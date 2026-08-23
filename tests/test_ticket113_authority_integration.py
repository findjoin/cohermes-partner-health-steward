import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from partner_health_steward import HealthCore, HealthPlugin
from partner_health_steward.admission import (
    AdmissionPolicy,
    RawWeixinMessage,
    materialize_source,
)
from partner_health_steward.answer_resolution import (
    FAILED_CLOSED_REPLY_TEXT,
    ModelAnswerResolution,
    ModelEffectRef,
    ModelEffectReport,
)
from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.contract import (
    CommandEnvelope,
    DailyTurnPreparePayload,
    EffectRequestPayload,
    EffectResultPayload,
    InboundAdmitPayload,
    StateCommitPayload,
)
from partner_health_steward.coordination import (
    CoarseMessageRouter,
    DailySkillAsset,
    DailySkillAttestor,
    DailySkillBundle,
    DailySkillRuntime,
    StewardContext,
    StewardPlan,
    StewardResolution,
    StewardResolutionContext,
)
from partner_health_steward.core import (
    InMemoryExecutionCapabilityVault,
    InMemoryWriterFenceVault,
)
from partner_health_steward.current_head import (
    FailureMode,
    HeadUnknown,
    InMemoryCurrentHead,
)
from partner_health_steward.initialization import (
    HealthInitAsset,
    HealthInitAttestor,
    HealthInitRuntime,
    InitialPreferences,
    OwnerConsentEvidence,
    OwnerInitialization,
    stable_digest,
)
from partner_health_steward.nondiagnostic import (
    ApprovedClaimAtom,
    ApprovedReplyTemplate,
    NonDiagnosticCandidate,
    NonDiagnosticReplyPipeline,
)
from partner_health_steward.storage import EncryptedStateStore, StaticKeyProvider


STRICT_REQUEST_DIGEST = "sha256:" + ("8" * 64)
MODEL_AUTHORITY_DIGEST = "sha256:" + ("9" * 64)
REQUESTED_MODEL = "synthetic-health-model"


class CountingBody:
    def __init__(self, text: str) -> None:
        self._text = text
        self.reads = 0

    def read(self) -> str:
        self.reads += 1
        return self._text


class MinimalAnswerExecutor:
    """Ticket 112 public executor seam with no evidence or portrait writes."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, skill_name: str, context: object) -> object:
        self.calls.append(skill_name)
        if skill_name != "health-steward":
            raise AssertionError(f"unexpected Skill execution: {skill_name}")
        if type(context) is StewardContext:
            return StewardPlan(
                purpose="answer-owner-health-question",
                selected_skills=(),
                atomic_claims=(),
            )
        if type(context) is StewardResolutionContext:
            return StewardResolution(
                commit_evidence_ids=context.candidate_evidence_ids,
                commit_portrait_topic_refs=context.candidate_portrait_topic_refs,
                reply_atom_ids=tuple(atom.atom_id for atom in context.reply_atoms),
                commit_evidence_change_ids=context.candidate_evidence_change_ids,
            )
        raise TypeError("unexpected steward context")


class LostReleaseResponseCurrentHead:
    """Lose one lease-release response after the authoritative mutation."""

    def __init__(self, delegate: InMemoryCurrentHead) -> None:
        self._delegate = delegate
        self._lose_release_once = True

    def read(self):
        return self._delegate.read()

    def validate_writer_fence(self, proof):
        return self._delegate.validate_writer_fence(proof)

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        return self._delegate.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        receipt = self._delegate.release_execution_lease(release)
        if self._lose_release_once:
            self._lose_release_once = False
            raise HeadUnknown("synthetic model effect release response lost")
        return receipt


class Ticket113AuthorityIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.writer_capability = "ticket113-authority-writer"
        self.store = EncryptedStateStore(
            f"file:ticket113-authority-{id(self)}?mode=memory&cache=shared",
            StaticKeyProvider(b"u" * 32, key_id="ticket113-authority-state-key"),
        )
        self.head = InMemoryCurrentHead(
            installation_id="ticket113-partner-installation",
            site="ticket113-partner-site",
            writer_capability=self.writer_capability,
        )
        authority = self.head.read().head.as_authority()
        self.store.seed_finalized_authority(authority)
        self.writer_vault = InMemoryWriterFenceVault()
        self.writer_vault.bind(authority, self.writer_capability)
        self.execution_vault = InMemoryExecutionCapabilityVault()
        self.policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-A",
            conversation_id="private-A",
        )
        self.init_attestor = HealthInitAttestor(
            b"a" * 32,
            key_id="ticket113-health-init-attestor",
        )
        self.init_asset = HealthInitAsset(
            version="1.0.0",
            asset_digest="sha256:" + ("1" * 64),
            disclosure_version="health-init-disclosure-v1",
        )
        self.init_runtime = HealthInitRuntime(
            self.init_asset,
            self.init_attestor,
            clock=lambda: datetime(2026, 8, 24, 0, 59, tzinfo=timezone.utc),
        )
        self.daily_attestor = DailySkillAttestor(
            b"s" * 32,
            key_id="ticket113-daily-skill-attestor",
        )
        self.daily_bundle = DailySkillBundle(
            tuple(
                DailySkillAsset(
                    canonical_name=canonical_name,
                    friendly_name=friendly_name,
                    role=role,
                    version="1.0.0",
                    asset_digest="sha256:" + (digit * 64),
                    disclosure_version="daily-skill-disclosure-v1",
                )
                for canonical_name, friendly_name, role, digit in (
                    ("health-steward", "健康管家", "A", "2"),
                    ("health-settings", "健康管家设置", "A", "3"),
                    ("health-portrait", "健康画像维护", "B", "4"),
                    ("health-evidence", "健康证据维护", "B", "5"),
                    ("health-owner-inquiry", "向主人补问", "B", "6"),
                    ("health-literature", "健康资料查找", "B", "7"),
                )
            )
        )
        self.executor = MinimalAnswerExecutor()
        self.daily_runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=self.executor,
            clock=lambda: datetime(2026, 8, 24, 1, 6, tzinfo=timezone.utc),
        )
        self.approved_claims = (
            ApprovedClaimAtom("claim-support", "support", "当前材料只支持有限事实。", "1.0.0"),
            ApprovedClaimAtom("claim-opposition", "opposition", "当前材料仍保留其他解释。", "1.0.0"),
            ApprovedClaimAtom("claim-unknown", "unknown", "目前仍有信息未知。", "1.0.0"),
            ApprovedClaimAtom("claim-limitation", "limitation", "这不是诊断或排除结论。", "1.0.0"),
            ApprovedClaimAtom("claim-next-step", "next-step", "如持续或加重，请寻求专业评估。", "1.0.0"),
        )
        self.approved_template = ApprovedReplyTemplate(
            "template-nondiagnostic-v1",
            "1.0.0",
            ("support", "opposition", "unknown", "limitation", "next-step"),
        )
        self.candidate = NonDiagnosticCandidate(
            owner_fact_refs=(),
            knowledge_refs=(),
            support=("claim-support",),
            opposition=("claim-opposition",),
            unknowns=("claim-unknown",),
            limitations=("claim-limitation",),
            next_steps=("claim-next-step",),
            claim_ids=tuple(claim.atom_id for claim in self.approved_claims),
            template_id=self.approved_template.template_id,
        )
        self.pipeline = NonDiagnosticReplyPipeline(
            current_owner_cards=(),
            current_knowledge_releases=(),
            approved_claims=self.approved_claims,
            approved_templates=(self.approved_template,),
        )
        self.rendered = self.pipeline.render(self.candidate)
        self.model_transport_calls = 0
        self._install_core(self.head)
        self._enable_product()

    def tearDown(self) -> None:
        self.core.close()
        self.store.close()

    def _install_core(self, current_head) -> None:
        self.core = HealthCore(
            self.store,
            current_head,
            execution_capability_vault=self.execution_vault,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
            daily_skill_verifier=self.daily_attestor,
            daily_skill_bundle=self.daily_bundle,
            model_authority_digest=MODEL_AUTHORITY_DIGEST,
            knowledge_releases=(),
            approved_claims=self.approved_claims,
            approved_templates=(self.approved_template,),
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=CoarseMessageRouter(lambda body, capability: "health"),
            daily_skill_runtime=self.daily_runtime,
        )

    def _reopen_with_head(self, current_head) -> None:
        self.core.close()
        self._install_core(current_head)

    def _initialization(self) -> OwnerInitialization:
        return OwnerInitialization(
            workflow_id="ticket113-init",
            admission_causal_id="ticket113-init-source",
            owner_consent=True,
            first_hop_route="jojo-responses-v1",
            first_hop_route_consent=True,
            timezone="Asia/Shanghai",
            preferences=InitialPreferences(
                contact_window="09:00-21:00",
                expression_style="concise",
                proactive_support=True,
            ),
            data_boundary=("health-portrait", "health-evidence", "health-tasks"),
            support_contact=None,
        )

    def _message(
        self,
        body: object,
        *,
        causal_id: str,
        message_id: str,
        native_cursor: str,
    ) -> RawWeixinMessage:
        return RawWeixinMessage(
            causal_id=causal_id,
            generation=self.head.read().head.generation,
            channel="weixin",
            partner_id="partner-A",
            sender_id="owner-A",
            conversation_id="private-A",
            chat_type="private",
            entrypoint="health_weixin",
            requested_capability=(
                "health-init" if causal_id == "ticket113-init-source" else "health-steward"
            ),
            message_id=message_id,
            protocol_timestamp="2026-08-24T09:00:00+08:00",
            received_at="2026-08-24T09:00:01+08:00",
            native_cursor=native_cursor,
            body=body,
        )

    def _enable_product(self) -> None:
        initialization = self._initialization()
        disclosure = self.plugin.form_initialization_disclosure(
            replace(
                initialization,
                owner_consent=False,
                first_hop_route_consent=False,
            ),
            peer_id="plugin",
        )
        consent = OwnerConsentEvidence.for_initialization(
            initialization,
            self.init_asset,
            disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
        )
        admitted = self.plugin.receive_weixin(
            self._message(
                CountingBody(consent.to_message_body()),
                causal_id="ticket113-init-source",
                message_id="wx-ticket113-init",
                native_cursor="cursor-ticket113-init",
            ),
            peer_id="plugin",
        )
        self.assertEqual(admitted.status, "accepted")
        self.assertEqual(
            self.plugin.prepare_initialization(initialization, peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(self.plugin.commit_initialization(peer_id="plugin").status, "accepted")
        self.assertEqual(self.plugin.finalize_initialization(peer_id="plugin").status, "accepted")

    def _command(self, action: str, causal_id: str, payload, *, generation=None):
        scopes = {
            "inbound.admit": "inbound:admit",
            "turn.prepare": "turn:prepare",
            "state.commit": "state:commit",
            "state.finalize": "state:finalize",
            "effect.request": "effect:request",
            "effect.result": "effect:result",
        }
        return CommandEnvelope(
            peer="plugin",
            action=action,
            source=(
                "health_weixin"
                if action == "inbound.admit"
                else "ticket113_authority_test"
            ),
            causal_id=causal_id,
            generation=(
                self.head.read().head.generation
                if generation is None
                else generation
            ),
            scope=(scopes[action],),
            payload=payload,
        )

    def _admit_daily_source(self, suffix: str):
        message = self._message(
            CountingBody("模型不得复制的自由正文 sentinel-model-body"),
            causal_id=f"ticket113-{suffix}",
            message_id=f"wx-ticket113-{suffix}",
            native_cursor=f"cursor-ticket113-{suffix}",
        )
        source = materialize_source(message)
        admitted = self.plugin.invoke(
            self._command(
                "inbound.admit",
                source.causal_id,
                InboundAdmitPayload(source, self.policy),
                generation=message.generation,
            ),
            peer_id="plugin",
        )
        self.assertEqual(admitted.status, "accepted")
        return message, source

    def _prepare_evidence_stage(self, source) -> None:
        with self.core.daily_turn_runtime_preparation(source.causal_id) as preparation:
            self.assertTrue(preparation.ready)
            stage = self.daily_runtime.execute_evidence_stage(
                source,
                self.core.daily_state(),
            )
            prepared = self.plugin.invoke(
                self._command(
                    "turn.prepare",
                    f"ticket113-evidence-prepare-{source.causal_id}",
                    DailyTurnPreparePayload(stage),
                    generation=preparation.generation,
                ),
                peer_id="plugin",
            )
        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        commit = self._transition_command(source.causal_id, "state.commit")
        self.assertEqual(
            self.plugin.invoke(commit, peer_id="plugin").status,
            "accepted",
        )
        finalize = self._transition_command(source.causal_id, "state.finalize")
        self.assertEqual(
            self.plugin.invoke(finalize, peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(self.core.daily_turn_status(source.causal_id).phase, "evidence-finalized")

    def _prepare_complete(
        self,
        source,
        resolution: ModelAnswerResolution,
        *,
        candidate: NonDiagnosticCandidate | None = None,
    ):
        status = self.core.daily_turn_status(source.causal_id)
        self.assertEqual(status.phase, "evidence-finalized")
        with self.core.daily_turn_runtime_preparation(
            source.causal_id,
            committed_evidence_stage=status.draft,
        ) as preparation:
            self.assertTrue(preparation.ready)
            model_atoms = () if candidate is None else self.rendered.reply_atoms
            draft = self.daily_runtime.complete(
                source,
                self.core.daily_turn_post_stage_state(source.causal_id),
                status.draft,
                model_answer_resolution=resolution,
                model_reply_atoms=model_atoms,
            )
            command = self._command(
                "turn.prepare",
                f"ticket113-complete-prepare-{source.causal_id}",
                DailyTurnPreparePayload(draft, candidate=candidate),
                generation=preparation.generation,
            )
            prepared = self.plugin.invoke(command, peer_id="plugin")
        return command, prepared

    def _transition_command(self, source_causal_id: str, action: str):
        status = self.core.daily_turn_status(source_causal_id)
        self.assertIsNotNone(status.draft)
        self.assertNotEqual(status.phase, "evidence-finalized")
        authority = status.prepared_authority
        generation = authority.generation if action == "state.commit" else authority.generation + 1
        turn_stage = "evidence" if status.draft.turn_kind == "evidence-stage" else "complete"
        return self._command(
            action,
            f"ticket113-{turn_stage}-{action}-{source_causal_id}",
            StateCommitPayload(
                status.draft.record_id,
                status.draft.revision_digest,
                status.draft.transition_id,
                authority.writer_fence,
            ),
            generation=generation,
        )

    def _finalize_complete(self, source_causal_id: str):
        commit = self._transition_command(source_causal_id, "state.commit")
        committed = self.plugin.invoke(commit, peer_id="plugin")
        self.assertEqual(committed.status, "accepted", committed.to_wire())
        finalize = self._transition_command(source_causal_id, "state.finalize")
        finalized = self.plugin.invoke(finalize, peer_id="plugin")
        self.assertEqual(finalized.status, "accepted", finalized.to_wire())
        return self.core.daily_turn_result(source_causal_id), commit, finalize

    def _failed_resolution(
        self,
        reason_code: str,
        effect_ref: ModelEffectRef | None = None,
    ) -> ModelAnswerResolution:
        return ModelAnswerResolution.failed_closed(
            strict_request_digest=STRICT_REQUEST_DIGEST,
            model_authority_digest=MODEL_AUTHORITY_DIGEST,
            reason_code=reason_code,
            effect_ref=effect_ref,
        )

    def _model_report(
        self,
        model_status: str,
        *,
        reason_code: str | None,
    ) -> ModelEffectReport:
        attempted = model_status != "not-started"
        if attempted:
            self.model_transport_calls += 1
        return ModelEffectReport(
            model_status=model_status,
            transport_attempted=attempted,
            terminal_proven=model_status not in {"not-started", "unknown"},
            requested_model=REQUESTED_MODEL,
            actual_model=(
                REQUESTED_MODEL
                if model_status in {"completed", "incomplete", "failed"}
                else None
            ),
            fallback_observed=False,
            truncated=False,
            reason_code=reason_code,
            result_digest="sha256:" + ({
                "not-started": "a",
                "completed": "b",
                "incomplete": "c",
                "failed": "d",
                "unknown": "e",
            }[model_status] * 64),
        )

    def _issue_model_report(self, suffix: str, report: ModelEffectReport):
        issued = self.plugin.invoke(
            self._command(
                "effect.request",
                f"ticket113-effect-request-{suffix}",
                EffectRequestPayload("model-work", STRICT_REQUEST_DIGEST),
            ),
            peer_id="plugin",
        )
        self.assertEqual(issued.status, "accepted", issued.to_wire())
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        payload = EffectResultPayload(
            effect_id=issued.meta["effect_id"],
            intent_digest=issued.meta["intent_digest"],
            lease_id=grant.lease.lease_id,
            completion_capability=grant.completion_capability,
            status=report.outer_effect_status,
            terminal=True,
            result_digest=report.digest,
            model_report=report,
        )
        command = self._command(
            "effect.result",
            f"ticket113-effect-result-{suffix}",
            payload,
        )
        response = self.plugin.invoke(command, peer_id="plugin")
        return issued.meta, grant, command, response

    def _rendered_resolution(self, effect_ref: ModelEffectRef) -> ModelAnswerResolution:
        return ModelAnswerResolution.rendered(
            strict_request_digest=STRICT_REQUEST_DIGEST,
            model_authority_digest=MODEL_AUTHORITY_DIGEST,
            template_id=self.approved_template.template_id,
            template_version=self.approved_template.version,
            template_digest=stable_digest(self.approved_template.to_wire()),
            effect_ref=effect_ref,
            candidate_digest=stable_digest(self.candidate.to_wire()),
            rendered_reply_digest=stable_digest(self.rendered.to_commit_wire()),
        )

    def test_113_a6_c01_pre_call_reject_commits_failed_closed_without_body(self) -> None:
        _, source = self._admit_daily_source("pre-call-reject")
        self._prepare_evidence_stage(source)

        resolution = self._failed_resolution("provider-drift")
        _, prepared = self._prepare_complete(source, resolution)
        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        result, _, _ = self._finalize_complete(source.causal_id)

        self.assertEqual(self.store.count_effects(), 0)
        self.assertEqual(result.answer_status, "failed-closed")
        self.assertEqual(result.answer_resolution_digest, resolution.digest)
        self.assertIn(FAILED_CLOSED_REPLY_TEXT, result.owner_reply)
        self.assertNotIn("sentinel-model-body", result.owner_reply)
        self.assertIsNotNone(
            self.plugin.native_cursor_directive(source.causal_id, peer_id="plugin")
        )

    def test_113_a6_c02_explicit_model_failure_commits_failed_closed_without_body(self) -> None:
        _, source = self._admit_daily_source("explicit-model-failure")
        self._prepare_evidence_stage(source)
        report = self._model_report("failed", reason_code="provider-failed")

        intent, _, _, effect_response = self._issue_model_report(
            "explicit-model-failure",
            report,
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        resolution = self._failed_resolution(
            "provider-failed",
            ModelEffectRef(intent["effect_id"], report.digest),
        )
        _, prepared = self._prepare_complete(source, resolution)
        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        result, _, _ = self._finalize_complete(source.causal_id)

        self.assertEqual(self.model_transport_calls, 1)
        self.assertEqual(self.store.effect_state(intent["effect_id"]), "accepted")
        self.assertEqual(result.answer_status, "failed-closed")
        self.assertIn(FAILED_CLOSED_REPLY_TEXT, result.owner_reply)
        self.assertNotIn("sentinel-model-body", result.owner_reply)

    def test_113_a6_c03_effect_response_loss_freezes_retry(self) -> None:
        message, source = self._admit_daily_source("effect-response-loss")
        self._prepare_evidence_stage(source)
        self._reopen_with_head(LostReleaseResponseCurrentHead(self.head))
        report = self._model_report("failed", reason_code="provider-failed")

        intent, _, effect_command, first = self._issue_model_report(
            "effect-response-loss",
            report,
        )

        self.assertEqual(first.status, "unknown")
        self.assertEqual(first.reason_code, "effect-lease-unknown")
        self.assertEqual(self.store.effect_state(intent["effect_id"]), "executing")
        self.assertEqual(self.core.daily_turn_status(source.causal_id).phase, "evidence-finalized")
        self.assertIsNone(
            self.plugin.native_cursor_directive(source.causal_id, peer_id="plugin")
        )
        self.assertEqual(self.model_transport_calls, 1)

        recovered = self.plugin.invoke(effect_command, peer_id="plugin")
        self.assertEqual(recovered.status, "accepted", recovered.to_wire())
        resolution = self._failed_resolution(
            "provider-failed",
            ModelEffectRef(intent["effect_id"], report.digest),
        )
        _, prepared = self._prepare_complete(source, resolution)
        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        result, _, _ = self._finalize_complete(source.causal_id)

        self.assertEqual(self.model_transport_calls, 1)
        self.assertEqual(self.store.count_effects(), 1)
        self.assertEqual(result.owner_reply.count(FAILED_CLOSED_REPLY_TEXT), 1)
        replay = self.plugin.receive_weixin(message, peer_id="plugin")
        self.assertIn(replay.status, {"accepted", "replayed"}, replay.to_wire())
        self.assertEqual(self.model_transport_calls, 1)

    def test_113_a6_c04_current_head_unknown_freezes_retry(self) -> None:
        _, source = self._admit_daily_source("current-head-unknown")
        self._prepare_evidence_stage(source)
        report = self._model_report("failed", reason_code="provider-failed")
        intent, _, _, effect_response = self._issue_model_report(
            "current-head-unknown",
            report,
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        resolution = self._failed_resolution(
            "provider-failed",
            ModelEffectRef(intent["effect_id"], report.digest),
        )
        _, prepared = self._prepare_complete(source, resolution)
        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        commit = self._transition_command(source.causal_id, "state.commit")
        self.head.set_failure(FailureMode.UNKNOWN, operation="advance")

        first = self.plugin.invoke(commit, peer_id="plugin")

        self.assertEqual(first.status, "unknown")
        self.assertEqual(self.core.daily_turn_status(source.causal_id).phase, "unknown")
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "current-head-recovery-required",
        ):
            self.core.daily_turn_result(source.causal_id)
        self.assertIsNone(
            self.plugin.native_cursor_directive(source.causal_id, peer_id="plugin")
        )
        calls_at_unknown = self.model_transport_calls
        replay = self.plugin.invoke(commit, peer_id="plugin")
        self.assertNotEqual(replay.status, "accepted")
        self.assertEqual(self.core.daily_turn_status(source.causal_id).phase, "unknown")
        self.assertEqual(self.model_transport_calls, calls_at_unknown)
        self.assertEqual(self.store.count_effects(), 1)

    def test_113_a6_c05_finalize_unknown_freezes_retry(self) -> None:
        _, source = self._admit_daily_source("finalize-unknown")
        self._prepare_evidence_stage(source)
        report = self._model_report("failed", reason_code="provider-failed")
        intent, _, _, effect_response = self._issue_model_report(
            "finalize-unknown",
            report,
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        resolution = self._failed_resolution(
            "provider-failed",
            ModelEffectRef(intent["effect_id"], report.digest),
        )
        _, prepared = self._prepare_complete(source, resolution)
        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        commit = self._transition_command(source.causal_id, "state.commit")
        self.assertEqual(self.plugin.invoke(commit, peer_id="plugin").status, "accepted")
        finalize = self._transition_command(source.causal_id, "state.finalize")
        self.head.set_failure(FailureMode.UNKNOWN, operation="read")

        first = self.plugin.invoke(finalize, peer_id="plugin")

        self.assertEqual(first.status, "unknown")
        self.assertIsNone(
            self.plugin.native_cursor_directive(source.causal_id, peer_id="plugin")
        )
        calls_at_unknown = self.model_transport_calls
        self.head.clear_failure()
        recovered = self.plugin.invoke(finalize, peer_id="plugin")
        self.assertEqual(recovered.status, "accepted", recovered.to_wire())
        result = self.core.daily_turn_result(source.causal_id)
        self.assertEqual(result.answer_status, "failed-closed")
        self.assertEqual(result.owner_reply.count(FAILED_CLOSED_REPLY_TEXT), 1)
        self.assertEqual(self.model_transport_calls, calls_at_unknown)
        self.assertIsNotNone(
            self.plugin.native_cursor_directive(source.causal_id, peer_id="plugin")
        )

    def test_113_a6_c06_replay_never_creates_a_second_effect_or_reply(self) -> None:
        message, source = self._admit_daily_source("rendered-replay")
        self._prepare_evidence_stage(source)
        report = self._model_report("completed", reason_code=None)
        intent, _, effect_command, effect_response = self._issue_model_report(
            "rendered-replay",
            report,
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        resolution = self._rendered_resolution(
            ModelEffectRef(intent["effect_id"], report.digest)
        )
        prepare_command, prepared = self._prepare_complete(
            source,
            resolution,
            candidate=self.candidate,
        )
        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        persisted_draft = json.dumps(
            self.core.daily_turn_status(source.causal_id).draft.to_storage(),
            ensure_ascii=False,
            sort_keys=True,
        )
        result, _, _ = self._finalize_complete(source.causal_id)
        calls_after_final = tuple(self.executor.calls)

        replayed_effect = self.plugin.invoke(effect_command, peer_id="plugin")
        replayed_prepare = self.plugin.invoke(prepare_command, peer_id="plugin")
        replayed_source = self.plugin.receive_weixin(message, peer_id="plugin")

        self.assertEqual(replayed_effect.to_wire(), effect_response.to_wire())
        self.assertEqual(replayed_prepare.to_wire(), prepared.to_wire())
        self.assertIn(
            replayed_source.status,
            {"accepted", "replayed"},
            replayed_source.to_wire(),
        )
        self.assertEqual(self.store.count_effects(), 1)
        self.assertEqual(self.model_transport_calls, 1)
        self.assertEqual(tuple(self.executor.calls), calls_after_final)
        rendered_owner_text = "".join(atom.text for atom in self.rendered.reply_atoms)
        self.assertEqual(result.owner_reply.count(rendered_owner_text), 1)
        replay_result = self.core.daily_turn_result(source.causal_id)
        self.assertEqual(replay_result.transition_id, result.transition_id)
        self.assertEqual(replay_result.owner_reply, result.owner_reply)
        self.assertNotIn('"claim_ids"', persisted_draft)
        self.assertNotIn('"support"', persisted_draft)

    def test_113_a6_c07_known_no_effect_failure_releases_cursor(self) -> None:
        _, source = self._admit_daily_source("known-no-effect")
        self._prepare_evidence_stage(source)
        report = self._model_report("not-started", reason_code="capacity-unavailable")
        intent, _, _, effect_response = self._issue_model_report(
            "known-no-effect",
            report,
        )
        self.assertEqual(effect_response.status, "rejected", effect_response.to_wire())
        self.assertEqual(self.model_transport_calls, 0)
        resolution = self._failed_resolution(
            "capacity-unavailable",
            ModelEffectRef(intent["effect_id"], report.digest),
        )
        _, prepared = self._prepare_complete(source, resolution)
        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        result, _, _ = self._finalize_complete(source.causal_id)

        self.assertEqual(self.store.effect_state(intent["effect_id"]), "rejected")
        self.assertEqual(result.answer_status, "failed-closed")
        directive = self.plugin.native_cursor_directive(source.causal_id, peer_id="plugin")
        self.assertIsNotNone(directive)
        self.assertEqual(
            self.plugin.source_receipt(source.causal_id, peer_id="plugin").managed_cursor_state,
            "committed",
        )

    def test_113_a6_c08_unknown_effect_freezes_cursor(self) -> None:
        _, source = self._admit_daily_source("unknown-effect")
        self._prepare_evidence_stage(source)
        report = self._model_report("unknown", reason_code="transport-result-unknown")

        intent, _, _, response = self._issue_model_report("unknown-effect", report)

        self.assertEqual(response.status, "unknown")
        self.assertEqual(self.store.effect_state(intent["effect_id"]), "unknown")
        self.assertEqual(self.model_transport_calls, 1)
        status = self.core.daily_turn_status(source.causal_id)
        self.assertEqual(status.phase, "evidence-finalized")
        self.assertIsNone(status.result)
        self.assertIsNone(
            self.plugin.native_cursor_directive(source.causal_id, peer_id="plugin")
        )


if __name__ == "__main__":
    unittest.main()

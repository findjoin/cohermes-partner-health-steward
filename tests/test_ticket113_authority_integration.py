import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone, tzinfo

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
from partner_health_steward.authority import (
    AuthoritySnapshot,
    AuthorityValidationError,
    EffectExecutionGrant,
    ExecutionLease,
    holder_id_for,
)
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
    OwnerReplyAtom,
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
from partner_health_steward.model_contract import (
    CapabilityProfile,
    FirstHopRoute,
    ModelMessage,
    ModelTransportResult,
    StrictHealthLLM,
    StrictModelOutcome,
    StrictModelRequest,
)
from partner_health_steward.knowledge import (
    KnowledgePublicationInput,
    KnowledgePublisher,
    KnowledgeRelease,
)
from partner_health_steward.nondiagnostic import (
    ApprovedClaimAtom,
    ApprovedReplyTemplate,
    CardReference,
    NonDiagnosticCandidate,
    NonDiagnosticReplyPipeline,
)
from partner_health_steward.storage import EncryptedStateStore, StaticKeyProvider


REQUESTED_MODEL = "synthetic-health-model"


def _model_route() -> FirstHopRoute:
    return FirstHopRoute(
        route_id="partner-first-hop",
        provider="synthetic-provider",
        canonical_base_url="https://model.example/v1",
        api_mode="responses",
        requested_model=REQUESTED_MODEL,
        configuration_generation=7,
        owner_consent_fingerprint="sha256:" + "a" * 64,
    )


def _model_profile() -> CapabilityProfile:
    return CapabilityProfile(
        profile_id="synthetic-profile",
        profile_version="1.0.0",
        synthetic=True,
        route_id="partner-first-hop",
        provider="synthetic-provider",
        canonical_base_url="https://model.example/v1",
        api_mode="responses",
        requested_model=REQUESTED_MODEL,
        allowed_actual_models=(REQUESTED_MODEL,),
        configuration_generation=7,
        input_measurement_method="synthetic-utf8-byte-upper-bound-v1",
        fixed_wrapper_tokens=96,
        output_reservation_tokens=512,
        common_context_lower_bound_tokens=4096,
        evidence_refs=("synthetic-contract-evidence",),
        invalidation_conditions=("route-change", "measurement-method-change"),
    )


def _strict_model_request() -> StrictModelRequest:
    messages = (
        ModelMessage("system", "synthetic policy"),
        ModelMessage("user", "synthetic health question"),
    )
    return StrictModelRequest(
        route=_model_route(),
        capability_profile=_model_profile(),
        messages=messages,
        final_input_digest=stable_digest(
            {"messages": [message.to_wire() for message in messages]}
        ),
        final_input_upper_bound_tokens=3000,
        output_reservation_tokens=512,
        strict_schema_name="nondiagnostic-candidate-v1",
        strict_schema_digest="sha256:" + "b" * 64,
    )


STRICT_REQUEST_DIGEST = _strict_model_request().digest
MODEL_AUTHORITY_DIGEST = StrictHealthLLM(
    _model_route(),
    _model_profile(),
).model_authority_digest


class CountingBody:
    def __init__(self, text: str) -> None:
        self._text = text
        self.reads = 0

    def read(self) -> str:
        self.reads += 1
        return self._text


class NeverCalledModelAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, payload: object):
        self.calls += 1
        raise AssertionError("forged model authority reached the adapter")


class RecordingResultAdapter:
    def __init__(self, result: ModelTransportResult) -> None:
        self.result = result
        self.calls = 0

    def execute(self, payload: object) -> ModelTransportResult:
        self.calls += 1
        return self.result


class RaisingModelAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, payload: object) -> ModelTransportResult:
        self.calls += 1
        raise TimeoutError("synthetic response ownership is unknown")


class CorruptingResultAdapter:
    def __init__(self, result: ModelTransportResult) -> None:
        self.result = result
        self.calls = 0

    def execute(self, payload: object) -> ModelTransportResult:
        self.calls += 1
        object.__setattr__(self.result, "structured_output", [])
        return self.result


class ExecuteDescriptorTrap:
    def __init__(self) -> None:
        self.touches = 0

    @property
    def execute(self):
        self.touches += 1
        return lambda payload: None


class RoutePropertyTrap:
    def __init__(self) -> None:
        self.touches = 0

    def __getattr__(self, name: str) -> object:
        self.touches += 1
        return "trap-route-value"


class IterableTrap:
    def __init__(self) -> None:
        self.touches = 0

    def __iter__(self):
        self.touches += 1
        return iter(("synthetic-trap-model",))


class HashTrap:
    def __init__(self) -> None:
        self.touches = 0

    def __hash__(self) -> int:
        self.touches += 1
        return hash("user")


class LeasePropertyTrap:
    def __init__(self) -> None:
        self.touches = 0

    def __getattr__(self, name: str) -> object:
        self.touches += 1
        if name == "intent_digest":
            return "sha256:" + "0" * 64
        raise AttributeError(name)


class RaisingTimezone(tzinfo):
    def utcoffset(self, value):
        raise RuntimeError("synthetic timezone offset failure")

    def dst(self, value):
        return None

    def tzname(self, value):
        return "synthetic-raising-timezone"


class MinimalAnswerExecutor:
    """Ticket 112 public executor seam with no evidence or portrait writes."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.reverse_model_direct_results = False

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
            selected_ids = [atom.atom_id for atom in context.reply_atoms]
            if self.reverse_model_direct_results:
                model_direct_indexes = [
                    index
                    for index, atom in enumerate(context.reply_atoms)
                    if atom.source_skill == "health-steward"
                    and atom.kind == "direct-result"
                ]
                reversed_ids = [
                    selected_ids[index]
                    for index in reversed(model_direct_indexes)
                ]
                for index, atom_id in zip(model_direct_indexes, reversed_ids):
                    selected_ids[index] = atom_id
            return StewardResolution(
                commit_evidence_ids=context.candidate_evidence_ids,
                commit_portrait_topic_refs=context.candidate_portrait_topic_refs,
                reply_atom_ids=tuple(selected_ids),
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
            knowledge_valid_at="2026-08-24T01:06:00+00:00",
            approved_claims=self.approved_claims,
            approved_templates=(self.approved_template,),
        )
        self.rendered = self.pipeline.render(self.candidate)
        self.knowledge_releases: tuple[KnowledgeRelease, ...] = ()
        self.knowledge_now = datetime(2026, 8, 24, 1, 6, tzinfo=timezone.utc)
        self.model_transport_calls = 0
        self._install_core(self.head)
        self._enable_product()

    def tearDown(self) -> None:
        self.core.close()
        self.store.close()

    def test_forged_execution_grant_cannot_create_a_controlled_model_effect(self) -> None:
        capability = "capability:forged-ticket113-model"
        forged = EffectExecutionGrant(
            lease=ExecutionLease(
                lease_id="lease:forged-ticket113-model",
                effect_id="effect:forged-ticket113-model",
                intent_digest=STRICT_REQUEST_DIGEST,
                authority=AuthoritySnapshot(
                    installation_id="installation:forged-ticket113",
                    generation=1,
                    revision_digest="revision:forged-ticket113",
                    transition_id="transition:forged-ticket113",
                    writer_fence="writer-fence:forged-ticket113",
                    terminal=False,
                    site="site:forged-ticket113",
                ),
                holder_id=holder_id_for(capability),
            ),
            completion_capability=capability,
        )
        adapter = NeverCalledModelAdapter()

        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            _strict_model_request(),
            "ticket113-forged-model-authority",
            forged,
            adapter,
        )

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(
            outcome.reason_code,
            "model-effect-authorization-required",
        )
        self.assertEqual(adapter.calls, 0)

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
            knowledge_releases=self.knowledge_releases,
            knowledge_valid_at=self.knowledge_now.isoformat(),
            knowledge_clock=lambda: self.knowledge_now,
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
        extra_model_atoms: tuple[OwnerReplyAtom, ...] = (),
    ):
        status = self.core.daily_turn_status(source.causal_id)
        self.assertEqual(status.phase, "evidence-finalized")
        with self.core.daily_turn_runtime_preparation(
            source.causal_id,
            committed_evidence_stage=status.draft,
        ) as preparation:
            self.assertTrue(preparation.ready)
            model_atoms = ()
            if candidate is not None:
                model_atoms = (
                    self.pipeline.render(candidate).reply_atoms
                    + extra_model_atoms
                )
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
        *,
        strict_request_digest: str = STRICT_REQUEST_DIGEST,
    ) -> ModelAnswerResolution:
        return ModelAnswerResolution.failed_closed(
            strict_request_digest=strict_request_digest,
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
            candidate_digest=(
                stable_digest(self.candidate.to_wire())
                if model_status == "completed" and reason_code is None
                else None
            ),
        )

    def _issue_model_report(self, suffix: str, report: ModelEffectReport):
        issued = self.plugin.invoke(
            self._command(
                "effect.request",
                f"ticket113-effect-request-{suffix}",
                EffectRequestPayload(
                    "model-work",
                    STRICT_REQUEST_DIGEST,
                    f"ticket113-{suffix}",
                ),
            ),
            peer_id="plugin",
        )
        self.assertEqual(issued.status, "accepted", issued.to_wire())
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        result_values: dict[str, object] = {
            "response_id": f"synthetic-response-{suffix}",
            "requested_model": REQUESTED_MODEL,
            "actual_model": REQUESTED_MODEL,
            "status": report.model_status,
            "incomplete_reason": None,
            "failure_reason": None,
            "usage_input_tokens": 3000,
            "usage_output_tokens": 256,
            "fallback_observed": report.fallback_observed,
            "truncated": report.truncated,
            "terminal_proven": report.terminal_proven,
            "structured_output": None,
        }
        if report.model_status == "completed":
            result_values["structured_output"] = self.candidate.to_wire()
        elif report.model_status == "incomplete":
            result_values["incomplete_reason"] = "max-output-tokens"
        elif report.model_status == "failed":
            result_values["failure_reason"] = "provider-failed"
        transport = ModelTransportResult.from_wire(result_values)
        adapter = RecordingResultAdapter(transport)
        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            _strict_model_request(),
            f"ticket113-{suffix}",
            grant,
            adapter,
        )
        self.model_transport_calls += adapter.calls
        observed_report = outcome.model_report
        self.assertIsNotNone(observed_report)
        payload = EffectResultPayload(
            effect_id=issued.meta["effect_id"],
            intent_digest=issued.meta["intent_digest"],
            lease_id=grant.lease.lease_id,
            completion_capability=grant.completion_capability,
            status=observed_report.outer_effect_status,
            terminal=True,
            result_digest=observed_report.digest,
            model_report=observed_report,
        )
        command = self._command(
            "effect.result",
            f"ticket113-effect-result-{suffix}",
            payload,
        )
        response = self.plugin.invoke(command, peer_id="plugin")
        return issued.meta, grant, command, response, observed_report

    def _start_controlled_completed_model(self, suffix: str):
        request = _strict_model_request()
        issued = self.plugin.invoke(
            self._command(
                "effect.request",
                f"ticket113-effect-request-{suffix}",
                EffectRequestPayload(
                    "model-work",
                    request.digest,
                    f"ticket113-{suffix}",
                ),
            ),
            peer_id="plugin",
        )
        self.assertEqual(issued.status, "accepted", issued.to_wire())
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        transport = ModelTransportResult.from_wire(
            {
                "response_id": f"synthetic-response-{suffix}",
                "requested_model": REQUESTED_MODEL,
                "actual_model": REQUESTED_MODEL,
                "status": "completed",
                "incomplete_reason": None,
                "failure_reason": None,
                "usage_input_tokens": 3000,
                "usage_output_tokens": 256,
                "fallback_observed": False,
                "truncated": False,
                "terminal_proven": True,
                "structured_output": self.candidate.to_wire(),
            }
        )
        adapter = RecordingResultAdapter(transport)
        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            request,
            f"ticket113-{suffix}",
            grant,
            adapter,
        )
        self.assertEqual(outcome.disposition, "candidate")
        self.assertIsNotNone(outcome.model_report)
        self.model_transport_calls += adapter.calls
        candidate = NonDiagnosticCandidate.from_wire(outcome.candidate)
        return issued.meta, grant, outcome, candidate, adapter

    def _issue_controlled_completed_model(self, suffix: str):
        issued, grant, outcome, candidate, _ = (
            self._start_controlled_completed_model(suffix)
        )
        report = outcome.model_report
        payload = EffectResultPayload(
            effect_id=issued["effect_id"],
            intent_digest=issued["intent_digest"],
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
        return issued, outcome, candidate, command, response

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

        request = _strict_model_request()
        drifted = replace(
            request,
            route=replace(request.route, provider="different-provider"),
        )
        adapter = NeverCalledModelAdapter()
        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            drifted,
            source.causal_id,
            None,
            adapter,
        )
        self.assertEqual(outcome.reason_code, "provider-drift")
        self.assertEqual(adapter.calls, 0)
        resolution = self._failed_resolution(
            outcome.reason_code,
            strict_request_digest=drifted.digest,
        )
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

    def test_missing_controlled_effect_closes_as_a_pre_call_failure(self) -> None:
        _, source = self._admit_daily_source("missing-controlled-effect")
        self._prepare_evidence_stage(source)
        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            _strict_model_request(),
            source.causal_id,
            None,
            NeverCalledModelAdapter(),
        )
        self.assertEqual(
            outcome.reason_code,
            "model-effect-authorization-required",
        )
        resolution = self._failed_resolution(outcome.reason_code)

        _, prepared = self._prepare_complete(source, resolution)

        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        result, _, _ = self._finalize_complete(source.causal_id)
        self.assertEqual(result.answer_status, "failed-closed")
        self.assertIn(FAILED_CLOSED_REPLY_TEXT, result.owner_reply)
        self.assertEqual(self.store.count_effects(), 0)

    def test_unobserved_pre_call_failure_cannot_consume_the_source(self) -> None:
        _, source = self._admit_daily_source("unobserved-pre-call")
        self._prepare_evidence_stage(source)
        forged = self._failed_resolution("provider-drift")

        _, prepared = self._prepare_complete(source, forged)

        self.assertEqual(prepared.status, "rejected", prepared.to_wire())
        self.assertEqual(
            prepared.reason_code,
            "model-preflight-observation-required",
        )
        self.assertIsNone(
            self.plugin.native_cursor_directive(source.causal_id, peer_id="plugin")
        )

    def test_corrupt_strict_request_fails_closed_without_preflight_observation(self) -> None:
        _, source = self._admit_daily_source("corrupt-strict-request")
        self._prepare_evidence_stage(source)
        request = _strict_model_request()
        original_digest = request.digest
        object.__setattr__(request, "route", None)
        adapter = NeverCalledModelAdapter()

        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            request,
            source.causal_id,
            None,
            adapter,
        )

        self.assertEqual(outcome.reason_code, "model-effect-authorization-required")
        self.assertEqual(adapter.calls, 0)
        forged = self._failed_resolution(
            outcome.reason_code,
            strict_request_digest=original_digest,
        )
        _, prepared = self._prepare_complete(source, forged)
        self.assertEqual(prepared.status, "rejected", prepared.to_wire())
        self.assertEqual(
            prepared.reason_code,
            "model-preflight-observation-required",
        )

    def test_instance_shadowed_preflight_cannot_create_consumable_failure(self) -> None:
        _, source = self._admit_daily_source("shadowed-model-preflight")
        self._prepare_evidence_stage(source)
        llm = StrictHealthLLM(_model_route(), _model_profile())
        llm.preflight = lambda request: StrictModelOutcome(  # type: ignore[method-assign]
            disposition="failed-closed",
            model_effect="not-started",
            reason_code="capacity-unavailable",
            candidate=None,
        )
        adapter = NeverCalledModelAdapter()

        outcome = self.plugin.execute_strict_health_model(
            llm,
            _strict_model_request(),
            source.causal_id,
            None,
            adapter,
        )

        self.assertEqual(
            outcome.reason_code,
            "model-effect-authorization-required",
        )
        self.assertEqual(adapter.calls, 0)
        forged = self._failed_resolution("capacity-unavailable")
        _, prepared = self._prepare_complete(source, forged)
        self.assertEqual(prepared.status, "rejected", prepared.to_wire())
        self.assertEqual(
            prepared.reason_code,
            "model-preflight-observation-required",
        )

    def test_corrupt_request_route_trap_is_not_dereferenced(self) -> None:
        request = _strict_model_request()
        trap = RoutePropertyTrap()
        object.__setattr__(request, "route", trap)
        adapter = NeverCalledModelAdapter()

        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            request,
            "ticket113-missing-request-route-trap-source",
            None,
            adapter,
        )

        self.assertEqual(
            outcome.reason_code,
            "model-effect-authorization-required",
        )
        self.assertEqual(trap.touches, 0)
        self.assertEqual(adapter.calls, 0)

    def test_corrupt_llm_route_trap_is_not_dereferenced(self) -> None:
        llm = StrictHealthLLM(_model_route(), _model_profile())
        trap = RoutePropertyTrap()
        object.__setattr__(llm, "_route", trap)
        adapter = NeverCalledModelAdapter()

        outcome = self.plugin.execute_strict_health_model(
            llm,
            _strict_model_request(),
            "ticket113-missing-llm-route-trap-source",
            None,
            adapter,
        )

        self.assertEqual(
            outcome.reason_code,
            "model-effect-authorization-required",
        )
        self.assertEqual(trap.touches, 0)
        self.assertEqual(adapter.calls, 0)

    def test_corrupt_request_profile_iterable_is_not_touched(self) -> None:
        request = _strict_model_request()
        trap = IterableTrap()
        object.__setattr__(
            request.capability_profile,
            "allowed_actual_models",
            trap,
        )
        adapter = NeverCalledModelAdapter()

        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            request,
            "ticket113-missing-request-profile-trap-source",
            None,
            adapter,
        )

        self.assertEqual(
            outcome.reason_code,
            "model-effect-authorization-required",
        )
        self.assertEqual(trap.touches, 0)
        self.assertEqual(adapter.calls, 0)

    def test_corrupt_llm_profile_iterable_is_not_touched(self) -> None:
        llm = StrictHealthLLM(_model_route(), _model_profile())
        trap = IterableTrap()
        object.__setattr__(
            llm._capability_profile,
            "allowed_actual_models",
            trap,
        )
        adapter = NeverCalledModelAdapter()

        outcome = self.plugin.execute_strict_health_model(
            llm,
            _strict_model_request(),
            "ticket113-missing-llm-profile-trap-source",
            None,
            adapter,
        )

        self.assertEqual(
            outcome.reason_code,
            "model-effect-authorization-required",
        )
        self.assertEqual(trap.touches, 0)
        self.assertEqual(adapter.calls, 0)

    def test_corrupt_model_message_role_hash_is_not_touched(self) -> None:
        request = _strict_model_request()
        trap = HashTrap()
        object.__setattr__(request.messages[0], "role", trap)
        adapter = NeverCalledModelAdapter()

        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            request,
            "ticket113-missing-message-role-trap-source",
            None,
            adapter,
        )

        self.assertEqual(
            outcome.reason_code,
            "model-effect-authorization-required",
        )
        self.assertEqual(trap.touches, 0)
        self.assertEqual(adapter.calls, 0)

    def test_corrupt_execution_grant_lease_trap_fails_closed_without_touch(self) -> None:
        _, source = self._admit_daily_source("corrupt-model-grant")
        self._prepare_evidence_stage(source)
        request = _strict_model_request()
        issued = self.plugin.invoke(
            self._command(
                "effect.request",
                "ticket113-effect-request-corrupt-model-grant",
                EffectRequestPayload(
                    "model-work",
                    request.digest,
                    source.causal_id,
                ),
            ),
            peer_id="plugin",
        )
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        trap = LeasePropertyTrap()
        object.__setattr__(grant, "lease", trap)
        adapter = NeverCalledModelAdapter()

        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            request,
            source.causal_id,
            grant,
            adapter,
        )

        self.assertEqual(
            outcome.reason_code,
            "model-effect-authorization-required",
        )
        self.assertEqual(trap.touches, 0)
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "executing")

    def test_113_a6_c02_explicit_model_failure_commits_failed_closed_without_body(self) -> None:
        _, source = self._admit_daily_source("explicit-model-failure")
        self._prepare_evidence_stage(source)
        report = self._model_report("failed", reason_code="provider-failed")

        intent, _, _, effect_response, report = self._issue_model_report(
            "explicit-model-failure",
            report,
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        resolution = self._failed_resolution(
            report.reason_code,
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

        intent, _, effect_command, first, report = self._issue_model_report(
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
            report.reason_code,
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
        intent, _, _, effect_response, report = self._issue_model_report(
            "current-head-unknown",
            report,
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        resolution = self._failed_resolution(
            report.reason_code,
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
        intent, _, _, effect_response, report = self._issue_model_report(
            "finalize-unknown",
            report,
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        resolution = self._failed_resolution(
            report.reason_code,
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
        (
            intent,
            outcome,
            candidate,
            effect_command,
            effect_response,
        ) = self._issue_controlled_completed_model("rendered-replay")
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        report = outcome.model_report
        resolution = self._rendered_resolution(
            ModelEffectRef(intent["effect_id"], report.digest)
        )
        prepare_command, prepared = self._prepare_complete(
            source,
            resolution,
            candidate=candidate,
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

    def test_completed_effect_crash_freezes_source_without_a_second_model_call(self) -> None:
        _, source = self._admit_daily_source("completed-before-answer-crash")
        self._prepare_evidence_stage(source)
        _, outcome, _, _, effect_response = self._issue_controlled_completed_model(
            "completed-before-answer-crash"
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        self.assertEqual(outcome.disposition, "candidate")
        self.assertEqual(self.model_transport_calls, 1)

        self._reopen_with_head(self.head)
        second = self.plugin.invoke(
            self._command(
                "effect.request",
                "ticket113-effect-request-completed-before-answer-crash-retry",
                EffectRequestPayload(
                    "model-work",
                    STRICT_REQUEST_DIGEST,
                    source.causal_id,
                ),
            ),
            peer_id="plugin",
        )

        self.assertEqual(second.status, "rejected", second.to_wire())
        self.assertEqual(second.reason_code, "model-answer-owner-decision-required")
        self.assertEqual(
            self.plugin.model_answer_recovery_status(source.causal_id),
            "unknown-owner-decision-required",
        )
        self.assertEqual(self.store.count_effects(), 1)
        self.assertEqual(self.model_transport_calls, 1)
        self.assertIsNone(
            self.plugin.native_cursor_directive(source.causal_id, peer_id="plugin")
        )

    def test_model_effect_cannot_be_reused_by_a_different_source(self) -> None:
        _, source_a = self._admit_daily_source("model-source-a")
        self._prepare_evidence_stage(source_a)
        intent, outcome, candidate, _, effect_response = (
            self._issue_controlled_completed_model("model-source-a")
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        report = outcome.model_report
        resolution = self._rendered_resolution(
            ModelEffectRef(intent["effect_id"], report.digest)
        )
        _, prepared_a = self._prepare_complete(
            source_a,
            resolution,
            candidate=candidate,
        )
        self.assertEqual(prepared_a.status, "accepted", prepared_a.to_wire())
        self._finalize_complete(source_a.causal_id)

        _, source_b = self._admit_daily_source("model-source-b")
        self._prepare_evidence_stage(source_b)
        _, prepared_b = self._prepare_complete(
            source_b,
            resolution,
            candidate=candidate,
        )

        self.assertEqual(prepared_b.status, "rejected", prepared_b.to_wire())
        self.assertEqual(prepared_b.reason_code, "model-effect-source-mismatch")
        self.assertEqual(
            self.core.daily_turn_status(source_b.causal_id).phase,
            "evidence-finalized",
        )

    def test_core_rejects_candidate_swap_after_the_terminal_model_effect(self) -> None:
        _, source = self._admit_daily_source("candidate-swap")
        self._prepare_evidence_stage(source)
        intent, outcome, _, _, effect_response = (
            self._issue_controlled_completed_model("candidate-swap")
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        swapped = replace(
            self.candidate,
            claim_ids=tuple(reversed(self.candidate.claim_ids)),
        )
        swapped_rendered = self.pipeline.render(swapped)
        report = outcome.model_report
        resolution = ModelAnswerResolution.rendered(
            strict_request_digest=STRICT_REQUEST_DIGEST,
            model_authority_digest=MODEL_AUTHORITY_DIGEST,
            template_id=self.approved_template.template_id,
            template_version=self.approved_template.version,
            template_digest=stable_digest(self.approved_template.to_wire()),
            effect_ref=ModelEffectRef(intent["effect_id"], report.digest),
            candidate_digest=stable_digest(swapped.to_wire()),
            rendered_reply_digest=stable_digest(swapped_rendered.to_commit_wire()),
        )

        _, prepared = self._prepare_complete(
            source,
            resolution,
            candidate=swapped,
        )

        self.assertEqual(prepared.status, "rejected", prepared.to_wire())
        self.assertEqual(
            prepared.reason_code,
            "model-candidate-provenance-mismatch",
        )
        self.assertEqual(
            self.core.daily_turn_status(source.causal_id).phase,
            "evidence-finalized",
        )

    def test_completed_model_effect_cannot_be_closed_as_a_no_effect_failure(self) -> None:
        _, source = self._admit_daily_source("effect-ref-omission")
        self._prepare_evidence_stage(source)
        _, outcome, _, _, effect_response = self._issue_controlled_completed_model(
            "effect-ref-omission"
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        self.assertEqual(outcome.disposition, "candidate")
        forged_no_effect = self._failed_resolution(
            "model-effect-authorization-required"
        )

        _, prepared = self._prepare_complete(source, forged_no_effect)

        self.assertEqual(prepared.status, "rejected", prepared.to_wire())
        self.assertEqual(
            prepared.reason_code,
            "model-effect-reference-required",
        )
        self.assertEqual(
            self.plugin.model_answer_recovery_status(source.causal_id),
            "unknown-owner-decision-required",
        )
        self.assertIsNone(
            self.plugin.native_cursor_directive(source.causal_id, peer_id="plugin")
        )

    def test_completed_rejection_remains_failed_closed_pending_after_reopen(self) -> None:
        _, source = self._admit_daily_source("completed-rejection-crash")
        self._prepare_evidence_stage(source)
        rejected_completed = replace(
            self._model_report("completed", reason_code=None),
            fallback_observed=True,
            reason_code="fallback-observed",
            candidate_digest=None,
        )
        _, _, _, effect_response, report = self._issue_model_report(
            "completed-rejection-crash",
            rejected_completed,
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        self.assertEqual(report.reason_code, "fallback-observed")

        self._reopen_with_head(self.head)
        retry = self.plugin.invoke(
            self._command(
                "effect.request",
                "ticket113-effect-request-completed-rejection-crash-retry",
                EffectRequestPayload(
                    "model-work",
                    STRICT_REQUEST_DIGEST,
                    source.causal_id,
                ),
            ),
            peer_id="plugin",
        )

        self.assertEqual(
            self.plugin.model_answer_recovery_status(source.causal_id),
            "failed-closed-pending",
        )
        self.assertEqual(retry.status, "rejected", retry.to_wire())
        self.assertEqual(retry.reason_code, "model-effect-already-bound")

    def test_observed_model_call_rejects_a_forged_not_started_report(self) -> None:
        _, source = self._admit_daily_source("forged-not-started-report")
        self._prepare_evidence_stage(source)
        issued, grant, outcome, _, adapter = self._start_controlled_completed_model(
            "forged-not-started-report"
        )
        self.assertEqual(outcome.disposition, "candidate")
        forged = ModelEffectReport(
            model_status="not-started",
            transport_attempted=False,
            terminal_proven=False,
            requested_model=REQUESTED_MODEL,
            actual_model=None,
            fallback_observed=False,
            truncated=False,
            reason_code="capacity-unavailable",
            result_digest="sha256:" + "f" * 64,
        )
        command = self._command(
            "effect.result",
            "ticket113-effect-result-forged-not-started-report",
            EffectResultPayload(
                effect_id=issued["effect_id"],
                intent_digest=issued["intent_digest"],
                lease_id=grant.lease.lease_id,
                completion_capability=grant.completion_capability,
                status=forged.outer_effect_status,
                terminal=True,
                result_digest=forged.digest,
                model_report=forged,
            ),
        )

        response = self.plugin.invoke(command, peer_id="plugin")

        self.assertEqual(response.status, "rejected", response.to_wire())
        self.assertEqual(response.reason_code, "model-effect-report-mismatch")
        self.assertEqual(self.store.effect_state(issued["effect_id"]), "executing")
        self.assertEqual(adapter.calls, 1)

    def test_adapter_exception_becomes_unknown_and_the_grant_is_one_shot(self) -> None:
        _, source = self._admit_daily_source("adapter-exception")
        self._prepare_evidence_stage(source)
        request = _strict_model_request()
        issued = self.plugin.invoke(
            self._command(
                "effect.request",
                "ticket113-effect-request-adapter-exception",
                EffectRequestPayload(
                    "model-work",
                    request.digest,
                    source.causal_id,
                ),
            ),
            peer_id="plugin",
        )
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        adapter = RaisingModelAdapter()
        llm = StrictHealthLLM(_model_route(), _model_profile())

        first = self.plugin.execute_strict_health_model(
            llm,
            request,
            source.causal_id,
            grant,
            adapter,
        )
        second = self.plugin.execute_strict_health_model(
            llm,
            request,
            source.causal_id,
            grant,
            adapter,
        )

        self.assertEqual(first.disposition, "unknown")
        self.assertEqual(first.reason_code, "model-effect-unknown")
        self.assertEqual(first.model_report.outer_effect_status, "unknown")
        self.assertEqual(second.reason_code, "model-effect-authorization-required")
        self.assertEqual(adapter.calls, 1)

    def test_adapter_descriptor_is_not_touched_without_model_authority(self) -> None:
        trap = ExecuteDescriptorTrap()

        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            _strict_model_request(),
            "ticket113-missing-model-authority",
            None,
            trap,  # type: ignore[arg-type]
        )

        self.assertEqual(outcome.reason_code, "model-effect-authorization-required")
        self.assertEqual(trap.touches, 0)

    def test_durable_started_marker_rejects_stale_grant_after_reopen(self) -> None:
        _, source = self._admit_daily_source("stale-grant-after-reopen")
        self._prepare_evidence_stage(source)
        _, grant, outcome, _, adapter = self._start_controlled_completed_model(
            "stale-grant-after-reopen"
        )
        self.assertEqual(outcome.disposition, "candidate")
        self.assertEqual(adapter.calls, 1)
        self._reopen_with_head(self.head)

        second = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            _strict_model_request(),
            source.causal_id,
            grant,
            adapter,
        )

        self.assertEqual(second.reason_code, "model-effect-authorization-required")
        self.assertEqual(adapter.calls, 1)

    def test_result_resolution_exception_becomes_an_observed_unknown(self) -> None:
        _, source = self._admit_daily_source("result-resolution-exception")
        self._prepare_evidence_stage(source)
        request = _strict_model_request()
        issued = self.plugin.invoke(
            self._command(
                "effect.request",
                "ticket113-effect-request-result-resolution-exception",
                EffectRequestPayload(
                    "model-work",
                    request.digest,
                    source.causal_id,
                ),
            ),
            peer_id="plugin",
        )
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        result = ModelTransportResult.from_wire(
            {
                "response_id": "synthetic-corrupt-result",
                "requested_model": REQUESTED_MODEL,
                "actual_model": REQUESTED_MODEL,
                "status": "completed",
                "incomplete_reason": None,
                "failure_reason": None,
                "usage_input_tokens": 1,
                "usage_output_tokens": 1,
                "fallback_observed": False,
                "truncated": False,
                "terminal_proven": True,
                "structured_output": self.candidate.to_wire(),
            }
        )
        adapter = CorruptingResultAdapter(result)

        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            request,
            source.causal_id,
            grant,
            adapter,
        )

        self.assertEqual(outcome.disposition, "unknown")
        self.assertEqual(outcome.reason_code, "model-effect-unknown")
        self.assertEqual(outcome.model_report.outer_effect_status, "unknown")
        self.assertEqual(adapter.calls, 1)

    def test_core_rechecks_knowledge_expiry_at_the_business_write(self) -> None:
        publication = KnowledgePublicationInput(
            topic_id="sleep-general",
            governance_schedule_id="fixed-quarterly-v1",
            source_id="source-guideline",
            source_version="2026-01",
            rights_status="approved",
            chinese_status="reviewed-chinese",
            applicability=("general-adult-health-education",),
            professional_review_status="approved",
            professional_review_ref="synthetic-review-ref",
            content="synthetic current knowledge",
            published_at="2026-08-24T00:00:00+00:00",
            expires_at="2026-08-25T00:00:00+00:00",
        )
        release = KnowledgePublisher().publish(
            publication,
            release_version="2026.08.24",
        )
        self.assertIsInstance(release, KnowledgeRelease)
        general = ApprovedClaimAtom(
            "claim-general-knowledge",
            "general-knowledge",
            "通用知识来自当前治理知识卡。",
            "1.0.0",
        )
        self.approved_claims = (general,) + self.approved_claims
        self.approved_template = ApprovedReplyTemplate(
            "template-nondiagnostic-v1",
            "1.0.0",
            (
                "general-knowledge",
                "support",
                "opposition",
                "unknown",
                "limitation",
                "next-step",
            ),
        )
        self.candidate = replace(
            self.candidate,
            knowledge_refs=(
                CardReference(
                    release.release_id,
                    release.release_version,
                    "general-knowledge",
                ),
            ),
            claim_ids=tuple(claim.atom_id for claim in self.approved_claims),
        )
        self.knowledge_releases = (release,)
        self.pipeline = NonDiagnosticReplyPipeline(
            current_owner_cards=(),
            current_knowledge_releases=self.knowledge_releases,
            knowledge_valid_at=self.knowledge_now.isoformat(),
            approved_claims=self.approved_claims,
            approved_templates=(self.approved_template,),
        )
        self.rendered = self.pipeline.render(self.candidate)
        self._reopen_with_head(self.head)
        _, source = self._admit_daily_source("knowledge-expires-before-write")
        self._prepare_evidence_stage(source)
        intent, outcome, candidate, _, effect_response = (
            self._issue_controlled_completed_model("knowledge-expires-before-write")
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        report = outcome.model_report
        resolution = self._rendered_resolution(
            ModelEffectRef(intent["effect_id"], report.digest)
        )
        self.knowledge_now = datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc)

        _, prepared = self._prepare_complete(
            source,
            resolution,
            candidate=candidate,
        )

        self.assertEqual(prepared.status, "rejected", prepared.to_wire())
        self.assertEqual(
            prepared.reason_code,
            "non-diagnostic-candidate-rejected",
        )
        self.assertEqual(
            self.core.daily_turn_status(source.causal_id).phase,
            "evidence-finalized",
        )

    def test_raising_knowledge_timezone_fails_closed_at_business_write(self) -> None:
        _, source = self._admit_daily_source("raising-knowledge-timezone")
        self._prepare_evidence_stage(source)
        intent, outcome, candidate, _, effect_response = (
            self._issue_controlled_completed_model("raising-knowledge-timezone")
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        resolution = self._rendered_resolution(
            ModelEffectRef(intent["effect_id"], outcome.model_report.digest)
        )
        self.knowledge_now = datetime(
            2026,
            8,
            24,
            tzinfo=RaisingTimezone(),
        )

        _, prepared = self._prepare_complete(
            source,
            resolution,
            candidate=candidate,
        )

        self.assertEqual(prepared.status, "rejected", prepared.to_wire())
        self.assertEqual(
            prepared.reason_code,
            "model-answer-configuration-mismatch",
        )
        self.assertEqual(
            self.core.daily_turn_status(source.causal_id).phase,
            "evidence-finalized",
        )

    def test_core_rejects_an_extra_unapproved_model_reply_atom(self) -> None:
        _, source = self._admit_daily_source("extra-model-atom")
        self._prepare_evidence_stage(source)
        report = self._model_report("completed", reason_code=None)
        intent, _, _, effect_response, report = self._issue_model_report(
            "extra-model-atom",
            report,
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        resolution = self._rendered_resolution(
            ModelEffectRef(intent["effect_id"], report.digest)
        )
        extra = OwnerReplyAtom.form(
            kind="direct-result",
            text="未经批准的模型正文",
            source_skill="health-steward",
            source_result_digest=stable_digest(self.candidate.to_wire()),
        )

        _, prepared = self._prepare_complete(
            source,
            resolution,
            candidate=self.candidate,
            extra_model_atoms=(extra,),
        )

        self.assertEqual(prepared.status, "rejected", prepared.to_wire())
        self.assertEqual(prepared.reason_code, "deterministic-model-reply-mismatch")
        self.assertEqual(
            self.core.daily_turn_status(source.causal_id).phase,
            "evidence-finalized",
        )

    def test_core_rejects_same_kind_model_atoms_selected_out_of_render_order(self) -> None:
        _, source = self._admit_daily_source("same-kind-model-order")
        self._prepare_evidence_stage(source)
        intent, outcome, candidate, _, effect_response = (
            self._issue_controlled_completed_model("same-kind-model-order")
        )
        self.assertEqual(effect_response.status, "accepted", effect_response.to_wire())
        resolution = self._rendered_resolution(
            ModelEffectRef(intent["effect_id"], outcome.model_report.digest)
        )
        self.executor.reverse_model_direct_results = True

        _, prepared = self._prepare_complete(
            source,
            resolution,
            candidate=candidate,
        )

        self.assertEqual(prepared.status, "rejected", prepared.to_wire())
        self.assertEqual(prepared.reason_code, "deterministic-model-reply-mismatch")
        self.assertEqual(
            self.core.daily_turn_status(source.causal_id).phase,
            "evidence-finalized",
        )

    def test_113_a6_c07_known_no_effect_failure_releases_cursor(self) -> None:
        _, source = self._admit_daily_source("known-no-effect")
        self._prepare_evidence_stage(source)
        request = replace(
            _strict_model_request(),
            final_input_upper_bound_tokens=4000,
        )
        adapter = NeverCalledModelAdapter()
        outcome = self.plugin.execute_strict_health_model(
            StrictHealthLLM(_model_route(), _model_profile()),
            request,
            source.causal_id,
            None,
            adapter,
        )
        self.assertEqual(outcome.reason_code, "capacity-unavailable")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(self.model_transport_calls, 0)
        resolution = self._failed_resolution(
            "capacity-unavailable",
            strict_request_digest=request.digest,
        )
        _, prepared = self._prepare_complete(source, resolution)
        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        result, _, _ = self._finalize_complete(source.causal_id)

        self.assertEqual(self.store.count_effects(), 0)
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

        intent, _, _, response, report = self._issue_model_report(
            "unknown-effect",
            report,
        )

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

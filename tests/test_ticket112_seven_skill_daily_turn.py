import unittest
import threading
from dataclasses import replace
from datetime import datetime, timezone

from partner_health_steward import HealthCore, HealthPlugin
from partner_health_steward.admission import (
    AdmissionPolicy,
    RawWeixinMessage,
    materialize_source,
)
from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.contract import (
    CommandEnvelope,
    DailyTurnMeta,
    DailyTurnPreparePayload,
    InboundAdmitPayload,
)
from partner_health_steward.coordination import (
    AtomicEvidenceClaim,
    CoarseMessageRouter,
    DailySkillAsset,
    DailySkillAttestor,
    DailySkillBundle,
    DailySkillRuntime,
    DailyTurnDraft,
    DailyHealthNavigation,
    DailyHealthState,
    EvidenceCard,
    EvidenceApplicabilityChange,
    EvidenceCompaction,
    EvidenceContext,
    EvidenceDecision,
    EvidenceMaintenanceRequest,
    EvidenceRelation,
    EvidenceSeriesKey,
    EvidenceSeriesWindow,
    EvidenceSummaryFields,
    EvidenceTypePreview,
    PersonalHealthFields,
    AuthoritativeKnowledgeFields,
    TaskProcessFields,
    PortraitContext,
    PortraitDecision,
    PortraitTopicProjection,
    PortraitProofLink,
    PortraitTopic,
    LiteratureContext,
    LiteratureDecision,
    OwnerInquiryContext,
    OwnerInquiryDecision,
    SettingsContext,
    SettingsDecision,
    StewardContext,
    StewardPlan,
    StewardResolution,
    StewardResolutionContext,
)
from partner_health_steward.core import InMemoryWriterFenceVault
from partner_health_steward.current_head import InMemoryCurrentHead
from partner_health_steward.evidence_profile import (
    AuthoritativeKnowledgeProfile,
    PersonalEvidenceProfile,
    TaskProcessProfile,
)
from partner_health_steward.initialization import (
    HealthInitAsset,
    HealthInitAttestor,
    HealthInitRuntime,
    InitialPreferences,
    OwnerConsentEvidence,
    OwnerInitialization,
)
from partner_health_steward.storage import (
    EncryptedStateStore,
    KeyUnavailable,
    StaticKeyProvider,
    StoreUnavailable,
)


class DailyFinalizeFailureStore(EncryptedStateStore):
    """Fail after staging aggregate/result writes inside the outer transaction."""

    fail_next_daily_finalize = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.last_daily_finalize_draft = None

    def finalize_daily_turn(self, draft):
        self.last_daily_finalize_draft = draft
        result = super().finalize_daily_turn(draft)
        if self.fail_next_daily_finalize:
            self.fail_next_daily_finalize = False
            raise StoreUnavailable("synthetic daily finalize failure")
        return result


class CountingBody:
    def __init__(self, text: str) -> None:
        self._text = text
        self.reads = 0

    def read(self) -> str:
        self.reads += 1
        return self._text


def _portrait_evidence_period(
    context: PortraitContext,
    evidence_id: str,
) -> str:
    for card in (
        *context.committed_related_cards,
        *context.in_turn_evidence_candidates,
    ):
        if card.evidence_id == evidence_id:
            return card.applicable_period
    raise AssertionError(f"portrait evidence missing: {evidence_id}")


class SyntheticSleepTurnExecutor:
    def __init__(self) -> None:
        self.contexts: dict[str, object] = {}
        self.context_history: list[tuple[str, object]] = []
        self.calls: list[str] = []
        self.fail_next_portrait = False

    def __call__(self, skill_name: str, context: object) -> object:
        self.calls.append(skill_name)
        self.contexts[skill_name] = context
        self.context_history.append((skill_name, context))
        if skill_name == "health-steward":
            if type(context) is StewardContext:
                return StewardPlan(
                    purpose="record-sleep-experience",
                    selected_skills=("health-evidence", "health-portrait"),
                    portrait_topic_refs=(
                        "physical-function-and-experience/sleep",
                    ),
                    atomic_claims=(
                        AtomicEvidenceClaim(
                            content="主人自述昨晚主观睡眠体验不佳",
                            evidence_type="personal-health",
                            source_kind="owner-statement",
                            occurred_at="2026-08-23",
                            applicable_period="2026-08-23-night",
                            purpose="sleep-support",
                            uncertainty="主人主观体验",
                            limitations=(
                                "未提供睡眠时长",
                                "未提供原因",
                                "单次陈述不证明趋势",
                            ),
                            proves=("主人自述昨晚主观睡眠体验不佳",),
                            does_not_prove=("睡眠时长", "长期趋势", "失眠诊断"),
                            topic_refs=("physical-function-and-experience/sleep",),
                            specific_fields=PersonalHealthFields("owner-statement"),
                            series_key=EvidenceSeriesKey(
                                "personal-health",
                                "subjective-sleep-experience",
                                PersonalEvidenceProfile("owner-statement"),
                                "single-night",
                            ),
                            time_certainty="known",
                        ),
                    ),
                )
            if type(context) is StewardResolutionContext:
                return StewardResolution(
                    commit_evidence_ids=context.candidate_evidence_ids,
                    commit_portrait_topic_refs=context.candidate_portrait_topic_refs,
                    reply_atom_ids=tuple(atom.atom_id for atom in context.reply_atoms),
                )
            raise TypeError("unexpected steward context")
        if skill_name == "health-evidence":
            if type(context) is not EvidenceContext:
                raise TypeError("unexpected evidence context")
            return EvidenceDecision.admit(context.atomic_claim)
        if skill_name == "health-portrait":
            if type(context) is not PortraitContext:
                raise TypeError("unexpected portrait context")
            if self.fail_next_portrait:
                self.fail_next_portrait = False
                raise AuthorityValidationError(
                    "synthetic completion interruption"
                )
            understanding = "主人自述昨晚睡眠体验不佳（仅昨晚）"
            return PortraitDecision.update(
                topic_ref="physical-function-and-experience/sleep",
                current_understandings=(understanding,),
                open_judgments=(),
                key_unknowns=("睡眠时长未知", "原因未知"),
                proof_links=(
                    *(
                        PortraitProofLink.form(
                            evidence_id=evidence_id,
                            relation_kind="supports",
                            topic_ref="physical-function-and-experience/sleep",
                            item_kind="current-understanding",
                            item_text=understanding,
                            applicable_period=_portrait_evidence_period(
                                context,
                                evidence_id,
                            ),
                        )
                        for evidence_id in context.evidence_ids
                    ),
                    PortraitProofLink.form(
                        evidence_id=context.evidence_ids[0],
                        relation_kind="qualifies",
                        topic_ref="physical-function-and-experience/sleep",
                        item_kind="key-unknown",
                        item_text="睡眠时长未知",
                    ),
                    PortraitProofLink.form(
                        evidence_id=context.evidence_ids[0],
                        relation_kind="qualifies",
                        topic_ref="physical-function-and-experience/sleep",
                        item_kind="key-unknown",
                        item_text="原因未知",
                    ),
                ),
            )
        raise AssertionError(f"unexpected Skill execution: {skill_name}")


class BoundaryResponsibilityExecutor:
    def __init__(self, mode: str, *, honor_missing_context: bool = True) -> None:
        self.mode = mode
        self.honor_missing_context = honor_missing_context
        self.contexts: dict[str, object] = {}

    def __call__(self, skill_name: str, context: object) -> object:
        self.contexts[skill_name] = context
        if skill_name == "health-steward":
            if type(context) is StewardResolutionContext:
                return StewardResolution(
                    commit_evidence_ids=context.candidate_evidence_ids,
                    commit_portrait_topic_refs=context.candidate_portrait_topic_refs,
                    reply_atom_ids=tuple(atom.atom_id for atom in context.reply_atoms),
                )
            if self.mode == "settings":
                return StewardPlan(
                    purpose="record-settings-intent",
                    selected_skills=("health-settings",),
                    atomic_claims=(),
                    settings_intent="暂停主动支持",
                )
            if self.mode == "inquiry":
                return StewardPlan(
                    purpose="clarify-sleep-duration",
                    selected_skills=("health-owner-inquiry",),
                    atomic_claims=(),
                    inquiry_gap="昨晚睡眠时长未知",
                )
            if self.mode == "literature":
                return StewardPlan(
                    purpose="find-sleep-knowledge",
                    selected_skills=("health-literature",),
                    atomic_claims=(),
                    knowledge_gap="一次主观睡眠不佳通常能说明什么",
                    knowledge_topic_refs=(
                        "physical-function-and-experience/sleep",
                    ),
                    allowed_knowledge_sources=("approved-library",),
                    recipient_boundary="configured-first-hop-only",
                )
        if skill_name == "health-settings":
            if type(context) is not SettingsContext:
                raise TypeError("unexpected settings context")
            if self.honor_missing_context and not context.current_settings_available:
                return SettingsDecision.gap("current-settings-unavailable")
            return SettingsDecision.candidate(context.owner_intent)
        if skill_name == "health-owner-inquiry":
            if type(context) is not OwnerInquiryContext:
                raise TypeError("unexpected inquiry context")
            if self.honor_missing_context and context.missing_requirements:
                return OwnerInquiryDecision.gap("required-context-unavailable")
            return OwnerInquiryDecision.ask("昨晚大约睡了多久？")
        if skill_name == "health-literature":
            if type(context) is not LiteratureContext:
                raise TypeError("unexpected literature context")
            return LiteratureDecision.no_qualified_material("no-qualified-material")
        raise AssertionError(f"unexpected Skill execution: {skill_name}")


class SeriesCompactionExecutor:
    def __init__(self) -> None:
        self.claim: AtomicEvidenceClaim | None = None
        self.retire_evidence_ids: tuple[str, ...] = ()

    def __call__(self, skill_name: str, context: object) -> object:
        if skill_name == "health-steward":
            if type(context) is StewardResolutionContext:
                return StewardResolution(
                    commit_evidence_ids=context.candidate_evidence_ids,
                    commit_portrait_topic_refs=context.candidate_portrait_topic_refs,
                    reply_atom_ids=tuple(atom.atom_id for atom in context.reply_atoms),
                )
            if type(context) is not StewardContext or self.claim is None:
                raise TypeError("unexpected steward context")
            return StewardPlan(
                purpose="maintain-sleep-series",
                selected_skills=("health-evidence",),
                atomic_claims=(self.claim,),
            )
        if skill_name == "health-evidence":
            if type(context) is not EvidenceContext or self.claim is None:
                raise TypeError("unexpected evidence context")
            if self.claim.summary_fields is None:
                return EvidenceDecision.admit(context.atomic_claim)
            return EvidenceDecision.compress(
                context.atomic_claim,
                self.retire_evidence_ids,
            )
        raise AssertionError(f"unexpected Skill execution: {skill_name}")


class Ticket112SevenSkillDailyTurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.writer_capability = "ticket112-synthetic-writer"
        self.store = DailyFinalizeFailureStore(
            "file:ticket112?mode=memory&cache=shared",
            StaticKeyProvider(b"t" * 32, key_id="ticket112-state-key"),
        )
        self.head = InMemoryCurrentHead(
            installation_id="partner-installation",
            site="partner-site",
            writer_capability=self.writer_capability,
        )
        authority = self.head.read().head.as_authority()
        self.store.seed_finalized_authority(authority)
        self.writer_vault = InMemoryWriterFenceVault()
        self.writer_vault.bind(authority, self.writer_capability)
        self.policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-A",
            conversation_id="private-A",
        )
        self.init_attestor = HealthInitAttestor(
            b"a" * 32,
            key_id="ticket112-health-init-attestor",
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
        self.route_classification = "ordinary"
        self.router = CoarseMessageRouter(
            classifier=lambda body, requested_capability: self.route_classification
        )
        self.daily_attestor = DailySkillAttestor(
            b"s" * 32,
            key_id="ticket112-daily-skill-attestor",
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
        self.turn_executor = SyntheticSleepTurnExecutor()
        self.daily_runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=self.turn_executor,
            clock=lambda: datetime(2026, 8, 24, 1, 6, tzinfo=timezone.utc),
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
            daily_skill_verifier=self.daily_attestor,
            daily_skill_bundle=self.daily_bundle,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=self.daily_runtime,
        )
        self._enable_product()

    def tearDown(self) -> None:
        self.core.close()
        self.store.close()

    def initialization_request(self) -> OwnerInitialization:
        return OwnerInitialization(
            workflow_id="ticket112-init",
            admission_causal_id="ticket112-init-source",
            owner_consent=True,
            first_hop_route="jojo-responses-v1",
            first_hop_route_consent=True,
            timezone="Asia/Shanghai",
            preferences=InitialPreferences(
                contact_window="09:00-21:00",
                expression_style="concise",
                proactive_support=True,
            ),
            data_boundary=(
                "health-portrait",
                "health-evidence",
                "health-tasks",
            ),
            support_contact=None,
        )

    def message(self, body: object, **changes: object) -> RawWeixinMessage:
        values = {
            "causal_id": "ticket112-init-source",
            "generation": 1,
            "channel": "weixin",
            "partner_id": "partner-A",
            "sender_id": "owner-A",
            "conversation_id": "private-A",
            "chat_type": "private",
            "entrypoint": "health_weixin",
            "requested_capability": "health-init",
            "message_id": "wx-ticket112-init",
            "protocol_timestamp": "2026-08-24T09:00:00+08:00",
            "received_at": "2026-08-24T09:00:01+08:00",
            "native_cursor": "cursor-ticket112-init",
            "body": body,
        }
        values.update(changes)
        return RawWeixinMessage(**values)

    def _enable_product(self) -> None:
        initialization = self.initialization_request()
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
            self.message(CountingBody(consent.to_message_body())),
            peer_id="plugin",
        )
        self.assertEqual(admitted.status, "accepted")
        self.assertEqual(
            self.plugin.prepare_initialization(
                initialization,
                peer_id="plugin",
            ).status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.commit_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.finalize_initialization(peer_id="plugin").status,
            "accepted",
        )

    def test_enabled_explicitly_non_health_message_routes_to_ordinary_hermes(self) -> None:
        body = CountingBody("请提醒我明天上午十点开项目会")

        response = self.plugin.receive_weixin(
            self.message(
                body,
                causal_id="ticket112-ordinary-source",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-ordinary",
                protocol_timestamp="2026-08-24T09:05:00+08:00",
                received_at="2026-08-24T09:05:01+08:00",
                native_cursor="cursor-ticket112-ordinary",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "accepted")
        self.assertEqual(response.reason_code, "ordinary-hermes-route")
        self.assertEqual(body.reads, 1)

    def test_runtime_commits_evidence_stage_before_portrait_and_uses_only_committed_context(self) -> None:
        source = materialize_source(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-two-phase-runtime",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-two-phase-runtime",
                protocol_timestamp="2026-08-24T09:04:00+08:00",
                received_at="2026-08-24T09:04:01+08:00",
                native_cursor="cursor-ticket112-two-phase-runtime",
            )
        )
        before = self.core.daily_state()

        stage = self.daily_runtime.execute(source, before)

        self.assertEqual(stage.turn_kind, "evidence-stage")
        self.assertIsNone(stage.evidence_stage)
        self.assertIsNone(stage.steward_resolution)
        self.assertEqual(stage.reply_atoms, ())
        self.assertEqual(stage.portrait_topics, ())
        self.assertEqual(stage.owner_reply, "")
        self.assertEqual(DailyTurnDraft.from_storage(stage.to_storage()), stage)
        self.assertEqual(
            self.turn_executor.calls,
            ["health-steward", "health-evidence"],
        )
        self.assertTrue(
            stage.verify(
                source,
                before,
                self.daily_bundle,
                self.daily_attestor,
            )
        )
        navigation = self.turn_executor.context_history[0][1].health_navigation
        self.assertIs(type(navigation), DailyHealthNavigation)
        self.assertEqual(
            set(vars(navigation)),
            {
                "state_digest",
                "evidence_count",
                "portrait_topic_refs",
                "unknown_domains",
            },
        )

        after_stage = before.apply_evidence_stage(stage)
        evidence_id = stage.evidence_cards[0].evidence_id
        unrelated_relations = (
            EvidenceRelation(
                evidence_id,
                "topic",
                "relevant",
                "portrait-topic",
                "health-behaviour-and-exposure/sleep-routine",
            ),
            EvidenceRelation(
                evidence_id,
                "use",
                "used-by",
                "managed-result",
                "health-task:unrelated",
            ),
        )
        after_stage = replace(
            after_stage,
            evidence_relations=(
                *after_stage.evidence_relations,
                *unrelated_relations,
            ),
        )

        complete = self.daily_runtime.complete(source, after_stage, stage)

        self.assertEqual(complete.turn_kind, "complete-turn")
        self.assertEqual(complete.evidence_stage, stage)
        self.assertEqual(complete.evidence_cards, ())
        self.assertEqual(complete.evidence_compactions, ())
        self.assertEqual(
            DailyTurnDraft.from_storage(complete.to_storage()),
            complete,
        )
        self.assertNotEqual(stage.record_id, complete.record_id)
        self.assertNotEqual(stage.transition_id, complete.transition_id)
        self.assertEqual(
            self.turn_executor.calls,
            [
                "health-steward",
                "health-evidence",
                "health-portrait",
                "health-steward",
            ],
        )
        portrait_context = self.turn_executor.contexts["health-portrait"]
        self.assertEqual(
            portrait_context.committed_related_cards,
            stage.evidence_cards,
        )
        self.assertEqual(portrait_context.in_turn_evidence_candidates, ())
        self.assertTrue(
            all(
                relation.relation_class == "topic"
                and relation.target_ref
                == "physical-function-and-experience/sleep"
                for relation in portrait_context.committed_relations
            )
        )
        self.assertTrue(
            complete.verify(
                source,
                after_stage,
                self.daily_bundle,
                self.daily_attestor,
                committed_evidence_stage=stage,
            )
        )
        final_state, result = after_stage.apply(complete)
        self.assertEqual(result.evidence_ids, (evidence_id,))
        self.assertIn(source.causal_id, final_state.processed_source_causal_ids)

    def test_evidence_stage_verify_rejects_same_source_card_substitution(self) -> None:
        source = materialize_source(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-evidence-result-tamper",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-evidence-result-tamper",
                protocol_timestamp="2026-08-24T09:04:05+08:00",
                received_at="2026-08-24T09:04:06+08:00",
                native_cursor="cursor-ticket112-evidence-result-tamper",
            )
        )
        before = self.core.daily_state()
        stage = self.daily_runtime.execute(source, before)
        claim = stage.steward_plan.atomic_claims[0]
        forged_claim = replace(
            claim,
            content="主人每晚睡眠体验良好",
            proves=("主人每晚睡眠体验良好",),
        )
        forged_card = EvidenceCard.from_claim(
            source.causal_id,
            forged_claim,
            recorded_at=stage.created_at,
        )
        original_result = stage.responsibility_results[0]
        forged = replace(
            stage,
            responsibility_results=(
                replace(
                    original_result,
                    candidate_refs=(forged_card.evidence_id,),
                ),
            ),
            evidence_cards=(forged_card,),
            evidence_relations=tuple(
                replace(relation, evidence_id=forged_card.evidence_id)
                for relation in stage.evidence_relations
            ),
        )

        self.assertIs(type(original_result.decision), EvidenceDecision)
        self.assertEqual(
            DailyTurnDraft.from_storage(stage.to_storage()),
            stage,
        )
        self.assertFalse(
            forged.verify(
                source,
                before,
                self.daily_bundle,
                self.daily_attestor,
            )
        )

    def test_evidence_only_stage_and_complete_require_no_portrait_result(self) -> None:
        source = materialize_source(
            self.message(
                CountingBody("仅记录这次睡眠体验"),
                causal_id="ticket112-evidence-only",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-evidence-only",
                protocol_timestamp="2026-08-24T09:04:07+08:00",
                received_at="2026-08-24T09:04:08+08:00",
                native_cursor="cursor-ticket112-evidence-only",
            )
        )
        claim = self.turn_executor(
            "health-steward",
            StewardContext(
                source.causal_id,
                source.requested_capability,
                source.body,
                DailyHealthState.empty().navigation,
            ),
        ).atomic_claims[0]

        class EvidenceOnlyExecutor:
            def __call__(self, skill_name: str, context: object) -> object:
                if skill_name == "health-steward":
                    if type(context) is StewardResolutionContext:
                        return StewardResolution(
                            context.candidate_evidence_ids,
                            (),
                            tuple(atom.atom_id for atom in context.reply_atoms),
                        )
                    return StewardPlan(
                        purpose="evidence-only",
                        selected_skills=("health-evidence",),
                        atomic_claims=(claim,),
                    )
                if skill_name == "health-evidence":
                    return EvidenceDecision.admit(context.atomic_claim)
                raise AssertionError(skill_name)

        runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=EvidenceOnlyExecutor(),
            clock=lambda: datetime(2026, 8, 24, 1, 4, 9, tzinfo=timezone.utc),
        )
        before = DailyHealthState.empty()
        stage = runtime.execute(source, before)
        after_stage = before.apply_evidence_stage(stage)
        complete = runtime.complete(source, after_stage, stage)

        self.assertEqual(
            tuple(
                result.canonical_name
                for result in complete.responsibility_results
            ),
            ("health-evidence",),
        )
        self.assertEqual(complete.portrait_topics, ())
        self.assertEqual(complete.portrait_withdrawals, ())
        self.assertTrue(
            complete.verify(
                source,
                after_stage,
                self.daily_bundle,
                self.daily_attestor,
                committed_evidence_stage=stage,
            )
        )

    def test_evidence_lifecycle_changes_current_applicability_and_forces_portrait_rejudgment(self) -> None:
        topic_ref = "physical-function-and-experience/sleep"
        seed_claim = AtomicEvidenceClaim(
            content="主人自述昨晚主观睡眠体验不佳",
            evidence_type="personal-health",
            source_kind="owner-statement",
            occurred_at="2026-08-22",
            applicable_period="2026-08-22-night",
            purpose="seed-current-evidence",
            uncertainty="主人主观体验",
            limitations=("单次陈述",),
            proves=("主人自述昨晚主观睡眠体验不佳",),
            does_not_prove=("长期趋势",),
            topic_refs=(topic_ref,),
            specific_fields=PersonalHealthFields("owner-statement"),
            series_key=EvidenceSeriesKey(
                "personal-health",
                "subjective-sleep-experience",
                PersonalEvidenceProfile("owner-statement"),
                "single-night",
            ),
            time_certainty="known",
        )
        old_card = EvidenceCard.from_claim(
            "ticket112-lifecycle-seed",
            seed_claim,
            recorded_at="2026-08-23T01:00:00Z",
        )
        old_links = (
            PortraitProofLink.form(
                evidence_id=old_card.evidence_id,
                relation_kind="supports",
                topic_ref=topic_ref,
                item_kind="current-understanding",
                item_text=seed_claim.content,
                applicable_period=old_card.applicable_period,
            ),
            PortraitProofLink.form(
                evidence_id=old_card.evidence_id,
                relation_kind="qualifies",
                topic_ref=topic_ref,
                item_kind="open-judgment",
                item_text="是否持续",
            ),
            PortraitProofLink.form(
                evidence_id=old_card.evidence_id,
                relation_kind="qualifies",
                topic_ref=topic_ref,
                item_kind="key-unknown",
                item_text="后续体验",
            ),
        )
        old_topic = PortraitTopic.from_decision(
            PortraitDecision.update(
                topic_ref=topic_ref,
                current_understandings=(seed_claim.content,),
                open_judgments=("是否持续",),
                key_unknowns=("后续体验",),
                proof_links=old_links,
            )
        )
        seeded = DailyHealthState(
            (old_card,),
            (old_topic,),
            old_topic.evidence_relations,
            (),
        )
        corrected_text = "主人更正为昨晚主观睡眠体验尚可"
        correction_claim = replace(
            seed_claim,
            content=corrected_text,
            proves=(corrected_text,),
            occurred_at="2026-08-23",
            applicable_period="2026-08-23-night",
            purpose="maintain-current-evidence",
        )

        for index, status in enumerate(
            ("correct", "withdraw", "invalidate"),
            start=1,
        ):
            evidence_contexts: list[EvidenceContext] = []
            portrait_contexts: list[PortraitContext] = []
            reason = {
                "correct": "主人明确更正原陈述",
                "withdraw": "主人明确撤回原陈述",
                "invalidate": "来源完整性核验失败",
            }[status]
            maintenance_request = EvidenceMaintenanceRequest(
                status,
                (old_card.evidence_id,),
                reason,
                f"evidence-{status}",
                correction_claim if status == "correct" else None,
            )

            class LifecycleExecutor:
                def __call__(self, skill_name: str, context: object) -> object:
                    if skill_name == "health-steward":
                        if type(context) is StewardResolutionContext:
                            return StewardResolution(
                                context.candidate_evidence_ids,
                                context.candidate_portrait_topic_refs,
                                tuple(
                                    atom.atom_id for atom in context.reply_atoms
                                ),
                                context.candidate_evidence_change_ids,
                            )
                        return StewardPlan(
                            purpose=f"evidence-{status}",
                            selected_skills=(
                                "health-evidence",
                                "health-portrait",
                            ),
                            atomic_claims=(),
                            portrait_topic_refs=(topic_ref,),
                            evidence_maintenance_requests=(
                                maintenance_request,
                            ),
                        )
                    if skill_name == "health-evidence":
                        evidence_contexts.append(context)
                        if status == "correct":
                            return EvidenceDecision.correct(
                                context.atomic_claim,
                                (old_card.evidence_id,),
                                reason=reason,
                            )
                        if status == "withdraw":
                            return EvidenceDecision.withdraw(
                                reason,
                                (old_card.evidence_id,),
                            )
                        return EvidenceDecision.invalidate(
                            reason,
                            (old_card.evidence_id,),
                        )
                    if skill_name == "health-portrait":
                        portrait_contexts.append(context)
                        if status == "correct":
                            successor = context.committed_related_cards[0]
                            links = (
                                PortraitProofLink.form(
                                    evidence_id=successor.evidence_id,
                                    relation_kind="supports",
                                    topic_ref=topic_ref,
                                    item_kind="current-understanding",
                                    item_text=corrected_text,
                                    applicable_period=successor.applicable_period,
                                ),
                                PortraitProofLink.form(
                                    evidence_id=successor.evidence_id,
                                    relation_kind="qualifies",
                                    topic_ref=topic_ref,
                                    item_kind="open-judgment",
                                    item_text="是否持续",
                                ),
                                PortraitProofLink.form(
                                    evidence_id=successor.evidence_id,
                                    relation_kind="qualifies",
                                    topic_ref=topic_ref,
                                    item_kind="key-unknown",
                                    item_text="后续体验",
                                ),
                            )
                            return PortraitDecision.update(
                                topic_ref=topic_ref,
                                current_understandings=(corrected_text,),
                                open_judgments=("是否持续",),
                                key_unknowns=("后续体验",),
                                proof_links=links,
                            )
                        return PortraitDecision.withdraw(
                            topic_ref,
                            "当前画像唯一依据已退出适用",
                        )
                    raise AssertionError(skill_name)

            source = materialize_source(
                self.message(
                    CountingBody(f"执行证据生命周期：{status}"),
                    causal_id=f"ticket112-evidence-lifecycle-{status}",
                    generation=2,
                    requested_capability="health-steward",
                    message_id=f"wx-ticket112-evidence-lifecycle-{status}",
                    protocol_timestamp=f"2026-08-24T09:3{index}:00+08:00",
                    received_at=f"2026-08-24T09:3{index}:01+08:00",
                    native_cursor=f"cursor-ticket112-evidence-lifecycle-{status}",
                )
            )
            runtime = DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=LifecycleExecutor(),
                clock=lambda index=index: datetime(
                    2026,
                    8,
                    24,
                    1,
                    30 + index,
                    tzinfo=timezone.utc,
                ),
            )
            stage = runtime.execute(source, seeded)
            self.assertTrue(
                stage.verify(
                    source,
                    seeded,
                    self.daily_bundle,
                    self.daily_attestor,
                )
            )
            self.assertEqual(
                DailyTurnDraft.from_storage(stage.to_storage()),
                stage,
            )
            change = stage.evidence_applicability_changes[0]
            self.assertIs(type(change), EvidenceApplicabilityChange)
            self.assertEqual(change.target_evidence_id, old_card.evidence_id)
            self.assertIn(old_card.evidence_id, evidence_contexts[0].current_evidence_ids)
            forged_stage = replace(
                stage,
                evidence_applicability_changes=(
                    replace(change, reason="被篡改的生命周期原因"),
                ),
            )
            self.assertFalse(
                forged_stage.verify(
                    source,
                    seeded,
                    self.daily_bundle,
                    self.daily_attestor,
                )
            )
            with self.assertRaises(AuthorityValidationError):
                seeded.apply_evidence_stage(forged_stage)

            post_stage = seeded.apply_evidence_stage(stage)
            self.assertIn(old_card, post_stage.evidence_cards)
            self.assertFalse(post_stage.is_evidence_current(old_card.evidence_id))
            self.assertIn(
                old_card.evidence_id,
                post_stage.projection.series_windows[0].protected_detail_ids,
            )
            topic_view = next(
                view
                for view in post_stage.projection.topic_views
                if view.topic_ref == topic_ref
            )
            self.assertFalse(
                any(
                    old_card.evidence_id in preview.preview_ids
                    for preview in topic_view.evidence_previews
                )
            )
            if status == "correct":
                successor = stage.evidence_cards[0]
                self.assertEqual(change.successor_evidence_id, successor.evidence_id)
                self.assertTrue(post_stage.is_evidence_current(successor.evidence_id))
            else:
                self.assertEqual(stage.evidence_cards, ())
                self.assertIsNone(change.successor_evidence_id)

            complete = runtime.complete(source, post_stage, stage)
            self.assertTrue(portrait_contexts)
            self.assertNotIn(
                old_card.evidence_id,
                portrait_contexts[0].evidence_ids,
            )
            self.assertEqual(
                complete.steward_resolution.commit_evidence_change_ids,
                (change.change_id,),
            )
            self.assertTrue(
                any(
                    change.change_id in atom.required_evidence_change_ids
                    for atom in complete.reply_atoms
                    if atom.source_skill == "health-evidence"
                )
            )
            self.assertTrue(
                complete.verify(
                    source,
                    post_stage,
                    self.daily_bundle,
                    self.daily_attestor,
                    committed_evidence_stage=stage,
                )
            )
            forged_complete = replace(
                complete,
                portrait_topics=(),
                portrait_withdrawals=(),
                evidence_relations=(),
            )
            self.assertFalse(
                forged_complete.verify(
                    source,
                    post_stage,
                    self.daily_bundle,
                    self.daily_attestor,
                    committed_evidence_stage=stage,
                )
            )
            with self.assertRaises(AuthorityValidationError):
                post_stage.apply(forged_complete)

            final_state, final_result = post_stage.apply(complete)
            self.assertEqual(
                DailyHealthState.from_storage(final_state.to_storage()),
                final_state,
            )
            self.assertIn(old_card, final_state.evidence_cards)
            self.assertEqual(final_state.evidence_applicability_changes, (change,))
            self.assertEqual(
                final_result.evidence_change_ids,
                (change.change_id,),
            )
            if status == "correct":
                self.assertEqual(
                    final_state.portrait_topics[0].evidence_ids,
                    (stage.evidence_cards[0].evidence_id,),
                )
            else:
                self.assertEqual(final_state.portrait_topics, ())
            self.assertTrue(
                any(
                    relation.relation_class == "history"
                    and relation.relation_kind
                    == ("corrects" if status == "correct" else "withdraws")
                    and relation.target_ref == old_card.evidence_id
                    for relation in final_state.evidence_relations
                )
            )

    def test_portrait_maintain_degrade_withdraw_and_gap_are_typed_final_results(self) -> None:
        topic_ref = "physical-function-and-experience/sleep"
        seed_source = materialize_source(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-portrait-lifecycle-seed",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-portrait-lifecycle-seed",
                protocol_timestamp="2026-08-24T09:04:10+08:00",
                received_at="2026-08-24T09:04:11+08:00",
                native_cursor="cursor-ticket112-portrait-lifecycle-seed",
            )
        )
        initial = self.core.daily_state()
        seed_stage = self.daily_runtime.execute(seed_source, initial)
        seed_after_stage = initial.apply_evidence_stage(seed_stage)
        seed_complete = self.daily_runtime.complete(
            seed_source,
            seed_after_stage,
            seed_stage,
        )
        seeded, _ = seed_after_stage.apply(seed_complete)
        seeded_topic = seeded.portrait_topics[0]
        seeded_card = seeded.evidence_cards[0]

        class LifecycleExecutor:
            def __init__(self, status: str) -> None:
                self.status = status

            def __call__(self, skill_name: str, context: object) -> object:
                if skill_name == "health-steward":
                    if type(context) is StewardResolutionContext:
                        return StewardResolution(
                            commit_evidence_ids=context.candidate_evidence_ids,
                            commit_portrait_topic_refs=(
                                context.candidate_portrait_topic_refs
                            ),
                            reply_atom_ids=tuple(
                                atom.atom_id for atom in context.reply_atoms
                            ),
                        )
                    return StewardPlan(
                        purpose=f"portrait-{self.status}",
                        selected_skills=("health-portrait",),
                        atomic_claims=(),
                        portrait_topic_refs=(topic_ref,),
                    )
                if skill_name != "health-portrait" or type(context) is not PortraitContext:
                    raise AssertionError(skill_name)
                if self.status == "maintain":
                    return PortraitDecision.maintain(
                        topic_ref,
                        "current-understanding-still-supported",
                    )
                if self.status == "withdraw":
                    return PortraitDecision.withdraw(
                        topic_ref,
                        "current-understanding-no-longer-current",
                    )
                if self.status == "gap":
                    return PortraitDecision.gap("required-context-unavailable")
                understanding = "当前理解因适用性下降而降级"
                return PortraitDecision.degrade(
                    topic_ref=topic_ref,
                    current_understandings=(understanding,),
                    open_judgments=("仍需主人补充近期情况",),
                    key_unknowns=("近期状态未知",),
                    proof_links=(
                        PortraitProofLink.form(
                            evidence_id=seeded_card.evidence_id,
                            relation_kind="qualifies",
                            topic_ref=topic_ref,
                            item_kind="current-understanding",
                            item_text=understanding,
                            applicable_period=seeded_card.applicable_period,
                        ),
                        PortraitProofLink.form(
                            evidence_id=seeded_card.evidence_id,
                            relation_kind="qualifies",
                            topic_ref=topic_ref,
                            item_kind="open-judgment",
                            item_text="仍需主人补充近期情况",
                        ),
                        PortraitProofLink.form(
                            evidence_id=seeded_card.evidence_id,
                            relation_kind="qualifies",
                            topic_ref=topic_ref,
                            item_kind="key-unknown",
                            item_text="近期状态未知",
                        ),
                    ),
                    reason="evidence-applicability-decreased",
                )

        expected_reply = {
            "maintain": "维持画像主题",
            "degrade": "降级画像主题",
            "withdraw": "撤回画像主题",
            "gap": "画像处理所需资料不足",
        }
        for index, status in enumerate(expected_reply, start=1):
            runtime = DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=LifecycleExecutor(status),
                clock=lambda index=index: datetime(
                    2026,
                    8,
                    24,
                    1,
                    20 + index,
                    tzinfo=timezone.utc,
                ),
            )
            source = materialize_source(
                self.message(
                    CountingBody(f"请{status}当前睡眠画像"),
                    causal_id=f"ticket112-portrait-{status}",
                    generation=2,
                    requested_capability="health-steward",
                    message_id=f"wx-ticket112-portrait-{status}",
                    protocol_timestamp=f"2026-08-24T09:1{index}:00+08:00",
                    received_at=f"2026-08-24T09:1{index}:01+08:00",
                    native_cursor=f"cursor-ticket112-portrait-{status}",
                )
            )
            stage = runtime.execute(source, seeded)
            after_stage = seeded.apply_evidence_stage(stage)
            complete = runtime.complete(source, after_stage, stage)

            self.assertEqual(
                complete.steward_resolution.commit_portrait_topic_refs,
                () if status == "gap" else (topic_ref,),
            )
            self.assertIn(expected_reply[status], complete.owner_reply)
            self.assertTrue(
                complete.verify(
                    source,
                    after_stage,
                    self.daily_bundle,
                    self.daily_attestor,
                    committed_evidence_stage=stage,
                )
            )
            final_state, result = after_stage.apply(complete)
            self.assertEqual(
                result.portrait_topics,
                () if status == "gap" else (topic_ref,),
            )
            self.assertIn(seeded_card, final_state.evidence_cards)
            if status in {"maintain", "gap"}:
                self.assertEqual(final_state.portrait_topics, (seeded_topic,))
            elif status == "degrade":
                self.assertEqual(
                    final_state.portrait_topics[0].current_understandings,
                    ("当前理解因适用性下降而降级",),
                )
            else:
                self.assertEqual(final_state.portrait_topics, ())
                self.assertEqual(complete.portrait_withdrawals, (topic_ref,))
                self.assertTrue(
                    set(seeded_topic.evidence_relations).isdisjoint(
                        relation
                        for relation in final_state.evidence_relations
                        if relation.relation_class == "proof"
                    )
                )

    def test_complete_verify_rejects_portrait_content_and_proof_link_tampering(self) -> None:
        source = materialize_source(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-portrait-result-tamper",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-portrait-result-tamper",
                protocol_timestamp="2026-08-24T09:18:00+08:00",
                received_at="2026-08-24T09:18:01+08:00",
                native_cursor="cursor-ticket112-portrait-result-tamper",
            )
        )
        before = self.core.daily_state()
        stage = self.daily_runtime.execute(source, before)
        after_stage = before.apply_evidence_stage(stage)
        complete = self.daily_runtime.complete(source, after_stage, stage)
        topic = complete.portrait_topics[0]
        forged_understanding = "篡改后的画像当前理解"
        forged_link = PortraitProofLink.form(
            evidence_id=topic.evidence_ids[0],
            relation_kind="supports",
            topic_ref=topic.topic_ref,
            item_kind="current-understanding",
            item_text=forged_understanding,
            applicable_period=(
                topic.current_understanding_applicable_periods[0]
            ),
        )
        forged_topic = replace(
            topic,
            current_understandings=(forged_understanding,),
            evidence_relations=tuple(
                relation
                for relation in topic.evidence_relations
                if relation.relation_class == "topic"
            ) + (forged_link.to_relation(),),
        )
        forged = replace(
            complete,
            portrait_topics=(forged_topic,),
            evidence_relations=forged_topic.evidence_relations,
        )

        self.assertFalse(
            forged.verify(
                source,
                after_stage,
                self.daily_bundle,
                self.daily_attestor,
                committed_evidence_stage=stage,
            )
        )

    def test_cross_type_corrects_and_withdraws_are_rejected_for_all_strong_types(self) -> None:
        topic_ref = "physical-function-and-experience/sleep"
        common = {
            "occurred_at": "2026-08-23",
            "applicable_period": "2026-08-23",
            "purpose": "cross-type-history-check",
            "uncertainty": "仍有边界",
            "limitations": ("不能跨强类型维护",),
            "does_not_prove": ("其他强类型主张",),
            "topic_refs": (topic_ref,),
            "time_certainty": "known",
        }
        claims = (
            AtomicEvidenceClaim(
                content="主人自述睡眠体验不佳",
                evidence_type="personal-health",
                source_kind="owner-statement",
                proves=("主人自述睡眠体验不佳",),
                specific_fields=PersonalHealthFields("owner-statement"),
                series_key=EvidenceSeriesKey(
                    "personal-health",
                    "subjective-sleep-experience",
                    PersonalEvidenceProfile("owner-statement"),
                    "single-night",
                ),
                **common,
            ),
            AtomicEvidenceClaim(
                content="资料中的一般睡眠知识",
                evidence_type="authoritative-knowledge",
                source_kind="publisher-material",
                proves=("资料中的一般睡眠知识",),
                specific_fields=AuthoritativeKnowledgeFields(
                    publisher="qualified-publisher",
                    material_version="2026-08-v1",
                    applicable_population="一般成年人",
                    validity_boundary="不证明主人个人事实",
                ),
                series_key=EvidenceSeriesKey(
                    "authoritative-knowledge",
                    "general-sleep-knowledge",
                    AuthoritativeKnowledgeProfile(
                        publisher="qualified-publisher",
                        applicable_population="一般成年人",
                        validity_boundary="不证明主人个人事实",
                        source_nature="publisher-material",
                    ),
                    "release",
                ),
                **common,
            ),
            AtomicEvidenceClaim(
                content="睡眠任务处于执行阶段",
                evidence_type="task-process",
                source_kind="task-ledger",
                proves=("睡眠任务处于执行阶段",),
                specific_fields=TaskProcessFields(
                    task_id="health-task:cross-type",
                    actual_stage="executing",
                    process_fact_kind="stage",
                    process_fact_ref="task-event:cross-type",
                ),
                series_key=EvidenceSeriesKey(
                    "task-process",
                    "task-stage-event",
                    TaskProcessProfile(
                        task_id="health-task:cross-type",
                        process_fact_kind="stage",
                        ledger_ref="task-ledger:health-task:cross-type",
                        source_nature="task-ledger",
                    ),
                    "task-event",
                ),
                **common,
            ),
        )
        existing_cards = tuple(
            EvidenceCard.from_claim(
                f"existing-source-{index}",
                claim,
                recorded_at=f"2026-08-24T01:4{index}:00Z",
            )
            for index, claim in enumerate(claims)
        )
        base = DailyHealthState(existing_cards, (), (), ())

        class AdmitOneExecutor:
            def __init__(self, claim: AtomicEvidenceClaim) -> None:
                self.claim = claim

            def __call__(self, skill_name: str, context: object) -> object:
                if skill_name == "health-steward":
                    return StewardPlan(
                        purpose="cross-type-history-check",
                        selected_skills=("health-evidence",),
                        atomic_claims=(self.claim,),
                    )
                if skill_name == "health-evidence":
                    return EvidenceDecision.admit(context.atomic_claim)
                raise AssertionError(skill_name)

        for source_index, claim in enumerate(claims):
            target = existing_cards[(source_index + 1) % len(existing_cards)]
            runtime = DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=AdmitOneExecutor(claim),
                clock=lambda source_index=source_index: datetime(
                    2026,
                    8,
                    24,
                    1,
                    50 + source_index,
                    tzinfo=timezone.utc,
                ),
            )
            source = materialize_source(
                self.message(
                    CountingBody("形成跨型历史关系候选"),
                    causal_id=f"ticket112-cross-type-{source_index}",
                    generation=2,
                    requested_capability="health-steward",
                    message_id=f"wx-ticket112-cross-type-{source_index}",
                    protocol_timestamp=f"2026-08-24T09:2{source_index}:00+08:00",
                    received_at=f"2026-08-24T09:2{source_index}:01+08:00",
                    native_cursor=f"cursor-ticket112-cross-type-{source_index}",
                )
            )
            stage = runtime.execute(source, base)
            for relation_kind in ("corrects", "withdraws"):
                forged = replace(
                    stage,
                    evidence_relations=(
                        EvidenceRelation(
                            stage.evidence_cards[0].evidence_id,
                            "history",
                            relation_kind,
                            "evidence-card",
                            target.evidence_id,
                        ),
                    ),
                )
                self.assertFalse(
                    forged.verify(
                        source,
                        base,
                        self.daily_bundle,
                        self.daily_attestor,
                    )
                )
                with self.assertRaises(AuthorityValidationError):
                    base.apply_evidence_stage(forged)
        self.assertIsNone(
            self.plugin.source_receipt(
                "ticket112-ordinary-source",
                peer_id="plugin",
            )
        )

    def test_evidence_finalized_lease_blocks_other_source_and_exact_replay_completes_once(self) -> None:
        self.route_classification = "health"
        self.turn_executor.fail_next_portrait = True
        first_changes = {
            "causal_id": "ticket112-two-phase-lease-owner",
            "generation": 2,
            "requested_capability": "health-steward",
            "message_id": "wx-ticket112-two-phase-lease-owner",
            "protocol_timestamp": "2026-08-24T09:05:00+08:00",
            "received_at": "2026-08-24T09:05:01+08:00",
            "native_cursor": "cursor-ticket112-two-phase-lease-owner",
        }

        interrupted = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **first_changes),
            peer_id="plugin",
        )

        self.assertEqual(interrupted.status, "unavailable")
        self.assertEqual(interrupted.reason_code, "daily-turn-candidate-invalid")
        stage_status = self.core.daily_turn_status(first_changes["causal_id"])
        self.assertIsNotNone(stage_status)
        self.assertEqual(stage_status.phase, "evidence-finalized")
        self.assertEqual(stage_status.draft.turn_kind, "evidence-stage")
        self.assertEqual(self.head.read().head.generation, 3)
        self.assertEqual(len(self.plugin.daily_state(peer_id="plugin").evidence_cards), 0)
        post_stage_state = self.core.daily_turn_post_stage_state(
            first_changes["causal_id"]
        )
        self.assertEqual(len(post_stage_state.evidence_cards), 1)
        self.assertEqual(
            post_stage_state.evidence_cards,
            stage_status.draft.evidence_cards,
        )
        self.assertFalse(
            self.plugin.source_receipt(
                first_changes["causal_id"],
                peer_id="plugin",
            ).business_committed
        )
        self.assertIsNone(
            self.plugin.native_cursor_directive(
                first_changes["causal_id"],
                peer_id="plugin",
            )
        )
        reopened = EncryptedStateStore(
            "file:ticket112?mode=memory&cache=shared",
            StaticKeyProvider(b"t" * 32, key_id="ticket112-state-key"),
        )
        try:
            durable_lease = reopened.unresolved_daily_turn()
            self.assertIsNotNone(durable_lease)
            self.assertEqual(durable_lease.phase, "evidence-finalized")
            self.assertEqual(durable_lease.draft, stage_status.draft)
            self.assertEqual(len(reopened.daily_state().evidence_cards), 0)
        finally:
            reopened.close()

        other_executor = SyntheticSleepTurnExecutor()
        other_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=other_executor,
                clock=lambda: datetime(2026, 8, 24, 1, 5, 30, tzinfo=timezone.utc),
            ),
        )
        other_message = self.message(
            CountingBody("我昨晚也没睡好"),
            causal_id="ticket112-two-phase-lease-other",
            generation=3,
            requested_capability="health-steward",
            message_id="wx-ticket112-two-phase-lease-other",
            protocol_timestamp="2026-08-24T09:05:30+08:00",
            received_at="2026-08-24T09:05:31+08:00",
            native_cursor="cursor-ticket112-two-phase-lease-other",
        )
        blocked = other_plugin.receive_weixin(
            other_message,
            peer_id="plugin",
        )

        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "daily-turn-busy")
        self.assertEqual(other_executor.calls, [])
        self.assertIsNone(
            self.store._execute(
                "SELECT 1 FROM command_receipts_v2 WHERE causal_id = ?",
                (
                    HealthPlugin._daily_turn_causal_id(
                        "evidence-prepare",
                        "ticket112-two-phase-lease-other",
                    ),
                ),
            ).fetchone()
        )
        self.assertIsNone(
            self.core.daily_turn_status("ticket112-two-phase-lease-other")
        )
        self.assertEqual(len(self.plugin.daily_state(peer_id="plugin").evidence_cards), 0)

        completed = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **first_changes),
            peer_id="plugin",
        )

        self.assertEqual(completed.status, "accepted")
        self.assertEqual(completed.reason_code, "daily-turn-finalized")
        self.assertIsInstance(completed.meta, DailyTurnMeta)
        self.assertEqual(self.head.read().head.generation, 4)
        self.assertEqual(self.turn_executor.calls.count("health-evidence"), 1)
        self.assertEqual(self.turn_executor.calls.count("health-portrait"), 2)
        self.assertEqual(
            self.turn_executor.calls,
            [
                "health-steward",
                "health-evidence",
                "health-portrait",
                "health-portrait",
                "health-steward",
            ],
        )
        final_status = self.core.daily_turn_status(first_changes["causal_id"])
        self.assertIsNotNone(final_status)
        self.assertEqual(final_status.phase, "finalized")
        self.assertIsNone(final_status.draft)
        self.assertEqual(final_status.terminal.stage_kind, "complete-turn")
        self.assertEqual(len(self.plugin.daily_state(peer_id="plugin").evidence_cards), 1)
        self.assertTrue(
            self.plugin.source_receipt(
                first_changes["causal_id"],
                peer_id="plugin",
            ).business_committed
        )
        self.assertIsNotNone(
            self.plugin.native_cursor_directive(
                first_changes["causal_id"],
                peer_id="plugin",
            )
        )

        other_completed = other_plugin.receive_weixin(
            other_message,
            peer_id="plugin",
        )
        self.assertEqual(other_completed.status, "accepted")
        self.assertEqual(other_completed.reason_code, "daily-turn-finalized")
        self.assertIsInstance(other_completed.meta, DailyTurnMeta)
        self.assertEqual(len(other_completed.meta.turn_result.evidence_ids), 1)
        self.assertEqual(
            other_executor.calls,
            [
                "health-steward",
                "health-evidence",
                "health-portrait",
                "health-steward",
            ],
        )
        self.assertEqual(self.head.read().head.generation, 6)
        final_state = self.plugin.daily_state(peer_id="plugin")
        self.assertEqual(
            final_state.processed_source_causal_ids,
            (
                first_changes["causal_id"],
                "ticket112-two-phase-lease-other",
            ),
        )
        self.assertEqual(
            len(
                {
                    card.evidence_id
                    for card in final_state.evidence_cards
                    if card.source_causal_id == "ticket112-two-phase-lease-other"
                }
            ),
            1,
        )
        other_status = self.core.daily_turn_status(
            "ticket112-two-phase-lease-other"
        )
        self.assertIsNotNone(other_status)
        self.assertEqual(other_status.phase, "finalized")
        self.assertEqual(final_status.terminal.ordinal, 1)
        self.assertEqual(other_status.terminal.ordinal, 2)
        self.assertEqual(
            other_status.terminal.previous_terminal_digest,
            final_status.terminal.digest,
        )
        self.assertTrue(
            self.store.verify_integrity(self.store.finalized_authority())
        )

    def test_runtime_preparation_lock_closes_same_core_concurrent_lease_race(self) -> None:
        sources = tuple(
            materialize_source(
                self.message(
                    CountingBody("我昨晚没睡好"),
                    causal_id=f"ticket112-runtime-race-{suffix}",
                    generation=2,
                    requested_capability="health-steward",
                    message_id=f"wx-ticket112-runtime-race-{suffix}",
                    protocol_timestamp=f"2026-08-24T09:0{7 + index}:00+08:00",
                    received_at=f"2026-08-24T09:0{7 + index}:01+08:00",
                    native_cursor=f"cursor-ticket112-runtime-race-{suffix}",
                )
            )
            for index, suffix in enumerate(("owner", "contender"))
        )
        for source in sources:
            admitted = self.plugin.invoke(
                CommandEnvelope(
                    peer="plugin",
                    action="inbound.admit",
                    source="health_weixin",
                    causal_id=source.causal_id,
                    generation=2,
                    scope=("inbound:admit",),
                    payload=InboundAdmitPayload(source, self.policy),
                ),
                peer_id="plugin",
            )
            self.assertEqual(admitted.status, "accepted")

        owner_executor = SyntheticSleepTurnExecutor()
        contender_executor = SyntheticSleepTurnExecutor()
        owner_runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=owner_executor,
            clock=lambda: datetime(2026, 8, 24, 1, 7, tzinfo=timezone.utc),
        )
        contender_runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=contender_executor,
            clock=lambda: datetime(2026, 8, 24, 1, 8, tzinfo=timezone.utc),
        )
        owner_stage_formed = threading.Event()
        allow_owner_prepare = threading.Event()
        contender_started = threading.Event()
        contender_finished = threading.Event()
        outcomes: dict[str, object] = {}

        def owner_worker() -> None:
            try:
                with self.core.daily_turn_runtime_preparation(
                    sources[0].causal_id
                ) as preparation:
                    outcomes["owner_preparation"] = preparation
                    draft = owner_runtime.execute_evidence_stage(
                        sources[0],
                        self.core.daily_state(),
                    )
                    owner_stage_formed.set()
                    if not allow_owner_prepare.wait(5):
                        raise TimeoutError("owner prepare release timed out")
                    outcomes["owner_response"] = self.plugin.invoke(
                        CommandEnvelope(
                            peer="plugin",
                            action="turn.prepare",
                            source="daily_skill_runtime",
                            causal_id=HealthPlugin._daily_turn_causal_id(
                                "evidence-prepare",
                                sources[0].causal_id,
                            ),
                            generation=preparation.generation,
                            scope=("turn:prepare",),
                            payload=DailyTurnPreparePayload(draft),
                        ),
                        peer_id="plugin",
                    )
            except BaseException as exc:
                outcomes["owner_error"] = exc

        def contender_worker() -> None:
            try:
                contender_started.set()
                with self.core.daily_turn_runtime_preparation(
                    sources[1].causal_id
                ) as preparation:
                    outcomes["contender_preparation"] = preparation
                    if preparation.ready:
                        contender_runtime.execute_evidence_stage(
                            sources[1],
                            self.core.daily_state(),
                        )
            except BaseException as exc:
                outcomes["contender_error"] = exc
            finally:
                contender_finished.set()

        owner_thread = threading.Thread(target=owner_worker)
        contender_thread = threading.Thread(target=contender_worker)
        owner_thread.start()
        self.assertTrue(owner_stage_formed.wait(5))
        contender_thread.start()
        self.assertTrue(contender_started.wait(5))
        self.assertFalse(contender_finished.wait(0.05))
        allow_owner_prepare.set()
        owner_thread.join(5)
        contender_thread.join(5)

        self.assertFalse(owner_thread.is_alive())
        self.assertFalse(contender_thread.is_alive())
        self.assertNotIn("owner_error", outcomes)
        self.assertNotIn("contender_error", outcomes)
        self.assertTrue(outcomes["owner_preparation"].ready)
        self.assertEqual(outcomes["owner_response"].status, "accepted")
        self.assertFalse(outcomes["contender_preparation"].ready)
        self.assertEqual(
            outcomes["contender_preparation"].reason_code,
            "daily-turn-busy",
        )
        self.assertEqual(contender_executor.calls, [])

    def test_sleep_turn_commits_one_personal_card_portrait_and_one_reply(self) -> None:
        self.route_classification = "health"
        body = CountingBody("我昨晚没睡好")

        response = self.plugin.receive_weixin(
            self.message(
                body,
                causal_id="ticket112-sleep-source",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-sleep",
                protocol_timestamp="2026-08-24T09:06:00+08:00",
                received_at="2026-08-24T09:06:01+08:00",
                native_cursor="cursor-ticket112-sleep",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "accepted")
        self.assertEqual(response.reason_code, "daily-turn-finalized")
        self.assertIsInstance(response.meta, DailyTurnMeta)
        result = response.meta.turn_result
        self.assertEqual(
            tuple(item.canonical_name for item in result.skill_disclosures),
            ("health-steward", "health-evidence", "health-portrait"),
        )
        self.assertEqual(len(result.evidence_ids), 1)
        self.assertEqual(result.portrait_topics, ("physical-function-and-experience/sleep",))
        self.assertIn("已记录：主人自述昨晚主观睡眠体验不佳", result.owner_reply)
        self.assertIn("未形成睡眠时长、长期趋势、失眠诊断或健康任务", result.owner_reply)
        self.assertNotIn("health-init", result.owner_reply)
        disclosure_line = (
            "🩺 本轮使用：健康管家（health-steward，1.0.0）；"
            "健康证据维护（health-evidence，1.0.0）；"
            "健康画像维护（health-portrait，1.0.0）。"
        )
        self.assertIn(disclosure_line, result.owner_reply)
        self.assertEqual(result.owner_reply.count("🩺 本轮使用："), 1)

        state = self.plugin.daily_state(peer_id="plugin")
        self.assertEqual(len(state.evidence_cards), 1)
        card = state.evidence_cards[0]
        self.assertEqual(card.evidence_type, "personal-health")
        self.assertEqual(card.content, "主人自述昨晚主观睡眠体验不佳")
        self.assertEqual(card.topic_refs, ("physical-function-and-experience/sleep",))
        self.assertEqual(len(state.portrait_topics), 1)
        topic = state.portrait_topics[0]
        self.assertEqual(topic.trend, None)
        self.assertEqual(topic.related_task_ids, ())
        self.assertEqual(topic.evidence_ids, (card.evidence_id,))
        self.assertEqual(
            tuple(relation.relation_class for relation in topic.evidence_relations),
            ("topic", "proof", "proof", "proof"),
        )
        self.assertEqual(state.evidence_relations, topic.evidence_relations)
        self.assertEqual(body.reads, 1)
        self.assertTrue(
            self.plugin.source_receipt(
                "ticket112-sleep-source",
                peer_id="plugin",
            ).business_committed
        )

    def test_finalized_journal_keeps_terminal_digests_not_the_full_turn_draft(self) -> None:
        self.route_classification = "health"
        source_causal_id = "ticket112-terminal-journal"

        response = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id=source_causal_id,
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-terminal-journal",
                protocol_timestamp="2026-08-24T09:07:00+08:00",
                received_at="2026-08-24T09:07:01+08:00",
                native_cursor="cursor-ticket112-terminal-journal",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "accepted", response)
        turn = self.store.daily_turn(source_causal_id)
        self.assertEqual(turn.phase, "finalized")
        self.assertIsNone(turn.draft)
        self.assertIsNotNone(turn.terminal)
        self.assertEqual(turn.terminal.stage_kind, "complete-turn")
        self.assertEqual(turn.terminal.ordinal, 1)
        self.assertEqual(turn.terminal.state_digest, self.store.daily_state().digest)
        self.assertEqual(
            tuple(item.action for item in turn.terminal.skill_uses),
            ("plan", "evaluate-evidence", "maintain-portrait", "resolve"),
        )
        self.assertIsNone(turn.terminal.skill_uses[0].parent_proof_digest)
        self.assertEqual(
            tuple(
                item.parent_proof_digest
                for item in turn.terminal.skill_uses[1:]
            ),
            turn.terminal.skill_proof_digests[:-1],
        )
        row = self.store._execute(
            "SELECT record_id, nonce, ciphertext FROM daily_turns_v1 "
            "WHERE source_causal_id = ?",
            (source_causal_id,),
        ).fetchone()
        plaintext = self.store._open(
            f"daily-turn:{source_causal_id}:{row[0]}:finalized",
            row[1],
            row[2],
        )
        self.assertEqual(set(plaintext), {"terminal", "result"})
        self.assertNotIn("draft", repr(plaintext))
        self.assertNotIn("steward_plan", repr(plaintext))
        self.assertNotIn("signature", repr(plaintext))
        self.assertNotIn("attestor_key_id", repr(plaintext))
        for prepare_stage in ("evidence-prepare", "complete-prepare"):
            prepare_causal_id = HealthPlugin._daily_turn_causal_id(
                prepare_stage,
                source_causal_id,
            )
            receipt_row = self.store._execute(
                "SELECT nonce, ciphertext FROM command_receipts_v2 "
                "WHERE causal_id = ?",
                (prepare_causal_id,),
            ).fetchone()
            self.assertIsNotNone(receipt_row)
            receipt_plaintext = self.store._open(
                f"receipt:v2:{prepare_causal_id}",
                receipt_row[0],
                receipt_row[1],
            )
            self.assertEqual(
                set(receipt_plaintext),
                {"kind", "command_digest", "response"},
            )
            self.assertNotIn("draft", repr(receipt_plaintext))
        self.assertTrue(self.store.verify_integrity(self.store.finalized_authority()))
        reopened = EncryptedStateStore(
            "file:ticket112?mode=memory&cache=shared",
            StaticKeyProvider(b"t" * 32, key_id="ticket112-state-key"),
        )
        try:
            reopened_turn = reopened.daily_turn(source_causal_id)
            self.assertIsNone(reopened_turn.draft)
            self.assertEqual(
                reopened_turn.terminal.digest,
                turn.terminal.digest,
            )
            self.assertTrue(reopened.verify_integrity(reopened.finalized_authority()))
        finally:
            reopened.close()

    def test_terminal_chain_is_verified_without_replaying_finalized_drafts(self) -> None:
        self.route_classification = "health"
        executor = SeriesCompactionExecutor()
        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda: datetime(2026, 8, 24, 1, 8, tzinfo=timezone.utc),
            ),
        )
        for index in range(2):
            source_causal_id = f"ticket112-terminal-chain-{index}"
            content = f"主人第{index + 1}晚自述睡眠体验不佳"
            executor.claim = AtomicEvidenceClaim(
                content=content,
                evidence_type="personal-health",
                source_kind="owner-statement",
                occurred_at=f"2026-08-{index + 20:02d}",
                applicable_period=f"2026-08-{index + 20:02d}-night",
                purpose="terminal-chain-validation",
                uncertainty="主人主观体验",
                limitations=("单次陈述不证明趋势",),
                proves=(content,),
                does_not_prove=("长期趋势",),
                topic_refs=("physical-function-and-experience/sleep",),
                specific_fields=PersonalHealthFields("owner-statement"),
                series_key=EvidenceSeriesKey(
                    "personal-health",
                    "subjective-sleep-experience",
                    PersonalEvidenceProfile("owner-statement"),
                    "single-night",
                ),
                time_certainty="known",
            )
            response = plugin.receive_weixin(
                self.message(
                    CountingBody(content),
                    causal_id=source_causal_id,
                    generation=self.head.read().head.generation,
                    requested_capability="health-steward",
                    message_id=f"wx-{source_causal_id}",
                    protocol_timestamp=f"2026-08-24T09:0{8 + index}:00+08:00",
                    received_at=f"2026-08-24T09:0{8 + index}:01+08:00",
                    native_cursor=f"cursor-{source_causal_id}",
                ),
                peer_id="plugin",
            )
            self.assertEqual(response.status, "accepted", response)

        first = self.store.daily_turn("ticket112-terminal-chain-0")
        second = self.store.daily_turn("ticket112-terminal-chain-1")
        self.assertIsNone(first.draft)
        self.assertIsNone(second.draft)
        self.assertEqual(first.terminal.ordinal, 1)
        self.assertEqual(second.terminal.ordinal, 2)
        self.assertEqual(
            second.terminal.previous_terminal_digest,
            first.terminal.digest,
        )
        row = self.store._execute(
            "SELECT record_id, nonce, ciphertext FROM daily_turns_v1 "
            "WHERE source_causal_id = ?",
            ("ticket112-terminal-chain-1",),
        ).fetchone()
        aad = f"daily-turn:ticket112-terminal-chain-1:{row[0]}:finalized"
        plaintext = self.store._open(aad, row[1], row[2])
        plaintext["terminal"]["previous_terminal_digest"] = "sha256:" + ("0" * 64)
        forged_nonce, forged_ciphertext = self.store._seal(aad, plaintext)
        with self.store.transaction() as connection:
            self.store._assert_integrity_manifest_before_mutation()
            connection.execute(
                "UPDATE daily_turns_v1 SET nonce = ?, ciphertext = ? "
                "WHERE source_causal_id = ?",
                (
                    forged_nonce,
                    forged_ciphertext,
                    "ticket112-terminal-chain-1",
                ),
            )
            self.store._refresh_integrity_manifest(connection)
        with self.assertRaisesRegex(KeyUnavailable, "terminal chain"):
            self.store.verify_integrity(self.store.finalized_authority())
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE daily_turns_v1 SET nonce = ?, ciphertext = ? "
                "WHERE source_causal_id = ?",
                (row[1], row[2], "ticket112-terminal-chain-1"),
            )
            self.store._refresh_integrity_manifest(connection)

    def test_health_mixed_and_uncertain_all_use_the_single_steward_route(self) -> None:
        for index, classification in enumerate(("health", "mixed", "uncertain"), start=1):
            self.route_classification = classification
            causal_id = f"ticket112-conservative-{index}"
            response = self.plugin.receive_weixin(
                self.message(
                    CountingBody("我昨晚没睡好"),
                    causal_id=causal_id,
                    generation=self.head.read().head.generation,
                    requested_capability="health-steward",
                    message_id=f"wx-{causal_id}",
                    protocol_timestamp=f"2026-08-24T09:1{index}:00+08:00",
                    received_at=f"2026-08-24T09:1{index}:01+08:00",
                    native_cursor=f"cursor-{causal_id}",
                ),
                peer_id="plugin",
            )

            self.assertEqual(response.status, "accepted")
            self.assertEqual(response.reason_code, "daily-turn-finalized")
            self.assertTrue(
                self.plugin.source_receipt(causal_id, peer_id="plugin").business_committed
            )

        self.assertEqual(
            self.turn_executor.calls,
            [
                "health-steward",
                "health-evidence",
                "health-portrait",
                "health-steward",
            ] * 3,
        )

    def test_explicit_b_role_entry_still_runs_through_health_steward_first(self) -> None:
        self.route_classification = "ordinary"
        calls: list[str] = []

        def executor(skill_name, context):
            calls.append(skill_name)
            if skill_name != "health-steward":
                raise AssertionError(skill_name)
            if type(context) is StewardResolutionContext:
                return StewardResolution(
                    context.candidate_evidence_ids,
                    context.candidate_portrait_topic_refs,
                    tuple(atom.atom_id for atom in context.reply_atoms),
                    context.candidate_evidence_change_ids,
                )
            return StewardPlan(
                purpose="route-explicit-b-through-steward",
                selected_skills=(),
                atomic_claims=(),
            )

        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda: datetime(2026, 8, 24, 2, 14, tzinfo=timezone.utc),
            ),
        )
        for index, requested_capability in enumerate(
            (
                "health-evidence",
                "health-portrait",
                "health-owner-inquiry",
                "health-literature",
            ),
            start=1,
        ):
            calls_before = len(calls)
            response = plugin.receive_weixin(
                self.message(
                    CountingBody("我昨晚没睡好"),
                    causal_id=f"ticket112-explicit-b-source-{index}",
                    generation=self.head.read().head.generation,
                    requested_capability=requested_capability,
                    message_id=f"wx-ticket112-explicit-b-{index}",
                    protocol_timestamp=f"2026-08-24T09:1{index}:00+08:00",
                    received_at=f"2026-08-24T09:1{index}:01+08:00",
                    native_cursor=f"cursor-ticket112-explicit-b-{index}",
                ),
                peer_id="plugin",
            )

            self.assertEqual(response.status, "accepted")
            self.assertNotEqual(response.reason_code, "ordinary-hermes-route")
            self.assertEqual(
                calls[calls_before],
                "health-steward",
            )
            self.assertEqual(
                tuple(
                    item.canonical_name
                    for item in response.meta.turn_result.skill_disclosures
                ),
                ("health-steward",),
            )

    def test_router_failure_is_uncertain_and_never_falls_through_to_ordinary_chat(self) -> None:
        def broken_classifier(body, requested_capability):
            del body, requested_capability
            raise RuntimeError("synthetic classifier failure")

        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=CoarseMessageRouter(broken_classifier),
            daily_skill_runtime=self.daily_runtime,
        )
        response = plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-router-failure",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-router-failure",
                protocol_timestamp="2026-08-24T09:16:00+08:00",
                received_at="2026-08-24T09:16:01+08:00",
                native_cursor="cursor-ticket112-router-failure",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "accepted")
        self.assertEqual(response.reason_code, "daily-turn-finalized")
        self.assertEqual(self.turn_executor.calls[0], "health-steward")

    def test_missing_required_portrait_context_stops_without_guessing_or_partial_commit(self) -> None:
        calls: list[str] = []

        def executor(skill_name, context):
            calls.append(skill_name)
            if skill_name == "health-steward":
                if type(context) is StewardResolutionContext:
                    return StewardResolution(
                        commit_evidence_ids=context.candidate_evidence_ids,
                        commit_portrait_topic_refs=(
                            context.candidate_portrait_topic_refs
                        ),
                        reply_atom_ids=tuple(
                            atom.atom_id for atom in context.reply_atoms
                        ),
                        commit_evidence_change_ids=(
                            context.candidate_evidence_change_ids
                        ),
                    )
                return StewardPlan(
                    purpose="portrait-without-evidence",
                    selected_skills=("health-portrait",),
                    portrait_topic_refs=(
                        "physical-function-and-experience/sleep",
                    ),
                    atomic_claims=(),
                )
            if skill_name == "health-portrait":
                self.assertIs(type(context), PortraitContext)
                self.assertEqual(context.evidence_ids, ())
                return PortraitDecision.gap("required-context-unavailable")
            raise AssertionError(f"unexpected Skill execution: {skill_name}")

        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda: datetime(2026, 8, 24, 1, 17, tzinfo=timezone.utc),
            ),
        )
        self.route_classification = "health"
        response = plugin.receive_weixin(
            self.message(
                CountingBody("请更新我的睡眠画像"),
                causal_id="ticket112-missing-context",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-missing-context",
                protocol_timestamp="2026-08-24T09:17:00+08:00",
                received_at="2026-08-24T09:17:01+08:00",
                native_cursor="cursor-ticket112-missing-context",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "accepted")
        self.assertEqual(response.reason_code, "daily-turn-finalized")
        self.assertEqual(
            calls,
            ["health-steward", "health-portrait", "health-steward"],
        )
        self.assertEqual(
            self.core.daily_turn_status("ticket112-missing-context").phase,
            "finalized",
        )
        self.assertEqual(plugin.daily_state(peer_id="plugin").evidence_cards, ())
        self.assertEqual(plugin.daily_state(peer_id="plugin").portrait_topics, ())
        self.assertIn("画像处理所需资料不足", response.meta.turn_result.owner_reply)

    def test_rejected_and_clarification_candidates_never_enter_authoritative_evidence(self) -> None:
        self.route_classification = "health"
        for index, decision_name in enumerate(("reject", "clarify"), start=1):
            claim = AtomicEvidenceClaim(
                content=f"待判断睡眠候选{index}",
                evidence_type="personal-health",
                source_kind="owner-statement",
                occurred_at="2026-08-23",
                applicable_period="2026-08-23-night",
                purpose="evidence-admission-check",
                uncertainty="来源内容不足",
                limitations=("不能支持画像",),
                proves=(f"待判断睡眠候选{index}",),
                does_not_prove=("个人健康事实",),
                topic_refs=("physical-function-and-experience/sleep",),
                specific_fields=PersonalHealthFields("owner-statement"),
                series_key=EvidenceSeriesKey(
                    "personal-health",
                    "subjective-sleep-experience",
                    PersonalEvidenceProfile("owner-statement"),
                    "single-night",
                ),
                time_certainty="known",
            )

            def executor(skill_name, context, *, claim=claim, decision_name=decision_name):
                if skill_name == "health-steward":
                    if type(context) is StewardResolutionContext:
                        return StewardResolution(
                            commit_evidence_ids=context.candidate_evidence_ids,
                            commit_portrait_topic_refs=context.candidate_portrait_topic_refs,
                            reply_atom_ids=tuple(
                                atom.atom_id for atom in context.reply_atoms
                            ),
                        )
                    return StewardPlan(
                        purpose="evidence-admission-check",
                        selected_skills=("health-evidence",),
                        atomic_claims=(claim,),
                    )
                if decision_name == "reject":
                    return EvidenceDecision.reject("source-boundary-failed")
                return EvidenceDecision.clarify("occurrence-time-required")

            plugin = HealthPlugin(
                self.core,
                admission_policy=self.policy,
                health_init_runtime=self.init_runtime,
                coarse_router=self.router,
                daily_skill_runtime=DailySkillRuntime(
                    self.daily_bundle,
                    self.daily_attestor,
                    executor=executor,
                    clock=lambda index=index: datetime(
                        2026,
                        8,
                        24,
                        2,
                        20 + index,
                        tzinfo=timezone.utc,
                    ),
                ),
            )
            causal_id = f"ticket112-evidence-{decision_name}"
            response = plugin.receive_weixin(
                self.message(
                    CountingBody("这条信息还不完整"),
                    causal_id=causal_id,
                    generation=self.head.read().head.generation,
                    requested_capability="health-steward",
                    message_id=f"wx-{causal_id}",
                    protocol_timestamp=f"2026-08-24T10:2{index}:00+08:00",
                    received_at=f"2026-08-24T10:2{index}:01+08:00",
                    native_cursor=f"cursor-{causal_id}",
                ),
                peer_id="plugin",
            )

            self.assertEqual(response.status, "accepted")
            self.assertEqual(response.meta.turn_result.evidence_ids, ())
            self.assertEqual(response.meta.turn_result.portrait_topics, ())
            self.assertIn("未写入权威证据或画像", response.meta.turn_result.owner_reply)

        state = self.plugin.daily_state(peer_id="plugin")
        self.assertEqual(state.evidence_cards, ())
        self.assertEqual(state.portrait_topics, ())

    def test_daily_contexts_are_exact_purpose_limited_projections(self) -> None:
        self.route_classification = "health"
        response = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-context-source",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-context",
                protocol_timestamp="2026-08-24T09:20:00+08:00",
                received_at="2026-08-24T09:20:01+08:00",
                native_cursor="cursor-ticket112-context",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "accepted")
        self.assertEqual(
            set(vars(self.turn_executor.context_history[0][1])),
            {
                "source_causal_id",
                "requested_capability",
                "owner_message",
                "health_navigation",
            },
        )
        self.assertIs(type(self.turn_executor.context_history[0][1]), StewardContext)
        self.assertEqual(
            set(vars(self.turn_executor.contexts["health-steward"])),
            {
                "source_causal_id",
                "purpose",
                "responsibility_results",
                "candidate_evidence_ids",
                "candidate_portrait_topic_refs",
                "reply_atoms",
                "candidate_evidence_change_ids",
            },
        )
        self.assertIs(
            type(self.turn_executor.contexts["health-steward"]),
            StewardResolutionContext,
        )
        self.assertEqual(
            set(vars(self.turn_executor.contexts["health-evidence"])),
            {
                "source_causal_id",
                "purpose",
                "atomic_claim",
                "maintenance_request",
                "base_state_digest",
                "related_existing_cards",
                "related_relations",
                "current_evidence_ids",
                "related_applicability_changes",
                "series_window",
            },
        )
        self.assertEqual(
            set(vars(self.turn_executor.contexts["health-portrait"])),
            {
                "source_causal_id",
                "purpose",
                "base_state_digest",
                "affected_topic_refs",
                "current_topic_views",
                "committed_related_cards",
                "committed_relations",
                "in_turn_evidence_candidates",
                "related_task_refs",
            },
        )

    def test_replaying_finalized_source_does_not_rerun_skills_or_duplicate_state(self) -> None:
        self.route_classification = "health"
        changes = {
            "causal_id": "ticket112-replay-source",
            "generation": 2,
            "requested_capability": "health-steward",
            "message_id": "wx-ticket112-replay",
            "protocol_timestamp": "2026-08-24T09:30:00+08:00",
            "received_at": "2026-08-24T09:30:01+08:00",
            "native_cursor": "cursor-ticket112-replay",
        }
        first = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **changes),
            peer_id="plugin",
        )
        calls_after_first = tuple(self.turn_executor.calls)
        second = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **changes),
            peer_id="plugin",
        )

        self.assertEqual(first.status, "accepted")
        self.assertEqual(second.status, "accepted")
        self.assertEqual(second.reason_code, "daily-turn-finalized")
        self.assertEqual(tuple(self.turn_executor.calls), calls_after_first)
        state = self.plugin.daily_state(peer_id="plugin")
        self.assertEqual(len(state.evidence_cards), 1)
        self.assertEqual(state.processed_source_causal_ids, ("ticket112-replay-source",))

    def test_runtime_asset_version_drift_cannot_commit_or_disclose_a_candidate(self) -> None:
        rotated_assets = tuple(
            replace(
                asset,
                version="2.0.0" if asset.canonical_name == "health-evidence" else asset.version,
                asset_digest=(
                    "sha256:" + ("8" * 64)
                    if asset.canonical_name == "health-evidence"
                    else asset.asset_digest
                ),
            )
            for asset in self.daily_bundle.assets
        )
        rotated_runtime = DailySkillRuntime(
            DailySkillBundle(rotated_assets),
            self.daily_attestor,
            executor=SyntheticSleepTurnExecutor(),
            clock=lambda: datetime(2026, 8, 24, 1, 40, tzinfo=timezone.utc),
        )
        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=rotated_runtime,
        )
        self.route_classification = "health"

        response = plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-version-drift",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-version-drift",
                protocol_timestamp="2026-08-24T09:40:00+08:00",
                received_at="2026-08-24T09:40:01+08:00",
                native_cursor="cursor-ticket112-version-drift",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "rejected")
        self.assertEqual(response.reason_code, "daily-skill-proof-required")
        self.assertIsNone(self.core.daily_turn_status("ticket112-version-drift"))
        self.assertEqual(plugin.daily_state(peer_id="plugin").evidence_cards, ())
        self.assertFalse(
            plugin.source_receipt("ticket112-version-drift", peer_id="plugin").business_committed
        )
        self.assertFalse(plugin.outbound_effects_allowed())

    def test_forged_skill_use_signature_is_rejected_at_the_plugin_core_seam(self) -> None:
        source = materialize_source(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-forged-proof",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-forged-proof",
                protocol_timestamp="2026-08-24T09:45:00+08:00",
                received_at="2026-08-24T09:45:01+08:00",
                native_cursor="cursor-ticket112-forged-proof",
            )
        )
        admitted = self.plugin.invoke(
            CommandEnvelope(
                peer="plugin",
                action="inbound.admit",
                source="health_weixin",
                causal_id=source.causal_id,
                generation=2,
                scope=("inbound:admit",),
                payload=InboundAdmitPayload(source, self.policy),
            ),
            peer_id="plugin",
        )
        self.assertEqual(admitted.status, "accepted")
        draft = self.daily_runtime.execute(source, self.core.daily_state())
        forged_proof = replace(
            draft.skill_proofs[1],
            signature="hmac-sha256:" + ("0" * 64),
        )
        forged_draft = replace(
            draft,
            skill_proofs=(
                draft.skill_proofs[0],
                forged_proof,
            ),
        )

        response = self.plugin.invoke(
            CommandEnvelope(
                peer="plugin",
                action="turn.prepare",
                source="daily_skill_runtime",
                causal_id="ticket112-forged-proof-prepare",
                generation=2,
                scope=("turn:prepare",),
                payload=DailyTurnPreparePayload(forged_draft),
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "rejected")
        self.assertEqual(response.reason_code, "daily-skill-proof-required")
        self.assertIsNone(self.core.daily_turn_status(source.causal_id))
        self.assertEqual(self.plugin.daily_state(peer_id="plugin").evidence_cards, ())

    def test_owner_reply_cannot_be_changed_after_the_steward_resolution_proof(self) -> None:
        source = materialize_source(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-forged-reply",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-forged-reply",
                protocol_timestamp="2026-08-24T09:46:00+08:00",
                received_at="2026-08-24T09:46:01+08:00",
                native_cursor="cursor-ticket112-forged-reply",
            )
        )
        before = self.core.daily_state()
        evidence_stage = self.daily_runtime.execute(
            source,
            before,
        )
        post_stage_state = before.apply_evidence_stage(evidence_stage)
        complete_draft = self.daily_runtime.complete(
            source,
            post_stage_state,
            evidence_stage,
        )
        forged_draft = replace(
            complete_draft,
            owner_reply="设置已经生效。",
        )

        self.assertFalse(
            forged_draft.verify(
                source,
                post_stage_state,
                self.daily_bundle,
                self.daily_attestor,
                committed_evidence_stage=evidence_stage,
            )
        )

    def test_finalize_failure_rolls_back_all_business_facts_and_replay_resumes(self) -> None:
        self.route_classification = "health"
        self.store.fail_next_daily_finalize = True
        changes = {
            "causal_id": "ticket112-atomic-source",
            "generation": 2,
            "requested_capability": "health-steward",
            "message_id": "wx-ticket112-atomic",
            "protocol_timestamp": "2026-08-24T09:50:00+08:00",
            "received_at": "2026-08-24T09:50:01+08:00",
            "native_cursor": "cursor-ticket112-atomic",
        }

        failed = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **changes),
            peer_id="plugin",
        )

        self.assertEqual(failed.status, "unavailable")
        self.assertEqual(failed.reason_code, "health-state-unavailable")
        status = self.core.daily_turn_status("ticket112-atomic-source")
        self.assertIsNotNone(status)
        self.assertEqual(status.phase, "committed")
        with self.assertRaises(AuthorityValidationError):
            self.plugin.daily_state(peer_id="plugin")
        self.assertIsNone(
            self.plugin.source_receipt("ticket112-atomic-source", peer_id="plugin")
        )
        self.assertIsNone(
            self.plugin.native_cursor_directive(
                "ticket112-atomic-source",
                peer_id="plugin",
            )
        )
        calls_after_failure = tuple(self.turn_executor.calls)

        recovered = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **changes),
            peer_id="plugin",
        )

        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(recovered.reason_code, "daily-turn-finalized")
        self.assertEqual(tuple(self.turn_executor.calls), calls_after_failure)
        self.assertEqual(len(self.plugin.daily_state(peer_id="plugin").evidence_cards), 1)
        self.assertTrue(
            self.plugin.source_receipt("ticket112-atomic-source", peer_id="plugin").business_committed
        )

    def test_native_cursor_is_released_only_for_the_finalized_daily_transition(self) -> None:
        self.route_classification = "health"
        response = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-cursor-source",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-cursor",
                protocol_timestamp="2026-08-24T10:00:00+08:00",
                received_at="2026-08-24T10:00:01+08:00",
                native_cursor="cursor-ticket112-daily",
            ),
            peer_id="plugin",
        )

        directive = self.plugin.native_cursor_directive(
            "ticket112-cursor-source",
            peer_id="plugin",
        )
        self.assertIsNotNone(directive)
        self.assertEqual(
            directive.business_transition_id,
            response.meta.turn_result.transition_id,
        )
        self.assertEqual(directive.native_cursor, "cursor-ticket112-daily")

        advanced = self.plugin.record_native_cursor_result(
            directive,
            status="advanced",
            peer_id="plugin",
        )

        self.assertEqual(advanced.status, "accepted")
        self.assertEqual(advanced.reason_code, "native-cursor-advanced")
        self.assertEqual(
            self.plugin.source_receipt(
                "ticket112-cursor-source",
                peer_id="plugin",
            ).native_cursor_state,
            "advanced",
        )
        terminal = self.core.daily_turn_status("ticket112-cursor-source")
        self.assertEqual(terminal.phase, "finalized")
        self.assertIsNone(terminal.result)

        calls_after_delivery = tuple(self.turn_executor.calls)
        replay = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-cursor-source",
                generation=2,
                requested_capability="health-steward",
                message_id="wx-ticket112-cursor",
                protocol_timestamp="2026-08-24T10:00:00+08:00",
                received_at="2026-08-24T10:00:01+08:00",
                native_cursor="cursor-ticket112-daily",
            ),
            peer_id="plugin",
        )
        self.assertEqual(replay.status, "accepted")
        self.assertEqual(replay.reason_code, "daily-turn-result-redacted")
        self.assertEqual(tuple(self.turn_executor.calls), calls_after_delivery)

    def test_settings_inquiry_and_literature_return_only_typed_candidates_or_gaps(self) -> None:
        self.route_classification = "health"
        expected = {
            "settings": (
                "health-settings",
                SettingsContext,
                "资料不足",
            ),
            "inquiry": (
                "health-owner-inquiry",
                OwnerInquiryContext,
                "上下文不足",
            ),
            "literature": (
                "health-literature",
                LiteratureContext,
                "没有合格资料",
            ),
        }
        for index, (mode, (skill_name, context_type, reply_text)) in enumerate(
            expected.items(),
            start=1,
        ):
            executor = BoundaryResponsibilityExecutor(mode)
            runtime = DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda index=index: datetime(
                    2026,
                    8,
                    24,
                    2,
                    index,
                    tzinfo=timezone.utc,
                ),
            )
            plugin = HealthPlugin(
                self.core,
                admission_policy=self.policy,
                health_init_runtime=self.init_runtime,
                coarse_router=self.router,
                daily_skill_runtime=runtime,
            )
            causal_id = f"ticket112-boundary-{mode}"

            response = plugin.receive_weixin(
                self.message(
                    CountingBody("请处理这个健康请求"),
                    causal_id=causal_id,
                    generation=self.head.read().head.generation,
                    requested_capability="health-steward",
                    message_id=f"wx-{causal_id}",
                    protocol_timestamp=f"2026-08-24T10:1{index}:00+08:00",
                    received_at=f"2026-08-24T10:1{index}:01+08:00",
                    native_cursor=f"cursor-{causal_id}",
                ),
                peer_id="plugin",
            )

            self.assertEqual(response.status, "accepted")
            self.assertEqual(
                tuple(item.canonical_name for item in response.meta.turn_result.skill_disclosures),
                ("health-steward", skill_name),
            )
            self.assertIs(type(executor.contexts[skill_name]), context_type)
            if mode == "settings":
                settings_context = executor.contexts[skill_name]
                self.assertFalse(settings_context.current_settings_available)
            elif mode == "inquiry":
                inquiry_context = executor.contexts[skill_name]
                self.assertEqual(inquiry_context.current_topic_views, ())
                self.assertEqual(inquiry_context.direct_evidence_cards, ())
                self.assertEqual(inquiry_context.related_task_acceptance_refs, ())
                self.assertFalse(inquiry_context.task_acceptance_available)
                self.assertFalse(inquiry_context.current_control_state_available)
                self.assertIsNone(inquiry_context.same_gap_already_asked)
                self.assertEqual(
                    set(inquiry_context.missing_requirements),
                    {
                        "topic-scope-unavailable",
                        "task-acceptance-unavailable",
                        "current-control-state-unavailable",
                        "same-gap-state-unavailable",
                    },
                )
            elif mode == "literature":
                literature_context = executor.contexts[skill_name]
                self.assertEqual(
                    literature_context.topic_refs,
                    ("physical-function-and-experience/sleep",),
                )
                self.assertEqual(
                    literature_context.existing_qualified_knowledge_cards,
                    (),
                )
            self.assertIn(reply_text, response.meta.turn_result.owner_reply)
            self.assertEqual(response.meta.turn_result.evidence_ids, ())
            self.assertEqual(response.meta.turn_result.portrait_topics, ())

        state = self.plugin.daily_state(peer_id="plugin")
        self.assertEqual(state.evidence_cards, ())
        self.assertEqual(state.portrait_topics, ())
        self.assertEqual(len(state.processed_source_causal_ids), 3)
        self.assertFalse(self.plugin.outbound_effects_allowed())

    def test_missing_settings_or_inquiry_context_cannot_be_promoted_to_a_candidate(self) -> None:
        for index, mode in enumerate(("settings", "inquiry"), start=1):
            executor = BoundaryResponsibilityExecutor(
                mode,
                honor_missing_context=False,
            )
            runtime = DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda index=index: datetime(
                    2026,
                    8,
                    24,
                    2,
                    20 + index,
                    tzinfo=timezone.utc,
                ),
            )
            source = materialize_source(
                self.message(
                    CountingBody("请处理这个健康请求"),
                    causal_id=f"ticket112-forged-{mode}-context",
                    generation=self.head.read().head.generation,
                    requested_capability="health-steward",
                    message_id=f"wx-ticket112-forged-{mode}-context",
                    protocol_timestamp=f"2026-08-24T10:3{index}:00+08:00",
                    received_at=f"2026-08-24T10:3{index}:01+08:00",
                    native_cursor=f"cursor-ticket112-forged-{mode}-context",
                )
            )

            stage = runtime.execute(source, self.core.daily_state())
            post_stage_state = self.core.daily_state().apply_evidence_stage(stage)
            with self.assertRaises(AuthorityValidationError):
                runtime.complete(source, post_stage_state, stage)

    def test_literature_context_contains_only_qualified_cards_in_the_explicit_topic_scope(self) -> None:
        sleep_topic = "physical-function-and-experience/sleep"
        heart_topic = "clinical-and-safety/symptoms-and-health-problems"

        def knowledge_card(topic_ref: str, content: str, publisher: str) -> EvidenceCard:
            claim = AtomicEvidenceClaim(
                content=content,
                evidence_type="authoritative-knowledge",
                source_kind="publisher-material",
                occurred_at="2026-08-20",
                applicable_period="2026-08-release",
                purpose="qualified-knowledge",
                uncertainty="适用性仍需按主人事实判断",
                limitations=("不证明主人个人事实",),
                proves=(content,),
                does_not_prove=("主人个人健康状态",),
                topic_refs=(topic_ref,),
                specific_fields=AuthoritativeKnowledgeFields(
                    publisher=publisher,
                    material_version="2026-08-v1",
                    applicable_population="一般成年人",
                    validity_boundary="仅作一般知识",
                ),
                series_key=EvidenceSeriesKey(
                    "authoritative-knowledge",
                    "general-health-knowledge",
                    AuthoritativeKnowledgeProfile(
                        publisher=publisher,
                        applicable_population="一般成年人",
                        validity_boundary="仅作一般知识",
                        source_nature="publisher-material",
                    ),
                    "release",
                ),
                time_certainty="known",
            )
            return EvidenceCard.from_claim(
                f"source:{publisher}",
                claim,
                recorded_at="2026-08-24T02:30:00Z",
            )

        sleep_card = knowledge_card(
            sleep_topic,
            "睡眠资料中的一般知识",
            "approved-library",
        )
        disallowed_sleep_card = knowledge_card(
            sleep_topic,
            "未授权来源中的睡眠知识",
            "unapproved-library",
        )
        heart_card = knowledge_card(
            heart_topic,
            "一般症状资料中的知识",
            "approved-library",
        )
        executor = BoundaryResponsibilityExecutor("literature")
        runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=executor,
            clock=lambda: datetime(2026, 8, 24, 2, 31, tzinfo=timezone.utc),
        )
        source = materialize_source(
            self.message(
                CountingBody("请查找与睡眠相关的合格资料"),
                causal_id="ticket112-purpose-scoped-literature",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-purpose-scoped-literature",
                protocol_timestamp="2026-08-24T10:35:00+08:00",
                received_at="2026-08-24T10:35:01+08:00",
                native_cursor="cursor-ticket112-purpose-scoped-literature",
            )
        )

        initial_state = DailyHealthState(
            (sleep_card, disallowed_sleep_card, heart_card),
            (),
            (),
            (),
        )
        stage = runtime.execute(
            source,
            initial_state,
        )
        runtime.complete(source, initial_state.apply_evidence_stage(stage), stage)

        context = executor.contexts["health-literature"]
        self.assertEqual(context.topic_refs, (sleep_topic,))
        self.assertEqual(
            context.existing_qualified_knowledge_cards,
            (sleep_card,),
        )

    def test_portrait_projection_requires_and_round_trips_the_trend_period(self) -> None:
        evidence_previews = tuple(
            EvidenceTypePreview(evidence_type, (), 0)
            for evidence_type in (
                "personal-health",
                "authoritative-knowledge",
                "task-process",
            )
        )
        common = {
            "topic_ref": "physical-function-and-experience/sleep",
            "current_status": "known",
            "current_understandings": ("过去一周有多次睡眠观察",),
            "current_understanding_applicable_periods": (
                "2026-08-18/2026-08-24",
            ),
            "open_judgments": (),
            "key_unknowns": (),
            "related_task_preview_ids": (),
            "additional_task_count": 0,
            "evidence_previews": evidence_previews,
        }
        with self.assertRaises(AuthorityValidationError):
            PortraitTopicProjection(
                trend="过去一周变差",
                trend_period=None,
                **common,
            )

        projection = PortraitTopicProjection(
            trend="过去一周变差",
            trend_period="2026-08-18/2026-08-24",
            **common,
        )

        self.assertEqual(
            PortraitTopicProjection.from_storage(projection.to_storage()),
            projection,
        )

    def test_steward_plan_requires_explicit_portrait_and_knowledge_topic_scopes(self) -> None:
        with self.assertRaises(AuthorityValidationError):
            StewardPlan(
                purpose="portrait-without-topic-scope",
                selected_skills=("health-portrait",),
                atomic_claims=(),
            )
        with self.assertRaises(AuthorityValidationError):
            StewardPlan(
                purpose="literature-without-topic-scope",
                selected_skills=("health-literature",),
                atomic_claims=(),
                knowledge_gap="需要睡眠资料",
            )
        with self.assertRaises(AuthorityValidationError):
            StewardPlan(
                purpose="unused-portrait-topic-scope",
                selected_skills=(),
                atomic_claims=(),
                portrait_topic_refs=(
                    "physical-function-and-experience/sleep",
                ),
            )

        plan = StewardPlan(
            purpose="purpose-scoped-literature",
            selected_skills=("health-literature",),
            atomic_claims=(),
            knowledge_gap="需要睡眠资料",
            knowledge_topic_refs=(
                "physical-function-and-experience/sleep",
            ),
            allowed_knowledge_sources=("approved-library",),
            recipient_boundary="configured-first-hop-only",
        )
        self.assertEqual(StewardPlan.from_storage(plan.to_storage()), plan)

    def test_settings_and_inquiry_gaps_must_name_the_missing_requirement(self) -> None:
        with self.assertRaises(AuthorityValidationError):
            SettingsDecision("gap", None, None)
        with self.assertRaises(AuthorityValidationError):
            OwnerInquiryDecision("gap", None, None)

    def test_evidence_types_relations_and_portrait_display_budgets_are_strict(self) -> None:
        common = {
            "occurred_at": "2026-08-23",
            "applicable_period": "2026-08-23",
            "purpose": "typed-evidence-check",
            "uncertainty": "仍有边界",
            "limitations": ("不能跨类型证明",),
            "does_not_prove": ("另一类证据的主张",),
            "topic_refs": ("physical-function-and-experience/sleep",),
            "time_certainty": "known",
        }
        claims = (
            AtomicEvidenceClaim(
                content="主人自述睡眠体验不佳",
                evidence_type="personal-health",
                source_kind="owner-statement",
                proves=("主人自述睡眠体验不佳",),
                specific_fields=PersonalHealthFields("owner-statement"),
                series_key=EvidenceSeriesKey(
                    "personal-health",
                    "subjective-sleep-experience",
                    PersonalEvidenceProfile("owner-statement"),
                    "single-night",
                ),
                **common,
            ),
            AtomicEvidenceClaim(
                content="某合格资料中的一般睡眠知识",
                evidence_type="authoritative-knowledge",
                source_kind="publisher-material",
                proves=("某合格资料中的一般睡眠知识",),
                specific_fields=AuthoritativeKnowledgeFields(
                    publisher="合格发布者",
                    material_version="2026-08-v1",
                    applicable_population="一般成年人",
                    validity_boundary="仅作一般知识，不证明主人事实",
                ),
                series_key=EvidenceSeriesKey(
                    "authoritative-knowledge",
                    "general-sleep-knowledge",
                    AuthoritativeKnowledgeProfile(
                        publisher="合格发布者",
                        applicable_population="一般成年人",
                        validity_boundary="仅作一般知识，不证明主人事实",
                        source_nature="publisher-material",
                    ),
                    "release",
                ),
                **common,
            ),
            AtomicEvidenceClaim(
                content="一次健康任务已进入执行阶段",
                evidence_type="task-process",
                source_kind="task-ledger",
                proves=("一次健康任务已进入执行阶段",),
                specific_fields=TaskProcessFields(
                    task_id="health-task:test",
                    actual_stage="executing",
                    process_fact_kind="stage",
                    process_fact_ref="task-event:test",
                ),
                series_key=EvidenceSeriesKey(
                    "task-process",
                    "task-stage-event",
                    TaskProcessProfile(
                        task_id="health-task:test",
                        process_fact_kind="stage",
                        ledger_ref="task-ledger:health-task:test",
                        source_nature="task-ledger",
                    ),
                    "task-event",
                ),
                **common,
            ),
        )
        self.assertEqual(
            tuple(claim.evidence_type for claim in claims),
            ("personal-health", "authoritative-knowledge", "task-process"),
        )
        round_tripped_claims = tuple(
            AtomicEvidenceClaim.from_storage(claim.to_storage())
            for claim in claims
        )
        self.assertEqual(round_tripped_claims, claims)
        self.assertEqual(
            tuple(
                type(claim.series_key.comparability_profile)
                for claim in round_tripped_claims
            ),
            (
                PersonalEvidenceProfile,
                AuthoritativeKnowledgeProfile,
                TaskProcessProfile,
            ),
        )
        evidence_id = "evidence:test"
        relations = (
            EvidenceRelation(
                evidence_id,
                "topic",
                "relevant",
                "portrait-topic",
                "physical-function-and-experience/sleep",
            ),
            EvidenceRelation(
                evidence_id,
                "proof",
                "qualifies",
                "portrait-item",
                "portrait-understanding:test",
            ),
            EvidenceRelation(
                evidence_id,
                "use",
                "used-by",
                "managed-result",
                "health-task:test",
            ),
            EvidenceRelation(
                evidence_id,
                "history",
                "corrects",
                "evidence-card",
                "evidence:older",
            ),
        )
        self.assertEqual(
            tuple(relation.relation_class for relation in relations),
            ("topic", "proof", "use", "history"),
        )
        with self.assertRaises(AuthorityValidationError):
            EvidenceRelation(
                evidence_id,
                "proof",
                "summarizes",
                "evidence-card",
                "evidence:older",
            )
        with self.assertRaises(AuthorityValidationError):
            PortraitDecision.update(
                topic_ref="physical-function-and-experience/sleep",
                current_understandings=("一", "二", "三", "四"),
                open_judgments=(),
                key_unknowns=(),
                proof_links=(),
            )
        with self.assertRaises(AuthorityValidationError):
            PortraitDecision.update(
                topic_ref="physical-function-and-experience/sleep",
                current_understandings=("睡" * 61,),
                open_judgments=(),
                key_unknowns=(),
                proof_links=(),
            )
        with self.assertRaises(AuthorityValidationError):
            PortraitDecision.update(
                topic_ref="physical-function-and-experience/sleep",
                current_understandings=("一次近期观察",),
                open_judgments=(),
                key_unknowns=(),
                proof_links=(
                    PortraitProofLink.form(
                        evidence_id=evidence_id,
                        relation_kind="supports",
                        topic_ref="physical-function-and-experience/sleep",
                        item_kind="current-understanding",
                        item_text="一次近期观察",
                        applicable_period="2026-08-23",
                    ),
                    PortraitProofLink.form(
                        evidence_id=evidence_id,
                        relation_kind="supports",
                        topic_ref="physical-function-and-experience/sleep",
                        item_kind="trend",
                        item_text="长期变差",
                        trend_period="近期",
                    ),
                ),
                trend="长期变差",
                trend_period="近期",
            )
        self.assertEqual(len(self.plugin.daily_state(peer_id="plugin").projection.unknown_domains), 6)

        with self.assertRaises(AuthorityValidationError):
            replace(
                claims[1],
                evidence_type="personal-health",
                series_key=replace(
                    claims[1].series_key,
                    evidence_type="personal-health",
                ),
            )
        with self.assertRaises(AuthorityValidationError):
            PersonalHealthFields(
                "measurement",
                measurement_value="72.4",
                measurement_unit=None,
                measurement_method="calibrated-scale",
            )

        personal_profile = claims[0].series_key.comparability_profile
        knowledge_profile = claims[1].series_key.comparability_profile
        task_profile = claims[2].series_key.comparability_profile
        self.assertIs(type(personal_profile), PersonalEvidenceProfile)
        self.assertIs(type(knowledge_profile), AuthoritativeKnowledgeProfile)
        self.assertIs(type(task_profile), TaskProcessProfile)

        with self.assertRaises(AuthorityValidationError):
            replace(
                claims[0],
                series_key=replace(
                    claims[0].series_key,
                    comparability_profile=AuthoritativeKnowledgeProfile(
                        publisher="合格发布者",
                        applicable_population="一般成年人",
                        validity_boundary="仅作一般知识，不证明主人事实",
                        source_nature="publisher-material",
                    ),
                ),
            )
        for mismatched_profile in (
            PersonalEvidenceProfile("reported-clinician-conclusion"),
            replace(knowledge_profile, publisher="另一个发布者"),
            replace(knowledge_profile, source_nature="unverified-web-page"),
            replace(task_profile, task_id="health-task:other"),
            replace(task_profile, process_fact_kind="delivery"),
            replace(task_profile, source_nature="owner-chat"),
        ):
            claim = (
                claims[0]
                if type(mismatched_profile) is PersonalEvidenceProfile
                else claims[1]
                if type(mismatched_profile) is AuthoritativeKnowledgeProfile
                else claims[2]
            )
            with self.subTest(mismatched_profile=mismatched_profile):
                with self.assertRaises(AuthorityValidationError):
                    replace(
                        claim,
                        series_key=replace(
                            claim.series_key,
                            comparability_profile=mismatched_profile,
                        ),
                    )

        measurement_profile = PersonalEvidenceProfile(
            "measurement",
            measurement_method="calibrated-scale",
            measurement_unit="kg",
        )
        measurement_claim = AtomicEvidenceClaim(
            content="校准体重秤测得体重72.4千克",
            evidence_type="personal-health",
            source_kind="measurement",
            occurred_at="2026-08-23T08:00:00+08:00",
            applicable_period="2026-08-23-morning",
            purpose="typed-evidence-check",
            uncertainty="单次测量仍有仪器误差",
            limitations=("单次测量不证明长期趋势",),
            proves=("校准体重秤测得体重72.4千克",),
            does_not_prove=("长期体重趋势",),
            topic_refs=("physical-function-and-experience/digestive-and-metabolic",),
            specific_fields=PersonalHealthFields(
                "measurement",
                measurement_value="72.4",
                measurement_unit="kg",
                measurement_method="calibrated-scale",
            ),
            series_key=EvidenceSeriesKey(
                "personal-health",
                "body-mass",
                measurement_profile,
                "point-measurement",
                unit="kg",
            ),
            time_certainty="known",
        )
        self.assertEqual(
            AtomicEvidenceClaim.from_storage(measurement_claim.to_storage()),
            measurement_claim,
        )
        with self.assertRaises(AuthorityValidationError):
            replace(
                measurement_claim,
                specific_fields=replace(
                    measurement_claim.specific_fields,
                    measurement_method="uncalibrated-estimate",
                ),
            )
        with self.assertRaises(AuthorityValidationError):
            replace(measurement_claim.series_key, unit="lb")

        tampered_claim = claims[0].to_storage()
        tampered_series = tampered_claim["series_key"]
        self.assertIs(type(tampered_series), dict)
        tampered_profile = tampered_series["comparability_profile"]
        self.assertIs(type(tampered_profile), dict)
        tampered_fields = tampered_profile["fields"]
        self.assertIs(type(tampered_fields), dict)
        tampered_fields["observation_basis"] = "reported-clinician-conclusion"
        with self.assertRaises(AuthorityValidationError):
            AtomicEvidenceClaim.from_storage(tampered_claim)

    def test_portrait_proof_links_are_item_specific_and_never_cross_joined(self) -> None:
        topic_ref = "physical-function-and-experience/sleep"
        first = "最近一晚主观睡眠体验不佳"
        second = "睡眠时长仍未知"
        links = (
            PortraitProofLink.form(
                evidence_id="evidence:first",
                relation_kind="supports",
                topic_ref=topic_ref,
                item_kind="current-understanding",
                item_text=first,
                applicable_period="2026-08-23-night",
            ),
            PortraitProofLink.form(
                evidence_id="evidence:second",
                relation_kind="qualifies",
                topic_ref=topic_ref,
                item_kind="current-understanding",
                item_text=second,
                applicable_period="2026-08-24-day",
            ),
        )
        decision = PortraitDecision.update(
            topic_ref=topic_ref,
            current_understandings=(first, second),
            open_judgments=(),
            key_unknowns=(),
            proof_links=links,
        )
        portrait = PortraitTopic.from_decision(decision)

        proof_relations = tuple(
            relation
            for relation in portrait.evidence_relations
            if relation.relation_class == "proof"
        )
        self.assertEqual(len(proof_relations), 2)
        self.assertEqual(
            tuple(relation.evidence_id for relation in proof_relations),
            ("evidence:first", "evidence:second"),
        )
        self.assertEqual(
            tuple(relation.relation_kind for relation in proof_relations),
            ("supports", "qualifies"),
        )
        self.assertNotEqual(proof_relations[0].target_ref, proof_relations[1].target_ref)

        with self.assertRaises(AuthorityValidationError):
            PortraitDecision.update(
                topic_ref=topic_ref,
                current_understandings=(first, second),
                open_judgments=(),
                key_unknowns=(),
                proof_links=(links[0],),
            )

        degraded = PortraitDecision.degrade(
            topic_ref=topic_ref,
            current_understandings=(first,),
            open_judgments=("仍需结合后续观察",),
            key_unknowns=(),
            proof_links=(
                PortraitProofLink.form(
                    evidence_id="evidence:counter",
                    relation_kind="qualifies",
                    topic_ref=topic_ref,
                    item_kind="open-judgment",
                    item_text="仍需结合后续观察",
                ),
                PortraitProofLink.form(
                    evidence_id="evidence:counter",
                    relation_kind="opposes",
                    topic_ref=topic_ref,
                    item_kind="current-understanding",
                    item_text=first,
                    applicable_period="2026-08-23-night",
                ),
            ),
            reason="当前依据只能维持较弱结论",
        )
        self.assertEqual(
            PortraitTopic.from_decision(degraded).evidence_relations[-1].relation_kind,
            "opposes",
        )

    def test_series_window_keeps_latest_five_plus_protected_and_previews_three(self) -> None:
        series_key = EvidenceSeriesKey(
            "personal-health",
            "subjective-sleep-experience",
            PersonalEvidenceProfile("owner-statement"),
            "single-night",
        )
        cards = tuple(
            EvidenceCard.from_claim(
                f"ticket112-series-{index}",
                AtomicEvidenceClaim(
                    content=f"主人第{index}晚自述睡眠体验不佳",
                    evidence_type="personal-health",
                    source_kind="owner-statement",
                    occurred_at=f"2026-08-{index:02d}",
                    applicable_period=f"2026-08-{index:02d}-night",
                    purpose="sleep-series-window",
                    uncertainty="主人主观体验",
                    limitations=("单次陈述不证明趋势",),
                    proves=(f"主人第{index}晚自述睡眠体验不佳",),
                    does_not_prove=("长期趋势",),
                    topic_refs=("physical-function-and-experience/sleep",),
                    specific_fields=PersonalHealthFields("owner-statement"),
                    series_key=series_key,
                    time_certainty="known",
                ),
                recorded_at=f"2026-08-{index:02d}T20:00:00+08:00",
            )
            for index in range(1, 10)
        )
        relations = tuple(
            EvidenceRelation(
                card.evidence_id,
                "topic",
                "relevant",
                "portrait-topic",
                "physical-function-and-experience/sleep",
            )
            for card in cards
        ) + (
            EvidenceRelation(
                cards[0].evidence_id,
                "use",
                "used-by",
                "managed-result",
                "active-task:protected-oldest",
            ),
        )

        projection = DailyHealthState(cards, (), relations, ()).projection

        self.assertEqual(len(projection.series_windows), 1)
        window = projection.series_windows[0]
        self.assertIs(type(window), EvidenceSeriesWindow)
        self.assertEqual(window.protected_detail_ids, (cards[0].evidence_id,))
        self.assertEqual(
            window.recent_detail_ids,
            tuple(card.evidence_id for card in reversed(cards[4:])),
        )
        self.assertEqual(
            window.window_outside_detail_ids,
            tuple(card.evidence_id for card in reversed(cards[1:4])),
        )
        self.assertEqual(
            window.summary_threshold_detail_ids,
            window.window_outside_detail_ids,
        )
        topic_view = next(
            item
            for item in projection.topic_views
            if item.topic_ref == "physical-function-and-experience/sleep"
        )
        preview = next(
            item
            for item in topic_view.evidence_previews
            if item.evidence_type == "personal-health"
        )
        self.assertIs(type(preview), EvidenceTypePreview)
        self.assertEqual(len(preview.preview_ids), 3)
        self.assertEqual(preview.additional_count, 6)

    def test_history_summary_retires_three_old_details_only_after_atomic_core_commit(self) -> None:
        series_key = EvidenceSeriesKey(
            "personal-health",
            "subjective-sleep-experience",
            PersonalEvidenceProfile("owner-statement"),
            "single-night",
        )
        executor = SeriesCompactionExecutor()
        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda: datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc),
            ),
        )
        self.route_classification = "health"

        def detail_claim(index: int) -> AtomicEvidenceClaim:
            content = f"主人第{index}晚自述睡眠体验不佳"
            return AtomicEvidenceClaim(
                content=content,
                evidence_type="personal-health",
                source_kind="owner-statement",
                occurred_at=f"2026-08-{index:02d}",
                applicable_period=f"2026-08-{index:02d}-night",
                purpose="sleep-series-history",
                uncertainty="主人主观体验",
                limitations=("单次陈述不证明趋势",),
                proves=(content,),
                does_not_prove=("长期趋势",),
                topic_refs=("physical-function-and-experience/sleep",),
                specific_fields=PersonalHealthFields("owner-statement"),
                series_key=series_key,
                time_certainty="known",
            )

        detail_messages: dict[str, RawWeixinMessage] = {}
        for index in range(1, 9):
            executor.claim = detail_claim(index)
            executor.retire_evidence_ids = ()
            causal_id = f"ticket112-history-detail-{index}"
            raw_message = self.message(
                    CountingBody(executor.claim.content),
                    causal_id=causal_id,
                    generation=self.head.read().head.generation,
                    requested_capability="health-steward",
                    message_id=f"wx-{causal_id}",
                    protocol_timestamp=f"2026-08-{index:02d}T20:00:00+08:00",
                    received_at=f"2026-08-{index:02d}T20:00:01+08:00",
                    native_cursor=f"cursor-{causal_id}",
                )
            detail_messages[causal_id] = raw_message
            response = plugin.receive_weixin(
                raw_message,
                peer_id="plugin",
            )
            self.assertEqual(response.status, "accepted")

        before = plugin.daily_state(peer_id="plugin")
        self.assertEqual(len(before.evidence_cards), 8)
        window = before.projection.series_windows[0]
        self.assertEqual(len(window.recent_detail_ids), 5)
        self.assertEqual(len(window.summary_threshold_detail_ids), 3)

        def summary_claim(
            targets: tuple[str, ...],
            coverage_start: str,
            coverage_end: str,
        ) -> AtomicEvidenceClaim:
            fields = EvidenceSummaryFields(
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                total_original_detail_count=3,
                pattern="覆盖期内三次主人自述睡眠体验不佳",
                exceptions=(),
                unknowns=("睡眠时长仍未知",),
                cumulative_uncertainty="仅为主人主观体验，未形成医学趋势",
                method_or_source_changes=(),
                lost_detail_scope="三次逐夜表述已压缩且不可恢复",
                generation=1,
                absorbed_records_digest=EvidenceCompaction.digest_for(targets),
                absorbed_record_count=3,
                predecessor_batch_digest=None,
            )
            return AtomicEvidenceClaim(
                content="覆盖期内主人三次自述睡眠体验不佳",
                evidence_type="personal-health",
                source_kind="historical-summary",
                occurred_at=coverage_end,
                applicable_period=f"{coverage_start}/{coverage_end}",
                purpose="sleep-series-history",
                uncertainty=fields.cumulative_uncertainty,
                limitations=(fields.lost_detail_scope,),
                proves=("覆盖期内主人三次自述睡眠体验不佳",),
                does_not_prove=("长期趋势", "失眠诊断"),
                topic_refs=("physical-function-and-experience/sleep",),
                specific_fields=PersonalHealthFields("historical-summary"),
                series_key=series_key,
                time_certainty="known",
                summary_fields=fields,
            )

        invalid_targets = (
            *window.summary_threshold_detail_ids[:2],
            window.recent_detail_ids[0],
        )
        executor.retire_evidence_ids = invalid_targets
        executor.claim = summary_claim(
            invalid_targets,
            "2026-08-02",
            "2026-08-08",
        )
        invalid = plugin.receive_weixin(
            self.message(
                CountingBody("请压缩不合格窗口"),
                causal_id="ticket112-history-invalid",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-history-invalid",
                protocol_timestamp="2026-08-24T11:00:00+08:00",
                received_at="2026-08-24T11:00:01+08:00",
                native_cursor="cursor-ticket112-history-invalid",
            ),
            peer_id="plugin",
        )
        self.assertEqual(invalid.status, "rejected")
        self.assertEqual(len(plugin.daily_state(peer_id="plugin").evidence_cards), 8)

        valid_targets = window.summary_threshold_detail_ids
        retired_terminal_expectations = tuple(
            (card.source_causal_id, card.content)
            for card in before.evidence_cards
            if card.evidence_id in valid_targets
        )
        executor.retire_evidence_ids = valid_targets
        executor.claim = summary_claim(valid_targets, "2026-08-01", "2026-08-03")
        self.assertEqual(
            executor.claim.series_key.comparability_profile,
            series_key.comparability_profile,
        )
        self.assertEqual(
            AtomicEvidenceClaim.from_storage(
                executor.claim.to_storage()
            ).series_key.comparability_profile,
            series_key.comparability_profile,
        )
        valid = plugin.receive_weixin(
            self.message(
                CountingBody("形成合格历史摘要"),
                causal_id="ticket112-history-valid",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-history-valid",
                protocol_timestamp="2026-08-24T11:01:00+08:00",
                received_at="2026-08-24T11:01:01+08:00",
                native_cursor="cursor-ticket112-history-valid",
            ),
            peer_id="plugin",
        )

        self.assertEqual(valid.status, "accepted", valid)
        after = plugin.daily_state(peer_id="plugin")
        self.assertEqual(len(after.evidence_cards), 6)
        self.assertTrue(set(valid_targets).isdisjoint(
            card.evidence_id for card in after.evidence_cards
        ))
        summary = next(card for card in after.evidence_cards if card.card_form == "summary")
        self.assertEqual(summary.summary_fields.total_original_detail_count, 3)
        relation = next(
            item
            for item in after.evidence_relations
            if item.relation_kind == "summarizes"
        )
        self.assertEqual(relation.target_ref, EvidenceCompaction.digest_for(valid_targets))
        final_window = after.projection.series_windows[0]
        self.assertEqual(len(final_window.recent_detail_ids), 5)
        self.assertEqual(final_window.window_outside_detail_ids, ())
        self.assertEqual(final_window.summary_ids, (summary.evidence_id,))
        for source_causal_id, retired_literal in retired_terminal_expectations:
            retired_turn = self.store.daily_turn(source_causal_id)
            self.assertIsNotNone(retired_turn)
            self.assertIsNone(retired_turn.draft)
            self.assertIsNone(retired_turn.result)
            retired_row = self.store._execute(
                "SELECT record_id, nonce, ciphertext FROM daily_turns_v1 "
                "WHERE source_causal_id = ?",
                (source_causal_id,),
            ).fetchone()
            retired_plaintext = self.store._open(
                f"daily-turn:{source_causal_id}:{retired_row[0]}:finalized",
                retired_row[1],
                retired_row[2],
            )
            self.assertNotIn(retired_literal, repr(retired_plaintext))
            self.assertEqual(
                set(retired_plaintext),
                {"terminal", "result"},
            )
        replay_source, replay_literal = retired_terminal_expectations[0]
        redacted_replay = plugin.receive_weixin(
            replace(
                detail_messages[replay_source],
                body=CountingBody(replay_literal),
            ),
            peer_id="plugin",
        )
        self.assertEqual(redacted_replay.status, "accepted")
        self.assertEqual(
            redacted_replay.reason_code,
            "daily-turn-result-redacted",
        )
        self.assertNotIsInstance(redacted_replay.meta, DailyTurnMeta)

        executor.claim = detail_claim(9)
        executor.retire_evidence_ids = ()
        ninth = plugin.receive_weixin(
            self.message(
                CountingBody(executor.claim.content),
                causal_id="ticket112-history-detail-9",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-history-detail-9",
                protocol_timestamp="2026-08-09T20:00:00+08:00",
                received_at="2026-08-09T20:00:01+08:00",
                native_cursor="cursor-ticket112-history-detail-9",
            ),
            peer_id="plugin",
        )
        self.assertEqual(ninth.status, "accepted")
        rolling_before = plugin.daily_state(peer_id="plugin")
        rolling_window = rolling_before.projection.series_windows[0]
        self.assertEqual(len(rolling_window.window_outside_detail_ids), 1)
        rolling_targets = (
            summary.evidence_id,
            rolling_window.window_outside_detail_ids[0],
        )
        predecessor_digest = EvidenceCompaction.predecessor_digest(
            (summary.evidence_id,)
        )
        rolling_fields = EvidenceSummaryFields(
            coverage_start="2026-08-01",
            coverage_end="2026-08-04",
            total_original_detail_count=4,
            pattern="覆盖期内四次主人自述睡眠体验不佳",
            exceptions=(),
            unknowns=("睡眠时长仍未知",),
            cumulative_uncertainty="仅为主人主观体验，滚动后不增加确定性",
            method_or_source_changes=(),
            lost_detail_scope="四次逐夜表述已压缩且不可恢复",
            generation=2,
            absorbed_records_digest=EvidenceCompaction.digest_for(rolling_targets),
            absorbed_record_count=2,
            predecessor_batch_digest=predecessor_digest,
        )
        executor.retire_evidence_ids = rolling_targets
        executor.claim = AtomicEvidenceClaim(
            content="覆盖期内主人四次自述睡眠体验不佳",
            evidence_type="personal-health",
            source_kind="historical-summary",
            occurred_at="2026-08-04",
            applicable_period="2026-08-01/2026-08-04",
            purpose="sleep-series-history",
            uncertainty=rolling_fields.cumulative_uncertainty,
            limitations=(rolling_fields.lost_detail_scope,),
            proves=("覆盖期内主人四次自述睡眠体验不佳",),
            does_not_prove=("长期趋势", "失眠诊断"),
            topic_refs=("physical-function-and-experience/sleep",),
            specific_fields=PersonalHealthFields("historical-summary"),
            series_key=series_key,
            time_certainty="known",
            summary_fields=rolling_fields,
        )
        rolling = plugin.receive_weixin(
            self.message(
                CountingBody("滚动形成后继摘要"),
                causal_id="ticket112-history-rolling",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-history-rolling",
                protocol_timestamp="2026-08-24T11:02:00+08:00",
                received_at="2026-08-24T11:02:01+08:00",
                native_cursor="cursor-ticket112-history-rolling",
            ),
            peer_id="plugin",
        )
        self.assertEqual(rolling.status, "accepted", rolling)
        rolling_after = plugin.daily_state(peer_id="plugin")
        self.assertTrue(set(rolling_targets).isdisjoint(
            card.evidence_id for card in rolling_after.evidence_cards
        ))
        successor = next(
            card for card in rolling_after.evidence_cards if card.card_form == "summary"
        )
        self.assertEqual(successor.summary_fields.generation, 2)
        self.assertEqual(successor.summary_fields.total_original_detail_count, 4)
        predecessor_turn = self.store.daily_turn("ticket112-history-valid")
        self.assertIsNotNone(predecessor_turn)
        self.assertIsNone(predecessor_turn.draft)
        self.assertIsNone(predecessor_turn.result)
        predecessor_row = self.store._execute(
            "SELECT record_id, nonce, ciphertext FROM daily_turns_v1 "
            "WHERE source_causal_id = ?",
            ("ticket112-history-valid",),
        ).fetchone()
        predecessor_plaintext = self.store._open(
            "daily-turn:ticket112-history-valid:"
            f"{predecessor_row[0]}:finalized",
            predecessor_row[1],
            predecessor_row[2],
        )
        self.assertNotIn(summary.content, repr(predecessor_plaintext))
        self.assertTrue(self.store.verify_integrity(self.store.finalized_authority()))

    def test_one_turn_supports_multiple_atomic_cards_and_one_card_can_link_two_topics(self) -> None:
        sleep_function = "physical-function-and-experience/sleep"
        sleep_routine = "health-behaviour-and-exposure/sleep-routine"
        claims = (
            AtomicEvidenceClaim(
                content="主人自述昨晚睡眠时长为4小时",
                evidence_type="personal-health",
                source_kind="owner-statement",
                occurred_at="2026-08-23",
                applicable_period="2026-08-23-night",
                purpose="record-sleep-observations",
                uncertainty="主人自述，未独立测量",
                limitations=("不证明原因",),
                proves=("主人自述昨晚睡眠时长为4小时",),
                does_not_prove=("睡眠不足原因", "长期趋势"),
                topic_refs=(sleep_function, sleep_routine),
                specific_fields=PersonalHealthFields("owner-statement"),
                series_key=EvidenceSeriesKey(
                    "personal-health",
                    "reported-sleep-duration",
                    PersonalEvidenceProfile("owner-statement"),
                    "single-night",
                ),
                time_certainty="known",
            ),
            AtomicEvidenceClaim(
                content="主人自述今天白天困倦",
                evidence_type="personal-health",
                source_kind="owner-statement",
                occurred_at="2026-08-24",
                applicable_period="2026-08-24-day",
                purpose="record-sleep-observations",
                uncertainty="主人主观体验",
                limitations=("不证明由睡眠不足导致",),
                proves=("主人自述今天白天困倦",),
                does_not_prove=("困倦原因", "诊断"),
                topic_refs=(sleep_function,),
                specific_fields=PersonalHealthFields("owner-statement"),
                series_key=EvidenceSeriesKey(
                    "personal-health",
                    "daytime-sleepiness",
                    PersonalEvidenceProfile("owner-statement"),
                    "single-day",
                ),
                time_certainty="known",
            ),
        )
        calls: list[str] = []

        def executor(skill_name: str, context: object) -> object:
            calls.append(skill_name)
            if skill_name == "health-steward":
                if type(context) is StewardResolutionContext:
                    return StewardResolution(
                        commit_evidence_ids=context.candidate_evidence_ids,
                        commit_portrait_topic_refs=context.candidate_portrait_topic_refs,
                        reply_atom_ids=tuple(atom.atom_id for atom in context.reply_atoms),
                    )
                return StewardPlan(
                    purpose="record-sleep-observations",
                    selected_skills=("health-evidence", "health-portrait"),
                    portrait_topic_refs=(sleep_function, sleep_routine),
                    atomic_claims=claims,
                )
            if skill_name == "health-evidence":
                return EvidenceDecision.admit(context.atomic_claim)
            if skill_name == "health-portrait":
                related_cards = tuple(
                    card
                    for card in (
                        *context.committed_related_cards,
                        *context.in_turn_evidence_candidates,
                    )
                    if card.evidence_id in context.evidence_ids
                )
                understandings = tuple(card.content for card in related_cards)
                return PortraitDecision.update(
                    topic_ref=context.topic_refs[0],
                    current_understandings=understandings,
                    open_judgments=(),
                    key_unknowns=("原因未知",),
                    proof_links=(
                        *(
                            PortraitProofLink.form(
                                evidence_id=card.evidence_id,
                                relation_kind="supports",
                                topic_ref=context.topic_refs[0],
                                item_kind="current-understanding",
                                item_text=card.content,
                                applicable_period=card.applicable_period,
                            )
                            for card in related_cards
                        ),
                        PortraitProofLink.form(
                            evidence_id=context.evidence_ids[0],
                            relation_kind="qualifies",
                            topic_ref=context.topic_refs[0],
                            item_kind="key-unknown",
                            item_text="原因未知",
                        ),
                    ),
                )
            raise AssertionError(skill_name)

        runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=executor,
            clock=lambda: datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc),
        )
        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=runtime,
        )
        self.route_classification = "health"
        response = plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚只睡了4小时，今天白天很困"),
                causal_id="ticket112-multi-claim",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-multi-claim",
                protocol_timestamp="2026-08-24T12:00:00+08:00",
                received_at="2026-08-24T12:00:01+08:00",
                native_cursor="cursor-ticket112-multi-claim",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "accepted", response)
        self.assertEqual(
            calls,
            [
                "health-steward",
                "health-evidence",
                "health-evidence",
                "health-portrait",
                "health-portrait",
                "health-steward",
            ],
        )
        self.assertEqual(
            tuple(
                item.canonical_name
                for item in response.meta.turn_result.skill_disclosures
            ),
            ("health-steward", "health-evidence", "health-portrait"),
        )
        state = plugin.daily_state(peer_id="plugin")
        self.assertEqual(len(state.evidence_cards), 2)
        self.assertEqual(len(state.portrait_topics), 2)
        first_card = next(card for card in state.evidence_cards if "4小时" in card.content)
        first_topics = {
            relation.target_ref
            for relation in state.evidence_relations
            if relation.evidence_id == first_card.evidence_id
            and relation.relation_class == "topic"
        }
        self.assertEqual(first_topics, {sleep_function, sleep_routine})
        status = self.core.daily_turn_status("ticket112-multi-claim")
        self.assertIsNone(status.draft)
        self.assertIsNotNone(status.terminal)
        self.assertEqual(
            tuple(skill_use.action for skill_use in status.terminal.skill_uses),
            (
                "plan",
                "evaluate-evidence",
                "evaluate-evidence",
                "maintain-portrait",
                "maintain-portrait",
                "resolve",
            ),
        )

    def test_noncandidate_evidence_and_literature_decisions_require_reasons(self) -> None:
        for status in ("reject", "clarify"):
            with self.assertRaises(AuthorityValidationError):
                EvidenceDecision(status, None, None)
        for status in ("no-qualified-material", "gap"):
            with self.assertRaises(AuthorityValidationError):
                LiteratureDecision(status, None, None)

    def test_same_type_correction_cannot_replace_an_unrelated_physical_dimension(self) -> None:
        sleep_topic = "physical-function-and-experience/sleep"
        vital_topic = "clinical-and-safety/tests-labs-and-vital-signs"
        sleep_claim = AtomicEvidenceClaim(
            content="主人自述昨晚睡眠体验不佳",
            evidence_type="personal-health",
            source_kind="owner-statement",
            occurred_at="2026-08-23",
            applicable_period="2026-08-23-night",
            purpose="correct-personal-evidence",
            uncertainty="主人主观体验",
            limitations=("不证明长期趋势",),
            proves=("主人自述昨晚睡眠体验不佳",),
            does_not_prove=("血压状态",),
            topic_refs=(sleep_topic,),
            specific_fields=PersonalHealthFields("owner-statement"),
            series_key=EvidenceSeriesKey(
                "personal-health",
                "subjective-sleep-experience",
                PersonalEvidenceProfile("owner-statement"),
                "single-night",
            ),
            time_certainty="known",
        )
        target = EvidenceCard.from_claim(
            "ticket112-unrelated-correction-target",
            sleep_claim,
            recorded_at="2026-08-24T01:00:00Z",
        )
        blood_pressure_claim = replace(
            sleep_claim,
            content="主人自述本次血压读数偏高",
            proves=("主人自述本次血压读数偏高",),
            does_not_prove=("睡眠体验",),
            topic_refs=(vital_topic,),
            series_key=EvidenceSeriesKey(
                "personal-health",
                "blood-pressure-observation",
                PersonalEvidenceProfile("owner-statement"),
                "single-observation",
            ),
        )
        request = EvidenceMaintenanceRequest(
            "correct",
            (target.evidence_id,),
            "主人要求纠正",
            "correct-personal-evidence",
            blood_pressure_claim,
        )

        def executor(skill_name, context):
            if skill_name == "health-steward":
                return StewardPlan(
                    purpose="correct-personal-evidence",
                    selected_skills=("health-evidence",),
                    atomic_claims=(),
                    evidence_maintenance_requests=(request,),
                )
            if skill_name == "health-evidence":
                return EvidenceDecision.correct(
                    context.atomic_claim,
                    request.target_evidence_ids,
                    reason=request.reason,
                )
            raise AssertionError(skill_name)

        runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=executor,
            clock=lambda: datetime(2026, 8, 24, 4, 5, tzinfo=timezone.utc),
        )
        source = materialize_source(
            self.message(
                CountingBody("请纠正这条个人证据"),
                causal_id="ticket112-unrelated-same-type-correction",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-unrelated-same-type-correction",
                protocol_timestamp="2026-08-24T12:05:00+08:00",
                received_at="2026-08-24T12:05:01+08:00",
                native_cursor="cursor-ticket112-unrelated-same-type-correction",
            )
        )

        with self.assertRaises(AuthorityValidationError):
            runtime.execute(source, DailyHealthState((target,), (), (), ()))

    def test_normal_evidence_context_reads_only_current_exact_series(self) -> None:
        topic_ref = "physical-function-and-experience/sleep"
        series_key = EvidenceSeriesKey(
            "personal-health",
            "subjective-sleep-experience",
            PersonalEvidenceProfile("owner-statement"),
            "single-night",
        )

        def claim(content: str, occurred_at: str, *, series=series_key):
            return AtomicEvidenceClaim(
                content=content,
                evidence_type="personal-health",
                source_kind="owner-statement",
                occurred_at=occurred_at,
                applicable_period=f"{occurred_at}-night",
                purpose="purpose-limited-evidence",
                uncertainty="主人主观体验",
                limitations=("单次陈述不证明趋势",),
                proves=(content,),
                does_not_prove=("长期趋势",),
                topic_refs=(topic_ref,),
                specific_fields=PersonalHealthFields("owner-statement"),
                series_key=series,
                time_certainty="known",
            )

        current = EvidenceCard.from_claim(
            "ticket112-context-current",
            claim("当前同序列睡眠观察", "2026-08-20"),
            recorded_at="2026-08-20T12:00:00Z",
        )
        inactive = EvidenceCard.from_claim(
            "ticket112-context-inactive",
            claim("已撤回同序列睡眠观察", "2026-08-19"),
            recorded_at="2026-08-19T12:00:00Z",
        )
        unrelated_series = EvidenceSeriesKey(
            "personal-health",
            "sleep-duration",
            PersonalEvidenceProfile("owner-statement"),
            "single-night",
        )
        unrelated = EvidenceCard.from_claim(
            "ticket112-context-unrelated",
            claim("同主题但不同物理量", "2026-08-18", series=unrelated_series),
            recorded_at="2026-08-18T12:00:00Z",
        )
        change = EvidenceApplicabilityChange(
            inactive.evidence_id,
            "withdrawn",
            "主人已撤回",
            None,
            "sha256:" + ("a" * 64),
            "2026-08-24T04:06:00+00:00",
        )
        withdraw_relation = EvidenceRelation(
            inactive.evidence_id,
            "history",
            "withdraws",
            "evidence-card",
            inactive.evidence_id,
        )
        state = DailyHealthState(
            (current, inactive, unrelated),
            (),
            (withdraw_relation,),
            (),
            (change,),
        )
        new_claim = claim("本轮新的同序列睡眠观察", "2026-08-23")
        contexts: list[EvidenceContext] = []

        def executor(skill_name, context):
            if skill_name == "health-steward":
                return StewardPlan(
                    purpose="purpose-limited-evidence",
                    selected_skills=("health-evidence",),
                    atomic_claims=(new_claim,),
                )
            if skill_name == "health-evidence":
                contexts.append(context)
                return EvidenceDecision.reject("本测试只核验上下文")
            raise AssertionError(skill_name)

        runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=executor,
            clock=lambda: datetime(2026, 8, 24, 4, 6, tzinfo=timezone.utc),
        )
        source = materialize_source(
            self.message(
                CountingBody("记录新的睡眠观察"),
                causal_id="ticket112-purpose-limited-evidence",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-purpose-limited-evidence",
                protocol_timestamp="2026-08-24T12:06:00+08:00",
                received_at="2026-08-24T12:06:01+08:00",
                native_cursor="cursor-ticket112-purpose-limited-evidence",
            )
        )

        runtime.execute(source, state)

        self.assertEqual(contexts[0].related_existing_cards, (current,))
        self.assertEqual(contexts[0].current_evidence_ids, (current.evidence_id,))
        self.assertEqual(contexts[0].related_relations, ())
        self.assertEqual(contexts[0].related_applicability_changes, ())
        self.assertIsNone(contexts[0].series_window)

    def test_portrait_context_uses_current_proofs_and_bounded_previews_not_whole_topic(self) -> None:
        topic_ref = "physical-function-and-experience/sleep"
        series_key = EvidenceSeriesKey(
            "personal-health",
            "subjective-sleep-experience",
            PersonalEvidenceProfile("owner-statement"),
            "single-night",
        )
        cards = tuple(
            EvidenceCard.from_claim(
                f"ticket112-portrait-context-{index}",
                AtomicEvidenceClaim(
                    content=f"第{index}次睡眠观察",
                    evidence_type="personal-health",
                    source_kind="owner-statement",
                    occurred_at=f"2026-08-{10 + index:02d}",
                    applicable_period=f"2026-08-{10 + index:02d}-night",
                    purpose="bounded-portrait-context",
                    uncertainty="主人主观体验",
                    limitations=("单次观察",),
                    proves=(f"第{index}次睡眠观察",),
                    does_not_prove=("长期趋势",),
                    topic_refs=(topic_ref,),
                    specific_fields=PersonalHealthFields("owner-statement"),
                    series_key=series_key,
                    time_certainty="known",
                ),
                recorded_at=f"2026-08-{10 + index:02d}T12:00:00Z",
            )
            for index in range(1, 7)
        )
        understanding = cards[0].content
        topic = PortraitTopic.from_decision(
            PortraitDecision.update(
                topic_ref=topic_ref,
                current_understandings=(understanding,),
                open_judgments=(),
                key_unknowns=(),
                proof_links=(
                    PortraitProofLink.form(
                        evidence_id=cards[0].evidence_id,
                        relation_kind="supports",
                        topic_ref=topic_ref,
                        item_kind="current-understanding",
                        item_text=understanding,
                        applicable_period=cards[0].applicable_period,
                    ),
                ),
            )
        )
        state = DailyHealthState(
            cards,
            (topic,),
            topic.evidence_relations,
            (),
        )
        contexts: list[PortraitContext] = []

        def executor(skill_name, context):
            if skill_name == "health-steward":
                if type(context) is StewardResolutionContext:
                    return StewardResolution(
                        context.candidate_evidence_ids,
                        context.candidate_portrait_topic_refs,
                        tuple(atom.atom_id for atom in context.reply_atoms),
                        context.candidate_evidence_change_ids,
                    )
                return StewardPlan(
                    purpose="bounded-portrait-context",
                    selected_skills=("health-portrait",),
                    atomic_claims=(),
                    portrait_topic_refs=(topic_ref,),
                )
            if skill_name == "health-portrait":
                contexts.append(context)
                return PortraitDecision.gap("完整主题依据未在最小上下文中可用")
            raise AssertionError(skill_name)

        runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=executor,
            clock=lambda: datetime(2026, 8, 24, 4, 7, tzinfo=timezone.utc),
        )
        source = materialize_source(
            self.message(
                CountingBody("复核睡眠画像"),
                causal_id="ticket112-bounded-portrait-context",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-bounded-portrait-context",
                protocol_timestamp="2026-08-24T12:07:00+08:00",
                received_at="2026-08-24T12:07:01+08:00",
                native_cursor="cursor-ticket112-bounded-portrait-context",
            )
        )
        stage = runtime.execute(source, state)
        runtime.complete(source, state.apply_evidence_stage(stage), stage)

        view = contexts[0].current_topic_views[0]
        preview_ids = {
            evidence_id
            for preview in view.evidence_previews
            for evidence_id in preview.preview_ids
        }
        expected_ids = preview_ids | set(topic.evidence_ids)
        self.assertEqual(
            {card.evidence_id for card in contexts[0].committed_related_cards},
            expected_ids,
        )
        self.assertLess(len(expected_ids), len(cards))

        def partial_executor(skill_name, context):
            if skill_name == "health-steward":
                if type(context) is StewardResolutionContext:
                    return StewardResolution(
                        context.candidate_evidence_ids,
                        context.candidate_portrait_topic_refs,
                        tuple(atom.atom_id for atom in context.reply_atoms),
                        context.candidate_evidence_change_ids,
                    )
                return StewardPlan(
                    purpose="bounded-portrait-context",
                    selected_skills=("health-portrait",),
                    atomic_claims=(),
                    portrait_topic_refs=(topic_ref,),
                )
            if skill_name == "health-portrait":
                partial_text = "只根据截断预览形成的错误画像"
                evidence_id = context.committed_related_cards[0].evidence_id
                return PortraitDecision.update(
                    topic_ref=topic_ref,
                    current_understandings=(partial_text,),
                    open_judgments=(),
                    key_unknowns=(),
                    proof_links=(
                        PortraitProofLink.form(
                            evidence_id=evidence_id,
                            relation_kind="supports",
                            topic_ref=topic_ref,
                            item_kind="current-understanding",
                            item_text=partial_text,
                            applicable_period=_portrait_evidence_period(
                                context,
                                evidence_id,
                            ),
                        ),
                    ),
                )
            raise AssertionError(skill_name)

        partial_runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=partial_executor,
            clock=lambda: datetime(2026, 8, 24, 4, 7, 1, tzinfo=timezone.utc),
        )
        partial_stage = partial_runtime.execute(source, state)
        with self.assertRaises(AuthorityValidationError):
            partial_runtime.complete(
                source,
                state.apply_evidence_stage(partial_stage),
                partial_stage,
            )

    def test_evidence_only_withdrawal_of_portrait_proof_is_rejected_before_lease(self) -> None:
        self.route_classification = "health"
        seed = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-linked-withdraw-seed",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-linked-withdraw-seed",
                protocol_timestamp="2026-08-24T12:08:00+08:00",
                received_at="2026-08-24T12:08:01+08:00",
                native_cursor="cursor-ticket112-linked-withdraw-seed",
            ),
            peer_id="plugin",
        )
        self.assertEqual(seed.status, "accepted")
        before = self.plugin.daily_state(peer_id="plugin")
        target = before.evidence_cards[0]
        request = EvidenceMaintenanceRequest(
            "withdraw",
            (target.evidence_id,),
            "主人明确撤回",
            "withdraw-linked-evidence",
        )

        def executor(skill_name, context):
            if skill_name == "health-steward":
                if type(context) is StewardResolutionContext:
                    return StewardResolution(
                        context.candidate_evidence_ids,
                        context.candidate_portrait_topic_refs,
                        tuple(atom.atom_id for atom in context.reply_atoms),
                        context.candidate_evidence_change_ids,
                    )
                return StewardPlan(
                    purpose="withdraw-linked-evidence",
                    selected_skills=("health-evidence",),
                    atomic_claims=(),
                    evidence_maintenance_requests=(request,),
                )
            if skill_name == "health-evidence":
                return EvidenceDecision.withdraw(
                    request.reason,
                    request.target_evidence_ids,
                )
            raise AssertionError(skill_name)

        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda: datetime(2026, 8, 24, 4, 8, tzinfo=timezone.utc),
            ),
        )
        causal_id = "ticket112-linked-evidence-only-withdraw"
        response = plugin.receive_weixin(
            self.message(
                CountingBody("撤回刚才的睡眠记录"),
                causal_id=causal_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-linked-evidence-only-withdraw",
                protocol_timestamp="2026-08-24T12:09:00+08:00",
                received_at="2026-08-24T12:09:01+08:00",
                native_cursor="cursor-ticket112-linked-evidence-only-withdraw",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "unavailable", response)
        self.assertEqual(response.reason_code, "daily-turn-candidate-invalid")
        self.assertIsNone(self.store.unresolved_daily_turn())
        self.assertIsNone(self.core.daily_turn_status(causal_id))
        self.assertEqual(plugin.daily_state(peer_id="plugin").digest, before.digest)

    def test_literature_candidate_is_returned_to_steward_without_authoritative_admission(self) -> None:
        topic_ref = "physical-function-and-experience/sleep"
        candidate_claim = AtomicEvidenceClaim(
            content="合格资料描述一般成年人睡眠体验的解释边界",
            evidence_type="authoritative-knowledge",
            source_kind="publisher-material",
            occurred_at="2026-08-24",
            applicable_period="2026-08-release",
            purpose="find-bounded-literature",
            uncertainty="不能自动适用于主人",
            limitations=("不证明主人个人事实",),
            proves=("合格资料描述一般成年人睡眠体验的解释边界",),
            does_not_prove=("主人健康状态",),
            topic_refs=(topic_ref,),
            specific_fields=AuthoritativeKnowledgeFields(
                publisher="approved-library",
                material_version="2026-08-v2",
                applicable_population="一般成年人",
                validity_boundary="仅作一般知识",
            ),
            series_key=EvidenceSeriesKey(
                "authoritative-knowledge",
                "general-sleep-knowledge",
                AuthoritativeKnowledgeProfile(
                    publisher="approved-library",
                    applicable_population="一般成年人",
                    validity_boundary="仅作一般知识",
                    source_nature="publisher-material",
                ),
                "release",
            ),
            time_certainty="known",
        )
        resolutions: list[StewardResolutionContext] = []

        def executor(skill_name, context):
            if skill_name == "health-steward":
                if type(context) is StewardResolutionContext:
                    resolutions.append(context)
                    return StewardResolution(
                        context.candidate_evidence_ids,
                        context.candidate_portrait_topic_refs,
                        tuple(atom.atom_id for atom in context.reply_atoms),
                        context.candidate_evidence_change_ids,
                    )
                return StewardPlan(
                    purpose="find-bounded-literature",
                    selected_skills=("health-literature",),
                    atomic_claims=(),
                    knowledge_gap="睡眠体验的一般解释边界",
                    knowledge_topic_refs=(topic_ref,),
                    allowed_knowledge_sources=("approved-library",),
                    recipient_boundary="configured-first-hop-only",
                )
            if skill_name == "health-literature":
                return LiteratureDecision.candidate(candidate_claim)
            raise AssertionError(skill_name)

        runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=executor,
            clock=lambda: datetime(2026, 8, 24, 4, 10, tzinfo=timezone.utc),
        )
        source = materialize_source(
            self.message(
                CountingBody("查找睡眠相关的一般资料"),
                causal_id="ticket112-literature-candidate",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-literature-candidate",
                protocol_timestamp="2026-08-24T12:10:00+08:00",
                received_at="2026-08-24T12:10:01+08:00",
                native_cursor="cursor-ticket112-literature-candidate",
            )
        )
        before = DailyHealthState.empty()
        stage = runtime.execute(source, before)
        complete = runtime.complete(
            source,
            before.apply_evidence_stage(stage),
            stage,
        )

        literature_result = next(
            result
            for result in resolutions[0].responsibility_results
            if result.canonical_name == "health-literature"
        )
        self.assertEqual(len(literature_result.candidate_refs), 1)
        self.assertTrue(
            literature_result.candidate_refs[0].startswith("literature-candidate:")
        )
        self.assertIn("找到一条合格资料候选", complete.owner_reply)
        self.assertIn("尚未写入权威证据", complete.owner_reply)
        self.assertNotIn("没有合格资料", complete.owner_reply)
        self.assertNotIn("边界不足", complete.owner_reply)
        self.assertEqual(complete.evidence_cards, ())

    def test_lifecycle_finalize_and_restart_replay_preserve_change_ids(self) -> None:
        self.route_classification = "health"
        seeded = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-replay-change-seed",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-replay-change-seed",
                protocol_timestamp="2026-08-24T12:11:00+08:00",
                received_at="2026-08-24T12:11:01+08:00",
                native_cursor="cursor-ticket112-replay-change-seed",
            ),
            peer_id="plugin",
        )
        self.assertEqual(seeded.status, "accepted")
        state = self.plugin.daily_state(peer_id="plugin")
        target = state.evidence_cards[0]
        topic_ref = state.portrait_topics[0].topic_ref
        request = EvidenceMaintenanceRequest(
            "withdraw",
            (target.evidence_id,),
            "主人明确撤回",
            "persist-evidence-change",
        )

        def executor(skill_name, context):
            if skill_name == "health-steward":
                if type(context) is StewardResolutionContext:
                    return StewardResolution(
                        context.candidate_evidence_ids,
                        context.candidate_portrait_topic_refs,
                        tuple(atom.atom_id for atom in context.reply_atoms),
                        context.candidate_evidence_change_ids,
                    )
                return StewardPlan(
                    purpose="persist-evidence-change",
                    selected_skills=("health-evidence", "health-portrait"),
                    atomic_claims=(),
                    portrait_topic_refs=(topic_ref,),
                    evidence_maintenance_requests=(request,),
                )
            if skill_name == "health-evidence":
                return EvidenceDecision.withdraw(
                    request.reason,
                    request.target_evidence_ids,
                )
            if skill_name == "health-portrait":
                return PortraitDecision.withdraw(
                    topic_ref,
                    "当前画像唯一依据已撤回",
                )
            raise AssertionError(skill_name)

        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda: datetime(2026, 8, 24, 4, 11, tzinfo=timezone.utc),
            ),
        )
        response = plugin.receive_weixin(
            self.message(
                CountingBody("撤回刚才的睡眠记录"),
                causal_id="ticket112-replay-change-source",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-replay-change-source",
                protocol_timestamp="2026-08-24T12:12:00+08:00",
                received_at="2026-08-24T12:12:01+08:00",
                native_cursor="cursor-ticket112-replay-change-source",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "accepted", response)
        expected = response.meta.turn_result
        self.assertEqual(len(expected.evidence_change_ids), 1)
        draft = self.store.last_daily_finalize_draft
        self.assertIs(type(draft), DailyTurnDraft)
        self.assertEqual(self.store.finalize_daily_turn(draft), expected)

        reopened = DailyFinalizeFailureStore(
            "file:ticket112?mode=memory&cache=shared",
            StaticKeyProvider(b"t" * 32, key_id="ticket112-state-key"),
        )
        try:
            replayed = reopened.finalize_daily_turn(draft)
            self.assertEqual(replayed, expected)
            self.assertEqual(
                replayed.evidence_change_ids,
                expected.evidence_change_ids,
            )
        finally:
            reopened.close()

    def test_inquiry_preflight_gap_does_not_disclose_health_views_or_cards(self) -> None:
        topic_ref = "physical-function-and-experience/sleep"
        series_key = EvidenceSeriesKey(
            "personal-health",
            "subjective-sleep-experience",
            PersonalEvidenceProfile("owner-statement"),
            "single-night",
        )

        def make_claim(content: str, occurred_at: str) -> AtomicEvidenceClaim:
            return AtomicEvidenceClaim(
                content=content,
                evidence_type="personal-health",
                source_kind="owner-statement",
                occurred_at=occurred_at,
                applicable_period=f"{occurred_at}-night",
                purpose="inquiry-preflight",
                uncertainty="主人主观体验",
                limitations=("单次陈述",),
                proves=(content,),
                does_not_prove=("长期趋势",),
                topic_refs=(topic_ref,),
                specific_fields=PersonalHealthFields("owner-statement"),
                series_key=series_key,
                time_certainty="known",
            )

        existing = EvidenceCard.from_claim(
            "ticket112-inquiry-existing",
            make_claim("既有睡眠正文不得在预检缺口时注入", "2026-08-22"),
            recorded_at="2026-08-22T12:00:00Z",
        )
        claim = make_claim("本轮待判断睡眠陈述", "2026-08-23")
        contexts: list[OwnerInquiryContext] = []

        def executor(skill_name, context):
            if skill_name == "health-steward":
                if type(context) is StewardResolutionContext:
                    return StewardResolution(
                        context.candidate_evidence_ids,
                        context.candidate_portrait_topic_refs,
                        tuple(atom.atom_id for atom in context.reply_atoms),
                        context.candidate_evidence_change_ids,
                    )
                return StewardPlan(
                    purpose="inquiry-preflight",
                    selected_skills=("health-evidence", "health-owner-inquiry"),
                    atomic_claims=(claim,),
                    inquiry_gap="昨晚睡眠时长未知",
                )
            if skill_name == "health-evidence":
                return EvidenceDecision.reject("本测试不准入候选")
            if skill_name == "health-owner-inquiry":
                contexts.append(context)
                return OwnerInquiryDecision.gap("required-context-unavailable")
            raise AssertionError(skill_name)

        runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=executor,
            clock=lambda: datetime(2026, 8, 24, 4, 12, tzinfo=timezone.utc),
        )
        source = materialize_source(
            self.message(
                CountingBody("我昨晚还是没睡好"),
                causal_id="ticket112-inquiry-preflight",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-inquiry-preflight",
                protocol_timestamp="2026-08-24T12:13:00+08:00",
                received_at="2026-08-24T12:13:01+08:00",
                native_cursor="cursor-ticket112-inquiry-preflight",
            )
        )
        before = DailyHealthState((existing,), (), (), ())
        stage = runtime.execute(source, before)
        runtime.complete(source, before.apply_evidence_stage(stage), stage)

        self.assertEqual(contexts[0].topic_refs, (topic_ref,))
        self.assertEqual(contexts[0].current_topic_views, ())
        self.assertEqual(contexts[0].direct_evidence_cards, ())
        self.assertEqual(contexts[0].related_task_acceptance_refs, ())
        self.assertEqual(
            set(contexts[0].missing_requirements),
            {
                "task-acceptance-unavailable",
                "current-control-state-unavailable",
                "same-gap-state-unavailable",
            },
        )

    def test_terminal_current_head_blocks_daily_result_replay_and_state_reads(self) -> None:
        self.route_classification = "health"
        message_changes = {
            "causal_id": "ticket112-terminal-strong-read",
            "generation": self.head.read().head.generation,
            "requested_capability": "health-steward",
            "message_id": "wx-ticket112-terminal-strong-read",
            "protocol_timestamp": "2026-08-24T12:14:00+08:00",
            "received_at": "2026-08-24T12:14:01+08:00",
            "native_cursor": "cursor-ticket112-terminal-strong-read",
        }
        first = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **message_changes),
            peer_id="plugin",
        )
        self.assertEqual(first.status, "accepted", first)
        calls_before_replay = tuple(self.turn_executor.calls)

        self.head.mark_terminal()
        replayed = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **message_changes),
            peer_id="plugin",
        )

        self.assertEqual(replayed.status, "unavailable", replayed)
        self.assertEqual(replayed.reason_code, "current-head-terminal")
        self.assertEqual(replayed.meta.to_wire(), {})
        self.assertEqual(tuple(self.turn_executor.calls), calls_before_replay)
        status = self.core.daily_turn_status(message_changes["causal_id"])
        self.assertTrue(status is None or status.result is None)
        with self.assertRaises(AuthorityValidationError):
            self.plugin.daily_state(peer_id="plugin")

    def test_finalized_prepare_replay_uses_body_free_digest_receipts(self) -> None:
        self.route_classification = "health"
        source_causal_id = "ticket112-redacted-prepare-replay"
        first = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id=source_causal_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-redacted-prepare-replay",
                protocol_timestamp="2026-08-24T12:15:00+08:00",
                received_at="2026-08-24T12:15:01+08:00",
                native_cursor="cursor-ticket112-redacted-prepare-replay",
            ),
            peer_id="plugin",
        )
        self.assertEqual(first.status, "accepted", first)
        complete_draft = self.store.last_daily_finalize_draft
        self.assertIs(type(complete_draft), DailyTurnDraft)
        evidence_draft = complete_draft.evidence_stage
        self.assertIs(type(evidence_draft), DailyTurnDraft)

        def prepare_command(stage: str, draft: DailyTurnDraft) -> CommandEnvelope:
            record = self.store.record(draft.record_id)
            self.assertIsNotNone(record)
            return CommandEnvelope(
                peer="plugin",
                action="turn.prepare",
                source="daily_skill_runtime",
                causal_id=self.plugin._daily_turn_causal_id(stage, source_causal_id),
                generation=record.payload.prepared.base.generation,
                scope=("turn:prepare",),
                payload=DailyTurnPreparePayload(draft),
            )

        commands = (
            prepare_command("evidence-prepare", evidence_draft),
            prepare_command("complete-prepare", complete_draft),
        )
        directive = self.plugin.native_cursor_directive(
            source_causal_id,
            peer_id="plugin",
        )
        self.assertIsNotNone(directive)
        self.assertEqual(
            self.plugin.record_native_cursor_result(
                directive,
                status="advanced",
                peer_id="plugin",
            ).status,
            "accepted",
        )
        before_digest = self.store.daily_state().digest
        before_generation = self.head.read().head.generation

        for command in commands:
            replayed = self.plugin.invoke(command, peer_id="plugin")
            self.assertEqual(replayed.status, "accepted", replayed)
            self.assertEqual(replayed.reason_code, "daily-turn-prepared")
            self.assertEqual(replayed.meta.to_wire(), {})
            self.assertEqual(self.store.receipt(command), replayed)
            row = self.store._execute(
                "SELECT nonce, ciphertext FROM command_receipts_v2 WHERE causal_id = ?",
                (command.causal_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            stored = self.store._open(
                f"receipt:v2:{command.causal_id}",
                row[0],
                row[1],
            )
            self.assertEqual(
                set(stored),
                {"kind", "command_digest", "response"},
            )
            self.assertNotIn("owner_reply", repr(stored))
            self.assertNotIn("主人自述昨晚主观睡眠体验不佳", repr(stored))

            forged = replace(command, generation=command.generation + 1)
            conflict = self.plugin.invoke(forged, peer_id="plugin")
            self.assertEqual(conflict.status, "rejected", conflict)
            self.assertEqual(conflict.reason_code, "causal-id-conflict")

        self.assertEqual(self.store.daily_state().digest, before_digest)
        self.assertEqual(self.head.read().head.generation, before_generation)

    def test_confirmed_native_redelivery_reuses_one_business_turn_and_two_cursors(self) -> None:
        self.route_classification = "health"
        root_causal_id = "ticket112-native-root"
        shared = {
            "requested_capability": "health-steward",
            "message_id": "wx-ticket112-native-same",
            "protocol_timestamp": "2026-08-24T12:16:00+08:00",
        }
        first = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id=root_causal_id,
                generation=self.head.read().head.generation,
                received_at="2026-08-24T12:16:01+08:00",
                native_cursor="cursor-ticket112-native-root",
                **shared,
            ),
            peer_id="plugin",
        )
        self.assertEqual(first.status, "accepted", first)
        calls_after_first = tuple(self.turn_executor.calls)

        alias_causal_id = "ticket112-native-alias"
        second = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id=alias_causal_id,
                generation=self.head.read().head.generation,
                received_at="2026-08-24T12:16:05+08:00",
                native_cursor="cursor-ticket112-native-alias",
                **shared,
            ),
            peer_id="plugin",
        )

        self.assertEqual(second.status, "replayed", second)
        self.assertEqual(second.reason_code, "daily-source-native-replay")
        self.assertEqual(tuple(self.turn_executor.calls), calls_after_first)
        state = self.plugin.daily_state(peer_id="plugin")
        self.assertEqual(len(state.evidence_cards), 1)
        self.assertEqual(state.processed_source_causal_ids, (root_causal_id,))
        alias_receipt = self.plugin.source_receipt(alias_causal_id, peer_id="plugin")
        self.assertEqual(alias_receipt.relation, "possible-replay")
        self.assertEqual(alias_receipt.business_source_causal_id, root_causal_id)
        self.assertTrue(
            alias_receipt.native_event_digest.startswith("hmac-sha256:")
        )
        self.assertTrue(alias_receipt.business_committed)
        self.assertIsNone(alias_receipt.envelope.body)

        directives = tuple(
            self.plugin.native_cursor_directive(causal_id, peer_id="plugin")
            for causal_id in (root_causal_id, alias_causal_id)
        )
        self.assertTrue(all(item is not None for item in directives))
        self.assertEqual(
            tuple(item.native_cursor for item in directives),
            ("cursor-ticket112-native-root", "cursor-ticket112-native-alias"),
        )
        self.assertEqual(
            directives[0].business_transition_id,
            directives[1].business_transition_id,
        )
        for directive in directives:
            advanced = self.plugin.record_native_cursor_result(
                directive,
                status="advanced",
                peer_id="plugin",
            )
            self.assertEqual(advanced.status, "accepted", advanced)

    def test_native_redelivery_after_restart_uses_persisted_fingerprint(self) -> None:
        self.route_classification = "health"
        root_causal_id = "ticket112-native-restart-root"
        shared = {
            "requested_capability": "health-steward",
            "message_id": "wx-ticket112-native-restart",
            "protocol_timestamp": "2026-08-24T12:16:10+08:00",
        }
        first = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id=root_causal_id,
                generation=self.head.read().head.generation,
                received_at="2026-08-24T12:16:11+08:00",
                native_cursor="cursor-ticket112-native-restart-root",
                **shared,
            ),
            peer_id="plugin",
        )
        self.assertEqual(first.status, "accepted", first)
        calls_after_first = tuple(self.turn_executor.calls)

        self.assertTrue(self.core.close().complete)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
            daily_skill_verifier=self.daily_attestor,
            daily_skill_bundle=self.daily_bundle,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=self.daily_runtime,
        )

        alias_causal_id = "ticket112-native-restart-alias"
        replayed = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id=alias_causal_id,
                generation=self.head.read().head.generation,
                received_at="2026-08-24T12:16:15+08:00",
                native_cursor="cursor-ticket112-native-restart-alias",
                **shared,
            ),
            peer_id="plugin",
        )

        self.assertEqual(replayed.status, "replayed", replayed)
        self.assertEqual(replayed.reason_code, "daily-source-native-replay")
        self.assertEqual(tuple(self.turn_executor.calls), calls_after_first)
        self.assertEqual(len(self.plugin.daily_state(peer_id="plugin").evidence_cards), 1)
        alias_receipt = self.store.source_receipt(alias_causal_id)
        self.assertEqual(alias_receipt.business_source_causal_id, root_causal_id)
        self.assertTrue(alias_receipt.business_committed)

    def test_different_native_message_ids_with_same_body_are_independent_turns(self) -> None:
        self.route_classification = "health"
        first = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-native-distinct-first",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-native-distinct-first",
                protocol_timestamp="2026-08-24T12:16:20+08:00",
                received_at="2026-08-24T12:16:21+08:00",
                native_cursor="cursor-ticket112-native-distinct-first",
            ),
            peer_id="plugin",
        )
        self.assertEqual(first.status, "accepted", first)
        calls_after_first = len(self.turn_executor.calls)

        second = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-native-distinct-second",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-native-distinct-second",
                protocol_timestamp="2026-08-24T12:16:20+08:00",
                received_at="2026-08-24T12:16:25+08:00",
                native_cursor="cursor-ticket112-native-distinct-second",
            ),
            peer_id="plugin",
        )

        self.assertEqual(second.status, "accepted", second)
        self.assertGreater(len(self.turn_executor.calls), calls_after_first)
        state = self.plugin.daily_state(peer_id="plugin")
        self.assertEqual(len(state.evidence_cards), 2)
        self.assertEqual(
            state.processed_source_causal_ids,
            (
                "ticket112-native-distinct-first",
                "ticket112-native-distinct-second",
            ),
        )

    def test_native_redelivery_during_evidence_stage_waits_for_root_recovery(self) -> None:
        self.route_classification = "health"
        self.turn_executor.fail_next_portrait = True
        root_causal_id = "ticket112-native-pending-root"
        root_changes = {
            "causal_id": root_causal_id,
            "generation": self.head.read().head.generation,
            "requested_capability": "health-steward",
            "message_id": "wx-ticket112-native-pending",
            "protocol_timestamp": "2026-08-24T12:16:30+08:00",
            "received_at": "2026-08-24T12:16:31+08:00",
            "native_cursor": "cursor-ticket112-native-pending-root",
        }
        interrupted = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **root_changes),
            peer_id="plugin",
        )
        self.assertEqual(interrupted.status, "unavailable", interrupted)
        self.assertEqual(
            self.core.daily_turn_status(root_causal_id).phase,
            "evidence-finalized",
        )
        calls_after_interruption = tuple(self.turn_executor.calls)

        alias_causal_id = "ticket112-native-pending-alias"
        alias_changes = {
            "causal_id": alias_causal_id,
            "generation": self.head.read().head.generation,
            "requested_capability": "health-steward",
            "message_id": root_changes["message_id"],
            "protocol_timestamp": root_changes["protocol_timestamp"],
            "received_at": "2026-08-24T12:16:35+08:00",
            "native_cursor": "cursor-ticket112-native-pending-alias",
        }
        alias = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                **alias_changes,
            ),
            peer_id="plugin",
        )
        self.assertEqual(alias.status, "unavailable", alias)
        self.assertEqual(alias.reason_code, "daily-source-native-replay-pending")
        self.assertEqual(tuple(self.turn_executor.calls), calls_after_interruption)
        self.assertIsNone(self.store.daily_turn(alias_causal_id))
        alias_receipt = self.store.source_receipt(alias_causal_id)
        self.assertEqual(
            alias_receipt.business_source_causal_id,
            root_causal_id,
        )
        self.assertFalse(alias_receipt.business_committed)

        recovered = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **root_changes),
            peer_id="plugin",
        )
        self.assertEqual(recovered.status, "accepted", recovered)
        self.assertEqual(
            self.core.daily_turn_status(root_causal_id).phase,
            "finalized",
        )
        self.assertEqual(len(self.plugin.daily_state(peer_id="plugin").evidence_cards), 1)
        self.assertTrue(self.store.source_receipt(alias_causal_id).business_committed)
        calls_after_recovery = tuple(self.turn_executor.calls)
        converged_alias = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **alias_changes),
            peer_id="plugin",
        )
        self.assertEqual(converged_alias.status, "replayed", converged_alias)
        self.assertEqual(
            converged_alias.reason_code,
            "daily-source-native-replay",
        )
        self.assertEqual(tuple(self.turn_executor.calls), calls_after_recovery)
        alias_directive = self.plugin.native_cursor_directive(
            alias_causal_id,
            peer_id="plugin",
        )
        self.assertIsNotNone(alias_directive)
        self.assertEqual(
            alias_directive.business_transition_id,
            self.plugin.native_cursor_directive(
                root_causal_id,
                peer_id="plugin",
            ).business_transition_id,
        )

    def test_native_alias_family_commit_rolls_back_and_recovers_atomically(self) -> None:
        self.route_classification = "health"
        self.turn_executor.fail_next_portrait = True
        root_changes = {
            "causal_id": "ticket112-native-family-root",
            "generation": self.head.read().head.generation,
            "requested_capability": "health-steward",
            "message_id": "wx-ticket112-native-family",
            "protocol_timestamp": "2026-08-24T12:16:40+08:00",
            "received_at": "2026-08-24T12:16:41+08:00",
            "native_cursor": "cursor-ticket112-native-family-root",
        }
        interrupted = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **root_changes),
            peer_id="plugin",
        )
        self.assertEqual(interrupted.status, "unavailable", interrupted)

        alias_changes = {
            **root_changes,
            "causal_id": "ticket112-native-family-alias",
            "generation": self.head.read().head.generation,
            "received_at": "2026-08-24T12:16:45+08:00",
            "native_cursor": "cursor-ticket112-native-family-alias",
        }
        pending = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **alias_changes),
            peer_id="plugin",
        )
        self.assertEqual(pending.reason_code, "daily-source-native-replay-pending")

        self.store.fail_next_daily_finalize = True
        failed = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **root_changes),
            peer_id="plugin",
        )
        self.assertEqual(failed.reason_code, "health-state-unavailable")
        for causal_id in (
            root_changes["causal_id"],
            alias_changes["causal_id"],
        ):
            receipt = self.store.source_receipt(causal_id)
            self.assertFalse(receipt.business_committed)
            self.assertIsNotNone(receipt.envelope.body)

        recovered = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **root_changes),
            peer_id="plugin",
        )
        self.assertEqual(recovered.status, "accepted", recovered)
        for causal_id in (
            root_changes["causal_id"],
            alias_changes["causal_id"],
        ):
            receipt = self.store.source_receipt(causal_id)
            self.assertTrue(receipt.business_committed)
            self.assertIsNone(receipt.envelope.body)

    def test_legacy_root_without_fingerprint_rejects_alias_without_retaining_body(self) -> None:
        self.route_classification = "health"
        root = materialize_source(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-native-legacy-root",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-native-legacy",
                protocol_timestamp="2026-08-24T12:16:50+08:00",
                received_at="2026-08-24T12:16:51+08:00",
                native_cursor="cursor-ticket112-native-legacy-root",
            )
        )
        self.store.save_source_envelope(root)
        committed = self.store.mark_source_business_committed(root.causal_id)
        legacy = committed.to_storage()
        legacy.pop("native_event_digest")
        legacy.pop("business_source_causal_id")
        nonce, ciphertext = self.store._seal(
            f"source-envelope:{root.causal_id}",
            legacy,
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE source_envelopes_v1 SET nonce = ?, ciphertext = ? "
                "WHERE causal_id = ?",
                (nonce, ciphertext, root.causal_id),
            )
            self.store._refresh_integrity_manifest(connection)

        alias_causal_id = "ticket112-native-legacy-alias"
        alias_changes = {
            "causal_id": alias_causal_id,
            "generation": self.head.read().head.generation,
            "requested_capability": "health-steward",
            "message_id": root.message_id,
            "protocol_timestamp": root.protocol_timestamp,
            "received_at": "2026-08-24T12:16:55+08:00",
            "native_cursor": "cursor-ticket112-native-legacy-alias",
        }
        unavailable = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **alias_changes),
            peer_id="plugin",
        )

        self.assertEqual(unavailable.status, "unavailable", unavailable)
        self.assertEqual(
            unavailable.reason_code,
            "native-replay-proof-unavailable",
        )
        rejected = self.store.source_receipt(alias_causal_id)
        self.assertEqual(rejected.managed_cursor_state, "rejected")
        self.assertIsNone(rejected.envelope.body)
        self.assertIsNone(
            self.plugin.native_cursor_directive(alias_causal_id, peer_id="plugin")
        )
        replayed = self.plugin.receive_weixin(
            self.message(CountingBody("我昨晚没睡好"), **alias_changes),
            peer_id="plugin",
        )
        self.assertEqual(replayed, unavailable)

    def test_native_message_id_conflict_fails_closed_without_second_turn(self) -> None:
        self.route_classification = "health"
        shared = {
            "requested_capability": "health-steward",
            "message_id": "wx-ticket112-native-conflict",
            "protocol_timestamp": "2026-08-24T12:17:00+08:00",
        }
        first = self.plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-native-conflict-root",
                generation=self.head.read().head.generation,
                received_at="2026-08-24T12:17:01+08:00",
                native_cursor="cursor-ticket112-native-conflict-root",
                **shared,
            ),
            peer_id="plugin",
        )
        self.assertEqual(first.status, "accepted", first)
        calls_after_first = tuple(self.turn_executor.calls)

        conflict_causal_id = "ticket112-native-conflict-second"
        conflict = self.plugin.receive_weixin(
            self.message(
                CountingBody("我今天睡得很好"),
                causal_id=conflict_causal_id,
                generation=self.head.read().head.generation,
                received_at="2026-08-24T12:17:05+08:00",
                native_cursor="cursor-ticket112-native-conflict-second",
                **shared,
            ),
            peer_id="plugin",
        )

        self.assertEqual(conflict.status, "rejected", conflict)
        self.assertEqual(conflict.reason_code, "native-message-id-conflict")
        self.assertEqual(tuple(self.turn_executor.calls), calls_after_first)
        self.assertEqual(len(self.plugin.daily_state(peer_id="plugin").evidence_cards), 1)
        conflict_receipt = self.store.source_receipt(conflict_causal_id)
        self.assertEqual(conflict_receipt.managed_cursor_state, "rejected")
        self.assertIsNone(conflict_receipt.envelope.body)
        self.assertIsNone(
            self.plugin.native_cursor_directive(
                conflict_causal_id,
                peer_id="plugin",
            )
        )

    def test_steward_cannot_hide_committed_evidence_from_owner_reply(self) -> None:
        self.route_classification = "health"
        delegate = SyntheticSleepTurnExecutor()

        def executor(skill_name, context):
            if skill_name == "health-steward" and type(context) is StewardResolutionContext:
                selected = tuple(
                    atom.atom_id
                    for atom in context.reply_atoms
                    if atom.required_portrait_topic_refs
                )
                return StewardResolution(
                    context.candidate_evidence_ids,
                    context.candidate_portrait_topic_refs,
                    selected,
                    context.candidate_evidence_change_ids,
                )
            return delegate(skill_name, context)

        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda: datetime(2026, 8, 24, 4, 18, tzinfo=timezone.utc),
            ),
        )
        before = plugin.daily_state(peer_id="plugin").digest
        response = plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-hidden-commit",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-hidden-commit",
                protocol_timestamp="2026-08-24T12:18:00+08:00",
                received_at="2026-08-24T12:18:01+08:00",
                native_cursor="cursor-ticket112-hidden-commit",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "unavailable", response)
        self.assertEqual(response.reason_code, "daily-turn-candidate-invalid")
        self.assertEqual(plugin.daily_state(peer_id="plugin").digest, before)

    def test_portrait_time_in_display_text_cannot_replace_structured_period(self) -> None:
        self.route_classification = "health"
        delegate = SyntheticSleepTurnExecutor()

        def executor(skill_name, context):
            if skill_name != "health-portrait":
                return delegate(skill_name, context)
            understanding = "主人自述昨晚睡眠体验不佳（仅昨晚）"
            return PortraitDecision.update(
                topic_ref="physical-function-and-experience/sleep",
                current_understandings=(understanding,),
                open_judgments=(),
                key_unknowns=(),
                proof_links=(
                    PortraitProofLink.form(
                        evidence_id=context.evidence_ids[0],
                        relation_kind="supports",
                        topic_ref="physical-function-and-experience/sleep",
                        item_kind="current-understanding",
                        item_text=understanding,
                    ),
                ),
            )

        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda: datetime(2026, 8, 24, 4, 19, tzinfo=timezone.utc),
            ),
        )
        before = plugin.daily_state(peer_id="plugin").digest
        response = plugin.receive_weixin(
            self.message(
                CountingBody("我昨晚没睡好"),
                causal_id="ticket112-portrait-time-required",
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id="wx-ticket112-portrait-time-required",
                protocol_timestamp="2026-08-24T12:19:00+08:00",
                received_at="2026-08-24T12:19:01+08:00",
                native_cursor="cursor-ticket112-portrait-time-required",
            ),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "unavailable", response)
        self.assertEqual(response.reason_code, "daily-turn-candidate-invalid")
        self.assertEqual(plugin.daily_state(peer_id="plugin").digest, before)

    def test_summary_coverage_order_uses_real_instants_not_raw_strings(self) -> None:
        common = {
            "total_original_detail_count": 3,
            "pattern": "三次观察",
            "exceptions": (),
            "unknowns": ("不能证明趋势",),
            "cumulative_uncertainty": "主人主观陈述",
            "method_or_source_changes": (),
            "lost_detail_scope": "三张旧明细",
            "generation": 1,
            "absorbed_records_digest": "sha256:" + ("b" * 64),
            "absorbed_record_count": 3,
        }
        valid = EvidenceSummaryFields(
            coverage_start="2026-08-02T00:00:00+08:00",
            coverage_end="2026-08-01T20:00:00+00:00",
            **common,
        )
        self.assertEqual(valid.coverage_start, "2026-08-02T00:00:00+08:00")
        with self.assertRaises(AuthorityValidationError):
            EvidenceSummaryFields(
                coverage_start="2026-08-02T01:00:00+08:00",
                coverage_end="2026-08-01T16:30:00+00:00",
                **common,
            )


if __name__ == "__main__":
    unittest.main()

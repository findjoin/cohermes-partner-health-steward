"""Red contract tests for Ticket112 portrait proof and revision semantics.

These tests intentionally describe the missing public contract instead of a
private implementation.  A durable ``DailyHealthState.portrait_revisions``
tuple is expected.  Each revision carries the exact previous/next
``PortraitTopic`` snapshots, action, human-readable reason, the signed
``PortraitDecision`` digest, and the Skill-use timestamp as ``changed_at``.
Equivalent storage may be implemented internally, but these values must remain
available through the aggregate so correction, export, and deletion can trace
the current projection back to its predecessor.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from partner_health_steward.admission import SourceEnvelope
from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.coordination import (
    AtomicEvidenceClaim,
    DailyHealthState,
    DailySkillAsset,
    DailySkillAttestor,
    DailySkillBundle,
    DailySkillRuntime,
    EvidenceContext,
    EvidenceDecision,
    EvidenceMaintenanceRequest,
    EvidenceSeriesKey,
    EvidenceCard,
    PersonalHealthFields,
    PortraitContext,
    PortraitDecision,
    PortraitProofLink,
    PortraitTopic,
    StewardContext,
    StewardPlan,
    StewardResolution,
    StewardResolutionContext,
)
from partner_health_steward.evidence_profile import PersonalEvidenceProfile


TOPIC_REF = "physical-function-and-experience/sleep"
CHANGE_TIME = datetime(2026, 8, 24, 2, 30, tzinfo=timezone.utc)


def _bundle() -> DailySkillBundle:
    return DailySkillBundle(
        tuple(
            DailySkillAsset(
                canonical_name=canonical_name,
                friendly_name=friendly_name,
                role=role,
                version="1.0.0",
                asset_digest="sha256:" + digit * 64,
                disclosure_version="daily-skill-disclosure-v1",
            )
            for canonical_name, friendly_name, role, digit in (
                ("health-steward", "健康管家", "A", "1"),
                ("health-settings", "健康管家设置", "A", "2"),
                ("health-portrait", "健康画像维护", "B", "3"),
                ("health-evidence", "健康证据维护", "B", "4"),
                ("health-owner-inquiry", "向主人补问", "B", "5"),
                ("health-literature", "健康资料查找", "B", "6"),
            )
        )
    )


def _source(suffix: str) -> SourceEnvelope:
    return SourceEnvelope(
        causal_id=f"ticket112-portrait-revision-{suffix}",
        generation=2,
        channel="weixin",
        partner_id="partner-A",
        sender_id="owner-A",
        conversation_id="private-A",
        chat_type="private",
        entrypoint="partner-health-steward",
        requested_capability="health-steward",
        message_id=f"wx-ticket112-portrait-revision-{suffix}",
        protocol_timestamp="2026-08-24T10:30:00+08:00",
        received_at="2026-08-24T10:30:01+08:00",
        native_cursor=f"cursor-ticket112-portrait-revision-{suffix}",
        body=f"portrait revision contract {suffix}",
    )


def _seed_claim() -> AtomicEvidenceClaim:
    content = "主人自述昨晚睡眠体验不佳"
    return AtomicEvidenceClaim(
        content=content,
        evidence_type="personal-health",
        source_kind="owner-statement",
        occurred_at="2026-08-23",
        applicable_period="2026-08-23-night",
        purpose="seed-sleep-portrait",
        uncertainty="主人主观体验",
        limitations=("单次陈述不证明趋势",),
        proves=(content,),
        does_not_prove=("睡眠诊断", "长期趋势"),
        topic_refs=(TOPIC_REF,),
        specific_fields=PersonalHealthFields("owner-statement"),
        series_key=EvidenceSeriesKey(
            "personal-health",
            "subjective-sleep-experience",
            PersonalEvidenceProfile("owner-statement"),
            "single-night",
        ),
        time_certainty="known",
    )


def _seeded_state() -> tuple[DailyHealthState, EvidenceCard, PortraitTopic]:
    claim = _seed_claim()
    card = EvidenceCard.from_claim(
        "ticket112-portrait-revision-seed",
        claim,
        recorded_at="2026-08-24T01:00:00Z",
    )
    link = PortraitProofLink.form(
        evidence_id=card.evidence_id,
        relation_kind="supports",
        topic_ref=TOPIC_REF,
        item_kind="current-understanding",
        item_text=claim.content,
    )
    topic = PortraitTopic.from_decision(
        PortraitDecision.update(
            topic_ref=TOPIC_REF,
            current_understandings=(claim.content,),
            open_judgments=(),
            key_unknowns=(),
            proof_links=(link,),
        )
    )
    return (
        DailyHealthState(
            (card,),
            (topic,),
            topic.evidence_relations,
            (),
        ),
        card,
        topic,
    )


def _proof_link(
    *,
    evidence_id: str,
    relation_kind: str,
    item_kind: str,
    item_text: str,
    trend_period: str | None = None,
) -> PortraitProofLink:
    return PortraitProofLink.form(
        evidence_id=evidence_id,
        relation_kind=relation_kind,
        topic_ref=TOPIC_REF,
        item_kind=item_kind,
        item_text=item_text,
        trend_period=trend_period,
    )


def _complete_item_links() -> tuple[PortraitProofLink, ...]:
    return (
        _proof_link(
            evidence_id="evidence:proof-1",
            relation_kind="supports",
            item_kind="current-understanding",
            item_text="近期入睡后易醒",
        ),
        _proof_link(
            evidence_id="evidence:proof-1",
            relation_kind="supports",
            item_kind="trend",
            item_text="近两周睡眠体验下降",
            trend_period="2026-08-10/2026-08-23",
        ),
        _proof_link(
            evidence_id="evidence:proof-2",
            relation_kind="qualifies",
            item_kind="trend",
            item_text="近两周睡眠体验下降",
            trend_period="2026-08-10/2026-08-23",
        ),
        _proof_link(
            evidence_id="evidence:proof-1",
            relation_kind="qualifies",
            item_kind="open-judgment",
            item_text="夜班是否是主要影响因素仍待判断",
        ),
        _proof_link(
            evidence_id="evidence:proof-2",
            relation_kind="opposes",
            item_kind="key-unknown",
            item_text="最近一周总睡眠时长未知",
        ),
    )


def _decision_with_all_item_kinds(
    proof_links: tuple[PortraitProofLink, ...],
) -> PortraitDecision:
    return PortraitDecision.update(
        topic_ref=TOPIC_REF,
        current_understandings=("近期入睡后易醒",),
        trend="近两周睡眠体验下降",
        trend_period="2026-08-10/2026-08-23",
        open_judgments=("夜班是否是主要影响因素仍待判断",),
        key_unknowns=("最近一周总睡眠时长未知",),
        proof_links=proof_links,
    )


class _PortraitOnlyExecutor:
    def __init__(self, decision: PortraitDecision, purpose: str) -> None:
        self.decision = decision
        self.purpose = purpose

    def __call__(self, skill_name: str, context: object) -> object:
        if skill_name == "health-steward":
            if type(context) is StewardContext:
                return StewardPlan(
                    purpose=self.purpose,
                    selected_skills=("health-portrait",),
                    atomic_claims=(),
                    portrait_topic_refs=(TOPIC_REF,),
                )
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
            raise TypeError("unexpected steward context")
        if skill_name == "health-portrait":
            if type(context) is not PortraitContext:
                raise TypeError("unexpected portrait context")
            return self.decision
        raise AssertionError(f"unexpected Skill execution: {skill_name}")


class _WithdrawThenReuseProofExecutor:
    def __init__(self, card: EvidenceCard) -> None:
        self.card = card
        self.portrait_context: PortraitContext | None = None

    def __call__(self, skill_name: str, context: object) -> object:
        if skill_name == "health-steward":
            if type(context) is StewardContext:
                purpose = "withdraw-obsolete-sleep-proof"
                return StewardPlan(
                    purpose=purpose,
                    selected_skills=("health-evidence", "health-portrait"),
                    atomic_claims=(),
                    portrait_topic_refs=(TOPIC_REF,),
                    evidence_maintenance_requests=(
                        EvidenceMaintenanceRequest(
                            "withdraw",
                            (self.card.evidence_id,),
                            "主人明确撤回原陈述",
                            purpose,
                        ),
                    ),
                )
            if type(context) is StewardResolutionContext:
                return StewardResolution(
                    context.candidate_evidence_ids,
                    context.candidate_portrait_topic_refs,
                    tuple(atom.atom_id for atom in context.reply_atoms),
                    context.candidate_evidence_change_ids,
                )
            raise TypeError("unexpected steward context")
        if skill_name == "health-evidence":
            if type(context) is not EvidenceContext:
                raise TypeError("unexpected evidence context")
            return EvidenceDecision.withdraw(
                "主人明确撤回原陈述",
                (self.card.evidence_id,),
            )
        if skill_name == "health-portrait":
            if type(context) is not PortraitContext:
                raise TypeError("unexpected portrait context")
            self.portrait_context = context
            replacement = "被撤回证据仍声称支持当前睡眠画像"
            return PortraitDecision.update(
                topic_ref=TOPIC_REF,
                current_understandings=(replacement,),
                open_judgments=(),
                key_unknowns=(),
                proof_links=(
                    _proof_link(
                        evidence_id=self.card.evidence_id,
                        relation_kind="supports",
                        item_kind="current-understanding",
                        item_text=replacement,
                    ),
                ),
            )
        raise AssertionError(f"unexpected Skill execution: {skill_name}")


class Ticket112PortraitRevisionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = _bundle()
        self.attestor = DailySkillAttestor(
            b"r" * 32,
            key_id="ticket112-portrait-revision-attestor",
        )

    def runtime(self, executor: object) -> DailySkillRuntime:
        return DailySkillRuntime(
            self.bundle,
            self.attestor,
            executor=executor,  # type: ignore[arg-type]
            clock=lambda: CHANGE_TIME,
        )

    def run_portrait_decision(
        self,
        *,
        suffix: str,
        state: DailyHealthState,
        decision: PortraitDecision,
        purpose: str,
    ) -> tuple[DailyHealthState, object, object]:
        source = _source(suffix)
        runtime = self.runtime(_PortraitOnlyExecutor(decision, purpose))
        stage = runtime.execute(source, state)
        post_stage = state.apply_evidence_stage(stage)
        complete = runtime.complete(source, post_stage, stage)
        final_state, _ = post_stage.apply(complete)
        portrait_result = next(
            result
            for result in complete.responsibility_results
            if result.canonical_name == "health-portrait"
        )
        portrait_proof = next(
            proof
            for proof in complete.skill_proofs
            if proof.skill_use.canonical_name == "health-portrait"
        )
        return final_state, portrait_result, portrait_proof

    def test_proof_link_round_trips_all_four_portrait_item_kinds(self) -> None:
        cases = (
            ("current-understanding", "近期入睡后易醒", None),
            ("trend", "近两周睡眠体验下降", "2026-08-10/2026-08-23"),
            ("open-judgment", "夜班是否是主要影响因素仍待判断", None),
            ("key-unknown", "最近一周总睡眠时长未知", None),
        )
        for item_kind, item_text, trend_period in cases:
            with self.subTest(item_kind=item_kind):
                link = _proof_link(
                    evidence_id="evidence:proof-1",
                    relation_kind="supports",
                    item_kind=item_kind,
                    item_text=item_text,
                    trend_period=trend_period,
                )
                self.assertEqual(
                    PortraitProofLink.from_storage(link.to_storage()),
                    link,
                )

    def test_every_displayed_portrait_item_requires_an_exact_proof_link(self) -> None:
        complete_links = _complete_item_links()
        decision = _decision_with_all_item_kinds(complete_links)
        self.assertEqual(
            PortraitDecision.from_storage(decision.to_storage()),
            decision,
        )

        for missing_kind in (
            "current-understanding",
            "trend",
            "open-judgment",
            "key-unknown",
        ):
            with self.subTest(missing_kind=missing_kind):
                incomplete_links = tuple(
                    link
                    for link in complete_links
                    if link.item_kind != missing_kind
                )
                with self.assertRaises(AuthorityValidationError):
                    _decision_with_all_item_kinds(incomplete_links)

    def test_portrait_item_proof_must_match_exact_text_and_trend_period(self) -> None:
        complete_links = _complete_item_links()
        mismatches = (
            _proof_link(
                evidence_id="evidence:proof-1",
                relation_kind="supports",
                item_kind="current-understanding",
                item_text="文字相近但不是该项原文",
            ),
            _proof_link(
                evidence_id="evidence:proof-1",
                relation_kind="qualifies",
                item_kind="open-judgment",
                item_text="另一个开放判断",
            ),
            _proof_link(
                evidence_id="evidence:proof-2",
                relation_kind="opposes",
                item_kind="key-unknown",
                item_text="另一个关键未知",
            ),
            _proof_link(
                evidence_id="evidence:proof-1",
                relation_kind="supports",
                item_kind="trend",
                item_text="近两周睡眠体验下降",
                trend_period="2026-08-01/2026-08-23",
            ),
        )
        for mismatch in mismatches:
            with self.subTest(item_kind=mismatch.item_kind):
                retained = tuple(
                    link
                    for link in complete_links
                    if not (
                        link.item_kind == mismatch.item_kind
                        and link.evidence_id == mismatch.evidence_id
                        and link.relation_kind == mismatch.relation_kind
                    )
                )
                with self.assertRaises(AuthorityValidationError):
                    _decision_with_all_item_kinds((*retained, mismatch))

    def test_update_degrade_and_withdraw_append_traceable_revisions(self) -> None:
        seeded, card, seeded_topic = _seeded_state()
        updated_text = "主人补充后，当前睡眠体验仍不佳"
        degraded_text = "现有资料只能限定为一次较差睡眠体验"
        cases = (
            (
                "update",
                PortraitDecision.update(
                    topic_ref=TOPIC_REF,
                    current_understandings=(updated_text,),
                    open_judgments=(),
                    key_unknowns=(),
                    proof_links=(
                        _proof_link(
                            evidence_id=card.evidence_id,
                            relation_kind="supports",
                            item_kind="current-understanding",
                            item_text=updated_text,
                        ),
                    ),
                ),
                "portrait-update",
            ),
            (
                "degrade",
                PortraitDecision.degrade(
                    topic_ref=TOPIC_REF,
                    current_understandings=(degraded_text,),
                    open_judgments=(),
                    key_unknowns=(),
                    proof_links=(
                        _proof_link(
                            evidence_id=card.evidence_id,
                            relation_kind="qualifies",
                            item_kind="current-understanding",
                            item_text=degraded_text,
                        ),
                    ),
                    reason="supporting-evidence-became-limited",
                ),
                "portrait-degrade",
            ),
            (
                "withdraw",
                PortraitDecision.withdraw(
                    TOPIC_REF,
                    "no-current-applicable-proof-remains",
                ),
                "portrait-withdraw",
            ),
        )

        for action, decision, purpose in cases:
            with self.subTest(action=action):
                final_state, portrait_result, portrait_proof = (
                    self.run_portrait_decision(
                        suffix=action,
                        state=seeded,
                        decision=decision,
                        purpose=purpose,
                    )
                )
                self.assertTrue(
                    hasattr(final_state, "portrait_revisions"),
                    "DailyHealthState must durably expose portrait revisions",
                )
                revisions = final_state.portrait_revisions
                self.assertEqual(len(revisions), 1)
                revision = revisions[0]
                self.assertEqual(revision.topic_ref, TOPIC_REF)
                self.assertEqual(revision.action, action)
                self.assertEqual(revision.previous_topic, seeded_topic)
                expected_next = next(
                    (
                        topic
                        for topic in final_state.portrait_topics
                        if topic.topic_ref == TOPIC_REF
                    ),
                    None,
                )
                self.assertEqual(revision.next_topic, expected_next)
                self.assertEqual(
                    revision.reason,
                    decision.reason if decision.reason is not None else purpose,
                )
                self.assertEqual(
                    revision.decision_digest,
                    portrait_result.result_digest,
                )
                self.assertEqual(
                    revision.changed_at,
                    portrait_proof.skill_use.used_at,
                )
                self.assertEqual(
                    DailyHealthState.from_storage(final_state.to_storage()),
                    final_state,
                )

                if action == "withdraw":
                    current_view = next(
                        view
                        for view in final_state.projection.topic_views
                        if view.topic_ref == TOPIC_REF
                    )
                    self.assertEqual(current_view.status, "unknown")
                    self.assertEqual(current_view.current_understandings, ())
                    self.assertIsNone(revision.next_topic)
                    self.assertEqual(revision.previous_topic, seeded_topic)

    def test_maintain_and_gap_do_not_forge_portrait_revisions(self) -> None:
        seeded, _, seeded_topic = _seeded_state()
        cases = (
            (
                "maintain",
                PortraitDecision.maintain(
                    TOPIC_REF,
                    "current-understanding-remains-supported",
                ),
            ),
            ("gap", PortraitDecision.gap("required-context-unavailable")),
        )
        for action, decision in cases:
            with self.subTest(action=action):
                final_state, _, _ = self.run_portrait_decision(
                    suffix=action,
                    state=seeded,
                    decision=decision,
                    purpose=f"portrait-{action}",
                )
                self.assertTrue(
                    hasattr(final_state, "portrait_revisions"),
                    "DailyHealthState must expose an empty revision ledger",
                )
                self.assertEqual(final_state.portrait_revisions, ())
                self.assertEqual(final_state.portrait_topics, (seeded_topic,))

    def test_inactive_evidence_cannot_be_reused_as_portrait_proof(self) -> None:
        seeded, card, _ = _seeded_state()
        executor = _WithdrawThenReuseProofExecutor(card)
        runtime = self.runtime(executor)
        source = _source("inactive-proof")

        stage = runtime.execute(source, seeded)
        post_stage = seeded.apply_evidence_stage(stage)
        self.assertNotIn(card.evidence_id, post_stage.current_evidence_ids)

        with self.assertRaises(AuthorityValidationError):
            runtime.complete(source, post_stage, stage)
        self.assertIsNotNone(executor.portrait_context)
        assert executor.portrait_context is not None
        self.assertNotIn(card.evidence_id, executor.portrait_context.evidence_ids)


if __name__ == "__main__":
    unittest.main()

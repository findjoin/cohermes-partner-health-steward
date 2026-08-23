import unittest
import json
from dataclasses import replace

from partner_health_steward.coordination import (
    AtomicEvidenceClaim,
    EvidenceCard,
    EvidenceSeriesKey,
    PersonalHealthFields,
)
from partner_health_steward.evidence_profile import PersonalEvidenceProfile
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
    NonDiagnosticContractViolation,
    NonDiagnosticReplyPipeline,
)


def _owner_card() -> EvidenceCard:
    claim = AtomicEvidenceClaim(
        content="主人自述昨晚主观睡眠体验不佳",
        evidence_type="personal-health",
        source_kind="owner-statement",
        occurred_at="2026-08-23",
        applicable_period="2026-08-23-night",
        purpose="sleep-support",
        uncertainty="主人主观体验",
        limitations=("单次陈述不证明趋势",),
        proves=("主人自述昨晚主观睡眠体验不佳",),
        does_not_prove=("长期趋势", "失眠诊断"),
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
    return EvidenceCard.from_claim(
        "ticket113-owner-source",
        claim,
        recorded_at="2026-08-24T00:00:00+00:00",
    )


def _knowledge_release() -> KnowledgeRelease:
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
        content="synthetic general health material",
        published_at="2026-08-24T00:00:00+00:00",
        expires_at="2027-08-24T00:00:00+00:00",
    )
    release = KnowledgePublisher().publish(publication, release_version="2026.08.24")
    if type(release) is not KnowledgeRelease:
        raise AssertionError("synthetic knowledge fixture must publish")
    return release


def _claims() -> tuple[ApprovedClaimAtom, ...]:
    return (
        ApprovedClaimAtom("claim-owner-fact", "owner-fact", "主人事实来自当前证据卡。", "1.0.0"),
        ApprovedClaimAtom("claim-general-knowledge", "general-knowledge", "通用知识来自当前治理知识卡。", "1.0.0"),
        ApprovedClaimAtom("claim-support", "support", "当前材料支持上述有限事实。", "1.0.0"),
        ApprovedClaimAtom("claim-opposition", "opposition", "当前材料也保留其他解释。", "1.0.0"),
        ApprovedClaimAtom("claim-unknown", "unknown", "目前仍有信息未知。", "1.0.0"),
        ApprovedClaimAtom("claim-limitation", "limitation", "这不是诊断或排除结论。", "1.0.0"),
        ApprovedClaimAtom("claim-next-step", "next-step", "如持续或加重，请寻求专业评估。", "1.0.0"),
    )


def _template() -> ApprovedReplyTemplate:
    return ApprovedReplyTemplate(
        template_id="template-nondiagnostic-v1",
        version="1.0.0",
        section_order=(
            "owner-fact", "general-knowledge", "support", "opposition",
            "unknown", "limitation", "next-step",
        ),
    )


def _candidate(owner: EvidenceCard, knowledge: KnowledgeRelease) -> NonDiagnosticCandidate:
    return NonDiagnosticCandidate(
        owner_fact_refs=(CardReference(owner.evidence_id, owner.card_version, "owner-fact"),),
        knowledge_refs=(CardReference(knowledge.release_id, knowledge.release_version, "general-knowledge"),),
        support=("claim-support",),
        opposition=("claim-opposition",),
        unknowns=("claim-unknown",),
        limitations=("claim-limitation",),
        next_steps=("claim-next-step",),
        claim_ids=tuple(claim.atom_id for claim in _claims()),
        template_id="template-nondiagnostic-v1",
    )


def _pipeline(owner: EvidenceCard, knowledge: KnowledgeRelease) -> NonDiagnosticReplyPipeline:
    return NonDiagnosticReplyPipeline(
        current_owner_cards=(owner,),
        current_knowledge_releases=(knowledge,),
        approved_claims=_claims(),
        approved_templates=(_template(),),
    )


class Ticket113NonDiagnosticTests(unittest.TestCase):
    def test_113_a4_c01_current_card_references_are_accepted(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()

        reply = _pipeline(owner, knowledge).render(_candidate(owner, knowledge))

        self.assertEqual(reply.owner_fact_refs[0].card_id, owner.evidence_id)
        self.assertEqual(reply.knowledge_refs[0].card_id, knowledge.release_id)
        self.assertTrue(reply.text)

    def test_113_a4_c02_reference_types_cannot_be_interchanged(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()
        valid = _candidate(owner, knowledge)
        pipeline = _pipeline(owner, knowledge)
        interchanged = (
            NonDiagnosticCandidate(
                owner_fact_refs=(CardReference(knowledge.release_id, knowledge.release_version, "owner-fact"),),
                knowledge_refs=valid.knowledge_refs,
                support=valid.support,
                opposition=valid.opposition,
                unknowns=valid.unknowns,
                limitations=valid.limitations,
                next_steps=valid.next_steps,
                claim_ids=valid.claim_ids,
                template_id=valid.template_id,
            ),
            NonDiagnosticCandidate(
                owner_fact_refs=valid.owner_fact_refs,
                knowledge_refs=(CardReference(owner.evidence_id, owner.card_version, "general-knowledge"),),
                support=valid.support,
                opposition=valid.opposition,
                unknowns=valid.unknowns,
                limitations=valid.limitations,
                next_steps=valid.next_steps,
                claim_ids=valid.claim_ids,
                template_id=valid.template_id,
            ),
        )

        for candidate in interchanged:
            with self.subTest(candidate=candidate):
                with self.assertRaises(NonDiagnosticContractViolation):
                    pipeline.render(candidate)

    def test_113_a4_c03_missing_support_is_rejected(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()

        with self.assertRaises(NonDiagnosticContractViolation):
            _pipeline(owner, knowledge).render(
                replace(_candidate(owner, knowledge), support=())
            )

    def test_113_a4_c04_missing_opposition_is_rejected(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()

        with self.assertRaises(NonDiagnosticContractViolation):
            _pipeline(owner, knowledge).render(
                replace(_candidate(owner, knowledge), opposition=())
            )

    def test_113_a4_c05_missing_unknown_is_rejected(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()

        with self.assertRaises(NonDiagnosticContractViolation):
            _pipeline(owner, knowledge).render(
                replace(_candidate(owner, knowledge), unknowns=())
            )

    def test_113_a4_c06_missing_limitation_is_rejected(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()

        with self.assertRaises(NonDiagnosticContractViolation):
            _pipeline(owner, knowledge).render(
                replace(_candidate(owner, knowledge), limitations=())
            )

    def test_113_a4_c07_stale_card_is_rejected(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()
        valid = _candidate(owner, knowledge)
        stale_candidates = (
            replace(
                valid,
                owner_fact_refs=(CardReference(owner.evidence_id, "evidence-card-v0", "owner-fact"),),
            ),
            replace(
                valid,
                knowledge_refs=(CardReference(knowledge.release_id, "2026.01.01", "general-knowledge"),),
            ),
        )

        for candidate in stale_candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(NonDiagnosticContractViolation):
                    _pipeline(owner, knowledge).render(candidate)

    def test_113_a4_c08_forged_identifier_is_rejected(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()
        valid = _candidate(owner, knowledge)
        forged_candidates = {
            "evidence": replace(
                valid,
                owner_fact_refs=(CardReference("forged-evidence", owner.card_version, "owner-fact"),),
            ),
            "knowledge": replace(
                valid,
                knowledge_refs=(CardReference("forged-knowledge", knowledge.release_version, "general-knowledge"),),
            ),
            "claim": replace(valid, claim_ids=(*valid.claim_ids[:-1], "forged-claim")),
            "template": replace(valid, template_id="forged-template"),
        }

        for kind, candidate in forged_candidates.items():
            with self.subTest(kind=kind):
                with self.assertRaises(NonDiagnosticContractViolation):
                    _pipeline(owner, knowledge).render(candidate)

    def test_113_a5_c01_replay_renders_identical_reply(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()
        pipeline = _pipeline(owner, knowledge)
        candidate = _candidate(owner, knowledge)

        first = pipeline.render(candidate)
        replay = pipeline.render(candidate)

        self.assertEqual(first, replay)
        self.assertEqual(len(first.reply_atoms), 7)
        self.assertIn("这不是诊断或排除结论。", first.text)

    def test_113_a5_c02_render_order_is_stable(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()
        pipeline = _pipeline(owner, knowledge)
        candidate = _candidate(owner, knowledge)

        canonical = pipeline.render(candidate)
        reordered = pipeline.render(
            replace(candidate, claim_ids=tuple(reversed(candidate.claim_ids)))
        )

        self.assertEqual(canonical.text, reordered.text)
        self.assertEqual(
            tuple(atom.kind for atom in canonical.reply_atoms),
            ("direct-result",) * 5 + ("limitation", "next-step"),
        )

    def test_113_a5_c03_illegal_medical_atom_cannot_be_constructed(self) -> None:
        for forbidden in (
            "disease-ranking",
            "diagnosis-label",
            "disease-exclusion",
            "individual-prescription-adjustment",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(NonDiagnosticContractViolation):
                    ApprovedReplyTemplate(
                        "forbidden-template",
                        "1.0.0",
                        ("owner-fact", forbidden),
                    )

    def test_113_a5_c04_illegal_medical_atom_cannot_be_parsed(self) -> None:
        with self.assertRaises(NonDiagnosticContractViolation):
            ApprovedReplyTemplate.from_wire(
                {
                    "template_id": "forbidden-template",
                    "version": "1.0.0",
                    "section_order": ["owner-fact", "diagnosis-label"],
                }
            )

    def test_113_a5_c05_candidate_is_not_persisted(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()
        candidate = _candidate(owner, knowledge)
        pipeline = _pipeline(owner, knowledge)

        reply = pipeline.render(candidate)
        commit_wire = reply.to_commit_wire()
        encoded = json.dumps(commit_wire, ensure_ascii=False, sort_keys=True)

        self.assertEqual(
            set(commit_wire),
            {"owner_reply", "reply_atoms", "owner_fact_refs", "knowledge_refs"},
        )
        for forbidden_field in (
            "support", "opposition", "unknowns", "limitations",
            "next_steps", "claim_ids", "template_id",
        ):
            self.assertNotIn(f'"{forbidden_field}"', encoded)
        self.assertFalse(any(value is candidate for value in vars(pipeline).values()))

    def test_113_a5_c08_owner_and_general_knowledge_boundaries_remain_visible(self) -> None:
        owner = _owner_card()
        knowledge = _knowledge_release()

        reply = _pipeline(owner, knowledge).render(_candidate(owner, knowledge))

        owner_line, knowledge_line, *_ = reply.text.splitlines()
        self.assertIn(owner.evidence_id, owner_line)
        self.assertNotIn(knowledge.release_id, owner_line)
        self.assertIn(knowledge.release_id, knowledge_line)
        self.assertNotIn(owner.evidence_id, knowledge_line)
        self.assertEqual(reply.owner_fact_refs[0].role, "owner-fact")
        self.assertEqual(reply.knowledge_refs[0].role, "general-knowledge")


if __name__ == "__main__":
    unittest.main()

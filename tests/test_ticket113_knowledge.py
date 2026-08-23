import unittest
from dataclasses import replace

from partner_health_steward.knowledge import (
    ImmutableKnowledgeRegistry,
    KnowledgeContractViolation,
    KnowledgeGap,
    KnowledgePublicationInput,
    KnowledgePublisher,
    KnowledgeRelease,
)
from tests.ticket113_deny_network import DenyBypassHarness


def _publication() -> KnowledgePublicationInput:
    return KnowledgePublicationInput(
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


class Ticket113KnowledgeTests(unittest.TestCase):
    def test_113_a3_c01_publication_is_owner_independent(self) -> None:
        publisher = KnowledgePublisher()

        first = publisher.publish(_publication(), release_version="2026.08.24")
        replay = publisher.publish(_publication(), release_version="2026.08.24")

        self.assertIsInstance(first, KnowledgeRelease)
        self.assertEqual(first, replay)
        self.assertEqual(first.topic_id, "sleep-general")
        self.assertNotIn("owner", first.to_wire())

    def test_113_a3_c02_content_hash_is_immutable(self) -> None:
        release = KnowledgePublisher().publish(_publication(), release_version="2026.08.24")
        registry = ImmutableKnowledgeRegistry()
        registry.stage(release)

        with self.assertRaises(KnowledgeContractViolation):
            registry.stage(replace(release, content_hash="sha256:" + "f" * 64))

    def test_113_a3_c03_release_version_is_immutable(self) -> None:
        publisher = KnowledgePublisher()
        original = publisher.publish(_publication(), release_version="2026.08.24")
        revised = publisher.publish(
            replace(_publication(), content="different governed content"),
            release_version="2026.08.24",
        )
        registry = ImmutableKnowledgeRegistry()
        registry.stage(original)

        with self.assertRaises(KnowledgeContractViolation):
            registry.stage(revised)

    def test_113_a3_c04_expired_release_returns_gap(self) -> None:
        release = KnowledgePublisher().publish(_publication(), release_version="2026.08.24")
        registry = ImmutableKnowledgeRegistry()
        registry.stage(release)

        result = registry.resolve("sleep-general", at="2027-08-24T00:00:00+00:00")

        self.assertIsInstance(result, KnowledgeGap)
        self.assertEqual(result.reason_code, "knowledge-expired")

    def test_113_a3_c05_withdrawn_release_returns_gap(self) -> None:
        release = KnowledgePublisher().publish(_publication(), release_version="2026.08.24")
        registry = ImmutableKnowledgeRegistry()
        registry.stage(replace(release, withdrawn=True))

        result = registry.resolve("sleep-general", at="2026-08-25T00:00:00+00:00")

        self.assertIsInstance(result, KnowledgeGap)
        self.assertEqual(result.reason_code, "knowledge-withdrawn")

    def test_113_a3_c06_rights_gap_blocks_release(self) -> None:
        result = KnowledgePublisher().publish(
            replace(_publication(), rights_status="rights-unconfirmed"),
            release_version="2026.08.24",
        )

        self.assertIsInstance(result, KnowledgeGap)
        self.assertEqual(result.reason_code, "knowledge-rights-gap")

    def test_113_a3_c07_chinese_status_gap_blocks_release(self) -> None:
        result = KnowledgePublisher().publish(
            replace(_publication(), chinese_status="translation-unreviewed"),
            release_version="2026.08.24",
        )

        self.assertIsInstance(result, KnowledgeGap)
        self.assertEqual(result.reason_code, "knowledge-chinese-gap")

    def test_113_a3_c08_professional_review_gap_blocks_release(self) -> None:
        result = KnowledgePublisher().publish(
            replace(_publication(), professional_review_status="pending"),
            release_version="2026.08.24",
        )

        self.assertIsInstance(result, KnowledgeGap)
        self.assertEqual(result.reason_code, "knowledge-review-gap")

    def test_113_a3_c11_missing_knowledge_never_fetches_on_demand(self) -> None:
        registry = ImmutableKnowledgeRegistry()

        with DenyBypassHarness() as harness:
            result = registry.resolve("missing-topic", at="2026-08-25T00:00:00+00:00")

        self.assertIsInstance(result, KnowledgeGap)
        self.assertEqual(result.reason_code, "knowledge-missing")
        self.assertEqual(harness.attempts, [])


if __name__ == "__main__":
    unittest.main()

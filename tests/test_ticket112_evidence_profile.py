from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.evidence_profile import (
    EVIDENCE_PROFILE_SCHEMA_VERSION,
    AuthoritativeKnowledgeProfile,
    PersonalEvidenceProfile,
    TaskProcessProfile,
    profile_for_authoritative_knowledge,
    profile_for_personal,
    profile_for_task_process,
    profile_from_wire,
)


class Ticket112EvidenceProfileTests(unittest.TestCase):
    def test_personal_measurement_profile_is_immutable_and_stable(self) -> None:
        profile = profile_for_personal(
            observation_basis="measurement",
            measurement_method="wrist actigraphy",
            measurement_unit="minute",
        )

        self.assertEqual(profile.kind, "personal-health")
        self.assertEqual(
            profile.digest,
            "sha256:5dbb6cb05734ec9b717e1ce039617e3512851248f62149534bee22646af966cf",
        )
        self.assertEqual(profile_from_wire(profile.to_wire()), profile)
        self.assertEqual(hash(profile_from_wire(profile.to_wire())), hash(profile))
        with self.assertRaises(FrozenInstanceError):
            setattr(profile, "measurement_unit", "hour")

    def test_measurement_requires_both_method_and_unit(self) -> None:
        for method, unit in ((None, "minute"), ("wrist actigraphy", None)):
            with self.subTest(method=method, unit=unit):
                with self.assertRaises(AuthorityValidationError):
                    PersonalEvidenceProfile(
                        observation_basis="measurement",
                        measurement_method=method,
                        measurement_unit=unit,
                    )

    def test_non_measurement_basis_forbids_measurement_fields(self) -> None:
        for basis in ("owner-statement", "reported-clinician-conclusion"):
            with self.subTest(basis=basis):
                profile = profile_for_personal(observation_basis=basis)
                self.assertIsNone(profile.measurement_method)
                self.assertIsNone(profile.measurement_unit)
                with self.assertRaises(AuthorityValidationError):
                    profile_for_personal(
                        observation_basis=basis,
                        measurement_method="manual timing",
                        measurement_unit="minute",
                    )

    def test_authoritative_knowledge_profile_carries_source_applicability(self) -> None:
        profile = profile_for_authoritative_knowledge(
            publisher="World Health Organization",
            applicable_population="adults aged 18 years and older",
            validity_boundary="general sleep guidance; not an individual diagnosis",
            source_nature="intergovernmental clinical guidance",
        )

        self.assertIsInstance(profile, AuthoritativeKnowledgeProfile)
        self.assertEqual(profile.kind, "authoritative-knowledge")
        self.assertEqual(profile_from_wire(profile.to_wire()), profile)

    def test_task_process_profile_carries_ledger_and_controlled_fact_kind(self) -> None:
        for fact_kind in ("stage", "delivery", "acceptance"):
            with self.subTest(fact_kind=fact_kind):
                profile = profile_for_task_process(
                    task_id="task-sleep-review-001",
                    process_fact_kind=fact_kind,
                    ledger_ref="health-task-ledger/revision-17",
                    source_nature="authoritative task transition receipt",
                )
                self.assertIsInstance(profile, TaskProcessProfile)
                self.assertEqual(profile.kind, "task-process")
                self.assertEqual(profile_from_wire(profile.to_wire()), profile)

        with self.assertRaises(AuthorityValidationError):
            profile_for_task_process(
                task_id="task-sleep-review-001",
                process_fact_kind="solved",
                ledger_ref="health-task-ledger/revision-17",
                source_nature="task label",
            )

    def test_wire_rejects_extra_or_missing_fields_at_every_level(self) -> None:
        profile = profile_for_personal(observation_basis="owner-statement")

        extra_outer = profile.to_wire()
        extra_outer["future_extension"] = True
        with self.assertRaises(AuthorityValidationError):
            profile_from_wire(extra_outer)

        extra_nested = profile.to_wire()
        assert type(extra_nested["fields"]) is dict
        extra_nested["fields"]["measurement_device"] = "watch"
        with self.assertRaises(AuthorityValidationError):
            profile_from_wire(extra_nested)

        missing_nested = profile.to_wire()
        assert type(missing_nested["fields"]) is dict
        del missing_nested["fields"]["measurement_unit"]
        with self.assertRaises(AuthorityValidationError):
            profile_from_wire(missing_nested)

    def test_wire_kind_cannot_reinterpret_another_profile_type(self) -> None:
        personal_wire = profile_for_personal(
            observation_basis="measurement",
            measurement_method="validated cuff",
            measurement_unit="mmHg",
        ).to_wire()
        personal_wire["kind"] = "task-process"

        with self.assertRaises(AuthorityValidationError):
            profile_from_wire(personal_wire)

    def test_wire_rejects_digest_or_schema_forgery(self) -> None:
        profile = profile_for_authoritative_knowledge(
            publisher="National institute",
            applicable_population="adults",
            validity_boundary="population guidance only",
            source_nature="evidence-based guideline",
        )

        forged_digest = profile.to_wire()
        forged_digest["digest"] = "sha256:" + ("0" * 64)
        with self.assertRaises(AuthorityValidationError):
            profile_from_wire(forged_digest)

        forged_schema = profile.to_wire()
        forged_schema["schema_version"] = EVIDENCE_PROFILE_SCHEMA_VERSION + "-future"
        with self.assertRaises(AuthorityValidationError):
            profile_from_wire(forged_schema)

    def test_blank_physical_meaning_fields_are_rejected(self) -> None:
        with self.assertRaises(AuthorityValidationError):
            profile_for_authoritative_knowledge(
                publisher=" ",
                applicable_population="adults",
                validity_boundary="general guidance only",
                source_nature="clinical guideline",
            )
        with self.assertRaises(AuthorityValidationError):
            profile_for_task_process(
                task_id="task-1",
                process_fact_kind="stage",
                ledger_ref="task-ledger/revision-2",
                source_nature=" delivery receipt ",
            )


if __name__ == "__main__":
    unittest.main()

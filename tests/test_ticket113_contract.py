import importlib
import unittest
from dataclasses import FrozenInstanceError

from partner_health_steward.initialization import stable_digest
from tests.ticket113_case_registry import CASE_REGISTRY, CONTRACT_CASE_IDS


def _modules():
    return (
        importlib.import_module("partner_health_steward.model_contract"),
        importlib.import_module("partner_health_steward.knowledge"),
        importlib.import_module("partner_health_steward.nondiagnostic"),
    )


def _route_wire() -> dict[str, object]:
    return {
        "route_id": "partner-first-hop",
        "provider": "synthetic-provider",
        "canonical_base_url": "https://model.example/v1",
        "api_mode": "responses",
        "requested_model": "synthetic-health-model",
        "configuration_generation": 7,
        "owner_consent_fingerprint": "sha256:" + "a" * 64,
    }


def _profile_wire() -> dict[str, object]:
    return {
        "profile_id": "synthetic-profile",
        "profile_version": "1.0.0",
        "synthetic": True,
        "route_id": "partner-first-hop",
        "provider": "synthetic-provider",
        "canonical_base_url": "https://model.example/v1",
        "api_mode": "responses",
        "requested_model": "synthetic-health-model",
        "allowed_actual_models": ["synthetic-health-model", "synthetic-health-model-alias"],
        "configuration_generation": 7,
        "input_measurement_method": "synthetic-utf8-byte-upper-bound-v1",
        "fixed_wrapper_tokens": 96,
        "output_reservation_tokens": 512,
        "common_context_lower_bound_tokens": 4096,
        "evidence_refs": ["synthetic-contract-evidence"],
        "invalidation_conditions": ["route-change", "measurement-method-change"],
    }


def _request_wire() -> dict[str, object]:
    return {
        "route": _route_wire(),
        "capability_profile": _profile_wire(),
        "messages": [
            {"role": "system", "content": "synthetic policy"},
            {"role": "user", "content": "synthetic health question"},
        ],
        "final_input_digest": stable_digest(
            {"messages": [
                {"role": "system", "content": "synthetic policy"},
                {"role": "user", "content": "synthetic health question"},
            ]}
        ),
        "final_input_upper_bound_tokens": 3000,
        "output_reservation_tokens": 512,
        "strict_schema_name": "nondiagnostic-candidate-v1",
        "strict_schema_digest": "sha256:" + "b" * 64,
    }


def _candidate_wire() -> dict[str, object]:
    return {
        "owner_fact_refs": [
            {"card_id": "personal-1", "version": "v1", "role": "owner-fact"}
        ],
        "knowledge_refs": [
            {"card_id": "knowledge-1", "version": "v1", "role": "general-knowledge"}
        ],
        "support": ["claim-support"],
        "opposition": ["claim-opposition"],
        "unknowns": ["claim-unknown"],
        "limitations": ["claim-limitation"],
        "next_steps": ["claim-next-step"],
        "claim_ids": [
            "claim-owner-fact", "claim-general-knowledge", "claim-support",
            "claim-opposition", "claim-unknown", "claim-limitation", "claim-next-step",
        ],
        "template_id": "template-nondiagnostic-v1",
    }


class Ticket113ContractTests(unittest.TestCase):
    def test_case_registry_is_ordered_unique_and_points_to_visible_tests(self) -> None:
        case_ids = tuple(item[0] for item in CASE_REGISTRY)
        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertEqual(case_ids[0], "113-A1-C01")
        self.assertEqual(case_ids[-1], "113-A6-C08")
        self.assertTrue(CONTRACT_CASE_IDS < set(case_ids))
        self.assertTrue(all(value.startswith("test_ticket113_") for _, value, _ in CASE_REGISTRY))

    def test_113_a1_c08_request_contract_binds_exact_final_wire_authority(self) -> None:
        model, _, _ = _modules()
        request = model.StrictModelRequest.from_wire(_request_wire())
        self.assertEqual(request.to_wire(), _request_wire())
        for field in _request_wire():
            with self.subTest(missing=field):
                malformed = _request_wire()
                malformed.pop(field)
                with self.assertRaises(model.ModelContractViolation):
                    model.StrictModelRequest.from_wire(malformed)
        malformed = _request_wire()
        malformed["unbound_transport"] = "forbidden"
        with self.assertRaises(model.ModelContractViolation):
            model.StrictModelRequest.from_wire(malformed)

    def test_113_a2_c09_transport_result_contract_preserves_four_terminal_states(self) -> None:
        model, _, _ = _modules()
        base = {
            "response_id": "synthetic-response",
            "requested_model": "synthetic-health-model",
            "actual_model": "synthetic-health-model",
            "status": "completed",
            "incomplete_reason": None,
            "failure_reason": None,
            "usage_input_tokens": 100,
            "usage_output_tokens": 50,
            "fallback_observed": False,
            "truncated": False,
            "terminal_proven": True,
            "structured_output": _candidate_wire(),
        }
        for status, reason_field in (
            ("completed", None),
            ("incomplete", "incomplete_reason"),
            ("failed", "failure_reason"),
            ("unknown", None),
        ):
            with self.subTest(status=status):
                wire = dict(base)
                wire["status"] = status
                wire["structured_output"] = _candidate_wire() if status == "completed" else None
                wire["terminal_proven"] = status != "unknown"
                if reason_field is not None:
                    wire[reason_field] = status + "-reason"
                result = model.ModelTransportResult.from_wire(wire)
                self.assertEqual(result.status, status)
                self.assertEqual(result.to_wire(), wire)
        malformed = dict(base)
        malformed["status"] = "stop"
        with self.assertRaises(model.ModelContractViolation):
            model.ModelTransportResult.from_wire(malformed)

    def test_113_a3_c09_publication_input_rejects_owner_derived_fields(self) -> None:
        _, knowledge, _ = _modules()
        valid = {
            "topic_id": "sleep-general",
            "governance_schedule_id": "fixed-quarterly-v1",
            "source_id": "source-guideline",
            "source_version": "2026-01",
            "rights_status": "approved",
            "chinese_status": "reviewed-chinese",
            "applicability": ["general-adult-health-education"],
            "professional_review_status": "approved",
            "professional_review_ref": "synthetic-review-ref",
            "content": "synthetic general health material",
            "published_at": "2026-08-24T00:00:00+00:00",
            "expires_at": "2027-08-24T00:00:00+00:00",
        }
        publication = knowledge.KnowledgePublicationInput.from_wire(valid)
        self.assertEqual(publication.to_wire(), valid)
        for owner_field in ("owner_id", "owner_question", "portrait_digest", "task_id"):
            with self.subTest(owner_field=owner_field):
                malformed = dict(valid)
                malformed[owner_field] = "forbidden-owner-derived-value"
                with self.assertRaises(knowledge.KnowledgeContractViolation):
                    knowledge.KnowledgePublicationInput.from_wire(malformed)

    def test_113_a3_c10_release_contract_is_strict_and_frozen(self) -> None:
        _, knowledge, _ = _modules()
        wire = {
            "release_id": "knowledge-release:synthetic",
            "release_version": "2026.08.24",
            "stage": "staged",
            "topic_id": "sleep-general",
            "source_id": "source-guideline",
            "source_version": "2026-01",
            "rights_status": "approved",
            "chinese_status": "reviewed-chinese",
            "applicability": ["general-adult-health-education"],
            "professional_review_status": "approved",
            "professional_review_ref": "synthetic-review-ref",
            "content_hash": "sha256:" + "c" * 64,
            "published_at": "2026-08-24T00:00:00+00:00",
            "expires_at": "2027-08-24T00:00:00+00:00",
            "withdrawn": False,
        }
        release = knowledge.KnowledgeRelease.from_wire(wire)
        self.assertEqual(release.to_wire(), wire)
        with self.assertRaises(FrozenInstanceError):
            release.release_version = "changed"  # type: ignore[misc]
        malformed = dict(wire)
        malformed["owner_id"] = "forbidden"
        with self.assertRaises(knowledge.KnowledgeContractViolation):
            knowledge.KnowledgeRelease.from_wire(malformed)

    def test_113_a4_c09_candidate_contract_forbids_model_draft_text(self) -> None:
        _, _, nondiagnostic = _modules()
        candidate = nondiagnostic.NonDiagnosticCandidate.from_wire(_candidate_wire())
        self.assertEqual(candidate.to_wire(), _candidate_wire())
        malformed = _candidate_wire()
        malformed["draft_text"] = "model-authored final reply"
        with self.assertRaises(nondiagnostic.NonDiagnosticContractViolation):
            nondiagnostic.NonDiagnosticCandidate.from_wire(malformed)

    def test_113_a5_c06_claim_atom_contract_excludes_medical_conclusions(self) -> None:
        _, _, nondiagnostic = _modules()
        atom = nondiagnostic.ApprovedClaimAtom(
            atom_id="claim-owner-fact",
            kind="owner-fact",
            text="主人资料显示：{owner_fact}。",
            version="1.0.0",
        )
        self.assertEqual(atom.kind, "owner-fact")
        for forbidden in (
            "disease-ranking",
            "diagnosis-label",
            "disease-exclusion",
            "individual-prescription-adjustment",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(nondiagnostic.NonDiagnosticContractViolation):
                    nondiagnostic.ApprovedClaimAtom(
                        atom_id="forbidden-atom",
                        kind=forbidden,
                        text="forbidden",
                        version="1.0.0",
                    )

    def test_113_a5_c07_claim_atom_parser_rejects_illegal_kind(self) -> None:
        _, _, nondiagnostic = _modules()
        with self.assertRaises(nondiagnostic.NonDiagnosticContractViolation):
            nondiagnostic.ApprovedClaimAtom.from_wire(
                {
                    "atom_id": "forbidden-atom",
                    "kind": "diagnosis-label",
                    "text": "forbidden",
                    "version": "1.0.0",
                }
            )


if __name__ == "__main__":
    unittest.main()

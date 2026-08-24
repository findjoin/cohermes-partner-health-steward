from __future__ import annotations

import hashlib
import importlib
import unittest
from typing import Any


STATUS = importlib.import_module("partner_health_steward.status")

_NOW_UTC = "2026-08-24T12:00:00+00:00"
_VALID_UNTIL_UTC = "2026-08-25T00:00:00+00:00"
_GENERATION = 7
_SIGNING_KEY = b"ticket-114-status-authority-key"

_CORE_PRODUCERS = {
    domain: f"health-core.status.{domain}"
    for domain in STATUS.CORE_STATUS_DOMAINS
}
_CORE_CONTRACTS = {
    domain: f"{domain}-fact-v1"
    for domain in STATUS.CORE_STATUS_DOMAINS
}
_OPTIONAL_PRODUCER = "health-core.status.optional-delivery"
_OPTIONAL_CONTRACT = "optional-delivery-fact-v1"
_UNEXPECTED_PRODUCER = "health-core.status.unexpected-entry"
_UNEXPECTED_CONTRACT = "unexpected-entry-fact-v1"


class Ticket114BusinessStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        producer_contracts = {
            _CORE_PRODUCERS[domain]: _CORE_CONTRACTS[domain]
            for domain in STATUS.CORE_STATUS_DOMAINS
        }
        producer_contracts[_OPTIONAL_PRODUCER] = _OPTIONAL_CONTRACT
        producer_contracts[_UNEXPECTED_PRODUCER] = _UNEXPECTED_CONTRACT
        self.authority = STATUS.CapabilityFactAuthority(
            authority_id="synthetic-ticket114-status-authority",
            signing_key=_SIGNING_KEY,
            producer_contracts=producer_contracts,
        )
        self.core_facts = tuple(
            self._seal_core(domain)
            for domain in STATUS.CORE_STATUS_DOMAINS
        )

    @staticmethod
    def _digest(*parts: object) -> str:
        material = "|".join(str(part) for part in parts).encode("utf-8")
        return "sha256:" + hashlib.sha256(material).hexdigest()

    def _seal(
        self,
        *,
        domain: str,
        requiredness: str,
        state: str,
        generation: int,
        producer_id: str,
        producer_contract_version: str,
        suffix: str,
        valid_until_utc: str = _VALID_UNTIL_UTC,
        authority: Any | None = None,
    ) -> Any:
        signer = self.authority if authority is None else authority
        return signer.seal(
            domain=domain,
            requiredness=requiredness,
            state=state,
            generation=generation,
            revision_digest=self._digest(
                domain,
                requiredness,
                state,
                generation,
                producer_id,
                producer_contract_version,
                suffix,
            ),
            transition_id=(
                f"status-fact:{domain}:{producer_id}:generation-{generation}:{suffix}"
            ),
            producer_id=producer_id,
            producer_contract_version=producer_contract_version,
            evidence_refs=(f"status-evidence:{domain}:{suffix}",),
            valid_until_utc=valid_until_utc,
        )

    def _seal_core(
        self,
        domain: str,
        *,
        state: str = "confirmed-ok",
        generation: int = _GENERATION,
        suffix: str = "current",
        valid_until_utc: str = _VALID_UNTIL_UTC,
        authority: Any | None = None,
    ) -> Any:
        return self._seal(
            domain=domain,
            requiredness="core",
            state=state,
            generation=generation,
            producer_id=_CORE_PRODUCERS[domain],
            producer_contract_version=_CORE_CONTRACTS[domain],
            suffix=suffix,
            valid_until_utc=valid_until_utc,
            authority=authority,
        )

    @staticmethod
    def _manifest_fact(
        facts: tuple[Any, ...],
        *,
        domain: str,
        producer_id: str,
    ) -> Any:
        matches = tuple(
            fact
            for fact in facts
            if getattr(fact, "domain", None) == domain
            and getattr(fact, "producer_id", None) == producer_id
        )
        if len(matches) != 1:
            raise AssertionError("status fixture requires one manifest fact")
        return matches[0]

    def _requirements(
        self,
        *,
        current_facts: tuple[Any, ...] | None = None,
        include_optional: bool = False,
    ) -> tuple[Any, ...]:
        requirement_type = STATUS.CapabilityRequirement
        manifest_facts = self.core_facts if current_facts is None else current_facts
        requirements = tuple(
            requirement_type(
                domain=domain,
                requiredness="core",
                producer_id=_CORE_PRODUCERS[domain],
                producer_contract_version=_CORE_CONTRACTS[domain],
                expected_generation=_GENERATION,
                expected_revision_digest=self._manifest_fact(
                    manifest_facts,
                    domain=domain,
                    producer_id=_CORE_PRODUCERS[domain],
                ).revision_digest,
                expected_transition_id=self._manifest_fact(
                    manifest_facts,
                    domain=domain,
                    producer_id=_CORE_PRODUCERS[domain],
                ).transition_id,
            )
            for domain in STATUS.CORE_STATUS_DOMAINS
        )
        if not include_optional:
            return requirements
        return requirements + (
            requirement_type(
                domain="delivery",
                requiredness="non-core",
                producer_id=_OPTIONAL_PRODUCER,
                producer_contract_version=_OPTIONAL_CONTRACT,
                expected_generation=_GENERATION,
                expected_revision_digest=self._manifest_fact(
                    manifest_facts,
                    domain="delivery",
                    producer_id=_OPTIONAL_PRODUCER,
                ).revision_digest,
                expected_transition_id=self._manifest_fact(
                    manifest_facts,
                    domain="delivery",
                    producer_id=_OPTIONAL_PRODUCER,
                ).transition_id,
            ),
        )

    def _projector(
        self,
        *,
        current_facts: tuple[Any, ...] | None = None,
        include_optional: bool = False,
    ) -> Any:
        return STATUS.StatusProjector(
            authority=self.authority,
            requirements=self._requirements(
                current_facts=current_facts,
                include_optional=include_optional,
            ),
        )

    @staticmethod
    def _replace_core(
        facts: tuple[Any, ...],
        domain: str,
        replacement: Any,
    ) -> tuple[Any, ...]:
        return tuple(
            replacement
            if getattr(fact, "domain", None) == domain
            and getattr(fact, "requiredness", None) == "core"
            else fact
            for fact in facts
        )

    @staticmethod
    def _project(projector: Any, facts: tuple[Any, ...]) -> Any:
        return projector.project(facts, evaluated_at_utc=_NOW_UTC)

    def test_114_a5_c01_active_truth_table(self) -> None:
        projector = self._projector()

        projection = self._project(projector, self.core_facts)

        self.assertEqual(projection.state, "active")
        self.assertEqual(projection.affected_core_domains, ())

    def test_114_a5_c02_abnormal_truth_table(self) -> None:
        task_fault = self._seal_core(
            "tasks", state="confirmed-fault", suffix="confirmed-fault"
        )
        head_unknown = self._seal_core(
            "current_head", state="unknown", suffix="authority-unknown"
        )
        facts = self._replace_core(self.core_facts, "tasks", task_fault)
        facts = self._replace_core(facts, "current_head", head_unknown)
        projector = self._projector(current_facts=facts)

        projection = self._project(projector, facts)

        self.assertEqual(projection.state, "abnormal")
        self.assertIn("tasks", projection.affected_core_domains)
        self.assertIn("current_head", projection.affected_core_domains)

    def test_114_a5_c03_cannot_confirm_truth_table(self) -> None:
        unknown = self._seal_core(
            "current_head", state="unknown", suffix="cannot-confirm"
        )
        facts = self._replace_core(self.core_facts, "current_head", unknown)
        projector = self._projector(current_facts=facts)

        projection = self._project(projector, facts)

        self.assertEqual(projection.state, "cannot-confirm")
        self.assertIn("current_head", projection.affected_core_domains)

    def test_114_a5_c04_forged_envelope_cannot_activate(self) -> None:
        projector = self._projector()
        attacker = STATUS.CapabilityFactAuthority(
            authority_id=self.authority.authority_id,
            signing_key=b"ticket-114-attacker-signing-key",
            producer_contracts={
                _CORE_PRODUCERS["entry"]: _CORE_CONTRACTS["entry"]
            },
        )
        forged = self._seal_core("entry", authority=attacker, suffix="forged")
        facts = self._replace_core(self.core_facts, "entry", forged)
        self.assertTrue(attacker.verify(forged))
        self.assertFalse(self.authority.verify(forged))

        projection = self._project(projector, facts)

        self.assertEqual(projection.state, "cannot-confirm")
        self.assertIn("entry", projection.affected_core_domains)

    def test_114_a5_c05_stale_or_old_generation_envelope_cannot_activate(self) -> None:
        projector = self._projector()
        cases = (
            (
                "old-generation",
                (
                    self._seal_core(
                        "controls",
                        generation=_GENERATION - 1,
                        suffix="old-generation",
                    ),
                ),
            ),
            (
                "unexpected-future-generation",
                (
                    self._seal_core(
                        "controls",
                        generation=_GENERATION + 1,
                        suffix="future-generation",
                    ),
                ),
            ),
            (
                "same-generation-revision-conflict",
                (
                    self._seal_core("controls", suffix="conflict-a"),
                    self._seal_core("controls", suffix="conflict-b"),
                ),
            ),
        )
        for label, replacements in cases:
            with self.subTest(label=label):
                facts = tuple(
                    fact
                    for fact in self.core_facts
                    if getattr(fact, "domain", None) != "controls"
                ) + replacements

                projection = self._project(projector, facts)

                self.assertEqual(projection.state, "cannot-confirm")
                self.assertIn("controls", projection.affected_core_domains)

    def test_114_a5_c06_unknown_domain_or_producer_cannot_activate(self) -> None:
        projector = self._projector()
        unexpected_producer = self._seal(
            domain="entry",
            requiredness="core",
            state="confirmed-ok",
            generation=_GENERATION,
            producer_id=_UNEXPECTED_PRODUCER,
            producer_contract_version=_UNEXPECTED_CONTRACT,
            suffix="unexpected-producer",
        )
        raw_unknown_domain = self._seal_core("entry").to_wire()
        raw_unknown_domain["domain"] = "heartbeat"
        cases = (
            ("unexpected-producer", self.core_facts + (unexpected_producer,)),
            ("raw-unknown-domain", self.core_facts + (raw_unknown_domain,)),
        )
        for label, facts in cases:
            with self.subTest(label=label):
                projection = self._project(projector, facts)
                self.assertEqual(projection.state, "cannot-confirm")

    def test_114_a5_c07_expired_envelope_cannot_activate(self) -> None:
        for valid_until_utc in (
            _NOW_UTC,
            "2026-08-24T11:59:59+00:00",
        ):
            with self.subTest(valid_until_utc=valid_until_utc):
                expired = self._seal_core(
                    "keys_state",
                    suffix="expired",
                    valid_until_utc=valid_until_utc,
                )
                facts = self._replace_core(self.core_facts, "keys_state", expired)
                projector = self._projector(current_facts=facts)

                projection = self._project(projector, facts)

                self.assertEqual(projection.state, "cannot-confirm")
                self.assertIn("keys_state", projection.affected_core_domains)

    def test_114_a5_c08_missing_future_producer_cannot_activate(self) -> None:
        projector = self._projector()
        for missing_domain in ("tasks", "delivery"):
            with self.subTest(missing_domain=missing_domain):
                facts = tuple(
                    fact
                    for fact in self.core_facts
                    if getattr(fact, "domain", None) != missing_domain
                )

                projection = self._project(projector, facts)

                self.assertEqual(projection.state, "cannot-confirm")
                self.assertIn(missing_domain, projection.affected_core_domains)

    def test_114_a5_c09_last_diagnostic_scope_invalid_is_abnormal(self) -> None:
        last_scope_lost = self._seal_core(
            "diagnostic_scope",
            state="confirmed-fault",
            suffix="last-scope-invalid",
        )
        facts = self._replace_core(
            self.core_facts, "diagnostic_scope", last_scope_lost
        )
        projector = self._projector(current_facts=facts)

        projection = self._project(projector, facts)

        self.assertEqual(projection.state, "abnormal")
        self.assertIn("diagnostic_scope", projection.affected_core_domains)

    def test_114_a5_c10_single_isolated_noncore_fault_remains_active(self) -> None:
        isolated = self._seal(
            domain="delivery",
            requiredness="non-core",
            state="isolated",
            generation=_GENERATION,
            producer_id=_OPTIONAL_PRODUCER,
            producer_contract_version=_OPTIONAL_CONTRACT,
            suffix="isolated-optional-delivery",
        )
        facts = self.core_facts + (isolated,)
        projector = self._projector(
            current_facts=facts,
            include_optional=True,
        )

        projection = self._project(projector, facts)

        self.assertEqual(projection.state, "active")
        self.assertEqual(projection.affected_core_domains, ())
        self.assertIn("delivery", projection.isolated_noncore_domains)

    def test_114_a5_c11_identical_fact_replay_is_deterministic_and_emits_no_second_transition(self) -> None:
        active_projector = self._projector()
        active = self._project(active_projector, self.core_facts)
        task_fault = self._seal_core(
            "tasks", state="confirmed-fault", suffix="transition-to-abnormal"
        )
        abnormal_facts = self._replace_core(self.core_facts, "tasks", task_fault)
        abnormal_projector = self._projector(current_facts=abnormal_facts)
        abnormal = self._project(abnormal_projector, abnormal_facts)
        first_transition = abnormal_projector.transition(active, abnormal)

        replayed = self._project(
            abnormal_projector,
            tuple(reversed(abnormal_facts)) + (abnormal_facts[0],),
        )
        deterministic_transition = abnormal_projector.transition(active, replayed)
        replay_transition = abnormal_projector.transition(abnormal, replayed)

        self.assertEqual(replayed, abnormal)
        self.assertIsNotNone(first_transition)
        self.assertIsNotNone(deterministic_transition)
        self.assertEqual(
            first_transition.transition_id,
            deterministic_transition.transition_id,
        )
        self.assertEqual(first_transition.previous_state, "active")
        self.assertEqual(first_transition.current_state, "abnormal")
        self.assertIsNone(replay_transition)

    def test_114_a5_c13_same_generation_superseded_signed_revision_cannot_activate(self) -> None:
        projector = self._projector()
        superseded = self._seal_core(
            "controls",
            generation=_GENERATION,
            suffix="superseded-same-generation-revision",
        )
        self.assertTrue(self.authority.verify(superseded))
        facts = self._replace_core(self.core_facts, "controls", superseded)

        projection = self._project(projector, facts)

        self.assertEqual(projection.state, "cannot-confirm")
        self.assertIn("controls", projection.affected_core_domains)
        self.assertIn(
            f"controls:{_CORE_PRODUCERS['controls']}:current-revision-mismatch",
            projection.reason_codes,
        )

    def test_114_a5_c14_future_generation_envelope_cannot_activate(self) -> None:
        projector = self._projector()
        future = self._seal_core(
            "controls",
            generation=_GENERATION + 1,
            suffix="future-generation-independent-case",
        )
        facts = self._replace_core(self.core_facts, "controls", future)

        projection = self._project(projector, facts)

        self.assertEqual(projection.state, "cannot-confirm")
        self.assertIn(
            f"controls:{_CORE_PRODUCERS['controls']}:generation-mismatch",
            projection.reason_codes,
        )

    def test_114_a5_c15_same_generation_conflicting_revisions_cannot_activate(self) -> None:
        projector = self._projector()
        conflicting = self._seal_core(
            "controls",
            generation=_GENERATION,
            suffix="conflicting-current-generation-revision",
        )
        facts = self.core_facts + (conflicting,)

        projection = self._project(projector, facts)

        self.assertEqual(projection.state, "cannot-confirm")
        self.assertIn(
            f"controls:{_CORE_PRODUCERS['controls']}:revision-conflict",
            projection.reason_codes,
        )

    def test_114_a5_c16_unknown_domain_input_cannot_activate(self) -> None:
        projector = self._projector()
        raw_unknown_domain = self._seal_core("entry").to_wire()
        raw_unknown_domain["domain"] = "heartbeat"

        projection = self._project(
            projector,
            self.core_facts + (raw_unknown_domain,),
        )

        self.assertEqual(projection.state, "cannot-confirm")
        self.assertIn("global:invalid-envelope", projection.reason_codes)

    def test_114_a5_c17_unexpected_producer_cannot_activate(self) -> None:
        projector = self._projector()
        unexpected = self._seal(
            domain="entry",
            requiredness="core",
            state="confirmed-ok",
            generation=_GENERATION,
            producer_id=_UNEXPECTED_PRODUCER,
            producer_contract_version=_UNEXPECTED_CONTRACT,
            suffix="unexpected-producer-independent-case",
        )

        projection = self._project(projector, self.core_facts + (unexpected,))

        self.assertEqual(projection.state, "cannot-confirm")
        self.assertIn("global:unexpected-producer", projection.reason_codes)

    def test_114_a5_c18_producer_contract_mismatch_cannot_activate(self) -> None:
        projector = self._projector()
        retired_contract = "entry-fact-v0"
        retired_authority = STATUS.CapabilityFactAuthority(
            authority_id=self.authority.authority_id,
            signing_key=_SIGNING_KEY,
            producer_contracts={_CORE_PRODUCERS["entry"]: retired_contract},
        )
        mismatched = self._seal(
            domain="entry",
            requiredness="core",
            state="confirmed-ok",
            generation=_GENERATION,
            producer_id=_CORE_PRODUCERS["entry"],
            producer_contract_version=retired_contract,
            suffix="retired-producer-contract",
            authority=retired_authority,
        )
        self.assertTrue(retired_authority.verify(mismatched))
        self.assertFalse(self.authority.verify(mismatched))
        facts = self._replace_core(self.core_facts, "entry", mismatched)

        projection = self._project(projector, facts)

        self.assertEqual(projection.state, "cannot-confirm")
        self.assertIn(
            f"entry:{_CORE_PRODUCERS['entry']}:producer-contract-mismatch",
            projection.reason_codes,
        )

    def test_114_a5_c19_requiredness_mismatch_cannot_activate(self) -> None:
        projector = self._projector()
        mismatched = self._seal(
            domain="entry",
            requiredness="non-core",
            state="confirmed-ok",
            generation=_GENERATION,
            producer_id=_CORE_PRODUCERS["entry"],
            producer_contract_version=_CORE_CONTRACTS["entry"],
            suffix="requiredness-mismatch",
        )
        self.assertTrue(self.authority.verify(mismatched))
        facts = self._replace_core(self.core_facts, "entry", mismatched)

        projection = self._project(projector, facts)

        self.assertEqual(projection.state, "cannot-confirm")
        self.assertIn(
            f"entry:{_CORE_PRODUCERS['entry']}:requiredness-mismatch",
            projection.reason_codes,
        )


if __name__ == "__main__":
    unittest.main()

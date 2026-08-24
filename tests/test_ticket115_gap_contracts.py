"""Independent Case evidence for the synchronized Ticket 115 A1-A8 contract."""

from __future__ import annotations

import unittest

from partner_health_steward.ticket115_contracts import (
    DeliveryEvidence,
    DeliveryEvidenceAuthority,
    MandatoryDeliveryLedger,
    MandatoryDeliveryRequest,
    TaskClaimLease,
    Ticket115ContractViolation,
)
from partner_health_steward.tasks import (
    TaskApprovalBinding,
    TaskCandidate,
    TaskEngine,
    TaskExternalBoundary,
    TaskRuntimeState,
)


SHA = "sha256:" + "a" * 64
OWNER = "owner-A"
INSTALLATION = "installation-A"
NOW = "2026-08-24T02:00:00+00:00"


def _candidate(*, suffix: str = "", external: bool = False) -> TaskCandidate:
    return TaskCandidate(
        candidate_id=f"candidate:gap:{suffix or 'base'}",
        source_kind="owner-goal",
        source_ref=f"owner-goal:gap:{suffix or 'base'}",
        source_revision_digest=SHA,
        purpose=f"purpose {suffix or 'base'}",
        expected_result="a declared result",
        assignee="health-steward",
        allowed_data_categories=("portrait",),
        allowed_data_refs=("portrait:sleep",),
        external_boundary=(
            TaskExternalBoundary(
                recipient_refs=("owner:weixin",),
                effect_kinds=("owner-delivery",),
            )
            if external
            else TaskExternalBoundary.internal_only()
        ),
        phase="waiting-approval" if external else "planned",
        approval=(
            TaskApprovalBinding.waiting()
            if external
            else TaskApprovalBinding.not_required()
        ),
        acceptance_criteria=("owner confirms the declared result",),
    )


class Ticket115GapContractTests(unittest.TestCase):
    def test_115_a1_c01_defer_is_a_fact_and_keeps_active_label(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            _candidate(),
            committed_at_utc=NOW,
        )
        deferred = TaskEngine.defer(
            created.state,
            created.task_id,
            deferred_at_utc="2026-08-24T03:00:00+00:00",
        )
        self.assertEqual(deferred.state.task(created.task_id).primary_label, "active")
        self.assertEqual(deferred.state.task(created.task_id).phase, "waiting-owner")
        self.assertEqual(deferred.state.control_facts[0].kind, "deferred")

    def test_115_a1_c02_scope_expansion_creates_linked_waiting_task(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            _candidate(),
            committed_at_utc=NOW,
        )
        expanded = TaskEngine.adjust(
            created.state,
            created.task_id,
            _candidate(suffix="expanded", external=True),
            adjusted_at_utc="2026-08-24T03:00:00+00:00",
            scope_expanded=True,
        )
        old = expanded.state.task(created.task_id)
        new = expanded.state.task(expanded.task_id)
        self.assertEqual(old.primary_label, "active")
        self.assertEqual(old.successor_task_ids, (new.task_id,))
        self.assertEqual(new.phase, "waiting-approval")
        self.assertEqual(expanded.state.control_facts[0].kind, "scope-expanded")

    def test_115_a2_c01_adjustment_is_append_only_and_changes_current_revision(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            _candidate(),
            committed_at_utc=NOW,
        )
        adjusted = TaskEngine.adjust(
            created.state,
            created.task_id,
            _candidate(suffix="adjusted"),
            adjusted_at_utc="2026-08-24T03:00:00+00:00",
        )
        self.assertEqual(adjusted.state.task(created.task_id).primary_label, "active")
        self.assertEqual(adjusted.state.control_facts[0].kind, "adjusted")
        self.assertEqual(adjusted.state.task(created.task_id).version, 2)

    def test_115_a6_c01_task_claim_lease_rejects_cross_epoch_and_stale_cas(self) -> None:
        lease = TaskClaimLease(
            claim_id="claim:1",
            task_id="task:1",
            generation=3,
            holder_role="health-tasks",
            runtime_epoch="epoch:1",
            acquired_at_monotonic_seconds=10.0,
            expires_at_monotonic_seconds=20.0,
            task_revision=4,
            task_cas_identity="cas:4",
        )
        self.assertTrue(
            lease.can_commit(
                runtime_epoch="epoch:1",
                monotonic_seconds=15.0,
                task_revision=4,
                task_cas_identity="cas:4",
            )
        )
        self.assertFalse(
            lease.can_commit(
                runtime_epoch="epoch:2",
                monotonic_seconds=15.0,
                task_revision=4,
                task_cas_identity="cas:4",
            )
        )
        self.assertFalse(
            lease.can_commit(
                runtime_epoch="epoch:1",
                monotonic_seconds=15.0,
                task_revision=5,
                task_cas_identity="cas:4",
            )
        )

    def test_115_a5_c01_delivery_evidence_accepts_only_layer_authority(self) -> None:
        evidence = DeliveryEvidence(
            layer="delivered",
            producer_contract="weixin.channel.receipt",
            generation=2,
            attestation=SHA,
            replay_identity="replay:1",
            effect_id="outbox:1",
            evidence_ref="weixin:receipt:1",
        )
        self.assertIs(DeliveryEvidenceAuthority.require(evidence), evidence)
        forged = DeliveryEvidence(
            **{
                **evidence.to_storage(),
                "producer_contract": "owner-delivery-adapter.interface",
            }
        )
        with self.assertRaises(Ticket115ContractViolation):
            DeliveryEvidenceAuthority.require(forged)

    def test_115_a5_c02_delivery_evidence_round_trip_preserves_replay_identity(self) -> None:
        evidence = DeliveryEvidence(
            layer="interface-accepted",
            producer_contract="owner-delivery-adapter.interface",
            generation=1,
            attestation=SHA,
            replay_identity="attempt:1",
            effect_id="outbox:1",
            evidence_ref="adapter:accepted:1",
        )
        self.assertEqual(
            DeliveryEvidence.from_storage(evidence.to_storage()),
            evidence,
        )

    def test_115_a8_c01_mandatory_request_is_content_free(self) -> None:
        request = MandatoryDeliveryRequest(
            request_id="mandatory:1",
            kind="status-change",
            causal_state_id="status-transition:1",
            generation=2,
            reason_code="active-to-abnormal",
        )
        self.assertTrue(request.body_free)
        self.assertNotIn("body", request.__dict__)

    def test_115_a8_c02_mandatory_request_dedupes_replay_and_keeps_new_cause(self) -> None:
        first = MandatoryDeliveryRequest(
            request_id="mandatory:1",
            kind="capability-gap",
            causal_state_id="status-transition:1",
            generation=2,
            reason_code="delivery-unknown",
        )
        replay = MandatoryDeliveryRequest(
            request_id="mandatory:replay",
            kind="capability-gap",
            causal_state_id="status-transition:1",
            generation=2,
            reason_code="delivery-unknown",
        )
        newer = MandatoryDeliveryRequest(
            request_id="mandatory:2",
            kind="capability-gap",
            causal_state_id="status-transition:2",
            generation=2,
            reason_code="delivery-unknown",
        )
        ledger, issued = MandatoryDeliveryLedger().issue(first)
        self.assertTrue(issued)
        ledger, issued = ledger.issue(replay)
        self.assertFalse(issued)
        ledger, issued = ledger.issue(newer)
        self.assertTrue(issued)
        self.assertEqual(len(ledger.requests), 2)


if __name__ == "__main__":
    unittest.main()

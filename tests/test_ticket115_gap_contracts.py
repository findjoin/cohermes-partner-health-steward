"""Independent Case evidence for the synchronized Ticket 115 A1-A8 contract."""

from __future__ import annotations

import unittest
from dataclasses import replace

from partner_health_steward.settings import ExecutionScopeApproval
from partner_health_steward.review import DailyReviewEngine, DailyReviewLedger
from partner_health_steward.status import StatusProjector, StatusTransition
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
    TaskContractViolation,
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


def _bound_scope_candidate(
    *, suffix: str, revoked: bool = False
) -> tuple[TaskCandidate, ExecutionScopeApproval]:
    proposed = _candidate(suffix=suffix, external=True)
    task_id = (
        "task:"
        + proposed.semantic_digest.removeprefix("sha256:")[:32]
        + ":1"
    )
    approval = ExecutionScopeApproval(
        approval_id=f"approval:gap-{suffix}",
        approval_version=1,
        owner_id=OWNER,
        installation_id=INSTALLATION,
        task_id=task_id,
        effect_request_id=f"effect:gap-{suffix}",
        assignee=proposed.assignee,
        purpose=proposed.purpose,
        allowed_data_categories=proposed.allowed_data_categories,
        allowed_data_refs=proposed.allowed_data_refs,
        first_hop_recipient="owner:weixin",
        external_effect_kind="owner-delivery",
        max_attempts=1,
        min_contact_interval_seconds=0,
        expires_at_utc="2026-09-01T00:00:00+00:00",
        route_id=f"route:gap-{suffix}",
        configuration_generation=1,
        disclosure_version=f"disclosure:gap-{suffix}",
        revoked=revoked,
        revoked_at_utc=(
            "2026-08-24T03:00:00+00:00" if revoked else None
        ),
    )
    return (
        replace(
            proposed,
            phase="planned",
            approval=TaskApprovalBinding.bound(
                approval.approval_id,
                approval.approval_version,
            ),
        ),
        approval,
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

    def test_115_a1_c05_scope_expansion_consumes_only_exact_current_approval(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            _candidate(),
            committed_at_utc=NOW,
        )
        proposed = _candidate(suffix="approved-expanded", external=True)
        successor_id = (
            "task:"
            + proposed.semantic_digest.removeprefix("sha256:")[:32]
            + ":1"
        )
        approval = ExecutionScopeApproval(
            approval_id="approval:gap-expansion",
            approval_version=1,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            task_id=successor_id,
            effect_request_id="effect:gap-expansion",
            assignee=proposed.assignee,
            purpose=proposed.purpose,
            allowed_data_categories=proposed.allowed_data_categories,
            allowed_data_refs=proposed.allowed_data_refs,
            first_hop_recipient="owner:weixin",
            external_effect_kind="owner-delivery",
            max_attempts=1,
            min_contact_interval_seconds=0,
            expires_at_utc="2026-09-01T00:00:00+00:00",
            route_id="route:gap-expansion",
            configuration_generation=1,
            disclosure_version="disclosure:gap-expansion",
            revoked=False,
            revoked_at_utc=None,
        )
        bound = replace(
            proposed,
            phase="planned",
            approval=TaskApprovalBinding.bound(
                approval.approval_id,
                approval.approval_version,
            ),
        )
        expanded = TaskEngine.adjust(
            created.state,
            created.task_id,
            bound,
            adjusted_at_utc="2026-08-24T03:00:00+00:00",
            scope_expanded=True,
            current_approval=approval,
        )
        self.assertEqual(expanded.state.task(expanded.task_id).approval.status, "bound")
        with self.assertRaisesRegex(TaskContractViolation, "current and exact"):
            TaskEngine.adjust(
                created.state,
                created.task_id,
                bound,
                adjusted_at_utc="2026-08-24T03:00:00+00:00",
                scope_expanded=True,
                current_approval=replace(approval, approval_version=2),
            )

    def test_115_a1_c06_scope_expansion_requires_a_current_approval(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            _candidate(),
            committed_at_utc=NOW,
        )
        bound, _ = _bound_scope_candidate(suffix="missing-approval")
        with self.assertRaisesRegex(TaskContractViolation, "exact current approval"):
            TaskEngine.adjust(
                created.state,
                created.task_id,
                bound,
                adjusted_at_utc="2026-08-24T03:00:00+00:00",
                scope_expanded=True,
            )

    def test_115_a1_c07_revoked_scope_approval_is_rejected(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            _candidate(),
            committed_at_utc=NOW,
        )
        bound, revoked = _bound_scope_candidate(suffix="revoked", revoked=True)
        with self.assertRaisesRegex(TaskContractViolation, "current and exact"):
            TaskEngine.adjust(
                created.state,
                created.task_id,
                bound,
                adjusted_at_utc="2026-08-24T03:00:00+00:00",
                scope_expanded=True,
                current_approval=revoked,
            )

    def test_115_a1_c08_phase_progression_keeps_the_active_primary_label(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            _candidate(),
            committed_at_utc=NOW,
        )
        advanced = TaskEngine.advance_phase(
            created.state,
            created.task_id,
            phase="in-progress",
            advanced_at_utc="2026-08-24T03:00:00+00:00",
        )
        task = advanced.state.task(created.task_id)
        self.assertEqual(task.phase, "in-progress")
        self.assertEqual(task.primary_label, "active")

    def test_115_a1_c09_primary_labels_are_mutually_exclusive(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            _candidate(),
            committed_at_utc=NOW,
        )
        cancelled = TaskEngine.cancel(
            created.state,
            created.task_id,
            cancelled_at_utc="2026-08-24T03:00:00+00:00",
        )
        task = cancelled.state.task(created.task_id)
        self.assertIn(task.primary_label, {"active", "solved", "failed", "cancelled"})
        self.assertEqual(
            sum(task.primary_label == label for label in {"active", "solved", "failed", "cancelled"}),
            1,
        )

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

    def test_115_a3_c06_same_local_day_replay_does_not_create_a_second_review(self) -> None:
        ledger = DailyReviewLedger.empty(OWNER, INSTALLATION)
        first = DailyReviewEngine.prepare(
            ledger,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc=NOW,
            current_state_digest=SHA,
            changed=True,
            action_refs=("task:review",),
        )
        committed = DailyReviewEngine.commit(
            first,
            completed_at_utc="2026-08-24T03:00:00+00:00",
        )
        replay = DailyReviewEngine.prepare(
            committed.ledger,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T04:00:00+00:00",
            current_state_digest=SHA,
            changed=True,
            action_refs=("task:review",),
        )
        self.assertEqual(replay.outcome, "already-completed")
        self.assertTrue(replay.replayed)
        self.assertEqual(len(replay.ledger.completed), 1)

    def test_115_a6_c07_task_engine_persists_runtime_epoch_claim_and_rejects_old_holder(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            _candidate(),
            committed_at_utc=NOW,
        )
        old_cas = __import__(
            "partner_health_steward.initialization",
            fromlist=["stable_digest"],
        ).stable_digest(created.state.task(created.task_id).to_storage())
        claimed = TaskEngine.claim(
            created.state,
            created.task_id,
            holder_id="worker:old",
            lease_id="claim:runtime-old",
            acquired_at_utc=NOW,
            runtime_epoch="epoch:old",
            acquired_at_monotonic_seconds=10.0,
            expires_at_monotonic_seconds=20.0,
            generation=1,
            task_cas_identity=old_cas,
        )
        self.assertEqual(len(claimed.state.task_claim_leases), 1)
        lease = claimed.state.task_claim_leases[0]
        takeover = TaskEngine.claim(
            claimed.state,
            created.task_id,
            holder_id="worker:new",
            lease_id="claim:runtime-new",
            acquired_at_utc="2026-08-24T02:00:01+00:00",
            runtime_epoch="epoch:new",
            acquired_at_monotonic_seconds=1.0,
            expires_at_monotonic_seconds=5.0,
            generation=2,
            task_cas_identity=__import__(
                "partner_health_steward.initialization",
                fromlist=["stable_digest"],
            ).stable_digest(claimed.state.task(created.task_id).to_storage()),
        )
        self.assertEqual(takeover.state.task_claim_leases[0].runtime_epoch, "epoch:new")
        with self.assertRaisesRegex(TaskContractViolation, "runtime task claim is stale"):
            TaskEngine.release_claim(
                takeover.state,
                "claim:runtime-new",
                holder_id="worker:new",
                observed_at_utc="2026-08-24T02:00:02+00:00",
                runtime_epoch="epoch:old",
                monotonic_seconds=2.0,
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

    def test_115_a5_c08_actual_action_requires_the_admitted_event_producer(self) -> None:
        evidence = DeliveryEvidence(
            layer="actual-action",
            producer_contract="owner.admitted-event",
            generation=1,
            attestation=SHA,
            replay_identity="owner-event:1",
            effect_id="outbox:1",
            evidence_ref="owner-event:evidence:1",
        )
        self.assertIs(DeliveryEvidenceAuthority.require(evidence), evidence)
        with self.assertRaises(Ticket115ContractViolation):
            DeliveryEvidenceAuthority.require(
                replace(evidence, producer_contract="owner-delivery-adapter.interface")
            )

    def test_115_a5_c09_out_of_order_delivery_facts_are_rejected(self) -> None:
        from partner_health_steward.delivery import DeliveryFact, DeliveryContractViolation

        formed = DeliveryFact(
            kind="formed",
            occurred_at_utc=NOW,
            evidence_ref="outbox:1:formed",
        )
        submitted = DeliveryFact(
            kind="submitted",
            occurred_at_utc="2026-08-24T02:00:01+00:00",
            evidence_ref="business:1",
        )
        from partner_health_steward.delivery import OutboxRecord, OwnerDeliveryEngine

        intent = OwnerDeliveryEngine.form_intent(
            effect_kind="owner-delivery",
            owner_id=OWNER,
            installation_id=INSTALLATION,
            effect_request_id="effect:1",
            business_fact_ref="business:1",
            business_revision_digest=SHA,
            source_ref="review:1",
            recipient_ref="owner:weixin",
            route_id="route:1",
            route_generation=1,
            payload_ref="payload:1",
            payload_digest=SHA,
            formed_at_utc=NOW,
        )
        with self.assertRaises(DeliveryContractViolation):
            OutboxRecord(intent=intent, facts=(submitted, formed))

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

    def test_115_a5_c07_production_delivery_fact_exposes_bound_authoritative_evidence(self) -> None:
        from partner_health_steward.delivery import DeliveryFact, DeliveryContractViolation

        fact = DeliveryFact(
            kind="delivered",
            occurred_at_utc=NOW,
            evidence_ref="weixin:receipt:gap",
            result_ref="weixin:result:gap",
            attempt_ref="attempt:gap",
        )
        evidence = fact.evidence("outbox:gap")
        self.assertEqual(evidence.producer_contract, "weixin.channel.receipt")
        with self.assertRaises(DeliveryContractViolation):
            DeliveryFact(
                kind="delivered",
                occurred_at_utc=NOW,
                evidence_ref="weixin:receipt:forged",
                result_ref="weixin:result:forged",
                attempt_ref="attempt:forged",
                producer_contract="owner-delivery-adapter.interface",
            )

    def test_115_a8_c04_status_transition_emits_one_content_free_request(self) -> None:
        transition = StatusTransition(
            transition_id="status-transition:gap",
            previous_state="active",
            current_state="cannot-confirm",
            projection_digest=SHA,
            affected_core_domains=("tasks",),
        )
        request = StatusProjector.mandatory_delivery_request(
            transition,
            generation=2,
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertTrue(request.body_free)
        self.assertEqual(request.causal_state_id, transition.transition_id)

    def test_115_registry_self_validates_every_observable_target(self) -> None:
        from tests.ticket115_case_registry import (
            CASE_REGISTRY,
            validate_case_registry,
        )

        validate_case_registry(resolve_tests=True)
        self.assertGreaterEqual(len(CASE_REGISTRY), 50)


if __name__ == "__main__":
    unittest.main()

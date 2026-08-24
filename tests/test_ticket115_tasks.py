"""Ticket 115 task authority and local-day review contract tests."""

from __future__ import annotations

import unittest

from partner_health_steward import tasking
from partner_health_steward.review import (
    DailyReviewEngine,
    DailyReviewLedger,
    ReviewContractViolation,
    local_day_key,
)
from partner_health_steward.tasks import (
    TaskAcceptance,
    TaskAcceptanceCriterionProof,
    TaskApprovalBinding,
    TaskCandidate,
    TaskContractViolation,
    TaskEngine,
    TaskExternalBoundary,
    TaskRuntimeState,
)


OWNER = "owner-A"
INSTALLATION = "partner-installation"
NOW = "2026-08-24T02:00:00+00:00"
SHA_ONE = "sha256:" + "1" * 64
SHA_TWO = "sha256:" + "2" * 64
CURRENT_EVIDENCE_REVISIONS = {
    "evidence:sleep:accepted": SHA_TWO,
}


def candidate(
    *,
    candidate_id: str = "candidate:sleep-follow-up:1",
    source_ref: str = "owner-goal:sleep-consistency",
    source_digest: str = SHA_ONE,
    purpose: str = "Confirm whether the new sleep schedule is sustainable.",
    expected_result: str = "A seven-day sleep pattern with the remaining gap stated.",
    phase: str = "planned",
    external_boundary: TaskExternalBoundary | None = None,
    approval: TaskApprovalBinding | None = None,
) -> TaskCandidate:
    return TaskCandidate(
        candidate_id=candidate_id,
        source_kind="owner-goal",
        source_ref=source_ref,
        source_revision_digest=source_digest,
        purpose=purpose,
        expected_result=expected_result,
        assignee="health-steward",
        allowed_data_categories=("portrait", "evidence"),
        allowed_data_refs=("portrait-topic:sleep",),
        external_boundary=external_boundary or TaskExternalBoundary.internal_only(),
        phase=phase,
        approval=approval or TaskApprovalBinding.not_required(),
        acceptance_criteria=("three owner-confirmed wake-time observations",),
    )


def acceptance_for(
    task,
    *,
    accepted_at_utc: str = "2026-08-24T03:00:00+00:00",
) -> TaskAcceptance:
    proof = TaskAcceptanceCriterionProof(
        criterion=task.acceptance_criteria[0],
        evidence_refs=("evidence:sleep:accepted",),
        evidence_revision_digests=(SHA_TWO,),
    )
    return TaskAcceptance.prove(
        task,
        (proof,),
        accepted_at_utc=accepted_at_utc,
    )


class Ticket115TaskValueTests(unittest.TestCase):
    def test_owner_cancellation_closes_active_task_and_releases_its_claim(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            candidate(),
            committed_at_utc=NOW,
        )
        claimed = TaskEngine.claim(
            created.state,
            created.task_id,
            holder_id="worker:A",
            lease_id="lease:A",
            acquired_at_utc="2026-08-24T02:01:00+00:00",
        )

        cancelled = TaskEngine.apply_owner_cancellation(
            claimed.state,
            created.task_id,
            control_ref="owner-control:cancel-sleep-follow-up",
            effective_at_utc="2026-08-24T02:02:00+00:00",
        )

        task = cancelled.state.task(created.task_id)
        self.assertEqual(cancelled.outcome, "owner-cancelled")
        self.assertEqual(task.primary_label, "cancelled")
        self.assertEqual(task.phase, "closed")
        self.assertEqual(task.terminal_fact.reason_code, "owner-task-cancelled")
        self.assertEqual(cancelled.state.active_claims, ())

    def test_tasking_public_surface_exports_governed_value_types(self) -> None:
        for name in (
            "TASK_APPROVAL_STATUSES",
            "TASK_INITIAL_PHASES",
            "TASK_UNKNOWN_RESOLUTIONS",
            "TaskApprovalBinding",
            "TaskAcceptanceCriterionProof",
            "TaskExternalBoundary",
            "TaskTerminalFact",
            "TaskUnknownFact",
        ):
            with self.subTest(name=name):
                self.assertIn(name, tasking.__all__)
                self.assertTrue(hasattr(tasking, name))

    def test_candidate_round_trip_preserves_every_governed_field(self) -> None:
        approval = TaskApprovalBinding.bound("approval:sleep", 3)
        external = TaskExternalBoundary(
            recipient_refs=("recipient:owner-weixin",),
            effect_kinds=("owner-reminder",),
        )
        original = candidate(external_boundary=external, approval=approval)

        restored = TaskCandidate.from_storage(original.to_storage())

        self.assertEqual(restored, original)
        self.assertEqual(restored.expected_result, original.expected_result)
        self.assertEqual(restored.external_boundary, external)
        self.assertEqual(restored.phase, "planned")
        self.assertEqual(restored.approval, approval)
        self.assertEqual(
            restored.acceptance_criteria,
            ("three owner-confirmed wake-time observations",),
        )

    def test_candidate_rejects_incomplete_or_inconsistent_external_authority(self) -> None:
        with self.assertRaises(TaskContractViolation):
            TaskExternalBoundary(
                recipient_refs=("recipient:owner-weixin",),
                effect_kinds=(),
            )
        with self.assertRaises(TaskContractViolation):
            candidate(
                external_boundary=TaskExternalBoundary(
                    recipient_refs=("recipient:owner-weixin",),
                    effect_kinds=("owner-reminder",),
                ),
                approval=TaskApprovalBinding.not_required(),
            )
        with self.assertRaises(TaskContractViolation):
            TaskCandidate.from_storage(
                {**candidate().to_storage(), "model_may_complete": True}
            )

    def test_runtime_round_trip_preserves_tasks_claims_receipts_and_unknowns(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            candidate(),
            committed_at_utc=NOW,
        )
        claimed = TaskEngine.claim(
            created.state,
            created.task_id,
            holder_id="worker:A",
            lease_id="lease:A",
            acquired_at_utc="2026-08-24T02:01:00+00:00",
            lease_seconds=60,
        )
        released = TaskEngine.release_claim(
            claimed.state,
            "lease:A",
            holder_id="worker:A",
            observed_at_utc="2026-08-24T02:01:20+00:00",
        )
        unknown = TaskEngine.mark_delivery_unknown(
            released.state,
            created.task_id,
            effect_ref="delivery:owner:1",
            reason_code="channel-result-unknown",
            observed_at_utc="2026-08-24T02:02:00+00:00",
        )

        restored = TaskRuntimeState.from_storage(unknown.state.to_storage())

        self.assertEqual(restored, unknown.state)
        self.assertEqual(restored.delivery_unknown_refs, ("delivery:owner:1",))

    def test_acceptance_round_trip_binds_current_task_criteria_and_evidence_revisions(
        self,
    ) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            candidate(),
            committed_at_utc=NOW,
        )
        task = created.state.task(created.task_id)
        acceptance = acceptance_for(task)
        restored = TaskAcceptance.from_storage(acceptance.to_storage())

        self.assertEqual(restored, acceptance)
        self.assertEqual(restored.task_version, task.version)
        self.assertEqual(restored.task_semantic_digest, task.semantic_digest)
        self.assertEqual(restored.evidence_refs, ("evidence:sleep:accepted",))
        with self.assertRaisesRegex(
            TaskContractViolation,
            "result digest mismatch",
        ):
            TaskAcceptance.from_storage(
                {
                    **acceptance.to_storage(),
                    "task_version": task.version + 1,
                }
            )
        with self.assertRaisesRegex(
            TaskContractViolation,
            "exact current criteria",
        ):
            TaskAcceptance.prove(
                task,
                (
                    TaskAcceptanceCriterionProof(
                        criterion="interface accepted",
                        evidence_refs=("weixin-response:accepted",),
                        evidence_revision_digests=(SHA_ONE,),
                    ),
                ),
                accepted_at_utc="2026-08-24T03:00:00+00:00",
            )
        with self.assertRaisesRegex(
            TaskContractViolation,
            "evidence revision",
        ):
            TaskAcceptanceCriterionProof(
                criterion=task.acceptance_criteria[0],
                evidence_refs=("evidence:sleep:accepted",),
                evidence_revision_digests=("unversioned-evidence",),
            )


class Ticket115TaskEngineTests(unittest.TestCase):
    def test_engine_owns_initial_task_state_and_merges_duplicate_basis(self) -> None:
        first = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            candidate(),
            committed_at_utc=NOW,
        )
        duplicate = TaskEngine.admit_candidate(
            first.state,
            candidate(
                candidate_id="candidate:sleep-follow-up:2",
                source_ref="evidence:sleep-note:2",
                source_digest=SHA_TWO,
            ),
            committed_at_utc="2026-08-24T02:05:00+00:00",
        )
        task = duplicate.state.task(first.task_id)

        self.assertEqual(first.outcome, "created")
        self.assertEqual(duplicate.outcome, "duplicate-active-task")
        self.assertEqual((task.primary_label, task.phase), ("active", "planned"))
        self.assertEqual(task.expected_result, candidate().expected_result)
        self.assertEqual(
            task.source_refs,
            ("evidence:sleep-note:2", "owner-goal:sleep-consistency"),
        )
        self.assertEqual(task.version, 2)
        self.assertEqual(duplicate.state.version, 2)

    def test_terminal_task_cannot_reopen_but_can_link_an_explicit_successor(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            candidate(),
            committed_at_utc=NOW,
        )
        solved = TaskEngine.solve(
            created.state,
            acceptance_for(created.state.task(created.task_id)),
            current_evidence_revisions=CURRENT_EVIDENCE_REVISIONS,
        )
        restored = TaskRuntimeState.from_storage(solved.state.to_storage())
        restored_terminal = restored.task(created.task_id).terminal_fact

        self.assertIsNotNone(restored_terminal)
        self.assertEqual(
            restored_terminal.acceptance,  # type: ignore[union-attr]
            acceptance_for(created.state.task(created.task_id)),
        )
        with self.assertRaises(TaskContractViolation):
            TaskEngine.admit_candidate(
                solved.state,
                candidate(candidate_id="candidate:sleep-follow-up:again"),
                committed_at_utc="2026-08-25T02:00:00+00:00",
            )

        successor = TaskEngine.link_successor(
            solved.state,
            created.task_id,
            candidate(candidate_id="candidate:sleep-follow-up:successor"),
            committed_at_utc="2026-08-25T02:00:00+00:00",
        )
        old = successor.state.task(created.task_id)
        new = successor.state.task(successor.task_id)

        self.assertEqual(old.primary_label, "solved")
        self.assertEqual(old.successor_task_ids, (new.task_id,))
        self.assertEqual(new.predecessor_task_ids, (old.task_id,))
        with self.assertRaises(TaskContractViolation):
            TaskEngine.advance_phase(
                successor.state,
                old.task_id,
                phase="planned",
                advanced_at_utc="2026-08-25T02:01:00+00:00",
            )

    def test_solve_rejects_stale_or_predating_acceptance_proof(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            candidate(),
            committed_at_utc=NOW,
        )
        original_task = created.state.task(created.task_id)
        stale_acceptance = acceptance_for(original_task)
        advanced = TaskEngine.advance_phase(
            created.state,
            created.task_id,
            phase="awaiting-result",
            advanced_at_utc="2026-08-24T02:30:00+00:00",
        )

        with self.assertRaisesRegex(
            TaskContractViolation,
            "current task version",
        ):
            TaskEngine.solve(
                advanced.state,
                stale_acceptance,
                current_evidence_revisions=CURRENT_EVIDENCE_REVISIONS,
            )

        current_task = advanced.state.task(created.task_id)
        predating = acceptance_for(
            current_task,
            accepted_at_utc="2026-08-24T02:29:59+00:00",
        )
        with self.assertRaisesRegex(
            TaskContractViolation,
            "predates the current task revision",
        ):
            TaskEngine.solve(
                advanced.state,
                predating,
                current_evidence_revisions=CURRENT_EVIDENCE_REVISIONS,
            )

    def test_solve_requires_acceptance_evidence_to_match_current_revisions(
        self,
    ) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            candidate(),
            committed_at_utc=NOW,
        )
        acceptance = acceptance_for(created.state.task(created.task_id))

        with self.assertRaisesRegex(
            TaskContractViolation,
            "current evidence revision",
        ):
            TaskEngine.solve(
                created.state,
                acceptance,
                current_evidence_revisions={
                    "evidence:sleep:accepted": SHA_ONE,
                },
            )
        with self.assertRaisesRegex(
            TaskContractViolation,
            "current evidence revision",
        ):
            TaskEngine.solve(
                created.state,
                acceptance,
                current_evidence_revisions={},
            )

    def test_expired_task_lease_can_be_taken_over_but_live_lease_cannot(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            candidate(),
            committed_at_utc=NOW,
        )
        first = TaskEngine.claim(
            created.state,
            created.task_id,
            holder_id="worker:A",
            lease_id="lease:A",
            acquired_at_utc="2026-08-24T02:01:00+00:00",
            lease_seconds=60,
        )
        with self.assertRaises(TaskContractViolation):
            TaskEngine.claim(
                first.state,
                created.task_id,
                holder_id="worker:B",
                lease_id="lease:B",
                acquired_at_utc="2026-08-24T02:01:59+00:00",
            )

        takeover = TaskEngine.claim(
            first.state,
            created.task_id,
            holder_id="worker:B",
            lease_id="lease:B",
            acquired_at_utc="2026-08-24T02:02:00+00:00",
        )

        self.assertEqual(takeover.outcome, "claim-taken-over")
        self.assertEqual(len(takeover.state.active_claims), 1)
        self.assertEqual(takeover.state.active_claims[0].holder_id, "worker:B")
        with self.assertRaises(TaskContractViolation):
            TaskEngine.release_claim(
                takeover.state,
                "lease:B",
                holder_id="worker:A",
                observed_at_utc="2026-08-24T02:02:01+00:00",
            )

    def test_delivery_unknown_is_an_active_ancillary_fact_not_a_fifth_label(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            candidate(),
            committed_at_utc=NOW,
        )
        unknown = TaskEngine.mark_delivery_unknown(
            created.state,
            created.task_id,
            effect_ref="delivery:owner:1",
            reason_code="interface-response-lost",
            observed_at_utc="2026-08-24T02:02:00+00:00",
        )
        replay = TaskEngine.mark_delivery_unknown(
            unknown.state,
            created.task_id,
            effect_ref="delivery:owner:1",
            reason_code="interface-response-lost",
            observed_at_utc="2026-08-24T02:02:00+00:00",
        )
        task = unknown.state.task(created.task_id)

        self.assertEqual(task.primary_label, "active")
        self.assertEqual(task.phase, "awaiting-result")
        self.assertEqual(len(unknown.state.unknown_facts), 1)
        self.assertTrue(replay.replayed)
        with self.assertRaises(TaskContractViolation):
            TaskEngine.fail(
                unknown.state,
                created.task_id,
                failed_at_utc="2026-08-24T02:03:00+00:00",
                reason_code="delivery-failed",
            )

        cancelled = TaskEngine.cancel(
            unknown.state,
            created.task_id,
            cancelled_at_utc="2026-08-24T02:03:00+00:00",
            reason_code="owner-stopped-task",
        )
        self.assertEqual(cancelled.state.task(created.task_id).primary_label, "cancelled")
        self.assertEqual(len(cancelled.state.unknown_facts), 1)

    def test_resolving_one_delivery_unknown_keeps_other_unknowns_frozen(self) -> None:
        created = TaskEngine.admit_candidate(
            TaskRuntimeState.empty(OWNER, INSTALLATION),
            candidate(),
            committed_at_utc=NOW,
        )
        first = TaskEngine.mark_delivery_unknown(
            created.state,
            created.task_id,
            effect_ref="delivery:owner:1",
            observed_at_utc="2026-08-24T02:02:00+00:00",
        )
        second = TaskEngine.mark_delivery_unknown(
            first.state,
            created.task_id,
            effect_ref="delivery:owner:2",
            observed_at_utc="2026-08-24T02:03:00+00:00",
        )

        resolved = TaskEngine.resolve_delivery_unknown(
            second.state,
            "delivery:owner:1",
            resolution="not-delivered",
            resolved_at_utc="2026-08-24T02:04:00+00:00",
        )

        self.assertEqual(resolved.state.task(created.task_id).phase, "awaiting-result")
        self.assertEqual(resolved.state.delivery_unknown_refs, ("delivery:owner:2",))
        with self.assertRaises(TaskContractViolation):
            TaskEngine.claim(
                resolved.state,
                created.task_id,
                holder_id="worker:A",
                lease_id="lease:A",
                acquired_at_utc="2026-08-24T02:05:00+00:00",
            )


class Ticket115DailyReviewTests(unittest.TestCase):
    def test_prepare_persists_pending_and_round_trips_before_commit(self) -> None:
        prepared = DailyReviewEngine.prepare(
            DailyReviewLedger.empty(OWNER, INSTALLATION),
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T15:30:00+00:00",
            current_state_digest=SHA_TWO,
            changed=True,
            action_refs=("task:sleep",),
        )
        restored = DailyReviewLedger.from_storage(prepared.ledger.to_storage())

        self.assertEqual(prepared.outcome, "prepared")
        self.assertIsNotNone(prepared.ledger.pending)
        self.assertEqual(restored, prepared.ledger)
        self.assertEqual(restored.pending.state_digest, SHA_TWO)  # type: ignore[union-attr]

    def test_same_day_crash_resumes_pending_then_commits_exactly_once(self) -> None:
        prepared = DailyReviewEngine.prepare(
            DailyReviewLedger.empty(OWNER, INSTALLATION),
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T15:30:00+00:00",
            current_state_digest=SHA_TWO,
            changed=True,
            action_refs=("task:sleep",),
        )
        resumed = DailyReviewEngine.prepare(
            DailyReviewLedger.from_storage(prepared.ledger.to_storage()),
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T15:45:00+00:00",
            current_state_digest=SHA_TWO,
            changed=True,
            action_refs=("task:sleep",),
        )
        committed = DailyReviewEngine.commit(
            resumed,
            completed_at_utc="2026-08-24T15:46:00+00:00",
        )
        replay = DailyReviewEngine.prepare(
            committed.ledger,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T15:50:00+00:00",
            current_state_digest=SHA_ONE,
            changed=True,
            action_refs=("task:must-not-repeat",),
        )

        self.assertEqual(resumed.outcome, "resume-current-day")
        self.assertEqual(committed.record.state_digest, SHA_TWO)  # type: ignore[union-attr]
        self.assertEqual(len(committed.ledger.completed), 1)
        self.assertIsNone(committed.ledger.pending)
        self.assertEqual(replay.outcome, "already-completed")
        self.assertTrue(replay.replayed)

    def test_stale_pending_is_discarded_without_backlog_and_only_current_day_runs(self) -> None:
        first = DailyReviewEngine.prepare(
            DailyReviewLedger.empty(OWNER, INSTALLATION),
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-23T15:30:00+00:00",
            current_state_digest=SHA_ONE,
            changed=True,
            action_refs=("task:old",),
        )
        current = DailyReviewEngine.prepare(
            DailyReviewLedger.from_storage(first.ledger.to_storage()),
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T15:30:00+00:00",
            current_state_digest=SHA_TWO,
            changed=False,
        )
        committed = DailyReviewEngine.commit(
            current,
            completed_at_utc="2026-08-24T15:31:00+00:00",
        )

        self.assertEqual(current.outcome, "stale-pending-replaced")
        self.assertEqual(current.key.local_date, "2026-08-24")
        self.assertEqual(
            tuple(record.key.local_date for record in committed.ledger.completed),
            ("2026-08-24",),
        )
        self.assertFalse(committed.notification_required)

    def test_local_day_key_is_timezone_and_dst_aware(self) -> None:
        first_fold = local_day_key(
            OWNER,
            INSTALLATION,
            "America/New_York",
            "2026-11-01T05:30:00+00:00",
        )
        second_fold = local_day_key(
            OWNER,
            INSTALLATION,
            "America/New_York",
            "2026-11-01T06:30:00+00:00",
        )
        utc_key = local_day_key(
            OWNER,
            INSTALLATION,
            "UTC",
            "2026-11-01T05:30:00+00:00",
        )

        self.assertEqual(first_fold.local_date, "2026-11-01")
        self.assertEqual(second_fold, first_fold)
        self.assertNotEqual(first_fold, utc_key)
        self.assertEqual(
            type(first_fold).from_storage(first_fold.to_storage()),
            first_fold,
        )

    def test_timezone_change_suppresses_an_already_reviewed_local_date(
        self,
    ) -> None:
        first = DailyReviewEngine.commit(
            DailyReviewEngine.prepare(
                DailyReviewLedger.empty(OWNER, INSTALLATION),
                owner_id=OWNER,
                installation_id=INSTALLATION,
                timezone_name="UTC",
                observed_at_utc="2026-08-24T12:00:00+00:00",
                current_state_digest=SHA_ONE,
                changed=False,
            ),
            completed_at_utc="2026-08-24T12:01:00+00:00",
        )
        duplicate_date = DailyReviewEngine.prepare(
            first.ledger,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="America/New_York",
            observed_at_utc="2026-08-24T18:00:00+00:00",
            current_state_digest=SHA_TWO,
            changed=True,
            action_refs=("task:must-not-duplicate",),
        )

        self.assertEqual(duplicate_date.outcome, "old-local-day-suppressed")
        self.assertEqual(duplicate_date.key.timezone, "America/New_York")
        self.assertEqual(duplicate_date.key.local_date, "2026-08-24")
        self.assertEqual(duplicate_date.ledger, first.ledger)
        self.assertIsNone(duplicate_date.record)
        self.assertEqual(duplicate_date.ledger.completed, (first.record,))
        self.assertFalse(duplicate_date.notification_required)
        self.assertEqual(
            DailyReviewEngine.commit(
                duplicate_date,
                completed_at_utc="2026-08-24T18:01:00+00:00",
            ),
            duplicate_date,
        )

        next_date = DailyReviewEngine.prepare(
            duplicate_date.ledger,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="America/New_York",
            observed_at_utc="2026-08-25T18:00:00+00:00",
            current_state_digest=SHA_TWO,
            changed=False,
        )
        committed = DailyReviewEngine.commit(
            next_date,
            completed_at_utc="2026-08-25T18:01:00+00:00",
        )

        self.assertEqual(next_date.outcome, "prepared")
        self.assertEqual(
            tuple(
                (record.key.timezone, record.key.local_date)
                for record in committed.ledger.completed
            ),
            (
                ("America/New_York", "2026-08-25"),
                ("UTC", "2026-08-24"),
            ),
        )

    def test_pending_review_cannot_commit_after_its_local_day_ends(self) -> None:
        prepared = DailyReviewEngine.prepare(
            DailyReviewLedger.empty(OWNER, INSTALLATION),
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T15:59:00+00:00",
            current_state_digest=SHA_ONE,
            changed=True,
            action_refs=("task:stale",),
        )

        with self.assertRaisesRegex(
            ReviewContractViolation,
            "cannot cross its owner-local day",
        ):
            DailyReviewEngine.commit(
                prepared,
                completed_at_utc="2026-08-24T16:01:00+00:00",
            )

        current = DailyReviewEngine.prepare(
            prepared.ledger,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T16:02:00+00:00",
            current_state_digest=SHA_TWO,
            changed=False,
        )
        self.assertEqual(current.outcome, "stale-pending-replaced")
        self.assertEqual(current.key.local_date, "2026-08-25")

    def test_quiet_review_has_no_notification_and_commit_cannot_change_pending(self) -> None:
        prepared = DailyReviewEngine.prepare(
            DailyReviewLedger.empty(OWNER, INSTALLATION),
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T15:30:00+00:00",
            current_state_digest=SHA_TWO,
            changed=False,
        )
        committed = DailyReviewEngine.commit(
            prepared,
            completed_at_utc="2026-08-24T15:31:00+00:00",
        )

        self.assertFalse(committed.notification_required)
        self.assertFalse(committed.record.changed)  # type: ignore[union-attr]
        with self.assertRaises(ReviewContractViolation):
            DailyReviewEngine.commit_observation(
                prepared,
                state_digest=SHA_ONE,
                changed=True,
                action_refs=("task:late-mutation",),
                completed_at_utc="2026-08-24T15:31:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()

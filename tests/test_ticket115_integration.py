"""Ticket 115 integration through the initialized owner authority stack."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from types import MethodType, SimpleNamespace

from partner_health_steward import HealthCore, HealthPlugin, settings, status
from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.contract import Response
from partner_health_steward.core import (
    InMemoryExecutionCapabilityVault,
)
from partner_health_steward.delivery import (
    DeliveryOutboxState,
    OwnerDeliveryTransportResult,
)
from partner_health_steward.review import (
    DailyReviewDecision,
    DailyReviewLedger,
    DailyReviewRecord,
    LocalDayKey,
    ReviewContractViolation,
)
from partner_health_steward.storage import StoreUnavailable
from partner_health_steward.tasks import (
    TaskApprovalBinding,
    TaskAcceptance,
    TaskAcceptanceCriterionProof,
    TaskCandidate,
    TaskExternalBoundary,
    TaskRuntimeState,
)
from tests import test_ticket114_authority_integration as ticket114_integration


_PEER = "plugin"
_PREPARED_AT = "2026-08-24T03:00:00+00:00"
_ATTEMPTED_AT = "2026-08-24T03:05:00+00:00"


class _RecordingAdapter:
    def __init__(self, store: object, *, status_value: str = "accepted") -> None:
        self._store = store
        self._status = status_value
        self.calls = 0
        self.saw_sqlite_transaction = False

    def send(self, intent: object) -> dict[str, object]:
        del intent
        self.calls += 1
        connection = getattr(self._store, "_connection")
        self.saw_sqlite_transaction = bool(connection.in_transaction)
        return OwnerDeliveryTransportResult(
            status=self._status,
            result_ref=f"owner-delivery-result:{self._status}",
            evidence_ref=f"owner-delivery-evidence:{self._status}",
        ).to_wire()


class _RaisingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, intent: object) -> dict[str, object]:
        del intent
        self.calls += 1
        raise RuntimeError("synthetic owner delivery transport failure")


class Ticket115IntegrationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        # Reuse Ticket 114's real initialization and current-head setup. The
        # selected case deliberately skips its correction-only fixture work.
        self.base = ticket114_integration.Ticket114AuthorityIntegrationTests(
            "test_114_a1_c17_ticket111_preferences_seed_authoritative_settings"
        )
        self.base.setUp()
        self.base.owner_clock_value = datetime.fromisoformat(_ATTEMPTED_AT)
        self.execution_vault = InMemoryExecutionCapabilityVault()
        self.status_authority = status.CapabilityFactAuthority(
            authority_id="ticket115-production-status-authority",
            signing_key=b"ticket115-production-status-key",
            producer_contracts=dict(status.PRODUCTION_STATUS_PRODUCER_CONTRACTS),
        )
        self.route_fact = settings.RouteConfigurationUpdate(
            route_id="jojo-responses-v1",
            first_hop_recipient="jojo-responses-v1",
            configuration_generation=1,
            disclosure_version="health-init-disclosure-v1",
            generation=1,
        )
        self._restart_core()

    def tearDown(self) -> None:
        self.base.tearDown()

    @property
    def core(self) -> HealthCore:
        return self.base.core

    @property
    def plugin(self) -> HealthPlugin:
        return self.base.plugin

    @property
    def store(self) -> object:
        return self.base.store

    def _restart_core(self) -> None:
        self.assertTrue(self.base.core.close().complete)
        core = HealthCore(
            self.base.store,
            self.base.head,
            execution_capability_vault=self.execution_vault,
            writer_fence_vault=self.base.writer_vault,
            admission_policy=self.base.policy,
            health_init_verifier=self.base.init_attestor,
            health_init_asset=self.base.init_asset,
            daily_skill_verifier=self.base.daily_attestor,
            daily_skill_bundle=self.base.daily_bundle,
            owner_settings_clock=lambda: self.base.owner_clock_value,
            route_configuration_provider=lambda: self.route_fact,
            status_fact_authority=self.status_authority,
            business_status_clock=lambda: self.base.status_clock_value,
        )
        plugin = HealthPlugin(
            core,
            admission_policy=self.base.policy,
            health_init_runtime=self.base.init_runtime,
            coarse_router=self.base.router,
            daily_skill_runtime=self.base.sleep_runtime,
        )
        self.base.core = core
        self.base.plugin = plugin
        self.base.correction_plugin = plugin

    def _ticket115_read(self) -> dict[str, object]:
        return self.plugin.managed_ticket115_read(peer_id=_PEER)

    def _task_state(self) -> TaskRuntimeState:
        return self.core.task_state()

    def _review_ledger(self) -> DailyReviewLedger:
        return self.core.daily_review_ledger()

    def _outbox(self) -> DeliveryOutboxState:
        return self.core.owner_delivery_outbox_state()

    def _decision(self, wire: dict[str, object]) -> DailyReviewDecision:
        return DailyReviewDecision(
            ledger=self.core.daily_review_ledger(),
            key=LocalDayKey.from_storage(wire["key"]),
            outcome=wire["outcome"],  # type: ignore[arg-type]
            record=(
                None
                if wire["record"] is None
                else DailyReviewRecord.from_storage(wire["record"])
            ),
            notification_required=wire["notification_required"],  # type: ignore[arg-type]
            replayed=wire["replayed"],  # type: ignore[arg-type]
        )

    @staticmethod
    def _transition(wire: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(
            task_id=wire["task_id"],
            outcome=wire["outcome"],
            replayed=wire["replayed"],
            task=wire["task"],
        )

    @staticmethod
    def _decision_wire(decision: DailyReviewDecision) -> dict[str, object]:
        pending = decision.ledger.pending
        prepare_digest = (
            decision.record.prepare_digest
            if decision.record is not None
            else (
                pending.prepare_digest
                if pending is not None and pending.key == decision.key
                else None
            )
        )
        return {
            "key": decision.key.to_storage(),
            "outcome": decision.outcome,
            "record": None
            if decision.record is None
            else decision.record.to_storage(),
            "notification_required": decision.notification_required,
            "replayed": decision.replayed,
            "prepare_digest": prepare_digest,
        }

    @staticmethod
    def _delivery_transition(wire: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(
            intent_id=wire["intent_id"],
            outcome=wire["outcome"],
            replayed=wire["replayed"],
            current_layer=wire["current_layer"],
        )

    def _health(self, action: str, payload: dict[str, object]) -> dict[str, object]:
        return self.plugin.health_operation(action, payload, peer_id=_PEER)

    def _effect(
        self,
        action: str,
        payload: dict[str, object],
        *,
        grant: object | None = None,
        transport: object | None = None,
    ) -> dict[str, object]:
        return self.plugin.controlled_effect(
            action,
            payload,
            grant=grant,  # type: ignore[arg-type]
            transport=transport,
            peer_id=_PEER,
        )

    def _apply_owner_setting(
        self,
        command: object,
        *,
        expected_version: int,
        suffix: str,
    ) -> None:
        request = self.base._owner_request(
            correction=False,
            settings_command=command,
            expected_settings_version=expected_version,
            command_suffix=suffix,
        )
        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

    def _candidate(
        self,
        *,
        source_revision_digest: str | None = None,
    ) -> tuple[TaskCandidate, str, str]:
        source_ref = self.base.baseline_card.evidence_id
        effect_request_id = "effect-request:ticket115-review-summary"
        candidate = TaskCandidate(
            candidate_id="candidate:ticket115-review-summary",
            source_kind="portrait-evidence",
            source_ref=source_ref,
            source_revision_digest=(
                self.base.baseline_card.revision_digest
                if source_revision_digest is None
                else source_revision_digest
            ),
            purpose="send one owner-approved daily review summary",
            expected_result="the summary transport outcome is independently observed",
            assignee="partner-health-plugin",
            allowed_data_categories=("health-evidence",),
            allowed_data_refs=(source_ref,),
            external_boundary=TaskExternalBoundary(
                recipient_refs=("jojo-responses-v1",),
                effect_kinds=("owner-delivery",),
            ),
            phase="planned",
            approval=TaskApprovalBinding.bound(
                "approval:ticket115-review-summary",
                1,
            ),
            acceptance_criteria=(
                "independent current evidence proves the declared result",
            ),
        )
        task_id = (
            "task:"
            + candidate.semantic_digest.removeprefix("sha256:")[:32]
            + ":1"
        )
        return candidate, task_id, effect_request_id

    def _configure_approval(
        self,
        task_id: str,
        effect_request_id: str,
        *,
        expected_version: int,
    ) -> None:
        snapshot = self.base.head.read().head
        approval = settings.ExecutionScopeApproval(
            approval_id="approval:ticket115-review-summary",
            approval_version=1,
            owner_id="owner-A",
            installation_id="partner-installation",
            task_id=task_id,
            effect_request_id=effect_request_id,
            assignee="partner-health-plugin",
            purpose="send one owner-approved daily review summary",
            allowed_data_categories=("health-evidence",),
            allowed_data_refs=(self.base.baseline_card.evidence_id,),
            first_hop_recipient="jojo-responses-v1",
            external_effect_kind="owner-delivery",
            max_attempts=1,
            min_contact_interval_seconds=0,
            expires_at_utc="2026-09-01T00:00:00+00:00",
            route_id="jojo-responses-v1",
            configuration_generation=1,
            disclosure_version="health-init-disclosure-v1",
            revoked=False,
            revoked_at_utc=None,
        )
        context = settings.OwnerCommandContext(
            command_id="settings-command:ticket115-approval",
            causal_id="settings-source:ticket115-approval",
            actor_kind="current_owner",
            owner_id="owner-A",
            installation_id="partner-installation",
            permission="health_settings.write",
            context_ref="managed-context:ticket115-approval",
            generation=snapshot.generation,
            writer_fence=snapshot.writer_fence,
        )
        command = settings.OwnerControlCommand(
            context=context,
            control_update=settings.ControlUpdate(
                control_name="execution_scope_approval",
                operation="grant",
                target_ref=approval.approval_id,
                generation=snapshot.generation,
                effective_at_utc="2026-08-24T02:00:00+00:00",
            ),
            execution_scope_approval=approval,
        )
        self._apply_owner_setting(
            command,
            expected_version=expected_version,
            suffix=":ticket115-approval",
        )

    def _enable_review_summary(self, *, expected_version: int = 1) -> None:
        snapshot = self.base.head.read().head
        self._apply_owner_setting(
            settings.NotificationUpdate(
                kind="review_summary",
                old_state="not-configured",
                new_state="enabled",
                generation=snapshot.generation,
                effective_at_utc="2026-08-24T02:00:00+00:00",
            ),
            expected_version=expected_version,
            suffix=":ticket115-review-summary-notification",
        )

    def _admit_review_task(
        self,
        *,
        notification_enabled: bool = True,
        source_revision_digest: str | None = None,
    ) -> tuple[str, str]:
        candidate, task_id, effect_request_id = self._candidate(
            source_revision_digest=source_revision_digest
        )
        next_version = 1
        if notification_enabled:
            self._enable_review_summary(expected_version=next_version)
            next_version += 1
        self._configure_approval(
            task_id,
            effect_request_id,
            expected_version=next_version,
        )
        transition = self._transition(
            self._health(
                "task.admit",
                {
                    "candidate": candidate.to_storage(),
                    "committed_at_utc": _PREPARED_AT,
                },
            )
        )
        self.assertEqual(transition.task_id, task_id)
        return task_id, effect_request_id

    def _replace_task_source_revision(
        self,
        task_id: str,
        source_revision_digest: str,
        *,
        updated_at_utc: str,
    ) -> None:
        task_state = self._task_state()
        task = task_state.task(task_id)
        stale_task = replace(
            task,
            version=task.version + 1,
            source_revision_digests=(source_revision_digest,),
            updated_at_utc=updated_at_utc,
        )
        self.base.store.commit_ticket115_facts(
            task_state=replace(
                task_state,
                version=task_state.version + 1,
                tasks=(stale_task,),
            )
        )

    def _commit_review_outbox(self, task_id: str, effect_request_id: str) -> str:
        prepared = self._decision(
            self._health(
                "review.prepare",
                {
                    "observed_at_utc": _PREPARED_AT,
                    "action_refs": [task_id],
                    "changed": True,
                },
            )
        )
        committed = self._decision(
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(prepared),
                    "completed_at_utc": "2026-08-24T03:01:00+00:00",
                    "delivery": {
                        "effect_request_id": effect_request_id,
                        "source_task_id": task_id,
                        "payload_ref": "payload:ticket115-review-summary",
                        "payload_digest": "sha256:" + ("7" * 64),
                        "formed_at_utc": "2026-08-24T03:00:30+00:00",
                        "submitted_at_utc": "2026-08-24T03:01:00+00:00",
                    },
                },
            )
        )
        self.assertEqual(committed.outcome, "committed")
        outbox = self._outbox()
        self.assertEqual(len(outbox.records), 1)
        return outbox.records[0].intent.intent_id

    def _claimed_delivery(self, intent_id: str) -> object:
        issued_wire = self._effect(
            "owner-delivery.issue",
            {"intent_id": intent_id},
        )
        issued = Response.from_wire(issued_wire["response"])
        self.assertEqual(issued.status, "accepted", issued)
        assert issued.meta is not None
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        assert grant is not None
        claimed = self._delivery_transition(
            self._effect(
                "owner-delivery.claim",
                {"intent_id": intent_id, "acquired_at_utc": _ATTEMPTED_AT},
                grant=grant,
            )["transition"]
        )
        self.assertEqual(claimed.outcome, "claimed")
        return grant

    def test_task_claim_and_review_prepare_resume_across_restart(self) -> None:
        task_id, _ = self._admit_review_task()
        claimed = self._transition(
            self._health(
                "task.claim",
                {
                    "task_id": task_id,
                    "holder_id": "task-worker:ticket115",
                    "lease_id": "task-lease:ticket115",
                    "acquired_at_utc": _PREPARED_AT,
                },
            )
        )
        self.assertEqual(claimed.outcome, "claimed")
        prepared = self._decision(
            self._health(
                "review.prepare",
                {
                    "observed_at_utc": _PREPARED_AT,
                    "action_refs": [task_id],
                    "changed": True,
                },
            )
        )

        self._restart_core()

        restored = self._task_state()
        self.assertEqual(restored.active_claims[0].lease_id, "task-lease:ticket115")
        resumed = self._decision(
            self._health(
                "review.prepare",
                {
                    "observed_at_utc": "2026-08-24T03:30:00+00:00",
                    "action_refs": [task_id],
                    "changed": True,
                },
            )
        )
        self.assertEqual(resumed.outcome, "resume-current-day")
        self.assertTrue(resumed.replayed)
        self.assertEqual(resumed.ledger, prepared.ledger)

    def test_plugin_ticket115_seam_exposes_only_bounded_wire_views(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        view = self._ticket115_read()
        self.assertEqual(
            frozenset(view),
            frozenset(
                {
                    "tasks",
                    "delivery_unknown_refs",
                    "completed_reviews",
                    "pending_review",
                    "owner_deliveries",
                }
            ),
        )
        self.assertEqual(view["tasks"][0]["task_id"], task_id)
        self.assertNotIn("candidate_receipts", view)
        self.assertNotIn("active_claims", view)

        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        delivery_view = self._ticket115_read()["owner_deliveries"][0]
        self.assertEqual(delivery_view["intent"]["intent_id"], intent_id)
        self.assertNotIn("leases", delivery_view)
        self.assertEqual(delivery_view["current_layer"], "submitted")

    def test_core_solve_task_requires_current_evidence_card_revision(self) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        task = self._task_state().task(task_id)
        card = self.base.baseline_card
        revision_digest = card.revision_digest
        acceptance = TaskAcceptance.prove(
            task,
            (
                TaskAcceptanceCriterionProof(
                    criterion=task.acceptance_criteria[0],
                    evidence_refs=(card.evidence_id,),
                    evidence_revision_digests=(revision_digest,),
                ),
            ),
            accepted_at_utc="2026-08-24T03:02:00+00:00",
        )

        solved = self._transition(
            self._health("task.solve", {"acceptance": acceptance.to_storage()})
        )

        self.assertEqual(solved.outcome, "solved")
        terminal = self._task_state().task(task_id).terminal_fact
        self.assertIsNotNone(terminal)
        assert terminal is not None
        self.assertEqual(terminal.acceptance, acceptance)

    def test_review_commit_rejects_stale_day_and_fresh_state_change(self) -> None:
        task_id, _ = self._admit_review_task()
        prepared = self._decision(
            self._health(
                "review.prepare",
                {
                    "observed_at_utc": _PREPARED_AT,
                    "action_refs": [task_id],
                    "changed": True,
                },
            )
        )
        with self.assertRaises(ReviewContractViolation):
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(prepared),
                    "completed_at_utc": "2026-08-24T16:01:00+00:00",
                },
            )

        self._health(
            "task.advance",
            {
                "task_id": task_id,
                "phase": "in-progress",
                "advanced_at_utc": "2026-08-24T03:40:00+00:00",
            },
        )
        with self.assertRaises(ReviewContractViolation):
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(prepared),
                    "completed_at_utc": "2026-08-24T04:00:00+00:00",
                },
            )

    def test_review_and_outbox_rollback_together(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        prepared = self._decision(
            self._health(
                "review.prepare",
                {
                    "observed_at_utc": _PREPARED_AT,
                    "action_refs": [task_id],
                    "changed": True,
                },
            )
        )
        store = self.base.store
        original = store.commit_ticket115_facts

        def fail_atomic_commit(this: object, **facts: object) -> None:
            if facts.get("review_state") is not None and facts.get("delivery_state") is not None:
                this._connection.set_authorizer(this._deny_commit)
                try:
                    original(**facts)
                finally:
                    this.clear_commit_failure()
                return
            original(**facts)

        store.commit_ticket115_facts = MethodType(fail_atomic_commit, store)
        try:
            with self.assertRaises(StoreUnavailable):
                self._health(
                    "review.commit",
                    {
                        "decision": self._decision_wire(prepared),
                        "completed_at_utc": "2026-08-24T03:01:00+00:00",
                        "delivery": {
                            "effect_request_id": effect_request_id,
                            "source_task_id": task_id,
                            "payload_ref": "payload:ticket115-rollback",
                            "payload_digest": "sha256:" + ("8" * 64),
                            "formed_at_utc": "2026-08-24T03:00:30+00:00",
                            "submitted_at_utc": "2026-08-24T03:01:00+00:00",
                        },
                    },
                )
        finally:
            store.commit_ticket115_facts = original
        self.assertIsNotNone(self._review_ledger().pending)
        self.assertEqual(
            self._outbox().records,
            (),
        )

    def test_not_configured_notification_never_reaches_adapter(self) -> None:
        task_id, effect_request_id = self._admit_review_task(
            notification_enabled=False
        )
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        issued = Response.from_wire(
            self._effect("owner-delivery.issue", {"intent_id": intent_id})["response"]
        )
        self.assertEqual(issued.status, "rejected")
        self.assertEqual(self.base.store.unresolved_effects(), ())

    def test_stale_evidence_binding_does_not_issue_generic_effect(self) -> None:
        task_id, effect_request_id = self._admit_review_task(
            source_revision_digest="sha256:" + ("0" * 64)
        )
        intent_id = self._commit_review_outbox(task_id, effect_request_id)

        issued = Response.from_wire(
            self._effect(
                "owner-delivery.issue",
                {"intent_id": intent_id},
            )["response"]
        )

        self.assertEqual(issued.status, "rejected")
        self.assertEqual(self.base.store.unresolved_effects(), ())

    def test_previous_local_day_outbox_does_not_issue_generic_effect(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        self.base.owner_clock_value = datetime(
            2026,
            8,
            25,
            3,
            5,
            tzinfo=timezone.utc,
        )

        issued = Response.from_wire(
            self._effect(
                "owner-delivery.issue",
                {"intent_id": intent_id},
            )["response"]
        )

        self.assertEqual(issued.status, "rejected")
        self.assertEqual(self.base.store.unresolved_effects(), ())

    def test_backdated_attempt_cannot_bypass_current_local_day(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        self.base.owner_clock_value = datetime(
            2026,
            8,
            25,
            3,
            5,
            tzinfo=timezone.utc,
        )
        adapter = _RecordingAdapter(self.base.store)

        with self.assertRaises(AuthorityValidationError):
            self._effect(
                "owner-delivery.execute",
                {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
                grant=grant,
                transport=adapter,
            )

        self.assertEqual(adapter.calls, 0)

    def test_accepted_delivered_and_read_stay_distinct_from_task_solved(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        adapter = _RecordingAdapter(self.base.store)
        executed = self._effect(
            "owner-delivery.execute",
            {
                "intent_id": intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
                "observed_at_utc": "2026-08-24T03:05:01+00:00",
            },
            grant=grant,
            transport=adapter,
        )
        transport_result = OwnerDeliveryTransportResult.from_wire(
            executed["transport_result"]
        )
        effect_response = Response.from_wire(executed["effect_response"])
        self.assertEqual(transport_result.status, "accepted")
        self.assertEqual(effect_response.status, "accepted")
        self.assertEqual(adapter.calls, 1)
        self.assertFalse(adapter.saw_sqlite_transaction)
        self.assertEqual(
            self._task_state().task(task_id).primary_label,
            "active",
        )

        attempted = self._outbox().record(intent_id).fact("attempted")
        for kind, observed_at in (
            ("delivered", "2026-08-24T03:06:00+00:00"),
            ("read", "2026-08-24T03:07:00+00:00"),
        ):
            self._health(
                "delivery.observe",
                {
                    "intent_id": intent_id,
                    "kind": kind,
                    "attempt_ref": attempted.attempt_ref,
                    "result_ref": f"owner-delivery-result:{kind}",
                    "evidence_ref": f"owner-delivery-evidence:{kind}",
                    "observed_at_utc": observed_at,
                },
            )
            self.assertEqual(
                self._task_state().task(task_id).primary_label,
                "active",
            )

        with self.assertRaises(AuthorityValidationError):
            self._effect(
                "owner-delivery.execute",
                {"intent_id": intent_id, "attempted_at_utc": "2026-08-24T03:08:00+00:00"},
                grant=grant,
                transport=adapter,
            )
        self.assertEqual(adapter.calls, 1)

    def test_adapter_exception_freezes_unknown_until_independent_delivery(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        adapter = _RaisingAdapter()
        executed = self._effect(
            "owner-delivery.execute",
            {
                "intent_id": intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
                "observed_at_utc": "2026-08-24T03:05:01+00:00",
            },
            grant=grant,
            transport=adapter,
        )
        transport_result = OwnerDeliveryTransportResult.from_wire(
            executed["transport_result"]
        )
        self.assertEqual(transport_result.status, "unknown")
        self.assertEqual(
            Response.from_wire(executed["effect_response"]).status,
            "unknown",
        )
        state = self._task_state()
        self.assertIn(intent_id, state.delivery_unknown_refs)
        self.assertEqual(state.task(task_id).primary_label, "active")

        attempted = self._outbox().record(intent_id).fact("attempted")
        self._health(
            "delivery.observe",
            {
                "intent_id": intent_id,
                "kind": "delivered",
                "attempt_ref": attempted.attempt_ref,
                "result_ref": "owner-delivery-result:later-delivered",
                "evidence_ref": "owner-delivery-evidence:later-delivered",
                "observed_at_utc": "2026-08-24T03:10:00+00:00",
            },
        )
        resolved = self._task_state()
        self.assertNotIn(intent_id, resolved.delivery_unknown_refs)
        self.assertEqual(resolved.task(task_id).primary_label, "active")
        self.assertEqual(
            self._outbox()
            .record(intent_id)
            .fact("unknown")
            .result_ref,
            transport_result.result_ref,
        )

    def test_writer_proof_is_rechecked_after_attempt_before_adapter(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        adapter = _RecordingAdapter(self.base.store)
        store = self.base.store
        original = store.commit_ticket115_facts
        invalidated = False

        def invalidate_after_attempt(this: object, **facts: object) -> None:
            nonlocal invalidated
            original(**facts)
            delivery_state = facts.get("delivery_state")
            if delivery_state is None or invalidated:
                return
            record = delivery_state.record(intent_id)
            if record.has_fact("attempted") and record.current_layer == "attempted":
                authority = self.base.head.read().head.as_authority()
                self.base.writer_vault.bind(
                    authority,
                    "ticket115-invalid-writer-capability",
                )
                invalidated = True

        store.commit_ticket115_facts = MethodType(invalidate_after_attempt, store)
        try:
            with self.assertRaises(AuthorityValidationError):
                self._effect(
                    "owner-delivery.execute",
                    {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
                    grant=grant,
                    transport=adapter,
                )
        finally:
            store.commit_ticket115_facts = original
        self.assertTrue(invalidated)
        self.assertEqual(adapter.calls, 0)

    def test_delivery_rechecks_current_evidence_revision_before_adapter(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)

        self._replace_task_source_revision(
            task_id,
            "sha256:" + ("0" * 64),
            updated_at_utc="2026-08-24T03:04:00+00:00",
        )

        adapter = _RecordingAdapter(self.base.store)
        with self.assertRaises(AuthorityValidationError):
            self._effect(
                "owner-delivery.execute",
                {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
                grant=grant,
                transport=adapter,
            )

        self.assertEqual(adapter.calls, 0)

    def test_evidence_change_after_attempt_stays_before_adapter(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        adapter = _RecordingAdapter(self.base.store)
        store = self.base.store
        original = store.commit_ticket115_facts
        invalidated = False

        def invalidate_after_attempt(this: object, **facts: object) -> None:
            nonlocal invalidated
            original(**facts)
            delivery_state = facts.get("delivery_state")
            if delivery_state is None or invalidated:
                return
            record = delivery_state.record(intent_id)
            if record.has_fact("attempted") and record.current_layer == "attempted":
                self._replace_task_source_revision(
                    task_id,
                    "sha256:" + ("0" * 64),
                    updated_at_utc="2026-08-24T03:05:00+00:00",
                )
                invalidated = True

        store.commit_ticket115_facts = MethodType(invalidate_after_attempt, store)
        try:
            with self.assertRaises(AuthorityValidationError):
                self._effect(
                    "owner-delivery.execute",
                    {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
                    grant=grant,
                    transport=adapter,
                )
        finally:
            store.commit_ticket115_facts = original

        self.assertTrue(invalidated)
        self.assertEqual(adapter.calls, 0)
        self.assertTrue(self._outbox().record(intent_id).has_fact("attempted"))

    def test_ticket115_status_domains_are_sealed_and_unknown_is_not_fault(self) -> None:
        initial = self.plugin.business_status(peer_id=_PEER).projection
        self.assertTrue(
            {"tasks", "daily_review", "delivery"}.isdisjoint(
                initial.affected_core_domains
            )
        )
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        self._effect(
            "owner-delivery.execute",
            {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
            grant=grant,
            transport=_RaisingAdapter(),
        )
        unknown = self.plugin.business_status(peer_id=_PEER).projection
        self.assertEqual(unknown.state, "cannot-confirm")
        self.assertNotIn("confirmed-fault", unknown.reason_codes)


if __name__ == "__main__":
    unittest.main()

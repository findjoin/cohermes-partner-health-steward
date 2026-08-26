"""Ticket 115 integration through the initialized owner authority stack."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import MethodType, SimpleNamespace
from unittest.mock import patch

from partner_health_steward import HealthCore, HealthPlugin, settings, status
from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.contract import ProtocolViolation, Response
from partner_health_steward.core import (
    InMemoryExecutionCapabilityVault,
)
from partner_health_steward.current_head import ExecutionLeaseIdentity, FailureMode
from partner_health_steward.delivery import (
    DeliveryOutboxState,
    OwnerDeliveryTransportResult,
    OwnerWeixinDestination,
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
    TaskAdjustment,
    TaskCandidate,
    TaskContractViolation,
    TaskEngine,
    TaskExternalBoundary,
    TaskOwnerMutation,
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
        self.owner_destination = OwnerWeixinDestination(
            partner_id=self.base.policy.partner_id,
            owner_sender_id=self.base.policy.owner_sender_id,
            conversation_id=self.base.policy.conversation_id,
            channel=self.base.policy.channel,
            entrypoint=self.base.policy.entrypoint,
        )
        self._health_command_index = 0
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

    def _restart_core(self, *, preserve_execution_vault: bool = True) -> None:
        self.assertTrue(self.base.core.close().complete)
        core = HealthCore(
            self.base.store,
            self.base.head,
            execution_capability_vault=(
                self.execution_vault
                if preserve_execution_vault
                else InMemoryExecutionCapabilityVault()
            ),
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

    def _recover_after_owner_delivery_marker_ttl(self, intent_id: str) -> None:
        _, marked_at = self.core._owner_delivery_attempts_started[intent_id]
        with patch(
            "partner_health_steward.core.time.monotonic",
            return_value=marked_at + 301.0,
        ):
            self.core.recover_owner_delivery_attempts()

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

    def _health_context(
        self,
        action: str,
        *,
        source: str | None = None,
        causal_id: str | None = None,
        generation: int | None = None,
        scope: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        self._health_command_index += 1
        return {
            "source": (
                source
                if source is not None
                else "daily_skill_runtime"
                if action == "task.admit"
                else "owner_delivery_adapter"
                if action == "delivery.observe"
                else "health_tasks"
            ),
            "causal_id": causal_id
            or f"ticket115-health-command:{self._health_command_index}:{action}",
            "generation": (
                self.base.head.read().head.generation
                if generation is None
                else generation
            ),
            "scope": list(
                (action.replace(".", ":"),) if scope is None else scope
            ),
        }

    def _health(
        self,
        action: str,
        payload: dict[str, object],
        *,
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return self.plugin.health_operation(
            action,
            payload,
            context=self._health_context(action) if context is None else context,
            peer_id=_PEER,
        )

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
        prepared = self.base._prepare(request)
        self.assertEqual(prepared.status, "accepted", prepared)
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

    def _owner_task_cancellation_request(
        self,
        task_id: str,
        *,
        suffix: str,
    ) -> object:
        snapshot = self.base.head.read().head
        current = self.store.owner_settings()
        self.assertIsNotNone(current)
        assert current is not None
        return self.base._owner_request(
            correction=False,
            settings_command=settings.ControlUpdate(
                control_name="task",
                operation="cancel",
                target_ref=task_id,
                generation=snapshot.generation,
                effective_at_utc=_ATTEMPTED_AT,
            ),
            expected_settings_version=current.version,
            command_suffix=suffix,
        )

    def _owner_task_mutation_request(
        self,
        task_id: str,
        mutation: TaskOwnerMutation,
        *,
        suffix: str,
    ) -> object:
        snapshot = self.base.head.read().head
        current = self.store.owner_settings()
        self.assertIsNotNone(current)
        assert current is not None
        nested_context = settings.OwnerCommandContext(
            command_id=f"owner-task-command:{self._testMethodName}{suffix}",
            causal_id=f"owner-task-source:{self._testMethodName}{suffix}",
            actor_kind="current_owner",
            owner_id="owner-A",
            installation_id="partner-installation",
            permission="health_settings.write",
            context_ref=f"managed-context:owner-task:{self._testMethodName}",
            generation=snapshot.generation,
            writer_fence=snapshot.writer_fence,
        )
        command = settings.OwnerControlCommand(
            context=nested_context,
            control_update=settings.ControlUpdate(
                control_name="task",
                operation=mutation.operation,
                target_ref=task_id,
                generation=snapshot.generation,
                effective_at_utc=_ATTEMPTED_AT,
            ),
            execution_scope_approval=None,
            task_mutation=mutation,
        )
        return self.base._owner_request(
            correction=False,
            settings_command=command,
            expected_settings_version=current.version,
            command_suffix=suffix,
        )

    def _candidate(
        self,
        *,
        source_revision_digest: str | None = None,
        suffix: str = "",
    ) -> tuple[TaskCandidate, str, str]:
        identifier_suffix = "" if not suffix else ":" + suffix
        purpose_suffix = "" if not suffix else " for " + suffix
        source_ref = self.base.baseline_card.evidence_id
        effect_request_id = (
            "effect-request:ticket115-review-summary" + identifier_suffix
        )
        candidate = TaskCandidate(
            candidate_id="candidate:ticket115-review-summary" + identifier_suffix,
            source_kind="portrait-evidence",
            source_ref=source_ref,
            source_revision_digest=(
                self.base.baseline_card.revision_digest
                if source_revision_digest is None
                else source_revision_digest
            ),
            purpose=(
                "send one owner-approved daily review summary" + purpose_suffix
            ),
            expected_result="the summary transport outcome is independently observed",
            assignee="partner-health-plugin",
            allowed_data_categories=("health-evidence",),
            allowed_data_refs=(source_ref,),
            external_boundary=TaskExternalBoundary(
                recipient_refs=(self.owner_destination.owner_sender_id,),
                effect_kinds=("owner-delivery",),
            ),
            phase="planned",
            approval=TaskApprovalBinding.bound(
                "approval:ticket115-review-summary" + identifier_suffix,
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
        approval_id: str = "approval:ticket115-review-summary",
        command_suffix: str = "",
        purpose: str = "send one owner-approved daily review summary",
        max_attempts: int = 1,
        min_contact_interval_seconds: int = 0,
    ) -> None:
        snapshot = self.base.head.read().head
        approval = settings.ExecutionScopeApproval(
            approval_id=approval_id,
            approval_version=1,
            owner_id="owner-A",
            installation_id="partner-installation",
            task_id=task_id,
            effect_request_id=effect_request_id,
            assignee="partner-health-plugin",
            purpose=purpose,
            allowed_data_categories=("health-evidence",),
            allowed_data_refs=(self.base.baseline_card.evidence_id,),
            first_hop_recipient=self.owner_destination.owner_sender_id,
            external_effect_kind="owner-delivery",
            max_attempts=max_attempts,
            min_contact_interval_seconds=min_contact_interval_seconds,
            expires_at_utc="2026-09-01T00:00:00+00:00",
            route_id=self.owner_destination.route_id,
            configuration_generation=self.route_fact.configuration_generation,
            disclosure_version=self.route_fact.disclosure_version,
            revoked=False,
            revoked_at_utc=None,
        )
        context = settings.OwnerCommandContext(
            command_id="settings-command:ticket115-approval" + command_suffix,
            causal_id="settings-source:ticket115-approval" + command_suffix,
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
            suffix=":ticket115-approval" + command_suffix,
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
        max_attempts: int = 1,
        min_contact_interval_seconds: int = 0,
    ) -> tuple[str, str]:
        candidate, task_id, effect_request_id = self._candidate(
            source_revision_digest=source_revision_digest
        )
        next_version = self.plugin.owner_settings_state(peer_id=_PEER).version
        if notification_enabled:
            self._enable_review_summary(expected_version=next_version)
            next_version += 1
        self._configure_approval(
            task_id,
            effect_request_id,
            expected_version=next_version,
            max_attempts=max_attempts,
            min_contact_interval_seconds=min_contact_interval_seconds,
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

    def _wake_review(
        self,
        observed_at_utc: str = _PREPARED_AT,
    ) -> DailyReviewDecision:
        self.base.owner_clock_value = datetime.fromisoformat(observed_at_utc)
        return self._decision(self._health("review.prepare", {}))

    def _commit_review_outbox(self, task_id: str, effect_request_id: str) -> str:
        prepared = self._wake_review()
        pending = prepared.ledger.pending
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending.action_refs, (task_id,))
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-24T03:01:00+00:00"
        )
        committed = self._decision(
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(prepared),
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
        self.base.owner_clock_value = datetime.fromisoformat(_ATTEMPTED_AT)
        outbox = self._outbox()
        self.assertEqual(len(outbox.records), 1)
        return outbox.records[0].intent.intent_id

    def _claimed_delivery(
        self,
        intent_id: str,
        *,
        attempted_at_utc: str = _ATTEMPTED_AT,
    ) -> object:
        prepared = self._effect(
            "owner-delivery.prepare",
            {"intent_id": intent_id, "attempted_at_utc": attempted_at_utc},
        )
        self.assertEqual(
            prepared["send_intent"]["destination"]["owner_sender_id"],
            "owner-A",
        )
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
        return grant

    def _send_opaque_intent_then_form_next_day_intent(
        self,
        task_id: str,
        *,
        first_effect_request_id: str,
        second_effect_request_id: str,
    ) -> tuple[_RecordingAdapter, str]:
        """Exercise two current intents without encoding approval-ID naming rules."""

        first_intent_id = self._commit_review_outbox(
            task_id,
            first_effect_request_id,
        )
        first_grant = self._claimed_delivery(first_intent_id)
        adapter = _RecordingAdapter(self.base.store)
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": first_intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
                "observed_at_utc": "2026-08-24T03:05:01+00:00",
            },
            grant=first_grant,
            transport=adapter,
        )
        self.assertEqual(adapter.calls, 1)

        defer_request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-24T04:00:00+00:00",
            ),
            suffix=":ticket115-verification-next-day-defer",
        )
        self.assertEqual(self.base._prepare(defer_request).status, "accepted")
        self.assertEqual(self.base._commit(defer_request).status, "accepted")
        self.assertEqual(self.base._finalize(defer_request).status, "accepted")

        second_review = self._wake_review("2026-08-25T03:00:00+00:00")
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-25T03:01:00+00:00"
        )
        second_commit = self._decision(
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(second_review),
                    "delivery": {
                        "effect_request_id": second_effect_request_id,
                        "source_task_id": task_id,
                        "payload_ref": "payload:ticket115-verification-next-day",
                        "payload_digest": "sha256:" + ("9" * 64),
                        "formed_at_utc": "2026-08-25T03:00:30+00:00",
                        "submitted_at_utc": "2026-08-25T03:01:00+00:00",
                    },
                },
            )
        )
        self.assertEqual(second_commit.outcome, "committed")
        second_intent_id = next(
            record.intent.intent_id
            for record in self._outbox().records
            if record.intent.effect_request_id == second_effect_request_id
        )
        return adapter, second_intent_id

    def test_owner_defer_uses_owner_mutation_chain_and_suppresses_review_action(self) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        claimed = self._transition(
            self._health(
                "task.claim",
                {
                    "task_id": task_id,
                    "holder_id": "task-worker:owner-defer",
                    "lease_id": "task-lease:owner-defer",
                    "acquired_at_utc": "2026-08-24T03:01:00+00:00",
                },
            )
        )
        self.assertEqual(claimed.outcome, "claimed")
        request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-24T04:00:00+00:00",
            ),
            suffix=":ticket115-owner-task-defer",
        )

        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

        task = self._task_state().task(task_id)
        self.assertEqual(task.primary_label, "active")
        self.assertEqual(task.deferred_until_utc, "2026-08-24T04:00:00+00:00")
        self.assertEqual(self._task_state().active_claims, ())
        visible_task = next(
            item
            for item in self._ticket115_read()["tasks"]
            if item["task_id"] == task_id
        )
        self.assertEqual(
            visible_task["deferred_until_utc"],
            "2026-08-24T04:00:00+00:00",
        )
        self.assertNotIn(
            "deferred_until_utc",
            self.store.owner_settings().to_wire()["controls"],
        )

        pending = self._wake_review("2026-08-24T03:30:00+00:00").ledger.pending
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending.action_refs, ())

    def test_owner_cancel_clears_defer_fact_through_owner_mutation_chain(self) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        defer_request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-24T04:00:00+00:00",
            ),
            suffix=":ticket115-owner-task-defer-before-cancel",
        )
        self.assertEqual(self.base._prepare(defer_request).status, "accepted")
        self.assertEqual(self.base._commit(defer_request).status, "accepted")
        self.assertEqual(self.base._finalize(defer_request).status, "accepted")

        cancel_request = self._owner_task_cancellation_request(
            task_id,
            suffix=":ticket115-owner-task-cancel-after-defer",
        )
        self.assertEqual(self.base._prepare(cancel_request).status, "accepted")
        self.assertEqual(self.base._commit(cancel_request).status, "accepted")
        self.assertEqual(self.base._finalize(cancel_request).status, "accepted")

        task = self._task_state().task(task_id)
        self.assertEqual(task.primary_label, "cancelled")
        self.assertIsNone(task.deferred_until_utc)

    def test_review_after_defer_expiry_detects_restored_actionable_set(self) -> None:
        task_id, _ = self._admit_review_task()
        defer_request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-24T04:00:00+00:00",
            ),
            suffix=":ticket115-review-expiry",
        )
        self.assertEqual(self.base._prepare(defer_request).status, "accepted")
        self.assertEqual(self.base._commit(defer_request).status, "accepted")
        self.assertEqual(self.base._finalize(defer_request).status, "accepted")

        quiet = self._wake_review("2026-08-24T03:30:00+00:00")
        self.assertEqual(quiet.ledger.pending.action_refs, ())  # type: ignore[union-attr]
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-24T03:31:00+00:00"
        )
        committed = self._decision(
            self._health(
                "review.commit",
                {"decision": self._decision_wire(quiet)},
            )
        )
        self.assertIsNotNone(committed.record)
        assert committed.record is not None

        expired = self._wake_review("2026-08-25T03:00:00+00:00")
        pending = expired.ledger.pending
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertTrue(pending.changed)
        self.assertEqual(pending.action_refs, (task_id,))
        self.assertTrue(pending.notification_required)
        self.assertEqual(pending.state_digest, committed.record.state_digest)

    def test_owner_in_scope_adjustment_is_atomic_and_invalidates_old_version(self) -> None:
        candidate, _, effect_request_id = self._candidate()
        candidate = replace(
            candidate,
            allowed_data_categories=("health-evidence", "owner-action"),
        )
        task_id = (
            "task:"
            + candidate.semantic_digest.removeprefix("sha256:")[:32]
            + ":1"
        )
        next_version = self.plugin.owner_settings_state(peer_id=_PEER).version
        self._configure_approval(task_id, effect_request_id, expected_version=next_version)
        self._transition(
            self._health(
                "task.admit",
                {
                    "candidate": candidate.to_storage(),
                    "committed_at_utc": _PREPARED_AT,
                },
            )
        )
        claimed = self._transition(
            self._health(
                "task.claim",
                {
                    "task_id": task_id,
                    "holder_id": "task-worker:owner-adjust",
                    "lease_id": "task-lease:owner-adjust",
                    "acquired_at_utc": "2026-08-24T03:01:00+00:00",
                },
            )
        )
        before = self._task_state().task(task_id)
        self.assertEqual(claimed.task_id, task_id)
        request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.adjust(
                task_id,
                TaskAdjustment(allowed_data_categories=("health-evidence",)),
            ),
            suffix=":ticket115-owner-task-adjust",
        )

        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

        after = self._task_state().task(task_id)
        self.assertEqual(after.task_id, before.task_id)
        self.assertEqual(after.version, before.version + 1)
        self.assertEqual(after.allowed_data_categories, ("health-evidence",))
        self.assertEqual(self._task_state().active_claims, ())

    def test_owner_scope_expansion_creates_successor_without_trusting_caller_scope_flag(self) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.adjust(
                task_id,
                TaskAdjustment(
                    assignee="external-sleep-coach",
                    allowed_data_refs=(
                        "portrait-topic:sleep",
                        "owner-provided:sleep-diary",
                    ),
                ),
            ),
            suffix=":ticket115-owner-task-expand",
        )

        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

        state = self._task_state()
        predecessor = state.task(task_id)
        self.assertEqual(len(state.tasks), 2)
        successor = state.task(predecessor.successor_task_ids[0])
        self.assertEqual(successor.predecessor_task_ids, (task_id,))
        self.assertEqual(successor.phase, "waiting-approval")
        self.assertEqual(successor.approval.status, "waiting")
        self.assertEqual(successor.primary_label, "active")

    def test_owner_defer_replay_is_idempotent_and_finalize_rollback_keeps_prepared_state(self) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-24T04:00:00+00:00",
            ),
            suffix=":ticket115-owner-task-defer-replay",
        )
        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        stored = self.store.owner_mutation(request.context.command_id)
        self.assertIsNotNone(stored)
        assert stored is not None and stored.prepared is not None
        before_settings = self.store.owner_settings()
        before_tasks = self.store.task_runtime()
        self.assertIsInstance(before_tasks, TaskRuntimeState)
        assert isinstance(before_tasks, TaskRuntimeState)
        deferred = TaskEngine.apply_owner_mutation(
            before_tasks,
            request.settings_command.task_mutation,  # type: ignore[union-attr]
            control_ref=request.context.command_id,
            effective_at_utc=_ATTEMPTED_AT,
        )
        original = self.store._write_task_runtime

        def fail_task_write(this: object, connection: object, state: object) -> None:
            del this, connection, state
            raise StoreUnavailable("synthetic owner task defer failure")

        self.store._write_task_runtime = MethodType(fail_task_write, self.store)
        try:
            with self.assertRaisesRegex(StoreUnavailable, "synthetic owner task defer failure"):
                self.store.finalize_owner_mutation(
                    stored.prepared,
                    task_state=deferred.state,
                )
        finally:
            self.store._write_task_runtime = original

        self.assertEqual(self.store.owner_settings(), before_settings)
        self.assertEqual(self.store.task_runtime(), before_tasks)
        self.assertEqual(
            self.store.owner_mutation(request.context.command_id).phase,
            "prepared",
        )

        self.assertEqual(self.base._finalize(request).status, "accepted")
        first = self._task_state()
        replayed = self.base._finalize(request)
        self.assertIn(replayed.status, {"accepted", "replayed"})
        self.assertEqual(self._task_state(), first)

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
        prepared = self._wake_review()

        self._restart_core()

        restored = self._task_state()
        self.assertEqual(restored.active_claims[0].lease_id, "task-lease:ticket115")
        resumed = self._wake_review(
            "2026-08-24T03:30:00+00:00"
        )
        self.assertEqual(resumed.outcome, "resume-current-day")
        self.assertTrue(resumed.replayed)
        self.assertEqual(resumed.ledger, prepared.ledger)

    def test_task_mutation_advances_current_head_before_local_visibility(self) -> None:
        candidate, task_id, _ = self._candidate()
        before = self.base.head.read().head
        self.base.head.set_failure(
            FailureMode.UNKNOWN_AFTER_ADVANCE,
            operation="advance",
        )

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "current-head-unknown",
        ):
            self.core.admit_task_candidate(
                candidate,
                committed_at_utc=_PREPARED_AT,
            )

        advanced = self.base.head.read().head
        self.assertEqual(advanced.generation, before.generation + 1)
        self.assertIsNone(self.base.store.task_runtime())
        pending = self.base.store.pending_ticket115_mutation()
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(
            self.base.store.record(pending.prepared.target.record_id).state,
            "unknown",
        )

        self.base.head.clear_failure()
        self._restart_core()
        restored = self.core.task_state()
        self.assertEqual(restored.task(task_id).task_id, task_id)
        self.assertIsNone(self.base.store.pending_ticket115_mutation())
        self.assertEqual(
            self.base.store.record(pending.prepared.target.record_id).state,
            "final",
        )
        self.assertEqual(
            self.base.store.finalized_authority(),
            self.base.head.read().head.as_authority(),
        )

    def test_review_and_outbox_business_commits_each_advance_current_head(
        self,
    ) -> None:
        task_id, effect_request_id = self._admit_review_task()
        before_prepare = self.base.head.read().head
        prepared = self._wake_review()
        pending = prepared.ledger.pending
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending.prepared_at_utc, _PREPARED_AT)
        self.assertTrue(pending.changed)
        self.assertEqual(pending.action_refs, (task_id,))
        after_prepare = self.base.head.read().head
        self.assertEqual(
            after_prepare.generation,
            before_prepare.generation + 1,
        )

        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-24T03:01:00+00:00"
        )
        committed = self._decision(
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(prepared),
                    "delivery": {
                        "effect_request_id": effect_request_id,
                        "source_task_id": task_id,
                        "payload_ref": "payload:ticket115-cas-review-summary",
                        "payload_digest": "sha256:" + ("6" * 64),
                        "formed_at_utc": "2026-08-24T03:00:30+00:00",
                        "submitted_at_utc": "2026-08-24T03:01:00+00:00",
                    },
                },
            )
        )
        self.assertIsNotNone(committed.record)
        assert committed.record is not None
        self.assertEqual(
            committed.record.completed_at_utc,
            "2026-08-24T03:01:00+00:00",
        )

        after_commit = self.base.head.read().head
        self.assertEqual(
            after_commit.generation,
            after_prepare.generation + 1,
        )
        self.assertEqual(
            self.base.store.finalized_authority(),
            after_commit.as_authority(),
        )
        self.assertEqual(len(self._outbox().records), 1)

    def test_refreshed_current_day_review_can_commit_through_plugin_wire(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        first = self._wake_review()
        self.assertEqual(first.outcome, "prepared")

        self._transition(
            self._health(
                "task.advance",
                {
                    "task_id": task_id,
                    "phase": "in-progress",
                    "advanced_at_utc": "2026-08-24T03:00:30+00:00",
                },
            )
        )
        refreshed = self._wake_review("2026-08-24T03:01:00+00:00")
        self.assertEqual(refreshed.outcome, "current-day-pending-refreshed")

        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-24T03:02:00+00:00"
        )
        committed = self._decision(
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(refreshed),
                    "delivery": {
                        "effect_request_id": effect_request_id,
                        "source_task_id": task_id,
                        "payload_ref": "payload:ticket115-refreshed-review-summary",
                        "payload_digest": "sha256:" + ("5" * 64),
                        "formed_at_utc": "2026-08-24T03:01:30+00:00",
                        "submitted_at_utc": "2026-08-24T03:02:00+00:00",
                    },
                },
            )
        )

        self.assertEqual(committed.outcome, "committed")
        self.assertIsNone(committed.ledger.pending)
        self.assertEqual(len(self._outbox().records), 1)

    def test_review_plugin_inputs_are_wake_only(self) -> None:
        with self.assertRaises(ProtocolViolation):
            self._health(
                "review.prepare",
                {
                    "observed_at_utc": _PREPARED_AT,
                    "action_refs": [],
                    "changed": False,
                },
            )

        prepared = self._wake_review()
        with self.assertRaises(ProtocolViolation):
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(prepared),
                    "completed_at_utc": "2026-08-24T03:01:00+00:00",
                },
            )

    def test_health_operation_requires_complete_trusted_context(self) -> None:
        before = self.base.head.read().head

        with self.assertRaises(ProtocolViolation):
            self.plugin.health_operation(
                "review.prepare",
                {},
                peer_id=_PEER,
            )

        complete = self._health_context(
            "review.prepare",
            causal_id="ticket115-complete-context-template",
        )
        for missing in ("source", "causal_id", "generation", "scope"):
            context = dict(complete)
            context.pop(missing)
            with self.subTest(missing=missing):
                with self.assertRaises(ProtocolViolation):
                    self._health("review.prepare", {}, context=context)
        with self.assertRaises(ProtocolViolation):
            self._health(
                "review.prepare",
                {},
                context={**complete, "unexpected": "authority"},
            )

        self.assertEqual(self.base.head.read().head, before)
        self.assertIsNone(self.base.store.pending_ticket115_mutation())

    def test_health_command_source_scope_and_generation_are_exact(self) -> None:
        before = self.base.head.read().head
        invalid_contexts = (
            self._health_context(
                "review.prepare",
                source="health-records",
                causal_id="ticket115-untrusted-skill-source",
            ),
            self._health_context(
                "review.prepare",
                causal_id="ticket115-empty-health-scope",
                scope=(),
            ),
            self._health_context(
                "review.prepare",
                causal_id="ticket115-extra-health-scope",
                scope=("review:prepare", "task:claim"),
            ),
            self._health_context(
                "review.prepare",
                causal_id="ticket115-stale-health-generation",
                generation=before.generation - 1,
            ),
            self._health_context(
                "review.prepare",
                causal_id="ticket115-future-health-generation",
                generation=before.generation + 1,
            ),
        )

        for context in invalid_contexts:
            with self.subTest(context=context):
                with self.assertRaises(ProtocolViolation):
                    self._health("review.prepare", {}, context=context)
                self.assertEqual(self.base.head.read().head, before)
                self.assertIsNone(self.base.store.pending_ticket115_mutation())

        with self.assertRaises(ProtocolViolation):
            self._health(
                "task.cancel",
                {
                    "task_id": "task:untrusted-owner-cancellation",
                    "cancelled_at_utc": _PREPARED_AT,
                },
                context=self._health_context(
                    "task.cancel",
                    causal_id="ticket115-direct-task-cancel-forbidden",
                ),
            )

        for action in ("task.advance", "delivery.observe"):
            with self.subTest(action=action):
                with self.assertRaises(ProtocolViolation):
                    self._health(
                        action,
                        {},
                        context=self._health_context(
                            action,
                            source="health-records",
                            causal_id=f"ticket115-b-skill-denied:{action}",
                        ),
                    )

        for action in ("task.defer", "task.adjust"):
            with self.subTest(action=action):
                with self.assertRaises(ProtocolViolation):
                    self._health(
                        action,
                        {},
                        context=self._health_context(
                            action,
                            causal_id=f"ticket115-direct-health-forbidden:{action}",
                        ),
                    )
        self.assertEqual(self.base.head.read().head, before)

    def test_health_command_exact_replay_and_causal_conflict_survive_restart(
        self,
    ) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        generation = self.base.head.read().head.generation
        context = self._health_context(
            "task.claim",
            causal_id="ticket115-trusted-claim-replay",
            generation=generation,
        )
        payload = {
            "task_id": task_id,
            "holder_id": "task-worker:trusted-replay",
            "lease_id": "task-lease:trusted-replay",
            "acquired_at_utc": _PREPARED_AT,
        }

        first = self._health("task.claim", payload, context=context)
        after_first = self.base.head.read().head
        self.assertEqual(after_first.generation, generation + 1)

        self._restart_core()
        replayed = self._health("task.claim", payload, context=context)
        self.assertEqual(replayed, first)
        self.assertEqual(self.base.head.read().head, after_first)

        conflicting = dict(payload)
        conflicting["holder_id"] = "task-worker:causal-conflict"
        with self.assertRaisesRegex(ProtocolViolation, "causal-id-conflict"):
            self._health("task.claim", conflicting, context=context)
        self.assertEqual(self.base.head.read().head, after_first)
        self.assertEqual(
            self._task_state().active_claims[0].holder_id,
            "task-worker:trusted-replay",
        )

    def test_health_command_rechecks_exact_replay_inside_the_write_lane(
        self,
    ) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        generation = self.base.head.read().head.generation
        context = self._health_context(
            "task.claim",
            causal_id="ticket115-interleaved-claim-replay",
            generation=generation,
        )
        payload = {
            "task_id": task_id,
            "holder_id": "task-worker:interleaved-replay",
            "lease_id": "task-lease:interleaved-replay",
            "acquired_at_utc": _PREPARED_AT,
        }
        original_write_authority = self.core._ticket115_write_authority
        interleaved: dict[str, object] = {}
        injecting = False

        @contextmanager
        def interleaving_write_authority(core: HealthCore):
            nonlocal injecting
            del core
            with original_write_authority() as authority:
                yield authority
            if not injecting and "result" not in interleaved:
                injecting = True
                try:
                    interleaved["result"] = self._health(
                        "task.claim",
                        payload,
                        context=context,
                    )
                finally:
                    injecting = False

        self.core._ticket115_write_authority = MethodType(
            interleaving_write_authority,
            self.core,
        )
        try:
            replayed = self._health("task.claim", payload, context=context)
        finally:
            self.core._ticket115_write_authority = original_write_authority

        self.assertEqual(replayed, interleaved["result"])
        self.assertFalse(replayed["replayed"])
        self.assertEqual(
            self.base.head.read().head.generation,
            generation + 1,
        )
        self.assertEqual(len(self._task_state().active_claims), 1)

    def test_health_command_rechecks_generation_inside_the_write_lane(
        self,
    ) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        generation = self.base.head.read().head.generation
        context = self._health_context(
            "task.claim",
            causal_id="ticket115-interleaved-stale-generation",
            generation=generation,
        )
        payload = {
            "task_id": task_id,
            "holder_id": "task-worker:must-not-claim",
            "lease_id": "task-lease:must-not-claim",
            "acquired_at_utc": _PREPARED_AT,
        }
        original_write_authority = self.core._ticket115_write_authority
        injecting = False
        injected = False

        @contextmanager
        def interleaving_write_authority(core: HealthCore):
            nonlocal injected, injecting
            del core
            with original_write_authority() as authority:
                yield authority
            if not injecting and not injected:
                injecting = True
                injected = True
                try:
                    self.core.advance_task_phase(
                        task_id,
                        phase="awaiting-result",
                        advanced_at_utc="2026-08-24T03:00:01+00:00",
                    )
                finally:
                    injecting = False

        self.core._ticket115_write_authority = MethodType(
            interleaving_write_authority,
            self.core,
        )
        try:
            with self.assertRaisesRegex(ProtocolViolation, "generation mismatch"):
                self._health("task.claim", payload, context=context)
        finally:
            self.core._ticket115_write_authority = original_write_authority

        self.assertTrue(injected)
        self.assertEqual(
            self.base.head.read().head.generation,
            generation + 1,
        )
        task_state = self._task_state()
        self.assertEqual(task_state.task(task_id).phase, "awaiting-result")
        self.assertEqual(task_state.active_claims, ())

    def test_health_command_unknown_cas_recovers_exact_causal_owner(self) -> None:
        candidate, task_id, _ = self._candidate()
        before = self.base.head.read().head
        context = self._health_context(
            "task.admit",
            causal_id="ticket115-health-command-unknown-cas",
            generation=before.generation,
        )
        payload = {
            "candidate": candidate.to_storage(),
            "committed_at_utc": _PREPARED_AT,
        }
        self.base.head.set_failure(
            FailureMode.UNKNOWN_AFTER_ADVANCE,
            operation="advance",
        )

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "current-head-unknown",
        ):
            self._health("task.admit", payload, context=context)

        advanced = self.base.head.read().head
        pending = self.base.store.pending_ticket115_mutation()
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertIsNotNone(pending.health_command_receipt)
        self.base.head.clear_failure()
        self._restart_core()

        conflicting = dict(payload)
        conflicting["committed_at_utc"] = "2026-08-24T03:00:01+00:00"
        with self.assertRaisesRegex(ProtocolViolation, "causal-id-conflict"):
            self._health("task.admit", conflicting, context=context)
        replayed = self._health("task.admit", payload, context=context)

        self.assertEqual(replayed["task_id"], task_id)
        self.assertEqual(self.base.head.read().head, advanced)
        self.assertEqual(self._task_state().task(task_id).task_id, task_id)
        self.assertIsNone(self.base.store.pending_ticket115_mutation())

    def test_receipt_only_review_replay_still_uses_ticket115_finalize(self) -> None:
        prepared = self._wake_review()
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-24T03:01:00+00:00"
        )
        self._health(
            "review.commit",
            {"decision": self._decision_wire(prepared)},
        )

        already_completed = self._wake_review(
            "2026-08-24T03:02:00+00:00"
        )
        self.assertEqual(already_completed.outcome, "already-completed")
        seen: list[object] = []
        original = self.core._complete_ticket115_mutation

        def capture_completion(this: object, mutation: object) -> None:
            seen.append(mutation)
            original(mutation)  # type: ignore[arg-type]

        self.core._complete_ticket115_mutation = MethodType(
            capture_completion,
            self.core,
        )
        try:
            self._health(
                "review.commit",
                {"decision": self._decision_wire(already_completed)},
            )
        finally:
            self.core._complete_ticket115_mutation = original

        self.assertEqual(len(seen), 1)
        mutation = seen[0]
        self.assertIsNotNone(mutation)
        assert mutation is not None
        self.assertIsNotNone(mutation.health_command_receipt)

    def test_next_local_day_derives_unchanged_from_last_completed_review(
        self,
    ) -> None:
        first = self._wake_review()
        first_pending = first.ledger.pending
        self.assertIsNotNone(first_pending)
        assert first_pending is not None
        self.assertTrue(first_pending.changed)
        self.assertEqual(first_pending.action_refs, ())

        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-24T03:01:00+00:00"
        )
        self._health(
            "review.commit",
            {"decision": self._decision_wire(first)},
        )

        next_day = self._wake_review("2026-08-25T03:00:00+00:00")
        pending = next_day.ledger.pending
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertFalse(pending.changed)
        self.assertEqual(pending.action_refs, ())
        self.assertFalse(pending.notification_required)

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
        prepared = self._wake_review()
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-24T16:01:00+00:00"
        )
        with self.assertRaises(ReviewContractViolation):
            self._health(
                "review.commit",
                {"decision": self._decision_wire(prepared)},
            )

        self._health(
            "task.advance",
            {
                "task_id": task_id,
                "phase": "in-progress",
                "advanced_at_utc": "2026-08-24T03:40:00+00:00",
            },
        )
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-24T04:00:00+00:00"
        )
        with self.assertRaises(ReviewContractViolation):
            self._health(
                "review.commit",
                {"decision": self._decision_wire(prepared)},
            )

    def test_review_and_outbox_rollback_together(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        prepared = self._wake_review()
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-24T03:01:00+00:00"
        )
        store = self.base.store
        original = store._write_delivery_outbox

        def fail_atomic_commit(
            this: object,
            connection: object,
            state: object,
        ) -> None:
            del this, connection, state
            raise StoreUnavailable("synthetic ticket115 outbox failure")

        store._write_delivery_outbox = MethodType(
            fail_atomic_commit,
            store,
        )
        try:
            with self.assertRaisesRegex(
                AuthorityValidationError,
                "health-state-unavailable",
            ):
                self._health(
                    "review.commit",
                    {
                        "decision": self._decision_wire(prepared),
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
            durable_review = store.daily_review_ledger()
            self.assertIsNotNone(durable_review)
            assert durable_review is not None
            self.assertIsNotNone(durable_review.pending)
            self.assertEqual(
                store.delivery_outbox_state(
                    "owner-A",
                    "partner-installation",
                ).records,
                (),
            )
        finally:
            store._write_delivery_outbox = original
        self.assertIsNone(self._review_ledger().pending)
        self.assertEqual(
            len(self._outbox().records),
            1,
        )

    def test_not_configured_notification_never_reaches_adapter(self) -> None:
        task_id, _ = self._admit_review_task(
            notification_enabled=False
        )
        prepared = self._wake_review()
        pending = prepared.ledger.pending
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertNotIn(task_id, pending.action_refs)
        self.assertFalse(pending.notification_required)
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-24T03:01:00+00:00"
        )
        committed = self._decision(
            self._health(
                "review.commit",
                {"decision": self._decision_wire(prepared)},
            )
        )
        self.assertFalse(committed.notification_required)
        self.assertEqual(self._outbox().records, ())
        self.assertEqual(self.base.store.unresolved_effects(), ())

    def test_stale_evidence_binding_does_not_issue_generic_effect(self) -> None:
        task_id, _ = self._admit_review_task(
            source_revision_digest="sha256:" + ("0" * 64)
        )
        prepared = self._wake_review()
        pending = prepared.ledger.pending
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertNotIn(task_id, pending.action_refs)
        self.assertFalse(pending.notification_required)
        self.assertEqual(self._outbox().records, ())
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

    def test_attempt_for_other_approval_does_not_consume_new_approval(self) -> None:
        first_task_id, first_effect_request_id = self._admit_review_task()
        first_intent_id = self._commit_review_outbox(
            first_task_id,
            first_effect_request_id,
        )
        self._effect(
            "owner-delivery.prepare",
            {
                "intent_id": first_intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
            },
        )

        candidate, second_task_id, second_effect_request_id = self._candidate(
            suffix="second",
        )
        current_settings = self.base.store.owner_settings()
        self.assertIsNotNone(current_settings)
        assert current_settings is not None
        self._configure_approval(
            second_task_id,
            second_effect_request_id,
            expected_version=current_settings.version,
            approval_id="approval:ticket115-review-summary:second",
            command_suffix=":second",
            purpose="send one owner-approved daily review summary for second",
        )
        self._health(
            "task.admit",
            {
                "candidate": candidate.to_storage(),
                "committed_at_utc": "2026-08-24T03:06:00+00:00",
            },
        )

        prepared = self._wake_review("2026-08-25T03:00:00+00:00")
        pending = prepared.ledger.pending
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending.action_refs, (second_task_id,))
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-25T03:01:00+00:00"
        )
        self._health(
            "review.commit",
            {
                "decision": self._decision_wire(prepared),
                "delivery": {
                    "effect_request_id": second_effect_request_id,
                    "source_task_id": second_task_id,
                    "payload_ref": "payload:ticket115-review-summary:second",
                    "payload_digest": "sha256:" + ("9" * 64),
                    "formed_at_utc": "2026-08-25T03:00:30+00:00",
                    "submitted_at_utc": "2026-08-25T03:01:00+00:00",
                },
            },
        )
        second_intent_id = next(
            record.intent.intent_id
            for record in self._outbox().records
            if record.intent.effect_request_id == second_effect_request_id
        )
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-25T03:05:00+00:00"
        )

        prepared_attempt = self._effect(
            "owner-delivery.prepare",
            {
                "intent_id": second_intent_id,
                "attempted_at_utc": "2026-08-25T03:05:00+00:00",
            },
        )

        self.assertEqual(
            prepared_attempt["send_intent"]["intent_id"],
            second_intent_id,
        )

    def test_reconsented_route_generation_is_bound_through_owner_delivery(self) -> None:
        self.route_fact = replace(
            self.route_fact,
            configuration_generation=2,
            generation=2,
        )
        drifted = self.plugin.owner_settings_state(peer_id=_PEER)
        self.assertEqual(drifted.consent_path_status, "paused")
        self.assertEqual(drifted.current_configuration_generation, 2)

        snapshot = self.base.head.read().head
        renewal = settings.ConsentRenewal(
            renewal_id="consent-renewal:ticket115-route-generation-2",
            context=settings.OwnerCommandContext(
                command_id="settings-command:ticket115-route-generation-2",
                causal_id="settings-source:ticket115-route-generation-2",
                actor_kind="current_owner",
                owner_id="owner-A",
                installation_id="partner-installation",
                permission="health_settings.write",
                context_ref="managed-context:ticket115-route-generation-2",
                generation=snapshot.generation,
                writer_fence=snapshot.writer_fence,
            ),
            route_id=self.route_fact.route_id,
            first_hop_recipient=self.route_fact.first_hop_recipient,
            configuration_generation=2,
            disclosure_version=self.route_fact.disclosure_version,
            disclosure_digest="sha256:" + ("e" * 64),
            consented_at_utc="2026-08-24T02:00:00+00:00",
        )
        self._apply_owner_setting(
            renewal,
            expected_version=drifted.version,
            suffix=":ticket115-route-generation-2",
        )
        renewed = self.plugin.owner_settings_state(peer_id=_PEER)
        self.assertEqual(renewed.consent_path_status, "active")
        self.assertEqual(renewed.consent_configuration_generation, 2)

        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        intent = self._outbox().record(intent_id).intent
        self.assertEqual(intent.route_generation, 2)

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

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(
            OwnerDeliveryTransportResult.from_wire(
                executed["transport_result"]
            ).status,
            "accepted",
        )

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

    def test_unknown_owner_delivery_forms_one_independent_owner_decision_request(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        adapter = _RaisingAdapter()

        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
                "observed_at_utc": "2026-08-24T03:05:01+00:00",
            },
            grant=grant,
            transport=adapter,
        )

        records = self._outbox().records
        self.assertEqual(len(records), 2)
        decision_records = tuple(
            record for record in records if record.intent.intent_id != intent_id
        )
        self.assertEqual(len(decision_records), 1)
        decision = decision_records[0]
        self.assertNotEqual(decision.intent.effect_request_id, effect_request_id)
        self.assertNotEqual(decision.intent.intent_id, intent_id)
        self.assertEqual(adapter.calls, 1)

        decision_id = decision.intent.intent_id
        self._restart_core()
        decision_adapter = _RecordingAdapter(self.base.store)
        decision_attempted_at = "2026-08-24T03:06:01+00:00"
        decision_grant = self._claimed_delivery(
            decision_id,
            attempted_at_utc=decision_attempted_at,
        )
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": decision_id,
                "attempted_at_utc": decision_attempted_at,
                "observed_at_utc": "2026-08-24T03:06:02+00:00",
            },
            grant=decision_grant,
            transport=decision_adapter,
        )
        self.assertEqual(decision_adapter.calls, 1)
        self.assertEqual(len(self._outbox().records), 2)
        self._restart_core()
        self.assertEqual(len(self._outbox().records), 2)

    def test_ticket115_status_transition_forms_one_current_owner_decision_request(self) -> None:
        prior = status.StatusProjection(
            state="active",
            evaluated_at_utc="2026-08-24T11:59:00+00:00",
            affected_core_domains=(),
            isolated_noncore_domains=(),
            reason_codes=(),
            fact_set_digest="sha256:" + ("f" * 64),
        )
        self.assertIsNone(self.store.remember_business_status(prior))
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
                "observed_at_utc": "2026-08-24T03:05:01+00:00",
            },
            grant=grant,
            transport=_RaisingAdapter(),
        )

        first = self.plugin.business_status(peer_id=_PEER)
        self.assertIsNotNone(first.transition)
        assert first.transition is not None
        self.assertTrue(
            {"tasks", "delivery"}.intersection(first.transition.affected_core_domains)
        )
        records = self._outbox().records
        status_records = tuple(
            record
            for record in records
            if record.intent.source_ref == first.transition.transition_id
        )
        self.assertEqual(len(status_records), 1)
        replay = self.plugin.business_status(peer_id=_PEER)
        self.assertIsNone(replay.transition)
        self.assertEqual(
            len(
                tuple(
                    record
                    for record in self._outbox().records
                    if record.intent.source_ref == first.transition.transition_id
                )
            ),
            1,
        )

        status_intent_id = status_records[0].intent.intent_id
        status_attempted_at = "2026-08-24T12:01:00+00:00"
        try:
            status_grant = self._claimed_delivery(
                status_intent_id,
                attempted_at_utc=status_attempted_at,
            )
        except AuthorityValidationError as exc:
            self.fail(f"current status request became unsendable: {exc}")
        status_adapter = _RecordingAdapter(self.base.store)
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": status_intent_id,
                "attempted_at_utc": status_attempted_at,
                "observed_at_utc": "2026-08-24T12:01:01+00:00",
            },
            grant=status_grant,
            transport=status_adapter,
        )
        self.assertEqual(status_adapter.calls, 1)

    def test_review_delivery_cannot_forge_mandatory_owner_decision_identity(self) -> None:
        task_id, _ = self._admit_review_task()
        forged_effect_request_id = "owner-decision:status-transition:forged"
        intent_id = self._commit_review_outbox(task_id, forged_effect_request_id)
        adapter = _RecordingAdapter(self.base.store)

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner-delivery-authorization-required",
        ):
            self._effect(
                "owner-delivery.prepare",
                {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
            )

        self.assertEqual(adapter.calls, 0)

    def test_approval_attempt_limit_survives_multiple_defer_expiry_intents(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        old_intent_id = self._commit_review_outbox(task_id, effect_request_id)
        first_defer = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-24T04:00:00+00:00",
            ),
            suffix=":ticket115-attempt-limit-first-defer",
        )
        self.assertEqual(self.base._prepare(first_defer).status, "accepted")
        self.assertEqual(self.base._commit(first_defer).status, "accepted")
        self.assertEqual(self.base._finalize(first_defer).status, "accepted")

        first_review = self._wake_review("2026-08-25T03:00:00+00:00")
        first_effect_request_id = effect_request_id + ":ticket115-attempt-limit-first"
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-25T03:01:00+00:00"
        )
        first_commit = self._decision(
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(first_review),
                    "delivery": {
                        "effect_request_id": first_effect_request_id,
                        "source_task_id": task_id,
                        "payload_ref": "payload:ticket115-attempt-limit-first",
                        "payload_digest": "sha256:" + ("a" * 64),
                        "formed_at_utc": "2026-08-25T03:00:30+00:00",
                        "submitted_at_utc": "2026-08-25T03:01:00+00:00",
                    },
                },
            )
        )
        self.assertEqual(first_commit.outcome, "committed")
        first_intent_id = next(
            record.intent.intent_id
            for record in self._outbox().records
            if record.intent.effect_request_id == first_effect_request_id
        )
        first_attempted_at_utc = "2026-08-25T03:05:00+00:00"
        first_grant = self._claimed_delivery(
            first_intent_id,
            attempted_at_utc=first_attempted_at_utc,
        )
        adapter = _RecordingAdapter(self.base.store)
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": first_intent_id,
                "attempted_at_utc": first_attempted_at_utc,
            },
            grant=first_grant,
            transport=adapter,
        )
        self.assertEqual(adapter.calls, 1)

        second_defer = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-25T04:00:00+00:00",
            ),
            suffix=":ticket115-attempt-limit-second-defer",
        )
        self.assertEqual(self.base._prepare(second_defer).status, "accepted")
        self.assertEqual(self.base._commit(second_defer).status, "accepted")
        self.assertEqual(self.base._finalize(second_defer).status, "accepted")

        second_review = self._wake_review("2026-08-26T03:00:00+00:00")
        second_effect_request_id = effect_request_id + ":ticket115-attempt-limit-second"
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-26T03:01:00+00:00"
        )
        second_commit = self._decision(
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(second_review),
                    "delivery": {
                        "effect_request_id": second_effect_request_id,
                        "source_task_id": task_id,
                        "payload_ref": "payload:ticket115-attempt-limit-second",
                        "payload_digest": "sha256:" + ("b" * 64),
                        "formed_at_utc": "2026-08-26T03:00:30+00:00",
                        "submitted_at_utc": "2026-08-26T03:01:00+00:00",
                    },
                },
            )
        )
        self.assertEqual(second_commit.outcome, "committed")
        second_intent_id = next(
            record.intent.intent_id
            for record in self._outbox().records
            if record.intent.effect_request_id == second_effect_request_id
        )

        with self.assertRaises(AuthorityValidationError):
            self._effect(
                "owner-delivery.prepare",
                {
                    "intent_id": second_intent_id,
                    "attempted_at_utc": "2026-08-26T03:01:01+00:00",
                },
            )
        self.assertEqual(adapter.calls, 1)

    def test_nonactive_to_nonactive_status_change_is_not_mandatory(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
                "observed_at_utc": "2026-08-24T03:05:01+00:00",
            },
            grant=grant,
            transport=_RaisingAdapter(),
        )
        prior = status.StatusProjection(
            state="abnormal",
            evaluated_at_utc="2026-08-24T11:59:00+00:00",
            affected_core_domains=("tasks",),
            isolated_noncore_domains=(),
            reason_codes=("synthetic-prior-abnormal",),
            fact_set_digest="sha256:" + ("e" * 64),
        )
        self.assertIsNone(self.store.remember_business_status(prior))

        result = self.plugin.business_status(peer_id=_PEER)

        self.assertIsNotNone(result.transition)
        assert result.transition is not None
        self.assertEqual(result.transition.previous_state, "abnormal")
        self.assertEqual(result.transition.current_state, "cannot-confirm")
        status_records = tuple(
            record
            for record in self._outbox().records
            if record.intent.effect_request_id.startswith(
                "owner-decision:status-transition:"
            )
        )
        self.assertEqual(status_records, ())

    def test_attempted_delivery_can_settle_unknown_after_defer_without_retry(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)

        prepared = self._effect(
            "owner-delivery.prepare",
            {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
        )
        adapter = _RaisingAdapter()
        with self.assertRaisesRegex(RuntimeError, "synthetic owner delivery transport failure"):
            adapter.send(prepared["send_intent"])

        defer_request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-24T04:00:00+00:00",
            ),
            suffix=":ticket115-attempted-then-defer",
        )
        self.assertEqual(self.base._prepare(defer_request).status, "accepted")
        self.assertEqual(self.base._commit(defer_request).status, "accepted")
        self.assertEqual(self.base._finalize(defer_request).status, "accepted")

        self._recover_after_owner_delivery_marker_ttl(intent_id)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(
            self._outbox().record(intent_id).current_layer,
            "unknown",
        )
        self.assertIn(intent_id, self._task_state().delivery_unknown_refs)
        self.assertEqual(
            self._task_state().task(task_id).deferred_until_utc,
            "2026-08-24T04:00:00+00:00",
        )
        with self.assertRaises(AuthorityValidationError):
            self._effect(
                "owner-delivery.prepare",
                {
                    "intent_id": intent_id,
                    "attempted_at_utc": "2026-08-24T03:05:02+00:00",
                },
            )
        self.assertEqual(self.core.recover_owner_delivery_attempts(), ())
        self.assertEqual(adapter.calls, 1)

    def test_deferred_prepared_attempt_never_reaches_adapter(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)

        self._effect(
            "owner-delivery.prepare",
            {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
        )
        self.assertEqual(self._outbox().record(intent_id).current_layer, "attempted")

        defer_request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-24T04:00:00+00:00",
            ),
            suffix=":ticket115-prepared-attempt-defer",
        )
        self.assertEqual(self.base._prepare(defer_request).status, "accepted")
        self.assertEqual(self.base._commit(defer_request).status, "accepted")
        self.assertEqual(self.base._finalize(defer_request).status, "accepted")

        issued = Response.from_wire(
            self._effect(
                "owner-delivery.issue",
                {"intent_id": intent_id},
            )["response"]
        )
        adapter = _RecordingAdapter(self.base.store)
        self.assertEqual(issued.status, "rejected")
        self.assertEqual(adapter.calls, 0)

    def test_deferred_unsent_intent_does_not_starve_fresh_expired_review_intent(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        old_intent_id = self._commit_review_outbox(task_id, effect_request_id)
        defer_request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-24T04:00:00+00:00",
            ),
            suffix=":ticket115-old-intent-defer",
        )
        self.assertEqual(self.base._prepare(defer_request).status, "accepted")
        self.assertEqual(self.base._commit(defer_request).status, "accepted")
        self.assertEqual(self.base._finalize(defer_request).status, "accepted")

        refreshed = self._wake_review("2026-08-25T03:00:00+00:00")
        pending = refreshed.ledger.pending
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertTrue(pending.changed)
        self.assertEqual(pending.action_refs, (task_id,))

        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-25T03:01:00+00:00"
        )
        new_effect_request_id = effect_request_id + ":ticket115-after-defer"
        committed = self._decision(
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(refreshed),
                    "delivery": {
                        "effect_request_id": new_effect_request_id,
                        "source_task_id": task_id,
                        "payload_ref": "payload:ticket115-review-summary-after-defer",
                        "payload_digest": "sha256:" + ("8" * 64),
                        "formed_at_utc": "2026-08-25T03:00:30+00:00",
                        "submitted_at_utc": "2026-08-25T03:01:00+00:00",
                    },
                },
            )
        )
        self.assertEqual(committed.outcome, "committed")
        self.assertEqual(len(self._outbox().records), 2)
        self.assertIn(old_intent_id, tuple(item.intent.intent_id for item in self._outbox().records))
        self.assertEqual(
            len(
                {
                    item.intent.effect_request_id
                    for item in self._outbox().records
                }
            ),
            2,
        )
        with self.assertRaises(AuthorityValidationError):
            self._effect(
                "owner-delivery.prepare",
                {
                    "intent_id": old_intent_id,
                    "attempted_at_utc": "2026-08-25T03:01:01+00:00",
                },
            )

    def test_defer_expiry_allows_current_intent_to_send_once_with_current_approval(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        old_intent_id = self._commit_review_outbox(task_id, effect_request_id)
        defer_request = self._owner_task_mutation_request(
            task_id,
            TaskOwnerMutation.defer(
                task_id,
                deferred_until_utc="2026-08-24T04:00:00+00:00",
            ),
            suffix=":ticket115-defer-expiry-current-send",
        )
        self.assertEqual(self.base._prepare(defer_request).status, "accepted")
        self.assertEqual(self.base._commit(defer_request).status, "accepted")
        self.assertEqual(self.base._finalize(defer_request).status, "accepted")

        refreshed = self._wake_review("2026-08-25T03:00:00+00:00")
        self.base.owner_clock_value = datetime.fromisoformat(
            "2026-08-25T03:01:00+00:00"
        )
        new_effect_request_id = effect_request_id + ":ticket115-defer-expiry-current-send"
        committed = self._decision(
            self._health(
                "review.commit",
                {
                    "decision": self._decision_wire(refreshed),
                    "delivery": {
                        "effect_request_id": new_effect_request_id,
                        "source_task_id": task_id,
                        "payload_ref": "payload:ticket115-current-review-summary",
                        "payload_digest": "sha256:" + ("9" * 64),
                        "formed_at_utc": "2026-08-25T03:00:30+00:00",
                        "submitted_at_utc": "2026-08-25T03:01:00+00:00",
                    },
                },
            )
        )
        self.assertEqual(committed.outcome, "committed")
        new_intent_id = next(
            record.intent.intent_id
            for record in self._outbox().records
            if record.intent.effect_request_id == new_effect_request_id
        )

        prepared = self._effect(
            "owner-delivery.prepare",
            {
                "intent_id": new_intent_id,
                "attempted_at_utc": "2026-08-25T03:01:01+00:00",
            },
        )
        issued = Response.from_wire(
            self._effect(
                "owner-delivery.issue",
                {"intent_id": new_intent_id},
            )["response"]
        )
        self.assertEqual(issued.status, "accepted")
        assert issued.meta is not None
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        assert grant is not None
        adapter = _RecordingAdapter(self.base.store)
        executed = self._effect(
            "owner-delivery.execute",
            {
                "intent_id": new_intent_id,
                "attempted_at_utc": "2026-08-25T03:01:01+00:00",
            },
            grant=grant,
            transport=adapter,
        )

        self.assertEqual(prepared["send_intent"]["intent_id"], new_intent_id)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(
            Response.from_wire(executed["effect_response"]).status,
            "accepted",
        )
        with self.assertRaises(AuthorityValidationError):
            self._effect(
                "owner-delivery.prepare",
                {
                    "intent_id": old_intent_id,
                    "attempted_at_utc": "2026-08-25T03:01:02+00:00",
                },
            )

    def test_restart_recovers_orphan_attempt_without_replaying_transport(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        self._claimed_delivery(intent_id)
        transport = _RecordingAdapter(self.base.store)

        self._restart_core()
        recovered = self._ticket115_read()

        self.assertEqual(transport.calls, 0)
        self.assertEqual(
            next(
                item["current_layer"]
                for item in recovered["owner_deliveries"]
                if item["intent"]["intent_id"] == intent_id
            ),
            "unknown",
        )
        self.assertEqual(self._outbox().record(intent_id).current_layer, "unknown")
        self.assertIn(intent_id, self._task_state().delivery_unknown_refs)
        effect_id = self.core._effect_id(effect_request_id)
        self.assertEqual(self.base.store.effect(effect_id).state, "unknown")

    def test_prepare_handoff_survives_managed_read_until_marker_ttl(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)

        self._effect(
            "owner-delivery.prepare",
            {
                "intent_id": intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
            },
        )
        self.assertIn(intent_id, self.core._owner_delivery_attempts_started)
        self.assertEqual(
            self.core._owner_delivery_attempt_phase(intent_id),
            "prepared",
        )

        view = self._ticket115_read()

        self.assertEqual(
            next(
                item["current_layer"]
                for item in view["owner_deliveries"]
                if item["intent"]["intent_id"] == intent_id
            ),
            "attempted",
        )
        self.assertNotIn(intent_id, self._task_state().delivery_unknown_refs)

    def test_prepare_abandonment_is_recovered_after_marker_ttl(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)

        self._effect(
            "owner-delivery.prepare",
            {
                "intent_id": intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
            },
        )
        self.assertIn(intent_id, self.core._owner_delivery_attempts_started)
        self.assertEqual(
            self.core._owner_delivery_attempt_phase(intent_id),
            "prepared",
        )

        self._recover_after_owner_delivery_marker_ttl(intent_id)

        self.assertEqual(self._outbox().record(intent_id).current_layer, "unknown")
        self.assertIn(intent_id, self._task_state().delivery_unknown_refs)

    def test_restart_recovers_abandoned_prepare_without_replaying_transport(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)

        self._effect(
            "owner-delivery.prepare",
            {
                "intent_id": intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
            },
        )
        self._restart_core()

        view = self._ticket115_read()

        self.assertEqual(
            next(
                item["current_layer"]
                for item in view["owner_deliveries"]
                if item["intent"]["intent_id"] == intent_id
            ),
            "unknown",
        )
        self.assertIn(intent_id, self._task_state().delivery_unknown_refs)
        effect_id = self.core._effect_id(effect_request_id)
        self.assertIsNone(self.base.store.effect(effect_id))

    def test_restart_freezes_orphan_attempt_when_generic_effect_capability_is_lost(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        self._claimed_delivery(intent_id)

        self._restart_core(preserve_execution_vault=False)
        recovered = self._ticket115_read()

        self.assertEqual(
            next(
                item["current_layer"]
                for item in recovered["owner_deliveries"]
                if item["intent"]["intent_id"] == intent_id
            ),
            "unknown",
        )
        self.assertIn(intent_id, self._task_state().delivery_unknown_refs)
        effect_id = self.core._effect_id(effect_request_id)
        self.assertEqual(self.base.store.effect(effect_id).state, "unknown")

    def test_pending_ticket115_recovery_releases_orphan_execution_lease_first(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        self._claimed_delivery(intent_id)

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "current-head-conflict",
        ):
            self.core.advance_task_phase(
                task_id,
                phase="in-progress",
                advanced_at_utc="2026-08-24T03:06:00+00:00",
            )
        pending = self.base.store.pending_ticket115_mutation()
        self.assertIsNotNone(pending)

        self._restart_core(preserve_execution_vault=False)
        restored = self._task_state().task(task_id)
        self.assertEqual(restored.phase, "in-progress")
        self.assertIsNone(self.base.store.pending_ticket115_mutation())
        effect = self.base.store.effect(self.core._effect_id(effect_request_id))
        self.assertIsNotNone(effect)
        assert effect is not None
        assert hasattr(effect.payload, "lease")
        lease = effect.payload.lease
        receipt = self.core._lookup_execution_lease(
            ExecutionLeaseIdentity(
                expected=lease.authority,
                effect_id=lease.effect_id,
                intent_digest=lease.intent_digest,
                writer_fence=lease.authority.writer_fence,
                holder_id=lease.holder_id,
            )
        )
        self.assertTrue(receipt.released)

    def test_repeated_authorize_preserves_first_in_flight_marker(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)

        send_intent = self.core.authorize_owner_delivery_attempt(
            intent_id,
            grant,
            attempted_at_utc=_ATTEMPTED_AT,
        )
        self.assertEqual(send_intent.intent_id, intent_id)
        self.assertEqual(
            self.core._owner_delivery_attempt_phase(intent_id),
            "authorized-in-flight",
        )

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner-delivery-authorization-required",
        ):
            self.core.authorize_owner_delivery_attempt(
                intent_id,
                grant,
                attempted_at_utc=_ATTEMPTED_AT,
            )

        self.assertEqual(
            self.core._owner_delivery_attempt_phase(intent_id),
            "authorized-in-flight",
        )
        self._recover_after_owner_delivery_marker_ttl(intent_id)
        self.assertEqual(self._outbox().record(intent_id).current_layer, "unknown")
        self.assertIn(intent_id, self._task_state().delivery_unknown_refs)
        effect_id = self.core._effect_id(effect_request_id)
        self.assertEqual(self.base.store.effect(effect_id).state, "unknown")

    def test_completion_failure_cannot_send_same_attempt_twice(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        adapter = _RecordingAdapter(self.base.store)
        original = self.core._complete_owner_delivery_attempt_impl

        def fail_completion(
            this: object,
            completion: object,
            completion_grant: object,
        ) -> None:
            del this, completion, completion_grant
            raise StoreUnavailable("synthetic owner delivery completion failure")

        self.core._complete_owner_delivery_attempt_impl = MethodType(
            fail_completion,
            self.core,
        )
        try:
            with self.assertRaisesRegex(
                StoreUnavailable,
                "synthetic owner delivery completion failure",
            ):
                self._effect(
                    "owner-delivery.execute",
                    {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
                    grant=grant,
                    transport=adapter,
                )
        finally:
            self.core._complete_owner_delivery_attempt_impl = original

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(
            self.core._owner_delivery_attempt_phase(intent_id),
            "authorized-in-flight",
        )
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner-delivery-authorization-required",
        ):
            self._effect(
                "owner-delivery.execute",
                {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
                grant=grant,
                transport=adapter,
            )
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(
            self.core._owner_delivery_attempt_phase(intent_id),
            "authorized-in-flight",
        )

        self._recover_after_owner_delivery_marker_ttl(intent_id)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(self._outbox().record(intent_id).current_layer, "unknown")
        self.assertIn(intent_id, self._task_state().delivery_unknown_refs)
        effect_id = self.core._effect_id(effect_request_id)
        self.assertEqual(self.base.store.effect(effect_id).state, "unknown")

    def test_writer_proof_is_rechecked_after_attempt_before_adapter(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        adapter = _RecordingAdapter(self.base.store)
        authority = self.base.head.read().head.as_authority()
        self.base.writer_vault.bind(
            authority,
            "ticket115-invalid-writer-capability",
        )

        with self.assertRaises(AuthorityValidationError):
            self._effect(
                "owner-delivery.execute",
                {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
                grant=grant,
                transport=adapter,
            )
        self.assertEqual(adapter.calls, 0)
        self.assertNotIn(intent_id, self.core._owner_delivery_attempts_started)

    def test_invalid_observation_time_is_rejected_before_transport_send(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        adapter = _RecordingAdapter(self.base.store)

        with self.assertRaises(ProtocolViolation):
            self._effect(
                "owner-delivery.execute",
                {
                    "intent_id": intent_id,
                    "attempted_at_utc": _ATTEMPTED_AT,
                    "observed_at_utc": "not-a-utc-time",
                },
                grant=grant,
                transport=adapter,
            )

        self.assertEqual(adapter.calls, 0)
        # Invalid caller input causes no external side effect; keep the
        # bounded handoff marker so a corrected execute can still proceed.
        self.assertIn(intent_id, self.core._owner_delivery_attempts_started)
        self.assertEqual(
            self.core._owner_delivery_attempt_phase(intent_id),
            "prepared",
        )
        self._recover_after_owner_delivery_marker_ttl(intent_id)
        self.assertEqual(self._outbox().record(intent_id).current_layer, "unknown")

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
        self.assertNotIn(intent_id, self.core._owner_delivery_attempts_started)

    def test_evidence_change_after_attempt_stays_before_adapter(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        grant = self._claimed_delivery(intent_id)
        adapter = _RecordingAdapter(self.base.store)
        self._replace_task_source_revision(
            task_id,
            "sha256:" + ("0" * 64),
            updated_at_utc="2026-08-24T03:05:00+00:00",
        )

        with self.assertRaises(AuthorityValidationError):
            self._effect(
                "owner-delivery.execute",
                {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
                grant=grant,
                transport=adapter,
            )

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

    def test_owner_task_cancellation_atomically_closes_active_task_and_claim(self) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        self._health(
            "task.claim",
            {
                "task_id": task_id,
                "holder_id": "task-worker:owner-cancellation",
                "lease_id": "task-lease:owner-cancellation",
                "acquired_at_utc": _PREPARED_AT,
            },
        )
        request = self._owner_task_cancellation_request(
            task_id,
            suffix=":ticket115-owner-task-cancellation",
        )

        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

        current_settings = self.store.owner_settings()
        self.assertIsNotNone(current_settings)
        assert current_settings is not None
        self.assertIn(task_id, current_settings.cancelled_task_refs)
        task_state = self._task_state()
        self.assertEqual(task_state.task(task_id).primary_label, "cancelled")
        self.assertEqual(task_state.active_claims, ())

    def test_owner_task_cancellation_tombstone_blocks_later_admission(self) -> None:
        candidate, task_id, _ = self._candidate(suffix="cancelled-before-admit")
        self._enable_review_summary()
        request = self._owner_task_cancellation_request(
            task_id,
            suffix=":ticket115-owner-task-cancel-before-admit",
        )

        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

        with self.assertRaisesRegex(
            TaskContractViolation,
            "cancelled by owner",
        ):
            self._health(
                "task.admit",
                {
                    "candidate": candidate.to_storage(),
                    "committed_at_utc": _PREPARED_AT,
                },
            )
        self.assertEqual(self._task_state().tasks, ())

    def test_owner_task_cancellation_preserves_solved_terminal(self) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        task = self._task_state().task(task_id)
        card = self.base.baseline_card
        acceptance = TaskAcceptance.prove(
            task,
            (
                TaskAcceptanceCriterionProof(
                    criterion=task.acceptance_criteria[0],
                    evidence_refs=(card.evidence_id,),
                    evidence_revision_digests=(card.revision_digest,),
                ),
            ),
            accepted_at_utc="2026-08-24T03:02:00+00:00",
        )
        self._health("task.solve", {"acceptance": acceptance.to_storage()})
        before = self._task_state().task(task_id)
        request = self._owner_task_cancellation_request(
            task_id,
            suffix=":ticket115-owner-task-solved",
        )

        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

        self.assertEqual(self._task_state().task(task_id), before)

    def test_owner_task_cancellation_preserves_failed_terminal(self) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        self._health(
            "task.fail",
            {
                "task_id": task_id,
                "failed_at_utc": "2026-08-24T03:02:00+00:00",
                "reason_code": "owner-cancellation-test-terminal",
            },
        )
        before = self._task_state().task(task_id)
        request = self._owner_task_cancellation_request(
            task_id,
            suffix=":ticket115-owner-task-failed",
        )

        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

        self.assertEqual(self._task_state().task(task_id), before)

    def test_owner_task_cancellation_finalize_replay_is_idempotent(self) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        request = self._owner_task_cancellation_request(
            task_id,
            suffix=":ticket115-owner-task-replay",
        )
        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")
        first = self._task_state()

        replayed = self.base._finalize(request)

        self.assertIn(replayed.status, {"accepted", "replayed"})
        self.assertEqual(self._task_state(), first)

    def test_owner_task_cancellation_rolls_back_settings_and_task_together(self) -> None:
        task_id, _ = self._admit_review_task(notification_enabled=False)
        request = self._owner_task_cancellation_request(
            task_id,
            suffix=":ticket115-owner-task-rollback",
        )
        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        stored = self.store.owner_mutation(request.context.command_id)
        self.assertIsNotNone(stored)
        assert stored is not None and stored.prepared is not None
        before_settings = self.store.owner_settings()
        before_tasks = self.store.task_runtime()
        self.assertIsInstance(before_tasks, TaskRuntimeState)
        assert isinstance(before_tasks, TaskRuntimeState)
        cancelled = TaskEngine.apply_owner_cancellation(
            before_tasks,
            task_id,
            control_ref=request.context.command_id,
            effective_at_utc=_ATTEMPTED_AT,
        )
        original = self.store._write_task_runtime

        def fail_task_write(
            this: object,
            connection: object,
            state: object,
        ) -> None:
            del this, connection, state
            raise StoreUnavailable("synthetic owner task cancellation failure")

        self.store._write_task_runtime = MethodType(fail_task_write, self.store)
        try:
            with self.assertRaisesRegex(
                StoreUnavailable,
                "synthetic owner task cancellation failure",
            ):
                self.store.finalize_owner_mutation(
                    stored.prepared,
                    task_state=cancelled.state,
                )
        finally:
            self.store._write_task_runtime = original

        self.assertEqual(self.store.owner_settings(), before_settings)
        self.assertEqual(self.store.task_runtime(), before_tasks)
        durable = self.store.owner_mutation(request.context.command_id)
        self.assertIsNotNone(durable)
        assert durable is not None
        self.assertEqual(durable.phase, "prepared")

    # === TICKET 115 VERIFICATION GATES START ===
    # These gates are owned by the independent test pass.
    # Implementation work may make these tests green, but must not weaken them.
    def test_verification_gate_attempt_budget_counts_opaque_current_intents(
        self,
    ) -> None:
        task_id, _ = self._admit_review_task(max_attempts=1)
        adapter, second_intent_id = self._send_opaque_intent_then_form_next_day_intent(
            task_id,
            first_effect_request_id="opaque-request:ticket115-budget-alpha",
            second_effect_request_id="opaque-request:ticket115-budget-omega",
        )
        self._restart_core()

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner-delivery-authorization-required",
        ):
            self._effect(
                "owner-delivery.prepare",
                {
                    "intent_id": second_intent_id,
                    "attempted_at_utc": "2026-08-25T03:05:00+00:00",
                },
            )
        self.assertEqual(adapter.calls, 1)

    def test_verification_gate_contact_interval_counts_opaque_current_intents(
        self,
    ) -> None:
        task_id, _ = self._admit_review_task(
            max_attempts=2,
            min_contact_interval_seconds=90_001,
        )
        adapter, second_intent_id = self._send_opaque_intent_then_form_next_day_intent(
            task_id,
            first_effect_request_id="opaque-request:ticket115-cadence-alpha",
            second_effect_request_id="opaque-request:ticket115-cadence-omega",
        )
        self._restart_core()

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner-delivery-authorization-required",
        ):
            self._effect(
                "owner-delivery.prepare",
                {
                    "intent_id": second_intent_id,
                    "attempted_at_utc": "2026-08-25T03:05:00+00:00",
                },
            )
        self.assertEqual(adapter.calls, 1)

    def test_verification_gate_revoked_approval_stops_before_adapter(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        current = self.store.owner_settings()
        self.assertIsNotNone(current)
        assert current is not None
        snapshot = self.base.head.read().head
        command = settings.OwnerControlCommand(
            context=settings.OwnerCommandContext(
                command_id="settings-command:ticket115-verifier-revoke-approval",
                causal_id="settings-source:ticket115-verifier-revoke-approval",
                actor_kind="current_owner",
                owner_id="owner-A",
                installation_id="partner-installation",
                permission="health_settings.write",
                context_ref="managed-context:ticket115-verifier-revoke-approval",
                generation=snapshot.generation,
                writer_fence=snapshot.writer_fence,
            ),
            control_update=settings.ControlUpdate(
                control_name="execution_scope_approval",
                operation="revoke",
                target_ref="approval:ticket115-review-summary",
                generation=snapshot.generation,
                effective_at_utc="2026-08-24T03:02:00+00:00",
            ),
            execution_scope_approval=None,
        )
        self._apply_owner_setting(
            command,
            expected_version=current.version,
            suffix=":ticket115-verifier-revoke-approval",
        )

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner-delivery-authorization-required",
        ):
            self._effect(
                "owner-delivery.prepare",
                {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
            )
        self.assertIsNone(self._outbox().record(intent_id).optional_fact("attempted"))

    def test_verification_gate_closed_contact_window_stops_before_adapter(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        current = self.store.owner_settings()
        self.assertIsNotNone(current)
        assert current is not None
        snapshot = self.base.head.read().head
        self._apply_owner_setting(
            settings.FieldUpdate(
                field_name="contact_window",
                old_value=current.contact_window,
                new_value="18:30-21:30",
                generation=snapshot.generation,
                effective_at_utc="2026-08-24T03:02:00+00:00",
            ),
            expected_version=current.version,
            suffix=":ticket115-verifier-close-contact-window",
        )

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner-delivery-authorization-required",
        ):
            self._effect(
                "owner-delivery.prepare",
                {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
            )
        self.assertIsNone(self._outbox().record(intent_id).optional_fact("attempted"))

    def test_verification_gate_route_generation_drift_stops_before_adapter(self) -> None:
        task_id, effect_request_id = self._admit_review_task()
        intent_id = self._commit_review_outbox(task_id, effect_request_id)
        self.route_fact = replace(
            self.route_fact,
            configuration_generation=2,
            generation=2,
        )
        projected = self.plugin.owner_settings_state(peer_id=_PEER)
        self.assertEqual(projected.consent_path_status, "paused")

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner-delivery-authorization-required",
        ):
            self._effect(
                "owner-delivery.prepare",
                {"intent_id": intent_id, "attempted_at_utc": _ATTEMPTED_AT},
            )
        self.assertIsNone(self._outbox().record(intent_id).optional_fact("attempted"))

    def _persist_disabled_ordinary_controls(self) -> None:
        current = self.plugin.owner_settings_state(peer_id=_PEER)
        current_notifications = dict(current.ordinary_notifications)
        snapshot = self.base.head.read().head
        self._apply_owner_setting(
            settings.NotificationUpdate(
                kind="review_summary",
                old_state=current_notifications["review_summary"],
                new_state="disabled",
                generation=snapshot.generation,
                effective_at_utc="2026-08-24T02:30:00+00:00",
            ),
            expected_version=current.version,
            suffix=":ticket115-verifier-disable-review-summary",
        )

        current = self.store.owner_settings()
        self.assertIsNotNone(current)
        assert current is not None
        snapshot = self.base.head.read().head
        pause_request = self.base._owner_request(
            correction=False,
            settings_command=settings.ControlUpdate(
                control_name="proactive_support",
                operation="pause",
                target_ref=None,
                generation=snapshot.generation,
                effective_at_utc="2026-08-24T02:31:00+00:00",
            ),
            expected_settings_version=current.version,
            command_suffix=":ticket115-verifier-pause-proactive-support",
        )
        self.assertEqual(self.base._prepare(pause_request).status, "accepted")
        self.assertEqual(self.base._commit(pause_request).status, "accepted")
        self.assertEqual(self.base._finalize(pause_request).status, "accepted")

    def test_verification_gate_mandatory_status_bypasses_persisted_ordinary_controls(
        self,
    ) -> None:
        self._persist_disabled_ordinary_controls()
        prior = status.StatusProjection(
            state="active",
            evaluated_at_utc="2026-08-24T11:59:00+00:00",
            affected_core_domains=(),
            isolated_noncore_domains=(),
            reason_codes=(),
            fact_set_digest="sha256:" + ("a" * 64),
        )
        self.assertIsNone(self.store.remember_business_status(prior))
        before_intent_ids = {
            record.intent.intent_id for record in self._outbox().records
        }

        with self._controlled_status_inputs(task_state="unknown"):
            result = self.plugin.business_status(peer_id=_PEER)

        self.assertIsNotNone(result.transition)
        assert result.transition is not None
        self.assertEqual(result.transition.previous_state, "active")
        self.assertNotEqual(result.transition.current_state, "active")
        created = tuple(
            record
            for record in self._outbox().records
            if record.intent.intent_id not in before_intent_ids
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].intent.source_ref, result.transition.transition_id)

        attempted_at_utc = "2026-08-24T12:01:00+00:00"
        grant = self._claimed_delivery(
            created[0].intent.intent_id,
            attempted_at_utc=attempted_at_utc,
        )
        adapter = _RecordingAdapter(self.base.store)
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": created[0].intent.intent_id,
                "attempted_at_utc": attempted_at_utc,
                "observed_at_utc": "2026-08-24T12:01:01+00:00",
            },
            grant=grant,
            transport=adapter,
        )
        self.assertEqual(adapter.calls, 1)

    def test_verification_gate_active_to_abnormal_requests_once(self) -> None:
        prior = status.StatusProjection(
            state="active",
            evaluated_at_utc="2026-08-24T11:59:00+00:00",
            affected_core_domains=(),
            isolated_noncore_domains=(),
            reason_codes=(),
            fact_set_digest="sha256:" + ("b" * 64),
        )
        self.assertIsNone(self.store.remember_business_status(prior))
        before_intent_ids = {
            record.intent.intent_id for record in self._outbox().records
        }

        with self._controlled_status_inputs(task_state="confirmed-fault"):
            result = self.plugin.business_status(peer_id=_PEER)

        self.assertIsNotNone(result.transition)
        assert result.transition is not None
        self.assertEqual(
            (result.transition.previous_state, result.transition.current_state),
            ("active", "abnormal"),
        )
        created = tuple(
            record
            for record in self._outbox().records
            if record.intent.intent_id not in before_intent_ids
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].intent.source_ref, result.transition.transition_id)

        attempted_at_utc = "2026-08-24T12:01:00+00:00"
        grant = self._claimed_delivery(
            created[0].intent.intent_id,
            attempted_at_utc=attempted_at_utc,
        )
        adapter = _RecordingAdapter(self.base.store)
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": created[0].intent.intent_id,
                "attempted_at_utc": attempted_at_utc,
                "observed_at_utc": "2026-08-24T12:01:01+00:00",
            },
            grant=grant,
            transport=adapter,
        )
        self.assertEqual(adapter.calls, 1)

    def test_verification_gate_opposite_status_transition_supersedes_old_request(
        self,
    ) -> None:
        prior = status.StatusProjection(
            state="active",
            evaluated_at_utc="2026-08-24T11:59:00+00:00",
            affected_core_domains=(),
            isolated_noncore_domains=(),
            reason_codes=(),
            fact_set_digest="sha256:" + ("e" * 64),
        )
        self.assertIsNone(self.store.remember_business_status(prior))
        with self._controlled_status_inputs(task_state="unknown"):
            down = self.plugin.business_status(peer_id=_PEER)
        self.assertIsNotNone(down.transition)
        assert down.transition is not None
        self.assertEqual(
            (down.transition.previous_state, down.transition.current_state),
            ("active", "cannot-confirm"),
        )
        down_records = tuple(
            record
            for record in self._outbox().records
            if record.intent.source_ref == down.transition.transition_id
        )
        self.assertEqual(len(down_records), 1)

        before_up_ids = {
            record.intent.intent_id for record in self._outbox().records
        }
        with self._controlled_status_inputs():
            up = self.plugin.business_status(peer_id=_PEER)
        self.assertIsNotNone(up.transition)
        assert up.transition is not None
        self.assertEqual(
            (up.transition.previous_state, up.transition.current_state),
            ("cannot-confirm", "active"),
        )
        up_records = tuple(
            record
            for record in self._outbox().records
            if record.intent.intent_id not in before_up_ids
        )
        self.assertEqual(len(up_records), 1)
        self.assertEqual(up_records[0].intent.source_ref, up.transition.transition_id)
        self._restart_core()

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner-delivery-authorization-required",
        ):
            self._effect(
                "owner-delivery.prepare",
                {
                    "intent_id": down_records[0].intent.intent_id,
                    "attempted_at_utc": "2026-08-24T12:01:00+00:00",
                },
            )
        up_attempted_at_utc = "2026-08-24T12:02:00+00:00"
        up_grant = self._claimed_delivery(
            up_records[0].intent.intent_id,
            attempted_at_utc=up_attempted_at_utc,
        )
        adapter = _RecordingAdapter(self.base.store)
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": up_records[0].intent.intent_id,
                "attempted_at_utc": up_attempted_at_utc,
                "observed_at_utc": "2026-08-24T12:02:01+00:00",
            },
            grant=up_grant,
            transport=adapter,
        )
        self.assertEqual(adapter.calls, 1)

    @contextmanager
    def _controlled_status_inputs(self, *, task_state: str = "confirmed-ok"):
        """Arrange signed status facts; business_status remains the stimulus."""

        original = self.core._production_status_inputs

        def produce_all_confirmed_ok(
            core: object,
            *,
            probe: object,
            valid_until_utc: str,
        ) -> tuple[tuple[object, ...], tuple[object, ...]]:
            del core, probe
            requirements = []
            facts = []
            for index, domain in enumerate(status.CORE_STATUS_DOMAINS, 1):
                revision_digest = "sha256:" + format(index, "064x")
                transition_id = f"verifier-current:{domain}:1"
                producer_id = status.PRODUCTION_STATUS_PRODUCER_IDS[domain]
                contract_version = (
                    status.PRODUCTION_STATUS_PRODUCER_CONTRACT_VERSIONS[domain]
                )
                requirements.append(
                    status.CapabilityRequirement(
                        domain=domain,
                        requiredness="core",
                        producer_id=producer_id,
                        producer_contract_version=contract_version,
                        expected_generation=1,
                        expected_revision_digest=revision_digest,
                        expected_transition_id=transition_id,
                    )
                )
                facts.append(
                    self.status_authority.seal(
                        domain=domain,
                        requiredness="core",
                        state=(task_state if domain == "tasks" else "confirmed-ok"),
                        generation=1,
                        revision_digest=revision_digest,
                        transition_id=transition_id,
                        producer_id=producer_id,
                        producer_contract_version=contract_version,
                        evidence_refs=(f"verifier-current:{domain}",),
                        valid_until_utc=valid_until_utc,
                    )
                )
            return tuple(requirements), tuple(facts)

        self.core._production_status_inputs = MethodType(  # type: ignore[method-assign]
            produce_all_confirmed_ok,
            self.core,
        )
        try:
            yield
        finally:
            self.core._production_status_inputs = original  # type: ignore[method-assign]

    def _assert_status_recovery_forms_one_sendable_request(
        self,
        previous_state: str,
    ) -> None:
        prior = status.StatusProjection(
            state=previous_state,  # type: ignore[arg-type]
            evaluated_at_utc="2026-08-24T11:59:00+00:00",
            affected_core_domains=("tasks",),
            isolated_noncore_domains=(),
            reason_codes=("synthetic-ticket115-prior-state",),
            fact_set_digest="sha256:"
            + (("c" if previous_state == "abnormal" else "d") * 64),
        )
        self.assertIsNone(self.store.remember_business_status(prior))

        before_intent_ids = {
            record.intent.intent_id for record in self._outbox().records
        }
        with self._controlled_status_inputs():
            recovered = self.plugin.business_status(peer_id=_PEER)
        self.assertIsNotNone(recovered.transition)
        assert recovered.transition is not None
        self.assertEqual(
            (recovered.transition.previous_state, recovered.transition.current_state),
            (previous_state, "active"),
        )
        created_records = tuple(
            record
            for record in self._outbox().records
            if record.intent.intent_id not in before_intent_ids
        )
        self.assertEqual(len(created_records), 1)
        self.assertEqual(
            created_records[0].intent.source_ref,
            recovered.transition.transition_id,
        )
        created_intent_ids = {
            record.intent.intent_id for record in self._outbox().records
        }

        self._restart_core()
        with self._controlled_status_inputs():
            replay = self.plugin.business_status(peer_id=_PEER)
        self.assertIsNone(replay.transition)
        self.assertEqual(
            {record.intent.intent_id for record in self._outbox().records},
            created_intent_ids,
        )

        intent_id = created_records[0].intent.intent_id
        attempted_at_utc = "2026-08-24T12:01:00+00:00"
        grant = self._claimed_delivery(
            intent_id,
            attempted_at_utc=attempted_at_utc,
        )
        adapter = _RecordingAdapter(self.base.store)
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": intent_id,
                "attempted_at_utc": attempted_at_utc,
                "observed_at_utc": "2026-08-24T12:01:01+00:00",
            },
            grant=grant,
            transport=adapter,
        )
        self.assertEqual(adapter.calls, 1)

    def test_verification_gate_cannot_confirm_to_active_requests_once(self) -> None:
        self._assert_status_recovery_forms_one_sendable_request("cannot-confirm")

    def test_verification_gate_abnormal_to_active_requests_once(self) -> None:
        self._assert_status_recovery_forms_one_sendable_request("abnormal")

    def test_verification_gate_unknown_request_expires_with_source_unknown(
        self,
    ) -> None:
        task_id, effect_request_id = self._admit_review_task()
        source_intent_id = self._commit_review_outbox(task_id, effect_request_id)
        source_grant = self._claimed_delivery(source_intent_id)
        source_adapter = _RaisingAdapter()
        self._effect(
            "owner-delivery.execute",
            {
                "intent_id": source_intent_id,
                "attempted_at_utc": _ATTEMPTED_AT,
                "observed_at_utc": "2026-08-24T03:05:01+00:00",
            },
            grant=source_grant,
            transport=source_adapter,
        )
        decision_records = tuple(
            record
            for record in self._outbox().records
            if record.intent.intent_id != source_intent_id
        )
        self.assertEqual(len(decision_records), 1)
        decision_record = decision_records[0]
        self.assertEqual(decision_record.intent.source_ref, source_intent_id)
        attempted = self._outbox().record(source_intent_id).fact("attempted")
        self._health(
            "delivery.observe",
            {
                "intent_id": source_intent_id,
                "kind": "delivered",
                "attempt_ref": attempted.attempt_ref,
                "result_ref": "owner-delivery-result:verification-delivered",
                "evidence_ref": "owner-delivery-evidence:verification-delivered",
                "observed_at_utc": "2026-08-24T03:06:00+00:00",
            },
        )
        self._restart_core()
        self.assertEqual(len(self._outbox().records), 2)

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner-delivery-authorization-required",
        ):
            self._effect(
                "owner-delivery.prepare",
                {
                    "intent_id": decision_record.intent.intent_id,
                    "attempted_at_utc": "2026-08-24T03:07:00+00:00",
                },
            )
        self.assertEqual(source_adapter.calls, 1)

    # === TICKET 115 VERIFICATION GATES END ===


if __name__ == "__main__":
    unittest.main()

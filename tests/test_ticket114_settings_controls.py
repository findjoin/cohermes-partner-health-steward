"""Ticket 114 slice 2: owner settings and independent control state machine.

These tests intentionally describe the public, immutable state-machine seam.
The contract/value-object slice exists already; this slice stays red until
``OwnerSettingsEngine`` and its state/command results are implemented.
"""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from typing import Any, Callable

from partner_health_steward import settings


OWNER = "owner-synthetic"
INSTALLATION = "installation-synthetic"
CURRENT_HEAD_GENERATION = 7
SETTINGS_VERSION = 1
COMMITTED_AT = "2026-08-24T01:02:03+00:00"
ROUTE_ID = "partner-first-hop"
RECIPIENT = "https://model.example/v1"
CONFIGURATION_GENERATION = 11
DISCLOSURE_VERSION = "health-recipient-disclosure-v3"
DISCLOSURE_DIGEST = "sha256:" + "d" * 64
APPROVAL_ID = "execution-approval:synthetic-1"
EFFECT_ID = "effect-request:synthetic-1"
NOT_CONFIGURED = "not-configured"
ENABLED = "enabled"
DISABLED = "disabled"
_DEFAULT_CONFIGURED_CONTACT = object()


def _contact_binding(wire: dict[str, object]) -> str:
    bound = {
        "contact_id": wire["contact_id"],
        "owner_id": wire["owner_id"],
        "installation_id": wire["installation_id"],
        "method_kind": wire["method_kind"],
        "method_value": wire["method_value"],
        "purpose": wire["purpose"],
        "minimum_alert_fields": wire["minimum_alert_fields"],
        "route_id": wire["route_id"],
        "route_generation": wire["route_generation"],
        "disclosure_version": wire["disclosure_version"],
    }
    canonical = json.dumps(
        bound, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _support_contact(
    *,
    approved: bool = True,
    contact_id: str = "support-contact:synthetic-1",
    version: int = 3,
    method_kind: str = "weixin_user",
    method_value: str = "wxid_synthetic_contact",
    route_id: str = "weixin-ilink-partner",
    route_generation: int = 5,
    disclosure_version: str = "support-contact-disclosure-v3",
) -> Any:
    wire: dict[str, object] = {
        "contact_id": contact_id,
        "version": version,
        "owner_id": OWNER,
        "installation_id": INSTALLATION,
        "identity_label": "Owner-recognizable trusted contact",
        "method_kind": method_kind,
        "method_value": method_value,
        "purpose": "minimum urgent-help contact alert",
        "minimum_alert_fields": [
            "owner_recognizable_name",
            "event_time",
            "fixed_urgent_help_request",
        ],
        "route_id": route_id,
        "route_generation": route_generation,
        "disclosure_version": disclosure_version,
        "dedicated_paused": False,
        "alert_authority_status": "approved" if approved else "invalidated",
        "alert_approval_id": "alert-approval:synthetic-1" if approved else None,
        "alert_authority_binding": None,
        "correction_authority_status": "approved" if approved else "invalidated",
        "correction_authority_id": (
            "correction-authority:synthetic-1" if approved else None
        ),
        "correction_authority_binding": None,
        "max_corrections_per_alert": 1,
    }
    if approved:
        binding = _contact_binding(wire)
        wire["alert_authority_binding"] = binding
        wire["correction_authority_binding"] = binding
    return settings.SupportContactSettings.from_wire(wire)


def _context(
    command_id: str,
    *,
    generation: int = CURRENT_HEAD_GENERATION,
    actor_kind: str = "current_owner",
    writer_fence: str | None = None,
) -> Any:
    return settings.OwnerCommandContext(
        command_id=command_id,
        causal_id="weixin-message:" + command_id,
        actor_kind=actor_kind,
        owner_id=OWNER,
        installation_id=INSTALLATION,
        permission="health_settings.write",
        context_ref="managed-context:settings-revision-6",
        generation=generation,
        writer_fence=(
            f"writer-fence:{generation}:synthetic"
            if writer_fence is None
            else writer_fence
        ),
    )


def _approval(
    *,
    version: int = 1,
    revoked: bool = False,
    revoked_at_utc: str | None = None,
    purpose: str = "send one owner-approved appointment request",
    categories: tuple[str, ...] = ("appointment_request",),
    refs: tuple[str, ...] = ("managed-object:task:synthetic-1:v3",),
    recipient: str = "https://appointments.example/v1",
    effect_kind: str = "appointment_request",
    max_attempts: int = 1,
    min_interval: int = 86_400,
    task_id: str = "task:synthetic-1",
    effect_request_id: str = EFFECT_ID,
    assignee: str = "partner-health-plugin",
    expires_at_utc: str = "2026-08-31T03:00:00+00:00",
    route_id: str = "approved-appointment-route",
    configuration_generation: int = CONFIGURATION_GENERATION,
    disclosure_version: str = "execution-disclosure-v2",
) -> Any:
    return settings.ExecutionScopeApproval(
        approval_id=APPROVAL_ID,
        approval_version=version,
        owner_id=OWNER,
        installation_id=INSTALLATION,
        task_id=task_id,
        effect_request_id=effect_request_id,
        assignee=assignee,
        purpose=purpose,
        allowed_data_categories=categories,
        allowed_data_refs=refs,
        first_hop_recipient=recipient,
        external_effect_kind=effect_kind,
        max_attempts=max_attempts,
        min_contact_interval_seconds=min_interval,
        expires_at_utc=expires_at_utc,
        route_id=route_id,
        configuration_generation=configuration_generation,
        disclosure_version=disclosure_version,
        revoked=revoked,
        revoked_at_utc=revoked_at_utc,
    )


def _approval_command(
    operation: str,
    *,
    command_id: str,
    approval: Any | None = None,
    generation: int = CURRENT_HEAD_GENERATION,
    writer_fence: str | None = None,
) -> Any:
    return settings.OwnerControlCommand(
        context=_context(
            command_id,
            generation=generation,
            writer_fence=writer_fence,
        ),
        control_update=settings.ControlUpdate(
            control_name="execution_scope_approval",
            operation=operation,
            target_ref=APPROVAL_ID,
            generation=generation,
            effective_at_utc=COMMITTED_AT,
        ),
        execution_scope_approval=approval,
    )


def _consumption(**changes: object) -> Any:
    fields: dict[str, object] = {
        "approval_id": APPROVAL_ID,
        "approval_version": 1,
        "owner_id": OWNER,
        "installation_id": INSTALLATION,
        "task_id": "task:synthetic-1",
        "effect_request_id": EFFECT_ID,
        "assignee": "partner-health-plugin",
        "purpose": "send one owner-approved appointment request",
        "data_categories": ("appointment_request",),
        "data_refs": ("managed-object:task:synthetic-1:v3",),
        "first_hop_recipient": "https://appointments.example/v1",
        "external_effect_kind": "appointment_request",
        "attempts_used": 0,
        "last_contact_at_utc": None,
        "evaluated_at_utc": "2026-08-24T03:00:00+00:00",
        "route_id": "approved-appointment-route",
        "configuration_generation": CONFIGURATION_GENERATION,
        "disclosure_version": "execution-disclosure-v2",
    }
    fields.update(changes)
    return settings.ExecutionScopeConsumptionRequest(**fields)


class Ticket114SettingsControlsTests(unittest.TestCase):
    """One visible method per SETTINGS_CONTROLS_CASE_IDS registry entry."""

    maxDiff = None

    def setUp(self) -> None:
        self.engine = settings.OwnerSettingsEngine
        self.state = self._seed()

    def _seed(
        self,
        *,
        contact: Any | None | object = _DEFAULT_CONFIGURED_CONTACT,
    ) -> Any:
        return self.engine.seed(
            owner_id=OWNER,
            installation_id=INSTALLATION,
            version=SETTINGS_VERSION,
            timezone="Asia/Shanghai",
            preferences={
                "contact_window": "09:00-21:00",
                "expression_style": "detailed",
                "proactive_contact": True,
                "ordinary_notifications": {
                    kind: NOT_CONFIGURED
                    for kind in settings.ORDINARY_NOTIFICATION_KINDS
                },
            },
            consent={
                "enabled": True,
                "data_scope": ("portrait", "evidence", "tasks"),
                "route_id": ROUTE_ID,
                "first_hop_recipient": RECIPIENT,
                "configuration_generation": CONFIGURATION_GENERATION,
                "consent_generation": 1,
                "disclosure_version": DISCLOSURE_VERSION,
                "disclosure_digest": DISCLOSURE_DIGEST,
            },
            contact=(
                _support_contact()
                if contact is _DEFAULT_CONFIGURED_CONTACT
                else contact
            ),
            completed_review_keys=("2026-08-23@Asia/Shanghai",),
        )

    def _apply(
        self,
        command: Any,
        *,
        state: Any | None = None,
        committed_at: str = COMMITTED_AT,
        current_head_generation: int = CURRENT_HEAD_GENERATION,
        current_writer_fence: str | None = None,
    ) -> Any:
        writer_fence = (
            f"writer-fence:{current_head_generation}:synthetic"
            if current_writer_fence is None
            else current_writer_fence
        )
        return self.engine.apply(
            self.state if state is None else state,
            command,
            core_committed_at_utc=committed_at,
            current_head_generation=current_head_generation,
            current_writer_fence=writer_fence,
        )

    def _view(self, state: Any | None = None) -> dict[str, object]:
        return self.engine.managed_view(
            self.state if state is None else state,
            requester_owner_id=OWNER,
        )

    def _field(
        self,
        name: str,
        old: object,
        new: object,
        *,
        generation: int = CURRENT_HEAD_GENERATION,
        effective_at: str = COMMITTED_AT,
    ) -> Any:
        return settings.FieldUpdate(
            field_name=name,
            old_value=old,
            new_value=new,
            generation=generation,
            effective_at_utc=effective_at,
        )

    def _notification(self, kind: str, old: str, new: str) -> Any:
        return settings.NotificationUpdate(
            kind=kind,
            old_state=old,
            new_state=new,
            generation=CURRENT_HEAD_GENERATION,
            effective_at_utc=COMMITTED_AT,
        )

    def _control(
        self,
        name: str,
        operation: str,
        target: str | None = None,
        *,
        generation: int = CURRENT_HEAD_GENERATION,
    ) -> Any:
        return settings.ControlUpdate(
            control_name=name,
            operation=operation,
            target_ref=target,
            generation=generation,
            effective_at_utc=COMMITTED_AT,
        )

    def _contact_command(
        self,
        operation: str,
        *,
        command_id: str,
        contact: Any | None = None,
        authority_id: str | None = None,
        expected_version: int | None = 3,
        expected_route_id: str | None = "weixin-ilink-partner",
        expected_route_generation: int | None = 5,
        generation: int = CURRENT_HEAD_GENERATION,
        writer_fence: str | None = None,
    ) -> Any:
        return settings.SupportContactCommand(
            context=_context(
                command_id,
                generation=generation,
                writer_fence=writer_fence,
            ),
            operation=operation,
            contact=contact,
            authority_id=authority_id,
            expected_contact_version=expected_version,
            expected_route_id=expected_route_id,
            expected_route_generation=expected_route_generation,
        )

    def _state_with_approval(self) -> Any:
        return self._apply(
            _approval_command(
                "grant", command_id="approval-grant", approval=_approval()
            )
        ).state

    def _control_vector(self, state: Any) -> dict[str, object]:
        view = self._view(state)
        controls = view["controls"]
        approvals = view["execution_scope_approvals"]
        contact = view["support_contact"]
        return {
            "proactive_support": controls["proactive_support_paused"],
            "recording": controls["recording_stopped"],
            "task": tuple(controls["cancelled_task_refs"]),
            "approval": approvals[APPROVAL_ID]["revoked"],
            "support_contact": contact["dedicated_paused"],
        }

    def _timezone_update(
        self,
        new_timezone: str,
        *,
        old_timezone: str = "Asia/Shanghai",
        committed_at: str,
    ) -> Any:
        return self._apply(
            self._field(
                "timezone",
                old_timezone,
                new_timezone,
                effective_at=committed_at,
            ),
            committed_at=committed_at,
        )

    def _drift(
        self,
        *,
        route_id: str = ROUTE_ID,
        recipient: str = RECIPIENT,
        configuration_generation: int = CONFIGURATION_GENERATION,
        disclosure_version: str = DISCLOSURE_VERSION,
    ) -> Any:
        command = settings.RouteConfigurationUpdate(
            route_id=route_id,
            first_hop_recipient=recipient,
            configuration_generation=configuration_generation,
            disclosure_version=disclosure_version,
            generation=CURRENT_HEAD_GENERATION,
        )
        return self.engine.observe_route_configuration(self.state, command)

    def _renewal(
        self,
        *,
        command_id: str,
        route_id: str,
        recipient: str,
        configuration_generation: int,
        disclosure_version: str,
        generation: int = CURRENT_HEAD_GENERATION,
    ) -> Any:
        return settings.ConsentRenewal(
            renewal_id="consent-renewal:" + command_id,
            context=_context(command_id, generation=generation),
            route_id=route_id,
            first_hop_recipient=recipient,
            configuration_generation=configuration_generation,
            disclosure_version=disclosure_version,
            disclosure_digest="sha256:" + "e" * 64,
            consented_at_utc=COMMITTED_AT,
        )

    def test_114_a1_c01_timezone_field_update(self) -> None:
        transition = self._timezone_update(
            "America/New_York", committed_at="2026-03-07T23:00:00+00:00"
        )
        result = transition.result
        self.assertEqual(
            (
                result["old_value"],
                result["new_value"],
                result["settings_version"],
                result["effective_at_utc"],
            ),
            (
                "Asia/Shanghai",
                "America/New_York",
                SETTINGS_VERSION + 1,
                "2026-03-08T05:00:00+00:00",
            ),
        )

    def test_114_a1_c02_contact_window_field_update(self) -> None:
        transition = self._apply(
            self._field("contact_window", "09:00-21:00", "18:30-21:30")
        )
        self.assertEqual(
            transition.result,
            {
                "kind": "field_update",
                "field_name": "contact_window",
                "old_value": "09:00-21:00",
                "new_value": "18:30-21:30",
                "settings_version": SETTINGS_VERSION + 1,
                "effective_at_utc": COMMITTED_AT,
            },
        )

    def test_114_a1_c03_expression_style_field_update(self) -> None:
        transition = self._apply(
            self._field("expression_style", "detailed", "concise")
        )
        self.assertEqual(
            (
                self._view(transition.state)["preferences"]["expression_style"],
                transition.result["old_value"],
                transition.result["new_value"],
            ),
            ("concise", "detailed", "concise"),
        )

    def test_114_a1_c04_proactive_contact_preference_update(self) -> None:
        before = self._view()
        transition = self._apply(
            self._field("proactive_contact", True, False)
        )
        after = self._view(transition.state)
        self.assertEqual(
            (
                after["preferences"]["proactive_contact"],
                after["preferences"]["contact_window"],
                after["controls"],
            ),
            (False, before["preferences"]["contact_window"], before["controls"]),
        )

    def test_114_a1_c05_concurrent_field_update(self) -> None:
        expression = self._apply(
            self._field("expression_style", "detailed", "concise")
        )
        contact_window = self._apply(
            self._field("contact_window", "09:00-21:00", "18:30-21:30"),
            state=expression.state,
        )
        self.assertEqual(
            self._view(contact_window.state)["preferences"],
            {
                "contact_window": "18:30-21:30",
                "expression_style": "concise",
                "proactive_contact": True,
            },
        )
        self.assertEqual(
            (
                contact_window.state.owner_id,
                contact_window.state.installation_id,
                contact_window.state.version,
            ),
            (OWNER, INSTALLATION, SETTINGS_VERSION + 2),
        )

    def test_114_a1_c06_invalid_iana_timezone(self) -> None:
        before = self.state.to_wire()
        with self.assertRaises(ValueError):
            self._apply(self._field("timezone", "Asia/Shanghai", "GMT+8"))
        self.assertEqual(self.state.to_wire(), before)

    def test_114_a1_c07_invalid_contact_window(self) -> None:
        before = self.state.to_wire()
        for invalid in ("24:00-01:00", "9am-10:00", "09:00", ""):
            with self.subTest(invalid_contact_window=invalid):
                with self.assertRaises(ValueError):
                    self._apply(
                        self._field("contact_window", "09:00-21:00", invalid)
                    )
                self.assertEqual(self.state.to_wire(), before)

    def _assert_notification_toggle(self, kind: str) -> None:
        before = self._view()["ordinary_notifications"]
        selected = self._apply(
            self._notification(kind, NOT_CONFIGURED, ENABLED)
        )
        after_selection = self._view(selected.state)["ordinary_notifications"]
        for candidate in settings.ORDINARY_NOTIFICATION_KINDS:
            with self.subTest(notification_kind=candidate, transition="first-selection"):
                self.assertEqual(
                    after_selection[candidate],
                    ENABLED if candidate == kind else before[candidate],
                )
        toggled = self._apply(
            self._notification(kind, ENABLED, DISABLED),
            state=selected.state,
        )
        after_toggle = self._view(toggled.state)["ordinary_notifications"]
        for candidate in settings.ORDINARY_NOTIFICATION_KINDS:
            with self.subTest(notification_kind=candidate, transition="later-toggle"):
                self.assertEqual(
                    after_toggle[candidate],
                    DISABLED if candidate == kind else before[candidate],
                )

    def test_114_a1_c08_notification_new_task_toggle(self) -> None:
        self._assert_notification_toggle("new_task")

    def test_114_a1_c09_notification_ordinary_stage_change_toggle(self) -> None:
        self._assert_notification_toggle("ordinary_stage_change")

    def test_114_a1_c10_notification_care_reminder_toggle(self) -> None:
        self._assert_notification_toggle("care_reminder")

    def test_114_a1_c11_notification_task_terminal_toggle(self) -> None:
        self._assert_notification_toggle("task_terminal")

    def test_114_a1_c12_notification_review_summary_toggle(self) -> None:
        self._assert_notification_toggle("review_summary")

    def test_114_a1_c13_exact_replay(self) -> None:
        command = self._field("expression_style", "detailed", "concise")
        first = self._apply(command)
        replay = self._apply(command, state=first.state)
        self.assertEqual(
            (replay.state.to_wire(), replay.result, replay.replayed),
            (first.state.to_wire(), first.result, True),
        )
        self.assertEqual(replay.state.version, first.state.version)

    def test_114_a1_c16_notifications_start_not_configured_without_defaults(self) -> None:
        self.assertEqual(
            self._view()["ordinary_notifications"],
            {
                kind: NOT_CONFIGURED
                for kind in settings.ORDINARY_NOTIFICATION_KINDS
            },
        )

    def test_114_a2_c01_control_cartesian_product_preserves_independence(self) -> None:
        baseline = self._state_with_approval()
        cases: tuple[tuple[str, Callable[[Any], Any]], ...] = (
            (
                "pause proactive support only",
                lambda state: self._apply(
                    self._control("proactive_support", "pause"), state=state
                ),
            ),
            (
                "stop recording only",
                lambda state: self._apply(
                    self._control("recording", "stop"), state=state
                ),
            ),
            (
                "cancel one task only",
                lambda state: self._apply(
                    self._control("task", "cancel", "task:synthetic-1"), state=state
                ),
            ),
            (
                "revoke one execution approval only",
                lambda state: self._apply(
                    _approval_command("revoke", command_id="matrix-revoke"),
                    state=state,
                ),
            ),
            (
                "pause current support contact only",
                lambda state: self._apply(
                    self._contact_command(
                        "pause", command_id="matrix-contact-pause"
                    ),
                    state=state,
                ),
            ),
        )
        for expected_name, run in cases:
            with self.subTest(control_effect=expected_name):
                before = self._control_vector(baseline)
                after = self._control_vector(run(baseline).state)
                changed = tuple(
                    name for name in before if before[name] != after[name]
                )
                expected_key = {
                    "pause proactive support only": "proactive_support",
                    "stop recording only": "recording",
                    "cancel one task only": "task",
                    "revoke one execution approval only": "approval",
                    "pause current support contact only": "support_contact",
                }[expected_name]
                self.assertEqual(changed, (expected_key,))

    def test_114_a2_c02_stale_generation_control_rejected(self) -> None:
        before = self.state.to_wire()
        with self.assertRaises(ValueError):
            self._apply(
                self._control(
                    "proactive_support",
                    "pause",
                    generation=CURRENT_HEAD_GENERATION - 1,
                ),
                current_head_generation=CURRENT_HEAD_GENERATION,
            )
        self.assertEqual(self.state.to_wire(), before)

    def test_114_a2_c03_concurrent_revoke_linearizes_once(self) -> None:
        granted = self._state_with_approval()
        first = self._apply(
            _approval_command("revoke", command_id="revoke-racer-1"),
            state=granted,
        )
        with self.assertRaises(ValueError):
            self._apply(
                _approval_command("revoke", command_id="revoke-racer-2"),
                state=first.state,
            )
        self.assertTrue(
            self._view(first.state)["execution_scope_approvals"][APPROVAL_ID][
                "revoked"
            ]
        )

    def test_114_a2_c04_unknown_effect_is_not_rewritten_as_unsent(self) -> None:
        decision = self.engine.rejudge_effect(
            self._state_with_approval(),
            effect_request_id=EFFECT_ID,
            observed_outcome="unknown",
        )
        self.assertEqual(
            (decision["outcome"], decision["action"], decision["may_retry"]),
            ("unknown", "freeze_pending_owner_decision", False),
        )

    def test_114_a2_c05_recording_resume_does_not_backfill(self) -> None:
        stopped = self._apply(
            self._control("recording", "stop"),
            committed_at="2026-08-24T02:00:00+00:00",
        )
        resumed = self._apply(
            self._control("recording", "resume"),
            state=stopped.state,
            committed_at="2026-08-25T02:00:00+00:00",
        )
        self.assertEqual(
            self._view(resumed.state)["recording_exclusions"],
            (
                {
                    "stopped_at_utc": "2026-08-24T02:00:00+00:00",
                    "resumed_at_utc": "2026-08-25T02:00:00+00:00",
                    "backfill_allowed": False,
                },
            ),
        )

    def test_114_a2_c06_unsent_effect_is_rejudged_against_current_controls(self) -> None:
        paused = self._apply(
            self._control("proactive_support", "pause")
        ).state
        decision = self.engine.rejudge_effect(
            paused,
            effect_request_id="effect-request:unsent-care-reminder",
            observed_outcome="unsent",
            effect_kind="care_reminder",
        )
        self.assertEqual(
            (decision["allowed"], decision["reason"], decision["action"]),
            (False, "proactive_support_paused", "suppress_without_backfill"),
        )

    def test_114_a4_c01_dst_gap_uses_earliest_valid_instant(self) -> None:
        transition = self._timezone_update(
            "America/Santiago", committed_at="2026-09-05T12:00:00+00:00"
        )
        pending = self._view(transition.state)["timezone_transition"]
        self.assertEqual(
            (
                pending["first_review_local_date"],
                pending["effective_at_utc"],
            ),
            ("2026-09-06", "2026-09-06T04:00:00+00:00"),
        )

    def test_114_a4_c02_dst_fold_uses_earliest_valid_instant(self) -> None:
        transition = self._timezone_update(
            "America/Havana", committed_at="2026-10-31T12:00:00+00:00"
        )
        pending = self._view(transition.state)["timezone_transition"]
        self.assertEqual(
            (
                pending["first_review_local_date"],
                pending["effective_at_utc"],
            ),
            ("2026-11-01", "2026-11-01T04:00:00+00:00"),
        )

    def test_114_a4_c03_cross_day_uses_strict_next_local_date(self) -> None:
        transition = self._timezone_update(
            "Pacific/Apia", committed_at="2011-12-29T12:00:00+00:00"
        )
        pending = self._view(transition.state)["timezone_transition"]
        self.assertEqual(
            (
                pending["first_review_local_date"],
                pending["effective_at_utc"],
            ),
            ("2011-12-31", "2011-12-30T10:00:00+00:00"),
        )

    def test_114_a4_c04_consecutive_pending_switches_keep_last_committed(self) -> None:
        first = self._timezone_update(
            "America/New_York", committed_at="2026-03-07T23:00:00+00:00"
        )
        second = self._apply(
            self._field(
                "timezone",
                "Asia/Shanghai",
                "Asia/Tokyo",
                effective_at="2026-03-08T00:00:00+00:00",
            ),
            state=first.state,
            committed_at="2026-03-08T00:00:00+00:00",
        )
        view = self._view(second.state)
        self.assertEqual(
            (
                view["timezone"],
                view["timezone_transition"]["new_timezone"],
                len(view["pending_timezone_transitions"]),
            ),
            ("Asia/Shanghai", "Asia/Tokyo", 1),
        )

    def test_114_a4_c05_restart_restores_committed_transition(self) -> None:
        transitioned = self._timezone_update(
            "America/New_York", committed_at="2026-03-07T23:00:00+00:00"
        ).state
        restarted = settings.OwnerSettingsState.from_wire(transitioned.to_wire())
        self.assertEqual(
            self._view(restarted)["timezone_transition"],
            self._view(transitioned)["timezone_transition"],
        )

    def test_114_a4_c06_existing_review_key_is_not_rewritten(self) -> None:
        transitioned = self._timezone_update(
            "America/New_York", committed_at="2026-03-07T23:00:00+00:00"
        ).state
        self.assertEqual(
            self._view(transitioned)["completed_review_keys"],
            ("2026-08-23@Asia/Shanghai",),
        )

    def test_114_a4_c07_old_days_are_not_backfilled_or_replayed(self) -> None:
        transitioned = self._timezone_update(
            "Pacific/Apia", committed_at="2011-12-29T12:00:00+00:00"
        ).state
        policy = self._view(transitioned)["review_policy"]
        self.assertEqual(
            (
                policy["backfill_local_dates"],
                policy["replay_completed_review_keys"],
            ),
            ((), ()),
        )

    def test_114_a4_c08_owner_can_see_effective_time(self) -> None:
        transitioned = self._timezone_update(
            "America/New_York", committed_at="2026-03-07T23:00:00+00:00"
        ).state
        owner_view = self._view(transitioned)
        self.assertEqual(
            owner_view["timezone_transition"]["effective_at_utc"],
            "2026-03-08T05:00:00+00:00",
        )

    def test_114_a4_c10_transition_is_not_effective_before_due_time(self) -> None:
        pending = self._timezone_update(
            "America/New_York", committed_at="2026-03-07T23:00:00+00:00"
        ).state
        before = pending.to_wire()
        transition = self.engine.activate_due_timezone_transition(
            pending,
            observed_at_utc="2026-03-08T04:59:59+00:00",
        )
        self.assertEqual(
            (
                transition.state.to_wire(),
                transition.result["outcome"],
                transition.result["state_changed"],
            ),
            (before, "pending", False),
        )

    def test_114_a4_c11_transition_activates_at_due_time(self) -> None:
        pending = self._timezone_update(
            "America/New_York", committed_at="2026-03-07T23:00:00+00:00"
        ).state
        transition = self.engine.activate_due_timezone_transition(
            pending,
            observed_at_utc="2026-03-08T05:00:00+00:00",
        )
        view = self._view(transition.state)
        self.assertEqual(
            (
                view["timezone"],
                view["timezone_transition"],
                view["completed_review_keys"],
                transition.state.version,
                transition.result["outcome"],
                transition.result["state_changed"],
            ),
            (
                "America/New_York",
                None,
                ("2026-08-23@Asia/Shanghai",),
                pending.version,
                "activated",
                True,
            ),
        )

    def test_114_a4_c12_restart_activates_persisted_transition_at_due_time(self) -> None:
        pending = self._timezone_update(
            "America/New_York", committed_at="2026-03-07T23:00:00+00:00"
        ).state
        restarted = settings.OwnerSettingsState.from_wire(pending.to_wire())
        transition = self.engine.activate_due_timezone_transition(
            restarted,
            observed_at_utc="2026-03-08T05:00:00+00:00",
        )
        self.assertEqual(
            (
                transition.state.timezone,
                transition.state.timezone_transition,
                transition.state.completed_review_keys,
                transition.result["effective_at_utc"],
            ),
            (
                "America/New_York",
                None,
                ("2026-08-23@Asia/Shanghai",),
                "2026-03-08T05:00:00+00:00",
            ),
        )

    def test_114_a7_c01_managed_read_shows_scope_recipient_enablement_consent(self) -> None:
        view = self._view()
        consent = view["consent"]
        self.assertEqual(
            (
                consent["data_scope"],
                consent["first_hop_recipient"],
                consent["enabled"],
                consent["consent_generation"],
                consent["disclosure_version"],
            ),
            (
                ("portrait", "evidence", "tasks"),
                RECIPIENT,
                True,
                1,
                DISCLOSURE_VERSION,
            ),
        )

    def test_114_a7_c02_route_drift_pauses_affected_path(self) -> None:
        drifted = self._drift(
            route_id="partner-first-hop-v2",
            recipient="https://model-v2.example/v1",
            disclosure_version="health-recipient-disclosure-v4",
        ).state
        consent = self._view(drifted)["consent"]
        self.assertEqual(
            (consent["path_status"], consent["pause_reason"]),
            ("paused", "first_hop_route_changed"),
        )

    def test_114_a7_c03_config_generation_drift_pauses_affected_path(self) -> None:
        drifted = self._drift(configuration_generation=12).state
        consent = self._view(drifted)["consent"]
        self.assertEqual(
            (consent["path_status"], consent["pause_reason"]),
            ("paused", "configuration_generation_changed"),
        )

    def test_114_a7_c04_exact_redisclosure_is_required(self) -> None:
        drifted = self._drift(
            route_id="partner-first-hop-v2",
            recipient="https://model-v2.example/v1",
            configuration_generation=12,
            disclosure_version="health-recipient-disclosure-v4",
        ).state
        required = self._view(drifted)["consent"]["required_redisclosure"]
        self.assertEqual(
            required,
            {
                "route_id": "partner-first-hop-v2",
                "first_hop_recipient": "https://model-v2.example/v1",
                "configuration_generation": 12,
                "disclosure_version": "health-recipient-disclosure-v4",
            },
        )

    def test_114_a7_c05_exact_reconsent_resumes_path(self) -> None:
        drifted = self._drift(
            route_id="partner-first-hop-v2",
            recipient="https://model-v2.example/v1",
            configuration_generation=12,
            disclosure_version="health-recipient-disclosure-v4",
        ).state
        renewed = self._apply(
            self._renewal(
                command_id="exact-reconsent",
                route_id="partner-first-hop-v2",
                recipient="https://model-v2.example/v1",
                configuration_generation=12,
                disclosure_version="health-recipient-disclosure-v4",
            ),
            state=drifted,
        )
        consent = self._view(renewed.state)["consent"]
        self.assertEqual(
            (
                consent["path_status"],
                consent["route_id"],
                consent["configuration_generation"],
                consent["disclosure_version"],
            ),
            ("active", "partner-first-hop-v2", 12, "health-recipient-disclosure-v4"),
        )

    def test_114_a7_c06_stale_disclosure_rejected(self) -> None:
        drifted = self._drift(
            route_id="partner-first-hop-v2",
            recipient="https://model-v2.example/v1",
            configuration_generation=12,
            disclosure_version="health-recipient-disclosure-v4",
        ).state
        before = drifted.to_wire()
        with self.assertRaises(ValueError):
            self._apply(
                self._renewal(
                    command_id="stale-disclosure",
                    route_id="partner-first-hop-v2",
                    recipient="https://model-v2.example/v1",
                    configuration_generation=12,
                    disclosure_version=DISCLOSURE_VERSION,
                ),
                state=drifted,
            )
        self.assertEqual(drifted.to_wire(), before)

    def test_114_a7_c07_stale_generation_rejected(self) -> None:
        drifted = self._drift(configuration_generation=12).state
        before = drifted.to_wire()
        with self.assertRaises(ValueError):
            self._apply(
                self._renewal(
                    command_id="stale-consent-generation",
                    route_id=ROUTE_ID,
                    recipient=RECIPIENT,
                    configuration_generation=12,
                    disclosure_version=DISCLOSURE_VERSION,
                    generation=CURRENT_HEAD_GENERATION - 1,
                ),
                state=drifted,
                current_head_generation=CURRENT_HEAD_GENERATION,
            )
        self.assertEqual(drifted.to_wire(), before)

    def test_114_a7_c08_close_but_retain_returns_clarification_without_state_change(self) -> None:
        command = settings.CloseButRetainRequest(
            context=_context("close-but-retain-ambiguous")
        )
        transition = self._apply(command)
        self.assertEqual(
            (
                transition.state.to_wire(),
                transition.result["outcome"],
                transition.result["state_changed"],
                transition.result["clarify_controls"],
            ),
            (
                self.state.to_wire(),
                "clarification_required",
                False,
                (
                    "proactive_support",
                    "recording",
                    "task",
                    "execution_scope_approval",
                ),
            ),
        )

    def test_114_a7_c10_old_route_configuration_fact_is_rejected(self) -> None:
        current = self._drift(configuration_generation=12).state
        before = current.to_wire()
        stale = settings.RouteConfigurationUpdate(
            route_id="partner-first-hop-stale",
            first_hop_recipient="https://model-stale.example/v1",
            configuration_generation=CONFIGURATION_GENERATION,
            disclosure_version="health-recipient-disclosure-stale",
            generation=CURRENT_HEAD_GENERATION,
        )
        with self.assertRaises(ValueError):
            self.engine.observe_route_configuration(current, stale)
        self.assertEqual(current.to_wire(), before)

    def test_114_a8_c01_full_field_approval_grant(self) -> None:
        approval = _approval()
        transition = self._apply(
            _approval_command(
                "grant", command_id="full-approval-grant", approval=approval
            )
        )
        self.assertEqual(
            self._view(transition.state)["execution_scope_approvals"][APPROVAL_ID],
            approval.to_wire(),
        )

    def test_114_a8_c02_full_field_approval_revision(self) -> None:
        granted = self._state_with_approval()
        revised = _approval(
            version=2,
            purpose="send one revised owner-approved appointment request",
            refs=("managed-object:task:synthetic-1:v4",),
            max_attempts=2,
        )
        transition = self._apply(
            _approval_command(
                "revise", command_id="full-approval-revise", approval=revised
            ),
            state=granted,
        )
        self.assertEqual(
            self._view(transition.state)["execution_scope_approvals"][APPROVAL_ID],
            revised.to_wire(),
        )

    def test_114_a8_c03_full_field_approval_revoke(self) -> None:
        granted = self._state_with_approval()
        transition = self._apply(
            _approval_command("revoke", command_id="full-approval-revoke"),
            state=granted,
        )
        current = self._view(transition.state)["execution_scope_approvals"][
            APPROVAL_ID
        ]
        self.assertEqual(
            (current["approval_version"], current["revoked"], current["revoked_at_utc"]),
            (2, True, COMMITTED_AT),
        )

    def test_114_a8_c04_blank_approval_rejected(self) -> None:
        for field in (
            "purpose",
            "assignee",
            "first_hop_recipient",
            "route_id",
            "disclosure_version",
        ):
            with self.subTest(blank_authority_field=field):
                wire = _approval().to_wire()
                wire[field] = ""
                with self.assertRaises(ValueError):
                    settings.ExecutionScopeApproval.from_wire(wire)

    def test_114_a8_c05_wildcard_approval_rejected(self) -> None:
        scalar_fields = (
            "purpose",
            "assignee",
            "first_hop_recipient",
            "route_id",
            "disclosure_version",
        )
        for field in scalar_fields:
            with self.subTest(wildcard_authority_field=field):
                wire = _approval().to_wire()
                wire[field] = "*"
                with self.assertRaises(ValueError):
                    settings.ExecutionScopeApproval.from_wire(wire)
        for field in ("allowed_data_categories", "allowed_data_refs"):
            with self.subTest(wildcard_scope_collection=field):
                wire = _approval().to_wire()
                wire[field] = ["*"]
                with self.assertRaises(ValueError):
                    settings.ExecutionScopeApproval.from_wire(wire)

    def test_114_a8_c06_scope_expansion_requires_new_version_and_reapproval(self) -> None:
        expansions: tuple[tuple[str, dict[str, object]], ...] = (
            ("owner burden max attempts", {"max_attempts": 2}),
            ("owner burden contact cadence", {"min_contact_interval_seconds": 1}),
            ("data categories", {"allowed_data_categories": ["appointment_request", "portrait"]}),
            ("stable data references", {"allowed_data_refs": ["managed-object:task:synthetic-1:v3", "managed-object:portrait:synthetic-1:v2"]}),
            ("first-hop recipient", {"first_hop_recipient": "https://appointments-v2.example/v1"}),
            ("external effect kind", {"external_effect_kind": "appointment_and_sms_request"}),
            ("acceptance meaning", {"purpose": "request an appointment and confirm an external booking"}),
        )
        for label, changes in expansions:
            with self.subTest(expansion_dimension=label):
                granted = self._state_with_approval()
                stale_wire = _approval().to_wire()
                stale_wire.update(changes)
                stale = settings.ExecutionScopeApproval.from_wire(stale_wire)
                rejected = False
                try:
                    self._apply(
                        _approval_command(
                            "revise",
                            command_id="unapproved-expansion-" + label.replace(" ", "-"),
                            approval=stale,
                        ),
                        state=granted,
                    )
                except ValueError:
                    rejected = True
                approved_wire = dict(stale_wire)
                approved_wire["approval_version"] = 2
                approved = settings.ExecutionScopeApproval.from_wire(approved_wire)
                accepted = self._apply(
                    _approval_command(
                        "revise",
                        command_id="approved-expansion-" + label.replace(" ", "-"),
                        approval=approved,
                    ),
                    state=granted,
                )
                current = self._view(accepted.state)["execution_scope_approvals"][
                    APPROVAL_ID
                ]
                self.assertEqual(
                    (rejected, current["approval_version"], current["revoked"]),
                    (True, 2, False),
                )

    def test_114_a8_c07_stale_generation_rejected(self) -> None:
        before = self.state.to_wire()
        stale = _approval()
        with self.assertRaises(ValueError):
            self._apply(
                _approval_command(
                    "grant",
                    command_id="stale-approval-generation",
                    approval=stale,
                    generation=CURRENT_HEAD_GENERATION - 1,
                ),
                current_head_generation=CURRENT_HEAD_GENERATION,
            )
        self.assertEqual(self.state.to_wire(), before)

    def test_114_a8_c08_stale_version_rejected(self) -> None:
        granted = self._state_with_approval()
        before = granted.to_wire()
        with self.assertRaises(ValueError):
            self._apply(
                _approval_command(
                    "revise",
                    command_id="stale-approval-version",
                    approval=_approval(version=1, purpose="changed without version"),
                ),
                state=granted,
            )
        self.assertEqual(granted.to_wire(), before)

    def test_114_a8_c09_exact_replay(self) -> None:
        command = _approval_command(
            "grant", command_id="approval-exact-replay", approval=_approval()
        )
        first = self._apply(command)
        replay = self._apply(command, state=first.state)
        self.assertEqual(
            (replay.state.to_wire(), replay.result, replay.replayed),
            (first.state.to_wire(), first.result, True),
        )

    def test_114_a8_c10_concurrent_revoke_linearizes_once(self) -> None:
        granted = self._state_with_approval()
        winner = self._apply(
            _approval_command("revoke", command_id="approval-revoke-winner"),
            state=granted,
        )
        loser_rejected = False
        try:
            self._apply(
                _approval_command("revoke", command_id="approval-revoke-loser"),
                state=winner.state,
            )
        except ValueError:
            loser_rejected = True
        current = self._view(winner.state)["execution_scope_approvals"][APPROVAL_ID]
        self.assertEqual(
            (loser_rejected, current["approval_version"], current["revoked"]),
            (True, 2, True),
        )

    def test_114_a8_c11_unknown_revoke_freezes_consumption(self) -> None:
        granted = self._state_with_approval()
        decision = self.engine.rejudge_effect(
            granted,
            effect_request_id=EFFECT_ID,
            approval_id=APPROVAL_ID,
            observed_outcome="unknown-revocation",
        )
        self.assertEqual(
            (
                decision["approval_consumable"],
                decision["action"],
                decision["may_retry"],
            ),
            (False, "freeze_pending_authority_confirmation", False),
        )

    def test_114_a8_c14_route_mismatch_cannot_consume_approval(self) -> None:
        granted = self._state_with_approval()
        current = self.engine.validate_execution_scope_consumption(
            granted,
            _consumption(),
        )
        decision = self.engine.validate_execution_scope_consumption(
            granted,
            _consumption(route_id="approved-appointment-route-old"),
        )
        self.assertEqual(
            (current.allowed, current.reason),
            (True, "approval_current_and_within_scope"),
        )
        self.assertEqual((decision.allowed, decision.reason), (False, "route_mismatch"))

    def test_114_a8_c15_configuration_generation_mismatch_cannot_consume_approval(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(configuration_generation=CONFIGURATION_GENERATION - 1),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "configuration_generation_mismatch"),
        )

    def test_114_a8_c16_disclosure_version_mismatch_cannot_consume_approval(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(disclosure_version="execution-disclosure-v1"),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "disclosure_version_mismatch"),
        )

    def test_114_a8_c17_first_hop_recipient_mismatch_cannot_consume_approval(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(first_hop_recipient="https://appointments-old.example/v1"),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "first_hop_recipient_mismatch"),
        )

    def test_114_a8_c18_expired_approval_cannot_be_consumed(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(evaluated_at_utc="2026-08-31T03:00:00+00:00"),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "approval_expired"),
        )

    def test_114_a8_c19_task_mismatch_cannot_consume_approval(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(task_id="task:synthetic-other"),
        )
        self.assertEqual((decision.allowed, decision.reason), (False, "task_mismatch"))

    def test_114_a8_c20_effect_request_mismatch_cannot_consume_approval(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(effect_request_id="effect-request:synthetic-other"),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "effect_request_mismatch"),
        )

    def test_114_a8_c21_assignee_mismatch_cannot_consume_approval(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(assignee="another-plugin"),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "assignee_mismatch"),
        )

    def test_114_a8_c22_purpose_mismatch_cannot_consume_approval(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(purpose="send a broader appointment and transport request"),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "purpose_mismatch"),
        )

    def test_114_a8_c23_data_category_outside_scope_cannot_consume_approval(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(data_categories=("appointment_request", "portrait")),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "data_category_outside_scope"),
        )

    def test_114_a8_c24_data_reference_outside_scope_cannot_consume_approval(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(data_refs=("managed-object:portrait:synthetic-1:v2",)),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "data_reference_outside_scope"),
        )

    def test_114_a8_c25_external_effect_kind_mismatch_cannot_consume_approval(self) -> None:
        decision = self.engine.validate_execution_scope_consumption(
            self._state_with_approval(),
            _consumption(external_effect_kind="appointment_and_sms_request"),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "external_effect_kind_mismatch"),
        )

    def test_114_a8_c26_attempt_limit_is_validated_without_persisting_a_counter(self) -> None:
        granted = self._state_with_approval()
        before = granted.to_wire()
        decision = self.engine.validate_execution_scope_consumption(
            granted,
            _consumption(attempts_used=1),
        )
        self.assertEqual(
            (decision.allowed, decision.reason, granted.to_wire()),
            (False, "maximum_attempts_reached", before),
        )

    def test_114_a8_c27_minimum_interval_is_validated_without_persisting_contact_time(self) -> None:
        granted = self._state_with_approval()
        before = granted.to_wire()
        decision = self.engine.validate_execution_scope_consumption(
            granted,
            _consumption(last_contact_at_utc="2026-08-24T02:59:59+00:00"),
        )
        self.assertEqual(
            (decision.allowed, decision.reason, granted.to_wire()),
            (False, "minimum_contact_interval_not_elapsed", before),
        )

    def test_114_a8_c28_revoked_approval_cannot_be_consumed(self) -> None:
        granted = self._state_with_approval()
        revoked = self._apply(
            _approval_command("revoke", command_id="approval-revoked-before-consume"),
            state=granted,
        ).state
        decision = self.engine.validate_execution_scope_consumption(
            revoked,
            _consumption(approval_version=2),
        )
        self.assertEqual(
            (decision.allowed, decision.reason),
            (False, "approval_revoked"),
        )

    def test_114_a8_c29_same_head_stale_writer_fence_rejects_every_approval_mutation(self) -> None:
        granted = self._state_with_approval()
        cases = (
            (
                "grant",
                self.state,
                _approval(),
            ),
            (
                "revise",
                granted,
                _approval(version=2, purpose="revised exact purpose"),
            ),
            ("revoke", granted, None),
        )
        for operation, state, approval in cases:
            with self.subTest(operation=operation):
                before = state.to_wire()
                command = _approval_command(
                    operation,
                    command_id=f"stale-writer-fence-{operation}",
                    approval=approval,
                    writer_fence="writer-fence:7:stale",
                )
                with self.assertRaises(ValueError):
                    self._apply(command, state=state)
                self.assertEqual(state.to_wire(), before)

    def test_114_a9_c01_managed_read_shows_current_contact_contract(self) -> None:
        contact = self._view()["support_contact"]
        self.assertEqual(
            {
                key: contact[key]
                for key in (
                    "configuration_status",
                    "contact_id",
                    "identity_label",
                    "method_kind",
                    "method_value",
                    "purpose",
                    "minimum_alert_fields",
                    "route_id",
                    "route_generation",
                    "dedicated_paused",
                    "alert_authority_status",
                    "correction_authority_status",
                    "max_corrections_per_alert",
                )
            },
            {
                "configuration_status": "configured",
                "contact_id": "support-contact:synthetic-1",
                "identity_label": "Owner-recognizable trusted contact",
                "method_kind": "weixin_user",
                "method_value": "wxid_synthetic_contact",
                "purpose": "minimum urgent-help contact alert",
                "minimum_alert_fields": (
                    "owner_recognizable_name",
                    "event_time",
                    "fixed_urgent_help_request",
                ),
                "route_id": "weixin-ilink-partner",
                "route_generation": 5,
                "dedicated_paused": False,
                "alert_authority_status": "approved",
                "correction_authority_status": "approved",
                "max_corrections_per_alert": 1,
            },
        )

    def test_114_a9_c18_managed_read_shows_support_contact_not_configured(self) -> None:
        state = self._seed(contact=None)
        self.assertEqual(
            self._view(state)["support_contact"],
            {"configuration_status": "not-configured"},
        )
        self.assertIsNone(state.support_contact)

    def test_114_a9_c19_owner_configures_first_support_contact_from_not_configured(self) -> None:
        state = self._seed(contact=None)
        contact = _support_contact(approved=False, version=1)
        configured = self._apply(
            self._contact_command(
                "configure",
                command_id="contact-first-configuration",
                contact=contact,
                expected_version=None,
                expected_route_id=None,
                expected_route_generation=None,
            ),
            state=state,
        )
        current = self._view(configured.state)["support_contact"]
        self.assertEqual(
            (
                current["configuration_status"],
                current["version"],
                current["alert_authority_status"],
                current["correction_authority_status"],
            ),
            ("configured", 1, "invalidated", "invalidated"),
        )

    def test_114_a9_c02_contact_replace(self) -> None:
        replacement = _support_contact(
            approved=False,
            contact_id="support-contact:synthetic-2",
            version=4,
            method_value="wxid_synthetic_contact_2",
            disclosure_version="support-contact-disclosure-v4",
        )
        transition = self._apply(
            self._contact_command(
                "replace",
                command_id="contact-replace",
                contact=replacement,
            )
        )
        current = self._view(transition.state)["support_contact"]
        self.assertEqual(
            (
                current["contact_id"],
                current["version"],
                current["alert_authority_status"],
                current["correction_authority_status"],
            ),
            ("support-contact:synthetic-2", 4, "invalidated", "invalidated"),
        )

    def test_114_a9_c03_method_change(self) -> None:
        changed = _support_contact(
            approved=False,
            version=4,
            method_kind="telephone_e164",
            method_value="+8613800138000",
            disclosure_version="support-contact-disclosure-v4",
        )
        transition = self._apply(
            self._contact_command(
                "change_method",
                command_id="contact-method-change",
                contact=changed,
            )
        )
        current = self._view(transition.state)["support_contact"]
        self.assertEqual(
            (
                current["method_kind"],
                current["method_value"],
                current["alert_authority_status"],
                current["correction_authority_status"],
            ),
            ("telephone_e164", "+8613800138000", "invalidated", "invalidated"),
        )

    def test_114_a9_c04_dedicated_pause(self) -> None:
        transition = self._apply(
            self._contact_command("pause", command_id="contact-dedicated-pause")
        )
        view = self._view(transition.state)
        self.assertEqual(
            (
                view["support_contact"]["dedicated_paused"],
                view["controls"]["proactive_support_paused"],
            ),
            (True, False),
        )

    def test_114_a9_c05_dedicated_resume(self) -> None:
        paused = self._apply(
            self._contact_command("pause", command_id="contact-pause-before-resume")
        ).state
        resumed = self._apply(
            self._contact_command(
                "resume",
                command_id="contact-dedicated-resume",
                expected_version=4,
            ),
            state=paused,
        )
        self.assertFalse(self._view(resumed.state)["support_contact"]["dedicated_paused"])

    def test_114_a9_c06_alert_authority_grant(self) -> None:
        unapproved = self._seed(contact=_support_contact(approved=False))
        transition = self._apply(
            self._contact_command(
                "grant_alert_authority",
                command_id="contact-alert-grant",
                authority_id="alert-approval:synthetic-2",
            ),
            state=unapproved,
        )
        current = self._view(transition.state)["support_contact"]
        self.assertEqual(
            (
                current["alert_authority_status"],
                current["alert_approval_id"],
                current["correction_authority_status"],
            ),
            ("approved", "alert-approval:synthetic-2", "invalidated"),
        )

    def test_114_a9_c07_alert_authority_revoke(self) -> None:
        transition = self._apply(
            self._contact_command(
                "revoke_alert_authority",
                command_id="contact-alert-revoke",
                authority_id="alert-approval:synthetic-1",
            )
        )
        current = self._view(transition.state)["support_contact"]
        self.assertEqual(
            (
                current["alert_authority_status"],
                current["correction_authority_status"],
            ),
            ("revoked", "approved"),
        )

    def test_114_a9_c08_alert_authority_reapprove(self) -> None:
        revoked = self._apply(
            self._contact_command(
                "revoke_alert_authority",
                command_id="contact-alert-revoke-before-reapprove",
                authority_id="alert-approval:synthetic-1",
            )
        ).state
        reapproved = self._apply(
            self._contact_command(
                "grant_alert_authority",
                command_id="contact-alert-reapprove",
                authority_id="alert-approval:synthetic-3",
                expected_version=4,
            ),
            state=revoked,
        )
        current = self._view(reapproved.state)["support_contact"]
        self.assertEqual(
            (current["alert_authority_status"], current["alert_approval_id"]),
            ("approved", "alert-approval:synthetic-3"),
        )

    def test_114_a9_c09_correction_authority_grant(self) -> None:
        unapproved = self._seed(contact=_support_contact(approved=False))
        transition = self._apply(
            self._contact_command(
                "grant_correction_authority",
                command_id="contact-correction-grant",
                authority_id="correction-authority:synthetic-2",
            ),
            state=unapproved,
        )
        current = self._view(transition.state)["support_contact"]
        self.assertEqual(
            (
                current["correction_authority_status"],
                current["correction_authority_id"],
                current["alert_authority_status"],
            ),
            ("approved", "correction-authority:synthetic-2", "invalidated"),
        )

    def test_114_a9_c10_correction_authority_revoke(self) -> None:
        transition = self._apply(
            self._contact_command(
                "revoke_correction_authority",
                command_id="contact-correction-revoke",
                authority_id="correction-authority:synthetic-1",
            )
        )
        current = self._view(transition.state)["support_contact"]
        self.assertEqual(
            (
                current["correction_authority_status"],
                current["alert_authority_status"],
            ),
            ("revoked", "approved"),
        )

    def test_114_a9_c11_correction_authority_reapprove(self) -> None:
        revoked = self._apply(
            self._contact_command(
                "revoke_correction_authority",
                command_id="contact-correction-revoke-before-reapprove",
                authority_id="correction-authority:synthetic-1",
            )
        ).state
        reapproved = self._apply(
            self._contact_command(
                "grant_correction_authority",
                command_id="contact-correction-reapprove",
                authority_id="correction-authority:synthetic-3",
                expected_version=4,
            ),
            state=revoked,
        )
        current = self._view(reapproved.state)["support_contact"]
        self.assertEqual(
            (
                current["correction_authority_status"],
                current["correction_authority_id"],
            ),
            ("approved", "correction-authority:synthetic-3"),
        )

    def test_114_a9_c12_stale_route_rejected(self) -> None:
        before = self.state.to_wire()
        with self.assertRaises(ValueError):
            self._apply(
                self._contact_command(
                    "pause",
                    command_id="contact-stale-route",
                    expected_route_id="weixin-ilink-old",
                    expected_route_generation=4,
                )
            )
        self.assertEqual(self.state.to_wire(), before)

    def test_114_a9_c13_stale_generation_rejected(self) -> None:
        before = self.state.to_wire()
        with self.assertRaises(ValueError):
            self._apply(
                self._contact_command(
                    "pause",
                    command_id="contact-stale-generation",
                    generation=CURRENT_HEAD_GENERATION - 1,
                ),
                current_head_generation=CURRENT_HEAD_GENERATION,
            )
        self.assertEqual(self.state.to_wire(), before)

    def test_114_a9_c14_non_owner_rejected(self) -> None:
        valid = self._contact_command(
            "pause", command_id="contact-owner-only"
        ).to_wire()
        forged = copy.deepcopy(valid)
        forged["context"]["actor_kind"] = "support_contact"
        with self.assertRaises(ValueError):
            settings.SupportContactCommand.from_wire(forged)

    def test_114_a9_c15_contact_controls_are_independent_of_general_controls(self) -> None:
        operations = (
            ("dedicated pause", "pause", None),
            ("alert revoke", "revoke_alert_authority", "alert-approval:synthetic-1"),
            (
                "correction revoke",
                "revoke_correction_authority",
                "correction-authority:synthetic-1",
            ),
        )
        before = self._view()
        general_before = (
            before["controls"],
            before["preferences"],
            before["ordinary_notifications"],
        )
        for label, operation, authority_id in operations:
            with self.subTest(contact_control=label):
                transition = self._apply(
                    self._contact_command(
                        operation,
                        command_id="independent-" + operation,
                        authority_id=authority_id,
                    )
                )
                after = self._view(transition.state)
                self.assertEqual(
                    (
                        after["controls"],
                        after["preferences"],
                        after["ordinary_notifications"],
                    ),
                    general_before,
                )

    def test_114_a9_c20_old_contact_object_version_is_rejected_without_state_change(self) -> None:
        before = self.state.to_wire()
        with self.assertRaises(ValueError):
            self._apply(
                self._contact_command(
                    "pause",
                    command_id="contact-stale-object-version",
                    expected_version=2,
                )
            )
        self.assertEqual(self.state.to_wire(), before)

    def test_114_a9_c21_same_head_stale_writer_fence_is_rejected_before_mutation(self) -> None:
        before = self.state.to_wire()
        with self.assertRaises(ValueError):
            self._apply(
                self._contact_command(
                    "pause",
                    command_id="contact-stale-writer-fence",
                    writer_fence="writer-fence:7:stale",
                )
            )
        self.assertEqual(self.state.to_wire(), before)

    def test_114_a9_c22_owner_or_installation_cross_replay_invalidates_authority_binding(self) -> None:
        for field, value in (
            ("owner_id", "owner-synthetic-other"),
            ("installation_id", "installation-synthetic-other"),
        ):
            with self.subTest(replayed_authority=field):
                wire = _support_contact().to_wire()
                wire[field] = value
                with self.assertRaises(ValueError):
                    settings.SupportContactSettings.from_wire(wire)

    def test_114_a9_c23_purpose_change_invalidates_authority_binding(self) -> None:
        wire = _support_contact().to_wire()
        wire["purpose"] = "urgent alert plus appointment scheduling"
        with self.assertRaises(ValueError):
            settings.SupportContactSettings.from_wire(wire)

    def test_114_a9_c24_minimum_alert_fields_change_invalidates_authority_binding(self) -> None:
        wire = _support_contact().to_wire()
        wire["minimum_alert_fields"] = [
            "owner_recognizable_name",
            "event_time",
            "fixed_urgent_help_request",
            "full_health_summary",
        ]
        with self.assertRaises(ValueError):
            settings.SupportContactSettings.from_wire(wire)


if __name__ == "__main__":
    unittest.main()

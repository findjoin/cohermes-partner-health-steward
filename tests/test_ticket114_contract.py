import copy
import hashlib
import importlib
import json
import re
import unittest
from collections import Counter
from pathlib import Path

from tests.ticket114_case_registry import CASE_REGISTRY, MODULE_CASE_IDS


def _settings():
    return importlib.import_module("partner_health_steward.settings")


def _rights():
    return importlib.import_module("partner_health_steward.rights")


def _status():
    return importlib.import_module("partner_health_steward.status")


def _field_update_wire() -> dict[str, object]:
    return {
        "field_name": "contact_window",
        "old_value": "09:00-21:00",
        "new_value": "18:30-21:30",
        "generation": 7,
        "effective_at_utc": "2026-08-24T01:02:03+00:00",
    }


def _notification_wire(kind: str) -> dict[str, object]:
    return {
        "kind": kind,
        "old_state": "not-configured",
        "new_state": "enabled",
        "generation": 7,
        "effective_at_utc": "2026-08-24T01:02:03+00:00",
    }


def _context_wire() -> dict[str, object]:
    return {
        "command_id": "owner-command-114",
        "causal_id": "weixin-message:synthetic-114",
        "actor_kind": "current_owner",
        "owner_id": "owner-synthetic",
        "installation_id": "installation-synthetic",
        "permission": "health_settings.write",
        "context_ref": "managed-context:settings-revision-6",
        "generation": 7,
        "writer_fence": "writer-fence:7:synthetic",
    }


def _control_update_wire(
    control_name: str = "proactive_support",
    operation: str = "pause",
    target_ref: str | None = None,
) -> dict[str, object]:
    return {
        "control_name": control_name,
        "operation": operation,
        "target_ref": target_ref,
        "generation": 7,
        "effective_at_utc": "2026-08-24T01:02:03+00:00",
    }


def _owner_control_command_wire(
    update: dict[str, object] | None = None,
    approval: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "context": _context_wire(),
        "control_update": update or _control_update_wire(),
        "execution_scope_approval": approval,
    }


def _managed_object_wire() -> dict[str, object]:
    return {
        "object_ref": "managed-object:portrait:card-1:v3",
        "object_kind": "portrait_item",
        "owner_id": "owner-synthetic",
        "installation_id": "installation-synthetic",
        "version": 3,
        "current": True,
        "source_refs": ["source:weixin-message:synthetic-1"],
        "evidence_refs": ["evidence-card:synthetic-1:v2"],
        "value": {"topic_id": "sleep", "status": "owner_confirmed"},
    }


def _correction_wire() -> dict[str, object]:
    return {
        "correction_id": "correction:synthetic-1",
        "object_ref": "managed-object:portrait:card-1",
        "previous_version": 3,
        "revision_version": 4,
        "reason": "owner corrected the recorded date",
        "corrected_at_utc": "2026-08-24T02:00:00+00:00",
        "source_refs": ["source:owner-correction:synthetic-1"],
        "evidence_refs": ["evidence-card:synthetic-1:v2"],
        "affected_object_refs": ["task:synthetic-1", "portrait:sleep"],
        "disposition_requests": ["withdraw_current", "rejudge"],
    }


def _export_wire() -> dict[str, object]:
    return {
        "snapshot_id": "export-snapshot:synthetic-1",
        "owner_id": "owner-synthetic",
        "installation_id": "installation-synthetic",
        "source_state_digest": "sha256:" + "a" * 64,
        "schema_version": "managed-export-v1",
        "created_at_utc": "2026-08-24T02:30:00+00:00",
        "object_refs": ["managed-object:portrait:card-1:v4"],
        "source_refs": ["source:owner-correction:synthetic-1"],
        "evidence_refs": ["evidence-card:synthetic-1:v2"],
    }


def _timezone_transition_wire() -> dict[str, object]:
    return {
        "transition_id": "timezone-transition:synthetic-1",
        "owner_id": "owner-synthetic",
        "installation_id": "installation-synthetic",
        "settings_version": 7,
        "previous_timezone": "Asia/Shanghai",
        "new_timezone": "America/New_York",
        "requested_at_utc": "2026-03-07T23:00:00+00:00",
        "first_review_local_date": "2026-03-08",
        "effective_at_utc": "2026-03-08T05:00:00+00:00",
    }


def _consent_wire() -> dict[str, object]:
    return {
        "renewal_id": "consent-renewal:synthetic-1",
        "context": _context_wire(),
        "route_id": "partner-first-hop",
        "first_hop_recipient": "https://model.example/v1",
        "configuration_generation": 11,
        "disclosure_version": "health-recipient-disclosure-v3",
        "disclosure_digest": "sha256:" + "d" * 64,
        "consented_at_utc": "2026-08-24T03:00:00+00:00",
    }


def _approval_wire() -> dict[str, object]:
    return {
        "approval_id": "execution-approval:synthetic-1",
        "approval_version": 2,
        "owner_id": "owner-synthetic",
        "installation_id": "installation-synthetic",
        "task_id": "task:synthetic-1",
        "effect_request_id": "effect-request:synthetic-1",
        "assignee": "partner-health-plugin",
        "purpose": "send one owner-approved appointment request",
        "allowed_data_categories": ["appointment_request"],
        "allowed_data_refs": ["managed-object:task:synthetic-1:v3"],
        "first_hop_recipient": "https://appointments.example/v1",
        "external_effect_kind": "appointment_request",
        "max_attempts": 1,
        "min_contact_interval_seconds": 86400,
        "expires_at_utc": "2026-08-31T03:00:00+00:00",
        "route_id": "approved-appointment-route",
        "configuration_generation": 11,
        "disclosure_version": "execution-disclosure-v2",
        "revoked": False,
        "revoked_at_utc": None,
    }


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


def _support_contact_wire(*, approved: bool = True) -> dict[str, object]:
    wire: dict[str, object] = {
        "contact_id": "support-contact:synthetic-1",
        "version": 3,
        "owner_id": "owner-synthetic",
        "installation_id": "installation-synthetic",
        "identity_label": "Owner-recognizable trusted contact",
        "method_kind": "weixin_user",
        "method_value": "wxid_synthetic_contact",
        "purpose": "minimum urgent-help contact alert",
        "minimum_alert_fields": [
            "owner_recognizable_name",
            "event_time",
            "fixed_urgent_help_request",
        ],
        "route_id": "weixin-ilink-partner",
        "route_generation": 5,
        "disclosure_version": "support-contact-disclosure-v3",
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
    return wire


class Ticket114RegistryTests(unittest.TestCase):
    def test_case_registry_has_208_unique_cases_in_acceptance_order(self) -> None:
        expected = tuple(
            f"114-A{acceptance}-C{case:02d}"
            for acceptance, count in (
                (1, 18), (2, 34), (3, 31), (4, 13), (5, 21),
                (6, 23), (7, 12), (8, 29), (9, 27),
            )
            for case in range(1, count + 1)
        )
        actual = tuple(case_id for case_id, _, _ in CASE_REGISTRY)
        self.assertEqual(len(actual), 208)
        self.assertEqual(len(set(actual)), 208)
        self.assertEqual(actual, expected)

    def test_case_registry_dotted_test_names_resolve_when_modules_exist(self) -> None:
        required_modules = {
            "test_ticket114_contract",
            "test_ticket114_settings_controls",
            "test_ticket114_rights",
            "test_ticket114_status",
            "test_ticket114_authority_integration",
        }
        self.assertEqual(set(MODULE_CASE_IDS), required_modules)

        dotted_names = tuple(dotted_name for _, dotted_name, _ in CASE_REGISTRY)
        observables = tuple(observable for _, _, observable in CASE_REGISTRY)
        self.assertEqual(len(dotted_names), 208)
        self.assertEqual(len(set(dotted_names)), 208)
        self.assertTrue(all(observable.strip() for observable in observables))
        self.assertEqual(len(set(observables)), 208)

        for case_id, dotted_name, _ in CASE_REGISTRY:
            with self.subTest(case_id=case_id):
                self.assertRegex(
                    dotted_name,
                    r"^test_ticket114_[a-z_]+\.test_114_a[1-9]_c\d{2}_[a-z0-9_]+$",
                )
                module_name, test_name = dotted_name.split(".", 1)
                _, acceptance_id, case_number = case_id.lower().split("-")
                self.assertTrue(
                    test_name.startswith(
                        f"test_114_{acceptance_id}_{case_number}_"
                    )
                )

        actual_locators: list[str] = []
        for module_name in sorted(required_modules):
            path = Path(__file__).with_name(module_name + ".py")
            self.assertTrue(path.is_file(), str(path))
            module = importlib.import_module("tests." + module_name)
            for candidate in vars(module).values():
                if not (
                    isinstance(candidate, type)
                    and issubclass(candidate, unittest.TestCase)
                ):
                    continue
                for test_name, member in candidate.__dict__.items():
                    if test_name.startswith("test_114_") and callable(member):
                        actual_locators.append(f"{module_name}.{test_name}")

        self.assertEqual(Counter(actual_locators), Counter(dotted_names))


class Ticket114ContractTests(unittest.TestCase):
    def test_114_a1_c14_single_field_command_rejects_settings_blob_or_multi_field(self) -> None:
        settings = _settings()
        wire = _field_update_wire()
        self.assertEqual(settings.FieldUpdate.from_wire(wire).to_wire(), wire)
        for malformed in (
            {**wire, "settings": {"contact_window": "09:00-21:00"}},
            {**wire, "updates": [_field_update_wire(), _field_update_wire()]},
            {**wire, "contact_window": "09:00-21:00"},
            {**wire, "field_name": "", "new_value": "concise"},
            {**wire, "field_name": "*", "new_value": "concise"},
            {**wire, "field_name": "settings", "new_value": {"all": "off"}},
        ):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    settings.FieldUpdate.from_wire(malformed)

    def test_114_a1_c15_notification_kind_enum_is_exactly_five(self) -> None:
        settings = _settings()
        expected = (
            "new_task",
            "ordinary_stage_change",
            "care_reminder",
            "task_terminal",
            "review_summary",
        )
        self.assertEqual(tuple(settings.ORDINARY_NOTIFICATION_KINDS), expected)
        for kind in expected:
            with self.subTest(kind=kind):
                wire = _notification_wire(kind)
                self.assertEqual(settings.NotificationUpdate.from_wire(wire).to_wire(), wire)
        for old_state, new_state in (
            ("not-configured", "enabled"),
            ("not-configured", "disabled"),
            ("enabled", "disabled"),
            ("disabled", "enabled"),
        ):
            with self.subTest(old_state=old_state, new_state=new_state):
                wire = {
                    **_notification_wire("new_task"),
                    "old_state": old_state,
                    "new_state": new_state,
                }
                self.assertEqual(
                    settings.NotificationUpdate.from_wire(wire).to_wire(), wire
                )
        for malformed_state in (
            {"old_state": True},
            {"old_state": None},
            {"old_state": "unset"},
            {"new_state": False},
            {"new_state": "not-configured"},
            {"new_state": "all"},
        ):
            with self.subTest(malformed_state=malformed_state):
                with self.assertRaises(ValueError):
                    settings.NotificationUpdate.from_wire(
                        {**_notification_wire("new_task"), **malformed_state}
                    )
        for kind in ("danger_alert", "status_change", "all", "*", ""):
            with self.subTest(forbidden_kind=kind):
                with self.assertRaises(ValueError):
                    settings.NotificationUpdate.from_wire(_notification_wire(kind))

    def test_114_a2_c07_control_command_names_exactly_one_explicit_control(self) -> None:
        settings = _settings()
        wire = _owner_control_command_wire()
        self.assertEqual(settings.OwnerControlCommand.from_wire(wire).to_wire(), wire)
        for malformed_update in (
            {**_control_update_wire(), "controls": ["proactive_support", "recording"]},
            {**_control_update_wire(), "stop_new_recording": True},
            {**_control_update_wire(), "control_name": ""},
            {**_control_update_wire(), "control_name": "*"},
            {**_control_update_wire(), "control_name": "global_health_off"},
        ):
            with self.subTest(update=malformed_update):
                malformed = _owner_control_command_wire(malformed_update)
                with self.assertRaises(ValueError):
                    settings.OwnerControlCommand.from_wire(malformed)

    def test_114_a3_c12_managed_object_contract_preserves_version_source_evidence_refs(self) -> None:
        rights = _rights()
        wire = _managed_object_wire()
        managed = rights.ManagedObject.from_wire(wire)
        self.assertEqual(managed.to_wire(), wire)
        self.assertEqual(
            (managed.owner_id, managed.installation_id),
            ("owner-synthetic", "installation-synthetic"),
        )
        self.assertEqual(managed.version, 3)
        self.assertEqual(tuple(managed.source_refs), ("source:weixin-message:synthetic-1",))
        self.assertEqual(tuple(managed.evidence_refs), ("evidence-card:synthetic-1:v2",))
        for field in ("version", "source_refs", "evidence_refs"):
            with self.subTest(missing=field):
                malformed = copy.deepcopy(wire)
                malformed.pop(field)
                with self.assertRaises(ValueError):
                    rights.ManagedObject.from_wire(malformed)
        with self.assertRaises(ValueError):
            rights.ManagedObject.from_wire({**wire, "chat_memory_copy": "forbidden"})

    def test_114_a3_c13_correction_and_export_contracts_preserve_history_and_snapshot_metadata(self) -> None:
        rights = _rights()
        correction_wire = _correction_wire()
        snapshot_wire = _export_wire()
        correction = rights.CorrectionRevision.from_wire(correction_wire)
        snapshot = rights.ExportSnapshot.from_wire(snapshot_wire)
        self.assertEqual(correction.to_wire(), correction_wire)
        self.assertEqual(snapshot.to_wire(), snapshot_wire)
        self.assertEqual(correction.previous_version, 3)
        self.assertEqual(correction.revision_version, 4)
        self.assertEqual(snapshot.source_state_digest, "sha256:" + "a" * 64)
        self.assertFalse(any(hasattr(snapshot, name) for name in ("import_snapshot", "apply", "write")))
        for cls, valid in (
            (rights.CorrectionRevision, correction_wire),
            (rights.ExportSnapshot, snapshot_wire),
        ):
            with self.subTest(contract=cls.__name__):
                malformed = copy.deepcopy(valid)
                malformed["extra_authority"] = True
                with self.assertRaises(ValueError):
                    cls.from_wire(malformed)

    def test_114_a4_c09_timezone_transition_binds_committed_request_next_date_and_effective_utc(self) -> None:
        settings = _settings()
        wire = _timezone_transition_wire()
        transition = settings.TimezoneTransition.from_wire(wire)
        self.assertEqual(transition.to_wire(), wire)
        self.assertEqual(transition.requested_at_utc, "2026-03-07T23:00:00+00:00")
        self.assertEqual(transition.first_review_local_date, "2026-03-08")
        self.assertEqual(transition.effective_at_utc, "2026-03-08T05:00:00+00:00")
        for field in ("requested_at_utc", "first_review_local_date", "effective_at_utc"):
            with self.subTest(missing=field):
                malformed = dict(wire)
                malformed.pop(field)
                with self.assertRaises(ValueError):
                    settings.TimezoneTransition.from_wire(malformed)
        with self.assertRaises(ValueError):
            settings.TimezoneTransition.from_wire({**wire, "server_timezone": "UTC"})

    def test_114_a5_c12_capability_envelope_is_core_sealed_body_free_and_rejects_liveness_proxies(self) -> None:
        status = _status()
        authority = status.CapabilityFactAuthority(
            authority_id="synthetic-core-status-authority",
            signing_key=b"ticket-114-synthetic-status-key",
            producer_contracts={"health-core.entry": "entry-fact-v1"},
        )
        envelope = authority.seal(
            domain="entry",
            requiredness="core",
            state="confirmed-ok",
            generation=7,
            revision_digest="sha256:" + "e" * 64,
            transition_id="current-head-transition:synthetic-7",
            producer_id="health-core.entry",
            producer_contract_version="entry-fact-v1",
            evidence_refs=("contract-probe:entry:synthetic-1",),
            valid_until_utc="2026-08-25T00:00:00+00:00",
        )
        wire = envelope.to_wire()
        self.assertEqual(
            status.CapabilityFactEnvelope.from_wire(wire, authority=authority).to_wire(),
            wire,
        )
        self.assertTrue(
            {
                "entry", "enablement", "keys_state", "portrait_evidence", "tasks",
                "controls", "daily_review", "model_route", "delivery", "safety",
                "question_answering", "diagnostic_scope", "current_head",
            }.issubset(set(status.CORE_STATUS_DOMAINS))
        )
        self.assertTrue(
            set(status.CORE_STATUS_DOMAINS).isdisjoint(
                {"heartbeat", "process_alive", "cron", "plugin_loaded", "adapter_ok"}
            )
        )
        for forbidden in ("body", "health_text", "heartbeat_at", "process_alive", "cron_ok", "plugin_loaded"):
            with self.subTest(forbidden=forbidden):
                malformed = dict(wire)
                malformed[forbidden] = "forbidden"
                with self.assertRaises(ValueError):
                    status.CapabilityFactEnvelope.from_wire(malformed, authority=authority)
        for domain in ("heartbeat", "process_alive", "cron", "plugin_loaded", "*"):
            with self.subTest(domain=domain):
                with self.assertRaises(ValueError):
                    authority.seal(
                        domain=domain,
                        requiredness="core",
                        state="confirmed-ok",
                        generation=7,
                        revision_digest="sha256:" + "e" * 64,
                        transition_id="current-head-transition:synthetic-7",
                        producer_id="health-core.entry",
                        producer_contract_version="entry-fact-v1",
                        evidence_refs=("contract-probe:entry:synthetic-1",),
                        valid_until_utc="2026-08-25T00:00:00+00:00",
                    )

    def test_114_a6_c09_authority_command_requires_permission_context_generation_and_fence(self) -> None:
        settings = _settings()
        context_wire = _context_wire()
        context = settings.OwnerCommandContext.from_wire(context_wire)
        self.assertEqual(context.to_wire(), context_wire)
        self.assertEqual(
            (
                context.owner_id,
                context.installation_id,
                context.generation,
                context.writer_fence,
            ),
            (
                "owner-synthetic",
                "installation-synthetic",
                7,
                "writer-fence:7:synthetic",
            ),
        )
        self.assertFalse(
            any(
                hasattr(context, field)
                for field in ("owner_epoch_generation", "settings_generation")
            )
        )
        command_wire = _owner_control_command_wire()
        self.assertEqual(settings.OwnerControlCommand.from_wire(command_wire).to_wire(), command_wire)
        for field in (
            "command_id", "causal_id", "actor_kind", "owner_id", "installation_id",
            "permission", "context_ref", "generation", "writer_fence",
        ):
            with self.subTest(missing=field):
                malformed = copy.deepcopy(command_wire)
                malformed["context"].pop(field)
                with self.assertRaises(ValueError):
                    settings.OwnerControlCommand.from_wire(malformed)
        for field in ("permission", "context_ref", "writer_fence"):
            with self.subTest(blank=field):
                malformed = copy.deepcopy(command_wire)
                malformed["context"][field] = ""
                with self.assertRaises(ValueError):
                    settings.OwnerControlCommand.from_wire(malformed)
        for forbidden_epoch in ("owner_epoch_generation", "settings_generation"):
            with self.subTest(forbidden_epoch=forbidden_epoch):
                malformed = copy.deepcopy(command_wire)
                malformed["context"][forbidden_epoch] = 7
                with self.assertRaises(ValueError):
                    settings.OwnerControlCommand.from_wire(malformed)

    def test_114_a7_c09_reconsent_contract_binds_route_config_generation_and_disclosure(self) -> None:
        settings = _settings()
        wire = _consent_wire()
        renewal = settings.ConsentRenewal.from_wire(wire)
        self.assertEqual(renewal.to_wire(), wire)
        self.assertEqual(renewal.route_id, "partner-first-hop")
        self.assertEqual(renewal.configuration_generation, 11)
        self.assertEqual(renewal.disclosure_version, "health-recipient-disclosure-v3")
        for field in (
            "route_id", "first_hop_recipient", "configuration_generation",
            "disclosure_version", "disclosure_digest",
        ):
            with self.subTest(missing=field):
                malformed = copy.deepcopy(wire)
                malformed.pop(field)
                with self.assertRaises(ValueError):
                    settings.ConsentRenewal.from_wire(malformed)
        for field in ("route_id", "first_hop_recipient", "disclosure_version"):
            with self.subTest(wildcard=field):
                malformed = copy.deepcopy(wire)
                malformed[field] = "*"
                with self.assertRaises(ValueError):
                    settings.ConsentRenewal.from_wire(malformed)

    def test_114_a8_c12_execution_scope_approval_contract_binds_all_required_fields(self) -> None:
        settings = _settings()
        wire = _approval_wire()
        approval = settings.ExecutionScopeApproval.from_wire(wire)
        self.assertEqual(approval.to_wire(), wire)
        self.assertEqual(
            (approval.owner_id, approval.installation_id, approval.approval_version),
            ("owner-synthetic", "installation-synthetic", 2),
        )
        self.assertFalse(
            any(
                hasattr(approval, field)
                for field in ("generation", "owner_epoch_generation")
            )
        )
        required = tuple(wire)
        for field in required:
            with self.subTest(missing=field):
                malformed = copy.deepcopy(wire)
                malformed.pop(field)
                with self.assertRaises(ValueError):
                    settings.ExecutionScopeApproval.from_wire(malformed)
        with self.assertRaises(ValueError):
            settings.ExecutionScopeApproval.from_wire({**wire, "implicit_scope": True})
        for forbidden_epoch in ("generation", "owner_epoch_generation"):
            with self.subTest(forbidden_epoch=forbidden_epoch):
                with self.assertRaises(ValueError):
                    settings.ExecutionScopeApproval.from_wire(
                        {**wire, forbidden_epoch: 7}
                    )
        for field in ("purpose", "assignee", "first_hop_recipient", "route_id", "disclosure_version"):
            for forbidden in ("", "*"):
                with self.subTest(field=field, forbidden=forbidden):
                    malformed = copy.deepcopy(wire)
                    malformed[field] = forbidden
                    with self.assertRaises(ValueError):
                        settings.ExecutionScopeApproval.from_wire(malformed)
        for field in ("allowed_data_categories", "allowed_data_refs"):
            with self.subTest(field=field):
                malformed = copy.deepcopy(wire)
                malformed[field] = ["*"]
                with self.assertRaises(ValueError):
                    settings.ExecutionScopeApproval.from_wire(malformed)

    def test_114_a8_c13_only_current_owner_can_author_and_consumers_cannot_self_approve(self) -> None:
        settings = _settings()
        update = _control_update_wire(
            "execution_scope_approval", "grant", "execution-approval:synthetic-1"
        )
        wire = _owner_control_command_wire(update, _approval_wire())
        self.assertEqual(settings.OwnerControlCommand.from_wire(wire).to_wire(), wire)
        for actor_kind, permission in (
            ("task_engine", "execution.consume"),
            ("skill", "health_settings.write"),
            ("adapter", "health_settings.write"),
        ):
            with self.subTest(actor_kind=actor_kind):
                malformed = copy.deepcopy(wire)
                malformed["context"]["actor_kind"] = actor_kind
                malformed["context"]["permission"] = permission
                with self.assertRaises(ValueError):
                    settings.OwnerControlCommand.from_wire(malformed)
        approval = settings.ExecutionScopeApproval.from_wire(_approval_wire())
        self.assertFalse(any(hasattr(approval, name) for name in ("self_approve", "grant", "revise", "revoke")))

    def test_114_a9_c16_support_contact_contract_requires_identifiable_identity_and_all_status_fields(self) -> None:
        settings = _settings()
        wire = _support_contact_wire()
        contact = settings.SupportContactSettings.from_wire(wire)
        self.assertEqual(contact.to_wire(), wire)
        self.assertEqual(
            (contact.owner_id, contact.installation_id, contact.version),
            ("owner-synthetic", "installation-synthetic", 3),
        )
        self.assertFalse(
            any(
                hasattr(contact, field)
                for field in ("generation", "owner_epoch_generation")
            )
        )
        for field in (
            "identity_label", "method_kind", "method_value", "purpose",
            "minimum_alert_fields", "route_id", "route_generation",
            "dedicated_paused", "alert_authority_status", "alert_approval_id",
            "alert_authority_binding", "correction_authority_status",
            "correction_authority_id", "correction_authority_binding",
            "max_corrections_per_alert",
        ):
            with self.subTest(missing=field):
                malformed = copy.deepcopy(wire)
                malformed.pop(field)
                with self.assertRaises(ValueError):
                    settings.SupportContactSettings.from_wire(malformed)
        for field in ("identity_label", "method_value", "purpose", "route_id"):
            with self.subTest(blank=field):
                malformed = copy.deepcopy(wire)
                malformed[field] = ""
                with self.assertRaises(ValueError):
                    settings.SupportContactSettings.from_wire(malformed)
        for forbidden_epoch in ("generation", "owner_epoch_generation"):
            with self.subTest(forbidden_epoch=forbidden_epoch):
                with self.assertRaises(ValueError):
                    settings.SupportContactSettings.from_wire(
                        {**wire, forbidden_epoch: 7}
                    )

    def test_114_a9_c17_replace_or_method_change_invalidates_old_authority_until_exact_approval(self) -> None:
        settings = _settings()
        current = _support_contact_wire()
        old_binding = current["alert_authority_binding"]
        for changed_field, changed_value in (
            ("contact_id", "support-contact:synthetic-2"),
            ("method_value", "wxid_synthetic_contact_2"),
        ):
            with self.subTest(changed_field=changed_field):
                stale = copy.deepcopy(current)
                stale[changed_field] = changed_value
                self.assertNotEqual(_contact_binding(stale), old_binding)
                with self.assertRaises(ValueError):
                    settings.SupportContactSettings.from_wire(stale)
        invalidated = _support_contact_wire(approved=False)
        invalidated["contact_id"] = "support-contact:synthetic-2"
        invalidated["method_value"] = "wxid_synthetic_contact_2"
        self.assertEqual(
            settings.SupportContactSettings.from_wire(invalidated).to_wire(),
            invalidated,
        )
        reapproved = copy.deepcopy(invalidated)
        binding = _contact_binding(reapproved)
        reapproved.update(
            {
                "alert_authority_status": "approved",
                "alert_approval_id": "alert-approval:synthetic-2",
                "alert_authority_binding": binding,
                "correction_authority_status": "approved",
                "correction_authority_id": "correction-authority:synthetic-2",
                "correction_authority_binding": binding,
            }
        )
        self.assertEqual(
            settings.SupportContactSettings.from_wire(reapproved).to_wire(),
            reapproved,
        )


if __name__ == "__main__":
    unittest.main()

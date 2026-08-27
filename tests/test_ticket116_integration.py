"""Verifier-owned RED gates for Ticket 116 public product behavior.

The tests deliberately use only the Plugin/Core public command, controlled
effect, managed-read, status, and replaceable adapter seams as acceptance
oracles.  Test setup may assemble the existing synthetic initialized product,
but no assertion reads SQLite, private collections, or private state helpers.

The original pre-implementation gate used one shared RED and dependency SKIPs.
The implementation-review candidate keeps the same twelve methods while adding
only public-seam equivalence classes that reproduce gaps in existing A1/A3/A4,
A5, and A9.  Completion always requires 12 PASS and zero skips.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone

from partner_health_steward import HealthCore, HealthPlugin
from partner_health_steward.admission import RawWeixinMessage
from partner_health_steward.authority import (
    AuthorityValidationError,
    EffectIntent,
)
from partner_health_steward.contract import ProtocolViolation, Response
from partner_health_steward.current_head import FailureMode
from partner_health_steward.delivery import OwnerDeliveryTransportResult
from partner_health_steward.initialization import stable_digest
from partner_health_steward.knowledge import (
    KnowledgePublicationInput,
    KnowledgePublisher,
    KnowledgeRelease,
)
from partner_health_steward.model_contract import (
    CapabilityProfile,
    FirstHopRoute,
    ModelTransportResult,
    StrictHealthLLM,
    StrictModelRequest,
)
from partner_health_steward.probe import ProbeState
from tests import test_ticket115_integration as ticket115_integration
from tests.test_ticket112_seven_skill_daily_turn import CountingBody


_PEER = "plugin"
_OWNER_ID = "owner-A"
_INSTALLATION_ID = "partner-installation"
_MODEL_NAME = "synthetic-ticket116-model"
_MODEL_SCHEMA_NAME = "synthetic-ticket116-diagnosis-v1"
_MODEL_SCHEMA_DIGEST = "sha256:" + ("d" * 64)
_RELEASE_DIGEST = "sha256:" + ("8" * 64)
_SCOPE_ID = "synthetic-bmi-scope"
_MINIMUM_TEMPLATE_REF = "minimum-help-template:synthetic-v1"
_DANGER_TEMPLATE_REF = "danger-owner-template:synthetic-v1"
_UNKNOWN_TEMPLATE_REF = "danger-unknown-template:synthetic-v1"
_OUT_OF_SCOPE_TEMPLATE_REF = "out-of-scope-template:synthetic-v1"


def _declared_bundle_digest(bundle: Mapping[str, object]) -> str:
    """Build a valid synthetic content address, excluding its declaration."""

    payload = {key: value for key, value in bundle.items() if key != "bundle_hash"}
    return stable_digest(payload)


def _asset_bundle_hash(assets: Mapping[str, object], bundle_name: str) -> str:
    """Read the declared address from the exact synthetic asset being used."""

    bundle = assets.get(bundle_name)
    if not isinstance(bundle, Mapping):
        raise AssertionError(f"synthetic assets have no {bundle_name}")
    declared = bundle.get("bundle_hash")
    if not isinstance(declared, str):
        raise AssertionError(f"{bundle_name} has no declared bundle hash")
    return declared


class _RecordingModelAdapter:
    """External model double; all Core authority behavior remains real."""

    def __init__(self, result: ModelTransportResult) -> None:
        self._result = result
        self.calls = 0

    def execute(self, payload: object) -> ModelTransportResult:
        if not isinstance(payload, Mapping):
            raise AssertionError("strict model adapter received a non-wire payload")
        self.calls += 1
        return self._result


class _ContactAdapter:
    """External contact transport double with a complete delivery result."""

    def __init__(
        self,
        *,
        raises_after_accepting: bool = False,
        status: str = "accepted",
    ) -> None:
        self.raises_after_accepting = raises_after_accepting
        self.status = status
        self.calls = 0
        self.wires: list[dict[str, object]] = []

    def send(self, intent: object) -> dict[str, object]:
        if type(intent) is not dict:
            raise AssertionError("contact adapter received a non-wire intent")
        self.calls += 1
        self.wires.append(dict(intent))
        if self.raises_after_accepting:
            raise TimeoutError("synthetic contact result ownership is unknown")
        return OwnerDeliveryTransportResult(
            status=self.status,
            result_ref=f"contact-result:{self.calls}",
            evidence_ref=f"contact-evidence:{self.calls}",
        ).to_wire()


class _AcceptanceEvidenceProvider:
    """Ticket 119 evidence double; Core has read-only access by opaque ref."""

    def __init__(self, records: Mapping[str, Mapping[str, object]]) -> None:
        self._records = {key: dict(value) for key, value in records.items()}

    def read(self, receipt_ref: str) -> dict[str, object] | None:
        record = self._records.get(receipt_ref)
        return None if record is None else dict(record)


class Ticket116VerificationTests(unittest.TestCase):
    """Twelve frozen public-seam gates, one per independent product break."""

    maxDiff = None

    def setUp(self) -> None:
        self.harness = ticket115_integration.Ticket115IntegrationTests(
            "test_plugin_ticket115_seam_exposes_only_bounded_wire_views"
        )
        self.harness.setUp()
        self.base = self.harness.base
        self._command_index = 0
        self._configured_safety_bundle_hash: str | None = None
        self._configured_scope_bundle_hash: str | None = None
        self.route = FirstHopRoute(
            route_id="jojo-responses-v1",
            provider="synthetic-provider",
            canonical_base_url="https://model.example/v1",
            api_mode="responses",
            requested_model=_MODEL_NAME,
            configuration_generation=1,
            owner_consent_fingerprint="sha256:" + ("a" * 64),
        )
        self.profile = CapabilityProfile(
            profile_id="synthetic-ticket116-profile",
            profile_version="1.0.0-test",
            synthetic=True,
            route_id=self.route.route_id,
            provider=self.route.provider,
            canonical_base_url=self.route.canonical_base_url,
            api_mode=self.route.api_mode,
            requested_model=self.route.requested_model,
            allowed_actual_models=(_MODEL_NAME,),
            configuration_generation=1,
            input_measurement_method="synthetic-exact-upper-bound-v1",
            fixed_wrapper_tokens=64,
            output_reservation_tokens=256,
            common_context_lower_bound_tokens=4096,
            evidence_refs=("synthetic-profile-review:ticket116",),
            invalidation_conditions=("route-or-schema-drift",),
        )
        self.llm = StrictHealthLLM(
            self.route,
            self.profile,
            strict_schema_name=_MODEL_SCHEMA_NAME,
            strict_schema_digest=_MODEL_SCHEMA_DIGEST,
        )
        publication = KnowledgePublicationInput(
            topic_id="synthetic-ticket116-bmi",
            governance_schedule_id="synthetic-ticket116-fixed-v1",
            source_id="synthetic-ticket116-source",
            source_version="1.0.0-test",
            rights_status="approved",
            chinese_status="reviewed-chinese",
            applicability=("synthetic-ticket116-bmi",),
            professional_review_status="approved",
            professional_review_ref="synthetic-review:ticket116",
            content="synthetic non-medical BMI verification knowledge",
            published_at="2026-08-24T00:00:00+00:00",
            expires_at="2026-08-25T00:00:00+00:00",
        )
        knowledge_release = KnowledgePublisher().publish(
            publication,
            release_version="1.0.0-test",
        )
        if type(knowledge_release) is not KnowledgeRelease:
            raise AssertionError("synthetic Ticket 116 knowledge did not publish")
        self.knowledge_release = knowledge_release
        self.knowledge_now = datetime(2026, 8, 24, 3, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.harness.tearDown()

    def _reset_harness(self) -> None:
        """Give one equivalence class an independent real authority stack."""

        self.harness.tearDown()
        self.setUp()

    @property
    def plugin(self) -> HealthPlugin:
        return self.base.plugin

    @property
    def core(self) -> HealthCore:
        return self.base.core

    @property
    def safety_bundle_hash(self) -> str:
        if self._configured_safety_bundle_hash is None:
            raise AssertionError("no safety rule bundle is currently configured")
        return self._configured_safety_bundle_hash

    @property
    def scope_bundle_hash(self) -> str:
        if self._configured_scope_bundle_hash is None:
            raise AssertionError("no diagnostic scope bundle is currently configured")
        return self._configured_scope_bundle_hash

    def _synthetic_assets(
        self,
        *,
        minimum_help_current: bool = True,
        minimum_help_rights_current: bool | None = None,
        minimum_help_review_current: bool | None = None,
        minimum_help_parse_current: bool | None = None,
        safety_rules_current: bool = True,
        diagnostic_prerequisites_current: bool = True,
        scope_state: str = "staged",
    ) -> dict[str, object]:
        """Literal non-medical assets; none of the expected values is derived."""

        rights_current = (
            minimum_help_current
            if minimum_help_rights_current is None
            else minimum_help_rights_current
        )
        review_current = (
            minimum_help_current
            if minimum_help_review_current is None
            else minimum_help_review_current
        )
        parse_current = (
            minimum_help_current
            if minimum_help_parse_current is None
            else minimum_help_parse_current
        )
        minimum_help_bundle: dict[str, object] = {
            "bundle_id": "synthetic-minimum-help",
            "version": "1.0.0-test",
            "language": "zh-CN",
            "content_rights_status": (
                "approved-synthetic" if rights_current else "unknown"
            ),
            "review_status": (
                "approved-synthetic" if review_current else "unknown"
            ),
            "parse_status": "valid" if parse_current else "unknown",
            "templates": {
                "minimum_help": {
                    "template_ref": _MINIMUM_TEMPLATE_REF,
                    "text": "[合成测试] 固定最低求助模板",
                },
                "danger_owner": {
                    "template_ref": _DANGER_TEMPLATE_REF,
                    "text": "[合成测试] 固定危险主人提示",
                },
                "danger_unknown": {
                    "template_ref": _UNKNOWN_TEMPLATE_REF,
                    "text": "[合成测试] 固定危险未明提示",
                },
                "out_of_scope": {
                    "template_ref": _OUT_OF_SCOPE_TEMPLATE_REF,
                    "text": "[合成测试] 固定范围外提示",
                },
            },
        }
        minimum_help_bundle["bundle_hash"] = _declared_bundle_digest(
            minimum_help_bundle
        )
        assets: dict[str, object] = {
            "asset_contract": "safety-diagnostic-assets-v1",
            "synthetic": True,
            "production_approval": False,
            "release_digest": _RELEASE_DIGEST,
            "minimum_help_bundle": minimum_help_bundle,
            "safety_rule_bundle": {
                "bundle_id": "synthetic-safety-rules",
                "version": "1.0.0-test",
                "synthetic": True,
                "rights_status": (
                    "approved-synthetic" if safety_rules_current else "unknown"
                ),
                "review_status": (
                    "approved-synthetic" if safety_rules_current else "unknown"
                ),
                "rules": [
                    {
                        "input": "SYNTHETIC:SAFETY_UNAVAILABLE",
                        "branch": "safety-capability-unavailable",
                    },
                    {
                        "input": "SYNTHETIC:DANGER_CONFIRMED",
                        "branch": "danger-escalation",
                    },
                    {
                        "input": "SYNTHETIC:DANGER_UNKNOWN",
                        "branch": "danger-unknown",
                    },
                    {
                        "input": "SYNTHETIC:OUT_OF_SCOPE",
                        "branch": "out-of-scope",
                    },
                    {
                        "input": "SYNTHETIC:IN_SCOPE",
                        "branch": "in-scope",
                    },
                ],
            },
            "diagnostic_scope_bundle": {
                "scope_id": _SCOPE_ID,
                "version": "1.0.0-test",
                "release_digest": _RELEASE_DIGEST,
                "synthetic": True,
                "medical_use": False,
                "persistent_state": scope_state,
                "activation_basis": "synthetic-test-fixture-only",
                "prerequisites": {
                    "content_rights": diagnostic_prerequisites_current,
                    "frozen_chinese_bundle": diagnostic_prerequisites_current,
                    "professional_review": diagnostic_prerequisites_current,
                    "implementation_compatibility": diagnostic_prerequisites_current,
                    "safety_review": diagnostic_prerequisites_current,
                },
                "population": {
                    "minimum_age_years": 18,
                    "pregnancy_allowed": False,
                },
                "measurements": {
                    "height_unit": "m",
                    "weight_unit": "kg",
                    "reliability_required": True,
                    "maximum_age_seconds": 86400,
                },
                "formula": {
                    "formula_id": "synthetic-bmi-formula-v1",
                    "expression": "weight_kg / height_m^2",
                    "result_unit": "kg/m^2",
                    "comparison_uses_unrounded_value": True,
                    "display_decimal_places": 1,
                },
                "thresholds": [
                    {"label": "synthetic-lower", "minimum_bmi": "0"},
                    {"label": "synthetic-upper", "minimum_bmi": "25.005"},
                ],
            },
        }
        for name in ("safety_rule_bundle", "diagnostic_scope_bundle"):
            bundle = assets[name]
            assert isinstance(bundle, dict)
            bundle["bundle_hash"] = _declared_bundle_digest(bundle)
        return assets

    def _restart_with_assets(
        self,
        assets: dict[str, object],
        *,
        root_gate: bool = False,
        acceptance_evidence_provider: object | None = None,
    ) -> None:
        """Expand downstream gates only after the shared asset seam exists."""

        safety_bundle_hash = _asset_bundle_hash(assets, "safety_rule_bundle")
        scope_bundle_hash = _asset_bundle_hash(assets, "diagnostic_scope_bundle")
        self.assertTrue(self.base.core.close().complete)
        acceptance_kwargs = (
            {}
            if acceptance_evidence_provider is None
            else {"acceptance_evidence_provider": acceptance_evidence_provider}
        )
        try:
            core = HealthCore(
                self.base.store,
                self.base.head,
                execution_capability_vault=self.harness.execution_vault,
                writer_fence_vault=self.base.writer_vault,
                admission_policy=self.base.policy,
                health_init_verifier=self.base.init_attestor,
                health_init_asset=self.base.init_asset,
                daily_skill_verifier=self.base.daily_attestor,
                daily_skill_bundle=self.base.daily_bundle,
                owner_settings_clock=lambda: self.base.owner_clock_value,
                route_configuration_provider=lambda: self.harness.route_fact,
                status_fact_authority=self.harness.status_authority,
                business_status_clock=lambda: self.base.status_clock_value,
                model_authority_digest=self.llm.model_authority_digest,
                knowledge_releases=(self.knowledge_release,),
                knowledge_valid_at=self.knowledge_now.isoformat(),
                knowledge_clock=lambda: self.knowledge_now,
                safety_diagnostic_assets=assets,
                **acceptance_kwargs,
            )
        except TypeError as exc:
            if (
                acceptance_evidence_provider is not None
                and "acceptance_evidence_provider" in str(exc)
            ):
                raise AssertionError(
                    "V116-04 prerequisite: read-only acceptance evidence provider "
                    "is not implemented"
                ) from exc
            if "safety_diagnostic_assets" not in str(exc):
                raise
            message = (
                "V116-01 prerequisite: managed safety/diagnostic asset injection "
                "is not implemented"
            )
            if root_gate:
                raise AssertionError(message) from exc
            self.skipTest(message)
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
        self._configured_safety_bundle_hash = safety_bundle_hash
        self._configured_scope_bundle_hash = scope_bundle_hash

    def _health_context(
        self,
        action: str,
        *,
        generation: int | None = None,
        suffix: str = "",
        source: str | None = None,
    ) -> dict[str, object]:
        self._command_index += 1
        return {
            "source": source
            or (
                "safety_runtime" if action.startswith("safety.") else "diagnostic_runtime"
            ),
            "causal_id": (
                f"ticket116-command:{self._testMethodName}:{self._command_index}:{suffix}"
            ),
            "generation": (
                self.base.head.read().head.generation
                if generation is None
                else generation
            ),
            "scope": [action.replace(".", ":")],
        }

    def _health(
        self,
        action: str,
        payload: dict[str, object],
        *,
        generation: int | None = None,
        suffix: str = "",
        source: str | None = None,
    ) -> dict[str, object]:
        try:
            return self.plugin.health_operation(
                action,
                payload,
                context=self._health_context(
                    action,
                    generation=generation,
                    suffix=suffix,
                    source=source,
                ),
                peer_id=_PEER,
            )
        except (ProtocolViolation, AuthorityValidationError) as exc:
            raise AssertionError(
                f"Ticket 116 public health action is unavailable: {action}: {exc}"
            ) from exc

    def _controlled(
        self,
        action: str,
        payload: dict[str, object],
        *,
        grant: object | None = None,
        transport: object | None = None,
    ) -> dict[str, object]:
        try:
            return self.plugin.controlled_effect(
                action,
                payload,
                grant=grant,  # type: ignore[arg-type]
                transport=transport,  # type: ignore[arg-type]
                peer_id=_PEER,
            )
        except (ProtocolViolation, AuthorityValidationError) as exc:
            raise AssertionError(
                f"Ticket 116 public controlled effect is unavailable: {action}: {exc}"
            ) from exc

    def _managed_read(self) -> dict[str, object]:
        reader = getattr(self.plugin, "managed_safety_diagnosis_read", None)
        if not callable(reader):
            raise AssertionError(
                "Ticket 116 public managed safety/diagnosis read is not implemented"
            )
        try:
            result = reader(peer_id=_PEER)
        except (ProtocolViolation, AuthorityValidationError) as exc:
            raise AssertionError(
                f"Ticket 116 public managed safety/diagnosis read is unavailable: {exc}"
            ) from exc
        if type(result) is not dict:
            raise AssertionError("Ticket 116 managed read did not return a wire mapping")
        return result

    def _message(
        self,
        body: object,
        *,
        suffix: str,
        generation: int | None = None,
        channel: str = "weixin",
        sender_id: str | None = None,
        conversation_id: str | None = None,
        chat_type: str = "private",
        entrypoint: str = "health_weixin",
    ) -> RawWeixinMessage:
        return RawWeixinMessage(
            causal_id=f"ticket116-source:{self._testMethodName}:{suffix}",
            generation=(
                self.base.head.read().head.generation
                if generation is None
                else generation
            ),
            channel=channel,
            partner_id=self.base.policy.partner_id,
            sender_id=(
                self.base.policy.owner_sender_id
                if sender_id is None
                else sender_id
            ),
            conversation_id=(
                self.base.policy.conversation_id
                if conversation_id is None
                else conversation_id
            ),
            chat_type=chat_type,
            entrypoint=entrypoint,
            requested_capability="health-steward",
            message_id=f"wx-ticket116:{self._testMethodName}:{suffix}",
            protocol_timestamp="2026-08-24T11:30:00+08:00",
            received_at="2026-08-24T11:30:01+08:00",
            native_cursor=f"cursor-ticket116:{self._testMethodName}:{suffix}",
            body=body,
        )

    @staticmethod
    def _meta_wire(response: Response) -> dict[str, object]:
        meta = response.meta
        if type(meta) is dict:
            return dict(meta)
        to_wire = getattr(meta, "to_wire", None)
        if callable(to_wire):
            value = to_wire()
            if type(value) is dict:
                return value
        raise AssertionError("Ticket 116 owner result is missing public wire metadata")

    def _configure_synthetic_contact(self) -> None:
        """Create the fixture through Ticket 114's public owner command path."""

        contact = self.base._support_contact(version=1)
        command = self.base._support_contact_command(
            "configure",
            suffix="ticket116-configure-contact",
            contact=contact,
        )
        self.base._commit_settings_command(
            command,
            suffix="ticket116-configure-contact",
        )

    def _change_synthetic_contact_method(
        self,
        *,
        route_generation: int | None = None,
    ) -> None:
        current = self.plugin.owner_settings_state(peer_id=_PEER).support_contact
        self.assertIsNotNone(current)
        assert current is not None
        changed = replace(
            current,
            version=current.version + 1,
            method_kind="telephone_e164",
            method_value="+8613800138000",
            route_generation=(
                current.route_generation
                if route_generation is None
                else route_generation
            ),
            alert_authority_status="invalidated",
            alert_approval_id=None,
            alert_authority_binding=None,
            correction_authority_status="invalidated",
            correction_authority_id=None,
            correction_authority_binding=None,
        )
        command = self.base._support_contact_command(
            "change_method",
            suffix="ticket116-change-contact-method",
            contact=changed,
            expected_contact_version=current.version,
            expected_route_id=current.route_id,
            expected_route_generation=current.route_generation,
        )
        self.base._commit_settings_command(
            command,
            suffix="ticket116-change-contact-method",
        )

    def _apply_contact_control(self, operation: str) -> None:
        current = self.plugin.owner_settings_state(peer_id=_PEER).support_contact
        self.assertIsNotNone(current)
        assert current is not None
        command = self.base._support_contact_command(
            operation,
            suffix=f"ticket116-{operation}",
            expected_contact_version=current.version,
            expected_route_id=current.route_id,
            expected_route_generation=current.route_generation,
        )
        self.base._commit_settings_command(
            command,
            suffix=f"ticket116-{operation}",
        )

    def _grant_contact_authority(self, *, correction: bool = False) -> None:
        operation = (
            "grant_correction_authority" if correction else "grant_alert_authority"
        )
        authority_id = (
            "correction-authority:ticket116" if correction else "alert-approval:ticket116"
        )
        current = self.plugin.owner_settings_state(peer_id=_PEER)
        contact = current.support_contact
        if contact is None:
            raise AssertionError("initialized synthetic owner has no support contact")
        command = self.base._support_contact_command(
            operation,
            suffix=f"ticket116-{operation}",
            authority_id=authority_id,
            expected_contact_version=contact.version,
            expected_route_id=contact.route_id,
            expected_route_generation=contact.route_generation,
        )
        self.base._commit_settings_command(
            command,
            suffix=f"ticket116-{operation}",
        )

    def _stop_recording(self) -> None:
        request = self.base._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=f":{self._testMethodName}:stop-recording",
        )
        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

    def _resume_recording(self) -> None:
        request = self.base._owner_request(
            correction=False,
            control_name="recording",
            control_operation="resume",
            command_suffix=f":{self._testMethodName}:resume-recording",
        )
        self.assertEqual(self.base._prepare(request).status, "accepted")
        self.assertEqual(self.base._commit(request).status, "accepted")
        self.assertEqual(self.base._finalize(request).status, "accepted")

    def _diagnosis_prepare_payload(
        self,
        *,
        source_suffix: str,
        question_ref: str = "question:synthetic-bmi",
        event_ref: str = "event:synthetic-measurement",
        applicable_period: str = "2026-08-24",
        evidence_revision_digest: str | None = None,
        scope_bundle_hash: str | None = None,
        run_receipt_ref: str | None = None,
    ) -> dict[str, object]:
        evidence = self.base.baseline_card
        return {
            "source_causal_id": f"ticket116-diagnostic-source:{source_suffix}",
            "question_ref": question_ref,
            "event_ref": event_ref,
            "applicable_period": applicable_period,
            "scope_id": _SCOPE_ID,
            "scope_bundle_hash": (
                self.scope_bundle_hash
                if scope_bundle_hash is None
                else scope_bundle_hash
            ),
            "minimum_evidence": {
                "evidence_ref": evidence.evidence_id,
                "evidence_revision_digest": (
                    evidence.revision_digest
                    if evidence_revision_digest is None
                    else evidence_revision_digest
                ),
                "height_m": "2.0",
                "weight_kg": "100.018",
                "measured_at_utc": "2026-08-24T03:00:00+00:00",
                "reliable": True,
                "age_years": 30,
                "pregnancy_status": "not-pregnant",
            },
            "run_receipt_ref": run_receipt_ref,
        }

    def _diagnostic_candidate(
        self,
        *,
        classification: str = "synthetic-lower",
        question_ref: str = "question:synthetic-bmi",
        event_ref: str = "event:synthetic-measurement",
        applicable_period: str = "2026-08-24",
    ) -> dict[str, object]:
        evidence = self.base.baseline_card
        return {
            "schema_version": "synthetic-diagnosis-candidate-v1",
            "question_ref": question_ref,
            "event_ref": event_ref,
            "applicable_period": applicable_period,
            "scope_id": _SCOPE_ID,
            "scope_bundle_hash": self.scope_bundle_hash,
            "judgment": {
                "kind": "synthetic-bmi-classification",
                "classification": classification,
                "bmi_unrounded": "25.0045",
                "bmi_display": "25.0",
                "unit": "kg/m^2",
            },
            "support_refs": [evidence.evidence_id],
            "opposition_refs": ["synthetic-opposition:none-observed"],
            "missing_refs": [],
            "uncertainties": ["synthetic-measurement-only"],
            "urgency": "routine",
            "allowed_next_steps": ["synthetic-professional-review"],
            "evidence_refs": [evidence.evidence_id],
            "knowledge_refs": [self.knowledge_release.release_id],
            "safety_bundle_ref": "synthetic-safety-rules@1.0.0-test",
            "template_bundle_ref": _MINIMUM_TEMPLATE_REF,
            "model_capability_ref": "synthetic-ticket116-profile@1.0.0-test",
        }

    def _completed_model_result(
        self,
        *,
        classification: str = "synthetic-lower",
        question_ref: str = "question:synthetic-bmi",
        event_ref: str = "event:synthetic-measurement",
        applicable_period: str = "2026-08-24",
        structured_output: Mapping[str, object] | None = None,
    ) -> ModelTransportResult:
        return ModelTransportResult(
            response_id=f"synthetic-response:{self._testMethodName}",
            requested_model=_MODEL_NAME,
            actual_model=_MODEL_NAME,
            status="completed",
            incomplete_reason=None,
            failure_reason=None,
            usage_input_tokens=128,
            usage_output_tokens=96,
            fallback_observed=False,
            truncated=False,
            terminal_proven=True,
            structured_output=(
                self._diagnostic_candidate(
                    classification=classification,
                    question_ref=question_ref,
                    event_ref=event_ref,
                    applicable_period=applicable_period,
                )
                if structured_output is None
                else structured_output
            ),
        )

    def _noncompleted_model_result(self, status: str) -> ModelTransportResult:
        return ModelTransportResult(
            response_id=f"synthetic-response:{self._testMethodName}:{status}",
            requested_model=_MODEL_NAME,
            actual_model=_MODEL_NAME,
            status=status,
            incomplete_reason=("synthetic-incomplete" if status == "incomplete" else None),
            failure_reason=("synthetic-failed" if status == "failed" else None),
            usage_input_tokens=128,
            usage_output_tokens=0,
            fallback_observed=False,
            truncated=(status == "incomplete"),
            terminal_proven=(status != "unknown"),
            structured_output=None,
        )

    def _prepare_and_execute_model(
        self,
        *,
        source_suffix: str,
        classification: str = "synthetic-lower",
        question_ref: str = "question:synthetic-bmi",
        event_ref: str = "event:synthetic-measurement",
        applicable_period: str = "2026-08-24",
        run_receipt_ref: str | None = None,
        source: str | None = None,
        model_result: ModelTransportResult | None = None,
    ) -> tuple[str, _RecordingModelAdapter]:
        prepare_payload = self._diagnosis_prepare_payload(
            source_suffix=source_suffix,
            question_ref=question_ref,
            event_ref=event_ref,
            applicable_period=applicable_period,
            run_receipt_ref=run_receipt_ref,
        )
        prepared = self._health(
            "diagnosis.prepare",
            prepare_payload,
            suffix=source_suffix,
            source=source,
        )
        self.assertEqual(prepared.get("status"), "model-ready", prepared)
        intent = EffectIntent.from_wire_metadata(prepared.get("model_intent"))
        request = StrictModelRequest.from_wire(prepared.get("request"))
        self.assertEqual(request.route, self.route)
        self.assertEqual(request.capability_profile, self.profile)
        self.assertEqual(request.strict_schema_name, _MODEL_SCHEMA_NAME)
        self.assertEqual(request.strict_schema_digest, _MODEL_SCHEMA_DIGEST)
        grant = self.plugin.claim_effect_execution(intent)
        self.assertIsNotNone(grant)
        adapter = _RecordingModelAdapter(
            self._completed_model_result(
                classification=classification,
                question_ref=question_ref,
                event_ref=event_ref,
                applicable_period=applicable_period,
            )
            if model_result is None
            else model_result
        )
        outcome = self.plugin.execute_strict_health_model(
            self.llm,
            request,
            prepare_payload["source_causal_id"],  # type: ignore[arg-type]
            grant,
            adapter,
        )
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(outcome.model_effect, adapter._result.status)
        return intent.effect_id, adapter

    def _activate_synthetic_scope_through_ticket119(
        self,
    ) -> dict[str, object]:
        """Establish synthetic active only through the frozen public workflow."""

        run_ref = "acceptance-run-receipt:ticket116-active-fixture"
        acceptance_ref = "owner-acceptance-receipt:ticket116-active-fixture"
        staged_assets = self._synthetic_assets(scope_state="staged")
        scope_bundle_hash = _asset_bundle_hash(
            staged_assets,
            "diagnostic_scope_bundle",
        )
        generation = self.base.head.read().head.generation
        run_fact = {
            "receipt_kind": "ticket119-acceptance-run",
            "status": "current",
            "owner_id": _OWNER_ID,
            "installation_id": _INSTALLATION_ID,
            "release_digest": _RELEASE_DIGEST,
            "bundle_hash": scope_bundle_hash,
            "generation": generation,
            "run_id": "ticket119-run:ticket116-active-fixture",
            "gate_id": "119-G12",
            "issued_at_utc": "2026-08-24T03:00:00+00:00",
            "expires_at_utc": "2099-08-24T04:00:00+00:00",
        }
        run_provider = _AcceptanceEvidenceProvider({run_ref: run_fact})
        self._restart_with_assets(
            staged_assets,
            acceptance_evidence_provider=run_provider,
        )
        ready_scope = self._managed_read()["scope"]
        self.assertEqual(ready_scope["persistent_state"], "staged")
        self.assertEqual(ready_scope["effective_phase"], "activation-ready")
        effect_id, adapter = self._prepare_and_execute_model(
            source_suffix="active-fixture",
            question_ref="question:synthetic-activation-proof",
            event_ref="event:synthetic-activation-proof",
            applicable_period="2026-08-23",
            run_receipt_ref=run_ref,
            source="ticket119_acceptance_runtime",
        )
        authorized_scope = self._managed_read()["scope"]
        self.assertEqual(authorized_scope["persistent_state"], "staged")
        self.assertEqual(
            authorized_scope["effective_phase"],
            "acceptance-authorized",
        )
        replay = self._health(
            "diagnosis.prepare",
            self._diagnosis_prepare_payload(
                source_suffix="active-fixture-replay",
                question_ref="question:synthetic-activation-proof",
                event_ref="event:synthetic-activation-proof",
                applicable_period="2026-08-23",
                run_receipt_ref=run_ref,
            ),
            suffix="active-fixture-replay",
            source="ticket119_acceptance_runtime",
        )
        self.assertEqual(replay.get("status"), "rejected", replay)
        committed = self._health(
            "diagnosis.commit",
            {
                "commit_kind": "diagnostic-judgment",
                "source_causal_id": "ticket116-diagnostic-source:active-fixture",
                "model_effect_id": effect_id,
                "run_receipt_ref": run_ref,
            },
            suffix="active-fixture-commit",
            source="ticket119_acceptance_runtime",
        )
        self.assertEqual(committed.get("status"), "committed", committed)
        self.assertEqual(adapter.calls, 1)
        diagnosis_ref = committed["diagnosis_ref"]
        accepted_provider = _AcceptanceEvidenceProvider(
            {
                run_ref: run_fact,
                acceptance_ref: {
                    "receipt_kind": "ticket119-owner-acceptance",
                    "status": "accepted",
                    "run_receipt_ref": run_ref,
                    "owner_id": _OWNER_ID,
                    "installation_id": _INSTALLATION_ID,
                    "release_digest": _RELEASE_DIGEST,
                    "bundle_hash": run_fact["bundle_hash"],
                    "generation": generation,
                    "run_id": run_fact["run_id"],
                    "gate_id": run_fact["gate_id"],
                    "diagnosis_ref": diagnosis_ref,
                    "accepted_at_utc": "2026-08-24T03:30:00+00:00",
                },
            }
        )
        self._restart_with_assets(
            self._synthetic_assets(scope_state="staged"),
            acceptance_evidence_provider=accepted_provider,
        )
        activated = self._health(
            "diagnosis.activate",
            {
                "run_receipt_ref": run_ref,
                "acceptance_receipt_ref": acceptance_ref,
            },
            suffix="active-fixture-activate",
            source="ticket119_acceptance_runtime",
        )
        self.assertEqual(activated.get("status"), "committed", activated)
        managed = self._managed_read()
        self.assertEqual(managed["scope"]["persistent_state"], "active")
        self.assertEqual(managed["scope"]["effective_phase"], "active")
        self.assertEqual(
            managed["scope"]["acceptance_evidence_ref"],
            acceptance_ref,
        )
        return managed

    def _contact_effect_grant(
        self,
        contact_alert: object,
    ) -> tuple[str, object]:
        """Parse the one frozen Ticket 116 contact-effect wire shape."""

        self.assertIsInstance(contact_alert, Mapping)
        assert isinstance(contact_alert, Mapping)
        self.assertEqual(set(contact_alert), {"intent_id", "effect_intent"})
        intent = EffectIntent.from_wire_metadata(contact_alert["effect_intent"])
        self.assertEqual(contact_alert["intent_id"], intent.effect_id)
        grant = self.plugin.claim_effect_execution(intent)
        self.assertIsNotNone(grant)
        return intent.effect_id, grant

    def test_v116_01_minimum_help_bundle_blocks_entry_before_body_read(self) -> None:
        """Break caught: an unverified minimum-help asset registers health entry."""

        # Keep the shared missing constructor seam as one method-level RED.
        # Once it exists, the four frozen invalid-asset classes expand below.
        self._restart_with_assets(self._synthetic_assets(), root_gate=True)

        for index, field in enumerate(("missing", "rights", "review", "parse")):
            with self.subTest(minimum_help_field=field):
                if index:
                    self._reset_harness()
                self._configure_synthetic_contact()
                self._grant_contact_authority()
                contact = self.plugin.managed_owner_settings_read(peer_id=_PEER)[
                    "support_contact"
                ]
                self.assertEqual(contact.get("alert_authority_status"), "approved")
                before_deliveries = self.plugin.managed_ticket115_read(
                    peer_id=_PEER
                )["owner_deliveries"]
                assets = self._synthetic_assets(
                    minimum_help_rights_current=(field != "rights"),
                    minimum_help_review_current=(field != "review"),
                    minimum_help_parse_current=(field != "parse"),
                )
                if field == "missing":
                    assets.pop("minimum_help_bundle")
                self._restart_with_assets(assets, root_gate=True)
                invalid_body = CountingBody("SYNTHETIC:DANGER_CONFIRMED")
                invalid = self.plugin.receive_weixin(
                    self._message(invalid_body, suffix=f"invalid-{field}"),
                    peer_id=_PEER,
                )
                probe = self.plugin.probe()
                self.assertEqual(probe.state, ProbeState.UNAVAILABLE)
                self.assertEqual(
                    probe.reason_code,
                    "minimum-help-bundle-unavailable",
                )
                self.assertEqual(
                    (invalid.status, invalid.reason_code),
                    ("unavailable", "minimum-help-bundle-unavailable"),
                )
                self.assertEqual(invalid_body.reads, 0)
                self.assertEqual(
                    self.plugin.business_status(peer_id=_PEER).projection.state,
                    "cannot-confirm",
                )
                public_meta = (
                    {}
                    if invalid.meta is None
                    else self._meta_wire(invalid)
                )
                self.assertIsNone(public_meta.get("contact_alert"))
                self.assertNotIn("effect_intent", public_meta)
                self.assertNotIn("model_intent", public_meta)
                self.assertEqual(
                    self.plugin.managed_ticket115_read(peer_id=_PEER)[
                        "owner_deliveries"
                    ],
                    before_deliveries,
                )

        # The declared digest is a content address, not a formatting token.
        # Tampering one approved template while retaining its digest must make
        # the entry fail before the message body can be materialized.  A host
        # may reject the Core constructor outright or expose an unavailable
        # Plugin; both are fail-closed startup outcomes.
        self._reset_harness()
        mismatched_assets = self._synthetic_assets()
        minimum = mismatched_assets["minimum_help_bundle"]
        assert isinstance(minimum, dict)
        templates = minimum["templates"]
        assert isinstance(templates, dict)
        danger_owner = templates["danger_owner"]
        assert isinstance(danger_owner, dict)
        danger_owner["text"] = "[合成测试] 未经内容地址批准的替换文本"
        mismatched_body = CountingBody("SYNTHETIC:DANGER_CONFIRMED")
        try:
            self._restart_with_assets(mismatched_assets, root_gate=True)
        except AuthorityValidationError:
            pass
        else:
            mismatched = self.plugin.receive_weixin(
                self._message(mismatched_body, suffix="minimum-help-hash-mismatch"),
                peer_id=_PEER,
            )
            self.assertEqual(mismatched_body.reads, 0)
            self.assertEqual(mismatched.status, "unavailable", mismatched)
            mismatch_meta = (
                {} if mismatched.meta is None else self._meta_wire(mismatched)
            )
            self.assertIsNone(mismatch_meta.get("contact_alert"))
        self.assertEqual(mismatched_body.reads, 0)

        self._reset_harness()
        self._restart_with_assets(
            self._synthetic_assets(),
            root_gate=True,
        )
        before_admission = self._managed_read()
        admission_cases = (
            ("admission", {"channel": "untrusted-channel"}),
            ("owner", {"sender_id": "not-current-owner"}),
            ("session", {"conversation_id": "other-private-session"}),
            ("entry", {"entrypoint": "untrusted-health-entry"}),
        )
        for suffix, overrides in admission_cases:
            with self.subTest(boundary=suffix):
                rejected_body = CountingBody("SYNTHETIC:DANGER_CONFIRMED")
                rejected = self.plugin.receive_weixin(
                    self._message(
                        rejected_body,
                        suffix=f"admission-{suffix}",
                        **overrides,
                    ),
                    peer_id=_PEER,
                )
                self.assertEqual(rejected.status, "rejected")
                self.assertEqual(rejected_body.reads, 0)
        self.assertEqual(self._managed_read(), before_admission)

    def test_v116_02_safety_priority_produces_one_truthful_branch(self) -> None:
        """Break caught: a lower-priority diagnosis branch overrides safety."""

        self._restart_with_assets(self._synthetic_assets())
        cases = (
            (
                "safety-unavailable-dominates",
                {
                    "safety_capability": "unavailable",
                    "danger": "confirmed",
                    "scope": "in-scope",
                },
                "safety-capability-unavailable",
                _MINIMUM_TEMPLATE_REF,
            ),
            (
                "danger-dominates-unknown",
                {
                    "safety_capability": "available",
                    "danger": "confirmed",
                    "scope": "out-of-scope",
                },
                "danger-escalation",
                _DANGER_TEMPLATE_REF,
            ),
            (
                "unknown-dominates-scope",
                {
                    "safety_capability": "available",
                    "danger": "unknown",
                    "scope": "in-scope",
                },
                "danger-unknown",
                _UNKNOWN_TEMPLATE_REF,
            ),
            (
                "out-of-scope",
                {
                    "safety_capability": "available",
                    "danger": "not-present",
                    "scope": "out-of-scope",
                },
                "out-of-scope",
                _OUT_OF_SCOPE_TEMPLATE_REF,
            ),
            (
                "in-scope",
                {
                    "safety_capability": "available",
                    "danger": "not-present",
                    "scope": "in-scope",
                },
                "in-scope",
                None,
            ),
        )
        for suffix, facts, branch, template_ref in cases:
            with self.subTest(suffix=suffix):
                result = self._health(
                    "safety.evaluate",
                    {
                        "source_causal_id": f"ticket116-safety:{suffix}",
                        "safety_rule_bundle_hash": self.safety_bundle_hash,
                        "facts": facts,
                    },
                    suffix=suffix,
                )
                self.assertEqual(result.get("branch"), branch, result)
                owner_result = result.get("owner_result")
                if template_ref is None:
                    self.assertIsNone(owner_result)
                else:
                    self.assertEqual(
                        owner_result,
                        {
                            "template_ref": template_ref,
                            "rendering": {
                                "language": "zh-CN",
                                "deterministic": True,
                            },
                        },
                    )
                self.assertNotIn("diagnosis", result)

    def test_v116_03_route_failure_keeps_owner_prompt_and_bounds_contact_alert(self) -> None:
        """Break caught: a route/Skill failure swallows or over-triggers safety."""

        self._restart_with_assets(self._synthetic_assets())
        route_down_plugin = HealthPlugin(
            self.core,
            admission_policy=self.base.policy,
            health_init_runtime=self.base.init_runtime,
            coarse_router=None,
            daily_skill_runtime=None,
        )

        without_approval = route_down_plugin.receive_weixin(
            self._message(
                CountingBody("SYNTHETIC:DANGER_CONFIRMED"),
                suffix="route-down-unapproved",
            ),
            peer_id=_PEER,
        )
        unapproved_meta = self._meta_wire(without_approval)
        self.assertEqual(unapproved_meta["branch"], "danger-escalation")
        self.assertEqual(
            unapproved_meta["owner_result"]["template_ref"],
            _DANGER_TEMPLATE_REF,
        )
        self.assertIsNone(unapproved_meta["contact_alert"])

        self._configure_synthetic_contact()
        self._grant_contact_authority()
        with_approval = route_down_plugin.receive_weixin(
            self._message(
                CountingBody("SYNTHETIC:DANGER_CONFIRMED"),
                suffix="route-down-approved",
            ),
            peer_id=_PEER,
        )
        approved_meta = self._meta_wire(with_approval)
        self.assertEqual(approved_meta["branch"], "danger-escalation")
        self.assertEqual(
            approved_meta["owner_result"]["template_ref"],
            _DANGER_TEMPLATE_REF,
        )
        self.assertIsNotNone(approved_meta["contact_alert"]["intent_id"])

        unknown = route_down_plugin.receive_weixin(
            self._message(
                CountingBody("SYNTHETIC:DANGER_UNKNOWN"),
                suffix="route-down-unknown",
            ),
            peer_id=_PEER,
        )
        unknown_meta = self._meta_wire(unknown)
        self.assertEqual(unknown_meta["branch"], "danger-unknown")
        self.assertEqual(
            unknown_meta["owner_result"]["template_ref"],
            _UNKNOWN_TEMPLATE_REF,
        )
        self.assertIsNone(unknown_meta["contact_alert"])

        # When routing is down, both an unmatched current rule and an
        # unavailable rule capability are the same safe observable class:
        # return the fixed minimum-help result and never infer a contact alert.
        for unavailable_kind in ("no-current-rule-match", "rule-capability-down"):
            with self.subTest(route_down_fallback=unavailable_kind):
                self._reset_harness()
                self._restart_with_assets(
                    self._synthetic_assets(
                        safety_rules_current=(
                            unavailable_kind != "rule-capability-down"
                        )
                    )
                )
                self._configure_synthetic_contact()
                self._grant_contact_authority()
                fallback_plugin = HealthPlugin(
                    self.core,
                    admission_policy=self.base.policy,
                    health_init_runtime=self.base.init_runtime,
                    coarse_router=None,
                    daily_skill_runtime=None,
                )
                body = CountingBody(
                    "SYNTHETIC:NO_CURRENT_RULE_MATCH"
                    if unavailable_kind == "no-current-rule-match"
                    else "SYNTHETIC:DANGER_CONFIRMED"
                )
                fallback = fallback_plugin.receive_weixin(
                    self._message(body, suffix=unavailable_kind),
                    peer_id=_PEER,
                )
                fallback_meta = self._meta_wire(fallback)
                self.assertEqual(fallback.status, "accepted", fallback)
                self.assertEqual(
                    fallback_meta["owner_result"]["template_ref"],
                    _MINIMUM_TEMPLATE_REF,
                )
                self.assertIsNone(fallback_meta["contact_alert"])

    def test_v116_04_scope_persists_only_staged_or_active(self) -> None:
        """Break caught: readiness or acceptance mode becomes durable scope state."""

        initial_assets = self._synthetic_assets(scope_state="staged")
        scope_bundle_hash = _asset_bundle_hash(
            initial_assets,
            "diagnostic_scope_bundle",
        )

        def acceptance_run_fact(suffix: str) -> dict[str, object]:
            return {
                "receipt_kind": "ticket119-acceptance-run",
                "status": "current",
                "owner_id": _OWNER_ID,
                "installation_id": _INSTALLATION_ID,
                "release_digest": _RELEASE_DIGEST,
                "bundle_hash": scope_bundle_hash,
                "generation": self.base.head.read().head.generation,
                "run_id": f"ticket119-run:{suffix}",
                "gate_id": "119-G12",
                "issued_at_utc": "2026-08-24T03:00:00+00:00",
                "expires_at_utc": "2099-08-24T04:00:00+00:00",
            }

        def owner_acceptance_fact(
            *,
            run_ref: str,
            run_fact: Mapping[str, object],
            diagnosis_ref: object,
            status: str,
        ) -> dict[str, object]:
            return {
                "receipt_kind": "ticket119-owner-acceptance",
                "status": status,
                "run_receipt_ref": run_ref,
                "owner_id": _OWNER_ID,
                "installation_id": _INSTALLATION_ID,
                "release_digest": _RELEASE_DIGEST,
                "bundle_hash": run_fact["bundle_hash"],
                "generation": run_fact["generation"],
                "run_id": run_fact["run_id"],
                "gate_id": run_fact["gate_id"],
                "diagnosis_ref": diagnosis_ref,
            }

        run_ref = "acceptance-run-receipt:ticket119-authorization-checks"
        expired_ref = "acceptance-run-receipt:ticket119-expired"
        wrong_binding_ref = "acceptance-run-receipt:ticket119-wrong-binding"
        run_fact = acceptance_run_fact("authorization-checks")
        provider = _AcceptanceEvidenceProvider(
            {
                run_ref: run_fact,
                expired_ref: {
                    **run_fact,
                    "run_id": "ticket119-run:expired",
                    "expires_at_utc": "2000-01-01T00:00:00+00:00",
                },
                wrong_binding_ref: {
                    **run_fact,
                    "run_id": "ticket119-run:wrong-binding",
                    "bundle_hash": "sha256:" + ("0" * 64),
                },
            }
        )
        self._restart_with_assets(
            initial_assets,
            acceptance_evidence_provider=provider,
        )
        before = self._managed_read()["scope"]
        self.assertEqual(before["persistent_state"], "staged")
        self.assertEqual(before["effective_phase"], "activation-ready")
        self.assertNotIn(
            before["persistent_state"],
            {"activation-ready", "acceptance-authorized"},
        )

        ordinary = self._health(
            "diagnosis.prepare",
            self._diagnosis_prepare_payload(source_suffix="ordinary-staged"),
            suffix="ordinary-staged",
        )
        self.assertEqual(ordinary.get("status"), "rejected", ordinary)

        for suffix, source, receipt_ref in (
            ("ordinary-valid-run", "diagnostic_runtime", run_ref),
            ("forged", "ticket119_acceptance_runtime", "acceptance-run-receipt:forged"),
            ("expired", "ticket119_acceptance_runtime", expired_ref),
            ("wrong-binding", "ticket119_acceptance_runtime", wrong_binding_ref),
        ):
            with self.subTest(authorization=suffix):
                denied = self._health(
                    "diagnosis.prepare",
                    self._diagnosis_prepare_payload(
                        source_suffix=suffix,
                        run_receipt_ref=receipt_ref,
                    ),
                    suffix=suffix,
                    source=source,
                )
                self.assertEqual(denied.get("status"), "rejected", denied)
                self.assertEqual(
                    self._managed_read()["scope"]["persistent_state"],
                    "staged",
                )

        intent_only = self._health(
            "diagnosis.prepare",
            self._diagnosis_prepare_payload(
                source_suffix="intent-formation-consumes-run",
                run_receipt_ref=run_ref,
            ),
            suffix="intent-formation-consumes-run",
            source="ticket119_acceptance_runtime",
        )
        self.assertEqual(intent_only.get("status"), "model-ready", intent_only)
        EffectIntent.from_wire_metadata(intent_only.get("model_intent"))
        consumed_at_intent = self._health(
            "diagnosis.prepare",
            self._diagnosis_prepare_payload(
                source_suffix="intent-formation-consumes-run-replay",
                run_receipt_ref=run_ref,
            ),
            suffix="intent-formation-consumes-run-replay",
            source="ticket119_acceptance_runtime",
        )
        self.assertEqual(
            consumed_at_intent.get("status"),
            "rejected",
            consumed_at_intent,
        )
        self.assertEqual(
            self._managed_read()["scope"]["persistent_state"],
            "staged",
        )

        self._reset_harness()
        positive = self._activate_synthetic_scope_through_ticket119()
        self.assertEqual(positive["scope"]["persistent_state"], "active")

        for terminal_status in ("rejected", "failed", "unknown"):
            with self.subTest(owner_acceptance_terminal=terminal_status):
                self._reset_harness()
                terminal_run_ref = (
                    f"acceptance-run-receipt:ticket119-terminal-{terminal_status}"
                )
                terminal_ref = (
                    f"owner-acceptance-receipt:ticket119-{terminal_status}"
                )
                late_accepted_ref = (
                    "owner-acceptance-receipt:ticket119-late-accepted-"
                    f"{terminal_status}"
                )
                terminal_run_fact = acceptance_run_fact(
                    f"terminal-{terminal_status}"
                )
                self._restart_with_assets(
                    self._synthetic_assets(scope_state="staged"),
                    acceptance_evidence_provider=_AcceptanceEvidenceProvider(
                        {terminal_run_ref: terminal_run_fact}
                    ),
                )
                source_suffix = f"terminal-{terminal_status}"
                effect_id, adapter = self._prepare_and_execute_model(
                    source_suffix=source_suffix,
                    run_receipt_ref=terminal_run_ref,
                    source="ticket119_acceptance_runtime",
                )
                committed = self._health(
                    "diagnosis.commit",
                    {
                        "commit_kind": "diagnostic-judgment",
                        "source_causal_id": (
                            f"ticket116-diagnostic-source:{source_suffix}"
                        ),
                        "model_effect_id": effect_id,
                        "run_receipt_ref": terminal_run_ref,
                    },
                    suffix=f"{source_suffix}-commit",
                    source="ticket119_acceptance_runtime",
                )
                self.assertEqual(committed.get("status"), "committed", committed)
                self.assertEqual(adapter.calls, 1)
                diagnosis_ref = committed["diagnosis_ref"]
                terminal_fact = owner_acceptance_fact(
                    run_ref=terminal_run_ref,
                    run_fact=terminal_run_fact,
                    diagnosis_ref=diagnosis_ref,
                    status=terminal_status,
                )
                self._restart_with_assets(
                    self._synthetic_assets(scope_state="staged"),
                    acceptance_evidence_provider=_AcceptanceEvidenceProvider(
                        {
                            terminal_run_ref: terminal_run_fact,
                            terminal_ref: terminal_fact,
                        }
                    ),
                )
                terminal = self._health(
                    "diagnosis.activate",
                    {
                        "run_receipt_ref": terminal_run_ref,
                        "acceptance_receipt_ref": terminal_ref,
                    },
                    suffix=f"owner-acceptance-{terminal_status}",
                    source="ticket119_acceptance_runtime",
                )
                self.assertNotEqual(terminal.get("status"), "committed", terminal)
                self.assertEqual(
                    self._managed_read()["scope"]["persistent_state"],
                    "staged",
                )

                late_accepted_fact = owner_acceptance_fact(
                    run_ref=terminal_run_ref,
                    run_fact=terminal_run_fact,
                    diagnosis_ref=diagnosis_ref,
                    status="accepted",
                )
                late_accepted_fact["accepted_at_utc"] = (
                    "2026-08-24T03:31:00+00:00"
                )
                self._restart_with_assets(
                    self._synthetic_assets(scope_state="staged"),
                    acceptance_evidence_provider=_AcceptanceEvidenceProvider(
                        {
                            terminal_run_ref: terminal_run_fact,
                            late_accepted_ref: late_accepted_fact,
                        }
                    ),
                )
                late = self._health(
                    "diagnosis.activate",
                    {
                        "run_receipt_ref": terminal_run_ref,
                        "acceptance_receipt_ref": late_accepted_ref,
                    },
                    suffix=f"late-accepted-after-{terminal_status}",
                    source="ticket119_acceptance_runtime",
                )
                self.assertNotEqual(late.get("status"), "committed", late)
                self.assertEqual(
                    self._managed_read()["scope"]["persistent_state"],
                    "staged",
                )

        self._reset_harness()
        mismatched_scope_assets = self._synthetic_assets(scope_state="staged")
        scope_bundle = mismatched_scope_assets["diagnostic_scope_bundle"]
        assert isinstance(scope_bundle, dict)
        thresholds = scope_bundle["thresholds"]
        assert isinstance(thresholds, list)
        upper = thresholds[-1]
        assert isinstance(upper, dict)
        upper["minimum_bmi"] = "26.0"
        try:
            self._restart_with_assets(mismatched_scope_assets)
        except AuthorityValidationError:
            pass
        else:
            mismatched_scope = self._managed_read()["scope"]
            self.assertEqual(mismatched_scope["persistent_state"], "staged")
            self.assertEqual(mismatched_scope["effective_phase"], "staged")

    def test_v116_05_pre_model_authority_drift_forms_no_model_effect(self) -> None:
        """Break caught: one pre-check is treated as permission for all facts."""

        self._activate_synthetic_scope_through_ticket119()
        cases = (
            "current-head",
            "evidence-revision",
            "route",
            "control",
            "safety-assets",
        )
        for index, authority in enumerate(cases):
            with self.subTest(authority_family=authority):
                if index:
                    self._reset_harness()
                    self._activate_synthetic_scope_through_ticket119()
                payload = self._diagnosis_prepare_payload(
                    source_suffix=f"pre-drift-{authority}"
                )
                generation = self.base.head.read().head.generation
                if authority == "evidence-revision":
                    # A real owner correction advances the evidence revision;
                    # the request continues to reference the earlier public card.
                    self.base._build_and_commit_correction_stage()
                elif authority == "route":
                    self.harness.route_fact = replace(
                        self.harness.route_fact,
                        configuration_generation=2,
                        generation=2,
                    )
                elif authority == "control":
                    self._stop_recording()
                elif authority == "safety-assets":
                    self._restart_with_assets(
                        self._synthetic_assets(
                            safety_rules_current=False,
                            scope_state="staged",
                        )
                    )

                unused_adapter = _RecordingModelAdapter(
                    self._completed_model_result()
                )
                try:
                    result = self.plugin.health_operation(
                        "diagnosis.prepare",
                        payload,
                        context=self._health_context(
                            "diagnosis.prepare",
                            generation=(
                                generation - 1
                                if authority == "current-head"
                                else None
                            ),
                            suffix=f"pre-drift-{authority}",
                        ),
                        peer_id=_PEER,
                    )
                except AuthorityValidationError:
                    result = {"status": "rejected"}
                self.assertEqual(result.get("status"), "rejected", result)
                self.assertNotIn("model_intent", result)
                self.assertEqual(unused_adapter.calls, 0)
                managed = self._managed_read()
                target_diagnoses = [
                    item
                    for item in managed["diagnoses"]
                    if item["question_ref"] == "question:synthetic-bmi"
                    and item["event_ref"] == "event:synthetic-measurement"
                    and item["applicable_period"] == "2026-08-24"
                ]
                self.assertEqual(target_diagnoses, [])
                self.assertFalse(
                    any(
                        item.get("source_causal_id")
                        == payload["source_causal_id"]
                        for item in managed["owner_results"]
                    )
                )

        # One representative safety-rule mutation exercises the same
        # content-addressed-asset boundary as V01/V04 without multiplying every
        # field combination.  Keeping the declared digest while changing a rule
        # must fail closed before a model effect can be formed.
        self._reset_harness()
        self._activate_synthetic_scope_through_ticket119()
        payload = self._diagnosis_prepare_payload(
            source_suffix="safety-content-hash-mismatch"
        )
        mismatched_safety_assets = self._synthetic_assets(scope_state="staged")
        safety_bundle = mismatched_safety_assets["safety_rule_bundle"]
        assert isinstance(safety_bundle, dict)
        rules = safety_bundle["rules"]
        assert isinstance(rules, list)
        first_rule = rules[0]
        assert isinstance(first_rule, dict)
        first_rule["input"] = "SYNTHETIC:TAMPERED-SAFETY-INPUT"
        try:
            self._restart_with_assets(mismatched_safety_assets)
        except AuthorityValidationError:
            pass
        else:
            mismatched = self._health(
                "diagnosis.prepare",
                payload,
                suffix="safety-content-hash-mismatch",
            )
            self.assertEqual(mismatched.get("status"), "rejected", mismatched)
            self.assertNotIn("model_intent", mismatched)

    def test_v116_06_post_model_recomputes_unrounded_bmi(self) -> None:
        """Break caught: terminal/schema/evidence/BMI failures become records."""

        active_baseline = self._activate_synthetic_scope_through_ticket119()
        cases = ("incomplete", "failed", "unknown", "schema", "evidence", "bmi")
        for index, case in enumerate(cases):
            with self.subTest(post_model_equivalence=case):
                if index:
                    self._reset_harness()
                    active_baseline = (
                        self._activate_synthetic_scope_through_ticket119()
                    )
                if case in {"incomplete", "failed", "unknown"}:
                    model_result = self._noncompleted_model_result(case)
                else:
                    candidate = self._diagnostic_candidate(
                        classification=("synthetic-upper" if case == "bmi" else "synthetic-lower")
                    )
                    if case == "schema":
                        candidate.pop("urgency")
                    elif case == "evidence":
                        candidate["evidence_refs"] = ["evidence:stale-revision"]
                    model_result = self._completed_model_result(
                        structured_output=candidate
                    )
                effect_id, adapter = self._prepare_and_execute_model(
                    source_suffix=f"post-{case}",
                    model_result=model_result,
                )
                committed = self._health(
                    "diagnosis.commit",
                    {
                        "commit_kind": "diagnostic-judgment",
                        "source_causal_id": f"ticket116-diagnostic-source:post-{case}",
                        "model_effect_id": effect_id,
                    },
                    suffix=f"post-{case}",
                )
                self.assertNotEqual(committed.get("status"), "committed", committed)
                self.assertEqual(adapter.calls, 1)
                self.assertEqual(
                    self._managed_read()["diagnoses"],
                    active_baseline["diagnoses"],
                )

        approved_reference_cases: tuple[tuple[str, str, object], ...] = (
            (
                "knowledge_refs",
                "knowledge_refs",
                ["knowledge-release:unapproved-ticket116"],
            ),
            (
                "safety_bundle_ref",
                "safety_bundle_ref",
                "synthetic-safety-rules@unapproved",
            ),
            (
                "template_bundle_ref",
                "template_bundle_ref",
                "minimum-help-template:unapproved-ticket116",
            ),
            (
                "model_capability_ref",
                "model_capability_ref",
                "synthetic-ticket116-profile@unapproved",
            ),
        )
        for label, field, unapproved_reference in approved_reference_cases:
            with self.subTest(candidate_current_reference=label):
                self._reset_harness()
                before = self._activate_synthetic_scope_through_ticket119()
                candidate = self._diagnostic_candidate()
                candidate[field] = unapproved_reference
                effect_id, adapter = self._prepare_and_execute_model(
                    source_suffix=f"post-unapproved-{label}",
                    model_result=self._completed_model_result(
                        structured_output=candidate
                    ),
                )
                committed = self._health(
                    "diagnosis.commit",
                    {
                        "commit_kind": "diagnostic-judgment",
                        "source_causal_id": (
                            f"ticket116-diagnostic-source:post-unapproved-{label}"
                        ),
                        "model_effect_id": effect_id,
                    },
                    suffix=f"post-unapproved-{label}",
                )
                self.assertNotEqual(committed.get("status"), "committed", committed)
                self.assertEqual(adapter.calls, 1)
                after = self._managed_read()
                self.assertEqual(after["diagnoses"], before["diagnoses"])
                self.assertEqual(after["owner_results"], before["owner_results"])

        self._reset_harness()
        active_baseline = self._activate_synthetic_scope_through_ticket119()
        effect_id, _ = self._prepare_and_execute_model(source_suffix="post-positive")
        positive = self._health(
            "diagnosis.commit",
            {
                "commit_kind": "diagnostic-judgment",
                "source_causal_id": "ticket116-diagnostic-source:post-positive",
                "model_effect_id": effect_id,
            },
            suffix="post-positive",
        )
        self.assertEqual(positive.get("status"), "committed", positive)
        positive_managed = self._managed_read()
        diagnosis = next(
            item
            for item in positive_managed["diagnoses"]
            if item["diagnosis_ref"] == positive["diagnosis_ref"]
        )
        self.assertEqual(diagnosis["judgment"]["bmi_unrounded"], "25.0045")
        self.assertEqual(diagnosis["judgment"]["classification"], "synthetic-lower")
        for field in (
            "support_refs",
            "opposition_refs",
            "missing_refs",
            "uncertainties",
            "urgency",
            "allowed_next_steps",
            "evidence_refs",
        ):
            self.assertIn(field, diagnosis)
        self.assertEqual(
            diagnosis["evidence_refs"],
            [self.base.baseline_card.evidence_id],
        )
        self.assertEqual(
            diagnosis["knowledge_refs"],
            [self.knowledge_release.release_id],
        )
        self.assertEqual(
            diagnosis["safety_bundle_ref"],
            "synthetic-safety-rules@1.0.0-test",
        )
        self.assertEqual(
            diagnosis["template_bundle_ref"],
            _MINIMUM_TEMPLATE_REF,
        )
        self.assertEqual(
            diagnosis["model_capability_ref"],
            "synthetic-ticket116-profile@1.0.0-test",
        )
        self.assertEqual(
            len(positive_managed["owner_results"]),
            len(active_baseline["owner_results"]) + 1,
        )
        owner_result = positive_managed["owner_results"][-1]
        self.assertEqual(owner_result["diagnosis_ref"], positive["diagnosis_ref"])
        self.assertTrue(owner_result["deterministic"])

    def test_v116_07_commit_gate_is_atomic_and_recovers_original_decision(self) -> None:
        """Break caught: precommit/prepare/CAS/finalize leaks partial state."""

        self._activate_synthetic_scope_through_ticket119()
        cases = ("precommit-drift", "prepare", "cas", "finalize", "unknown")
        for index, case in enumerate(cases):
            with self.subTest(transaction_boundary=case):
                if index:
                    self._reset_harness()
                    self._activate_synthetic_scope_through_ticket119()
                effect_id, adapter = self._prepare_and_execute_model(
                    source_suffix=f"commit-{case}"
                )
                generation = self.base.head.read().head.generation
                if case == "precommit-drift":
                    self.harness.route_fact = replace(
                        self.harness.route_fact,
                        configuration_generation=2,
                        generation=2,
                    )
                elif case == "prepare":
                    self.base.head.set_failure(FailureMode.TIMEOUT, operation="read")
                elif case == "cas":
                    self.base.head.set_failure(FailureMode.CONFLICT, operation="advance")
                elif case == "finalize":
                    self.base.store.fail_commit_after_receipt = True
                elif case == "unknown":
                    self.base.head.set_failure(
                        FailureMode.UNKNOWN_AFTER_ADVANCE,
                        operation="advance",
                    )
                result = self._health(
                    "diagnosis.commit",
                    {
                        "commit_kind": "diagnostic-judgment",
                        "source_causal_id": f"ticket116-diagnostic-source:commit-{case}",
                        "model_effect_id": effect_id,
                    },
                    generation=generation,
                    suffix=f"commit-{case}",
                )
                self.base.head.clear_failure()
                self.base.store.clear_commit_failure()
                target_source = f"ticket116-diagnostic-source:commit-{case}"
                if case != "unknown":
                    self.assertNotEqual(result.get("status"), "committed", result)
                    during = self._managed_read()
                    target_diagnoses = [
                        item
                        for item in during["diagnoses"]
                        if item["question_ref"] == "question:synthetic-bmi"
                        and item["event_ref"] == "event:synthetic-measurement"
                        and item["applicable_period"] == "2026-08-24"
                    ]
                    self.assertEqual(target_diagnoses, [])
                    self.assertFalse(
                        any(
                            item.get("source_causal_id") == target_source
                            for item in during["owner_results"]
                        )
                    )
                    if case == "finalize":
                        self._restart_with_assets(
                            self._synthetic_assets(scope_state="staged")
                        )
                        recovered = self._health(
                            "diagnosis.commit",
                            {
                                "commit_kind": "diagnostic-judgment",
                                "source_causal_id": target_source,
                                "model_effect_id": effect_id,
                            },
                            suffix="commit-finalize-replay",
                        )
                        self.assertIn(
                            recovered.get("status"),
                            {"committed", "replayed"},
                            recovered,
                        )
                        final = self._managed_read()
                        recovered_diagnoses = [
                            item
                            for item in final["diagnoses"]
                            if item["question_ref"] == "question:synthetic-bmi"
                            and item["event_ref"] == "event:synthetic-measurement"
                            and item["applicable_period"] == "2026-08-24"
                        ]
                        self.assertEqual(len(recovered_diagnoses), 1)
                        self.assertEqual(
                            sum(
                                item.get("source_causal_id") == target_source
                                for item in final["owner_results"]
                            ),
                            1,
                        )
                else:
                    self.assertEqual(result.get("status"), "unknown", result)
                    self._restart_with_assets(
                        self._synthetic_assets(scope_state="staged")
                    )
                    recovered = self._health(
                        "diagnosis.commit",
                        {
                            "commit_kind": "diagnostic-judgment",
                            "source_causal_id": "ticket116-diagnostic-source:commit-unknown",
                            "model_effect_id": effect_id,
                        },
                        suffix="commit-unknown-replay",
                    )
                    self.assertIn(
                        recovered.get("status"),
                        {"committed", "replayed"},
                        recovered,
                    )
                    final = self._managed_read()
                    recovered_diagnoses = [
                        item
                        for item in final["diagnoses"]
                        if item["question_ref"] == "question:synthetic-bmi"
                        and item["event_ref"] == "event:synthetic-measurement"
                        and item["applicable_period"] == "2026-08-24"
                    ]
                    self.assertEqual(len(recovered_diagnoses), 1)
                    self.assertEqual(
                        sum(
                            item.get("source_causal_id") == target_source
                            for item in final["owner_results"]
                        ),
                        1,
                    )
                self.assertEqual(adapter.calls, 1)

        # A safety decision is a durable business result, not a local cache
        # write.  Once the first command commits, another distinct command
        # carrying the same former generation must be rejected; otherwise two
        # writers can publish safety results under one current-head snapshot.
        self._reset_harness()
        self._restart_with_assets(self._synthetic_assets())
        stale_generation = self.base.head.read().head.generation
        first_source = "ticket116-safety:writer-fence-first"
        second_source = "ticket116-safety:writer-fence-stale"
        first = self._health(
            "safety.evaluate",
            {
                "source_causal_id": first_source,
                "safety_rule_bundle_hash": self.safety_bundle_hash,
                "facts": {
                    "safety_capability": "available",
                    "danger": "unknown",
                    "scope": "in-scope",
                },
            },
            generation=stale_generation,
            suffix="writer-fence-first",
        )
        self.assertEqual(first.get("branch"), "danger-unknown", first)
        try:
            stale = self.plugin.health_operation(
                "safety.evaluate",
                {
                    "source_causal_id": second_source,
                    "safety_rule_bundle_hash": self.safety_bundle_hash,
                    "facts": {
                        "safety_capability": "available",
                        "danger": "unknown",
                        "scope": "in-scope",
                    },
                },
                context=self._health_context(
                    "safety.evaluate",
                    generation=stale_generation,
                    suffix="writer-fence-stale",
                ),
                peer_id=_PEER,
            )
        except (ProtocolViolation, AuthorityValidationError):
            stale = {"status": "rejected"}
        self.assertEqual(stale.get("status"), "rejected", stale)
        persisted_sources = {
            item.get("source_causal_id")
            for item in self._managed_read()["safety_events"]
        }
        self.assertIn(first_source, persisted_sources)
        self.assertNotIn(second_source, persisted_sources)

    def test_v116_08_revision_chain_never_exposes_two_current_judgments(self) -> None:
        """Break caught: correction overwrites or forks the current judgment."""

        self._activate_synthetic_scope_through_ticket119()
        outcomes = ("no-change", "replace", "degrade", "withdraw")
        for index, outcome in enumerate(outcomes):
            with self.subTest(revision_outcome=outcome):
                if index:
                    self._reset_harness()
                    self._activate_synthetic_scope_through_ticket119()
                effect_id, _ = self._prepare_and_execute_model(
                    source_suffix=f"revision-{outcome}"
                )
                root = self._health(
                    "diagnosis.commit",
                    {
                        "commit_kind": "diagnostic-judgment",
                        "source_causal_id": f"ticket116-diagnostic-source:revision-{outcome}",
                        "model_effect_id": effect_id,
                    },
                    suffix=f"revision-{outcome}",
                )
                self.assertEqual(root.get("status"), "committed", root)
                root_ref = root["diagnosis_ref"]
                revision = self._health(
                    "diagnosis.correct",
                    {
                        "diagnosis_ref": root_ref,
                        "correction_ref": f"owner-correction:{outcome}",
                        "corrected_at_utc": "2026-08-24T03:40:00+00:00",
                        "outcome": outcome,
                        "reason": "owner-corrected-measurement",
                    },
                    suffix=f"owner-correction-{outcome}",
                )
                self.assertEqual(
                    revision.get("status"),
                    "no-change" if outcome == "no-change" else "revised",
                    revision,
                )
                self.assertEqual(revision.get("outcome"), outcome)
                managed = [
                    item
                    for item in self._managed_read()["diagnoses"]
                    if item["question_ref"] == "question:synthetic-bmi"
                    and item["event_ref"] == "event:synthetic-measurement"
                    and item["applicable_period"] == "2026-08-24"
                ]
                self.assertLessEqual(
                    sum(1 for item in managed if item["current"] is True),
                    1,
                )
                old = next(
                    item for item in managed if item["diagnosis_ref"] == root_ref
                )
                if outcome == "no-change":
                    self.assertTrue(old["current"])
                    self.assertEqual(
                        [
                            item
                            for item in managed
                            if item.get("predecessor_ref") == root_ref
                        ],
                        [],
                    )
                else:
                    self.assertFalse(old["current"])
                    self.assertEqual(
                        old["exit_reason"],
                        "owner-corrected-measurement",
                    )
                    successors = [
                        item
                        for item in managed
                        if item.get("predecessor_ref") == root_ref
                    ]
                    self.assertEqual(len(successors), 1)
                    successor = successors[0]
                    self.assertEqual(successor["outcome"], outcome)
                    self.assertEqual(
                        successor["correction_ref"],
                        f"owner-correction:{outcome}",
                    )
                    self.assertEqual(
                        successor["current"],
                        outcome in {"replace", "degrade"},
                    )

        stable_before_unknown = self._managed_read()
        self.base.head.set_failure(FailureMode.UNKNOWN, operation="read")
        uncertain = self._managed_read()
        self.base.head.clear_failure()
        self.assertEqual(uncertain["current_judgment_status"], "cannot-confirm")
        self.assertFalse(
            any(item["current"] is True for item in uncertain["diagnoses"])
        )
        self._restart_with_assets(self._synthetic_assets(scope_state="staged"))
        self.assertEqual(self._managed_read(), stable_before_unknown)

        self._reset_harness()
        self._activate_synthetic_scope_through_ticket119()
        invalidation_question = "question:synthetic-scope-invalidation"
        invalidation_event = "event:synthetic-scope-invalidation"
        invalidation_period = "2026-08-25"
        root_effect_id, _ = self._prepare_and_execute_model(
            source_suffix="scope-invalidation-root",
            question_ref=invalidation_question,
            event_ref=invalidation_event,
            applicable_period=invalidation_period,
        )
        invalidation_root = self._health(
            "diagnosis.commit",
            {
                "commit_kind": "diagnostic-judgment",
                "source_causal_id": (
                    "ticket116-diagnostic-source:scope-invalidation-root"
                ),
                "model_effect_id": root_effect_id,
            },
            suffix="scope-invalidation-root",
        )
        self.assertEqual(
            invalidation_root.get("status"),
            "committed",
            invalidation_root,
        )
        invalidation_root_ref = invalidation_root["diagnosis_ref"]

        rerun_effect_id, rerun_adapter = self._prepare_and_execute_model(
            source_suffix="scope-invalidation-rerun",
            question_ref=invalidation_question,
            event_ref=invalidation_event,
            applicable_period=invalidation_period,
        )
        self._health(
            "diagnosis.commit",
            {
                "commit_kind": "diagnostic-judgment",
                "source_causal_id": (
                    "ticket116-diagnostic-source:scope-invalidation-rerun"
                ),
                "model_effect_id": rerun_effect_id,
            },
            suffix="scope-invalidation-rerun",
        )
        self.assertEqual(rerun_adapter.calls, 1)
        before_invalidation = [
            item
            for item in self._managed_read()["diagnoses"]
            if item["question_ref"] == invalidation_question
            and item["event_ref"] == invalidation_event
            and item["applicable_period"] == invalidation_period
        ]
        self.assertEqual(len(before_invalidation), 1)
        self.assertEqual(
            before_invalidation[0]["diagnosis_ref"],
            invalidation_root_ref,
        )
        self.assertTrue(before_invalidation[0]["current"])

        self._restart_with_assets(
            self._synthetic_assets(
                diagnostic_prerequisites_current=False,
                scope_state="staged",
            )
        )
        after_invalidation = [
            item
            for item in self._managed_read()["diagnoses"]
            if item["question_ref"] == invalidation_question
            and item["event_ref"] == invalidation_event
            and item["applicable_period"] == invalidation_period
        ]
        self.assertEqual(len(after_invalidation), 2)
        invalidated_root = next(
            item
            for item in after_invalidation
            if item["diagnosis_ref"] == invalidation_root_ref
        )
        self.assertFalse(invalidated_root["current"])
        invalidation_successors = [
            item
            for item in after_invalidation
            if item.get("predecessor_ref") == invalidation_root_ref
        ]
        self.assertEqual(len(invalidation_successors), 1)
        self.assertLessEqual(
            sum(item["current"] is True for item in after_invalidation),
            1,
        )
        invalidation_successor_ref = invalidation_successors[0]["diagnosis_ref"]

        # Scope recovery is not evidence that the withdrawn judgment became
        # current again.  The invalidation successor is a durable revision and
        # must survive both asset restoration and process restart.
        self._restart_with_assets(
            self._synthetic_assets(
                diagnostic_prerequisites_current=True,
                scope_state="active",
            )
        )
        after_restoration = [
            item
            for item in self._managed_read()["diagnoses"]
            if item["question_ref"] == invalidation_question
            and item["event_ref"] == invalidation_event
            and item["applicable_period"] == invalidation_period
        ]
        restored_root = next(
            item
            for item in after_restoration
            if item["diagnosis_ref"] == invalidation_root_ref
        )
        self.assertFalse(restored_root["current"])
        restored_successors = [
            item
            for item in after_restoration
            if item.get("predecessor_ref") == invalidation_root_ref
        ]
        self.assertEqual(len(restored_successors), 1)
        self.assertEqual(
            restored_successors[0]["diagnosis_ref"],
            invalidation_successor_ref,
        )
        self.assertFalse(any(item["current"] is True for item in after_restoration))

    def test_v116_09_contact_failure_never_suppresses_owner_result_or_self_approves(self) -> None:
        """Break caught: the Ticket 116 consumer writes its own contact authority."""

        self._restart_with_assets(self._synthetic_assets())
        states = ("missing", "method", "revoke", "pause", "generation")
        for index, state in enumerate(states):
            with self.subTest(contact_authority=state):
                if index:
                    self._reset_harness()
                self._restart_with_assets(self._synthetic_assets())
                if state != "missing":
                    self._configure_synthetic_contact()
                    self._grant_contact_authority()
                    if state == "method":
                        self._change_synthetic_contact_method()
                    elif state == "revoke":
                        self._apply_contact_control("revoke_alert_authority")
                    elif state == "pause":
                        self._grant_contact_authority(correction=True)
                        self._apply_contact_control("pause")
                    elif state == "generation":
                        current = self.plugin.owner_settings_state(
                            peer_id=_PEER
                        ).support_contact
                        assert current is not None
                        self._change_synthetic_contact_method(
                            route_generation=current.route_generation + 1
                        )
                before = self.plugin.managed_owner_settings_read(peer_id=_PEER)[
                    "support_contact"
                ]
                result = self._health(
                    "safety.evaluate",
                    {
                        "source_causal_id": f"ticket116-safety:contact-{state}",
                        "safety_rule_bundle_hash": self.safety_bundle_hash,
                        "facts": {
                            "safety_capability": "available",
                            "danger": "confirmed",
                            "scope": "in-scope",
                        },
                    },
                    suffix=f"contact-{state}",
                )
                after = self.plugin.managed_owner_settings_read(peer_id=_PEER)[
                    "support_contact"
                ]
                self.assertEqual(result.get("branch"), "danger-escalation", result)
                self.assertEqual(
                    result["owner_result"]["template_ref"],
                    _DANGER_TEMPLATE_REF,
                )
                self.assertIsNone(result["contact_alert"])
                self.assertEqual(after, before)
                if state != "pause":
                    self.assertNotEqual(
                        before.get("alert_authority_status"),
                        "approved",
                    )
                    continue
                self.assertEqual(before["alert_authority_status"], "approved")
                self.assertEqual(before["correction_authority_status"], "approved")
                self._apply_contact_control("resume")
                resumed = self.plugin.managed_owner_settings_read(peer_id=_PEER)[
                    "support_contact"
                ]
                self.assertFalse(resumed["dedicated_paused"])
                self.assertEqual(resumed["alert_authority_status"], "approved")
                self.assertEqual(resumed["correction_authority_status"], "approved")
                resumed_result = self._health(
                    "safety.evaluate",
                    {
                        "source_causal_id": "ticket116-safety:dedicated-resume",
                        "event_time": "2026-08-24T03:46:00+00:00",
                        "owner_recognizable_name": "合成主人称呼",
                        "safety_rule_bundle_hash": self.safety_bundle_hash,
                        "facts": {
                            "safety_capability": "available",
                            "danger": "confirmed",
                            "scope": "in-scope",
                        },
                    },
                    suffix="dedicated-resume",
                )
                self.assertIsNotNone(resumed_result["contact_alert"])

    def test_v116_10_contact_unknown_freezes_retry_and_correction_stays_original(self) -> None:
        """Break caught: unknown alert retries or correction changes recipient."""

        self._restart_with_assets(self._synthetic_assets())
        self._configure_synthetic_contact()
        self._grant_contact_authority()
        self._grant_contact_authority(correction=True)
        formed = self._health(
            "safety.evaluate",
            {
                "source_causal_id": "ticket116-safety:contact-unknown",
                "event_time": "2026-08-24T03:50:00+00:00",
                "owner_recognizable_name": "合成主人称呼",
                "safety_rule_bundle_hash": self.safety_bundle_hash,
                "facts": {
                    "safety_capability": "available",
                    "danger": "confirmed",
                    "scope": "in-scope",
                },
            },
            suffix="contact-unknown",
        )
        intent_id, grant = self._contact_effect_grant(formed["contact_alert"])
        attempted_at = "2026-08-24T03:50:01+00:00"
        unknown_adapter = _ContactAdapter(raises_after_accepting=True)
        unknown = self._controlled(
            "contact-alert.execute",
            {
                "intent_id": intent_id,
                "attempted_at_utc": attempted_at,
                "observed_at_utc": "2026-08-24T03:50:02+00:00",
            },
            grant=grant,
            transport=unknown_adapter,
        )
        self.assertEqual(unknown_adapter.calls, 1)
        alert_wire = unknown_adapter.wires[0]["contact_alert"]
        self.assertEqual(
            frozenset(alert_wire),
            frozenset(
                {
                    "owner_recognizable_name",
                    "event_time",
                    "fixed_urgent_help_request",
                }
            ),
        )
        self.assertEqual(unknown["transport_result"]["status"], "unknown")

        extra_formed = self._health(
            "safety.evaluate",
            {
                "source_causal_id": "ticket116-safety:contact-extra-field",
                "event_time": "2026-08-24T03:50:05+00:00",
                "owner_recognizable_name": "合成主人称呼",
                "safety_rule_bundle_hash": self.safety_bundle_hash,
                "facts": {
                    "safety_capability": "available",
                    "danger": "confirmed",
                    "scope": "in-scope",
                },
            },
            suffix="contact-extra-field",
        )
        extra_intent_id, extra_grant = self._contact_effect_grant(
            extra_formed["contact_alert"]
        )
        extra_adapter = _ContactAdapter()
        with self.assertRaises(ProtocolViolation):
            self.plugin.controlled_effect(
                "contact-alert.execute",
                {
                    "intent_id": extra_intent_id,
                    "attempted_at_utc": "2026-08-24T03:50:10+00:00",
                    "observed_at_utc": "2026-08-24T03:50:11+00:00",
                    "health_body": "FORBIDDEN-EXTRA-FIELD",
                },
                grant=extra_grant,  # type: ignore[arg-type]
                transport=extra_adapter,
                peer_id=_PEER,
            )
        self.assertEqual(extra_adapter.calls, 0)

        retry_adapter = _ContactAdapter()
        replay = self._controlled(
            "contact-alert.execute",
            {
                "intent_id": intent_id,
                "attempted_at_utc": "2026-08-24T03:51:00+00:00",
                "observed_at_utc": "2026-08-24T03:51:01+00:00",
            },
            grant=grant,
            transport=retry_adapter,
        )
        self.assertEqual(retry_adapter.calls, 0)
        self.assertEqual(replay["transport_result"]["status"], "unknown")

        original_destination = unknown_adapter.wires[0]["destination"]
        # Dedicated support pause suppresses new ordinary alerts.  It cannot
        # suppress the necessary correction for an alert that may already have
        # left the system, and that correction remains bound to the original
        # destination.
        self._apply_contact_control("pause")
        correction = self._health(
            "safety.correct",
            {
                "source_alert_intent_id": intent_id,
                "basis_change_ref": "owner-correction:danger-no-longer-current",
                "corrected_at_utc": "2026-08-24T03:52:00+00:00",
            },
            suffix="contact-correction",
        )
        correction_id, correction_grant = self._contact_effect_grant(
            correction["contact_correction"],
        )
        correction_adapter = _ContactAdapter()
        sent_correction = self._controlled(
            "contact-alert.execute",
            {
                "intent_id": correction_id,
                "attempted_at_utc": "2026-08-24T03:52:01+00:00",
                "observed_at_utc": "2026-08-24T03:52:02+00:00",
            },
            grant=correction_grant,
            transport=correction_adapter,
        )
        self.assertEqual(correction_adapter.calls, 1)
        self.assertEqual(
            correction_adapter.wires[0]["destination"],
            original_destination,
        )
        correction_replay_adapter = _ContactAdapter()
        replayed_correction = self._controlled(
            "contact-alert.execute",
            {
                "intent_id": correction_id,
                "attempted_at_utc": "2026-08-24T03:52:03+00:00",
                "observed_at_utc": "2026-08-24T03:52:04+00:00",
            },
            grant=correction_grant,
            transport=correction_replay_adapter,
        )
        self.assertEqual(correction_replay_adapter.calls, 0)
        self.assertEqual(
            replayed_correction["transport_result"],
            sent_correction["transport_result"],
        )

        # A currentness change after an unknown departure makes correction a
        # truthful no-send; it may not retarget the new contact method.
        self._reset_harness()
        self._restart_with_assets(self._synthetic_assets())
        self._configure_synthetic_contact()
        self._grant_contact_authority()
        self._grant_contact_authority(correction=True)
        changed_formed = self._health(
            "safety.evaluate",
            {
                "source_causal_id": "ticket116-safety:authority-change",
                "event_time": "2026-08-24T04:00:00+00:00",
                "owner_recognizable_name": "合成主人称呼",
                "safety_rule_bundle_hash": self.safety_bundle_hash,
                "facts": {
                    "safety_capability": "available",
                    "danger": "confirmed",
                    "scope": "in-scope",
                },
            },
            suffix="contact-authority-change",
        )
        changed_id, changed_grant = self._contact_effect_grant(
            changed_formed["contact_alert"]
        )
        changed_unknown_adapter = _ContactAdapter(raises_after_accepting=True)
        self._controlled(
            "contact-alert.execute",
            {
                "intent_id": changed_id,
                "attempted_at_utc": "2026-08-24T04:00:01+00:00",
                "observed_at_utc": "2026-08-24T04:00:02+00:00",
            },
            grant=changed_grant,
            transport=changed_unknown_adapter,
        )
        self._change_synthetic_contact_method()
        undeliverable = self._health(
            "safety.correct",
            {
                "source_alert_intent_id": changed_id,
                "basis_change_ref": "owner-correction:authority-changed",
                "corrected_at_utc": "2026-08-24T04:01:00+00:00",
            },
            suffix="contact-correction-authority-changed",
        )
        self.assertIsNone(undeliverable.get("contact_correction"))
        self.assertEqual(
            undeliverable.get("contact_outcome"),
            "correction-undeliverable",
        )

        # A transport rejection proves no departure, so no correction effect
        # may be formed even while authority remains current.
        self._reset_harness()
        self._restart_with_assets(self._synthetic_assets())
        self._configure_synthetic_contact()
        self._grant_contact_authority()
        self._grant_contact_authority(correction=True)
        rejected_formed = self._health(
            "safety.evaluate",
            {
                "source_causal_id": "ticket116-safety:no-departure",
                "event_time": "2026-08-24T04:10:00+00:00",
                "owner_recognizable_name": "合成主人称呼",
                "safety_rule_bundle_hash": self.safety_bundle_hash,
                "facts": {
                    "safety_capability": "available",
                    "danger": "confirmed",
                    "scope": "in-scope",
                },
            },
            suffix="contact-no-departure",
        )
        rejected_id, rejected_grant = self._contact_effect_grant(
            rejected_formed["contact_alert"]
        )
        rejected_adapter = _ContactAdapter(status="rejected")
        rejected_result = self._controlled(
            "contact-alert.execute",
            {
                "intent_id": rejected_id,
                "attempted_at_utc": "2026-08-24T04:10:01+00:00",
                "observed_at_utc": "2026-08-24T04:10:02+00:00",
            },
            grant=rejected_grant,
            transport=rejected_adapter,
        )
        self.assertEqual(rejected_result["transport_result"]["status"], "rejected")
        no_departure = self._health(
            "safety.correct",
            {
                "source_alert_intent_id": rejected_id,
                "basis_change_ref": "owner-correction:no-departure",
                "corrected_at_utc": "2026-08-24T04:11:00+00:00",
            },
            suffix="contact-correction-no-departure",
        )
        self.assertIsNone(no_departure.get("contact_correction"))

    def test_v116_11_stop_recording_keeps_only_body_free_safety_delivery_facts(self) -> None:
        """Break caught: temporary safety handling persists or later backfills body."""

        self._restart_with_assets(self._synthetic_assets())
        self._configure_synthetic_contact()
        self._grant_contact_authority()
        self._stop_recording()
        before_daily = self.plugin.daily_state(peer_id=_PEER)
        before_managed = self._managed_read()
        before_tasks = self.plugin.managed_ticket115_read(peer_id=_PEER)["tasks"]
        before_evidence = before_daily.evidence_cards
        body = CountingBody("SYNTHETIC:DANGER_CONFIRMED")
        message = self._message(body, suffix="recording-stopped-danger")

        first = self.plugin.receive_weixin(message, peer_id=_PEER)
        self._restart_with_assets(self._synthetic_assets())
        replay = self.plugin.receive_weixin(message, peer_id=_PEER)

        first_meta = self._meta_wire(first)
        replay_meta = self._meta_wire(replay)
        self.assertEqual(first_meta["branch"], "danger-escalation")
        self.assertEqual(
            first_meta["owner_result"]["template_ref"],
            _DANGER_TEMPLATE_REF,
        )
        self.assertEqual(
            replay_meta["contact_alert"]["intent_id"],
            first_meta["contact_alert"]["intent_id"],
        )
        receipt = self.plugin.source_receipt(message.causal_id, peer_id=_PEER)
        self.assertIsNotNone(receipt)
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(self.plugin.daily_state(peer_id=_PEER), before_daily)
        self.assertEqual(
            self.plugin.daily_state(peer_id=_PEER).evidence_cards,
            before_evidence,
        )
        self.assertEqual(
            self.plugin.managed_ticket115_read(peer_id=_PEER)["tasks"],
            before_tasks,
        )
        after_managed = self._managed_read()
        self.assertEqual(after_managed["diagnoses"], before_managed["diagnoses"])
        self.assertEqual(
            after_managed["safety_events"],
            before_managed["safety_events"],
        )
        self.assertNotIn("SYNTHETIC:DANGER_CONFIRMED", repr(after_managed))
        self._resume_recording()
        self.assertEqual(self.plugin.daily_state(peer_id=_PEER), before_daily)
        self.assertEqual(
            self.plugin.daily_state(peer_id=_PEER).evidence_cards,
            before_evidence,
        )
        self.assertEqual(
            self.plugin.managed_ticket115_read(peer_id=_PEER)["tasks"],
            before_tasks,
        )
        resumed = self._managed_read()
        self.assertEqual(resumed["diagnoses"], before_managed["diagnoses"])
        self.assertEqual(resumed["safety_events"], before_managed["safety_events"])

    def test_v116_12_status_uses_typed_safety_and_diagnostic_scope_facts(self) -> None:
        """Break caught: staged scope or missing contact falsely reports active."""

        self._restart_with_assets(self._synthetic_assets())
        staged = self.plugin.business_status(peer_id=_PEER).projection
        staged_scope = self._managed_read()["scope"]
        self.assertNotEqual(staged.state, "active")
        self.assertEqual(staged_scope["persistent_state"], "staged")
        self.assertEqual(staged_scope["effective_phase"], "activation-ready")
        self.assertIn("diagnostic_scope", staged.affected_core_domains)
        self.assertNotIn("safety", staged.affected_core_domains)
        self.assertFalse(
            any("missing" in reason and "safety" in reason for reason in staged.reason_codes)
        )

        contact_unavailable = self._health(
            "safety.evaluate",
            {
                "source_causal_id": "ticket116-safety:contact-unavailable-status",
                "safety_rule_bundle_hash": self.safety_bundle_hash,
                "facts": {
                    "safety_capability": "available",
                    "danger": "confirmed",
                    "scope": "in-scope",
                },
            },
            suffix="contact-unavailable-status",
        )
        self.assertEqual(
            contact_unavailable["owner_result"]["template_ref"],
            _DANGER_TEMPLATE_REF,
        )
        self.assertIsNone(contact_unavailable["contact_alert"])
        contact_status = self.plugin.business_status(peer_id=_PEER).projection
        self.assertNotIn("safety", contact_status.affected_core_domains)
        self.assertTrue(
            any(
                "contact" in value or "delivery" in value
                for value in (
                    *contact_status.affected_core_domains,
                    *contact_status.reason_codes,
                )
            ),
            contact_status,
        )

        self._restart_with_assets(
            self._synthetic_assets(safety_rules_current=False)
        )
        failed = self.plugin.business_status(peer_id=_PEER).projection
        self.assertEqual(failed.state, "abnormal")
        self.assertIn("safety", failed.affected_core_domains)
        self.assertIn("diagnostic_scope", failed.affected_core_domains)


if __name__ == "__main__":
    unittest.main()

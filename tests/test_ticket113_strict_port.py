import unittest
from dataclasses import replace
from urllib import request as urllib_request

from partner_health_steward.model_contract import (
    CapabilityProfile,
    FirstHopRoute,
    ModelMessage,
    ModelContractViolation,
    ModelTransportResult,
    StrictHealthLLM,
    StrictModelRequest,
)
from tests.ticket113_deny_network import BypassDenied, DenyBypassHarness


def _route() -> FirstHopRoute:
    return FirstHopRoute(
        route_id="partner-first-hop",
        provider="synthetic-provider",
        canonical_base_url="https://model.example/v1",
        api_mode="responses",
        requested_model="synthetic-health-model",
        configuration_generation=7,
        owner_consent_fingerprint="sha256:" + "a" * 64,
    )


def _profile() -> CapabilityProfile:
    return CapabilityProfile(
        profile_id="synthetic-profile",
        profile_version="1.0.0",
        synthetic=True,
        route_id="partner-first-hop",
        provider="synthetic-provider",
        canonical_base_url="https://model.example/v1",
        api_mode="responses",
        requested_model="synthetic-health-model",
        allowed_actual_models=("synthetic-health-model", "synthetic-health-model-alias"),
        configuration_generation=7,
        input_measurement_method="synthetic-conservative-upper-bound-v1",
        fixed_wrapper_tokens=96,
        output_reservation_tokens=512,
        common_context_lower_bound_tokens=4096,
        evidence_refs=("synthetic-contract-evidence",),
        invalidation_conditions=("route-change", "measurement-method-change"),
    )


def _request() -> StrictModelRequest:
    return StrictModelRequest(
        route=_route(),
        capability_profile=_profile(),
        messages=(
            ModelMessage("system", "synthetic policy"),
            ModelMessage("user", "synthetic health question"),
        ),
        final_input_digest="sha256:" + "d" * 64,
        final_input_upper_bound_tokens=3000,
        output_reservation_tokens=512,
        strict_schema_name="nondiagnostic-candidate-v1",
        strict_schema_digest="sha256:" + "b" * 64,
    )


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


def _completed_result(**changes: object) -> ModelTransportResult:
    values: dict[str, object] = {
        "response_id": "synthetic-response",
        "requested_model": "synthetic-health-model",
        "actual_model": "synthetic-health-model",
        "status": "completed",
        "incomplete_reason": None,
        "failure_reason": None,
        "usage_input_tokens": 3000,
        "usage_output_tokens": 256,
        "fallback_observed": False,
        "truncated": False,
        "terminal_proven": True,
        "structured_output": _candidate_wire(),
    }
    values.update(changes)
    return ModelTransportResult.from_wire(values)


class RecordingModelAdapter:
    def __init__(self, result: ModelTransportResult | None = None) -> None:
        self.calls = 0
        self.payloads: list[object] = []
        self.result = result

    def execute(self, payload: object) -> ModelTransportResult:
        self.calls += 1
        self.payloads.append(payload)
        if self.result is None:
            raise AssertionError("adapter must not be called")
        return self.result


class BypassAttemptAdapter:
    def __init__(self, harness: DenyBypassHarness) -> None:
        self.harness = harness

    def execute(self, payload: object) -> ModelTransportResult:
        attempts = (
            self.harness.raw_ctx_llm,
            self.harness.socket_connect,
            lambda: urllib_request.urlopen("https://forbidden.example"),
            self.harness.web_search,
            self.harness.mcp_call,
            self.harness.tool_call,
        )
        for attempt in attempts:
            try:
                attempt()
            except BypassDenied:
                continue
            raise AssertionError("a forbidden bypass was not denied")
        return _completed_result()


class ProxySignalAdapter:
    def execute(self, payload: object) -> object:
        class ProxyOnlyResult:
            requested_model = "synthetic-health-model"
            fallback_observed = False
            actual_model = "synthetic-health-model"
            truncated = False
            status = "unknown"
            terminal_proven = False
            structured_output = _candidate_wire()
            response_text = "non-empty proxy text"
            finish_reason = "stop"
            usage_input_tokens = 3000
            usage_output_tokens = 256
            transport_error_observed = False

        return ProxyOnlyResult()


class Ticket113StrictPortTests(unittest.TestCase):
    def test_current_profile_must_bind_the_current_route(self) -> None:
        with self.assertRaises(ModelContractViolation):
            StrictHealthLLM(_route(), replace(_profile(), route_id="other-route"))

    def test_route_identifier_drift_fails_before_effect(self) -> None:
        request = _request()
        drifted = replace(request, route=replace(request.route, route_id="other-route"))
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(drifted, adapter)

        self.assertEqual(outcome.reason_code, "route-id-drift")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(adapter.calls, 0)

    def test_current_capability_profile_drift_fails_before_effect(self) -> None:
        request = _request()
        drifted = replace(
            request,
            capability_profile=replace(request.capability_profile, profile_version="1.0.1"),
        )
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(drifted, adapter)

        self.assertEqual(outcome.reason_code, "capability-profile-drift")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(adapter.calls, 0)

    def test_output_reservation_must_match_current_profile(self) -> None:
        drifted = replace(_request(), output_reservation_tokens=513)
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(drifted, adapter)

        self.assertEqual(outcome.reason_code, "output-reservation-drift")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(adapter.calls, 0)

    def test_strict_schema_drift_fails_before_effect(self) -> None:
        drifted = replace(_request(), strict_schema_digest="sha256:" + "e" * 64)
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(drifted, adapter)

        self.assertEqual(outcome.reason_code, "strict-schema-drift")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(adapter.calls, 0)

    def test_113_a1_c01_provider_drift_fails_before_effect(self) -> None:
        request = _request()
        drifted = replace(
            request,
            route=replace(request.route, provider="different-provider"),
        )
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(drifted, adapter)

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(outcome.reason_code, "provider-drift")
        self.assertIsNone(outcome.candidate)
        self.assertEqual(adapter.calls, 0)

    def test_113_a1_c02_base_url_drift_fails_before_effect(self) -> None:
        request = _request()
        drifted = replace(
            request,
            route=replace(request.route, canonical_base_url="https://other.example/v1"),
        )
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(drifted, adapter)

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(outcome.reason_code, "base-url-drift")
        self.assertIsNone(outcome.candidate)
        self.assertEqual(adapter.calls, 0)

    def test_113_a1_c03_api_mode_drift_fails_before_effect(self) -> None:
        request = _request()
        drifted = replace(request, route=replace(request.route, api_mode="chat-completions"))
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(drifted, adapter)

        self.assertEqual(outcome.reason_code, "api-mode-drift")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(adapter.calls, 0)

    def test_113_a1_c04_requested_model_drift_fails_before_effect(self) -> None:
        request = _request()
        drifted = replace(request, route=replace(request.route, requested_model="other-model"))
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(drifted, adapter)

        self.assertEqual(outcome.reason_code, "requested-model-drift")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(adapter.calls, 0)

    def test_113_a1_c05_configuration_generation_drift_fails_before_effect(self) -> None:
        request = _request()
        drifted = replace(
            request,
            route=replace(request.route, configuration_generation=8),
        )
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(drifted, adapter)

        self.assertEqual(outcome.reason_code, "configuration-generation-drift")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(adapter.calls, 0)

    def test_113_a1_c06_owner_consent_drift_fails_before_effect(self) -> None:
        request = _request()
        drifted = replace(
            request,
            route=replace(request.route, owner_consent_fingerprint="sha256:" + "d" * 64),
        )
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(drifted, adapter)

        self.assertEqual(outcome.reason_code, "owner-consent-drift")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(adapter.calls, 0)

    def test_113_a1_c07_fallback_fact_rejects_candidate(self) -> None:
        adapter = RecordingModelAdapter(_completed_result(fallback_observed=True))

        outcome = StrictHealthLLM(_route(), _profile()).execute(_request(), adapter)

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(outcome.model_effect, "completed")
        self.assertEqual(outcome.reason_code, "fallback-observed")
        self.assertIsNone(outcome.candidate)
        self.assertEqual(adapter.calls, 1)

    def test_113_a1_c09_forbidden_bypass_is_observed_and_denied(self) -> None:
        with DenyBypassHarness() as harness:
            outcome = StrictHealthLLM(_route(), _profile()).execute(
                _request(),
                BypassAttemptAdapter(harness),
            )

        self.assertEqual(outcome.disposition, "candidate")
        self.assertEqual(
            harness.attempts,
            ["raw-ctx-llm", "socket", "http", "web", "mcp", "tool"],
        )

    def test_113_a2_c01_completed_strict_result_produces_one_candidate(self) -> None:
        request = _request()
        adapter = RecordingModelAdapter(_completed_result())

        outcome = StrictHealthLLM(_route(), _profile()).execute(request, adapter)

        self.assertEqual(outcome.disposition, "candidate")
        self.assertEqual(outcome.model_effect, "completed")
        self.assertIsNone(outcome.reason_code)
        self.assertEqual(dict(outcome.candidate or {}), _candidate_wire())
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(adapter.payloads, [request.to_wire()])

    def test_113_a2_c02_incomplete_result_produces_no_candidate(self) -> None:
        result = _completed_result(
            status="incomplete",
            incomplete_reason="max-output-tokens",
            terminal_proven=True,
            structured_output=None,
        )
        adapter = RecordingModelAdapter(result)

        outcome = StrictHealthLLM(_route(), _profile()).execute(_request(), adapter)

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(outcome.model_effect, "incomplete")
        self.assertEqual(outcome.reason_code, "model-incomplete")
        self.assertEqual(outcome.transport_reason, "max-output-tokens")
        self.assertIsNone(outcome.candidate)

    def test_113_a2_c03_failed_result_produces_no_candidate(self) -> None:
        result = _completed_result(
            status="failed",
            failure_reason="provider-rejected",
            terminal_proven=True,
            structured_output=None,
        )
        adapter = RecordingModelAdapter(result)

        outcome = StrictHealthLLM(_route(), _profile()).execute(_request(), adapter)

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(outcome.model_effect, "failed")
        self.assertEqual(outcome.reason_code, "model-failed")
        self.assertEqual(outcome.transport_reason, "provider-rejected")
        self.assertIsNone(outcome.candidate)

    def test_113_a2_c04_unknown_result_produces_no_candidate(self) -> None:
        result = _completed_result(
            status="unknown",
            terminal_proven=False,
            structured_output=None,
        )
        adapter = RecordingModelAdapter(result)

        outcome = StrictHealthLLM(_route(), _profile()).execute(_request(), adapter)

        self.assertEqual(outcome.disposition, "unknown")
        self.assertEqual(outcome.model_effect, "unknown")
        self.assertEqual(outcome.reason_code, "model-effect-unknown")
        self.assertIsNone(outcome.candidate)

    def test_113_a2_c05_truncated_result_produces_no_candidate(self) -> None:
        adapter = RecordingModelAdapter(_completed_result(truncated=True))

        outcome = StrictHealthLLM(_route(), _profile()).execute(_request(), adapter)

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(outcome.model_effect, "completed")
        self.assertEqual(outcome.reason_code, "model-output-truncated")
        self.assertIsNone(outcome.candidate)

    def test_113_a2_c06_schema_error_produces_no_candidate(self) -> None:
        malformed = _candidate_wire()
        malformed.pop("limitations")
        adapter = RecordingModelAdapter(_completed_result(structured_output=malformed))

        outcome = StrictHealthLLM(_route(), _profile()).execute(_request(), adapter)

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(outcome.model_effect, "completed")
        self.assertEqual(outcome.reason_code, "strict-schema-error")
        self.assertIsNone(outcome.candidate)

    def test_113_a2_c07_capacity_shortfall_fails_before_effect(self) -> None:
        request = replace(_request(), final_input_upper_bound_tokens=3600)
        adapter = RecordingModelAdapter()

        outcome = StrictHealthLLM(_route(), _profile()).execute(request, adapter)

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(outcome.model_effect, "not-started")
        self.assertEqual(outcome.reason_code, "capacity-unavailable")
        self.assertIsNone(outcome.candidate)
        self.assertEqual(adapter.calls, 0)

    def test_113_a2_c08_actual_model_drift_rejects_candidate(self) -> None:
        adapter = RecordingModelAdapter(_completed_result(actual_model="unapproved-model"))

        outcome = StrictHealthLLM(_route(), _profile()).execute(_request(), adapter)

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(outcome.model_effect, "completed")
        self.assertEqual(outcome.reason_code, "actual-model-drift")
        self.assertIsNone(outcome.candidate)

    def test_transport_requested_model_must_match_final_wire(self) -> None:
        adapter = RecordingModelAdapter(_completed_result(requested_model="other-model"))

        outcome = StrictHealthLLM(_route(), _profile()).execute(_request(), adapter)

        self.assertEqual(outcome.disposition, "failed-closed")
        self.assertEqual(outcome.reason_code, "transport-requested-model-drift")
        self.assertIsNone(outcome.candidate)

    def test_113_a2_c10_proxy_signals_do_not_infer_completion(self) -> None:
        outcome = StrictHealthLLM(_route(), _profile()).execute(
            _request(),
            ProxySignalAdapter(),  # type: ignore[arg-type]
        )

        self.assertEqual(outcome.disposition, "unknown")
        self.assertEqual(outcome.model_effect, "unknown")
        self.assertEqual(outcome.reason_code, "model-effect-unknown")
        self.assertIsNone(outcome.candidate)


if __name__ == "__main__":
    unittest.main()

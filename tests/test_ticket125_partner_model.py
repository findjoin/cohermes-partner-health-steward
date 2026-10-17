"""Independent Ticket 125 gates; all external effects use offline transports.

The evidence below is explicitly a verifier fixture, never a target profile.
No production methods are patched and no real model or credential is read.
"""

from __future__ import annotations

import copy
import importlib
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from partner_health_steward.contract import EffectRequestPayload
from partner_health_steward.core import HealthCore
from partner_health_steward.coordination import CoarseMessageRouter
from partner_health_steward.initialization import stable_digest
from partner_health_steward.knowledge import (
    KnowledgeContractViolation, KnowledgeGap, KnowledgePublisher, KnowledgeRelease,
)
from partner_health_steward.model_contract import (
    CapabilityProfile, FirstHopRoute, ModelContractViolation, ModelMessage,
    ModelTransportResult, StrictHealthLLM, StrictModelRequest,
)
from partner_health_steward.plugin import HealthPlugin
from tests import test_ticket113_authority_integration as authority_fixture
from tests.test_ticket113_knowledge import _publication
from tests.ticket113_deny_network import DenyBypassHarness


_NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
_METHOD = "responses-final-wire-utf8-upper-bound-v1"
_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"verifier_result": {"type": "string"}},
    "required": ["verifier_result"],
}
_SCHEMA_NAME = "ticket125-offline-verifier-result-v1"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _string_leaves(value):
    if type(value) is str:
        yield value
    elif type(value) is dict:
        for item in value.values():
            yield from _string_leaves(item)
    elif type(value) is list:
        for item in value:
            yield from _string_leaves(item)


def _route() -> FirstHopRoute:
    return FirstHopRoute(
        "ticket125-fixture-route", "verifier-offline-provider",
        "https://offline.invalid/v1", "codex_responses", "offline-fixture-model",
        25, "sha256:" + "a" * 64,
    )


def _profile_and_evidence():
    route = _route()
    profile = CapabilityProfile(
        profile_id="ticket125-offline-fixture-profile", profile_version="1",
        synthetic=False, route_id=route.route_id, provider=route.provider,
        canonical_base_url=route.canonical_base_url, api_mode=route.api_mode,
        requested_model=route.requested_model,
        allowed_actual_models=(route.requested_model, "offline-fixture-alias"),
        configuration_generation=route.configuration_generation,
        input_measurement_method=_METHOD, fixed_wrapper_tokens=64,
        output_reservation_tokens=512, common_context_lower_bound_tokens=32768,
        evidence_refs=("verifier-fixture-only",),
        invalidation_conditions=("route-change", "approval-expired"),
    )
    bound = profile.to_wire()
    bound.pop("evidence_refs")
    evidence = {
        "contract": "ticket125-model-measurement-evidence-v1",
        "profile_binding_digest": stable_digest(bound),
        "schema_digest": stable_digest(_SCHEMA),
        "wire_builder_version": "responses-fixed-wire-v1",
        "method_id": _METHOD,
        "issued_at": "2026-08-31T00:00:00+00:00",
        "expires_at": "2026-09-02T00:00:00+00:00",
        "capacity_evidence_ref": "verifier-fixture:common-window-not-target",
        "tokenizer_evidence_ref": "verifier-fixture:byte-bound-not-target",
        "approval_ref": "verifier-fixture:g10-approval-not-target",
    }
    return replace(profile, evidence_refs=(stable_digest(evidence),)), evidence


def _request(profile: CapabilityProfile) -> StrictModelRequest:
    messages = (
        ModelMessage("system", "Offline verifier policy; no health interpretation."),
        ModelMessage("user", 'Synthetic UTF-8 input: 中文、引号" and newline\n.'),
    )
    return StrictModelRequest(
        route=_route(), capability_profile=profile, messages=messages,
        final_input_digest=stable_digest({"messages": [m.to_wire() for m in messages]}),
        final_input_upper_bound_tokens=1, output_reservation_tokens=512,
        strict_schema_name=_SCHEMA_NAME, strict_schema_digest=stable_digest(_SCHEMA),
    )


def _raw(status="completed", **changes):
    value = {
        "id": "response:ticket125-offline", "model": _route().requested_model,
        "status": status, "usage": {"input_tokens": 123, "output_tokens": 17},
        "output": [{"type": "message", "status": "completed", "content": [
            {"type": "output_text", "text": '{"verifier_result":"offline"}'},
        ]}],
    }
    if status == "incomplete":
        value["output"] = []
        value["incomplete_details"] = {"reason": "max_output_tokens"}
    elif status == "failed":
        value["output"] = []
        value["error"] = {"code": "server_error", "message": "MUST_NOT_ESCAPE_RAW_ERROR"}
    value.update(changes)
    return value


class _OfflineTransport:
    def __init__(self, result=None, *, route=None):
        self.route = route or _route()
        self.result = _raw() if result is None else result
        self.calls = []

    def send(self, body):
        self.calls.append(copy.deepcopy(body))
        if isinstance(self.result, BaseException):
            raise self.result
        return copy.deepcopy(self.result)


class Ticket125ProductionModelVerificationTests(unittest.TestCase):
    maxDiff = None

    def _module(self):
        try:
            module = importlib.import_module("partner_health_steward.model_adapter")
        except ModuleNotFoundError:
            self.fail("125 prerequisite: production model Adapter is not implemented")
        for name in ("ProductionModelAdapter", "ProfileBoundInputMeasurementStrategy",
                     "BoundResponsesTransport", "load_governed_knowledge_artifact"):
            self.assertTrue(callable(getattr(module, name, None)), name)
        return module

    def _context(self, *, transport=None, clock=None):
        module = self._module()
        profile, evidence = _profile_and_evidence()
        strategy = module.ProfileBoundInputMeasurementStrategy(
            profile, schema=copy.deepcopy(_SCHEMA), measurement_evidence=evidence,
            clock=clock or (lambda: _NOW),
        )
        request = _request(profile)
        request = replace(request, final_input_upper_bound_tokens=strategy.measure(request))
        llm = StrictHealthLLM(
            _route(), profile, _SCHEMA_NAME, stable_digest(_SCHEMA),
            measurement_strategy=strategy,
        )
        transport = transport or _OfflineTransport()
        adapter = module.ProductionModelAdapter(
            _route(), profile, transport=transport, measurement_strategy=strategy,
        )
        return module, profile, evidence, strategy, request, llm, transport, adapter

    def _core_fixture(self, llm):
        base = authority_fixture.Ticket113AuthorityIntegrationTests()
        base.setUp()
        self.addCleanup(base.tearDown)
        base.core.close()
        base.core = HealthCore(
            base.store, base.head, execution_capability_vault=base.execution_vault,
            writer_fence_vault=base.writer_vault, admission_policy=base.policy,
            health_init_verifier=base.init_attestor, health_init_asset=base.init_asset,
            daily_skill_verifier=base.daily_attestor, daily_skill_bundle=base.daily_bundle,
            model_authority_digest=llm.model_authority_digest,
            knowledge_releases=(), knowledge_valid_at=base.knowledge_now.isoformat(),
            knowledge_clock=lambda: base.knowledge_now,
            approved_claims=base.approved_claims,
            approved_templates=(base.approved_template,),
        )
        base.plugin = HealthPlugin(
            base.core, admission_policy=base.policy, health_init_runtime=base.init_runtime,
            coarse_router=CoarseMessageRouter(lambda body, capability: "health"),
            daily_skill_runtime=base.daily_runtime,
        )
        return base

    def _authorize(self, base, request, suffix):
        _, source = base._admit_daily_source(suffix)
        base._prepare_evidence_stage(source)
        response = base.plugin.invoke(
            base._command("effect.request", f"ticket125-effect:{suffix}",
                          EffectRequestPayload("model-work", request.digest, source.causal_id)),
            peer_id="plugin",
        )
        self.assertEqual(response.status, "accepted", response.to_wire())
        grant = base.plugin.claim_effect_execution(response.meta.intent)
        self.assertIsNotNone(grant)
        return source.causal_id, grant

    def test_v125_01_exact_final_wire_crosses_real_core_authorization_once(self):
        _, profile, _, strategy, request, llm, transport, adapter = self._context()
        self.assertFalse(profile.synthetic)
        self.assertIsNone(llm.preflight(request))
        copied = StrictHealthLLM.canonical_copy(llm)
        self.assertEqual(copied.model_authority_digest, llm.model_authority_digest)
        self.assertIsNone(copied.preflight(request))
        base = self._core_fixture(llm)
        source, grant = self._authorize(base, request, "production-positive")
        with DenyBypassHarness() as deny:
            no_grant = base.plugin.execute_strict_health_model(llm, request, source, None, adapter)
            self.assertEqual(no_grant.model_effect, "not-started")
            self.assertEqual(transport.calls, [])
            outcome = base.plugin.execute_strict_health_model(llm, request, source, grant, adapter)
            repeated = base.plugin.execute_strict_health_model(llm, request, source, grant, adapter)
        self.assertEqual(deny.attempts, [])
        self.assertEqual(outcome.disposition, "candidate", outcome)
        self.assertEqual(outcome.candidate["verifier_result"], "offline")
        self.assertEqual(repeated.model_effect, "not-started")
        self.assertEqual(len(transport.calls), 1)
        body = transport.calls[0]
        self.assertEqual(set(body), {"model", "instructions", "input", "store", "stream",
                                     "max_output_tokens", "text"})
        self.assertEqual(body["model"], request.route.requested_model)
        self.assertIs(body["store"], False)
        self.assertIs(body["stream"], True)
        self.assertEqual(body["max_output_tokens"], request.output_reservation_tokens)
        self.assertEqual(body["text"]["format"], {
            "type": "json_schema", "name": _SCHEMA_NAME,
            "schema": _SCHEMA, "strict": True,
        })
        encoded = _canonical(body)
        self.assertEqual(strategy.measure(request), len(encoded))
        for message in request.messages:
            self.assertTrue(any(message.content in leaf for leaf in _string_leaves(body)))
        self.assertEqual(request.digest, stable_digest(request.to_wire()))

    def test_v125_02_missing_expired_drifted_or_insufficient_authority_is_precall(self):
        module, profile, evidence, _, request, llm, transport, adapter = self._context()
        no_strategy = StrictHealthLLM(_route(), profile, _SCHEMA_NAME, stable_digest(_SCHEMA))
        result = no_strategy.preflight(request)
        self.assertEqual((result.model_effect, result.reason_code),
                         ("not-started", "capacity-unavailable"))
        for changed in (
            replace(request, final_input_upper_bound_tokens=1),
            replace(request, final_input_upper_bound_tokens=profile.common_context_lower_bound_tokens),
            replace(request, route=replace(_route(), configuration_generation=26)),
            replace(request, strict_schema_digest="sha256:" + "f" * 64),
        ):
            with self.subTest(change=changed.digest):
                outcome = llm.preflight(changed)
                self.assertIsNotNone(outcome)
                self.assertEqual(outcome.model_effect, "not-started")
                with self.assertRaises(ModelContractViolation):
                    adapter.execute(changed.to_wire())
        bad_evidence = {**evidence, "capacity_evidence_ref": "unbound-replacement"}
        with self.assertRaises(ModelContractViolation):
            strategy = module.ProfileBoundInputMeasurementStrategy(
                profile, schema=_SCHEMA, measurement_evidence=bad_evidence,
                clock=lambda: _NOW,
            )
            strategy.measure(request)
        now = [_NOW]
        _, _, _, _, expiring_request, expiring_llm, expiring_transport, expiring_adapter = (
            self._context(clock=lambda: now[0])
        )
        now[0] = datetime(2026, 9, 2, tzinfo=timezone.utc)
        expired = expiring_llm.preflight(expiring_request)
        self.assertEqual((expired.model_effect, expired.reason_code),
                         ("not-started", "capacity-unavailable"))
        with self.assertRaises(ModelContractViolation):
            expiring_adapter.execute(expiring_request.to_wire())
        self.assertEqual(expiring_transport.calls, [])
        self.assertEqual(transport.calls, [])

    def test_v125_03_raw_terminal_facts_and_unknown_never_retry_or_fabricate(self):
        self._module()
        for status in ("completed", "incomplete", "failed"):
            with self.subTest(terminal=status):
                _, _, _, _, request, llm, transport, adapter = self._context(
                    transport=_OfflineTransport(_raw(status)))
                observed = adapter.execute(request.to_wire())
                self.assertIs(type(observed), ModelTransportResult)
                self.assertEqual(observed.status, status)
                self.assertEqual(observed.actual_model, _route().requested_model)
                self.assertEqual(observed.usage_input_tokens, 123)
                self.assertEqual(observed.usage_output_tokens, 17)
                self.assertEqual(len(transport.calls), 1)
                self.assertNotIn("MUST_NOT_ESCAPE_RAW_ERROR", repr(observed))
                resolved = llm.resolve_transport_result(request, observed)
                self.assertEqual(resolved.disposition,
                                 "candidate" if status == "completed" else "failed-closed")
        unknown_examples = (
            TimeoutError("PRIVATE_TRANSPORT_ERROR_MUST_NOT_ESCAPE"),
            _raw(model=None), _raw(usage=None),
            _raw(output=[{"type": "function_call", "name": "forbidden_tool", "arguments": "{}"}]),
            [{"type": "response.output_text.delta", "delta": "{not terminal}"}],
        )
        for raw in unknown_examples:
            with self.subTest(unknown=type(raw).__name__):
                _, _, _, _, request, llm, transport, adapter = self._context(
                    transport=_OfflineTransport(raw))
                outcome = adapter.execute(request.to_wire())
                self.assertEqual(outcome.status, "unknown")
                self.assertFalse(outcome.terminal_proven)
                self.assertIsNone(outcome.structured_output)
                self.assertNotIn("PRIVATE_TRANSPORT_ERROR", repr(outcome))
                self.assertEqual(len(transport.calls), 1)
        _, _, _, _, request, _, transport, adapter = self._context(
            transport=_OfflineTransport([{"type": "response.completed", "response": _raw()}]))
        self.assertEqual(adapter.execute(request.to_wire()).status, "completed")
        self.assertEqual(len(transport.calls), 1)
        _, _, _, _, request, llm, transport, adapter = self._context(
            transport=_OfflineTransport(_raw(model="unapproved-real-model")))
        outcome = llm.resolve_transport_result(request, adapter.execute(request.to_wire()))
        self.assertEqual(outcome.reason_code, "actual-model-drift")
        self.assertIsNone(outcome.candidate)
        # An unknown transport crosses the actual Core one-shot grant path.
        _, _, _, _, request, llm, transport, adapter = self._context(
            transport=_OfflineTransport(TimeoutError("offline timeout")))
        base = self._core_fixture(llm)
        source, grant = self._authorize(base, request, "production-unknown")
        first = base.plugin.execute_strict_health_model(llm, request, source, grant, adapter)
        second = base.plugin.execute_strict_health_model(llm, request, source, grant, adapter)
        self.assertEqual(first.model_effect, "unknown")
        self.assertEqual(second.model_effect, "not-started")
        self.assertEqual(len(transport.calls), 1)
        # Admission may expire after a real attempt. Its observed terminal facts
        # must not be rewritten as not-started or unknown by a second preflight.
        for terminal in ("completed", "incomplete", "failed"):
            with self.subTest(expired_after_attempt=terminal):
                now = [_NOW]
                class CrossExpiryTransport(_OfflineTransport):
                    def send(self, body):
                        result = super().send(body)
                        now[0] = datetime(2026, 9, 2, tzinfo=timezone.utc)
                        return result
                _, _, _, _, request, llm, transport, adapter = self._context(
                    transport=CrossExpiryTransport(_raw(terminal)), clock=lambda: now[0])
                observed = adapter.execute(request.to_wire())
                self.assertEqual(observed.status, terminal)
                resolved = llm.resolve_transport_result(request, observed)
                self.assertEqual(resolved.model_effect, terminal)
                self.assertIsNone(resolved.candidate)
                self.assertTrue(resolved.model_report.transport_attempted)
                self.assertTrue(resolved.model_report.terminal_proven)
                self.assertEqual(resolved.model_report.model_status, terminal)
                self.assertEqual(resolved.model_report.actual_model, _route().requested_model)
                self.assertEqual(resolved.model_report.result_digest, stable_digest(observed.to_wire()))
                self.assertEqual(len(transport.calls), 1)
        now = [_NOW]
        class CoreCrossExpiryTransport(_OfflineTransport):
            def send(self, body):
                value = super().send(body)
                now[0] = datetime(2026, 9, 2, tzinfo=timezone.utc)
                return value
        _, _, _, _, request, llm, transport, adapter = self._context(
            transport=CoreCrossExpiryTransport(), clock=lambda: now[0])
        base = self._core_fixture(llm)
        source, grant = self._authorize(base, request, "expired-after-core-attempt")
        expired_attempt = base.plugin.execute_strict_health_model(llm, request, source, grant, adapter)
        self.assertEqual(expired_attempt.model_effect, "completed")
        self.assertIsNone(expired_attempt.candidate)
        self.assertEqual(expired_attempt.model_report.model_status, "completed")
        self.assertEqual(len(transport.calls), 1)

    def test_v125_04_governed_artifact_republishes_exactly_without_owner_input(self):
        module = self._module()
        publication = _publication()
        release = KnowledgePublisher().publish(publication, release_version="fixture-v125")
        self.assertIs(type(release), KnowledgeRelease)
        artifact = {
            "contract": "ticket125-governed-knowledge-artifact-v1",
            "publication": publication.to_wire(), "release_version": "fixture-v125",
            "release": release.to_wire(),
        }
        load = module.load_governed_knowledge_artifact
        with DenyBypassHarness() as deny:
            current = load(artifact, expected_digest=stable_digest(artifact), at=_NOW.isoformat())
        self.assertEqual(current, release)
        self.assertEqual(current.stage, "staged")
        self.assertEqual(deny.attempts, [])
        tampered = copy.deepcopy(artifact)
        tampered["publication"]["content"] = "changed offline material"
        with self.assertRaises(KnowledgeContractViolation):
            load(tampered, expected_digest=stable_digest(artifact), at=_NOW.isoformat())
        with self.assertRaises(KnowledgeContractViolation):
            load(tampered, expected_digest=stable_digest(tampered), at=_NOW.isoformat())
        with self.assertRaises(KnowledgeContractViolation):
            owner_input = {**artifact, "owner_context": "must-not-enter-build-path"}
            load(owner_input, expected_digest=stable_digest(owner_input), at=_NOW.isoformat())
        expired = load(artifact, expected_digest=stable_digest(artifact),
                       at="2027-08-24T00:00:00+00:00")
        self.assertIs(type(expired), KnowledgeGap)
        unapproved = copy.deepcopy(artifact)
        unapproved["publication"]["rights_status"] = "unapproved"
        result = load(unapproved, expected_digest=stable_digest(unapproved), at=_NOW.isoformat())
        self.assertIs(type(result), KnowledgeGap)


if __name__ == "__main__":
    unittest.main()

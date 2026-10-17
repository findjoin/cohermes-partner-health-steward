"""Independent finite Ticket 131 gates; all external effects are offline.

The budget fixtures prove local operational limits, never a server context
window, tokenizer, actual routing set, target approval or owner acceptance.
"""
from __future__ import annotations

import copy
import importlib
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from partner_health_steward.answer_resolution import ModelAnswerResolution, ModelEffectRef
from partner_health_steward.contract import EffectRequestPayload, EffectResultPayload
from partner_health_steward.initialization import stable_digest
from partner_health_steward.model_contract import (
    ModelContractViolation, ModelMessage, StrictHealthLLM, StrictModelRequest,
)
from partner_health_steward.nondiagnostic import NonDiagnosticCandidate
from tests import test_ticket125_partner_model as production_fixture
from tests import test_ticket116_integration as diagnostic_fixture
from tests.ticket113_deny_network import DenyBypassHarness


_NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
_MODE = "non-diagnostic-operational-budget"
_PURPOSE = "non-diagnostic-health"
_DISCLOSURE = "不提供共同上下文保证"
_DISCLOSURE_FIELDS = {
    "mode", "purpose", "budget_digest", "owner_decision_ref",
    "max_final_wire_bytes", "output_reservation_tokens",
    "context_guarantee", "context_disclosure",
}
_REQUEST_FIELDS = {
    "contract", "route", "operational_budget", "messages", "final_input_digest",
    "final_wire_bytes", "output_reservation_tokens", "strict_schema_name", "strict_schema_digest",
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _raw(route, candidate, status="completed", **changes):
    value = {
        "id": "response:ticket131-offline", "model": route.requested_model,
        "status": status, "usage": {"input_tokens": 123, "output_tokens": 17},
        "output": [{"type": "message", "status": "completed", "content": [
            {"type": "output_text", "text": json.dumps(candidate, ensure_ascii=False)},
        ]}],
    }
    if status == "incomplete":
        value["output"] = []
        value["incomplete_details"] = {"reason": "max_output_tokens"}
    elif status == "failed":
        value["output"] = []
        value["error"] = {"code": "server_error", "message": "OFFLINE_RAW_ERROR_MUST_NOT_ESCAPE"}
    value.update(changes)
    return value


class _Transport:
    def __init__(self, route, result):
        self.route, self.result = route, result
        self.calls = []

    def send(self, body):
        self.calls.append(copy.deepcopy(body))
        if isinstance(self.result, BaseException):
            raise self.result
        return copy.deepcopy(self.result)


class Ticket131NonDiagnosticBudgetVerificationTests(unittest.TestCase):
    maxDiff = None

    def _modules(self):
        contract = importlib.import_module("partner_health_steward.model_contract")
        adapter = importlib.import_module("partner_health_steward.model_adapter")
        for module, name in (
            (contract, "NonDiagnosticOperationalBudget"),
            (adapter, "NonDiagnosticBudgetInputMeasurementStrategy"),
            (adapter, "nondiagnostic_operation_schema"),
        ):
            self.assertTrue(callable(getattr(module, name, None)),
                            "131 prerequisite is absent: " + name)
        return contract, adapter

    def _budget(self, *, route=None, now=_NOW):
        contract, _ = self._modules()
        route = route or production_fixture._route()
        return contract.NonDiagnosticOperationalBudget(
            "budget:ticket131-offline", "1", route, (route.requested_model,),
            "owner-decision:verifier-fixture-not-target-approval",
            (now - timedelta(days=1)).isoformat(), (now + timedelta(days=1)).isoformat(),
        )

    def _context(self, *, budget=None, messages=None, clock=None, result=None, transport_type=_Transport):
        _, module = self._modules()
        budget = budget or self._budget()
        strategy = module.NonDiagnosticBudgetInputMeasurementStrategy(budget, clock=clock or (lambda: _NOW))
        request = strategy.prepare_request(messages or (
            ModelMessage("system", "Offline fixed policy; return only the governed candidate."),
            ModelMessage("user", '合成离线输入：中文、引号"、换行\n；没有实际主人资料。'),
        ))
        llm = StrictHealthLLM(budget.route, budget, request.strict_schema_name,
                              request.strict_schema_digest, measurement_strategy=strategy)
        fixture = production_fixture.authority_fixture.Ticket113AuthorityIntegrationTests()
        # Its known candidate is a literal governed non-medical fixture. No
        # Core fixture needs to be started merely to form this transport body.
        fixture.setUp()
        try:
            candidate = fixture.candidate.to_wire()
        finally:
            fixture.tearDown()
        transport = transport_type(budget.route, _raw(budget.route, candidate) if result is None else result)
        adapter = module.ProductionModelAdapter(budget.route, budget, transport=transport,
                                               measurement_strategy=strategy)
        return budget, strategy, request, llm, transport, adapter, candidate

    def _core_fixture(self, llm):
        owner = production_fixture.Ticket125ProductionModelVerificationTests()
        self.addCleanup(owner.doCleanups)
        return owner._core_fixture(llm)

    def _authorize(self, base, request, suffix):
        _, source = base._admit_daily_source("ticket131-" + suffix)
        base._prepare_evidence_stage(source)
        issued = base.plugin.invoke(base._command(
            "effect.request", "ticket131-effect-request:" + suffix,
            EffectRequestPayload("model-work", request.digest, source.causal_id)), peer_id="plugin")
        self.assertEqual(issued.status, "accepted", issued.to_wire())
        grant = base.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        return source, grant

    def _terminal(self, base, grant, report, suffix):
        return base.plugin.invoke(base._command(
            "effect.result", "ticket131-effect-result:" + suffix,
            EffectResultPayload(grant.lease.effect_id, grant.lease.intent_digest,
                                grant.lease.lease_id, grant.completion_capability,
                                report.outer_effect_status, True, report.digest, report)), peer_id="plugin")

    def _assert_disclosure(self, value, budget):
        self.assertEqual(set(value), _DISCLOSURE_FIELDS)
        self.assertEqual(value, {
            "mode": _MODE, "purpose": _PURPOSE, "budget_digest": budget.digest,
            "owner_decision_ref": budget.owner_decision_ref,
            "max_final_wire_bytes": 65536, "output_reservation_tokens": 2048,
            "context_guarantee": "not-provided", "context_disclosure": _DISCLOSURE,
        })

    def test_v131_01_real_core_exact_attempt_records_limitation_and_commits_only_typed_reply(self):
        budget, strategy, request, llm, transport, adapter, _ = self._context()
        wire = request.to_wire()
        self.assertEqual(set(wire), _REQUEST_FIELDS)
        self.assertEqual(wire["contract"], "nondiagnostic-operational-request-v1")
        self.assertNotIn("common_context_lower_bound_tokens", budget.to_wire())
        self.assertNotIn("input_measurement_method", budget.to_wire())
        self.assertEqual(type(budget).from_wire(budget.to_wire()), budget)
        self.assertEqual(StrictModelRequest.from_wire(wire).digest, request.digest)
        self.assertEqual(StrictModelRequest.canonical_copy(request).to_wire(), wire)
        copied = StrictHealthLLM.canonical_copy(llm)
        self.assertEqual(copied.model_authority_digest, llm.model_authority_digest)
        self._assert_disclosure(budget.model_use_disclosure, budget)
        self._assert_disclosure(copied.model_use_disclosure, budget)
        detached = llm.model_use_disclosure
        detached["context_guarantee"] = "forged-proof"
        self._assert_disclosure(llm.model_use_disclosure, budget)
        base = self._core_fixture(llm)
        with DenyBypassHarness():
            denied = base.plugin.execute_strict_health_model(llm, request, "ticket131-ungranted", None, adapter)
            self.assertEqual(denied.model_effect, "not-started")
            self.assertEqual(transport.calls, [])
            source, grant = self._authorize(base, request, "one-attempt")
            outcome = base.plugin.execute_strict_health_model(llm, request, source.causal_id, grant, adapter)
            repeated = base.plugin.execute_strict_health_model(llm, request, source.causal_id, grant, adapter)
        self.assertEqual(outcome.disposition, "candidate")
        self.assertEqual(repeated.model_effect, "not-started")
        self.assertEqual(len(transport.calls), 1)
        body = transport.calls[0]
        self.assertEqual(set(body), {"model", "instructions", "input", "store", "stream", "max_output_tokens", "text"})
        self.assertFalse(body["store"])
        self.assertTrue(body["stream"])
        self.assertEqual(body["max_output_tokens"], 2048)
        self.assertEqual(len(_canonical(body)), wire["final_wire_bytes"])
        self.assertEqual(strategy.measure(request), len(_canonical(body)))
        self.assertEqual(stable_digest(body["text"]["format"]["schema"]), request.strict_schema_digest)
        self.assertEqual(body["input"][0]["content"][0]["text"], request.messages[1].content)
        candidate = NonDiagnosticCandidate.from_wire(outcome.candidate)
        self._assert_disclosure(outcome.model_report.model_use_disclosure, budget)
        # A self-consistent report with the limitation removed still cannot
        # replace the Core-observed result for this exact grant.
        stripped = replace(outcome.model_report, model_use_disclosure=None)
        forged = self._terminal(base, grant, stripped, "stripped-disclosure")
        self.assertEqual(forged.status, "rejected", forged.to_wire())
        completed = self._terminal(base, grant, outcome.model_report, "observed")
        self.assertEqual(completed.status, "accepted", completed.to_wire())
        report = base.plugin.model_effect_report(grant.lease.effect_id)
        self._assert_disclosure(report.to_storage()["model_use_disclosure"], budget)
        self.assertEqual(type(report).from_storage(report.to_storage()), report)
        rendered = base.pipeline.render(candidate)
        resolution = ModelAnswerResolution.rendered(
            strict_request_digest=request.digest, model_authority_digest=llm.model_authority_digest,
            template_id=base.approved_template.template_id,
            template_version=base.approved_template.version,
            template_digest=stable_digest(base.approved_template.to_wire()),
            effect_ref=ModelEffectRef(grant.lease.effect_id, report.digest),
            candidate_digest=stable_digest(candidate.to_wire()),
            rendered_reply_digest=stable_digest(rendered.to_commit_wire()))
        _, prepared = base._prepare_complete(source, resolution, candidate=candidate)
        self.assertEqual(prepared.status, "accepted", prepared.to_wire())
        result, commit, finalize = base._finalize_complete(source.causal_id)
        self.assertEqual(result.answer_status, "rendered")
        self.assertEqual(result.answer_resolution_digest, resolution.digest)
        generation = base.head.read().head.generation
        for command in (commit, finalize):
            self.assertIn(base.plugin.invoke(command, peer_id="plugin").status, {"accepted", "replayed"})
        self.assertEqual(base.head.read().head.generation, generation)
        self.assertEqual(len(transport.calls), 1)
        self._assert_disclosure(base.plugin.model_effect_report(grant.lease.effect_id).model_use_disclosure, budget)

    def test_v131_02_exact_wire_ceiling_and_current_budget_fail_before_send(self):
        _, module = self._modules()
        budget = self._budget()
        strategy = module.NonDiagnosticBudgetInputMeasurementStrategy(budget, clock=lambda: _NOW)
        schema = module.nondiagnostic_operation_schema()
        self.assertEqual(stable_digest(schema), module.NONDIAGNOSTIC_OPERATION_SCHEMA_DIGEST)
        # Independently serialize the public fixed wire to place one request
        # exactly on the byte ceiling, then cross it by one ASCII byte.
        messages = (ModelMessage("system", "Offline fixed policy."), *(ModelMessage("user", "x") for _ in range(4)))
        request = strategy.prepare_request(messages)
        body = {"model": budget.route.requested_model, "instructions": messages[0].content,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": "x"}]} for _ in range(4)],
                "store": False, "stream": True, "max_output_tokens": 2048,
                "text": {"format": {"type": "json_schema", "name": module.NONDIAGNOSTIC_OPERATION_SCHEMA_NAME,
                                    "schema": schema, "strict": True}}}
        self.assertEqual(strategy.measure(request), len(_canonical(body)))
        remaining = 65536 - len(_canonical(body))
        texts = []
        for _ in range(4):
            extra = min(remaining, 16383)
            texts.append("x" * (1 + extra)); remaining -= extra
        self.assertEqual(remaining, 0)
        boundary_messages = (messages[0], *(ModelMessage("user", text) for text in texts))
        boundary = strategy.prepare_request(boundary_messages)
        for item, text in zip(body["input"], texts): item["content"][0]["text"] = text
        self.assertEqual(len(_canonical(body)), 65536)
        self.assertEqual(boundary.to_wire()["final_wire_bytes"], 65536)
        self.assertEqual(strategy.measure(boundary), 65536)
        index = next(i for i, text in enumerate(texts) if len(text) < 16384)
        over = list(boundary_messages)
        over[index + 1] = ModelMessage("user", texts[index] + "x")
        with self.assertRaises(ModelContractViolation): strategy.prepare_request(tuple(over))
        with self.assertRaises(ModelContractViolation):
            strategy.prepare_request((messages[0], *(ModelMessage("user", '中"' * 4000) for _ in range(4))))
        for field, replacement in (("max_final_wire_bytes", 65537), ("context_guarantee", "proved")):
            forged = budget.to_wire(); forged[field] = replacement
            with self.assertRaises(ModelContractViolation): type(budget).from_wire(forged)
        mixed = request.to_wire(); mixed["final_input_upper_bound_tokens"] = 240000
        with self.assertRaises(ModelContractViolation): StrictModelRequest.from_wire(mixed)
        underdeclared = request.to_wire(); underdeclared["final_wire_bytes"] -= 1
        with self.assertRaises(ModelContractViolation): StrictModelRequest.from_wire(underdeclared)
        _, _, valid, llm, transport, adapter, _ = self._context()
        try:
            unmeasured = StrictHealthLLM(budget.route, budget, valid.strict_schema_name, valid.strict_schema_digest)
        except ModelContractViolation:
            pass
        else:
            self.assertEqual(unmeasured.preflight(valid).model_effect, "not-started")
        with self.assertRaises(ModelContractViolation):
            StrictHealthLLM(budget.route, budget, valid.strict_schema_name,
                            valid.strict_schema_digest, measurement_strategy=object())
        changed = replace(budget, owner_decision_ref="owner-decision:different-offline-binding")
        other_strategy = module.NonDiagnosticBudgetInputMeasurementStrategy(changed, clock=lambda: _NOW)
        other = other_strategy.prepare_request(valid.messages)
        refused = llm.preflight(other)
        self.assertEqual((refused.disposition, refused.model_effect), ("failed-closed", "not-started"))
        self.assertNotEqual(StrictHealthLLM(changed.route, changed, other.strict_schema_name,
            other.strict_schema_digest, measurement_strategy=other_strategy).model_authority_digest, llm.model_authority_digest)
        drift_route = replace(budget.route, configuration_generation=budget.route.configuration_generation + 1)
        drift_budget = replace(budget, route=drift_route)
        drift_strategy = module.NonDiagnosticBudgetInputMeasurementStrategy(drift_budget, clock=lambda: _NOW)
        refused = llm.preflight(drift_strategy.prepare_request(valid.messages))
        self.assertEqual(refused.model_effect, "not-started")
        now = [_NOW]
        _, expiring_strategy, expiring, expiring_llm, expiring_transport, expiring_adapter, _ = self._context(clock=lambda: now[0])
        now[0] += timedelta(days=1)
        with self.assertRaises(ModelContractViolation): expiring_strategy.prepare_request(valid.messages)
        with self.assertRaises(ModelContractViolation): expiring_strategy.measure(expiring)
        refused = expiring_llm.preflight(expiring)
        self.assertEqual((refused.model_effect, refused.reason_code), ("not-started", "operation-budget-unavailable"))
        with self.assertRaises(ModelContractViolation): expiring_adapter.execute(expiring.to_wire())
        self.assertEqual(transport.calls + expiring_transport.calls, [])

    def test_v131_03_raw_terminal_truth_expiry_and_unknown_remain_one_attempt(self):
        self._modules()
        budget, _, request, llm, _, _, candidate = self._context()
        cases = [
            (_raw(budget.route, candidate, "incomplete"), "incomplete"),
            (_raw(budget.route, candidate, "failed"), "failed"),
            (_raw(budget.route, candidate, model=None), "unknown"),
            (_raw(budget.route, candidate, usage=None), "unknown"),
            (_raw(budget.route, {"diagnosis": "FORBIDDEN_SYNTHETIC_LABEL"}), "unknown"),
            (TimeoutError("OFFLINE_RESPONSE_LOST"), "unknown"),
        ]
        for raw, status in cases:
            with self.subTest(terminal=status, malformed=type(raw).__name__):
                b, _, r, current, transport, adapter, _ = self._context(result=raw)
                with DenyBypassHarness(): observed = adapter.execute(r.to_wire())
                outcome = current.resolve_transport_result(r, observed)
                self.assertEqual((observed.status, outcome.model_effect), (status, status))
                self.assertIsNone(outcome.candidate)
                self.assertEqual(len(transport.calls), 1)
                self.assertEqual(outcome.model_report.result_digest, stable_digest(observed.to_wire()))
                self._assert_disclosure(outcome.model_report.model_use_disclosure, b)
                if status != "unknown":
                    self.assertEqual((observed.response_id, observed.actual_model, observed.usage_input_tokens,
                                      observed.usage_output_tokens), ("response:ticket131-offline", b.route.requested_model, 123, 17))
        for status in ("completed", "incomplete", "failed"):
            now = [_NOW]
            class CrossExpiry(_Transport):
                def send(self, body):
                    result = super().send(body)
                    now[0] += timedelta(days=1)
                    return result
            b, _, r, current, transport, adapter, _ = self._context(
                result=_raw(budget.route, candidate, status), clock=lambda: now[0], transport_type=CrossExpiry)
            observed = adapter.execute(r.to_wire())
            outcome = current.resolve_transport_result(r, observed)
            self.assertEqual((observed.status, outcome.model_effect, outcome.model_report.model_status), (status, status, status))
            self.assertTrue(outcome.model_report.transport_attempted)
            self.assertTrue(outcome.model_report.terminal_proven)
            self.assertIsNone(outcome.candidate)
            self._assert_disclosure(outcome.model_report.model_use_disclosure, b)
            if status == "completed": self.assertEqual(outcome.reason_code, "operation-budget-expired")
            self.assertEqual(len(transport.calls), 1)
        now = [_NOW]
        class CoreCrossExpiry(_Transport):
            def send(self, body):
                result = super().send(body); now[0] += timedelta(days=1)
                return result
        b, _, r, current, transport, adapter, _ = self._context(clock=lambda: now[0], transport_type=CoreCrossExpiry)
        base = self._core_fixture(current)
        source, grant = self._authorize(base, r, "cross-expiry")
        outcome = base.plugin.execute_strict_health_model(current, r, source.causal_id, grant, adapter)
        self.assertEqual((outcome.model_effect, outcome.reason_code), ("completed", "operation-budget-expired"))
        self.assertIsNone(outcome.candidate)
        self.assertEqual(self._terminal(base, grant, outcome.model_report, "cross-expiry").status, "accepted")
        self._assert_disclosure(base.plugin.model_effect_report(grant.lease.effect_id).model_use_disclosure, b)
        b, _, r, current, lost_transport, lost_adapter, _ = self._context(result=TimeoutError("offline unknown"))
        pending = self._core_fixture(current)
        source, grant = self._authorize(pending, r, "unknown")
        outcome = pending.plugin.execute_strict_health_model(current, r, source.causal_id, grant, lost_adapter)
        again = pending.plugin.execute_strict_health_model(current, r, source.causal_id, grant, lost_adapter)
        self.assertEqual((outcome.model_effect, again.model_effect), ("unknown", "not-started"))
        self.assertEqual(len(lost_transport.calls), 1)
        self.assertEqual(self._terminal(pending, grant, outcome.model_report, "unknown").status, "unknown")
        self.assertEqual(pending.plugin.model_answer_recovery_status(source.causal_id), "unknown")
        self.assertIsNone(pending.plugin.native_cursor_directive(source.causal_id, peer_id="plugin"))

    def test_v131_04_real_active_diagnostic_source_rejects_operational_budget(self):
        self._modules()
        diagnostic = diagnostic_fixture.Ticket116VerificationTests()
        diagnostic.setUp()
        self.addCleanup(diagnostic.tearDown)
        diagnostic._activate_synthetic_scope_through_ticket119()
        self.assertEqual(diagnostic._managed_read()["scope"]["effective_phase"], "active")
        # An actual strict diagnostic intent/execution is the positive control;
        # the later denial cannot be explained by staged/missing medical assets.
        _, strict_adapter = diagnostic._prepare_and_execute_model(
            source_suffix="ticket131-strict-control", question_ref="question:strict-control",
            event_ref="event:strict-control")
        self.assertEqual(strict_adapter.calls, 1)
        budget = self._budget(route=diagnostic.route, now=diagnostic.knowledge_now)
        _, _, request, llm, transport, adapter, _ = self._context(
            budget=budget, clock=lambda: diagnostic.knowledge_now)
        diagnostic.llm = llm
        diagnostic._restart_with_assets(diagnostic._synthetic_assets(scope_state="staged"))
        self.assertEqual(diagnostic._managed_read()["scope"]["effective_phase"], "active")
        before = diagnostic.base.store.count_effects()
        refused = diagnostic._health("diagnosis.prepare", diagnostic._diagnosis_prepare_payload(
            source_suffix="ticket131-budget-denied", question_ref="question:budget-denied",
            event_ref="event:budget-denied"), suffix="ticket131-budget-denied")
        self.assertEqual(refused.get("status"), "rejected", refused)
        self.assertNotIn("model_intent", refused)
        self.assertNotIn("request", refused)
        self.assertEqual(diagnostic.base.store.count_effects(), before)
        self.assertEqual(transport.calls, [])
        self.assertEqual(diagnostic._managed_read()["scope"]["persistent_state"], "active")


if __name__ == "__main__":
    unittest.main()

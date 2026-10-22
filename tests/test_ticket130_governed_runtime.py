"""Independent Ticket130 gates at published Plugin, AF_UNIX and HTTP boundaries.

All identities, keys, text, authority resources and network observations are
synthetic. No target configuration or external account is read or contacted.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPOSITORY = Path(__file__).resolve().parents[1]
if __name__ == "__main__" and "--pinned-gate" in sys.argv:
    sys.path[:] = [p for p in sys.path if Path(p or os.getcwd()).resolve()
                   not in {_REPOSITORY, _REPOSITORY / "tests"}]
    sys.path.insert(0, os.environ["TICKET130_PINNED_SOURCE"])
    sys.path.insert(0, os.environ["TICKET130_PUBLISHED_PLUGIN"])
    tests = types.ModuleType("tests")
    tests.__path__ = [str(_REPOSITORY / "tests")]
    tests.__package__ = "tests"
    sys.modules["tests"] = tests

from partner_health_steward.coordination import DailySkillBundle
from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.host_contract import _CorePortClient, _HostVerificationFailure
from partner_health_steward.initialization import stable_digest, InitializationDisclosure, OwnerConsentEvidence
from partner_health_steward.model_contract import ModelMessage, StrictHealthLLM, StrictModelRequest, ModelTransportResult
from tests import test_ticket113_authority_integration as answer_fixture
from tests import test_ticket125_partner_model as model_fixture
from tests import test_ticket126_live_delivery as delivery_fixture

_OPERATION = delivery_fixture._operation
_PROJECTION = delivery_fixture._projection
_CANONICAL = delivery_fixture._canonical
_SHA = delivery_fixture._sha
_TOPIC = "physical-function-and-experience/sleep"
_NOW = datetime(2026, 8, 24, 1, 6, tzinfo=timezone.utc)
_STAGE_FIELDS = {"response", "next_stage", "model_use_disclosure", "delivery_refs"}
_GRANT_FIELDS = {"session_id", "lease_id", "effect_id", "intent_digest", "generation", "writer_fence"}
_LIMIT = "不提供共同上下文保证"
_TOKEN = "SYNTHETIC130-NETWORK-ONLY-CREDENTIAL"


def _budget(clock=lambda: _NOW, *, wide=False):
    from partner_health_steward.model_contract import NonDiagnosticOperationalBudget
    route = model_fixture._route()
    if wide:
        route = replace(route, provider="\x01" * 4900 + "中" * 1500)
    # Explicit offline fixture, current for both synthetic Core time and actual
    # Plugin UTC measurement time. This is never a target capacity approval.
    budget = NonDiagnosticOperationalBudget(
        "budget:ticket130-offline-only", "1", route, (route.requested_model,),
        "owner-decision:ticket130-fixture-not-target-approval",
        "2026-01-01T00:00:00+00:00", "2028-01-01T00:00:00+00:00")
    from partner_health_steward.model_adapter import NonDiagnosticBudgetInputMeasurementStrategy
    strategy = NonDiagnosticBudgetInputMeasurementStrategy(budget, clock=clock)
    return budget, strategy


def _llms(strategy, budget):
    values = []
    for stage in ("intake", "answer"):
        request = strategy.prepare_request((ModelMessage("system", "Offline governed policy."),
                                            ModelMessage("user", "合成资料")), stage=stage)
        values.append(StrictHealthLLM(budget.route, budget, request.strict_schema_name,
                                     request.strict_schema_digest, measurement_strategy=strategy))
    assert values[0].model_authority_digest != values[1].model_authority_digest
    return tuple(values)


def _answer_resources():
    fixture = answer_fixture.Ticket113AuthorityIntegrationTests()
    fixture.setUp()
    try:
        return (fixture.approved_claims, (fixture.approved_template,),
                fixture.candidate.to_wire(), fixture.rendered.text)
    finally:
        fixture.tearDown()


def _intake(text, *, operation="record", fact=None, question=None, time_text="昨晚", topic=_TOPIC):
    fact = text if fact is None and operation == "record" else fact
    facts = []
    if fact is not None:
        start = text.index(fact)
        ts = text.index(time_text, start) if time_text is not None else None
        facts.append({"start": start, "end": start + len(fact), "quote": fact, "topic_ref": topic,
                      "time_start": ts, "time_end": None if ts is None else ts + len(time_text)})
    query = None
    if question is not None:
        start = text.index(question)
        query = {"start": start, "end": start + len(question), "quote": question}
    return {"operation": operation, "facts": facts, "question": query}


def _raw(route, candidate, *, status="completed", response_id="response:ticket130-offline", **changes):
    value = {"id": response_id, "model": route.requested_model, "status": status,
             "usage": {"input_tokens": 219, "output_tokens": 31},
             "output": [{"type": "message", "status": "completed", "content": [
                 {"type": "output_text", "text": json.dumps(candidate, ensure_ascii=False)}]}]}
    if status == "incomplete":
        value.update(output=[], incomplete_details={"reason": "max_output_tokens"})
    elif status == "failed":
        value.update(output=[], error={"code": "server_error", "message": "RAW_ERROR_MUST_NOT_ESCAPE"})
    value.update(changes)
    return value


@contextmanager
def _service(*, wide=False):
    """Reuse123/126 real publication and host facilities, replace no authority.

    The legacy126 fixture is closed before constructing the declared130 typed
    runtime. Access to its Core object below is fixture plumbing for existing
    public read methods, never a frozen private helper or alternate server.
    """
    from partner_health_steward.governed_nondiagnostic import GovernedNonDiagnosticRuntime
    from partner_health_steward.live_health import LiveHealthRuntime
    from partner_health_steward.production_core_service import ProductionCoreService
    clock = [datetime.now(timezone.utc)]
    budget, strategy = _budget(lambda: clock[0], wide=wide)
    intake_llm, answer_llm = _llms(strategy, budget)
    claims, templates, candidate, reply = _answer_resources()
    options = {"owner_settings_clock": lambda: clock[0], "business_status_clock": lambda: clock[0],
               "knowledge_clock": lambda: clock[0], "knowledge_valid_at": _NOW.isoformat(),
               "knowledge_releases": (), "approved_claims": claims, "approved_templates": templates,
               "model_authority_digest": answer_llm.model_authority_digest}
    with delivery_fixture._service(core_options=options) as base:
        base.service.close()
        root = Path(base.binding["release_root"])
        paths = {name: f"skills/{name}/SKILL.md" for name in
                 ("health-init", *(a.canonical_name for a in base.daily.daily_bundle.assets))}
        bundle = DailySkillBundle(tuple(replace(a, asset_digest=_SHA((root / paths[a.canonical_name]).read_bytes()))
                                        for a in base.daily.daily_bundle.assets))
        governed = GovernedNonDiagnosticRuntime(intake_llm, answer_llm, strategy,
            bundle=bundle, attestor=base.daily.daily_attestor, clock=lambda: clock[0])
        runtime = LiveHealthRuntime(base.daily.policy, base.init, base.daily.router,
            asset_paths=paths, core_options=options, governed_nondiagnostic_runtime=governed)
        service = ProductionCoreService(base.binding, current_head=base.head, live_runtime=runtime)
        endpoint = service.start()
        fixture = types.SimpleNamespace(**{**vars(base), "service": service, "runtime": runtime,
            "port": delivery_fixture._SocketPort(endpoint), "clock": clock, "budget": budget,
            "strategy": strategy, "intake_llm": intake_llm, "answer_llm": answer_llm,
            "candidate": candidate, "approved_reply": reply})
        try:
            yield fixture
        finally:
            fixture.service.close()


def _message(fixture, suffix, text):
    raw = fixture.daily.message(text, causal_id="ticket130:" + suffix,
        generation=fixture.head.read().head.generation, requested_capability="health-steward",
        message_id="native130:" + suffix, native_cursor="cursor130:" + suffix,
        protocol_timestamp="2026-08-24T09:05:00+08:00", received_at="2026-08-24T09:05:01+08:00")
    return asdict(raw)


def _receive(fixture, suffix, text):
    result = fixture.port.exchange("command", _OPERATION("governed-receive", {
        "message": _message(fixture, suffix, text)}))
    assert set(result) == _STAGE_FIELDS, result
    return result


def _read(fixture, source):
    value = fixture.port.exchange("managed-read", _PROJECTION("health-entry-nondiagnostic", {
        "source_causal_id": source}))
    assert set(value) == {"source_causal_id", "next_stage", "state", "reason_code", "model_use_disclosure"}
    assert value["source_causal_id"] == source
    assert "body" not in value and _TOKEN not in repr(value)
    return value


def _await_status(fixture, source, allowed):
    deadline = time.monotonic() + 8
    while True:
        value = _read(fixture, source)
        if value["state"] in allowed: return value
        if time.monotonic() >= deadline: raise AssertionError(value)
        time.sleep(0.01)


def _prepare(fixture, source, stage):
    result = fixture.port.exchange("controlled-effect", _OPERATION("nondiagnostic-prepare", {
        "source_causal_id": source, "stage": stage}))
    assert set(result) == {"stage", "state", "request_transfer", "intent", "grant"}, result
    if result["grant"] is not None:
        assert set(result["grant"]) == _GRANT_FIELDS
        assert result["grant"]["effect_id"] == result["intent"]["effect_id"]
    return result


def _request(fixture, source, stage, prepared):
    descriptor, pieces = prepared["request_transfer"], []
    assert set(descriptor) == {"size_bytes", "digest", "chunk_count"}
    assert 1 <= descriptor["chunk_count"] <= 256 and descriptor["size_bytes"] <= 8388608
    for index in range(descriptor["chunk_count"]):
        payload = {"source_causal_id": source, "stage": stage, "grant": prepared["grant"], "index": index}
        value = fixture.port.exchange("controlled-effect", _OPERATION("nondiagnostic-request-chunk", payload))
        assert set(value) == {"request_transfer", "index", "bytes_b64", "next_index"}
        assert value["request_transfer"] == descriptor and value["index"] == index
        raw = base64.b64decode(value["bytes_b64"], validate=True)
        assert 1 <= len(raw) <= 32768
        assert index == descriptor["chunk_count"] - 1 or len(raw) == 32768
        assert value["next_index"] == (None if index + 1 == descriptor["chunk_count"] else index + 1)
        assert len(_CANONICAL(value)) <= 65536
        pieces.append(raw)
    encoded = b"".join(pieces)
    assert len(encoded) == descriptor["size_bytes"] and _SHA(encoded) == descriptor["digest"]
    wire = json.loads(encoded)
    assert _CANONICAL(wire) == encoded
    request = StrictModelRequest.from_wire(wire)
    assert request.digest == stable_digest(wire)
    return request, descriptor, encoded


def _start(fixture, source, stage, prepared, receipt):
    value = fixture.port.exchange("controlled-effect", _OPERATION("nondiagnostic-start", {
        "source_causal_id": source, "stage": stage, "grant": prepared["grant"], "request_receipt": receipt}))
    assert set(value) == {"stage", "state", "request_digest", "attempt_ref"}
    return value


def _upload_result(fixture, source, stage, prepared, started, result):
    encoded = _CANONICAL(result.to_wire())
    descriptor = {"size_bytes": len(encoded), "digest": _SHA(encoded),
                  "chunk_count": (len(encoded) + 32767) // 32768}
    for index in range(descriptor["chunk_count"]):
        value = fixture.port.exchange("controlled-effect", _OPERATION("nondiagnostic-result-chunk", {
            "source_causal_id": source, "stage": stage, "grant": prepared["grant"],
            "attempt_ref": started["attempt_ref"], "result_transfer": descriptor,
            "index": index, "bytes_b64": base64.b64encode(encoded[index * 32768:(index + 1) * 32768]).decode()}))
        assert set(value) == {"stage", "state", "next_index"}
        assert value["next_index"] == (None if index + 1 == descriptor["chunk_count"] else index + 1)
    return descriptor


def _complete(fixture, source, stage, prepared, started, descriptor):
    return fixture.port.exchange("controlled-effect", _OPERATION("nondiagnostic-complete", {
        "source_causal_id": source, "stage": stage, "grant": prepared["grant"],
        "attempt_ref": started["attempt_ref"], "result_receipt": descriptor}))


def _request_or_denial(port, kind, payload):
    """A strict production client represents a refused frame as this exact EOF.

    The older raw socket fixture returns None for the same wire observation.
    Other failures remain test errors; no substitute successful reply is made.
    """
    try:
        return port.request(kind, payload)
    except _HostVerificationFailure as exc:
        assert str(exc) == "core-frame-truncated", str(exc)
        return None


def _parent_barrier(config, event, **payload):
    """Synthetic body-free fixture IPC, never a product receipt or authority."""
    directory = Path(config["observer_directory"])
    temporary = directory / "request.tmp"
    temporary.write_bytes(_CANONICAL({"event": event, **payload}))
    temporary.replace(directory / "request.json")
    deadline = time.monotonic() + 12
    while not (directory / "response.json").is_file():
        assert time.monotonic() < deadline, "parent system-boundary observation timed out"
        time.sleep(0.01)
    observed = json.loads((directory / "response.json").read_bytes())
    assert "error" not in observed, observed
    return observed


def _initialize(fixture):
    # Existing public consent/disclosure/commit/finalize; no direct active flag.
    request = replace(fixture.daily.initialization_request(), first_hop_route=fixture.budget.route.route_id)
    request = replace(request, preferences=replace(request.preferences, contact_window="00:00-00:00"))
    pending = replace(request, owner_consent=False, first_hop_route_consent=False)
    disclosure = InitializationDisclosure.from_storage(fixture.port.exchange("command", _OPERATION(
        "initialization-disclosure", {"initialization": pending.to_storage()}))["disclosure"])
    evidence = OwnerConsentEvidence.for_initialization(request, fixture.init.asset, disclosure,
        owner_confirmed=True, first_hop_route_confirmed=True)
    message = asdict(fixture.daily.message(evidence.to_message_body(), generation=fixture.head.read().head.generation))
    assert fixture.port.exchange("command", _OPERATION("receive-weixin", {"message": message}))["response"]["status"] == "accepted"
    for operation, payload in (("initialization-consent", {"initialization": request.to_storage()}),
                               ("initialization-commit", {}), ("initialization-finalize", {})):
        assert fixture.port.exchange("command", _OPERATION(operation, payload))["response"]["status"] in {"accepted", "replayed"}
    assert fixture.port.exchange("managed-read", _PROJECTION("health-entry-initialization"))["initialization"]["phase"] == "enabled"


def _offline_stage(fixture, source, stage, candidate, *, status="completed"):
    """Real125 Adapter, only its documented external transport is replaced."""
    from partner_health_steward.model_adapter import ProductionModelAdapter
    prepared = _prepare(fixture, source, stage)
    assert prepared["grant"] is not None, prepared
    request, receipt, _ = _request(fixture, source, stage, prepared)
    started = _start(fixture, source, stage, prepared, receipt)
    assert started["state"] == "attempted" and started["attempt_ref"], started
    calls = []
    class Transport:
        route = fixture.budget.route
        def send(self, body):
            calls.append(copy.deepcopy(body))
            return _raw(self.route, candidate, status=status)
    adapter = ProductionModelAdapter(fixture.budget.route, fixture.budget,
                                     transport=Transport(), measurement_strategy=fixture.strategy)
    result = adapter.execute(request.to_wire())
    assert type(result) is ModelTransportResult and len(calls) == 1
    descriptor = _upload_result(fixture, source, stage, prepared, started, result)
    completed = _complete(fixture, source, stage, prepared, started, descriptor)
    return prepared, result, completed


class Ticket130GovernedRuntimeVerificationTests(unittest.TestCase):
    maxDiff = None

    def _modules(self):
        for name in ("governed_nondiagnostic", "live_nondiagnostic"):
            self.assertIsNotNone(importlib.util.find_spec("partner_health_steward." + name),
                                 "130 prerequisite: governed two-stage runtime and Plugin bridge are absent")
        return importlib.import_module("partner_health_steward.governed_nondiagnostic")

    def _run_child(self, gate, fixture, *, data=None):
        pinned = Path(os.environ.get("TICKET118_PINNED_HERMES_SOURCE", "/tmp/health-steward-hermes-git"))
        self.assertTrue((pinned / "gateway/platforms/weixin.py").is_file())
        with tempfile.TemporaryDirectory(prefix="ticket130-hermes-home-") as directory:
            home = Path(directory)
            release_root = Path(fixture.binding["release_root"])
            host = json.loads((release_root / "host-release-manifest.json").read_text())
            initial = fixture.daily.initialization_request()
            initial = replace(initial, owner_consent=False, first_hop_route_consent=False,
                              first_hop_route=fixture.budget.route.route_id,
                              preferences=replace(initial.preferences, contact_window="00:00-00:00"))
            config = {"gate": gate, "data": data or {}, "endpoint": fixture.port.endpoint,
                      "policy": fixture.daily.policy.to_storage(), "initialization": initial.to_storage(),
                      "budget": fixture.budget.to_wire(), "route": fixture.budget.route.to_wire(),
                      "answer": fixture.candidate, "approved_reply": fixture.approved_reply,
                      "now": fixture.clock[0].isoformat()}
            observer = home / "observer"
            observer.mkdir()
            config["observer_directory"] = str(observer)
            config_path = home / "offline-config.json"
            config_path.write_bytes(_CANONICAL(config)); config_path.chmod(0o600)
            env = {key: os.environ[key] for key in ("PATH", "LANG", "SYSTEMROOT") if key in os.environ}
            env.update(HERMES_HOME=str(home), HERMES_CONFIG=str(home / "config.yaml"), PYTHONDONTWRITEBYTECODE="1",
                       TICKET130_PINNED_SOURCE=str(pinned), TICKET130_PUBLISHED_PLUGIN=str(release_root / "plugin/health-weixin"),
                       TICKET126_HOST_RELEASE_DIGEST=host["release_digest"])
            stop, observer_errors = threading.Event(), []
            def coordinate():
                while not stop.wait(0.01):
                    request_path = observer / "request.json"
                    if not request_path.is_file():
                        continue
                    try:
                        request = json.loads(request_path.read_bytes())
                        if request == {"event": "head-unavailable-after-artifact-read"}:
                            assert gate == "export" and data == {"mode": "unavailable-after-read"}
                            # Replace only the already-declared external Dynamo
                            # HTTP fixture after the final actual Core read.
                            fixture.client.get_error = TimeoutError("offline current-head unavailable after export read")
                            response = {"external_head_unavailable": True}
                        else:
                            assert gate == "delete" and set(request) == {"event", "operation_ref"}
                            assert request["event"] == "observe-delete-terminal"
                            deadline = time.monotonic() + 8
                            while True:
                                response = fixture.service._core.managed_lifecycle_read(request["operation_ref"])
                                if response.get("phase") == "completed":
                                    break
                                assert time.monotonic() < deadline, response
                                time.sleep(0.01)
                    except BaseException as exc:
                        observer_errors.append(exc)
                        response = {"error": repr(exc)}
                    temporary = observer / "response.tmp"
                    temporary.write_bytes(_CANONICAL(response))
                    temporary.replace(observer / "response.json")
                    return
            worker = threading.Thread(target=coordinate, daemon=True)
            worker.start()
            try:
                run = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--pinned-gate", str(config_path)],
                                     cwd=home, env=env, capture_output=True, text=True, timeout=100)
            finally:
                stop.set()
                worker.join(timeout=13)
            self.assertFalse(worker.is_alive(), "fixture observer did not finish")
            if observer_errors:
                raise observer_errors[0]
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("TICKET130-" + gate + "-PASS", run.stdout)
            return json.loads((home / "offline-result.json").read_text())

    def _assert_start_denied(self, value):
        if value is None:
            return
        self.assertEqual(value["status"], "accepted")
        payload = value["payload"]
        self.assertEqual(set(payload), {"stage", "state", "request_digest", "attempt_ref"})
        self.assertIn(payload["state"], {"failed-closed", "not-started", "unavailable", "rejected"})
        self.assertIsNone(payload["attempt_ref"])

    def test_v130_01_published_registry_socket_intake_evidence_answer_unique_commit_and_visible_limits(self):
        self._modules()
        with _service() as fixture:
            result = self._run_child("trace", fixture)
            self.assertEqual(result["model_stages"], ["intake", "intake", "answer", "intake", "answer"])
            self.assertEqual(set(result["kinds"]), {"command", "managed-read", "controlled-effect"})
            self.assertTrue(result["initialized_message"])
            self.assertEqual(result["ordinary_calls"], 0)
            core = fixture.service._core
            state = core.daily_state()
            self.assertEqual(len(state.evidence_cards), 2, "a question cannot turn into an owner fact")
            self.assertTrue(all("没有失眠" in card.content for card in state.evidence_cards))
            self.assertTrue(all(card.specific_fields.observation_kind == "owner-statement"
                                for card in state.evidence_cards))
            self.assertTrue(all(card.occurred_at == "2026-08-23" for card in state.evidence_cards))
            self.assertTrue(any(_TOPIC == topic.topic_ref for topic in state.portrait_topics))
            for effect in result["effects"]:
                report = core.model_effect_report(effect)
                self.assertIsNotNone(report)
                self.assertEqual(report.actual_model, fixture.budget.route.requested_model)
                wire = result["results"][effect]
                self.assertEqual(wire["usage_input_tokens"], 219)
                self.assertEqual(wire["usage_output_tokens"], 31)
                self.assertEqual(report.result_digest, stable_digest(wire))
                self.assertEqual(report.model_use_disclosure, fixture.budget.model_use_disclosure)
            self.assertEqual(len(result["effects"]), 5)
            self.assertEqual(len(set(result["records"])), 3)
            self.assertTrue(result["replay_unchanged"])

    def test_v130_02_intake_source_negation_time_question_and_real_stage_authority(self):
        self._modules()
        cases = []
        text = "我昨晚没有失眠"
        correct = _intake(text)
        omitted = _intake(text); omitted["facts"][0].update(start=text.index("失眠"), quote="失眠", time_start=None, time_end=None)
        cases.append((text, omitted))
        forged = _intake(text); forged["facts"][0]["quote"] = "我昨晚失眠"
        cases.append((text, forged))
        query = "我是不是糖尿病？"
        cases.append((query, _intake(query, time_text=None, topic="clinical-and-safety/symptoms-and-health-problems")))
        wrong_time = _intake(text); wrong_time["facts"][0].update(time_start=0, time_end=len(text) + 1)
        cases.append((text, wrong_time))
        for index, (body, candidate) in enumerate(cases):
            with self.subTest(mutation=index), _service() as fixture:
                _initialize(fixture)
                _receive(fixture, "invalid-intake", body)
                source = "ticket130:invalid-intake"
                _offline_stage(fixture, source, "intake", candidate)
                outcome = fixture.port.exchange("command", _OPERATION("governed-advance", {"source_causal_id": source}))
                self.assertNotEqual(outcome["next_stage"], "answer")
                self.assertEqual(fixture.service._core.daily_state().evidence_cards, ())
                self.assertIsNone(_prepare(fixture, source, "answer")["grant"])
        with _service() as fixture:
            _initialize(fixture)
            _receive(fixture, "valid-intake", text)
            # Answer before intake/evidence has no authority or network request.
            self.assertIsNone(_prepare(fixture, "ticket130:valid-intake", "answer")["grant"])
            prepared, _, _ = _offline_stage(fixture, "ticket130:valid-intake", "intake", correct)
            committed = fixture.port.exchange("command", _OPERATION("governed-advance", {"source_causal_id": "ticket130:valid-intake"}))
            self.assertIsNone(committed["next_stage"])
            self.assertEqual(len(fixture.service._core.daily_state().evidence_cards), 1)
            self.assertIsNone(_prepare(fixture, "ticket130:valid-intake", "intake")["grant"])
            self.assertIsNone(_prepare(fixture, "ticket130:valid-intake", "answer")["grant"])
            self.assertTrue(fixture.service._core.model_effect_report(prepared["intent"]["effect_id"]))
        with _service() as fixture:
            _initialize(fixture)
            text = "我感觉一般"
            _receive(fixture, "unknown-time", text)
            _offline_stage(fixture, "ticket130:unknown-time", "intake", _intake(text, time_text=None, topic=None))
            fixture.port.exchange("command", _OPERATION("governed-advance", {"source_causal_id": "ticket130:unknown-time"}))
            card, = fixture.service._core.daily_state().evidence_cards
            self.assertEqual(card.content, text)
            self.assertEqual(card.occurred_at, "unknown")
            self.assertEqual(card.time_certainty, "uncertain")

    def test_v130_03_bounded_canonical_chunks_grant_isolation_currentness_and_no_core_network_lock(self):
        self._modules()
        with _service(wide=True) as fixture:
            _initialize(fixture)
            result = self._run_child("chunks", fixture)
            self.assertGreater(result["request_size"], 65536)
            self.assertGreater(result["result_size"], 65536)
            self.assertLessEqual(max(result["frame_sizes"]), 65536)
            self.assertTrue(result["split_utf8"])
            self.assertEqual(result["probes_during_http"], result["model_calls"])
            self.assertTrue(result["report_preserved"])
        # The same source/stage/session has one ordered transfer; an invalid
        # transfer must never fabricate an attempt or lend another grant bytes.
        for mutation in ("cross-source", "cross-stage", "wrong-index", "wrong-receipt"):
            with self.subTest(mutation=mutation), _service() as fixture:
                _initialize(fixture)
                _receive(fixture, "slice", "我昨晚没有失眠")
                prepared = _prepare(fixture, "ticket130:slice", "intake")
                self.assertIsNotNone(prepared["grant"])
                payload = {"source_causal_id": "ticket130:slice", "stage": "intake",
                           "grant": prepared["grant"], "index": 0}
                if mutation == "cross-source": payload["source_causal_id"] = "ticket130:foreign"
                if mutation == "cross-stage": payload["stage"] = "answer"
                if mutation == "wrong-index": payload["index"] = 1
                if mutation == "wrong-receipt":
                    request, receipt, _ = _request(fixture, "ticket130:slice", "intake", prepared)
                    receipt = dict(receipt, digest="sha256:" + "0" * 64)
                    value = _request_or_denial(fixture.port, "controlled-effect", _OPERATION("nondiagnostic-start", {
                        "source_causal_id": "ticket130:slice", "stage": "intake", "grant": prepared["grant"],
                        "request_receipt": receipt}))
                    self._assert_start_denied(value)
                else:
                    value = _request_or_denial(fixture.port, "controlled-effect", _OPERATION("nondiagnostic-request-chunk", payload))
                    # A successful slice has no state field. Require actual
                    # wire refusal, so no health bytes can escape to the wrong
                    # source/stage/index even when no attempt has started.
                    self.assertIsNone(value, "invalid slice returned a payload or body bytes")
                valid_slice = {"source_causal_id": "ticket130:slice", "stage": "intake",
                               "grant": prepared["grant"], "index": 0}
                self.assertIsNone(_request_or_denial(fixture.port, "controlled-effect", _OPERATION(
                    "nondiagnostic-request-chunk", valid_slice)), "invalid transfer did not close its original grant")
                # The original correct descriptor cannot revive a closed
                # transfer, including after a fully read wrong-receipt case.
                self._assert_start_denied(_request_or_denial(fixture.port, "controlled-effect", _OPERATION(
                    "nondiagnostic-start", {"source_causal_id": "ticket130:slice", "stage": "intake",
                        "grant": prepared["grant"], "request_receipt": prepared["request_transfer"]})))
                self.assertIsNone(fixture.service._core.model_effect_report(prepared["intent"]["effect_id"]))
                self.assertNotIn(_read(fixture, "ticket130:slice")["state"], {"attempted", "completed", "unknown"})
        with _service() as fixture:
            _initialize(fixture); _receive(fixture, "stale", "我昨晚没有失眠")
            prepared = _prepare(fixture, "ticket130:stale", "intake")
            _, receipt, _ = _request(fixture, "ticket130:stale", "intake", prepared)
            fixture.client.get_error = TimeoutError("offline current-head unavailable after prepare")
            result = _request_or_denial(fixture.port, "controlled-effect", _OPERATION("nondiagnostic-start", {
                "source_causal_id": "ticket130:stale", "stage": "intake", "grant": prepared["grant"],
                "request_receipt": receipt}))
            self._assert_start_denied(result)

    def test_v130_04_started_unknown_completed_candidate_loss_and_terminal_recovery_never_recall(self):
        self._modules()
        for gate in ("known-incomplete", "known-failed", "unknown", "complete-loss", "candidate-loss", "peer-exit"):
            with self.subTest(gate=gate), _service() as fixture:
                _initialize(fixture)
                first = self._run_child(gate, fixture)
                self.assertEqual(first["model_calls"], 1)
                source = first["source"]
                status = _await_status(fixture, source, {"completed", "finalized", "failed-closed", "unknown", "owner-decision-required"})
                effect_id = first["effect_id"]
                if gate.startswith("known-"):
                    report = fixture.service._core.model_effect_report(effect_id)
                    self.assertEqual(report.model_status, gate.removeprefix("known-"))
                    self.assertTrue(report.terminal_proven)
                    self.assertTrue(first["visible_limits"])
                    self.assertEqual(fixture.service._core.daily_state().evidence_cards, ())
                    continue
                if gate in {"complete-loss", "candidate-loss"}:
                    report = fixture.service._core.model_effect_report(effect_id)
                    self.assertIsNotNone(report)
                    self.assertEqual(report.model_status, "completed")
                    self.assertEqual(report.actual_model, fixture.budget.route.requested_model)
                    retained_report = report.to_storage()
                if gate == "complete-loss":
                    self.assertTrue(first["recovered"])
                else:
                    from partner_health_steward.production_core_service import ProductionCoreService
                    fixture.service.close()
                    restarted = ProductionCoreService(fixture.binding, current_head=fixture.head, live_runtime=fixture.runtime)
                    fixture.service = restarted; fixture.port = delivery_fixture._SocketPort(restarted.start())
                    second = self._run_child("resume-only", fixture, data={"source": source})
                    self.assertEqual(second["model_calls"], 0)
                    self.assertTrue(second["visible_limits"])
                    status = _read(fixture, source)
                    self.assertIn(status["state"], {"unknown", "owner-decision-required"})
                    self.assertIsNone(fixture.port.exchange("managed-read", _PROJECTION(
                        "health-entry-cursor-directive", {"source_causal_id": source}))["directive"])
                    self.assertEqual(fixture.service._core.daily_state().evidence_cards, ())
                    if gate == "candidate-loss":
                        self.assertEqual(fixture.service._core.model_effect_report(effect_id).to_storage(), retained_report)

    def test_v130_05_real_owner_controls_one_shot_task_current_wake_and_visible_results(self):
        self._modules()
        with _service() as fixture:
            _initialize(fixture)
            result = self._run_child("controls", fixture)
            self.assertEqual(result["model_calls"], 0)
            self.assertTrue(result["visible_results"])
            core = fixture.service._core
            self.assertFalse(core.owner_settings_state().recording_stopped)
            self.assertFalse(core.owner_settings_state().proactive_support_paused)
            tasks = core.task_state().tasks
            self.assertEqual(len(tasks), 1)
            approval = next(item for item in core.owner_settings_state().approvals if item.task_id == tasks[0].task_id)
            self.assertEqual(approval.max_attempts, 1)
            self.assertFalse(approval.revoked)
            self.assertEqual(tasks[0].approval.approval_id, approval.approval_id)
            self.assertEqual(len(tasks[0].external_boundary.recipient_refs), 1)
            fixture.clock[0] += timedelta(minutes=3)
            first = self._run_child("wake", fixture)
            self.assertTrue(first["visible_results"])
            completed = core.owner_settings_state().completed_review_keys
            self.assertTrue(completed)
            self.assertEqual(core.task_state().tasks[0].primary_label, "solved")
            self.assertEqual(core.task_state().tasks[0].phase, "accepted")
            second = self._run_child("wake", fixture)
            self.assertEqual(second["new_sends"], 0)
            self.assertEqual(core.owner_settings_state().completed_review_keys, completed)
            self.assertEqual(len(core.task_state().tasks), 1)
        with _service() as fixture:
            _initialize(fixture)
            result = self._run_child("task-cancel", fixture)
            self.assertEqual(result["model_calls"], 0)
            self.assertEqual(fixture.service._core.task_state().tasks[0].primary_label, "cancelled")
            fixture.clock[0] += timedelta(minutes=3)
            wake = self._run_child("wake-cancelled", fixture)
            self.assertEqual(wake["task_sends"], 0)

    def test_v130_06_actual_owner_rights_correction_recording_privacy_and_independent_delete(self):
        self._modules()
        with _service() as fixture:
            _initialize(fixture)
            seeded = self._run_child("seed", fixture)
            objects = fixture.service._core.managed_rights_read_current()
            evidence = next(item for item in objects if item.object_kind == "evidence_card")
            original = evidence.to_wire()
            corrected = self._run_child("rights", fixture, data={"object_ref": evidence.object_ref})
            self.assertEqual(corrected["model_calls"], 0)
            self.assertTrue(corrected["visible_results"])
            state = fixture.service._core.daily_state()
            self.assertTrue(state.owner_correction_revisions)
            self.assertTrue(any("我昨晚睡得很好" in item.content for item in state.evidence_cards))
            self.assertNotEqual([x.to_wire() for x in fixture.service._core.managed_rights_read_current()], [original])
            private = self._run_child("recording-private", fixture)
            self.assertEqual(private["model_calls"], 1)
            self.assertNotIn(private["sentinel"], repr(fixture.service._core.daily_state()))
            for path in fixture.root.rglob("*"):
                if path.is_file() and path.stat().st_size <= 16777216:
                    self.assertNotIn(private["sentinel"].encode(), path.read_bytes(), str(path))
        with _service() as fixture:
            _initialize(fixture)
            self._run_child("seed", fixture)
            core = fixture.service._core
            before = core.managed_rights_read_current()
            self.assertTrue(any(item.object_kind == "evidence_card" for item in before))
            self.assertTrue(core.daily_state().evidence_cards)
            self.assertFalse(fixture.head.read().head.terminal)
            self.assertEqual(core.managed_lifecycle_read(None)["phase"], "idle")
            replica_paths = tuple(Path(path) for path in fixture.binding["managed_replica_bindings"].values())
            self.assertTrue(replica_paths and all(path.is_file() for path in replica_paths))
            outcome = self._run_child("delete", fixture)
            self.assertEqual(outcome["model_calls"], 0)
            self.assertGreater(outcome["notice_send_count"], 0)
            operation_ref = outcome["operation_ref"]
            view = core.managed_lifecycle_read(operation_ref)
            self.assertEqual(view["operation_ref"], operation_ref)
            self.assertEqual(view["phase"], "completed")
            self.assertEqual(view["status"], "completed")
            self.assertEqual(view["mode"], "terminal")
            self.assertFalse(view["source_active"] or view["target_active"])
            authority = fixture.head.read().head.as_authority()
            self.assertTrue(authority.terminal)
            self.assertEqual(authority.transition_id, "lifecycle:terminal-delete:" + operation_ref)
            self.assertEqual(view["authority_binding"], authority.to_storage())
            request = {"operation_ref": operation_ref, "authority_binding": authority.to_storage(),
                       "transition_id": authority.transition_id}
            from partner_health_steward.host_authority import HostPrivateKeyProvider, HostAuthorityUnavailable
            from partner_health_steward.production_core_service import FilesystemManagedReplicaAdapter
            key = HostPrivateKeyProvider(fixture.binding["host_private_paths"], fixture.binding["installation_id"])
            self.assertEqual(key.absence(request), {"status": "absent"})
            with self.assertRaises(HostAuthorityUnavailable):
                key.get_key()
            replicas = FilesystemManagedReplicaAdapter(fixture.binding["managed_replica_root"],
                fixture.binding["installation_id"], fixture.binding["managed_replica_bindings"],
                fixture.binding["lifecycle_release"].get("unbound_real_providers", ()))
            absent = replicas.absence(request)
            self.assertEqual(absent["status"], "absent")
            self.assertEqual(absent["remains_unproven"], view["remains_unproven"])
            self.assertTrue(all(not path.exists() for path in replica_paths))
            with self.assertRaises(AuthorityValidationError):
                core.managed_rights_read_current()
            # Generic storage-system absence oracle, as in the original117
            # gate: enumerate all tables and count rows without product table
            # names, columns, encrypted payloads or private store internals.
            database = Path(fixture.binding["database_path"]).resolve()
            with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
                tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                self.assertTrue(tables)
                for (table,) in tables:
                    quoted = '"' + table.replace('"', '""') + '"'
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM " + quoted).fetchone()[0], 0, table)
            self.assertFalse(core.health_writes_allowed())
            self.assertFalse(core.model_effects_allowed())
            self.assertFalse(core.outbound_effects_allowed())

    def test_v130_07_managed_json_file_real_pinned_media_second_authorization_and_no_false_delivery(self):
        self._modules()
        for mode in ("accepted", "rejected", "send-loss", "bad-upload-url", "unavailable-after-read"):
            with self.subTest(mode=mode), _service() as fixture:
                _initialize(fixture)
                self._run_child("seed-large" if mode == "accepted" else "seed", fixture)
                result = self._run_child("export", fixture, data={"mode": mode})
                self.assertEqual(result["model_calls"], 0)
                self.assertTrue(result["two_authorizations"])
                self.assertTrue(result["artifact_from_core"])
                if mode == "unavailable-after-read":
                    self.assertEqual(result["media_posts"], 0)
                    self.assertTrue(result["second_authorization_denied"])
                elif mode == "bad-upload-url":
                    self.assertEqual(result["media_posts"], 1)
                    self.assertEqual(result["layer"], "unknown")
                else:
                    self.assertEqual(result["media_posts"], 3)
                    if mode == "accepted": self.assertGreater(result["artifact_size"], 65536)
                    self.assertTrue(result["decrypted_equals_canonical_export"])
                    self.assertEqual(result["layer"], {"accepted": "accepted", "rejected": "rejected", "send-loss": "unknown"}[mode])
                    self.assertEqual(result["replay_posts"], 0)
                    self.assertTrue(result["external_copy_limit_visible"])
                    self.assertNotIn(result["layer"], {"delivered", "read", "downloaded"})


class _HTTPResponse:
    def __init__(self, value=None, *, status=200, headers=None, binary=None):
        self.value, self.status, self.ok = value, status, status == 200
        self.headers = headers or {}
        self.binary = binary
    async def __aenter__(self):
        if isinstance(self.value, BaseException): raise self.value
        return self
    async def __aexit__(self, *args): return None
    async def text(self):
        if isinstance(self.value, BaseException): raise self.value
        return json.dumps(self.value)
    async def read(self): return self.binary if self.binary is not None else (await self.text()).encode()


class _ChannelHTTP:
    """The pinned functions still own JSON/media wire; replace HTTP only."""
    def __init__(self, *, export_mode="accepted"):
        self.batches, self.cursors, self.sends, self.posts, self.sessions = [], [], [], [], []
        self.media_posts, self.ticket, self.ciphertext = [], None, None
        self.requests = []
        self.export_mode = export_mode

    def factory(self, **options):
        assert options.get("trust_env", False) is False
        router = self
        class Session:
            def __init__(self):
                self.loop = id(asyncio.get_running_loop()); self.closed = False
            async def __aenter__(self): return self
            async def __aexit__(self, *args): self.closed = True
            async def close(self): self.closed = True
            def post(self, url, *, data, headers=None, **kwargs):
                router.requests.append((url, copy.deepcopy(headers or {}), copy.deepcopy(kwargs)))
                assert self.loop == id(asyncio.get_running_loop()), "session crossed event loops"
                assert kwargs.get("allow_redirects") is False
                if url.startswith("https://novac2c.cdn.weixin.qq.com/"):
                    from urllib.parse import urlsplit, parse_qs
                    parsed = urlsplit(url)
                    query = parse_qs(parsed.query, strict_parsing=True)
                    assert parsed.scheme == "https" and parsed.netloc == "novac2c.cdn.weixin.qq.com"
                    assert parsed.path == "/c2c/upload" and not parsed.fragment
                    assert set(query) == {"encrypted_query_param", "filekey"}
                    assert query["filekey"] == [router.ticket["filekey"]]
                    assert query["encrypted_query_param"] == ["synthetic-upload-ticket"]
                    assert not any("authorization" == key.lower() for key in (headers or {}))
                    assert isinstance(data, bytes) and _TOKEN.encode() not in data
                    router.ciphertext = data
                    router.media_posts.append((url, data))
                    return _HTTPResponse({}, headers={"x-encrypted-param": "synthetic-cdn-ticket"})
                assert url.startswith("https://ilinkai.weixin.qq.com/ilink/bot/")
                body = json.loads(data)
                router.posts.append((url, copy.deepcopy(body)))
                if url.endswith("getupdates"):
                    cursor = body["get_updates_buf"]
                    router.cursors.append(cursor)
                    value = router.batches.pop(0) if router.batches else {"ret": 0, "msgs": [], "get_updates_buf": cursor}
                    return delivery_fixture._PollResponse(value)
                if url.endswith("getuploadurl"):
                    router.ticket = copy.deepcopy(body)
                    router.media_posts.append((url, copy.deepcopy(body)))
                    if router.export_mode == "bad-upload-url":
                        return _HTTPResponse({"ret": 0, "errcode": 0, "upload_full_url": "https://unapproved.invalid/c2c/upload?encrypted_query_param=bad&filekey=" + body["filekey"]})
                    return _HTTPResponse({"ret": 0, "errcode": 0, "upload_param": "synthetic-upload-ticket"})
                assert url.endswith("sendmessage"), url
                msg = body["msg"]
                router.sends.append(copy.deepcopy(msg))
                if msg["item_list"][0]["type"] == 4:
                    router.media_posts.append((url, copy.deepcopy(body)))
                    if router.export_mode == "send-loss":
                        return _HTTPResponse(TimeoutError("synthetic final-file response lost"))
                    return _HTTPResponse({"ret": 7, "errcode": 7} if router.export_mode == "rejected" else {"ret": 0, "errcode": 0})
                return _HTTPResponse({"ret": 0, "errcode": 0})
        session = Session(); self.sessions.append(session)
        return session

    def enqueue(self, cursor, native):
        self.batches.append({"ret": 0, "msgs": [copy.deepcopy(native)], "get_updates_buf": cursor})

    def texts(self):
        return [item["text_item"]["text"] for msg in self.sends for item in msg["item_list"] if item["type"] == 1]


class _TracePort:
    def __init__(self, client, *, mode=None):
        self.client, self.mode = client, mode
        self.calls, self.responses, self.frames, self.results = [], [], [], {}
        self.effect_ids, self.transfers = [], {}
        self.completed, self.blocked_advances, self.lost_reply = False, 0, False
        self.read_artifact = bytearray()
        self.artifact_metadata = None
        self.authorizations = []
        self.authorization_replies = []
        self.denied = []

    def request(self, kind, payload, *, request_id=None):
        request_id = request_id or "ticket130-child-rpc"
        envelope = {"protocol_version": 1, "kind": kind, "request_id": request_id, "payload": payload}
        self.frames.append(len(_CANONICAL(envelope)))
        assert self.frames[-1] <= 65536
        self.calls.append((kind, copy.deepcopy(payload)))
        operation = payload.get("operation")
        if operation == "governed-advance" and self.completed and self.mode == "candidate-loss":
            self.blocked_advances += 1
            raise ConnectionResetError("synthetic caller stops before using the completed candidate")
        try:
            response = self.client.request(kind, payload, request_id=request_id)
        except _HostVerificationFailure as exc:
            assert str(exc) == "core-frame-truncated", str(exc)
            self.denied.append((kind, copy.deepcopy(payload), str(exc)))
            raise
        self.frames.append(len(_CANONICAL(response)))
        assert self.frames[-1] <= 65536
        self.responses.append(copy.deepcopy(response))
        value = response["payload"]
        if operation == "nondiagnostic-prepare" and value.get("grant"):
            self.effect_ids.append(value["intent"]["effect_id"])
        if operation == "nondiagnostic-result-chunk":
            data = payload["payload"]
            effect = data["grant"]["effect_id"]
            buffer = self.transfers.setdefault(effect, bytearray())
            buffer.extend(base64.b64decode(data["bytes_b64"], validate=True))
            if value["next_index"] is None:
                wire = json.loads(buffer)
                assert _CANONICAL(wire) == buffer
                self.results[effect] = wire
        if operation == "nondiagnostic-complete":
            self.completed = True
            if self.mode == "complete-loss" and not self.lost_reply:
                self.lost_reply = True
                raise ConnectionResetError("synthetic lost terminal reply after actual Core commit")
        if operation == "delivery-authorize":
            self.authorization_replies.append(copy.deepcopy(value))
        if operation == "delivery-authorize" and type(value.get("authorization")) is dict and value["authorization"]["purpose"] == "export-artifact":
            self.authorizations.append(copy.deepcopy(value))
        if operation == "export-artifact-read" and value.get("artifact"):
            artifact = value["artifact"]
            metadata = {key: artifact[key] for key in ("artifact_ref", "filename", "size_bytes", "digest")}
            assert self.artifact_metadata is None or self.artifact_metadata == metadata
            self.artifact_metadata = metadata
            assert artifact["index"] == len(self.read_artifact) // 32768
            chunk = base64.b64decode(artifact["bytes_b64"], validate=True)
            assert 1 <= len(chunk) <= 32768
            assert artifact["next_index"] == (None if artifact["index"] + 1 == artifact["chunk_count"] else artifact["index"] + 1)
            assert artifact["next_index"] is None or len(chunk) == 32768
            self.read_artifact.extend(chunk)
        return response


def _exchange(port, kind, name, payload=None):
    wrapper = _PROJECTION if kind == "managed-read" else _OPERATION
    response = port.request(kind, wrapper(name, payload))
    assert response["status"] == "accepted", response
    return response["payload"]


def _native(config, identifier, text, *, minute=5):
    value = delivery_fixture._native_message("native130:" + identifier, text, config["policy"])
    natural = identifier in {"record", "mixed", "question", "seed", "wide-chunks", "private-body", "correction"} or identifier.startswith(("recovery-", "seed-large-"))
    at = datetime(2026, 8, 24, 1, minute, 1, tzinfo=timezone.utc) if natural else datetime.fromisoformat(config["now"]) + timedelta(seconds=1)
    value["create_time_ms"] = int(at.timestamp() * 1000)
    return value


def _source_message(port, config, identifier, text):
    """Explicit synthetic owner source for low-level transport mutations only."""
    headers = {"causal_id": "ticket130:" + identifier, "channel": "weixin",
               "partner_id": config["policy"]["partner_id"], "sender_id": config["policy"]["owner_sender_id"],
               "conversation_id": config["policy"]["conversation_id"], "chat_type": "private",
               "entrypoint": "health_weixin", "message_id": "native130:" + identifier,
               "protocol_timestamp": "2026-08-24T09:05:00+08:00", "received_at": "2026-08-24T09:05:01+08:00",
               "native_cursor": "cursor130:" + identifier}
    ready = _exchange(port, "managed-read", "health-entry-preflight", {"headers": headers})
    return {**headers, "generation": ready["current_generation"], "requested_capability": "health-steward", "body": text}


class _ModelHTTP:
    def __init__(self, port, config):
        self.port, self.config = port, config
        self.queue, self.calls, self.errors, self.probes = [], [], [], []
        self.response_bytes = []

    def factory(self, **kwargs):
        import httpx
        assert kwargs == {"retries": 0}
        def handler(request):
            try:
                assert request.method == "POST"
                assert str(request.url) == self.config["route"]["canonical_base_url"] + "/responses"
                assert request.headers["authorization"] == "Bearer " + _TOKEN
                body = json.loads(request.content)
                assert body["store"] is False and body["stream"] is True and body["max_output_tokens"] == 2048
                assert len(request.content) <= 65536
                from partner_health_steward.model_adapter import NONDIAGNOSTIC_OPERATION_SCHEMA_NAME
                name = body["text"]["format"]["name"]
                assert name in {"nondiagnostic-intake-v1", NONDIAGNOSTIC_OPERATION_SCHEMA_NAME}
                stage = "intake" if name == "nondiagnostic-intake-v1" else "answer"
                expected_stage, candidate, options = self.queue.pop(0)
                assert stage == expected_stage, (stage, expected_stage)
                self.calls.append((stage, body))
                # A second actual AF_UNIX request must return while model HTTP
                # is outstanding. Its state may legitimately be UNKNOWN.
                probe = self.port.client.request("command", {"operation": "health-runtime-probe"},
                                                 request_id="ticket130-concurrent-core-lock-probe")
                assert probe["status"] == "accepted" and isinstance(probe["payload"], dict)
                self.probes.append(probe)
                if options.get("timeout"):
                    raise httpx.ReadTimeout("synthetic model terminal unobserved")
                from partner_health_steward.model_contract import FirstHopRoute
                route = FirstHopRoute.from_wire(self.config["route"])
                raw = _raw(route, candidate, status=options.get("status", "completed"),
                           response_id=("response:" + "\x01" * 11000 + "中") if options.get("wide") else "response:ticket130-offline")
                encoded = _CANONICAL(raw)
                self.response_bytes.append(encoded)
                return httpx.Response(200, content=encoded, headers={"content-type": "application/json"})
            except httpx.ReadTimeout:
                raise
            except BaseException as exc:
                self.errors.append(repr(exc))
                raise
        return httpx.MockTransport(handler)

    def add(self, stage, candidate, **options):
        self.queue.append((stage, copy.deepcopy(candidate), options))


async def _wait(predicate):
    for _ in range(800):
        result = predicate()
        if result: return result
        await asyncio.sleep(0.01)
    raise AssertionError("real published lifecycle did not reach its bounded observation")


async def _child(config):
    from unittest.mock import patch
    from gateway.platforms.weixin import ContextTokenStore
    from partner_health_steward.live_weixin import LiveHealthWeixinAdapter
    from partner_health_steward.live_nondiagnostic import create_live_nondiagnostic_model_bridge
    core = _CorePortClient(config["endpoint"])
    gate = config["gate"]
    port = _TracePort(core, mode=gate)
    channel = _ChannelHTTP(export_mode=config["data"].get("mode", "accepted"))
    models = _ModelHTTP(port, config)
    store = ContextTokenStore(os.environ["HERMES_HOME"])
    store.set(config["policy"]["partner_id"], config["policy"]["owner_sender_id"], "synthetic-context")
    ordinary = []
    extra = {"admission_policy": config["policy"], "core_port": port,
             "initialization_template": config["initialization"],
             "weixin_transport_binding": {"account_id": config["policy"]["partner_id"],
                                          "base_url": "https://ilinkai.weixin.qq.com"},
             "nondiagnostic_model_binding": {"route": config["route"], "budget": config["budget"],
                                              "credential_provider": lambda: _TOKEN}}
    if gate in {"wake", "wake-cancelled"}:
        # Only the declared business clock advances in due-task tests. Keep
        # the real126 Bridge and real pinned sender on that same fixture clock;
        # the full trace/export gates exercise production autowire unchanged.
        from partner_health_steward.live_delivery import LiveWeixinDeliveryBridge
        from partner_health_steward.weixin_transport import WeixinTransportBinding, PinnedWeixinOwnerDeliveryAdapter
        binding = WeixinTransportBinding(config["policy"]["partner_id"], "https://ilinkai.weixin.qq.com")
        extra["delivery_transport"] = LiveWeixinDeliveryBridge(port,
            lambda authorization: PinnedWeixinOwnerDeliveryAdapter(binding, authorization,
                token="synthetic-token", context_token_provider=lambda recipient: "synthetic-context"),
            clock=lambda: datetime.fromisoformat(config["now"]))
    native_times = {}
    async def owner(text, identifier, *, allow_no_cursor=False, minute=5):
        before_sends = len(channel.sends)
        before_polls = len(channel.cursors)
        message = _native(config, identifier, text, minute=minute)
        # Replays retain exact protocol time; independent sources are later.
        timestamp = native_times.setdefault(identifier, message["create_time_ms"] + len(native_times) * 1000)
        message["create_time_ms"] = timestamp
        cursor = "cursor130:" + identifier
        channel.enqueue(cursor, message)
        if allow_no_cursor:
            return cursor, before_sends
        await _wait(lambda: len(channel.cursors) >= before_polls + 2 and not channel.batches and cursor in channel.cursors)
        assert _exchange(port, "managed-read", "health-entry-native-cursor")["native_cursor"] == cursor
        return cursor, before_sends
    def ready():
        return _exchange(port, "managed-read", "health-entry-initialization")["initialization"]["phase"]
    def sources():
        return [value["payload"]["message"]["causal_id"] for kind, value in port.calls
                if kind == "command" and value.get("operation") == "governed-receive"]
    def latest_response():
        values = [value["payload"] for value in port.responses
                  if type(value.get("payload")) is dict and set(value["payload"]) == _STAGE_FIELDS]
        return values[-1] if values else None
    async def visible(text, identifier, *, expected=None, minute=5):
        before = len(channel.sends)
        await owner(text, identifier, minute=minute)
        await _wait(lambda: len(channel.sends) > before)
        new = channel.texts()
        if expected is not None: assert any(expected in value for value in new), (expected, new)
        refs = [value["payload"]["delivery_refs"] for value in port.responses
                if type(value.get("payload")) is dict and "delivery_refs" in value["payload"]]
        assert any(refs), "actual visible result needs a Core-issued owner-outbox reference"
        return new[-1]
    with patch("aiohttp.ClientSession", channel.factory), patch("httpx.HTTPTransport", models.factory):
        adapter = delivery_fixture._create_registered(extra)
        assert type(adapter) is LiveHealthWeixinAdapter
        adapter.set_message_handler(lambda event: ordinary.append(event))
        assert await adapter.connect(is_reconnect=False)
        try:
            if gate == "trace":
                assert ready() == "uninitialized"
                await owner("/health-init", "init-request")
                await _wait(lambda: any("/health-init-confirm" in value for value in channel.texts()))
                assert ready() == "uninitialized" and not models.calls
                match = re.search(r"/health-init-confirm\s+(\S+)\s+(\S+)", "\n".join(channel.texts()))
                assert match
                await visible("/health-init-confirm " + " ".join(match.groups()), "init-confirm",
                              expected="健康管家已初始化；诊断未启用")
                assert ready() == "enabled" and not models.calls
                assert any(_LIMIT in text for text in channel.texts())
                initial_count = len(channel.sends)
                await owner("/health-init-confirm " + " ".join(match.groups()), "init-confirm")
                assert len(channel.sends) == initial_count, "same confirm source must not mint a second success"
                text = "我昨晚没有失眠"
                models.add("intake", _intake(text))
                await visible(text, "record")
                assert len(models.calls) == 1
                record_response = latest_response()
                record_turn = record_response["response"]["meta"]["turn_result"]
                assert record_turn["evidence_ids"]
                assert {item["canonical_name"] for item in record_turn["skill_disclosures"]} == {"health-steward", "health-evidence", "health-portrait"}
                mixed_fact = "我昨晚确实没有失眠"
                mixed = mixed_fact + "；今天怎样安排休息？"
                models.add("intake", _intake(mixed, operation="mixed", fact=mixed_fact, question="今天怎样安排休息？"))
                models.add("answer", config["answer"])
                mixed_reply = await visible(mixed, "mixed")
                assert config["approved_reply"] in mixed_reply and "claim-support" not in mixed_reply
                question = "我是不是糖尿病？"
                models.add("intake", _intake(question, operation="question", question=question, time_text=None))
                models.add("answer", config["answer"])
                question_reply = await visible(question, "question")
                assert config["approved_reply"] in question_reply and "claim-support" not in question_reply
                for text in channel.texts()[initial_count:]:
                    assert _LIMIT in text, "record and approved answer must actually show131 limitation"
                records = [result["payload"]["response"]["meta"]["turn_result"]["record_id"]
                           for result in port.responses if type(result.get("payload")) is dict
                           and result["payload"].get("response", {}).get("meta", {}).get("turn_result")]
                before = (len(models.calls), len(channel.sends))
                await owner(question, "question")
                assert (len(models.calls), len(channel.sends)) == before
                result = {"model_stages": [stage for stage, _ in models.calls],
                          "kinds": sorted({kind for kind, _ in port.calls}), "initialized_message": True,
                          "ordinary_calls": len(ordinary), "effects": list(dict.fromkeys(port.effect_ids)),
                          "results": port.results, "records": list(dict.fromkeys(records)), "replay_unchanged": True}
            elif gate == "seed":
                text = "我昨晚没有失眠"
                models.add("intake", _intake(text))
                await visible(text, "seed")
                result = {"model_calls": len(models.calls), "source": sources()[-1]}
            elif gate == "seed-large":
                # Four bounded record inputs form real managed owner objects;
                # do not hand the export adapter caller-created file bytes.
                for batch in range(4):
                    quotes = ["我昨晚没有失眠（合成编号" + str(batch * 8 + i) + "：" + "x" * 1450 + "）" for i in range(8)]
                    text = "\n".join(quotes)
                    assert len(text.encode()) < 16384
                    facts = [_intake(text, fact=quote)["facts"][0] for quote in quotes]
                    models.add("intake", {"operation": "record", "facts": facts, "question": None})
                    await visible(text, "seed-large-" + str(batch))
                result = {"model_calls": len(models.calls)}
            elif gate in {"known-incomplete", "known-failed", "unknown", "complete-loss", "candidate-loss"}:
                text = "我昨晚没有失眠"
                models.add("intake", _intake(text), timeout=gate == "unknown",
                           status=gate.removeprefix("known-") if gate.startswith("known-") else "completed")
                cursor, _ = await owner(text, "recovery-" + gate, allow_no_cursor=True)
                await _wait(lambda: models.calls and port.effect_ids)
                source = sources()[-1]
                if gate.startswith("known-"):
                    await _wait(lambda: port.completed and any(_LIMIT in text for text in channel.texts()))
                    assert len(models.calls) == 1 and "RAW_ERROR_MUST_NOT_ESCAPE" not in repr(channel.sends)
                elif gate == "unknown":
                    await _wait(lambda: _exchange(port, "managed-read", "health-entry-nondiagnostic", {"source_causal_id": source})["state"] in {"unknown", "owner-decision-required"})
                    await _wait(lambda: any(_LIMIT in text for text in channel.texts()))
                    assert cursor not in channel.cursors
                elif gate == "candidate-loss":
                    await _wait(lambda: port.completed and port.blocked_advances)
                    assert cursor not in channel.cursors
                else:
                    await _wait(lambda: cursor in channel.cursors)
                    assert port.lost_reply and len(models.calls) == 1
                result = {"model_calls": len(models.calls), "source": source,
                          "effect_id": port.effect_ids[0], "recovered": gate == "complete-loss",
                          "visible_limits": any(_LIMIT in text for text in channel.texts())}
            elif gate == "resume-only":
                bridge = create_live_nondiagnostic_model_bridge(port,
                    route=config["route"], budget=config["budget"], credential_provider=lambda: _TOKEN)
                outcome = await bridge.advance_source(config["data"]["source"])
                assert set(outcome) == _STAGE_FIELDS
                assert outcome["delivery_refs"], "unresolved original source needs its Core-bound minimal limitation"
                from partner_health_steward.live_delivery import LiveWeixinDeliveryBridge
                from partner_health_steward.weixin_transport import WeixinTransportBinding, PinnedWeixinOwnerDeliveryAdapter
                binding = WeixinTransportBinding(config["policy"]["partner_id"], "https://ilinkai.weixin.qq.com")
                delivery = LiveWeixinDeliveryBridge(port,
                    lambda authorization: PinnedWeixinOwnerDeliveryAdapter(binding, authorization,
                        token="synthetic-token", context_token_provider=lambda recipient: "synthetic-context"),
                    clock=lambda: datetime.fromisoformat(config["now"]))
                for ref in outcome["delivery_refs"]:
                    observed = await delivery.send_committed(ref)
                    assert observed["handoff_complete"]
                assert not models.calls and any(_LIMIT in text for text in channel.texts())
                result = {"model_calls": 0, "visible_limits": True}
            elif gate == "peer-exit":
                # Direct declared CorePort sequence leaves an actual started
                # attempt with no result callback, then this real process exits.
                source = "ticket130:peer-exit"
                message = _source_message(port, config, "peer-exit", "我昨晚没有失眠")
                _exchange(port, "command", "governed-receive", {"message": message})
                prepared = _exchange(port, "controlled-effect", "nondiagnostic-prepare", {"source_causal_id": source, "stage": "intake"})
                fixture = types.SimpleNamespace(port=types.SimpleNamespace(exchange=lambda kind, payload: port.request(kind, payload)["payload"]))
                request, receipt, _ = _request(fixture, source, "intake", prepared)
                started = _start(fixture, source, "intake", prepared, receipt)
                assert started["state"] == "attempted"
                from partner_health_steward.model_adapter import ProductionModelAdapter, BoundResponsesTransport, NonDiagnosticBudgetInputMeasurementStrategy
                from partner_health_steward.model_contract import NonDiagnosticOperationalBudget, FirstHopRoute
                route = FirstHopRoute.from_wire(config["route"]); budget = NonDiagnosticOperationalBudget.from_wire(config["budget"])
                strategy = NonDiagnosticBudgetInputMeasurementStrategy(budget)
                actual = ProductionModelAdapter(route, budget, transport=BoundResponsesTransport(route, credential_provider=lambda: _TOKEN), measurement_strategy=strategy)
                models.add("intake", _intake("我昨晚没有失眠"))
                observed = await asyncio.to_thread(actual.execute, request.to_wire())
                assert observed.status == "completed" and len(models.calls) == 1
                result = {"model_calls": 1, "source": source, "effect_id": prepared["intent"]["effect_id"]}
            elif gate == "chunks":
                text = "我是不是糖尿病？"
                models.add("intake", _intake(text, operation="question", question=text, time_text=None), wide=True)
                models.add("answer", config["answer"], wide=True)
                await visible(text, "wide-chunks")
                requests = [response["payload"]["request_transfer"] for response in port.responses
                            if type(response.get("payload")) is dict and response["payload"].get("request_transfer")]
                pieces = [response["payload"]["bytes_b64"] for response in port.responses
                          if type(response.get("payload")) is dict and "request_transfer" in response["payload"] and "bytes_b64" in response["payload"]]
                split = False
                for value in pieces:
                    try: base64.b64decode(value, validate=True).decode("utf-8")
                    except UnicodeDecodeError: split = True
                assert port.results
                result = {"request_size": max(item["size_bytes"] for item in requests),
                          "result_size": max(len(_CANONICAL(item)) for item in port.results.values()),
                          "frame_sizes": port.frames, "split_utf8": split,
                          "probes_during_http": len(models.probes), "model_calls": len(models.calls),
                          "report_preserved": all(item["actual_model"] == config["route"]["requested_model"] and item["usage_input_tokens"] == 219 for item in port.results.values())}
            elif gate in {"controls", "task-cancel"}:
                for identifier, command, expected in (
                    ("status", "/health-status", None), ("pause", "/health-pause", "暂停"),
                    ("resume", "/health-resume", "恢复"), ("stop", "/health-recording-stop", "停止记录"),
                    ("record-resume", "/health-recording-resume", "恢复")):
                    await visible(command, identifier, expected=expected)
                from zoneinfo import ZoneInfo
                when = (datetime.fromisoformat(config["now"]).astimezone(ZoneInfo("Asia/Shanghai")) + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M")
                task_command = "/health-task-once " + when + " 合成提醒喝水"
                await visible(task_command, "task-once")
                task_text = channel.texts()[-1]
                assert "合成提醒喝水" in task_text and "一次" in task_text
                assert any("取消" in text for text in channel.texts())
                if gate == "task-cancel":
                    match = re.search(r"/health-task-cancel\s+(\S+)", task_text)
                    assert match, "task result must expose its actual cancellation command"
                    await visible(match.group(0), "task-cancel", expected="取消")
                before = len(channel.sends)
                await owner(task_command, "task-once")
                assert len(channel.sends) == before and not models.calls
                foreign = _native(config, "foreign-owner-command", "/health-pause")
                foreign["from_user_id"] = "not-the-owner"
                polls = len(channel.cursors)
                channel.enqueue("cursor130:foreign-owner-command", foreign)
                await _wait(lambda: not channel.batches and len(channel.cursors) >= polls + 2)
                assert len(channel.sends) == before and not models.calls
                result = {"model_calls": 0, "visible_results": True}
            elif gate in {"wake", "wake-cancelled"}:
                before = len(channel.sends)
                result_rpc = await adapter.wake_current()
                # Wait for same Core-authorized effects, never a timer callback.
                assert isinstance(result_rpc, dict)
                await asyncio.sleep(0)
                task_sends = sum("合成提醒喝水" in value for value in channel.texts())
                result = {"model_calls": len(models.calls), "visible_results": len(channel.sends) > before,
                          "new_sends": len(channel.sends) - before, "task_sends": task_sends}
            elif gate == "rights":
                ref = config["data"]["object_ref"]
                viewed = await visible("/health-view", "view")
                assert "没有失眠" in viewed
                await visible("/health-correct " + ref + " 我昨晚睡得很好", "correction", expected="纠正")
                viewed = await visible("/health-view", "view-after")
                assert "我昨晚睡得很好" in viewed
                assert not models.calls
                result = {"model_calls": 0, "visible_results": True}
            elif gate == "recording-private":
                await visible("/health-recording-stop", "privacy-stop", expected="停止记录")
                sentinel = "SYNTHETIC130_PRIVATE_BODY_不落盘"
                text = "我昨晚没有失眠" + sentinel
                models.add("intake", _intake(text))
                await visible(text, "private-body")
                assert len(models.calls) == 1
                result = {"model_calls": 1, "sentinel": sentinel, "source": sources()[-1]}
            elif gate == "delete":
                description = await visible("/health-delete", "delete-request")
                match = re.search(r"/health-delete-confirm\s+(\S+)", description)
                assert match, "read the actual Core-rendered independent confirmation command"
                assert ready() == "enabled"
                before = len(channel.sends)
                await owner("/health-delete", "delete-request")
                assert ready() == "enabled" and len(channel.sends) == before
                operation_ref = match.group(1)
                await owner(match.group(0), "delete-independent-confirm", minute=7, allow_no_cursor=True)
                # Original117 sends its minimal notice before terminal/key
                # destruction. Do not require a new encrypted outbox, message
                # or persistent native cursor after all local state is purged.
                terminal = await asyncio.to_thread(_parent_barrier, config,
                    "observe-delete-terminal", operation_ref=operation_ref)
                assert terminal["operation_ref"] == operation_ref and terminal["phase"] == "completed"
                await _wait(lambda: len(channel.sends) > before)
                assert not models.calls
                result = {"model_calls": len(models.calls), "operation_ref": operation_ref,
                          "notice_send_count": len(channel.sends) - before}
            elif gate == "export":
                mode = config["data"]["mode"]
                # A real held owner-delivery lease blocks correction CAS, so
                # accepted RPC is not evidence that an object changed. Inject
                # the declared external current-head read failure only after
                # the complete actual artifact has crossed CorePort instead.
                ordinary_request = port.request
                unavailable = False
                def observed_request(kind, payload, *, request_id=None):
                    nonlocal unavailable
                    value = ordinary_request(kind, payload, request_id=request_id)
                    artifact = value["payload"].get("artifact")
                    if mode == "unavailable-after-read" and not unavailable and artifact and artifact["next_index"] is None:
                        observed = _parent_barrier(config, "head-unavailable-after-artifact-read")
                        assert observed == {"external_head_unavailable": True}
                        unavailable = True
                    return value
                port.request = observed_request
                before = len(channel.sends)
                await owner("/health-export", "export-file", allow_no_cursor=True)
                await _wait(lambda: len(port.authorizations) >= (1 if mode == "unavailable-after-read" else 2) and
                            (unavailable if mode == "unavailable-after-read" else len(channel.media_posts) == (1 if mode == "bad-upload-url" else 3)))
                await _wait(lambda: any(type(value.get("payload", {}).get("delivery")) is dict and value["payload"]["delivery"]["handoff_complete"]
                                       for value in port.responses) or mode == "unavailable-after-read")
                assert port.artifact_metadata and port.read_artifact
                metadata = port.artifact_metadata; plaintext = bytes(port.read_artifact)
                assert metadata["digest"] == _SHA(plaintext) and metadata["size_bytes"] == len(plaintext)
                assert metadata["filename"] == "health-export-" + metadata["digest"][7:] + ".json"
                from partner_health_steward.rights import ManagedExport
                exported = ManagedExport.from_wire(json.loads(plaintext))
                assert _CANONICAL(exported.to_wire()) == plaintext
                second_denied = False
                if mode == "unavailable-after-read":
                    intent_id = port.authorizations[0]["authorization"]["intent_id"]
                    def denied_second_authorization():
                        calls = [payload for _, payload in port.calls if payload.get("operation") == "delivery-authorize"
                                 and payload["payload"]["intent_id"] == intent_id]
                        refused_frame = any(payload.get("operation") == "delivery-authorize"
                            and payload["payload"]["intent_id"] == intent_id and reason == "core-frame-truncated"
                            for _, payload, reason in port.denied)
                        refused_reply = any(value.get("authorization") is None and type(value.get("delivery")) is dict
                            and value["delivery"]["intent_id"] == intent_id for value in port.authorization_replies)
                        return len(calls) >= 2 and (refused_frame or refused_reply)
                    await _wait(denied_second_authorization)
                    second_denied = denied_second_authorization()
                    assert not channel.media_posts
                    layer = "unknown"
                elif mode == "bad-upload-url":
                    intent_id = port.authorizations[-1]["authorization"]["intent_id"]
                    await _wait(lambda: _exchange(port, "managed-read", "health-entry-delivery", {"intent_id": intent_id})["delivery"]["handoff_complete"])
                    layer = _exchange(port, "managed-read", "health-entry-delivery", {"intent_id": intent_id})["delivery"]["current_layer"]
                    assert len(channel.media_posts) == 1
                else:
                    from gateway.platforms.weixin import _aes128_ecb_decrypt
                    ticket = channel.ticket
                    assert ticket["media_type"] == 3 and ticket["to_user_id"] == config["policy"]["owner_sender_id"]
                    assert re.fullmatch("[0-9a-f]{32}", ticket["filekey"])
                    assert re.fullmatch("[0-9a-f]{32}", ticket["aeskey"])
                    assert ticket["rawsize"] == len(plaintext)
                    assert ticket["rawfilemd5"] == hashlib.md5(plaintext).hexdigest()
                    assert ticket["filesize"] == ((len(plaintext) // 16) + 1) * 16
                    # Pinned protocol key is ASCII-hex in final media but raw
                    # 16-byte AES key for cryptography.
                    decrypted = _aes128_ecb_decrypt(channel.ciphertext, bytes.fromhex(ticket["aeskey"]))
                    assert decrypted == plaintext
                    file_messages = [msg for msg in channel.sends if msg["item_list"][0]["type"] == 4]
                    assert len(file_messages) == 1
                    msg = file_messages[0]; file_item = msg["item_list"][0]["file_item"]
                    assert len(msg["item_list"]) == 1 and msg["to_user_id"] == config["policy"]["owner_sender_id"]
                    assert msg["from_user_id"] == "" and msg["message_type"] == 2 and msg["message_state"] == 2
                    assert file_item["media"]["encrypt_query_param"] == "synthetic-cdn-ticket"
                    assert msg["context_token"] == "synthetic-context"
                    assert file_item["file_name"] == metadata["filename"] and file_item["len"] == str(len(plaintext))
                    assert file_item["media"]["aes_key"] == base64.b64encode(ticket["aeskey"].encode()).decode()
                    assert file_item["media"]["encrypt_type"] == 1
                    intent_id = port.authorizations[-1]["authorization"]["intent_id"]
                    def export_deliveries():
                        return [value["payload"]["delivery"] for value in port.responses
                                if type(value.get("payload", {}).get("delivery")) is dict
                                and value["payload"]["delivery"]["intent_id"] == intent_id]
                    await _wait(lambda: any(item["handoff_complete"] for item in export_deliveries()))
                    layer = export_deliveries()[-1]["current_layer"]
                    previous = len(channel.media_posts)
                    await owner("/health-export", "export-file")
                    assert len(channel.media_posts) == previous
                texts = "\n".join(channel.texts())
                if mode != "unavailable-after-read":
                    assert "平台接受文件不代表你已经下载" in texts and "不能撤回微信或CDN副本" in texts
                result = {"model_calls": len(models.calls), "media_posts": len(channel.media_posts),
                          "two_authorizations": sum(payload.get("operation") == "delivery-authorize" and payload["payload"]["intent_id"] == port.authorizations[0]["authorization"]["intent_id"] for _, payload in port.calls) >= 2,
                          "artifact_from_core": True, "artifact_size": len(plaintext), "decrypted_equals_canonical_export": mode not in {"unavailable-after-read", "bad-upload-url"},
                          "layer": layer, "replay_posts": 0, "second_authorization_denied": second_denied,
                          "external_copy_limit_visible": mode == "unavailable-after-read" or "不能撤回微信或CDN副本" in texts}
            else:
                raise AssertionError(gate)
        finally:
            await adapter.disconnect()
    assert not ordinary, "health/failed model/owner commands must not enter ordinary Hermes Session"
    assert all(msg["to_user_id"] == config["policy"]["owner_sender_id"] for msg in channel.sends)
    assert not models.errors, models.errors
    assert all(session.closed for session in channel.sessions)
    from urllib.parse import urlsplit
    for url, headers, options in channel.requests:
        parsed = urlsplit(url)
        assert parsed.scheme == "https" and not parsed.username and not parsed.password and not parsed.fragment and parsed.port is None
        assert (parsed.netloc == "ilinkai.weixin.qq.com" and parsed.path in {"/ilink/bot/getupdates", "/ilink/bot/getuploadurl", "/ilink/bot/sendmessage"} and not parsed.query) or (parsed.netloc == "novac2c.cdn.weixin.qq.com" and parsed.path == "/c2c/upload")
        assert options.get("allow_redirects") is False
        if parsed.netloc == "novac2c.cdn.weixin.qq.com":
            assert not any(key.lower() == "authorization" for key in headers)
        else:
            assert headers.get("Authorization") == "Bearer synthetic-token"
    assert _TOKEN not in repr(port.calls) and _TOKEN not in repr(port.responses)
    assert not models.queue, "the expected finite model stages were not all reached"
    return result


if __name__ == "__main__" and "--pinned-gate" in sys.argv:
    config = json.loads(Path(sys.argv[-1]).read_text())
    published = Path(os.environ["TICKET130_PUBLISHED_PLUGIN"]).resolve()
    for module_name in ("partner_health_steward.live_nondiagnostic", "partner_health_steward.governed_nondiagnostic",
                        "partner_health_steward.live_weixin", "partner_health_steward.model_adapter",
                        "partner_health_steward.live_delivery", "partner_health_steward.weixin_transport"):
        module = importlib.import_module(module_name)
        assert Path(module.__file__).resolve().is_relative_to(published), module_name
    result = asyncio.run(_child(config))
    (Path(os.environ["HERMES_HOME"]) / "offline-result.json").write_bytes(_CANONICAL(result))
    print("TICKET130-" + config["gate"] + "-PASS")

"""Verifier-owned Ticket 124 gates across CorePort and pinned Hermes.

All messages and authorities are offline fixtures. Native imports run with a
temporary Hermes home; no running profile, credential or transcript is read.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

_REPOSITORY = Path(__file__).resolve().parents[1]
if __name__ == "__main__" and "--pinned-gate" in sys.argv:
    # Only the verifier fixture namespace comes from the checkout. Every
    # product import must resolve inside the actual Publisher-built Plugin.
    sys.path[:] = [p for p in sys.path if Path(p or os.getcwd()).resolve()
                   not in {_REPOSITORY, _REPOSITORY / "tests"}]
    sys.path.insert(0, os.environ["TICKET124_PINNED_SOURCE"])
    sys.path.insert(0, os.environ["TICKET124_PUBLISHED_PLUGIN"])
    fixture_tests = types.ModuleType("tests")
    fixture_tests.__path__ = [str(_REPOSITORY / "tests")]
    fixture_tests.__package__ = "tests"
    sys.modules["tests"] = fixture_tests
    import partner_health_steward as published_product
    published_package = Path(os.environ["TICKET124_PUBLISHED_PLUGIN"]) / "partner_health_steward"
    assert Path(published_product.__file__).resolve().is_relative_to(published_package.resolve())
    assert all(Path(p).resolve().is_relative_to(published_package.resolve())
               for p in published_product.__path__)

from partner_health_steward.contract import DailyTurnMeta, Response
from partner_health_steward import HealthCore, HealthPlugin
from partner_health_steward.admission import AdmissionPolicy
from partner_health_steward.core import InMemoryWriterFenceVault
from partner_health_steward.current_head import InMemoryCurrentHead
from partner_health_steward.coordination import (
    DailySkillBundle, DailySkillDisclosure, DailySkillRuntime, DailyTurnResult,
)
from partner_health_steward.host_contract import HostReleaseContract
from partner_health_steward.initialization import (
    HealthInitRuntime, InitializationDisclosure, InitializationProjection, OwnerConsentEvidence,
)
from partner_health_steward.release_deployment import HermesReleasePublisher
from partner_health_steward.storage import EncryptedStateStore, StaticKeyProvider
from tests import test_ticket111_admission_initialization as init_fixture
from tests import test_ticket112_seven_skill_daily_turn as daily_fixture
from tests import test_ticket119_integration as release_fixture
from tests import test_ticket123_production_core_service as service_fixture


_HEADER_FIELDS = (
    "causal_id", "channel", "partner_id", "sender_id", "conversation_id",
    "chat_type", "entrypoint", "message_id", "protocol_timestamp", "received_at",
    "native_cursor",
)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _command(operation, payload=None):
    return {"interface": "health-entry-v1", "operation": operation,
            "payload": {} if payload is None else payload}


def _read(projection, payload=None):
    return {"interface": "health-entry-v1", "projection": projection,
            "payload": {} if payload is None else payload}


def _message_wire(message, body):
    wire = asdict(message)
    wire["body"] = body
    return wire


class Ticket124LiveEntryVerificationTests(unittest.TestCase):
    maxDiff = None

    def _module(self):
        try:
            module = importlib.import_module("partner_health_steward.live_health")
        except ModuleNotFoundError:
            self.fail("124 prerequisite: live health CorePort operations are not implemented")
        self.assertTrue(callable(getattr(module, "LiveHealthCoreOperations", None)))
        self.assertTrue(callable(getattr(module, "LiveHealthRuntime", None)))
        return module

    def _operations(self, fixture, *, wake=None):
        return self._module().LiveHealthCoreOperations(
            fixture.plugin, current_generation=lambda: fixture.head.read().head.generation,
            wake_current=wake,
        )

    def test_v124_01_live_operations_preserve_real_consent_and_committed_turn(self):
        self._module()
        base = init_fixture.Ticket111AdmissionInitializationTests()
        base.setUp()
        self.addCleanup(base.tearDown)
        operations = self._operations(base)
        initialization = base.initialization_request()
        message = base.message("unused")
        headers = {key: getattr(message, key) for key in _HEADER_FIELDS}
        preflight = operations.dispatch("managed-read", _read("health-entry-preflight", {"headers": headers}))
        self.assertEqual(set(preflight), {"allowed", "current_generation", "initialization_phase", "reason_code"})
        self.assertTrue(preflight["allowed"])
        self.assertEqual(preflight["initialization_phase"], "uninitialized")
        self.assertEqual(preflight["current_generation"], base.head.read().head.generation)
        # A caller's True fields are not consent evidence without an admitted source.
        before = operations.dispatch("command", _command("initialization-consent", {
            "initialization": initialization.to_storage(),
        }))
        self.assertEqual(before["response"]["status"], "rejected")
        disclosure_wire = operations.dispatch("command", _command("initialization-disclosure", {
            "initialization": replace(initialization, owner_consent=False,
                                      first_hop_route_consent=False).to_storage(),
        }))
        disclosure = InitializationDisclosure.from_storage(disclosure_wire["disclosure"])
        consent = OwnerConsentEvidence.for_initialization(
            initialization, base.init_asset, disclosure,
            owner_confirmed=True, first_hop_route_confirmed=True,
        )
        admitted = operations.dispatch("command", _command("receive-weixin", {
            "message": _message_wire(message, consent.to_message_body()),
        }))
        self.assertEqual(admitted["response"]["status"], "accepted")
        for operation, payload in (
            ("initialization-consent", {"initialization": initialization.to_storage()}),
            ("initialization-commit", {}), ("initialization-finalize", {}),
        ):
            result = operations.dispatch("command", _command(operation, payload))
            self.assertIn(result["response"]["status"], {"accepted", "replayed"})
        initialized = operations.dispatch("managed-read", _read("health-entry-initialization"))
        self.assertEqual(initialized["initialization"]["phase"], "enabled")
        # A daily source then traverses the same public adapter into actual Core.
        daily = daily_fixture.Ticket112SevenSkillDailyTurnTests()
        daily.setUp()
        self.addCleanup(daily.tearDown)
        daily.route_classification = "health"
        ops = self._operations(daily)
        raw = daily.message(
            "offline", causal_id="ticket124-daily-source", generation=daily.head.read().head.generation,
            requested_capability="health-steward", message_id="ticket124-native-daily",
            native_cursor="ticket124-cursor", protocol_timestamp="2026-08-24T09:05:00+08:00",
            received_at="2026-08-24T09:05:01+08:00",
        )
        result = ops.dispatch("command", _command("receive-weixin", {
            "message": _message_wire(raw, "我昨晚没睡好"),
        }))
        self.assertEqual(result["response"]["status"], "accepted", result)
        committed = result["response"]["meta"]["turn_result"]
        self.assertTrue(committed["record_id"])
        self.assertTrue(committed["owner_reply"])
        self.assertIn("health-steward", [s["canonical_name"] for s in committed["skill_disclosures"]])
        generation = daily.head.read().head.generation
        replay = ops.dispatch("command", _command("receive-weixin", {
            "message": _message_wire(raw, "我昨晚没睡好"),
        }))
        self.assertEqual(replay["response"]["meta"]["turn_result"], committed)
        self.assertEqual(daily.head.read().head.generation, generation)

    def test_v124_02_production_socket_uses_one_release_bound_live_runtime(self):
        module = self._module()
        producer = importlib.import_module("partner_health_steward.production_core_service")
        runtime_root = os.environ.get("TICKET123_RUNTIME_ROOT")
        self.assertIsNotNone(runtime_root, "formal production gate requires the declared 3.11 runtime")
        self.assertTrue(Path(producer.__file__).resolve().is_relative_to(Path(runtime_root).resolve()),
                        "formal production gate must import the runtime-owned product module")
        # This is the existing real 123 fixture, not a replacement server or patched Core.
        fixture = service_fixture.Ticket123ProductionCoreServiceTests()
        fixture.module = producer
        with tempfile.TemporaryDirectory(prefix="ticket124-coreport-") as directory:
            root = Path(directory)
            _, binding, head, _ = fixture._fixture(root)
            daily = daily_fixture.Ticket112SevenSkillDailyTurnTests()
            daily.setUp()
            self.addCleanup(daily.tearDown)
            draft = root / "live-release-draft"
            shutil.copytree(binding["release_root"], draft)
            paths = {name: f"skills/{name}/SKILL.md" for name in (
                "health-init", *(a.canonical_name for a in daily.daily_bundle.assets))}
            digests = {}
            for name, relative in paths.items():
                content = f"# {name}\n\nVersion: verifier-v124\nOffline fixture role resource.\n".encode()
                (draft / relative).write_bytes(content)
                digests[name] = _sha(content)
            # Publish a self-consistent offline release with substantive fixture assets.
            descriptor = release_fixture.Ticket119VerificationTests()
            descriptor.release_root = draft
            descriptor.artifacts = tuple({"path": p, "role": r} for p, r in release_fixture._ARTIFACTS)
            host = HostReleaseContract().build(descriptor._release_sources()).to_wire()
            (draft / "host-release-manifest.json").write_bytes(_canonical(host))
            old = json.loads((draft / "release-manifest.json").read_text())
            files = sorted(({"path": p.relative_to(draft).as_posix(), "sha256": _sha(p.read_bytes())}
                            for p in draft.rglob("*") if p.is_file() and p.name != "release-manifest.json"),
                           key=lambda item: item["path"])
            body = {"contract": old["contract"], "state": "staged", "files": files,
                    "host_release_manifest": host}
            digest = _sha(_canonical(body))
            wire = {"contract": old["contract"], "state": "staged", "files": files,
                    "release_digest": digest, "host_release_digest": host["release_digest"]}
            (draft / "release-manifest.json").write_bytes(_canonical(wire))
            staged = root / "releases" / digest.removeprefix("sha256:")
            draft.rename(staged)
            published = HermesReleasePublisher(_REPOSITORY).publish_current_successor(staged, binding["runtime_manifest"]).to_wire()
            binding["release_root"] = str(staged.parent / published["release_digest"].removeprefix("sha256:"))
            binding["release_digest"] = published["release_digest"]
            binding["lifecycle_release"]["product_release"] = published["release_digest"]
            init_runtime = HealthInitRuntime(
                replace(daily.init_asset, asset_digest=digests["health-init"]), daily.init_attestor,
                clock=lambda: datetime(2026, 8, 24, tzinfo=timezone.utc),
            )
            bundle = DailySkillBundle(tuple(replace(a, asset_digest=digests[a.canonical_name])
                                           for a in daily.daily_bundle.assets))
            daily_runtime = DailySkillRuntime(bundle, daily.daily_attestor,
                                             executor=daily.turn_executor,
                                             clock=lambda: datetime(2026, 8, 24, 1, 6, tzinfo=timezone.utc))
            daily.route_classification = "health"
            runtime = module.LiveHealthRuntime(
                daily.policy, init_runtime, daily.router, daily_runtime, asset_paths=paths,
            )
            service = producer.ProductionCoreService(binding, current_head=head, live_runtime=runtime)
            endpoint = service.start()
            try:
                request = {"protocol_version": 1, "kind": "managed-read",
                           "request_id": "ticket124-socket-init",
                           "payload": _read("health-entry-initialization")}
                result = fixture._request(endpoint, request)
                self.assertEqual(result["payload"]["initialization"]["phase"], "uninitialized")
                def exchange(kind, payload):
                    envelope = {"protocol_version": 1, "kind": kind,
                                "request_id": "ticket124-real-socket", "payload": payload}
                    observed = fixture._request(endpoint, envelope)
                    self.assertIsNotNone(observed, payload)
                    return observed["payload"]
                initialization = daily.initialization_request()
                disclosure = InitializationDisclosure.from_storage(exchange("command", _command(
                    "initialization-disclosure", {"initialization": replace(
                        initialization, owner_consent=False, first_hop_route_consent=False).to_storage()}))["disclosure"])
                consent = OwnerConsentEvidence.for_initialization(
                    initialization, init_runtime.asset, disclosure,
                    owner_confirmed=True, first_hop_route_confirmed=True)
                raw = daily.message("offline", generation=head.read().head.generation)
                admitted = exchange("command", _command("receive-weixin", {
                    "message": _message_wire(raw, consent.to_message_body())}))
                self.assertEqual(admitted["response"]["status"], "accepted", admitted)
                for operation, payload in (
                    ("initialization-consent", {"initialization": initialization.to_storage()}),
                    ("initialization-commit", {}), ("initialization-finalize", {}),
                ):
                    response = exchange("command", _command(operation, payload))
                    self.assertIn(response["response"]["status"], {"accepted", "replayed"}, response)
                self.assertEqual(exchange("managed-read", _read("health-entry-initialization"))[
                    "initialization"]["phase"], "enabled")
                health = daily.message(
                    "offline", causal_id="ticket124-production-daily", generation=head.read().head.generation,
                    requested_capability="health-steward", message_id="native-production-daily",
                    protocol_timestamp="2026-08-24T09:05:00+08:00", received_at="2026-08-24T09:05:01+08:00",
                    native_cursor="cursor-production-daily")
                daily_result = exchange("command", _command("receive-weixin", {
                    "message": _message_wire(health, "我昨晚没睡好")}))
                self.assertEqual(daily_result["response"]["status"], "accepted", daily_result)
                committed = daily_result["response"]["meta"]["turn_result"]
                self.assertTrue(committed["evidence_ids"])
                self.assertTrue(committed["portrait_topics"])
                self.assertEqual({item["canonical_name"] for item in committed["skill_disclosures"]},
                                 {"health-steward", "health-evidence", "health-portrait"})
                request["payload"] = _command("call-any-method", {"method": "__dict__"})
                request["kind"] = "command"
                self.assertIsNone(fixture._request(endpoint, request))
            finally:
                service.close()
            (Path(binding["release_root"]) / paths["health-init"]).write_text("tampered")
            rejected = producer.ProductionCoreService(binding, current_head=head, live_runtime=runtime)
            with self.assertRaises((ValueError, RuntimeError)):
                rejected.start()
            self.assertFalse(Path(binding["socket_path"]).exists())

    def _run_pinned_gate(self, gate):
        self._module()
        try:
            spec = importlib.util.find_spec("partner_health_steward.live_weixin")
        except ModuleNotFoundError:
            spec = None
        self.assertIsNotNone(spec, "124 prerequisite: live pinned Weixin Adapter is not implemented")
        pinned = Path(os.environ.get("TICKET118_PINNED_HERMES_SOURCE", "/tmp/health-steward-hermes-pinned"))
        self.assertTrue((pinned / "gateway/platforms/base.py").is_file(), "pinned Hermes source is required")
        with tempfile.TemporaryDirectory(prefix="ticket124-hermes-home-") as home:
            release_output = Path(home) / "releases"
            publication = HermesReleasePublisher(_REPOSITORY).build(release_output).to_wire()
            release_root = release_output / publication["release_digest"].removeprefix("sha256:")
            plugin_root = release_root / "plugin" / "health-weixin"
            env = {key: os.environ[key] for key in ("PATH", "LANG", "SYSTEMROOT") if key in os.environ}
            env.update({"HOME": home, "HERMES_HOME": home, "HERMES_CONFIG": str(Path(home) / "config.yaml"),
                        "PYTHONDONTWRITEBYTECODE": "1", "TICKET124_PINNED_SOURCE": str(pinned),
                        "TICKET124_PUBLISHED_PLUGIN": str(plugin_root),
                        "TICKET124_HOST_RELEASE_DIGEST": publication["host_release_digest"]})
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--pinned-gate", gate],
                                 cwd=home, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"TICKET124-{gate}-PASS", run.stdout)

    def test_v124_03_pinned_lifecycle_admits_headers_before_body_and_keeps_sources(self):
        self._run_pinned_gate("V03")

    def test_v124_04_cursor_unknown_replay_wake_and_costop_are_truthful(self):
        self._run_pinned_gate("V04")


class _PoisonMessage(dict):
    reads = 0

    def __getitem__(self, key):
        if key == "item_list":
            self.reads += 1
            raise AssertionError("rejected native body was read")
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key == "item_list":
            self.reads += 1
            raise AssertionError("rejected native body was read")
        return super().get(key, default)

    def items(self):
        self.reads += 1
        raise AssertionError("rejected native message was copied or serialized")

    def values(self):
        self.reads += 1
        raise AssertionError("rejected native message values were materialized")


def _native(identifier, *, sender="owner-offline", poison=False):
    value = {"message_id": identifier, "from_user_id": sender, "to_user_id": "partner-offline",
             "msg_type": 1, "create_time_ms": 1787520000000,
             "context_token": "offline-token-ref", "item_list": [
                 {"type": 1, "text_item": {"text": "相同的离线健康消息"}},
             ]}
    return _PoisonMessage(value) if poison else value


class _Ingress:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.cursors = []
        self.acknowledged = []
        self.events = []

    async def connect(self): return True
    async def disconnect(self): self.events.append("disconnect")
    async def get_updates(self, cursor):
        self.cursors.append(cursor)
        return await self.queue.get()
    async def acknowledge_cursor(self, cursor):
        self.events.append("ack:" + cursor)
        self.acknowledged.append(cursor)


class _RPC:
    def __init__(self, ingress, *, unknown_id=None):
        self.ingress = ingress
        self.unknown_id = unknown_id
        self.calls = []
        self.messages = []
        self.results = {}
        self.available = True

    def request(self, kind, payload, *, request_id=None):
        self.calls.append((kind, copy.deepcopy(payload)))
        if not self.available:
            raise TimeoutError("offline CorePort unavailable")
        projection = payload.get("projection")
        operation = payload.get("operation")
        data = payload.get("payload", {})
        result = {}
        if projection == "health-entry-preflight":
            h = data["headers"]
            result = {"allowed": h["sender_id"] == "owner-offline", "current_generation": 2,
                      "initialization_phase": "enabled", "reason_code": None}
        elif projection == "health-entry-initialization":
            result = {"initialization": InitializationProjection.uninitialized().to_storage()}
        elif projection == "health-entry-native-cursor":
            result = {"native_cursor": self.ingress.acknowledged[-1] if self.ingress.acknowledged else None}
        elif projection == "health-entry-cursor-directive":
            source = data["source_causal_id"]
            msg = next(m for m in self.messages if m["causal_id"] == source)
            directive = None if msg["message_id"] == self.unknown_id else {
                "source_causal_id": source, "native_cursor": msg["native_cursor"],
                "business_transition_id": "transition:" + msg["message_id"], "authority_generation": 2,
            }
            self.ingress.events.append("directive:" + source)
            result = {"directive": directive}
        elif operation == "receive-weixin":
            msg = data["message"]
            self.messages.append(msg)
            identifier = msg["message_id"]
            if identifier == self.unknown_id:
                response = Response("unavailable", msg["causal_id"], "processing-result-unknown")
            else:
                prior = self.results.get(identifier)
                turn = DailyTurnResult(msg["causal_id"], "record:" + identifier,
                    "transition:" + identifier, (), (),
                    (DailySkillDisclosure("health-steward", "离线健康管家", "1", "offline-v1"),),
                    "离线已提交回复") if prior is None else prior
                self.results[identifier] = turn
                response = Response("accepted" if prior is None else "replayed", msg["causal_id"],
                                    meta=DailyTurnMeta(turn))
            result = {"response": response.to_wire()}
        elif operation == "native-cursor-result":
            self.ingress.events.append("cursor-result:" + data["status"])
            result = {"response": Response("accepted", data["source_causal_id"]).to_wire()}
        elif operation == "wake-current":
            result = {"response": Response("accepted").to_wire()}
        elif payload == {"operation": "health-runtime-probe"} or payload == {"projection": "health-runtime"}:
            result = {"state": "healthy", "health_writes_allowed": True}
        else:
            raise AssertionError("unexpected CorePort operation: " + repr(payload))
        return {"protocol_version": 1, "kind": kind, "request_id": request_id or "offline-rpc",
                "status": "accepted", "payload": result}


class _Delivery:
    def __init__(self, *, unknown=False):
        self.calls = []
        self.effects = {}
        self.presentations = []
        self.attempts = []
        self.unknown = unknown
    async def send_committed(self, intent):
        self.calls.append(copy.deepcopy(intent))
        if intent.get("kind") == "initialization-disclosure":
            self.presentations.append(copy.deepcopy(intent))
            return {"status": "not-authorized", "reason_code": "ticket126-authorization-required"}
        # The 126 effect bridge owns stable identity/idempotency. 124 may ask
        # it to read an existing effect; a repeated call is not a second send.
        turn = intent["turn_result"]
        identity = (turn["record_id"], turn["transition_id"])
        if identity not in self.effects:
            self.attempts.append(copy.deepcopy(intent))
            self.effects[identity] = copy.deepcopy(intent)
        if self.unknown:
            return {"status": "unknown", "reason_code": "offline-response-lost"}
        return {"status": "accepted", "result_ref": "offline-accepted", "evidence_ref": "offline-evidence"}


async def _wait(predicate):
    for _ in range(200):
        if predicate(): return
        await asyncio.sleep(0.01)
    raise AssertionError("pinned lifecycle did not process the queued update")


async def _pinned_gate(gate):
    from gateway.config import PlatformConfig
    from gateway.platform_registry import platform_registry, PlatformEntry
    from gateway.platforms.base import BasePlatformAdapter
    from partner_health_steward.admission import AdmissionPolicy
    from partner_health_steward.live_weixin import LiveHealthWeixinAdapter
    from partner_health_steward import hermes_host
    from partner_health_steward.host_contract import (
        _CURRENT_PROCESS_ACTIVATION_CAPABILITY, _activation_proof,
    )
    class Context:
        def register_platform(self, **fields):
            platform_registry.register(PlatformEntry(**fields))
    hermes_host.register(Context())
    assert [e.name for e in platform_registry.plugin_entries()].count("health_weixin") == 1
    ingress, delivery = _Ingress(), _Delivery()
    rpc = _RPC(ingress, unknown_id="unknown" if gate == "V04" else None)
    policy = AdmissionPolicy("partner-offline", "owner-offline", "owner-offline")
    config = PlatformConfig(enabled=True, extra={
        "admission_policy": policy.to_storage(), "core_port": rpc,
        "ingress_transport": ingress, "delivery_transport": delivery,
    })
    entry = platform_registry.get("health_weixin")
    # This is Gateway's actual selection path: an unarmed registration is
    # staged, regardless of whether its factory could construct an object.
    assert platform_registry.create_adapter("health_weixin", config) is None
    release_digest = os.environ["TICKET124_HOST_RELEASE_DIGEST"]
    release_root = Path(os.environ["TICKET124_PUBLISHED_PLUGIN"]).parents[1]
    host_manifest = json.loads((release_root / "host-release-manifest.json").read_text())
    assert host_manifest["release_digest"] == release_digest
    proof = _activation_proof(release_digest)
    activation = {"registry": platform_registry,
                  "activation_capability": _CURRENT_PROCESS_ACTIVATION_CAPABILITY,
                  "activation_proof": proof}
    arm = getattr(entry.check_fn, "_ticket118_arm")
    def create_registered(selected_config):
        # The offline trusted composition fixture re-arms the same exact
        # release after disconnect; the Adapter cannot issue this authority.
        arm(_CURRENT_PROCESS_ACTIVATION_CAPABILITY, proof)
        selected_config.extra.update(activation)
        return platform_registry.create_adapter("health_weixin", selected_config)
    invalid = PlatformConfig(enabled=True, extra={**config.extra, "admission_policy": {}})
    assert create_registered(invalid) is None  # no fallback to the old probe
    legacy = create_registered(PlatformConfig(enabled=True, extra={
        "core_port_endpoint": {"transport": "af-unix", "path": str(Path(os.environ["HERMES_HOME"]) / "unused.sock"),
                               "protocol": "ticket118-core-port-v1"}}))
    assert isinstance(legacy, hermes_host._HealthWeixinAdapter)
    assert not isinstance(legacy, LiveHealthWeixinAdapter)
    adapter = create_registered(config)
    assert isinstance(adapter, LiveHealthWeixinAdapter)
    assert isinstance(adapter, BasePlatformAdapter)
    ordinary = []
    async def ordinary_handler(event): ordinary.append(event)
    adapter.set_message_handler(ordinary_handler)
    adapter.set_fatal_error_handler(lambda value: None)
    adapter.set_session_store(object())
    adapter.set_busy_session_handler(None)
    adapter.set_topic_recovery_fn(None)
    adapter.set_authorization_check(lambda *a, **kw: True)
    assert await adapter.connect(is_reconnect=False)
    if gate == "V03":
        poison = _native("outside", sender="outsider", poison=True)
        ingress.queue.put_nowait({"ret": 0, "msgs": [poison, _native("one"), _native("two")],
                                 "get_updates_buf": "cursor-batch"})
        await _wait(lambda: len(rpc.messages) == 2 and "cursor-batch" in ingress.acknowledged)
        assert poison.reads == 0
        assert [m["message_id"] for m in rpc.messages] == ["one", "two"]
        assert rpc.messages[0]["body"] == rpc.messages[1]["body"]
        assert rpc.messages[0]["causal_id"] != rpc.messages[1]["causal_id"]
        assert ordinary == []
        ack = ingress.events.index("ack:cursor-batch")
        assert len([event for event in ingress.events[:ack] if event.startswith("directive:")]) == 2
        assert any(event.startswith("cursor-result:") for event in ingress.events[ack + 1:])
        result = await adapter.send("owner-offline", "unauthorized arbitrary health send")
        assert result.success is False
        assert len(delivery.effects) == 2
        first = copy.deepcopy(rpc.messages)
        ingress.queue.put_nowait({"ret": 0, "msgs": [_native("one"), _native("two")],
                                 "get_updates_buf": "cursor-batch"})
        await _wait(lambda: len(rpc.messages) == 4)
        assert [m["message_id"] for m in rpc.messages[2:]] == ["one", "two"]
        assert [m["causal_id"] for m in rpc.messages[2:]] == [m["causal_id"] for m in first]
        assert len(delivery.effects) == 2
    else:
        ingress.queue.put_nowait({"ret": 0, "msgs": [_native("one"), _native("unknown")],
                                 "get_updates_buf": "cursor-blocked"})
        await _wait(lambda: len(rpc.messages) == 2)
        await asyncio.sleep(0.03)
        assert "cursor-blocked" not in ingress.acknowledged
        before = len(delivery.calls)
        await adapter.wake_current()
        assert len(delivery.calls) == before
        assert any(p.get("operation") == "wake-current" for _, p in rpc.calls)
        rpc.available = False
        before_calls = len(rpc.calls)
        poison = _native("core-stopped", poison=True)
        ingress.queue.put_nowait({"ret": 0, "msgs": [poison], "get_updates_buf": "cursor-core-stopped"})
        await _wait(lambda: len(rpc.calls) > before_calls)
        await asyncio.sleep(0.03)
        assert poison.reads == 0
        assert len(delivery.calls) == before
        assert "cursor-core-stopped" not in ingress.acknowledged
    await adapter.disconnect()
    before = len(rpc.messages)
    ingress.queue.put_nowait({"ret": 0, "msgs": [_native("after-stop")], "get_updates_buf": "after-stop"})
    await asyncio.sleep(0.03)
    assert len(rpc.messages) == before
    if gate == "V04":
        await _real_adapter_initialization_and_restart(create_registered, PlatformConfig)
    published_package = (Path(os.environ["TICKET124_PUBLISHED_PLUGIN"]) / "partner_health_steward").resolve()
    for name, module in tuple(sys.modules.items()):
        if name == "partner_health_steward" or name.startswith("partner_health_steward."):
            assert Path(module.__file__).resolve().is_relative_to(published_package), name
    print(f"TICKET124-{gate}-PASS")


class _RealRPC:
    """The transport fake is real operations over an actual retained Core."""
    def __init__(self, fixture):
        from partner_health_steward.live_health import LiveHealthCoreOperations
        self.fixture = fixture
        self.operations = LiveHealthCoreOperations(
            fixture.plugin, current_generation=lambda: fixture.head.read().head.generation)
        self.calls = []
        self.turns = []
        self.responses = []

    def request(self, kind, payload, *, request_id=None):
        self.calls.append((kind, copy.deepcopy(payload)))
        if payload == {"operation": "health-runtime-probe"} or payload == {"projection": "health-runtime"}:
            probe = self.fixture.plugin.probe()
            result = {"state": probe.state.value,
                      "health_writes_allowed": self.fixture.plugin.health_writes_allowed(),
                      "model_effects_allowed": self.fixture.plugin.model_effects_allowed(),
                      "outbound_effects_allowed": self.fixture.plugin.outbound_effects_allowed()}
        else:
            result = self.operations.dispatch(kind, payload)
        if type(result) is dict and type(result.get("response")) is dict:
            if payload.get("operation") == "receive-weixin":
                self.responses.append(copy.deepcopy(result["response"]))
            turn = (result["response"].get("meta") or {}).get("turn_result")
            if turn is not None: self.turns.append(copy.deepcopy(turn))
        return {"protocol_version": 1, "kind": kind, "request_id": request_id or "offline-real-rpc",
                "status": "accepted", "payload": result}


def _uninitialized_real_fixture():
    base = daily_fixture.Ticket112SevenSkillDailyTurnTests()
    base.setUp()
    base.core.close(); base.store.close()
    base.policy = AdmissionPolicy("partner-offline", "owner-offline", "owner-offline")
    base.store = EncryptedStateStore(f"file:ticket124-real-{id(base)}?mode=memory&cache=shared",
                                    StaticKeyProvider(b"k" * 32, key_id="ticket124-offline-key"))
    base.head = InMemoryCurrentHead("partner-installation", "partner-site",
                                     writer_capability=base.writer_capability)
    authority = base.head.read().head.as_authority()
    base.store.seed_finalized_authority(authority)
    base.writer_vault = InMemoryWriterFenceVault()
    base.writer_vault.bind(authority, base.writer_capability)
    base.core = HealthCore(base.store, base.head, writer_fence_vault=base.writer_vault,
        admission_policy=base.policy, health_init_verifier=base.init_attestor,
        health_init_asset=base.init_asset, daily_skill_verifier=base.daily_attestor,
        daily_skill_bundle=base.daily_bundle)
    base.route_classification = "health"
    base.plugin = HealthPlugin(base.core, admission_policy=base.policy,
        health_init_runtime=base.init_runtime, coarse_router=base.router,
        daily_skill_runtime=base.daily_runtime)
    return base


async def _real_adapter_initialization_and_restart(create_registered, PlatformConfig):
    fixture = _uninitialized_real_fixture()
    rpc, delivery = _RealRPC(fixture), _Delivery(unknown=True)
    template = replace(fixture.initialization_request(), owner_consent=False,
                       first_hop_route_consent=False).to_storage()
    adapters = []
    def create(ingress):
        config = PlatformConfig(enabled=True, extra={
            "admission_policy": fixture.policy.to_storage(), "initialization_template": template,
            "core_port": rpc, "ingress_transport": ingress, "delivery_transport": delivery})
        adapter = create_registered(config)
        assert adapter is not None
        adapters.append(adapter)
        return adapter
    try:
        first_ingress = _Ingress()
        first = create(first_ingress)
        ordinary = []
        async def ordinary_handler(event): ordinary.append(event)
        first.set_message_handler(ordinary_handler)
        assert await first.connect(is_reconnect=False)
        # Before health initialization, an explicit ordinary classification
        # still reaches the host; a health classification must never fall back.
        fixture.route_classification = "ordinary"
        greeting = _native("ordinary-before-init")
        greeting["item_list"][0]["text_item"]["text"] = "你好"
        first_ingress.queue.put_nowait({"ret": 0, "msgs": [greeting], "get_updates_buf": "cursor-ordinary"})
        await _wait(lambda: len(ordinary) == 1)
        await _wait(lambda: len(first_ingress.cursors) >= 2)
        assert fixture.plugin.initialization_status(peer_id="plugin").phase == "uninitialized"
        fixture.route_classification = "health"
        blocked_health = _native("health-before-init")
        blocked_health["item_list"][0]["text_item"]["text"] = "我昨晚没睡好"
        before_health = len(rpc.calls)
        before_health_polls = len(first_ingress.cursors)
        first_ingress.queue.put_nowait({"ret": 0, "msgs": [blocked_health], "get_updates_buf": "cursor-health-blocked"})
        await _wait(lambda: len(first_ingress.cursors) > before_health_polls and any(payload.get("operation") == "receive-weixin"
                    and payload["payload"]["message"]["message_id"] == "health-before-init"
                    for _, payload in rpc.calls[before_health:]))
        assert len(ordinary) == 1
        assert rpc.turns == [] and delivery.effects == {}
        assert fixture.plugin.initialization_status(peer_id="plugin").phase == "uninitialized"
        begin = _native("begin-init")
        begin["item_list"][0]["text_item"]["text"] = "/health-init"
        first_ingress.queue.put_nowait({"ret": 0, "msgs": [begin], "get_updates_buf": "cursor-before-consent"})
        await _wait(lambda: len(delivery.presentations) > 0)
        presentation = delivery.presentations[-1]
        assert set(presentation) == {"kind", "workflow_id", "disclosure"}
        assert fixture.plugin.initialization_status(peer_id="plugin").phase == "uninitialized"
        assert delivery.effects == {}  # formed presentation is not a real accepted send
        workflow = presentation["workflow_id"]
        retained = rpc.operations.dispatch("managed-read", _read("health-entry-disclosure", {"workflow_id": workflow}))
        assert retained["disclosure"] == presentation["disclosure"]
        assert retained["initialization"]["owner_consent"] is False
        assert retained["initialization"]["first_hop_route_consent"] is False
        disclosure = InitializationDisclosure.from_storage(retained["disclosure"])
        callback_source = retained["initialization"]["admission_causal_id"]
        await first.disconnect()
        adapters.remove(first)
        # No Adapter memory survives. The challenge is reloaded from Core.
        second_ingress = _Ingress()
        second = create(second_ingress)
        assert await second.connect(is_reconnect=True)
        confirm = _native("independent-native-confirmation")
        confirm["create_time_ms"] = int(datetime(2026, 8, 24, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        confirm["item_list"][0]["text_item"]["text"] = f"/health-init-confirm {workflow} {disclosure.disclosure_id}"
        second_ingress.queue.put_nowait({"ret": 0, "msgs": [confirm], "get_updates_buf": "cursor-after-consent"})
        await _wait(lambda: fixture.plugin.initialization_status(peer_id="plugin").phase == "enabled")
        receipt = fixture.plugin.source_receipt(callback_source, peer_id="plugin")
        assert receipt.envelope.message_id == "independent-native-confirmation"
        health = _native("retained-daily-source")
        health["create_time_ms"] = int(datetime(2026, 8, 24, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)
        health["item_list"][0]["text_item"]["text"] = "我昨晚没睡好"
        second_ingress.queue.put_nowait({"ret": 0, "msgs": [health], "get_updates_buf": "cursor-approved-by-core"})
        def committed_cursor_advanced():
            if not rpc.turns:
                return False
            receipt = fixture.plugin.source_receipt(rpc.turns[-1]["source_causal_id"], peer_id="plugin")
            return receipt is not None and receipt.native_cursor_state == "advanced"
        await _wait(lambda: len(rpc.turns) > 0 and len(delivery.attempts) == 1
                    and "cursor-approved-by-core" in second_ingress.acknowledged
                    and committed_cursor_advanced())
        committed = rpc.turns[-1]
        approved = rpc.operations.dispatch("managed-read", _read("health-entry-native-cursor"))["native_cursor"]
        assert approved == "cursor-approved-by-core"
        assert fixture.plugin.source_receipt(committed["source_causal_id"], peer_id="plugin").native_cursor_state == "advanced"
        terminal = fixture.core.daily_turn_status(committed["source_causal_id"])
        assert terminal.phase == "finalized" and terminal.draft is None and terminal.result is None
        assert terminal.terminal.record_id == committed["record_id"]
        assert terminal.terminal.transition_id == committed["transition_id"]
        assert fixture.core.daily_turn_result(committed["source_causal_id"]) is None
        generation = fixture.head.read().head.generation
        effects = copy.deepcopy(delivery.effects)
        await second.disconnect()
        adapters.remove(second)
        third_ingress = _Ingress()
        third = create(third_ingress)
        assert await third.connect(is_reconnect=True)
        await _wait(lambda: len(third_ingress.cursors) > 0)
        assert third_ingress.cursors[0] == approved
        before = len(rpc.turns)
        before_bridge = len(delivery.calls)
        before_responses = len(rpc.responses)
        before_polls = len(third_ingress.cursors)
        third_ingress.queue.put_nowait({"ret": 0, "msgs": [copy.deepcopy(health)], "get_updates_buf": approved})
        await _wait(lambda: len(rpc.responses) > before_responses and len(third_ingress.cursors) > before_polls)
        replay = rpc.responses[-1]
        assert replay["status"] == "accepted" and replay["reason_code"] == "daily-turn-result-redacted"
        assert (replay.get("meta") or {}).get("turn_result") is None
        after = fixture.core.daily_turn_status(committed["source_causal_id"])
        assert after == terminal
        assert fixture.core.daily_turn_result(committed["source_causal_id"]) is None
        assert fixture.head.read().head.generation == generation
        assert len(rpc.turns) == before
        assert len(delivery.calls) == before_bridge
        assert delivery.effects == effects
        assert len(delivery.attempts) == 1  # retained unknown is never sent again
    finally:
        for adapter in reversed(adapters): await adapter.disconnect()
        fixture.tearDown()


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--pinned-gate":
    asyncio.run(_pinned_gate(sys.argv[2]))
elif __name__ == "__main__":
    unittest.main()

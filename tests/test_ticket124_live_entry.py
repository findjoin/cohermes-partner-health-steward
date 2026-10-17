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
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

_REPOSITORY = Path(__file__).resolve().parents[1]
if __name__ == "__main__" and "--pinned-gate" in sys.argv:
    sys.path.insert(0, os.environ["TICKET124_PINNED_SOURCE"])
    sys.path.insert(0, str(_REPOSITORY))

from partner_health_steward.contract import DailyTurnMeta, Response
from partner_health_steward.coordination import (
    DailySkillBundle, DailySkillDisclosure, DailySkillRuntime, DailyTurnResult,
)
from partner_health_steward.host_contract import HostReleaseContract
from partner_health_steward.initialization import (
    HealthInitRuntime, InitializationDisclosure, InitializationProjection, OwnerConsentEvidence,
)
from partner_health_steward.release_deployment import HermesReleasePublisher
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
                                             executor=daily.turn_executor)
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
            env = {key: os.environ[key] for key in ("PATH", "LANG", "SYSTEMROOT") if key in os.environ}
            env.update({"HOME": home, "HERMES_HOME": home, "HERMES_CONFIG": str(Path(home) / "config.yaml"),
                        "PYTHONDONTWRITEBYTECODE": "1", "TICKET124_PINNED_SOURCE": str(pinned)})
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--pinned-gate", gate],
                                 cwd=_REPOSITORY, env=env, capture_output=True, text=True, timeout=30)
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
    def __init__(self):
        self.calls = []
        self.effects = {}
    async def send_committed(self, intent):
        self.calls.append(copy.deepcopy(intent))
        # The 126 effect bridge owns stable identity/idempotency. 124 may ask
        # it to read an existing effect; a repeated call is not a second send.
        self.effects.setdefault(_sha(_canonical(intent)), copy.deepcopy(intent))
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
    adapter = entry.adapter_factory(config)
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
    print(f"TICKET124-{gate}-PASS")


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--pinned-gate":
    sys.path.insert(0, os.environ["TICKET124_PINNED_SOURCE"])
    sys.path.insert(0, str(_REPOSITORY))
    asyncio.run(_pinned_gate(sys.argv[2]))
elif __name__ == "__main__":
    unittest.main()

"""Independent offline delivery gates: real Core, socket, pinned HTTP boundary.

No real account, configuration, message, credential, or recipient is used.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import types
import unittest
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

_REPOSITORY = Path(__file__).resolve().parents[1]
if __name__ == "__main__" and "--pinned-gate" in sys.argv:
    sys.path[:] = [p for p in sys.path if Path(p or os.getcwd()).resolve()
                   not in {_REPOSITORY, _REPOSITORY / "tests"}]
    sys.path.insert(0, os.environ["TICKET126_PINNED_SOURCE"])
    sys.path.insert(0, os.environ["TICKET126_PUBLISHED_PLUGIN"])
    tests = types.ModuleType("tests")
    tests.__path__ = [str(_REPOSITORY / "tests")]
    tests.__package__ = "tests"
    sys.modules["tests"] = tests

from partner_health_steward.authority import EffectExecutionGrant, EffectIntent
from partner_health_steward.contract import ProtocolViolation
from partner_health_steward.delivery import OwnerDeliveryTransportResult
from partner_health_steward.live_health import LiveHealthCoreOperations
from partner_health_steward.coordination import DailySkillBundle, DailySkillRuntime
from partner_health_steward.host_contract import HostReleaseContract, _CorePortClient, _HostVerificationFailure
from partner_health_steward.initialization import HealthInitRuntime, OwnerConsentEvidence, InitializationDisclosure
from partner_health_steward.release_deployment import HermesReleasePublisher
from tests import test_ticket112_seven_skill_daily_turn as daily_fixture
from tests import test_ticket119_integration as release_fixture
from tests import test_ticket122_dynamodb_current_head as head_fixture
from tests import test_ticket123_production_core_service as service_fixture


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _operation(name, payload=None):
    return {"interface": "health-entry-v1", "operation": name,
            "payload": {} if payload is None else payload}


def _projection(name, payload=None):
    return {"interface": "health-entry-v1", "projection": name,
            "payload": {} if payload is None else payload}


class _SocketPort:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.calls = []

    def request(self, kind, payload, *, request_id=None):
        self.calls.append((kind, copy.deepcopy(payload)))
        request = {"protocol_version": 1, "kind": kind,
                   "request_id": request_id or "ticket126-offline-rpc", "payload": payload}
        return service_fixture.Ticket123ProductionCoreServiceTests()._request(self.endpoint, request)

    def exchange(self, kind, payload):
        response = self.request(kind, payload)
        if type(response) is not dict or response.get("status") != "accepted":
            raise AssertionError((kind, payload, response))
        return response["payload"]


class _ReleaseCapableDynamo(head_fixture._ScriptedDynamo):
    """126's AWS boundary: retain actual Core release digests and conditions.

    The inherited 122 fake intentionally recognizes two placeholder release
    digests. Other transactions still use that unchanged fixture; only this
    real-Core release transaction needs a general conditional HTTP boundary.
    """

    def transact_write_items(self, **request):
        actions = request["TransactItems"]
        updates = [action["Update"] for action in actions if "Update" in action]
        leases = [update for update in updates
                  if update["Key"]["SK"]["S"].startswith("LEASE#")]
        if not leases:
            return super().transact_write_items(**request)
        self.calls.append(("TransactWriteItems", copy.deepcopy(request)))
        if self.transact_error is not None:
            raise self.transact_error
        guards = [update for update in updates
                  if update["Key"]["SK"]["S"] == "LEASE-GUARD"]
        if len(actions) != 2 or len(updates) != 2 or len(leases) != 1 or len(guards) != 1:
            raise AssertionError("release must atomically update one lease and its guard")
        lease, guard = leases[0], guards[0]
        stored = self.records.get(lease["Key"]["SK"]["S"])
        if stored is None:
            raise head_fixture._AwsError("ConditionalCheckFailedException")
        pairs = self._equality_pairs(lease)
        if not {"lease_id", "holder_id", "released"} <= pairs.keys():
            raise AssertionError("release condition must bind lease, holder and unreleased state")
        if pairs["released"] != {"BOOL": False}:
            raise AssertionError("release must require an unreleased lease")
        if (lease["Key"]["PK"] != stored["PK"]
                or guard["Key"]["PK"] != stored["PK"]
                or any(pairs[name] != stored[name] for name in ("lease_id", "holder_id", "released"))):
            raise head_fixture._AwsError("ConditionalCheckFailedException")
        changes = self._update_operations(lease)["SET"]
        operation = changes.get("released_operation_digest")
        if (changes.get("released") != {"BOOL": True}
                or type(operation) is not dict or set(operation) != {"S"}
                or re.fullmatch(r"sha256:[0-9a-f]{64}", operation["S"]) is None):
            raise AssertionError("release must store its actual SHA256 operation digest")
        condition = self._normalized_expression(lease)
        if (pairs.get("released_operation_digest") != operation
                or re.search(r"\(\s*attribute_not_exists\s*\(\s*released_operation_digest\s*\)"
                             r"\s+OR\s+released_operation_digest\s*=\s*:[A-Za-z0-9_]+\s*\)", condition) is None):
            raise AssertionError("release must conditionally bind exact operation ownership")
        previous = stored.get("released_operation_digest")
        if previous is not None and previous != operation:
            raise head_fixture._AwsError("ConditionalCheckFailedException")
        effect = stored["effect_id"]["S"]
        tokens = re.findall(r"\bcontains\s*\(\s*active_effect_ids\s*,\s*(:[A-Za-z0-9_]+)\s*\)",
                            self._normalized_expression(guard))
        values = guard.get("ExpressionAttributeValues", {})
        deletion = self._update_operations(guard)["DELETE"].get("active_effect_ids")
        if (not any(values.get(token) == {"S": effect} for token in tokens)
                or deletion != {"SS": [effect]}):
            raise AssertionError("release must condition on and delete only its active effect")
        if effect not in self.active_effects:
            raise head_fixture._AwsError("ConditionalCheckFailedException")
        # No mutation occurs before every conditional check has passed.
        self.records[lease["Key"]["SK"]["S"]] = {
            **stored, "released": {"BOOL": True},
            "released_operation_digest": copy.deepcopy(operation),
        }
        self.active_effects.remove(effect)
        if self.transact_error_after_apply is not None:
            raise self.transact_error_after_apply
        return {}


@contextmanager
def _service(*, core_options=None):
    """Publish substantive synthetic assets using the existing real 123 fixture."""
    import partner_health_steward.production_core_service as producer
    from partner_health_steward.live_health import LiveHealthRuntime
    runtime_root = os.environ.get("TICKET123_RUNTIME_ROOT")
    assert runtime_root, "126 formal socket gate requires declared Python3.11 runtime"
    assert Path(producer.__file__).resolve().is_relative_to(Path(runtime_root).resolve())
    fixture = service_fixture.Ticket123ProductionCoreServiceTests()
    fixture.module = producer
    daily = daily_fixture.Ticket112SevenSkillDailyTurnTests()
    daily.setUp()
    try:
        with tempfile.TemporaryDirectory(prefix="ticket126-coreport-") as directory:
            root = Path(directory)
            _, binding, head, client = fixture._fixture(root, client_factory=_ReleaseCapableDynamo)
            draft = root / "live-release-draft"
            shutil.copytree(binding["release_root"], draft)
            names = ("health-init", *(a.canonical_name for a in daily.daily_bundle.assets))
            paths = {name: f"skills/{name}/SKILL.md" for name in names}
            digests = {}
            for name, relative in paths.items():
                content = f"# {name}\n\nVersion: verifier-v126\nOffline fixture role resource.\n".encode()
                (draft / relative).write_bytes(content)
                digests[name] = _sha(content)
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
            published = HermesReleasePublisher(_REPOSITORY).publish_current_successor(
                staged, binding["runtime_manifest"]).to_wire()
            binding["release_root"] = str(staged.parent / published["release_digest"].removeprefix("sha256:"))
            binding["release_digest"] = published["release_digest"]
            binding["lifecycle_release"]["product_release"] = published["release_digest"]
            init = HealthInitRuntime(replace(daily.init_asset, asset_digest=digests["health-init"]),
                daily.init_attestor, clock=lambda: datetime(2026, 8, 24, tzinfo=timezone.utc))
            bundle = DailySkillBundle(tuple(replace(a, asset_digest=digests[a.canonical_name])
                                            for a in daily.daily_bundle.assets))
            daily_runtime = DailySkillRuntime(bundle, daily.daily_attestor, executor=daily.turn_executor,
                clock=lambda: datetime(2026, 8, 24, 1, 6, tzinfo=timezone.utc))
            daily.route_classification = "health"
            runtime = LiveHealthRuntime(daily.policy, init, daily.router, daily_runtime, asset_paths=paths, core_options=core_options)
            service = producer.ProductionCoreService(binding, current_head=head, live_runtime=runtime)
            endpoint = service.start()
            try:
                yield types.SimpleNamespace(service=service, binding=binding, head=head, runtime=runtime,
                    daily=daily, init=init, port=_SocketPort(endpoint), root=root, client=client)
            finally:
                service.close()
    finally:
        daily.tearDown()


# Test transport only: every authorization/grant/result below comes from real Core.
_GRANT_FIELDS = {
    "session_id", "lease_id", "effect_id", "intent_digest", "generation", "writer_fence",
}


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ProtocolViolation("invalid verifier CorePort shape")
    return value


def _wire_copy(value):
    """Accept JSON values, never carry a typed capability across the port."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False))


def _grant_wire(session_id, grant):
    lease = grant.lease
    return {
        "session_id": session_id, "lease_id": lease.lease_id,
        "effect_id": lease.effect_id, "intent_digest": lease.intent_digest,
        "generation": lease.authority.generation, "writer_fence": lease.authority.writer_fence,
    }


def _intent_wire(intent):
    # The existing service exposes a deliberately bounded intent projection,
    # not a serialized completion bearer or arbitrary effect object.
    return {
        "effect_id": intent.effect_id, "intent_digest": intent.intent_digest,
        "effect_kind": intent.effect_kind,
        "authority": {"source": "core", "generation": intent.authority.generation,
                      "writer_fence": intent.authority.writer_fence},
    }


class _RealCoreRPC:
    def __init__(self, fixture):
        self.fixture = fixture
        self.operations = LiveHealthCoreOperations(
            fixture.plugin,
            current_generation=lambda: fixture.base.head.read().head.generation,
        )
        self.calls = []
        self.responses = []
        self._sessions = {}
        self._lock = threading.RLock()

    def _runtime(self):
        plugin = self.fixture.plugin
        probe = plugin.probe()
        return {
            "state": probe.state.value, "reason_code": probe.reason_code,
            "generation": self.fixture.base.head.read().head.generation,
            "health_writes_allowed": plugin.health_writes_allowed(),
            "model_effects_allowed": plugin.model_effects_allowed(),
            "outbound_effects_allowed": plugin.outbound_effects_allowed(),
            "content": None,
        }

    def request(self, kind, payload, *, request_id=None):
        if kind not in {"command", "managed-read", "controlled-effect"}:
            raise ProtocolViolation("invalid verifier CorePort kind")
        if request_id is None:
            request_id = "ticket126-offline-rpc:" + uuid.uuid4().hex
        if type(request_id) is not str or not request_id:
            raise ProtocolViolation("invalid verifier CorePort request identifier")
        payload = _wire_copy(payload)
        if type(payload) is not dict:
            raise ProtocolViolation("invalid verifier CorePort payload")
        # The real service is a bounded serial dispatcher. Do not hold this
        # transport lock or a Core lock while waiting for external network I/O.
        with self._lock:
            self.calls.append((kind, copy.deepcopy(payload), request_id))
            if kind == "command" and payload == {"operation": "health-runtime-probe"}:
                result = {"projection": self._runtime()}
            elif kind == "managed-read" and payload == {"projection": "health-runtime"}:
                result = self._runtime()
            elif kind in {"command", "managed-read"}:
                result = self.operations.dispatch(kind, payload)
            else:
                result = self._controlled(payload)
            # 'accepted' here means a processed RPC envelope, exactly as in
            # ProductionCoreService. Business statuses remain inside result.
            response = {
                "protocol_version": 1, "kind": kind, "request_id": request_id,
                "status": "accepted", "payload": _wire_copy(result),
            }
            self.responses.append(copy.deepcopy(response))
            return response

    def _session_grant(self, intent_id, supplied):
        _exact(supplied, _GRANT_FIELDS)
        if (type(supplied["generation"]) is not int or supplied["generation"] < 1
                or any(type(supplied[key]) is not str or not supplied[key]
                       for key in _GRANT_FIELDS - {"generation"})):
            raise ProtocolViolation("invalid verifier effect session")
        held = self._sessions.get(supplied["session_id"])
        if held is None:
            raise ProtocolViolation("unknown verifier effect session")
        held_intent_id, _intent, grant = held
        if held_intent_id != intent_id or _grant_wire(supplied["session_id"], grant) != supplied:
            raise ProtocolViolation("verifier effect session binding mismatch")
        return grant

    def _controlled(self, value):
        _exact(value, {"interface", "operation", "payload"})
        if value["interface"] != "health-entry-v1":
            raise ProtocolViolation("invalid verifier delivery interface")
        operation, data = value["operation"], value["payload"]
        core = self.fixture.core
        if operation == "delivery-prepare":
            _exact(data, {"intent_id", "attempted_at_utc"})
            prepared = core.prepare_live_delivery(
                data["intent_id"], attempted_at_utc=data["attempted_at_utc"])
            _exact(prepared, {"delivery", "send_intent", "effect_intent"})
            intent = prepared["effect_intent"]
            if intent is None:
                return {"delivery": prepared["delivery"], "send_intent": None,
                        "intent": None, "grant": None}
            if type(intent) is not EffectIntent:
                raise ProtocolViolation("invalid Core-issued effect intent")
            grant = self.fixture.plugin.claim_effect_execution(intent)
            if grant is None:
                return {"delivery": core.live_delivery_status(data["intent_id"]),
                        "send_intent": None, "intent": None, "grant": None}
            if (type(grant) is not EffectExecutionGrant
                    or grant.lease.effect_id != intent.effect_id
                    or grant.lease.intent_digest != intent.intent_digest
                    or grant.lease.authority != intent.authority):
                raise ProtocolViolation("invalid Core-issued execution grant")
            session = "effect-session:ticket126-verifier:" + uuid.uuid4().hex
            self._sessions[session] = (data["intent_id"], intent, grant)
            return {"delivery": prepared["delivery"],
                    "send_intent": prepared["send_intent"], "intent": _intent_wire(intent),
                    "grant": _grant_wire(session, grant)}
        if operation == "delivery-authorize":
            _exact(data, {"intent_id", "grant", "attempted_at_utc"})
            grant = self._session_grant(data["intent_id"], data["grant"])
            authorization = core.authorize_live_delivery(
                data["intent_id"], grant, attempted_at_utc=data["attempted_at_utc"])
            return {"delivery": core.live_delivery_status(data["intent_id"]),
                    "authorization": authorization}
        if operation == "delivery-complete":
            _exact(data, {"intent_id", "grant", "result", "observed_at_utc"})
            grant = self._session_grant(data["intent_id"], data["grant"])
            result = core.complete_live_delivery(
                data["intent_id"], grant, OwnerDeliveryTransportResult.from_wire(data["result"]),
                observed_at_utc=data["observed_at_utc"])
            _exact(result, {"delivery", "source_causal_id", "handoff_complete"})
            # Keep no reusable transport session after a Core-proven handoff.
            # If completion raises, no terminal/handoff is invented here.
            if result["handoff_complete"] is True:
                self._sessions.pop(data["grant"]["session_id"], None)
            return result
        raise ProtocolViolation("unsupported verifier delivery operation")


class _Response:
    def __init__(self, value, *, status=200):
        self.value, self.status = value, status
        self.ok = 200 <= status < 300

    async def __aenter__(self):
        if isinstance(self.value, BaseException):
            raise self.value
        return self

    async def __aexit__(self, *args):
        return None

    async def text(self):
        return self.value if type(self.value) is str else json.dumps(self.value)


class _HTTP:
    """HTTP boundary only: actual pinned serialization and low-level functions run."""
    def __init__(self, results=None):
        self.results = list(results or [])
        self.posts, self.options = [], []
        self.closed = False

    def factory(self, **options):
        self.options.append(options)
        return self

    async def __aenter__(self):
        self.closed = False
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def close(self):
        self.closed = True

    def post(self, url, *, data, headers, **options):
        self.posts.append({"url": url, "payload": json.loads(data), "options": options})
        value = self.results.pop(0) if self.results else {"ret": 0, "errcode": 0}
        return value if isinstance(value, _Response) else _Response(value)


def _authorization():
    from partner_health_steward.delivery import OwnerDeliverySendIntent, OwnerWeixinDestination
    payload = {"text": "[合成测试] 唯一固定回复"}
    intent = OwnerDeliverySendIntent(
        intent_id="outbox:" + "a" * 64, attempt_ref="owner-delivery-attempt:" + "b" * 64,
        destination=OwnerWeixinDestination(partner_id="account-offline", owner_sender_id="owner-offline",
            conversation_id="owner-offline", channel="weixin", entrypoint="health_weixin"),
        payload_ref="owner-message:ticket126-synthetic", payload_digest="sha256:" + "e" * 64,
        idempotency_key="health-owner-delivery:v1:" + "c" * 64)
    execution = {"lease_id": "lease:ticket126",
             "effect_id": "effect:ticket126", "intent_digest": "sha256:" + "d" * 64,
             "generation": 7, "writer_fence": "writer-fence:ticket126"}
    return {"purpose": "owner-reply", "recipient_role": "owner", "account_id": "account-offline", "intent_id": intent.intent_id,
            "send_intent": intent.to_wire(), "payload": payload, "payload_digest": _sha(_canonical(payload)),
            "route_id": intent.destination.route_id, "route_generation": 1, "execution": execution}


async def _transport_gate():
    from partner_health_steward.weixin_transport import (
        WeixinTransportBinding, PinnedWeixinIngressTransport, PinnedWeixinOwnerDeliveryAdapter,
    )
    binding = WeixinTransportBinding("account-offline", "https://ilink.offline.invalid")
    network = _HTTP([{"ret": 0, "msgs": [{"message_id": "native-one"}, {"message_id": "native-two"}],
                      "get_updates_buf": "next-cursor"},
                     {"ret": 0, "msgs": [], "get_updates_buf": "same-cursor"}])
    ingress = PinnedWeixinIngressTransport(binding, token="synthetic-token", session_factory=network.factory)
    assert await ingress.connect() is True
    result = await ingress.get_updates("current-cursor")
    assert [m["message_id"] for m in result["msgs"]] == ["native-one", "native-two"]
    await ingress.acknowledge_cursor("next-cursor")
    assert len(network.posts) == 1  # no invented remote ACK request
    await ingress.get_updates("caller-approved-cursor")
    assert network.posts[0]["payload"]["get_updates_buf"] == "current-cursor"
    assert network.posts[1]["payload"]["get_updates_buf"] == "caller-approved-cursor"
    await ingress.disconnect()
    assert network.closed
    authorization = _authorization()
    observations = []
    for response, expected in (({"ret": 0, "errcode": 0}, "accepted"),
                               ({"ret": -14, "errcode": -14}, "rejected"),
                               ({}, "unknown"),
                               (TimeoutError("PRIVATE-HTTP-SENTINEL"), "unknown"),
                               (_Response("PRIVATE-HTTP-SENTINEL", status=503), "unknown")):
        http = _HTTP([response])
        adapter = PinnedWeixinOwnerDeliveryAdapter(binding, copy.deepcopy(authorization),
            token="synthetic-token", context_token_provider=lambda recipient: "synthetic-context",
            session_factory=http.factory)
        observed = await asyncio.to_thread(adapter.send, copy.deepcopy(authorization["send_intent"]))
        assert observed["status"] == expected, observed
        assert set(observed) == {"status", "result_ref", "evidence_ref"}
        assert "PRIVATE-HTTP-SENTINEL" not in repr(observed)
        assert len(http.posts) == 1, "no retry or tokenless fallback"
        sent = http.posts[0]["payload"]["msg"]
        assert sent["to_user_id"] == "owner-offline"
        assert sent["context_token"] == "synthetic-context"
        assert sent["item_list"] == [{"type": 1, "text_item": {"text": authorization["payload"]["text"]}}]
        assert http.posts[0]["options"].get("allow_redirects") is False
        assert all(options.get("trust_env", False) is False for options in http.options)
        observations.append(sent["client_id"])
    assert len(set(observations)) == 1, "same Core identity must not become random native IDs"
    http = _HTTP()
    adapter = PinnedWeixinOwnerDeliveryAdapter(binding, authorization, token="synthetic-token",
        context_token_provider=lambda recipient: "synthetic-context", session_factory=http.factory)
    tampered = copy.deepcopy(authorization["send_intent"])
    tampered["destination"]["owner_sender_id"] = "another-recipient"
    try:
        observed = await asyncio.to_thread(adapter.send, tampered)
    except Exception as exc:
        assert "PRIVATE" not in repr(exc)
    else:
        assert observed["status"] != "accepted"
    assert http.posts == []
    # Contact serialization is a separate role with exactly the approved minimum.
    contact = copy.deepcopy(authorization)
    alert = {"owner_recognizable_name": "合成主人称呼", "event_time": "2026-08-24T03:50:00+00:00",
             "fixed_urgent_help_request": "请尽快联系并协助主人获得紧急帮助。"}
    contact.update(purpose="contact-alert", recipient_role="support-contact", route_id="weixin-ilink-partner",
        payload={"contact_alert": alert}, payload_digest=_sha(_canonical({"contact_alert": alert})),
        send_intent={"destination": {"contact_id": "support-contact:offline", "identity_label": "合成联系人",
            "method_kind": "weixin_user", "method_value": "wxid_offline_contact",
            "route_id": "weixin-ilink-partner", "route_generation": 1}, "contact_alert": alert})
    http = _HTTP()
    adapter = PinnedWeixinOwnerDeliveryAdapter(binding, contact, token="synthetic-token",
        context_token_provider=lambda recipient: "synthetic-context", session_factory=http.factory)
    result = await asyncio.to_thread(adapter.send, copy.deepcopy(contact["send_intent"]))
    assert result["status"] == "accepted" and len(http.posts) == 1
    sent = http.posts[0]["payload"]["msg"]
    assert sent["to_user_id"] == "wxid_offline_contact"
    text = sent["item_list"][0]["text_item"]["text"]
    assert all(value in text for value in alert.values())
    invalid = copy.deepcopy(contact)
    invalid["send_intent"]["destination"]["method_kind"] = "telephone_e164"
    http = _HTTP()
    try:
        adapter = PinnedWeixinOwnerDeliveryAdapter(binding, invalid, token="synthetic-token",
            context_token_provider=lambda recipient: "synthetic-context", session_factory=http.factory)
        await asyncio.to_thread(adapter.send, invalid["send_intent"])
    except Exception:
        pass
    assert http.posts == []


def _initialize(fixture, *, proactive=True):
    request = fixture.daily.initialization_request()
    request = replace(request, preferences=replace(request.preferences,
        contact_window="00:00-00:00", proactive_support=proactive))
    pending = replace(request, owner_consent=False, first_hop_route_consent=False)
    disclosure = InitializationDisclosure.from_storage(fixture.port.exchange("command", _operation(
        "initialization-disclosure", {"initialization": pending.to_storage()}))["disclosure"])
    evidence = OwnerConsentEvidence.for_initialization(request, fixture.init.asset, disclosure,
        owner_confirmed=True, first_hop_route_confirmed=True)
    message = fixture.daily.message("offline", generation=fixture.head.read().head.generation)
    wire = asdict(message); wire["body"] = evidence.to_message_body()
    result = fixture.port.exchange("command", _operation("receive-weixin", {"message": wire}))
    assert result["response"]["status"] == "accepted", result
    for name, payload in (("initialization-consent", {"initialization": request.to_storage()}),
                          ("initialization-commit", {}), ("initialization-finalize", {})):
        result = fixture.port.exchange("command", _operation(name, payload))
        assert result["response"]["status"] in {"accepted", "replayed"}, result
    assert fixture.port.exchange("managed-read", _projection("health-entry-initialization"))[
        "initialization"]["phase"] == "enabled"


def _daily_result(fixture, suffix):
    message = fixture.daily.message("offline", causal_id="ticket126-daily:" + suffix,
        generation=fixture.head.read().head.generation, requested_capability="health-steward",
        message_id="ticket126-native:" + suffix, native_cursor="ticket126-cursor:" + suffix,
        protocol_timestamp="2026-08-24T09:05:00+08:00", received_at="2026-08-24T09:05:01+08:00")
    wire = asdict(message); wire["body"] = "我昨晚没睡好"
    response = fixture.port.exchange("command", _operation("receive-weixin", {"message": wire}))["response"]
    assert response["status"] == "accepted", response
    return response["meta"]["turn_result"]


class _RecordingWire:
    """Network seam records the *Core-authorized* package, never a business result."""
    def __init__(self, authorization, calls, *, unknown=False):
        self.authorization, self.calls, self.unknown = copy.deepcopy(authorization), calls, unknown

    def send(self, wire, /):
        assert wire == self.authorization["send_intent"]
        self.calls.append(copy.deepcopy(self.authorization))
        if self.unknown:
            raise TimeoutError("synthetic response ownership lost")
        return {"status": "accepted", "result_ref": "ticket126-interface-observation",
                "evidence_ref": "ticket126-offline-http-response"}


def _bridge(port, calls, *, unknown=False):
    from partner_health_steward.live_delivery import LiveWeixinDeliveryBridge
    return LiveWeixinDeliveryBridge(port,
        lambda authorization: _RecordingWire(authorization, calls, unknown=unknown),
        clock=lambda: datetime.now(timezone.utc))


def _turn_reference(turn):
    return {"kind": "committed-turn", "source_causal_id": turn["source_causal_id"],
            "turn_result": copy.deepcopy(turn)}


class Ticket126LiveDeliveryVerificationTests(unittest.TestCase):
    maxDiff = None

    def _modules(self):
        for name in ("weixin_transport", "live_delivery"):
            self.assertIsNotNone(importlib.util.find_spec("partner_health_steward." + name),
                                 "126 prerequisite: real pinned transport and controlled bridge are missing")
        return importlib.import_module("partner_health_steward.live_delivery")

    def _run_child(self, gate, fixture=None, *, data=None):
        pinned = Path(os.environ.get("TICKET118_PINNED_HERMES_SOURCE", "/tmp/health-steward-hermes-git"))
        self.assertTrue((pinned / "gateway/platforms/weixin.py").is_file())
        with tempfile.TemporaryDirectory(prefix="ticket126-hermes-home-") as directory:
            home = Path(directory)
            if fixture is None:
                publication = HermesReleasePublisher(_REPOSITORY).build(home / "releases").to_wire()
                release_root = home / "releases" / publication["release_digest"].removeprefix("sha256:")
            else:
                release_root = Path(fixture.binding["release_root"])
            host = json.loads((release_root / "host-release-manifest.json").read_text())
            config = {"gate": gate, "data": data or {}}
            if fixture is not None:
                request = fixture.daily.initialization_request()
                request = replace(request, owner_consent=False, first_hop_route_consent=False,
                    preferences=replace(request.preferences, contact_window="00:00-00:00"))
                config.update(endpoint=fixture.port.endpoint, policy=fixture.daily.policy.to_storage(),
                              initialization=request.to_storage())
            config_path = home / "offline-config.json"
            config_path.write_bytes(_canonical(config)); config_path.chmod(0o600)
            env = {key: os.environ[key] for key in ("PATH", "LANG", "SYSTEMROOT") if key in os.environ}
            env.update(HERMES_HOME=str(home), HERMES_CONFIG=str(home / "config.yaml"),
                PYTHONDONTWRITEBYTECODE="1", TICKET126_PINNED_SOURCE=str(pinned),
                TICKET126_PUBLISHED_PLUGIN=str(release_root / "plugin/health-weixin"),
                TICKET126_HOST_RELEASE_DIGEST=host["release_digest"])
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--pinned-gate", str(config_path)],
                cwd=home, env=env, capture_output=True, text=True, timeout=40)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("TICKET126-" + gate + "-PASS", run.stdout)
            report_path = home / "offline-result.json"
            return json.loads(report_path.read_text()) if report_path.exists() else None

    def test_v126_01_real_pinned_http_boundary_is_single_exact_and_sanitized(self):
        self._modules()
        self._run_child("transport")

    def test_v126_02_real_init_native_identity_survives_cursor_change_and_restart(self):
        self._modules()
        with _service() as fixture:
            formed = self._run_child("init-form", fixture)
            state = fixture.port.exchange("managed-read", _projection("health-entry-initialization"))
            self.assertEqual(state["initialization"]["phase"], "uninitialized")
            fixture.service.close()
            from partner_health_steward.production_core_service import ProductionCoreService
            restarted = ProductionCoreService(fixture.binding, current_head=fixture.head, live_runtime=fixture.runtime)
            fixture.service = restarted
            fixture.port = _SocketPort(restarted.start())
            try:
                confirmed = self._run_child("init-confirm", fixture, data=formed)
                self.assertEqual(confirmed["new_disclosure_sends"], 0)
                state = fixture.port.exchange("managed-read", _projection("health-entry-initialization"))
                self.assertEqual(state["initialization"]["phase"], "enabled")
            finally:
                restarted.close()

    def test_v126_03_daily_reply_comes_from_committed_core_and_current_authority(self):
        self._modules()
        with _service() as fixture:
            _initialize(fixture, proactive=False)
            turn = _daily_result(fixture, "exact")
            reference = _turn_reference(turn)
            reference["turn_result"]["owner_reply"] = "CALLER-INJECTED-NOT-AUTHORIZED"
            calls = []
            bridge = _bridge(fixture.port, calls)
            result = asyncio.run(bridge.send_committed(reference))
            self.assertTrue(result["handoff_complete"], result)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["payload"], {"text": turn["owner_reply"]})
            self.assertNotIn("CALLER-INJECTED", repr(calls))
            intent = result["deliveries"][0]["intent_id"]
            projection = fixture.port.exchange("managed-read", _projection("health-entry-delivery", {"intent_id": intent}))["delivery"]
            self.assertEqual(projection["current_layer"], "accepted")
            self.assertTrue(projection["handoff_complete"])
            self.assertNotIn("delivered", projection.values())
            self.assertNotIn("read", projection.values())
            again = asyncio.run(bridge.send_committed(_turn_reference(turn)))
            self.assertTrue(again["handoff_complete"])
            self.assertEqual(len(calls), 1)
            forged = _turn_reference(turn); forged["turn_result"]["transition_id"] = "transition:foreign"
            rejected = asyncio.run(bridge.send_committed(forged))
            self.assertFalse(rejected["handoff_complete"])
            self.assertEqual(len(calls), 1)
        with _service() as fixture:
            _initialize(fixture)
            turn = _daily_result(fixture, "head-unavailable")
            prepared_grants = []
            class FailHeadAfterPrepare:
                def request(self, kind, payload, *, request_id=None):
                    result = fixture.port.request(kind, payload, request_id=request_id)
                    if payload.get("operation") == "delivery-prepare" and type(result) is dict:
                        grant = result.get("payload", {}).get("grant")
                        if grant is not None:
                            prepared_grants.append(grant)
                            fixture.client.get_error = TimeoutError("synthetic current-head unavailable after claim")
                    return result
            calls = []
            try:
                result = asyncio.run(_bridge(FailHeadAfterPrepare(), calls).send_committed(_turn_reference(turn)))
            except Exception:
                pass
            else:
                self.assertFalse(result["handoff_complete"])
            self.assertTrue(prepared_grants, "negative class must reach a real prepare/claim first")
            self.assertEqual(calls, [])

    def test_v126_04_real_socket_registry_handoff_and_unknown_restart_do_not_resend(self):
        self._modules()
        with _service() as fixture:
            _initialize(fixture)
            result = self._run_child("daily", fixture)
            self.assertEqual(result["sends"], 1)
            self.assertEqual(set(result["kinds"]), {"command", "managed-read", "controlled-effect"})
            self.assertTrue(result["handoff_complete"])
        with _service() as fixture:
            _initialize(fixture)
            lost = self._run_child("daily-loss", fixture)
            self.assertEqual(lost["sends"], 1)
            self.assertFalse(lost["handoff_complete"])
            intent = lost["intent_id"]
            fixture.service.close()
            from partner_health_steward.production_core_service import ProductionCoreService
            restarted = ProductionCoreService(fixture.binding, current_head=fixture.head, live_runtime=fixture.runtime)
            fixture.service = restarted; fixture.port = _SocketPort(restarted.start())
            try:
                calls = []
                result = asyncio.run(_bridge(fixture.port, calls).send_committed(lost["binding"]))
                self.assertTrue(result["handoff_complete"])
                self.assertEqual(calls, [], "an already attempted delivery cannot cross the network again")
                status = fixture.port.exchange("managed-read", _projection("health-entry-delivery", {"intent_id": intent}))["delivery"]
                self.assertEqual(status["current_layer"], "unknown")
                self.assertTrue(status["unknown_frozen"])
                denied = fixture.port.request("controlled-effect", _operation("delivery-complete", {
                    "intent_id": intent, "grant": lost["grant"],
                    "result": {"status": "accepted", "result_ref": "forged", "evidence_ref": "forged"},
                    "observed_at_utc": datetime.now(timezone.utc).isoformat()}))
                self.assertTrue(denied is None or denied.get("payload", {}).get("delivery", {}).get("current_layer") != "accepted")
                # Recovery has proven the source's durable unknown handoff.
                # A general UNKNOWN write guard must not strand this exact ACK.
                directive = fixture.port.exchange("managed-read", _projection(
                    "health-entry-cursor-directive", {"source_causal_id": lost["binding"]["source_causal_id"]}))["directive"]
                self.assertIsNotNone(directive, "durable unknown handoff must permit its exact source cursor")
                self.assertEqual(directive["native_cursor"], "cursor-live-daily")
                acknowledged = fixture.port.exchange("command", _operation("native-cursor-result", {
                    "source_causal_id": lost["binding"]["source_causal_id"], "status": "advanced"}))["response"]
                self.assertIn(acknowledged["status"], {"accepted", "replayed"})
                self.assertEqual(fixture.port.exchange("managed-read", _projection(
                    "health-entry-native-cursor"))["native_cursor"], "cursor-live-daily")
                self.assertEqual(calls, [], "cursor handoff never reissues the uncertain send")
            finally:
                restarted.close()
        with _service() as fixture:
            _initialize(fixture)
            result = self._run_child("daily-unknown", fixture)
            self.assertEqual(result["sends"], 1)
            self.assertTrue(result["handoff_complete"])
            self.assertTrue(result["unknown_frozen"])

    def test_v126_05_real_contact_authority_minimal_alert_unknown_and_bounded_correction(self):
        self._modules()
        self._run_child("safety-routing")
        from partner_health_steward.delivery import OwnerDeliveryTransportResult
        from tests import test_ticket116_integration as contact_fixture
        for unknown in (False, True):
            with self.subTest(response_lost=unknown):
                fixture = contact_fixture.Ticket116VerificationTests()
                fixture.setUp()
                try:
                    assets = fixture._synthetic_assets()
                    fixture._restart_with_assets(assets)
                    fixture._configure_synthetic_contact()
                    fixture._grant_contact_authority()
                    fixture._grant_contact_authority(correction=True)
                    response = fixture.plugin.receive_weixin(fixture._message(
                        contact_fixture.CountingBody("SYNTHETIC:DANGER_CONFIRMED"),
                        suffix="126-real-safety"), peer_id="plugin")
                    meta = fixture._meta_wire(response)
                    self.assertEqual(meta["branch"], "danger-escalation")
                    reference = {"kind": "committed-safety", "source_causal_id": response.causal_id,
                                 "result_ref": meta["result_ref"]}
                    core = fixture.core
                    bound = core.bind_live_delivery(reference)
                    self.assertEqual({p["recipient_role"] for p in bound["deliveries"]}, {"owner", "support-contact"})
                    calls = []
                    def execute(intent_id, *, lost=False, at="2026-08-24T03:50:01+00:00"):
                        prepared = core.prepare_live_delivery(intent_id, attempted_at_utc=at)
                        effect = prepared["effect_intent"]
                        self.assertIsNotNone(effect)
                        grant = fixture.plugin.claim_effect_execution(effect)
                        self.assertIsNotNone(grant)
                        authorization = core.authorize_live_delivery(intent_id, grant, attempted_at_utc=at)
                        self.assertIsNotNone(authorization)
                        observed = _RecordingWire(authorization, calls).send(authorization["send_intent"])
                        if lost:
                            observed = {"status": "unknown", "result_ref": "synthetic-response-lost",
                                        "evidence_ref": "synthetic-no-terminal"}
                        result = core.complete_live_delivery(intent_id, grant,
                            OwnerDeliveryTransportResult.from_wire(observed), observed_at_utc=at)
                        self.assertTrue(result["delivery"]["handoff_complete"])
                        return authorization, result
                    owner = next(p for p in bound["deliveries"] if p["recipient_role"] == "owner")
                    owner_authorized, _ = execute(owner["intent_id"])
                    self.assertEqual(owner_authorized["payload"], {
                        "text": assets["minimum_help_bundle"]["templates"]["danger_owner"]["text"]})
                    contact = next(p for p in bound["deliveries"] if p["recipient_role"] == "support-contact")
                    authorization, result = execute(contact["intent_id"], lost=unknown)
                    self.assertEqual(authorization["recipient_role"], "support-contact")
                    alert = authorization["payload"]["contact_alert"]
                    self.assertEqual(set(alert), {"owner_recognizable_name", "event_time", "fixed_urgent_help_request"})
                    self.assertNotIn("SYNTHETIC:DANGER_CONFIRMED", repr(alert))
                    self.assertEqual(authorization["send_intent"]["destination"]["method_kind"], "weixin_user")
                    self.assertEqual(result["delivery"]["current_layer"], "unknown" if unknown else "accepted")
                    self.assertEqual(result["delivery"]["unknown_frozen"], unknown)
                    before = len(calls)
                    replay = core.prepare_live_delivery(contact["intent_id"], attempted_at_utc="2026-08-24T03:51:00+00:00")
                    self.assertIsNone(replay["effect_intent"])
                    self.assertIsNone(replay["send_intent"])
                    self.assertEqual(len(calls), before)
                    fixture._apply_contact_control("pause")
                    corrected = fixture._health("safety.correct", {
                        "source_alert_intent_id": meta["contact_alert"]["intent_id"],
                        "basis_change_ref": "owner-correction:ticket126",
                        "corrected_at_utc": "2026-08-24T03:52:00+00:00"}, suffix="126-correction")
                    correction_id = corrected["contact_correction"]["intent_id"]
                    correction = core.bind_live_delivery({"kind": "contact-alert", "intent_id": correction_id})
                    correction_wire, _ = execute(correction["deliveries"][0]["intent_id"], at="2026-08-24T03:52:01+00:00")
                    self.assertEqual(correction_wire["purpose"], "contact-correction")
                    self.assertEqual(correction_wire["send_intent"]["destination"], authorization["send_intent"]["destination"])
                    self.assertEqual(set(correction_wire["payload"]["contact_alert"]), set(alert))
                    self.assertIsNone(core.prepare_live_delivery(correction_id,
                        attempted_at_utc="2026-08-24T03:52:02+00:00")["effect_intent"])
                finally:
                    fixture.tearDown()
        fixture = contact_fixture.Ticket116VerificationTests(); fixture.setUp()
        try:
            fixture._restart_with_assets(fixture._synthetic_assets())
            fixture._configure_synthetic_contact(); fixture._grant_contact_authority()
            formed = fixture._health("safety.evaluate", {"source_causal_id": "ticket126-stale-contact",
                "event_time": "2026-08-24T03:50:00+00:00", "owner_recognizable_name": "合成主人称呼",
                "safety_rule_bundle_hash": fixture.safety_bundle_hash,
                "facts": {"safety_capability": "available", "danger": "confirmed", "scope": "in-scope"}},
                suffix="126-stale-contact")
            intent = formed["contact_alert"]["intent_id"]
            fixture._apply_contact_control("revoke_alert_authority")
            try:
                bound = fixture.core.bind_live_delivery({"kind": "contact-alert", "intent_id": intent})
                prepared = fixture.core.prepare_live_delivery(intent, attempted_at_utc="2026-08-24T03:50:01+00:00")
            except Exception:
                pass
            else:
                self.assertIsNone(prepared["send_intent"])
        finally:
            fixture.tearDown()


class _PollResponse(_Response):
    async def text(self):
        await asyncio.sleep(0.01)
        return await super().text()


class _HTTPRouter:
    """One HTTP router shared by independent session objects and event loops."""
    def __init__(self, *, send_unknown=False):
        self.batches, self.posts, self.cursors, self.sends, self.sessions = [], [], [], [], []
        self.send_unknown = send_unknown

    def factory(self, **options):
        assert options.get("trust_env", False) is False
        router = self
        class Session:
            def __init__(self):
                self.closed = False
                self.loop = id(asyncio.get_running_loop())
            async def __aenter__(self):
                self.loop = id(asyncio.get_running_loop())
                return self
            async def __aexit__(self, *args):
                self.closed = True
            async def close(self):
                self.closed = True
            def post(self, url, *, data, headers, **kwargs):
                assert kwargs.get("allow_redirects") is False
                if self.loop is not None:
                    assert self.loop == id(asyncio.get_running_loop()), "cross-loop session reuse"
                body = json.loads(data)
                router.posts.append((url, copy.deepcopy(body)))
                if "getupdates" in url:
                    cursor = body["get_updates_buf"]
                    router.cursors.append(cursor)
                    value = router.batches.pop(0) if router.batches else {"ret": 0, "msgs": [], "get_updates_buf": cursor}
                    return _PollResponse(value)
                assert "sendmessage" in url, url
                router.sends.append(copy.deepcopy(body["msg"]))
                if router.send_unknown:
                    return _Response(TimeoutError("synthetic send response unconfirmed"))
                return _Response({"ret": 0, "errcode": 0})
        session = Session()
        self.sessions.append(session)
        return session

    def enqueue(self, cursor, native):
        self.batches.append({"ret": 0, "msgs": [copy.deepcopy(native)], "get_updates_buf": cursor})


def _native_message(identifier, text, policy):
    return {"message_id": identifier, "from_user_id": policy["owner_sender_id"],
            "to_user_id": policy["partner_id"], "conversation_id": policy["conversation_id"],
            "msg_type": 1, "create_time_ms": 1787520000000,
            "context_token": "synthetic-context", "item_list": [{"type": 1, "text_item": {"text": text}}]}


async def _wait_until(predicate):
    for _ in range(600):
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.01)
    raise AssertionError("actual pinned lifecycle did not reach expected Core/HTTP observation")


async def _registered_gate(config):
    from unittest.mock import patch
    from partner_health_steward.live_weixin import LiveHealthWeixinAdapter
    from gateway.platforms.weixin import ContextTokenStore
    core = _CorePortClient(config["endpoint"])
    kinds, completions, bindings, prepared = [], [], [], []
    lost_completions = []
    class Port:
        def request(self, kind, payload, *, request_id=None):
            kinds.append(kind)
            if payload.get("operation") == "delivery-bind":
                bindings.append(copy.deepcopy(payload["payload"]["binding"]))
            if config["gate"] == "daily-loss" and payload.get("operation") == "delivery-complete":
                lost_completions.append(copy.deepcopy(payload))
                raise ConnectionResetError("synthetic lost Core completion request")
            result = core.request(kind, payload, request_id=request_id)
            if payload.get("operation") == "delivery-prepare" and type(result) is dict and result["payload"].get("grant"):
                prepared.append(copy.deepcopy(result["payload"]))
            if payload.get("operation") == "delivery-complete" and type(result) is dict:
                completions.append(copy.deepcopy(result["payload"]))
            return result
    def projection(name, payload=None):
        response = core.request("managed-read", _projection(name, payload), request_id="ticket126-child-read")
        assert response is not None, name
        return response["payload"]
    token_store = ContextTokenStore(os.environ["HERMES_HOME"])
    token_store.set(config["policy"]["partner_id"], config["policy"]["owner_sender_id"], "synthetic-context")
    router = _HTTPRouter(send_unknown=config["gate"] == "daily-unknown")
    extra = {"admission_policy": config["policy"], "core_port": Port(),
             "initialization_template": config["initialization"],
             "weixin_transport_binding": {"account_id": config["policy"]["partner_id"],
                                          "base_url": "https://ilink.offline.invalid"}}
    with patch("aiohttp.ClientSession", router.factory):
        adapter = _create_registered(extra)
        assert isinstance(adapter, LiveHealthWeixinAdapter), "actual registry did not select production Live Adapter"
        adapter.set_message_handler(lambda event: None)
        assert await adapter.connect(is_reconnect=False)
        try:
            gate = config["gate"]
            if gate in {"init-form", "init-confirm"}:
                first = _native_message("ticket126-native-initialization", "/health-init", config["policy"])
                cursor = "cursor-init" if gate == "init-form" else "cursor-init-after-restart"
                router.enqueue(cursor, first)
                await _wait_until(lambda: cursor in router.cursors)
                assert projection("health-entry-initialization")["initialization"]["phase"] == "uninitialized"
                if gate == "init-form":
                    assert len(router.sends) == 1
                    sent = router.sends[0]["item_list"][0]["text_item"]["text"]
                    import re
                    match = re.search(r"/health-init-confirm\s+(\S+)\s+(\S+)", sent)
                    assert match, "real disclosure must contain its exact independent confirmation command"
                    workflow, disclosure = match.groups()
                    initial = next(binding for binding in bindings if binding["kind"] == "initialization-disclosure")
                    for bad in (dict(copy.deepcopy(initial), text="CALLER-PLAINTEXT"), copy.deepcopy(initial)):
                        if "text" not in bad:
                            bad["headers"]["sender_id"] = "outside-owner"
                        try:
                            denied = core.request("command", _operation("delivery-bind", {"binding": bad}),
                                                  request_id="ticket126-negative-init-binding")
                        except _HostVerificationFailure as exc:
                            # Only these deliberately invalid bindings may be
                            # rejected by closing the strict framed connection.
                            assert str(exc) == "core-frame-truncated"
                            assert "CALLER-PLAINTEXT" not in repr(exc)
                            assert "outside-owner" not in repr(exc)
                            denied = None
                        assert denied is None or not denied.get("payload", {}).get("handoff_complete", False)
                        assert denied is None or denied.get("payload", {}).get("status") != "accepted"
                        assert len(router.sends) == 1
                        assert projection("health-entry-initialization")["initialization"]["phase"] == "uninitialized"
                    assert len(router.sends) == 1
                    router.enqueue("cursor-init-replay", first)
                    await _wait_until(lambda: "cursor-init-replay" in router.cursors)
                    assert len(router.sends) == 1
                    result = {"workflow": workflow, "disclosure": disclosure,
                              "command": "/health-init-confirm " + workflow + " " + disclosure}
                else:
                    assert router.sends == [], "retained first event must not send another disclosure"
                    confirm = _native_message("ticket126-independent-confirm", config["data"]["command"], config["policy"])
                    confirm["create_time_ms"] += 1000
                    router.enqueue("cursor-confirm", confirm)
                    await _wait_until(lambda: projection("health-entry-initialization")["initialization"]["phase"] == "enabled")
                    result = {"new_disclosure_sends": len(router.sends)}
            elif gate in {"daily", "daily-loss", "daily-unknown"}:
                native = _native_message("ticket126-native-daily-socket", "我昨晚没睡好", config["policy"])
                approved = projection("health-entry-native-cursor")["native_cursor"]
                router.enqueue("cursor-live-daily", native)
                if gate == "daily-loss":
                    await _wait_until(lambda: router.sends and lost_completions and len(router.cursors) >= 4)
                    assert len(router.sends) == 1
                    assert "cursor-live-daily" not in router.cursors, "failed handoff must not advance the next poll cursor"
                    assert projection("health-entry-native-cursor")["native_cursor"] == approved
                    assert prepared and bindings
                    delivery = projection("health-entry-delivery", {"intent_id": prepared[-1]["delivery"]["intent_id"]})["delivery"]
                    assert not delivery["handoff_complete"]
                    result = {"sends": 1, "handoff_complete": delivery["handoff_complete"],
                              "intent_id": delivery["intent_id"], "binding": bindings[-1],
                              "grant": prepared[-1]["grant"]}
                else:
                    await _wait_until(lambda: "cursor-live-daily" in router.cursors)
                    assert len(router.sends) == 1
                    assert completions and completions[-1]["handoff_complete"] is True
                    committed = projection("health-entry-delivery", {"intent_id": completions[-1]["delivery"]["intent_id"]})["delivery"]
                    expected_layer = "unknown" if gate == "daily-unknown" else "accepted"
                    assert committed["current_layer"] == expected_layer and committed["handoff_complete"] is True
                    assert committed["unknown_frozen"] is (gate == "daily-unknown")
                    assert projection("health-entry-native-cursor")["native_cursor"] == "cursor-live-daily"
                    before_polls = len(router.cursors)
                    router.enqueue("cursor-live-daily", native)
                    await _wait_until(lambda: len(router.cursors) >= before_polls + 3)
                    assert len(router.sends) == 1
                    result = {"sends": len(router.sends), "kinds": sorted(set(kinds)),
                              "handoff_complete": committed["handoff_complete"],
                              "unknown_frozen": committed["unknown_frozen"]}
            else:
                raise AssertionError(gate)
        finally:
            await adapter.disconnect()
    assert all(session.closed for session in router.sessions)
    return result


def _create_registered(extra):
    from gateway.config import PlatformConfig
    from gateway.platform_registry import platform_registry, PlatformEntry
    from partner_health_steward import hermes_host
    from partner_health_steward.host_contract import _CURRENT_PROCESS_ACTIVATION_CAPABILITY, _activation_proof
    class Context:
        def register_platform(self, **fields):
            platform_registry.register(PlatformEntry(**fields))
    hermes_host.register(Context())
    entry = platform_registry.get("health_weixin")
    config = PlatformConfig(enabled=True, token="synthetic-token", extra=extra)
    assert platform_registry.create_adapter("health_weixin", config) is None
    proof = _activation_proof(os.environ["TICKET126_HOST_RELEASE_DIGEST"])
    getattr(entry.check_fn, "_ticket118_arm")(_CURRENT_PROCESS_ACTIVATION_CAPABILITY, proof)
    extra.update(registry=platform_registry, activation_capability=_CURRENT_PROCESS_ACTIVATION_CAPABILITY,
                 activation_proof=proof)
    return platform_registry.create_adapter("health_weixin", config)


async def _safety_routing_gate():
    from tests import test_ticket116_integration as contact_fixture
    from partner_health_steward.live_weixin import LiveHealthWeixinAdapter
    from partner_health_steward.live_delivery import LiveWeixinDeliveryBridge
    fixture = contact_fixture.Ticket116VerificationTests()
    fixture.setUp()
    adapter = None
    try:
        assets = fixture._synthetic_assets()
        fixture._restart_with_assets(assets)
        fixture._configure_synthetic_contact(); fixture._grant_contact_authority()
        rpc, calls = _RealCoreRPC(fixture), []
        bridge = LiveWeixinDeliveryBridge(rpc, lambda authorization: _RecordingWire(authorization, calls),
            clock=lambda: fixture.base.owner_clock_value.astimezone(timezone.utc))
        class Ingress:
            def __init__(self):
                self.queue = asyncio.Queue(); self.acknowledged = []
            async def connect(self): return True
            async def disconnect(self): return None
            async def get_updates(self, cursor): return await self.queue.get()
            async def acknowledge_cursor(self, cursor): self.acknowledged.append(cursor)
        ingress = Ingress()
        adapter = _create_registered({"admission_policy": fixture.base.policy.to_storage(),
            "core_port": rpc, "ingress_transport": ingress, "delivery_transport": bridge})
        assert isinstance(adapter, LiveHealthWeixinAdapter)
        assert await adapter.connect()
        native = _native_message("ticket126-routed-danger", "SYNTHETIC:DANGER_CONFIRMED", fixture.base.policy.to_storage())
        ingress.queue.put_nowait({"ret": 0, "msgs": [native], "get_updates_buf": "cursor-safety-routed"})
        await _wait_until(lambda: len(calls) == 2 and "cursor-safety-routed" in ingress.acknowledged)
        owner = next(a for a in calls if a["recipient_role"] == "owner")
        contact = next(a for a in calls if a["recipient_role"] == "support-contact")
        assert owner["payload"] == {"text": assets["minimum_help_bundle"]["templates"]["danger_owner"]["text"]}
        assert set(contact["payload"]["contact_alert"]) == {"owner_recognizable_name", "event_time", "fixed_urgent_help_request"}
        safety_refs = [payload["payload"]["binding"] for kind, payload, _ in rpc.calls
                       if kind == "command" and payload.get("operation") == "delivery-bind"]
        assert len(safety_refs) == 1 and set(safety_refs[0]) == {"kind", "source_causal_id", "result_ref"}
        assert safety_refs[0]["kind"] == "committed-safety"
        receive = next(reply["payload"]["response"] for reply in rpc.responses
                       if type(reply.get("payload")) is dict and type(reply["payload"].get("response")) is dict
                       and reply["payload"]["response"].get("reason_code") == "ticket116-safety-result")
        assert receive["meta"]["result_ref"] == safety_refs[0]["result_ref"]
        assert receive["causal_id"] == safety_refs[0]["source_causal_id"]
        for authorization in calls:
            status = fixture.core.live_delivery_status(authorization["intent_id"])
            assert status["current_layer"] == "accepted" and status["handoff_complete"] is True
        return {"owner_sends": 1, "contact_sends": 1}
    finally:
        if adapter is not None:
            await adapter.disconnect()
        fixture.tearDown()


async def _child_main(path):
    config = json.loads(Path(path).read_text())
    if config["gate"] == "transport":
        await _transport_gate()
        result = {}
    elif config["gate"] == "safety-routing":
        result = await _safety_routing_gate()
    else:
        result = await _registered_gate(config)
    published = (Path(os.environ["TICKET126_PUBLISHED_PLUGIN"]) / "partner_health_steward").resolve()
    for name, module in tuple(sys.modules.items()):
        if name == "partner_health_steward" or name.startswith("partner_health_steward."):
            assert Path(module.__file__).resolve().is_relative_to(published), name
    (Path(path).parent / "offline-result.json").write_bytes(_canonical(result))
    print("TICKET126-" + config["gate"] + "-PASS")


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--pinned-gate":
    asyncio.run(_child_main(sys.argv[2]))
elif __name__ == "__main__":
    unittest.main()

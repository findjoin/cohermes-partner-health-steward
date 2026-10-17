"""Core-owned delivery handoff over the existing three CorePort kinds."""
from __future__ import annotations

import asyncio
import copy
import uuid
from datetime import datetime, timezone

from .delivery import OwnerDeliveryTransportResult
from .initialization import stable_digest


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError("invalid delivery handoff")
    return value


class LiveWeixinDeliveryBridge:
    def __init__(self, core_port, wire_adapter_factory, *, clock):
        if not callable(getattr(core_port, "request", None)) or not callable(wire_adapter_factory) or not callable(clock):
            raise ValueError("invalid live delivery dependencies")
        self._port, self._factory, self._clock = core_port, wire_adapter_factory, clock
        self._lock = asyncio.Lock()

    async def _rpc(self, kind, name, payload):
        selector = "projection" if kind == "managed-read" else "operation"
        identity = "delivery-rpc:" + uuid.uuid4().hex
        response = await asyncio.to_thread(self._port.request, kind, {
            "interface": "health-entry-v1", selector: name, "payload": payload,
        }, request_id=identity)
        _exact(response, {"protocol_version", "kind", "request_id", "status", "payload"})
        if (response["protocol_version"] != 1 or response["kind"] != kind
                or response["request_id"] != identity or response["status"] != "accepted"
                or type(response["payload"]) is not dict):
            raise ValueError("delivery Core response unconfirmed")
        return response["payload"]

    def _at(self):
        now = self._clock()
        if type(now) is not datetime or now.utcoffset() is None:
            raise ValueError("invalid delivery observation clock")
        return now.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _reference(value):
        if type(value) is not dict:
            raise ValueError("invalid delivery reference")
        kind = value.get("kind")
        if kind == "committed-turn" and "turn_result" in value:
            _exact(value, {"kind", "source_causal_id", "turn_result"})
            turn = value["turn_result"]
            if type(turn) is not dict:
                raise ValueError("invalid committed turn reference")
            return {"kind": kind, "source_causal_id": value["source_causal_id"],
                    "record_id": turn["record_id"], "transition_id": turn["transition_id"]}
        if kind == "initialization-disclosure" and "disclosure" in value:
            _exact(value, {"kind", "source_causal_id", "workflow_id", "disclosure", "headers"})
            return {"kind": kind, "source_causal_id": value["source_causal_id"],
                    "workflow_id": value["workflow_id"], "disclosure_id": value["disclosure"]["disclosure_id"],
                    "headers": copy.deepcopy(value["headers"])}
        fields = {
            "committed-turn": {"kind", "source_causal_id", "record_id", "transition_id"},
            "initialization-disclosure": {"kind", "source_causal_id", "workflow_id", "disclosure_id", "headers"},
            "committed-safety": {"kind", "source_causal_id", "result_ref"},
            "owner-outbox": {"kind", "intent_id"}, "contact-alert": {"kind", "intent_id"},
        }.get(kind)
        if fields is None:
            raise ValueError("unsupported delivery reference")
        return copy.deepcopy(_exact(value, fields))

    @staticmethod
    def _delivery(value):
        _exact(value, {"intent_id", "recipient_role", "source_causal_id", "current_layer", "unknown_frozen", "handoff_complete"})
        if value["recipient_role"] not in {"owner", "support-contact"} or type(value["handoff_complete"]) is not bool:
            raise ValueError("invalid Core delivery projection")
        return value

    async def _read(self, intent_id):
        result = await self._rpc("managed-read", "health-entry-delivery", {"intent_id": intent_id})
        _exact(result, {"delivery"})
        return None if result["delivery"] is None else self._delivery(result["delivery"])

    async def _send(self, delivery):
        intent_id = delivery["intent_id"]
        if delivery["handoff_complete"]:
            return delivery
        at = self._at()
        prepared = await self._rpc("controlled-effect", "delivery-prepare", {"intent_id": intent_id, "attempted_at_utc": at})
        _exact(prepared, {"delivery", "send_intent", "intent", "grant"})
        grant, intent = prepared["grant"], prepared["intent"]
        if grant is None or intent is None:
            return self._delivery(prepared["delivery"])
        _exact(grant, {"session_id", "lease_id", "effect_id", "intent_digest", "generation", "writer_fence"})
        _exact(intent, {"effect_id", "intent_digest", "effect_kind", "authority"})
        _exact(intent["authority"], {"source", "generation", "writer_fence"})
        if (intent["effect_kind"] != "owner-delivery" or intent["authority"]["source"] != "core"
                or any(grant[field] != intent[field] for field in ("effect_id", "intent_digest"))
                or any(grant[field] != intent["authority"][field] for field in ("generation", "writer_fence"))):
            raise ValueError("delivery effect grant mismatch")
        authorized = await self._rpc("controlled-effect", "delivery-authorize", {"intent_id": intent_id, "grant": grant, "attempted_at_utc": at})
        _exact(authorized, {"delivery", "authorization"})
        auth = authorized["authorization"]
        if auth is None:
            return self._delivery(authorized["delivery"])
        if (type(auth) is not dict or auth.get("intent_id") != intent_id
                or auth.get("send_intent") != prepared["send_intent"]
                or auth.get("execution") != {field: grant[field] for field in ("lease_id", "effect_id", "intent_digest", "generation", "writer_fence")}):
            raise ValueError("delivery authorization mismatch")
        try:
            adapter = self._factory(copy.deepcopy(auth))
            result = await asyncio.to_thread(adapter.send, copy.deepcopy(auth["send_intent"]))
            result = OwnerDeliveryTransportResult.from_wire(result).to_wire()
        except Exception:
            digest = stable_digest({"intent_id": intent_id, "execution": auth["execution"]}).removeprefix("sha256:")
            result = {"status": "unknown", "result_ref": "delivery-unknown:" + digest, "evidence_ref": "delivery-observation:" + digest}
        try:
            completed = await self._rpc("controlled-effect", "delivery-complete", {
                "intent_id": intent_id, "grant": grant, "result": result, "observed_at_utc": self._at()})
            _exact(completed, {"delivery", "source_causal_id", "handoff_complete"})
            delivery = self._delivery(completed["delivery"])
        except Exception:
            # Exact readback may establish a lost reply. Never send again.
            delivery = await self._read(intent_id)
        if delivery is None or delivery["intent_id"] != intent_id:
            raise ValueError("delivery terminal unconfirmed")
        return delivery

    async def send_committed(self, value):
        source, deliveries = None, []
        async with self._lock:
            try:
                reference = self._reference(value)
                bound = await self._rpc("command", "delivery-bind", {"binding": reference})
                _exact(bound, {"deliveries", "source_causal_id", "handoff_complete"})
                source = bound["source_causal_id"]
                if type(bound["deliveries"]) is not list or type(bound["handoff_complete"]) is not bool:
                    raise ValueError("delivery binding unconfirmed")
                for projection in bound["deliveries"]:
                    projection = self._delivery(projection)
                    try:
                        projection = await self._send(projection)
                    except Exception:
                        try:
                            projection = await self._read(projection["intent_id"]) or projection
                        except Exception:
                            pass
                    deliveries.append(projection)
                handoff = bound["handoff_complete"] or (bool(deliveries) and all(p["handoff_complete"] for p in deliveries))
                status = ("unknown" if any(p["current_layer"] == "unknown" for p in deliveries)
                          else "rejected" if any(p["current_layer"] == "rejected" for p in deliveries)
                          else "accepted" if handoff else "not-authorized")
                return {"status": status, "source_causal_id": source, "handoff_complete": handoff, "deliveries": deliveries}
            except Exception:
                return {"status": "not-authorized", "source_causal_id": source, "handoff_complete": False, "deliveries": deliveries}

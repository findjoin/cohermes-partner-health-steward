"""Pinned Hermes ingress which consults the health Core before reading text.

Imported lazily by the release registry factory.  The actual Hermes Base is
required: there is no compatibility stub or native Weixin fallback here.
"""

from __future__ import annotations

import asyncio
import contextvars
import copy
import uuid
from dataclasses import replace
from datetime import datetime, timezone

from gateway.config import Platform
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, SendResult

from .admission import AdmissionPolicy, RawWeixinMessage, validate_opaque_text
from .host_contract import _CorePortClient
from .initialization import (
    InitializationDisclosure, InitializationProjection, OwnerConsentEvidence,
    OwnerInitialization, stable_digest,
)


_ORDINARY_SEND = contextvars.ContextVar("health_weixin_ordinary_send", default=None)
_DIRECTIVE_FIELDS = {
    "source_causal_id", "native_cursor", "business_transition_id", "authority_generation",
}


class _EntryUnavailable(ValueError):
    """A fixed, body-free failure at the host/Core boundary."""


def _text(value, *, optional=False):
    if optional and value is None:
        return None
    if type(value) is not str or not value or len(value.encode("utf-8")) > 16384:
        raise _EntryUnavailable("health-entry-invalid-metadata")
    return value


class LiveHealthWeixinAdapter(BasePlatformAdapter):
    """One sequential poller, with no health Session or transport retry loop."""

    SUPPORTS_MESSAGE_EDITING = False
    splits_long_messages = False

    def __init__(self, config, *, core_port=None, ingress_transport=None, delivery_transport=None):
        extra = getattr(config, "extra", None)
        if type(extra) is not dict or "admission_policy" not in extra:
            raise _EntryUnavailable("health-entry-admission-required")
        self._policy = AdmissionPolicy.from_storage(extra["admission_policy"])
        super().__init__(config, Platform("health_weixin"))
        self._core_port = core_port if core_port is not None else extra.get("core_port")
        if self._core_port is None:
            endpoint = extra.get("core_port_endpoint")
            if type(endpoint) is not dict or endpoint.get("transport") != "af-unix":
                raise _EntryUnavailable("health-entry-private-core-required")
            self._core_port = _CorePortClient(endpoint)
        if not callable(getattr(self._core_port, "request", None)):
            raise _EntryUnavailable("health-entry-core-required")
        self._ingress = ingress_transport if ingress_transport is not None else extra.get("ingress_transport")
        self._delivery = delivery_transport if delivery_transport is not None else extra.get("delivery_transport")
        self._template = None
        if "initialization_template" in extra:
            self._template = OwnerInitialization.from_storage(extra["initialization_template"])
            if self._template.owner_consent or self._template.first_hop_route_consent:
                raise _EntryUnavailable("health-entry-template-cannot-consent")
        self._cursor = ""
        self._poll_task = None
        self._poll_lock = asyncio.Lock()
        self._rpc_lock = asyncio.Lock()
        self._connected_ingress = False
        self._last_reason = "health-entry-not-connected"

    async def _rpc(self, kind, payload):
        async with self._rpc_lock:
            if not self._running:
                raise _EntryUnavailable("health-entry-stopped")
            identity = "health-entry-rpc:" + uuid.uuid4().hex
            response = await asyncio.to_thread(
                self._core_port.request, kind, payload, request_id=identity,
            )
            if (type(response) is not dict or set(response) != {
                    "protocol_version", "kind", "request_id", "status", "payload"}
                    or response["protocol_version"] != 1 or response["kind"] != kind
                    or response["request_id"] != identity or response["status"] != "accepted"
                    or type(response["payload"]) is not dict):
                raise _EntryUnavailable("health-entry-core-result-unconfirmed")
            return response["payload"]

    async def _read(self, projection, payload=None):
        return await self._rpc("managed-read", {
            "interface": "health-entry-v1", "projection": projection,
            "payload": {} if payload is None else payload,
        })

    async def _command(self, operation, payload=None):
        return await self._rpc("command", {
            "interface": "health-entry-v1", "operation": operation,
            "payload": {} if payload is None else payload,
        })

    async def connect(self, *, is_reconnect=False):
        del is_reconnect
        if self._running:
            return True
        try:
            for name in ("connect", "get_updates", "acknowledge_cursor", "disconnect"):
                if not callable(getattr(self._ingress, name, None)):
                    raise _EntryUnavailable("health-entry-ingress-unavailable")
            self._running = True
            probe = await self._rpc("command", {"operation": "health-runtime-probe"})
            if set(probe) == {"projection"} and type(probe["projection"]) is dict:
                probe = probe["projection"]
            runtime = await self._rpc("managed-read", {"projection": "health-runtime"})
            if (probe.get("state") != "healthy" or runtime.get("state") != "healthy"
                    or probe.get("health_writes_allowed") is not True
                    or runtime.get("health_writes_allowed") is not True):
                raise _EntryUnavailable("health-entry-core-unavailable")
            retained = await self._read("health-entry-native-cursor")
            if set(retained) != {"native_cursor"}:
                raise _EntryUnavailable("health-entry-cursor-unconfirmed")
            self._cursor = _text(retained["native_cursor"], optional=True) or ""
            if await self._ingress.connect() is not True:
                raise _EntryUnavailable("health-entry-ingress-unavailable")
            self._connected_ingress = True
            self._last_reason = None
            self._poll_task = asyncio.create_task(self._poll_loop())
            return True
        except Exception:
            self._running = False
            self._last_reason = "health-entry-unavailable"
            if self._connected_ingress:
                try:
                    await self._ingress.disconnect()
                except Exception:
                    pass
                self._connected_ingress = False
            return False

    async def disconnect(self):
        self._running = False
        task, self._poll_task = self._poll_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._connected_ingress:
            self._connected_ingress = False
            try:
                await self._ingress.disconnect()
            except Exception:
                self._last_reason = "health-entry-disconnect-unconfirmed"

    async def _poll_loop(self):
        try:
            while self._running:
                await self.poll_once()
                # Receiving the same unacknowledged batch is not permission to
                # repeat any model or delivery effect. Core/126 own that fact.
                if self._running:
                    await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._running = False
            self._last_reason = "health-entry-processing-unconfirmed"

    async def poll_once(self):
        async with self._poll_lock:
            if not self._running:
                return False
            batch = await self._ingress.get_updates(self._cursor)
            if not self._running:
                return False
            if (type(batch) is not dict or batch.get("ret") != 0
                    or batch.get("errcode", 0) != 0 or type(batch.get("msgs")) is not list):
                raise _EntryUnavailable("health-entry-poll-unconfirmed")
            cursor = _text(batch.get("get_updates_buf"))
            sources = []
            can_ack = True
            for index, native in enumerate(batch["msgs"]):
                if not self._running:
                    return False
                source, committed = await self._process(native, cursor, index)
                can_ack = can_ack and committed
                if source is not None:
                    sources.append(source)
            if not can_ack:
                return False
            for source in sources:
                result = await self._read("health-entry-cursor-directive", {"source_causal_id": source})
                directive = result.get("directive") if set(result) == {"directive"} else None
                if (type(directive) is not dict or set(directive) != _DIRECTIVE_FIELDS
                        or directive["source_causal_id"] != source or directive["native_cursor"] != cursor
                        or type(directive["authority_generation"]) is not int
                        or directive["authority_generation"] < 1):
                    return False
                _text(directive["business_transition_id"])
            if not self._running:
                return False
            try:
                await self._ingress.acknowledge_cursor(cursor)
            except Exception:
                for source in sources:
                    await self._command("native-cursor-result", {"source_causal_id": source, "status": "unknown"})
                return False
            for source in sources:
                reported = await self._command("native-cursor-result", {"source_causal_id": source, "status": "advanced"})
                response = reported.get("response")
                if type(response) is not dict or response.get("status") not in {"accepted", "replayed"}:
                    return False
            self._cursor = cursor
            return True

    def _headers(self, native, cursor, index):
        if not isinstance(native, dict):
            raise _EntryUnavailable("health-entry-invalid-native-header")
        sender = _text(native.get("from_user_id"))
        partner = _text(native.get("to_user_id"))
        message_id = _text(native.get("message_id"), optional=True)
        conversation = native.get("conversation_id", sender)
        grouped = any(native.get(key) for key in ("group_id", "group_chat_id", "chatroom_id"))
        native_chat_type = native.get("chat_type", "private")
        if native_chat_type not in {"private", "dm"}:
            grouped = True
        stamp = native.get("create_time_ms")
        if type(stamp) is not int or stamp < 0:
            raise _EntryUnavailable("health-entry-invalid-native-time")
        timestamp = datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()
        identity = {
            "channel": self._policy.channel, "partner": partner, "sender": sender,
            "conversation": conversation, "message_id": message_id,
            "protocol_timestamp": timestamp, "native_cursor": cursor,
        }
        if message_id is None:
            identity["batch_index"] = index
        causal = "health-weixin-source:" + stable_digest(identity).removeprefix("sha256:")
        headers = {
            "causal_id": causal, "channel": "weixin", "partner_id": partner,
            "sender_id": sender, "conversation_id": conversation,
            "chat_type": "group" if grouped else "private", "entrypoint": "health_weixin",
            "message_id": message_id, "protocol_timestamp": timestamp,
            "received_at": datetime.now(timezone.utc).isoformat(), "native_cursor": cursor,
        }
        raw = RawWeixinMessage(**headers, generation=1, requested_capability="health-init", body=None)
        if (native.get("msg_type") != 1 or self._policy.rejection_reason(raw) is not None):
            return None
        return headers

    @staticmethod
    def _body(native):
        items = native.get("item_list")
        if type(items) is not list or not items:
            raise _EntryUnavailable("health-entry-unsupported-native-body")
        parts = []
        for item in items:
            if type(item) is not dict or item.get("type") != 1:
                raise _EntryUnavailable("health-entry-unsupported-native-body")
            text_item = item.get("text_item")
            if type(text_item) is not dict:
                raise _EntryUnavailable("health-entry-unsupported-native-body")
            parts.append(_text(text_item.get("text")))
        body = "\n".join(parts)
        if len(body.encode("utf-8")) > 16384:
            raise _EntryUnavailable("health-entry-native-body-too-large")
        return body

    async def _bridge(self, value):
        send = getattr(self._delivery, "send_committed", None)
        if callable(send):
            # The bridge owns intent/grant acquisition, idempotency and unknown.
            # Its response is deliberately not interpreted as delivered/read.
            await send(copy.deepcopy(value))

    async def _process(self, native, cursor, index):
        try:
            headers = self._headers(native, cursor, index)
        except (ValueError, TypeError, OverflowError, OSError):
            return None, False
        if headers is None:
            return None, True  # Explicit header exclusion, with zero body reads.
        preflight = await self._read("health-entry-preflight", {"headers": headers})
        if (set(preflight) != {"allowed", "current_generation", "initialization_phase", "reason_code"}
                or preflight["allowed"] is not True
                or type(preflight["current_generation"]) is not int
                or preflight["current_generation"] < 1):
            return None, False
        try:
            body = self._body(native)
        except (ValueError, TypeError):
            return None, False
        words = body.strip().split()
        if words == ["/health-init"]:
            if self._template is None or preflight["initialization_phase"] == "enabled":
                return None, False
            workflow = "health-init-workflow:" + headers["causal_id"].split(":", 1)[1]
            callback = "health-init-consent:" + stable_digest({"workflow": workflow}).removeprefix("sha256:")
            initialization = replace(self._template, workflow_id=workflow, admission_causal_id=callback)
            disclosure = await self._command("initialization-disclosure", {"initialization": initialization.to_storage()})
            if set(disclosure) != {"disclosure"}:
                return None, False
            actual = InitializationDisclosure.from_storage(disclosure["disclosure"])
            if actual.skill_proof.workflow_id != workflow or actual.skill_proof.admission_causal_id != callback:
                return None, False
            await self._bridge({"kind": "initialization-disclosure", "workflow_id": workflow,
                                "disclosure": actual.to_storage()})
            return None, False
        initialization = None
        capability = "health-steward"
        if words and words[0] == "/health-init-confirm":
            if len(words) != 3:
                return None, False
            workflow, disclosure_id = words[1:]
            validate_opaque_text(workflow, "initialization workflow")
            retained = await self._read("health-entry-disclosure", {"workflow_id": workflow})
            if set(retained) != {"initialization", "disclosure"} or retained["initialization"] is None or retained["disclosure"] is None:
                return None, False
            pending = OwnerInitialization.from_storage(retained["initialization"])
            disclosure = InitializationDisclosure.from_storage(retained["disclosure"])
            if (pending.workflow_id != workflow or pending.owner_consent or pending.first_hop_route_consent
                    or disclosure.disclosure_id != disclosure_id
                    or disclosure.skill_proof.workflow_id != workflow
                    or disclosure.skill_proof.admission_causal_id != pending.admission_causal_id
                    or self._template is None
                    or replace(pending, workflow_id=self._template.workflow_id,
                               admission_causal_id=self._template.admission_causal_id) != self._template):
                return None, False
            initialization = replace(pending, owner_consent=True, first_hop_route_consent=True)
            evidence = OwnerConsentEvidence(
                workflow_id=workflow, admission_causal_id=pending.admission_causal_id,
                initialization_digest=initialization.digest, initialization=initialization,
                disclosure_version=disclosure.content.disclosure_version,
                disclosed_topics=disclosure.content.disclosed_topics, disclosure=disclosure,
                owner_confirmed=True, first_hop_route_confirmed=True,
            )
            headers["causal_id"] = pending.admission_causal_id
            body = evidence.to_message_body()
            capability = "health-init"
        message = {**headers, "generation": preflight["current_generation"],
                   "requested_capability": capability, "body": body}
        admitted = await self._command("receive-weixin", {"message": message})
        response = admitted.get("response") if set(admitted) == {"response"} else None
        if (type(response) is not dict or response.get("status") not in {"accepted", "replayed"}
                or response.get("causal_id") != headers["causal_id"]):
            return None, False
        if initialization is not None:
            for operation, payload in (
                ("initialization-consent", {"initialization": initialization.to_storage()}),
                ("initialization-commit", {}), ("initialization-finalize", {}),
            ):
                result = await self._command(operation, payload)
                business = result.get("response") if set(result) == {"response"} else None
                if type(business) is not dict or business.get("status") not in {"accepted", "replayed"}:
                    return None, False
            state = await self._read("health-entry-initialization")
            if set(state) != {"initialization"}:
                return None, False
            projection = InitializationProjection.from_storage(state["initialization"])
            if projection.phase != "enabled" or not projection.enabled:
                return None, False
        elif response.get("reason_code") == "ordinary-hermes-route":
            await self._ordinary(headers, body)
            return None, True
        else:
            meta = response.get("meta")
            turn = meta.get("turn_result") if type(meta) is dict else None
            if type(turn) is not dict:
                return None, False
            # Core can return the original business turn for a proved native
            # replay alias. The Response binds this delivery; the turn retains
            # its original source. 126 resolves that relation before sending.
            for name in ("source_causal_id", "record_id", "transition_id"):
                _text(turn.get(name))
            await self._bridge({"kind": "committed-turn", "source_causal_id": headers["causal_id"],
                                "turn_result": turn})
        return headers["causal_id"], True

    async def _ordinary(self, headers, body):
        handler = self._message_handler
        if not callable(handler):
            return
        source = self.build_source(chat_id=headers["conversation_id"], chat_type="dm",
                                   user_id=headers["sender_id"], message_id=headers["message_id"])
        event = MessageEvent(text=body, source=source, message_id=headers["message_id"],
                             raw_message={"message_id": headers["message_id"]})
        token = _ORDINARY_SEND.set((id(self), headers["conversation_id"]))
        try:
            await handler(event)
        finally:
            _ORDINARY_SEND.reset(token)

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        if self._running and _ORDINARY_SEND.get() == (id(self), chat_id):
            ordinary = getattr(self._delivery, "send_ordinary", None)
            if callable(ordinary):
                result = await ordinary(chat_id, content, reply_to=reply_to, metadata=metadata)
                if isinstance(result, SendResult):
                    return result
        return SendResult(success=False, error="health-controlled-delivery-required", retryable=False)

    async def get_chat_info(self, chat_id):
        """Describe the supplied route without fetching account or chat data."""
        chat_id = _text(chat_id)
        return {"name": chat_id, "type": "group" if chat_id.endswith("@chatroom") else "dm",
                "chat_id": chat_id}

    async def wake_current(self):
        if not self._running:
            return False
        try:
            result = await self._command("wake-current")
            response = result.get("response") if set(result) == {"response"} else None
            return type(response) is dict and response.get("status") in {"accepted", "replayed"}
        except Exception:
            self._running = False
            self._last_reason = "health-entry-core-unavailable"
            return False

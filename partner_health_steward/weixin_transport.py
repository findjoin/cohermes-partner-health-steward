"""Single-attempt pinned iLink transport; no business state or native retries."""
from __future__ import annotations

import asyncio
import copy
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .delivery import OwnerDeliverySendIntent, OwnerDeliveryTransportResult
from .initialization import stable_digest


def _text(value):
    if type(value) is not str or not value or len(value.encode("utf-8")) > 16384:
        raise ValueError("invalid Weixin transport binding")
    return value


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError("invalid Weixin transport authorization")
    return value


@dataclass(frozen=True)
class WeixinTransportBinding:
    account_id: str
    base_url: str

    def __post_init__(self):
        _text(self.account_id)
        value = _text(self.base_url)
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None
                or url.query or url.fragment or any(c in value for c in "\r\n\t")
                or value != urlunsplit((url.scheme, url.netloc.lower(), url.path.rstrip("/"), "", ""))):
            raise ValueError("invalid Weixin HTTPS origin")


class _BoundSession:
    def __init__(self, session, binding):
        self._session, self._binding = session, binding

    def post(self, url, **kwargs):
        from gateway.platforms.weixin import EP_GET_UPDATES, EP_SEND_MESSAGE
        if url not in {self._binding.base_url + "/" + EP_GET_UPDATES,
                       self._binding.base_url + "/" + EP_SEND_MESSAGE}:
            raise ValueError("Weixin endpoint binding mismatch")
        kwargs["allow_redirects"] = False
        return self._session.post(url, **kwargs)


def _session(factory):
    if factory is None:
        import aiohttp
        factory = aiohttp.ClientSession
    return factory(trust_env=False)


class PinnedWeixinIngressTransport:
    def __init__(self, binding, *, token, session_factory=None):
        if type(binding) is not WeixinTransportBinding:
            raise ValueError("invalid Weixin ingress binding")
        self._binding, self._token, self._factory = binding, _text(token), session_factory
        self._session, self._loop = None, None

    async def connect(self):
        if self._session is None:
            self._loop = asyncio.get_running_loop()
            self._session = _session(self._factory)
        return True

    async def get_updates(self, cursor):
        if self._session is None or self._loop is not asyncio.get_running_loop() or type(cursor) is not str:
            raise ValueError("Weixin ingress is unavailable")
        from gateway.platforms.weixin import _get_updates, LONG_POLL_TIMEOUT_MS
        try:
            return await _get_updates(_BoundSession(self._session, self._binding),
                base_url=self._binding.base_url, token=self._token,
                sync_buf=cursor, timeout_ms=LONG_POLL_TIMEOUT_MS)
        except Exception:
            raise ValueError("Weixin poll outcome unconfirmed") from None

    async def acknowledge_cursor(self, cursor):
        if type(cursor) is not str or self._session is None:
            raise ValueError("invalid Weixin cursor handoff")
        # iLink has no separate ACK endpoint. The caller supplies the Core-
        # authorized cursor on its next poll; no native sync file is written.

    async def disconnect(self):
        session, self._session = self._session, None
        if session is not None:
            await session.close()


class PinnedWeixinOwnerDeliveryAdapter:
    def __init__(self, binding, authorization, *, token, context_token_provider, session_factory=None):
        if type(binding) is not WeixinTransportBinding or not callable(context_token_provider):
            raise ValueError("invalid Weixin delivery binding")
        self._binding, self._token = binding, _text(token)
        self._context, self._factory = context_token_provider, session_factory
        self._authorization = copy.deepcopy(authorization)
        self._used, self._lock = False, threading.Lock()
        self._validated()

    def _validated(self):
        auth = _exact(self._authorization, {
            "purpose", "recipient_role", "account_id", "intent_id", "send_intent", "payload",
            "payload_digest", "route_id", "route_generation", "execution",
        })
        if auth["account_id"] != self._binding.account_id or type(auth["route_generation"]) is not int or auth["route_generation"] < 1:
            raise ValueError("Weixin account or route mismatch")
        execution = _exact(auth["execution"], {"lease_id", "effect_id", "intent_digest", "generation", "writer_fence"})
        for field in ("lease_id", "effect_id", "intent_digest", "writer_fence"):
            _text(execution[field])
        if type(execution["generation"]) is not int or execution["generation"] < 1:
            raise ValueError("invalid Weixin execution generation")
        if stable_digest(auth["payload"]) != auth["payload_digest"]:
            raise ValueError("Weixin payload digest mismatch")
        if auth["recipient_role"] == "owner" and auth["purpose"] in {"owner-reply", "initialization-disclosure", "owner-outbox"}:
            intent = OwnerDeliverySendIntent.from_wire(auth["send_intent"])
            payload = _exact(auth["payload"], {"text"})
            if (intent.intent_id != auth["intent_id"] or intent.destination.partner_id != self._binding.account_id
                    or intent.destination.route_id != auth["route_id"]):
                raise ValueError("Weixin owner destination mismatch")
            recipient, text = intent.destination.owner_sender_id, _text(payload["text"])
        elif auth["recipient_role"] == "support-contact" and auth["purpose"] in {"contact-alert", "contact-correction"}:
            wire = _exact(auth["send_intent"], {"destination", "contact_alert"})
            destination = _exact(wire["destination"], {
                "contact_id", "identity_label", "method_kind", "method_value", "route_id", "route_generation"})
            payload = _exact(auth["payload"], {"contact_alert"})
            alert = _exact(payload["contact_alert"], {"owner_recognizable_name", "event_time", "fixed_urgent_help_request"})
            if (destination["method_kind"] != "weixin_user" or destination["route_id"] != auth["route_id"]
                    or destination["route_generation"] != auth["route_generation"] or wire["contact_alert"] != alert):
                raise ValueError("Weixin contact destination mismatch")
            recipient = _text(destination["method_value"])
            text = "\n".join(_text(alert[name]) for name in ("owner_recognizable_name", "event_time", "fixed_urgent_help_request"))
        else:
            raise ValueError("Weixin delivery purpose denied")
        if len(text) > 2000:
            raise ValueError("Weixin authorized text exceeds single-send limit")
        client = "health-" + stable_digest({
            "account": self._binding.account_id, "intent_id": auth["intent_id"],
            "execution": execution, "route_id": auth["route_id"],
            "route_generation": auth["route_generation"], "role": auth["recipient_role"],
            "idempotency_key": auth["send_intent"].get("idempotency_key"),
        }).removeprefix("sha256:")
        return recipient, text, client

    def send(self, intent, /):
        if type(intent) is not dict or intent != self._authorization["send_intent"]:
            raise ValueError("Weixin exact send intent required")
        recipient, text, client = self._validated()
        with self._lock:
            if self._used:
                raise ValueError("Weixin attempt already consumed")
            self._used = True
        status = "unknown"
        try:
            context = _text(self._context(recipient))
            raw = asyncio.run(self._send_once(recipient, text, client, context))
            if type(raw) is dict:
                values = [raw[key] for key in ("ret", "errcode") if key in raw]
                if any(type(v) is int and v != 0 for v in values):
                    status = "rejected"
                elif values and all(type(v) is int and v == 0 for v in values):
                    status = "accepted"
        except Exception:
            pass
        identity = stable_digest({"client_id": client, "status": status}).removeprefix("sha256:")
        return OwnerDeliveryTransportResult(status, "weixin-result:" + identity,
                                             "weixin-observation:" + identity).to_wire()

    async def _send_once(self, recipient, text, client, context):
        from gateway.platforms.weixin import _send_message
        session = _session(self._factory)
        try:
            return await _send_message(_BoundSession(session, self._binding),
                base_url=self._binding.base_url, token=self._token, to=recipient,
                text=text, context_token=context, client_id=client)
        finally:
            await session.close()

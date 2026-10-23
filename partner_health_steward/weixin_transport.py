"""Single-attempt pinned iLink transport; no business state or native retries."""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import re
import secrets
import threading
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit, urlunsplit

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


_EXPORT_API = "https://ilinkai.weixin.qq.com"
_EXPORT_CDN = "https://novac2c.cdn.weixin.qq.com/c2c"
_MAX_EXPORT_BYTES = 8388608


def _export_upload_url(value, filekey):
    from gateway.platforms.weixin import _cdn_upload_url
    value = _text(value)
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "novac2c.cdn.weixin.qq.com"
            or parsed.path != "/c2c/upload" or parsed.fragment
            or parsed.username is not None or parsed.password is not None or parsed.port is not None):
        raise ValueError("export CDN binding mismatch")
    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    if (len(pairs) != 2 or {key for key, _ in pairs} != {"encrypted_query_param", "filekey"}
            or any(not item for _, item in pairs)):
        raise ValueError("invalid export upload ticket")
    fields = dict(pairs)
    if fields["filekey"] != filekey or _cdn_upload_url(_EXPORT_CDN, fields["encrypted_query_param"], filekey) != value:
        raise ValueError("export upload ticket changed")
    return value


class _ExportBoundSession:
    def __init__(self, session, filekey):
        self._session, self._filekey = session, filekey

    def post(self, url, **kwargs):
        from gateway.platforms.weixin import EP_GET_UPLOAD_URL, EP_SEND_MESSAGE
        if url not in {_EXPORT_API + "/" + EP_GET_UPLOAD_URL, _EXPORT_API + "/" + EP_SEND_MESSAGE}:
            _export_upload_url(url, self._filekey)
            if any(key.lower() == "authorization" for key in kwargs.get("headers", {})):
                raise ValueError("export CDN credentials denied")
        kwargs["allow_redirects"] = False
        return self._session.post(url, **kwargs)


class PinnedWeixinExportArtifactAdapter:
    """One in-memory pinned file attempt for one exact Core export grant."""

    def __init__(self, binding, authorization, artifact_bytes, *, token, context_token_provider, session_factory=None):
        if (type(binding) is not WeixinTransportBinding or binding.base_url != _EXPORT_API
                or not callable(context_token_provider) or type(artifact_bytes) is not bytes):
            raise ValueError("invalid export transport binding")
        self._binding, self._token = binding, _text(token)
        self._authorization, self._artifact = copy.deepcopy(authorization), artifact_bytes
        self._context, self._factory = context_token_provider, session_factory
        self._used, self._lock = False, threading.Lock()
        self._validated()

    def _validated(self):
        auth = _exact(self._authorization, {
            "purpose", "recipient_role", "account_id", "intent_id", "send_intent", "payload",
            "payload_digest", "route_id", "route_generation", "execution",
        })
        if (auth["purpose"] != "export-artifact" or auth["recipient_role"] != "owner"
                or auth["account_id"] != self._binding.account_id
                or type(auth["route_generation"]) is not int or auth["route_generation"] < 1):
            raise ValueError("export owner route mismatch")
        execution = _exact(auth["execution"], {"lease_id", "effect_id", "intent_digest", "generation", "writer_fence"})
        for field in ("lease_id", "effect_id", "intent_digest", "writer_fence"):
            _text(execution[field])
        if type(execution["generation"]) is not int or execution["generation"] < 1:
            raise ValueError("invalid export execution generation")
        payload = _exact(auth["payload"], {"artifact_ref", "filename", "size_bytes", "digest"})
        _text(payload["artifact_ref"])
        digest = payload["digest"]
        if (type(digest) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
                or payload["filename"] != "health-export-" + digest[7:] + ".json"
                or type(payload["size_bytes"]) is not int or not 1 <= payload["size_bytes"] <= _MAX_EXPORT_BYTES
                or type(self._artifact) is not bytes or len(self._artifact) != payload["size_bytes"]
                or "sha256:" + hashlib.sha256(self._artifact).hexdigest() != digest
                or stable_digest(payload) != auth["payload_digest"]):
            raise ValueError("export artifact metadata mismatch")
        intent = OwnerDeliverySendIntent.from_wire(auth["send_intent"])
        if (intent.intent_id != auth["intent_id"] or intent.destination.partner_id != self._binding.account_id
                or intent.destination.route_id != auth["route_id"] or intent.payload_digest != auth["payload_digest"]):
            raise ValueError("export exact destination mismatch")
        client = "health-export-" + stable_digest({
            "account": self._binding.account_id, "intent_id": intent.intent_id,
            "attempt_ref": intent.attempt_ref, "execution": execution,
            "route_id": auth["route_id"], "route_generation": auth["route_generation"],
            "idempotency_key": intent.idempotency_key,
        }).removeprefix("sha256:")
        return intent.destination.owner_sender_id, payload["filename"], client

    def send(self, exact_send_intent, /):
        if type(exact_send_intent) is not dict or exact_send_intent != self._authorization["send_intent"]:
            raise ValueError("export exact send intent required")
        recipient, filename, client = self._validated()
        with self._lock:
            if self._used:
                raise ValueError("export attempt already consumed")
            self._used = True
        status = "unknown"
        try:
            context = _text(self._context(recipient))
            raw = asyncio.run(self._send_once(recipient, filename, client, context))
            if type(raw) is dict:
                values = [raw[key] for key in ("ret", "errcode") if key in raw]
                if any(type(value) is int and value != 0 for value in values):
                    status = "rejected"
                elif values and all(type(value) is int and value == 0 for value in values):
                    status = "accepted"
        except Exception:
            pass
        finally:
            self._artifact = None
        identity = stable_digest({"client_id": client, "status": status}).removeprefix("sha256:")
        return OwnerDeliveryTransportResult(status, "weixin-export-result:" + identity,
                                             "weixin-export-observation:" + identity).to_wire()

    async def _send_once(self, recipient, filename, client, context):
        from gateway.platforms.weixin import (
            API_TIMEOUT_MS, EP_SEND_MESSAGE, MEDIA_FILE, ITEM_FILE,
            _aes128_ecb_encrypt, _aes_padded_size, _api_post, _cdn_upload_url,
            _get_upload_url, _upload_ciphertext,
        )
        plaintext = self._artifact
        filekey, key = secrets.token_hex(16), secrets.token_bytes(16)
        session = _session(self._factory)
        bound = _ExportBoundSession(session, filekey)
        try:
            ticket = await _get_upload_url(bound, base_url=_EXPORT_API, token=self._token,
                to_user_id=recipient, media_type=MEDIA_FILE, filekey=filekey,
                rawsize=len(plaintext), rawfilemd5=hashlib.md5(plaintext).hexdigest(),
                filesize=_aes_padded_size(len(plaintext)), aeskey_hex=key.hex())
            if type(ticket) is not dict:
                raise ValueError("export upload ticket unconfirmed")
            codes = [ticket[name] for name in ("ret", "errcode") if name in ticket]
            if any(type(code) is int and code != 0 for code in codes):
                return ticket
            if any(type(code) is not int for code in codes):
                raise ValueError("export upload ticket unconfirmed")
            if ticket.get("upload_param"):
                upload_url = _cdn_upload_url(_EXPORT_CDN, _text(ticket["upload_param"]), filekey)
            else:
                upload_url = _text(ticket.get("upload_full_url"))
            upload_url = _export_upload_url(upload_url, filekey)
            ciphertext = _aes128_ecb_encrypt(plaintext, key)
            if len(ciphertext) != _aes_padded_size(len(plaintext)) or len(ciphertext) > _MAX_EXPORT_BYTES + 16:
                raise ValueError("export ciphertext size mismatch")
            encrypted = _text(await _upload_ciphertext(bound, ciphertext=ciphertext, upload_url=upload_url))
            return await _api_post(bound, base_url=_EXPORT_API, endpoint=EP_SEND_MESSAGE,
                payload={"msg": {
                    "from_user_id": "", "to_user_id": recipient, "client_id": client,
                    "message_type": 2, "message_state": 2,
                    "item_list": [{"type": ITEM_FILE, "file_item": {
                        "media": {"encrypt_query_param": encrypted,
                                  "aes_key": base64.b64encode(key.hex().encode("ascii")).decode("ascii"),
                                  "encrypt_type": 1},
                        "file_name": filename, "len": str(len(plaintext)),
                    }}], "context_token": context,
                }}, token=self._token, timeout_ms=API_TIMEOUT_MS)
        finally:
            await session.close()


class PinnedWeixinConversationSender:
    """The admitted ordinary reply and two fixed technical messages only."""

    def __init__(self, binding, policy, *, token, context_token_provider,
                 ordinary_guard, technical_channel=None, session_factory=None):
        from .admission import AdmissionPolicy
        if (type(binding) is not WeixinTransportBinding or type(policy) is not AdmissionPolicy
                or binding.account_id != policy.partner_id
                or not callable(context_token_provider) or not callable(ordinary_guard)):
            raise ValueError("invalid ordinary Weixin route")
        self._binding, self._policy, self._token = binding, policy, _text(token)
        self._context, self._guard = context_token_provider, ordinary_guard
        self._technical, self._factory = technical_channel, session_factory

    async def _send_once(self, text, client):
        from gateway.platforms.weixin import _send_message
        context = self._context(self._policy.owner_sender_id)
        if context is not None:
            context = _text(context)
        session = _session(self._factory)
        try:
            return await _send_message(_BoundSession(session, self._binding),
                base_url=self._binding.base_url, token=self._token,
                to=self._policy.owner_sender_id, text=text, context_token=context, client_id=client)
        finally:
            await session.close()

    async def _result(self, text, client):
        status = "unknown"
        try:
            raw = await self._send_once(text, client)
            if type(raw) is dict:
                codes = [raw[key] for key in ("ret", "errcode") if key in raw]
                if codes and all(type(value) is int for value in codes):
                    status = "accepted" if all(value == 0 for value in codes) else "rejected"
        except Exception:
            pass
        digest = stable_digest({"client_id": client, "status": status})[7:]
        return OwnerDeliveryTransportResult(status, "weixin-result:" + digest,
                                            "weixin-observation:" + digest).to_wire()

    async def send_ordinary(self, chat_id, content, *, reply_to=None, metadata=None):
        del reply_to, metadata
        if (chat_id != self._policy.conversation_id or not self._guard(chat_id)
                or type(content) is not str or not content or len(content) > 2000):
            raise ValueError("ordinary Weixin conversation context required")
        # One ordinary reply attempt. Unknown never receives a transport retry.
        return await self._result(content, "ordinary-" + secrets.token_hex(16))

    async def send_technical(self, attempt):
        from .ticket128_technical import TechnicalAcceptanceChannel
        if (type(self._technical) is not TechnicalAcceptanceChannel or type(attempt) is not dict
                or self._technical.attempt(attempt.get("execution_key")) != attempt
                or attempt.get("attempted_at_utc") is None or attempt.get("send_result") is not None):
            raise ValueError("current technical Weixin attempt required")
        challenge = attempt["challenge"]
        if re.fullmatch(r"[0-9a-f]{32,64}", challenge) is None:
            raise ValueError("invalid technical challenge")
        if attempt["gate_id"] == "119-G11":
            text = "连接测试：请独立回复以下完整指令，确认已看到并操作本次连接测试。\n`连接测试 " + challenge + "`"
        elif attempt["gate_id"] == "128-ND12":
            text = ("本次仅验收非诊断范围，诊断未启用。请在实际体验后独立回复以下完整反馈；"
                    "拒绝、缺项或其他意见不会形成通过。\n`验收反馈 " + challenge + " 有用 清楚 可信`")
        else:
            raise ValueError("technical Weixin gate denied")
        client = "technical-" + stable_digest({"execution_key": attempt["execution_key"],
                                               "challenge": challenge, "gate_id": attempt["gate_id"]})[7:]
        return await self._result(text, client)

"""Protocol definitions for health-sidecar requests."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Mapping

from .recording import (
    ACTION_RECORDING_FEEDBACK_BACKFILLED,
    ACTION_RECORDING_FEEDBACK_NOT_RECORDED,
)


ACTION_PING = "health.ping"
ACTION_STATUS_GET = "health.status.get"
ACTION_STATUS_SET = "health.status.set"
ACTION_AUDIT_READ = "health.audit.read"
ACTION_DELIVERY_AUDIT_APPEND = "health.delivery.audit.append_once"
ACTION_PROFILE_OWNER_BIND = "health.profile.owner.bind"
ACTION_PROFILE_OWNER_TRANSFER = "health.profile.owner.transfer"
ACTION_PROFILE_OWNER_RECOVER = "health.profile.owner.recover"
ACTION_PROFILE_MESSAGE_STAGE = "health.profile.message.stage"
ACTION_PROFILE_RECENT_MESSAGE = "health.profile.message.recent"
ACTION_PROFILE_MESSAGE_ADMISSION_STATUS = "health.profile.message.admission_status"
ACTION_PROFILE_CANDIDATE = "health.profile.candidate"
ACTION_RECORDING_STATUS = "health.recording.status"
ACTION_RECORDING_ATTEMPT_BEGIN = "health.recording.attempt.begin"
ACTION_RECORDING_ATTEMPT_END = "health.recording.attempt.end"
ACTION_RECORDING_ENABLE = "health.recording.enable"
ACTION_RECORDING_STOP = "health.recording.stop"
ACTION_RECORDING_RESUME = "health.recording.resume"
ACTION_PROFILE_CONSENTED_ADMIT = "health.profile.message.admit"
ACTION_PROFILE_READ = "health.profile.read"
ACTION_PROFILE_DELETE_REQUEST = "health.profile.delete.request"
ACTION_PROFILE_DELETE_CONFIRM = "health.profile.delete.confirm"
ACTION_PROFILE_DELETION_STATUS = "health.profile.deletion.status"
ACTION_BACKUPS_PURGE = "health.maintenance.backups.purge"
ACTION_ACCESS_GRANT = "health.access.grant"
ACTION_ACCESS_REVOKE = "health.access.revoke"
ACTION_ACCESS_READ = "health.access.read"
ACTION_ACCESS_ANALYZE = "health.access.analyze"
ACTION_PROFILE_EXPORT = "health.profile.export"
ACTION_SOURCE_QUERY = "health.source.query"
ACTION_SOURCE_SCAN = "health.source.scan"
ACTION_HEALTH_TURN_CONTEXT_READ = "health.turn.context.read"
ACTION_DAILY_REVIEW_SNAPSHOT = "health.daily_review.snapshot"
ACTION_DAILY_REVIEW = "health.daily_review.run"
ACTION_DAILY_REVIEW_EXECUTE = "health.daily_review.execute"
ACTION_DISPATCH_DUE_TASKS = "health.dispatch.run"
ACTION_PROACTIVE_PAUSE = "health.proactive.pause"
ACTION_PROACTIVE_RESUME = "health.proactive.resume"

STREAM_RESPONSE_MAGIC = b"HSS1"
STREAM_RESPONSE_HEADER_BYTES = 44

HEALTH_TURN_CONTEXT_EVIDENCE_KIND = "health_related"

SUPPORTED_ACTIONS = {
    ACTION_PING,
    ACTION_STATUS_GET,
    ACTION_STATUS_SET,
    ACTION_AUDIT_READ,
    ACTION_DELIVERY_AUDIT_APPEND,
    ACTION_PROFILE_OWNER_BIND,
    ACTION_PROFILE_OWNER_TRANSFER,
    ACTION_PROFILE_OWNER_RECOVER,
    ACTION_PROFILE_MESSAGE_STAGE,
    ACTION_PROFILE_RECENT_MESSAGE,
    ACTION_PROFILE_MESSAGE_ADMISSION_STATUS,
    ACTION_PROFILE_CANDIDATE,
    ACTION_RECORDING_STATUS,
    ACTION_RECORDING_ATTEMPT_BEGIN,
    ACTION_RECORDING_ATTEMPT_END,
    ACTION_RECORDING_ENABLE,
    ACTION_RECORDING_STOP,
    ACTION_RECORDING_RESUME,
    ACTION_RECORDING_FEEDBACK_BACKFILLED,
    ACTION_RECORDING_FEEDBACK_NOT_RECORDED,
    ACTION_PROFILE_CONSENTED_ADMIT,
    ACTION_PROFILE_READ,
    ACTION_PROFILE_DELETE_REQUEST,
    ACTION_PROFILE_DELETE_CONFIRM,
    ACTION_PROFILE_DELETION_STATUS,
    ACTION_BACKUPS_PURGE,
    ACTION_ACCESS_GRANT,
    ACTION_ACCESS_REVOKE,
    ACTION_ACCESS_READ,
    ACTION_ACCESS_ANALYZE,
    ACTION_PROFILE_EXPORT,
    ACTION_SOURCE_QUERY,
    ACTION_SOURCE_SCAN,
    ACTION_HEALTH_TURN_CONTEXT_READ,
    ACTION_DAILY_REVIEW_SNAPSHOT,
    ACTION_DAILY_REVIEW,
    ACTION_DAILY_REVIEW_EXECUTE,
    ACTION_DISPATCH_DUE_TASKS,
    ACTION_PROACTIVE_PAUSE,
    ACTION_PROACTIVE_RESUME,
}


REQUIRED_FIELDS = {
    ACTION_DELIVERY_AUDIT_APPEND: {"event_id", "event", "details"},
    ACTION_STATUS_GET: {"subject"},
    ACTION_STATUS_SET: {"subject", "status"},
    ACTION_PROFILE_OWNER_BIND: {"subject", "owner_sender_id", "verification_token"},
    ACTION_PROFILE_OWNER_TRANSFER: {
        "subject",
        "old_owner_sender_id",
        "new_owner_sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_PROFILE_OWNER_RECOVER: {
        "subject",
        "new_owner_sender_id",
        "recovery_code",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_PROFILE_MESSAGE_STAGE: {
        "subject",
        "sender_id",
        "message_id",
        "message_utc",
        "message_text",
        "evidence_kind",
        "verification_token",
    },
    ACTION_PROFILE_RECENT_MESSAGE: {
        "subject",
        "sender_id",
        "message_id",
        "message_utc",
        "attempt_utc",
        "message_text",
        "evidence_kind",
        "channel",
        "profile_name",
        "verification_token",
    },
    ACTION_PROFILE_MESSAGE_ADMISSION_STATUS: {
        "subject",
        "sender_id",
        "message_id",
    },
    ACTION_PROFILE_CANDIDATE: {"subject", "sender_id", "candidate"},
    ACTION_RECORDING_STATUS: {"subject", "sender_id"},
    ACTION_RECORDING_ATTEMPT_BEGIN: {"subject", "sender_id"},
    ACTION_RECORDING_ATTEMPT_END: {"lease_id"},
    ACTION_RECORDING_ENABLE: {
        "subject",
        "owner_sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_RECORDING_STOP: {
        "subject",
        "owner_sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_RECORDING_RESUME: {
        "subject",
        "owner_sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_RECORDING_FEEDBACK_BACKFILLED: {
        "subject",
        "owner_sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_RECORDING_FEEDBACK_NOT_RECORDED: {
        "subject",
        "owner_sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_PROFILE_CONSENTED_ADMIT: {
        "subject",
        "sender_id",
        "message_id",
        "message_utc",
        "attempt_utc",
        "message_text",
        "evidence_kind",
        "channel",
        "profile_name",
        "verification_token",
        "candidate",
    },
    ACTION_PROFILE_READ: {
        "subject",
        "sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_PROFILE_DELETE_REQUEST: {
        "subject",
        "sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_PROFILE_DELETE_CONFIRM: {
        "subject",
        "sender_id",
        "request_message_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_PROFILE_DELETION_STATUS: {
        "subject",
        "sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_BACKUPS_PURGE: set(),
    ACTION_ACCESS_GRANT: {
        "subject",
        "owner_sender_id",
        "viewer_sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_ACCESS_REVOKE: {
        "subject",
        "owner_sender_id",
        "viewer_sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_ACCESS_READ: {
        "subject",
        "sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_ACCESS_ANALYZE: {
        "subject",
        "sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_PROFILE_EXPORT: {
        "subject",
        "sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_SOURCE_QUERY: {"query"},
    ACTION_SOURCE_SCAN: {"candidates"},
    ACTION_HEALTH_TURN_CONTEXT_READ: {
        "subject",
        "sender_id",
        "message_id",
        "message_utc",
        "message_text",
        "channel",
        "profile_name",
        "attempt_utc",
        "verification_token",
    },
    ACTION_DAILY_REVIEW_SNAPSHOT: {"subject", "review_utc", "timezone"},
    ACTION_DAILY_REVIEW: {"subject", "review_utc", "timezone", "plan"},
    ACTION_DAILY_REVIEW_EXECUTE: {
        "subject",
        "review_utc",
        "timezone",
        "job_authorization",
    },
    ACTION_DISPATCH_DUE_TASKS: {"subject", "now_utc", "job_authorization"},
    ACTION_PROACTIVE_PAUSE: {
        "subject",
        "owner_sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
    ACTION_PROACTIVE_RESUME: {
        "subject",
        "owner_sender_id",
        "receipt_message_id",
        "receipt_utc",
        "verification_token",
    },
}


class SidecarProtocolError(ValueError):
    """Raised when a request cannot be parsed or fails validation."""


@dataclass(frozen=True)
class SidecarRequest:
    req_id: str | None
    action: str
    payload: Dict[str, Any]


def parse_request(raw: bytes) -> SidecarRequest:
    """Parse and validate one framed JSON request."""

    if not raw:
        raise SidecarProtocolError("empty-payload")

    try:
        loaded = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise SidecarProtocolError("invalid-json") from exc

    if not isinstance(loaded, dict):
        raise SidecarProtocolError("request-must-be-object")

    action = str(loaded.get("action", "")).strip()
    if action not in SUPPORTED_ACTIONS:
        raise SidecarProtocolError("unsupported-action")

    payload = loaded.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise SidecarProtocolError("payload-must-be-object")

    required = REQUIRED_FIELDS.get(action, set())
    missing = sorted(required.difference(payload))
    if missing:
        raise SidecarProtocolError(f"missing-payload-fields:{','.join(missing)}")

    if action in (
        ACTION_STATUS_GET,
        ACTION_STATUS_SET,
        ACTION_PROFILE_OWNER_BIND,
        ACTION_PROFILE_OWNER_TRANSFER,
        ACTION_PROFILE_OWNER_RECOVER,
        ACTION_PROFILE_MESSAGE_STAGE,
        ACTION_PROFILE_RECENT_MESSAGE,
        ACTION_PROFILE_CANDIDATE,
        ACTION_RECORDING_STATUS,
        ACTION_RECORDING_ENABLE,
        ACTION_RECORDING_STOP,
        ACTION_RECORDING_RESUME,
        ACTION_RECORDING_FEEDBACK_BACKFILLED,
        ACTION_RECORDING_FEEDBACK_NOT_RECORDED,
        ACTION_PROFILE_CONSENTED_ADMIT,
        ACTION_PROFILE_READ,
        ACTION_PROFILE_DELETE_REQUEST,
        ACTION_PROFILE_DELETE_CONFIRM,
        ACTION_PROFILE_DELETION_STATUS,
        ACTION_ACCESS_GRANT,
        ACTION_ACCESS_REVOKE,
        ACTION_ACCESS_READ,
        ACTION_ACCESS_ANALYZE,
        ACTION_PROFILE_EXPORT,
        ACTION_HEALTH_TURN_CONTEXT_READ,
        ACTION_DAILY_REVIEW_SNAPSHOT,
        ACTION_DAILY_REVIEW,
        ACTION_DAILY_REVIEW_EXECUTE,
        ACTION_DISPATCH_DUE_TASKS,
        ACTION_PROACTIVE_PAUSE,
        ACTION_PROACTIVE_RESUME,
    ):
        subject = payload.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            raise SidecarProtocolError("invalid-subject")

    if action == ACTION_STATUS_SET:
        status = payload.get("status")
        if not isinstance(status, Mapping):
            raise SidecarProtocolError("status-must-be-object")
        if len(status) == 0:
            raise SidecarProtocolError("status-empty")

    if action == ACTION_DELIVERY_AUDIT_APPEND:
        if set(payload) != REQUIRED_FIELDS[ACTION_DELIVERY_AUDIT_APPEND]:
            raise SidecarProtocolError("delivery-audit-fields-unsupported")
        event_id = payload.get("event_id")
        event = payload.get("event")
        details = payload.get("details")
        allowed_events = {
            "weixin_delivery_sent": "sent",
            "weixin_delivery_uncertain": "uncertain",
            "weixin_delivery_rejected": "rejected",
        }
        if event not in allowed_events or not isinstance(details, Mapping):
            raise SidecarProtocolError("invalid-delivery-audit")
        required_detail_fields = {
            "actor_role",
            "action",
            "object_id",
            "recipient_id",
            "result",
            "reason",
        }
        if set(details) not in {
            required_detail_fields,
            required_detail_fields | {"subject"},
        }:
            raise SidecarProtocolError("delivery-audit-content-forbidden")
        object_id = details.get("object_id")
        if (
            not isinstance(event_id, str)
            or not isinstance(object_id, str)
            or not object_id.startswith("hermes-health-")
            or event_id != f"{event}:{object_id}"
            or details.get("actor_role") != "weixin-delivery-adapter"
            or details.get("result") != allowed_events[event]
            or details.get("action")
            not in {
                "weixin.send_once",
                "weixin.send_attachment_once",
                "weixin.send_text_parts_once",
                "weixin.delivery.recover",
            }
        ):
            raise SidecarProtocolError("invalid-delivery-audit")
        for field in ("recipient_id", "reason", "subject"):
            if field not in details:
                continue
            value = details.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise SidecarProtocolError("invalid-delivery-audit")

    if action == ACTION_PROFILE_OWNER_BIND:
        owner_sender_id = payload.get("owner_sender_id")
        if not isinstance(owner_sender_id, str) or not owner_sender_id.strip():
            raise SidecarProtocolError("invalid-owner-sender")
        token = payload.get("verification_token")
        if not isinstance(token, str) or not token.strip():
            raise SidecarProtocolError("invalid-verification-token")

    if action == ACTION_PROFILE_OWNER_TRANSFER:
        for field, code in (
            ("old_owner_sender_id", "invalid-old-owner-sender"),
            ("new_owner_sender_id", "invalid-new-owner-sender"),
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise SidecarProtocolError(code)
        _validate_access_receipt_fields(payload)

    if action == ACTION_PROFILE_OWNER_RECOVER:
        new_owner_sender_id = payload.get("new_owner_sender_id")
        recovery_code = payload.get("recovery_code")
        if not isinstance(new_owner_sender_id, str) or not new_owner_sender_id.strip():
            raise SidecarProtocolError("invalid-new-owner-sender")
        if (
            not isinstance(recovery_code, str)
            or not 43 <= len(recovery_code.strip()) <= 128
        ):
            raise SidecarProtocolError("invalid-recovery-code")
        _validate_access_receipt_fields(payload)

    if action == ACTION_PROFILE_MESSAGE_STAGE:
        sender_id = payload.get("sender_id")
        if not isinstance(sender_id, str) or not sender_id.strip():
            raise SidecarProtocolError("invalid-sender")
        for field in (
            "message_id",
            "message_utc",
            "message_text",
            "evidence_kind",
            "verification_token",
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise SidecarProtocolError(f"invalid-{field}")

    if action == ACTION_PROFILE_RECENT_MESSAGE:
        sender_id = payload.get("sender_id")
        if not isinstance(sender_id, str) or not sender_id.strip():
            raise SidecarProtocolError("invalid-sender")
        for field in (
            "message_id",
            "message_utc",
            "attempt_utc",
            "message_text",
            "evidence_kind",
            "channel",
            "profile_name",
            "verification_token",
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise SidecarProtocolError(f"invalid-{field}")

    if action == ACTION_PROFILE_CANDIDATE:
        sender_id = payload.get("sender_id")
        if not isinstance(sender_id, str) or not sender_id.strip():
            raise SidecarProtocolError("invalid-sender")
        if not isinstance(payload.get("candidate"), Mapping):
            raise SidecarProtocolError("candidate-must-be-object")

    if action == ACTION_RECORDING_STATUS:
        sender_id = payload.get("sender_id")
        if not isinstance(sender_id, str) or not sender_id.strip():
            raise SidecarProtocolError("invalid-sender")

    if action == ACTION_RECORDING_ENABLE:
        owner_sender_id = payload.get("owner_sender_id")
        if not isinstance(owner_sender_id, str) or not owner_sender_id.strip():
            raise SidecarProtocolError("invalid-owner-sender")
        _validate_access_receipt_fields(payload)

    if action in (
        ACTION_RECORDING_STOP,
        ACTION_RECORDING_RESUME,
        ACTION_RECORDING_FEEDBACK_BACKFILLED,
        ACTION_RECORDING_FEEDBACK_NOT_RECORDED,
    ):
        owner_sender_id = payload.get("owner_sender_id")
        if not isinstance(owner_sender_id, str) or not owner_sender_id.strip():
            raise SidecarProtocolError("invalid-owner-sender")
        _validate_access_receipt_fields(payload)

    if action == ACTION_PROFILE_CONSENTED_ADMIT:
        sender_id = payload.get("sender_id")
        if not isinstance(sender_id, str) or not sender_id.strip():
            raise SidecarProtocolError("invalid-sender")
        for field in (
            "message_id",
            "message_utc",
            "attempt_utc",
            "message_text",
            "evidence_kind",
            "channel",
            "profile_name",
            "verification_token",
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise SidecarProtocolError(f"invalid-{field}")
        if not isinstance(payload.get("candidate"), Mapping):
            raise SidecarProtocolError("candidate-must-be-object")

    if action in (
        ACTION_PROFILE_READ,
        ACTION_PROFILE_DELETE_REQUEST,
        ACTION_PROFILE_DELETE_CONFIRM,
        ACTION_PROFILE_DELETION_STATUS,
    ):
        sender_id = payload.get("sender_id")
        if not isinstance(sender_id, str) or not sender_id.strip():
            raise SidecarProtocolError("invalid-sender")
        _validate_access_receipt_fields(payload)

    if action == ACTION_PROFILE_DELETE_CONFIRM:
        request_message_id = payload.get("request_message_id")
        if not isinstance(request_message_id, str) or not request_message_id.strip():
            raise SidecarProtocolError("invalid-request-message-id")

    if action in (ACTION_ACCESS_GRANT, ACTION_ACCESS_REVOKE):
        for field, code in (
            ("owner_sender_id", "invalid-owner-sender"),
            ("viewer_sender_id", "invalid-viewer-sender"),
            ("receipt_message_id", "invalid-receipt-message-id"),
            ("receipt_utc", "invalid-receipt-utc"),
            ("verification_token", "invalid-verification-token"),
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise SidecarProtocolError(code)

    if action in (
        ACTION_ACCESS_READ,
        ACTION_ACCESS_ANALYZE,
        ACTION_PROFILE_EXPORT,
    ):
        sender_id = payload.get("sender_id")
        if not isinstance(sender_id, str) or not sender_id.strip():
            raise SidecarProtocolError("invalid-sender")
        _validate_access_receipt_fields(payload)

    if action == ACTION_SOURCE_QUERY:
        query = payload.get("query")
        if not isinstance(query, str) or not query.strip():
            raise SidecarProtocolError("invalid-source-query")
        source_url = payload.get("source_url")
        if source_url is not None and (
            not isinstance(source_url, str) or not source_url.strip()
        ):
            raise SidecarProtocolError("invalid-source-url")
        timeout_seconds = payload.get("timeout_seconds")
        if timeout_seconds is not None and (
            source_url is None
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= 20
        ):
            raise SidecarProtocolError("invalid-source-timeout")

    if action == ACTION_SOURCE_SCAN:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not all(
            isinstance(item, str) and item.strip() for item in candidates
        ):
            raise SidecarProtocolError("invalid-source-candidates")

    if action == ACTION_HEALTH_TURN_CONTEXT_READ:
        if set(payload) != REQUIRED_FIELDS[ACTION_HEALTH_TURN_CONTEXT_READ]:
            raise SidecarProtocolError("health-turn-context-fields-unsupported")
        for field in (
            "sender_id",
            "message_id",
            "message_utc",
            "message_text",
            "channel",
            "profile_name",
            "attempt_utc",
            "verification_token",
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise SidecarProtocolError(f"invalid-{field}")

    if action in (
        ACTION_DAILY_REVIEW_SNAPSHOT,
        ACTION_DAILY_REVIEW,
        ACTION_DAILY_REVIEW_EXECUTE,
    ):
        for field, code in (
            ("review_utc", "invalid-review-utc"),
            ("timezone", "invalid-timezone"),
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise SidecarProtocolError(code)
        if action == ACTION_DAILY_REVIEW and not isinstance(
            payload.get("plan"), Mapping
        ):
            raise SidecarProtocolError("plan-must-be-object")
        if action == ACTION_DAILY_REVIEW_EXECUTE:
            authorization = payload.get("job_authorization")
            if not isinstance(authorization, str) or not authorization.strip():
                raise SidecarProtocolError("invalid-job-authorization")

    if action == ACTION_DISPATCH_DUE_TASKS:
        now_utc = payload.get("now_utc")
        if not isinstance(now_utc, str) or not now_utc.strip():
            raise SidecarProtocolError("invalid-dispatch-utc")
        authorization = payload.get("job_authorization")
        if not isinstance(authorization, str) or not authorization.strip():
            raise SidecarProtocolError("invalid-job-authorization")

    if action in (ACTION_PROACTIVE_PAUSE, ACTION_PROACTIVE_RESUME):
        owner_sender_id = payload.get("owner_sender_id")
        if not isinstance(owner_sender_id, str) or not owner_sender_id.strip():
            raise SidecarProtocolError("invalid-owner-sender")
        _validate_access_receipt_fields(payload)
        if action == ACTION_PROACTIVE_PAUSE:
            pause_until = payload.get("pause_until_utc")
            if pause_until is not None and (
                not isinstance(pause_until, str) or not pause_until.strip()
            ):
                raise SidecarProtocolError("invalid-pause-time")

    return SidecarRequest(
        req_id=(
            str(loaded.get("req_id")).strip()
            if loaded.get("req_id") is not None
            else None
        ),
        action=action,
        payload=dict(payload),
    )


def _validate_access_receipt_fields(payload: Mapping[str, Any]) -> None:
    for field, code in (
        ("receipt_message_id", "invalid-receipt-message-id"),
        ("receipt_utc", "invalid-receipt-utc"),
        ("verification_token", "invalid-verification-token"),
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SidecarProtocolError(code)


def response_ok(req_id: str | None, action: str, data: Mapping[str, Any]) -> bytes:
    return _build_response(
        {"ok": True, "req_id": req_id, "action": action, "data": dict(data)}
    )


def response_error(
    req_id: str | None, action: str, code: str, message: str
) -> bytes:
    return _build_response(
        {
            "ok": False,
            "req_id": req_id,
            "action": action,
            "error": {"code": code, "message": message},
        }
    )


def iter_stream_response_frames(
    payload: bytes,
    *,
    max_frame_bytes: int,
) -> Iterator[bytes]:
    """Split one response into integrity-bound frames below the socket cap."""
    chunk_bytes = int(max_frame_bytes) - STREAM_RESPONSE_HEADER_BYTES
    if chunk_bytes < 1:
        raise SidecarProtocolError("stream-frame-limit-invalid")
    body = bytes(payload)
    total = max(1, (len(body) + chunk_bytes - 1) // chunk_bytes)
    digest = hashlib.sha256(body).digest()
    for index in range(total):
        chunk = body[index * chunk_bytes : (index + 1) * chunk_bytes]
        yield (
            STREAM_RESPONSE_MAGIC
            + index.to_bytes(4, "big")
            + total.to_bytes(4, "big")
            + digest
            + chunk
        )


def parse_stream_response_frame(
    frame: bytes,
) -> tuple[int, int, bytes, bytes]:
    """Validate one streamed response frame and expose its ordered payload."""
    if (
        not isinstance(frame, bytes)
        or len(frame) < STREAM_RESPONSE_HEADER_BYTES
        or not frame.startswith(STREAM_RESPONSE_MAGIC)
    ):
        raise SidecarProtocolError("stream-response-frame-invalid")
    index = int.from_bytes(frame[4:8], "big")
    total = int.from_bytes(frame[8:12], "big")
    if total < 1 or index >= total:
        raise SidecarProtocolError("stream-response-frame-invalid")
    return index, total, frame[12:44], frame[44:]


def _build_response(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )

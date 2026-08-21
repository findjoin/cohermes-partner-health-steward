"""Python client for the health-sidecar socket protocol."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid
from typing import Any, Mapping

from .protocol import (
    ACTION_AUDIT_READ,
    ACTION_DELIVERY_AUDIT_APPEND,
    ACTION_ACCESS_GRANT,
    ACTION_ACCESS_REVOKE,
    ACTION_ACCESS_READ,
    ACTION_ACCESS_ANALYZE,
    ACTION_PING,
    ACTION_PROFILE_CANDIDATE,
    ACTION_RECORDING_STATUS,
    ACTION_RECORDING_ATTEMPT_BEGIN,
    ACTION_RECORDING_ATTEMPT_END,
    ACTION_RECORDING_ENABLE,
    ACTION_RECORDING_STOP,
    ACTION_RECORDING_RESUME,
    ACTION_PROFILE_CONSENTED_ADMIT,
    ACTION_PROFILE_DELETE_REQUEST,
    ACTION_PROFILE_DELETE_CONFIRM,
    ACTION_PROFILE_DELETION_STATUS,
    ACTION_BACKUPS_PURGE,
    ACTION_PROFILE_MESSAGE_STAGE,
    ACTION_PROFILE_RECENT_MESSAGE,
    ACTION_PROFILE_MESSAGE_ADMISSION_STATUS,
    ACTION_PROFILE_OWNER_BIND,
    ACTION_PROFILE_OWNER_TRANSFER,
    ACTION_PROFILE_OWNER_RECOVER,
    ACTION_PROFILE_READ,
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
    ACTION_STATUS_GET,
    ACTION_STATUS_SET,
    STREAM_RESPONSE_MAGIC,
    SidecarProtocolError,
    parse_stream_response_frame,
)

MAX_FRAME_BYTES = 128 * 1024
DAILY_REVIEW_SOCKET_TIMEOUT_SECONDS = 480.0
# One fixed dispatcher invocation can render several due tasks.  Its pinned
# model has a 15-second per-task budget, so the ordinary two-second control
# RPC timeout would make a healthy sidecar look failed while it keeps working.
# Keep the whole call inside Hermes' 600-second Cron watchdog, with room for
# the scheduler to record a deterministic failure.
DISPATCH_SOCKET_TIMEOUT_SECONDS = 480.0
MAX_STREAM_RESPONSE_FRAMES = 4096


class SidecarClientError(RuntimeError):
    """Raised when the client cannot talk to the sidecar."""


def _pack_frame(payload: bytes) -> bytes:
    if len(payload) > MAX_FRAME_BYTES:
        raise SidecarClientError("payload-too-large")
    return len(payload).to_bytes(4, "big") + payload


def _read_frame(conn: socket.socket) -> bytes:
    header = b""
    while len(header) < 4:
        chunk = conn.recv(4 - len(header))
        if not chunk:
            raise SidecarClientError("remote-closed-before-response")
        header += chunk
    body_len = int.from_bytes(header, "big")
    if body_len < 1 or body_len > MAX_FRAME_BYTES:
        raise SidecarClientError("invalid-response-length")
    body = b""
    while len(body) < body_len:
        chunk = conn.recv(body_len - len(body))
        if not chunk:
            raise SidecarClientError("response-truncated")
        body += chunk
    return body


class HealthSidecarClient:
    """Convenience wrapper to call health-sidecar RPC actions."""

    def __init__(
        self,
        socket_path: str,
        timeout_seconds: float = 2.0,
    ) -> None:
        if not hasattr(socket, "AF_UNIX"):
            raise SidecarClientError("AF_UNIX not available on this platform")
        self.socket_path = socket_path
        self.timeout_seconds = timeout_seconds

    def call(
        self,
        action: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        response = self._exchange(
            action,
            payload,
            timeout_seconds=timeout_seconds,
            streamed=False,
        )
        return self._parse_response(response)

    def call_streamed(
        self,
        action: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        response = self._exchange(
            action,
            payload,
            timeout_seconds=timeout_seconds,
            streamed=True,
        )
        return self._parse_response(response)

    def _exchange(
        self,
        action: str,
        payload: Mapping[str, Any] | None,
        *,
        timeout_seconds: float | None,
        streamed: bool,
    ) -> bytes:
        req = {
            "req_id": str(uuid.uuid4()),
            "action": action,
            "payload": dict(payload or {}),
        }
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(
                    self.timeout_seconds
                    if timeout_seconds is None
                    else float(timeout_seconds)
                )
                sock.connect(self.socket_path)
                body = json.dumps(req, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
                sock.sendall(_pack_frame(body))
                response = _read_frame(sock)
                if streamed and response.startswith(STREAM_RESPONSE_MAGIC):
                    response = self._read_streamed_response(sock, response)
        except (OSError, ValueError) as exc:
            raise SidecarClientError(f"socket-call-failed:{exc}") from exc
        return response

    @staticmethod
    def _read_streamed_response(
        sock: socket.socket,
        first_frame: bytes,
    ) -> bytes:
        try:
            index, total, digest, chunk = parse_stream_response_frame(first_frame)
        except SidecarProtocolError as exc:
            raise SidecarClientError(str(exc)) from exc
        if index != 0 or total > MAX_STREAM_RESPONSE_FRAMES:
            raise SidecarClientError("stream-response-order-invalid")
        chunks = [chunk]
        for expected_index in range(1, total):
            frame = _read_frame(sock)
            try:
                index, frame_total, frame_digest, chunk = (
                    parse_stream_response_frame(frame)
                )
            except SidecarProtocolError as exc:
                raise SidecarClientError(str(exc)) from exc
            if (
                index != expected_index
                or frame_total != total
                or frame_digest != digest
            ):
                raise SidecarClientError("stream-response-order-invalid")
            chunks.append(chunk)
        response = b"".join(chunks)
        if hashlib.sha256(response).digest() != digest:
            raise SidecarClientError("stream-response-integrity-invalid")
        return response

    @staticmethod
    def _parse_response(response: bytes) -> dict[str, Any]:
        try:
            parsed = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SidecarClientError("invalid-response") from exc
        if not isinstance(parsed, dict):
            raise SidecarClientError("invalid-response")
        return parsed

    def ping(self) -> dict[str, Any]:
        return self.call(ACTION_PING)

    def get_status(self, subject: str) -> dict[str, Any]:
        return self.call(ACTION_STATUS_GET, {"subject": subject})

    def set_status(self, subject: str, status: Mapping[str, Any]) -> dict[str, Any]:
        return self.call(ACTION_STATUS_SET, {"subject": subject, "status": dict(status)})

    def read_audit(self) -> dict[str, Any]:
        return self.call(ACTION_AUDIT_READ)

    def append_delivery_audit_once(
        self,
        event_id: str,
        event: str,
        details: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.call(
            ACTION_DELIVERY_AUDIT_APPEND,
            {
                "event_id": event_id,
                "event": event,
                "details": dict(details),
            },
        )

    def bind_profile_owner(
        self, subject: str, owner_sender_id: str, verification_token: str
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_OWNER_BIND,
            {
                "subject": subject,
                "owner_sender_id": owner_sender_id,
                "verification_token": verification_token,
            },
        )

    def transfer_profile_owner(
        self,
        subject: str,
        old_owner_sender_id: str,
        new_owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_OWNER_TRANSFER,
            {
                "subject": subject,
                "old_owner_sender_id": old_owner_sender_id,
                "new_owner_sender_id": new_owner_sender_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def recover_profile_owner(
        self,
        subject: str,
        new_owner_sender_id: str,
        recovery_code: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_OWNER_RECOVER,
            {
                "subject": subject,
                "new_owner_sender_id": new_owner_sender_id,
                "recovery_code": recovery_code,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def record_profile_candidate(
        self,
        subject: str,
        sender_id: str,
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_CANDIDATE,
            {"subject": subject, "sender_id": sender_id, "candidate": dict(candidate)},
        )

    def health_recording_status(
        self, subject: str, sender_id: str
    ) -> dict[str, Any]:
        return self.call(
            ACTION_RECORDING_STATUS,
            {"subject": subject, "sender_id": sender_id},
        )

    def profile_message_admission_status(
        self, subject: str, sender_id: str, message_id: str
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_MESSAGE_ADMISSION_STATUS,
            {
                "subject": subject,
                "sender_id": sender_id,
                "message_id": message_id,
            },
        )

    def begin_recording_attempt(self, subject: str, sender_id: str) -> dict[str, Any]:
        return self.call(
            ACTION_RECORDING_ATTEMPT_BEGIN,
            {"subject": subject, "sender_id": sender_id},
        )

    def end_recording_attempt(self, lease_id: str) -> dict[str, Any]:
        return self.call(ACTION_RECORDING_ATTEMPT_END, {"lease_id": lease_id})

    def enable_health_recording(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_RECORDING_ENABLE,
            {
                "subject": subject,
                "owner_sender_id": owner_sender_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def stop_health_recording(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self._recording_control_call(
            ACTION_RECORDING_STOP,
            subject,
            owner_sender_id,
            receipt_message_id,
            receipt_utc,
            verification_token,
        )

    def resume_health_recording(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self._recording_control_call(
            ACTION_RECORDING_RESUME,
            subject,
            owner_sender_id,
            receipt_message_id,
            receipt_utc,
            verification_token,
        )

    def send_recording_feedback(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
        feedback_status: str,
    ) -> dict[str, Any]:
        from .recording import RECORDING_FEEDBACK_ACTION_BY_STATUS

        try:
            action = RECORDING_FEEDBACK_ACTION_BY_STATUS[feedback_status]
        except KeyError as exc:
            raise SidecarClientError("invalid-recording-feedback-status") from exc
        return self._recording_control_call(
            action,
            subject,
            owner_sender_id,
            receipt_message_id,
            receipt_utc,
            verification_token,
        )

    def _recording_control_call(
        self,
        action: str,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            action,
            {
                "subject": subject,
                "owner_sender_id": owner_sender_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def admit_consented_profile_candidate(
        self,
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        attempt_utc: str,
        message_text: str,
        evidence_kind: str,
        channel: str,
        profile_name: str,
        verification_token: str,
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_CONSENTED_ADMIT,
            {
                "subject": subject,
                "sender_id": sender_id,
                "message_id": message_id,
                "message_utc": message_utc,
                "attempt_utc": attempt_utc,
                "message_text": message_text,
                "evidence_kind": evidence_kind,
                "channel": channel,
                "profile_name": profile_name,
                "verification_token": verification_token,
                "candidate": dict(candidate),
            },
        )

    def read_health_turn_context(
        self,
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        channel: str,
        profile_name: str,
        attempt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_HEALTH_TURN_CONTEXT_READ,
            {
                "subject": subject,
                "sender_id": sender_id,
                "message_id": message_id,
                "message_utc": message_utc,
                "message_text": message_text,
                "channel": channel,
                "profile_name": profile_name,
                "attempt_utc": attempt_utc,
                "verification_token": verification_token,
            },
        )

    def stage_profile_message(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_MESSAGE_STAGE,
            {
                "subject": subject,
                "sender_id": sender_id,
                "message_id": message_id,
                "message_utc": message_utc,
                "message_text": message_text,
                "evidence_kind": evidence_kind,
                "verification_token": verification_token,
            },
        )

    def remember_recent_owner_message(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
        verification_token: str,
        *,
        attempt_utc: str | None = None,
        channel: str = "weixin",
        profile_name: str = "partner",
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_RECENT_MESSAGE,
            {
                "subject": subject,
                "sender_id": sender_id,
                "message_id": message_id,
                "message_utc": message_utc,
                "attempt_utc": attempt_utc or message_utc,
                "message_text": message_text,
                "evidence_kind": evidence_kind,
                "channel": channel,
                "profile_name": profile_name,
                "verification_token": verification_token,
            },
        )

    def read_profile(self, subject: str, sender_id: str) -> dict[str, Any]:
        raise SidecarClientError("profile-read-requires-access-receipt")

    def read_profile_with_receipt(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_READ,
            {
                "subject": subject,
                "sender_id": sender_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def delete_profile(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        """Reject the retired public one-step deletion client seam."""
        raise SidecarClientError("delete-confirmation-required")

    def request_profile_deletion(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_DELETE_REQUEST,
            {
                "subject": subject,
                "sender_id": sender_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def confirm_profile_deletion(
        self,
        subject: str,
        sender_id: str,
        request_message_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_DELETE_CONFIRM,
            {
                "subject": subject,
                "sender_id": sender_id,
                "request_message_id": request_message_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def profile_deletion_status(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROFILE_DELETION_STATUS,
            {
                "subject": subject,
                "sender_id": sender_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def purge_backups(self) -> dict[str, Any]:
        return self.call(ACTION_BACKUPS_PURGE, {})

    def grant_viewer(
        self,
        subject: str,
        owner_sender_id: str,
        viewer_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_ACCESS_GRANT,
            {
                "subject": subject,
                "owner_sender_id": owner_sender_id,
                "viewer_sender_id": viewer_sender_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def revoke_viewer(
        self,
        subject: str,
        owner_sender_id: str,
        viewer_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_ACCESS_REVOKE,
            {
                "subject": subject,
                "owner_sender_id": owner_sender_id,
                "viewer_sender_id": viewer_sender_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def read_authorized_view(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "subject": subject,
            "sender_id": sender_id,
            "receipt_message_id": receipt_message_id,
            "receipt_utc": receipt_utc,
            "verification_token": verification_token,
        }
        return self.call_streamed(ACTION_ACCESS_READ, payload)

    def export_profile(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "subject": subject,
            "sender_id": sender_id,
            "receipt_message_id": receipt_message_id,
            "receipt_utc": receipt_utc,
            "verification_token": verification_token,
        }
        return self.call_streamed(ACTION_PROFILE_EXPORT, payload)

    def read_authorized_analysis_context(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_ACCESS_ANALYZE,
            {
                "subject": subject,
                "sender_id": sender_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

    def query_sources(
        self,
        query: str,
        source_url: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if source_url is not None:
            payload["source_url"] = source_url
        if timeout_seconds is not None:
            payload["timeout_seconds"] = float(timeout_seconds)
        return self.call(
            ACTION_SOURCE_QUERY,
            payload,
            timeout_seconds=(
                None
                if timeout_seconds is None
                else float(timeout_seconds) + 1.0
            ),
        )

    def scan_sources(self, candidates: list[str]) -> dict[str, Any]:
        return self.call(ACTION_SOURCE_SCAN, {"candidates": list(candidates)})

    def daily_review_snapshot(
        self, subject: str, review_utc: str, timezone: str
    ) -> dict[str, Any]:
        return self.call(
            ACTION_DAILY_REVIEW_SNAPSHOT,
            {"subject": subject, "review_utc": review_utc, "timezone": timezone},
        )

    def run_daily_review(
        self,
        subject: str,
        review_utc: str,
        timezone: str,
        plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.call(
            ACTION_DAILY_REVIEW,
            {
                "subject": subject,
                "review_utc": review_utc,
                "timezone": timezone,
                "plan": dict(plan),
            },
        )

    def execute_daily_review(
        self,
        subject: str,
        review_utc: str,
        timezone: str,
        job_authorization: str,
    ) -> dict[str, Any]:
        """Run one delegated daily review within the bounded 480s Job budget.

        480 seconds covers at most twenty 20-second whitelist fetches, the
        20-second pinned model call, and 60 seconds for socket/state overhead;
        it remains below Hermes' 600-second Cron watchdog.
        """
        return self.call(
            ACTION_DAILY_REVIEW_EXECUTE,
            {
                "subject": subject,
                "review_utc": review_utc,
                "timezone": timezone,
                "job_authorization": job_authorization,
            },
            timeout_seconds=DAILY_REVIEW_SOCKET_TIMEOUT_SECONDS,
        )

    def dispatch_due_tasks(
        self, subject: str, now_utc: str, job_authorization: str
    ) -> dict[str, Any]:
        return self.call(
            ACTION_DISPATCH_DUE_TASKS,
            {
                "subject": subject,
                "now_utc": now_utc,
                "job_authorization": job_authorization,
            },
            timeout_seconds=DISPATCH_SOCKET_TIMEOUT_SECONDS,
        )

    def pause_proactive_contact(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
        pause_until_utc: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "subject": subject,
            "owner_sender_id": owner_sender_id,
            "receipt_message_id": receipt_message_id,
            "receipt_utc": receipt_utc,
            "verification_token": verification_token,
        }
        if pause_until_utc is not None:
            payload["pause_until_utc"] = pause_until_utc
        return self.call(ACTION_PROACTIVE_PAUSE, payload)

    def resume_proactive_contact(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> dict[str, Any]:
        return self.call(
            ACTION_PROACTIVE_RESUME,
            {
                "subject": subject,
                "owner_sender_id": owner_sender_id,
                "receipt_message_id": receipt_message_id,
                "receipt_utc": receipt_utc,
                "verification_token": verification_token,
            },
        )

"""Unix-domain-socket health sidecar server."""

from __future__ import annotations

import argparse
import os
import socket
import struct
import threading
from pathlib import Path
from typing import Any

from job_authorization import (
    read_job_authorization_secret,
    verify_job_action_authorization,
)

from .protocol import (
    ACTION_ACCESS_GRANT,
    ACTION_ACCESS_ANALYZE,
    ACTION_ACCESS_READ,
    ACTION_ACCESS_REVOKE,
    ACTION_AUDIT_READ,
    ACTION_DELIVERY_AUDIT_APPEND,
    ACTION_BACKUPS_PURGE,
    ACTION_PING,
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
    ACTION_PROFILE_DELETE_REQUEST,
    ACTION_PROFILE_DELETE_CONFIRM,
    ACTION_PROFILE_DELETION_STATUS,
    ACTION_PROFILE_EXPORT,
    ACTION_PROFILE_MESSAGE_STAGE,
    ACTION_PROFILE_RECENT_MESSAGE,
    ACTION_PROFILE_MESSAGE_ADMISSION_STATUS,
    ACTION_PROFILE_OWNER_BIND,
    ACTION_PROFILE_OWNER_TRANSFER,
    ACTION_PROFILE_OWNER_RECOVER,
    ACTION_PROFILE_READ,
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
    SidecarProtocolError,
    parse_request,
    iter_stream_response_frames,
    response_error,
    response_ok,
)
from .health_turn_context import compose_health_turn_context
from .daily_runner import DailyReviewExecutor, GatewayJobLease
from .ports import (
    HealthStewardPorts,
    NoopMemoryProjection,
    build_health_memory_projection,
)
from .production_ports import ProductionPortsFactory
from .recording import RECORDING_FEEDBACK_STATUS_BY_ACTION
from .sources import SourceLibrary
from .store import (
    Clock,
    Ed25519InboundMessageVerifier,
    HealthSidecarStore,
    InboundMessageVerifier,
    KeyManager,
    StoreError,
)


MAX_FRAME_BYTES = 128 * 1024
MAX_MESSAGE_TIMEOUT_SECONDS = 5
SO_PEERCRED = getattr(socket, "SO_PEERCRED", None)


class HealthSidecarServerError(RuntimeError):
    """Raised for fatal server issues."""


class HealthSidecarServer:
    def __init__(
        self,
        socket_path: str | os.PathLike[str],
        store: HealthSidecarStore,
        allowed_uids: set[int] | None = None,
        allowed_gids: set[int] | None = None,
        socket_gid: int | None = None,
        socket_mode: int = 0o660,
        ready_event: Any | None = None,
        ports: HealthStewardPorts | None = None,
        approved_guideline_hosts: set[str] | None = None,
        memory_projection: Any | None = None,
        projection_subject: str | None = None,
        job_authorization_secret: bytes | None = None,
    ) -> None:
        if not hasattr(socket, "AF_UNIX"):
            raise HealthSidecarServerError("AF_UNIX is not available on this platform")

        self.socket_path = Path(socket_path)
        self.store = store
        self.allowed_uids = set(int(uid) for uid in (allowed_uids or ()))
        self.allowed_gids = set(int(gid) for gid in (allowed_gids or ()))
        self.socket_gid = socket_gid
        self.socket_mode = socket_mode
        self.ready_event = ready_event
        self.ports = ports
        self.memory_projection = (
            memory_projection
            or (ports.memory_projection if ports is not None else None)
            or NoopMemoryProjection()
        )
        self.projection_subject = str(projection_subject or "").strip() or None
        self._job_authorization_secret = job_authorization_secret
        self._gateway_job_lease = GatewayJobLease(store.now_utc)
        self.source_library = SourceLibrary(
            store,
            source_fetch=ports.source_fetch if ports is not None else None,
            approved_guideline_hosts=approved_guideline_hosts,
        )
        daily_executor_required = (
            ports is not None
            and self.projection_subject is not None
            and callable(getattr(ports.llm, "complete_daily_review", None))
        )
        if daily_executor_required and (
            not isinstance(job_authorization_secret, bytes)
            or len(job_authorization_secret) < 32
        ):
            raise HealthSidecarServerError("job-authorization-secret-required")
        self.daily_executor = (
            DailyReviewExecutor(
                store=store,
                source_library=self.source_library,
                model=ports.llm,
                subject=self.projection_subject,
                gateway_live=self._gateway_job_lease.active,
            )
            if daily_executor_required
            else None
        )
        self._sock: socket.socket | None = None
        self._stopped = threading.Event()

    def _sync_projection(self, subject: str, *, fail_closed: bool = False) -> bool:
        if self.projection_subject != subject:
            return False
        try:
            profile = self.store.read_subject_status(
                subject, _allow_profile_state=True
            )
            if not isinstance(profile, dict) or profile.get("profile_schema_version") != 1:
                return False
            projection = build_health_memory_projection(
                subject, profile, self.store.now_utc()
            )
            if not self.memory_projection.replace_health_projection(
                subject, projection
            ):
                raise RuntimeError("projection-replace-refused")
            return True
        except Exception as exc:
            if fail_closed:
                raise HealthSidecarServerError("memory-projection-sync-failed") from exc
            self.store.append_audit_event(
                "memory_projection_sync",
                {
                    "subject": subject,
                    "actor_role": "sidecar",
                    "action": "memory.projection.sync",
                    "object_id": f"projection:{subject}",
                    "result": "failed",
                    "reason": "projection-sync-failed",
                },
            )
            return False

    @property
    def socket_file(self) -> str:
        return str(self.socket_path)

    def run_forever(self, listen_backlog: int = 16) -> None:
        if self._sock is not None:
            raise HealthSidecarServerError("server-already-running")

        if self.projection_subject is not None:
            self._sync_projection(self.projection_subject, fail_closed=True)

        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError as exc:
                raise HealthSidecarServerError(
                    f"failed-remove-existing-socket:{exc}"
                ) from exc

        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(self.socket_path))
        sock.listen(listen_backlog)
        try:
            os.chmod(self.socket_path, self.socket_mode)
        except OSError:
            pass
        if self.socket_gid is not None:
            try:
                os.chown(self.socket_path, -1, self.socket_gid)
            except OSError:
                raise HealthSidecarServerError("socket-chown-failed")
        self._sock = sock
        if self.daily_executor is not None:
            self.daily_executor.start()
        if self.ready_event is not None:
            self.ready_event.set()

        try:
            while not self._stopped.is_set():
                try:
                    conn, _ = sock.accept()
                except OSError:
                    continue
                handler = threading.Thread(
                    target=self._handle_client, args=(conn,), daemon=True
                )
                handler.start()
        finally:
            if self.daily_executor is not None:
                self.daily_executor.stop()
            sock.close()
            self._sock = None
            try:
                self.socket_path.unlink()
            except OSError:
                pass

    def stop(self) -> None:
        self._stopped.set()
        if self._sock is not None:
            self._sock.close()

    def _authorize_job_action(
        self, authorization: str, *, role: str, subject: str, peer_uid: int, peer_gid: int
    ) -> None:
        if not isinstance(self._job_authorization_secret, bytes):
            raise HealthSidecarServerError("job-authorization-secret-unavailable")
        claims = verify_job_action_authorization(
            self._job_authorization_secret,
            authorization,
            role=role,
            subject=subject,
            now_utc=self.store.now_utc(),
        )
        if claims is None:
            raise HealthSidecarServerError("job-authorization-invalid")
        self.store.consume_job_action_authorization(
            claims["nonce"], claims["issued_utc"]
        )
        self.store.append_audit_event(
            "job_action_authorized",
            {
                "subject": subject,
                "actor_role": role,
                "action": "health.job.authorize",
                "object_id": role,
                "result": "accepted",
                "peer_uid": peer_uid,
                "peer_gid": peer_gid,
            },
        )
        self._gateway_job_lease.renew()
        if self.daily_executor is not None:
            self.daily_executor.wake()

    def _handle_client(self, conn: socket.socket) -> None:
        with conn:
            request = None
            peer_uid = -1
            peer_gid = -1
            try:
                request_bytes = _read_frame(conn)
                if not request_bytes:
                    return
                peer_uid = _peer_uid(conn)
                peer_gid = _peer_gid(conn)
                request = parse_request(request_bytes)
                if not self._is_authorized(uid=peer_uid, gid=peer_gid):
                    conn.sendall(
                        _pack_response(
                            response_error(
                                request.req_id,
                                request.action,
                                "unauthorized_client",
                                "peer-identity-not-authorized",
                            )
                        )
                    )
                    self.store.append_audit_event(
                        "request_rejected",
                        {
                            "action": request.action,
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "reason": "unauthorized",
                        },
                    )
                    return

                if request.action == ACTION_PING:
                    self.store.append_audit_event(
                        "ping", {"peer_uid": peer_uid, "peer_gid": peer_gid}
                    )
                    resp = response_ok(request.req_id, ACTION_PING, {"status": "ok"})
                elif request.action == ACTION_STATUS_GET:
                    subject = str(request.payload["subject"]).strip()
                    status = self.store.read_subject_status(subject)
                    meta = self.store.metadata()
                    if status is None:
                        resp_data = {"subject": subject, "found": False}
                    else:
                        resp_data = {
                            "subject": subject,
                            "found": True,
                            "version": int(meta.get("version", 0)),
                            "status": status,
                            "updated_utc": str(meta.get("updated_utc")),
                        }
                    self.store.append_audit_event(
                        "status_get",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "subject": subject,
                            "found": resp_data["found"],
                        },
                    )
                    resp = response_ok(request.req_id, ACTION_STATUS_GET, resp_data)
                elif request.action == ACTION_STATUS_SET:
                    subject = str(request.payload["subject"]).strip()
                    status = request.payload["status"]
                    version = self.store.write_subject_status(subject, status)
                    self.store.append_audit_event(
                        "status_set",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "subject": subject,
                            "version": version,
                        },
                    )
                    resp = response_ok(
                        request.req_id,
                        ACTION_STATUS_SET,
                        {
                            "subject": subject,
                            "written": True,
                            "version": version,
                        },
                    )
                elif request.action == ACTION_AUDIT_READ:
                    events = self.store.read_audit_events()
                    self.store.append_audit_event(
                        "audit_read",
                        {"peer_uid": peer_uid, "peer_gid": peer_gid},
                    )
                    resp = response_ok(
                        request.req_id,
                        ACTION_AUDIT_READ,
                        {"events": events},
                    )
                elif request.action == ACTION_DELIVERY_AUDIT_APPEND:
                    appended = self.store.append_audit_event_once(
                        str(request.payload["event_id"]).strip(),
                        str(request.payload["event"]).strip(),
                        request.payload["details"],
                    )
                    resp = response_ok(
                        request.req_id,
                        ACTION_DELIVERY_AUDIT_APPEND,
                        {"appended": appended},
                    )
                elif request.action == ACTION_PROFILE_OWNER_BIND:
                    subject = str(request.payload["subject"]).strip()
                    owner_sender_id = str(request.payload["owner_sender_id"]).strip()
                    bound = self.store.bind_profile_owner(
                        subject,
                        owner_sender_id,
                        str(request.payload["verification_token"]).strip(),
                    )
                    self._sync_projection(subject)
                    self.store.append_audit_event(
                        "profile_owner_bind",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "subject": subject,
                            "bound": bound,
                        },
                    )
                    resp = response_ok(
                        request.req_id,
                        ACTION_PROFILE_OWNER_BIND,
                        {"subject": subject, "bound": bound},
                    )
                elif request.action == ACTION_PROFILE_OWNER_TRANSFER:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.transfer_profile_owner(
                        subject,
                        str(request.payload["old_owner_sender_id"]).strip(),
                        str(request.payload["new_owner_sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    self._sync_projection(subject)
                    resp = response_ok(
                        request.req_id,
                        ACTION_PROFILE_OWNER_TRANSFER,
                        result,
                    )
                elif request.action == ACTION_PROFILE_OWNER_RECOVER:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.recover_profile_owner(
                        subject,
                        str(request.payload["new_owner_sender_id"]).strip(),
                        str(request.payload["recovery_code"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    self._sync_projection(subject)
                    resp = response_ok(
                        request.req_id,
                        ACTION_PROFILE_OWNER_RECOVER,
                        result,
                    )
                elif request.action == ACTION_PROFILE_MESSAGE_STAGE:
                    subject = str(request.payload["subject"]).strip()
                    sender_id = str(request.payload["sender_id"]).strip()
                    staged = self.store.stage_profile_message(
                        subject,
                        sender_id,
                        str(request.payload["message_id"]).strip(),
                        str(request.payload["message_utc"]).strip(),
                        str(request.payload["message_text"]),
                        str(request.payload["evidence_kind"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    self.store.append_audit_event(
                        "profile_message_staged",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "subject": subject,
                            "sender_id": sender_id,
                            "message_id": str(request.payload["message_id"]).strip(),
                        },
                    )
                    resp = response_ok(
                        request.req_id,
                        ACTION_PROFILE_MESSAGE_STAGE,
                        {"subject": subject, "staged": staged},
                    )
                elif request.action == ACTION_PROFILE_RECENT_MESSAGE:
                    subject = str(request.payload["subject"]).strip()
                    sender_id = str(request.payload["sender_id"]).strip()
                    remembered = self.store.remember_recent_owner_message(
                        subject,
                        sender_id,
                        str(request.payload["message_id"]).strip(),
                        str(request.payload["message_utc"]).strip(),
                        str(request.payload["message_text"]),
                        str(request.payload["evidence_kind"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                        attempt_utc=str(request.payload["attempt_utc"]).strip(),
                        channel=str(request.payload["channel"]).strip(),
                        profile_name=str(request.payload["profile_name"]).strip(),
                    )
                    resp = response_ok(
                        request.req_id,
                        ACTION_PROFILE_RECENT_MESSAGE,
                        {"subject": subject, "remembered": remembered},
                    )
                elif request.action == ACTION_PROFILE_CANDIDATE:
                    subject = str(request.payload["subject"]).strip()
                    sender_id = str(request.payload["sender_id"]).strip()
                    result = self.store.record_profile_candidate(
                        subject,
                        sender_id,
                        request.payload["candidate"],
                    )
                    self._sync_projection(subject)
                    self.store.append_audit_event(
                        "profile_candidate_accepted",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "subject": subject,
                            "actor_role": "owner",
                            "actor_id": sender_id,
                            "action": "health.profile.candidate",
                            "object_id": result["version_id"],
                            "result": "accepted",
                            "evidence_id": result["evidence_id"],
                            "evidence_ids": [result["evidence_id"]],
                            "version_id": result["version_id"],
                        },
                    )
                    resp = response_ok(request.req_id, ACTION_PROFILE_CANDIDATE, result)
                elif request.action == ACTION_RECORDING_STATUS:
                    subject = str(request.payload["subject"]).strip()
                    sender_id = str(request.payload["sender_id"]).strip()
                    resp = response_ok(
                        request.req_id,
                        ACTION_RECORDING_STATUS,
                        {
                            "subject": subject,
                            "enabled": self.store.health_recording_enabled(
                                subject, sender_id
                            ),
                            "status": self.store.health_recording_status(
                                subject, sender_id
                            ),
                        },
                    )
                elif request.action == ACTION_RECORDING_ATTEMPT_BEGIN:
                    subject = str(request.payload["subject"]).strip()
                    sender_id = str(request.payload["sender_id"]).strip()
                    resp = response_ok(
                        request.req_id,
                        ACTION_RECORDING_ATTEMPT_BEGIN,
                        {
                            "subject": subject,
                            "lease_id": self.store.begin_recording_attempt(
                                subject, sender_id
                            ),
                        },
                    )
                elif request.action == ACTION_RECORDING_ATTEMPT_END:
                    lease_id = str(request.payload["lease_id"]).strip()
                    resp = response_ok(
                        request.req_id,
                        ACTION_RECORDING_ATTEMPT_END,
                        {
                            "lease_id": lease_id,
                            "released": self.store.end_recording_attempt(lease_id),
                        },
                    )
                elif request.action == ACTION_PROFILE_MESSAGE_ADMISSION_STATUS:
                    subject = str(request.payload["subject"]).strip()
                    sender_id = str(request.payload["sender_id"]).strip()
                    message_id = str(request.payload["message_id"]).strip()
                    resp = response_ok(
                        request.req_id,
                        ACTION_PROFILE_MESSAGE_ADMISSION_STATUS,
                        {
                            "subject": subject,
                            "message_id": message_id,
                            "admitted": self.store.profile_message_admitted(
                                subject, sender_id, message_id
                            ),
                        },
                    )
                elif request.action == ACTION_RECORDING_ENABLE:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.enable_health_recording(
                        subject,
                        str(request.payload["owner_sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    resp = response_ok(
                        request.req_id, ACTION_RECORDING_ENABLE, result
                    )
                elif request.action in (ACTION_RECORDING_STOP, ACTION_RECORDING_RESUME):
                    subject = str(request.payload["subject"]).strip()
                    method = (
                        self.store.stop_health_recording
                        if request.action == ACTION_RECORDING_STOP
                        else self.store.resume_health_recording
                    )
                    result = method(
                        subject,
                        str(request.payload["owner_sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    self._sync_projection(subject)
                    resp = response_ok(request.req_id, request.action, result)
                elif request.action in (
                    ACTION_RECORDING_FEEDBACK_BACKFILLED,
                    ACTION_RECORDING_FEEDBACK_NOT_RECORDED,
                ):
                    subject = str(request.payload["subject"]).strip()
                    feedback_status = RECORDING_FEEDBACK_STATUS_BY_ACTION[
                        request.action
                    ]
                    result = self.store.send_recording_feedback(
                        subject,
                        str(request.payload["owner_sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                        feedback_status,
                        self.ports.channel_send if self.ports is not None else None,
                    )
                    resp = response_ok(request.req_id, request.action, result)
                elif request.action == ACTION_PROFILE_CONSENTED_ADMIT:
                    subject = str(request.payload["subject"]).strip()
                    sender_id = str(request.payload["sender_id"]).strip()
                    result = self.store.admit_consented_profile_candidate(
                        subject=subject,
                        sender_id=sender_id,
                        message_id=str(request.payload["message_id"]).strip(),
                        message_utc=str(request.payload["message_utc"]).strip(),
                        attempt_utc=str(request.payload["attempt_utc"]).strip(),
                        message_text=str(request.payload["message_text"]),
                        evidence_kind=str(request.payload["evidence_kind"]).strip(),
                        channel=str(request.payload["channel"]).strip(),
                        profile_name=str(request.payload["profile_name"]).strip(),
                        verification_token=str(
                            request.payload["verification_token"]
                        ).strip(),
                        candidate=request.payload["candidate"],
                        audit_context={"peer_uid": peer_uid, "peer_gid": peer_gid},
                    )
                    self._sync_projection(subject)
                    resp = response_ok(
                        request.req_id, ACTION_PROFILE_CONSENTED_ADMIT, result
                    )
                elif request.action == ACTION_PROFILE_READ:
                    subject = str(request.payload["subject"]).strip()
                    sender_id = str(request.payload["sender_id"]).strip()
                    view = self.store.read_authorized_view(
                        subject,
                        sender_id,
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                        action=ACTION_PROFILE_READ,
                    )
                    profile = view["profile"]
                    self.store.append_audit_event(
                        "profile_read",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "subject": subject,
                            "sender_id": sender_id,
                        },
                    )
                    resp = response_ok(request.req_id, ACTION_PROFILE_READ, profile)
                elif request.action == ACTION_PROFILE_DELETE_REQUEST:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.request_profile_deletion(
                        subject,
                        str(request.payload["sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    resp = response_ok(
                        request.req_id, ACTION_PROFILE_DELETE_REQUEST, result
                    )
                elif request.action == ACTION_PROFILE_DELETE_CONFIRM:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.confirm_profile_deletion(
                        subject,
                        str(request.payload["sender_id"]).strip(),
                        str(request.payload["request_message_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                        memory_projection=self.memory_projection,
                    )
                    resp = response_ok(
                        request.req_id, ACTION_PROFILE_DELETE_CONFIRM, result
                    )
                elif request.action == ACTION_PROFILE_DELETION_STATUS:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.profile_deletion_status(
                        subject,
                        str(request.payload["sender_id"]),
                        str(request.payload["receipt_message_id"]),
                        str(request.payload["receipt_utc"]),
                        str(request.payload["verification_token"]),
                    )
                    resp = response_ok(
                        request.req_id, ACTION_PROFILE_DELETION_STATUS, result
                    )
                elif request.action == ACTION_BACKUPS_PURGE:
                    result = self.store.purge_expired_backups()
                    self.store.append_audit_event(
                        "backup_purge",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "action": ACTION_BACKUPS_PURGE,
                            "object_id": "encrypted-backups",
                            "result": "completed",
                            "deleted": int(result.get("deleted", 0)),
                            "failed": int(result.get("failed", 0)),
                        },
                    )
                    resp = response_ok(request.req_id, ACTION_BACKUPS_PURGE, result)
                elif request.action == ACTION_ACCESS_GRANT:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.grant_profile_viewer(
                        subject,
                        str(request.payload["owner_sender_id"]).strip(),
                        str(request.payload["viewer_sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    resp = response_ok(request.req_id, ACTION_ACCESS_GRANT, result)
                elif request.action == ACTION_ACCESS_REVOKE:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.revoke_profile_viewer(
                        subject,
                        str(request.payload["owner_sender_id"]).strip(),
                        str(request.payload["viewer_sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    resp = response_ok(request.req_id, ACTION_ACCESS_REVOKE, result)
                elif request.action == ACTION_ACCESS_READ:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.read_authorized_view(
                        subject,
                        str(request.payload["sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    resp = response_ok(request.req_id, ACTION_ACCESS_READ, result)
                elif request.action == ACTION_ACCESS_ANALYZE:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.read_authorized_analysis_context(
                        subject,
                        str(request.payload["sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    resp = response_ok(
                        request.req_id,
                        ACTION_ACCESS_ANALYZE,
                        result,
                    )
                elif request.action == ACTION_PROFILE_EXPORT:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.export_profile(
                        subject,
                        str(request.payload["sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    resp = response_ok(request.req_id, ACTION_PROFILE_EXPORT, result)
                elif request.action == ACTION_HEALTH_TURN_CONTEXT_READ:
                    subject = str(request.payload["subject"]).strip()
                    message_text = str(request.payload["message_text"])
                    # SourceLibrary can touch card usage metadata, so preserve
                    # the established source-lock then state-lock order while
                    # taking the post-write current profile snapshot.
                    with self.store.source_library_lock():
                        with self.store._state_lock:
                            profile_context = self.store.read_health_turn_context(
                                subject=subject,
                                sender_id=str(
                                    request.payload["sender_id"]
                                ).strip(),
                                message_id=str(
                                    request.payload["message_id"]
                                ).strip(),
                                message_utc=str(
                                    request.payload["message_utc"]
                                ).strip(),
                                message_text=message_text,
                                channel=str(request.payload["channel"]).strip(),
                                profile_name=str(
                                    request.payload["profile_name"]
                                ).strip(),
                                attempt_utc=str(
                                    request.payload["attempt_utc"]
                                ).strip(),
                                verification_token=str(
                                    request.payload["verification_token"]
                                ).strip(),
                            )
                            source_result = self.source_library.lookup(message_text)
                            result = compose_health_turn_context(
                                profile_context, source_result
                            )
                    self.store.append_audit_event(
                        "health_turn_context_read",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "subject": subject,
                            "action": ACTION_HEALTH_TURN_CONTEXT_READ,
                            "result": "accepted",
                            "version_id": result["current_version_id"],
                            "verified": result["source_status"]["verified"],
                            "source": result["source_status"]["source"],
                        },
                    )
                    resp = response_ok(
                        request.req_id, ACTION_HEALTH_TURN_CONTEXT_READ, result
                    )
                elif request.action == ACTION_SOURCE_QUERY:
                    query = str(request.payload["query"]).strip()
                    source_url = request.payload.get("source_url")
                    timeout_seconds = request.payload.get("timeout_seconds")
                    result = self.source_library.lookup(
                        query,
                        source_url,
                        timeout_seconds=(
                            None
                            if timeout_seconds is None
                            else float(timeout_seconds)
                        ),
                    )
                    self.store.append_audit_event(
                        "source_query",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "verified": bool(result.get("verified")),
                            "source": str(result.get("source", "")),
                        },
                    )
                    resp = response_ok(request.req_id, ACTION_SOURCE_QUERY, result)
                elif request.action == ACTION_SOURCE_SCAN:
                    result = self.source_library.scan(request.payload["candidates"])
                    self.store.append_audit_event(
                        "source_scan",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "downloaded": len(result.get("downloaded", [])),
                            "deferred": len(result.get("deferred", [])),
                            "rejected": len(result.get("rejected", [])),
                        },
                    )
                    resp = response_ok(request.req_id, ACTION_SOURCE_SCAN, result)
                elif request.action == ACTION_DAILY_REVIEW_SNAPSHOT:
                    if self.daily_executor is not None:
                        raise HealthSidecarServerError(
                            "daily-review-legacy-action-disabled"
                        )
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.daily_review_snapshot(
                        subject,
                        str(request.payload["review_utc"]).strip(),
                        str(request.payload["timezone"]).strip(),
                        audit_context={
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                        },
                    )
                    if result.get("recording_status") != "recording_stopped":
                        self._sync_projection(subject)
                    resp = response_ok(
                        request.req_id, ACTION_DAILY_REVIEW_SNAPSHOT, result
                    )
                elif request.action == ACTION_DAILY_REVIEW:
                    if self.daily_executor is not None:
                        raise HealthSidecarServerError(
                            "daily-review-legacy-action-disabled"
                        )
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.run_daily_review(
                        subject,
                        str(request.payload["review_utc"]).strip(),
                        str(request.payload["timezone"]).strip(),
                        request.payload["plan"],
                        source_library=self.source_library,
                    )
                    self._sync_projection(subject)
                    resp = response_ok(request.req_id, ACTION_DAILY_REVIEW, result)
                elif request.action == ACTION_DAILY_REVIEW_EXECUTE:
                    subject = str(request.payload["subject"]).strip()
                    if self.daily_executor is None or subject != self.daily_executor.subject:
                        raise HealthSidecarServerError(
                            "daily-review-production-model-unavailable"
                        )
                    self._authorize_job_action(
                        str(request.payload["job_authorization"]),
                        role="daily_profile_review",
                        subject=subject,
                        peer_uid=peer_uid,
                        peer_gid=peer_gid,
                    )
                    result = self.daily_executor.run_initial(
                        str(request.payload["review_utc"]).strip(),
                        str(request.payload["timezone"]).strip(),
                    )
                    self._sync_projection(subject)
                    resp = response_ok(
                        request.req_id, ACTION_DAILY_REVIEW_EXECUTE, result
                    )
                elif request.action == ACTION_DISPATCH_DUE_TASKS:
                    subject = str(request.payload["subject"]).strip()
                    if self.ports is not None:
                        self._authorize_job_action(
                            str(request.payload["job_authorization"]),
                            role="due_task_dispatch",
                            subject=subject,
                            peer_uid=peer_uid,
                            peer_gid=peer_gid,
                        )
                    result = self.store.dispatch_due_tasks(
                        subject,
                        str(request.payload["now_utc"]).strip(),
                        self.ports.llm if self.ports is not None else None,
                        self.ports.channel_send if self.ports is not None else None,
                        source_library=self.source_library,
                    )
                    resp = response_ok(
                        request.req_id, ACTION_DISPATCH_DUE_TASKS, result
                    )
                elif request.action == ACTION_PROACTIVE_PAUSE:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.pause_proactive_contact(
                        subject,
                        str(request.payload["owner_sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                        request.payload.get("pause_until_utc"),
                    )
                    self._sync_projection(subject)
                    resp = response_ok(request.req_id, ACTION_PROACTIVE_PAUSE, result)
                elif request.action == ACTION_PROACTIVE_RESUME:
                    subject = str(request.payload["subject"]).strip()
                    result = self.store.resume_proactive_contact(
                        subject,
                        str(request.payload["owner_sender_id"]).strip(),
                        str(request.payload["receipt_message_id"]).strip(),
                        str(request.payload["receipt_utc"]).strip(),
                        str(request.payload["verification_token"]).strip(),
                    )
                    self._sync_projection(subject)
                    resp = response_ok(request.req_id, ACTION_PROACTIVE_RESUME, result)
                else:
                    # This should be impossible after parse_request.
                    raise HealthSidecarServerError("unsupported_action")

                if request.action in {ACTION_ACCESS_READ, ACTION_PROFILE_EXPORT}:
                    for frame in iter_stream_response_frames(
                        resp,
                        max_frame_bytes=MAX_FRAME_BYTES,
                    ):
                        conn.sendall(_pack_response(frame))
                else:
                    conn.sendall(_pack_response(resp))
            except SidecarProtocolError as exc:
                self.store.append_audit_event(
                    "protocol_error",
                    {
                        "peer_uid": peer_uid,
                        "peer_gid": peer_gid,
                        "action": request.action if request else "",
                        "result": "rejected",
                        "reason": "protocol-error",
                        "error_type": type(exc).__name__,
                    },
                )
                conn.sendall(
                    _pack_response(
                        response_error(
                            None,
                            "",
                            "protocol_error",
                            str(exc),
                        )
                    )
                )
            except StoreError as exc:
                reason = getattr(exc, "code", "state_error")
                rejection_event = (
                    "profile_candidate_rejected"
                    if request is not None
                    and request.action in {
                        ACTION_PROFILE_CANDIDATE,
                        ACTION_PROFILE_CONSENTED_ADMIT,
                    }
                    else "state_request_rejected"
                )
                try:
                    self.store.append_audit_event(
                        rejection_event,
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "action": request.action if request else "",
                            "result": "rejected",
                            "reason": reason,
                        },
                    )
                except Exception:
                    pass
                conn.sendall(
                    _pack_response(
                        response_error(
                            request.req_id if request else None,
                            request.action if request else "",
                            str(reason),
                            str(reason),
                        )
                    )
                )
            except Exception as exc:
                try:
                    self.store.append_audit_event(
                        "request_failed",
                        {
                            "peer_uid": peer_uid,
                            "peer_gid": peer_gid,
                            "action": request.action if request else "",
                            "result": "failed",
                            "reason": "request-failed",
                            "error_type": type(exc).__name__,
                        },
                    )
                except Exception:
                    pass
                conn.sendall(
                    _pack_response(
                        response_error(
                            None,
                            "",
                            "server_error",
                            "internal_error",
                        )
                    )
                )

    def _is_authorized(self, uid: int, gid: int | None) -> bool:
        if not self.allowed_uids and not self.allowed_gids:
            return False
        if uid in self.allowed_uids:
            return True
        return gid is not None and gid in self.allowed_gids


def run_server(
    socket_path: str,
    state_path: str,
    key_path: str,
    allowed_uids: set[int] | None = None,
    allowed_gids: set[int] | None = None,
    socket_gid: int | None = None,
    socket_mode: int = 0o660,
    listen_backlog: int = 16,
    clock: Clock | None = None,
    key_manager: KeyManager | None = None,
    ready_event: Any | None = None,
    ports: HealthStewardPorts | None = None,
    production_ports_factory: Any | None = None,
    message_verifier: InboundMessageVerifier | None = None,
    approved_guideline_hosts: set[str] | None = None,
    memory_projection: Any | None = None,
    projection_subject: str | None = None,
    expected_owner_sender_id: str | None = None,
    expected_viewer_sender_id: str | None = None,
    job_authorization_secret: bytes | None = None,
) -> None:
    if message_verifier is None:
        raise HealthSidecarServerError("message-verifier-required")
    if ports is not None and production_ports_factory is not None:
        raise ValueError("ports-conflict-with-production-ports-factory")
    if production_ports_factory is not None:
        if clock is not None or key_manager is not None:
            raise ValueError("ports-conflict-with-explicit-clock-or-key-manager")
        clock = getattr(production_ports_factory, "clock", None)
        key_manager = getattr(production_ports_factory, "key_manager", None)
        if clock is None or key_manager is None:
            raise HealthSidecarServerError("production-ports-factory-invalid")
    if ports is not None:
        if clock is not None or key_manager is not None:
            raise ValueError("ports-conflict-with-explicit-clock-or-key-manager")
        clock = ports.clock
        key_manager = ports.key_manager
    store = HealthSidecarStore(
        state_path,
        key_path,
        clock=clock,
        key_manager=key_manager,
        message_verifier=message_verifier,
        expected_owner_sender_id=expected_owner_sender_id,
        expected_viewer_sender_id=expected_viewer_sender_id,
    )
    if production_ports_factory is not None:
        try:
            ports = production_ports_factory.build(store)
        except Exception as exc:
            raise HealthSidecarServerError("production-ports-unavailable") from exc
        if not isinstance(ports, HealthStewardPorts):
            raise HealthSidecarServerError("production-ports-factory-invalid")
        if ports.clock is not clock or ports.key_manager is not key_manager:
            raise HealthSidecarServerError("production-ports-clock-key-mismatch")
    server = HealthSidecarServer(
        socket_path=socket_path,
        store=store,
        allowed_uids=allowed_uids,
        allowed_gids=allowed_gids,
        socket_gid=socket_gid,
        socket_mode=socket_mode,
        ready_event=ready_event,
        ports=ports,
        approved_guideline_hosts=approved_guideline_hosts,
        memory_projection=memory_projection,
        projection_subject=projection_subject,
        job_authorization_secret=job_authorization_secret,
    )
    server.run_forever(listen_backlog=listen_backlog)


def _pack_response(payload: bytes) -> bytes:
    if len(payload) > MAX_FRAME_BYTES:
        raise HealthSidecarServerError("response-too-large")
    return len(payload).to_bytes(4, "big") + payload


def _read_frame(conn: socket.socket) -> bytes:
    header = _recv_exact(conn, 4)
    if not header:
        return b""
    frame_len = int.from_bytes(header, "big")
    if frame_len < 2 or frame_len > MAX_FRAME_BYTES:
        raise HealthSidecarServerError("invalid-frame-length")
    return _recv_exact(conn, frame_len)


def _recv_exact(conn: socket.socket, length: int) -> bytes:
    data = bytearray()
    conn.settimeout(MAX_MESSAGE_TIMEOUT_SECONDS)
    try:
        while len(data) < length:
            chunk = conn.recv(length - len(data))
            if not chunk:
                break
            data.extend(chunk)
    finally:
        conn.settimeout(None)
    if len(data) != length:
        raise HealthSidecarServerError("connection-closed-before-frame-complete")
    return bytes(data)


def _peer_uid(conn: socket.socket) -> int:
    if SO_PEERCRED is None:
        return -1
    raw = conn.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", raw)
    return int(uid)


def _peer_gid(conn: socket.socket) -> int | None:
    if SO_PEERCRED is None:
        return -1
    raw = conn.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("3i"))
    _pid, _uid, gid = struct.unpack("3i", raw)
    return int(gid)


def _parse_uids(value: str | None) -> set[int]:
    return _parse_int_set(value)


def _parse_gids(value: str | None) -> set[int]:
    return _parse_int_set(value)


def _parse_hosts(value: str | None) -> set[str]:
    return {item.strip().lower().rstrip(".") for item in (value or "").split(",") if item.strip()}


def _parse_int_set(value: str | None) -> set[int]:
    output: set[int] = set()
    if not value:
        return output
    for token in value.split(","):
        token = token.strip()
        if token:
            output.add(int(token))
    return output


def _parse_octal_mode(value: str | None) -> int:
    if not value:
        return 0o660
    try:
        return int(value, 8)
    except ValueError as exc:
        raise HealthSidecarServerError(f"invalid-socket-mode:{exc}") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="run the health-sidecar daemon")
    parser.add_argument(
        "--socket",
        default=os.getenv("HEALTH_SIDECAR_SOCKET", "/run/health-sidecar/health-sidecar.sock"),
        help="Unix socket path for partner sidecar requests",
    )
    parser.add_argument(
        "--state-path",
        default=os.getenv(
            "HEALTH_SIDECAR_STATE_PATH",
            os.path.expanduser("~/.local/share/health-sidecar/state.sqlite.enc"),
        ),
        help="Encrypted sqlite profile state file",
    )
    parser.add_argument(
        "--key-path",
        default=os.getenv(
            "HEALTH_SIDECAR_KEY_PATH",
            os.path.expanduser("~/.local/share/health-sidecar/sidecar.key"),
        ),
        help="Master key path",
    )
    parser.add_argument(
        "--receipt-public-key-path",
        default=os.getenv("HEALTH_SIDECAR_RECEIPT_PUBLIC_KEY_PATH"),
        help="Gateway Ed25519 public key path; required for profile writes",
    )
    parser.add_argument(
        "--approved-guideline-hosts",
        default=os.getenv("HEALTH_SIDECAR_APPROVED_GUIDELINE_HOSTS", ""),
        help="Comma-separated HTTPS hosts for reviewed specialty guidelines",
    )
    parser.add_argument(
        "--memory-projection-path",
        default=os.getenv("HEALTH_SIDECAR_MEMORY_PROJECTION_PATH"),
        help="JSON bridge file containing the narrow Hermes memory projection; required",
    )
    parser.add_argument(
        "--projection-subject",
        default=os.getenv("HEALTH_SIDECAR_SUBJECT", "profile"),
        help="Single profile subject projected into the partner memory bridge",
    )
    parser.add_argument(
        "--job-authorization-secret-path",
        default=os.getenv("HEALTH_SIDECAR_JOB_AUTHORIZATION_SECRET_PATH"),
        help="Private shared key used only to verify delegated fixed-Job actions",
    )
    parser.add_argument(
        "--expected-owner-sender-id",
        default=os.getenv("HEALTH_SIDECAR_EXPECTED_OWNER_SENDER_ID"),
        help="Preconfigured partner Weixin sender ID; required for consent",
    )
    parser.add_argument(
        "--expected-viewer-sender-id",
        default=os.getenv("HEALTH_SIDECAR_EXPECTED_VIEWER_SENDER_ID"),
        help="Single preconfigured read-only viewer Weixin sender ID; required",
    )
    parser.add_argument(
        "--allowed-uids",
        default=os.getenv("HEALTH_SIDECAR_ALLOWED_UIDS", ""),
        help="Comma-separated uids allowed to connect. Required.",
    )
    parser.add_argument(
        "--allowed-gids",
        default=os.getenv("HEALTH_SIDECAR_ALLOWED_GIDS", ""),
        help="Comma-separated gids allowed to connect.",
    )
    parser.add_argument(
        "--socket-gid",
        default=os.getenv("HEALTH_SIDECAR_SOCKET_GID"),
        help="Optional socket group ID for Unix group permission checks",
    )
    parser.add_argument(
        "--socket-mode",
        default=os.getenv("HEALTH_SIDECAR_SOCKET_MODE", "660"),
        help="Socket file mode in octal, default 0660",
    )
    parser.add_argument(
        "--listen-backlog",
        type=int,
        default=16,
        help="listen backlog for unix socket",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    allowed_uids = _parse_uids(args.allowed_uids)
    allowed_gids = _parse_gids(args.allowed_gids)
    socket_gid = None if args.socket_gid is None else int(args.socket_gid)
    socket_mode = _parse_octal_mode(args.socket_mode)
    approved_guideline_hosts = _parse_hosts(args.approved_guideline_hosts)
    if not args.memory_projection_path:
        raise HealthSidecarServerError("memory-projection-path-required")
    if not args.receipt_public_key_path:
        raise HealthSidecarServerError("receipt-public-key-path-required")
    if not args.expected_owner_sender_id:
        raise HealthSidecarServerError("expected-owner-sender-id-required")
    if not args.expected_viewer_sender_id:
        raise HealthSidecarServerError("expected-viewer-sender-id-required")
    if args.expected_viewer_sender_id == args.expected_owner_sender_id:
        raise HealthSidecarServerError("viewer-must-not-be-owner")
    if not args.job_authorization_secret_path:
        raise HealthSidecarServerError("job-authorization-secret-path-required")
    try:
        receipt_public_key = Path(args.receipt_public_key_path).read_bytes()
    except OSError as exc:
        raise HealthSidecarServerError(f"failed-read-receipt-public-key:{exc}") from exc
    message_verifier = Ed25519InboundMessageVerifier(receipt_public_key)
    try:
        job_authorization_secret = read_job_authorization_secret(
            args.job_authorization_secret_path
        )
    except Exception as exc:
        raise HealthSidecarServerError(
            "job-authorization-secret-unavailable"
        ) from exc
    try:
        production_ports_factory = ProductionPortsFactory.from_environment(
            memory_projection_path=args.memory_projection_path,
            subject=args.projection_subject,
        )
    except Exception as exc:
        raise HealthSidecarServerError("production-ports-unavailable") from exc
    run_server(
        socket_path=args.socket,
        state_path=args.state_path,
        key_path=args.key_path,
        allowed_uids=allowed_uids,
        allowed_gids=allowed_gids,
        socket_gid=socket_gid,
        socket_mode=socket_mode,
        listen_backlog=args.listen_backlog,
        production_ports_factory=production_ports_factory,
        message_verifier=message_verifier,
        approved_guideline_hosts=approved_guideline_hosts,
        projection_subject=args.projection_subject,
        expected_owner_sender_id=args.expected_owner_sender_id,
        expected_viewer_sender_id=args.expected_viewer_sender_id,
        job_authorization_secret=job_authorization_secret,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

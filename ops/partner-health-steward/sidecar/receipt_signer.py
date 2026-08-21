"""Narrow Ed25519 receipt signer isolated from health data and model tools."""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from .protocol import ACTION_HEALTH_TURN_CONTEXT_READ
from .recording import RECORDING_FEEDBACK_ACTION_BY_STATUS
from .store import HmacInboundMessageVerifier


MAX_FRAME_BYTES = 64 * 1024
SO_PEERCRED = getattr(socket, "SO_PEERCRED", None)
INGRESS_ACTION = "health.profile.message.admit"
ACCESS_ACTIONS = {
    "health.recording.enable",
    "health.recording.stop",
    "health.recording.resume",
    *RECORDING_FEEDBACK_ACTION_BY_STATUS.values(),
    "health.access.grant",
    "health.access.revoke",
    "health.access.read",
    "health.access.analyze",
    "health.profile.read",
    "health.profile.export",
    "health.profile.delete.request",
    "health.profile.delete.confirm",
    "health.profile.owner.transfer",
    "health.profile.owner.recover",
    "health.proactive.pause",
    "health.proactive.resume",
}
INGRESS_ACTIONS = {
    "health.profile.message.admit",
    "health.profile.message.recent",
    ACTION_HEALTH_TURN_CONTEXT_READ,
}
_ACCESS_FIELDS = {
    "action",
    "subject",
    "actor_sender_id",
    "target_sender_id",
    "message_id",
    "message_utc",
}
_INGRESS_FIELDS = {
    "action",
    "subject",
    "sender_id",
    "message_id",
    "message_utc",
    "attempt_utc",
    "message_text",
    "evidence_kind",
    "channel",
    "profile_name",
}


class ReceiptSignerError(RuntimeError):
    """Raised when a receipt request is malformed or unauthorized."""


def _required_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReceiptSignerError(code)
    return value.strip()


def _signature_token(signature: bytes) -> str:
    return base64.urlsafe_b64encode(signature).decode("ascii")


class Ed25519ReceiptSigner:
    """Hold the private key and sign only the two controlled payload shapes."""

    def __init__(self, private_key: bytes) -> None:
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )

            if len(private_key) == 32:
                self._key = Ed25519PrivateKey.from_private_bytes(private_key)
            else:
                loaded = serialization.load_pem_private_key(
                    private_key, password=None
                )
                if not isinstance(loaded, Ed25519PrivateKey):
                    raise ValueError("not-ed25519")
                self._key = loaded
        except Exception as exc:
            raise ReceiptSignerError("invalid-ed25519-private-key") from exc

    def sign_access(
        self,
        *,
        action: str,
        subject: str,
        actor_sender_id: str,
        target_sender_id: str,
        message_id: str,
        message_utc: str,
        pause_until_utc: str | None = None,
    ) -> str:
        action = _required_text(action, "action-required")
        if action not in ACCESS_ACTIONS:
            raise ReceiptSignerError("access-action-not-allowed")
        payload = HmacInboundMessageVerifier._canonical_access(
            action=action,
            subject=_required_text(subject, "subject-required"),
            actor_sender_id=_required_text(
                actor_sender_id, "actor-sender-required"
            ),
            target_sender_id=_required_text(
                target_sender_id, "target-sender-required"
            ),
            message_id=_required_text(message_id, "message-id-required"),
            message_utc=_required_text(message_utc, "message-utc-required"),
            pause_until_utc=pause_until_utc,
        )
        return _signature_token(self._key.sign(payload))

    def sign_ingress(
        self,
        *,
        action: str,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
        channel: str,
        profile_name: str,
        attempt_utc: str | None = None,
    ) -> str:
        action = _required_text(action, "action-required")
        if action not in INGRESS_ACTIONS:
            raise ReceiptSignerError("ingress-action-not-allowed")
        payload = HmacInboundMessageVerifier._canonical_ingress(
            action=action,
            subject=_required_text(subject, "subject-required"),
            sender_id=_required_text(sender_id, "sender-required"),
            message_id=_required_text(message_id, "message-id-required"),
            message_utc=_required_text(message_utc, "message-utc-required"),
            message_text=_required_text(message_text, "message-text-required"),
            evidence_kind=_required_text(evidence_kind, "evidence-kind-required"),
            channel=_required_text(channel, "channel-required"),
            profile_name=_required_text(profile_name, "profile-name-required"),
            attempt_utc=_required_text(
                attempt_utc or message_utc, "attempt-utc-required"
            ),
        )
        return _signature_token(self._key.sign(payload))


def _pack(payload: Mapping[str, Any]) -> bytes:
    body = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if not body or len(body) > MAX_FRAME_BYTES:
        raise ReceiptSignerError("signer-frame-size-invalid")
    return len(body).to_bytes(4, "big") + body


def _recv_exact(conn: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise ReceiptSignerError("signer-frame-truncated")
        data += chunk
    return data


def _read(conn: socket.socket) -> Mapping[str, Any]:
    length = int.from_bytes(_recv_exact(conn, 4), "big")
    if length < 2 or length > MAX_FRAME_BYTES:
        raise ReceiptSignerError("signer-frame-size-invalid")
    try:
        payload = json.loads(_recv_exact(conn, length).decode("utf-8"))
    except Exception as exc:
        raise ReceiptSignerError("signer-request-invalid") from exc
    if not isinstance(payload, Mapping):
        raise ReceiptSignerError("signer-request-invalid")
    return payload


def _peer_pid_uid(conn: socket.socket) -> tuple[int, int]:
    if SO_PEERCRED is None:
        raise ReceiptSignerError("peer-credentials-unavailable")
    try:
        raw = conn.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, _gid = struct.unpack("3i", raw)
    except (OSError, struct.error) as exc:
        raise ReceiptSignerError("peer-credentials-unavailable") from exc
    if pid <= 0 or uid < 0:
        raise ReceiptSignerError("peer-credentials-invalid")
    return pid, uid


class ReceiptSignerClient:
    """Gateway-only socket client; it contains no key material."""

    def __init__(self, socket_path: str, timeout_seconds: float = 2.0) -> None:
        self.socket_path = socket_path
        self.timeout_seconds = timeout_seconds

    def _call(self, operation: str, payload: Mapping[str, Any]) -> str:
        if not hasattr(socket, "AF_UNIX"):
            raise ReceiptSignerError("AF_UNIX-unavailable")
        request = {"operation": operation, "payload": dict(payload)}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(self.timeout_seconds)
            conn.connect(self.socket_path)
            conn.sendall(_pack(request))
            response = _read(conn)
        if response.get("ok") is not True:
            raise ReceiptSignerError(str(response.get("code") or "signer-rejected"))
        token = response.get("token")
        return _required_text(token, "signer-token-invalid")

    def sign_access(self, **payload: Any) -> str:
        return self._call("sign_access", payload)

    def sign_ingress(self, **payload: Any) -> str:
        return self._call("sign_ingress", payload)


class ReceiptSignerServer:
    """Serve signatures only to one exact Gateway main process identity."""

    def __init__(
        self,
        socket_path: str,
        signer: Ed25519ReceiptSigner,
        *,
        allowed_gateway_pid: int | None = None,
        gateway_pid_resolver: Callable[[], int] | None = None,
        allowed_gateway_uid: int,
        socket_mode: int = 0o660,
        socket_gid: int | None = None,
    ) -> None:
        if not hasattr(socket, "AF_UNIX"):
            raise ReceiptSignerError("AF_UNIX-unavailable")
        if (
            (allowed_gateway_pid is None) == (gateway_pid_resolver is None)
            or (allowed_gateway_pid is not None and allowed_gateway_pid <= 0)
            or allowed_gateway_uid < 0
        ):
            raise ReceiptSignerError("gateway-identity-invalid")
        self.socket_path = Path(socket_path)
        self.signer = signer
        self.allowed_gateway_pid = (
            int(allowed_gateway_pid) if allowed_gateway_pid is not None else None
        )
        self.gateway_pid_resolver = gateway_pid_resolver
        self.allowed_gateway_uid = int(allowed_gateway_uid)
        self.socket_mode = int(socket_mode)
        self.socket_gid = socket_gid
        self._socket: socket.socket | None = None
        self._stopped = False

    def serve_once(self) -> None:
        if self._socket is None:
            self._open()
        assert self._socket is not None
        conn, _ = self._socket.accept()
        with conn:
            try:
                pid, uid = _peer_pid_uid(conn)
                expected_pid = (
                    self.gateway_pid_resolver()
                    if self.gateway_pid_resolver is not None
                    else self.allowed_gateway_pid
                )
                if (
                    expected_pid is None
                    or expected_pid <= 0
                    or pid != expected_pid
                    or uid != self.allowed_gateway_uid
                ):
                    raise ReceiptSignerError("gateway-process-not-authorized")
                request = _read(conn)
                operation = request.get("operation")
                payload = request.get("payload")
                if not isinstance(payload, Mapping):
                    raise ReceiptSignerError("signer-request-invalid")
                if operation == "sign_access":
                    fields = set(payload)
                    if (
                        not _ACCESS_FIELDS.issubset(fields)
                        or fields.difference(_ACCESS_FIELDS | {"pause_until_utc"})
                        or (
                            "pause_until_utc" in fields
                            and payload.get("action") != "health.proactive.pause"
                        )
                    ):
                        raise ReceiptSignerError("signer-request-invalid")
                    token = self.signer.sign_access(**dict(payload))
                elif operation == "sign_ingress":
                    if set(payload) != _INGRESS_FIELDS:
                        raise ReceiptSignerError("signer-request-invalid")
                    token = self.signer.sign_ingress(**dict(payload))
                else:
                    raise ReceiptSignerError("signer-operation-not-allowed")
                response = {"ok": True, "token": token}
            except ReceiptSignerError as exc:
                response = {"ok": False, "code": str(exc)}
            except (TypeError, ValueError):
                response = {"ok": False, "code": "signer-request-invalid"}
            conn.sendall(_pack(response))

    def _open(self) -> None:
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(self.socket_path))
        os.chmod(self.socket_path, self.socket_mode)
        if self.socket_gid is not None:
            try:
                os.chown(self.socket_path, -1, int(self.socket_gid))
            except OSError as exc:
                sock.close()
                raise ReceiptSignerError("signer-socket-chown-failed") from exc
        sock.listen(8)
        self._socket = sock

    def serve_forever(self) -> None:
        self._open()
        try:
            while not self._stopped:
                self.serve_once()
        finally:
            self.close()

    def close(self) -> None:
        self._stopped = True
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Partner Gateway receipt signer")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--private-key-path", required=True)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--allowed-gateway-pid", type=int)
    identity.add_argument("--gateway-systemd-unit")
    parser.add_argument("--allowed-gateway-uid", required=True, type=int)
    parser.add_argument("--socket-gid", type=int)
    parser.add_argument("--socket-mode", default="660")
    return parser.parse_args(argv)


def systemd_main_pid_resolver(unit: str) -> Callable[[], int]:
    unit = _required_text(unit, "gateway-systemd-unit-required")

    def resolve() -> int:
        try:
            result = subprocess.run(
                ["systemctl", "show", "--property=MainPID", "--value", unit],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            pid = int(result.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise ReceiptSignerError("gateway-main-pid-unavailable") from exc
        if pid <= 0:
            raise ReceiptSignerError("gateway-main-pid-unavailable")
        return pid

    return resolve


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        private_key = Path(args.private_key_path).read_bytes()
    except OSError as exc:
        raise ReceiptSignerError("private-key-unavailable") from exc
    signer = Ed25519ReceiptSigner(private_key)
    try:
        socket_mode = int(str(args.socket_mode), 8)
    except ValueError as exc:
        raise ReceiptSignerError("signer-socket-mode-invalid") from exc
    ReceiptSignerServer(
        args.socket,
        signer,
        allowed_gateway_pid=args.allowed_gateway_pid,
        gateway_pid_resolver=(
            systemd_main_pid_resolver(args.gateway_systemd_unit)
            if args.gateway_systemd_unit
            else None
        ),
        allowed_gateway_uid=args.allowed_gateway_uid,
        socket_gid=args.socket_gid,
        socket_mode=socket_mode,
    ).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Encrypted sidecar state store used by the health-sidecar vertical spine."""

from __future__ import annotations

import base64
import copy
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol, TypeVar

from job_authorization import JOB_ACTION_AUTHORIZATION_TTL_SECONDS

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no POSIX flock.
    fcntl = None
try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX has no msvcrt locking.
    msvcrt = None


_SCHEMA_VERSION = 1
_SOURCE_LIBRARY_SUBJECT = "__health_source_library__"
_ACCESS_RECEIPT_SUBJECT = "__health_access_receipt_ledger__"
_JOB_ACTION_AUTHORIZATION_SUBJECT = "__health_job_action_authorizations__"
_RECORDING_CONSENT_SUBJECT = "__health_recording_consent__"
_DELETION_CONFIRMATION_SUBJECT = "__health_profile_delete_confirmations__"
_PROFILE_DELIVERY_AUDIT_EVENTS = frozenset(
    {
        "weixin_delivery_sent",
        "weixin_delivery_uncertain",
        "weixin_delivery_rejected",
    }
)
ACCESS_RECEIPT_MAX_AGE_SECONDS = 600
ACCESS_RECEIPT_MAX_FUTURE_SECONDS = 60
DELETION_CONFIRMATION_TTL_SECONDS = 600
RECORDING_ATTEMPT_WRITE_BUDGET_SECONDS = 15
RECORDING_ATTEMPT_LEASE_SECONDS = 16
RECENT_MESSAGE_MAX_AGE = dt.timedelta(hours=72)
BACKUP_RETENTION_DAYS = 30
AUDIT_RETENTION_DAYS = 90
_AUDIT_FORBIDDEN_KEYS = {
    "message",
    "message_text",
    "text",
    "excerpt",
    "profile",
    "candidate",
    "prompt",
    "response",
    "content",
    "health_content",
}
_OPERATIONAL_AUDIT_KEYS = {
    "audit_event_id",
    "subject",
    "local_date",
    "attempt",
    "result",
    "object_id",
    "action",
    "actor_role",
    "actor_id",
    "reason",
    "evidence_ids",
    "recipient_id",
    "task_id",
    "task_count",
    "processed",
    "sent",
    "skipped",
    "failed",
    "deleted",
    "found",
    "verified",
    "deferred",
    "rejected",
    "downloaded",
    "peer_uid",
    "peer_gid",
    "status",
    "heartbeat",
    "retain_until_utc",
    "key_destroyed",
    "projection_removed",
    "grant_id",
    "viewer_sender_id",
    "revoked",
    "granted",
    "failure_code",
    "retry_after_utc",
    "run_id",
    "review_utc",
    "outcome",
}
_AUDIT_ALLOWED_KEYS = _OPERATIONAL_AUDIT_KEYS | {
    "peer_uid",
    "peer_gid",
    "sender_id",
    "message_id",
    "version",
    "bound",
    "staged",
    "remembered",
    "source",
    "card_id",
    "host",
    "version_hash",
    "cancelled_task_count",
    "indefinite",
    "error_type",
    "task_type",
    "task_ids",
    "deferred_task_count",
    "finished_utc",
    "permissions",
    "target_id",
    "evidence_id",
    "version_id",
}
_AUDIT_LIST_KEYS = {"evidence_ids", "task_ids", "permissions"}
_AUDIT_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")
_AUDIT_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:@/+\-]{0,127}$")
_AUDIT_UTC_FIELDS = {
    "retain_until_utc",
    "retry_after_utc",
    "review_utc",
    "finished_utc",
}
_AUDIT_ID_FIELDS = {
    "audit_event_id",
    "subject",
    "object_id",
    "actor_id",
    "recipient_id",
    "task_id",
    "grant_id",
    "viewer_sender_id",
    "sender_id",
    "message_id",
    "evidence_id",
    "version_id",
    "card_id",
    "run_id",
    "target_id",
    "host",
    "version_hash",
}
_AUDIT_BOOL_FIELDS = {
    "bound",
    "staged",
    "remembered",
    "verified",
    "heartbeat",
    "key_destroyed",
    "projection_removed",
    "revoked",
    "granted",
    "indefinite",
    "found",
}
_AUDIT_INT_FIELDS = {
    "version",
    "attempt",
    "task_count",
    "processed",
    "sent",
    "skipped",
    "failed",
    "deleted",
    "deferred",
    "rejected",
    "downloaded",
    "peer_uid",
    "peer_gid",
    "cancelled_task_count",
    "deferred_task_count",
}
_KEY_BYTES = 32
_NONCE_BYTES = 16
_MAC_BYTES = 32
_MutationResult = TypeVar("_MutationResult")


def _harden_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.chmod(0o600)
    except OSError:
        pass


@contextmanager
def _cross_process_file_lock(path: Path) -> Iterator[None]:
    """Serialize append/replace operations that share a sidecar file."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        _harden_file(lock_path)
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class StoreError(RuntimeError):
    """Raised when store encryption/state decoding fails."""


def _validate_audit_record(event: Any, details: Any, *, utc: Any = None) -> None:
    if not isinstance(event, str) or not _AUDIT_TOKEN.fullmatch(event.strip()):
        raise StoreError("audit-content-forbidden")
    if utc is not None:
        if not isinstance(utc, str):
            raise StoreError("audit-content-forbidden")
        try:
            parsed_utc = dt.datetime.fromisoformat(utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise StoreError("audit-content-forbidden") from exc
        if parsed_utc.tzinfo is None:
            raise StoreError("audit-content-forbidden")
    if details is not None and not isinstance(details, Mapping):
        raise StoreError("audit-content-forbidden")
    normalized_details = dict(details or {})
    for key, value in normalized_details.items():
        if not isinstance(key, str):
            raise StoreError("audit-content-forbidden")
        normalized_key = key.strip().lower()
        if (
            key != normalized_key
            or normalized_key in _AUDIT_FORBIDDEN_KEYS
            or normalized_key not in _AUDIT_ALLOWED_KEYS
        ):
            raise StoreError("audit-content-forbidden")
        if isinstance(value, Mapping):
            raise StoreError("audit-content-forbidden")
        if normalized_key in _AUDIT_LIST_KEYS:
            if not isinstance(value, list) or not all(
                isinstance(item, str)
                and item.strip()
                and "\n" not in item
                and "\r" not in item
                and _AUDIT_ID.fullmatch(item)
                for item in value
            ):
                raise StoreError("audit-content-forbidden")
            continue
        if isinstance(value, (list, tuple, set)):
            raise StoreError("audit-content-forbidden")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise StoreError("audit-content-forbidden")
        if normalized_key in _AUDIT_BOOL_FIELDS and not isinstance(value, bool):
            raise StoreError("audit-content-forbidden")
        if normalized_key in _AUDIT_INT_FIELDS and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise StoreError("audit-content-forbidden")
        if not isinstance(value, str):
            continue
        if len(value) > 256 or "\n" in value or "\r" in value:
            raise StoreError("audit-content-forbidden")
        if normalized_key in _AUDIT_ID_FIELDS and not _AUDIT_ID.fullmatch(value):
            raise StoreError("audit-content-forbidden")
        if normalized_key == "reason" and not _AUDIT_TOKEN.fullmatch(value):
            raise StoreError("audit-content-forbidden")
        if normalized_key in _AUDIT_UTC_FIELDS:
            try:
                parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise StoreError("audit-content-forbidden") from exc
            if parsed.tzinfo is None:
                raise StoreError("audit-content-forbidden")
        if normalized_key == "local_date":
            try:
                dt.datetime.strptime(value, "%Y-%m-%d")
            except ValueError as exc:
                raise StoreError("audit-content-forbidden") from exc
        if normalized_key in {
            "action",
            "actor_role",
            "result",
            "status",
            "source",
            "task_type",
            "failure_code",
            "error_type",
        } and not _AUDIT_ID.fullmatch(value):
            raise StoreError("audit-content-forbidden")


class Clock(Protocol):
    """Provide the current UTC time to the store."""

    def now_utc(self) -> dt.datetime:
        ...


class SystemClock:
    """Production clock implementation."""

    def now_utc(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)


class KeyManager(Protocol):
    """Provide master and per-record keys to the store."""

    def load_or_create_master_key(self, key_path: Path) -> bytes:
        ...

    def generate_record_key(self) -> bytes:
        ...

    # Profile-key methods are optional for legacy controlled test doubles;
    # production FileKeyManager implements them so each profile has an
    # independently destroyable data-encryption key.
    def load_profile_key(self, key_dir: Path, subject: str) -> bytes:
        ...

    def load_or_create_profile_key(self, key_dir: Path, subject: str) -> bytes:
        ...

    def destroy_profile_key(self, key_dir: Path, subject: str) -> bool:
        ...


class InboundMessageVerifier(Protocol):
    """Verify an inbound message receipt issued by the trusted gateway."""

    def verify(
        self,
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
        token: str,
    ) -> bool:
        ...

    def verify_owner_binding(
        self, *, subject: str, owner_sender_id: str, token: str
    ) -> bool:
        ...

    def verify_access_receipt(
        self,
        *,
        action: str,
        subject: str,
        actor_sender_id: str,
        target_sender_id: str,
        message_id: str,
        message_utc: str,
        token: str,
        pause_until_utc: str | None = None,
    ) -> bool:
        ...

    def verify_ingress_receipt(
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
        attempt_utc: str,
        token: str,
    ) -> bool:
        ...


class HmacInboundMessageVerifier:
    """HMAC receipt verifier shared by the gateway and sidecar only."""

    def __init__(self, secret: bytes) -> None:
        if not isinstance(secret, bytes) or len(secret) < _KEY_BYTES:
            raise StoreError("inbound-verifier-secret-too-short")
        self._secret = secret

    @staticmethod
    def _canonical(
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
    ) -> bytes:
        try:
            normalized_utc = (
                dt.datetime.fromisoformat(message_utc.replace("Z", "+00:00"))
                .astimezone(dt.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )
        except (ValueError, TypeError):
            normalized_utc = message_utc
        return json.dumps(
            {
                "subject": subject,
                "sender_id": sender_id,
                "message_id": message_id,
                "message_utc": normalized_utc,
                "message_text": message_text,
                "evidence_kind": evidence_kind,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _canonical_owner(*, subject: str, owner_sender_id: str) -> bytes:
        return json.dumps(
            {"subject": subject, "owner_sender_id": owner_sender_id},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _canonical_ingress(
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
    ) -> bytes:
        try:
            parsed_utc = dt.datetime.fromisoformat(message_utc.replace("Z", "+00:00"))
            normalized_utc = (
                parsed_utc.astimezone(dt.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                if parsed_utc.tzinfo is not None
                else message_utc
            )
        except (AttributeError, TypeError, ValueError):
            normalized_utc = message_utc
        raw_attempt_utc = attempt_utc or message_utc
        try:
            parsed_attempt_utc = dt.datetime.fromisoformat(
                raw_attempt_utc.replace("Z", "+00:00")
            )
            normalized_attempt_utc = (
                parsed_attempt_utc.astimezone(dt.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                if parsed_attempt_utc.tzinfo is not None
                else raw_attempt_utc
            )
        except (AttributeError, TypeError, ValueError):
            normalized_attempt_utc = raw_attempt_utc
        return json.dumps(
            {
                "action": action,
                "subject": subject,
                "sender_id": sender_id,
                "message_id": message_id,
                "message_utc": normalized_utc,
                "message_text": message_text,
                "evidence_kind": evidence_kind,
                "channel": channel,
                "profile_name": profile_name,
                "attempt_utc": normalized_attempt_utc,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _canonical_access(
        *,
        action: str,
        subject: str,
        actor_sender_id: str,
        target_sender_id: str,
        message_id: str,
        message_utc: str,
        pause_until_utc: str | None = None,
    ) -> bytes:
        try:
            normalized_utc = (
                dt.datetime.fromisoformat(message_utc.replace("Z", "+00:00"))
                .astimezone(dt.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )
        except (ValueError, TypeError):
            normalized_utc = message_utc
        normalized_pause_until = pause_until_utc
        if pause_until_utc is not None:
            try:
                normalized_pause_until = (
                    dt.datetime.fromisoformat(
                        pause_until_utc.replace("Z", "+00:00")
                    )
                    .astimezone(dt.timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                )
            except (ValueError, TypeError, AttributeError):
                normalized_pause_until = pause_until_utc
        payload = {
            "action": action,
            "subject": subject,
            "actor_sender_id": actor_sender_id,
            "target_sender_id": target_sender_id,
            "message_id": message_id,
            "message_utc": normalized_utc,
        }
        if action == "health.proactive.pause":
            payload["pause_until_utc"] = normalized_pause_until
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def sign_owner_binding(self, *, subject: str, owner_sender_id: str) -> str:
        return hmac.new(
            self._secret,
            self._canonical_owner(subject=subject, owner_sender_id=owner_sender_id),
            hashlib.sha256,
        ).hexdigest()

    def verify_owner_binding(
        self, *, subject: str, owner_sender_id: str, token: str
    ) -> bool:
        if not isinstance(token, str) or not token:
            return False
        expected = self.sign_owner_binding(
            subject=subject, owner_sender_id=owner_sender_id
        )
        return hmac.compare_digest(expected, token)

    def sign_access_receipt(
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
        return hmac.new(
            self._secret,
            self._canonical_access(
                action=action,
                subject=subject,
                actor_sender_id=actor_sender_id,
                target_sender_id=target_sender_id,
                message_id=message_id,
                message_utc=message_utc,
                pause_until_utc=pause_until_utc,
            ),
            hashlib.sha256,
        ).hexdigest()

    def sign_ingress_receipt(
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
        return hmac.new(
            self._secret,
            self._canonical_ingress(
                action=action,
                subject=subject,
                sender_id=sender_id,
                message_id=message_id,
                message_utc=message_utc,
                message_text=message_text,
                evidence_kind=evidence_kind,
                channel=channel,
                profile_name=profile_name,
                attempt_utc=attempt_utc,
            ),
            hashlib.sha256,
        ).hexdigest()

    def verify_ingress_receipt(
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
        token: str,
    ) -> bool:
        if not isinstance(token, str) or not token:
            return False
        expected = self.sign_ingress_receipt(
            action=action,
            subject=subject,
            sender_id=sender_id,
            message_id=message_id,
            message_utc=message_utc,
            message_text=message_text,
            evidence_kind=evidence_kind,
            channel=channel,
            profile_name=profile_name,
            attempt_utc=attempt_utc,
        )
        return hmac.compare_digest(expected, token)

    def verify_access_receipt(
        self,
        *,
        action: str,
        subject: str,
        actor_sender_id: str,
        target_sender_id: str,
        message_id: str,
        message_utc: str,
        token: str,
        pause_until_utc: str | None = None,
    ) -> bool:
        if not isinstance(token, str) or not token:
            return False
        expected = self.sign_access_receipt(
            action=action,
            subject=subject,
            actor_sender_id=actor_sender_id,
            target_sender_id=target_sender_id,
            message_id=message_id,
            message_utc=message_utc,
            pause_until_utc=pause_until_utc,
        )
        return hmac.compare_digest(expected, token)

    def sign(
        self,
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
    ) -> str:
        digest = hmac.new(
            self._secret,
            self._canonical(
                subject=subject,
                sender_id=sender_id,
                message_id=message_id,
                message_utc=message_utc,
                message_text=message_text,
                evidence_kind=evidence_kind,
            ),
            hashlib.sha256,
        ).hexdigest()
        return digest

    def verify(
        self,
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
        token: str,
    ) -> bool:
        if not isinstance(token, str) or not token:
            return False
        expected = self.sign(
            subject=subject,
            sender_id=sender_id,
            message_id=message_id,
            message_utc=message_utc,
            message_text=message_text,
            evidence_kind=evidence_kind,
        )
        return hmac.compare_digest(expected, token)


class Ed25519InboundMessageVerifier:
    """Verify gateway receipts with a public key held by the sidecar."""

    def __init__(self, public_key: bytes) -> None:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            self._key = Ed25519PublicKey.from_public_bytes(public_key)
        except Exception as exc:
            raise StoreError("invalid-ed25519-public-key") from exc

    @staticmethod
    def _decode_token(token: str) -> bytes:
        try:
            return base64.urlsafe_b64decode(token.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise StoreError("invalid-inbound-receipt") from exc

    def _verify_bytes(self, payload: bytes, token: str) -> bool:
        try:
            self._key.verify(self._decode_token(token), payload)
        except Exception:
            return False
        return True

    def verify(
        self,
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
        token: str,
    ) -> bool:
        return self._verify_bytes(
            HmacInboundMessageVerifier._canonical(
                subject=subject,
                sender_id=sender_id,
                message_id=message_id,
                message_utc=message_utc,
                message_text=message_text,
                evidence_kind=evidence_kind,
            ),
            token,
        )

    def verify_owner_binding(
        self, *, subject: str, owner_sender_id: str, token: str
    ) -> bool:
        return self._verify_bytes(
            HmacInboundMessageVerifier._canonical_owner(
                subject=subject, owner_sender_id=owner_sender_id
            ),
            token,
        )

    def verify_access_receipt(
        self,
        *,
        action: str,
        subject: str,
        actor_sender_id: str,
        target_sender_id: str,
        message_id: str,
        message_utc: str,
        token: str,
        pause_until_utc: str | None = None,
    ) -> bool:
        return self._verify_bytes(
            HmacInboundMessageVerifier._canonical_access(
                action=action,
                subject=subject,
                actor_sender_id=actor_sender_id,
                target_sender_id=target_sender_id,
                message_id=message_id,
                message_utc=message_utc,
                pause_until_utc=pause_until_utc,
            ),
            token,
        )

    def verify_ingress_receipt(
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
        token: str,
    ) -> bool:
        return self._verify_bytes(
            HmacInboundMessageVerifier._canonical_ingress(
                action=action,
                subject=subject,
                sender_id=sender_id,
                message_id=message_id,
                message_utc=message_utc,
                message_text=message_text,
                evidence_kind=evidence_kind,
                channel=channel,
                profile_name=profile_name,
                attempt_utc=attempt_utc,
            ),
            token,
        )

class FileKeyManager:
    """Production key manager that stores only the master key on disk."""

    def load_or_create_master_key(self, key_path: Path) -> bytes:
        if key_path.exists():
            try:
                raw = key_path.read_bytes()
            except OSError as exc:
                raise StoreError(f"failed-read-key:{exc}") from exc
            if len(raw) != _KEY_BYTES:
                raise StoreError("stored-key-has-wrong-length")
            _harden_file(key_path)
            return raw

        key = secrets.token_bytes(_KEY_BYTES)
        with open(key_path, "wb") as key_file:
            key_file.write(key)
        _harden_file(key_path)
        return key

    def generate_record_key(self) -> bytes:
        return secrets.token_bytes(_KEY_BYTES)

    @staticmethod
    def _profile_key_path(key_dir: Path, subject: str) -> Path:
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        return key_dir / f"{digest}.key"

    def load_profile_key(self, key_dir: Path, subject: str) -> bytes:
        path = self._profile_key_path(key_dir, subject)
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise StoreError("profile-key-destroyed") from exc
        except OSError as exc:
            raise StoreError(f"failed-read-profile-key:{exc}") from exc
        if len(raw) != _KEY_BYTES:
            raise StoreError("stored-profile-key-has-wrong-length")
        _harden_file(path)
        return raw

    def load_or_create_profile_key(self, key_dir: Path, subject: str) -> bytes:
        key_dir.mkdir(parents=True, exist_ok=True)
        path = self._profile_key_path(key_dir, subject)
        if path.exists():
            return self.load_profile_key(key_dir, subject)
        key = secrets.token_bytes(_KEY_BYTES)
        try:
            with open(path, "xb") as key_file:
                key_file.write(key)
        except FileExistsError:
            return self.load_profile_key(key_dir, subject)
        _harden_file(path)
        return key

    def destroy_profile_key(self, key_dir: Path, subject: str) -> bool:
        path = self._profile_key_path(key_dir, subject)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise StoreError(f"failed-destroy-profile-key:{exc}") from exc
        return True


class HealthSidecarStore:
    def __init__(
        self,
        store_path: str | os.PathLike[str],
        key_path: str | os.PathLike[str],
        clock: Clock | None = None,
        key_manager: KeyManager | None = None,
        message_verifier: InboundMessageVerifier | None = None,
        expected_owner_sender_id: str | None = None,
        expected_viewer_sender_id: str | None = None,
    ) -> None:
        self.store_path = Path(store_path)
        self.key_path = Path(key_path)
        self.audit_path = self.store_path.with_suffix(".audit.log")
        self.backup_dir = self.store_path.parent / "backups"
        self.profile_key_dir = self.store_path.parent / "profile-keys"
        self.clock = clock or SystemClock()
        self.key_manager = key_manager or FileKeyManager()
        self._state_lock = threading.RLock()
        self._audit_lock = threading.RLock()
        self._source_library_lock = threading.RLock()
        self._recent_message_lock = threading.RLock()
        self._recording_attempt_condition = threading.Condition(threading.RLock())
        self._recording_attempts: dict[str, tuple[str, float]] = {}
        self._recording_stopping_subjects: set[str] = set()
        self._staged_profile_messages: dict[str, list[dict[str, Any]]] = {}
        # Latest owner messages are an ephemeral render input.  They are
        # deliberately kept outside encrypted profile state and capped at
        # three entries per subject.
        self._recent_profile_messages: dict[str, list[dict[str, Any]]] = {}
        self._profile_key_cache: dict[str, bytes] = {}
        self._destroyed_profile_keys: set[str] = set()
        self._ensure_parent(self.store_path)
        self._ensure_parent(self.key_path)
        self._ensure_parent(self.audit_path)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.profile_key_dir.mkdir(parents=True, exist_ok=True)
        self.key = self.key_manager.load_or_create_master_key(self.key_path)
        # A direct in-process store gets an ephemeral verifier for tests and
        # local domain use; the daemon entrypoint requires an explicit,
        # separately provisioned gateway verifier and never uses this fallback.
        self.message_verifier = message_verifier or HmacInboundMessageVerifier(
            secrets.token_bytes(_KEY_BYTES)
        )
        self.expected_owner_sender_id = str(expected_owner_sender_id or "").strip()
        self.expected_viewer_sender_id = str(expected_viewer_sender_id or "").strip()
        if (
            self.expected_owner_sender_id
            and self.expected_owner_sender_id == self.expected_viewer_sender_id
        ):
            raise StoreError("viewer-must-not-be-owner")
        self._init_db()
        # A committed deletion is an irreversible transaction: once its
        # profile key is gone, an interrupted cleanup must converge to the
        # deleted state before any profile row is decoded or migrated.
        self._recover_committed_profile_deletions()
        self._migrate_legacy_profile_storage()

    @staticmethod
    def _ensure_parent(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def _now_utc(self) -> dt.datetime:
        now = self.clock.now_utc()
        if now.tzinfo is None:
            raise StoreError("clock-must-return-aware-utc")
        return now.astimezone(dt.timezone.utc)

    def now_utc(self) -> dt.datetime:
        """Return the injected UTC clock value for domain operations."""
        return self._now_utc()

    def remember_recent_profile_message(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
    ) -> None:
        """Keep at most three recent owner messages in process memory only."""
        now = self._now_utc()
        with self._recent_message_lock:
            messages = self._recent_profile_messages.setdefault(subject, [])
            messages[:] = [
                item
                for item in messages
                if item.get("message_id") != message_id
                and self._recent_message_is_live(item, now)
            ]
            messages.append(
                {
                    "message_id": message_id,
                    "sender_id": sender_id,
                    "message_utc": message_utc,
                    "text": message_text,
                }
            )
            del messages[:-3]

    def recent_profile_messages(
        self, subject: str, sender_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return a copy of the bounded ephemeral message window."""
        with self._recent_message_lock:
            messages = self._recent_profile_messages.get(subject, [])
            now = self._now_utc()
            messages[:] = [
                item for item in messages if self._recent_message_is_live(item, now)
            ]
            return [
                copy.deepcopy(item)
                for item in messages
                if sender_id is None or item.get("sender_id") == sender_id
            ]

    @staticmethod
    def _recent_message_is_live(
        item: Mapping[str, Any], now: dt.datetime
    ) -> bool:
        try:
            observed = dt.datetime.fromisoformat(
                str(item.get("message_utc", "")).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return False
        if observed.tzinfo is None:
            return False
        observed = observed.astimezone(dt.timezone.utc)
        return now - observed <= RECENT_MESSAGE_MAX_AGE

    def _apply_owner_reply_to_profile(
        self,
        profile: Mapping[str, Any],
        sender_id: str,
        message_utc: str,
    ) -> tuple[dict[str, Any], bool]:
        """Apply content-free reply metadata to an already loaded profile."""
        from .profile import ProfileStoreError, _profile_from_status

        def parse_aware_utc(value: Any, code: str) -> dt.datetime:
            if not isinstance(value, str) or not value.strip():
                raise ProfileStoreError(code)
            try:
                parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except (TypeError, ValueError) as exc:
                raise ProfileStoreError(code) from exc
            if parsed.tzinfo is None:
                raise ProfileStoreError(code)
            return parsed.astimezone(dt.timezone.utc)

        try:
            reply_time = parse_aware_utc(message_utc, "invalid-owner-reply-time")
        except ProfileStoreError as exc:
            raise ProfileStoreError("invalid-owner-reply-time") from exc

        updated_profile = _profile_from_status(profile)
        if updated_profile.get("owner_sender_id") != sender_id:
            raise StoreError("non-owner-message")
        changed = False
        tasks = copy.deepcopy(list(updated_profile.get("tasks", [])))
        for index, item in enumerate(tasks):
            if not isinstance(item, Mapping) or item.get("status") != "sent":
                continue
            sent_raw = item.get("sent_utc")
            try:
                sent_time = parse_aware_utc(sent_raw, "invalid-task-sent-time")
            except ProfileStoreError:
                continue
            if reply_time <= sent_time or item.get("owner_reply_utc"):
                continue
            updated = dict(item)
            updated["owner_reply_utc"] = reply_time.replace(
                microsecond=0
            ).isoformat()
            tasks[index] = updated
            changed = True
        if changed:
            updated_profile["tasks"] = tasks
        return updated_profile, changed

    def _record_owner_reply(
        self, subject: str, sender_id: str, message_utc: str
    ) -> None:
        """Mark sent proactive tasks answered after their outbound handoff.

        The body is intentionally not persisted.  A verified owner message is
        enough to stop treating an earlier proactive contact as unanswered;
        the message remains available only in the bounded ephemeral window.
        """

        existing = self.read_subject_status(subject, _allow_profile_state=True)
        if existing is None:
            return
        _, changed = self._apply_owner_reply_to_profile(
            existing, sender_id, message_utc
        )
        if not changed:
            return

        def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], None]:
            updated, _ = self._apply_owner_reply_to_profile(
                current, sender_id, message_utc
            )
            return updated, None

        self.mutate_subject_status(subject, mutate)

    def verify_inbound_message(
        self,
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
        token: str,
    ) -> bool:
        return self.message_verifier.verify(
            subject=subject,
            sender_id=sender_id,
            message_id=message_id,
            message_utc=message_utc,
            message_text=message_text,
            evidence_kind=evidence_kind,
            token=token,
        )

    def verify_owner_binding(
        self, *, subject: str, owner_sender_id: str, token: str
    ) -> bool:
        return self.message_verifier.verify_owner_binding(
            subject=subject, owner_sender_id=owner_sender_id, token=token
        )

    def _init_db(self) -> None:
        with self._open_db(mutable=True):
            pass

    def _mark_profile_deletion_committed(
        self,
        subject: str,
        sender_id: str,
        *,
        action: str,
        clear_recording_consent: bool,
    ) -> None:
        """Durably record deletion intent before removing the profile key.

        The state database and the profile-key directory cannot share one
        filesystem transaction.  This content-free journal turns a crash
        between those two operations into an idempotent startup recovery
        rather than an undecryptable half-deleted profile.
        """
        committed_utc = self._now_utc().astimezone(dt.timezone.utc).isoformat()
        with self._open_db(mutable=True) as conn:
            conn.execute(
                """
                INSERT INTO profile_deletion_tombstones(
                    subject,owner_sender_id,action,clear_recording_consent,committed_utc
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(subject) DO UPDATE SET
                    owner_sender_id=excluded.owner_sender_id,
                    action=excluded.action,
                    clear_recording_consent=excluded.clear_recording_consent,
                    committed_utc=excluded.committed_utc;
                """,
                (
                    subject,
                    sender_id,
                    action,
                    1 if clear_recording_consent else 0,
                    committed_utc,
                ),
            )

    def _committed_profile_deletions(self) -> list[tuple[str, str, str, bool]]:
        with self._open_db(mutable=False) as conn:
            rows = conn.execute(
                """
                SELECT subject,owner_sender_id,action,clear_recording_consent
                FROM profile_deletion_tombstones
                ORDER BY subject;
                """
            ).fetchall()
        committed: list[tuple[str, str, str, bool]] = []
        for row in rows:
            subject = str(row[0] or "").strip()
            sender_id = str(row[1] or "").strip()
            action = str(row[2] or "").strip()
            if (
                not subject
                or not sender_id
                or action != "health.profile.delete.confirm"
                or int(row[3]) not in (0, 1)
            ):
                raise StoreError("profile-deletion-tombstone-corrupt")
            committed.append((subject, sender_id, action, bool(row[3])))
        return committed

    def _recover_committed_profile_deletions(self) -> None:
        """Finish any deletion whose durable intent survived a crash."""
        with self._state_lock:
            for subject, sender_id, action, clear_recording_consent in (
                self._committed_profile_deletions()
            ):
                self._finalize_committed_profile_deletion(
                    subject,
                    sender_id,
                    action=action,
                    clear_recording_consent=clear_recording_consent,
                )

    def _remove_committed_profile_state(
        self, subject: str, *, clear_recording_consent: bool
    ) -> None:
        """Remove raw rows without ever attempting to decrypt a dead key."""
        with self._open_db(mutable=True) as conn:
            conn.execute("DELETE FROM state_records WHERE subject=?;", (subject,))
            if clear_recording_consent:
                conn.execute(
                    "DELETE FROM state_records WHERE subject=?;",
                    (_RECORDING_CONSENT_SUBJECT,),
                )

    def _clear_profile_deletion_request(self, subject: str) -> None:
        def clear_request(
            current: Mapping[str, Any],
        ) -> tuple[Mapping[str, Any], None]:
            active = self._active_deletion_requests(
                current, self._now_utc().astimezone(dt.timezone.utc)
            )
            active.pop(subject, None)
            return {
                "delete_confirmation_schema_version": 1,
                "requests": active,
            }, None

        self.mutate_subject_status(_DELETION_CONFIRMATION_SUBJECT, clear_request)

    def _clear_profile_deletion_tombstone(self, subject: str) -> None:
        with self._open_db(mutable=True) as conn:
            conn.execute(
                "DELETE FROM profile_deletion_tombstones WHERE subject=?;", (subject,)
            )

    def _finalize_committed_profile_deletion(
        self,
        subject: str,
        sender_id: str,
        *,
        action: str,
        clear_recording_consent: bool,
    ) -> Mapping[str, Any]:
        """Idempotently finish a deletion already committed in the journal."""
        destroyed_now = self._destroy_profile_key(subject)
        key_path = self.profile_key_dir / f"{self._profile_key_id(subject)}.key"
        if not destroyed_now and key_path.exists():
            # A key manager that reports failure while retaining the key must
            # leave the journal in place and keep all delivery paths blocked.
            raise StoreError("profile-key-destruction-unconfirmed")
        self._remove_committed_profile_state(
            subject, clear_recording_consent=clear_recording_consent
        )
        self._staged_profile_messages.pop(subject, None)
        self._recent_profile_messages.pop(subject, None)
        self._rewrite_audit_after_profile_delete(
            subject, sender_id, True, action=action
        )
        result: dict[str, Any] = {
            "subject": subject,
            "deleted": True,
            "key_destroyed": True,
        }
        try:
            self._clear_profile_deletion_request(subject)
            self._clear_profile_deletion_tombstone(subject)
        except Exception:
            # The profile/key/audit destruction is already complete.  Preserve
            # the tombstone for a later startup/status retry, but never turn a
            # cleanup write outage into permission to reopen delivery.
            result["confirmation_cleanup_pending"] = True
        return result

    def _migrate_legacy_profile_storage(self) -> None:
        """Move pre-Ticket-07 profile rows behind destroyable profile keys.

        Older state files used a master-wrapped record key for every subject.
        Leaving those rows in place would let a deleted profile reappear from
        an old backup after its profile key was destroyed.  Startup therefore
        migrates both the live database and every encrypted backup before the
        store accepts requests.  A deletion proof is treated as authoritative
        for old backups: any stale copy of that subject is removed from the
        backup rather than being re-keyed and resurrected.
        """
        with self._state_lock:
            deleted_subjects = self._deleted_profile_subjects()
            with self._open_db(mutable=True) as conn:
                self._migrate_legacy_profile_rows(conn, deleted_subjects)

            for backup in sorted(self.backup_dir.glob(f"{self.store_path.name}.*.bak")):
                self._migrate_legacy_profile_backup(backup, deleted_subjects)

    def _deleted_profile_subjects(self) -> set[str]:
        deleted: set[str] = set()
        for event in self.read_audit_events(limit=None):
            if event.get("event") != "profile_deleted":
                continue
            details = event.get("details")
            if isinstance(details, Mapping) and isinstance(details.get("subject"), str):
                deleted.add(str(details["subject"]).strip())
        return {subject for subject in deleted if subject}

    def _migrate_legacy_profile_backup(
        self, backup: Path, deleted_subjects: set[str]
    ) -> None:
        try:
            encrypted = backup.read_bytes()
            plain = self._decrypt_database_blob(encrypted)
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            try:
                conn.deserialize(plain)
                self._ensure_schema(conn)
                changed = self._migrate_legacy_profile_rows(conn, deleted_subjects)
                if changed:
                    conn.commit()
                    self._atomic_write_encrypted(
                        self._encrypt_database_blob(conn.serialize()), backup
                    )
            finally:
                conn.close()
        except FileNotFoundError:
            return
        except StoreError:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise StoreError(f"legacy-profile-backup-migration-failed:{exc}") from exc

    def _migrate_legacy_profile_rows(
        self, conn: sqlite3.Connection, deleted_subjects: set[str]
    ) -> bool:
        changed = False
        rows = conn.execute(
            "SELECT subject,schema_version,key_scope,wrapped_key,nonce,mac,payload "
            "FROM state_records WHERE key_scope='master';"
        ).fetchall()
        for row in rows:
            row_dict = {
                "subject": str(row[0]),
                "schema_version": str(row[1]),
                "key_scope": str(row[2]),
                "wrapped_key": row[3],
                "nonce": row[4],
                "mac": row[5],
                "payload": row[6],
            }
            try:
                record_data = self._decrypt_record(row_dict)
            except StoreError as exc:
                raise StoreError(
                    f"legacy-profile-migration-failed:{row_dict['subject']}:{exc}"
                ) from exc
            status = record_data.get("status")
            if not isinstance(status, Mapping) or status.get("profile_schema_version") != 1:
                continue

            subject = row_dict["subject"].strip()
            if subject in deleted_subjects:
                conn.execute("DELETE FROM state_records WHERE subject=?;", (subject,))
                changed = True
                continue

            rec_key = self._load_profile_key(subject, create=True)
            envelope = json.dumps(record_data, ensure_ascii=False, sort_keys=True)
            cipher_blob, nonce, mac = self._encrypt_payload(envelope, rec_key)
            conn.execute(
                """
                UPDATE state_records
                SET key_scope='profile', wrapped_key=?, nonce=?, mac=?, payload=?
                WHERE subject=?;
                """,
                (
                    f"profile:{self._profile_key_id(subject)}",
                    base64.urlsafe_b64encode(nonce).decode("ascii"),
                    base64.urlsafe_b64encode(mac).decode("ascii"),
                    base64.urlsafe_b64encode(cipher_blob).decode("ascii"),
                    subject,
                ),
            )
            changed = True
        return changed

    def read_subject_status(
        self,
        subject: str,
        _allow_profile_state: bool = False,
    ) -> Mapping[str, Any] | None:
        """Return decrypted status payload for a subject, or None when not found."""
        if not _allow_profile_state:
            if subject.strip() == _SOURCE_LIBRARY_SUBJECT:
                raise StoreError("source-library-state-protected")
            if subject.strip() == _ACCESS_RECEIPT_SUBJECT:
                raise StoreError("access-receipt-state-protected")
            if subject.strip() == _RECORDING_CONSENT_SUBJECT:
                raise StoreError("recording-consent-state-protected")
            if subject.strip() == _DELETION_CONFIRMATION_SUBJECT:
                raise StoreError("deletion-confirmation-state-protected")
        with self._open_db(mutable=False) as conn:
            row = self._get_record(conn, subject)
            if row is None:
                return None

            try:
                record_data = self._decrypt_record(row)
            except StoreError as exc:
                raise StoreError(f"record-decode-failed:{exc}") from exc

            if record_data.get("schema_version") != _SCHEMA_VERSION:
                raise StoreError("unsupported-schema-version")
            if record_data.get("subject") != subject:
                return None
            status = dict(record_data["status"])
            if status.get("profile_schema_version") == 1 and not _allow_profile_state:
                raise StoreError("profile-state-protected")
            return status

    def write_subject_status(
        self,
        subject: str,
        status: Mapping[str, Any],
        _allow_profile_state: bool = False,
        _additional_audit_events: tuple[
            tuple[str, Mapping[str, Any]], ...
        ] = (),
        _commit_validator: Callable[[], None] | None = None,
    ) -> int:
        """Write state and its audit batch, rolling state back on failure."""
        with self._state_lock:
            previous_blob = (
                self.store_path.read_bytes() if self.store_path.exists() else None
            )
            return self._write_subject_status_locked(
                subject,
                status,
                _allow_profile_state=_allow_profile_state,
                _additional_audit_events=_additional_audit_events,
                _previous_blob=previous_blob,
                _commit_validator=_commit_validator,
            )

    def _write_subject_status_locked(
        self,
        subject: str,
        status: Mapping[str, Any],
        *,
        _allow_profile_state: bool,
        _additional_audit_events: tuple[
            tuple[str, Mapping[str, Any]], ...
        ],
        _previous_blob: bytes | None,
        _commit_validator: Callable[[], None] | None,
    ) -> int:
        """Persist one state revision while the caller holds the state lock."""
        if not isinstance(status, Mapping):
            raise StoreError("status-must-be-object")

        if not _allow_profile_state:
            if subject.strip() == _SOURCE_LIBRARY_SUBJECT:
                raise StoreError("source-library-state-protected")
            if subject.strip() == _ACCESS_RECEIPT_SUBJECT:
                raise StoreError("access-receipt-state-protected")
            if subject.strip() == _RECORDING_CONSENT_SUBJECT:
                raise StoreError("recording-consent-state-protected")
            if subject.strip() == _DELETION_CONFIRMATION_SUBJECT:
                raise StoreError("deletion-confirmation-state-protected")

        if not _allow_profile_state and status.get("profile_schema_version") == 1:
            raise StoreError("profile-state-protected")
        if not _allow_profile_state:
            current = self.read_subject_status(subject, _allow_profile_state=True)
            if current is not None and current.get("profile_schema_version") == 1:
                raise StoreError("profile-state-protected")

        self._make_backup()
        now = self._now_utc().replace(microsecond=0).isoformat()
        subject = subject.strip()

        with self._open_db(mutable=True) as conn:
            cursor = conn.execute(
                "SELECT version FROM state_records WHERE subject=?;",
                (subject,),
            )
            row = cursor.fetchone()
            prev_version = int(row[0]) if row else 0
            version = prev_version + 1
            global_version = int(
                conn.execute(
                    "SELECT v FROM metadata WHERE k='global_version';"
                ).fetchone()[0]
            ) + 1

            payload_obj = {
                "schema_version": _SCHEMA_VERSION,
                "subject": subject,
                "updated_utc": now,
                "version": version,
                "status": dict(status),
            }
            envelope = json.dumps(payload_obj, ensure_ascii=False, sort_keys=True)
            profile_record = status.get("profile_schema_version") == 1
            if profile_record:
                rec_key = self._load_profile_key(subject, create=True)
                key_scope = "profile"
                wrapped_key = f"profile:{self._profile_key_id(subject)}"
            else:
                rec_key = self._load_or_generate_record_key()
                key_scope = "master"
                wrapped_key = self._wrap_record_key(rec_key)
            cipher_blob, nonce, mac = self._encrypt_payload(envelope, rec_key)
            payload_b64 = base64.urlsafe_b64encode(cipher_blob).decode("ascii")

            conn.execute(
                """
                INSERT INTO state_records(subject,schema_version,version,updated_utc,key_scope,wrapped_key,nonce,mac,payload)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(subject) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    version=excluded.version,
                    updated_utc=excluded.updated_utc,
                    key_scope=excluded.key_scope,
                    wrapped_key=excluded.wrapped_key,
                    nonce=excluded.nonce,
                    mac=excluded.mac,
                    payload=excluded.payload;
                """,
                (
                    subject,
                    _SCHEMA_VERSION,
                    version,
                    now,
                    key_scope,
                    wrapped_key,
                    base64.urlsafe_b64encode(nonce).decode("ascii"),
                    base64.urlsafe_b64encode(mac).decode("ascii"),
                    payload_b64,
                ),
            )
            conn.execute(
                "UPDATE metadata SET v=? WHERE k='global_version';",
                (str(global_version),),
            )
            conn.execute(
                "UPDATE metadata SET v=? WHERE k='updated_utc';",
                (now,),
            )
            conn.commit()

        try:
            self._append_audit_events(
                (
                    (
                        "status_write",
                        {
                            "subject": subject,
                            "version": version,
                        },
                    ),
                    *_additional_audit_events,
                ),
                post_append_validator=_commit_validator,
            )
        except Exception:
            try:
                if _previous_blob is None:
                    self.store_path.unlink(missing_ok=True)
                    self._fsync_parent_directory()
                else:
                    self._atomic_write_encrypted(_previous_blob)
            except Exception as rollback_exc:
                raise StoreError("state-audit-rollback-failed") from rollback_exc
            raise
        return version

    def mutate_subject_status(
        self,
        subject: str,
        mutator: Callable[[Mapping[str, Any]], tuple[Mapping[str, Any], _MutationResult]],
        *,
        audit_builder: Callable[
            [_MutationResult], tuple[tuple[str, Mapping[str, Any]], ...]
        ]
        | None = None,
        commit_validator: Callable[[], None] | None = None,
    ) -> _MutationResult:
        """Atomically derive and persist a subject status through a public seam."""
        with self._state_lock:
            current = self.read_subject_status(subject, _allow_profile_state=True) or {}
            updated, result = mutator(dict(current))
            if not isinstance(updated, Mapping):
                raise StoreError("status-mutator-must-return-object")
            additional_events = audit_builder(result) if audit_builder else ()
            self.write_subject_status(
                subject,
                updated,
                _allow_profile_state=True,
                _additional_audit_events=additional_events,
                _commit_validator=commit_validator,
            )
            return result

    def read_source_library_state(self) -> Mapping[str, Any] | None:
        """Read the encrypted source-library metadata through its private seam."""
        return self.read_subject_status(
            _SOURCE_LIBRARY_SUBJECT, _allow_profile_state=True
        )

    @contextmanager
    def source_library_lock(self) -> Iterator[None]:
        """Serialize source-cache reads, limits, and commits across socket workers."""
        with self._source_library_lock:
            yield

    @contextmanager
    def dispatch_lock(self) -> Iterator[None]:
        """Serialize the final authorization check and channel hand-off.

        The dispatcher may spend time rendering outside this lock, but the
        last live-state check and the controlled channel call are one critical
        section.  This prevents a concurrent pause/revocation from racing a
        send, while keeping the public store seam testable.
        """
        with self._state_lock:
            yield

    def mutate_source_library_state(
        self,
        mutator: Callable[[Mapping[str, Any]], tuple[Mapping[str, Any], _MutationResult]],
    ) -> _MutationResult:
        """Atomically update source-library metadata without exposing generic status RPC."""
        return self.mutate_subject_status(_SOURCE_LIBRARY_SUBJECT, mutator)

    def bind_profile_owner(
        self, subject: str, owner_sender_id: str, verification_token: str
    ) -> bool:
        from .profile import bind_profile_owner

        return bind_profile_owner(self, subject, owner_sender_id, verification_token)

    def _recording_consent_state(
        self, subject: str
    ) -> Mapping[str, Any] | None:
        state = self.read_subject_status(
            _RECORDING_CONSENT_SUBJECT, _allow_profile_state=True
        )
        if not (
            isinstance(state, Mapping)
            and state.get("recording_consent_schema_version") == 1
            and state.get("profile_subject") == subject
        ):
            return None
        owner_sender_id = state.get("owner_sender_id")
        if not isinstance(owner_sender_id, str) or not owner_sender_id.strip():
            return None
        return dict(state)

    def _owner_recovery_verifier(self, subject: str, recovery_code: str) -> str:
        """Return a keyed verifier without retaining the one-time recovery code."""
        payload = (
            f"health-owner-recovery:v1:{subject}:".encode("utf-8")
            + recovery_code.encode("ascii")
        )
        return hmac.new(
            self.key_manager.load_or_create_master_key(self.key_path),
            payload,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _new_owner_recovery_code() -> str:
        """Generate a 256-bit URL-safe secret for one owner-only display."""
        return secrets.token_urlsafe(32)

    def health_recording_status(self, subject: str, sender_id: str) -> str:
        """Return the owner's recording lifecycle without leaking it to others."""
        subject = str(subject or "").strip()
        sender_id = str(sender_id or "").strip()
        if not subject or not sender_id:
            return "not_enabled"
        state = self._recording_consent_state(subject)
        if state is None:
            if subject in self._deleted_profile_subjects():
                return "not_enabled"
            return (
                "recording_disabled"
                if sender_id == self.expected_owner_sender_id
                else "not_enabled"
            )
        if state.get("owner_sender_id") != sender_id:
            return "not_enabled"
        consent_status = state.get("recording_status")
        if consent_status is None:
            consent_status = (
                "recording_enabled" if state.get("enabled") is True else "not_enabled"
            )
        if consent_status != "recording_enabled":
            return str(consent_status)
        profile = self.read_subject_status(subject, _allow_profile_state=True)
        # Explicit recording consent deliberately precedes the first profile
        # write.  Permanent deletion clears that consent record below, so a
        # missing profile is valid only during that initial consented state.
        if profile is None:
            return "recording_enabled"
        if not (
            isinstance(profile, Mapping)
            and profile.get("profile_schema_version") == 1
            and profile.get("owner_sender_id") == sender_id
        ):
            return "not_enabled"
        if profile.get("recording_status") == "recording_stopped":
            return "recording_stopped"
        return "recording_enabled"

    def health_recording_enabled(self, subject: str, sender_id: str) -> bool:
        """Return true only while the configured owner explicitly allows writes."""
        return self.health_recording_status(subject, sender_id) == "recording_enabled"

    def begin_recording_attempt(self, subject: str, sender_id: str) -> str:
        """Lease one bounded classification attempt against stop-recording."""
        subject = str(subject or "").strip()
        sender_id = str(sender_id or "").strip()
        if not subject or not sender_id:
            raise StoreError("recording-attempt-fields-required")
        with self._recording_attempt_condition:
            self._prune_recording_attempts()
            if subject in self._recording_stopping_subjects:
                raise StoreError("recording-not-enabled")
            with self._state_lock:
                if not self.health_recording_enabled(subject, sender_id):
                    raise StoreError("recording-not-enabled")
                lease_id = f"recording-attempt-{secrets.token_hex(16)}"
                self._recording_attempts[lease_id] = (
                    subject,
                    time.monotonic() + RECORDING_ATTEMPT_LEASE_SECONDS,
                )
                return lease_id

    def end_recording_attempt(self, lease_id: str) -> bool:
        """Release a classification lease; expired leases are already inactive."""
        normalized = str(lease_id or "").strip()
        if not normalized:
            raise StoreError("recording-attempt-lease-required")
        with self._recording_attempt_condition:
            removed = self._recording_attempts.pop(normalized, None) is not None
            self._recording_attempt_condition.notify_all()
            return removed

    def _prune_recording_attempts(self) -> None:
        now = time.monotonic()
        expired = [
            lease_id
            for lease_id, (_, expires_at) in self._recording_attempts.items()
            if expires_at <= now
        ]
        for lease_id in expired:
            self._recording_attempts.pop(lease_id, None)

    def _wait_for_recording_attempts(self, subject: str) -> None:
        while True:
            self._prune_recording_attempts()
            expiries = [
                expires_at
                for active_subject, expires_at in self._recording_attempts.values()
                if active_subject == subject
            ]
            if not expiries:
                return
            self._recording_attempt_condition.wait(
                timeout=max(0.001, min(expiries) - time.monotonic())
            )

    def enable_health_recording(
        self,
        subject: str,
        owner_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Persist explicit consent without creating or binding a health profile."""
        from .profile import ProfileStoreError

        subject = str(subject or "").strip()
        owner_sender_id = str(owner_sender_id or "").strip()
        if not subject or not owner_sender_id:
            raise ProfileStoreError("recording-enable-not-authorized")
        action = "health.recording.enable"
        with self._state_lock:
            existing_consent = self._recording_consent_state(subject)
            if existing_consent is None:
                if (
                    not self.expected_owner_sender_id
                    or owner_sender_id != self.expected_owner_sender_id
                ):
                    raise ProfileStoreError("recording-enable-not-authorized")
            elif existing_consent.get("owner_sender_id") != owner_sender_id:
                raise ProfileStoreError("recording-enable-not-authorized")
            if self.health_recording_status(subject, owner_sender_id) == "recording_stopped":
                raise ProfileStoreError("recording-resume-required")
            if not self.message_verifier.verify_access_receipt(
                action=action,
                subject=subject,
                actor_sender_id=owner_sender_id,
                target_sender_id=owner_sender_id,
                message_id=message_id,
                message_utc=message_utc,
                token=verification_token,
            ):
                raise ProfileStoreError("unverified-access-receipt")
            receipt_time, _ = self._validate_access_receipt(
                subject, message_id, message_utc
            )

            def mutate(
                current: Mapping[str, Any],
            ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
                if current:
                    if (
                        current.get("recording_consent_schema_version") != 1
                        or current.get("profile_subject") != subject
                        or current.get("owner_sender_id") != owner_sender_id
                    ):
                        raise ProfileStoreError("recording-consent-state-corrupt")
                    if current.get("consent_message_id") == message_id:
                        raise ProfileStoreError("access-receipt-replayed")
                    if current.get("enabled") is True:
                        return dict(current), {
                            "subject": subject,
                            "enabled": True,
                            "changed": False,
                        }
                recovery_code = self._new_owner_recovery_code()
                state = {
                    "recording_consent_schema_version": 1,
                    "profile_subject": subject,
                    "owner_sender_id": owner_sender_id,
                    "enabled": True,
                    "recording_status": "recording_enabled",
                    "consent_message_id": message_id,
                    "consent_utc": receipt_time.replace(microsecond=0).isoformat(),
                    "owner_recovery_schema_version": 1,
                    "recovery_code_verifier": self._owner_recovery_verifier(
                        subject, recovery_code
                    ),
                    "recovery_failed_attempts": 0,
                    "recovery_locked": False,
                }
                return state, {
                    "subject": subject,
                    "enabled": True,
                    "changed": True,
                    "recovery_code": recovery_code,
                }

            result = self.mutate_subject_status(_RECORDING_CONSENT_SUBJECT, mutate)
        self.append_audit_event(
            "health_recording_enabled",
            {
                "subject": subject,
                "actor_role": "owner",
                "actor_id": owner_sender_id,
                "action": action,
                "object_id": subject,
                "result": "enabled" if result["changed"] else "unchanged",
            },
        )
        return result

    def transfer_profile_owner(
        self,
        subject: str,
        old_owner_sender_id: str,
        new_owner_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Move owner control with a fresh old-owner receipt and rotate the code."""
        from .profile import ProfileStoreError, _profile_from_status

        subject = str(subject or "").strip()
        old_owner_sender_id = str(old_owner_sender_id or "").strip()
        new_owner_sender_id = str(new_owner_sender_id or "").strip()
        action = "health.profile.owner.transfer"
        if (
            not subject
            or not old_owner_sender_id
            or not new_owner_sender_id
            or old_owner_sender_id == new_owner_sender_id
            or new_owner_sender_id == self.expected_viewer_sender_id
        ):
            raise ProfileStoreError("owner-transfer-not-authorized")

        with self._state_lock:
            consent = self._recording_consent_state(subject)
            if consent is None or consent.get("owner_sender_id") != old_owner_sender_id:
                raise ProfileStoreError("owner-transfer-not-authorized")
            if not self.message_verifier.verify_access_receipt(
                action=action,
                subject=subject,
                actor_sender_id=old_owner_sender_id,
                target_sender_id=new_owner_sender_id,
                message_id=message_id,
                message_utc=message_utc,
                token=verification_token,
            ):
                raise ProfileStoreError("unverified-access-receipt")
            self._validate_access_receipt(subject, message_id, message_utc)
            profile_state = self.read_subject_status(
                subject, _allow_profile_state=True
            )
            if isinstance(profile_state, Mapping) and profile_state.get(
                "profile_schema_version"
            ) == 1:
                profile = _profile_from_status(profile_state)
                if profile.get("owner_sender_id") != old_owner_sender_id:
                    raise ProfileStoreError("owner-transfer-state-corrupt")

                def mutate_profile(
                    current: Mapping[str, Any],
                ) -> tuple[Mapping[str, Any], bool]:
                    updated = _profile_from_status(current)
                    if updated.get("owner_sender_id") != old_owner_sender_id:
                        raise ProfileStoreError("owner-transfer-state-corrupt")
                    updated["owner_sender_id"] = new_owner_sender_id
                    return updated, True

                self.mutate_subject_status(subject, mutate_profile)

            self.consume_access_receipt(subject, message_id, message_utc)
            recovery_code = self._new_owner_recovery_code()

            def mutate_consent(
                current: Mapping[str, Any],
            ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
                updated = dict(current)
                if (
                    updated.get("recording_consent_schema_version") != 1
                    or updated.get("profile_subject") != subject
                    or updated.get("owner_sender_id") != old_owner_sender_id
                ):
                    raise ProfileStoreError("owner-transfer-state-corrupt")
                updated.update(
                    {
                        "owner_sender_id": new_owner_sender_id,
                        "owner_recovery_schema_version": 1,
                        "recovery_code_verifier": self._owner_recovery_verifier(
                            subject, recovery_code
                        ),
                        "recovery_failed_attempts": 0,
                        "recovery_locked": False,
                    }
                )
                return updated, {"changed": True}

            def audit_builder(
                result: Mapping[str, Any],
            ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
                return (
                    (
                        "owner_identity_transferred",
                        {
                            "subject": subject,
                            "actor_role": "owner",
                            "actor_id": old_owner_sender_id,
                            "action": action,
                            "target_id": new_owner_sender_id,
                            "object_id": subject,
                            "result": "transferred",
                        },
                    ),
                )

            self.mutate_subject_status(
                _RECORDING_CONSENT_SUBJECT,
                mutate_consent,
                audit_builder=audit_builder,
            )
        return {
            "subject": subject,
            "old_owner_sender_id": old_owner_sender_id,
            "new_owner_sender_id": new_owner_sender_id,
            "changed": True,
            "recovery_code": recovery_code,
        }

    def recover_profile_owner(
        self,
        subject: str,
        new_owner_sender_id: str,
        recovery_code: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Rebind one owner only after an authenticated one-time code proof."""
        from .profile import ProfileStoreError, _profile_from_status

        subject = str(subject or "").strip()
        new_owner_sender_id = str(new_owner_sender_id or "").strip()
        recovery_code = str(recovery_code or "").strip()
        action = "health.profile.owner.recover"
        if (
            not subject
            or not new_owner_sender_id
            or new_owner_sender_id == self.expected_viewer_sender_id
            or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", recovery_code)
        ):
            raise ProfileStoreError("owner-recovery-not-authorized")

        with self._state_lock:
            consent = self._recording_consent_state(subject)
            if consent is None:
                raise ProfileStoreError("owner-recovery-unavailable")
            old_owner_sender_id = str(consent.get("owner_sender_id") or "").strip()
            if not old_owner_sender_id or new_owner_sender_id == old_owner_sender_id:
                raise ProfileStoreError("owner-recovery-not-authorized")
            if not self.message_verifier.verify_access_receipt(
                action=action,
                subject=subject,
                actor_sender_id=new_owner_sender_id,
                target_sender_id=new_owner_sender_id,
                message_id=message_id,
                message_utc=message_utc,
                token=verification_token,
            ):
                raise ProfileStoreError("unverified-access-receipt")
            self._validate_access_receipt(subject, message_id, message_utc)
            self.consume_access_receipt(subject, message_id, message_utc)

            expected_verifier = str(consent.get("recovery_code_verifier") or "")
            supplied_verifier = self._owner_recovery_verifier(subject, recovery_code)
            valid_code = (
                consent.get("owner_recovery_schema_version") == 1
                and consent.get("recovery_locked") is not True
                and bool(expected_verifier)
                and hmac.compare_digest(expected_verifier, supplied_verifier)
            )
            if not valid_code:

                def reject(
                    current: Mapping[str, Any],
                ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
                    updated = dict(current)
                    attempts = int(updated.get("recovery_failed_attempts", 0)) + 1
                    updated["recovery_failed_attempts"] = attempts
                    updated["recovery_locked"] = attempts >= 5
                    return updated, {
                        "attempts": attempts,
                        "locked": updated["recovery_locked"],
                    }

                def reject_audit(
                    result: Mapping[str, Any],
                ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
                    return (
                        (
                            "owner_identity_recovery_failed",
                            {
                                "subject": subject,
                                "actor_role": "recovery_code",
                                "actor_id": new_owner_sender_id,
                                "action": action,
                                "object_id": subject,
                                "result": "denied",
                                "reason": (
                                    "recovery-code-locked"
                                    if result["locked"]
                                    else "recovery-code-invalid"
                                ),
                            },
                        ),
                    )

                self.mutate_subject_status(
                    _RECORDING_CONSENT_SUBJECT,
                    reject,
                    audit_builder=reject_audit,
                )
                raise ProfileStoreError("owner-recovery-unavailable")

            profile_state = self.read_subject_status(
                subject, _allow_profile_state=True
            )
            if isinstance(profile_state, Mapping) and profile_state.get(
                "profile_schema_version"
            ) == 1:
                profile = _profile_from_status(profile_state)
                if profile.get("owner_sender_id") != old_owner_sender_id:
                    raise ProfileStoreError("owner-recovery-state-corrupt")

                def mutate_profile(
                    current: Mapping[str, Any],
                ) -> tuple[Mapping[str, Any], bool]:
                    updated = _profile_from_status(current)
                    if updated.get("owner_sender_id") != old_owner_sender_id:
                        raise ProfileStoreError("owner-recovery-state-corrupt")
                    updated["owner_sender_id"] = new_owner_sender_id
                    return updated, True

                self.mutate_subject_status(subject, mutate_profile)

            next_recovery_code = self._new_owner_recovery_code()

            def accept(
                current: Mapping[str, Any],
            ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
                updated = dict(current)
                if (
                    updated.get("recording_consent_schema_version") != 1
                    or updated.get("profile_subject") != subject
                    or updated.get("owner_sender_id") != old_owner_sender_id
                ):
                    raise ProfileStoreError("owner-recovery-state-corrupt")
                updated.update(
                    {
                        "owner_sender_id": new_owner_sender_id,
                        "owner_recovery_schema_version": 1,
                        "recovery_code_verifier": self._owner_recovery_verifier(
                            subject, next_recovery_code
                        ),
                        "recovery_failed_attempts": 0,
                        "recovery_locked": False,
                    }
                )
                return updated, {"changed": True}

            def accept_audit(
                result: Mapping[str, Any],
            ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
                return (
                    (
                        "owner_identity_recovered",
                        {
                            "subject": subject,
                            "actor_role": "recovery_code",
                            "actor_id": new_owner_sender_id,
                            "action": action,
                            "object_id": subject,
                            "result": "recovered",
                        },
                    ),
                )

            self.mutate_subject_status(
                _RECORDING_CONSENT_SUBJECT,
                accept,
                audit_builder=accept_audit,
            )
        return {
            "subject": subject,
            "new_owner_sender_id": new_owner_sender_id,
            "changed": True,
            "recovery_code": next_recovery_code,
        }

    def stop_health_recording(
        self,
        subject: str,
        owner_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Stop new health processing while retaining the encrypted record."""
        self._prevalidate_recording_control(
            subject,
            owner_sender_id,
            message_id,
            message_utc,
            verification_token,
            action="health.recording.stop",
        )
        normalized_subject = str(subject or "").strip()
        with self._recording_attempt_condition:
            self._recording_stopping_subjects.add(normalized_subject)
            try:
                self._wait_for_recording_attempts(normalized_subject)
                # Source retrieval may be blocked on an external endpoint.
                # Stop is therefore committed through the state boundary
                # without waiting for the source lock; guarded daily scans
                # re-check this state before any subsequent sidecar write.
                return self._set_health_recording_status(
                    normalized_subject,
                    owner_sender_id,
                    message_id,
                    message_utc,
                    verification_token,
                    target_status="recording_stopped",
                )
            finally:
                self._recording_stopping_subjects.discard(normalized_subject)
                self._recording_attempt_condition.notify_all()

    def resume_health_recording(
        self,
        subject: str,
        owner_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Resume only through a fresh owner action receipt."""
        return self._set_health_recording_status(
            subject,
            owner_sender_id,
            message_id,
            message_utc,
            verification_token,
            target_status="recording_enabled",
        )

    def _set_health_recording_status(
        self,
        subject: str,
        owner_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
        *,
        target_status: str,
    ) -> Mapping[str, Any]:
        from .profile import ProfileStoreError, _profile_from_status
        from .tasks import TASK_STATUSES

        subject = str(subject or "").strip()
        owner_sender_id = str(owner_sender_id or "").strip()
        if target_status not in {"recording_enabled", "recording_stopped"}:
            raise ProfileStoreError("recording-status-invalid")
        if (
            not subject
            or not owner_sender_id
        ):
            raise ProfileStoreError("recording-control-not-authorized")
        action = (
            "health.recording.stop"
            if target_status == "recording_stopped"
            else "health.recording.resume"
        )
        with self._state_lock:
            if not self.message_verifier.verify_access_receipt(
                action=action,
                subject=subject,
                actor_sender_id=owner_sender_id,
                target_sender_id=owner_sender_id,
                message_id=message_id,
                message_utc=message_utc,
                token=verification_token,
            ):
                raise ProfileStoreError("unverified-access-receipt")
            self._validate_access_receipt(subject, message_id, message_utc)
            current_status = self.health_recording_status(subject, owner_sender_id)
            if current_status == "not_enabled":
                raise ProfileStoreError("recording-not-enabled")
            self.consume_access_receipt(subject, message_id, message_utc)
            now = self._now_utc().replace(microsecond=0).isoformat()
            profile_state = self.read_subject_status(
                subject, _allow_profile_state=True
            )
            cancelled = 0

            def control_audit_builder(
                result: Mapping[str, Any],
            ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
                return (
                    (
                        "health_recording_stopped"
                        if target_status == "recording_stopped"
                        else "health_recording_resumed",
                        {
                            "subject": subject,
                            "actor_role": "owner",
                            "actor_id": owner_sender_id,
                            "action": action,
                            "object_id": subject,
                            "result": (
                                (
                                    "stopped"
                                    if target_status == "recording_stopped"
                                    else "resumed"
                                )
                                if result["changed"]
                                else "unchanged"
                            ),
                            "cancelled_task_count": int(
                                result["cancelled_task_count"]
                            ),
                        },
                    ),
                )

            if (
                isinstance(profile_state, Mapping)
                and profile_state.get("profile_schema_version") == 1
            ):
                def mutate_profile(
                    current: Mapping[str, Any],
                ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
                    nonlocal cancelled
                    updated = _profile_from_status(current)
                    if updated.get("owner_sender_id") != owner_sender_id:
                        raise ProfileStoreError("recording-control-owner-mismatch")
                    changed = updated.get("recording_status") != target_status
                    updated["recording_status"] = target_status
                    if target_status == "recording_stopped":
                        tasks = copy.deepcopy(list(updated.get("tasks", [])))
                        cancelled_report_ids: set[str] = set()
                        for index, item in enumerate(tasks):
                            if (
                                not isinstance(item, Mapping)
                                or item.get("status") not in TASK_STATUSES
                            ):
                                continue
                            task = dict(item)
                            task.update(
                                {
                                    "status": "cancelled",
                                    "cancel_reason": "health-recording-stopped",
                                    "dispatch_claim_id": None,
                                    "dispatch_claimed_utc": None,
                                    "updated_utc": now,
                                }
                            )
                            tasks[index] = task
                            cancelled += 1
                            if task.get("report_id"):
                                cancelled_report_ids.add(str(task["report_id"]))
                        updated["tasks"] = tasks
                        if cancelled_report_ids:
                            reports = copy.deepcopy(list(updated.get("reports", [])))
                            for index, report in enumerate(reports):
                                if (
                                    isinstance(report, Mapping)
                                    and str(report.get("report_id"))
                                    in cancelled_report_ids
                                ):
                                    changed_report = dict(report)
                                    changed_report["status"] = "cancelled"
                                    changed_report["skip_reason"] = (
                                        "health-recording-stopped"
                                    )
                                    reports[index] = changed_report
                            updated["reports"] = reports
                    return updated, {
                        "changed": changed,
                        "cancelled_task_count": cancelled,
                    }

                result = self.mutate_subject_status(
                    subject,
                    mutate_profile,
                    audit_builder=control_audit_builder,
                )
            else:
                def mutate_consent(
                    current: Mapping[str, Any],
                ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
                    state = dict(current)
                    if (
                        state.get("recording_consent_schema_version") != 1
                        or state.get("profile_subject") != subject
                        or state.get("owner_sender_id") != owner_sender_id
                    ):
                        raise ProfileStoreError("recording-consent-state-corrupt")
                    changed = state.get("recording_status") != target_status
                    state["recording_status"] = target_status
                    state["enabled"] = target_status == "recording_enabled"
                    state["consent_message_id"] = message_id
                    state["consent_utc"] = now
                    return state, {"changed": changed, "cancelled_task_count": 0}

                result = self.mutate_subject_status(
                    _RECORDING_CONSENT_SUBJECT,
                    mutate_consent,
                    audit_builder=control_audit_builder,
                )
        return {
            "subject": subject,
            "status": target_status,
            "enabled": target_status == "recording_enabled",
            "changed": bool(result["changed"]),
            "cancelled_task_count": int(result["cancelled_task_count"]),
        }

    def _prevalidate_recording_control(
        self,
        subject: str,
        owner_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
        *,
        action: str,
    ) -> None:
        from .profile import ProfileStoreError

        subject = str(subject or "").strip()
        owner_sender_id = str(owner_sender_id or "").strip()
        with self._state_lock:
            if (
                not subject
                or not owner_sender_id
                or not self.message_verifier.verify_access_receipt(
                    action=action,
                    subject=subject,
                    actor_sender_id=owner_sender_id,
                    target_sender_id=owner_sender_id,
                    message_id=message_id,
                    message_utc=message_utc,
                    token=verification_token,
                )
            ):
                raise ProfileStoreError("recording-control-not-authorized")
            self._validate_access_receipt(subject, message_id, message_utc)
            if self.health_recording_status(subject, owner_sender_id) == "not_enabled":
                raise ProfileStoreError("recording-not-enabled")

    def send_recording_feedback(
        self,
        subject: str,
        owner_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
        feedback_status: str,
        channel_send: Any,
    ) -> Mapping[str, Any]:
        """Authorize and send one fixed, idempotent reactive status message."""
        from .profile import ProfileStoreError

        from .recording import (
            RECORDING_FEEDBACK_ACTION_BY_STATUS,
            RECORDING_FEEDBACK_MESSAGE_BY_STATUS,
        )
        try:
            action = RECORDING_FEEDBACK_ACTION_BY_STATUS[feedback_status]
            message = RECORDING_FEEDBACK_MESSAGE_BY_STATUS[feedback_status]
        except KeyError as exc:
            raise ProfileStoreError("recording-feedback-invalid") from exc
        subject = str(subject or "").strip()
        owner_sender_id = str(owner_sender_id or "").strip()
        if (
            not subject
            or channel_send is None
            or not callable(getattr(channel_send, "send_once", None))
        ):
            raise ProfileStoreError("recording-feedback-not-authorized")
        with self._state_lock:
            if not self.message_verifier.verify_access_receipt(
                action=action,
                subject=subject,
                actor_sender_id=owner_sender_id,
                target_sender_id=owner_sender_id,
                message_id=message_id,
                message_utc=message_utc,
                token=verification_token,
            ):
                raise ProfileStoreError("unverified-access-receipt")
            self._validate_access_receipt(subject, message_id, message_utc)
            if (
                feedback_status == "not_recorded"
                and self.health_recording_status(subject, owner_sender_id)
                == "recording_stopped"
            ):
                self.consume_access_receipt(subject, message_id, message_utc)
                return {
                    "subject": subject,
                    "status": feedback_status,
                    "sent": False,
                    "reason": "health-recording-stopped",
                }
            delivery_key = (
                f"health-recording-feedback:{subject}:{message_id}:{feedback_status}"
            )
            sent = bool(
                channel_send.send_once(owner_sender_id, message, delivery_key)
            )
            self.consume_access_receipt(subject, message_id, message_utc)
        self.append_audit_event_once(
            f"recording-feedback:{message_id}:{feedback_status}",
            "recording_feedback_sent" if sent else "recording_feedback_rejected",
            {
                "subject": subject,
                "actor_role": "health-ingress",
                "actor_id": owner_sender_id,
                "action": action,
                "object_id": message_id,
                "recipient_id": owner_sender_id,
                "result": "sent" if sent else "rejected",
                "status": feedback_status,
            },
        )
        return {
            "subject": subject,
            "status": feedback_status,
            "sent": sent,
            "delivery_key": delivery_key,
        }

    def profile_message_admitted(
        self, subject: str, sender_id: str, message_id: str
    ) -> bool:
        """Return only whether a trusted source message already has evidence."""
        subject = str(subject or "").strip()
        sender_id = str(sender_id or "").strip()
        message_id = str(message_id or "").strip()
        if not subject or not sender_id or not message_id:
            raise StoreError("admission-status-fields-required")
        with self._state_lock:
            profile = self.read_subject_status(subject, _allow_profile_state=True)
            if (
                not isinstance(profile, Mapping)
                or profile.get("owner_sender_id") != sender_id
            ):
                return False
            return any(
                isinstance(item, Mapping)
                and item.get("source_message_id") == message_id
                for item in profile.get("evidence", [])
            )

    def admit_consented_profile_candidate(
        self,
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
        channel: str,
        profile_name: str,
        verification_token: str,
        candidate: Mapping[str, Any],
        attempt_utc: str | None = None,
        audit_context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Atomically bind the configured owner and admit one trusted candidate."""
        from .profile import admit_consented_profile_candidate

        return admit_consented_profile_candidate(
            self,
            subject=subject,
            sender_id=sender_id,
            message_id=message_id,
            message_utc=message_utc,
            attempt_utc=attempt_utc,
            message_text=message_text,
            evidence_kind=evidence_kind,
            channel=channel,
            profile_name=profile_name,
            verification_token=verification_token,
            candidate=candidate,
            audit_context=audit_context,
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
    ) -> Mapping[str, Any]:
        """Read one receipt-bound, model-visible health-turn projection."""
        from .profile import read_health_turn_context

        return read_health_turn_context(
            self,
            subject=subject,
            sender_id=sender_id,
            message_id=message_id,
            message_utc=message_utc,
            message_text=message_text,
            channel=channel,
            profile_name=profile_name,
            attempt_utc=attempt_utc,
            verification_token=verification_token,
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
    ) -> bool:
        from .profile import stage_profile_message

        return stage_profile_message(
            self,
            subject,
            sender_id,
            message_id,
            message_utc,
            message_text,
            evidence_kind,
            verification_token,
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
        channel: str | None = None,
        profile_name: str | None = None,
    ) -> bool:
        """Keep a verified owner's latest message for ephemeral rendering only.

        This is deliberately separate from evidence staging: ordinary chat may
        appear in the latest-three context window but can never become profile
        evidence or a conclusion.
        """
        values = (subject, sender_id, message_id, message_utc, evidence_kind, verification_token)
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise StoreError("recent-message-fields-required")
        if not isinstance(message_text, str) or not message_text.strip() or len(message_text) > 4000:
            raise StoreError("recent-message-text-invalid")
        production_route = any(
            value is not None for value in (attempt_utc, channel, profile_name)
        )
        if production_route:
            normalized_attempt = str(attempt_utc or "").strip()
            normalized_channel = str(channel or "").strip()
            normalized_profile = str(profile_name or "").strip()
            verified = (
                normalized_channel == "weixin"
                and normalized_profile == "partner"
                and self.message_verifier.verify_ingress_receipt(
                    action="health.profile.message.recent",
                    subject=subject,
                    sender_id=sender_id,
                    message_id=message_id,
                    message_utc=message_utc,
                    message_text=message_text,
                    evidence_kind=evidence_kind,
                    channel=normalized_channel,
                    profile_name=normalized_profile,
                    attempt_utc=normalized_attempt,
                    token=verification_token,
                )
            )
            try:
                source_time = dt.datetime.fromisoformat(
                    message_utc.replace("Z", "+00:00")
                )
                attempt_time = dt.datetime.fromisoformat(
                    normalized_attempt.replace("Z", "+00:00")
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise StoreError("recent-message-time-invalid") from exc
            if source_time.tzinfo is None or attempt_time.tzinfo is None:
                raise StoreError("recent-message-time-invalid")
            source_time = source_time.astimezone(dt.timezone.utc)
            attempt_time = attempt_time.astimezone(dt.timezone.utc)
            now = self._now_utc()
            if (
                attempt_time < source_time
                or attempt_time
                > source_time
                + dt.timedelta(seconds=ACCESS_RECEIPT_MAX_AGE_SECONDS)
                or attempt_time > now + dt.timedelta(seconds=ACCESS_RECEIPT_MAX_FUTURE_SECONDS)
                or now
                >= attempt_time
                + dt.timedelta(seconds=RECORDING_ATTEMPT_WRITE_BUDGET_SECONDS)
            ):
                raise StoreError("recent-message-attempt-invalid")
        else:
            verified = self.verify_inbound_message(
                subject=subject,
                sender_id=sender_id,
                message_id=message_id,
                message_utc=message_utc,
                message_text=message_text,
                evidence_kind=evidence_kind,
                token=verification_token,
            )
        if not verified:
            raise StoreError("unverified-inbound-message")
        with self._recent_message_lock:
            with self._state_lock:
                if self.expected_owner_sender_id and not self.health_recording_enabled(
                    subject, sender_id
                ):
                    raise StoreError("recording-not-enabled")
                profile = self.read_subject_status(
                    subject, _allow_profile_state=True
                )
                if not profile and production_route:
                    return False
                if not profile or profile.get("owner_sender_id") != sender_id:
                    raise StoreError("non-owner-message")
                self._record_owner_reply(subject, sender_id, message_utc)
                self.remember_recent_profile_message(
                    subject, sender_id, message_id, message_utc, message_text
                )
        return True

    def record_profile_candidate(
        self,
        subject: str,
        sender_id: str,
        candidate: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        from .profile import record_profile_candidate

        return record_profile_candidate(self, subject, sender_id, candidate)

    def read_profile(self, subject: str, sender_id: str) -> Mapping[str, Any]:
        from .profile import read_profile

        return read_profile(self, subject, sender_id)

    def grant_profile_viewer(
        self,
        subject: str,
        owner_sender_id: str,
        viewer_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        from .access import grant_profile_viewer

        return grant_profile_viewer(
            self,
            subject,
            owner_sender_id,
            viewer_sender_id,
            message_id,
            message_utc,
            verification_token,
        )

    def revoke_profile_viewer(
        self,
        subject: str,
        owner_sender_id: str,
        viewer_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        from .access import revoke_profile_viewer

        return revoke_profile_viewer(
            self,
            subject,
            owner_sender_id,
            viewer_sender_id,
            message_id,
            message_utc,
            verification_token,
        )

    def read_authorized_view(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
        action: str = "health.access.read",
    ) -> Mapping[str, Any]:
        from .access import read_authorized_view

        return read_authorized_view(
            self,
            subject,
            sender_id,
            message_id,
            message_utc,
            verification_token,
            action=action,
        )

    def export_profile(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        from .access import export_profile

        return export_profile(
            self, subject, sender_id, message_id, message_utc, verification_token
        )

    def read_authorized_analysis_context(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        from .access import read_authorized_analysis_context

        return read_authorized_analysis_context(
            self,
            subject,
            sender_id,
            message_id,
            message_utc,
            verification_token,
        )

    def daily_review_snapshot(
        self,
        subject: str,
        review_utc: str,
        timezone: str,
        *,
        audit_context: Mapping[str, Any] | None = None,
        retry_only: bool = False,
    ) -> Mapping[str, Any]:
        from .tasks import daily_review_snapshot

        with self._state_lock:
            result = daily_review_snapshot(
                self,
                subject,
                review_utc,
                timezone,
                retry_only=retry_only,
            )
            if result.get("recording_status") == "recording_stopped" or result.get(
                "result"
            ) in {
                "already_completed",
                "retry_not_due",
                "retry_exhausted",
                "retry_window_expired",
            }:
                return result
            purge = self.purge_expired_backups()
            self.append_audit_event(
                "backup_retention_purge",
                {
                    "subject": subject,
                    "actor_role": "daily-review",
                    "action": "backup.retention.purge",
                    "object_id": f"backup-retention:{subject}",
                    "result": "passed" if purge["failed"] == 0 else "failed",
                    "deleted": purge["deleted"],
                    "failed": purge["failed"],
                },
            )
            snapshot_audit = {
                "subject": subject,
                "actor_role": "daily-review",
                "action": "daily-review.snapshot",
                "object_id": f"daily-review-snapshot:{subject}",
                "result": "provided",
            }
            if audit_context:
                for key in ("peer_uid", "peer_gid"):
                    if key in audit_context:
                        snapshot_audit[key] = audit_context[key]
            self.append_audit_event("daily_review_snapshot", snapshot_audit)
            return result

    def run_daily_review(
        self,
        subject: str,
        review_utc: str,
        timezone: str,
        plan: Mapping[str, Any],
        source_library: Any | None = None,
        *,
        retry_only: bool = False,
    ) -> Mapping[str, Any]:
        from .tasks import run_daily_review

        return run_daily_review(
            self,
            subject,
            review_utc,
            timezone,
            plan,
            source_library=source_library,
            retry_only=retry_only,
        )

    def expire_daily_review_retry(
        self, subject: str, review_utc: str, timezone: str
    ) -> Mapping[str, Any]:
        """Record a missed daily retry window without invoking model work."""
        from .tasks import expire_daily_review_retry

        return expire_daily_review_retry(self, subject, review_utc, timezone)

    def dispatch_due_tasks(
        self,
        subject: str,
        now_utc: str,
        llm: Any | None,
        channel_send: Any | None,
        source_library: Any | None = None,
    ) -> Mapping[str, Any]:
        from .dispatch import dispatch_due_tasks

        return dispatch_due_tasks(
            self,
            subject,
            now_utc,
            llm,
            channel_send,
            source_library=source_library,
        )

    def pause_proactive_contact(
        self,
        subject: str,
        owner_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
        pause_until_utc: str | None = None,
    ) -> Mapping[str, Any]:
        """Pause all proactive contact after verifying one owner receipt."""
        from .profile import ProfileStoreError, _profile_from_status
        from .tasks import TASK_STATUSES, _utc

        subject = str(subject).strip()
        owner_sender_id = str(owner_sender_id).strip()
        action = "health.proactive.pause"
        with self._state_lock:
            pause_until: str | None = None
            if pause_until_utc not in (None, ""):
                pause_until = _utc(pause_until_utc, "invalid-pause-time").replace(
                    microsecond=0
                ).isoformat()
            profile = _profile_from_status(
                self.read_subject_status(subject, _allow_profile_state=True)
            )
            if profile.get("owner_sender_id") != owner_sender_id:
                raise ProfileStoreError("pause-owner-mismatch")
            if not self.message_verifier.verify_access_receipt(
                action=action,
                subject=subject,
                actor_sender_id=owner_sender_id,
                target_sender_id=owner_sender_id,
                message_id=message_id,
                message_utc=message_utc,
                token=verification_token,
                pause_until_utc=pause_until,
            ):
                raise ProfileStoreError("unverified-access-receipt")
            self._validate_access_receipt(subject, message_id, message_utc)
            now = self.now_utc().replace(microsecond=0)
            if pause_until is not None:
                if dt.datetime.fromisoformat(pause_until) <= now:
                    raise ProfileStoreError("pause-time-not-in-future")
            self.consume_access_receipt(subject, message_id, message_utc)

            cancelled = 0

            def mutate(
                current: Mapping[str, Any],
            ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
                nonlocal cancelled
                updated = _profile_from_status(current)
                tasks = copy.deepcopy(list(updated.get("tasks", [])))
                current_contact = updated.get("proactive_contact", {})
                contact_already_matches = (
                    isinstance(current_contact, Mapping)
                    and current_contact.get("paused") is True
                    and current_contact.get("pause_until_utc") == pause_until
                    and bool(current_contact.get("indefinite"))
                    == (pause_until is None)
                )
                has_cancellable_tasks = any(
                    isinstance(item, Mapping)
                    and item.get("status") in TASK_STATUSES
                    for item in tasks
                )
                if contact_already_matches and not has_cancellable_tasks:
                    return current, {"changed": False}
                cancelled_report_ids: set[str] = set()
                for index, item in enumerate(tasks):
                    if not isinstance(item, Mapping) or item.get("status") not in TASK_STATUSES:
                        continue
                    task = dict(item)
                    task.update(
                        {
                            "status": "cancelled",
                            "cancel_reason": "proactive-contact-paused",
                            "dispatch_claim_id": None,
                            "dispatch_claimed_utc": None,
                            "updated_utc": now.isoformat(),
                        }
                    )
                    tasks[index] = task
                    if task.get("report_id"):
                        cancelled_report_ids.add(str(task["report_id"]))
                    cancelled += 1
                updated["tasks"] = tasks
                if cancelled_report_ids:
                    reports = copy.deepcopy(list(updated.get("reports", [])))
                    for report_index, report in enumerate(reports):
                        if (
                            isinstance(report, Mapping)
                            and str(report.get("report_id")) in cancelled_report_ids
                        ):
                            report_update = dict(report)
                            report_update["status"] = "cancelled"
                            report_update["skip_reason"] = "proactive-contact-paused"
                            reports[report_index] = report_update
                    updated["reports"] = reports
                updated["proactive_contact"] = {
                    "paused": True,
                    "pause_until_utc": pause_until,
                    "pause_reason": "owner-request",
                    "paused_utc": now.isoformat(),
                    "indefinite": pause_until is None,
                }
                return updated, {"changed": True}

            def audit_builder(result: Mapping[str, Any]):
                return ((
                    "proactive_contact_paused",
                    {
                        "subject": subject,
                        "actor_role": "owner",
                        "actor_id": owner_sender_id,
                        "action": action,
                        "object_id": subject,
                        "result": "paused" if result["changed"] else "unchanged",
                        "reason": "owner-request",
                        "cancelled_task_count": cancelled,
                        "indefinite": pause_until is None,
                    },
                ),)

            result = self.mutate_subject_status(
                subject,
                mutate,
                audit_builder=audit_builder,
            )
        return {
            "subject": subject,
            "paused": True,
            "changed": bool(result["changed"]),
            "pause_until_utc": pause_until,
            "indefinite": pause_until is None,
            "cancelled_task_count": cancelled,
        }

    def resume_proactive_contact(
        self,
        subject: str,
        owner_sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Resume proactive contact only after an explicit owner receipt."""
        from .profile import ProfileStoreError, _profile_from_status

        subject = str(subject).strip()
        owner_sender_id = str(owner_sender_id).strip()
        action = "health.proactive.resume"
        with self._state_lock:
            profile = _profile_from_status(
                self.read_subject_status(subject, _allow_profile_state=True)
            )
            if profile.get("owner_sender_id") != owner_sender_id:
                raise ProfileStoreError("resume-owner-mismatch")
            if not self.message_verifier.verify_access_receipt(
                action=action,
                subject=subject,
                actor_sender_id=owner_sender_id,
                target_sender_id=owner_sender_id,
                message_id=message_id,
                message_utc=message_utc,
                token=verification_token,
            ):
                raise ProfileStoreError("unverified-access-receipt")
            self._validate_access_receipt(subject, message_id, message_utc)
            self.consume_access_receipt(subject, message_id, message_utc)
            now = self.now_utc().replace(microsecond=0)

            def mutate(
                current: Mapping[str, Any],
            ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
                updated = _profile_from_status(current)
                current_contact = updated.get("proactive_contact", {})
                if (
                    isinstance(current_contact, Mapping)
                    and current_contact.get("paused") is False
                    and current_contact.get("pause_until_utc") is None
                ):
                    return current, {"changed": False}
                updated["proactive_contact"] = {
                    "paused": False,
                    "pause_until_utc": None,
                    "pause_reason": None,
                    "resumed_utc": now.isoformat(),
                    "indefinite": False,
                }
                return updated, {"changed": True}

            def audit_builder(result: Mapping[str, Any]):
                return ((
                    "proactive_contact_resumed",
                    {
                        "subject": subject,
                        "actor_role": "owner",
                        "actor_id": owner_sender_id,
                        "action": action,
                        "object_id": subject,
                        "result": "resumed" if result["changed"] else "unchanged",
                        "reason": "owner-request",
                    },
                ),)

            result = self.mutate_subject_status(
                subject,
                mutate,
                audit_builder=audit_builder,
            )
        return {
            "subject": subject,
            "resumed": True,
            "changed": bool(result["changed"]),
        }

    def consume_access_receipt(
        self, subject: str, message_id: str, message_utc: str
    ) -> None:
        """Consume a short-lived, one-time access receipt in its own ledger."""
        from .profile import ProfileStoreError

        with self._state_lock:
            receipt_time, now = self._validate_access_receipt(
                subject, message_id, message_utc
            )

            def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], None]:
                ledger = dict(current or {})
                consumed = dict(ledger.get("receipts", {}))
                retained = {}
                for consumed_id, consumed_utc in consumed.items():
                    try:
                        consumed_time = dt.datetime.fromisoformat(
                            str(consumed_utc).replace("Z", "+00:00")
                        ).astimezone(dt.timezone.utc)
                    except (TypeError, ValueError):
                        continue
                    if (now - consumed_time).total_seconds() <= ACCESS_RECEIPT_MAX_AGE_SECONDS:
                        retained[str(consumed_id)] = str(consumed_utc)
                if message_id in retained:
                    raise ProfileStoreError("access-receipt-replayed")
                retained[message_id] = receipt_time.replace(microsecond=0).isoformat()
                return {"ledger_schema_version": 1, "receipts": retained}, None

            self.mutate_subject_status(_ACCESS_RECEIPT_SUBJECT, mutate)

    def consume_job_action_authorization(
        self, nonce: str, issued_utc: str
    ) -> None:
        """Atomically consume one verified, content-free Job action proof."""
        from .profile import ProfileStoreError

        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise ProfileStoreError("job-authorization-invalid")
        try:
            issued = dt.datetime.fromisoformat(issued_utc.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ProfileStoreError("job-authorization-invalid") from exc
        if issued.tzinfo is None:
            raise ProfileStoreError("job-authorization-invalid")
        with self._state_lock:
            now = self._now_utc().astimezone(dt.timezone.utc)
            issued = issued.astimezone(dt.timezone.utc).replace(microsecond=0)
            age = (now - issued).total_seconds()
            if age < -60 or age > JOB_ACTION_AUTHORIZATION_TTL_SECONDS:
                raise ProfileStoreError("job-authorization-expired")

            def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], None]:
                ledger = dict(current or {})
                consumed = dict(ledger.get("authorizations", {}))
                retained: dict[str, str] = {}
                for recorded_nonce, recorded_utc in consumed.items():
                    try:
                        recorded = dt.datetime.fromisoformat(
                            str(recorded_utc).replace("Z", "+00:00")
                        )
                    except (TypeError, ValueError):
                        continue
                    if recorded.tzinfo is None:
                        continue
                    if (
                        now - recorded.astimezone(dt.timezone.utc)
                    ).total_seconds() <= JOB_ACTION_AUTHORIZATION_TTL_SECONDS:
                        retained[str(recorded_nonce)] = recorded.astimezone(
                            dt.timezone.utc
                        ).replace(microsecond=0).isoformat()
                if nonce in retained:
                    raise ProfileStoreError("job-authorization-replayed")
                retained[nonce] = issued.isoformat()
                return {"ledger_schema_version": 1, "authorizations": retained}, None

            self.mutate_subject_status(_JOB_ACTION_AUTHORIZATION_SUBJECT, mutate)

    def _retain_recent_ingress_receipts(
        self, profile: Mapping[str, Any]
    ) -> None:
        """Keep short-lived ingress nonces replay-safe across profile deletion."""
        now = self._now_utc().astimezone(dt.timezone.utc)
        recent: dict[str, str] = {}
        for evidence in profile.get("evidence", []):
            if not isinstance(evidence, Mapping):
                continue
            message_id = str(evidence.get("source_message_id", "")).strip()
            source_utc = str(evidence.get("source_utc", "")).strip()
            if not message_id or not source_utc:
                continue
            try:
                source_time = dt.datetime.fromisoformat(
                    source_utc.replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                continue
            if source_time.tzinfo is None:
                continue
            source_time = source_time.astimezone(dt.timezone.utc)
            age_seconds = (now - source_time).total_seconds()
            if (
                age_seconds <= ACCESS_RECEIPT_MAX_AGE_SECONDS
                and age_seconds >= -ACCESS_RECEIPT_MAX_FUTURE_SECONDS
            ):
                recent[message_id] = source_time.replace(
                    microsecond=0
                ).isoformat()
        if not recent:
            return

        def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], None]:
            ledger = dict(current or {})
            consumed = dict(ledger.get("receipts", {}))
            retained: dict[str, str] = {}
            for consumed_id, consumed_utc in consumed.items():
                try:
                    consumed_time = dt.datetime.fromisoformat(
                        str(consumed_utc).replace("Z", "+00:00")
                    )
                except (TypeError, ValueError):
                    continue
                if consumed_time.tzinfo is None:
                    continue
                consumed_time = consumed_time.astimezone(dt.timezone.utc)
                if (
                    now - consumed_time
                ).total_seconds() <= ACCESS_RECEIPT_MAX_AGE_SECONDS:
                    retained[str(consumed_id)] = consumed_time.replace(
                        microsecond=0
                    ).isoformat()
            retained.update(recent)
            return {"ledger_schema_version": 1, "receipts": retained}, None

        self.mutate_subject_status(_ACCESS_RECEIPT_SUBJECT, mutate)

    def _validate_access_receipt(
        self,
        subject: str,
        message_id: str,
        message_utc: str,
        *,
        allow_consumed: bool = False,
    ) -> tuple[dt.datetime, dt.datetime]:
        """Validate receipt freshness and, by default, replay state.

        Recovery status is read-only and must recognize the same confirmation
        receipt after the destructive path has consumed it.  That one caller
        passes ``allow_consumed=True``; all state-changing paths retain the
        normal one-time rule.
        """
        from .profile import ProfileStoreError

        if not isinstance(message_id, str) or not message_id.strip():
            raise ProfileStoreError("access-message-id-required")
        try:
            receipt_time = dt.datetime.fromisoformat(
                message_utc.replace("Z", "+00:00")
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProfileStoreError("invalid-access-receipt-utc") from exc
        if receipt_time.tzinfo is None:
            raise ProfileStoreError("invalid-access-receipt-utc")
        receipt_time = receipt_time.astimezone(dt.timezone.utc)
        now = self._now_utc().astimezone(dt.timezone.utc)
        age_seconds = (now - receipt_time).total_seconds()
        if age_seconds > ACCESS_RECEIPT_MAX_AGE_SECONDS:
            raise ProfileStoreError("access-receipt-expired")
        if age_seconds < -ACCESS_RECEIPT_MAX_FUTURE_SECONDS:
            raise ProfileStoreError("access-receipt-from-future")
        if not allow_consumed:
            ledger = self.read_subject_status(
                _ACCESS_RECEIPT_SUBJECT, _allow_profile_state=True
            ) or {}
            for consumed_id, consumed_utc in dict(ledger.get("receipts", {})).items():
                if str(consumed_id) != message_id:
                    continue
                try:
                    consumed_time = dt.datetime.fromisoformat(
                        str(consumed_utc).replace("Z", "+00:00")
                    ).astimezone(dt.timezone.utc)
                except (TypeError, ValueError):
                    continue
                if (
                    now - consumed_time
                ).total_seconds() <= ACCESS_RECEIPT_MAX_AGE_SECONDS:
                    raise ProfileStoreError("access-receipt-replayed")
        return receipt_time, now

    def delete_profile(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
        *,
        memory_projection: Any | None = None,
    ) -> Mapping[str, Any]:
        """Reject the retired one-step deletion seam.

        A callable one-step API would let a partner process turn one owner
        receipt into irreversible destruction.  Keep the method only to make
        accidental legacy callers fail closed; the socket exposes the request
        and confirmation actions below instead.
        """
        from .profile import ProfileStoreError

        raise ProfileStoreError("delete-confirmation-required")

    @staticmethod
    def _active_deletion_requests(
        current: Mapping[str, Any], now: dt.datetime
    ) -> dict[str, dict[str, str]]:
        """Validate and retain only unexpired content-free delete requests."""
        from .profile import ProfileStoreError

        if not current:
            return {}
        if current.get("delete_confirmation_schema_version") != 1:
            raise ProfileStoreError("delete-confirmation-state-corrupt")
        raw_requests = current.get("requests")
        if not isinstance(raw_requests, Mapping):
            raise ProfileStoreError("delete-confirmation-state-corrupt")
        active: dict[str, dict[str, str]] = {}
        for raw_subject, raw_request in raw_requests.items():
            if not isinstance(raw_subject, str) or not raw_subject.strip():
                raise ProfileStoreError("delete-confirmation-state-corrupt")
            if not isinstance(raw_request, Mapping):
                raise ProfileStoreError("delete-confirmation-state-corrupt")
            request: dict[str, str] = {}
            for key in (
                "owner_sender_id",
                "request_message_id",
                "request_utc",
                "expires_utc",
            ):
                value = raw_request.get(key)
                if not isinstance(value, str):
                    raise ProfileStoreError("delete-confirmation-state-corrupt")
                request[key] = value.strip()
            if not all(request.values()):
                raise ProfileStoreError("delete-confirmation-state-corrupt")
            try:
                request_time = dt.datetime.fromisoformat(
                    request["request_utc"].replace("Z", "+00:00")
                )
                expires = dt.datetime.fromisoformat(
                    request["expires_utc"].replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise ProfileStoreError("delete-confirmation-state-corrupt") from exc
            if request_time.tzinfo is None or expires.tzinfo is None:
                raise ProfileStoreError("delete-confirmation-state-corrupt")
            request_time = request_time.astimezone(dt.timezone.utc)
            expires = expires.astimezone(dt.timezone.utc)
            if expires != request_time + dt.timedelta(
                seconds=DELETION_CONFIRMATION_TTL_SECONDS
            ):
                raise ProfileStoreError("delete-confirmation-state-corrupt")
            if expires.astimezone(dt.timezone.utc) > now:
                active[raw_subject.strip()] = request
        return active

    def request_profile_deletion(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Record the first, one-time owner action for permanent deletion."""
        from .profile import ProfileStoreError, _profile_from_status

        subject = str(subject or "").strip()
        sender_id = str(sender_id or "").strip()
        action = "health.profile.delete.request"
        with self._recent_message_lock:
            profile = _profile_from_status(
                self.read_subject_status(subject, _allow_profile_state=True)
            )
            if profile.get("owner_sender_id") != sender_id:
                self._append_audit_event(
                    "access_denied",
                    {
                        "subject": subject,
                        "actor_role": "unknown",
                        "actor_id": sender_id,
                        "action": action,
                        "object_id": subject,
                        "result": "denied",
                        "reason": "delete-owner-mismatch",
                    },
                )
                raise ProfileStoreError("delete-owner-mismatch")
            if not self.message_verifier.verify_access_receipt(
                action=action,
                subject=subject,
                actor_sender_id=sender_id,
                target_sender_id=sender_id,
                message_id=message_id,
                message_utc=message_utc,
                token=verification_token,
            ):
                raise ProfileStoreError("unverified-access-receipt")
            request_time, now = self._validate_access_receipt(
                subject, message_id, message_utc
            )
            expires = request_time + dt.timedelta(
                seconds=DELETION_CONFIRMATION_TTL_SECONDS
            )
            if expires <= now:
                raise ProfileStoreError("delete-confirmation-window-expired")

            def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
                active = self._active_deletion_requests(current, now)
                if subject in active:
                    raise ProfileStoreError("delete-confirmation-pending")
                active[subject] = {
                    "owner_sender_id": sender_id,
                    "request_message_id": message_id,
                    "request_utc": request_time.isoformat(),
                    "expires_utc": expires.isoformat(),
                }
                return {
                    "delete_confirmation_schema_version": 1,
                    "requests": active,
                }, {
                    "expires_utc": expires.isoformat(),
                }

            result = self.mutate_subject_status(
                _DELETION_CONFIRMATION_SUBJECT, mutate
            )
            self.consume_access_receipt(subject, message_id, message_utc)
            self._append_audit_event(
                "profile_deletion_requested",
                {
                    "subject": subject,
                    "actor_role": "owner",
                    "actor_id": sender_id,
                    "action": action,
                    "object_id": subject,
                    "result": "pending",
                    "reason": "second-owner-confirmation-required",
                },
            )
            return {
                "subject": subject,
                "deleted": False,
                "request_message_id": message_id,
                "expires_utc": result["expires_utc"],
            }

    def confirm_profile_deletion(
        self,
        subject: str,
        sender_id: str,
        request_message_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
        *,
        memory_projection: Any | None = None,
    ) -> Mapping[str, Any]:
        """Destroy a profile only with a distinct current owner confirmation."""
        from .profile import ProfileStoreError

        subject = str(subject or "").strip()
        sender_id = str(sender_id or "").strip()
        request_message_id = str(request_message_id or "").strip()
        action = "health.profile.delete.confirm"
        if not request_message_id:
            raise ProfileStoreError("delete-request-message-id-required")
        if message_id == request_message_id:
            raise ProfileStoreError("delete-confirmation-must-be-distinct")
        with self._recent_message_lock:
            if not self.message_verifier.verify_access_receipt(
                action=action,
                subject=subject,
                actor_sender_id=sender_id,
                target_sender_id=sender_id,
                message_id=message_id,
                message_utc=message_utc,
                token=verification_token,
            ):
                raise ProfileStoreError("unverified-access-receipt")
            confirmation_time, now = self._validate_access_receipt(
                subject, message_id, message_utc
            )
            state = self.read_subject_status(
                _DELETION_CONFIRMATION_SUBJECT, _allow_profile_state=True
            ) or {}
            pending = self._active_deletion_requests(state, now).get(subject)
            if pending is None:
                raise ProfileStoreError("delete-confirmation-missing-or-expired")
            if pending["owner_sender_id"] != sender_id:
                raise ProfileStoreError("delete-confirmation-owner-mismatch")
            if pending["request_message_id"] != request_message_id:
                raise ProfileStoreError("delete-confirmation-request-mismatch")
            try:
                request_time = dt.datetime.fromisoformat(
                    pending["request_utc"].replace("Z", "+00:00")
                ).astimezone(dt.timezone.utc)
                expires = dt.datetime.fromisoformat(
                    pending["expires_utc"].replace("Z", "+00:00")
                ).astimezone(dt.timezone.utc)
            except (AttributeError, TypeError, ValueError) as exc:
                raise ProfileStoreError("delete-confirmation-state-corrupt") from exc
            if confirmation_time <= request_time:
                raise ProfileStoreError("delete-confirmation-not-after-request")
            if confirmation_time > expires:
                raise ProfileStoreError("delete-confirmation-expired")
            with self._recording_attempt_condition:
                self._recording_stopping_subjects.add(subject)
                try:
                    self._wait_for_recording_attempts(subject)
                    result = self._delete_profile_after_confirmation_locked(
                        subject,
                        sender_id,
                        message_id,
                        message_utc,
                        verification_token,
                        memory_projection=memory_projection,
                    )
                finally:
                    self._recording_stopping_subjects.discard(subject)
                    self._recording_attempt_condition.notify_all()

            def clear_request(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], None]:
                active = self._active_deletion_requests(current, now)
                active.pop(subject, None)
                return {
                    "delete_confirmation_schema_version": 1,
                    "requests": active,
                }, None

            self.mutate_subject_status(_DELETION_CONFIRMATION_SUBJECT, clear_request)
            return result

    def profile_deletion_status(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Expose deletion liveness only to a current owner-confirmation turn."""
        from .profile import ProfileStoreError, _profile_from_status

        subject = str(subject or "").strip()
        sender_id = str(sender_id or "").strip()
        action = "health.profile.delete.confirm"
        # A process can still be alive after a filesystem failure between key
        # destruction and state cleanup.  Recover the durable intent before
        # attempting to decode the profile row for this read-only status seam.
        self._recover_committed_profile_deletions()
        profile = self.read_subject_status(subject, _allow_profile_state=True)
        if profile is not None:
            owner_sender_id = str(
                _profile_from_status(profile).get("owner_sender_id", "")
            ).strip()
        else:
            # A deleted profile no longer retains its owner record.  The
            # production sidecar's configured owner remains the sole recovery
            # principal for its one terminal acknowledgement.
            owner_sender_id = self.expected_owner_sender_id
        if not owner_sender_id or sender_id != owner_sender_id:
            raise ProfileStoreError("delete-status-owner-mismatch")
        if not self.message_verifier.verify_access_receipt(
            action=action,
            subject=subject,
            actor_sender_id=sender_id,
            target_sender_id=sender_id,
            message_id=message_id,
            message_utc=message_utc,
            token=verification_token,
        ):
            raise ProfileStoreError("unverified-access-receipt")
        self._validate_access_receipt(
            subject,
            message_id,
            message_utc,
            allow_consumed=True,
        )
        profile_exists = self.read_subject_status(
            subject, _allow_profile_state=True
        ) is not None
        if not profile_exists:
            # A durable tombstone may still be retrying only its
            # content-free confirmation-ledger cleanup.  The profile is
            # already irreversibly gone, so never expose a stale pending
            # request or make the terminal acknowledgement wait on it.
            return {
                "subject": subject,
                "profile_exists": False,
                "deletion_pending": False,
                "request_message_id": None,
                "deleted": True,
            }
        state = self.read_subject_status(
            _DELETION_CONFIRMATION_SUBJECT, _allow_profile_state=True
        ) or {}
        active = self._active_deletion_requests(
            state, self._now_utc().astimezone(dt.timezone.utc)
        )
        pending_request = active.get(subject)
        return {
            "subject": subject,
            "profile_exists": profile_exists,
            "deletion_pending": pending_request is not None,
            "request_message_id": (
                pending_request["request_message_id"]
                if pending_request is not None
                else None
            ),
            "deleted": not profile_exists,
        }

    def _delete_profile_after_confirmation_locked(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
        *,
        memory_projection: Any | None = None,
    ) -> Mapping[str, Any]:
        """Serialize destruction with any last in-flight delivery audit."""
        with self._state_lock:
            return self._delete_profile_after_confirmation_locked_unlocked(
                subject,
                sender_id,
                message_id,
                message_utc,
                verification_token,
                memory_projection=memory_projection,
            )

    def _delete_profile_after_confirmation_locked_unlocked(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        verification_token: str,
        *,
        memory_projection: Any | None = None,
    ) -> Mapping[str, Any]:
        """Delete one owner's profile while preserving only a proof event."""
        from .profile import ProfileStoreError, _profile_from_status

        subject = subject.strip()
        sender_id = sender_id.strip()
        action = "health.profile.delete.confirm"
        profile = _profile_from_status(
            self.read_subject_status(subject, _allow_profile_state=True)
        )
        if profile.get("owner_sender_id") != sender_id:
            self._append_audit_event(
                "access_denied",
                {
                    "subject": subject,
                    "actor_role": "unknown",
                    "actor_id": sender_id,
                    "action": action,
                    "object_id": subject,
                    "result": "denied",
                    "reason": "delete-owner-mismatch",
                },
            )
            raise ProfileStoreError("delete-owner-mismatch")
        if not self.message_verifier.verify_access_receipt(
            action=action,
            subject=subject,
            actor_sender_id=sender_id,
            target_sender_id=sender_id,
            message_id=message_id,
            message_utc=message_utc,
            token=verification_token,
        ):
            self._append_audit_event(
                "access_denied",
                {
                    "subject": subject,
                    "actor_role": "owner",
                    "actor_id": sender_id,
                    "action": action,
                    "object_id": subject,
                    "result": "denied",
                    "reason": "unverified-access-receipt",
                },
            )
            raise ProfileStoreError("unverified-access-receipt")

        # Check expiry and one-time use before touching the external memory
        # projection.  A stale or replayed receipt must have no side effect.
        self._validate_access_receipt(subject, message_id, message_utc)

        # Rekey legacy master-scoped rows and backups before any destructive
        # side effect, so every retained copy is protected by the profile key.
        self._migrate_legacy_profile_storage()

        # The profile evidence ledger normally prevents ingress replay. Preserve
        # only still-valid message nonces before destroying that ledger so an
        # attacker cannot recreate the profile with an old signed envelope.
        self._retain_recent_ingress_receipts(profile)

        # Deletion is fail-closed until a real Hermes-memory projection port
        # confirms removal.  The default placeholder deliberately returns
        # False, so the profile and its key remain available for retry.
        if memory_projection is None:
            self._append_audit_event(
                "profile_delete_failed",
                {
                    "subject": subject,
                    "actor_role": "owner",
                    "actor_id": sender_id,
                    "action": action,
                    "object_id": subject,
                    "result": "failed",
                    "reason": "memory-projection-required",
                },
            )
            raise StoreError("memory-projection-required")
        try:
            projection_removed = bool(
                memory_projection.remove_health_projection(subject)
            )
        except Exception as exc:
            self._append_audit_event(
                "profile_delete_failed",
                {
                    "subject": subject,
                    "actor_role": "owner",
                    "actor_id": sender_id,
                    "action": action,
                    "object_id": subject,
                    "result": "failed",
                    "reason": "memory-projection-remove-failed",
                },
            )
            raise StoreError("memory-projection-remove-failed") from exc
        if not projection_removed:
            self._append_audit_event(
                "profile_delete_failed",
                {
                    "subject": subject,
                    "actor_role": "owner",
                    "actor_id": sender_id,
                    "action": action,
                    "object_id": subject,
                    "result": "failed",
                    "reason": "memory-projection-not-removed",
                },
            )
            raise StoreError("memory-projection-not-removed")

        self.consume_access_receipt(subject, message_id, message_utc)

        # Make the pre-delete encrypted copy first.  Once the profile key is
        # destroyed this copy remains physically present but unreadable.
        self._make_backup()
        recording_consent = self.read_subject_status(
            _RECORDING_CONSENT_SUBJECT, _allow_profile_state=True
        ) or {}
        clear_recording_consent = (
            isinstance(recording_consent, Mapping)
            and recording_consent.get("profile_subject") == subject
        )
        self._mark_profile_deletion_committed(
            subject,
            sender_id,
            action=action,
            clear_recording_consent=clear_recording_consent,
        )
        result = self._finalize_committed_profile_deletion(
            subject,
            sender_id,
            action=action,
            clear_recording_consent=clear_recording_consent,
        )
        return {**result, "projection_removed": projection_removed}

    def purge_expired_backups(self) -> Mapping[str, int]:
        """Remove encrypted backup files at the 30-day retention boundary."""
        cutoff = self._now_utc().astimezone(dt.timezone.utc) - dt.timedelta(
            days=BACKUP_RETENTION_DAYS
        )
        deleted = 0
        failed = 0
        managed_backups = list(
            self.backup_dir.glob(f"{self.store_path.name}.*.bak")
        ) + list(self.backup_dir.glob("pre-restore-*.bak"))
        state_prefix = f"{self.store_path.name}."
        restore_prefix = "pre-restore-"
        for backup in managed_backups:
            name = backup.name
            if name.startswith(state_prefix) and name.endswith(".bak"):
                stamp = name[len(state_prefix) : -4]
            elif name.startswith(restore_prefix) and name.endswith(".bak"):
                stamp = name[len(restore_prefix) : -4]
            else:
                continue
            try:
                backup_time = dt.datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ").replace(
                    tzinfo=dt.timezone.utc
                )
            except ValueError:
                continue
            if backup_time > cutoff:
                continue
            try:
                backup.unlink()
            except OSError:
                failed += 1
            else:
                deleted += 1
        self._purge_expired_audit_events()
        return {"deleted": deleted, "failed": failed}

    def _rewrite_audit_after_profile_delete(
        self, subject: str, sender_id: str, key_destroyed: bool, *, action: str
    ) -> None:
        with self._audit_lock:
            with _cross_process_file_lock(self.audit_path):
                retained: list[dict[str, Any]] = []
                for event in self._read_audit_events_unlocked(limit=None):
                    details = event.get("details")
                    try:
                        _validate_audit_record(
                            event.get("event"), details, utc=event.get("utc")
                        )
                    except StoreError:
                        continue
                    if isinstance(details, Mapping) and details.get("subject") == subject:
                        continue
                    # Delivery audits written before Ticket 21 had no profile
                    # scope.  The partner ledger is single-profile, so an
                    # unscoped legacy Weixin delivery event can only belong to
                    # the subject being deleted and must not outlive it.
                    if (
                        event.get("event") in _PROFILE_DELIVERY_AUDIT_EVENTS
                        and isinstance(details, Mapping)
                        and not str(details.get("subject", "")).strip()
                    ):
                        continue
                    retained.append(event)
                now = self._now_utc().astimezone(dt.timezone.utc).replace(microsecond=0)
                retained.append(
                    {
                        "utc": now.isoformat(),
                        "event": "profile_deleted",
                        "details": {
                            "subject": subject,
                            "actor_role": "owner",
                            "actor_id": sender_id,
                            "action": action,
                            "object_id": subject,
                            "result": "deleted",
                            "key_destroyed": bool(key_destroyed),
                            "retain_until_utc": (
                                now + dt.timedelta(days=AUDIT_RETENTION_DAYS)
                            ).isoformat(),
                        },
                    }
                )
                self._write_audit_events_unlocked(retained)

    def purge_expired_audit_events(self) -> Mapping[str, int]:
        """Delete only expired content-free audit records."""
        with self._audit_lock:
            with _cross_process_file_lock(self.audit_path):
                if not self.audit_path.exists():
                    return {"deleted": 0, "retained": 0}
                cutoff = self._now_utc().astimezone(dt.timezone.utc) - dt.timedelta(
                    days=AUDIT_RETENTION_DAYS
                )
                events = self._read_audit_events_unlocked(limit=None)
                retained: list[dict[str, Any]] = []
                for event in events:
                    try:
                        _validate_audit_record(
                            event.get("event"),
                            event.get("details"),
                            utc=event.get("utc"),
                        )
                    except StoreError:
                        continue
                    try:
                        parsed = dt.datetime.fromisoformat(
                            str(event.get("utc", "")).replace("Z", "+00:00")
                        )
                        if parsed.tzinfo is None:
                            raise ValueError("audit timestamp must be timezone-aware")
                        event_time = parsed.astimezone(dt.timezone.utc)
                    except (TypeError, ValueError):
                        retained.append(event)
                        continue
                    if event_time >= cutoff:
                        retained.append(event)
                self._write_audit_events_unlocked(retained)
                return {"deleted": len(events) - len(retained), "retained": len(retained)}

    def _purge_expired_audit_events(self) -> None:
        self.purge_expired_audit_events()

    def _write_audit_events(self, events: list[Mapping[str, Any]]) -> None:
        with self._audit_lock:
            with _cross_process_file_lock(self.audit_path):
                self._write_audit_events_unlocked(events)

    def _write_audit_events_unlocked(self, events: list[Mapping[str, Any]]) -> None:
        temporary = self.audit_path.with_suffix(".audit.tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            for event in events:
                try:
                    _validate_audit_record(
                        event.get("event"),
                        event.get("details"),
                        utc=event.get("utc"),
                    )
                except StoreError:
                    continue
                handle.write(
                    json.dumps(dict(event), ensure_ascii=False, separators=(",", ":"))
                )
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _harden_file(temporary)
        os.replace(temporary, self.audit_path)

    def metadata(self) -> dict[str, Any]:
        return dict(self._read_metadata())

    def _read_metadata(self) -> dict[str, Any]:
        with self._open_db(mutable=False) as conn:
            rows = conn.execute("SELECT k,v FROM metadata;").fetchall()
        result = {}
        for key, value in rows:
            if key == "global_version":
                result["version"] = int(value)
            elif key == "updated_utc":
                result["updated_utc"] = value
            else:
                result[key] = value
        return result

    def _get_record(self, conn: sqlite3.Connection, subject: str) -> dict[str, str] | None:
        cursor = conn.execute(
            "SELECT subject,schema_version,key_scope,wrapped_key,nonce,mac,payload FROM state_records WHERE subject=?;",
            (subject.strip(),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "subject": str(row[0]),
            "schema_version": str(row[1]),
            "key_scope": str(row[2]),
            "wrapped_key": row[3],
            "nonce": row[4],
            "mac": row[5],
            "payload": row[6],
        }

    def append_audit_event(self, event: str, details: Mapping[str, Any] | None = None) -> None:
        self._append_audit_event(event, details or {})

    def append_audit_event_once(
        self,
        event_id: str,
        event: str,
        details: Mapping[str, Any] | None = None,
    ) -> bool:
        """Append one durable audit event for a stable idempotency key."""
        normalized_id = str(event_id).strip()
        if not _AUDIT_ID.fullmatch(normalized_id):
            raise StoreError("audit-content-forbidden")
        normalized_details = dict(details or {})
        if "audit_event_id" in normalized_details:
            raise StoreError("audit-content-forbidden")
        normalized_details["audit_event_id"] = normalized_id
        _validate_audit_record(event, normalized_details)
        def append_once() -> bool:
            with self._audit_lock:
                with _cross_process_file_lock(self.audit_path):
                    for existing in self._read_audit_events_unlocked(limit=None):
                        existing_details = existing.get("details")
                        if (
                            isinstance(existing_details, Mapping)
                            and existing_details.get("audit_event_id") == normalized_id
                        ):
                            return False
                    payload = {
                        "utc": self._now_utc().replace(microsecond=0).isoformat(),
                        "event": event,
                        "details": normalized_details,
                    }
                    line = json.dumps(
                        payload, ensure_ascii=False, separators=(",", ":")
                    )
                    with open(self.audit_path, "a", encoding="utf-8") as handle:
                        handle.write(line)
                        handle.write("\n")
                    try:
                        self.audit_path.chmod(0o600)
                    except OSError:
                        pass
            return True

        protected_subject = str(normalized_details.get("subject", "")).strip()
        if event in _PROFILE_DELIVERY_AUDIT_EVENTS and protected_subject:
            # Hold the state boundary until the content-free delivery audit is
            # durable.  Deletion either follows and rewrites it away, or wins
            # first and makes this late audit fail closed; it cannot append
            # after the profile-deletion proof event.
            with self._state_lock:
                if self.read_subject_status(
                    protected_subject, _allow_profile_state=True
                ) is None:
                    raise StoreError("profile-deleted-delivery-audit-forbidden")
                return append_once()
        return append_once()

    def read_audit_events(self, limit: int | None = 100) -> list[dict[str, Any]]:
        if limit is not None and limit < 1:
            raise StoreError("audit-limit-must-be-positive")
        with self._audit_lock:
            with _cross_process_file_lock(self.audit_path):
                return self._read_audit_events_unlocked(limit)

    def _read_audit_events_unlocked(
        self, limit: int | None = 100
    ) -> list[dict[str, Any]]:
        if limit is not None and limit < 1:
            raise StoreError("audit-limit-must-be-positive")
        if not self.audit_path.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise StoreError(f"failed-read-audit:{exc}") from exc
        selected_lines = lines if limit is None else lines[-limit:]
        for raw in selected_lines:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise StoreError("invalid-audit-event") from exc
            if not isinstance(event, dict):
                raise StoreError("audit-event-must-be-object")
            events.append(event)
        return events

    def read_operational_audit_events(
        self, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return a metadata-only audit projection for an external monitor."""
        projected: list[dict[str, Any]] = []
        for event in self.read_audit_events(limit=limit):
            details = event.get("details")
            try:
                _validate_audit_record(
                    event.get("event"), details, utc=event.get("utc")
                )
            except StoreError:
                continue
            if not isinstance(details, Mapping):
                continue
            safe_details: dict[str, Any] = {}
            for key in _OPERATIONAL_AUDIT_KEYS:
                value = details.get(key)
                if value is None:
                    continue
                if key == "evidence_ids":
                    if isinstance(value, list) and all(
                        isinstance(item, str) and item.strip() for item in value
                    ):
                        safe_details[key] = [str(item) for item in value]
                    continue
                if isinstance(value, (str, int, float, bool)):
                    safe_details[key] = value
            projected.append(
                {
                    "utc": str(event.get("utc", "")),
                    "event": str(event.get("event", "")),
                    "details": safe_details,
                }
            )
        return projected

    def _append_audit_event(
        self, event: str, details: Mapping[str, Any] | None
    ) -> None:
        self._append_audit_events(((event, dict(details or {})),))

    def _append_audit_events(
        self,
        events: tuple[tuple[str, Mapping[str, Any]], ...],
        *,
        post_append_validator: Callable[[], None] | None = None,
    ) -> None:
        """Append a validated audit batch without leaving partial lines."""
        payloads: list[bytes] = []
        for event, details in events:
            _validate_audit_record(event, details)
            payload = {
                "utc": self._now_utc().replace(microsecond=0).isoformat(),
                "event": event,
                "details": dict(details),
            }
            payloads.append(
                (
                    json.dumps(
                        payload, ensure_ascii=False, separators=(",", ":")
                    )
                    + "\n"
                ).encode("utf-8")
            )
        if not payloads:
            return
        with self._audit_lock:
            with _cross_process_file_lock(self.audit_path):
                try:
                    existed = self.audit_path.exists()
                    prior_size = self.audit_path.stat().st_size if existed else 0
                    with open(self.audit_path, "a+b") as handle:
                        try:
                            handle.write(b"".join(payloads))
                            handle.flush()
                            os.fsync(handle.fileno())
                            if post_append_validator is not None:
                                post_append_validator()
                        except Exception:
                            handle.seek(prior_size)
                            handle.truncate()
                            handle.flush()
                            os.fsync(handle.fileno())
                            raise
                    _harden_file(self.audit_path)
                except Exception:
                    if not existed:
                        try:
                            self.audit_path.unlink()
                        except FileNotFoundError:
                            pass
                    self._fsync_parent_directory(self.audit_path.parent)
                    raise
                self._fsync_parent_directory(self.audit_path.parent)

    def _make_backup(self) -> None:
        if not self.store_path.exists():
            return
        timestamp = self._now_utc().strftime("%Y%m%dT%H%M%S%fZ")
        backup_name = f"{self.store_path.name}.{timestamp}.bak"
        destination = self.backup_dir / backup_name
        shutil.copy2(self.store_path, destination)
        try:
            destination.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def _open_db(self, mutable: bool) -> Iterator[sqlite3.Connection]:
        with self._state_lock:
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            try:
                if self.store_path.exists():
                    encrypted = self.store_path.read_bytes()
                    plain_bytes = self._decrypt_database_blob(encrypted)
                    try:
                        conn.deserialize(plain_bytes)
                    except sqlite3.Error as exc:
                        raise StoreError(f"invalid-sqlite-state:{exc}") from exc
                self._ensure_schema(conn)
                yield conn
                if mutable:
                    conn.commit()
                    self._persist_state(conn)
                    _harden_file(self.store_path)
            finally:
                conn.close()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata(
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state_records(
                subject TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                version INTEGER NOT NULL,
                updated_utc TEXT NOT NULL,
                key_scope TEXT NOT NULL DEFAULT 'master',
                wrapped_key TEXT NOT NULL,
                nonce TEXT NOT NULL,
                mac TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_deletion_tombstones(
                subject TEXT PRIMARY KEY,
                owner_sender_id TEXT NOT NULL,
                action TEXT NOT NULL,
                clear_recording_consent INTEGER NOT NULL,
                committed_utc TEXT NOT NULL
            );
            """
        )
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(state_records);").fetchall()
        }
        if "key_scope" not in columns:
            conn.execute(
                "ALTER TABLE state_records ADD COLUMN key_scope TEXT NOT NULL DEFAULT 'master';"
            )
        existing = conn.execute(
            "SELECT 1 FROM metadata WHERE k='schema_version';"
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO metadata(k,v) VALUES('schema_version',?);",
                (str(_SCHEMA_VERSION),),
            )
        existing_version = conn.execute(
            "SELECT 1 FROM metadata WHERE k='global_version';"
        ).fetchone()
        if existing_version is None:
            conn.execute(
                "INSERT INTO metadata(k,v) VALUES('global_version','0');"
            )

    def _persist_state(self, conn: sqlite3.Connection) -> None:
        try:
            data = conn.serialize()
        except sqlite3.Error as exc:
            raise StoreError(f"sqlite-serialize-failed:{exc}") from exc
        self._atomic_write_encrypted(self._encrypt_database_blob(data))

    def _atomic_write_encrypted(
        self, encrypted: bytes, target_path: Path | None = None
    ) -> None:
        target = Path(target_path) if target_path is not None else self.store_path
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as handle:
                file_descriptor = -1
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            _harden_file(temporary_path)
            os.replace(temporary_path, target)
            self._fsync_parent_directory(target.parent)
        finally:
            if file_descriptor != -1:
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass
            try:
                temporary_path.unlink()
            except OSError:
                pass

    def _fsync_parent_directory(self, directory: Path | None = None) -> None:
        directory = directory or self.store_path.parent
        try:
            directory_fd = os.open(str(directory), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            os.close(directory_fd)

    def _load_or_generate_record_key(self) -> bytes:
        return self.key_manager.generate_record_key()

    @staticmethod
    def _profile_key_id(subject: str) -> str:
        return hashlib.sha256(subject.encode("utf-8")).hexdigest()

    def _load_profile_key(self, subject: str, *, create: bool) -> bytes:
        subject = subject.strip()
        if subject in self._destroyed_profile_keys and not create:
            raise StoreError("profile-key-destroyed")
        if subject in self._destroyed_profile_keys and create:
            self._destroyed_profile_keys.discard(subject)
        if subject in self._profile_key_cache:
            return self._profile_key_cache[subject]
        if create:
            loader = getattr(self.key_manager, "load_or_create_profile_key", None)
        else:
            loader = getattr(self.key_manager, "load_profile_key", None)
        if callable(loader):
            key = loader(self.profile_key_dir, subject)
        else:
            # Legacy controlled key fakes predate the profile-key methods. The
            # store still keeps a separate random file rather than deriving a
            # profile key from the shared master key.
            path = self.profile_key_dir / f"{self._profile_key_id(subject)}.key"
            if create:
                self.profile_key_dir.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    key = path.read_bytes()
                else:
                    key = secrets.token_bytes(_KEY_BYTES)
                    with open(path, "xb") as handle:
                        handle.write(key)
                    _harden_file(path)
            else:
                try:
                    key = path.read_bytes()
                except FileNotFoundError as exc:
                    raise StoreError("profile-key-destroyed") from exc
        if not isinstance(key, bytes) or len(key) != _KEY_BYTES:
            raise StoreError("invalid-profile-key")
        self._profile_key_cache[subject] = key
        return key

    def _destroy_profile_key(self, subject: str) -> bool:
        subject = subject.strip()
        destroyer = getattr(self.key_manager, "destroy_profile_key", None)
        if callable(destroyer):
            destroyed = bool(destroyer(self.profile_key_dir, subject))
        else:
            path = self.profile_key_dir / f"{self._profile_key_id(subject)}.key"
            try:
                path.unlink()
            except FileNotFoundError:
                destroyed = False
            except OSError as exc:
                raise StoreError(f"failed-destroy-profile-key:{exc}") from exc
            else:
                destroyed = True
        self._profile_key_cache.pop(subject, None)
        self._destroyed_profile_keys.add(subject)
        if destroyed:
            self._fsync_parent_directory(self.profile_key_dir)
        return destroyed

    def _wrap_record_key(self, rec_key: bytes) -> str:
        nonce = secrets.token_bytes(_NONCE_BYTES)
        stream = self._keystream(self.key, nonce, _KEY_BYTES)
        wrapped = _xor_bytes(rec_key, stream)
        mac = hmac.new(self.key, nonce + wrapped, hashlib.sha256).digest()
        payload = nonce + mac + wrapped
        return base64.urlsafe_b64encode(payload).decode("ascii")

    def _unwrap_record_key(self, wrapped_key: str) -> bytes:
        try:
            raw = base64.urlsafe_b64decode(wrapped_key.encode("ascii"))
        except Exception as exc:
            raise StoreError("invalid-wrapped-key") from exc
        if len(raw) < _NONCE_BYTES + _MAC_BYTES + 1:
            raise StoreError("wrapped-key-too-short")
        nonce = raw[:_NONCE_BYTES]
        mac = raw[_NONCE_BYTES : _NONCE_BYTES + _MAC_BYTES]
        wrapped = raw[_NONCE_BYTES + _MAC_BYTES :]
        calc = hmac.new(self.key, nonce + wrapped, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, calc):
            raise StoreError("wrapped-key-auth-failed")
        return _xor_bytes(wrapped, self._keystream(self.key, nonce, len(wrapped)))

    def _encrypt_payload(self, text: str, rec_key: bytes) -> tuple[bytes, bytes, bytes]:
        plain = text.encode("utf-8")
        nonce = secrets.token_bytes(_NONCE_BYTES)
        stream = self._keystream(rec_key, nonce, len(plain))
        cipher = _xor_bytes(plain, stream)
        mac = hmac.new(rec_key, nonce + cipher, hashlib.sha256).digest()
        return nonce + mac + cipher, nonce, mac

    def encrypt_blob(self, data: bytes) -> bytes:
        """Encrypt one sidecar-owned blob with a fresh wrapped record key."""
        if not isinstance(data, bytes):
            raise StoreError("blob-must-be-bytes")
        record_key = self._load_or_generate_record_key()
        wrapped_key = self._wrap_record_key(record_key)
        encoded = base64.urlsafe_b64encode(data).decode("ascii")
        cipher_blob, nonce, mac = self._encrypt_payload(encoded, record_key)
        return json.dumps(
            {
                "schema_version": _SCHEMA_VERSION,
                "wrapped_key": wrapped_key,
                "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
                "mac": base64.urlsafe_b64encode(mac).decode("ascii"),
                "payload": base64.urlsafe_b64encode(cipher_blob).decode("ascii"),
            },
            separators=(",", ":"),
        ).encode("utf-8")

    def _decrypt_record(self, row: dict[str, str]) -> dict[str, Any]:
        if row.get("key_scope") == "profile":
            rec_key = self._load_profile_key(row["subject"], create=False)
        else:
            rec_key = self._unwrap_record_key(row["wrapped_key"])
        payload_b64 = row["payload"]
        try:
            payload = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        except Exception as exc:
            raise StoreError("invalid-payload-b64") from exc
        if len(payload) < _NONCE_BYTES + _MAC_BYTES + 1:
            raise StoreError("payload-too-short")
        nonce = payload[:_NONCE_BYTES]
        mac = payload[_NONCE_BYTES : _NONCE_BYTES + _MAC_BYTES]
        cipher = payload[_NONCE_BYTES + _MAC_BYTES :]
        calc = hmac.new(rec_key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, calc):
            raise StoreError("payload-auth-failed")
        plain = _xor_bytes(cipher, self._keystream(rec_key, nonce, len(cipher)))
        return json.loads(plain.decode("utf-8"))

    def _encrypt_database_blob(self, plain: bytes) -> bytes:
        nonce = secrets.token_bytes(_NONCE_BYTES)
        stream = self._keystream(self.key, nonce, len(plain))
        cipher = _xor_bytes(plain, stream)
        mac = hmac.new(self.key, nonce + cipher, hashlib.sha256).digest()
        return nonce + mac + cipher

    def _decrypt_database_blob(self, blob: bytes) -> bytes:
        if blob.startswith(b"SQLite format 3\0"):
            raise StoreError("plaintext-database-refused")
        if len(blob) < _NONCE_BYTES + _MAC_BYTES:
            raise StoreError("database-blob-too-short")
        nonce = blob[:_NONCE_BYTES]
        mac = blob[_NONCE_BYTES : _NONCE_BYTES + _MAC_BYTES]
        cipher = blob[_NONCE_BYTES + _MAC_BYTES :]
        if not cipher:
            raise StoreError("database-blob-empty")
        calc = hmac.new(self.key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, calc):
            raise StoreError("database-auth-failed")
        return _xor_bytes(cipher, self._keystream(self.key, nonce, len(cipher)))

    @staticmethod
    def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
        if not isinstance(key, (bytes, bytearray)) or len(key) != _KEY_BYTES:
            raise StoreError("invalid-key")
        out = bytearray()
        counter = 0
        while len(out) < length:
            block = hmac.new(
                key, nonce + counter.to_bytes(4, "big"), hashlib.sha256
            ).digest()
            out.extend(block)
            counter += 1
        return bytes(out[:length])

def _xor_bytes(left: bytes, right: bytes) -> bytes:
    if len(left) != len(right):
        raise StoreError("stream-length-mismatch")
    return bytes(a ^ b for a, b in zip(left, right))


def validate_encrypted_database_backup(
    backup_path: str | os.PathLike[str], key_path: str | os.PathLike[str]
) -> None:
    """Authenticate an encrypted backup and verify its in-memory SQLite image.

    This deliberately does not instantiate ``HealthSidecarStore``: validation
    must not migrate or rewrite the live database, its backups, or profile keys.
    """
    try:
        blob = Path(backup_path).read_bytes()
        key = Path(key_path).read_bytes()
    except OSError as exc:
        raise StoreError(f"backup-validation-read-failed:{exc}") from exc
    if len(key) != _KEY_BYTES:
        raise StoreError("invalid-key")
    if blob.startswith(b"SQLite format 3\0"):
        raise StoreError("plaintext-database-refused")
    if len(blob) < _NONCE_BYTES + _MAC_BYTES:
        raise StoreError("database-blob-too-short")
    nonce = blob[:_NONCE_BYTES]
    mac = blob[_NONCE_BYTES : _NONCE_BYTES + _MAC_BYTES]
    cipher = blob[_NONCE_BYTES + _MAC_BYTES :]
    if not cipher:
        raise StoreError("database-blob-empty")
    calculated = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, calculated):
        raise StoreError("database-auth-failed")
    plain = _xor_bytes(cipher, HealthSidecarStore._keystream(key, nonce, len(cipher)))
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(plain)
        result = connection.execute("PRAGMA quick_check;").fetchone()
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
    except sqlite3.Error as exc:
        raise StoreError(f"invalid-sqlite-backup:{exc}") from exc
    finally:
        connection.close()
    if result is None or result[0] != "ok" or not {"metadata", "state_records"}.issubset(tables):
        raise StoreError("sqlite-backup-integrity-failed")

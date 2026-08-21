"""One-time authorization delegated from a verified native Job to sidecar.

The partner plugin verifies the scheduler-bound capability before it creates
one of these short-lived opaque proofs.  The sidecar verifies the proof with a
separate shared integration key and persists the nonce before it performs a
health-bearing Job action.  This prevents another Cron or ordinary plugin
process from calling the privileged socket action merely because it shares the
partner Unix UID.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
from pathlib import Path
from typing import Any, Mapping


JOB_ACTION_AUTHORIZATION_TTL_SECONDS = 600
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ROLES = frozenset({"daily_profile_review", "due_task_dispatch"})


class JobAuthorizationError(RuntimeError):
    """Raised when the isolated Job-action key cannot be read safely."""


def read_job_authorization_secret(path: str | Path) -> bytes:
    """Read the dedicated partner/sidecar integration key without fallback."""
    try:
        secret = Path(path).expanduser().resolve().read_bytes()
    except OSError as exc:
        raise JobAuthorizationError("job-authorization-secret-unavailable") from exc
    if len(secret) < 32:
        raise JobAuthorizationError("job-authorization-secret-invalid")
    return secret


def ensure_job_authorization_secret(path: str | Path) -> Path:
    """Create the partner-owned delegation key once, never rotating it silently."""
    secret_path = Path(path).expanduser().resolve()
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if not secret_path.exists():
        secret_path.write_bytes(secrets.token_bytes(32))
    try:
        # The partner plugin needs only read access to issue a proof; keeping
        # the immutable integration key at 0400 prevents an ordinary runtime
        # process from silently rotating the sidecar trust anchor.
        secret_path.chmod(0o400)
    except OSError:
        pass
    read_job_authorization_secret(secret_path)
    return secret_path


def issue_job_action_authorization(
    secret: bytes,
    *,
    role: str,
    subject: str,
    capability: str,
    issued_utc: dt.datetime | None = None,
) -> str:
    """Sign an opaque sidecar proof only after local capability verification."""
    if role not in _ROLES:
        raise ValueError("job-authorization-role-invalid")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("job-authorization-subject-invalid")
    if not isinstance(capability, str) or not capability.strip():
        raise ValueError("job-authorization-capability-invalid")
    if len(secret) < 32:
        raise ValueError("job-authorization-secret-invalid")
    now = issued_utc or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("job-authorization-time-invalid")
    payload = {
        "role": role,
        "subject": subject.strip(),
        # Bind the server proof to the already verified opaque capability
        # without disclosing that token to the sidecar or its content-free audit.
        "capability_sha256": hashlib.sha256(capability.encode("utf-8")).hexdigest(),
        "issued_utc": now.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "nonce": secrets.token_hex(16),
    }
    body = _encode_body(payload)
    signature = hmac.new(secret, body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_job_action_authorization(
    secret: bytes,
    token: str,
    *,
    role: str,
    subject: str,
    now_utc: dt.datetime | None = None,
) -> Mapping[str, str] | None:
    """Verify proof claims without consuming its nonce.

    The sidecar store owns the durable atomic nonce consumption, so a successful
    verification here is intentionally not enough to authorize replay.
    """
    try:
        if len(secret) < 32 or role not in _ROLES or not subject.strip():
            return None
        body, signature = str(token).split(".", 1)
        expected = hmac.new(secret, body.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, Mapping):
            return None
        if (
            payload.get("role") != role
            or payload.get("subject") != subject.strip()
            or not _NONCE.fullmatch(str(payload.get("nonce") or ""))
            or not _DIGEST.fullmatch(str(payload.get("capability_sha256") or ""))
        ):
            return None
        issued = dt.datetime.fromisoformat(str(payload.get("issued_utc") or ""))
        if issued.tzinfo is None:
            return None
        now = now_utc or dt.datetime.now(dt.timezone.utc)
        if now.tzinfo is None:
            return None
        age = (now.astimezone(dt.timezone.utc) - issued.astimezone(dt.timezone.utc)).total_seconds()
        if age < -60 or age > JOB_ACTION_AUTHORIZATION_TTL_SECONDS:
            return None
        return {
            "nonce": str(payload["nonce"]),
            "issued_utc": issued.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat(),
        }
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError, binascii.Error):
        return None


def _encode_body(payload: Mapping[str, str]) -> str:
    encoded = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


__all__ = [
    "JOB_ACTION_AUTHORIZATION_TTL_SECONDS",
    "JobAuthorizationError",
    "ensure_job_authorization_secret",
    "issue_job_action_authorization",
    "read_job_authorization_secret",
    "verify_job_action_authorization",
]

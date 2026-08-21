"""Controlled dependency ports for the health-steward runtime."""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .store import Clock, KeyManager


class LLMAdapter(Protocol):
    """Controlled boundary for isolated fresh-session model calls."""

    def complete(self, prompt: str, context: Mapping[str, Any]) -> Any:
        ...

    def complete_fresh(
        self, prompt: str, context: Mapping[str, Any], session_id: str
    ) -> Any:
        """Start an independent model session for one dispatch task."""
        ...


class SourceFetchAdapter(Protocol):
    """Controlled boundary for approved source retrieval."""

    def fetch(
        self, url: str, timeout_seconds: float | None = None
    ) -> Mapping[str, Any]:
        ...


class ChannelSendAdapter(Protocol):
    """Controlled boundary for outbound channel delivery."""

    def send(self, recipient: str, message: str) -> None:
        ...

    def send_once(self, recipient: str, message: str, delivery_key: str) -> bool | None:
        """Deliver with a stable idempotency key across retries.

        A channel adapter must deduplicate repeated calls carrying the same
        key.  The legacy ``send`` method remains available for simple callers,
        but the dispatcher will only retry through this idempotent port.
        """
        ...

    def send_json_attachment_once(
        self, recipient: str, attachment_path: Path, delivery_key: str
    ) -> bool | None:
        """Deliver one JSON attachment with the same persistent idempotency key."""
        ...


class MemoryProjectionPort(Protocol):
    """Replace or remove the sidecar-owned one-way Hermes projection."""

    def replace_health_projection(
        self, subject: str, projection: Mapping[str, Any]
    ) -> bool:
        ...

    def remove_health_projection(self, subject: str) -> bool:
        ...


class NoopMemoryProjection:
    """Fail-closed placeholder until the real Hermes memory bridge is wired."""

    def replace_health_projection(
        self, subject: str, projection: Mapping[str, Any]
    ) -> bool:
        del subject, projection
        return False

    def remove_health_projection(self, subject: str) -> bool:
        del subject
        return False


class FileMemoryProjection:
    """Atomically maintain the sidecar-owned Hermes memory bridge file."""

    def __init__(self, projection_path: str | os.PathLike[str]) -> None:
        self.path = Path(projection_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_document(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid-memory-projection:{exc}") from exc
        if not isinstance(document, dict):
            raise RuntimeError("memory-projection-must-be-object")
        return document

    def _write_document(self, document: Mapping[str, Any]) -> None:
        encoded = json.dumps(
            dict(document), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o640)
            os.replace(temporary, self.path)
            if os.name == "posix":
                directory_fd = os.open(
                    str(self.path.parent),
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if descriptor != -1:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            try:
                temporary.unlink()
            except OSError:
                pass

    def replace_health_projection(
        self, subject: str, projection: Mapping[str, Any]
    ) -> bool:
        if not subject.strip() or not isinstance(projection, Mapping):
            return False
        document = self._read_document()
        document[subject] = dict(projection)
        self._write_document(document)
        return True

    def remove_health_projection(self, subject: str) -> bool:
        document = self._read_document()
        if subject not in document:
            return False
        del document[subject]
        self._write_document(document)
        return True


def build_health_memory_projection(
    subject: str, profile: Mapping[str, Any], now_utc: dt.datetime
) -> dict[str, Any]:
    """Build the only health-derived data allowed in ordinary Hermes context."""
    if now_utc.tzinfo is None:
        raise ValueError("projection-time-must-be-aware")
    preferences: list[str] = []
    for conclusion in profile.get("conclusions", []):
        if not isinstance(conclusion, Mapping):
            continue
        if (
            conclusion.get("category") != "interaction_preference"
            or not conclusion.get("active", True)
            or conclusion.get("status") not in {"fact", "tendency"}
        ):
            continue
        valid_until = conclusion.get("valid_until_utc")
        if valid_until:
            try:
                expiry = dt.datetime.fromisoformat(
                    str(valid_until).replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if expiry.tzinfo is None or expiry <= now_utc.astimezone(dt.timezone.utc):
                continue
        text = conclusion.get("text")
        if isinstance(text, str) and text.strip() and len(text.strip()) <= 300:
            preferences.append(text.strip())
    proactive = profile.get("proactive_contact")
    paused = bool(
        profile.get("recording_status") == "recording_stopped"
        or (isinstance(proactive, Mapping) and proactive.get("paused") is True)
    )
    pause_until = (
        proactive.get("pause_until_utc") if isinstance(proactive, Mapping) else None
    )
    if pause_until is not None and not isinstance(pause_until, str):
        pause_until = None
    return {
        "schema_version": 1,
        "archive_pointer": f"health-sidecar://profile/{subject}",
        "interaction_preferences": preferences[:2],
        "proactive_contact": {
            "paused": paused,
            "pause_until_utc": pause_until if paused else None,
        },
    }


@dataclass(frozen=True)
class HealthStewardPorts:
    """All replaceable runtime dependencies used by future health jobs."""

    clock: Clock
    key_manager: KeyManager
    llm: LLMAdapter
    source_fetch: SourceFetchAdapter
    channel_send: ChannelSendAdapter
    memory_projection: MemoryProjectionPort | None = None

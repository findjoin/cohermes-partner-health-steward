"""Opaque current-head port and synthetic conditional-write implementation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CurrentHeadError(RuntimeError):
    pass


class HeadConflict(CurrentHeadError):
    pass


class HeadTimeout(CurrentHeadError):
    pass


class HeadUnknown(CurrentHeadError):
    pass


class HeadTerminal(CurrentHeadError):
    pass


class FailureMode(str, Enum):
    NONE = "none"
    CONFLICT = "conflict"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HeadSnapshot:
    installation_id: str
    generation: int
    revision_digest: str
    transition_id: str
    writer_fence: str
    terminal: bool
    site: str


@dataclass(frozen=True)
class HeadRead:
    head: HeadSnapshot


class InMemoryCurrentHead:
    """Synthetic current-head with opaque metadata and injectable failures."""

    def __init__(self, installation_id: str, site: str = "synthetic-site") -> None:
        self._head = HeadSnapshot(installation_id, 1, "sha256:empty", "transition:empty", "fence:1", False, site)
        self._failure = FailureMode.NONE
        self._failure_operation = "all"

    def set_failure(self, failure: FailureMode, *, operation: str = "all") -> None:
        if operation not in {"all", "read", "advance"}:
            raise ValueError("invalid failure operation")
        self._failure = failure
        self._failure_operation = operation

    def clear_failure(self) -> None:
        self._failure = FailureMode.NONE
        self._failure_operation = "all"

    def read(self) -> HeadRead:
        self._raise_if_failed("read")
        return HeadRead(self._head)

    def conditional_advance(
        self,
        *,
        expected_generation: int,
        expected_revision_digest: str,
        transition_id: str,
        revision_digest: str,
        writer_fence: str | None = None,
    ) -> HeadSnapshot:
        self._raise_if_failed("advance")
        if self._head.terminal:
            raise HeadTerminal("terminal current head")
        if expected_generation != self._head.generation or expected_revision_digest != self._head.revision_digest:
            raise HeadConflict("current-head compare-and-set conflict")
        if writer_fence is not None and writer_fence != self._head.writer_fence:
            raise HeadConflict("stale writer fence")
        next_generation = self._head.generation + 1
        self._head = HeadSnapshot(
            self._head.installation_id,
            next_generation,
            revision_digest,
            transition_id,
            f"fence:{next_generation}",
            False,
            self._head.site,
        )
        return self._head

    def mark_terminal(self) -> HeadSnapshot:
        self._raise_if_failed("advance")
        next_generation = self._head.generation + 1
        self._head = HeadSnapshot(
            self._head.installation_id,
            next_generation,
            self._head.revision_digest,
            f"transition:terminal:{next_generation}",
            f"fence:{next_generation}",
            True,
            self._head.site,
        )
        return self._head

    def _raise_if_failed(self, operation: str) -> None:
        if self._failure_operation not in {"all", operation}:
            return
        if self._failure is FailureMode.CONFLICT:
            raise HeadConflict("synthetic conflict")
        if self._failure is FailureMode.TIMEOUT:
            raise HeadTimeout("synthetic timeout")
        if self._failure is FailureMode.UNKNOWN:
            raise HeadUnknown("synthetic unknown result")

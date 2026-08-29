"""Opaque current-head port and synthetic conditional-write implementation."""

from __future__ import annotations

import threading
import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .authority import (
    AuthoritySnapshot,
    AuthorityValidationError,
    ExecutionLease,
    WriterFenceProof,
    validate_opaque_text,
)


class CurrentHeadError(RuntimeError):
    pass


class HeadConflict(CurrentHeadError):
    pass


class TransitionNotFound(CurrentHeadError):
    """A lookup proved that this exact transition has not been applied."""


class HeadTimeout(CurrentHeadError):
    pass


class HeadUnknown(CurrentHeadError):
    pass


class HeadTerminal(CurrentHeadError):
    pass


class ExecutionLeaseNotFound(CurrentHeadError):
    """No durable current-head lease exists for the requested effect."""

    pass


class FailureMode(str, Enum):
    NONE = "none"
    CONFLICT = "conflict"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    UNKNOWN_AFTER_ADVANCE = "unknown-after-advance"


@dataclass(frozen=True)
class HeadSnapshot(AuthoritySnapshot):
    """Current-head authority, including the active writer site."""

    def __post_init__(self) -> None:
        super().__post_init__()

    def as_authority(self) -> AuthoritySnapshot:
        return AuthoritySnapshot(
            installation_id=self.installation_id,
            generation=self.generation,
            revision_digest=self.revision_digest,
            transition_id=self.transition_id,
            writer_fence=self.writer_fence,
            terminal=self.terminal,
            site=self.site,
        )


@dataclass(frozen=True)
class HeadRead:
    head: HeadSnapshot

    def __post_init__(self) -> None:
        if type(self.head) is not HeadSnapshot:
            raise AuthorityValidationError("invalid current head")


@dataclass(frozen=True)
class _ExecutionOverlapPermit:
    """Internal proof for one bounded pre-freeze effect overlap."""

    active_effect_id: str

    def __post_init__(self) -> None:
        validate_opaque_text(self.active_effect_id, "overlap active effect identifier")


@dataclass(frozen=True)
class AdvanceRequest:
    """The only core-to-current-head write shape."""

    expected: AuthoritySnapshot
    transition_id: str
    revision_digest: str
    writer_fence: str
    operation_digest: str
    writer_proof: WriterFenceProof
    _execution_overlap: _ExecutionOverlapPermit | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self.expected) is not AuthoritySnapshot:
            raise AuthorityValidationError("invalid expected authority")
        validate_opaque_text(self.transition_id, "transition_id")
        validate_opaque_text(self.revision_digest, "revision_digest")
        validate_opaque_text(self.writer_fence, "writer_fence")
        validate_opaque_text(self.operation_digest, "operation_digest")
        if type(self.writer_proof) is not WriterFenceProof:
            raise AuthorityValidationError("invalid advance writer proof")
        if self.writer_fence != self.expected.writer_fence:
            raise AuthorityValidationError("advance request does not hold expected writer fence")
        if self.writer_proof.authority != self.expected:
            raise AuthorityValidationError("advance request writer proof mismatch")
        if self._execution_overlap is not None and type(self._execution_overlap) is not _ExecutionOverlapPermit:
            raise AuthorityValidationError("invalid execution overlap permit")

    def identity(self) -> "AdvanceIdentity":
        return AdvanceIdentity(
            expected=self.expected,
            transition_id=self.transition_id,
            revision_digest=self.revision_digest,
            writer_fence=self.writer_fence,
            operation_digest=self.operation_digest,
        )


@dataclass(frozen=True)
class AdvanceIdentity:
    """Public, durable identity of a conditional advance."""

    expected: AuthoritySnapshot
    transition_id: str
    revision_digest: str
    writer_fence: str
    operation_digest: str

    def __post_init__(self) -> None:
        if type(self.expected) is not AuthoritySnapshot:
            raise AuthorityValidationError("invalid expected authority")
        validate_opaque_text(self.transition_id, "transition_id")
        validate_opaque_text(self.revision_digest, "revision_digest")
        validate_opaque_text(self.writer_fence, "writer_fence")
        validate_opaque_text(self.operation_digest, "operation_digest")
        if self.writer_fence != self.expected.writer_fence:
            raise AuthorityValidationError("advance identity does not hold expected writer fence")


@dataclass(frozen=True)
class AppliedTransition:
    """The durable remote proof for one complete conditional advance request."""

    request: AdvanceIdentity
    applied: HeadSnapshot

    def __post_init__(self) -> None:
        if type(self.request) is not AdvanceIdentity:
            raise AuthorityValidationError("invalid transition request")
        if type(self.applied) is not HeadSnapshot:
            raise AuthorityValidationError("invalid applied authority")
        if self.applied.installation_id != self.request.expected.installation_id:
            raise AuthorityValidationError("applied installation mismatch")
        if self.applied.site != self.request.expected.site:
            raise AuthorityValidationError("applied site mismatch")
        if self.applied.generation != self.request.expected.generation + 1:
            raise AuthorityValidationError("applied generation mismatch")
        if self.applied.revision_digest != self.request.revision_digest:
            raise AuthorityValidationError("applied revision mismatch")
        if self.applied.transition_id != self.request.transition_id:
            raise AuthorityValidationError("applied transition mismatch")
        if self.applied.writer_fence != self.request.writer_fence:
            # A receipt proves the exact fence held by the completed CAS.  A
            # later live-fence rotation needs its own authenticated transfer
            # protocol; it must never rewrite historical transition proof.
            raise AuthorityValidationError("applied writer fence mismatch")
        if self.applied.terminal:
            raise AuthorityValidationError("applied authority cannot be terminal")


@dataclass(frozen=True)
class LifecycleTransitionRequest:
    """The typed current-head write used only by the lifecycle coordinator."""

    kind: str
    expected: AuthoritySnapshot
    operation_ref: str
    transition_id: str
    revision_digest: str
    writer_fence: str
    operation_digest: str
    writer_proof: WriterFenceProof
    target_site: str | None = None
    target_writer_fence_ref: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"terminal-delete", "writer-transfer"}:
            raise AuthorityValidationError("invalid lifecycle transition kind")
        if type(self.expected) is not AuthoritySnapshot or self.expected.terminal:
            raise AuthorityValidationError("invalid lifecycle expected authority")
        for value, name in (
            (self.operation_ref, "lifecycle operation reference"),
            (self.transition_id, "lifecycle transition identifier"),
            (self.revision_digest, "lifecycle revision digest"),
            (self.writer_fence, "lifecycle writer fence"),
            (self.operation_digest, "lifecycle operation digest"),
        ):
            validate_opaque_text(value, name)
        if self.writer_fence != self.expected.writer_fence:
            raise AuthorityValidationError(
                "lifecycle request does not hold expected writer fence"
            )
        if type(self.writer_proof) is not WriterFenceProof:
            raise AuthorityValidationError("invalid lifecycle writer proof")
        if self.writer_proof.authority != self.expected:
            raise AuthorityValidationError("lifecycle writer proof mismatch")
        if self.kind == "terminal-delete":
            if self.target_site is not None or self.target_writer_fence_ref is not None:
                raise AuthorityValidationError(
                    "terminal lifecycle transition cannot carry target authority"
                )
        else:
            validate_opaque_text(self.target_site, "lifecycle target site")
            validate_opaque_text(
                self.target_writer_fence_ref,
                "lifecycle target writer fence reference",
            )

    def identity(self) -> "LifecycleTransitionIdentity":
        return LifecycleTransitionIdentity(
            kind=self.kind,
            expected=self.expected,
            operation_ref=self.operation_ref,
            transition_id=self.transition_id,
            revision_digest=self.revision_digest,
            writer_fence=self.writer_fence,
            operation_digest=self.operation_digest,
            target_site=self.target_site,
            target_writer_fence_ref=self.target_writer_fence_ref,
        )


@dataclass(frozen=True)
class LifecycleTransitionIdentity:
    """Exact, non-secret identity used for lifecycle lookup recovery."""

    kind: str
    expected: AuthoritySnapshot
    operation_ref: str
    transition_id: str
    revision_digest: str
    writer_fence: str
    operation_digest: str
    target_site: str | None = None
    target_writer_fence_ref: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"terminal-delete", "writer-transfer"}:
            raise AuthorityValidationError("invalid lifecycle transition kind")
        if type(self.expected) is not AuthoritySnapshot or self.expected.terminal:
            raise AuthorityValidationError("invalid lifecycle expected authority")
        for value, name in (
            (self.operation_ref, "lifecycle operation reference"),
            (self.transition_id, "lifecycle transition identifier"),
            (self.revision_digest, "lifecycle revision digest"),
            (self.writer_fence, "lifecycle writer fence"),
            (self.operation_digest, "lifecycle operation digest"),
        ):
            validate_opaque_text(value, name)
        if self.writer_fence != self.expected.writer_fence:
            raise AuthorityValidationError(
                "lifecycle identity does not hold expected writer fence"
            )
        if self.kind == "terminal-delete":
            if self.target_site is not None or self.target_writer_fence_ref is not None:
                raise AuthorityValidationError(
                    "terminal lifecycle identity cannot carry target authority"
                )
        else:
            validate_opaque_text(self.target_site, "lifecycle target site")
            validate_opaque_text(
                self.target_writer_fence_ref,
                "lifecycle target writer fence reference",
            )


@dataclass(frozen=True)
class AppliedLifecycleTransition:
    """Durable current-head proof for one lifecycle transition."""

    request: LifecycleTransitionIdentity
    applied: HeadSnapshot

    def __post_init__(self) -> None:
        if type(self.request) is not LifecycleTransitionIdentity:
            raise AuthorityValidationError("invalid lifecycle transition request")
        if type(self.applied) is not HeadSnapshot:
            raise AuthorityValidationError("invalid lifecycle applied authority")
        if self.applied.installation_id != self.request.expected.installation_id:
            raise AuthorityValidationError("lifecycle applied installation mismatch")
        if self.applied.generation != self.request.expected.generation + 1:
            raise AuthorityValidationError("lifecycle applied generation mismatch")
        if self.applied.revision_digest != self.request.revision_digest:
            raise AuthorityValidationError("lifecycle applied revision mismatch")
        if self.applied.transition_id != self.request.transition_id:
            raise AuthorityValidationError("lifecycle applied transition mismatch")
        if self.request.kind == "terminal-delete" and (
            self.applied.writer_fence != self.request.writer_fence
        ):
            raise AuthorityValidationError("lifecycle applied writer fence mismatch")
        if self.request.kind == "writer-transfer" and (
            self.applied.writer_fence == self.request.writer_fence
        ):
            raise AuthorityValidationError("writer transfer did not rotate fence")
        expected_site = self.request.target_site or self.request.expected.site
        if self.applied.site != expected_site:
            raise AuthorityValidationError("lifecycle applied site mismatch")
        if self.request.kind == "terminal-delete" and not self.applied.terminal:
            raise AuthorityValidationError("terminal lifecycle proof is not terminal")
        if self.request.kind == "writer-transfer" and self.applied.terminal:
            raise AuthorityValidationError("writer transfer cannot be terminal")


@dataclass(frozen=True)
class ExecutionLeaseIdentity:
    """The non-secret remote identity for one controlled effect lease."""

    expected: AuthoritySnapshot
    effect_id: str
    intent_digest: str
    writer_fence: str
    holder_id: str

    def __post_init__(self) -> None:
        if type(self.expected) is not AuthoritySnapshot or self.expected.terminal:
            raise AuthorityValidationError("invalid execution lease authority")
        validate_opaque_text(self.effect_id, "effect_id")
        validate_opaque_text(self.intent_digest, "intent_digest")
        validate_opaque_text(self.writer_fence, "writer_fence")
        validate_opaque_text(self.holder_id, "effect holder identifier")
        if self.writer_fence != self.expected.writer_fence:
            raise AuthorityValidationError("execution lease does not hold expected writer fence")


@dataclass(frozen=True)
class ExecutionLeaseRequest:
    """A writer-authorized request to acquire one public lease identity.

    Completion capabilities remain in the host-local execution vault.  They
    are never sent to a current-head adapter or retained in its receipts.
    """

    expected: AuthoritySnapshot
    effect_id: str
    intent_digest: str
    writer_fence: str
    holder_id: str
    writer_proof: WriterFenceProof
    _execution_overlap: _ExecutionOverlapPermit | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self.writer_proof) is not WriterFenceProof:
            raise AuthorityValidationError("invalid execution lease writer proof")
        ExecutionLeaseIdentity(
            expected=self.expected,
            effect_id=self.effect_id,
            intent_digest=self.intent_digest,
            writer_fence=self.writer_fence,
            holder_id=self.holder_id,
        )
        if self.writer_proof.authority != self.expected:
            raise AuthorityValidationError("execution lease writer proof mismatch")
        if self._execution_overlap is not None and type(self._execution_overlap) is not _ExecutionOverlapPermit:
            raise AuthorityValidationError("invalid execution overlap permit")

    def identity(self) -> ExecutionLeaseIdentity:
        return ExecutionLeaseIdentity(
            expected=self.expected,
            effect_id=self.effect_id,
            intent_digest=self.intent_digest,
            writer_fence=self.writer_fence,
            holder_id=self.holder_id,
        )


@dataclass(frozen=True)
class ExecutionLeaseRelease:
    """A writer-authorized release of an already host-validated lease."""

    lease: ExecutionLease
    writer_proof: WriterFenceProof
    operation_digest: str

    def __post_init__(self) -> None:
        if type(self.lease) is not ExecutionLease:
            raise AuthorityValidationError("invalid execution lease release")
        if type(self.writer_proof) is not WriterFenceProof:
            raise AuthorityValidationError("invalid execution lease writer proof")
        if self.writer_proof.authority != self.lease.authority:
            raise AuthorityValidationError("execution lease release writer proof mismatch")
        validate_opaque_text(self.operation_digest, "operation_digest")


@dataclass(frozen=True)
class ExecutionLeaseReceipt:
    """Durable lookup proof for an active or released effect lease."""

    request: ExecutionLeaseIdentity
    lease: ExecutionLease
    released: bool
    released_operation_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.request) is not ExecutionLeaseIdentity:
            raise AuthorityValidationError("invalid execution lease request")
        if type(self.lease) is not ExecutionLease:
            raise AuthorityValidationError("invalid execution lease")
        if type(self.released) is not bool:
            raise AuthorityValidationError("invalid execution lease state")
        if self.released:
            validate_opaque_text(self.released_operation_digest, "released operation digest")
        elif self.released_operation_digest is not None:
            raise AuthorityValidationError("active execution lease cannot have release ownership")
        if (
            self.lease.effect_id != self.request.effect_id
            or self.lease.intent_digest != self.request.intent_digest
            or self.lease.authority != self.request.expected
            or self.lease.holder_id != self.request.holder_id
        ):
            raise AuthorityValidationError("execution lease receipt mismatch")


class CurrentHeadPort(Protocol):
    """Typed read/CAS/recovery contract used by the health core."""

    def read(self) -> HeadRead: ...

    def conditional_advance(self, request: AdvanceRequest) -> HeadSnapshot: ...

    def lookup_transition(self, request: AdvanceIdentity) -> AppliedTransition: ...

    def conditional_lifecycle_transition(
        self,
        request: LifecycleTransitionRequest,
    ) -> HeadSnapshot: ...

    def lookup_lifecycle_transition(
        self,
        identity: LifecycleTransitionIdentity,
    ) -> AppliedLifecycleTransition: ...

    def validate_writer_fence(self, proof: WriterFenceProof) -> bool: ...

    def acquire_execution_lease(self, request: ExecutionLeaseRequest) -> ExecutionLeaseReceipt: ...

    def lookup_execution_lease(self, identity: ExecutionLeaseIdentity) -> ExecutionLeaseReceipt: ...

    def release_execution_lease(self, release: ExecutionLeaseRelease) -> ExecutionLeaseReceipt: ...


class InMemoryCurrentHead:
    """Synthetic current-head with injectable read, CAS and recovery failures."""

    def __init__(
        self,
        installation_id: str,
        site: str = "synthetic-site",
        *,
        writer_capability: str,
    ) -> None:
        if type(writer_capability) is not str:
            raise ValueError("synthetic current-head requires an explicit writer capability")
        self._writer_capability = writer_capability
        validate_opaque_text(self._writer_capability, "writer_fence_capability")
        self._head = HeadSnapshot(
            installation_id,
            1,
            "sha256:empty",
            "transition:empty",
            "fence:1",
            False,
            site,
        )
        self._transitions: dict[tuple[str, str, str], AppliedTransition] = {}
        self._lifecycle_transitions: dict[
            tuple[str, str, str], AppliedLifecycleTransition
        ] = {}
        self._execution_leases: dict[str, ExecutionLeaseReceipt] = {}
        self._active_execution_effect_ids: set[str] = set()
        self._active_execution_effect_id: str | None = None
        self._failure = FailureMode.NONE
        self._failure_operation = "all"
        self._lock = threading.RLock()

    def set_failure(self, failure: FailureMode, *, operation: str = "all") -> None:
        if operation not in {
            "all",
            "read",
            "advance",
            "lookup",
            "lifecycle",
            "lease",
            "lease-lookup",
            "lease-release",
        }:
            raise ValueError("invalid failure operation")
        with self._lock:
            self._failure = failure
            self._failure_operation = operation

    def clear_failure(self) -> None:
        with self._lock:
            self._failure = FailureMode.NONE
            self._failure_operation = "all"

    def read(self) -> HeadRead:
        with self._lock:
            self._raise_if_failed("read")
            return HeadRead(self._head)

    def validate_writer_fence(self, proof: WriterFenceProof) -> bool:
        if type(proof) is not WriterFenceProof:
            return False
        with self._lock:
            if self._head.terminal:
                raise HeadTerminal("terminal current head")
            return (
                proof.authority == self._head.as_authority()
                and secrets.compare_digest(proof.capability, self._writer_capability)
            )

    def conditional_advance(self, request: AdvanceRequest) -> HeadSnapshot:
        """Apply the sole typed core-to-current-head CAS request shape."""
        if type(request) is not AdvanceRequest:
            raise AuthorityValidationError("invalid advance request")
        with self._lock:
            if self._active_execution_effect_ids and not self._overlap_permits_advance(
                request._execution_overlap
            ):
                raise HeadConflict("active execution lease")
            lose_response = self._is_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, "advance")
            if not lose_response:
                self._raise_if_failed("advance")
            if self._head.terminal:
                raise HeadTerminal("terminal current head")
            if not self._valid_writer_proof(request.writer_proof, request.expected):
                raise HeadConflict("current writer fence capability conflict")
            if request.expected.installation_id != self._head.installation_id:
                raise HeadConflict("current-head installation conflict")
            if request.expected.terminal:
                raise HeadTerminal("terminal expected authority")
            if (
                request.expected.generation != self._head.generation
                or request.expected.revision_digest != self._head.revision_digest
                or request.expected.transition_id != self._head.transition_id
                or request.expected.writer_fence != self._head.writer_fence
                or request.expected.site != self._head.site
            ):
                raise HeadConflict("current-head compare-and-set conflict")

            self._before_advance_publish()
            next_generation = self._head.generation + 1
            next_head = HeadSnapshot(
                self._head.installation_id,
                next_generation,
                request.revision_digest,
                request.transition_id,
                self._head.writer_fence,
                False,
                self._head.site,
            )
            applied = AppliedTransition(
                request=request.identity(),
                applied=next_head,
            )
            self._head = next_head
            self._transitions[
                (next_head.installation_id, next_head.transition_id, request.operation_digest)
            ] = applied
            if lose_response:
                raise HeadUnknown("synthetic response lost after successful advance")
            return self._head

    def _before_advance_publish(self) -> None:
        """Synthetic scheduling hook for exercising the CAS publication boundary."""

        return None

    def lookup_transition(self, request: AdvanceIdentity) -> AppliedTransition:
        if type(request) is not AdvanceIdentity:
            raise AuthorityValidationError("invalid transition lookup request")
        with self._lock:
            self._raise_if_failed("lookup")
            found = self._transitions.get(
                (request.expected.installation_id, request.transition_id, request.operation_digest)
            )
            if found is None:
                raise TransitionNotFound("transition not found")
            return found

    def conditional_lifecycle_transition(
        self,
        request: LifecycleTransitionRequest,
    ) -> HeadSnapshot:
        """Apply one terminal delete or writer-transfer CAS."""

        if type(request) is not LifecycleTransitionRequest:
            raise AuthorityValidationError("invalid lifecycle transition request")
        with self._lock:
            lose_response = self._is_failure(
                FailureMode.UNKNOWN_AFTER_ADVANCE,
                "lifecycle",
            ) or self._is_failure(
                FailureMode.UNKNOWN_AFTER_ADVANCE,
                "advance",
            )
            if not lose_response:
                self._raise_if_failed("lifecycle")
            if request.kind == "terminal-delete" and self._active_execution_effect_ids:
                raise HeadConflict("active execution lease")
            if self._head.terminal:
                raise HeadTerminal("terminal current head")
            if not self._valid_writer_proof(request.writer_proof, request.expected):
                raise HeadConflict("current writer fence capability conflict")
            if request.expected != self._head.as_authority():
                raise HeadConflict("current-head lifecycle compare-and-set conflict")
            next_writer_fence = self._head.writer_fence
            if request.kind == "writer-transfer":
                next_writer_fence = "fence:" + secrets.token_urlsafe(32)
            next_head = HeadSnapshot(
                self._head.installation_id,
                self._head.generation + 1,
                request.revision_digest,
                request.transition_id,
                next_writer_fence,
                request.kind == "terminal-delete",
                request.target_site or self._head.site,
            )
            applied = AppliedLifecycleTransition(
                request=request.identity(),
                applied=next_head,
            )
            self._head = next_head
            self._lifecycle_transitions[
                (
                    request.expected.installation_id,
                    request.operation_ref,
                    request.operation_digest,
                )
            ] = applied
            if request.kind == "writer-transfer":
                # A generation transfer makes every pre-transfer execution
                # lease stale.  Keep the historical receipts for exact old
                # grant lookups, but remove their live hold before the new
                # writer can acquire work.
                self._active_execution_effect_ids.clear()
                self._sync_active_execution_effect_id()
            if lose_response:
                raise HeadUnknown("synthetic lifecycle response lost")
            return next_head

    def lookup_lifecycle_transition(
        self,
        identity: LifecycleTransitionIdentity,
    ) -> AppliedLifecycleTransition:
        if type(identity) is not LifecycleTransitionIdentity:
            raise AuthorityValidationError("invalid lifecycle transition lookup")
        with self._lock:
            self._raise_if_failed("lookup")
            found = self._lifecycle_transitions.get(
                (
                    identity.expected.installation_id,
                    identity.operation_ref,
                    identity.operation_digest,
                )
            )
            if found is None or found.request != identity:
                raise TransitionNotFound("lifecycle transition not found")
            return found

    def acquire_execution_lease(self, request: ExecutionLeaseRequest) -> ExecutionLeaseReceipt:
        """Atomically bind one effect to the exact live current-head fence."""

        if type(request) is not ExecutionLeaseRequest:
            raise AuthorityValidationError("invalid execution lease request")
        with self._lock:
            self._raise_if_failed("lease")
            if self._head.terminal:
                raise HeadTerminal("terminal current head")
            if not self._valid_writer_proof(request.writer_proof, request.expected):
                raise HeadConflict("current writer fence capability conflict")
            if request.expected != self._head.as_authority():
                raise HeadConflict("execution lease authority conflict")
            existing = self._execution_leases.get(request.effect_id)
            if existing is not None:
                if existing.request != request.identity():
                    raise HeadConflict("execution lease effect conflict")
                return existing
            if self._active_execution_effect_ids and (
                len(self._active_execution_effect_ids) >= 2
                or not self._overlap_permits_acquire(request._execution_overlap)
            ):
                raise HeadConflict("another execution lease is active")
            lease = ExecutionLease(
                lease_id="lease:" + secrets.token_urlsafe(32),
                effect_id=request.effect_id,
                intent_digest=request.intent_digest,
                authority=request.expected,
                holder_id=request.holder_id,
            )
            receipt = ExecutionLeaseReceipt(request=request.identity(), lease=lease, released=False)
            self._execution_leases[request.effect_id] = receipt
            self._active_execution_effect_ids.add(request.effect_id)
            self._sync_active_execution_effect_id()
            return receipt

    def lookup_execution_lease(self, identity: ExecutionLeaseIdentity) -> ExecutionLeaseReceipt:
        if type(identity) is not ExecutionLeaseIdentity:
            raise AuthorityValidationError("invalid execution lease lookup request")
        with self._lock:
            self._raise_if_failed("lease-lookup")
            receipt = self._execution_leases.get(identity.effect_id)
            if receipt is None:
                raise ExecutionLeaseNotFound("execution lease not found")
            if receipt.request != identity:
                raise HeadConflict("execution lease lookup conflict")
            return receipt

    def release_execution_lease(self, release: ExecutionLeaseRelease) -> ExecutionLeaseReceipt:
        if type(release) is not ExecutionLeaseRelease:
            raise AuthorityValidationError("invalid execution lease release")
        with self._lock:
            self._raise_if_failed("lease-release")
            lease = release.lease
            receipt = self._execution_leases.get(lease.effect_id)
            if receipt is None:
                raise ExecutionLeaseNotFound("execution lease not found")
            if (
                receipt.lease != lease
                or not self._valid_writer_proof(release.writer_proof, lease.authority)
            ):
                raise HeadConflict("execution lease release conflict")
            if not receipt.released:
                receipt = ExecutionLeaseReceipt(
                    request=receipt.request,
                    lease=receipt.lease,
                    released=True,
                    released_operation_digest=release.operation_digest,
                )
                self._execution_leases[lease.effect_id] = receipt
                self._active_execution_effect_ids.discard(lease.effect_id)
                self._sync_active_execution_effect_id()
            elif receipt.released_operation_digest != release.operation_digest:
                raise HeadConflict("execution lease release ownership conflict")
            return receipt

    def mark_terminal(self) -> HeadSnapshot:
        with self._lock:
            if self._active_execution_effect_ids:
                raise HeadConflict("active execution lease")
            self._raise_if_failed("advance")
            next_generation = self._head.generation + 1
            self._head = HeadSnapshot(
                self._head.installation_id,
                next_generation,
                self._head.revision_digest,
                f"transition:terminal:{next_generation}",
                self._head.writer_fence,
                True,
                self._head.site,
            )
            return self._head

    def _overlap_permits_advance(
        self,
        permit: _ExecutionOverlapPermit | None,
    ) -> bool:
        return (
            len(self._active_execution_effect_ids) == 1
            and type(permit) is _ExecutionOverlapPermit
            and permit.active_effect_id in self._active_execution_effect_ids
        )

    def _overlap_permits_acquire(
        self,
        permit: _ExecutionOverlapPermit | None,
    ) -> bool:
        return self._overlap_permits_advance(permit)

    def _sync_active_execution_effect_id(self) -> None:
        self._active_execution_effect_id = (
            next(iter(self._active_execution_effect_ids))
            if len(self._active_execution_effect_ids) == 1
            else None
        )

    def _is_failure(self, failure: FailureMode, operation: str) -> bool:
        return self._failure is failure and self._failure_operation in {"all", operation}

    def _valid_writer_proof(self, proof: WriterFenceProof, expected: AuthoritySnapshot) -> bool:
        return (
            type(proof) is WriterFenceProof
            and proof.authority == expected
            and expected == self._head.as_authority()
            and secrets.compare_digest(proof.capability, self._writer_capability)
        )

    def _raise_if_failed(self, operation: str) -> None:
        if self._failure_operation not in {"all", operation}:
            return
        if self._failure is FailureMode.CONFLICT:
            raise HeadConflict("synthetic conflict")
        if self._failure is FailureMode.TIMEOUT:
            raise HeadTimeout("synthetic timeout")
        if self._failure is FailureMode.UNKNOWN:
            raise HeadUnknown("synthetic unknown result")

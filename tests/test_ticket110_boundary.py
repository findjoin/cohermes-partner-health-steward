import json
import sqlite3
import struct
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from partner_health_steward.authority import (
    AuthoritySnapshot,
    AuthorityValidationError,
    CommittedTransition,
    EffectIntent,
    ExecutionLease,
    PreparedTransition,
    RevisionTarget,
    TerminalEffect,
    WriterHolderClaim,
    WriterFenceProof,
)
from partner_health_steward.contract import (
    CommandEnvelope,
    EffectIntentMeta,
    MAX_ID_BYTES,
    ProtocolViolation,
    Response,
    StateCandidatePayload,
    decode_response_frame,
    encode_frame,
)
from partner_health_steward.core import (
    HealthCore,
    InMemoryExecutionCapabilityVault,
    InMemoryWriterFenceVault,
)
from partner_health_steward.current_head import (
    AdvanceRequest,
    AdvanceIdentity,
    AppliedTransition,
    CurrentHeadError,
    ExecutionLeaseIdentity,
    ExecutionLeaseReceipt,
    ExecutionLeaseRequest,
    FailureMode,
    HeadConflict,
    HeadTerminal,
    HeadUnknown,
    HeadRead,
    HeadSnapshot,
    TransitionNotFound,
    InMemoryCurrentHead,
)
from partner_health_steward.plugin import HealthPlugin
from partner_health_steward.probe import ProbeState
from partner_health_steward.storage import (
    CurrentHeadRecoveryBinding,
    EncryptedStateStore,
    KeyUnavailable,
    StaticKeyProvider,
    StoreUnavailable,
)


_TEST_WRITER_CAPABILITY = "ticket110-synthetic-writer-capability"
_TEST_OPERATION_DIGEST = "sha256:" + ("0" * 64)


def synthetic_head(installation_id, site="synthetic-site"):
    """Create a head whose writer secret is supplied by this test host only."""

    return InMemoryCurrentHead(
        installation_id=installation_id,
        site=site,
        writer_capability=_TEST_WRITER_CAPABILITY,
    )


class SnapshotCurrentHead:
    """Read-only current-head fixture for authority mismatch checks."""

    def __init__(self, snapshot):
        self._snapshot = snapshot

    def read(self):
        return HeadRead(self._snapshot)

    def validate_writer_fence(self, proof):
        return (
            isinstance(proof, WriterFenceProof)
            and proof.authority == self._snapshot.as_authority()
            and proof.capability == _TEST_WRITER_CAPABILITY
        )


class AlwaysEqualStr(str):
    """A hostile str subclass used to test semantic type canonicalization."""

    def __eq__(self, other):
        del other
        return True

    def __ne__(self, other):
        del other
        return False


class DeceptiveText(str):
    """Carries one raw value while claiming equality with another."""

    def __new__(cls, raw, accepted):
        value = str.__new__(cls, raw)
        value._accepted = accepted
        return value

    def __eq__(self, other):
        return other == self._accepted

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._accepted)


class DeceptiveInt(int):
    """Carries one raw integer while claiming equality with another."""

    def __new__(cls, raw, accepted):
        value = int.__new__(cls, raw)
        value._accepted = accepted
        return value

    def __eq__(self, other):
        return other == self._accepted

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._accepted)


class SpoofedAuthorityCurrentHead:
    """Returns a structurally typed head whose primitives lie via equality."""

    def __init__(self, delegate, snapshot):
        self._delegate = delegate
        self._snapshot = snapshot

    def read(self):
        return HeadRead(self._snapshot)

    def validate_writer_fence(self, proof):
        return self._delegate.validate_writer_fence(proof)


class ForgedEffectIntent(EffectIntent):
    """A subtype whose equality cannot be trusted at a Plugin/core seam."""

    def __eq__(self, other):
        del other
        return True


class PretendPluginPeer:
    """A non-string that lies about the Plugin peer comparison."""

    def __eq__(self, other):
        del other
        return True

    def __ne__(self, other):
        del other
        return False


class _DelegatingCurrentHead:
    def validate_writer_fence(self, proof):
        return self._delegate.validate_writer_fence(proof)


class WrongFenceLookupCurrentHead(_DelegatingCurrentHead):
    """Returns a forged remote receipt to verify recovery rechecks its fence."""

    def __init__(self, delegate):
        self._delegate = delegate

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        receipt = self._delegate.lookup_transition(request)
        return AppliedTransition(
            request=AdvanceIdentity(
                expected=replace(receipt.request.expected, writer_fence="fence:forged"),
                transition_id=receipt.request.transition_id,
                revision_digest=receipt.request.revision_digest,
                writer_fence="fence:forged",
                operation_digest=receipt.request.operation_digest,
            ),
            applied=receipt.applied,
        )


class RotatedFenceRecoveryCurrentHead(_DelegatingCurrentHead):
    """Models a current writer that rotated its fence after an old CAS."""

    def __init__(self, delegate, writer_fence):
        self._delegate = delegate
        self._writer_fence = writer_fence

    def _rotated(self):
        return replace(self._delegate.read().head, writer_fence=self._writer_fence)

    def read(self):
        return HeadRead(self._rotated())

    def validate_writer_fence(self, proof):
        return (
            isinstance(proof, WriterFenceProof)
            and proof.authority == self._rotated().as_authority()
            and proof.capability == _TEST_WRITER_CAPABILITY
        )

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        # A transition receipt is historical proof.  Rotating the live fence
        # must not rewrite the fence that was held when the CAS occurred.
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        return self._delegate.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        return self._delegate.release_execution_lease(release)


class RotatedFenceAfterReleaseCurrentHead(_DelegatingCurrentHead):
    """Rotates the live writer fence immediately after a lease release."""

    def __init__(self, delegate, writer_fence):
        self._delegate = delegate
        self._writer_fence = writer_fence
        self._after_release = False

    def _live(self):
        return replace(self._delegate.read().head, writer_fence=self._writer_fence)

    def read(self):
        return HeadRead(self._live()) if self._after_release else self._delegate.read()

    def validate_writer_fence(self, proof):
        current = self._live().as_authority() if self._after_release else self._delegate.read().head.as_authority()
        return (
            isinstance(proof, WriterFenceProof)
            and proof.authority == current
            and proof.capability == _TEST_WRITER_CAPABILITY
        )

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        return self._delegate.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        receipt = self._delegate.release_execution_lease(release)
        self._after_release = True
        return receipt


class SyntheticCrash(RuntimeError):
    pass


class SyntheticStop(BaseException):
    pass


class FlakyKeyIdentityProvider:
    """A key provider whose identity channel can fail after store setup."""

    def __init__(self):
        self.fail_identity = False

    @property
    def key_id(self):
        if self.fail_identity:
            raise RuntimeError("synthetic key identity unavailable")
        return "synthetic-flaky-key"

    def get_key(self):
        return b"f" * 32


class GenericFailureCurrentHead(_DelegatingCurrentHead):
    """Raises an unclassified CurrentHeadError at one selected port boundary."""

    def __init__(self, delegate):
        self._delegate = delegate
        self.fail_read = False
        self.fail_lookup = False

    def read(self):
        if self.fail_read:
            raise CurrentHeadError("synthetic generic read failure")
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        if self.fail_lookup:
            raise CurrentHeadError("synthetic generic lookup failure")
        return self._delegate.lookup_transition(request)


class MutatingAdvanceRequestCurrentHead(_DelegatingCurrentHead):
    """Mutates only the adapter-owned CAS argument after core dispatch."""

    def __init__(self, delegate, mode):
        self._delegate = delegate
        self._mode = mode

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        if self._mode == "operation-digest":
            object.__setattr__(request, "operation_digest", "sha256:adapter-operation-digest")
            return self._delegate.conditional_advance(request)
        if self._mode == "nested-authority":
            # Delegate a deep copy so the remote receipt remains honest; only
            # the object originally handed to the adapter is corrupted.
            expected = request.expected
            copied_authority = AuthoritySnapshot(
                installation_id=expected.installation_id,
                generation=expected.generation,
                revision_digest=expected.revision_digest,
                transition_id=expected.transition_id,
                writer_fence=expected.writer_fence,
                terminal=expected.terminal,
                site=expected.site,
            )
            copied_request = AdvanceRequest(
                expected=copied_authority,
                transition_id=request.transition_id,
                revision_digest=request.revision_digest,
                writer_fence=request.writer_fence,
                operation_digest=request.operation_digest,
                writer_proof=WriterFenceProof(
                    authority=copied_authority,
                    capability=request.writer_proof.capability,
                ),
            )
            advanced = self._delegate.conditional_advance(copied_request)
            object.__setattr__(request.expected, "revision_digest", "sha256:adapter-mutated-authority")
            return advanced
        raise AssertionError("unknown synthetic advance mutation")

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        return self._delegate.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        return self._delegate.release_execution_lease(release)


class MutatingPortInputCurrentHead(_DelegatingCurrentHead):
    """Mutates each untrusted port input before or after delegation."""

    def __init__(self, delegate, mode):
        self._delegate = delegate
        self._mode = mode
        self.enabled = True

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def validate_writer_fence(self, proof):
        if self.enabled and self._mode == "writer-proof-before":
            object.__setattr__(proof, "capability", "capability:adapter")
        valid = self._delegate.validate_writer_fence(proof)
        if self.enabled and self._mode == "writer-proof-after":
            object.__setattr__(proof, "capability", "capability:adapter")
        return valid

    def acquire_execution_lease(self, request):
        if self.enabled and self._mode == "lease-request-before":
            object.__setattr__(request.writer_proof, "capability", "capability:adapter")
        receipt = self._delegate.acquire_execution_lease(request)
        if self.enabled and self._mode == "lease-request-after":
            object.__setattr__(request.writer_proof, "capability", "capability:adapter")
        return receipt

    def lookup_execution_lease(self, identity):
        if self.enabled and self._mode == "lease-identity-before":
            object.__setattr__(identity, "holder_id", "holder:adapter")
        receipt = self._delegate.lookup_execution_lease(identity)
        if self.enabled and self._mode == "lease-identity-after":
            object.__setattr__(identity, "holder_id", "holder:adapter")
        return receipt

    def release_execution_lease(self, release):
        if self.enabled and self._mode == "lease-release-before":
            object.__setattr__(release, "operation_digest", "sha256:adapter-release")
        receipt = self._delegate.release_execution_lease(release)
        if self.enabled and self._mode == "lease-release-after":
            object.__setattr__(release, "operation_digest", "sha256:adapter-release")
        return receipt


class FaultingWriterHolderSession:
    """Host-session wrapper that can fail or silently ignore orderly release."""

    def __init__(self, vault, delegate):
        self._vault = vault
        self._delegate = delegate

    def active(self):
        return self._delegate.active()

    def proof_for(self, authority):
        return self._delegate.proof_for(authority)

    def release(self):
        if self._vault.mode == "raise":
            raise RuntimeError("synthetic writer-holder release failure")
        if self._vault.mode == "noop":
            return None
        return self._delegate.release()


class FaultingWriterFenceVault:
    """Delegates authority while exposing a recoverable close fault to tests."""

    def __init__(self, delegate, mode):
        self._delegate = delegate
        self.mode = mode
        self._wrappers = {}

    def acquire_or_resume(self, installation_id, site, holder):
        session = self._delegate.acquire_or_resume(installation_id, site, holder)
        if session is None:
            return None
        key = id(session)
        wrapper = self._wrappers.get(key)
        if wrapper is None:
            wrapper = FaultingWriterHolderSession(self, session)
            self._wrappers[key] = wrapper
        return wrapper


class CurrentHeadErrorAfterRemoteMutationValidationCurrentHead(_DelegatingCurrentHead):
    """Makes the post-mutation writer validation fail without losing the CAS."""

    def __init__(self, delegate, *, reject_writer=False):
        self._delegate = delegate
        self._fail_next_validation = False
        self._reject_writer = reject_writer

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        advanced = self._delegate.conditional_advance(request)
        self._fail_next_validation = True
        return advanced

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        return self._delegate.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        receipt = self._delegate.release_execution_lease(release)
        self._fail_next_validation = True
        return receipt

    def validate_writer_fence(self, proof):
        if self._fail_next_validation:
            self._fail_next_validation = False
            if self._reject_writer:
                return False
            raise CurrentHeadError("synthetic unclassified post-mutation validation failure")
        return self._delegate.validate_writer_fence(proof)


class CurrentHeadErrorAfterReleaseReadCurrentHead(_DelegatingCurrentHead):
    """Makes only the post-release live-authority read unclassified."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._fail_next_read = False

    def read(self):
        if self._fail_next_read:
            self._fail_next_read = False
            raise CurrentHeadError("synthetic unclassified post-release read failure")
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        return self._delegate.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        receipt = self._delegate.release_execution_lease(release)
        self._fail_next_read = True
        return receipt


class RejectingWriterValidationCurrentHead(_DelegatingCurrentHead):
    """Returns a definite current-writer rejection when toggled."""

    def __init__(self, delegate):
        self._delegate = delegate
        self.reject_writer = False

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def validate_writer_fence(self, proof):
        if self.reject_writer:
            return False
        return self._delegate.validate_writer_fence(proof)


class FlipWriterFenceVault:
    """Provides one live proof, then models a holder that disappeared."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._calls = 0

    def acquire_or_resume(self, installation_id, site, holder):
        session = self._delegate.acquire_or_resume(installation_id, site, holder)
        if session is None:
            return None
        return _FlipWriterFenceSession(self, session)


class _FlipWriterFenceSession:
    def __init__(self, owner, delegate):
        self._owner = owner
        self._delegate = delegate

    def active(self):
        return self._delegate.active()

    def proof_for(self, authority):
        self._owner._calls += 1
        if self._owner._calls == 1:
            return self._delegate.proof_for(authority)
        return None

    def release(self):
        self._delegate.release()


class InvalidAuthorityCurrentHead:
    """Simulates a remote current-head response that fails authority decoding."""

    def read(self):
        raise AuthorityValidationError("synthetic invalid remote authority")


class ForgedAdvanceCurrentHead(_DelegatingCurrentHead):
    """Returns a structurally valid but semantically forged CAS response."""

    def __init__(self, delegate):
        self._delegate = delegate

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        applied = self._delegate.conditional_advance(request)
        return replace(applied, revision_digest="sha256:forged-current-head")

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)


class WrongFenceAdvanceCurrentHead(_DelegatingCurrentHead):
    """Returns a CAS response whose fence differs from the authoritative head."""

    def __init__(self, delegate):
        self._delegate = delegate

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        applied = self._delegate.conditional_advance(request)
        return replace(applied, writer_fence="fence:forged")

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)


class OversizedFenceAdvanceCurrentHead(_DelegatingCurrentHead):
    """Models a remote CAS result that cannot be represented on the wire."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._fence = "x" * (MAX_ID_BYTES + 1)

    def read(self):
        snapshot = self._delegate.read().head
        if snapshot.generation >= 2:
            snapshot = replace(snapshot, writer_fence=self._fence)
        return HeadRead(snapshot)

    def conditional_advance(self, request):
        applied = self._delegate.conditional_advance(request)
        return replace(applied, writer_fence=self._fence)

    def lookup_transition(self, request):
        receipt = self._delegate.lookup_transition(request)
        return AppliedTransition(request=receipt.request, applied=replace(receipt.applied, writer_fence=self._fence))


class LostExecutionLeaseResponseCurrentHead(_DelegatingCurrentHead):
    """Loses one acquire and one release response after the remote mutation."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._lose_acquire_once = True
        self._lose_release_once = True

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        receipt = self._delegate.acquire_execution_lease(request)
        if self._lose_acquire_once:
            self._lose_acquire_once = False
            raise HeadUnknown("synthetic execution lease acquire response lost")
        return receipt

    def lookup_execution_lease(self, request):
        return self._delegate.lookup_execution_lease(request)

    def release_execution_lease(self, lease):
        receipt = self._delegate.release_execution_lease(lease)
        if self._lose_release_once:
            self._lose_release_once = False
            raise HeadUnknown("synthetic execution lease release response lost")
        return receipt


class LostReleaseResponseCurrentHead(_DelegatingCurrentHead):
    """Loses one release response after the remote lease has changed state."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._lose_release_once = True

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, request):
        return self._delegate.lookup_execution_lease(request)

    def release_execution_lease(self, release):
        receipt = self._delegate.release_execution_lease(release)
        if self._lose_release_once:
            self._lose_release_once = False
            raise HeadUnknown("synthetic execution lease release response lost")
        return receipt


class LostReleaseThenFaultyLeaseLookupCurrentHead(LostReleaseResponseCurrentHead):
    """Creates an exact release-recovery binding, then faults its lookup."""

    def __init__(self, delegate, mode):
        super().__init__(delegate)
        self._mode = mode
        self.fault_lookup = False

    def lookup_execution_lease(self, identity):
        if self.fault_lookup:
            if self._mode == "malformed":
                return object()
            if self._mode == "unclassified":
                raise CurrentHeadError("synthetic unclassified lease lookup failure")
            raise AssertionError("unknown synthetic lease lookup fault")
        return self._delegate.lookup_execution_lease(identity)


class ForeignInstallationLeaseRecoveryCurrentHead:
    """Mixes a foreign live head with an old released-lease lookup fixture."""

    def __init__(self, foreign_head, old_lease_head):
        self._foreign_head = foreign_head
        self._old_lease_head = old_lease_head

    def read(self):
        return self._foreign_head.read()

    def validate_writer_fence(self, proof):
        return self._foreign_head.validate_writer_fence(proof)

    def lookup_execution_lease(self, identity):
        return self._old_lease_head.lookup_execution_lease(identity)


class SwitchableInstallationRecoveryCurrentHead:
    """Switches live authority while retaining primary historical receipts."""

    def __init__(self, primary_head, foreign_head):
        self._primary_head = primary_head
        self._foreign_head = foreign_head
        self.use_foreign = False

    @property
    def _live_head(self):
        return self._foreign_head if self.use_foreign else self._primary_head

    def read(self):
        return self._live_head.read()

    def validate_writer_fence(self, proof):
        return self._live_head.validate_writer_fence(proof)

    def conditional_advance(self, request):
        return self._primary_head.conditional_advance(request)

    def lookup_transition(self, request):
        return self._primary_head.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._primary_head.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        return self._primary_head.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        return self._primary_head.release_execution_lease(release)


class ForeignHeadAfterReleaseCurrentHead(_DelegatingCurrentHead):
    """Moves only the post-release live check to a foreign authority."""

    def __init__(self, primary_head, foreign_head):
        self._primary_head = primary_head
        self._foreign_head = foreign_head
        self._foreign_after_release = False

    def read(self):
        head = self._foreign_head if self._foreign_after_release else self._primary_head
        return head.read()

    def validate_writer_fence(self, proof):
        head = self._foreign_head if self._foreign_after_release else self._primary_head
        return head.validate_writer_fence(proof)

    def conditional_advance(self, request):
        return self._primary_head.conditional_advance(request)

    def lookup_transition(self, request):
        return self._primary_head.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._primary_head.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        return self._primary_head.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        receipt = self._primary_head.release_execution_lease(release)
        self._foreign_after_release = True
        return receipt


class ForgedAcquireCurrentHead(_DelegatingCurrentHead):
    """Returns a valid-looking acquire receipt without mutating current-head."""

    def __init__(self, delegate):
        self._delegate = delegate

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        lease = ExecutionLease(
            lease_id="lease:forged-acquire",
            effect_id=request.effect_id,
            intent_digest=request.intent_digest,
            authority=request.expected,
            holder_id=request.holder_id,
        )
        return ExecutionLeaseReceipt(request=request.identity(), lease=lease, released=False)

    def lookup_execution_lease(self, request):
        return self._delegate.lookup_execution_lease(request)

    def release_execution_lease(self, release):
        return self._delegate.release_execution_lease(release)


class ForgedReleaseCurrentHead(_DelegatingCurrentHead):
    """Claims a release succeeded without changing the actual remote lease."""

    def __init__(self, delegate):
        self._delegate = delegate

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, request):
        return self._delegate.lookup_execution_lease(request)

    def release_execution_lease(self, release):
        active = self._delegate.lookup_execution_lease(
            ExecutionLeaseIdentity(
                expected=release.lease.authority,
                effect_id=release.lease.effect_id,
                intent_digest=release.lease.intent_digest,
                writer_fence=release.lease.authority.writer_fence,
                holder_id=release.lease.holder_id,
            )
        )
        return ExecutionLeaseReceipt(
            request=active.request,
            lease=active.lease,
            released=True,
            released_operation_digest="sha256:forged-release",
        )


class AdvanceAfterLookupCurrentHead(_DelegatingCurrentHead):
    """Lets another writer advance immediately after transition lookup."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._advanced = False

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        receipt = self._delegate.lookup_transition(request)
        if not self._advanced:
            self._advanced = True
            current = self._delegate.read().head
            self._delegate.conditional_advance(
                AdvanceRequest(
                    expected=current.as_authority(),
                    transition_id="transition:interloper-after-lookup",
                    revision_digest="sha256:interloper-after-lookup",
                    writer_fence=current.writer_fence,
                    operation_digest=_TEST_OPERATION_DIGEST,
                    writer_proof=WriterFenceProof(
                        authority=current.as_authority(),
                        capability=_TEST_WRITER_CAPABILITY,
                    ),
                )
            )
        return receipt


class TerminalThenRecreatedCurrentHead:
    """Reports one terminal head, then simulates an unsafe old-name rebuild."""

    def __init__(self, original):
        self._original = original
        self._terminal_once = True

    def read(self):
        if self._terminal_once:
            self._terminal_once = False
            return HeadRead(
                replace(
                    self._original,
                    generation=self._original.generation + 1,
                    transition_id="transition:terminal-observed",
                    writer_fence="fence:terminal-observed",
                    terminal=True,
                )
            )
        return HeadRead(self._original)


class BlockingConditionalCurrentHead(InMemoryCurrentHead):
    """Pauses one CAS after its checks and before publishing its new head."""

    def __init__(self, installation_id):
        super().__init__(installation_id, writer_capability=_TEST_WRITER_CAPABILITY)
        self.first_advance_checked = threading.Event()
        self.release_first_advance = threading.Event()
        self._pause_once = True

    def _before_advance_publish(self):
        if self._pause_once:
            self._pause_once = False
            self.first_advance_checked.set()
            if not self.release_first_advance.wait(timeout=2):
                raise SyntheticCrash("synthetic conditional advance release timeout")


class BlockingReleaseCurrentHead(_DelegatingCurrentHead):
    """Pauses an effect-lease release after the core has entered its write lane."""

    def __init__(self, delegate):
        self._delegate = delegate
        self.release_started = threading.Event()
        self.allow_release = threading.Event()

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        return self._delegate.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        self.release_started.set()
        if not self.allow_release.wait(timeout=2):
            raise SyntheticCrash("synthetic release gate timeout")
        return self._delegate.release_execution_lease(release)


class CrashBeforeReceiptStore(EncryptedStateStore):
    """Injects a process-stop point after domain work and before the receipt."""

    def __init__(self, database, key_provider):
        super().__init__(database, key_provider)
        self.fail_before_receipt = True

    def save_receipt(self, *args, **kwargs):
        if self.fail_before_receipt:
            self.fail_before_receipt = False
            raise SyntheticCrash("synthetic crash before receipt")
        return super().save_receipt(*args, **kwargs)


class JournalCheckingCurrentHead(_DelegatingCurrentHead):
    """Observes whether commit persists its causal recovery proof before CAS."""

    def __init__(self, delegate, store, record_id):
        self._delegate = delegate
        self._store = store
        self._record_id = record_id
        self.pending_at_advance = None

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        self.pending_at_advance = self._store.pending_for_record(self._record_id)
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)


class TerminalLookupCurrentHead(_DelegatingCurrentHead):
    """Makes transition recovery observe a terminal current-head result."""

    def __init__(self, delegate):
        self._delegate = delegate

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        raise HeadTerminal("synthetic terminal during lookup")


class TerminalReadCurrentHead:
    """Makes the initial current-head read report a terminal authority."""

    def read(self):
        raise HeadTerminal("synthetic terminal during read")


class TerminalOnceCurrentHead(_DelegatingCurrentHead):
    """Reports terminal for exactly one recovery preflight read."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._terminal_once = True

    def read(self):
        if self._terminal_once:
            self._terminal_once = False
            raise HeadTerminal("synthetic terminal during recovery preflight")
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        return self._delegate.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        return self._delegate.release_execution_lease(release)


class TerminalAtAdvanceCurrentHead(_DelegatingCurrentHead):
    """Reports terminal exactly from the mutable CAS boundary."""

    def __init__(self, delegate):
        self._delegate = delegate

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        del request
        raise HeadTerminal("synthetic terminal during conditional advance")

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)


class AdvanceThenTerminalCurrentHead(_DelegatingCurrentHead):
    """Publishes a CAS, then loses its response to a terminal observation."""

    def __init__(self, delegate):
        self._delegate = delegate

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        self._delegate.conditional_advance(request)
        raise HeadTerminal("synthetic terminal after successful conditional advance")

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)


class TerminalHandoffFailureStore(EncryptedStateStore):
    """Fails only the bound-to-generic handoff after a terminal mutation read."""

    def __init__(self, database, key_provider):
        super().__init__(database, key_provider)
        self.fail_terminal_handoff_once = True

    def replace_current_head_observation(self, expected_binding, next_binding):
        if self.fail_terminal_handoff_once and expected_binding is not None and next_binding is None:
            self.fail_terminal_handoff_once = False
            raise StoreUnavailable("synthetic terminal handoff persistence failure")
        return super().replace_current_head_observation(expected_binding, next_binding)


class TerminalAfterAdvanceReadCurrentHead(_DelegatingCurrentHead):
    """Returns a successful CAS, then reports terminal on its confirmation read."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._terminal_after_advance = False

    def read(self):
        if self._terminal_after_advance:
            self._terminal_after_advance = False
            raise HeadTerminal("synthetic terminal after successful CAS")
        return self._delegate.read()

    def conditional_advance(self, request):
        advanced = self._delegate.conditional_advance(request)
        self._terminal_after_advance = True
        return advanced

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)


class TerminalAfterReleaseLookupCurrentHead(_DelegatingCurrentHead):
    """Returns a released lease, then reports terminal on confirmation lookup."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._terminal_after_release = False

    def read(self):
        return self._delegate.read()

    def conditional_advance(self, request):
        return self._delegate.conditional_advance(request)

    def lookup_transition(self, request):
        return self._delegate.lookup_transition(request)

    def acquire_execution_lease(self, request):
        return self._delegate.acquire_execution_lease(request)

    def lookup_execution_lease(self, identity):
        if self._terminal_after_release:
            self._terminal_after_release = False
            raise HeadTerminal("synthetic terminal after successful lease release")
        return self._delegate.lookup_execution_lease(identity)

    def release_execution_lease(self, release):
        receipt = self._delegate.release_execution_lease(release)
        self._terminal_after_release = True
        return receipt


class CrashBeforeTerminalLatchCore(HealthCore):
    """Models process loss immediately after a terminal observation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._crash_before_terminal_latch_once = True

    def _latch_terminal(self):
        if self._crash_before_terminal_latch_once:
            self._crash_before_terminal_latch_once = False
            raise SyntheticCrash("synthetic crash before terminal latch")
        return super()._latch_terminal()


class DropWriterBeforeStatePersistenceCore(HealthCore):
    """Models a writer fence holder disappearing after a confirmed CAS."""

    def _persist_state_commit_success(self, *args, **kwargs):
        self._writer_fence_vault = None
        return super()._persist_state_commit_success(*args, **kwargs)


class DropWriterBeforeEffectPersistenceCore(HealthCore):
    """Models a writer fence holder disappearing after a confirmed release."""

    def _persist_effect_result_success(self, *args, **kwargs):
        self._writer_fence_vault = None
        return super()._persist_effect_result_success(*args, **kwargs)


class CrashAfterGuardArmCore(HealthCore):
    """Turns an unexpected guard entry into a synthetic hard process stop."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guard_entered = False

    def _enter_current_head_guard(self, *args, **kwargs):
        self.guard_entered = True
        super()._enter_current_head_guard(*args, **kwargs)
        raise SyntheticCrash("synthetic crash immediately after generic guard arm")


class BlockingReceiptStore(EncryptedStateStore):
    """Stops exactly one receipt save after local business rows are written."""

    def __init__(self, database, key_provider):
        super().__init__(database, key_provider)
        self.block_before_receipt = False
        self.receipt_started = threading.Event()
        self.release_receipt = threading.Event()

    def save_receipt(self, *args, **kwargs):
        if self.block_before_receipt:
            self.block_before_receipt = False
            self.receipt_started.set()
            if not self.release_receipt.wait(timeout=2):
                raise SyntheticCrash("synthetic receipt release timeout")
        return super().save_receipt(*args, **kwargs)


class BlockingJournalStore(EncryptedStateStore):
    """Pauses a commit after its stale preflight but before journal insertion."""

    def __init__(self, database, key_provider):
        super().__init__(database, key_provider)
        self.journal_started = threading.Event()
        self.release_journal = threading.Event()

    def _pause_before_journal(self):
        self.journal_started.set()
        if not self.release_journal.wait(timeout=2):
            raise SyntheticCrash("synthetic journal release timeout")

    def write_pending_command(self, *args, **kwargs):
        self._pause_before_journal()
        return super().write_pending_command(*args, **kwargs)

    def reserve_pending_commit(self, *args, **kwargs):
        self._pause_before_journal()
        return super().reserve_pending_commit(*args, **kwargs)


class CommitFailureStore(EncryptedStateStore):
    """Rejects the outer SQLite COMMIT after a remote CAS has returned."""

    def __init__(self, database, key_provider):
        super().__init__(database, key_provider)
        self.fail_commit_after_receipt = False

    def save_receipt(self, *args, **kwargs):
        result = super().save_receipt(*args, **kwargs)
        if self.fail_commit_after_receipt:
            self.fail_commit_after_receipt = False
            self._connection.set_authorizer(self._deny_commit)
        return result

    @staticmethod
    def _deny_commit(action, argument_one, argument_two, database, trigger):
        del argument_two, database, trigger
        if action == sqlite3.SQLITE_TRANSACTION and argument_one == "COMMIT":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def clear_commit_failure(self):
        self._connection.set_authorizer(None)


class RollbackFailureStore(EncryptedStateStore):
    """Rejects both final COMMIT and rollback to exercise a poisoned SQLite connection."""

    def __init__(self, database, key_provider):
        super().__init__(database, key_provider)
        self.fail_commit_and_rollback_after_receipt = False

    def save_receipt(self, *args, **kwargs):
        result = super().save_receipt(*args, **kwargs)
        if self.fail_commit_and_rollback_after_receipt:
            self.fail_commit_and_rollback_after_receipt = False
            self._connection.set_authorizer(self._deny_commit_and_rollback)
        return result

    @staticmethod
    def _deny_commit_and_rollback(action, argument_one, argument_two, database, trigger):
        del argument_two, database, trigger
        if action == sqlite3.SQLITE_TRANSACTION and argument_one in {"COMMIT", "ROLLBACK"}:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def clear_transaction_failure(self):
        self._connection.set_authorizer(None)


class Ticket110BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.key_provider = StaticKeyProvider(b"k" * 32, key_id="synthetic-key")
        self.store = EncryptedStateStore("file:ticket110?mode=memory&cache=shared", self.key_provider)
        self.head = synthetic_head(installation_id="synthetic-installation")
        self.store.seed_finalized_authority(self.authority_for(self.head))
        self.execution_vault = InMemoryExecutionCapabilityVault()
        self.writer_vault = self.writer_vault_for(self.head)
        self.core = self.core_for(
            self.store,
            self.head,
            execution_capability_vault=self.execution_vault,
        )
        self.plugin = HealthPlugin(self.core)

    def tearDown(self):
        self.store.close()

    def command(self, action, causal_id, payload, *, generation=1, scope=None):
        special_scopes = {
            "probe": "probe",
            "effect.request": "effect:request",
            "effect.result": "effect:result",
        }
        default_scope = special_scopes.get(action)
        if default_scope is None:
            default_scope = "state:" + action.split(".", 1)[1]
        return CommandEnvelope(
            peer="plugin",
            action=action,
            source="synthetic",
            causal_id=causal_id,
            generation=generation,
            scope=tuple((default_scope,) if scope is None else scope),
            payload=payload,
        )

    @staticmethod
    def writer_vault_for(head):
        current = head
        while not isinstance(current, InMemoryCurrentHead) and hasattr(current, "_delegate"):
            current = current._delegate
        if not isinstance(current, InMemoryCurrentHead):
            raise AttributeError("synthetic writer host is unavailable")
        snapshot = current.read().head.as_authority()
        vault = InMemoryWriterFenceVault()
        vault.bind(snapshot, _TEST_WRITER_CAPABILITY)
        return vault

    @staticmethod
    def writer_proof_for(head, authority=None):
        current = head
        while not isinstance(current, InMemoryCurrentHead) and hasattr(current, "_delegate"):
            current = current._delegate
        if not isinstance(current, InMemoryCurrentHead):
            raise AttributeError("synthetic writer host is unavailable")
        expected = authority if authority is not None else current.read().head.as_authority()
        return WriterFenceProof(
            authority=expected,
            capability=_TEST_WRITER_CAPABILITY,
        )

    def core_for(self, store, head, **kwargs):
        if "writer_fence_vault" not in kwargs:
            try:
                kwargs["writer_fence_vault"] = self.writer_vault_for(head)
            except AttributeError:
                kwargs["writer_fence_vault"] = self.writer_vault
        return HealthCore(store, head, **kwargs)

    @staticmethod
    def _capture_worker_response(responses, failures, operation):
        try:
            responses.append(operation())
        except BaseException as exc:
            failures.append(exc)

    @staticmethod
    def _capture_close(core, completed, failures):
        try:
            core.close()
        except BaseException as exc:
            failures.append(exc)
        finally:
            completed.set()

    def send(self, envelope):
        return decode_response_frame(self.plugin.handle_frame(encode_frame(envelope), peer_id="plugin"))

    def send_raw(self, value):
        return decode_response_frame(self.plugin.handle_frame(encode_raw_frame(value), peer_id="plugin"))

    def authority_for(self, head):
        snapshot = head.read().head
        return AuthoritySnapshot(
            installation_id=snapshot.installation_id,
            generation=snapshot.generation,
            revision_digest=snapshot.revision_digest,
            transition_id=snapshot.transition_id,
            writer_fence=snapshot.writer_fence,
            terminal=snapshot.terminal,
            site=snapshot.site,
        )

    def advance_head(self, head, *, revision_digest, transition_id):
        snapshot = head.read().head
        return head.conditional_advance(
            AdvanceRequest(
                expected=snapshot.as_authority(),
                transition_id=transition_id,
                revision_digest=revision_digest,
                writer_fence=snapshot.writer_fence,
                operation_digest=_TEST_OPERATION_DIGEST,
                writer_proof=self.writer_proof_for(head, snapshot.as_authority()),
            )
        )

    def state_payload(self, record_id="record-1"):
        return {
            "record_id": record_id,
            "revision_digest": "sha256:revision-1",
            "transition_id": "transition-1",
            "payload_digest": "sha256:synthetic-payload",
        }

    def commit_payload(self, record_id="record-1", *, writer_fence=None):
        payload = self.state_payload(record_id)
        payload.pop("payload_digest")
        payload["writer_fence"] = self.head.read().head.writer_fence if writer_fence is None else writer_fence
        return payload

    def effect_request_payload(self, *, effect_kind="model-work", request_digest="sha256:effect-request"):
        return {
            "effect_kind": effect_kind,
            "request_digest": request_digest,
        }

    def effect_result_payload(
        self,
        intent,
        grant=None,
        *,
        status="accepted",
        terminal=True,
        result_digest="sha256:effect-result",
    ):
        lease_id = "lease:unclaimed" if grant is None else grant.lease.lease_id
        capability = "capability:unclaimed" if grant is None else grant.completion_capability
        return {
            "effect_id": intent["effect_id"],
            "intent_digest": intent["intent_digest"],
            "lease_id": lease_id,
            "completion_capability": capability,
            "status": status,
            "terminal": terminal,
            "result_digest": result_digest,
        }

    def assert_all_effect_paths_closed(self, plugin):
        self.assertFalse(plugin.health_writes_allowed())
        self.assertFalse(plugin.model_effects_allowed())
        self.assertFalse(plugin.outbound_effects_allowed())

    def establish_prepared(self, record_id="record-1"):
        payload = self.state_payload(record_id)
        self.assertEqual(self.send(self.command("state.candidate", "candidate-1", payload)).status, "accepted")
        self.assertEqual(self.send(self.command("state.prepare", "prepare-1", payload)).status, "accepted")

    def establish_finalized(self, record_id="record-1"):
        self.establish_prepared(record_id)
        commit = self.commit_payload(record_id)
        self.assertEqual(self.send(self.command("state.commit", "commit-1", commit)).status, "accepted")
        finalize = dict(commit)
        finalize["writer_fence"] = self.head.read().head.writer_fence
        self.assertEqual(
            self.send(self.command("state.finalize", "finalize-1", finalize, generation=2)).status,
            "accepted",
        )

    def test_valid_command_is_idempotent_and_duplicate_effect_is_not_created(self):
        envelope = self.command("state.candidate", "same-causal-id", self.state_payload())

        first = self.send(envelope)
        second = self.send(envelope)

        self.assertEqual(first.status, "accepted")
        self.assertEqual(second.to_wire(), first.to_wire())
        self.assertEqual(self.store.record_state("record-1"), "candidate")
        self.assertEqual(self.store.count_records(), 1)

    def test_concurrent_same_causal_id_serializes_before_remote_or_local_mutation(self):
        envelope = self.command("state.candidate", "concurrent-causal-id", self.state_payload())
        gate = threading.Barrier(2)
        responses = []
        failures = []

        def invoke():
            try:
                gate.wait(timeout=2)
                responses.append(self.send(envelope))
            except BaseException as exc:  # test worker must surface every failure
                failures.append(exc)

        first = threading.Thread(target=invoke)
        second = threading.Thread(target=invoke)
        first.start()
        second.start()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0].to_wire(), responses[1].to_wire())
        self.assertEqual(responses[0].status, "accepted")
        self.assertEqual(self.store.count_records(), 1)

    def test_wrong_peer_unknown_action_missing_field_extra_field_and_truncated_frame_fail_closed(self):
        envelope = self.command("state.candidate", "bad-peer", self.state_payload())
        with self.assertRaises(ProtocolViolation):
            self.plugin.invoke(envelope, peer_id="ordinary-hermes")

        unknown = envelope.to_wire()
        unknown["action"] = "state.delete"
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(encode_raw_frame(unknown), peer_id="plugin")).status,
            "rejected",
        )

        missing = envelope.to_wire()
        del missing["payload"]["payload_digest"]
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(encode_raw_frame(missing), peer_id="plugin")).status,
            "rejected",
        )

        extra = envelope.to_wire()
        extra["payload"]["unexpected"] = "value"
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(encode_raw_frame(extra), peer_id="plugin")).status,
            "rejected",
        )

        frame = encode_frame(envelope)
        truncated = frame[:-1]
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(truncated, peer_id="plugin")).status,
            "rejected",
        )

    def test_generation_and_permission_scope_are_checked_before_state_change(self):
        stale = self.send(self.command("state.candidate", "stale", self.state_payload(), generation=99))
        self.assertEqual(stale.status, "rejected")
        self.assertEqual(self.store.count_records(), 0)

        no_scope = self.command("state.candidate", "no-scope", self.state_payload()).to_wire()
        no_scope["scope"] = []
        response = decode_response_frame(
            self.plugin.handle_frame(encode_raw_frame(no_scope), peer_id="plugin")
        )
        self.assertEqual(response.status, "rejected")
        self.assertEqual(self.store.count_records(), 0)

    def test_candidate_prepare_commit_finalize_are_distinct_states(self):
        payload = self.state_payload()
        self.assertEqual(self.send(self.command("state.candidate", "candidate", payload)).status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "candidate")
        self.assertEqual(self.send(self.command("state.prepare", "prepare", payload)).status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "prepared")

        commit = self.commit_payload()
        self.assertEqual(self.send(self.command("state.commit", "commit", commit)).status, "accepted")
        self.assertEqual(self.head.read().head.revision_digest, "sha256:revision-1")

        finalize = dict(commit)
        finalize["writer_fence"] = self.head.read().head.writer_fence
        self.assertEqual(
            self.send(self.command("state.finalize", "finalize", finalize, generation=2)).status,
            "accepted",
        )
        self.assertEqual(self.store.record_state("record-1"), "final")

    def test_current_head_conflict_keeps_prepared_state_but_unknown_closes_health(self):
        self.establish_prepared()

        self.head.set_failure(FailureMode.CONFLICT, operation="advance")
        conflict_payload = self.commit_payload()
        conflict = self.send(self.command("state.commit", "conflict", conflict_payload))
        self.assertEqual(conflict.status, "unavailable")
        self.assertEqual(self.store.record_state("record-1"), "prepared")

        unknown_store = EncryptedStateStore("file:ticket110-unknown?mode=memory&cache=shared", self.key_provider)
        self.addCleanup(unknown_store.close)
        unknown_head = synthetic_head(installation_id="synthetic-unknown")
        unknown_store.seed_finalized_authority(self.authority_for(unknown_head))
        unknown_plugin = HealthPlugin(self.core_for(unknown_store, unknown_head))
        self.assertEqual(
            decode_response_frame(
                unknown_plugin.handle_frame(
                    encode_frame(self.command("state.candidate", "unknown-candidate", self.state_payload())),
                    peer_id="plugin",
                )
            ).status,
            "accepted",
        )
        self.assertEqual(
            decode_response_frame(
                unknown_plugin.handle_frame(
                    encode_frame(self.command("state.prepare", "unknown-prepare", self.state_payload())),
                    peer_id="plugin",
                )
            ).status,
            "accepted",
        )
        unknown_head.set_failure(FailureMode.UNKNOWN, operation="advance")
        unknown = decode_response_frame(
            unknown_plugin.handle_frame(
                encode_frame(self.command("state.commit", "unknown", conflict_payload)),
                peer_id="plugin",
            )
        )
        self.assertEqual(unknown.status, "unknown")
        self.assertEqual(unknown_store.record_state("record-1"), "unknown")
        self.assert_all_effect_paths_closed(unknown_plugin)

    def test_timeout_and_terminal_head_never_report_healthy(self):
        self.head.set_failure(FailureMode.TIMEOUT)
        report = self.plugin.probe(ordinary_hermes_status="healthy")
        self.assertEqual(report.state, ProbeState.UNKNOWN)
        self.assert_all_effect_paths_closed(self.plugin)

        self.head.clear_failure()
        self.head.mark_terminal()
        terminal_report = self.plugin.probe(ordinary_hermes_status="healthy")
        self.assertEqual(terminal_report.state, ProbeState.UNAVAILABLE)
        self.assert_all_effect_paths_closed(self.plugin)

    def test_unjournaled_prepared_remote_advance_fails_closed(self):
        self.establish_prepared()
        self.assertEqual(self.plugin.probe().state, ProbeState.UNKNOWN)

        advanced = self.advance_head(
            self.head,
            transition_id="transition-1",
            revision_digest="sha256:revision-1",
        )
        finalize = {
            "record_id": "record-1",
            "revision_digest": "sha256:revision-1",
            "transition_id": "transition-1",
            "writer_fence": advanced.writer_fence,
        }

        response = decode_response_frame(
            self.plugin.handle_frame(
                encode_frame(self.command("state.finalize", "crash-finalize", finalize, generation=2)),
                peer_id="plugin",
            )
        )

        self.assertEqual(response.status, "unavailable")
        self.assertEqual(response.reason_code, "pending-command-missing")
        self.assertEqual(self.store.record_state("record-1"), "prepared")
        self.assertEqual(self.head.read().head.generation, advanced.generation)
        self.assert_all_effect_paths_closed(self.plugin)

    def test_incomplete_effect_result_is_rejected_without_persisting_an_effect(self):
        intent_response = self.send(
            self.command("effect.request", "effect-request-incomplete", self.effect_request_payload())
        )
        self.assertEqual(intent_response.status, "accepted")
        grant = self.plugin.claim_effect_execution(intent_response.meta.intent)
        self.assertIsNotNone(grant)
        payload = self.effect_result_payload(intent_response.meta, grant, terminal=False)
        response = self.send(self.command("effect.result", "effect-incomplete", payload, scope=("effect:result",)))
        self.assertEqual(response.status, "rejected")
        self.assertEqual(self.store.effect_state(intent_response.meta["effect_id"]), "executing")
        self.assertIsNone(self.store.pending_effect_result(intent_response.meta["effect_id"]))

        completed = self.send(
            self.command(
                "effect.result",
                "effect-complete-after-incomplete",
                self.effect_result_payload(intent_response.meta, grant),
                scope=("effect:result",),
            )
        )
        self.assertEqual(completed.status, "accepted")
        self.assertEqual(self.store.effect_state(intent_response.meta["effect_id"]), "accepted")

    def test_unknown_effect_result_is_terminal_but_remains_unknown(self):
        intent_response = self.send(
            self.command("effect.request", "effect-request-unknown", self.effect_request_payload())
        )
        self.assertEqual(intent_response.status, "accepted")
        grant = self.plugin.claim_effect_execution(intent_response.meta.intent)
        self.assertIsNotNone(grant)
        payload = self.effect_result_payload(
            intent_response.meta,
            grant,
            status="unknown",
            result_digest="sha256:unknown",
        )
        response = self.send(self.command("effect.result", "effect-unknown", payload, scope=("effect:result",)))
        self.assertEqual(response.status, "unknown")
        self.assertEqual(self.store.effect_state(intent_response.meta["effect_id"]), "unknown")

    def test_length_and_trailing_bytes_are_rejected(self):
        frame = bytearray(encode_frame(self.command("probe", "probe-1", {}, scope=("probe",))))
        frame[0:4] = struct.pack(">I", len(frame))
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(bytes(frame), peer_id="plugin")).status,
            "rejected",
        )

        valid = encode_frame(self.command("probe", "probe-2", {}, scope=("probe",)))
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(valid + b"trailing", peer_id="plugin")).status,
            "rejected",
        )

    def test_ciphertext_storage_does_not_expose_synthetic_payload(self):
        marker = "synthetic-secret-marker"
        payload = dict(self.state_payload())
        payload["payload_digest"] = marker
        response = self.send(self.command("state.candidate", "encrypted", payload))
        self.assertEqual(response.status, "accepted")
        self.assertNotIn(marker.encode("utf-8"), self.store.raw_storage_bytes())

    def test_probe_is_content_free_and_ordinary_hermes_health_is_not_a_substitute(self):
        report = self.plugin.probe(ordinary_hermes_status="healthy")
        self.assertEqual(report.state, ProbeState.HEALTHY)
        self.assertEqual(report.content, None)
        self.assertNotIn("healthy", report.to_wire().get("checks", []))
        self.assertTrue(self.plugin.health_writes_allowed())
        self.assertTrue(self.plugin.model_effects_allowed())
        self.assertTrue(self.plugin.outbound_effects_allowed())

    def test_commit_requires_and_holds_the_prepared_writer_fence(self):
        self.establish_prepared()

        missing_wire = self.command("state.commit", "missing-fence", self.commit_payload()).to_wire()
        missing_wire["payload"].pop("writer_fence")
        missing = self.send_raw(missing_wire)
        self.assertEqual(missing.status, "rejected")
        self.assertEqual(self.store.record_state("record-1"), "prepared")
        self.assertEqual(self.head.read().head.generation, 1)

        stale = self.send(
            self.command("state.commit", "stale-fence", self.commit_payload(writer_fence="fence:stale"))
        )
        self.assertEqual(stale.status, "unavailable")
        self.assertEqual(stale.reason_code, "stale-writer-fence")
        self.assertEqual(self.store.record_state("record-1"), "prepared")
        self.assertEqual(self.head.read().head.revision_digest, "sha256:empty")
        self.assert_all_effect_paths_closed(self.plugin)

        rebound_head = synthetic_head(installation_id="synthetic-rebound")
        rebound_store = EncryptedStateStore("file:ticket110-rebound?mode=memory&cache=shared", self.key_provider)
        self.addCleanup(rebound_store.close)
        rebound_store.seed_finalized_authority(self.authority_for(rebound_head))
        rebound_plugin = HealthPlugin(self.core_for(rebound_store, rebound_head))
        rebound_payload = self.state_payload()
        self.assertEqual(
            decode_response_frame(rebound_plugin.handle_frame(encode_frame(self.command("state.candidate", "rebound-candidate", rebound_payload)), peer_id="plugin")).status,
            "accepted",
        )
        self.assertEqual(
            decode_response_frame(rebound_plugin.handle_frame(encode_frame(self.command("state.prepare", "rebound-prepare", rebound_payload)), peer_id="plugin")).status,
            "accepted",
        )
        self.advance_head(
            rebound_head,
            transition_id="transition-other",
            revision_digest="sha256:other",
        )
        rebound_commit = {
            "record_id": "record-1",
            "revision_digest": "sha256:revision-1",
            "transition_id": "transition-1",
            "writer_fence": "fence:1",
        }
        rebound = decode_response_frame(
            rebound_plugin.handle_frame(
                encode_frame(self.command("state.commit", "rebound-commit", rebound_commit, generation=2)),
                peer_id="plugin",
            )
        )
        self.assertEqual(rebound.status, "unavailable")
        self.assertEqual(rebound.reason_code, "stale-writer-fence")
        self.assertEqual(rebound_store.record_state("record-1"), "prepared")
        self.assertEqual(rebound_head.read().head.revision_digest, "sha256:other")

    def test_probe_requires_matching_local_finalized_authority(self):
        self.establish_finalized()
        snapshot = self.head.read().head
        cases = (
            ("local-finalized-revision-mismatch", replace(snapshot, revision_digest="sha256:other")),
            ("local-installation-mismatch", replace(snapshot, installation_id="synthetic-other")),
            ("local-transition-mismatch", replace(snapshot, transition_id="transition-other")),
            ("local-writer-fence-mismatch", replace(snapshot, writer_fence="fence:other")),
            ("local-site-mismatch", replace(snapshot, site="synthetic-other-site")),
        )

        for reason_code, mismatched_snapshot in cases:
            with self.subTest(reason_code=reason_code):
                writer_vault = InMemoryWriterFenceVault()
                # Probe entry is owned by the finalized local namespace.  A
                # foreign remote snapshot must be observed only after that
                # local holder is proven; otherwise the test would stop at
                # the earlier, correct copied-state holder rejection.
                writer_vault.bind(self.authority_for(self.head), _TEST_WRITER_CAPABILITY)
                writer_vault.bind(mismatched_snapshot.as_authority(), _TEST_WRITER_CAPABILITY)
                plugin = HealthPlugin(
                    self.core_for(
                        self.store,
                        SnapshotCurrentHead(mismatched_snapshot),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                report = plugin.probe()
                self.assertEqual(report.state, ProbeState.UNKNOWN)
                self.assertEqual(report.reason_code, reason_code)
                self.assert_all_effect_paths_closed(plugin)

    def test_probe_authenticates_all_local_rows_before_reporting_healthy(self):
        self.establish_finalized()
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE health_records SET state = 'candidate' WHERE record_id = ?",
                ("record-1",),
            )

        report = self.plugin.probe()

        self.assertEqual(report.state, ProbeState.UNAVAILABLE)
        self.assertEqual(report.reason_code, "health-key-unavailable")
        self.assert_all_effect_paths_closed(self.plugin)

    def test_probe_requires_an_authenticated_final_record_for_the_finalized_authority(self):
        self.establish_finalized()
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM health_records WHERE record_id = ?", ("record-1",))

        report = self.plugin.probe()

        self.assertEqual(report.state, ProbeState.UNAVAILABLE)
        self.assertEqual(report.reason_code, "health-key-unavailable")
        self.assert_all_effect_paths_closed(self.plugin)

    def test_probe_fails_closed_without_a_local_finalized_authority(self):
        store = EncryptedStateStore("file:ticket110-unanchored?mode=memory&cache=shared", self.key_provider)
        self.addCleanup(store.close)
        plugin = HealthPlugin(self.core_for(store, synthetic_head(installation_id="synthetic-unanchored")))

        report = plugin.probe()

        self.assertEqual(report.state, ProbeState.UNKNOWN)
        self.assertEqual(report.reason_code, "local-finalized-authority-missing")
        self.assert_all_effect_paths_closed(plugin)

    def test_scope_is_exactly_the_scope_for_the_current_action(self):
        candidate = self.command("state.candidate", "extra-scope", self.state_payload()).to_wire()
        for scope in (
            ["state:candidate", "state:commit"],
            ["state:prepare"],
            ["state:candidate", "state:candidate"],
        ):
            with self.subTest(scope=scope):
                candidate["scope"] = scope
                response = self.send_raw(candidate)
                self.assertEqual(response.status, "rejected")
                self.assertEqual(response.reason_code, "permission scope denied")

        probe = self.command("probe", "extra-probe-scope", {}, scope=("probe",)).to_wire()
        probe["scope"] = ["probe", "state:candidate"]
        response = self.send_raw(probe)
        self.assertEqual(response.status, "rejected")
        self.assertEqual(response.reason_code, "permission scope denied")

        effect = self.command("effect.request", "extra-effect-scope", self.effect_request_payload()).to_wire()
        effect["scope"] = ["effect:request", "effect:result"]
        response = self.send_raw(effect)
        self.assertEqual(response.status, "rejected")
        self.assertEqual(response.reason_code, "permission scope denied")
        self.assertEqual(self.store.count_records(), 0)
        self.assertEqual(self.store.count_effects(), 0)
        self.assertEqual(self.head.read().head.generation, 1)

    def test_core_issues_a_controlled_effect_intent_before_accepting_a_result(self):
        forged = {
            "effect_id": "effect:forged",
            "intent_digest": "sha256:forged",
            "lease_id": "lease:forged",
            "completion_capability": "capability:forged",
            "status": "accepted",
            "terminal": True,
            "result_digest": "sha256:result",
        }
        rejected = self.send(self.command("effect.result", "forged-result", forged))
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.reason_code, "effect-intent-required")
        self.assertEqual(self.store.count_effects(), 0)

        issued = self.send(
            self.command("effect.request", "core-issued-intent", self.effect_request_payload())
        )
        self.assertEqual(issued.status, "accepted")
        self.assertEqual(issued.reason_code, "effect-intent-issued")
        intent = issued.meta
        self.assertEqual(intent["effect_kind"], "model-work")
        self.assertEqual(intent.intent.authority.installation_id, "synthetic-installation")
        self.assertEqual(intent.intent.authority.generation, 1)
        self.assertEqual(intent.intent.authority.writer_fence, "fence:1")
        self.assertEqual(self.store.effect_state(intent["effect_id"]), "intent")

        unclaimed = self.send(
            self.command("effect.result", "unclaimed-result", self.effect_result_payload(intent))
        )
        self.assertEqual(unclaimed.status, "rejected")
        self.assertEqual(unclaimed.reason_code, "effect-execution-required")
        grant = self.plugin.claim_effect_execution(intent.intent)
        self.assertIsNotNone(grant)
        self.assertEqual(self.store.effect_state(intent["effect_id"]), "executing")

        result = self.send(
            self.command("effect.result", "issued-result", self.effect_result_payload(intent, grant))
        )
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.reason_code, "effect-terminal")
        self.assertEqual(self.store.effect_state(intent["effect_id"]), "accepted")

        duplicate = self.send(
            self.command("effect.result", "duplicate-result", self.effect_result_payload(intent))
        )
        self.assertEqual(duplicate.status, "rejected")
        self.assertEqual(duplicate.reason_code, "effect-intent-required")

    def test_unterminated_effect_intent_closes_global_gates_until_core_claim_and_terminal_result(self):
        issued = self.send(
            self.command("effect.request", "controlled-effect-intent", self.effect_request_payload())
        )

        report = self.plugin.probe()
        self.assertEqual(report.state, ProbeState.UNKNOWN)
        self.assertEqual(report.reason_code, "effect-result-unknown")
        self.assert_all_effect_paths_closed(self.plugin)
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "executing")
        self.assertFalse(self.plugin.claim_effect_execution(issued.meta.intent))
        self.assert_all_effect_paths_closed(self.plugin)

        completed = self.send(
            self.command(
                "effect.result",
                "controlled-effect-result",
                self.effect_result_payload(issued.meta, grant),
            )
        )
        self.assertEqual(completed.status, "accepted")
        self.assertEqual(self.plugin.probe().state, ProbeState.HEALTHY)
        self.assertTrue(self.plugin.health_writes_allowed())
        self.assertTrue(self.plugin.model_effects_allowed())
        self.assertTrue(self.plugin.outbound_effects_allowed())

    def test_effect_execution_claim_holds_the_current_writer_fence_until_terminal_result(self):
        issued = self.send(
            self.command("effect.request", "fenced-effect-lease", self.effect_request_payload())
        )
        self.assertEqual(issued.status, "accepted")

        grant = self.plugin.claim_effect_execution(issued.meta.intent)

        self.assertIsNotNone(grant)
        expected = self.head.read().head.as_authority()
        with self.assertRaises(HeadConflict):
            self.head.conditional_advance(
                AdvanceRequest(
                    expected=expected,
                    transition_id="transition-blocked-by-effect-lease",
                    revision_digest="sha256:blocked-by-effect-lease",
                    writer_fence=expected.writer_fence,
                    operation_digest=_TEST_OPERATION_DIGEST,
                    writer_proof=self.writer_proof_for(self.head, expected),
                )
            )
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "executing")

        terminal = self.send(
            self.command(
                "effect.result",
                "fenced-effect-terminal",
                self.effect_result_payload(issued.meta, grant),
            )
        )
        self.assertEqual(terminal.status, "accepted")
        advanced = self.head.conditional_advance(
            AdvanceRequest(
                expected=expected,
                transition_id="transition-after-effect-lease",
                revision_digest="sha256:after-effect-lease",
                writer_fence=expected.writer_fence,
                operation_digest=_TEST_OPERATION_DIGEST,
                writer_proof=self.writer_proof_for(self.head, expected),
            )
        )
        self.assertEqual(advanced.generation, 2)

    def test_execution_lease_response_loss_recovers_by_effect_identity_without_a_second_lease(self):
        issued = self.send(
            self.command("effect.request", "lost-effect-lease", self.effect_request_payload())
        )
        plugin = HealthPlugin(
            self.core_for(
                self.store,
                LostExecutionLeaseResponseCurrentHead(self.head),
                execution_capability_vault=self.execution_vault,
            )
        )

        first_claim = plugin.claim_effect_execution(issued.meta.intent)

        self.assertIsNone(first_claim)
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "claiming")
        expected = self.head.read().head.as_authority()
        with self.assertRaises(HeadConflict):
            self.head.conditional_advance(
                AdvanceRequest(
                    expected=expected,
                    transition_id="transition-blocked-after-lost-lease",
                    revision_digest="sha256:blocked-after-lost-lease",
                    writer_fence=expected.writer_fence,
                    operation_digest=_TEST_OPERATION_DIGEST,
                    writer_proof=self.writer_proof_for(self.head, expected),
                )
            )

        recovered_claim = plugin.claim_effect_execution(issued.meta.intent)

        self.assertIsNotNone(recovered_claim)
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "executing")
        terminal = self.command(
            "effect.result",
            "lost-effect-lease-terminal",
            self.effect_result_payload(issued.meta, recovered_claim),
        )
        lost_release = decode_response_frame(plugin.handle_frame(encode_frame(terminal), peer_id="plugin"))
        self.assertEqual(lost_release.status, "unknown")
        self.assertEqual(lost_release.reason_code, "effect-lease-unknown")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "executing")
        self.assert_all_effect_paths_closed(plugin)

        recovered_terminal = decode_response_frame(plugin.handle_frame(encode_frame(terminal), peer_id="plugin"))

        self.assertEqual(recovered_terminal.status, "accepted")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "accepted")
        advanced = self.head.conditional_advance(
            AdvanceRequest(
                expected=expected,
                transition_id="transition-after-lost-effect-lease",
                revision_digest="sha256:after-lost-effect-lease",
                writer_fence=expected.writer_fence,
                operation_digest=_TEST_OPERATION_DIGEST,
                writer_proof=self.writer_proof_for(self.head, expected),
            )
        )
        self.assertEqual(advanced.generation, 2)

    def test_replayed_effect_intent_needs_a_fresh_core_execution_claim(self):
        request = self.command("effect.request", "stale-replayed-effect", self.effect_request_payload())
        issued = self.send(request)
        self.advance_head(
            self.head,
            transition_id="transition:after-effect-intent",
            revision_digest="sha256:after-effect-intent",
        )

        replayed = self.send(request)

        self.assertEqual(replayed.to_wire(), issued.to_wire())
        self.assertFalse(self.plugin.claim_effect_execution(replayed.meta.intent))
        self.assert_all_effect_paths_closed(self.plugin)

    def test_replayed_effect_intent_cannot_claim_execution_when_key_identity_is_lost(self):
        provider = FlakyKeyIdentityProvider()
        store = EncryptedStateStore("file:ticket110-effect-key-replay?mode=memory&cache=shared", provider)
        self.addCleanup(store.close)
        head = synthetic_head(installation_id="synthetic-effect-key-replay")
        store.seed_finalized_authority(self.authority_for(head))
        plugin = HealthPlugin(
            self.core_for(store, head, execution_capability_vault=InMemoryExecutionCapabilityVault())
        )
        request = self.command("effect.request", "key-stale-replayed-effect", self.effect_request_payload())
        issued = decode_response_frame(plugin.handle_frame(encode_frame(request), peer_id="plugin"))
        provider.fail_identity = True

        replayed = decode_response_frame(plugin.handle_frame(encode_frame(request), peer_id="plugin"))

        self.assertEqual(replayed.to_wire(), issued.to_wire())
        self.assertFalse(plugin.claim_effect_execution(replayed.meta.intent))
        self.assert_all_effect_paths_closed(plugin)

    def test_maximum_length_effect_causal_id_has_a_bounded_replayable_intent_identifier(self):
        request = self.command(
            "effect.request",
            "x" * MAX_ID_BYTES,
            self.effect_request_payload(),
        )

        first = self.send(request)
        replayed = self.send(request)

        self.assertEqual(first.status, "accepted")
        self.assertEqual(replayed.to_wire(), first.to_wire())
        self.assertLessEqual(len(first.meta["effect_id"].encode("utf-8")), MAX_ID_BYTES)
        self.assertEqual(self.store.effect_state(first.meta["effect_id"]), "intent")

    def test_transition_and_terminal_branches_fail_closed(self):
        payload = self.state_payload()
        no_candidate = self.send(self.command("state.prepare", "no-candidate", payload))
        self.assertEqual(no_candidate.status, "rejected")

        self.assertEqual(self.send(self.command("state.candidate", "candidate-transition", payload)).status, "accepted")
        changed = dict(payload)
        changed["revision_digest"] = "sha256:changed"
        changed_transition = self.send(self.command("state.prepare", "changed-transition", changed))
        self.assertEqual(changed_transition.status, "rejected")
        self.assertEqual(changed_transition.reason_code, "record transition changed")

        commit_before_prepare = self.send(self.command("state.commit", "commit-before-prepare", self.commit_payload()))
        self.assertEqual(commit_before_prepare.status, "rejected")
        finalize_before_prepare = self.send(
            self.command("state.finalize", "finalize-before-prepare", self.commit_payload())
        )
        self.assertEqual(finalize_before_prepare.status, "rejected")
        self.assertEqual(self.head.read().head.generation, 1)

        self.assertEqual(self.send(self.command("state.prepare", "prepare-terminal", payload)).status, "accepted")
        self.head.mark_terminal()
        terminal_commit = self.send(
            self.command("state.commit", "terminal-commit", self.commit_payload(), generation=2)
        )
        self.assertEqual(terminal_commit.status, "unavailable")
        self.assertEqual(terminal_commit.reason_code, "current-head-terminal")
        terminal_finalize = self.send(
            self.command("state.finalize", "terminal-finalize", self.commit_payload(), generation=2)
        )
        self.assertEqual(terminal_finalize.status, "unavailable")
        self.assertEqual(terminal_finalize.reason_code, "current-head-terminal")
        terminal_effect = self.send(
            self.command("effect.request", "terminal-effect", self.effect_request_payload(), generation=2)
        )
        self.assertEqual(terminal_effect.status, "unavailable")
        self.assertEqual(terminal_effect.reason_code, "current-head-terminal")
        self.assertEqual(self.store.record_state("record-1"), "prepared")
        self.assertEqual(self.store.count_effects(), 0)
        self.assert_all_effect_paths_closed(self.plugin)

    def test_finalized_record_cannot_be_reopened(self):
        self.establish_finalized()

        reopened = self.send(self.command("state.candidate", "reopen-final", self.state_payload(), generation=2))

        self.assertEqual(reopened.status, "rejected")
        self.assertEqual(self.store.record_state("record-1"), "final")
        self.assertEqual(self.head.read().head.generation, 2)

    def test_prepared_revision_is_bound_to_its_installation(self):
        self.establish_prepared()
        other_installation = synthetic_head(installation_id="synthetic-other-installation")
        other_plugin = HealthPlugin(self.core_for(self.store, other_installation))

        response = decode_response_frame(
            other_plugin.handle_frame(
                encode_frame(self.command("state.commit", "cross-installation", self.commit_payload())),
                peer_id="plugin",
            )
        )

        self.assertEqual(response.status, "unavailable")
        self.assertEqual(self.store.record_state("record-1"), "prepared")
        self.assertEqual(other_installation.read().head.generation, 1)
        finalize = decode_response_frame(
            other_plugin.handle_frame(
                encode_frame(
                    self.command(
                        "state.finalize",
                        "cross-installation-finalize",
                        self.commit_payload(),
                    )
                ),
                peer_id="plugin",
            )
        )
        self.assertEqual(finalize.status, "unavailable")
        self.assertEqual(self.store.record_state("record-1"), "prepared")
        self.assertEqual(other_installation.read().head.generation, 1)
        self.assertNotEqual(other_plugin.probe().state, ProbeState.HEALTHY)

    def test_successful_remote_cas_with_lost_response_recovers_by_transition_lookup(self):
        self.establish_prepared()
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        original_commit_payload = self.commit_payload()

        commit_envelope = self.command("state.commit", "lost-response-commit", original_commit_payload)
        commit = self.send(commit_envelope)

        self.assertEqual(commit.status, "unknown")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assertEqual(self.head.read().head.generation, 2)
        self.assertEqual(self.head.read().head.transition_id, "transition-1")

        self.head.clear_failure()
        recovered_commit = self.send(commit_envelope)
        self.assertEqual(recovered_commit.status, "accepted")
        self.assertEqual(recovered_commit.meta["generation"], 2)
        self.assertEqual(recovered_commit.meta["writer_fence"], "fence:1")
        self.assertEqual(self.store.record_state("record-1"), "committed")
        self.assertEqual(self.send(commit_envelope).to_wire(), recovered_commit.to_wire())

        recovered_finalize = self.commit_payload()
        recovered_finalize["writer_fence"] = self.head.read().head.writer_fence
        response = self.send(
            self.command("state.finalize", "recover-lost-response", recovered_finalize, generation=2)
        )

        self.assertEqual(response.status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "final")
        self.assertEqual(self.plugin.probe().state, ProbeState.HEALTHY)

    def test_transition_recovery_requires_the_original_writer_fence_proof(self):
        self.establish_prepared()
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        original_commit = self.command("state.commit", "lookup-fence-commit", self.commit_payload())
        self.assertEqual(self.send(original_commit).status, "unknown")
        self.head.clear_failure()

        forged_plugin = HealthPlugin(self.core_for(self.store, WrongFenceLookupCurrentHead(self.head)))
        response = decode_response_frame(
            forged_plugin.handle_frame(
                encode_frame(original_commit),
                peer_id="plugin",
            )
        )

        self.assertEqual(response.status, "unavailable")
        self.assertEqual(response.reason_code, "current-head-malformed")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        guard = self.store.current_head_observation_guard()
        self.assertIsNotNone(guard)
        self.assertIsNone(guard.binding)
        self.assertEqual(
            self.send(original_commit).reason_code,
            "current-head-observation-incomplete",
        )
        self.assert_all_effect_paths_closed(forged_plugin)

    def test_unknown_before_remote_advance_never_retries_an_ambiguous_cas(self):
        self.establish_prepared()
        commit = self.command("state.commit", "unknown-before-advance", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN, operation="advance")

        self.assertEqual(self.send(commit).status, "unknown")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assertEqual(self.head.read().head.generation, 1)

        self.head.clear_failure()
        recovered = self.send(commit)
        self.assertEqual(recovered.status, "unavailable")
        self.assertEqual(recovered.reason_code, "transition-recovery-unconfirmed")
        replay = self.send(commit)
        self.assertEqual(replay.status, "unavailable")
        # The first lookup-only recovery intentionally consumes the exact
        # response-loss binding into a generic tripwire.  A subsequent replay
        # may not regain a mutation/recovery privilege from that ambiguous
        # outcome.
        self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
        self.assertEqual(self.head.read().head.generation, 1)
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assert_all_effect_paths_closed(self.plugin)

    def test_pending_unknown_causal_id_rejects_a_different_command_without_poisoning_recovery(self):
        self.establish_prepared()
        commit = self.command("state.commit", "pending-causal-id", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        self.assertEqual(self.send(commit).status, "unknown")

        conflicting = commit.to_wire()
        conflicting["source"] = "synthetic-other-source"
        rejected = self.send_raw(conflicting)
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.reason_code, "causal-id-conflict")
        self.assertEqual(self.store.record_state("record-1"), "unknown")

        self.head.clear_failure()
        recovered = self.send(commit)
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "committed")

    def test_pending_unknown_record_rejects_a_new_causal_id_takeover(self):
        self.establish_prepared()
        original = self.command("state.commit", "original-pending-causal", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN, operation="advance")
        self.assertEqual(self.send(original).status, "unknown")
        self.head.clear_failure()

        takeover = self.command("state.commit", "takeover-pending-causal", self.commit_payload())
        rejected = self.send(takeover)
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.reason_code, "causal-id-conflict")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assertEqual(self.head.read().head.generation, 1)

        recovered = self.send(original)
        self.assertEqual(recovered.status, "unavailable")
        self.assertEqual(recovered.reason_code, "transition-recovery-unconfirmed")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assertEqual(self.head.read().head.generation, 1)

    def test_pending_commit_must_recover_by_its_original_causal_command_before_finalize(self):
        self.establish_prepared()
        commit = self.command("state.commit", "pending-finalize-commit", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        self.assertEqual(self.send(commit).status, "unknown")
        self.head.clear_failure()

        finalize = self.commit_payload()
        blocked = self.send(
            self.command("state.finalize", "pending-finalize", finalize, generation=2)
        )

        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "pending-command-owner-required")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assert_all_effect_paths_closed(self.plugin)
        recovered = self.send(commit)
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(recovered.reason_code, "current-head-advanced")
        self.assertEqual(recovered.meta["generation"], 2)
        finalized = self.send(
            self.command("state.finalize", "pending-finalize", finalize, generation=2)
        )
        self.assertEqual(finalized.status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "final")
        self.assertEqual(self.send(commit).to_wire(), recovered.to_wire())

    def test_business_write_and_receipt_are_one_atomic_commit(self):
        store = CrashBeforeReceiptStore("file:ticket110-receipt-crash?mode=memory&cache=shared", self.key_provider)
        self.addCleanup(store.close)
        head = synthetic_head(installation_id="synthetic-receipt-crash")
        store.seed_finalized_authority(self.authority_for(head))
        plugin = HealthPlugin(self.core_for(store, head))
        envelope = self.command("state.candidate", "crash-causal-id", self.state_payload())

        with self.assertRaises(SyntheticCrash):
            plugin.handle_frame(encode_frame(envelope), peer_id="plugin")

        self.assertIsNone(store.record_state("record-1"))
        recovered_plugin = HealthPlugin(self.core_for(store, head))
        retried = decode_response_frame(
            recovered_plugin.handle_frame(encode_frame(envelope), peer_id="plugin")
        )
        self.assertEqual(retried.status, "accepted")
        self.assertEqual(store.record_state("record-1"), "candidate")

    def test_sqlite_commit_failure_after_remote_cas_returns_unavailable_and_recovers(self):
        store = CommitFailureStore("file:ticket110-sqlite-commit-failure?mode=memory&cache=shared", self.key_provider)
        self.addCleanup(store.close)
        head = synthetic_head(installation_id="synthetic-sqlite-commit-failure")
        store.seed_finalized_authority(self.authority_for(head))
        plugin = HealthPlugin(self.core_for(store, head))
        payload = self.state_payload()
        for action, causal_id in (
            ("state.candidate", "sqlite-failure-candidate"),
            ("state.prepare", "sqlite-failure-prepare"),
        ):
            self.assertEqual(
                decode_response_frame(
                    plugin.handle_frame(
                        encode_frame(self.command(action, causal_id, payload)),
                        peer_id="plugin",
                    )
                ).status,
                "accepted",
            )
        commit = {
            "record_id": "record-1",
            "revision_digest": "sha256:revision-1",
            "transition_id": "transition-1",
            "writer_fence": "fence:1",
        }
        original = self.command("state.commit", "sqlite-failure-commit", commit)
        store.fail_commit_after_receipt = True

        response = decode_response_frame(
            plugin.handle_frame(encode_frame(original), peer_id="plugin")
        )

        self.assertEqual(response.status, "unavailable")
        self.assertEqual(response.reason_code, "health-state-unavailable")
        self.assertFalse(store._connection.in_transaction)
        self.assertEqual(store.record_state("record-1"), "prepared")
        self.assertEqual(head.read().head.generation, 2)

        store.clear_commit_failure()
        recovered = decode_response_frame(
            plugin.handle_frame(encode_frame(original), peer_id="plugin")
        )
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(recovered.meta["generation"], 2)
        self.assertEqual(store.record_state("record-1"), "committed")

    def test_rollback_failure_poisoning_never_allows_a_healthy_probe_on_uncommitted_state(self):
        store = RollbackFailureStore("file:ticket110-rollback-failure?mode=memory&cache=shared", self.key_provider)
        head = synthetic_head(installation_id="synthetic-rollback-failure")
        store.seed_finalized_authority(self.authority_for(head))
        plugin = HealthPlugin(self.core_for(store, head))
        store.fail_commit_and_rollback_after_receipt = True
        candidate = self.command("state.candidate", "rollback-failure-candidate", self.state_payload())
        try:
            failed = decode_response_frame(
                plugin.handle_frame(encode_frame(candidate), peer_id="plugin")
            )

            self.assertEqual(failed.status, "unavailable")
            self.assertEqual(failed.reason_code, "health-state-unavailable")
            self.assertTrue(store._connection.in_transaction)
            with self.assertRaises(StoreUnavailable):
                store.record_state("record-1")
            report = plugin.probe()
            self.assertEqual(report.state, ProbeState.UNAVAILABLE)
            self.assertEqual(report.reason_code, "health-state-unavailable")
            self.assert_all_effect_paths_closed(plugin)
        finally:
            store.clear_transaction_failure()
            store._connection.rollback()
            store.close()

    def test_sqlite_business_write_failure_fails_closed_and_allows_a_clean_retry(self):
        def deny_health_record_insert(action, argument_one, argument_two, database, trigger):
            del argument_two, database, trigger
            if action == sqlite3.SQLITE_INSERT and argument_one == "health_records":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        candidate = self.command("state.candidate", "sqlite-write-failure", self.state_payload())
        self.store._connection.set_authorizer(deny_health_record_insert)

        failed = self.send(candidate)

        self.assertEqual(failed.status, "unavailable")
        self.assertEqual(failed.reason_code, "health-state-unavailable")
        self.assertFalse(self.store._connection.in_transaction)
        self.assertIsNone(self.store.record_state("record-1"))

        self.store._connection.set_authorizer(None)
        recovered = self.send(candidate)
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "candidate")

    def test_sqlite_probe_read_failure_is_unavailable_and_recovers_when_transient(self):
        def deny_finalized_authority_read(action, argument_one, argument_two, database, trigger):
            del argument_two, database, trigger
            if action == sqlite3.SQLITE_READ and argument_one == "finalized_authority":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.store._connection.set_authorizer(deny_finalized_authority_read)

        failed = self.plugin.probe()

        self.assertEqual(failed.state, ProbeState.UNAVAILABLE)
        self.assertEqual(failed.reason_code, "health-state-unavailable")
        self.assert_all_effect_paths_closed(self.plugin)

        self.store._connection.set_authorizer(None)
        recovered = self.plugin.probe()
        self.assertEqual(recovered.state, ProbeState.HEALTHY)
        self.assertTrue(self.plugin.health_writes_allowed())
        self.assertTrue(self.plugin.model_effects_allowed())
        self.assertTrue(self.plugin.outbound_effects_allowed())

    def test_key_identity_failure_closes_the_probe_and_all_effect_paths(self):
        provider = FlakyKeyIdentityProvider()
        store = EncryptedStateStore("file:ticket110-key-identity-failure?mode=memory&cache=shared", provider)
        self.addCleanup(store.close)
        head = synthetic_head(installation_id="synthetic-key-identity-failure")
        store.seed_finalized_authority(self.authority_for(head))
        plugin = HealthPlugin(self.core_for(store, head))
        provider.fail_identity = True

        report = plugin.probe()

        self.assertEqual(report.state, ProbeState.UNAVAILABLE)
        self.assertEqual(report.reason_code, "health-key-unavailable")
        self.assert_all_effect_paths_closed(plugin)

    def test_key_check_commit_failure_rolls_back_and_recovers_without_a_false_healthy_probe(self):
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM key_check WHERE slot = 1")

        def deny_commit(action, argument_one, argument_two, database, trigger):
            del argument_two, database, trigger
            if action == sqlite3.SQLITE_TRANSACTION and argument_one == "COMMIT":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.store._connection.set_authorizer(deny_commit)
        failed = self.plugin.probe()

        self.assertEqual(failed.state, ProbeState.UNAVAILABLE)
        self.assertEqual(failed.reason_code, "health-state-unavailable")
        self.assertFalse(self.store._connection.in_transaction)
        self.assert_all_effect_paths_closed(self.plugin)

        self.store._connection.set_authorizer(None)
        recovered = self.plugin.probe()
        self.assertEqual(recovered.state, ProbeState.HEALTHY)
        self.assertFalse(self.store._connection.in_transaction)

    def test_base_exception_rolls_back_the_outer_transaction_before_it_is_reraised(self):
        with self.assertRaises(SyntheticStop):
            with self.store.transaction() as connection:
                connection.execute(
                    "INSERT INTO receipts(causal_id, status, reason_code) VALUES (?, ?, ?)",
                    ("synthetic-stop", "accepted", "synthetic"),
                )
                raise SyntheticStop("synthetic cancellation")

        self.assertFalse(self.store._connection.in_transaction)
        self.assertIsNone(
            self.store._connection.execute(
                "SELECT 1 FROM receipts WHERE causal_id = ?", ("synthetic-stop",)
            ).fetchone()
        )
        self.assertEqual(
            self.send(self.command("state.candidate", "post-stop-candidate", self.state_payload())).status,
            "accepted",
        )

    def test_sqlite_business_write_after_remote_cas_fails_closed_and_recovers_the_original_command(self):
        self.establish_prepared()
        commit = self.command("state.commit", "sqlite-body-after-cas", self.commit_payload())

        def deny_health_record_mutation(action, argument_one, argument_two, database, trigger):
            del argument_two, database, trigger
            if argument_one == "health_records" and action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.store._connection.set_authorizer(deny_health_record_mutation)
        failed = self.send(commit)

        self.assertEqual(failed.status, "unavailable")
        self.assertEqual(failed.reason_code, "health-state-unavailable")
        self.assertFalse(self.store._connection.in_transaction)
        self.assertEqual(self.store.record_state("record-1"), "prepared")
        self.assertEqual(self.head.read().head.generation, 2)
        pending = self.store.pending_for_record("record-1")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.command.to_wire(), commit.to_wire())
        self.assert_all_effect_paths_closed(self.plugin)

        self.store._connection.set_authorizer(None)
        recovered = self.send(commit)
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(recovered.meta["generation"], 2)
        self.assertEqual(self.store.record_state("record-1"), "committed")
        self.assertIsNone(self.store.pending_for_record("record-1"))

    def test_unclassified_current_head_read_failure_is_unavailable_and_recovers(self):
        current_head = GenericFailureCurrentHead(self.head)
        plugin = HealthPlugin(self.core_for(self.store, current_head))
        current_head.fail_read = True

        response = decode_response_frame(
            plugin.handle_frame(
                encode_frame(self.command("state.candidate", "generic-read-failure", self.state_payload())),
                peer_id="plugin",
            )
        )

        self.assertEqual(response.status, "unavailable")
        self.assertEqual(response.reason_code, "current-head-unavailable")
        self.assertEqual(plugin.probe().state, ProbeState.UNAVAILABLE)
        self.assert_all_effect_paths_closed(plugin)

        current_head.fail_read = False
        self.assertEqual(plugin.probe().state, ProbeState.HEALTHY)

    def test_invalid_current_head_authority_is_fail_closed_at_the_adapter_boundary(self):
        plugin = HealthPlugin(self.core_for(self.store, InvalidAuthorityCurrentHead()))

        response = decode_response_frame(
            plugin.handle_frame(
                encode_frame(self.command("state.candidate", "invalid-current-head", self.state_payload())),
                peer_id="plugin",
            )
        )

        self.assertEqual(response.status, "unavailable")
        self.assertEqual(response.reason_code, "current-head-unavailable")
        self.assertEqual(plugin.probe().state, ProbeState.UNAVAILABLE)
        self.assert_all_effect_paths_closed(plugin)

    def test_semantically_forged_current_head_cas_response_is_recovered_fail_closed(self):
        self.establish_prepared()
        plugin = HealthPlugin(self.core_for(self.store, ForgedAdvanceCurrentHead(self.head)))
        commit = self.command("state.commit", "forged-advance", self.commit_payload())

        response = decode_response_frame(plugin.handle_frame(encode_frame(commit), peer_id="plugin"))

        self.assertEqual(response.status, "unavailable")
        self.assertEqual(response.reason_code, "current-head-unavailable")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        pending = self.store.pending_for_record("record-1")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.command.to_wire(), commit.to_wire())
        self.assertEqual(self.head.read().head.generation, 2)
        self.assertEqual(self.head.read().head.revision_digest, "sha256:revision-1")
        self.assert_all_effect_paths_closed(plugin)

    def test_forged_current_head_writer_fence_is_not_accepted_and_recovers_by_transition_lookup(self):
        self.establish_prepared()
        plugin = HealthPlugin(self.core_for(self.store, WrongFenceAdvanceCurrentHead(self.head)))
        commit = self.command("state.commit", "forged-fence-advance", self.commit_payload())

        failed = decode_response_frame(plugin.handle_frame(encode_frame(commit), peer_id="plugin"))

        self.assertEqual(failed.status, "unavailable")
        self.assertEqual(failed.reason_code, "current-head-unavailable")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assertIsNotNone(self.store.pending_for_record("record-1"))
        self.assertEqual(self.head.read().head.writer_fence, "fence:1")
        self.assert_all_effect_paths_closed(plugin)

        recovered = decode_response_frame(plugin.handle_frame(encode_frame(commit), peer_id="plugin"))
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(recovered.meta["writer_fence"], "fence:1")
        self.assertEqual(self.store.record_state("record-1"), "committed")

    def test_oversized_remote_writer_fence_fails_closed_without_rejecting_an_advanced_cas(self):
        self.establish_prepared()
        plugin = HealthPlugin(self.core_for(self.store, OversizedFenceAdvanceCurrentHead(self.head)))
        commit = self.command("state.commit", "oversized-remote-fence", self.commit_payload())

        failed = decode_response_frame(plugin.handle_frame(encode_frame(commit), peer_id="plugin"))

        self.assertEqual(failed.status, "unavailable")
        self.assertEqual(failed.reason_code, "current-head-unavailable")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        pending = self.store.pending_for_record("record-1")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.command.to_wire(), commit.to_wire())
        self.assertEqual(self.head.read().head.generation, 2)
        self.assert_all_effect_paths_closed(plugin)

    def test_ambiguous_cas_recovery_never_retries_into_a_forged_writer_fence(self):
        self.establish_prepared()
        commit = self.command("state.commit", "unknown-forged-fence", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN, operation="advance")
        self.assertEqual(self.send(commit).status, "unknown")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.head.clear_failure()
        plugin = HealthPlugin(self.core_for(self.store, WrongFenceAdvanceCurrentHead(self.head)))

        failed = decode_response_frame(plugin.handle_frame(encode_frame(commit), peer_id="plugin"))

        self.assertEqual(failed.status, "unavailable")
        self.assertEqual(failed.reason_code, "transition-recovery-unconfirmed")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assertEqual(self.head.read().head.writer_fence, "fence:1")
        self.assert_all_effect_paths_closed(plugin)

        recovered = decode_response_frame(plugin.handle_frame(encode_frame(commit), peer_id="plugin"))
        self.assertEqual(recovered.status, "unavailable")
        self.assertEqual(recovered.reason_code, "current-head-observation-incomplete")
        self.assertEqual(self.head.read().head.generation, 1)
        self.assertEqual(self.store.record_state("record-1"), "unknown")

    def test_unclassified_current_head_lookup_failure_consumes_the_recovery_binding(self):
        store = EncryptedStateStore("file:ticket110-generic-lookup?mode=memory&cache=shared", self.key_provider)
        self.addCleanup(store.close)
        head = synthetic_head(installation_id="synthetic-generic-lookup")
        current_head = GenericFailureCurrentHead(head)
        store.seed_finalized_authority(self.authority_for(head))
        plugin = HealthPlugin(self.core_for(store, current_head))
        payload = self.state_payload()
        for action, causal_id in (("state.candidate", "generic-lookup-candidate"), ("state.prepare", "generic-lookup-prepare")):
            self.assertEqual(
                decode_response_frame(
                    plugin.handle_frame(
                        encode_frame(self.command(action, causal_id, payload)),
                        peer_id="plugin",
                    )
                ).status,
                "accepted",
            )
        commit_payload = {
            "record_id": "record-1",
            "revision_digest": "sha256:revision-1",
            "transition_id": "transition-1",
            "writer_fence": head.read().head.writer_fence,
        }
        commit = self.command("state.commit", "generic-lookup-commit", commit_payload)
        head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        self.assertEqual(
            decode_response_frame(plugin.handle_frame(encode_frame(commit), peer_id="plugin")).status,
            "unknown",
        )
        head.clear_failure()
        current_head.fail_lookup = True

        failed = decode_response_frame(plugin.handle_frame(encode_frame(commit), peer_id="plugin"))
        guard = store.current_head_observation_guard()

        self.assertEqual(failed.status, "unavailable")
        self.assertEqual(failed.reason_code, "current-head-lookup-unclassified")
        self.assertEqual(store.record_state("record-1"), "unknown")
        self.assertIsNotNone(guard)
        self.assertIsNone(guard.binding)
        self.assert_all_effect_paths_closed(plugin)

        current_head.fail_lookup = False
        recovered = decode_response_frame(plugin.handle_frame(encode_frame(commit), peer_id="plugin"))
        self.assertEqual(recovered.status, "unavailable")
        self.assertEqual(recovered.reason_code, "current-head-observation-incomplete")
        self.assertEqual(store.record_state("record-1"), "unknown")

    def test_adapter_mutation_cannot_rebind_or_corrupt_the_cas_operation_identity(self):
        for mode in ("operation-digest", "nested-authority"):
            with self.subTest(mode=mode):
                store = EncryptedStateStore(
                    f"file:ticket110-mutable-cas-{mode}?mode=memory&cache=shared",
                    self.key_provider,
                )
                self.addCleanup(store.close)
                head = synthetic_head(installation_id=f"synthetic-mutable-cas-{mode}")
                writer_vault = self.writer_vault_for(head)
                store.seed_finalized_authority(self.authority_for(head))
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        MutatingAdvanceRequestCurrentHead(head, mode),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                payload = self.state_payload()
                self.assertEqual(
                    plugin.invoke(
                        self.command("state.candidate", f"mutable-candidate-{mode}", payload),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                self.assertEqual(
                    plugin.invoke(
                        self.command("state.prepare", f"mutable-prepare-{mode}", payload),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                commit = self.command(
                    "state.commit",
                    f"mutable-commit-{mode}",
                    {
                        "record_id": "record-1",
                        "revision_digest": "sha256:revision-1",
                        "transition_id": "transition-1",
                        "writer_fence": "fence:1",
                    },
                )

                response = plugin.invoke(commit, peer_id="plugin")

                if mode == "operation-digest":
                    guard = store.current_head_observation_guard()
                    self.assertEqual(response.status, "unavailable")
                    self.assertEqual(store.record_state("record-1"), "unknown")
                    self.assertIsNone(store.receipt(commit))
                    self.assertIsNotNone(guard)
                    self.assertIsNone(guard.binding)
                    self.assert_all_effect_paths_closed(plugin)
                else:
                    self.assertEqual(response.status, "accepted")
                    self.assertEqual(store.record_state("record-1"), "committed")
                    self.assertIsNotNone(store.receipt(commit))
                store.close()

    def test_adapter_mutation_cannot_corrupt_writer_proof_in_normal_or_recovery_paths(self):
        for mode, response_loss in (("writer-proof-before", False), ("writer-proof-after", True)):
            with self.subTest(mode=mode):
                store = EncryptedStateStore(
                    f"file:ticket110-mutable-writer-proof-{mode}?mode=memory&cache=shared",
                    self.key_provider,
                )
                head = synthetic_head(installation_id=f"synthetic-mutable-writer-proof-{mode}")
                writer_vault = self.writer_vault_for(head)
                store.seed_finalized_authority(self.authority_for(head))
                current_head = MutatingPortInputCurrentHead(head, mode)
                current_head.enabled = False
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        current_head,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                try:
                    payload = self.state_payload()
                    self.assertEqual(
                        plugin.invoke(self.command("state.candidate", f"{mode}-candidate", payload), peer_id="plugin").status,
                        "accepted",
                    )
                    self.assertEqual(
                        plugin.invoke(self.command("state.prepare", f"{mode}-prepare", payload), peer_id="plugin").status,
                        "accepted",
                    )
                    commit = self.command(
                        "state.commit",
                        f"{mode}-commit",
                        {
                            "record_id": "record-1",
                            "revision_digest": "sha256:revision-1",
                            "transition_id": "transition-1",
                            "writer_fence": "fence:1",
                        },
                    )
                    current_head.enabled = True
                    if response_loss:
                        head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")

                    first = plugin.invoke(commit, peer_id="plugin")

                    if response_loss:
                        self.assertEqual(first.status, "unknown")
                        self.assertEqual(store.record_state("record-1"), "unknown")
                        head.clear_failure()
                        recovered = plugin.invoke(commit, peer_id="plugin")
                        self.assertEqual(recovered.status, "accepted")
                        self.assertEqual(store.record_state("record-1"), "committed")
                    else:
                        self.assertEqual(first.status, "unavailable")
                        self.assertEqual(first.reason_code, "current-writer-holder-missing")
                        self.assertEqual(store.record_state("record-1"), "prepared")
                        self.assertEqual(head.read().head.generation, 1)
                finally:
                    store.close()

    def test_adapter_mutation_cannot_corrupt_execution_lease_request_or_lookup_identity(self):
        for mode in ("lease-request-before", "lease-request-after"):
            with self.subTest(mode=mode):
                store = EncryptedStateStore(
                    f"file:ticket110-mutable-{mode}?mode=memory&cache=shared",
                    self.key_provider,
                )
                head = synthetic_head(installation_id=f"synthetic-mutable-{mode}")
                writer_vault = self.writer_vault_for(head)
                store.seed_finalized_authority(self.authority_for(head))
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        MutatingPortInputCurrentHead(head, mode),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                try:
                    issued = plugin.invoke(
                        self.command("effect.request", f"{mode}-intent", self.effect_request_payload()),
                        peer_id="plugin",
                    )
                    self.assertEqual(issued.status, "accepted", issued.to_wire())
                    grant = plugin.claim_effect_execution(issued.meta.intent)

                    if mode.endswith("before"):
                        self.assertIsNone(grant)
                        self.assertEqual(store.effect_state(issued.meta["effect_id"]), "claiming")
                        advanced = self.advance_head(
                            head,
                            transition_id=f"transition:{mode}",
                            revision_digest=f"sha256:{mode}",
                        )
                        self.assertEqual(advanced.generation, 2)
                    else:
                        self.assertIsNotNone(grant)
                        self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                        terminal = plugin.invoke(
                            self.command(
                                "effect.result",
                                f"{mode}-result",
                                self.effect_result_payload(issued.meta, grant),
                            ),
                            peer_id="plugin",
                        )
                        self.assertEqual(terminal.status, "accepted")
                finally:
                    store.close()

        for mode in ("lease-identity-before", "lease-identity-after"):
            with self.subTest(mode=mode):
                store = EncryptedStateStore(
                    f"file:ticket110-mutable-{mode}?mode=memory&cache=shared",
                    self.key_provider,
                )
                head = synthetic_head(installation_id=f"synthetic-mutable-{mode}")
                writer_vault = self.writer_vault_for(head)
                store.seed_finalized_authority(self.authority_for(head))
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        MutatingPortInputCurrentHead(LostExecutionLeaseResponseCurrentHead(head), mode),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                try:
                    issued = plugin.invoke(
                        self.command("effect.request", f"{mode}-intent", self.effect_request_payload()),
                        peer_id="plugin",
                    )
                    self.assertEqual(issued.status, "accepted", issued.to_wire())
                    self.assertIsNone(plugin.claim_effect_execution(issued.meta.intent))
                    recovered = plugin.claim_effect_execution(issued.meta.intent)

                    if mode.endswith("before"):
                        self.assertIsNone(recovered)
                        self.assertEqual(store.effect_state(issued.meta["effect_id"]), "claiming")
                        expected = head.read().head.as_authority()
                        with self.assertRaises(HeadConflict):
                            head.conditional_advance(
                                AdvanceRequest(
                                    expected=expected,
                                    transition_id=f"transition:{mode}",
                                    revision_digest=f"sha256:{mode}",
                                    writer_fence=expected.writer_fence,
                                    operation_digest=_TEST_OPERATION_DIGEST,
                                    writer_proof=self.writer_proof_for(head, expected),
                                )
                            )
                    else:
                        self.assertIsNotNone(recovered)
                        self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                finally:
                    store.close()

    def test_adapter_mutation_cannot_terminalize_a_different_effect_release_owner(self):
        for mode in ("lease-release-before", "lease-release-after"):
            with self.subTest(mode=mode):
                store = EncryptedStateStore(
                    f"file:ticket110-mutable-{mode}?mode=memory&cache=shared",
                    self.key_provider,
                )
                head = synthetic_head(installation_id=f"synthetic-mutable-{mode}")
                writer_vault = self.writer_vault_for(head)
                execution_vault = InMemoryExecutionCapabilityVault()
                store.seed_finalized_authority(self.authority_for(head))
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        MutatingPortInputCurrentHead(head, mode),
                        execution_capability_vault=execution_vault,
                        writer_fence_vault=writer_vault,
                    )
                )
                try:
                    issued = plugin.invoke(
                        self.command("effect.request", f"{mode}-intent", self.effect_request_payload()),
                        peer_id="plugin",
                    )
                    self.assertEqual(issued.status, "accepted", issued.to_wire())
                    grant = plugin.claim_effect_execution(issued.meta.intent)
                    self.assertIsNotNone(grant)
                    result_command = self.command(
                        "effect.result",
                        f"{mode}-result",
                        self.effect_result_payload(issued.meta, grant),
                    )
                    result = plugin.invoke(result_command, peer_id="plugin")

                    if mode.endswith("before"):
                        self.assertEqual(result.status, "unavailable")
                        self.assertEqual(result.reason_code, "effect-release-owner-mismatch")
                        self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                        self.assertIsNone(store.receipt(result_command))
                        receipt = head.lookup_execution_lease(
                            ExecutionLeaseIdentity(
                                expected=grant.lease.authority,
                                effect_id=grant.lease.effect_id,
                                intent_digest=grant.lease.intent_digest,
                                writer_fence=grant.lease.authority.writer_fence,
                                holder_id=grant.lease.holder_id,
                            )
                        )
                        self.assertTrue(receipt.released)
                        self.assertEqual(receipt.released_operation_digest, "sha256:adapter-release")
                        self.assert_all_effect_paths_closed(plugin)
                    else:
                        self.assertEqual(result.status, "accepted")
                        self.assertEqual(store.effect_state(issued.meta["effect_id"]), "accepted")
                finally:
                    store.close()

    def test_synthetic_current_head_conditional_advance_allows_exactly_one_concurrent_writer(self):
        head = BlockingConditionalCurrentHead("synthetic-conditional-lock")
        base = head.read().head.as_authority()
        first = AdvanceRequest(
            expected=base,
            transition_id="transition:first",
            revision_digest="sha256:first",
            writer_fence=base.writer_fence,
            operation_digest="sha256:first-operation",
            writer_proof=self.writer_proof_for(head, base),
        )
        second = AdvanceRequest(
            expected=base,
            transition_id="transition:second",
            revision_digest="sha256:second",
            writer_fence=base.writer_fence,
            operation_digest="sha256:second-operation",
            writer_proof=self.writer_proof_for(head, base),
        )
        successes = []
        failures = []

        def advance(request):
            try:
                successes.append((request, head.conditional_advance(request)))
            except BaseException as exc:
                failures.append(exc)

        first_worker = threading.Thread(target=advance, args=(first,))
        second_worker = threading.Thread(target=advance, args=(second,))
        first_worker.start()
        try:
            self.assertTrue(head.first_advance_checked.wait(timeout=1))
            second_worker.start()
        finally:
            head.release_first_advance.set()
            first_worker.join(timeout=2)
            second_worker.join(timeout=2)

        self.assertFalse(first_worker.is_alive())
        self.assertFalse(second_worker.is_alive())
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], HeadConflict)
        self.assertEqual(head.read().head.generation, 2)
        self.assertEqual(successes[0][1].transition_id, head.read().head.transition_id)

    def test_receipt_crash_rolls_back_after_reopening_a_file_store(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "ticket110.sqlite")
            store = CrashBeforeReceiptStore(database, self.key_provider)
            head = synthetic_head(installation_id="synthetic-reopen-crash")
            store.seed_finalized_authority(self.authority_for(head))
            plugin = HealthPlugin(self.core_for(store, head))
            envelope = self.command("state.candidate", "reopen-crash-causal-id", self.state_payload())

            with self.assertRaises(SyntheticCrash):
                plugin.handle_frame(encode_frame(envelope), peer_id="plugin")
            store.close()

            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                self.assertIsNone(reopened.record_state("record-1"))
                recovered = decode_response_frame(
                    HealthPlugin(self.core_for(reopened, head)).handle_frame(
                        encode_frame(envelope),
                        peer_id="plugin",
                    )
                )
                self.assertEqual(recovered.status, "accepted")
                self.assertEqual(reopened.record_state("record-1"), "candidate")
            finally:
                reopened.close()

    def test_effect_terminal_receipt_crash_keeps_the_executing_intent_closed_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "ticket110-effect-receipt-crash.sqlite")
            store = CrashBeforeReceiptStore(database, self.key_provider)
            store.fail_before_receipt = False
            head = synthetic_head(installation_id="synthetic-effect-receipt-crash")
            store.seed_finalized_authority(self.authority_for(head))
            plugin = HealthPlugin(
                self.core_for(store, head, execution_capability_vault=InMemoryExecutionCapabilityVault())
            )
            request = self.command("effect.request", "effect-crash-request", self.effect_request_payload())
            try:
                issued = decode_response_frame(plugin.handle_frame(encode_frame(request), peer_id="plugin"))
                grant = plugin.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                result = self.command(
                    "effect.result",
                    "effect-crash-result",
                    self.effect_result_payload(
                        issued.meta,
                        grant,
                        status="unknown",
                        result_digest="sha256:crash",
                    ),
                )
                store.fail_before_receipt = True

                with self.assertRaises(SyntheticCrash):
                    plugin.handle_frame(encode_frame(result), peer_id="plugin")
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
            finally:
                store.close()

            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                reopened_plugin = HealthPlugin(self.core_for(reopened, head))
                self.assertEqual(reopened.effect_state(issued.meta["effect_id"]), "executing")
                report = reopened_plugin.probe()
                self.assertEqual(report.state, ProbeState.UNKNOWN)
                self.assertEqual(report.reason_code, "effect-result-unknown")
                self.assert_all_effect_paths_closed(reopened_plugin)
                retried = decode_response_frame(reopened_plugin.handle_frame(encode_frame(result), peer_id="plugin"))
                self.assertEqual(retried.status, "unknown")
                self.assertEqual(reopened.effect_state(issued.meta["effect_id"]), "unknown")
                self.assert_all_effect_paths_closed(reopened_plugin)
            finally:
                reopened.close()

    def test_remote_commit_receipt_crash_requires_original_causal_recovery_before_finalize(self):
        store = CrashBeforeReceiptStore("file:ticket110-commit-receipt-crash?mode=memory&cache=shared", self.key_provider)
        self.addCleanup(store.close)
        store.fail_before_receipt = False
        head = synthetic_head(installation_id="synthetic-commit-receipt-crash")
        store.seed_finalized_authority(self.authority_for(head))
        plugin = HealthPlugin(self.core_for(store, head))
        candidate_payload = self.state_payload()

        self.assertEqual(
            decode_response_frame(
                plugin.handle_frame(
                    encode_frame(self.command("state.candidate", "commit-crash-candidate", candidate_payload)),
                    peer_id="plugin",
                )
            ).status,
            "accepted",
        )
        self.assertEqual(
            decode_response_frame(
                plugin.handle_frame(
                    encode_frame(self.command("state.prepare", "commit-crash-prepare", candidate_payload)),
                    peer_id="plugin",
                )
            ).status,
            "accepted",
        )
        commit_payload = {
            "record_id": "record-1",
            "revision_digest": "sha256:revision-1",
            "transition_id": "transition-1",
            "writer_fence": "fence:1",
        }
        commit_envelope = self.command("state.commit", "commit-crash-causal-id", commit_payload)
        store.fail_before_receipt = True

        with self.assertRaises(SyntheticCrash):
            plugin.handle_frame(encode_frame(commit_envelope), peer_id="plugin")

        self.assertEqual(store.record_state("record-1"), "prepared")
        self.assertEqual(head.read().head.generation, 2)

        recovered_plugin = HealthPlugin(self.core_for(store, head))
        finalize_payload = {
            "record_id": "record-1",
            "revision_digest": "sha256:revision-1",
            "transition_id": "transition-1",
            "writer_fence": head.read().head.writer_fence,
        }
        blocked = decode_response_frame(
            recovered_plugin.handle_frame(
                encode_frame(
                    self.command(
                        "state.finalize",
                        "commit-crash-finalize",
                        finalize_payload,
                        generation=2,
                    )
                ),
                peer_id="plugin",
            )
        )
        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "pending-command-owner-required")
        self.assertEqual(store.record_state("record-1"), "prepared")
        recovered = decode_response_frame(
            recovered_plugin.handle_frame(encode_frame(commit_envelope), peer_id="plugin")
        )
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(recovered.meta["generation"], 2)
        self.assertEqual(store.record_state("record-1"), "committed")
        finalized = decode_response_frame(
            recovered_plugin.handle_frame(
                encode_frame(
                    self.command(
                        "state.finalize",
                        "commit-crash-finalize",
                        finalize_payload,
                        generation=2,
                    )
                ),
                peer_id="plugin",
            )
        )
        self.assertEqual(finalized.status, "accepted")
        self.assertEqual(store.record_state("record-1"), "final")
        replay = decode_response_frame(
            recovered_plugin.handle_frame(encode_frame(commit_envelope), peer_id="plugin")
        )
        self.assertEqual(replay.to_wire(), recovered.to_wire())

    def test_commit_persists_the_original_causal_journal_before_remote_cas(self):
        self.establish_prepared()
        checking_head = JournalCheckingCurrentHead(self.head, self.store, "record-1")
        checking_plugin = HealthPlugin(self.core_for(self.store, checking_head))
        commit = self.command("state.commit", "journal-before-cas", self.commit_payload())

        response = decode_response_frame(
            checking_plugin.handle_frame(encode_frame(commit), peer_id="plugin")
        )

        self.assertEqual(response.status, "accepted")
        self.assertIsNotNone(checking_head.pending_at_advance)
        self.assertEqual(checking_head.pending_at_advance.command.to_wire(), commit.to_wire())

    def test_remote_commit_receipt_crash_reserves_the_original_causal_id_against_takeover(self):
        store = CrashBeforeReceiptStore(
            "file:ticket110-commit-causal-reservation?mode=memory&cache=shared",
            self.key_provider,
        )
        self.addCleanup(store.close)
        store.fail_before_receipt = False
        head = synthetic_head(installation_id="synthetic-commit-causal-reservation")
        store.seed_finalized_authority(self.authority_for(head))
        plugin = HealthPlugin(self.core_for(store, head))
        candidate_payload = self.state_payload()

        self.assertEqual(
            decode_response_frame(
                plugin.handle_frame(
                    encode_frame(self.command("state.candidate", "reservation-candidate", candidate_payload)),
                    peer_id="plugin",
                )
            ).status,
            "accepted",
        )
        self.assertEqual(
            decode_response_frame(
                plugin.handle_frame(
                    encode_frame(self.command("state.prepare", "reservation-prepare", candidate_payload)),
                    peer_id="plugin",
                )
            ).status,
            "accepted",
        )
        original = self.command("state.commit", "reservation-original", self.commit_payload())
        store.fail_before_receipt = True

        with self.assertRaises(SyntheticCrash):
            plugin.handle_frame(encode_frame(original), peer_id="plugin")

        self.assertEqual(store.record_state("record-1"), "prepared")
        self.assertEqual(head.read().head.generation, 2)
        takeover = self.command("state.commit", "reservation-takeover", self.commit_payload())
        rejected = decode_response_frame(
            HealthPlugin(self.core_for(store, head)).handle_frame(
                encode_frame(takeover),
                peer_id="plugin",
            )
        )
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.reason_code, "causal-id-conflict")
        self.assertEqual(store.record_state("record-1"), "prepared")

        recovered = decode_response_frame(
            HealthPlugin(self.core_for(store, head)).handle_frame(
                encode_frame(original),
                peer_id="plugin",
            )
        )
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(recovered.meta["generation"], 2)
        self.assertEqual(store.record_state("record-1"), "committed")

    def test_pre_cas_journal_survives_reopen_before_remote_commit_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "ticket110-pre-cas-journal.sqlite")
            store = CrashBeforeReceiptStore(database, self.key_provider)
            head = synthetic_head(installation_id="synthetic-pre-cas-journal")
            store.fail_before_receipt = False
            store.seed_finalized_authority(self.authority_for(head))
            plugin = HealthPlugin(self.core_for(store, head))
            candidate_payload = self.state_payload()
            self.assertEqual(
                decode_response_frame(
                    plugin.handle_frame(
                        encode_frame(self.command("state.candidate", "journal-file-candidate", candidate_payload)),
                        peer_id="plugin",
                    )
                ).status,
                "accepted",
            )
            self.assertEqual(
                decode_response_frame(
                    plugin.handle_frame(
                        encode_frame(self.command("state.prepare", "journal-file-prepare", candidate_payload)),
                        peer_id="plugin",
                    )
                ).status,
                "accepted",
            )
            original = self.command("state.commit", "journal-file-original", self.commit_payload())
            store.fail_before_receipt = True

            with self.assertRaises(SyntheticCrash):
                plugin.handle_frame(encode_frame(original), peer_id="plugin")
            self.assertEqual(head.read().head.generation, 2)
            store.close()

            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                pending = reopened.pending_for_record("record-1")
                self.assertIsNotNone(pending)
                self.assertEqual(pending.command.to_wire(), original.to_wire())
                recovered_plugin = HealthPlugin(self.core_for(reopened, head))
                takeover = self.command("state.commit", "journal-file-takeover", self.commit_payload())
                rejected = decode_response_frame(
                    recovered_plugin.handle_frame(encode_frame(takeover), peer_id="plugin")
                )
                self.assertEqual(rejected.status, "rejected")
                self.assertEqual(rejected.reason_code, "causal-id-conflict")
                finalize = {
                    "record_id": "record-1",
                    "revision_digest": "sha256:revision-1",
                    "transition_id": "transition-1",
                    "writer_fence": head.read().head.writer_fence,
                }
                blocked = decode_response_frame(
                    recovered_plugin.handle_frame(
                        encode_frame(
                            self.command(
                                "state.finalize",
                                "journal-file-takeover-finalize",
                                finalize,
                                generation=2,
                            )
                        ),
                        peer_id="plugin",
                    )
                )
                self.assertEqual(blocked.status, "unavailable")
                self.assertEqual(blocked.reason_code, "pending-command-owner-required")
                self.assertEqual(reopened.record_state("record-1"), "prepared")
                self.assertEqual(reopened.pending_for_record("record-1").command.to_wire(), original.to_wire())

                recovered = decode_response_frame(
                    recovered_plugin.handle_frame(encode_frame(original), peer_id="plugin")
                )
                self.assertEqual(recovered.status, "accepted")
                self.assertEqual(recovered.meta["generation"], 2)
                self.assertEqual(
                    decode_response_frame(
                        recovered_plugin.handle_frame(
                            encode_frame(
                                self.command("state.finalize", "journal-file-finalize", finalize, generation=2)
                            ),
                            peer_id="plugin",
                        )
                    ).status,
                    "accepted",
                )
                self.assertEqual(recovered_plugin.probe().state, ProbeState.HEALTHY)
            finally:
                reopened.close()

    def test_lookup_conflict_is_not_transition_not_found_and_does_not_retry_cas(self):
        self.establish_prepared()
        original = self.command("state.commit", "lookup-conflict-original", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN, operation="advance")
        self.assertEqual(self.send(original).status, "unknown")
        self.assertEqual(self.head.read().head.generation, 1)

        self.head.clear_failure()
        self.head.set_failure(FailureMode.CONFLICT, operation="lookup")
        blocked = self.send(original)

        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "current-head-lookup-conflict")
        self.assertEqual(self.head.read().head.generation, 1)
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assert_all_effect_paths_closed(self.plugin)

        self.head.clear_failure()
        recovered = self.send(original)
        self.assertEqual(recovered.status, "unavailable")
        self.assertEqual(recovered.reason_code, "current-head-observation-incomplete")
        self.assertEqual(self.head.read().head.generation, 1)

    def test_terminal_during_transition_lookup_returns_a_fail_closed_response(self):
        self.establish_prepared()
        original = self.command("state.commit", "lookup-terminal-original", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN, operation="advance")
        self.assertEqual(self.send(original).status, "unknown")
        self.head.clear_failure()
        terminal_plugin = HealthPlugin(self.core_for(self.store, TerminalLookupCurrentHead(self.head)))

        response = decode_response_frame(
            terminal_plugin.handle_frame(encode_frame(original), peer_id="plugin")
        )

        self.assertEqual(response.status, "unavailable")
        self.assertEqual(response.reason_code, "current-head-terminal")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assert_all_effect_paths_closed(terminal_plugin)

    def test_terminal_during_current_head_read_returns_a_fail_closed_response(self):
        terminal_plugin = HealthPlugin(self.core_for(self.store, TerminalReadCurrentHead()))

        response = decode_response_frame(
            terminal_plugin.handle_frame(
                encode_frame(self.command("state.candidate", "read-terminal", self.state_payload())),
                peer_id="plugin",
            )
        )

        self.assertEqual(response.status, "unavailable")
        self.assertEqual(response.reason_code, "current-head-terminal")
        self.assertEqual(self.store.count_records(), 0)
        self.assert_all_effect_paths_closed(terminal_plugin)

    def test_probe_waits_for_the_atomic_final_record_and_receipt_commit(self):
        store = BlockingReceiptStore("file:ticket110-probe-atomic?mode=memory&cache=shared", self.key_provider)
        self.addCleanup(store.close)
        head = synthetic_head(installation_id="synthetic-probe-atomic")
        store.seed_finalized_authority(self.authority_for(head))
        plugin = HealthPlugin(self.core_for(store, head))
        payload = self.state_payload()
        for action, causal_id in (
            ("state.candidate", "probe-atomic-candidate"),
            ("state.prepare", "probe-atomic-prepare"),
        ):
            self.assertEqual(
                decode_response_frame(
                    plugin.handle_frame(
                        encode_frame(self.command(action, causal_id, payload)),
                        peer_id="plugin",
                    )
                ).status,
                "accepted",
            )
        commit = {
            "record_id": "record-1",
            "revision_digest": "sha256:revision-1",
            "transition_id": "transition-1",
            "writer_fence": head.read().head.writer_fence,
        }
        self.assertEqual(
            decode_response_frame(
                plugin.handle_frame(
                    encode_frame(self.command("state.commit", "probe-atomic-commit", commit)),
                    peer_id="plugin",
                )
            ).status,
            "accepted",
        )
        finalize = dict(commit)
        finalize["writer_fence"] = head.read().head.writer_fence
        store.block_before_receipt = True
        final_responses = []
        probe_reports = []
        failures = []
        probe_finished = threading.Event()

        def finalize_in_background():
            try:
                final_responses.append(
                    decode_response_frame(
                        plugin.handle_frame(
                            encode_frame(
                                self.command("state.finalize", "probe-atomic-finalize", finalize, generation=2)
                            ),
                            peer_id="plugin",
                        )
                    )
                )
            except BaseException as exc:
                failures.append(exc)

        def probe_in_background():
            try:
                probe_reports.append(plugin.probe())
            except BaseException as exc:
                failures.append(exc)
            finally:
                probe_finished.set()

        finalizer = threading.Thread(target=finalize_in_background)
        prober = threading.Thread(target=probe_in_background)
        finalizer.start()
        try:
            self.assertTrue(store.receipt_started.wait(timeout=1))
            prober.start()
            self.assertFalse(probe_finished.wait(timeout=0.1))
        finally:
            store.release_receipt.set()
            finalizer.join(timeout=2)
            prober.join(timeout=2)

        self.assertFalse(finalizer.is_alive())
        self.assertFalse(prober.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(final_responses[0].status, "accepted")
        self.assertEqual(probe_reports[0].state, ProbeState.HEALTHY)

    def test_cross_process_stale_preflight_cannot_leave_an_orphan_commit_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "ticket110-cross-process-journal.sqlite")
            store_a = BlockingJournalStore(database, self.key_provider)
            store_b = EncryptedStateStore(database, self.key_provider)
            head = synthetic_head(installation_id="synthetic-cross-process-journal")
            store_a.seed_finalized_authority(self.authority_for(head))
            plugin_a = HealthPlugin(self.core_for(store_a, head))
            plugin_b = HealthPlugin(self.core_for(store_b, head))
            payload = self.state_payload()
            try:
                self.assertEqual(
                    decode_response_frame(
                        plugin_b.handle_frame(
                            encode_frame(self.command("state.candidate", "cross-candidate", payload)),
                            peer_id="plugin",
                        )
                    ).status,
                    "accepted",
                )
                self.assertEqual(
                    decode_response_frame(
                        plugin_b.handle_frame(
                            encode_frame(self.command("state.prepare", "cross-prepare", payload)),
                            peer_id="plugin",
                        )
                    ).status,
                    "accepted",
                )
                commit = {
                    "record_id": "record-1",
                    "revision_digest": "sha256:revision-1",
                    "transition_id": "transition-1",
                    "writer_fence": "fence:1",
                }
                original = self.command("state.commit", "cross-original", commit)
                responses = []
                failures = []

                def invoke_a():
                    try:
                        responses.append(
                            decode_response_frame(
                                plugin_a.handle_frame(encode_frame(original), peer_id="plugin")
                            )
                        )
                    except BaseException as exc:
                        failures.append(exc)

                worker = threading.Thread(target=invoke_a)
                worker.start()
                try:
                    self.assertTrue(store_a.journal_started.wait(timeout=1))
                    takeover = self.command("state.commit", "cross-takeover", commit)
                    self.assertEqual(
                        decode_response_frame(
                            plugin_b.handle_frame(encode_frame(takeover), peer_id="plugin")
                        ).status,
                        "accepted",
                    )
                    finalize = dict(commit)
                    finalize["writer_fence"] = head.read().head.writer_fence
                    self.assertEqual(
                        decode_response_frame(
                            plugin_b.handle_frame(
                                encode_frame(
                                    self.command("state.finalize", "cross-finalize", finalize, generation=2)
                                ),
                                peer_id="plugin",
                            )
                        ).status,
                        "accepted",
                    )
                finally:
                    store_a.release_journal.set()
                    worker.join(timeout=2)

                self.assertFalse(worker.is_alive())
                self.assertEqual(failures, [])
                self.assertEqual(responses[0].status, "rejected")
                self.assertIsNone(store_b.pending_for_record("record-1"))
                self.assertEqual(store_b.record_state("record-1"), "final")
                self.assertEqual(plugin_b.probe().state, ProbeState.HEALTHY)
            finally:
                store_b.close()
                store_a.close()

    def test_replay_preserves_effect_intent_and_commit_metadata(self):
        request = self.command("effect.request", "replay-effect", self.effect_request_payload())
        first_intent = self.send(request)
        replayed_intent = self.send(request)
        self.assertEqual(replayed_intent.to_wire(), first_intent.to_wire())
        grant = self.plugin.claim_effect_execution(first_intent.meta.intent)
        self.assertIsNotNone(grant)
        self.assertEqual(
            self.send(
                self.command(
                    "effect.result",
                    "replay-effect-result",
                    self.effect_result_payload(first_intent.meta, grant),
                )
            ).status,
            "accepted",
        )

        self.establish_prepared()
        commit = self.command("state.commit", "replay-commit", self.commit_payload())
        first_commit = self.send(commit)
        replayed_commit = self.send(commit)
        self.assertEqual(replayed_commit.to_wire(), first_commit.to_wire())
        self.assertEqual(replayed_commit.meta["generation"], 2)
        self.assertEqual(replayed_commit.meta["writer_fence"], "fence:1")

    def test_transient_current_head_read_timeout_recovers_without_recreating_core(self):
        self.head.set_failure(FailureMode.TIMEOUT, operation="read")

        unavailable = self.send(self.command("state.candidate", "temporary-timeout", self.state_payload()))

        self.assertEqual(unavailable.status, "unavailable")
        self.head.clear_failure()
        self.assertEqual(self.plugin.probe().state, ProbeState.HEALTHY)
        self.assertTrue(self.plugin.health_writes_allowed())
        self.assertTrue(self.plugin.model_effects_allowed())
        self.assertTrue(self.plugin.outbound_effects_allowed())

    def test_protocol_rejects_invalid_opaque_field_types_and_empty_digests(self):
        candidate = self.command("state.candidate", "invalid-fields", self.state_payload()).to_wire()
        cases = (
            ("record_id", True),
            ("revision_digest", 7),
            ("transition_id", False),
            ("payload_digest", ""),
        )

        for field, value in cases:
            with self.subTest(field=field):
                malformed = self.command("state.candidate", f"invalid-{field}", self.state_payload()).to_wire()
                malformed["payload"][field] = value
                response = self.send_raw(malformed)
                self.assertEqual(response.status, "rejected")

        self.assertEqual(self.store.count_records(), 0)
        self.assertEqual(candidate["payload"]["record_id"], "record-1")

    def test_public_authority_and_protocol_constructors_reject_subclass_shortcuts(self):
        class AuthoritySubclass(AuthoritySnapshot):
            pass

        class HeadSubclass(HeadSnapshot):
            pass

        class CandidateSubclass(StateCandidatePayload):
            pass

        class RequestSubclass(AdvanceRequest):
            pass

        class DictSubclass(dict):
            pass

        class ListSubclass(list):
            pass

        authority = self.authority_for(self.head)
        subclassed_authority = AuthoritySubclass(
            installation_id=authority.installation_id,
            generation=authority.generation,
            revision_digest=authority.revision_digest,
            transition_id=authority.transition_id,
            writer_fence=authority.writer_fence,
            terminal=authority.terminal,
            site=authority.site,
        )
        subclassed_head = HeadSubclass(
            installation_id=authority.installation_id,
            generation=authority.generation,
            revision_digest=authority.revision_digest,
            transition_id=authority.transition_id,
            writer_fence=authority.writer_fence,
            terminal=authority.terminal,
            site=authority.site,
        )

        with self.assertRaises(AuthorityValidationError):
            WriterFenceProof(subclassed_authority, _TEST_WRITER_CAPABILITY)
        with self.assertRaises(AuthorityValidationError):
            AdvanceIdentity(
                expected=subclassed_authority,
                transition_id="transition:subclass",
                revision_digest="sha256:subclass",
                writer_fence=authority.writer_fence,
                operation_digest=_TEST_OPERATION_DIGEST,
            )
        with self.assertRaises(AuthorityValidationError):
            HeadRead(subclassed_head)
        request_subclass = RequestSubclass(
            expected=authority,
            transition_id="transition:subclass-request",
            revision_digest="sha256:subclass-request",
            writer_fence=authority.writer_fence,
            operation_digest=_TEST_OPERATION_DIGEST,
            writer_proof=WriterFenceProof(authority, _TEST_WRITER_CAPABILITY),
        )
        with self.assertRaises(AuthorityValidationError):
            self.head.conditional_advance(request_subclass)
        self.assertEqual(self.head.read().head.generation, 1)
        with self.assertRaises(ProtocolViolation):
            CommandEnvelope(
                peer=PretendPluginPeer(),
                action="state.candidate",
                source="synthetic",
                causal_id="subclass-peer",
                generation=1,
                scope=("state:candidate",),
                payload=self.state_payload("subclass-peer"),
            )
        with self.assertRaises(ProtocolViolation):
            CommandEnvelope(
                peer="plugin",
                action="state.candidate",
                source="synthetic",
                causal_id="subclass-payload",
                generation=1,
                scope=("state:candidate",),
                payload=CandidateSubclass(**self.state_payload("subclass-payload")),
            )
        with self.assertRaises(ProtocolViolation):
            CommandEnvelope.from_wire(DictSubclass(self.command(
                "state.candidate",
                "subclass-dict",
                self.state_payload("subclass-dict"),
            ).to_wire()))
        list_subclass_wire = self.command(
            "state.candidate",
            "subclass-list",
            self.state_payload("subclass-list"),
        ).to_wire()
        list_subclass_wire["scope"] = ListSubclass(["state:candidate"])
        with self.assertRaises(ProtocolViolation):
            CommandEnvelope.from_wire(list_subclass_wire)

        intent = EffectIntent(
            effect_id="effect:nested-authority",
            effect_kind="model-work",
            intent_digest="sha256:nested-authority",
            authority=authority,
        )
        with self.assertRaises(ProtocolViolation):
            EffectIntentMeta(
                ForgedEffectIntent(
                    effect_id=intent.effect_id,
                    effect_kind=intent.effect_kind,
                    intent_digest=intent.intent_digest,
                    authority=intent.authority,
                )
            )
        wire = Response(
            "accepted",
            "nested-authority-meta",
            "effect-intent-issued",
            EffectIntentMeta(intent),
        ).to_wire()

        self.assertEqual(
            wire["meta"],
            {
                "effect_id": intent.effect_id,
                "effect_kind": intent.effect_kind,
                "intent_digest": intent.intent_digest,
                "authority": authority.to_storage(),
            },
        )
        self.assertEqual(Response.from_wire(wire).meta.intent, intent)

    def test_response_protocol_rejects_unhashable_status_values(self):
        for status in ([], {}):
            with self.subTest(status_type=type(status).__name__):
                with self.assertRaises(ProtocolViolation):
                    decode_response_frame(
                        encode_raw_frame(
                            {
                                "protocol_version": 1,
                                "status": status,
                                "causal_id": None,
                                "reason_code": None,
                                "meta": {},
                            }
                        )
                    )

    def test_typed_authority_values_and_storage_reject_split_or_malformed_authority(self):
        authority = self.authority_for(self.head)
        target = RevisionTarget(
            record_id="record-typed",
            revision_digest="sha256:typed-revision",
            transition_id="transition-typed",
            payload_digest="sha256:typed-payload",
        )
        with self.assertRaises(AuthorityValidationError):
            PreparedTransition(target=object(), base=authority)
        with self.assertRaises(AuthorityValidationError):
            CommittedTransition(prepared=object(), committed=authority)
        with self.assertRaises(AuthorityValidationError):
            EffectIntent(
                effect_id="effect:typed",
                effect_kind="model-work",
                intent_digest="sha256:typed-intent",
                authority=object(),
            )
        with self.assertRaises(AuthorityValidationError):
            TerminalEffect(execution=object(), status="accepted", result_digest="sha256:typed-result")
        with self.assertRaises(AuthorityValidationError):
            AdvanceRequest(
                expected=object(),
                transition_id=target.transition_id,
                revision_digest=target.revision_digest,
                writer_fence=authority.writer_fence,
                operation_digest=_TEST_OPERATION_DIGEST,
                writer_proof=self.writer_proof_for(self.head, authority),
            )
        with self.assertRaises(AuthorityValidationError):
            AppliedTransition(request=object(), applied=self.head.read().head)

        prepared = PreparedTransition(target=target, base=authority)
        committed_authority = AuthoritySnapshot(
            installation_id=authority.installation_id,
            generation=authority.generation + 1,
            revision_digest=target.revision_digest,
            transition_id=target.transition_id,
            writer_fence=authority.writer_fence,
            terminal=False,
            site=authority.site,
        )
        committed = CommittedTransition(prepared=prepared, committed=committed_authority)
        intent = EffectIntent(
            effect_id="effect:typed",
            effect_kind="model-work",
            intent_digest="sha256:typed-intent",
            authority=authority,
        )
        with self.assertRaises(AuthorityValidationError):
            self.store.write_record(
                "record-other",
                "prepared",
                target.revision_digest,
                target.transition_id,
                prepared,
            )
        with self.assertRaises(AuthorityValidationError):
            self.store.write_finalized_record(
                target.record_id,
                target.revision_digest,
                target.transition_id,
                committed,
                replace(committed_authority, writer_fence="fence:other"),
            )
        with self.assertRaises(AuthorityValidationError):
            self.store.write_effect("effect:other", "intent", intent)

    def test_transition_receipt_cannot_substitute_a_rotated_writer_fence(self):
        authority = self.authority_for(self.head)
        request = AdvanceIdentity(
            expected=authority,
            transition_id="transition:receipt-fence",
            revision_digest="sha256:receipt-fence",
            writer_fence=authority.writer_fence,
            operation_digest=_TEST_OPERATION_DIGEST,
        )
        forged_applied = replace(
            self.head.read().head,
            generation=authority.generation + 1,
            revision_digest=request.revision_digest,
            transition_id=request.transition_id,
            writer_fence="fence:forged",
        )

        with self.assertRaises(AuthorityValidationError):
            AppliedTransition(request=request, applied=forged_applied)

    def test_committed_transition_cannot_replace_the_prepared_writer_fence(self):
        base = self.authority_for(self.head)
        target = RevisionTarget(
            record_id="record:committed-fence",
            revision_digest="sha256:committed-fence",
            transition_id="transition:committed-fence",
            payload_digest="sha256:committed-fence-payload",
        )
        prepared = PreparedTransition(target=target, base=base)
        forged_authority = AuthoritySnapshot(
            installation_id=base.installation_id,
            generation=base.generation + 1,
            revision_digest=target.revision_digest,
            transition_id=target.transition_id,
            writer_fence="fence:replacement",
            terminal=False,
            site=base.site,
        )

        with self.assertRaises(AuthorityValidationError):
            CommittedTransition(prepared=prepared, committed=forged_authority)

        forged = object.__new__(CommittedTransition)
        object.__setattr__(forged, "prepared", prepared)
        object.__setattr__(forged, "committed", forged_authority)
        with self.assertRaises(AuthorityValidationError):
            self.store.write_record(
                target.record_id,
                "committed",
                target.revision_digest,
                target.transition_id,
                forged,
            )
        self.assertIsNone(self.store.record_state(target.record_id))

    def test_ticket110_rejects_delivery_effects_until_they_have_outbox_and_approval_binding(self):
        response = self.send(
            self.command(
                "effect.request",
                "contact-delivery-without-outbox",
                self.effect_request_payload(effect_kind="contact-delivery"),
            )
        )

        self.assertEqual(response.status, "rejected")
        self.assertEqual(response.reason_code, "contact-delivery-not-supported-in-ticket-110")
        self.assertEqual(self.store.count_effects(), 0)

    def test_ticket110_rejects_contact_delivery_intents_at_all_effect_boundaries(self):
        authority = self.authority_for(self.head)
        with self.assertRaises(AuthorityValidationError):
            EffectIntent(
                effect_id="effect:contact-delivery-direct",
                effect_kind="contact-delivery",
                intent_digest="sha256:contact-delivery-direct",
                authority=authority,
            )

        mutated = EffectIntent(
            effect_id="effect:contact-delivery-mutated",
            effect_kind="model-work",
            intent_digest="sha256:contact-delivery-mutated",
            authority=authority,
        )
        object.__setattr__(mutated, "effect_kind", "contact-delivery")

        with self.assertRaises(AuthorityValidationError):
            self.store.write_effect(mutated.effect_id, "intent", mutated)
        self.assertIsNone(self.plugin.claim_effect_execution(mutated))
        self.assertIsNone(self.store.effect(mutated.effect_id))

    def test_execution_capability_prevents_a_second_store_from_claiming_or_completing_an_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            head = synthetic_head(installation_id="synthetic-effect-holder")
            store_a = EncryptedStateStore(str(Path(directory) / "a.sqlite"), self.key_provider)
            store_b = EncryptedStateStore(str(Path(directory) / "b.sqlite"), self.key_provider)
            try:
                authority = self.authority_for(head)
                store_a.seed_finalized_authority(authority)
                store_b.seed_finalized_authority(authority)
                plugin_a = HealthPlugin(
                    self.core_for(store_a, head, execution_capability_vault=InMemoryExecutionCapabilityVault())
                )
                plugin_b = HealthPlugin(
                    self.core_for(store_b, head, execution_capability_vault=InMemoryExecutionCapabilityVault())
                )
                request = self.command("effect.request", "shared-effect-holder", self.effect_request_payload())
                issued_a = decode_response_frame(plugin_a.handle_frame(encode_frame(request), peer_id="plugin"))
                issued_b = decode_response_frame(plugin_b.handle_frame(encode_frame(request), peer_id="plugin"))
                self.assertEqual(issued_a.meta.to_wire(), issued_b.meta.to_wire())

                grant_a = plugin_a.claim_effect_execution(issued_a.meta.intent)
                grant_b = plugin_b.claim_effect_execution(issued_b.meta.intent)

                self.assertIsNotNone(grant_a)
                self.assertIsNone(grant_b)
                self.assertEqual(store_a.effect_state(issued_a.meta["effect_id"]), "executing")
                self.assertEqual(store_b.effect_state(issued_b.meta["effect_id"]), "claiming")
                forged = decode_response_frame(
                    plugin_a.handle_frame(
                        encode_frame(
                            self.command(
                                "effect.result",
                                "untrusted-effect-result",
                                self.effect_result_payload(issued_a.meta),
                            )
                        ),
                        peer_id="plugin",
                    )
                )
                self.assertEqual(forged.status, "rejected")
                self.assertEqual(forged.reason_code, "effect-execution-capability-required")
                expected = head.read().head.as_authority()
                with self.assertRaises(HeadConflict):
                    head.conditional_advance(
                        AdvanceRequest(
                            expected=expected,
                            transition_id="transition:blocked-by-holder",
                            revision_digest="sha256:blocked-by-holder",
                            writer_fence=expected.writer_fence,
                            operation_digest=_TEST_OPERATION_DIGEST,
                            writer_proof=self.writer_proof_for(head, expected),
                        )
                    )
                self.assert_all_effect_paths_closed(plugin_a)
                self.assert_all_effect_paths_closed(plugin_b)
            finally:
                store_b.close()
                store_a.close()

    def test_effect_execution_requires_an_explicit_host_bound_vault(self):
        store = EncryptedStateStore("file:ticket110-no-effect-vault?mode=memory&cache=shared", self.key_provider)
        self.addCleanup(store.close)
        head = synthetic_head(installation_id="synthetic-no-effect-vault")
        store.seed_finalized_authority(self.authority_for(head))
        plugin = HealthPlugin(self.core_for(store, head))

        self.assertEqual(plugin.probe().state, ProbeState.HEALTHY)
        self.assertFalse(plugin.model_effects_allowed())
        self.assertFalse(plugin.outbound_effects_allowed())
        issued = decode_response_frame(
            plugin.handle_frame(
                encode_frame(self.command("effect.request", "no-effect-vault", self.effect_request_payload())),
                peer_id="plugin",
            )
        )

        self.assertEqual(issued.status, "accepted")
        self.assertIsNone(plugin.claim_effect_execution(issued.meta.intent))
        self.assertEqual(store.effect_state(issued.meta["effect_id"]), "intent")
        self.assert_all_effect_paths_closed(plugin)

    def test_shared_vault_namespaces_claiming_capabilities_by_full_installation_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            shared_vault = InMemoryExecutionCapabilityVault()
            head_a = synthetic_head(installation_id="synthetic-vault-installation-a")
            head_b = synthetic_head(installation_id="synthetic-vault-installation-b")
            store_a = EncryptedStateStore(str(Path(directory) / "a.sqlite"), self.key_provider)
            store_b = EncryptedStateStore(str(Path(directory) / "b.sqlite"), self.key_provider)
            try:
                store_a.seed_finalized_authority(self.authority_for(head_a))
                store_b.seed_finalized_authority(self.authority_for(head_b))
                plugin_a = HealthPlugin(
                    self.core_for(
                        store_a,
                        LostExecutionLeaseResponseCurrentHead(head_a),
                        execution_capability_vault=shared_vault,
                    )
                )
                plugin_b = HealthPlugin(
                    self.core_for(store_b, head_b, execution_capability_vault=shared_vault)
                )
                request = self.command("effect.request", "same-causal-different-installations", self.effect_request_payload())
                issued_a = decode_response_frame(plugin_a.handle_frame(encode_frame(request), peer_id="plugin"))
                issued_b = decode_response_frame(plugin_b.handle_frame(encode_frame(request), peer_id="plugin"))

                self.assertIsNone(plugin_a.claim_effect_execution(issued_a.meta.intent))
                self.assertIsNotNone(plugin_b.claim_effect_execution(issued_b.meta.intent))
                recovered_a = plugin_a.claim_effect_execution(issued_a.meta.intent)

                self.assertIsNotNone(recovered_a)
                self.assertEqual(store_a.effect_state(issued_a.meta["effect_id"]), "executing")
                self.assertEqual(store_b.effect_state(issued_b.meta["effect_id"]), "executing")
            finally:
                store_b.close()
                store_a.close()

    def test_shared_vault_does_not_let_a_cloned_claiming_store_receive_the_same_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            shared_vault = InMemoryExecutionCapabilityVault()
            head = synthetic_head(installation_id="synthetic-vault-clone")
            store_a = EncryptedStateStore(str(Path(directory) / "a.sqlite"), self.key_provider)
            store_b = EncryptedStateStore(str(Path(directory) / "b.sqlite"), self.key_provider)
            try:
                authority = self.authority_for(head)
                store_a.seed_finalized_authority(authority)
                store_b.seed_finalized_authority(authority)
                plugin_a = HealthPlugin(
                    self.core_for(
                        store_a,
                        LostExecutionLeaseResponseCurrentHead(head),
                        execution_capability_vault=shared_vault,
                    )
                )
                plugin_b = HealthPlugin(
                    self.core_for(store_b, head, execution_capability_vault=shared_vault)
                )
                request = self.command("effect.request", "shared-vault-clone", self.effect_request_payload())
                issued_a = decode_response_frame(plugin_a.handle_frame(encode_frame(request), peer_id="plugin"))
                issued_b = decode_response_frame(plugin_b.handle_frame(encode_frame(request), peer_id="plugin"))

                self.assertIsNone(plugin_a.claim_effect_execution(issued_a.meta.intent))
                cloned_claim = store_a.effect(issued_a.meta["effect_id"])
                self.assertIsNotNone(cloned_claim)
                self.assertEqual(cloned_claim.state, "claiming")
                store_b.write_effect(issued_b.meta["effect_id"], "claiming", cloned_claim.payload)
                second_grant = plugin_b.claim_effect_execution(issued_b.meta.intent)
                first_grant = plugin_a.claim_effect_execution(issued_a.meta.intent)

                self.assertIsNone(second_grant)
                self.assertIsNotNone(first_grant)
                self.assertEqual(store_a.effect_state(issued_a.meta["effect_id"]), "executing")
                self.assertEqual(store_b.effect_state(issued_b.meta["effect_id"]), "claiming")
            finally:
                store_b.close()
                store_a.close()

    def test_forged_execution_lease_acquire_response_requires_remote_readback(self):
        issued = self.send(
            self.command("effect.request", "forged-acquire-effect", self.effect_request_payload())
        )
        plugin = HealthPlugin(
            self.core_for(
                self.store,
                ForgedAcquireCurrentHead(self.head),
                execution_capability_vault=self.execution_vault,
            )
        )

        grant = plugin.claim_effect_execution(issued.meta.intent)

        self.assertIsNone(grant)
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "claiming")
        expected = self.head.read().head.as_authority()
        advanced = self.head.conditional_advance(
            AdvanceRequest(
                expected=expected,
                transition_id="transition:no-forged-lease",
                revision_digest="sha256:no-forged-lease",
                writer_fence=expected.writer_fence,
                operation_digest=_TEST_OPERATION_DIGEST,
                writer_proof=self.writer_proof_for(self.head, expected),
            )
        )
        self.assertEqual(advanced.generation, 2)
        self.assert_all_effect_paths_closed(plugin)

    def test_forged_execution_lease_release_response_requires_remote_readback(self):
        issued = self.send(
            self.command("effect.request", "forged-release-effect", self.effect_request_payload())
        )
        plugin = HealthPlugin(
            self.core_for(
                self.store,
                ForgedReleaseCurrentHead(self.head),
                execution_capability_vault=self.execution_vault,
            )
        )
        grant = plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)

        result = decode_response_frame(
            plugin.handle_frame(
                encode_frame(
                    self.command(
                        "effect.result",
                        "forged-release-result",
                        self.effect_result_payload(issued.meta, grant),
                    )
                ),
                peer_id="plugin",
            )
        )

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "executing")
        expected = self.head.read().head.as_authority()
        with self.assertRaises(HeadConflict):
            self.head.conditional_advance(
                AdvanceRequest(
                    expected=expected,
                    transition_id="transition:still-held-after-forged-release",
                    revision_digest="sha256:still-held-after-forged-release",
                    writer_fence=expected.writer_fence,
                    operation_digest=_TEST_OPERATION_DIGEST,
                    writer_proof=self.writer_proof_for(self.head, expected),
                )
            )
        self.assert_all_effect_paths_closed(plugin)

    def test_lost_effect_release_response_recovers_after_another_writer_advances(self):
        issued = self.send(
            self.command("effect.request", "lost-release-effect", self.effect_request_payload())
        )
        plugin = HealthPlugin(
            self.core_for(
                self.store,
                LostReleaseResponseCurrentHead(self.head),
                execution_capability_vault=self.execution_vault,
            )
        )
        grant = plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        result_command = self.command(
            "effect.result",
            "lost-release-terminal",
            self.effect_result_payload(issued.meta, grant),
        )

        first = decode_response_frame(plugin.handle_frame(encode_frame(result_command), peer_id="plugin"))
        self.assertEqual(first.status, "unknown")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "executing")
        self.advance_head(
            self.head,
            transition_id="transition:after-lost-release",
            revision_digest="sha256:after-lost-release",
        )

        recovered = decode_response_frame(plugin.handle_frame(encode_frame(result_command), peer_id="plugin"))
        replayed = decode_response_frame(plugin.handle_frame(encode_frame(result_command), peer_id="plugin"))

        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(replayed.to_wire(), recovered.to_wire())
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "accepted")
        self.assert_all_effect_paths_closed(plugin)

    def test_lost_effect_release_reserves_its_original_causal_id_against_takeover(self):
        issued = self.send(
            self.command("effect.request", "lost-release-owner", self.effect_request_payload())
        )
        plugin = HealthPlugin(
            self.core_for(
                self.store,
                LostReleaseResponseCurrentHead(self.head),
                execution_capability_vault=self.execution_vault,
            )
        )
        grant = plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        original = self.command(
            "effect.result",
            "lost-release-owner-original",
            self.effect_result_payload(issued.meta, grant),
        )

        first = decode_response_frame(plugin.handle_frame(encode_frame(original), peer_id="plugin"))
        takeover = decode_response_frame(
            plugin.handle_frame(
                encode_frame(
                    self.command(
                        "effect.result",
                        "lost-release-owner-takeover",
                        self.effect_result_payload(issued.meta, grant),
                    )
                ),
                peer_id="plugin",
            )
        )
        recovered = decode_response_frame(plugin.handle_frame(encode_frame(original), peer_id="plugin"))

        self.assertEqual(first.status, "unknown")
        self.assertEqual(first.reason_code, "effect-lease-unknown")
        self.assertEqual(takeover.status, "rejected")
        self.assertEqual(takeover.reason_code, "causal-id-conflict")
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "accepted")

    def test_faulty_effect_recovery_lookup_consumes_the_exact_binding(self):
        for mode, expected_reason in (
            ("malformed", "effect-lease-malformed"),
            ("unclassified", "effect-lease-lookup-unclassified"),
        ):
            with self.subTest(mode=mode):
                store = EncryptedStateStore(
                    f"file:ticket110-effect-recovery-{mode}?mode=memory&cache=shared",
                    self.key_provider,
                )
                self.addCleanup(store.close)
                head = synthetic_head(installation_id=f"synthetic-effect-recovery-{mode}")
                writer_vault = self.writer_vault_for(head)
                execution_vault = InMemoryExecutionCapabilityVault()
                store.seed_finalized_authority(self.authority_for(head))
                current_head = LostReleaseThenFaultyLeaseLookupCurrentHead(head, mode)
                core = HealthCore(
                    store,
                    current_head,
                    execution_capability_vault=execution_vault,
                    writer_fence_vault=writer_vault,
                )
                plugin = HealthPlugin(core)
                issued = plugin.invoke(
                    self.command(
                        "effect.request",
                        f"faulty-effect-intent-{mode}",
                        self.effect_request_payload(),
                    ),
                    peer_id="plugin",
                )
                self.assertEqual(issued.status, "accepted")
                grant = plugin.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                original = self.command(
                    "effect.result",
                    f"faulty-effect-result-{mode}",
                    self.effect_result_payload(issued.meta, grant),
                )

                self.assertEqual(plugin.invoke(original, peer_id="plugin").status, "unknown")
                current_head.fault_lookup = True
                blocked = plugin.invoke(original, peer_id="plugin")
                guard = store.current_head_observation_guard()

                self.assertEqual(blocked.status, "unavailable")
                self.assertEqual(blocked.reason_code, expected_reason)
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                self.assertIsNone(store.receipt(original))
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
                self.assert_all_effect_paths_closed(plugin)

                current_head.fault_lookup = False
                replay = plugin.invoke(original, peer_id="plugin")
                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                core.close()
                store.close()

    def test_cross_clone_effect_release_cannot_be_taken_over_by_a_different_causal_id(self):
        with tempfile.TemporaryDirectory() as directory:
            head = synthetic_head(installation_id="synthetic-cross-clone-effect")
            writer_vault = self.writer_vault_for(head)
            execution_vault = InMemoryExecutionCapabilityVault()
            store_a = EncryptedStateStore(str(Path(directory) / "a.sqlite"), self.key_provider)
            store_b = EncryptedStateStore(str(Path(directory) / "b.sqlite"), self.key_provider)
            authority = self.authority_for(head)
            store_a.seed_finalized_authority(authority)
            store_b.seed_finalized_authority(authority)
            b_core = None
            a_core = None
            recovery_core = None
            try:
                b_core = HealthCore(
                    store_b,
                    head,
                    execution_capability_vault=execution_vault,
                    writer_fence_vault=writer_vault,
                )
                b_plugin = HealthPlugin(b_core)
                issued = b_plugin.invoke(
                    self.command("effect.request", "clone-effect-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                self.assertEqual(issued.status, "accepted")
                grant = b_plugin.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                stored_b = store_b.effect(issued.meta["effect_id"])
                self.assertIsNotNone(stored_b)
                self.assertEqual(stored_b.state, "executing")
                execution = stored_b.payload
                original_b = self.command(
                    "effect.result",
                    "clone-effect-result-b",
                    self.effect_result_payload(issued.meta, grant),
                )
                store_b.reserve_pending_effect_result(original_b, execution)
                store_b.mark_pending_effect_result_attempted(original_b, execution)
                store_b.arm_current_head_observation(CurrentHeadRecoveryBinding.from_command(original_b))
                b_core.close()
                execution_vault.simulate_process_crash_for_test()

                # This is a post-crash local clone: it has the same executing
                # intent but owns a different terminal causal command.
                store_a.write_effect(issued.meta["effect_id"], "executing", execution)
                a_core = HealthCore(
                    store_a,
                    head,
                    execution_capability_vault=execution_vault,
                    writer_fence_vault=writer_vault,
                )
                a_plugin = HealthPlugin(a_core)
                original_a = self.command(
                    "effect.result",
                    "clone-effect-result-a",
                    self.effect_result_payload(issued.meta, grant),
                )
                accepted_a = a_plugin.invoke(original_a, peer_id="plugin")
                self.assertEqual(accepted_a.status, "accepted")
                release_receipt = head.lookup_execution_lease(
                    ExecutionLeaseIdentity(
                        expected=grant.lease.authority,
                        effect_id=grant.lease.effect_id,
                        intent_digest=grant.lease.intent_digest,
                        writer_fence=grant.lease.authority.writer_fence,
                        holder_id=grant.lease.holder_id,
                    )
                )
                self.assertTrue(release_receipt.released)
                self.assertEqual(
                    release_receipt.released_operation_digest,
                    CurrentHeadRecoveryBinding.from_command(original_a).command_digest,
                )
                a_core.close()

                recovery_core = HealthCore(
                    store_b,
                    head,
                    execution_capability_vault=execution_vault,
                    writer_fence_vault=writer_vault,
                )
                recovered_b = HealthPlugin(recovery_core)
                blocked = recovered_b.invoke(original_b, peer_id="plugin")
                guard = store_b.current_head_observation_guard()

                self.assertEqual(blocked.status, "unavailable")
                self.assertEqual(blocked.reason_code, "effect-release-owner-mismatch")
                self.assertEqual(store_b.effect_state(issued.meta["effect_id"]), "executing")
                self.assertIsNone(store_b.receipt(original_b))
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
                replay = recovered_b.invoke(original_b, peer_id="plugin")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assert_all_effect_paths_closed(recovered_b)
            finally:
                if recovery_core is not None:
                    recovery_core.close()
                if a_core is not None:
                    a_core.close()
                if b_core is not None:
                    b_core.close()
                store_b.close()
                store_a.close()

    def test_foreign_clone_cannot_consume_an_exact_effect_release_recovery_binding(self):
        issued = self.send(
            self.command("effect.request", "bound-effect-recovery-intent", self.effect_request_payload())
        )
        owner = HealthPlugin(
            self.core_for(
                self.store,
                LostReleaseResponseCurrentHead(self.head),
                execution_capability_vault=self.execution_vault,
            )
        )
        grant = owner.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        original = self.command(
            "effect.result",
            "bound-effect-recovery-result",
            self.effect_result_payload(issued.meta, grant),
        )

        first = owner.invoke(original, peer_id="plugin")
        foreign = HealthPlugin(
            HealthCore(
                self.store,
                self.head,
                execution_capability_vault=InMemoryExecutionCapabilityVault(),
                writer_fence_vault=None,
            )
        )
        blocked = foreign.invoke(original, peer_id="plugin")
        guard_after_foreign = self.store.current_head_observation_guard()
        recovered = owner.invoke(original, peer_id="plugin")

        self.assertEqual(first.status, "unknown")
        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "current-writer-holder-missing")
        self.assertIsNotNone(guard_after_foreign)
        self.assertEqual(guard_after_foreign.binding, CurrentHeadRecoveryBinding.from_command(original))
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "accepted")

    def test_foreign_installation_cannot_terminalize_a_released_effect_recovery(self):
        issued = self.send(
            self.command("effect.request", "foreign-installation-effect-intent", self.effect_request_payload())
        )
        owner_head = LostReleaseResponseCurrentHead(self.head)
        owner = HealthPlugin(
            self.core_for(
                self.store,
                owner_head,
                execution_capability_vault=self.execution_vault,
            )
        )
        grant = owner.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        original = self.command(
            "effect.result",
            "foreign-installation-effect-result",
            self.effect_result_payload(issued.meta, grant),
        )
        self.assertEqual(owner.invoke(original, peer_id="plugin").status, "unknown")

        foreign_head = synthetic_head(installation_id="synthetic-foreign-effect-installation")
        foreign = HealthPlugin(
            HealthCore(
                self.store,
                ForeignInstallationLeaseRecoveryCurrentHead(foreign_head, self.head),
                execution_capability_vault=InMemoryExecutionCapabilityVault(),
                writer_fence_vault=self.writer_vault_for(foreign_head),
            )
        )
        blocked = foreign.invoke(original, peer_id="plugin")
        guard_after_foreign = self.store.current_head_observation_guard()

        self.assertEqual(blocked.status, "unavailable")
        # The foreign installation has no host-private proof for the original
        # installation, so recovery stops before it can consume B or read its
        # own head.  That is stronger than reporting a remote mismatch later.
        self.assertEqual(blocked.reason_code, "current-writer-holder-missing")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "executing")
        self.assertIsNotNone(guard_after_foreign)
        self.assertEqual(guard_after_foreign.binding, CurrentHeadRecoveryBinding.from_command(original))
        self.assertNotEqual(foreign.probe().state, ProbeState.HEALTHY)
        recovered = owner.invoke(original, peer_id="plugin")
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "accepted")

    def test_observed_foreign_installation_consumes_state_recovery_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "foreign-installation-state-binding.sqlite")
            primary_head = synthetic_head(installation_id="synthetic-primary-state-installation")
            foreign_head = synthetic_head(installation_id="synthetic-foreign-state-installation")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = InMemoryWriterFenceVault()
            writer_vault.bind(self.authority_for(primary_head), _TEST_WRITER_CAPABILITY)
            writer_vault.bind(self.authority_for(foreign_head), _TEST_WRITER_CAPABILITY)
            store.seed_finalized_authority(self.authority_for(primary_head))
            try:
                owner_core = HealthCore(
                    store,
                    primary_head,
                    execution_capability_vault=InMemoryExecutionCapabilityVault(),
                    writer_fence_vault=writer_vault,
                )
                owner = HealthPlugin(owner_core)
                payload = self.state_payload()
                self.assertEqual(
                    owner.invoke(
                        self.command("state.candidate", "foreign-state-candidate", payload),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                self.assertEqual(
                    owner.invoke(
                        self.command("state.prepare", "foreign-state-prepare", payload),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                original = self.command("state.commit", "foreign-state-original", self.commit_payload())
                primary_head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
                self.assertEqual(owner.invoke(original, peer_id="plugin").status, "unknown")
                primary_head.clear_failure()
                owner_core.close()

                rerouted_head = SwitchableInstallationRecoveryCurrentHead(primary_head, foreign_head)
                rerouted_head.use_foreign = True
                foreign_core = HealthCore(
                    store,
                    rerouted_head,
                    execution_capability_vault=InMemoryExecutionCapabilityVault(),
                    writer_fence_vault=writer_vault,
                )
                foreign = HealthPlugin(foreign_core)

                mismatch = foreign.invoke(original, peer_id="plugin")
                guard = store.current_head_observation_guard()

                self.assertEqual(mismatch.status, "unavailable")
                self.assertEqual(mismatch.reason_code, "prepared-installation-mismatch")
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
                foreign_core.close()

                resumed = HealthPlugin(
                    HealthCore(
                        store,
                        primary_head,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                replay = resumed.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(primary_head.read().head.generation, 2)
                self.assertEqual(store.record_state("record-1"), "unknown")
                self.assert_all_effect_paths_closed(resumed)
            finally:
                store.close()

    def test_observed_foreign_installation_consumes_effect_recovery_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "foreign-installation-effect-binding.sqlite")
            primary_head = synthetic_head(installation_id="synthetic-primary-effect-installation")
            foreign_head = synthetic_head(installation_id="synthetic-foreign-effect-installation")
            primary_release_head = LostReleaseResponseCurrentHead(primary_head)
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = InMemoryWriterFenceVault()
            writer_vault.bind(self.authority_for(primary_head), _TEST_WRITER_CAPABILITY)
            writer_vault.bind(self.authority_for(foreign_head), _TEST_WRITER_CAPABILITY)
            execution_vault = InMemoryExecutionCapabilityVault()
            store.seed_finalized_authority(self.authority_for(primary_head))
            try:
                owner_core = HealthCore(
                    store,
                    primary_release_head,
                    execution_capability_vault=execution_vault,
                    writer_fence_vault=writer_vault,
                )
                owner = HealthPlugin(owner_core)
                issued = owner.invoke(
                    self.command("effect.request", "foreign-effect-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                grant = owner.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                original = self.command(
                    "effect.result",
                    "foreign-effect-original",
                    self.effect_result_payload(issued.meta, grant),
                )
                self.assertEqual(owner.invoke(original, peer_id="plugin").status, "unknown")
                owner_core.close()

                rerouted_head = SwitchableInstallationRecoveryCurrentHead(
                    primary_release_head,
                    foreign_head,
                )
                rerouted_head.use_foreign = True
                foreign_core = HealthCore(
                    store,
                    rerouted_head,
                    execution_capability_vault=InMemoryExecutionCapabilityVault(),
                    writer_fence_vault=writer_vault,
                )
                foreign = HealthPlugin(foreign_core)

                mismatch = foreign.invoke(original, peer_id="plugin")
                guard = store.current_head_observation_guard()

                self.assertEqual(mismatch.status, "unavailable")
                self.assertEqual(mismatch.reason_code, "effect-installation-mismatch")
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
                foreign_core.close()

                resumed = HealthPlugin(
                    HealthCore(
                        store,
                        primary_release_head,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                replay = resumed.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                self.assert_all_effect_paths_closed(resumed)
            finally:
                store.close()

    def test_rotated_writer_fence_consumes_effect_recovery_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "rotated-fence-effect-binding.sqlite")
            primary_head = synthetic_head(installation_id="synthetic-rotated-effect-recovery")
            release_head = LostReleaseResponseCurrentHead(primary_head)
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(primary_head)
            execution_vault = InMemoryExecutionCapabilityVault()
            store.seed_finalized_authority(self.authority_for(primary_head))
            try:
                owner_core = HealthCore(
                    store,
                    release_head,
                    execution_capability_vault=execution_vault,
                    writer_fence_vault=writer_vault,
                )
                owner = HealthPlugin(owner_core)
                issued = owner.invoke(
                    self.command("effect.request", "rotated-effect-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                grant = owner.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                original = self.command(
                    "effect.result",
                    "rotated-effect-original",
                    self.effect_result_payload(issued.meta, grant),
                )
                self.assertEqual(owner.invoke(original, peer_id="plugin").status, "unknown")
                owner_core.close()

                rotated = RotatedFenceRecoveryCurrentHead(primary_head, "fence:rotated")
                writer_vault.bind(rotated.read().head.as_authority(), _TEST_WRITER_CAPABILITY)
                recovering_core = HealthCore(
                    store,
                    rotated,
                    execution_capability_vault=InMemoryExecutionCapabilityVault(),
                    writer_fence_vault=writer_vault,
                )
                recovering = HealthPlugin(recovering_core)

                rejected = recovering.invoke(original, peer_id="plugin")
                guard = store.current_head_observation_guard()

                self.assertEqual(rejected.status, "unavailable")
                self.assertEqual(rejected.reason_code, "effect-writer-fence-mismatch")
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
                self.assert_all_effect_paths_closed(recovering)
            finally:
                store.close()

    def test_post_release_rotated_writer_fence_cannot_close_effect_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "post-release-rotated-fence.sqlite")
            primary_head = synthetic_head(installation_id="synthetic-post-release-rotated")
            current_head = RotatedFenceAfterReleaseCurrentHead(primary_head, "fence:rotated")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(primary_head)
            writer_vault.bind(
                replace(self.authority_for(primary_head), writer_fence="fence:rotated"),
                _TEST_WRITER_CAPABILITY,
            )
            execution_vault = InMemoryExecutionCapabilityVault()
            store.seed_finalized_authority(self.authority_for(primary_head))
            try:
                owner = HealthPlugin(
                    HealthCore(
                        store,
                        current_head,
                        execution_capability_vault=execution_vault,
                        writer_fence_vault=writer_vault,
                    )
                )
                issued = owner.invoke(
                    self.command("effect.request", "post-release-rotated-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                grant = owner.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                original = self.command(
                    "effect.result",
                    "post-release-rotated-result",
                    self.effect_result_payload(issued.meta, grant),
                )

                rejected = owner.invoke(original, peer_id="plugin")
                guard = store.current_head_observation_guard()

                self.assertEqual(rejected.status, "unavailable")
                self.assertEqual(rejected.reason_code, "effect-writer-fence-mismatch")
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
                self.assert_all_effect_paths_closed(owner)
            finally:
                store.close()

    def test_post_release_foreign_installation_consumes_effect_closure_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "post-release-foreign-installation.sqlite")
            primary_head = synthetic_head(installation_id="synthetic-post-release-primary")
            foreign_head = synthetic_head(installation_id="synthetic-post-release-foreign")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = InMemoryWriterFenceVault()
            writer_vault.bind(self.authority_for(primary_head), _TEST_WRITER_CAPABILITY)
            writer_vault.bind(self.authority_for(foreign_head), _TEST_WRITER_CAPABILITY)
            execution_vault = InMemoryExecutionCapabilityVault()
            store.seed_finalized_authority(self.authority_for(primary_head))
            try:
                owner_core = HealthCore(
                    store,
                    ForeignHeadAfterReleaseCurrentHead(primary_head, foreign_head),
                    execution_capability_vault=execution_vault,
                    writer_fence_vault=writer_vault,
                )
                owner = HealthPlugin(owner_core)
                issued = owner.invoke(
                    self.command("effect.request", "post-release-foreign-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                grant = owner.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                original = self.command(
                    "effect.result",
                    "post-release-foreign-original",
                    self.effect_result_payload(issued.meta, grant),
                )

                first = owner.invoke(original, peer_id="plugin")
                guard = store.current_head_observation_guard()

                self.assertEqual(first.status, "unavailable")
                self.assertEqual(first.reason_code, "effect-installation-mismatch")
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
                owner_core.close()

                resumed = HealthPlugin(
                    HealthCore(
                        store,
                        primary_head,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                replay = resumed.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                self.assert_all_effect_paths_closed(resumed)
            finally:
                store.close()

    def test_foreign_clone_cannot_consume_an_exact_state_cas_recovery_binding(self):
        self.establish_prepared()
        original = self.command("state.commit", "bound-state-recovery-commit", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        first = self.send(original)
        self.head.clear_failure()
        foreign = HealthPlugin(
            HealthCore(
                self.store,
                self.head,
                execution_capability_vault=InMemoryExecutionCapabilityVault(),
                writer_fence_vault=None,
            )
        )

        blocked = foreign.invoke(original, peer_id="plugin")
        guard_after_foreign = self.store.current_head_observation_guard()
        recovered = self.send(original)

        self.assertEqual(first.status, "unknown")
        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "current-writer-holder-missing")
        self.assertIsNotNone(guard_after_foreign)
        self.assertEqual(guard_after_foreign.binding, CurrentHeadRecoveryBinding.from_command(original))
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "committed")

    def test_cross_clone_state_receipt_cannot_be_taken_over_by_a_different_causal_id(self):
        with tempfile.TemporaryDirectory() as directory:
            head = synthetic_head(installation_id="synthetic-cross-clone-state")
            writer_vault = self.writer_vault_for(head)
            store_a = EncryptedStateStore(str(Path(directory) / "a.sqlite"), self.key_provider)
            store_b = EncryptedStateStore(str(Path(directory) / "b.sqlite"), self.key_provider)
            authority = self.authority_for(head)
            store_a.seed_finalized_authority(authority)
            store_b.seed_finalized_authority(authority)
            b_core = None
            a_core = None
            recovery_core = None
            try:
                b_core = HealthCore(
                    store_b,
                    head,
                    execution_capability_vault=InMemoryExecutionCapabilityVault(),
                    writer_fence_vault=writer_vault,
                )
                b_plugin = HealthPlugin(b_core)
                payload_b = self.state_payload("record-b")
                self.assertEqual(
                    b_plugin.invoke(
                        self.command("state.candidate", "clone-b-candidate", payload_b),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                self.assertEqual(
                    b_plugin.invoke(
                        self.command("state.prepare", "clone-b-prepare", payload_b),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                original_b = self.command(
                    "state.commit",
                    "clone-b-state-result",
                    {
                        "record_id": "record-b",
                        "revision_digest": "sha256:revision-1",
                        "transition_id": "transition-1",
                        "writer_fence": "fence:1",
                    },
                )
                prepared_b = store_b.record("record-b")
                self.assertIsNotNone(prepared_b)
                self.assertTrue(store_b.reserve_pending_commit(original_b, prepared_b.payload))
                store_b.mark_pending_remote_attempted(original_b)
                store_b.arm_current_head_observation(CurrentHeadRecoveryBinding.from_command(original_b))
                b_core.close()

                a_core = HealthCore(
                    store_a,
                    head,
                    execution_capability_vault=InMemoryExecutionCapabilityVault(),
                    writer_fence_vault=writer_vault,
                )
                a_plugin = HealthPlugin(a_core)
                payload_a = self.state_payload("record-a")
                self.assertEqual(
                    a_plugin.invoke(
                        self.command("state.candidate", "clone-a-candidate", payload_a),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                self.assertEqual(
                    a_plugin.invoke(
                        self.command("state.prepare", "clone-a-prepare", payload_a),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                accepted_a = a_plugin.invoke(
                    self.command(
                        "state.commit",
                        "clone-a-state-result",
                        {
                            "record_id": "record-a",
                            "revision_digest": "sha256:revision-1",
                            "transition_id": "transition-1",
                            "writer_fence": "fence:1",
                        },
                    ),
                    peer_id="plugin",
                )
                self.assertEqual(accepted_a.status, "accepted")
                a_core.close()

                recovery_core = HealthCore(
                    store_b,
                    head,
                    execution_capability_vault=InMemoryExecutionCapabilityVault(),
                    writer_fence_vault=writer_vault,
                )
                recovered_b = HealthPlugin(recovery_core)
                blocked = recovered_b.invoke(original_b, peer_id="plugin")
                guard = store_b.current_head_observation_guard()

                self.assertEqual(blocked.status, "unavailable")
                self.assertEqual(blocked.reason_code, "transition-recovery-unconfirmed")
                self.assertEqual(store_b.record_state("record-b"), "prepared")
                self.assertIsNone(store_b.receipt(original_b))
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
                with self.assertRaises(TransitionNotFound):
                    head.lookup_transition(
                        AdvanceIdentity(
                            expected=prepared_b.payload.base,
                            transition_id="transition-1",
                            revision_digest="sha256:revision-1",
                            writer_fence="fence:1",
                            operation_digest=CurrentHeadRecoveryBinding.from_command(original_b).command_digest,
                        )
                    )
                replay = recovered_b.invoke(original_b, peer_id="plugin")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assert_all_effect_paths_closed(recovered_b)
            finally:
                if recovery_core is not None:
                    recovery_core.close()
                if a_core is not None:
                    a_core.close()
                if b_core is not None:
                    b_core.close()
                store_b.close()
                store_a.close()

    def test_confirmed_cas_cannot_write_local_record_or_receipt_after_writer_loss(self):
        self.establish_prepared()
        original = self.command("state.commit", "writer-loss-after-cas", self.commit_payload())
        stale = HealthPlugin(
            DropWriterBeforeStatePersistenceCore(
                self.store,
                self.head,
                execution_capability_vault=self.execution_vault,
                writer_fence_vault=self.writer_vault,
            )
        )

        blocked = stale.invoke(original, peer_id="plugin")

        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "current-writer-holder-missing")
        self.assertEqual(self.head.read().head.generation, 2)
        self.assertEqual(self.store.record_state("record-1"), "prepared")
        self.assertIsNone(self.store.receipt(original))
        self.assertIsNotNone(self.store.pending_for_record("record-1"))

        recovered = self.send(original)
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "committed")
        self.assertEqual(self.send(original).to_wire(), recovered.to_wire())

    def test_confirmed_release_cannot_terminalize_or_receipt_after_writer_loss(self):
        stale = HealthPlugin(
            DropWriterBeforeEffectPersistenceCore(
                self.store,
                self.head,
                execution_capability_vault=self.execution_vault,
                writer_fence_vault=self.writer_vault,
            )
        )
        issued = stale.invoke(
            self.command("effect.request", "writer-loss-after-release-intent", self.effect_request_payload()),
            peer_id="plugin",
        )
        grant = stale.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        original = self.command(
            "effect.result",
            "writer-loss-after-release-result",
            self.effect_result_payload(issued.meta, grant),
        )

        blocked = stale.invoke(original, peer_id="plugin")

        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "current-writer-holder-missing")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "executing")
        self.assertIsNone(self.store.receipt(original))
        pending = self.store.pending_effect_result(issued.meta["effect_id"])
        self.assertIsNotNone(pending)
        self.assertTrue(pending.remote_attempted)

        recovered = self.send(original)
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "accepted")
        self.assertEqual(self.send(original).to_wire(), recovered.to_wire())

    def test_synthetic_current_head_never_exports_a_writer_credential(self):
        with self.assertRaises(ValueError):
            InMemoryCurrentHead(
                installation_id="synthetic-missing-writer-credential",
                writer_capability=None,
            )
        head = synthetic_head(installation_id="synthetic-private-writer-credential")
        empty_vault = InMemoryWriterFenceVault()

        self.assertFalse(hasattr(head, "synthetic_writer_capability"))
        self.assertIsNone(
            empty_vault.acquire_or_resume(
                head.read().head.installation_id,
                head.read().head.site,
                WriterHolderClaim("synthetic-empty-holder"),
            )
        )

    def test_only_one_live_core_holds_the_writer_namespace_and_effect_gates(self):
        shared_writer_vault = self.writer_vault_for(self.head)
        shared_execution_vault = InMemoryExecutionCapabilityVault()
        primary_core = HealthCore(
            self.store,
            self.head,
            execution_capability_vault=shared_execution_vault,
            writer_fence_vault=shared_writer_vault,
        )
        standby_core = HealthCore(
            self.store,
            self.head,
            execution_capability_vault=shared_execution_vault,
            writer_fence_vault=shared_writer_vault,
        )
        primary = HealthPlugin(primary_core)
        standby = HealthPlugin(standby_core)

        primary_report = primary.probe()
        standby_report = standby.probe()

        self.assertEqual(primary_report.state, ProbeState.HEALTHY)
        self.assertTrue(primary.model_effects_allowed())
        self.assertTrue(primary.outbound_effects_allowed())
        self.assertEqual(standby_report.state, ProbeState.UNAVAILABLE)
        self.assertEqual(standby_report.reason_code, "current-writer-holder-missing")
        self.assertFalse(standby.model_effects_allowed())
        self.assertFalse(standby.outbound_effects_allowed())

        primary_core.close()

        self.assertEqual(standby.probe().state, ProbeState.HEALTHY)
        self.assertTrue(standby.model_effects_allowed())
        self.assertTrue(standby.outbound_effects_allowed())

    def test_foreign_core_without_writer_proof_cannot_poison_a_generic_observation_guard(self):
        foreign_core = CrashAfterGuardArmCore(
            self.store,
            self.head,
            execution_capability_vault=InMemoryExecutionCapabilityVault(),
            writer_fence_vault=None,
        )
        foreign = HealthPlugin(foreign_core)

        candidate = foreign.invoke(
            self.command("state.candidate", "foreign-guard-candidate", self.state_payload("foreign-guard")),
            peer_id="plugin",
        )
        request = foreign.invoke(
            self.command("effect.request", "foreign-guard-effect", self.effect_request_payload()),
            peer_id="plugin",
        )
        report = foreign.probe()
        owner = self.send(
            self.command("state.candidate", "owner-after-foreign-guard", self.state_payload("owner-guard"))
        )

        self.assertEqual(candidate.status, "unavailable")
        self.assertEqual(candidate.reason_code, "current-writer-holder-missing")
        self.assertEqual(request.status, "unavailable")
        self.assertEqual(request.reason_code, "current-writer-holder-missing")
        self.assertEqual(report.state, ProbeState.UNAVAILABLE)
        self.assertEqual(report.reason_code, "current-writer-holder-missing")
        self.assertFalse(foreign_core.guard_entered)
        self.assertIsNone(self.store.current_head_observation_guard())
        self.assertEqual(owner.status, "accepted")

    def test_transition_lookup_rechecks_current_head_before_releasing_its_journal(self):
        self.establish_prepared()
        original = self.command("state.commit", "lookup-overtaken", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        self.assertEqual(self.send(original).status, "unknown")
        self.head.clear_failure()
        plugin = HealthPlugin(self.core_for(self.store, AdvanceAfterLookupCurrentHead(self.head)))

        recovered = decode_response_frame(plugin.handle_frame(encode_frame(original), peer_id="plugin"))
        guard = self.store.current_head_observation_guard()

        self.assertEqual(recovered.status, "unavailable")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assertIsNotNone(self.store.pending_for_record("record-1"))
        self.assertIsNotNone(guard)
        self.assertIsNone(guard.binding)
        self.assertEqual(self.head.read().head.generation, 3)
        replay = decode_response_frame(plugin.handle_frame(encode_frame(original), peer_id="plugin"))
        self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assert_all_effect_paths_closed(plugin)

    def test_stale_pre_cas_journal_is_cleared_before_any_remote_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            head = synthetic_head(installation_id="synthetic-stale-pre-cas")
            store = BlockingJournalStore(str(Path(directory) / "stale-pre-cas.sqlite"), self.key_provider)
            try:
                store.seed_finalized_authority(self.authority_for(head))
                plugin = HealthPlugin(self.core_for(store, head))
                payload = self.state_payload()
                self.assertEqual(
                    decode_response_frame(
                        plugin.handle_frame(
                            encode_frame(self.command("state.candidate", "stale-journal-candidate", payload)),
                            peer_id="plugin",
                        )
                    ).status,
                    "accepted",
                )
                self.assertEqual(
                    decode_response_frame(
                        plugin.handle_frame(
                            encode_frame(self.command("state.prepare", "stale-journal-prepare", payload)),
                            peer_id="plugin",
                        )
                    ).status,
                    "accepted",
                )
                commit = self.command("state.commit", "stale-journal-commit", self.commit_payload())
                responses = []

                worker = threading.Thread(
                    target=lambda: responses.append(
                        decode_response_frame(plugin.handle_frame(encode_frame(commit), peer_id="plugin"))
                    )
                )
                worker.start()
                try:
                    self.assertTrue(store.journal_started.wait(timeout=1))
                    self.advance_head(
                        head,
                        transition_id="transition:external-before-cas",
                        revision_digest="sha256:external-before-cas",
                    )
                finally:
                    store.release_journal.set()
                    worker.join(timeout=2)

                self.assertFalse(worker.is_alive())
                self.assertEqual(responses[0].status, "unavailable")
                self.assertEqual(responses[0].reason_code, "current-head-conflict")
                self.assertEqual(store.record_state("record-1"), "prepared")
                self.assertIsNone(store.pending_for_record("record-1"))
                with self.assertRaises(TransitionNotFound):
                    head.lookup_transition(
                        AdvanceIdentity(
                            expected=self.authority_for(head),
                            transition_id="transition-1",
                            revision_digest="sha256:revision-1",
                            writer_fence=head.read().head.writer_fence,
                            operation_digest=_TEST_OPERATION_DIGEST,
                        )
                    )
                self.assert_all_effect_paths_closed(plugin)
            finally:
                store.close()

    def test_terminal_observation_is_durable_across_same_name_current_head_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "terminal-latch.sqlite")
            head = synthetic_head(installation_id="synthetic-terminal-latch")
            original = head.read().head
            store = EncryptedStateStore(database, self.key_provider)
            store.seed_finalized_authority(self.authority_for(head))
            try:
                writer_vault = InMemoryWriterFenceVault()
                writer_vault.bind(original.as_authority(), _TEST_WRITER_CAPABILITY)
                first_plugin = HealthPlugin(
                    HealthCore(
                        store,
                        TerminalThenRecreatedCurrentHead(original),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                first = first_plugin.probe()
                self.assertEqual(first.state, ProbeState.UNAVAILABLE)
                self.assertEqual(first.reason_code, "current-head-terminal")
                self.assert_all_effect_paths_closed(first_plugin)
            finally:
                store.close()

            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recreated_plugin = HealthPlugin(self.core_for(reopened, SnapshotCurrentHead(original)))
                report = recreated_plugin.probe()
                response = decode_response_frame(
                    recreated_plugin.handle_frame(
                        encode_frame(self.command("state.candidate", "after-terminal-latch", self.state_payload())),
                        peer_id="plugin",
                    )
                )
                self.assertEqual(report.state, ProbeState.UNAVAILABLE)
                self.assertEqual(report.reason_code, "current-head-terminal")
                self.assertEqual(response.status, "unavailable")
                self.assertEqual(response.reason_code, "current-head-terminal")
                self.assertEqual(reopened.count_records(), 0)
                self.assert_all_effect_paths_closed(recreated_plugin)
            finally:
                reopened.close()

    def test_terminal_crash_during_state_recovery_preflight_never_replays_same_h2_head(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "terminal-state-recovery-preflight.sqlite")
            head = synthetic_head(installation_id="synthetic-terminal-state-recovery")
            writer_vault = self.writer_vault_for(head)
            store = EncryptedStateStore(database, self.key_provider)
            store.seed_finalized_authority(self.authority_for(head))
            original = self.command(
                "state.commit",
                "terminal-state-recovery-original",
                {
                    "record_id": "record-1",
                    "revision_digest": "sha256:revision-1",
                    "transition_id": "transition-1",
                    "writer_fence": "fence:1",
                },
            )
            try:
                setup_core = HealthCore(
                    store,
                    head,
                    execution_capability_vault=InMemoryExecutionCapabilityVault(),
                    writer_fence_vault=writer_vault,
                )
                setup = HealthPlugin(setup_core)
                payload = self.state_payload()
                self.assertEqual(
                    setup.invoke(self.command("state.candidate", "terminal-state-recovery-candidate", payload), peer_id="plugin").status,
                    "accepted",
                )
                self.assertEqual(
                    setup.invoke(self.command("state.prepare", "terminal-state-recovery-prepare", payload), peer_id="plugin").status,
                    "accepted",
                )
                prepared = store.record("record-1")
                self.assertIsNotNone(prepared)
                self.assertTrue(store.reserve_pending_commit(original, prepared.payload))
                store.mark_pending_remote_attempted(original)
                store.arm_current_head_observation(CurrentHeadRecoveryBinding.from_command(original))
                self.advance_head(
                    head,
                    revision_digest="sha256:revision-1",
                    transition_id="transition-1",
                )
                setup_core.close()

                crashing = HealthPlugin(
                    CrashBeforeTerminalLatchCore(
                        store,
                        TerminalOnceCurrentHead(head),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                with self.assertRaises(SyntheticCrash):
                    crashing.invoke(original, peer_id="plugin")

                guard = store.current_head_observation_guard()
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
                self.assertEqual(store.record_state("record-1"), "prepared")
            finally:
                store.close()

            recreated = synthetic_head(installation_id="synthetic-terminal-state-recovery")
            self.advance_head(
                recreated,
                revision_digest="sha256:revision-1",
                transition_id="transition-1",
            )
            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        recreated,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(recreated),
                    )
                )

                replay = recovered.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(recreated.read().head.generation, 2)
                self.assertEqual(reopened.record_state("record-1"), "prepared")
                self.assert_all_effect_paths_closed(recovered)
            finally:
                reopened.close()

    def test_terminal_crash_during_effect_recovery_preflight_never_closes_historical_release(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "terminal-effect-recovery-preflight.sqlite")
            head = synthetic_head(installation_id="synthetic-terminal-effect-recovery")
            writer_vault = self.writer_vault_for(head)
            execution_vault = InMemoryExecutionCapabilityVault()
            store = EncryptedStateStore(database, self.key_provider)
            store.seed_finalized_authority(self.authority_for(head))
            try:
                owner_core = HealthCore(
                    store,
                    LostReleaseResponseCurrentHead(head),
                    execution_capability_vault=execution_vault,
                    writer_fence_vault=writer_vault,
                )
                owner = HealthPlugin(owner_core)
                issued = owner.invoke(
                    self.command("effect.request", "terminal-effect-recovery-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                grant = owner.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                original = self.command(
                    "effect.result",
                    "terminal-effect-recovery-original",
                    self.effect_result_payload(issued.meta, grant),
                )
                self.assertEqual(owner.invoke(original, peer_id="plugin").status, "unknown")
                guard = store.current_head_observation_guard()
                self.assertIsNotNone(guard)
                self.assertEqual(guard.binding, CurrentHeadRecoveryBinding.from_command(original))
                owner_core.close()

                crashing = HealthPlugin(
                    CrashBeforeTerminalLatchCore(
                        store,
                        TerminalOnceCurrentHead(head),
                        execution_capability_vault=execution_vault,
                        writer_fence_vault=writer_vault,
                    )
                )
                with self.assertRaises(SyntheticCrash):
                    crashing.invoke(original, peer_id="plugin")

                guard = store.current_head_observation_guard()
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
            finally:
                store.close()

            recreated = synthetic_head(installation_id="synthetic-terminal-effect-recovery")
            self.advance_head(
                recreated,
                revision_digest="sha256:recreated-effect-head",
                transition_id="transition:recreated-effect-head",
            )
            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        ForeignInstallationLeaseRecoveryCurrentHead(recreated, head),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(recreated),
                    )
                )

                replay = recovered.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(recreated.read().head.generation, 2)
                self.assertEqual(reopened.effect_state(original.payload.effect_id), "executing")
                self.assert_all_effect_paths_closed(recovered)
            finally:
                reopened.close()

    def test_state_recovery_preflight_timeout_rebinds_only_for_the_same_live_writer(self):
        self.establish_prepared()
        original = self.command("state.commit", "recovery-preflight-timeout", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        self.assertEqual(self.send(original).status, "unknown")
        self.head.clear_failure()
        self.head.set_failure(FailureMode.TIMEOUT, operation="read")

        first_retry = self.send(original)
        guard = self.store.current_head_observation_guard()
        self.head.clear_failure()
        recovered = self.send(original)

        self.assertEqual(first_retry.status, "unavailable")
        self.assertEqual(first_retry.reason_code, "current-head-unavailable")
        self.assertIsNotNone(guard)
        self.assertEqual(guard.binding, CurrentHeadRecoveryBinding.from_command(original))
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "committed")

    def test_rejected_writer_validation_consumes_state_recovery_binding(self):
        self.establish_prepared()
        original = self.command("state.commit", "rejected-writer-recovery", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        self.assertEqual(self.send(original).status, "unknown")
        self.head.clear_failure()
        rejecting_head = RejectingWriterValidationCurrentHead(self.head)
        rejecting_head.reject_writer = True
        plugin = HealthPlugin(self.core_for(self.store, rejecting_head))

        rejected = plugin.invoke(original, peer_id="plugin")
        guard = self.store.current_head_observation_guard()

        self.assertEqual(rejected.status, "unavailable")
        self.assertEqual(rejected.reason_code, "current-writer-holder-missing")
        self.assertIsNotNone(guard)
        self.assertIsNone(guard.binding)
        rejecting_head.reject_writer = False

        replay = plugin.invoke(original, peer_id="plugin")

        self.assertEqual(replay.status, "unavailable")
        self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assert_all_effect_paths_closed(plugin)

    def test_effect_recovery_preflight_timeout_rebinds_only_for_the_same_live_writer(self):
        issued = self.send(
            self.command("effect.request", "effect-recovery-preflight-intent", self.effect_request_payload())
        )
        owner = HealthPlugin(
            self.core_for(
                self.store,
                LostReleaseResponseCurrentHead(self.head),
                execution_capability_vault=self.execution_vault,
            )
        )
        grant = owner.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        original = self.command(
            "effect.result",
            "effect-recovery-preflight-result",
            self.effect_result_payload(issued.meta, grant),
        )
        self.assertEqual(owner.invoke(original, peer_id="plugin").status, "unknown")
        self.head.set_failure(FailureMode.TIMEOUT, operation="read")

        first_retry = owner.invoke(original, peer_id="plugin")
        guard = self.store.current_head_observation_guard()
        self.head.clear_failure()
        recovered = owner.invoke(original, peer_id="plugin")

        self.assertEqual(first_retry.status, "unavailable")
        self.assertEqual(first_retry.reason_code, "current-head-unavailable")
        self.assertIsNotNone(guard)
        self.assertEqual(guard.binding, CurrentHeadRecoveryBinding.from_command(original))
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "accepted")

    def test_rotated_writer_fence_keeps_response_loss_recovery_fail_closed(self):
        self.establish_prepared()
        original = self.command("state.commit", "rotated-fence-recovery", self.commit_payload())
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        self.assertEqual(self.send(original).status, "unknown")
        self.head.clear_failure()
        # Model the original process ending before a new holder starts.  The
        # same host has both capabilities, but there is no authenticated
        # continuity proof that authorizes F1's historical receipt as F2.
        self.core.close()
        rotated = RotatedFenceRecoveryCurrentHead(self.head, "fence:rotated")
        live = rotated.read().head.as_authority()
        self.writer_vault.bind(live, _TEST_WRITER_CAPABILITY)
        current_holder = HealthPlugin(
            HealthCore(
                self.store,
                rotated,
                execution_capability_vault=InMemoryExecutionCapabilityVault(),
                writer_fence_vault=self.writer_vault,
            )
        )

        recovered = current_holder.invoke(original, peer_id="plugin")
        guard = self.store.current_head_observation_guard()

        self.assertEqual(recovered.status, "unavailable")
        self.assertEqual(recovered.reason_code, "prepared-writer-fence-mismatch")
        self.assertIsNotNone(guard)
        self.assertIsNone(guard.binding)
        self.assertEqual(self.store.record_state("record-1"), "unknown")
        self.assert_all_effect_paths_closed(current_holder)

        replay = current_holder.invoke(original, peer_id="plugin")

        self.assertEqual(replay.status, "unavailable")
        self.assertEqual(replay.reason_code, "current-head-observation-incomplete")

    def test_crashed_attempted_commit_recovers_only_the_original_causal_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "guarded-commit-recovery.sqlite")
            head = synthetic_head(installation_id="synthetic-guarded-commit-recovery")
            store = EncryptedStateStore(database, self.key_provider)
            store.seed_finalized_authority(self.authority_for(head))
            plugin = HealthPlugin(self.core_for(store, head, execution_capability_vault=InMemoryExecutionCapabilityVault()))
            payload = self.state_payload()
            original = self.command("state.commit", "guarded-crash-original", self.commit_payload())
            try:
                self.assertEqual(
                    decode_response_frame(
                        plugin.handle_frame(
                            encode_frame(self.command("state.candidate", "guarded-crash-candidate", payload)),
                            peer_id="plugin",
                        )
                    ).status,
                    "accepted",
                )
                self.assertEqual(
                    decode_response_frame(
                        plugin.handle_frame(
                            encode_frame(self.command("state.prepare", "guarded-crash-prepare", payload)),
                            peer_id="plugin",
                        )
                    ).status,
                    "accepted",
                )
                prepared = store.record("record-1")
                self.assertIsNotNone(prepared)
                self.assertTrue(store.reserve_pending_commit(original, prepared.payload))
                store.mark_pending_remote_attempted(original)
                store.arm_current_head_observation(CurrentHeadRecoveryBinding.from_command(original))
                head.conditional_advance(
                    AdvanceRequest(
                        expected=prepared.payload.base,
                        transition_id="transition-1",
                        revision_digest="sha256:revision-1",
                        writer_fence="fence:1",
                        operation_digest=CurrentHeadRecoveryBinding.from_command(original).command_digest,
                        writer_proof=self.writer_proof_for(head, prepared.payload.base),
                    )
                )
            finally:
                store.close()

            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered_plugin = HealthPlugin(
                    self.core_for(reopened, head, execution_capability_vault=InMemoryExecutionCapabilityVault())
                )
                unrelated = decode_response_frame(
                    recovered_plugin.handle_frame(
                        encode_frame(self.command("state.candidate", "guarded-crash-unrelated", self.state_payload("other"))),
                        peer_id="plugin",
                    )
                )
                recovered = decode_response_frame(
                    recovered_plugin.handle_frame(encode_frame(original), peer_id="plugin")
                )

                self.assertEqual(unrelated.status, "unavailable")
                self.assertEqual(unrelated.reason_code, "current-head-observation-incomplete")
                self.assertEqual(recovered.status, "accepted")
                self.assertEqual(recovered.meta["generation"], 2)
                self.assertEqual(reopened.record_state("record-1"), "committed")
                self.assertIsNone(reopened.pending_for_record("record-1"))
                self.assertFalse(reopened.current_head_observation_incomplete())
            finally:
                reopened.close()

    def test_key_check_reinitialization_never_commits_an_outer_business_transaction(self):
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM key_check WHERE slot = 1")

        with self.assertRaises(SyntheticStop):
            with self.store.transaction() as connection:
                connection.execute(
                    "INSERT INTO receipts(causal_id, status, reason_code) VALUES (?, ?, ?)",
                    ("key-check-before", "accepted", "before"),
                )
                self.store.verify_key()
                self.assertTrue(connection.in_transaction)
                connection.execute(
                    "INSERT INTO receipts(causal_id, status, reason_code) VALUES (?, ?, ?)",
                    ("key-check-after", "accepted", "after"),
                )
                raise SyntheticStop("force outer rollback")

        self.assertIsNone(
            self.store._execute("SELECT 1 FROM receipts WHERE causal_id = ?", ("key-check-before",)).fetchone()
        )
        self.assertIsNone(
            self.store._execute("SELECT 1 FROM receipts WHERE causal_id = ?", ("key-check-after",)).fetchone()
        )
        self.assertIsNone(self.store._execute("SELECT 1 FROM key_check WHERE slot = 1").fetchone())

    def test_malformed_integrity_manifest_nonce_fails_all_probe_gates_closed(self):
        self.establish_finalized()
        with self.store.transaction() as connection:
            connection.execute("UPDATE integrity_manifest_v1 SET nonce = ? WHERE slot = 1", ("not-bytes",))

        report = self.plugin.probe()

        self.assertEqual(report.state, ProbeState.UNAVAILABLE)
        self.assertEqual(report.reason_code, "health-key-unavailable")
        self.assert_all_effect_paths_closed(self.plugin)

    def test_receipt_response_causal_id_must_equal_its_command(self):
        command = self.command("state.candidate", "receipt-causal-owner", self.state_payload())

        with self.assertRaises(KeyUnavailable):
            self.store.save_receipt(command, Response("accepted", "other-causal-id", "synthetic"))

        self.assertIsNone(self.store.receipt(command))

    def test_protocol_malformed_json_never_escapes_or_mutates_core_state(self):
        valid = json.dumps(
            self.command("state.candidate", "surrogate-frame", self.state_payload()).to_wire(),
            separators=(",", ":"),
            sort_keys=True,
        )
        surrogate = valid.replace('"record-1"', '"\\ud800"').encode("ascii")
        malformed_frames = (
            surrogate,
            b"[" * 1200 + b"0" + b"]" * 1200,
            b'{"generation":' + b"9" * 5000 + b"}",
            b'{"action":"probe","action":"state.candidate"}',
        )

        for body in malformed_frames:
            with self.subTest(length=len(body)):
                response = decode_response_frame(
                    self.plugin.handle_frame(struct.pack(">I", len(body)) + body, peer_id="plugin")
                )
                self.assertEqual(response.status, "rejected")

        with self.assertRaises(AuthorityValidationError):
            AuthoritySnapshot(
                installation_id="synthetic-installation",
                generation=1,
                revision_digest="sha256:empty",
                transition_id="transition:empty",
                writer_fence="fence:1",
                terminal=False,
                site="\ud800",
            )
        self.assertEqual(self.store.count_records(), 0)
        self.assertEqual(self.store.count_effects(), 0)

    def test_direct_command_objects_are_canonicalized_before_any_storage_access(self):
        forged_scope = self.command(
            "state.candidate",
            "forged-direct-scope",
            self.state_payload("forged-scope-record"),
        )
        object.__setattr__(forged_scope, "scope", ("state:candidate", "effect:request"))
        forged_generation = self.command(
            "state.candidate",
            "forged-direct-generation",
            self.state_payload("forged-generation-record"),
        )
        object.__setattr__(forged_generation, "generation", True)

        scope_response = self.plugin.invoke(forged_scope, peer_id="plugin")
        generation_response = self.core.handle(forged_generation)
        valid = self.send(
            self.command(
                "state.candidate",
                "forged-direct-scope",
                self.state_payload("forged-scope-record"),
            )
        )

        self.assertEqual(scope_response.status, "rejected")
        self.assertIsNone(scope_response.causal_id)
        self.assertEqual(scope_response.reason_code, "invalid-command-envelope")
        self.assertEqual(generation_response.status, "rejected")
        self.assertIsNone(generation_response.causal_id)
        self.assertEqual(generation_response.reason_code, "invalid-command-envelope")
        self.assertEqual(valid.status, "accepted")
        self.assertEqual(self.store.count_records(), 1)

    def test_plugin_peer_boundary_rejects_an_equality_spoofed_non_string(self):
        command = self.command(
            "state.candidate",
            "spoofed-plugin-peer",
            self.state_payload("spoofed-peer-record"),
        )

        with self.assertRaises(ProtocolViolation):
            self.plugin.invoke(command, peer_id=PretendPluginPeer())

        framed = decode_response_frame(
            self.plugin.handle_frame(encode_frame(command), peer_id=PretendPluginPeer())
        )

        self.assertEqual(framed.status, "rejected")
        self.assertEqual(framed.reason_code, "untrusted peer")
        self.assertIsNone(self.store.record_state("spoofed-peer-record"))

    def test_probe_rejects_authority_primitives_with_deceptive_equality(self):
        authority = self.authority_for(self.head)
        spoofed = object.__new__(HeadSnapshot)
        object.__setattr__(spoofed, "installation_id", DeceptiveText("other-installation", authority.installation_id))
        object.__setattr__(spoofed, "generation", DeceptiveInt(99, authority.generation))
        object.__setattr__(spoofed, "revision_digest", DeceptiveText("sha256:other", authority.revision_digest))
        object.__setattr__(spoofed, "transition_id", DeceptiveText("transition:other", authority.transition_id))
        object.__setattr__(spoofed, "writer_fence", DeceptiveText("fence:other", authority.writer_fence))
        object.__setattr__(spoofed, "terminal", False)
        object.__setattr__(spoofed, "site", DeceptiveText("other-site", authority.site))
        plugin = HealthPlugin(
            HealthCore(
                self.store,
                SpoofedAuthorityCurrentHead(self.head, spoofed),
                execution_capability_vault=InMemoryExecutionCapabilityVault(),
                writer_fence_vault=self.writer_vault,
            )
        )

        report = plugin.probe()

        self.assertEqual(report.state, ProbeState.UNAVAILABLE)
        self.assertEqual(report.reason_code, "current-head-unavailable")
        self.assert_all_effect_paths_closed(plugin)

    def test_claim_rejects_mutated_or_subclassed_effect_intents(self):
        issued = self.send(
            self.command("effect.request", "mutated-effect-intent", self.effect_request_payload())
        )
        mutated = issued.meta.intent
        object.__setattr__(mutated, "effect_kind", AlwaysEqualStr("contact-delivery"))

        self.assertIsNone(self.plugin.claim_effect_execution(mutated))
        stored = self.store.effect(issued.meta["effect_id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.state, "intent")
        self.assertEqual(stored.payload.effect_kind, "model-work")

        issued_intent = stored.payload
        forged = ForgedEffectIntent(
            effect_id=issued_intent.effect_id,
            effect_kind="model-work",
            intent_digest=issued_intent.intent_digest,
            authority=issued_intent.authority,
        )

        self.assertIsNone(self.plugin.claim_effect_execution(forged))
        stored_after_subclass = self.store.effect(issued_intent.effect_id)
        self.assertIsNotNone(stored_after_subclass)
        self.assertEqual(stored_after_subclass.state, "intent")
        self.assertEqual(stored_after_subclass.payload.effect_kind, "model-work")

    def test_foreign_writer_cannot_reserve_state_commit_recovery_ownership(self):
        self.establish_prepared()
        foreign = HealthPlugin(
            HealthCore(
                self.store,
                self.head,
                execution_capability_vault=InMemoryExecutionCapabilityVault(),
                writer_fence_vault=None,
            )
        )
        foreign_commit = self.command("state.commit", "foreign-commit-owner", self.commit_payload())

        blocked = foreign.invoke(foreign_commit, peer_id="plugin")
        owner = self.send(self.command("state.commit", "writer-commit-owner", self.commit_payload()))

        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "current-writer-holder-missing")
        self.assertIsNone(self.store.pending_for_record("record-1"))
        self.assertEqual(owner.status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "committed")

    def test_foreign_writer_cannot_reserve_effect_terminal_recovery_ownership(self):
        issued = self.send(
            self.command("effect.request", "foreign-effect-intent", self.effect_request_payload())
        )
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        foreign = HealthPlugin(
            HealthCore(
                self.store,
                self.head,
                execution_capability_vault=InMemoryExecutionCapabilityVault(),
                writer_fence_vault=None,
            )
        )
        foreign_result = self.command(
            "effect.result",
            "foreign-effect-owner",
            self.effect_result_payload(issued.meta, grant),
        )
        owner_result = self.command(
            "effect.result",
            "writer-effect-owner",
            self.effect_result_payload(issued.meta, grant),
        )

        blocked = foreign.invoke(foreign_result, peer_id="plugin")
        owner = self.send(owner_result)

        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "current-writer-holder-missing")
        self.assertIsNone(self.store.pending_effect_result(issued.meta["effect_id"]))
        self.assertEqual(owner.status, "accepted")
        self.assertEqual(self.store.effect_state(issued.meta["effect_id"]), "accepted")

    def test_same_writer_host_recovers_lost_effect_acquire_after_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "lost-effect-acquire.sqlite")
            head = synthetic_head(installation_id="synthetic-lost-effect-acquire")
            writer_vault = self.writer_vault_for(head)
            execution_vault = InMemoryExecutionCapabilityVault()
            store = EncryptedStateStore(database, self.key_provider)
            store.seed_finalized_authority(self.authority_for(head))
            lost_head = LostExecutionLeaseResponseCurrentHead(head)
            first_core = HealthCore(
                store,
                lost_head,
                execution_capability_vault=execution_vault,
                writer_fence_vault=writer_vault,
            )
            first = HealthPlugin(first_core)
            try:
                issued = first.invoke(
                    self.command("effect.request", "restart-effect-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                self.assertEqual(issued.status, "accepted")
                self.assertIsNone(first.claim_effect_execution(issued.meta.intent))
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "claiming")

                still_live_core = HealthCore(
                    store,
                    lost_head,
                    execution_capability_vault=execution_vault,
                    writer_fence_vault=writer_vault,
                )
                still_live = HealthPlugin(still_live_core)
                self.assertIsNone(still_live.claim_effect_execution(issued.meta.intent))

                execution_vault.simulate_process_crash_for_test()
                first_core.close()
                still_live_core.close()
            finally:
                store.close()

            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        lost_head,
                        execution_capability_vault=execution_vault,
                        writer_fence_vault=writer_vault,
                    )
                )

                grant = recovered.claim_effect_execution(issued.meta.intent)

                self.assertIsNotNone(grant)
                self.assertEqual(reopened.effect_state(issued.meta["effect_id"]), "executing")
                self.assertEqual(grant.lease.effect_id, issued.meta["effect_id"])
            finally:
                reopened.close()

    def test_close_waits_for_inflight_cas_before_releasing_writer_holder(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "close-during-cas.sqlite")
            head = BlockingConditionalCurrentHead("synthetic-close-during-cas")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(head)
            store.seed_finalized_authority(self.authority_for(head))
            primary_core = HealthCore(
                store,
                head,
                execution_capability_vault=InMemoryExecutionCapabilityVault(),
                writer_fence_vault=writer_vault,
            )
            primary = HealthPlugin(primary_core)
            responses = []
            failures = []
            close_done = threading.Event()
            close_failures = []
            worker = threading.Thread(
                target=lambda: self._capture_worker_response(
                    responses,
                    failures,
                    lambda: primary.invoke(
                        self.command(
                            "state.commit",
                            "close-during-cas",
                            {
                                "record_id": "record-1",
                                "revision_digest": "sha256:revision-1",
                                "transition_id": "transition-1",
                                "writer_fence": head.read().head.writer_fence,
                            },
                        ),
                        peer_id="plugin",
                    ),
                )
            )
            closer = threading.Thread(
                target=lambda: self._capture_close(primary_core, close_done, close_failures)
            )
            standby_session = None
            try:
                payload = self.state_payload()
                self.assertEqual(
                    primary.invoke(self.command("state.candidate", "close-cas-candidate", payload), peer_id="plugin").status,
                    "accepted",
                )
                self.assertEqual(
                    primary.invoke(self.command("state.prepare", "close-cas-prepare", payload), peer_id="plugin").status,
                    "accepted",
                )

                worker.start()
                self.assertTrue(head.first_advance_checked.wait(timeout=1))
                closer.start()

                self.assertFalse(close_done.wait(timeout=0.1))
                standby_session = writer_vault.acquire_or_resume(
                    "synthetic-close-during-cas",
                    "synthetic-site",
                    WriterHolderClaim("standby-close-cas"),
                )
                self.assertIsNone(standby_session)
            finally:
                head.release_first_advance.set()
                if worker.ident is not None:
                    worker.join(timeout=2)
                if closer.ident is not None:
                    closer.join(timeout=2)
                if sys.exc_info()[0] is not None:
                    if standby_session is not None:
                        standby_session.release()
                    store.close()

            worker_alive = worker.is_alive()
            closer_alive = closer.is_alive()
            generation = head.read().head.generation
            guard = store.current_head_observation_guard()
            post_close_standby = writer_vault.acquire_or_resume(
                head.read().head.installation_id,
                head.read().head.site,
                WriterHolderClaim("standby-after-cas"),
            )
            post_close_standby_acquired = post_close_standby is not None
            if post_close_standby is not None:
                post_close_standby.release()
            store.close()
            self.assertFalse(worker_alive)
            self.assertFalse(closer_alive)
            self.assertEqual(failures, [])
            self.assertEqual(close_failures, [])
            self.assertEqual(len(responses), 1)
            self.assertEqual(responses[0].status, "accepted")
            self.assertEqual(generation, 2)
            self.assertIsNone(guard)
            self.assertTrue(post_close_standby_acquired)

    def test_close_reports_and_retries_a_failed_writer_handoff(self):
        for mode in ("raise", "noop"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                database = str(Path(directory) / f"failed-close-{mode}.sqlite")
                head = synthetic_head(installation_id=f"synthetic-failed-close-{mode}")
                store = EncryptedStateStore(database, self.key_provider)
                inner_vault = self.writer_vault_for(head)
                faulting_vault = FaultingWriterFenceVault(inner_vault, mode)
                store.seed_finalized_authority(self.authority_for(head))
                core = HealthCore(
                    store,
                    head,
                    execution_capability_vault=InMemoryExecutionCapabilityVault(),
                    writer_fence_vault=faulting_vault,
                )
                plugin = HealthPlugin(core)
                try:
                    self.assertEqual(plugin.probe().state, ProbeState.HEALTHY)

                    first = core.close()
                    standby = inner_vault.acquire_or_resume(
                        head.read().head.installation_id,
                        head.read().head.site,
                        WriterHolderClaim(f"standby-failed-close-{mode}"),
                    )

                    self.assertFalse(first.complete)
                    self.assertEqual(first.reason_code, "writer-handoff-incomplete")
                    self.assertEqual(plugin.probe().state, ProbeState.UNAVAILABLE)
                    self.assertIsNone(standby)

                    faulting_vault.mode = "pass"
                    second = core.close()
                    standby = inner_vault.acquire_or_resume(
                        head.read().head.installation_id,
                        head.read().head.site,
                        WriterHolderClaim(f"standby-retried-close-{mode}"),
                    )

                    self.assertTrue(second.complete)
                    self.assertIsNone(second.reason_code)
                    self.assertIsNotNone(standby)
                    standby.release()
                finally:
                    core.close()
                    store.close()

    def test_close_releases_execution_capability_for_same_host_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "execution-handoff.sqlite")
            head = synthetic_head(installation_id="synthetic-execution-handoff")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(head)
            execution_vault = InMemoryExecutionCapabilityVault()
            store.seed_finalized_authority(self.authority_for(head))
            first_core = HealthCore(
                store,
                head,
                execution_capability_vault=execution_vault,
                writer_fence_vault=writer_vault,
            )
            first = HealthPlugin(first_core)
            second_core = None
            try:
                issued_first = first.invoke(
                    self.command("effect.request", "handoff-first-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                first_grant = first.claim_effect_execution(issued_first.meta.intent)
                self.assertIsNotNone(first_grant)
                self.assertEqual(
                    first.invoke(
                        self.command(
                            "effect.result",
                            "handoff-first-result",
                            self.effect_result_payload(issued_first.meta, first_grant),
                        ),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                self.assertTrue(first_core.close().complete)

                second_core = HealthCore(
                    store,
                    head,
                    execution_capability_vault=execution_vault,
                    writer_fence_vault=writer_vault,
                )
                second = HealthPlugin(second_core)
                issued_second = second.invoke(
                    self.command("effect.request", "handoff-second-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                second_grant = second.claim_effect_execution(issued_second.meta.intent)

                self.assertNotEqual(second.probe().state, ProbeState.HEALTHY)
                self.assertIsNotNone(second_grant)
                self.assertEqual(store.effect_state(issued_second.meta["effect_id"]), "executing")
            finally:
                if second_core is not None:
                    second_core.close()
                first_core.close()
                store.close()

    def test_close_waits_for_inflight_effect_release_before_releasing_writer_holder(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "close-during-release.sqlite")
            head = synthetic_head(installation_id="synthetic-close-during-release")
            current_head = BlockingReleaseCurrentHead(head)
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(head)
            execution_vault = InMemoryExecutionCapabilityVault()
            store.seed_finalized_authority(self.authority_for(head))
            primary_core = HealthCore(
                store,
                current_head,
                execution_capability_vault=execution_vault,
                writer_fence_vault=writer_vault,
            )
            primary = HealthPlugin(primary_core)
            responses = []
            failures = []
            close_done = threading.Event()
            close_failures = []
            standby_session = None
            try:
                issued = primary.invoke(
                    self.command("effect.request", "close-release-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                self.assertEqual(issued.status, "accepted")
                grant = primary.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                result = self.command(
                    "effect.result",
                    "close-during-release",
                    self.effect_result_payload(issued.meta, grant),
                )
                worker = threading.Thread(
                    target=lambda: self._capture_worker_response(
                        responses,
                        failures,
                        lambda: primary.invoke(result, peer_id="plugin"),
                    )
                )
                closer = threading.Thread(
                    target=lambda: self._capture_close(primary_core, close_done, close_failures)
                )
                worker.start()
                self.assertTrue(current_head.release_started.wait(timeout=1))
                closer.start()

                self.assertFalse(close_done.wait(timeout=0.1))
                standby_session = writer_vault.acquire_or_resume(
                    head.read().head.installation_id,
                    head.read().head.site,
                    WriterHolderClaim("standby-close-release"),
                )
                self.assertIsNone(standby_session)
            finally:
                current_head.allow_release.set()
                if "worker" in locals() and worker.ident is not None:
                    worker.join(timeout=2)
                if "closer" in locals() and closer.ident is not None:
                    closer.join(timeout=2)

                if sys.exc_info()[0] is not None:
                    if standby_session is not None:
                        standby_session.release()
                    store.close()

            worker_alive = worker.is_alive()
            closer_alive = closer.is_alive()
            effect_state = store.effect_state(issued.meta["effect_id"])
            receipt = head.lookup_execution_lease(
                ExecutionLeaseIdentity(
                    expected=grant.lease.authority,
                    effect_id=grant.lease.effect_id,
                    intent_digest=grant.lease.intent_digest,
                    writer_fence=grant.lease.authority.writer_fence,
                    holder_id=grant.lease.holder_id,
                )
            )
            post_close_standby = writer_vault.acquire_or_resume(
                head.read().head.installation_id,
                head.read().head.site,
                WriterHolderClaim("standby-after-release"),
            )
            post_close_standby_acquired = post_close_standby is not None
            if post_close_standby is not None:
                post_close_standby.release()
            store.close()
            self.assertFalse(worker_alive)
            self.assertFalse(closer_alive)
            self.assertEqual(failures, [])
            self.assertEqual(close_failures, [])
            self.assertEqual(len(responses), 1)
            self.assertEqual(responses[0].status, "accepted")
            self.assertEqual(effect_state, "accepted")
            self.assertTrue(receipt.released)
            self.assertTrue(post_close_standby_acquired)

    def test_effect_result_lost_writer_proof_releases_its_unattempted_owner(self):
        issued = self.send(
            self.command("effect.request", "flip-proof-effect-intent", self.effect_request_payload())
        )
        grant = self.plugin.claim_effect_execution(issued.meta.intent)
        self.assertIsNotNone(grant)
        flaky = HealthPlugin(
            HealthCore(
                self.store,
                self.head,
                execution_capability_vault=self.execution_vault,
                writer_fence_vault=FlipWriterFenceVault(self.writer_vault),
            )
        )

        blocked = flaky.invoke(
            self.command(
                "effect.result",
                "flip-proof-first-result",
                self.effect_result_payload(issued.meta, grant),
            ),
            peer_id="plugin",
        )
        owner = self.send(
            self.command(
                "effect.result",
                "flip-proof-owner-result",
                self.effect_result_payload(issued.meta, grant),
            )
        )

        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.reason_code, "current-writer-holder-missing")
        self.assertIsNone(self.store.pending_effect_result(issued.meta["effect_id"]))
        self.assertEqual(owner.status, "accepted")

    def test_unclassified_post_cas_writer_validation_never_replays_historical_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "unclassified-post-cas-validation.sqlite")
            head = synthetic_head(installation_id="synthetic-unclassified-post-cas")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(head)
            store.seed_finalized_authority(self.authority_for(head))
            original = self.command("state.commit", "unclassified-post-cas-original", self.commit_payload())
            try:
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        CurrentHeadErrorAfterRemoteMutationValidationCurrentHead(head),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                payload = self.state_payload()
                self.assertEqual(
                    plugin.invoke(
                        self.command("state.candidate", "unclassified-post-cas-candidate", payload),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                self.assertEqual(
                    plugin.invoke(
                        self.command("state.prepare", "unclassified-post-cas-prepare", payload),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )

                first = plugin.invoke(original, peer_id="plugin")

                self.assertEqual(first.status, "unavailable")
                self.assertEqual(head.read().head.generation, 2)
                self.assertEqual(store.record_state("record-1"), "prepared")
                guard = store.current_head_observation_guard()
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
            finally:
                store.close()

            # A terminal old resource may be replaced externally before this
            # process can observe it.  A same-name H2 still has the historical
            # transition receipt, but it must not revive the old local commit.
            recreated = synthetic_head(installation_id="synthetic-unclassified-post-cas")
            self.advance_head(
                recreated,
                revision_digest="sha256:revision-1",
                transition_id="transition-1",
            )
            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        recreated,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(recreated),
                    )
                )

                replay = recovered.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(recreated.read().head.generation, 2)
                self.assertEqual(reopened.record_state("record-1"), "prepared")
                self.assert_all_effect_paths_closed(recovered)
            finally:
                reopened.close()

    def test_rejected_post_cas_writer_validation_never_replays_historical_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "rejected-post-cas-validation.sqlite")
            head = synthetic_head(installation_id="synthetic-rejected-post-cas")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(head)
            store.seed_finalized_authority(self.authority_for(head))
            original = self.command("state.commit", "rejected-post-cas-original", self.commit_payload())
            try:
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        CurrentHeadErrorAfterRemoteMutationValidationCurrentHead(
                            head,
                            reject_writer=True,
                        ),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                payload = self.state_payload()
                self.assertEqual(
                    plugin.invoke(
                        self.command("state.candidate", "rejected-post-cas-candidate", payload),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )
                self.assertEqual(
                    plugin.invoke(
                        self.command("state.prepare", "rejected-post-cas-prepare", payload),
                        peer_id="plugin",
                    ).status,
                    "accepted",
                )

                first = plugin.invoke(original, peer_id="plugin")

                self.assertEqual(first.status, "unavailable")
                self.assertEqual(first.reason_code, "current-writer-holder-missing")
                self.assertEqual(head.read().head.generation, 2)
                self.assertEqual(store.record_state("record-1"), "prepared")
                guard = store.current_head_observation_guard()
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
            finally:
                store.close()

            recreated = synthetic_head(installation_id="synthetic-rejected-post-cas")
            self.advance_head(
                recreated,
                revision_digest="sha256:revision-1",
                transition_id="transition-1",
            )
            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        recreated,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(recreated),
                    )
                )

                replay = recovered.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(reopened.record_state("record-1"), "prepared")
                self.assert_all_effect_paths_closed(recovered)
            finally:
                reopened.close()

    def test_unclassified_post_release_read_never_replays_historical_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "unclassified-post-release-read.sqlite")
            head = synthetic_head(installation_id="synthetic-unclassified-post-release-read")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(head)
            execution_vault = InMemoryExecutionCapabilityVault()
            store.seed_finalized_authority(self.authority_for(head))
            try:
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        CurrentHeadErrorAfterReleaseReadCurrentHead(head),
                        execution_capability_vault=execution_vault,
                        writer_fence_vault=writer_vault,
                    )
                )
                issued = plugin.invoke(
                    self.command("effect.request", "unclassified-post-release-read-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                grant = plugin.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                original = self.command(
                    "effect.result",
                    "unclassified-post-release-read-original",
                    self.effect_result_payload(issued.meta, grant),
                )

                first = plugin.invoke(original, peer_id="plugin")

                self.assertEqual(first.status, "unavailable")
                self.assertEqual(first.reason_code, "current-head-unavailable")
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                guard = store.current_head_observation_guard()
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
            finally:
                store.close()

            recreated = synthetic_head(installation_id="synthetic-unclassified-post-release-read")
            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        ForeignInstallationLeaseRecoveryCurrentHead(recreated, head),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(recreated),
                    )
                )

                replay = recovered.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(reopened.effect_state(original.payload.effect_id), "executing")
                self.assert_all_effect_paths_closed(recovered)
            finally:
                reopened.close()

    def test_unclassified_post_release_writer_validation_never_replays_historical_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "unclassified-post-release-validation.sqlite")
            head = synthetic_head(installation_id="synthetic-unclassified-post-release")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(head)
            execution_vault = InMemoryExecutionCapabilityVault()
            store.seed_finalized_authority(self.authority_for(head))
            try:
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        CurrentHeadErrorAfterRemoteMutationValidationCurrentHead(head),
                        execution_capability_vault=execution_vault,
                        writer_fence_vault=writer_vault,
                    )
                )
                issued = plugin.invoke(
                    self.command("effect.request", "unclassified-post-release-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                grant = plugin.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                original = self.command(
                    "effect.result",
                    "unclassified-post-release-original",
                    self.effect_result_payload(issued.meta, grant),
                )

                first = plugin.invoke(original, peer_id="plugin")

                self.assertEqual(first.status, "unavailable")
                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                guard = store.current_head_observation_guard()
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
            finally:
                store.close()

            # The recreated endpoint exposes the historical release receipt;
            # an unclassified validation failure must nevertheless keep it
            # outside any exact replay lane.
            recreated = synthetic_head(installation_id="synthetic-unclassified-post-release")
            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        ForeignInstallationLeaseRecoveryCurrentHead(recreated, head),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(recreated),
                    )
                )

                replay = recovered.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(reopened.effect_state(original.payload.effect_id), "executing")
                self.assert_all_effect_paths_closed(recovered)
            finally:
                reopened.close()

    def test_terminal_cas_handoff_failure_latches_before_same_h2_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "terminal-cas-handoff-latch.sqlite")
            head = synthetic_head(installation_id="synthetic-terminal-cas-handoff")
            store = TerminalHandoffFailureStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(head)
            store.seed_finalized_authority(self.authority_for(head))
            original = self.command(
                "state.commit",
                "terminal-cas-handoff-original",
                {
                    "record_id": "record-1",
                    "revision_digest": "sha256:revision-1",
                    "transition_id": "transition-1",
                    "writer_fence": "fence:1",
                },
            )
            try:
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        AdvanceThenTerminalCurrentHead(head),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                payload = self.state_payload()
                self.assertEqual(
                    plugin.invoke(self.command("state.candidate", "terminal-cas-handoff-candidate", payload), peer_id="plugin").status,
                    "accepted",
                )
                self.assertEqual(
                    plugin.invoke(self.command("state.prepare", "terminal-cas-handoff-prepare", payload), peer_id="plugin").status,
                    "accepted",
                )

                failed = plugin.invoke(original, peer_id="plugin")

                self.assertEqual(failed.status, "unavailable")
                self.assertEqual(failed.reason_code, "health-state-unavailable")
                self.assertEqual(head.read().head.generation, 2)
                self.assertTrue(store.terminal_observed())
                self.assertEqual(store.record_state("record-1"), "prepared")
            finally:
                store.close()

            recreated = synthetic_head(installation_id="synthetic-terminal-cas-handoff")
            self.advance_head(
                recreated,
                revision_digest="sha256:revision-1",
                transition_id="transition-1",
            )
            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        recreated,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(recreated),
                    )
                )

                replay = recovered.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-terminal")
                self.assertEqual(recreated.read().head.generation, 2)
                self.assertEqual(reopened.record_state("record-1"), "prepared")
                self.assert_all_effect_paths_closed(recovered)
            finally:
                reopened.close()

    def test_terminal_mutation_handoff_failure_never_retries_after_same_name_head_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "terminal-handoff-recovery.sqlite")
            original_head = synthetic_head(installation_id="synthetic-terminal-handoff")
            store = TerminalHandoffFailureStore(database, self.key_provider)
            store.seed_finalized_authority(self.authority_for(original_head))
            original = self.command("state.commit", "terminal-handoff-commit", self.commit_payload())
            try:
                plugin = HealthPlugin(
                    HealthCore(
                        store,
                        TerminalAtAdvanceCurrentHead(original_head),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(original_head),
                    )
                )
                payload = self.state_payload()
                self.assertEqual(
                    plugin.invoke(self.command("state.candidate", "terminal-handoff-candidate", payload), peer_id="plugin").status,
                    "accepted",
                )
                self.assertEqual(
                    plugin.invoke(self.command("state.prepare", "terminal-handoff-prepare", payload), peer_id="plugin").status,
                    "accepted",
                )

                failed = plugin.invoke(original, peer_id="plugin")

                self.assertEqual(failed.status, "unavailable")
                self.assertEqual(failed.reason_code, "health-state-unavailable")
                self.assertIsNotNone(store.current_head_observation_guard())
                self.assertTrue(store.terminal_observed())
            finally:
                store.close()

            recreated_head = synthetic_head(installation_id="synthetic-terminal-handoff")
            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        recreated_head,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(recreated_head),
                    )
                )

                replay = recovered.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-terminal")
                self.assertEqual(recreated_head.read().head.generation, 1)
                self.assertEqual(reopened.record_state("record-1"), "prepared")
                self.assertNotEqual(recovered.probe().state, ProbeState.HEALTHY)
                self.assert_all_effect_paths_closed(recovered)
            finally:
                reopened.close()

    def test_post_cas_terminal_crash_keeps_recreated_head_and_all_effect_gates_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "post-cas-terminal.sqlite")
            head = synthetic_head(installation_id="synthetic-post-cas-terminal")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(head)
            store.seed_finalized_authority(self.authority_for(head))
            original = self.command("state.commit", "post-cas-terminal-commit", self.commit_payload())
            try:
                plugin = HealthPlugin(
                    CrashBeforeTerminalLatchCore(
                        store,
                        TerminalAfterAdvanceReadCurrentHead(head),
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=writer_vault,
                    )
                )
                payload = self.state_payload()
                self.assertEqual(
                    plugin.invoke(self.command("state.candidate", "post-cas-terminal-candidate", payload), peer_id="plugin").status,
                    "accepted",
                )
                self.assertEqual(
                    plugin.invoke(self.command("state.prepare", "post-cas-terminal-prepare", payload), peer_id="plugin").status,
                    "accepted",
                )

                with self.assertRaises(SyntheticCrash):
                    plugin.invoke(original, peer_id="plugin")

                self.assertEqual(head.read().head.generation, 2)
                self.assertEqual(store.record_state("record-1"), "prepared")
                guard = store.current_head_observation_guard()
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
            finally:
                store.close()

            recreated = synthetic_head(installation_id="synthetic-post-cas-terminal")
            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        recreated,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(recreated),
                    )
                )

                replay = recovered.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(recreated.read().head.generation, 1)
                self.assertEqual(reopened.record_state("record-1"), "prepared")
                self.assert_all_effect_paths_closed(recovered)
            finally:
                reopened.close()

    def test_post_release_terminal_crash_keeps_recreated_head_and_all_effect_gates_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "post-release-terminal.sqlite")
            head = synthetic_head(installation_id="synthetic-post-release-terminal")
            store = EncryptedStateStore(database, self.key_provider)
            writer_vault = self.writer_vault_for(head)
            execution_vault = InMemoryExecutionCapabilityVault()
            store.seed_finalized_authority(self.authority_for(head))
            try:
                plugin = HealthPlugin(
                    CrashBeforeTerminalLatchCore(
                        store,
                        TerminalAfterReleaseLookupCurrentHead(head),
                        execution_capability_vault=execution_vault,
                        writer_fence_vault=writer_vault,
                    )
                )
                issued = plugin.invoke(
                    self.command("effect.request", "post-release-terminal-intent", self.effect_request_payload()),
                    peer_id="plugin",
                )
                grant = plugin.claim_effect_execution(issued.meta.intent)
                self.assertIsNotNone(grant)
                original = self.command(
                    "effect.result",
                    "post-release-terminal-result",
                    self.effect_result_payload(issued.meta, grant),
                )

                with self.assertRaises(SyntheticCrash):
                    plugin.invoke(original, peer_id="plugin")

                self.assertEqual(store.effect_state(issued.meta["effect_id"]), "executing")
                pending = store.pending_effect_result(issued.meta["effect_id"])
                self.assertIsNotNone(pending)
                self.assertTrue(pending.remote_attempted)
                guard = store.current_head_observation_guard()
                self.assertIsNotNone(guard)
                self.assertIsNone(guard.binding)
            finally:
                store.close()

            recreated = synthetic_head(installation_id="synthetic-post-release-terminal")
            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                recovered = HealthPlugin(
                    HealthCore(
                        reopened,
                        recreated,
                        execution_capability_vault=InMemoryExecutionCapabilityVault(),
                        writer_fence_vault=self.writer_vault_for(recreated),
                    )
                )

                replay = recovered.invoke(original, peer_id="plugin")

                self.assertEqual(replay.status, "unavailable")
                self.assertEqual(replay.reason_code, "current-head-observation-incomplete")
                self.assertEqual(reopened.effect_state(issued.meta["effect_id"]), "executing")
                self.assert_all_effect_paths_closed(recovered)
            finally:
                reopened.close()


def encode_raw_frame(value):
    body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return struct.pack(">I", len(body)) + body


if __name__ == "__main__":
    unittest.main()

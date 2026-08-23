"""Single-writer health-core state machine for Ticket 110."""

from __future__ import annotations

import hashlib
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Iterator, Protocol, TypeVar

from .admission import (
    MAX_MESSAGE_BODY_BYTES,
    AdmissionPolicy,
    NativeCursorDirective,
    SourceEnvelope,
    SourceReceipt,
)
from .authority import (
    AuthoritySnapshot,
    AuthorityValidationError,
    ClaimingEffect,
    CommittedTransition,
    ExecutionCapabilityBinding,
    EffectExecutionGrant,
    EffectIntent,
    ExecutingEffect,
    ExecutionLease,
    PreparedTransition,
    RevisionTarget,
    TerminalEffect,
    WriterHolderClaim,
    WriterFenceProof,
    holder_id_for,
    validate_opaque_text,
    validate_ticket110_effect_kind,
)
from .contract import (
    CommandEnvelope,
    CommitMeta,
    DailySourceMeta,
    DailyTurnPreparePayload,
    EffectIntentMeta,
    EffectRequestPayload,
    EffectResultPayload,
    InboundAdmitPayload,
    InitializationDisclosurePayload,
    InitializationPreparePayload,
    NativeCursorResultPayload,
    ProbeMeta,
    ProtocolViolation,
    Response,
    StateCandidatePayload,
    StateCommitPayload,
    canonicalize_command,
)
from .coordination import (
    DAILY_HEALTH_SKILL_NAMES,
    DailyHealthState,
    DailySkillAttestor,
    DailySkillBundle,
    DailyTurnDraft,
    DailyTurnResult,
)
from .initialization import (
    HealthInitAttestor,
    HealthInitAsset,
    InitialPortrait,
    InitializationDisclosure,
    InitializationDisclosureChallenge,
    InitializationDraft,
    InitializationProjection,
    MAX_RESOLVED_SOURCE_CAUSAL_IDS,
    OwnerConsentEvidence,
    OwnerInitialization,
    SkillUseProof,
    stable_digest,
)
from .current_head import (
    AdvanceRequest,
    AdvanceIdentity,
    AppliedTransition,
    CurrentHeadError,
    CurrentHeadPort,
    ExecutionLeaseIdentity,
    ExecutionLeaseNotFound,
    ExecutionLeaseReceipt,
    ExecutionLeaseRequest,
    ExecutionLeaseRelease,
    HeadConflict,
    HeadRead,
    HeadSnapshot,
    HeadTerminal,
    HeadTimeout,
    HeadUnknown,
    TransitionNotFound,
)
from .probe import ProbeReport, ProbeState
from .storage import (
    CausalIdConflict,
    CurrentHeadRecoveryBinding,
    DailyTurnTerminalReceipt,
    EncryptedStateStore,
    KeyUnavailable,
    StoreUnavailable,
)


_STATE_ACTIONS = frozenset({"state.candidate", "state.prepare", "state.commit", "state.finalize"})
_TRANSITION_RECOVERY_ACTIONS = frozenset({"state.commit", "state.finalize"})
_PROBE_BYPASS_ACTIONS = _TRANSITION_RECOVERY_ACTIONS | frozenset({"effect.result"})
_PERSISTENT_CLOSE_REASONS = frozenset(
    {"effect-result-unknown", "health-key-unavailable", "current-head-terminal"}
)
_MAX_HELD_INITIALIZATION_SOURCES = MAX_RESOLVED_SOURCE_CAUSAL_IDS + 1
_MAX_UNRESOLVED_INITIALIZATION_SOURCES = _MAX_HELD_INITIALIZATION_SOURCES + 1
_CurrentHeadValue = TypeVar("_CurrentHeadValue")


class MalformedCurrentHeadResponse(CurrentHeadError):
    """A port returned an invalid typed value, not a retryable I/O outcome."""


@dataclass(frozen=True)
class _Handled:
    response: Response
    persist_receipt: bool


@dataclass(frozen=True)
class DailyTurnStatus:
    """Core-owned recovery projection for one admitted daily source."""

    phase: str
    draft: DailyTurnDraft | None
    result: DailyTurnResult | None
    prepared_authority: AuthoritySnapshot
    terminal: DailyTurnTerminalReceipt | None = None

    def __post_init__(self) -> None:
        if self.phase not in {
            "prepared",
            "unknown",
            "committed",
            "evidence-finalized",
            "finalized",
        }:
            raise AuthorityValidationError("invalid daily turn phase")
        if self.phase == "finalized":
            if self.draft is not None or type(self.terminal) is not DailyTurnTerminalReceipt:
                raise AuthorityValidationError("invalid finalized daily turn status")
        elif type(self.draft) is not DailyTurnDraft or self.terminal is not None:
            raise AuthorityValidationError("invalid unresolved daily turn status")
        if self.result is not None and type(self.result) is not DailyTurnResult:
            raise AuthorityValidationError("invalid daily turn result")
        if type(self.prepared_authority) is not AuthoritySnapshot:
            raise AuthorityValidationError("invalid daily turn authority")

    @property
    def record_id(self) -> str:
        if self.draft is not None:
            return self.draft.record_id
        if self.terminal is None:
            raise AuthorityValidationError("daily terminal receipt required")
        return self.terminal.record_id

    @property
    def transition_id(self) -> str:
        if self.draft is not None:
            return self.draft.transition_id
        if self.terminal is None:
            raise AuthorityValidationError("daily terminal receipt required")
        return self.terminal.transition_id


@dataclass(frozen=True)
class DailyTurnRuntimePreparation:
    """Core-owned permission to form one draft under the lifecycle lock."""

    generation: int | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        ready = type(self.generation) is int and self.generation >= 0
        if ready != (self.reason_code is None):
            raise AuthorityValidationError("invalid daily runtime preparation")
        if self.reason_code not in {
            None,
            "daily-turn-busy",
            "daily-turn-recovery-required",
        }:
            raise AuthorityValidationError("invalid daily runtime preparation")

    @property
    def ready(self) -> bool:
        return self.generation is not None


@dataclass(frozen=True)
class _BoundRecoveryPreflightFailure:
    """A live recovery preflight result that is safe or unsafe to retry."""

    response: Response
    resumable_by_same_live_writer: bool


@dataclass(frozen=True)
class _WriterProofValidation:
    """Classify a local-closure writer check without losing its safety meaning."""

    proof: WriterFenceProof | None
    resumable_by_same_live_writer: bool


@dataclass(frozen=True)
class CloseReport:
    """Observable result of an orderly host-capability handoff attempt."""

    complete: bool
    reason_code: str | None = None
    failed_writer_namespaces: tuple[tuple[str, str], ...] = ()
    failed_execution_authorities: tuple[AuthoritySnapshot, ...] = ()

    def __post_init__(self) -> None:
        if type(self.complete) is not bool:
            raise ValueError("invalid close completion")
        if self.reason_code is not None and type(self.reason_code) is not str:
            raise ValueError("invalid close reason")


class ExecutionCapabilitySession(Protocol):
    """Host-private, exclusive capability holder for one authority domain."""

    def mint(self, binding: ExecutionCapabilityBinding) -> str | None: ...

    def recover(self, binding: ExecutionCapabilityBinding, holder_id: str) -> str | None: ...

    def active(self) -> bool: ...

    def release(self) -> None: ...


class ExecutionCapabilityVault(Protocol):
    """Non-SQLite holder for effect completion capabilities.

    A production implementation belongs in a host-bound secret facility.  It
    must issue one non-serialisable, exclusive session per current authority;
    it must not be copied with the encrypted health-state database.
    """

    def acquire_or_resume_session(
        self,
        authority: AuthoritySnapshot,
        writer_proof: WriterFenceProof,
    ) -> ExecutionCapabilitySession | None: ...


class WriterHolderSession(Protocol):
    """Host-private holder for one installation/site writer namespace."""

    def active(self) -> bool: ...

    def proof_for(self, authority: AuthoritySnapshot) -> WriterFenceProof | None: ...

    def release(self) -> None: ...


class WriterFenceVault(Protocol):
    """Host-private source of non-serialisable writer holder sessions."""

    def acquire_or_resume(
        self,
        installation_id: str,
        site: str,
        holder: WriterHolderClaim,
    ) -> WriterHolderSession | None: ...


class _InMemoryWriterHolderSession:
    """Synthetic host session; the raw capability remains in its vault."""

    def __init__(
        self,
        vault: "InMemoryWriterFenceVault",
        installation_id: str,
        site: str,
        holder: WriterHolderClaim,
    ) -> None:
        self._vault = vault
        self._installation_id = installation_id
        self._site = site
        self._holder = holder

    def active(self) -> bool:
        return self._vault._session_is_active(self)

    def proof_for(self, authority: AuthoritySnapshot) -> WriterFenceProof | None:
        if (
            not self.active()
            or
            not isinstance(authority, AuthoritySnapshot)
            or authority.installation_id != self._installation_id
            or authority.site != self._site
        ):
            return None
        return self._vault._proof_for(authority)

    def release(self) -> None:
        self._vault._release_session(self)


class InMemoryWriterFenceVault:
    """Synthetic host vault; raw writer capabilities never enter SQLite.

    A session proves possession of the installation/site host namespace before
    core consumes an exact response-loss binding.  It can then mint a proof
    for the *live* fence read after that binding becomes generic.  Neither the
    session nor its capability is serialised, exposed through Plugin, or sent
    through the command protocol.
    """

    def __init__(self) -> None:
        self._capabilities: dict[tuple[str, str, str], str] = {}
        self._sessions: dict[tuple[str, str], _InMemoryWriterHolderSession] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(authority: AuthoritySnapshot) -> tuple[str, str, str]:
        return (authority.installation_id, authority.site, authority.writer_fence)

    def bind(self, authority: AuthoritySnapshot, capability: str) -> None:
        if not isinstance(authority, AuthoritySnapshot):
            raise ValueError("invalid writer authority")
        with self._lock:
            self._capabilities[self._key(authority)] = capability

    def acquire_or_resume(
        self,
        installation_id: str,
        site: str,
        holder: WriterHolderClaim,
    ) -> WriterHolderSession | None:
        if (
            not isinstance(installation_id, str)
            or not installation_id
            or not isinstance(site, str)
            or not site
            or not isinstance(holder, WriterHolderClaim)
        ):
            return None
        namespace = (installation_id, site)
        with self._lock:
            if not any(key[:2] == namespace for key in self._capabilities):
                return None
            session = self._sessions.get(namespace)
            if session is not None and session.active():
                return session if session._holder == holder else None
            session = _InMemoryWriterHolderSession(self, installation_id, site, holder)
            self._sessions[namespace] = session
            return session

    def _session_is_active(self, session: _InMemoryWriterHolderSession) -> bool:
        with self._lock:
            return self._sessions.get((session._installation_id, session._site)) is session

    def _release_session(self, session: _InMemoryWriterHolderSession) -> None:
        with self._lock:
            namespace = (session._installation_id, session._site)
            if self._sessions.get(namespace) is session:
                self._sessions.pop(namespace, None)

    def _proof_for(self, authority: AuthoritySnapshot) -> WriterFenceProof | None:
        if not isinstance(authority, AuthoritySnapshot) or authority.terminal:
            return None
        with self._lock:
            capability = self._capabilities.get(self._key(authority))
        if capability is None:
            return None
        return WriterFenceProof(authority=authority, capability=capability)


class _InMemoryExecutionCapabilitySession:
    """Synthetic exclusive session; production uses a host secret facility."""

    def __init__(
        self,
        vault: "InMemoryExecutionCapabilityVault",
        authority: AuthoritySnapshot,
        holder_key: str,
    ) -> None:
        self._vault = vault
        self._authority = authority
        self._holder_key = holder_key

    def mint(self, binding: ExecutionCapabilityBinding) -> str | None:
        if binding.authority != self._authority:
            return None
        return self._vault._mint(self, binding)

    def recover(self, binding: ExecutionCapabilityBinding, holder_id: str) -> str | None:
        if binding.authority != self._authority:
            return None
        return self._vault._recover(self, binding, holder_id)

    def active(self) -> bool:
        return self._vault._session_is_active(self)

    def release(self) -> None:
        self._vault._release_session(self)


class InMemoryExecutionCapabilityVault:
    """Synthetic host-local vault used by the Ticket 110 harness.

    The durable secret namespace (capabilities and writer-holder fingerprint)
    outlives an individual core instance.  The active session does not: it is
    an exclusive process lease.  A second live core cannot obtain it, while a
    test-only crash hook models an OS-owned lease being released on process
    death so the same host can recover an acquire response loss.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[AuthoritySnapshot, _InMemoryExecutionCapabilitySession] = {}
        self._holder_keys: dict[AuthoritySnapshot, str] = {}
        self._capabilities: dict[ExecutionCapabilityBinding, tuple[str, str]] = {}

    @staticmethod
    def _holder_key(proof: WriterFenceProof) -> str | None:
        if not isinstance(proof, WriterFenceProof):
            return None
        return hashlib.sha256(proof.capability.encode("utf-8")).hexdigest()

    def acquire_or_resume_session(
        self,
        authority: AuthoritySnapshot,
        writer_proof: WriterFenceProof,
    ) -> ExecutionCapabilitySession | None:
        if (
            not isinstance(authority, AuthoritySnapshot)
            or authority.terminal
            or not isinstance(writer_proof, WriterFenceProof)
            or writer_proof.authority != authority
        ):
            return None
        holder_key = self._holder_key(writer_proof)
        if holder_key is None:
            return None
        with self._lock:
            registered = self._holder_keys.get(authority)
            if registered is not None and not secrets.compare_digest(registered, holder_key):
                return None
            if authority in self._sessions:
                # Never hand a live core's completion capability to another
                # in-process core.  A true process death releases this lease.
                return None
            self._holder_keys[authority] = holder_key
            session = _InMemoryExecutionCapabilitySession(self, authority, holder_key)
            self._sessions[authority] = session
            return session

    def _mint(
        self,
        session: _InMemoryExecutionCapabilitySession,
        binding: ExecutionCapabilityBinding,
    ) -> str | None:
        with self._lock:
            if not self._session_is_active(session):
                return None
            existing = self._capabilities.get(binding)
            if existing is not None:
                holder_key, capability = existing
                return capability if secrets.compare_digest(holder_key, session._holder_key) else None
            capability = secrets.token_urlsafe(32)
            self._capabilities[binding] = (session._holder_key, capability)
            return capability

    def _recover(
        self,
        session: _InMemoryExecutionCapabilitySession,
        binding: ExecutionCapabilityBinding,
        holder_id: str,
    ) -> str | None:
        with self._lock:
            if not self._session_is_active(session):
                return None
            existing = self._capabilities.get(binding)
            if existing is None:
                return None
            holder_key, capability = existing
            if (
                not secrets.compare_digest(holder_key, session._holder_key)
                or holder_id_for(capability) != holder_id
            ):
                return None
            return capability

    def _session_is_active(self, session: _InMemoryExecutionCapabilitySession) -> bool:
        with self._lock:
            return self._sessions.get(session._authority) is session

    def _release_session(self, session: _InMemoryExecutionCapabilitySession) -> None:
        with self._lock:
            if self._sessions.get(session._authority) is session:
                self._sessions.pop(session._authority, None)

    def simulate_process_crash_for_test(self) -> None:
        """Release synthetic process leases but retain host-private secrets."""

        with self._lock:
            self._sessions.clear()


class HealthCore:
    def __init__(
        self,
        store: EncryptedStateStore,
        current_head: CurrentHeadPort,
        *,
        execution_capability_vault: ExecutionCapabilityVault | None = None,
        writer_fence_vault: WriterFenceVault | None = None,
        admission_policy: AdmissionPolicy | None = None,
        health_init_verifier: HealthInitAttestor | None = None,
        health_init_asset: HealthInitAsset | None = None,
        daily_skill_verifier: DailySkillAttestor | None = None,
        daily_skill_bundle: DailySkillBundle | None = None,
    ) -> None:
        self._store = store
        self._current_head = current_head
        self._closed_reason: str | None = None
        # No fallback vault is safe: a host must explicitly inject its private,
        # non-serialisable capability authority before the core may execute an
        # intent.  SQLite stores only a holder hash and a public claim reference.
        self._execution_capability_vault = execution_capability_vault
        # No default writer proof is safe.  A copied database and a copied
        # public fence string are intentionally insufficient to probe healthy,
        # advance current-head, acquire an execution lease, or release one.
        self._writer_fence_vault = writer_fence_vault
        self._admission_policy = admission_policy
        self._health_init_verifier = health_init_verifier
        self._health_init_asset = health_init_asset
        self._daily_skill_verifier = daily_skill_verifier
        self._daily_skill_bundle = daily_skill_bundle
        self._writer_holder_claim = WriterHolderClaim(
            "writer-holder:" + secrets.token_urlsafe(24)
        )
        self._writer_holder_sessions: dict[tuple[str, str], WriterHolderSession] = {}
        # Serializes lifecycle handoff with every public operation that can
        # mint or consume a writer proof.  ``close`` must not release its host
        # holder while an already-admitted CAS or lease release still carries
        # a valid proof to current-head.
        self._lifecycle_lock = threading.RLock()
        self._closed = False
        self._execution_capability_sessions: dict[AuthoritySnapshot, ExecutionCapabilitySession] = {}
        self._terminal_seen = False
        self._current_head_guard_depth = 0
        self._current_head_guard_binding: CurrentHeadRecoveryBinding | None = None
        # A mutable current-head call whose response may have been lost keeps
        # its exact recovery binding durable.  A generic guard is deliberately
        # kept for every other interrupted observation: only the former can
        # ever be closed by replaying the original causal command.
        self._current_head_guard_preserved = False
        # A failed clear can leave our own durable guard behind even though
        # this process is still alive.  Retain that provenance in memory so a
        # recovered store can clear it; a restarted core has no such proof and
        # therefore remains fail-closed.
        self._current_head_guard_owned = False

    def close(self) -> CloseReport:
        """Disable this core and report whether host authority really handed off.

        The core becomes unusable on the first call even when a host release
        faults.  Failed sessions remain retained solely so a later ``close``
        can retry their release; callers must not mistake a disabled old core
        for a completed writer/capability handoff.
        """

        with self._lifecycle_lock:
            # The lifecycle lock first drains every admitted public operation.
            # Only then can a new core acquire the namespace, so no old
            # WriterFenceProof remains usable after orderly handoff.
            self._closed = True
            failed_writer: list[tuple[str, str]] = []
            for namespace, session in tuple(self._writer_holder_sessions.items()):
                if self._release_host_session(session):
                    self._writer_holder_sessions.pop(namespace, None)
                else:
                    failed_writer.append(namespace)

            failed_execution: list[AuthoritySnapshot] = []
            for authority, session in tuple(self._execution_capability_sessions.items()):
                if self._release_host_session(session):
                    self._execution_capability_sessions.pop(authority, None)
                else:
                    failed_execution.append(authority)

            if failed_writer:
                return CloseReport(
                    complete=False,
                    reason_code="writer-handoff-incomplete",
                    failed_writer_namespaces=tuple(failed_writer),
                    failed_execution_authorities=tuple(failed_execution),
                )
            if failed_execution:
                return CloseReport(
                    complete=False,
                    reason_code="execution-capability-handoff-incomplete",
                    failed_execution_authorities=tuple(failed_execution),
                )
            return CloseReport(complete=True)

    @staticmethod
    def _release_host_session(session: object) -> bool:
        """Prove that a host session no longer holds its namespace."""

        if not callable(getattr(session, "release", None)) or not callable(getattr(session, "active", None)):
            return False
        try:
            session.release()
        except Exception:
            return False
        try:
            return session.active() is False
        except Exception:
            return False

    def _current_writer_proof(self, authority: AuthoritySnapshot) -> WriterFenceProof | None:
        """Return a host proof only after the remote adapter validates it live."""

        return self._current_writer_proof_validation(authority).proof

    def _current_writer_proof_validation(
        self,
        authority: AuthoritySnapshot,
    ) -> _WriterProofValidation:
        """Keep explicit nonterminal validation loss distinct from malformed I/O.

        A local business/receipt close may restore its exact recovery binding
        only when the validation failure itself proves no terminal or malformed
        adapter result was observed.  Conflating those cases would make a
        response-lost CAS or lease release replayable after an unsafe remote
        boundary.
        """

        proof = self._writer_proof_from_vault(authority)
        if proof is None:
            # This is a host-local absence; no current-head observation was
            # made, so the same live holder may later retry its local close.
            return _WriterProofValidation(None, resumable_by_same_live_writer=True)
        try:
            # The port gets a disposable copy.  Retain an independent proof
            # for any later CAS/lease operation so a validator cannot mutate
            # the authority or bearer field it was asked to inspect.
            port_proof = self._canonical_writer_proof_for_port(proof)
            retained_proof = self._canonical_writer_proof_for_port(proof)
        except CurrentHeadError:
            return _WriterProofValidation(None, resumable_by_same_live_writer=False)
        try:
            valid = self._guard_current_head_call(
                lambda: self._current_head.validate_writer_fence(port_proof)
            )
        except HeadTerminal:
            self._latch_terminal()
            return _WriterProofValidation(None, resumable_by_same_live_writer=False)
        except (HeadConflict, HeadTimeout, HeadUnknown):
            return _WriterProofValidation(None, resumable_by_same_live_writer=True)
        except CurrentHeadError:
            return _WriterProofValidation(None, resumable_by_same_live_writer=False)
        except Exception:
            return _WriterProofValidation(None, resumable_by_same_live_writer=False)
        if valid is True:
            return _WriterProofValidation(retained_proof, resumable_by_same_live_writer=False)
        if valid is False:
            # A decoded false is a definite live-fence rejection.  It cannot
            # reopen an exact post-mutation closure binding.
            return _WriterProofValidation(None, resumable_by_same_live_writer=False)
        return _WriterProofValidation(None, resumable_by_same_live_writer=False)

    def _writer_proof_from_vault(self, authority: AuthoritySnapshot) -> WriterFenceProof | None:
        """Mint an exact fence proof from a host session without remote I/O."""

        session = self._writer_holder_session(authority)
        if session is None:
            return None
        try:
            proof = session.proof_for(authority)
        except Exception:
            return None
        if type(proof) is not WriterFenceProof or type(proof.authority) is not AuthoritySnapshot:
            return None
        try:
            canonical = self._canonical_writer_proof_for_port(proof)
        except CurrentHeadError:
            return None
        if canonical.authority != authority:
            return None
        return canonical

    def _writer_holder_session(self, authority: AuthoritySnapshot) -> WriterHolderSession | None:
        """Return a local holder session without reading or writing current-head."""

        if self._closed or not isinstance(authority, AuthoritySnapshot) or authority.terminal:
            return None
        vault = self._writer_fence_vault
        if vault is None:
            return None
        namespace = (authority.installation_id, authority.site)
        cached = self._writer_holder_sessions.get(namespace)
        if cached is not None:
            try:
                if cached.active():
                    return cached
            except Exception:
                pass
            self._writer_holder_sessions.pop(namespace, None)
        try:
            session = vault.acquire_or_resume(
                authority.installation_id,
                authority.site,
                self._writer_holder_claim,
            )
        except Exception:
            return None
        if (
            session is None
            or not callable(getattr(session, "active", None))
            or not callable(getattr(session, "proof_for", None))
            or not callable(getattr(session, "release", None))
        ):
            return None
        try:
            if not session.active():
                return None
        except Exception:
            return None
        self._writer_holder_sessions[namespace] = session
        return session

    def _writer_entry_preflight(self, causal_id: str | None = None) -> Response | None:
        """Require a host-local writer credential before arming any tripwire.

        A core that merely holds a copied SQLite file must not be able to write
        a generic current-head crash guard and die before its first remote read.
        The finalized authority is local encrypted state, so this check neither
        observes current-head nor creates a terminal-observation hazard.  The
        later guarded live validation remains mandatory before every mutation.
        """

        authority = self._store.finalized_authority()
        if authority is None:
            return Response("unavailable", causal_id, "local-finalized-authority-missing")
        if self._writer_holder_session(authority) is None:
            return Response("unavailable", causal_id, "current-writer-holder-missing")
        return None

    def _bound_recovery_local_writer_preflight(
        self,
        expected_authority: AuthoritySnapshot,
    ) -> Response | None:
        """Require host-local ownership before touching an exact guard.

        A copied SQLite file must not be able to consume an exact ambiguous
        mutation binding merely by attempting recovery.  This check is purely
        local: it neither observes current-head nor changes the durable guard.
        """

        if not isinstance(expected_authority, AuthoritySnapshot):
            return Response("unavailable", reason_code="current-head-observation-incomplete")
        if self._writer_holder_session(expected_authority) is None:
            return Response("unavailable", reason_code="current-writer-holder-missing")
        return None

    def _bound_recovery_live_writer_preflight(
        self,
        expected_authority: AuthoritySnapshot,
        *,
        installation_mismatch_reason: str,
        site_mismatch_reason: str,
        writer_fence_mismatch_reason: str,
    ) -> AuthoritySnapshot | _BoundRecoveryPreflightFailure:
        """Validate live authority only after exact recovery became generic.

        Callers must first pass the host-local proof check and atomically move
        the exact response-loss binding to a generic tripwire.  A terminal
        observation or hard stop here can therefore never leave the old CAS or
        release replayable.  Only a *returned*, explicitly nonterminal
        transport/validation failure may later restore that exact binding in
        the same live core.
        """

        try:
            authority = self._read_head()
        except HeadTerminal:
            self._latch_terminal()
            return _BoundRecoveryPreflightFailure(
                Response("unavailable", reason_code=self._closed_reason),
                resumable_by_same_live_writer=False,
            )
        except HeadUnknown:
            return _BoundRecoveryPreflightFailure(
                Response("unknown", reason_code="current-head-unknown"),
                resumable_by_same_live_writer=True,
            )
        except (HeadConflict, HeadTimeout):
            return _BoundRecoveryPreflightFailure(
                Response("unavailable", reason_code="current-head-unavailable"),
                resumable_by_same_live_writer=True,
            )
        except CurrentHeadError:
            # An invalid or unclassified adapter response is not evidence that
            # current-head was nonterminal.  Retain the generic tripwire.
            return _BoundRecoveryPreflightFailure(
                Response("unavailable", reason_code="current-head-unavailable"),
                resumable_by_same_live_writer=False,
            )

        # A response-loss binding belongs to one installation/site namespace.
        # A different current writer must not consume it and terminalize copied
        # business state merely because a lease/transition lookup still returns
        # a historical receipt from the old namespace.
        if authority.installation_id != expected_authority.installation_id:
            return _BoundRecoveryPreflightFailure(
                Response("unavailable", reason_code=installation_mismatch_reason),
                resumable_by_same_live_writer=False,
            )
        if authority.site != expected_authority.site:
            return _BoundRecoveryPreflightFailure(
                Response("unavailable", reason_code=site_mismatch_reason),
                resumable_by_same_live_writer=False,
            )
        if authority.writer_fence != expected_authority.writer_fence:
            # A response-loss binding is tied to the exact writer fence that
            # owned the CAS or release.  Installation/site continuity alone
            # is not an authenticated F1-to-F2 handoff proof.
            return _BoundRecoveryPreflightFailure(
                Response("unavailable", reason_code=writer_fence_mismatch_reason),
                resumable_by_same_live_writer=False,
            )

        # Use the same disposable port proof / retained proof discipline as
        # ordinary writes.  Recovery must not be the one path that lets a
        # validator mutate a vault-owned authority or bearer object.
        validation = self._current_writer_proof_validation(authority)
        if validation.proof is None:
            return _BoundRecoveryPreflightFailure(
                Response("unavailable", reason_code="current-writer-holder-missing"),
                resumable_by_same_live_writer=validation.resumable_by_same_live_writer,
            )
        return authority

    def _latch_terminal(self) -> None:
        # Set the in-process latch first.  A transient local storage failure
        # after observing terminal must never let a later nonterminal read
        # reopen the same core while durable latching is retried.
        self._terminal_seen = True
        try:
            self._store.latch_terminal_observation()
        except KeyUnavailable:
            self._closed_reason = "health-key-unavailable"
        except StoreUnavailable:
            self._closed_reason = "health-state-unavailable"
        else:
            self._closed_reason = "current-head-terminal"

    def _terminal_closed(self) -> bool:
        if self._terminal_seen:
            self._latch_terminal()
            return True
        if self._current_head_guard_owned and self._current_head_guard_depth == 0:
            if self._current_head_guard_preserved:
                self._closed_reason = "current-head-observation-incomplete"
                return True
            # The prior guarded call definitely returned in this live core.
            # Retrying a failed clear is safe here; after process loss this
            # provenance disappears and the persisted guard below closes the
            # new core instead.
            self._store.clear_current_head_observation(self._current_head_guard_binding)
            self._current_head_guard_owned = False
            self._current_head_guard_binding = None
        if self._store.terminal_observed():
            self._terminal_seen = True
            self._closed_reason = "current-head-terminal"
            return True
        # A guard owned by this live core protects the current operation.  Only
        # an orphaned durable guard (with no matching in-process depth) proves
        # that a previous current-head observation was interrupted by a crash.
        if (
            self._current_head_guard_depth == 0
            and self._store.current_head_observation_incomplete()
        ):
            self._closed_reason = "current-head-observation-incomplete"
            return True
        return False

    def _enter_current_head_guard(
        self,
        binding: CurrentHeadRecoveryBinding | None = None,
    ) -> None:
        self._store.arm_current_head_observation(binding)
        self._current_head_guard_owned = True
        self._current_head_guard_binding = binding
        if self._current_head_guard_depth == 0:
            self._current_head_guard_preserved = False
        self._current_head_guard_depth += 1

    def _exit_current_head_guard(self) -> None:
        if self._current_head_guard_depth < 1:
            raise StoreUnavailable("current-head observation guard underflow")
        self._current_head_guard_depth -= 1
        if (
            self._current_head_guard_depth == 0
            and not self._terminal_seen
            and not self._current_head_guard_preserved
            and self._current_head_guard_owned
        ):
            self._store.clear_current_head_observation(self._current_head_guard_binding)
            self._current_head_guard_owned = False
            self._current_head_guard_binding = None

    def _retarget_current_head_guard(
        self,
        binding: CurrentHeadRecoveryBinding | None,
    ) -> None:
        """Durably move a live tripwire between observation phases.

        A command-specific binding is valid only while its one mutable remote
        call is in flight.  The caller must therefore enter with the generic
        guard, bind immediately before the call, then restore generic before
        any post-write read or local business transaction.
        """

        if self._current_head_guard_depth < 1:
            raise StoreUnavailable("current-head observation guard is not active")
        if self._current_head_guard_binding == binding:
            return
        self._store.replace_current_head_observation(
            self._current_head_guard_binding,
            binding,
        )
        self._current_head_guard_binding = binding

    def _begin_interrupted_current_head_recovery(
        self,
        binding: CurrentHeadRecoveryBinding,
    ) -> None:
        """Consume a mutable-call binding before any recovery observation.

        If recovery itself crashes, its generic guard remains deliberately
        non-recoverable.  In particular a terminal read after a successful CAS
        can never be mistaken for permission to replay that earlier CAS.
        """

        self._store.replace_current_head_observation(binding, None)
        self._current_head_guard_binding = None
        self._current_head_guard_owned = True
        self._current_head_guard_preserved = False
        self._current_head_guard_depth += 1

    def _restore_recovery_binding_after_returned_preflight_failure(
        self,
        binding: CurrentHeadRecoveryBinding,
        *,
        still_owned: Callable[[], bool],
    ) -> None:
        """Rebind only after a known nonterminal preflight result returned.

        The exact binding has already become generic before this method runs.
        This is intentionally narrower than general recovery: transition and
        lease lookup results remain generic once observed, because they can
        close response-loss ambiguity.  A returned timeout/unknown or a
        decoded nonterminal writer-proof rejection is the only phase in which
        the same live writer may safely retry the preflight.
        """

        # Preserve generic protection by default.  If this local state changed
        # or the retarget write fails, a later call must not clear the tripwire.
        self._current_head_guard_preserved = True
        if self._terminal_seen or not still_owned():
            return
        self._current_head_guard_depth += 1
        try:
            self._retarget_current_head_guard(binding)
        finally:
            self._current_head_guard_depth -= 1

    def _preserve_exact_local_closure_binding(
        self,
        binding: CurrentHeadRecoveryBinding,
    ) -> None:
        """Bind only the original command around an already-confirmed local close."""

        self._current_head_guard_preserved = True
        self._retarget_current_head_guard(binding)

    def _retain_local_closure_guard_after_writer_validation(
        self,
        binding: CurrentHeadRecoveryBinding,
        validation: _WriterProofValidation,
    ) -> None:
        """Retain B only after an explicitly nonterminal validation failure."""

        if validation.resumable_by_same_live_writer and not self._terminal_seen:
            self._preserve_exact_local_closure_binding(binding)
            return
        # An invalid adapter response, unexpected exception, or terminal
        # observation has consumed the safe replay lane.  Keep generic guard
        # through the caller's finally block and across process loss.
        self._current_head_guard_preserved = True

    def _state_recovery_binding_still_owned(
        self,
        command: CommandEnvelope,
        prepared: PreparedTransition,
    ) -> bool:
        payload = command.payload
        if not isinstance(payload, StateCommitPayload):
            return False
        stored = self._store.record(payload.record_id)
        pending = self._store.pending_for_record(payload.record_id)
        return (
            stored is not None
            and stored.state in {"prepared", "unknown"}
            and stored.payload == prepared
            and pending is not None
            and pending.remote_attempted
            and pending.command.to_wire() == command.to_wire()
        )

    def _effect_recovery_binding_still_owned(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
    ) -> bool:
        payload = command.payload
        if not isinstance(payload, EffectResultPayload):
            return False
        stored = self._store.effect(payload.effect_id)
        pending = self._store.pending_effect_result(payload.effect_id)
        if (
            stored is None
            or stored.state != "executing"
            or stored.payload != execution
            or pending is None
            or not pending.remote_attempted
        ):
            return False
        try:
            return pending.matches(command, execution)
        except ProtocolViolation:
            return False

    def handle(self, command: CommandEnvelope) -> Response:
        """Apply one command, atomically recording its exact terminal replay response."""

        with self._lifecycle_lock:
            if self._closed:
                # Do not derive a response field from a direct caller object
                # after orderly shutdown; the core no longer owns a writer
                # namespace and must not reopen it just to replay a receipt.
                return Response("unavailable", reason_code="current-writer-holder-missing")
            return self._handle_open(command)

    def _handle_open(self, command: CommandEnvelope) -> Response:
        """Run one admitted command while its writer holder remains live."""

        try:
            command = canonicalize_command(command)
        except ProtocolViolation:
            # The object itself is untrusted, including its causal ID.  Do not
            # derive a receipt, pending journal, or response field from it.
            return Response("rejected", reason_code="invalid-command-envelope")

        try:
            with self._store.serialized():
                with self._store.transaction():
                    previous = self._store.receipt(command)
                    if previous is not None:
                        guard = self._store.current_head_observation_guard()
                        if guard is not None and guard.binding is not None and guard.binding.matches(command):
                            self._store.clear_current_head_observation(guard.binding)
                        return previous
                    # An unresolved remote operation reserves its causal ID for
                    # the exact original command until transition lookup closes
                    # it.  This only validates an existing reservation; a new
                    # state.commit reservation is durably written below.
                    self._store.pending_command(command)

                # A completed terminal latch outranks any residual tripwire:
                # the latter may remain because the terminal path deliberately
                # avoids clearing it, but it must never mask the irreversible
                # terminal result on replay or after restart.
                if self._store.terminal_observed():
                    self._terminal_seen = True
                    self._closed_reason = "current-head-terminal"
                    return Response("unavailable", command.causal_id, self._closed_reason)

                if command.action == "turn.prepare":
                    with self._store.transaction():
                        lease_handled = self._daily_turn_lease_response(command)
                        if lease_handled is not None:
                            if lease_handled.persist_receipt:
                                self._store.save_receipt(command, lease_handled.response)
                            return lease_handled.response

                interrupted = self._store.current_head_observation_guard()
                if interrupted is not None:
                    return self._recover_interrupted_current_head_observation(command, interrupted.binding)

                if self._terminal_closed():
                    return Response("unavailable", command.causal_id, self._closed_reason)

                writer_entry = self._writer_entry_preflight(command.causal_id)
                if writer_entry is not None:
                    return writer_entry

                preflight = self._prewrite_remote_journal(command)
                if preflight is not None:
                    return preflight

                if command.action == "state.commit":
                    return self._handle_state_commit_remote(command)
                if command.action == "effect.result":
                    return self._handle_effect_result_remote(command)

                # Commit a *generic* observation tripwire before entering the
                # command.  The exact causal binding is installed later, in a
                # separately committed phase immediately around CAS/release;
                # it must never cover a post-write confirmation read.
                self._enter_current_head_guard()
                try:
                    with self._store.transaction():
                        # The journal write is deliberately a separate committed
                        # transaction before CAS.  Recheck receipt afterward so an
                        # independently completed replay remains exact.
                        previous = self._store.receipt(command)
                        if previous is not None:
                            return previous
                        handled = self._handle_new(command)
                        if handled.persist_receipt:
                            self._store.save_receipt(command, handled.response)
                    return handled.response
                finally:
                    self._exit_current_head_guard()
        except ProtocolViolation as exc:
            return self._persist_rejection(command, str(exc))
        except CausalIdConflict as exc:
            return Response("rejected", command.causal_id, str(exc) or "causal-id-conflict")
        except KeyUnavailable:
            self._closed_reason = "health-key-unavailable"
            return Response("unavailable", command.causal_id, self._closed_reason)
        except StoreUnavailable:
            self._closed_reason = "health-state-unavailable"
            return Response("unavailable", command.causal_id, self._closed_reason)

    def _handle_state_commit_remote(self, command: CommandEnvelope) -> Response:
        """Complete a state commit without holding SQLite across remote CAS.

        The three durable phases are deliberately explicit:

        ``generic -> exact command binding -> generic -> exact command
        binding -> local record/receipt/guard clear``.

        The first bound phase covers only CAS response ambiguity.  The second
        starts after all post-CAS reads are complete, so a failed local commit
        remains recoverable without allowing a terminal confirmation read to
        replay the old CAS.
        """

        payload = command.payload
        if not isinstance(payload, StateCommitPayload):
            raise ProtocolViolation("invalid commit payload")
        # Terminal observation outranks a stale envelope.  Perform this read
        # before validating the prepared generation/fence so a terminal head
        # can never be reported as a protocol rejection.
        try:
            preflight_head = self._read_head()
        except HeadTerminal:
            self._latch_terminal()
            return Response("unavailable", command.causal_id, self._closed_reason)
        except HeadUnknown:
            return Response("unknown", command.causal_id, "current-head-unknown")
        except (HeadConflict, HeadTimeout, CurrentHeadError):
            return Response("unavailable", command.causal_id, "current-head-unavailable")
        stored = self._store.record(payload.record_id)
        if stored is None or stored.state not in {"prepared", "unknown"}:
            raise ProtocolViolation("record is not prepared")
        if not isinstance(stored.payload, PreparedTransition):
            raise KeyUnavailable("invalid prepared state")
        prepared = stored.payload
        if not prepared.target.matches_commit(
            record_id=payload.record_id,
            revision_digest=payload.revision_digest,
            transition_id=payload.transition_id,
        ):
            raise ProtocolViolation("record transition changed")
        if (
            command.generation != prepared.base.generation
            or payload.writer_fence != prepared.base.writer_fence
        ):
            if command.generation == preflight_head.generation:
                mismatch = self._prepared_mismatch_reason(
                    prepared.base,
                    preflight_head,
                    payload.writer_fence,
                )
                if mismatch is not None:
                    self._closed_reason = mismatch
                    return Response("unavailable", command.causal_id, mismatch)
            raise ProtocolViolation("generation mismatch")
        pending = self._store.pending_for_record(payload.record_id)
        if pending is None:
            return Response("unavailable", command.causal_id, "pending-command-missing")
        if pending.command.to_wire() != command.to_wire():
            return Response("rejected", command.causal_id, "causal-id-conflict")
        if not pending.remote_attempted:
            return Response("unavailable", command.causal_id, "pending-command-not-attempted")

        binding = CurrentHeadRecoveryBinding.from_command(command)
        self._enter_current_head_guard()
        try:
            try:
                head = self._read_head()
            except HeadUnknown:
                return Response("unknown", command.causal_id, "current-head-unknown")
            except HeadTerminal:
                self._latch_terminal()
                return Response("unavailable", command.causal_id, self._closed_reason)
            except (HeadConflict, HeadTimeout, CurrentHeadError):
                return Response("unavailable", command.causal_id, "current-head-unavailable")

            committed = self._resolve_state_commit_remote(
                command,
                prepared,
                stored.state,
                head,
                binding,
            )
            if isinstance(committed, Response):
                return committed
            return self._persist_state_commit_success(command, prepared, committed, binding)
        finally:
            self._exit_current_head_guard()

    def _resolve_state_commit_remote(
        self,
        command: CommandEnvelope,
        prepared: PreparedTransition,
        current_state: str,
        head: AuthoritySnapshot,
        binding: CurrentHeadRecoveryBinding,
        *,
        recovery_only: bool = False,
    ) -> CommittedTransition | Response:
        """Return a fully confirmed transition, without any SQLite business write."""

        should_lookup = recovery_only or current_state == "unknown" or head != prepared.base
        if should_lookup:
            recovered = self._finalization_authority(
                "unknown" if current_state == "unknown" else "prepared",
                prepared,
                head,
                binding,
            )
            if not isinstance(recovered, _Handled):
                return recovered
            if recovered.response.reason_code != "transition-not-found":
                return self._with_causal_id(recovered, command.causal_id).response
            if recovery_only:
                # Once an exact response-loss binding is being recovered, a
                # missing transition is not evidence that the original CAS did
                # not happen.  Never issue another mutation from recovery:
                # terminal observation, adapter reset, and response loss are
                # observationally indistinguishable at this boundary.
                self._current_head_guard_preserved = True
                return Response("unavailable", command.causal_id, "transition-recovery-unconfirmed")
            if head != prepared.base:
                self._rollback_unapplied_state_commit(command, prepared, current_state)
                return Response("unavailable", command.causal_id, "current-head-conflict")

        writer_proof = self._current_writer_proof(prepared.base)
        if writer_proof is None:
            return Response("unavailable", command.causal_id, "current-writer-holder-missing")
        request = AdvanceRequest(
            expected=prepared.base,
            transition_id=prepared.target.transition_id,
            revision_digest=prepared.target.revision_digest,
            writer_fence=prepared.base.writer_fence,
            operation_digest=binding.command_digest,
            writer_proof=writer_proof,
        )
        try:
            updated = self._advance_head(request, recovery_binding=binding)
        except HeadConflict:
            self._rollback_unapplied_state_commit(command, prepared, current_state)
            return Response("unavailable", command.causal_id, "current-head-conflict")
        except HeadTimeout:
            self._mark_state_commit_ambiguous(command, prepared)
            return Response("unknown", command.causal_id, "current-head-timeout")
        except HeadUnknown:
            self._mark_state_commit_ambiguous(command, prepared)
            return Response("unknown", command.causal_id, "current-head-unknown")
        except HeadTerminal:
            self._latch_terminal()
            return Response("unavailable", command.causal_id, self._closed_reason)
        except CurrentHeadError:
            self._mark_state_commit_ambiguous(command, prepared)
            return Response("unavailable", command.causal_id, "current-head-unavailable")

        # The successful response is not authority proof.  This generic read
        # is intentionally outside both mutable and local-commit bindings.
        try:
            confirmed = self._confirm_advanced_head(updated)
        except HeadUnknown:
            self._mark_state_commit_ambiguous(command, prepared)
            return Response("unknown", command.causal_id, "current-head-unknown")
        except HeadTerminal:
            self._latch_terminal()
            self._mark_state_commit_ambiguous(command, prepared)
            return Response("unavailable", command.causal_id, self._closed_reason)
        except (HeadConflict, HeadTimeout, CurrentHeadError):
            self._mark_state_commit_ambiguous(command, prepared)
            return Response("unavailable", command.causal_id, "current-head-unavailable")
        return CommittedTransition(prepared=prepared, committed=confirmed)

    def _rollback_unapplied_state_commit(
        self,
        command: CommandEnvelope,
        prepared: PreparedTransition,
        current_state: str,
    ) -> None:
        """Release only an exact CAS journal proved not to have applied."""

        with self._store.transaction():
            payload = command.payload
            if not isinstance(payload, StateCommitPayload):
                raise KeyUnavailable("invalid commit payload")
            stored = self._store.record(payload.record_id)
            pending = self._store.pending_for_record(payload.record_id)
            if (
                stored is None
                or stored.state not in {"prepared", "unknown"}
                or stored.payload != prepared
                or pending is None
                or pending.command.to_wire() != command.to_wire()
            ):
                raise StoreUnavailable("state commit recovery state changed")
            if current_state == "unknown":
                daily = self._store.daily_turn_for_record(prepared.target.record_id)
                self._store.write_record(
                    prepared.target.record_id,
                    "prepared",
                    prepared.target.revision_digest,
                    prepared.target.transition_id,
                    prepared,
                )
                initialization = self._store.initialization()
                if (
                    initialization is not None
                    and initialization.draft.record_id == prepared.target.record_id
                ):
                    self._store.write_initialization("prepared", initialization.draft)
                if daily is not None:
                    self._store.write_daily_turn("prepared", daily.draft)
            self._store.clear_pending_command(command.causal_id)

    def _mark_state_commit_ambiguous(
        self,
        command: CommandEnvelope,
        prepared: PreparedTransition,
    ) -> None:
        """Record only the ambiguity that followed an already-owned CAS.

        The original pending command remains intact.  Its exact recovery binding
        is the sole authority that may later perform a read-only transition
        lookup, so this helper must never clear either the journal or guard.
        """

        payload = command.payload
        if not isinstance(payload, StateCommitPayload):
            raise KeyUnavailable("invalid commit payload")
        with self._store.transaction():
            stored = self._store.record(payload.record_id)
            pending = self._store.pending_for_record(payload.record_id)
            if (
                stored is None
                or stored.state not in {"prepared", "unknown"}
                or stored.payload != prepared
                or pending is None
                or pending.command.to_wire() != command.to_wire()
                or not pending.remote_attempted
            ):
                raise StoreUnavailable("state commit ambiguity state changed")
            if stored.state != "unknown":
                daily = self._store.daily_turn_for_record(prepared.target.record_id)
                self._store.write_record(
                    prepared.target.record_id,
                    "unknown",
                    prepared.target.revision_digest,
                    prepared.target.transition_id,
                    prepared,
                )
                initialization = self._store.initialization()
                if (
                    initialization is not None
                    and initialization.draft.record_id == prepared.target.record_id
                ):
                    self._store.write_initialization("unknown", initialization.draft)
                if daily is not None:
                    self._store.write_daily_turn("unknown", daily.draft)

    def _persist_state_commit_success(
        self,
        command: CommandEnvelope,
        prepared: PreparedTransition,
        committed: CommittedTransition,
        binding: CurrentHeadRecoveryBinding,
    ) -> Response:
        """Atomically write record, exact receipt, pending clear, and guard clear."""

        # The remote transition is confirmed, but no local business write may
        # close it after this core has lost the current writer.  A later exact
        # replay remains journaled and can perform lookup-only recovery.
        writer_validation = self._current_writer_proof_validation(committed.committed)
        if writer_validation.proof is None:
            self._retain_local_closure_guard_after_writer_validation(binding, writer_validation)
            return Response("unavailable", command.causal_id, "current-writer-holder-missing")

        response = Response(
            "accepted",
            command.causal_id,
            "current-head-advanced",
            CommitMeta(committed.committed.generation, committed.committed.writer_fence),
        )
        # Preserve the newly bound tripwire if the following local transaction
        # rolls back or its COMMIT response is lost.  The original causal
        # command can then repeat read-only transition recovery after restart.
        self._preserve_exact_local_closure_binding(binding)
        with self._store.transaction():
            guard = self._store.current_head_observation_guard()
            payload = command.payload
            if not isinstance(payload, StateCommitPayload):
                raise KeyUnavailable("invalid commit payload")
            current = self._store.record(payload.record_id)
            pending = self._store.pending_for_record(payload.record_id)
            if (
                guard is None
                or guard.binding != binding
                or current is None
                or current.state not in {"prepared", "unknown"}
                or current.payload != prepared
                or pending is None
                or pending.command.to_wire() != command.to_wire()
                or not pending.remote_attempted
            ):
                raise StoreUnavailable("state commit persistence changed")
            daily = self._store.daily_turn_for_record(prepared.target.record_id)
            self._store.write_record(
                prepared.target.record_id,
                "committed",
                prepared.target.revision_digest,
                prepared.target.transition_id,
                committed,
            )
            initialization = self._store.initialization()
            if (
                initialization is not None
                and initialization.draft.record_id == prepared.target.record_id
            ):
                self._store.write_initialization("committed", initialization.draft)
            if daily is not None:
                self._store.write_daily_turn("committed", daily.draft)
            self._store.clear_pending_command(command.causal_id)
            self._store.save_receipt(command, response)
            self._store.clear_current_head_observation(binding)
        self._current_head_guard_owned = False
        self._current_head_guard_binding = None
        self._current_head_guard_preserved = False
        return response

    def _handle_effect_result_remote(self, command: CommandEnvelope) -> Response:
        """Terminalize a controlled effect with the same three-phase discipline."""

        payload = command.payload
        if not isinstance(payload, EffectResultPayload):
            raise ProtocolViolation("invalid effect result payload")
        stored = self._store.effect(payload.effect_id)
        if stored is None or stored.state in {"accepted", "rejected", "unknown"}:
            raise ProtocolViolation("effect-intent-required")
        if stored.state != "executing" or not isinstance(stored.payload, ExecutingEffect):
            raise ProtocolViolation("effect-execution-required")
        execution = stored.payload
        if payload.intent_digest != execution.intent.intent_digest:
            raise ProtocolViolation("effect-intent-required")
        if payload.terminal is not True:
            raise ProtocolViolation("effect result is incomplete")
        if payload.lease_id != execution.lease.lease_id:
            raise ProtocolViolation("effect-execution-capability-required")
        try:
            holder_id = holder_id_for(payload.completion_capability)
        except ValueError as exc:
            raise ProtocolViolation("effect-execution-capability-required") from exc
        if holder_id != execution.lease.holder_id:
            raise ProtocolViolation("effect-execution-capability-required")
        pending = self._store.pending_effect_result(payload.effect_id)
        if pending is None:
            return Response("unavailable", command.causal_id, "effect-result-owner-missing")
        if not pending.matches(command, execution):
            return Response("rejected", command.causal_id, "causal-id-conflict")
        if not pending.remote_attempted and command.generation != execution.lease.authority.generation:
            raise ProtocolViolation("generation mismatch")

        binding = CurrentHeadRecoveryBinding.from_command(command)
        self._enter_current_head_guard()
        try:
            receipt = self._confirm_effect_result_remote(command, execution, pending, binding)
            if isinstance(receipt, Response):
                return receipt
            return self._persist_effect_result_success(command, execution, receipt, binding)
        finally:
            self._exit_current_head_guard()

    def _confirm_effect_result_remote(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
        pending: object,
        binding: CurrentHeadRecoveryBinding,
        *,
        allow_release: bool = True,
    ) -> ExecutionLeaseReceipt | Response:
        """Prove a released lease before any terminal SQLite mutation."""

        payload = command.payload
        if not isinstance(payload, EffectResultPayload):
            raise KeyUnavailable("invalid effect result payload")
        identity = ExecutionLeaseIdentity(
            expected=execution.lease.authority,
            effect_id=execution.lease.effect_id,
            intent_digest=execution.lease.intent_digest,
            writer_fence=execution.lease.authority.writer_fence,
            holder_id=execution.lease.holder_id,
        )
        try:
            receipt = self._lookup_execution_lease(identity)
        except HeadUnknown:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unknown", command.causal_id, "effect-lease-unknown"),
            )
        except HeadTerminal:
            self._latch_terminal()
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, self._closed_reason),
            )
        except ExecutionLeaseNotFound:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "effect-lease-not-found"),
            )
        except HeadConflict:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "effect-lease-lookup-conflict"),
            )
        except HeadTimeout:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "effect-lease-timeout"),
            )
        except MalformedCurrentHeadResponse:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "effect-lease-malformed"),
            )
        except CurrentHeadError:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "effect-lease-lookup-unclassified"),
            )
        if receipt.lease != execution.lease:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "effect-lease-mismatch"),
            )
        if receipt.released:
            if not getattr(pending, "remote_attempted", False):
                return self._unattempted_effect_result_response(
                    command,
                    execution,
                    pending,
                    Response("unavailable", command.causal_id, "effect-release-unconfirmed"),
                )
            # A released lease is historical proof for one exact terminal
            # command, never generic authority for a cloned local effect row.
            if receipt.released_operation_digest != binding.command_digest:
                self._current_head_guard_preserved = True
                return Response("unavailable", command.causal_id, "effect-release-owner-mismatch")
            return receipt
        if not allow_release:
            # A recovery binding proves only that the original release may
            # already have happened.  Once it is consumed into generic guard,
            # an active lease is not permission to issue a second side effect.
            return Response("unavailable", command.causal_id, "effect-release-unconfirmed")

        try:
            live = self._read_head()
        except HeadUnknown:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unknown", command.causal_id, "effect-lease-unknown"),
            )
        except HeadTerminal:
            self._latch_terminal()
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, self._closed_reason),
            )
        except HeadConflict:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "effect-lease-read-conflict"),
            )
        except HeadTimeout:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "effect-lease-timeout"),
            )
        except MalformedCurrentHeadResponse:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "effect-lease-malformed"),
            )
        except CurrentHeadError:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "effect-lease-read-unclassified"),
            )
        if execution.lease.authority.mismatch_reason(live) is not None:
            self._closed_reason = "effect-intent-stale"
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, self._closed_reason),
            )
        if command.generation != live.generation:
            self._clear_unattempted_effect_result(command, execution, pending)
            raise ProtocolViolation("generation mismatch")
        writer_proof = self._current_writer_proof(live)
        if writer_proof is None:
            return self._unattempted_effect_result_response(
                command,
                execution,
                pending,
                Response("unavailable", command.causal_id, "current-writer-holder-missing"),
            )

        if not getattr(pending, "remote_attempted", False):
            if not self._completion_capability_is_held(
                execution,
                payload.completion_capability,
                writer_proof,
            ):
                return self._unattempted_effect_result_response(
                    command,
                    execution,
                    pending,
                    Response("unavailable", command.causal_id, "effect-execution-capability-unavailable"),
                )
            self._store.mark_pending_effect_result_attempted(command, execution)
        try:
            self._release_execution_lease(
                execution.lease,
                writer_proof=writer_proof,
                recovery_binding=binding,
            )
        except HeadUnknown:
            return Response("unknown", command.causal_id, "effect-lease-unknown")
        except HeadTerminal:
            self._latch_terminal()
            return Response("unavailable", command.causal_id, self._closed_reason)
        except ExecutionLeaseNotFound:
            return Response("unavailable", command.causal_id, "effect-lease-not-found")
        except HeadConflict:
            return Response("unavailable", command.causal_id, "effect-lease-release-conflict")
        except HeadTimeout:
            return Response("unavailable", command.causal_id, "effect-lease-timeout")
        except MalformedCurrentHeadResponse:
            return Response("unavailable", command.causal_id, "effect-lease-malformed")
        except CurrentHeadError:
            return Response("unavailable", command.causal_id, "effect-lease-release-unclassified")

        # The release response is not completion proof.  This read executes
        # under generic guard, before the local terminal/receipt binding.
        try:
            receipt = self._lookup_execution_lease(identity)
        except HeadUnknown:
            return Response("unknown", command.causal_id, "effect-lease-unknown")
        except HeadTerminal:
            self._latch_terminal()
            return Response("unavailable", command.causal_id, self._closed_reason)
        except MalformedCurrentHeadResponse:
            self._current_head_guard_preserved = True
            return Response("unavailable", command.causal_id, "effect-lease-malformed")
        except ExecutionLeaseNotFound:
            return Response("unavailable", command.causal_id, "effect-lease-not-found")
        except HeadConflict:
            return Response("unavailable", command.causal_id, "effect-lease-lookup-conflict")
        except HeadTimeout:
            return Response("unavailable", command.causal_id, "effect-lease-timeout")
        except CurrentHeadError:
            return Response("unavailable", command.causal_id, "effect-lease-lookup-unclassified")
        if receipt.lease != execution.lease or not receipt.released:
            return Response("unavailable", command.causal_id, "effect-lease-unavailable")
        if receipt.released_operation_digest != binding.command_digest:
            self._current_head_guard_preserved = True
            return Response("unavailable", command.causal_id, "effect-release-owner-mismatch")
        return receipt

    def _clear_unattempted_effect_result(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
        pending: object,
    ) -> None:
        if not getattr(pending, "remote_attempted", False):
            self._store.clear_unattempted_pending_effect_result(command, execution)

    def _unattempted_effect_result_response(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
        pending: object,
        response: Response,
    ) -> Response:
        self._clear_unattempted_effect_result(command, execution, pending)
        return response

    def _persist_effect_result_success(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
        receipt: ExecutionLeaseReceipt,
        binding: CurrentHeadRecoveryBinding,
    ) -> Response:
        """Atomically terminalize the effect, save replay, and clear its guard."""

        payload = command.payload
        if not isinstance(payload, EffectResultPayload):
            raise KeyUnavailable("invalid effect result payload")
        if receipt.lease != execution.lease or not receipt.released:
            raise StoreUnavailable("effect release was not confirmed")
        if receipt.released_operation_digest != binding.command_digest:
            self._current_head_guard_preserved = True
            return Response("unavailable", command.causal_id, "effect-release-owner-mismatch")
        # A release receipt proves historical effect completion.  It does not
        # authorize a cloned or stale local core to write the terminal business
        # row and replay receipt.  Revalidate the *current* writer immediately
        # before that atomic local closure; the live authority may legitimately
        # have advanced after the receipt was released.
        try:
            live = self._read_head()
        except HeadTerminal:
            self._latch_terminal()
            return Response("unavailable", command.causal_id, self._closed_reason)
        except HeadUnknown:
            self._preserve_exact_local_closure_binding(binding)
            return Response("unknown", command.causal_id, "current-head-unknown")
        except (HeadConflict, HeadTimeout):
            self._preserve_exact_local_closure_binding(binding)
            return Response("unavailable", command.causal_id, "current-head-unavailable")
        except CurrentHeadError:
            # An invalid or unclassified live read cannot prove the remote is
            # nonterminal.  It consumes the exact release-replay lane.
            self._current_head_guard_preserved = True
            return Response("unavailable", command.causal_id, "current-head-unavailable")
        if live.installation_id != execution.lease.authority.installation_id:
            # A live authority mismatch is a confirmed boundary change, not a
            # retryable local closure fault.  Keep generic guard forever.
            self._current_head_guard_preserved = True
            return Response("unavailable", command.causal_id, "effect-installation-mismatch")
        if live.site != execution.lease.authority.site:
            self._current_head_guard_preserved = True
            return Response("unavailable", command.causal_id, "effect-site-mismatch")
        if live.writer_fence != execution.lease.authority.writer_fence:
            # A released lease is historical F1 proof.  Without a distinct,
            # authenticated handoff fact, a live F2 writer cannot use it to
            # terminalize this core's local business row or replay receipt.
            self._current_head_guard_preserved = True
            return Response("unavailable", command.causal_id, "effect-writer-fence-mismatch")
        writer_validation = self._current_writer_proof_validation(live)
        if writer_validation.proof is None:
            self._retain_local_closure_guard_after_writer_validation(binding, writer_validation)
            return Response("unavailable", command.causal_id, "current-writer-holder-missing")
        terminal_effect = TerminalEffect(
            execution=execution,
            status=payload.status,
            result_digest=payload.result_digest,
        )
        response = Response(
            "unknown" if payload.status == "unknown" else ("accepted" if payload.status == "accepted" else "rejected"),
            command.causal_id,
            "effect-result-unknown" if payload.status == "unknown" else "effect-terminal",
        )
        self._preserve_exact_local_closure_binding(binding)
        with self._store.transaction():
            guard = self._store.current_head_observation_guard()
            current = self._store.effect(payload.effect_id)
            pending = self._store.pending_effect_result(payload.effect_id)
            if (
                guard is None
                or guard.binding != binding
                or current is None
                or current.state != "executing"
                or current.payload != execution
                or pending is None
                or not pending.matches(command, execution)
            ):
                raise StoreUnavailable("effect result persistence changed")
            self._store.write_effect(payload.effect_id, payload.status, terminal_effect)
            self._store.clear_pending_effect_result(command, execution)
            self._store.save_receipt(command, response)
            self._store.clear_current_head_observation(binding)
        self._current_head_guard_owned = False
        self._current_head_guard_binding = None
        self._current_head_guard_preserved = False
        if payload.status == "unknown":
            self._closed_reason = "effect-result-unknown"
        return response

    def _recover_interrupted_current_head_observation(
        self,
        command: CommandEnvelope,
        binding: CurrentHeadRecoveryBinding | None,
    ) -> Response:
        """Allow only a bound original causal command to close a crash tripwire."""

        if binding is None or not binding.matches(command):
            nonowner = self._interrupted_nonowner_response(command)
            if nonowner is not None:
                return nonowner
            self._closed_reason = "current-head-observation-incomplete"
            return Response("unavailable", command.causal_id, self._closed_reason)
        if command.action == "state.commit":
            return self._recover_interrupted_state_commit(command, binding)
        if command.action == "effect.result":
            return self._recover_interrupted_effect_result(command, binding)
        self._closed_reason = "current-head-observation-incomplete"
        return Response("unavailable", command.causal_id, self._closed_reason)

    def _interrupted_nonowner_response(self, command: CommandEnvelope) -> Response | None:
        """Report a known conflicting owner without relaxing the tripwire."""

        payload = command.payload
        if command.action == "state.commit" and isinstance(payload, StateCommitPayload):
            pending = self._store.pending_for_record(payload.record_id)
            if pending is not None and pending.command.to_wire() != command.to_wire():
                return Response("rejected", command.causal_id, "causal-id-conflict")
        if command.action == "state.finalize" and isinstance(payload, StateCommitPayload):
            if self._store.pending_for_record(payload.record_id) is not None:
                return Response("unavailable", command.causal_id, "pending-command-owner-required")
        if command.action == "effect.result" and isinstance(payload, EffectResultPayload):
            pending = self._store.pending_effect_result(payload.effect_id)
            if pending is not None:
                stored = self._store.effect(payload.effect_id)
                if (
                    stored is not None
                    and stored.state == "executing"
                    and isinstance(stored.payload, ExecutingEffect)
                    and not pending.matches(command, stored.payload)
                ):
                    return Response("rejected", command.causal_id, "causal-id-conflict")
        return None

    def _recover_interrupted_state_commit(
        self,
        command: CommandEnvelope,
        binding: CurrentHeadRecoveryBinding,
    ) -> Response:
        pending = self._store.pending_command(command)
        payload = command.payload
        if (
            pending is None
            or not pending.remote_attempted
            or not isinstance(payload, StateCommitPayload)
        ):
            self._closed_reason = "current-head-observation-incomplete"
            return Response("unavailable", command.causal_id, self._closed_reason)
        stored = self._store.record(payload.record_id)
        if (
            stored is None
            or stored.state not in {"prepared", "unknown"}
            or not isinstance(stored.payload, PreparedTransition)
        ):
            self._closed_reason = "current-head-observation-incomplete"
            return Response("unavailable", command.causal_id, self._closed_reason)
        prepared = stored.payload
        if not prepared.target.matches_commit(
            record_id=payload.record_id,
            revision_digest=payload.revision_digest,
            transition_id=payload.transition_id,
        ):
            self._closed_reason = "current-head-observation-incomplete"
            return Response("unavailable", command.causal_id, self._closed_reason)
        local_writer_preflight = self._bound_recovery_local_writer_preflight(prepared.base)
        if local_writer_preflight is not None:
            return Response(
                local_writer_preflight.status,
                command.causal_id,
                local_writer_preflight.reason_code,
                local_writer_preflight.meta,
            )

        # The host proved the old writer capability without observing remote
        # state.  Consume B before *any* remote read or writer validation: a
        # terminal response plus a hard stop can now leave only generic guard.
        self._begin_interrupted_current_head_recovery(binding)
        preflight_failure: _BoundRecoveryPreflightFailure | None = None
        try:
            live = self._bound_recovery_live_writer_preflight(
                prepared.base,
                installation_mismatch_reason="prepared-installation-mismatch",
                site_mismatch_reason="prepared-site-mismatch",
                writer_fence_mismatch_reason="prepared-writer-fence-mismatch",
            )
            if isinstance(live, _BoundRecoveryPreflightFailure):
                preflight_failure = live
                recovered: CommittedTransition | Response = Response(
                    live.response.status,
                    command.causal_id,
                    live.response.reason_code,
                    live.response.meta,
                )
            else:
                recovered = self._resolve_state_commit_remote(
                    command,
                    prepared,
                    stored.state,
                    live,
                    binding,
                    recovery_only=True,
                )
        except BaseException:
            # This recovery phase owns a generic guard.  An unexpected process
            # stop or adapter exception must not let a later call clear it.
            self._current_head_guard_preserved = True
            raise
        finally:
            self._current_head_guard_depth -= 1
        if isinstance(recovered, Response):
            retryable_lookup_failure = (
                preflight_failure is None
                and recovered.reason_code
                in {
                    "current-head-unknown",
                    "current-head-timeout",
                }
            )
            if (
                (
                    preflight_failure is not None
                    and preflight_failure.resumable_by_same_live_writer
                )
                or retryable_lookup_failure
            ) and not self._terminal_seen:
                self._restore_recovery_binding_after_returned_preflight_failure(
                    binding,
                    still_owned=lambda: self._state_recovery_binding_still_owned(command, prepared),
                )
            else:
                # A transition lookup has consumed the response-loss recovery
                # lane, or the live adapter result was malformed/terminal.
                # Retain generic protection rather than making B replayable.
                self._current_head_guard_preserved = True
            return recovered
        # All remote reads/lookup confirmation have completed under the
        # generic recovery guard.  Rebind only for the atomic local closure.
        self._current_head_guard_depth += 1
        try:
            response = self._persist_state_commit_success(command, prepared, recovered, binding)
            if self._current_head_guard_owned:
                self._current_head_guard_preserved = True
            return response
        finally:
            self._current_head_guard_depth -= 1

    def _recover_interrupted_effect_result(
        self,
        command: CommandEnvelope,
        binding: CurrentHeadRecoveryBinding,
    ) -> Response:
        payload = command.payload
        if not isinstance(payload, EffectResultPayload):
            self._closed_reason = "current-head-observation-incomplete"
            return Response("unavailable", command.causal_id, self._closed_reason)
        stored = self._store.effect(payload.effect_id)
        pending = self._store.pending_effect_result(payload.effect_id)
        if (
            stored is None
            or stored.state != "executing"
            or not isinstance(stored.payload, ExecutingEffect)
            or pending is None
            or not pending.remote_attempted
        ):
            self._closed_reason = "current-head-observation-incomplete"
            return Response("unavailable", command.causal_id, self._closed_reason)
        execution = stored.payload
        try:
            if not pending.matches(command, execution):
                self._closed_reason = "current-head-observation-incomplete"
                return Response("unavailable", command.causal_id, self._closed_reason)
        except ProtocolViolation:
            self._closed_reason = "current-head-observation-incomplete"
            return Response("unavailable", command.causal_id, self._closed_reason)
        local_writer_preflight = self._bound_recovery_local_writer_preflight(
            execution.lease.authority
        )
        if local_writer_preflight is not None:
            return Response(
                local_writer_preflight.status,
                command.causal_id,
                local_writer_preflight.reason_code,
                local_writer_preflight.meta,
            )

        # The host-local old-fence proof is the only check allowed while B is
        # still present.  All remote observation, including live writer
        # validation, runs after B becomes generic.
        self._begin_interrupted_current_head_recovery(binding)
        preflight_failure: _BoundRecoveryPreflightFailure | None = None
        try:
            live = self._bound_recovery_live_writer_preflight(
                execution.lease.authority,
                installation_mismatch_reason="effect-installation-mismatch",
                site_mismatch_reason="effect-site-mismatch",
                writer_fence_mismatch_reason="effect-writer-fence-mismatch",
            )
            if isinstance(live, _BoundRecoveryPreflightFailure):
                preflight_failure = live
                receipt: ExecutionLeaseReceipt | Response = Response(
                    live.response.status,
                    command.causal_id,
                    live.response.reason_code,
                    live.response.meta,
                )
            else:
                receipt = self._confirm_effect_result_remote(
                    command,
                    execution,
                    pending,
                    binding,
                    allow_release=False,
                )
        except BaseException:
            self._current_head_guard_preserved = True
            raise
        finally:
            self._current_head_guard_depth -= 1
        if isinstance(receipt, Response):
            retryable_lookup_failure = (
                preflight_failure is None
                and receipt.reason_code in {"effect-lease-unknown", "effect-lease-timeout"}
            )
            if (
                (
                    preflight_failure is not None
                    and preflight_failure.resumable_by_same_live_writer
                )
                or retryable_lookup_failure
            ) and not self._terminal_seen:
                self._restore_recovery_binding_after_returned_preflight_failure(
                    binding,
                    still_owned=lambda: self._effect_recovery_binding_still_owned(command, execution),
                )
            else:
                self._current_head_guard_preserved = True
            return receipt
        self._current_head_guard_depth += 1
        try:
            response = self._persist_effect_result_success(command, execution, receipt, binding)
            if self._current_head_guard_owned:
                self._current_head_guard_preserved = True
            return response
        finally:
            self._current_head_guard_depth -= 1

    def _prewrite_remote_journal(self, command: CommandEnvelope) -> Response | None:
        """Persist exact causal ownership before any remote mutation."""

        state_preflight = self._prewrite_commit_journal(command)
        if state_preflight is not None or command.action != "effect.result":
            return state_preflight
        return self._prewrite_effect_result_journal(command)

    def _prewrite_commit_journal(self, command: CommandEnvelope) -> Response | None:
        """Durably bind a fresh remote commit to its exact causal command.

        A prepared row alone cannot prove who owns an ambiguous remote CAS.  A
        new commit therefore gets an encrypted record-scoped journal only while
        current-head still exactly equals the authority saved at prepare time.
        Existing journals are never replaced by a different causal ID.
        """

        if command.action != "state.commit":
            return None
        payload = command.payload
        if not isinstance(payload, StateCommitPayload):
            raise ProtocolViolation("invalid commit payload")
        if self._admission_policy is not None:
            if self._business_transition_record_kind(payload.record_id) is None:
                return self._persist_rejection(
                    command,
                    "generic-initialization-action-denied",
                )
        current = self._store.record(payload.record_id)
        if current is None or current.state not in {"prepared", "unknown"}:
            return None
        if not isinstance(current.payload, PreparedTransition):
            raise KeyUnavailable("invalid prepared state")
        prepared = current.payload
        if not prepared.target.matches_commit(
            record_id=payload.record_id,
            revision_digest=payload.revision_digest,
            transition_id=payload.transition_id,
        ):
            return None
        # An unknown row without its original journal is not eligible for any
        # new command to claim; it remains fail-closed for operator recovery.
        if current.state == "unknown":
            pending = self._store.pending_for_record(payload.record_id)
            if pending is not None and pending.command.to_wire() != command.to_wire():
                raise CausalIdConflict("causal-id-conflict")
            return None
        if (
            command.generation != prepared.base.generation
            or payload.writer_fence != prepared.base.writer_fence
        ):
            return None
        existing_pending = self._store.pending_for_record(payload.record_id)
        if existing_pending is not None:
            if existing_pending.command.to_wire() != command.to_wire():
                raise CausalIdConflict("causal-id-conflict")
            if existing_pending.remote_attempted:
                # This journal already crossed the pre-CAS phase boundary;
                # leave recovery to the state handler rather than erasing an
                # operation whose remote outcome may be ambiguous.
                return None
        try:
            head = self._read_head()
        except HeadUnknown:
            return Response("unknown", command.causal_id, "current-head-unknown")
        except (HeadConflict, HeadTimeout):
            return Response("unavailable", command.causal_id, "current-head-unavailable")
        except HeadTerminal:
            self._latch_terminal()
            return Response("unavailable", command.causal_id, self._closed_reason)
        except CurrentHeadError:
            return Response("unavailable", command.causal_id, "current-head-unavailable")
        # Leave terminal and stale authority responses to the normal state
        # handler, but only journal a CAS that is still safe to issue.
        if head != prepared.base:
            return None
        if self._admission_policy is not None:
            if self._business_transition_kind(payload.record_id) is None:
                return Response(
                    "unavailable",
                    command.causal_id,
                    "initialization-configuration-mismatch",
                )
        # Owning a durable CAS-recovery lane is itself authority-sensitive.
        # A copied database plus the public fence text must not be able to
        # reserve/poison a real writer's causal ID before the later CAS check.
        if self._current_writer_proof(head) is None:
            return Response("unavailable", command.causal_id, "current-writer-holder-missing")
        # Recheck the encrypted local record and reserve in one SQLite write
        # transaction.  The reservation is explicitly *unattempted* until a
        # second remote read proves it is still safe to call CAS.
        if not self._store.reserve_pending_commit(command, prepared):
            return None
        try:
            confirmed = self._read_head()
        except HeadUnknown:
            self._store.clear_unattempted_pending_command(command)
            return Response("unknown", command.causal_id, "current-head-unknown")
        except (HeadConflict, HeadTimeout):
            self._store.clear_unattempted_pending_command(command)
            return Response("unavailable", command.causal_id, "current-head-unavailable")
        except HeadTerminal:
            self._store.clear_unattempted_pending_command(command)
            self._latch_terminal()
            return Response("unavailable", command.causal_id, self._closed_reason)
        except CurrentHeadError:
            self._store.clear_unattempted_pending_command(command)
            return Response("unavailable", command.causal_id, "current-head-unavailable")
        if confirmed != prepared.base:
            # No remote operation has been attempted for an explicitly
            # unattempted journal.  Do not turn a stale local preflight into an
            # unrecoverable causal reservation.
            self._store.clear_unattempted_pending_command(command)
            return Response("unavailable", command.causal_id, "current-head-conflict")
        if self._current_writer_proof(confirmed) is None:
            # No remote CAS was attempted, so a lost holder proof can safely
            # release this still-unattempted reservation instead of leaving a
            # stale process to deny the live writer forever.
            self._store.clear_unattempted_pending_command(command)
            return Response("unavailable", command.causal_id, "current-writer-holder-missing")
        self._store.mark_pending_remote_attempted(command)
        return None

    def _prewrite_effect_result_journal(self, command: CommandEnvelope) -> Response | None:
        """Reserve an effect terminal result before its remote lease release.

        Unlike an ordinary receipt, this durable record never includes the raw
        completion capability.  It binds its holder hash and the complete
        command authority so a later causal ID cannot claim a response-lost
        remote release.
        """

        payload = command.payload
        if not isinstance(payload, EffectResultPayload):
            raise ProtocolViolation("invalid effect result payload")
        if payload.terminal is not True:
            # Validation must precede durable ownership reservation; otherwise
            # an invalid partial result could permanently seize this effect's
            # causal recovery lane without ever touching current-head.
            raise ProtocolViolation("effect result is incomplete")
        stored = self._store.effect(payload.effect_id)
        if stored is None or stored.state != "executing":
            return None
        if not isinstance(stored.payload, ExecutingEffect):
            raise KeyUnavailable("invalid executing effect")
        execution = stored.payload
        existing = self._store.pending_effect_result(payload.effect_id)
        if existing is None:
            if command.generation != execution.lease.authority.generation:
                # A fresh terminal result is authorized only at the generation
                # that issued its execution lease.  An exact already-attempted
                # causal replay may later close a released lease after another
                # writer has advanced current-head; it is handled by recovery.
                raise ProtocolViolation("generation mismatch")
            try:
                live = self._read_head()
            except HeadUnknown:
                return Response("unknown", command.causal_id, "effect-lease-unknown")
            except HeadTerminal:
                self._latch_terminal()
                return Response("unavailable", command.causal_id, self._closed_reason)
            except (HeadConflict, HeadTimeout, CurrentHeadError):
                return Response("unavailable", command.causal_id, "effect-lease-unavailable")
            if execution.lease.authority.mismatch_reason(live) is not None:
                return Response("unavailable", command.causal_id, "effect-intent-stale")
            # As with a state CAS journal, a fresh effect-result reservation is
            # durable ownership.  Require a live host-only writer proof before
            # it reaches SQLite, otherwise a clone can DoS the real executor.
            if self._current_writer_proof(live) is None:
                return Response("unavailable", command.causal_id, "current-writer-holder-missing")
        # Reservation also validates effect/intent/lease/holder binding.  The
        # attempted marker is committed immediately before the remote release:
        # a crash after it can only be recovered by this exact causal command.
        self._store.reserve_pending_effect_result(command, execution)
        return None

    def _persist_rejection(self, command: CommandEnvelope, reason_code: str) -> Response:
        response = Response("rejected", command.causal_id, reason_code)
        try:
            with self._store.transaction():
                if self._store.has_pending_causal_id(command.causal_id):
                    return response
                self._store.save_receipt(command, response)
        except (CausalIdConflict, KeyUnavailable):
            # A malformed command never gets to rewrite state; inability to save
            # a synthetic rejection is still fail-closed.
            self._closed_reason = "health-key-unavailable"
            return Response("unavailable", command.causal_id, self._closed_reason)
        except StoreUnavailable:
            self._closed_reason = "health-state-unavailable"
            return Response("unavailable", command.causal_id, self._closed_reason)
        return response

    def _handle_new(self, command: CommandEnvelope) -> _Handled:
        if command.action == "probe":
            report = self.probe()
            return _Handled(
                Response("accepted", command.causal_id, report.reason_code, ProbeMeta(report.state.value)),
                False,
            )

        try:
            head = self._read_head()
        except HeadUnknown:
            return _Handled(Response("unknown", command.causal_id, "current-head-unknown"), False)
        except (HeadConflict, HeadTimeout):
            return _Handled(Response("unavailable", command.causal_id, "current-head-unavailable"), False)
        except HeadTerminal:
            self._latch_terminal()
            return _Handled(Response("unavailable", command.causal_id, self._closed_reason), False)
        except CurrentHeadError:
            return _Handled(Response("unavailable", command.causal_id, "current-head-unavailable"), False)

        # A response-lost commit retries with the original prepared generation;
        # its state-specific branch below can only reconcile an existing
        # encrypted ``unknown`` operation by transition lookup.
        confirmed_alias_replay = self._is_confirmed_daily_source_alias_replay(
            command
        )
        if (
            command.generation != head.generation
            and command.action not in {"state.commit", "effect.result"}
            and not confirmed_alias_replay
        ):
            raise ProtocolViolation("generation mismatch")
        if command.action == "effect.result" and command.generation != head.generation:
            payload = command.payload
            if not isinstance(payload, EffectResultPayload):
                raise ProtocolViolation("invalid effect result payload")
            stored = self._store.effect(payload.effect_id)
            pending = self._store.pending_effect_result(payload.effect_id)
            if (
                stored is None
                or stored.state != "executing"
                or not isinstance(stored.payload, ExecutingEffect)
                or pending is None
                or not pending.remote_attempted
                or not pending.matches(command, stored.payload)
            ):
                raise ProtocolViolation("generation mismatch")
        if head.terminal:
            self._latch_terminal()
            return _Handled(Response("unavailable", command.causal_id, self._closed_reason), False)

        if command.action in {
            "initialization.disclose",
            "initialization.prepare",
        } and self._store.initialization() is not None:
            return _Handled(
                Response("rejected", command.causal_id, "initialization already exists"),
                True,
            )
        if command.action == "effect.request" and self._admission_policy is not None:
            initialization = self._store.initialization()
            if initialization is None or initialization.phase != "enabled":
                return _Handled(
                    Response("rejected", command.causal_id, "initialization-required"),
                    True,
                )
            if not self._initialization_configuration_matches(initialization.draft):
                return _Handled(
                    Response(
                        "unavailable",
                        command.causal_id,
                        "initialization-configuration-mismatch",
                    ),
                    False,
                )

        if command.action not in _PROBE_BYPASS_ACTIONS:
            report = self._probe_for_head(head)
            if report.state is ProbeState.HEALTHY and self._current_writer_proof(head) is None:
                return _Handled(
                    Response("unavailable", command.causal_id, "current-writer-holder-missing"),
                    False,
                )
            if report.state is not ProbeState.HEALTHY:
                return _Handled(Response("unavailable", command.causal_id, report.reason_code), False)

        if command.action in _STATE_ACTIONS:
            if self._admission_policy is not None:
                payload = command.payload
                if (
                    command.action in {"state.candidate", "state.prepare"}
                    or not isinstance(payload, StateCommitPayload)
                    or self._business_transition_record_kind(payload.record_id) is None
                ):
                    return _Handled(
                        Response(
                            "rejected",
                            command.causal_id,
                            "generic-initialization-action-denied",
                        ),
                        True,
                    )
            return self._handle_state(command, head)
        if command.action == "inbound.admit":
            return self._handle_inbound_admit(command)
        if command.action == "initialization.disclose":
            return self._handle_initialization_disclose(command)
        if command.action == "initialization.prepare":
            return self._handle_initialization_prepare(command, head)
        if command.action == "turn.prepare":
            return self._handle_daily_turn_prepare(command, head)
        if command.action == "cursor.result":
            return self._handle_native_cursor_result(command)
        if command.action == "effect.request":
            return self._handle_effect_request(command, head)
        if command.action == "effect.result":
            raise StoreUnavailable("effect result must use the remote handler")
        raise ProtocolViolation("unknown action")

    def _is_confirmed_daily_source_alias_replay(
        self,
        command: CommandEnvelope,
    ) -> bool:
        """Permit an exact confirmed alias to converge after its root advanced head."""

        payload = command.payload
        if (
            command.action != "inbound.admit"
            or not isinstance(payload, InboundAdmitPayload)
            or payload.envelope.causal_id != command.causal_id
        ):
            return False
        receipt = self._store.source_receipt(command.causal_id)
        return (
            receipt is not None
            and receipt.business_source_causal_id is not None
            and self._store.source_receipt_matches_exact_delivery(
                receipt,
                payload.envelope,
            )
        )

    def _daily_turn_lease_response(
        self,
        command: CommandEnvelope,
    ) -> _Handled | None:
        """Resolve an already-owned daily lease before any remote-head read.

        An unknown or committed transition can legitimately make the generic
        probe unavailable, but neither state should obscure the core-owned
        daily lease.  The caller holds both the store's serialized writer lane
        and its SQLite transaction, so this read is authoritative for the
        response and cannot race a new prepared row in this core/store.
        """

        if command.action != "turn.prepare":
            return None
        payload = command.payload
        if not isinstance(payload, DailyTurnPreparePayload):
            raise ProtocolViolation("invalid daily turn payload")
        unresolved = self._store.unresolved_daily_turn()
        if unresolved is None:
            return None
        draft = payload.draft
        if unresolved.draft.source_causal_id != draft.source_causal_id:
            return _Handled(
                Response("unavailable", command.causal_id, "daily-turn-busy"),
                False,
            )
        if (
            unresolved.phase == "evidence-finalized"
            and draft.turn_kind == "complete-turn"
        ):
            if (
                draft.evidence_stage != unresolved.draft
                or draft.base_state_digest != unresolved.evidence_state_digest
            ):
                raise ProtocolViolation(
                    "daily completion did not continue exact evidence stage"
                )
            return None
        if unresolved.draft != draft:
            raise ProtocolViolation("daily source already has another turn")
        return _Handled(
            Response("accepted", command.causal_id, "daily-turn-already-prepared"),
            True,
        )

    def _handle_daily_turn_prepare(
        self,
        command: CommandEnvelope,
        head: AuthoritySnapshot,
    ) -> _Handled:
        payload = command.payload
        if not isinstance(payload, DailyTurnPreparePayload):
            raise ProtocolViolation("invalid daily turn payload")
        initialization = self._store.initialization()
        verifier = self._daily_skill_verifier
        bundle = self._daily_skill_bundle
        if (
            initialization is None
            or initialization.phase != "enabled"
            or not self._initialization_configuration_matches(initialization.draft)
            or type(verifier) is not DailySkillAttestor
            or type(bundle) is not DailySkillBundle
        ):
            return _Handled(
                Response(
                    "unavailable",
                    command.causal_id,
                    "daily-skill-configuration-mismatch",
                ),
                False,
            )
        draft = payload.draft
        source = self._store.source_envelope(draft.source_causal_id)
        receipt = self._store.source_receipt(draft.source_causal_id)
        state = self._store.daily_state()
        if (
            source is None
            or receipt is None
            or receipt.managed_cursor_state != "held"
            or source.requested_capability not in DAILY_HEALTH_SKILL_NAMES
        ):
            return _Handled(
                Response("rejected", command.causal_id, "daily-source-required"),
                True,
            )
        unresolved = self._store.unresolved_daily_turn()
        if draft.turn_kind == "evidence-stage":
            verified = draft.verify(source, state, bundle, verifier)
            continuing_stage = None
        else:
            continuing_stage = (
                unresolved.draft
                if unresolved is not None
                and unresolved.phase == "evidence-finalized"
                and unresolved.draft.source_causal_id == draft.source_causal_id
                else None
            )
            if type(continuing_stage) is not DailyTurnDraft:
                raise ProtocolViolation("daily completion evidence stage missing")
            post_stage_state = state.apply_evidence_stage(continuing_stage)
            verified = draft.verify(
                source,
                post_stage_state,
                bundle,
                verifier,
                committed_evidence_stage=continuing_stage,
            )
        if not verified:
            return _Handled(
                Response("rejected", command.causal_id, "daily-skill-proof-required"),
                True,
            )
        # The lease read and a possible prepared-row write occur inside the
        # caller's serialized store transaction.  A busy response deliberately
        # has no receipt, so the caller can retry after the current owner reaches
        # its finalized phase.  Exact recovery for that owner remains idempotent.
        existing = self._store.daily_turn(draft.source_causal_id)
        if existing is not None and draft.turn_kind == "evidence-stage":
            if existing.draft != draft:
                raise ProtocolViolation("daily source already has another turn")
            return _Handled(
                Response("accepted", command.causal_id, "daily-turn-already-prepared"),
                True,
            )
        if unresolved is not None and draft.turn_kind == "evidence-stage":
            return _Handled(
                Response("unavailable", command.causal_id, "daily-turn-busy"),
                False,
            )
        target = RevisionTarget(
            record_id=draft.record_id,
            revision_digest=draft.revision_digest,
            transition_id=draft.transition_id,
            payload_digest=draft.payload_digest,
        )
        self._store.write_record(
            draft.record_id,
            "prepared",
            draft.revision_digest,
            draft.transition_id,
            PreparedTransition(target=target, base=head),
        )
        self._store.write_daily_turn("prepared", draft)
        return _Handled(
            Response("accepted", command.causal_id, "daily-turn-prepared"),
            True,
        )

    def _handle_inbound_admit(self, command: CommandEnvelope) -> _Handled:
        payload = command.payload
        policy = self._admission_policy
        if not isinstance(payload, InboundAdmitPayload):
            raise ProtocolViolation("invalid inbound payload")
        if (
            type(policy) is not AdmissionPolicy
            or payload.admission_policy != policy
        ):
            return _Handled(
                Response(
                    "unavailable",
                    command.causal_id,
                    "admission-policy-mismatch",
                ),
                False,
            )
        initialization = self._store.initialization()
        allowed_capabilities = (
            ("health-init",)
            if initialization is None
            else DAILY_HEALTH_SKILL_NAMES
        )
        if not policy.accepts(
            payload.envelope,
            allowed_capabilities=allowed_capabilities,
        ):
            return _Handled(
                Response("rejected", command.causal_id, "unique-private-source-denied"),
                False,
            )
        if type(payload.envelope.body) is not str:
            raise ProtocolViolation("source body is required")
        if payload.envelope.causal_id != command.causal_id:
            raise ProtocolViolation("source causal identifier mismatch")
        if initialization is not None:
            if (
                initialization.phase != "enabled"
                or not self._initialization_configuration_matches(initialization.draft)
            ):
                return _Handled(
                    Response(
                        "unavailable",
                        command.causal_id,
                        "initialization-configuration-mismatch",
                    ),
                    False,
                )
            receipt = self._store.save_source_envelope(
                payload.envelope,
                confirm_native_replay=True,
            )
            if receipt.relation == "possible-replay":
                business_source = receipt.business_source_causal_id
                if business_source is None:
                    related = (
                        None
                        if receipt.related_causal_id is None
                        else self._store.source_receipt(receipt.related_causal_id)
                    )
                    if related is None or related.native_event_digest is None:
                        self._store.reject_source_native_replay(
                            command.causal_id
                        )
                        return _Handled(
                            Response(
                                "unavailable",
                                command.causal_id,
                                "native-replay-proof-unavailable",
                            ),
                            True,
                        )
                    self._store.reject_source_native_replay(
                        command.causal_id
                    )
                    return _Handled(
                        Response(
                            "rejected",
                            command.causal_id,
                            "native-message-id-conflict",
                        ),
                        True,
                    )
                root_turn = self._store.daily_turn(business_source)
                if root_turn is None or root_turn.phase != "finalized":
                    return _Handled(
                        Response(
                            "unavailable",
                            command.causal_id,
                            "daily-source-native-replay-pending",
                            DailySourceMeta(business_source),
                        ),
                        False,
                    )
                self._store.mark_source_business_committed(command.causal_id)
                return _Handled(
                    Response(
                        "replayed",
                        command.causal_id,
                        "daily-source-native-replay",
                        DailySourceMeta(business_source),
                    ),
                    True,
                )
            return _Handled(
                Response("accepted", command.causal_id, "daily-source-admitted"),
                True,
            )
        unresolved_receipts = self._store.held_source_receipts()
        if len(unresolved_receipts) >= _MAX_UNRESOLVED_INITIALIZATION_SOURCES:
            # One stale resolution source may remain frozen while its exact
            # same-configuration successor occupies the active slot.  A
            # second rotation must restore/finish that successor rather than
            # accumulating sensitive bodies and cursor obligations forever.
            return _Handled(
                Response(
                    "unavailable",
                    command.causal_id,
                    "initialization-source-capacity-reached",
                ),
                False,
            )
        active_receipts = tuple(
            receipt
            for receipt in unresolved_receipts
            if receipt.managed_cursor_state == "held"
        )
        if len(active_receipts) > _MAX_HELD_INITIALIZATION_SOURCES:
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "initialization-source-capacity-reached",
                ),
                True,
            )
        if len(active_receipts) == _MAX_HELD_INITIALIZATION_SOURCES:
            stale_resolution = self._stale_initialization_resolution_slot(
                active_receipts
            )
            if stale_resolution is None:
                return _Handled(
                    Response(
                        "rejected",
                        command.causal_id,
                        "initialization-source-capacity-reached",
                    ),
                    True,
                )
            stale_slot, stale_candidate = stale_resolution
            remaining = tuple(
                receipt for receipt in active_receipts if receipt != stale_slot
            )
            resolution_status = self._initialization_resolution_slot_status(
                payload.envelope,
                remaining,
                required_configuration_digest=(
                    stale_candidate.initialization.configuration_digest
                ),
            )
            if resolution_status == "initialization-configuration-mismatch":
                return _Handled(
                    Response("unavailable", command.causal_id, resolution_status),
                    False,
                )
            if resolution_status != "ready":
                return _Handled(
                    Response(
                        "rejected",
                        command.causal_id,
                        "owner-resolution-required",
                    ),
                    True,
                )
            self._store.supersede_initialization_resolution_source(
                stale_slot.envelope.causal_id
            )
        elif len(active_receipts) == MAX_RESOLVED_SOURCE_CAUSAL_IDS:
            resolution_status = self._initialization_resolution_slot_status(
                payload.envelope,
                active_receipts,
            )
            if resolution_status == "initialization-configuration-mismatch":
                return _Handled(
                    Response("unavailable", command.causal_id, resolution_status),
                    False,
                )
            if resolution_status != "ready":
                return _Handled(
                    Response(
                        "rejected",
                        command.causal_id,
                        "owner-resolution-required",
                    ),
                    True,
                )
        self._store.save_source_envelope(payload.envelope)
        return _Handled(
            Response("accepted", command.causal_id, "initialization-source-admitted"),
            True,
        )

    def _handle_initialization_disclose(self, command: CommandEnvelope) -> _Handled:
        payload = command.payload
        verifier = self._health_init_verifier
        approved_asset = self._health_init_asset
        policy = self._admission_policy
        if not isinstance(payload, InitializationDisclosurePayload):
            raise ProtocolViolation("invalid initialization disclosure payload")
        if (
            type(verifier) is not HealthInitAttestor
            or type(approved_asset) is not HealthInitAsset
            or type(policy) is not AdmissionPolicy
            or payload.admission_policy != policy
        ):
            return _Handled(
                Response(
                    "unavailable",
                    command.causal_id,
                    "initialization-configuration-mismatch",
                ),
                False,
            )
        try:
            challenge = InitializationDisclosureChallenge(
                initialization=payload.initialization,
                disclosure=payload.disclosure,
                admission_policy=payload.admission_policy,
            )
        except AuthorityValidationError as exc:
            return _Handled(
                Response("rejected", command.causal_id, str(exc)),
                True,
            )
        if (
            not challenge.disclosure.matches(
                challenge.initialization,
                approved_asset,
            )
            or not verifier.verify(
                challenge.disclosure.skill_proof,
                challenge.initialization,
            )
        ):
            return _Handled(
                Response(
                    "unavailable",
                    command.causal_id,
                    "initialization-configuration-mismatch",
                ),
                False,
            )
        if not self._resolution_evidence_fits_transport(
            challenge,
            approved_asset,
        ):
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "initialization-resolution-capacity-exceeded",
                ),
                True,
            )
        try:
            self._store.save_initialization_disclosure_challenge(challenge)
        except AuthorityValidationError as exc:
            return _Handled(
                Response("rejected", command.causal_id, str(exc)),
                True,
            )
        return _Handled(
            Response(
                "accepted",
                command.causal_id,
                "initialization-disclosure-formed",
            ),
            True,
        )

    def _handle_initialization_prepare(
        self,
        command: CommandEnvelope,
        head: AuthoritySnapshot,
    ) -> _Handled:
        payload = command.payload
        verifier = self._health_init_verifier
        approved_asset = self._health_init_asset
        if not isinstance(payload, InitializationPreparePayload):
            raise ProtocolViolation("invalid initialization payload")
        initialization = payload.initialization
        reason = initialization.incomplete_reason
        if reason is not None:
            return _Handled(Response("rejected", command.causal_id, reason), True)
        source = self._store.source_envelope(initialization.admission_causal_id)
        if source is None:
            return _Handled(
                Response(
                    "unavailable",
                    command.causal_id,
                    "initialization-source-required",
                ),
                False,
            )
        try:
            consent = OwnerConsentEvidence.from_message_body(source.body)
            consent_fact = consent.disclosure.skill_proof.skill_use
            historical_asset = HealthInitAsset(
                canonical_name=consent_fact.canonical_name,
                version=consent_fact.version,
                asset_digest=consent_fact.asset_digest,
                disclosure_version=consent_fact.disclosure_version,
            )
        except AuthorityValidationError:
            consent = None
        if (
            consent is None
            or source.causal_id != initialization.admission_causal_id
            or not consent.matches(initialization, historical_asset)
        ):
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "owner-consent-evidence-required",
                ),
                True,
            )
        if consent.disclosure.skill_proof != payload.skill_proof:
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "health-init-proof-required",
                ),
                True,
            )
        challenge = self._store.initialization_disclosure_challenge(
            consent.disclosure.disclosure_id
        )
        if challenge is None or not challenge.matches_confirmation(consent):
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "health-init-disclosure-challenge-required",
                ),
                True,
            )
        fact = payload.skill_proof.skill_use
        asset_matches = (
            type(approved_asset) is HealthInitAsset
            and fact.canonical_name == approved_asset.canonical_name
            and fact.version == approved_asset.version
            and fact.asset_digest == approved_asset.asset_digest
            and fact.disclosure_version == approved_asset.disclosure_version
        )
        policy = self._admission_policy
        if (
            type(verifier) is not HealthInitAttestor
            or not asset_matches
            or not verifier.verify(payload.skill_proof, initialization)
            or type(policy) is not AdmissionPolicy
            or not challenge.issued_under(policy)
            or not policy.accepts(source)
        ):
            return _Handled(
                Response(
                    "unavailable",
                    command.causal_id,
                    "initialization-configuration-mismatch",
                ),
                False,
            )
        if not self._disclosure_precedes_source(consent.disclosure, source):
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "health-init-disclosure-order-invalid",
                ),
                True,
            )
        held_receipts = self._store.held_source_receipts()
        candidates: dict[str, OwnerConsentEvidence] = {}
        for receipt in held_receipts:
            if receipt.managed_cursor_state != "held":
                continue
            candidate_source = receipt.envelope
            candidate = self._historically_accepted_initialization_candidate(
                candidate_source
            )
            if candidate is not None:
                candidates[candidate_source.causal_id] = candidate
        if candidates.get(source.causal_id) != consent:
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "owner-consent-evidence-required",
                ),
                True,
            )
        other_candidate_ids = set(candidates) - {source.causal_id}
        declared_resolutions = set(consent.resolved_source_causal_ids)
        arrival_index = {
            receipt.envelope.causal_id: index
            for index, receipt in enumerate(held_receipts)
        }
        current_arrival_index = arrival_index[source.causal_id]
        conflicting_candidate_ids = {
            causal_id
            for causal_id, candidate in candidates.items()
            if causal_id != source.causal_id
            and candidate.initialization.configuration_digest
            != initialization.configuration_digest
        }
        if (
            source.causal_id in declared_resolutions
            or not declared_resolutions <= other_candidate_ids
            or not conflicting_candidate_ids <= declared_resolutions
            or any(
                arrival_index[causal_id] >= current_arrival_index
                for causal_id in declared_resolutions
            )
        ):
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "owner-resolution-required",
                ),
                True,
            )
        if self._store.initialization() is not None:
            raise ProtocolViolation("initialization already exists")

        resolved_source_causal_ids = tuple(
            receipt.envelope.causal_id
            for receipt in held_receipts
            if receipt.envelope.causal_id != source.causal_id
        )

        portrait = InitialPortrait()
        content = {
            "owner": initialization.to_storage(),
            "source_causal_id": source.causal_id,
            "skill_proof": payload.skill_proof.to_storage(),
            "owner_consent_evidence": consent.to_storage(),
            "key_id": self._store.key_id,
            "prepared_authority": head.to_storage(),
            "initial_portrait": portrait.to_storage(),
            "disclosed_topics": list(consent.disclosed_topics),
            "resolved_source_causal_ids": list(resolved_source_causal_ids),
        }
        revision_digest = stable_digest(content)
        transition_id = "initialization-transition:" + revision_digest.removeprefix("sha256:")
        record_id = "owner-initialization"
        draft = InitializationDraft(
            owner=initialization,
            source_causal_id=source.causal_id,
            skill_proof=payload.skill_proof,
            owner_consent_evidence=consent,
            key_id=self._store.key_id,
            prepared_authority=head,
            record_id=record_id,
            revision_digest=revision_digest,
            transition_id=transition_id,
            resolved_source_causal_ids=resolved_source_causal_ids,
            initial_portrait=portrait,
        )
        target = RevisionTarget(
            record_id=record_id,
            revision_digest=revision_digest,
            transition_id=transition_id,
            payload_digest=draft.content_digest,
        )
        self._store.write_record(
            record_id,
            "prepared",
            revision_digest,
            transition_id,
            PreparedTransition(target=target, base=head),
        )
        self._store.write_initialization("prepared", draft)
        self._store.clear_initialization_disclosure_challenges()
        return _Handled(
            Response("accepted", command.causal_id, "initialization-prepared"),
            True,
        )

    def _handle_native_cursor_result(self, command: CommandEnvelope) -> _Handled:
        payload = command.payload
        if not isinstance(payload, NativeCursorResultPayload):
            raise ProtocolViolation("invalid native cursor result")
        if self._business_transition_id_for_source(payload.source_causal_id) is None:
            raise ProtocolViolation("native cursor source mismatch")
        receipt = self._store.source_receipt(payload.source_causal_id)
        if receipt is None or receipt.envelope.native_cursor != payload.native_cursor:
            raise ProtocolViolation("native cursor mismatch")
        if receipt.native_cursor_state != "executing":
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "native-cursor-result-terminal",
                ),
                True,
            )
        self._store.mark_native_cursor_state(payload.source_causal_id, payload.status)
        if payload.status == "unknown":
            return _Handled(
                Response("unknown", command.causal_id, "native-cursor-unknown"),
                True,
            )
        return _Handled(
            Response("accepted", command.causal_id, "native-cursor-advanced"),
            True,
        )

    @staticmethod
    def _resolution_evidence_fits_transport(
        challenge: InitializationDisclosureChallenge,
        approved_asset: HealthInitAsset,
    ) -> bool:
        """Prove one later decision can enumerate the bounded prior-source set."""

        try:
            confirmed = replace(
                challenge.initialization,
                owner_consent=True,
                first_hop_route_consent=True,
            )
            # A JSON-escaped ASCII control byte occupies six transport bytes.
            # These unique 256-byte identifiers therefore bound every legal
            # causal identifier's contribution to the canonical message body.
            worst_case_source_ids = tuple(
                ("\x00" * 255) + chr(index + 1)
                for index in range(MAX_RESOLVED_SOURCE_CAUSAL_IDS)
            )
            evidence = OwnerConsentEvidence.for_initialization(
                confirmed,
                approved_asset,
                challenge.disclosure,
                owner_confirmed=True,
                first_hop_route_confirmed=True,
                resolved_source_causal_ids=worst_case_source_ids,
            )
            return (
                len(evidence.to_message_body().encode("utf-8"))
                <= MAX_MESSAGE_BODY_BYTES
            )
        except (AuthorityValidationError, UnicodeEncodeError):
            return False

    def _historically_accepted_initialization_candidate(
        self,
        source: SourceEnvelope,
    ) -> OwnerConsentEvidence | None:
        """Validate a source against its integrity-protected accepted challenge.

        Historical candidates continue to count during asset or attestor
        rotation.  Their challenge was verified by core when persisted; the
        authenticated store, exact challenge binding, and original asset
        metadata preserve that fact without asking the new verifier to bless
        the old proof again.
        """

        try:
            candidate = OwnerConsentEvidence.from_message_body(source.body)
            fact = candidate.disclosure.skill_proof.skill_use
            historical_asset = HealthInitAsset(
                canonical_name=fact.canonical_name,
                version=fact.version,
                asset_digest=fact.asset_digest,
                disclosure_version=fact.disclosure_version,
            )
            challenge = self._store.initialization_disclosure_challenge(
                candidate.disclosure.disclosure_id
            )
        except AuthorityValidationError:
            return None
        if (
            candidate.admission_causal_id != source.causal_id
            or challenge is None
            or (
                challenge.admission_policy is not None
                and not challenge.admission_policy.accepts(source)
            )
            or not challenge.matches_confirmation(candidate)
            or not candidate.matches(candidate.initialization, historical_asset)
            or not self._disclosure_precedes_source(candidate.disclosure, source)
        ):
            return None
        return candidate

    def _currently_approved_initialization_candidate(
        self,
        source: SourceEnvelope,
    ) -> OwnerConsentEvidence | None:
        candidate = self._historically_accepted_initialization_candidate(source)
        approved_asset = self._health_init_asset
        verifier = self._health_init_verifier
        policy = self._admission_policy
        challenge = (
            None
            if candidate is None
            else self._store.initialization_disclosure_challenge(
                candidate.disclosure.disclosure_id
            )
        )
        if (
            candidate is None
            or type(approved_asset) is not HealthInitAsset
            or type(verifier) is not HealthInitAttestor
            or type(policy) is not AdmissionPolicy
            or challenge is None
            or not challenge.issued_under(policy)
            or not policy.accepts(source)
            or not candidate.matches(candidate.initialization, approved_asset)
            or not verifier.verify(
                candidate.disclosure.skill_proof,
                candidate.initialization,
            )
        ):
            return None
        return candidate

    def _initialization_resolution_slot_status(
        self,
        source: SourceEnvelope,
        prior_receipts: tuple[SourceReceipt, ...],
        *,
        required_configuration_digest: str | None = None,
    ) -> str:
        historical = self._historically_accepted_initialization_candidate(source)
        if historical is None:
            return "owner-resolution-required"
        candidate = self._currently_approved_initialization_candidate(source)
        if candidate is None:
            # A challenge accepted under another live asset/key/policy may
            # become valid again after an operator restores that configuration.
            # Do not persist a replay result for this transient condition.
            return "initialization-configuration-mismatch"
        if (
            required_configuration_digest is not None
            and candidate.initialization.configuration_digest
            != required_configuration_digest
        ):
            return "owner-resolution-required"
        if not self._candidate_resolves_prior_sources(
            candidate,
            source.causal_id,
            prior_receipts,
        ):
            return "owner-resolution-required"
        return "ready"

    def _candidate_resolves_prior_sources(
        self,
        candidate: OwnerConsentEvidence,
        source_causal_id: str,
        prior_receipts: tuple[SourceReceipt, ...],
    ) -> bool:
        prior_candidates: dict[str, OwnerConsentEvidence] = {}
        for receipt in prior_receipts:
            if receipt.managed_cursor_state != "held":
                continue
            prior = self._historically_accepted_initialization_candidate(
                receipt.envelope
            )
            if prior is not None:
                prior_candidates[receipt.envelope.causal_id] = prior
        declared = set(candidate.resolved_source_causal_ids)
        prior_ids = set(prior_candidates)
        conflicting = {
            causal_id
            for causal_id, prior in prior_candidates.items()
            if prior.initialization.configuration_digest
            != candidate.initialization.configuration_digest
        }
        return (
            source_causal_id not in declared
            and declared <= prior_ids
            and conflicting <= declared
        )

    def _stale_initialization_resolution_slot(
        self,
        active_receipts: tuple[SourceReceipt, ...],
    ) -> tuple[SourceReceipt, OwnerConsentEvidence] | None:
        if len(active_receipts) != _MAX_HELD_INITIALIZATION_SOURCES:
            return None
        slot = active_receipts[-1]
        historical = self._historically_accepted_initialization_candidate(
            slot.envelope
        )
        if (
            historical is None
            or self._currently_approved_initialization_candidate(slot.envelope)
            is not None
            or not self._candidate_resolves_prior_sources(
                historical,
                slot.envelope.causal_id,
                active_receipts[:-1],
            )
        ):
            return None
        return slot, historical

    @staticmethod
    def _disclosure_precedes_source(
        disclosure: InitializationDisclosure,
        source: SourceEnvelope,
    ) -> bool:
        if source.protocol_timestamp is None:
            return False
        try:
            used_at = datetime.fromisoformat(disclosure.skill_proof.skill_use.used_at)
            protocol_timestamp = datetime.fromisoformat(source.protocol_timestamp)
            received_at = datetime.fromisoformat(source.received_at)
        except (TypeError, ValueError):
            return False
        return used_at < protocol_timestamp and used_at < received_at

    def _handle_state(self, command: CommandEnvelope, head: AuthoritySnapshot) -> _Handled:
        payload = command.payload
        if not isinstance(payload, (StateCandidatePayload, StateCommitPayload)):
            raise ProtocolViolation("invalid state payload")
        record_id = payload.record_id
        revision_digest = payload.revision_digest
        transition_id = payload.transition_id
        current = self._store.record(record_id)

        if command.action == "state.candidate":
            if not isinstance(payload, StateCandidatePayload):
                raise ProtocolViolation("invalid candidate payload")
            target = RevisionTarget(
                record_id=payload.record_id,
                revision_digest=payload.revision_digest,
                transition_id=payload.transition_id,
                payload_digest=payload.payload_digest,
            )
            if current is not None:
                raise ProtocolViolation("record already exists")
            self._store.write_record(
                target.record_id,
                "candidate",
                target.revision_digest,
                target.transition_id,
                target,
            )
            return _Handled(Response("accepted", command.causal_id, "candidate-recorded"), True)

        if current is None:
            raise ProtocolViolation("record is required for this action")
        current_state = current.state
        current_revision = current.revision_digest
        current_transition = current.transition_id
        current_payload = current.payload
        if current_revision != revision_digest or current_transition != transition_id:
            raise ProtocolViolation("record transition changed")

        if command.action == "state.prepare":
            if not isinstance(payload, StateCandidatePayload):
                raise ProtocolViolation("invalid prepare payload")
            target = RevisionTarget(
                record_id=payload.record_id,
                revision_digest=payload.revision_digest,
                transition_id=payload.transition_id,
                payload_digest=payload.payload_digest,
            )
            if current_state != "candidate":
                raise ProtocolViolation("record is not a candidate")
            if not isinstance(current_payload, RevisionTarget):
                raise KeyUnavailable("invalid candidate state")
            candidate = current_payload
            if candidate != target:
                raise ProtocolViolation("record transition changed")
            prepared = PreparedTransition(target=target, base=head)
            self._store.write_record(
                target.record_id,
                "prepared",
                target.revision_digest,
                target.transition_id,
                prepared,
            )
            return _Handled(Response("accepted", command.causal_id, "revision-prepared"), True)

        if command.action == "state.finalize":
            if not isinstance(payload, StateCommitPayload):
                raise ProtocolViolation("invalid finalize payload")
            writer_fence = payload.writer_fence
            if writer_fence != head.writer_fence:
                self._closed_reason = "stale-writer-fence"
                return _Handled(Response("unavailable", command.causal_id, self._closed_reason), False)
            if current_state in {"prepared", "unknown"}:
                pending = self._store.pending_for_record(record_id)
                if pending is not None:
                    # A pending journal belongs to the original state.commit.
                    # Only that exact command may reconcile its ambiguous CAS;
                    # a separate finalize causal ID cannot claim or erase it.
                    return _Handled(
                        Response("unavailable", command.causal_id, "pending-command-owner-required"),
                        False,
                    )
                return _Handled(
                    Response("unavailable", command.causal_id, "pending-command-missing"),
                    False,
                )
            if current_state != "committed":
                raise ProtocolViolation("record is not ready to finalize")
            committed = self._finalization_authority(current_state, current_payload, head)
            if isinstance(committed, _Handled):
                return self._with_causal_id(committed, command.causal_id)
            if not committed.prepared.target.matches_commit(
                record_id=record_id,
                revision_digest=revision_digest,
                transition_id=transition_id,
            ):
                raise ProtocolViolation("record transition changed")
            initialization = self._store.initialization()
            transition_kind = self._business_transition_kind(record_id)
            if self._admission_policy is not None and transition_kind is None:
                return _Handled(
                    Response(
                        "unavailable",
                        command.causal_id,
                        "initialization-configuration-mismatch",
                    ),
                    False,
                )
            if self._current_writer_proof(head) is None:
                return _Handled(
                    Response("unavailable", command.causal_id, "current-writer-holder-missing"),
                    False,
                )
            daily = (
                self._store.daily_turn_for_record(record_id)
                if transition_kind == "daily"
                else None
            )
            self._store.write_finalized_record(
                record_id,
                revision_digest,
                transition_id,
                committed,
                committed.committed,
            )
            if (
                initialization is not None
                and initialization.draft.record_id == record_id
            ):
                self._store.write_initialization("enabled", initialization.draft)
                self._store.mark_source_business_committed_many(
                    initialization.draft.source_causal_ids
                )
            elif transition_kind == "daily":
                if daily is None:
                    raise KeyUnavailable("daily turn aggregate missing")
                if daily.draft.turn_kind == "evidence-stage":
                    self._store.finalize_daily_evidence_stage(daily.draft)
                else:
                    self._store.finalize_daily_turn(daily.draft)
                    self._store.mark_daily_source_family_business_committed(
                        daily.draft.source_causal_id
                    )
            self._closed_reason = None
            return _Handled(Response("accepted", command.causal_id, "revision-finalized"), True)

        raise ProtocolViolation("unknown state action")

    def _finalization_authority(
        self,
        state: str,
        payload: object,
        head: AuthoritySnapshot,
        binding: CurrentHeadRecoveryBinding | None = None,
    ) -> CommittedTransition | _Handled:
        if state == "committed":
            if not isinstance(payload, CommittedTransition):
                raise KeyUnavailable("invalid committed state")
            committed = payload
            mismatch = committed.committed.mismatch_reason(head)
            if mismatch is not None:
                self._closed_reason = "stale-writer-fence"
                return _Handled(Response("unavailable", None, self._closed_reason), False)
            if not self._target_matches_authority(committed.prepared, head):
                return _Handled(Response("unavailable", None, "transition-recovery-mismatch"), False)
            return committed

        if not isinstance(payload, PreparedTransition):
            raise KeyUnavailable("invalid prepared state")
        if binding is None:
            return _Handled(Response("unavailable", None, "transition-recovery-unconfirmed"), False)
        prepared = payload
        if prepared.base.installation_id != head.installation_id:
            self._closed_reason = "prepared-installation-mismatch"
            return _Handled(Response("unavailable", None, self._closed_reason), False)
        recovery_request = AdvanceIdentity(
            expected=prepared.base,
            transition_id=prepared.target.transition_id,
            revision_digest=prepared.target.revision_digest,
            writer_fence=prepared.base.writer_fence,
            operation_digest=binding.command_digest,
        )
        try:
            lookup_receipt = self._lookup_transition(recovery_request)
        except HeadUnknown:
            return _Handled(Response("unknown", None, "current-head-unknown"), False)
        except TransitionNotFound:
            return _Handled(Response("unavailable", None, "transition-not-found"), False)
        except HeadConflict:
            return _Handled(Response("unavailable", None, "current-head-lookup-conflict"), False)
        except HeadTimeout:
            return _Handled(Response("unavailable", None, "current-head-timeout"), False)
        except HeadTerminal:
            self._latch_terminal()
            return _Handled(Response("unavailable", None, self._closed_reason), False)
        except MalformedCurrentHeadResponse:
            return _Handled(Response("unavailable", None, "current-head-malformed"), False)
        except CurrentHeadError:
            return _Handled(Response("unavailable", None, "current-head-lookup-unclassified"), False)
        if lookup_receipt.request != recovery_request:
            return _Handled(Response("unavailable", None, "transition-lookup-expected-mismatch"), False)
        lookup = lookup_receipt.applied.as_authority()
        if lookup.mismatch_reason(head) is not None:
            return _Handled(Response("unavailable", None, "current-head-transition-lookup-mismatch"), False)
        try:
            # A lookup receipt is historical proof, not a current authority
            # proof.  Re-read after lookup so another writer cannot overtake
            # this transition between remote recovery and local acceptance.
            confirmed = self._confirm_advanced_head(lookup)
        except HeadUnknown:
            return _Handled(Response("unknown", None, "current-head-unknown"), False)
        except HeadTerminal:
            self._latch_terminal()
            return _Handled(Response("unavailable", None, self._closed_reason), False)
        except HeadConflict:
            return _Handled(Response("unavailable", None, "current-head-confirmation-conflict"), False)
        except HeadTimeout:
            return _Handled(Response("unavailable", None, "current-head-timeout"), False)
        except MalformedCurrentHeadResponse:
            return _Handled(Response("unavailable", None, "current-head-malformed"), False)
        except CurrentHeadError:
            return _Handled(Response("unavailable", None, "current-head-confirmation-unclassified"), False)
        if not self._target_matches_authority(prepared, lookup):
            return _Handled(Response("unavailable", None, "transition-recovery-mismatch"), False)
        return CommittedTransition(prepared=prepared, committed=confirmed)

    @staticmethod
    def _with_causal_id(handled: _Handled, causal_id: str) -> _Handled:
        return _Handled(
            Response(
                handled.response.status,
                causal_id,
                handled.response.reason_code,
                handled.response.meta,
            ),
            handled.persist_receipt,
        )

    def _handle_effect_request(self, command: CommandEnvelope, head: AuthoritySnapshot) -> _Handled:
        payload = command.payload
        if not isinstance(payload, EffectRequestPayload):
            raise ProtocolViolation("invalid effect request payload")
        effect_kind = payload.effect_kind
        if effect_kind == "contact-delivery":
            return _Handled(
                Response("rejected", command.causal_id, "contact-delivery-not-supported-in-ticket-110"),
                True,
            )
        if effect_kind != "model-work":
            return _Handled(
                Response("rejected", command.causal_id, "delivery-not-supported-in-ticket-110"),
                True,
            )
        intent = EffectIntent(
            effect_id=self._effect_id(command.causal_id),
            effect_kind=effect_kind,
            intent_digest=payload.request_digest,
            authority=head,
        )
        self._store.write_effect(intent.effect_id, "intent", intent)
        return _Handled(
            Response("accepted", command.causal_id, "effect-intent-issued", EffectIntentMeta(intent)),
            True,
        )

    @staticmethod
    def _effect_id(causal_id: str) -> str:
        """Derive a bounded opaque effect ID from an already bounded causal ID."""

        return "effect:" + hashlib.sha256(causal_id.encode("utf-8")).hexdigest()

    def _execution_capability_session(
        self,
        authority: AuthoritySnapshot,
        writer_proof: WriterFenceProof,
    ) -> ExecutionCapabilitySession | None:
        session = self._execution_capability_sessions.get(authority)
        if session is not None:
            try:
                if session.active():
                    return session
            except Exception:
                pass
        self._execution_capability_sessions.pop(authority, None)
        vault = self._execution_capability_vault
        if vault is None:
            return None
        session = vault.acquire_or_resume_session(authority, writer_proof)
        if (
            session is None
            or not callable(getattr(session, "active", None))
            or not callable(getattr(session, "mint", None))
            or not callable(getattr(session, "recover", None))
            or not callable(getattr(session, "release", None))
        ):
            return None
        try:
            if not session.active():
                return None
        except Exception:
            return None
        self._execution_capability_sessions[authority] = session
        return session

    def _completion_capability_is_held(
        self,
        execution: ExecutingEffect,
        completion_capability: str,
        writer_proof: WriterFenceProof,
    ) -> bool:
        """Verify a raw completion bearer locally, never at current-head."""

        try:
            holder_id = holder_id_for(completion_capability)
        except ValueError:
            return False
        if holder_id != execution.lease.holder_id:
            return False
        session = self._execution_capability_session(execution.intent.authority, writer_proof)
        if session is None:
            return False
        expected = session.recover(ExecutionCapabilityBinding.for_execution(execution), holder_id)
        return expected is not None and secrets.compare_digest(expected, completion_capability)

    @staticmethod
    def _canonical_effect_intent_from_caller(value: object) -> EffectIntent | None:
        """Accept only an exact, primitive-safe copy of a core-issued intent."""

        if type(value) is not EffectIntent:
            return None
        try:
            authority = value.authority
            if type(authority) is not AuthoritySnapshot:
                return None
            validate_ticket110_effect_kind(value.effect_kind)
            return EffectIntent(
                effect_id=value.effect_id,
                effect_kind=value.effect_kind,
                intent_digest=value.intent_digest,
                authority=AuthoritySnapshot(
                    installation_id=authority.installation_id,
                    generation=authority.generation,
                    revision_digest=authority.revision_digest,
                    transition_id=authority.transition_id,
                    writer_fence=authority.writer_fence,
                    terminal=authority.terminal,
                    site=authority.site,
                ),
            )
        except Exception:
            return None

    def claim_effect_execution(self, intent: EffectIntent) -> EffectExecutionGrant | None:
        """Claim an effect under a durable terminal-observation tripwire."""

        with self._lifecycle_lock:
            if self._closed:
                return None
            return self._claim_effect_execution_open(intent)

    def _claim_effect_execution_open(self, intent: EffectIntent) -> EffectExecutionGrant | None:
        """Run an admitted effect claim while its writer holder remains live."""

        requested_intent = self._canonical_effect_intent_from_caller(intent)
        if requested_intent is None:
            return None
        try:
            with self._store.serialized():
                self._store.verify_key()
                if self._terminal_closed():
                    return None
                if self._admission_policy is not None:
                    initialization = self._store.initialization()
                    if (
                        initialization is None
                        or initialization.phase != "enabled"
                        or not self._initialization_configuration_matches(
                            initialization.draft
                        )
                    ):
                        return None
                if self._writer_entry_preflight() is not None:
                    return None
                # Claim performs remote reads/acquire after local claim state is
                # written.  Persist the terminal tripwire before entering that
                # transaction so a process stop cannot lose a terminal read.
                self._enter_current_head_guard()
                try:
                    return self._claim_effect_execution_guarded(requested_intent)
                finally:
                    self._exit_current_head_guard()
        except KeyUnavailable:
            self._closed_reason = "health-key-unavailable"
        except StoreUnavailable:
            self._closed_reason = "health-state-unavailable"
        return None

    def _claim_effect_execution_guarded(self, intent: EffectIntent) -> EffectExecutionGrant | None:
        """Issue an unforgeable completion grant only after a proved lease claim.

        The durable ``claiming`` phase is committed before the remote acquire.
        It contains only ``H(completion_capability)``; a cloned store can see
        the binding but cannot re-acquire, execute, or terminalize the effect.
        The same core can recover a lost acquire response using its local
        capability, then must read back both the remote lease and authority.
        """

        try:
            with self._store.serialized():
                self._store.verify_key()
                if self._terminal_closed():
                    return None

                capability: str | None = None
                claim: ClaimingEffect | None = None
                issued_intent: EffectIntent | None = None
                with self._store.transaction():
                    head = self._read_head()
                    if head.terminal:
                        self._latch_terminal()
                        return None
                    writer_proof = self._current_writer_proof(head)
                    if writer_proof is None:
                        return None
                    authority = self._store.finalized_authority()
                    if authority is None or authority.mismatch_reason(head) is not None:
                        return None
                    if not self._store.verify_integrity(authority):
                        return None
                    if self._store.has_pending_commands():
                        return None
                    unresolved_states = self._store.unresolved_states()
                    if any(state in {"prepared", "committed", "unknown"} for state in unresolved_states):
                        return None
                    stored = self._store.effect(intent.effect_id)
                    if stored is None:
                        return None
                    unresolved_effects = self._store.unresolved_effects()
                    if unresolved_effects != (intent.effect_id,):
                        return None
                    if stored.state == "intent" and type(stored.payload) is EffectIntent:
                        issued_intent = stored.payload
                        if issued_intent != intent or issued_intent.authority.mismatch_reason(head) is not None:
                            return None
                        session = self._execution_capability_session(issued_intent.authority, writer_proof)
                        if session is None:
                            return None
                        provisional_claim = ClaimingEffect(
                            intent=issued_intent,
                            holder_id="holder:pending",
                            vault_claim_ref="claim:" + secrets.token_urlsafe(24),
                        )
                        binding = ExecutionCapabilityBinding.for_claim(provisional_claim)
                        capability = session.mint(binding)
                        if capability is None:
                            return None
                        claim = ClaimingEffect(
                            intent=issued_intent,
                            holder_id=holder_id_for(capability),
                            vault_claim_ref=provisional_claim.vault_claim_ref,
                        )
                        self._store.write_effect(issued_intent.effect_id, "claiming", claim)
                    elif stored.state == "claiming" and type(stored.payload) is ClaimingEffect:
                        claim = stored.payload
                        issued_intent = claim.intent
                        if type(issued_intent) is not EffectIntent or issued_intent != intent:
                            return None
                        if issued_intent.authority.mismatch_reason(head) is not None:
                            return None
                        session = self._execution_capability_session(issued_intent.authority, writer_proof)
                        if session is None:
                            return None
                        capability = session.recover(
                            ExecutionCapabilityBinding.for_claim(claim),
                            claim.holder_id,
                        )
                        if capability is None or holder_id_for(capability) != claim.holder_id:
                            # A process that did not mint the capability may
                            # observe the unresolved claim but cannot take it.
                            return None
                    else:
                        return None

                if capability is None or claim is None or issued_intent is None:
                    return None
                # The first durable phase has committed.  Remote acquisition
                # occurs outside the SQLite transaction so an I/O failure can
                # never roll it back and hand the effect to another holder.
                head = self._read_head()
                if head.terminal:
                    self._latch_terminal()
                    return None
                if issued_intent.authority.mismatch_reason(head) is not None:
                    return None
                writer_proof = self._current_writer_proof(head)
                if writer_proof is None:
                    return None
                request = ExecutionLeaseRequest(
                    expected=head,
                    effect_id=issued_intent.effect_id,
                    intent_digest=issued_intent.intent_digest,
                    writer_fence=head.writer_fence,
                    holder_id=claim.holder_id,
                    writer_proof=writer_proof,
                )
                acquired = self._acquire_execution_lease(request)
                observed = self._lookup_execution_lease(request.identity())
                if acquired != observed or observed.released:
                    return None
                confirmed = self._read_head()
                if confirmed.terminal:
                    self._latch_terminal()
                    return None
                if observed.lease.authority.mismatch_reason(confirmed) is not None:
                    return None
                execution = ExecutingEffect(
                    intent=issued_intent,
                    lease=observed.lease,
                    vault_claim_ref=claim.vault_claim_ref,
                )
                with self._store.transaction():
                    stored = self._store.effect(issued_intent.effect_id)
                    if stored is None or stored.state != "claiming" or stored.payload != claim:
                        return None
                    self._store.write_effect(issued_intent.effect_id, "executing", execution)
                return EffectExecutionGrant(
                    lease=observed.lease,
                    completion_capability=capability,
                )
        except KeyUnavailable:
            self._closed_reason = "health-key-unavailable"
        except StoreUnavailable:
            self._closed_reason = "health-state-unavailable"
        except HeadTerminal:
            self._latch_terminal()
        except (ExecutionLeaseNotFound, HeadConflict, HeadTimeout, HeadUnknown, CurrentHeadError):
            pass
        return None

    def source_envelope(self, causal_id: str) -> SourceEnvelope | None:
        """Return one admitted envelope through the managed core read seam."""

        with self._lifecycle_lock:
            if self._closed:
                return None
            try:
                if self._probe_open().state is not ProbeState.HEALTHY:
                    return None
                return self._store.source_envelope(causal_id)
            except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
                return None

    def source_receipt(self, causal_id: str) -> SourceReceipt | None:
        """Return one content-bearing receipt only through the managed read seam."""

        with self._lifecycle_lock:
            if self._closed:
                return None
            try:
                if self._probe_open().state is not ProbeState.HEALTHY:
                    return None
                return self._store.source_receipt(causal_id)
            except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
                return None

    def daily_state(self) -> DailyHealthState:
        """Return managed daily evidence/portrait state after full integrity proof."""

        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError("daily-state-unavailable")
            try:
                if self._probe_open().state is not ProbeState.HEALTHY:
                    raise AuthorityValidationError("daily-state-unavailable")
                self._store.verify_key()
                authority = self._store.finalized_authority()
                initialization = self._store.initialization()
                if (
                    authority is None
                    or not self._store.verify_integrity(authority)
                    or initialization is None
                    or initialization.phase != "enabled"
                    or not self._initialization_configuration_matches(initialization.draft)
                    or type(self._daily_skill_verifier) is not DailySkillAttestor
                    or type(self._daily_skill_bundle) is not DailySkillBundle
                ):
                    raise AuthorityValidationError("daily-state-unavailable")
                return self._store.daily_state()
            except (KeyUnavailable, StoreUnavailable) as exc:
                raise AuthorityValidationError("daily-state-unavailable") from exc

    @contextmanager
    def daily_turn_runtime_preparation(
        self,
        source_causal_id: str,
        *,
        committed_evidence_stage: DailyTurnDraft | None = None,
    ) -> Iterator[DailyTurnRuntimePreparation]:
        """Serialize Skill formation with its strict ``turn.prepare`` command.

        The lifecycle lock remains held across the caller's runtime work and
        re-entrant command invocation, but no SQLite transaction or store lock
        crosses the yield.  A different source's durable lease is reported
        before any model-backed Skill may run.
        """

        validate_opaque_text(source_causal_id, "source causal identifier")
        if committed_evidence_stage is not None and (
            type(committed_evidence_stage) is not DailyTurnDraft
            or committed_evidence_stage.turn_kind != "evidence-stage"
            or committed_evidence_stage.source_causal_id != source_causal_id
        ):
            raise AuthorityValidationError("invalid daily evidence continuation")
        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError("daily-authority-unavailable")
            try:
                self._store.verify_key()
                unresolved = self._store.unresolved_daily_turn()
            except (KeyUnavailable, StoreUnavailable) as exc:
                raise AuthorityValidationError(
                    "daily-authority-unavailable"
                ) from exc
            if (
                unresolved is not None
                and unresolved.source_causal_id != source_causal_id
            ):
                yield DailyTurnRuntimePreparation(None, "daily-turn-busy")
                return
            if committed_evidence_stage is None:
                if unresolved is not None:
                    yield DailyTurnRuntimePreparation(
                        None,
                        "daily-turn-recovery-required",
                    )
                    return
            elif (
                unresolved is None
                or unresolved.phase != "evidence-finalized"
                or unresolved.draft != committed_evidence_stage
            ):
                yield DailyTurnRuntimePreparation(
                    None,
                    "daily-turn-recovery-required",
                )
                return
            # This re-enters the same lifecycle lock only for the bounded head,
            # writer and configuration proof.  Its store locks are released
            # before control is yielded to DailySkillRuntime.
            generation = self.daily_prepare_generation()
            yield DailyTurnRuntimePreparation(generation)

    def daily_prepare_generation(self) -> int:
        """Return the currently verified writer generation for a new daily prepare."""

        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError("daily-authority-unavailable")
            with self._store.serialized():
                try:
                    self._store.verify_key()
                    authority = self._store.finalized_authority()
                    initialization = self._store.initialization()
                    if (
                        authority is None
                        or not self._store.verify_integrity(authority)
                        or initialization is None
                        or initialization.phase != "enabled"
                        or not self._initialization_configuration_matches(
                            initialization.draft
                        )
                        or self._store.current_head_observation_guard() is not None
                        or self._terminal_closed()
                        or self._writer_entry_preflight() is not None
                    ):
                        raise AuthorityValidationError(
                            "daily-authority-unavailable"
                        )
                    self._enter_current_head_guard()
                    try:
                        head = self._read_head()
                        if (
                            self._probe_for_head(head).state is not ProbeState.HEALTHY
                            or self._current_writer_proof(head) is None
                        ):
                            raise AuthorityValidationError(
                                "daily-authority-unavailable"
                            )
                        return head.generation
                    finally:
                        self._exit_current_head_guard()
                except HeadTerminal as exc:
                    self._latch_terminal()
                    raise AuthorityValidationError(
                        "daily-authority-unavailable"
                    ) from exc
                except (KeyUnavailable, StoreUnavailable, CurrentHeadError) as exc:
                    raise AuthorityValidationError(
                        "daily-authority-unavailable"
                    ) from exc

    def daily_turn_post_stage_state(
        self,
        source_causal_id: str,
    ) -> DailyHealthState:
        """Materialize one durable evidence stage without publishing it."""

        validate_opaque_text(source_causal_id, "source causal identifier")
        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError("daily-stage-state-unavailable")
            try:
                if self._probe_open().state is not ProbeState.HEALTHY:
                    raise AuthorityValidationError("daily-stage-state-unavailable")
                self._store.verify_key()
                authority = self._store.finalized_authority()
                if authority is None or not self._store.verify_integrity(authority):
                    raise AuthorityValidationError("daily-stage-state-unavailable")
                daily = self._store.daily_turn(source_causal_id)
                if (
                    daily is None
                    or daily.phase != "evidence-finalized"
                    or type(daily.draft) is not DailyTurnDraft
                    or daily.evidence_state_digest is None
                ):
                    raise AuthorityValidationError("daily-stage-state-unavailable")
                state = self._store.daily_state().apply_evidence_stage(daily.draft)
                if state.digest != daily.evidence_state_digest:
                    raise KeyUnavailable("evidence stage state mismatch")
                return state
            except (KeyUnavailable, StoreUnavailable) as exc:
                raise AuthorityValidationError(
                    "daily-stage-state-unavailable"
                ) from exc

    def daily_turn_status(self, source_causal_id: str) -> DailyTurnStatus | None:
        """Project one exact durable turn so Plugin can resume without rerunning Skills."""

        validate_opaque_text(source_causal_id, "source causal identifier")
        with self._lifecycle_lock:
            if self._closed:
                return None
            try:
                self._store.verify_key()
                authority = self._store.finalized_authority()
                if authority is None or not self._store.verify_integrity(authority):
                    return None
                daily = self._store.daily_turn(source_causal_id)
                if daily is None:
                    return None
                record = self._store.record(daily.record_id)
                if record is None:
                    raise KeyUnavailable("daily turn transition missing")
                expected = {
                    "prepared": "prepared",
                    "unknown": "unknown",
                    "committed": "committed",
                    "evidence-finalized": "final",
                    "finalized": "final",
                }[daily.phase]
                identity = daily.draft if daily.draft is not None else daily.terminal
                if identity is None:
                    raise KeyUnavailable("daily turn identity missing")
                if (
                    record.state != expected
                    or record.revision_digest != identity.revision_digest
                    or record.transition_id != identity.transition_id
                ):
                    raise KeyUnavailable("daily turn transition mismatch")
                payload = record.payload
                if isinstance(payload, PreparedTransition):
                    prepared = payload
                elif isinstance(payload, CommittedTransition):
                    prepared = payload.prepared
                else:
                    raise KeyUnavailable("daily turn authority missing")
                return DailyTurnStatus(
                    daily.phase,
                    daily.draft,
                    None if daily.phase == "finalized" else daily.result,
                    prepared.base,
                    daily.terminal,
                )
            except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
                return None

    def daily_turn_result(self, source_causal_id: str) -> DailyTurnResult | None:
        """Release one finalized owner result only after a fresh strong read."""

        validate_opaque_text(source_causal_id, "source causal identifier")
        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError("daily-turn-result-unavailable")
            report = self._probe_open()
            if report.state is not ProbeState.HEALTHY:
                raise AuthorityValidationError(
                    report.reason_code or "daily-turn-result-unavailable"
                )
            try:
                daily = self._store.daily_turn(source_causal_id)
                if (
                    daily is None
                    or daily.phase != "finalized"
                    or daily.draft is not None
                    or daily.terminal is None
                ):
                    raise AuthorityValidationError(
                        "daily-turn-result-unavailable"
                    )
                return daily.result
            except (KeyUnavailable, StoreUnavailable) as exc:
                raise AuthorityValidationError(
                    "daily-turn-result-unavailable"
                ) from exc

    def initialization_status(self) -> InitializationProjection:
        """Return the durable product phase without treating probe liveness as enablement."""

        with self._lifecycle_lock:
            if self._closed:
                return InitializationProjection.cannot_confirm()
            try:
                self._store.verify_key()
                authority = self._store.finalized_authority()
                if authority is None or not self._store.verify_integrity(authority):
                    return InitializationProjection.cannot_confirm()
                stored = self._store.initialization()
                if stored is None:
                    return InitializationProjection.uninitialized()
                return stored.draft.projection(
                    phase=stored.phase,
                    enabled=stored.phase == "enabled",
                )
            except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
                return InitializationProjection.cannot_confirm()

    def initialization_disclosure_replay(
        self,
        initialization: OwnerInitialization,
        admission_policy: AdmissionPolicy,
    ) -> tuple[InitializationDisclosure | None, int]:
        """Return an exact durable pre-consent challenge and local generation."""

        if type(initialization) is not OwnerInitialization:
            raise AuthorityValidationError("invalid owner initialization")
        if type(admission_policy) is not AdmissionPolicy:
            raise AuthorityValidationError("initialization-configuration-mismatch")
        if (
            initialization.owner_consent is not False
            or initialization.first_hop_route_consent is not False
        ):
            raise AuthorityValidationError(
                "initialization-disclosure-before-consent-required"
            )
        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError("initialization-state-unavailable")
            if self._admission_policy != admission_policy:
                raise AuthorityValidationError("initialization-configuration-mismatch")
            report = self._probe_open()
            if report.state is not ProbeState.HEALTHY:
                raise AuthorityValidationError(report.reason_code)
            try:
                self._store.verify_key()
                authority = self._store.finalized_authority()
                if authority is None or not self._store.verify_integrity(authority):
                    raise AuthorityValidationError("initialization-state-unavailable")
                if self._store.initialization() is not None:
                    raise AuthorityValidationError("initialization already exists")
                challenge = self._store.initialization_disclosure_for_workflow(
                    initialization.workflow_id
                )
            except (KeyUnavailable, StoreUnavailable) as exc:
                raise AuthorityValidationError(
                    "initialization-state-unavailable"
                ) from exc
            if challenge is None:
                return None, authority.generation
            if challenge.initialization == initialization:
                approved_asset = self._health_init_asset
                verifier = self._health_init_verifier
                policy = admission_policy
                if (
                    type(approved_asset) is not HealthInitAsset
                    or type(verifier) is not HealthInitAttestor
                    or type(policy) is not AdmissionPolicy
                    or not challenge.issued_under(policy)
                    or not challenge.disclosure.matches(
                        initialization,
                        approved_asset,
                    )
                    or not verifier.verify(
                        challenge.disclosure.skill_proof,
                        initialization,
                    )
                ):
                    raise AuthorityValidationError(
                        "initialization-configuration-mismatch"
                    )
                return challenge.disclosure, authority.generation
            raise AuthorityValidationError("health-init workflow conflict")

    def admission_policy_matches(self, policy: object) -> bool:
        """Compare the Plugin's immutable entrypoint contract without data access."""

        with self._lifecycle_lock:
            configured = self._admission_policy
            if configured is None or policy is None:
                return configured is None and policy is None
            return (
                type(configured) is AdmissionPolicy
                and type(policy) is AdmissionPolicy
                and configured == policy
            )

    def initialization_prepare_replay(
        self,
        initialization: OwnerInitialization,
    ) -> tuple[SkillUseProof, int] | None:
        """Return the exact durable prepare proof without rerunning health-init."""

        if type(initialization) is not OwnerInitialization:
            raise AuthorityValidationError("invalid owner initialization")
        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError("initialization-state-unavailable")
            try:
                self._store.verify_key()
                stored = self._store.initialization()
            except (KeyUnavailable, StoreUnavailable) as exc:
                raise AuthorityValidationError(
                    "initialization-state-unavailable"
                ) from exc
            if stored is None:
                return None
            draft = stored.draft
            if draft.owner == initialization:
                return draft.skill_proof, draft.prepared_authority.generation
            if draft.owner.workflow_id == initialization.workflow_id:
                raise AuthorityValidationError("health-init workflow conflict")
            raise AuthorityValidationError("initialization already exists")

    def native_cursor_directive(self, causal_id: str) -> NativeCursorDirective | None:
        """Release one exact native cursor only after its business transition finalizes."""

        with self._lifecycle_lock:
            if self._closed or not self.health_writes_allowed():
                return None
            try:
                receipt = self._store.source_receipt(causal_id)
                transition_id = self._business_transition_id_for_source(causal_id)
                authority = self._store.finalized_authority()
                if (
                    transition_id is None
                    or authority is None
                    or receipt is None
                    or receipt.managed_cursor_state != "committed"
                    or receipt.native_cursor_state not in {"ready", "executing"}
                ):
                    return None
                directive = NativeCursorDirective(
                    source_causal_id=causal_id,
                    native_cursor=receipt.envelope.native_cursor,
                    business_transition_id=transition_id,
                    authority_generation=authority.generation,
                )
                if receipt.native_cursor_state == "ready":
                    self._store.mark_native_cursor_state(causal_id, "executing")
                return directive
            except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
                return None

    def native_cursor_directive_matches(self, directive: object) -> bool:
        """Validate a previously issued directive, including terminal result replay."""

        if type(directive) is not NativeCursorDirective:
            return False
        with self._lifecycle_lock:
            try:
                receipt = self._store.source_receipt(directive.source_causal_id)
                authority = self._store.finalized_authority()
                return (
                    receipt is not None
                    and authority is not None
                    and receipt.envelope.native_cursor == directive.native_cursor
                    and self._business_transition_id_for_source(
                        directive.source_causal_id
                    ) == directive.business_transition_id
                    and authority.generation == directive.authority_generation
                )
            except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
                return False

    def _business_transition_id_for_source(self, causal_id: str) -> str | None:
        receipt = self._store.source_receipt(causal_id)
        if (
            receipt is not None
            and receipt.business_source_causal_id is not None
        ):
            return self._business_transition_id_for_source(
                receipt.business_source_causal_id
            )
        initialization = self._store.initialization()
        if (
            initialization is not None
            and initialization.phase == "enabled"
            and causal_id in initialization.draft.source_causal_ids
        ):
            return initialization.draft.transition_id
        daily = self._store.daily_turn(causal_id)
        if daily is not None and daily.phase == "finalized":
            if daily.terminal is None:
                raise KeyUnavailable("daily terminal receipt missing")
            return daily.terminal.transition_id
        return None

    def probe(self) -> ProbeReport:
        with self._lifecycle_lock:
            if self._closed:
                return ProbeReport(ProbeState.UNAVAILABLE, "current-writer-holder-missing")
            return self._probe_open()

    def _probe_open(self) -> ProbeReport:
        # A probe must never observe this SQLite connection between a business
        # write and its replay receipt.  Share the same writer lane as handle()
        # so health/model/outbound gates see only committed domain snapshots.
        with self._store.serialized():
            try:
                self._store.verify_key()
                interrupted = self._store.current_head_observation_guard()
                if interrupted is not None and interrupted.binding is not None:
                    # A bound guard can be closed only by its original causal
                    # command.  It is never healthy, but reporting UNKNOWN
                    # preserves the distinction from an unbound terminal/read
                    # tripwire while model and outbound gates remain closed.
                    reason = (
                        "effect-result-unknown"
                        if interrupted.binding.action == "effect.result"
                        else "current-head-recovery-required"
                    )
                    return ProbeReport(ProbeState.UNKNOWN, reason)
                if self._terminal_closed():
                    return ProbeReport(ProbeState.UNAVAILABLE, self._closed_reason)
                writer_entry = self._writer_entry_preflight()
                if writer_entry is not None:
                    reason = writer_entry.reason_code or "current-writer-holder-missing"
                    state = (
                        ProbeState.UNKNOWN
                        if reason == "local-finalized-authority-missing"
                        else ProbeState.UNAVAILABLE
                    )
                    return ProbeReport(state, reason)
                self._enter_current_head_guard()
                try:
                    head = self._read_head()
                    report = self._probe_for_head(head)
                    if report.state is ProbeState.HEALTHY and self._current_writer_proof(head) is None:
                        return ProbeReport(ProbeState.UNAVAILABLE, "current-writer-holder-missing")
                    return report
                finally:
                    self._exit_current_head_guard()
            except KeyUnavailable:
                self._closed_reason = "health-key-unavailable"
                return ProbeReport(ProbeState.UNAVAILABLE, self._closed_reason)
            except StoreUnavailable:
                self._closed_reason = "health-state-unavailable"
                return ProbeReport(ProbeState.UNAVAILABLE, self._closed_reason)
            except HeadUnknown:
                return ProbeReport(ProbeState.UNKNOWN, "current-head-unknown")
            except (HeadConflict, HeadTimeout):
                return ProbeReport(ProbeState.UNKNOWN, "current-head-unavailable")
            except HeadTerminal:
                self._latch_terminal()
                return ProbeReport(ProbeState.UNAVAILABLE, self._closed_reason)
            except CurrentHeadError:
                return ProbeReport(ProbeState.UNAVAILABLE, "current-head-unavailable")

    def _probe_for_head(self, head: AuthoritySnapshot) -> ProbeReport:
        try:
            # Take one SQLite snapshot: plaintext row labels are indexes, not
            # proof, so validate every encrypted payload before a healthy
            # response can escape this method.
            with self._store.transaction():
                self._store.verify_key()
                if self._terminal_closed():
                    return ProbeReport(ProbeState.UNAVAILABLE, self._closed_reason)
                authority = self._store.finalized_authority()
                if head.terminal:
                    self._latch_terminal()
                    return ProbeReport(ProbeState.UNAVAILABLE, self._closed_reason)
                if authority is None:
                    return ProbeReport(ProbeState.UNKNOWN, "local-finalized-authority-missing")
                mismatch_reason = authority.mismatch_reason(head)
                if mismatch_reason is not None:
                    return ProbeReport(ProbeState.UNKNOWN, mismatch_reason)
                if not self._store.verify_integrity(authority):
                    return ProbeReport(ProbeState.UNKNOWN, "local-finalized-record-missing")
                if self._store.has_pending_commands():
                    return ProbeReport(ProbeState.UNKNOWN, "local-pending-command")
                unresolved = self._store.unresolved_states()
                if "unknown" in unresolved:
                    return ProbeReport(ProbeState.UNKNOWN, "local-transition-unknown")
                if any(state in {"prepared", "committed"} for state in unresolved):
                    return ProbeReport(ProbeState.UNKNOWN, "local-transition-unresolved")
                if self._store.unresolved_effects():
                    return ProbeReport(ProbeState.UNKNOWN, "effect-result-unknown")
        except KeyUnavailable:
            self._closed_reason = "health-key-unavailable"
            return ProbeReport(ProbeState.UNAVAILABLE, self._closed_reason)
        except StoreUnavailable:
            self._closed_reason = "health-state-unavailable"
            return ProbeReport(ProbeState.UNAVAILABLE, self._closed_reason)
        if self._closed_reason in _PERSISTENT_CLOSE_REASONS:
            state = ProbeState.UNKNOWN if self._closed_reason == "effect-result-unknown" else ProbeState.UNAVAILABLE
            return ProbeReport(state, self._closed_reason)
        # A successful full proof clears only non-persistent/transient errors.
        self._closed_reason = None
        return ProbeReport(
            ProbeState.HEALTHY,
            "contract-ok",
            checks=(
                "key-boundary",
                "current-head",
                "local-finalized-authority",
                "local-finalized-record",
                "single-writer",
            ),
        )

    def health_writes_allowed(self) -> bool:
        if self.probe().state is not ProbeState.HEALTHY:
            return False
        if self._admission_policy is None:
            # Ticket 110 compatibility: deployments without the Ticket 111
            # admission surface retain the lower-level trusted-boundary gate.
            return True
        try:
            initialization = self._store.initialization()
            if initialization is None or initialization.phase != "enabled":
                return False
            draft = initialization.draft
            return (
                draft.key_id == self._store.key_id
                and self._initialization_configuration_matches(draft)
            )
        except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
            return False

    def _initialization_configuration_matches(
        self,
        draft: InitializationDraft,
    ) -> bool:
        """Revalidate every live authority input bound by initialization."""

        policy = self._admission_policy
        asset = self._health_init_asset
        verifier = self._health_init_verifier
        if (
            type(draft) is not InitializationDraft
            or type(policy) is not AdmissionPolicy
            or type(asset) is not HealthInitAsset
            or type(verifier) is not HealthInitAttestor
            or draft.key_id != self._store.key_id
        ):
            return False
        source = self._store.source_envelope(draft.source_causal_id)
        fact = draft.skill_proof.skill_use
        return (
            source is not None
            and policy.accepts(source)
            and fact.canonical_name == asset.canonical_name
            and fact.version == asset.version
            and fact.asset_digest == asset.asset_digest
            and fact.disclosure_version == asset.disclosure_version
            and verifier.verify(draft.skill_proof, draft.owner)
            and draft.owner_consent_evidence.matches(draft.owner, asset)
        )

    def _business_transition_kind(self, record_id: str) -> str | None:
        """Authorize only an exact initialization or attested daily record."""

        record_kind = self._business_transition_record_kind(record_id)
        initialization = self._store.initialization()
        if (
            record_kind == "initialization"
            and initialization is not None
            and self._initialization_configuration_matches(initialization.draft)
        ):
            return "initialization"
        daily = (
            self._store.daily_turn_for_record(record_id)
            if record_kind == "daily"
            else None
        )
        verifier = self._daily_skill_verifier
        bundle = self._daily_skill_bundle
        if (
            daily is None
            or type(verifier) is not DailySkillAttestor
            or type(bundle) is not DailySkillBundle
        ):
            return None
        if daily.phase == "finalized":
            return "daily" if daily.terminal is not None else None
        if daily.draft is None:
            return None
        source = self._store.source_envelope(daily.draft.source_causal_id)
        if source is None:
            return None
        return (
            "daily" if self._daily_draft_is_authorized(
                daily.draft,
                source,
                bundle,
                verifier,
            ) else None
        )

    def _daily_draft_is_authorized(
        self,
        draft: DailyTurnDraft,
        source: SourceEnvelope,
        bundle: DailySkillBundle,
        verifier: DailySkillAttestor,
    ) -> bool:
        """Verify one stage against public state or its exact provisional view."""

        state = self._store.daily_state()
        if draft.turn_kind == "evidence-stage":
            return draft.verify(source, state, bundle, verifier)
        evidence_stage = draft.evidence_stage
        if type(evidence_stage) is not DailyTurnDraft:
            return False
        try:
            post_stage_state = state.apply_evidence_stage(evidence_stage)
        except AuthorityValidationError:
            return False
        return draft.verify(
            source,
            post_stage_state,
            bundle,
            verifier,
            committed_evidence_stage=evidence_stage,
        )

    def _business_transition_record_kind(self, record_id: str) -> str | None:
        """Identify the purpose-specific owner without accepting config drift."""

        initialization = self._store.initialization()
        if (
            initialization is not None
            and initialization.draft.record_id == record_id
        ):
            return "initialization"
        return (
            "daily"
            if self._store.daily_turn_for_record(record_id) is not None
            else None
        )

    def model_effects_allowed(self) -> bool:
        return self._execution_capability_vault is not None and self.health_writes_allowed()

    def outbound_effects_allowed(self) -> bool:
        if self._admission_policy is not None:
            # Ticket 111 records only the configured support-contact boundary
            # and the owner's initialization approval.  It deliberately does
            # not create a delivery outbox, per-effect approval, or receipt,
            # so no owner/contact send may be advertised as executable yet.
            return False
        return self._execution_capability_vault is not None and self.health_writes_allowed()

    def _guard_current_head_call(
        self,
        operation: Callable[[], _CurrentHeadValue],
    ) -> _CurrentHeadValue:
        """Persist a tripwire before an operation that may observe terminal.

        If terminal is observed but persisting its permanent latch fails, the
        already-committed guard survives a process restart and keeps the state
        domain fail-closed instead of accepting a recreated old head.
        """

        if self._current_head_guard_depth > 0:
            try:
                return operation()
            except HeadTerminal:
                self._terminal_seen = True
                raise
        self._store.arm_current_head_observation()
        try:
            value = operation()
        except HeadTerminal:
            # Keep the guard until _latch_terminal() durably closes it.
            raise
        except BaseException:
            self._store.clear_current_head_observation()
            raise
        self._store.clear_current_head_observation()
        return value

    def _guard_mutable_current_head_call(
        self,
        binding: CurrentHeadRecoveryBinding,
        operation: Callable[[], _CurrentHeadValue],
    ) -> _CurrentHeadValue:
        """Run one mutable remote call under an exact response-loss binding.

        The caller normally already owns a generic guard.  The binding swap is
        a separate committed SQLite transaction because this method is never
        called from the business-write/receipt transaction.  On a successful
        response it immediately returns to generic protection before any
        follow-up observation.  Ambiguous transport failures retain the exact
        binding; terminal observations durably retarget to generic or latch
        terminal before their error can escape.
        """

        entered_here = False
        if self._current_head_guard_depth == 0:
            self._enter_current_head_guard()
            entered_here = True
        try:
            self._retarget_current_head_guard(binding)
            try:
                value = operation()
            except HeadTerminal:
                # A terminal observation must never leave a replayable CAS or
                # release binding behind if latching crashes immediately after.
                self._terminal_seen = True
                self._current_head_guard_preserved = True
                try:
                    # Prefer a generic handoff.  If its SQLite write fails,
                    # persist the independent terminal latch before exposing
                    # that failure; a later restart then checks the latch
                    # before any old exact binding.
                    self._retarget_current_head_guard(None)
                except BaseException:
                    try:
                        self._latch_terminal()
                    except BaseException:
                        # If both durable writes fail the exact binding cannot
                        # be safely transformed by this store.  Keep the live
                        # latch and rethrow; a host-durable tombstone is needed
                        # for stronger guarantees beyond this skeleton.
                        pass
                    raise
                # Generic guard is already durable, so a latch failure still
                # leaves restart fail-closed rather than replayable.
                self._latch_terminal()
                raise
            except HeadConflict:
                # A conflict proves this specific mutation did not apply.
                self._retarget_current_head_guard(None)
                raise
            except (HeadUnknown, HeadTimeout):
                # Only declared transport ambiguity permits one bound
                # read-only recovery attempt.
                self._current_head_guard_preserved = True
                raise
            except MalformedCurrentHeadResponse:
                # A malformed response arrived after the mutable adapter call
                # returned.  The operation may have completed remotely, so
                # retain B for this exact causal command's lookup-only
                # recovery.  A missing receipt closes B into generic
                # protection; recovery never retries the mutation.
                self._current_head_guard_preserved = True
                raise
            except CurrentHeadError:
                # An unclassified adapter error has no typed response phase.
                # It is not a retry or recovery contract, so consume B into
                # generic protection before exposing the error.
                self._current_head_guard_preserved = True
                self._retarget_current_head_guard(None)
                raise
            except BaseException:
                self._current_head_guard_preserved = True
                raise
            try:
                self._retarget_current_head_guard(None)
            except BaseException:
                # CAS/release may have succeeded; never let finally erase the
                # prior binding merely because the phase handoff failed.
                self._current_head_guard_preserved = True
                raise
            return value
        finally:
            if entered_here:
                self._exit_current_head_guard()

    @staticmethod
    def _canonical_authority_from_port(value: object) -> AuthoritySnapshot:
        """Rebuild a port authority from exact built-in primitive fields."""

        if type(value) is not HeadSnapshot:
            raise MalformedCurrentHeadResponse("invalid current-head authority")
        try:
            return AuthoritySnapshot(
                installation_id=value.installation_id,
                generation=value.generation,
                revision_digest=value.revision_digest,
                transition_id=value.transition_id,
                writer_fence=value.writer_fence,
                terminal=value.terminal,
                site=value.site,
            )
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head authority") from exc

    @staticmethod
    def _canonical_head_snapshot_from_port(value: object) -> HeadSnapshot:
        """Rebuild a port snapshot without trusting subclass methods/equality."""

        if type(value) is not HeadSnapshot:
            raise MalformedCurrentHeadResponse("invalid current-head snapshot")
        try:
            return HeadSnapshot(
                installation_id=value.installation_id,
                generation=value.generation,
                revision_digest=value.revision_digest,
                transition_id=value.transition_id,
                writer_fence=value.writer_fence,
                terminal=value.terminal,
                site=value.site,
            )
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head snapshot") from exc

    @staticmethod
    def _canonical_authority_value_from_port(value: object) -> AuthoritySnapshot:
        """Rebuild a nested non-head authority returned in a receipt."""

        if type(value) is not AuthoritySnapshot:
            raise MalformedCurrentHeadResponse("invalid receipt authority")
        try:
            return AuthoritySnapshot(
                installation_id=value.installation_id,
                generation=value.generation,
                revision_digest=value.revision_digest,
                transition_id=value.transition_id,
                writer_fence=value.writer_fence,
                terminal=value.terminal,
                site=value.site,
            )
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid receipt authority") from exc

    @classmethod
    def _canonical_advance_identity_from_port(cls, value: object) -> AdvanceIdentity:
        if type(value) is not AdvanceIdentity:
            raise MalformedCurrentHeadResponse("invalid current-head transition identity")
        try:
            return AdvanceIdentity(
                expected=cls._canonical_authority_value_from_port(value.expected),
                transition_id=value.transition_id,
                revision_digest=value.revision_digest,
                writer_fence=value.writer_fence,
                operation_digest=value.operation_digest,
            )
        except MalformedCurrentHeadResponse:
            raise
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head transition identity") from exc

    @classmethod
    def _canonical_transition_receipt_from_port(cls, value: object) -> AppliedTransition:
        if type(value) is not AppliedTransition:
            raise MalformedCurrentHeadResponse("invalid current-head transition receipt")
        try:
            return AppliedTransition(
                request=cls._canonical_advance_identity_from_port(value.request),
                applied=cls._canonical_head_snapshot_from_port(value.applied),
            )
        except MalformedCurrentHeadResponse:
            raise
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head transition receipt") from exc

    @classmethod
    def _canonical_writer_proof_for_port(cls, value: object) -> WriterFenceProof:
        """Copy a host proof before an untrusted port can mutate its fields."""

        if type(value) is not WriterFenceProof:
            raise MalformedCurrentHeadResponse("invalid current-head writer proof")
        try:
            return WriterFenceProof(
                authority=cls._canonical_authority_value_from_port(value.authority),
                capability=value.capability,
            )
        except MalformedCurrentHeadResponse:
            raise
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head writer proof") from exc

    @classmethod
    def _canonical_advance_request_for_port(cls, value: object) -> AdvanceRequest:
        """Create an adapter-owned copy and retain no mutable caller fields."""

        if type(value) is not AdvanceRequest:
            raise MalformedCurrentHeadResponse("invalid current-head advance request")
        try:
            expected = cls._canonical_authority_value_from_port(value.expected)
            proof = cls._canonical_writer_proof_for_port(value.writer_proof)
            return AdvanceRequest(
                expected=expected,
                transition_id=value.transition_id,
                revision_digest=value.revision_digest,
                writer_fence=value.writer_fence,
                operation_digest=value.operation_digest,
                writer_proof=proof,
            )
        except MalformedCurrentHeadResponse:
            raise
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head advance request") from exc

    @classmethod
    def _canonical_execution_lease_identity_for_port(
        cls,
        value: object,
    ) -> ExecutionLeaseIdentity:
        if type(value) is not ExecutionLeaseIdentity:
            raise MalformedCurrentHeadResponse("invalid current-head execution lease identity")
        try:
            return ExecutionLeaseIdentity(
                expected=cls._canonical_authority_value_from_port(value.expected),
                effect_id=value.effect_id,
                intent_digest=value.intent_digest,
                writer_fence=value.writer_fence,
                holder_id=value.holder_id,
            )
        except MalformedCurrentHeadResponse:
            raise
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head execution lease identity") from exc

    @classmethod
    def _canonical_execution_lease_for_port(cls, value: object) -> ExecutionLease:
        if type(value) is not ExecutionLease:
            raise MalformedCurrentHeadResponse("invalid current-head execution lease")
        try:
            return ExecutionLease(
                lease_id=value.lease_id,
                effect_id=value.effect_id,
                intent_digest=value.intent_digest,
                authority=cls._canonical_authority_value_from_port(value.authority),
                holder_id=value.holder_id,
            )
        except MalformedCurrentHeadResponse:
            raise
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head execution lease") from exc

    @classmethod
    def _canonical_execution_lease_request_for_port(cls, value: object) -> ExecutionLeaseRequest:
        if type(value) is not ExecutionLeaseRequest:
            raise MalformedCurrentHeadResponse("invalid current-head execution lease request")
        try:
            return ExecutionLeaseRequest(
                expected=cls._canonical_authority_value_from_port(value.expected),
                effect_id=value.effect_id,
                intent_digest=value.intent_digest,
                writer_fence=value.writer_fence,
                holder_id=value.holder_id,
                writer_proof=cls._canonical_writer_proof_for_port(value.writer_proof),
            )
        except MalformedCurrentHeadResponse:
            raise
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head execution lease request") from exc

    @classmethod
    def _canonical_execution_lease_release_for_port(cls, value: object) -> ExecutionLeaseRelease:
        if type(value) is not ExecutionLeaseRelease:
            raise MalformedCurrentHeadResponse("invalid current-head execution lease release")
        try:
            return ExecutionLeaseRelease(
                lease=cls._canonical_execution_lease_for_port(value.lease),
                writer_proof=cls._canonical_writer_proof_for_port(value.writer_proof),
                operation_digest=value.operation_digest,
            )
        except MalformedCurrentHeadResponse:
            raise
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head execution lease release") from exc

    def _read_head(self) -> AuthoritySnapshot:
        def read_authority() -> AuthoritySnapshot:
            try:
                read = self._current_head.read()
            except CurrentHeadError:
                raise
            except AuthorityValidationError as exc:
                raise MalformedCurrentHeadResponse("invalid current-head read") from exc
            except Exception as exc:
                raise CurrentHeadError("current-head read unavailable") from exc
            if type(read) is not HeadRead:
                raise MalformedCurrentHeadResponse("invalid current-head read")
            authority = self._canonical_authority_from_port(read.head)
            if authority.terminal:
                raise HeadTerminal("terminal current head")
            return authority

        return self._guard_current_head_call(read_authority)

    def _advance_head(
        self,
        request: AdvanceRequest,
        *,
        recovery_binding: CurrentHeadRecoveryBinding | None = None,
    ) -> AuthoritySnapshot:
        if recovery_binding is None:
            raise StoreUnavailable("state CAS requires a durable recovery binding")
        # Keep a private desired identity.  The adapter receives a distinct
        # object and may not change the operation digest that later authorizes
        # local commit/replay closure by mutating its call argument.
        retained_request = self._canonical_advance_request_for_port(request)
        expected_identity = retained_request.identity()
        outbound = self._canonical_advance_request_for_port(request)

        def advance() -> AuthoritySnapshot:
            try:
                updated = self._current_head.conditional_advance(outbound)
            except CurrentHeadError:
                raise
            except AuthorityValidationError as exc:
                raise MalformedCurrentHeadResponse("invalid current-head advance") from exc
            except Exception as exc:
                raise CurrentHeadError("current-head advance unavailable") from exc
            try:
                applied = self._canonical_head_snapshot_from_port(updated)
                return AppliedTransition(request=expected_identity, applied=applied).applied.as_authority()
            except MalformedCurrentHeadResponse:
                raise
            except Exception as exc:
                raise MalformedCurrentHeadResponse("invalid current-head advance") from exc

        entered_here = False
        if self._current_head_guard_depth == 0:
            self._enter_current_head_guard()
            entered_here = True
        try:
            applied = self._guard_mutable_current_head_call(recovery_binding, advance)
            # A successful CAS response carries no durable ownership of the
            # command digest.  Read the receipt back under the pre-call
            # identity so a port-side mutation cannot turn A's remote CAS into
            # B's local receipt.
            try:
                receipt = self._lookup_transition(expected_identity)
            except (HeadUnknown, HeadTimeout):
                self._preserve_exact_local_closure_binding(recovery_binding)
                raise
            except (TransitionNotFound, HeadConflict, MalformedCurrentHeadResponse, CurrentHeadError):
                self._current_head_guard_preserved = True
                raise
            if receipt.request != expected_identity:
                self._current_head_guard_preserved = True
                raise MalformedCurrentHeadResponse("current-head advance receipt identity mismatch")
            confirmed = receipt.applied.as_authority()
            if applied.mismatch_reason(confirmed) is not None:
                self._current_head_guard_preserved = True
                raise MalformedCurrentHeadResponse("current-head advance receipt mismatch")
            return confirmed
        finally:
            if entered_here:
                self._exit_current_head_guard()

    def _confirm_advanced_head(self, advanced: AuthoritySnapshot) -> AuthoritySnapshot:
        """Require a post-CAS read to prove every returned authority field."""

        confirmed = self._read_head()
        if confirmed.terminal:
            raise HeadTerminal("terminal current head")
        if advanced.mismatch_reason(confirmed) is not None:
            raise CurrentHeadError("current-head advance confirmation mismatch")
        return confirmed

    def _lookup_transition(self, request: AdvanceIdentity) -> AppliedTransition:
        expected = self._canonical_advance_identity_from_port(request)
        outbound = self._canonical_advance_identity_from_port(request)

        def lookup() -> AppliedTransition:
            try:
                receipt = self._current_head.lookup_transition(outbound)
            except CurrentHeadError:
                raise
            except AuthorityValidationError as exc:
                raise MalformedCurrentHeadResponse("invalid current-head transition receipt") from exc
            except Exception as exc:
                raise CurrentHeadError("current-head lookup unavailable") from exc
            canonical = self._canonical_transition_receipt_from_port(receipt)
            if canonical.request != expected:
                raise CurrentHeadError("current-head transition lookup request mismatch")
            return canonical

        return self._guard_current_head_call(lookup)

    def _acquire_execution_lease(self, request: ExecutionLeaseRequest) -> ExecutionLeaseReceipt:
        retained_request = self._canonical_execution_lease_request_for_port(request)
        expected = retained_request.identity()
        outbound = self._canonical_execution_lease_request_for_port(request)

        def acquire() -> ExecutionLeaseReceipt:
            try:
                receipt = self._current_head.acquire_execution_lease(outbound)
            except CurrentHeadError:
                raise
            except Exception as exc:
                raise CurrentHeadError("current-head execution lease unavailable") from exc
            return self._validate_execution_lease_receipt(expected, receipt)

        return self._guard_current_head_call(acquire)

    def _lookup_execution_lease(self, identity: ExecutionLeaseIdentity) -> ExecutionLeaseReceipt:
        expected = self._canonical_execution_lease_identity_for_port(identity)
        outbound = self._canonical_execution_lease_identity_for_port(identity)

        def lookup() -> ExecutionLeaseReceipt:
            try:
                receipt = self._current_head.lookup_execution_lease(outbound)
            except CurrentHeadError:
                raise
            except Exception as exc:
                raise CurrentHeadError("current-head execution lease lookup unavailable") from exc
            return self._validate_execution_lease_receipt(expected, receipt)

        return self._guard_current_head_call(lookup)

    def _release_execution_lease(
        self,
        lease: ExecutionLease,
        *,
        writer_proof: WriterFenceProof | None = None,
        recovery_binding: CurrentHeadRecoveryBinding | None = None,
    ) -> ExecutionLeaseReceipt:
        if recovery_binding is None:
            raise StoreUnavailable("execution lease release requires a durable recovery binding")
        if writer_proof is None:
            raise CurrentHeadError("execution lease release lacks writer proof")
        release = ExecutionLeaseRelease(
            lease=lease,
            writer_proof=writer_proof,
            operation_digest=recovery_binding.command_digest,
        )
        retained_release = self._canonical_execution_lease_release_for_port(release)
        outbound = self._canonical_execution_lease_release_for_port(release)
        identity = ExecutionLeaseIdentity(
            expected=retained_release.lease.authority,
            effect_id=retained_release.lease.effect_id,
            intent_digest=retained_release.lease.intent_digest,
            writer_fence=retained_release.lease.authority.writer_fence,
            holder_id=retained_release.lease.holder_id,
        )

        def release() -> ExecutionLeaseReceipt:
            try:
                receipt = self._current_head.release_execution_lease(outbound)
            except CurrentHeadError:
                raise
            except Exception as exc:
                raise CurrentHeadError("current-head execution lease release unavailable") from exc
            return self._validate_execution_lease_receipt(identity, receipt)

        return self._guard_mutable_current_head_call(recovery_binding, release)

    @staticmethod
    def _validate_execution_lease_receipt(
        identity: ExecutionLeaseIdentity,
        receipt: object,
    ) -> ExecutionLeaseReceipt:
        if type(identity) is not ExecutionLeaseIdentity or type(receipt) is not ExecutionLeaseReceipt:
            raise MalformedCurrentHeadResponse("invalid current-head execution lease receipt")
        try:
            if type(receipt.request) is not ExecutionLeaseIdentity:
                raise MalformedCurrentHeadResponse("invalid current-head execution lease receipt")
            request = ExecutionLeaseIdentity(
                expected=HealthCore._canonical_authority_value_from_port(receipt.request.expected),
                effect_id=receipt.request.effect_id,
                intent_digest=receipt.request.intent_digest,
                writer_fence=receipt.request.writer_fence,
                holder_id=receipt.request.holder_id,
            )
            if request != identity:
                raise CurrentHeadError("execution lease request mismatch")
            # Reconstructing every returned typed value forces all exact
            # authority, effect ID, digest, and writer-fence invariants at the
            # adapter boundary even if an untrusted port mutates a frozen
            # dataclass object after construction.
            if type(receipt.lease) is not ExecutionLease:
                raise MalformedCurrentHeadResponse("invalid current-head execution lease receipt")
            lease = ExecutionLease(
                lease_id=receipt.lease.lease_id,
                effect_id=receipt.lease.effect_id,
                intent_digest=receipt.lease.intent_digest,
                authority=HealthCore._canonical_authority_value_from_port(receipt.lease.authority),
                holder_id=receipt.lease.holder_id,
            )
            return ExecutionLeaseReceipt(
                request=request,
                lease=lease,
                released=receipt.released,
                released_operation_digest=receipt.released_operation_digest,
            )
        except MalformedCurrentHeadResponse:
            raise
        except CurrentHeadError:
            raise
        except Exception as exc:
            raise MalformedCurrentHeadResponse("invalid current-head execution lease receipt") from exc

    @staticmethod
    def _prepared_mismatch_reason(
        prepared: AuthoritySnapshot,
        head: AuthoritySnapshot,
        writer_fence: str,
    ) -> str | None:
        if prepared.installation_id != head.installation_id:
            return "prepared-installation-mismatch"
        if prepared.site != head.site:
            return "prepared-site-mismatch"
        if writer_fence != prepared.writer_fence or prepared.writer_fence != head.writer_fence:
            return "stale-writer-fence"
        if (
            prepared.generation != head.generation
            or prepared.revision_digest != head.revision_digest
            or prepared.transition_id != head.transition_id
            or prepared.terminal != head.terminal
        ):
            return "stale-writer-fence"
        return None

    @staticmethod
    def _target_matches_authority(prepared: PreparedTransition, authority: AuthoritySnapshot) -> bool:
        return (
            authority.installation_id == prepared.base.installation_id
            and authority.site == prepared.base.site
            and authority.generation == prepared.base.generation + 1
            and authority.revision_digest == prepared.target.revision_digest
            and authority.transition_id == prepared.target.transition_id
            and authority.writer_fence == prepared.base.writer_fence
            and not authority.terminal
        )

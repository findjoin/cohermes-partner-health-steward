"""Single-writer health-core state machine for Ticket 110."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator, Protocol, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .admission import (
    MAX_MESSAGE_BODY_BYTES,
    AdmissionPolicy,
    NativeCursorDirective,
    SourceEnvelope,
    SourceReceipt,
)
from .answer_resolution import (
    ModelAnswerResolution,
    ModelEffectReport,
    render_failed_closed,
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
    validate_controlled_effect_kind,
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
    OwnerPreparePayload,
    ProbeMeta,
    ProtocolViolation,
    Response,
    StateCandidatePayload,
    StateCommitPayload,
    canonicalize_command,
)
from .coordination import (
    DAILY_HEALTH_SKILL_NAMES,
    RECORDING_EXCLUDED_CORRECTION_PORTRAIT_REASON,
    AtomicEvidenceClaim,
    DailyHealthState,
    DailySkillAttestor,
    DailySkillBundle,
    DailyTurnDraft,
    DailyTurnResult,
    OwnerCorrectionRevision,
    OwnerReplyAtom,
    PortraitDecision,
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
from .health_commands import (
    HealthCommandReceipt,
    TrustedHealthCommand,
)
from .knowledge import KnowledgeRelease
from .model_contract import (
    ModelTransportResult,
    StrictHealthLLM,
    StrictModelAdapter,
    StrictModelOutcome,
    StrictModelRequest,
)
from .nondiagnostic import (
    ApprovedClaimAtom,
    ApprovedReplyTemplate,
    NonDiagnosticCandidate,
    NonDiagnosticContractViolation,
    NonDiagnosticReplyPipeline,
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
from .delivery import (
    DeliveryContractViolation,
    DeliveryOutboxState,
    DeliveryTransition,
    OutboxIntent,
    OutboxRecord,
    OwnerDeliveryCompletion,
    OwnerDeliveryEngine,
    OwnerDeliverySendIntent,
    OwnerDeliveryTransportResult,
    OwnerWeixinDestination,
)
from .ticket115_contracts import (
    DeliveryEvidence,
    DeliveryEvidenceAuthority,
    DeliveryEvidenceIssuer,
)
from .probe import ProbeReport, ProbeState
from .owner_authority import (
    OwnerAuthorityContractViolation,
    OwnerMutationRequest,
    OwnerPreparedMutation,
)
from .rights import (
    ManagedExport,
    ManagedObject,
    ManagedObjectReference,
    ManagedRightsProjection,
    ManagedRightsService,
    PendingCorrectionDraft,
    RightsContractViolation,
)
from .settings import (
    ExecutionScopeApproval,
    ExecutionScopeConsumptionRequest,
    ORDINARY_NOTIFICATION_KINDS,
    OwnerSettingsEngine,
    OwnerSettingsState,
    RouteConfigurationUpdate,
    SettingsContractViolation,
    SupportContactSettings,
)
from .status import (
    BusinessStatusResult,
    CapabilityFactAuthority,
    CapabilityRequirement,
    CORE_STATUS_DOMAINS,
    PRODUCTION_STATUS_PRODUCER_CONTRACTS,
    PRODUCTION_STATUS_PRODUCER_CONTRACT_VERSIONS,
    PRODUCTION_STATUS_PRODUCER_IDS,
    StatusContractViolation,
    StatusProjector,
)
from .storage import (
    CausalIdConflict,
    CurrentHeadRecoveryBinding,
    DailyTurnTerminalReceipt,
    EncryptedStateStore,
    KeyUnavailable,
    OwnerPreparedCorrectionRecovery,
    StoreUnavailable,
    Ticket115PreparedMutation,
)
from .review import (
    DailyReviewPending,
    DailyReviewDecision,
    DailyReviewEngine,
    DailyReviewLedger,
    DailyReviewRecord,
    LocalDayKey,
    ReviewContractViolation,
    local_day_key,
)
from .tasks import (
    ManagedTask,
    TaskAcceptance,
    TaskCandidate,
    TaskContractViolation,
    TaskEngine,
    TaskRuntimeState,
    TaskTransition,
)


_STATE_ACTIONS = frozenset({"state.candidate", "state.prepare", "state.commit", "state.finalize"})
_TRANSITION_RECOVERY_ACTIONS = frozenset({"state.commit", "state.finalize"})
_PROBE_BYPASS_ACTIONS = _TRANSITION_RECOVERY_ACTIONS | frozenset({"effect.result"})
_PERSISTENT_CLOSE_REASONS = frozenset(
    {"effect-result-unknown", "health-key-unavailable", "current-head-terminal"}
)
_MAX_HELD_INITIALIZATION_SOURCES = MAX_RESOLVED_SOURCE_CAUSAL_IDS + 1
_MAX_UNRESOLVED_INITIALIZATION_SOURCES = _MAX_HELD_INITIALIZATION_SOURCES + 1
_PRECALL_FAILED_CLOSED_REASONS = frozenset(
    {
        "route-id-drift",
        "provider-drift",
        "base-url-drift",
        "api-mode-drift",
        "requested-model-drift",
        "configuration-generation-drift",
        "owner-consent-drift",
        "capability-profile-drift",
        "output-reservation-drift",
        "strict-schema-drift",
        "capacity-unavailable",
        "model-effect-authorization-required",
    }
)

_TICKET115_HEALTH_COMMAND_AUTHORITY = {
    "task.admit": ("daily_skill_runtime", ("task:admit",)),
    "task.claim": ("health_tasks", ("task:claim",)),
    "task.release": ("health_tasks", ("task:release",)),
    "task.defer": ("health_tasks", ("task:defer",)),
    "task.adjust": ("health_tasks", ("task:adjust",)),
    "task.advance": ("health_tasks", ("task:advance",)),
    "task.solve": ("health_tasks", ("task:solve",)),
    "task.cancel": ("health_tasks", ("task:cancel",)),
    "task.fail": ("health_tasks", ("task:fail",)),
    "task.link-successor": ("health_tasks", ("task:link-successor",)),
    "review.prepare": ("health_tasks", ("review:prepare",)),
    "review.commit": ("health_tasks", ("review:commit",)),
    "delivery.observe": ("owner_delivery_adapter", ("delivery:observe",)),
    "delivery.observe-owner-action": (
        "owner_event_admission",
        ("delivery:actual-action",),
    ),
}

# A process-local marker only protects the short hand-off between authorization
# and completion.  Durable recovery must regain ownership once that hand-off
# has clearly stalled; it must never depend on an unbounded process set.
_OWNER_DELIVERY_ATTEMPT_MARKER_TTL_SECONDS = 300.0
_OWNER_DELIVERY_ATTEMPT_PREPARED = "prepared"
_OWNER_DELIVERY_ATTEMPT_AUTHORIZED = "authorized-in-flight"


class _TrustedHealthCommandReplay(Exception):
    """Return one exact durable result from inside the final write lane."""

    def __init__(self, result: dict[str, object]) -> None:
        super().__init__("trusted health command replay")
        self.result = result


def _ticket115_wire_fields(
    value: object,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolViolation("invalid Ticket 115 wire payload")
    keys = frozenset(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise ProtocolViolation("invalid Ticket 115 wire fields")
    return value


def _ticket115_task_transition_wire(
    transition: TaskTransition,
) -> dict[str, object]:
    return {
        "task_id": transition.task_id,
        "outcome": transition.outcome,
        "replayed": transition.replayed,
        "task": transition.state.task(transition.task_id).to_storage(),
    }


def _ticket115_review_decision_wire(
    decision: DailyReviewDecision,
) -> dict[str, object]:
    pending = decision.ledger.pending
    prepare_digest = (
        decision.record.prepare_digest
        if decision.record is not None
        else (
            pending.prepare_digest
            if pending is not None and pending.key == decision.key
            else None
        )
    )
    return {
        "key": decision.key.to_storage(),
        "outcome": decision.outcome,
        "record": None if decision.record is None else decision.record.to_storage(),
        "notification_required": decision.notification_required,
        "replayed": decision.replayed,
        "prepare_digest": prepare_digest,
    }


def _ticket115_delivery_transition_wire(
    transition: DeliveryTransition,
) -> dict[str, object]:
    return {
        "intent_id": transition.intent_id,
        "outcome": transition.outcome,
        "replayed": transition.replayed,
        "current_layer": transition.record.current_layer,
    }


def _ticket115_review_decision_from_wire(
    value: object,
    ledger: DailyReviewLedger,
) -> DailyReviewDecision:
    fields = _ticket115_wire_fields(
        value,
        frozenset(
            {
                "key",
                "outcome",
                "record",
                "notification_required",
                "replayed",
                "prepare_digest",
            }
        ),
    )
    key = LocalDayKey.from_storage(fields["key"])
    outcome = validate_opaque_text(fields["outcome"], "review decision outcome")
    record_wire = fields["record"]
    notification_required = fields["notification_required"]
    replayed = fields["replayed"]
    if type(notification_required) is not bool or type(replayed) is not bool:
        raise ProtocolViolation("invalid review decision flags")
    prepare_digest = fields["prepare_digest"]
    if prepare_digest is not None:
        prepare_digest = validate_opaque_text(
            prepare_digest,
            "review preparation digest",
        )
    if outcome == "already-completed":
        record = ledger.record_for(key)
        if (
            record is None
            or record_wire != record.to_storage()
            or prepare_digest != record.prepare_digest
            or notification_required
            or not replayed
        ):
            raise ProtocolViolation("invalid completed review decision")
    elif outcome == "old-local-day-suppressed":
        if (
            record_wire is not None
            or prepare_digest is not None
            or notification_required
            or not replayed
        ):
            raise ProtocolViolation("invalid suppressed review decision")
        record = None
    elif outcome in {
        "prepared",
        "stale-pending-replaced",
        "resume-current-day",
        "current-day-pending-refreshed",
    }:
        pending = ledger.pending
        if (
            pending is None
            or pending.key != key
            or prepare_digest != pending.prepare_digest
            or record_wire is not None
            or notification_required != pending.notification_required
            or replayed != (outcome == "resume-current-day")
        ):
            raise ProtocolViolation("invalid pending review decision")
        record = None
    else:
        raise ProtocolViolation("unsupported review decision outcome")
    return DailyReviewDecision(
        ledger=ledger,
        key=key,
        outcome=outcome,
        record=record,
        notification_required=notification_required,
        replayed=replayed,
    )


def _ticket115_owner_delivery_submission_from_wire(
    value: object,
) -> OwnerDeliverySubmission:
    fields = _ticket115_wire_fields(
        value,
        frozenset(
            {
                "effect_request_id",
                "source_task_id",
                "payload_ref",
                "payload_digest",
                "formed_at_utc",
                "submitted_at_utc",
            }
        ),
        frozenset({"notification_kind"}),
    )
    return OwnerDeliverySubmission(
        effect_request_id=fields["effect_request_id"],  # type: ignore[arg-type]
        source_task_id=fields["source_task_id"],  # type: ignore[arg-type]
        payload_ref=fields["payload_ref"],  # type: ignore[arg-type]
        payload_digest=fields["payload_digest"],  # type: ignore[arg-type]
        formed_at_utc=fields["formed_at_utc"],  # type: ignore[arg-type]
        submitted_at_utc=fields["submitted_at_utc"],  # type: ignore[arg-type]
        notification_kind=fields.get(
            "notification_kind",
            "review_summary",
        ),  # type: ignore[arg-type]
    )
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
class OwnerDeliverySubmission:
    """Non-authoritative payload references for one review-owned send intent."""

    effect_request_id: str
    source_task_id: str
    payload_ref: str
    payload_digest: str
    formed_at_utc: str
    submitted_at_utc: str
    notification_kind: str = "review_summary"

    def __post_init__(self) -> None:
        for value, name in (
            (self.effect_request_id, "owner delivery effect request"),
            (self.source_task_id, "owner delivery source task"),
            (self.payload_ref, "owner delivery payload reference"),
            (self.payload_digest, "owner delivery payload digest"),
            (self.formed_at_utc, "owner delivery formation time"),
            (self.submitted_at_utc, "owner delivery submission time"),
        ):
            validate_opaque_text(value, name)
        if self.notification_kind not in ORDINARY_NOTIFICATION_KINDS:
            raise AuthorityValidationError("invalid owner delivery notification kind")


@dataclass(frozen=True)
class OwnerDeliveryExecutionResult:
    """Adapter fact plus the two durable terminal projections it produced."""

    transport_result: OwnerDeliveryTransportResult
    effect_response: Response
    delivery_transition: DeliveryTransition

    def __post_init__(self) -> None:
        if type(self.transport_result) is not OwnerDeliveryTransportResult:
            raise AuthorityValidationError("invalid owner delivery transport result")
        if type(self.effect_response) is not Response:
            raise AuthorityValidationError("invalid owner delivery effect response")
        if type(self.delivery_transition) is not DeliveryTransition:
            raise AuthorityValidationError("invalid owner delivery transition")


@dataclass(frozen=True)
class OwnerMutationStatus:
    """Health-body-free recovery projection for one owner mutation."""

    command_id: str
    phase: str
    record_id: str
    revision_digest: str
    transition_id: str
    prepared_authority: AuthoritySnapshot
    owner_authority_binding_digest: str
    settings_version: int
    settings_result: dict[str, object] | None
    committed_authority: AuthoritySnapshot | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.command_id, "owner mutation command identifier"),
            (self.record_id, "owner mutation record identifier"),
            (self.revision_digest, "owner mutation revision digest"),
            (self.transition_id, "owner mutation transition identifier"),
            (
                self.owner_authority_binding_digest,
                "owner mutation authority binding",
            ),
        ):
            validate_opaque_text(value, name)
        if self.phase not in {"prepared", "unknown", "committed", "finalized"}:
            raise AuthorityValidationError("invalid owner mutation phase")
        if type(self.prepared_authority) is not AuthoritySnapshot:
            raise AuthorityValidationError("invalid owner mutation authority")
        if self.phase in {"committed", "finalized"}:
            if type(self.committed_authority) is not AuthoritySnapshot:
                raise AuthorityValidationError(
                    "invalid committed owner mutation authority"
                )
        elif self.committed_authority is not None:
            raise AuthorityValidationError(
                "unexpected committed owner mutation authority"
            )
        if type(self.settings_version) is not int or self.settings_version < 1:
            raise AuthorityValidationError("invalid owner settings version")
        if self.settings_result is not None:
            if type(self.settings_result) is not dict:
                raise AuthorityValidationError("invalid owner settings result")
            try:
                normalized = json.loads(
                    json.dumps(
                        self.settings_result,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise AuthorityValidationError(
                    "invalid owner settings result"
                ) from exc
            if type(normalized) is not dict:
                raise AuthorityValidationError("invalid owner settings result")
            object.__setattr__(self, "settings_result", normalized)


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
        owner_settings_clock: Callable[[], datetime] | None = None,
        route_configuration_provider: (
            Callable[[], RouteConfigurationUpdate] | None
        ) = None,
        status_fact_authority: CapabilityFactAuthority | None = None,
        delivery_evidence_authority: DeliveryEvidenceAuthority | None = None,
        delivery_evidence_issuers: tuple[DeliveryEvidenceIssuer, ...] = (),
        business_status_clock: Callable[[], datetime] | None = None,
        model_authority_digest: str | None = None,
        knowledge_releases: tuple[KnowledgeRelease, ...] = (),
        knowledge_valid_at: str | None = None,
        knowledge_clock: Callable[[], datetime] | None = None,
        approved_claims: tuple[ApprovedClaimAtom, ...] = (),
        approved_templates: tuple[ApprovedReplyTemplate, ...] = (),
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
        if owner_settings_clock is not None and not callable(owner_settings_clock):
            raise AuthorityValidationError("invalid owner settings clock")
        self._owner_settings_clock = (
            owner_settings_clock
            if owner_settings_clock is not None
            else lambda: datetime.now(timezone.utc)
        )
        if (
            route_configuration_provider is not None
            and not callable(route_configuration_provider)
        ):
            raise AuthorityValidationError("invalid route configuration provider")
        self._route_configuration_provider = route_configuration_provider
        if status_fact_authority is not None:
            if type(status_fact_authority) is not CapabilityFactAuthority:
                raise AuthorityValidationError("invalid status fact authority")
            if any(
                status_fact_authority.producer_contracts.get(producer_id)
                != contract_version
                for producer_id, contract_version
                in PRODUCTION_STATUS_PRODUCER_CONTRACTS.items()
            ):
                raise AuthorityValidationError(
                    "incomplete production status producer authority"
                )
        if business_status_clock is not None and not callable(
            business_status_clock
        ):
            raise AuthorityValidationError("invalid business status clock")
        self._status_fact_authority = status_fact_authority
        if delivery_evidence_authority is not None and (
            type(delivery_evidence_authority) is not DeliveryEvidenceAuthority
        ):
            raise AuthorityValidationError("invalid delivery evidence authority")
        if type(delivery_evidence_issuers) is not tuple or any(
            type(issuer) is not DeliveryEvidenceIssuer
            for issuer in delivery_evidence_issuers
        ):
            raise AuthorityValidationError("invalid delivery evidence issuers")
        issuers = {
            issuer.producer_contract: issuer
            for issuer in delivery_evidence_issuers
        }
        if len(issuers) != len(delivery_evidence_issuers):
            raise AuthorityValidationError("duplicate delivery evidence issuer")
        if issuers and delivery_evidence_authority is None:
            raise AuthorityValidationError("delivery evidence authority required")
        if delivery_evidence_authority is not None:
            for issuer in issuers.values():
                for layer in issuer.allowed_layers:
                    probe = issuer.issue(
                        layer=layer,
                        generation=1,
                        replay_identity="delivery-issuer-probe",
                        effect_id="effect:delivery-issuer-probe",
                        evidence_ref="delivery-evidence:issuer-probe",
                    )
                    if not delivery_evidence_authority.verify(probe):
                        raise AuthorityValidationError(
                            "delivery evidence issuer is not registered"
                        )
        self._delivery_evidence_authority = delivery_evidence_authority
        self._delivery_evidence_issuers = issuers
        self._business_status_clock = (
            business_status_clock
            if business_status_clock is not None
            else lambda: datetime.now(timezone.utc)
        )
        if model_authority_digest is not None and (
            type(model_authority_digest) is not str
            or len(model_authority_digest) != 71
            or not model_authority_digest.startswith("sha256:")
        ):
            raise AuthorityValidationError("invalid model authority digest")
        try:
            if model_authority_digest is not None:
                int(model_authority_digest[7:], 16)
        except ValueError as exc:
            raise AuthorityValidationError("invalid model authority digest") from exc
        self._model_authority_digest = model_authority_digest
        if knowledge_clock is not None and not callable(knowledge_clock):
            raise AuthorityValidationError("invalid knowledge clock")
        self._knowledge_clock = (
            knowledge_clock
            if knowledge_clock is not None
            else lambda: datetime.now().astimezone()
        )
        if (
            (knowledge_releases or approved_claims or approved_templates)
            and knowledge_valid_at is None
        ):
            raise AuthorityValidationError("knowledge valid-at is required")
        self._non_diagnostic_pipeline = (
            None
            if not (knowledge_releases or approved_claims or approved_templates)
            else NonDiagnosticReplyPipeline(
                current_owner_cards=(),
                current_knowledge_releases=knowledge_releases,
                knowledge_valid_at=knowledge_valid_at,  # type: ignore[arg-type]
                approved_claims=approved_claims,
                approved_templates=approved_templates,
            )
        )
        self._writer_holder_claim = WriterHolderClaim(
            "writer-holder:" + secrets.token_urlsafe(24)
        )
        # Task claims compare monotonic clocks only inside this process epoch.
        # A recreated core therefore cannot inherit a holder's commit authority.
        self._task_runtime_epoch = "task-runtime:" + secrets.token_urlsafe(24)
        self._writer_holder_sessions: dict[tuple[str, str], WriterHolderSession] = {}
        # Serializes lifecycle handoff with every public operation that can
        # mint or consume a writer proof.  ``close`` must not release its host
        # holder while an already-admitted CAS or lease release still carries
        # a valid proof to current-head.
        self._lifecycle_lock = threading.RLock()
        self._closed = False
        self._execution_capability_sessions: dict[AuthoritySnapshot, ExecutionCapabilitySession] = {}
        self._model_effect_executions_started: set[tuple[str, str]] = set()
        # This short-lived marker protects only an in-flight authorization /
        # transport hand-off.  Restart deliberately loses the marker, and the
        # TTL prevents an abandoned host call from suppressing recovery.
        self._owner_delivery_attempts_started: dict[str, tuple[str, float]] = {}
        self._observed_model_reports: dict[
            tuple[str, str], ModelEffectReport
        ] = {}
        self._observed_model_preflight_failures: dict[
            tuple[str, str, str], str
        ] = {}
        # A stopped-recording source is never persisted with its body.  The
        # exact admitted envelope may exist only for the current live turn so
        # a body-free temporary answer or an owner correction can still be
        # attested.  Restart loses this cache by design; exact redelivery can
        # repopulate it from the keyed native-event fingerprint.
        self._recording_excluded_sources: dict[str, SourceEnvelope] = {}
        # A managed-rights correction authorizes one exact stopped-recording
        # evidence stage.  Only body-free digests live here; restart loses the
        # transient grant and the owner must form the pending draft again.
        self._pending_correction_authorizations: dict[
            str,
            tuple[str, str],
        ] = {}
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
            self._recording_excluded_sources.clear()
            self._pending_correction_authorizations.clear()
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
                        payload = command.payload
                        if (
                            command.action == "inbound.admit"
                            and isinstance(payload, InboundAdmitPayload)
                        ):
                            source_receipt = self._store.source_receipt(
                                payload.envelope.causal_id
                            )
                            if source_receipt is not None:
                                self._remember_recording_excluded_source(
                                    source_receipt,
                                    payload.envelope,
                                )
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
        if (
            payload.model_report is not None
            and execution.intent.effect_kind != "model-work"
        ):
            raise ProtocolViolation("model report requires a model effect")
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
            model_report=payload.model_report,
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
        model_execution_key = (
            execution.lease.effect_id,
            execution.lease.lease_id,
        )
        self._observed_model_reports.pop(model_execution_key, None)
        self._model_effect_executions_started.discard(model_execution_key)
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
        if (
            payload.model_report is not None
            and execution.intent.effect_kind != "model-work"
        ):
            raise ProtocolViolation("model report requires a model effect")
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
        if (
            payload.model_report is not None
            and execution.intent.effect_kind != "model-work"
        ):
            raise ProtocolViolation("model report requires a model effect")
        existing = self._store.pending_effect_result(payload.effect_id)
        if existing is None:
            if (
                execution.intent.effect_kind == "model-work"
                and self._model_authority_digest is not None
            ):
                key = (execution.lease.effect_id, execution.lease.lease_id)
                observed = self._observed_model_reports.get(key)
                if observed is None or payload.model_report != observed:
                    return Response(
                        "rejected",
                        command.causal_id,
                        "model-effect-report-mismatch",
                    )
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
            return self._handle_inbound_admit(command, head)
        if command.action == "initialization.disclose":
            return self._handle_initialization_disclose(command)
        if command.action == "initialization.prepare":
            return self._handle_initialization_prepare(command, head)
        if command.action == "turn.prepare":
            return self._handle_daily_turn_prepare(command, head)
        if command.action == "owner.prepare":
            return self._handle_owner_mutation_prepare(command, head)
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
        source_binding = self._daily_source_binding(draft.source_causal_id)
        recording_excluded = (
            source_binding is not None and source_binding[2]
        )
        settings = self._current_owner_settings(head)
        recording_stage = (
            draft
            if draft.turn_kind == "evidence-stage"
            else draft.evidence_stage
        )
        recording_candidates = tuple(
            candidate
            for candidate in (recording_stage, draft)
            if type(candidate) is DailyTurnDraft
        )
        if (
            (settings.recording_stopped or recording_excluded)
            and (
                not recording_candidates
                or any(
                    not self._recording_excluded_candidate_safe(candidate)
                    for candidate in recording_candidates
                )
            )
        ):
            self._store.reject_source_recording(draft.source_causal_id)
            self._recording_excluded_sources.pop(
                draft.source_causal_id,
                None,
            )
            self._pending_correction_authorizations.pop(
                draft.source_causal_id,
                None,
            )
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "health-recording-stopped",
                ),
                True,
            )
        if source_binding is None:
            source_binding = self._daily_source_binding(draft.source_causal_id)
        state = self._store.daily_state()
        if (
            source_binding is None
            or source_binding[0].requested_capability
            not in DAILY_HEALTH_SKILL_NAMES
        ):
            return _Handled(
                Response("rejected", command.causal_id, "daily-source-required"),
                True,
            )
        source, _receipt, _recording_excluded = source_binding
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
        answer_rejection = self._daily_answer_resolution_rejection(
            draft,
            payload.candidate,
            state if continuing_stage is None else post_stage_state,
        )
        if answer_rejection is not None:
            return _Handled(
                Response("rejected", command.causal_id, answer_rejection),
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
        resolution = draft.model_answer_resolution
        if (
            type(resolution) is ModelAnswerResolution
            and resolution.effect_ref is None
        ):
            self._observed_model_preflight_failures.pop(
                (
                    draft.source_causal_id,
                    resolution.strict_request_digest,
                    resolution.model_authority_digest,
                ),
                None,
            )
        return _Handled(
            Response("accepted", command.causal_id, "daily-turn-prepared"),
            True,
        )

    def _handle_owner_mutation_prepare(
        self,
        command: CommandEnvelope,
        head: AuthoritySnapshot,
    ) -> _Handled:
        """Prepare one owner mutation without publishing either business state."""

        payload = command.payload
        if not isinstance(payload, OwnerPreparePayload):
            raise ProtocolViolation("invalid owner mutation payload")
        request = payload.request
        context = request.context
        policy = self._admission_policy
        initialization = self._store.initialization()
        if (
            type(policy) is not AdmissionPolicy
            or initialization is None
            or initialization.phase != "enabled"
            or not self._initialization_configuration_matches(initialization.draft)
        ):
            return _Handled(
                Response(
                    "unavailable",
                    command.causal_id,
                    "owner-authority-unavailable",
                ),
                False,
            )
        if (
            command.causal_id != context.causal_id
            or command.generation != context.current_head_generation
            or context.owner_id != policy.owner_sender_id
            or context.installation_id != head.installation_id
        ):
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "owner-authority-mismatch",
                ),
                True,
            )
        if context.writer_fence != head.writer_fence:
            return _Handled(
                Response(
                    "unavailable",
                    command.causal_id,
                    "stale-writer-fence",
                ),
                False,
            )

        current_settings = self._current_owner_settings(head)
        if request.expected_settings_version != current_settings.version:
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "owner-settings-version-mismatch",
                ),
                True,
            )

        settings_result: dict[str, object] | None = None
        next_settings = current_settings
        if request.settings_command is not None:
            try:
                observed_at = self._owner_settings_clock()
                if (
                    type(observed_at) is not datetime
                    or observed_at.tzinfo is None
                    or observed_at.utcoffset() is None
                ):
                    raise ValueError("owner settings clock must be timezone-aware")
                core_committed_at = observed_at.astimezone(timezone.utc).isoformat()
            except Exception as exc:
                raise StoreUnavailable("owner settings clock unavailable") from exc
            try:
                transition = OwnerSettingsEngine.apply(
                    current_settings,
                    request.settings_command,
                    core_committed_at_utc=core_committed_at,
                    current_head_generation=head.generation,
                    current_writer_fence=head.writer_fence,
                )
            except (SettingsContractViolation, TypeError, ValueError) as exc:
                raise ProtocolViolation("invalid owner settings mutation") from exc
            next_settings = transition.state
            settings_result = transition.result

        daily = request.daily_turn_draft
        daily_result_digest: str | None = None
        if daily is not None:
            rejection = self._owner_correction_rejection(
                request,
                payload.candidate,
                initialization.draft,
                current_settings,
            )
            if rejection is not None:
                return _Handled(
                    Response("rejected", command.causal_id, rejection),
                    True,
                )
            pending = request.pending_correction
            if pending is None:
                raise ProtocolViolation("owner correction metadata missing")
            revision = pending.revision
            daily = replace(
                daily,
                owner_correction_revision=OwnerCorrectionRevision(
                    correction_id=revision.correction_id,
                    object_ref=revision.object_ref,
                    previous_version=revision.previous_version,
                    revision_version=revision.revision_version,
                    reason=revision.reason,
                    corrected_at_utc=revision.corrected_at_utc,
                    source_refs=revision.source_refs,
                    evidence_refs=revision.evidence_refs,
                    affected_object_refs=revision.affected_object_refs,
                    disposition_requests=revision.disposition_requests,
                ),
            )
            request = replace(request, daily_turn_draft=daily)
            expected_result = EncryptedStateStore._daily_result_for_draft(daily)
            daily_result_digest = stable_digest(expected_result.to_storage())
        elif self._store.unresolved_daily_turn() is not None:
            return _Handled(
                Response("unavailable", command.causal_id, "daily-turn-busy"),
                False,
            )

        try:
            prepared = OwnerPreparedMutation(
                request=request,
                next_settings=next_settings,
                settings_result=settings_result,
                daily_result_digest=daily_result_digest,
            )
        except OwnerAuthorityContractViolation as exc:
            raise ProtocolViolation("invalid prepared owner mutation") from exc
        target = RevisionTarget(
            record_id=prepared.record_id,
            revision_digest=prepared.revision_digest,
            transition_id=prepared.transition_id,
            payload_digest=prepared.payload_digest,
        )
        self._store.write_record(
            target.record_id,
            "prepared",
            target.revision_digest,
            target.transition_id,
            PreparedTransition(target=target, base=head),
        )
        self._store.write_owner_mutation(prepared)
        if daily is not None:
            self._store.write_daily_turn("prepared", daily)
        return _Handled(
            Response("accepted", command.causal_id, "owner-mutation-prepared"),
            True,
        )

    def _owner_correction_rejection(
        self,
        request: OwnerMutationRequest,
        candidate: NonDiagnosticCandidate | None,
        initialization: InitializationDraft,
        current_settings: OwnerSettingsState,
    ) -> str | None:
        """Revalidate a rights draft through Ticket 112's exact correction chain."""

        pending = request.pending_correction
        daily = request.daily_turn_draft
        verifier = self._daily_skill_verifier
        bundle = self._daily_skill_bundle
        if (
            pending is None
            or daily is None
            or daily.turn_kind != "complete-turn"
            or type(verifier) is not DailySkillAttestor
            or type(bundle) is not DailySkillBundle
            or not self._initialization_configuration_matches(initialization)
        ):
            return "owner-correction-authority-mismatch"
        state = self._store.daily_state()
        if pending.base_state_digest != state.digest:
            return "owner-correction-state-mismatch"
        if pending.revision.source_refs != (
            f"source:{daily.source_causal_id}",
        ):
            return "owner-correction-source-mismatch"
        try:
            projection = self._managed_rights_projection_from_state(
                state,
                owner_id=request.context.owner_id,
                installation_id=request.context.installation_id,
            )
            expected_pending = ManagedRightsService.correct(
                projection,
                requester_owner_id=request.context.owner_id,
                permission="health_data.correct",
                target_ref=pending.target_ref,
                correction_id=pending.revision.correction_id,
                reason=pending.revision.reason,
                corrected_at_utc=pending.revision.corrected_at_utc,
                replacement_claim=(
                    pending.maintenance_request.replacement_claim
                ),
                correction_source_refs=pending.revision.source_refs,
                affected_object_refs=pending.revision.affected_object_refs,
                disposition_requests=pending.revision.disposition_requests,
            )
        except RightsContractViolation:
            return "owner-correction-target-mismatch"
        if expected_pending != pending:
            return "owner-correction-target-mismatch"
        unresolved = self._store.unresolved_daily_turn()
        stage = daily.evidence_stage
        if (
            type(stage) is DailyTurnDraft
            and (
                stage.steward_plan.atomic_claims
                or stage.steward_plan.evidence_maintenance_requests
                != (pending.maintenance_request,)
            )
        ):
            return "owner-correction-evidence-scope-mismatch"
        if (
            unresolved is None
            or unresolved.phase != "evidence-finalized"
            or type(stage) is not DailyTurnDraft
            or unresolved.draft != stage
            or stage.steward_plan.evidence_maintenance_requests
            != (pending.maintenance_request,)
        ):
            return "owner-correction-evidence-stage-required"
        source_binding = self._daily_source_binding(daily.source_causal_id)
        if (
            source_binding is None
            or source_binding[0].requested_capability
            not in DAILY_HEALTH_SKILL_NAMES
        ):
            return "daily-source-required"
        source, _receipt, recording_excluded = source_binding
        try:
            post_stage_state = state.apply_evidence_stage(stage)
        except AuthorityValidationError:
            return "owner-correction-evidence-stage-invalid"
        if not daily.verify(
            source,
            post_stage_state,
            bundle,
            verifier,
            committed_evidence_stage=stage,
        ):
            return "daily-skill-proof-required"
        if (
            (current_settings.recording_stopped or recording_excluded)
            and not self._recording_excluded_correction_completion_safe(
                daily,
                pending,
                request.owner_authority_binding_digest,
            )
        ):
            return "health-recording-stopped"
        portrait_decisions = tuple(
            result.decision
            for result in daily.responsibility_results
            if result.canonical_name == "health-portrait"
            and type(result.decision) is PortraitDecision
            and result.decision.status
            in {"update", "degrade", "maintain", "withdraw"}
        )
        expected_written_topics = {
            decision.topic_ref
            for decision in portrait_decisions
            if decision.status in {"update", "degrade"}
        }
        expected_withdrawn_topics = {
            decision.topic_ref
            for decision in portrait_decisions
            if decision.status == "withdraw"
        }
        if (
            {topic.topic_ref for topic in daily.portrait_topics}
            != expected_written_topics
            or set(daily.portrait_withdrawals)
            != expected_withdrawn_topics
        ):
            return "owner-correction-affected-scope-mismatch"
        actual_portrait_refs = {
            f"portrait-topic:{decision.topic_ref}"
            for decision in portrait_decisions
        }
        declared_portrait_refs = set(
            pending.revision.affected_object_refs
        )
        if actual_portrait_refs != declared_portrait_refs:
            return "owner-correction-affected-scope-mismatch"
        dispositions = set(pending.revision.disposition_requests)
        if actual_portrait_refs and "rejudge" not in dispositions:
            return "owner-correction-disposition-mismatch"
        if "withdraw_current" in dispositions:
            corrected_targets = {
                change.target_evidence_id
                for change in stage.evidence_applicability_changes
                if change.applicability == "corrected"
            }
            if corrected_targets != set(pending.revision.evidence_refs):
                return "owner-correction-disposition-mismatch"
        return self._daily_answer_resolution_rejection(
            daily,
            candidate,
            post_stage_state,
        )

    def _recording_excluded_correction_completion_safe(
        self,
        daily: DailyTurnDraft,
        pending: PendingCorrectionDraft,
        owner_authority_binding_digest: str,
    ) -> bool:
        """Accept only the closed first-release correction completion shape."""

        stage = daily.evidence_stage
        if (
            type(stage) is not DailyTurnDraft
            or not stage.recording_excluded_persistence_safe()
            or not self._recording_excluded_correction_authorization_matches(
                stage
            )
            or stage.steward_plan.evidence_maintenance_requests
            != (pending.maintenance_request,)
            or len(stage.evidence_cards) != 1
            or len(stage.responsibility_results) != 1
            or daily.owner_authority_binding_digest
            != owner_authority_binding_digest
            or daily.owner_correction_revision is not None
            or daily.model_answer_resolution is not None
            or daily.evidence_cards
            or daily.evidence_compactions
            or daily.evidence_applicability_changes
            or daily.portrait_topics
            or daily.evidence_relations
        ):
            return False
        stage_result = stage.responsibility_results[0]
        card = stage.evidence_cards[0]
        if stage_result.candidate_refs != (card.evidence_id,):
            return False
        continuation = daily.responsibility_results[
            len(stage.responsibility_results) :
        ]
        topics = stage.steward_plan.portrait_topic_refs
        if (
            daily.responsibility_results[
                : len(stage.responsibility_results)
            ]
            != stage.responsibility_results
            or len(continuation) != len(topics)
            or daily.portrait_withdrawals != topics
        ):
            return False
        portrait_atoms: list[OwnerReplyAtom] = []
        for result, topic_ref in zip(continuation, topics):
            expected_decision = PortraitDecision.withdraw(
                topic_ref,
                RECORDING_EXCLUDED_CORRECTION_PORTRAIT_REASON,
            )
            if (
                result.canonical_name != "health-portrait"
                or result.status != "withdraw"
                or result.decision != expected_decision
                or result.candidate_refs != (topic_ref,)
                or result.candidate_change_ids
            ):
                return False
            portrait_atoms.append(
                OwnerReplyAtom.form(
                    kind="record-result",
                    text=f"已撤回画像主题：{topic_ref}。",
                    source_skill="health-portrait",
                    source_result_digest=result.result_digest,
                    required_portrait_topic_refs=(topic_ref,),
                )
            )
        evidence_atom = OwnerReplyAtom.form(
            kind="record-result",
            text=f"已记录：{card.content}。",
            source_skill="health-evidence",
            source_result_digest=stage_result.result_digest,
            required_evidence_ids=(card.evidence_id,),
            required_evidence_change_ids=(
                stage_result.candidate_change_ids
            ),
        )
        limitation_atom = OwnerReplyAtom.form(
            kind="limitation",
            text=(
                "未形成"
                + "、".join(card.does_not_prove)
                + "或健康任务。"
            ),
            source_skill="health-evidence",
            source_result_digest=stage_result.result_digest,
            required_evidence_ids=(card.evidence_id,),
        )
        expected_atoms = (
            evidence_atom,
            *portrait_atoms,
            limitation_atom,
        )
        resolution = daily.steward_resolution
        return (
            daily.reply_atoms == expected_atoms
            and resolution is not None
            and resolution.commit_evidence_ids == (card.evidence_id,)
            and resolution.commit_portrait_topic_refs == topics
            and resolution.reply_atom_ids
            == tuple(atom.atom_id for atom in expected_atoms)
            and resolution.commit_evidence_change_ids
            == tuple(
                change.change_id
                for change in stage.evidence_applicability_changes
            )
        )

    def _daily_answer_resolution_rejection(
        self,
        draft: DailyTurnDraft,
        candidate: NonDiagnosticCandidate | None,
        state: DailyHealthState,
    ) -> str | None:
        """Revalidate a model candidate at the core-owned business-write seam."""

        resolution = draft.model_answer_resolution
        if resolution is None:
            return None if candidate is None else "model-answer-resolution-required"
        if type(resolution) is not ModelAnswerResolution:
            return "model-answer-resolution-invalid"
        if (
            self._model_authority_digest is None
            or resolution.model_authority_digest != self._model_authority_digest
        ):
            return "model-answer-authority-mismatch"

        report: ModelEffectReport | None = None
        effect_ref = resolution.effect_ref
        if effect_ref is None:
            if (
                resolution.status != "failed-closed"
                or resolution.reason_code not in _PRECALL_FAILED_CLOSED_REASONS
            ):
                return "model-effect-reference-required"
            if self._store.model_effect_for_source(draft.source_causal_id) is not None:
                return "model-effect-reference-required"
            observed_reason = self._observed_model_preflight_failures.get(
                (
                    draft.source_causal_id,
                    resolution.strict_request_digest,
                    resolution.model_authority_digest,
                )
            )
            if observed_reason != resolution.reason_code:
                return "model-preflight-observation-required"
        else:
            stored = self._store.effect(effect_ref.effect_id)
            if (
                stored is None
                or stored.state not in {"accepted", "rejected", "unknown"}
                or type(stored.payload) is not TerminalEffect
                or stored.payload.intent.effect_kind != "model-work"
                or type(stored.payload.model_report) is not ModelEffectReport
            ):
                return "model-effect-terminal-required"
            terminal_effect = stored.payload
            report = terminal_effect.model_report
            if (
                terminal_effect.intent.business_source_causal_id
                != draft.source_causal_id
            ):
                return "model-effect-source-mismatch"
            if (
                terminal_effect.status == "unknown"
                or report.outer_effect_status != terminal_effect.status
                or report.digest != effect_ref.report_digest
                or terminal_effect.result_digest != report.digest
                or terminal_effect.intent.intent_digest
                != resolution.strict_request_digest
            ):
                return "model-effect-terminal-mismatch"

        if resolution.status == "failed-closed":
            if candidate is not None:
                return "failed-closed-candidate-forbidden"
            if report is not None and (
                report.reason_code != resolution.reason_code
                or (
                    report.model_status == "completed"
                    and report.reason_code is None
                    and not report.fallback_observed
                    and not report.truncated
                )
            ):
                return "model-failure-reason-mismatch"
            expected_atom = OwnerReplyAtom.form(
                kind="limitation",
                text=render_failed_closed(resolution),
                source_skill="health-steward",
                source_result_digest=resolution.digest,
            )
            steward_proof_digests = {
                proof.skill_use.result_digest
                for proof in draft.skill_proofs
                if proof.skill_use.canonical_name == "health-steward"
            }
            if (
                expected_atom not in draft.reply_atoms
                or draft.steward_resolution is None
                or expected_atom.atom_id not in draft.steward_resolution.reply_atom_ids
                or any(
                    atom.source_skill == "health-steward"
                    and atom.source_result_digest
                    not in steward_proof_digests | {resolution.digest}
                    for atom in draft.reply_atoms
                )
                or {
                    atom.atom_id: atom
                    for atom in draft.reply_atoms
                    if atom.source_skill == "health-steward"
                    and atom.source_result_digest == resolution.digest
                }
                != {expected_atom.atom_id: expected_atom}
            ):
                return "failed-closed-owner-prompt-required"
            return None

        if (
            candidate is None
            or report is None
            or report.model_status != "completed"
            or not report.terminal_proven
            or report.reason_code is not None
            or report.fallback_observed
            or report.truncated
        ):
            return "completed-model-result-required"
        if report.candidate_digest != resolution.candidate_digest:
            return "model-candidate-provenance-mismatch"
        if stable_digest(candidate.to_wire()) != resolution.candidate_digest:
            return "model-candidate-digest-mismatch"
        pipeline = self._non_diagnostic_pipeline
        if type(pipeline) is not NonDiagnosticReplyPipeline:
            return "model-answer-configuration-mismatch"
        try:
            knowledge_now = self._knowledge_clock()
            if (
                type(knowledge_now) is not datetime
                or knowledge_now.tzinfo is None
                or knowledge_now.utcoffset() is None
            ):
                return "model-answer-configuration-mismatch"
            knowledge_valid_at = knowledge_now.isoformat()
        except Exception:
            return "model-answer-configuration-mismatch"
        try:
            template = pipeline.approved_template(candidate.template_id)
            rendered = pipeline.with_current_owner_cards(
                state.current_evidence_cards,
                knowledge_valid_at=knowledge_valid_at,
            ).render(candidate)
        except NonDiagnosticContractViolation:
            return "non-diagnostic-candidate-rejected"
        rendered_atoms = {atom.atom_id: atom for atom in rendered.reply_atoms}
        draft_model_atoms = {
            atom.atom_id: atom
            for atom in draft.reply_atoms
            if atom.source_skill == "health-steward"
            and atom.source_result_digest == resolution.candidate_digest
        }
        steward_proof_digests = {
            proof.skill_use.result_digest
            for proof in draft.skill_proofs
            if proof.skill_use.canonical_name == "health-steward"
        }
        selected_atom_ids = (
            ()
            if draft.steward_resolution is None
            else draft.steward_resolution.reply_atom_ids
        )
        selected_model_atom_ids = tuple(
            atom_id for atom_id in selected_atom_ids if atom_id in rendered_atoms
        )
        if (
            resolution.template_id != template.template_id
            or resolution.template_version != template.version
            or resolution.template_digest != stable_digest(template.to_wire())
            or resolution.rendered_reply_digest
            != stable_digest(rendered.to_commit_wire())
            or draft.steward_resolution is None
            or draft_model_atoms != rendered_atoms
            or selected_model_atom_ids
            != tuple(atom.atom_id for atom in rendered.reply_atoms)
            or any(
                atom.source_skill == "health-steward"
                and atom.source_result_digest
                not in steward_proof_digests | {resolution.candidate_digest}
                for atom in draft.reply_atoms
            )
        ):
            return "deterministic-model-reply-mismatch"
        return None

    def _daily_source_binding(
        self,
        source_causal_id: str,
    ) -> tuple[SourceEnvelope, SourceReceipt, bool] | None:
        """Resolve a daily source without restoring a stopped-recording body."""

        receipt = self._store.source_receipt(source_causal_id)
        if receipt is None:
            return None
        if receipt.managed_cursor_state == "held":
            source = receipt.envelope
            if type(source.body) is not str:
                return None
            return source, receipt, False
        if receipt.managed_cursor_state != "recording-excluded":
            return None
        source = self._recording_excluded_sources.get(source_causal_id)
        if (
            type(source) is not SourceEnvelope
            or not self._store.source_receipt_matches_exact_delivery(
                receipt,
                source,
            )
        ):
            return None
        return source, receipt, True

    def _remember_recording_excluded_source(
        self,
        receipt: SourceReceipt,
        source: SourceEnvelope,
    ) -> None:
        if (
            receipt.managed_cursor_state == "recording-excluded"
            and self._store.source_receipt_matches_exact_delivery(receipt, source)
        ):
            self._recording_excluded_sources[source.causal_id] = source

    def _handle_inbound_admit(
        self,
        command: CommandEnvelope,
        head: AuthoritySnapshot,
    ) -> _Handled:
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
            recording_excluded = self._current_owner_settings(
                head
            ).excludes_health_recording(
                payload.envelope.protocol_timestamp
            )
            receipt = self._store.save_source_envelope(
                payload.envelope,
                confirm_native_replay=True,
                retain_body=not recording_excluded,
            )
            if recording_excluded and receipt.managed_cursor_state == "held":
                receipt = self._store.reject_source_recording(
                    payload.envelope.causal_id
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
            self._remember_recording_excluded_source(
                receipt,
                payload.envelope,
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
            owner_mutation = (
                self._store.owner_mutation_for_record(record_id)
                if transition_kind == "owner"
                else None
            )
            daily = (
                self._store.daily_turn_for_record(record_id)
                if transition_kind in {"daily", "owner"}
                else None
            )
            if transition_kind == "ticket115":
                self._store.finalize_ticket115_mutation(
                    record_id,
                    committed,
                )
            else:
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
            elif transition_kind == "owner":
                if (
                    owner_mutation is None
                    or type(owner_mutation.prepared)
                    not in {
                        OwnerPreparedMutation,
                        OwnerPreparedCorrectionRecovery,
                    }
                ):
                    raise KeyUnavailable("owner mutation aggregate missing")
                prepared_owner = owner_mutation.prepared
                if (
                    type(prepared_owner)
                    is OwnerPreparedCorrectionRecovery
                    and daily is None
                ):
                    raise KeyUnavailable("owner correction aggregate missing")
                if daily is not None:
                    if (
                        daily.draft is None
                        or daily.draft.turn_kind != "complete-turn"
                        or (
                            type(prepared_owner)
                            is OwnerPreparedCorrectionRecovery
                            and not prepared_owner.matches_daily(daily.draft)
                        )
                        or (
                            type(prepared_owner) is OwnerPreparedMutation
                            and daily.draft
                            != prepared_owner.request.daily_turn_draft
                        )
                    ):
                        raise KeyUnavailable("owner correction aggregate mismatch")
                    self._store.finalize_daily_turn(daily.draft)
                    self._store.mark_daily_source_family_business_committed(
                        daily.draft.source_causal_id
                    )
                    self._recording_excluded_sources.pop(
                        daily.draft.source_causal_id,
                        None,
                    )
                    self._pending_correction_authorizations.pop(
                        daily.draft.source_causal_id,
                        None,
                    )
                current_settings = self._store.owner_settings()
                previous_cancelled = (
                    frozenset()
                    if current_settings is None
                    else frozenset(current_settings.cancelled_task_refs)
                )
                newly_cancelled = tuple(
                    task_ref
                    for task_ref in prepared_owner.next_settings.cancelled_task_refs
                    if task_ref not in previous_cancelled
                )
                task_state = self._store.task_runtime()
                next_task_state = None
                matching_task_refs = (
                    ()
                    if type(task_state) is not TaskRuntimeState
                    else tuple(
                        task_ref
                        for task_ref in newly_cancelled
                        if any(
                            task.task_id == task_ref
                            for task in task_state.tasks
                        )
                    )
                )
                if matching_task_refs:
                    settings_result = prepared_owner.settings_result
                    effective_at_utc = (
                        None
                        if type(settings_result) is not dict
                        else settings_result.get("effective_at_utc")
                    )
                    if (
                        type(settings_result) is not dict
                        or type(effective_at_utc) is not str
                    ):
                        raise KeyUnavailable(
                            "owner task cancellation effective time missing"
                        )
                    control_ref = (
                        prepared_owner.command_id
                        if type(prepared_owner)
                        is OwnerPreparedCorrectionRecovery
                        else prepared_owner.request.context.command_id
                    )
                    next_task_state = task_state
                    for task_ref in matching_task_refs:
                        next_task_state = TaskEngine.apply_owner_cancellation(
                            next_task_state,
                            task_ref,
                            control_ref=control_ref,
                            effective_at_utc=effective_at_utc,
                        ).state
                self._store.finalize_owner_mutation(
                    prepared_owner,
                    task_state=next_task_state,
                )
            elif transition_kind == "daily":
                if daily is None:
                    raise KeyUnavailable("daily turn aggregate missing")
                if daily.draft is None:
                    raise KeyUnavailable("daily turn draft missing")
                if daily.draft.turn_kind == "evidence-stage":
                    self._store.finalize_daily_evidence_stage(daily.draft)
                else:
                    self._store.finalize_daily_turn(daily.draft)
                    self._store.mark_daily_source_family_business_committed(
                        daily.draft.source_causal_id
                    )
                    self._recording_excluded_sources.pop(
                        daily.draft.source_causal_id,
                        None,
                    )
                    self._pending_correction_authorizations.pop(
                        daily.draft.source_causal_id,
                        None,
                    )
            elif transition_kind == "ticket115":
                pass
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
        if effect_kind == "owner-delivery":
            source_causal_id = payload.business_source_causal_id
            try:
                settings = self._current_owner_settings(head)
                outbox = self._ticket115_outbox_state_open(settings)
                outbox_record = outbox.record(source_causal_id)
                outbox_intent = outbox_record.intent
                attempted = outbox_record.optional_fact("attempted")
                observed_at_utc = self._owner_delivery_clock_utc_open()
                if observed_at_utc is None or attempted is None:
                    raise TypeError("owner delivery clock must be timezone-aware")
            except (
                AuthorityValidationError,
                DeliveryContractViolation,
                SettingsContractViolation,
                TypeError,
                ValueError,
            ):
                return _Handled(
                    Response(
                        "rejected",
                        command.causal_id,
                        "owner-delivery-outbox-binding-required",
                    ),
                    True,
                )
            if (
                source_causal_id != outbox_intent.intent_id
                or command.causal_id != outbox_intent.effect_request_id
                or payload.request_digest != outbox_intent.semantic_digest
                or self._owner_delivery_sendable_open(
                    outbox_intent,
                    settings,
                    observed_at_utc=observed_at_utc,
                    expected_attempt_ref=attempted.attempt_ref,
                )
                is None
            ):
                return _Handled(
                    Response(
                        "rejected",
                        command.causal_id,
                        "owner-delivery-outbox-binding-mismatch",
                    ),
                    True,
                )
            intent = EffectIntent(
                effect_id=self._effect_id(command.causal_id),
                effect_kind=effect_kind,
                intent_digest=payload.request_digest,
                authority=head,
                business_source_causal_id=source_causal_id,
            )
            self._store.write_effect(intent.effect_id, "intent", intent)
            return _Handled(
                Response(
                    "accepted",
                    command.causal_id,
                    "effect-intent-issued",
                    EffectIntentMeta(intent),
                ),
                True,
            )
        if effect_kind != "model-work":
            return _Handled(
                Response("rejected", command.causal_id, "delivery-not-supported-in-ticket-110"),
                True,
            )
        source_causal_id = payload.business_source_causal_id
        if self._model_authority_digest is not None and source_causal_id is None:
            return _Handled(
                Response(
                    "rejected",
                    command.causal_id,
                    "model-effect-source-required",
                ),
                True,
            )
        if source_causal_id is not None:
            source_binding = self._daily_source_binding(source_causal_id)
            daily = self._store.daily_turn(source_causal_id)
            if (
                source_binding is None
                or daily is None
                or daily.phase != "evidence-finalized"
            ):
                return _Handled(
                    Response(
                        "rejected",
                        command.causal_id,
                        "model-effect-source-not-ready",
                    ),
                    True,
                )
            existing = self._store.model_effect_for_source(source_causal_id)
            if existing is not None:
                reason = "model-effect-already-bound"
                if (
                    existing.state == "accepted"
                    and type(existing.payload) is TerminalEffect
                    and self._model_report_has_accepted_candidate(
                        existing.payload.model_report
                    )
                ):
                    reason = "model-answer-owner-decision-required"
                return _Handled(
                    Response("rejected", command.causal_id, reason),
                    True,
                )
        intent = EffectIntent(
            effect_id=self._effect_id(command.causal_id),
            effect_kind=effect_kind,
            intent_digest=payload.request_digest,
            authority=head,
            business_source_causal_id=source_causal_id,
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

    @staticmethod
    def _model_report_has_accepted_candidate(report: object) -> bool:
        return (
            type(report) is ModelEffectReport
            and report.model_status == "completed"
            and report.terminal_proven
            and report.reason_code is None
            and not report.fallback_observed
            and not report.truncated
            and report.candidate_digest is not None
        )

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
            validate_controlled_effect_kind(value.effect_kind)
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
                business_source_causal_id=value.business_source_causal_id,
            )
        except Exception:
            return None

    def claim_effect_execution(self, intent: EffectIntent) -> EffectExecutionGrant | None:
        """Claim an effect under a durable terminal-observation tripwire."""

        with self._lifecycle_lock:
            if self._closed:
                return None
            return self._claim_effect_execution_open(intent)

    def _validated_effect_execution(
        self,
        grant: EffectExecutionGrant | None,
        request_digest: str,
        *,
        effect_kind: str,
    ) -> ExecutingEffect | None:
        """Return one exact live execution bound to an unforgeable bearer."""

        if type(grant) is not EffectExecutionGrant:
            return None
        try:
            validate_opaque_text(request_digest, "effect request digest")
            validate_controlled_effect_kind(effect_kind)
            lease = object.__getattribute__(grant, "lease")
            capability = object.__getattribute__(
                grant,
                "completion_capability",
            )
            if type(lease) is not ExecutionLease:
                return None
            authority = object.__getattribute__(lease, "authority")
            if type(authority) is not AuthoritySnapshot:
                return None
            canonical_grant = EffectExecutionGrant(
                lease=ExecutionLease(
                    lease_id=object.__getattribute__(lease, "lease_id"),
                    effect_id=object.__getattribute__(lease, "effect_id"),
                    intent_digest=object.__getattribute__(
                        lease,
                        "intent_digest",
                    ),
                    authority=AuthoritySnapshot(
                        installation_id=object.__getattribute__(
                            authority,
                            "installation_id",
                        ),
                        generation=object.__getattribute__(
                            authority,
                            "generation",
                        ),
                        revision_digest=object.__getattribute__(
                            authority,
                            "revision_digest",
                        ),
                        transition_id=object.__getattribute__(
                            authority,
                            "transition_id",
                        ),
                        writer_fence=object.__getattribute__(
                            authority,
                            "writer_fence",
                        ),
                        terminal=object.__getattribute__(authority, "terminal"),
                        site=object.__getattribute__(authority, "site"),
                    ),
                    holder_id=object.__getattribute__(lease, "holder_id"),
                ),
                completion_capability=capability,
            )
        except Exception:
            return None
        lease = canonical_grant.lease
        if lease.intent_digest != request_digest:
            return None
        stored = self._store.effect(lease.effect_id)
        if (
            stored is None
            or stored.state != "executing"
            or type(stored.payload) is not ExecutingEffect
        ):
            return None
        execution = stored.payload
        if (
            execution.lease != lease
            or execution.intent.effect_kind != effect_kind
            or execution.intent.intent_digest != request_digest
        ):
            return None
        finalized = self._store.finalized_authority()
        if (
            finalized is None
            or execution.intent.authority.mismatch_reason(finalized) is not None
        ):
            return None
        writer_proof = self._writer_proof_from_vault(execution.intent.authority)
        if writer_proof is None or not self._completion_capability_is_held(
            execution,
            canonical_grant.completion_capability,
            writer_proof,
        ):
            return None
        return execution

    def _validated_model_execution(
        self,
        grant: EffectExecutionGrant | None,
        request_digest: str,
    ) -> ExecutingEffect | None:
        return self._validated_effect_execution(
            grant,
            request_digest,
            effect_kind="model-work",
        )

    @staticmethod
    def _model_authorization_failure() -> StrictModelOutcome:
        return StrictModelOutcome(
            disposition="failed-closed",
            model_effect="not-started",
            reason_code="model-effect-authorization-required",
            candidate=None,
        )

    def execute_strict_health_model(
        self,
        llm: StrictHealthLLM,
        request: StrictModelRequest,
        source_causal_id: str,
        grant: EffectExecutionGrant | None,
        adapter: StrictModelAdapter,
    ) -> StrictModelOutcome:
        """Validate and perform exactly one core-owned strict model attempt."""

        if (
            type(llm) is not StrictHealthLLM
            or type(request) is not StrictModelRequest
        ):
            return self._model_authorization_failure()
        try:
            validate_opaque_text(
                source_causal_id,
                "model business source causal identifier",
            )
        except ValueError:
            return self._model_authorization_failure()
        try:
            canonical_request = StrictModelRequest.canonical_copy(request)
            canonical_llm = StrictHealthLLM.canonical_copy(llm)
            payload = StrictModelRequest.to_wire(canonical_request)
            request_digest = stable_digest(payload)
            model_authority_digest = canonical_llm.model_authority_digest
            preflight = StrictHealthLLM.preflight(
                canonical_llm,
                canonical_request,
            )
            if preflight is not None and type(preflight) is not StrictModelOutcome:
                return self._model_authorization_failure()
            unknown_outcome = (
                None
                if preflight is not None
                else StrictHealthLLM.transport_unknown_outcome(
                    canonical_llm,
                    canonical_request,
                )
            )
            if unknown_outcome is not None and (
                type(unknown_outcome) is not StrictModelOutcome
                or unknown_outcome.disposition != "unknown"
                or type(unknown_outcome.model_report) is not ModelEffectReport
            ):
                return self._model_authorization_failure()
        except Exception:
            return self._model_authorization_failure()
        with self._lifecycle_lock:
            if self._closed:
                return self._model_authorization_failure()
            try:
                with self._store.serialized():
                    self._store.verify_key()
                    if self._terminal_closed():
                        return self._model_authorization_failure()
                    if self._writer_entry_preflight() is not None:
                        return self._model_authorization_failure()
                    source_binding = self._daily_source_binding(
                        source_causal_id
                    )
                    daily = self._store.daily_turn(source_causal_id)
                    if (
                        source_binding is None
                        or daily is None
                        or daily.phase != "evidence-finalized"
                        or self._model_authority_digest is None
                        or model_authority_digest != self._model_authority_digest
                    ):
                        return self._model_authorization_failure()
                    preflight_key = (
                        source_causal_id,
                        request_digest,
                        self._model_authority_digest,
                    )
                    if preflight is not None:
                        if (
                            preflight.reason_code
                            in _PRECALL_FAILED_CLOSED_REASONS
                            and self._store.model_effect_for_source(
                                source_causal_id
                            )
                            is None
                        ):
                            self._observed_model_preflight_failures[
                                preflight_key
                            ] = preflight.reason_code
                        return preflight
                    if type(grant) is not EffectExecutionGrant:
                        if self._store.model_effect_for_source(source_causal_id) is None:
                            self._observed_model_preflight_failures[
                                preflight_key
                            ] = "model-effect-authorization-required"
                        return self._model_authorization_failure()
                    execution = self._validated_model_execution(
                        grant,
                        request_digest,
                    )
                    if execution is None:
                        return self._model_authorization_failure()
                    key = (
                        execution.lease.effect_id,
                        execution.lease.lease_id,
                    )
                    if (
                        execution.intent.business_source_causal_id
                        != source_causal_id
                        or execution.model_attempt_started
                        or key in self._model_effect_executions_started
                    ):
                        return self._model_authorization_failure()
                    self._store.write_effect(
                        execution.intent.effect_id,
                        "executing",
                        replace(execution, model_attempt_started=True),
                    )
                    self._model_effect_executions_started.add(key)
            except (KeyUnavailable, StoreUnavailable):
                return self._model_authorization_failure()

            try:
                execute_adapter = getattr(adapter, "execute")
                if not callable(execute_adapter):
                    raise TypeError("model adapter execute is not callable")
                result = execute_adapter(payload)
            except Exception:
                outcome = unknown_outcome
            else:
                try:
                    outcome = (
                        StrictHealthLLM.resolve_transport_result(
                            canonical_llm,
                            canonical_request,
                            ModelTransportResult.canonical_copy(result),
                        )
                        if type(result) is ModelTransportResult
                        else unknown_outcome
                    )
                except Exception:
                    outcome = unknown_outcome
            if type(outcome.model_report) is not ModelEffectReport:
                outcome = unknown_outcome
            self._observed_model_reports[key] = outcome.model_report
            return outcome

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
                    candidate_intent = (
                        stored.payload
                        if stored.state == "intent"
                        and type(stored.payload) is EffectIntent
                        else stored.payload.intent
                        if stored.state == "claiming"
                        and type(stored.payload) is ClaimingEffect
                        else None
                    )
                    if (
                        type(candidate_intent) is EffectIntent
                        and candidate_intent.effect_kind == "owner-delivery"
                    ):
                        try:
                            observed_at_utc = self._owner_delivery_clock_utc_open()
                            if observed_at_utc is None:
                                return None
                            settings = self._current_owner_settings(head)
                            outbox_record = self._ticket115_outbox_state_open(
                                settings
                            ).record(
                                candidate_intent.business_source_causal_id
                            )
                            outbox_intent = outbox_record.intent
                            attempted = outbox_record.optional_fact("attempted")
                            if (
                                attempted is None
                                or
                                candidate_intent.intent_digest
                                != outbox_intent.semantic_digest
                            ):
                                return None
                            if self._owner_delivery_sendable_open(
                                outbox_intent,
                                settings,
                                observed_at_utc=observed_at_utc,
                                expected_attempt_ref=attempted.attempt_ref,
                            ) is None:
                                return None
                        except (
                            AuthorityValidationError,
                            DeliveryContractViolation,
                            SettingsContractViolation,
                            TypeError,
                            ValueError,
                        ):
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

    def _current_owner_settings(
        self,
        authority: AuthoritySnapshot,
    ) -> OwnerSettingsState:
        """Load Ticket 114 settings or derive their sole Ticket 111 seed."""

        policy = self._admission_policy
        initialization = self._store.initialization()
        if (
            type(authority) is not AuthoritySnapshot
            or type(policy) is not AdmissionPolicy
            or initialization is None
            or initialization.phase != "enabled"
            or not self._initialization_configuration_matches(initialization.draft)
        ):
            raise AuthorityValidationError("owner-settings-unavailable")
        stored = self._store.owner_settings()
        if stored is not None:
            if (
                stored.owner_id != policy.owner_sender_id
                or stored.installation_id != authority.installation_id
            ):
                raise AuthorityValidationError("owner-settings-authority-mismatch")
            return self._project_current_owner_settings(stored)

        owner = initialization.draft.owner
        configured = owner.support_contact
        contact: SupportContactSettings | None = None
        if configured is not None:
            contact_id = "support-contact:" + stable_digest(
                {
                    "owner_id": policy.owner_sender_id,
                    "installation_id": authority.installation_id,
                    "contact": configured.to_storage(),
                }
            ).removeprefix("sha256:")
            contact = SupportContactSettings(
                contact_id=contact_id,
                version=1,
                owner_id=policy.owner_sender_id,
                installation_id=authority.installation_id,
                identity_label=configured.contact_ref,
                method_kind=configured.method,
                method_value=configured.contact_ref,
                purpose=configured.purpose,
                minimum_alert_fields=(
                    "owner_recognizable_name",
                    "event_time",
                    "fixed_urgent_help_request",
                ),
                route_id=configured.method,
                route_generation=1,
                disclosure_version=(
                    initialization.draft.skill_use.disclosure_version
                ),
                dedicated_paused=False,
                alert_authority_status="invalidated",
                alert_approval_id=None,
                alert_authority_binding=None,
                correction_authority_status="invalidated",
                correction_authority_id=None,
                correction_authority_binding=None,
                max_corrections_per_alert=1,
            )
        preferences = owner.preferences
        seeded = OwnerSettingsEngine.seed(
            owner_id=policy.owner_sender_id,
            installation_id=authority.installation_id,
            version=1,
            timezone=owner.timezone,
            preferences={
                "contact_window": preferences.contact_window,
                "expression_style": preferences.expression_style,
                "proactive_contact": preferences.proactive_support,
                "ordinary_notifications": {
                    kind: "not-configured"
                    for kind in ORDINARY_NOTIFICATION_KINDS
                },
            },
            consent={
                "enabled": True,
                "data_scope": owner.data_boundary,
                # Ticket 111 has one first-hop route fact rather than separate
                # logical-route and recipient fields.  Preserve that fact in
                # both Ticket 114 views instead of fabricating a second value.
                "route_id": owner.first_hop_route,
                "first_hop_recipient": owner.first_hop_route,
                "configuration_generation": 1,
                "consent_generation": 1,
                "disclosure_version": (
                    initialization.draft.skill_use.disclosure_version
                ),
                "disclosure_digest": (
                    initialization.draft.skill_proof.disclosure_digest
                ),
            },
            contact=contact,
            completed_review_keys=(),
        )
        return self._project_current_owner_settings(seeded)

    def _project_current_owner_settings(
        self,
        state: OwnerSettingsState,
    ) -> OwnerSettingsState:
        """Materialize time and core-owned route facts over persisted settings."""

        try:
            observed_at = self._owner_settings_clock()
            if (
                type(observed_at) is not datetime
                or observed_at.tzinfo is None
                or observed_at.utcoffset() is None
            ):
                raise ValueError("owner settings clock must be timezone-aware")
            observed_at_utc = observed_at.astimezone(timezone.utc).isoformat()
            projected = OwnerSettingsEngine.activate_due_timezone_transition(
                state,
                observed_at_utc=observed_at_utc,
            ).state
            provider = self._route_configuration_provider
            if provider is None:
                return projected
            route_fact = provider()
            if type(route_fact) is not RouteConfigurationUpdate:
                raise ValueError("route configuration provider returned invalid fact")
            return OwnerSettingsEngine.observe_route_configuration(
                projected,
                route_fact,
            ).state
        except (SettingsContractViolation, TypeError, ValueError) as exc:
            raise AuthorityValidationError("owner-settings-projection-unavailable") from exc

    def owner_settings_state(self) -> OwnerSettingsState:
        """Return the current owner-scoped settings after integrity proof."""

        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError("owner-settings-unavailable")
            try:
                if self._probe_open().state is not ProbeState.HEALTHY:
                    raise AuthorityValidationError("owner-settings-unavailable")
                self._store.verify_key()
                authority = self._store.finalized_authority()
                if authority is None or not self._store.verify_integrity(authority):
                    raise AuthorityValidationError("owner-settings-unavailable")
                return self._current_owner_settings(authority)
            except (KeyUnavailable, StoreUnavailable, SettingsContractViolation) as exc:
                raise AuthorityValidationError("owner-settings-unavailable") from exc

    def managed_owner_settings_read(self) -> dict[str, object]:
        """Return the policy-bound health-settings projection for the owner."""

        policy = self._admission_policy
        if type(policy) is not AdmissionPolicy:
            raise AuthorityValidationError("owner-settings-read-unavailable")
        try:
            return OwnerSettingsEngine.managed_view(
                self.owner_settings_state(),
                requester_owner_id=policy.owner_sender_id,
            )
        except (SettingsContractViolation, TypeError, ValueError) as exc:
            raise AuthorityValidationError(
                "owner-settings-read-unavailable"
            ) from exc

    @staticmethod
    def _ticket115_commit_command(
        mutation: Ticket115PreparedMutation,
    ) -> CommandEnvelope:
        target = mutation.prepared.target
        identity = target.transition_id.removeprefix("transition:ticket115:")
        return CommandEnvelope(
            peer="plugin",
            action="state.commit",
            source="health_tasks",
            causal_id="ticket115-commit:" + identity,
            generation=mutation.prepared.base.generation,
            scope=("state:commit",),
            payload=StateCommitPayload(
                record_id=target.record_id,
                revision_digest=target.revision_digest,
                transition_id=target.transition_id,
                writer_fence=mutation.prepared.base.writer_fence,
            ),
        )

    @staticmethod
    def _ticket115_finalize_command(
        mutation: Ticket115PreparedMutation,
        committed: CommittedTransition | None = None,
    ) -> CommandEnvelope:
        target = mutation.prepared.target
        identity = target.transition_id.removeprefix("transition:ticket115:")
        generation = (
            mutation.prepared.base.generation + 1
            if committed is None
            else committed.committed.generation
        )
        return CommandEnvelope(
            peer="plugin",
            action="state.finalize",
            source="health_tasks",
            causal_id="ticket115-finalize:" + identity,
            generation=generation,
            scope=("state:finalize",),
            payload=StateCommitPayload(
                record_id=target.record_id,
                revision_digest=target.revision_digest,
                transition_id=target.transition_id,
                writer_fence=mutation.prepared.base.writer_fence,
            ),
        )

    def _recover_ticket115_mutation(self) -> None:
        """Resume the sole prepared Ticket 115 CAS before any later read/write."""

        mutation = self._store.pending_ticket115_mutation()
        if mutation is None:
            return
        self._release_orphan_ticket115_execution_leases()
        target = mutation.prepared.target
        stored = self._store.record(target.record_id)
        if stored is None:
            raise AuthorityValidationError("ticket115 mutation record missing")
        if stored.state in {"prepared", "unknown"}:
            pending = self._store.pending_for_record(target.record_id)
            command = (
                self._ticket115_commit_command(mutation)
                if pending is None
                else pending.command
            )
            response = self.handle(command)
            if response.status not in {"accepted", "replayed"}:
                raise AuthorityValidationError(
                    response.reason_code or "ticket115-current-head-unavailable"
                )
            stored = self._store.record(target.record_id)
        if (
            stored is None
            or stored.state != "committed"
            or type(stored.payload) is not CommittedTransition
            or stored.payload.prepared != mutation.prepared
        ):
            raise AuthorityValidationError("ticket115 mutation commit missing")
        response = self.handle(
            self._ticket115_finalize_command(mutation, stored.payload)
        )
        if response.status not in {"accepted", "replayed"}:
            raise AuthorityValidationError(
                response.reason_code or "ticket115-finalization-unavailable"
            )

    def _release_orphan_ticket115_execution_leases(self) -> None:
        """Release stale owner-delivery leases before resuming a Ticket 115 CAS."""

        try:
            head = self._read_head()
            writer_proof = self._current_writer_proof(head)
        except (CurrentHeadError, HeadTerminal, StoreUnavailable):
            return
        if writer_proof is None:
            return
        for effect_id in self._store.unresolved_effects():
            stored = self._store.effect(effect_id)
            if stored is None or stored.state != "executing":
                continue
            execution = stored.payload
            if (
                type(execution) is not ExecutingEffect
                or execution.intent.effect_kind != "owner-delivery"
                or execution.intent.business_source_causal_id is None
                or self._owner_delivery_attempt_is_active(
                    execution.intent.business_source_causal_id
                )
                or execution.lease.authority.mismatch_reason(head) is not None
            ):
                continue
            digest = stable_digest(
                {
                    "contract": "ticket115-orphan-lease-release-v1",
                    "effect_id": effect_id,
                    "lease_id": execution.lease.lease_id,
                }
            )
            binding = CurrentHeadRecoveryBinding(
                action="effect.result",
                causal_id="ticket115-orphan-lease-release:" + digest,
                command_digest=digest,
            )
            try:
                self._release_execution_lease(
                    execution.lease,
                    writer_proof=writer_proof,
                    recovery_binding=binding,
                )
            except (
                CurrentHeadError,
                ExecutionLeaseNotFound,
                HeadConflict,
                HeadTimeout,
                HeadUnknown,
                MalformedCurrentHeadResponse,
            ):
                continue

    def _prepare_ticket115_facts_open(
        self,
        head: AuthoritySnapshot,
        settings: OwnerSettingsState,
        *,
        task_state: TaskRuntimeState | None = None,
        review_state: DailyReviewLedger | None = None,
        delivery_state: DeliveryOutboxState | None = None,
        health_command_receipt: HealthCommandReceipt | None = None,
    ) -> Ticket115PreparedMutation | None:
        """Persist one complete invisible aggregate revision before remote CAS."""

        current_task = self._ticket115_task_state_open(settings)
        current_review = self._ticket115_review_ledger_open(settings)
        current_delivery = self._ticket115_outbox_state_open(settings)
        next_task = current_task if task_state is None else task_state
        next_review = current_review if review_state is None else review_state
        next_delivery = (
            current_delivery if delivery_state is None else delivery_state
        )
        if (
            next_task == current_task
            and next_review == current_review
            and next_delivery == current_delivery
            and health_command_receipt is None
        ):
            return None
        mutation = Ticket115PreparedMutation.prepare(
            base=head,
            current_task_state=current_task,
            current_review_state=current_review,
            current_delivery_state=current_delivery,
            task_state=next_task,
            review_state=next_review,
            delivery_state=next_delivery,
            health_command_receipt=health_command_receipt,
        )
        self._store.prepare_ticket115_mutation(mutation)
        return mutation

    def _complete_ticket115_mutation(
        self,
        mutation: Ticket115PreparedMutation | None,
    ) -> None:
        if mutation is None:
            return
        response = self.handle(self._ticket115_commit_command(mutation))
        if response.status not in {"accepted", "replayed"}:
            raise AuthorityValidationError(
                response.reason_code or "ticket115-current-head-unavailable"
            )
        stored = self._store.record(mutation.prepared.target.record_id)
        if (
            stored is None
            or stored.state != "committed"
            or type(stored.payload) is not CommittedTransition
        ):
            raise AuthorityValidationError("ticket115 mutation commit missing")
        response = self.handle(
            self._ticket115_finalize_command(mutation, stored.payload)
        )
        if response.status not in {"accepted", "replayed"}:
            raise AuthorityValidationError(
                response.reason_code or "ticket115-finalization-unavailable"
            )

    @contextmanager
    def _ticket115_write_authority(
        self,
    ) -> Iterator[tuple[AuthoritySnapshot, OwnerSettingsState]]:
        """Hold the single-writer lane across one local Ticket 115 mutation."""

        if self._closed:
            raise AuthorityValidationError("ticket115-authority-unavailable")
        self._recover_ticket115_mutation()
        with self._store.serialized():
            self._store.verify_key()
            if self._terminal_closed():
                raise AuthorityValidationError(
                    self._closed_reason or "current-head-terminal"
                )
            writer_entry = self._writer_entry_preflight()
            if writer_entry is not None:
                raise AuthorityValidationError(
                    writer_entry.reason_code or "current-writer-holder-missing"
                )
            self._enter_current_head_guard()
            try:
                try:
                    head = self._read_head()
                except HeadTerminal as exc:
                    self._latch_terminal()
                    raise AuthorityValidationError(
                        self._closed_reason or "current-head-terminal"
                    ) from exc
                except (HeadConflict, HeadTimeout, HeadUnknown, CurrentHeadError) as exc:
                    raise AuthorityValidationError(
                        "current-head-unavailable"
                    ) from exc
                authority = self._store.finalized_authority()
                if (
                    authority is None
                    or authority.mismatch_reason(head) is not None
                    or not self._store.verify_integrity(authority)
                ):
                    raise AuthorityValidationError(
                        "ticket115-authority-unavailable"
                    )
                if self._current_writer_proof(head) is None:
                    raise AuthorityValidationError(
                        "current-writer-holder-missing"
                    )
                settings = self._current_owner_settings(head)
                yield head, settings
            finally:
                self._exit_current_head_guard()

    def _ticket115_task_state_open(
        self,
        settings: OwnerSettingsState,
    ) -> TaskRuntimeState:
        stored = self._store.task_runtime()
        state = (
            TaskRuntimeState.empty(settings.owner_id, settings.installation_id)
            if stored is None
            else stored
        )
        if (
            type(state) is not TaskRuntimeState
            or state.owner_id != settings.owner_id
            or state.installation_id != settings.installation_id
        ):
            raise AuthorityValidationError("task-state-authority-mismatch")
        return state

    def _ticket115_review_ledger_open(
        self,
        settings: OwnerSettingsState,
    ) -> DailyReviewLedger:
        stored = self._store.daily_review_ledger()
        ledger = (
            DailyReviewLedger.empty(settings.owner_id, settings.installation_id)
            if stored is None
            else stored
        )
        if (
            type(ledger) is not DailyReviewLedger
            or ledger.owner_id != settings.owner_id
            or ledger.installation_id != settings.installation_id
        ):
            raise AuthorityValidationError("daily-review-authority-mismatch")
        return ledger

    def _ticket115_outbox_state_open(
        self,
        settings: OwnerSettingsState,
    ) -> DeliveryOutboxState:
        state = self._store.delivery_outbox_state(
            settings.owner_id,
            settings.installation_id,
        )
        if type(state) is not DeliveryOutboxState:
            raise AuthorityValidationError("owner-delivery-authority-mismatch")
        self._require_delivery_state_evidence_open(state)
        return state

    def _delivery_evidence_issuer_open(
        self,
        producer_contract: str,
    ) -> DeliveryEvidenceIssuer:
        issuer = self._delivery_evidence_issuers.get(producer_contract)
        if type(issuer) is not DeliveryEvidenceIssuer:
            raise AuthorityValidationError("delivery-evidence-issuer-unavailable")
        return issuer

    def _require_delivery_state_evidence_open(
        self,
        state: DeliveryOutboxState,
    ) -> None:
        authority = self._delivery_evidence_authority
        if state.records and type(authority) is not DeliveryEvidenceAuthority:
            raise AuthorityValidationError("delivery-evidence-authority-unavailable")
        if authority is None:
            return
        try:
            for record in state.records:
                for fact in record.facts:
                    authority.require(
                        fact.evidence(),
                        expected_layer=fact.evidence().layer,
                        expected_generation=record.intent.route_generation,
                        expected_effect_id=record.intent.effect_id,
                        expected_replay_identity=fact.replay_identity,
                    )
        except ValueError as exc:
            raise AuthorityValidationError(
                "owner-delivery-evidence-invalid"
            ) from exc

    def execute_trusted_health_command(
        self,
        command: TrustedHealthCommand,
    ) -> dict[str, object]:
        """Authorize and execute one semantic health command."""

        try:
            return self._execute_trusted_health_command(command)
        except _TrustedHealthCommandReplay as replay:
            return replay.result

    def _execute_trusted_health_command(
        self,
        command: TrustedHealthCommand,
    ) -> dict[str, object]:
        """Authorize, execute, and durably receipt one semantic health command."""

        if type(command) is not TrustedHealthCommand:
            raise ProtocolViolation("trusted health command required")
        authority = _TICKET115_HEALTH_COMMAND_AUTHORITY.get(command.action)
        if authority is None or (command.source, command.scope) != authority:
            raise ProtocolViolation("health-command-authority-denied")

        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError(
                    self._closed_reason or "ticket115-entry-unavailable"
                )
            self._recover_ticket115_mutation()
            try:
                with self._store.serialized():
                    self._store.verify_key()
                    prior = self._store.lookup_health_command_receipt(command)
            except CausalIdConflict as exc:
                raise ProtocolViolation("causal-id-conflict") from exc
            if prior is not None:
                return prior.result

            with self._ticket115_write_authority() as (head, _settings):
                if command.generation != head.generation:
                    raise ProtocolViolation("generation mismatch")

            payload = command.payload
            action = command.action
            if action == "task.admit":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset({"candidate", "committed_at_utc"}),
                )
                transition = self.admit_task_candidate(
                    TaskCandidate.from_storage(fields["candidate"]),
                    committed_at_utc=fields["committed_at_utc"],  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_task_transition_wire(transition)
            if action == "task.claim":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset(
                        {"task_id", "holder_id", "lease_id", "acquired_at_utc"}
                    ),
                    frozenset({"lease_seconds"}),
                )
                transition = self.claim_task(
                    fields["task_id"],  # type: ignore[arg-type]
                    holder_id=fields["holder_id"],  # type: ignore[arg-type]
                    lease_id=fields["lease_id"],  # type: ignore[arg-type]
                    acquired_at_utc=fields["acquired_at_utc"],  # type: ignore[arg-type]
                    lease_seconds=fields.get("lease_seconds", 300),  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_task_transition_wire(transition)
            if action == "task.release":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset({"lease_id", "holder_id", "observed_at_utc"}),
                )
                transition = self.release_task_claim(
                    fields["lease_id"],  # type: ignore[arg-type]
                    holder_id=fields["holder_id"],  # type: ignore[arg-type]
                    observed_at_utc=fields["observed_at_utc"],  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_task_transition_wire(transition)
            if action == "task.defer":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset({"task_id", "deferred_at_utc"}),
                    frozenset({"reason_code"}),
                )
                transition = self.defer_task(
                    fields["task_id"],  # type: ignore[arg-type]
                    deferred_at_utc=fields["deferred_at_utc"],  # type: ignore[arg-type]
                    reason_code=fields.get("reason_code", "owner-deferred"),  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_task_transition_wire(transition)
            if action == "task.adjust":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset(
                        {
                            "task_id",
                            "candidate",
                            "adjusted_at_utc",
                            "scope_expanded",
                            "requested_approval",
                        }
                    ),
                )
                approval_wire = fields["requested_approval"]
                transition = self.adjust_task(
                    fields["task_id"],  # type: ignore[arg-type]
                    TaskCandidate.from_storage(fields["candidate"]),
                    adjusted_at_utc=fields["adjusted_at_utc"],  # type: ignore[arg-type]
                    scope_expanded=fields["scope_expanded"],  # type: ignore[arg-type]
                    requested_approval=(
                        None
                        if approval_wire is None
                        else ExecutionScopeApproval.from_wire(approval_wire)
                    ),
                    _health_command=command,
                )
                return _ticket115_task_transition_wire(transition)
            if action == "task.advance":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset(
                        {
                            "task_id",
                            "phase",
                            "advanced_at_utc",
                            "claim_id",
                            "holder_role",
                        }
                    ),
                )
                transition = self.advance_task_phase(
                    fields["task_id"],  # type: ignore[arg-type]
                    phase=fields["phase"],  # type: ignore[arg-type]
                    advanced_at_utc=fields["advanced_at_utc"],  # type: ignore[arg-type]
                    claim_id=fields["claim_id"],  # type: ignore[arg-type]
                    holder_role=fields["holder_role"],  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_task_transition_wire(transition)
            if action == "task.solve":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset({"acceptance", "claim_id", "holder_role"}),
                )
                transition = self.solve_task(
                    TaskAcceptance.from_storage(fields["acceptance"]),
                    claim_id=fields["claim_id"],  # type: ignore[arg-type]
                    holder_role=fields["holder_role"],  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_task_transition_wire(transition)
            if action == "task.cancel":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset({"task_id", "cancelled_at_utc"}),
                )
                transition = self.cancel_task(
                    fields["task_id"],  # type: ignore[arg-type]
                    cancelled_at_utc=fields["cancelled_at_utc"],  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_task_transition_wire(transition)
            if action == "task.fail":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset({"task_id", "failed_at_utc"}),
                    frozenset({"reason_code"}),
                )
                transition = self.fail_task(
                    fields["task_id"],  # type: ignore[arg-type]
                    failed_at_utc=fields["failed_at_utc"],  # type: ignore[arg-type]
                    reason_code=fields.get(
                        "reason_code",
                        "no-reasonable-path",
                    ),  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_task_transition_wire(transition)
            if action == "task.link-successor":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset(
                        {
                            "predecessor_task_id",
                            "successor_candidate",
                            "committed_at_utc",
                        }
                    ),
                )
                transition = self.link_task_successor(
                    fields["predecessor_task_id"],  # type: ignore[arg-type]
                    TaskCandidate.from_storage(fields["successor_candidate"]),
                    committed_at_utc=fields["committed_at_utc"],  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_task_transition_wire(transition)
            if action == "review.prepare":
                _ticket115_wire_fields(payload, frozenset())
                decision = self.prepare_daily_review(_health_command=command)
                return _ticket115_review_decision_wire(decision)
            if action == "review.commit":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset({"decision"}),
                    frozenset({"delivery"}),
                )
                delivery_wire = fields.get("delivery")
                decision = self.commit_daily_review(
                    _ticket115_review_decision_from_wire(
                        fields["decision"],
                        self.daily_review_ledger(),
                    ),
                    delivery=(
                        None
                        if delivery_wire is None
                        else _ticket115_owner_delivery_submission_from_wire(
                            delivery_wire
                        )
                    ),
                    _health_command=command,
                )
                return _ticket115_review_decision_wire(decision)
            if action == "delivery.observe":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset(
                        {
                            "intent_id",
                            "kind",
                            "attempt_ref",
                            "result_ref",
                            "evidence_ref",
                            "evidence",
                            "observed_at_utc",
                        }
                    ),
                )
                transition = self.record_owner_delivery_observation(
                    fields["intent_id"],  # type: ignore[arg-type]
                    kind=fields["kind"],  # type: ignore[arg-type]
                    attempt_ref=fields["attempt_ref"],  # type: ignore[arg-type]
                    result_ref=fields["result_ref"],  # type: ignore[arg-type]
                    evidence_ref=fields["evidence_ref"],  # type: ignore[arg-type]
                    evidence=DeliveryEvidence.from_storage(fields["evidence"]),
                    observed_at_utc=fields["observed_at_utc"],  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_delivery_transition_wire(transition)
            if action == "delivery.observe-owner-action":
                fields = _ticket115_wire_fields(
                    payload,
                    frozenset(
                        {
                            "intent_id",
                            "attempt_ref",
                            "result_ref",
                            "evidence_ref",
                            "evidence",
                            "observed_at_utc",
                        }
                    ),
                )
                transition = self.record_owner_delivery_observation(
                    fields["intent_id"],  # type: ignore[arg-type]
                    kind="actual-action",
                    attempt_ref=fields["attempt_ref"],  # type: ignore[arg-type]
                    result_ref=fields["result_ref"],  # type: ignore[arg-type]
                    evidence_ref=fields["evidence_ref"],  # type: ignore[arg-type]
                    evidence=DeliveryEvidence.from_storage(fields["evidence"]),
                    observed_at_utc=fields["observed_at_utc"],  # type: ignore[arg-type]
                    _health_command=command,
                )
                return _ticket115_delivery_transition_wire(transition)
        raise ProtocolViolation("unsupported Ticket 115 health operation")

    def _recheck_trusted_health_command_open(
        self,
        head: AuthoritySnapshot,
        command: TrustedHealthCommand | None,
        *,
        expected_action: str,
    ) -> None:
        """Recheck replay and generation inside the operation's final write lane."""

        if command is None:
            return
        authority = _TICKET115_HEALTH_COMMAND_AUTHORITY.get(expected_action)
        if (
            command.action != expected_action
            or authority is None
            or (command.source, command.scope) != authority
        ):
            raise ProtocolViolation("health-command-authority-denied")
        try:
            prior = self._store.lookup_health_command_receipt(command)
        except CausalIdConflict as exc:
            raise ProtocolViolation("causal-id-conflict") from exc
        if prior is not None:
            raise _TrustedHealthCommandReplay(prior.result)
        if command.generation != head.generation:
            raise ProtocolViolation("generation mismatch")

    def _mutate_ticket115_task(
        self,
        operation: Callable[[TaskRuntimeState], TaskTransition],
        *,
        operation_with_settings: Callable[
            [TaskRuntimeState, OwnerSettingsState], TaskTransition
        ] | None = None,
        health_command: TrustedHealthCommand,
        health_command_action: str,
    ) -> TaskTransition:
        if type(health_command) is not TrustedHealthCommand:
            raise ProtocolViolation("trusted health command required")
        with self._lifecycle_lock:
            with self._ticket115_write_authority() as (head, settings):
                self._recheck_trusted_health_command_open(
                    head,
                    health_command,
                    expected_action=health_command_action,
                )
                task_state = self._ticket115_task_state_open(settings)
                transition = (
                    operation_with_settings(task_state, settings)
                    if operation_with_settings is not None
                    else operation(task_state)
                )
                if type(transition) is not TaskTransition:
                    raise AuthorityValidationError("invalid task transition")
                receipt = HealthCommandReceipt(
                    causal_id=health_command.causal_id,
                    command_digest=health_command.command_digest,
                    result=_ticket115_task_transition_wire(transition),
                )
                mutation = self._prepare_ticket115_facts_open(
                    head,
                    settings,
                    task_state=transition.state,
                    health_command_receipt=receipt,
                )
            self._complete_ticket115_mutation(mutation)
            return transition

    def task_state(self) -> TaskRuntimeState:
        """Return the current owner task aggregate, including an authoritative empty state."""

        with self._lifecycle_lock:
            with self._ticket115_write_authority() as (_, settings):
                return self._ticket115_task_state_open(settings)

    def admit_task_candidate(
        self,
        candidate: TaskCandidate,
        *,
        committed_at_utc: str,
        _health_command: TrustedHealthCommand,
    ) -> TaskTransition:
        return self._mutate_ticket115_task(
            lambda state: TaskEngine.admit_candidate(
                state,
                candidate,
                committed_at_utc=committed_at_utc,
            ),
            operation_with_settings=lambda state, settings: TaskEngine.admit_candidate(
                state,
                candidate,
                committed_at_utc=committed_at_utc,
                cancelled_task_refs=settings.cancelled_task_refs,
            ),
            health_command=_health_command,
            health_command_action="task.admit",
        )

    def claim_task(
        self,
        task_id: str,
        *,
        holder_id: str,
        lease_id: str,
        acquired_at_utc: str,
        lease_seconds: int = 300,
        _health_command: TrustedHealthCommand,
    ) -> TaskTransition:
        def claim_with_runtime(
            state: TaskRuntimeState,
            settings: OwnerSettingsState,
        ) -> TaskTransition:
            acquired_monotonic = time.monotonic()
            return TaskEngine.claim(
                state,
                task_id,
                holder_id=holder_id,
                lease_id=lease_id,
                acquired_at_utc=acquired_at_utc,
                lease_seconds=lease_seconds,
                runtime_epoch=self._task_runtime_epoch,
                acquired_at_monotonic_seconds=acquired_monotonic,
                expires_at_monotonic_seconds=acquired_monotonic + lease_seconds,
                generation=settings.version,
                task_cas_identity=stable_digest(state.task(task_id).to_storage()),
            )

        return self._mutate_ticket115_task(
            lambda state: (_ for _ in ()).throw(
                AuthorityValidationError("task-claim-settings-required")
            ),
            operation_with_settings=claim_with_runtime,
            health_command=_health_command,
            health_command_action="task.claim",
        )

    def release_task_claim(
        self,
        lease_id: str,
        *,
        holder_id: str,
        observed_at_utc: str,
        _health_command: TrustedHealthCommand,
    ) -> TaskTransition:
        def release_with_runtime(state: TaskRuntimeState) -> TaskTransition:
            return TaskEngine.release_claim(
                state,
                lease_id,
                holder_id=holder_id,
                observed_at_utc=observed_at_utc,
                runtime_epoch=self._task_runtime_epoch,
                monotonic_seconds=time.monotonic(),
            )

        return self._mutate_ticket115_task(
            release_with_runtime,
            health_command=_health_command,
            health_command_action="task.release",
        )

    def defer_task(
        self,
        task_id: str,
        *,
        deferred_at_utc: str,
        reason_code: str = "owner-deferred",
        _health_command: TrustedHealthCommand,
    ) -> TaskTransition:
        return self._mutate_ticket115_task(
            lambda state: TaskEngine.defer(
                state,
                task_id,
                deferred_at_utc=deferred_at_utc,
                reason_code=reason_code,
            ),
            health_command=_health_command,
            health_command_action="task.defer",
        )

    def adjust_task(
        self,
        task_id: str,
        candidate: TaskCandidate,
        *,
        adjusted_at_utc: str,
        scope_expanded: bool,
        requested_approval: ExecutionScopeApproval | None,
        _health_command: TrustedHealthCommand,
    ) -> TaskTransition:
        def adjust_with_current_settings(
            state: TaskRuntimeState,
            settings: OwnerSettingsState,
        ) -> TaskTransition:
            current_approval = (
                None
                if requested_approval is None
                else next(
                    (
                        approval
                        for approval in settings.approvals
                        if approval.approval_id == requested_approval.approval_id
                    ),
                    None,
                )
            )
            return TaskEngine.adjust(
                state,
                task_id,
                candidate,
                adjusted_at_utc=adjusted_at_utc,
                scope_expanded=scope_expanded,
                cancelled_task_refs=settings.cancelled_task_refs,
                requested_approval=requested_approval,
                current_approval=current_approval,
            )

        return self._mutate_ticket115_task(
            lambda state: TaskEngine.adjust(
                state,
                task_id,
                candidate,
                adjusted_at_utc=adjusted_at_utc,
                scope_expanded=scope_expanded,
                requested_approval=requested_approval,
            ),
            operation_with_settings=adjust_with_current_settings,
            health_command=_health_command,
            health_command_action="task.adjust",
        )

    def _consume_task_claim_open(
        self,
        state: TaskRuntimeState,
        task_id: str,
        *,
        claim_id: str,
        holder_role: str,
        generation: int,
    ) -> TaskRuntimeState:
        task = state.task(task_id)
        claim = next(
            (item for item in state.task_claim_leases if item.claim_id == claim_id),
            None,
        )
        legacy = next(
            (item for item in state.active_claims if item.lease_id == claim_id),
            None,
        )
        if (
            claim is None
            or legacy is None
            or claim.task_id != task.task_id
            or legacy.task_id != task.task_id
            or legacy.holder_id != holder_role
            or not claim.can_commit(
                runtime_epoch=self._task_runtime_epoch,
                monotonic_seconds=time.monotonic(),
                generation=generation,
                holder_role=holder_role,
                task_revision=task.version,
                task_cas_identity=stable_digest(task.to_storage()),
            )
        ):
            raise TaskContractViolation("runtime task claim is stale")
        return replace(
            state,
            active_claims=tuple(
                item for item in state.active_claims if item.lease_id != claim_id
            ),
            task_claim_leases=tuple(
                item
                for item in state.task_claim_leases
                if item.claim_id != claim_id
            ),
        )

    def advance_task_phase(
        self,
        task_id: str,
        *,
        phase: str,
        advanced_at_utc: str,
        claim_id: str,
        holder_role: str,
        _health_command: TrustedHealthCommand,
    ) -> TaskTransition:
        return self._mutate_ticket115_task(
            lambda state: (_ for _ in ()).throw(
                AuthorityValidationError("task-claim-settings-required")
            ),
            operation_with_settings=lambda state, settings: TaskEngine.advance_phase(
                self._consume_task_claim_open(
                    state,
                    task_id,
                    claim_id=claim_id,
                    holder_role=holder_role,
                    generation=settings.version,
                ),
                task_id,
                phase=phase,
                advanced_at_utc=advanced_at_utc,
            ),
            health_command=_health_command,
            health_command_action="task.advance",
        )

    def solve_task(
        self,
        acceptance: TaskAcceptance,
        *,
        claim_id: str,
        holder_role: str,
        _health_command: TrustedHealthCommand,
    ) -> TaskTransition:
        def solve_with_current_evidence(
            state: TaskRuntimeState,
            settings: OwnerSettingsState,
        ) -> TaskTransition:
            # Acceptance must bind to the evidence revisions that are current
            # in the same serialized authority lane as the task transition.
            daily_state = self._store.daily_state()
            current_evidence_revisions = {
                card.evidence_id: card.revision_digest
                for card in daily_state.current_evidence_cards
            }
            return TaskEngine.solve(
                self._consume_task_claim_open(
                    state,
                    acceptance.task_id,
                    claim_id=claim_id,
                    holder_role=holder_role,
                    generation=settings.version,
                ),
                acceptance,
                current_evidence_revisions=current_evidence_revisions,
            )

        return self._mutate_ticket115_task(
            lambda state: (_ for _ in ()).throw(
                AuthorityValidationError("task-claim-settings-required")
            ),
            operation_with_settings=solve_with_current_evidence,
            health_command=_health_command,
            health_command_action="task.solve",
        )

    def cancel_task(
        self,
        task_id: str,
        *,
        cancelled_at_utc: str,
        _health_command: TrustedHealthCommand,
    ) -> TaskTransition:
        return self._mutate_ticket115_task(
            lambda state: (_ for _ in ()).throw(
                TaskContractViolation("owner task cancellation is not committed")
            ),
            operation_with_settings=lambda state, settings: (
                TaskEngine.apply_owner_cancellation(
                    state,
                    task_id,
                    control_ref=_health_command.causal_id,
                    effective_at_utc=cancelled_at_utc,
                )
                if task_id in settings.cancelled_task_refs
                else (_ for _ in ()).throw(
                    TaskContractViolation("owner task cancellation is not committed")
                )
            ),
            health_command=_health_command,
            health_command_action="task.cancel",
        )

    def fail_task(
        self,
        task_id: str,
        *,
        failed_at_utc: str,
        reason_code: str = "no-reasonable-path",
        _health_command: TrustedHealthCommand,
    ) -> TaskTransition:
        return self._mutate_ticket115_task(
            lambda state: TaskEngine.fail(
                state,
                task_id,
                failed_at_utc=failed_at_utc,
                reason_code=reason_code,
            ),
            health_command=_health_command,
            health_command_action="task.fail",
        )

    def link_task_successor(
        self,
        predecessor_task_id: str,
        successor_candidate: TaskCandidate,
        *,
        committed_at_utc: str,
        _health_command: TrustedHealthCommand,
    ) -> TaskTransition:
        return self._mutate_ticket115_task(
            lambda state: TaskEngine.link_successor(
                state,
                predecessor_task_id,
                successor_candidate,
                committed_at_utc=committed_at_utc,
            ),
            operation_with_settings=lambda state, settings: TaskEngine.link_successor(
                state,
                predecessor_task_id,
                successor_candidate,
                committed_at_utc=committed_at_utc,
                cancelled_task_refs=settings.cancelled_task_refs,
            ),
            health_command=_health_command,
            health_command_action="task.link-successor",
        )

    def _daily_review_state_digest_open(
        self,
        settings: OwnerSettingsState,
        *,
        task_state: TaskRuntimeState | None = None,
        daily_state: DailyHealthState | None = None,
    ) -> str:
        current_tasks = (
            self._ticket115_task_state_open(settings)
            if task_state is None
            else task_state
        )
        current_daily_state = (
            self._store.daily_state()
            if daily_state is None
            else daily_state
        )
        return stable_digest(
            {
                "task_runtime": current_tasks.to_storage(),
                "daily_health_state_digest": current_daily_state.digest,
            }
        )

    def _daily_review_clock_utc_open(self) -> str:
        try:
            observed = self._owner_settings_clock()
        except Exception as exc:
            raise ReviewContractViolation("review clock unavailable") from exc
        if (
            type(observed) is not datetime
            or observed.tzinfo is None
            or observed.utcoffset() is None
        ):
            raise ReviewContractViolation("review clock must be timezone-aware")
        return observed.astimezone(timezone.utc).isoformat()

    def _owner_delivery_global_controls_allow_open(
        self,
        settings: OwnerSettingsState,
        *,
        observed_at_utc: str,
    ) -> bool:
        return (
            settings.consent_enabled
            and settings.consent_path_status == "active"
            and settings.consent_route_id == settings.current_route_id
            and settings.consent_first_hop_recipient
            == settings.current_first_hop_recipient
            and settings.consent_configuration_generation
            == settings.current_configuration_generation
            and settings.consent_disclosure_version
            == settings.current_disclosure_version
            and settings.proactive_contact
            and not settings.proactive_support_paused
            and dict(settings.ordinary_notifications).get("review_summary")
            == "enabled"
            and self._owner_contact_window_allows(settings, observed_at_utc)
        )

    @staticmethod
    def _owner_delivery_attempt_usage(
        outbox: DeliveryOutboxState,
        effect_request_id: str,
        *,
        excluded_attempt: tuple[str, str] | None = None,
    ) -> tuple[int, str | None]:
        attempted_facts = tuple(
            fact
            for record in outbox.records
            if record.intent.effect_request_id == effect_request_id
            and (fact := record.optional_fact("attempted")) is not None
            and (
                excluded_attempt is None
                or (record.intent.intent_id, fact.attempt_ref)
                != excluded_attempt
            )
        )
        return (
            len(attempted_facts),
            None
            if not attempted_facts
            else max(fact.occurred_at_utc for fact in attempted_facts),
        )

    def _owner_delivery_scope_allows_open(
        self,
        settings: OwnerSettingsState,
        task: ManagedTask,
        approval: ExecutionScopeApproval | None,
        outbox: DeliveryOutboxState,
        *,
        effect_request_id: str,
        recipient_ref: str,
        route_id: str,
        route_generation: int,
        observed_at_utc: str,
        excluded_attempt: tuple[str, str] | None = None,
    ) -> bool:
        approval_binding = task.approval
        if (
            task.primary_label != "active"
            or task.task_id in settings.cancelled_task_refs
            or task.external_boundary.recipient_refs != (recipient_ref,)
            or task.external_boundary.effect_kinds != ("owner-delivery",)
            or approval_binding.status != "bound"
            or approval is None
            or approval.approval_version != approval_binding.approval_version
            or not set(task.allowed_data_categories).issubset(
                settings.consent_data_scope
            )
            or not self._owner_delivery_global_controls_allow_open(
                settings,
                observed_at_utc=observed_at_utc,
            )
        ):
            return False
        attempts_used, last_contact_at_utc = self._owner_delivery_attempt_usage(
            outbox,
            effect_request_id,
            excluded_attempt=excluded_attempt,
        )
        try:
            consumption = ExecutionScopeConsumptionRequest(
                approval_id=approval.approval_id,
                approval_version=approval.approval_version,
                owner_id=settings.owner_id,
                installation_id=settings.installation_id,
                task_id=task.task_id,
                effect_request_id=effect_request_id,
                assignee=task.assignee,
                purpose=task.purpose,
                data_categories=task.allowed_data_categories,
                data_refs=task.allowed_data_refs,
                first_hop_recipient=recipient_ref,
                external_effect_kind="owner-delivery",
                attempts_used=attempts_used,
                last_contact_at_utc=last_contact_at_utc,
                evaluated_at_utc=observed_at_utc,
                route_id=route_id,
                configuration_generation=route_generation,
                disclosure_version=settings.current_disclosure_version,
            )
            return OwnerSettingsEngine.validate_execution_scope_consumption(
                settings,
                consumption,
            ).allowed
        except (SettingsContractViolation, TypeError, ValueError):
            return False

    @staticmethod
    def _task_evidence_bindings_are_current(
        task: ManagedTask,
        daily_state: DailyHealthState,
    ) -> bool:
        current_revisions = {
            card.evidence_id: card.revision_digest
            for card in daily_state.current_evidence_cards
        }
        known_refs = {card.evidence_id for card in daily_state.evidence_cards}
        known_refs.update(
            change.target_evidence_id
            for change in daily_state.evidence_applicability_changes
        )
        known_refs.update(
            change.successor_evidence_id
            for change in daily_state.evidence_applicability_changes
            if change.successor_evidence_id is not None
        )
        return all(
            source_kind != "portrait-evidence"
            or current_revisions.get(source_ref) == source_revision
            for source_kind, source_ref, source_revision in zip(
                task.source_kinds,
                task.source_refs,
                task.source_revision_digests,
            )
        ) and all(
            data_ref not in known_refs or data_ref in current_revisions
            for data_ref in task.allowed_data_refs
        )

    def _daily_review_action_refs_open(
        self,
        settings: OwnerSettingsState,
        task_state: TaskRuntimeState,
        daily_state: DailyHealthState,
        *,
        observed_at_utc: str,
    ) -> tuple[str, ...]:
        try:
            destination = self._owner_weixin_destination_open(settings)
        except AuthorityValidationError:
            return ()
        if not self._owner_delivery_global_controls_allow_open(
            settings,
            observed_at_utc=observed_at_utc,
        ):
            return ()

        approvals = {
            approval.approval_id: approval for approval in settings.approvals
        }
        outbox = self._ticket115_outbox_state_open(settings)
        refs: list[str] = []
        for task in task_state.tasks:
            approval_binding = task.approval
            approval = (
                None
                if approval_binding.approval_id is None
                else approvals.get(approval_binding.approval_id)
            )
            if (
                approval is None
                or not self._task_evidence_bindings_are_current(task, daily_state)
                or any(
                    record.intent.effect_request_id
                    == approval.effect_request_id
                    for record in outbox.records
                )
            ):
                continue
            if self._owner_delivery_scope_allows_open(
                settings,
                task,
                approval,
                outbox,
                effect_request_id=approval.effect_request_id,
                recipient_ref=destination.owner_sender_id,
                route_id=destination.route_id,
                route_generation=settings.current_configuration_generation,
                observed_at_utc=observed_at_utc,
            ):
                refs.append(task.task_id)
        return tuple(sorted(refs))

    def _daily_review_plan_open(
        self,
        settings: OwnerSettingsState,
        ledger: DailyReviewLedger,
        *,
        observed_at_utc: str,
    ) -> tuple[str, bool, tuple[str, ...]]:
        task_state = self._ticket115_task_state_open(settings)
        daily_state = self._store.daily_state()
        state_digest = self._daily_review_state_digest_open(
            settings,
            task_state=task_state,
            daily_state=daily_state,
        )
        previous = (
            None
            if not ledger.completed
            else max(
                ledger.completed,
                key=lambda record: datetime.fromisoformat(
                    record.completed_at_utc
                ),
            )
        )
        return (
            state_digest,
            previous is None or previous.state_digest != state_digest,
            self._daily_review_action_refs_open(
                settings,
                task_state,
                daily_state,
                observed_at_utc=observed_at_utc,
            ),
        )

    def daily_review_ledger(self) -> DailyReviewLedger:
        """Return the current owner-local review ledger."""

        with self._lifecycle_lock:
            with self._ticket115_write_authority() as (_, settings):
                return self._ticket115_review_ledger_open(settings)

    def prepare_daily_review(
        self,
        *,
        _health_command: TrustedHealthCommand | None = None,
    ) -> DailyReviewDecision:
        with self._lifecycle_lock:
            with self._ticket115_write_authority() as (head, settings):
                self._recheck_trusted_health_command_open(
                    head,
                    _health_command,
                    expected_action="review.prepare",
                )
                observed_at_utc = self._daily_review_clock_utc_open()
                ledger = self._ticket115_review_ledger_open(settings)
                state_digest, changed, action_refs = self._daily_review_plan_open(
                    settings,
                    ledger,
                    observed_at_utc=observed_at_utc,
                )
                decision = DailyReviewEngine.prepare(
                    ledger,
                    owner_id=settings.owner_id,
                    installation_id=settings.installation_id,
                    timezone_name=settings.timezone,
                    observed_at_utc=observed_at_utc,
                    current_state_digest=state_digest,
                    action_refs=action_refs,
                    changed=changed,
                )
                receipt = (
                    None
                    if _health_command is None
                    else HealthCommandReceipt(
                        causal_id=_health_command.causal_id,
                        command_digest=_health_command.command_digest,
                        result=_ticket115_review_decision_wire(decision),
                    )
                )
                mutation = self._prepare_ticket115_facts_open(
                    head,
                    settings,
                    review_state=decision.ledger,
                    health_command_receipt=receipt,
                )
            self._complete_ticket115_mutation(mutation)
            return decision

    def commit_daily_review(
        self,
        decision: DailyReviewDecision,
        *,
        delivery: OwnerDeliverySubmission | None = None,
        _health_command: TrustedHealthCommand | None = None,
    ) -> DailyReviewDecision:
        if type(decision) is not DailyReviewDecision:
            raise ReviewContractViolation("invalid review decision")
        result = decision
        with self._lifecycle_lock:
            with self._ticket115_write_authority() as (head, settings):
                self._recheck_trusted_health_command_open(
                    head,
                    _health_command,
                    expected_action="review.commit",
                )
                ledger = self._ticket115_review_ledger_open(settings)
                if decision.outcome == "already-completed":
                    if decision.ledger != ledger or delivery is not None:
                        raise ReviewContractViolation(
                            "completed review replay mismatch"
                        )
                    if _health_command is None:
                        return decision
                    mutation = self._prepare_ticket115_facts_open(
                        head,
                        settings,
                        health_command_receipt=HealthCommandReceipt(
                            causal_id=_health_command.causal_id,
                            command_digest=_health_command.command_digest,
                            result=_ticket115_review_decision_wire(decision),
                        ),
                    )
                else:
                    pending = ledger.pending
                    if (
                        type(pending) is not DailyReviewPending
                        or decision.ledger != ledger
                        or decision.key != pending.key
                    ):
                        raise ReviewContractViolation("stale review decision")
                    completed_at_utc = self._daily_review_clock_utc_open()
                    current_plan = self._daily_review_plan_open(
                        settings,
                        ledger,
                        observed_at_utc=completed_at_utc,
                    )
                    if current_plan != (
                        pending.state_digest,
                        pending.changed,
                        pending.action_refs,
                    ):
                        raise ReviewContractViolation(
                            "review state changed after prepare"
                        )
                    current_key = local_day_key(
                        settings.owner_id,
                        settings.installation_id,
                        settings.timezone,
                        completed_at_utc,
                    )
                    if current_key != pending.key:
                        raise ReviewContractViolation(
                            "review commit crossed its owner-local day"
                        )
                    completed = DailyReviewEngine.commit(
                        decision,
                        completed_at_utc=completed_at_utc,
                    )
                    result = completed
                    receipt = (
                        None
                        if _health_command is None
                        else HealthCommandReceipt(
                            causal_id=_health_command.causal_id,
                            command_digest=_health_command.command_digest,
                            result=_ticket115_review_decision_wire(completed),
                        )
                    )
                    record = completed.record
                    if type(record) is not DailyReviewRecord:
                        raise ReviewContractViolation(
                            "review commit did not produce a record"
                        )
                    if not record.notification_required:
                        if delivery is not None:
                            raise ReviewContractViolation(
                                "quiet review cannot submit owner delivery"
                            )
                        mutation = self._prepare_ticket115_facts_open(
                            head,
                            settings,
                            review_state=completed.ledger,
                            health_command_receipt=receipt,
                        )
                    else:
                        destination = self._owner_weixin_destination_open(settings)
                        if (
                            type(delivery) is not OwnerDeliverySubmission
                            or delivery.notification_kind != "review_summary"
                            or delivery.source_task_id not in record.action_refs
                        ):
                            raise ReviewContractViolation(
                                "notifying review requires its exact delivery submission"
                            )
                        task = self._ticket115_task_state_open(settings).task(
                            delivery.source_task_id
                        )
                        if (
                            task.primary_label != "active"
                            or task.external_boundary.recipient_refs
                            != (destination.owner_sender_id,)
                            or task.external_boundary.effect_kinds
                            != ("owner-delivery",)
                        ):
                            raise ReviewContractViolation(
                                "review delivery task boundary mismatch"
                            )
                        intent = OwnerDeliveryEngine.form_intent(
                            effect_kind="owner-delivery",
                            owner_id=settings.owner_id,
                            installation_id=settings.installation_id,
                            effect_request_id=delivery.effect_request_id,
                            business_fact_ref=record.key.value,
                            business_revision_digest=record.result_digest,
                            source_ref=delivery.source_task_id,
                            recipient_ref=destination.owner_sender_id,
                            route_id=destination.route_id,
                            route_generation=(
                                settings.current_configuration_generation
                            ),
                            payload_ref=delivery.payload_ref,
                            payload_digest=delivery.payload_digest,
                            formed_at_utc=delivery.formed_at_utc,
                        )
                        submitted = OwnerDeliveryEngine.submit(
                            self._ticket115_outbox_state_open(settings),
                            intent,
                            submitted_at_utc=delivery.submitted_at_utc,
                            formed_issuer=self._delivery_evidence_issuer_open(
                                "health-core.delivery.formed"
                            ),
                            committed_issuer=self._delivery_evidence_issuer_open(
                                "health-core.delivery.committed"
                            ),
                        )
                        mutation = self._prepare_ticket115_facts_open(
                            head,
                            settings,
                            review_state=completed.ledger,
                            delivery_state=submitted.state,
                            health_command_receipt=receipt,
                        )
            self._complete_ticket115_mutation(mutation)
            return result

    def owner_delivery_outbox_state(self) -> DeliveryOutboxState:
        """Return the owner outbox through the current authority boundary."""

        with self._lifecycle_lock:
            with self._ticket115_write_authority() as (_, settings):
                return self._ticket115_outbox_state_open(settings)

    def managed_ticket115_read(self) -> dict[str, object]:
        """Project tasks, reviews, and delivery facts from one authority read."""

        self.recover_owner_delivery_attempts()
        with self._lifecycle_lock:
            with self._ticket115_write_authority() as (_, settings):
                tasks = self._ticket115_task_state_open(settings)
                reviews = self._ticket115_review_ledger_open(settings)
                outbox = self._ticket115_outbox_state_open(settings)
                return {
                    "tasks": [task.to_storage() for task in tasks.tasks],
                    "delivery_unknown_refs": list(tasks.delivery_unknown_refs),
                    "completed_reviews": [
                        record.to_storage() for record in reviews.completed
                    ],
                    "pending_review": (
                        None
                        if reviews.pending is None
                        else {
                            "key": reviews.pending.key.to_storage(),
                            "changed": reviews.pending.changed,
                            "action_refs": list(reviews.pending.action_refs),
                            "prepared_at_utc": reviews.pending.prepared_at_utc,
                            "notification_required": (
                                reviews.pending.notification_required
                            ),
                        }
                    ),
                    "owner_deliveries": [
                        {
                            "intent": record.intent.to_wire(),
                            "facts": [fact.to_wire() for fact in record.facts],
                            "current_layer": record.current_layer,
                            "unknown_frozen": record.unknown_frozen,
                        }
                        for record in outbox.records
                    ],
                }

    def _owner_delivery_clock_utc_open(self) -> str | None:
        try:
            observed = self._owner_settings_clock()
        except Exception:
            return None
        if (
            type(observed) is not datetime
            or observed.tzinfo is None
            or observed.utcoffset() is None
        ):
            return None
        return observed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _owner_contact_window_allows(
        settings: OwnerSettingsState,
        observed_at_utc: str,
    ) -> bool:
        try:
            observed = datetime.fromisoformat(observed_at_utc)
            if observed.tzinfo is None or observed.utcoffset() != timedelta(0):
                return False
            try:
                zone = ZoneInfo(settings.timezone)
            except ZoneInfoNotFoundError:
                # Windows test/runtime images may not ship the IANA tzdata
                # package even though the rest of the authority stack accepts
                # the same named zones through python-dateutil.
                from dateutil.tz import gettz  # type: ignore[import-not-found]

                zone = gettz(settings.timezone)
                if zone is None:
                    return False
            local = observed.astimezone(zone)
            start_text, end_text = settings.contact_window.split("-", 1)
            start_hour, start_minute = map(int, start_text.split(":"))
            end_hour, end_minute = map(int, end_text.split(":"))
            minute = local.hour * 60 + local.minute
            start = start_hour * 60 + start_minute
            end = end_hour * 60 + end_minute
            if start == end:
                return True
            return (
                start <= minute < end
                if start < end
                else minute >= start or minute < end
            )
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            return False

    def _owner_weixin_destination_open(
        self,
        settings: OwnerSettingsState,
    ) -> OwnerWeixinDestination:
        policy = self._admission_policy
        if (
            type(policy) is not AdmissionPolicy
            or settings.owner_id != policy.owner_sender_id
        ):
            raise AuthorityValidationError("owner-weixin-destination-unavailable")
        return OwnerWeixinDestination(
            partner_id=policy.partner_id,
            owner_sender_id=policy.owner_sender_id,
            conversation_id=policy.conversation_id,
            channel=policy.channel,
            entrypoint=policy.entrypoint,
        )

    def _owner_delivery_binding_open(
        self,
        intent: OutboxIntent,
        settings: OwnerSettingsState,
    ) -> tuple[
        DeliveryOutboxState,
        OutboxRecord,
        TaskRuntimeState,
        DailyReviewRecord,
    ] | None:
        if (
            type(intent) is not OutboxIntent
            or intent.effect_kind != "owner-delivery"
            or intent.owner_id != settings.owner_id
            or intent.installation_id != settings.installation_id
        ):
            return None
        try:
            outbox = self._ticket115_outbox_state_open(settings)
            outbox_record = outbox.record(intent.intent_id)
            review = self._store.daily_review(intent.business_fact_ref)
            task_state = self._ticket115_task_state_open(settings)
            task = task_state.task(intent.source_ref)
        except (AuthorityValidationError, DeliveryContractViolation, TaskContractViolation):
            return None
        daily_state = self._store.daily_state()
        current_review_state_digest = stable_digest(
            {
                "task_runtime": task_state.to_storage(),
                "daily_health_state_digest": daily_state.digest,
            }
        )
        return (
            (outbox, outbox_record, task_state, review)
            if (
                outbox_record.intent == intent
                and type(review) is DailyReviewRecord
                and review.notification_required
                and review.key.value == intent.business_fact_ref
                and review.result_digest == intent.business_revision_digest
                and intent.source_ref in review.action_refs
                and task.primary_label == "active"
                and task.external_boundary.recipient_refs
                == (intent.recipient_ref,)
                and task.external_boundary.effect_kinds
                == ("owner-delivery",)
                and self._task_evidence_bindings_are_current(task, daily_state)
                and review.state_digest == current_review_state_digest
            )
            else None
        )

    def _owner_delivery_sendable_open(
        self,
        intent: OutboxIntent,
        settings: OwnerSettingsState,
        *,
        observed_at_utc: str,
        required_lease: ExecutionLease | None = None,
        expected_attempt_ref: str | None = None,
    ) -> tuple[
        DeliveryOutboxState,
        OutboxRecord,
        TaskRuntimeState,
        DailyReviewRecord,
    ] | None:
        binding = self._owner_delivery_binding_open(intent, settings)
        if binding is None:
            return None
        outbox, outbox_record, task_state, review = binding
        task = task_state.task(intent.source_ref)
        try:
            current_review_key = local_day_key(
                settings.owner_id,
                settings.installation_id,
                settings.timezone,
                observed_at_utc,
            )
        except ReviewContractViolation:
            return None
        approval_binding = task.approval
        try:
            destination = self._owner_weixin_destination_open(settings)
        except AuthorityValidationError:
            return None
        approval = next(
            (
                item
                for item in settings.approvals
                if item.approval_id == approval_binding.approval_id
            ),
            None,
        )
        if (
            review.key != current_review_key
            or intent.route_id != destination.route_id
            or intent.route_generation != settings.current_configuration_generation
            or intent.recipient_ref != destination.owner_sender_id
            or outbox_record.unknown_frozen
        ):
            return None
        attempted = outbox_record.optional_fact("attempted")
        if expected_attempt_ref is None:
            if attempted is not None:
                return None
        elif (
            attempted is None
            or attempted.attempt_ref != expected_attempt_ref
            or outbox_record.current_layer != "attempted"
        ):
            return None
        if not self._owner_delivery_scope_allows_open(
            settings,
            task,
            approval,
            outbox,
            effect_request_id=intent.effect_request_id,
            recipient_ref=intent.recipient_ref,
            route_id=intent.route_id,
            route_generation=intent.route_generation,
            observed_at_utc=observed_at_utc,
            excluded_attempt=(
                None
                if expected_attempt_ref is None
                else (intent.intent_id, expected_attempt_ref)
            ),
        ):
            return None
        if (
            required_lease is not None
            and required_lease.intent_digest != intent.semantic_digest
        ):
            return None
        return binding

    def issue_owner_delivery_effect(self, intent_id: str) -> Response:
        """Issue the generic effect bound to one exact committed outbox intent."""

        validate_opaque_text(intent_id, "owner delivery intent identifier")
        with self._lifecycle_lock:
            with self._ticket115_write_authority() as (head, settings):
                intent = self._ticket115_outbox_state_open(settings).record(
                    intent_id
                ).intent
                command = CommandEnvelope(
                    peer="plugin",
                    action="effect.request",
                    source="health_tasks",
                    causal_id=intent.effect_request_id,
                    generation=head.generation,
                    scope=("effect:request",),
                    payload=EffectRequestPayload(
                        effect_kind="owner-delivery",
                        request_digest=intent.semantic_digest,
                        business_source_causal_id=intent.intent_id,
                    ),
                )
        return self.handle(command)

    @staticmethod
    def _owner_delivery_attempt_ref(
        intent: OutboxIntent,
    ) -> str:
        digest = stable_digest(
            {
                "contract": "owner-delivery-attempt-v2",
                "intent_id": intent.intent_id,
                "intent_digest": intent.semantic_digest,
            }
        )
        return "owner-delivery-attempt:" + digest.removeprefix("sha256:")

    @staticmethod
    def _owner_delivery_attempt_claim_ref(intent: OutboxIntent, kind: str) -> str:
        digest = stable_digest(
            {
                "contract": "owner-delivery-attempt-claim-v1",
                "intent_id": intent.intent_id,
                "kind": kind,
            }
        ).removeprefix("sha256:")
        return f"owner-delivery-{kind}:" + digest

    def _mark_owner_delivery_attempt_started(
        self,
        intent_id: str,
        phase: str,
    ) -> None:
        self._owner_delivery_attempts_started[intent_id] = (
            phase,
            time.monotonic(),
        )

    def _clear_owner_delivery_attempt_started(
        self,
        intent_id: str,
        *,
        expected_phase: str | None = None,
    ) -> None:
        marker = self._owner_delivery_attempts_started.get(intent_id)
        if marker is not None and (
            expected_phase is None or marker[0] == expected_phase
        ):
            self._owner_delivery_attempts_started.pop(intent_id, None)

    def _owner_delivery_attempt_phase(self, intent_id: str) -> str | None:
        marker = self._owner_delivery_attempts_started.get(intent_id)
        if marker is None:
            return None
        phase, started = marker
        if time.monotonic() - started >= _OWNER_DELIVERY_ATTEMPT_MARKER_TTL_SECONDS:
            self._owner_delivery_attempts_started.pop(intent_id, None)
            return None
        return phase

    def _owner_delivery_attempt_is_active(self, intent_id: str) -> bool:
        return self._owner_delivery_attempt_phase(intent_id) is not None

    def _owner_delivery_send_intent_open(
        self,
        intent: OutboxIntent,
        settings: OwnerSettingsState,
        attempt_ref: str,
    ) -> OwnerDeliverySendIntent:
        destination = self._owner_weixin_destination_open(settings)
        if (
            intent.recipient_ref != destination.owner_sender_id
            or intent.route_id != destination.route_id
            or intent.route_generation != settings.current_configuration_generation
        ):
            raise AuthorityValidationError("owner-delivery-destination-mismatch")
        return OwnerDeliverySendIntent(
            intent_id=intent.intent_id,
            attempt_ref=attempt_ref,
            destination=destination,
            payload_ref=intent.payload_ref,
            payload_digest=intent.payload_digest,
            idempotency_key=intent.idempotency_key,
        )

    @staticmethod
    def _orphan_owner_delivery_completion(
        intent: OutboxIntent,
        attempt_ref: str,
        observed_at_utc: str,
    ) -> OwnerDeliveryCompletion:
        digest = stable_digest(
            {
                "contract": "owner-delivery-orphan-recovery-v1",
                "intent_id": intent.intent_id,
                "attempt_ref": attempt_ref,
            }
        ).removeprefix("sha256:")
        return OwnerDeliveryCompletion(
            intent_id=intent.intent_id,
            attempt_ref=attempt_ref,
            status="unknown",
            result_ref="owner-delivery-result:" + digest,
            evidence_ref="owner-delivery-observation:" + digest,
            observed_at_utc=observed_at_utc,
        )

    def _recover_owner_delivery_execution_grant(
        self,
        execution: ExecutingEffect,
    ) -> EffectExecutionGrant | None:
        try:
            head = self._read_head()
        except CurrentHeadError:
            return None
        if execution.lease.authority.mismatch_reason(head) is not None:
            return None
        writer_proof = self._current_writer_proof(head)
        if writer_proof is None:
            return None
        session = self._execution_capability_session(
            execution.intent.authority,
            writer_proof,
        )
        if session is None:
            return None
        capability = session.recover(
            ExecutionCapabilityBinding.for_execution(execution),
            execution.lease.holder_id,
        )
        if capability is None:
            return None
        return EffectExecutionGrant(execution.lease, capability)

    @staticmethod
    def _pending_owner_delivery_result_command(
        pending: object,
        grant: EffectExecutionGrant,
    ) -> CommandEnvelope:
        required = (
            "effect_id",
            "causal_id",
            "protocol_version",
            "peer",
            "source",
            "generation",
            "scope",
            "intent_digest",
            "lease_id",
            "status",
            "terminal",
            "result_digest",
            "model_report",
        )
        if any(not hasattr(pending, name) for name in required):
            raise AuthorityValidationError("invalid pending owner delivery result")
        return CommandEnvelope(
            peer=pending.peer,
            action="effect.result",
            source=pending.source,
            causal_id=pending.causal_id,
            generation=pending.generation,
            scope=pending.scope,
            payload=EffectResultPayload(
                effect_id=pending.effect_id,
                intent_digest=pending.intent_digest,
                lease_id=pending.lease_id,
                completion_capability=grant.completion_capability,
                status=pending.status,
                terminal=pending.terminal,
                result_digest=pending.result_digest,
                model_report=pending.model_report,
            ),
            protocol_version=pending.protocol_version,
        )

    def _record_orphan_owner_delivery_unknown(
        self,
        completion: OwnerDeliveryCompletion,
    ) -> DeliveryTransition | None:
        """CAS-publish conservative uncertainty after execution is no longer live."""

        transport = OwnerDeliveryTransportResult(
            status=completion.status,
            result_ref=completion.result_ref,
            evidence_ref=completion.evidence_ref,
        )
        with self._ticket115_write_authority() as (head, settings):
            outbox = self._ticket115_outbox_state_open(settings)
            current = outbox.record(completion.intent_id)
            attempted = current.optional_fact("attempted")
            if (
                current.current_layer != "attempted"
                or attempted is None
                or attempted.attempt_ref != completion.attempt_ref
            ):
                return None
            transition = OwnerDeliveryEngine.record_transport_result(
                outbox,
                completion.intent_id,
                attempt_ref=completion.attempt_ref,
                result=transport,
                observed_at_utc=completion.observed_at_utc,
                issuer=self._delivery_evidence_issuer_open(
                    "owner-delivery-adapter.unknown"
                ),
                authority=self._delivery_evidence_authority,  # type: ignore[arg-type]
            )
            task_state = self._ticket115_task_state_open(settings)
            task_transition = (
                None
                if completion.intent_id in task_state.delivery_unknown_refs
                else TaskEngine.mark_delivery_unknown(
                    task_state,
                    current.intent.source_ref,
                    effect_ref=completion.intent_id,
                    observed_at_utc=completion.observed_at_utc,
                )
            )
            mutation = self._prepare_ticket115_facts_open(
                head,
                settings,
                task_state=(
                    None if task_transition is None else task_transition.state
                ),
                delivery_state=transition.state,
            )
        self._complete_ticket115_mutation(mutation)
        return transition

    def _freeze_orphan_owner_delivery_effect_unknown(
        self,
        intent: OutboxIntent,
        *,
        observed_at_utc: str,
    ) -> None:
        """Conservatively close an orphan generic effect without transport access."""

        effect_id = self._effect_id(intent.effect_request_id)
        stored = self._store.effect(effect_id)
        if stored is None or stored.state in {"accepted", "rejected", "unknown"}:
            return
        if stored.state == "executing" and type(stored.payload) is ExecutingEffect:
            execution = stored.payload
        else:
            stored_intent = (
                stored.payload
                if stored.state == "intent" and type(stored.payload) is EffectIntent
                else stored.payload.intent
                if stored.state == "claiming" and type(stored.payload) is ClaimingEffect
                else None
            )
            if type(stored_intent) is not EffectIntent:
                return
            digest = stable_digest(
                {
                    "contract": "ticket115-orphan-effect-lease-v1",
                    "effect_id": stored_intent.effect_id,
                    "intent_digest": stored_intent.intent_digest,
                }
            ).removeprefix("sha256:")
            lease = ExecutionLease(
                lease_id="ticket115-orphan-lease:" + digest,
                effect_id=stored_intent.effect_id,
                intent_digest=stored_intent.intent_digest,
                authority=stored_intent.authority,
                holder_id="ticket115-orphan-recovery-holder",
            )
            execution = ExecutingEffect(
                intent=stored_intent,
                lease=lease,
                vault_claim_ref="ticket115-orphan-claim:" + digest,
            )
        result_digest = stable_digest(
            {
                "contract": "ticket115-orphan-effect-unknown-v1",
                "effect_id": effect_id,
                "intent_digest": execution.intent.intent_digest,
                "observed_at_utc": observed_at_utc,
            }
        )
        terminal = TerminalEffect(
            execution=execution,
            status="unknown",
            result_digest=result_digest,
        )
        current = self._store.effect(effect_id)
        if current == stored:
            self._store.write_effect(effect_id, "unknown", terminal)

    def recover_owner_delivery_attempts(self) -> tuple[DeliveryTransition, ...]:
        """Freeze attempts inherited from an earlier process without sending again."""

        recovered: list[DeliveryTransition] = []
        with self._lifecycle_lock:
            if self._closed:
                return ()
            with self._ticket115_write_authority() as (_, settings):
                orphan_attempts = tuple(
                    (record.intent, attempted)
                    for record in self._ticket115_outbox_state_open(settings).records
                    if record.current_layer == "attempted"
                    and not self._owner_delivery_attempt_is_active(
                        record.intent.intent_id
                    )
                    and (attempted := record.optional_fact("attempted")) is not None
                )

            for intent, attempted in orphan_attempts:
                observed_at_utc = self._owner_delivery_clock_utc_open()
                if observed_at_utc is None:
                    raise AuthorityValidationError("owner-delivery-clock-unavailable")
                completion = self._orphan_owner_delivery_completion(
                    intent,
                    attempted.attempt_ref,
                    observed_at_utc,
                )
                effect_id = self._effect_id(intent.effect_request_id)
                stored = self._store.effect(effect_id)
                if stored is None or stored.state in {
                    "accepted",
                    "rejected",
                    "unknown",
                }:
                    transition = self._record_orphan_owner_delivery_unknown(completion)
                    if transition is not None:
                        recovered.append(transition)
                    continue

                grant: EffectExecutionGrant | None = None
                if stored.state in {"intent", "claiming"}:
                    effect_intent = (
                        stored.payload
                        if type(stored.payload) is EffectIntent
                        else stored.payload.intent
                        if type(stored.payload) is ClaimingEffect
                        else None
                    )
                    if type(effect_intent) is EffectIntent:
                        grant = self._claim_effect_execution_open(effect_intent)
                elif (
                    stored.state == "executing"
                    and type(stored.payload) is ExecutingEffect
                ):
                    grant = self._recover_owner_delivery_execution_grant(
                        stored.payload
                    )
                if grant is None:
                    self._release_orphan_ticket115_execution_leases()
                    self._freeze_orphan_owner_delivery_effect_unknown(
                        intent,
                        observed_at_utc=completion.observed_at_utc,
                    )
                    transition = self._record_orphan_owner_delivery_unknown(
                        completion
                    )
                    if transition is not None:
                        recovered.append(transition)
                    continue

                pending = self._store.pending_effect_result(effect_id)
                if pending is not None:
                    response = self.handle(
                        self._pending_owner_delivery_result_command(pending, grant)
                    )
                    terminal = self._store.effect(effect_id)
                    if (
                        response.status not in {"accepted", "rejected", "unknown"}
                        or terminal is None
                        or terminal.state
                        not in {"accepted", "rejected", "unknown"}
                    ):
                        self._release_orphan_ticket115_execution_leases()
                        self._freeze_orphan_owner_delivery_effect_unknown(
                            intent,
                            observed_at_utc=completion.observed_at_utc,
                        )
                        transition = self._record_orphan_owner_delivery_unknown(
                            completion
                        )
                        if transition is not None:
                            recovered.append(transition)
                        continue
                    transition = self._record_orphan_owner_delivery_unknown(completion)
                    if transition is not None:
                        recovered.append(transition)
                    continue

                self._mark_owner_delivery_attempt_started(
                    intent.intent_id,
                    _OWNER_DELIVERY_ATTEMPT_AUTHORIZED,
                )
                result = self.complete_owner_delivery_attempt(completion, grant)
                recovered.append(result.delivery_transition)
        return tuple(recovered)

    def prepare_owner_delivery_attempt(
        self,
        intent_id: str,
        *,
        attempted_at_utc: str,
        lease_seconds: int = 300,
    ) -> OwnerDeliverySendIntent:
        """CAS-publish the sole send attempt before any execution lease exists."""

        validate_opaque_text(intent_id, "owner delivery intent identifier")
        with self._lifecycle_lock:
            with self._ticket115_write_authority() as (head, settings):
                outbox = self._ticket115_outbox_state_open(settings)
                record = outbox.record(intent_id)
                intent = record.intent
                authorization_time = self._owner_delivery_clock_utc_open()
                if (
                    authorization_time is None
                    or record.optional_fact("attempted") is not None
                    or self._owner_delivery_sendable_open(
                        intent,
                        settings,
                        observed_at_utc=authorization_time,
                    )
                    is None
                ):
                    raise AuthorityValidationError(
                        "owner-delivery-authorization-required"
                    )
                attempt_ref = self._owner_delivery_attempt_ref(intent)
                lease_id = self._owner_delivery_attempt_claim_ref(
                    intent,
                    "lease",
                )
                claimed = OwnerDeliveryEngine.claim(
                    outbox,
                    intent_id,
                    holder_id=self._owner_delivery_attempt_claim_ref(
                        intent,
                        "holder",
                    ),
                    lease_id=lease_id,
                    acquired_at_utc=attempted_at_utc,
                    lease_seconds=lease_seconds,
                )
                attempted = OwnerDeliveryEngine.mark_attempted(
                    claimed.state,
                    intent_id,
                    lease_id=lease_id,
                    attempt_ref=attempt_ref,
                    attempted_at_utc=attempted_at_utc,
                    issuer=self._delivery_evidence_issuer_open(
                        "owner-delivery-adapter.attempted"
                    ),
                )
                attempted_state = replace(
                    attempted.state,
                    version=outbox.version + 1,
                )
                send_intent = self._owner_delivery_send_intent_open(
                    intent,
                    settings,
                    attempt_ref,
                )
                mutation = self._prepare_ticket115_facts_open(
                    head,
                    settings,
                    delivery_state=attempted_state,
                )
            self._complete_ticket115_mutation(mutation)
            # Keep the prepare-to-authorize handoff recoverable, but only for
            # the bounded marker TTL.  A managed read during a normal short
            # handoff must not mistake the durable attempted fact for an
            # abandoned transport.
            self._mark_owner_delivery_attempt_started(
                intent_id,
                _OWNER_DELIVERY_ATTEMPT_PREPARED,
            )
            return send_intent

    def authorize_owner_delivery_attempt(
        self,
        intent_id: str,
        grant: EffectExecutionGrant,
        *,
        attempted_at_utc: str,
    ) -> OwnerDeliverySendIntent:
        try:
            return self._authorize_owner_delivery_attempt_impl(
                intent_id,
                grant,
                attempted_at_utc=attempted_at_utc,
            )
        except Exception:
            self._clear_owner_delivery_attempt_started(
                intent_id,
                expected_phase=_OWNER_DELIVERY_ATTEMPT_PREPARED,
            )
            raise

    def _authorize_owner_delivery_attempt_impl(
        self,
        intent_id: str,
        grant: EffectExecutionGrant,
        *,
        attempted_at_utc: str,
    ) -> OwnerDeliverySendIntent:
        """Return the bounded send intent only for one exact attempted effect."""

        validate_opaque_text(intent_id, "owner delivery intent identifier")
        with self._lifecycle_lock:
            if (
                self._owner_delivery_attempt_phase(intent_id)
                != _OWNER_DELIVERY_ATTEMPT_PREPARED
            ):
                raise AuthorityValidationError(
                    "owner-delivery-authorization-required"
                )
            with self._ticket115_write_authority() as (_, settings):
                outbox = self._ticket115_outbox_state_open(settings)
                record = outbox.record(intent_id)
                intent = record.intent
                attempted = record.optional_fact("attempted")
                authorization_time = self._owner_delivery_clock_utc_open()
                execution = self._validated_effect_execution(
                    grant,
                    intent.semantic_digest,
                    effect_kind="owner-delivery",
                )
                if (
                    attempted is None
                    or attempted.occurred_at_utc != attempted_at_utc
                    or authorization_time is None
                    or execution is None
                    or execution.intent.business_source_causal_id != intent_id
                    or self._owner_delivery_sendable_open(
                        intent,
                        settings,
                        observed_at_utc=authorization_time,
                        required_lease=execution.lease,
                        expected_attempt_ref=attempted.attempt_ref,
                    )
                    is None
                ):
                    raise AuthorityValidationError(
                        "owner-delivery-authorization-required"
                    )
                send_intent = self._owner_delivery_send_intent_open(
                    intent,
                    settings,
                    attempted.attempt_ref,
                )
                self._mark_owner_delivery_attempt_started(
                    intent_id,
                    _OWNER_DELIVERY_ATTEMPT_AUTHORIZED,
                )
                return send_intent

    @staticmethod
    def _owner_delivery_effect_result_command(
        execution: ExecutingEffect,
        grant: EffectExecutionGrant,
        transport: OwnerDeliveryTransportResult,
    ) -> CommandEnvelope:
        result_digest = stable_digest(transport.to_wire())
        return CommandEnvelope(
            peer="plugin",
            action="effect.result",
            source="health_tasks",
            causal_id=(
                "owner-delivery-result:"
                + stable_digest(
                    {
                        "effect_id": execution.intent.effect_id,
                        "lease_id": execution.lease.lease_id,
                        "result_digest": result_digest,
                    }
                ).removeprefix("sha256:")
            ),
            generation=execution.lease.authority.generation,
            scope=("effect:result",),
            payload=EffectResultPayload(
                effect_id=execution.intent.effect_id,
                intent_digest=execution.intent.intent_digest,
                lease_id=execution.lease.lease_id,
                completion_capability=grant.completion_capability,
                status=transport.status,
                terminal=True,
                result_digest=result_digest,
            ),
        )

    def complete_owner_delivery_attempt(
        self,
        completion: OwnerDeliveryCompletion,
        grant: EffectExecutionGrant,
    ) -> OwnerDeliveryExecutionResult:
        return self._complete_owner_delivery_attempt_impl(completion, grant)

    def _complete_owner_delivery_attempt_impl(
        self,
        completion: OwnerDeliveryCompletion,
        grant: EffectExecutionGrant,
    ) -> OwnerDeliveryExecutionResult:
        """Release the generic lease, then CAS-publish the exact terminal fact."""

        if type(completion) is not OwnerDeliveryCompletion:
            raise AuthorityValidationError("invalid owner delivery completion")
        transport = OwnerDeliveryTransportResult(
            status=completion.status,
            result_ref=completion.result_ref,
            evidence_ref=completion.evidence_ref,
        )
        with self._lifecycle_lock:
            if (
                self._owner_delivery_attempt_phase(completion.intent_id)
                != _OWNER_DELIVERY_ATTEMPT_AUTHORIZED
            ):
                raise AuthorityValidationError(
                    "owner-delivery-authorization-required"
                )
            with self._ticket115_write_authority() as (_, settings):
                outbox = self._ticket115_outbox_state_open(settings)
                current = outbox.record(completion.intent_id)
                intent = current.intent
                attempted_fact = current.optional_fact("attempted")
                execution = self._validated_effect_execution(
                    grant,
                    intent.semantic_digest,
                    effect_kind="owner-delivery",
                )
                if (
                    attempted_fact is None
                    or attempted_fact.attempt_ref != completion.attempt_ref
                    or execution is None
                    or execution.intent.business_source_causal_id
                    != completion.intent_id
                ):
                    raise AuthorityValidationError(
                        "owner-delivery-attempt-mismatch"
                    )

            effect_response = self.handle(
                self._owner_delivery_effect_result_command(
                    execution,
                    grant,
                    transport,
                )
            )
            if effect_response.status not in {"accepted", "rejected", "unknown"}:
                raise AuthorityValidationError(
                    effect_response.reason_code
                    or "owner-delivery-effect-result-unavailable"
                )

            with self._ticket115_write_authority() as (head, settings):
                outbox = self._ticket115_outbox_state_open(settings)
                current = outbox.record(completion.intent_id)
                if (
                    current.intent != intent
                    or current.optional_fact("attempted") != attempted_fact
                ):
                    raise AuthorityValidationError(
                        "owner-delivery-attempt-mismatch"
                    )
                delivery_transition = OwnerDeliveryEngine.record_transport_result(
                    outbox,
                    completion.intent_id,
                    attempt_ref=completion.attempt_ref,
                    result=transport,
                    observed_at_utc=completion.observed_at_utc,
                    issuer=self._delivery_evidence_issuer_open(
                        "owner-delivery-adapter.unknown"
                        if transport.status == "unknown"
                        else "owner-delivery-adapter.interface"
                    ),
                    authority=self._delivery_evidence_authority,  # type: ignore[arg-type]
                )
                task_state = self._ticket115_task_state_open(settings)
                task_transition: TaskTransition | None = None
                if transport.status == "unknown":
                    task_transition = TaskEngine.mark_delivery_unknown(
                        task_state,
                        intent.source_ref,
                        effect_ref=intent.intent_id,
                        observed_at_utc=completion.observed_at_utc,
                    )
                mutation = self._prepare_ticket115_facts_open(
                    head,
                    settings,
                    task_state=(
                        None
                        if task_transition is None
                        else task_transition.state
                    ),
                    delivery_state=delivery_transition.state,
                )
            self._complete_ticket115_mutation(mutation)
            self._clear_owner_delivery_attempt_started(completion.intent_id)
            return OwnerDeliveryExecutionResult(
                transport,
                effect_response,
                delivery_transition,
            )

    def record_owner_delivery_observation(
        self,
        intent_id: str,
        *,
        kind: str,
        attempt_ref: str,
        result_ref: str,
        evidence_ref: str,
        evidence: DeliveryEvidence,
        observed_at_utc: str,
        _health_command: TrustedHealthCommand,
    ) -> DeliveryTransition:
        """Append independent channel evidence without rewriting transport facts."""

        validate_opaque_text(intent_id, "owner delivery intent identifier")
        if type(_health_command) is not TrustedHealthCommand:
            raise ProtocolViolation("trusted health command required")
        expected_action = (
            "delivery.observe-owner-action"
            if kind == "actual-action"
            else "delivery.observe"
        )
        if (
            (expected_action == "delivery.observe" and kind not in {"delivered", "read", "unknown"})
            or (
                expected_action == "delivery.observe-owner-action"
                and kind != "actual-action"
            )
        ):
            raise ProtocolViolation("delivery-observation-authority-denied")
        with self._lifecycle_lock:
            with self._ticket115_write_authority() as (head, settings):
                self._recheck_trusted_health_command_open(
                    head,
                    _health_command,
                    expected_action=expected_action,
                )
                outbox = self._ticket115_outbox_state_open(settings)
                intent = outbox.record(intent_id).intent
                transition = OwnerDeliveryEngine.record_observation(
                    outbox,
                    intent_id,
                    kind=kind,
                    attempt_ref=attempt_ref,
                    result_ref=result_ref,
                    evidence_ref=evidence_ref,
                    observed_at_utc=observed_at_utc,
                    evidence=evidence,
                    authority=self._delivery_evidence_authority,  # type: ignore[arg-type]
                )
                task_state = self._ticket115_task_state_open(settings)
                task_transition: TaskTransition | None = None
                unresolved = intent.intent_id in task_state.delivery_unknown_refs
                if kind == "unknown" and not unresolved:
                    task_transition = TaskEngine.mark_delivery_unknown(
                        task_state,
                        intent.source_ref,
                        effect_ref=intent.intent_id,
                        observed_at_utc=observed_at_utc,
                    )
                elif unresolved and kind in {"delivered", "read", "actual-action"}:
                    task_transition = TaskEngine.resolve_delivery_unknown(
                        task_state,
                        intent.intent_id,
                        resolution=(
                            "delivered"
                            if kind in {"delivered", "read", "actual-action"}
                            else "not-delivered"
                        ),
                        resolved_at_utc=observed_at_utc,
                    )
                receipt = HealthCommandReceipt(
                    causal_id=_health_command.causal_id,
                    command_digest=_health_command.command_digest,
                    result=_ticket115_delivery_transition_wire(transition),
                )
                mutation = self._prepare_ticket115_facts_open(
                    head,
                    settings,
                    task_state=(
                        None
                        if task_transition is None
                        else task_transition.state
                    ),
                    delivery_state=transition.state,
                    health_command_receipt=receipt,
                )
            self._complete_ticket115_mutation(mutation)
            return transition

    def _production_status_inputs(
        self,
        *,
        probe: ProbeReport,
        valid_until_utc: str,
    ) -> tuple[tuple[CapabilityRequirement, ...], tuple[object, ...]]:
        """Convert current domain authorities into sealed, body-free facts.

        The complete requirement manifest is always present.  Domains owned by
        Ticket 115 or Ticket 116 deliberately have no envelope yet, so their
        absence remains visible to ``StatusProjector`` as ``cannot-confirm``.
        """

        signer = self._status_fact_authority
        if type(signer) is not CapabilityFactAuthority:
            raise AuthorityValidationError("business-status-authority-unavailable")

        expectations: dict[str, tuple[int, str, str]] = {}
        facts: list[object] = []
        for domain in CORE_STATUS_DOMAINS:
            unavailable_digest = stable_digest(
                {
                    "domain": domain,
                    "producer_id": PRODUCTION_STATUS_PRODUCER_IDS[domain],
                    "producer_contract_version": (
                        PRODUCTION_STATUS_PRODUCER_CONTRACT_VERSIONS[domain]
                    ),
                    "availability": "producer-not-integrated",
                }
            )
            expectations[domain] = (
                1,
                unavailable_digest,
                f"status-fact:{domain}:producer-not-integrated-v1",
            )

        def seal_current(
            domain: str,
            *,
            state: str,
            generation: int,
            revision_digest: str,
            transition_id: str,
            evidence_refs: tuple[str, ...],
        ) -> None:
            expectations[domain] = (
                generation,
                revision_digest,
                transition_id,
            )
            facts.append(
                signer.seal(
                    domain=domain,
                    requiredness="core",
                    state=state,
                    generation=generation,
                    revision_digest=revision_digest,
                    transition_id=transition_id,
                    producer_id=PRODUCTION_STATUS_PRODUCER_IDS[domain],
                    producer_contract_version=(
                        PRODUCTION_STATUS_PRODUCER_CONTRACT_VERSIONS[domain]
                    ),
                    evidence_refs=evidence_refs,
                    valid_until_utc=valid_until_utc,
                )
            )

        authority = self._store.finalized_authority()
        if authority is not None:
            head_revision = stable_digest(
                {
                    "authority": authority.to_storage(),
                    "probe_state": probe.state.value,
                    "probe_reason": probe.reason_code,
                }
            )
            head_transition = (
                f"status-fact:current-head:{authority.generation}:"
                + head_revision.removeprefix("sha256:")
            )
            head_state = (
                "confirmed-ok"
                if probe.state is ProbeState.HEALTHY
                else "confirmed-fault"
                if probe.reason_code == "current-head-terminal"
                else "unknown"
            )
            seal_current(
                "current_head",
                state=head_state,
                generation=authority.generation,
                revision_digest=head_revision,
                transition_id=head_transition,
                evidence_refs=(
                    "current-head-authority:"
                    + stable_digest(authority.to_storage()).removeprefix(
                        "sha256:"
                    ),
                ),
            )

        # A non-healthy current-head proof cannot establish that any other
        # producer snapshot is current.  Preserve those domains as missing
        # rather than turning process or adapter liveness into business facts.
        if probe.state is ProbeState.HEALTHY and authority is not None:
            initialization = self._store.initialization()
            initialization_current = (
                initialization is not None
                and initialization.phase == "enabled"
                and self._initialization_configuration_matches(
                    initialization.draft
                )
            )
            if initialization_current and initialization is not None:
                draft = initialization.draft
                init_evidence = (f"initialization-record:{draft.record_id}",)
                init_generation = max(1, draft.prepared_authority.generation)
                seal_current(
                    "entry",
                    state="confirmed-ok",
                    generation=init_generation,
                    revision_digest=draft.revision_digest,
                    transition_id=draft.transition_id,
                    evidence_refs=init_evidence,
                )
                seal_current(
                    "enablement",
                    state="confirmed-ok",
                    generation=init_generation,
                    revision_digest=draft.revision_digest,
                    transition_id=draft.transition_id,
                    evidence_refs=init_evidence,
                )

                key_revision = stable_digest({"key_id": self._store.key_id})
                seal_current(
                    "keys_state",
                    state="confirmed-ok",
                    generation=1,
                    revision_digest=key_revision,
                    transition_id=(
                        "status-fact:keys-state:"
                        + key_revision.removeprefix("sha256:")
                    ),
                    evidence_refs=(
                        "key-boundary:"
                        + key_revision.removeprefix("sha256:"),
                    ),
                )

                daily_state = self._store.daily_state()
                daily_generation = max(
                    1,
                    len(daily_state.processed_source_causal_ids),
                )
                seal_current(
                    "portrait_evidence",
                    state="confirmed-ok",
                    generation=daily_generation,
                    revision_digest=daily_state.digest,
                    transition_id=(
                        f"status-fact:portrait-evidence:{daily_generation}:"
                        + daily_state.digest.removeprefix("sha256:")
                    ),
                    evidence_refs=(
                        "daily-health-state:"
                        + daily_state.digest.removeprefix("sha256:"),
                    ),
                )

                settings = self._current_owner_settings(authority)
                settings_revision = stable_digest(settings.to_wire())
                seal_current(
                    "controls",
                    state="confirmed-ok",
                    generation=settings.version,
                    revision_digest=settings_revision,
                    transition_id=(
                        f"status-fact:controls:{settings.version}:"
                        + settings_revision.removeprefix("sha256:")
                    ),
                    evidence_refs=(
                        "owner-settings:"
                        + settings_revision.removeprefix("sha256:"),
                    ),
                )

                task_state = self._ticket115_task_state_open(settings)
                task_revision = stable_digest(task_state.to_storage())
                task_generation = max(1, task_state.version)
                seal_current(
                    "tasks",
                    state=(
                        "unknown"
                        if task_state.delivery_unknown_refs
                        else "confirmed-ok"
                    ),
                    generation=task_generation,
                    revision_digest=task_revision,
                    transition_id=(
                        f"status-fact:tasks:{task_generation}:"
                        + task_revision.removeprefix("sha256:")
                    ),
                    evidence_refs=(
                        "task-runtime:"
                        + task_revision.removeprefix("sha256:"),
                    ),
                )

                review_ledger = self._ticket115_review_ledger_open(settings)
                review_revision = stable_digest(
                    review_ledger.to_storage()
                )
                review_generation = max(1, review_ledger.version)
                seal_current(
                    "daily_review",
                    state="confirmed-ok",
                    generation=review_generation,
                    revision_digest=review_revision,
                    transition_id=(
                        f"status-fact:daily-review:{review_generation}:"
                        + review_revision.removeprefix("sha256:")
                    ),
                    evidence_refs=(
                        "daily-review-ledger:"
                        + review_revision.removeprefix("sha256:"),
                    ),
                )

                delivery_state = self._ticket115_outbox_state_open(settings)
                delivery_revision = stable_digest(delivery_state.to_wire())
                delivery_generation = max(1, delivery_state.version)
                seal_current(
                    "delivery",
                    state=(
                        "unknown"
                        if any(
                            record.current_layer in {"attempted", "unknown"}
                            for record in delivery_state.records
                        )
                        else "confirmed-ok"
                    ),
                    generation=delivery_generation,
                    revision_digest=delivery_revision,
                    transition_id=(
                        f"status-fact:delivery:{delivery_generation}:"
                        + delivery_revision.removeprefix("sha256:")
                    ),
                    evidence_refs=(
                        "owner-delivery-outbox:"
                        + delivery_revision.removeprefix("sha256:"),
                    ),
                )

                if self._model_authority_digest is not None:
                    route_state = (
                        "confirmed-ok"
                        if settings.consent_path_status == "active"
                        else "confirmed-fault"
                    )
                    route_revision = stable_digest(
                        {
                            "model_authority_digest": (
                                self._model_authority_digest
                            ),
                            "route_id": settings.current_route_id,
                            "configuration_generation": (
                                settings.current_configuration_generation
                            ),
                            "disclosure_version": (
                                settings.current_disclosure_version
                            ),
                            "path_status": settings.consent_path_status,
                        }
                    )
                    seal_current(
                        "model_route",
                        state=route_state,
                        generation=(
                            settings.current_configuration_generation
                        ),
                        revision_digest=route_revision,
                        transition_id=(
                            "status-fact:model-route:"
                            + route_revision.removeprefix("sha256:")
                        ),
                        evidence_refs=(
                            "model-route-authority:"
                            + route_revision.removeprefix("sha256:"),
                        ),
                    )

        requirements = tuple(
            CapabilityRequirement(
                domain=domain,
                requiredness="core",
                producer_id=PRODUCTION_STATUS_PRODUCER_IDS[domain],
                producer_contract_version=(
                    PRODUCTION_STATUS_PRODUCER_CONTRACT_VERSIONS[domain]
                ),
                expected_generation=expectations[domain][0],
                expected_revision_digest=expectations[domain][1],
                expected_transition_id=expectations[domain][2],
            )
            for domain in CORE_STATUS_DOMAINS
        )
        return requirements, tuple(facts)

    def business_status(self) -> BusinessStatusResult:
        """Return the business tri-state and one durable state-change fact."""

        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError("business-status-unavailable")
            try:
                evaluated_at = self._business_status_clock()
                if (
                    type(evaluated_at) is not datetime
                    or evaluated_at.tzinfo is None
                    or evaluated_at.utcoffset() != timedelta(0)
                ):
                    raise AuthorityValidationError(
                        "invalid business status clock result"
                    )
                evaluated_at_utc = evaluated_at.isoformat()
                valid_until_utc = (
                    evaluated_at + timedelta(minutes=5)
                ).isoformat()
                probe = self._probe_open()
                requirements, facts = self._production_status_inputs(
                    probe=probe,
                    valid_until_utc=valid_until_utc,
                )
                projector = StatusProjector(
                    authority=self._status_fact_authority,  # type: ignore[arg-type]
                    requirements=requirements,
                )
                projection = projector.project(
                    facts,
                    evaluated_at_utc=evaluated_at_utc,
                )
                _, transition, mandatory_request = (
                    self._store.remember_business_status_transition(
                        projection,
                        generation=max(
                            requirement.expected_generation
                            for requirement in requirements
                        ),
                    )
                )
                return BusinessStatusResult(
                    projection,
                    transition,
                    mandatory_request,
                )
            except (
                KeyUnavailable,
                StoreUnavailable,
                SettingsContractViolation,
                StatusContractViolation,
            ) as exc:
                raise AuthorityValidationError(
                    "business-status-unavailable"
                ) from exc

    def _managed_rights_projection(self) -> ManagedRightsProjection:
        """Form the private core projection; never expose its raw objects."""

        with self._lifecycle_lock:
            if self._closed:
                raise AuthorityValidationError("managed-rights-unavailable")
            try:
                state = self.daily_state()
                authority = self._store.finalized_authority()
                policy = self._admission_policy
                if authority is None or type(policy) is not AdmissionPolicy:
                    raise AuthorityValidationError("managed-rights-unavailable")
                return self._managed_rights_projection_from_state(
                    state,
                    owner_id=policy.owner_sender_id,
                    installation_id=authority.installation_id,
                )
            except (KeyUnavailable, StoreUnavailable, RightsContractViolation) as exc:
                raise AuthorityValidationError("managed-rights-unavailable") from exc

    def managed_rights_read_current(self) -> tuple[ManagedObject, ...]:
        """Return current objects through the core-owned owner/read authority."""

        projection = self._managed_rights_projection()
        requested = tuple(
            ManagedObjectReference(
                object_ref=item.object_ref,
                installation_id=item.installation_id,
                version=item.version,
            )
            for item in projection.objects
            if item.current
            and item.object_ref in projection.permitted_object_refs
            and item.object_ref not in projection.revoked_object_refs
        )
        if not requested:
            return ()
        return ManagedRightsService.managed_read(
            projection,
            requester_owner_id=projection.owner_id,
            permission="health_data.read",
            requested_refs=requested,
        )

    def managed_correction_draft(
        self,
        *,
        target_ref: ManagedObjectReference,
        correction_id: str,
        reason: str,
        corrected_at_utc: str,
        replacement_claim: AtomicEvidenceClaim,
        correction_source_refs: tuple[str, ...],
        affected_object_refs: tuple[str, ...],
        disposition_requests: tuple[str, ...],
    ) -> PendingCorrectionDraft:
        """Create a pending draft only from the private current projection."""

        projection = self._managed_rights_projection()
        pending = ManagedRightsService.correct(
            projection,
            requester_owner_id=projection.owner_id,
            permission="health_data.correct",
            target_ref=target_ref,
            correction_id=correction_id,
            reason=reason,
            corrected_at_utc=corrected_at_utc,
            replacement_claim=replacement_claim,
            correction_source_refs=correction_source_refs,
            affected_object_refs=affected_object_refs,
            disposition_requests=disposition_requests,
        )
        source_refs = pending.revision.source_refs
        if (
            len(source_refs) == 1
            and source_refs[0].startswith("source:")
            and len(source_refs[0]) > len("source:")
        ):
            source_causal_id = source_refs[0].removeprefix("source:")
            with self._lifecycle_lock:
                if not self._closed:
                    self._pending_correction_authorizations[
                        source_causal_id
                    ] = (
                        pending.base_state_digest,
                        stable_digest(
                            pending.maintenance_request.to_storage()
                        ),
                    )
        return pending

    def managed_rights_export(
        self,
        *,
        requested_refs: tuple[ManagedObjectReference, ...],
        snapshot_id: str,
        created_at_utc: str,
    ) -> ManagedExport:
        """Create one read-only export through the owner-bound core seam."""

        projection = self._managed_rights_projection()
        return ManagedRightsService.export(
            projection,
            requester_owner_id=projection.owner_id,
            permission="health_data.export",
            requested_refs=requested_refs,
            snapshot_id=snapshot_id,
            created_at_utc=created_at_utc,
        )

    @staticmethod
    def _managed_rights_projection_from_state(
        state: DailyHealthState,
        *,
        owner_id: str,
        installation_id: str,
    ) -> ManagedRightsProjection:
        permitted = tuple(
            card.evidence_id for card in state.evidence_cards
        ) + tuple(
            f"portrait-topic:{topic.topic_ref}"
            for topic in state.portrait_topics
        )
        return ManagedRightsService._project_from_daily_state(
            state,
            owner_id=owner_id,
            installation_id=installation_id,
            permitted_object_refs=permitted,
            revoked_object_refs=(),
        )

    def owner_mutation_status(
        self,
        command_id: str,
    ) -> OwnerMutationStatus | None:
        """Return body-free recovery state for one owner mutation command."""

        validate_opaque_text(command_id, "owner mutation command identifier")
        with self._lifecycle_lock:
            if self._closed:
                return None
            try:
                self._store.verify_key()
                authority = self._store.finalized_authority()
                if authority is None or not self._store.verify_integrity(authority):
                    return None
                stored = self._store.owner_mutation(command_id)
                if stored is None:
                    return None
                record = self._store.record(stored.record_id)
                if record is None:
                    raise KeyUnavailable("owner mutation transition missing")
                phase_by_record = {
                    "prepared": "prepared",
                    "unknown": "unknown",
                    "committed": "committed",
                    "final": "finalized",
                }
                phase = phase_by_record.get(record.state)
                if phase is None:
                    raise KeyUnavailable("invalid owner mutation transition")
                if (
                    (stored.phase == "prepared" and phase == "finalized")
                    or (stored.phase == "finalized" and phase != "finalized")
                ):
                    raise KeyUnavailable("owner mutation phase mismatch")
                payload = record.payload
                if isinstance(payload, PreparedTransition):
                    prepared_authority = payload
                    committed_authority = None
                elif isinstance(payload, CommittedTransition):
                    prepared_authority = payload.prepared
                    committed_authority = payload.committed
                else:
                    raise KeyUnavailable("owner mutation authority missing")
                if not prepared_authority.target.matches_commit(
                    record_id=stored.record_id,
                    revision_digest=record.revision_digest,
                    transition_id=record.transition_id,
                ):
                    raise KeyUnavailable("owner mutation transition mismatch")
                if type(stored.prepared) is OwnerPreparedCorrectionRecovery:
                    binding = (
                        stored.prepared.owner_authority_binding_digest
                    )
                    settings_version = stored.prepared.next_settings.version
                    settings_result = stored.prepared.settings_result
                elif type(stored.prepared) is OwnerPreparedMutation:
                    binding = (
                        stored.prepared.request.owner_authority_binding_digest
                    )
                    settings_version = stored.prepared.next_settings.version
                    settings_result = stored.prepared.settings_result
                elif stored.terminal is not None:
                    binding = stored.terminal.owner_authority_binding_digest
                    settings_version = stored.terminal.settings_version
                    settings_result = stored.terminal.settings_result
                else:  # pragma: no cover - StoredOwnerMutation invariant
                    raise KeyUnavailable("owner mutation identity missing")
                return OwnerMutationStatus(
                    command_id=stored.command_id,
                    phase=phase,
                    record_id=stored.record_id,
                    revision_digest=record.revision_digest,
                    transition_id=record.transition_id,
                    prepared_authority=prepared_authority.base,
                    owner_authority_binding_digest=binding,
                    settings_version=settings_version,
                    settings_result=settings_result,
                    committed_authority=committed_authority,
                )
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

    def _recording_excluded_correction_authorization_matches(
        self,
        draft: DailyTurnDraft,
    ) -> bool:
        requests = draft.steward_plan.evidence_maintenance_requests
        if len(requests) != 1 or requests[0].action != "correct":
            return False
        return self._pending_correction_authorizations.get(
            draft.source_causal_id
        ) == (
            draft.base_state_digest,
            stable_digest(requests[0].to_storage()),
        )

    def _recording_excluded_candidate_safe(
        self,
        draft: DailyTurnDraft,
    ) -> bool:
        if not draft.recording_excluded_persistence_safe():
            return False
        if not draft.steward_plan.evidence_maintenance_requests:
            return True
        return self._recording_excluded_correction_authorization_matches(
            draft
        )

    def discard_recording_plaintext(self, source_causal_id: str) -> None:
        """Unconditionally release one stopped source and its transient grant."""

        validate_opaque_text(source_causal_id, "source causal identifier")
        with self._lifecycle_lock:
            self._recording_excluded_sources.pop(source_causal_id, None)
            self._pending_correction_authorizations.pop(
                source_causal_id,
                None,
            )

    def recording_excluded_owner_correction_handoff_required(
        self,
        source_causal_id: str,
        stage: DailyTurnDraft,
    ) -> bool:
        """Keep an exact stopped correction transient for owner prepare.

        A correction completion cannot use the ordinary daily writer.  Once
        the managed draft and exact redelivery restore the transient grant,
        Plugin must hand the body to the existing owner prepare path instead
        of attempting a second durable daily prepare.
        """

        validate_opaque_text(source_causal_id, "source causal identifier")
        with self._lifecycle_lock:
            if (
                self._closed
                or type(stage) is not DailyTurnDraft
                or stage.turn_kind != "evidence-stage"
                or stage.source_causal_id != source_causal_id
            ):
                return False
            try:
                daily = self._store.daily_turn(source_causal_id)
                source_binding = self._daily_source_binding(
                    source_causal_id
                )
            except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
                return False
            return (
                daily is not None
                and daily.phase == "evidence-finalized"
                and daily.draft == stage
                and source_binding is not None
                and source_binding[2]
                and stage.recording_excluded_persistence_safe()
                and self._recording_excluded_correction_authorization_matches(
                    stage
                )
            )

    def release_recording_plaintext_if_unowned(
        self,
        source_causal_id: str,
    ) -> None:
        """Drop transient stopped-recording text unless an unresolved turn owns retry."""

        validate_opaque_text(source_causal_id, "source causal identifier")
        with self._lifecycle_lock:
            if source_causal_id not in self._recording_excluded_sources:
                return
            try:
                durable_turn = self._store.daily_turn(source_causal_id)
                owner_mutation = (
                    None
                    if durable_turn is None
                    else self._store.owner_mutation_for_record(
                        durable_turn.record_id
                    )
                )
            except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
                self._recording_excluded_sources.pop(source_causal_id, None)
                self._pending_correction_authorizations.pop(
                    source_causal_id,
                    None,
                )
                return
            correction_stage_owns_retry = (
                durable_turn is not None
                and durable_turn.phase == "evidence-finalized"
                and type(durable_turn.draft) is DailyTurnDraft
                and self._recording_excluded_correction_authorization_matches(
                    durable_turn.draft
                )
            )
            owner_prepared = (
                None
                if owner_mutation is None
                else owner_mutation.prepared
            )
            owner_correction_owns_retry = (
                durable_turn is not None
                and durable_turn.phase in {"prepared", "unknown", "committed"}
                and type(durable_turn.draft) is DailyTurnDraft
                and (
                    (
                        type(owner_prepared)
                        is OwnerPreparedCorrectionRecovery
                        and owner_prepared.matches_daily(
                            durable_turn.draft
                        )
                    )
                    or (
                        type(owner_prepared) is OwnerPreparedMutation
                        and owner_prepared.request.daily_turn_draft
                        == durable_turn.draft
                    )
                )
            )
            if not (
                correction_stage_owns_retry
                or owner_correction_owns_retry
            ):
                self._recording_excluded_sources.pop(source_causal_id, None)
                self._pending_correction_authorizations.pop(
                    source_causal_id,
                    None,
                )

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

    def model_effect_report(self, effect_id: str) -> ModelEffectReport | None:
        """Return only the content-free report for one terminal model effect."""

        validate_opaque_text(effect_id, "effect identifier")
        with self._lifecycle_lock:
            if self._closed:
                return None
            try:
                self._store.verify_key()
                authority = self._store.finalized_authority()
                if authority is None or not self._store.verify_integrity(authority):
                    return None
                stored = self._store.effect(effect_id)
                if (
                    stored is None
                    or stored.state not in {"accepted", "rejected", "unknown"}
                    or type(stored.payload) is not TerminalEffect
                    or stored.payload.intent.effect_kind != "model-work"
                    or type(stored.payload.model_report) is not ModelEffectReport
                ):
                    return None
                return stored.payload.model_report
            except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
                return None

    def model_answer_recovery_status(self, source_causal_id: str) -> str:
        """Expose the durable no-retry decision after an answer-window crash."""

        validate_opaque_text(source_causal_id, "source causal identifier")
        with self._lifecycle_lock:
            if self._closed:
                return "unavailable"
            try:
                self._store.verify_key()
                daily = self._store.daily_turn(source_causal_id)
                effect = self._store.model_effect_for_source(source_causal_id)
                if effect is None:
                    return "not-started"
                if daily is not None and daily.phase != "evidence-finalized":
                    return "answer-bound"
                if (
                    effect.state == "accepted"
                    and type(effect.payload) is TerminalEffect
                    and self._model_report_has_accepted_candidate(
                        effect.payload.model_report
                    )
                ):
                    return "unknown-owner-decision-required"
                if effect.state in {"intent", "claiming", "executing", "unknown"}:
                    return "unknown"
                return "failed-closed-pending"
            except (AuthorityValidationError, KeyUnavailable, StoreUnavailable):
                return "unavailable"

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
        owner_mutation = (
            self._store.owner_mutation_for_record(record_id)
            if record_kind == "owner"
            else None
        )
        if owner_mutation is not None:
            if owner_mutation.phase == "finalized":
                return "owner" if owner_mutation.terminal is not None else None
            prepared_owner = owner_mutation.prepared
            policy = self._admission_policy
            record = self._store.record(record_id)
            record_authority = (
                None
                if record is None
                else record.payload
                if isinstance(record.payload, PreparedTransition)
                else record.payload.prepared
                if isinstance(record.payload, CommittedTransition)
                else None
            )
            if type(prepared_owner) is OwnerPreparedCorrectionRecovery:
                prepared_owner_id = prepared_owner.owner_id
                prepared_installation_id = prepared_owner.installation_id
                prepared_generation = prepared_owner.current_head_generation
                prepared_fence = prepared_owner.writer_fence
                expected_settings_version = (
                    prepared_owner.expected_settings_version
                )
                daily = self._store.daily_turn_for_record(record_id)
                daily_draft = None if daily is None else daily.draft
                if (
                    daily_draft is None
                    or not prepared_owner.matches_daily(daily_draft)
                ):
                    return None
            elif type(prepared_owner) is OwnerPreparedMutation:
                prepared_owner_id = prepared_owner.request.context.owner_id
                prepared_installation_id = (
                    prepared_owner.request.context.installation_id
                )
                prepared_generation = (
                    prepared_owner.request.context.current_head_generation
                )
                prepared_fence = (
                    prepared_owner.request.context.writer_fence
                )
                expected_settings_version = (
                    prepared_owner.request.expected_settings_version
                )
                daily_draft = prepared_owner.request.daily_turn_draft
                daily = (
                    None
                    if daily_draft is None
                    else self._store.daily_turn_for_record(record_id)
                )
            else:
                return None
            if (
                type(policy) is not AdmissionPolicy
                or initialization is None
                or initialization.phase != "enabled"
                or not self._initialization_configuration_matches(
                    initialization.draft
                )
                or type(record_authority) is not PreparedTransition
                or not record_authority.target.matches_commit(
                    record_id=prepared_owner.record_id,
                    revision_digest=prepared_owner.revision_digest,
                    transition_id=prepared_owner.transition_id,
                )
                or prepared_owner_id != policy.owner_sender_id
                or prepared_installation_id
                != record_authority.base.installation_id
                or prepared_generation
                != record_authority.base.generation
                or prepared_fence
                != record_authority.base.writer_fence
            ):
                return None
            try:
                current_settings = self._current_owner_settings(
                    record_authority.base
                )
            except (AuthorityValidationError, SettingsContractViolation):
                return None
            if (
                current_settings.version
                != expected_settings_version
            ):
                return None
            if daily_draft is not None:
                verifier = self._daily_skill_verifier
                bundle = self._daily_skill_bundle
                if (
                    daily is None
                    or daily.draft != daily_draft
                    or type(verifier) is not DailySkillAttestor
                    or type(bundle) is not DailySkillBundle
                ):
                    return None
                if type(prepared_owner) is OwnerPreparedCorrectionRecovery:
                    if not self._daily_draft_recovery_is_authorized(
                        daily_draft,
                        bundle,
                        verifier,
                    ):
                        return None
                else:
                    source_binding = self._daily_source_binding(
                        daily_draft.source_causal_id
                    )
                    if (
                        source_binding is None
                        or not self._daily_draft_is_authorized(
                            daily_draft,
                            source_binding[0],
                            bundle,
                            verifier,
                        )
                    ):
                        return None
            return "owner"
        ticket115_mutation = (
            self._store.ticket115_mutation_for_record(record_id)
            if record_kind == "ticket115"
            else None
        )
        if ticket115_mutation is not None:
            record = self._store.record(record_id)
            record_authority = (
                None
                if record is None
                else record.payload
                if type(record.payload) is PreparedTransition
                else record.payload.prepared
                if type(record.payload) is CommittedTransition
                else None
            )
            if (
                initialization is None
                or initialization.phase != "enabled"
                or not self._initialization_configuration_matches(
                    initialization.draft
                )
                or type(record_authority) is not PreparedTransition
                or record_authority != ticket115_mutation.prepared
                or not self._store.ticket115_mutation_base_is_current(
                    ticket115_mutation
                )
            ):
                return None
            try:
                settings = self._current_owner_settings(
                    record_authority.base
                )
            except (AuthorityValidationError, SettingsContractViolation):
                return None
            if (
                ticket115_mutation.owner_id != settings.owner_id
                or ticket115_mutation.installation_id
                != settings.installation_id
            ):
                return None
            return "ticket115"
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
        source_binding = self._daily_source_binding(
            daily.draft.source_causal_id
        )
        if source_binding is None:
            return None
        return (
            "daily" if self._daily_draft_is_authorized(
                daily.draft,
                source_binding[0],
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

    def _daily_draft_recovery_is_authorized(
        self,
        draft: DailyTurnDraft,
        bundle: DailySkillBundle,
        verifier: DailySkillAttestor,
    ) -> bool:
        """Revalidate a manifest-bound owner correction without source text."""

        stage = draft.evidence_stage
        if (
            draft.turn_kind != "complete-turn"
            or type(stage) is not DailyTurnDraft
            or stage.turn_kind != "evidence-stage"
            or stage.source_causal_id != draft.source_causal_id
            or stage.source_digest != draft.source_digest
        ):
            return False
        state = self._store.daily_state()
        if stage.base_state_digest != state.digest:
            return False
        try:
            post_stage_state = state.apply_evidence_stage(stage)
        except AuthorityValidationError:
            return False
        if draft.base_state_digest != post_stage_state.digest:
            return False
        try:
            for candidate in (stage, draft):
                names = tuple(
                    proof.skill_use.canonical_name
                    for proof in candidate.skill_proofs
                )
                used_names = tuple(dict.fromkeys(names))
                if (
                    tuple(
                        disclosure.canonical_name
                        for disclosure in candidate.skill_disclosures
                    )
                    != used_names
                    or any(
                        not disclosure.matches(
                            bundle.asset(disclosure.canonical_name)
                        )
                        for disclosure in candidate.skill_disclosures
                    )
                ):
                    return False
                parent: str | None = None
                for index, proof in enumerate(candidate.skill_proofs):
                    fact = proof.skill_use
                    if (
                        fact.source_causal_id != draft.source_causal_id
                        or fact.purpose != candidate.purpose
                        or fact.sequence_index != index
                        or fact.parent_proof_digest != parent
                        or not verifier.verify(
                            proof,
                            bundle.asset(fact.canonical_name),
                        )
                    ):
                        return False
                    parent = proof.digest
        except AuthorityValidationError:
            return False
        return True

    def _business_transition_record_kind(self, record_id: str) -> str | None:
        """Identify the purpose-specific owner without accepting config drift."""

        initialization = self._store.initialization()
        if (
            initialization is not None
            and initialization.draft.record_id == record_id
        ):
            return "initialization"
        if self._store.owner_mutation_for_record(record_id) is not None:
            return "owner"
        if self._store.ticket115_mutation_for_record(record_id) is not None:
            return "ticket115"
        return (
            "daily"
            if self._store.daily_turn_for_record(record_id) is not None
            else None
        )

    def model_effects_allowed(self) -> bool:
        return self._execution_capability_vault is not None and self.health_writes_allowed()

    def outbound_effects_allowed(self) -> bool:
        with self._lifecycle_lock:
            if (
                self._execution_capability_vault is None
                or not self.health_writes_allowed()
            ):
                return False
            if self._admission_policy is None:
                return True
            try:
                authority = self._store.finalized_authority()
                if authority is None:
                    return False
                settings = self._current_owner_settings(authority)
                return (
                    settings.consent_enabled
                    and settings.consent_path_status == "active"
                )
            except (
                AuthorityValidationError,
                KeyUnavailable,
                SettingsContractViolation,
                StoreUnavailable,
            ):
                return False

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

"""Typed authority and durable transition values for the Ticket 110 core."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

from .answer_resolution import ModelEffectReport


class AuthorityValidationError(ValueError):
    """Raised when encrypted authority or transition state is malformed."""


_AUTHORITY_FIELDS = frozenset(
    {
        "installation_id",
        "generation",
        "revision_digest",
        "transition_id",
        "writer_fence",
        "terminal",
        "site",
    }
)

# Every authority value can cross the private Plugin/Core protocol boundary.
# Keep this in the lower-level value module so storage, current-head adapters,
# and the wire contract cannot silently disagree about representability.
MAX_OPAQUE_TEXT_BYTES = 256


def _required_mapping(value: object, required: frozenset[str], name: str) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != required:
        raise AuthorityValidationError(f"invalid {name}")
    return value


def validate_opaque_text(value: object, name: str) -> str:
    # Security-relevant authority values must be plain immutable primitives.
    # ``str`` subclasses may override equality/hash and make a foreign
    # installation, fence, or digest appear to match a trusted value.
    if type(value) is not str or not value:
        raise AuthorityValidationError(f"invalid {name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AuthorityValidationError(f"invalid {name}") from exc
    if len(encoded) > MAX_OPAQUE_TEXT_BYTES:
        raise AuthorityValidationError(f"invalid {name}")
    return value


def validate_ticket110_effect_kind(value: object) -> str:
    """Accept only the controlled-effect kind implemented by Ticket 110.

    Delivery intents require a committed business record, an approved outbox,
    and a delivery receipt.  Those facts do not exist in this skeleton, so
    every durable controlled-effect boundary must reject them.
    """

    effect_kind = validate_opaque_text(value, "effect_kind")
    if effect_kind != "model-work":
        raise AuthorityValidationError("effect kind not supported in ticket 110")
    return effect_kind


def holder_id_for(completion_capability: object) -> str:
    """Return the non-secret remote binding for one execution capability.

    The capability itself is intentionally absent from encrypted durable effect
    state and effect intents.  Only the adapter that received the grant can
    later prove this binding to complete or recover the controlled effect.
    """

    capability = validate_opaque_text(completion_capability, "completion_capability")
    return "holder:" + hashlib.sha256(capability.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthoritySnapshot:
    """The complete opaque authority proof shared by all core transitions."""

    installation_id: str
    generation: int
    revision_digest: str
    transition_id: str
    writer_fence: str
    terminal: bool
    site: str

    def __post_init__(self) -> None:
        validate_opaque_text(self.installation_id, "installation_id")
        if (
            type(self.generation) is not int
            or self.generation < 1
        ):
            raise AuthorityValidationError("invalid generation")
        validate_opaque_text(self.revision_digest, "revision_digest")
        validate_opaque_text(self.transition_id, "transition_id")
        validate_opaque_text(self.writer_fence, "writer_fence")
        if type(self.terminal) is not bool:
            raise AuthorityValidationError("invalid terminal")
        validate_opaque_text(self.site, "site")

    def to_storage(self) -> dict[str, object]:
        return {
            "installation_id": self.installation_id,
            "generation": self.generation,
            "revision_digest": self.revision_digest,
            "transition_id": self.transition_id,
            "writer_fence": self.writer_fence,
            "terminal": self.terminal,
            "site": self.site,
        }

    @classmethod
    def from_storage(cls, value: object) -> "AuthoritySnapshot":
        stored = _required_mapping(value, _AUTHORITY_FIELDS, "authority")
        return cls(
            installation_id=validate_opaque_text(stored["installation_id"], "installation_id"),
            generation=stored["generation"],  # type: ignore[arg-type]
            revision_digest=validate_opaque_text(stored["revision_digest"], "revision_digest"),
            transition_id=validate_opaque_text(stored["transition_id"], "transition_id"),
            writer_fence=validate_opaque_text(stored["writer_fence"], "writer_fence"),
            terminal=stored["terminal"],  # type: ignore[arg-type]
            site=validate_opaque_text(stored["site"], "site"),
        )

    def mismatch_reason(self, current: "AuthoritySnapshot") -> str | None:
        """Return the stable local-proof failure code, if the snapshots differ."""

        if self.installation_id != current.installation_id:
            return "local-installation-mismatch"
        if self.generation != current.generation:
            return "local-generation-mismatch"
        if self.revision_digest != current.revision_digest:
            return "local-finalized-revision-mismatch"
        if self.transition_id != current.transition_id:
            return "local-transition-mismatch"
        if self.writer_fence != current.writer_fence:
            return "local-writer-fence-mismatch"
        if self.site != current.site:
            return "local-site-mismatch"
        if self.terminal != current.terminal:
            return "local-terminal-mismatch"
        return None


@dataclass(frozen=True)
class WriterFenceProof:
    """A host-private proof for the public writer-fence reference.

    ``capability`` is deliberately transient: it has no storage or wire
    representation.  Current-head adapters must verify it independently
    against their live writer holder; equality of the public fence string is
    never sufficient authority to write or to execute an effect.
    """

    authority: AuthoritySnapshot
    capability: str

    def __post_init__(self) -> None:
        if type(self.authority) is not AuthoritySnapshot or self.authority.terminal:
            raise AuthorityValidationError("invalid writer fence authority")
        validate_opaque_text(self.capability, "writer_fence_capability")


@dataclass(frozen=True)
class WriterHolderClaim:
    """An in-memory core identity used to hold one host writer session.

    It is neither a current-head fence nor a wire/storage value.  The host
    vault uses it only to ensure that one live core owns an installation/site
    namespace at a time.
    """

    value: str

    def __post_init__(self) -> None:
        validate_opaque_text(self.value, "writer holder claim")


@dataclass(frozen=True)
class RevisionTarget:
    """The immutable target held from candidate through finalization."""

    record_id: str
    revision_digest: str
    transition_id: str
    payload_digest: str

    def __post_init__(self) -> None:
        validate_opaque_text(self.record_id, "record_id")
        validate_opaque_text(self.revision_digest, "revision_digest")
        validate_opaque_text(self.transition_id, "transition_id")
        validate_opaque_text(self.payload_digest, "payload_digest")

    def to_storage(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "revision_digest": self.revision_digest,
            "transition_id": self.transition_id,
            "payload_digest": self.payload_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "RevisionTarget":
        stored = _required_mapping(
            value,
            frozenset({"record_id", "revision_digest", "transition_id", "payload_digest"}),
            "revision target",
        )
        return cls(
            record_id=validate_opaque_text(stored["record_id"], "record_id"),
            revision_digest=validate_opaque_text(stored["revision_digest"], "revision_digest"),
            transition_id=validate_opaque_text(stored["transition_id"], "transition_id"),
            payload_digest=validate_opaque_text(stored["payload_digest"], "payload_digest"),
        )

    def matches_commit(self, *, record_id: str, revision_digest: str, transition_id: str) -> bool:
        return (
            self.record_id == record_id
            and self.revision_digest == revision_digest
            and self.transition_id == transition_id
        )


@dataclass(frozen=True)
class PreparedTransition:
    """A target bound to the complete current-head authority at prepare time."""

    target: RevisionTarget
    base: AuthoritySnapshot

    def __post_init__(self) -> None:
        if type(self.target) is not RevisionTarget:
            raise AuthorityValidationError("invalid prepared target")
        if type(self.base) is not AuthoritySnapshot:
            raise AuthorityValidationError("invalid prepared authority")

    def to_storage(self) -> dict[str, object]:
        return {"target": self.target.to_storage(), "base": self.base.to_storage()}

    @classmethod
    def from_storage(cls, value: object) -> "PreparedTransition":
        stored = _required_mapping(value, frozenset({"target", "base"}), "prepared transition")
        return cls(
            target=RevisionTarget.from_storage(stored["target"]),
            base=AuthoritySnapshot.from_storage(stored["base"]),
        )


@dataclass(frozen=True)
class CommittedTransition:
    """A prepared target with the exact authority returned by current-head."""

    prepared: PreparedTransition
    committed: AuthoritySnapshot

    def __post_init__(self) -> None:
        if type(self.prepared) is not PreparedTransition:
            raise AuthorityValidationError("invalid committed preparation")
        if type(self.committed) is not AuthoritySnapshot:
            raise AuthorityValidationError("invalid committed authority")
        if self.committed.installation_id != self.prepared.base.installation_id:
            raise AuthorityValidationError("committed installation mismatch")
        if self.committed.site != self.prepared.base.site:
            raise AuthorityValidationError("committed site mismatch")
        if self.committed.generation != self.prepared.base.generation + 1:
            raise AuthorityValidationError("committed generation mismatch")
        if self.committed.revision_digest != self.prepared.target.revision_digest:
            raise AuthorityValidationError("committed revision mismatch")
        if self.committed.transition_id != self.prepared.target.transition_id:
            raise AuthorityValidationError("committed transition mismatch")
        if self.committed.writer_fence != self.prepared.base.writer_fence:
            raise AuthorityValidationError("committed writer fence mismatch")
        if self.committed.terminal:
            raise AuthorityValidationError("committed authority cannot be terminal")

    def to_storage(self) -> dict[str, object]:
        return {
            "prepared": self.prepared.to_storage(),
            "committed": self.committed.to_storage(),
        }

    @classmethod
    def from_storage(cls, value: object) -> "CommittedTransition":
        stored = _required_mapping(value, frozenset({"prepared", "committed"}), "committed transition")
        return cls(
            prepared=PreparedTransition.from_storage(stored["prepared"]),
            committed=AuthoritySnapshot.from_storage(stored["committed"]),
        )


def validate_committed_transition(value: object) -> CommittedTransition:
    """Rebuild a committed transition before trusting a collaborator value."""

    if type(value) is not CommittedTransition:
        raise AuthorityValidationError("invalid committed transition")
    prepared = value.prepared
    committed = value.committed
    if (
        type(prepared) is not PreparedTransition
        or type(prepared.target) is not RevisionTarget
        or type(prepared.base) is not AuthoritySnapshot
        or type(committed) is not AuthoritySnapshot
    ):
        raise AuthorityValidationError("invalid committed transition")
    return CommittedTransition(
        prepared=PreparedTransition.from_storage(prepared.to_storage()),
        committed=AuthoritySnapshot.from_storage(committed.to_storage()),
    )


@dataclass(frozen=True)
class EffectIntent:
    """A core-issued effect description, not itself permission to execute it.

    The private Plugin facade must obtain a fresh core execution claim before a
    model or outbound adapter acts on this intent.  That claim is persisted as
    ``executing`` and rechecks the complete current authority proof.
    """

    effect_id: str
    effect_kind: str
    intent_digest: str
    authority: AuthoritySnapshot

    def __post_init__(self) -> None:
        validate_opaque_text(self.effect_id, "effect_id")
        validate_ticket110_effect_kind(self.effect_kind)
        validate_opaque_text(self.intent_digest, "intent_digest")
        if type(self.authority) is not AuthoritySnapshot:
            raise AuthorityValidationError("invalid effect authority")

    def to_storage(self) -> dict[str, object]:
        return {
            "effect_id": self.effect_id,
            "effect_kind": self.effect_kind,
            "intent_digest": self.intent_digest,
            "authority": self.authority.to_storage(),
        }

    def to_wire_metadata(self) -> dict[str, object]:
        """Return the one nested authority shape used by response metadata."""

        return self.to_storage()

    @classmethod
    def from_storage(cls, value: object) -> "EffectIntent":
        stored = _required_mapping(
            value,
            frozenset({"effect_id", "effect_kind", "intent_digest", "authority"}),
            "effect intent",
        )
        return cls(
            effect_id=validate_opaque_text(stored["effect_id"], "effect_id"),
            effect_kind=validate_opaque_text(stored["effect_kind"], "effect_kind"),
            intent_digest=validate_opaque_text(stored["intent_digest"], "intent_digest"),
            authority=AuthoritySnapshot.from_storage(stored["authority"]),
        )

    @classmethod
    def from_wire_metadata(cls, value: object) -> "EffectIntent":
        """Decode response metadata through the same authority schema as storage."""

        return cls.from_storage(value)


@dataclass(frozen=True)
class ExecutionCapabilityBinding:
    """Complete non-secret namespace for one host-held effect capability."""

    authority: AuthoritySnapshot
    effect_id: str
    intent_digest: str
    vault_claim_ref: str

    def __post_init__(self) -> None:
        if type(self.authority) is not AuthoritySnapshot or self.authority.terminal:
            raise AuthorityValidationError("invalid execution capability authority")
        validate_opaque_text(self.effect_id, "effect_id")
        validate_opaque_text(self.intent_digest, "intent_digest")
        validate_opaque_text(self.vault_claim_ref, "vault claim reference")

    @classmethod
    def for_claim(cls, claim: "ClaimingEffect") -> "ExecutionCapabilityBinding":
        if type(claim) is not ClaimingEffect:
            raise AuthorityValidationError("invalid execution capability claim")
        validate_ticket110_effect_kind(claim.intent.effect_kind)
        return cls(
            authority=claim.intent.authority,
            effect_id=claim.intent.effect_id,
            intent_digest=claim.intent.intent_digest,
            vault_claim_ref=claim.vault_claim_ref,
        )

    @classmethod
    def for_execution(cls, execution: "ExecutingEffect") -> "ExecutionCapabilityBinding":
        if type(execution) is not ExecutingEffect:
            raise AuthorityValidationError("invalid execution capability execution")
        validate_ticket110_effect_kind(execution.intent.effect_kind)
        return cls(
            authority=execution.intent.authority,
            effect_id=execution.intent.effect_id,
            intent_digest=execution.intent.intent_digest,
            vault_claim_ref=execution.vault_claim_ref,
        )


@dataclass(frozen=True)
class ClaimingEffect:
    """A durable local claim before the remote effect lease is acquired.

    ``holder_id`` is a one-way binding of an in-memory completion capability;
    it cannot itself authorize an effect or its terminal result.
    """

    intent: EffectIntent
    holder_id: str
    vault_claim_ref: str

    def __post_init__(self) -> None:
        if type(self.intent) is not EffectIntent:
            raise AuthorityValidationError("invalid claiming effect intent")
        validate_ticket110_effect_kind(self.intent.effect_kind)
        validate_opaque_text(self.holder_id, "effect holder identifier")
        validate_opaque_text(self.vault_claim_ref, "vault claim reference")

    def to_storage(self) -> dict[str, object]:
        return {
            "intent": self.intent.to_storage(),
            "holder_id": self.holder_id,
            "vault_claim_ref": self.vault_claim_ref,
        }

    @classmethod
    def from_storage(cls, value: object) -> "ClaimingEffect":
        stored = _required_mapping(
            value,
            frozenset({"intent", "holder_id", "vault_claim_ref"}),
            "claiming effect",
        )
        return cls(
            intent=EffectIntent.from_storage(stored["intent"]),
            holder_id=validate_opaque_text(stored["holder_id"], "effect holder identifier"),
            vault_claim_ref=validate_opaque_text(stored["vault_claim_ref"], "vault claim reference"),
        )


@dataclass(frozen=True)
class ExecutionLease:
    """A current-head-held fence for exactly one controlled effect."""

    lease_id: str
    effect_id: str
    intent_digest: str
    authority: AuthoritySnapshot
    holder_id: str

    def __post_init__(self) -> None:
        validate_opaque_text(self.lease_id, "lease_id")
        validate_opaque_text(self.effect_id, "effect_id")
        validate_opaque_text(self.intent_digest, "intent_digest")
        validate_opaque_text(self.holder_id, "effect holder identifier")
        if type(self.authority) is not AuthoritySnapshot or self.authority.terminal:
            raise AuthorityValidationError("invalid execution lease authority")

    def to_storage(self) -> dict[str, object]:
        return {
            "lease_id": self.lease_id,
            "effect_id": self.effect_id,
            "intent_digest": self.intent_digest,
            "authority": self.authority.to_storage(),
            "holder_id": self.holder_id,
        }

    @classmethod
    def from_storage(cls, value: object) -> "ExecutionLease":
        stored = _required_mapping(
            value,
            frozenset({"lease_id", "effect_id", "intent_digest", "authority", "holder_id"}),
            "execution lease",
        )
        return cls(
            lease_id=validate_opaque_text(stored["lease_id"], "lease_id"),
            effect_id=validate_opaque_text(stored["effect_id"], "effect_id"),
            intent_digest=validate_opaque_text(stored["intent_digest"], "intent_digest"),
            authority=AuthoritySnapshot.from_storage(stored["authority"]),
            holder_id=validate_opaque_text(stored["holder_id"], "effect holder identifier"),
        )


@dataclass(frozen=True)
class EffectExecutionGrant:
    """Non-durable completion capability returned only after a valid claim."""

    lease: ExecutionLease
    completion_capability: str

    def __post_init__(self) -> None:
        if type(self.lease) is not ExecutionLease:
            raise AuthorityValidationError("invalid effect execution lease")
        capability = validate_opaque_text(self.completion_capability, "completion_capability")
        if self.lease.holder_id != holder_id_for(capability):
            raise AuthorityValidationError("execution capability does not match lease holder")


@dataclass(frozen=True)
class ExecutingEffect:
    """A core intent whose remote writer-fence lease is still held."""

    intent: EffectIntent
    lease: ExecutionLease
    vault_claim_ref: str

    def __post_init__(self) -> None:
        if type(self.intent) is not EffectIntent:
            raise AuthorityValidationError("invalid executing effect intent")
        validate_ticket110_effect_kind(self.intent.effect_kind)
        if type(self.lease) is not ExecutionLease:
            raise AuthorityValidationError("invalid executing effect lease")
        validate_opaque_text(self.vault_claim_ref, "vault claim reference")
        if (
            self.lease.effect_id != self.intent.effect_id
            or self.lease.intent_digest != self.intent.intent_digest
            or self.lease.authority != self.intent.authority
        ):
            raise AuthorityValidationError("execution lease does not match effect intent")

    def to_storage(self) -> dict[str, object]:
        return {
            "intent": self.intent.to_storage(),
            "lease": self.lease.to_storage(),
            "vault_claim_ref": self.vault_claim_ref,
        }

    @classmethod
    def from_storage(cls, value: object) -> "ExecutingEffect":
        stored = _required_mapping(
            value,
            frozenset({"intent", "lease", "vault_claim_ref"}),
            "executing effect",
        )
        return cls(
            intent=EffectIntent.from_storage(stored["intent"]),
            lease=ExecutionLease.from_storage(stored["lease"]),
            vault_claim_ref=validate_opaque_text(stored["vault_claim_ref"], "vault claim reference"),
        )


@dataclass(frozen=True)
class TerminalEffect:
    """A complete, locally recorded result for a core-issued effect intent."""

    execution: ExecutingEffect
    status: str
    result_digest: str
    model_report: ModelEffectReport | None = None

    def __post_init__(self) -> None:
        if type(self.execution) is not ExecutingEffect:
            raise AuthorityValidationError("invalid terminal execution")
        validate_ticket110_effect_kind(self.execution.intent.effect_kind)
        if type(self.status) is not str or self.status not in {"accepted", "rejected", "unknown"}:
            raise AuthorityValidationError("invalid effect status")
        validate_opaque_text(self.result_digest, "result_digest")
        if self.model_report is not None:
            if type(self.model_report) is not ModelEffectReport:
                raise AuthorityValidationError("invalid model effect report")
            if self.execution.intent.effect_kind != "model-work":
                raise AuthorityValidationError("model report requires a model effect")
            if self.result_digest != self.model_report.digest:
                raise AuthorityValidationError("model effect report digest mismatch")
            if self.status != self.model_report.outer_effect_status:
                raise AuthorityValidationError("model effect outer status mismatch")

    @property
    def intent(self) -> EffectIntent:
        return self.execution.intent

    @property
    def lease(self) -> ExecutionLease:
        return self.execution.lease

    def to_storage(self) -> dict[str, object]:
        stored: dict[str, object] = {
            "execution": self.execution.to_storage(),
            "status": self.status,
            "result_digest": self.result_digest,
        }
        if self.model_report is not None:
            stored["model_report"] = self.model_report.to_storage()
        return stored

    @classmethod
    def from_storage(cls, value: object) -> "TerminalEffect":
        legacy_fields = frozenset({"execution", "status", "result_digest"})
        if not isinstance(value, Mapping) or frozenset(value) not in (
            legacy_fields,
            legacy_fields | {"model_report"},
        ):
            raise AuthorityValidationError("invalid terminal effect")
        stored = value
        try:
            return cls(
                execution=ExecutingEffect.from_storage(stored["execution"]),
                status=stored["status"],  # type: ignore[arg-type]
                result_digest=validate_opaque_text(stored["result_digest"], "result_digest"),
                model_report=(
                    None
                    if "model_report" not in stored
                    else ModelEffectReport.from_storage(stored["model_report"])
                ),
            )
        except ValueError as exc:
            if isinstance(exc, AuthorityValidationError):
                raise
            raise AuthorityValidationError("invalid terminal effect") from exc

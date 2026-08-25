"""Typed difference contracts for Ticket 115's current acceptance matrix.

The older task and delivery values remain the compatibility surface.  These
values add the facts that the synchronized contract requires without giving
Plugin, Skill, or a transport adapter write authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from datetime import datetime
from math import isfinite
from types import MappingProxyType
from typing import Mapping

from .initialization import stable_digest


class Ticket115ContractViolation(ValueError):
    """A Ticket 115 typed fact is invalid or crosses an authority boundary."""


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise Ticket115ContractViolation(f"invalid {name}")
    return value


def _sha(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise Ticket115ContractViolation(f"invalid {name}")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise Ticket115ContractViolation(f"invalid {name}") from exc
    return text


def _utc(value: object, name: str) -> str:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise Ticket115ContractViolation(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise Ticket115ContractViolation(f"invalid {name}")
    return text


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise Ticket115ContractViolation(f"invalid {name}")
    return value


@dataclass(frozen=True)
class TaskClaimLease:
    """A task-worker lease that is never compared across runtime epochs."""

    claim_id: str
    task_id: str
    generation: int
    holder_role: str
    runtime_epoch: str
    acquired_at_monotonic_seconds: float
    expires_at_monotonic_seconds: float
    task_revision: int
    task_cas_identity: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.claim_id, "task claim identifier"),
            (self.task_id, "task claim task identifier"),
            (self.holder_role, "task claim holder role"),
            (self.runtime_epoch, "task claim runtime epoch"),
            (self.task_cas_identity, "task claim CAS identity"),
        ):
            _text(value, name)
        _positive(self.generation, "task claim generation")
        _positive(self.task_revision, "task claim revision")
        if (
            type(self.acquired_at_monotonic_seconds) is not float
            or not isfinite(self.acquired_at_monotonic_seconds)
        ):
            raise Ticket115ContractViolation("invalid task claim acquisition clock")
        if (
            type(self.expires_at_monotonic_seconds) is not float
            or not isfinite(self.expires_at_monotonic_seconds)
        ):
            raise Ticket115ContractViolation("invalid task claim expiry clock")
        if self.expires_at_monotonic_seconds <= self.acquired_at_monotonic_seconds:
            raise Ticket115ContractViolation("task claim must expire after acquisition")

    @property
    def cas_identity(self) -> str:
        return self.task_cas_identity

    def is_active(self, *, runtime_epoch: str, monotonic_seconds: float) -> bool:
        if runtime_epoch != self.runtime_epoch:
            return False
        return (
            self.acquired_at_monotonic_seconds
            <= monotonic_seconds
            < self.expires_at_monotonic_seconds
        )

    def can_commit(
        self,
        *,
        runtime_epoch: str,
        monotonic_seconds: float,
        task_revision: int,
        task_cas_identity: str,
    ) -> bool:
        return self.is_active(
            runtime_epoch=runtime_epoch,
            monotonic_seconds=monotonic_seconds,
        ) and task_revision == self.task_revision and task_cas_identity == self.task_cas_identity

    def to_storage(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "task_id": self.task_id,
            "generation": self.generation,
            "holder_role": self.holder_role,
            "runtime_epoch": self.runtime_epoch,
            "acquired_at_monotonic_seconds": self.acquired_at_monotonic_seconds,
            "expires_at_monotonic_seconds": self.expires_at_monotonic_seconds,
            "task_revision": self.task_revision,
            "task_cas_identity": self.task_cas_identity,
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskClaimLease":
        fields = frozenset(
            {
                "claim_id",
                "task_id",
                "generation",
                "holder_role",
                "runtime_epoch",
                "acquired_at_monotonic_seconds",
                "expires_at_monotonic_seconds",
                "task_revision",
                "task_cas_identity",
            }
        )
        if type(value) is not dict or frozenset(value) != fields:
            raise Ticket115ContractViolation("invalid task claim lease")
        return cls(
            claim_id=_text(value["claim_id"], "task claim identifier"),
            task_id=_text(value["task_id"], "task claim task identifier"),
            generation=_positive(value["generation"], "task claim generation"),
            holder_role=_text(value["holder_role"], "task claim holder role"),
            runtime_epoch=_text(value["runtime_epoch"], "task claim runtime epoch"),
            acquired_at_monotonic_seconds=value["acquired_at_monotonic_seconds"],  # type: ignore[arg-type]
            expires_at_monotonic_seconds=value["expires_at_monotonic_seconds"],  # type: ignore[arg-type]
            task_revision=_positive(value["task_revision"], "task claim revision"),
            task_cas_identity=_text(
                value["task_cas_identity"], "task claim CAS identity"
            ),
        )


@dataclass(frozen=True)
class DeliveryEvidence:
    """One immutable layer proof with its producer and replay identity."""

    layer: str
    producer_contract: str
    generation: int
    attestation: str
    replay_identity: str
    effect_id: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if self.layer not in {
            "formed",
            "business-committed",
            "attempted",
            "interface-accepted",
            "interface-rejected",
            "delivered",
            "read",
            "actual-action",
            "unknown",
        }:
            raise Ticket115ContractViolation("invalid delivery evidence layer")
        for value, name in (
            (self.producer_contract, "delivery producer contract"),
            (self.attestation, "delivery attestation"),
            (self.replay_identity, "delivery replay identity"),
            (self.effect_id, "delivery effect identifier"),
            (self.evidence_ref, "delivery evidence reference"),
        ):
            _text(value, name)
        _positive(self.generation, "delivery evidence generation")
        _sha(self.attestation, "delivery attestation")

    @property
    def digest(self) -> str:
        return stable_digest(
            {
                "layer": self.layer,
                "producer_contract": self.producer_contract,
                "generation": self.generation,
                "attestation": self.attestation,
                "replay_identity": self.replay_identity,
                "effect_id": self.effect_id,
                "evidence_ref": self.evidence_ref,
            }
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "layer": self.layer,
            "producer_contract": self.producer_contract,
            "generation": self.generation,
            "attestation": self.attestation,
            "replay_identity": self.replay_identity,
            "effect_id": self.effect_id,
            "evidence_ref": self.evidence_ref,
        }

    @classmethod
    def from_storage(cls, value: object) -> "DeliveryEvidence":
        if type(value) is not dict:
            raise Ticket115ContractViolation("invalid delivery evidence")
        return cls(**value)  # type: ignore[arg-type]


class DeliveryEvidenceAuthority:
    """Restrict which producer may prove each delivery layer."""

    PRODUCER_BY_LAYER = MappingProxyType({
        "formed": "health-core.delivery.formed",
        "business-committed": "health-core.delivery.committed",
        "attempted": "owner-delivery-adapter.attempted",
        "interface-accepted": "owner-delivery-adapter.interface",
        "interface-rejected": "owner-delivery-adapter.interface",
        "unknown": "owner-delivery-adapter.unknown",
        "delivered": "weixin.channel.receipt",
        "read": "weixin.channel.receipt",
        "actual-action": "owner.admitted-event",
    })

    @classmethod
    def verify(cls, evidence: DeliveryEvidence) -> bool:
        return (
            type(evidence) is DeliveryEvidence
            and cls.PRODUCER_BY_LAYER.get(evidence.layer)
            == evidence.producer_contract
        )

    @classmethod
    def require(cls, evidence: DeliveryEvidence) -> DeliveryEvidence:
        if not cls.verify(evidence):
            raise Ticket115ContractViolation("delivery evidence producer is not authoritative")
        return evidence


MANDATORY_DELIVERY_KINDS = (
    "status-change",
    "authorization-request",
    "unknown-risk-decision",
    "capability-gap",
)


@dataclass(frozen=True)
class MandatoryDeliveryRequest:
    """A content-free, one-causal-state required owner action."""

    request_id: str
    kind: str
    causal_state_id: str
    generation: int
    reason_code: str
    body_free: bool = True

    def __post_init__(self) -> None:
        if self.kind not in MANDATORY_DELIVERY_KINDS:
            raise Ticket115ContractViolation("invalid mandatory delivery kind")
        for value, name in (
            (self.request_id, "mandatory request identifier"),
            (self.causal_state_id, "mandatory request causal state"),
            (self.reason_code, "mandatory request reason"),
        ):
            _text(value, name)
        _positive(self.generation, "mandatory request generation")
        if self.body_free is not True:
            raise Ticket115ContractViolation("mandatory request must be content-free")

    @property
    def dedupe_key(self) -> str:
        return stable_digest(
            {
                "kind": self.kind,
                "causal_state_id": self.causal_state_id,
                "generation": self.generation,
            }
        )


@dataclass(frozen=True)
class MandatoryDeliveryLedger:
    """Append-only dedupe ledger for required owner notifications."""

    requests: tuple[MandatoryDeliveryRequest, ...] = ()

    def __post_init__(self) -> None:
        keys = tuple(item.dedupe_key for item in self.requests)
        if len(keys) != len(set(keys)):
            raise Ticket115ContractViolation("duplicate mandatory causal state")

    def issue(self, request: MandatoryDeliveryRequest) -> tuple["MandatoryDeliveryLedger", bool]:
        if type(request) is not MandatoryDeliveryRequest:
            raise Ticket115ContractViolation("invalid mandatory delivery request")
        if any(item.dedupe_key == request.dedupe_key for item in self.requests):
            return self, False
        return (
            MandatoryDeliveryLedger(self.requests + (request,)),
            True,
        )


__all__ = [
    "DeliveryEvidence",
    "DeliveryEvidenceAuthority",
    "MANDATORY_DELIVERY_KINDS",
    "MandatoryDeliveryLedger",
    "MandatoryDeliveryRequest",
    "TaskClaimLease",
    "Ticket115ContractViolation",
]

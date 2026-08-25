"""Typed difference contracts for Ticket 115's current acceptance matrix.

The older task and delivery values remain the compatibility surface.  These
values add the facts that the synchronized contract requires without giving
Plugin, Skill, or a transport adapter write authority.
"""

from __future__ import annotations

import hashlib
import hmac
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
        generation: int,
        holder_role: str,
        task_revision: int,
        task_cas_identity: str,
    ) -> bool:
        return self.is_active(
            runtime_epoch=runtime_epoch,
            monotonic_seconds=monotonic_seconds,
        ) and (
            generation == self.generation
            and holder_role == self.holder_role
            and task_revision == self.task_revision
            and task_cas_identity == self.task_cas_identity
        )

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

    @property
    def signing_material(self) -> dict[str, object]:
        return {
            "layer": self.layer,
            "producer_contract": self.producer_contract,
            "generation": self.generation,
            "replay_identity": self.replay_identity,
            "effect_id": self.effect_id,
            "evidence_ref": self.evidence_ref,
        }

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
        fields = frozenset(
            {
                "layer",
                "producer_contract",
                "generation",
                "attestation",
                "replay_identity",
                "effect_id",
                "evidence_ref",
            }
        )
        if type(value) is not dict or frozenset(value) != fields:
            raise Ticket115ContractViolation("invalid delivery evidence")
        return cls(**value)  # type: ignore[arg-type]


def _delivery_attestation(
    signing_key: bytes,
    material: Mapping[str, object],
) -> str:
    digest = stable_digest(dict(material)).encode("ascii")
    return "sha256:" + hmac.new(signing_key, digest, hashlib.sha256).hexdigest()


class DeliveryEvidenceIssuer:
    """A producer-bound signing capability for only its declared layers."""

    __slots__ = ("producer_contract", "allowed_layers", "_signing_key")

    def __init__(
        self,
        *,
        producer_contract: str,
        allowed_layers: tuple[str, ...],
        signing_key: bytes,
    ) -> None:
        self.producer_contract = _text(
            producer_contract,
            "delivery producer contract",
        )
        if (
            type(allowed_layers) is not tuple
            or not allowed_layers
            or len(allowed_layers) != len(set(allowed_layers))
            or any(
                DeliveryEvidenceAuthority.PRODUCER_BY_LAYER.get(layer)
                != self.producer_contract
                for layer in allowed_layers
            )
        ):
            raise Ticket115ContractViolation("invalid delivery issuer layers")
        if type(signing_key) is not bytes or len(signing_key) < 16:
            raise Ticket115ContractViolation("invalid delivery signing key")
        self.allowed_layers = allowed_layers
        self._signing_key = bytes(signing_key)

    def issue(
        self,
        *,
        layer: str,
        generation: int,
        replay_identity: str,
        effect_id: str,
        evidence_ref: str,
    ) -> DeliveryEvidence:
        if layer not in self.allowed_layers:
            raise Ticket115ContractViolation("delivery issuer cannot prove layer")
        material = {
            "layer": layer,
            "producer_contract": self.producer_contract,
            "generation": _positive(generation, "delivery evidence generation"),
            "replay_identity": _text(
                replay_identity,
                "delivery replay identity",
            ),
            "effect_id": _text(effect_id, "delivery effect identifier"),
            "evidence_ref": _text(evidence_ref, "delivery evidence reference"),
        }
        return DeliveryEvidence(
            **material,
            attestation=_delivery_attestation(self._signing_key, material),
        )


class DeliveryEvidenceAuthority:
    """Verify producer possession plus exact layer/effect/replay bindings."""

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

    def __init__(self, producer_keys: Mapping[str, bytes]) -> None:
        if not isinstance(producer_keys, Mapping):
            raise Ticket115ContractViolation("invalid delivery producer manifest")
        keys: dict[str, bytes] = {}
        for producer, key in producer_keys.items():
            parsed = _text(producer, "delivery producer contract")
            if parsed not in self.PRODUCER_BY_LAYER.values():
                raise Ticket115ContractViolation("unknown delivery producer contract")
            if type(key) is not bytes or len(key) < 16:
                raise Ticket115ContractViolation("invalid delivery verification key")
            keys[parsed] = bytes(key)
        self._producer_keys = MappingProxyType(keys)

    @property
    def producer_contracts(self) -> frozenset[str]:
        return frozenset(self._producer_keys)

    def verify(
        self,
        evidence: DeliveryEvidence,
        *,
        expected_layer: str | None = None,
        expected_generation: int | None = None,
        expected_effect_id: str | None = None,
        expected_replay_identity: str | None = None,
    ) -> bool:
        if type(evidence) is not DeliveryEvidence:
            return False
        key = self._producer_keys.get(evidence.producer_contract)
        if (
            key is None
            or self.PRODUCER_BY_LAYER.get(evidence.layer)
            != evidence.producer_contract
            or (expected_layer is not None and evidence.layer != expected_layer)
            or (
                expected_generation is not None
                and evidence.generation != expected_generation
            )
            or (
                expected_effect_id is not None
                and evidence.effect_id != expected_effect_id
            )
            or (
                expected_replay_identity is not None
                and evidence.replay_identity != expected_replay_identity
            )
        ):
            return False
        expected = _delivery_attestation(key, evidence.signing_material)
        return hmac.compare_digest(evidence.attestation, expected)

    def require(
        self,
        evidence: DeliveryEvidence,
        *,
        expected_layer: str | None = None,
        expected_generation: int | None = None,
        expected_effect_id: str | None = None,
        expected_replay_identity: str | None = None,
    ) -> DeliveryEvidence:
        if not self.verify(
            evidence,
            expected_layer=expected_layer,
            expected_generation=expected_generation,
            expected_effect_id=expected_effect_id,
            expected_replay_identity=expected_replay_identity,
        ):
            raise Ticket115ContractViolation(
                "delivery evidence is not authoritative"
            )
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

    def to_storage(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "kind": self.kind,
            "causal_state_id": self.causal_state_id,
            "generation": self.generation,
            "reason_code": self.reason_code,
            "body_free": self.body_free,
        }

    @classmethod
    def from_storage(cls, value: object) -> "MandatoryDeliveryRequest":
        fields = frozenset(
            {
                "request_id",
                "kind",
                "causal_state_id",
                "generation",
                "reason_code",
                "body_free",
            }
        )
        if type(value) is not dict or frozenset(value) != fields:
            raise Ticket115ContractViolation("invalid mandatory delivery request")
        return cls(**value)  # type: ignore[arg-type]


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

    def to_storage(self) -> dict[str, object]:
        return {
            "requests": [request.to_storage() for request in self.requests],
        }

    @classmethod
    def from_storage(cls, value: object) -> "MandatoryDeliveryLedger":
        if type(value) is not dict or frozenset(value) != {"requests"}:
            raise Ticket115ContractViolation("invalid mandatory delivery ledger")
        requests = value["requests"]
        if type(requests) is not list:
            raise Ticket115ContractViolation("invalid mandatory delivery ledger")
        return cls(
            tuple(MandatoryDeliveryRequest.from_storage(item) for item in requests)
        )


__all__ = [
    "DeliveryEvidence",
    "DeliveryEvidenceAuthority",
    "DeliveryEvidenceIssuer",
    "MANDATORY_DELIVERY_KINDS",
    "MandatoryDeliveryLedger",
    "MandatoryDeliveryRequest",
    "TaskClaimLease",
    "Ticket115ContractViolation",
]

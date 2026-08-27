"""Transactional outbox values for layered Ticket 115 owner delivery.

This module is deliberately independent from core persistence and the channel
adapter.  Core can commit one :class:`OutboxIntent` beside its business fact,
then a worker can claim that submitted value and report channel observations
without collapsing interface acceptance, delivery, or reading into one state.

Support-contact delivery remains disabled here.  Ticket 116 must introduce a
separate approved authority chain before ``contact-delivery`` can be formed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from .initialization import stable_digest


class DeliveryContractViolation(ValueError):
    """A value cannot cross the managed owner-delivery boundary."""


CONTACT_DELIVERY_ENABLED = False
DELIVERY_EFFECT_KINDS = ("owner-delivery",)
DELIVERY_FACT_KINDS = (
    "formed",
    "submitted",
    "attempted",
    "accepted",
    "rejected",
    "delivered",
    "read",
    "unknown",
)
DELIVERY_OBSERVATION_KINDS = (
    "accepted",
    "rejected",
    "delivered",
    "read",
    "unknown",
)
OWNER_DELIVERY_TRANSPORT_STATUSES = ("accepted", "rejected", "unknown")
OWNER_DELIVERY_AUTHORIZATION_KINDS = (
    "legacy",
    "approval",
    "delivery-unknown",
    "status-transition",
)

_FACT_ORDER = {kind: index for index, kind in enumerate(DELIVERY_FACT_KINDS)}
_MAX_TEXT_BYTES = 4_096


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise DeliveryContractViolation(f"invalid {name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DeliveryContractViolation(f"invalid {name}") from exc
    if len(encoded) > _MAX_TEXT_BYTES:
        raise DeliveryContractViolation(f"invalid {name}")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _sha256(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise DeliveryContractViolation(f"invalid {name}")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise DeliveryContractViolation(f"invalid {name}") from exc
    return text


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise DeliveryContractViolation(f"invalid {name}")
    return value


def _utc(value: object, name: str) -> str:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DeliveryContractViolation(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise DeliveryContractViolation(f"invalid {name}")
    return text


def _utc_datetime(value: object, name: str) -> datetime:
    return datetime.fromisoformat(_utc(value, name))


def _status_supersession_refs(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if type(value) is not tuple:
        raise DeliveryContractViolation(
            "status supersession references must be a tuple"
        )
    refs = tuple(
        _text(item, "status supersession reference")
        for item in value
    )
    if len(refs) != len(set(refs)):
        raise DeliveryContractViolation(
            "status supersession references must be unique"
        )
    return refs


def _intent_wire_version(
    authorization_kind: str,
    status_supersedes_refs: tuple[str, ...] | None,
) -> str:
    if authorization_kind == "legacy":
        return "v1"
    if (
        authorization_kind == "status-transition"
        and status_supersedes_refs is not None
    ):
        return "v3"
    return "v2"


def validate_owner_delivery_observed_at(value: object) -> str:
    """Validate the timestamp before a transport side effect is attempted."""

    return _utc(value, "owner delivery observation time")


def _mapping(
    value: object,
    fields: frozenset[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise DeliveryContractViolation(f"invalid {name}")
    return value


def _intent_material(
    *,
    effect_kind: str,
    owner_id: str,
    installation_id: str,
    effect_request_id: str,
    business_fact_ref: str,
    business_revision_digest: str,
    source_ref: str,
    recipient_ref: str,
    route_id: str,
    route_generation: int,
    payload_ref: str,
    payload_digest: str,
    authorization_kind: str = "legacy",
    approval_binding_digest: str | None = None,
    status_target_active: bool | None = None,
    status_supersedes_refs: tuple[str, ...] | None = None,
) -> dict[str, object]:
    material: dict[str, object] = {
        "contract": "owner-delivery-intent-v1",
        "effect_kind": effect_kind,
        "owner_id": owner_id,
        "installation_id": installation_id,
        "effect_request_id": effect_request_id,
        "business_fact_ref": business_fact_ref,
        "business_revision_digest": business_revision_digest,
        "source_ref": source_ref,
        "recipient_ref": recipient_ref,
        "route_id": route_id,
        "route_generation": route_generation,
        "payload_ref": payload_ref,
        "payload_digest": payload_digest,
    }
    if authorization_kind != "legacy":
        material.update(
            contract="owner-delivery-intent-v2",
            authorization_kind=authorization_kind,
            approval_binding_digest=approval_binding_digest,
            status_target_active=status_target_active,
        )
    if authorization_kind == "status-transition" and status_supersedes_refs is not None:
        material.update(
            contract="owner-delivery-intent-v3",
            status_supersedes_refs=status_supersedes_refs,
        )
    return material


def owner_delivery_idempotency_key(
    *,
    owner_id: str,
    installation_id: str,
    effect_request_id: str,
    business_fact_ref: str,
    business_revision_digest: str,
    source_ref: str,
    recipient_ref: str,
    route_id: str,
    route_generation: int,
    payload_ref: str,
    payload_digest: str,
    authorization_kind: str = "legacy",
    approval_binding_digest: str | None = None,
    status_target_active: bool | None = None,
    status_supersedes_refs: tuple[str, ...] | None = None,
) -> str:
    """Return the stable, opaque channel key for one exact owner effect."""

    values = {
        "owner_id": _text(owner_id, "delivery owner"),
        "installation_id": _text(installation_id, "delivery installation"),
        "effect_request_id": _text(
            effect_request_id, "delivery effect request identifier"
        ),
        "business_fact_ref": _text(
            business_fact_ref, "delivery business fact reference"
        ),
        "business_revision_digest": _sha256(
            business_revision_digest, "delivery business revision"
        ),
        "source_ref": _text(source_ref, "delivery source reference"),
        "recipient_ref": _text(recipient_ref, "delivery recipient reference"),
        "route_id": _text(route_id, "delivery route identifier"),
        "route_generation": _positive_int(
            route_generation, "delivery route generation"
        ),
        "payload_ref": _text(payload_ref, "delivery payload reference"),
        "payload_digest": _sha256(payload_digest, "delivery payload digest"),
    }
    digest = stable_digest(
        _intent_material(
            effect_kind="owner-delivery",
            authorization_kind=authorization_kind,
            approval_binding_digest=approval_binding_digest,
            status_target_active=status_target_active,
            status_supersedes_refs=status_supersedes_refs,
            **values,
        )
    )
    version = _intent_wire_version(authorization_kind, status_supersedes_refs)
    return f"health-owner-delivery:{version}:" + digest.removeprefix("sha256:")


@dataclass(frozen=True)
class OutboxIntent:
    """One immutable owner-delivery intent committed with a business fact."""

    intent_id: str
    effect_kind: str
    owner_id: str
    installation_id: str
    effect_request_id: str
    business_fact_ref: str
    business_revision_digest: str
    source_ref: str
    recipient_ref: str
    route_id: str
    route_generation: int
    payload_ref: str
    payload_digest: str
    semantic_digest: str
    idempotency_key: str
    formed_at_utc: str
    authorization_kind: str = "legacy"
    approval_binding_digest: str | None = None
    status_target_active: bool | None = None
    status_supersedes_refs: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.effect_kind == "contact-delivery":
            raise DeliveryContractViolation("contact delivery is not enabled")
        if self.effect_kind not in DELIVERY_EFFECT_KINDS:
            raise DeliveryContractViolation("unsupported delivery effect kind")
        for value, name in (
            (self.intent_id, "outbox intent identifier"),
            (self.owner_id, "delivery owner"),
            (self.installation_id, "delivery installation"),
            (self.effect_request_id, "delivery effect request identifier"),
            (self.business_fact_ref, "delivery business fact reference"),
            (self.source_ref, "delivery source reference"),
            (self.recipient_ref, "delivery recipient reference"),
            (self.route_id, "delivery route identifier"),
            (self.payload_ref, "delivery payload reference"),
        ):
            _text(value, name)
        _sha256(self.business_revision_digest, "delivery business revision")
        _positive_int(self.route_generation, "delivery route generation")
        _sha256(self.payload_digest, "delivery payload digest")
        _sha256(self.semantic_digest, "delivery intent semantic digest")
        _text(self.idempotency_key, "delivery idempotency key")
        _utc(self.formed_at_utc, "delivery formation time")
        if self.authorization_kind not in OWNER_DELIVERY_AUTHORIZATION_KINDS:
            raise DeliveryContractViolation("invalid delivery authorization kind")
        if self.authorization_kind == "approval":
            _sha256(
                self.approval_binding_digest,
                "delivery approval binding digest",
            )
            if (
                self.status_target_active is not None
                or self.status_supersedes_refs is not None
            ):
                raise DeliveryContractViolation(
                    "approval delivery cannot carry status authorization"
                )
        elif self.authorization_kind == "status-transition":
            if self.approval_binding_digest is not None or type(
                self.status_target_active
            ) is not bool:
                raise DeliveryContractViolation(
                    "status delivery requires its active-boundary direction"
                )
            _status_supersession_refs(self.status_supersedes_refs)
        elif (
            self.approval_binding_digest is not None
            or self.status_target_active is not None
            or self.status_supersedes_refs is not None
        ):
            raise DeliveryContractViolation(
                "delivery authorization binding does not match its kind"
            )

        expected_digest = stable_digest(self.semantic_material())
        expected_intent_id = "outbox:" + expected_digest.removeprefix("sha256:")
        key_version = _intent_wire_version(
            self.authorization_kind,
            self.status_supersedes_refs,
        )
        expected_key = (
            f"health-owner-delivery:{key_version}:"
            + expected_digest.removeprefix("sha256:")
        )
        if self.semantic_digest != expected_digest:
            raise DeliveryContractViolation("delivery intent digest mismatch")
        if self.intent_id != expected_intent_id:
            raise DeliveryContractViolation("delivery intent identifier mismatch")
        if self.idempotency_key != expected_key:
            raise DeliveryContractViolation("delivery idempotency key mismatch")

    def semantic_material(self) -> dict[str, object]:
        return _intent_material(
            effect_kind=self.effect_kind,
            owner_id=self.owner_id,
            installation_id=self.installation_id,
            effect_request_id=self.effect_request_id,
            business_fact_ref=self.business_fact_ref,
            business_revision_digest=self.business_revision_digest,
            source_ref=self.source_ref,
            recipient_ref=self.recipient_ref,
            route_id=self.route_id,
            route_generation=self.route_generation,
            payload_ref=self.payload_ref,
            payload_digest=self.payload_digest,
            authorization_kind=self.authorization_kind,
            approval_binding_digest=self.approval_binding_digest,
            status_target_active=self.status_target_active,
            status_supersedes_refs=self.status_supersedes_refs,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "intent_id": self.intent_id,
            "effect_kind": self.effect_kind,
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "effect_request_id": self.effect_request_id,
            "business_fact_ref": self.business_fact_ref,
            "business_revision_digest": self.business_revision_digest,
            "source_ref": self.source_ref,
            "recipient_ref": self.recipient_ref,
            "route_id": self.route_id,
            "route_generation": self.route_generation,
            "payload_ref": self.payload_ref,
            "payload_digest": self.payload_digest,
            "semantic_digest": self.semantic_digest,
            "idempotency_key": self.idempotency_key,
            "formed_at_utc": self.formed_at_utc,
            "authorization_kind": self.authorization_kind,
            "approval_binding_digest": self.approval_binding_digest,
            "status_target_active": self.status_target_active,
            "status_supersedes_refs": (
                None
                if self.status_supersedes_refs is None
                else list(self.status_supersedes_refs)
            ),
        }

    @classmethod
    def from_wire(cls, value: object) -> "OutboxIntent":
        legacy_fields = frozenset(
            {
                "intent_id",
                "effect_kind",
                "owner_id",
                "installation_id",
                "effect_request_id",
                "business_fact_ref",
                "business_revision_digest",
                "source_ref",
                "recipient_ref",
                "route_id",
                "route_generation",
                "payload_ref",
                "payload_digest",
                "semantic_digest",
                "idempotency_key",
                "formed_at_utc",
            }
        )
        current_fields = legacy_fields | {
            "authorization_kind",
            "approval_binding_digest",
            "status_target_active",
        }
        next_fields = current_fields | {"status_supersedes_refs"}
        if type(value) is not dict or frozenset(value) not in {
            legacy_fields,
            current_fields,
            next_fields,
        }:
            raise DeliveryContractViolation("invalid outbox intent")
        fields = dict(value)
        fields.setdefault("authorization_kind", "legacy")
        fields.setdefault("approval_binding_digest", None)
        fields.setdefault("status_target_active", None)
        fields.setdefault("status_supersedes_refs", None)
        if fields["status_supersedes_refs"] is not None:
            if type(fields["status_supersedes_refs"]) is not list:
                raise DeliveryContractViolation(
                    "invalid status supersession references"
                )
            fields["status_supersedes_refs"] = tuple(
                fields["status_supersedes_refs"]
            )
        return cls(**fields)  # type: ignore[arg-type]


def is_status_transition_intent(intent: OutboxIntent) -> bool:
    """Recognize status requests, including structurally verifiable v1 wire."""

    if type(intent) is not OutboxIntent:
        return False
    if intent.authorization_kind == "status-transition":
        return True
    if intent.authorization_kind != "legacy":
        return False
    prefix = "owner-decision:status-transition:"
    if not intent.effect_request_id.startswith(prefix):
        return False
    transition_id = intent.effect_request_id.removeprefix(prefix)
    return bool(transition_id) and (
        intent.business_fact_ref == transition_id
        and intent.source_ref == transition_id
        and intent.payload_ref == "owner-decision-status-payload:" + transition_id
    )


@dataclass(frozen=True)
class OwnerWeixinDestination:
    """The exact configured private Weixin owner route for one send."""

    partner_id: str
    owner_sender_id: str
    conversation_id: str
    channel: str = "weixin"
    entrypoint: str = "health_weixin"

    def __post_init__(self) -> None:
        for value, name in (
            (self.partner_id, "owner delivery partner"),
            (self.owner_sender_id, "owner delivery sender"),
            (self.conversation_id, "owner delivery conversation"),
        ):
            _text(value, name)
        if self.channel != "weixin" or self.entrypoint != "health_weixin":
            raise DeliveryContractViolation("invalid owner Weixin destination")

    def to_wire(self) -> dict[str, object]:
        return {
            "partner_id": self.partner_id,
            "owner_sender_id": self.owner_sender_id,
            "conversation_id": self.conversation_id,
            "channel": self.channel,
            "entrypoint": self.entrypoint,
        }

    @property
    def route_id(self) -> str:
        digest = stable_digest(
            {
                "contract": "owner-weixin-destination-v1",
                **self.to_wire(),
            }
        )
        return "health-weixin-route:v1:" + digest.removeprefix("sha256:")

    @classmethod
    def from_wire(cls, value: object) -> "OwnerWeixinDestination":
        fields = _mapping(
            value,
            frozenset(
                {
                    "partner_id",
                    "owner_sender_id",
                    "conversation_id",
                    "channel",
                    "entrypoint",
                }
            ),
            "owner Weixin destination",
        )
        return cls(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class OwnerDeliverySendIntent:
    """The bounded value Plugin may hand to the Weixin transport."""

    intent_id: str
    attempt_ref: str
    destination: OwnerWeixinDestination
    payload_ref: str
    payload_digest: str
    idempotency_key: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.intent_id, "owner delivery intent identifier"),
            (self.attempt_ref, "owner delivery attempt reference"),
            (self.payload_ref, "owner delivery payload reference"),
            (self.idempotency_key, "owner delivery idempotency key"),
        ):
            _text(value, name)
        if type(self.destination) is not OwnerWeixinDestination:
            raise DeliveryContractViolation("invalid owner Weixin destination")
        _sha256(self.payload_digest, "owner delivery payload digest")

    def to_wire(self) -> dict[str, object]:
        return {
            "intent_id": self.intent_id,
            "attempt_ref": self.attempt_ref,
            "destination": self.destination.to_wire(),
            "payload_ref": self.payload_ref,
            "payload_digest": self.payload_digest,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_wire(cls, value: object) -> "OwnerDeliverySendIntent":
        fields = _mapping(
            value,
            frozenset(
                {
                    "intent_id",
                    "attempt_ref",
                    "destination",
                    "payload_ref",
                    "payload_digest",
                    "idempotency_key",
                }
            ),
            "owner delivery send intent",
        )
        return cls(
            intent_id=fields["intent_id"],  # type: ignore[arg-type]
            attempt_ref=fields["attempt_ref"],  # type: ignore[arg-type]
            destination=OwnerWeixinDestination.from_wire(fields["destination"]),
            payload_ref=fields["payload_ref"],  # type: ignore[arg-type]
            payload_digest=fields["payload_digest"],  # type: ignore[arg-type]
            idempotency_key=fields["idempotency_key"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class OwnerDeliveryCompletion:
    """The complete transport observation Plugin returns to core."""

    intent_id: str
    attempt_ref: str
    status: str
    result_ref: str
    evidence_ref: str
    observed_at_utc: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.intent_id, "owner delivery intent identifier"),
            (self.attempt_ref, "owner delivery attempt reference"),
            (self.result_ref, "owner delivery transport result reference"),
            (self.evidence_ref, "owner delivery transport evidence reference"),
        ):
            _text(value, name)
        if self.status not in OWNER_DELIVERY_TRANSPORT_STATUSES:
            raise DeliveryContractViolation("invalid owner delivery transport status")
        _utc(self.observed_at_utc, "owner delivery observation time")

    def to_wire(self) -> dict[str, object]:
        return {
            "intent_id": self.intent_id,
            "attempt_ref": self.attempt_ref,
            "status": self.status,
            "result_ref": self.result_ref,
            "evidence_ref": self.evidence_ref,
            "observed_at_utc": self.observed_at_utc,
        }

    @classmethod
    def from_wire(cls, value: object) -> "OwnerDeliveryCompletion":
        fields = _mapping(
            value,
            frozenset(
                {
                    "intent_id",
                    "attempt_ref",
                    "status",
                    "result_ref",
                    "evidence_ref",
                    "observed_at_utc",
                }
            ),
            "owner delivery completion",
        )
        return cls(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class OwnerDeliveryTransportResult:
    """The only immediate outcomes an owner-delivery adapter may report."""

    status: str
    result_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if self.status not in OWNER_DELIVERY_TRANSPORT_STATUSES:
            raise DeliveryContractViolation(
                "invalid owner delivery transport status"
            )
        _text(self.result_ref, "owner delivery transport result reference")
        _text(self.evidence_ref, "owner delivery transport evidence reference")

    def to_wire(self) -> dict[str, object]:
        return {
            "status": self.status,
            "result_ref": self.result_ref,
            "evidence_ref": self.evidence_ref,
        }

    @classmethod
    def from_wire(cls, value: object) -> "OwnerDeliveryTransportResult":
        fields = _mapping(
            value,
            frozenset({"status", "result_ref", "evidence_ref"}),
            "owner delivery transport result",
        )
        return cls(**fields)  # type: ignore[arg-type]


@runtime_checkable
class OwnerDeliveryWireAdapter(Protocol):
    """Plugin transport seam; only strict wire values cross this boundary."""

    def send(
        self,
        intent: Mapping[str, object],
        /,
    ) -> Mapping[str, object]:
        """Attempt one serialized Weixin send and return its serialized result."""


@dataclass(frozen=True)
class DeliveryFact:
    """One factual delivery layer; no layer implies another layer."""

    kind: str
    occurred_at_utc: str
    evidence_ref: str
    result_ref: str | None = None
    attempt_ref: str | None = None
    lease_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in DELIVERY_FACT_KINDS:
            raise DeliveryContractViolation("invalid delivery fact kind")
        _utc(self.occurred_at_utc, "delivery fact time")
        _text(self.evidence_ref, "delivery fact evidence reference")
        result_ref = _optional_text(
            self.result_ref, "delivery fact result reference"
        )
        attempt_ref = _optional_text(
            self.attempt_ref, "delivery fact attempt reference"
        )
        lease_id = _optional_text(self.lease_id, "delivery fact lease identifier")
        if self.kind in {"formed", "submitted"}:
            if (
                result_ref is not None
                or attempt_ref is not None
                or lease_id is not None
            ):
                raise DeliveryContractViolation(
                    "pre-attempt delivery fact cannot name an attempt"
                )
        elif self.kind == "attempted":
            if result_ref is not None or attempt_ref is None or lease_id is None:
                raise DeliveryContractViolation(
                    "attempted delivery fact requires attempt and lease"
                )
        elif result_ref is None or attempt_ref is None or lease_id is not None:
            raise DeliveryContractViolation(
                "delivery observation requires result and attempt references"
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "occurred_at_utc": self.occurred_at_utc,
            "evidence_ref": self.evidence_ref,
            "result_ref": self.result_ref,
            "attempt_ref": self.attempt_ref,
            "lease_id": self.lease_id,
        }

    @classmethod
    def from_wire(cls, value: object) -> "DeliveryFact":
        fields = _mapping(
            value,
            frozenset(
                {
                    "kind",
                    "occurred_at_utc",
                    "evidence_ref",
                    "result_ref",
                    "attempt_ref",
                    "lease_id",
                }
            ),
            "delivery fact",
        )
        return cls(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class DeliveryLease:
    """One exclusive, expiring claim to begin an unattempted delivery."""

    lease_id: str
    intent_id: str
    holder_id: str
    acquired_at_utc: str
    expires_at_utc: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.lease_id, "delivery lease identifier"),
            (self.intent_id, "delivery lease intent identifier"),
            (self.holder_id, "delivery lease holder"),
        ):
            _text(value, name)
        acquired = _utc_datetime(
            self.acquired_at_utc, "delivery lease acquisition time"
        )
        expires = _utc_datetime(self.expires_at_utc, "delivery lease expiry time")
        if expires <= acquired:
            raise DeliveryContractViolation(
                "delivery lease must expire after acquisition"
            )

    def is_active(self, observed_at_utc: str) -> bool:
        observed = _utc_datetime(
            observed_at_utc, "delivery lease observation time"
        )
        return (
            _utc_datetime(self.acquired_at_utc, "delivery lease acquisition time")
            <= observed
            < _utc_datetime(self.expires_at_utc, "delivery lease expiry time")
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "lease_id": self.lease_id,
            "intent_id": self.intent_id,
            "holder_id": self.holder_id,
            "acquired_at_utc": self.acquired_at_utc,
            "expires_at_utc": self.expires_at_utc,
        }

    @classmethod
    def from_wire(cls, value: object) -> "DeliveryLease":
        fields = _mapping(
            value,
            frozenset(
                {
                    "lease_id",
                    "intent_id",
                    "holder_id",
                    "acquired_at_utc",
                    "expires_at_utc",
                }
            ),
            "delivery lease",
        )
        return cls(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class OutboxRecord:
    """Submitted outbox intent with append-only delivery facts and leases."""

    intent: OutboxIntent
    facts: tuple[DeliveryFact, ...]
    leases: tuple[DeliveryLease, ...] = ()

    def __post_init__(self) -> None:
        if type(self.intent) is not OutboxIntent:
            raise DeliveryContractViolation("invalid outbox intent")
        if type(self.facts) is not tuple or any(
            type(fact) is not DeliveryFact for fact in self.facts
        ):
            raise DeliveryContractViolation("invalid delivery facts")
        kinds = tuple(fact.kind for fact in self.facts)
        if len(kinds) != len(set(kinds)):
            raise DeliveryContractViolation("duplicate delivery fact kind")
        if kinds != tuple(sorted(kinds, key=_FACT_ORDER.__getitem__)):
            raise DeliveryContractViolation("delivery facts are not layer ordered")
        if "formed" not in kinds or "submitted" not in kinds:
            raise DeliveryContractViolation(
                "submitted outbox record requires formed and submitted facts"
            )
        formed = self.fact("formed")
        submitted = self.fact("submitted")
        if formed.occurred_at_utc != self.intent.formed_at_utc:
            raise DeliveryContractViolation("delivery formation fact mismatch")
        if formed.evidence_ref != f"{self.intent.intent_id}:formed":
            raise DeliveryContractViolation("delivery formation evidence mismatch")
        if submitted.evidence_ref != self.intent.business_fact_ref:
            raise DeliveryContractViolation("delivery submission evidence mismatch")
        if _utc_datetime(
            submitted.occurred_at_utc, "delivery submission time"
        ) < _utc_datetime(formed.occurred_at_utc, "delivery formation time"):
            raise DeliveryContractViolation("delivery submitted before formation")

        if type(self.leases) is not tuple or any(
            type(lease) is not DeliveryLease for lease in self.leases
        ):
            raise DeliveryContractViolation("invalid delivery leases")
        lease_ids = tuple(lease.lease_id for lease in self.leases)
        if len(lease_ids) != len(set(lease_ids)):
            raise DeliveryContractViolation("duplicate delivery lease identifier")
        if any(lease.intent_id != self.intent.intent_id for lease in self.leases):
            raise DeliveryContractViolation("delivery lease authority mismatch")
        sorted_leases = tuple(
            sorted(
                self.leases,
                key=lambda item: (
                    _utc_datetime(
                        item.acquired_at_utc,
                        "delivery lease acquisition time",
                    ),
                    item.lease_id,
                ),
            )
        )
        if self.leases != sorted_leases:
            raise DeliveryContractViolation("delivery leases are not ordered")
        for previous, current in zip(self.leases, self.leases[1:]):
            if _utc_datetime(
                current.acquired_at_utc, "delivery lease acquisition time"
            ) < _utc_datetime(previous.expires_at_utc, "delivery lease expiry time"):
                raise DeliveryContractViolation("overlapping delivery leases")

        attempted = self.optional_fact("attempted")
        observations = tuple(
            fact
            for fact in self.facts
            if fact.kind in DELIVERY_OBSERVATION_KINDS
        )
        if attempted is None and observations:
            raise DeliveryContractViolation(
                "delivery observation exists without an attempt"
            )
        if attempted is not None:
            if attempted.evidence_ref != attempted.attempt_ref:
                raise DeliveryContractViolation(
                    "delivery attempt evidence mismatch"
                )
            lease = next(
                (
                    item
                    for item in self.leases
                    if item.lease_id == attempted.lease_id
                ),
                None,
            )
            if lease is None or not lease.is_active(attempted.occurred_at_utc):
                raise DeliveryContractViolation(
                    "delivery attempt does not hold an active lease"
                )
            attempted_at = _utc_datetime(
                attempted.occurred_at_utc, "delivery attempt time"
            )
            if attempted_at < _utc_datetime(
                submitted.occurred_at_utc, "delivery submission time"
            ):
                raise DeliveryContractViolation("delivery attempted before submission")
            for observation in observations:
                if observation.attempt_ref != attempted.attempt_ref:
                    raise DeliveryContractViolation(
                        "delivery observation attempt mismatch"
                    )
                if _utc_datetime(
                    observation.occurred_at_utc, "delivery observation time"
                ) < attempted_at:
                    raise DeliveryContractViolation(
                        "delivery observation predates attempt"
                    )
            accepted = self.optional_fact("accepted")
            rejected = self.optional_fact("rejected")
            if accepted is not None and rejected is not None:
                raise DeliveryContractViolation(
                    "delivery cannot be both accepted and rejected"
                )
            if rejected is not None and any(
                self.optional_fact(kind) is not None
                for kind in ("delivered", "read")
            ):
                raise DeliveryContractViolation(
                    "rejected delivery cannot be delivered or read"
                )
            self._validate_known_layer_times()
            unknown = self.optional_fact("unknown")
            if unknown is not None:
                unknown_at = _utc_datetime(
                    unknown.occurred_at_utc, "delivery unknown time"
                )
                for kind in ("rejected", "delivered", "read"):
                    known = self.optional_fact(kind)
                    if known is not None and _utc_datetime(
                        known.occurred_at_utc, "delivery observation time"
                    ) <= unknown_at:
                        raise DeliveryContractViolation(
                            "known owner delivery cannot regress to unknown"
                        )

    def _validate_known_layer_times(self) -> None:
        previous: DeliveryFact | None = None
        for kind in ("accepted", "delivered", "read"):
            current = self.optional_fact(kind)
            if current is None:
                continue
            if previous is not None and _utc_datetime(
                current.occurred_at_utc, "delivery observation time"
            ) < _utc_datetime(
                previous.occurred_at_utc, "delivery observation time"
            ):
                raise DeliveryContractViolation(
                    "delivery facts contradict layer chronology"
                )
            previous = current

    @property
    def fact_kinds(self) -> tuple[str, ...]:
        return tuple(fact.kind for fact in self.facts)

    def has_fact(self, kind: str) -> bool:
        if kind not in DELIVERY_FACT_KINDS:
            raise DeliveryContractViolation("invalid delivery fact kind")
        return any(fact.kind == kind for fact in self.facts)

    def optional_fact(self, kind: str) -> DeliveryFact | None:
        if kind not in DELIVERY_FACT_KINDS:
            raise DeliveryContractViolation("invalid delivery fact kind")
        return next((fact for fact in self.facts if fact.kind == kind), None)

    def fact(self, kind: str) -> DeliveryFact:
        fact = self.optional_fact(kind)
        if fact is None:
            raise DeliveryContractViolation("delivery fact does not exist")
        return fact

    @property
    def current_layer(self) -> str:
        unknown = self.optional_fact("unknown")
        resolution = next(
            (
                fact
                for kind in ("read", "delivered", "rejected", "accepted")
                if (fact := self.optional_fact(kind)) is not None
            ),
            None,
        )
        if unknown is not None and (
            resolution is None
            or _utc_datetime(unknown.occurred_at_utc, "delivery unknown time")
            >= _utc_datetime(
                resolution.occurred_at_utc, "delivery observation time"
            )
        ):
            return "unknown"
        if resolution is not None:
            return resolution.kind
        if self.has_fact("attempted"):
            return "attempted"
        return "submitted"

    @property
    def unknown_frozen(self) -> bool:
        return self.current_layer == "unknown"

    @property
    def automatic_retry_allowed(self) -> bool:
        return not self.has_fact("attempted")

    def active_lease(self, observed_at_utc: str) -> DeliveryLease | None:
        active = tuple(
            lease for lease in self.leases if lease.is_active(observed_at_utc)
        )
        if len(active) > 1:  # pragma: no cover - constructor rejects overlap
            raise DeliveryContractViolation("multiple active delivery claims")
        return active[0] if active else None

    def to_wire(self) -> dict[str, object]:
        return {
            "intent": self.intent.to_wire(),
            "facts": [fact.to_wire() for fact in self.facts],
            "leases": [lease.to_wire() for lease in self.leases],
        }

    @classmethod
    def from_wire(cls, value: object) -> "OutboxRecord":
        fields = _mapping(
            value,
            frozenset({"intent", "facts", "leases"}),
            "outbox record",
        )
        if type(fields["facts"]) is not list or type(fields["leases"]) is not list:
            raise DeliveryContractViolation("invalid outbox record collections")
        return cls(
            intent=OutboxIntent.from_wire(fields["intent"]),
            facts=tuple(DeliveryFact.from_wire(item) for item in fields["facts"]),
            leases=tuple(
                DeliveryLease.from_wire(item) for item in fields["leases"]
            ),
        )


@dataclass(frozen=True)
class DeliveryOutboxState:
    """One owner/install authority's submitted delivery values."""

    owner_id: str
    installation_id: str
    version: int
    records: tuple[OutboxRecord, ...]

    def __post_init__(self) -> None:
        _text(self.owner_id, "delivery owner")
        _text(self.installation_id, "delivery installation")
        if type(self.version) is not int or self.version < 0:
            raise DeliveryContractViolation("invalid delivery outbox version")
        if type(self.records) is not tuple or any(
            type(record) is not OutboxRecord for record in self.records
        ):
            raise DeliveryContractViolation("invalid delivery outbox records")
        intent_ids = tuple(record.intent.intent_id for record in self.records)
        if intent_ids != tuple(sorted(intent_ids)) or len(intent_ids) != len(
            set(intent_ids)
        ):
            raise DeliveryContractViolation(
                "outbox records must be uniquely ordered"
            )
        effect_request_ids = tuple(
            record.intent.effect_request_id for record in self.records
        )
        if len(effect_request_ids) != len(set(effect_request_ids)):
            raise DeliveryContractViolation(
                "duplicate delivery effect request identifier"
            )
        if any(
            record.intent.owner_id != self.owner_id
            or record.intent.installation_id != self.installation_id
            for record in self.records
        ):
            raise DeliveryContractViolation("delivery outbox authority mismatch")
        self._validate_status_transition_supersession_graph()

    @classmethod
    def empty(
        cls, owner_id: str, installation_id: str
    ) -> "DeliveryOutboxState":
        return cls(
            owner_id=_text(owner_id, "delivery owner"),
            installation_id=_text(installation_id, "delivery installation"),
            version=0,
            records=(),
        )

    def record(self, intent_id: str) -> OutboxRecord:
        parsed = _text(intent_id, "outbox intent identifier")
        for record in self.records:
            if record.intent.intent_id == parsed:
                return record
        raise DeliveryContractViolation("outbox intent does not exist")

    def _validate_status_transition_supersession_graph(self) -> None:
        by_intent_id = {
            record.intent.intent_id: record for record in self.records
        }
        edges: dict[str, tuple[str, ...]] = {}
        for record in self.records:
            intent = record.intent
            refs = intent.status_supersedes_refs
            if intent.authorization_kind != "status-transition":
                if refs is not None:  # pragma: no cover - intent validates this
                    raise DeliveryContractViolation(
                        "non-status delivery has status supersession references"
                    )
                continue
            if refs is None:
                continue
            edges[intent.intent_id] = refs
            for ref in refs:
                target = by_intent_id.get(ref)
                if target is None:
                    raise DeliveryContractViolation(
                        "status supersession target does not exist"
                    )
                if (
                    target.intent.owner_id != intent.owner_id
                    or target.intent.installation_id != intent.installation_id
                    or not is_status_transition_intent(target.intent)
                ):
                    raise DeliveryContractViolation(
                        "status supersession target authority mismatch"
                    )
                if ref == intent.intent_id:
                    raise DeliveryContractViolation(
                        "status supersession cannot self-reference"
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(intent_id: str) -> None:
            if intent_id in visiting:
                raise DeliveryContractViolation(
                    "status supersession graph contains a cycle"
                )
            if intent_id in visited:
                return
            visiting.add(intent_id)
            for ref in edges.get(intent_id, ()):
                visit(ref)
            visiting.remove(intent_id)
            visited.add(intent_id)

        for intent_id in edges:
            visit(intent_id)

    def status_transition_leaf_intent_ids(self) -> tuple[str, ...]:
        """Return status intents not superseded by a persisted successor."""

        self._validate_status_transition_supersession_graph()
        superseded_ids = {
            ref
            for record in self.records
            if is_status_transition_intent(record.intent)
            and record.intent.status_supersedes_refs is not None
            for ref in record.intent.status_supersedes_refs
        }
        return tuple(
            record.intent.intent_id
            for record in self.records
            if is_status_transition_intent(record.intent)
            and record.intent.intent_id not in superseded_ids
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "version": self.version,
            "records": [record.to_wire() for record in self.records],
        }

    @classmethod
    def from_wire(cls, value: object) -> "DeliveryOutboxState":
        fields = _mapping(
            value,
            frozenset({"owner_id", "installation_id", "version", "records"}),
            "delivery outbox state",
        )
        if type(fields["records"]) is not list:
            raise DeliveryContractViolation("invalid delivery outbox records")
        return cls(
            owner_id=fields["owner_id"],  # type: ignore[arg-type]
            installation_id=fields["installation_id"],  # type: ignore[arg-type]
            version=fields["version"],  # type: ignore[arg-type]
            records=tuple(
                OutboxRecord.from_wire(item) for item in fields["records"]
            ),
        )


@dataclass(frozen=True)
class DeliveryTransition:
    state: DeliveryOutboxState
    intent_id: str
    outcome: str
    replayed: bool = False

    @property
    def record(self) -> OutboxRecord:
        return self.state.record(self.intent_id)


class OwnerDeliveryEngine:
    """Pure transitions for one transactional owner-delivery outbox."""

    @staticmethod
    def form_intent(
        *,
        effect_kind: str,
        owner_id: str,
        installation_id: str,
        effect_request_id: str,
        business_fact_ref: str,
        business_revision_digest: str,
        source_ref: str,
        recipient_ref: str,
        route_id: str,
        route_generation: int,
        payload_ref: str,
        payload_digest: str,
        formed_at_utc: str,
        authorization_kind: str = "legacy",
        approval_binding_digest: str | None = None,
        status_target_active: bool | None = None,
        status_supersedes_refs: tuple[str, ...] | None = None,
    ) -> OutboxIntent:
        if effect_kind == "contact-delivery":
            raise DeliveryContractViolation("contact delivery is not enabled")
        if effect_kind != "owner-delivery":
            raise DeliveryContractViolation("unsupported delivery effect kind")
        if authorization_kind == "status-transition" and status_supersedes_refs is None:
            status_supersedes_refs = ()
        key = owner_delivery_idempotency_key(
            owner_id=owner_id,
            installation_id=installation_id,
            effect_request_id=effect_request_id,
            business_fact_ref=business_fact_ref,
            business_revision_digest=business_revision_digest,
            source_ref=source_ref,
            recipient_ref=recipient_ref,
            route_id=route_id,
            route_generation=route_generation,
            payload_ref=payload_ref,
            payload_digest=payload_digest,
            authorization_kind=authorization_kind,
            approval_binding_digest=approval_binding_digest,
            status_target_active=status_target_active,
            status_supersedes_refs=status_supersedes_refs,
        )
        digest = "sha256:" + key.rsplit(":", 1)[-1]
        return OutboxIntent(
            intent_id="outbox:" + digest.removeprefix("sha256:"),
            effect_kind=effect_kind,
            owner_id=owner_id,
            installation_id=installation_id,
            effect_request_id=effect_request_id,
            business_fact_ref=business_fact_ref,
            business_revision_digest=business_revision_digest,
            source_ref=source_ref,
            recipient_ref=recipient_ref,
            route_id=route_id,
            route_generation=route_generation,
            payload_ref=payload_ref,
            payload_digest=payload_digest,
            semantic_digest=digest,
            idempotency_key=key,
            formed_at_utc=formed_at_utc,
            authorization_kind=authorization_kind,
            approval_binding_digest=approval_binding_digest,
            status_target_active=status_target_active,
            status_supersedes_refs=status_supersedes_refs,
        )

    @staticmethod
    def submit(
        state: DeliveryOutboxState,
        intent: OutboxIntent,
        *,
        submitted_at_utc: str,
    ) -> DeliveryTransition:
        if type(state) is not DeliveryOutboxState:
            raise DeliveryContractViolation("invalid delivery outbox state")
        if type(intent) is not OutboxIntent:
            raise DeliveryContractViolation("invalid outbox intent")
        if (
            intent.owner_id != state.owner_id
            or intent.installation_id != state.installation_id
        ):
            raise DeliveryContractViolation("delivery outbox authority mismatch")
        submitted_at = _utc(submitted_at_utc, "delivery submission time")
        existing = next(
            (
                record
                for record in state.records
                if record.intent.effect_request_id == intent.effect_request_id
            ),
            None,
        )
        if existing is not None:
            if existing.intent.semantic_digest != intent.semantic_digest:
                raise DeliveryContractViolation(
                    "effect request identifier was already submitted"
                )
            return DeliveryTransition(
                state=state,
                intent_id=existing.intent.intent_id,
                outcome="submitted",
                replayed=True,
            )
        if _utc_datetime(
            submitted_at, "delivery submission time"
        ) < _utc_datetime(intent.formed_at_utc, "delivery formation time"):
            raise DeliveryContractViolation("delivery submitted before formation")
        record = OutboxRecord(
            intent=intent,
            facts=(
                DeliveryFact(
                    kind="formed",
                    occurred_at_utc=intent.formed_at_utc,
                    evidence_ref=f"{intent.intent_id}:formed",
                ),
                DeliveryFact(
                    kind="submitted",
                    occurred_at_utc=submitted_at,
                    evidence_ref=intent.business_fact_ref,
                ),
            ),
        )
        next_state = replace(
            state,
            version=state.version + 1,
            records=tuple(
                sorted(
                    state.records + (record,),
                    key=lambda item: item.intent.intent_id,
                )
            ),
        )
        return DeliveryTransition(next_state, intent.intent_id, "submitted")

    @staticmethod
    def claim(
        state: DeliveryOutboxState,
        intent_id: str,
        *,
        holder_id: str,
        lease_id: str,
        acquired_at_utc: str,
        lease_seconds: int = 300,
    ) -> DeliveryTransition:
        if type(state) is not DeliveryOutboxState:
            raise DeliveryContractViolation("invalid delivery outbox state")
        record = state.record(intent_id)
        if record.has_fact("attempted"):
            raise DeliveryContractViolation(
                "delivery is frozen after an attempted effect"
            )
        holder = _text(holder_id, "delivery lease holder")
        lease_identifier = _text(lease_id, "delivery lease identifier")
        acquired = _utc_datetime(
            acquired_at_utc, "delivery lease acquisition time"
        )
        duration = _positive_int(lease_seconds, "delivery lease duration")
        candidate = DeliveryLease(
            lease_id=lease_identifier,
            intent_id=record.intent.intent_id,
            holder_id=holder,
            acquired_at_utc=acquired.isoformat(),
            expires_at_utc=(acquired + timedelta(seconds=duration)).isoformat(),
        )
        prior = next(
            (lease for lease in record.leases if lease.lease_id == lease_identifier),
            None,
        )
        if prior is not None:
            if prior == candidate:
                return DeliveryTransition(
                    state, record.intent.intent_id, "claimed", replayed=True
                )
            raise DeliveryContractViolation(
                "delivery lease identifier was already used"
            )
        if record.active_lease(candidate.acquired_at_utc) is not None:
            raise DeliveryContractViolation(
                "outbox intent has an active delivery claim"
            )
        next_record = replace(record, leases=record.leases + (candidate,))
        next_state = OwnerDeliveryEngine._replace_record(state, next_record)
        return DeliveryTransition(next_state, record.intent.intent_id, "claimed")

    @staticmethod
    def mark_attempted(
        state: DeliveryOutboxState,
        intent_id: str,
        *,
        lease_id: str,
        attempt_ref: str,
        attempted_at_utc: str,
    ) -> DeliveryTransition:
        if type(state) is not DeliveryOutboxState:
            raise DeliveryContractViolation("invalid delivery outbox state")
        record = state.record(intent_id)
        lease_identifier = _text(lease_id, "delivery lease identifier")
        attempt = _text(attempt_ref, "delivery attempt reference")
        attempted_at = _utc(attempted_at_utc, "delivery attempt time")
        fact = DeliveryFact(
            kind="attempted",
            occurred_at_utc=attempted_at,
            evidence_ref=attempt,
            attempt_ref=attempt,
            lease_id=lease_identifier,
        )
        existing = record.optional_fact("attempted")
        if existing is not None:
            if existing == fact:
                return DeliveryTransition(
                    state, record.intent.intent_id, "attempted", replayed=True
                )
            raise DeliveryContractViolation("delivery attempt already recorded")
        lease = next(
            (item for item in record.leases if item.lease_id == lease_identifier),
            None,
        )
        if lease is None or not lease.is_active(attempted_at):
            raise DeliveryContractViolation(
                "delivery attempt requires an active exact lease"
            )
        next_record = replace(
            record,
            facts=OwnerDeliveryEngine._ordered_facts(record.facts + (fact,)),
        )
        next_state = OwnerDeliveryEngine._replace_record(state, next_record)
        return DeliveryTransition(next_state, record.intent.intent_id, "attempted")

    @staticmethod
    def record_observation(
        state: DeliveryOutboxState,
        intent_id: str,
        *,
        kind: str,
        attempt_ref: str,
        result_ref: str,
        evidence_ref: str,
        observed_at_utc: str,
    ) -> DeliveryTransition:
        if type(state) is not DeliveryOutboxState:
            raise DeliveryContractViolation("invalid delivery outbox state")
        if kind not in DELIVERY_OBSERVATION_KINDS:
            raise DeliveryContractViolation("invalid delivery observation kind")
        record = state.record(intent_id)
        attempted = record.optional_fact("attempted")
        attempt = _text(attempt_ref, "delivery attempt reference")
        if attempted is None or attempted.attempt_ref != attempt:
            raise DeliveryContractViolation(
                "delivery observation requires the exact attempted effect"
            )
        fact = DeliveryFact(
            kind=kind,
            occurred_at_utc=_utc(
                observed_at_utc, "delivery observation time"
            ),
            result_ref=_text(
                result_ref, "delivery observation result reference"
            ),
            evidence_ref=_text(
                evidence_ref, "delivery observation evidence reference"
            ),
            attempt_ref=attempt,
        )
        existing = record.optional_fact(kind)
        if existing is not None:
            if existing == fact:
                return DeliveryTransition(
                    state, record.intent.intent_id, kind, replayed=True
                )
            raise DeliveryContractViolation(
                f"{kind} delivery fact already recorded"
            )
        next_record = replace(
            record,
            facts=OwnerDeliveryEngine._ordered_facts(record.facts + (fact,)),
        )
        next_state = OwnerDeliveryEngine._replace_record(state, next_record)
        return DeliveryTransition(next_state, record.intent.intent_id, kind)

    @staticmethod
    def record_transport_result(
        state: DeliveryOutboxState,
        intent_id: str,
        *,
        attempt_ref: str,
        result: OwnerDeliveryTransportResult,
        observed_at_utc: str,
    ) -> DeliveryTransition:
        """Record one narrow adapter response without implying owner receipt."""

        if type(result) is not OwnerDeliveryTransportResult:
            raise DeliveryContractViolation(
                "invalid owner delivery transport result"
            )
        return OwnerDeliveryEngine.record_observation(
            state,
            intent_id,
            kind=result.status,
            attempt_ref=attempt_ref,
            result_ref=result.result_ref,
            evidence_ref=result.evidence_ref,
            observed_at_utc=observed_at_utc,
        )

    @staticmethod
    def _ordered_facts(facts: tuple[DeliveryFact, ...]) -> tuple[DeliveryFact, ...]:
        return tuple(sorted(facts, key=lambda fact: _FACT_ORDER[fact.kind]))

    @staticmethod
    def _replace_record(
        state: DeliveryOutboxState,
        record: OutboxRecord,
    ) -> DeliveryOutboxState:
        return replace(
            state,
            version=state.version + 1,
            records=tuple(
                sorted(
                    (
                        record
                        if item.intent.intent_id == record.intent.intent_id
                        else item
                        for item in state.records
                    ),
                    key=lambda item: item.intent.intent_id,
                )
            ),
        )


__all__ = [
    "CONTACT_DELIVERY_ENABLED",
    "DELIVERY_EFFECT_KINDS",
    "DELIVERY_FACT_KINDS",
    "DELIVERY_OBSERVATION_KINDS",
    "OWNER_DELIVERY_TRANSPORT_STATUSES",
    "DeliveryContractViolation",
    "DeliveryFact",
    "DeliveryLease",
    "DeliveryOutboxState",
    "DeliveryTransition",
    "OutboxIntent",
    "OutboxRecord",
    "OwnerDeliveryCompletion",
    "OwnerDeliveryEngine",
    "OwnerDeliverySendIntent",
    "OwnerDeliveryTransportResult",
    "OwnerDeliveryWireAdapter",
    "OwnerWeixinDestination",
    "owner_delivery_idempotency_key",
    "validate_owner_delivery_observed_at",
]

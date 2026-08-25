"""Sealed, content-free business capability facts for Ticket 114.

This module owns only the capability-fact wire contract.  Status projection is
deliberately a later slice: liveness observations and unverified caller values
must never become product status merely by crossing this boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import InitVar, dataclass
from datetime import datetime, timedelta
from types import MappingProxyType

from .ticket115_contracts import (
    MandatoryDeliveryLedger,
    MandatoryDeliveryRequest,
)


class StatusContractViolation(ValueError):
    """A value cannot cross the sealed business-status fact boundary."""


CORE_STATUS_DOMAINS = (
    "entry",
    "enablement",
    "keys_state",
    "portrait_evidence",
    "tasks",
    "controls",
    "daily_review",
    "model_route",
    "delivery",
    "safety",
    "question_answering",
    "diagnostic_scope",
    "current_head",
)

# This is the production manifest, not a liveness inventory.  Each entry names
# one business authority that core can convert into a sealed fact.  Ticket 115
# and Ticket 116 own several of the corresponding producers; until those
# producers exist their requirements deliberately remain present without a
# fact, which projects ``cannot-confirm``.
PRODUCTION_STATUS_PRODUCER_IDS = MappingProxyType(
    {
        domain: f"health-core.status.{domain}"
        for domain in CORE_STATUS_DOMAINS
    }
)
PRODUCTION_STATUS_PRODUCER_CONTRACT_VERSIONS = MappingProxyType(
    {
        domain: f"{domain}-fact-v1"
        for domain in CORE_STATUS_DOMAINS
    }
)
PRODUCTION_OPTIONAL_STATUS_PRODUCER_IDS = MappingProxyType(
    {"delivery": "health-core.status.delivery-effects"}
)
PRODUCTION_OPTIONAL_STATUS_PRODUCER_CONTRACT_VERSIONS = MappingProxyType(
    {"delivery": "delivery-effect-fact-v1"}
)
PRODUCTION_STATUS_PRODUCER_CONTRACTS = MappingProxyType(
    {
        PRODUCTION_STATUS_PRODUCER_IDS[domain]:
        PRODUCTION_STATUS_PRODUCER_CONTRACT_VERSIONS[domain]
        for domain in CORE_STATUS_DOMAINS
    }
    | {
        PRODUCTION_OPTIONAL_STATUS_PRODUCER_IDS[domain]:
        PRODUCTION_OPTIONAL_STATUS_PRODUCER_CONTRACT_VERSIONS[domain]
        for domain in PRODUCTION_OPTIONAL_STATUS_PRODUCER_IDS
    }
)
FUTURE_STATUS_DOMAINS = frozenset(
    {
        "tasks",
        "daily_review",
        "delivery",
        "safety",
        "diagnostic_scope",
    }
)

_CORE_STATUS_DOMAIN_SET = frozenset(CORE_STATUS_DOMAINS)
_REQUIREDNESS_VALUES = frozenset({"core", "non-core"})
_CAPABILITY_STATES = frozenset(
    {"confirmed-ok", "confirmed-fault", "unknown", "isolated"}
)
_BUSINESS_STATUS_STATES = frozenset({"active", "abnormal", "cannot-confirm"})
_DOMAIN_ORDER = {domain: index for index, domain in enumerate(CORE_STATUS_DOMAINS)}
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_HMAC_SHA256_RE = re.compile(r"hmac-sha256:[0-9a-f]{64}\Z")
_MAX_OPAQUE_TEXT_BYTES = 256
_MIN_SIGNING_KEY_BYTES = 16
_CONSTRUCTION_TOKEN = object()
_ENVELOPE_FIELDS = frozenset(
    {
        "authority_id",
        "domain",
        "requiredness",
        "state",
        "generation",
        "revision_digest",
        "transition_id",
        "producer_id",
        "producer_contract_version",
        "evidence_refs",
        "valid_until_utc",
        "signature",
    }
)


def _opaque_text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or value == "*":
        raise StatusContractViolation(f"invalid {name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise StatusContractViolation(f"invalid {name}") from exc
    if len(encoded) > _MAX_OPAQUE_TEXT_BYTES:
        raise StatusContractViolation(f"invalid {name}")
    return value


def _generation(value: object) -> int:
    if type(value) is not int or value < 1:
        raise StatusContractViolation("invalid capability generation")
    return value


def _sha256(value: object, name: str) -> str:
    text = _opaque_text(value, name)
    if _SHA256_RE.fullmatch(text) is None:
        raise StatusContractViolation(f"invalid {name}")
    return text


def _utc_timestamp(value: object, name: str) -> str:
    text = _opaque_text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise StatusContractViolation(f"invalid {name}") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.isoformat() != text
    ):
        raise StatusContractViolation(f"invalid {name}")
    return text


def _direct_evidence_refs(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise StatusContractViolation("invalid capability evidence references")
    result = tuple(
        _opaque_text(item, "capability evidence reference") for item in value
    )
    if result != value or len(set(result)) != len(result):
        raise StatusContractViolation("invalid capability evidence references")
    return result


def _wire_evidence_refs(value: object) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise StatusContractViolation("invalid capability evidence references")
    result = tuple(
        _opaque_text(item, "capability evidence reference") for item in value
    )
    if list(result) != value or len(set(result)) != len(result):
        raise StatusContractViolation("invalid capability evidence references")
    return result


def _domain(value: object) -> str:
    domain = _opaque_text(value, "capability domain")
    if domain not in _CORE_STATUS_DOMAIN_SET:
        raise StatusContractViolation("unknown capability domain")
    return domain


def _requiredness(value: object) -> str:
    requiredness = _opaque_text(value, "capability requiredness")
    if requiredness not in _REQUIREDNESS_VALUES:
        raise StatusContractViolation("invalid capability requiredness")
    return requiredness


def _state(value: object) -> str:
    state = _opaque_text(value, "capability state")
    if state not in _CAPABILITY_STATES:
        raise StatusContractViolation("invalid capability state")
    return state


def _business_status(value: object) -> str:
    state = _opaque_text(value, "business status")
    if state not in _BUSINESS_STATUS_STATES:
        raise StatusContractViolation("invalid business status")
    return state


def _domain_tuple(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise StatusContractViolation(f"invalid {name}")
    result = tuple(_domain(item) for item in value)
    if result != value or len(set(result)) != len(result):
        raise StatusContractViolation(f"invalid {name}")
    return result


def _reason_codes(value: object) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise StatusContractViolation("invalid status reason codes")
    result = tuple(_opaque_text(item, "status reason code") for item in value)
    if result != value or len(set(result)) != len(result):
        raise StatusContractViolation("invalid status reason codes")
    return result


def _signature(value: object) -> str:
    signature = _opaque_text(value, "capability signature")
    if _HMAC_SHA256_RE.fullmatch(signature) is None:
        raise StatusContractViolation("invalid capability signature")
    return signature


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class CapabilityFactEnvelope:
    """One authenticated, content-free fact emitted through core authority."""

    authority_id: str
    domain: str
    requiredness: str
    state: str
    generation: int
    revision_digest: str
    transition_id: str
    producer_id: str
    producer_contract_version: str
    evidence_refs: tuple[str, ...]
    valid_until_utc: str
    signature: str
    _construction_token: InitVar[object] = None

    def __post_init__(self, _construction_token: object) -> None:
        if _construction_token is not _CONSTRUCTION_TOKEN:
            raise StatusContractViolation(
                "capability envelopes must be constructed by status authority"
            )
        _opaque_text(self.authority_id, "status authority identifier")
        _domain(self.domain)
        _requiredness(self.requiredness)
        _state(self.state)
        _generation(self.generation)
        _sha256(self.revision_digest, "capability revision digest")
        _opaque_text(self.transition_id, "capability transition identifier")
        _opaque_text(self.producer_id, "capability producer identifier")
        _opaque_text(
            self.producer_contract_version,
            "capability producer contract version",
        )
        _direct_evidence_refs(self.evidence_refs)
        _utc_timestamp(self.valid_until_utc, "capability validity time")
        _signature(self.signature)

    def unsigned_wire(self) -> dict[str, object]:
        return {
            "authority_id": self.authority_id,
            "domain": self.domain,
            "requiredness": self.requiredness,
            "state": self.state,
            "generation": self.generation,
            "revision_digest": self.revision_digest,
            "transition_id": self.transition_id,
            "producer_id": self.producer_id,
            "producer_contract_version": self.producer_contract_version,
            "evidence_refs": list(self.evidence_refs),
            "valid_until_utc": self.valid_until_utc,
        }

    def to_wire(self) -> dict[str, object]:
        return {**self.unsigned_wire(), "signature": self.signature}

    @classmethod
    def from_wire(
        cls,
        value: object,
        *,
        authority: "CapabilityFactAuthority",
    ) -> "CapabilityFactEnvelope":
        if type(authority) is not CapabilityFactAuthority:
            raise StatusContractViolation("invalid status authority")
        if type(value) is not dict or frozenset(value) != _ENVELOPE_FIELDS:
            raise StatusContractViolation("invalid capability fact envelope")
        envelope = cls(
            authority_id=_opaque_text(
                value["authority_id"], "status authority identifier"
            ),
            domain=_domain(value["domain"]),
            requiredness=_requiredness(value["requiredness"]),
            state=_state(value["state"]),
            generation=_generation(value["generation"]),
            revision_digest=_sha256(
                value["revision_digest"], "capability revision digest"
            ),
            transition_id=_opaque_text(
                value["transition_id"], "capability transition identifier"
            ),
            producer_id=_opaque_text(
                value["producer_id"], "capability producer identifier"
            ),
            producer_contract_version=_opaque_text(
                value["producer_contract_version"],
                "capability producer contract version",
            ),
            evidence_refs=_wire_evidence_refs(value["evidence_refs"]),
            valid_until_utc=_utc_timestamp(
                value["valid_until_utc"], "capability validity time"
            ),
            signature=_signature(value["signature"]),
            _construction_token=_CONSTRUCTION_TOKEN,
        )
        if not authority.verify(envelope):
            raise StatusContractViolation("unverified capability fact envelope")
        return envelope


class CapabilityFactAuthority:
    """Host-held HMAC authority for registered core fact producers."""

    __slots__ = ("_authority_id", "_producer_contracts", "_signing_key")

    def __init__(
        self,
        *,
        authority_id: str,
        signing_key: bytes,
        producer_contracts: Mapping[str, str],
    ) -> None:
        self._authority_id = _opaque_text(
            authority_id, "status authority identifier"
        )
        if type(signing_key) is not bytes or len(signing_key) < _MIN_SIGNING_KEY_BYTES:
            raise StatusContractViolation("invalid status authority signing key")
        if type(producer_contracts) is not dict or not producer_contracts:
            raise StatusContractViolation("invalid capability producer contracts")
        validated: dict[str, str] = {}
        for producer_id, contract_version in producer_contracts.items():
            producer = _opaque_text(producer_id, "capability producer identifier")
            version = _opaque_text(
                contract_version, "capability producer contract version"
            )
            validated[producer] = version
        self._signing_key = signing_key
        self._producer_contracts = MappingProxyType(validated)

    @property
    def authority_id(self) -> str:
        return self._authority_id

    @property
    def producer_contracts(self) -> Mapping[str, str]:
        return self._producer_contracts

    def _registered_producer(self, producer_id: object, version: object) -> tuple[str, str]:
        producer = _opaque_text(producer_id, "capability producer identifier")
        contract_version = _opaque_text(
            version, "capability producer contract version"
        )
        if self._producer_contracts.get(producer) != contract_version:
            raise StatusContractViolation("unregistered capability producer contract")
        return producer, contract_version

    def _sign(self, unsigned_wire: Mapping[str, object]) -> str:
        return "hmac-sha256:" + hmac.new(
            self._signing_key,
            _canonical_bytes(unsigned_wire),
            hashlib.sha256,
        ).hexdigest()

    def seal(
        self,
        *,
        domain: str,
        requiredness: str,
        state: str,
        generation: int,
        revision_digest: str,
        transition_id: str,
        producer_id: str,
        producer_contract_version: str,
        evidence_refs: tuple[str, ...],
        valid_until_utc: str,
    ) -> CapabilityFactEnvelope:
        validated_producer, validated_contract = self._registered_producer(
            producer_id, producer_contract_version
        )
        unsigned_wire: dict[str, object] = {
            "authority_id": self.authority_id,
            "domain": _domain(domain),
            "requiredness": _requiredness(requiredness),
            "state": _state(state),
            "generation": _generation(generation),
            "revision_digest": _sha256(
                revision_digest, "capability revision digest"
            ),
            "transition_id": _opaque_text(
                transition_id, "capability transition identifier"
            ),
            "producer_id": validated_producer,
            "producer_contract_version": validated_contract,
            "evidence_refs": list(_direct_evidence_refs(evidence_refs)),
            "valid_until_utc": _utc_timestamp(
                valid_until_utc, "capability validity time"
            ),
        }
        return CapabilityFactEnvelope(
            authority_id=self.authority_id,
            domain=unsigned_wire["domain"],
            requiredness=unsigned_wire["requiredness"],
            state=unsigned_wire["state"],
            generation=unsigned_wire["generation"],
            revision_digest=unsigned_wire["revision_digest"],
            transition_id=unsigned_wire["transition_id"],
            producer_id=validated_producer,
            producer_contract_version=validated_contract,
            evidence_refs=tuple(unsigned_wire["evidence_refs"]),
            valid_until_utc=unsigned_wire["valid_until_utc"],
            signature=self._sign(unsigned_wire),
            _construction_token=_CONSTRUCTION_TOKEN,
        )

    def verify(self, envelope: object) -> bool:
        if type(envelope) is not CapabilityFactEnvelope:
            return False
        try:
            if envelope.authority_id != self.authority_id:
                return False
            self._registered_producer(
                envelope.producer_id, envelope.producer_contract_version
            )
            expected = self._sign(envelope.unsigned_wire())
        except (StatusContractViolation, TypeError, UnicodeEncodeError):
            return False
        return hmac.compare_digest(expected, envelope.signature)


@dataclass(frozen=True)
class CapabilityRequirement:
    """One producer contract that must be current for status projection."""

    domain: str
    requiredness: str
    producer_id: str
    producer_contract_version: str
    expected_generation: int
    expected_revision_digest: str
    expected_transition_id: str

    def __post_init__(self) -> None:
        _domain(self.domain)
        _requiredness(self.requiredness)
        _opaque_text(self.producer_id, "capability producer identifier")
        _opaque_text(
            self.producer_contract_version,
            "capability producer contract version",
        )
        _generation(self.expected_generation)
        _sha256(
            self.expected_revision_digest,
            "expected capability revision digest",
        )
        _opaque_text(
            self.expected_transition_id,
            "expected capability transition identifier",
        )

    @property
    def key(self) -> tuple[str, str]:
        return (self.domain, self.producer_id)

    def canonical_wire(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "requiredness": self.requiredness,
            "producer_id": self.producer_id,
            "producer_contract_version": self.producer_contract_version,
            "expected_generation": self.expected_generation,
            "expected_revision_digest": self.expected_revision_digest,
            "expected_transition_id": self.expected_transition_id,
        }


@dataclass(frozen=True)
class StatusProjection:
    """A deterministic, content-free view of current business capability."""

    state: str
    evaluated_at_utc: str
    affected_core_domains: tuple[str, ...]
    isolated_noncore_domains: tuple[str, ...]
    reason_codes: tuple[str, ...]
    fact_set_digest: str

    def __post_init__(self) -> None:
        _business_status(self.state)
        _utc_timestamp(self.evaluated_at_utc, "status evaluation time")
        _domain_tuple(self.affected_core_domains, "affected core domains")
        _domain_tuple(self.isolated_noncore_domains, "isolated non-core domains")
        _reason_codes(self.reason_codes)
        _sha256(self.fact_set_digest, "status fact-set digest")

    def to_storage(self) -> dict[str, object]:
        return {
            "state": self.state,
            "evaluated_at_utc": self.evaluated_at_utc,
            "affected_core_domains": list(self.affected_core_domains),
            "isolated_noncore_domains": list(self.isolated_noncore_domains),
            "reason_codes": list(self.reason_codes),
            "fact_set_digest": self.fact_set_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "StatusProjection":
        fields = frozenset(
            {
                "state",
                "evaluated_at_utc",
                "affected_core_domains",
                "isolated_noncore_domains",
                "reason_codes",
                "fact_set_digest",
            }
        )
        if type(value) is not dict or frozenset(value) != fields:
            raise StatusContractViolation("invalid stored status projection")
        affected = value["affected_core_domains"]
        isolated = value["isolated_noncore_domains"]
        reasons = value["reason_codes"]
        if type(affected) is not list or type(isolated) is not list:
            raise StatusContractViolation("invalid stored status domains")
        if type(reasons) is not list:
            raise StatusContractViolation("invalid stored status reasons")
        return cls(
            state=_business_status(value["state"]),
            evaluated_at_utc=_utc_timestamp(
                value["evaluated_at_utc"],
                "status evaluation time",
            ),
            affected_core_domains=_domain_tuple(
                tuple(affected),
                "affected core domains",
            ),
            isolated_noncore_domains=_domain_tuple(
                tuple(isolated),
                "isolated non-core domains",
            ),
            reason_codes=_reason_codes(tuple(reasons)),
            fact_set_digest=_sha256(
                value["fact_set_digest"],
                "status fact-set digest",
            ),
        )


@dataclass(frozen=True)
class StatusTransition:
    """One deterministic tri-state change; durable dedup remains core-owned."""

    transition_id: str
    previous_state: str
    current_state: str
    projection_digest: str
    affected_core_domains: tuple[str, ...]

    def __post_init__(self) -> None:
        _opaque_text(self.transition_id, "status transition identifier")
        _business_status(self.previous_state)
        _business_status(self.current_state)
        if self.previous_state == self.current_state:
            raise StatusContractViolation("status transition must change state")
        _sha256(self.projection_digest, "status transition projection digest")
        _domain_tuple(self.affected_core_domains, "affected core domains")

    def to_storage(self) -> dict[str, object]:
        return {
            "transition_id": self.transition_id,
            "previous_state": self.previous_state,
            "current_state": self.current_state,
            "projection_digest": self.projection_digest,
            "affected_core_domains": list(self.affected_core_domains),
        }

    @classmethod
    def from_storage(cls, value: object) -> "StatusTransition":
        fields = frozenset(
            {
                "transition_id",
                "previous_state",
                "current_state",
                "projection_digest",
                "affected_core_domains",
            }
        )
        if type(value) is not dict or frozenset(value) != fields:
            raise StatusContractViolation("invalid stored status transition")
        affected = value["affected_core_domains"]
        if type(affected) is not list:
            raise StatusContractViolation("invalid stored transition domains")
        return cls(
            transition_id=_opaque_text(
                value["transition_id"],
                "status transition identifier",
            ),
            previous_state=_business_status(value["previous_state"]),
            current_state=_business_status(value["current_state"]),
            projection_digest=_sha256(
                value["projection_digest"],
                "status transition projection digest",
            ),
            affected_core_domains=_domain_tuple(
                tuple(affected),
                "affected core domains",
            ),
        )

    @classmethod
    def between(
        cls,
        previous: StatusProjection,
        current: StatusProjection,
    ) -> "StatusTransition | None":
        if type(previous) is not StatusProjection or type(current) is not StatusProjection:
            raise StatusContractViolation("invalid status projection transition")
        if previous.state == current.state:
            return None
        transition_wire: dict[str, object] = {
            "previous_state": previous.state,
            "previous_fact_set_digest": previous.fact_set_digest,
            "current_state": current.state,
            "current_fact_set_digest": current.fact_set_digest,
            "affected_core_domains": list(current.affected_core_domains),
        }
        transition_id = "status-transition:" + hashlib.sha256(
            _canonical_bytes(transition_wire)
        ).hexdigest()
        return cls(
            transition_id=transition_id,
            previous_state=previous.state,
            current_state=current.state,
            projection_digest=current.fact_set_digest,
            affected_core_domains=current.affected_core_domains,
        )


@dataclass(frozen=True)
class BusinessStatusResult:
    """Owner-visible status plus at most one newly persisted state change."""

    projection: StatusProjection
    transition: StatusTransition | None
    mandatory_request: MandatoryDeliveryRequest | None = None

    def __post_init__(self) -> None:
        if type(self.projection) is not StatusProjection:
            raise StatusContractViolation("invalid business status projection")
        if self.transition is None:
            if self.mandatory_request is not None:
                raise StatusContractViolation(
                    "mandatory status request requires a new transition"
                )
            return
        if (
            type(self.transition) is not StatusTransition
            or self.transition.current_state != self.projection.state
            or self.transition.projection_digest
            != self.projection.fact_set_digest
            or self.transition.affected_core_domains
            != self.projection.affected_core_domains
        ):
            raise StatusContractViolation("invalid business status transition")
        if self.mandatory_request is not None and (
            type(self.mandatory_request) is not MandatoryDeliveryRequest
            or self.mandatory_request.kind != "status-change"
            or self.mandatory_request.causal_state_id
            != self.transition.transition_id
        ):
            raise StatusContractViolation("invalid mandatory status request")


class StatusProjector:
    """Pure projection over sealed facts and an explicit producer manifest."""

    __slots__ = ("_authority", "_requirements", "_requirements_by_key")

    def __init__(
        self,
        *,
        authority: CapabilityFactAuthority,
        requirements: tuple[CapabilityRequirement, ...],
    ) -> None:
        if type(authority) is not CapabilityFactAuthority:
            raise StatusContractViolation("invalid status authority")
        if type(requirements) is not tuple or not requirements:
            raise StatusContractViolation("invalid capability requirements")
        by_key: dict[tuple[str, str], CapabilityRequirement] = {}
        producer_ids: set[str] = set()
        for requirement in requirements:
            if type(requirement) is not CapabilityRequirement:
                raise StatusContractViolation("invalid capability requirement")
            if requirement.key in by_key or requirement.producer_id in producer_ids:
                raise StatusContractViolation("duplicate capability requirement")
            if (
                authority.producer_contracts.get(requirement.producer_id)
                != requirement.producer_contract_version
            ):
                raise StatusContractViolation(
                    "unregistered capability requirement producer"
                )
            by_key[requirement.key] = requirement
            producer_ids.add(requirement.producer_id)
        core_domains = {
            requirement.domain
            for requirement in requirements
            if requirement.requiredness == "core"
        }
        if core_domains != _CORE_STATUS_DOMAIN_SET:
            raise StatusContractViolation("incomplete core capability requirements")
        self._authority = authority
        self._requirements = tuple(
            sorted(
                requirements,
                key=lambda item: (
                    _DOMAIN_ORDER[item.domain],
                    item.requiredness,
                    item.producer_id,
                ),
            )
        )
        self._requirements_by_key = MappingProxyType(by_key)

    @property
    def requirements(self) -> tuple[CapabilityRequirement, ...]:
        return self._requirements

    @staticmethod
    def _input_fingerprint(value: object) -> bytes:
        try:
            if type(value) is CapabilityFactEnvelope:
                return _canonical_bytes(
                    {"kind": "capability-envelope", "wire": value.to_wire()}
                )
            if type(value) is dict:
                return _canonical_bytes({"kind": "untrusted-wire", "wire": value})
        except (TypeError, ValueError, UnicodeEncodeError):
            pass
        value_type = type(value)
        return _canonical_bytes(
            {
                "kind": "invalid-capability-input",
                "type": f"{value_type.__module__}.{value_type.__qualname__}",
            }
        )

    def _fact_set_digest(
        self,
        fact_fingerprints: set[bytes],
    ) -> str:
        framed: list[bytes] = [
            b"requirement:" + _canonical_bytes(requirement.canonical_wire())
            for requirement in self._requirements
        ]
        framed.extend(b"fact:" + item for item in fact_fingerprints)
        digest = hashlib.sha256()
        for item in sorted(framed):
            digest.update(len(item).to_bytes(8, "big"))
            digest.update(item)
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _reason(
        requirement: CapabilityRequirement,
        reason: str,
    ) -> str:
        return f"{requirement.domain}:{requirement.producer_id}:{reason}"

    def project(
        self,
        envelopes: object,
        *,
        evaluated_at_utc: str,
    ) -> StatusProjection:
        evaluated_text = _utc_timestamp(
            evaluated_at_utc,
            "status evaluation time",
        )
        evaluated_at = datetime.fromisoformat(evaluated_text)
        try:
            facts = tuple(envelopes)  # type: ignore[arg-type]
        except TypeError:
            facts = ()
            unreadable_collection = True
        else:
            unreadable_collection = False

        candidates: dict[
            tuple[str, str],
            dict[bytes, CapabilityFactEnvelope],
        ] = {requirement.key: {} for requirement in self._requirements}
        requirement_issues: dict[tuple[str, str], set[str]] = {
            requirement.key: set() for requirement in self._requirements
        }
        same_generation_variants: dict[
            tuple[str, str],
            set[tuple[str, str]],
        ] = {requirement.key: set() for requirement in self._requirements}
        global_issues: set[str] = set()
        if unreadable_collection:
            global_issues.add("invalid-fact-collection")
        fingerprints: set[bytes] = set()

        for fact in facts:
            fingerprint = self._input_fingerprint(fact)
            fingerprints.add(fingerprint)
            if type(fact) is not CapabilityFactEnvelope:
                global_issues.add("invalid-envelope")
                continue
            raw_key = (fact.domain, fact.producer_id)
            requirement = self._requirements_by_key.get(raw_key)
            if (
                requirement is not None
                and fact.producer_contract_version
                != requirement.producer_contract_version
            ):
                requirement_issues[requirement.key].add(
                    "producer-contract-mismatch"
                )
                continue
            if (
                requirement is not None
                and fact.requiredness != requirement.requiredness
            ):
                requirement_issues[requirement.key].add("requiredness-mismatch")
                continue
            if not self._authority.verify(fact):
                if requirement is None:
                    global_issues.add("unverified-envelope")
                else:
                    requirement_issues[requirement.key].add("unverified-envelope")
                continue
            if requirement is None:
                global_issues.add("unexpected-producer")
                continue
            if fact.generation != requirement.expected_generation:
                requirement_issues[requirement.key].add("generation-mismatch")
                continue
            if datetime.fromisoformat(fact.valid_until_utc) <= evaluated_at:
                requirement_issues[requirement.key].add("expired")
                continue
            same_generation_variants[requirement.key].add(
                (fact.revision_digest, fact.transition_id)
            )
            if fact.revision_digest != requirement.expected_revision_digest:
                requirement_issues[requirement.key].add(
                    "current-revision-mismatch"
                )
                continue
            if fact.transition_id != requirement.expected_transition_id:
                requirement_issues[requirement.key].add(
                    "current-transition-mismatch"
                )
                continue
            candidates[requirement.key][fingerprint] = fact

        has_confirmed_fault = False
        has_uncertainty = bool(global_issues)
        affected_core: set[str] = set()
        isolated_noncore: set[str] = set()
        reasons: set[str] = {f"global:{reason}" for reason in global_issues}

        if global_issues:
            affected_core.update(CORE_STATUS_DOMAINS)

        for requirement in self._requirements:
            issues = requirement_issues[requirement.key]
            matched = candidates[requirement.key]
            if (
                len(matched) > 1
                or len(same_generation_variants[requirement.key]) > 1
            ):
                issues.add("revision-conflict")

            if issues:
                reasons.update(self._reason(requirement, issue) for issue in issues)
                has_uncertainty = True
                if requirement.requiredness == "core":
                    affected_core.add(requirement.domain)

            if len(matched) != 1:
                if len(matched) == 0 and not issues and requirement.requiredness == "core":
                    reasons.add(self._reason(requirement, "missing"))
                    has_uncertainty = True
                    affected_core.add(requirement.domain)
                continue

            fact = next(iter(matched.values()))
            if requirement.requiredness == "non-core":
                if fact.state == "isolated":
                    isolated_noncore.add(requirement.domain)
                    reasons.add(self._reason(requirement, "isolated"))
                elif fact.state == "confirmed-fault":
                    has_confirmed_fault = True
                    reasons.add(self._reason(requirement, "confirmed-fault"))
                continue

            if fact.state == "confirmed-ok":
                continue
            affected_core.add(requirement.domain)
            if fact.state in {"confirmed-fault", "isolated"}:
                has_confirmed_fault = True
                reasons.add(self._reason(requirement, fact.state))
            else:
                has_uncertainty = True
                reasons.add(self._reason(requirement, "unknown"))

        if has_confirmed_fault:
            state = "abnormal"
        elif has_uncertainty:
            state = "cannot-confirm"
        else:
            state = "active"

        ordered_affected = tuple(
            domain for domain in CORE_STATUS_DOMAINS if domain in affected_core
        )
        ordered_isolated = tuple(
            domain for domain in CORE_STATUS_DOMAINS if domain in isolated_noncore
        )
        return StatusProjection(
            state=state,
            evaluated_at_utc=evaluated_text,
            affected_core_domains=ordered_affected,
            isolated_noncore_domains=ordered_isolated,
            reason_codes=tuple(sorted(reasons)),
            fact_set_digest=self._fact_set_digest(fingerprints),
        )

    def transition(
        self,
        previous: StatusProjection,
        current: StatusProjection,
    ) -> StatusTransition | None:
        return StatusTransition.between(previous, current)

    @staticmethod
    def mandatory_delivery_request(
        transition: StatusTransition | None,
        *,
        generation: int,
    ) -> MandatoryDeliveryRequest | None:
        if transition is None:
            return None
        request = MandatoryDeliveryRequest(
            request_id="mandatory:" + transition.transition_id,
            kind="status-change",
            causal_state_id=transition.transition_id,
            generation=generation,
            reason_code=(
                f"{transition.previous_state}-to-{transition.current_state}"
            ),
        )
        _, issued = MandatoryDeliveryLedger().issue(request)
        return request if issued else None

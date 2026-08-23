"""Strong comparability identities for the three health-evidence types.

These values describe *how* records may be compared.  They deliberately do
not contain an evidence claim, a measurement value, or task/portrait state.
That keeps a future ``EvidenceSeriesKey`` capable of holding one immutable
profile without turning the key into a second evidence card.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from .authority import AuthorityValidationError, validate_opaque_text
from .initialization import stable_digest


EVIDENCE_PROFILE_SCHEMA_VERSION = "evidence-profile-v1"
_WIRE_FIELDS = frozenset({"schema_version", "kind", "fields", "digest"})

PersonalObservationBasis: TypeAlias = Literal[
    "owner-statement",
    "measurement",
    "reported-clinician-conclusion",
]
TaskProcessFactKind: TypeAlias = Literal["stage", "delivery", "acceptance"]


def _meaningful_text(value: object, name: str) -> str:
    """Validate a short semantic label, including its visible boundaries."""

    text = validate_opaque_text(value, name)
    if text != text.strip():
        raise AuthorityValidationError(f"invalid {name}")
    return text


def _exact_fields(
    value: object,
    expected: frozenset[str],
    name: str,
) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected:
        raise AuthorityValidationError(f"invalid {name}")
    return value


def _profile_payload(
    kind: str,
    fields: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": EVIDENCE_PROFILE_SCHEMA_VERSION,
        "kind": kind,
        "fields": fields,
    }


def _profile_wire(kind: str, fields: dict[str, object]) -> dict[str, object]:
    payload = _profile_payload(kind, fields)
    return {**payload, "digest": stable_digest(payload)}


@dataclass(frozen=True, slots=True)
class PersonalEvidenceProfile:
    """Comparability identity for one personal-health evidence series."""

    observation_basis: PersonalObservationBasis
    measurement_method: str | None = None
    measurement_unit: str | None = None

    def __post_init__(self) -> None:
        if type(self.observation_basis) is not str or self.observation_basis not in {
            "owner-statement",
            "measurement",
            "reported-clinician-conclusion",
        }:
            raise AuthorityValidationError("invalid personal observation basis")
        measurement_fields = (self.measurement_method, self.measurement_unit)
        if self.observation_basis == "measurement":
            if any(value is None for value in measurement_fields):
                raise AuthorityValidationError(
                    "personal measurement profile requires method and unit"
                )
            _meaningful_text(self.measurement_method, "measurement method")
            _meaningful_text(self.measurement_unit, "measurement unit")
        elif any(value is not None for value in measurement_fields):
            raise AuthorityValidationError(
                "non-measurement personal profile cannot carry method or unit"
            )

    @property
    def kind(self) -> Literal["personal-health"]:
        return "personal-health"

    def _fields(self) -> dict[str, object]:
        return {
            "observation_basis": self.observation_basis,
            "measurement_method": self.measurement_method,
            "measurement_unit": self.measurement_unit,
        }

    @property
    def digest(self) -> str:
        return stable_digest(_profile_payload(self.kind, self._fields()))

    def to_wire(self) -> dict[str, object]:
        return _profile_wire(self.kind, self._fields())

    @classmethod
    def _from_fields(cls, value: object) -> "PersonalEvidenceProfile":
        fields = _exact_fields(
            value,
            frozenset(
                {"observation_basis", "measurement_method", "measurement_unit"}
            ),
            "personal evidence profile fields",
        )
        return cls(
            observation_basis=fields["observation_basis"],  # type: ignore[arg-type]
            measurement_method=fields["measurement_method"],  # type: ignore[arg-type]
            measurement_unit=fields["measurement_unit"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class AuthoritativeKnowledgeProfile:
    """Comparability identity for one authoritative-knowledge series."""

    publisher: str
    applicable_population: str
    validity_boundary: str
    source_nature: str

    def __post_init__(self) -> None:
        _meaningful_text(self.publisher, "knowledge publisher")
        _meaningful_text(
            self.applicable_population,
            "knowledge applicable population",
        )
        _meaningful_text(self.validity_boundary, "knowledge validity boundary")
        _meaningful_text(self.source_nature, "knowledge source nature")

    @property
    def kind(self) -> Literal["authoritative-knowledge"]:
        return "authoritative-knowledge"

    def _fields(self) -> dict[str, object]:
        return {
            "publisher": self.publisher,
            "applicable_population": self.applicable_population,
            "validity_boundary": self.validity_boundary,
            "source_nature": self.source_nature,
        }

    @property
    def digest(self) -> str:
        return stable_digest(_profile_payload(self.kind, self._fields()))

    def to_wire(self) -> dict[str, object]:
        return _profile_wire(self.kind, self._fields())

    @classmethod
    def _from_fields(cls, value: object) -> "AuthoritativeKnowledgeProfile":
        fields = _exact_fields(
            value,
            frozenset(
                {
                    "publisher",
                    "applicable_population",
                    "validity_boundary",
                    "source_nature",
                }
            ),
            "authoritative knowledge profile fields",
        )
        return cls(
            publisher=fields["publisher"],  # type: ignore[arg-type]
            applicable_population=fields["applicable_population"],  # type: ignore[arg-type]
            validity_boundary=fields["validity_boundary"],  # type: ignore[arg-type]
            source_nature=fields["source_nature"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class TaskProcessProfile:
    """Comparability identity for one task-process evidence series."""

    task_id: str
    process_fact_kind: TaskProcessFactKind
    ledger_ref: str
    source_nature: str

    def __post_init__(self) -> None:
        _meaningful_text(self.task_id, "task identifier")
        if type(self.process_fact_kind) is not str or self.process_fact_kind not in {
            "stage",
            "delivery",
            "acceptance",
        }:
            raise AuthorityValidationError("invalid task process fact kind")
        _meaningful_text(self.ledger_ref, "task process ledger reference")
        _meaningful_text(self.source_nature, "task process source nature")

    @property
    def kind(self) -> Literal["task-process"]:
        return "task-process"

    def _fields(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "process_fact_kind": self.process_fact_kind,
            "ledger_ref": self.ledger_ref,
            "source_nature": self.source_nature,
        }

    @property
    def digest(self) -> str:
        return stable_digest(_profile_payload(self.kind, self._fields()))

    def to_wire(self) -> dict[str, object]:
        return _profile_wire(self.kind, self._fields())

    @classmethod
    def _from_fields(cls, value: object) -> "TaskProcessProfile":
        fields = _exact_fields(
            value,
            frozenset(
                {"task_id", "process_fact_kind", "ledger_ref", "source_nature"}
            ),
            "task process profile fields",
        )
        return cls(
            task_id=fields["task_id"],  # type: ignore[arg-type]
            process_fact_kind=fields["process_fact_kind"],  # type: ignore[arg-type]
            ledger_ref=fields["ledger_ref"],  # type: ignore[arg-type]
            source_nature=fields["source_nature"],  # type: ignore[arg-type]
        )


EvidenceProfile: TypeAlias = (
    PersonalEvidenceProfile
    | AuthoritativeKnowledgeProfile
    | TaskProcessProfile
)


def profile_from_wire(value: object) -> EvidenceProfile:
    """Parse one exact self-identifying profile and verify its digest."""

    outer = _exact_fields(value, _WIRE_FIELDS, "evidence profile wire")
    if type(outer["schema_version"]) is not str or (
        outer["schema_version"] != EVIDENCE_PROFILE_SCHEMA_VERSION
    ):
        raise AuthorityValidationError("invalid evidence profile schema version")
    kind = outer["kind"]
    if type(kind) is not str:
        raise AuthorityValidationError("invalid evidence profile kind")
    if kind == "personal-health":
        profile: EvidenceProfile = PersonalEvidenceProfile._from_fields(
            outer["fields"]
        )
    elif kind == "authoritative-knowledge":
        profile = AuthoritativeKnowledgeProfile._from_fields(outer["fields"])
    elif kind == "task-process":
        profile = TaskProcessProfile._from_fields(outer["fields"])
    else:
        raise AuthorityValidationError("invalid evidence profile kind")
    if type(outer["digest"]) is not str or outer["digest"] != profile.digest:
        raise AuthorityValidationError("evidence profile digest mismatch")
    return profile


def profile_for_personal(
    *,
    observation_basis: PersonalObservationBasis,
    measurement_method: str | None = None,
    measurement_unit: str | None = None,
) -> PersonalEvidenceProfile:
    return PersonalEvidenceProfile(
        observation_basis=observation_basis,
        measurement_method=measurement_method,
        measurement_unit=measurement_unit,
    )


def profile_for_authoritative_knowledge(
    *,
    publisher: str,
    applicable_population: str,
    validity_boundary: str,
    source_nature: str,
) -> AuthoritativeKnowledgeProfile:
    return AuthoritativeKnowledgeProfile(
        publisher=publisher,
        applicable_population=applicable_population,
        validity_boundary=validity_boundary,
        source_nature=source_nature,
    )


def profile_for_task_process(
    *,
    task_id: str,
    process_fact_kind: TaskProcessFactKind,
    ledger_ref: str,
    source_nature: str,
) -> TaskProcessProfile:
    return TaskProcessProfile(
        task_id=task_id,
        process_fact_kind=process_fact_kind,
        ledger_ref=ledger_ref,
        source_nature=source_nature,
    )


__all__ = [
    "EVIDENCE_PROFILE_SCHEMA_VERSION",
    "AuthoritativeKnowledgeProfile",
    "EvidenceProfile",
    "PersonalEvidenceProfile",
    "PersonalObservationBasis",
    "TaskProcessFactKind",
    "TaskProcessProfile",
    "profile_for_authoritative_knowledge",
    "profile_for_personal",
    "profile_for_task_process",
    "profile_from_wire",
]

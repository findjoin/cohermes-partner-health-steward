"""Typed post-initialization routing and seven-Skill coordination.

The runtime forms candidates; health-core verifies their complete Skill-use
chain before atomically applying any evidence, portrait, or reply intent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .admission import SourceEnvelope
from .answer_resolution import ModelAnswerResolution, render_failed_closed
from .authority import AuthorityValidationError, validate_opaque_text
from .evidence_profile import (
    AuthoritativeKnowledgeProfile,
    EvidenceProfile,
    PersonalEvidenceProfile,
    TaskProcessProfile,
    profile_from_wire,
)
from .initialization import stable_digest
from .portrait_schema import (
    FIRST_RELEASE_PORTRAIT_SCHEMA,
    PORTRAIT_DOMAIN_REFS,
    PORTRAIT_SCHEMA_VERSION,
    PORTRAIT_TOPIC_REFS,
    PortraitSchemaValidationError,
    validate_topic_ref,
)


DAILY_HEALTH_SKILL_NAMES = (
    "health-steward", "health-settings", "health-portrait",
    "health-evidence", "health-owner-inquiry", "health-literature",
)
COARSE_CLASSIFICATIONS = frozenset({"ordinary", "health", "mixed", "uncertain"})
EVIDENCE_TYPE_ORDER = (
    "personal-health",
    "authoritative-knowledge",
    "task-process",
)
EVIDENCE_TYPES = frozenset(EVIDENCE_TYPE_ORDER)
DAILY_SKILL_ROLES = {
    "health-steward": "A", "health-settings": "A",
    "health-portrait": "B", "health-evidence": "B",
    "health-owner-inquiry": "B", "health-literature": "B",
}
DAILY_SKILL_ACTIONS = frozenset(
    {
        "plan",
        "evaluate-evidence",
        "maintain-portrait",
        "form-settings-candidate",
        "form-owner-question",
        "find-literature",
        "resolve",
    }
)
REPLY_ATOM_KINDS = (
    "direct-result",
    "record-result",
    "limitation",
    "next-step",
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_HMAC_RE = re.compile(r"hmac-sha256:[0-9a-f]{64}\Z")
# One integrated owner reply may contain several 60-character mobile display
# atoms plus disclosures.  4096 UTF-8 bytes is the protocol payload budget for
# that one reply intent; it is not an evidence or portrait retention limit.
MAX_OWNER_REPLY_BYTES = 4096


def _mapping(value: object, fields: frozenset[str], name: str) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise AuthorityValidationError(f"invalid {name}")
    return value


def _owner_reply_text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise AuthorityValidationError(f"invalid {name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AuthorityValidationError(f"invalid {name}") from exc
    if len(encoded) > MAX_OWNER_REPLY_BYTES:
        raise AuthorityValidationError(f"invalid {name}")
    return value


def _texts(value: object, name: str, *, empty: bool = False) -> tuple[str, ...]:
    if type(value) is not tuple or (not value and not empty):
        raise AuthorityValidationError(f"invalid {name}")
    result = tuple(validate_opaque_text(item, name) for item in value)
    if result != value or len(set(result)) != len(result):
        raise AuthorityValidationError(f"invalid {name}")
    return result


def _stored_texts(value: object, name: str, *, empty: bool = False) -> tuple[str, ...]:
    if type(value) is not list:
        raise AuthorityValidationError(f"invalid {name}")
    result = tuple(validate_opaque_text(item, name) for item in value)
    if (not result and not empty) or list(result) != value or len(set(result)) != len(result):
        raise AuthorityValidationError(f"invalid {name}")
    return result


def _sha(value: object, name: str) -> str:
    text = validate_opaque_text(value, name)
    if _SHA256_RE.fullmatch(text) is None:
        raise AuthorityValidationError(f"invalid {name}")
    return text


def _time(value: object, name: str) -> str:
    text = validate_opaque_text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AuthorityValidationError(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError(f"invalid {name}")
    return text


def _occurrence_time(value: str, certainty: str) -> datetime | None:
    if certainty == "uncertain":
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AuthorityValidationError("known evidence occurrence is not orderable") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError("known evidence occurrence requires a timezone")
    return parsed.astimezone(timezone.utc)


def _topic(value: object) -> str:
    try:
        return validate_topic_ref(value)
    except PortraitSchemaValidationError as exc:
        # The coordination boundary exposes one validation vocabulary even
        # though the closed taxonomy is owned by portrait_schema.
        raise AuthorityValidationError("invalid portrait topic reference") from exc


def _display_texts(value: object, name: str) -> tuple[str, ...]:
    result = _texts(value, name, empty=True)
    if len(result) > 3 or any(len(item) > 60 for item in result):
        # The 60-character display budget requires a faithful rewrite; values
        # are never sliced and then treated as the underlying understanding.
        raise AuthorityValidationError(f"invalid {name}: faithful rewrite required")
    return result


def _aligned_periods(
    value: object,
    expected_count: int,
    name: str,
) -> tuple[str, ...]:
    """Validate one structured period per displayed conclusion.

    Unlike ``_texts``, duplicate periods are valid: several distinct current
    understandings may apply to the same period.
    """

    if type(value) is not tuple or len(value) != expected_count:
        raise AuthorityValidationError(f"invalid {name}")
    result = tuple(validate_opaque_text(item, name) for item in value)
    if result != value:
        raise AuthorityValidationError(f"invalid {name}")
    return result


def _stored_aligned_periods(
    value: object,
    expected_count: int,
    name: str,
) -> tuple[str, ...]:
    if type(value) is not list or len(value) != expected_count:
        raise AuthorityValidationError(f"invalid {name}")
    result = tuple(validate_opaque_text(item, name) for item in value)
    if list(result) != value:
        raise AuthorityValidationError(f"invalid {name}")
    return result


class CoarseMessageRouter:
    """Use only the current body; failures conservatively stay in health."""

    def __init__(self, classifier: Callable[[str, str], str]) -> None:
        if not callable(classifier):
            raise AuthorityValidationError("invalid coarse message classifier")
        self._classifier = classifier

    def classify(self, body: str, requested_capability: str) -> str:
        if type(body) is not str:
            raise AuthorityValidationError("invalid message body")
        validate_opaque_text(requested_capability, "requested capability")
        try:
            result = self._classifier(body, requested_capability)
        except Exception:
            return "uncertain"
        return result if type(result) is str and result in COARSE_CLASSIFICATIONS else "uncertain"


@dataclass(frozen=True)
class EvidenceSeriesKey:
    """The complete physical comparability identity for one evidence sequence."""

    evidence_type: str
    atomic_dimension: str
    comparability_profile: EvidenceProfile
    period_kind: str
    unit: str | None = None

    def __post_init__(self) -> None:
        if self.evidence_type not in EVIDENCE_TYPES:
            raise AuthorityValidationError("invalid evidence series type")
        validate_opaque_text(self.atomic_dimension, "evidence atomic dimension")
        if type(self.comparability_profile) not in {
            PersonalEvidenceProfile,
            AuthoritativeKnowledgeProfile,
            TaskProcessProfile,
        }:
            raise AuthorityValidationError("invalid evidence comparability profile")
        if self.comparability_profile.kind != self.evidence_type:
            raise AuthorityValidationError("evidence profile type mismatch")
        validate_opaque_text(self.period_kind, "evidence period kind")
        if self.unit is not None:
            validate_opaque_text(self.unit, "evidence measurement unit")
        if self.evidence_type != "personal-health" and self.unit is not None:
            raise AuthorityValidationError("only personal measurements may carry a unit")
        if (
            type(self.comparability_profile) is PersonalEvidenceProfile
            and self.unit != self.comparability_profile.measurement_unit
        ):
            raise AuthorityValidationError("personal evidence profile unit mismatch")

    def to_storage(self) -> dict[str, object]:
        return {
            "evidence_type": self.evidence_type,
            "atomic_dimension": self.atomic_dimension,
            "comparability_profile": self.comparability_profile.to_wire(),
            "period_kind": self.period_kind,
            "unit": self.unit,
        }

    @classmethod
    def from_storage(cls, value: object) -> "EvidenceSeriesKey":
        fields = _mapping(
            value,
            frozenset(
                {
                    "evidence_type",
                    "atomic_dimension",
                    "comparability_profile",
                    "period_kind",
                    "unit",
                }
            ),
            "evidence series key",
        )
        return cls(
            evidence_type=fields["evidence_type"],
            atomic_dimension=fields["atomic_dimension"],
            comparability_profile=profile_from_wire(fields["comparability_profile"]),
            period_kind=fields["period_kind"],
            unit=fields["unit"],
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class PersonalHealthFields:
    observation_kind: str
    measurement_value: str | None = None
    measurement_unit: str | None = None
    measurement_method: str | None = None

    def __post_init__(self) -> None:
        if self.observation_kind not in {
            "owner-statement",
            "measurement",
            "reported-clinician-conclusion",
            "historical-summary",
        }:
            raise AuthorityValidationError("invalid personal evidence basis")
        measurement = (
            self.measurement_value,
            self.measurement_unit,
            self.measurement_method,
        )
        if self.observation_kind == "measurement":
            if any(value is None for value in measurement):
                raise AuthorityValidationError(
                    "personal measurement requires value, unit, and method"
                )
            for value, name in zip(
                measurement,
                ("measurement value", "measurement unit", "measurement method"),
            ):
                validate_opaque_text(value, name)
            try:
                parsed = Decimal(self.measurement_value)  # type: ignore[arg-type]
            except (InvalidOperation, ValueError) as exc:
                raise AuthorityValidationError("invalid measurement value") from exc
            if not parsed.is_finite():
                raise AuthorityValidationError("invalid measurement value")
        elif any(value is not None for value in measurement):
            raise AuthorityValidationError(
                "non-measurement personal evidence cannot carry measurement fields"
            )

    def to_storage(self) -> dict[str, object]:
        return {
            "observation_kind": self.observation_kind,
            "measurement_value": self.measurement_value,
            "measurement_unit": self.measurement_unit,
            "measurement_method": self.measurement_method,
        }

    @classmethod
    def from_storage(cls, value: object) -> "PersonalHealthFields":
        fields = _mapping(
            value,
            frozenset(
                {
                    "observation_kind",
                    "measurement_value",
                    "measurement_unit",
                    "measurement_method",
                }
            ),
            "personal health fields",
        )
        return cls(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class AuthoritativeKnowledgeFields:
    publisher: str
    material_version: str
    applicable_population: str
    validity_boundary: str
    record_kind: str = "detail"

    def __post_init__(self) -> None:
        for value, name in (
            (self.publisher, "knowledge publisher"),
            (self.material_version, "knowledge material version"),
            (self.applicable_population, "knowledge applicable population"),
            (self.validity_boundary, "knowledge validity boundary"),
        ):
            validate_opaque_text(value, name)
        if self.record_kind not in {"detail", "historical-summary"}:
            raise AuthorityValidationError("invalid knowledge record kind")

    def to_storage(self) -> dict[str, object]:
        return {
            "publisher": self.publisher,
            "material_version": self.material_version,
            "applicable_population": self.applicable_population,
            "validity_boundary": self.validity_boundary,
            "record_kind": self.record_kind,
        }

    @classmethod
    def from_storage(cls, value: object) -> "AuthoritativeKnowledgeFields":
        fields = _mapping(
            value,
            frozenset(
                {
                    "publisher",
                    "material_version",
                    "applicable_population",
                    "validity_boundary",
                    "record_kind",
                }
            ),
            "authoritative knowledge fields",
        )
        return cls(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class TaskProcessFields:
    task_id: str
    actual_stage: str
    process_fact_kind: str
    process_fact_ref: str
    record_kind: str = "detail"

    def __post_init__(self) -> None:
        validate_opaque_text(self.task_id, "task identifier")
        validate_opaque_text(self.actual_stage, "actual task stage")
        if self.process_fact_kind not in {"stage", "delivery", "acceptance"}:
            raise AuthorityValidationError("invalid task process fact kind")
        validate_opaque_text(self.process_fact_ref, "task process fact reference")
        if self.record_kind not in {"detail", "historical-summary"}:
            raise AuthorityValidationError("invalid task process record kind")

    def to_storage(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "actual_stage": self.actual_stage,
            "process_fact_kind": self.process_fact_kind,
            "process_fact_ref": self.process_fact_ref,
            "record_kind": self.record_kind,
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskProcessFields":
        fields = _mapping(
            value,
            frozenset(
                {
                    "task_id",
                    "actual_stage",
                    "process_fact_kind",
                    "process_fact_ref",
                    "record_kind",
                }
            ),
            "task process fields",
        )
        return cls(**fields)  # type: ignore[arg-type]


EvidenceSpecificFields = (
    PersonalHealthFields | AuthoritativeKnowledgeFields | TaskProcessFields
)


def _specific_fields_to_storage(value: EvidenceSpecificFields) -> dict[str, object]:
    if type(value) is PersonalHealthFields:
        kind = "personal-health"
    elif type(value) is AuthoritativeKnowledgeFields:
        kind = "authoritative-knowledge"
    elif type(value) is TaskProcessFields:
        kind = "task-process"
    else:
        raise AuthorityValidationError("invalid evidence-specific fields")
    return {"kind": kind, "fields": value.to_storage()}


def _specific_fields_from_storage(value: object) -> EvidenceSpecificFields:
    outer = _mapping(
        value,
        frozenset({"kind", "fields"}),
        "evidence-specific fields",
    )
    kind = outer["kind"]
    if kind == "personal-health":
        return PersonalHealthFields.from_storage(outer["fields"])
    if kind == "authoritative-knowledge":
        return AuthoritativeKnowledgeFields.from_storage(outer["fields"])
    if kind == "task-process":
        return TaskProcessFields.from_storage(outer["fields"])
    raise AuthorityValidationError("invalid evidence-specific field kind")


@dataclass(frozen=True)
class EvidenceSummaryFields:
    coverage_start: str
    coverage_end: str
    total_original_detail_count: int
    pattern: str
    exceptions: tuple[str, ...]
    unknowns: tuple[str, ...]
    cumulative_uncertainty: str
    method_or_source_changes: tuple[str, ...]
    lost_detail_scope: str
    generation: int
    absorbed_records_digest: str
    absorbed_record_count: int
    predecessor_batch_digest: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.coverage_start, "summary coverage start"),
            (self.coverage_end, "summary coverage end"),
            (self.pattern, "summary pattern"),
            (self.cumulative_uncertainty, "summary cumulative uncertainty"),
            (self.lost_detail_scope, "summary lost detail scope"),
        ):
            validate_opaque_text(value, name)
        coverage_start_instant = _occurrence_time(
            self.coverage_start,
            "known",
        )
        coverage_end_instant = _occurrence_time(
            self.coverage_end,
            "known",
        )
        if coverage_start_instant > coverage_end_instant:
            raise AuthorityValidationError(
                "historical summary coverage is reversed"
            )
        _texts(self.exceptions, "summary exceptions", empty=True)
        _texts(self.unknowns, "summary unknowns", empty=True)
        _texts(
            self.method_or_source_changes,
            "summary method or source changes",
            empty=True,
        )
        if (
            type(self.total_original_detail_count) is not int
            or self.total_original_detail_count < 3
            or type(self.absorbed_record_count) is not int
            or self.absorbed_record_count < 2
            or type(self.generation) is not int
            or self.generation < 1
        ):
            raise AuthorityValidationError("invalid historical summary counts")
        _sha(self.absorbed_records_digest, "absorbed evidence records digest")
        if self.predecessor_batch_digest is not None:
            _sha(self.predecessor_batch_digest, "predecessor evidence batch digest")

    def to_storage(self) -> dict[str, object]:
        return {
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "total_original_detail_count": self.total_original_detail_count,
            "pattern": self.pattern,
            "exceptions": list(self.exceptions),
            "unknowns": list(self.unknowns),
            "cumulative_uncertainty": self.cumulative_uncertainty,
            "method_or_source_changes": list(self.method_or_source_changes),
            "lost_detail_scope": self.lost_detail_scope,
            "generation": self.generation,
            "absorbed_records_digest": self.absorbed_records_digest,
            "absorbed_record_count": self.absorbed_record_count,
            "predecessor_batch_digest": self.predecessor_batch_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "EvidenceSummaryFields":
        fields = _mapping(
            value,
            frozenset(
                {
                    "coverage_start",
                    "coverage_end",
                    "total_original_detail_count",
                    "pattern",
                    "exceptions",
                    "unknowns",
                    "cumulative_uncertainty",
                    "method_or_source_changes",
                    "lost_detail_scope",
                    "generation",
                    "absorbed_records_digest",
                    "absorbed_record_count",
                    "predecessor_batch_digest",
                }
            ),
            "historical evidence summary",
        )
        return cls(
            fields["coverage_start"],
            fields["coverage_end"],
            fields["total_original_detail_count"],
            fields["pattern"],
            _stored_texts(fields["exceptions"], "summary exceptions", empty=True),
            _stored_texts(fields["unknowns"], "summary unknowns", empty=True),
            fields["cumulative_uncertainty"],
            _stored_texts(
                fields["method_or_source_changes"],
                "summary method or source changes",
                empty=True,
            ),
            fields["lost_detail_scope"],
            fields["generation"],
            fields["absorbed_records_digest"],
            fields["absorbed_record_count"],
            fields["predecessor_batch_digest"],
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class AtomicEvidenceClaim:
    content: str
    evidence_type: str
    source_kind: str
    occurred_at: str
    applicable_period: str
    purpose: str
    uncertainty: str
    limitations: tuple[str, ...]
    proves: tuple[str, ...]
    does_not_prove: tuple[str, ...]
    topic_refs: tuple[str, ...]
    specific_fields: EvidenceSpecificFields
    series_key: EvidenceSeriesKey
    time_certainty: str
    summary_fields: EvidenceSummaryFields | None = None

    def __post_init__(self) -> None:
        for value, name in ((self.content, "evidence content"), (self.source_kind, "source kind"),
                            (self.occurred_at, "occurrence"), (self.applicable_period, "period"),
                            (self.purpose, "evidence purpose"), (self.uncertainty, "uncertainty")):
            validate_opaque_text(value, name)
        if self.evidence_type not in EVIDENCE_TYPES:
            raise AuthorityValidationError("invalid evidence type")
        expected_fields = {
            "personal-health": PersonalHealthFields,
            "authoritative-knowledge": AuthoritativeKnowledgeFields,
            "task-process": TaskProcessFields,
        }[self.evidence_type]
        if type(self.specific_fields) is not expected_fields:
            raise AuthorityValidationError("evidence type-specific fields mismatch")
        if (
            type(self.series_key) is not EvidenceSeriesKey
            or self.series_key.evidence_type != self.evidence_type
        ):
            raise AuthorityValidationError("evidence series type mismatch")
        if self.time_certainty not in {"known", "uncertain"}:
            raise AuthorityValidationError("invalid evidence time certainty")
        _occurrence_time(self.occurred_at, self.time_certainty)
        if self.summary_fields is not None and type(self.summary_fields) is not EvidenceSummaryFields:
            raise AuthorityValidationError("invalid historical summary fields")
        is_summary = self.summary_fields is not None
        if type(self.specific_fields) is PersonalHealthFields:
            if type(self.series_key.comparability_profile) is not PersonalEvidenceProfile:
                raise AuthorityValidationError("personal evidence profile mismatch")
            personal_profile = self.series_key.comparability_profile
            source_kinds = {
                "owner-statement": {"owner-statement"},
                "measurement": {"measurement"},
                "reported-clinician-conclusion": {
                    "reported-clinician-conclusion",
                    "doctor-relay",
                },
            }
            if is_summary:
                if (
                    self.specific_fields.observation_kind != "historical-summary"
                    or self.source_kind != "historical-summary"
                ):
                    raise AuthorityValidationError("invalid personal historical summary")
            else:
                if self.specific_fields.observation_kind == "historical-summary":
                    raise AuthorityValidationError("summary fields required")
                if self.source_kind not in source_kinds[self.specific_fields.observation_kind]:
                    raise AuthorityValidationError("personal evidence source mismatch")
                if (
                    personal_profile.observation_basis
                    != self.specific_fields.observation_kind
                    or personal_profile.measurement_method
                    != self.specific_fields.measurement_method
                    or personal_profile.measurement_unit
                    != self.specific_fields.measurement_unit
                ):
                    raise AuthorityValidationError(
                        "personal evidence fields do not match series profile"
                    )
                expected_unit = self.specific_fields.measurement_unit
                if self.series_key.unit != expected_unit:
                    raise AuthorityValidationError("measurement series unit mismatch")
        elif type(self.specific_fields) is AuthoritativeKnowledgeFields:
            if (
                type(self.series_key.comparability_profile)
                is not AuthoritativeKnowledgeProfile
            ):
                raise AuthorityValidationError("knowledge evidence profile mismatch")
            knowledge_profile = self.series_key.comparability_profile
            expected_kind = "historical-summary" if is_summary else "detail"
            if (
                self.specific_fields.record_kind != expected_kind
                or self.source_kind
                != ("historical-summary" if is_summary else "publisher-material")
            ):
                raise AuthorityValidationError("knowledge source mismatch")
            if (
                knowledge_profile.publisher != self.specific_fields.publisher
                or knowledge_profile.applicable_population
                != self.specific_fields.applicable_population
                or knowledge_profile.validity_boundary
                != self.specific_fields.validity_boundary
                or knowledge_profile.source_nature != "publisher-material"
            ):
                raise AuthorityValidationError(
                    "knowledge evidence fields do not match series profile"
                )
        else:
            if type(self.series_key.comparability_profile) is not TaskProcessProfile:
                raise AuthorityValidationError("task evidence profile mismatch")
            task_profile = self.series_key.comparability_profile
            expected_kind = "historical-summary" if is_summary else "detail"
            if (
                self.specific_fields.record_kind != expected_kind
                or self.source_kind
                != ("historical-summary" if is_summary else "task-ledger")
            ):
                raise AuthorityValidationError("task process source mismatch")
            if (
                task_profile.task_id != self.specific_fields.task_id
                or task_profile.process_fact_kind
                != self.specific_fields.process_fact_kind
                or task_profile.source_nature != "task-ledger"
            ):
                raise AuthorityValidationError(
                    "task evidence fields do not match series profile"
                )
        _texts(self.limitations, "limitations")
        if _texts(self.proves, "proves") != (self.content,):
            raise AuthorityValidationError("one evidence card must carry one atomic claim")
        _texts(self.does_not_prove, "does not prove")
        for topic_ref in _texts(self.topic_refs, "topic references"):
            _topic(topic_ref)

    def to_storage(self) -> dict[str, object]:
        return {"content": self.content, "evidence_type": self.evidence_type,
                "source_kind": self.source_kind, "occurred_at": self.occurred_at,
                "applicable_period": self.applicable_period, "purpose": self.purpose,
                "uncertainty": self.uncertainty, "limitations": list(self.limitations),
                "proves": list(self.proves), "does_not_prove": list(self.does_not_prove),
                "topic_refs": list(self.topic_refs),
                "specific_fields": _specific_fields_to_storage(self.specific_fields),
                "series_key": self.series_key.to_storage(),
                "time_certainty": self.time_certainty,
                "summary_fields": (
                    None if self.summary_fields is None else self.summary_fields.to_storage()
                )}

    @classmethod
    def from_storage(cls, value: object) -> "AtomicEvidenceClaim":
        f = _mapping(value, frozenset({"content", "evidence_type", "source_kind", "occurred_at",
            "applicable_period", "purpose", "uncertainty", "limitations", "proves",
            "does_not_prove", "topic_refs", "specific_fields", "series_key",
            "time_certainty", "summary_fields"}), "atomic evidence claim")
        summary_fields = f["summary_fields"]
        return cls(f["content"], f["evidence_type"], f["source_kind"], f["occurred_at"],
                   f["applicable_period"], f["purpose"], f["uncertainty"],
                   _stored_texts(f["limitations"], "limitations"),
                   _stored_texts(f["proves"], "proves"),
                   _stored_texts(f["does_not_prove"], "does not prove"),
                   _stored_texts(f["topic_refs"], "topic references"),
                   _specific_fields_from_storage(f["specific_fields"]),
                   EvidenceSeriesKey.from_storage(f["series_key"]),
                   f["time_certainty"],
                   None if summary_fields is None else EvidenceSummaryFields.from_storage(summary_fields))  # type: ignore[arg-type]


@dataclass(frozen=True)
class EvidenceMaintenanceRequest:
    """Plan-level authority for an exact evidence lifecycle operation."""

    action: str
    target_evidence_ids: tuple[str, ...]
    reason: str
    purpose: str
    replacement_claim: AtomicEvidenceClaim | None = None

    def __post_init__(self) -> None:
        if self.action not in {"correct", "withdraw", "invalidate"}:
            raise AuthorityValidationError("invalid evidence maintenance action")
        _texts(self.target_evidence_ids, "evidence maintenance targets")
        if len(set(self.target_evidence_ids)) != len(self.target_evidence_ids):
            raise AuthorityValidationError("duplicate evidence maintenance target")
        validate_opaque_text(self.reason, "evidence maintenance reason")
        validate_opaque_text(self.purpose, "evidence maintenance purpose")
        if self.action == "correct":
            if type(self.replacement_claim) is not AtomicEvidenceClaim:
                raise AuthorityValidationError(
                    "evidence correction requires a replacement claim"
                )
        elif self.replacement_claim is not None:
            raise AuthorityValidationError(
                "withdrawal cannot carry a replacement claim"
            )

    def to_storage(self) -> dict[str, object]:
        return {
            "action": self.action,
            "target_evidence_ids": list(self.target_evidence_ids),
            "reason": self.reason,
            "purpose": self.purpose,
            "replacement_claim": (
                None
                if self.replacement_claim is None
                else self.replacement_claim.to_storage()
            ),
        }

    @classmethod
    def from_storage(cls, value: object) -> "EvidenceMaintenanceRequest":
        fields = _mapping(
            value,
            frozenset(
                {
                    "action",
                    "target_evidence_ids",
                    "reason",
                    "purpose",
                    "replacement_claim",
                }
            ),
            "evidence maintenance request",
        )
        raw_claim = fields["replacement_claim"]
        if raw_claim is not None and type(raw_claim) is not dict:
            raise AuthorityValidationError(
                "invalid evidence maintenance replacement"
            )
        return cls(
            fields["action"],
            _stored_texts(
                fields["target_evidence_ids"],
                "evidence maintenance targets",
            ),
            fields["reason"],
            fields["purpose"],
            (
                None
                if raw_claim is None
                else AtomicEvidenceClaim.from_storage(raw_claim)
            ),
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class StewardContext:
    source_causal_id: str
    requested_capability: str
    owner_message: str
    health_navigation: "DailyHealthNavigation"

    def __post_init__(self) -> None:
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        validate_opaque_text(self.requested_capability, "requested capability")
        validate_opaque_text(self.owner_message, "owner message")
        if type(self.health_navigation) is not DailyHealthNavigation:
            raise AuthorityValidationError("invalid steward health navigation")

    def to_storage(self) -> dict[str, object]:
        return {"source_causal_id": self.source_causal_id,
                "requested_capability": self.requested_capability,
                "owner_message": self.owner_message,
                "health_navigation": self.health_navigation.to_storage()}


@dataclass(frozen=True)
class StewardPlan:
    purpose: str
    selected_skills: tuple[str, ...]
    atomic_claims: tuple[AtomicEvidenceClaim, ...]
    settings_intent: str | None = None
    inquiry_gap: str | None = None
    knowledge_gap: str | None = None
    allowed_knowledge_sources: tuple[str, ...] = ()
    recipient_boundary: str | None = None
    portrait_topic_refs: tuple[str, ...] = ()
    knowledge_topic_refs: tuple[str, ...] = ()
    evidence_maintenance_requests: tuple[EvidenceMaintenanceRequest, ...] = ()

    def __post_init__(self) -> None:
        validate_opaque_text(self.purpose, "daily purpose")
        _texts(self.selected_skills, "selected skills", empty=True)
        if any(name not in DAILY_HEALTH_SKILL_NAMES[1:] for name in self.selected_skills):
            raise AuthorityValidationError("invalid selected daily skill")
        if type(self.atomic_claims) is not tuple or any(type(c) is not AtomicEvidenceClaim for c in self.atomic_claims):
            raise AuthorityValidationError("invalid atomic claims")
        if type(self.evidence_maintenance_requests) is not tuple or any(
            type(request) is not EvidenceMaintenanceRequest
            for request in self.evidence_maintenance_requests
        ):
            raise AuthorityValidationError("invalid evidence maintenance requests")
        if any(
            request.purpose != self.purpose
            for request in self.evidence_maintenance_requests
        ):
            raise AuthorityValidationError(
                "evidence maintenance purpose mismatch"
            )
        if (
            self.atomic_claims or self.evidence_maintenance_requests
        ) and "health-evidence" not in self.selected_skills:
            raise AuthorityValidationError("health-evidence selection required")
        if (
            "health-evidence" not in self.selected_skills
            and self.evidence_maintenance_requests
        ):
            raise AuthorityValidationError("unused evidence maintenance request")
        for value, name in (
            (self.settings_intent, "settings intent"),
            (self.inquiry_gap, "inquiry gap"),
            (self.knowledge_gap, "knowledge gap"),
            (self.recipient_boundary, "recipient boundary"),
        ):
            if value is not None:
                validate_opaque_text(value, name)
        _texts(self.allowed_knowledge_sources, "allowed knowledge sources", empty=True)
        for topic_ref in _texts(
            self.portrait_topic_refs,
            "portrait topic scope",
            empty=True,
        ):
            _topic(topic_ref)
        for topic_ref in _texts(
            self.knowledge_topic_refs,
            "knowledge topic scope",
            empty=True,
        ):
            _topic(topic_ref)
        if ("health-settings" in self.selected_skills) != (self.settings_intent is not None):
            raise AuthorityValidationError("settings intent binding required")
        if ("health-owner-inquiry" in self.selected_skills) != (self.inquiry_gap is not None):
            raise AuthorityValidationError("inquiry gap binding required")
        if ("health-literature" in self.selected_skills) != (self.knowledge_gap is not None):
            raise AuthorityValidationError("knowledge gap binding required")
        if "health-literature" not in self.selected_skills and (
            self.allowed_knowledge_sources
            or self.recipient_boundary is not None
            or self.knowledge_topic_refs
        ):
            raise AuthorityValidationError("unused literature context")
        claim_topic_refs = {
            topic_ref
            for claim in self.atomic_claims
            for topic_ref in claim.topic_refs
        }
        claim_topic_refs.update(
            topic_ref
            for request in self.evidence_maintenance_requests
            if request.replacement_claim is not None
            for topic_ref in request.replacement_claim.topic_refs
        )
        if "health-portrait" in self.selected_skills:
            if not claim_topic_refs.union(self.portrait_topic_refs):
                raise AuthorityValidationError("portrait topic scope required")
        elif self.portrait_topic_refs:
            raise AuthorityValidationError("unused portrait topic scope")
        if (
            "health-literature" in self.selected_skills
            and not self.knowledge_topic_refs
        ):
            raise AuthorityValidationError("knowledge topic scope required")
        if "health-literature" in self.selected_skills and (
            not self.allowed_knowledge_sources
            or self.recipient_boundary is None
        ):
            raise AuthorityValidationError(
                "literature source and recipient boundaries required"
            )

    def to_storage(self) -> dict[str, object]:
        return {"purpose": self.purpose, "selected_skills": list(self.selected_skills),
                "atomic_claims": [c.to_storage() for c in self.atomic_claims],
                "settings_intent": self.settings_intent, "inquiry_gap": self.inquiry_gap,
                "knowledge_gap": self.knowledge_gap,
                "allowed_knowledge_sources": list(self.allowed_knowledge_sources),
                "recipient_boundary": self.recipient_boundary,
                "portrait_topic_refs": list(self.portrait_topic_refs),
                "knowledge_topic_refs": list(self.knowledge_topic_refs),
                "evidence_maintenance_requests": [
                    request.to_storage()
                    for request in self.evidence_maintenance_requests
                ]}

    @classmethod
    def from_storage(cls, value: object) -> "StewardPlan":
        fields = _mapping(
            value,
            frozenset(
                {
                    "purpose",
                    "selected_skills",
                    "atomic_claims",
                    "settings_intent",
                    "inquiry_gap",
                    "knowledge_gap",
                    "allowed_knowledge_sources",
                    "recipient_boundary",
                    "portrait_topic_refs",
                    "knowledge_topic_refs",
                    "evidence_maintenance_requests",
                }
            ),
            "steward plan",
        )
        claims = fields["atomic_claims"]
        maintenance = fields["evidence_maintenance_requests"]
        if type(claims) is not list or type(maintenance) is not list:
            raise AuthorityValidationError("invalid evidence plan inputs")
        return cls(
            fields["purpose"],
            _stored_texts(fields["selected_skills"], "selected skills", empty=True),
            tuple(AtomicEvidenceClaim.from_storage(item) for item in claims),
            fields["settings_intent"],
            fields["inquiry_gap"],
            fields["knowledge_gap"],
            _stored_texts(
                fields["allowed_knowledge_sources"],
                "allowed knowledge sources",
                empty=True,
            ),
            fields["recipient_boundary"],
            _stored_texts(
                fields["portrait_topic_refs"],
                "portrait topic scope",
                empty=True,
            ),
            _stored_texts(
                fields["knowledge_topic_refs"],
                "knowledge topic scope",
                empty=True,
            ),
            tuple(
                EvidenceMaintenanceRequest.from_storage(item)
                for item in maintenance
            ),
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class ResponsibilityResult:
    """Minimal typed hand-back from one responsibility action to the steward."""

    canonical_name: str
    status: str
    input_digest: str
    result_digest: str
    decision: object
    candidate_refs: tuple[str, ...] = ()
    candidate_change_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.canonical_name not in DAILY_HEALTH_SKILL_NAMES[1:]:
            raise AuthorityValidationError("invalid responsibility result")
        validate_opaque_text(self.status, "responsibility status")
        _sha(self.input_digest, "responsibility input digest")
        _sha(self.result_digest, "responsibility result digest")
        _texts(self.candidate_refs, "responsibility candidate references", empty=True)
        _texts(
            self.candidate_change_ids,
            "responsibility candidate changes",
            empty=True,
        )
        expected_type = {
            "health-evidence": EvidenceDecision,
            "health-portrait": PortraitDecision,
            "health-settings": SettingsDecision,
            "health-owner-inquiry": OwnerInquiryDecision,
            "health-literature": LiteratureDecision,
        }[self.canonical_name]
        if type(self.decision) is not expected_type:
            raise AuthorityValidationError("responsibility decision type mismatch")
        decision_status = getattr(self.decision, "status", None)
        decision_storage = getattr(self.decision, "to_storage", None)
        if (
            decision_status != self.status
            or not callable(decision_storage)
            or stable_digest(decision_storage()) != self.result_digest
        ):
            raise AuthorityValidationError("responsibility decision digest mismatch")
        if type(self.decision) is EvidenceDecision:
            expects_candidate = self.decision.status in {
                "admit",
                "correct",
                "compress",
            }
            if (len(self.candidate_refs) == 1) != expects_candidate:
                raise AuthorityValidationError("evidence candidate reference mismatch")
            expected_change_count = (
                len(self.decision.target_evidence_ids)
                if self.decision.status in {
                    "correct",
                    "withdraw",
                    "invalidate",
                }
                else 0
            )
            if len(self.candidate_change_ids) != expected_change_count:
                raise AuthorityValidationError(
                    "evidence applicability candidate mismatch"
                )
        elif type(self.decision) is PortraitDecision:
            expected_refs = (
                (self.decision.topic_ref,)
                if self.decision.status in {
                    "update",
                    "maintain",
                    "degrade",
                    "withdraw",
                }
                else ()
            )
            if self.candidate_refs != expected_refs or self.candidate_change_ids:
                raise AuthorityValidationError("portrait candidate reference mismatch")
        elif type(self.decision) is LiteratureDecision:
            expected_refs = (
                ()
                if self.decision.candidate_ref is None
                else (self.decision.candidate_ref,)
            )
            if self.candidate_refs != expected_refs or self.candidate_change_ids:
                raise AuthorityValidationError("literature candidate reference mismatch")
        elif self.candidate_refs or self.candidate_change_ids:
            raise AuthorityValidationError("unexpected responsibility candidate reference")

    def to_storage(self) -> dict[str, object]:
        return {
            "canonical_name": self.canonical_name,
            "status": self.status,
            "input_digest": self.input_digest,
            "result_digest": self.result_digest,
            "decision": self.decision.to_storage(),
            "candidate_refs": list(self.candidate_refs),
            "candidate_change_ids": list(self.candidate_change_ids),
        }

    @classmethod
    def from_storage(cls, value: object) -> "ResponsibilityResult":
        fields = _mapping(
            value,
            frozenset(
                {
                    "canonical_name",
                    "status",
                    "input_digest",
                    "result_digest",
                    "decision",
                    "candidate_refs",
                    "candidate_change_ids",
                }
            ),
            "responsibility result",
        )
        return cls(
            fields["canonical_name"],
            fields["status"],
            fields["input_digest"],
            fields["result_digest"],
            _responsibility_decision_from_storage(
                fields["canonical_name"],
                fields["decision"],
            ),
            _stored_texts(
                fields["candidate_refs"],
                "responsibility candidate references",
                empty=True,
            ),
            _stored_texts(
                fields["candidate_change_ids"],
                "responsibility candidate changes",
                empty=True,
            ),
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class OwnerReplyAtom:
    """A bounded owner-visible statement backed by one typed responsibility result."""

    atom_id: str
    kind: str
    text: str
    source_skill: str
    source_result_digest: str
    required_evidence_ids: tuple[str, ...] = ()
    required_portrait_topic_refs: tuple[str, ...] = ()
    required_evidence_change_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_opaque_text(self.atom_id, "reply atom identifier")
        if self.kind not in REPLY_ATOM_KINDS:
            raise AuthorityValidationError("invalid reply atom kind")
        _owner_reply_text(self.text, "reply atom text")
        if self.source_skill not in DAILY_HEALTH_SKILL_NAMES:
            raise AuthorityValidationError("invalid reply atom source")
        _sha(self.source_result_digest, "reply atom source result")
        _texts(self.required_evidence_ids, "reply atom evidence", empty=True)
        _texts(
            self.required_evidence_change_ids,
            "reply atom evidence changes",
            empty=True,
        )
        for topic_ref in _texts(
            self.required_portrait_topic_refs,
            "reply atom portrait topics",
            empty=True,
        ):
            _topic(topic_ref)
        expected = "reply-atom:" + stable_digest(
            {
                "kind": self.kind,
                "text": self.text,
                "source_skill": self.source_skill,
                "source_result_digest": self.source_result_digest,
                "required_evidence_ids": list(self.required_evidence_ids),
                "required_portrait_topic_refs": list(
                    self.required_portrait_topic_refs
                ),
                "required_evidence_change_ids": list(
                    self.required_evidence_change_ids
                ),
            }
        ).removeprefix("sha256:")
        if self.atom_id != expected:
            raise AuthorityValidationError("reply atom identifier mismatch")

    @classmethod
    def form(
        cls,
        *,
        kind: str,
        text: str,
        source_skill: str,
        source_result_digest: str,
        required_evidence_ids: tuple[str, ...] = (),
        required_portrait_topic_refs: tuple[str, ...] = (),
        required_evidence_change_ids: tuple[str, ...] = (),
    ) -> "OwnerReplyAtom":
        body = {
            "kind": kind,
            "text": text,
            "source_skill": source_skill,
            "source_result_digest": source_result_digest,
            "required_evidence_ids": list(required_evidence_ids),
            "required_portrait_topic_refs": list(required_portrait_topic_refs),
            "required_evidence_change_ids": list(
                required_evidence_change_ids
            ),
        }
        return cls(
            "reply-atom:" + stable_digest(body).removeprefix("sha256:"),
            kind,
            text,
            source_skill,
            source_result_digest,
            required_evidence_ids,
            required_portrait_topic_refs,
            required_evidence_change_ids,
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "atom_id": self.atom_id,
            "kind": self.kind,
            "text": self.text,
            "source_skill": self.source_skill,
            "source_result_digest": self.source_result_digest,
            "required_evidence_ids": list(self.required_evidence_ids),
            "required_portrait_topic_refs": list(
                self.required_portrait_topic_refs
            ),
            "required_evidence_change_ids": list(
                self.required_evidence_change_ids
            ),
        }

    @classmethod
    def from_storage(cls, value: object) -> "OwnerReplyAtom":
        fields = _mapping(
            value,
            frozenset(
                {
                    "atom_id",
                    "kind",
                    "text",
                    "source_skill",
                    "source_result_digest",
                    "required_evidence_ids",
                    "required_portrait_topic_refs",
                    "required_evidence_change_ids",
                }
            ),
            "owner reply atom",
        )
        return cls(
            fields["atom_id"],
            fields["kind"],
            fields["text"],
            fields["source_skill"],
            fields["source_result_digest"],
            _stored_texts(fields["required_evidence_ids"], "reply atom evidence", empty=True),
            _stored_texts(
                fields["required_portrait_topic_refs"],
                "reply atom portrait topics",
                empty=True,
            ),
            _stored_texts(
                fields["required_evidence_change_ids"],
                "reply atom evidence changes",
                empty=True,
            ),
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class StewardResolutionContext:
    source_causal_id: str
    purpose: str
    responsibility_results: tuple[ResponsibilityResult, ...]
    candidate_evidence_ids: tuple[str, ...]
    candidate_portrait_topic_refs: tuple[str, ...]
    reply_atoms: tuple[OwnerReplyAtom, ...]
    candidate_evidence_change_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        validate_opaque_text(self.purpose, "daily purpose")
        if type(self.responsibility_results) is not tuple or any(
            type(item) is not ResponsibilityResult
            for item in self.responsibility_results
        ):
            raise AuthorityValidationError("invalid responsibility results")
        _texts(self.candidate_evidence_ids, "candidate evidence identifiers", empty=True)
        _texts(
            self.candidate_evidence_change_ids,
            "candidate evidence changes",
            empty=True,
        )
        for topic_ref in _texts(
            self.candidate_portrait_topic_refs,
            "candidate portrait topics",
            empty=True,
        ):
            _topic(topic_ref)
        if type(self.reply_atoms) is not tuple or not self.reply_atoms or any(
            type(item) is not OwnerReplyAtom for item in self.reply_atoms
        ):
            raise AuthorityValidationError("invalid owner reply atoms")
        if len({item.atom_id for item in self.reply_atoms}) != len(self.reply_atoms):
            raise AuthorityValidationError("duplicate owner reply atom")

    def to_storage(self) -> dict[str, object]:
        return {
            "source_causal_id": self.source_causal_id,
            "purpose": self.purpose,
            "responsibility_results": [
                item.to_storage() for item in self.responsibility_results
            ],
            "candidate_evidence_ids": list(self.candidate_evidence_ids),
            "candidate_portrait_topic_refs": list(
                self.candidate_portrait_topic_refs
            ),
            "reply_atoms": [item.to_storage() for item in self.reply_atoms],
            "candidate_evidence_change_ids": list(
                self.candidate_evidence_change_ids
            ),
        }


@dataclass(frozen=True)
class StewardResolution:
    commit_evidence_ids: tuple[str, ...]
    commit_portrait_topic_refs: tuple[str, ...]
    reply_atom_ids: tuple[str, ...]
    commit_evidence_change_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _texts(self.commit_evidence_ids, "committed evidence identifiers", empty=True)
        _texts(
            self.commit_evidence_change_ids,
            "committed evidence changes",
            empty=True,
        )
        for topic_ref in _texts(
            self.commit_portrait_topic_refs,
            "committed portrait topics",
            empty=True,
        ):
            _topic(topic_ref)
        _texts(self.reply_atom_ids, "selected reply atoms")

    def to_storage(self) -> dict[str, object]:
        return {
            "commit_evidence_ids": list(self.commit_evidence_ids),
            "commit_portrait_topic_refs": list(self.commit_portrait_topic_refs),
            "reply_atom_ids": list(self.reply_atom_ids),
            "commit_evidence_change_ids": list(
                self.commit_evidence_change_ids
            ),
        }

    @classmethod
    def from_storage(cls, value: object) -> "StewardResolution":
        fields = _mapping(
            value,
            frozenset(
                {
                    "commit_evidence_ids",
                    "commit_portrait_topic_refs",
                    "reply_atom_ids",
                    "commit_evidence_change_ids",
                }
            ),
            "steward resolution",
        )
        return cls(
            _stored_texts(
                fields["commit_evidence_ids"],
                "committed evidence identifiers",
                empty=True,
            ),
            _stored_texts(
                fields["commit_portrait_topic_refs"],
                "committed portrait topics",
                empty=True,
            ),
            _stored_texts(fields["reply_atom_ids"], "selected reply atoms"),
            _stored_texts(
                fields["commit_evidence_change_ids"],
                "committed evidence changes",
                empty=True,
            ),
        )


def _validated_selected_reply_atoms(
    context: StewardResolutionContext,
    resolution: StewardResolution,
) -> tuple[OwnerReplyAtom, ...]:
    """Return only a complete, ordered, responsibility-bound reply selection."""

    if (
        type(context) is not StewardResolutionContext
        or type(resolution) is not StewardResolution
    ):
        raise AuthorityValidationError("invalid steward reply selection")
    atoms_by_id = {atom.atom_id: atom for atom in context.reply_atoms}
    if len(atoms_by_id) != len(context.reply_atoms):
        raise AuthorityValidationError("duplicate owner reply atom")
    try:
        selected_atoms = tuple(
            atoms_by_id[atom_id] for atom_id in resolution.reply_atom_ids
        )
    except KeyError as exc:
        raise AuthorityValidationError("unknown owner reply atom") from exc
    if (
        len({atom.atom_id for atom in selected_atoms}) != len(selected_atoms)
        or [REPLY_ATOM_KINDS.index(atom.kind) for atom in selected_atoms]
        != sorted(REPLY_ATOM_KINDS.index(atom.kind) for atom in selected_atoms)
    ):
        raise AuthorityValidationError("invalid final owner reply selection")

    committed_evidence_ids = set(resolution.commit_evidence_ids)
    committed_topic_refs = set(resolution.commit_portrait_topic_refs)
    committed_change_ids = set(resolution.commit_evidence_change_ids)
    if (
        {
            evidence_id
            for atom in selected_atoms
            if atom.kind == "record-result"
            for evidence_id in atom.required_evidence_ids
        }
        != committed_evidence_ids
        or {
            topic_ref
            for atom in selected_atoms
            if atom.kind == "record-result"
            for topic_ref in atom.required_portrait_topic_refs
        }
        != committed_topic_refs
        or {
            change_id
            for atom in selected_atoms
            if atom.kind == "record-result"
            for change_id in atom.required_evidence_change_ids
        }
        != committed_change_ids
    ):
        raise AuthorityValidationError(
            "owner reply did not cover every committed business change"
        )

    results_by_source: dict[
        tuple[str, str], list[ResponsibilityResult]
    ] = {}
    for result in context.responsibility_results:
        results_by_source.setdefault(
            (result.canonical_name, result.result_digest), []
        ).append(result)
    for atom in selected_atoms:
        carries_reference = bool(
            atom.required_evidence_ids
            or atom.required_portrait_topic_refs
            or atom.required_evidence_change_ids
        )
        if atom.source_skill == "health-steward":
            if carries_reference:
                raise AuthorityValidationError(
                    "steward reply reference lacks a responsibility result"
                )
            continue
        matching_results = results_by_source.get(
            (atom.source_skill, atom.source_result_digest), []
        )
        if len(matching_results) != 1:
            raise AuthorityValidationError(
                "owner reply source did not bind one responsibility result"
            )
        result = matching_results[0]
        if (
            (
                atom.required_evidence_ids
                and (
                    result.canonical_name != "health-evidence"
                    or not set(atom.required_evidence_ids)
                    <= set(result.candidate_refs)
                )
            )
            or (
                atom.required_portrait_topic_refs
                and (
                    result.canonical_name != "health-portrait"
                    or not set(atom.required_portrait_topic_refs)
                    <= set(result.candidate_refs)
                )
            )
            or (
                atom.required_evidence_change_ids
                and (
                    result.canonical_name != "health-evidence"
                    or not set(atom.required_evidence_change_ids)
                    <= set(result.candidate_change_ids)
                )
            )
        ):
            raise AuthorityValidationError(
                "owner reply reference exceeded its responsibility result"
            )
    return selected_atoms


@dataclass(frozen=True)
class EvidenceContext:
    source_causal_id: str
    purpose: str
    atomic_claim: AtomicEvidenceClaim | None
    maintenance_request: EvidenceMaintenanceRequest | None
    base_state_digest: str
    related_existing_cards: tuple["EvidenceCard", ...]
    related_relations: tuple["EvidenceRelation", ...]
    current_evidence_ids: tuple[str, ...]
    related_applicability_changes: tuple["EvidenceApplicabilityChange", ...]
    series_window: "EvidenceSeriesWindow | None"

    def __post_init__(self) -> None:
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        validate_opaque_text(self.purpose, "daily purpose")
        if self.maintenance_request is None:
            if type(self.atomic_claim) is not AtomicEvidenceClaim:
                raise AuthorityValidationError("invalid atomic claim")
        elif type(self.maintenance_request) is not EvidenceMaintenanceRequest:
            raise AuthorityValidationError("invalid evidence maintenance request")
        elif (
            self.maintenance_request.purpose != self.purpose
            or self.atomic_claim != self.maintenance_request.replacement_claim
        ):
            raise AuthorityValidationError("evidence maintenance context mismatch")
        _sha(self.base_state_digest, "evidence context state digest")
        if type(self.related_existing_cards) is not tuple or any(
            type(item) is not EvidenceCard for item in self.related_existing_cards
        ):
            raise AuthorityValidationError("invalid related evidence cards")
        if type(self.related_relations) is not tuple or any(
            type(item) is not EvidenceRelation for item in self.related_relations
        ):
            raise AuthorityValidationError("invalid related evidence relations")
        _texts(
            self.current_evidence_ids,
            "current evidence identifiers",
            empty=True,
        )
        if type(self.related_applicability_changes) is not tuple or any(
            type(item) is not EvidenceApplicabilityChange
            for item in self.related_applicability_changes
        ):
            raise AuthorityValidationError(
                "invalid related applicability changes"
            )
        if self.series_window is not None and type(self.series_window) is not EvidenceSeriesWindow:
            raise AuthorityValidationError("invalid evidence series window context")
        related_ids = {card.evidence_id for card in self.related_existing_cards}
        if any(relation.evidence_id not in related_ids for relation in self.related_relations):
            raise AuthorityValidationError("evidence context relation exceeded card scope")
        if (
            not set(self.current_evidence_ids) <= related_ids
            or any(
                change.target_evidence_id not in related_ids
                for change in self.related_applicability_changes
            )
        ):
            raise AuthorityValidationError(
                "evidence currentness exceeded card scope"
            )
        if self.maintenance_request is not None and (
            set(self.maintenance_request.target_evidence_ids)
            != related_ids
            or not related_ids <= set(self.current_evidence_ids)
        ):
            raise AuthorityValidationError(
                "evidence maintenance target context mismatch"
            )

    def to_storage(self) -> dict[str, object]:
        return {"source_causal_id": self.source_causal_id, "purpose": self.purpose,
                "atomic_claim": (
                    None
                    if self.atomic_claim is None
                    else self.atomic_claim.to_storage()
                ),
                "maintenance_request": (
                    None
                    if self.maintenance_request is None
                    else self.maintenance_request.to_storage()
                ),
                "base_state_digest": self.base_state_digest,
                "related_existing_cards": [
                    item.to_storage() for item in self.related_existing_cards
                ],
                "related_relations": [
                    item.to_storage() for item in self.related_relations
                ],
                "current_evidence_ids": list(self.current_evidence_ids),
                "related_applicability_changes": [
                    item.to_storage()
                    for item in self.related_applicability_changes
                ],
                "series_window": (
                    None if self.series_window is None else self.series_window.to_storage()
                )}


@dataclass(frozen=True)
class EvidenceDecision:
    status: str
    atomic_claim: AtomicEvidenceClaim | None
    reason: str | None = None
    target_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {
            "admit",
            "reject",
            "clarify",
            "correct",
            "withdraw",
            "invalidate",
            "compress",
        }:
            raise AuthorityValidationError("invalid evidence decision")
        _texts(self.target_evidence_ids, "evidence maintenance targets", empty=True)
        if len(set(self.target_evidence_ids)) != len(self.target_evidence_ids):
            raise AuthorityValidationError("duplicate evidence maintenance target")
        if self.status == "admit":
            if type(self.atomic_claim) is not AtomicEvidenceClaim or self.reason is not None:
                raise AuthorityValidationError("invalid evidence admission")
            if self.atomic_claim.summary_fields is not None or self.target_evidence_ids:
                raise AuthorityValidationError("invalid detail evidence admission")
        elif self.status == "compress":
            if (
                type(self.atomic_claim) is not AtomicEvidenceClaim
                or self.atomic_claim.summary_fields is None
                or self.reason is not None
                or len(self.target_evidence_ids) < 2
            ):
                raise AuthorityValidationError("invalid evidence compression")
        elif self.status == "correct":
            if (
                type(self.atomic_claim) is not AtomicEvidenceClaim
                or self.atomic_claim.summary_fields is not None
                or self.reason is None
                or not self.target_evidence_ids
            ):
                raise AuthorityValidationError("invalid evidence correction")
        elif self.atomic_claim is not None:
            raise AuthorityValidationError("unadmitted evidence cannot carry a claim")
        elif self.status in {"withdraw", "invalidate"} and (
            not self.target_evidence_ids or self.reason is None
        ):
            raise AuthorityValidationError("invalid evidence status change")
        elif self.status in {"reject", "clarify"} and (
            self.target_evidence_ids or self.reason is None
        ):
            raise AuthorityValidationError("invalid rejected evidence decision")
        if self.reason is not None:
            validate_opaque_text(self.reason, "evidence reason")

    @classmethod
    def admit(cls, claim: AtomicEvidenceClaim) -> "EvidenceDecision": return cls("admit", claim)
    @classmethod
    def reject(cls, reason: str) -> "EvidenceDecision": return cls("reject", None, reason)
    @classmethod
    def clarify(cls, reason: str) -> "EvidenceDecision": return cls("clarify", None, reason)
    @classmethod
    def compress(
        cls,
        claim: AtomicEvidenceClaim,
        retire_evidence_ids: tuple[str, ...],
    ) -> "EvidenceDecision":
        return cls("compress", claim, target_evidence_ids=retire_evidence_ids)

    @classmethod
    def correct(
        cls,
        claim: AtomicEvidenceClaim,
        corrected_evidence_ids: tuple[str, ...],
        *,
        reason: str,
    ) -> "EvidenceDecision":
        return cls("correct", claim, reason, corrected_evidence_ids)

    @classmethod
    def withdraw(
        cls, reason: str, evidence_ids: tuple[str, ...]
    ) -> "EvidenceDecision":
        return cls("withdraw", None, reason, evidence_ids)

    @classmethod
    def invalidate(
        cls, reason: str, evidence_ids: tuple[str, ...]
    ) -> "EvidenceDecision":
        return cls("invalidate", None, reason, evidence_ids)

    def to_storage(self) -> dict[str, object]:
        return {"status": self.status,
                "atomic_claim": None if self.atomic_claim is None else self.atomic_claim.to_storage(),
                "reason": self.reason,
                "target_evidence_ids": list(self.target_evidence_ids)}

    @classmethod
    def from_storage(cls, value: object) -> "EvidenceDecision":
        fields = _mapping(
            value,
            frozenset({"status", "atomic_claim", "reason", "target_evidence_ids"}),
            "evidence decision",
        )
        raw_claim = fields["atomic_claim"]
        if raw_claim is not None and type(raw_claim) is not dict:
            raise AuthorityValidationError("invalid evidence decision claim")
        return cls(
            fields["status"],
            None if raw_claim is None else AtomicEvidenceClaim.from_storage(raw_claim),
            fields["reason"],
            _stored_texts(
                fields["target_evidence_ids"],
                "evidence maintenance targets",
                empty=True,
            ),
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class PortraitContext:
    source_causal_id: str
    purpose: str
    base_state_digest: str
    affected_topic_refs: tuple[str, ...]
    current_topic_views: tuple["PortraitTopicProjection", ...]
    committed_related_cards: tuple["EvidenceCard", ...]
    committed_relations: tuple["EvidenceRelation", ...]
    in_turn_evidence_candidates: tuple["EvidenceCard", ...]
    related_task_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        validate_opaque_text(self.purpose, "daily purpose")
        _sha(self.base_state_digest, "portrait context state digest")
        for topic_ref in _texts(self.affected_topic_refs, "affected topic references"):
            _topic(topic_ref)
        if type(self.current_topic_views) is not tuple or any(
            type(item) is not PortraitTopicProjection for item in self.current_topic_views
        ):
            raise AuthorityValidationError("invalid current portrait topic views")
        if tuple(item.topic_ref for item in self.current_topic_views) != self.affected_topic_refs:
            raise AuthorityValidationError("portrait context view scope mismatch")
        for value, expected, name in (
            (self.committed_related_cards, EvidenceCard, "committed related evidence"),
            (self.committed_relations, EvidenceRelation, "committed related relations"),
            (self.in_turn_evidence_candidates, EvidenceCard, "in-turn evidence candidates"),
        ):
            if type(value) is not tuple or any(type(item) is not expected for item in value):
                raise AuthorityValidationError(f"invalid {name}")
        committed_ids = {card.evidence_id for card in self.committed_related_cards}
        if any(
            relation.evidence_id not in committed_ids
            for relation in self.committed_relations
        ):
            raise AuthorityValidationError("portrait context relation exceeded evidence scope")
        _texts(self.related_task_refs, "related task references", empty=True)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            card.evidence_id
            for card in (
                *self.committed_related_cards,
                *self.in_turn_evidence_candidates,
            )
        )

    @property
    def topic_refs(self) -> tuple[str, ...]:
        return self.affected_topic_refs

    def to_storage(self) -> dict[str, object]:
        return {"source_causal_id": self.source_causal_id, "purpose": self.purpose,
                "base_state_digest": self.base_state_digest,
                "affected_topic_refs": list(self.affected_topic_refs),
                "current_topic_views": [
                    item.to_storage() for item in self.current_topic_views
                ],
                "committed_related_cards": [
                    item.to_storage() for item in self.committed_related_cards
                ],
                "committed_relations": [
                    item.to_storage() for item in self.committed_relations
                ],
                "in_turn_evidence_candidates": [
                    item.to_storage() for item in self.in_turn_evidence_candidates
                ],
                "related_task_refs": list(self.related_task_refs)}


def _portrait_item_target_ref(
    *,
    topic_ref: str,
    item_kind: str,
    item_text: str,
    trend_period: str | None,
    applicable_period: str | None,
) -> str:
    prefix = {
        "current-understanding": "portrait-understanding:",
        "trend": "portrait-trend:",
        "open-judgment": "portrait-open-judgment:",
        "key-unknown": "portrait-key-unknown:",
    }[item_kind]
    target: dict[str, object] = {
        "topic_ref": topic_ref,
        "item_kind": item_kind,
        "item_text": item_text,
        "trend_period": trend_period,
    }
    if item_kind == "current-understanding":
        target["applicable_period"] = applicable_period
    return prefix + stable_digest(target).removeprefix("sha256:")


@dataclass(frozen=True)
class PortraitProofLink:
    """One explicit evidence-to-portrait-item proof candidate.

    The portrait Skill, rather than the runtime, chooses whether one evidence
    card supports, opposes, or merely qualifies one exact displayed item.
    Keeping the item text in the transient candidate lets core reject a link
    to some other conclusion; the committed ledger stores only the stable
    target reference and never duplicates the displayed text.
    """

    evidence_id: str
    relation_kind: str
    topic_ref: str
    item_kind: str
    item_text: str
    trend_period: str | None = None
    applicable_period: str | None = None

    def __post_init__(self) -> None:
        validate_opaque_text(self.evidence_id, "portrait proof evidence identifier")
        if self.relation_kind not in {"supports", "opposes", "qualifies"}:
            raise AuthorityValidationError("invalid portrait proof relation")
        _topic(self.topic_ref)
        if self.item_kind not in {
            "current-understanding",
            "trend",
            "open-judgment",
            "key-unknown",
        }:
            raise AuthorityValidationError("invalid portrait proof item kind")
        validate_opaque_text(self.item_text, "portrait proof item")
        if self.item_kind == "trend":
            if self.trend_period is None:
                raise AuthorityValidationError("portrait trend proof period required")
            validate_opaque_text(self.trend_period, "portrait trend proof period")
        elif self.trend_period is not None:
            raise AuthorityValidationError("unexpected portrait proof period")
        if self.item_kind == "current-understanding":
            if self.applicable_period is None:
                raise AuthorityValidationError(
                    "portrait current understanding applicable period required"
                )
            validate_opaque_text(
                self.applicable_period,
                "portrait current understanding applicable period",
            )
        elif self.applicable_period is not None:
            raise AuthorityValidationError(
                "unexpected portrait current understanding applicable period"
            )

    @classmethod
    def form(
        cls,
        *,
        evidence_id: str,
        relation_kind: str,
        topic_ref: str,
        item_kind: str,
        item_text: str,
        trend_period: str | None = None,
        applicable_period: str | None = None,
    ) -> "PortraitProofLink":
        return cls(
            evidence_id,
            relation_kind,
            topic_ref,
            item_kind,
            item_text,
            trend_period,
            applicable_period,
        )

    @property
    def target_ref(self) -> str:
        return _portrait_item_target_ref(
            topic_ref=self.topic_ref,
            item_kind=self.item_kind,
            item_text=self.item_text,
            trend_period=self.trend_period,
            applicable_period=self.applicable_period,
        )

    def to_relation(self) -> "EvidenceRelation":
        return EvidenceRelation(
            self.evidence_id,
            "proof",
            self.relation_kind,
            "portrait-item",
            self.target_ref,
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "relation_kind": self.relation_kind,
            "topic_ref": self.topic_ref,
            "item_kind": self.item_kind,
            "item_text": self.item_text,
            "trend_period": self.trend_period,
            "applicable_period": self.applicable_period,
        }

    @classmethod
    def from_storage(cls, value: object) -> "PortraitProofLink":
        fields = _mapping(
            value,
            frozenset({
                "evidence_id",
                "relation_kind",
                "topic_ref",
                "item_kind",
                "item_text",
                "trend_period",
                "applicable_period",
            }),
            "portrait proof link",
        )
        return cls(**fields)  # type: ignore[arg-type]


def _current_understanding_applicable_periods(
    current_understandings: tuple[str, ...],
    proof_links: tuple[PortraitProofLink, ...],
) -> tuple[str, ...]:
    periods: list[str] = []
    for understanding in current_understandings:
        linked_periods = {
            link.applicable_period
            for link in proof_links
            if link.item_kind == "current-understanding"
            and link.item_text == understanding
        }
        if len(linked_periods) != 1 or None in linked_periods:
            raise AuthorityValidationError(
                "one applicable period required per current understanding"
            )
        period = next(iter(linked_periods))
        if type(period) is not str:
            raise AuthorityValidationError(
                "invalid current understanding applicable period"
            )
        periods.append(period)
    return tuple(periods)


@dataclass(frozen=True)
class PortraitDecision:
    status: str
    topic_ref: str | None = None
    current_understandings: tuple[str, ...] = ()
    open_judgments: tuple[str, ...] = ()
    key_unknowns: tuple[str, ...] = ()
    proof_links: tuple[PortraitProofLink, ...] = ()
    trend: str | None = None
    trend_period: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "update",
            "maintain",
            "degrade",
            "withdraw",
            "gap",
            "no-change",
        }:
            raise AuthorityValidationError("invalid portrait decision")
        if self.status in {"no-change", "gap"}:
            if any((self.topic_ref, self.current_understandings, self.open_judgments,
                    self.key_unknowns, self.proof_links, self.trend,
                    self.trend_period)):
                raise AuthorityValidationError("invalid empty portrait decision")
            if self.status == "gap" and self.reason is None:
                raise AuthorityValidationError("portrait gap reason required")
            if self.status == "gap":
                validate_opaque_text(self.reason, "portrait gap reason")
            if self.status == "no-change" and self.reason is not None:
                raise AuthorityValidationError("invalid no-change portrait")
            return
        if self.status in {"maintain", "withdraw"}:
            _topic(self.topic_ref)
            if (
                self.reason is None
                or any((self.current_understandings, self.open_judgments,
                        self.key_unknowns, self.proof_links,
                        self.trend, self.trend_period))
            ):
                raise AuthorityValidationError("invalid portrait maintenance decision")
            validate_opaque_text(self.reason, "portrait decision reason")
            return
        _topic(self.topic_ref)
        _display_texts(self.current_understandings, "current understandings")
        _display_texts(self.open_judgments, "open judgments")
        _display_texts(self.key_unknowns, "key unknowns")
        if type(self.proof_links) is not tuple or any(
            type(link) is not PortraitProofLink for link in self.proof_links
        ):
            raise AuthorityValidationError("invalid portrait proof links")
        if len(set(self.proof_links)) != len(self.proof_links):
            raise AuthorityValidationError("duplicate portrait proof link")
        if self.trend is not None:
            validate_opaque_text(self.trend, "portrait trend")
            if (
                len(self.trend) > 20
                or len({link.evidence_id for link in self.proof_links}) < 2
                or self.trend_period is None
            ):
                raise AuthorityValidationError("one observation cannot establish a trend")
            validate_opaque_text(self.trend_period, "portrait trend period")
        elif self.trend_period is not None:
            raise AuthorityValidationError("portrait trend period without trend")
        understanding_periods = _current_understanding_applicable_periods(
            self.current_understandings,
            self.proof_links,
        )
        expected_targets = {
            PortraitProofLink.form(
                evidence_id="evidence:target-check",
                relation_kind="supports",
                topic_ref=self.topic_ref,
                item_kind="current-understanding",
                item_text=item,
                applicable_period=period,
            ).target_ref
            for item, period in zip(
                self.current_understandings,
                understanding_periods,
            )
        }
        for item_kind, items in (
            ("open-judgment", self.open_judgments),
            ("key-unknown", self.key_unknowns),
        ):
            expected_targets.update(
                PortraitProofLink.form(
                    evidence_id="evidence:target-check",
                    relation_kind="supports",
                    topic_ref=self.topic_ref,
                    item_kind=item_kind,
                    item_text=item,
                ).target_ref
                for item in items
            )
        if self.trend is not None:
            expected_targets.add(
                PortraitProofLink.form(
                    evidence_id="evidence:target-check",
                    relation_kind="supports",
                    topic_ref=self.topic_ref,
                    item_kind="trend",
                    item_text=self.trend,
                    trend_period=self.trend_period,
                ).target_ref
            )
        if (
            any(link.topic_ref != self.topic_ref for link in self.proof_links)
            or {link.target_ref for link in self.proof_links} != expected_targets
        ):
            raise AuthorityValidationError(
                "each portrait conclusion requires its own exact proof link"
            )
        if self.status == "degrade":
            if self.reason is None:
                raise AuthorityValidationError("portrait degradation reason required")
            validate_opaque_text(self.reason, "portrait decision reason")
        elif self.reason is not None:
            raise AuthorityValidationError("unexpected portrait decision reason")

    @property
    def current_understanding_applicable_periods(self) -> tuple[str, ...]:
        return _current_understanding_applicable_periods(
            self.current_understandings,
            self.proof_links,
        )

    @classmethod
    def update(cls, *, topic_ref: str, current_understandings: tuple[str, ...],
               open_judgments: tuple[str, ...], key_unknowns: tuple[str, ...],
               proof_links: tuple[PortraitProofLink, ...], trend: str | None = None,
               trend_period: str | None = None) -> "PortraitDecision":
        return cls("update", topic_ref, current_understandings, open_judgments,
                   key_unknowns, proof_links, trend, trend_period)

    @classmethod
    def no_change(cls) -> "PortraitDecision": return cls("no-change")

    @classmethod
    def maintain(cls, topic_ref: str, reason: str) -> "PortraitDecision":
        return cls("maintain", topic_ref=topic_ref, reason=reason)

    @classmethod
    def degrade(
        cls,
        *,
        topic_ref: str,
        current_understandings: tuple[str, ...],
        open_judgments: tuple[str, ...],
        key_unknowns: tuple[str, ...],
        proof_links: tuple[PortraitProofLink, ...],
        reason: str,
        trend: str | None = None,
        trend_period: str | None = None,
    ) -> "PortraitDecision":
        return cls(
            "degrade",
            topic_ref,
            current_understandings,
            open_judgments,
            key_unknowns,
            proof_links,
            trend,
            trend_period,
            reason,
        )

    @classmethod
    def withdraw(cls, topic_ref: str, reason: str) -> "PortraitDecision":
        return cls("withdraw", topic_ref=topic_ref, reason=reason)

    @classmethod
    def gap(cls, reason: str) -> "PortraitDecision":
        return cls("gap", reason=reason)

    def to_storage(self) -> dict[str, object]:
        return {"status": self.status, "topic_ref": self.topic_ref,
                "current_understandings": list(self.current_understandings),
                "open_judgments": list(self.open_judgments),
                "key_unknowns": list(self.key_unknowns),
                "proof_links": [link.to_storage() for link in self.proof_links],
                "trend": self.trend, "trend_period": self.trend_period,
                "reason": self.reason}

    @classmethod
    def from_storage(cls, value: object) -> "PortraitDecision":
        fields = _mapping(
            value,
            frozenset({
                "status",
                "topic_ref",
                "current_understandings",
                "open_judgments",
                "key_unknowns",
                "proof_links",
                "trend",
                "trend_period",
                "reason",
            }),
            "portrait decision",
        )
        raw_links = fields["proof_links"]
        if type(raw_links) is not list:
            raise AuthorityValidationError("invalid portrait proof links")
        return cls(
            fields["status"],
            fields["topic_ref"],
            _stored_texts(
                fields["current_understandings"],
                "current understandings",
                empty=True,
            ),
            _stored_texts(
                fields["open_judgments"],
                "open judgments",
                empty=True,
            ),
            _stored_texts(
                fields["key_unknowns"],
                "key unknowns",
                empty=True,
            ),
            tuple(PortraitProofLink.from_storage(item) for item in raw_links),
            fields["trend"],
            fields["trend_period"],
            fields["reason"],
        )  # type: ignore[arg-type]


def _validate_portrait_decision_applicable_periods(
    decision: PortraitDecision,
    cards: Mapping[str, EvidenceCard],
) -> None:
    if decision.status not in {"update", "degrade"}:
        return
    for link in decision.proof_links:
        if link.item_kind != "current-understanding":
            continue
        card = cards.get(link.evidence_id)
        if card is None or link.applicable_period != card.applicable_period:
            raise AuthorityValidationError(
                "portrait applicable period did not match its evidence card"
            )


@dataclass(frozen=True)
class SettingsContext:
    source_causal_id: str
    purpose: str
    owner_intent: str
    current_settings_available: bool

    def __post_init__(self) -> None:
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        validate_opaque_text(self.purpose, "daily purpose")
        validate_opaque_text(self.owner_intent, "settings intent")
        if type(self.current_settings_available) is not bool:
            raise AuthorityValidationError("invalid settings availability")

    def to_storage(self) -> dict[str, object]:
        return {"source_causal_id": self.source_causal_id, "purpose": self.purpose,
                "owner_intent": self.owner_intent,
                "current_settings_available": self.current_settings_available}


@dataclass(frozen=True)
class SettingsDecision:
    status: str
    intent: str | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.status not in {"candidate", "gap", "no-change"}:
            raise AuthorityValidationError("invalid settings decision")
        if self.status == "candidate":
            validate_opaque_text(self.intent, "settings intent")
            if self.reason is not None:
                raise AuthorityValidationError("invalid settings candidate")
        elif self.status == "gap":
            if self.intent is not None or self.reason is None:
                raise AuthorityValidationError("invalid settings gap")
            validate_opaque_text(self.reason, "settings reason")
        elif self.intent is not None or self.reason is not None:
            raise AuthorityValidationError("invalid settings no-change decision")

    @classmethod
    def candidate(cls, intent: str) -> "SettingsDecision": return cls("candidate", intent, None)
    @classmethod
    def gap(cls, reason: str) -> "SettingsDecision": return cls("gap", None, reason)
    @classmethod
    def no_change(cls) -> "SettingsDecision": return cls("no-change", None, None)

    def to_storage(self) -> dict[str, object]:
        return {"status": self.status, "intent": self.intent, "reason": self.reason}

    @classmethod
    def from_storage(cls, value: object) -> "SettingsDecision":
        fields = _mapping(
            value,
            frozenset({"status", "intent", "reason"}),
            "settings decision",
        )
        return cls(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class OwnerInquiryContext:
    source_causal_id: str
    purpose: str
    necessary_gap: str
    topic_refs: tuple[str, ...]
    current_topic_views: tuple["PortraitTopicProjection", ...]
    direct_evidence_cards: tuple["EvidenceCard", ...]
    related_task_acceptance_refs: tuple[str, ...]
    task_acceptance_available: bool
    current_control_state_available: bool
    same_gap_already_asked: bool | None
    missing_requirements: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        validate_opaque_text(self.purpose, "daily purpose")
        validate_opaque_text(self.necessary_gap, "necessary gap")
        for topic in _texts(self.topic_refs, "topic references", empty=True): _topic(topic)
        if type(self.current_topic_views) is not tuple or any(
            type(item) is not PortraitTopicProjection
            for item in self.current_topic_views
        ):
            raise AuthorityValidationError("invalid inquiry topic views")
        if type(self.direct_evidence_cards) is not tuple or any(
            type(item) is not EvidenceCard
            for item in self.direct_evidence_cards
        ):
            raise AuthorityValidationError("invalid inquiry evidence cards")
        if len({item.evidence_id for item in self.direct_evidence_cards}) != len(
            self.direct_evidence_cards
        ):
            raise AuthorityValidationError("duplicate inquiry evidence card")
        if any(
            not set(card.topic_refs).intersection(self.topic_refs)
            for card in self.direct_evidence_cards
        ):
            raise AuthorityValidationError("inquiry evidence exceeded topic scope")
        _texts(
            self.related_task_acceptance_refs,
            "related task acceptance references",
            empty=True,
        )
        if type(self.task_acceptance_available) is not bool:
            raise AuthorityValidationError("invalid task acceptance availability")
        if type(self.current_control_state_available) is not bool:
            raise AuthorityValidationError("invalid current control availability")
        if self.same_gap_already_asked is not None and type(
            self.same_gap_already_asked
        ) is not bool:
            raise AuthorityValidationError("invalid same-gap inquiry state")
        missing = set(_texts(
            self.missing_requirements,
            "inquiry missing requirements",
            empty=True,
        ))
        expected_missing = set()
        if not self.topic_refs:
            expected_missing.add("topic-scope-unavailable")
        if not self.task_acceptance_available:
            expected_missing.add("task-acceptance-unavailable")
        if not self.current_control_state_available:
            expected_missing.add("current-control-state-unavailable")
        if self.same_gap_already_asked is None:
            expected_missing.add("same-gap-state-unavailable")
        if missing != expected_missing:
            raise AuthorityValidationError("inquiry missing requirements mismatch")
        if missing:
            if (
                self.current_topic_views
                or self.direct_evidence_cards
                or self.related_task_acceptance_refs
            ):
                raise AuthorityValidationError(
                    "inquiry preflight gap disclosed unavailable health context"
                )
        elif tuple(
            item.topic_ref for item in self.current_topic_views
        ) != self.topic_refs:
            raise AuthorityValidationError("inquiry topic view scope mismatch")

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(card.evidence_id for card in self.direct_evidence_cards)

    def to_storage(self) -> dict[str, object]:
        return {"source_causal_id": self.source_causal_id, "purpose": self.purpose,
                "necessary_gap": self.necessary_gap, "topic_refs": list(self.topic_refs),
                "current_topic_views": [
                    item.to_storage() for item in self.current_topic_views
                ],
                "direct_evidence_cards": [
                    item.to_storage() for item in self.direct_evidence_cards
                ],
                "related_task_acceptance_refs": list(
                    self.related_task_acceptance_refs
                ),
                "task_acceptance_available": self.task_acceptance_available,
                "current_control_state_available": self.current_control_state_available,
                "same_gap_already_asked": self.same_gap_already_asked,
                "missing_requirements": list(self.missing_requirements)}


@dataclass(frozen=True)
class OwnerInquiryDecision:
    status: str
    question: str | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.status not in {"question", "gap", "already-asked"}:
            raise AuthorityValidationError("invalid owner inquiry decision")
        if self.status == "question":
            validate_opaque_text(self.question, "owner inquiry question")
            if self.reason is not None:
                raise AuthorityValidationError("invalid owner inquiry question")
        elif self.status == "gap":
            if self.question is not None or self.reason is None:
                raise AuthorityValidationError("invalid owner inquiry gap")
            validate_opaque_text(self.reason, "owner inquiry reason")
        elif self.question is not None or self.reason is not None:
            raise AuthorityValidationError("invalid repeated owner inquiry")

    @classmethod
    def ask(cls, question: str) -> "OwnerInquiryDecision": return cls("question", question, None)
    @classmethod
    def gap(cls, reason: str) -> "OwnerInquiryDecision": return cls("gap", None, reason)
    @classmethod
    def already_asked(cls) -> "OwnerInquiryDecision": return cls("already-asked", None, None)

    def to_storage(self) -> dict[str, object]:
        return {"status": self.status, "question": self.question, "reason": self.reason}

    @classmethod
    def from_storage(cls, value: object) -> "OwnerInquiryDecision":
        fields = _mapping(
            value,
            frozenset({"status", "question", "reason"}),
            "owner inquiry decision",
        )
        return cls(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class LiteratureContext:
    source_causal_id: str
    purpose: str
    knowledge_gap: str
    topic_refs: tuple[str, ...]
    allowed_sources: tuple[str, ...]
    recipient_boundary: str | None
    existing_qualified_knowledge_cards: tuple["EvidenceCard", ...]

    def __post_init__(self) -> None:
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        validate_opaque_text(self.purpose, "daily purpose")
        validate_opaque_text(self.knowledge_gap, "knowledge gap")
        for topic_ref in _texts(self.topic_refs, "knowledge topic scope"):
            _topic(topic_ref)
        _texts(self.allowed_sources, "allowed knowledge sources", empty=True)
        if self.recipient_boundary is not None:
            validate_opaque_text(self.recipient_boundary, "recipient boundary")
        if type(self.existing_qualified_knowledge_cards) is not tuple or any(
            type(item) is not EvidenceCard
            for item in self.existing_qualified_knowledge_cards
        ):
            raise AuthorityValidationError("invalid qualified knowledge cards")
        if len({
            item.evidence_id for item in self.existing_qualified_knowledge_cards
        }) != len(self.existing_qualified_knowledge_cards):
            raise AuthorityValidationError("duplicate qualified knowledge card")
        if any(
            card.evidence_type != "authoritative-knowledge"
            or not set(card.topic_refs).intersection(self.topic_refs)
            for card in self.existing_qualified_knowledge_cards
        ):
            raise AuthorityValidationError("knowledge card exceeded literature scope")

    def to_storage(self) -> dict[str, object]:
        return {"source_causal_id": self.source_causal_id, "purpose": self.purpose,
                "knowledge_gap": self.knowledge_gap,
                "topic_refs": list(self.topic_refs),
                "allowed_sources": list(self.allowed_sources),
                "recipient_boundary": self.recipient_boundary,
                "existing_qualified_knowledge_cards": [
                    item.to_storage()
                    for item in self.existing_qualified_knowledge_cards
                ]}


@dataclass(frozen=True)
class LiteratureDecision:
    status: str
    candidate_claim: AtomicEvidenceClaim | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.status not in {"candidate", "no-qualified-material", "gap"}:
            raise AuthorityValidationError("invalid literature decision")
        if self.status == "candidate":
            if (type(self.candidate_claim) is not AtomicEvidenceClaim
                or self.candidate_claim.evidence_type != "authoritative-knowledge"
                or self.reason is not None):
                raise AuthorityValidationError("invalid literature candidate")
        else:
            if self.candidate_claim is not None or self.reason is None:
                raise AuthorityValidationError("unqualified literature candidate")
            validate_opaque_text(self.reason, "literature reason")

    @property
    def candidate_ref(self) -> str | None:
        if self.candidate_claim is None:
            return None
        return "literature-candidate:" + stable_digest(
            self.candidate_claim.to_storage()
        ).removeprefix("sha256:")

    @classmethod
    def candidate(cls, claim: AtomicEvidenceClaim) -> "LiteratureDecision":
        return cls("candidate", claim, None)
    @classmethod
    def no_qualified_material(cls, reason: str) -> "LiteratureDecision":
        return cls("no-qualified-material", None, reason)
    @classmethod
    def gap(cls, reason: str) -> "LiteratureDecision": return cls("gap", None, reason)

    def to_storage(self) -> dict[str, object]:
        return {"status": self.status,
                "candidate_claim": None if self.candidate_claim is None else self.candidate_claim.to_storage(),
                "reason": self.reason}

    @classmethod
    def from_storage(cls, value: object) -> "LiteratureDecision":
        fields = _mapping(
            value,
            frozenset({"status", "candidate_claim", "reason"}),
            "literature decision",
        )
        raw_claim = fields["candidate_claim"]
        if raw_claim is not None and type(raw_claim) is not dict:
            raise AuthorityValidationError("invalid literature candidate claim")
        return cls(
            fields["status"],
            None if raw_claim is None else AtomicEvidenceClaim.from_storage(raw_claim),
            fields["reason"],
        )  # type: ignore[arg-type]


def _responsibility_decision_from_storage(
    canonical_name: object,
    value: object,
) -> object:
    decision_types = {
        "health-evidence": EvidenceDecision,
        "health-portrait": PortraitDecision,
        "health-settings": SettingsDecision,
        "health-owner-inquiry": OwnerInquiryDecision,
        "health-literature": LiteratureDecision,
    }
    decision_type = decision_types.get(canonical_name)
    if decision_type is None:
        raise AuthorityValidationError("invalid responsibility decision Skill")
    return decision_type.from_storage(value)


@dataclass(frozen=True)
class DailySkillAsset:
    canonical_name: str
    friendly_name: str
    role: str
    version: str
    asset_digest: str
    disclosure_version: str

    def __post_init__(self) -> None:
        if self.canonical_name not in DAILY_HEALTH_SKILL_NAMES or self.role != DAILY_SKILL_ROLES[self.canonical_name]:
            raise AuthorityValidationError("invalid daily Skill asset")
        if self.canonical_name == "health-steward" and self.role != "A":
            raise AuthorityValidationError("health-steward must be role A")
        validate_opaque_text(self.friendly_name, "friendly name")
        validate_opaque_text(self.version, "Skill version")
        _sha(self.asset_digest, "Skill asset digest")
        validate_opaque_text(self.disclosure_version, "disclosure version")

    def to_storage(self) -> dict[str, object]:
        return {"canonical_name": self.canonical_name, "friendly_name": self.friendly_name,
                "role": self.role, "version": self.version, "asset_digest": self.asset_digest,
                "disclosure_version": self.disclosure_version}

    @classmethod
    def from_storage(cls, value: object) -> "DailySkillAsset":
        return cls(**_mapping(value, frozenset({"canonical_name", "friendly_name", "role", "version",
            "asset_digest", "disclosure_version"}), "daily Skill asset"))  # type: ignore[arg-type]


class DailySkillBundle:
    def __init__(self, assets: tuple[DailySkillAsset, ...]) -> None:
        if type(assets) is not tuple or any(type(a) is not DailySkillAsset for a in assets):
            raise AuthorityValidationError("invalid daily Skill bundle")
        if tuple(a.canonical_name for a in assets) != DAILY_HEALTH_SKILL_NAMES:
            raise AuthorityValidationError("incomplete daily Skill bundle")
        self._assets = assets

    @property
    def assets(self) -> tuple[DailySkillAsset, ...]: return self._assets

    def asset(self, name: str) -> DailySkillAsset:
        for asset in self._assets:
            if asset.canonical_name == name: return asset
        raise AuthorityValidationError("daily Skill asset unavailable")

    def to_storage(self) -> dict[str, object]:
        return {"assets": [asset.to_storage() for asset in self._assets]}

    @classmethod
    def from_storage(cls, value: object) -> "DailySkillBundle":
        fields = _mapping(value, frozenset({"assets"}), "daily Skill bundle")
        assets = fields["assets"]
        if type(assets) is not list:
            raise AuthorityValidationError("invalid daily Skill bundle")
        return cls(tuple(DailySkillAsset.from_storage(item) for item in assets))


@dataclass(frozen=True)
class DailySkillUseFact:
    canonical_name: str
    friendly_name: str
    role: str
    version: str
    asset_digest: str
    disclosure_version: str
    used_at: str
    source_causal_id: str
    input_digest: str
    result_digest: str
    purpose: str
    action: str
    sequence_index: int
    parent_proof_digest: str | None

    def __post_init__(self) -> None:
        DailySkillAsset(self.canonical_name, self.friendly_name, self.role, self.version,
                        self.asset_digest, self.disclosure_version)
        _time(self.used_at, "Skill use timestamp")
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        _sha(self.input_digest, "Skill input digest")
        _sha(self.result_digest, "Skill result digest")
        validate_opaque_text(self.purpose, "daily purpose")
        if self.action not in DAILY_SKILL_ACTIONS:
            raise AuthorityValidationError("invalid daily Skill action")
        if type(self.sequence_index) is not int or self.sequence_index < 0:
            raise AuthorityValidationError("invalid Skill sequence")
        if self.parent_proof_digest is not None:
            _sha(self.parent_proof_digest, "parent proof digest")

    def to_storage(self) -> dict[str, object]:
        return {"canonical_name": self.canonical_name, "friendly_name": self.friendly_name,
                "role": self.role, "version": self.version, "asset_digest": self.asset_digest,
                "disclosure_version": self.disclosure_version, "used_at": self.used_at,
                "source_causal_id": self.source_causal_id, "input_digest": self.input_digest,
                "result_digest": self.result_digest, "purpose": self.purpose,
                "action": self.action, "sequence_index": self.sequence_index,
                "parent_proof_digest": self.parent_proof_digest}

    @classmethod
    def from_storage(cls, value: object) -> "DailySkillUseFact":
        return cls(**_mapping(value, frozenset({"canonical_name", "friendly_name", "role", "version",
            "asset_digest", "disclosure_version", "used_at", "source_causal_id", "input_digest",
            "result_digest", "purpose", "action", "sequence_index", "parent_proof_digest"}),
            "daily Skill use fact"))  # type: ignore[arg-type]

    @property
    def digest(self) -> str: return stable_digest(self.to_storage())


@dataclass(frozen=True)
class DailySkillUseProof:
    skill_use: DailySkillUseFact
    attestor_key_id: str
    signature: str

    def __post_init__(self) -> None:
        if type(self.skill_use) is not DailySkillUseFact:
            raise AuthorityValidationError("invalid daily Skill use fact")
        validate_opaque_text(self.attestor_key_id, "attestor key identifier")
        if type(self.signature) is not str or _HMAC_RE.fullmatch(self.signature) is None:
            raise AuthorityValidationError("invalid daily Skill signature")

    def to_storage(self) -> dict[str, object]:
        return {"skill_use": self.skill_use.to_storage(), "attestor_key_id": self.attestor_key_id,
                "signature": self.signature}

    @classmethod
    def from_storage(cls, value: object) -> "DailySkillUseProof":
        f = _mapping(value, frozenset({"skill_use", "attestor_key_id", "signature"}), "daily Skill proof")
        return cls(DailySkillUseFact.from_storage(f["skill_use"]), f["attestor_key_id"], f["signature"])  # type: ignore[arg-type]

    @property
    def digest(self) -> str: return stable_digest(self.to_storage())


@dataclass(frozen=True)
class DailySkillDisclosure:
    canonical_name: str
    friendly_name: str
    version: str
    disclosure_version: str

    def __post_init__(self) -> None:
        if self.canonical_name not in DAILY_HEALTH_SKILL_NAMES:
            raise AuthorityValidationError("invalid daily Skill disclosure")
        validate_opaque_text(self.friendly_name, "friendly name")
        validate_opaque_text(self.version, "Skill version")
        validate_opaque_text(self.disclosure_version, "disclosure version")

    @classmethod
    def from_asset(cls, asset: DailySkillAsset) -> "DailySkillDisclosure":
        return cls(asset.canonical_name, asset.friendly_name, asset.version, asset.disclosure_version)

    def matches(self, asset: DailySkillAsset) -> bool: return self == self.from_asset(asset)

    def to_storage(self) -> dict[str, object]:
        return {"canonical_name": self.canonical_name, "friendly_name": self.friendly_name,
                "version": self.version, "disclosure_version": self.disclosure_version}

    @classmethod
    def from_storage(cls, value: object) -> "DailySkillDisclosure":
        return cls(**_mapping(value, frozenset({"canonical_name", "friendly_name", "version",
            "disclosure_version"}), "daily Skill disclosure"))  # type: ignore[arg-type]


def _render_daily_skill_disclosure(
    disclosures: tuple[DailySkillDisclosure, ...],
) -> str:
    if not disclosures:
        raise AuthorityValidationError("daily Skill disclosure required")
    entries = "；".join(
        f"{item.friendly_name}（{item.canonical_name}，{item.version}）"
        for item in disclosures
    )
    return f"\n\n🩺 本轮使用：{entries}。"


class DailySkillAttestor:
    def __init__(self, key: bytes, *, key_id: str) -> None:
        if not isinstance(key, bytes) or len(key) < 32:
            raise AuthorityValidationError("invalid daily Skill attestor key")
        validate_opaque_text(key_id, "attestor key identifier")
        self._key, self._key_id = bytes(key), key_id

    @property
    def key_id(self) -> str: return self._key_id

    def attest(self, fact: DailySkillUseFact) -> DailySkillUseProof:
        if type(fact) is not DailySkillUseFact:
            raise AuthorityValidationError("invalid daily Skill use fact")
        body = json.dumps(fact.to_storage(), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return DailySkillUseProof(fact, self._key_id,
            "hmac-sha256:" + hmac.new(self._key, body, hashlib.sha256).hexdigest())

    def verify(self, proof: DailySkillUseProof, asset: DailySkillAsset) -> bool:
        if type(proof) is not DailySkillUseProof or type(asset) is not DailySkillAsset:
            return False
        f = proof.skill_use
        if proof.attestor_key_id != self._key_id or (f.canonical_name, f.friendly_name, f.role,
            f.version, f.asset_digest, f.disclosure_version) != (asset.canonical_name,
            asset.friendly_name, asset.role, asset.version, asset.asset_digest, asset.disclosure_version):
            return False
        return hmac.compare_digest(self.attest(f).signature, proof.signature)


@dataclass(frozen=True)
class EvidenceCard:
    evidence_id: str
    source_causal_id: str
    content: str
    evidence_type: str
    source_kind: str
    occurred_at: str
    applicable_period: str
    purpose: str
    uncertainty: str
    limitations: tuple[str, ...]
    proves: tuple[str, ...]
    does_not_prove: tuple[str, ...]
    topic_refs: tuple[str, ...]
    specific_fields: EvidenceSpecificFields
    series_key: EvidenceSeriesKey
    time_certainty: str
    summary_fields: EvidenceSummaryFields | None
    recorded_at: str
    card_version: str = "evidence-card-v1"
    card_form: str = "detail"

    def __post_init__(self) -> None:
        validate_opaque_text(self.evidence_id, "evidence identifier")
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        AtomicEvidenceClaim(self.content, self.evidence_type, self.source_kind, self.occurred_at,
            self.applicable_period, self.purpose, self.uncertainty, self.limitations, self.proves,
            self.does_not_prove, self.topic_refs, self.specific_fields, self.series_key,
            self.time_certainty, self.summary_fields)
        _time(self.recorded_at, "evidence recorded timestamp")
        if self.card_version != "evidence-card-v1":
            raise AuthorityValidationError("invalid evidence card version")
        expected_form = "summary" if self.summary_fields is not None else "detail"
        if self.card_form != expected_form:
            raise AuthorityValidationError("evidence card form mismatch")

    @classmethod
    def from_claim(
        cls,
        source_causal_id: str,
        claim: AtomicEvidenceClaim,
        *,
        recorded_at: str,
    ) -> "EvidenceCard":
        digest = stable_digest({
            "source_causal_id": source_causal_id,
            "claim": claim.to_storage(),
            "recorded_at": recorded_at,
        })
        return cls("evidence:" + digest.removeprefix("sha256:"), source_causal_id, claim.content,
            claim.evidence_type, claim.source_kind, claim.occurred_at, claim.applicable_period,
            claim.purpose, claim.uncertainty, claim.limitations, claim.proves, claim.does_not_prove,
            claim.topic_refs, claim.specific_fields, claim.series_key, claim.time_certainty,
            claim.summary_fields, recorded_at, card_form=(
                "summary" if claim.summary_fields is not None else "detail"
            ))

    def to_storage(self) -> dict[str, object]:
        claim = AtomicEvidenceClaim(self.content, self.evidence_type, self.source_kind, self.occurred_at,
            self.applicable_period, self.purpose, self.uncertainty, self.limitations, self.proves,
            self.does_not_prove, self.topic_refs, self.specific_fields, self.series_key,
            self.time_certainty, self.summary_fields).to_storage()
        return {"evidence_id": self.evidence_id, "source_causal_id": self.source_causal_id,
                "recorded_at": self.recorded_at, "card_version": self.card_version,
                "card_form": self.card_form, **claim}

    @classmethod
    def from_storage(cls, value: object) -> "EvidenceCard":
        f = _mapping(value, frozenset({"evidence_id", "source_causal_id", "content", "evidence_type",
            "source_kind", "occurred_at", "applicable_period", "purpose", "uncertainty",
            "limitations", "proves", "does_not_prove", "topic_refs", "specific_fields",
            "series_key", "time_certainty", "summary_fields", "recorded_at", "card_version",
            "card_form"}), "evidence card")
        raw = dict(f); evidence_id = raw.pop("evidence_id"); source = raw.pop("source_causal_id")
        recorded_at = raw.pop("recorded_at"); card_version = raw.pop("card_version")
        card_form = raw.pop("card_form")
        card = cls.from_claim(
            source,
            AtomicEvidenceClaim.from_storage(raw),
            recorded_at=recorded_at,
        )  # type: ignore[arg-type]
        if card.evidence_id != evidence_id:
            raise AuthorityValidationError("evidence identifier mismatch")
        return cls(**{**card.__dict__, "card_version": card_version, "card_form": card_form})  # type: ignore[arg-type]


@dataclass(frozen=True)
class EvidenceCompaction:
    """Transient exact retire set; only its bounded batch digest survives."""

    summary_evidence_id: str
    retire_evidence_ids: tuple[str, ...]
    retire_records_digest: str

    def __post_init__(self) -> None:
        validate_opaque_text(self.summary_evidence_id, "summary evidence identifier")
        _texts(self.retire_evidence_ids, "retired evidence identifiers")
        if len(self.retire_evidence_ids) < 2:
            raise AuthorityValidationError("historical summary needs multiple predecessors")
        _sha(self.retire_records_digest, "retired evidence batch digest")
        if self.retire_records_digest != self.digest_for(self.retire_evidence_ids):
            raise AuthorityValidationError("retired evidence batch digest mismatch")

    @staticmethod
    def digest_for(evidence_ids: tuple[str, ...]) -> str:
        return stable_digest({"retire_evidence_ids": list(evidence_ids)})

    @staticmethod
    def predecessor_digest(summary_ids: tuple[str, ...]) -> str:
        _texts(summary_ids, "predecessor summary identifiers")
        return stable_digest({"predecessor_summary_ids": list(summary_ids)})

    @classmethod
    def form(
        cls,
        summary_evidence_id: str,
        retire_evidence_ids: tuple[str, ...],
    ) -> "EvidenceCompaction":
        return cls(
            summary_evidence_id,
            retire_evidence_ids,
            cls.digest_for(retire_evidence_ids),
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "summary_evidence_id": self.summary_evidence_id,
            "retire_evidence_ids": list(self.retire_evidence_ids),
            "retire_records_digest": self.retire_records_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "EvidenceCompaction":
        fields = _mapping(
            value,
            frozenset(
                {
                    "summary_evidence_id",
                    "retire_evidence_ids",
                    "retire_records_digest",
                }
            ),
            "evidence compaction",
        )
        return cls(
            fields["summary_evidence_id"],
            _stored_texts(fields["retire_evidence_ids"], "retired evidence identifiers"),
            fields["retire_records_digest"],
        )  # type: ignore[arg-type]


EVIDENCE_RELATION_KINDS = {
    "topic": frozenset({"relevant"}),
    "proof": frozenset({"supports", "opposes", "qualifies"}),
    "use": frozenset({"used-by"}),
    "history": frozenset({"corrects", "replaces", "withdraws", "summarizes"}),
}
EVIDENCE_RELATION_TARGETS = {
    ("topic", "relevant"): "portrait-topic",
    ("proof", "supports"): "portrait-item",
    ("proof", "opposes"): "portrait-item",
    ("proof", "qualifies"): "portrait-item",
    ("use", "used-by"): "managed-result",
    ("history", "corrects"): "evidence-card",
    ("history", "replaces"): "evidence-card",
    ("history", "withdraws"): "evidence-card",
    ("history", "summarizes"): "evidence-lineage-batch",
}


@dataclass(frozen=True)
class EvidenceRelation:
    """A typed link to the one evidence card; it never copies card content."""

    evidence_id: str
    relation_class: str
    relation_kind: str
    target_kind: str
    target_ref: str

    def __post_init__(self) -> None:
        validate_opaque_text(self.evidence_id, "evidence identifier")
        if (
            self.relation_class not in EVIDENCE_RELATION_KINDS
            or self.relation_kind not in EVIDENCE_RELATION_KINDS[self.relation_class]
        ):
            raise AuthorityValidationError("invalid evidence relation")
        if EVIDENCE_RELATION_TARGETS[(self.relation_class, self.relation_kind)] != self.target_kind:
            raise AuthorityValidationError("invalid evidence relation target kind")
        validate_opaque_text(self.target_ref, "evidence relation target")

    def to_storage(self) -> dict[str, object]:
        return {"evidence_id": self.evidence_id, "relation_class": self.relation_class,
                "relation_kind": self.relation_kind, "target_kind": self.target_kind,
                "target_ref": self.target_ref}

    @classmethod
    def from_storage(cls, value: object) -> "EvidenceRelation":
        fields = _mapping(value, frozenset({"evidence_id", "relation_class",
            "relation_kind", "target_kind", "target_ref"}), "evidence relation")
        return cls(**fields)  # type: ignore[arg-type]


def _is_relevant_correction(
    successor: EvidenceCard,
    target: EvidenceCard,
) -> bool:
    """Keep a correction inside one independently judged physical meaning.

    A correction may legitimately repair method or unit metadata, so the
    complete comparability profile need not remain identical.  It must still
    remain in the same strong evidence type and atomic dimension and share an
    approved portrait topic with the record it supersedes.
    """

    return (
        successor.evidence_type == target.evidence_type
        and successor.series_key.atomic_dimension
        == target.series_key.atomic_dimension
        and bool(set(successor.topic_refs).intersection(target.topic_refs))
    )


def _validate_evidence_relation_ledger(
    cards: Mapping[str, EvidenceCard],
    relations: tuple[EvidenceRelation, ...],
) -> None:
    if len(set(relations)) != len(relations):
        raise AuthorityValidationError("duplicate evidence relation")
    for relation in relations:
        card = cards.get(relation.evidence_id)
        if card is None:
            raise AuthorityValidationError("evidence relation source missing")
        if relation.target_kind == "portrait-topic":
            _topic(relation.target_ref)
        elif relation.target_kind == "evidence-card":
            if relation.target_ref not in cards:
                raise AuthorityValidationError("evidence history target missing")
            target = cards[relation.target_ref]
            if (
                relation.relation_class == "history"
                and relation.relation_kind == "corrects"
                and not _is_relevant_correction(card, target)
            ):
                raise AuthorityValidationError(
                    "evidence correction crossed an atomic dimension"
                )
            if (
                relation.relation_class == "history"
                and relation.relation_kind in {"replaces", "withdraws"}
                and target.evidence_type != card.evidence_type
            ):
                raise AuthorityValidationError("evidence history crossed a strong type")
            if (
                relation.relation_class == "history"
                and relation.relation_kind == "replaces"
                and target.series_key != card.series_key
            ):
                raise AuthorityValidationError(
                    "comparable evidence history crossed a series"
                )
        if relation.relation_class == "proof":
            if card.evidence_type == "authoritative-knowledge" and (
                relation.relation_kind != "qualifies"
            ):
                raise AuthorityValidationError(
                    "general knowledge cannot prove an owner fact"
                )
            if card.evidence_type == "task-process":
                raise AuthorityValidationError(
                    "task process evidence cannot prove a health state"
                )


@dataclass(frozen=True)
class EvidenceApplicabilityChange:
    """Append-only evidence lifecycle event; the original card stays immutable."""

    target_evidence_id: str
    applicability: str
    reason: str
    successor_evidence_id: str | None
    decision_digest: str
    changed_at: str

    def __post_init__(self) -> None:
        validate_opaque_text(self.target_evidence_id, "applicability target")
        if self.applicability not in {
            "corrected",
            "withdrawn",
            "invalidated",
        }:
            raise AuthorityValidationError("invalid evidence applicability")
        validate_opaque_text(self.reason, "applicability reason")
        _sha(self.decision_digest, "applicability decision digest")
        _time(self.changed_at, "applicability change timestamp")
        if self.applicability == "corrected":
            if (
                self.successor_evidence_id is None
                or self.successor_evidence_id == self.target_evidence_id
            ):
                raise AuthorityValidationError(
                    "corrected evidence requires a distinct successor"
                )
            validate_opaque_text(
                self.successor_evidence_id,
                "applicability successor",
            )
        elif self.successor_evidence_id is not None:
            raise AuthorityValidationError(
                "withdrawn evidence cannot carry a successor"
            )

    def to_storage(self) -> dict[str, object]:
        return {
            "target_evidence_id": self.target_evidence_id,
            "applicability": self.applicability,
            "reason": self.reason,
            "successor_evidence_id": self.successor_evidence_id,
            "decision_digest": self.decision_digest,
            "changed_at": self.changed_at,
        }

    @property
    def change_id(self) -> str:
        return "evidence-applicability-change:" + stable_digest(
            self.to_storage()
        ).removeprefix("sha256:")

    @classmethod
    def from_storage(cls, value: object) -> "EvidenceApplicabilityChange":
        return cls(
            **_mapping(
                value,
                frozenset(
                    {
                        "target_evidence_id",
                        "applicability",
                        "reason",
                        "successor_evidence_id",
                        "decision_digest",
                        "changed_at",
                    }
                ),
                "evidence applicability change",
            )
        )  # type: ignore[arg-type]


def _evidence_decision_artifacts(
    *,
    source_causal_id: str,
    claim: AtomicEvidenceClaim | None,
    decision: EvidenceDecision,
    decision_digest: str,
    recorded_at: str,
) -> tuple[
    EvidenceCard | None,
    EvidenceCompaction | None,
    tuple[EvidenceRelation, ...],
    tuple[EvidenceApplicabilityChange, ...],
]:
    """Derive every state artifact from one signed evidence decision."""

    _sha(decision_digest, "evidence decision digest")
    commits_card = decision.status in {"admit", "correct", "compress"}
    if commits_card and (
        type(claim) is not AtomicEvidenceClaim
        or decision.atomic_claim != claim
    ):
        raise AuthorityValidationError(
            "health-evidence changed the planned atomic claim"
        )
    candidate_card = (
        None
        if not commits_card or claim is None
        else EvidenceCard.from_claim(
            source_causal_id,
            claim,
            recorded_at=recorded_at,
        )
    )
    compaction: EvidenceCompaction | None = None
    maintenance_relations: list[EvidenceRelation] = []
    changes: list[EvidenceApplicabilityChange] = []
    if decision.status == "compress":
        if candidate_card is None:
            raise AuthorityValidationError("evidence compression lost its card")
        compaction = EvidenceCompaction.form(
            candidate_card.evidence_id,
            decision.target_evidence_ids,
        )
        maintenance_relations.append(
            EvidenceRelation(
                candidate_card.evidence_id,
                "history",
                "summarizes",
                "evidence-lineage-batch",
                compaction.retire_records_digest,
            )
        )
    elif decision.status == "correct":
        if candidate_card is None or decision.reason is None:
            raise AuthorityValidationError("evidence correction lost its successor")
        for target_id in decision.target_evidence_ids:
            maintenance_relations.append(
                EvidenceRelation(
                    candidate_card.evidence_id,
                    "history",
                    "corrects",
                    "evidence-card",
                    target_id,
                )
            )
            changes.append(
                EvidenceApplicabilityChange(
                    target_id,
                    "corrected",
                    decision.reason,
                    candidate_card.evidence_id,
                    decision_digest,
                    recorded_at,
                )
            )
    elif decision.status in {"withdraw", "invalidate"}:
        if decision.reason is None:
            raise AuthorityValidationError("evidence withdrawal lost its reason")
        applicability = (
            "withdrawn" if decision.status == "withdraw" else "invalidated"
        )
        for target_id in decision.target_evidence_ids:
            maintenance_relations.append(
                EvidenceRelation(
                    target_id,
                    "history",
                    "withdraws",
                    "evidence-card",
                    target_id,
                )
            )
            changes.append(
                EvidenceApplicabilityChange(
                    target_id,
                    applicability,
                    decision.reason,
                    None,
                    decision_digest,
                    recorded_at,
                )
            )
    return (
        candidate_card,
        compaction,
        tuple(maintenance_relations),
        tuple(changes),
    )


def _expected_stage_evidence_artifacts(
    draft: "DailyTurnDraft",
) -> tuple[
    tuple[EvidenceCard, ...],
    tuple[EvidenceCompaction, ...],
    tuple[EvidenceRelation, ...],
    tuple[EvidenceApplicabilityChange, ...],
]:
    operations = (
        tuple((claim, None) for claim in draft.steward_plan.atomic_claims)
        + tuple(
            (request.replacement_claim, request)
            for request in draft.steward_plan.evidence_maintenance_requests
        )
        if "health-evidence" in draft.steward_plan.selected_skills
        else ()
    )
    if len(operations) != len(draft.responsibility_results):
        raise AuthorityValidationError("evidence operation count mismatch")
    cards: list[EvidenceCard] = []
    compactions: list[EvidenceCompaction] = []
    maintenance_relations: list[EvidenceRelation] = []
    changes: list[EvidenceApplicabilityChange] = []
    for (claim, request), result in zip(
        operations,
        draft.responsibility_results,
    ):
        if (
            result.canonical_name != "health-evidence"
            or type(result.decision) is not EvidenceDecision
        ):
            raise AuthorityValidationError("invalid evidence responsibility result")
        decision = result.decision
        if request is None:
            if decision.status in {"correct", "withdraw", "invalidate"}:
                raise AuthorityValidationError(
                    "evidence lifecycle decision lacks plan authority"
                )
        elif (
            decision.status != request.action
            or decision.target_evidence_ids != request.target_evidence_ids
            or decision.reason != request.reason
            or decision.atomic_claim != request.replacement_claim
        ):
            raise AuthorityValidationError(
                "evidence maintenance decision changed its request"
            )
        card, compaction, relations, decision_changes = (
            _evidence_decision_artifacts(
                source_causal_id=draft.source_causal_id,
                claim=claim,
                decision=decision,
                decision_digest=result.result_digest,
                recorded_at=draft.created_at,
            )
        )
        expected_card_refs = () if card is None else (card.evidence_id,)
        if (
            result.candidate_refs != expected_card_refs
            or result.candidate_change_ids
            != tuple(change.change_id for change in decision_changes)
        ):
            raise AuthorityValidationError("evidence candidate binding mismatch")
        if card is not None:
            cards.append(card)
        if compaction is not None:
            compactions.append(compaction)
        maintenance_relations.extend(relations)
        changes.extend(decision_changes)
    topic_relations = tuple(
        EvidenceRelation(
            card.evidence_id,
            "topic",
            "relevant",
            "portrait-topic",
            topic_ref,
        )
        for card in cards
        for topic_ref in card.topic_refs
    )
    return (
        tuple(cards),
        tuple(compactions),
        tuple(dict.fromkeys((*topic_relations, *maintenance_relations))),
        tuple(changes),
    )


@dataclass(frozen=True)
class PortraitTopic:
    topic_ref: str
    current_understandings: tuple[str, ...]
    current_understanding_applicable_periods: tuple[str, ...]
    open_judgments: tuple[str, ...]
    key_unknowns: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    trend: str | None = None
    trend_period: str | None = None
    related_task_ids: tuple[str, ...] = ()
    evidence_relations: tuple[EvidenceRelation, ...] = ()

    def __post_init__(self) -> None:
        _topic(self.topic_ref)
        _display_texts(self.current_understandings, "current understandings")
        _aligned_periods(
            self.current_understanding_applicable_periods,
            len(self.current_understandings),
            "current understanding applicable periods",
        )
        _display_texts(self.open_judgments, "open judgments")
        _display_texts(self.key_unknowns, "key unknowns")
        _texts(self.evidence_ids, "evidence identifiers")
        _texts(self.related_task_ids, "related task identifiers", empty=True)
        if type(self.evidence_relations) is not tuple or any(
            type(relation) is not EvidenceRelation for relation in self.evidence_relations
        ):
            raise AuthorityValidationError("invalid portrait evidence relations")
        if any(
            relation.evidence_id not in self.evidence_ids
            or relation.relation_class not in {"topic", "proof"}
            for relation in self.evidence_relations
        ):
            raise AuthorityValidationError("portrait relation exceeded its evidence scope")
        if self.trend is not None:
            validate_opaque_text(self.trend, "portrait trend")
            if (
                len(self.trend) > 20
                or len(self.evidence_ids) < 2
                or self.trend_period is None
            ):
                raise AuthorityValidationError("one observation cannot establish a trend")
            validate_opaque_text(self.trend_period, "portrait trend period")
        elif self.trend_period is not None:
            raise AuthorityValidationError("portrait trend period without trend")

    @classmethod
    def from_decision(cls, decision: PortraitDecision) -> "PortraitTopic":
        if decision.status not in {"update", "degrade"} or decision.topic_ref is None:
            raise AuthorityValidationError("portrait update required")
        evidence_ids = tuple(dict.fromkeys(
            link.evidence_id for link in decision.proof_links
        ))
        relations = tuple(dict.fromkeys((
            *(
                EvidenceRelation(
                    evidence_id,
                    "topic",
                    "relevant",
                    "portrait-topic",
                    decision.topic_ref,
                )
                for evidence_id in evidence_ids
            ),
            *(link.to_relation() for link in decision.proof_links),
        )))
        return cls(
            decision.topic_ref,
            decision.current_understandings,
            decision.current_understanding_applicable_periods,
            decision.open_judgments,
            decision.key_unknowns,
            evidence_ids,
            trend=decision.trend,
            trend_period=decision.trend_period,
            evidence_relations=relations,
        )

    def to_storage(self) -> dict[str, object]:
        return {"topic_ref": self.topic_ref, "current_understandings": list(self.current_understandings),
            "current_understanding_applicable_periods": list(
                self.current_understanding_applicable_periods
            ),
            "open_judgments": list(self.open_judgments), "key_unknowns": list(self.key_unknowns),
            "evidence_ids": list(self.evidence_ids), "trend": self.trend,
            "trend_period": self.trend_period,
            "related_task_ids": list(self.related_task_ids),
            "evidence_relations": [relation.to_storage() for relation in self.evidence_relations]}

    @classmethod
    def from_storage(cls, value: object) -> "PortraitTopic":
        f = _mapping(value, frozenset({"topic_ref", "current_understandings",
            "current_understanding_applicable_periods", "open_judgments",
            "key_unknowns", "evidence_ids", "trend", "related_task_ids",
            "trend_period", "evidence_relations"}), "portrait topic")
        relations = f["evidence_relations"]
        if type(relations) is not list:
            raise AuthorityValidationError("invalid portrait evidence relations")
        current_understandings = _stored_texts(
            f["current_understandings"],
            "current understandings",
            empty=True,
        )
        return cls(f["topic_ref"], current_understandings,
            _stored_aligned_periods(
                f["current_understanding_applicable_periods"],
                len(current_understandings),
                "current understanding applicable periods",
            ),
            _stored_texts(f["open_judgments"], "open judgments", empty=True),
            _stored_texts(f["key_unknowns"], "key unknowns", empty=True),
            _stored_texts(f["evidence_ids"], "evidence identifiers"), f["trend"],
            f["trend_period"],
            _stored_texts(f["related_task_ids"], "related task identifiers", empty=True),
            tuple(EvidenceRelation.from_storage(item) for item in relations))  # type: ignore[arg-type]


def _validate_portrait_topic_applicable_periods(
    topic: PortraitTopic,
    cards: Mapping[str, EvidenceCard],
) -> None:
    for understanding, applicable_period in zip(
        topic.current_understandings,
        topic.current_understanding_applicable_periods,
    ):
        target_ref = _portrait_item_target_ref(
            topic_ref=topic.topic_ref,
            item_kind="current-understanding",
            item_text=understanding,
            trend_period=None,
            applicable_period=applicable_period,
        )
        proof_relations = tuple(
            relation
            for relation in topic.evidence_relations
            if relation.relation_class == "proof"
            and relation.target_kind == "portrait-item"
            and relation.target_ref == target_ref
        )
        if not proof_relations or any(
            cards.get(relation.evidence_id) is None
            or cards[relation.evidence_id].applicable_period != applicable_period
            for relation in proof_relations
        ):
            raise AuthorityValidationError(
                "portrait applicable period did not match its evidence card"
            )


@dataclass(frozen=True)
class PortraitRevision:
    """One immutable, signed transition in a portrait topic's history."""

    topic_ref: str
    action: str
    previous_topic: PortraitTopic | None
    next_topic: PortraitTopic | None
    reason: str
    decision_digest: str
    changed_at: str

    def __post_init__(self) -> None:
        _topic(self.topic_ref)
        if self.action not in {"update", "degrade", "withdraw"}:
            raise AuthorityValidationError("invalid portrait revision action")
        for snapshot in (self.previous_topic, self.next_topic):
            if snapshot is not None and (
                type(snapshot) is not PortraitTopic
                or snapshot.topic_ref != self.topic_ref
            ):
                raise AuthorityValidationError(
                    "portrait revision snapshot changed topic"
                )
        if self.action in {"update", "degrade"}:
            if self.next_topic is None:
                raise AuthorityValidationError(
                    "portrait revision next snapshot required"
                )
        elif self.previous_topic is None or self.next_topic is not None:
            raise AuthorityValidationError(
                "portrait withdrawal revision snapshots invalid"
            )
        validate_opaque_text(self.reason, "portrait revision reason")
        _sha(self.decision_digest, "portrait revision decision digest")
        _time(self.changed_at, "portrait revision timestamp")

    def to_storage(self) -> dict[str, object]:
        return {
            "topic_ref": self.topic_ref,
            "action": self.action,
            "previous_topic": (
                None
                if self.previous_topic is None
                else self.previous_topic.to_storage()
            ),
            "next_topic": (
                None if self.next_topic is None else self.next_topic.to_storage()
            ),
            "reason": self.reason,
            "decision_digest": self.decision_digest,
            "changed_at": self.changed_at,
        }

    @classmethod
    def from_storage(cls, value: object) -> "PortraitRevision":
        fields = _mapping(
            value,
            frozenset({
                "topic_ref",
                "action",
                "previous_topic",
                "next_topic",
                "reason",
                "decision_digest",
                "changed_at",
            }),
            "portrait revision",
        )
        previous = fields["previous_topic"]
        next_topic = fields["next_topic"]
        return cls(
            fields["topic_ref"],
            fields["action"],
            None if previous is None else PortraitTopic.from_storage(previous),
            (
                None
                if next_topic is None
                else PortraitTopic.from_storage(next_topic)
            ),
            fields["reason"],
            fields["decision_digest"],
            fields["changed_at"],
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class EvidenceSeriesWindow:
    """Derived logical retention window for one exact comparable sequence."""

    series_key: EvidenceSeriesKey
    recent_detail_ids: tuple[str, ...]
    protected_detail_ids: tuple[str, ...]
    unorderable_detail_ids: tuple[str, ...]
    window_outside_detail_ids: tuple[str, ...]
    summary_ids: tuple[str, ...]
    summary_threshold_detail_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.series_key) is not EvidenceSeriesKey:
            raise AuthorityValidationError("invalid evidence series window")
        for value, name in (
            (self.recent_detail_ids, "recent evidence details"),
            (self.protected_detail_ids, "protected evidence details"),
            (self.unorderable_detail_ids, "unorderable evidence details"),
            (self.window_outside_detail_ids, "window-outside evidence details"),
            (self.summary_ids, "historical evidence summaries"),
            (self.summary_threshold_detail_ids, "summary threshold details"),
        ):
            _texts(value, name, empty=True)
        if len(self.recent_detail_ids) > 5:
            raise AuthorityValidationError("recent evidence detail budget exceeded")
        groups = (
            self.recent_detail_ids,
            self.protected_detail_ids,
            self.window_outside_detail_ids,
            self.summary_ids,
        )
        flattened = tuple(item for group in groups for item in group)
        if len(flattened) != len(set(flattened)):
            raise AuthorityValidationError("evidence series window overlaps")
        if not set(self.unorderable_detail_ids) <= set(self.protected_detail_ids):
            raise AuthorityValidationError("unorderable evidence must stay protected")
        expected_threshold = (
            self.window_outside_detail_ids
            if len(self.window_outside_detail_ids) >= 3
            else ()
        )
        if self.summary_threshold_detail_ids != expected_threshold:
            raise AuthorityValidationError("invalid evidence summary threshold")

    def to_storage(self) -> dict[str, object]:
        return {
            "series_key": self.series_key.to_storage(),
            "recent_detail_ids": list(self.recent_detail_ids),
            "protected_detail_ids": list(self.protected_detail_ids),
            "unorderable_detail_ids": list(self.unorderable_detail_ids),
            "window_outside_detail_ids": list(self.window_outside_detail_ids),
            "summary_ids": list(self.summary_ids),
            "summary_threshold_detail_ids": list(
                self.summary_threshold_detail_ids
            ),
        }

    @classmethod
    def from_storage(cls, value: object) -> "EvidenceSeriesWindow":
        fields = _mapping(
            value,
            frozenset(
                {
                    "series_key",
                    "recent_detail_ids",
                    "protected_detail_ids",
                    "unorderable_detail_ids",
                    "window_outside_detail_ids",
                    "summary_ids",
                    "summary_threshold_detail_ids",
                }
            ),
            "evidence series window",
        )
        return cls(
            EvidenceSeriesKey.from_storage(fields["series_key"]),
            _stored_texts(fields["recent_detail_ids"], "recent evidence details", empty=True),
            _stored_texts(fields["protected_detail_ids"], "protected evidence details", empty=True),
            _stored_texts(fields["unorderable_detail_ids"], "unorderable evidence details", empty=True),
            _stored_texts(fields["window_outside_detail_ids"], "window-outside evidence details", empty=True),
            _stored_texts(fields["summary_ids"], "historical evidence summaries", empty=True),
            _stored_texts(fields["summary_threshold_detail_ids"], "summary threshold details", empty=True),
        )


@dataclass(frozen=True)
class EvidenceTypePreview:
    evidence_type: str
    preview_ids: tuple[str, ...]
    additional_count: int

    def __post_init__(self) -> None:
        if self.evidence_type not in EVIDENCE_TYPES:
            raise AuthorityValidationError("invalid evidence preview type")
        _texts(self.preview_ids, "evidence preview identifiers", empty=True)
        if len(self.preview_ids) > 3:
            raise AuthorityValidationError("evidence preview budget exceeded")
        if type(self.additional_count) is not int or self.additional_count < 0:
            raise AuthorityValidationError("invalid evidence preview remainder")

    @property
    def full_list_available(self) -> bool:
        return self.additional_count > 0

    def to_storage(self) -> dict[str, object]:
        return {
            "evidence_type": self.evidence_type,
            "preview_ids": list(self.preview_ids),
            "additional_count": self.additional_count,
        }

    @classmethod
    def from_storage(cls, value: object) -> "EvidenceTypePreview":
        fields = _mapping(
            value,
            frozenset({"evidence_type", "preview_ids", "additional_count"}),
            "evidence type preview",
        )
        return cls(
            fields["evidence_type"],
            _stored_texts(fields["preview_ids"], "evidence preview identifiers", empty=True),
            fields["additional_count"],
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class PortraitTopicProjection:
    topic_ref: str
    current_status: str
    current_understandings: tuple[str, ...]
    current_understanding_applicable_periods: tuple[str, ...]
    open_judgments: tuple[str, ...]
    key_unknowns: tuple[str, ...]
    trend: str | None
    trend_period: str | None
    related_task_preview_ids: tuple[str, ...]
    additional_task_count: int
    evidence_previews: tuple[EvidenceTypePreview, ...]

    def __post_init__(self) -> None:
        _topic(self.topic_ref)
        if self.current_status not in {"known", "unknown"}:
            raise AuthorityValidationError("invalid portrait topic status")
        _display_texts(self.current_understandings, "current understandings")
        _aligned_periods(
            self.current_understanding_applicable_periods,
            len(self.current_understandings),
            "current understanding applicable periods",
        )
        _display_texts(self.open_judgments, "open judgments")
        _display_texts(self.key_unknowns, "key unknowns")
        if self.trend is not None:
            validate_opaque_text(self.trend, "portrait trend")
            if len(self.trend) > 20:
                raise AuthorityValidationError("portrait trend display budget exceeded")
            if self.trend_period is None:
                raise AuthorityValidationError("portrait trend period required")
            validate_opaque_text(self.trend_period, "portrait trend period")
        elif self.trend_period is not None:
            raise AuthorityValidationError("portrait trend period without trend")
        _texts(self.related_task_preview_ids, "related task preview", empty=True)
        if len(self.related_task_preview_ids) > 3:
            raise AuthorityValidationError("related task preview budget exceeded")
        if type(self.additional_task_count) is not int or self.additional_task_count < 0:
            raise AuthorityValidationError("invalid related task remainder")
        if (
            type(self.evidence_previews) is not tuple
            or tuple(item.evidence_type for item in self.evidence_previews)
            != EVIDENCE_TYPE_ORDER
        ):
            raise AuthorityValidationError("incomplete three-type evidence navigation")

    @property
    def status(self) -> str:
        """Public shorthand for the fixed topic's current known/unknown state."""

        return self.current_status

    def to_storage(self) -> dict[str, object]:
        return {
            "topic_ref": self.topic_ref,
            "current_status": self.current_status,
            "current_understandings": list(self.current_understandings),
            "current_understanding_applicable_periods": list(
                self.current_understanding_applicable_periods
            ),
            "open_judgments": list(self.open_judgments),
            "key_unknowns": list(self.key_unknowns),
            "trend": self.trend,
            "trend_period": self.trend_period,
            "related_task_preview_ids": list(self.related_task_preview_ids),
            "additional_task_count": self.additional_task_count,
            "evidence_previews": [item.to_storage() for item in self.evidence_previews],
        }

    @classmethod
    def from_storage(cls, value: object) -> "PortraitTopicProjection":
        fields = _mapping(
            value,
            frozenset(
                {
                    "topic_ref",
                    "current_status",
                    "current_understandings",
                    "current_understanding_applicable_periods",
                    "open_judgments",
                    "key_unknowns",
                    "trend",
                    "trend_period",
                    "related_task_preview_ids",
                    "additional_task_count",
                    "evidence_previews",
                }
            ),
            "portrait topic projection",
        )
        previews = fields["evidence_previews"]
        if type(previews) is not list:
            raise AuthorityValidationError("invalid evidence previews")
        current_understandings = _stored_texts(
            fields["current_understandings"],
            "current understandings",
            empty=True,
        )
        return cls(
            fields["topic_ref"],
            fields["current_status"],
            current_understandings,
            _stored_aligned_periods(
                fields["current_understanding_applicable_periods"],
                len(current_understandings),
                "current understanding applicable periods",
            ),
            _stored_texts(fields["open_judgments"], "open judgments", empty=True),
            _stored_texts(fields["key_unknowns"], "key unknowns", empty=True),
            fields["trend"],
            fields["trend_period"],
            _stored_texts(fields["related_task_preview_ids"], "related task preview", empty=True),
            fields["additional_task_count"],
            tuple(EvidenceTypePreview.from_storage(item) for item in previews),
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class DailyHealthProjection:
    state_digest: str
    evidence_count: int
    portrait_topic_refs: tuple[str, ...]
    unknown_domains: tuple[str, ...]
    topic_views: tuple[PortraitTopicProjection, ...] = ()
    series_windows: tuple[EvidenceSeriesWindow, ...] = ()

    def __post_init__(self) -> None:
        _sha(self.state_digest, "daily state digest")
        if type(self.evidence_count) is not int or self.evidence_count < 0:
            raise AuthorityValidationError("invalid evidence count")
        _texts(self.portrait_topic_refs, "portrait topic references", empty=True)
        _texts(self.unknown_domains, "unknown domains", empty=True)
        if type(self.topic_views) is not tuple or any(
            type(item) is not PortraitTopicProjection for item in self.topic_views
        ):
            raise AuthorityValidationError("invalid portrait topic projections")
        if type(self.series_windows) is not tuple or any(
            type(item) is not EvidenceSeriesWindow for item in self.series_windows
        ):
            raise AuthorityValidationError("invalid evidence series windows")
        if self.portrait_topic_refs != PORTRAIT_TOPIC_REFS or tuple(
            item.topic_ref for item in self.topic_views
        ) != PORTRAIT_TOPIC_REFS:
            raise AuthorityValidationError(
                "portrait projection does not match the fixed schema order"
            )
        known_domains = {
            item.topic_ref.split("/", 1)[0]
            for item in self.topic_views
            if item.current_status == "known"
        }
        expected_unknown_domains = tuple(
            domain_ref
            for domain_ref in PORTRAIT_DOMAIN_REFS
            if domain_ref not in known_domains
        )
        if self.unknown_domains != expected_unknown_domains:
            raise AuthorityValidationError(
                "portrait unknown domains do not match topic status"
            )

    def to_storage(self) -> dict[str, object]:
        return {"state_digest": self.state_digest, "evidence_count": self.evidence_count,
                "portrait_topic_refs": list(self.portrait_topic_refs),
                "unknown_domains": list(self.unknown_domains),
                "topic_views": [item.to_storage() for item in self.topic_views],
                "series_windows": [item.to_storage() for item in self.series_windows]}

    @classmethod
    def from_storage(cls, value: object) -> "DailyHealthProjection":
        fields = _mapping(value, frozenset({"state_digest", "evidence_count",
            "portrait_topic_refs", "unknown_domains", "topic_views",
            "series_windows"}), "daily health projection")
        topic_views = fields["topic_views"]
        series_windows = fields["series_windows"]
        if type(topic_views) is not list or type(series_windows) is not list:
            raise AuthorityValidationError("invalid daily health projection lists")
        return cls(fields["state_digest"], fields["evidence_count"],
            _stored_texts(fields["portrait_topic_refs"], "portrait topic references", empty=True),
            _stored_texts(fields["unknown_domains"], "unknown domains", empty=True),
            tuple(PortraitTopicProjection.from_storage(item) for item in topic_views),
            tuple(EvidenceSeriesWindow.from_storage(item) for item in series_windows))  # type: ignore[arg-type]


@dataclass(frozen=True)
class DailyHealthNavigation:
    """Body-free top-level navigation available to the coordinating Skill."""

    state_digest: str
    evidence_count: int
    portrait_topic_refs: tuple[str, ...]
    unknown_domains: tuple[str, ...]

    def __post_init__(self) -> None:
        _sha(self.state_digest, "daily state digest")
        if type(self.evidence_count) is not int or self.evidence_count < 0:
            raise AuthorityValidationError("invalid evidence count")
        _texts(self.portrait_topic_refs, "portrait topic references", empty=True)
        _texts(self.unknown_domains, "unknown domains", empty=True)
        if self.portrait_topic_refs != PORTRAIT_TOPIC_REFS:
            raise AuthorityValidationError(
                "portrait navigation does not match the fixed schema order"
            )
        if self.unknown_domains != tuple(
            domain_ref
            for domain_ref in PORTRAIT_DOMAIN_REFS
            if domain_ref in set(self.unknown_domains)
        ):
            raise AuthorityValidationError("invalid portrait domain navigation")

    @classmethod
    def from_projection(
        cls,
        projection: DailyHealthProjection,
    ) -> "DailyHealthNavigation":
        if type(projection) is not DailyHealthProjection:
            raise AuthorityValidationError("invalid daily health projection")
        return cls(
            projection.state_digest,
            projection.evidence_count,
            projection.portrait_topic_refs,
            projection.unknown_domains,
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "state_digest": self.state_digest,
            "evidence_count": self.evidence_count,
            "portrait_topic_refs": list(self.portrait_topic_refs),
            "unknown_domains": list(self.unknown_domains),
        }


@dataclass(frozen=True)
class DailyTurnResult:
    source_causal_id: str
    record_id: str
    transition_id: str
    evidence_ids: tuple[str, ...]
    portrait_topics: tuple[str, ...]
    skill_disclosures: tuple[DailySkillDisclosure, ...]
    owner_reply: str
    evidence_change_ids: tuple[str, ...] = ()
    answer_status: str | None = None
    answer_resolution_digest: str | None = None

    def __post_init__(self) -> None:
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        validate_opaque_text(self.record_id, "daily turn record identifier")
        validate_opaque_text(self.transition_id, "daily turn transition identifier")
        _texts(self.evidence_ids, "evidence identifiers", empty=True)
        _texts(self.portrait_topics, "portrait topic references", empty=True)
        _texts(self.evidence_change_ids, "evidence change identifiers", empty=True)
        if type(self.skill_disclosures) is not tuple or not self.skill_disclosures or any(
            type(item) is not DailySkillDisclosure for item in self.skill_disclosures):
            raise AuthorityValidationError("invalid daily Skill disclosures")
        _owner_reply_text(self.owner_reply, "owner reply intent")
        if (self.answer_status is None) != (self.answer_resolution_digest is None):
            raise AuthorityValidationError("incomplete model answer result")
        if self.answer_status is not None:
            if self.answer_status not in {"failed-closed", "rendered"}:
                raise AuthorityValidationError("invalid model answer status")
            _sha(self.answer_resolution_digest, "model answer resolution")

    def to_storage(self) -> dict[str, object]:
        stored: dict[str, object] = {"source_causal_id": self.source_causal_id, "record_id": self.record_id,
            "transition_id": self.transition_id, "evidence_ids": list(self.evidence_ids),
            "portrait_topics": list(self.portrait_topics),
            "skill_disclosures": [d.to_storage() for d in self.skill_disclosures],
            "owner_reply": self.owner_reply,
            "evidence_change_ids": list(self.evidence_change_ids)}
        if self.answer_status is not None:
            stored["answer_status"] = self.answer_status
            stored["answer_resolution_digest"] = self.answer_resolution_digest
        return stored

    @classmethod
    def from_storage(cls, value: object) -> "DailyTurnResult":
        legacy_fields = frozenset({"source_causal_id", "record_id", "transition_id",
            "evidence_ids", "portrait_topics", "skill_disclosures", "owner_reply",
            "evidence_change_ids"})
        if type(value) is not dict or frozenset(value) not in (
            legacy_fields,
            legacy_fields | {"answer_status", "answer_resolution_digest"},
        ):
            raise AuthorityValidationError("invalid daily turn result")
        f = value
        disclosures = f["skill_disclosures"]
        if type(disclosures) is not list: raise AuthorityValidationError("invalid Skill disclosures")
        return cls(f["source_causal_id"], f["record_id"], f["transition_id"],
            _stored_texts(f["evidence_ids"], "evidence identifiers", empty=True),
            _stored_texts(f["portrait_topics"], "portrait topic references", empty=True),
            tuple(DailySkillDisclosure.from_storage(x) for x in disclosures), f["owner_reply"],
            _stored_texts(
                f["evidence_change_ids"],
                "evidence change identifiers",
                empty=True,
            ),
            f.get("answer_status"),
            f.get("answer_resolution_digest"),
        )  # type: ignore[arg-type]


@dataclass(frozen=True)
class DailyTurnDraft:
    source_causal_id: str
    source_digest: str
    base_state_digest: str
    purpose: str
    created_at: str
    steward_plan: StewardPlan
    responsibility_results: tuple[ResponsibilityResult, ...]
    reply_atoms: tuple[OwnerReplyAtom, ...]
    steward_resolution: StewardResolution | None
    evidence_cards: tuple[EvidenceCard, ...]
    portrait_topics: tuple[PortraitTopic, ...]
    evidence_relations: tuple[EvidenceRelation, ...]
    evidence_compactions: tuple[EvidenceCompaction, ...]
    skill_proofs: tuple[DailySkillUseProof, ...]
    skill_disclosures: tuple[DailySkillDisclosure, ...]
    owner_reply: str
    turn_kind: str = "complete-turn"
    evidence_stage: "DailyTurnDraft | None" = None
    portrait_withdrawals: tuple[str, ...] = ()
    evidence_applicability_changes: tuple[EvidenceApplicabilityChange, ...] = ()
    model_answer_resolution: ModelAnswerResolution | None = None

    def __post_init__(self) -> None:
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        _sha(self.source_digest, "source digest"); _sha(self.base_state_digest, "base state digest")
        validate_opaque_text(self.purpose, "daily purpose"); _time(self.created_at, "daily timestamp")
        if type(self.steward_plan) is not StewardPlan or self.steward_plan.purpose != self.purpose:
            raise AuthorityValidationError("invalid steward plan")
        if self.turn_kind not in {"evidence-stage", "complete-turn"}:
            raise AuthorityValidationError("invalid daily turn kind")
        for value, expected, name in (
            (self.responsibility_results, ResponsibilityResult, "responsibility results"),
            (self.reply_atoms, OwnerReplyAtom, "reply atoms"),
            (self.evidence_cards, EvidenceCard, "evidence cards"),
            (self.portrait_topics, PortraitTopic, "portrait topics"),
            (self.evidence_relations, EvidenceRelation, "evidence relations"),
            (self.evidence_compactions, EvidenceCompaction, "evidence compactions"),
            (
                self.evidence_applicability_changes,
                EvidenceApplicabilityChange,
                "evidence applicability changes",
            ),
            (self.skill_proofs, DailySkillUseProof, "Skill proofs"),
            (self.skill_disclosures, DailySkillDisclosure, "Skill disclosures"),
        ):
            if type(value) is not tuple or any(type(item) is not expected for item in value):
                raise AuthorityValidationError(f"invalid {name}")
        if not self.skill_proofs or not self.skill_disclosures:
            raise AuthorityValidationError("daily Skill proof required")
        if self.model_answer_resolution is not None and type(
            self.model_answer_resolution
        ) is not ModelAnswerResolution:
            raise AuthorityValidationError("invalid model answer resolution")
        if len({c.evidence_id for c in self.evidence_cards}) != len(self.evidence_cards):
            raise AuthorityValidationError("duplicate evidence card")
        for topic_ref in _texts(
            self.portrait_withdrawals,
            "portrait withdrawal topics",
            empty=True,
        ):
            _topic(topic_ref)
        proof_names = tuple(
            proof.skill_use.canonical_name for proof in self.skill_proofs
        )
        result_names = tuple(
            result.canonical_name for result in self.responsibility_results
        )
        if self.turn_kind == "evidence-stage":
            if (
                self.evidence_stage is not None
                or self.steward_resolution is not None
                or self.reply_atoms
                or self.portrait_topics
                or self.portrait_withdrawals
                or self.owner_reply != ""
                or any(name != "health-evidence" for name in proof_names[1:])
                or any(name != "health-evidence" for name in result_names)
                or self.model_answer_resolution is not None
            ):
                raise AuthorityValidationError("evidence stage exceeded its authority")
        else:
            if (
                type(self.evidence_stage) is not DailyTurnDraft
                or self.evidence_stage.turn_kind != "evidence-stage"
                or type(self.steward_resolution) is not StewardResolution
                or self.evidence_cards
                or self.evidence_compactions
                or self.evidence_applicability_changes
                or set(self.portrait_withdrawals)
                & {topic.topic_ref for topic in self.portrait_topics}
            ):
                raise AuthorityValidationError("invalid complete daily turn")
            _owner_reply_text(self.owner_reply, "owner reply intent")

    @property
    def record_id(self) -> str:
        return "daily-" + self.turn_kind + ":" + stable_digest({
            "source_causal_id": self.source_causal_id,
            "turn_kind": self.turn_kind,
        }).removeprefix("sha256:")
    @property
    def digest(self) -> str: return stable_digest(self.to_storage())
    @property
    def revision_digest(self) -> str: return self.digest
    @property
    def transition_id(self) -> str:
        return (
            "daily-"
            + self.turn_kind
            + "-transition:"
            + self.digest.removeprefix("sha256:")
        )
    @property
    def payload_digest(self) -> str: return self.digest

    def to_storage(self) -> dict[str, object]:
        stored: dict[str, object] = {"source_causal_id": self.source_causal_id, "source_digest": self.source_digest,
            "base_state_digest": self.base_state_digest, "purpose": self.purpose,
            "created_at": self.created_at,
            "steward_plan": self.steward_plan.to_storage(),
            "responsibility_results": [
                item.to_storage() for item in self.responsibility_results
            ],
            "reply_atoms": [item.to_storage() for item in self.reply_atoms],
            "steward_resolution": (
                None
                if self.steward_resolution is None
                else self.steward_resolution.to_storage()
            ),
            "evidence_cards": [c.to_storage() for c in self.evidence_cards],
            "portrait_topics": [t.to_storage() for t in self.portrait_topics],
            "evidence_relations": [r.to_storage() for r in self.evidence_relations],
            "evidence_compactions": [c.to_storage() for c in self.evidence_compactions],
            "skill_proofs": [p.to_storage() for p in self.skill_proofs],
            "skill_disclosures": [d.to_storage() for d in self.skill_disclosures],
            "owner_reply": self.owner_reply,
            "turn_kind": self.turn_kind,
            "evidence_stage": (
                None
                if self.evidence_stage is None
                else self.evidence_stage.to_storage()
            ),
            "portrait_withdrawals": list(self.portrait_withdrawals),
            "evidence_applicability_changes": [
                change.to_storage()
                for change in self.evidence_applicability_changes
            ]}
        if self.model_answer_resolution is not None:
            stored["model_answer_resolution"] = (
                self.model_answer_resolution.to_storage()
            )
        return stored

    @classmethod
    def from_storage(cls, value: object) -> "DailyTurnDraft":
        legacy_fields = frozenset({"source_causal_id", "source_digest", "base_state_digest",
            "purpose", "created_at", "steward_plan", "responsibility_results",
            "reply_atoms", "steward_resolution", "evidence_cards", "portrait_topics",
            "evidence_relations", "evidence_compactions", "skill_proofs",
            "skill_disclosures", "owner_reply", "turn_kind", "evidence_stage",
            "portrait_withdrawals", "evidence_applicability_changes"})
        if type(value) is not dict or frozenset(value) not in (
            legacy_fields,
            legacy_fields | {"model_answer_resolution"},
        ):
            raise AuthorityValidationError("invalid daily turn draft")
        f = value
        for key in ("responsibility_results", "reply_atoms", "evidence_cards",
                    "portrait_topics", "evidence_relations", "evidence_compactions",
                    "skill_proofs",
                    "skill_disclosures", "evidence_applicability_changes"):
            if type(f[key]) is not list: raise AuthorityValidationError(f"invalid {key}")
        raw_stage = f["evidence_stage"]
        if raw_stage is not None and type(raw_stage) is not dict:
            raise AuthorityValidationError("invalid embedded evidence stage")
        raw_resolution = f["steward_resolution"]
        if raw_resolution is not None and type(raw_resolution) is not dict:
            raise AuthorityValidationError("invalid steward resolution")
        try:
            model_resolution = (
                None
                if "model_answer_resolution" not in f
                else ModelAnswerResolution.from_storage(
                    f["model_answer_resolution"]
                )
            )
        except ValueError as exc:
            raise AuthorityValidationError(
                "invalid model answer resolution"
            ) from exc
        return cls(f["source_causal_id"], f["source_digest"], f["base_state_digest"], f["purpose"],
            f["created_at"], StewardPlan.from_storage(f["steward_plan"]),
            tuple(ResponsibilityResult.from_storage(x) for x in f["responsibility_results"]),
            tuple(OwnerReplyAtom.from_storage(x) for x in f["reply_atoms"]),
            None if raw_resolution is None else StewardResolution.from_storage(raw_resolution),
            tuple(EvidenceCard.from_storage(x) for x in f["evidence_cards"]),
            tuple(PortraitTopic.from_storage(x) for x in f["portrait_topics"]),
            tuple(EvidenceRelation.from_storage(x) for x in f["evidence_relations"]),
            tuple(EvidenceCompaction.from_storage(x) for x in f["evidence_compactions"]),
            tuple(DailySkillUseProof.from_storage(x) for x in f["skill_proofs"]),
            tuple(DailySkillDisclosure.from_storage(x) for x in f["skill_disclosures"]),
            f["owner_reply"], f["turn_kind"],
            None if raw_stage is None else DailyTurnDraft.from_storage(raw_stage),
            _stored_texts(
                f["portrait_withdrawals"],
                "portrait withdrawal topics",
                empty=True,
            ),
            tuple(
                EvidenceApplicabilityChange.from_storage(item)
                for item in f["evidence_applicability_changes"]
            ),
            model_resolution,
        )  # type: ignore[arg-type]

    def verify(
        self,
        source: SourceEnvelope,
        state: "DailyHealthState",
        bundle: DailySkillBundle,
        verifier: DailySkillAttestor,
        *,
        committed_evidence_stage: "DailyTurnDraft | None" = None,
    ) -> bool:
        if (
            type(source) is not SourceEnvelope
            or type(state) is not DailyHealthState
            or self.source_causal_id != source.causal_id
            or self.source_digest != stable_digest(source.to_storage())
            or self.base_state_digest != state.digest
        ):
            return False
        names = tuple(
            proof.skill_use.canonical_name for proof in self.skill_proofs
        )
        actions = tuple(proof.skill_use.action for proof in self.skill_proofs)
        used_names = tuple(dict.fromkeys(names))
        if (
            tuple(item.canonical_name for item in self.skill_disclosures)
            != used_names
            or any(
                not disclosure.matches(bundle.asset(disclosure.canonical_name))
                for disclosure in self.skill_disclosures
            )
        ):
            return False
        parent: str | None = None
        for index, proof in enumerate(self.skill_proofs):
            fact = proof.skill_use
            if (
                fact.source_causal_id != source.causal_id
                or fact.purpose != self.purpose
                or fact.sequence_index != index
                or fact.parent_proof_digest != parent
                or not verifier.verify(proof, bundle.asset(fact.canonical_name))
            ):
                return False
            parent = proof.digest

        expected_actions = {
            "health-evidence": "evaluate-evidence",
            "health-portrait": "maintain-portrait",
            "health-settings": "form-settings-candidate",
            "health-owner-inquiry": "form-owner-question",
            "health-literature": "find-literature",
        }

        if self.turn_kind == "evidence-stage":
            if (
                not names
                or names[0] != "health-steward"
                or actions[0] != "plan"
                or any(name != "health-evidence" for name in names[1:])
                or any(action != "evaluate-evidence" for action in actions[1:])
                or len(self.skill_proofs) - 1 != len(self.responsibility_results)
            ):
                return False
            navigation = DailyHealthNavigation.from_projection(state.projection)
            initial_context = StewardContext(
                source.causal_id,
                source.requested_capability,
                source.body,
                navigation,
            )
            first_fact = self.skill_proofs[0].skill_use
            if (
                first_fact.input_digest
                != stable_digest(
                    {
                        "source": source.to_storage(),
                        "context": initial_context.to_storage(),
                    }
                )
                or first_fact.result_digest
                != stable_digest(self.steward_plan.to_storage())
            ):
                return False
            evidence_proofs = self.skill_proofs[1:]
            planned_operations = (
                tuple(
                    (claim, None)
                    for claim in self.steward_plan.atomic_claims
                )
                + tuple(
                    (request.replacement_claim, request)
                    for request in self.steward_plan.evidence_maintenance_requests
                )
                if "health-evidence" in self.steward_plan.selected_skills
                else ()
            )
            expected_claim_count = (
                len(planned_operations)
                if "health-evidence" in self.steward_plan.selected_skills
                else 0
            )
            if len(evidence_proofs) != expected_claim_count:
                return False
            expected_cards: list[EvidenceCard] = []
            expected_topic_relations: list[EvidenceRelation] = []
            expected_maintenance_relations: list[EvidenceRelation] = []
            expected_compactions: list[EvidenceCompaction] = []
            expected_changes: list[EvidenceApplicabilityChange] = []
            for (claim, request), proof, result in zip(
                planned_operations,
                evidence_proofs,
                self.responsibility_results,
            ):
                fact = proof.skill_use
                if (
                    result.canonical_name != "health-evidence"
                    or result.input_digest != fact.input_digest
                    or result.result_digest != fact.result_digest
                    or type(result.decision) is not EvidenceDecision
                ):
                    return False
                try:
                    expected_context = (
                        _evidence_context_for(
                            source,
                            self.steward_plan,
                            state,
                            claim,
                        )
                        if request is None and claim is not None
                        else _evidence_maintenance_context_for(
                            source,
                            self.steward_plan,
                            state,
                            request,
                        )
                    )
                except AuthorityValidationError:
                    return False
                if fact.input_digest != stable_digest(
                    {
                        "source": source.to_storage(),
                        "context": expected_context.to_storage(),
                    }
                ):
                    return False
                decision = result.decision
                if request is None:
                    if decision.status in {
                        "correct",
                        "withdraw",
                        "invalidate",
                    }:
                        return False
                elif (
                    decision.status != request.action
                    or decision.target_evidence_ids
                    != request.target_evidence_ids
                    or decision.reason != request.reason
                    or decision.atomic_claim != request.replacement_claim
                ):
                    return False
                try:
                    (
                        expected_card,
                        expected_compaction,
                        decision_relations,
                        decision_changes,
                    ) = _evidence_decision_artifacts(
                        source_causal_id=source.causal_id,
                        claim=claim,
                        decision=decision,
                        decision_digest=result.result_digest,
                        recorded_at=self.created_at,
                    )
                except AuthorityValidationError:
                    return False
                expected_candidate_refs = (
                    ()
                    if expected_card is None
                    else (expected_card.evidence_id,)
                )
                if (
                    result.candidate_refs != expected_candidate_refs
                    or result.candidate_change_ids
                    != tuple(change.change_id for change in decision_changes)
                ):
                    return False
                if expected_card is not None:
                    expected_cards.append(expected_card)
                    expected_topic_relations.extend(
                        EvidenceRelation(
                            expected_card.evidence_id,
                            "topic",
                            "relevant",
                            "portrait-topic",
                            topic_ref,
                        )
                        for topic_ref in expected_card.topic_refs
                    )
                if expected_compaction is not None:
                    expected_compactions.append(expected_compaction)
                expected_maintenance_relations.extend(decision_relations)
                expected_changes.extend(decision_changes)
                if (
                    decision.status == "correct"
                    and expected_card is not None
                    and any(
                        not _is_relevant_correction(expected_card, card)
                        for card in expected_context.related_existing_cards
                    )
                ):
                    return False
            if (
                tuple(expected_cards) != self.evidence_cards
                or tuple(dict.fromkeys((
                    *expected_topic_relations,
                    *expected_maintenance_relations,
                )))
                != self.evidence_relations
                or tuple(expected_compactions) != self.evidence_compactions
                or tuple(expected_changes)
                != self.evidence_applicability_changes
            ):
                return False
            try:
                state.apply_evidence_stage(self)
            except AuthorityValidationError:
                return False
            return all(
                card.source_causal_id == source.causal_id
                for card in self.evidence_cards
            )

        stage = self.evidence_stage
        if (
            type(stage) is not DailyTurnDraft
            or type(committed_evidence_stage) is not DailyTurnDraft
            or committed_evidence_stage.turn_kind != "evidence-stage"
            or stage.digest != committed_evidence_stage.digest
            or stage.source_causal_id != self.source_causal_id
            or stage.source_digest != self.source_digest
            or stage.steward_plan != self.steward_plan
            or self.skill_proofs[: len(stage.skill_proofs)] != stage.skill_proofs
            or self.responsibility_results[: len(stage.responsibility_results)]
            != stage.responsibility_results
        ):
            return False
        state_cards = {card.evidence_id: card for card in state.evidence_cards}
        if (
            any(state_cards.get(card.evidence_id) != card for card in stage.evidence_cards)
            or not set(stage.evidence_relations) <= set(state.evidence_relations)
            or not set(stage.evidence_applicability_changes)
            <= set(state.evidence_applicability_changes)
        ):
            return False
        continuation_proofs = self.skill_proofs[len(stage.skill_proofs):]
        continuation_results = self.responsibility_results[
            len(stage.responsibility_results):
        ]
        if (
            not continuation_proofs
            or continuation_proofs[-1].skill_use.canonical_name != "health-steward"
            or continuation_proofs[-1].skill_use.action != "resolve"
            or "health-steward" in tuple(
                proof.skill_use.canonical_name for proof in continuation_proofs[:-1]
            )
            or len(continuation_proofs) - 1 != len(continuation_results)
        ):
            return False
        for proof, result in zip(continuation_proofs[:-1], continuation_results):
            fact = proof.skill_use
            if (
                fact.canonical_name == "health-evidence"
                or result.canonical_name != fact.canonical_name
                or result.input_digest != fact.input_digest
                or result.result_digest != fact.result_digest
                or expected_actions.get(fact.canonical_name) != fact.action
            ):
                return False
        expected_execution_names = tuple(dict.fromkeys((
            *(result.canonical_name for result in stage.responsibility_results),
            *(
                skill_name
                for skill_name in self.steward_plan.selected_skills
                if skill_name != "health-evidence"
            ),
        )))
        actual_execution_names = tuple(dict.fromkeys(
            result.canonical_name for result in self.responsibility_results
        ))
        if actual_execution_names != expected_execution_names:
            return False
        portrait_results = tuple(
            result
            for result in continuation_results
            if result.canonical_name == "health-portrait"
        )
        portrait_proofs = tuple(
            proof
            for proof in continuation_proofs[:-1]
            if proof.skill_use.canonical_name == "health-portrait"
        )
        portrait_scope = (
            _portrait_scope_for(self.steward_plan, stage)
            if "health-portrait" in self.steward_plan.selected_skills
            else ()
        )
        if (
            len(portrait_results) != len(portrait_proofs)
            or len(portrait_results) != len(portrait_scope)
        ):
            return False
        expected_portrait_topics: list[PortraitTopic] = []
        expected_withdrawal_refs: list[str] = []
        current_topic_refs = {
            topic.topic_ref for topic in state.portrait_topics
        }
        for topic_ref, proof, result in zip(
            portrait_scope,
            portrait_proofs,
            portrait_results,
        ):
            context = _portrait_context_for(
                source,
                self.steward_plan,
                state,
                topic_ref,
            )
            decision = result.decision
            if (
                type(decision) is not PortraitDecision
                or context.in_turn_evidence_candidates
                or (
                    decision.status in {"update", "degrade", "maintain"}
                    and _portrait_context_is_truncated(context)
                )
                or proof.skill_use.input_digest
                != stable_digest(
                    {
                        "source": source.to_storage(),
                        "context": context.to_storage(),
                    }
                )
            ):
                return False
            try:
                _validate_portrait_decision_applicable_periods(
                    decision,
                    {
                        card.evidence_id: card
                        for card in context.committed_related_cards
                    },
                )
            except AuthorityValidationError:
                return False
            if decision.status in {"update", "degrade"}:
                if (
                    decision.topic_ref != topic_ref
                    or not {
                        link.evidence_id for link in decision.proof_links
                    }.issubset(context.evidence_ids)
                ):
                    return False
                expected_portrait_topics.append(
                    PortraitTopic.from_decision(decision)
                )
            elif decision.status == "maintain":
                if (
                    decision.topic_ref != topic_ref
                    or topic_ref not in current_topic_refs
                ):
                    return False
            elif decision.status == "withdraw":
                if (
                    decision.topic_ref != topic_ref
                    or topic_ref not in current_topic_refs
                ):
                    return False
                expected_withdrawal_refs.append(topic_ref)
            elif decision.status != "gap":
                return False
        candidate_evidence_ids = tuple(
            card.evidence_id for card in stage.evidence_cards
        )
        candidate_evidence_change_ids = tuple(
            change.change_id
            for change in stage.evidence_applicability_changes
        )
        candidate_portrait_topics = tuple(
            candidate_ref
            for result in self.responsibility_results
            if result.canonical_name == "health-portrait"
            for candidate_ref in result.candidate_refs
        )
        expected_portrait_relations = tuple(dict.fromkeys(
            relation
            for topic in expected_portrait_topics
            for relation in topic.evidence_relations
        ))
        resolution_context = StewardResolutionContext(
            self.source_causal_id,
            self.purpose,
            self.responsibility_results,
            candidate_evidence_ids,
            candidate_portrait_topics,
            self.reply_atoms,
            candidate_evidence_change_ids,
        )
        resolution = self.steward_resolution
        final_fact = continuation_proofs[-1].skill_use
        if (
            type(resolution) is not StewardResolution
            or final_fact.input_digest
            != stable_digest(
                {
                    "source": source.to_storage(),
                    "context": resolution_context.to_storage(),
                }
            )
            or final_fact.result_digest != stable_digest(resolution.to_storage())
            or resolution.commit_evidence_ids != candidate_evidence_ids
            or resolution.commit_portrait_topic_refs != candidate_portrait_topics
            or resolution.commit_evidence_change_ids
            != candidate_evidence_change_ids
            or self.portrait_topics != tuple(expected_portrait_topics)
            or self.portrait_withdrawals != tuple(expected_withdrawal_refs)
            or self.evidence_relations != expected_portrait_relations
        ):
            return False
        try:
            selected_atoms = _validated_selected_reply_atoms(
                resolution_context,
                resolution,
            )
        except AuthorityValidationError:
            return False
        if (
            (
                "".join(atom.text for atom in selected_atoms)
                + _render_daily_skill_disclosure(self.skill_disclosures)
            )
            != self.owner_reply
        ):
            return False
        try:
            _validate_evidence_relation_ledger(state_cards, self.evidence_relations)
            state.apply(self)
        except AuthorityValidationError:
            return False
        return (
            all(
                set(topic.evidence_ids) <= set(state_cards)
                for topic in self.portrait_topics
            )
            and all(
                set(topic.evidence_relations) <= set(self.evidence_relations)
                for topic in self.portrait_topics
            )
        )


@dataclass(frozen=True)
class DailyHealthState:
    evidence_cards: tuple[EvidenceCard, ...]
    portrait_topics: tuple[PortraitTopic, ...]
    evidence_relations: tuple[EvidenceRelation, ...]
    processed_source_causal_ids: tuple[str, ...]
    evidence_applicability_changes: tuple[EvidenceApplicabilityChange, ...] = ()
    portrait_schema_version: str = PORTRAIT_SCHEMA_VERSION
    portrait_schema_digest: str = FIRST_RELEASE_PORTRAIT_SCHEMA.digest
    portrait_revisions: tuple[PortraitRevision, ...] = ()

    def __post_init__(self) -> None:
        if self.portrait_schema_version != PORTRAIT_SCHEMA_VERSION:
            raise AuthorityValidationError("unknown portrait schema version")
        if self.portrait_schema_digest != FIRST_RELEASE_PORTRAIT_SCHEMA.digest:
            raise AuthorityValidationError("portrait schema digest mismatch")
        if type(self.evidence_cards) is not tuple or any(type(x) is not EvidenceCard for x in self.evidence_cards):
            raise AuthorityValidationError("invalid evidence cards")
        if type(self.portrait_topics) is not tuple or any(type(x) is not PortraitTopic for x in self.portrait_topics):
            raise AuthorityValidationError("invalid portrait topics")
        if type(self.evidence_relations) is not tuple or any(
            type(x) is not EvidenceRelation for x in self.evidence_relations
        ):
            raise AuthorityValidationError("invalid evidence relations")
        if type(self.evidence_applicability_changes) is not tuple or any(
            type(change) is not EvidenceApplicabilityChange
            for change in self.evidence_applicability_changes
        ):
            raise AuthorityValidationError("invalid evidence applicability ledger")
        if type(self.portrait_revisions) is not tuple or any(
            type(revision) is not PortraitRevision
            for revision in self.portrait_revisions
        ):
            raise AuthorityValidationError("invalid portrait revision ledger")
        _texts(self.processed_source_causal_ids, "processed sources", empty=True)
        ids = {c.evidence_id for c in self.evidence_cards}
        topic_refs = tuple(topic.topic_ref for topic in self.portrait_topics)
        if len(set(topic_refs)) != len(topic_refs):
            raise AuthorityValidationError("duplicate portrait topic")
        if len(ids) != len(self.evidence_cards) or any(not set(t.evidence_ids) <= ids for t in self.portrait_topics):
            raise AuthorityValidationError("portrait references uncommitted evidence")
        _validate_evidence_relation_ledger(
            {card.evidence_id: card for card in self.evidence_cards},
            self.evidence_relations,
        )
        if any(
            not set(topic.evidence_relations) <= set(self.evidence_relations)
            for topic in self.portrait_topics
        ):
            raise AuthorityValidationError("portrait relation missing from evidence ledger")
        cards = {card.evidence_id: card for card in self.evidence_cards}
        for topic in self.portrait_topics:
            _validate_portrait_topic_applicable_periods(topic, cards)
        changes_by_target = {
            change.target_evidence_id: change
            for change in self.evidence_applicability_changes
        }
        if len(changes_by_target) != len(self.evidence_applicability_changes):
            raise AuthorityValidationError("evidence applicability changed twice")
        relations = set(self.evidence_relations)
        for change in self.evidence_applicability_changes:
            target = cards.get(change.target_evidence_id)
            successor = (
                None
                if change.successor_evidence_id is None
                else cards.get(change.successor_evidence_id)
            )
            if target is None or (
                change.successor_evidence_id is not None and successor is None
            ):
                raise AuthorityValidationError(
                    "evidence applicability references a missing card"
                )
            if change.applicability == "corrected":
                if (
                    successor is None
                    or not _is_relevant_correction(successor, target)
                    or EvidenceRelation(
                        successor.evidence_id,
                        "history",
                        "corrects",
                        "evidence-card",
                        target.evidence_id,
                    )
                    not in relations
                ):
                    raise AuthorityValidationError(
                        "evidence correction history mismatch"
                    )
            elif EvidenceRelation(
                target.evidence_id,
                "history",
                "withdraws",
                "evidence-card",
                target.evidence_id,
            ) not in relations:
                raise AuthorityValidationError(
                    "evidence withdrawal history mismatch"
                )

        for start in changes_by_target:
            visited: set[str] = set()
            cursor = start
            while cursor in changes_by_target:
                if cursor in visited:
                    raise AuthorityValidationError(
                        "cyclic evidence applicability history"
                    )
                visited.add(cursor)
                successor_id = changes_by_target[cursor].successor_evidence_id
                if successor_id is None:
                    break
                cursor = successor_id

        current_topics = {
            topic.topic_ref: topic for topic in self.portrait_topics
        }
        latest_revision_by_topic: dict[str, PortraitRevision] = {}
        for revision in self.portrait_revisions:
            previous_revision = latest_revision_by_topic.get(revision.topic_ref)
            if (
                previous_revision is not None
                and revision.previous_topic != previous_revision.next_topic
            ):
                raise AuthorityValidationError(
                    "portrait revision history is discontinuous"
                )
            latest_revision_by_topic[revision.topic_ref] = revision
        if any(
            current_topics.get(topic_ref) != revision.next_topic
            for topic_ref, revision in latest_revision_by_topic.items()
        ):
            raise AuthorityValidationError(
                "portrait revision ledger disagrees with current projection"
            )

    @classmethod
    def empty(cls) -> "DailyHealthState": return cls((), (), (), (), ())
    def to_storage(self) -> dict[str, object]:
        return {"evidence_cards": [c.to_storage() for c in self.evidence_cards],
            "portrait_topics": [t.to_storage() for t in self.portrait_topics],
            "evidence_relations": [r.to_storage() for r in self.evidence_relations],
            "processed_source_causal_ids": list(self.processed_source_causal_ids),
            "portrait_schema_version": self.portrait_schema_version,
            "portrait_schema_digest": self.portrait_schema_digest,
            "portrait_revisions": [
                revision.to_storage() for revision in self.portrait_revisions
            ],
            "evidence_applicability_changes": [
                change.to_storage()
                for change in self.evidence_applicability_changes
            ]}
    @classmethod
    def from_storage(cls, value: object) -> "DailyHealthState":
        f = _mapping(value, frozenset({"evidence_cards", "portrait_topics",
            "evidence_relations", "processed_source_causal_ids",
            "evidence_applicability_changes", "portrait_schema_version",
            "portrait_schema_digest", "portrait_revisions"}),
            "daily health state")
        if (type(f["evidence_cards"]) is not list
                or type(f["portrait_topics"]) is not list
                or type(f["evidence_relations"]) is not list
                or type(f["evidence_applicability_changes"]) is not list
                or type(f["portrait_revisions"]) is not list):
            raise AuthorityValidationError("invalid daily health state")
        return cls(tuple(EvidenceCard.from_storage(x) for x in f["evidence_cards"]),
            tuple(PortraitTopic.from_storage(x) for x in f["portrait_topics"]),
            tuple(EvidenceRelation.from_storage(x) for x in f["evidence_relations"]),
            _stored_texts(f["processed_source_causal_ids"], "processed sources", empty=True),
            tuple(
                EvidenceApplicabilityChange.from_storage(item)
                for item in f["evidence_applicability_changes"]
            ),
            f["portrait_schema_version"],
            f["portrait_schema_digest"],
            tuple(
                PortraitRevision.from_storage(item)
                for item in f["portrait_revisions"]
            ),
        )  # type: ignore[arg-type]
    @property
    def digest(self) -> str: return stable_digest(self.to_storage())

    @property
    def current_evidence_ids(self) -> tuple[str, ...]:
        inactive = {
            change.target_evidence_id
            for change in self.evidence_applicability_changes
        }
        return tuple(
            card.evidence_id
            for card in self.evidence_cards
            if card.evidence_id not in inactive
        )

    @property
    def current_evidence_cards(self) -> tuple[EvidenceCard, ...]:
        current_ids = set(self.current_evidence_ids)
        return tuple(
            card for card in self.evidence_cards
            if card.evidence_id in current_ids
        )

    def is_evidence_current(self, evidence_id: str) -> bool:
        validate_opaque_text(evidence_id, "evidence identifier")
        return evidence_id in set(self.current_evidence_ids)

    def _protected_evidence_ids(self) -> set[str]:
        protected = {
            card.evidence_id
            for card in self.evidence_cards
            if card.time_certainty == "uncertain"
            or (
                type(card.specific_fields) is PersonalHealthFields
                and card.specific_fields.observation_kind
                == "reported-clinician-conclusion"
            )
        }
        current_use_prefixes = (
            "active-task:",
            "diagnosis-current:",
            "safety-current:",
            "conflict-open:",
            "external-unknown:",
        )
        for relation in self.evidence_relations:
            if relation.relation_class == "proof":
                protected.add(relation.evidence_id)
            elif relation.relation_class == "use" and relation.target_ref.startswith(
                current_use_prefixes
            ):
                protected.add(relation.evidence_id)
            elif relation.relation_class == "history" and relation.relation_kind in {
                "corrects",
                "replaces",
                "withdraws",
            }:
                protected.add(relation.evidence_id)
                if relation.target_kind == "evidence-card":
                    protected.add(relation.target_ref)
        for change in self.evidence_applicability_changes:
            protected.add(change.target_evidence_id)
            if change.successor_evidence_id is not None:
                protected.add(change.successor_evidence_id)
        return protected

    def _series_windows(self) -> tuple[EvidenceSeriesWindow, ...]:
        protected_ids = self._protected_evidence_ids()
        grouped: dict[EvidenceSeriesKey, list[EvidenceCard]] = {}
        for card in self.evidence_cards:
            grouped.setdefault(card.series_key, []).append(card)

        windows: list[EvidenceSeriesWindow] = []
        for series_key in sorted(
            grouped,
            key=lambda key: stable_digest(key.to_storage()),
        ):
            series_cards = grouped[series_key]
            details = [card for card in series_cards if card.card_form == "detail"]
            summaries = [card for card in series_cards if card.card_form == "summary"]

            def ordered(cards: list[EvidenceCard]) -> tuple[EvidenceCard, ...]:
                return tuple(
                    sorted(
                        cards,
                        key=lambda card: (
                            _occurrence_time(card.occurred_at, card.time_certainty)
                            or datetime.min.replace(tzinfo=timezone.utc),
                            card.evidence_id,
                        ),
                        reverse=True,
                    )
                )

            protected = ordered(
                [card for card in details if card.evidence_id in protected_ids]
            )
            unorderable = tuple(
                card.evidence_id
                for card in protected
                if card.time_certainty == "uncertain"
            )
            regular = ordered(
                [
                    card
                    for card in details
                    if card.evidence_id not in protected_ids
                    and card.time_certainty == "known"
                ]
            )
            recent = regular[:5]
            outside = regular[5:]
            summary_ids = tuple(card.evidence_id for card in ordered(summaries))
            outside_ids = tuple(card.evidence_id for card in outside)
            windows.append(
                EvidenceSeriesWindow(
                    series_key,
                    tuple(card.evidence_id for card in recent),
                    tuple(card.evidence_id for card in protected),
                    unorderable,
                    outside_ids,
                    summary_ids,
                    outside_ids if len(outside_ids) >= 3 else (),
                )
            )
        return tuple(windows)

    def _topic_projections(
        self,
        windows: tuple[EvidenceSeriesWindow, ...],
    ) -> tuple[PortraitTopicProjection, ...]:
        topics = {topic.topic_ref: topic for topic in self.portrait_topics}
        ordered_ids: list[str] = []
        for window in windows:
            ordered_ids.extend(window.protected_detail_ids)
            ordered_ids.extend(window.recent_detail_ids)
            ordered_ids.extend(window.summary_ids)
            ordered_ids.extend(window.window_outside_detail_ids)
        rank = {evidence_id: index for index, evidence_id in enumerate(ordered_ids)}

        projections: list[PortraitTopicProjection] = []
        for topic_ref in PORTRAIT_TOPIC_REFS:
            topic = topics.get(topic_ref)
            evidence_previews: list[EvidenceTypePreview] = []
            for evidence_type in EVIDENCE_TYPE_ORDER:
                ids = tuple(
                    card.evidence_id
                    for card in sorted(
                        (
                            card
                            for card in self.current_evidence_cards
                            if card.evidence_type == evidence_type
                            and topic_ref in card.topic_refs
                        ),
                        key=lambda card: rank.get(card.evidence_id, len(rank)),
                    )
                )
                evidence_previews.append(
                    EvidenceTypePreview(
                        evidence_type,
                        ids[:3],
                        max(0, len(ids) - 3),
                    )
                )
            related_tasks = () if topic is None else topic.related_task_ids
            projections.append(
                PortraitTopicProjection(
                    topic_ref,
                    "unknown" if topic is None else "known",
                    () if topic is None else topic.current_understandings,
                    (
                        ()
                        if topic is None
                        else topic.current_understanding_applicable_periods
                    ),
                    () if topic is None else topic.open_judgments,
                    () if topic is None else topic.key_unknowns,
                    None if topic is None else topic.trend,
                    None if topic is None else topic.trend_period,
                    related_tasks[:3],
                    max(0, len(related_tasks) - 3),
                    tuple(evidence_previews),
                )
            )
        return tuple(projections)

    @property
    def projection(self) -> DailyHealthProjection:
        known = {t.topic_ref.split("/", 1)[0] for t in self.portrait_topics}
        windows = self._series_windows()
        topic_views = self._topic_projections(windows)
        return DailyHealthProjection(
            self.digest,
            len(self.evidence_cards),
            tuple(view.topic_ref for view in topic_views),
            tuple(d for d in PORTRAIT_DOMAIN_REFS if d not in known),
            topic_views,
            windows,
        )

    @property
    def navigation(self) -> DailyHealthNavigation:
        return DailyHealthNavigation.from_projection(self.projection)

    def apply_evidence_stage(self, draft: DailyTurnDraft) -> "DailyHealthState":
        if (
            type(draft) is not DailyTurnDraft
            or draft.turn_kind != "evidence-stage"
            or draft.base_state_digest != self.digest
            or draft.source_causal_id in self.processed_source_causal_ids
        ):
            raise AuthorityValidationError("invalid evidence-stage revision")
        _validate_portrait_rejudgment_scope(draft.steward_plan, self)
        (
            expected_cards,
            expected_compactions,
            expected_relations,
            expected_changes,
        ) = _expected_stage_evidence_artifacts(draft)
        if (
            draft.evidence_cards != expected_cards
            or draft.evidence_compactions != expected_compactions
            or draft.evidence_relations != expected_relations
            or draft.evidence_applicability_changes != expected_changes
        ):
            raise AuthorityValidationError(
                "evidence stage artifacts changed their typed decisions"
            )
        current_ids = set(self.current_evidence_ids)
        if any(
            change.target_evidence_id not in current_ids
            for change in draft.evidence_applicability_changes
        ):
            raise AuthorityValidationError(
                "evidence applicability target is not current"
            )
        cards = {card.evidence_id: card for card in self.evidence_cards}
        for card in draft.evidence_cards:
            if card.evidence_id in cards:
                raise AuthorityValidationError("duplicate evidence card")
            cards[card.evidence_id] = card
        relations = list(self.evidence_relations)
        retired_ids: set[str] = set()
        protected_ids = self._protected_evidence_ids()
        protected_ids.update(
            change.target_evidence_id
            for change in draft.evidence_applicability_changes
        )
        windows = {
            window.series_key: window for window in self._series_windows()
        }
        draft_cards = {
            card.evidence_id: card for card in draft.evidence_cards
        }
        for compaction in draft.evidence_compactions:
            summary = draft_cards.get(compaction.summary_evidence_id)
            if (
                summary is None
                or summary.card_form != "summary"
                or summary.summary_fields is None
                or set(compaction.retire_evidence_ids) & retired_ids
            ):
                raise AuthorityValidationError("invalid historical summary card")
            predecessors = tuple(
                next(
                    (
                        card
                        for card in self.evidence_cards
                        if card.evidence_id == evidence_id
                    ),
                    None,
                )
                for evidence_id in compaction.retire_evidence_ids
            )
            if any(card is None for card in predecessors):
                raise AuthorityValidationError("evidence compaction predecessor missing")
            typed_predecessors = tuple(
                card for card in predecessors if card is not None
            )
            if any(
                card.evidence_type != summary.evidence_type
                or card.series_key != summary.series_key
                for card in typed_predecessors
            ):
                raise AuthorityValidationError(
                    "evidence compaction crossed a comparable series"
                )
            if set(compaction.retire_evidence_ids) & protected_ids:
                raise AuthorityValidationError(
                    "protected evidence cannot be compressed"
                )
            details = tuple(
                card for card in typed_predecessors if card.card_form == "detail"
            )
            summaries = tuple(
                card for card in typed_predecessors if card.card_form == "summary"
            )
            window = windows.get(summary.series_key)
            if window is None:
                raise AuthorityValidationError("evidence series window missing")
            if not summaries:
                if (
                    len(details) < 3
                    or not set(compaction.retire_evidence_ids)
                    <= set(window.summary_threshold_detail_ids)
                ):
                    raise AuthorityValidationError(
                        "first historical summary requires three qualified old details"
                    )
            elif not (
                (summaries and details) or len(summaries) >= 2
            ):
                raise AuthorityValidationError("invalid rolling evidence summary")
            if details and not {card.evidence_id for card in details} <= set(
                window.window_outside_detail_ids
            ):
                raise AuthorityValidationError("recent evidence cannot be compressed")
            fields = summary.summary_fields
            predecessor_summary_ids = tuple(
                card.evidence_id for card in summaries
            )
            expected_predecessor_digest = (
                None
                if not predecessor_summary_ids
                else EvidenceCompaction.predecessor_digest(
                    predecessor_summary_ids
                )
            )
            coverage_starts = tuple(
                card.summary_fields.coverage_start
                if card.summary_fields is not None
                else card.occurred_at
                for card in typed_predecessors
            )
            coverage_ends = tuple(
                card.summary_fields.coverage_end
                if card.summary_fields is not None
                else card.occurred_at
                for card in typed_predecessors
            )
            if (
                fields.absorbed_records_digest
                != compaction.retire_records_digest
                or fields.absorbed_record_count != len(typed_predecessors)
                or fields.total_original_detail_count
                != len(details)
                + sum(
                    card.summary_fields.total_original_detail_count
                    for card in summaries
                    if card.summary_fields is not None
                )
                or fields.predecessor_batch_digest
                != expected_predecessor_digest
                or fields.generation
                != 1
                + max(
                    (
                        card.summary_fields.generation
                        for card in summaries
                        if card.summary_fields is not None
                    ),
                    default=0,
                )
                or fields.coverage_start
                != min(
                    coverage_starts,
                    key=lambda value: _occurrence_time(value, "known"),
                )
                or fields.coverage_end
                != max(
                    coverage_ends,
                    key=lambda value: _occurrence_time(value, "known"),
                )
            ):
                raise AuthorityValidationError("historical summary lineage mismatch")
            retired_ids.update(compaction.retire_evidence_ids)
        for evidence_id in retired_ids:
            cards.pop(evidence_id)
        if retired_ids:
            relations = [
                relation
                for relation in relations
                if relation.evidence_id not in retired_ids
                and not (
                    relation.target_kind == "evidence-card"
                    and relation.target_ref in retired_ids
                )
            ]
        relations.extend(draft.evidence_relations)
        return DailyHealthState(
            tuple(cards.values()),
            self.portrait_topics,
            tuple(dict.fromkeys(relations)),
            self.processed_source_causal_ids,
            (
                *self.evidence_applicability_changes,
                *draft.evidence_applicability_changes,
            ),
            self.portrait_schema_version,
            self.portrait_schema_digest,
            self.portrait_revisions,
        )

    def apply(self, draft: DailyTurnDraft) -> tuple["DailyHealthState", DailyTurnResult]:
        if (
            type(draft) is not DailyTurnDraft
            or draft.turn_kind != "complete-turn"
            or draft.base_state_digest != self.digest
        ):
            raise AuthorityValidationError("daily state revision changed")
        if draft.source_causal_id in self.processed_source_causal_ids:
            raise AuthorityValidationError("daily source already committed")
        cards = {c.evidence_id: c for c in self.evidence_cards}
        for card in draft.evidence_cards:
            if card.evidence_id in cards: raise AuthorityValidationError("duplicate evidence card")
            cards[card.evidence_id] = card
        topics = {t.topic_ref: t for t in self.portrait_topics}
        previous_topics = dict(topics)
        relations = list(self.evidence_relations)
        retired_ids: set[str] = set()
        protected_ids = self._protected_evidence_ids()
        windows = {window.series_key: window for window in self._series_windows()}
        draft_cards = {card.evidence_id: card for card in draft.evidence_cards}
        for compaction in draft.evidence_compactions:
            summary = draft_cards.get(compaction.summary_evidence_id)
            if (
                summary is None
                or summary.card_form != "summary"
                or summary.summary_fields is None
            ):
                raise AuthorityValidationError("historical summary card missing")
            if set(compaction.retire_evidence_ids) & retired_ids:
                raise AuthorityValidationError("evidence predecessor retired twice")
            predecessors: list[EvidenceCard] = []
            for evidence_id in compaction.retire_evidence_ids:
                predecessor = next(
                    (
                        card
                        for card in self.evidence_cards
                        if card.evidence_id == evidence_id
                    ),
                    None,
                )
                if predecessor is None:
                    raise AuthorityValidationError("evidence compaction predecessor missing")
                predecessors.append(predecessor)
            if any(
                card.evidence_type != summary.evidence_type
                or card.series_key != summary.series_key
                for card in predecessors
            ):
                raise AuthorityValidationError("evidence compaction crossed a comparable series")
            if set(compaction.retire_evidence_ids) & protected_ids:
                raise AuthorityValidationError("protected evidence cannot be compressed")
            detail_predecessors = [
                card for card in predecessors if card.card_form == "detail"
            ]
            summary_predecessors = [
                card for card in predecessors if card.card_form == "summary"
            ]
            window = windows.get(summary.series_key)
            if window is None:
                raise AuthorityValidationError("evidence series window missing")
            if not summary_predecessors:
                if (
                    len(detail_predecessors) < 3
                    or not set(compaction.retire_evidence_ids)
                    <= set(window.summary_threshold_detail_ids)
                ):
                    raise AuthorityValidationError(
                        "first historical summary requires three qualified old details"
                    )
            elif not (
                (len(summary_predecessors) >= 1 and len(detail_predecessors) >= 1)
                or len(summary_predecessors) >= 2
            ):
                raise AuthorityValidationError("invalid rolling evidence summary")
            if detail_predecessors and not {
                card.evidence_id for card in detail_predecessors
            } <= set(window.window_outside_detail_ids):
                raise AuthorityValidationError("recent evidence cannot be compressed")
            fields = summary.summary_fields
            expected_original_count = len(detail_predecessors) + sum(
                card.summary_fields.total_original_detail_count
                for card in summary_predecessors
                if card.summary_fields is not None
            )
            predecessor_summary_ids = tuple(
                card.evidence_id for card in summary_predecessors
            )
            expected_predecessor_digest = (
                None
                if not predecessor_summary_ids
                else EvidenceCompaction.predecessor_digest(predecessor_summary_ids)
            )
            coverage_starts = tuple(
                card.summary_fields.coverage_start
                if card.summary_fields is not None
                else card.occurred_at
                for card in predecessors
            )
            coverage_ends = tuple(
                card.summary_fields.coverage_end
                if card.summary_fields is not None
                else card.occurred_at
                for card in predecessors
            )
            expected_generation = (
                1
                + max(
                    (
                        card.summary_fields.generation
                        for card in summary_predecessors
                        if card.summary_fields is not None
                    ),
                    default=0,
                )
            )
            if (
                fields.absorbed_records_digest != compaction.retire_records_digest
                or fields.absorbed_record_count != len(predecessors)
                or fields.total_original_detail_count != expected_original_count
                or fields.predecessor_batch_digest != expected_predecessor_digest
                or fields.generation != expected_generation
                or fields.coverage_start
                != min(
                    coverage_starts,
                    key=lambda value: _occurrence_time(value, "known"),
                )
                or fields.coverage_end
                != max(
                    coverage_ends,
                    key=lambda value: _occurrence_time(value, "known"),
                )
            ):
                raise AuthorityValidationError("historical summary lineage mismatch")
            retired_ids.update(compaction.retire_evidence_ids)
        for evidence_id in retired_ids:
            cards.pop(evidence_id)
        if retired_ids:
            relations = [
                relation
                for relation in relations
                if relation.evidence_id not in retired_ids
                and not (
                    relation.target_kind == "evidence-card"
                    and relation.target_ref in retired_ids
                )
            ]
        for topic_ref in draft.portrait_withdrawals:
            previous = topics.pop(topic_ref, None)
            if previous is None:
                raise AuthorityValidationError(
                    "portrait withdrawal target missing"
                )
            old_proof_relations = {
                relation
                for relation in previous.evidence_relations
                if relation.relation_class == "proof"
            }
            relations = [
                relation
                for relation in relations
                if relation not in old_proof_relations
            ]
        for topic in draft.portrait_topics:
            if not set(topic.evidence_ids) <= set(cards):
                raise AuthorityValidationError("portrait references uncommitted evidence")
            previous = topics.get(topic.topic_ref)
            if previous is not None:
                previous_relations = set(previous.evidence_relations)
                relations = [
                    relation
                    for relation in relations
                    if relation not in previous_relations
                ]
            topics[topic.topic_ref] = topic
        relations.extend(draft.evidence_relations)
        inactive_ids = {
            change.target_evidence_id
            for change in self.evidence_applicability_changes
        }
        current_ids = set(cards) - inactive_ids
        if any(
            not set(topic.evidence_ids) <= current_ids
            for topic in topics.values()
        ):
            raise AuthorityValidationError(
                "portrait must be rejudged after evidence applicability changed"
            )
        draft_topics = {topic.topic_ref: topic for topic in draft.portrait_topics}
        new_revisions: list[PortraitRevision] = []
        revised_topic_refs: set[str] = set()
        portrait_proofs = tuple(
            proof
            for proof in draft.skill_proofs
            if proof.skill_use.canonical_name == "health-portrait"
        )
        for result in draft.responsibility_results:
            if result.canonical_name != "health-portrait":
                continue
            decision = result.decision
            if type(decision) is not PortraitDecision or decision.status not in {
                "update",
                "degrade",
                "withdraw",
            }:
                continue
            topic_ref = decision.topic_ref
            if topic_ref is None or topic_ref in revised_topic_refs:
                raise AuthorityValidationError(
                    "portrait topic revised more than once in one turn"
                )
            revised_topic_refs.add(topic_ref)
            if decision.status in {"update", "degrade"}:
                expected_next = PortraitTopic.from_decision(decision)
                if (
                    draft_topics.get(topic_ref) != expected_next
                    or topics.get(topic_ref) != expected_next
                ):
                    raise AuthorityValidationError(
                        "portrait revision next snapshot changed its decision"
                    )
                next_topic: PortraitTopic | None = expected_next
            else:
                if (
                    topic_ref not in draft.portrait_withdrawals
                    or topic_ref not in previous_topics
                    or topic_ref in topics
                ):
                    raise AuthorityValidationError(
                        "portrait withdrawal revision changed its target"
                    )
                next_topic = None
            matching_proofs = tuple(
                proof
                for proof in portrait_proofs
                if proof.skill_use.input_digest == result.input_digest
                and proof.skill_use.result_digest == result.result_digest
            )
            if len(matching_proofs) != 1:
                raise AuthorityValidationError(
                    "portrait revision Skill proof is ambiguous"
                )
            new_revisions.append(
                PortraitRevision(
                    topic_ref,
                    decision.status,
                    previous_topics.get(topic_ref),
                    next_topic,
                    decision.reason or draft.purpose,
                    result.result_digest,
                    matching_proofs[0].skill_use.used_at,
                )
            )
        state = DailyHealthState(tuple(cards.values()), tuple(topics.values()),
            tuple(dict.fromkeys(relations)),
            (*self.processed_source_causal_ids, draft.source_causal_id),
            self.evidence_applicability_changes,
            self.portrait_schema_version,
            self.portrait_schema_digest,
            (*self.portrait_revisions, *new_revisions))
        stage = draft.evidence_stage
        if type(stage) is not DailyTurnDraft:
            raise AuthorityValidationError("complete turn evidence stage missing")
        resolution = draft.steward_resolution
        if type(resolution) is not StewardResolution:
            raise AuthorityValidationError("complete turn resolution missing")
        if (
            resolution.commit_evidence_ids
            != tuple(card.evidence_id for card in stage.evidence_cards)
            or resolution.commit_evidence_change_ids
            != tuple(
                change.change_id
                for change in stage.evidence_applicability_changes
            )
        ):
            raise AuthorityValidationError(
                "complete turn lost an evidence stage commitment"
            )
        result = DailyTurnResult(draft.source_causal_id, draft.record_id, draft.transition_id,
            tuple(c.evidence_id for c in stage.evidence_cards), resolution.commit_portrait_topic_refs,
            draft.skill_disclosures, draft.owner_reply,
            resolution.commit_evidence_change_ids,
            (
                None
                if draft.model_answer_resolution is None
                else draft.model_answer_resolution.status
            ),
            (
                None
                if draft.model_answer_resolution is None
                else draft.model_answer_resolution.digest
            ))
        return state, result


def _evidence_context_for(
    source: SourceEnvelope,
    plan: StewardPlan,
    state: DailyHealthState,
    claim: AtomicEvidenceClaim,
) -> EvidenceContext:
    projection = state.projection
    is_compression_candidate = claim.summary_fields is not None
    current_ids = set(state.current_evidence_ids)
    related_existing_cards = tuple(
        card
        for card in state.evidence_cards
        if card.series_key == claim.series_key
        and (
            is_compression_candidate
            or card.evidence_id in current_ids
        )
    )
    related_ids = {card.evidence_id for card in related_existing_cards}
    related_relations = tuple(
        relation
        for relation in state.evidence_relations
        if relation.evidence_id in related_ids
    )
    related_applicability_changes = tuple(
        change
        for change in state.evidence_applicability_changes
        if is_compression_candidate
        and change.target_evidence_id in related_ids
    )
    series_window = (
        next(
            (
                window
                for window in projection.series_windows
                if window.series_key == claim.series_key
            ),
            None,
        )
        if is_compression_candidate
        else None
    )
    return EvidenceContext(
        source.causal_id,
        plan.purpose,
        claim,
        None,
        state.digest,
        related_existing_cards,
        related_relations,
        tuple(
            card.evidence_id
            for card in related_existing_cards
            if card.evidence_id in current_ids
        ),
        related_applicability_changes,
        series_window,
    )


def _evidence_maintenance_context_for(
    source: SourceEnvelope,
    plan: StewardPlan,
    state: DailyHealthState,
    request: EvidenceMaintenanceRequest,
) -> EvidenceContext:
    cards = {card.evidence_id: card for card in state.evidence_cards}
    current_ids = set(state.current_evidence_ids)
    try:
        target_cards = tuple(
            cards[evidence_id] for evidence_id in request.target_evidence_ids
        )
    except KeyError as exc:
        raise AuthorityValidationError(
            "evidence maintenance target missing"
        ) from exc
    if not set(request.target_evidence_ids) <= current_ids:
        raise AuthorityValidationError(
            "evidence maintenance target is not current"
        )
    target_ids = set(request.target_evidence_ids)
    related_relations = tuple(
        relation
        for relation in state.evidence_relations
        if relation.evidence_id in target_ids
    )
    related_changes = tuple(
        change
        for change in state.evidence_applicability_changes
        if change.target_evidence_id in target_ids
    )
    return EvidenceContext(
        source.causal_id,
        plan.purpose,
        request.replacement_claim,
        request,
        state.digest,
        target_cards,
        related_relations,
        request.target_evidence_ids,
        related_changes,
        None,
    )


def _portrait_scope_for(
    plan: StewardPlan,
    stage: DailyTurnDraft,
) -> tuple[str, ...]:
    return tuple(dict.fromkeys((
        *plan.portrait_topic_refs,
        *(
            topic_ref
            for claim in plan.atomic_claims
            for topic_ref in claim.topic_refs
        ),
        *(
            topic_ref
            for request in plan.evidence_maintenance_requests
            if request.replacement_claim is not None
            for topic_ref in request.replacement_claim.topic_refs
        ),
        *(topic_ref for card in stage.evidence_cards for topic_ref in card.topic_refs),
    )))


def _validate_portrait_rejudgment_scope(
    plan: StewardPlan,
    state: DailyHealthState,
) -> None:
    target_ids = {
        evidence_id
        for request in plan.evidence_maintenance_requests
        for evidence_id in request.target_evidence_ids
    }
    if not target_ids:
        return
    affected_topics = {
        topic.topic_ref
        for topic in state.portrait_topics
        if set(topic.evidence_ids).intersection(target_ids)
    }
    if not affected_topics:
        return
    covered_topics = set(plan.portrait_topic_refs)
    covered_topics.update(
        topic_ref
        for request in plan.evidence_maintenance_requests
        if request.replacement_claim is not None
        for topic_ref in request.replacement_claim.topic_refs
    )
    if (
        "health-portrait" not in plan.selected_skills
        or not affected_topics <= covered_topics
    ):
        raise AuthorityValidationError(
            "portrait rejudgment required before evidence applicability changes"
        )


def _portrait_context_for(
    source: SourceEnvelope,
    plan: StewardPlan,
    state: DailyHealthState,
    topic_ref: str,
) -> PortraitContext:
    projection = state.projection
    current_view = next(
        (
            item
            for item in projection.topic_views
            if item.topic_ref == topic_ref
        ),
        PortraitTopicProjection(
            topic_ref,
            "unknown",
            (),
            (),
            (),
            (),
            None,
            None,
            (),
            0,
            tuple(
                EvidenceTypePreview(evidence_type, (), 0)
                for evidence_type in EVIDENCE_TYPE_ORDER
            ),
        ),
    )
    current_topic = next(
        (
            topic
            for topic in state.portrait_topics
            if topic.topic_ref == topic_ref
        ),
        None,
    )
    committed_related_cards = tuple(
        card
        for card in state.current_evidence_cards
        if topic_ref in card.topic_refs
        and card.evidence_id in {
            *(
                evidence_id
                for preview in current_view.evidence_previews
                for evidence_id in preview.preview_ids
            ),
            *(() if current_topic is None else current_topic.evidence_ids),
            *(
                card.evidence_id
                for card in state.current_evidence_cards
                if card.source_causal_id == source.causal_id
                and topic_ref in card.topic_refs
            ),
        }
    )
    committed_ids = {
        card.evidence_id for card in committed_related_cards
    }
    related_task_refs = current_view.related_task_preview_ids
    current_proof_relations = (
        set()
        if current_topic is None
        else set(current_topic.evidence_relations)
    )
    committed_relations = tuple(
        relation
        for relation in state.evidence_relations
        if relation.evidence_id in committed_ids
        and (
            (
                relation.relation_class == "topic"
                and relation.relation_kind == "relevant"
                and relation.target_kind == "portrait-topic"
                and relation.target_ref == topic_ref
            )
            or (
                relation.relation_class == "proof"
                and relation in current_proof_relations
            )
            or (
                relation.relation_class == "use"
                and relation.target_ref in related_task_refs
            )
        )
    )
    return PortraitContext(
        source.causal_id,
        plan.purpose,
        state.digest,
        (topic_ref,),
        (current_view,),
        committed_related_cards,
        committed_relations,
        (),
        related_task_refs,
    )


def _portrait_context_is_truncated(context: PortraitContext) -> bool:
    return any(
        view.additional_task_count
        or any(preview.additional_count for preview in view.evidence_previews)
        for view in context.current_topic_views
    )


class DailySkillRuntime:
    """Form a typed daily-turn draft without writing state or sending."""

    def __init__(self, bundle: DailySkillBundle, attestor: DailySkillAttestor, *,
                 executor: Callable[[str, object], object],
                 clock: Callable[[], datetime] | None = None) -> None:
        if type(bundle) is not DailySkillBundle or type(attestor) is not DailySkillAttestor:
            raise AuthorityValidationError("invalid daily Skill runtime")
        if not callable(executor) or (clock is not None and not callable(clock)):
            raise AuthorityValidationError("invalid daily Skill runtime callback")
        self._bundle = bundle
        self._attestor = attestor
        self._executor = executor
        self._clock = clock or (lambda: datetime.now().astimezone())

    def _used_at(self) -> str:
        value = self._clock()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise AuthorityValidationError("daily Skill clock must be timezone-aware")
        return value.isoformat()

    def _proof(self, asset: DailySkillAsset, *, source: SourceEnvelope,
               purpose: str, context: object, result: object, used_at: str,
               action: str,
               sequence_index: int,
               parent: DailySkillUseProof | None) -> DailySkillUseProof:
        context_storage = getattr(context, "to_storage", None)
        result_storage = getattr(result, "to_storage", None)
        if not callable(context_storage) or not callable(result_storage):
            raise AuthorityValidationError("daily Skill returned an untyped value")
        # input_digest binds the complete admitted source plus the purpose-
        # limited context; the fact separately carries the causal identifier.
        input_digest = stable_digest({
            "source": source.to_storage(), "context": context_storage(),
        })
        fact = DailySkillUseFact(
            asset.canonical_name, asset.friendly_name, asset.role, asset.version,
            asset.asset_digest, asset.disclosure_version, used_at,
            source.causal_id, input_digest, stable_digest(result_storage()),
            purpose, action, sequence_index,
            None if parent is None else parent.digest,
        )
        return self._attestor.attest(fact)

    def execute(
        self,
        source: SourceEnvelope,
        current_state: DailyHealthState,
    ) -> DailyTurnDraft:
        """Alias for the first, evidence-only phase of a daily turn."""

        return self.execute_evidence_stage(source, current_state)

    def execute_evidence_stage(
        self,
        source: SourceEnvelope,
        current_state: DailyHealthState,
    ) -> DailyTurnDraft:
        if (
            type(source) is not SourceEnvelope
            or source.body is None
            or type(current_state) is not DailyHealthState
        ):
            raise AuthorityValidationError(
                "evidence stage requires admitted source and exact state"
            )
        navigation = current_state.navigation
        steward_context = StewardContext(
            source.causal_id,
            source.requested_capability,
            source.body,
            navigation,
        )
        plan = self._executor("health-steward", steward_context)
        if type(plan) is not StewardPlan:
            raise AuthorityValidationError(
                "health-steward returned an untyped plan"
            )
        _validate_portrait_rejudgment_scope(plan, current_state)
        used_at = self._used_at()
        proofs: list[DailySkillUseProof] = [
            self._proof(
                self._bundle.asset("health-steward"),
                source=source,
                purpose=plan.purpose,
                context=steward_context,
                result=plan,
                used_at=used_at,
                action="plan",
                sequence_index=0,
                parent=None,
            )
        ]
        results: list[ResponsibilityResult] = []
        cards: list[EvidenceCard] = []
        compactions: list[EvidenceCompaction] = []
        maintenance_relations: list[EvidenceRelation] = []
        applicability_changes: list[EvidenceApplicabilityChange] = []

        if "health-evidence" in plan.selected_skills:
            if not plan.atomic_claims and not plan.evidence_maintenance_requests:
                raise AuthorityValidationError(
                    "health-evidence requires a claim or maintenance request"
                )

            def execute_evidence(
                context: EvidenceContext,
                claim: AtomicEvidenceClaim | None,
                request: EvidenceMaintenanceRequest | None,
            ) -> None:
                decision = self._executor("health-evidence", context)
                if type(decision) is not EvidenceDecision:
                    raise AuthorityValidationError(
                        "health-evidence returned an untyped candidate"
                    )
                if request is None:
                    if decision.status in {"correct", "withdraw", "invalidate"}:
                        raise AuthorityValidationError(
                            "evidence lifecycle decision lacks plan authority"
                        )
                elif (
                    decision.status != request.action
                    or decision.target_evidence_ids
                    != request.target_evidence_ids
                    or decision.reason != request.reason
                    or decision.atomic_claim != request.replacement_claim
                ):
                    raise AuthorityValidationError(
                        "evidence maintenance decision changed its request"
                    )
                proof = self._proof(
                    self._bundle.asset("health-evidence"),
                    source=source,
                    purpose=plan.purpose,
                    context=context,
                    result=decision,
                    used_at=used_at,
                    action="evaluate-evidence",
                    sequence_index=len(proofs),
                    parent=proofs[-1],
                )
                proofs.append(proof)
                (
                    candidate_card,
                    compaction,
                    decision_relations,
                    decision_changes,
                ) = _evidence_decision_artifacts(
                    source_causal_id=source.causal_id,
                    claim=claim,
                    decision=decision,
                    decision_digest=proof.skill_use.result_digest,
                    recorded_at=used_at,
                )
                if candidate_card is not None and decision.status == "correct":
                    targets = {
                        card.evidence_id: card
                        for card in context.related_existing_cards
                    }
                    if any(
                        not _is_relevant_correction(
                            candidate_card,
                            targets[target_id],
                        )
                        for target_id in decision.target_evidence_ids
                    ):
                        raise AuthorityValidationError(
                            "evidence correction crossed an atomic dimension"
                        )
                candidate_refs = (
                    ()
                    if candidate_card is None
                    else (candidate_card.evidence_id,)
                )
                candidate_change_ids = tuple(
                    change.change_id for change in decision_changes
                )
                results.append(
                    ResponsibilityResult(
                        "health-evidence",
                        decision.status,
                        proof.skill_use.input_digest,
                        proof.skill_use.result_digest,
                        decision,
                        candidate_refs,
                        candidate_change_ids,
                    )
                )
                if candidate_card is not None:
                    cards.append(candidate_card)
                if compaction is not None:
                    compactions.append(compaction)
                maintenance_relations.extend(decision_relations)
                applicability_changes.extend(decision_changes)

            for claim in plan.atomic_claims:
                execute_evidence(
                    _evidence_context_for(
                        source,
                        plan,
                        current_state,
                        claim,
                    ),
                    claim,
                    None,
                )
            for request in plan.evidence_maintenance_requests:
                execute_evidence(
                    _evidence_maintenance_context_for(
                        source,
                        plan,
                        current_state,
                        request,
                    ),
                    request.replacement_claim,
                    request,
                )

        if len({
            change.target_evidence_id for change in applicability_changes
        }) != len(applicability_changes):
            raise AuthorityValidationError(
                "evidence applicability target changed twice in one stage"
            )
        evidence_relations = tuple(dict.fromkeys((
            *(
                EvidenceRelation(
                    card.evidence_id,
                    "topic",
                    "relevant",
                    "portrait-topic",
                    topic_ref,
                )
                for card in cards
                for topic_ref in card.topic_refs
            ),
            *maintenance_relations,
        )))
        used_names = tuple(dict.fromkeys(
            proof.skill_use.canonical_name for proof in proofs
        ))
        disclosures = tuple(
            DailySkillDisclosure.from_asset(self._bundle.asset(name))
            for name in used_names
        )
        return DailyTurnDraft(
            source.causal_id,
            stable_digest(source.to_storage()),
            current_state.digest,
            plan.purpose,
            used_at,
            plan,
            tuple(results),
            (),
            None,
            tuple(cards),
            (),
            evidence_relations,
            tuple(compactions),
            tuple(proofs),
            disclosures,
            "",
            "evidence-stage",
            None,
            (),
            tuple(applicability_changes),
        )

    def complete(
        self,
        source: SourceEnvelope,
        post_stage_state: DailyHealthState,
        evidence_stage: DailyTurnDraft,
        *,
        model_answer_resolution: ModelAnswerResolution | None = None,
        model_reply_atoms: tuple[OwnerReplyAtom, ...] = (),
    ) -> DailyTurnDraft:
        if (
            type(source) is not SourceEnvelope
            or source.body is None
            or type(post_stage_state) is not DailyHealthState
            or type(evidence_stage) is not DailyTurnDraft
            or evidence_stage.turn_kind != "evidence-stage"
            or evidence_stage.source_causal_id != source.causal_id
            or evidence_stage.source_digest != stable_digest(source.to_storage())
        ):
            raise AuthorityValidationError("invalid evidence stage continuation")
        if model_answer_resolution is not None and type(
            model_answer_resolution
        ) is not ModelAnswerResolution:
            raise AuthorityValidationError("invalid model answer resolution")
        if type(model_reply_atoms) is not tuple or any(
            type(atom) is not OwnerReplyAtom for atom in model_reply_atoms
        ):
            raise AuthorityValidationError("invalid model reply atoms")
        if model_answer_resolution is None:
            if model_reply_atoms:
                raise AuthorityValidationError(
                    "model reply atoms require an answer resolution"
                )
        elif model_answer_resolution.status == "failed-closed":
            if model_reply_atoms:
                raise AuthorityValidationError(
                    "failed-closed resolution cannot carry model reply atoms"
                )
        elif not model_reply_atoms:
            raise AuthorityValidationError(
                "rendered resolution requires deterministic reply atoms"
            )
        elif any(
            atom.source_result_digest
            != model_answer_resolution.candidate_digest
            for atom in model_reply_atoms
        ):
            raise AuthorityValidationError(
                "model reply atoms do not bind the validated candidate"
            )
        if any(
            atom.source_skill != "health-steward"
            or atom.required_evidence_ids
            or atom.required_portrait_topic_refs
            or atom.required_evidence_change_ids
            for atom in model_reply_atoms
        ):
            raise AuthorityValidationError(
                "model reply atoms exceeded the steward answer boundary"
            )
        state_cards = {
            card.evidence_id: card for card in post_stage_state.evidence_cards
        }
        if (
            any(
                state_cards.get(card.evidence_id) != card
                for card in evidence_stage.evidence_cards
            )
            or not set(evidence_stage.evidence_relations)
            <= set(post_stage_state.evidence_relations)
            or not set(evidence_stage.evidence_applicability_changes)
            <= set(post_stage_state.evidence_applicability_changes)
        ):
            raise AuthorityValidationError(
                "evidence stage is not committed in current state"
            )
        plan = evidence_stage.steward_plan
        used_at = self._used_at()
        proofs = list(evidence_stage.skill_proofs)
        results = list(evidence_stage.responsibility_results)
        reply_atoms: list[OwnerReplyAtom] = []
        portrait_topics: list[PortraitTopic] = []
        portrait_withdrawals: list[str] = []

        stage_cards = {
            card.evidence_id: card for card in evidence_stage.evidence_cards
        }
        stage_changes = {
            change.change_id: change
            for change in evidence_stage.evidence_applicability_changes
        }
        for result in evidence_stage.responsibility_results:
            if result.canonical_name != "health-evidence":
                raise AuthorityValidationError(
                    "evidence stage contains a non-evidence result"
                )
            if not set(result.candidate_change_ids) <= set(stage_changes):
                raise AuthorityValidationError(
                    "evidence result lost its applicability change"
                )
            if result.candidate_refs:
                for evidence_id in result.candidate_refs:
                    card = stage_cards.get(evidence_id)
                    if card is None:
                        raise AuthorityValidationError(
                            "evidence result lost its committed card"
                        )
                    reply_atoms.append(
                        OwnerReplyAtom.form(
                            kind="record-result",
                            text=f"已记录：{card.content}。",
                            source_skill="health-evidence",
                            source_result_digest=result.result_digest,
                            required_evidence_ids=(evidence_id,),
                            required_evidence_change_ids=(
                                result.candidate_change_ids
                            ),
                        )
                    )
                    reply_atoms.append(
                        OwnerReplyAtom.form(
                            kind="limitation",
                            text=(
                                "未形成"
                                + "、".join(card.does_not_prove)
                                + "或健康任务。"
                            ),
                            source_skill="health-evidence",
                            source_result_digest=result.result_digest,
                            required_evidence_ids=(evidence_id,),
                        )
                    )
            else:
                text = (
                    "已撤回指定证据的当前适用性；原记录与历史保留。"
                    if result.status == "withdraw"
                    else "指定证据已失效并退出当前适用；原记录与历史保留。"
                    if result.status == "invalidate"
                    else "候选证据仍需澄清，本轮未写入权威证据或画像。"
                    if result.status == "clarify"
                    else "候选证据未获准，本轮未写入权威证据或画像。"
                )
                reply_atoms.append(
                    OwnerReplyAtom.form(
                        kind="record-result",
                        text=text,
                        source_skill="health-evidence",
                        source_result_digest=result.result_digest,
                        required_evidence_change_ids=(
                            result.candidate_change_ids
                        ),
                    )
                )

        def record_responsibility(
            skill_name: str,
            context: object,
            result: object,
            *,
            action: str,
            status: str,
            candidate_refs: tuple[str, ...] = (),
            candidate_change_ids: tuple[str, ...] = (),
        ) -> DailySkillUseProof:
            proof = self._proof(
                self._bundle.asset(skill_name),
                source=source,
                purpose=plan.purpose,
                context=context,
                result=result,
                used_at=used_at,
                action=action,
                sequence_index=len(proofs),
                parent=proofs[-1],
            )
            proofs.append(proof)
            results.append(
                ResponsibilityResult(
                    skill_name,
                    status,
                    proof.skill_use.input_digest,
                    proof.skill_use.result_digest,
                    result,
                    candidate_refs,
                    candidate_change_ids,
                )
            )
            return proof

        for skill_name in plan.selected_skills:
            if skill_name == "health-evidence":
                continue
            if skill_name == "health-portrait":
                for topic_ref in _portrait_scope_for(plan, evidence_stage):
                    context = _portrait_context_for(
                        source,
                        plan,
                        post_stage_state,
                        topic_ref,
                    )
                    if context.in_turn_evidence_candidates:
                        raise AuthorityValidationError(
                            "portrait context contains uncommitted evidence"
                        )
                    decision = self._executor(skill_name, context)
                    if type(decision) is not PortraitDecision:
                        raise AuthorityValidationError(
                            "health-portrait returned an untyped candidate"
                        )
                    if (
                        decision.status in {"update", "degrade", "maintain"}
                        and _portrait_context_is_truncated(context)
                    ):
                        raise AuthorityValidationError(
                            "portrait preview is incomplete; typed gap required"
                        )
                    _validate_portrait_decision_applicable_periods(
                        decision,
                        {
                            card.evidence_id: card
                            for card in context.committed_related_cards
                        },
                    )
                    candidate_refs = (
                        (topic_ref,)
                        if decision.status in {
                            "update",
                            "maintain",
                            "degrade",
                            "withdraw",
                        }
                        else ()
                    )
                    proof = record_responsibility(
                        skill_name,
                        context,
                        decision,
                        action="maintain-portrait",
                        status=decision.status,
                        candidate_refs=candidate_refs,
                    )
                    if decision.status in {"update", "degrade"}:
                        if (
                            decision.topic_ref != topic_ref
                            or not {
                                link.evidence_id for link in decision.proof_links
                            }.issubset(context.evidence_ids)
                        ):
                            raise AuthorityValidationError(
                                "portrait candidate exceeded its context"
                            )
                        portrait_topics.append(
                            PortraitTopic.from_decision(decision)
                        )
                        reply_atoms.append(
                            OwnerReplyAtom.form(
                                kind="record-result",
                                text=(
                                    f"已降级画像主题：{topic_ref}。"
                                    if decision.status == "degrade"
                                    else f"已更新画像主题：{topic_ref}。"
                                ),
                                source_skill=skill_name,
                                source_result_digest=proof.skill_use.result_digest,
                                required_portrait_topic_refs=(topic_ref,),
                            )
                        )
                    elif decision.status == "maintain":
                        if decision.topic_ref != topic_ref:
                            raise AuthorityValidationError(
                                "portrait maintenance exceeded its context"
                            )
                        reply_atoms.append(
                            OwnerReplyAtom.form(
                                kind="record-result",
                                text=f"已维持画像主题：{topic_ref}。",
                                source_skill=skill_name,
                                source_result_digest=proof.skill_use.result_digest,
                                required_portrait_topic_refs=(topic_ref,),
                            )
                        )
                    elif decision.status == "withdraw":
                        if decision.topic_ref != topic_ref:
                            raise AuthorityValidationError(
                                "portrait withdrawal exceeded its context"
                            )
                        portrait_withdrawals.append(topic_ref)
                        reply_atoms.append(
                            OwnerReplyAtom.form(
                                kind="record-result",
                                text=f"已撤回画像主题：{topic_ref}。",
                                source_skill=skill_name,
                                source_result_digest=proof.skill_use.result_digest,
                                required_portrait_topic_refs=(topic_ref,),
                            )
                        )
                    elif decision.status == "gap":
                        reply_atoms.append(
                            OwnerReplyAtom.form(
                                kind="record-result",
                                text="画像处理所需资料不足，本轮未更新画像。",
                                source_skill=skill_name,
                                source_result_digest=proof.skill_use.result_digest,
                            )
                        )
                    else:
                        raise AuthorityValidationError(
                            "unsupported portrait result status"
                        )
            elif skill_name == "health-settings":
                if plan.settings_intent is None:
                    raise AuthorityValidationError("settings intent required")
                context = SettingsContext(
                    source.causal_id,
                    plan.purpose,
                    plan.settings_intent,
                    current_settings_available=False,
                )
                decision = self._executor(skill_name, context)
                if type(decision) is not SettingsDecision:
                    raise AuthorityValidationError(
                        "health-settings returned an untyped candidate"
                    )
                if not context.current_settings_available and decision.status != "gap":
                    raise AuthorityValidationError(
                        "health-settings must return a gap without current settings"
                    )
                proof = record_responsibility(
                    skill_name,
                    context,
                    decision,
                    action="form-settings-candidate",
                    status=decision.status,
                )
                reply_atoms.append(
                    OwnerReplyAtom.form(
                        kind="record-result",
                        text=(
                            "设置处理所需资料不足，未修改设置。"
                            if decision.status == "gap"
                            else "当前设置无需形成修改候选。"
                        ),
                        source_skill=skill_name,
                        source_result_digest=proof.skill_use.result_digest,
                    )
                )
            elif skill_name == "health-owner-inquiry":
                if plan.inquiry_gap is None:
                    raise AuthorityValidationError("inquiry gap required")
                topic_refs = tuple(dict.fromkeys(
                    topic_ref
                    for claim in plan.atomic_claims
                    for topic_ref in claim.topic_refs
                ))
                missing = [
                    "task-acceptance-unavailable",
                    "current-control-state-unavailable",
                    "same-gap-state-unavailable",
                ]
                if not topic_refs:
                    missing.insert(0, "topic-scope-unavailable")
                context = OwnerInquiryContext(
                    source.causal_id,
                    plan.purpose,
                    plan.inquiry_gap,
                    topic_refs,
                    (),
                    (),
                    (),
                    False,
                    False,
                    None,
                    tuple(missing),
                )
                decision = self._executor(skill_name, context)
                if (
                    type(decision) is not OwnerInquiryDecision
                    or decision.status != "gap"
                ):
                    raise AuthorityValidationError(
                        "health-owner-inquiry must return a typed context gap"
                    )
                proof = record_responsibility(
                    skill_name,
                    context,
                    decision,
                    action="form-owner-question",
                    status=decision.status,
                )
                reply_atoms.append(
                    OwnerReplyAtom.form(
                        kind="next-step",
                        text="补问所需上下文不足，本轮没有猜测提问。",
                        source_skill=skill_name,
                        source_result_digest=proof.skill_use.result_digest,
                    )
                )
            elif skill_name == "health-literature":
                if plan.knowledge_gap is None:
                    raise AuthorityValidationError("knowledge gap required")
                context = LiteratureContext(
                    source.causal_id,
                    plan.purpose,
                    plan.knowledge_gap,
                    plan.knowledge_topic_refs,
                    plan.allowed_knowledge_sources,
                    plan.recipient_boundary,
                    tuple(
                        card
                        for card in post_stage_state.current_evidence_cards
                        if card.evidence_type == "authoritative-knowledge"
                        and set(card.topic_refs).intersection(
                            plan.knowledge_topic_refs
                        )
                        and type(card.specific_fields)
                        is AuthoritativeKnowledgeFields
                        and card.specific_fields.publisher
                        in plan.allowed_knowledge_sources
                    ),
                )
                decision = self._executor(skill_name, context)
                if type(decision) is not LiteratureDecision:
                    raise AuthorityValidationError(
                        "health-literature returned an untyped candidate"
                    )
                if decision.status == "candidate":
                    claim = decision.candidate_claim
                    if (
                        type(claim) is not AtomicEvidenceClaim
                        or claim.purpose != plan.purpose
                        or not set(claim.topic_refs) <= set(context.topic_refs)
                        or type(claim.specific_fields)
                        is not AuthoritativeKnowledgeFields
                        or claim.specific_fields.publisher
                        not in context.allowed_sources
                    ):
                        raise AuthorityValidationError(
                            "literature candidate exceeded its source boundary"
                        )
                proof = record_responsibility(
                    skill_name,
                    context,
                    decision,
                    action="find-literature",
                    status=decision.status,
                    candidate_refs=(
                        ()
                        if decision.candidate_ref is None
                        else (decision.candidate_ref,)
                    ),
                )
                reply_atoms.append(
                    OwnerReplyAtom.form(
                        kind="direct-result",
                        text=(
                            "找到一条合格资料候选，尚未写入权威证据。"
                            if decision.status == "candidate"
                            else
                            "当前来源与接收方边界内没有合格资料。"
                            if decision.status == "no-qualified-material"
                            else "资料查找所需边界不足，本轮没有扩大读取或外发。"
                        ),
                        source_skill=skill_name,
                        source_result_digest=proof.skill_use.result_digest,
                    )
                )
            else:
                raise AuthorityValidationError(
                    f"unsupported daily Skill candidate: {skill_name}"
                )

        if model_answer_resolution is not None:
            if model_answer_resolution.status == "failed-closed":
                reply_atoms.append(
                    OwnerReplyAtom.form(
                        kind="limitation",
                        text=render_failed_closed(model_answer_resolution),
                        source_skill="health-steward",
                        source_result_digest=model_answer_resolution.digest,
                    )
                )
            else:
                reply_atoms.extend(model_reply_atoms)
        if not reply_atoms:
            reply_atoms.append(
                OwnerReplyAtom.form(
                    kind="direct-result",
                    text="本轮未形成新的健康证据、画像或健康任务。",
                    source_skill="health-steward",
                    source_result_digest=proofs[0].skill_use.result_digest,
                )
            )
        reply_atoms.sort(key=lambda atom: REPLY_ATOM_KINDS.index(atom.kind))
        stage_evidence_ids = tuple(
            card.evidence_id for card in evidence_stage.evidence_cards
        )
        stage_evidence_change_ids = tuple(
            change.change_id
            for change in evidence_stage.evidence_applicability_changes
        )
        resolution_context = StewardResolutionContext(
            source.causal_id,
            plan.purpose,
            tuple(results),
            stage_evidence_ids,
            tuple(
                candidate_ref
                for result in results
                if result.canonical_name == "health-portrait"
                for candidate_ref in result.candidate_refs
            ),
            tuple(reply_atoms),
            stage_evidence_change_ids,
        )
        resolution = self._executor("health-steward", resolution_context)
        if type(resolution) is not StewardResolution:
            raise AuthorityValidationError(
                "health-steward returned an untyped resolution"
            )
        candidate_topics = {
            topic.topic_ref: topic for topic in portrait_topics
        }
        affected_portrait_refs = (
            resolution_context.candidate_portrait_topic_refs
        )
        if (
            resolution.commit_evidence_ids != stage_evidence_ids
            or resolution.commit_portrait_topic_refs != affected_portrait_refs
            or resolution.commit_evidence_change_ids
            != stage_evidence_change_ids
        ):
            raise AuthorityValidationError(
                "steward resolution did not preserve committed evidence"
            )
        committed_topics = tuple(
            candidate_topics[topic_ref]
            for topic_ref in resolution.commit_portrait_topic_refs
            if topic_ref in candidate_topics
        )
        selected_atoms = _validated_selected_reply_atoms(
            resolution_context,
            resolution,
        )
        proofs.append(
            self._proof(
                self._bundle.asset("health-steward"),
                source=source,
                purpose=plan.purpose,
                context=resolution_context,
                result=resolution,
                used_at=used_at,
                action="resolve",
                sequence_index=len(proofs),
                parent=proofs[-1],
            )
        )
        used_names = tuple(dict.fromkeys(
            proof.skill_use.canonical_name for proof in proofs
        ))
        disclosures = tuple(
            DailySkillDisclosure.from_asset(self._bundle.asset(name))
            for name in used_names
        )
        portrait_relations = tuple(dict.fromkeys(
            relation
            for topic in committed_topics
            for relation in topic.evidence_relations
        ))
        return DailyTurnDraft(
            source.causal_id,
            stable_digest(source.to_storage()),
            post_stage_state.digest,
            plan.purpose,
            used_at,
            plan,
            tuple(results),
            tuple(reply_atoms),
            resolution,
            (),
            committed_topics,
            portrait_relations,
            (),
            tuple(proofs),
            disclosures,
            (
                "".join(atom.text for atom in selected_atoms)
                + _render_daily_skill_disclosure(disclosures)
            ),
            "complete-turn",
            evidence_stage,
            tuple(portrait_withdrawals),
            model_answer_resolution=model_answer_resolution,
        )

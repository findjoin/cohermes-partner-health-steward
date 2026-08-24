"""Strict value contracts for owner-managed reads, corrections, and exports.

The values in this module are deliberately passive.  They describe managed
objects and finite snapshots, but do not expose an import, write, or storage
operation that could turn an export into a second authority.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Mapping

from .coordination import (
    AtomicEvidenceClaim,
    DailyHealthState,
    EvidenceCard,
    EvidenceMaintenanceRequest,
    OwnerCorrectionRevision,
)


MANAGED_EXPORT_SCHEMA_VERSION = "managed-export-v1"


class RightsContractViolation(ValueError):
    """A value cannot cross the managed data-rights contract."""


_MANAGED_OBJECT_FIELDS = frozenset(
    {
        "object_ref",
        "object_kind",
        "owner_id",
        "installation_id",
        "version",
        "current",
        "source_refs",
        "evidence_refs",
        "value",
    }
)
_MANAGED_OBJECT_REFERENCE_FIELDS = frozenset(
    {"object_ref", "installation_id", "version"}
)
_CORRECTION_REVISION_FIELDS = frozenset(
    {
        "correction_id",
        "object_ref",
        "previous_version",
        "revision_version",
        "reason",
        "corrected_at_utc",
        "source_refs",
        "evidence_refs",
        "affected_object_refs",
        "disposition_requests",
    }
)
_EXPORT_SNAPSHOT_FIELDS = frozenset(
    {
        "snapshot_id",
        "owner_id",
        "installation_id",
        "source_state_digest",
        "schema_version",
        "created_at_utc",
        "object_refs",
        "source_refs",
        "evidence_refs",
    }
)
_MANAGED_EXPORT_FIELDS = frozenset({"snapshot", "objects", "corrections"})
_CORRECTION_DISPOSITIONS = frozenset({"withdraw_current", "rejudge"})
_MAX_JSON_DEPTH = 64


def _exact_fields(
    value: object,
    expected: frozenset[str],
    name: str,
) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected:
        raise RightsContractViolation(f"invalid {name}")
    return value


def _meaningful_text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or value == "*":
        raise RightsContractViolation(f"invalid {name}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RightsContractViolation(f"invalid {name}") from exc
    return value


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise RightsContractViolation(f"invalid {name}")
    return value


def _sha256_digest(value: object, name: str) -> str:
    text = _meaningful_text(value, name)
    if not text.startswith("sha256:") or len(text) != len("sha256:") + 64:
        raise RightsContractViolation(f"invalid {name}")
    try:
        int(text.removeprefix("sha256:"), 16)
    except ValueError as exc:
        raise RightsContractViolation(f"invalid {name}") from exc
    return text


def _utc_time(value: object, name: str) -> str:
    text = _meaningful_text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RightsContractViolation(f"invalid {name}") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset() != timedelta(0)
    ):
        raise RightsContractViolation(f"invalid {name}")
    return text


def _wire_refs(
    value: object,
    name: str,
    *,
    allowed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise RightsContractViolation(f"invalid {name}")
    result = tuple(_meaningful_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise RightsContractViolation(f"invalid {name}")
    if allowed is not None and not set(result).issubset(allowed):
        raise RightsContractViolation(f"invalid {name}")
    return result


def _validate_refs(
    value: object,
    name: str,
    *,
    allowed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise RightsContractViolation(f"invalid {name}")
    result = tuple(_meaningful_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise RightsContractViolation(f"invalid {name}")
    if allowed is not None and not set(result).issubset(allowed):
        raise RightsContractViolation(f"invalid {name}")
    return result


def _validate_optional_refs(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise RightsContractViolation(f"invalid {name}")
    result = tuple(_meaningful_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise RightsContractViolation(f"invalid {name}")
    return result


def _freeze_json(
    value: object,
    name: str,
    *,
    depth: int = 0,
    ancestors: set[int] | None = None,
) -> object:
    """Copy one standard JSON value into an immutable representation."""

    if depth > _MAX_JSON_DEPTH:
        raise RightsContractViolation(f"invalid {name}")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise RightsContractViolation(f"invalid {name}")
        return value
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise RightsContractViolation(f"invalid {name}") from exc
        return value
    if type(value) not in {list, dict}:
        raise RightsContractViolation(f"invalid {name}")

    active = set() if ancestors is None else ancestors
    identity = id(value)
    if identity in active:
        raise RightsContractViolation(f"invalid {name}")
    active.add(identity)
    try:
        if type(value) is list:
            return tuple(
                _freeze_json(
                    item,
                    name,
                    depth=depth + 1,
                    ancestors=active,
                )
                for item in value
            )

        frozen: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise RightsContractViolation(f"invalid {name}")
            try:
                key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise RightsContractViolation(f"invalid {name}") from exc
            frozen[key] = _freeze_json(
                item,
                name,
                depth=depth + 1,
                ancestors=active,
            )
        return MappingProxyType(frozen)
    finally:
        active.remove(identity)


def _thaw_json(value: object, name: str, *, depth: int = 0) -> object:
    """Return a detached JSON representation of one frozen managed value."""

    if depth > _MAX_JSON_DEPTH:
        raise RightsContractViolation(f"invalid {name}")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise RightsContractViolation(f"invalid {name}")
        return value
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise RightsContractViolation(f"invalid {name}") from exc
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise RightsContractViolation(f"invalid {name}")
            result[key] = _thaw_json(item, name, depth=depth + 1)
        return result
    if type(value) is tuple:
        return [_thaw_json(item, name, depth=depth + 1) for item in value]
    raise RightsContractViolation(f"invalid {name}")


@dataclass(frozen=True, slots=True)
class ManagedObject:
    """One immutable current-or-historical managed object representation."""

    object_ref: str
    object_kind: str
    owner_id: str
    installation_id: str
    version: int
    current: bool
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    value: object

    def __post_init__(self) -> None:
        _meaningful_text(self.object_ref, "managed object reference")
        _meaningful_text(self.object_kind, "managed object kind")
        _meaningful_text(self.owner_id, "managed object owner")
        _meaningful_text(self.installation_id, "managed object installation")
        _positive_integer(self.version, "managed object version")
        if type(self.current) is not bool:
            raise RightsContractViolation("invalid managed object current status")
        _validate_refs(self.source_refs, "managed object source references")
        _validate_refs(self.evidence_refs, "managed object evidence references")
        object.__setattr__(
            self,
            "value",
            _freeze_json(self.value, "managed object JSON value"),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "object_ref": self.object_ref,
            "object_kind": self.object_kind,
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "version": self.version,
            "current": self.current,
            "source_refs": list(self.source_refs),
            "evidence_refs": list(self.evidence_refs),
            "value": _thaw_json(self.value, "managed object JSON value"),
        }

    @classmethod
    def from_wire(cls, value: object) -> "ManagedObject":
        fields = _exact_fields(
            value,
            _MANAGED_OBJECT_FIELDS,
            "managed object",
        )
        current = fields["current"]
        if type(current) is not bool:
            raise RightsContractViolation("invalid managed object current status")
        return cls(
            object_ref=_meaningful_text(
                fields["object_ref"],
                "managed object reference",
            ),
            object_kind=_meaningful_text(
                fields["object_kind"],
                "managed object kind",
            ),
            owner_id=_meaningful_text(fields["owner_id"], "managed object owner"),
            installation_id=_meaningful_text(
                fields["installation_id"],
                "managed object installation",
            ),
            version=_positive_integer(fields["version"], "managed object version"),
            current=current,
            source_refs=_wire_refs(
                fields["source_refs"],
                "managed object source references",
            ),
            evidence_refs=_wire_refs(
                fields["evidence_refs"],
                "managed object evidence references",
            ),
            value=fields["value"],
        )


@dataclass(frozen=True, slots=True)
class ManagedObjectReference:
    """An exact current-object reference, independent of writer generation."""

    object_ref: str
    installation_id: str
    version: int

    def __post_init__(self) -> None:
        _meaningful_text(self.object_ref, "managed object reference")
        _meaningful_text(self.installation_id, "managed object installation")
        _positive_integer(self.version, "managed object version")

    def to_wire(self) -> dict[str, object]:
        return {
            "object_ref": self.object_ref,
            "installation_id": self.installation_id,
            "version": self.version,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ManagedObjectReference":
        fields = _exact_fields(
            value,
            _MANAGED_OBJECT_REFERENCE_FIELDS,
            "managed object reference",
        )
        return cls(
            object_ref=_meaningful_text(
                fields["object_ref"], "managed object reference"
            ),
            installation_id=_meaningful_text(
                fields["installation_id"], "managed object installation"
            ),
            version=_positive_integer(
                fields["version"], "managed object version"
            ),
        )


@dataclass(frozen=True, slots=True)
class CorrectionRevision:
    """An append-only correction link from one version to its successor."""

    correction_id: str
    object_ref: str
    previous_version: int
    revision_version: int
    reason: str
    corrected_at_utc: str
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    affected_object_refs: tuple[str, ...]
    disposition_requests: tuple[str, ...]

    def __post_init__(self) -> None:
        _meaningful_text(self.correction_id, "correction identifier")
        _meaningful_text(self.object_ref, "corrected object reference")
        previous = _positive_integer(
            self.previous_version,
            "previous object version",
        )
        revision = _positive_integer(
            self.revision_version,
            "correction revision version",
        )
        if revision != previous + 1:
            raise RightsContractViolation("correction must inherit the next version")
        _meaningful_text(self.reason, "correction reason")
        _utc_time(self.corrected_at_utc, "correction UTC time")
        _validate_refs(self.source_refs, "correction source references")
        _validate_refs(self.evidence_refs, "correction evidence references")
        _validate_refs(
            self.affected_object_refs,
            "correction affected object references",
        )
        _validate_refs(
            self.disposition_requests,
            "correction disposition requests",
            allowed=_CORRECTION_DISPOSITIONS,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "correction_id": self.correction_id,
            "object_ref": self.object_ref,
            "previous_version": self.previous_version,
            "revision_version": self.revision_version,
            "reason": self.reason,
            "corrected_at_utc": self.corrected_at_utc,
            "source_refs": list(self.source_refs),
            "evidence_refs": list(self.evidence_refs),
            "affected_object_refs": list(self.affected_object_refs),
            "disposition_requests": list(self.disposition_requests),
        }

    @classmethod
    def from_wire(cls, value: object) -> "CorrectionRevision":
        fields = _exact_fields(
            value,
            _CORRECTION_REVISION_FIELDS,
            "correction revision",
        )
        return cls(
            correction_id=_meaningful_text(
                fields["correction_id"],
                "correction identifier",
            ),
            object_ref=_meaningful_text(
                fields["object_ref"],
                "corrected object reference",
            ),
            previous_version=_positive_integer(
                fields["previous_version"],
                "previous object version",
            ),
            revision_version=_positive_integer(
                fields["revision_version"],
                "correction revision version",
            ),
            reason=_meaningful_text(fields["reason"], "correction reason"),
            corrected_at_utc=_utc_time(
                fields["corrected_at_utc"],
                "correction UTC time",
            ),
            source_refs=_wire_refs(
                fields["source_refs"],
                "correction source references",
            ),
            evidence_refs=_wire_refs(
                fields["evidence_refs"],
                "correction evidence references",
            ),
            affected_object_refs=_wire_refs(
                fields["affected_object_refs"],
                "correction affected object references",
            ),
            disposition_requests=_wire_refs(
                fields["disposition_requests"],
                "correction disposition requests",
                allowed=_CORRECTION_DISPOSITIONS,
            ),
        )


@dataclass(frozen=True, slots=True)
class ExportSnapshot:
    """Finite read-only metadata for one managed export snapshot."""

    snapshot_id: str
    owner_id: str
    installation_id: str
    source_state_digest: str
    schema_version: str
    created_at_utc: str
    object_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _meaningful_text(self.snapshot_id, "export snapshot identifier")
        _meaningful_text(self.owner_id, "export snapshot owner")
        _meaningful_text(self.installation_id, "export snapshot installation")
        _sha256_digest(self.source_state_digest, "export source state digest")
        if self.schema_version != MANAGED_EXPORT_SCHEMA_VERSION:
            raise RightsContractViolation("invalid managed export schema version")
        _utc_time(self.created_at_utc, "export snapshot UTC time")
        _validate_refs(self.object_refs, "export snapshot object references")
        _validate_refs(self.source_refs, "export snapshot source references")
        _validate_refs(self.evidence_refs, "export snapshot evidence references")

    def to_wire(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "source_state_digest": self.source_state_digest,
            "schema_version": self.schema_version,
            "created_at_utc": self.created_at_utc,
            "object_refs": list(self.object_refs),
            "source_refs": list(self.source_refs),
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_wire(cls, value: object) -> "ExportSnapshot":
        fields = _exact_fields(
            value,
            _EXPORT_SNAPSHOT_FIELDS,
            "export snapshot",
        )
        schema_version = _meaningful_text(
            fields["schema_version"],
            "managed export schema version",
        )
        if schema_version != MANAGED_EXPORT_SCHEMA_VERSION:
            raise RightsContractViolation("invalid managed export schema version")
        return cls(
            snapshot_id=_meaningful_text(
                fields["snapshot_id"],
                "export snapshot identifier",
            ),
            owner_id=_meaningful_text(fields["owner_id"], "export snapshot owner"),
            installation_id=_meaningful_text(
                fields["installation_id"],
                "export snapshot installation",
            ),
            source_state_digest=_sha256_digest(
                fields["source_state_digest"],
                "export source state digest",
            ),
            schema_version=schema_version,
            created_at_utc=_utc_time(
                fields["created_at_utc"],
                "export snapshot UTC time",
            ),
            object_refs=_wire_refs(
                fields["object_refs"],
                "export snapshot object references",
            ),
            source_refs=_wire_refs(
                fields["source_refs"],
                "export snapshot source references",
            ),
            evidence_refs=_wire_refs(
                fields["evidence_refs"],
                "export snapshot evidence references",
            ),
        )


@dataclass(frozen=True, slots=True)
class ManagedRightsProjection:
    """A transient, core-formed view over one verified daily-state digest."""

    owner_id: str
    installation_id: str
    source_state_digest: str
    objects: tuple[ManagedObject, ...]
    permitted_object_refs: tuple[str, ...]
    revoked_object_refs: tuple[str, ...]
    corrections: tuple[CorrectionRevision, ...] = ()

    def __post_init__(self) -> None:
        _meaningful_text(self.owner_id, "managed projection owner")
        _meaningful_text(self.installation_id, "managed projection installation")
        _sha256_digest(self.source_state_digest, "managed projection state digest")
        if type(self.objects) is not tuple or any(
            type(item) is not ManagedObject for item in self.objects
        ):
            raise RightsContractViolation("invalid managed projection objects")
        object_refs = tuple(item.object_ref for item in self.objects)
        if len(object_refs) != len(set(object_refs)):
            raise RightsContractViolation("duplicate managed projection object")
        if any(
            item.owner_id != self.owner_id
            or item.installation_id != self.installation_id
            for item in self.objects
        ):
            raise RightsContractViolation("managed projection identity mismatch")
        permitted = _validate_optional_refs(
            self.permitted_object_refs,
            "managed projection permitted references",
        )
        revoked = _validate_optional_refs(
            self.revoked_object_refs,
            "managed projection revoked references",
        )
        if type(self.corrections) is not tuple or any(
            type(item) is not CorrectionRevision for item in self.corrections
        ):
            raise RightsContractViolation("invalid managed projection corrections")
        correction_ids = tuple(item.correction_id for item in self.corrections)
        correction_links = tuple(
            (item.object_ref, item.revision_version)
            for item in self.corrections
        )
        if (
            len(correction_ids) != len(set(correction_ids))
            or len(correction_links) != len(set(correction_links))
        ):
            raise RightsContractViolation("duplicate managed projection correction")
        known = set(object_refs)
        if (
            not set(permitted).issubset(known)
            or not set(revoked).issubset(known)
            or set(permitted).intersection(revoked)
        ):
            raise RightsContractViolation("invalid managed projection permission scope")
        if any(item.object_ref not in known for item in self.corrections):
            raise RightsContractViolation(
                "managed projection correction object is missing"
            )


@dataclass(frozen=True, slots=True)
class PendingCorrectionDraft:
    """Owner-authored correction intent awaiting Ticket 112 authority commit."""

    owner_id: str
    installation_id: str
    base_state_digest: str
    target_ref: ManagedObjectReference
    revision: CorrectionRevision
    previous_value: object
    maintenance_request: EvidenceMaintenanceRequest

    def __post_init__(self) -> None:
        _meaningful_text(self.owner_id, "pending correction owner")
        _meaningful_text(self.installation_id, "pending correction installation")
        _sha256_digest(self.base_state_digest, "pending correction state digest")
        if (
            type(self.target_ref) is not ManagedObjectReference
            or self.target_ref.installation_id != self.installation_id
        ):
            raise RightsContractViolation("pending correction target mismatch")
        if (
            type(self.revision) is not CorrectionRevision
            or self.revision.object_ref != self.target_ref.object_ref
            or self.revision.previous_version != self.target_ref.version
        ):
            raise RightsContractViolation("pending correction revision mismatch")
        object.__setattr__(
            self,
            "previous_value",
            _freeze_json(
                self.previous_value,
                "pending correction previous JSON value",
            ),
        )
        if (
            type(self.maintenance_request) is not EvidenceMaintenanceRequest
            or self.maintenance_request.action != "correct"
            or self.maintenance_request.target_evidence_ids
            != self.revision.evidence_refs
            or self.maintenance_request.reason != self.revision.reason
            or self.maintenance_request.replacement_claim is None
        ):
            raise RightsContractViolation("pending correction maintenance mismatch")


@dataclass(frozen=True, slots=True)
class ManagedExport:
    """A finite, schema-parseable export with no import or write behavior."""

    snapshot: ExportSnapshot
    objects: tuple[ManagedObject, ...]
    corrections: tuple[CorrectionRevision, ...] = ()

    def __post_init__(self) -> None:
        if type(self.snapshot) is not ExportSnapshot:
            raise RightsContractViolation("invalid managed export snapshot")
        if type(self.objects) is not tuple or any(
            type(item) is not ManagedObject for item in self.objects
        ):
            raise RightsContractViolation("invalid managed export objects")
        if type(self.corrections) is not tuple or any(
            type(item) is not CorrectionRevision for item in self.corrections
        ):
            raise RightsContractViolation("invalid managed export corrections")
        correction_ids = tuple(item.correction_id for item in self.corrections)
        correction_links = tuple(
            (item.object_ref, item.revision_version)
            for item in self.corrections
        )
        if (
            len(correction_ids) != len(set(correction_ids))
            or len(correction_links) != len(set(correction_links))
        ):
            raise RightsContractViolation("duplicate managed export correction")
        if tuple(item.object_ref for item in self.objects) != self.snapshot.object_refs:
            raise RightsContractViolation("managed export object scope mismatch")
        if any(
            item.owner_id != self.snapshot.owner_id
            or item.installation_id != self.snapshot.installation_id
            or not item.current
            for item in self.objects
        ):
            raise RightsContractViolation("managed export object identity mismatch")
        expected_sources = tuple(
            dict.fromkeys(
                source_ref
                for item in self.objects
                for source_ref in item.source_refs
            )
        )
        expected_evidence = tuple(
            dict.fromkeys(
                evidence_ref
                for item in self.objects
                for evidence_ref in item.evidence_refs
            )
        )
        if (
            self.snapshot.source_refs != expected_sources
            or self.snapshot.evidence_refs != expected_evidence
        ):
            raise RightsContractViolation("managed export lineage mismatch")
        if any(
            correction.object_ref not in set(self.snapshot.object_refs)
            for correction in self.corrections
        ):
            raise RightsContractViolation("managed export correction scope mismatch")

    def to_wire(self) -> dict[str, object]:
        return {
            "snapshot": self.snapshot.to_wire(),
            "objects": [item.to_wire() for item in self.objects],
            "corrections": [item.to_wire() for item in self.corrections],
        }

    @classmethod
    def from_wire(cls, value: object) -> "ManagedExport":
        fields = _exact_fields(value, _MANAGED_EXPORT_FIELDS, "managed export")
        raw_objects = fields["objects"]
        raw_corrections = fields["corrections"]
        if type(raw_objects) is not list or type(raw_corrections) is not list:
            raise RightsContractViolation("invalid managed export")
        return cls(
            snapshot=ExportSnapshot.from_wire(fields["snapshot"]),
            objects=tuple(ManagedObject.from_wire(item) for item in raw_objects),
            corrections=tuple(
                CorrectionRevision.from_wire(item) for item in raw_corrections
            ),
        )


class ManagedRightsService:
    """Pure managed-read operations over a verified ``DailyHealthState`` view."""

    @staticmethod
    def _evidence_lineage(
        state: DailyHealthState,
    ) -> dict[str, tuple[str, int]]:
        predecessors: dict[str, str] = {}
        for change in state.evidence_applicability_changes:
            if (
                change.applicability != "corrected"
                or change.successor_evidence_id is None
            ):
                continue
            existing = predecessors.get(change.successor_evidence_id)
            if existing is not None and existing != change.target_evidence_id:
                raise RightsContractViolation("forked managed evidence predecessor")
            predecessors[change.successor_evidence_id] = change.target_evidence_id
        card_ids = {card.evidence_id for card in state.evidence_cards}
        lineage: dict[str, tuple[str, int]] = {}
        visiting: set[str] = set()

        def lineage_for(evidence_id: str) -> tuple[str, int]:
            known = lineage.get(evidence_id)
            if known is not None:
                return known
            if evidence_id in visiting:
                raise RightsContractViolation("cyclic managed evidence history")
            visiting.add(evidence_id)
            try:
                predecessor = predecessors.get(evidence_id)
                if predecessor is None:
                    result = (evidence_id, 1)
                else:
                    if predecessor not in card_ids:
                        raise RightsContractViolation(
                            "managed evidence predecessor is missing"
                        )
                    root_ref, predecessor_version = lineage_for(predecessor)
                    result = (root_ref, predecessor_version + 1)
                lineage[evidence_id] = result
                return result
            finally:
                visiting.remove(evidence_id)

        for card in state.evidence_cards:
            lineage_for(card.evidence_id)
        return lineage

    @staticmethod
    def _portrait_version(state: DailyHealthState, topic_ref: str) -> int:
        revisions = tuple(
            revision
            for revision in state.portrait_revisions
            if revision.topic_ref == topic_ref
        )
        if not revisions:
            return 1
        return len(revisions) if revisions[0].previous_topic is None else len(revisions) + 1

    @classmethod
    def _project_from_daily_state(
        cls,
        state: DailyHealthState,
        *,
        owner_id: str,
        installation_id: str,
        permitted_object_refs: tuple[str, ...],
        revoked_object_refs: tuple[str, ...],
    ) -> ManagedRightsProjection:
        """Core-only mapper from a verified state; not a caller authority seam."""

        if type(state) is not DailyHealthState:
            raise RightsContractViolation("verified daily health state required")
        _meaningful_text(owner_id, "managed projection owner")
        _meaningful_text(installation_id, "managed projection installation")
        lineage = cls._evidence_lineage(state)
        representatives: dict[str, tuple[int, EvidenceCard]] = {}
        root_order: list[str] = []
        for card in state.evidence_cards:
            root_ref, version = lineage[card.evidence_id]
            previous = representatives.get(root_ref)
            if previous is None:
                root_order.append(root_ref)
                representatives[root_ref] = (version, card)
            elif version > previous[0]:
                representatives[root_ref] = (version, card)
            elif version == previous[0] and card.evidence_id != previous[1].evidence_id:
                raise RightsContractViolation("forked managed evidence correction chain")

        objects: list[ManagedObject] = []
        for root_ref in root_order:
            version, card = representatives[root_ref]
            objects.append(
                ManagedObject(
                object_ref=root_ref,
                object_kind="evidence_card",
                owner_id=owner_id,
                installation_id=installation_id,
                version=version,
                current=state.is_evidence_current(card.evidence_id),
                source_refs=(card.source_causal_id,),
                evidence_refs=(card.evidence_id,),
                value=card.to_storage(),
            )
            )
        cards = {card.evidence_id: card for card in state.evidence_cards}
        for topic in state.portrait_topics:
            source_refs = tuple(
                dict.fromkeys(
                    cards[evidence_id].source_causal_id
                    for evidence_id in topic.evidence_ids
                    if evidence_id in cards
                )
            )
            objects.append(
                ManagedObject(
                    object_ref=f"portrait-topic:{topic.topic_ref}",
                    object_kind="portrait_topic",
                    owner_id=owner_id,
                    installation_id=installation_id,
                    version=cls._portrait_version(state, topic.topic_ref),
                    current=True,
                    source_refs=source_refs,
                    evidence_refs=topic.evidence_ids,
                    value=topic.to_storage(),
                )
            )
        logical_refs = {
            evidence_id: root_ref
            for evidence_id, (root_ref, _version) in lineage.items()
        }

        def normalize_scope(refs: tuple[str, ...]) -> tuple[str, ...]:
            if type(refs) is not tuple:
                raise RightsContractViolation("invalid managed projection scope")
            return tuple(
                dict.fromkeys(
                    logical_refs.get(
                        _meaningful_text(ref, "managed projection scope reference"),
                        ref,
                    )
                    for ref in refs
                )
            )

        return ManagedRightsProjection(
            owner_id=owner_id,
            installation_id=installation_id,
            source_state_digest=state.digest,
            objects=tuple(objects),
            permitted_object_refs=normalize_scope(permitted_object_refs),
            revoked_object_refs=normalize_scope(revoked_object_refs),
            corrections=tuple(
                CorrectionRevision(
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
                )
                for revision in state.owner_correction_revisions
                if type(revision) is OwnerCorrectionRevision
            ),
        )

    @staticmethod
    def _authorize(
        projection: ManagedRightsProjection,
        *,
        requester_owner_id: str,
        permission: object,
        expected_permission: str,
    ) -> None:
        if type(projection) is not ManagedRightsProjection:
            raise RightsContractViolation("managed rights projection required")
        if (
            requester_owner_id != projection.owner_id
            or type(permission) is not str
            or permission != expected_permission
        ):
            raise RightsContractViolation("managed rights permission denied")

    @staticmethod
    def _resolve(
        projection: ManagedRightsProjection,
        requested_refs: tuple[ManagedObjectReference, ...],
    ) -> tuple[ManagedObject, ...]:
        if type(requested_refs) is not tuple or not requested_refs or any(
            type(item) is not ManagedObjectReference for item in requested_refs
        ):
            raise RightsContractViolation("invalid managed object request scope")
        if len(set(requested_refs)) != len(requested_refs):
            raise RightsContractViolation("duplicate managed object request")
        objects = {item.object_ref: item for item in projection.objects}
        permitted = set(projection.permitted_object_refs)
        revoked = set(projection.revoked_object_refs)
        result: list[ManagedObject] = []
        for requested in requested_refs:
            item = objects.get(requested.object_ref)
            if (
                requested.installation_id != projection.installation_id
                or item is None
                or item.installation_id != requested.installation_id
                or requested.object_ref not in permitted
                or requested.object_ref in revoked
                or not item.current
                or item.version != requested.version
            ):
                raise RightsContractViolation("managed object reference is not current")
            result.append(item)
        return tuple(result)

    @classmethod
    def managed_read(
        cls,
        projection: ManagedRightsProjection,
        *,
        requester_owner_id: str,
        permission: object,
        requested_refs: tuple[ManagedObjectReference, ...],
    ) -> tuple[ManagedObject, ...]:
        cls._authorize(
            projection,
            requester_owner_id=requester_owner_id,
            permission=permission,
            expected_permission="health_data.read",
        )
        return cls._resolve(projection, requested_refs)

    @classmethod
    def correct(
        cls,
        projection: ManagedRightsProjection,
        *,
        requester_owner_id: str,
        permission: object,
        target_ref: ManagedObjectReference,
        correction_id: str,
        reason: str,
        corrected_at_utc: str,
        replacement_claim: AtomicEvidenceClaim,
        correction_source_refs: tuple[str, ...],
        affected_object_refs: tuple[str, ...],
        disposition_requests: tuple[str, ...],
    ) -> PendingCorrectionDraft:
        cls._authorize(
            projection,
            requester_owner_id=requester_owner_id,
            permission=permission,
            expected_permission="health_data.correct",
        )
        if type(target_ref) is not ManagedObjectReference:
            raise RightsContractViolation("managed correction target required")
        target = cls._resolve(projection, (target_ref,))[0]
        if target.object_kind != "evidence_card":
            raise RightsContractViolation("only evidence supports managed correction")
        if type(replacement_claim) is not AtomicEvidenceClaim:
            raise RightsContractViolation("typed replacement claim required")
        previous_value = target.to_wire()["value"]
        if type(previous_value) is not dict:
            raise RightsContractViolation("invalid managed evidence projection")
        if (
            replacement_claim.evidence_type != previous_value.get("evidence_type")
            or replacement_claim.series_key.atomic_dimension
            != previous_value.get("series_key", {}).get("atomic_dimension")
            or not set(replacement_claim.topic_refs).intersection(
                previous_value.get("topic_refs", [])
            )
        ):
            raise RightsContractViolation("correction crossed an evidence dimension")
        revision = CorrectionRevision(
            correction_id=correction_id,
            object_ref=target.object_ref,
            previous_version=target.version,
            revision_version=target.version + 1,
            reason=reason,
            corrected_at_utc=corrected_at_utc,
            source_refs=_validate_refs(
                correction_source_refs,
                "correction source references",
            ),
            evidence_refs=target.evidence_refs,
            affected_object_refs=_validate_refs(
                affected_object_refs,
                "correction affected object references",
            ),
            disposition_requests=_validate_refs(
                disposition_requests,
                "correction disposition requests",
                allowed=_CORRECTION_DISPOSITIONS,
            ),
        )
        request = EvidenceMaintenanceRequest(
            "correct",
            target.evidence_refs,
            reason,
            replacement_claim.purpose,
            replacement_claim,
        )
        return PendingCorrectionDraft(
            owner_id=projection.owner_id,
            installation_id=projection.installation_id,
            base_state_digest=projection.source_state_digest,
            target_ref=target_ref,
            revision=revision,
            previous_value=previous_value,
            maintenance_request=request,
        )

    @classmethod
    def export(
        cls,
        projection: ManagedRightsProjection,
        *,
        requester_owner_id: str,
        permission: object,
        requested_refs: tuple[ManagedObjectReference, ...],
        snapshot_id: str,
        created_at_utc: str,
    ) -> ManagedExport:
        cls._authorize(
            projection,
            requester_owner_id=requester_owner_id,
            permission=permission,
            expected_permission="health_data.export",
        )
        objects = cls._resolve(projection, requested_refs)
        snapshot = ExportSnapshot(
            snapshot_id=snapshot_id,
            owner_id=projection.owner_id,
            installation_id=projection.installation_id,
            source_state_digest=projection.source_state_digest,
            schema_version=MANAGED_EXPORT_SCHEMA_VERSION,
            created_at_utc=created_at_utc,
            object_refs=tuple(item.object_ref for item in objects),
            source_refs=tuple(
                dict.fromkeys(
                    source_ref for item in objects for source_ref in item.source_refs
                )
            ),
            evidence_refs=tuple(
                dict.fromkeys(
                    evidence_ref
                    for item in objects
                    for evidence_ref in item.evidence_refs
                )
            ),
        )
        selected_refs = set(snapshot.object_refs)
        return ManagedExport(
            snapshot=snapshot,
            objects=objects,
            corrections=tuple(
                correction
                for correction in projection.corrections
                if correction.object_ref in selected_refs
            ),
        )


__all__ = [
    "MANAGED_EXPORT_SCHEMA_VERSION",
    "RightsContractViolation",
    "ManagedObject",
    "ManagedObjectReference",
    "CorrectionRevision",
    "ExportSnapshot",
    "ManagedRightsProjection",
    "PendingCorrectionDraft",
    "ManagedExport",
    "ManagedRightsService",
]

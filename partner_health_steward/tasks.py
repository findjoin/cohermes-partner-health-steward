"""Authoritative health-task values and state transitions for Ticket 115."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .initialization import stable_digest


class TaskContractViolation(ValueError):
    """A value cannot cross the managed task boundary."""


TASK_PRIMARY_LABELS = ("active", "solved", "failed", "cancelled")
TASK_SOURCE_KINDS = ("owner-goal", "portrait-evidence", "task-event")
TASK_PHASES = (
    "planned",
    "waiting-owner",
    "waiting-approval",
    "in-progress",
    "awaiting-result",
    "accepted",
    "closed",
)
TASK_INITIAL_PHASES = ("planned", "waiting-owner", "waiting-approval")
TASK_APPROVAL_STATUSES = ("not-required", "waiting", "bound", "withdrawn")
TASK_UNKNOWN_RESOLUTIONS = (
    "delivered",
    "not-delivered",
    "owner-authorized-new-attempt",
)


def _mapping(value: object, fields: frozenset[str], name: str) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != fields:
        raise TaskContractViolation(f"invalid {name}")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise TaskContractViolation(f"invalid {name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TaskContractViolation(f"invalid {name}") from exc
    if len(encoded) > 65_536:
        raise TaskContractViolation(f"invalid {name}")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _sha256(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise TaskContractViolation(f"invalid {name}")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise TaskContractViolation(f"invalid {name}") from exc
    return text


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise TaskContractViolation(f"invalid {name}")
    return value


def _nonnegative_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise TaskContractViolation(f"invalid {name}")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TaskContractViolation(f"invalid {name}")
    return value


def _tuple_texts(
    value: object,
    name: str,
    *,
    allow_empty: bool = False,
    ordered: bool = False,
) -> tuple[str, ...]:
    if type(value) is not tuple or (not allow_empty and not value):
        raise TaskContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if result != value or len(result) != len(set(result)):
        raise TaskContractViolation(f"invalid {name}")
    if ordered and result != tuple(sorted(result)):
        raise TaskContractViolation(f"invalid {name} order")
    return result


def _wire_texts(
    value: object,
    name: str,
    *,
    allow_empty: bool = False,
    ordered: bool = False,
) -> tuple[str, ...]:
    if type(value) is not list or (not allow_empty and not value):
        raise TaskContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise TaskContractViolation(f"invalid {name}")
    if ordered and result != tuple(sorted(result)):
        raise TaskContractViolation(f"invalid {name} order")
    return result


def _utc_time(value: object, name: str) -> str:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TaskContractViolation(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise TaskContractViolation(f"invalid {name}")
    return text


@dataclass(frozen=True)
class TaskExternalBoundary:
    """The exact recipients and effect kinds a task may eventually use."""

    recipient_refs: tuple[str, ...]
    effect_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        recipients = _tuple_texts(
            self.recipient_refs,
            "task external recipient",
            allow_empty=True,
            ordered=True,
        )
        effects = _tuple_texts(
            self.effect_kinds,
            "task external effect kind",
            allow_empty=True,
            ordered=True,
        )
        if bool(recipients) != bool(effects):
            raise TaskContractViolation(
                "task external recipients and effect kinds must be declared together"
            )

    @classmethod
    def internal_only(cls) -> "TaskExternalBoundary":
        return cls(recipient_refs=(), effect_kinds=())

    @property
    def permits_external_effect(self) -> bool:
        return bool(self.effect_kinds)

    def to_storage(self) -> dict[str, object]:
        return {
            "recipient_refs": list(self.recipient_refs),
            "effect_kinds": list(self.effect_kinds),
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskExternalBoundary":
        stored = _mapping(
            value,
            frozenset({"recipient_refs", "effect_kinds"}),
            "task external boundary",
        )
        return cls(
            recipient_refs=_wire_texts(
                stored["recipient_refs"],
                "task external recipient",
                allow_empty=True,
                ordered=True,
            ),
            effect_kinds=_wire_texts(
                stored["effect_kinds"],
                "task external effect kind",
                allow_empty=True,
                ordered=True,
            ),
        )


@dataclass(frozen=True)
class TaskApprovalBinding:
    """A task's approval requirement and optional current approval reference."""

    status: str
    approval_id: str | None
    approval_version: int | None

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in TASK_APPROVAL_STATUSES:
            raise TaskContractViolation("invalid task approval status")
        approval_id = _optional_text(self.approval_id, "task approval identifier")
        approval_version = self.approval_version
        if self.status in {"not-required", "waiting"}:
            if approval_id is not None or approval_version is not None:
                raise TaskContractViolation(
                    "unbound task approval cannot carry an approval reference"
                )
        else:
            if approval_id is None:
                raise TaskContractViolation("bound task approval requires an identifier")
            _positive_integer(approval_version, "task approval version")

    @classmethod
    def not_required(cls) -> "TaskApprovalBinding":
        return cls("not-required", None, None)

    @classmethod
    def waiting(cls) -> "TaskApprovalBinding":
        return cls("waiting", None, None)

    @classmethod
    def bound(cls, approval_id: str, approval_version: int) -> "TaskApprovalBinding":
        return cls("bound", approval_id, approval_version)

    @classmethod
    def withdrawn(cls, approval_id: str, approval_version: int) -> "TaskApprovalBinding":
        return cls("withdrawn", approval_id, approval_version)

    def to_storage(self) -> dict[str, object]:
        return {
            "status": self.status,
            "approval_id": self.approval_id,
            "approval_version": self.approval_version,
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskApprovalBinding":
        stored = _mapping(
            value,
            frozenset({"status", "approval_id", "approval_version"}),
            "task approval binding",
        )
        approval_version = stored["approval_version"]
        if approval_version is not None:
            approval_version = _positive_integer(
                approval_version, "task approval version"
            )
        return cls(
            status=_text(stored["status"], "task approval status"),
            approval_id=_optional_text(
                stored["approval_id"], "task approval identifier"
            ),
            approval_version=approval_version,
        )


def _validate_task_scope(
    external_boundary: TaskExternalBoundary,
    approval: TaskApprovalBinding,
    phase: str,
    *,
    initial: bool,
) -> None:
    if type(external_boundary) is not TaskExternalBoundary:
        raise TaskContractViolation("invalid task external boundary")
    if type(approval) is not TaskApprovalBinding:
        raise TaskContractViolation("invalid task approval binding")
    if phase not in TASK_PHASES or (initial and phase not in TASK_INITIAL_PHASES):
        raise TaskContractViolation("invalid task phase")
    if external_boundary.permits_external_effect:
        if approval.status == "not-required":
            raise TaskContractViolation("external task effect requires explicit approval")
    elif approval.status != "not-required":
        raise TaskContractViolation("internal-only task cannot bind external approval")
    if approval.status in {"waiting", "withdrawn"} and phase != "waiting-approval":
        raise TaskContractViolation("unapproved task must wait for approval")
    if approval.status == "bound" and phase == "waiting-approval":
        raise TaskContractViolation("approved task cannot remain waiting for approval")


def _semantic_digest(
    *,
    purpose: str,
    expected_result: str,
    assignee: str,
    allowed_data_categories: tuple[str, ...],
    allowed_data_refs: tuple[str, ...],
    external_boundary: TaskExternalBoundary,
    acceptance_criteria: tuple[str, ...],
) -> str:
    return stable_digest(
        {
            "purpose": purpose,
            "expected_result": expected_result,
            "assignee": assignee,
            "allowed_data_categories": list(allowed_data_categories),
            "allowed_data_refs": list(allowed_data_refs),
            "external_boundary": external_boundary.to_storage(),
            "acceptance_criteria": list(acceptance_criteria),
        }
    )


@dataclass(frozen=True)
class TaskCandidate:
    """A non-authoritative task proposal from an allowed product source."""

    candidate_id: str
    source_kind: str
    source_ref: str
    source_revision_digest: str
    purpose: str
    expected_result: str
    assignee: str
    allowed_data_categories: tuple[str, ...]
    allowed_data_refs: tuple[str, ...]
    external_boundary: TaskExternalBoundary
    phase: str
    approval: TaskApprovalBinding
    acceptance_criteria: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.candidate_id, "task candidate identifier")
        if type(self.source_kind) is not str or self.source_kind not in TASK_SOURCE_KINDS:
            raise TaskContractViolation("invalid task candidate source")
        _text(self.source_ref, "task candidate source reference")
        _sha256(self.source_revision_digest, "task candidate source revision")
        _text(self.purpose, "task purpose")
        _text(self.expected_result, "task expected result")
        _text(self.assignee, "task assignee")
        _tuple_texts(self.allowed_data_categories, "allowed task data categories")
        _tuple_texts(self.allowed_data_refs, "allowed task data references")
        _tuple_texts(self.acceptance_criteria, "task acceptance criteria")
        _validate_task_scope(
            self.external_boundary,
            self.approval,
            self.phase,
            initial=True,
        )

    @property
    def semantic_digest(self) -> str:
        return _semantic_digest(
            purpose=self.purpose,
            expected_result=self.expected_result,
            assignee=self.assignee,
            allowed_data_categories=self.allowed_data_categories,
            allowed_data_refs=self.allowed_data_refs,
            external_boundary=self.external_boundary,
            acceptance_criteria=self.acceptance_criteria,
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "source_revision_digest": self.source_revision_digest,
            "purpose": self.purpose,
            "expected_result": self.expected_result,
            "assignee": self.assignee,
            "allowed_data_categories": list(self.allowed_data_categories),
            "allowed_data_refs": list(self.allowed_data_refs),
            "external_boundary": self.external_boundary.to_storage(),
            "phase": self.phase,
            "approval": self.approval.to_storage(),
            "acceptance_criteria": list(self.acceptance_criteria),
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskCandidate":
        stored = _mapping(
            value,
            frozenset(
                {
                    "candidate_id",
                    "source_kind",
                    "source_ref",
                    "source_revision_digest",
                    "purpose",
                    "expected_result",
                    "assignee",
                    "allowed_data_categories",
                    "allowed_data_refs",
                    "external_boundary",
                    "phase",
                    "approval",
                    "acceptance_criteria",
                }
            ),
            "task candidate",
        )
        return cls(
            candidate_id=_text(stored["candidate_id"], "task candidate identifier"),
            source_kind=_text(stored["source_kind"], "task candidate source"),
            source_ref=_text(stored["source_ref"], "task candidate source reference"),
            source_revision_digest=_sha256(
                stored["source_revision_digest"], "task candidate source revision"
            ),
            purpose=_text(stored["purpose"], "task purpose"),
            expected_result=_text(
                stored["expected_result"], "task expected result"
            ),
            assignee=_text(stored["assignee"], "task assignee"),
            allowed_data_categories=_wire_texts(
                stored["allowed_data_categories"], "allowed task data categories"
            ),
            allowed_data_refs=_wire_texts(
                stored["allowed_data_refs"], "allowed task data references"
            ),
            external_boundary=TaskExternalBoundary.from_storage(
                stored["external_boundary"]
            ),
            phase=_text(stored["phase"], "task phase"),
            approval=TaskApprovalBinding.from_storage(stored["approval"]),
            acceptance_criteria=_wire_texts(
                stored["acceptance_criteria"], "task acceptance criteria"
            ),
        )


@dataclass(frozen=True)
class TaskTerminalFact:
    primary_label: str
    reason_code: str
    evidence_refs: tuple[str, ...]
    result_digest: str | None
    recorded_at_utc: str
    acceptance: TaskAcceptance | None = None

    def __post_init__(self) -> None:
        if type(self.primary_label) is not str or self.primary_label not in {
            "solved",
            "failed",
            "cancelled",
        }:
            raise TaskContractViolation("invalid task terminal label")
        _text(self.reason_code, "task terminal reason")
        _tuple_texts(
            self.evidence_refs,
            "task terminal evidence reference",
            allow_empty=True,
            ordered=True,
        )
        if self.primary_label == "solved":
            _sha256(self.result_digest, "task terminal result digest")
            if not self.evidence_refs:
                raise TaskContractViolation("solved task requires acceptance evidence")
            if type(self.acceptance) is not TaskAcceptance:
                raise TaskContractViolation(
                    "solved task requires its complete acceptance proof"
                )
            if (
                self.acceptance.evidence_refs != self.evidence_refs
                or self.acceptance.result_digest != self.result_digest
                or self.acceptance.accepted_at_utc != self.recorded_at_utc
            ):
                raise TaskContractViolation(
                    "task terminal acceptance proof mismatch"
                )
        else:
            if self.result_digest is not None:
                _sha256(self.result_digest, "task terminal result digest")
            if self.acceptance is not None:
                raise TaskContractViolation(
                    "non-solved task cannot carry an acceptance proof"
                )
        _utc_time(self.recorded_at_utc, "task terminal time")

    def to_storage(self) -> dict[str, object]:
        return {
            "primary_label": self.primary_label,
            "reason_code": self.reason_code,
            "evidence_refs": list(self.evidence_refs),
            "result_digest": self.result_digest,
            "recorded_at_utc": self.recorded_at_utc,
            "acceptance": (
                None if self.acceptance is None else self.acceptance.to_storage()
            ),
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskTerminalFact":
        stored = _mapping(
            value,
            frozenset(
                {
                    "primary_label",
                    "reason_code",
                    "evidence_refs",
                    "result_digest",
                    "recorded_at_utc",
                    "acceptance",
                }
            ),
            "task terminal fact",
        )
        result_digest = stored["result_digest"]
        if result_digest is not None:
            result_digest = _sha256(result_digest, "task terminal result digest")
        return cls(
            primary_label=_text(stored["primary_label"], "task terminal label"),
            reason_code=_text(stored["reason_code"], "task terminal reason"),
            evidence_refs=_wire_texts(
                stored["evidence_refs"],
                "task terminal evidence reference",
                allow_empty=True,
                ordered=True,
            ),
            result_digest=result_digest,
            recorded_at_utc=_utc_time(
                stored["recorded_at_utc"], "task terminal time"
            ),
            acceptance=(
                None
                if stored["acceptance"] is None
                else TaskAcceptance.from_storage(stored["acceptance"])
            ),
        )


@dataclass(frozen=True)
class ManagedTask:
    task_id: str
    version: int
    purpose: str
    expected_result: str
    assignee: str
    allowed_data_categories: tuple[str, ...]
    allowed_data_refs: tuple[str, ...]
    external_boundary: TaskExternalBoundary
    approval: TaskApprovalBinding
    acceptance_criteria: tuple[str, ...]
    source_kinds: tuple[str, ...]
    source_refs: tuple[str, ...]
    source_revision_digests: tuple[str, ...]
    semantic_digest: str
    primary_label: str
    phase: str
    predecessor_task_ids: tuple[str, ...]
    successor_task_ids: tuple[str, ...]
    terminal_fact: TaskTerminalFact | None
    created_at_utc: str
    updated_at_utc: str

    def __post_init__(self) -> None:
        _text(self.task_id, "task identifier")
        _positive_integer(self.version, "task version")
        _text(self.purpose, "task purpose")
        _text(self.expected_result, "task expected result")
        _text(self.assignee, "task assignee")
        _tuple_texts(self.allowed_data_categories, "allowed task data categories")
        _tuple_texts(self.allowed_data_refs, "allowed task data references")
        _tuple_texts(self.acceptance_criteria, "task acceptance criteria")
        if type(self.source_kinds) is not tuple or not self.source_kinds:
            raise TaskContractViolation("invalid task source kinds")
        for source_kind in self.source_kinds:
            if type(source_kind) is not str or source_kind not in TASK_SOURCE_KINDS:
                raise TaskContractViolation("invalid task source kind")
        source_refs = _tuple_texts(
            self.source_refs,
            "task source reference",
            ordered=True,
        )
        if type(self.source_revision_digests) is not tuple:
            raise TaskContractViolation("invalid task source revisions")
        for digest in self.source_revision_digests:
            _sha256(digest, "task source revision")
        if not (
            len(self.source_kinds)
            == len(source_refs)
            == len(self.source_revision_digests)
        ):
            raise TaskContractViolation("task source bindings must align")
        _sha256(self.semantic_digest, "task semantic digest")
        if type(self.primary_label) is not str or self.primary_label not in TASK_PRIMARY_LABELS:
            raise TaskContractViolation("invalid task primary label")
        _validate_task_scope(
            self.external_boundary,
            self.approval,
            self.phase,
            initial=False,
        )
        predecessors = _tuple_texts(
            self.predecessor_task_ids,
            "predecessor task identifier",
            allow_empty=True,
            ordered=True,
        )
        successors = _tuple_texts(
            self.successor_task_ids,
            "successor task identifier",
            allow_empty=True,
            ordered=True,
        )
        if self.task_id in predecessors or self.task_id in successors:
            raise TaskContractViolation("task cannot link to itself")
        if self.primary_label == "active":
            if self.terminal_fact is not None or self.phase in {"accepted", "closed"}:
                raise TaskContractViolation("active task cannot carry a terminal fact")
        else:
            if type(self.terminal_fact) is not TaskTerminalFact:
                raise TaskContractViolation("terminal task requires a terminal fact")
            if self.terminal_fact.primary_label != self.primary_label:
                raise TaskContractViolation("task terminal fact label mismatch")
            expected_phase = "accepted" if self.primary_label == "solved" else "closed"
            if self.phase != expected_phase:
                raise TaskContractViolation("invalid terminal task phase")
            if self.primary_label == "solved":
                acceptance = self.terminal_fact.acceptance
                if type(acceptance) is not TaskAcceptance or (
                    acceptance.task_id != self.task_id
                    or acceptance.task_version >= self.version
                    or acceptance.task_semantic_digest != self.semantic_digest
                    or tuple(
                        proof.criterion
                        for proof in acceptance.criterion_proofs
                    )
                    != self.acceptance_criteria
                ):
                    raise TaskContractViolation(
                        "task terminal acceptance does not bind solved task"
                    )
        created = datetime.fromisoformat(_utc_time(self.created_at_utc, "task creation time"))
        updated = datetime.fromisoformat(_utc_time(self.updated_at_utc, "task update time"))
        if updated < created:
            raise TaskContractViolation("task update cannot precede creation")
        if self.terminal_fact is not None and datetime.fromisoformat(
            self.terminal_fact.recorded_at_utc
        ) > updated:
            raise TaskContractViolation("task terminal time exceeds task update time")
        expected_digest = _semantic_digest(
            purpose=self.purpose,
            expected_result=self.expected_result,
            assignee=self.assignee,
            allowed_data_categories=self.allowed_data_categories,
            allowed_data_refs=self.allowed_data_refs,
            external_boundary=self.external_boundary,
            acceptance_criteria=self.acceptance_criteria,
        )
        if self.semantic_digest != expected_digest:
            raise TaskContractViolation("task semantic digest mismatch")

    def to_storage(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "version": self.version,
            "purpose": self.purpose,
            "expected_result": self.expected_result,
            "assignee": self.assignee,
            "allowed_data_categories": list(self.allowed_data_categories),
            "allowed_data_refs": list(self.allowed_data_refs),
            "external_boundary": self.external_boundary.to_storage(),
            "approval": self.approval.to_storage(),
            "acceptance_criteria": list(self.acceptance_criteria),
            "source_kinds": list(self.source_kinds),
            "source_refs": list(self.source_refs),
            "source_revision_digests": list(self.source_revision_digests),
            "semantic_digest": self.semantic_digest,
            "primary_label": self.primary_label,
            "phase": self.phase,
            "predecessor_task_ids": list(self.predecessor_task_ids),
            "successor_task_ids": list(self.successor_task_ids),
            "terminal_fact": (
                None if self.terminal_fact is None else self.terminal_fact.to_storage()
            ),
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
        }

    @classmethod
    def from_storage(cls, value: object) -> "ManagedTask":
        stored = _mapping(
            value,
            frozenset(
                {
                    "task_id",
                    "version",
                    "purpose",
                    "expected_result",
                    "assignee",
                    "allowed_data_categories",
                    "allowed_data_refs",
                    "external_boundary",
                    "approval",
                    "acceptance_criteria",
                    "source_kinds",
                    "source_refs",
                    "source_revision_digests",
                    "semantic_digest",
                    "primary_label",
                    "phase",
                    "predecessor_task_ids",
                    "successor_task_ids",
                    "terminal_fact",
                    "created_at_utc",
                    "updated_at_utc",
                }
            ),
            "managed task",
        )
        revisions = stored["source_revision_digests"]
        if type(revisions) is not list or not revisions:
            raise TaskContractViolation("invalid task source revisions")
        source_kinds = stored["source_kinds"]
        if type(source_kinds) is not list or not source_kinds:
            raise TaskContractViolation("invalid task source kinds")
        terminal = stored["terminal_fact"]
        return cls(
            task_id=_text(stored["task_id"], "task identifier"),
            version=_positive_integer(stored["version"], "task version"),
            purpose=_text(stored["purpose"], "task purpose"),
            expected_result=_text(
                stored["expected_result"], "task expected result"
            ),
            assignee=_text(stored["assignee"], "task assignee"),
            allowed_data_categories=_wire_texts(
                stored["allowed_data_categories"], "allowed task data categories"
            ),
            allowed_data_refs=_wire_texts(
                stored["allowed_data_refs"], "allowed task data references"
            ),
            external_boundary=TaskExternalBoundary.from_storage(
                stored["external_boundary"]
            ),
            approval=TaskApprovalBinding.from_storage(stored["approval"]),
            acceptance_criteria=_wire_texts(
                stored["acceptance_criteria"], "task acceptance criteria"
            ),
            source_kinds=tuple(
                _text(item, "task source kind") for item in source_kinds
            ),
            source_refs=_wire_texts(
                stored["source_refs"], "task source reference", ordered=True
            ),
            source_revision_digests=tuple(
                _sha256(item, "task source revision") for item in revisions
            ),
            semantic_digest=_sha256(
                stored["semantic_digest"], "task semantic digest"
            ),
            primary_label=_text(stored["primary_label"], "task primary label"),
            phase=_text(stored["phase"], "task phase"),
            predecessor_task_ids=_wire_texts(
                stored["predecessor_task_ids"],
                "predecessor task identifier",
                allow_empty=True,
                ordered=True,
            ),
            successor_task_ids=_wire_texts(
                stored["successor_task_ids"],
                "successor task identifier",
                allow_empty=True,
                ordered=True,
            ),
            terminal_fact=(
                None if terminal is None else TaskTerminalFact.from_storage(terminal)
            ),
            created_at_utc=_utc_time(stored["created_at_utc"], "task creation time"),
            updated_at_utc=_utc_time(stored["updated_at_utc"], "task update time"),
        )


@dataclass(frozen=True)
class TaskAcceptanceCriterionProof:
    """Immutable evidence revisions proving one declared acceptance criterion."""

    criterion: str
    evidence_refs: tuple[str, ...]
    evidence_revision_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.criterion, "task acceptance criterion")
        refs = _tuple_texts(
            self.evidence_refs,
            "task acceptance evidence reference",
        )
        if type(self.evidence_revision_digests) is not tuple:
            raise TaskContractViolation(
                "invalid task acceptance evidence revisions"
            )
        revisions = tuple(
            _sha256(digest, "task acceptance evidence revision")
            for digest in self.evidence_revision_digests
        )
        if len(refs) != len(revisions):
            raise TaskContractViolation(
                "task acceptance evidence and revisions must align"
            )
        pairs = tuple(zip(refs, revisions))
        if pairs != tuple(sorted(pairs)):
            raise TaskContractViolation(
                "task acceptance evidence must be ordered"
            )

    def to_storage(self) -> dict[str, object]:
        return {
            "criterion": self.criterion,
            "evidence_refs": list(self.evidence_refs),
            "evidence_revision_digests": list(
                self.evidence_revision_digests
            ),
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskAcceptanceCriterionProof":
        stored = _mapping(
            value,
            frozenset(
                {
                    "criterion",
                    "evidence_refs",
                    "evidence_revision_digests",
                }
            ),
            "task acceptance criterion proof",
        )
        revisions = stored["evidence_revision_digests"]
        if type(revisions) is not list:
            raise TaskContractViolation(
                "invalid task acceptance evidence revisions"
            )
        return cls(
            criterion=_text(
                stored["criterion"], "task acceptance criterion"
            ),
            evidence_refs=_wire_texts(
                stored["evidence_refs"],
                "task acceptance evidence reference",
            ),
            evidence_revision_digests=tuple(
                _sha256(digest, "task acceptance evidence revision")
                for digest in revisions
            ),
        )


def _task_acceptance_result_digest(
    *,
    task_id: str,
    task_version: int,
    task_semantic_digest: str,
    criterion_proofs: tuple[TaskAcceptanceCriterionProof, ...],
    accepted_at_utc: str,
) -> str:
    return stable_digest(
        {
            "contract": "task-acceptance-v1",
            "task_id": task_id,
            "task_version": task_version,
            "task_semantic_digest": task_semantic_digest,
            "criterion_proofs": [
                proof.to_storage() for proof in criterion_proofs
            ],
            "accepted_at_utc": accepted_at_utc,
        }
    )


@dataclass(frozen=True)
class TaskAcceptance:
    """Exact, self-verifying proof for the current managed task revision."""

    task_id: str
    task_version: int
    task_semantic_digest: str
    criterion_proofs: tuple[TaskAcceptanceCriterionProof, ...]
    result_digest: str
    accepted_at_utc: str

    def __post_init__(self) -> None:
        task_id = _text(self.task_id, "task acceptance task identifier")
        task_version = _positive_integer(
            self.task_version, "task acceptance task version"
        )
        task_digest = _sha256(
            self.task_semantic_digest,
            "task acceptance semantic digest",
        )
        if type(self.criterion_proofs) is not tuple or not self.criterion_proofs:
            raise TaskContractViolation(
                "invalid task acceptance criterion proofs"
            )
        if any(
            type(proof) is not TaskAcceptanceCriterionProof
            for proof in self.criterion_proofs
        ):
            raise TaskContractViolation(
                "invalid task acceptance criterion proofs"
            )
        criteria = tuple(proof.criterion for proof in self.criterion_proofs)
        if len(criteria) != len(set(criteria)):
            raise TaskContractViolation(
                "task acceptance criteria must be unique"
            )
        accepted_at = _utc_time(
            self.accepted_at_utc, "task acceptance time"
        )
        result_digest = _sha256(
            self.result_digest, "task acceptance result digest"
        )
        if result_digest != _task_acceptance_result_digest(
            task_id=task_id,
            task_version=task_version,
            task_semantic_digest=task_digest,
            criterion_proofs=self.criterion_proofs,
            accepted_at_utc=accepted_at,
        ):
            raise TaskContractViolation(
                "task acceptance result digest mismatch"
            )

    @classmethod
    def prove(
        cls,
        task: ManagedTask,
        criterion_proofs: tuple[TaskAcceptanceCriterionProof, ...],
        *,
        accepted_at_utc: str,
    ) -> "TaskAcceptance":
        if type(task) is not ManagedTask:
            raise TaskContractViolation("invalid managed task acceptance target")
        if type(criterion_proofs) is not tuple or any(
            type(proof) is not TaskAcceptanceCriterionProof
            for proof in criterion_proofs
        ):
            raise TaskContractViolation(
                "invalid task acceptance criterion proofs"
            )
        if tuple(proof.criterion for proof in criterion_proofs) != (
            task.acceptance_criteria
        ):
            raise TaskContractViolation(
                "task acceptance proof does not cover exact current criteria"
            )
        accepted_at = _utc_time(accepted_at_utc, "task acceptance time")
        return cls(
            task_id=task.task_id,
            task_version=task.version,
            task_semantic_digest=task.semantic_digest,
            criterion_proofs=criterion_proofs,
            result_digest=_task_acceptance_result_digest(
                task_id=task.task_id,
                task_version=task.version,
                task_semantic_digest=task.semantic_digest,
                criterion_proofs=criterion_proofs,
                accepted_at_utc=accepted_at,
            ),
            accepted_at_utc=accepted_at,
        )

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    evidence_ref
                    for proof in self.criterion_proofs
                    for evidence_ref in proof.evidence_refs
                }
            )
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_version": self.task_version,
            "task_semantic_digest": self.task_semantic_digest,
            "criterion_proofs": [
                proof.to_storage() for proof in self.criterion_proofs
            ],
            "result_digest": self.result_digest,
            "accepted_at_utc": self.accepted_at_utc,
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskAcceptance":
        stored = _mapping(
            value,
            frozenset(
                {
                    "task_id",
                    "task_version",
                    "task_semantic_digest",
                    "criterion_proofs",
                    "result_digest",
                    "accepted_at_utc",
                }
            ),
            "task acceptance",
        )
        proofs = stored["criterion_proofs"]
        if type(proofs) is not list:
            raise TaskContractViolation(
                "invalid task acceptance criterion proofs"
            )
        return cls(
            task_id=_text(stored["task_id"], "task acceptance task identifier"),
            task_version=_positive_integer(
                stored["task_version"], "task acceptance task version"
            ),
            task_semantic_digest=_sha256(
                stored["task_semantic_digest"],
                "task acceptance semantic digest",
            ),
            criterion_proofs=tuple(
                TaskAcceptanceCriterionProof.from_storage(proof)
                for proof in proofs
            ),
            result_digest=_sha256(
                stored["result_digest"], "task acceptance result digest"
            ),
            accepted_at_utc=_utc_time(
                stored["accepted_at_utc"], "task acceptance time"
            ),
        )


@dataclass(frozen=True)
class TaskLease:
    """A task-work lease, distinct from an external-effect lease."""

    lease_id: str
    task_id: str
    holder_id: str
    acquired_at_utc: str
    expires_at_utc: str

    def __post_init__(self) -> None:
        _text(self.lease_id, "task lease identifier")
        _text(self.task_id, "task lease task identifier")
        _text(self.holder_id, "task lease holder")
        acquired = datetime.fromisoformat(
            _utc_time(self.acquired_at_utc, "task lease acquisition time")
        )
        expires = datetime.fromisoformat(
            _utc_time(self.expires_at_utc, "task lease expiry time")
        )
        if expires <= acquired:
            raise TaskContractViolation("task lease must expire after acquisition")

    def is_active(self, observed_at_utc: str) -> bool:
        observed = datetime.fromisoformat(
            _utc_time(observed_at_utc, "task lease observation time")
        )
        return observed < datetime.fromisoformat(self.expires_at_utc)

    def to_storage(self) -> dict[str, object]:
        return {
            "lease_id": self.lease_id,
            "task_id": self.task_id,
            "holder_id": self.holder_id,
            "acquired_at_utc": self.acquired_at_utc,
            "expires_at_utc": self.expires_at_utc,
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskLease":
        stored = _mapping(
            value,
            frozenset(
                {
                    "lease_id",
                    "task_id",
                    "holder_id",
                    "acquired_at_utc",
                    "expires_at_utc",
                }
            ),
            "task lease",
        )
        return cls(
            lease_id=_text(stored["lease_id"], "task lease identifier"),
            task_id=_text(stored["task_id"], "task lease task identifier"),
            holder_id=_text(stored["holder_id"], "task lease holder"),
            acquired_at_utc=_utc_time(
                stored["acquired_at_utc"], "task lease acquisition time"
            ),
            expires_at_utc=_utc_time(
                stored["expires_at_utc"], "task lease expiry time"
            ),
        )


@dataclass(frozen=True)
class TaskUnknownFact:
    """An external-result uncertainty attached to, but not replacing, a task."""

    unknown_id: str
    task_id: str
    effect_ref: str
    reason_code: str
    observed_at_utc: str
    possibly_external: bool
    resolution: str | None = None
    resolved_at_utc: str | None = None

    def __post_init__(self) -> None:
        _text(self.unknown_id, "task unknown identifier")
        _text(self.task_id, "task unknown task identifier")
        _text(self.effect_ref, "task unknown effect reference")
        _text(self.reason_code, "task unknown reason")
        _utc_time(self.observed_at_utc, "task unknown observation time")
        _boolean(self.possibly_external, "task unknown external-effect flag")
        if self.resolution is None:
            if self.resolved_at_utc is not None:
                raise TaskContractViolation("unresolved task unknown cannot have a resolution time")
        else:
            if self.resolution not in TASK_UNKNOWN_RESOLUTIONS:
                raise TaskContractViolation("invalid task unknown resolution")
            if self.resolved_at_utc is None:
                raise TaskContractViolation("resolved task unknown requires a resolution time")
            _utc_time(self.resolved_at_utc, "task unknown resolution time")

    @property
    def unresolved(self) -> bool:
        return self.resolution is None

    def to_storage(self) -> dict[str, object]:
        return {
            "unknown_id": self.unknown_id,
            "task_id": self.task_id,
            "effect_ref": self.effect_ref,
            "reason_code": self.reason_code,
            "observed_at_utc": self.observed_at_utc,
            "possibly_external": self.possibly_external,
            "resolution": self.resolution,
            "resolved_at_utc": self.resolved_at_utc,
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskUnknownFact":
        stored = _mapping(
            value,
            frozenset(
                {
                    "unknown_id",
                    "task_id",
                    "effect_ref",
                    "reason_code",
                    "observed_at_utc",
                    "possibly_external",
                    "resolution",
                    "resolved_at_utc",
                }
            ),
            "task unknown fact",
        )
        return cls(
            unknown_id=_text(stored["unknown_id"], "task unknown identifier"),
            task_id=_text(stored["task_id"], "task unknown task identifier"),
            effect_ref=_text(stored["effect_ref"], "task unknown effect reference"),
            reason_code=_text(stored["reason_code"], "task unknown reason"),
            observed_at_utc=_utc_time(
                stored["observed_at_utc"], "task unknown observation time"
            ),
            possibly_external=_boolean(
                stored["possibly_external"], "task unknown external-effect flag"
            ),
            resolution=_optional_text(
                stored["resolution"], "task unknown resolution"
            ),
            resolved_at_utc=(
                None
                if stored["resolved_at_utc"] is None
                else _utc_time(
                    stored["resolved_at_utc"], "task unknown resolution time"
                )
            ),
        )


@dataclass(frozen=True)
class TaskRuntimeState:
    owner_id: str
    installation_id: str
    version: int
    tasks: tuple[ManagedTask, ...]
    candidate_receipts: tuple[tuple[str, str, str], ...]
    unknown_facts: tuple[TaskUnknownFact, ...] = ()
    active_claims: tuple[TaskLease, ...] = ()

    def __post_init__(self) -> None:
        _text(self.owner_id, "task owner")
        _text(self.installation_id, "task installation")
        _nonnegative_integer(self.version, "task runtime version")
        if type(self.tasks) is not tuple or any(
            type(task) is not ManagedTask for task in self.tasks
        ):
            raise TaskContractViolation("invalid managed task collection")
        task_ids = tuple(task.task_id for task in self.tasks)
        if task_ids != tuple(sorted(task_ids)) or len(task_ids) != len(set(task_ids)):
            raise TaskContractViolation("tasks must be uniquely ordered")
        task_id_set = frozenset(task_ids)
        if type(self.candidate_receipts) is not tuple:
            raise TaskContractViolation("invalid task candidate receipts")
        receipt_ids: list[str] = []
        for receipt in self.candidate_receipts:
            if type(receipt) is not tuple or len(receipt) != 3:
                raise TaskContractViolation("invalid task candidate receipt")
            candidate_id, candidate_digest, task_id = receipt
            receipt_ids.append(_text(candidate_id, "task candidate identifier"))
            _sha256(candidate_digest, "task candidate digest")
            if _text(task_id, "task identifier") not in task_id_set:
                raise TaskContractViolation("task candidate receipt points outside state")
        if receipt_ids != sorted(receipt_ids) or len(receipt_ids) != len(set(receipt_ids)):
            raise TaskContractViolation("candidate receipts must be uniquely ordered")
        if type(self.unknown_facts) is not tuple or any(
            type(fact) is not TaskUnknownFact for fact in self.unknown_facts
        ):
            raise TaskContractViolation("invalid task unknown facts")
        unknown_ids = tuple(fact.unknown_id for fact in self.unknown_facts)
        if unknown_ids != tuple(sorted(unknown_ids)) or len(unknown_ids) != len(
            set(unknown_ids)
        ):
            raise TaskContractViolation("task unknown facts must be uniquely ordered")
        if any(fact.task_id not in task_id_set for fact in self.unknown_facts):
            raise TaskContractViolation("task unknown fact points outside state")
        if type(self.active_claims) is not tuple or any(
            type(claim) is not TaskLease for claim in self.active_claims
        ):
            raise TaskContractViolation("invalid task claims")
        lease_ids = tuple(claim.lease_id for claim in self.active_claims)
        claimed_tasks = tuple(claim.task_id for claim in self.active_claims)
        if lease_ids != tuple(sorted(lease_ids)) or len(lease_ids) != len(set(lease_ids)):
            raise TaskContractViolation("task claims must be uniquely ordered")
        if len(claimed_tasks) != len(set(claimed_tasks)):
            raise TaskContractViolation("task may have only one retained claim")
        if any(claim.task_id not in task_id_set for claim in self.active_claims):
            raise TaskContractViolation("task claim points outside state")
        if any(self.task(claim.task_id).primary_label != "active" for claim in self.active_claims):
            raise TaskContractViolation("terminal task cannot retain a claim")

    @classmethod
    def empty(cls, owner_id: str, installation_id: str) -> "TaskRuntimeState":
        return cls(
            owner_id=_text(owner_id, "task owner"),
            installation_id=_text(installation_id, "task installation"),
            version=0,
            tasks=(),
            candidate_receipts=(),
            unknown_facts=(),
            active_claims=(),
        )

    def task(self, task_id: str) -> ManagedTask:
        parsed = _text(task_id, "task identifier")
        for task in self.tasks:
            if task.task_id == parsed:
                return task
        raise TaskContractViolation("task does not exist")

    @property
    def delivery_unknown_refs(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                fact.effect_ref for fact in self.unknown_facts if fact.unresolved
            )
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "version": self.version,
            "tasks": [task.to_storage() for task in self.tasks],
            "candidate_receipts": [list(receipt) for receipt in self.candidate_receipts],
            "unknown_facts": [fact.to_storage() for fact in self.unknown_facts],
            "active_claims": [claim.to_storage() for claim in self.active_claims],
        }

    @classmethod
    def from_storage(cls, value: object) -> "TaskRuntimeState":
        stored = _mapping(
            value,
            frozenset(
                {
                    "owner_id",
                    "installation_id",
                    "version",
                    "tasks",
                    "candidate_receipts",
                    "unknown_facts",
                    "active_claims",
                }
            ),
            "task runtime state",
        )
        raw_tasks = stored["tasks"]
        raw_receipts = stored["candidate_receipts"]
        raw_unknowns = stored["unknown_facts"]
        raw_claims = stored["active_claims"]
        if any(type(value) is not list for value in (raw_tasks, raw_receipts, raw_unknowns, raw_claims)):
            raise TaskContractViolation("invalid task runtime collection")
        receipts: list[tuple[str, str, str]] = []
        for receipt in raw_receipts:
            if type(receipt) is not list or len(receipt) != 3:
                raise TaskContractViolation("invalid task candidate receipt")
            receipts.append(
                (
                    _text(receipt[0], "task candidate identifier"),
                    _sha256(receipt[1], "task candidate digest"),
                    _text(receipt[2], "task identifier"),
                )
            )
        return cls(
            owner_id=_text(stored["owner_id"], "task owner"),
            installation_id=_text(
                stored["installation_id"], "task installation"
            ),
            version=_nonnegative_integer(stored["version"], "task runtime version"),
            tasks=tuple(ManagedTask.from_storage(item) for item in raw_tasks),
            candidate_receipts=tuple(receipts),
            unknown_facts=tuple(
                TaskUnknownFact.from_storage(item) for item in raw_unknowns
            ),
            active_claims=tuple(TaskLease.from_storage(item) for item in raw_claims),
        )


@dataclass(frozen=True)
class TaskTransition:
    state: TaskRuntimeState
    task_id: str
    outcome: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if type(self.state) is not TaskRuntimeState:
            raise TaskContractViolation("invalid task transition state")
        _text(self.task_id, "task transition task identifier")
        _text(self.outcome, "task transition outcome")
        _boolean(self.replayed, "task transition replay flag")


def _candidate_receipt_digest(candidate: TaskCandidate) -> str:
    return stable_digest(candidate.to_storage())


def _replace_task(state: TaskRuntimeState, task: ManagedTask) -> tuple[ManagedTask, ...]:
    return tuple(
        sorted(
            (task if item.task_id == task.task_id else item for item in state.tasks),
            key=lambda item: item.task_id,
        )
    )


def _unresolved_unknowns(state: TaskRuntimeState, task_id: str) -> tuple[TaskUnknownFact, ...]:
    return tuple(
        fact
        for fact in state.unknown_facts
        if fact.task_id == task_id and fact.unresolved
    )


class TaskEngine:
    """The sole authority that turns proposals into managed task facts."""

    @staticmethod
    def admit_candidate(
        state: TaskRuntimeState,
        candidate: TaskCandidate,
        *,
        committed_at_utc: str,
        cancelled_task_refs: tuple[str, ...] = (),
    ) -> TaskTransition:
        return TaskEngine._admit_candidate(
            state,
            candidate,
            committed_at_utc=committed_at_utc,
            explicit_predecessor_id=None,
            cancelled_task_refs=cancelled_task_refs,
        )

    @staticmethod
    def _admit_candidate(
        state: TaskRuntimeState,
        candidate: TaskCandidate,
        *,
        committed_at_utc: str,
        explicit_predecessor_id: str | None,
        cancelled_task_refs: tuple[str, ...] = (),
    ) -> TaskTransition:
        if type(state) is not TaskRuntimeState:
            raise TaskContractViolation("invalid task runtime state")
        if type(candidate) is not TaskCandidate:
            raise TaskContractViolation("invalid task candidate")
        committed_at = _utc_time(committed_at_utc, "task commit time")
        candidate_digest = _candidate_receipt_digest(candidate)
        for receipt_id, receipt_digest, task_id in state.candidate_receipts:
            if receipt_id != candidate.candidate_id:
                continue
            if receipt_digest != candidate_digest:
                raise TaskContractViolation(
                    "task candidate identifier was already used for another proposal"
                )
            return TaskTransition(state, task_id, "replayed", True)

        for task in state.tasks:
            if task.semantic_digest != candidate.semantic_digest:
                continue
            if task.primary_label != "active":
                if task.task_id != explicit_predecessor_id:
                    raise TaskContractViolation(
                        "terminal task requires an explicit linked successor"
                    )
                continue
            source_bindings = {
                source_ref: (source_kind, source_revision_digest)
                for source_kind, source_ref, source_revision_digest in zip(
                    task.source_kinds,
                    task.source_refs,
                    task.source_revision_digests,
                )
            }
            candidate_binding = (
                candidate.source_kind,
                candidate.source_revision_digest,
            )
            existing_binding = source_bindings.get(candidate.source_ref)
            if existing_binding is not None and existing_binding != candidate_binding:
                raise TaskContractViolation(
                    "task source reference changed its authoritative binding"
                )
            source_bindings[candidate.source_ref] = candidate_binding
            ordered_bindings = tuple(sorted(source_bindings.items()))
            merged = replace(
                task,
                version=task.version + 1,
                source_kinds=tuple(item[1][0] for item in ordered_bindings),
                source_refs=tuple(item[0] for item in ordered_bindings),
                source_revision_digests=tuple(
                    item[1][1] for item in ordered_bindings
                ),
                updated_at_utc=committed_at,
            )
            receipt = (candidate.candidate_id, candidate_digest, task.task_id)
            next_state = replace(
                state,
                version=state.version + 1,
                tasks=_replace_task(state, merged),
                candidate_receipts=tuple(
                    sorted(state.candidate_receipts + (receipt,))
                ),
            )
            return TaskTransition(
                next_state,
                task.task_id,
                "duplicate-active-task",
            )

        ordinal = 1 + sum(
            task.semantic_digest == candidate.semantic_digest for task in state.tasks
        )
        task_id = (
            "task:"
            + candidate.semantic_digest.removeprefix("sha256:")[:32]
            + f":{ordinal}"
        )
        if task_id in cancelled_task_refs:
            raise TaskContractViolation("task admission was cancelled by owner")
        task = ManagedTask(
            task_id=task_id,
            version=1,
            purpose=candidate.purpose,
            expected_result=candidate.expected_result,
            assignee=candidate.assignee,
            allowed_data_categories=candidate.allowed_data_categories,
            allowed_data_refs=candidate.allowed_data_refs,
            external_boundary=candidate.external_boundary,
            approval=candidate.approval,
            acceptance_criteria=candidate.acceptance_criteria,
            source_kinds=(candidate.source_kind,),
            source_refs=(candidate.source_ref,),
            source_revision_digests=(candidate.source_revision_digest,),
            semantic_digest=candidate.semantic_digest,
            primary_label="active",
            phase=candidate.phase,
            predecessor_task_ids=(),
            successor_task_ids=(),
            terminal_fact=None,
            created_at_utc=committed_at,
            updated_at_utc=committed_at,
        )
        receipt = (candidate.candidate_id, candidate_digest, task_id)
        next_state = replace(
            state,
            version=state.version + 1,
            tasks=tuple(sorted(state.tasks + (task,), key=lambda item: item.task_id)),
            candidate_receipts=tuple(sorted(state.candidate_receipts + (receipt,))),
        )
        return TaskTransition(next_state, task_id, "created")

    @staticmethod
    def claim(
        state: TaskRuntimeState,
        task_id: str,
        *,
        holder_id: str,
        lease_id: str,
        acquired_at_utc: str,
        lease_seconds: int = 300,
    ) -> TaskTransition:
        if type(state) is not TaskRuntimeState:
            raise TaskContractViolation("invalid task runtime state")
        task = state.task(task_id)
        if task.primary_label != "active":
            raise TaskContractViolation("only active tasks can be claimed")
        if task.phase not in {"planned", "in-progress"}:
            raise TaskContractViolation("task is not ready for a work claim")
        holder = _text(holder_id, "task lease holder")
        lease_identifier = _text(lease_id, "task lease identifier")
        duration = _positive_integer(lease_seconds, "task lease duration")
        acquired_text = _utc_time(acquired_at_utc, "task lease acquisition time")
        acquired = datetime.fromisoformat(acquired_text)
        expiry = (acquired + timedelta(seconds=duration)).isoformat()
        for existing in state.active_claims:
            if existing.lease_id != lease_identifier:
                continue
            if (
                existing.task_id == task.task_id
                and existing.holder_id == holder
                and existing.acquired_at_utc == acquired_text
                and existing.expires_at_utc == expiry
            ):
                return TaskTransition(state, task.task_id, "claimed", True)
            raise TaskContractViolation("task lease identifier was reused")
        active = tuple(
            claim for claim in state.active_claims if claim.is_active(acquired_text)
        )
        if any(claim.task_id == task.task_id for claim in active):
            raise TaskContractViolation("task already has an active claim")
        taken_over = any(
            claim.task_id == task.task_id and not claim.is_active(acquired_text)
            for claim in state.active_claims
        )
        lease = TaskLease(
            lease_id=lease_identifier,
            task_id=task.task_id,
            holder_id=holder,
            acquired_at_utc=acquired_text,
            expires_at_utc=expiry,
        )
        next_task = replace(
            task,
            phase="in-progress",
            version=task.version + 1,
            updated_at_utc=acquired_text,
        )
        next_state = replace(
            state,
            version=state.version + 1,
            tasks=_replace_task(state, next_task),
            active_claims=tuple(
                sorted(active + (lease,), key=lambda item: item.lease_id)
            ),
        )
        return TaskTransition(
            next_state,
            task.task_id,
            "claim-taken-over" if taken_over else "claimed",
        )

    @staticmethod
    def release_claim(
        state: TaskRuntimeState,
        lease_id: str,
        *,
        holder_id: str,
        observed_at_utc: str,
    ) -> TaskTransition:
        if type(state) is not TaskRuntimeState:
            raise TaskContractViolation("invalid task runtime state")
        lease_identifier = _text(lease_id, "task lease identifier")
        holder = _text(holder_id, "task lease holder")
        observed = _utc_time(observed_at_utc, "task lease release time")
        lease = next(
            (item for item in state.active_claims if item.lease_id == lease_identifier),
            None,
        )
        if lease is None:
            raise TaskContractViolation("task lease does not exist")
        if lease.holder_id != holder:
            raise TaskContractViolation("task lease holder mismatch")
        task = state.task(lease.task_id)
        if task.primary_label != "active":
            raise TaskContractViolation("terminal task cannot release a claim")
        next_task = replace(
            task,
            phase="planned",
            version=task.version + 1,
            updated_at_utc=observed,
        )
        next_state = replace(
            state,
            version=state.version + 1,
            tasks=_replace_task(state, next_task),
            active_claims=tuple(
                item for item in state.active_claims if item.lease_id != lease_identifier
            ),
        )
        return TaskTransition(next_state, task.task_id, "released")

    @staticmethod
    def advance_phase(
        state: TaskRuntimeState,
        task_id: str,
        *,
        phase: str,
        advanced_at_utc: str,
    ) -> TaskTransition:
        task = state.task(task_id)
        if task.primary_label != "active":
            raise TaskContractViolation("terminal task cannot be advanced")
        if type(phase) is not str or phase not in TASK_PHASES or phase in {
            "accepted",
            "closed",
        }:
            raise TaskContractViolation("invalid active task phase")
        at = _utc_time(advanced_at_utc, "task phase time")
        if phase == task.phase:
            return TaskTransition(state, task.task_id, "phase-unchanged", True)
        next_task = replace(
            task,
            phase=phase,
            version=task.version + 1,
            updated_at_utc=at,
        )
        return TaskTransition(
            replace(
                state,
                version=state.version + 1,
                tasks=_replace_task(state, next_task),
            ),
            task.task_id,
            "phase-advanced",
        )

    @staticmethod
    def solve(
        state: TaskRuntimeState,
        acceptance: TaskAcceptance,
        *,
        current_evidence_revisions: Mapping[str, str],
    ) -> TaskTransition:
        if type(acceptance) is not TaskAcceptance:
            raise TaskContractViolation("invalid task acceptance")
        if not isinstance(current_evidence_revisions, Mapping):
            raise TaskContractViolation("invalid current evidence revisions")
        current_revisions = {
            _text(ref, "current evidence reference"): _sha256(
                digest,
                "current evidence revision",
            )
            for ref, digest in current_evidence_revisions.items()
        }
        task = state.task(acceptance.task_id)
        if task.primary_label != "active":
            raise TaskContractViolation("terminal task cannot be solved again")
        if acceptance.task_version != task.version:
            raise TaskContractViolation(
                "task acceptance does not bind the current task version"
            )
        if acceptance.task_semantic_digest != task.semantic_digest:
            raise TaskContractViolation(
                "task acceptance does not bind the current task semantics"
            )
        if tuple(
            proof.criterion for proof in acceptance.criterion_proofs
        ) != task.acceptance_criteria:
            raise TaskContractViolation(
                "task acceptance does not prove the current criteria"
            )
        if any(
            current_revisions.get(ref) != digest
            for proof in acceptance.criterion_proofs
            for ref, digest in zip(
                proof.evidence_refs,
                proof.evidence_revision_digests,
            )
        ):
            raise TaskContractViolation(
                "task acceptance does not match a current evidence revision"
            )
        if datetime.fromisoformat(acceptance.accepted_at_utc) < datetime.fromisoformat(
            task.updated_at_utc
        ):
            raise TaskContractViolation(
                "task acceptance evidence predates the current task revision"
            )
        if any(claim.task_id == task.task_id for claim in state.active_claims):
            raise TaskContractViolation("release task claim before acceptance")
        if _unresolved_unknowns(state, task.task_id):
            raise TaskContractViolation("delivery unknown cannot be rewritten as solved")
        terminal = TaskTerminalFact(
            primary_label="solved",
            reason_code="acceptance-proved",
            evidence_refs=acceptance.evidence_refs,
            result_digest=acceptance.result_digest,
            recorded_at_utc=acceptance.accepted_at_utc,
            acceptance=acceptance,
        )
        next_task = replace(
            task,
            primary_label="solved",
            phase="accepted",
            terminal_fact=terminal,
            version=task.version + 1,
            updated_at_utc=acceptance.accepted_at_utc,
        )
        return TaskTransition(
            replace(
                state,
                version=state.version + 1,
                tasks=_replace_task(state, next_task),
            ),
            task.task_id,
            "solved",
        )

    @staticmethod
    def cancel(
        state: TaskRuntimeState,
        task_id: str,
        *,
        cancelled_at_utc: str,
        reason_code: str = "task-cancelled",
    ) -> TaskTransition:
        task = state.task(task_id)
        if task.primary_label != "active":
            raise TaskContractViolation("terminal task cannot be cancelled again")
        at = _utc_time(cancelled_at_utc, "task cancellation time")
        terminal = TaskTerminalFact(
            primary_label="cancelled",
            reason_code=_text(reason_code, "task cancellation reason"),
            evidence_refs=(),
            result_digest=None,
            recorded_at_utc=at,
        )
        next_task = replace(
            task,
            primary_label="cancelled",
            phase="closed",
            terminal_fact=terminal,
            version=task.version + 1,
            updated_at_utc=at,
        )
        return TaskTransition(
            replace(
                state,
                version=state.version + 1,
                tasks=_replace_task(state, next_task),
                active_claims=tuple(
                    item for item in state.active_claims if item.task_id != task.task_id
                ),
            ),
            task.task_id,
            "cancelled",
        )

    @staticmethod
    def apply_owner_cancellation(
        state: TaskRuntimeState,
        task_id: str,
        *,
        control_ref: str,
        effective_at_utc: str,
    ) -> TaskTransition:
        """Apply an owner task-control fact without rewriting prior terminals."""

        if type(state) is not TaskRuntimeState:
            raise TaskContractViolation("invalid task runtime state")
        _text(control_ref, "owner task cancellation control reference")
        task = state.task(task_id)
        if task.primary_label == "active":
            cancelled = TaskEngine.cancel(
                state,
                task.task_id,
                cancelled_at_utc=effective_at_utc,
                reason_code="owner-task-cancelled",
            )
            return TaskTransition(
                cancelled.state,
                cancelled.task_id,
                "owner-cancelled",
            )
        if task.primary_label == "cancelled":
            return TaskTransition(state, task.task_id, "owner-cancelled", True)
        return TaskTransition(
            state,
            task.task_id,
            "owner-cancel-terminal-preserved",
        )

    @staticmethod
    def fail(
        state: TaskRuntimeState,
        task_id: str,
        *,
        failed_at_utc: str,
        reason_code: str = "no-reasonable-path",
    ) -> TaskTransition:
        task = state.task(task_id)
        if task.primary_label != "active":
            raise TaskContractViolation("terminal task cannot be failed again")
        if _unresolved_unknowns(state, task.task_id):
            raise TaskContractViolation("delivery unknown cannot be rewritten as failed")
        at = _utc_time(failed_at_utc, "task failure time")
        terminal = TaskTerminalFact(
            primary_label="failed",
            reason_code=_text(reason_code, "task failure reason"),
            evidence_refs=(),
            result_digest=None,
            recorded_at_utc=at,
        )
        next_task = replace(
            task,
            primary_label="failed",
            phase="closed",
            terminal_fact=terminal,
            version=task.version + 1,
            updated_at_utc=at,
        )
        return TaskTransition(
            replace(
                state,
                version=state.version + 1,
                tasks=_replace_task(state, next_task),
                active_claims=tuple(
                    item for item in state.active_claims if item.task_id != task.task_id
                ),
            ),
            task.task_id,
            "failed",
        )

    @staticmethod
    def mark_delivery_unknown(
        state: TaskRuntimeState,
        task_id: str,
        *,
        effect_ref: str,
        reason_code: str = "delivery-result-unknown",
        observed_at_utc: str,
        possibly_external: bool = True,
    ) -> TaskTransition:
        task = state.task(task_id)
        if task.primary_label != "active":
            raise TaskContractViolation("delivery unknown requires an active task")
        effect = _text(effect_ref, "task delivery effect reference")
        reason = _text(reason_code, "task delivery unknown reason")
        observed = _utc_time(observed_at_utc, "task delivery unknown time")
        _boolean(possibly_external, "task delivery unknown external flag")
        for fact in state.unknown_facts:
            if fact.effect_ref != effect:
                continue
            if (
                fact.task_id == task.task_id
                and fact.reason_code == reason
                and fact.possibly_external == possibly_external
            ):
                return TaskTransition(state, task.task_id, "delivery-unknown", True)
            raise TaskContractViolation("delivery effect reference has conflicting unknown fact")
        unknown_id = "unknown:" + stable_digest(
            {"task_id": task.task_id, "effect_ref": effect}
        ).removeprefix("sha256:")
        fact = TaskUnknownFact(
            unknown_id=unknown_id,
            task_id=task.task_id,
            effect_ref=effect,
            reason_code=reason,
            observed_at_utc=observed,
            possibly_external=possibly_external,
        )
        next_task = replace(
            task,
            phase="awaiting-result",
            version=task.version + 1,
            updated_at_utc=observed,
        )
        next_state = replace(
            state,
            version=state.version + 1,
            tasks=_replace_task(state, next_task),
            unknown_facts=tuple(
                sorted(state.unknown_facts + (fact,), key=lambda item: item.unknown_id)
            ),
            active_claims=tuple(
                item for item in state.active_claims if item.task_id != task.task_id
            ),
        )
        return TaskTransition(next_state, task.task_id, "delivery-unknown")

    @staticmethod
    def resolve_delivery_unknown(
        state: TaskRuntimeState,
        effect_ref: str,
        *,
        resolution: str,
        resolved_at_utc: str,
    ) -> TaskTransition:
        effect = _text(effect_ref, "task delivery effect reference")
        if type(resolution) is not str or resolution not in TASK_UNKNOWN_RESOLUTIONS:
            raise TaskContractViolation("invalid task unknown resolution")
        at = _utc_time(resolved_at_utc, "task delivery resolution time")
        fact = next((item for item in state.unknown_facts if item.effect_ref == effect), None)
        if fact is None:
            raise TaskContractViolation("task delivery unknown does not exist")
        if not fact.unresolved:
            if fact.resolution == resolution and fact.resolved_at_utc == at:
                return TaskTransition(state, fact.task_id, "delivery-unknown-resolved", True)
            raise TaskContractViolation("task delivery unknown was already resolved")
        resolved = replace(fact, resolution=resolution, resolved_at_utc=at)
        task = state.task(fact.task_id)
        next_task = task
        still_unresolved = any(
            item.task_id == task.task_id
            and item.unknown_id != fact.unknown_id
            and item.unresolved
            for item in state.unknown_facts
        )
        if (
            task.primary_label == "active"
            and task.phase == "awaiting-result"
            and not still_unresolved
        ):
            next_task = replace(
                task,
                phase="planned",
                version=task.version + 1,
                updated_at_utc=at,
            )
        next_state = replace(
            state,
            version=state.version + 1,
            tasks=_replace_task(state, next_task),
            unknown_facts=tuple(
                sorted(
                    (
                        resolved if item.unknown_id == fact.unknown_id else item
                        for item in state.unknown_facts
                    ),
                    key=lambda item: item.unknown_id,
                )
            ),
        )
        return TaskTransition(next_state, fact.task_id, "delivery-unknown-resolved")

    @staticmethod
    def link_successor(
        state: TaskRuntimeState,
        predecessor_task_id: str,
        successor_candidate: TaskCandidate,
        *,
        committed_at_utc: str,
        cancelled_task_refs: tuple[str, ...] = (),
    ) -> TaskTransition:
        predecessor = state.task(predecessor_task_id)
        at = _utc_time(committed_at_utc, "task successor commit time")
        transition = TaskEngine._admit_candidate(
            state,
            successor_candidate,
            committed_at_utc=at,
            explicit_predecessor_id=predecessor.task_id,
            cancelled_task_refs=cancelled_task_refs,
        )
        successor = transition.state.task(transition.task_id)
        if successor.task_id == predecessor.task_id:
            raise TaskContractViolation("task cannot be its own successor")
        if transition.replayed:
            if (
                successor.task_id in predecessor.successor_task_ids
                and predecessor.task_id in successor.predecessor_task_ids
            ):
                return transition
            raise TaskContractViolation("replayed successor is missing its atomic link")
        predecessor = replace(
            predecessor,
            version=predecessor.version + 1,
            successor_task_ids=tuple(
                sorted(set(predecessor.successor_task_ids + (successor.task_id,)))
            ),
            updated_at_utc=at,
        )
        successor = replace(
            successor,
            version=successor.version + 1,
            predecessor_task_ids=tuple(
                sorted(set(successor.predecessor_task_ids + (predecessor.task_id,)))
            ),
            updated_at_utc=at,
        )
        linked_tasks = tuple(
            sorted(
                (
                    predecessor
                    if item.task_id == predecessor.task_id
                    else successor
                    if item.task_id == successor.task_id
                    else item
                    for item in transition.state.tasks
                ),
                key=lambda item: item.task_id,
            )
        )
        outcome = (
            "successor-created"
            if transition.outcome == "created"
            else "successor-linked"
        )
        return TaskTransition(
            replace(transition.state, tasks=linked_tasks),
            successor.task_id,
            outcome,
        )


__all__ = [
    "TASK_APPROVAL_STATUSES",
    "TASK_INITIAL_PHASES",
    "TASK_PHASES",
    "TASK_PRIMARY_LABELS",
    "TASK_SOURCE_KINDS",
    "TASK_UNKNOWN_RESOLUTIONS",
    "ManagedTask",
    "TaskAcceptance",
    "TaskAcceptanceCriterionProof",
    "TaskApprovalBinding",
    "TaskCandidate",
    "TaskContractViolation",
    "TaskEngine",
    "TaskExternalBoundary",
    "TaskLease",
    "TaskRuntimeState",
    "TaskTerminalFact",
    "TaskTransition",
    "TaskUnknownFact",
]

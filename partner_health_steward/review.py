"""Owner-local-day review ledger and crash recovery rules for Ticket 115."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .initialization import stable_digest


class ReviewContractViolation(ValueError):
    """A local-day review value is not valid."""


def _mapping(value: object, fields: frozenset[str], name: str) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != fields:
        raise ReviewContractViolation(f"invalid {name}")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ReviewContractViolation(f"invalid {name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ReviewContractViolation(f"invalid {name}") from exc
    if len(encoded) > 65_536:
        raise ReviewContractViolation(f"invalid {name}")
    return value


def _sha256(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise ReviewContractViolation(f"invalid {name}")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise ReviewContractViolation(f"invalid {name}") from exc
    return text


def _nonnegative_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ReviewContractViolation(f"invalid {name}")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ReviewContractViolation(f"invalid {name}")
    return value


def _tuple_texts(
    value: object,
    name: str,
    *,
    ordered: bool = False,
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise ReviewContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if result != value or len(result) != len(set(result)):
        raise ReviewContractViolation(f"invalid {name}")
    if ordered and result != tuple(sorted(result)):
        raise ReviewContractViolation(f"invalid {name} order")
    return result


def _wire_texts(
    value: object,
    name: str,
    *,
    ordered: bool = False,
) -> tuple[str, ...]:
    if type(value) is not list:
        raise ReviewContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise ReviewContractViolation(f"invalid {name}")
    if ordered and result != tuple(sorted(result)):
        raise ReviewContractViolation(f"invalid {name} order")
    return result


def _utc(value: object, name: str) -> str:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReviewContractViolation(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ReviewContractViolation(f"invalid {name}")
    return text


def _timezone(name: object) -> str:
    text = _text(name, "review timezone")
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError as exc:
        try:
            from dateutil.tz import gettz  # type: ignore[import-not-found]
        except ImportError:
            if text not in {"UTC", "Etc/UTC", "Asia/Shanghai"}:
                raise ReviewContractViolation("unknown review timezone") from exc
        else:
            if gettz(text) is None:
                raise ReviewContractViolation("unknown review timezone") from exc
    return text


def _zone(name: str):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        try:
            from dateutil.tz import gettz  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - validation already ran
            raise ReviewContractViolation("unknown review timezone") from exc
        zone = gettz(name)
        if zone is None:  # pragma: no cover - validation already ran
            raise ReviewContractViolation("unknown review timezone")
        return zone


@dataclass(frozen=True, order=True)
class LocalDayKey:
    """Stable business identity: owner + installation + timezone + local date."""

    owner_id: str
    installation_id: str
    timezone: str
    local_date: str

    def __post_init__(self) -> None:
        _text(self.owner_id, "review owner")
        _text(self.installation_id, "review installation")
        _timezone(self.timezone)
        try:
            parsed = date.fromisoformat(_text(self.local_date, "review local date"))
        except ValueError as exc:
            raise ReviewContractViolation("invalid review local date") from exc
        if parsed.isoformat() != self.local_date:
            raise ReviewContractViolation("invalid review local date")

    @property
    def value(self) -> str:
        return (
            f"{self.owner_id}:{self.installation_id}:"
            f"{self.timezone}:{self.local_date}"
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_storage())

    def to_storage(self) -> dict[str, object]:
        return {
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "timezone": self.timezone,
            "local_date": self.local_date,
        }

    @classmethod
    def from_storage(cls, value: object) -> "LocalDayKey":
        stored = _mapping(
            value,
            frozenset({"owner_id", "installation_id", "timezone", "local_date"}),
            "local-day review key",
        )
        return cls(
            owner_id=_text(stored["owner_id"], "review owner"),
            installation_id=_text(
                stored["installation_id"], "review installation"
            ),
            timezone=_timezone(stored["timezone"]),
            local_date=_text(stored["local_date"], "review local date"),
        )


def local_day_key(
    owner_id: str,
    installation_id: str,
    timezone_name: str,
    observed_at_utc: str | datetime,
) -> LocalDayKey:
    """Compute the current owner-local natural day, including DST folds."""

    normalized_timezone = _timezone(timezone_name)
    if isinstance(observed_at_utc, datetime):
        observed = observed_at_utc
        if observed.tzinfo is None or observed.utcoffset() != timedelta(0):
            raise ReviewContractViolation("review observation must be UTC")
    else:
        observed = datetime.fromisoformat(
            _utc(observed_at_utc, "review observation time")
        )
    local = observed.astimezone(_zone(normalized_timezone))
    return LocalDayKey(
        owner_id=_text(owner_id, "review owner"),
        installation_id=_text(installation_id, "review installation"),
        timezone=normalized_timezone,
        local_date=local.date().isoformat(),
    )


def _pending_digest(
    key: LocalDayKey,
    state_digest: str,
    changed: bool,
    action_refs: tuple[str, ...],
    prepared_at_utc: str,
) -> str:
    return stable_digest(
        {
            "key": key.to_storage(),
            "state_digest": state_digest,
            "changed": changed,
            "action_refs": list(action_refs),
            "prepared_at_utc": prepared_at_utc,
        }
    )


@dataclass(frozen=True)
class DailyReviewPending:
    """Durable prepare fact for exactly one current owner-local day."""

    key: LocalDayKey
    state_digest: str
    changed: bool
    action_refs: tuple[str, ...]
    prepared_at_utc: str
    prepare_digest: str

    def __post_init__(self) -> None:
        if type(self.key) is not LocalDayKey:
            raise ReviewContractViolation("invalid pending review key")
        _sha256(self.state_digest, "pending review state digest")
        _boolean(self.changed, "pending review changed flag")
        _tuple_texts(
            self.action_refs,
            "pending review action reference",
            ordered=True,
        )
        _utc(self.prepared_at_utc, "pending review prepare time")
        _sha256(self.prepare_digest, "pending review digest")
        if self.prepare_digest != _pending_digest(
            self.key,
            self.state_digest,
            self.changed,
            self.action_refs,
            self.prepared_at_utc,
        ):
            raise ReviewContractViolation("pending review digest mismatch")

    @property
    def notification_required(self) -> bool:
        return self.changed and bool(self.action_refs)

    def to_storage(self) -> dict[str, object]:
        return {
            "key": self.key.to_storage(),
            "state_digest": self.state_digest,
            "changed": self.changed,
            "action_refs": list(self.action_refs),
            "prepared_at_utc": self.prepared_at_utc,
            "prepare_digest": self.prepare_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "DailyReviewPending":
        stored = _mapping(
            value,
            frozenset(
                {
                    "key",
                    "state_digest",
                    "changed",
                    "action_refs",
                    "prepared_at_utc",
                    "prepare_digest",
                }
            ),
            "pending daily review",
        )
        return cls(
            key=LocalDayKey.from_storage(stored["key"]),
            state_digest=_sha256(
                stored["state_digest"], "pending review state digest"
            ),
            changed=_boolean(stored["changed"], "pending review changed flag"),
            action_refs=_wire_texts(
                stored["action_refs"],
                "pending review action reference",
                ordered=True,
            ),
            prepared_at_utc=_utc(
                stored["prepared_at_utc"], "pending review prepare time"
            ),
            prepare_digest=_sha256(
                stored["prepare_digest"], "pending review digest"
            ),
        )


def _review_result_digest(
    pending: DailyReviewPending,
    completed_at_utc: str,
) -> str:
    return stable_digest(
        {
            "prepare_digest": pending.prepare_digest,
            "completed_at_utc": completed_at_utc,
        }
    )


@dataclass(frozen=True)
class DailyReviewRecord:
    key: LocalDayKey
    state_digest: str
    changed: bool
    action_refs: tuple[str, ...]
    prepared_at_utc: str
    completed_at_utc: str
    prepare_digest: str
    result_digest: str
    notification_required: bool

    def __post_init__(self) -> None:
        if type(self.key) is not LocalDayKey:
            raise ReviewContractViolation("invalid review key")
        _sha256(self.state_digest, "review state digest")
        _boolean(self.changed, "review changed flag")
        _tuple_texts(
            self.action_refs,
            "review action reference",
            ordered=True,
        )
        prepared = datetime.fromisoformat(
            _utc(self.prepared_at_utc, "review prepare time")
        )
        completed = datetime.fromisoformat(
            _utc(self.completed_at_utc, "review completion time")
        )
        if completed < prepared:
            raise ReviewContractViolation("review completion cannot precede prepare")
        _sha256(self.prepare_digest, "review prepare digest")
        _sha256(self.result_digest, "review result digest")
        _boolean(self.notification_required, "review notification flag")
        pending = DailyReviewPending(
            key=self.key,
            state_digest=self.state_digest,
            changed=self.changed,
            action_refs=self.action_refs,
            prepared_at_utc=self.prepared_at_utc,
            prepare_digest=self.prepare_digest,
        )
        if self.result_digest != _review_result_digest(pending, self.completed_at_utc):
            raise ReviewContractViolation("review result digest mismatch")
        if self.notification_required != pending.notification_required:
            raise ReviewContractViolation("review notification does not match result")

    def to_storage(self) -> dict[str, object]:
        return {
            "key": self.key.to_storage(),
            "state_digest": self.state_digest,
            "changed": self.changed,
            "action_refs": list(self.action_refs),
            "prepared_at_utc": self.prepared_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "prepare_digest": self.prepare_digest,
            "result_digest": self.result_digest,
            "notification_required": self.notification_required,
        }

    @classmethod
    def from_storage(cls, value: object) -> "DailyReviewRecord":
        stored = _mapping(
            value,
            frozenset(
                {
                    "key",
                    "state_digest",
                    "changed",
                    "action_refs",
                    "prepared_at_utc",
                    "completed_at_utc",
                    "prepare_digest",
                    "result_digest",
                    "notification_required",
                }
            ),
            "daily review record",
        )
        return cls(
            key=LocalDayKey.from_storage(stored["key"]),
            state_digest=_sha256(stored["state_digest"], "review state digest"),
            changed=_boolean(stored["changed"], "review changed flag"),
            action_refs=_wire_texts(
                stored["action_refs"], "review action reference", ordered=True
            ),
            prepared_at_utc=_utc(stored["prepared_at_utc"], "review prepare time"),
            completed_at_utc=_utc(
                stored["completed_at_utc"], "review completion time"
            ),
            prepare_digest=_sha256(
                stored["prepare_digest"], "review prepare digest"
            ),
            result_digest=_sha256(stored["result_digest"], "review result digest"),
            notification_required=_boolean(
                stored["notification_required"], "review notification flag"
            ),
        )


@dataclass(frozen=True)
class DailyReviewLedger:
    owner_id: str
    installation_id: str
    version: int
    completed: tuple[DailyReviewRecord, ...]
    pending: DailyReviewPending | None = None

    def __post_init__(self) -> None:
        _text(self.owner_id, "review owner")
        _text(self.installation_id, "review installation")
        _nonnegative_integer(self.version, "review ledger version")
        if type(self.completed) is not tuple or any(
            type(record) is not DailyReviewRecord for record in self.completed
        ):
            raise ReviewContractViolation("invalid completed reviews")
        keys = tuple(record.key.value for record in self.completed)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ReviewContractViolation("completed review keys must be uniquely ordered")
        if any(not self._owns(record.key) for record in self.completed):
            raise ReviewContractViolation("review ledger authority mismatch")
        if self.pending is not None:
            if type(self.pending) is not DailyReviewPending or not self._owns(
                self.pending.key
            ):
                raise ReviewContractViolation("pending review authority mismatch")
            if self.pending.key.value in set(keys):
                raise ReviewContractViolation("completed review cannot remain pending")

    def _owns(self, key: LocalDayKey) -> bool:
        return (
            key.owner_id == self.owner_id
            and key.installation_id == self.installation_id
        )

    @classmethod
    def empty(cls, owner_id: str, installation_id: str) -> "DailyReviewLedger":
        return cls(
            _text(owner_id, "review owner"),
            _text(installation_id, "review installation"),
            0,
            (),
            None,
        )

    def record_for(self, key: LocalDayKey) -> DailyReviewRecord | None:
        if type(key) is not LocalDayKey or not self._owns(key):
            raise ReviewContractViolation("review key is outside ledger authority")
        for record in self.completed:
            if record.key == key:
                return record
        return None

    def to_storage(self) -> dict[str, object]:
        return {
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "version": self.version,
            "completed": [record.to_storage() for record in self.completed],
            "pending": None if self.pending is None else self.pending.to_storage(),
        }

    @classmethod
    def from_storage(cls, value: object) -> "DailyReviewLedger":
        stored = _mapping(
            value,
            frozenset(
                {"owner_id", "installation_id", "version", "completed", "pending"}
            ),
            "daily review ledger",
        )
        completed = stored["completed"]
        if type(completed) is not list:
            raise ReviewContractViolation("invalid completed reviews")
        pending = stored["pending"]
        return cls(
            owner_id=_text(stored["owner_id"], "review owner"),
            installation_id=_text(
                stored["installation_id"], "review installation"
            ),
            version=_nonnegative_integer(stored["version"], "review ledger version"),
            completed=tuple(
                DailyReviewRecord.from_storage(record) for record in completed
            ),
            pending=(
                None if pending is None else DailyReviewPending.from_storage(pending)
            ),
        )


@dataclass(frozen=True)
class DailyReviewDecision:
    ledger: DailyReviewLedger
    key: LocalDayKey
    outcome: str
    record: DailyReviewRecord | None
    notification_required: bool
    replayed: bool = False

    def __post_init__(self) -> None:
        if type(self.ledger) is not DailyReviewLedger:
            raise ReviewContractViolation("invalid review decision ledger")
        if type(self.key) is not LocalDayKey or not self.ledger._owns(self.key):
            raise ReviewContractViolation("invalid review decision key")
        _text(self.outcome, "review decision outcome")
        if self.record is not None and type(self.record) is not DailyReviewRecord:
            raise ReviewContractViolation("invalid review decision record")
        _boolean(self.notification_required, "review decision notification flag")
        _boolean(self.replayed, "review decision replay flag")


class DailyReviewEngine:
    """Prepare and commit at most one review for the current owner-local day."""

    @staticmethod
    def prepare(
        ledger: DailyReviewLedger,
        *,
        owner_id: str,
        installation_id: str,
        timezone_name: str,
        observed_at_utc: str,
        current_state_digest: str,
        action_refs: tuple[str, ...] = (),
        changed: bool = False,
    ) -> DailyReviewDecision:
        if type(ledger) is not DailyReviewLedger:
            raise ReviewContractViolation("invalid review ledger")
        observed = _utc(observed_at_utc, "review observation time")
        state_digest = _sha256(current_state_digest, "review state digest")
        refs = tuple(
            sorted(_tuple_texts(action_refs, "review action reference"))
        )
        changed_flag = _boolean(changed, "review changed flag")
        key = local_day_key(
            owner_id,
            installation_id,
            timezone_name,
            observed,
        )
        if not ledger._owns(key):
            raise ReviewContractViolation("review ledger authority mismatch")
        existing = ledger.record_for(key)
        if existing is not None:
            return DailyReviewDecision(
                ledger,
                key,
                "already-completed",
                existing,
                False,
                True,
            )
        if any(
            record.key.local_date >= key.local_date
            for record in ledger.completed
        ):
            return DailyReviewDecision(
                ledger,
                key,
                "old-local-day-suppressed",
                None,
                False,
                True,
            )
        if ledger.pending is not None and ledger.pending.key == key:
            return DailyReviewDecision(
                ledger,
                key,
                "resume-current-day",
                None,
                ledger.pending.notification_required,
                True,
            )
        pending = DailyReviewPending(
            key=key,
            state_digest=state_digest,
            changed=changed_flag,
            action_refs=refs,
            prepared_at_utc=observed,
            prepare_digest=_pending_digest(
                key,
                state_digest,
                changed_flag,
                refs,
                observed,
            ),
        )
        stale_pending = ledger.pending is not None
        prepared_ledger = replace(
            ledger,
            version=ledger.version + 1,
            pending=pending,
        )
        return DailyReviewDecision(
            prepared_ledger,
            key,
            "stale-pending-replaced" if stale_pending else "prepared",
            None,
            pending.notification_required,
            False,
        )

    @staticmethod
    def commit(
        decision: DailyReviewDecision,
        *,
        completed_at_utc: str,
    ) -> DailyReviewDecision:
        if type(decision) is not DailyReviewDecision:
            raise ReviewContractViolation("invalid review decision")
        if decision.outcome in {
            "already-completed",
            "old-local-day-suppressed",
        }:
            return decision
        pending = decision.ledger.pending
        if pending is None or pending.key != decision.key:
            raise ReviewContractViolation("review commit requires its durable pending fact")
        completed_at = _utc(completed_at_utc, "review completion time")
        if local_day_key(
            pending.key.owner_id,
            pending.key.installation_id,
            pending.key.timezone,
            completed_at,
        ) != pending.key:
            raise ReviewContractViolation(
                "stale pending review cannot cross its owner-local day"
            )
        record = DailyReviewRecord(
            key=pending.key,
            state_digest=pending.state_digest,
            changed=pending.changed,
            action_refs=pending.action_refs,
            prepared_at_utc=pending.prepared_at_utc,
            completed_at_utc=completed_at,
            prepare_digest=pending.prepare_digest,
            result_digest=_review_result_digest(pending, completed_at),
            notification_required=pending.notification_required,
        )
        completed = tuple(
            sorted(
                decision.ledger.completed + (record,),
                key=lambda item: item.key.value,
            )
        )
        ledger = replace(
            decision.ledger,
            version=decision.ledger.version + 1,
            completed=completed,
            pending=None,
        )
        return DailyReviewDecision(
            ledger,
            decision.key,
            "committed",
            record,
            record.notification_required,
            False,
        )

    @staticmethod
    def commit_observation(
        decision: DailyReviewDecision,
        *,
        state_digest: str,
        changed: bool,
        action_refs: tuple[str, ...],
        completed_at_utc: str,
    ) -> DailyReviewDecision:
        """Commit only the exact observation already persisted by prepare."""

        if type(decision) is not DailyReviewDecision:
            raise ReviewContractViolation("invalid review decision")
        if decision.outcome in {
            "already-completed",
            "old-local-day-suppressed",
        }:
            return decision
        pending = decision.ledger.pending
        if pending is None or pending.key != decision.key:
            raise ReviewContractViolation("review commit requires its durable pending fact")
        requested = (
            _sha256(state_digest, "review state digest"),
            _boolean(changed, "review changed flag"),
            tuple(sorted(_tuple_texts(action_refs, "review action reference"))),
        )
        if requested != (
            pending.state_digest,
            pending.changed,
            pending.action_refs,
        ):
            raise ReviewContractViolation("review commit cannot mutate its pending observation")
        return DailyReviewEngine.commit(
            decision,
            completed_at_utc=completed_at_utc,
        )


LocalDayReview = DailyReviewRecord
ReviewLedger = DailyReviewLedger

__all__ = [
    "DailyReviewDecision",
    "DailyReviewEngine",
    "DailyReviewLedger",
    "DailyReviewPending",
    "DailyReviewRecord",
    "LocalDayKey",
    "LocalDayReview",
    "ReviewContractViolation",
    "ReviewLedger",
    "local_day_key",
]

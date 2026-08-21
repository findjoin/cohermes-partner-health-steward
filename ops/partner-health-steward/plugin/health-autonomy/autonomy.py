"""Deterministic autonomy core for the isolated partner health steward.

The language model never writes this database and never creates cron jobs.
Only typed rules in this module may update the structured profile, interaction
preferences, or reversible low-risk reminder tasks.

This module is stdlib-only so the same code can run inside the Hermes gateway
and from the fixed ``no_agent`` cron dispatcher.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA_VERSION = 3
DISPATCH_JOB_NAME = "health-autonomy-dispatch-v02"
DISPATCH_JOB_SCRIPT = "health_autonomy_dispatch.py"
DISPATCH_JOB_PROMPT = "[health-autonomy-v02] deterministic private dispatcher"
DISPATCH_JOB_SCHEDULE = "every 5m"

ALLOWED_CATEGORIES = {
    "补水提示": "hydration_cue",
    "作息收尾": "wind_down",
    "久坐活动": "movement_cue",
}
CATEGORY_LABELS = {value: key for key, value in ALLOWED_CATEGORIES.items()}

EVIDENCE_STATES = {
    "candidate",
    "single",
    "explicit",
    "repeated",
    "conflicted",
    "invalid",
    "stale",
}

FIXED_MESSAGES = {
    "hydration_cue": "该喝点水了。如果医生要求限制饮水，请按医嘱。",
    "wind_down": "可以准备收尾休息了，给自己留一点放松时间。",
    "movement_cue": "坐得有点久了，可以按自己的舒适程度起身活动一下；不舒服时不要勉强。",
}

SHORT_MESSAGES = {
    "hydration_cue": "该喝点水了；如有医生限水要求，请按医嘱。",
    "wind_down": "可以准备收尾休息了。",
    "movement_cue": "坐久了可按舒适程度活动一下；不舒服时别勉强。",
}

CONTROL_EXACT = {
    "健康管家状态": "status",
    "暂停健康管家自治模式": "pause",
    "恢复健康管家自治模式": "resume",
    "关闭健康管家自治模式": "revoke",
    "删除我的健康管家数据": "delete",
}


class DuplicateControlEvent(RuntimeError):
    """Raised when Telegram redelivers an already-consumed mutating control."""


class DataSubjectMismatch(PermissionError):
    """Raised when a verified but different user targets the bound store."""

ACTIVATION_PREFIX = "确认开启健康管家自治模式："
ACTIVATION_KEYS = {
    "画像",
    "交互学习",
    "模型最小使用",
    "自治类别",
    "补水提示时间",
    "作息收尾时间",
    "久坐活动时间",
    "每日主动消息上限",
    "最短间隔分钟",
    "静默时段",
    "时区",
    "任务最长天数",
    "数据保留天数",
    "同时任务上限",
    "单次调时上限分钟",
}


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _zone(timezone_name: str) -> dt.tzinfo:
    """Resolve an IANA zone, with a stdlib-only Shanghai fallback on Windows.

    Production Linux reads the system tz database.  Some Windows Python
    distributions omit ``tzdata`` entirely; Asia/Shanghai has no present-day
    daylight-saving transitions, so UTC+08:00 is an exact operational fallback
    for this partner-only deployment target.
    """
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "Asia/Shanghai":
            return dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")
        raise


def _utc_iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def _parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def routing_subject_key(routing: dict[str, str]) -> str:
    """Pseudonymous, stable binding for the one authorized data subject."""
    platform = str(routing.get("platform") or "").strip().lower()
    user_id = str(routing.get("user_id") or "").strip()
    chat_id = str(routing.get("chat_id") or "").strip()
    if not platform or not user_id or not chat_id:
        raise ValueError("缺少可绑定数据主体的平台、用户或私聊标识")
    material = f"health-autonomy-v02|{platform}|{user_id}|{chat_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_RUNTIME_JOB_VOLATILE_FIELDS = frozenset(
    {
        "next_run_at",
        "last_run_at",
        "last_status",
        "last_error",
        "last_delivery_error",
        "run_claim",
        "fire_claim",
    }
)


def runtime_job_fingerprint(job: dict[str, Any]) -> str:
    """Match Hermes core's binding of the exact run/delivery job snapshot."""
    snapshot = {
        str(key): value
        for key, value in job.items()
        if str(key) not in _RUNTIME_JOB_VOLATILE_FIELDS
    }
    repeat = snapshot.get("repeat")
    if isinstance(repeat, dict):
        snapshot["repeat"] = {"times": repeat.get("times")}
    elif repeat is None:
        snapshot["repeat"] = {"times": None}
    return hashlib.sha256(_json(snapshot).encode("utf-8")).hexdigest()


def _uuid() -> str:
    return uuid.uuid4().hex


def _clock_minutes(value: str) -> int:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value.strip())
    if not match:
        raise ValueError(f"时间必须是 HH:MM：{value}")
    return int(match.group(1)) * 60 + int(match.group(2))


def _format_minutes(value: int) -> str:
    value %= 24 * 60
    return f"{value // 60:02d}:{value % 60:02d}"


def _in_quiet_minutes(value: int, quiet_start: int, quiet_end: int) -> bool:
    if quiet_start == quiet_end:
        return False
    if quiet_start < quiet_end:
        return quiet_start <= value < quiet_end
    return value >= quiet_start or value < quiet_end


def _local_date(now: dt.datetime, timezone_name: str) -> str:
    return now.astimezone(_zone(timezone_name)).date().isoformat()


def _next_occurrence(
    schedule: dict[str, Any],
    timezone_name: str,
    after: dt.datetime,
) -> dt.datetime:
    """Return the next strictly-future local wall-clock occurrence in UTC."""
    zone = _zone(timezone_name)
    local_after = after.astimezone(zone)
    times = sorted({_clock_minutes(value) for value in schedule.get("times", [])})
    weekdays = set(schedule.get("weekdays", range(7)))
    if not times:
        raise ValueError("schedule has no local times")
    for day_offset in range(0, 9):
        date = local_after.date() + dt.timedelta(days=day_offset)
        if date.weekday() not in weekdays:
            continue
        for minutes in times:
            candidate_local = dt.datetime.combine(
                date,
                dt.time(minutes // 60, minutes % 60),
                tzinfo=zone,
            )
            candidate = candidate_local.astimezone(dt.timezone.utc)
            if candidate > after:
                return candidate
    raise RuntimeError("no future schedule occurrence found")


def _quiet_end_after(now: dt.datetime, timezone_name: str, quiet_end: int) -> dt.datetime:
    zone = _zone(timezone_name)
    local_now = now.astimezone(zone)
    end_today = dt.datetime.combine(
        local_now.date(),
        dt.time(quiet_end // 60, quiet_end % 60),
        tzinfo=zone,
    )
    if end_today <= local_now:
        end_today += dt.timedelta(days=1)
    return end_today.astimezone(dt.timezone.utc)


@dataclasses.dataclass(frozen=True)
class ActivationConfig:
    structured_profile: bool
    interaction_learning: bool
    minimal_model_context: bool
    categories: tuple[str, ...]
    category_times: dict[str, tuple[str, ...]]
    max_proactive_messages_24h: int
    min_spacing_minutes: int
    quiet_start: str
    quiet_end: str
    timezone: str
    task_ttl_days: int
    data_retention_days: int
    max_active_tasks: int
    max_schedule_shift_minutes: int
    max_new_tasks_7d: int = 1

    def to_params(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def activation_example() -> str:
    return (
        ACTIVATION_PREFIX
        +
        "画像=开；交互学习=开；模型最小使用=开；"
        "自治类别=补水提示,作息收尾,久坐活动；"
        "补水提示时间=10:30,15:30；作息收尾时间=22:30；"
        "久坐活动时间=11:00,16:00；每日主动消息上限=3；"
        "最短间隔分钟=240；静默时段=23:00-08:00；"
        "时区=Asia/Shanghai；任务最长天数=30；"
        "数据保留天数=180；同时任务上限=3；单次调时上限分钟=30"
    )


def parse_activation(text: str) -> ActivationConfig:
    normalized = text.strip().rstrip("。")
    if not normalized.startswith(ACTIVATION_PREFIX):
        raise ValueError("不是健康管家自治授权语句")
    body = normalized[len(ACTIVATION_PREFIX) :]
    pairs: dict[str, str] = {}
    for piece in re.split(r"[；;]", body):
        piece = piece.strip()
        if not piece:
            continue
        if "=" not in piece:
            raise ValueError(f"授权字段缺少等号：{piece}")
        key, value = (part.strip() for part in piece.split("=", 1))
        if key in pairs:
            raise ValueError(f"授权字段重复：{key}")
        pairs[key] = value
    unknown = set(pairs) - ACTIVATION_KEYS
    missing = ACTIVATION_KEYS - set(pairs)
    if unknown:
        raise ValueError(f"存在未知授权字段：{','.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"缺少授权字段：{','.join(sorted(missing))}")

    def enabled(key: str) -> bool:
        if pairs[key] not in {"开", "关"}:
            raise ValueError(f"{key} 只能是开或关")
        return pairs[key] == "开"

    profile = enabled("画像")
    learning = enabled("交互学习")
    model_context = enabled("模型最小使用")
    if not model_context:
        raise ValueError(
            "v0.2 为保证任务变更有明确回执，模型最小使用必须为开；它只允许当前动作、偏好和相关字段，不允许完整画像"
        )
    category_labels = tuple(
        item.strip()
        for item in re.split(r"[,，、]", pairs["自治类别"])
        if item.strip()
    )
    if not category_labels:
        raise ValueError("自治类别不能为空；不授权自治任务时请不要启用本模式")
    unknown_categories = set(category_labels) - set(ALLOWED_CATEGORIES)
    if unknown_categories:
        raise ValueError(f"不支持的自治类别：{','.join(sorted(unknown_categories))}")
    if len(set(category_labels)) != len(category_labels):
        raise ValueError("自治类别不能重复")
    categories = tuple(ALLOWED_CATEGORIES[label] for label in category_labels)

    schedule_keys = {
        "hydration_cue": "补水提示时间",
        "wind_down": "作息收尾时间",
        "movement_cue": "久坐活动时间",
    }
    category_times: dict[str, tuple[str, ...]] = {}
    for category, key in schedule_keys.items():
        values = tuple(
            item.strip()
            for item in re.split(r"[,，、]", pairs[key])
            if item.strip()
        )
        if category in categories and not values:
            raise ValueError(f"已授权 {CATEGORY_LABELS[category]}，必须给出 {key}")
        if len(values) > 2:
            raise ValueError(f"{key} 首版最多两个时点")
        for value in values:
            _clock_minutes(value)
        category_times[category] = values

    def bounded_int(key: str, minimum: int, maximum: int) -> int:
        try:
            value = int(pairs[key])
        except ValueError as exc:
            raise ValueError(f"{key} 必须是整数") from exc
        if not minimum <= value <= maximum:
            raise ValueError(f"{key} 必须在 {minimum} 到 {maximum} 之间")
        return value

    daily_cap = bounded_int("每日主动消息上限", 1, 5)
    spacing = bounded_int("最短间隔分钟", 60, 720)
    ttl = bounded_int("任务最长天数", 1, 30)
    retention = bounded_int("数据保留天数", 7, 180)
    max_tasks = bounded_int("同时任务上限", 1, 3)
    max_shift = bounded_int("单次调时上限分钟", 10, 60)
    if ttl > retention:
        raise ValueError("任务最长天数不能大于数据保留天数")

    quiet_match = re.fullmatch(
        r"([0-2]\d:[0-5]\d)-([0-2]\d:[0-5]\d)", pairs["静默时段"]
    )
    if not quiet_match:
        raise ValueError("静默时段必须是 HH:MM-HH:MM")
    quiet_start, quiet_end = quiet_match.groups()
    quiet_start_minutes = _clock_minutes(quiet_start)
    quiet_end_minutes = _clock_minutes(quiet_end)
    if quiet_start_minutes == quiet_end_minutes:
        raise ValueError("静默开始和结束不能相同")

    timezone_name = pairs["时区"]
    try:
        _zone(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"未知 IANA 时区：{timezone_name}") from exc

    for category in categories:
        for value in category_times[category]:
            if _in_quiet_minutes(
                _clock_minutes(value), quiet_start_minutes, quiet_end_minutes
            ):
                raise ValueError(
                    f"{CATEGORY_LABELS[category]}时点 {value} 落在静默时段内"
                )

    return ActivationConfig(
        structured_profile=profile,
        interaction_learning=learning,
        minimal_model_context=model_context,
        categories=categories,
        category_times=category_times,
        max_proactive_messages_24h=daily_cap,
        min_spacing_minutes=spacing,
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        timezone=timezone_name,
        task_ttl_days=ttl,
        data_retention_days=retention,
        max_active_tasks=max_tasks,
        max_schedule_shift_minutes=max_shift,
    )


def default_db_path() -> Path:
    home = Path(os.environ.get("HERMES_HOME", "/root/.hermes/profiles/partner"))
    return home / "private" / "health-autonomy-v02.sqlite3"


class HealthAutonomyStore:
    """Private structured state with append-only evidence and reversible tasks."""

    _EXPECTED_COLUMNS = {
        "schema_meta": ("key", "value"),
        "authorization": (
            "authorization_id", "subject_key", "scope", "decision", "params_json",
            "granted_by", "valid_from", "valid_until", "revoked_at", "source_event_id",
        ),
        "control_state": ("key", "value", "updated_at"),
        "observation_event": (
            "event_id", "subject_key", "event_kind", "source_kind", "source_actor_key",
            "source_ref_hash", "occurred_at", "received_at", "payload_json", "schema_state",
            "correction_of", "retention_until", "idempotency_key",
        ),
        "state_item": (
            "item_id", "subject_key", "domain", "state_key", "value_json", "lifecycle",
            "evidence_state", "support_count", "support_days", "valid_from", "valid_until",
            "rule_id", "rule_version", "supersedes_item_id", "created_at",
        ),
        "state_evidence": ("item_id", "event_id", "relation"),
        "automation_task": (
            "task_id", "subject_key", "category", "purpose", "schedule_json", "timezone",
            "status", "trigger_item_id", "revision", "next_run_at", "suppressed_until",
            "review_at", "expires_at", "created_at", "last_dispatched_at", "last_adjusted_at",
            "run_count", "max_runs", "created_by_decision_id", "idempotency_key", "pause_reason",
        ),
        "feedback_event": (
            "feedback_id", "task_id", "source_event_id", "feedback_kind", "occurred_at",
            "local_date", "explicit", "idempotency_key",
        ),
        "decision_log": (
            "decision_id", "subject_key", "decided_at", "rule_id", "rule_version",
            "input_revisions_json", "result", "reason_code", "action_json",
            "execution_status", "reverses_decision_id", "idempotency_key",
        ),
        "dispatch_event": (
            "dispatch_id", "emitted_at", "task_ids_json", "disposition", "message_kind",
            "idempotency_key",
        ),
        "deletion_audit": ("deletion_id", "deleted_at", "deleted_counts_json"),
        "replay_tombstone": ("idempotency_key",),
        "control_replay_ledger": ("idempotency_key",),
        "message_replay_ledger": ("idempotency_key",),
    }

    def __init__(
        self,
        path: Optional[Path] = None,
        now_fn: Callable[[], dt.datetime] = utc_now,
    ) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.now_fn = now_fn
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._protect_path(self.path.parent, 0o700)
        if self.path.exists() or self.path.is_symlink():
            self._protect_path(self.path, 0o600)
        else:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.path, flags, 0o600)
            os.close(descriptor)
            self._protect_path(self.path, 0o600)
        self._initialize()
        self._protect_path(self.path, 0o600)

    @staticmethod
    def _protect_path(path: Path, mode: int) -> None:
        """Apply and verify private storage permissions, failing closed.

        Linux is the production target, so ownership and exact POSIX mode are
        mandatory there.  Windows has no equivalent uid/mode contract; it
        still rejects links and validates the object kind so local tests do
        not silently exercise a different path.
        """
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode):
            raise PermissionError(f"health autonomy private path must not be a symlink: {path}")
        expected_directory = mode == 0o700
        if expected_directory and not stat.S_ISDIR(before.st_mode):
            raise PermissionError(f"health autonomy private directory is not a directory: {path}")
        if not expected_directory and not stat.S_ISREG(before.st_mode):
            raise PermissionError(f"health autonomy database is not a regular file: {path}")
        os.chmod(path, mode)
        after = path.lstat()
        if stat.S_ISLNK(after.st_mode):
            raise PermissionError(f"health autonomy private path became a symlink: {path}")
        if os.name == "posix":
            if after.st_uid != os.geteuid():
                raise PermissionError(f"health autonomy private path owner mismatch: {path}")
            actual_mode = stat.S_IMODE(after.st_mode)
            if actual_mode != mode:
                raise PermissionError(
                    f"health autonomy private path mode mismatch: {path} "
                    f"actual={oct(actual_mode)} expected={oct(mode)}"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA secure_delete=ON")
        # DELETE avoids persistent -wal/-shm sidecars with weaker permissions.
        connection.execute("PRAGMA journal_mode=DELETE")
        return connection

    @contextlib.contextmanager
    def _transaction(self) -> Iterable[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with contextlib.closing(self._connect()) as existing_connection:
            existing_tables = {
                row["name"]
                for row in existing_connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            if existing_tables:
                self._validate_schema(existing_connection)
                return

        connection = self._connect()
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS authorization (
                    authorization_id TEXT NOT NULL,
                    subject_key TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('allow','deny')),
                    params_json TEXT NOT NULL,
                    granted_by TEXT NOT NULL CHECK(granted_by = 'self'),
                    valid_from TEXT NOT NULL,
                    valid_until TEXT NOT NULL,
                    revoked_at TEXT,
                    source_event_id TEXT NOT NULL,
                    PRIMARY KEY (authorization_id, scope),
                    UNIQUE (scope, source_event_id)
                );
                CREATE TABLE IF NOT EXISTS control_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observation_event (
                    event_id TEXT PRIMARY KEY,
                    subject_key TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_actor_key TEXT NOT NULL,
                    source_ref_hash TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    schema_state TEXT NOT NULL,
                    correction_of TEXT,
                    retention_until TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS state_item (
                    item_id TEXT PRIMARY KEY,
                    subject_key TEXT NOT NULL,
                    domain TEXT NOT NULL CHECK(domain IN (
                        'health_profile','interaction_preference','automation_policy'
                    )),
                    state_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    lifecycle TEXT NOT NULL CHECK(lifecycle IN (
                        'active','superseded','invalidated','deleted'
                    )),
                    evidence_state TEXT NOT NULL,
                    support_count INTEGER NOT NULL,
                    support_days INTEGER NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    supersedes_item_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_state_active
                    ON state_item(subject_key, domain, state_key, lifecycle, created_at);
                CREATE TABLE IF NOT EXISTS state_evidence (
                    item_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    relation TEXT NOT NULL CHECK(relation IN (
                        'supports','contradicts','corrects'
                    )),
                    PRIMARY KEY(item_id, event_id, relation),
                    FOREIGN KEY(item_id) REFERENCES state_item(item_id) ON DELETE CASCADE,
                    FOREIGN KEY(event_id) REFERENCES observation_event(event_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS automation_task (
                    task_id TEXT PRIMARY KEY,
                    subject_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    schedule_json TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','paused','expired')),
                    trigger_item_id TEXT,
                    revision INTEGER NOT NULL,
                    next_run_at TEXT NOT NULL,
                    suppressed_until TEXT,
                    review_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_dispatched_at TEXT,
                    last_adjusted_at TEXT,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    max_runs INTEGER NOT NULL,
                    created_by_decision_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    pause_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_due
                    ON automation_task(status, next_run_at);
                CREATE TABLE IF NOT EXISTS feedback_event (
                    feedback_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    feedback_kind TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    local_date TEXT NOT NULL,
                    explicit INTEGER NOT NULL CHECK(explicit IN (0,1)),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    FOREIGN KEY(task_id) REFERENCES automation_task(task_id) ON DELETE CASCADE,
                    FOREIGN KEY(source_event_id) REFERENCES observation_event(event_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS decision_log (
                    decision_id TEXT PRIMARY KEY,
                    subject_key TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    input_revisions_json TEXT NOT NULL,
                    result TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    action_json TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    reverses_decision_id TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS dispatch_event (
                    dispatch_id TEXT PRIMARY KEY,
                    emitted_at TEXT NOT NULL,
                    task_ids_json TEXT NOT NULL,
                    disposition TEXT NOT NULL CHECK(disposition IN ('emitted_to_cron')),
                    message_kind TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS deletion_audit (
                    deletion_id TEXT PRIMARY KEY,
                    deleted_at TEXT NOT NULL,
                    deleted_counts_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replay_tombstone (
                    idempotency_key TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS control_replay_ledger (
                    idempotency_key TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS message_replay_ledger (
                    idempotency_key TEXT PRIMARY KEY
                );
                INSERT INTO schema_meta(key,value) VALUES('schema_version','3');
                INSERT INTO schema_meta(key,value)
                    VALUES('replay_hmac_key',lower(hex(randomblob(32))));
                PRAGMA user_version=3;
                COMMIT;
                """
            )
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        with contextlib.closing(self._connect()) as created_connection:
            self._validate_schema(created_connection)

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        actual_tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        expected_tables = set(self._EXPECTED_COLUMNS)
        if actual_tables != expected_tables:
            raise RuntimeError(
                "health autonomy database schema mismatch: "
                f"tables={sorted(actual_tables)} expected={sorted(expected_tables)}"
            )
        for table, expected_columns in self._EXPECTED_COLUMNS.items():
            actual_columns = tuple(
                row["name"] for row in connection.execute(f"PRAGMA table_info('{table}')")
            )
            if actual_columns != expected_columns:
                raise RuntimeError(
                    f"health autonomy database schema mismatch: {table} columns={actual_columns}"
                )
        version_row = connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if not version_row or version_row["value"] != str(SCHEMA_VERSION) or user_version != SCHEMA_VERSION:
            raise RuntimeError("health autonomy database schema version mismatch")
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            ).fetchall()
        }
        if not {"idx_state_active", "idx_tasks_due"}.issubset(indexes):
            raise RuntimeError("health autonomy database required indexes are missing")
        for table in (
            "observation_event",
            "automation_task",
            "feedback_event",
            "decision_log",
            "dispatch_event",
        ):
            unique_sets = []
            for index_row in connection.execute(f"PRAGMA index_list('{table}')"):
                if int(index_row["unique"]) != 1:
                    continue
                columns = tuple(
                    row["name"]
                    for row in connection.execute(
                        f"PRAGMA index_info('{index_row['name']}')"
                    )
                )
                unique_sets.append(columns)
            if ("idempotency_key",) not in unique_sets:
                raise RuntimeError(
                    f"health autonomy database idempotency constraint missing: {table}"
                )
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("health autonomy database foreign key check failed")
        replay_key = connection.execute(
            "SELECT value FROM schema_meta WHERE key='replay_hmac_key'"
        ).fetchone()
        if not replay_key or not re.fullmatch(r"[0-9a-f]{64}", replay_key["value"]):
            raise RuntimeError("health autonomy database replay key is missing or invalid")

    @staticmethod
    def _event_key(
        connection: sqlite3.Connection,
        message_id: str,
        subject_key: str,
        namespace: str,
    ) -> str:
        """Return a routing-bound opaque replay key without retaining metadata."""
        key_row = connection.execute(
            "SELECT value FROM schema_meta WHERE key='replay_hmac_key'"
        ).fetchone()
        if not key_row:
            raise RuntimeError("health autonomy replay key is unavailable")
        try:
            key = bytes.fromhex(str(key_row["value"]))
        except ValueError as exc:
            raise RuntimeError("health autonomy replay key is invalid") from exc
        material = f"{namespace}|{subject_key}|{message_id}".encode("utf-8")
        return hmac.new(key, material, hashlib.sha256).hexdigest()

    @staticmethod
    def _route_fingerprint(
        connection: sqlite3.Connection, routing: dict[str, str]
    ) -> str:
        key_row = connection.execute(
            "SELECT value FROM schema_meta WHERE key='replay_hmac_key'"
        ).fetchone()
        if not key_row:
            raise RuntimeError("health autonomy replay key is unavailable")
        normalized = {
            "platform": str(routing.get("platform") or "").lower(),
            "chat_id": str(routing.get("chat_id") or ""),
            "thread_id": str(routing.get("thread_id") or ""),
            "user_id": str(routing.get("user_id") or ""),
            "chat_type": str(routing.get("chat_type") or "").lower(),
        }
        key = bytes.fromhex(str(key_row["value"]))
        return hmac.new(
            key,
            ("dispatcher-route|" + _json(normalized)).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _set_control(connection: sqlite3.Connection, key: str, value: str, now: str) -> None:
        connection.execute(
            """
            INSERT INTO control_state(key,value,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now),
        )

    @staticmethod
    def _get_control(connection: sqlite3.Connection, key: str) -> Optional[str]:
        row = connection.execute(
            "SELECT value FROM control_state WHERE key=?", (key,)
        ).fetchone()
        return str(row["value"]) if row else None

    def _consume_control_event(
        self,
        connection: sqlite3.Connection,
        source_message_id: Optional[str],
        subject_key: str,
        action: str,
    ) -> None:
        if not source_message_id:
            return
        key = self._event_key(
            connection, source_message_id, subject_key, f"control:{action}"
        )
        if connection.execute(
            "SELECT 1 FROM control_replay_ledger WHERE idempotency_key=?",
            (key,),
        ).fetchone():
            raise DuplicateControlEvent(action)
        connection.execute(
            "INSERT INTO control_replay_ledger VALUES(?)",
            (key,),
        )

    def activate(
        self,
        config: ActivationConfig,
        source_message_id: str,
        dispatcher_job_id: str,
        subject_key: str,
        dispatcher_routing: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        now = self.now_fn()
        now_text = _utc_iso(now)
        valid_until = _utc_iso(now + dt.timedelta(days=180))
        scopes = ["autonomous_tasks"]
        if config.structured_profile:
            scopes.append("structured_profile")
        if config.interaction_learning:
            scopes.append("interaction_learning")
        if config.minimal_model_context:
            scopes.append("minimal_model_context")
        params_json = _json(config.to_params())

        with self._transaction() as connection:
            source_event_id = self._event_key(
                connection, source_message_id, subject_key, "control:activate"
            )
            existing_subject = self._get_control(connection, "subject_key")
            if existing_subject and existing_subject != subject_key:
                raise DataSubjectMismatch(
                    "现有健康数据绑定到另一位数据主体；拒绝换绑，请先由原本人删除或由管理员离线清除"
                )
            consumed = connection.execute(
                "SELECT 1 FROM control_replay_ledger WHERE idempotency_key=?",
                (source_event_id,),
            ).fetchone()
            if consumed:
                return {"authorization_id": None, "duplicate": True}
            duplicate = connection.execute(
                "SELECT authorization_id FROM authorization WHERE source_event_id=? LIMIT 1",
                (source_event_id,),
            ).fetchone()
            if duplicate:
                return {
                    "authorization_id": duplicate["authorization_id"],
                    "duplicate": True,
                }
            old_id = self._get_control(connection, "authorization_id")
            if old_id:
                connection.execute(
                    "UPDATE authorization SET revoked_at=? WHERE authorization_id=? AND revoked_at IS NULL",
                    (now_text, old_id),
                )
            authorization_id = _uuid()
            for scope in scopes:
                connection.execute(
                    """
                    INSERT INTO authorization(
                        authorization_id,subject_key,scope,decision,params_json,
                        granted_by,valid_from,valid_until,revoked_at,source_event_id
                    ) VALUES(?,?,?,?,?,?,?,?,NULL,?)
                    """,
                    (
                        authorization_id,
                        subject_key,
                        scope,
                        "allow",
                        params_json,
                        "self",
                        now_text,
                        valid_until,
                        source_event_id,
                    ),
                )
            self._set_control(connection, "authorization_id", authorization_id, now_text)
            self._set_control(connection, "subject_key", subject_key, now_text)
            self._set_control(connection, "mode", "active", now_text)
            self._set_control(connection, "dispatcher_job_id", dispatcher_job_id, now_text)
            if dispatcher_routing:
                self._set_control(
                    connection,
                    "dispatcher_route_fingerprint",
                    self._route_fingerprint(connection, dispatcher_routing),
                    now_text,
                )
            self._set_control(
                connection,
                "data_retention_days",
                str(config.data_retention_days),
                now_text,
            )
            retention_deadline = _utc_iso(
                now + dt.timedelta(days=config.data_retention_days)
            )
            connection.execute(
                """
                UPDATE observation_event SET retention_until=?
                WHERE retention_until>?
                """,
                (retention_deadline, retention_deadline),
            )
            connection.execute(
                "UPDATE state_item SET valid_until=? WHERE valid_until>?",
                (retention_deadline, retention_deadline),
            )
            connection.execute(
                """
                UPDATE automation_task SET expires_at=?,review_at=?
                WHERE expires_at>?
                """,
                (retention_deadline, retention_deadline, retention_deadline),
            )
            allowed_categories = tuple(config.categories)
            if allowed_categories:
                placeholders = ",".join("?" for _ in allowed_categories)
                connection.execute(
                    f"""
                    UPDATE automation_task
                    SET status='paused',pause_reason='authorization_scope_changed'
                    WHERE status='active' AND category NOT IN ({placeholders})
                    """,
                    allowed_categories,
                )
                retained = connection.execute(
                    f"""
                    SELECT task_id,category,timezone,expires_at,run_count,max_runs
                    FROM automation_task
                    WHERE status='active' AND category IN ({placeholders})
                    """,
                    allowed_categories,
                ).fetchall()
                for task in retained:
                    schedule = {
                        "kind": "daily",
                        "times": list(config.category_times[task["category"]]),
                        "weekdays": list(range(7)),
                    }
                    next_run = _next_occurrence(schedule, config.timezone, now)
                    tightened_expiry = min(
                        _parse_utc(task["expires_at"]),
                        now + dt.timedelta(days=config.task_ttl_days),
                    )
                    tightened_max_runs = min(
                        int(task["max_runs"]),
                        int(task["run_count"])
                        + config.task_ttl_days * len(schedule["times"]),
                    )
                    connection.execute(
                        """
                        UPDATE automation_task SET schedule_json=?,timezone=?,revision=revision+1,
                            next_run_at=?,suppressed_until=NULL,last_adjusted_at=?,
                            review_at=?,expires_at=?,max_runs=?
                        WHERE task_id=?
                        """,
                        (
                            _json(schedule),
                            config.timezone,
                            _utc_iso(next_run),
                            now_text,
                            _utc_iso(tightened_expiry),
                            _utc_iso(tightened_expiry),
                            tightened_max_runs,
                            task["task_id"],
                        ),
                    )
                active_after_reconcile = connection.execute(
                    """
                    SELECT task_id FROM automation_task
                    WHERE status='active' ORDER BY created_at,task_id
                    """
                ).fetchall()
                for overflow in active_after_reconcile[config.max_active_tasks :]:
                    connection.execute(
                        """
                        UPDATE automation_task SET status='paused',
                            pause_reason='authorization_active_task_cap'
                        WHERE task_id=?
                        """,
                        (overflow["task_id"],),
                    )
            decision_id = _uuid()
            connection.execute(
                """
                INSERT INTO decision_log VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    decision_id,
                    subject_key,
                    now_text,
                    "authorization.activate",
                    "2.0",
                    _json({"source_event_id": source_event_id}),
                    "allowed",
                    "self_explicit_scoped_authorization",
                    _json({"scopes": scopes, "dispatcher_job_id": dispatcher_job_id}),
                    "executed",
                    None,
                    f"activate:{source_event_id}",
                ),
            )
            connection.execute(
                "INSERT INTO control_replay_ledger VALUES(?)",
                (source_event_id,),
            )
            self._purge_expired(connection, now)
        return {"authorization_id": authorization_id, "duplicate": False}

    def control_event_seen(
        self, source_message_id: str, action: str, subject_key: str
    ) -> bool:
        with contextlib.closing(self._connect()) as connection:
            key = self._event_key(
                connection, source_message_id, subject_key, f"control:{action}"
            )
            row = connection.execute(
                "SELECT 1 FROM control_replay_ledger WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            return bool(row)

    def _active_policy(
        self, connection: sqlite3.Connection, now: Optional[dt.datetime] = None
    ) -> Optional[dict[str, Any]]:
        now = now or self.now_fn()
        now_text = _utc_iso(now)
        if self._get_control(connection, "mode") != "active":
            return None
        authorization_id = self._get_control(connection, "authorization_id")
        if not authorization_id:
            return None
        row = connection.execute(
            """
            SELECT params_json FROM authorization
            WHERE authorization_id=? AND scope='autonomous_tasks'
              AND decision='allow' AND revoked_at IS NULL
              AND valid_from<=? AND valid_until>?
            """,
            (authorization_id, now_text, now_text),
        ).fetchone()
        return json.loads(row["params_json"]) if row else None

    def _scope_allowed(
        self, connection: sqlite3.Connection, scope: str, now: Optional[dt.datetime] = None
    ) -> bool:
        now = now or self.now_fn()
        authorization_id = self._get_control(connection, "authorization_id")
        if not authorization_id or self._get_control(connection, "mode") != "active":
            return False
        now_text = _utc_iso(now)
        row = connection.execute(
            """
            SELECT 1 FROM authorization
            WHERE authorization_id=? AND scope=? AND decision='allow'
              AND revoked_at IS NULL AND valid_from<=? AND valid_until>?
            """,
            (authorization_id, scope, now_text, now_text),
        ).fetchone()
        return bool(row)

    def _purge_expired(self, connection: sqlite3.Connection, now: dt.datetime) -> None:
        """Deterministically expire state and remove payload past retention."""
        now_text = _utc_iso(now)
        connection.execute(
            """
            UPDATE automation_task SET status='expired',pause_reason='ttl_expired'
            WHERE status='active' AND (expires_at<=? OR run_count>=max_runs)
            """,
            (now_text,),
        )
        expired_items = connection.execute(
            """
            SELECT item_id FROM state_item
            WHERE lifecycle='active' AND valid_until<=?
            """,
            (now_text,),
        ).fetchall()
        for item in expired_items:
            connection.execute(
                """
                UPDATE automation_task SET status='paused',pause_reason='trigger_state_expired'
                WHERE trigger_item_id=? AND status='active'
                """,
                (item["item_id"],),
            )
        connection.execute("DELETE FROM state_item WHERE valid_until<=?", (now_text,))
        connection.execute(
            "DELETE FROM observation_event WHERE retention_until<=?", (now_text,)
        )
        authorization_id = self._get_control(connection, "authorization_id")
        retention_days = 180
        stored_retention = self._get_control(connection, "data_retention_days")
        if stored_retention:
            try:
                retention_days = max(7, min(180, int(stored_retention)))
            except ValueError:
                retention_days = 180
        cutoff = _utc_iso(now - dt.timedelta(days=retention_days))
        connection.execute("DELETE FROM feedback_event WHERE occurred_at<=?", (cutoff,))
        connection.execute("DELETE FROM decision_log WHERE decided_at<=?", (cutoff,))
        connection.execute("DELETE FROM dispatch_event WHERE emitted_at<=?", (cutoff,))
        connection.execute(
            """
            DELETE FROM automation_task
            WHERE status<>'active' AND created_at<=?
            """,
            (cutoff,),
        )
        connection.execute(
            """
            DELETE FROM authorization
            WHERE valid_until<=? OR (revoked_at IS NOT NULL AND revoked_at<=?)
            """,
            (cutoff, cutoff),
        )
        if authorization_id:
            current_exists = connection.execute(
                "SELECT 1 FROM authorization WHERE authorization_id=? LIMIT 1",
                (authorization_id,),
            ).fetchone()
            if not current_exists:
                connection.execute(
                    "DELETE FROM control_state WHERE key='authorization_id'"
                )
                self._set_control(connection, "mode", "expired", now_text)

    def _assert_subject(
        self,
        connection: sqlite3.Connection,
        subject_key: str,
        *,
        allow_unbound: bool = False,
    ) -> None:
        bound = self._get_control(connection, "subject_key")
        if not bound and allow_unbound:
            return
        if not bound or bound != subject_key:
            raise DataSubjectMismatch("当前私聊身份不是这份健康数据的本人")

    def assert_activation_subject(self, subject_key: str) -> None:
        """Reject a different authorized sender before any cron side effect."""
        with contextlib.closing(self._connect()) as connection:
            self._assert_subject(connection, subject_key, allow_unbound=True)

    def dispatcher_job_id(self) -> Optional[str]:
        with contextlib.closing(self._connect()) as connection:
            return self._get_control(connection, "dispatcher_job_id")

    def dispatcher_binding(
        self,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        with contextlib.closing(self._connect()) as connection:
            return (
                self._get_control(connection, "dispatcher_job_id"),
                self._get_control(connection, "subject_key"),
                self._get_control(connection, "dispatcher_route_fingerprint"),
            )

    def dispatcher_route_matches(self, routing: dict[str, str]) -> bool:
        with contextlib.closing(self._connect()) as connection:
            expected = self._get_control(
                connection, "dispatcher_route_fingerprint"
            )
            if not expected:
                return False
            actual = self._route_fingerprint(connection, routing)
            return hmac.compare_digest(expected, actual)

    def quarantine_dispatcher(
        self,
        reason: str = "dispatcher_integrity_failure",
        expected_subject_key: Optional[str] = None,
    ) -> None:
        """Fail closed before any output when the managed cron fingerprint drifts."""
        now_text = _utc_iso(self.now_fn())
        with self._transaction() as connection:
            if expected_subject_key is not None:
                self._assert_subject(connection, expected_subject_key)
            self._set_control(connection, "mode", "paused_integrity", now_text)
            connection.execute(
                """
                UPDATE automation_task SET status='paused',pause_reason=?
                WHERE status='active'
                """,
                (reason,),
            )

    def housekeep(self) -> None:
        """Delete expired payload without reading it into the model or emitting."""
        with self._transaction() as connection:
            self._purge_expired(connection, self.now_fn())

    def status(self, subject_key: str) -> dict[str, Any]:
        with contextlib.closing(self._connect()) as connection:
            self._assert_subject(connection, subject_key, allow_unbound=True)
            now = self.now_fn()
            mode = self._get_control(connection, "mode") or "inactive"
            active_policy = self._active_policy(connection, now)
            authorization_id = self._get_control(connection, "authorization_id")
            policy_row = (
                connection.execute(
                    """
                    SELECT params_json FROM authorization
                    WHERE authorization_id=? AND scope='autonomous_tasks'
                    LIMIT 1
                    """,
                    (authorization_id,),
                ).fetchone()
                if authorization_id
                else None
            )
            policy = json.loads(policy_row["params_json"]) if policy_row else None
            active_state_count = connection.execute(
                "SELECT COUNT(*) AS n FROM state_item WHERE lifecycle='active'"
            ).fetchone()["n"]
            stored_counts = {
                "authorizations": int(
                    connection.execute(
                        "SELECT COUNT(*) AS n FROM authorization"
                    ).fetchone()["n"]
                ),
                "observations": int(
                    connection.execute(
                        "SELECT COUNT(*) AS n FROM observation_event"
                    ).fetchone()["n"]
                ),
                "state_items": int(
                    connection.execute(
                        "SELECT COUNT(*) AS n FROM state_item"
                    ).fetchone()["n"]
                ),
                "tasks": int(
                    connection.execute(
                        "SELECT COUNT(*) AS n FROM automation_task"
                    ).fetchone()["n"]
                ),
                "feedback": int(
                    connection.execute(
                        "SELECT COUNT(*) AS n FROM feedback_event"
                    ).fetchone()["n"]
                ),
                "decisions": int(
                    connection.execute(
                        "SELECT COUNT(*) AS n FROM decision_log"
                    ).fetchone()["n"]
                ),
                "dispatches": int(
                    connection.execute(
                        "SELECT COUNT(*) AS n FROM dispatch_event"
                    ).fetchone()["n"]
                ),
            }
            task_rows = connection.execute(
                """
                SELECT category,status,next_run_at,expires_at,pause_reason
                FROM automation_task ORDER BY created_at
                """
            ).fetchall()
            return {
                "mode": mode,
                "authorized": active_policy is not None,
                "can_dispatch": active_policy is not None and mode == "active",
                "policy": policy,
                "active_state_items": int(active_state_count),
                "stored_counts": stored_counts,
                "stored_payload_rows": sum(stored_counts.values()),
                "tasks": [dict(row) for row in task_rows],
                "dispatcher_job_id": self._get_control(connection, "dispatcher_job_id"),
                "housekeeping_configured": bool(
                    self._get_control(connection, "dispatcher_job_id")
                ),
            }

    def pause(
        self,
        subject_key: str,
        reason: str = "self_pause",
        source_message_id: Optional[str] = None,
    ) -> Optional[str]:
        now_text = _utc_iso(self.now_fn())
        with self._transaction() as connection:
            self._assert_subject(connection, subject_key)
            self._consume_control_event(
                connection, source_message_id, subject_key, "pause"
            )
            job_id = self._get_control(connection, "dispatcher_job_id")
            self._set_control(connection, "mode", "paused", now_text)
            connection.execute(
                """
                UPDATE automation_task SET status='paused', pause_reason=?
                WHERE status='active'
                """,
                (reason,),
            )
            return job_id

    def resume(
        self, subject_key: str, source_message_id: Optional[str] = None
    ) -> Optional[str]:
        now = self.now_fn()
        now_text = _utc_iso(now)
        with self._transaction() as connection:
            self._assert_subject(connection, subject_key)
            self._consume_control_event(
                connection, source_message_id, subject_key, "resume"
            )
            authorization_id = self._get_control(connection, "authorization_id")
            if not authorization_id:
                raise ValueError("没有可恢复的本人授权，请重新开启")
            valid = connection.execute(
                """
                SELECT 1 FROM authorization WHERE authorization_id=?
                  AND scope='autonomous_tasks' AND revoked_at IS NULL
                  AND valid_until>?
                """,
                (authorization_id, now_text),
            ).fetchone()
            if not valid:
                raise ValueError("授权已撤销或过期，请重新开启")
            row = connection.execute(
                "SELECT params_json FROM authorization WHERE authorization_id=? LIMIT 1",
                (authorization_id,),
            ).fetchone()
            params = json.loads(row["params_json"])
            self._set_control(connection, "mode", "active", now_text)
            tasks = connection.execute(
                """
                SELECT task_id,schedule_json,timezone,expires_at FROM automation_task
                WHERE status='paused' AND pause_reason='self_pause'
                """
            ).fetchall()
            for task in tasks:
                if _parse_utc(task["expires_at"]) <= now:
                    connection.execute(
                        "UPDATE automation_task SET status='expired',pause_reason='ttl_expired' WHERE task_id=?",
                        (task["task_id"],),
                    )
                    continue
                next_run = _next_occurrence(
                    json.loads(task["schedule_json"]), task["timezone"], now
                )
                connection.execute(
                    """
                    UPDATE automation_task SET status='active',pause_reason=NULL,next_run_at=?
                    WHERE task_id=?
                    """,
                    (_utc_iso(next_run), task["task_id"]),
                )
            del params  # params validated by the original authorization.
            return self._get_control(connection, "dispatcher_job_id")

    def revoke(
        self, subject_key: str, source_message_id: Optional[str] = None
    ) -> Optional[str]:
        now_text = _utc_iso(self.now_fn())
        with self._transaction() as connection:
            self._assert_subject(connection, subject_key)
            self._consume_control_event(
                connection, source_message_id, subject_key, "revoke"
            )
            authorization_id = self._get_control(connection, "authorization_id")
            job_id = self._get_control(connection, "dispatcher_job_id")
            if authorization_id:
                connection.execute(
                    "UPDATE authorization SET revoked_at=? WHERE authorization_id=? AND revoked_at IS NULL",
                    (now_text, authorization_id),
                )
            self._set_control(connection, "mode", "revoked", now_text)
            connection.execute(
                """
                UPDATE automation_task SET status='paused',pause_reason='authorization_revoked'
                WHERE status='active'
                """
            )
            return job_id

    def delete_all(
        self, subject_key: str, source_message_id: Optional[str] = None
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            self._assert_subject(connection, subject_key, allow_unbound=True)
            self._consume_control_event(
                connection, source_message_id, subject_key, "delete"
            )
            job_id = self._get_control(connection, "dispatcher_job_id")
            tables = (
                "authorization",
                "observation_event",
                "state_item",
                "automation_task",
                "feedback_event",
                "decision_log",
                "dispatch_event",
                "replay_tombstone",
            )
            counts = {
                table: int(
                    connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                )
                for table in tables
            }
            # Child evidence is removed explicitly before its parent rows.
            connection.execute("DELETE FROM state_evidence")
            connection.execute("DELETE FROM feedback_event")
            connection.execute("DELETE FROM automation_task")
            connection.execute("DELETE FROM state_item")
            connection.execute("DELETE FROM observation_event")
            connection.execute("DELETE FROM decision_log")
            connection.execute("DELETE FROM dispatch_event")
            connection.execute("DELETE FROM replay_tombstone")
            connection.execute("DELETE FROM authorization")
            connection.execute("DELETE FROM control_state")
            connection.execute(
                "INSERT INTO deletion_audit VALUES(?,?,?)",
                (_uuid(), _utc_iso(self.now_fn()), _json(counts)),
            )
        # secure_delete overwrites deleted cells; VACUUM rebuilds the file so
        # freed pages cannot retain recoverable health payload bytes.
        with contextlib.closing(self._connect()) as connection:
            connection.execute("VACUUM")
        return {"dispatcher_job_id": job_id, "deleted_counts": counts}

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        subject_key: str,
        event_id: str,
        event_key: str,
        payload: dict[str, Any],
        schema_state: str,
        now: dt.datetime,
        retention_days: int,
        correction_of: Optional[str] = None,
    ) -> None:
        now_text = _utc_iso(now)
        connection.execute(
            """
            INSERT INTO observation_event VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                subject_key,
                "structured_user_observation",
                "verified_private_self",
                "self",
                event_key,
                now_text,
                now_text,
                _json(payload),
                schema_state,
                correction_of,
                _utc_iso(now + dt.timedelta(days=retention_days)),
                event_key,
            ),
        )

    @staticmethod
    def _upsert_state(
        connection: sqlite3.Connection,
        *,
        subject_key: str,
        domain: str,
        state_key: str,
        value: dict[str, Any],
        evidence_state: str,
        event_id: str,
        now: dt.datetime,
        ttl_days: int,
        rule_id: str,
    ) -> str:
        if evidence_state not in EVIDENCE_STATES:
            raise ValueError("invalid evidence state")
        previous = connection.execute(
            """
            SELECT item_id FROM state_item
            WHERE subject_key=? AND domain=? AND state_key=? AND lifecycle='active'
            ORDER BY created_at DESC LIMIT 1
            """,
            (subject_key, domain, state_key),
        ).fetchone()
        previous_id = previous["item_id"] if previous else None
        if previous_id:
            connection.execute(
                "UPDATE state_item SET lifecycle='superseded' WHERE item_id=?",
                (previous_id,),
            )
        item_id = _uuid()
        connection.execute(
            """
            INSERT INTO state_item VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item_id,
                subject_key,
                domain,
                state_key,
                _json(value),
                "active",
                evidence_state,
                1,
                1,
                _utc_iso(now),
                _utc_iso(now + dt.timedelta(days=ttl_days)),
                rule_id,
                "2.0",
                previous_id,
                _utc_iso(now),
            ),
        )
        connection.execute(
            "INSERT INTO state_evidence VALUES(?,?,?)", (item_id, event_id, "supports")
        )
        if previous_id:
            # Dependent tasks follow the current revision of the same state key
            # so a later correction invalidates the task's actual evidence.
            connection.execute(
                "UPDATE automation_task SET trigger_item_id=? WHERE trigger_item_id=?",
                (item_id, previous_id),
            )
        return item_id

    @staticmethod
    def _parse_structured_candidates(text: str, now: dt.datetime) -> dict[str, Any]:
        compact = re.sub(r"\s+", "", text)
        result: dict[str, list[dict[str, Any]]] = {
            "profile": [],
            "preferences": [],
            "invalid": [],
        }
        if re.search(
            r"(?:服务器|系统|项目|数据集|论文|药店|库存|测试|举例|"
            r"假设|如果|假如|要是|科普|引用|翻译|改写|文案)",
            compact,
        ) or re.search(r"[‘’“”\"'《》]", compact):
            return result

        # Explicit interaction instructions are attributable to the verified
        # private sender even when Chinese naturally omits the pronoun “我”.
        preference_rules = (
            (r"(?:回复|回答)(?:短点|简短点|简短一点)", "response_length", "short"),
            (r"(?:回复|回答)(?:详细点|详细一点|多一点)", "response_length", "detailed"),
            (r"(?:语气温柔一点|说得温柔一点|说得温柔)", "tone", "warm"),
            (r"(?:语气直接一点|直接一点|直说|别绕弯)", "tone", "direct"),
            (r"一次(?:只)?问一个", "question_count", "one"),
        )
        clauses = [
            clause for clause in re.split(r"[，,。.!！；;]+", compact) if clause
        ]
        for pattern, key, value in preference_rules:
            if any(re.fullmatch(pattern, clause) for clause in clauses):
                result["preferences"].append(
                    {
                        "state_key": key,
                        "value": {"value": value, "source_kind": "explicit_preference"},
                        "evidence_state": "explicit",
                        "ttl_days": 180,
                        "rule_id": "preference.explicit",
                    }
                )

        # A verified sender may talk about relatives.  That text can still
        # carry an interaction preference, but it is never her health profile.
        if re.search(
            r"(?:我妈|我爸|我父亲|我母亲|我女朋友|我男朋友|我家人|我朋友|"
            r"(?:她|他|别人|朋友|妈妈|爸爸)(?:说|想|需要|总|最近|现在))",
            compact,
        ):
            return result
        if not re.search(r"(?:^|[，。！？,.!?])?(?:我|本人)", compact):
            return result
        # Long-lived health facts require an affirmative personal assertion,
        # not a question or a statement that the reading/report is invalid.
        if re.search(r"(?:是否|是不是|吗|么|[?？])", compact):
            return result
        if re.search(r"(?:不准确|不准|误测|测错|设备坏了|仪器坏了|别人的)", compact):
            return result
        if re.fullmatch(
            r"我(?:最近|这几天|今晚|现在)?(?:睡不着|入睡困难|总醒|睡不好)"
            r"[。.!！]?",
            compact,
        ):
            result["profile"].append(
                {
                    "state_key": "sleep.current_self_report",
                    "value": {
                        "kind": "current_sleep_difficulty",
                        "representation": "本人自述近期睡眠困扰",
                        "source_kind": "self_report",
                        "reported_at": _utc_iso(now),
                    },
                    "evidence_state": "explicit",
                    "ttl_days": 1,
                    "rule_id": "profile.sleep.self_report",
                }
            )

        allergy = None
        if not re.search(
            r"(?:不|没(?:有)?|无|未|从未|否认|并非|不是).{0,20}过敏",
            compact,
        ):
            allergy = re.fullmatch(
                r"我(?:确实)?(?:对)?"
                r"(?P<item>[\u4e00-\u9fa5A-Za-z0-9、及和]{1,32}?)"
                r"(?:会)?过敏(?:反应)?[。.!！]?",
                compact,
            )
        if allergy:
            allergy_items = [
                item for item in re.split(r"(?:、|以及|及|和)", allergy.group("item"))
                if item
            ]
            denied_tokens = ("不", "没", "无", "未", "从未", "否认", "并非", "不是")
            if 1 <= len(allergy_items) <= 5 and not any(
                token in item for item in allergy_items for token in denied_tokens
            ):
                for allergy_item in allergy_items:
                    item_key = hashlib.sha256(
                        allergy_item.encode("utf-8")
                    ).hexdigest()[:12]
                    result["profile"].append(
                        {
                            "state_key": f"allergy.self_report.{item_key}",
                            "value": {
                                "kind": "reported_allergy",
                                "item": allergy_item,
                                "source_kind": "self_report",
                                "representation": "本人自述过敏信息，未经系统诊断",
                            },
                            "evidence_state": "explicit",
                            "ttl_days": 180,
                            "rule_id": "profile.allergy.self_report",
                        }
                    )

        doctor = re.search(
            r"医生(?:说|告诉我)(?:我)?(?P<label>[\u4e00-\u9fa5A-Za-z0-9]{1,20})", compact
        )
        if doctor:
            label = doctor.group("label")
            label = re.split(r"[，。！？,.!?；;]", label)[0][:20]
            result["profile"].append(
                {
                    "state_key": "doctor_opinion.self_report",
                    "value": {
                        "kind": "self_reported_doctor_opinion",
                        "reported_label": label,
                        "source_kind": "self_reported_doctor",
                        "representation": "本人转述医生意见；系统未独立核验或诊断",
                    },
                    "evidence_state": "explicit",
                    "ttl_days": 180,
                    "rule_id": "profile.doctor_opinion.self_report",
                }
            )

        measurement_markers = ("血压", "血糖", "心率", "体温")
        if any(marker in compact for marker in measurement_markers):
            time_known = bool(re.search(r"刚测|刚刚|现在|今天", compact))
            valid_measurement: Optional[dict[str, Any]] = None
            bp = re.search(r"血压(?:是|为)?(\d{2,3})/(\d{2,3})(?:mmhg|毫米汞柱)", compact, re.I)
            glucose = re.search(r"血糖(?:是|为)?(\d{1,2}(?:\.\d+)?)mmol/l", compact, re.I)
            heart = re.search(r"心率(?:是|为)?(\d{2,3})(?:次/分钟|bpm)", compact, re.I)
            temp = re.search(r"体温(?:是|为)?(\d{2}(?:\.\d+)?)(?:℃|摄氏度)", compact)
            if (
                bp
                and time_known
                and 30 <= int(bp.group(1)) <= 300
                and 20 <= int(bp.group(2)) <= 200
                and int(bp.group(1)) > int(bp.group(2))
            ):
                valid_measurement = {
                    "state_key": "measurement.blood_pressure.latest",
                    "value": {
                        "measurement_type": "blood_pressure",
                        "systolic": int(bp.group(1)),
                        "diastolic": int(bp.group(2)),
                        "unit": "mmHg",
                        "occurred_at": _utc_iso(now),
                        "time_basis": "self_reported_current_or_today",
                    },
                }
            elif glucose and time_known and 0.5 <= float(glucose.group(1)) <= 50.0:
                valid_measurement = {
                    "state_key": "measurement.blood_glucose.latest",
                    "value": {
                        "measurement_type": "blood_glucose",
                        "value": float(glucose.group(1)),
                        "unit": "mmol/L",
                        "occurred_at": _utc_iso(now),
                        "time_basis": "self_reported_current_or_today",
                    },
                }
            elif heart and time_known and 20 <= int(heart.group(1)) <= 300:
                valid_measurement = {
                    "state_key": "measurement.heart_rate.latest",
                    "value": {
                        "measurement_type": "heart_rate",
                        "value": int(heart.group(1)),
                        "unit": "beats/minute",
                        "occurred_at": _utc_iso(now),
                        "time_basis": "self_reported_current_or_today",
                    },
                }
            elif temp and time_known and 25.0 <= float(temp.group(1)) <= 45.0:
                valid_measurement = {
                    "state_key": "measurement.body_temperature.latest",
                    "value": {
                        "measurement_type": "body_temperature",
                        "value": float(temp.group(1)),
                        "unit": "degree_Celsius",
                        "occurred_at": _utc_iso(now),
                        "time_basis": "self_reported_current_or_today",
                    },
                }
            if valid_measurement:
                valid_measurement.update(
                    {
                        "evidence_state": "single",
                        "ttl_days": 7,
                        "rule_id": "profile.measurement.typed",
                    }
                )
                result["profile"].append(valid_measurement)
            else:
                result["invalid"].append(
                    {
                        "kind": "measurement",
                        "reason": "measurement_requires_type_value_unit_and_time",
                    }
                )

        return result

    @staticmethod
    def _task_trigger(text: str) -> Optional[str]:
        compact = re.sub(r"\s+", "", text)
        if re.search(
            r"(?:测试用例|测试一下|举例|假设|如果有人|科普|引用|"
            r"服务器|系统|项目|数据集|论文|文案|翻译|改写)",
            compact,
        ):
            return None
        if re.search(r"[‘’“”\"'《》]", compact):
            return None
        if re.search(r"(?:不要|别|不用|停止|取消).{0,8}(?:提醒|喝水|休息|活动)", compact):
            return None
        if re.search(
            r"(?:我妈|我爸|我父亲|我母亲|我女朋友|我男朋友|我家人|我朋友|"
            r"(?:她|他|别人|朋友|妈妈|爸爸)(?:说|想|需要|总|最近|现在))",
            compact,
        ):
            return None
        polite = r"(?:请|麻烦|可以|能不能)?"
        suffix = r"(?:吧|好吗|可以吗)?[。.!！?？]?"
        rules = (
            (
                "hydration_cue",
                rf"(?:我(?:总忘记喝水|喝水太少)|{polite}提醒我喝水{suffix})",
            ),
            (
                "wind_down",
                rf"(?:我(?:想早点睡|总熬夜|睡得太晚)|{polite}提醒我(?:早点休息|睡觉){suffix})",
            ),
            (
                "movement_cue",
                rf"(?:我(?:久坐|总忘记活动)|{polite}提醒我(?:活动|起来走走){suffix})",
            ),
        )
        for category, pattern in rules:
            if re.fullmatch(pattern, compact):
                return category
        return None

    @staticmethod
    def _feedback_kind(text: str) -> Optional[str]:
        compact = re.sub(r"\s+", "", text)
        if re.search(
            r"(?:测试用例|测试一下|举例|假设|如果有人|科普|引用|"
            r"服务器|系统|项目|数据集|论文|文案|翻译|改写)",
            compact,
        ):
            return None
        if re.search(r"[‘’“”\"'《》]", compact):
            return None
        if re.search(
            r"(?:我妈|我爸|我父亲|我母亲|我女朋友|我男朋友|我家人|我朋友|"
            r"(?:她|他|别人|朋友|妈妈|爸爸)(?:说|想|需要|总|最近|现在))",
            compact,
        ):
            return None
        category = r"(?:喝水|补水|早点休息|睡觉|休息|作息|久坐|活动|起来走走)?"
        ending = r"(?:了|吧|好吗)?[。.!！?？]?"
        rules = (
            (
                "stop",
                rf"(?:(?:不要|不用|别|别再|停止)(?:再)?提醒我?{category}|"
                rf"取消{category}提醒){ending}",
            ),
            (
                "skip_today",
                rf"今天(?:先)?(?:不要|不用|别)提醒我?{category}{ending}",
            ),
            (
                "snooze",
                rf"(?:(?:这个|{category})?提醒晚点(?:再)?提醒|"
                rf"晚点(?:再)?提醒我?{category}){ending}",
            ),
            (
                "less_frequent",
                rf"(?:{category}提醒|提醒我?{category})太频繁{ending}",
            ),
            (
                "too_early",
                rf"(?:{category}提醒|提醒我?{category})太早{ending}",
            ),
            (
                "too_late",
                rf"(?:{category}提醒|提醒我?{category})太晚{ending}",
            ),
        )
        for kind, pattern in rules:
            if re.fullmatch(pattern, compact):
                return kind
        return None

    @staticmethod
    def _feedback_category(text: str) -> Optional[str]:
        compact = re.sub(r"\s+", "", text)
        matches = []
        if re.search(r"喝水|补水", compact):
            matches.append("hydration_cue")
        if re.search(r"睡觉|休息|作息|熬夜", compact):
            matches.append("wind_down")
        if re.search(r"久坐|活动|走走", compact):
            matches.append("movement_cue")
        return matches[0] if len(set(matches)) == 1 else None

    @staticmethod
    def _target_task(
        connection: sqlite3.Connection,
        subject_key: str,
        category: Optional[str],
    ) -> Optional[sqlite3.Row]:
        if category:
            return connection.execute(
                """
                SELECT * FROM automation_task
                WHERE subject_key=? AND category=? AND status IN ('active','paused')
                ORDER BY COALESCE(last_dispatched_at,created_at) DESC LIMIT 1
                """,
                (subject_key, category),
            ).fetchone()
        rows = connection.execute(
            """
            SELECT * FROM automation_task
            WHERE subject_key=? AND status='active'
            ORDER BY COALESCE(last_dispatched_at,created_at) DESC LIMIT 1
            """,
            (subject_key,),
        ).fetchall()
        # Ambiguous feedback never mutates an arbitrary task.
        active_count = connection.execute(
            "SELECT COUNT(*) AS n FROM automation_task WHERE subject_key=? AND status='active'",
            (subject_key,),
        ).fetchone()["n"]
        return rows[0] if int(active_count) == 1 and rows else None

    def _apply_feedback(
        self,
        connection: sqlite3.Connection,
        subject_key: str,
        event_id: str,
        event_key: str,
        feedback_kind: str,
        target_category: Optional[str],
        policy: dict[str, Any],
        now: dt.datetime,
    ) -> list[dict[str, Any]]:
        task = self._target_task(connection, subject_key, target_category)
        if not task:
            return [{"action": "feedback_not_applied", "reason": "task_binding_required"}]
        feedback_id = _uuid()
        connection.execute(
            """
            INSERT INTO feedback_event VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                feedback_id,
                task["task_id"],
                event_id,
                feedback_kind,
                _utc_iso(now),
                _local_date(now, task["timezone"]),
                1,
                f"feedback:{event_key}:{feedback_kind}",
            ),
        )
        actions: list[dict[str, Any]] = []
        if feedback_kind == "stop":
            connection.execute(
                "UPDATE automation_task SET status='paused',pause_reason='self_stop' WHERE task_id=?",
                (task["task_id"],),
            )
            actions.append({"action": "paused", "category": task["category"], "reason": "self_stop"})
        elif feedback_kind == "skip_today":
            zone = _zone(task["timezone"])
            tomorrow = now.astimezone(zone).date() + dt.timedelta(days=1)
            boundary = dt.datetime.combine(tomorrow, dt.time(0, 0), tzinfo=zone)
            schedule = json.loads(task["schedule_json"])
            next_run = _next_occurrence(
                schedule,
                task["timezone"],
                boundary.astimezone(dt.timezone.utc) - dt.timedelta(seconds=1),
            )
            connection.execute(
                "UPDATE automation_task SET suppressed_until=?,next_run_at=? WHERE task_id=?",
                (
                    _utc_iso(boundary.astimezone(dt.timezone.utc)),
                    _utc_iso(next_run),
                    task["task_id"],
                ),
            )
            actions.append({"action": "skip_today", "category": task["category"]})
        elif feedback_kind == "snooze":
            shift = int(policy["max_schedule_shift_minutes"])
            next_run = max(_parse_utc(task["next_run_at"]), now) + dt.timedelta(minutes=shift)
            connection.execute(
                "UPDATE automation_task SET next_run_at=? WHERE task_id=?",
                (_utc_iso(next_run), task["task_id"]),
            )
            actions.append(
                {"action": "snoozed_once", "category": task["category"], "minutes": shift}
            )
        elif feedback_kind == "less_frequent":
            schedule = json.loads(task["schedule_json"])
            times = list(schedule.get("times", []))
            if len(times) > 1:
                schedule["times"] = [times[0]]
                next_run = _next_occurrence(schedule, task["timezone"], now)
                connection.execute(
                    """
                    UPDATE automation_task SET schedule_json=?,revision=revision+1,
                        next_run_at=?,last_adjusted_at=? WHERE task_id=?
                    """,
                    (_json(schedule), _utc_iso(next_run), _utc_iso(now), task["task_id"]),
                )
                actions.append({"action": "frequency_reduced", "category": task["category"]})
            else:
                connection.execute(
                    "UPDATE automation_task SET status='paused',pause_reason='frequency_feedback' WHERE task_id=?",
                    (task["task_id"],),
                )
                actions.append({"action": "paused", "category": task["category"], "reason": "frequency_feedback"})
        elif feedback_kind in {"too_early", "too_late"}:
            feedback_start = now - dt.timedelta(days=30)
            if task["last_adjusted_at"]:
                feedback_start = max(feedback_start, _parse_utc(task["last_adjusted_at"]))
            rows = connection.execute(
                """
                SELECT local_date FROM feedback_event
                WHERE task_id=? AND feedback_kind=? AND occurred_at>?
                """,
                (
                    task["task_id"],
                    feedback_kind,
                    _utc_iso(feedback_start),
                ),
            ).fetchall()
            count = len(rows)
            days = len({row["local_date"] for row in rows})
            opposite_kind = "too_late" if feedback_kind == "too_early" else "too_early"
            opposite_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS n FROM feedback_event
                    WHERE task_id=? AND feedback_kind=? AND occurred_at>?
                    """,
                    (task["task_id"], opposite_kind, _utc_iso(feedback_start)),
                ).fetchone()["n"]
            )
            if opposite_count:
                actions.append(
                    {
                        "action": "schedule_not_adjusted",
                        "category": task["category"],
                        "reason": "conflicting_explicit_time_feedback",
                    }
                )
                return actions
            adjusted_at = _parse_utc(task["last_adjusted_at"]) if task["last_adjusted_at"] else None
            if count >= 3 and days >= 2 and (
                adjusted_at is None or adjusted_at <= now - dt.timedelta(days=7)
            ):
                delta = int(policy["max_schedule_shift_minutes"])
                if feedback_kind == "too_early":
                    delta = abs(delta)
                else:
                    delta = -abs(delta)
                schedule = json.loads(task["schedule_json"])
                shifted = [_format_minutes(_clock_minutes(value) + delta) for value in schedule["times"]]
                quiet_start = _clock_minutes(policy["quiet_start"])
                quiet_end = _clock_minutes(policy["quiet_end"])
                if not any(
                    _in_quiet_minutes(_clock_minutes(value), quiet_start, quiet_end)
                    for value in shifted
                ):
                    schedule["times"] = shifted
                    next_run = _next_occurrence(schedule, task["timezone"], now)
                    connection.execute(
                        """
                        UPDATE automation_task SET schedule_json=?,revision=revision+1,
                            next_run_at=?,last_adjusted_at=? WHERE task_id=?
                        """,
                        (_json(schedule), _utc_iso(next_run), _utc_iso(now), task["task_id"]),
                    )
                    actions.append(
                        {
                            "action": "stable_time_adjustment",
                            "category": task["category"],
                            "minutes": delta,
                            "support_count": count,
                            "support_days": days,
                        }
                    )
        return actions

    def observe(
        self,
        text: str,
        source_message_id: str,
        subject_key: str,
        reply_to_message_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Apply one authenticated private message; raw text is never persisted."""
        if not source_message_id:
            return {"result": "ignored", "reason": "missing_platform_message_id"}
        now = self.now_fn()
        with self._transaction() as connection:
            if not self._get_control(connection, "subject_key"):
                return {"result": "ignored", "reason": "inactive_or_unauthorized"}
            try:
                self._assert_subject(connection, subject_key)
            except PermissionError:
                return {"result": "ignored", "reason": "data_subject_mismatch"}
            event_key = self._event_key(
                connection, source_message_id, subject_key, "message:structured"
            )
            self._purge_expired(connection, now)
            duplicate = connection.execute(
                "SELECT event_id FROM observation_event WHERE idempotency_key=?",
                (event_key,),
            ).fetchone()
            tombstone = connection.execute(
                "SELECT 1 FROM replay_tombstone WHERE idempotency_key=?",
                (event_key,),
            ).fetchone()
            durable_seen = connection.execute(
                "SELECT 1 FROM message_replay_ledger WHERE idempotency_key=?",
                (event_key,),
            ).fetchone()
            if duplicate or tombstone or durable_seen:
                return {"result": "duplicate", "reason": "platform_message_replay"}
            policy = self._active_policy(connection, now)
            if not policy:
                # After an authorization has existed, keep only a content-free
                # hash tombstone while paused/revoked/expired.  A replay cannot
                # turn into a new health action after resume.
                if self._get_control(connection, "authorization_id"):
                    connection.execute(
                        "INSERT OR IGNORE INTO replay_tombstone VALUES(?)",
                        (event_key,),
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO message_replay_ledger VALUES(?)",
                        (event_key,),
                    )
                return {"result": "ignored", "reason": "inactive_or_unauthorized"}

            correction_requested = bool(
                re.fullmatch(r"\s*不是我[，,]?是我妈[。.!！]?\s*", text)
            )
            correction = correction_requested
            candidates = self._parse_structured_candidates(text, now)
            profile_allowed = self._scope_allowed(
                connection, "structured_profile", now
            )
            preference_allowed = self._scope_allowed(
                connection, "interaction_learning", now
            )
            if not profile_allowed:
                correction = False
                candidates["profile"] = []
                candidates["invalid"] = []
            if not preference_allowed:
                candidates["preferences"] = []
            correction_of: Optional[str] = None
            if correction:
                if not reply_to_message_id:
                    return {
                        "result": "no_structured_change",
                        "actions": [
                            {
                                "action": "correction_not_applied",
                                "reason": "exact_reply_required",
                            }
                        ],
                    }
                reply_key = self._event_key(
                    connection,
                    reply_to_message_id,
                    subject_key,
                    "message:structured",
                )
                prior_event = connection.execute(
                    """
                    SELECT o.event_id FROM observation_event AS o
                    JOIN state_evidence AS e
                      ON e.event_id=o.event_id AND e.relation='supports'
                    JOIN state_item AS s
                      ON s.item_id=e.item_id AND s.domain='health_profile'
                     AND s.lifecycle='active'
                    WHERE o.source_ref_hash=? AND o.subject_key=?
                    LIMIT 1
                    """,
                    (reply_key, subject_key),
                ).fetchone()
                if not prior_event:
                    return {
                        "result": "no_structured_change",
                        "actions": [
                            {
                                "action": "correction_not_applied",
                                "reason": "reply_has_no_active_health_evidence",
                            }
                        ],
                    }
                correction_of = str(prior_event["event_id"])
            task_category = self._task_trigger(text)
            feedback_kind = self._feedback_kind(text)
            feedback_category = self._feedback_category(text) if feedback_kind else None
            has_material = bool(
                correction
                or candidates["profile"]
                or candidates["preferences"]
                or candidates["invalid"]
                or task_category
                or feedback_kind
            )
            if not has_material:
                return {"result": "no_structured_change", "actions": []}

            event_id = _uuid()
            schema_state = "invalid" if candidates["invalid"] and not (
                candidates["profile"] or candidates["preferences"]
            ) else "valid"
            payload = {
                "profile_candidates": candidates["profile"],
                "preference_candidates": candidates["preferences"],
                "invalid_candidates": candidates["invalid"],
                "task_candidate": task_category,
                "feedback_kind": feedback_kind,
                "feedback_category": feedback_category,
                "correction": correction,
            }
            self._insert_event(
                connection,
                subject_key,
                event_id,
                event_key,
                payload,
                schema_state,
                now,
                retention_days=int(policy["data_retention_days"]),
                correction_of=correction_of,
            )
            connection.execute(
                "INSERT INTO message_replay_ledger VALUES(?)",
                (event_key,),
            )
            actions: list[dict[str, Any]] = []

            if correction and profile_allowed:
                prior_items = connection.execute(
                    """
                    SELECT s.item_id,s.state_key FROM state_item AS s
                    JOIN state_evidence AS e ON e.item_id=s.item_id
                    WHERE s.domain='health_profile' AND s.lifecycle='active'
                      AND e.event_id=? AND e.relation='supports'
                    ORDER BY s.created_at DESC
                    """,
                    (correction_of,),
                ).fetchall()
                for prior in prior_items:
                    connection.execute(
                        "UPDATE state_item SET lifecycle='invalidated',evidence_state='invalid' WHERE item_id=?",
                        (prior["item_id"],),
                    )
                    connection.execute(
                        "INSERT INTO state_evidence VALUES(?,?,?)",
                        (prior["item_id"], event_id, "corrects"),
                    )
                    connection.execute(
                        """
                        UPDATE automation_task SET status='paused',pause_reason='trigger_corrected'
                        WHERE trigger_item_id=? AND status='active'
                        """,
                        (prior["item_id"],),
                    )
                    actions.append({"action": "profile_corrected", "state_key": prior["state_key"]})

            trigger_item_id: Optional[str] = None
            if self._scope_allowed(connection, "structured_profile", now) and not correction:
                for candidate in candidates["profile"]:
                    item_id = self._upsert_state(
                        connection,
                        subject_key=subject_key,
                        domain="health_profile",
                        event_id=event_id,
                        now=now,
                        **{
                            **candidate,
                            "ttl_days": min(
                                int(candidate["ttl_days"]),
                                int(policy["data_retention_days"]),
                            ),
                        },
                    )
                    trigger_item_id = trigger_item_id or item_id
                    actions.append(
                        {
                            "action": "profile_updated",
                            "state_key": candidate["state_key"],
                            "evidence_state": candidate["evidence_state"],
                        }
                    )

            if (
                task_category
                and not correction
                and self._scope_allowed(connection, "structured_profile", now)
            ):
                routine_labels = {
                    "hydration_cue": "本人表达经常忘记喝水或希望获得补水提示",
                    "wind_down": "本人表达希望改善作息收尾",
                    "movement_cue": "本人表达久坐或希望获得活动提示",
                }
                trigger_item_id = self._upsert_state(
                    connection,
                    subject_key=subject_key,
                    domain="health_profile",
                    state_key=f"routine.{task_category}.self_report",
                    value={
                        "kind": "self_chosen_routine_need",
                        "category": task_category,
                        "representation": routine_labels[task_category],
                        "source_kind": "self_report",
                    },
                    evidence_state="explicit",
                    event_id=event_id,
                    now=now,
                    ttl_days=min(
                        int(policy["task_ttl_days"]),
                        int(policy["data_retention_days"]),
                    ),
                    rule_id="profile.routine.self_report",
                )
                actions.append(
                    {
                        "action": "profile_updated",
                        "state_key": f"routine.{task_category}.self_report",
                        "evidence_state": "explicit",
                    }
                )

            if self._scope_allowed(connection, "interaction_learning", now):
                for candidate in candidates["preferences"]:
                    self._upsert_state(
                        connection,
                        subject_key=subject_key,
                        domain="interaction_preference",
                        event_id=event_id,
                        now=now,
                        **{
                            **candidate,
                            "ttl_days": min(
                                int(candidate["ttl_days"]),
                                int(policy["data_retention_days"]),
                            ),
                        },
                    )
                    actions.append(
                        {
                            "action": "preference_updated",
                            "state_key": candidate["state_key"],
                            "value": candidate["value"]["value"],
                            "evidence_state": "explicit",
                        }
                    )

            if feedback_kind:
                actions.extend(
                    self._apply_feedback(
                        connection,
                        subject_key,
                        event_id,
                        event_key,
                        feedback_kind,
                        feedback_category,
                        policy,
                        now,
                    )
                )

            if task_category and task_category in set(policy["categories"]):
                active_count = int(
                    connection.execute(
                        "SELECT COUNT(*) AS n FROM automation_task WHERE status='active'"
                    ).fetchone()["n"]
                )
                recent_count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) AS n FROM automation_task WHERE created_at>=?
                        """,
                        (_utc_iso(now - dt.timedelta(days=7)),),
                    ).fetchone()["n"]
                )
                existing = connection.execute(
                    "SELECT task_id,status FROM automation_task WHERE idempotency_key=?",
                    (f"task:{subject_key}:{task_category}",),
                ).fetchone()
                reason: Optional[str] = None
                if existing:
                    reason = "category_task_already_exists"
                elif active_count >= int(policy["max_active_tasks"]):
                    reason = "active_task_cap"
                elif recent_count >= int(policy.get("max_new_tasks_7d", 1)):
                    reason = "new_task_7d_cap"
                if reason:
                    actions.append(
                        {"action": "task_not_created", "category": task_category, "reason": reason}
                    )
                else:
                    schedule = {
                        "kind": "daily",
                        "times": list(policy["category_times"][task_category]),
                        "weekdays": list(range(7)),
                    }
                    next_run = _next_occurrence(schedule, policy["timezone"], now)
                    task_id = _uuid()
                    decision_id = _uuid()
                    expires = now + dt.timedelta(days=int(policy["task_ttl_days"]))
                    max_runs = int(policy["task_ttl_days"]) * len(schedule["times"])
                    connection.execute(
                        """
                        INSERT INTO decision_log VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            decision_id,
                            subject_key,
                            _utc_iso(now),
                            "task.low_risk_self_routine",
                            "2.0",
                            _json({"event_id": event_id, "trigger_item_id": trigger_item_id}),
                            "allowed",
                            "explicit_self_routine_with_scoped_authorization",
                            _json({"category": task_category, "schedule": schedule}),
                            "executed",
                            None,
                            f"decision:{event_key}:{task_category}",
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO automation_task(
                            task_id,subject_key,category,purpose,schedule_json,timezone,
                            status,trigger_item_id,revision,next_run_at,suppressed_until,
                            review_at,expires_at,created_at,last_dispatched_at,last_adjusted_at,
                            run_count,max_runs,created_by_decision_id,idempotency_key,pause_reason
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            task_id,
                            subject_key,
                            task_category,
                            "self_chosen_low_risk_routine",
                            _json(schedule),
                            policy["timezone"],
                            "active",
                            trigger_item_id,
                            1,
                            _utc_iso(next_run),
                            None,
                            _utc_iso(expires),
                            _utc_iso(expires),
                            _utc_iso(now),
                            None,
                            None,
                            0,
                            max_runs,
                            decision_id,
                            f"task:{subject_key}:{task_category}",
                            None,
                        ),
                    )
                    actions.append(
                        {
                            "action": "task_created",
                            "category": task_category,
                            "times": schedule["times"],
                            "expires_at": _utc_iso(expires),
                        }
                    )
            elif task_category:
                actions.append(
                    {
                        "action": "task_not_created",
                        "category": task_category,
                        "reason": "category_not_authorized",
                    }
                )

            if candidates["invalid"]:
                actions.append(
                    {
                        "action": "invalid_observation_not_promoted",
                        "reasons": [item["reason"] for item in candidates["invalid"]],
                    }
                )
            return {"result": "applied", "actions": actions}

    def _preference_values(self, connection: sqlite3.Connection, now: dt.datetime) -> dict[str, str]:
        rows = connection.execute(
            """
            SELECT state_key,value_json FROM state_item
            WHERE domain='interaction_preference' AND lifecycle='active' AND valid_until>?
            ORDER BY created_at
            """,
            (_utc_iso(now),),
        ).fetchall()
        return {row["state_key"]: json.loads(row["value_json"])["value"] for row in rows}

    def context_for_model(
        self,
        current_text: str,
        action_result: dict[str, Any],
        subject_key: str,
    ) -> str:
        """Return minimal ephemeral context; never the complete profile."""
        now = self.now_fn()
        with contextlib.closing(self._connect()) as connection:
            try:
                self._assert_subject(connection, subject_key)
            except PermissionError:
                return ""
            if not self._scope_allowed(connection, "minimal_model_context", now):
                return ""
            preferences = (
                self._preference_values(connection, now)
                if self._scope_allowed(connection, "interaction_learning", now)
                else {}
            )
            lines = [
                "[health-autonomy-v02 verified deterministic context]",
                "Treat all health items as sourced observations, never as a diagnosis.",
                "Never change medication, diagnose, or share with another person.",
            ]
            if preferences:
                lines.append("Interaction preferences: " + _json(preferences))
            actions = action_result.get("actions") or []
            if actions:
                lines.append("Deterministic actions already executed: " + _json(actions))
                lines.append("Briefly explain material actions; do not claim any action not listed.")

            relevant_prefixes: set[str] = set()
            if any(term in current_text for term in ("睡", "作息", "熬夜", "休息")):
                relevant_prefixes.update(("sleep.", "routine.wind_down."))
            if "过敏" in current_text:
                relevant_prefixes.add("allergy.")
            if any(term in current_text for term in ("医生", "诊断", "确诊")):
                relevant_prefixes.add("doctor_opinion.")
            measurement_map = {
                "血压": "measurement.blood_pressure.",
                "血糖": "measurement.blood_glucose.",
                "心率": "measurement.heart_rate.",
                "体温": "measurement.body_temperature.",
            }
            for term, prefix in measurement_map.items():
                if term in current_text:
                    relevant_prefixes.add(prefix)
            if any(term in current_text for term in ("喝水", "补水")):
                relevant_prefixes.add("routine.hydration_cue.")
            if any(term in current_text for term in ("久坐", "活动", "走走")):
                relevant_prefixes.add("routine.movement_cue.")
            if relevant_prefixes and self._scope_allowed(
                connection, "structured_profile", now
            ):
                rows = connection.execute(
                    """
                    SELECT state_key,value_json,evidence_state,valid_until
                    FROM state_item WHERE domain='health_profile' AND lifecycle='active'
                      AND valid_until>? ORDER BY created_at DESC LIMIT 16
                    """,
                    (_utc_iso(now),),
                ).fetchall()
                rows = [
                    row for row in rows
                    if any(row["state_key"].startswith(prefix) for prefix in relevant_prefixes)
                ][:4]
                if rows:
                    minimal = [
                        {
                            "key": row["state_key"],
                            "value": json.loads(row["value_json"]),
                            "evidence_state": row["evidence_state"],
                            "valid_until": row["valid_until"],
                        }
                        for row in rows
                    ]
                    lines.append("Minimum relevant structured observations: " + _json(minimal))
            return "\n".join(lines)

    def dispatch_due(self) -> str:
        """Claim due tasks at-most-once and return one fixed combined message."""
        now = self.now_fn()
        now_text = _utc_iso(now)
        with self._transaction() as connection:
            self._purge_expired(connection, now)
            policy = self._active_policy(connection, now)
            if not policy:
                return ""
            timezone_name = policy["timezone"]
            local_now = now.astimezone(_zone(timezone_name))
            local_minutes = local_now.hour * 60 + local_now.minute
            quiet_start = _clock_minutes(policy["quiet_start"])
            quiet_end = _clock_minutes(policy["quiet_end"])

            connection.execute(
                """
                UPDATE automation_task SET status='expired',pause_reason='ttl_expired'
                WHERE status='active' AND (expires_at<=? OR run_count>=max_runs)
                """,
                (now_text,),
            )
            due = connection.execute(
                """
                SELECT * FROM automation_task
                WHERE status='active' AND next_run_at<=?
                  AND (suppressed_until IS NULL OR suppressed_until<=?)
                ORDER BY next_run_at,created_at
                """,
                (now_text, now_text),
            ).fetchall()
            if not due:
                return ""

            if _in_quiet_minutes(local_minutes, quiet_start, quiet_end):
                defer_until = _quiet_end_after(now, timezone_name, quiet_end)
                for task in due:
                    connection.execute(
                        "UPDATE automation_task SET next_run_at=? WHERE task_id=?",
                        (_utc_iso(defer_until), task["task_id"]),
                    )
                return ""

            window_start = _utc_iso(now - dt.timedelta(hours=24))
            emissions = connection.execute(
                "SELECT emitted_at FROM dispatch_event WHERE emitted_at>? ORDER BY emitted_at",
                (window_start,),
            ).fetchall()
            if len(emissions) >= int(policy["max_proactive_messages_24h"]):
                earliest = _parse_utc(emissions[0]["emitted_at"]) + dt.timedelta(hours=24, minutes=1)
                for task in due:
                    connection.execute(
                        "UPDATE automation_task SET next_run_at=? WHERE task_id=?",
                        (_utc_iso(earliest), task["task_id"]),
                    )
                return ""

            last = connection.execute(
                "SELECT emitted_at FROM dispatch_event ORDER BY emitted_at DESC LIMIT 1"
            ).fetchone()
            if last:
                next_allowed = _parse_utc(last["emitted_at"]) + dt.timedelta(
                    minutes=int(policy["min_spacing_minutes"])
                )
                if next_allowed > now:
                    for task in due:
                        connection.execute(
                            "UPDATE automation_task SET next_run_at=? WHERE task_id=?",
                            (_utc_iso(next_allowed), task["task_id"]),
                        )
                    return ""

            claimed = list(due[: int(policy["max_active_tasks"])])
            categories: list[str] = []
            task_ids: list[str] = []
            for task in claimed:
                schedule = json.loads(task["schedule_json"])
                next_run = _next_occurrence(schedule, task["timezone"], now + dt.timedelta(seconds=1))
                connection.execute(
                    """
                    UPDATE automation_task SET next_run_at=?,last_dispatched_at=?,
                        run_count=run_count+1,suppressed_until=NULL WHERE task_id=?
                    """,
                    (_utc_iso(next_run), now_text, task["task_id"]),
                )
                categories.append(task["category"])
                task_ids.append(task["task_id"])

            preferences = (
                self._preference_values(connection, now)
                if self._scope_allowed(connection, "interaction_learning", now)
                else {}
            )
            message_catalog = (
                SHORT_MESSAGES
                if preferences.get("response_length") == "short"
                else FIXED_MESSAGES
            )
            messages = [message_catalog[category] for category in categories]
            prefix = "温柔提醒：" if preferences.get("tone") == "warm" else "健康管家："
            if preferences.get("tone") == "direct":
                prefix = "提醒："
            output = prefix + " ".join(messages)
            dispatch_id = _uuid()
            connection.execute(
                "INSERT INTO dispatch_event VALUES(?,?,?,?,?,?)",
                (
                    dispatch_id,
                    now_text,
                    _json(task_ids),
                    "emitted_to_cron",
                    "fixed_low_risk_combined",
                    f"dispatch:{now_text}:{','.join(sorted(task_ids))}",
                ),
            )
            return output


class HermesCronBridge:
    """Narrow wrapper around Hermes cron with an explicit verified origin.

    Plugin slash commands run before Hermes binds ``HERMES_SESSION_*``.  The
    origin is therefore passed directly to ``create_job`` from the trusted
    gateway event instead of relying on ambient process/session variables.
    """

    def __init__(
        self,
        cronjob_func: Optional[Callable[..., str]] = None,
        list_jobs_func: Optional[Callable[..., list[dict[str, Any]]]] = None,
        create_job_func: Optional[Callable[..., dict[str, Any]]] = None,
        notify_func: Optional[Callable[[], None]] = None,
    ) -> None:
        self._cronjob_func = cronjob_func
        self._list_jobs_func = list_jobs_func
        self._create_job_func = create_job_func
        self._notify_func = notify_func

    def _backend(
        self,
    ) -> tuple[
        Callable[..., str],
        Callable[..., list[dict[str, Any]]],
        Callable[..., dict[str, Any]],
        Callable[[], None],
    ]:
        if all(
            (
                self._cronjob_func,
                self._list_jobs_func,
                self._create_job_func,
                self._notify_func,
            )
        ):
            return (
                self._cronjob_func,
                self._list_jobs_func,
                self._create_job_func,
                self._notify_func,
            )
        from cron.jobs import create_job, list_jobs
        from tools.cronjob_tools import _notify_provider_jobs_changed_safe, cronjob

        return cronjob, list_jobs, create_job, _notify_provider_jobs_changed_safe

    @staticmethod
    def _parse_result(raw: str) -> dict[str, Any]:
        data = json.loads(raw)
        if not data.get("success"):
            raise RuntimeError(str(data.get("error") or "Hermes cron operation failed"))
        return data

    @staticmethod
    def _expected_job(job: dict[str, Any], routing: dict[str, str]) -> bool:
        schedule = job.get("schedule") or {}
        origin = job.get("origin") or {}
        repeat = job.get("repeat")
        repeat_ok = repeat is None or (
            isinstance(repeat, dict) and repeat.get("times") is None
        )
        return bool(
            job.get("name") == DISPATCH_JOB_NAME
            and job.get("prompt") == DISPATCH_JOB_PROMPT
            and job.get("script") == DISPATCH_JOB_SCRIPT
            and job.get("no_agent") is True
            and job.get("deliver") == "origin"
            and job.get("attach_to_session") is False
            and schedule.get("kind") == "interval"
            and int(schedule.get("minutes", 0)) == 5
            and repeat_ok
            and not job.get("skill")
            and not job.get("skills")
            and not job.get("context_from")
            and not job.get("enabled_toolsets")
            and not job.get("workdir")
            and not job.get("model")
            and not job.get("provider")
            and not job.get("base_url")
            and origin.get("platform") == routing.get("platform")
            and str(origin.get("chat_id") or "") == str(routing.get("chat_id") or "")
            and str(origin.get("thread_id") or "") == str(routing.get("thread_id") or "")
            and str(origin.get("user_id") or "") == str(routing.get("user_id") or "")
            and str(origin.get("chat_type") or "").lower() == "dm"
        )

    @staticmethod
    def _is_dispatcher_candidate(job: dict[str, Any]) -> bool:
        return bool(
            job.get("name") == DISPATCH_JOB_NAME
            or job.get("prompt") == DISPATCH_JOB_PROMPT
            or Path(str(job.get("script") or "")).name == DISPATCH_JOB_SCRIPT
        )

    def verify_runtime_dispatcher(
        self,
        current_job_id: Optional[str],
        current_job_fingerprint: Optional[str],
        managed_job_id: Optional[str],
        subject_key: Optional[str],
        route_matches: Callable[[dict[str, str]], bool],
    ) -> bool:
        """Verify the caller snapshot, unique managed job and delivery route."""
        if (
            not current_job_id
            or not current_job_fingerprint
            or not managed_job_id
            or not subject_key
        ):
            return False
        _, list_jobs, _, _ = self._backend()
        matches = [
            job
            for job in list_jobs(include_disabled=True)
            if self._is_dispatcher_candidate(job)
        ]
        if len(matches) != 1:
            return False
        job = matches[0]
        if not (
            str(job.get("id") or "")
            == str(current_job_id)
            == str(managed_job_id)
        ):
            return False
        origin = job.get("origin") or {}
        routing = {
            "platform": str(origin.get("platform") or ""),
            "chat_id": str(origin.get("chat_id") or ""),
            "thread_id": str(origin.get("thread_id") or ""),
            "user_id": str(origin.get("user_id") or ""),
            "chat_type": str(origin.get("chat_type") or "").lower(),
        }
        try:
            bound = routing_subject_key(routing)
        except ValueError:
            return False
        return bool(
            bound == subject_key
            and route_matches(routing)
            and self._expected_job(job, routing)
            and job.get("enabled", True)
            and job.get("state") != "paused"
            and hmac.compare_digest(
                runtime_job_fingerprint(job),
                str(current_job_fingerprint).strip().lower(),
            )
        )

    def verify_configured_dispatcher(
        self,
        managed_job_id: Optional[str],
        subject_key: Optional[str],
        route_matches: Callable[[dict[str, str]], bool],
    ) -> bool:
        """Check stored configuration for status without claiming a run snapshot."""
        if not managed_job_id or not subject_key:
            return False
        _, list_jobs, _, _ = self._backend()
        matches = [
            job
            for job in list_jobs(include_disabled=True)
            if self._is_dispatcher_candidate(job)
        ]
        if len(matches) != 1:
            return False
        job = matches[0]
        if str(job.get("id") or "") != str(managed_job_id):
            return False
        origin = job.get("origin") or {}
        routing = {
            "platform": str(origin.get("platform") or ""),
            "chat_id": str(origin.get("chat_id") or ""),
            "thread_id": str(origin.get("thread_id") or ""),
            "user_id": str(origin.get("user_id") or ""),
            "chat_type": str(origin.get("chat_type") or "").lower(),
        }
        try:
            bound = routing_subject_key(routing)
        except ValueError:
            return False
        return bool(
            bound == subject_key
            and route_matches(routing)
            and self._expected_job(job, routing)
            and job.get("enabled", True)
            and job.get("state") != "paused"
        )

    def ensure_dispatcher(self, routing: dict[str, str]) -> tuple[str, bool]:
        required = {"platform", "chat_id", "user_id"}
        if not required.issubset(routing) or any(not routing[key] for key in required):
            raise RuntimeError("缺少经过验证的健康提醒投递来源")
        if routing.get("platform") != "telegram":
            raise RuntimeError("健康自治首版只允许 partner Telegram 私聊来源")
        cronjob, list_jobs, create_job, notify = self._backend()
        matches = [
            job for job in list_jobs(include_disabled=True)
            if self._is_dispatcher_candidate(job)
        ]
        if len(matches) > 1:
            raise RuntimeError("发现多个健康自治调度器，拒绝继续")
        if matches:
            job = matches[0]
            if not self._expected_job(job, routing):
                raise RuntimeError("现有健康自治调度器指纹不匹配，拒绝复用")
            if not job.get("enabled", True) or job.get("state") == "paused":
                self._parse_result(cronjob(action="resume", job_id=job["id"]))
            return str(job["id"]), False
        job = create_job(
            prompt=DISPATCH_JOB_PROMPT,
            schedule=DISPATCH_JOB_SCHEDULE,
            name=DISPATCH_JOB_NAME,
            repeat=None,
            deliver="origin",
            origin={
                "platform": routing["platform"],
                "chat_id": routing["chat_id"],
                "thread_id": routing.get("thread_id") or None,
                "user_id": routing["user_id"],
                "chat_type": "dm",
            },
            script=DISPATCH_JOB_SCRIPT,
            no_agent=True,
            attach_to_session=False,
        )
        notify()
        return str(job["id"]), True

    def pause(self, job_id: Optional[str], reason: str) -> None:
        if not job_id:
            return
        cronjob, _, _, _ = self._backend()
        self._parse_result(cronjob(action="pause", job_id=job_id, reason=reason))

    def resume(self, job_id: Optional[str]) -> None:
        if not job_id:
            raise RuntimeError("缺少健康自治调度器 ID")
        cronjob, _, _, _ = self._backend()
        self._parse_result(cronjob(action="resume", job_id=job_id))

    def remove(self, job_id: Optional[str]) -> None:
        if not job_id:
            return
        cronjob, _, _, _ = self._backend()
        self._parse_result(cronjob(action="remove", job_id=job_id))


class HealthAutonomyEngine:
    def __init__(
        self,
        store: Optional[HealthAutonomyStore] = None,
        cron: Optional[HermesCronBridge] = None,
    ) -> None:
        self.store = store or HealthAutonomyStore()
        self.cron = cron or HermesCronBridge()
        self._mutation_lock = threading.RLock()

    def activate(
        self,
        text: str,
        source_message_id: str,
        routing: dict[str, str],
    ) -> str:
        config = parse_activation(text)
        subject_key = routing_subject_key(routing)
        with self._mutation_lock:
            self.store.assert_activation_subject(subject_key)
            if self.store.control_event_seen(source_message_id, "activate", subject_key):
                return "这条本人授权已处理过；删除或撤销后也不会因旧消息重放而重新开启。"
            job_id: Optional[str] = None
            created = False
            try:
                job_id, created = self.cron.ensure_dispatcher(routing)
                result = self.store.activate(
                    config,
                    source_message_id,
                    job_id,
                    subject_key,
                    dispatcher_routing=routing,
                )
                if result["duplicate"] and created and job_id:
                    self.cron.remove(job_id)
                    created = False
            except DataSubjectMismatch:
                if created and job_id:
                    try:
                        self.cron.remove(job_id)
                    except Exception:
                        pass
                raise
            except Exception:
                try:
                    self.store.quarantine_dispatcher(
                        "dispatcher_activation_check_failed",
                        expected_subject_key=subject_key,
                    )
                except Exception:
                    pass
                if created and job_id:
                    try:
                        self.cron.remove(job_id)
                    except Exception:
                        pass
                raise
        if result["duplicate"]:
            return "这条本人授权已处理过，没有重复创建任务或调度器。"
        labels = "、".join(CATEGORY_LABELS[item] for item in config.categories)
        return (
            f"健康管家自治模式已开启：允许结构化画像={config.structured_profile}，"
            f"交互学习={config.interaction_learning}，最小模型使用={config.minimal_model_context}；"
            f"自治类别为{labels}。任意连续24小时最多{config.max_proactive_messages_24h}条主动消息，"
            f"两条至少间隔{config.min_spacing_minutes}分钟，静默时段{config.quiet_start}-{config.quiet_end}，"
            f"单个任务最长{config.task_ttl_days}天。开启最小模型使用意味着当前服务器管理员和已配置的"
            f"模型供应商可能接触每轮所需的最少字段；不会注入完整画像。可随时暂停、关闭或删除数据。"
        )

    def control(
        self,
        action: str,
        routing: dict[str, str],
        source_message_id: Optional[str] = None,
    ) -> str:
        with self._mutation_lock:
            try:
                return self._control_locked(action, routing, source_message_id)
            except DuplicateControlEvent:
                return "这条本人控制消息已处理过；没有再次改变健康管家状态。"

    def _control_locked(
        self,
        action: str,
        routing: dict[str, str],
        source_message_id: Optional[str],
    ) -> str:
        subject_key = routing_subject_key(routing)
        if action == "status":
            status = self.store.status(subject_key)
            mode_labels = {
                "inactive": "未开启",
                "active": "运行中",
                "paused": "本人暂停",
                "revoked": "本人已撤销授权",
                "expired": "授权已过期",
                "paused_integrity": "完整性检查失败并已隔离",
            }
            mode_text = mode_labels.get(status["mode"], status["mode"])
            if status["mode"] == "inactive" and not status["stored_payload_rows"]:
                return (
                    "健康管家自治模式未开启，当前没有健康载荷、画像、偏好或任务；"
                    "开启时必须由本人在私聊中给出完整授权参数。"
                )
            policy = status["policy"]
            housekeeping_verified = False
            if status["housekeeping_configured"]:
                try:
                    housekeeping_verified = self.cron.verify_configured_dispatcher(
                        status["dispatcher_job_id"],
                        subject_key,
                        self.store.dispatcher_route_matches,
                    )
                except Exception:
                    housekeeping_verified = False
            tasks = status["tasks"]
            active = [task for task in tasks if task["status"] == "active"]
            task_text = "、".join(
                f"{CATEGORY_LABELS.get(task['category'], task['category'])}({task['status']})"
                for task in tasks
            ) or "无"
            policy_text = ""
            if policy:
                policy_text = (
                    f"最近授权参数：任意连续24小时最多"
                    f"{policy['max_proactive_messages_24h']}条，最短间隔"
                    f"{policy['min_spacing_minutes']}分钟，静默"
                    f"{policy['quiet_start']}-{policy['quiet_end']}。"
                )
            output_state = "允许投递" if status["can_dispatch"] else "禁止投递"
            housekeeping = ""
            if status["housekeeping_configured"] and not status["can_dispatch"]:
                housekeeping = (
                    "固定清理调度器指纹本次已核验"
                    if housekeeping_verified
                    else "数据库保留清理调度器配置，但本次未核验为可运行"
                )
            counts = status["stored_counts"]
            stored_text = (
                f"授权{counts['authorizations']}、观察{counts['observations']}、"
                f"状态项{counts['state_items']}、任务{counts['tasks']}、"
                f"反馈{counts['feedback']}、决策{counts['decisions']}、"
                f"投递记录{counts['dispatches']}"
            )
            return (
                f"当前模式：{mode_text}；{output_state}；仍保存：{stored_text}；活跃画像条目"
                f"{status['active_state_items']}项；自治任务{task_text}，当前活跃"
                f"{len(active)}个。{policy_text}{housekeeping}"
            )
        if action == "pause":
            self.store.pause(
                subject_key,
                "self_pause",
                source_message_id=source_message_id,
            )
            return (
                "自治判断和主动提醒已暂停；固定调度器仅继续执行无投递的数据到期清理，"
                "急症与用药安全规则仍然有效。"
            )
        if action == "resume":
            self.store.resume(subject_key, source_message_id=source_message_id)
            return "自治模式已恢复；已到期、本人停止或证据被纠正的任务不会自动复活。"
        if action == "revoke":
            self.store.revoke(subject_key, source_message_id=source_message_id)
            return (
                "本人授权已撤销，画像不再读取或写入，自治输出已停止；"
                "固定调度器仅继续执行无投递的数据到期清理。"
            )
        if action == "delete":
            result = self.store.delete_all(
                subject_key, source_message_id=source_message_id
            )
            try:
                self.cron.remove(result["dispatcher_job_id"])
            except Exception:
                return "健康载荷、画像、偏好和任务已删除；cron 删除失败但已无数据可投递，需要管理员检查。"
            return (
                "健康载荷、画像、偏好、任务和调度器已删除；仅保留不含身份、健康内容或原消息时间的"
                "不透明防重放 HMAC，以及只含删除时间和各表计数的删除审计。"
            )
        raise ValueError("未知健康管家控制动作")

    def observe(
        self,
        text: str,
        source_message_id: str,
        routing: dict[str, str],
        reply_to_message_id: Optional[str] = None,
    ) -> tuple[dict[str, Any], str]:
        subject_key = routing_subject_key(routing)
        result = self.store.observe(
            text,
            source_message_id,
            subject_key,
            reply_to_message_id=reply_to_message_id,
        )
        return result, self.store.context_for_model(text, result, subject_key)


__all__ = [
    "ACTIVATION_PREFIX",
    "CONTROL_EXACT",
    "ActivationConfig",
    "HealthAutonomyEngine",
    "HealthAutonomyStore",
    "HermesCronBridge",
    "activation_example",
    "parse_activation",
    "routing_subject_key",
    "runtime_job_fingerprint",
]

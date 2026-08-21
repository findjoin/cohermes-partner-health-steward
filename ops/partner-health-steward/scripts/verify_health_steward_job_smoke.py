"""Run the two fixed Jobs once and verify their fresh-session sidecar path."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from health_model import HealthModelConfig  # noqa: E402
from hermes_jobs import fixed_job_specs, job_matches_spec  # noqa: E402
from sidecar.adapter import PartnerHealthAdapter  # noqa: E402


OWNER_TIMEZONE = "Asia/Shanghai"
SUBJECT = "profile"


def _owner_zone() -> dt.tzinfo:
    try:
        return ZoneInfo(OWNER_TIMEZONE)
    except ZoneInfoNotFoundError:
        return dt.timezone(dt.timedelta(hours=8), name=OWNER_TIMEZONE)


def _event_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        name = str(event.get("event", ""))
        counts[name] = counts.get(name, 0) + 1
    return counts


def _cron_session_ids(state_db: Path) -> set[str]:
    if not state_db.is_file():
        raise RuntimeError("hermes-state-db-unavailable")
    try:
        with sqlite3.connect(f"file:{state_db}?mode=ro", uri=True) as connection:
            return {
                str(row[0])
                for row in connection.execute(
                    "SELECT id FROM sessions WHERE id LIKE 'cron_%';"
                ).fetchall()
            }
    except sqlite3.Error as exc:
        raise RuntimeError("failed-read-cron-sessions") from exc


def _fixed_specs():
    config_path = os.environ.get("HEALTH_STEWARD_HEALTH_MODEL_CONFIG", "").strip()
    if not config_path:
        raise RuntimeError("health-model-config-unavailable")
    try:
        return fixed_job_specs(HealthModelConfig.from_file(config_path))
    except Exception as exc:
        raise RuntimeError("health-model-config-unavailable") from exc


def _fixed_records() -> dict[str, dict[str, Any]]:
    from cron import jobs

    records = list(jobs.list_jobs(include_disabled=True))
    health = [
        record
        for record in records
        if str(record.get("name", "")).lower().startswith(("health-", "health_"))
    ]
    specs = _fixed_specs()
    if len(health) != 2:
        raise RuntimeError(f"expected-two-health-jobs-found-{len(health)}")
    by_name = {str(record.get("name")): record for record in health}
    if any(not job_matches_spec(by_name.get(spec.name, {}), spec) for spec in specs):
        raise RuntimeError("fixed-health-job-contract-drift")
    return by_name


def _parse_aware(value: Any) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _ran_today(record: dict[str, Any], now: dt.datetime) -> bool:
    last_run = _parse_aware(record.get("last_run_at"))
    if last_run is None or record.get("last_status") != "ok":
        return False
    zone = _owner_zone()
    return last_run.astimezone(zone).date() == now.astimezone(zone).date()


def _has_current_daily_audit(
    events: list[dict[str, Any]], now: dt.datetime
) -> bool:
    zone = _owner_zone()
    local_date = now.astimezone(zone).date().isoformat()
    snapshot = False
    outcome = False
    for event in events:
        details = event.get("details")
        if not isinstance(details, dict) or details.get("subject") != SUBJECT:
            continue
        event_utc = _parse_aware(event.get("utc"))
        if event_utc is None or event_utc.astimezone(zone).date().isoformat() != local_date:
            continue
        if event.get("event") == "daily_review_snapshot":
            snapshot = True
        if event.get("event") in {"daily_review_completed", "daily_review_failed"}:
            outcome = details.get("local_date") == local_date
    return snapshot and outcome


def main(argv: list[str] | None = None) -> int:
    from cron import jobs

    parser = argparse.ArgumentParser(description="verify the two fixed health Jobs")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0 or args.timeout_seconds > 1800:
        raise RuntimeError("invalid-smoke-timeout")
    if os.environ.get("HERMES_HOME") != "/var/lib/hermes-partner/.hermes/profiles/partner":
        raise RuntimeError("smoke-requires-isolated-partner-home")

    socket_path = os.environ.get("HEALTH_STEWARD_SOCKET", "")
    source_root = os.environ.get("HEALTH_STEWARD_SOURCE_ROOT", "")
    if socket_path != "/run/health-sidecar/health.sock" or not source_root.startswith(
        "/opt/partner-health-steward/releases/"
    ):
        raise RuntimeError("smoke-requires-installed-runtime")

    adapter = PartnerHealthAdapter(socket_path)
    now = dt.datetime.now(dt.timezone.utc)
    before_event_list = [dict(event) for event in adapter.read_audit()]
    before_events = _event_counts(before_event_list)
    state_db = Path(os.environ["HERMES_HOME"]) / "state.db"
    before_sessions = _cron_session_ids(state_db)
    before = _fixed_records()
    before_runs = {name: record.get("last_run_at") for name, record in before.items()}
    specs = {spec.role: spec for spec in _fixed_specs()}
    daily = specs["daily_profile_review"]
    dispatcher = specs["due_task_dispatch"]

    if not _ran_today(before[daily.name], now):
        raise RuntimeError("daily-job-has-not-completed-today;run-after-owner-0400")
    if not _has_current_daily_audit(before_event_list, now):
        raise RuntimeError("current-daily-sidecar-evidence-missing")
    local_stamp = now.astimezone(_owner_zone()).strftime("%Y%m%d")
    if not any(
        session.startswith(f"cron_{before[daily.name]['id']}_{local_stamp}_")
        for session in before_sessions
    ):
        raise RuntimeError("current-daily-fresh-session-missing")

    if jobs.trigger_job(str(before[dispatcher.name]["id"])) is None:
        raise RuntimeError(f"failed-trigger-fixed-job:{dispatcher.name}")

    deadline = time.monotonic() + args.timeout_seconds
    current: dict[str, dict[str, Any]] = {}
    while time.monotonic() < deadline:
        current = _fixed_records()
        if (
            current[dispatcher.name].get("last_run_at")
            and current[dispatcher.name].get("last_run_at")
            != before_runs[dispatcher.name]
        ):
            break
        time.sleep(5)
    else:
        raise RuntimeError("fixed-health-jobs-did-not-complete")
    if current[dispatcher.name].get("last_status") != "ok":
        raise RuntimeError("fixed-health-job-completed-with-error")

    after_events = _event_counts(adapter.read_audit())
    if after_events.get("dispatcher_heartbeat", 0) <= before_events.get(
        "dispatcher_heartbeat", 0
    ):
        raise RuntimeError("dispatcher-plugin-sidecar-call-missing")

    new_sessions = _cron_session_ids(state_db) - before_sessions
    if not any(
        session.startswith(f"cron_{before[dispatcher.name]['id']}_")
        for session in new_sessions
    ):
        raise RuntimeError("fresh-cron-session-missing")

    print(
        json.dumps(
            {
                "result": "passed",
                "fixed_jobs": 2,
                "daily_job_completed_today": True,
                "daily_fresh_session_verified": True,
                "daily_sidecar_snapshot_and_outcome_verified": True,
                "dispatcher_triggered_once": True,
                "dispatcher_fresh_session_verified": True,
                "dispatcher_sidecar_heartbeat_verified": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

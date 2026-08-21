"""Content-free operational monitoring outside the health planning flow."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import logging.handlers
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Protocol

from .store import (
    AUDIT_RETENTION_DAYS,
    Clock,
    SystemClock,
    _AUDIT_TOKEN,
    _cross_process_file_lock,
    _OPERATIONAL_AUDIT_KEYS,
    StoreError,
    _validate_audit_record,
)


DAILY_REVIEW_FAILURE_THRESHOLD = 2
DISPATCHER_HEARTBEAT_TIMEOUT = dt.timedelta(minutes=15)
ACCEPTANCE_STATES = {"not_run", "pending", "passed", "blocked"}
_ALERT_METADATA_KEYS = {
    "subject_id",
    "failure_count",
    "last_failure_utc",
    "last_heartbeat_utc",
    "timeout_seconds",
    "reason",
}
_ALERT_CODES = {
    "daily-review-failure-streak",
    "dispatcher-heartbeat-stale",
    "operational-audit-unavailable",
}
_ALERT_STATES = {
    "firing",
    "recovered",
    "delivery_failed",
    "recovery_delivery_failed",
}
_ALERT_REASON_CODES = {"audit-reader-unavailable"}


class OperationalAuditReader(Protocol):
    """Read only the store's metadata-only operational audit projection."""

    def read_operational_audit_events(
        self, limit: int | None = None
    ) -> list[Mapping[str, Any]]:
        ...


class OperatorAlertSink(Protocol):
    """Deliver an alert without receiving health content or profile snapshots."""

    def send_alert(
        self, alert_code: str, state: str, metadata: Mapping[str, Any]
    ) -> None:
        ...


class OperationalMonitorError(RuntimeError):
    """Raised when the monitor configuration or clock is invalid."""


def _project_operational_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    details = event.get("details")
    try:
        _validate_audit_record(
            event.get("event"), details, utc=event.get("utc")
        )
    except StoreError:
        return None
    if not isinstance(details, Mapping):
        return None
    safe_details: dict[str, Any] = {}
    for key in _OPERATIONAL_AUDIT_KEYS:
        value = details.get(key)
        if value is None:
            continue
        if key in {"evidence_ids", "task_ids"}:
            if isinstance(value, list) and all(
                isinstance(item, str) and item.strip() for item in value
            ):
                safe_details[key] = [str(item) for item in value]
            continue
        if isinstance(value, (str, int, float, bool)):
            safe_details[key] = value
    return {
        "utc": str(event.get("utc", "")),
        "event": str(event.get("event", "")),
        "details": safe_details,
    }


class JsonlOperationalAuditReader:
    """Read and purge the content-free audit log without opening health state."""

    def __init__(
        self,
        audit_path: str | os.PathLike[str],
        *,
        clock: Clock | None = None,
    ) -> None:
        self.audit_path = Path(audit_path)
        self.clock = clock or SystemClock()

    def _read_raw_events(self) -> list[dict[str, Any]]:
        with _cross_process_file_lock(self.audit_path):
            return self._read_raw_events_unlocked()

    def _read_raw_events_unlocked(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        try:
            lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise OperationalMonitorError("audit-read-failed") from exc
        events: list[dict[str, Any]] = []
        for raw in lines:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise OperationalMonitorError("invalid-operational-audit") from exc
            if not isinstance(event, dict):
                raise OperationalMonitorError("operational-audit-must-be-object")
            events.append(event)
        return events

    def read_operational_audit_events(
        self, limit: int | None = None
    ) -> list[Mapping[str, Any]]:
        if limit is not None and limit < 1:
            raise OperationalMonitorError("audit-limit-must-be-positive")
        events = self._read_raw_events()
        selected = events if limit is None else events[-limit:]
        return [
            projected
            for event in selected
            if (projected := _project_operational_event(event)) is not None
        ]

    def purge_expired_audit_events(self) -> Mapping[str, int]:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with _cross_process_file_lock(self.audit_path):
            events = self._read_raw_events_unlocked()
            if not events:
                return {"deleted": 0, "retained": 0}
            now = self.clock.now_utc()
            if now.tzinfo is None:
                raise OperationalMonitorError("clock-must-return-aware-utc")
            cutoff = now.astimezone(dt.timezone.utc) - dt.timedelta(
                days=AUDIT_RETENTION_DAYS
            )
            retained: list[dict[str, Any]] = []
            for event in events:
                try:
                    _validate_audit_record(
                        event.get("event"),
                        event.get("details"),
                        utc=event.get("utc"),
                    )
                except StoreError:
                    continue
                try:
                    event_time = _utc(
                        event.get("utc"), "invalid-operational-audit-time"
                    )
                except OperationalMonitorError:
                    retained.append(event)
                    continue
                if event_time >= cutoff:
                    retained.append(event)
            if len(retained) != len(events):
                fd, temporary_name = tempfile.mkstemp(
                    prefix=f".{self.audit_path.name}.",
                    suffix=".tmp",
                    dir=str(self.audit_path.parent),
                )
                os.close(fd)
                temporary = Path(temporary_name)
                try:
                    with open(temporary, "w", encoding="utf-8") as handle:
                        for event in retained:
                            handle.write(
                                json.dumps(
                                    event, ensure_ascii=False, separators=(",", ":")
                                )
                            )
                            handle.write("\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                    try:
                        temporary.chmod(0o600)
                    except OSError:
                        pass
                    os.replace(temporary, self.audit_path)
                finally:
                    try:
                        temporary.unlink()
                    except OSError:
                        pass
            return {
                "deleted": len(events) - len(retained),
                "retained": len(retained),
            }


class JsonlOperatorAlertSink:
    """Append content-free alert transitions for an external operator relay."""

    def __init__(
        self,
        alert_path: str | os.PathLike[str],
        *,
        clock: Clock | None = None,
    ) -> None:
        self.alert_path = Path(alert_path)
        self.clock = clock or SystemClock()

    def send_alert(
        self, alert_code: str, state: str, metadata: Mapping[str, Any]
    ) -> None:
        if not isinstance(alert_code, str) or alert_code not in _ALERT_CODES:
            raise OperationalMonitorError("alert-code-forbidden")
        if not isinstance(state, str) or state not in _ALERT_STATES:
            raise OperationalMonitorError("alert-state-forbidden")
        if any(str(key) not in _ALERT_METADATA_KEYS for key in metadata):
            raise OperationalMonitorError("alert-metadata-forbidden")
        safe = OperationalMonitor._safe_alert_metadata(metadata)
        if set(safe) != {str(key) for key in metadata}:
            raise OperationalMonitorError("alert-metadata-forbidden")
        event = {
            "utc": _now(self.clock, None).isoformat(),
            "alert_code": alert_code.strip(),
            "state": state.strip(),
            "metadata": safe,
        }
        self.alert_path.parent.mkdir(parents=True, exist_ok=True)
        with _cross_process_file_lock(self.alert_path):
            with open(self.alert_path, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        try:
            self.alert_path.chmod(0o600)
        except OSError:
            pass


class SyslogOperatorAlertSink:
    """Send fixed-format, content-free alerts to the operator's syslog relay."""

    def __init__(self, address: str | tuple[str, int] = "/dev/log") -> None:
        self.address = address

    def send_alert(
        self, alert_code: str, state: str, metadata: Mapping[str, Any]
    ) -> None:
        if not isinstance(alert_code, str) or alert_code not in _ALERT_CODES:
            raise OperationalMonitorError("alert-code-forbidden")
        if not isinstance(state, str) or state not in _ALERT_STATES:
            raise OperationalMonitorError("alert-state-forbidden")
        safe = OperationalMonitor._safe_alert_metadata(metadata)
        if set(safe) != {str(key) for key in metadata}:
            raise OperationalMonitorError("alert-metadata-forbidden")
        handler = logging.handlers.SysLogHandler(address=self.address)
        try:
            message = "health-sidecar " + json.dumps(
                {
                    "alert_code": alert_code,
                    "state": state,
                    "metadata": safe,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            handler.emit(
                logging.LogRecord(
                    "health-sidecar",
                    logging.ERROR if state == "firing" else logging.INFO,
                    __file__,
                    0,
                    message,
                    (),
                    None,
                )
            )
        finally:
            handler.close()


def run_monitor_once(
    audit_path: str | os.PathLike[str],
    alert_path: str | os.PathLike[str],
    state_path: str | os.PathLike[str],
    *,
    production_acceptance: str = "not_run",
    clock: Clock | None = None,
    alert_sink: OperatorAlertSink | None = None,
) -> Mapping[str, Any]:
    """Run one external monitor poll; suitable for a systemd timer/cron wrapper."""
    reader = JsonlOperationalAuditReader(audit_path, clock=clock)
    sink = alert_sink or JsonlOperatorAlertSink(alert_path, clock=clock)
    monitor = OperationalMonitor(reader, sink, state_path=state_path, clock=clock)
    return monitor.check(production_acceptance=production_acceptance)


def _utc(value: Any, error: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise OperationalMonitorError(error)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise OperationalMonitorError(error) from exc
    if parsed.tzinfo is None:
        raise OperationalMonitorError(error)
    return parsed.astimezone(dt.timezone.utc)


def _now(clock: Clock, value: Any | None) -> dt.datetime:
    if value is None:
        current = clock.now_utc()
        if current.tzinfo is None:
            raise OperationalMonitorError("clock-must-return-aware-utc")
        return current.astimezone(dt.timezone.utc).replace(microsecond=0)
    return _utc(value, "invalid-operational-time").replace(microsecond=0)


class OperationalMonitor:
    """Evaluate job health and emit deduplicated, content-free alerts.

    The monitor consumes only the store's operational-audit projection.  It
    never reads profile state, evidence, source cards, task snapshots, or
    model output.  Its small state file contains alert transitions and a
    monitor start time, not health data.
    """

    def __init__(
        self,
        audit_reader: OperationalAuditReader,
        alert_sink: OperatorAlertSink,
        *,
        state_path: str | os.PathLike[str] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.audit_reader = audit_reader
        self.alert_sink = alert_sink
        self.state_path = Path(state_path) if state_path is not None else None
        self.clock = clock or SystemClock()
        self._state = self._load_state()

    def check(
        self,
        now_utc: str | None = None,
        *,
        production_acceptance: str = "not_run",
    ) -> Mapping[str, Any]:
        if self.state_path is None:
            return self._check_unlocked(
                now_utc,
                production_acceptance=production_acceptance,
            )
        lock = _cross_process_file_lock(self.state_path)
        with lock:
            self._state = self._load_state()
            return self._check_unlocked(
                now_utc,
                production_acceptance=production_acceptance,
            )

    def _check_unlocked(
        self,
        now_utc: str | None = None,
        *,
        production_acceptance: str = "not_run",
    ) -> Mapping[str, Any]:
        if production_acceptance not in ACCEPTANCE_STATES:
            raise OperationalMonitorError("invalid-production-acceptance-state")
        now = _now(self.clock, now_utc)
        started = self._state.get("monitor_started_utc")
        if not isinstance(started, str) or not started:
            started = now.isoformat()
            self._state["monitor_started_utc"] = started

        alerts: list[dict[str, Any]] = []
        try:
            purge = getattr(self.audit_reader, "purge_expired_audit_events", None)
            if callable(purge):
                purge()
            events = self.audit_reader.read_operational_audit_events(limit=None)
            if not isinstance(events, list):
                raise OperationalMonitorError("operational-audit-must-be-list")
            normalized_events = [
                event for event in events if isinstance(event, Mapping)
            ]
            service_state = "healthy"
        except Exception as exc:
            normalized_events = []
            service_state = "degraded"
            audit_alert = self._transition(
                "audit-reader",
                "operational-audit-unavailable",
                True,
                {"reason": "audit-reader-unavailable"},
                now_utc=now,
            )
            if audit_alert is not None:
                alerts.append(audit_alert)
            self._state["last_reader_error"] = type(exc).__name__

        daily = self._daily_review_status(normalized_events)
        for subject_id, details in daily["subjects"].items():
            alert = self._transition(
                f"daily-review:{subject_id}",
                "daily-review-failure-streak",
                details["failure_streak"] >= DAILY_REVIEW_FAILURE_THRESHOLD,
                {
                    "subject_id": subject_id,
                    "failure_count": details["failure_streak"],
                    "last_failure_utc": details.get("last_failure_utc"),
                },
                now_utc=now,
            )
            if alert is not None:
                alerts.append(alert)

        dispatcher = self._dispatcher_status(normalized_events, now, started)
        dispatcher_alert = self._transition(
            "dispatcher-heartbeat",
            "dispatcher-heartbeat-stale",
            dispatcher["state"] == "stale",
            {
                "last_heartbeat_utc": dispatcher.get("last_heartbeat_utc"),
                "timeout_seconds": int(DISPATCHER_HEARTBEAT_TIMEOUT.total_seconds()),
            },
            now_utc=now,
        )
        if dispatcher_alert is not None:
            alerts.append(dispatcher_alert)

        self._save_state()
        return {
            "checked_utc": now.isoformat(),
            "service_health": {
                "state": service_state,
                "audit_retention_days": AUDIT_RETENTION_DAYS,
            },
            "job_health": {
                "daily_review": daily,
                "dispatcher": dispatcher,
            },
            "content_authorization": "metadata_only",
            "production_acceptance": production_acceptance,
            "alerts": alerts,
        }

    def status(
        self,
        now_utc: str | None = None,
        *,
        production_acceptance: str = "not_run",
    ) -> Mapping[str, Any]:
        """Alias for operational queries used by operators and tests."""
        return self.check(
            now_utc,
            production_acceptance=production_acceptance,
        )

    def _daily_review_status(
        self, events: list[Mapping[str, Any]]
    ) -> dict[str, Any]:
        subjects: dict[str, dict[str, Any]] = {}
        ordered = self._ordered_events(events)
        for event_time, event in ordered:
            if event.get("event") not in {
                "daily_review_failed",
                "daily_review_completed",
            }:
                continue
            details = event.get("details")
            if not isinstance(details, Mapping):
                continue
            subject_id = str(details.get("subject", "")).strip()
            if not subject_id:
                continue
            state = subjects.setdefault(
                subject_id,
                {
                    "failure_streak": 0,
                    "last_failure_utc": None,
                    "last_success_utc": None,
                },
            )
            if event.get("event") == "daily_review_failed":
                state["failure_streak"] += 1
                state["last_failure_utc"] = event_time.isoformat()
            else:
                state["failure_streak"] = 0
                state["last_success_utc"] = event_time.isoformat()
        failing = [
            subject
            for subject, state in subjects.items()
            if state["failure_streak"] >= DAILY_REVIEW_FAILURE_THRESHOLD
        ]
        return {
            "state": "degraded" if failing else ("healthy" if subjects else "unknown"),
            "subjects": subjects,
            "failing_subject_ids": sorted(failing),
        }

    def _dispatcher_status(
        self,
        events: list[Mapping[str, Any]],
        now: dt.datetime,
        started_utc: str,
    ) -> dict[str, Any]:
        heartbeats = [
            (event_time, event)
            for event_time, event in self._ordered_events(events)
            if event.get("event") == "dispatcher_heartbeat"
            and isinstance(event.get("details"), Mapping)
            and event["details"].get("result") == "healthy"
        ]
        last_heartbeat = heartbeats[-1][0] if heartbeats else None
        reference = last_heartbeat or _utc(started_utc, "invalid-monitor-start-time")
        age = max(dt.timedelta(0), now - reference)
        stale = age >= DISPATCHER_HEARTBEAT_TIMEOUT
        return {
            "state": "stale" if stale else ("healthy" if last_heartbeat else "starting"),
            "last_heartbeat_utc": last_heartbeat.isoformat()
            if last_heartbeat
            else None,
            "age_seconds": int(age.total_seconds()),
            "timeout_seconds": int(DISPATCHER_HEARTBEAT_TIMEOUT.total_seconds()),
        }

    def _ordered_events(
        self, events: list[Mapping[str, Any]]
    ) -> list[tuple[dt.datetime, Mapping[str, Any]]]:
        ordered: list[tuple[dt.datetime, Mapping[str, Any]]] = []
        for event in events:
            try:
                event_time = _utc(event.get("utc"), "invalid-operational-audit-time")
            except OperationalMonitorError:
                continue
            ordered.append((event_time, event))
        ordered.sort(key=lambda item: item[0])
        return ordered

    def _transition(
        self,
        key: str,
        alert_code: str,
        unhealthy: bool,
        metadata: Mapping[str, Any],
        *,
        now_utc: dt.datetime,
    ) -> dict[str, Any] | None:
        active = self._state.setdefault("active_alerts", {})
        if unhealthy:
            if key in active:
                return None
            state = "firing"
            payload = self._safe_alert_metadata(metadata)
            try:
                self.alert_sink.send_alert(alert_code, state, payload)
            except Exception:
                self._record_transition(
                    key, alert_code, "delivery_failed", payload, now_utc
                )
                return {
                    "alert_code": alert_code,
                    "state": "delivery_failed",
                    "key": key,
                }
            active[key] = {"alert_code": alert_code}
            self._record_transition(key, alert_code, state, payload, now_utc)
            return {"alert_code": alert_code, "state": state, "key": key}
        if key not in active:
            return None
        state = "recovered"
        payload = self._safe_alert_metadata(metadata)
        try:
            self.alert_sink.send_alert(alert_code, state, payload)
        except Exception:
            self._record_transition(
                key, alert_code, "recovery_delivery_failed", payload, now_utc
            )
            return {
                "alert_code": alert_code,
                "state": "recovery_delivery_failed",
                "key": key,
            }
        del active[key]
        self._record_transition(key, alert_code, state, payload, now_utc)
        return {"alert_code": alert_code, "state": state, "key": key}

    def _record_transition(
        self,
        key: str,
        alert_code: str,
        state: str,
        metadata: Mapping[str, Any],
        now_utc: dt.datetime,
    ) -> None:
        transitions = self._state.setdefault("alert_transitions", [])
        if not isinstance(transitions, list):
            transitions = []
        transitions.append(
            {
                "key": key,
                "alert_code": alert_code,
                "state": state,
                "transitioned_utc": now_utc.isoformat(),
                "metadata": self._safe_alert_metadata(metadata),
            }
        )
        self._state["alert_transitions"] = transitions[-1024:]

    @staticmethod
    def _safe_alert_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in metadata.items():
            key = str(key)
            if key not in _ALERT_METADATA_KEYS:
                continue
            if key in {"subject_id", "reason"}:
                if key == "reason" and value not in _ALERT_REASON_CODES:
                    continue
                if not isinstance(value, str) or not _AUDIT_TOKEN.fullmatch(value):
                    continue
            elif key in {"failure_count", "timeout_seconds"}:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    continue
            elif key in {"last_failure_utc", "last_heartbeat_utc"}:
                if value is not None:
                    try:
                        _utc(value, "invalid-alert-time")
                    except OperationalMonitorError:
                        continue
            elif not (
                isinstance(value, (str, int, float, bool)) or value is None
            ):
                continue
            safe[key] = value
        return safe

    def _load_state(self) -> dict[str, Any]:
        if self.state_path is None or not self.state_path.exists():
            return {"active_alerts": {}, "alert_transitions": []}
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"active_alerts": {}, "alert_transitions": []}
        if not isinstance(loaded, dict):
            return {"active_alerts": {}, "alert_transitions": []}
        state: dict[str, Any] = {"active_alerts": {}, "alert_transitions": []}
        started = loaded.get("monitor_started_utc")
        if isinstance(started, str):
            try:
                _utc(started, "invalid-monitor-start-time")
            except OperationalMonitorError:
                pass
            else:
                state["monitor_started_utc"] = started
        active = loaded.get("active_alerts")
        if isinstance(active, Mapping):
            state["active_alerts"] = {
                str(key): {"alert_code": value.get("alert_code")}
                for key, value in active.items()
                if isinstance(key, str)
                and isinstance(value, Mapping)
                and value.get("alert_code") in _ALERT_CODES
            }
        transitions = loaded.get("alert_transitions")
        if isinstance(transitions, list):
            safe_transitions: list[dict[str, Any]] = []
            for item in transitions[-1024:]:
                if not isinstance(item, Mapping):
                    continue
                if item.get("alert_code") not in _ALERT_CODES:
                    continue
                if item.get("state") not in _ALERT_STATES:
                    continue
                try:
                    _utc(item.get("transitioned_utc"), "invalid-transition-time")
                except OperationalMonitorError:
                    continue
                metadata = item.get("metadata")
                if not isinstance(metadata, Mapping):
                    continue
                safe_metadata = self._safe_alert_metadata(metadata)
                if set(safe_metadata) != {str(key) for key in metadata}:
                    continue
                safe_transitions.append(
                    {
                        "key": str(item.get("key", "")),
                        "alert_code": item["alert_code"],
                        "state": item["state"],
                        "transitioned_utc": item["transitioned_utc"],
                        "metadata": safe_metadata,
                    }
                )
            state["alert_transitions"] = safe_transitions
        last_error = loaded.get("last_reader_error")
        if isinstance(last_error, str) and _AUDIT_TOKEN.fullmatch(last_error):
            state["last_reader_error"] = last_error
        return state

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        encoded = json.dumps(
            self._state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, self.state_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="run one content-free health-sidecar operational monitor poll"
    )
    parser.add_argument("--audit-path", required=True)
    parser.add_argument("--alert-path")
    parser.add_argument(
        "--syslog-address",
        help="operator syslog Unix socket path or HOST:PORT destination",
    )
    parser.add_argument("--state-path", required=True)
    parser.add_argument(
        "--production-acceptance",
        choices=sorted(ACCEPTANCE_STATES),
        default="not_run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.alert_path and not args.syslog_address:
        raise OperationalMonitorError("operator-alert-sink-required")
    if args.syslog_address:
        address: str | tuple[str, int] = args.syslog_address
        if ":" in args.syslog_address and not args.syslog_address.startswith("/"):
            host, port = args.syslog_address.rsplit(":", 1)
            address = (host, int(port))
        result = run_monitor_once(
            args.audit_path,
            args.alert_path or str(Path(args.audit_path).with_suffix(".alerts.log")),
            args.state_path,
            production_acceptance=args.production_acceptance,
            alert_sink=SyslogOperatorAlertSink(address),
        )
    else:
        result = run_monitor_once(
            args.audit_path,
            args.alert_path,
            args.state_path,
            production_acceptance=args.production_acceptance,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

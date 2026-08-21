import datetime as dt
import tempfile
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import OperationalMonitor
from sidecar.operations import (
    JsonlOperationalAuditReader,
    JsonlOperatorAlertSink,
    run_monitor_once,
)
from sidecar.store import HealthSidecarStore, StoreError


class FixedClock:
    def __init__(self, now: dt.datetime):
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class AuditReaderFake:
    def __init__(self, events=None):
        self.events = list(events or [])
        self.purge_calls = 0

    def read_operational_audit_events(self, limit=None):
        del limit
        return list(self.events)

    def purge_expired_audit_events(self):
        self.purge_calls += 1
        return {"deleted": 0, "retained": len(self.events)}


class AlertSinkFake:
    def __init__(self):
        self.alerts = []

    def send_alert(self, alert_code, state, metadata):
        self.alerts.append((alert_code, state, dict(metadata)))


def audit(utc, event, **details):
    return {"utc": utc, "event": event, "details": details}


class OperationalMonitorTests(unittest.TestCase):
    def test_two_daily_failures_fire_once_and_recover_without_health_content(self):
        reader = AuditReaderFake(
            [
                audit(
                    "2026-01-01T04:00:00Z",
                    "daily_review_failed",
                    subject="profile",
                    local_date="2026-01-01",
                    attempt=1,
                    reason="daily-review-failed",
                ),
                audit(
                    "2026-01-02T04:00:00Z",
                    "daily_review_failed",
                    subject="profile",
                    local_date="2026-01-02",
                    attempt=2,
                    reason="daily-review-failed",
                ),
            ]
        )
        sink = AlertSinkFake()
        clock = FixedClock(dt.datetime(2026, 1, 2, 4, 10, tzinfo=dt.timezone.utc))
        monitor = OperationalMonitor(reader, sink, clock=clock)

        first = monitor.check()
        second = monitor.check()

        self.assertEqual(first["job_health"]["daily_review"]["state"], "degraded")
        self.assertEqual(len(sink.alerts), 1)
        self.assertEqual(sink.alerts[0][:2], ("daily-review-failure-streak", "firing"))
        self.assertNotIn("睡眠", str(sink.alerts))
        self.assertEqual(second["alerts"], [])

        reader.events.append(
            audit(
                "2026-01-02T04:20:00Z",
                "daily_review_completed",
                subject="profile",
                local_date="2026-01-02",
                result="no_action",
            )
        )
        recovered = monitor.check()
        self.assertEqual(sink.alerts[-1][:2], ("daily-review-failure-streak", "recovered"))
        self.assertEqual(recovered["job_health"]["daily_review"]["state"], "healthy")

    def test_dispatcher_heartbeat_alerts_after_fifteen_minutes_and_recovers(self):
        reader = AuditReaderFake(
            [
                audit(
                    "2026-01-01T00:00:00Z",
                    "dispatcher_heartbeat",
                    subject="profile",
                    result="healthy",
                    heartbeat=True,
                )
            ]
        )
        sink = AlertSinkFake()
        clock = FixedClock(dt.datetime(2026, 1, 1, 0, 1, tzinfo=dt.timezone.utc))
        monitor = OperationalMonitor(reader, sink, clock=clock)
        self.assertEqual(monitor.check()["job_health"]["dispatcher"]["state"], "healthy")

        clock.now = dt.datetime(2026, 1, 1, 0, 15, tzinfo=dt.timezone.utc)
        stale = monitor.check()
        self.assertEqual(stale["job_health"]["dispatcher"]["state"], "stale")
        self.assertEqual(sink.alerts[-1][:2], ("dispatcher-heartbeat-stale", "firing"))

        reader.events.append(
            audit(
                "2026-01-01T00:16:00Z",
                "dispatcher_heartbeat",
                subject="profile",
                result="healthy",
                heartbeat=True,
            )
        )
        clock.now = dt.datetime(2026, 1, 1, 0, 16, tzinfo=dt.timezone.utc)
        self.assertEqual(monitor.check()["job_health"]["dispatcher"]["state"], "healthy")
        self.assertEqual(sink.alerts[-1][:2], ("dispatcher-heartbeat-stale", "recovered"))

    def test_status_separates_job_health_authorization_and_acceptance(self):
        reader = AuditReaderFake(
            [
                audit(
                    "2026-01-01T00:00:00Z",
                    "dispatcher_heartbeat",
                    result="healthy",
                    heartbeat=True,
                ),
                audit(
                    "2026-01-01T00:01:00Z",
                    "daily_review_failed",
                    subject="profile",
                    reason="daily-review-failed",
                ),
            ]
        )
        monitor = OperationalMonitor(
            reader,
            AlertSinkFake(),
            clock=FixedClock(dt.datetime(2026, 1, 1, 0, 2, tzinfo=dt.timezone.utc)),
        )
        status = monitor.status(production_acceptance="blocked")
        self.assertEqual(status["service_health"]["state"], "healthy")
        self.assertEqual(status["content_authorization"], "metadata_only")
        self.assertEqual(status["production_acceptance"], "blocked")
        self.assertNotIn("profile_summary_zh", str(status))

    def test_store_audit_projection_rejects_content_and_purges_after_ninety_days(self):
        with tempfile.TemporaryDirectory() as root:
            clock = FixedClock(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
            store = HealthSidecarStore(
                Path(root) / "state.sqlite.enc", Path(root) / "sidecar.key", clock=clock
            )
            with self.assertRaisesRegex(StoreError, "audit-content-forbidden"):
                store.append_audit_event(
                    "unsafe", {"message_text": "sleep detail", "subject": "profile"}
                )
            store.append_audit_event(
                "old-operation",
                {"subject": "profile", "action": "task.send", "result": "sent"},
            )
            clock.now = dt.datetime(2026, 4, 2, tzinfo=dt.timezone.utc)
            store.append_audit_event(
                "current-operation",
                {"subject": "profile", "action": "task.skip", "result": "skipped"},
            )
            result = store.purge_expired_audit_events()
            self.assertEqual(result["deleted"], 1)
            projected = store.read_operational_audit_events()
            self.assertEqual([event["event"] for event in projected], ["current-operation"])
            self.assertNotIn("sleep detail", str(projected))

    def test_dispatcher_run_writes_successful_heartbeat(self):
        with tempfile.TemporaryDirectory() as root:
            clock = FixedClock(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
            store = HealthSidecarStore(
                Path(root) / "state.sqlite.enc", Path(root) / "sidecar.key", clock=clock
            )
            owner_token = store.message_verifier.sign_owner_binding(
                subject="profile", owner_sender_id="owner"
            )
            store.bind_profile_owner("profile", "owner", owner_token)
            store.dispatch_due_tasks("profile", "2026-01-01T00:00:00Z", None, None)
            events = store.read_operational_audit_events()
            self.assertTrue(any(event["event"] == "dispatcher_heartbeat" for event in events))

    def test_audit_writer_rejects_unknown_and_nested_content(self):
        with tempfile.TemporaryDirectory() as root:
            store = HealthSidecarStore(
                Path(root) / "state.sqlite.enc", Path(root) / "sidecar.key"
            )
            for details in (
                {"note": "sleep detail"},
                {"meta": {"message_text": "sleep detail"}},
                {"reason": "HEALTH_TEXT_PROBE"},
                {"actor_id": "sleep detail"},
                {"heartbeat": "stomach pain for 2 days"},
            ):
                with self.subTest(details=details):
                    with self.assertRaisesRegex(StoreError, "audit-content-forbidden"):
                        store.append_audit_event("unsafe", details)
            self.assertEqual(store.read_audit_events(), [])

    def test_monitor_purges_on_each_check_and_persists_recovery_transition(self):
        reader = AuditReaderFake(
            [
                audit(
                    "2026-01-01T00:00:00Z",
                    "dispatcher_heartbeat",
                    subject="profile",
                    result="healthy",
                    heartbeat=True,
                )
            ]
        )
        clock = FixedClock(dt.datetime(2026, 1, 1, 0, 1, tzinfo=dt.timezone.utc))
        sink = AlertSinkFake()
        with tempfile.TemporaryDirectory() as root:
            state_path = Path(root) / "monitor-state.json"
            monitor = OperationalMonitor(
                reader, sink, state_path=state_path, clock=clock
            )
            monitor.check()
            self.assertEqual(reader.purge_calls, 1)
            clock.now = dt.datetime(2026, 1, 1, 0, 15, tzinfo=dt.timezone.utc)
            monitor.check()
            reader.events.append(
                audit(
                    "2026-01-01T00:16:00Z",
                    "dispatcher_heartbeat",
                    subject="profile",
                    result="healthy",
                    heartbeat=True,
                )
            )
            clock.now = dt.datetime(2026, 1, 1, 0, 16, tzinfo=dt.timezone.utc)
            monitor.check()
            saved = state_path.read_text(encoding="utf-8")
            self.assertIn('"state":"firing"', saved)
            self.assertIn('"state":"recovered"', saved)

    def test_external_jsonl_reader_and_alert_sink_are_content_free(self):
        with tempfile.TemporaryDirectory() as root:
            audit_path = Path(root) / "health.audit.log"
            audit_path.write_text(
                '{"utc":"2026-01-01T00:00:00+00:00","event":"dispatcher_heartbeat",'
                '"details":{"subject":"profile","result":"healthy",'
                '"heartbeat":true,"message_text":"must not be projected"}}\n',
                encoding="utf-8",
            )
            reader = JsonlOperationalAuditReader(audit_path)
            events = reader.read_operational_audit_events()
            self.assertEqual(events, [])
            self.assertNotIn("message_text", str(events))
            sink = JsonlOperatorAlertSink(Path(root) / "operator-alerts.log")
            sink.send_alert(
                "dispatcher-heartbeat-stale", "firing", {"timeout_seconds": 900}
            )
            with self.assertRaisesRegex(Exception, "alert-metadata-forbidden"):
                sink.send_alert(
                    "dispatcher-heartbeat-stale",
                    "firing",
                    {"reason": "sleep detail"},
                )
            alert_text = (Path(root) / "operator-alerts.log").read_text(
                encoding="utf-8"
            )
            self.assertIn("dispatcher-heartbeat-stale", alert_text)
            self.assertNotIn("message_text", alert_text)

    def test_external_monitor_runner_emits_alert_without_health_store_key(self):
        with tempfile.TemporaryDirectory() as root:
            audit_path = Path(root) / "health.audit.log"
            audit_path.write_text(
                '{"utc":"2026-01-01T00:00:00+00:00","event":"dispatcher_heartbeat",'
                '"details":{"subject":"profile","result":"healthy",'
                '"heartbeat":true}}\n',
                encoding="utf-8",
            )
            clock = FixedClock(dt.datetime(2026, 1, 1, 0, 15, tzinfo=dt.timezone.utc))
            result = run_monitor_once(
                audit_path,
                Path(root) / "operator-alerts.log",
                Path(root) / "monitor-state.json",
                clock=clock,
            )
            self.assertEqual(result["job_health"]["dispatcher"]["state"], "stale")
            alert_text = (Path(root) / "operator-alerts.log").read_text(
                encoding="utf-8"
            )
            self.assertIn("dispatcher-heartbeat-stale", alert_text)

    def test_external_reader_purges_audit_at_the_ninety_day_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            audit_path = Path(root) / "health.audit.log"
            audit_path.write_text(
                "\n".join(
                    [
                        '{"utc":"2026-01-01T00:00:00+00:00","event":"old", "details":{}}',
                        '{"utc":"2026-04-02T00:00:00+00:00","event":"current", "details":{}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            reader = JsonlOperationalAuditReader(
                audit_path,
                clock=FixedClock(dt.datetime(2026, 4, 2, tzinfo=dt.timezone.utc)),
            )
            self.assertEqual(reader.purge_expired_audit_events()["deleted"], 1)
            self.assertEqual(
                [event["event"] for event in reader.read_operational_audit_events()],
                ["current"],
            )

    def test_external_projection_rejects_invalid_top_level_time(self):
        with tempfile.TemporaryDirectory() as root:
            audit_path = Path(root) / "health.audit.log"
            audit_path.write_text(
                '{"utc":"stomach pain for 2 days","event":"dispatcher_heartbeat",'
                '"details":{"heartbeat":true}}\n',
                encoding="utf-8",
            )
            reader = JsonlOperationalAuditReader(audit_path)
            self.assertEqual(reader.read_operational_audit_events(), [])
            self.assertEqual(reader.purge_expired_audit_events()["deleted"], 1)

    def test_overlapping_monitor_polls_emit_one_firing_transition(self):
        reader = AuditReaderFake(
            [
                audit(
                    "2026-01-01T00:00:00Z",
                    "dispatcher_heartbeat",
                    subject="profile",
                    result="healthy",
                    heartbeat=True,
                )
            ]
        )
        now = FixedClock(dt.datetime(2026, 1, 1, 0, 15, tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as root:
            state_path = Path(root) / "monitor-state.json"
            sinks = [AlertSinkFake(), AlertSinkFake()]
            monitors = [
                OperationalMonitor(reader, sink, state_path=state_path, clock=now)
                for sink in sinks
            ]
            threads = [threading.Thread(target=monitor.check) for monitor in monitors]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            all_alerts = sinks[0].alerts + sinks[1].alerts
            self.assertEqual(
                [item[:2] for item in all_alerts],
                [("dispatcher-heartbeat-stale", "firing")],
            )


if __name__ == "__main__":
    unittest.main()

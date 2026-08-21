from __future__ import annotations

import datetime as dt
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar.daily_runner import DailyReviewExecutor, GatewayJobLease  # noqa: E402
from sidecar.profile import ProfileStoreError  # noqa: E402
from sidecar.sources import SourceLibrary  # noqa: E402
from sidecar.store import HealthSidecarStore  # noqa: E402


class MutableClock:
    def __init__(self, now: dt.datetime) -> None:
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class ScriptedDailyModel:
    def __init__(self, plans: list[object]) -> None:
        self._plans = list(plans)
        self.calls: list[object] = []
        self.called = threading.Event()

    def complete_daily_review(self, snapshot):
        self.calls.append(snapshot)
        self.called.set()
        next_plan = self._plans.pop(0)
        if isinstance(next_plan, Exception):
            raise next_plan
        return next_plan


class DailyRetryRunnerTests(unittest.TestCase):
    SUBJECT = "profile"
    OWNER = "wx-owner"
    REVIEW_UTC = "2026-01-02T20:00:00Z"
    TIMEZONE = "Asia/Shanghai"

    def _store(self, root: Path, clock: MutableClock) -> HealthSidecarStore:
        store = HealthSidecarStore(root / "state.sqlite.enc", root / "sidecar.key", clock=clock)
        owner_token = store.message_verifier.sign_owner_binding(
            subject=self.SUBJECT,
            owner_sender_id=self.OWNER,
        )
        self.assertTrue(store.bind_profile_owner(self.SUBJECT, self.OWNER, owner_token))
        return store

    def _executor(
        self,
        store: HealthSidecarStore,
        model: ScriptedDailyModel,
        *,
        gateway_live=lambda: True,
    ) -> DailyReviewExecutor:
        return DailyReviewExecutor(
            store=store,
            source_library=SourceLibrary(store),
            model=model,
            subject=self.SUBJECT,
            gateway_live=gateway_live,
        )

    def _record_fresh_evidence(
        self, store: HealthSidecarStore, message_id: str
    ) -> dict[str, object]:
        message_utc = "2026-01-02T20:05:00Z"
        token = store.message_verifier.sign(
            subject=self.SUBJECT,
            sender_id=self.OWNER,
            message_id=message_id,
            message_utc=message_utc,
            message_text="午后补充：昨晚睡眠仍不稳定",
            evidence_kind="direct_statement",
        )
        store.stage_profile_message(
            self.SUBJECT,
            self.OWNER,
            message_id,
            message_utc,
            "午后补充：昨晚睡眠仍不稳定",
            "direct_statement",
            token,
        )
        return store.record_profile_candidate(
            self.SUBJECT,
            self.OWNER,
            {
                "evidence_kind": "direct_statement",
                "source_message_id": message_id,
                "source_utc": message_utc,
                "excerpt": "午后补充：昨晚睡眠仍不稳定",
                "conclusions": [
                    {
                        "category": "state",
                        "dedupe_key": "sleep-retry-freshness",
                        "text": "睡眠仍不稳定",
                        "status": "fact",
                        "priority": 80,
                    }
                ],
            },
        )

    def test_first_model_failure_is_durable_then_retried_once_from_a_fresh_snapshot(self):
        clock = MutableClock(dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary), clock)
            model = ScriptedDailyModel([RuntimeError("model unavailable"), {"outcome": "no_action"}])
            executor = self._executor(store, model)

            first = executor.run_initial(self.REVIEW_UTC, self.TIMEZONE)

            self.assertEqual(first["result"], "failed")
            self.assertEqual(first["attempt"], 1)
            self.assertEqual(first["retry_after_utc"], "2026-01-02T20:10:00+00:00")
            self.assertEqual(len(model.calls), 1)
            self.assertNotIn("model unavailable", str(store.read_audit_events()))
            fresh_evidence = self._record_fresh_evidence(
                store, "daily-retry-fresh-evidence"
            )

            clock.now = dt.datetime(2026, 1, 2, 20, 10, tzinfo=dt.timezone.utc)
            retried = executor.run_due_retries()

            self.assertEqual(len(retried), 1)
            self.assertEqual(retried[0]["result"], "no_action")
            self.assertEqual(retried[0]["attempt"], 2)
            self.assertEqual(len(model.calls), 2)
            self.assertEqual(model.calls[0]["evidence"], [])
            self.assertEqual(
                [item["evidence_id"] for item in model.calls[1]["evidence"]],
                [fresh_evidence["evidence_id"]],
            )
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            run = profile["daily_review_runs"][-1]
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["attempt"], 2)
            self.assertEqual(profile["tasks"], [])

    def test_restart_recovers_only_the_persisted_retry_and_never_runs_it_early(self):
        clock = MutableClock(dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary), clock)
            first_model = ScriptedDailyModel([RuntimeError("first failure")])
            self.assertEqual(
                self._executor(store, first_model).run_initial(self.REVIEW_UTC, self.TIMEZONE)["result"],
                "failed",
            )

            # A real process restart recreates the encrypted store and the
            # background retry owner; neither object carries in-memory retry
            # state forward from the failed initial Job tick.
            restarted_store = HealthSidecarStore(
                Path(temporary) / "state.sqlite.enc",
                Path(temporary) / "sidecar.key",
                clock=clock,
            )
            restarted_model = ScriptedDailyModel([{"outcome": "no_action"}])
            restarted = self._executor(restarted_store, restarted_model)
            clock.now = dt.datetime(2026, 1, 2, 20, 5, tzinfo=dt.timezone.utc)
            self.assertEqual(restarted.run_due_retries(), [])
            self.assertEqual(restarted_model.calls, [])

            clock.now = dt.datetime(2026, 1, 2, 20, 10, tzinfo=dt.timezone.utc)
            restarted.start()
            try:
                self.assertTrue(restarted_model.called.wait(timeout=1.0))
            finally:
                restarted.stop()
            self.assertEqual(len(restarted_model.calls), 1)
            profile = restarted_store.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            )
            self.assertEqual(profile["daily_review_runs"][-1]["attempt"], 2)
            self.assertEqual(restarted.run_due_retries(), [])

    def test_second_failure_is_terminal_and_creates_no_tasks(self):
        clock = MutableClock(dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary), clock)
            model = ScriptedDailyModel([RuntimeError("first"), RuntimeError("second")])
            executor = self._executor(store, model)
            self.assertEqual(executor.run_initial(self.REVIEW_UTC, self.TIMEZONE)["attempt"], 1)

            clock.now = dt.datetime(2026, 1, 2, 20, 10, tzinfo=dt.timezone.utc)
            retried = executor.run_due_retries()
            self.assertEqual(retried[0]["result"], "failed")
            self.assertEqual(retried[0]["attempt"], 2)
            self.assertIsNone(retried[0]["retry_after_utc"])
            self.assertEqual(executor.run_due_retries(), [])
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertEqual(profile["daily_review_runs"][-1]["status"], "failed")
            self.assertEqual(profile["tasks"], [])

    def test_gateway_unavailable_never_starts_an_initial_or_recovery_model_call(self):
        clock = MutableClock(dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary), clock)
            model = ScriptedDailyModel([{"outcome": "no_action"}])
            unavailable = self._executor(store, model, gateway_live=lambda: False)

            result = unavailable.run_initial(self.REVIEW_UTC, self.TIMEZONE)

            self.assertEqual(result, {"result": "gateway_unavailable", "created_tasks": []})
            self.assertEqual(model.calls, [])
            self.assertEqual(unavailable.run_due_retries(), [])

    def test_late_retry_is_terminalized_without_a_model_call(self):
        clock = MutableClock(dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary), clock)
            model = ScriptedDailyModel([RuntimeError("first")])
            executor = self._executor(store, model)
            self.assertEqual(
                executor.run_initial(self.REVIEW_UTC, self.TIMEZONE)["attempt"], 1
            )

            # The permitted recovery window is exactly the persisted +10 minute
            # due point plus the one-minute clock-skew grace, never a late
            # same-day catch-up after a restart.
            clock.now = dt.datetime(2026, 1, 2, 20, 12, tzinfo=dt.timezone.utc)
            expired = executor.run_due_retries()

            self.assertEqual(len(expired), 1)
            self.assertEqual(expired[0]["result"], "retry_window_expired")
            self.assertEqual(len(model.calls), 1)
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            run = profile["daily_review_runs"][-1]
            self.assertEqual((run["status"], run["attempt"], run["retry_after_utc"]), ("failed", 2, None))

    def test_delayed_initial_tick_is_rejected_without_a_model_call(self):
        """A delayed 04:10 recovery is not allowed to become attempt one."""
        clock = MutableClock(dt.datetime(2026, 1, 2, 20, 10, tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary), clock)
            model = ScriptedDailyModel([{"outcome": "no_action"}])
            executor = self._executor(store, model)

            with self.assertRaisesRegex(
                ProfileStoreError, "daily-review-time-too-old"
            ):
                executor.run_initial(self.REVIEW_UTC, self.TIMEZONE)

            self.assertEqual(model.calls, [])
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertEqual(profile["daily_review_runs"], [])

    def test_expired_retry_snapshot_does_not_emit_snapshot_or_backup_audits(self):
        """A terminal retry result is not a health snapshot or maintenance run."""
        clock = MutableClock(dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary), clock)
            model = ScriptedDailyModel([RuntimeError("first")])
            self.assertEqual(
                self._executor(store, model).run_initial(self.REVIEW_UTC, self.TIMEZONE)[
                    "result"
                ],
                "failed",
            )
            before = len(store.read_audit_events(limit=None))
            clock.now = dt.datetime(2026, 1, 2, 20, 12, tzinfo=dt.timezone.utc)

            result = store.daily_review_snapshot(
                self.SUBJECT,
                self.REVIEW_UTC,
                self.TIMEZONE,
                retry_only=True,
            )

            self.assertEqual(result["result"], "retry_window_expired")
            later_events = store.read_audit_events(limit=None)[before:]
            self.assertFalse(
                any(
                    event["event"]
                    in {"daily_review_snapshot", "backup_retention_purge"}
                    for event in later_events
                )
            )

    def test_gateway_lease_expires_and_fails_closed_on_a_backward_clock_jump(self):
        clock = MutableClock(dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc))
        lease = GatewayJobLease(clock.now_utc, duration_seconds=60)
        lease.renew()
        self.assertTrue(lease.active())

        clock.now += dt.timedelta(seconds=61)
        self.assertFalse(lease.active())
        clock.now -= dt.timedelta(seconds=120)
        self.assertFalse(lease.active())


if __name__ == "__main__":
    unittest.main()

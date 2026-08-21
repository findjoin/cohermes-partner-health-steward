import datetime as dt
import copy
import os
import socket
import tempfile
import threading
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import HealthSidecarServer, PartnerHealthAdapter
from sidecar.profile import ProfileStoreError
from sidecar.store import HealthSidecarStore


class FixedClock:
    def __init__(self, now: dt.datetime):
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class DailyReviewTests(unittest.TestCase):
    SUBJECT = "profile"
    OWNER = "owner-1"

    def _store(self, root: Path) -> tuple[HealthSidecarStore, FixedClock]:
        clock = FixedClock(dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc))
        store = HealthSidecarStore(root / "state.sqlite.enc", root / "sidecar.key", clock=clock)
        token = store.message_verifier.sign_owner_binding(
            subject=self.SUBJECT, owner_sender_id=self.OWNER
        )
        self.assertTrue(store.bind_profile_owner(self.SUBJECT, self.OWNER, token))
        return store, clock

    def _add_sleep_evidence(self, store: HealthSidecarStore) -> str:
        message_id = "message-sleep"
        message_utc = "2026-01-02T19:55:00Z"
        text = "最近睡眠不好"
        token = store.message_verifier.sign(
            subject=self.SUBJECT,
            sender_id=self.OWNER,
            message_id=message_id,
            message_utc=message_utc,
            message_text=text,
            evidence_kind="direct_statement",
        )
        store.stage_profile_message(
            self.SUBJECT,
            self.OWNER,
            message_id,
            message_utc,
            text,
            "direct_statement",
            token,
        )
        result = store.record_profile_candidate(
            self.SUBJECT,
            self.OWNER,
            {
                "evidence_kind": "direct_statement",
                "source_message_id": message_id,
                "source_utc": message_utc,
                "excerpt": text,
                "conclusions": [
                    {
                        "category": "state",
                        "dedupe_key": "sleep",
                        "text": text,
                        "status": "fact",
                        "priority": 80,
                    }
                ],
            },
        )
        return str(result["evidence_id"])

    def test_daily_review_at_owner_0400_can_record_no_action(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            result = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                {"outcome": "no_action"},
            )

            self.assertEqual(result["result"], "no_action")
            self.assertEqual(result["created_tasks"], [])
            self.assertIn("profile", result["snapshot"])
            profile = store.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            )
            self.assertEqual(profile["tasks"], [])
            self.assertEqual(profile["daily_review_runs"][-1]["status"], "completed")

    def test_daily_snapshot_runs_real_backup_retention_maintenance(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            old_backups = list(store.backup_dir.glob("*.bak"))
            self.assertTrue(old_backups)
            clock.now = dt.datetime(2026, 2, 2, 20, 0, tzinfo=dt.timezone.utc)
            store.daily_review_snapshot(
                self.SUBJECT,
                "2026-02-02T20:00:00Z",
                "Asia/Shanghai",
            )
            self.assertTrue(all(not backup.exists() for backup in old_backups))
            events = store.read_audit_events(limit=None)
            purge = [
                event
                for event in events
                if event["event"] == "backup_retention_purge"
            ]
            self.assertTrue(purge)
            self.assertGreaterEqual(purge[-1]["details"]["deleted"], 1)

    def test_daily_review_persists_evidence_bound_task_without_message_copy(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            evidence_id = self._add_sleep_evidence(store)
            plan = {
                "outcome": "tasks",
                "tasks": [
                    {
                        "task_type": "status_follow_up",
                        "purpose": "跟进近期睡眠状态",
                        "evidence_ids": [evidence_id],
                        "conclusion_keys": ["sleep"],
                        "time_window": {
                            "start_utc": "2026-01-02T20:00:00Z",
                            "end_utc": "2026-01-03T20:00:00Z",
                        },
                        "valid_until_utc": "2026-01-04T20:00:00Z",
                        "dedupe_key": "sleep-follow-up",
                        "policy_constraints": {"low_risk": True},
                    }
                ],
            }
            result = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                plan,
            )

            self.assertEqual(result["result"], "tasks_created")
            task = result["created_tasks"][0]
            self.assertEqual(task["status"], "candidate")
            self.assertEqual(task["evidence_ids"], [evidence_id])
            self.assertNotIn("message", task)
            self.assertNotIn("text", task)
            profile = store.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            )
            self.assertEqual(profile["tasks"][0]["dedupe_key"], "sleep-follow-up")

            clock.now = dt.datetime(2026, 1, 3, 20, 0, tzinfo=dt.timezone.utc)
            next_plan = copy.deepcopy(plan)
            next_plan["tasks"][0]["time_window"] = {
                "start_utc": "2026-01-03T20:00:00Z",
                "end_utc": "2026-01-04T20:00:00Z",
            }
            next_plan["tasks"][0]["valid_until_utc"] = "2026-01-05T20:00:00Z"
            duplicate = store.run_daily_review(
                self.SUBJECT,
                "2026-01-03T20:00:00Z",
                "Asia/Shanghai",
                next_plan,
            )
            self.assertEqual(duplicate["result"], "no_action")
            self.assertEqual(duplicate["created_tasks"], [])

    def test_daily_review_failure_retries_once_after_ten_minutes(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            first = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                {"outcome": "failure", "reason": "private health details"},
            )
            self.assertEqual(first["result"], "failed")
            self.assertEqual(first["reason"], "daily-review-model-failure")
            self.assertEqual(first["attempt"], 1)
            self.assertEqual(first["retry_after_utc"], "2026-01-02T20:10:00+00:00")
            failure_events = [
                event
                for event in store.read_audit_events()
                if event.get("event") == "daily_review_failed"
            ]
            self.assertEqual(
                failure_events[-1]["details"]["reason"], "daily-review-failed"
            )
            self.assertNotIn("private health details", str(failure_events[-1]))

            clock.now = dt.datetime(2026, 1, 2, 20, 5, tzinfo=dt.timezone.utc)
            not_due = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                {"outcome": "no_action"},
                retry_only=True,
            )
            self.assertEqual(not_due["result"], "retry_not_due")

            clock.now = dt.datetime(2026, 1, 2, 20, 10, tzinfo=dt.timezone.utc)
            second = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                {"outcome": "no_action"},
                retry_only=True,
            )
            self.assertEqual(second["result"], "no_action")
            self.assertEqual(second["attempt"], 2)

    def test_rejected_daily_source_scan_is_a_content_free_failure_with_one_retry(self):
        class RejectedSourceLibrary:
            def scan(self, candidates, *, continue_check=None):
                if continue_check is not None and not continue_check():
                    raise AssertionError("daily scan ran after recording stopped")
                return {
                    "downloaded": [],
                    "deferred": [],
                    "rejected": list(candidates),
                }

        with tempfile.TemporaryDirectory() as root:
            store, _clock = self._store(Path(root))
            result = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                {
                    "outcome": "no_action",
                    "maintenance": {
                        "source_scan_candidates": ["https://www.who.int/health/sleep"]
                    },
                },
                source_library=RejectedSourceLibrary(),
            )

            self.assertEqual(result["result"], "failed")
            self.assertEqual(result["attempt"], 1)
            self.assertEqual(result["reason"], "daily-review-source-failure")
            self.assertEqual(result["retry_after_utc"], "2026-01-02T20:10:00+00:00")
            self.assertEqual(result["source_scan"]["rejected"], ["https://www.who.int/health/sleep"])
            self.assertNotIn("who.int", str(store.read_audit_events()))

    def test_daily_review_rejects_forbidden_task_and_respects_proactive_pause(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            evidence_id = self._add_sleep_evidence(store)
            forbidden = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                {
                    "outcome": "tasks",
                    "tasks": [
                        {
                            "task_type": "diagnosis",
                            "purpose": "判断病因",
                            "evidence_ids": [evidence_id],
                            "time_window": {
                                "start_utc": "2026-01-02T20:00:00Z",
                                "end_utc": "2026-01-03T20:00:00Z",
                            },
                            "valid_until_utc": "2026-01-04T20:00:00Z",
                            "dedupe_key": "diagnosis",
                            "policy_constraints": {"low_risk": False},
                        }
                    ],
                },
            )
            self.assertEqual(forbidden["result"], "failed")
            self.assertEqual(forbidden["created_tasks"], [])

            clock.now = dt.datetime(2026, 1, 3, 20, 0, tzinfo=dt.timezone.utc)
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "proactive_contact": {"paused": True, "reason": "owner-pause"},
                    },
                    None,
                ),
            )
            paused = store.run_daily_review(
                self.SUBJECT,
                "2026-01-03T20:00:00Z",
                "Asia/Shanghai",
                {"outcome": "tasks", "tasks": []},
            )
            self.assertEqual(paused["result"], "no_action")
            self.assertEqual(paused["reason"], "proactive-contact-paused")

    def test_daily_review_allows_at_most_one_completion_question_per_hypothesis(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            evidence_id = self._add_sleep_evidence(store)
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "conclusions": [
                            {
                                **dict(current["conclusions"][0]),
                                "status": "unverified_hypothesis",
                                "completion_question_issued": False,
                            }
                        ],
                    },
                    None,
                ),
            )
            task_base = {
                "task_type": "profile_completion_question",
                "purpose": "核实睡眠变化",
                "evidence_ids": [evidence_id],
                "conclusion_keys": ["sleep"],
                "time_window": {
                    "start_utc": "2026-01-02T20:00:00Z",
                    "end_utc": "2026-01-03T20:00:00Z",
                },
                "valid_until_utc": "2026-01-04T20:00:00Z",
                "policy_constraints": {"low_risk": True},
            }
            result = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                {
                    "outcome": "tasks",
                    "tasks": [
                        {**task_base, "dedupe_key": "hypothesis-question-1"},
                        {**task_base, "dedupe_key": "hypothesis-question-2"},
                    ],
                },
            )
            self.assertEqual(result["result"], "failed")
            self.assertEqual(result["reason"], "completion-question-already-issued")
            self.assertEqual(result["created_tasks"], [])

            clock.now = dt.datetime(2026, 1, 2, 20, 10, tzinfo=dt.timezone.utc)
            status_follow_up = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                {
                    "outcome": "tasks",
                    "tasks": [
                        {
                            **task_base,
                            "task_type": "status_follow_up",
                            "time_window": {
                                "start_utc": "2026-01-02T20:10:00Z",
                                "end_utc": "2026-01-03T20:00:00Z",
                            },
                            "valid_until_utc": "2026-01-04T20:00:00Z",
                            "dedupe_key": "hypothesis-follow-up",
                        }
                    ],
                },
                retry_only=True,
            )
            self.assertEqual(status_follow_up["result"], "failed")
            self.assertEqual(
                status_follow_up["reason"], "hypothesis-requires-completion-question"
            )

    def test_completion_question_lock_survives_terminal_task(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            evidence_id = self._add_sleep_evidence(store)
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "conclusions": [
                            {
                                **dict(current["conclusions"][0]),
                                "status": "unverified_hypothesis",
                                "completion_question_issued": False,
                            }
                        ],
                    },
                    None,
                ),
            )
            task = {
                "task_type": "profile_completion_question",
                "purpose": "核实睡眠变化",
                "evidence_ids": [evidence_id],
                "conclusion_keys": ["sleep"],
                "time_window": {
                    "start_utc": "2026-01-02T20:00:00Z",
                    "end_utc": "2026-01-03T20:00:00Z",
                },
                "valid_until_utc": "2026-01-04T20:00:00Z",
                "dedupe_key": "hypothesis-question",
                "policy_constraints": {"low_risk": True},
            }
            first = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                {"outcome": "tasks", "tasks": [task]},
            )
            self.assertEqual(first["result"], "tasks_created")
            profile = store.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            )
            self.assertTrue(profile["conclusions"][0]["completion_question_issued"])
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "tasks": [
                            {**dict(current["tasks"][0]), "status": "skipped"}
                        ],
                    },
                    None,
                ),
            )
            clock.now = dt.datetime(2026, 1, 3, 20, 0, tzinfo=dt.timezone.utc)
            retry_task = {
                **task,
                "time_window": {
                    "start_utc": "2026-01-03T20:00:00Z",
                    "end_utc": "2026-01-04T20:00:00Z",
                },
                "valid_until_utc": "2026-01-05T20:00:00Z",
                "dedupe_key": "hypothesis-question-again",
            }
            second = store.run_daily_review(
                self.SUBJECT,
                "2026-01-03T20:00:00Z",
                "Asia/Shanghai",
                {"outcome": "tasks", "tasks": [retry_task]},
            )
            self.assertEqual(second["result"], "failed")
            self.assertEqual(second["reason"], "completion-question-already-issued")

    def test_daily_review_rejects_stale_or_future_review_timestamp(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            with self.assertRaisesRegex(ProfileStoreError, "daily-review-date-not-current"):
                store.run_daily_review(
                    self.SUBJECT,
                    "2026-01-01T20:00:00Z",
                    "Asia/Shanghai",
                    {"outcome": "no_action"},
                )
            clock.now = dt.datetime(2026, 1, 2, 19, 58, tzinfo=dt.timezone.utc)
            with self.assertRaisesRegex(ProfileStoreError, "daily-review-time-in-future"):
                store.run_daily_review(
                    self.SUBJECT,
                    "2026-01-02T20:00:00Z",
                    "Asia/Shanghai",
                    {"outcome": "no_action"},
                )

    def test_daily_review_refreshes_expired_profile_lifecycle(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            self._add_sleep_evidence(store)
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "conclusions": [
                            {
                                **dict(current["conclusions"][0]),
                                "valid_until_utc": "2026-01-02T19:00:00+00:00",
                            }
                        ],
                    },
                    None,
                ),
            )
            result = store.run_daily_review(
                self.SUBJECT,
                "2026-01-02T20:00:00Z",
                "Asia/Shanghai",
                {"outcome": "no_action"},
            )
            self.assertTrue(result["maintenance"]["profile_refreshed"])
            profile = store.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            )
            self.assertEqual(profile["profile_summary_zh"], "")
            self.assertEqual(profile["conclusions"], [])

    @unittest.skipIf(not hasattr(socket, "AF_UNIX"), "AF_UNIX not available")
    def test_daily_review_adapter_socket_seam(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store, _ = self._store(root_path)
            evidence_id = self._add_sleep_evidence(store)
            socket_path = root_path / "health.sock"
            ready = threading.Event()
            server = HealthSidecarServer(
                socket_path,
                store,
                allowed_uids={os.getuid()},
                ready_event=ready,
            )
            thread = threading.Thread(target=server.run_forever, daemon=True)
            thread.start()
            self.assertTrue(ready.wait(timeout=3))
            try:
                adapter = PartnerHealthAdapter(str(socket_path), timeout_seconds=1.0)
                snapshot = adapter.daily_review_snapshot(
                    self.SUBJECT, "2026-01-02T20:00:00Z", "Asia/Shanghai"
                )
                self.assertIn("profile", snapshot)
                self.assertIn("evidence", snapshot)
                self.assertNotIn("messages", snapshot)
                result = adapter.run_daily_review(
                    self.SUBJECT,
                    "2026-01-02T20:00:00Z",
                    "Asia/Shanghai",
                    {
                        "outcome": "tasks",
                        "tasks": [
                            {
                                "task_type": "status_follow_up",
                                "purpose": "follow up on sleep status",
                                "evidence_ids": [evidence_id],
                                "conclusion_keys": ["sleep"],
                                "time_window": {
                                    "start_utc": "2026-01-02T20:00:00Z",
                                    "end_utc": "2026-01-03T20:00:00Z",
                                },
                                "valid_until_utc": "2026-01-04T20:00:00Z",
                                "dedupe_key": "socket-sleep-follow-up",
                                "policy_constraints": {"low_risk": True},
                            }
                        ],
                    },
                )
                self.assertEqual(result["result"], "tasks_created")
                self.assertNotIn("text", result["created_tasks"][0])
                self.assertTrue(
                    any(
                        event.get("event") == "daily_review_completed"
                        for event in adapter.read_audit()
                    )
                )
            finally:
                server.stop()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

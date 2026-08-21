from __future__ import annotations

import datetime as dt
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar.profile import ProfileStoreError
from sidecar.ports import build_health_memory_projection
from sidecar.protocol import parse_request
from sidecar.receipt_signer import Ed25519ReceiptSigner
from sidecar.store import HealthSidecarStore, HmacInboundMessageVerifier, StoreError


OWNER = "wx-owner"
SUBJECT = "profile"
STOP_ACTION = "health.recording.stop"
RESUME_ACTION = "health.recording.resume"


class FixedClock:
    def __init__(self, value: dt.datetime) -> None:
        self.value = value

    def now_utc(self) -> dt.datetime:
        return self.value


class RecordingLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.clock = FixedClock(
            dt.datetime(2026, 8, 9, 20, 0, tzinfo=dt.timezone.utc)
        )
        self.verifier = HmacInboundMessageVerifier(b"l" * 32)
        self.state_path = root / "health.state"
        self.key_path = root / "health.key"
        self.store = HealthSidecarStore(
            self.state_path,
            self.key_path,
            clock=self.clock,
            message_verifier=self.verifier,
            expected_owner_sender_id=OWNER,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _receipt(self, action: str, message_id: str) -> tuple[str, str, str]:
        message_utc = self.clock.now_utc().replace(microsecond=0).isoformat()
        token = self.verifier.sign_access_receipt(
            action=action,
            subject=SUBJECT,
            actor_sender_id=OWNER,
            target_sender_id=OWNER,
            message_id=message_id,
            message_utc=message_utc,
        )
        return message_id, message_utc, token

    def _enable_and_admit(self) -> str:
        consent_id, consent_utc, consent_token = self._receipt(
            "health.recording.enable", "consent-1"
        )
        self.store.enable_health_recording(
            SUBJECT, OWNER, consent_id, consent_utc, consent_token
        )
        message_id = "health-1"
        message_utc = self.clock.now_utc().replace(microsecond=0).isoformat()
        text = "最近睡眠不好"
        ingress_token = self.verifier.sign_ingress_receipt(
            action="health.profile.message.admit",
            subject=SUBJECT,
            sender_id=OWNER,
            message_id=message_id,
            message_utc=message_utc,
            attempt_utc=message_utc,
            message_text=text,
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
        )
        result = self.store.admit_consented_profile_candidate(
            subject=SUBJECT,
            sender_id=OWNER,
            message_id=message_id,
            message_utc=message_utc,
            attempt_utc=message_utc,
            message_text=text,
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
            verification_token=ingress_token,
            candidate={
                "evidence_kind": "direct_statement",
                "source_message_id": message_id,
                "source_utc": message_utc,
                "excerpt": text,
                "measurement": None,
                "conclusions": [
                    {
                        "category": "habit_goal",
                        "dedupe_key": "sleep",
                        "text": text,
                        "status": "fact",
                        "priority": 3,
                    }
                ],
            },
        )
        return str(result["evidence_id"])

    def _create_task(self, evidence_id: str) -> str:
        result = self.store.run_daily_review(
            SUBJECT,
            self.clock.now_utc().isoformat(),
            "Asia/Shanghai",
            {
                "outcome": "tasks",
                "tasks": [
                    {
                        "task_type": "status_follow_up",
                        "purpose": "跟进睡眠状态",
                        "evidence_ids": [evidence_id],
                        "conclusion_keys": ["sleep"],
                        "time_window": {
                            "start_utc": self.clock.now_utc().isoformat(),
                            "end_utc": (
                                self.clock.now_utc() + dt.timedelta(days=1)
                            ).isoformat(),
                        },
                        "valid_until_utc": (
                            self.clock.now_utc() + dt.timedelta(days=2)
                        ).isoformat(),
                        "dedupe_key": "sleep-follow-up",
                        "timing_rationale": "owner-time follow-up window",
                        "policy_constraints": {"low_risk": True},
                    }
                ],
            },
        )
        return str(result["created_tasks"][0]["task_id"])

    def test_stop_keeps_record_but_cancels_tasks_and_requires_explicit_resume(self):
        evidence_id = self._enable_and_admit()
        task_id = self._create_task(evidence_id)
        stop = self.store.stop_health_recording(
            SUBJECT, OWNER, *self._receipt(STOP_ACTION, "stop-1")
        )

        self.assertEqual(stop["status"], "recording_stopped")
        self.assertEqual(stop["cancelled_task_count"], 1)
        self.assertFalse(self.store.health_recording_enabled(SUBJECT, OWNER))
        profile = self.store.read_profile(SUBJECT, OWNER)
        self.assertEqual(profile["recording_status"], "recording_stopped")
        task = next(item for item in profile["tasks"] if item["task_id"] == task_id)
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["cancel_reason"], "health-recording-stopped")
        self.assertFalse(profile["proactive_contact"]["paused"])
        projection = build_health_memory_projection(
            SUBJECT, profile, self.clock.now_utc()
        )
        self.assertTrue(projection["proactive_contact"]["paused"])
        self.assertEqual(len(profile["evidence"]), 1)

        stopped_message_utc = self.clock.now_utc().replace(microsecond=0).isoformat()
        stopped_token = self.verifier.sign_ingress_receipt(
            action="health.profile.message.admit",
            subject=SUBJECT,
            sender_id=OWNER,
            message_id="health-while-stopped",
            message_utc=stopped_message_utc,
            attempt_utc=stopped_message_utc,
            message_text="今天还是睡不好",
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
        )
        with self.assertRaisesRegex(ProfileStoreError, "recording-not-enabled"):
            self.store.admit_consented_profile_candidate(
                subject=SUBJECT,
                sender_id=OWNER,
                message_id="health-while-stopped",
                message_utc=stopped_message_utc,
                attempt_utc=stopped_message_utc,
                message_text="今天还是睡不好",
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
                verification_token=stopped_token,
                candidate={
                    "evidence_kind": "direct_statement",
                    "source_message_id": "health-while-stopped",
                    "source_utc": stopped_message_utc,
                    "excerpt": "睡不好",
                    "measurement": None,
                    "conclusions": [],
                },
            )

        with self.assertRaisesRegex(ProfileStoreError, "recording-resume-required"):
            consent_id, consent_utc, consent_token = self._receipt(
                "health.recording.enable", "enable-again"
            )
            self.store.enable_health_recording(
                SUBJECT, OWNER, consent_id, consent_utc, consent_token
            )

        resumed = self.store.resume_health_recording(
            SUBJECT, OWNER, *self._receipt(RESUME_ACTION, "resume-1")
        )
        self.assertEqual(resumed["status"], "recording_enabled")
        self.assertTrue(self.store.health_recording_enabled(SUBJECT, OWNER))
        profile = self.store.read_profile(SUBJECT, OWNER)
        self.assertFalse(profile["proactive_contact"]["paused"])
        self.assertEqual(len(profile["evidence"]), 1)

        with self.assertRaisesRegex(ProfileStoreError, "access-receipt-replayed"):
            self.store.resume_health_recording(
                SUBJECT, OWNER, *self._receipt(RESUME_ACTION, "resume-1")
            )

    def test_stop_changes_nothing_when_receipt_ledger_commit_fails(self):
        self._enable_and_admit()
        before = self.store.read_profile(SUBJECT, OWNER)
        receipt = self._receipt(STOP_ACTION, "stop-ledger-failure")

        with mock.patch.object(
            self.store,
            "consume_access_receipt",
            side_effect=ProfileStoreError("receipt-ledger-write-failed"),
        ), self.assertRaisesRegex(
            ProfileStoreError,
            "receipt-ledger-write-failed",
        ):
            self.store.stop_health_recording(SUBJECT, OWNER, *receipt)

        self.assertTrue(self.store.health_recording_enabled(SUBJECT, OWNER))
        self.assertEqual(self.store.read_profile(SUBJECT, OWNER), before)

    def test_stop_before_first_health_fact_does_not_create_a_profile(self):
        consent_id, consent_utc, consent_token = self._receipt(
            "health.recording.enable", "consent-no-profile"
        )
        self.store.enable_health_recording(
            SUBJECT, OWNER, consent_id, consent_utc, consent_token
        )
        stopped = self.store.stop_health_recording(
            SUBJECT, OWNER, *self._receipt(STOP_ACTION, "stop-no-profile")
        )
        self.assertEqual(stopped["status"], "recording_stopped")
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )
        self.store.resume_health_recording(
            SUBJECT, OWNER, *self._receipt(RESUME_ACTION, "resume-no-profile")
        )
        self.assertTrue(self.store.health_recording_enabled(SUBJECT, OWNER))
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

    def test_stop_completed_before_admission_commit_prevents_the_write(self):
        consent_id, consent_utc, consent_token = self._receipt(
            "health.recording.enable", "consent-race"
        )
        self.store.enable_health_recording(
            SUBJECT, OWNER, consent_id, consent_utc, consent_token
        )
        candidate_started = threading.Event()
        allow_candidate = threading.Event()

        class BlockingCandidate(dict):
            def get(self, key, default=None):
                if key == "evidence_kind" and not candidate_started.is_set():
                    candidate_started.set()
                    if not allow_candidate.wait(2):
                        raise RuntimeError("candidate-test-timeout")
                return super().get(key, default)

        message_utc = self.clock.now_utc().replace(microsecond=0).isoformat()
        message_id = "health-race"
        message_text = "今天头疼"
        token = self.verifier.sign_ingress_receipt(
            action="health.profile.message.admit",
            subject=SUBJECT,
            sender_id=OWNER,
            message_id=message_id,
            message_utc=message_utc,
            attempt_utc=message_utc,
            message_text=message_text,
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
        )
        errors: list[BaseException] = []

        def admit() -> None:
            try:
                self.store.admit_consented_profile_candidate(
                    subject=SUBJECT,
                    sender_id=OWNER,
                    message_id=message_id,
                    message_utc=message_utc,
                    attempt_utc=message_utc,
                    message_text=message_text,
                    evidence_kind="direct_statement",
                    channel="weixin",
                    profile_name="partner",
                    verification_token=token,
                    candidate=BlockingCandidate(
                        {
                            "evidence_kind": "direct_statement",
                            "source_message_id": message_id,
                            "source_utc": message_utc,
                            "excerpt": message_text,
                            "measurement": None,
                            "conclusions": [],
                        }
                    ),
                )
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=admit)
        thread.start()
        self.assertTrue(candidate_started.wait(2))
        self.store.stop_health_recording(
            SUBJECT, OWNER, *self._receipt(STOP_ACTION, "stop-race")
        )
        allow_candidate.set()
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertRegex(str(errors[0]), "recording-not-enabled")
        self.assertEqual(
            self.store.health_recording_status(SUBJECT, OWNER),
            "recording_stopped",
        )
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

    def test_stop_waits_for_an_active_attempt_and_blocks_new_leases(self):
        consent_id, consent_utc, consent_token = self._receipt(
            "health.recording.enable", "consent-lease"
        )
        self.store.enable_health_recording(
            SUBJECT, OWNER, consent_id, consent_utc, consent_token
        )
        lease_id = self.store.begin_recording_attempt(SUBJECT, OWNER)
        results: list[object] = []

        def stop() -> None:
            try:
                results.append(
                    self.store.stop_health_recording(
                        SUBJECT,
                        OWNER,
                        *self._receipt(STOP_ACTION, "stop-active-lease"),
                    )
                )
            except BaseException as exc:
                results.append(exc)

        thread = threading.Thread(target=stop)
        thread.start()
        threading.Event().wait(0.05)
        self.assertTrue(thread.is_alive())
        self.store.end_recording_attempt(lease_id)
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]["status"], "recording_stopped")
        with self.assertRaisesRegex(StoreError, "recording-not-enabled"):
            self.store.begin_recording_attempt(SUBJECT, OWNER)

    def test_recording_resume_preserves_an_independent_owner_proactive_pause(self):
        self._enable_and_admit()
        self.store.pause_proactive_contact(
            SUBJECT,
            OWNER,
            *self._receipt("health.proactive.pause", "owner-pause"),
        )
        self.store.stop_health_recording(
            SUBJECT, OWNER, *self._receipt(STOP_ACTION, "stop-after-pause")
        )
        self.store.resume_health_recording(
            SUBJECT, OWNER, *self._receipt(RESUME_ACTION, "resume-after-pause")
        )

        profile = self.store.read_profile(SUBJECT, OWNER)
        self.assertEqual(profile["recording_status"], "recording_enabled")
        self.assertTrue(profile["proactive_contact"]["paused"])
        self.assertEqual(
            profile["proactive_contact"]["pause_reason"], "owner-request"
        )

    def test_stopped_daily_review_exposes_no_health_snapshot_and_writes_nothing(self):
        self._enable_and_admit()
        self.store.stop_health_recording(
            SUBJECT, OWNER, *self._receipt(STOP_ACTION, "stop-before-review")
        )
        before = self.store.read_profile(SUBJECT, OWNER)
        audit_count = len(self.store.read_operational_audit_events(limit=None))

        snapshot = self.store.daily_review_snapshot(
            SUBJECT, self.clock.now_utc().isoformat(), "Asia/Shanghai"
        )
        result = self.store.run_daily_review(
            SUBJECT,
            self.clock.now_utc().isoformat(),
            "Asia/Shanghai",
            {"outcome": "no_action", "tasks": []},
        )

        self.assertEqual(snapshot["recording_status"], "recording_stopped")
        self.assertEqual(snapshot["profile"], {})
        self.assertEqual(snapshot["evidence"], [])
        self.assertEqual(result["result"], "recording_stopped")
        self.assertEqual(self.store.read_profile(SUBJECT, OWNER), before)
        self.assertEqual(
            len(self.store.read_operational_audit_events(limit=None)), audit_count
        )

    def test_daily_snapshot_is_linearized_with_a_concurrent_recording_stop(self):
        from sidecar.tasks import daily_review_snapshot

        self._enable_and_admit()
        snapshot_read = threading.Event()
        release_snapshot = threading.Event()
        original_read = self.store.read_subject_status
        completion_order: list[str] = []
        results: list[object] = []

        def blocking_read(subject, *args, **kwargs):
            value = original_read(subject, *args, **kwargs)
            if (
                threading.current_thread().name == "daily-snapshot"
                and subject == SUBJECT
                and not snapshot_read.is_set()
            ):
                snapshot_read.set()
                if not release_snapshot.wait(2):
                    raise RuntimeError("daily-snapshot-test-timeout")
            return value

        self.store.read_subject_status = blocking_read

        def take_snapshot() -> None:
            try:
                results.append(
                    daily_review_snapshot(
                        self.store,
                        SUBJECT,
                        self.clock.now_utc().isoformat(),
                        "Asia/Shanghai",
                    )
                )
            except BaseException as exc:
                results.append(exc)
            finally:
                completion_order.append("snapshot")

        def stop_recording() -> None:
            self.store.stop_health_recording(
                SUBJECT, OWNER, *self._receipt(STOP_ACTION, "stop-snapshot-race")
            )
            completion_order.append("stop")

        snapshot_thread = threading.Thread(
            target=take_snapshot, name="daily-snapshot"
        )
        stop_thread = threading.Thread(target=stop_recording, name="recording-stop")
        snapshot_thread.start()
        self.assertTrue(snapshot_read.wait(2))
        stop_thread.start()
        stop_thread.join(0.2)
        release_snapshot.set()
        snapshot_thread.join(2)
        stop_thread.join(2)

        self.assertFalse(snapshot_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], dict)
        if completion_order.index("stop") < completion_order.index("snapshot"):
            self.assertEqual(
                results[0]["recording_status"], "recording_stopped"
            )

    def test_daily_snapshot_maintenance_finishes_before_a_concurrent_stop(self):
        self._enable_and_admit()
        purge_started = threading.Event()
        release_purge = threading.Event()
        original_purge = self.store.purge_expired_backups

        def blocking_purge():
            purge_started.set()
            if not release_purge.wait(2):
                raise RuntimeError("daily-purge-test-timeout")
            return original_purge()

        self.store.purge_expired_backups = blocking_purge
        results: list[object] = []

        def take_snapshot() -> None:
            results.append(
                self.store.daily_review_snapshot(
                    SUBJECT,
                    self.clock.now_utc().isoformat(),
                    "Asia/Shanghai",
                )
            )

        def stop_recording() -> None:
            self.store.stop_health_recording(
                SUBJECT, OWNER, *self._receipt(STOP_ACTION, "stop-purge-race")
            )

        snapshot_thread = threading.Thread(target=take_snapshot)
        stop_thread = threading.Thread(target=stop_recording)
        snapshot_thread.start()
        self.assertTrue(purge_started.wait(2))
        stop_thread.start()
        stop_thread.join(0.2)
        release_purge.set()
        snapshot_thread.join(2)
        stop_thread.join(2)

        self.assertFalse(snapshot_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        events = self.store.read_operational_audit_events(limit=None)
        event_names = [event["event"] for event in events]
        self.assertLess(
            max(
                index
                for index, name in enumerate(event_names)
                if name in {"backup_retention_purge", "daily_review_snapshot"}
            ),
            event_names.index("health_recording_stopped"),
        )

    def test_daily_source_scan_is_cancelled_without_blocking_stop(self):
        self._enable_and_admit()
        scan_started = threading.Event()
        release_scan = threading.Event()
        completion_order: list[str] = []

        class BlockingSourceLibrary:
            def __init__(inner_self, store):
                inner_self.store = store

            def scan(inner_self, _candidates, *, continue_check=None):
                scan_started.set()
                if not release_scan.wait(2):
                    raise RuntimeError("source-scan-test-timeout")
                if continue_check is not None and not continue_check():
                    completion_order.append("scan-cancelled")
                    raise StoreError("health-recording-stopped")
                inner_self.store.mutate_source_library_state(
                    lambda _current: (
                        {"source_schema_version": 1, "scan_marker": "written"},
                        None,
                    )
                )
                completion_order.append("scan-write")
                return {"downloaded": [], "deferred": [], "rejected": []}

        source_library = BlockingSourceLibrary(self.store)
        results: list[object] = []

        def review() -> None:
            results.append(
                self.store.run_daily_review(
                    SUBJECT,
                    self.clock.now_utc().isoformat(),
                    "Asia/Shanghai",
                    {
                        "outcome": "no_action",
                        "maintenance": {
                            "source_scan_candidates": [
                                "https://www.who.int/health"
                            ]
                        },
                    },
                    source_library=source_library,
                )
            )
            completion_order.append("review")

        def stop_recording() -> None:
            self.store.stop_health_recording(
                SUBJECT, OWNER, *self._receipt(STOP_ACTION, "stop-source-race")
            )
            completion_order.append("stop")

        review_thread = threading.Thread(target=review)
        stop_thread = threading.Thread(target=stop_recording)
        review_thread.start()
        self.assertTrue(scan_started.wait(2))
        stop_thread.start()
        stop_thread.join(0.5)
        self.assertFalse(
            stop_thread.is_alive(), "recording stop waited for a blocked source fetch"
        )
        release_scan.set()
        review_thread.join(2)
        stop_thread.join(2)

        self.assertFalse(review_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["result"], "recording_stopped")
        self.assertNotIn("scan-write", completion_order)
        self.assertLess(completion_order.index("stop"), completion_order.index("review"))

    def test_stop_completed_before_daily_commit_prevents_new_tasks(self):
        evidence_id = self._enable_and_admit()
        plan_started = threading.Event()
        allow_plan = threading.Event()

        class BlockingPlan(dict):
            def get(self, key, default=None):
                if key == "outcome" and not plan_started.is_set():
                    plan_started.set()
                    if not allow_plan.wait(2):
                        raise RuntimeError("daily-plan-test-timeout")
                return super().get(key, default)

        plan = BlockingPlan(
            {
                "outcome": "tasks",
                "tasks": [
                    {
                        "task_type": "status_follow_up",
                        "purpose": "并发停止验证",
                        "evidence_ids": [evidence_id],
                        "conclusion_keys": ["sleep"],
                        "time_window": {
                            "start_utc": self.clock.now_utc().isoformat(),
                            "end_utc": (
                                self.clock.now_utc() + dt.timedelta(days=1)
                            ).isoformat(),
                        },
                        "valid_until_utc": (
                            self.clock.now_utc() + dt.timedelta(days=2)
                        ).isoformat(),
                        "dedupe_key": "stop-review-race",
                        "policy_constraints": {"low_risk": True},
                    }
                ],
            }
        )
        results: list[object] = []

        def review() -> None:
            try:
                results.append(
                    self.store.run_daily_review(
                        SUBJECT,
                        self.clock.now_utc().isoformat(),
                        "Asia/Shanghai",
                        plan,
                    )
                )
            except BaseException as exc:
                results.append(exc)

        thread = threading.Thread(target=review)
        thread.start()
        self.assertTrue(plan_started.wait(2))
        self.store.stop_health_recording(
            SUBJECT, OWNER, *self._receipt(STOP_ACTION, "stop-daily-race")
        )
        allow_plan.set()
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], dict)
        self.assertEqual(results[0]["result"], "recording_stopped")
        profile = self.store.read_profile(SUBJECT, OWNER)
        self.assertEqual(profile["recording_status"], "recording_stopped")
        self.assertEqual(profile["tasks"], [])
        self.assertEqual(profile["daily_review_runs"], [])

    def test_stop_during_render_keeps_the_claimed_task_cancelled(self):
        task_id = self._create_task(self._enable_and_admit())
        self.clock.now = self.clock.now_utc() + dt.timedelta(hours=8)
        render_started = threading.Event()
        release_render = threading.Event()

        class BlockingFailureLLM:
            def complete_fresh(inner_self, _prompt, _context, _session_id):
                render_started.set()
                if not release_render.wait(2):
                    raise RuntimeError("dispatch-stop-test-timeout")
                raise RuntimeError("llm-failed")

        class Channel:
            def send_once(self, _recipient, _message, _delivery_key):
                return True

        results: list[object] = []

        def dispatch() -> None:
            results.append(
                self.store.dispatch_due_tasks(
                    SUBJECT,
                    self.clock.now_utc().isoformat(),
                    BlockingFailureLLM(),
                    Channel(),
                )
            )

        thread = threading.Thread(target=dispatch)
        thread.start()
        self.assertTrue(render_started.wait(2), results)
        self.store.stop_health_recording(
            SUBJECT, OWNER, *self._receipt(STOP_ACTION, "stop-dispatch-race")
        )
        release_render.set()
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        profile = self.store.read_profile(SUBJECT, OWNER)
        task = next(item for item in profile["tasks"] if item["task_id"] == task_id)
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["cancel_reason"], "health-recording-stopped")
        self.assertNotIn(task_id, results[0]["retry_after_utc"])

    def test_feedback_is_fixed_idempotent_and_does_not_create_proactive_contact(self):
        self._enable_and_admit()

        class Channel:
            def __init__(self) -> None:
                self.sent = []

            def send_once(self, recipient, message, delivery_key):
                self.sent.append((recipient, message, delivery_key))
                return True

        channel = Channel()
        result = self.store.send_recording_feedback(
            SUBJECT,
            OWNER,
            *self._receipt(
                "health.recording.feedback.backfilled", "feedback-health-1"
            ),
            "backfilled",
            channel,
        )
        self.assertTrue(result["sent"])
        self.assertEqual(
            channel.sent,
            [
                (
                    OWNER,
                    "〔健康管家：已补录〕",
                    "health-recording-feedback:profile:feedback-health-1:backfilled",
                )
            ],
        )
        profile = self.store.read_profile(SUBJECT, OWNER)
        self.assertEqual(profile["tasks"], [])
        audit = self.store.read_operational_audit_events(limit=None)
        self.assertNotIn("已补录", str(audit))

        with self.assertRaisesRegex(ProfileStoreError, "access-receipt-replayed"):
            self.store.send_recording_feedback(
                SUBJECT,
                OWNER,
                *self._receipt(
                    "health.recording.feedback.backfilled", "feedback-health-1"
                ),
                "backfilled",
                channel,
            )
        self.assertEqual(len(channel.sent), 1)

    def test_recent_ordinary_messages_are_ephemeral_capped_and_expire(self):
        self._enable_and_admit()
        for index in range(4):
            self.clock.value += dt.timedelta(hours=1)
            message_id = f"ordinary-{index}"
            message_utc = self.clock.now_utc().replace(microsecond=0).isoformat()
            text = f"普通聊天{index}"
            token = self.verifier.sign_ingress_receipt(
                action="health.profile.message.recent",
                subject=SUBJECT,
                sender_id=OWNER,
                message_id=message_id,
                message_utc=message_utc,
                attempt_utc=message_utc,
                message_text=text,
                evidence_kind="ordinary_chat",
                channel="weixin",
                profile_name="partner",
            )
            self.store.remember_recent_owner_message(
                SUBJECT,
                OWNER,
                message_id,
                message_utc,
                text,
                "ordinary_chat",
                token,
                attempt_utc=message_utc,
                channel="weixin",
                profile_name="partner",
            )

        recent = self.store.recent_profile_messages(SUBJECT, OWNER)
        self.assertEqual(
            [item["message_id"] for item in recent],
            ["ordinary-1", "ordinary-2", "ordinary-3"],
        )
        profile = self.store.read_profile(SUBJECT, OWNER)
        self.assertNotIn("普通聊天", str(profile))

        self.clock.value += dt.timedelta(hours=73)
        self.assertEqual(self.store.recent_profile_messages(SUBJECT, OWNER), [])

        restarted = HealthSidecarStore(
            self.state_path,
            self.key_path,
            clock=self.clock,
            message_verifier=self.verifier,
            expected_owner_sender_id=OWNER,
        )
        self.assertEqual(restarted.recent_profile_messages(SUBJECT, OWNER), [])

    def test_stop_resume_and_feedback_actions_are_supported_by_production_receipts(self):
        private_key = bytes(range(32))
        signer = Ed25519ReceiptSigner(private_key)
        for action in (
            STOP_ACTION,
            RESUME_ACTION,
            "health.recording.feedback.backfilled",
            "health.recording.feedback.not_recorded",
        ):
            token = signer.sign_access(
                action=action,
                subject=SUBJECT,
                actor_sender_id=OWNER,
                target_sender_id=OWNER,
                message_id=f"receipt-{action.rsplit('.', 1)[-1]}",
                message_utc=self.clock.now_utc().isoformat(),
            )
            self.assertTrue(token)

        request = parse_request(
            (
                '{"action":"health.recording.stop","payload":'
                '{"subject":"profile","owner_sender_id":"wx-owner",'
                '"receipt_message_id":"stop-wire","receipt_utc":'
                '"2026-08-09T20:00:00+00:00","verification_token":"token"}}'
            ).encode("utf-8")
        )
        self.assertEqual(request.action, STOP_ACTION)


@unittest.skipUnless(hasattr(socket, "AF_UNIX"), "AF_UNIX required")
class RecordingLifecycleSocketTests(unittest.TestCase):
    def test_adapter_stop_resume_and_reactive_feedback_cross_private_socket(self):
        from sidecar.adapter import PartnerHealthAdapter
        from sidecar.server import HealthSidecarServer

        class Channel:
            def __init__(self) -> None:
                self.sent = []

            def send_once(self, recipient, message, delivery_key):
                self.sent.append((recipient, message, delivery_key))
                return True

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clock = FixedClock(
                dt.datetime(2026, 8, 9, 20, 0, tzinfo=dt.timezone.utc)
            )
            verifier = HmacInboundMessageVerifier(b"s" * 32)
            store = HealthSidecarStore(
                root / "state.enc",
                root / "state.key",
                clock=clock,
                message_verifier=verifier,
                expected_owner_sender_id=OWNER,
            )
            message_utc = clock.now_utc().isoformat()
            enable_token = verifier.sign_access_receipt(
                action="health.recording.enable",
                subject=SUBJECT,
                actor_sender_id=OWNER,
                target_sender_id=OWNER,
                message_id="socket-consent",
                message_utc=message_utc,
            )
            store.enable_health_recording(
                SUBJECT, OWNER, "socket-consent", message_utc, enable_token
            )
            channel = Channel()
            peer_uid = os.getuid() if hasattr(os, "getuid") else 1001
            peer_gid = os.getgid() if hasattr(os, "getgid") else 1001
            socket_path = root / "health.sock"
            ready = threading.Event()
            server = HealthSidecarServer(
                socket_path,
                store,
                allowed_uids={peer_uid},
                allowed_gids={peer_gid},
                ready_event=ready,
                ports=SimpleNamespace(
                    llm=None,
                    source_fetch=None,
                    channel_send=channel,
                    memory_projection=None,
                ),
            )
            server_thread = threading.Thread(target=server.run_forever, daemon=True)
            server_thread.start()
            self.addCleanup(server.stop)
            self.addCleanup(server_thread.join, 2)
            self.assertTrue(ready.wait(3))
            adapter = PartnerHealthAdapter(str(socket_path))

            stop_token = verifier.sign_access_receipt(
                action=STOP_ACTION,
                subject=SUBJECT,
                actor_sender_id=OWNER,
                target_sender_id=OWNER,
                message_id="socket-stop",
                message_utc=message_utc,
            )
            stopped = adapter.stop_health_recording(
                SUBJECT, OWNER, "socket-stop", message_utc, stop_token
            )
            self.assertEqual(stopped["status"], "recording_stopped")
            self.assertEqual(
                adapter.health_recording_status(SUBJECT, OWNER),
                "recording_stopped",
            )

            resume_token = verifier.sign_access_receipt(
                action=RESUME_ACTION,
                subject=SUBJECT,
                actor_sender_id=OWNER,
                target_sender_id=OWNER,
                message_id="socket-resume",
                message_utc=message_utc,
            )
            adapter.resume_health_recording(
                SUBJECT, OWNER, "socket-resume", message_utc, resume_token
            )
            admitted_message_id = "socket-admitted"
            admitted_text = "今天胃不舒服"
            ingress_token = verifier.sign_ingress_receipt(
                action="health.profile.message.admit",
                subject=SUBJECT,
                sender_id=OWNER,
                message_id=admitted_message_id,
                message_utc=message_utc,
                attempt_utc=message_utc,
                message_text=admitted_text,
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
            )
            adapter.admit_consented_profile_candidate(
                subject=SUBJECT,
                sender_id=OWNER,
                message_id=admitted_message_id,
                message_utc=message_utc,
                attempt_utc=message_utc,
                message_text=admitted_text,
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
                verification_token=ingress_token,
                candidate={
                    "evidence_kind": "direct_statement",
                    "source_message_id": admitted_message_id,
                    "source_utc": message_utc,
                    "excerpt": admitted_text,
                    "measurement": None,
                    "conclusions": [],
                },
            )
            self.assertTrue(
                adapter.profile_message_admitted(
                    SUBJECT, OWNER, admitted_message_id
                )
            )
            self.assertFalse(
                adapter.profile_message_admitted(
                    SUBJECT, OWNER, "socket-missing"
                )
            )
            feedback_action = "health.recording.feedback.not_recorded"
            feedback_token = verifier.sign_access_receipt(
                action=feedback_action,
                subject=SUBJECT,
                actor_sender_id=OWNER,
                target_sender_id=OWNER,
                message_id="socket-feedback",
                message_utc=message_utc,
            )
            feedback = adapter.send_recording_feedback(
                SUBJECT,
                OWNER,
                "socket-feedback",
                message_utc,
                feedback_token,
                "not_recorded",
            )
            self.assertTrue(feedback["sent"])
            self.assertEqual(channel.sent[0][1], "〔健康管家：本次未记录〕")


if __name__ == "__main__":
    unittest.main()

import datetime as dt
import os
import socket
import tempfile
import threading
import sys
import unittest
from pathlib import Path
from unittest import mock

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


class LLMFake:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def complete_fresh(self, prompt, context, session_id):
        self.calls.append((prompt, context, session_id))
        if not self.responses:
            raise RuntimeError("no-response")
        return self.responses.pop(0)


class ChannelFake:
    def __init__(self):
        self.sent = []

    def send_once(self, recipient, message, delivery_key):
        self.sent.append((recipient, message, delivery_key))
        return True


class ProactiveContactTests(unittest.TestCase):
    SUBJECT = "profile"
    OWNER = "owner-1"
    NOW = dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc)

    def _store(self, root: Path):
        clock = FixedClock(self.NOW)
        store = HealthSidecarStore(
            root / "state.sqlite.enc", root / "sidecar.key", clock=clock
        )
        token = store.message_verifier.sign_owner_binding(
            subject=self.SUBJECT, owner_sender_id=self.OWNER
        )
        self.assertTrue(store.bind_profile_owner(self.SUBJECT, self.OWNER, token))
        return store, clock

    def _evidence(self, store: HealthSidecarStore, message_id="sleep-message"):
        message_utc = "2026-01-02T19:55:00Z"
        text = "sleep is poor"
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

    def _task(self, evidence_id, *, topic_key="sleep", rationale=None):
        task = {
            "task_type": "status_follow_up",
            "purpose": "follow up on sleep",
            "evidence_ids": [evidence_id],
            "conclusion_keys": ["sleep"],
            "topic_key": topic_key,
            "time_window": {
                "start_utc": "2026-01-02T20:00:00Z",
                "end_utc": "2026-01-03T20:00:00Z",
            },
            "valid_until_utc": "2026-01-04T20:00:00Z",
            "dedupe_key": f"sleep-{topic_key}",
            "policy_constraints": {"low_risk": True},
        }
        if rationale is not None:
            task["timing_rationale"] = rationale
        return task

    def _review(self, store, plan, review_utc="2026-01-02T20:00:00Z"):
        return store.run_daily_review(
            self.SUBJECT, review_utc, "Asia/Shanghai", plan
        )

    def _receipt(self, store, action, message_id, message_utc, pause_until_utc=None):
        return store.message_verifier.sign_access_receipt(
            action=action,
            subject=self.SUBJECT,
            actor_sender_id=self.OWNER,
            target_sender_id=self.OWNER,
            message_id=message_id,
            message_utc=message_utc,
            pause_until_utc=pause_until_utc,
        )

    def test_same_purpose_is_not_recreated_when_unfinished_task_has_other_key(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            evidence_id = self._evidence(store)
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "conclusions": [
                            {
                                **dict(current["conclusions"][0]),
                                "valid_until_utc": "2026-01-10T20:00:00+00:00",
                            }
                        ],
                    },
                    None,
                ),
            )
            first = self._review(
                store, {"outcome": "tasks", "tasks": [self._task(evidence_id)]}
            )
            self.assertEqual(first["result"], "tasks_created")
            clock.now = dt.datetime(2026, 1, 3, 20, 0, tzinfo=dt.timezone.utc)
            repeat = self._task(evidence_id)
            repeat["dedupe_key"] = "different-key"
            repeat["time_window"] = {
                "start_utc": "2026-01-03T20:00:00Z",
                "end_utc": "2026-01-04T20:00:00Z",
            }
            repeat["valid_until_utc"] = "2026-01-05T20:00:00Z"
            result = self._review(
                store, {"outcome": "tasks", "tasks": [repeat]},
                "2026-01-03T20:00:00Z",
            )
            self.assertEqual(result["result"], "no_action")
            self.assertEqual(len(result["created_tasks"]), 0)
            self.assertEqual(result["reason"], "unfinished-purpose")

    def test_unanswered_topic_waits_72_hours_and_owner_reply_releases_backoff(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            evidence_id = self._evidence(store)
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "conclusions": [
                            {
                                **dict(current["conclusions"][0]),
                                "valid_until_utc": "2026-01-10T20:00:00+00:00",
                            }
                        ],
                    },
                    None,
                ),
            )
            first = self._review(
                store,
                {"outcome": "tasks", "tasks": [self._task(evidence_id, rationale="owner-time window")],},
            )
            task_id = first["created_tasks"][0]["task_id"]
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "tasks": [
                            {
                                **dict(current["tasks"][0]),
                                "status": "sent",
                                "sent_utc": self.NOW.isoformat(),
                            }
                        ],
                    },
                    None,
                ),
            )
            clock.now = dt.datetime(2026, 1, 3, 20, 0, tzinfo=dt.timezone.utc)
            repeat = self._task(evidence_id, rationale="owner-time window")
            repeat["topic_key"] = "renamed-by-model"
            repeat["dedupe_key"] = "sleep-repeat"
            repeat["time_window"] = {
                "start_utc": "2026-01-03T20:00:00Z",
                "end_utc": "2026-01-04T20:00:00Z",
            }
            repeat["valid_until_utc"] = "2026-01-05T20:00:00Z"
            blocked = self._review(
                store, {"outcome": "tasks", "tasks": [repeat]},
                "2026-01-03T20:00:00Z",
            )
            self.assertEqual(blocked["result"], "no_action")
            self.assertEqual(blocked["reason"], "unanswered-topic-backoff")
            self.assertEqual(store.read_subject_status(self.SUBJECT, _allow_profile_state=True)["tasks"][0]["task_id"], task_id)

            reply_id = "reply-message"
            reply_text = "I am better now"
            token = store.message_verifier.sign(
                subject=self.SUBJECT,
                sender_id=self.OWNER,
                message_id=reply_id,
                message_utc="2026-01-03T20:05:00Z",
                message_text=reply_text,
                evidence_kind="ordinary_chat",
            )
            store.remember_recent_owner_message(
                self.SUBJECT,
                self.OWNER,
                reply_id,
                "2026-01-03T20:05:00Z",
                reply_text,
                "ordinary_chat",
                token,
            )
            clock.now = dt.datetime(2026, 1, 4, 20, 0, tzinfo=dt.timezone.utc)
            repeat["time_window"] = {
                "start_utc": "2026-01-04T20:00:00Z",
                "end_utc": "2026-01-05T20:00:00Z",
            }
            repeat["valid_until_utc"] = "2026-01-06T20:00:00Z"
            allowed = self._review(
                store, {"outcome": "tasks", "tasks": [repeat]},
                "2026-01-04T20:00:00Z",
            )
            self.assertEqual(allowed["result"], "tasks_created")

    def test_night_send_requires_reviewable_timing_rationale(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            evidence_id = self._evidence(store)
            plan = {"outcome": "tasks", "tasks": [self._task(evidence_id)]}
            created = self._review(store, plan)
            task_id = created["created_tasks"][0]["task_id"]
            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.NOW.isoformat(),
                LLMFake([{"decision": "send", "message": "check", "reason": "ok"}]),
                ChannelFake(),
            )
            self.assertEqual(result["skipped"], [task_id])
            self.assertEqual(result["reasons"][task_id], "night-timing-rationale-missing")

    def test_superseding_conclusion_skips_before_send(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            evidence_id = self._evidence(store)
            created = self._review(
                store,
                {
                    "outcome": "tasks",
                    "tasks": [self._task(evidence_id, rationale="owner-time window")],
                },
            )
            task_id = created["created_tasks"][0]["task_id"]
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "conclusions": [
                            {
                                **dict(current["conclusions"][0]),
                                "last_evidence_utc": "2026-01-02T19:59:00+00:00",
                            }
                        ],
                    },
                    None,
                ),
            )
            channel = ChannelFake()
            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.NOW.isoformat(),
                LLMFake([{"decision": "send", "message": "must not send", "reason": "stale"}]),
                channel,
            )
            self.assertEqual(result["skipped"], [task_id])
            self.assertEqual(result["reasons"][task_id], "conclusion-superseded")
            self.assertEqual(channel.sent, [])

    def test_capacity_exhaustion_skips_without_catch_up(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            evidence_id = self._evidence(store)
            created = self._review(
                store,
                {"outcome": "tasks", "tasks": [self._task(evidence_id, rationale="owner-time window")]},
            )
            task_id = created["created_tasks"][0]["task_id"]
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            sent = [
                {
                    "task_id": f"sent-{index}",
                    "status": "sent",
                    "sent_utc": self.NOW.isoformat(),
                    "purpose": f"sent-{index}",
                    "topic_key": f"sent-{index}",
                    "dedupe_key": f"sent-{index}",
                }
                for index in range(100)
            ]
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: ({**dict(current), "tasks": [*sent, *current["tasks"]]}, None),
            )
            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.NOW.isoformat(),
                LLMFake([{"decision": "send", "message": "must not send", "reason": "ok"}]),
                ChannelFake(),
            )
            self.assertEqual(result["skipped"], [task_id])
            self.assertEqual(result["reasons"][task_id], "capacity_exhausted")
            self.assertEqual(result["failed"], [])

    def test_owner_pause_cancels_waiting_tasks_but_resume_is_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            evidence_id = self._evidence(store)
            created = self._review(
                store,
                {"outcome": "tasks", "tasks": [self._task(evidence_id, rationale="owner-time window")]},
            )
            self.assertEqual(created["result"], "tasks_created")
            pause_utc = self.NOW.isoformat()
            pause_token = self._receipt(
                store, "health.proactive.pause", "pause-1", pause_utc
            )
            paused = store.pause_proactive_contact(
                self.SUBJECT,
                self.OWNER,
                "pause-1",
                pause_utc,
                pause_token,
                None,
            )
            self.assertTrue(paused["paused"])
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertEqual(profile["tasks"][0]["status"], "cancelled")
            self.assertEqual(profile["tasks"][0]["cancel_reason"], "proactive-contact-paused")
            clock.now = dt.datetime(2026, 1, 5, 20, 0, tzinfo=dt.timezone.utc)
            review = self._review(
                store,
                {"outcome": "no_action"},
                "2026-01-05T20:00:00Z",
            )
            self.assertEqual(review["reason"], "proactive-contact-paused")
            resume_utc = clock.now.isoformat()
            resume_token = self._receipt(
                store, "health.proactive.resume", "resume-1", resume_utc
            )
            resumed = store.resume_proactive_contact(
                self.SUBJECT,
                self.OWNER,
                "resume-1",
                resume_utc,
                resume_token,
            )
            self.assertTrue(resumed["resumed"])
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertFalse(profile["proactive_contact"]["paused"])

    def test_pause_changes_nothing_when_receipt_ledger_commit_fails(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            before = store.read_subject_status(
                self.SUBJECT,
                _allow_profile_state=True,
            )
            pause_utc = self.NOW.isoformat()
            pause_token = self._receipt(
                store,
                "health.proactive.pause",
                "pause-ledger-failure",
                pause_utc,
            )

            with mock.patch.object(
                store,
                "consume_access_receipt",
                side_effect=ProfileStoreError("receipt-ledger-write-failed"),
            ), self.assertRaisesRegex(
                ProfileStoreError,
                "receipt-ledger-write-failed",
            ):
                store.pause_proactive_contact(
                    self.SUBJECT,
                    self.OWNER,
                    "pause-ledger-failure",
                    pause_utc,
                    pause_token,
                    None,
                )

            self.assertEqual(
                store.read_subject_status(
                    self.SUBJECT,
                    _allow_profile_state=True,
                ),
                before,
            )

    def test_finite_pause_expires_without_an_explicit_resume(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            evidence_id = self._evidence(store)
            pause_utc = self.NOW.isoformat()
            pause_until_utc = "2026-01-02T20:00:30Z"
            pause_token = self._receipt(
                store,
                "health.proactive.pause",
                "finite-pause",
                pause_utc,
                pause_until_utc,
            )
            store.pause_proactive_contact(
                self.SUBJECT,
                self.OWNER,
                "finite-pause",
                pause_utc,
                pause_token,
                pause_until_utc,
            )
            clock.now = dt.datetime(2026, 1, 2, 20, 1, tzinfo=dt.timezone.utc)
            plan = self._task(evidence_id, rationale="owner-time window")
            plan["time_window"] = {
                "start_utc": "2026-01-02T20:01:00Z",
                "end_utc": "2026-01-03T20:01:00Z",
            }
            plan["valid_until_utc"] = "2026-01-04T20:01:00Z"
            result = self._review(
                store,
                {"outcome": "tasks", "tasks": [plan]},
                "2026-01-02T20:00:00Z",
            )
            self.assertEqual(result["result"], "tasks_created")

    def test_pause_does_not_block_realtime_owner_message_or_candidate(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            pause_utc = self.NOW.isoformat()
            pause_token = self._receipt(
                store, "health.proactive.pause", "pause-realtime", pause_utc
            )
            store.pause_proactive_contact(
                self.SUBJECT,
                self.OWNER,
                "pause-realtime",
                pause_utc,
                pause_token,
                None,
            )
            message_id = "paused-owner-message"
            message_text = "sleep remains poor"
            token = store.message_verifier.sign(
                subject=self.SUBJECT,
                sender_id=self.OWNER,
                message_id=message_id,
                message_utc="2026-01-02T20:05:00Z",
                message_text=message_text,
                evidence_kind="direct_statement",
            )
            self.assertTrue(
                store.stage_profile_message(
                    self.SUBJECT,
                    self.OWNER,
                    message_id,
                    "2026-01-02T20:05:00Z",
                    message_text,
                    "direct_statement",
                    token,
                )
            )
            result = store.record_profile_candidate(
                self.SUBJECT,
                self.OWNER,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": message_id,
                    "source_utc": "2026-01-02T20:05:00Z",
                    "excerpt": message_text,
                    "conclusions": [],
                },
            )
            self.assertIn("evidence_id", result)

    def test_direct_statement_marks_previous_proactive_contact_answered(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            evidence_id = self._evidence(store)
            created = self._review(
                store,
                {"outcome": "tasks", "tasks": [self._task(evidence_id, rationale="owner-time window")]},
            )
            task_id = created["created_tasks"][0]["task_id"]
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "tasks": [
                            {
                                **dict(current["tasks"][0]),
                                "status": "sent",
                                "sent_utc": self.NOW.isoformat(),
                            }
                        ],
                    },
                    None,
                ),
            )
            message_id = "direct-reply"
            message_utc = "2026-01-02T20:05:00Z"
            text = "睡眠已经好一些了"
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
            task = next(
                item
                for item in store.read_subject_status(self.SUBJECT, _allow_profile_state=True)["tasks"]
                if item["task_id"] == task_id
            )
            self.assertEqual(task["owner_reply_utc"], "2026-01-02T20:05:00+00:00")

    def test_naive_owner_message_time_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            message_id = "naive-owner-message"
            message_utc = "2026-01-02T20:05:00"
            text = "普通聊天"
            token = store.message_verifier.sign(
                subject=self.SUBJECT,
                sender_id=self.OWNER,
                message_id=message_id,
                message_utc=message_utc,
                message_text=text,
                evidence_kind="ordinary_chat",
            )
            with self.assertRaisesRegex(ProfileStoreError, "invalid-owner-reply-time"):
                store.remember_recent_owner_message(
                    self.SUBJECT,
                    self.OWNER,
                    message_id,
                    message_utc,
                    text,
                    "ordinary_chat",
                    token,
                )

    def test_naive_control_receipt_time_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            message_id = "naive-pause-receipt"
            message_utc = "2026-01-02T20:00:00"
            token = self._receipt(store, "health.proactive.pause", message_id, message_utc)
            with self.assertRaisesRegex(ProfileStoreError, "invalid-access-receipt-utc"):
                store.pause_proactive_contact(
                    self.SUBJECT,
                    self.OWNER,
                    message_id,
                    message_utc,
                    token,
                    None,
                )

    def test_pause_receipt_binds_requested_duration(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            message_id = "bound-pause-receipt"
            message_utc = self.NOW.isoformat()
            signed_until = "2026-01-02T20:00:30Z"
            token = self._receipt(
                store,
                "health.proactive.pause",
                message_id,
                message_utc,
                signed_until,
            )
            with self.assertRaisesRegex(ProfileStoreError, "unverified-access-receipt"):
                store.pause_proactive_contact(
                    self.SUBJECT,
                    self.OWNER,
                    message_id,
                    message_utc,
                    token,
                    "2026-01-02T20:01:00Z",
                )

    def test_pause_and_resume_receipts_are_one_time_under_concurrency(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))

            def run_concurrently(callback):
                barrier = threading.Barrier(2)
                outcomes = []

                def invoke():
                    barrier.wait()
                    try:
                        callback()
                    except Exception as exc:  # noqa: BLE001 - assert the public error code below
                        outcomes.append(("error", str(exc)))
                    else:
                        outcomes.append(("ok", ""))

                threads = [threading.Thread(target=invoke) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)
                self.assertFalse(any(thread.is_alive() for thread in threads))
                return outcomes

            pause_utc = self.NOW.isoformat()
            pause_token = self._receipt(store, "health.proactive.pause", "race-pause", pause_utc)
            pause_outcomes = run_concurrently(
                lambda: store.pause_proactive_contact(
                    self.SUBJECT,
                    self.OWNER,
                    "race-pause",
                    pause_utc,
                    pause_token,
                    None,
                )
            )
            self.assertEqual(sorted(outcome[0] for outcome in pause_outcomes), ["error", "ok"])
            self.assertIn("access-receipt-replayed", " ".join(outcome[1] for outcome in pause_outcomes))

            resume_utc = self.NOW.isoformat()
            resume_token = self._receipt(store, "health.proactive.resume", "race-resume", resume_utc)
            resume_outcomes = run_concurrently(
                lambda: store.resume_proactive_contact(
                    self.SUBJECT,
                    self.OWNER,
                    "race-resume",
                    resume_utc,
                    resume_token,
                )
            )
            self.assertEqual(sorted(outcome[0] for outcome in resume_outcomes), ["error", "ok"])
            self.assertIn("access-receipt-replayed", " ".join(outcome[1] for outcome in resume_outcomes))

    @unittest.skipIf(not hasattr(socket, "AF_UNIX"), "AF_UNIX not available")
    def test_pause_resume_partner_adapter_socket_seam(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store, _ = self._store(root_path)
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
                pause_utc = self.NOW.isoformat()
                pause_token = self._receipt(
                    store, "health.proactive.pause", "socket-pause", pause_utc
                )
                paused = adapter.pause_proactive_contact(
                    self.SUBJECT,
                    self.OWNER,
                    "socket-pause",
                    pause_utc,
                    pause_token,
                    None,
                )
                self.assertTrue(paused["paused"])
                resume_utc = self.NOW.isoformat()
                resume_token = self._receipt(
                    store, "health.proactive.resume", "socket-resume", resume_utc
                )
                resumed = adapter.resume_proactive_contact(
                    self.SUBJECT,
                    self.OWNER,
                    "socket-resume",
                    resume_utc,
                    resume_token,
                )
                self.assertTrue(resumed["resumed"])
            finally:
                server.stop()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

import datetime as dt
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

from sidecar import HealthSidecarServer, HealthStewardPorts, PartnerHealthAdapter
from sidecar.store import HealthSidecarStore
from sidecar.weixin_delivery import ChannelSendUncertainError


class FixedClock:
    def __init__(self, now: dt.datetime):
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class LLMFake:
    def __init__(self, responses=None, error: Exception | None = None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []
        self.session_ids = []

    def complete(self, prompt, context):
        self.calls.append((prompt, context))
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise RuntimeError("no-llm-response")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def complete_fresh(self, prompt, context, session_id):
        self.session_ids.append(session_id)
        return self.complete(prompt, context)


class ChannelFake:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.sent = []
        self.delivery_keys = []

    def send(self, recipient: str, message: str) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((recipient, message))

    def send_once(self, recipient: str, message: str, delivery_key: str) -> bool:
        if self.error is not None:
            raise self.error
        if delivery_key not in self.delivery_keys:
            self.delivery_keys.append(delivery_key)
            self.sent.append((recipient, message))
        return True


class DispatchTests(unittest.TestCase):
    SUBJECT = "profile"
    OWNER = "owner-1"
    REVIEW_UTC = "2026-01-02T20:00:00Z"

    def _store(self, root: Path):
        clock = FixedClock(dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc))
        store = HealthSidecarStore(root / "state.sqlite.enc", root / "sidecar.key", clock=clock)
        token = store.message_verifier.sign_owner_binding(
            subject=self.SUBJECT, owner_sender_id=self.OWNER
        )
        self.assertTrue(store.bind_profile_owner(self.SUBJECT, self.OWNER, token))
        return store, clock

    def _add_evidence(self, store: HealthSidecarStore) -> str:
        message_id = "dispatch-message"
        message_utc = "2026-01-02T19:55:00Z"
        text = "最近睡眠不太好"
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

    def _add_task(self, store: HealthSidecarStore) -> str:
        evidence_id = self._add_evidence(store)
        result = store.run_daily_review(
            self.SUBJECT,
            self.REVIEW_UTC,
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
                            "start_utc": self.REVIEW_UTC,
                            "end_utc": "2026-01-03T20:00:00Z",
                        },
                        "valid_until_utc": "2026-01-04T20:00:00Z",
                        "dedupe_key": "dispatch-sleep-follow-up",
                        "timing_rationale": "owner-time window",
                        "policy_constraints": {"low_risk": True},
                    }
                ],
            },
        )
        self.assertEqual(result["result"], "tasks_created")
        return str(result["created_tasks"][0]["task_id"])

    def test_dispatch_renders_from_current_snapshot_and_sends_without_persisting_copy(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            task_id = self._add_task(store)
            llm = LLMFake(
                [{"decision": "send", "message": "最近睡眠怎么样？", "reason": "follow-up"}]
            )
            channel = ChannelFake()

            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.REVIEW_UTC,
                llm,
                channel,
            )

            self.assertEqual(result["sent"], [task_id])
            self.assertEqual(channel.sent, [(self.OWNER, "最近睡眠怎么样？")])
            self.assertEqual(llm.calls[0][1]["task"]["task_id"], task_id)
            self.assertEqual(len(llm.session_ids), 1)
            self.assertTrue(llm.session_ids[0].startswith("dispatch:profile:"))
            self.assertIn("profile", llm.calls[0][1])
            self.assertIn("evidence", llm.calls[0][1])
            self.assertIn("recent_messages", llm.calls[0][1])
            self.assertEqual(len(llm.calls[0][1]["recent_messages"]), 1)
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            task = profile["tasks"][0]
            self.assertEqual(task["status"], "sent")
            self.assertNotIn("message", task)
            self.assertTrue(
                any(event["event"] == "task_sent" for event in store.read_audit_events())
            )
            self.assertNotIn("最近睡眠怎么样？", str(store.read_audit_events()))

            sent_event = next(
                event for event in store.read_audit_events() if event["event"] == "task_sent"
            )
            self.assertEqual(sent_event["details"]["actor_role"], "dispatcher")
            self.assertEqual(sent_event["details"]["action"], "task.send")
            self.assertEqual(sent_event["details"]["object_id"], task_id)
            self.assertEqual(sent_event["details"]["result"], "sent")
            self.assertIn("evidence_ids", sent_event["details"])

    def test_snapshot_can_include_verified_ordinary_chat_without_profile_write(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            token = store.message_verifier.sign(
                subject=self.SUBJECT,
                sender_id=self.OWNER,
                message_id="chat-1",
                message_utc="2026-01-02T19:50:00Z",
                message_text="今天看了部电影",
                evidence_kind="ordinary_chat",
            )
            self.assertTrue(
                store.remember_recent_owner_message(
                    self.SUBJECT,
                    self.OWNER,
                    "chat-1",
                    "2026-01-02T19:50:00Z",
                    "今天看了部电影",
                    "ordinary_chat",
                    token,
                )
            )
            self.assertEqual(
                store.recent_profile_messages(self.SUBJECT, self.OWNER)[-1]["message_id"],
                "chat-1",
            )
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertEqual(profile["evidence"], [])

    def test_dispatch_skips_when_pause_or_conclusion_is_invalid(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            self._add_task(store)
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "proactive_contact": {"paused": True},
                    },
                    None,
                ),
            )
            llm = LLMFake()
            channel = ChannelFake()
            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.REVIEW_UTC,
                llm,
                channel,
            )
            self.assertEqual(len(result["skipped"]), 1)
            self.assertEqual(llm.calls, [])
            self.assertEqual(channel.sent, [])
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertEqual(profile["tasks"][0]["status"], "skipped")

    def test_dispatch_preserves_model_skip_reason_and_rechecks_pause_before_send(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            task_id = self._add_task(store)

            class PausingLLM(LLMFake):
                def complete(inner_self, prompt, context):
                    store.mutate_subject_status(
                        self.SUBJECT,
                        lambda current: (
                            {**dict(current), "proactive_contact": {"paused": True}},
                            None,
                        ),
                    )
                    return {"decision": "send", "message": "不应发送", "reason": "stale"}

            llm = PausingLLM()
            channel = ChannelFake()
            result = store.dispatch_due_tasks(self.SUBJECT, self.REVIEW_UTC, llm, channel)
            self.assertEqual(result["skipped"], [task_id])
            self.assertEqual(channel.sent, [])
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertEqual(profile["tasks"][0]["status"], "skipped")
            self.assertEqual(profile["tasks"][0]["skip_reason"], "proactive-contact-paused")

    def test_dispatch_rechecks_window_after_slow_render(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            task_id = self._add_task(store)

            class SlowLLM(LLMFake):
                def complete(inner_self, prompt, context):
                    clock.now = dt.datetime(2026, 1, 3, 20, 1, tzinfo=dt.timezone.utc)
                    return {"decision": "send", "message": "过期不发送", "reason": "late"}

            channel = ChannelFake()
            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.REVIEW_UTC,
                SlowLLM(),
                channel,
            )
            self.assertEqual(result["skipped"], [task_id])
            self.assertEqual(channel.sent, [])
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertEqual(profile["tasks"][0]["status"], "skipped")
            self.assertEqual(profile["tasks"][0]["skip_reason"], "task-window-expired")

    def test_dispatch_rejects_unverified_and_duplicate_premises(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            task_id = self._add_task(store)
            store.mutate_subject_status(
                self.SUBJECT,
                lambda current: (
                    {
                        **dict(current),
                        "conclusions": [
                            {
                                **dict(current["conclusions"][0]),
                                "status": "unverified_hypothesis",
                            }
                        ],
                    },
                    None,
                ),
            )
            result = store.dispatch_due_tasks(
                self.SUBJECT, self.REVIEW_UTC, LLMFake(), ChannelFake()
            )
            self.assertEqual(result["skipped"], [task_id])

    def test_dispatch_uses_idempotent_delivery_key_for_retry(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            task_id = self._add_task(store)

            class FlakyChannel(ChannelFake):
                def __init__(inner_self):
                    super().__init__()
                    inner_self.calls = 0

                def send_once(inner_self, recipient, message, delivery_key):
                    inner_self.calls += 1
                    if inner_self.calls == 1:
                        raise RuntimeError("temporary")
                    return super(FlakyChannel, inner_self).send_once(
                        recipient, message, delivery_key
                    )

            channel = FlakyChannel()
            llm = LLMFake(
                [
                    {"decision": "send", "message": "问候", "reason": "follow-up"},
                    {"decision": "send", "message": "问候", "reason": "follow-up"},
                ]
            )
            first = store.dispatch_due_tasks(self.SUBJECT, self.REVIEW_UTC, llm, channel)
            self.assertEqual(first["failed"], [task_id])
            clock.now = dt.datetime(2026, 1, 2, 20, 15, tzinfo=dt.timezone.utc)
            second = store.dispatch_due_tasks(self.SUBJECT, clock.now.isoformat(), llm, channel)
            self.assertEqual(second["sent"], [task_id])
            self.assertEqual(len(set(channel.delivery_keys)), 1)

    def test_dispatch_fails_closed_for_non_idempotent_channel(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            task_id = self._add_task(store)

            class LegacyChannel:
                def __init__(self):
                    self.sent = []

                def send(self, recipient, message):
                    self.sent.append((recipient, message))

            channel = LegacyChannel()
            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.REVIEW_UTC,
                LLMFake([{"decision": "send", "message": "不应调用", "reason": "test"}]),
                channel,
            )
            self.assertEqual(result["failed"], [task_id])
            self.assertEqual(channel.sent, [])

    def test_dispatch_retries_llm_failure_once_after_fifteen_minutes(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            task_id = self._add_task(store)
            llm = LLMFake(error=RuntimeError("model unavailable"))
            channel = ChannelFake()

            first = store.dispatch_due_tasks(
                self.SUBJECT,
                self.REVIEW_UTC,
                llm,
                channel,
            )
            self.assertEqual(first["failed"], [task_id])
            self.assertEqual(
                first["retry_after_utc"][task_id], "2026-01-02T20:15:00+00:00"
            )
            clock.now = dt.datetime(2026, 1, 2, 20, 5, tzinfo=dt.timezone.utc)
            not_due = store.dispatch_due_tasks(
                self.SUBJECT,
                clock.now.isoformat(),
                llm,
                channel,
            )
            self.assertEqual(not_due["retry_not_due"], [task_id])
            clock.now = dt.datetime(2026, 1, 2, 20, 15, tzinfo=dt.timezone.utc)
            second = store.dispatch_due_tasks(
                self.SUBJECT,
                clock.now.isoformat(),
                llm,
                channel,
            )
            self.assertEqual(second["failed"], [task_id])
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertEqual(profile["tasks"][0]["status"], "failed")

    def test_render_failure_cannot_revive_a_task_cancelled_by_recording_stop(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            task_id = self._add_task(store)
            render_started = threading.Event()
            release_render = threading.Event()

            class BlockingFailureLLM(LLMFake):
                def complete(inner_self, prompt, context):
                    render_started.set()
                    if not release_render.wait(2):
                        raise RuntimeError("dispatch-race-test-timeout")
                    raise RuntimeError("llm-failed")

            results: list[object] = []

            def dispatch() -> None:
                try:
                    results.append(
                        store.dispatch_due_tasks(
                            self.SUBJECT,
                            self.REVIEW_UTC,
                            BlockingFailureLLM(),
                            ChannelFake(),
                        )
                    )
                except BaseException as exc:
                    results.append(exc)

            thread = threading.Thread(target=dispatch)
            thread.start()
            self.assertTrue(render_started.wait(2))

            def stop_state(current):
                profile = dict(current)
                tasks = []
                for item in profile.get("tasks", []):
                    task = dict(item)
                    if task.get("task_id") == task_id:
                        task.update(
                            {
                                "status": "cancelled",
                                "cancel_reason": "health-recording-stopped",
                                "dispatch_claim_id": None,
                                "dispatch_claimed_utc": None,
                            }
                        )
                    tasks.append(task)
                profile["tasks"] = tasks
                profile["recording_status"] = "recording_stopped"
                return profile, None

            store.mutate_subject_status(self.SUBJECT, stop_state)
            release_render.set()
            thread.join(2)

            self.assertFalse(thread.is_alive())
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], dict)
            profile = store.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            )
            task = next(item for item in profile["tasks"] if item["task_id"] == task_id)
            self.assertEqual(task["status"], "cancelled")
            self.assertEqual(task["cancel_reason"], "health-recording-stopped")
            self.assertIsNone(task.get("retry_after_utc"))
            self.assertNotIn(task_id, results[0]["retry_after_utc"])

    def test_stale_unclaimed_failure_cannot_clear_another_dispatcher_claim(self):
        from sidecar.dispatch import _claim_task, _failure_update

        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            task_id = self._add_task(store)
            profile = store.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            )
            stale_task = next(
                dict(item) for item in profile["tasks"] if item["task_id"] == task_id
            )
            claimed = _claim_task(store, self.SUBJECT, task_id, clock.now_utc())
            self.assertIsNotNone(claimed)
            active_claim_id = claimed[1]["dispatch_claim_id"]

            failure = _failure_update(
                store,
                self.SUBJECT,
                stale_task,
                clock.now_utc(),
                "dispatch-dependency-unavailable",
            )

            self.assertIsNone(failure)
            profile = store.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            )
            task = next(item for item in profile["tasks"] if item["task_id"] == task_id)
            self.assertEqual(task["dispatch_claim_id"], active_claim_id)
            self.assertEqual(task["dispatch_attempts"], 0)

    def test_dispatch_retries_channel_failure_without_persisting_message(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            task_id = self._add_task(store)
            llm = LLMFake(
                [
                    {"decision": "send", "message": "睡眠怎么样？", "reason": "follow-up"},
                    {"decision": "send", "message": "睡眠怎么样？", "reason": "follow-up"},
                ]
            )
            channel = ChannelFake(error=RuntimeError("channel unavailable"))
            first = store.dispatch_due_tasks(
                self.SUBJECT, self.REVIEW_UTC, llm, channel
            )
            self.assertEqual(first["failed"], [task_id])
            clock.now = dt.datetime(2026, 1, 2, 20, 15, tzinfo=dt.timezone.utc)
            second = store.dispatch_due_tasks(
                self.SUBJECT, clock.now.isoformat(), llm, channel
            )
            self.assertEqual(second["failed"], [task_id])
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertEqual(profile["tasks"][0]["status"], "failed")
            self.assertNotIn("message", profile["tasks"][0])

    def test_dispatch_never_retries_an_uncertain_weixin_handoff(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            task_id = self._add_task(store)

            class UncertainChannel:
                def send_once(self, _recipient, _message, _delivery_key):
                    raise ChannelSendUncertainError("channel-send-uncertain")

            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.REVIEW_UTC,
                LLMFake(
                    [
                        {
                            "decision": "send",
                            "message": "不能自动重发",
                            "reason": "follow-up",
                        }
                    ]
                ),
                UncertainChannel(),
            )

            self.assertEqual(result["failed"], [task_id])
            self.assertNotIn(task_id, result["retry_after_utc"])
            profile = store.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            )
            self.assertEqual(profile["tasks"][0]["status"], "failed")
            self.assertEqual(
                profile["tasks"][0]["failure_code"], "channel-send-uncertain"
            )

    @unittest.skipIf(not hasattr(socket, "AF_UNIX"), "AF_UNIX not available")
    def test_dispatch_adapter_socket_seam(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store, clock = self._store(root_path)
            self._add_task(store)
            llm = LLMFake([{"decision": "skip", "reason": "not useful now"}])
            channel = ChannelFake()
            ports = HealthStewardPorts(
                clock=clock,
                key_manager=store.key_manager,
                llm=llm,
                source_fetch=object(),
                channel_send=channel,
            )
            socket_path = root_path / "health.sock"
            ready = threading.Event()
            server = HealthSidecarServer(
                socket_path,
                store,
                allowed_uids={os.getuid()},
                ready_event=ready,
                ports=ports,
            )
            thread = threading.Thread(target=server.run_forever, daemon=True)
            thread.start()
            self.assertTrue(ready.wait(timeout=3))
            try:
                adapter = PartnerHealthAdapter(str(socket_path), timeout_seconds=1.0)
                result = adapter.dispatch_due_tasks(
                    self.SUBJECT,
                    self.REVIEW_UTC,
                    "nonproduction-test-job-authorization",
                )
                self.assertEqual(len(result["skipped"]), 1)
                self.assertEqual(channel.sent, [])
            finally:
                server.stop()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

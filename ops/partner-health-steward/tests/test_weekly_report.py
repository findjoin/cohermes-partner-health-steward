import datetime as dt
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import HealthSidecarServer, PartnerHealthAdapter
from sidecar.ports import HealthStewardPorts
from sidecar.profile import ProfileStoreError
from sidecar.store import HealthSidecarStore


class FixedClock:
    def __init__(self, now: dt.datetime):
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class LLMFake:
    def __init__(self, response):
        self.response = response
        self.contexts = []
        self.prompts = []

    def complete_fresh(self, prompt, context, session_id):
        self.prompts.append(prompt)
        self.contexts.append(context)
        return self.response


class ChannelFake:
    def __init__(self):
        self.sent = []

    def send_once(self, recipient, message, delivery_key):
        self.sent.append((recipient, message, delivery_key))
        return True


class WeeklyReportTests(unittest.TestCase):
    SUBJECT = "profile"
    OWNER = "owner-1"
    VIEWER = "viewer-1"
    SUNDAY_REVIEW_UTC = "2026-01-03T20:00:00Z"  # Sunday 04:00 Asia/Shanghai.
    REPORT_DUE_UTC = "2026-01-04T02:00:00Z"  # Sunday 10:00 Asia/Shanghai.

    def _store(self, root: Path):
        clock = FixedClock(dt.datetime(2026, 1, 3, 20, 0, tzinfo=dt.timezone.utc))
        store = HealthSidecarStore(
            root / "state.sqlite.enc", root / "sidecar.key", clock=clock
        )
        owner_token = store.message_verifier.sign_owner_binding(
            subject=self.SUBJECT, owner_sender_id=self.OWNER
        )
        self.assertTrue(store.bind_profile_owner(self.SUBJECT, self.OWNER, owner_token))
        return store, clock

    def _receipt(self, store, action, actor, target, message_id, message_utc=None):
        message_utc = message_utc or self.SUNDAY_REVIEW_UTC
        return (
            message_id,
            message_utc,
            store.message_verifier.sign_access_receipt(
                action=action,
                subject=self.SUBJECT,
                actor_sender_id=actor,
                target_sender_id=target,
                message_id=message_id,
                message_utc=message_utc,
            ),
        )

    def _grant_viewer(self, store, viewer=None, message_id="grant-weekly", message_utc=None):
        viewer = viewer or self.VIEWER
        return store.grant_profile_viewer(
            self.SUBJECT,
            self.OWNER,
            viewer,
            *self._receipt(
                store,
                "health.access.grant",
                self.OWNER,
                viewer,
                message_id,
                message_utc,
            ),
        )

    def _add_evidence(self, store, message_id, source_utc, text, key="sleep"):
        token = store.message_verifier.sign(
            subject=self.SUBJECT,
            sender_id=self.OWNER,
            message_id=message_id,
            message_utc=source_utc,
            message_text=text,
            evidence_kind="direct_statement",
        )
        store.stage_profile_message(
            self.SUBJECT,
            self.OWNER,
            message_id,
            source_utc,
            text,
            "direct_statement",
            token,
        )
        return store.record_profile_candidate(
            self.SUBJECT,
            self.OWNER,
            {
                "evidence_kind": "direct_statement",
                "source_message_id": message_id,
                "source_utc": source_utc,
                "excerpt": text,
                "conclusions": [
                    {
                        "category": "state",
                        "dedupe_key": key,
                        "text": text,
                        "status": "fact",
                        "priority": 80,
                    }
                ],
            },
        )

    def _run_review(self, store, review_utc=None):
        return store.run_daily_review(
            self.SUBJECT,
            review_utc or self.SUNDAY_REVIEW_UTC,
            "Asia/Shanghai",
            {"outcome": "no_action"},
        )

    def test_sunday_daily_review_creates_one_report_per_active_viewer(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_evidence(
                store,
                "sleep-1",
                "2026-01-02T19:55:00Z",
                "sleep was poor",
            )
            self._add_evidence(
                store,
                "sleep-2",
                "2026-01-03T19:55:00Z",
                "sleep is improving",
            )
            self._grant_viewer(store)

            result = self._run_review(store)

            self.assertEqual(result["result"], "tasks_created")
            report_tasks = [
                task
                for task in result["created_tasks"]
                if task["task_type"] == "profile_difference_report"
            ]
            self.assertEqual(len(report_tasks), 1)
            task = report_tasks[0]
            self.assertEqual(task["recipient_sender_id"], self.VIEWER)
            self.assertEqual(task["time_window"]["start_utc"], "2026-01-04T02:00:00+00:00")
            self.assertEqual(task["report_to_version_id"], store.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            )["current_version_id"])
            self.assertIn("changed_conclusion_keys", task["report_change_refs"])
            self.assertNotIn("excerpt", str(task["report_change_refs"]))
            profile = store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            self.assertEqual(len(profile["reports"]), 1)

    def test_daily_review_model_cannot_create_weekly_report_directly(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            result = store.run_daily_review(
                self.SUBJECT,
                self.SUNDAY_REVIEW_UTC,
                "Asia/Shanghai",
                {
                    "outcome": "tasks",
                    "tasks": [{"task_type": "profile_difference_report"}],
                },
            )
            self.assertEqual(result["result"], "failed")
            self.assertEqual(result["reason"], "weekly-report-system-generated")

    def test_report_context_contains_references_only_and_dispatches_to_viewer(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_evidence(
                store,
                "sleep-1",
                "2026-01-02T19:55:00Z",
                "private sleep detail",
            )
            self._add_evidence(
                store,
                "sleep-2",
                "2026-01-03T19:55:00Z",
                "another private sleep detail",
                key="hydration",
            )
            self._grant_viewer(store)
            self._run_review(store)
            clock.now = dt.datetime(2026, 1, 4, 2, 0, tzinfo=dt.timezone.utc)
            llm = LLMFake(
                {"decision": "send", "message": "本周画像有 1 项变化（引用 pv-...）。", "reason": "weekly-report"}
            )
            channel = ChannelFake()
            llm.response = {
                "decision": "send",
                "summary": "本周画像有一项可追溯变化。",
                "reference_ids": ["hydration"],
                "reason": "weekly-report",
            }

            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.REPORT_DUE_UTC,
                llm,
                channel,
            )

            self.assertEqual(len(result["sent"]), 1)
            self.assertEqual(channel.sent[0][0], self.VIEWER)
            context = llm.contexts[0]
            self.assertIn("report", context)
            self.assertEqual(context["recent_messages"], [])
            self.assertEqual(context["evidence"], [])
            self.assertNotIn("private sleep detail", str(context))
            self.assertNotIn("profile_summary_zh", context.get("report", {}))

    def test_report_message_must_use_structured_references(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_evidence(store, "sleep-1", "2026-01-02T19:55:00Z", "sleep was poor")
            self._add_evidence(store, "sleep-2", "2026-01-03T19:55:00Z", "sleep is improving", key="hydration")
            self._grant_viewer(store)
            self._run_review(store)
            clock.now = dt.datetime(2026, 1, 4, 2, 0, tzinfo=dt.timezone.utc)
            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.REPORT_DUE_UTC,
                LLMFake(
                    {
                        "decision": "send",
                        "message": "伪造的完整报告正文",
                        "reason": "weekly-report",
                    }
                ),
                ChannelFake(),
            )
            self.assertEqual(result["sent"], [])
            self.assertEqual(len(result["failed"]), 1)

    def test_revocation_before_due_blocks_report_delivery(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_evidence(
                store,
                "sleep-1",
                "2026-01-02T19:55:00Z",
                "sleep was poor",
            )
            self._add_evidence(
                store,
                "sleep-2",
                "2026-01-03T19:55:00Z",
                "sleep is improving",
            )
            self._grant_viewer(store)
            self._run_review(store)
            store.revoke_profile_viewer(
                self.SUBJECT,
                self.OWNER,
                self.VIEWER,
                *self._receipt(
                    store,
                    "health.access.revoke",
                    self.OWNER,
                    self.VIEWER,
                    "revoke-weekly",
                ),
            )
            clock.now = dt.datetime(2026, 1, 4, 2, 0, tzinfo=dt.timezone.utc)
            channel = ChannelFake()

            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.REPORT_DUE_UTC,
                LLMFake({"decision": "send", "message": "must not send", "reason": "bad"}),
                channel,
            )

            self.assertEqual(result["sent"], [])
            self.assertEqual(len(result["skipped"]), 1)
            self.assertEqual(result["reasons"][result["skipped"][0]], "report-authorization-invalid")
            self.assertEqual(channel.sent, [])

    def test_configured_viewer_filters_historic_report_candidates(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            legacy_store, clock = self._store(root_path)
            self._add_evidence(
                legacy_store,
                "configured-filter-1",
                "2026-01-02T19:55:00Z",
                "first bounded change",
            )
            self._add_evidence(
                legacy_store,
                "configured-filter-2",
                "2026-01-03T19:55:00Z",
                "second bounded change",
                key="hydration",
            )
            self._grant_viewer(legacy_store, self.VIEWER, "grant-configured")
            self._grant_viewer(
                legacy_store,
                "viewer-historic",
                "grant-historic",
            )
            configured_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "sidecar.key",
                clock=clock,
                expected_owner_sender_id=self.OWNER,
                expected_viewer_sender_id=self.VIEWER,
            )
            regrant = self._grant_viewer(
                configured_store,
                self.VIEWER,
                "regrant-configured",
            )
            self.assertTrue(regrant["changed"])

            result = self._run_review(configured_store)

            recipients = {
                task["recipient_sender_id"]
                for task in result["created_tasks"]
                if task["task_type"] == "profile_difference_report"
            }
            self.assertEqual(recipients, {self.VIEWER})

    def test_configured_viewer_blocks_historic_report_already_due(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            legacy_store, clock = self._store(root_path)
            self._add_evidence(
                legacy_store,
                "historic-due-1",
                "2026-01-02T19:55:00Z",
                "first bounded change",
            )
            self._add_evidence(
                legacy_store,
                "historic-due-2",
                "2026-01-03T19:55:00Z",
                "second bounded change",
                key="hydration",
            )
            self._grant_viewer(legacy_store, self.VIEWER, "grant-current")
            self._grant_viewer(
                legacy_store,
                "viewer-historic",
                "grant-old",
            )
            self._run_review(legacy_store)
            configured_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "sidecar.key",
                clock=clock,
                expected_owner_sender_id=self.OWNER,
                expected_viewer_sender_id=self.VIEWER,
            )
            regrant = self._grant_viewer(
                configured_store,
                self.VIEWER,
                "regrant-current",
            )
            self.assertTrue(regrant["changed"])
            clock.now = dt.datetime(2026, 1, 4, 2, 0, tzinfo=dt.timezone.utc)
            llm = LLMFake(
                {
                    "decision": "send",
                    "summary": "本周画像有一项可追溯变化。",
                    "reference_ids": ["hydration"],
                    "reason": "weekly-report",
                }
            )
            channel = ChannelFake()

            result = configured_store.dispatch_due_tasks(
                self.SUBJECT,
                self.REPORT_DUE_UTC,
                llm,
                channel,
            )

            self.assertEqual([item[0] for item in channel.sent], [self.VIEWER])
            self.assertEqual(len(result["sent"]), 1)
            self.assertIn("report-authorization-invalid", result["reasons"].values())

    def test_no_substantive_change_can_be_explicitly_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_evidence(
                store,
                "sleep-1",
                "2026-01-02T19:55:00Z",
                "sleep was poor",
            )
            self._grant_viewer(store)
            self._run_review(store)
            clock.now = dt.datetime(2026, 1, 4, 2, 0, tzinfo=dt.timezone.utc)
            # A single version has no adjacent prior version; the report still
            # carries an explicit empty change set and may be skipped.
            llm = LLMFake({"decision": "skip", "reason": "no-substantive-change"})
            result = store.dispatch_due_tasks(
                self.SUBJECT,
                self.REPORT_DUE_UTC,
                llm,
                ChannelFake(),
            )
            self.assertEqual(len(result["skipped"]), 1)
            self.assertEqual(result["reasons"][result["skipped"][0]], "no-substantive-change")

    def test_next_week_without_a_new_version_has_empty_change_references(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_evidence(
                store,
                "sleep-1",
                "2026-01-02T19:55:00Z",
                "sleep was poor",
            )
            self._grant_viewer(store)
            self._run_review(store)
            clock.now = dt.datetime(2026, 1, 4, 2, 0, tzinfo=dt.timezone.utc)
            store.dispatch_due_tasks(
                self.SUBJECT,
                self.REPORT_DUE_UTC,
                LLMFake({"decision": "skip", "reason": "no-substantive-change"}),
                ChannelFake(),
            )

            clock.now = dt.datetime(2026, 1, 10, 20, 0, tzinfo=dt.timezone.utc)
            result = self._run_review(store, "2026-01-10T20:00:00Z")
            report = next(
                task
                for task in result["created_tasks"]
                if task["task_type"] == "profile_difference_report"
            )
            refs = report["report_change_refs"]
            self.assertEqual(refs["added_conclusion_keys"], [])
            self.assertEqual(refs["evidence_added_ids"], [])
            self.assertFalse(refs["profile_summary_changed"])
            self.assertEqual(refs["task_event_refs"], [])
            self.assertEqual(refs["authorization_event_refs"], [])
            self.assertEqual(refs["deletion_event_refs"], [])
            self.assertEqual(refs["daily_review_failure_refs"], [])
            self.assertEqual(refs["audit_refs"], [])

    def test_deletion_before_due_blocks_report_dispatch(self):
        class MemoryProjection:
            def remove_health_projection(self, subject):
                del subject
                return True

        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_evidence(store, "sleep-1", "2026-01-02T19:55:00Z", "sleep was poor")
            self._add_evidence(store, "sleep-2", "2026-01-03T19:55:00Z", "sleep is improving")
            self._grant_viewer(store)
            self._run_review(store)
            store.request_profile_deletion(
                self.SUBJECT,
                self.OWNER,
                *self._receipt(
                    store,
                    "health.profile.delete.request",
                    self.OWNER,
                    self.OWNER,
                    "delete-weekly-request",
                ),
            )
            store.confirm_profile_deletion(
                self.SUBJECT,
                self.OWNER,
                "delete-weekly-request",
                *self._receipt(
                    store,
                    "health.profile.delete.confirm",
                    self.OWNER,
                    self.OWNER,
                    "delete-weekly-confirm",
                    "2026-01-03T20:00:01Z",
                ),
                memory_projection=MemoryProjection(),
            )
            clock.now = dt.datetime(2026, 1, 4, 2, 0, tzinfo=dt.timezone.utc)
            with self.assertRaisesRegex(ProfileStoreError, "profile-not-bound"):
                store.dispatch_due_tasks(
                    self.SUBJECT,
                    self.REPORT_DUE_UTC,
                    LLMFake(
                        {
                            "decision": "send",
                            "summary": "must not send",
                            "reference_ids": ["sleep"],
                            "reason": "bad",
                        }
                    ),
                    ChannelFake(),
                )

    def test_report_baseline_is_scoped_to_each_viewer(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_evidence(store, "sleep-1", "2026-01-02T19:55:00Z", "sleep was poor")
            self._add_evidence(store, "sleep-2", "2026-01-03T19:55:00Z", "sleep is improving")
            self._grant_viewer(store)
            first = self._run_review(store)
            self.assertTrue(any(task["recipient_sender_id"] == self.VIEWER for task in first["created_tasks"]))
            clock.now = dt.datetime(2026, 1, 4, 2, 0, tzinfo=dt.timezone.utc)
            store.dispatch_due_tasks(
                self.SUBJECT,
                self.REPORT_DUE_UTC,
                LLMFake({"decision": "skip", "reason": "no-substantive-change"}),
                ChannelFake(),
            )
            clock.now = dt.datetime(2026, 1, 10, 19, 55, tzinfo=dt.timezone.utc)
            self._grant_viewer(
                store,
                viewer="viewer-2",
                message_id="grant-weekly-2",
                message_utc="2026-01-10T19:55:00Z",
            )
            clock.now = dt.datetime(2026, 1, 10, 20, 0, tzinfo=dt.timezone.utc)
            result = self._run_review(store, "2026-01-10T20:00:00Z")
            reports = {
                task["recipient_sender_id"]: task
                for task in result["created_tasks"]
                if task["task_type"] == "profile_difference_report"
            }
            self.assertEqual(
                reports[self.VIEWER]["report_from_version_id"],
                reports[self.VIEWER]["report_to_version_id"],
            )
            self.assertTrue(reports["viewer-2"]["report_change_refs"]["added_conclusion_keys"])
            self.assertNotEqual(
                reports["viewer-2"]["report_from_version_id"],
                reports["viewer-2"]["report_to_version_id"],
            )

    def test_new_version_uses_each_viewer_report_time_for_audit_refs(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_evidence(store, "sleep-1", "2026-01-02T19:55:00Z", "sleep was poor")
            self._grant_viewer(store)
            self._run_review(store)
            clock.now = dt.datetime(2026, 1, 4, 2, 0, tzinfo=dt.timezone.utc)
            store.dispatch_due_tasks(
                self.SUBJECT,
                self.REPORT_DUE_UTC,
                LLMFake({"decision": "skip", "reason": "no-substantive-change"}),
                ChannelFake(),
            )
            clock.now = dt.datetime(2026, 1, 10, 19, 30, tzinfo=dt.timezone.utc)
            self._add_evidence(store, "sleep-2", "2026-01-10T19:30:00Z", "sleep is improving")
            clock.now = dt.datetime(2026, 1, 10, 19, 55, tzinfo=dt.timezone.utc)
            self._grant_viewer(
                store,
                viewer="viewer-2",
                message_id="grant-weekly-2",
                message_utc="2026-01-10T19:55:00Z",
            )
            clock.now = dt.datetime(2026, 1, 10, 20, 0, tzinfo=dt.timezone.utc)
            result = self._run_review(store, "2026-01-10T20:00:00Z")
            owner_report = next(
                task for task in result["created_tasks"]
                if task.get("recipient_sender_id") == self.VIEWER
            )
            self.assertTrue(owner_report["report_change_refs"]["authorization_event_refs"])
            self.assertTrue(
                all(
                    item["utc"] >= "2026-01-10T19:30:00+00:00"
                    for item in owner_report["report_change_refs"]["authorization_event_refs"]
                )
            )

    @unittest.skipIf(not hasattr(socket, "AF_UNIX"), "AF_UNIX not available")
    def test_weekly_report_adapter_socket_seam(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store, clock = self._store(root_path)
            self._add_evidence(store, "sleep-1", "2026-01-02T19:55:00Z", "sleep was poor")
            self._add_evidence(store, "sleep-2", "2026-01-03T19:55:00Z", "sleep is improving")
            self._grant_viewer(store)
            llm = LLMFake(
                {
                    "decision": "send",
                    "summary": "本周画像有一项可追溯变化。",
                    "reference_ids": ["sleep"],
                    "reason": "weekly-report",
                }
            )
            channel = ChannelFake()
            ports = HealthStewardPorts(
                clock=store.clock,
                key_manager=store.key_manager,
                llm=llm,
                source_fetch=None,
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
                result = adapter.run_daily_review(
                    self.SUBJECT,
                    self.SUNDAY_REVIEW_UTC,
                    "Asia/Shanghai",
                    {"outcome": "no_action"},
                )
                self.assertEqual(result["result"], "tasks_created")
                self.assertTrue(
                    any(
                        task["task_type"] == "profile_difference_report"
                        for task in result["created_tasks"]
                    )
                )
                clock.now = dt.datetime(2026, 1, 4, 2, 0, tzinfo=dt.timezone.utc)
                dispatched = adapter.dispatch_due_tasks(
                    self.SUBJECT,
                    self.REPORT_DUE_UTC,
                    "nonproduction-test-job-authorization",
                )
                self.assertEqual(len(dispatched["sent"]), 1)
                self.assertEqual(channel.sent[0][0], self.VIEWER)
            finally:
                server.stop()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

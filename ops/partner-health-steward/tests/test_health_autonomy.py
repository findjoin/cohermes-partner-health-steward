from __future__ import annotations

import dataclasses
import datetime as dt
import concurrent.futures
import contextlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugin" / "health-autonomy"
SPEC = importlib.util.spec_from_file_location(
    "health_autonomy_core_under_test", PLUGIN_DIR / "autonomy.py"
)
autonomy = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = autonomy
SPEC.loader.exec_module(autonomy)


class MutableClock:
    def __init__(self, value: dt.datetime):
        self.value = value

    def __call__(self) -> dt.datetime:
        return self.value


class FakeCron:
    def __init__(self):
        self.calls = []
        self.job_id = "job-health-v02"

    def ensure_dispatcher(self, routing):
        self.calls.append(("ensure", routing))
        return self.job_id, True

    def pause(self, job_id, reason):
        self.calls.append(("pause", job_id, reason))

    def resume(self, job_id):
        self.calls.append(("resume", job_id))

    def remove(self, job_id):
        self.calls.append(("remove", job_id))


class HealthAutonomyCoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.clock = MutableClock(dt.datetime(2026, 8, 5, 1, 0, tzinfo=dt.timezone.utc))
        self.db_path = Path(self.tempdir.name) / "private" / "health.sqlite3"
        self.store = autonomy.HealthAutonomyStore(self.db_path, now_fn=self.clock)
        self.config = autonomy.parse_activation(autonomy.activation_example())
        self.routing = {
            "platform": "telegram",
            "user_id": "partner-user",
            "chat_id": "partner-chat",
            "thread_id": "",
            "chat_type": "dm",
        }
        self.subject_key = autonomy.routing_subject_key(self.routing)

    def tearDown(self):
        self.tempdir.cleanup()

    def activate(self, config=None):
        return self.store.activate(
            config or self.config,
            source_message_id="message-auth-1",
            dispatcher_job_id="job-health-v02",
            subject_key=self.subject_key,
            dispatcher_routing=self.routing,
        )

    def rows(self, query, params=()):
        with contextlib.closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(query, params).fetchall()

    def test_activation_contract_has_physical_limits_and_scoped_categories(self):
        config = self.config
        self.assertEqual(config.max_proactive_messages_24h, 3)
        self.assertEqual(config.min_spacing_minutes, 240)
        self.assertEqual((config.quiet_start, config.quiet_end), ("23:00", "08:00"))
        self.assertEqual(config.task_ttl_days, 30)
        self.assertEqual(config.max_active_tasks, 3)
        self.assertEqual(config.category_times["hydration_cue"], ("10:30", "15:30"))

    def test_dispatcher_route_fingerprint_round_trip_binds_dm_route(self):
        self.activate()
        self.assertTrue(self.store.dispatcher_route_matches(self.routing))
        for field, replacement in (
            ("chat_id", "different-chat"),
            ("thread_id", "different-thread"),
            ("user_id", "different-user"),
            ("chat_type", "group"),
        ):
            with self.subTest(field=field):
                altered = {**self.routing, field: replacement}
                self.assertFalse(self.store.dispatcher_route_matches(altered))

    def test_activation_rejects_unknown_fields_and_times_inside_quiet_hours(self):
        with self.assertRaisesRegex(ValueError, "未知授权字段"):
            autonomy.parse_activation(autonomy.activation_example() + "；诊断=开")
        bad = autonomy.activation_example().replace(
            "补水提示时间=10:30,15:30", "补水提示时间=10:30,23:30"
        )
        with self.assertRaisesRegex(ValueError, "静默时段"):
            autonomy.parse_activation(bad)

    def test_no_authorization_means_no_persistence(self):
        result = self.store.observe("我最近睡不着", "m-no-auth", self.subject_key)
        self.assertEqual(result["reason"], "inactive_or_unauthorized")
        self.assertEqual(self.rows("SELECT * FROM observation_event"), [])
        self.assertEqual(self.rows("SELECT * FROM state_item"), [])
        self.assertEqual(self.rows("SELECT * FROM automation_task"), [])

    def test_replayed_message_creates_one_task_and_stores_no_raw_transcript(self):
        self.activate()
        first = self.store.observe("我总忘记喝水", "m-water-1", self.subject_key)
        second = self.store.observe("我总忘记喝水", "m-water-1", self.subject_key)
        self.assertTrue(any(a["action"] == "task_created" for a in first["actions"]))
        self.assertEqual(second["result"], "duplicate")
        tasks = self.rows("SELECT * FROM automation_task")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["category"], "hydration_cue")
        self.assertEqual(json.loads(tasks[0]["schedule_json"])["times"], ["10:30", "15:30"])
        self.assertNotIn("我总忘记喝水".encode("utf-8"), self.db_path.read_bytes())

    def test_new_task_rate_cap_blocks_second_category_within_seven_days(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-water", self.subject_key)
        result = self.store.observe("我总熬夜", "m-sleep-routine", self.subject_key)
        self.assertIn(
            {
                "action": "task_not_created",
                "category": "wind_down",
                "reason": "new_task_7d_cap",
            },
            result["actions"],
        )
        self.assertEqual(len(self.rows("SELECT * FROM automation_task")), 1)

    def test_doctor_opinion_is_self_report_not_system_diagnosis(self):
        self.activate()
        self.store.observe("医生说我高血压", "m-doctor", self.subject_key)
        row = self.rows(
            "SELECT value_json,evidence_state FROM state_item WHERE state_key='doctor_opinion.self_report'"
        )[0]
        value = json.loads(row["value_json"])
        self.assertEqual(value["source_kind"], "self_reported_doctor")
        self.assertIn("系统未独立核验或诊断", value["representation"])
        self.assertEqual(row["evidence_state"], "explicit")

    def test_untyped_measurement_is_invalid_and_never_promoted(self):
        self.activate()
        result = self.store.observe("我今天血压120", "m-bare-measurement", self.subject_key)
        self.assertTrue(
            any(a["action"] == "invalid_observation_not_promoted" for a in result["actions"])
        )
        self.assertEqual(
            self.rows("SELECT * FROM state_item WHERE state_key LIKE 'measurement.%'"), []
        )
        event = self.rows("SELECT schema_state,payload_json FROM observation_event")[0]
        self.assertEqual(event["schema_state"], "invalid")

    def test_subject_correction_invalidates_latest_item_and_dependent_task(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-water-correct", self.subject_key)
        task = self.rows("SELECT task_id,trigger_item_id FROM automation_task")[0]
        self.assertIsNotNone(task["trigger_item_id"])
        result = self.store.observe(
            "不是我，是我妈",
            "m-correction",
            self.subject_key,
            reply_to_message_id="m-water-correct",
        )
        self.assertTrue(any(a["action"] == "profile_corrected" for a in result["actions"]))
        row = self.rows(
            "SELECT lifecycle,evidence_state FROM state_item WHERE state_key='routine.hydration_cue.self_report'"
        )[0]
        self.assertEqual((row["lifecycle"], row["evidence_state"]), ("invalidated", "invalid"))
        task = self.rows("SELECT status,pause_reason FROM automation_task")[0]
        self.assertEqual((task["status"], task["pause_reason"]), ("paused", "trigger_corrected"))

    def test_explicit_preference_applies_immediately_and_is_minimally_injected(self):
        self.activate()
        result = self.store.observe("回复简短一点，语气温柔一点", "m-pref", self.subject_key)
        self.assertEqual(result["result"], "applied")
        context = self.store.context_for_model("今天很忙", result, self.subject_key)
        self.assertIn('"response_length":"short"', context)
        self.assertIn('"tone":"warm"', context)
        self.assertNotIn("structured observations", context)

    def test_three_cross_day_time_feedbacks_are_required_for_stable_shift(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-task", self.subject_key)
        before = json.loads(self.rows("SELECT schedule_json FROM automation_task")[0][0])
        self.store.observe("喝水提醒太早了", "m-feedback-1", self.subject_key)
        self.clock.value += dt.timedelta(hours=2)
        self.store.observe("喝水提醒太早了", "m-feedback-2", self.subject_key)
        middle = json.loads(self.rows("SELECT schedule_json FROM automation_task")[0][0])
        self.assertEqual(middle, before)
        self.clock.value += dt.timedelta(days=1)
        result = self.store.observe("喝水提醒太早了", "m-feedback-3", self.subject_key)
        after = json.loads(self.rows("SELECT schedule_json FROM automation_task")[0][0])
        self.assertEqual(after["times"], ["11:00", "16:00"])
        shift = [a for a in result["actions"] if a["action"] == "stable_time_adjustment"]
        self.assertEqual(shift[0]["support_count"], 3)
        self.assertEqual(shift[0]["support_days"], 2)

    def test_dispatch_is_at_most_once_and_rolling_cap_is_conservative(self):
        config = dataclasses.replace(self.config, max_proactive_messages_24h=1)
        self.activate(config)
        self.store.observe("我总忘记喝水", "m-task", self.subject_key)
        self.clock.value = dt.datetime(2026, 8, 5, 2, 30, tzinfo=dt.timezone.utc)
        first = self.store.dispatch_due()
        replay = self.store.dispatch_due()
        self.assertIn("喝点水", first)
        self.assertEqual(replay, "")
        self.clock.value = dt.datetime(2026, 8, 5, 7, 30, tzinfo=dt.timezone.utc)
        capped = self.store.dispatch_due()
        self.assertEqual(capped, "")
        self.assertEqual(len(self.rows("SELECT * FROM dispatch_event")), 1)

    def test_quiet_hours_defer_due_task_to_quiet_end(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-task", self.subject_key)
        self.clock.value = dt.datetime(2026, 8, 5, 16, 30, tzinfo=dt.timezone.utc)  # 00:30 local
        with contextlib.closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE automation_task SET next_run_at=?",
                (self.clock.value.isoformat(),),
            )
            connection.commit()
        self.assertEqual(self.store.dispatch_due(), "")
        next_run = self.rows("SELECT next_run_at FROM automation_task")[0][0]
        self.assertEqual(
            dt.datetime.fromisoformat(next_run),
            dt.datetime(2026, 8, 6, 0, 0, tzinfo=dt.timezone.utc),  # 08:00 local
        )

    def test_revoke_stops_reads_writes_and_dispatch(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-task", self.subject_key)
        self.store.revoke(self.subject_key)
        result = self.store.observe("我最近睡不着", "m-after-revoke", self.subject_key)
        self.assertEqual(result["reason"], "inactive_or_unauthorized")
        self.clock.value = dt.datetime(2026, 8, 5, 2, 30, tzinfo=dt.timezone.utc)
        self.assertEqual(self.store.dispatch_due(), "")
        task = self.rows("SELECT status,pause_reason FROM automation_task")[0]
        self.assertEqual(
            (task["status"], task["pause_reason"]),
            ("paused", "authorization_revoked"),
        )

    def test_status_distinguishes_pause_from_no_data_and_discloses_retained_counts(self):
        self.activate()
        self.store.observe("我最近睡不好", "m-status-health", self.subject_key)
        self.store.pause(self.subject_key)
        engine = autonomy.HealthAutonomyEngine(self.store, FakeCron())

        reply = engine.control("status", self.routing)

        self.assertIn("本人暂停", reply)
        self.assertIn("禁止投递", reply)
        self.assertIn("观察1", reply)
        self.assertIn("状态项1", reply)
        self.assertIn("本次未核验为可运行", reply)

    def test_delete_cascades_sensitive_rows_and_leaves_only_content_free_audit(self):
        self.activate()
        self.store.observe("我最近睡不着，回复简短一点", "m-data", self.subject_key)
        result = self.store.delete_all(self.subject_key)
        self.assertEqual(result["dispatcher_job_id"], "job-health-v02")
        for table in (
            "authorization",
            "observation_event",
            "state_item",
            "state_evidence",
            "automation_task",
            "feedback_event",
            "decision_log",
            "dispatch_event",
            "control_state",
        ):
            self.assertEqual(self.rows(f"SELECT * FROM {table}"), [], table)
        audit = self.rows("SELECT * FROM deletion_audit")
        self.assertEqual(len(audit), 1)
        self.assertNotIn("sleep", audit[0]["deleted_counts_json"])

    def test_corrupted_schema_version_fails_closed_on_reopen(self):
        with contextlib.closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE schema_meta SET value='999' WHERE key='schema_version'"
            )
            connection.commit()

        with self.assertRaisesRegex(RuntimeError, "schema version mismatch"):
            autonomy.HealthAutonomyStore(self.db_path, now_fn=self.clock)

    def test_delete_removes_sensitive_markers_from_raw_database_bytes(self):
        marker = b"routine.hydration_cue.self_report"
        self.activate()
        self.store.observe("我总忘记喝水", "m-sensitive", self.subject_key)
        self.assertIn(marker, self.db_path.read_bytes())

        self.store.delete_all(self.subject_key)

        self.assertNotIn(marker, self.db_path.read_bytes())

    def test_delete_keeps_old_authorization_and_message_replays_inert(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-before-delete", self.subject_key)
        self.store.delete_all(
            self.subject_key, source_message_id="m-delete-before-reauthorize"
        )

        old_authorization = self.store.activate(
            self.config,
            source_message_id="message-auth-1",
            dispatcher_job_id="job-health-v02",
            subject_key=self.subject_key,
        )
        self.assertEqual(
            old_authorization,
            {"authorization_id": None, "duplicate": True},
        )
        self.assertEqual(self.rows("SELECT * FROM authorization"), [])

        fresh_authorization = self.store.activate(
            self.config,
            source_message_id="message-auth-2",
            dispatcher_job_id="job-health-v02",
            subject_key=self.subject_key,
        )
        self.assertFalse(fresh_authorization["duplicate"])
        with self.assertRaises(autonomy.DuplicateControlEvent):
            self.store.delete_all(
                self.subject_key,
                source_message_id="m-delete-before-reauthorize",
            )
        self.assertEqual(len(self.rows("SELECT * FROM authorization")), 4)
        replay = self.store.observe(
            "我总忘记喝水", "m-before-delete", self.subject_key
        )
        self.assertEqual(
            replay,
            {"result": "duplicate", "reason": "platform_message_replay"},
        )
        self.assertEqual(self.rows("SELECT * FROM automation_task"), [])

    def test_subject_mismatch_cannot_read_or_write_bound_health_state(self):
        self.activate()
        wrong_subject = autonomy.routing_subject_key(
            {
                "platform": "telegram",
                "user_id": "different-user",
                "chat_id": "different-chat",
                "thread_id": "",
                "chat_type": "dm",
            }
        )

        result = self.store.observe("我最近睡不着", "m-wrong-subject", wrong_subject)

        self.assertEqual(
            result, {"result": "ignored", "reason": "data_subject_mismatch"}
        )
        self.assertEqual(self.rows("SELECT * FROM observation_event"), [])
        with self.assertRaisesRegex(PermissionError, "不是这份健康数据的本人"):
            self.store.status(wrong_subject)

    def test_different_authorized_sender_cannot_quarantine_or_create_cron(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-bound-task", self.subject_key)
        cron = FakeCron()
        engine = autonomy.HealthAutonomyEngine(self.store, cron)
        other_routing = {
            "platform": "telegram",
            "user_id": "other-authorized-user",
            "chat_id": "other-authorized-chat",
            "thread_id": "",
            "chat_type": "dm",
        }

        with self.assertRaises(autonomy.DataSubjectMismatch):
            engine.activate(
                autonomy.activation_example(),
                "m-other-activation",
                other_routing,
            )

        self.assertEqual(cron.calls, [])
        self.assertEqual(
            self.rows("SELECT value FROM control_state WHERE key='mode'")[0][0],
            "active",
        )
        self.assertEqual(
            self.rows("SELECT status FROM automation_task")[0][0], "active"
        )

    def test_adversarial_phrasing_does_not_create_autonomous_tasks(self):
        self.activate()
        phrases = (
            "她说提醒我喝水",
            "“提醒我喝水”",
            "不要提醒我喝水",
            "测试用例：提醒我喝水",
            "科普一下为什么有人会说提醒我喝水",
        )

        for index, phrase in enumerate(phrases):
            with self.subTest(phrase=phrase):
                result = self.store.observe(
                    phrase, f"m-adversarial-{index}", self.subject_key
                )
                self.assertFalse(
                    any(
                        action.get("action") == "task_created"
                        for action in result.get("actions", [])
                    )
                )
        self.assertEqual(self.rows("SELECT * FROM automation_task"), [])

    def test_negated_allergy_statements_are_not_promoted(self):
        self.activate()
        for index, phrase in enumerate(
            (
                "我不过敏",
                "我没有对花生过敏",
                "我对青霉素未过敏",
                "我对青霉素无过敏反应",
                "我对青霉素从未过敏",
            )
        ):
            with self.subTest(phrase=phrase):
                self.store.observe(phrase, f"m-negated-allergy-{index}", self.subject_key)
                self.assertEqual(
                    self.rows(
                        "SELECT * FROM state_item WHERE state_key LIKE 'allergy.%'"
                    ),
                    [],
                )

    def test_hypothetical_quoted_or_invalid_health_facts_are_not_persisted(self):
        self.activate()
        phrases = (
            "测试用例：我对青霉素过敏",
            "请改写“我对青霉素过敏”",
            "假设我今天血压120/80mmHg",
            "我今天血压120/80mmHg不准确",
            "我对青霉素过敏吗？",
            "我最近没有睡不好",
            "我不是睡不好",
            "如果我今天血压120/80mmHg",
            "假如我今天血压120/80mmHg",
            "要是我今天血压120/80mmHg",
        )
        for index, phrase in enumerate(phrases):
            with self.subTest(phrase=phrase):
                result = self.store.observe(
                    phrase, f"m-non-fact-{index}", self.subject_key
                )
                self.assertEqual(result["result"], "no_structured_change")
        self.assertEqual(self.rows("SELECT * FROM observation_event"), [])
        self.assertEqual(self.rows("SELECT * FROM state_item"), [])

    def test_multi_value_allergy_is_split_or_rejected_never_collapsed(self):
        self.activate()
        self.store.observe("我对花生和牛奶过敏", "m-multi-allergy", self.subject_key)
        rows = self.rows(
            "SELECT value_json FROM state_item WHERE state_key LIKE 'allergy.%'"
        )

        if rows:
            items = [json.loads(row["value_json"])["item"] for row in rows]
            self.assertCountEqual(items, ["花生", "牛奶"])
        self.assertFalse(
            any("和" in json.loads(row["value_json"])["item"] for row in rows)
        )

    def test_physically_implausible_measurements_are_never_promoted(self):
        self.activate()
        phrases = (
            "我刚测血压999/999mmHg",
            "我现在心率999bpm",
            "我今天体温99.9℃",
        )

        for index, phrase in enumerate(phrases):
            with self.subTest(phrase=phrase):
                result = self.store.observe(
                    phrase, f"m-abnormal-measurement-{index}", self.subject_key
                )
                self.assertTrue(
                    any(
                        action.get("action") == "invalid_observation_not_promoted"
                        for action in result["actions"]
                    )
                )
        self.assertEqual(
            self.rows("SELECT * FROM state_item WHERE state_key LIKE 'measurement.%'"),
            [],
        )
        self.assertTrue(
            all(
                row["schema_state"] == "invalid"
                for row in self.rows(
                    "SELECT schema_state FROM observation_event ORDER BY received_at"
                )
            )
        )

    def test_skip_today_resumes_next_local_day_at_original_schedule_time(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-skip-task", self.subject_key)
        original_schedule = json.loads(
            self.rows("SELECT schedule_json FROM automation_task")[0][0]
        )

        result = self.store.observe(
            "今天先别提醒我喝水", "m-skip-feedback", self.subject_key
        )
        task = self.rows(
            "SELECT schedule_json,next_run_at,suppressed_until FROM automation_task"
        )[0]
        next_local = autonomy._parse_utc(task["next_run_at"]).astimezone(
            autonomy._zone("Asia/Shanghai")
        )
        suppressed_local = autonomy._parse_utc(task["suppressed_until"]).astimezone(
            autonomy._zone("Asia/Shanghai")
        )

        self.assertIn(
            {"action": "skip_today", "category": "hydration_cue"},
            result["actions"],
        )
        self.assertEqual(json.loads(task["schedule_json"]), original_schedule)
        self.assertEqual(next_local.date(), dt.date(2026, 8, 6))
        self.assertEqual(next_local.time().replace(tzinfo=None), dt.time(10, 30))
        self.assertEqual(suppressed_local.time().replace(tzinfo=None), dt.time(0, 0))
        self.clock.value = autonomy._parse_utc(task["next_run_at"])
        self.assertIn("该喝点水了", self.store.dispatch_due())

    def test_second_schedule_shift_requires_three_fresh_feedbacks_across_two_days(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-shift-task", self.subject_key)
        self.store.observe("喝水提醒太早了", "m-shift-1", self.subject_key)
        self.clock.value += dt.timedelta(hours=2)
        self.store.observe("喝水提醒太早了", "m-shift-2", self.subject_key)
        self.clock.value += dt.timedelta(days=1)
        self.store.observe("喝水提醒太早了", "m-shift-3", self.subject_key)
        once_shifted = json.loads(
            self.rows("SELECT schedule_json FROM automation_task")[0][0]
        )
        self.assertEqual(once_shifted["times"], ["11:00", "16:00"])

        self.clock.value += dt.timedelta(days=7, minutes=1)
        self.store.observe("喝水提醒太早了", "m-shift-4", self.subject_key)
        self.clock.value += dt.timedelta(hours=2)
        second = self.store.observe("喝水提醒太早了", "m-shift-5", self.subject_key)
        after_two_fresh = json.loads(
            self.rows("SELECT schedule_json FROM automation_task")[0][0]
        )
        self.assertEqual(after_two_fresh, once_shifted)
        self.assertFalse(
            any(a.get("action") == "stable_time_adjustment" for a in second["actions"])
        )

        self.clock.value += dt.timedelta(days=1)
        third = self.store.observe("喝水提醒太早了", "m-shift-6", self.subject_key)
        twice_shifted = json.loads(
            self.rows("SELECT schedule_json FROM automation_task")[0][0]
        )
        self.assertEqual(twice_shifted["times"], ["11:30", "16:30"])
        adjustment = [
            action
            for action in third["actions"]
            if action.get("action") == "stable_time_adjustment"
        ][0]
        self.assertEqual(
            (adjustment["support_count"], adjustment["support_days"]), (3, 2)
        )

    def test_correction_reaches_health_event_across_intervening_preference(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-health-before-pref", self.subject_key)
        self.clock.value += dt.timedelta(seconds=1)
        self.store.observe("回复简短一点", "m-pref-between", self.subject_key)
        self.clock.value += dt.timedelta(seconds=1)
        result = self.store.observe(
            "不是我，是我妈",
            "m-late-correction",
            self.subject_key,
            reply_to_message_id="m-health-before-pref",
        )

        events = self.rows(
            "SELECT event_id,correction_of FROM observation_event ORDER BY received_at,rowid"
        )
        self.assertEqual(events[2]["correction_of"], events[0]["event_id"])
        self.assertNotEqual(events[2]["correction_of"], events[1]["event_id"])
        self.assertTrue(any(a["action"] == "profile_corrected" for a in result["actions"]))
        preference = self.rows(
            "SELECT lifecycle FROM state_item WHERE domain='interaction_preference'"
        )[0]
        self.assertEqual(preference["lifecycle"], "active")
        task = self.rows("SELECT status,pause_reason FROM automation_task")[0]
        self.assertEqual((task["status"], task["pause_reason"]), ("paused", "trigger_corrected"))

    def test_reauthorization_tightens_categories_task_ttl_and_active_task_cap(self):
        initial = dataclasses.replace(self.config, max_new_tasks_7d=3)
        self.activate(initial)
        self.store.observe("我总忘记喝水", "m-reauth-water", self.subject_key)
        self.clock.value += dt.timedelta(seconds=1)
        self.store.observe("我总熬夜", "m-reauth-sleep", self.subject_key)
        self.clock.value += dt.timedelta(seconds=1)
        self.store.observe("我总忘记活动", "m-reauth-move", self.subject_key)
        self.clock.value += dt.timedelta(hours=1)

        tightened_times = dict(initial.category_times)
        tightened_times["hydration_cue"] = ("12:00",)
        tightened_times["wind_down"] = ("21:30",)
        tightened = dataclasses.replace(
            initial,
            categories=("hydration_cue", "wind_down"),
            category_times=tightened_times,
            task_ttl_days=5,
            data_retention_days=7,
            max_active_tasks=1,
        )
        self.store.activate(
            tightened,
            source_message_id="message-auth-2",
            dispatcher_job_id="job-health-v02",
            subject_key=self.subject_key,
        )

        tasks = {
            row["category"]: row
            for row in self.rows(
                "SELECT category,status,pause_reason,schedule_json,expires_at,max_runs "
                "FROM automation_task"
            )
        }
        self.assertEqual(tasks["hydration_cue"]["status"], "active")
        self.assertEqual(
            (tasks["wind_down"]["status"], tasks["wind_down"]["pause_reason"]),
            ("paused", "authorization_active_task_cap"),
        )
        self.assertEqual(
            (tasks["movement_cue"]["status"], tasks["movement_cue"]["pause_reason"]),
            ("paused", "authorization_scope_changed"),
        )
        self.assertEqual(
            json.loads(tasks["hydration_cue"]["schedule_json"])["times"], ["12:00"]
        )
        self.assertEqual(
            autonomy._parse_utc(tasks["hydration_cue"]["expires_at"]),
            self.clock.value + dt.timedelta(days=5),
        )
        self.assertEqual(tasks["hydration_cue"]["max_runs"], 5)
        policy = self.store.status(self.subject_key)["policy"]
        self.assertEqual(policy["categories"], ["hydration_cue", "wind_down"])
        self.assertEqual(policy["data_retention_days"], 7)
        self.assertEqual(policy["max_active_tasks"], 1)

    def test_ambiguous_feedback_does_not_mutate_but_named_hydration_can_pause(self):
        config = dataclasses.replace(self.config, max_new_tasks_7d=3)
        self.activate(config)
        self.store.observe("我总忘记喝水", "m-two-water", self.subject_key)
        self.clock.value += dt.timedelta(seconds=1)
        self.store.observe("我总熬夜", "m-two-sleep", self.subject_key)

        ambiguous = self.store.observe("停止提醒", "m-stop-ambiguous", self.subject_key)
        before = {
            row["category"]: row["status"]
            for row in self.rows("SELECT category,status FROM automation_task")
        }
        self.assertEqual(before, {"hydration_cue": "active", "wind_down": "active"})
        self.assertIn(
            {"action": "feedback_not_applied", "reason": "task_binding_required"},
            ambiguous["actions"],
        )

        specified = self.store.observe(
            "取消喝水提醒", "m-stop-hydration", self.subject_key
        )
        after = {
            row["category"]: (row["status"], row["pause_reason"])
            for row in self.rows(
                "SELECT category,status,pause_reason FROM automation_task"
            )
        }
        self.assertEqual(after["hydration_cue"], ("paused", "self_stop"))
        self.assertEqual(after["wind_down"], ("active", None))
        self.assertIn(
            {"action": "paused", "category": "hydration_cue", "reason": "self_stop"},
            specified["actions"],
        )

    def test_model_context_injects_only_topically_relevant_health_items(self):
        self.activate()
        self.store.observe("我最近睡不着", "m-context-sleep", self.subject_key)
        self.store.observe("我对花生过敏", "m-context-allergy", self.subject_key)
        self.store.observe(
            "我刚测血压120/80mmHg", "m-context-bp", self.subject_key
        )
        no_actions = {"result": "no_structured_change", "actions": []}

        sleep_context = self.store.context_for_model(
            "昨晚睡眠怎么样", no_actions, self.subject_key
        )
        self.assertIn("sleep.current_self_report", sleep_context)
        self.assertNotIn("allergy.self_report", sleep_context)
        self.assertNotIn("measurement.blood_pressure", sleep_context)

        allergy_context = self.store.context_for_model(
            "我的过敏信息是什么", no_actions, self.subject_key
        )
        self.assertIn("allergy.self_report", allergy_context)
        self.assertNotIn("sleep.current_self_report", allergy_context)
        self.assertNotIn("measurement.blood_pressure", allergy_context)

        unrelated_context = self.store.context_for_model(
            "今天工作很忙", no_actions, self.subject_key
        )
        self.assertNotIn("Minimum relevant structured observations", unrelated_context)

    def test_retention_purge_removes_expired_payload_and_task_metadata(self):
        config = dataclasses.replace(
            self.config, task_ttl_days=7, data_retention_days=7
        )
        self.activate(config)
        marker = b"routine.hydration_cue.self_report"
        self.store.observe("我总忘记喝水", "m-retention-task", self.subject_key)
        self.assertIn(marker, self.db_path.read_bytes())

        self.clock.value += dt.timedelta(days=8)
        self.assertEqual(self.store.dispatch_due(), "")

        self.assertEqual(self.rows("SELECT * FROM observation_event"), [])
        self.assertEqual(self.rows("SELECT * FROM state_item"), [])
        self.assertEqual(self.rows("SELECT * FROM decision_log"), [])
        self.assertEqual(self.rows("SELECT status,pause_reason FROM automation_task"), [])
        self.assertNotIn(marker, self.db_path.read_bytes())

    def test_concurrent_dispatch_claims_due_task_exactly_once(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-concurrent-task", self.subject_key)
        self.clock.value = autonomy._parse_utc(
            self.rows("SELECT next_run_at FROM automation_task")[0][0]
        )
        barrier = threading.Barrier(2)

        def dispatch() -> str:
            barrier.wait(timeout=5)
            return self.store.dispatch_due()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outputs = list(executor.map(lambda _: dispatch(), range(2)))

        self.assertEqual(sum(bool(output) for output in outputs), 1)
        self.assertTrue(any("该喝点水了" in output for output in outputs))
        self.assertEqual(len(self.rows("SELECT * FROM dispatch_event")), 1)
        self.assertEqual(self.rows("SELECT run_count FROM automation_task")[0][0], 1)

    def test_multiple_due_tasks_are_combined_into_one_dispatch(self):
        config = dataclasses.replace(self.config, max_new_tasks_7d=3)
        self.activate(config)
        self.store.observe("我总忘记喝水", "m-combine-water", self.subject_key)
        self.clock.value += dt.timedelta(seconds=1)
        self.store.observe("我总熬夜", "m-combine-sleep", self.subject_key)
        now_text = autonomy._utc_iso(self.clock.value)
        with contextlib.closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE automation_task SET next_run_at=?", (now_text,)
            )
            connection.commit()

        output = self.store.dispatch_due()

        self.assertIn("该喝点水了", output)
        self.assertIn("可以准备收尾休息了", output)
        dispatches = self.rows("SELECT task_ids_json FROM dispatch_event")
        self.assertEqual(len(dispatches), 1)
        self.assertEqual(len(json.loads(dispatches[0]["task_ids_json"])), 2)
        self.assertTrue(
            all(
                row["run_count"] == 1
                for row in self.rows("SELECT run_count FROM automation_task")
            )
        )

    def test_disabled_profile_and_learning_scopes_persist_no_corresponding_messages(self):
        disabled = dataclasses.replace(
            self.config, structured_profile=False, interaction_learning=False
        )
        self.activate(disabled)

        profile_result = self.store.observe(
            "我最近睡不着", "m-profile-disabled", self.subject_key
        )
        preference_result = self.store.observe(
            "回复简短一点，语气温柔一点",
            "m-learning-disabled",
            self.subject_key,
        )

        self.assertEqual(profile_result["result"], "no_structured_change")
        self.assertEqual(preference_result["result"], "no_structured_change")
        self.assertEqual(self.rows("SELECT * FROM observation_event"), [])
        self.assertEqual(self.rows("SELECT * FROM state_item"), [])

    def test_negated_interaction_preferences_are_not_learned(self):
        self.activate()
        phrases = (
            "不要回复简短一点",
            "我不喜欢简短一点",
            "不要语气温柔一点",
            "别一次只问一个",
        )
        for index, phrase in enumerate(phrases):
            with self.subTest(phrase=phrase):
                result = self.store.observe(
                    phrase, f"m-negated-pref-{index}", self.subject_key
                )
                self.assertEqual(result["result"], "no_structured_change")
        self.assertEqual(
            self.rows(
                "SELECT * FROM state_item WHERE domain='interaction_preference'"
            ),
            [],
        )

    def test_reauthorization_scope_off_hides_old_profile_and_preference_from_dispatch(self):
        self.activate()
        self.store.observe("我最近睡不着", "m-old-profile", self.subject_key)
        self.store.observe(
            "回复简短一点，语气温柔一点", "m-old-preference", self.subject_key
        )
        self.store.observe("我总忘记喝水", "m-old-hydration-task", self.subject_key)
        disabled = dataclasses.replace(
            self.config, structured_profile=False, interaction_learning=False
        )
        self.store.activate(
            disabled,
            source_message_id="message-auth-scopes-off",
            dispatcher_job_id="job-health-v02",
            subject_key=self.subject_key,
        )
        before_counts = (
            len(self.rows("SELECT * FROM observation_event")),
            len(self.rows("SELECT * FROM state_item")),
        )

        self.store.observe("我现在睡不着", "m-new-profile-off", self.subject_key)
        self.store.observe(
            "回复详细一点，语气直接一点", "m-new-preference-off", self.subject_key
        )
        after_counts = (
            len(self.rows("SELECT * FROM observation_event")),
            len(self.rows("SELECT * FROM state_item")),
        )
        context = self.store.context_for_model(
            "我的睡眠和喝水情况怎么样", {"actions": []}, self.subject_key
        )
        with contextlib.closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE automation_task SET next_run_at=?",
                (autonomy._utc_iso(self.clock.value),),
            )
            connection.commit()
        output = self.store.dispatch_due()

        self.assertEqual(after_counts, before_counts)
        self.assertNotIn("Interaction preferences", context)
        self.assertNotIn("Minimum relevant structured observations", context)
        self.assertTrue(output.startswith("健康管家："))
        self.assertIn("如果医生要求限制饮水，请按医嘱", output)
        self.assertNotIn("温柔提醒", output)

    def test_project_and_quoted_stop_text_do_not_pause_but_direct_self_stop_does(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-stop-task", self.subject_key)

        for index, phrase in enumerate(
            ("项目需求：停止提醒我喝水", "引用：“停止提醒我喝水”")
        ):
            with self.subTest(phrase=phrase):
                self.store.observe(phrase, f"m-stop-decoy-{index}", self.subject_key)
                task = self.rows("SELECT status,pause_reason FROM automation_task")[0]
                self.assertEqual((task["status"], task["pause_reason"]), ("active", None))

        result = self.store.observe(
            "不要提醒我喝水", "m-stop-direct", self.subject_key
        )
        task = self.rows("SELECT status,pause_reason FROM automation_task")[0]
        self.assertEqual((task["status"], task["pause_reason"]), ("paused", "self_stop"))
        self.assertIn(
            {"action": "paused", "category": "hydration_cue", "reason": "self_stop"},
            result["actions"],
        )

    def test_short_hydration_message_preserves_doctor_fluid_restriction_safety(self):
        self.activate()
        self.store.observe("回复简短一点", "m-short-safety-pref", self.subject_key)
        self.store.observe("我总忘记喝水", "m-short-safety-task", self.subject_key)
        self.clock.value = autonomy._parse_utc(
            self.rows("SELECT next_run_at FROM automation_task")[0][0]
        )

        output = self.store.dispatch_due()

        self.assertIn("该喝点水了", output)
        self.assertIn("医生限水要求", output)
        self.assertIn("请按医嘱", output)

    def test_private_path_chmod_failure_is_not_silently_accepted(self):
        probe = Path(self.tempdir.name) / "permission-probe.sqlite3"
        probe.touch()

        with mock.patch.object(
            autonomy.os, "chmod", side_effect=PermissionError("chmod denied")
        ):
            with self.assertRaisesRegex(PermissionError, "chmod denied"):
                autonomy.HealthAutonomyStore._protect_path(probe, 0o600)

    def test_private_path_symlink_shape_fails_closed_without_os_symlink_support(self):
        fake_path = mock.Mock(name="private-database-symlink")
        fake_path.lstat.return_value = types.SimpleNamespace(
            st_mode=autonomy.stat.S_IFLNK | 0o777
        )

        with mock.patch.object(autonomy.os, "chmod") as chmod:
            with self.assertRaisesRegex(PermissionError, "must not be a symlink"):
                autonomy.HealthAutonomyStore._protect_path(fake_path, 0o600)
        chmod.assert_not_called()

    def test_conflicting_early_and_late_feedback_never_shifts_schedule(self):
        self.activate()
        self.store.observe("我总忘记喝水", "m-conflict-task", self.subject_key)
        before = json.loads(self.rows("SELECT schedule_json FROM automation_task")[0][0])
        self.store.observe("喝水提醒太早了", "m-conflict-early-1", self.subject_key)
        self.clock.value += dt.timedelta(hours=1)
        self.store.observe("喝水提醒太晚了", "m-conflict-late", self.subject_key)
        self.clock.value += dt.timedelta(days=1)
        self.store.observe("喝水提醒太早了", "m-conflict-early-2", self.subject_key)
        self.clock.value += dt.timedelta(hours=2)

        result = self.store.observe(
            "喝水提醒太早了", "m-conflict-early-3", self.subject_key
        )
        task = self.rows(
            "SELECT schedule_json,revision,last_adjusted_at FROM automation_task"
        )[0]

        self.assertEqual(json.loads(task["schedule_json"]), before)
        self.assertEqual(task["revision"], 1)
        self.assertIsNone(task["last_adjusted_at"])
        self.assertIn(
            {
                "action": "schedule_not_adjusted",
                "category": "hydration_cue",
                "reason": "conflicting_explicit_time_feedback",
            },
            result["actions"],
        )


class CronBridgeTests(unittest.TestCase):
    routing = {
        "platform": "telegram",
        "user_id": "partner-user",
        "chat_id": "partner-chat",
        "thread_id": "",
        "chat_type": "dm",
    }

    def expected_job(self):
        return {
            "id": "job-health-v02",
            "name": autonomy.DISPATCH_JOB_NAME,
            "prompt": autonomy.DISPATCH_JOB_PROMPT,
            "script": autonomy.DISPATCH_JOB_SCRIPT,
            "no_agent": True,
            "deliver": "origin",
            "attach_to_session": False,
            "schedule": {"kind": "interval", "minutes": 5},
            "repeat": None,
            "origin": {
                **self.routing,
                "chat_type": "dm",
            },
            "enabled": True,
            "state": "active",
        }

    def test_create_uses_one_fixed_no_agent_dispatcher(self):
        calls = []

        def cronjob(**kwargs):
            return json.dumps({"success": True})

        def create_job(**kwargs):
            calls.append(kwargs)
            return {"id": "created-job", **kwargs}

        bridge = autonomy.HermesCronBridge(
            cronjob,
            lambda include_disabled: [],
            create_job,
            lambda: None,
        )
        job_id, created = bridge.ensure_dispatcher(self.routing)
        self.assertEqual((job_id, created), ("created-job", True))
        call = calls[0]
        self.assertTrue(call["no_agent"])
        self.assertEqual(call["script"], "health_autonomy_dispatch.py")
        self.assertEqual(call["deliver"], "origin")
        self.assertEqual(call["origin"]["chat_id"], "partner-chat")
        self.assertEqual(call["origin"]["chat_type"], "dm")
        self.assertIsNone(call["repeat"])
        self.assertIs(call["attach_to_session"], False)
        self.assertNotIn("model", call)

    def test_existing_dispatcher_must_match_full_fingerprint(self):
        bad_job = {
            "id": "bad",
            "name": autonomy.DISPATCH_JOB_NAME,
            "prompt": autonomy.DISPATCH_JOB_PROMPT,
            "script": "evil.py",
            "no_agent": True,
            "deliver": "origin",
            "attach_to_session": False,
            "schedule": {"kind": "interval", "minutes": 5},
        }
        bridge = autonomy.HermesCronBridge(
            lambda **kwargs: json.dumps({"success": True}),
            lambda include_disabled: [bad_job],
            lambda **kwargs: {"id": "unused"},
            lambda: None,
        )
        with self.assertRaisesRegex(RuntimeError, "指纹不匹配"):
            bridge.ensure_dispatcher(self.routing)

    def test_ensure_dispatcher_rejects_a_shadow_candidate(self):
        expected = self.expected_job()
        shadow = {
            **expected,
            "id": "shadow-job",
            "name": "unrelated-name",
        }
        bridge = autonomy.HermesCronBridge(
            lambda **kwargs: json.dumps({"success": True}),
            lambda include_disabled: [expected, shadow],
            lambda **kwargs: {"id": "unused"},
            lambda: None,
        )
        with self.assertRaisesRegex(RuntimeError, "多个健康自治调度器"):
            bridge.ensure_dispatcher(self.routing)

    def test_finite_repeat_legacy_skill_and_non_dm_dispatchers_are_rejected(self):
        finite_repeat = self.expected_job()
        finite_repeat["repeat"] = {"times": 1}
        legacy_skill = self.expected_job()
        legacy_skill["skill"] = "legacy-health-dispatch"
        non_dm = self.expected_job()
        non_dm["origin"] = {**non_dm["origin"], "chat_type": "group"}

        for name, job in (
            ("finite_repeat", finite_repeat),
            ("legacy_skill", legacy_skill),
            ("non_dm", non_dm),
        ):
            with self.subTest(case=name):
                bridge = autonomy.HermesCronBridge(
                    lambda **kwargs: json.dumps({"success": True}),
                    lambda include_disabled, candidate=job: [candidate],
                    lambda **kwargs: {"id": "unused"},
                    lambda: None,
                )
                with self.assertRaisesRegex(RuntimeError, "指纹不匹配"):
                    bridge.ensure_dispatcher(self.routing)

    def test_runtime_dispatcher_verification_accepts_exact_job_and_rejects_tamper(self):
        expected = self.expected_job()
        subject_key = autonomy.routing_subject_key(self.routing)
        bridge = autonomy.HermesCronBridge(
            lambda **kwargs: json.dumps({"success": True}),
            lambda include_disabled: [expected],
            lambda **kwargs: {"id": "unused"},
            lambda: None,
        )
        route_matches = lambda route: route == self.routing
        expected_fingerprint = autonomy.runtime_job_fingerprint(expected)
        self.assertTrue(
            bridge.verify_runtime_dispatcher(
                expected["id"],
                expected_fingerprint,
                expected["id"],
                subject_key,
                route_matches,
            )
        )
        self.assertFalse(
            bridge.verify_runtime_dispatcher(
                "different-caller",
                expected_fingerprint,
                expected["id"],
                subject_key,
                route_matches,
            )
        )

        stale_malicious_snapshot = {
            **expected,
            "deliver": "telegram:attacker-chat",
        }
        self.assertFalse(
            bridge.verify_runtime_dispatcher(
                expected["id"],
                autonomy.runtime_job_fingerprint(stale_malicious_snapshot),
                expected["id"],
                subject_key,
                route_matches,
            )
        )

        tampered = {**expected, "script": "tampered_dispatch.py"}
        tampered_bridge = autonomy.HermesCronBridge(
            lambda **kwargs: json.dumps({"success": True}),
            lambda include_disabled: [tampered],
            lambda **kwargs: {"id": "unused"},
            lambda: None,
        )
        self.assertFalse(
            tampered_bridge.verify_runtime_dispatcher(
                tampered["id"],
                autonomy.runtime_job_fingerprint(tampered),
                tampered["id"],
                subject_key,
                route_matches,
            )
        )

        duplicate = {**expected, "id": "shadow", "name": "shadow-name"}
        duplicate_bridge = autonomy.HermesCronBridge(
            lambda **kwargs: json.dumps({"success": True}),
            lambda include_disabled: [expected, duplicate],
            lambda **kwargs: {"id": "unused"},
            lambda: None,
        )
        self.assertFalse(
            duplicate_bridge.verify_runtime_dispatcher(
                expected["id"],
                expected_fingerprint,
                expected["id"],
                subject_key,
                route_matches,
            )
        )


class PluginBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "health_autonomy_plugin_under_test",
            PLUGIN_DIR / "__init__.py",
            submodule_search_locations=[str(PLUGIN_DIR)],
        )
        cls.plugin = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[spec.name] = cls.plugin
        spec.loader.exec_module(cls.plugin)

    def setUp(self):
        class FakeEngine:
            def __init__(self):
                self.calls = []
                self.store = types.SimpleNamespace(
                    dispatcher_job_id=lambda: "job-managed"
                )

            def activate(self, text, message_id, routing):
                self.calls.append(("activate", text, message_id, routing))
                return "activated"

            def control(self, action, routing, source_message_id=None):
                self.calls.append(
                    ("control", action, routing, source_message_id)
                )
                return action

            def observe(
                self, text, message_id, routing, reply_to_message_id=None
            ):
                self.calls.append(
                    ("observe", text, message_id, routing, reply_to_message_id)
                )
                return {"result": "applied"}, "trusted-context"

        self.engine = FakeEngine()
        self.plugin._ENGINE = self.engine
        self.plugin._TRUSTED_TURN.set(None)
        with self.plugin._BINDING_LOCK:
            self.plugin._RECENT_BINDINGS.clear()

    @staticmethod
    def source(authorized=True, chat_type="dm", profile="partner"):
        return types.SimpleNamespace(
            platform=types.SimpleNamespace(value="telegram"),
            chat_type=chat_type,
            profile=profile,
            user_id="partner-user",
            chat_id="partner-chat",
            thread_id="",
            message_id="m-source",
            authorized=authorized,
        )

    def test_unauthorized_or_group_source_cannot_bind_or_mutate(self):
        gateway = types.SimpleNamespace(
            _is_user_authorized=lambda source: source.authorized
        )
        for source in (self.source(authorized=False), self.source(chat_type="group")):
            event = types.SimpleNamespace(
                text=autonomy.activation_example(),
                source=source,
                internal=False,
                message_id="m-auth",
            )
            self.assertIsNone(self.plugin.pre_gateway_dispatch(event, gateway))
            self.assertIn("拒绝", self.plugin.health_autonomy_safe_command("status"))
        self.assertEqual(self.engine.calls, [])

    def test_verified_private_activation_uses_same_message_binding(self):
        gateway = types.SimpleNamespace(_is_user_authorized=lambda source: True)
        event = types.SimpleNamespace(
            text=autonomy.activation_example(),
            source=self.source(),
            internal=False,
            message_id="m-auth",
        )
        directive = self.plugin.pre_gateway_dispatch(event, gateway)
        self.assertEqual(directive["action"], "rewrite")
        raw_args = directive["text"].split(maxsplit=1)[1]
        self.assertEqual(self.plugin.health_autonomy_safe_command(raw_args), "activated")
        self.assertEqual(self.engine.calls[0][0], "activate")
        self.assertEqual(self.engine.calls[0][2], "m-auth")

    def test_direct_internal_slash_cannot_supply_a_different_activation(self):
        gateway = types.SimpleNamespace(_is_user_authorized=lambda source: True)
        event = types.SimpleNamespace(
            text="/health-autonomy-safe activate opaque",
            source=self.source(),
            internal=False,
            message_id="m-opaque",
        )
        self.assertIsNone(self.plugin.pre_gateway_dispatch(event, gateway))
        encoded = self.plugin._encode_activation(autonomy.activation_example())

        result = self.plugin.health_autonomy_safe_command(f"activate {encoded}")

        self.assertIn("当前可见消息不一致", result)
        self.assertEqual(self.engine.calls, [])

    def test_tampered_rewrite_payload_cannot_change_visible_authorization(self):
        gateway = types.SimpleNamespace(_is_user_authorized=lambda source: True)
        visible = autonomy.activation_example()
        event = types.SimpleNamespace(
            text=visible,
            source=self.source(),
            internal=False,
            message_id="m-tampered-authorization",
        )
        self.assertIsNotNone(self.plugin.pre_gateway_dispatch(event, gateway))
        altered = visible.replace("每日主动消息上限=3", "每日主动消息上限=2")

        result = self.plugin.health_autonomy_safe_command(
            f"activate {self.plugin._encode_activation(altered)}"
        )

        self.assertIn("当前可见消息不一致", result)
        self.assertEqual(self.engine.calls, [])

    def test_control_requires_visible_exact_sentence_not_direct_slash(self):
        gateway = types.SimpleNamespace(_is_user_authorized=lambda source: True)
        for visible_text, action in autonomy.CONTROL_EXACT.items():
            with self.subTest(action=action, route="direct-slash"):
                direct = types.SimpleNamespace(
                    text=f"/health-autonomy-safe {action}",
                    source=self.source(),
                    internal=False,
                    message_id=f"m-direct-{action}",
                )
                self.assertIsNone(self.plugin.pre_gateway_dispatch(direct, gateway))
                self.assertIn(
                    "当前可见消息不一致",
                    self.plugin.health_autonomy_safe_command(action),
                )
                self.assertEqual(self.engine.calls, [])

            with self.subTest(action=action, route="visible-sentence"):
                visible = types.SimpleNamespace(
                    text=visible_text + "。",
                    source=self.source(),
                    internal=False,
                    message_id=f"m-visible-{action}",
                )
                directive = self.plugin.pre_gateway_dispatch(visible, gateway)
                self.assertEqual(
                    directive,
                    {"action": "rewrite", "text": f"/health-autonomy-safe {action}"},
                )
                self.assertEqual(
                    self.plugin.health_autonomy_safe_command(action), action
                )
                self.assertEqual(self.engine.calls[-1][0], "control")
                self.engine.calls.clear()

    def test_plugin_routing_explicitly_binds_private_chat_type(self):
        binding = self.plugin.TrustedPrivateTurn(
            platform="telegram",
            user_id="partner-user",
            chat_id="partner-chat",
            thread_id="",
            message_id="m-route",
            reply_to_message_id="",
            text_hash="hash",
            captured_monotonic=0.0,
        )
        self.assertEqual(self.plugin._routing(binding)["chat_type"], "dm")

    def test_natural_turn_observation_requires_exact_sender_binding(self):
        gateway = types.SimpleNamespace(_is_user_authorized=lambda source: True)
        event = types.SimpleNamespace(
            text="回复简短一点",
            source=self.source(),
            internal=False,
            message_id="m-pref",
        )
        self.plugin.pre_gateway_dispatch(event, gateway)
        allowed = self.plugin.pre_llm_call(
            session_id="s",
            user_message=event.text,
            platform="telegram",
            sender_id="partner-user",
        )
        denied = self.plugin.pre_llm_call(
            session_id="s2",
            user_message=event.text,
            platform="telegram",
            sender_id="different-user",
        )
        self.assertEqual(allowed, {"context": "trusted-context"})
        self.assertIsNone(denied)

    def test_private_binding_is_invalidated_before_same_sender_group_turn(self):
        gateway = types.SimpleNamespace(_is_user_authorized=lambda source: True)
        private_event = types.SimpleNamespace(
            text="回复简短一点",
            source=self.source(chat_type="dm"),
            internal=False,
            message_id="m-private-before-group",
        )
        self.plugin.pre_gateway_dispatch(private_event, gateway)
        group_event = types.SimpleNamespace(
            text=private_event.text,
            source=self.source(chat_type="group"),
            internal=False,
            message_id="m-group-same-text",
        )

        self.assertIsNone(self.plugin.pre_gateway_dispatch(group_event, gateway))
        result = self.plugin.pre_llm_call(
            session_id="group-session",
            user_message=group_event.text,
            platform="telegram",
            sender_id="partner-user",
        )

        self.assertIsNone(result)
        self.assertEqual(self.engine.calls, [])

    def test_model_cannot_mutate_managed_dispatcher_or_private_database(self):
        managed = self.plugin.pre_tool_call(
            "cronjob", {"action": "pause", "job_id": "job-managed"}
        )
        database = self.plugin.pre_tool_call(
            "terminal", {"command": "sqlite3 health-autonomy-v02.sqlite3 .dump"}
        )
        self.assertEqual(managed["action"], "block")
        self.assertEqual(database["action"], "block")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import base64
import multiprocessing
import socket
import sqlite3
import tempfile
import threading
import unittest
import json
import datetime as dt
import inspect
import hashlib
from unittest import mock
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sidecar.protocol as protocol
import sidecar.store as store
import sidecar.server as server
import sidecar.client as client
import sidecar

ACTION_PING = protocol.ACTION_PING
ACTION_STATUS_GET = protocol.ACTION_STATUS_GET
ACTION_STATUS_SET = protocol.ACTION_STATUS_SET
ACTION_PROFILE_OWNER_BIND = protocol.ACTION_PROFILE_OWNER_BIND
ACTION_PROFILE_MESSAGE_STAGE = protocol.ACTION_PROFILE_MESSAGE_STAGE
ACTION_PROFILE_CANDIDATE = protocol.ACTION_PROFILE_CANDIDATE
ACTION_PROFILE_READ = protocol.ACTION_PROFILE_READ
parse_request = protocol.parse_request
response_ok = protocol.response_ok
HealthSidecarStore = store.HealthSidecarStore
HmacInboundMessageVerifier = store.HmacInboundMessageVerifier
StoreError = store.StoreError
HealthSidecarServer = server.HealthSidecarServer
_parse_uids = server._parse_uids
HealthSidecarClient = client.HealthSidecarClient


def _record_candidate(store_instance, candidate, sender_id="owner-1"):
    if sender_id == "owner-1":
        message_text = f"消息：{candidate['excerpt']}"
        token = store_instance.message_verifier.sign(
            subject="profile",
            sender_id=sender_id,
            message_id=candidate["source_message_id"],
            message_utc=candidate["source_utc"],
            message_text=message_text,
            evidence_kind=candidate["evidence_kind"],
        )
        store_instance.stage_profile_message(
            "profile",
            sender_id,
            candidate["source_message_id"],
            candidate["source_utc"],
            message_text,
            candidate["evidence_kind"],
            token,
        )
    return store_instance.record_profile_candidate("profile", sender_id, candidate)


def _stage_message(store_instance, subject, sender_id, message_id, message_utc, text, kind):
    token = store_instance.message_verifier.sign(
        subject=subject,
        sender_id=sender_id,
        message_id=message_id,
        message_utc=message_utc,
        message_text=text,
        evidence_kind=kind,
    )
    return store_instance.stage_profile_message(
        subject, sender_id, message_id, message_utc, text, kind, token
    )


def _bind_profile_owner(store_instance, subject, owner_sender_id):
    token = store_instance.message_verifier.sign_owner_binding(
        subject=subject, owner_sender_id=owner_sender_id
    )
    return store_instance.bind_profile_owner(subject, owner_sender_id, token)


class HealthSidecarStoreTests(unittest.TestCase):
    def test_audit_event_once_deduplicates_by_stable_event_id(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
            )
            details = {
                "actor_role": "weixin-delivery-adapter",
                "action": "weixin.send_once",
                "object_id": "hermes-health-stable-id",
                "recipient_id": "owner-1",
                "result": "sent",
                "reason": "provider-accepted",
            }

            sidecar_store.append_audit_event_once(
                "weixin-delivery-sent:hermes-health-stable-id",
                "weixin_delivery_sent",
                details,
            )
            sidecar_store.append_audit_event_once(
                "weixin-delivery-sent:hermes-health-stable-id",
                "weixin_delivery_sent",
                details,
            )

            events = sidecar_store.read_audit_events(limit=None)
            matching = [
                event
                for event in events
                if event.get("event") == "weixin_delivery_sent"
            ]
            self.assertEqual(len(matching), 1)
            self.assertEqual(
                matching[0]["details"]["audit_event_id"],
                "weixin-delivery-sent:hermes-health-stable-id",
            )

    def test_encrypt_and_decrypt_status_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
            )
            version = sidecar_store.write_subject_status(
                "owner", {"profile_summary_zh": "测试"}
            )
            self.assertEqual(version, 1)
            status = sidecar_store.read_subject_status("owner")
            self.assertEqual(status["profile_summary_zh"], "测试")
            self.assertIsNone(sidecar_store.read_subject_status("other"))

            backup_dir = root_path / "backups"
            self.assertTrue(backup_dir.exists())

    def test_refuses_plaintext_sqlite_state(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            state_path = root_path / "state.sqlite.enc"
            conn = sqlite3.connect(str(state_path))
            try:
                conn.execute("CREATE TABLE legacy_state(k TEXT PRIMARY KEY)")
                conn.commit()
            finally:
                conn.close()

            with self.assertRaisesRegex(StoreError, "plaintext-database-refused"):
                HealthSidecarStore(state_path, root_path / "key.bin")

    def test_store_uses_injected_clock_and_key_manager(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            fixed_time = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)
            clock = FixedClock(fixed_time)
            key_manager = FixedKeyManager()
            try:
                sidecar_store = HealthSidecarStore(
                    root_path / "state.sqlite.enc",
                    root_path / "key.bin",
                    clock=clock,
                    key_manager=key_manager,
                )
            except TypeError:
                sidecar_store = None

            self.assertIsNotNone(sidecar_store)
            sidecar_store.write_subject_status(
                "owner", {"profile_summary_zh": "测试"}
            )
            self.assertFalse((root_path / "key.bin").exists())
            self.assertEqual(key_manager.record_calls, 1)
            self.assertEqual(
                sidecar_store.read_audit_events()[-1]["utc"],
                fixed_time.replace(microsecond=0).isoformat(),
            )

    def test_atomic_write_preserves_previous_state_when_replace_is_interrupted(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            state_path = root_path / "state.sqlite.enc"
            sidecar_store = HealthSidecarStore(state_path, root_path / "key.bin")
            sidecar_store.write_subject_status(
                "owner", {"profile_summary_zh": "旧状态"}
            )
            previous_bytes = state_path.read_bytes()

            with mock.patch("os.replace", side_effect=OSError("simulated interruption")):
                with self.assertRaises(OSError):
                    sidecar_store.write_subject_status(
                        "owner", {"profile_summary_zh": "新状态"}
                    )

            self.assertEqual(state_path.read_bytes(), previous_bytes)
            self.assertFalse(list(root_path.glob(".*.tmp")))

    def test_profile_candidate_records_evidence_and_immutable_version(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin"
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            first = _record_candidate(sidecar_store, {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-1",
                    "source_utc": "2026-01-02T03:04:05+08:00",
                    "excerpt": "最近睡眠不佳",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "sleep",
                            "text": "最近睡眠不佳",
                            "status": "fact",
                            "priority": 90,
                        }
                    ],
                })
            first_snapshot = sidecar_store.read_profile("profile", "owner-1")
            second = _record_candidate(sidecar_store, {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-2",
                    "source_utc": "2026-01-03T03:04:05+08:00",
                    "excerpt": "昨晚睡得好一些",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "sleep",
                            "text": "昨晚睡眠有所改善",
                            "status": "tendency",
                            "priority": 80,
                        }
                    ],
                })
            profile = sidecar_store.read_profile("profile", "owner-1")

            self.assertNotEqual(first["version_id"], second["version_id"])
            self.assertEqual(profile["current_version_id"], second["version_id"])
            self.assertEqual(len(profile["profile_versions"]), 2)
            self.assertEqual(
                profile["profile_versions"][0],
                first_snapshot["profile_versions"][0],
            )
            self.assertEqual(len(profile["evidence"]), 2)
            self.assertEqual(profile["evidence"][0]["source_message_id"], "msg-1")
            self.assertEqual(profile["evidence"][0]["source_utc"], "2026-01-01T19:04:05+00:00")

    def test_profile_measurement_and_owner_relayed_clinician_advice_are_typed(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin"
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            _record_candidate(sidecar_store, {
                    "evidence_kind": "measurement",
                    "source_message_id": "msg-m",
                    "source_utc": "2026-01-02T03:04:05Z",
                    "excerpt": "体温 37.5 °C",
                    "measurement": {
                        "type": "body_temperature",
                        "value": 37.5,
                        "unit": "°C",
                        "observed_utc": "2026-01-02T02:55:00Z",
                    },
                    "conclusions": [],
                })
            _record_candidate(sidecar_store, {
                    "evidence_kind": "owner_relayed_clinician",
                    "source_message_id": "msg-c",
                    "source_utc": "2026-01-02T04:04:05Z",
                    "excerpt": "我转述医生建议先观察",
                    "conclusions": [],
                })
            evidence = sidecar_store.read_profile("profile", "owner-1")["evidence"]

            self.assertEqual(evidence[0]["measurement"]["type"], "body_temperature")
            self.assertEqual(evidence[0]["measurement"]["value"], 37.5)
            self.assertEqual(evidence[0]["measurement"]["unit"], "°C")
            self.assertEqual(evidence[1]["owner_relayed"], True)

    def test_non_personal_evidence_and_non_owner_are_rejected_without_write(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin"
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            base = {
                "source_message_id": "msg-1",
                "source_utc": "2026-01-02T03:04:05Z",
                "excerpt": "普通聊天",
                "conclusions": [],
            }
            for sender_id, kind, error in (
                ("other", "direct_statement", "non-owner-evidence"),
                ("owner-1", "ordinary_chat", "not-personal-evidence"),
                ("owner-1", "source_card", "not-personal-evidence"),
                ("owner-1", "model_inference", "not-personal-evidence"),
            ):
                candidate = dict(base)
                candidate["evidence_kind"] = kind
                with self.assertRaisesRegex(StoreError, error):
                    sidecar_store.record_profile_candidate(
                        "profile", sender_id, candidate
                    )
            profile = sidecar_store.read_profile("profile", "owner-1")
            self.assertEqual(profile["evidence"], [])
            self.assertEqual(profile["profile_versions"], [])

    def test_profile_summary_caps_categories_and_has_no_markdown(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin"
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            conclusions = []
            for index in range(3):
                conclusions.append(
                    {
                        "category": "state",
                        "dedupe_key": f"state-{index}",
                        "text": f"状态{index}",
                        "status": "fact",
                        "priority": 90 - index,
                    }
                )
            for index in range(4):
                conclusions.append(
                    {
                        "category": "habit_goal",
                        "dedupe_key": f"habit-{index}",
                        "text": f"习惯{index}",
                        "status": "tendency",
                        "priority": 80 - index,
                    }
                )
            for index in range(3):
                conclusions.append(
                    {
                        "category": "interaction_preference",
                        "dedupe_key": f"pref-{index}",
                        "text": f"偏好{index}",
                        "status": "fact",
                        "priority": 70 - index,
                    }
                )
            for index in range(2):
                conclusions.append(
                    {
                        "category": "task_context",
                        "dedupe_key": f"task-{index}",
                        "text": f"任务{index}",
                        "status": "tendency",
                        "priority": 60 - index,
                    }
                )
            result = _record_candidate(sidecar_store, {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-caps",
                    "source_utc": "2026-01-02T03:04:05Z",
                    "excerpt": "我希望用简短方式沟通",
                    "conclusions": conclusions,
                })
            summary = sidecar_store.read_profile("profile", "owner-1")["profile_summary_zh"]
            counts = {"state": 0, "habit_goal": 0, "interaction_preference": 0, "task_context": 0}
            for item in result["conclusions"]:
                counts[item["category"]] += 1
            self.assertLessEqual(counts["state"], 2)
            self.assertLessEqual(counts["habit_goal"], 3)
            self.assertLessEqual(counts["interaction_preference"], 2)
            self.assertLessEqual(counts["task_context"], 1)
            self.assertLessEqual(len(summary), 300)
            self.assertNotRegex(summary, r"[`*_#]|\[[^]]+\]\(")

    def test_profile_rejects_markdown_in_candidate_conclusion(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin"
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            candidate = {
                "evidence_kind": "direct_statement",
                "source_message_id": "msg-markdown",
                "source_utc": "2026-01-02T03:04:05Z",
                "excerpt": "我最近睡眠不佳",
                "conclusions": [
                    {
                        "category": "state",
                        "dedupe_key": "sleep",
                        "text": "**睡眠不佳**",
                        "status": "fact",
                        "priority": 90,
                    }
                ],
            }
            _stage_message(
                sidecar_store, "profile", "owner-1",
                candidate["source_message_id"], candidate["source_utc"],
                candidate["excerpt"], candidate["evidence_kind"],
            )
            with self.assertRaisesRegex(StoreError, "profile-summary-markdown-forbidden"):
                sidecar_store.record_profile_candidate("profile", "owner-1", candidate)

    def test_profile_requires_excerpt_to_match_staged_source_message(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin"
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            _stage_message(
                sidecar_store, "profile", "owner-1", "msg-source",
                "2026-01-02T03:04:05Z", "真实的主人健康陈述", "direct_statement",
            )
            with self.assertRaisesRegex(StoreError, "evidence-excerpt-not-in-source"):
                sidecar_store.record_profile_candidate(
                    "profile",
                    "owner-1",
                    {
                        "evidence_kind": "direct_statement",
                        "source_message_id": "msg-source",
                        "source_utc": "2026-01-02T03:04:05Z",
                        "excerpt": "伪造的模型推断",
                        "conclusions": [],
                    },
                )

    def test_profile_staging_rejects_ordinary_chat_and_kind_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin"
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            with self.assertRaisesRegex(StoreError, "profile-message-not-eligible"):
                sidecar_store.stage_profile_message(
                    "profile", "owner-1", "msg-chat", "2026-01-02T03:04:05Z",
                    "good morning", "ordinary_chat", "invalid-token",
                )
            with self.assertRaisesRegex(StoreError, "unverified-inbound-message"):
                sidecar_store.stage_profile_message(
                    "profile", "owner-1", "msg-unverified",
                    "2026-01-02T03:04:05Z", "personal symptom",
                    "direct_statement", "invalid-token",
                )
            _stage_message(
                sidecar_store, "profile", "owner-1", "msg-kind",
                "2026-01-02T03:04:05Z", "personal symptom", "direct_statement",
            )
            with self.assertRaisesRegex(StoreError, "source-kind-mismatch"):
                sidecar_store.record_profile_candidate(
                    "profile",
                    "owner-1",
                    {
                        "evidence_kind": "measurement",
                        "source_message_id": "msg-kind",
                        "source_utc": "2026-01-02T03:04:05Z",
                        "excerpt": "personal symptom",
                        "measurement": {
                            "type": "pain_score",
                            "value": 2,
                            "unit": "score",
                            "observed_utc": "2026-01-02T03:04:05Z",
                        },
                        "conclusions": [],
                    },
                )

    def test_profile_failed_candidate_keeps_source_for_retry(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                clock=FixedClock(dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)),
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            candidate = {
                "evidence_kind": "direct_statement",
                "source_message_id": "msg-retry",
                "source_utc": "2026-01-02T03:04:05Z",
                "excerpt": "retryable health statement",
                "conclusions": [
                    {
                        "category": "state",
                        "dedupe_key": "critical-a",
                        "text": "A" * 180,
                        "status": "fact",
                        "priority": 100,
                        "task_dependency": True,
                    },
                    {
                        "category": "state",
                        "dedupe_key": "critical-b",
                        "text": "B" * 180,
                        "status": "fact",
                        "priority": 99,
                        "task_dependency": True,
                    },
                ],
            }
            _stage_message(
                sidecar_store, "profile", "owner-1",
                candidate["source_message_id"], candidate["source_utc"],
                candidate["excerpt"], candidate["evidence_kind"],
            )
            with self.assertRaisesRegex(StoreError, "summary_overflow"):
                sidecar_store.record_profile_candidate("profile", "owner-1", candidate)

            retry = dict(candidate)
            retry["conclusions"] = []
            result = sidecar_store.record_profile_candidate(
                "profile", "owner-1", retry
            )
            self.assertTrue(result["evidence_id"].startswith("ev-"))
            self.assertEqual(
                len(sidecar_store.read_profile("profile", "owner-1")["evidence"]),
                1,
            )

    def test_profile_deduplicates_source_message_id(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin"
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            candidate = {
                "evidence_kind": "direct_statement",
                "source_message_id": "msg-dedupe",
                "source_utc": "2026-01-02T03:04:05Z",
                "excerpt": "same source",
                "conclusions": [],
            }
            _record_candidate(sidecar_store, candidate)
            with self.assertRaisesRegex(StoreError, "duplicate-source-message"):
                _stage_message(
                    sidecar_store, "profile", "owner-1",
                    candidate["source_message_id"], candidate["source_utc"],
                    candidate["excerpt"], candidate["evidence_kind"],
                )
            self.assertEqual(
                len(sidecar_store.read_profile("profile", "owner-1")["evidence"]),
                1,
            )

    def test_generic_status_seam_protects_profile_state(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin"
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            with self.assertRaisesRegex(StoreError, "profile-state-protected"):
                sidecar_store.write_subject_status("profile", {"profile_summary_zh": "bypass"})
            with self.assertRaisesRegex(StoreError, "profile-state-protected"):
                sidecar_store.read_subject_status("profile")

            forged_store = HealthSidecarStore(
                root_path / "forged.sqlite.enc", root_path / "forged.key"
            )
            forged_status = {
                "profile_schema_version": 1,
                "owner_sender_id": "forged-owner",
                "evidence": [],
                "profile_versions": [],
                "current_version_id": None,
                "profile_summary_zh": "forged",
                "conclusions": [],
            }
            with self.assertRaisesRegex(StoreError, "profile-state-protected"):
                forged_store.write_subject_status("profile", forged_status)

    def test_profile_hypothesis_cannot_create_automatic_task_and_questions_are_once(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store_instance = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                clock=FixedClock(dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)),
            )
            _bind_profile_owner(store_instance, "profile", "owner-1")
            with self.assertRaisesRegex(StoreError, "hypothesis-task-not-allowed"):
                _record_candidate(
                    store_instance,
                    {
                        "evidence_kind": "direct_statement",
                        "source_message_id": "msg-hypothesis-task",
                        "source_utc": "2026-01-02T03:04:05Z",
                        "excerpt": "可能需要核实",
                        "conclusions": [
                            {
                                "category": "state",
                                "dedupe_key": "uncertain",
                                "text": "可能需要核实",
                                "status": "unverified_hypothesis",
                                "priority": 80,
                                "task_dependency": True,
                            }
                        ],
                    },
                )
            result = _record_candidate(
                store_instance,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-hypothesis",
                    "source_utc": "2026-01-02T03:05:05Z",
                    "excerpt": "可能需要核实",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "uncertain",
                            "text": "可能需要核实",
                            "status": "unverified_hypothesis",
                            "priority": 80,
                            "completion_question": True,
                        }
                    ],
                },
            )
            self.assertFalse(result["conclusions"][0]["automatic_task_eligible"])
            self.assertTrue(result["conclusions"][0]["completion_question_issued"])
            with self.assertRaisesRegex(StoreError, "completion-question-already-issued"):
                _record_candidate(
                    store_instance,
                    {
                        "evidence_kind": "direct_statement",
                        "source_message_id": "msg-hypothesis-again",
                        "source_utc": "2026-01-02T03:06:05Z",
                        "excerpt": "仍然需要核实",
                        "conclusions": [
                            {
                                "category": "state",
                                "dedupe_key": "uncertain",
                                "text": "仍然需要核实",
                                "status": "unverified_hypothesis",
                                "completion_question": True,
                            }
                        ],
                    },
                )

    def test_profile_newer_direct_statement_wins_and_measurements_coexist(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store_instance = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                clock=FixedClock(dt.datetime(2026, 1, 2, 12, tzinfo=dt.timezone.utc)),
            )
            _bind_profile_owner(store_instance, "profile", "owner-1")
            _record_candidate(
                store_instance,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-newer",
                    "source_utc": "2026-01-02T11:00:00Z",
                    "excerpt": "现在好多了",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "pain",
                            "text": "现在好多了",
                            "status": "fact",
                        }
                    ],
                },
            )
            _record_candidate(
                store_instance,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-older",
                    "source_utc": "2026-01-02T09:00:00Z",
                    "excerpt": "早些时候仍然不舒服",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "pain",
                            "text": "早些时候仍然不舒服",
                            "status": "fact",
                        }
                    ],
                },
            )
            profile = store_instance.read_profile("profile", "owner-1")
            self.assertEqual(profile["conclusions"][0]["text"], "现在好多了")

            result = _record_candidate(
                store_instance,
                {
                    "evidence_kind": "measurement",
                    "source_message_id": "msg-measurement",
                    "source_utc": "2026-01-02T10:00:00Z",
                    "excerpt": "体温 37.5 C",
                    "measurement": {
                        "type": "body_temperature",
                        "value": 37.5,
                        "unit": "C",
                        "observed_utc": "2026-01-02T10:00:00Z",
                    },
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "pain",
                            "text": "体温记录",
                            "status": "fact",
                        }
                    ],
                },
            )
            self.assertEqual(len(result["conclusions"]), 2)

    def test_profile_high_impact_conflict_becomes_hypothesis(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store_instance = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                clock=FixedClock(dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)),
            )
            _bind_profile_owner(store_instance, "profile", "owner-1")
            for index, (message_id, text) in enumerate(
                (("msg-a", "疼痛很重"), ("msg-b", "完全不痛"))
            ):
                result = _record_candidate(
                    store_instance,
                    {
                        "evidence_kind": "direct_statement",
                        "source_message_id": message_id,
                        "source_utc": f"2026-01-02T0{3 + index}:04:05Z",
                        "excerpt": text,
                        "conclusions": [
                            {
                                "category": "state",
                                "dedupe_key": message_id,
                                "text": text,
                                "status": "fact",
                                "conflict_key": "pain-level",
                                "high_impact": True,
                            }
                        ],
                    },
                )
            conclusion = result["conclusions"][0]
            self.assertEqual(conclusion["status"], "unverified_hypothesis")
            self.assertFalse(conclusion["automatic_task_eligible"])
            self.assertTrue(conclusion["completion_question_issued"])

    def test_profile_preferences_require_explicit_feedback_or_three_behaviors(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            clock = FixedClock(dt.datetime(2026, 1, 2, 12, tzinfo=dt.timezone.utc))
            store_instance = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin", clock=clock
            )
            _bind_profile_owner(store_instance, "profile", "owner-1")
            same_source_conclusions = [
                {
                    "category": "interaction_preference",
                    "dedupe_key": "same-source",
                    "text": "偏好详细回复",
                    "status": "fact",
                    "preference_mode": "implicit",
                    "preference_signal": "owner_behavior",
                    "behavior_id": f"forged-{index}",
                }
                for index in range(1, 4)
            ]
            same_source = _record_candidate(
                store_instance,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-one-source",
                    "source_utc": "2026-01-02T03:04:05Z",
                    "excerpt": "一条消息",
                    "conclusions": same_source_conclusions,
                },
            )
            self.assertFalse(same_source["conclusions"][-1]["active"])
            self.assertEqual(len(same_source["conclusions"][-1]["behavior_events"]), 1)
            explicit = _record_candidate(
                store_instance,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-explicit-pref",
                    "source_utc": "2026-01-02T03:04:05Z",
                    "excerpt": "请用简短回复",
                    "conclusions": [
                        {
                            "category": "interaction_preference",
                            "dedupe_key": "concise",
                            "text": "偏好简短回复",
                            "status": "fact",
                            "preference_mode": "explicit",
                        }
                    ],
                },
            )
            self.assertTrue(explicit["conclusions"][0]["active"])
            with self.assertRaisesRegex(StoreError, "preference-evidence-excluded"):
                _record_candidate(
                    store_instance,
                    {
                        "evidence_kind": "direct_statement",
                        "source_message_id": "msg-silence",
                        "source_utc": "2026-01-02T03:05:05Z",
                        "excerpt": "silence signal",
                        "conclusions": [
                            {
                                "category": "interaction_preference",
                                "dedupe_key": "silent",
                                "text": "不主动联系",
                                "status": "fact",
                                "preference_mode": "implicit",
                                "preference_signal": "silence",
                                "behavior_id": "silence-1",
                            }
                        ],
                    },
                )
            for index in range(1, 4):
                result = _record_candidate(
                    store_instance,
                    {
                        "evidence_kind": "direct_statement",
                        "source_message_id": f"msg-implicit-{index}",
                        "source_utc": f"2026-01-02T03:0{index}:05Z",
                        "excerpt": f"行为 {index}",
                        "conclusions": [
                            {
                                "category": "interaction_preference",
                                "dedupe_key": "detail-level",
                                "text": "偏好详细回复",
                                "status": "fact",
                                "preference_mode": "implicit",
                                "preference_signal": "owner_behavior",
                                "behavior_id": f"behavior-{index}",
                            }
                        ],
                    },
                )
                detail = next(
                    item
                    for item in result["conclusions"]
                    if item["dedupe_key"] == "detail-level"
                )
                if index < 3:
                    self.assertFalse(detail["active"])
            self.assertTrue(detail["active"])
            self.assertEqual(len(detail["behavior_ids"]), 3)
            clock.now = dt.datetime(2026, 3, 5, tzinfo=dt.timezone.utc)
            _record_candidate(
                store_instance,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-expire-pref",
                    "source_utc": "2026-03-05T00:00:00Z",
                    "excerpt": "新的健康状态",
                    "conclusions": [],
                },
            )
            profile = store_instance.read_profile("profile", "owner-1")
            self.assertFalse(any(item.get("active") for item in profile["conclusions"] if item["category"] == "interaction_preference"))

    def test_profile_preference_window_and_conflict_expiry_are_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            clock = FixedClock(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
            store_instance = HealthSidecarStore(
                root_path / "state.sqlite.enc", root_path / "key.bin", clock=clock
            )
            _bind_profile_owner(store_instance, "profile", "owner-1")
            for index, when in enumerate(
                ("2026-01-01T01:00:00Z", "2026-02-01T01:00:00Z", "2026-06-01T01:00:00Z"),
                start=1,
            ):
                clock.now = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
                result = _record_candidate(
                    store_instance,
                    {
                        "evidence_kind": "direct_statement",
                        "source_message_id": f"msg-window-{index}",
                        "source_utc": when,
                        "excerpt": f"行为 {index}",
                        "conclusions": [
                            {
                                "category": "interaction_preference",
                                "dedupe_key": "windowed",
                                "text": "偏好详细回复",
                                "status": "fact",
                                "preference_mode": "implicit",
                                "preference_signal": "owner_behavior",
                                "behavior_id": f"window-{index}",
                            }
                        ],
                    },
                )
            self.assertFalse(result["conclusions"][-1]["active"])
            self.assertEqual(result["conclusions"][-1]["behavior_ids"], ["window-3"])

            clock.now = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
            for message_id, source_utc, text in (
                ("msg-conflict-a", "2026-01-01T02:00:00Z", "疼痛很重"),
                ("msg-conflict-b", "2026-01-01T04:00:00Z", "完全不痛"),
            ):
                _record_candidate(
                    store_instance,
                    {
                        "evidence_kind": "direct_statement",
                        "source_message_id": message_id,
                        "source_utc": source_utc,
                        "excerpt": text,
                        "conclusions": [
                            {
                                "category": "state",
                                "dedupe_key": message_id,
                                "text": text,
                                "status": "fact",
                                "conflict_key": "windowed-pain",
                                "high_impact": True,
                            }
                        ],
                    },
                )
            self.assertTrue(
                any(
                    item.get("dedupe_key") == "conflict:windowed-pain"
                    for item in store_instance.read_profile("profile", "owner-1")["conclusions"]
                )
            )
            clock.now = dt.datetime(2026, 2, 5, tzinfo=dt.timezone.utc)
            _record_candidate(
                store_instance,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-after-conflict",
                    "source_utc": "2026-02-05T00:00:00Z",
                    "excerpt": "新的状态",
                    "conclusions": [],
                },
            )
            self.assertFalse(
                any(
                    item.get("dedupe_key") == "conflict:windowed-pain"
                    for item in store_instance.read_profile("profile", "owner-1")["conclusions"]
                )
            )

    def test_inbound_verifier_is_a_replaceable_controlled_port(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            verifier = FixedInboundVerifier()
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                message_verifier=verifier,
            )
            self.assertTrue(
                sidecar_store.bind_profile_owner("profile", "owner-1", "owner-token")
            )
            self.assertTrue(
                sidecar_store.stage_profile_message(
                    "profile",
                    "owner-1",
                    "msg-controlled",
                    "2026-01-02T03:04:05Z",
                    "controlled inbound",
                    "direct_statement",
                    "message-token",
                )
            )
            self.assertEqual(verifier.message_tokens, ["message-token"])

    def test_ed25519_public_receipt_verifier_rejects_tampering(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
        except ImportError:
            self.skipTest("cryptography ed25519 unavailable")
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        verifier = sidecar.Ed25519InboundMessageVerifier(public)
        payload = store.HmacInboundMessageVerifier._canonical(
            subject="profile",
            sender_id="owner-1",
            message_id="msg-ed25519",
            message_utc="2026-01-02T03:04:05Z",
            message_text="signed inbound",
            evidence_kind="direct_statement",
        )
        token = base64.urlsafe_b64encode(private.sign(payload)).decode("ascii")
        self.assertTrue(
            verifier.verify(
                subject="profile",
                sender_id="owner-1",
                message_id="msg-ed25519",
                message_utc="2026-01-02T03:04:05Z",
                message_text="signed inbound",
                evidence_kind="direct_statement",
                token=token,
            )
        )
        self.assertFalse(
            verifier.verify(
                subject="profile",
                sender_id="owner-1",
                message_id="msg-ed25519",
                message_utc="2026-01-02T03:04:05Z",
                message_text="tampered inbound",
                evidence_kind="direct_statement",
                token=token,
            )
        )

    def test_profile_summary_overflow_fails_closed_without_new_version(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                clock=FixedClock(dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)),
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            long_text = "重要状态" * 45
            candidate = {
                "evidence_kind": "direct_statement",
                "source_message_id": "msg-overflow",
                "source_utc": "2026-01-02T03:04:05Z",
                "excerpt": "我有很多需要记录的情况",
                "conclusions": [
                    {
                        "category": "state",
                        "dedupe_key": "critical-a",
                        "text": long_text,
                        "status": "fact",
                        "priority": 100,
                        "task_dependency": True,
                    },
                    {
                        "category": "state",
                        "dedupe_key": "critical-b",
                        "text": long_text,
                        "status": "fact",
                        "priority": 99,
                        "task_dependency": True,
                    },
                ],
            }
            _stage_message(
                sidecar_store, "profile", "owner-1",
                candidate["source_message_id"], candidate["source_utc"],
                f"消息：{candidate['excerpt']}", candidate["evidence_kind"],
            )
            with self.assertRaisesRegex(StoreError, "summary_overflow"):
                sidecar_store.record_profile_candidate("profile", "owner-1", candidate)
            profile = sidecar_store.read_profile("profile", "owner-1")
            self.assertEqual(profile["evidence"], [])
            self.assertEqual(profile["profile_versions"], [])

    def test_profile_compaction_expires_and_merges_synonyms_before_summary(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                clock=FixedClock(dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)),
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            _record_candidate(sidecar_store, {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-old",
                    "source_utc": "2026-01-01T00:00:00Z",
                    "excerpt": "之前的情况已过期",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "old",
                            "text": "已过期状态",
                            "status": "fact",
                            "priority": 20,
                            "valid_until_utc": "2026-01-01T00:00:00Z",
                        },
                        {
                            "category": "state",
                            "dedupe_key": "sleep",
                            "text": "睡眠较差",
                            "status": "fact",
                            "priority": 90,
                        },
                    ],
                })
            result = _record_candidate(sidecar_store, {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-new",
                    "source_utc": "2026-01-02T00:00:00Z",
                    "excerpt": "睡眠比昨天好一些",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "sleep-improved",
                            "aliases": ["sleep"],
                            "text": "睡眠有所改善",
                            "status": "tendency",
                            "priority": 80,
                        }
                    ],
                })
            conclusions = result["conclusions"]
            self.assertEqual(len(conclusions), 1)
            self.assertEqual(conclusions[0]["text"], "睡眠有所改善")
            self.assertEqual(len(conclusions[0]["evidence_ids"]), 1)
            self.assertNotIn("已过期状态", result["profile_summary_zh"])

    def test_profile_applies_default_expiry_to_unbounded_conclusions(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            clock = FixedClock(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                clock=clock,
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            _record_candidate(
                sidecar_store,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-acute",
                    "source_utc": "2026-01-01T00:00:00Z",
                    "excerpt": "acute symptom",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "acute",
                            "text": "acute symptom",
                            "status": "fact",
                            "priority": 90,
                        }
                    ],
                },
            )
            clock.now = dt.datetime(2026, 1, 3, tzinfo=dt.timezone.utc)
            result = _record_candidate(
                sidecar_store,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-new-state",
                    "source_utc": "2026-01-03T00:00:00Z",
                    "excerpt": "new symptom",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "new",
                            "text": "new symptom",
                            "status": "fact",
                            "priority": 80,
                        }
                    ],
                },
            )
            self.assertEqual([item["dedupe_key"] for item in result["conclusions"]], ["new"])

    def test_profile_default_expiry_uses_source_time_not_acceptance_time(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                clock=FixedClock(dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc)),
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            result = _record_candidate(
                sidecar_store,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-delayed",
                    "source_utc": "2026-01-01T00:00:00Z",
                    "excerpt": "delayed acute statement",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "delayed-acute",
                            "text": "delayed acute statement",
                            "status": "fact",
                            "priority": 90,
                        }
                    ],
                },
            )
            self.assertEqual(result["conclusions"], [])
            self.assertEqual(result["profile_summary_zh"], "")

    def test_profile_summary_defers_low_priority_conclusion_without_task_dependency(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            sidecar_store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                clock=FixedClock(dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)),
            )
            _bind_profile_owner(sidecar_store, "profile", "owner-1")
            long_text = "重要状态" * 45
            result = _record_candidate(sidecar_store, {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-defer",
                    "source_utc": "2026-01-02T03:04:05Z",
                    "excerpt": "我有一项重要情况和一项次要情况",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "high",
                            "text": long_text,
                            "status": "fact",
                            "priority": 100,
                        },
                        {
                            "category": "state",
                            "dedupe_key": "low",
                            "text": long_text,
                            "status": "tendency",
                            "priority": 1,
                        },
                    ],
                })
            self.assertEqual(len(result["conclusions"]), 1)
            self.assertEqual(result["conclusions"][0]["dedupe_key"], "high")
            self.assertLessEqual(len(result["profile_summary_zh"]), 300)
            profile = sidecar_store.read_profile("profile", "owner-1")
            self.assertEqual(
                [item["dedupe_key"] for item in profile["deferred_conclusions"]],
                ["low"],
            )


class HealthSidecarProtocolTests(unittest.TestCase):
    def test_large_response_stream_frames_are_bounded_ordered_and_complete(self):
        response = response_ok(
            "stream-large-view",
            protocol.ACTION_ACCESS_READ,
            {"health_view": "健" * 100_000},
        )

        frames = list(
            protocol.iter_stream_response_frames(
                response,
                max_frame_bytes=client.MAX_FRAME_BYTES,
            )
        )

        self.assertGreater(len(frames), 1)
        self.assertTrue(
            all(len(frame) <= client.MAX_FRAME_BYTES for frame in frames)
        )
        chunks = []
        expected_digest = hashlib.sha256(response).digest()
        for expected_index, frame in enumerate(frames):
            index, total, digest, chunk = protocol.parse_stream_response_frame(
                frame
            )
            self.assertEqual(index, expected_index)
            self.assertEqual(total, len(frames))
            self.assertEqual(digest, expected_digest)
            chunks.append(chunk)
        self.assertEqual(b"".join(chunks), response)

    def test_request_roundtrip_for_known_action(self):
        req = parse_request(
            b'{"req_id":"1","action":"health.ping","payload":{}}'
        )
        self.assertEqual(req.action, "health.ping")

    def test_response_success_is_json(self):
        encoded = response_ok("r", "health.ping", {"status": "ok"})
        self.assertIn(b'"ok":true', encoded)

    def test_request_rejects_empty_status_payload(self):
        with self.assertRaises(protocol.SidecarProtocolError):
            parse_request(
                b'{"action":"health.status.set","payload":{"subject":"owner","status":{}}}'
            )

    def test_request_accepts_audit_read(self):
        try:
            request = parse_request(
                b'{"req_id":"a1","action":"health.audit.read","payload":{}}'
            )
        except protocol.SidecarProtocolError:
            request = None
        self.assertIsNotNone(request)
        self.assertEqual(request.action, "health.audit.read")

    def test_request_accepts_profile_candidate(self):
        request = parse_request(
            json.dumps(
                {
                    "action": ACTION_PROFILE_CANDIDATE,
                    "payload": {
                        "subject": "profile",
                        "sender_id": "owner-1",
                        "candidate": {
                            "evidence_kind": "direct_statement",
                            "source_message_id": "msg-1",
                            "source_utc": "2026-01-02T03:04:05Z",
                            "excerpt": "最近睡眠不佳",
                            "conclusions": [],
                        },
                    },
                }
            ).encode("utf-8")
        )
        self.assertEqual(request.action, ACTION_PROFILE_CANDIDATE)

    def test_request_accepts_daily_review_plan(self):
        request = parse_request(
            json.dumps(
                {
                    "action": protocol.ACTION_DAILY_REVIEW,
                    "payload": {
                        "subject": "profile",
                        "review_utc": "2026-01-02T20:00:00Z",
                        "timezone": "Asia/Shanghai",
                        "plan": {"outcome": "no_action"},
                    },
                }
            ).encode("utf-8")
        )
        self.assertEqual(request.action, protocol.ACTION_DAILY_REVIEW)

    def test_request_accepts_sidecar_owned_daily_review_execution(self):
        request = parse_request(
            json.dumps(
                {
                    "action": protocol.ACTION_DAILY_REVIEW_EXECUTE,
                    "payload": {
                        "subject": "profile",
                        "review_utc": "2026-01-02T20:00:00Z",
                        "timezone": "Asia/Shanghai",
                        "job_authorization": "test-job-authorization",
                    },
                }
            ).encode("utf-8")
        )
        self.assertEqual(request.action, protocol.ACTION_DAILY_REVIEW_EXECUTE)

    def test_request_accepts_dispatch_tick(self):
        request = parse_request(
            json.dumps(
                {
                    "action": protocol.ACTION_DISPATCH_DUE_TASKS,
                    "payload": {
                        "subject": "profile",
                        "now_utc": "2026-01-02T20:00:00Z",
                        "job_authorization": "test-job-authorization",
                    },
                }
            ).encode("utf-8")
        )
        self.assertEqual(request.action, protocol.ACTION_DISPATCH_DUE_TASKS)


class PartnerHealthAdapterApiTests(unittest.TestCase):
    def test_package_exports_partner_adapter(self):
        self.assertTrue(hasattr(sidecar, "PartnerHealthAdapter"))

    def test_adapter_exposes_profile_evidence_seam(self):
        for name in (
            "bind_profile_owner",
            "stage_profile_message",
            "remember_recent_owner_message",
            "record_profile_candidate",
            "read_profile",
            "delete_profile",
            "purge_backups",
            "daily_review_snapshot",
            "run_daily_review",
            "execute_daily_review",
            "dispatch_due_tasks",
        ):
            self.assertTrue(hasattr(sidecar.PartnerHealthAdapter, name), name)


class JobRpcTimeoutTests(unittest.TestCase):
    def test_dispatch_uses_the_bounded_job_timeout_not_the_default_rpc_timeout(self):
        with mock.patch.object(client.socket, "AF_UNIX", object(), create=True):
            sidecar_client = HealthSidecarClient(str(ROOT / "unused-health.sock"))
            with mock.patch.object(sidecar_client, "call", return_value={}) as call:
                sidecar_client.dispatch_due_tasks(
                    "profile", "2026-01-02T20:00:00Z", "job-authorization"
                )

        call.assert_called_once_with(
            protocol.ACTION_DISPATCH_DUE_TASKS,
            {
                "subject": "profile",
                "now_utc": "2026-01-02T20:00:00Z",
                "job_authorization": "job-authorization",
            },
            timeout_seconds=client.DISPATCH_SOCKET_TIMEOUT_SECONDS,
        )


class HealthSidecarReadinessApiTests(unittest.TestCase):
    def test_server_exposes_readiness_event_hook(self):
        self.assertIn("ready_event", inspect.signature(HealthSidecarServer).parameters)


class HealthStewardPortsApiTests(unittest.TestCase):
    def test_controlled_port_bundle_is_public(self):
        for name in (
            "HealthStewardPorts",
            "LLMAdapter",
            "SourceFetchAdapter",
            "ChannelSendAdapter",
            "MemoryProjectionPort",
        ):
            self.assertTrue(hasattr(sidecar, name), name)
        self.assertIn("ports", inspect.signature(server.run_server).parameters)

    def test_controlled_port_bundle_accepts_all_dependencies(self):
        ports = sidecar.HealthStewardPorts(
            clock=FixedClock(dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)),
            key_manager=FixedKeyManager(),
            llm=FixedLLM(),
            source_fetch=FixedSourceFetch(),
            channel_send=RecordingChannelSend(),
        )
        self.assertEqual(ports.llm.complete("prompt", {}), "controlled")
        self.assertEqual(ports.llm.complete_fresh("prompt", {}, "session-1"), "controlled")
        self.assertEqual(ports.source_fetch.fetch("https://example.test"), {})
        ports.channel_send.send("owner", "message")
        self.assertTrue(ports.channel_send.send_once("owner", "message-2", "delivery-1"))
        self.assertEqual(
            ports.channel_send.sent,
            [("owner", "message"), ("owner", "message-2")],
        )


def _run_sidecar_process(
    socket_path: str,
    state_path: str,
    key_path: str,
    uid: int,
    ready_event: multiprocessing.synchronize.Event,
    ports: sidecar.HealthStewardPorts,
    message_verifier: HmacInboundMessageVerifier,
) -> None:
    server.run_server(
        socket_path=socket_path,
        state_path=state_path,
        key_path=key_path,
        allowed_uids={uid},
        ready_event=ready_event,
        ports=ports,
        message_verifier=message_verifier,
    )


@unittest.skipIf(not hasattr(socket, "AF_UNIX"), "AF_UNIX not available")
class PartnerHealthAdapterProcessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self._temp_dir = temp
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.socket_path = self.root / "health-sidecar.sock"
        self.ready_event = multiprocessing.Event()
        self.ports = sidecar.HealthStewardPorts(
            clock=FixedClock(dt.datetime(2026, 1, 2, 3, 5, tzinfo=dt.timezone.utc)),
            key_manager=FixedKeyManager(),
            llm=FixedLLM(),
            source_fetch=FixedSourceFetch(),
            channel_send=RecordingChannelSend(),
        )
        self.message_verifier = HmacInboundMessageVerifier(b"i" * 32)
        self.process = multiprocessing.Process(
            target=_run_sidecar_process,
            args=(
                str(self.socket_path),
                str(self.root / "state.sqlite.enc"),
                str(self.root / "sidecar.key"),
                os.getuid(),
                self.ready_event,
                self.ports,
                self.message_verifier,
            ),
            daemon=True,
        )
        self.process.start()
        self.addCleanup(self._stop_process)
        self.assertTrue(self.ready_event.wait(timeout=3), "sidecar process did not become ready")

    def _token(self, subject, sender_id, message_id, message_utc, text, kind):
        return self.message_verifier.sign(
            subject=subject,
            sender_id=sender_id,
            message_id=message_id,
            message_utc=message_utc,
            message_text=text,
            evidence_kind=kind,
        )

    def _owner_token(self, subject, owner_sender_id):
        return self.message_verifier.sign_owner_binding(
            subject=subject, owner_sender_id=owner_sender_id
        )

    def _access_receipt(self, action, actor, target, message_id):
        message_utc = "2026-01-02T03:04:05Z"
        return (
            message_id,
            message_utc,
            self.message_verifier.sign_access_receipt(
                action=action,
                subject="profile",
                actor_sender_id=actor,
                target_sender_id=target,
                message_id=message_id,
                message_utc=message_utc,
            ),
        )

    def _stop_process(self):
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=2)

    def test_adapter_writes_reads_and_observes_content_free_audit(self):
        adapter = sidecar.PartnerHealthAdapter(str(self.socket_path))
        version = adapter.write_state("owner", {"profile_summary_zh": "测试"})
        self.assertEqual(version, 1)
        self.assertEqual(
            adapter.read_state("owner"), {"profile_summary_zh": "测试"}
        )

        events = adapter.read_audit()
        event_names = [str(event["event"]) for event in events]
        self.assertIn("status_set", event_names)
        self.assertIn("status_get", event_names)
        self.assertNotIn("测试", json.dumps(events, ensure_ascii=False))

    def test_adapter_records_profile_and_reads_compact_snapshot(self):
        adapter = sidecar.PartnerHealthAdapter(str(self.socket_path))
        self.assertTrue(
            adapter.bind_profile_owner(
                "profile", "owner-1", self._owner_token("profile", "owner-1")
            )
        )
        self.assertTrue(
            adapter.stage_profile_message(
                "profile",
                "owner-1",
                "msg-1",
                "2026-01-02T03:04:05Z",
                "最近睡眠不佳",
                "direct_statement",
                self._token("profile", "owner-1", "msg-1", "2026-01-02T03:04:05Z", "最近睡眠不佳", "direct_statement"),
            )
        )
        result = adapter.record_profile_candidate(
            "profile",
            "owner-1",
            {
                "evidence_kind": "direct_statement",
                "source_message_id": "msg-1",
                "source_utc": "2026-01-02T03:04:05Z",
                "excerpt": "最近睡眠不佳",
                "conclusions": [
                    {
                        "category": "state",
                        "dedupe_key": "sleep",
                        "text": "最近睡眠不佳",
                        "status": "fact",
                        "priority": 90,
                    }
                ],
            },
        )
        snapshot = adapter.read_profile(
            "profile", "owner-1",
            *self._access_receipt("health.profile.read", "owner-1", "owner-1", "adapter-read-1"),
        )
        self.assertEqual(snapshot["current_version_id"], result["version_id"])
        self.assertEqual(snapshot["profile_summary_zh"], "最近睡眠不佳")
        self.assertEqual(snapshot["evidence"][0]["source_message_id"], "msg-1")

    def test_adapter_rejects_non_owner_and_non_personal_candidates(self):
        adapter = sidecar.PartnerHealthAdapter(str(self.socket_path))
        adapter.bind_profile_owner(
            "profile", "owner-1", self._owner_token("profile", "owner-1")
        )
        with self.assertRaisesRegex(sidecar.PartnerHealthAdapterError, "profile-message-not-eligible"):
            adapter.stage_profile_message(
                "profile",
                "owner-1",
                "msg-chat",
                "2026-01-02T03:04:05Z",
                "ordinary chat",
                "ordinary_chat",
                "invalid-token",
                )
        with self.assertRaisesRegex(sidecar.PartnerHealthAdapterError, "non-owner-message"):
            adapter.stage_profile_message(
                "profile",
                "other",
                "msg-other",
                "2026-01-02T03:04:05Z",
                "我不是主人",
                "direct_statement",
                self._token("profile", "other", "msg-other", "2026-01-02T03:04:05Z", "我不是主人", "direct_statement"),
            )
        with self.assertRaisesRegex(sidecar.PartnerHealthAdapterError, "not-personal-evidence"):
            adapter.record_profile_candidate(
                "profile",
                "owner-1",
                {
                    "evidence_kind": "ordinary_chat",
                    "source_message_id": "msg-chat",
                    "source_utc": "2026-01-02T03:04:05Z",
                    "excerpt": "普通聊天",
                    "conclusions": [],
                },
            )
        snapshot = adapter.read_profile(
            "profile", "owner-1",
            *self._access_receipt("health.profile.read", "owner-1", "owner-1", "adapter-read-2"),
        )
        self.assertEqual(snapshot["evidence"], [])

        with self.assertRaisesRegex(sidecar.PartnerHealthAdapterError, "profile-state-protected"):
            adapter.write_state("profile", {"profile_summary_zh": "bypass"})
        with self.assertRaisesRegex(sidecar.PartnerHealthAdapterError, "profile-state-protected"):
            adapter.read_state("profile")
        with self.assertRaisesRegex(sidecar.PartnerHealthAdapterError, "profile-state-protected"):
            adapter.write_state(
                "unbound",
                {
                    "profile_schema_version": 1,
                    "owner_sender_id": "forged-owner",
                    "evidence": [],
                    "profile_versions": [],
                    "current_version_id": None,
                    "profile_summary_zh": "forged",
                    "conclusions": [],
                },
            )

    def test_adapter_records_measurement_and_relayed_clinician_evidence(self):
        adapter = sidecar.PartnerHealthAdapter(str(self.socket_path))
        adapter.bind_profile_owner(
            "profile", "owner-1", self._owner_token("profile", "owner-1")
        )
        adapter.stage_profile_message(
            "profile", "owner-1", "msg-m", "2026-01-02T03:04:05Z", "体温 37.5 °C", "measurement",
            self._token("profile", "owner-1", "msg-m", "2026-01-02T03:04:05Z", "体温 37.5 °C", "measurement"),
        )
        adapter.record_profile_candidate(
            "profile",
            "owner-1",
            {
                "evidence_kind": "measurement",
                "source_message_id": "msg-m",
                "source_utc": "2026-01-02T03:04:05Z",
                "excerpt": "体温 37.5 °C",
                "measurement": {
                    "type": "body_temperature",
                    "value": 37.5,
                    "unit": "°C",
                    "observed_utc": "2026-01-02T02:55:00Z",
                },
                "conclusions": [],
            },
        )
        adapter.stage_profile_message(
            "profile", "owner-1", "msg-c", "2026-01-02T04:04:05Z", "我转述医生建议先观察", "owner_relayed_clinician",
            self._token("profile", "owner-1", "msg-c", "2026-01-02T04:04:05Z", "我转述医生建议先观察", "owner_relayed_clinician"),
        )
        adapter.record_profile_candidate(
            "profile",
            "owner-1",
            {
                "evidence_kind": "owner_relayed_clinician",
                "source_message_id": "msg-c",
                "source_utc": "2026-01-02T04:04:05Z",
                "excerpt": "我转述医生建议先观察",
                "conclusions": [],
            },
        )
        evidence = adapter.read_profile(
            "profile", "owner-1",
            *self._access_receipt("health.profile.read", "owner-1", "owner-1", "adapter-read-3"),
        )["evidence"]
        self.assertEqual(evidence[0]["measurement"]["unit"], "°C")
        self.assertTrue(evidence[1]["owner_relayed"])

    def test_adapter_fails_closed_on_summary_overflow(self):
        adapter = sidecar.PartnerHealthAdapter(str(self.socket_path))
        adapter.bind_profile_owner(
            "profile", "owner-1", self._owner_token("profile", "owner-1")
        )
        long_text = "重要状态" * 45
        adapter.stage_profile_message(
            "profile", "owner-1", "msg-overflow", "2026-01-02T03:04:05Z", "需要记录很多情况", "direct_statement",
            self._token("profile", "owner-1", "msg-overflow", "2026-01-02T03:04:05Z", "需要记录很多情况", "direct_statement"),
        )
        with self.assertRaisesRegex(sidecar.PartnerHealthAdapterError, "summary_overflow"):
            adapter.record_profile_candidate(
                "profile",
                "owner-1",
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "msg-overflow",
                    "source_utc": "2026-01-02T03:04:05Z",
                    "excerpt": "需要记录很多情况",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "critical-a",
                            "text": long_text,
                            "status": "fact",
                            "priority": 100,
                            "task_dependency": True,
                        },
                        {
                            "category": "state",
                            "dedupe_key": "critical-b",
                            "text": long_text,
                            "status": "fact",
                            "priority": 99,
                            "task_dependency": True,
                        },
                    ],
                },
            )
        self.assertEqual(
            adapter.read_profile(
                "profile", "owner-1",
                *self._access_receipt("health.profile.read", "owner-1", "owner-1", "adapter-read-4"),
            )["evidence"],
            [],
        )


def _crash_during_persist(
    root: str,
    state_path: str,
    key_path: str,
    ready: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
) -> None:
    tempfile.tempdir = root
    sidecar_store = HealthSidecarStore(state_path, key_path)

    def hold_persist(_connection):
        ready.set()
        release.wait()

    sidecar_store._persist_state = hold_persist
    sidecar_store.write_subject_status("owner", {"profile_summary_zh": "测试"})


class HealthSidecarCrashSafetyTests(unittest.TestCase):
    def test_terminated_persist_does_not_leave_plaintext_sqlite(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        ready = multiprocessing.Event()
        release = multiprocessing.Event()
        process = multiprocessing.Process(
            target=_crash_during_persist,
            args=(
                str(root),
                str(root / "state.sqlite.enc"),
                str(root / "sidecar.key"),
                ready,
                release,
            ),
            daemon=True,
        )
        process.start()
        self.assertTrue(ready.wait(timeout=3), "persist hook was not reached")
        process.terminate()
        process.join(timeout=2)
        self.assertFalse(list(root.glob("*.sqlite")))


class FixedClock:
    def __init__(self, now: dt.datetime):
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class FixedKeyManager:
    def __init__(self):
        self.record_calls = 0

    def load_or_create_master_key(self, _key_path: Path) -> bytes:
        return b"m" * 32

    def generate_record_key(self) -> bytes:
        self.record_calls += 1
        return bytes([96 + self.record_calls]) * 32


class FixedInboundVerifier:
    def __init__(self):
        self.message_tokens = []

    def verify_owner_binding(self, *, subject, owner_sender_id, token):
        return token == "owner-token" and subject == "profile" and owner_sender_id == "owner-1"

    def verify(
        self,
        *,
        subject,
        sender_id,
        message_id,
        message_utc,
        message_text,
        evidence_kind,
        token,
    ):
        self.message_tokens.append(token)
        return token == "message-token"


class FixedLLM:
    def complete(self, _prompt: str, _context: dict[str, object]) -> str:
        return "controlled"

    def complete_fresh(
        self, _prompt: str, _context: dict[str, object], _session_id: str
    ) -> str:
        return "controlled"


class FixedSourceFetch:
    def fetch(self, _url: str) -> dict[str, object]:
        return {}


class RecordingChannelSend:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, recipient: str, message: str) -> None:
        self.sent.append((recipient, message))

    def send_once(self, recipient: str, message: str, _delivery_key: str) -> bool:
        self.send(recipient, message)
        return True


@unittest.skipIf(not hasattr(socket, "AF_UNIX"), "AF_UNIX not available")
class HealthSidecarServerTests(unittest.TestCase):
    def _run_server(
        self,
        socket_path: Path,
        store_path: Path,
        key_path: Path,
        ready_event: threading.Event,
    ):
        self.server = HealthSidecarServer(
            socket_path=socket_path,
            store=HealthSidecarStore(store_path, key_path),
            allowed_uids=_parse_uids(str(os.getuid())),
            ready_event=ready_event,
        )
        self.server.run_forever(listen_backlog=2)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self._temp_dir = temp
        self.addCleanup(temp.cleanup)

        self.root = Path(temp.name)
        self.socket_path = self.root / "health-sidecar.sock"
        self.state_path = self.root / "state.sqlite.enc"
        self.key_path = self.root / "sidecar.key"
        self.server = None
        self.ready_event = threading.Event()

        self.thread = threading.Thread(
            target=self._run_server,
            args=(self.socket_path, self.state_path, self.key_path, self.ready_event),
            daemon=True,
        )
        self.thread.start()
        self.assertTrue(self.ready_event.wait(timeout=3), "server did not become ready")

    def _send_raw(self, payload: bytes) -> dict[str, object]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect(str(self.socket_path))
            frame = len(payload).to_bytes(4, "big") + payload
            sock.sendall(frame)

            header = b""
            while len(header) < 4:
                chunk = sock.recv(4 - len(header))
                if not chunk:
                    break
                header += chunk
            if len(header) != 4:
                raise AssertionError("incomplete response header")

            body_len = int.from_bytes(header, "big")
            body = b""
            while len(body) < body_len:
                chunk = sock.recv(body_len - len(body))
                if not chunk:
                    break
                body += chunk
            if len(body) != body_len:
                raise AssertionError("incomplete response body")
            return json.loads(body.decode("utf-8"))

    def _read_audit_events(self) -> list[dict[str, object]]:
        lines = []
        if not self.server.store.audit_path.exists():
            return lines
        for raw in self.server.store.audit_path.read_text(encoding="utf-8").splitlines():
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
        return lines

    def tearDown(self):
        if self.server is not None:
            self.server.stop()
        self.thread.join(timeout=2)

    def test_ping_get_set_status(self):
        self.assertTrue(self.socket_path.exists())
        sidecar_client = HealthSidecarClient(str(self.socket_path), timeout_seconds=1.0)
        ping = sidecar_client.ping()
        self.assertTrue(ping["ok"])
        self.assertEqual(ping["action"], ACTION_PING)

        set_result = sidecar_client.set_status(
            "owner", {"profile_summary_zh": "测试"}
        )
        self.assertTrue(set_result["ok"])
        self.assertEqual(set_result["action"], ACTION_STATUS_SET)

        get_result = sidecar_client.get_status("owner")
        self.assertTrue(get_result["ok"])
        self.assertEqual(get_result["action"], ACTION_STATUS_GET)
        self.assertTrue(get_result["data"]["found"])
        self.assertEqual(
            get_result["data"]["status"]["profile_summary_zh"], "测试"
        )

    def test_unauthorized_client_is_rejected(self):
        sidecar_client = HealthSidecarClient(str(self.socket_path), timeout_seconds=1.0)
        # restart server with uid rule that does not include current uid
        self.server.stop()
        self.thread.join(timeout=2)

        unauthorized_ready = threading.Event()
        self.server = HealthSidecarServer(
            socket_path=self.socket_path,
            store=HealthSidecarStore(self.state_path, self.key_path),
            allowed_uids=_parse_uids("999999"),
            ready_event=unauthorized_ready,
        )
        self.thread = threading.Thread(
            target=self.server.run_forever, args=(), kwargs={"listen_backlog": 2}, daemon=True
        )
        self.thread.start()
        self.assertTrue(unauthorized_ready.wait(timeout=3), "server did not become ready")

        ping = sidecar_client.ping()
        self.assertFalse(ping["ok"])
        self.assertEqual(ping["error"]["code"], "unauthorized_client")

    def test_protocol_error_is_logged(self):
        self._send_raw(b'{"action":"health.invalid","payload":{}}')
        protocol_events = [
            e for e in self._read_audit_events() if e.get("event") == "protocol_error"
        ]
        self.assertTrue(protocol_events)
        event = protocol_events[-1]
        details = event["details"]
        self.assertIsInstance(details, dict)
        self.assertIn("peer_uid", details)
        self.assertIn("error", details)
        self.assertIn("unsupported-action", str(details["error"]))

    def test_backup_is_encrypted_bytes(self):
        sidecar_client = HealthSidecarClient(str(self.socket_path), timeout_seconds=1.0)
        sidecar_client.set_status("owner", {"profile_summary_zh": "首条"})
        sidecar_client.set_status("owner", {"profile_summary_zh": "测试"})

        backups = sorted(self.server.store.backup_dir.glob(f"{self.server.store.store_path.name}.*.bak"))
        self.assertTrue(backups)
        backup_blob = backups[0].read_bytes()
        self.assertNotEqual(backup_blob[:16], b"SQLite format 3\0")


class SidecarIdentityConfigurationTests(unittest.TestCase):
    def _argv(self) -> list[str]:
        return [
            "--allowed-uids",
            "1",
            "--memory-projection-path",
            "memory.json",
            "--receipt-public-key-path",
            "receipt-public.key",
            "--expected-owner-sender-id",
            "wx-owner",
        ]

    def test_production_main_requires_one_distinct_preconfigured_viewer(self):
        with self.assertRaisesRegex(
            server.HealthSidecarServerError,
            "expected-viewer-sender-id-required",
        ):
            server.main(self._argv())

        with self.assertRaisesRegex(
            server.HealthSidecarServerError,
            "viewer-must-not-be-owner",
        ):
            server.main(
                self._argv()
                + ["--expected-viewer-sender-id", "wx-owner"]
            )


if __name__ == "__main__":
    unittest.main()

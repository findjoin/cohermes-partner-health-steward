import datetime as dt
import json
import os
import shutil
import socket
import tempfile
import threading
import unittest
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from sidecar import (
    FileMemoryProjection,
    HealthSidecarServer,
    HmacInboundMessageVerifier,
    NoopMemoryProjection,
    PartnerHealthAdapter,
)
from sidecar.store import HealthSidecarStore, StoreError
from sidecar.weixin_delivery import (
    ChannelSendUncertainError,
    DeliveryResult,
    WeixinHealthChannel,
)
from sidecar.ports import build_health_memory_projection
from legacy_state_fixture import create_legacy_profile_fixture


class FixedClock:
    def __init__(self, now: dt.datetime):
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class MemoryProjectionFake:
    def __init__(self):
        self.removed = []

    def remove_health_projection(self, subject: str) -> bool:
        self.removed.append(subject)
        return True


class ProfileDeletionTests(unittest.TestCase):
    SUBJECT = "profile"
    OWNER = "owner-1"
    DELETE_REQUEST_ACTION = "health.profile.delete.request"
    DELETE_CONFIRM_ACTION = "health.profile.delete.confirm"

    def _store(self, root: Path, clock: FixedClock | None = None) -> tuple[HealthSidecarStore, FixedClock]:
        clock = clock or FixedClock(dt.datetime(2026, 1, 2, 0, 5, tzinfo=dt.timezone.utc))
        store = HealthSidecarStore(
            root / "state.sqlite.enc",
            root / "sidecar.key",
            clock=clock,
        )
        token = store.message_verifier.sign_owner_binding(
            subject=self.SUBJECT,
            owner_sender_id=self.OWNER,
        )
        self.assertTrue(store.bind_profile_owner(self.SUBJECT, self.OWNER, token))
        return store, clock

    def _receipt(
        self,
        store: HealthSidecarStore,
        action: str,
        message_id: str,
        *,
        message_utc: str = "2026-01-02T00:04:00Z",
    ):
        return (
            message_id,
            message_utc,
            store.message_verifier.sign_access_receipt(
                action=action,
                subject=self.SUBJECT,
                actor_sender_id=self.OWNER,
                target_sender_id=self.OWNER,
                message_id=message_id,
                message_utc=message_utc,
            ),
        )

    def _request_deletion(
        self,
        store: HealthSidecarStore,
        request_message_id: str,
        *,
        request_utc: str = "2026-01-02T00:04:00Z",
    ) -> str:
        store.request_profile_deletion(
            self.SUBJECT,
            self.OWNER,
            *self._receipt(
                store,
                self.DELETE_REQUEST_ACTION,
                request_message_id,
                message_utc=request_utc,
            ),
        )
        return request_message_id

    def _confirm_deletion(
        self,
        store: HealthSidecarStore,
        request_message_id: str,
        confirmation_message_id: str,
        memory_projection,
        *,
        confirmation_utc: str = "2026-01-02T00:04:01Z",
    ):
        return store.confirm_profile_deletion(
            self.SUBJECT,
            self.OWNER,
            request_message_id,
            *self._receipt(
                store,
                self.DELETE_CONFIRM_ACTION,
                confirmation_message_id,
                message_utc=confirmation_utc,
            ),
            memory_projection=memory_projection,
        )

    def _add_profile_content(self, store: HealthSidecarStore) -> None:
        store.stage_profile_message(
            self.SUBJECT,
            self.OWNER,
            "message-1",
            "2026-01-02T00:04:00Z",
            "最近睡眠不佳",
            "direct_statement",
            store.message_verifier.sign(
                subject=self.SUBJECT,
                sender_id=self.OWNER,
                message_id="message-1",
                message_utc="2026-01-02T00:04:00Z",
                message_text="最近睡眠不佳",
                evidence_kind="direct_statement",
            ),
        )
        store.record_profile_candidate(
            self.SUBJECT,
            self.OWNER,
            {
                "evidence_kind": "direct_statement",
                "source_message_id": "message-1",
                "source_utc": "2026-01-02T00:04:00Z",
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
        store.mutate_subject_status(
            self.SUBJECT,
            lambda current: (
                {
                    **dict(current),
                    "tasks": [{"task_id": "task-1", "status": "pending"}],
                    "reports": [{"report_id": "report-1"}],
                },
                None,
            ),
        )

    def test_owner_delete_clears_profile_key_projection_and_profile_audit(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store, _ = self._store(root_path)
            self._add_profile_content(store)
            store.mutate_source_library_state(
                lambda current: ({**dict(current), "shared_card": "retained"}, None)
            )
            legacy_delivery_details = {
                "actor_role": "weixin-delivery-adapter",
                "action": "weixin.send_once",
                "object_id": "legacy-delivery-before-delete",
                "recipient_id": self.OWNER,
                "result": "sent",
                "reason": "provider-accepted",
            }
            # Pre-Ticket-21 ledger events have no subject field.  This
            # dedicated partner channel must still remove them at deletion.
            store.append_audit_event_once(
                "legacy-delivery-before-delete",
                "weixin_delivery_sent",
                legacy_delivery_details,
            )
            projection = MemoryProjectionFake()
            request_id = self._request_deletion(store, "delete-1-request")
            result = self._confirm_deletion(
                store,
                request_id,
                "delete-1-confirm",
                projection,
            )

            self.assertTrue(result["deleted"])
            self.assertEqual(projection.removed, [self.SUBJECT])
            self.assertIsNone(
                store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            )
            self.assertTrue(store.read_source_library_state())
            self.assertFalse(list(store.profile_key_dir.glob("*.key")))
            events = store.read_audit_events()
            profile_events = [
                event
                for event in events
                if event.get("details", {}).get("subject") == self.SUBJECT
            ]
            self.assertEqual([event["event"] for event in profile_events], ["profile_deleted"])
            self.assertNotIn("睡眠", str(profile_events))
            self.assertNotIn(
                "weixin_delivery_sent", [event["event"] for event in events]
            )
            with self.assertRaisesRegex(
                StoreError, "profile-deleted-delivery-audit-forbidden"
            ):
                store.append_audit_event_once(
                    "late-delivery-after-delete",
                    "weixin_delivery_sent",
                    {**legacy_delivery_details, "subject": self.SUBJECT},
                )
            self.assertNotIn(
                "weixin_delivery_sent",
                [event["event"] for event in store.read_audit_events()],
            )

    def test_startup_recovers_after_key_destruction_before_record_cleanup(self):
        """A crash after key destruction converges instead of bricking startup."""
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store, clock = self._store(root_path)
            self._add_profile_content(store)
            request_id = self._request_deletion(store, "journal-request")
            original_remove = store._remove_committed_profile_state
            failed_once = {"value": False}

            def fail_after_key(*args, **kwargs):
                if not failed_once["value"]:
                    failed_once["value"] = True
                    raise StoreError("injected-record-cleanup-failure")
                return original_remove(*args, **kwargs)

            with mock.patch.object(
                store,
                "_remove_committed_profile_state",
                side_effect=fail_after_key,
            ):
                with self.assertRaisesRegex(
                    StoreError, "injected-record-cleanup-failure"
                ):
                    self._confirm_deletion(
                        store,
                        request_id,
                        "journal-confirm",
                        MemoryProjectionFake(),
                    )

            self.assertFalse(list(store.profile_key_dir.glob("*.key")))
            with self.assertRaisesRegex(StoreError, "profile-key-destroyed"):
                store.read_subject_status(self.SUBJECT, _allow_profile_state=True)

            recovered = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "sidecar.key",
                clock=clock,
                message_verifier=store.message_verifier,
                expected_owner_sender_id=self.OWNER,
            )
            self.assertIsNone(
                recovered.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            )
            status = recovered.profile_deletion_status(
                self.SUBJECT,
                self.OWNER,
                *self._receipt(
                    recovered,
                    self.DELETE_CONFIRM_ACTION,
                    "journal-recovery-status",
                    message_utc="2026-01-02T00:04:02Z",
                ),
            )
            self.assertTrue(status["deleted"])
            self.assertFalse(status["deletion_pending"])
            profile_events = [
                event
                for event in recovered.read_audit_events()
                if event.get("details", {}).get("subject") == self.SUBJECT
            ]
            self.assertEqual([event["event"] for event in profile_events], ["profile_deleted"])

    def test_confirmed_delete_revokes_recording_consent_before_future_ingest(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            legacy_store, clock = self._store(root_path)
            self._add_profile_content(legacy_store)
            store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "sidecar.key",
                clock=clock,
                message_verifier=legacy_store.message_verifier,
                expected_owner_sender_id=self.OWNER,
            )
            store.enable_health_recording(
                self.SUBJECT,
                self.OWNER,
                *self._receipt(
                    store,
                    "health.recording.enable",
                    "recording-enable-before-delete",
                ),
            )
            self.assertTrue(store.health_recording_enabled(self.SUBJECT, self.OWNER))

            request_id = self._request_deletion(store, "recording-delete-request")
            result = self._confirm_deletion(
                store,
                request_id,
                "recording-delete-confirm",
                MemoryProjectionFake(),
            )

            self.assertTrue(result["deleted"])
            self.assertFalse(store.health_recording_enabled(self.SUBJECT, self.OWNER))
            self.assertEqual(
                store.health_recording_status(self.SUBJECT, self.OWNER), "not_enabled"
            )
            with self.assertRaisesRegex(StoreError, "recording-not-enabled"):
                store.begin_recording_attempt(self.SUBJECT, self.OWNER)

    def test_delete_serializes_the_last_delivery_audit_with_its_audit_rewrite(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            self._add_profile_content(store)
            request_id = self._request_deletion(store, "audit-race-request")
            audit_entered = threading.Event()
            release_audit = threading.Event()
            delete_started = threading.Event()
            delete_finished = threading.Event()
            errors: list[BaseException] = []
            original_read = store._read_audit_events_unlocked

            def blocking_read(limit=100):
                if threading.current_thread().name == "late-delivery-audit":
                    audit_entered.set()
                    if not release_audit.wait(timeout=2):
                        raise RuntimeError("test-audit-release-timeout")
                return original_read(limit)

            store._read_audit_events_unlocked = blocking_read
            delivery_details = {
                "actor_role": "weixin-delivery-adapter",
                "action": "weixin.send_once",
                "object_id": "race-delivery",
                "recipient_id": self.OWNER,
                "result": "sent",
                "reason": "provider-accepted",
                "subject": self.SUBJECT,
            }

            def append_late_delivery_audit() -> None:
                try:
                    store.append_audit_event_once(
                        "race-delivery-audit",
                        "weixin_delivery_sent",
                        delivery_details,
                    )
                except BaseException as exc:  # captured for the assertion below
                    errors.append(exc)

            def confirm_delete() -> None:
                try:
                    delete_started.set()
                    self._confirm_deletion(
                        store,
                        request_id,
                        "audit-race-confirm",
                        MemoryProjectionFake(),
                    )
                except BaseException as exc:  # captured for the assertion below
                    errors.append(exc)
                finally:
                    delete_finished.set()

            audit_thread = threading.Thread(
                target=append_late_delivery_audit,
                name="late-delivery-audit",
            )
            audit_thread.start()
            self.assertTrue(audit_entered.wait(timeout=1))
            delete_thread = threading.Thread(target=confirm_delete)
            delete_thread.start()
            self.assertTrue(delete_started.wait(timeout=1))
            self.assertFalse(delete_finished.wait(timeout=0.05))
            release_audit.set()
            audit_thread.join(timeout=2)
            delete_thread.join(timeout=2)
            store._read_audit_events_unlocked = original_read

            self.assertFalse(audit_thread.is_alive())
            self.assertFalse(delete_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertIsNone(
                store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            )
            self.assertNotIn(
                "weixin_delivery_sent",
                [event["event"] for event in store.read_audit_events(limit=None)],
            )

    def test_restart_does_not_restore_a_pending_delivery_audit_after_profile_deletion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store, clock = self._store(root_path)
            self._add_profile_content(store)

            class AcceptedTransport:
                runtime_version = "0.20.0"

                def send_text(self, _recipient, _message, client_id):
                    return DeliveryResult.accepted(client_id)

            class FailingAuditSink:
                def append_audit_event_once(self, *_args, **_kwargs):
                    raise RuntimeError("controlled-audit-outage")

            ledger_path = root_path / "delivery.sqlite3"
            before_delete_channel = WeixinHealthChannel(
                ledger_path,
                AcceptedTransport(),
                accepted_hermes_version="0.20.0",
                clock=clock,
                audit_sink=FailingAuditSink(),
                profile_subject=self.SUBJECT,
            )
            with self.assertRaisesRegex(
                ChannelSendUncertainError, "channel-send-uncertain"
            ):
                before_delete_channel.send_once(
                    self.OWNER,
                    "content is never persisted by the delivery ledger",
                    "restart-audit-race",
                )
            self.assertTrue(
                before_delete_channel.prepare_profile_deletion("delete-terminal")
            )
            request_id = self._request_deletion(store, "restart-audit-request")
            self.assertTrue(
                self._confirm_deletion(
                    store,
                    request_id,
                    "restart-audit-confirm",
                    MemoryProjectionFake(),
                )["deleted"]
            )

            # Simulates a process restart in the narrow window after sidecar
            # destruction but before the local delivery ledger has purged its
            # pending audit.  The store rejects the late profile-bound audit.
            recovered_channel = WeixinHealthChannel(
                ledger_path,
                AcceptedTransport(),
                accepted_hermes_version="0.20.0",
                clock=clock,
                audit_sink=store,
                profile_subject=self.SUBJECT,
            )
            self.assertTrue(recovered_channel.complete_profile_deletion())
            self.assertNotIn(
                "weixin_delivery_sent",
                [event["event"] for event in store.read_audit_events(limit=None)],
            )

    def test_delete_serializes_against_recent_owner_message_ingest(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            started = threading.Event()
            release = threading.Event()
            recent_done = threading.Event()
            errors = []

            class BlockingProjection:
                def remove_health_projection(self, subject: str) -> bool:
                    started.set()
                    release.wait(timeout=3)
                    return True

            recent_token = store.message_verifier.sign(
                subject=self.SUBJECT,
                sender_id=self.OWNER,
                message_id="chat-after-delete",
                message_utc="2026-01-02T00:04:30Z",
                message_text="这条消息不能回写",
                evidence_kind="ordinary_chat",
            )

            def delete_worker():
                try:
                    self._confirm_deletion(
                        store,
                        request_id,
                        "delete-race-confirm",
                        BlockingProjection(),
                    )
                except Exception as exc:
                    errors.append(exc)

            def recent_worker():
                try:
                    store.remember_recent_owner_message(
                        self.SUBJECT,
                        self.OWNER,
                        "chat-after-delete",
                        "2026-01-02T00:04:30Z",
                        "这条消息不能回写",
                        "ordinary_chat",
                        recent_token,
                    )
                except Exception as exc:
                    errors.append(exc)
                finally:
                    recent_done.set()

            request_id = self._request_deletion(store, "delete-race-request")
            delete_thread = threading.Thread(target=delete_worker)
            delete_thread.start()
            self.assertTrue(started.wait(timeout=3))
            recent_thread = threading.Thread(target=recent_worker)
            recent_thread.start()
            self.assertFalse(recent_done.wait(timeout=0.1))
            release.set()
            delete_thread.join(timeout=3)
            recent_thread.join(timeout=3)
            self.assertFalse(
                [error for error in errors if not isinstance(error, StoreError)]
            )
            self.assertTrue(any(isinstance(error, StoreError) for error in errors))
            self.assertFalse(store.recent_profile_messages(self.SUBJECT, self.OWNER))

    def test_delete_serializes_against_profile_message_staging(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            started = threading.Event()
            release = threading.Event()
            stage_done = threading.Event()
            errors = []

            class BlockingProjection:
                def remove_health_projection(self, _subject: str) -> bool:
                    started.set()
                    release.wait(timeout=3)
                    return True

            stage_token = store.message_verifier.sign(
                subject=self.SUBJECT,
                sender_id=self.OWNER,
                message_id="staged-after-delete",
                message_utc="2026-01-02T00:04:30Z",
                message_text="不能重新暂存",
                evidence_kind="direct_statement",
            )

            def delete_worker():
                try:
                    self._confirm_deletion(
                        store,
                        request_id,
                        "delete-stage-race-confirm",
                        BlockingProjection(),
                    )
                except Exception as exc:
                    errors.append(exc)

            def stage_worker():
                try:
                    store.stage_profile_message(
                        self.SUBJECT,
                        self.OWNER,
                        "staged-after-delete",
                        "2026-01-02T00:04:30Z",
                        "不能重新暂存",
                        "direct_statement",
                        stage_token,
                    )
                except Exception as exc:
                    errors.append(exc)
                finally:
                    stage_done.set()

            request_id = self._request_deletion(store, "delete-stage-race-request")
            delete_thread = threading.Thread(target=delete_worker)
            delete_thread.start()
            self.assertTrue(started.wait(timeout=3))
            stage_thread = threading.Thread(target=stage_worker)
            stage_thread.start()
            self.assertFalse(stage_done.wait(timeout=0.1))
            release.set()
            delete_thread.join(timeout=3)
            stage_thread.join(timeout=3)
            self.assertFalse(
                [error for error in errors if not isinstance(error, StoreError)]
            )
            self.assertTrue(any(isinstance(error, StoreError) for error in errors))
            self.assertFalse(store.recent_profile_messages(self.SUBJECT, self.OWNER))

    def test_deleted_profile_backup_is_undecryptable_and_purges_on_day_30(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store, clock = self._store(root_path)
            self._add_profile_content(store)
            backups = sorted(store.backup_dir.glob("*.bak"))
            self.assertTrue(backups)
            old_backup = backups[-1]
            backup_copy = root_path / "restored.sqlite.enc"
            shutil.copy2(old_backup, backup_copy)

            request_id = self._request_deletion(store, "delete-2-request")
            deleted = self._confirm_deletion(
                store,
                request_id,
                "delete-2-confirm",
                MemoryProjectionFake(),
            )
            self.assertTrue(deleted["key_destroyed"])
            restored = HealthSidecarStore(
                backup_copy,
                root_path / "sidecar.key",
                clock=clock,
            )
            with self.assertRaisesRegex(StoreError, "profile-key-destroyed"):
                restored.read_subject_status(self.SUBJECT, _allow_profile_state=True)

            clock.now = dt.datetime(2026, 1, 31, 0, 5, tzinfo=dt.timezone.utc)
            self.assertEqual(store.purge_expired_backups(), {"deleted": 0, "failed": 0})
            clock.now = dt.datetime(2026, 2, 1, 0, 5, tzinfo=dt.timezone.utc)
            result = store.purge_expired_backups()
            self.assertGreaterEqual(result["deleted"], 1)
            self.assertFalse(old_backup.exists())

    def test_day_30_purge_also_removes_pre_restore_backup(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            pre_restore = (
                store.backup_dir / "pre-restore-20260101T000000000000Z.bak"
            )
            pre_restore.write_bytes(b"encrypted-restore-snapshot")
            clock.now = dt.datetime(2026, 2, 1, 0, 0, tzinfo=dt.timezone.utc)

            result = store.purge_expired_backups()

            self.assertEqual(result["deleted"], 1)
            self.assertFalse(pre_restore.exists())

    def test_legacy_master_profile_and_backup_are_rekeyed_before_delete(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store, clock = self._store(root_path)
            self._add_profile_content(store)
            profile_status = dict(
                store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            )
            legacy_backup = create_legacy_profile_fixture(
                store.store_path,
                store.key_path,
                root_path / "backups",
                self.SUBJECT,
                profile_status,
            )
            for key_file in (root_path / "profile-keys").glob("*.key"):
                key_file.unlink()

            migrated = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "sidecar.key",
                clock=clock,
            )
            self.assertIn("profile_schema_version", migrated.read_subject_status(
                self.SUBJECT, _allow_profile_state=True
            ))

            backup_copy = root_path / "legacy-backup-copy.sqlite.enc"
            shutil.copy2(legacy_backup, backup_copy)
            request_id = self._request_deletion(migrated, "legacy-delete-request")
            result = self._confirm_deletion(
                migrated,
                request_id,
                "legacy-delete-confirm",
                MemoryProjectionFake(),
            )
            self.assertTrue(result["key_destroyed"])
            restored = HealthSidecarStore(
                backup_copy, root_path / "sidecar.key", clock=clock
            )
            with self.assertRaisesRegex(StoreError, "profile-key-destroyed"):
                restored.read_subject_status(self.SUBJECT, _allow_profile_state=True)

    def test_delete_fails_closed_without_real_memory_projection(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            self._add_profile_content(store)
            request_id = self._request_deletion(store, "no-memory-request")
            with self.assertRaisesRegex(StoreError, "memory-projection-not-removed"):
                self._confirm_deletion(
                    store,
                    request_id,
                    "no-memory-confirm",
                    NoopMemoryProjection(),
                )
            self.assertIsNotNone(
                store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            )

    def test_delete_request_alone_preserves_profile_key_and_projection(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            self._add_profile_content(store)
            projection = MemoryProjectionFake()

            self._request_deletion(store, "delete-request-only")

            self.assertIsNotNone(
                store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            )
            self.assertTrue(list(store.profile_key_dir.glob("*.key")))
            self.assertEqual(projection.removed, [])
            events = store.read_audit_events()
            self.assertNotIn(
                "profile_deleted", [event.get("event") for event in events]
            )

    def test_deletion_status_requires_a_current_owner_confirm_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            request_id = self._request_deletion(store, "status-request")
            with self.assertRaisesRegex(StoreError, "delete-status-owner-mismatch"):
                store.profile_deletion_status(
                    self.SUBJECT,
                    "untrusted-socket-peer",
                    "status-untrusted",
                    "2026-01-02T00:04:01Z",
                    "forged-token",
                )
            status = store.profile_deletion_status(
                self.SUBJECT,
                self.OWNER,
                *self._receipt(
                    store,
                    self.DELETE_CONFIRM_ACTION,
                    "status-owner",
                    message_utc="2026-01-02T00:04:01Z",
                ),
            )
            self.assertFalse(status["deleted"])
            self.assertTrue(status["deletion_pending"])
            self.assertEqual(status["request_message_id"], request_id)

    def test_expired_confirmation_does_not_remove_memory_projection(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_profile_content(store)
            projection = MemoryProjectionFake()
            request_id = self._request_deletion(store, "expired-request")

            clock.now = dt.datetime(2026, 1, 2, 0, 15, 1, tzinfo=dt.timezone.utc)
            with self.assertRaises(StoreError):
                self._confirm_deletion(
                    store,
                    request_id,
                    "expired-confirm",
                    projection,
                    confirmation_utc="2026-01-02T00:15:01Z",
                )
            self.assertEqual(projection.removed, [])
            self.assertIsNotNone(
                store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            )

    def test_confirmation_window_starts_at_request_receipt_time(self):
        with tempfile.TemporaryDirectory() as root:
            store, clock = self._store(Path(root))
            self._add_profile_content(store)
            projection = MemoryProjectionFake()

            # The request is still fresh to the sidecar at 00:13:59, but its
            # signed event happened at 00:04:00. Confirming at 00:14:01 must
            # not get a new ten-minute window from server receipt time.
            clock.now = dt.datetime(2026, 1, 2, 0, 13, 59, tzinfo=dt.timezone.utc)
            request_id = self._request_deletion(
                store,
                "late-request",
                request_utc="2026-01-02T00:04:00Z",
            )
            clock.now = dt.datetime(2026, 1, 2, 0, 14, 1, tzinfo=dt.timezone.utc)
            with self.assertRaises(StoreError):
                self._confirm_deletion(
                    store,
                    request_id,
                    "late-request-confirm",
                    projection,
                    confirmation_utc="2026-01-02T00:14:01Z",
                )

            self.assertEqual(projection.removed, [])
            self.assertIsNotNone(
                store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            )

    def test_confirmation_receipt_must_be_strictly_later_than_request_receipt(self):
        for label, confirmation_utc in (
            ("same", "2026-01-02T00:04:00Z"),
            ("earlier", "2026-01-02T00:03:59Z"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as root:
                store, _ = self._store(Path(root))
                self._add_profile_content(store)
                projection = MemoryProjectionFake()
                request_id = self._request_deletion(
                    store,
                    f"{label}-time-request",
                )

                with self.assertRaises(StoreError):
                    self._confirm_deletion(
                        store,
                        request_id,
                        f"{label}-time-confirm",
                        projection,
                        confirmation_utc=confirmation_utc,
                    )

                self.assertEqual(projection.removed, [])
                self.assertIsNotNone(
                    store.read_subject_status(
                        self.SUBJECT, _allow_profile_state=True
                    )
                )

    def test_confirmation_rejects_replay_wrong_pending_and_nonconfirm_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._store(Path(root))
            self._add_profile_content(store)
            projection = MemoryProjectionFake()
            request_id = self._request_deletion(store, "delete-confirm-request")

            with self.assertRaises(StoreError):
                store.confirm_profile_deletion(
                    self.SUBJECT,
                    self.OWNER,
                    request_id,
                    *self._receipt(
                        store,
                        self.DELETE_REQUEST_ACTION,
                        request_id,
                    ),
                    memory_projection=projection,
                )
            with self.assertRaises(StoreError):
                self._confirm_deletion(
                    store,
                    "different-delete-request",
                    "wrong-pending-confirm",
                    projection,
                )

            receipt = self._receipt(
                store,
                self.DELETE_CONFIRM_ACTION,
                "replayed-confirm",
            )
            store.consume_access_receipt(self.SUBJECT, receipt[0], receipt[1])
            with self.assertRaises(StoreError):
                store.confirm_profile_deletion(
                    self.SUBJECT,
                    self.OWNER,
                    request_id,
                    *receipt,
                    memory_projection=projection,
                )
            self.assertEqual(projection.removed, [])
            self.assertIsNotNone(
                store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
            )

    def test_file_memory_projection_removes_only_subject_entry(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "hermes-memory.json"
            path.write_text(
                json.dumps(
                    {"profile": {"pointer": "health-sidecar"}, "other": "keep"}
                ),
                encoding="utf-8",
            )
            projection = FileMemoryProjection(path)
            self.assertTrue(projection.remove_health_projection("profile"))
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), {"other": "keep"}
            )
            self.assertFalse(projection.remove_health_projection("profile"))
            self.assertFalse(
                FileMemoryProjection(Path(root) / "missing.json")
                .remove_health_projection("profile")
            )

    def test_file_memory_projection_contains_only_pointer_and_preferences(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "hermes-memory.json"
            projection = build_health_memory_projection(
                self.SUBJECT,
                {
                    "profile_summary_zh": "must-not-project",
                    "evidence": [{"excerpt": "must-not-project"}],
                    "conclusions": [
                        {
                            "category": "state",
                            "text": "must-not-project",
                            "status": "fact",
                            "active": True,
                        },
                        {
                            "category": "interaction_preference",
                            "text": "prefer concise replies",
                            "status": "fact",
                            "active": True,
                            "valid_until_utc": "2026-03-01T00:00:00+00:00",
                        },
                    ],
                    "proactive_contact": {"paused": False},
                },
                dt.datetime(2026, 2, 1, tzinfo=dt.timezone.utc),
            )
            bridge = FileMemoryProjection(path)
            self.assertTrue(bridge.replace_health_projection(self.SUBJECT, projection))
            document = json.loads(path.read_text(encoding="utf-8"))
            serialized = json.dumps(document)
            self.assertEqual(
                document[self.SUBJECT]["archive_pointer"],
                "health-sidecar://profile/profile",
            )
            self.assertEqual(
                document[self.SUBJECT]["interaction_preferences"],
                ["prefer concise replies"],
            )
            self.assertNotIn("must-not-project", serialized)

    def test_file_memory_projection_fails_closed_on_permission_or_sync_error(self):
        with tempfile.TemporaryDirectory() as root:
            permission_path = Path(root) / "permission.json"
            permission_bridge = FileMemoryProjection(permission_path)
            with mock.patch(
                "sidecar.ports.Path.chmod", side_effect=OSError("permission-denied")
            ):
                with self.assertRaisesRegex(OSError, "permission-denied"):
                    permission_bridge.replace_health_projection(
                        self.SUBJECT, {"schema_version": 1}
                    )
            self.assertFalse(permission_path.exists())

            sync_path = Path(root) / "sync.json"
            sync_bridge = FileMemoryProjection(sync_path)
            with mock.patch(
                "sidecar.ports.os.fsync", side_effect=OSError("sync-failed")
            ):
                with self.assertRaisesRegex(OSError, "sync-failed"):
                    sync_bridge.replace_health_projection(
                        self.SUBJECT, {"schema_version": 1}
                    )
            self.assertFalse(sync_path.exists())

    @unittest.skipIf(not hasattr(socket, "AF_UNIX"), "AF_UNIX not available")
    def test_sidecar_produces_projection_from_authoritative_profile(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store, _ = self._store(root_path)
            self._add_profile_content(store)
            path = root_path / "memory.json"
            server = HealthSidecarServer(
                root_path / "health.sock",
                store,
                allowed_uids={getattr(os, "getuid", lambda: 0)()},
                memory_projection=FileMemoryProjection(path),
                projection_subject=self.SUBJECT,
            )
            self.assertTrue(server._sync_projection(self.SUBJECT, fail_closed=True))
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                document[self.SUBJECT]["archive_pointer"],
                "health-sidecar://profile/profile",
            )
            self.assertNotIn("profile_summary_zh", document[self.SUBJECT])

    @unittest.skipIf(not hasattr(socket, "AF_UNIX"), "AF_UNIX not available")
    def test_adapter_socket_delete_blocks_future_reads(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            socket_path = root_path / "health.sock"
            store, _ = self._store(root_path)
            self._add_profile_content(store)
            ready = threading.Event()
            server = HealthSidecarServer(
                socket_path,
                store,
                allowed_uids={os.getuid()},
                ready_event=ready,
                memory_projection=MemoryProjectionFake(),
            )
            thread = threading.Thread(target=server.run_forever, daemon=True)
            thread.start()
            self.assertTrue(ready.wait(timeout=3))
            try:
                adapter = PartnerHealthAdapter(str(socket_path), timeout_seconds=1.0)
                with self.assertRaisesRegex(
                    RuntimeError, "delete-status-owner-mismatch"
                ):
                    adapter.profile_deletion_status(
                        self.SUBJECT,
                        "untrusted-socket-peer",
                        "socket-status-untrusted",
                        "2026-01-02T00:04:01Z",
                        "forged-token",
                    )
                status = adapter.profile_deletion_status(
                    self.SUBJECT,
                    self.OWNER,
                    *self._receipt(
                        store,
                        self.DELETE_CONFIRM_ACTION,
                        "socket-status-owner",
                        message_utc="2026-01-02T00:04:01Z",
                    ),
                )
                self.assertFalse(status["deleted"])
                self.assertFalse(status["deletion_pending"])
                request_id = "socket-delete-request"
                adapter.request_profile_deletion(
                    self.SUBJECT,
                    self.OWNER,
                    *self._receipt(
                        store,
                        self.DELETE_REQUEST_ACTION,
                        request_id,
                    ),
                )
                self.assertIsNotNone(
                    store.read_subject_status(self.SUBJECT, _allow_profile_state=True)
                )
                result = adapter.confirm_profile_deletion(
                    self.SUBJECT,
                    self.OWNER,
                    request_id,
                    *self._receipt(
                        store,
                        self.DELETE_CONFIRM_ACTION,
                        "socket-delete-confirm",
                        message_utc="2026-01-02T00:04:01Z",
                    ),
                )
                self.assertTrue(result["deleted"])
                purge = adapter.purge_backups()
                self.assertIn("deleted", purge)
                with self.assertRaisesRegex(RuntimeError, "profile-not-bound"):
                    adapter.read_authorized_view(
                        self.SUBJECT,
                        self.OWNER,
                        *self._receipt(store, "health.access.read", "socket-read-after-delete"),
                    )
            finally:
                server.stop()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

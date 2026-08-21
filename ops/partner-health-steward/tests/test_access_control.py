import datetime as dt
import json
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

from sidecar.protocol import (
    ACTION_ACCESS_ANALYZE,
    ACTION_ACCESS_GRANT,
    ACTION_ACCESS_READ,
    ACTION_ACCESS_REVOKE,
    ACTION_PROFILE_EXPORT,
    parse_request,
)
from sidecar import HealthSidecarServer, PartnerHealthAdapter
from sidecar.store import HealthSidecarStore, StoreError


class FixedClock:
    def __init__(self, now: dt.datetime):
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class FixedKeyManager:
    def load_or_create_master_key(self, key_path: Path) -> bytes:
        if key_path.exists():
            return key_path.read_bytes()
        key = b"k" * 32
        key_path.write_bytes(key)
        return key

    def generate_record_key(self) -> bytes:
        return b"r" * 32


class AccessControlTests(unittest.TestCase):
    SUBJECT = "profile"
    OWNER = "owner-wechat"
    VIEWER = "viewer-wechat"

    def _store(self, root: Path) -> HealthSidecarStore:
        return HealthSidecarStore(
            root / "state.sqlite.enc",
            root / "key.bin",
            clock=FixedClock(dt.datetime(2026, 1, 2, 3, 5, tzinfo=dt.timezone.utc)),
            key_manager=FixedKeyManager(),
        )

    def _bound_store(self, root: Path) -> tuple[HealthSidecarStore, str]:
        store = self._store(root)
        token = store.message_verifier.sign_owner_binding(
            subject=self.SUBJECT, owner_sender_id=self.OWNER
        )
        self.assertTrue(store.bind_profile_owner(self.SUBJECT, self.OWNER, token))
        return store, token

    def _receipt(
        self,
        store: HealthSidecarStore,
        action: str,
        actor: str,
        target: str,
        message_id: str,
    ) -> tuple[str, str, str]:
        message_utc = "2026-01-02T03:04:05Z"
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

    def test_protocol_exposes_access_and_export_actions(self):
        grant = parse_request(
            json.dumps(
                {
                    "action": ACTION_ACCESS_GRANT,
                    "payload": {
                        "subject": self.SUBJECT,
                        "owner_sender_id": self.OWNER,
                        "viewer_sender_id": self.VIEWER,
                        "receipt_message_id": "grant-1",
                        "receipt_utc": "2026-01-02T03:04:05Z",
                        "verification_token": "token",
                    },
                }
            ).encode()
        )
        revoke = parse_request(
            json.dumps(
                {
                    "action": ACTION_ACCESS_REVOKE,
                    "payload": {
                        "subject": self.SUBJECT,
                        "owner_sender_id": self.OWNER,
                        "viewer_sender_id": self.VIEWER,
                        "receipt_message_id": "revoke-1",
                        "receipt_utc": "2026-01-02T03:04:05Z",
                        "verification_token": "token",
                    },
                }
            ).encode()
        )
        read = parse_request(
            json.dumps(
                {
                    "action": ACTION_ACCESS_READ,
                    "payload": {
                        "subject": self.SUBJECT,
                        "sender_id": self.VIEWER,
                        "receipt_message_id": "read-1",
                        "receipt_utc": "2026-01-02T03:04:05Z",
                        "verification_token": "token",
                    },
                }
            ).encode()
        )
        analyze = parse_request(
            json.dumps(
                {
                    "action": ACTION_ACCESS_ANALYZE,
                    "payload": {
                        "subject": self.SUBJECT,
                        "sender_id": self.OWNER,
                        "receipt_message_id": "analyze-1",
                        "receipt_utc": "2026-01-02T03:04:05Z",
                        "verification_token": "token",
                    },
                }
            ).encode()
        )
        export = parse_request(
            json.dumps(
                {
                    "action": ACTION_PROFILE_EXPORT,
                    "payload": {
                        "subject": self.SUBJECT,
                        "sender_id": self.OWNER,
                        "receipt_message_id": "export-1",
                        "receipt_utc": "2026-01-02T03:04:05Z",
                        "verification_token": "token",
                    },
                }
            ).encode()
        )
        self.assertEqual(grant.action, ACTION_ACCESS_GRANT)
        self.assertEqual(revoke.action, ACTION_ACCESS_REVOKE)
        self.assertEqual(read.action, ACTION_ACCESS_READ)
        self.assertEqual(analyze.action, ACTION_ACCESS_ANALYZE)
        self.assertEqual(export.action, ACTION_PROFILE_EXPORT)

    def test_analysis_receipt_binds_all_fields_and_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as root:
            store, _token = self._bound_store(Path(root))
            receipt = self._receipt(
                store,
                "health.access.analyze",
                self.OWNER,
                self.OWNER,
                "analyze-valid",
            )
            context = store.read_authorized_analysis_context(
                self.SUBJECT,
                self.OWNER,
                *receipt,
            )
            self.assertEqual(context["role"], "owner")
            self.assertEqual(
                set(context),
                {
                    "analysis_context_schema_version",
                    "subject",
                    "role",
                    "current_version_id",
                    "profile_summary_zh",
                    "evidence_ids",
                },
            )
            with self.assertRaisesRegex(StoreError, "access-receipt-replayed"):
                store.read_authorized_analysis_context(
                    self.SUBJECT,
                    self.OWNER,
                    *receipt,
                )

            message_utc = "2026-01-02T03:04:05Z"
            cases = (
                (
                    "analyze-wrong-action",
                    "health.access.read",
                    self.OWNER,
                    self.OWNER,
                    "analyze-wrong-action",
                    message_utc,
                ),
                (
                    "analyze-wrong-sender",
                    "health.access.analyze",
                    self.VIEWER,
                    self.VIEWER,
                    "analyze-wrong-sender",
                    message_utc,
                ),
                (
                    "analyze-message-call",
                    "health.access.analyze",
                    self.OWNER,
                    self.OWNER,
                    "analyze-message-signed",
                    message_utc,
                ),
                (
                    "analyze-wrong-time",
                    "health.access.analyze",
                    self.OWNER,
                    self.OWNER,
                    "analyze-wrong-time",
                    "2026-01-02T03:04:04Z",
                ),
            )
            for call_message_id, action, actor, target, signed_message_id, signed_utc in cases:
                with self.subTest(call_message_id=call_message_id):
                    bad_token = store.message_verifier.sign_access_receipt(
                        action=action,
                        subject=self.SUBJECT,
                        actor_sender_id=actor,
                        target_sender_id=target,
                        message_id=signed_message_id,
                        message_utc=signed_utc,
                    )
                    with self.assertRaisesRegex(StoreError, "unverified-access-receipt"):
                        store.read_authorized_analysis_context(
                            self.SUBJECT,
                            self.OWNER,
                            call_message_id,
                            message_utc,
                            bad_token,
                        )

    def test_analysis_context_caps_active_evidence_references(self):
        with tempfile.TemporaryDirectory() as root:
            store, _token = self._bound_store(Path(root))

            def add_many_conclusions(current):
                updated = dict(current)
                updated["profile_summary_zh"] = "紧凑画像" * 30
                updated["conclusions"] = [
                    {
                        "dedupe_key": f"active-{index}",
                        "active": True,
                        "evidence_ids": [
                            f"ev-{index}-{evidence_index}"
                            for evidence_index in range(5)
                        ],
                    }
                    for index in range(12)
                ] + [
                    {
                        "dedupe_key": "inactive-history",
                        "active": False,
                        "evidence_ids": ["inactive-evidence"],
                    }
                ]
                return updated, None

            store.mutate_subject_status(self.SUBJECT, add_many_conclusions)
            context = store.read_authorized_analysis_context(
                self.SUBJECT,
                self.OWNER,
                *self._receipt(
                    store,
                    "health.access.analyze",
                    self.OWNER,
                    self.OWNER,
                    "analyze-bounded",
                ),
            )

            self.assertEqual(len(context["evidence_ids"]), 24)
            self.assertNotIn("inactive-evidence", context["evidence_ids"])
            for conclusion_index in range(8):
                self.assertEqual(
                    [
                        evidence_id
                        for evidence_id in context["evidence_ids"]
                        if evidence_id.startswith(f"ev-{conclusion_index}-")
                    ],
                    [
                        f"ev-{conclusion_index}-{evidence_index}"
                        for evidence_index in range(3)
                    ],
                )

    def test_owner_grant_viewer_and_both_can_read_full_view(self):
        with tempfile.TemporaryDirectory() as root:
            store, token = self._bound_store(Path(root))
            grant_receipt = self._receipt(
                store, "health.access.grant", self.OWNER, self.VIEWER, "grant-1"
            )
            result = store.grant_profile_viewer(
                self.SUBJECT, self.OWNER, self.VIEWER, *grant_receipt
            )
            self.assertTrue(result["granted"])
            self.assertEqual(result["viewer_sender_id"], self.VIEWER)

            owner_view = store.read_authorized_view(
                self.SUBJECT,
                self.OWNER,
                *self._receipt(
                    store, "health.access.read", self.OWNER, self.OWNER, "read-owner"
                ),
            )
            viewer_view = store.read_authorized_view(
                self.SUBJECT,
                self.VIEWER,
                *self._receipt(
                    store, "health.access.read", self.VIEWER, self.VIEWER, "read-viewer"
                ),
            )
            self.assertEqual(owner_view["role"], "owner")
            self.assertEqual(viewer_view["role"], "viewer")
            for view in (owner_view, viewer_view):
                self.assertIn("profile", view)
                self.assertIn("evidence", view["profile"])
                self.assertIn("tasks", view)
                self.assertIn("reports", view)
                self.assertIn("audit", view)
            self.assertIn("viewer_grants", owner_view["profile"])
            self.assertNotIn("viewer_grants", viewer_view["profile"])
            legacy_profile = store.read_authorized_view(
                self.SUBJECT,
                self.OWNER,
                *self._receipt(
                    store,
                    "health.profile.read",
                    self.OWNER,
                    self.OWNER,
                    "legacy-profile-read",
                ),
                action="health.profile.read",
            )
            self.assertEqual(legacy_profile["role"], "owner")

    def test_owner_can_read_structured_empty_view_before_first_health_fact(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store = HealthSidecarStore(
                root_path / "state.sqlite.enc",
                root_path / "key.bin",
                clock=FixedClock(
                    dt.datetime(2026, 1, 2, 3, 5, tzinfo=dt.timezone.utc)
                ),
                key_manager=FixedKeyManager(),
                expected_owner_sender_id=self.OWNER,
                expected_viewer_sender_id=self.VIEWER,
            )
            enable_id = "enable-empty-view"
            enable_utc = "2026-01-02T03:04:05Z"
            store.enable_health_recording(
                self.SUBJECT,
                self.OWNER,
                enable_id,
                enable_utc,
                store.message_verifier.sign_access_receipt(
                    action="health.recording.enable",
                    subject=self.SUBJECT,
                    actor_sender_id=self.OWNER,
                    target_sender_id=self.OWNER,
                    message_id=enable_id,
                    message_utc=enable_utc,
                ),
            )

            view = store.read_authorized_view(
                self.SUBJECT,
                self.OWNER,
                *self._receipt(
                    store,
                    "health.access.read",
                    self.OWNER,
                    self.OWNER,
                    "read-empty-view",
                ),
            )

            self.assertEqual(view["role"], "owner")
            self.assertEqual(view["profile"]["recording_status"], "recording_enabled")
            self.assertIsNone(view["profile"]["current_version_id"])
            self.assertEqual(view["profile"]["evidence"], [])
            self.assertEqual(view["tasks"], [])
            self.assertEqual(view["reports"], [])

    def test_revoke_blocks_future_view_and_history_is_not_claimed_recalled(self):
        with tempfile.TemporaryDirectory() as root:
            store, token = self._bound_store(Path(root))
            store.grant_profile_viewer(
                self.SUBJECT,
                self.OWNER,
                self.VIEWER,
                *self._receipt(
                    store, "health.access.grant", self.OWNER, self.VIEWER, "grant-2"
                ),
            )
            self.assertEqual(
                store.read_authorized_view(
                    self.SUBJECT,
                    self.VIEWER,
                    *self._receipt(
                        store, "health.access.read", self.VIEWER, self.VIEWER, "read-2"
                    ),
                )["role"],
                "viewer",
            )
            revoked = store.revoke_profile_viewer(
                self.SUBJECT,
                self.OWNER,
                self.VIEWER,
                *self._receipt(
                    store, "health.access.revoke", self.OWNER, self.VIEWER, "revoke-2"
                ),
            )
            self.assertTrue(revoked["revoked"])
            with self.assertRaisesRegex(StoreError, "access-not-authorized"):
                store.read_authorized_view(
                    self.SUBJECT,
                    self.VIEWER,
                    *self._receipt(
                        store, "health.access.read", self.VIEWER, self.VIEWER, "read-3"
                    ),
                )
            events = store.read_audit_events()
            self.assertTrue(any(event["event"] == "access_revoke" for event in events))
            self.assertNotIn("recall", json.dumps(events, ensure_ascii=False))

    def test_only_verified_owner_can_grant_or_revoke(self):
        with tempfile.TemporaryDirectory() as root:
            store, token = self._bound_store(Path(root))
            with self.assertRaisesRegex(StoreError, "access-owner-mismatch"):
                store.grant_profile_viewer(
                    self.SUBJECT,
                    self.VIEWER,
                    "other-viewer",
                    *self._receipt(
                        store, "health.access.grant", self.VIEWER, "other-viewer", "grant-3"
                    ),
                )
            with self.assertRaisesRegex(StoreError, "unverified-access-receipt"):
                store.grant_profile_viewer(
                    self.SUBJECT,
                    self.OWNER,
                    "other-viewer",
                    "grant-4",
                    "2026-01-02T03:04:05Z",
                    "wrong-token",
                )
            with self.assertRaisesRegex(StoreError, "access-not-authorized"):
                store.read_authorized_view(
                    self.SUBJECT,
                    self.VIEWER,
                    *self._receipt(
                        store, "health.access.read", self.VIEWER, self.VIEWER, "read-4"
                    ),
                )

    def test_configured_viewer_is_enforced_again_inside_the_sidecar(self):
        with tempfile.TemporaryDirectory() as root:
            store = HealthSidecarStore(
                Path(root) / "state.sqlite.enc",
                Path(root) / "key.bin",
                clock=FixedClock(
                    dt.datetime(2026, 1, 2, 3, 5, tzinfo=dt.timezone.utc)
                ),
                key_manager=FixedKeyManager(),
                expected_viewer_sender_id=self.VIEWER,
            )
            token = store.message_verifier.sign_owner_binding(
                subject=self.SUBJECT,
                owner_sender_id=self.OWNER,
            )
            self.assertTrue(store.bind_profile_owner(self.SUBJECT, self.OWNER, token))

            with self.assertRaisesRegex(StoreError, "viewer-not-configured"):
                store.grant_profile_viewer(
                    self.SUBJECT,
                    self.OWNER,
                    "viewer-other",
                    *self._receipt(
                        store,
                        "health.access.grant",
                        self.OWNER,
                        "viewer-other",
                        "grant-other",
                    ),
                )
            granted = store.grant_profile_viewer(
                self.SUBJECT,
                self.OWNER,
                self.VIEWER,
                *self._receipt(
                    store,
                    "health.access.grant",
                    self.OWNER,
                    self.VIEWER,
                    "grant-configured",
                ),
            )
            self.assertEqual(granted["viewer_sender_id"], self.VIEWER)

    def test_unauthorized_reads_and_writes_do_not_expose_health_content(self):
        with tempfile.TemporaryDirectory() as root:
            store, token = self._bound_store(Path(root))
            with self.assertRaisesRegex(StoreError, "access-not-authorized"):
                store.export_profile(
                    self.SUBJECT,
                    self.VIEWER,
                    *self._receipt(
                        store, "health.profile.export", self.VIEWER, self.VIEWER, "export-2"
                    ),
                )
            with self.assertRaisesRegex(StoreError, "profile-state-protected"):
                store.write_subject_status(
                    self.SUBJECT,
                    {"profile_schema_version": 1, "profile_summary_zh": "secret"},
                )
            events = store.read_audit_events()
            serialized = json.dumps(events, ensure_ascii=False)
            self.assertNotIn("secret", serialized)
            self.assertTrue(any(event["event"] == "access_denied" for event in events))

    def test_viewer_cannot_export_and_receipts_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._bound_store(Path(root))
            store.grant_profile_viewer(
                self.SUBJECT,
                self.OWNER,
                self.VIEWER,
                *self._receipt(
                    store, "health.access.grant", self.OWNER, self.VIEWER, "grant-export"
                ),
            )
            with self.assertRaisesRegex(StoreError, "owner-only-export"):
                store.export_profile(
                    self.SUBJECT,
                    self.VIEWER,
                    *self._receipt(
                        store,
                        "health.profile.export",
                        self.VIEWER,
                        self.VIEWER,
                        "viewer-export",
                    ),
                )
            owner_receipt = self._receipt(
                store,
                "health.profile.export",
                self.OWNER,
                self.OWNER,
                "owner-export",
            )
            exported = store.export_profile(self.SUBJECT, self.OWNER, *owner_receipt)
            self.assertTrue(exported["exported"])
            with self.assertRaisesRegex(StoreError, "access-receipt-replayed"):
                store.export_profile(self.SUBJECT, self.OWNER, *owner_receipt)

            events = store.read_audit_events()
            for event in events:
                details = event.get("details", {})
                if event.get("event") in {
                    "access_grant",
                    "access_read",
                    "access_revoke",
                    "access_denied",
                    "profile_export",
                }:
                    self.assertTrue(details.get("actor_role"))
                    self.assertTrue(details.get("action"))
                    self.assertTrue(details.get("object_id"))
                    self.assertIn(details.get("result"), {"allowed", "denied", "granted", "revoked"})
                    self.assertTrue(event.get("utc"))

    def test_access_receipt_has_ten_minute_window_and_private_ledger(self):
        with tempfile.TemporaryDirectory() as root:
            store, _ = self._bound_store(Path(root))
            old_receipt = (
                "old-receipt",
                "2026-01-02T02:54:00Z",
                store.message_verifier.sign_access_receipt(
                    action="health.access.read",
                    subject=self.SUBJECT,
                    actor_sender_id=self.OWNER,
                    target_sender_id=self.OWNER,
                    message_id="old-receipt",
                    message_utc="2026-01-02T02:54:00Z",
                ),
            )
            with self.assertRaisesRegex(StoreError, "access-receipt-expired"):
                store.read_authorized_view(self.SUBJECT, self.OWNER, *old_receipt)

            fresh = store.read_authorized_view(
                self.SUBJECT,
                self.OWNER,
                *self._receipt(
                    store, "health.access.read", self.OWNER, self.OWNER, "fresh-receipt"
                ),
            )
            self.assertNotIn("access_receipt_ids", fresh["profile"])
            with self.assertRaisesRegex(StoreError, "access-receipt-state-protected"):
                store.read_subject_status("__health_access_receipt_ledger__")

    @unittest.skipIf(not hasattr(socket, "AF_UNIX"), "AF_UNIX not available")
    def test_partner_adapter_socket_seam_grant_read_revoke(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            socket_path = root_path / "health.sock"
            store = self._store(root_path)
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
                token = store.message_verifier.sign_owner_binding(
                    subject=self.SUBJECT, owner_sender_id=self.OWNER
                )
                adapter = PartnerHealthAdapter(str(socket_path), timeout_seconds=1.0)
                self.assertTrue(adapter.bind_profile_owner(self.SUBJECT, self.OWNER, token))
                def receipt(action: str, actor: str, target: str, message_id: str):
                    utc = "2026-01-02T03:04:05Z"
                    return (
                        message_id,
                        utc,
                        store.message_verifier.sign_access_receipt(
                            action=action,
                            subject=self.SUBJECT,
                            actor_sender_id=actor,
                            target_sender_id=target,
                            message_id=message_id,
                            message_utc=utc,
                        ),
                    )

                adapter.grant_viewer(
                    self.SUBJECT,
                    self.OWNER,
                    self.VIEWER,
                    *receipt("health.access.grant", self.OWNER, self.VIEWER, "socket-grant"),
                )
                for index in range(1400):
                    store.append_audit_event(
                        "content_free_growth_fixture",
                        {
                            "subject": self.SUBJECT,
                            "actor_role": "test-fixture",
                            "action": "fixture.grow.audit",
                            "object_id": f"audit-{index:04d}-" + "x" * 100,
                            "result": "recorded",
                        },
                    )
                view = adapter.read_authorized_view(
                    self.SUBJECT,
                    self.VIEWER,
                    *receipt("health.access.read", self.VIEWER, self.VIEWER, "socket-read"),
                )
                self.assertEqual(view["role"], "viewer")
                self.assertGreater(
                    len(json.dumps(view, ensure_ascii=False).encode("utf-8")),
                    128 * 1024,
                )
                exported = adapter.export_profile(
                    self.SUBJECT,
                    self.OWNER,
                    *receipt("health.profile.export", self.OWNER, self.OWNER, "socket-export"),
                )
                self.assertTrue(exported["exported"])
                with self.assertRaisesRegex(RuntimeError, "owner-only-export"):
                    adapter.export_profile(
                        self.SUBJECT,
                        self.VIEWER,
                        *receipt(
                            "health.profile.export",
                            self.VIEWER,
                            self.VIEWER,
                            "socket-viewer-export",
                        ),
                    )
                adapter.revoke_viewer(
                    self.SUBJECT,
                    self.OWNER,
                    self.VIEWER,
                    *receipt("health.access.revoke", self.OWNER, self.VIEWER, "socket-revoke"),
                )
                with self.assertRaisesRegex(RuntimeError, "access-not-authorized"):
                    adapter.read_authorized_view(
                        self.SUBJECT,
                        self.VIEWER,
                        *receipt("health.access.read", self.VIEWER, self.VIEWER, "socket-read-2"),
                    )
                events = adapter.read_audit()
                relevant = [
                    event
                    for event in events
                    if event.get("event")
                    in {"access_grant", "access_read", "profile_export", "access_denied", "access_revoke"}
                ]
                self.assertTrue(relevant)
                for event in relevant:
                    details = event.get("details", {})
                    self.assertTrue(details.get("actor_role"))
                    self.assertTrue(details.get("action"))
                    self.assertTrue(details.get("object_id"))
                    self.assertTrue(details.get("result"))
                    self.assertTrue(event.get("utc"))
            finally:
                server.stop()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

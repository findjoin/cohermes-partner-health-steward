from __future__ import annotations

import asyncio
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
HERMES_SOURCE = ROOT.parents[1] / ".research" / "hermes-agent"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERMES_SOURCE))
sys.path.insert(0, str(ROOT / "plugin" / "health-steward"))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from gateway.config import PlatformConfig
from export_attachments import PrivateJsonExportStore
from owner_controls import PartnerOwnerControlHandler
from sidecar import HealthSidecarServer, PartnerHealthAdapter
from sidecar.receipt_signer import Ed25519ReceiptSigner
from sidecar.store import Ed25519InboundMessageVerifier, HealthSidecarStore
from sidecar.weixin_delivery import (
    DeliveryResult,
    ProfileDeliveryBlockedError,
    WeixinHealthChannel,
)
from weixin_adapter import PartnerHealthWeixinAdapter
from weixin_ingress import (
    IngressOutcome,
    PartnerWeixinIngressCoordinator,
    TrustedWeixinEnvelope,
)


OWNER = "wx-owner"
VIEWER = "wx-viewer"
ADMIN = "wx-admin"
SUBJECT = "profile"


class _ExplodingClassifier:
    def __init__(self) -> None:
        self.calls = 0

    def classify(self, _envelope):
        self.calls += 1
        raise AssertionError("owner control must not enter health classification")


class _RecordingTransport:
    runtime_version = "test-hermes-v1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.attachment_calls: list[tuple[str, Path, bytes, str, int]] = []

    def send_text(self, recipient: str, message: str, client_id: str):
        self.calls.append((recipient, message, client_id))
        return DeliveryResult.accepted(client_id)

    def send_json_attachment(self, recipient: str, attachment: Path, client_id: str):
        path = Path(attachment)
        self.attachment_calls.append(
            (
                recipient,
                path,
                path.read_bytes(),
                client_id,
                path.stat().st_mode & 0o777,
            )
        )
        return DeliveryResult.accepted(client_id)


class _RecordingAnalyzer:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, str]] = []

    def analyze(self, context, request_text: str) -> str:
        self.calls.append((dict(context), request_text))
        return "基于当前紧凑画像：请继续观察睡眠变化。"


class _RecordingHealthTurnHandler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def handle(self, envelope, _outcome, **_kwargs) -> None:
        self.calls.append(envelope.message_id)


class _StorePort:
    """Public sidecar behavior used where this Windows Python has no AF_UNIX."""

    def __init__(self, store: HealthSidecarStore) -> None:
        self.store = store
        self.projection = _MemoryProjection()

    def read_authorized_view(self, *args, **kwargs):
        return self.store.read_authorized_view(*args, **kwargs)

    def read_authorized_analysis_context(self, *args, **kwargs):
        return self.store.read_authorized_analysis_context(*args, **kwargs)

    def export_profile(self, *args, **kwargs):
        return self.store.export_profile(*args, **kwargs)

    def request_profile_deletion(self, *args, **kwargs):
        return self.store.request_profile_deletion(*args, **kwargs)

    def confirm_profile_deletion(self, *args, **kwargs):
        return self.store.confirm_profile_deletion(
            *args, **kwargs, memory_projection=self.projection
        )

    def profile_deletion_status(self, *args, **kwargs):
        return self.store.profile_deletion_status(*args, **kwargs)

    def grant_viewer(self, *args, **kwargs):
        return self.store.grant_profile_viewer(*args, **kwargs)

    def revoke_viewer(self, *args, **kwargs):
        return self.store.revoke_profile_viewer(*args, **kwargs)

    def pause_proactive_contact(self, *args, **kwargs):
        return self.store.pause_proactive_contact(*args, **kwargs)

    def resume_proactive_contact(self, *args, **kwargs):
        return self.store.resume_proactive_contact(*args, **kwargs)

    def stop_health_recording(self, *args, **kwargs):
        return self.store.stop_health_recording(*args, **kwargs)

    def resume_health_recording(self, *args, **kwargs):
        return self.store.resume_health_recording(*args, **kwargs)

    def health_recording_enabled(self, *args, **kwargs):
        return self.store.health_recording_enabled(*args, **kwargs)

    def health_recording_status(self, *args, **kwargs):
        return self.store.health_recording_status(*args, **kwargs)

    def append_audit_event_once(self, event_id, event, details):
        return self.store.append_audit_event_once(event_id, event, details)

    def read_audit(self):
        return self.store.read_audit_events()


class _MemoryProjection:
    def __init__(self) -> None:
        self.removed: list[str] = []

    def remove_health_projection(self, subject: str) -> bool:
        self.removed.append(subject)
        return True


class OwnerControlPrimarySeamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.old_hermes_home = os.environ.get("HERMES_HOME")
        self.temp_home = tempfile.TemporaryDirectory()
        os.environ["HERMES_HOME"] = self.temp_home.name
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

        private = Ed25519PrivateKey.generate()
        private_bytes = private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        public_bytes = private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.signer = Ed25519ReceiptSigner(private_bytes)
        self.store = HealthSidecarStore(
            self.root / "state.enc",
            self.root / "state.key",
            message_verifier=Ed25519InboundMessageVerifier(public_bytes),
            expected_owner_sender_id=OWNER,
            expected_viewer_sender_id=VIEWER,
        )
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        enable_id = "fixture-enable"
        self.store.enable_health_recording(
            SUBJECT,
            OWNER,
            enable_id,
            now,
            self.signer.sign_access(
                action="health.recording.enable",
                subject=SUBJECT,
                actor_sender_id=OWNER,
                target_sender_id=OWNER,
                message_id=enable_id,
                message_utc=now,
            ),
        )
        message_id = "fixture-health"
        message_text = "我最近睡不好"
        candidate = {
            "evidence_kind": "direct_statement",
            "source_message_id": message_id,
            "source_utc": now,
            "excerpt": message_text,
            "measurement": None,
            "conclusions": [
                {
                    "category": "state",
                    "dedupe_key": "sleep",
                    "text": "最近睡不好",
                    "status": "fact",
                    "priority": 3,
                }
            ],
        }
        self.store.admit_consented_profile_candidate(
            subject=SUBJECT,
            sender_id=OWNER,
            message_id=message_id,
            message_utc=now,
            attempt_utc=now,
            message_text=message_text,
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
            verification_token=self.signer.sign_ingress(
                action="health.profile.message.admit",
                subject=SUBJECT,
                sender_id=OWNER,
                message_id=message_id,
                message_utc=now,
                attempt_utc=now,
                message_text=message_text,
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
            ),
            candidate=candidate,
        )

        self.sidecar = _StorePort(self.store)
        self.transport = _RecordingTransport()
        self.channel = WeixinHealthChannel(
            self.root / "delivery.sqlite3",
            self.transport,
            accepted_hermes_version="test-hermes-v1",
            audit_sink=self.sidecar,
            profile_subject=SUBJECT,
        )
        export_root = self.root / "private-exports"
        export_root.mkdir(mode=0o700)
        self.export_store = PrivateJsonExportStore(
            export_root,
            tmpfs_verifier=lambda _directory: None,
        )
        self.classifier = _ExplodingClassifier()
        ingress = PartnerWeixinIngressCoordinator(
            self.sidecar,
            self.signer,
            self.classifier,
            expected_owner_sender_id=OWNER,
            subject=SUBJECT,
        )
        controls = PartnerOwnerControlHandler(
            self.sidecar,
            self.signer,
            self.channel,
            expected_owner_sender_id=OWNER,
            expected_viewer_sender_id=VIEWER,
            subject=SUBJECT,
            export_store=self.export_store,
        )
        self.controls = controls
        config = PlatformConfig(
            enabled=True,
            token="test-token",
            typing_indicator=False,
            extra={
                "account_id": "partner-bot",
                "dm_policy": "allowlist",
                "allow_from": [OWNER, VIEWER, ADMIN],
                "text_batch_delay_seconds": 30,
            },
        )
        self.weixin = PartnerHealthWeixinAdapter(
            config,
            ingress,
            owner_control_handler=controls,
        )
        self.weixin._poll_session = object()

        async def no_typing_ticket(*_args, **_kwargs):
            return None

        self.weixin._maybe_fetch_typing_ticket = no_typing_ticket

    async def asyncTearDown(self) -> None:
        pending = list(self.weixin._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.temp.cleanup()
        self.temp_home.cleanup()
        if self.old_hermes_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self.old_hermes_home

    async def _send_event(self, sender_id: str, message_id: str, text: str) -> None:
        await self.weixin._process_message(
            {
                "from_user_id": sender_id,
                "to_user_id": "partner-bot",
                "message_id": message_id,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            }
        )

    async def _wait_for_calls(self, expected: int) -> None:
        for _ in range(200):
            if len(self.transport.calls) >= expected:
                for _ in range(200):
                    if not self.weixin._background_tasks:
                        return
                    await asyncio.sleep(0.01)
                self.fail("owner control background task did not finish")
            await asyncio.sleep(0.01)
        self.fail(f"expected {expected} direct Weixin deliveries")

    async def _wait_for_attachments(self, expected: int) -> None:
        for _ in range(200):
            if len(self.transport.attachment_calls) >= expected:
                for _ in range(200):
                    if not self.weixin._background_tasks:
                        return
                    await asyncio.sleep(0.01)
                self.fail("owner export background task did not finish")
            await asyncio.sleep(0.01)
        self.fail(f"expected {expected} direct Weixin attachments")

    async def _send_control(
        self, sender_id: str, message_id: str, text: str
    ) -> list[str]:
        before = len(self.transport.calls)
        await self._send_event(sender_id, message_id, text)
        await self._wait_for_calls(before + 1)
        return [call[1] for call in self.transport.calls[before:]]

    @staticmethod
    def _joined_delivery(messages: list[str]) -> str:
        if len(messages) == 1 and not messages[0].startswith("【"):
            return messages[0]
        return "".join(message.split("\n", 1)[1] for message in messages)

    async def _assert_slow_control_does_not_block_later_health(
        self,
        *,
        control_message_id: str,
        control_text: str,
        control_started: threading.Event,
        release_control: threading.Event,
    ) -> None:
        classification_started = threading.Event()

        def classify_health(envelope, **_kwargs):
            classification_started.set()
            return IngressOutcome("health-related", health_related=True)

        health_turns = _RecordingHealthTurnHandler()
        self.weixin._health_coordinator.classify_and_admit = classify_health
        self.weixin.bind_health_turn_handler(health_turns)
        # Keep this below the 0.2-second non-blocking assertion while leaving
        # enough scheduler margin for the Windows test runtime.
        self.weixin._health_ingress_budget_seconds = 0.25

        await self._send_event(OWNER, control_message_id, control_text)
        self.assertTrue(
            await asyncio.to_thread(control_started.wait, 1),
            "slow control did not reach its blocking boundary",
        )
        health_message_id = f"{control_message_id}-later-health"
        await self._send_event(OWNER, health_message_id, "我今天头疼")
        try:
            self.assertTrue(
                await asyncio.to_thread(classification_started.wait, 0.2),
                "slow private control blocked later health classification",
            )
        finally:
            release_control.set()

        for _ in range(200):
            if not self.weixin._background_tasks:
                break
            await asyncio.sleep(0.01)
        else:
            self.fail("slow control tasks did not finish")
        self.assertEqual(health_turns.calls, [health_message_id])
        self.assertEqual(self.weixin._pending_text_batches, {})

    async def test_owner_natural_self_view_is_direct_and_never_enters_chat_history(self):
        messages = await self._send_control(
            OWNER, "owner-view-1", "请让我查看我的完整健康档案"
        )

        recipient = self.transport.calls[0][0]
        body = self._joined_delivery(messages)
        self.assertEqual(recipient, OWNER)
        self.assertIn('"view_schema_version":1', body)
        self.assertIn("我最近睡不好", body)
        self.assertEqual(self.classifier.calls, 0)
        self.assertEqual(self.weixin._pending_text_batches, {})
        audit = self.sidecar.read_audit()
        self.assertTrue(any(event["event"] == "access_read" for event in audit))
        self.assertNotIn("我最近睡不好", str(audit))

    async def test_owner_export_is_direct_attachment_then_plaintext_is_removed(self):
        await self._send_event(
            OWNER,
            "owner-export-1",
            "请导出我的完整健康档案 JSON",
        )
        await self._wait_for_attachments(1)

        recipient, path, payload, client_id, mode = self.transport.attachment_calls[0]
        exported = json.loads(payload.decode("utf-8"))
        self.assertEqual(recipient, OWNER)
        self.assertTrue(client_id.startswith("hermes-health-"))
        self.assertEqual(exported["export_schema_version"], 1)
        self.assertTrue(exported["exported"])
        self.assertIn("我最近睡不好", payload.decode("utf-8"))
        self.assertFalse(path.exists(), "plaintext export must be removed after handoff")
        if os.name == "posix":
            self.assertEqual(mode, 0o600)
        self.assertEqual(self.transport.calls, [])
        key = f"health-control:v1:{SUBJECT}:{OWNER}:owner-export-1:health.profile.export"
        delivery = self.channel.delivery_status(key)
        self.assertEqual(delivery["status"], "sent")
        self.assertNotIn("我最近睡不好", str(delivery))
        self.assertNotIn(str(path), str(delivery))
        self.assertEqual(self.classifier.calls, 0)
        self.assertEqual(self.weixin._pending_text_batches, {})

    async def test_group_owner_export_and_delete_are_rejected_before_health_or_control_work(
        self,
    ) -> None:
        self.weixin._group_policy = "allowlist"
        self.weixin._group_allow_from = {"trusted-health-group"}
        before_text = len(self.transport.calls)
        before_attachments = len(self.transport.attachment_calls)
        for message_id, text in (
            ("group-owner-export", "导出我的完整健康档案 JSON"),
            ("group-owner-delete", "删除我的健康档案"),
        ):
            await self.weixin._process_message(
                {
                    "from_user_id": OWNER,
                    "to_user_id": "trusted-health-group",
                    "room_id": "trusted-health-group",
                    "msg_type": 1,
                    "message_id": message_id,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                }
            )

        self.assertEqual(len(self.transport.calls), before_text)
        self.assertEqual(len(self.transport.attachment_calls), before_attachments)
        self.assertEqual(self.classifier.calls, 0)
        self.assertIsNotNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )
        self.assertEqual(self.weixin._pending_text_batches, {})

    async def test_viewer_and_admin_cannot_export_health_attachment(self):
        viewer = await self._send_control(
            VIEWER, "viewer-export-denied", "导出我的完整健康档案"
        )
        admin = await self._send_control(
            ADMIN, "admin-export-denied", "导出我的完整健康档案"
        )

        self.assertIn("仅限主人", self._joined_delivery(viewer))
        self.assertIn("仅限主人", self._joined_delivery(admin))
        self.assertEqual(self.transport.attachment_calls, [])
        self.assertEqual(self.classifier.calls, 0)
        self.assertEqual(self.weixin._pending_text_batches, {})

    async def test_owner_delete_requires_second_turn_then_blocks_profile_and_delivery(self):
        request = await self._send_control(
            OWNER, "owner-delete-request", "删除我的健康档案"
        )
        self.assertIn("尚未删除任何健康内容", self._joined_delivery(request))
        self.assertIsNotNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )
        self.assertEqual(self.channel.profile_deletion_status(), "active")

        confirmed = await self._send_control(
            OWNER, "owner-delete-confirm", "确认删除我的健康档案"
        )
        self.assertIn("已永久删除", self._joined_delivery(confirmed))
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )
        self.assertEqual(self.sidecar.projection.removed, [SUBJECT])
        self.assertFalse(self.store.health_recording_enabled(SUBJECT, OWNER))
        self.assertEqual(self.channel.profile_deletion_status(), "deleted")
        terminal_key = (
            f"health-control:v1:{SUBJECT}:{OWNER}:owner-delete-confirm:"
            "health.profile.delete.confirm"
        )
        with self.assertRaises(KeyError):
            self.channel.delivery_batch_status(terminal_key)
        with self.assertRaises(KeyError):
            self.channel.delivery_status(f"{terminal_key}:terminal:0001-of-0001")
        with self.assertRaises(ProfileDeliveryBlockedError):
            self.channel.send_once(OWNER, "health content must not send", "after-delete")
        profile_audit = [
            event
            for event in self.sidecar.read_audit()
            if event.get("details", {}).get("subject") == SUBJECT
        ]
        self.assertEqual([event["event"] for event in profile_audit], ["profile_deleted"])
        self.assertNotIn("我最近睡不好", str(profile_audit))
        self.assertEqual(self.classifier.calls, 0)
        self.assertEqual(self.weixin._pending_text_batches, {})

    @unittest.skipUnless(
        os.name == "posix" and hasattr(socket, "AF_UNIX"),
        "Ticket 21 primary socket seam requires Unix-domain sockets",
    )
    async def test_primary_weixin_export_and_delete_traverse_the_unix_sidecar_boundary(
        self,
    ) -> None:
        socket_path = self.root / "ticket-21-primary.sock"
        ready = threading.Event()
        projection = _MemoryProjection()
        server = HealthSidecarServer(
            socket_path,
            self.store,
            allowed_uids={os.getuid()},
            ready_event=ready,
            memory_projection=projection,
        )
        server_thread = threading.Thread(target=server.run_forever, daemon=True)
        server_thread.start()
        self.assertTrue(ready.wait(timeout=3))
        primary_weixin = None
        try:
            sidecar_port = PartnerHealthAdapter(str(socket_path), timeout_seconds=1.0)
            transport = _RecordingTransport()
            channel = WeixinHealthChannel(
                self.root / "ticket-21-primary-delivery.sqlite3",
                transport,
                accepted_hermes_version="test-hermes-v1",
                audit_sink=sidecar_port,
                profile_subject=SUBJECT,
            )
            export_root = self.root / "ticket-21-primary-exports"
            export_root.mkdir(mode=0o700)
            controls = PartnerOwnerControlHandler(
                sidecar_port,
                self.signer,
                channel,
                expected_owner_sender_id=OWNER,
                expected_viewer_sender_id=VIEWER,
                subject=SUBJECT,
                export_store=PrivateJsonExportStore(
                    export_root,
                    tmpfs_verifier=lambda _directory: None,
                ),
            )
            ingress = PartnerWeixinIngressCoordinator(
                sidecar_port,
                self.signer,
                self.classifier,
                expected_owner_sender_id=OWNER,
                subject=SUBJECT,
            )
            config = PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "dm_policy": "allowlist",
                    "allow_from": [OWNER, VIEWER, ADMIN],
                    "text_batch_delay_seconds": 30,
                },
            )
            primary_weixin = PartnerHealthWeixinAdapter(
                config,
                ingress,
                owner_control_handler=controls,
            )
            primary_weixin._poll_session = object()

            async def no_typing_ticket(*_args, **_kwargs):
                return None

            primary_weixin._maybe_fetch_typing_ticket = no_typing_ticket

            async def send(message_id: str, text: str) -> None:
                await primary_weixin._process_message(
                    {
                        "from_user_id": OWNER,
                        "to_user_id": "partner-bot",
                        "message_id": message_id,
                        "item_list": [{"type": 1, "text_item": {"text": text}}],
                    }
                )
                for _ in range(200):
                    if not primary_weixin._background_tasks:
                        return
                    await asyncio.sleep(0.01)
                self.fail("primary socket control task did not finish")

            await send("primary-export", "导出我的完整健康档案 JSON")
            self.assertEqual(len(transport.attachment_calls), 1)
            self.assertFalse(transport.attachment_calls[0][1].exists())
            self.assertEqual(transport.calls, [])

            await send("primary-delete-request", "删除我的健康档案")
            await send("primary-delete-confirm", "确认删除我的健康档案")
            self.assertEqual(len(transport.calls), 2)
            self.assertIn("已永久删除", transport.calls[-1][1])
            self.assertIsNone(
                self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
            )
            self.assertEqual(channel.profile_deletion_status(), "deleted")
            self.assertEqual(projection.removed, [SUBJECT])
            self.assertEqual(self.classifier.calls, 0)
            self.assertEqual(primary_weixin._pending_text_batches, {})
        finally:
            if primary_weixin is not None:
                pending = list(primary_weixin._background_tasks)
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            server.stop()
            server_thread.join(timeout=2)

    async def test_delete_reconciles_a_prepared_delivery_guard_after_sidecar_commit(self):
        await self._send_control(
            OWNER, "delete-recovery-request", "删除我的健康档案"
        )
        original_complete = self.channel.complete_profile_deletion
        failures = [0]

        def fail_once_complete():
            failures[0] += 1
            if failures[0] == 1:
                raise RuntimeError("controlled-delivery-ledger-outage")
            return original_complete()

        self.channel.complete_profile_deletion = fail_once_complete
        before = len(self.transport.calls)
        await self._send_event(
            OWNER, "delete-recovery-confirm", "确认删除我的健康档案"
        )
        for _ in range(200):
            if not self.weixin._background_tasks:
                break
            await asyncio.sleep(0.01)
        else:
            self.fail("delete recovery control task did not finish")

        self.assertEqual(len(self.transport.calls), before)
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )
        self.assertEqual(self.channel.profile_deletion_status(), "prepared")

        self.channel.complete_profile_deletion = original_complete
        recovered = await self._send_control(
            OWNER, "delete-recovery-retry", "确认删除我的健康档案"
        )
        self.assertIn("已永久删除", self._joined_delivery(recovered))
        self.assertEqual(self.channel.profile_deletion_status(), "deleted")
        self.assertEqual(self.classifier.calls, 0)
        self.assertEqual(self.weixin._pending_text_batches, {})

    async def test_post_delete_sidecar_cleanup_failure_never_reopens_delivery(self):
        await self._send_control(
            OWNER, "delete-postcommit-request", "删除我的健康档案"
        )
        original_mutate = self.store.mutate_subject_status

        def fail_only_confirmation_cleanup(subject, *args, **kwargs):
            if subject == "__health_profile_delete_confirmations__":
                raise RuntimeError("controlled-post-delete-cleanup-failure")
            return original_mutate(subject, *args, **kwargs)

        self.store.mutate_subject_status = fail_only_confirmation_cleanup
        try:
            confirmed = await self._send_control(
                OWNER,
                "delete-postcommit-confirm",
                "确认删除我的健康档案",
            )
        finally:
            self.store.mutate_subject_status = original_mutate

        self.assertIn("已永久删除", self._joined_delivery(confirmed))
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )
        self.assertEqual(self.channel.profile_deletion_status(), "deleted")
        with self.assertRaises(ProfileDeliveryBlockedError):
            self.channel.send_once(OWNER, "must remain blocked", "post-delete-race")
        self.assertEqual(self.classifier.calls, 0)

    async def test_fresh_confirmation_replaces_a_stale_prepared_delivery_guard(self):
        await self._send_control(
            OWNER, "delete-stale-guard-request", "删除我的健康档案"
        )
        self.assertTrue(
            self.channel.prepare_profile_deletion("interrupted-old-confirmation")
        )

        confirmed = await self._send_control(
            OWNER,
            "delete-stale-guard-confirm",
            "确认删除我的健康档案",
        )

        self.assertIn("已永久删除", self._joined_delivery(confirmed))
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )
        self.assertEqual(self.channel.profile_deletion_status(), "deleted")
        self.assertEqual(self.classifier.calls, 0)

    async def test_slow_private_view_does_not_block_later_health_classification(self):
        control_started = threading.Event()
        release_control = threading.Event()
        original_read = self.sidecar.read_authorized_view

        def slow_read(*args, **kwargs):
            control_started.set()
            if not release_control.wait(timeout=2):
                raise RuntimeError("test-view-release-timeout")
            return original_read(*args, **kwargs)

        self.sidecar.read_authorized_view = slow_read
        await self._assert_slow_control_does_not_block_later_health(
            control_message_id="slow-owner-view",
            control_text="查看我的完整健康档案",
            control_started=control_started,
            release_control=release_control,
        )

    async def test_slow_explicit_analysis_does_not_block_later_health_classification(self):
        control_started = threading.Event()
        release_control = threading.Event()

        class SlowAnalyzer:
            def analyze(self, _context, _request_text: str) -> str:
                control_started.set()
                if not release_control.wait(timeout=2):
                    raise RuntimeError("test-analysis-release-timeout")
                return "基于当前紧凑画像：请继续观察睡眠变化。"

        self.controls.analyzer = SlowAnalyzer()
        await self._assert_slow_control_does_not_block_later_health(
            control_message_id="slow-owner-analysis",
            control_text="请用健康模型分析我的健康档案",
            control_started=control_started,
            release_control=release_control,
        )

    async def test_non_pause_receipt_omits_pause_deadline_for_signer_service(self):
        backing_signer = self.signer

        class StrictSignerPort:
            def sign_access(self, **payload):
                if payload["action"] != "health.proactive.pause":
                    if "pause_until_utc" in payload:
                        raise AssertionError("unexpected-pause-until-field")
                return backing_signer.sign_access(**payload)

        self.controls.signer = StrictSignerPort()

        messages = await self._send_control(
            OWNER, "owner-view-strict-signer", "查看我的完整健康档案"
        )

        self.assertIn("我最近睡不好", self._joined_delivery(messages))

    async def test_configured_viewer_can_read_only_between_owner_grant_and_revoke(self):
        grant_messages = await self._send_control(
            OWNER,
            "owner-grant-1",
            "我授权预配置查看者查看我的健康档案",
        )
        self.assertIn("查看授权已生效", self._joined_delivery(grant_messages))

        view_messages = await self._send_control(
            VIEWER, "viewer-view-1", "查看完整健康档案"
        )
        self.assertIn("我最近睡不好", self._joined_delivery(view_messages))

        revoke_messages = await self._send_control(
            OWNER,
            "owner-revoke-1",
            "我撤回预配置查看者的健康档案查看权限",
        )
        self.assertIn("查看授权已撤回", self._joined_delivery(revoke_messages))

        denied_messages = await self._send_control(
            VIEWER, "viewer-view-2", "请再次查看完整健康档案"
        )
        denied = self._joined_delivery(denied_messages)
        self.assertNotIn("我最近睡不好", denied)
        self.assertIn("未获授权", denied)
        self.assertEqual(self.classifier.calls, 0)
        self.assertEqual(self.weixin._pending_text_batches, {})
        audit = self.sidecar.read_audit()
        self.assertEqual(
            [
                event["event"]
                for event in audit
                if event["event"] in {
                    "access_grant",
                    "access_read",
                    "access_revoke",
                    "access_denied",
                }
            ][-4:],
            ["access_grant", "access_read", "access_revoke", "access_denied"],
        )
        self.assertNotIn("我最近睡不好", str(audit))

    async def test_unconfigured_target_and_server_admin_never_gain_health_content(self):
        grant_messages = await self._send_control(
            OWNER,
            "owner-grant-admin",
            "我授权 wx-admin 查看我的健康档案",
        )
        self.assertIn("查看授权未更改", self._joined_delivery(grant_messages))

        admin_messages = await self._send_control(
            ADMIN, "admin-view-1", "请查看完整健康档案"
        )
        admin_reply = self._joined_delivery(admin_messages)
        self.assertIn("未获授权", admin_reply)
        self.assertNotIn("我最近睡不好", admin_reply)
        self.assertEqual(self.classifier.calls, 0)
        self.assertEqual(self.weixin._pending_text_batches, {})
        audit = self.sidecar.read_audit()
        self.assertFalse(any(event["event"] == "access_grant" for event in audit))
        self.assertNotIn("我最近睡不好", str(audit))

    async def test_finite_proactive_pause_and_resume_leave_health_recording_enabled(self):
        pause_messages = await self._send_control(
            OWNER, "pause-2h", "请暂停健康提醒 2 小时"
        )
        self.assertIn("主动触达已暂停", self._joined_delivery(pause_messages))

        view_messages = await self._send_control(
            OWNER, "view-paused", "查看我的健康档案当前状态"
        )
        paused = json.loads(self._joined_delivery(view_messages))["health_view"]["profile"]
        self.assertTrue(paused["proactive_contact"]["paused"])
        self.assertIsNotNone(paused["proactive_contact"]["pause_until_utc"])
        self.assertEqual(paused["recording_status"], "recording_enabled")

        resume_messages = await self._send_control(
            OWNER, "resume-contact", "请恢复健康提醒"
        )
        self.assertIn("主动触达已恢复", self._joined_delivery(resume_messages))

        resumed_messages = await self._send_control(
            OWNER, "view-resumed", "再次查看我的健康档案状态"
        )
        resumed = json.loads(self._joined_delivery(resumed_messages))["health_view"]["profile"]
        self.assertFalse(resumed["proactive_contact"]["paused"])
        self.assertEqual(resumed["recording_status"], "recording_enabled")
        self.assertEqual(self.classifier.calls, 0)
        self.assertEqual(self.weixin._pending_text_batches, {})

    async def test_stop_and_resume_recording_preserve_view_but_disable_classification(self):
        stop_messages = await self._send_control(
            OWNER, "recording-stop", "请停止健康记录"
        )
        self.assertIn("健康记录已停止", self._joined_delivery(stop_messages))

        view_messages = await self._send_control(
            OWNER, "view-stopped", "查看停止后的完整健康档案"
        )
        joined_view = self._joined_delivery(view_messages)
        stopped = json.loads(joined_view)["health_view"]["profile"]
        self.assertEqual(stopped["recording_status"], "recording_stopped")
        self.assertIn("我最近睡不好", joined_view)

        await self._send_event(OWNER, "stopped-health", "我今天头疼")
        for _ in range(200):
            if self.weixin._pending_text_batches:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(self.weixin._pending_text_batches)
        self.assertEqual(self.classifier.calls, 0)

        resume_messages = await self._send_control(
            OWNER, "recording-resume", "我明确恢复健康记录"
        )
        self.assertIn("健康记录已恢复", self._joined_delivery(resume_messages))

        resumed_view_messages = await self._send_control(
            OWNER, "view-recording-resumed", "查看恢复后的健康档案"
        )
        resumed_view = self._joined_delivery(resumed_view_messages)
        resumed = json.loads(resumed_view)["health_view"]["profile"]
        self.assertEqual(resumed["recording_status"], "recording_enabled")
        self.assertIn("我最近睡不好", resumed_view)

    async def test_arriving_stop_blocks_later_message_before_classification(self):
        stop_started = threading.Event()
        allow_stop = threading.Event()
        original_stop = self.sidecar.stop_health_recording

        def blocking_stop(*args, **kwargs):
            stop_started.set()
            if not allow_stop.wait(timeout=3):
                raise RuntimeError("test-stop-release-timeout")
            return original_stop(*args, **kwargs)

        self.sidecar.stop_health_recording = blocking_stop
        classification_calls: list[str] = []

        def classify_later(envelope, **_kwargs):
            classification_calls.append(envelope.message_id)
            return IngressOutcome("no-health-candidate")

        self.weixin._health_coordinator.classify_and_admit = classify_later

        await self._send_event(OWNER, "ordered-stop-1", "停止健康记录")
        self.assertTrue(
            await asyncio.to_thread(stop_started.wait, 2),
            "stop control did not reach the state boundary",
        )
        await self._send_event(
            OWNER,
            "ordered-health-2",
            "刚测得血压偏高",
        )
        await asyncio.sleep(0.05)
        self.assertEqual(classification_calls, [])

        allow_stop.set()
        await self._wait_for_calls(1)
        self.assertFalse(self.store.health_recording_enabled(SUBJECT, OWNER))
        self.assertEqual(classification_calls, [])

        batch_tasks = list(self.weixin._pending_text_batch_tasks.values())
        for task in batch_tasks:
            task.cancel()
        if batch_tasks:
            await asyncio.gather(*batch_tasks, return_exceptions=True)
        self.weixin._pending_text_batches.clear()
        self.weixin._pending_text_batch_tasks.clear()

    async def test_stop_then_resume_state_and_weixin_results_keep_arrival_order(self):
        first_delivery_started = threading.Event()
        release_first_delivery = threading.Event()
        resume_committed = threading.Event()
        original_send = self.channel.send_text_parts_once
        original_resume = self.sidecar.resume_health_recording

        def delayed_stop_delivery(recipient, parts, delivery_key):
            if delivery_key.endswith(":health.recording.stop"):
                first_delivery_started.set()
                if not release_first_delivery.wait(timeout=3):
                    raise RuntimeError("test-stop-delivery-release-timeout")
            return original_send(recipient, parts, delivery_key)

        def observed_resume(*args, **kwargs):
            result = original_resume(*args, **kwargs)
            resume_committed.set()
            return result

        self.channel.send_text_parts_once = delayed_stop_delivery
        self.sidecar.resume_health_recording = observed_resume

        await self._send_event(OWNER, "ordered-stop-delivery", "停止健康记录")
        self.assertTrue(await asyncio.to_thread(first_delivery_started.wait, 2))
        self.assertFalse(self.store.health_recording_enabled(SUBJECT, OWNER))
        await self._send_event(OWNER, "ordered-resume-delivery", "恢复健康记录")
        try:
            self.assertTrue(await asyncio.to_thread(resume_committed.wait, 2))
            self.assertTrue(self.store.health_recording_enabled(SUBJECT, OWNER))
            self.assertEqual(self.transport.calls, [])
        finally:
            release_first_delivery.set()

        await self._wait_for_calls(2)
        replies = [call[1] for call in self.transport.calls]
        self.assertIn("健康记录已停止", replies[0])
        self.assertIn("健康记录已恢复", replies[1])
        self.assertTrue(self.store.health_recording_enabled(SUBJECT, OWNER))

    async def test_resume_then_stop_state_and_weixin_results_keep_arrival_order(self):
        await self._send_control(OWNER, "ordered-initial-stop", "停止健康记录")
        baseline = len(self.transport.calls)
        first_delivery_started = threading.Event()
        release_first_delivery = threading.Event()
        stop_committed = threading.Event()
        original_send = self.channel.send_text_parts_once
        original_stop = self.sidecar.stop_health_recording

        def delayed_resume_delivery(recipient, parts, delivery_key):
            if delivery_key.endswith(":health.recording.resume"):
                first_delivery_started.set()
                if not release_first_delivery.wait(timeout=3):
                    raise RuntimeError("test-resume-delivery-release-timeout")
            return original_send(recipient, parts, delivery_key)

        def observed_stop(*args, **kwargs):
            result = original_stop(*args, **kwargs)
            stop_committed.set()
            return result

        self.channel.send_text_parts_once = delayed_resume_delivery
        self.sidecar.stop_health_recording = observed_stop

        await self._send_event(OWNER, "ordered-resume-first", "恢复健康记录")
        self.assertTrue(await asyncio.to_thread(first_delivery_started.wait, 2))
        self.assertTrue(self.store.health_recording_enabled(SUBJECT, OWNER))
        await self._send_event(OWNER, "ordered-stop-second", "停止健康记录")
        try:
            self.assertTrue(await asyncio.to_thread(stop_committed.wait, 2))
            self.assertFalse(self.store.health_recording_enabled(SUBJECT, OWNER))
            self.assertEqual(len(self.transport.calls), baseline)
        finally:
            release_first_delivery.set()

        await self._wait_for_calls(baseline + 2)
        replies = [call[1] for call in self.transport.calls[baseline:]]
        self.assertIn("健康记录已恢复", replies[0])
        self.assertIn("健康记录已停止", replies[1])
        self.assertFalse(self.store.health_recording_enabled(SUBJECT, OWNER))

    async def test_explicit_analysis_uses_only_minimal_pinned_health_context(self):
        analyzer = _RecordingAnalyzer()
        self.controls.analyzer = analyzer

        analysis_messages = await self._send_control(
            OWNER,
            "analyze-profile-1",
            "请用健康模型分析我的当前健康画像",
        )

        self.assertEqual(len(analyzer.calls), 1)
        context, request_text = analyzer.calls[0]
        self.assertEqual(request_text, "请用健康模型分析我的当前健康画像")
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
        self.assertNotIn("我最近睡不好", str(context))
        self.assertIn("基于当前紧凑画像", self._joined_delivery(analysis_messages))
        self.assertEqual(self.classifier.calls, 0)
        self.assertEqual(self.weixin._pending_text_batches, {})

    async def test_only_currently_authorized_viewer_can_request_analysis(self):
        analyzer = _RecordingAnalyzer()
        self.controls.analyzer = analyzer
        await self._send_control(
            OWNER,
            "grant-viewer-analysis",
            "授权预配置查看者查看健康档案",
        )

        allowed = await self._send_control(
            VIEWER,
            "viewer-analysis-allowed",
            "请用健康模型分析我的当前健康画像",
        )

        self.assertIn("基于当前紧凑画像", self._joined_delivery(allowed))
        self.assertEqual(len(analyzer.calls), 1)
        self.assertEqual(analyzer.calls[0][0]["role"], "viewer")

        await self._send_control(
            OWNER,
            "revoke-viewer-analysis",
            "撤回预配置查看者的健康档案查看权限",
        )
        denied = await self._send_control(
            VIEWER,
            "viewer-analysis-revoked",
            "请用健康模型分析我的当前健康画像",
        )
        admin_denied = await self._send_control(
            ADMIN,
            "admin-analysis-denied",
            "请用健康模型分析我的当前健康画像",
        )

        self.assertIn("未获授权", self._joined_delivery(denied))
        self.assertIn("未获授权", self._joined_delivery(admin_denied))
        self.assertEqual(len(analyzer.calls), 1)

    async def test_long_private_view_is_split_into_stable_idempotent_weixin_parts(self):
        class LargeViewSidecar:
            def read_authorized_view(self, *_args, **_kwargs):
                return {"role": "owner", "large_projection": "健" * 5000}

        controls = PartnerOwnerControlHandler(
            LargeViewSidecar(),
            self.signer,
            self.channel,
            expected_owner_sender_id=OWNER,
            expected_viewer_sender_id=VIEWER,
            subject=SUBJECT,
        )
        envelope = TrustedWeixinEnvelope(
            sender_id=OWNER,
            message_id="owner-large-view",
            message_utc=dt.datetime.now(dt.timezone.utc).replace(
                microsecond=0
            ).isoformat(),
            message_text="查看我的完整健康档案",
            channel="weixin",
            profile_name="partner",
        )
        await asyncio.to_thread(controls.handle, envelope)

        parts = [call[1] for call in self.transport.calls]
        client_ids = [call[2] for call in self.transport.calls]
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(0 < len(part) <= 1800 for part in parts))
        self.assertEqual(len(client_ids), len(set(client_ids)))
        payload_parts = [part.split("\n", 1)[1] for part in parts]
        reconstructed = json.loads("".join(payload_parts))
        self.assertEqual(
            reconstructed["health_view"]["large_projection"],
            "健" * 5000,
        )

        await asyncio.to_thread(controls.handle, envelope)
        self.assertEqual(len(self.transport.calls), len(parts))

    async def test_partial_private_view_delivery_never_replays_as_complete(self):
        class RejectSecondPartTransport(_RecordingTransport):
            def send_text(self, recipient: str, message: str, client_id: str):
                self.calls.append((recipient, message, client_id))
                if len(self.calls) == 2:
                    return DeliveryResult.rejected("controlled-second-part-rejection")
                return DeliveryResult.accepted(client_id)

        class LargeViewSidecar:
            def read_authorized_view(self, *_args, **_kwargs):
                return {"role": "owner", "large_projection": "健" * 5000}

        transport = RejectSecondPartTransport()
        channel = WeixinHealthChannel(
            self.root / "partial-delivery.sqlite3",
            transport,
            accepted_hermes_version="test-hermes-v1",
            audit_sink=self.sidecar,
        )
        controls = PartnerOwnerControlHandler(
            LargeViewSidecar(),
            self.signer,
            channel,
            expected_owner_sender_id=OWNER,
            expected_viewer_sender_id=VIEWER,
            subject=SUBJECT,
        )
        envelope = TrustedWeixinEnvelope(
            sender_id=OWNER,
            message_id="owner-partial-view",
            message_utc=dt.datetime.now(dt.timezone.utc).replace(
                microsecond=0
            ).isoformat(),
            message_text="查看我的完整健康档案",
            channel="weixin",
            profile_name="partner",
        )

        first = await asyncio.to_thread(controls.handle, envelope)
        calls_after_first = len(transport.calls)
        second = await asyncio.to_thread(controls.handle, envelope)

        self.assertFalse(first.delivered)
        self.assertFalse(second.delivered)
        self.assertEqual(len(transport.calls), calls_after_first)

    async def test_fresh_no_op_controls_have_no_health_success_marker(self):
        changed = await self._send_control(
            OWNER, "grant-change", "授权预配置查看者查看健康档案"
        )
        self.assertIn("〔健康管家：", self._joined_delivery(changed))

        unchanged = await self._send_control(
            OWNER, "grant-no-op", "再次授权预配置查看者查看健康档案"
        )
        self.assertNotIn("〔健康管家：", self._joined_delivery(unchanged))

        changed = await self._send_control(
            OWNER, "revoke-change", "撤回预配置查看者的健康档案查看权限"
        )
        self.assertIn("〔健康管家：", self._joined_delivery(changed))

        unchanged = await self._send_control(
            OWNER, "revoke-no-op", "再次撤回预配置查看者的健康档案查看权限"
        )
        unchanged_revoke = self._joined_delivery(unchanged)
        self.assertIn("状态未变化", unchanged_revoke)
        self.assertNotIn("〔健康管家：", unchanged_revoke)

        changed = await self._send_control(
            OWNER, "pause-change", "无限期暂停健康提醒"
        )
        self.assertIn("〔健康管家：", self._joined_delivery(changed))

        unchanged = await self._send_control(
            OWNER, "pause-no-op", "继续无限期暂停健康提醒"
        )
        self.assertNotIn("〔健康管家：", self._joined_delivery(unchanged))

        changed = await self._send_control(OWNER, "stop-change", "停止健康记录")
        self.assertIn("〔健康管家：", self._joined_delivery(changed))

        unchanged = await self._send_control(
            OWNER, "stop-no-op", "停止健康记录"
        )
        self.assertNotIn("〔健康管家：", self._joined_delivery(unchanged))

    async def test_invalid_duration_and_negated_command_do_not_change_state(self):
        for message_id, text in (
            ("pause-unsupported-duration", "暂停健康提醒 1 个月"),
            ("pause-overlong-duration", "暂停健康提醒 99999 天"),
            ("pause-leading-zero-duration", "暂停健康提醒 0001 天"),
        ):
            invalid = await self._send_control(OWNER, message_id, text)
            invalid_reply = self._joined_delivery(invalid)
            self.assertIn("状态未更改", invalid_reply)
            self.assertNotIn("〔健康管家：", invalid_reply)

        state_messages = await self._send_control(
            OWNER,
            "view-after-invalid-pause",
            "查看我的健康档案当前状态",
        )
        profile = json.loads(self._joined_delivery(state_messages))["health_view"][
            "profile"
        ]
        self.assertFalse(profile["proactive_contact"]["paused"])

        before = len(self.transport.calls)
        await self._send_event(
            OWNER,
            "negated-recording-stop",
            "请不要停止健康记录",
        )
        for _ in range(200):
            if not self.weixin._background_tasks:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(len(self.transport.calls), before)
        self.assertTrue(self.weixin._pending_text_batches)
        self.assertTrue(self.store.health_recording_enabled(SUBJECT, OWNER))

    async def test_only_unambiguous_positive_commands_can_change_or_disclose(self):
        analyzer = _RecordingAnalyzer()
        self.controls.analyzer = analyzer

        before = len(self.transport.calls)
        for message_id, text in (
            (
                "negated-viewer-grant",
                "我不授权预配置查看者查看我的健康档案",
            ),
            ("negated-analysis", "请勿分析我的健康档案"),
            (
                "compound-control",
                "授权预配置查看者查看健康档案并停止健康记录",
            ),
        ):
            await self._send_event(OWNER, message_id, text)
            for _ in range(200):
                if not self.weixin._background_tasks:
                    break
                await asyncio.sleep(0.01)

        self.assertEqual(len(self.transport.calls), before)
        self.assertEqual(analyzer.calls, [])
        self.assertTrue(self.store.health_recording_enabled(SUBJECT, OWNER))

        denied = await self._send_control(
            VIEWER, "viewer-after-negated-grant", "查看完整健康档案"
        )
        self.assertIn("未获授权", self._joined_delivery(denied))

        query = await self._send_control(
            OWNER, "view-wording-with-stopped", "查看停止后的健康记录"
        )
        self.assertIn("我最近睡不好", self._joined_delivery(query))
        self.assertTrue(self.store.health_recording_enabled(SUBJECT, OWNER))

if __name__ == "__main__":
    unittest.main()

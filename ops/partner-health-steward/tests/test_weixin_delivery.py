from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import (
    ChannelSendUncertainError,
    DeliveryResult,
    HermesWeixinTransport,
    WeixinHealthChannel,
    WeixinVersionMismatchError,
)
from sidecar.weixin_delivery import ProfileDeliveryBlockedError
from sidecar.adapter import PartnerHealthAdapter


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class SidecarDeliveryAuditSinkTests(unittest.TestCase):
    def test_partner_adapter_exposes_only_content_free_idempotent_audit(self):
        client = mock.Mock()
        client.append_delivery_audit_once.return_value = {
            "ok": True,
            "data": {"appended": True},
        }
        adapter = object.__new__(PartnerHealthAdapter)
        adapter._client = client
        details = {
            "actor_role": "weixin-delivery-adapter",
            "action": "weixin.send_once",
            "object_id": "hermes-health-abc123",
            "recipient_id": "wx-owner",
            "result": "sent",
            "reason": "provider-accepted",
        }

        appended = adapter.append_audit_event_once(
            "weixin_delivery_sent:hermes-health-abc123",
            "weixin_delivery_sent",
            details,
        )

        self.assertTrue(appended)
        client.append_delivery_audit_once.assert_called_once_with(
            "weixin_delivery_sent:hermes-health-abc123",
            "weixin_delivery_sent",
            details,
        )


class FailingAfterHandoffClock(FixedClock):
    def __init__(self, now: dt.datetime) -> None:
        super().__init__(now)
        self.calls = 0

    def now_utc(self) -> dt.datetime:
        self.calls += 1
        if self.calls >= 2:
            raise RuntimeError("local-clock-failed-after-handoff")
        return self.now


class ConcurrentStartClock(FixedClock):
    def __init__(self, now: dt.datetime) -> None:
        super().__init__(now)
        self.barrier = threading.Barrier(2)
        self.lock = threading.Lock()
        self.calls = 0

    def now_utc(self) -> dt.datetime:
        with self.lock:
            self.calls += 1
            call_number = self.calls
        if call_number <= 2:
            self.barrier.wait(timeout=5)
        return self.now


class TransportFake:
    runtime_version = "0.20.0"

    def __init__(
        self, results: list[DeliveryResult | BaseException] | None = None
    ) -> None:
        self.text_calls: list[tuple[str, str, str]] = []
        self.attachment_calls: list[tuple[str, Path, str]] = []
        self.results = list(results or [])

    def send_text(
        self, recipient: str, message: str, client_id: str
    ) -> DeliveryResult:
        self.text_calls.append((recipient, message, client_id))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return DeliveryResult.accepted(client_id)

    def send_json_attachment(
        self, recipient: str, attachment_path: Path, client_id: str
    ) -> DeliveryResult:
        self.attachment_calls.append((recipient, attachment_path, client_id))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return DeliveryResult.accepted(client_id)


class AuditFake:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.event_ids: set[str] = set()

    def append_audit_event_once(
        self,
        event_id: str,
        event: str,
        details: dict[str, object],
    ) -> None:
        if event_id in self.event_ids:
            return
        self.event_ids.add(event_id)
        self.events.append((event, dict(details)))


class FailingAuditFake(AuditFake):
    def append_audit_event_once(
        self,
        event_id: str,
        event: str,
        details: dict[str, object],
    ) -> None:
        raise RuntimeError("controlled-audit-outage")


class AsyncSessionFake:
    async def __aenter__(self) -> "AsyncSessionFake":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class HermesWeixinModuleFake:
    ILINK_BASE_URL = "https://weixin.example"
    WEIXIN_CDN_BASE_URL = "https://cdn.weixin.example"
    MEDIA_FILE = 3
    ITEM_FILE = 4
    EP_SEND_MESSAGE = "sendmessage"
    MSG_TYPE_BOT = 2
    MSG_STATE_FINISH = 2
    API_TIMEOUT_MS = 30_000

    def __init__(
        self,
        text_results: list[object | BaseException] | None = None,
        attachment_results: list[object | BaseException] | None = None,
        *,
        block_text: bool = False,
    ) -> None:
        self.text_calls: list[dict[str, object]] = []
        self.upload_url_calls: list[dict[str, object]] = []
        self.upload_calls: list[dict[str, object]] = []
        self.api_calls: list[dict[str, object]] = []
        self.text_results = list(text_results or [])
        self.attachment_results = list(attachment_results or [])
        self.block_text = block_text
        self.text_entered = threading.Event()
        self.text_release = threading.Event()

    @staticmethod
    def _controlled_result(
        results: list[object | BaseException], default: object
    ) -> object:
        result = results.pop(0) if results else default
        if isinstance(result, BaseException):
            raise result
        return result

    async def _send_message(self, _session: object, **kwargs: object) -> object:
        self.text_calls.append(dict(kwargs))
        self.text_entered.set()
        if self.block_text and not self.text_release.wait(timeout=5):
            raise TimeoutError("controlled-network-timeout")
        return self._controlled_result(self.text_results, {"ret": 0})

    async def _get_upload_url(
        self, _session: object, **kwargs: object
    ) -> dict[str, str]:
        self.upload_url_calls.append(dict(kwargs))
        return {"upload_full_url": "https://cdn.weixin.example/upload"}

    async def _upload_ciphertext(
        self, _session: object, **kwargs: object
    ) -> str:
        self.upload_calls.append(dict(kwargs))
        return "encrypted-query"

    @staticmethod
    def _aes_padded_size(raw_size: int) -> int:
        return raw_size + 16

    @staticmethod
    def _aes128_ecb_encrypt(plaintext: bytes, _key: bytes) -> bytes:
        return b"encrypted:" + plaintext

    async def _api_post(self, _session: object, **kwargs: object) -> object:
        self.api_calls.append(dict(kwargs))
        return self._controlled_result(self.attachment_results, {"ret": 0})


def _production_transport(
    weixin: HermesWeixinModuleFake,
    *,
    runtime_version: str = "0.20.0",
) -> HermesWeixinTransport:
    return HermesWeixinTransport(
        weixin,
        runtime_version=runtime_version,
        token="controlled-secret-token",
        base_url="https://weixin.example",
        session_factory=AsyncSessionFake,
    )


class WeixinHealthChannelTests(unittest.TestCase):
    def test_profile_deletion_guard_purges_scoped_delivery_state_and_requires_terminal_notice_api(
        self,
    ) -> None:
        """A confirmed profile deletion revokes old delivery state without storing content."""
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            ledger_path = root_path / "delivery.sqlite3"
            transport = TransportFake()
            legacy_channel = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=AuditFake(),
            )
            self.assertTrue(
                legacy_channel.send_once(
                    "owner-1", "迁移前的健康投递正文", "health-task:legacy"
                )
            )
            channel = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=AuditFake(),
                profile_subject="profile-owner-42",
            )

            self.assertTrue(
                channel.send_once(
                    "owner-1",
                    "删除前的健康投递正文",
                    "health-task:before-delete",
                )
            )
            self.assertTrue(
                channel.send_text_parts_once(
                    "owner-1",
                    ("删除前的健康批次正文",),
                    "health-view:before-delete",
                )
            )
            self.assertEqual(channel.profile_deletion_status(), "active")

            self.assertTrue(
                channel.prepare_profile_deletion(
                    "health-delete:confirmed:receipt-2"
                )
            )
            self.assertEqual(channel.profile_deletion_status(), "prepared")
            with self.assertRaisesRegex(
                ProfileDeliveryBlockedError, "profile-delivery-blocked"
            ):
                channel.send_once(
                    "owner-1",
                    "准备删除后不得投递",
                    "health-task:during-delete",
                )
            with self.assertRaisesRegex(
                ProfileDeliveryBlockedError, "profile-delivery-blocked"
            ):
                channel.send_text_parts_once(
                    "owner-1",
                    ("错误的删除终态通知",),
                    "health-delete:wrong-receipt",
                )
            with self.assertRaisesRegex(
                ProfileDeliveryBlockedError, "profile-delivery-blocked"
            ):
                channel.send_text_parts_once(
                    "owner-1",
                    ("删除尚未完成，不得发送终态通知。",),
                    "health-delete:confirmed:receipt-2",
                )
            with self.assertRaisesRegex(ValueError, "terminal-key-mismatch"):
                channel.prepare_profile_deletion("health-delete:other-receipt")

            self.assertTrue(channel.complete_profile_deletion())
            self.assertEqual(channel.profile_deletion_status(), "deleted")
            with self.assertRaises(KeyError):
                channel.delivery_status("health-task:before-delete")
            with self.assertRaises(KeyError):
                channel.delivery_batch_status("health-view:before-delete")
            with self.assertRaises(KeyError):
                legacy_channel.delivery_status("health-task:legacy")
            with self.assertRaisesRegex(
                ProfileDeliveryBlockedError, "profile-delivery-blocked"
            ):
                channel.send_once(
                    "owner-1",
                    "删除后不得投递",
                    "health-task:after-delete",
                )

            terminal_key = "health-delete:confirmed:receipt-2"
            with self.assertRaisesRegex(
                ProfileDeliveryBlockedError, "profile-delivery-blocked"
            ):
                channel.send_text_parts_once(
                    "owner-1",
                    ("删除已确认；已发送或导出的外部副本无法召回。",),
                    terminal_key,
                )
            self.assertTrue(
                channel.send_profile_deletion_notice_once(
                    "owner-1",
                    ("删除已确认；已发送或导出的外部副本无法召回。",),
                    terminal_key,
                )
            )
            self.assertTrue(
                channel.send_profile_deletion_notice_once(
                    "owner-1",
                    ("删除已确认；已发送或导出的外部副本无法召回。",),
                    terminal_key,
                )
            )
            self.assertEqual(len(transport.text_calls), 4)
            with self.assertRaises(KeyError):
                channel.delivery_status(
                    f"{terminal_key}:terminal:0001-of-0001"
                )
            with self.assertRaises(KeyError):
                channel.delivery_batch_status(terminal_key)

            with closing(sqlite3.connect(ledger_path)) as connection:
                rows = connection.execute(
                    "SELECT scope_id FROM deliveries UNION ALL "
                    "SELECT scope_id FROM delivery_batches"
                ).fetchall()
            self.assertEqual(rows, [])
            persisted = ledger_path.read_bytes()
            self.assertNotIn(b"profile-owner-42", persisted)
            self.assertNotIn("迁移前的健康投递正文".encode("utf-8"), persisted)
            self.assertNotIn("删除前的健康投递正文".encode("utf-8"), persisted)
            self.assertNotIn("删除前的健康批次正文".encode("utf-8"), persisted)

    def test_prepared_profile_deletion_can_be_cancelled_without_losing_delivery_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            channel = WeixinHealthChannel(
                Path(root) / "delivery.sqlite3",
                TransportFake(),
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=AuditFake(),
                profile_subject="profile-owner-42",
            )
            self.assertTrue(
                channel.send_once(
                    "owner-1", "删除失败前的投递", "health-task:retain"
                )
            )

            self.assertTrue(
                channel.prepare_profile_deletion("health-delete:receipt-2")
            )
            self.assertTrue(channel.cancel_profile_deletion())
            self.assertEqual(channel.profile_deletion_status(), "active")
            self.assertEqual(
                channel.delivery_status("health-task:retain")["status"], "sent"
            )
            self.assertTrue(
                channel.send_once(
                    "owner-1", "删除未完成后的投递", "health-task:after-cancel"
                )
            )

    def test_confirmed_deletion_notice_is_idempotent_without_regular_delivery_state_or_audit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            transport = TransportFake()
            audit = AuditFake()
            channel = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=audit,
                profile_subject="profile-owner-42",
            )
            terminal_key = "health-delete:confirmed:receipt-2"
            self.assertTrue(channel.prepare_profile_deletion(terminal_key))
            self.assertTrue(channel.complete_profile_deletion())

            with self.assertRaisesRegex(
                ProfileDeliveryBlockedError, "profile-deletion-notice-blocked"
            ):
                channel.send_profile_deletion_notice_once(
                    "owner-1",
                    ("删除已确认。",),
                    "health-delete:wrong-receipt",
                )
            self.assertEqual(transport.text_calls, [])

            messages = ("删除已确认；已发送或导出的外部副本无法召回。",)
            self.assertTrue(
                channel.send_profile_deletion_notice_once(
                    "owner-1", messages, terminal_key
                )
            )
            self.assertTrue(
                channel.send_profile_deletion_notice_once(
                    "owner-1", messages, terminal_key
                )
            )
            self.assertEqual(len(transport.text_calls), 1)
            self.assertEqual(audit.events, [])
            with self.assertRaises(KeyError):
                channel.delivery_status(
                    f"{terminal_key}:terminal:0001-of-0001"
                )
            with self.assertRaises(KeyError):
                channel.delivery_batch_status(terminal_key)

            with closing(sqlite3.connect(ledger_path)) as connection:
                delivery_count = connection.execute(
                    "SELECT COUNT(*) FROM deliveries"
                ).fetchone()[0]
                batch_count = connection.execute(
                    "SELECT COUNT(*) FROM delivery_batches"
                ).fetchone()[0]
                terminal_status = connection.execute(
                    "SELECT terminal_status FROM profile_deletion_guards"
                ).fetchone()[0]
            self.assertEqual(delivery_count, 0)
            self.assertEqual(batch_count, 0)
            self.assertEqual(terminal_status, "sent")
            persisted = ledger_path.read_bytes()
            self.assertNotIn(b"profile-owner-42", persisted)
            self.assertNotIn(messages[0].encode("utf-8"), persisted)

    def test_recovery_notice_reuses_the_tombstone_without_recreating_delivery_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            transport = TransportFake()
            audit = AuditFake()
            channel = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=audit,
                profile_subject="profile-owner-42",
            )
            terminal_key = "health-delete:confirmed:receipt-2"
            messages = ("健康档案已永久删除。",)
            self.assertTrue(channel.prepare_profile_deletion(terminal_key))
            self.assertTrue(channel.complete_profile_deletion())

            # The owner-control seam authenticates the explicit retry.  The
            # channel consumes only the tombstone hash retained from the
            # original confirmation, never a new ordinary delivery key.
            self.assertTrue(
                channel.recover_profile_deletion_notice_once("owner-1", messages)
            )
            self.assertTrue(
                channel.recover_profile_deletion_notice_once("owner-1", messages)
            )
            self.assertEqual(len(transport.text_calls), 1)
            self.assertEqual(audit.events, [])
            with self.assertRaises(KeyError):
                channel.delivery_status("health-delete:recovery:receipt-3")
            with self.assertRaises(KeyError):
                channel.delivery_batch_status("health-delete:recovery:receipt-3")

            persisted = ledger_path.read_bytes()
            self.assertNotIn(b"profile-owner-42", persisted)
            self.assertNotIn(messages[0].encode("utf-8"), persisted)

    def test_uncertain_deletion_notice_is_terminal_and_never_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            transport = TransportFake(
                [DeliveryResult.uncertain("network-confirmation-missing")]
            )
            audit = AuditFake()
            channel = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=audit,
                profile_subject="profile-owner-42",
            )
            terminal_key = "health-delete:confirmed:receipt-2"
            channel.prepare_profile_deletion(terminal_key)
            channel.complete_profile_deletion()

            with self.assertRaisesRegex(
                ChannelSendUncertainError, "channel-send-uncertain"
            ):
                channel.send_profile_deletion_notice_once(
                    "owner-1", ("删除已确认。",), terminal_key
                )
            with self.assertRaisesRegex(
                ChannelSendUncertainError, "channel-send-uncertain"
            ):
                channel.send_profile_deletion_notice_once(
                    "owner-1", ("删除已确认。",), terminal_key
                )
            self.assertEqual(len(transport.text_calls), 1)
            self.assertEqual(audit.events, [])

            with closing(sqlite3.connect(ledger_path)) as connection:
                delivery_count = connection.execute(
                    "SELECT COUNT(*) FROM deliveries"
                ).fetchone()[0]
                batch_count = connection.execute(
                    "SELECT COUNT(*) FROM delivery_batches"
                ).fetchone()[0]
                terminal_status = connection.execute(
                    "SELECT terminal_status FROM profile_deletion_guards"
                ).fetchone()[0]
            self.assertEqual(delivery_count, 0)
            self.assertEqual(batch_count, 0)
            self.assertEqual(terminal_status, "uncertain")

    def test_profile_scoped_normal_delivery_audit_binds_subject_without_ledger_copy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            audit = AuditFake()
            channel = WeixinHealthChannel(
                ledger_path,
                TransportFake(),
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=audit,
                profile_subject="profile-owner-42",
            )

            self.assertTrue(
                channel.send_once(
                    "owner-1", "仅用于审计绑定的正常健康投递", "health-task:subject"
                )
            )

            self.assertEqual(audit.events[0][1]["subject"], "profile-owner-42")
            persisted = ledger_path.read_bytes()
            self.assertNotIn(b"profile-owner-42", persisted)
            self.assertNotIn("仅用于审计绑定的正常健康投递".encode("utf-8"), persisted)

    def test_legacy_non_idempotent_send_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            weixin = HermesWeixinModuleFake()
            channel = WeixinHealthChannel(
                Path(root) / "delivery.sqlite3",
                _production_transport(weixin),
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=AuditFake(),
            )

            with self.assertRaisesRegex(
                RuntimeError, "non-idempotent-weixin-send-disabled"
            ):
                channel.send("owner-1", "health-message")

            self.assertEqual(weixin.text_calls, [])

    def test_repeated_delivery_uses_one_stable_weixin_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            weixin = HermesWeixinModuleFake()
            transport = _production_transport(weixin)
            audit = AuditFake()
            channel = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=audit,
            )

            self.assertTrue(
                channel.send_once("owner-1", "今晚记得关注睡眠状态", "health-task:profile:t1")
            )
            self.assertTrue(
                channel.send_once("owner-1", "今晚记得关注睡眠状态", "health-task:profile:t1")
            )

            self.assertEqual(len(weixin.text_calls), 1)
            self.assertEqual(
                weixin.text_calls[0]["client_id"],
                "hermes-health-ac605d85fe08a44eb1e9788d99138856",
            )
            status = channel.delivery_status("health-task:profile:t1")
            self.assertEqual(status["status"], "sent")
            self.assertEqual(status["recipient_id"], "owner-1")
            self.assertNotIn("message", status)
            self.assertEqual(
                audit.events,
                [
                    (
                        "weixin_delivery_sent",
                        {
                            "actor_role": "weixin-delivery-adapter",
                            "action": "weixin.send_once",
                            "object_id": status["delivery_id"],
                            "recipient_id": "owner-1",
                            "result": "sent",
                            "reason": "provider-accepted",
                        },
                    )
                ],
            )
            self.assertNotIn("今晚记得关注睡眠状态".encode("utf-8"), ledger_path.read_bytes())

    def test_uncertain_handoff_is_terminal_and_emits_content_free_audit(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            weixin = HermesWeixinModuleFake(text_results=[{}])
            transport = _production_transport(weixin)
            audit = AuditFake()
            channel = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=audit,
            )

            with self.assertRaisesRegex(
                ChannelSendUncertainError, "channel-send-uncertain"
            ):
                channel.send_once(
                    "owner-1", "这段健康正文不能进入审计", "health-task:profile:t2"
                )
            with self.assertRaisesRegex(
                ChannelSendUncertainError, "channel-send-uncertain"
            ):
                channel.send_once(
                    "owner-1", "这段健康正文不能进入审计", "health-task:profile:t2"
                )

            self.assertEqual(len(weixin.text_calls), 1)
            status = channel.delivery_status("health-task:profile:t2")
            self.assertEqual(status["status"], "uncertain")
            self.assertEqual(status["error_code"], "provider-confirmation-missing")
            self.assertEqual(
                audit.events,
                [
                    (
                        "weixin_delivery_uncertain",
                        {
                            "actor_role": "weixin-delivery-adapter",
                            "action": "weixin.send_once",
                            "object_id": status["delivery_id"],
                            "recipient_id": "owner-1",
                            "result": "uncertain",
                            "reason": "provider-confirmation-missing",
                        },
                    )
                ],
            )
            serialized = ledger_path.read_bytes() + repr(audit.events).encode("utf-8")
            self.assertNotIn("这段健康正文不能进入审计".encode("utf-8"), serialized)

    def test_transport_exception_becomes_fixed_uncertain_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            weixin = HermesWeixinModuleFake(
                text_results=[TimeoutError("敏感正文不应出现在错误记录中")]
            )
            transport = _production_transport(weixin)
            audit = AuditFake()
            channel = WeixinHealthChannel(
                Path(root) / "delivery.sqlite3",
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=audit,
            )

            with self.assertRaisesRegex(
                ChannelSendUncertainError, "channel-send-uncertain"
            ):
                channel.send_once(
                    "owner-1", "健康消息正文", "health-task:profile:timeout"
                )

            status = channel.delivery_status("health-task:profile:timeout")
            self.assertEqual(status["status"], "uncertain")
            self.assertEqual(status["error_code"], "transport-exception")
            self.assertEqual(audit.events[0][1]["reason"], "transport-exception")
            persisted = (Path(root) / "delivery.sqlite3").read_bytes()
            self.assertNotIn("敏感正文".encode("utf-8"), persisted)
            self.assertNotIn("健康消息正文".encode("utf-8"), persisted)

    def test_transport_error_text_is_replaced_by_a_fixed_code(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            audit = AuditFake()
            channel = WeixinHealthChannel(
                ledger_path,
                TransportFake([DeliveryResult.uncertain("睡眠情况详细描述")]),
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=audit,
            )

            with self.assertRaises(ChannelSendUncertainError):
                channel.send_once(
                    "owner-1", "健康消息正文", "health-task:profile:bad-error"
                )

            status = channel.delivery_status("health-task:profile:bad-error")
            self.assertEqual(status["error_code"], "invalid-transport-error-code")
            self.assertEqual(
                audit.events[0][1]["reason"], "invalid-transport-error-code"
            )
            serialized = ledger_path.read_bytes() + repr(audit.events).encode("utf-8")
            self.assertNotIn("睡眠情况详细描述".encode("utf-8"), serialized)

    def test_post_handoff_local_failure_is_terminal_and_never_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            audit = AuditFake()
            weixin = HermesWeixinModuleFake()
            transport = _production_transport(weixin)
            channel = WeixinHealthChannel(
                Path(root) / "delivery.sqlite3",
                transport,
                accepted_hermes_version="0.20.0",
                clock=FailingAfterHandoffClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=audit,
            )

            with self.assertRaisesRegex(
                ChannelSendUncertainError, "channel-send-uncertain"
            ):
                channel.send_once(
                    "owner-1", "已发送但状态提交失败", "health-task:profile:state-fail"
                )
            with self.assertRaisesRegex(
                ChannelSendUncertainError, "channel-send-uncertain"
            ):
                channel.send_once(
                    "owner-1", "已发送但状态提交失败", "health-task:profile:state-fail"
                )

            self.assertEqual(len(weixin.text_calls), 1)
            status = channel.delivery_status("health-task:profile:state-fail")
            self.assertEqual(status["status"], "uncertain")
            self.assertEqual(status["error_code"], "post-handoff-state-failure")
            self.assertEqual(audit.events[0][1]["reason"], "post-handoff-state-failure")

    def test_sent_delivery_recovers_a_missing_audit_without_network_replay(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            weixin = HermesWeixinModuleFake()
            transport = _production_transport(weixin)
            first = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=FailingAuditFake(),
            )

            with self.assertRaisesRegex(
                ChannelSendUncertainError, "channel-send-uncertain"
            ):
                first.send_once(
                    "owner-1",
                    "health-message",
                    "health-task:profile:audit-recovery",
                )
            self.assertEqual(len(weixin.text_calls), 1)
            self.assertEqual(
                first.delivery_status("health-task:profile:audit-recovery")[
                    "status"
                ],
                "sent_audit_pending",
            )

            recovered_audit = AuditFake()
            recovered = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 1, tzinfo=dt.timezone.utc)
                ),
                audit_sink=recovered_audit,
            )

            self.assertTrue(
                recovered.send_once(
                    "owner-1",
                    "health-message",
                    "health-task:profile:audit-recovery",
                )
            )
            self.assertEqual(len(weixin.text_calls), 1)
            self.assertEqual(
                recovered.delivery_status("health-task:profile:audit-recovery")[
                    "status"
                ],
                "sent",
            )
            self.assertEqual(
                [event[0] for event in recovered_audit.events],
                ["weixin_delivery_sent"],
            )

    def test_uncertain_delivery_recovers_a_missing_audit_without_network_replay(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            weixin = HermesWeixinModuleFake(text_results=[{}])
            transport = _production_transport(weixin)
            first = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=FailingAuditFake(),
            )

            with self.assertRaises(ChannelSendUncertainError):
                first.send_once(
                    "owner-1",
                    "health-message",
                    "health-task:profile:uncertain-audit-recovery",
                )
            self.assertEqual(len(weixin.text_calls), 1)
            self.assertEqual(
                first.delivery_status(
                    "health-task:profile:uncertain-audit-recovery"
                )["status"],
                "uncertain_audit_pending",
            )

            recovered_audit = AuditFake()
            recovered = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 1, tzinfo=dt.timezone.utc)
                ),
                audit_sink=recovered_audit,
            )

            with self.assertRaises(ChannelSendUncertainError):
                recovered.send_once(
                    "owner-1",
                    "health-message",
                    "health-task:profile:uncertain-audit-recovery",
                )
            self.assertEqual(len(weixin.text_calls), 1)
            self.assertEqual(
                recovered.delivery_status(
                    "health-task:profile:uncertain-audit-recovery"
                )["status"],
                "uncertain",
            )
            self.assertEqual(
                [event[0] for event in recovered_audit.events],
                ["weixin_delivery_uncertain"],
            )

    def test_concurrent_same_delivery_never_hands_off_twice(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            weixin = HermesWeixinModuleFake(block_text=True)
            transport = _production_transport(weixin)
            audit = AuditFake()
            clock = ConcurrentStartClock(
                dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
            )
            first = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=clock,
                audit_sink=audit,
            )
            second = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=clock,
                audit_sink=audit,
            )
            outcomes: list[str] = []

            def deliver(channel: WeixinHealthChannel) -> None:
                try:
                    outcomes.append(
                        "sent"
                        if channel.send_once(
                            "owner-1",
                            "controlled-health-message",
                            "health-task:profile:concurrent",
                        )
                        else "rejected"
                    )
                except ChannelSendUncertainError:
                    outcomes.append("uncertain")
                except Exception as exc:
                    outcomes.append(type(exc).__name__)

            first_thread = threading.Thread(target=deliver, args=(first,))
            second_thread = threading.Thread(target=deliver, args=(second,))
            second_thread.start()
            first_thread.start()
            self.assertTrue(weixin.text_entered.wait(timeout=5))
            weixin.text_release.set()
            first_thread.join(timeout=5)
            second_thread.join(timeout=5)
            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())

            self.assertEqual(len(outcomes), 2)
            self.assertIn("sent", outcomes)
            self.assertTrue(
                all(outcome in {"sent", "uncertain"} for outcome in outcomes)
            )
            self.assertEqual(len(weixin.text_calls), 1)
            self.assertEqual([event[0] for event in audit.events], ["weixin_delivery_sent"])

    def test_untrusted_provider_message_id_is_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            transport = TransportFake(
                [DeliveryResult.accepted("untrusted-health-text")]
            )
            channel = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=AuditFake(),
            )

            self.assertTrue(
                channel.send_once(
                    "owner-1",
                    "controlled-health-message",
                    "health-task:profile:provider-id",
                )
            )

            status = channel.delivery_status("health-task:profile:provider-id")
            self.assertEqual(
                status["provider_message_id"], transport.text_calls[0][2]
            )
            self.assertNotIn(b"untrusted-health-text", ledger_path.read_bytes())

    def test_provider_rejection_is_persisted_without_repeat_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            weixin = HermesWeixinModuleFake(text_results=[{"ret": 17}])
            transport = _production_transport(weixin)
            audit = AuditFake()
            channel = WeixinHealthChannel(
                Path(root) / "delivery.sqlite3",
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=audit,
            )

            self.assertFalse(
                channel.send_once("owner-1", "不会保存的正文", "health-task:profile:reject")
            )
            self.assertFalse(
                channel.send_once("owner-1", "不会保存的正文", "health-task:profile:reject")
            )

            self.assertEqual(len(weixin.text_calls), 1)
            status = channel.delivery_status("health-task:profile:reject")
            self.assertEqual(status["status"], "rejected")
            self.assertEqual(status["error_code"], "provider-rejected")
            self.assertEqual(audit.events[0][0], "weixin_delivery_rejected")
            self.assertNotIn("不会保存的正文", repr(audit.events))

    def test_process_recovery_never_replays_an_inflight_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            first_audit = AuditFake()
            crashing_weixin = HermesWeixinModuleFake(
                text_results=[SystemExit("simulated-process-stop")]
            )
            crashing = _production_transport(crashing_weixin)
            first = WeixinHealthChannel(
                ledger_path,
                crashing,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=first_audit,
            )
            with self.assertRaises(SystemExit):
                first.send_once(
                    "owner-1", "进程中断时不能重发", "health-task:profile:crash"
                )

            recovered_audit = AuditFake()
            recovered_weixin = HermesWeixinModuleFake()
            after_restart = _production_transport(recovered_weixin)
            pending_recovery = WeixinHealthChannel(
                ledger_path,
                after_restart,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 1, tzinfo=dt.timezone.utc)
                ),
                audit_sink=FailingAuditFake(),
            )
            self.assertEqual(
                pending_recovery.delivery_status("health-task:profile:crash")[
                    "status"
                ],
                "uncertain_audit_pending",
            )
            recovered = WeixinHealthChannel(
                ledger_path,
                after_restart,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 1, tzinfo=dt.timezone.utc)
                ),
                audit_sink=recovered_audit,
            )
            with self.assertRaisesRegex(
                ChannelSendUncertainError, "channel-send-uncertain"
            ):
                recovered.send_once(
                    "owner-1", "进程中断时不能重发", "health-task:profile:crash"
                )

            self.assertEqual(recovered_weixin.text_calls, [])
            status = recovered.delivery_status("health-task:profile:crash")
            self.assertEqual(status["status"], "uncertain")
            self.assertEqual(status["error_code"], "interrupted-before-confirmation")
            self.assertEqual(recovered_audit.events[0][0], "weixin_delivery_uncertain")

    def test_json_attachment_uses_the_same_persistent_idempotency_contract(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            ledger_path = root_path / "delivery.sqlite3"
            attachment = root_path / "health-export.json"
            attachment.write_text(
                '{"private_health_text":"不能进入投递账本"}', encoding="utf-8"
            )
            weixin = HermesWeixinModuleFake()
            transport = _production_transport(weixin)
            channel = WeixinHealthChannel(
                ledger_path,
                transport,
                accepted_hermes_version="0.20.0",
                clock=FixedClock(
                    dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                ),
                audit_sink=AuditFake(),
            )

            self.assertTrue(
                channel.send_json_attachment_once(
                    "owner-1", attachment, "health-export:profile:v3"
                )
            )
            attachment.unlink()
            self.assertTrue(
                channel.send_json_attachment_once(
                    "owner-1", attachment, "health-export:profile:v3"
                )
            )

            self.assertEqual(len(weixin.api_calls), 1)
            self.assertEqual(
                weixin.api_calls[0]["payload"]["msg"]["client_id"],
                "hermes-health-dbec698d23922ffa83633b95e157da99",
            )
            persisted = ledger_path.read_bytes()
            self.assertNotIn("不能进入投递账本".encode("utf-8"), persisted)
            self.assertNotIn(str(attachment).encode("utf-8"), persisted)

    def test_unaccepted_hermes_version_fails_before_state_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger_path = Path(root) / "delivery.sqlite3"
            weixin = HermesWeixinModuleFake()
            transport = _production_transport(weixin, runtime_version="0.21.0")

            with self.assertRaisesRegex(
                WeixinVersionMismatchError, "hermes-weixin-version-mismatch"
            ):
                WeixinHealthChannel(
                    ledger_path,
                    transport,
                    accepted_hermes_version="0.20.0",
                    clock=FixedClock(
                        dt.datetime(2026, 8, 9, 8, 0, tzinfo=dt.timezone.utc)
                    ),
                    audit_sink=AuditFake(),
                )

            self.assertFalse(ledger_path.exists())
            self.assertEqual(weixin.text_calls, [])
            self.assertEqual(weixin.api_calls, [])

    def test_hermes_transport_passes_stable_client_id_to_ilink(self) -> None:
        weixin = HermesWeixinModuleFake()
        transport = HermesWeixinTransport(
            weixin,
            runtime_version="0.20.0",
            token="secret-token",
            base_url="https://weixin.example",
            session_factory=AsyncSessionFake,
        )

        result = transport.send_text(
            "owner-1", "health message", "hermes-health-fixed-client-id"
        )

        self.assertEqual(
            result,
            DeliveryResult.accepted("hermes-health-fixed-client-id"),
        )
        self.assertEqual(len(weixin.text_calls), 1)
        call = weixin.text_calls[0]
        self.assertEqual(call["to"], "owner-1")
        self.assertEqual(call["text"], "health message")
        self.assertEqual(call["client_id"], "hermes-health-fixed-client-id")
        self.assertIsNone(call["context_token"])

    def test_hermes_transport_uses_stable_client_id_for_json_attachment_message(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            attachment = Path(root) / "health-export.json"
            attachment.write_text('{"schema_version":1}', encoding="utf-8")
            weixin = HermesWeixinModuleFake()
            transport = HermesWeixinTransport(
                weixin,
                runtime_version="0.20.0",
                token="secret-token",
                base_url="https://weixin.example",
                session_factory=AsyncSessionFake,
            )

            result = transport.send_json_attachment(
                "owner-1", attachment, "hermes-health-fixed-attachment-id"
            )

            self.assertEqual(
                result,
                DeliveryResult.accepted("hermes-health-fixed-attachment-id"),
            )
            self.assertEqual(len(weixin.upload_url_calls), 1)
            self.assertEqual(len(weixin.upload_calls), 1)
            self.assertEqual(len(weixin.api_calls), 1)
            payload = weixin.api_calls[0]["payload"]
            message = payload["msg"]
            self.assertEqual(
                message["client_id"], "hermes-health-fixed-attachment-id"
            )
            file_item = message["item_list"][0]["file_item"]
            self.assertEqual(file_item["file_name"], "health-export.json")
            self.assertEqual(file_item["len"], str(attachment.stat().st_size))

    def test_production_transport_loads_the_runtime_from_the_pinned_source_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            source_root = Path(root) / "hermes-source"
            source_root.mkdir()
            weixin = HermesWeixinModuleFake()
            seen: list[Path] = []

            def loader(path: Path) -> tuple[str, HermesWeixinModuleFake]:
                seen.append(path)
                return "0.20.0", weixin

            transport = HermesWeixinTransport.from_hermes_source(
                source_root,
                token="secret-token",
                module_loader=loader,
                session_factory=AsyncSessionFake,
            )

            self.assertEqual(seen, [source_root.resolve()])
            self.assertEqual(transport.runtime_version, "0.20.0")
            self.assertIs(transport.weixin, weixin)


if __name__ == "__main__":
    unittest.main()

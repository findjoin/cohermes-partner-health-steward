from __future__ import annotations

import datetime as dt
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sidecar.adapter import PartnerHealthAdapter
from sidecar.health_turn_context import compose_health_turn_context
from sidecar.profile import MAX_SUMMARY_CHARS
from sidecar.protocol import (
    ACTION_HEALTH_TURN_CONTEXT_READ,
    HEALTH_TURN_CONTEXT_EVIDENCE_KIND,
    SidecarProtocolError,
    parse_request,
)
from sidecar.receipt_signer import Ed25519ReceiptSigner
from sidecar.server import HealthSidecarServer
from sidecar.sources import SourceLibrary
from sidecar.store import (
    Ed25519InboundMessageVerifier,
    HealthSidecarStore,
    HmacInboundMessageVerifier,
)


OWNER = "wx-owner"
SUBJECT = "profile"
CONTEXT_FIELDS = {
    "context_schema_version",
    "current_version_id",
    "profile_summary_zh",
    "evidence_ids",
    "source_cards",
    "source_status",
}
PUBLIC_SOURCE_CARD_FIELDS = {
    "card_id",
    "url",
    "source_type",
    "title",
    "version_hash",
    "key_excerpt",
    "tags",
    "fetched_utc",
    "review_due_utc",
    "untrusted_data",
}


class FixedClock:
    def __init__(self, value: dt.datetime) -> None:
        self.value = value

    def now_utc(self) -> dt.datetime:
        return self.value


def _tags() -> dict[str, list[str]]:
    return {
        "topic": ["sleep"],
        "symptom_behavior": ["insomnia"],
        "target_population": ["adult"],
        "evidence_type": ["guideline"],
        "region_language": ["global-en"],
        "freshness": ["current"],
    }


class HealthTurnContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = FixedClock(
            dt.datetime(2026, 8, 9, 2, 0, tzinfo=dt.timezone.utc)
        )
        self.verifier = HmacInboundMessageVerifier(b"r" * 32)
        self.store = HealthSidecarStore(
            self.root / "health.state",
            self.root / "health.key",
            clock=self.clock,
            message_verifier=self.verifier,
            expected_owner_sender_id=OWNER,
        )
        self._enable_recording()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _enable_recording(self) -> None:
        now = self.clock.now_utc().isoformat()
        token = self.verifier.sign_access_receipt(
            action="health.recording.enable",
            subject=SUBJECT,
            actor_sender_id=OWNER,
            target_sender_id=OWNER,
            message_id="consent-1",
            message_utc=now,
        )
        self.store.enable_health_recording(
            SUBJECT, OWNER, "consent-1", now, token
        )

    def _admit(self, index: int) -> dict:
        self.clock.value += dt.timedelta(seconds=1)
        message_id = f"health-{index}"
        message_utc = self.clock.now_utc().isoformat()
        text = f"我最近睡眠第{index}次不好"
        candidate = {
            "evidence_kind": "direct_statement",
            "source_message_id": message_id,
            "source_utc": message_utc,
            "excerpt": text,
            "measurement": None,
            "conclusions": [
                {
                    "category": "state",
                    "dedupe_key": "sleep-quality",
                    "text": f"睡眠第{index}次不好",
                    "status": "fact",
                    "priority": 3,
                }
            ],
        }
        token = self.verifier.sign_ingress_receipt(
            action="health.profile.message.admit",
            subject=SUBJECT,
            sender_id=OWNER,
            message_id=message_id,
            message_utc=message_utc,
            message_text=text,
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
            attempt_utc=message_utc,
        )
        return dict(
            self.store.admit_consented_profile_candidate(
                subject=SUBJECT,
                sender_id=OWNER,
                message_id=message_id,
                message_utc=message_utc,
                attempt_utc=message_utc,
                message_text=text,
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
                verification_token=token,
                candidate=candidate,
            )
        )

    def _context_request(
        self,
        message_text: str = "sleep",
        *,
        message_id: str = "question-1",
    ) -> dict[str, str]:
        message_utc = self.clock.now_utc().isoformat()
        payload = {
            "subject": SUBJECT,
            "sender_id": OWNER,
            "message_id": message_id,
            "message_utc": message_utc,
            "message_text": message_text,
            "channel": "weixin",
            "profile_name": "partner",
            "attempt_utc": message_utc,
        }
        payload["verification_token"] = self.verifier.sign_ingress_receipt(
            action=ACTION_HEALTH_TURN_CONTEXT_READ,
            evidence_kind=HEALTH_TURN_CONTEXT_EVIDENCE_KIND,
            **payload,
        )
        return payload

    def test_protocol_accepts_only_the_receipt_bound_trusted_envelope(self):
        payload = self._context_request()
        request = parse_request(
            json.dumps(
                {
                    "req_id": "context-1",
                    "action": ACTION_HEALTH_TURN_CONTEXT_READ,
                    "payload": payload,
                }
            ).encode("utf-8")
        )
        self.assertEqual(request.action, ACTION_HEALTH_TURN_CONTEXT_READ)

        payload["candidate"] = {"forbidden": True}
        with self.assertRaisesRegex(
            SidecarProtocolError, "health-turn-context-fields-unsupported"
        ):
            parse_request(
                json.dumps(
                    {
                        "req_id": "context-extra",
                        "action": ACTION_HEALTH_TURN_CONTEXT_READ,
                        "payload": payload,
                    }
                ).encode("utf-8")
            )

    def test_receipt_signer_allows_the_narrow_context_action(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        private_key = Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        public_bytes = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        signer = Ed25519ReceiptSigner(private_bytes)
        payload = self._context_request()
        payload.pop("verification_token")
        token = signer.sign_ingress(
            action=ACTION_HEALTH_TURN_CONTEXT_READ,
            evidence_kind=HEALTH_TURN_CONTEXT_EVIDENCE_KIND,
            **payload,
        )

        self.assertTrue(
            Ed25519InboundMessageVerifier(public_bytes).verify_ingress_receipt(
                action=ACTION_HEALTH_TURN_CONTEXT_READ,
                evidence_kind=HEALTH_TURN_CONTEXT_EVIDENCE_KIND,
                token=token,
                **payload,
            )
        )

    def test_profile_projection_is_post_write_current_and_evidence_is_bounded(self):
        admissions = [self._admit(index) for index in range(1, 6)]
        request = self._context_request(
            "我最近睡眠第5次不好", message_id="health-5"
        )

        result = self.store.read_health_turn_context(**request)

        self.assertEqual(set(result), {
            "context_schema_version",
            "current_version_id",
            "profile_summary_zh",
            "evidence_ids",
        })
        self.assertEqual(result["context_schema_version"], 1)
        self.assertEqual(result["current_version_id"], admissions[-1]["version_id"])
        self.assertEqual(result["profile_summary_zh"], "睡眠第5次不好")
        self.assertLessEqual(len(result["profile_summary_zh"]), MAX_SUMMARY_CHARS)
        self.assertEqual(
            result["evidence_ids"],
            [item["evidence_id"] for item in admissions[-3:]],
        )

        with self.assertRaisesRegex(
            Exception, "access-receipt-replayed"
        ):
            self.store.read_health_turn_context(**request)

    def test_unlinked_question_does_not_receive_unrelated_evidence_ids(self):
        self._admit(1)

        question = self.store.read_health_turn_context(
            **self._context_request("睡眠第1次不好", message_id="question-new")
        )

        self.assertEqual(question["profile_summary_zh"], "睡眠第1次不好")
        self.assertEqual(question["evidence_ids"], [])

    def test_source_projection_exposes_only_fresh_public_fields(self):
        library = SourceLibrary(self.store, cache_dir=self.root / "source-cache")
        card = library.ingest(
            {
                "url": "https://www.who.int/sleep",
                "source_type": "clinical_guideline",
                "title": "Sleep guidance",
                "tags": _tags(),
                "key_excerpt": "Sleep hygiene guidance.",
                "raw_document": b"private cached source bytes",
            }
        )
        self.assertIsNotNone(card["raw_path"])

        profile_context = {
            "context_schema_version": 1,
            "current_version_id": None,
            "profile_summary_zh": "",
            "evidence_ids": [],
        }
        current = compose_health_turn_context(
            profile_context, library.lookup("sleep")
        )

        self.assertEqual(set(current), CONTEXT_FIELDS)
        self.assertEqual(len(current["source_cards"]), 1)
        self.assertEqual(
            set(current["source_cards"][0]), PUBLIC_SOURCE_CARD_FIELDS
        )
        self.assertTrue(current["source_cards"][0]["untrusted_data"])
        self.assertEqual(
            current["source_status"],
            {"verified": True, "source": "card", "reason": None},
        )
        self.assertNotIn("raw_path", current["source_cards"][0])
        self.assertNotIn("conclusion_refs", current["source_cards"][0])

        self.clock.value += dt.timedelta(days=181)
        stale = compose_health_turn_context(
            profile_context, library.lookup("sleep")
        )
        self.assertEqual(stale["source_cards"], [])
        self.assertEqual(stale["source_status"]["reason"], "source-card-stale")

    @unittest.skipIf(
        not hasattr(socket, "AF_UNIX"),
        "AF_UNIX unavailable",
    )
    def test_partner_adapter_to_server_returns_the_narrow_current_context(self):
        admission = self._admit(1)
        ready = threading.Event()
        peer_uid = os.getuid() if hasattr(os, "getuid") else 1001
        peer_gid = os.getgid() if hasattr(os, "getgid") else 1001
        if not hasattr(socket, "SO_PEERCRED"):
            uid_patch = mock.patch("sidecar.server._peer_uid", return_value=peer_uid)
            gid_patch = mock.patch("sidecar.server._peer_gid", return_value=peer_gid)
            uid_patch.start()
            gid_patch.start()
            self.addCleanup(uid_patch.stop)
            self.addCleanup(gid_patch.stop)
        server = HealthSidecarServer(
            self.root / "health.sock",
            self.store,
            allowed_uids={peer_uid},
            allowed_gids={peer_gid},
            ready_event=ready,
        )
        server.source_library.ingest(
            {
                "url": "https://www.who.int/sleep",
                "source_type": "clinical_guideline",
                "title": "Sleep guidance",
                "tags": _tags(),
                "key_excerpt": "Sleep hygiene guidance.",
                "raw_document": b"private cached source bytes",
            }
        )
        thread = threading.Thread(target=server.run_forever, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(timeout=3))
        self.addCleanup(server.stop)
        self.addCleanup(thread.join, 3)

        result = PartnerHealthAdapter(
            str(self.root / "health.sock")
        ).read_health_turn_context(
            **self._context_request(
                "我最近睡眠第1次不好", message_id="health-1"
            )
        )

        self.assertEqual(set(result), CONTEXT_FIELDS)
        self.assertEqual(result["current_version_id"], admission["version_id"])
        self.assertEqual(result["profile_summary_zh"], "睡眠第1次不好")
        self.assertEqual(result["evidence_ids"], [admission["evidence_id"]])
        self.assertEqual(len(result["source_cards"]), 1)
        self.assertEqual(
            set(result["source_cards"][0]), PUBLIC_SOURCE_CARD_FIELDS
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import datetime as dt
import asyncio
import json
import os
import multiprocessing
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HERMES_SOURCE = ROOT.parents[1] / ".research" / "hermes-agent"

from sidecar.profile import ProfileStoreError
from sidecar.receipt_signer import Ed25519ReceiptSigner
from sidecar.store import HealthSidecarStore, HmacInboundMessageVerifier, StoreError
from weixin_ingress import (
    HealthModelConfig,
    HermesFreshHealthClassifier,
    PartnerWeixinIngressCoordinator,
    TrustedWeixinEnvelope,
)


OWNER = "wx-owner"
OTHER = "wx-other"
SUBJECT = "profile"
CONSENT_ACTION = "health.recording.enable"
ADMIT_ACTION = "health.profile.message.admit"


def _child_signer_attempt(socket_path: str, result_queue) -> None:
    from sidecar.receipt_signer import ReceiptSignerClient

    try:
        ReceiptSignerClient(socket_path).sign_access(
            action=CONSENT_ACTION,
            subject=SUBJECT,
            actor_sender_id=OWNER,
            target_sender_id=OWNER,
            message_id="child-forge",
            message_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
    except Exception as exc:
        result_queue.put(str(exc))
    else:
        result_queue.put("unexpected-success")


class FixedClock:
    def __init__(self, value: dt.datetime) -> None:
        self.value = value

    def now_utc(self) -> dt.datetime:
        return self.value


class ConsentedWeixinIngressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.clock = FixedClock(
            dt.datetime(2026, 8, 9, 2, 0, tzinfo=dt.timezone.utc)
        )
        self.verifier = HmacInboundMessageVerifier(b"r" * 32)
        self.store = HealthSidecarStore(
            root / "health.state",
            root / "health.key",
            clock=self.clock,
            message_verifier=self.verifier,
            expected_owner_sender_id=OWNER,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _enable(self, sender_id: str = OWNER, message_id: str = "consent-1"):
        message_utc = self.clock.now_utc().isoformat()
        token = self.verifier.sign_access_receipt(
            action=CONSENT_ACTION,
            subject=SUBJECT,
            actor_sender_id=sender_id,
            target_sender_id=sender_id,
            message_id=message_id,
            message_utc=message_utc,
        )
        return self.store.enable_health_recording(
            SUBJECT,
            sender_id,
            message_id,
            message_utc,
            token,
        )

    def _candidate(self, message_id: str = "health-1") -> dict:
        message_utc = self.clock.now_utc().isoformat()
        return {
            "evidence_kind": "direct_statement",
            "source_message_id": message_id,
            "source_utc": message_utc,
            "excerpt": "肚子不舒服",
            "measurement": None,
            "conclusions": [
                {
                    "category": "state",
                    "dedupe_key": "abdominal-discomfort",
                    "text": "肚子不舒服",
                    "status": "fact",
                    "priority": 3,
                }
            ],
        }

    def _admit(self, *, message_id: str = "health-1", text: str = "我肚子不舒服"):
        message_utc = self.clock.now_utc().isoformat()
        token = self.verifier.sign_ingress_receipt(
            action=ADMIT_ACTION,
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
        return self.store.admit_consented_profile_candidate(
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
            candidate=self._candidate(message_id),
        )

    def test_explicit_consent_does_not_create_profile_then_first_health_write_binds_atomically(self):
        enabled = self._enable()
        self.assertTrue(enabled["enabled"])
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

        result = self._admit()

        self.assertTrue(result["changed"])
        profile = self.store.read_profile(SUBJECT, OWNER)
        self.assertEqual(profile["owner_sender_id"], OWNER)
        self.assertEqual(len(profile["evidence"]), 1)
        self.assertEqual(len(profile["profile_versions"]), 1)
        self.assertLessEqual(len(profile["profile_summary_zh"]), 300)

    def test_no_consent_or_wrong_owner_never_creates_or_reveals_profile(self):
        with self.assertRaisesRegex(ProfileStoreError, "recording-not-enabled"):
            self._admit()
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

    def test_consent_mode_disables_all_legacy_profile_write_entrypoints(self):
        owner_token = self.verifier.sign_owner_binding(
            subject=SUBJECT, owner_sender_id=OWNER
        )
        with self.assertRaisesRegex(
            ProfileStoreError, "legacy-profile-ingress-disabled"
        ):
            self.store.bind_profile_owner(SUBJECT, OWNER, owner_token)
        with self.assertRaisesRegex(
            ProfileStoreError, "legacy-profile-ingress-disabled"
        ):
            self.store.stage_profile_message(
                SUBJECT,
                OWNER,
                "legacy-message",
                "2026-08-09T02:00:00+00:00",
                "我肚子不舒服",
                "direct_statement",
                "unused-token",
            )
        with self.assertRaisesRegex(
            ProfileStoreError, "legacy-profile-ingress-disabled"
        ):
            self.store.record_profile_candidate(
                SUBJECT, OWNER, self._candidate("legacy-message")
            )
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

        with self.assertRaisesRegex(ProfileStoreError, "recording-enable-not-authorized"):
            self._enable(OTHER)
        self.assertFalse(self.store.health_recording_enabled(SUBJECT, OTHER))
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

    def test_forged_mismatched_or_replayed_receipt_has_no_partial_write(self):
        self._enable()
        message_utc = self.clock.now_utc().isoformat()
        candidate = self._candidate()
        with self.assertRaisesRegex(ProfileStoreError, "unverified-inbound-message"):
            self.store.admit_consented_profile_candidate(
                subject=SUBJECT,
                sender_id=OWNER,
                message_id="health-1",
                message_utc=message_utc,
                message_text="我肚子不舒服",
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
                verification_token="forged",
                candidate=candidate,
            )
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

        token = self.verifier.sign_ingress_receipt(
            action=ADMIT_ACTION,
            subject=SUBJECT,
            sender_id=OWNER,
            message_id="health-1",
            message_utc=message_utc,
            message_text="我肚子不舒服",
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
        )
        candidate["excerpt"] = "头疼"
        with self.assertRaisesRegex(ProfileStoreError, "evidence-excerpt-not-in-source"):
            self.store.admit_consented_profile_candidate(
                subject=SUBJECT,
                sender_id=OWNER,
                message_id="health-1",
                message_utc=message_utc,
                message_text="我肚子不舒服",
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
                verification_token=token,
                candidate=candidate,
            )
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

        first = self._admit()
        with self.assertRaisesRegex(ProfileStoreError, "duplicate-source-message"):
            self._admit()
        profile = self.store.read_profile(SUBJECT, OWNER)
        self.assertEqual(len(profile["evidence"]), 1)
        self.assertEqual(profile["current_version_id"], first["version_id"])

    def test_audit_failure_rolls_back_candidate_and_allows_safe_retry(self):
        self._enable()
        with mock.patch.object(
            self.store,
            "_append_audit_events",
            side_effect=StoreError("forced-audit-failure"),
        ):
            with self.assertRaisesRegex(StoreError, "forced-audit-failure"):
                self._admit()
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

        result = self._admit()
        self.assertTrue(result["changed"])
        self.assertEqual(len(self.store.read_profile(SUBJECT, OWNER)["evidence"]), 1)

    def test_delete_keeps_recent_ingress_nonce_from_recreating_profile(self):
        self._enable()
        self._admit()
        message_utc = self.clock.now_utc().isoformat()
        confirmation_utc = (
            self.clock.now_utc() + dt.timedelta(seconds=1)
        ).isoformat()
        ingress_token = self.verifier.sign_ingress_receipt(
            action=ADMIT_ACTION,
            subject=SUBJECT,
            sender_id=OWNER,
            message_id="health-1",
            message_utc=message_utc,
            message_text="鎴戣倸瀛愪笉鑸掓湇",
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
        )
        delete_request_token = self.verifier.sign_access_receipt(
            action="health.profile.delete.request",
            subject=SUBJECT,
            actor_sender_id=OWNER,
            target_sender_id=OWNER,
            message_id="delete-request-1",
            message_utc=message_utc,
        )
        delete_confirm_token = self.verifier.sign_access_receipt(
            action="health.profile.delete.confirm",
            subject=SUBJECT,
            actor_sender_id=OWNER,
            target_sender_id=OWNER,
            message_id="delete-confirm-1",
            message_utc=confirmation_utc,
        )

        class Projection:
            def remove_health_projection(self, _subject):
                return True

        requested = self.store.request_profile_deletion(
            SUBJECT,
            OWNER,
            "delete-request-1",
            message_utc,
            delete_request_token,
        )
        self.assertFalse(requested["deleted"])
        result = self.store.confirm_profile_deletion(
            SUBJECT,
            OWNER,
            "delete-request-1",
            "delete-confirm-1",
            confirmation_utc,
            delete_confirm_token,
            memory_projection=Projection(),
        )
        self.assertTrue(result["deleted"])
        self._enable(message_id="consent-after-delete")
        with self.assertRaisesRegex(ProfileStoreError, "access-receipt-replayed"):
            self.store.admit_consented_profile_candidate(
                subject=SUBJECT,
                sender_id=OWNER,
                message_id="health-1",
                message_utc=message_utc,
                message_text="鎴戣倸瀛愪笉鑸掓湇",
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
                verification_token=ingress_token,
                candidate=self._candidate("health-1"),
            )
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

    def test_sidecar_rejects_candidate_that_arrives_after_ingress_deadline(self):
        self._enable()
        message_utc = self.clock.now_utc().isoformat()
        candidate = self._candidate("late-health")
        token = self.verifier.sign_ingress_receipt(
            action=ADMIT_ACTION,
            subject=SUBJECT,
            sender_id=OWNER,
            message_id="late-health",
            message_utc=message_utc,
            message_text="鎴戣倸瀛愪笉鑸掓湇",
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
        )
        self.clock.value += dt.timedelta(seconds=16)

        with self.assertRaisesRegex(
            ProfileStoreError, "health-ingress-deadline-exceeded"
        ):
            self.store.admit_consented_profile_candidate(
                subject=SUBJECT,
                sender_id=OWNER,
                message_id="late-health",
                message_utc=message_utc,
                message_text="鎴戣倸瀛愪笉鑸掓湇",
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
                verification_token=token,
                candidate=candidate,
            )
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )

    def test_fresh_retry_attempt_can_admit_same_envelope_within_ten_minutes(self):
        self._enable()
        message_utc = self.clock.now_utc().isoformat()
        candidate = self._candidate("retry-health")
        message_text = str(candidate["excerpt"])
        self.clock.value += dt.timedelta(seconds=30)
        attempt_utc = self.clock.now_utc().isoformat()
        token = self.verifier.sign_ingress_receipt(
            action=ADMIT_ACTION,
            subject=SUBJECT,
            sender_id=OWNER,
            message_id="retry-health",
            message_utc=message_utc,
            message_text=message_text,
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
            attempt_utc=attempt_utc,
        )

        result = self.store.admit_consented_profile_candidate(
            subject=SUBJECT,
            sender_id=OWNER,
            message_id="retry-health",
            message_utc=message_utc,
            attempt_utc=attempt_utc,
            message_text=message_text,
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
            verification_token=token,
            candidate=candidate,
        )
        self.assertTrue(result["changed"])

    def test_deadline_crossed_during_audit_rolls_back_state_and_audit(self):
        self._enable()
        message_utc = self.clock.now_utc().isoformat()
        candidate = self._candidate("slow-commit")
        message_text = str(candidate["excerpt"])
        token = self.verifier.sign_ingress_receipt(
            action=ADMIT_ACTION,
            subject=SUBJECT,
            sender_id=OWNER,
            message_id="slow-commit",
            message_utc=message_utc,
            message_text=message_text,
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
            attempt_utc=message_utc,
        )
        append_batch = self.store._append_audit_events

        def slow_audit(events, **kwargs):
            self.clock.value += dt.timedelta(seconds=16)
            return append_batch(events, **kwargs)

        with mock.patch.object(
            self.store, "_append_audit_events", side_effect=slow_audit
        ):
            with self.assertRaisesRegex(
                ProfileStoreError, "health-ingress-deadline-exceeded"
            ):
                self.store.admit_consented_profile_candidate(
                    subject=SUBJECT,
                    sender_id=OWNER,
                    message_id="slow-commit",
                    message_utc=message_utc,
                    attempt_utc=message_utc,
                    message_text=message_text,
                    evidence_kind="direct_statement",
                    channel="weixin",
                    profile_name="partner",
                    verification_token=token,
                    candidate=candidate,
                )
        self.assertIsNone(
            self.store.read_subject_status(SUBJECT, _allow_profile_state=True)
        )
        self.assertNotIn(
            "profile_candidate_accepted",
            json.dumps(self.store.read_audit_events(limit=None)),
        )


class ReceiptSignerTests(unittest.TestCase):
    def test_production_ingress_schemas_require_attempt_only_on_consent_admit(self):
        from sidecar import protocol, receipt_signer

        self.assertIn("attempt_utc", receipt_signer._INGRESS_FIELDS)
        stage = {
            "action": protocol.ACTION_PROFILE_MESSAGE_STAGE,
            "payload": {
                "subject": SUBJECT,
                "sender_id": OWNER,
                "message_id": "legacy-stage",
                "message_utc": "2026-08-09T02:00:00+00:00",
                "message_text": "legacy",
                "evidence_kind": "direct_statement",
                "verification_token": "token",
            },
        }
        self.assertEqual(
            protocol.parse_request(json.dumps(stage).encode()).action,
            protocol.ACTION_PROFILE_MESSAGE_STAGE,
        )
        consented = {
            "action": protocol.ACTION_PROFILE_CONSENTED_ADMIT,
            "payload": {
                "subject": SUBJECT,
                "sender_id": OWNER,
                "message_id": "health-1",
                "message_utc": "2026-08-09T02:00:00+00:00",
                "message_text": "health",
                "evidence_kind": "direct_statement",
                "channel": "weixin",
                "profile_name": "partner",
                "verification_token": "token",
                "candidate": {},
            },
        }
        with self.assertRaisesRegex(
            protocol.SidecarProtocolError, "attempt_utc"
        ):
            protocol.parse_request(json.dumps(consented).encode())
        consented["payload"]["attempt_utc"] = "2026-08-09T02:00:00+00:00"
        self.assertEqual(
            protocol.parse_request(json.dumps(consented).encode()).action,
            protocol.ACTION_PROFILE_CONSENTED_ADMIT,
        )

    def test_ed25519_signer_binds_action_and_exact_ingress_envelope(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
        except ImportError:
            self.skipTest("cryptography unavailable")
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
        from sidecar.store import Ed25519InboundMessageVerifier

        verifier = Ed25519InboundMessageVerifier(public_bytes)
        message_utc = "2026-08-09T02:00:00+00:00"
        access_token = signer.sign_access(
            action=CONSENT_ACTION,
            subject=SUBJECT,
            actor_sender_id=OWNER,
            target_sender_id=OWNER,
            message_id="consent-1",
            message_utc=message_utc,
        )
        self.assertTrue(
            verifier.verify_access_receipt(
                action=CONSENT_ACTION,
                subject=SUBJECT,
                actor_sender_id=OWNER,
                target_sender_id=OWNER,
                message_id="consent-1",
                message_utc=message_utc,
                token=access_token,
            )
        )

        ingress_token = signer.sign_ingress(
            action=ADMIT_ACTION,
            subject=SUBJECT,
            sender_id=OWNER,
            message_id="health-1",
            message_utc=message_utc,
            message_text="我肚子不舒服",
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
            attempt_utc=message_utc,
        )
        self.assertTrue(
            verifier.verify_ingress_receipt(
                action=ADMIT_ACTION,
                subject=SUBJECT,
                sender_id=OWNER,
                message_id="health-1",
                message_utc=message_utc,
                message_text="我肚子不舒服",
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
                attempt_utc=message_utc,
                token=ingress_token,
            )
        )
        self.assertFalse(
            verifier.verify_ingress_receipt(
                action="health.profile.message.stage",
                subject=SUBJECT,
                sender_id=OWNER,
                message_id="health-1",
                message_utc=message_utc,
                message_text="我肚子不舒服",
                evidence_kind="direct_statement",
                channel="weixin",
                profile_name="partner",
                attempt_utc="2026-08-09T02:00:01+00:00",
                token=ingress_token,
            )
        )


@unittest.skipUnless(
    hasattr(socket, "AF_UNIX")
    and hasattr(socket, "SO_PEERCRED")
    and hasattr(os, "getuid"),
    "Linux AF_UNIX peer credentials required",
)
class LinuxReceiptSignerBoundaryTests(unittest.TestCase):
    def test_same_uid_tool_subprocess_is_denied_by_exact_gateway_pid(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        from sidecar.receipt_signer import ReceiptSignerServer

        private = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        with tempfile.TemporaryDirectory() as temp:
            socket_path = str(Path(temp) / "signer.sock")
            server = ReceiptSignerServer(
                socket_path,
                Ed25519ReceiptSigner(private),
                allowed_gateway_pid=os.getpid(),
                allowed_gateway_uid=os.getuid(),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.close)
            for _ in range(100):
                if Path(socket_path).exists():
                    break
                threading.Event().wait(0.01)
            result_queue = multiprocessing.Queue()
            child = multiprocessing.Process(
                target=_child_signer_attempt,
                args=(socket_path, result_queue),
            )
            child.start()
            child.join(5)
            self.assertEqual(result_queue.get(timeout=2), "gateway-process-not-authorized")


class FakePartnerAdapter:
    def __init__(self, enabled: bool = False, changed: bool = True) -> None:
        self.enabled = enabled
        self.changed = changed
        self.calls: list[tuple] = []
        self.admitted_message_ids: set[str] = set()
        self._next_lease = 0

    def health_recording_enabled(self, subject: str, sender_id: str) -> bool:
        self.calls.append(("status", subject, sender_id))
        return self.enabled

    def enable_health_recording(self, *args):
        self.calls.append(("enable", *args))
        self.enabled = True
        return {"enabled": True, "changed": True}

    def admit_consented_profile_candidate(self, **kwargs):
        self.calls.append(("admit", kwargs))
        self.admitted_message_ids.add(str(kwargs["message_id"]))
        return {
            "changed": self.changed,
            "version_id": "pv-1",
            "evidence_id": "ev-1",
        }

    def profile_message_admitted(
        self, subject: str, sender_id: str, message_id: str
    ) -> bool:
        self.calls.append(("admission-status", subject, sender_id, message_id))
        return message_id in self.admitted_message_ids

    def begin_recording_attempt(self, subject: str, sender_id: str) -> str:
        if not self.enabled:
            raise RuntimeError("recording-not-enabled")
        self._next_lease += 1
        lease_id = f"fake-lease-{self._next_lease}"
        self.calls.append(("attempt-begin", subject, sender_id, lease_id))
        return lease_id

    def end_recording_attempt(self, lease_id: str) -> bool:
        self.calls.append(("attempt-end", lease_id))
        return True

    def remember_recent_owner_message(self, *args, **kwargs):
        self.calls.append(("recent", args, kwargs))
        return True

    def send_recording_feedback(self, *args, **kwargs):
        self.calls.append(("feedback", args, kwargs))
        return {"sent": True}

    def read_health_turn_context(self, **kwargs):
        self.calls.append(("turn-context", kwargs))
        return {
            "context_schema_version": 1,
            "current_version_id": "pv-1",
            "profile_summary_zh": "刚提交的画像",
            "evidence_ids": ["ev-1"],
            "source_cards": [],
            "source_status": {
                "verified": False,
                "source": "none",
                "reason": "verification-unavailable",
            },
        }


class FakeSigner:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def sign_access(self, **kwargs) -> str:
        self.calls.append(("access", kwargs))
        return "access-token"

    def sign_ingress(self, **kwargs) -> str:
        self.calls.append(("ingress", kwargs))
        return "ingress-token"


class FakeClassifier:
    def __init__(self, decision: dict) -> None:
        self.decision = decision
        self.envelopes: list[TrustedWeixinEnvelope] = []

    def classify(self, envelope: TrustedWeixinEnvelope) -> dict:
        self.envelopes.append(envelope)
        return self.decision


class WeixinIngressCoordinatorTests(unittest.TestCase):
    def _envelope(self, text: str, message_id: str = "m-1"):
        return TrustedWeixinEnvelope(
            sender_id=OWNER,
            message_id=message_id,
            message_utc="2026-08-09T02:00:00+00:00",
            message_text=text,
            channel="weixin",
            profile_name="partner",
        )

    def _candidate_decision(self, message_id: str = "m-1") -> dict:
        return {
            "decision": "candidate",
            "candidate": {
                "evidence_kind": "direct_statement",
                "source_message_id": message_id,
                "source_utc": "2026-08-09T02:00:00+00:00",
                "excerpt": "肚子不舒服",
                "measurement": None,
                "conclusions": [],
            },
        }

    def test_no_consent_never_calls_health_classifier(self):
        adapter = FakePartnerAdapter(enabled=False)
        signer = FakeSigner()
        classifier = FakeClassifier(self._candidate_decision())
        coordinator = PartnerWeixinIngressCoordinator(
            adapter, signer, classifier, expected_owner_sender_id=OWNER
        )

        outcome = coordinator.process(self._envelope("我肚子不舒服"))

        self.assertEqual(outcome.status, "recording-disabled")
        self.assertEqual(classifier.envelopes, [])
        self.assertEqual(signer.calls, [])

    def test_exact_owner_consent_enables_without_classifying_or_binding(self):
        adapter = FakePartnerAdapter(enabled=False)
        signer = FakeSigner()
        classifier = FakeClassifier(self._candidate_decision())
        coordinator = PartnerWeixinIngressCoordinator(
            adapter, signer, classifier, expected_owner_sender_id=OWNER
        )

        outcome = coordinator.process(self._envelope("启用健康记录"))

        self.assertEqual(outcome.status, "recording-enabled")
        self.assertIsNone(outcome.tail_marker)
        self.assertEqual(classifier.envelopes, [])
        self.assertEqual(signer.calls[0][0], "access")
        self.assertEqual(adapter.calls[0][0], "enable")

    def test_each_prebatch_message_is_classified_fresh_and_marker_needs_sidecar_change(self):
        adapter = FakePartnerAdapter(enabled=True)
        signer = FakeSigner()
        classifier = FakeClassifier(self._candidate_decision("m-1"))
        coordinator = PartnerWeixinIngressCoordinator(
            adapter, signer, classifier, expected_owner_sender_id=OWNER
        )

        first = coordinator.process(self._envelope("我肚子不舒服", "m-1"))
        classifier.decision = self._candidate_decision("m-2")
        adapter.changed = False
        second = coordinator.process(self._envelope("还是肚子不舒服", "m-2"))

        self.assertEqual(first.tail_marker, "〔健康管家：画像已更新〕")
        self.assertIsNone(second.tail_marker)
        self.assertEqual(
            [item.message_id for item in classifier.envelopes], ["m-1", "m-2"]
        )
        ingress_calls = [item for item in signer.calls if item[0] == "ingress"]
        self.assertEqual(
            [item[1]["message_id"] for item in ingress_calls], ["m-1", "m-2"]
        )

    def test_ordinary_chat_is_verified_only_for_ephemeral_recent_window(self):
        adapter = FakePartnerAdapter(enabled=True)
        signer = FakeSigner()
        coordinator = PartnerWeixinIngressCoordinator(
            adapter,
            signer,
            FakeClassifier({"decision": "none"}),
            expected_owner_sender_id=OWNER,
        )

        outcome = coordinator.process(self._envelope("今天聊点别的", "ordinary-1"))

        self.assertEqual(outcome.status, "no-health-candidate")
        recent_calls = [item for item in adapter.calls if item[0] == "recent"]
        self.assertEqual(len(recent_calls), 1)
        ingress = [item for item in signer.calls if item[0] == "ingress"]
        self.assertEqual(ingress[-1][1]["action"], "health.profile.message.recent")
        self.assertEqual(ingress[-1][1]["evidence_kind"], "ordinary_chat")

    def test_health_question_routes_to_health_answer_without_becoming_ordinary_chat(self):
        adapter = FakePartnerAdapter(enabled=True)
        coordinator = PartnerWeixinIngressCoordinator(
            adapter,
            FakeSigner(),
            FakeClassifier(
                {
                    "decision": "none",
                    "health_related": True,
                    "requires_source_verification": True,
                }
            ),
            expected_owner_sender_id=OWNER,
        )

        outcome = coordinator.process(
            self._envelope("失眠时怎样调整作息？", "health-question-1")
        )

        self.assertEqual(outcome.status, "health-related")
        self.assertTrue(outcome.health_related)
        self.assertTrue(outcome.source_verification_required)
        self.assertFalse(any(call[0] == "recent" for call in adapter.calls))

    def test_health_turn_context_is_receipt_bound_and_read_after_profile_write(self):
        adapter = FakePartnerAdapter(enabled=True)
        signer = FakeSigner()
        coordinator = PartnerWeixinIngressCoordinator(
            adapter,
            signer,
            FakeClassifier(self._candidate_decision("post-write-context")),
            expected_owner_sender_id=OWNER,
        )
        envelope = self._envelope(
            "我肚子不舒服",
            "post-write-context",
        )

        outcome = coordinator.process(envelope)
        context = coordinator.load_health_turn_context(envelope)

        self.assertEqual(outcome.version_id, "pv-1")
        self.assertEqual(context["current_version_id"], "pv-1")
        call_names = [call[0] for call in adapter.calls]
        self.assertLess(call_names.index("admit"), call_names.index("turn-context"))
        context_signature = [
            payload
            for kind, payload in signer.calls
            if kind == "ingress"
            and payload["action"] == "health.turn.context.read"
        ]
        self.assertEqual(len(context_signature), 1)
        self.assertEqual(context_signature[0]["message_id"], "post-write-context")
        self.assertEqual(context_signature[0]["message_text"], "我肚子不舒服")
        self.assertEqual(context_signature[0]["evidence_kind"], "health_related")

    def test_health_decision_is_observed_before_candidate_admission_failure(self):
        class FailingAdmissionAdapter(FakePartnerAdapter):
            def admit_consented_profile_candidate(self, **kwargs):
                self.calls.append(("admit", kwargs))
                raise RuntimeError("sidecar-admission-unavailable")

        adapter = FailingAdmissionAdapter(enabled=True)
        coordinator = PartnerWeixinIngressCoordinator(
            adapter,
            FakeSigner(),
            FakeClassifier(self._candidate_decision("health-admit-fails")),
            expected_owner_sender_id=OWNER,
        )
        observed = []

        with self.assertRaisesRegex(
            RuntimeError, "sidecar-admission-unavailable"
        ):
            coordinator.classify_and_admit(
                self._envelope("我肚子不舒服", "health-admit-fails"),
                health_decision_observed=lambda health, source: observed.append(
                    (health, source)
                ),
            )

        self.assertEqual(observed, [(True, False)])
        self.assertEqual(
            [call[0] for call in adapter.calls],
            ["attempt-begin", "admit", "attempt-end"],
        )

    def test_health_model_call_uses_only_envelope_and_exact_pinned_endpoint(self):
        if not (HERMES_SOURCE / "agent/plugin_llm.py").is_file():
            self.skipTest("Hermes mirror unavailable")
        sys.path.insert(0, str(HERMES_SOURCE))
        from agent.plugin_llm import PluginLlm, _TrustPolicy

        class Completions:
            def __init__(self) -> None:
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                message = type(
                    "Message",
                    (),
                    {
                        "content": (
                            '{"decision":"none","health_related":true,'
                            '"requires_source_verification":true}'
                        )
                    },
                )()
                choice = type("Choice", (), {"message": message})()
                return type(
                    "Response",
                    (),
                    {"choices": [choice], "model": "health-model-v1"},
                )()

        completions = Completions()
        client = type(
            "Client",
            (),
            {
                "base_url": "https://accepted.example/v1/",
                "chat": type(
                    "Chat", (), {"completions": completions}
                )(),
            },
        )()
        policy = _TrustPolicy(
            plugin_id="health-steward",
            allow_provider_override=True,
            allowed_providers=frozenset({"accepted-provider"}),
            allow_model_override=True,
            allowed_models=frozenset({"health-model-v1"}),
            allow_profile_override=True,
        )
        llm = PluginLlm(
            plugin_id="health-steward", policy_loader=lambda _plugin_id: policy
        )
        config = HealthModelConfig(
            provider="accepted-provider",
            endpoint="https://accepted.example/v1",
            model_id="health-model-v1",
            privacy_mode="third-party-accepted",
            auth_profile="partner",
        )
        classifier = HermesFreshHealthClassifier(llm, config)
        try:
            with mock.patch(
                "agent.auxiliary_client._get_cached_client",
                return_value=(client, "health-model-v1"),
            ), mock.patch("agent.auxiliary_client.call_llm") as fallback_call:
                result = classifier.classify(self._envelope("我肚子不舒服"))
        finally:
            if str(HERMES_SOURCE) in sys.path:
                sys.path.remove(str(HERMES_SOURCE))

        self.assertEqual(
            result,
            {
                "decision": "none",
                "health_related": True,
                "requires_source_verification": True,
            },
        )
        fallback_call.assert_not_called()
        self.assertEqual(len(completions.calls), 1)
        call = completions.calls[0]
        serialized_messages = json.dumps(call["messages"], ensure_ascii=False)
        self.assertIn("我肚子不舒服", serialized_messages)
        self.assertNotIn("history", serialized_messages)

    def test_health_model_endpoint_drift_fails_before_sending(self):
        if not (HERMES_SOURCE / "agent/plugin_llm.py").is_file():
            self.skipTest("Hermes mirror unavailable")
        sys.path.insert(0, str(HERMES_SOURCE))
        from agent.plugin_llm import PluginLlm, _TrustPolicy

        create = mock.Mock()
        client = type(
            "Client",
            (),
            {
                "base_url": "https://unapproved.example/v1",
                "chat": type(
                    "Chat", (), {"completions": type("Completions", (), {"create": create})()}
                )(),
            },
        )()
        policy = _TrustPolicy(
            plugin_id="health-steward",
            allow_provider_override=True,
            allowed_providers=frozenset({"accepted-provider"}),
            allow_model_override=True,
            allowed_models=frozenset({"health-model-v1"}),
            allow_profile_override=True,
        )
        classifier = HermesFreshHealthClassifier(
            PluginLlm(
                plugin_id="health-steward",
                policy_loader=lambda _plugin_id: policy,
            ),
            HealthModelConfig(
                provider="accepted-provider",
                endpoint="https://accepted.example/v1",
                model_id="health-model-v1",
                privacy_mode="third-party-accepted",
                auth_profile="partner",
            ),
        )
        try:
            with mock.patch(
                "agent.auxiliary_client._get_cached_client",
                return_value=(client, "health-model-v1"),
            ):
                with self.assertRaisesRegex(
                    Exception, "health-model-endpoint-mismatch"
                ):
                    classifier.classify(self._envelope("我肚子不舒服"))
        finally:
            if str(HERMES_SOURCE) in sys.path:
                sys.path.remove(str(HERMES_SOURCE))
        create.assert_not_called()


class PartnerWeixinAdapterIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.hermes_source = ROOT.parents[1] / ".research" / "hermes-agent"
        if not (self.hermes_source / "gateway/platforms/weixin.py").is_file():
            self.skipTest("Hermes mirror unavailable")
        sys.path.insert(0, str(self.hermes_source))
        sys.path.insert(0, str(ROOT / "plugin" / "health-steward"))
        self.old_hermes_home = os.environ.get("HERMES_HOME")
        self.temp_home = tempfile.TemporaryDirectory()
        os.environ["HERMES_HOME"] = self.temp_home.name

    async def asyncTearDown(self) -> None:
        for path in (str(ROOT / "plugin" / "health-steward"), str(self.hermes_source)):
            if path in sys.path:
                sys.path.remove(path)
        self.temp_home.cleanup()
        if self.old_hermes_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self.old_hermes_home

    async def test_adapter_observes_each_event_before_native_batch_and_carries_marker(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter
        from weixin_ingress import IngressOutcome

        class Coordinator:
            def __init__(self) -> None:
                self.envelopes = []

            def prepare(self, envelope, **_kwargs):
                self.envelopes.append(envelope)
                return None

            def classify_and_admit(self, envelope, **_kwargs):
                return IngressOutcome(
                    "profile-updated" if envelope.message_id == "m-2" else "none",
                    tail_marker=(
                        "〔健康管家：画像已更新〕"
                        if envelope.message_id == "m-2"
                        else None
                    ),
                )

        coordinator = Coordinator()
        config = PlatformConfig(
            enabled=True,
            token="test-token",
            typing_indicator=False,
            extra={"account_id": "partner-bot", "text_batch_delay_seconds": 30},
        )
        adapter = PartnerHealthWeixinAdapter(config, coordinator)
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        first = MessageEvent(text="第一条", source=source, message_id="m-1")
        second = MessageEvent(text="第二条", source=source, message_id="m-2")

        adapter._enqueue_text_event(first)
        adapter._enqueue_text_event(second)
        for _ in range(100):
            pending_values = list(adapter._pending_text_batches.values())
            if (
                len(coordinator.envelopes) == 2
                and pending_values
                and pending_values[0].text == "第一条\n第二条"
            ):
                break
            await asyncio.sleep(0.01)

        self.assertEqual(
            [item.message_id for item in coordinator.envelopes], ["m-1", "m-2"]
        )
        self.assertTrue(all(item.message_utc.endswith("+00:00") for item in coordinator.envelopes))
        pending = next(iter(adapter._pending_text_batches.values()))
        self.assertEqual(pending.text, "第一条\n第二条")
        self.assertEqual(
            pending.metadata["health_steward_tail_marker"],
            "〔健康管家：画像已更新〕",
        )
        for task in list(adapter._pending_text_batch_tasks.values()):
            task.cancel()

    async def test_health_turn_is_answered_before_native_chat_batch(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter
        from weixin_ingress import IngressOutcome

        class Coordinator:
            def prepare(self, _envelope, **_kwargs):
                return None

            def classify_and_admit(self, _envelope, **_kwargs):
                return IngressOutcome(
                    "health-related",
                    health_related=True,
                    version_id="profile-version-2",
                )

        class HealthTurnHandler:
            def __init__(self) -> None:
                self.calls = []

            def handle(
                self, envelope, outcome, *, cancellation_requested=None
            ) -> None:
                if cancellation_requested is not None and cancellation_requested():
                    return
                self.calls.append((envelope, outcome))

        handler = HealthTurnHandler()
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "text_batch_delay_seconds": 30,
                },
            ),
            Coordinator(),
            health_turn_handler=handler,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )

        adapter._enqueue_text_event(
            MessageEvent(
                text="失眠时怎样调整作息？",
                source=source,
                message_id="health-answer-1",
            )
        )
        for _ in range(100):
            if handler.calls:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(len(handler.calls), 1)
        envelope, outcome = handler.calls[0]
        self.assertEqual(envelope.message_id, "health-answer-1")
        self.assertEqual(outcome.version_id, "profile-version-2")
        self.assertEqual(adapter._pending_text_batches, {})

    async def test_ordinary_turn_never_calls_health_turn_handler(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter
        from weixin_ingress import IngressOutcome

        class Coordinator:
            def prepare(self, _envelope, **_kwargs):
                return None

            def classify_and_admit(self, _envelope, **_kwargs):
                return IngressOutcome("no-health-candidate")

        handler = mock.Mock()
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "text_batch_delay_seconds": 30,
                },
            ),
            Coordinator(),
            health_turn_handler=handler,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )

        adapter._enqueue_text_event(
            MessageEvent(
                text="今晚吃什么？",
                source=source,
                message_id="ordinary-only-1",
            )
        )
        pending = None
        for _ in range(100):
            values = list(adapter._pending_text_batches.values())
            pending = values[0] if values else None
            if pending is not None:
                break
            await asyncio.sleep(0.01)

        self.assertIsNotNone(pending)
        self.assertEqual(pending.text, "今晚吃什么？")
        handler.handle.assert_not_called()
        for task in list(adapter._pending_text_batch_tasks.values()):
            task.cancel()

    async def test_post_classification_admission_timeout_never_enters_native_chat(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter

        class SlowAdmissionAdapter(FakePartnerAdapter):
            def admit_consented_profile_candidate(self, **kwargs):
                self.calls.append(("admit", kwargs))
                time.sleep(0.15)
                raise RuntimeError("late-sidecar-admission")

        sidecar = SlowAdmissionAdapter(enabled=True)
        decision = WeixinIngressCoordinatorTests()._candidate_decision(
            "health-admission-timeout"
        )
        decision.update(
            {
                "health_related": True,
                "requires_source_verification": False,
            }
        )
        coordinator = PartnerWeixinIngressCoordinator(
            sidecar,
            FakeSigner(),
            FakeClassifier(decision),
            expected_owner_sender_id=OWNER,
        )

        class HealthTurnHandler:
            def __init__(self) -> None:
                self.outcomes = []

            def handle(
                self, _envelope, outcome, *, cancellation_requested=None
            ) -> None:
                self.outcomes.append(outcome)

        handler = HealthTurnHandler()
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={"account_id": "partner-bot"},
            ),
            coordinator,
            health_ingress_budget_seconds=0.05,
            health_turn_handler=handler,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )

        adapter._enqueue_text_event(
            MessageEvent(
                text="我肚子不舒服",
                source=source,
                message_id="health-admission-timeout",
            )
        )
        for _ in range(100):
            if handler.outcomes:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(len(handler.outcomes), 1)
        self.assertTrue(handler.outcomes[0].health_related)
        self.assertFalse(handler.outcomes[0].health_answer_ready)
        self.assertEqual(adapter._pending_text_batches, {})

    async def test_rapid_health_turns_are_answered_in_arrival_order(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter
        from weixin_ingress import IngressOutcome

        second_classified = threading.Event()

        class Coordinator:
            def prepare(self, _envelope, **_kwargs):
                return None

            def classify_and_admit(self, envelope, **_kwargs):
                if envelope.message_id == "ordered-health-1":
                    second_classified.wait(1)
                    time.sleep(0.03)
                else:
                    second_classified.set()
                return IngressOutcome("health-related", health_related=True)

        class HealthTurnHandler:
            def __init__(self) -> None:
                self.message_ids = []

            def handle(
                self, envelope, _outcome, *, cancellation_requested=None
            ) -> None:
                if cancellation_requested is not None and cancellation_requested():
                    return
                self.message_ids.append(envelope.message_id)

        handler = HealthTurnHandler()
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={"account_id": "partner-bot"},
            ),
            Coordinator(),
            health_turn_handler=handler,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )

        adapter._enqueue_text_event(
            MessageEvent(
                text="第一条健康问题",
                source=source,
                message_id="ordered-health-1",
            )
        )
        adapter._enqueue_text_event(
            MessageEvent(
                text="第二条健康问题",
                source=source,
                message_id="ordered-health-2",
            )
        )
        for _ in range(100):
            if len(handler.message_ids) == 2:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(
            handler.message_ids,
            ["ordered-health-1", "ordered-health-2"],
        )

    async def test_real_message_closes_post_write_context_to_pinned_health_delivery(self):
        from types import SimpleNamespace

        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from health_turn import HealthSourceCatalog, HealthTurnHandler
        from weixin_adapter import PartnerHealthWeixinAdapter

        public_card = {
            "card_id": "card-sleep-current",
            "url": "https://www.who.int/health-topics/sleep",
            "source_type": "general_health_education",
            "title": "Sleep guidance",
            "version_hash": "source-v1",
            "key_excerpt": "保持规律起床时间。",
            "tags": {
                "topic": ["sleep"],
                "symptom_behavior": ["insomnia"],
                "target_population": ["adult"],
                "evidence_type": ["health_education"],
                "region_language": ["global-zh"],
                "freshness": ["current"],
            },
            "fetched_utc": "2026-08-09T02:00:00+00:00",
            "review_due_utc": "2027-08-09T02:00:00+00:00",
            "untrusted_data": True,
        }

        class PartnerAdapter(FakePartnerAdapter):
            def read_health_turn_context(self, **kwargs):
                self.calls.append(("turn-context", kwargs))
                return {
                    "context_schema_version": 1,
                    "current_version_id": "pv-1",
                    "profile_summary_zh": "刚提交的睡眠画像",
                    "evidence_ids": ["ev-1"],
                    "source_cards": [public_card],
                    "source_status": {
                        "verified": True,
                        "source": "card",
                        "reason": None,
                    },
                }

            def query_sources(self, *_args, **_kwargs):
                raise AssertionError("fresh context card must win")

        class Responder:
            def __init__(self) -> None:
                self.inputs = []

            def answer(self, answer_input):
                self.inputs.append(answer_input)
                return SimpleNamespace(
                    answer_text="先保持规律作息。",
                    used_source_card_ids=("card-sleep-current",),
                )

        class Channel:
            def __init__(self) -> None:
                self.sent = []

            def send_once(self, recipient, message, delivery_key):
                self.sent.append((recipient, message, delivery_key))
                return True

        with tempfile.TemporaryDirectory() as temp:
            catalog_path = Path(temp) / "catalog.json"
            catalog_path.write_text(
                json.dumps(
                    {
                        "catalog_schema_version": 1,
                        "keyword_urls": {
                            "睡眠": "https://www.who.int/health-topics/sleep"
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            partner = PartnerAdapter(enabled=True)
            coordinator = PartnerWeixinIngressCoordinator(
                partner,
                FakeSigner(),
                FakeClassifier(
                    {
                        "decision": "candidate",
                        "health_related": True,
                        "candidate": {
                            "evidence_kind": "direct_statement",
                            "source_message_id": "closed-health-1",
                            "source_utc": "2026-08-09T02:00:00+00:00",
                            "excerpt": "我最近睡眠不好",
                            "measurement": None,
                            "conclusions": [],
                        },
                    }
                ),
                expected_owner_sender_id=OWNER,
                subject=SUBJECT,
            )
            responder = Responder()
            channel = Channel()
            handler = HealthTurnHandler(
                context_loader=coordinator,
                source_reader=partner,
                responder=responder,
                channel=channel,
                source_catalog=HealthSourceCatalog.from_file(catalog_path),
            )
            adapter = PartnerHealthWeixinAdapter(
                PlatformConfig(
                    enabled=True,
                    token="test-token",
                    typing_indicator=False,
                    extra={"account_id": "partner-bot"},
                ),
                coordinator,
                health_turn_handler=handler,
            )
            source = adapter.build_source(
                chat_id=OWNER,
                chat_type="dm",
                user_id=OWNER,
                user_name=OWNER,
            )

            adapter._enqueue_text_event(
                MessageEvent(
                    text="我最近睡眠不好",
                    source=source,
                    message_id="closed-health-1",
                )
            )
            for _ in range(100):
                if channel.sent:
                    break
                await asyncio.sleep(0.01)

        self.assertEqual(len(channel.sent), 1)
        self.assertEqual(channel.sent[0][0], OWNER)
        self.assertEqual(
            channel.sent[0][1],
            "先保持规律作息。\n\n〔健康管家：画像已更新〕",
        )
        self.assertEqual(adapter._pending_text_batches, {})
        self.assertEqual(responder.inputs[0].current_version_id, "pv-1")
        self.assertEqual(
            responder.inputs[0].relevant_evidence_ids,
            ("ev-1",),
        )
        call_names = [call[0] for call in partner.calls]
        self.assertLess(call_names.index("admit"), call_names.index("turn-context"))

    async def test_rapid_messages_classify_concurrently_but_enqueue_in_order(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter
        from weixin_ingress import IngressOutcome

        barrier = threading.Barrier(2, timeout=1)

        class Coordinator:
            def __init__(self) -> None:
                self.errors = []

            def prepare(self, _envelope, **_kwargs):
                return None

            def classify_and_admit(self, _envelope, **_kwargs):
                try:
                    barrier.wait()
                except threading.BrokenBarrierError as exc:
                    self.errors.append(exc)
                    raise
                return IngressOutcome("no-health-candidate")

        coordinator = Coordinator()
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "text_batch_delay_seconds": 30,
                },
            ),
            coordinator,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        adapter._enqueue_text_event(
            MessageEvent(text="第一条", source=source, message_id="parallel-1")
        )
        adapter._enqueue_text_event(
            MessageEvent(text="第二条", source=source, message_id="parallel-2")
        )
        pending = None
        for _ in range(200):
            values = list(adapter._pending_text_batches.values())
            pending = values[0] if values else None
            if pending is not None and pending.text == "第一条\n第二条":
                break
            await asyncio.sleep(0.01)

        self.assertEqual(coordinator.errors, [])
        self.assertIsNotNone(pending)
        self.assertEqual(pending.text, "第一条\n第二条")
        for task in list(adapter._pending_text_batch_tasks.values()):
            task.cancel()

    async def test_total_ingress_deadline_releases_chat_and_cancels_late_admit(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter

        classifier_started = threading.Event()
        classifier_finished = threading.Event()

        class SlowClassifier:
            def classify(self, _envelope):
                classifier_started.set()
                time.sleep(0.2)
                classifier_finished.set()
                return {
                    "decision": "candidate",
                    "candidate": {
                        "evidence_kind": "direct_statement",
                        "source_message_id": "deadline-1",
                        "source_utc": "2026-08-09T02:00:00+00:00",
                        "excerpt": "肚子不舒服",
                        "measurement": None,
                        "conclusions": [],
                    },
                }

        partner_adapter = FakePartnerAdapter(enabled=True)
        signer = FakeSigner()
        coordinator = PartnerWeixinIngressCoordinator(
            partner_adapter,
            signer,
            SlowClassifier(),
            expected_owner_sender_id=OWNER,
            subject=SUBJECT,
        )
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "text_batch_delay_seconds": 30,
                },
            ),
            coordinator,
            health_ingress_budget_seconds=0.05,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        started = time.monotonic()
        adapter._enqueue_text_event(
            MessageEvent(
                text="肚子不舒服", source=source, message_id="deadline-1"
            )
        )
        pending = None
        for _ in range(100):
            values = list(adapter._pending_text_batches.values())
            pending = values[0] if values else None
            if pending is not None:
                break
            await asyncio.sleep(0.005)

        self.assertTrue(classifier_started.is_set())
        self.assertIsNotNone(pending)
        self.assertLess(time.monotonic() - started, 0.15)
        self.assertFalse(classifier_finished.is_set())
        await asyncio.sleep(0.2)
        self.assertTrue(classifier_finished.is_set())
        self.assertFalse(any(call[0] == "ingress" for call in signer.calls))
        self.assertFalse(any(call[0] == "admit" for call in partner_adapter.calls))
        for task in list(adapter._pending_text_batch_tasks.values()):
            task.cancel()

    async def test_timeout_shows_processing_and_one_retry_reports_backfilled(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter

        class SlowThenCandidate:
            def __init__(self) -> None:
                self.calls = 0
                self.lock = threading.Lock()

            def classify(self, _envelope):
                with self.lock:
                    self.calls += 1
                    call = self.calls
                if call == 1:
                    time.sleep(0.25)
                return {
                    "decision": "candidate",
                    "candidate": {
                        "evidence_kind": "direct_statement",
                        "source_message_id": "retry-visible",
                        "source_utc": "2026-08-09T02:00:00+00:00",
                        "excerpt": "肚子不舒服",
                        "measurement": None,
                        "conclusions": [],
                    },
                }

        classifier = SlowThenCandidate()
        partner_adapter = FakePartnerAdapter(enabled=True)
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "text_batch_delay_seconds": 30,
                },
            ),
            PartnerWeixinIngressCoordinator(
                partner_adapter,
                FakeSigner(),
                classifier,
                expected_owner_sender_id=OWNER,
                subject=SUBJECT,
            ),
            health_ingress_budget_seconds=0.1,
            health_retry_enabled=True,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        adapter._enqueue_text_event(
            MessageEvent(
                text="肚子不舒服", source=source, message_id="retry-visible"
            )
        )

        pending = None
        for _ in range(200):
            values = list(adapter._pending_text_batches.values())
            pending = values[0] if values else None
            feedback = [item for item in partner_adapter.calls if item[0] == "feedback"]
            if pending is not None and feedback:
                break
            await asyncio.sleep(0.005)

        self.assertIsNotNone(pending)
        self.assertEqual(
            pending.metadata["health_steward_tail_marker"],
            "〔健康管家：记录处理中〕",
        )
        self.assertEqual(classifier.calls, 2)
        feedback = [item for item in partner_adapter.calls if item[0] == "feedback"]
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0][1][-1], "backfilled")
        for task in list(adapter._pending_text_batch_tasks.values()):
            task.cancel()

    async def test_second_classification_failure_reports_not_recorded_once(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter

        class FailingClassifier:
            def __init__(self) -> None:
                self.calls = 0

            def classify(self, _envelope):
                self.calls += 1
                raise RuntimeError("controlled-classification-failure")

        classifier = FailingClassifier()
        partner_adapter = FakePartnerAdapter(enabled=True)
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "text_batch_delay_seconds": 30,
                },
            ),
            PartnerWeixinIngressCoordinator(
                partner_adapter,
                FakeSigner(),
                classifier,
                expected_owner_sender_id=OWNER,
                subject=SUBJECT,
            ),
            health_ingress_budget_seconds=0.1,
            health_retry_enabled=True,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        adapter._enqueue_text_event(
            MessageEvent(text="可能不舒服", source=source, message_id="retry-fail")
        )
        for _ in range(200):
            feedback = [item for item in partner_adapter.calls if item[0] == "feedback"]
            if feedback:
                break
            await asyncio.sleep(0.005)

        self.assertEqual(classifier.calls, 2)
        feedback = [item for item in partner_adapter.calls if item[0] == "feedback"]
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0][1][-1], "not_recorded")
        for task in list(adapter._pending_text_batch_tasks.values()):
            task.cancel()

    async def test_committed_first_attempt_with_lost_response_reports_backfilled(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter

        class CommitThenDelayAdapter(FakePartnerAdapter):
            def admit_consented_profile_candidate(self, **kwargs):
                result = super().admit_consented_profile_candidate(**kwargs)
                time.sleep(0.25)
                return result

        classifier = FakeClassifier(
            {
                "decision": "candidate",
                "candidate": {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "committed-before-timeout",
                    "source_utc": "2026-08-09T02:00:00+00:00",
                    "excerpt": "头疼",
                    "measurement": None,
                    "conclusions": [],
                },
            }
        )
        partner_adapter = CommitThenDelayAdapter(enabled=True)
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "text_batch_delay_seconds": 30,
                },
            ),
            PartnerWeixinIngressCoordinator(
                partner_adapter,
                FakeSigner(),
                classifier,
                expected_owner_sender_id=OWNER,
                subject=SUBJECT,
            ),
            health_ingress_budget_seconds=0.1,
            health_retry_enabled=True,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        adapter._enqueue_text_event(
            MessageEvent(
                text="头疼", source=source, message_id="committed-before-timeout"
            )
        )
        for _ in range(200):
            feedback = [item for item in partner_adapter.calls if item[0] == "feedback"]
            if feedback:
                break
            await asyncio.sleep(0.005)

        feedback = [item for item in partner_adapter.calls if item[0] == "feedback"]
        self.assertEqual(len(classifier.envelopes), 1)
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0][1][-1], "backfilled")
        for task in list(adapter._pending_text_batch_tasks.values()):
            task.cancel()

    async def test_recording_stop_can_cancel_pending_retry_before_second_model_call(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter

        class FailingClassifier:
            def __init__(self) -> None:
                self.calls = 0

            def classify(self, _envelope):
                self.calls += 1
                raise RuntimeError("controlled-first-failure")

        classifier = FailingClassifier()
        partner_adapter = FakePartnerAdapter(enabled=True)
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "text_batch_delay_seconds": 30,
                },
            ),
            PartnerWeixinIngressCoordinator(
                partner_adapter,
                FakeSigner(),
                classifier,
                expected_owner_sender_id=OWNER,
                subject=SUBJECT,
            ),
            health_ingress_budget_seconds=0.1,
            health_retry_enabled=True,
            health_retry_delay_seconds=2.0,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        adapter._enqueue_text_event(
            MessageEvent(text="不太舒服", source=source, message_id="cancel-retry")
        )
        for _ in range(100):
            if adapter._health_retry_tasks:
                break
            await asyncio.sleep(0.005)
        partner_adapter.enabled = False
        for _ in range(80):
            if not adapter._health_retry_tasks:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(classifier.calls, 1)
        self.assertFalse(
            any(item[0] == "feedback" for item in partner_adapter.calls)
        )
        self.assertEqual(adapter._health_retry_tasks, {})
        for task in list(adapter._pending_text_batch_tasks.values()):
            task.cancel()

    async def test_stop_between_admission_check_and_retry_blocks_second_model_call(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter

        admission_checked = threading.Event()
        release_check = threading.Event()

        class StopRaceAdapter(FakePartnerAdapter):
            def profile_message_admitted(self, subject, sender_id, message_id):
                admission_checked.set()
                if not release_check.wait(2):
                    raise RuntimeError("admission-check-test-timeout")
                return False

        class FirstFailureThenCandidate:
            def __init__(self) -> None:
                self.calls = 0

            def classify(self, _envelope):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("controlled-first-failure")
                return {
                    "decision": "candidate",
                    "candidate": {
                        "evidence_kind": "direct_statement",
                        "source_message_id": "retry-stop-race",
                        "source_utc": "2026-08-09T02:00:00+00:00",
                        "excerpt": "头疼",
                        "measurement": None,
                        "conclusions": [],
                    },
                }

        classifier = FirstFailureThenCandidate()
        partner_adapter = StopRaceAdapter(enabled=True)
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "text_batch_delay_seconds": 30,
                },
            ),
            PartnerWeixinIngressCoordinator(
                partner_adapter,
                FakeSigner(),
                classifier,
                expected_owner_sender_id=OWNER,
                subject=SUBJECT,
            ),
            health_ingress_budget_seconds=0.2,
            health_retry_enabled=True,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        adapter._enqueue_text_event(
            MessageEvent(
                text="头疼", source=source, message_id="retry-stop-race"
            )
        )
        self.assertTrue(await asyncio.to_thread(admission_checked.wait, 2))
        partner_adapter.enabled = False
        release_check.set()
        for _ in range(100):
            if not adapter._health_retry_tasks:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(classifier.calls, 1)
        self.assertEqual(adapter._health_retry_tasks, {})
        self.assertFalse(
            any(item[0] == "feedback" for item in partner_adapter.calls)
        )
        for task in list(adapter._pending_text_batch_tasks.values()):
            task.cancel()

    async def test_deadline_starts_when_event_is_enqueued_not_when_task_runs(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter

        classifier = FakeClassifier({"decision": "none"})
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "text_batch_delay_seconds": 30,
                },
            ),
            PartnerWeixinIngressCoordinator(
                FakePartnerAdapter(enabled=True),
                FakeSigner(),
                classifier,
                expected_owner_sender_id=OWNER,
                subject=SUBJECT,
            ),
            health_ingress_budget_seconds=0.15,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        adapter._enqueue_text_event(
            MessageEvent(text="普通消息", source=source, message_id="queued-late")
        )
        time.sleep(0.2)
        event_loop_resumed = time.monotonic()
        pending = None
        for _ in range(100):
            values = list(adapter._pending_text_batches.values())
            pending = values[0] if values else None
            if pending is not None:
                break
            await asyncio.sleep(0.005)

        self.assertIsNotNone(pending)
        self.assertLess(time.monotonic() - event_loop_resumed, 0.08)
        self.assertEqual(classifier.envelopes, [])
        for task in list(adapter._pending_text_batch_tasks.values()):
            task.cancel()

    async def test_gateway_shutdown_cancellation_stops_late_sign_and_admit(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter

        classifier_started = threading.Event()

        class SlowClassifier:
            def classify(self, _envelope):
                classifier_started.set()
                time.sleep(0.2)
                return {
                    "decision": "candidate",
                    "candidate": {
                        "evidence_kind": "direct_statement",
                        "source_message_id": "shutdown-1",
                        "source_utc": "2026-08-09T02:00:00+00:00",
                        "excerpt": "肚子不舒服",
                        "measurement": None,
                        "conclusions": [],
                    },
                }

        partner_adapter = FakePartnerAdapter(enabled=True)
        signer = FakeSigner()
        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={"account_id": "partner-bot"},
            ),
            PartnerWeixinIngressCoordinator(
                partner_adapter,
                signer,
                SlowClassifier(),
                expected_owner_sender_id=OWNER,
                subject=SUBJECT,
            ),
            health_ingress_budget_seconds=1.0,
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        adapter._enqueue_text_event(
            MessageEvent(
                text="肚子不舒服", source=source, message_id="shutdown-1"
            )
        )
        for _ in range(100):
            if classifier_started.is_set():
                break
            await asyncio.sleep(0.005)
        self.assertTrue(classifier_started.is_set())
        health_task = next(iter(adapter._background_tasks))
        health_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await health_task
        await asyncio.sleep(0.25)

        self.assertFalse(any(call[0] == "ingress" for call in signer.calls))
        self.assertFalse(any(call[0] == "admit" for call in partner_adapter.calls))

    async def test_gateway_shutdown_cancellation_stops_late_health_answer_send(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent
        from weixin_adapter import PartnerHealthWeixinAdapter
        from weixin_ingress import IngressOutcome

        handler_started = threading.Event()
        cancellation_seen = threading.Event()
        late_send = threading.Event()

        class Coordinator:
            def prepare(self, _envelope, **_kwargs):
                return None

            def classify_and_admit(self, _envelope, **_kwargs):
                return IngressOutcome("health-related", health_related=True)

        class SlowHealthTurnHandler:
            def handle(
                self, _envelope, _outcome, *, cancellation_requested=None
            ) -> None:
                handler_started.set()
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    if cancellation_requested is not None and cancellation_requested():
                        cancellation_seen.set()
                        return
                    time.sleep(0.005)
                late_send.set()

        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={"account_id": "partner-bot"},
            ),
            Coordinator(),
            health_turn_handler=SlowHealthTurnHandler(),
        )
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        adapter._enqueue_text_event(
            MessageEvent(
                text="失眠时怎样调整作息？",
                source=source,
                message_id="shutdown-health-answer-1",
            )
        )
        for _ in range(100):
            if handler_started.is_set():
                break
            await asyncio.sleep(0.005)
        self.assertTrue(handler_started.is_set())

        health_task = next(iter(adapter._background_tasks))
        health_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await health_task
        for _ in range(100):
            if cancellation_seen.is_set():
                break
            await asyncio.sleep(0.005)

        self.assertTrue(cancellation_seen.is_set())
        self.assertFalse(late_send.is_set())
        self.assertEqual(adapter._pending_text_batches, {})

    async def test_confirmed_marker_is_appended_by_adapter_not_by_model(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import MessageEvent, SendResult
        from gateway.platforms.weixin import WeixinAdapter
        from gateway.session import build_session_key
        from weixin_adapter import PartnerHealthWeixinAdapter

        config = PlatformConfig(
            enabled=True,
            token="test-token",
            typing_indicator=False,
            extra={"account_id": "partner-bot"},
        )
        adapter = PartnerHealthWeixinAdapter(config, mock.Mock())
        source = adapter.build_source(
            chat_id=OWNER,
            chat_type="dm",
            user_id=OWNER,
            user_name=OWNER,
        )
        event = MessageEvent(text="我肚子不舒服", source=source, message_id="m-1")
        event.metadata["health_steward_tail_marker"] = "〔健康管家：画像已更新〕"

        async def handler(_event):
            return "普通模型生成的回复"

        adapter.set_message_handler(handler)
        session_key = build_session_key(source)
        adapter._active_sessions[session_key] = asyncio.Event()
        sent = []

        async def fake_native_send(_self, **kwargs):
            sent.append(kwargs["content"])
            return SendResult(success=True, message_id="sent-1")

        with mock.patch.object(WeixinAdapter, "send", new=fake_native_send):
            await adapter._process_message_background(event, session_key)

        self.assertEqual(
            sent,
            ["普通模型生成的回复\n\n〔健康管家：画像已更新〕"],
        )

    async def test_model_cannot_emit_reserved_health_marker_without_sidecar_change(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.base import SendResult
        from gateway.platforms.weixin import WeixinAdapter
        from weixin_adapter import PartnerHealthWeixinAdapter

        adapter = PartnerHealthWeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={"account_id": "partner-bot"},
            ),
            mock.Mock(),
        )
        sent = []

        async def fake_native_send(_self, **kwargs):
            sent.append(kwargs["content"])
            return SendResult(success=True, message_id="sent-ordinary")

        with mock.patch.object(WeixinAdapter, "send", new=fake_native_send):
            await adapter.send(
                OWNER,
                "普通模型自行声称成功\n\n〔健康管家：画像已更新〕",
            )

        self.assertEqual(sent, ["普通模型自行声称成功"])


@unittest.skipUnless(
    hasattr(socket, "AF_UNIX"),
    "AF_UNIX required",
)
class PrimaryIngressSeamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        sys.path.insert(0, str(HERMES_SOURCE))
        sys.path.insert(0, str(ROOT / "plugin" / "health-steward"))
        self.old_hermes_home = os.environ.get("HERMES_HOME")
        self.temp_home = tempfile.TemporaryDirectory()
        os.environ["HERMES_HOME"] = self.temp_home.name

    async def asyncTearDown(self) -> None:
        for path in (str(ROOT / "plugin" / "health-steward"), str(HERMES_SOURCE)):
            if path in sys.path:
                sys.path.remove(path)
        self.temp_home.cleanup()
        if self.old_hermes_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self.old_hermes_home

    async def test_real_format_health_turn_closes_through_all_production_adapters(self):
        from types import SimpleNamespace

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        from sidecar.adapter import PartnerHealthAdapter
        from sidecar.weixin_delivery import (
            DeliveryResult,
            WeixinHealthChannel,
        )
        from sidecar.receipt_signer import ReceiptSignerClient, ReceiptSignerServer
        from sidecar.server import HealthSidecarServer
        from sidecar.store import Ed25519InboundMessageVerifier
        from health_turn import HealthSourceCatalog, HealthTurnHandler
        from gateway.config import PlatformConfig
        from gateway.platforms.base import SendResult
        from gateway.platforms.weixin import WeixinAdapter
        from gateway.session import build_session_key
        from weixin_adapter import PartnerHealthWeixinAdapter

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

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sidecar_socket = root / "sidecar.sock"
            signer_socket = root / "signer.sock"
            peer_uid = os.getuid() if hasattr(os, "getuid") else 1001
            peer_gid = os.getgid() if hasattr(os, "getgid") else 1001
            if not hasattr(socket, "SO_PEERCRED"):
                uid_patch = mock.patch(
                    "sidecar.server._peer_uid", return_value=peer_uid
                )
                gid_patch = mock.patch(
                    "sidecar.server._peer_gid", return_value=peer_gid
                )
                signer_peer_patch = mock.patch(
                    "sidecar.receipt_signer._peer_pid_uid",
                    return_value=(os.getpid(), peer_uid),
                )
                uid_patch.start()
                gid_patch.start()
                signer_peer_patch.start()
                self.addCleanup(uid_patch.stop)
                self.addCleanup(gid_patch.stop)
                self.addCleanup(signer_peer_patch.stop)

            ready = threading.Event()
            source_url = "https://www.who.int/health-topics/abdominal-pain"

            class SourceFetch:
                def __init__(self) -> None:
                    self.calls = []

                def fetch(self, url, timeout_seconds=None):
                    self.calls.append((url, timeout_seconds))
                    return {
                        "url": url,
                        "version_hash": "who-abdominal-v1",
                        "source_type": "general_health_education",
                        "title": "Abdominal discomfort guidance",
                        "tags": {
                            "topic": ["digestive health"],
                            "symptom_behavior": ["abdominal discomfort"],
                            "target_population": ["adult"],
                            "evidence_type": ["health education"],
                            "region_language": ["global-zh"],
                            "freshness": ["current"],
                        },
                        "key_excerpt": "Seek care for severe or worsening symptoms.",
                        "raw_document": b"controlled public health source",
                    }

            source_fetch = SourceFetch()
            store = HealthSidecarStore(
                root / "state.enc",
                root / "state.key",
                message_verifier=Ed25519InboundMessageVerifier(public_bytes),
                expected_owner_sender_id=OWNER,
            )
            sidecar_server = HealthSidecarServer(
                str(sidecar_socket),
                store,
                allowed_uids={peer_uid},
                allowed_gids={peer_gid},
                ready_event=ready,
                ports=SimpleNamespace(
                    source_fetch=source_fetch,
                    memory_projection=None,
                ),
            )
            sidecar_thread = threading.Thread(
                target=sidecar_server.run_forever, daemon=True
            )
            sidecar_thread.start()
            self.addAsyncCleanup(
                self._stop_sidecar, sidecar_server, sidecar_thread
            )
            self.assertTrue(
                await asyncio.to_thread(ready.wait, 5),
                "sidecar did not become ready",
            )

            signer_server = ReceiptSignerServer(
                str(signer_socket),
                Ed25519ReceiptSigner(private_bytes),
                allowed_gateway_pid=os.getpid(),
                allowed_gateway_uid=peer_uid,
            )
            signer_thread = threading.Thread(
                target=signer_server.serve_forever, daemon=True
            )
            signer_thread.start()
            self.addAsyncCleanup(self._stop_signer, signer_server, signer_thread)
            for _ in range(100):
                if signer_socket.exists():
                    break
                await asyncio.sleep(0.01)

            adapter_port = PartnerHealthAdapter(str(sidecar_socket))
            signer_client = ReceiptSignerClient(str(signer_socket))

            class Classifier:
                def __init__(self) -> None:
                    self.message_ids = []

                def classify(self, envelope):
                    self.message_ids.append(envelope.message_id)
                    if envelope.message_text == "ordinary weather chat":
                        return {
                            "decision": "none",
                            "health_related": False,
                            "requires_source_verification": False,
                        }
                    return {
                        "decision": "candidate",
                        "health_related": True,
                        "requires_source_verification": True,
                        "candidate": {
                            "evidence_kind": "direct_statement",
                            "source_message_id": envelope.message_id,
                            "source_utc": envelope.message_utc,
                            "excerpt": envelope.message_text,
                            "measurement": None,
                            "conclusions": [
                                {
                                    "category": "state",
                                    "dedupe_key": "abdominal-discomfort",
                                    "text": "abdominal discomfort",
                                    "status": "fact",
                                    "priority": 3,
                                }
                            ],
                        },
                    }

            classifier = Classifier()
            coordinator = PartnerWeixinIngressCoordinator(
                adapter_port,
                signer_client,
                classifier,
                expected_owner_sender_id=OWNER,
            )

            class Responder:
                def __init__(self) -> None:
                    self.inputs = []

                def answer(self, answer_input):
                    self.inputs.append(answer_input)
                    card_ids = tuple(
                        card.card_id for card in answer_input.fresh_source_cards
                    )
                    return SimpleNamespace(
                        answer_text=(
                            "Use the verified guidance and seek care if symptoms worsen."
                        ),
                        used_source_card_ids=card_ids,
                    )

            class Transport:
                runtime_version = "test-hermes-v1"

                def __init__(self) -> None:
                    self.calls = []

                def send_text(self, recipient, message, client_id):
                    self.calls.append((recipient, message, client_id))
                    return DeliveryResult.accepted(client_id)

                def send_json_attachment(self, *_args, **_kwargs):
                    raise AssertionError("health turn must send text only")

            responder = Responder()
            transport = Transport()
            channel = WeixinHealthChannel(
                root / "weixin-delivery.sqlite3",
                transport,
                accepted_hermes_version="test-hermes-v1",
                audit_sink=adapter_port,
            )
            handler = HealthTurnHandler(
                context_loader=coordinator,
                source_reader=adapter_port,
                responder=responder,
                channel=channel,
                source_catalog=HealthSourceCatalog(
                    {"abdominal": source_url}
                ),
            )
            config = PlatformConfig(
                enabled=True,
                token="test-token",
                typing_indicator=False,
                extra={
                    "account_id": "partner-bot",
                    "dm_policy": "allowlist",
                    "allow_from": [OWNER],
                    "text_batch_delay_seconds": 30,
                },
            )
            weixin = PartnerHealthWeixinAdapter(
                config,
                coordinator,
                health_turn_handler=handler,
            )
            weixin._poll_session = object()

            async def no_typing_ticket(*_args, **_kwargs):
                return None

            weixin._maybe_fetch_typing_ticket = no_typing_ticket
            consent_event = {
                "from_user_id": OWNER,
                "to_user_id": "partner-bot",
                "message_id": "consent-real-1",
                "item_list": [
                    {"type": 1, "text_item": {"text": "启用健康记录"}}
                ],
            }
            await weixin._process_message(consent_event)
            for _ in range(100):
                if adapter_port.health_recording_enabled(SUBJECT, OWNER):
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(adapter_port.health_recording_enabled(SUBJECT, OWNER))

            health_event = {
                "from_user_id": OWNER,
                "to_user_id": "partner-bot",
                "message_id": "health-real-1",
                "item_list": [
                    {
                        "type": 1,
                        "text_item": {"text": "abdominal discomfort"},
                    }
                ],
            }
            await weixin._process_message(health_event)
            for _ in range(200):
                if len(transport.calls) == 2 and responder.inputs:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(classifier.message_ids, ["health-real-1"])
            self.assertEqual(weixin._pending_text_batches, {})
            self.assertEqual(len(transport.calls), 2)
            self.assertEqual(
                transport.calls[0][1],
                "正在核验资料",
            )
            self.assertIn(
                "Use the verified guidance",
                transport.calls[1][1],
            )
            self.assertIn("〔健康管家：画像已更新〕", transport.calls[1][1])
            self.assertEqual(source_fetch.calls, [(source_url, 20.0)])

            read_utc = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
            read_token = signer_client.sign_access(
                action="health.profile.read",
                subject=SUBJECT,
                actor_sender_id=OWNER,
                target_sender_id=OWNER,
                message_id="read-real-1",
                message_utc=read_utc,
            )
            profile = adapter_port.read_profile(
                SUBJECT, OWNER, "read-real-1", read_utc, read_token
            )
            self.assertEqual(profile["evidence"][0]["source_message_id"], "health-real-1")
            self.assertEqual(
                responder.inputs[0].current_version_id,
                profile["current_version_id"],
            )
            self.assertEqual(
                responder.inputs[0].relevant_evidence_ids,
                (profile["evidence"][0]["evidence_id"],),
            )
            self.assertEqual(
                len(responder.inputs[0].fresh_source_cards),
                1,
            )

            # A fresh authenticated message ID is a new health observation
            # even when its text is identical inside Hermes' fingerprint TTL.
            repeated_text_event = {
                **health_event,
                "message_id": "health-real-2",
            }
            await weixin._process_message(repeated_text_event)
            for _ in range(200):
                if len(transport.calls) == 4 and len(responder.inputs) == 2:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(
                classifier.message_ids,
                ["health-real-1", "health-real-2"],
            )
            self.assertEqual(len(responder.inputs), 2)
            self.assertEqual(len(transport.calls), 4)
            self.assertEqual(
                source_fetch.calls,
                [(source_url, 20.0), (source_url, 20.0)],
            )

            # Reprocessing the same authenticated Weixin message must stop
            # before a second model-visible context projection.  Native
            # Weixin dedup normally catches this first; the persisted sidecar
            # receipt consumption remains the restart/TTL fail-closed boundary.
            await weixin._process_message(health_event)
            await asyncio.sleep(0.05)
            self.assertEqual(len(responder.inputs), 2)
            self.assertEqual(len(transport.calls), 4)
            self.assertEqual(
                source_fetch.calls,
                [(source_url, 20.0), (source_url, 20.0)],
            )

            ordinary_event = {
                "from_user_id": OWNER,
                "to_user_id": "partner-bot",
                "message_id": "ordinary-real-1",
                "item_list": [
                    {
                        "type": 1,
                        "text_item": {"text": "ordinary weather chat"},
                    }
                ],
            }
            await weixin._process_message(ordinary_event)
            pending = None
            for _ in range(200):
                values = list(weixin._pending_text_batches.values())
                pending = values[0] if values else None
                if pending is not None:
                    break
                await asyncio.sleep(0.01)
            self.assertIsNotNone(pending)
            assert pending is not None
            self.assertEqual(pending.text, "ordinary weather chat")
            metadata_text = json.dumps(
                pending.metadata, ensure_ascii=False, sort_keys=True
            )
            for forbidden in (
                "profile_summary_zh",
                "evidence_ids",
                "source_cards",
                "abdominal discomfort",
            ):
                self.assertNotIn(forbidden, metadata_text)

            ordinary_inputs = []

            async def ordinary_handler(event):
                ordinary_inputs.append(event.text)
                return "ordinary reply"

            weixin.set_message_handler(ordinary_handler)
            session_key = build_session_key(pending.source)
            weixin._active_sessions[session_key] = asyncio.Event()
            native_sent = []

            async def fake_native_send(_self, **kwargs):
                native_sent.append(kwargs["content"])
                return SendResult(success=True, message_id="ordinary-visible-1")

            with mock.patch.object(WeixinAdapter, "send", new=fake_native_send):
                await weixin._process_message_background(pending, session_key)
            self.assertEqual(ordinary_inputs, ["ordinary weather chat"])
            self.assertEqual(native_sent, ["ordinary reply"])
            self.assertEqual(len(transport.calls), 2)

            audit = adapter_port.read_audit()
            audit_text = json.dumps(audit, ensure_ascii=False)
            self.assertIn("profile_candidate_accepted", audit_text)
            self.assertNotIn("abdominal discomfort", audit_text)

            for task in list(weixin._pending_text_batch_tasks.values()):
                task.cancel()

    @staticmethod
    async def _stop_sidecar(server, thread) -> None:
        server.stop()
        thread.join(2)

    @staticmethod
    async def _stop_signer(server, thread) -> None:
        server.close()
        thread.join(2)


if __name__ == "__main__":
    unittest.main()

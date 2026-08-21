from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sidecar.profile import ProfileStoreError
from sidecar.store import HealthSidecarStore, HmacInboundMessageVerifier


OWNER = "wx-owner"
VIEWER = "wx-viewer"
ADMIN = "wx-admin"
NEW_OWNER = "wx-new-owner"
SUBJECT = "profile"


class FixedClock:
    def __init__(self, value: dt.datetime) -> None:
        self.value = value

    def now_utc(self) -> dt.datetime:
        return self.value


class OwnerRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.clock = FixedClock(
            dt.datetime(2026, 8, 11, 2, 0, tzinfo=dt.timezone.utc)
        )
        self.verifier = HmacInboundMessageVerifier(b"r" * 32)
        self.store = HealthSidecarStore(
            root / "health.state",
            root / "health.key",
            clock=self.clock,
            message_verifier=self.verifier,
            expected_owner_sender_id=OWNER,
            expected_viewer_sender_id=VIEWER,
        )
        self.initial_code = self._enable()["recovery_code"]
        self._admit_profile()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _utc(self) -> str:
        return self.clock.now_utc().isoformat()

    def _access_token(
        self,
        action: str,
        actor_sender_id: str,
        target_sender_id: str,
        message_id: str,
    ) -> str:
        return self.verifier.sign_access_receipt(
            action=action,
            subject=SUBJECT,
            actor_sender_id=actor_sender_id,
            target_sender_id=target_sender_id,
            message_id=message_id,
            message_utc=self._utc(),
        )

    def _enable(self):
        message_id = "enable"
        return self.store.enable_health_recording(
            SUBJECT,
            OWNER,
            message_id,
            self._utc(),
            self._access_token(
                "health.recording.enable",
                OWNER,
                OWNER,
                message_id,
            ),
        )

    def _admit_profile(self) -> None:
        message_id = "profile-write"
        text = "我最近睡不好"
        token = self.verifier.sign_ingress_receipt(
            action="health.profile.message.admit",
            subject=SUBJECT,
            sender_id=OWNER,
            message_id=message_id,
            message_utc=self._utc(),
            message_text=text,
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
            attempt_utc=self._utc(),
        )
        self.store.admit_consented_profile_candidate(
            subject=SUBJECT,
            sender_id=OWNER,
            message_id=message_id,
            message_utc=self._utc(),
            attempt_utc=self._utc(),
            message_text=text,
            evidence_kind="direct_statement",
            channel="weixin",
            profile_name="partner",
            verification_token=token,
            candidate={
                "evidence_kind": "direct_statement",
                "source_message_id": message_id,
                "source_utc": self._utc(),
                "excerpt": text,
                "measurement": None,
                "conclusions": [
                    {
                        "category": "state",
                        "dedupe_key": "sleep",
                        "text": "最近睡不好",
                        "status": "fact",
                        "priority": 1,
                    }
                ],
            },
        )

    def _transfer(self, new_owner: str, message_id: str = "transfer"):
        return self.store.transfer_profile_owner(
            SUBJECT,
            OWNER,
            new_owner,
            message_id,
            self._utc(),
            self._access_token(
                "health.profile.owner.transfer",
                OWNER,
                new_owner,
                message_id,
            ),
        )

    def _recover(
        self,
        new_owner: str,
        recovery_code: str,
        message_id: str,
    ):
        return self.store.recover_profile_owner(
            SUBJECT,
            new_owner,
            recovery_code,
            message_id,
            self._utc(),
            self._access_token(
                "health.profile.owner.recover",
                new_owner,
                new_owner,
                message_id,
            ),
        )

    def test_initial_code_is_high_entropy_verifier_only_and_audit_safe(self):
        self.assertRegex(self.initial_code, r"^[A-Za-z0-9_-]{43}$")
        consent = self.store.read_subject_status(
            "__health_recording_consent__", _allow_profile_state=True
        )
        self.assertIsInstance(consent, dict)
        self.assertNotIn(self.initial_code, json.dumps(consent, ensure_ascii=False))
        audit = json.dumps(self.store.read_audit_events(), ensure_ascii=False)
        self.assertNotIn(self.initial_code, audit)

    def test_old_owner_transfer_preserves_profile_and_revokes_old_control(self):
        before = self.store.read_profile(SUBJECT, OWNER)
        result = self._transfer(NEW_OWNER)
        self.assertTrue(result["changed"])
        self.assertRegex(result["recovery_code"], r"^[A-Za-z0-9_-]{43}$")
        after = self.store.read_profile(SUBJECT, NEW_OWNER)
        self.assertEqual(before["evidence"], after["evidence"])
        self.assertEqual(before["viewer_grants"], after["viewer_grants"])
        self.assertFalse(self.store.health_recording_enabled(SUBJECT, OWNER))
        self.assertTrue(self.store.health_recording_enabled(SUBJECT, NEW_OWNER))
        with self.assertRaisesRegex(ProfileStoreError, "profile-read-not-authorized"):
            self.store.read_profile(SUBJECT, OWNER)

    def test_recovery_rotates_the_code_and_old_code_cannot_rebind_twice(self):
        result = self._recover(NEW_OWNER, self.initial_code, "recover-first")
        next_code = result["recovery_code"]
        self.assertNotEqual(next_code, self.initial_code)
        self.assertTrue(self.store.health_recording_enabled(SUBJECT, NEW_OWNER))
        with self.assertRaisesRegex(ProfileStoreError, "owner-recovery-unavailable"):
            self._recover(ADMIN, self.initial_code, "recover-old-code")
        self.assertFalse(self.store.health_recording_enabled(SUBJECT, ADMIN))

    def test_viewer_cannot_recover_even_with_the_valid_code(self):
        with self.assertRaisesRegex(ProfileStoreError, "owner-recovery-not-authorized"):
            self._recover(VIEWER, self.initial_code, "viewer-recover")
        self.assertTrue(self.store.health_recording_enabled(SUBJECT, OWNER))

    def test_concurrent_same_code_has_exactly_one_success(self):
        outcomes: list[object] = []
        barrier = threading.Barrier(2)

        def attempt(sender_id: str, message_id: str) -> None:
            try:
                barrier.wait(timeout=2)
                outcomes.append(self._recover(sender_id, self.initial_code, message_id))
            except Exception as exc:
                outcomes.append(exc)

        first = threading.Thread(
            target=attempt, args=("wx-new-a", "recover-concurrent-a")
        )
        second = threading.Thread(
            target=attempt, args=("wx-new-b", "recover-concurrent-b")
        )
        first.start()
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)

        successes = [item for item in outcomes if isinstance(item, dict)]
        failures = [item for item in outcomes if isinstance(item, Exception)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIn(
            self.store.read_profile(SUBJECT, successes[0]["new_owner_sender_id"])[
                "owner_sender_id"
            ],
            {"wx-new-a", "wx-new-b"},
        )


if __name__ == "__main__":
    unittest.main()

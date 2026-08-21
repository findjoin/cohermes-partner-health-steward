from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from job_authorization import (  # noqa: E402
    issue_job_action_authorization,
    verify_job_action_authorization,
)
from sidecar.profile import ProfileStoreError  # noqa: E402
from sidecar.store import HealthSidecarStore  # noqa: E402


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class JobAuthorizationTests(unittest.TestCase):
    SECRET = b"job-authorization-test-secret-0001"
    NOW = dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc)

    def _issue(self, **overrides: object) -> str:
        claims: dict[str, object] = {
            "role": "daily_profile_review",
            "subject": "profile",
            "capability": "verified-native-job-capability",
            "issued_utc": self.NOW,
        }
        claims.update(overrides)
        return issue_job_action_authorization(self.SECRET, **claims)

    def test_proof_is_bound_to_role_subject_time_and_tamper_protected(self) -> None:
        token = self._issue()
        self.assertIsNotNone(
            verify_job_action_authorization(
                self.SECRET,
                token,
                role="daily_profile_review",
                subject="profile",
                now_utc=self.NOW,
            )
        )
        self.assertIsNone(
            verify_job_action_authorization(
                self.SECRET,
                token,
                role="due_task_dispatch",
                subject="profile",
                now_utc=self.NOW,
            )
        )
        self.assertIsNone(
            verify_job_action_authorization(
                self.SECRET,
                token,
                role="daily_profile_review",
                subject="other-profile",
                now_utc=self.NOW,
            )
        )
        self.assertIsNone(
            verify_job_action_authorization(
                self.SECRET,
                token + "x",
                role="daily_profile_review",
                subject="profile",
                now_utc=self.NOW,
            )
        )
        self.assertIsNone(
            verify_job_action_authorization(
                self.SECRET,
                token,
                role="daily_profile_review",
                subject="profile",
                now_utc=self.NOW + dt.timedelta(minutes=11),
            )
        )

    def test_verified_proof_nonce_is_durably_one_time_even_after_store_restart(self) -> None:
        clock = FixedClock(self.NOW)
        token = self._issue()
        claims = verify_job_action_authorization(
            self.SECRET,
            token,
            role="daily_profile_review",
            subject="profile",
            now_utc=clock.now_utc(),
        )
        self.assertIsNotNone(claims)
        assert claims is not None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = HealthSidecarStore(
                root / "state.sqlite.enc", root / "sidecar.key", clock=clock
            )
            first.consume_job_action_authorization(
                claims["nonce"], claims["issued_utc"]
            )

            restarted = HealthSidecarStore(
                root / "state.sqlite.enc", root / "sidecar.key", clock=clock
            )
            with self.assertRaisesRegex(ProfileStoreError, "job-authorization-replayed"):
                restarted.consume_job_action_authorization(
                    claims["nonce"], claims["issued_utc"]
                )


if __name__ == "__main__":
    unittest.main()

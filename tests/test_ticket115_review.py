"""Ticket 115 owner-local-day review authority tests."""

from __future__ import annotations

import unittest

from partner_health_steward.review import DailyReviewEngine, DailyReviewLedger


class Ticket115ReviewTests(unittest.TestCase):
    def test_current_day_pending_refreshes_when_authoritative_basis_changes(self) -> None:
        ledger = DailyReviewLedger.empty("owner-A", "partner-installation")
        first = DailyReviewEngine.prepare(
            ledger,
            owner_id="owner-A",
            installation_id="partner-installation",
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T01:00:00+00:00",
            current_state_digest="sha256:" + ("1" * 64),
            changed=False,
            action_refs=(),
        )

        refreshed = DailyReviewEngine.prepare(
            first.ledger,
            owner_id="owner-A",
            installation_id="partner-installation",
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T02:00:00+00:00",
            current_state_digest="sha256:" + ("2" * 64),
            changed=True,
            action_refs=("task:review-summary",),
        )

        self.assertEqual(refreshed.outcome, "current-day-pending-refreshed")
        self.assertFalse(refreshed.replayed)
        self.assertTrue(refreshed.notification_required)
        self.assertEqual(refreshed.ledger.version, first.ledger.version + 1)
        self.assertEqual(
            refreshed.ledger.pending.state_digest,
            "sha256:" + ("2" * 64),
        )
        self.assertEqual(
            refreshed.ledger.pending.action_refs,
            ("task:review-summary",),
        )


if __name__ == "__main__":
    unittest.main()

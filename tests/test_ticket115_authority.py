"""Ticket 115 controlled-effect authority boundary tests."""

from __future__ import annotations

import unittest

from partner_health_steward.authority import (
    AuthoritySnapshot,
    AuthorityValidationError,
    EffectIntent,
)


class Ticket115AuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = AuthoritySnapshot(
            installation_id="partner-installation",
            generation=7,
            revision_digest="sha256:" + ("1" * 64),
            transition_id="transition:ticket115",
            writer_fence="writer-fence:ticket115",
            terminal=False,
            site="partner-site",
        )

    def test_owner_delivery_is_a_supported_controlled_effect(self) -> None:
        intent = EffectIntent(
            effect_id="effect:owner-delivery:daily-review",
            effect_kind="owner-delivery",
            intent_digest="sha256:" + ("2" * 64),
            authority=self.authority,
            business_source_causal_id="outbox:daily-review:2026-08-24",
        )

        self.assertEqual(EffectIntent.from_storage(intent.to_storage()), intent)

    def test_contact_delivery_remains_disabled(self) -> None:
        with self.assertRaises(AuthorityValidationError):
            EffectIntent(
                effect_id="effect:contact-delivery:disabled",
                effect_kind="contact-delivery",
                intent_digest="sha256:" + ("3" * 64),
                authority=self.authority,
            )


if __name__ == "__main__":
    unittest.main()

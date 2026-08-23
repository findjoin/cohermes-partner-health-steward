from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace

from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.coordination import DailyHealthState
from partner_health_steward.portrait_schema import (
    FIRST_RELEASE_PORTRAIT_SCHEMA,
    PORTRAIT_DOMAIN_REFS,
    PORTRAIT_SCHEMA_VERSION,
    PORTRAIT_TOPIC_REFS,
    PORTRAIT_TOPIC_REFS_BY_DOMAIN,
    PortraitSchemaRelease,
    PortraitSchemaValidationError,
    validate_topic_ref,
)


class Ticket112PortraitSchemaTests(unittest.TestCase):
    def test_first_release_contains_exactly_45_ordered_basic_topics(self) -> None:
        self.assertEqual(PORTRAIT_SCHEMA_VERSION, "portrait-schema-v1")
        self.assertEqual(len(PORTRAIT_DOMAIN_REFS), 6)
        self.assertEqual(len(PORTRAIT_TOPIC_REFS), 45)
        self.assertEqual(len(set(PORTRAIT_TOPIC_REFS)), 45)
        self.assertEqual(
            FIRST_RELEASE_PORTRAIT_SCHEMA.ordered_topic_refs,
            PORTRAIT_TOPIC_REFS,
        )

    def test_each_domain_has_its_fixed_basic_topic_count(self) -> None:
        self.assertEqual(
            {
                domain_ref: len(PORTRAIT_TOPIC_REFS_BY_DOMAIN[domain_ref])
                for domain_ref in PORTRAIT_DOMAIN_REFS
            },
            {
                "clinical-and-safety": 10,
                "physical-function-and-experience": 9,
                "mental-cognitive-and-wellbeing": 8,
                "activity-and-social-participation": 7,
                "health-behaviour-and-exposure": 6,
                "owner-goals-values-and-care-preferences": 5,
            },
        )

    def test_release_is_immutable_and_has_a_stable_digest(self) -> None:
        self.assertEqual(
            FIRST_RELEASE_PORTRAIT_SCHEMA.digest,
            "sha256:e76e787c18b14eff89a6705a1255c92a3905ca1dd3411c364d30e3142fbea155",
        )
        with self.assertRaises(FrozenInstanceError):
            setattr(FIRST_RELEASE_PORTRAIT_SCHEMA, "version", "changed")
        with self.assertRaises(TypeError):
            PORTRAIT_TOPIC_REFS_BY_DOMAIN["clinical-and-safety"] = ()  # type: ignore[index]

    def test_exact_wire_round_trip_rejects_an_extra_field(self) -> None:
        wire = FIRST_RELEASE_PORTRAIT_SCHEMA.to_wire()
        self.assertEqual(
            PortraitSchemaRelease.from_wire(wire),
            FIRST_RELEASE_PORTRAIT_SCHEMA,
        )

        extra = dict(wire)
        extra["future_extension"] = []
        with self.assertRaises(PortraitSchemaValidationError):
            PortraitSchemaRelease.from_wire(extra)

    def test_wire_rejects_schema_drift_and_digest_forgery(self) -> None:
        changed_topics = FIRST_RELEASE_PORTRAIT_SCHEMA.to_wire()
        assert type(changed_topics["ordered_topic_refs"]) is list
        changed_topics["ordered_topic_refs"] = [
            *changed_topics["ordered_topic_refs"],
            "clinical-and-safety/future-child",
        ]
        with self.assertRaises(PortraitSchemaValidationError):
            PortraitSchemaRelease.from_wire(changed_topics)

        forged_digest = FIRST_RELEASE_PORTRAIT_SCHEMA.to_wire()
        forged_digest["digest"] = "sha256:" + ("0" * 64)
        with self.assertRaises(PortraitSchemaValidationError):
            PortraitSchemaRelease.from_wire(forged_digest)

    def test_only_fixed_topic_references_are_valid(self) -> None:
        sleep = "physical-function-and-experience/sleep"
        sleep_routine = "health-behaviour-and-exposure/sleep-routine"
        self.assertEqual(validate_topic_ref(sleep), sleep)
        self.assertEqual(validate_topic_ref(sleep_routine), sleep_routine)

        for unknown in (
            "clinical-and-safety/foo",
            "new-domain/sleep",
            "physical-function-and-experience/sleep/child",
            " physical-function-and-experience/sleep",
        ):
            with self.subTest(unknown=unknown):
                with self.assertRaises(PortraitSchemaValidationError):
                    validate_topic_ref(unknown)

    def test_daily_state_wire_binds_the_exact_schema_identity(self) -> None:
        state = DailyHealthState.empty()
        wire = state.to_storage()

        self.assertEqual(wire["portrait_schema_version"], PORTRAIT_SCHEMA_VERSION)
        self.assertEqual(
            wire["portrait_schema_digest"],
            FIRST_RELEASE_PORTRAIT_SCHEMA.digest,
        )
        self.assertEqual(DailyHealthState.from_storage(wire), state)

        for field, forged_value in (
            ("portrait_schema_version", "portrait-schema-v2"),
            ("portrait_schema_digest", "sha256:" + ("0" * 64)),
        ):
            with self.subTest(field=field):
                forged = dict(wire)
                forged[field] = forged_value
                with self.assertRaises(AuthorityValidationError):
                    DailyHealthState.from_storage(forged)

    def test_empty_projection_and_navigation_show_all_fixed_topics_unknown(self) -> None:
        projection = DailyHealthState.empty().projection

        self.assertEqual(projection.portrait_topic_refs, PORTRAIT_TOPIC_REFS)
        self.assertEqual(
            tuple(item.topic_ref for item in projection.topic_views),
            PORTRAIT_TOPIC_REFS,
        )
        self.assertTrue(
            all(item.current_status == "unknown" for item in projection.topic_views)
        )
        self.assertEqual(projection.unknown_domains, PORTRAIT_DOMAIN_REFS)
        self.assertEqual(
            DailyHealthState.empty().navigation.portrait_topic_refs,
            PORTRAIT_TOPIC_REFS,
        )

    def test_projection_rejects_domain_status_or_topic_order_drift(self) -> None:
        projection = DailyHealthState.empty().projection
        first_known = replace(projection.topic_views[0], current_status="known")

        with self.assertRaises(AuthorityValidationError):
            replace(
                projection,
                topic_views=(first_known, *projection.topic_views[1:]),
            )
        with self.assertRaises(AuthorityValidationError):
            replace(
                projection,
                portrait_topic_refs=tuple(reversed(PORTRAIT_TOPIC_REFS)),
            )

    def test_coordination_boundary_normalizes_unknown_topic_errors(self) -> None:
        projection = DailyHealthState.empty().projection

        with self.assertRaises(AuthorityValidationError) as raised:
            replace(
                projection.topic_views[0],
                topic_ref="clinical-and-safety/future-child",
            )
        self.assertIsInstance(raised.exception.__cause__, PortraitSchemaValidationError)


if __name__ == "__main__":
    unittest.main()

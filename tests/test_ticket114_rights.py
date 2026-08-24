"""Ticket 114 slice 3 RED: owner-scoped rights over Ticket 112 state.

The rights service is deliberately stateless. Its only input authority is a
managed projection formed from ``DailyHealthState``; correction returns a
pending Ticket 112 maintenance draft and cannot mutate or replace that state.
There is no public rights ``seed``/``state`` authority and no export import or
write path.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from typing import Any

from partner_health_steward import rights
from partner_health_steward.coordination import (
    AtomicEvidenceClaim,
    DailyHealthState,
    EvidenceApplicabilityChange,
    EvidenceCard,
    EvidenceMaintenanceRequest,
    EvidenceRelation,
    EvidenceSeriesKey,
    OwnerCorrectionRevision,
    PersonalHealthFields,
)
from partner_health_steward.evidence_profile import PersonalEvidenceProfile


OWNER = "owner-synthetic"
OTHER_OWNER = "owner-not-authorized"
INSTALLATION = "installation-synthetic"
OTHER_INSTALLATION = "installation-not-current"
CORRECTED_AT = "2026-08-24T02:00:00+00:00"
EXPORTED_AT = "2026-08-24T02:30:00+00:00"
TOPIC_REF = "physical-function-and-experience/sleep"


class _ForgedPermission(str):
    """A caller-controlled string subtype must not cross the permission seam."""


def _claim(
    content: str,
    *,
    occurred_at: str,
    purpose: str = "maintain-current-evidence",
) -> AtomicEvidenceClaim:
    return AtomicEvidenceClaim(
        content=content,
        evidence_type="personal-health",
        source_kind="owner-statement",
        occurred_at=occurred_at,
        applicable_period=f"{occurred_at}-night",
        purpose=purpose,
        uncertainty="owner subjective report",
        limitations=("one report does not establish a long-term trend",),
        proves=(content,),
        does_not_prove=("sleep diagnosis",),
        topic_refs=(TOPIC_REF,),
        specific_fields=PersonalHealthFields("owner-statement"),
        series_key=EvidenceSeriesKey(
            "personal-health",
            "subjective-sleep-experience",
            PersonalEvidenceProfile("owner-statement"),
            "single-night",
        ),
        time_certainty="known",
    )


def _card(
    source_causal_id: str,
    claim: AtomicEvidenceClaim,
    *,
    recorded_at: str,
) -> EvidenceCard:
    return EvidenceCard.from_claim(
        source_causal_id,
        claim,
        recorded_at=recorded_at,
    )


class Ticket114RightsTests(unittest.TestCase):
    """One visible method per Ticket 114 A3 behavior case."""

    maxDiff = None

    def setUp(self) -> None:
        old_claim = _claim(
            "owner initially reported poor sleep",
            occurred_at="2026-08-22",
        )
        self.old_card = _card(
            "ticket114-rights-old",
            old_claim,
            recorded_at="2026-08-23T00:30:00+00:00",
        )
        successor_claim = replace(
            old_claim,
            content="owner corrected the sleep report to fair",
            proves=("owner corrected the sleep report to fair",),
            purpose="correct-personal-evidence",
        )
        self.successor_card = _card(
            "ticket114-rights-existing-correction",
            successor_claim,
            recorded_at="2026-08-23T01:00:00+00:00",
        )
        self.other_current_card = _card(
            "ticket114-rights-other-current",
            _claim(
                "owner reported restorative sleep on the next night",
                occurred_at="2026-08-23",
            ),
            recorded_at="2026-08-24T01:00:00+00:00",
        )
        self.revoked_card = _card(
            "ticket114-rights-revoked",
            _claim(
                "owner report whose managed-read permission was revoked",
                occurred_at="2026-08-21",
            ),
            recorded_at="2026-08-22T01:00:00+00:00",
        )
        correction_relation = EvidenceRelation(
            self.successor_card.evidence_id,
            "history",
            "corrects",
            "evidence-card",
            self.old_card.evidence_id,
        )
        applicability_change = EvidenceApplicabilityChange(
            target_evidence_id=self.old_card.evidence_id,
            applicability="corrected",
            reason="owner corrected the prior sleep report",
            successor_evidence_id=self.successor_card.evidence_id,
            decision_digest="sha256:" + "a" * 64,
            changed_at="2026-08-23T01:00:00+00:00",
        )
        self.daily_state = DailyHealthState(
            evidence_cards=(
                self.old_card,
                self.successor_card,
                self.other_current_card,
                self.revoked_card,
            ),
            portrait_topics=(),
            evidence_relations=(correction_relation,),
            processed_source_causal_ids=(),
            evidence_applicability_changes=(applicability_change,),
        )
        self.permitted_object_refs = (
            self.old_card.evidence_id,
            self.other_current_card.evidence_id,
        )
        self.revoked_object_refs = (self.revoked_card.evidence_id,)

    def _projection(self) -> Any:
        return rights.ManagedRightsService._project_from_daily_state(
            self.daily_state,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            permitted_object_refs=self.permitted_object_refs,
            revoked_object_refs=self.revoked_object_refs,
        )

    def _reference(
        self,
        card: EvidenceCard,
        *,
        version: int,
        installation_id: str = INSTALLATION,
    ) -> Any:
        return rights.ManagedObjectReference(
            object_ref=card.evidence_id,
            installation_id=installation_id,
            version=version,
        )

    @property
    def successor_ref(self) -> Any:
        return self._reference(self.old_card, version=2)

    @property
    def other_current_ref(self) -> Any:
        return self._reference(self.other_current_card, version=1)

    def _read(
        self,
        *requested_refs: Any,
        requester_owner_id: str = OWNER,
        projection: Any | None = None,
        permission: object = "health_data.read",
    ) -> tuple[rights.ManagedObject, ...]:
        return rights.ManagedRightsService.managed_read(
            self._projection() if projection is None else projection,
            requester_owner_id=requester_owner_id,
            permission=permission,
            requested_refs=tuple(requested_refs),
        )

    def _correct(
        self,
        *,
        requester_owner_id: str = OWNER,
        projection: Any | None = None,
        permission: object = "health_data.correct",
        target_ref: Any | None = None,
    ) -> Any:
        replacement_claim = _claim(
            "owner corrected the sleep report to good",
            occurred_at="2026-08-22",
            purpose="correct-personal-evidence",
        )
        return rights.ManagedRightsService.correct(
            self._projection() if projection is None else projection,
            requester_owner_id=requester_owner_id,
            permission=permission,
            target_ref=self.successor_ref if target_ref is None else target_ref,
            correction_id="correction:synthetic-2",
            reason="owner corrected the recorded sleep assessment",
            corrected_at_utc=CORRECTED_AT,
            replacement_claim=replacement_claim,
            correction_source_refs=("source:owner-correction:synthetic-2",),
            affected_object_refs=(
                "task:synthetic-1",
                f"portrait-topic:{TOPIC_REF}",
            ),
            disposition_requests=("withdraw_current", "rejudge"),
        )

    def _export(
        self,
        *,
        requester_owner_id: str = OWNER,
        projection: Any | None = None,
        requested_refs: tuple[Any, ...] | None = None,
        permission: object = "health_data.export",
    ) -> Any:
        return rights.ManagedRightsService.export(
            self._projection() if projection is None else projection,
            requester_owner_id=requester_owner_id,
            permission=permission,
            requested_refs=(
                (self.successor_ref, self.other_current_ref)
                if requested_refs is None
                else requested_refs
            ),
            snapshot_id="export-snapshot:synthetic-1",
            created_at_utc=EXPORTED_AT,
        )

    def test_114_a3_c01_non_owner_managed_read_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._read(self.successor_ref, requester_owner_id=OTHER_OWNER)

    def test_114_a3_c02_non_owner_correction_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._correct(requester_owner_id=OTHER_OWNER)

    def test_114_a3_c03_non_owner_export_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._export(requester_owner_id=OTHER_OWNER)

    def test_114_a3_c04_scoped_read_returns_only_current_authorized_objects(self) -> None:
        objects = self._read(self.successor_ref, self.other_current_ref)
        self.assertEqual(
            tuple(
                (
                    item.object_ref,
                    item.current,
                    item.version,
                    item.source_refs,
                    item.evidence_refs,
                )
                for item in objects
            ),
            (
                (
                    self.old_card.evidence_id,
                    True,
                    2,
                    (self.successor_card.source_causal_id,),
                    (self.successor_card.evidence_id,),
                ),
                (
                    self.other_current_card.evidence_id,
                    True,
                    1,
                    (self.other_current_card.source_causal_id,),
                    (self.other_current_card.evidence_id,),
                ),
            ),
        )

    def test_114_a3_c05_correction_returns_pending_ticket112_draft(self) -> None:
        before_digest = self.daily_state.digest
        pending = self._correct()
        self.assertIs(type(pending), rights.PendingCorrectionDraft)
        self.assertEqual(self.daily_state.digest, before_digest)
        self.assertEqual(
            (
                pending.owner_id,
                pending.installation_id,
                pending.base_state_digest,
                pending.target_ref,
                pending.revision.object_ref,
                pending.revision.previous_version,
                pending.revision.revision_version,
                pending.revision.reason,
                pending.revision.corrected_at_utc,
                pending.revision.affected_object_refs,
                pending.revision.disposition_requests,
                pending.maintenance_request.action,
                pending.maintenance_request.target_evidence_ids,
                pending.maintenance_request.reason,
            ),
            (
                OWNER,
                INSTALLATION,
                before_digest,
                self.successor_ref,
                self.old_card.evidence_id,
                2,
                3,
                "owner corrected the recorded sleep assessment",
                CORRECTED_AT,
                ("task:synthetic-1", f"portrait-topic:{TOPIC_REF}"),
                ("withdraw_current", "rejudge"),
                "correct",
                (self.successor_card.evidence_id,),
                "owner corrected the recorded sleep assessment",
            ),
        )
        self.assertIs(type(pending.maintenance_request), EvidenceMaintenanceRequest)
        self.assertEqual(
            pending.maintenance_request.replacement_claim.content,
            "owner corrected the sleep report to good",
        )
        self.assertFalse(
            any(
                hasattr(pending, name)
                for name in ("state", "current_object", "successor_object", "apply")
            )
        )

    def test_114_a3_c06_export_serializes_finite_snapshot(self) -> None:
        exported = self._export()
        self.assertEqual(
            (
                exported.snapshot.snapshot_id,
                exported.snapshot.schema_version,
                exported.snapshot.source_state_digest,
                exported.snapshot.created_at_utc,
                exported.snapshot.object_refs,
                tuple((item.object_ref, item.version) for item in exported.objects),
            ),
            (
                "export-snapshot:synthetic-1",
                rights.MANAGED_EXPORT_SCHEMA_VERSION,
                self.daily_state.digest,
                EXPORTED_AT,
                (
                    self.old_card.evidence_id,
                    self.other_current_card.evidence_id,
                ),
                (
                    (self.old_card.evidence_id, 2),
                    (self.other_current_card.evidence_id, 1),
                ),
            ),
        )

    def test_114_a3_c07_export_round_trips_through_schema_parser(self) -> None:
        exported = self._export()
        serialized = json.dumps(
            exported.to_wire(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        parsed = rights.ManagedExport.from_wire(json.loads(serialized))
        self.assertEqual(parsed.to_wire(), exported.to_wire())

    def test_114_a3_c08_export_has_no_import_write_or_second_state_path(self) -> None:
        projection = self._projection()
        exported = self._export(projection=projection)
        forbidden = (
            "import_snapshot",
            "import_export",
            "apply",
            "apply_export",
            "write",
            "write_export",
        )
        self.assertEqual(
            (
                hasattr(rights.ManagedRightsService, "seed"),
                hasattr(rights.ManagedRightsService, "state"),
                hasattr(rights.ManagedRightsService, "project"),
                hasattr(projection, "state"),
                tuple(name for name in forbidden if hasattr(exported, name)),
                tuple(name for name in forbidden if hasattr(rights.ManagedExport, name)),
                tuple(name for name in forbidden if hasattr(rights, name)),
            ),
            (False, False, False, False, (), (), ()),
        )

    def test_114_a3_c09_superseded_current_false_reference_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._read(self._reference(self.successor_card, version=2))

    def test_114_a3_c10_permission_revoked_reference_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._read(self._reference(self.revoked_card, version=1))

    def test_114_a3_c11_wrong_installation_reference_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._read(
                self._reference(
                    self.successor_card,
                    version=2,
                    installation_id=OTHER_INSTALLATION,
                )
            )

    def test_114_a3_c14_stale_object_version_reference_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._read(self._reference(self.old_card, version=1))

    def test_114_a3_c15_correction_chain_keeps_stable_logical_object_ref(self) -> None:
        projection = self._projection()
        chain_objects = tuple(
            item
            for item in projection.objects
            if self.old_card.evidence_id in {
                item.object_ref,
                *item.evidence_refs,
            }
            or self.successor_card.evidence_id in {
                item.object_ref,
                *item.evidence_refs,
            }
        )

        self.assertEqual(len(chain_objects), 1)
        self.assertEqual(
            (
                chain_objects[0].object_ref,
                chain_objects[0].version,
                chain_objects[0].current,
                chain_objects[0].source_refs,
                chain_objects[0].evidence_refs,
            ),
            (
                self.old_card.evidence_id,
                2,
                True,
                (self.successor_card.source_causal_id,),
                (self.successor_card.evidence_id,),
            ),
        )
        self.assertNotIn(
            self.successor_card.evidence_id,
            tuple(item.object_ref for item in projection.objects),
        )

    def test_114_a3_c16_read_missing_or_forged_permission_rejected(self) -> None:
        for label, permission in (
            ("missing", None),
            ("forged-subclass", _ForgedPermission("health_data.read")),
        ):
            with self.subTest(label=label), self.assertRaises(ValueError):
                self._read(self.other_current_ref, permission=permission)

    def test_114_a3_c17_correct_missing_or_forged_permission_rejected(self) -> None:
        for label, permission in (
            ("missing", None),
            ("forged-subclass", _ForgedPermission("health_data.correct")),
        ):
            with self.subTest(label=label), self.assertRaises(ValueError):
                self._correct(
                    permission=permission,
                    target_ref=self.other_current_ref,
                )

    def test_114_a3_c18_export_missing_or_forged_permission_rejected(self) -> None:
        for label, permission in (
            ("missing", None),
            ("forged-subclass", _ForgedPermission("health_data.export")),
        ):
            with self.subTest(label=label), self.assertRaises(ValueError):
                self._export(
                    permission=permission,
                    requested_refs=(self.other_current_ref,),
                )

    def test_114_a3_c19_draft_preserves_previous_value_and_logical_versions(self) -> None:
        projection = self._projection()
        current = self._read(self.successor_ref, projection=projection)[0]

        pending = self._correct(projection=projection)

        self.assertEqual(pending.previous_value, current.value)
        self.assertIsNot(pending.previous_value, current.value)
        self.assertEqual(
            (
                pending.target_ref.object_ref,
                pending.target_ref.version,
                pending.revision.object_ref,
                pending.revision.previous_version,
                pending.revision.revision_version,
                pending.revision.evidence_refs,
                pending.maintenance_request.target_evidence_ids,
            ),
            (
                self.old_card.evidence_id,
                2,
                self.old_card.evidence_id,
                2,
                3,
                (self.successor_card.evidence_id,),
                (self.successor_card.evidence_id,),
            ),
        )

    def test_114_a3_c22_final_authoritative_state_recovers_correction_metadata_for_export(
        self,
    ) -> None:
        revision = OwnerCorrectionRevision(
            correction_id="correction:committed-synthetic-1",
            object_ref=self.old_card.evidence_id,
            previous_version=1,
            revision_version=2,
            reason="owner corrected the prior sleep report",
            corrected_at_utc="2026-08-23T01:00:00+00:00",
            source_refs=("source:owner-correction:committed-synthetic-1",),
            evidence_refs=(self.old_card.evidence_id,),
            affected_object_refs=(
                "task:synthetic-1",
                f"portrait-topic:{TOPIC_REF}",
            ),
            disposition_requests=("withdraw_current", "rejudge"),
        )
        final_state = replace(
            self.daily_state,
            owner_correction_revisions=(revision,),
        )
        restored = DailyHealthState.from_storage(final_state.to_storage())
        projection = rights.ManagedRightsService._project_from_daily_state(
            restored,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            permitted_object_refs=self.permitted_object_refs,
            revoked_object_refs=self.revoked_object_refs,
        )
        exported = rights.ManagedRightsService.export(
            projection,
            requester_owner_id=OWNER,
            permission="health_data.export",
            requested_refs=(self.successor_ref,),
            snapshot_id="export-snapshot:committed-correction",
            created_at_utc=EXPORTED_AT,
        )

        self.assertEqual(restored.owner_correction_revisions, (revision,))
        self.assertEqual(
            exported.corrections,
            (
                rights.CorrectionRevision(
                    correction_id=revision.correction_id,
                    object_ref=revision.object_ref,
                    previous_version=revision.previous_version,
                    revision_version=revision.revision_version,
                    reason=revision.reason,
                    corrected_at_utc=revision.corrected_at_utc,
                    source_refs=revision.source_refs,
                    evidence_refs=revision.evidence_refs,
                    affected_object_refs=revision.affected_object_refs,
                    disposition_requests=revision.disposition_requests,
                ),
            ),
        )
        self.assertEqual(
            next(
                card
                for card in restored.evidence_cards
                if card.evidence_id == exported.corrections[0].evidence_refs[0]
            ),
            self.old_card,
        )
        self.assertNotIn(
            "previous_value",
            exported.corrections[0].to_wire(),
        )


if __name__ == "__main__":
    unittest.main()

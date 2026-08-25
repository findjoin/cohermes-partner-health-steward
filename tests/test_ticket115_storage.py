import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.current_head import InMemoryCurrentHead
from partner_health_steward.initialization import stable_digest
from partner_health_steward.delivery import (
    DeliveryOutboxState,
    OwnerDeliveryEngine,
)
from partner_health_steward.review import DailyReviewEngine, DailyReviewLedger
from partner_health_steward.storage import (
    EncryptedStateStore,
    KeyUnavailable,
    StaticKeyProvider,
)
from partner_health_steward.tasks import (
    TaskApprovalBinding,
    TaskCandidate,
    TaskEngine,
    TaskExternalBoundary,
    TaskRuntimeState,
)
from tests.ticket115_delivery_fixtures import (
    mark_attempted,
    record_observation,
    submit,
)


OWNER = "owner-A"
INSTALLATION = "ticket115-storage-installation"
SHA_ONE = "sha256:" + "1" * 64
SHA_TWO = "sha256:" + "2" * 64


def _task_state() -> TaskRuntimeState:
    transition = TaskEngine.admit_candidate(
        TaskRuntimeState.empty(OWNER, INSTALLATION),
        TaskCandidate(
            candidate_id="candidate:storage:1",
            source_kind="owner-goal",
            source_ref="owner-goal:storage",
            source_revision_digest=SHA_ONE,
            purpose="Confirm the storage recovery path.",
            expected_result="One typed task aggregate survives restart.",
            expected_result_kind="internal-result",
            assignee="health-steward",
            allowed_data_categories=("evidence",),
            allowed_data_refs=("evidence:storage",),
            external_boundary=TaskExternalBoundary.internal_only(),
            phase="planned",
            approval=TaskApprovalBinding.not_required(),
            acceptance_criteria=("typed aggregate reopens",),
        ),
        committed_at_utc="2026-08-24T00:00:00+00:00",
    )
    return transition.state


def _prepared_review_state() -> DailyReviewLedger:
    return DailyReviewEngine.prepare(
        DailyReviewLedger.empty(OWNER, INSTALLATION),
        owner_id=OWNER,
        installation_id=INSTALLATION,
        timezone_name="Asia/Shanghai",
        observed_at_utc="2026-08-24T00:01:00+00:00",
        current_state_digest=SHA_TWO,
        changed=True,
        action_refs=("task:storage",),
    ).ledger


def _review_state(
    prepared: DailyReviewLedger | None = None,
) -> DailyReviewLedger:
    prepared_state = prepared or _prepared_review_state()
    return DailyReviewEngine.commit(
        DailyReviewEngine.prepare(
            prepared_state,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T00:01:30+00:00",
            current_state_digest=SHA_TWO,
            changed=True,
            action_refs=("task:storage",),
        ),
        completed_at_utc="2026-08-24T00:02:00+00:00",
    ).ledger


def _delivery_state(
    review_state: DailyReviewLedger | None = None,
    *,
    business_fact_ref: str | None = None,
    business_revision_digest: str | None = None,
    source_ref: str | None = None,
) -> DeliveryOutboxState:
    review = (review_state or _review_state()).completed[-1]
    intent = OwnerDeliveryEngine.form_intent(
        effect_kind="owner-delivery",
        owner_id=OWNER,
        installation_id=INSTALLATION,
        effect_request_id="effect:storage-review",
        business_fact_ref=business_fact_ref or review.key.value,
        business_revision_digest=(
            business_revision_digest or review.result_digest
        ),
        source_ref=source_ref or review.action_refs[0],
        recipient_ref="owner-route:weixin-private",
        route_id="health_weixin",
        route_generation=1,
        payload_ref="owner-message:storage",
        payload_digest=SHA_TWO,
        formed_at_utc="2026-08-24T00:01:30+00:00",
    )
    return submit(
        DeliveryOutboxState.empty(OWNER, INSTALLATION),
        intent,
        submitted_at_utc="2026-08-24T00:02:00+00:00",
    ).state


class Ticket115StorageMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.key_provider = StaticKeyProvider(
            b"q" * 32,
            key_id="ticket115-storage-key",
        )
        self.authority = InMemoryCurrentHead(
            installation_id="ticket115-storage-installation",
            site="ticket115-storage-site",
            writer_capability="ticket115-storage-writer",
        ).read().head.as_authority()

    @staticmethod
    def _install_pre_ticket115_manifest(store: EncryptedStateStore) -> str:
        legacy_fingerprint = store._pre_ticket115_integrity_fingerprint()
        nonce, ciphertext = store._seal(
            "integrity-manifest",
            {"fingerprint": legacy_fingerprint},
        )
        store._execute(
            "UPDATE integrity_manifest_v1 SET nonce = ?, ciphertext = ? "
            "WHERE slot = 1",
            (nonce, ciphertext),
        )
        return legacy_fingerprint

    def test_pre_ticket115_manifest_migrates_only_with_empty_new_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "pre-ticket115-empty.sqlite")
            store = EncryptedStateStore(database, self.key_provider)
            store.seed_finalized_authority(self.authority)
            with store.transaction():
                self._install_pre_ticket115_manifest(store)
            store.close()

            migrated = EncryptedStateStore(database, self.key_provider)
            try:
                self.assertTrue(migrated.verify_integrity(self.authority))
                tables = {
                    row[0]
                    for row in migrated._execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                self.assertTrue(
                    {
                        "task_runtime_v1",
                        "ticket115_mutations_v1",
                        "daily_reviews_v1",
                        "owner_outbox_v1",
                        "owner_delivery_observations_v1",
                    }.issubset(tables)
                )
                manifest = migrated._execute(
                    "SELECT nonce, ciphertext FROM integrity_manifest_v1 "
                    "WHERE slot = 1"
                ).fetchone()
                self.assertIsNotNone(manifest)
                self.assertEqual(
                    migrated._open("integrity-manifest", *manifest)["fingerprint"],
                    migrated._integrity_fingerprint(),
                )
            finally:
                migrated.close()

    def test_pre_ticket115_manifest_with_outbox_data_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "pre-ticket115-outbox.sqlite")
            store = EncryptedStateStore(database, self.key_provider)
            store.seed_finalized_authority(self.authority)
            with store.transaction() as connection:
                nonce, ciphertext = store._seal(
                    "owner-outbox:intent:test:committed",
                    {
                        "intent_id": "intent:test",
                        "phase": "committed",
                        "formed_at_utc": "2026-08-24T00:00:00+00:00",
                    },
                )
                connection.execute(
                    "INSERT INTO owner_outbox_v1("
                    "intent_id, state_version, phase, nonce, ciphertext"
                    ") VALUES (?, 1, 'committed', ?, ?)",
                    ("intent:test", nonce, ciphertext),
                )
                legacy_fingerprint = self._install_pre_ticket115_manifest(store)
            store.close()

            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                with self.assertRaisesRegex(
                    KeyUnavailable,
                    "health state integrity manifest mismatch",
                ):
                    reopened.verify_integrity(self.authority)
                manifest = reopened._execute(
                    "SELECT nonce, ciphertext FROM integrity_manifest_v1 "
                    "WHERE slot = 1"
                ).fetchone()
                self.assertEqual(
                    reopened._open("integrity-manifest", *manifest)["fingerprint"],
                    legacy_fingerprint,
                )
            finally:
                reopened.close()

    def test_existing_delivery_schema_adds_actual_action_without_losing_facts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "pre-actual-action.sqlite")
            expected = _delivery_state()
            store = EncryptedStateStore(database, self.key_provider)
            store.commit_ticket115_facts(delivery_state=expected)
            store.close()

            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "ALTER TABLE owner_delivery_observations_v1 "
                    "RENAME TO owner_delivery_observations_legacy_v1"
                )
                connection.execute(
                    """
                    CREATE TABLE owner_delivery_observations_v1 (
                        observation_id TEXT PRIMARY KEY,
                        intent_id TEXT NOT NULL,
                        layer TEXT NOT NULL CHECK(
                            layer IN (
                                'formed', 'submitted', 'attempted', 'accepted',
                                'rejected', 'delivered', 'read', 'unknown'
                            )
                        ),
                        nonce BLOB NOT NULL,
                        ciphertext BLOB NOT NULL,
                        FOREIGN KEY(intent_id) REFERENCES owner_outbox_v1(intent_id)
                            ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO owner_delivery_observations_v1(
                        observation_id, intent_id, layer, nonce, ciphertext
                    )
                    SELECT observation_id, intent_id, layer, nonce, ciphertext
                    FROM owner_delivery_observations_legacy_v1
                    """
                )
                connection.execute(
                    "DROP TABLE owner_delivery_observations_legacy_v1"
                )
                connection.execute(
                    """
                    CREATE INDEX owner_delivery_observations_intent_v1
                    ON owner_delivery_observations_v1(intent_id, observation_id)
                    """
                )
                connection.commit()
            finally:
                connection.close()

            migrated = EncryptedStateStore(database, self.key_provider)
            try:
                schema = migrated._execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'table' "
                    "AND name = 'owner_delivery_observations_v1'"
                ).fetchone()[0]
                self.assertIn("'actual-action'", schema)
                self.assertEqual(
                    migrated.delivery_outbox_state(OWNER, INSTALLATION),
                    expected,
                )
            finally:
                migrated.close()


class Ticket115TypedStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = str(Path(self.directory.name) / "ticket115-typed.sqlite")
        self.key_provider = StaticKeyProvider(
            b"r" * 32,
            key_id="ticket115-typed-storage-key",
        )
        self.authority = InMemoryCurrentHead(
            installation_id=INSTALLATION,
            site="ticket115-typed-site",
            writer_capability="ticket115-typed-writer",
        ).read().head.as_authority()
        self.store = EncryptedStateStore(self.database, self.key_provider)
        self.store.seed_finalized_authority(self.authority)

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def test_complete_task_review_and_delivery_states_round_trip_after_restart(
        self,
    ) -> None:
        task_state = _task_state()
        prepared_review = _prepared_review_state()
        review_state = _review_state(prepared_review)
        delivery_state = _delivery_state(review_state)
        self.store.remember_daily_review(prepared_review)

        self.store.commit_ticket115_facts(
            task_state=task_state,
            review_state=review_state,
            delivery_state=delivery_state,
        )

        self.assertEqual(self.store.task_runtime(), task_state)
        self.assertEqual(self.store.daily_review_ledger(), review_state)
        self.assertEqual(
            self.store.delivery_outbox_state(OWNER, INSTALLATION),
            delivery_state,
        )
        self.assertTrue(self.store.verify_integrity(self.authority))
        self.store.close()

        self.store = EncryptedStateStore(self.database, self.key_provider)
        self.assertEqual(self.store.task_runtime(), task_state)
        self.assertEqual(self.store.daily_review_ledger(), review_state)
        self.assertEqual(
            self.store.delivery_outbox_state(OWNER, INSTALLATION),
            delivery_state,
        )
        self.assertTrue(self.store.verify_integrity(self.authority))

    def test_legacy_review_key_upgrades_on_restart_without_duplicate_day(self) -> None:
        prepared = DailyReviewEngine.prepare(
            DailyReviewLedger.empty(OWNER, INSTALLATION),
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            observed_at_utc="2026-08-24T00:01:00+00:00",
            current_state_digest=SHA_TWO,
            changed=False,
        )
        current = DailyReviewEngine.commit(
            prepared,
            completed_at_utc="2026-08-24T00:02:00+00:00",
        ).ledger
        wire = current.to_storage()
        record = wire["completed"][0]
        key = record["key"]
        del key["owner_generation"]
        record["prepare_digest"] = stable_digest(
            {
                "key": key,
                "state_digest": record["state_digest"],
                "changed": record["changed"],
                "action_refs": record["action_refs"],
                "prepared_at_utc": record["prepared_at_utc"],
            }
        )
        record["result_digest"] = stable_digest(
            {
                "prepare_digest": record["prepare_digest"],
                "completed_at_utc": record["completed_at_utc"],
            }
        )
        self.store.remember_daily_review(prepared.ledger)
        self.store.remember_daily_review(current)
        with self.store.transaction() as connection:
            self.store._assert_integrity_manifest_before_mutation()
            nonce, ciphertext = self.store._seal("daily-review-ledger:v1", wire)
            connection.execute(
                "UPDATE daily_reviews_v1 SET nonce = ?, ciphertext = ? WHERE slot = 1",
                (nonce, ciphertext),
            )
            self.store._refresh_integrity_manifest(connection)
        self.store.close()
        self.store = EncryptedStateStore(self.database, self.key_provider)

        restored = self.store.daily_review_ledger()
        self.assertEqual(restored.completed[0].key.owner_generation, 1)
        replay = DailyReviewEngine.prepare(
            restored,
            owner_id=OWNER,
            installation_id=INSTALLATION,
            timezone_name="Asia/Shanghai",
            owner_generation=1,
            observed_at_utc="2026-08-24T00:03:00+00:00",
            current_state_digest=SHA_ONE,
            changed=True,
            action_refs=("task:must-not-replay",),
        )
        self.assertEqual(replay.outcome, "already-completed")
        self.assertTrue(self.store.verify_integrity(self.authority))

    def test_outbox_failure_rolls_back_task_and_review_business_state(self) -> None:
        prepared_review = _prepared_review_state()
        self.store.remember_daily_review(prepared_review)
        review_state = _review_state(prepared_review)
        invalid_delivery = replace(_delivery_state(review_state), version=2)

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "stale delivery outbox version",
        ):
            self.store.commit_ticket115_facts(
                task_state=_task_state(),
                review_state=review_state,
                delivery_state=invalid_delivery,
            )

        self.assertIsNone(self.store.task_runtime())
        self.assertEqual(self.store.daily_review_ledger(), prepared_review)
        self.assertEqual(
            self.store.delivery_outbox_state(OWNER, INSTALLATION),
            DeliveryOutboxState.empty(OWNER, INSTALLATION),
        )
        self.assertTrue(self.store.verify_integrity(self.authority))

    def test_unrelated_new_intent_cannot_satisfy_notifying_review_commit(
        self,
    ) -> None:
        prepared_review = _prepared_review_state()
        review_state = _review_state(prepared_review)
        review = review_state.completed[-1]
        self.store.remember_daily_review(prepared_review)
        mismatches = {
            "business fact": {
                "business_fact_ref": "daily-review:unrelated",
            },
            "business revision": {
                "business_revision_digest": SHA_ONE,
            },
            "source action": {
                "source_ref": "task:unrelated",
            },
        }

        for mismatch, overrides in mismatches.items():
            with self.subTest(mismatch=mismatch):
                with self.assertRaisesRegex(
                    AuthorityValidationError,
                    "requires its exact new owner-delivery intent",
                ):
                    self.store.commit_ticket115_facts(
                        review_state=review_state,
                        delivery_state=_delivery_state(
                            review_state,
                            **overrides,
                        ),
                    )

                self.assertEqual(
                    self.store.daily_review_ledger(),
                    prepared_review,
                )
                self.assertEqual(
                    self.store.delivery_outbox_state(OWNER, INSTALLATION),
                    DeliveryOutboxState.empty(OWNER, INSTALLATION),
                )
                self.assertTrue(review.notification_required)

    def test_outbox_history_rejects_intent_deletion_and_same_id_mutation(
        self,
    ) -> None:
        initial = _delivery_state()
        self.store.remember_delivery_outbox(initial)
        record = initial.records[0]

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "cannot discard every intent",
        ):
            self.store.remember_delivery_outbox(
                replace(initial, version=initial.version + 1, records=())
            )

        mutated_intent = replace(
            record.intent,
            formed_at_utc="2026-08-24T00:01:31+00:00",
        )
        mutated_record = replace(
            record,
            intent=mutated_intent,
            facts=(
                replace(
                    record.fact("formed"),
                    occurred_at_utc=mutated_intent.formed_at_utc,
                ),
                record.fact("submitted"),
            ),
        )
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner outbox intent is immutable",
        ):
            self.store.remember_delivery_outbox(
                replace(
                    initial,
                    version=initial.version + 1,
                    records=(mutated_record,),
                )
            )

    def test_outbox_history_rejects_fact_deletion_and_modification(self) -> None:
        submitted = _delivery_state()
        intent_id = submitted.records[0].intent.intent_id
        self.store.remember_delivery_outbox(submitted)
        claimed = OwnerDeliveryEngine.claim(
            submitted,
            intent_id,
            holder_id="worker:A",
            lease_id="lease:storage:1",
            acquired_at_utc="2026-08-24T00:03:00+00:00",
            lease_seconds=30,
        )
        self.store.remember_delivery_outbox(claimed.state)
        attempted = mark_attempted(
            claimed.state,
            intent_id,
            lease_id="lease:storage:1",
            attempt_ref="attempt:storage:1",
            attempted_at_utc="2026-08-24T00:03:01+00:00",
        )
        self.store.remember_delivery_outbox(attempted.state)
        accepted = record_observation(
            attempted.state,
            intent_id,
            kind="accepted",
            attempt_ref="attempt:storage:1",
            result_ref="result:storage:accepted",
            evidence_ref="evidence:storage:accepted",
            observed_at_utc="2026-08-24T00:03:02+00:00",
        ).state
        self.store.remember_delivery_outbox(accepted)
        record = accepted.records[0]

        without_accepted = replace(
            record,
            facts=tuple(fact for fact in record.facts if fact.kind != "accepted"),
        )
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner delivery facts are append-only",
        ):
            self.store.remember_delivery_outbox(
                replace(
                    accepted,
                    version=accepted.version + 1,
                    records=(without_accepted,),
                )
            )

        changed_accepted = replace(
            record.fact("accepted"),
            occurred_at_utc="2026-08-24T00:03:03+00:00",
        )
        modified_record = replace(
            record,
            facts=tuple(
                changed_accepted if fact.kind == "accepted" else fact
                for fact in record.facts
            ),
        )
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner delivery facts are append-only",
        ):
            self.store.remember_delivery_outbox(
                replace(
                    accepted,
                    version=accepted.version + 1,
                    records=(modified_record,),
                )
            )

    def test_outbox_history_rejects_lease_deletion_and_modification(self) -> None:
        submitted = _delivery_state()
        intent_id = submitted.records[0].intent.intent_id
        claimed = OwnerDeliveryEngine.claim(
            submitted,
            intent_id,
            holder_id="worker:A",
            lease_id="lease:storage:2",
            acquired_at_utc="2026-08-24T00:03:00+00:00",
            lease_seconds=30,
        ).state
        self.store.remember_delivery_outbox(submitted)
        self.store.remember_delivery_outbox(claimed)
        record = claimed.records[0]

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner delivery leases are append-only",
        ):
            self.store.remember_delivery_outbox(
                replace(
                    claimed,
                    version=claimed.version + 1,
                    records=(replace(record, leases=()),),
                )
            )

        changed_lease = replace(record.leases[0], holder_id="worker:B")
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "owner delivery leases are append-only",
        ):
            self.store.remember_delivery_outbox(
                replace(
                    claimed,
                    version=claimed.version + 1,
                    records=(replace(record, leases=(changed_lease,)),),
                )
            )

    def test_outbox_fact_append_preserves_prior_observations(self) -> None:
        submitted = _delivery_state()
        intent_id = submitted.records[0].intent.intent_id
        claimed = OwnerDeliveryEngine.claim(
            submitted,
            intent_id,
            holder_id="worker:A",
            lease_id="lease:storage:3",
            acquired_at_utc="2026-08-24T00:03:00+00:00",
            lease_seconds=30,
        )
        attempted = mark_attempted(
            claimed.state,
            intent_id,
            lease_id="lease:storage:3",
            attempt_ref="attempt:storage:3",
            attempted_at_utc="2026-08-24T00:03:01+00:00",
        )
        accepted = record_observation(
            attempted.state,
            intent_id,
            kind="accepted",
            attempt_ref="attempt:storage:3",
            result_ref="result:storage:accepted:3",
            evidence_ref="evidence:storage:accepted:3",
            observed_at_utc="2026-08-24T00:03:02+00:00",
        ).state
        self.store.remember_delivery_outbox(submitted)
        self.store.remember_delivery_outbox(claimed.state)
        self.store.remember_delivery_outbox(attempted.state)
        self.store.remember_delivery_outbox(accepted)

        delivered = record_observation(
            accepted,
            intent_id,
            kind="delivered",
            attempt_ref="attempt:storage:3",
            result_ref="result:storage:delivered:3",
            evidence_ref="evidence:storage:delivered:3",
            observed_at_utc="2026-08-24T00:03:03+00:00",
        ).state
        self.store.remember_delivery_outbox(delivered)
        restored = self.store.delivery_outbox_state(OWNER, INSTALLATION)

        self.assertEqual(restored, delivered)
        self.assertEqual(
            restored.record(intent_id).fact_kinds,
            ("formed", "submitted", "attempted", "accepted", "delivered"),
        )
        self.assertEqual(
            restored.record(intent_id).fact("accepted").result_ref,
            "result:storage:accepted:3",
        )

    def test_integrity_scan_rejects_authenticated_but_invalid_task_wire(self) -> None:
        self.store.remember_task_runtime(_task_state())
        with self.store.transaction() as connection:
            self.store._assert_integrity_manifest_before_mutation()
            nonce, ciphertext = self.store._seal(
                "task-runtime:v1",
                {"owner_id": OWNER, "installation_id": INSTALLATION},
            )
            connection.execute(
                "UPDATE task_runtime_v1 SET nonce = ?, ciphertext = ? "
                "WHERE slot = 1",
                (nonce, ciphertext),
            )
            self.store._refresh_integrity_manifest(connection)

        with self.assertRaisesRegex(
            KeyUnavailable,
            "invalid task runtime aggregate",
        ):
            self.store.verify_integrity(self.authority)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from partner_health_steward.authority import (
    AuthorityValidationError,
    CommittedTransition,
)
from partner_health_steward.current_head import InMemoryCurrentHead
from partner_health_steward.delivery import DeliveryOutboxState
from partner_health_steward.health_commands import (
    HealthCommandContractViolation,
    HealthCommandReceipt,
    TrustedHealthCommand,
)
from partner_health_steward.review import DailyReviewLedger
from partner_health_steward.storage import (
    CausalIdConflict,
    EncryptedStateStore,
    KeyUnavailable,
    StaticKeyProvider,
    Ticket115PreparedMutation,
)
from partner_health_steward.tasks import (
    TaskApprovalBinding,
    TaskCandidate,
    TaskEngine,
    TaskExternalBoundary,
    TaskRuntimeState,
)


OWNER = "owner-A"
INSTALLATION = "ticket115-health-command-installation"
SHA_ONE = "sha256:" + "1" * 64


def _command(
    *,
    causal_id: str = "health-command:1",
    payload: dict[str, object] | None = None,
) -> TrustedHealthCommand:
    return TrustedHealthCommand(
        action="task.advance",
        source="health_tasks",
        causal_id=causal_id,
        generation=1,
        scope=("task:advance",),
        payload={"task_id": "task:1", "phase": "working"}
        if payload is None
        else payload,
    )


def _receipt(
    command: TrustedHealthCommand,
    result: object = "working",
) -> HealthCommandReceipt:
    return HealthCommandReceipt(
        causal_id=command.causal_id,
        command_digest=command.command_digest,
        result={"task_id": "task:1", "outcome": result, "replayed": False},
    )


def _next_task_state() -> TaskRuntimeState:
    return TaskEngine.admit_candidate(
        TaskRuntimeState.empty(OWNER, INSTALLATION),
        TaskCandidate(
            candidate_id="candidate:health-command:1",
            source_kind="owner-goal",
            source_ref="owner-goal:health-command",
            source_revision_digest=SHA_ONE,
            purpose="Prove an atomic health-command receipt.",
            expected_result="The task and receipt appear together.",
            expected_result_kind="internal-result",
            assignee="health-steward",
            allowed_data_categories=("evidence",),
            allowed_data_refs=("evidence:health-command",),
            external_boundary=TaskExternalBoundary.internal_only(),
            phase="planned",
            approval=TaskApprovalBinding.not_required(),
            acceptance_criteria=("receipt is durable",),
        ),
        committed_at_utc="2026-08-24T00:00:00+00:00",
    ).state


class TrustedHealthCommandContractTests(unittest.TestCase):
    def test_command_and_receipt_are_canonical_immutable_values(self) -> None:
        payload = {
            "z": [{"nested": "original"}],
            "a": {"flag": True, "count": 2},
        }
        command = _command(payload=payload)
        digest = command.command_digest

        payload["z"][0]["nested"] = "changed"
        exposed = command.payload
        exposed["z"][0]["nested"] = "also-changed"

        self.assertEqual(command.payload["z"], [{"nested": "original"}])
        self.assertEqual(command.command_digest, digest)
        self.assertEqual(
            command.command_digest,
            _command(
                payload={
                    "a": {"count": 2, "flag": True},
                    "z": [{"nested": "original"}],
                }
            ).command_digest,
        )

        receipt_result = {"outcome": {"items": ["original"]}}
        receipt = HealthCommandReceipt(
            causal_id=command.causal_id,
            command_digest=command.command_digest,
            result=receipt_result,
        )
        receipt_result["outcome"]["items"].append("changed")
        returned = receipt.result
        returned["outcome"]["items"].append("also-changed")
        self.assertEqual(receipt.result, {"outcome": {"items": ["original"]}})

    def test_strict_wire_and_storage_round_trips_reject_shape_drift(self) -> None:
        command = _command()
        self.assertEqual(
            TrustedHealthCommand.from_wire(command.to_wire()),
            command,
        )
        receipt = _receipt(command)
        self.assertEqual(
            HealthCommandReceipt.from_storage(receipt.to_storage()),
            receipt,
        )

        command_wire = command.to_wire()
        command_wire["extra"] = True
        with self.assertRaises(HealthCommandContractViolation):
            TrustedHealthCommand.from_wire(command_wire)

        command_wire = command.to_wire()
        command_wire["scope"] = ("task:advance",)
        with self.assertRaises(HealthCommandContractViolation):
            TrustedHealthCommand.from_wire(command_wire)

        receipt_wire = receipt.to_storage()
        receipt_wire.pop("result")
        with self.assertRaises(HealthCommandContractViolation):
            HealthCommandReceipt.from_storage(receipt_wire)

    def test_command_rejects_non_json_or_non_exact_authority_values(self) -> None:
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        invalid_changes = (
            {"generation": True},
            {"generation": 0},
            {"scope": ["task:advance"]},
            {"scope": ()},
            {"payload": {"unsupported": object()}},
            {"payload": {"non_finite": float("nan")}},
            {"payload": cyclic},
        )
        base = {
            "action": "task.advance",
            "source": "health_tasks",
            "causal_id": "health-command:strict",
            "generation": 1,
            "scope": ("task:advance",),
            "payload": {},
        }
        for changes in invalid_changes:
            with self.subTest(changes=changes):
                with self.assertRaises(HealthCommandContractViolation):
                    TrustedHealthCommand(**(base | changes))


class Ticket115HealthCommandStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = str(Path(self.directory.name) / "health-commands.sqlite")
        self.key_provider = StaticKeyProvider(
            b"h" * 32,
            key_id="ticket115-health-command-key",
        )
        self.authority = InMemoryCurrentHead(
            installation_id=INSTALLATION,
            site="ticket115-health-command-site",
            writer_capability="ticket115-health-command-writer",
        ).read().head.as_authority()
        self.store = EncryptedStateStore(self.database, self.key_provider)
        self.store.seed_finalized_authority(self.authority)

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def _mutation(
        self,
        receipt: HealthCommandReceipt | None,
    ) -> Ticket115PreparedMutation:
        current_task = TaskRuntimeState.empty(OWNER, INSTALLATION)
        current_review = DailyReviewLedger.empty(OWNER, INSTALLATION)
        current_delivery = DeliveryOutboxState.empty(OWNER, INSTALLATION)
        return Ticket115PreparedMutation.prepare(
            base=self.authority,
            current_task_state=current_task,
            current_review_state=current_review,
            current_delivery_state=current_delivery,
            task_state=_next_task_state(),
            review_state=current_review,
            delivery_state=current_delivery,
            health_command_receipt=receipt,
        )

    def _mark_committed(
        self,
        mutation: Ticket115PreparedMutation,
    ) -> CommittedTransition:
        target = mutation.prepared.target
        committed = CommittedTransition(
            prepared=mutation.prepared,
            committed=replace(
                self.authority,
                generation=self.authority.generation + 1,
                revision_digest=target.revision_digest,
                transition_id=target.transition_id,
            ),
        )
        self.store.write_record(
            target.record_id,
            "committed",
            target.revision_digest,
            target.transition_id,
            committed,
        )
        return committed

    def test_encrypted_receipt_round_trip_replay_and_conflict(self) -> None:
        command = _command()
        receipt = _receipt(command, result="sensitive-result")
        self.store.save_health_command_receipt(receipt)
        self.store.save_health_command_receipt(receipt)

        self.store.close()
        self.store = EncryptedStateStore(self.database, self.key_provider)

        self.assertEqual(
            self.store.lookup_health_command_receipt(command),
            receipt,
        )
        self.assertNotIn(b"sensitive-result", self.store.raw_storage_bytes())
        self.assertTrue(self.store.verify_integrity(self.authority))

        conflicting = _command(payload={"task_id": "task:1", "phase": "solved"})
        with self.assertRaisesRegex(CausalIdConflict, "causal-id-conflict"):
            self.store.lookup_health_command_receipt(conflicting)

    def test_existing_ticket115_manifest_migrates_only_with_empty_receipt_table(
        self,
    ) -> None:
        self.store.remember_task_runtime(_next_task_state())
        legacy_fingerprint = (
            self.store._pre_ticket115_health_command_integrity_fingerprint()
        )
        with self.store.transaction() as connection:
            self.store._assert_integrity_manifest_before_mutation()
            nonce, ciphertext = self.store._seal(
                "integrity-manifest",
                {"fingerprint": legacy_fingerprint},
            )
            connection.execute(
                "UPDATE integrity_manifest_v1 SET nonce = ?, ciphertext = ? "
                "WHERE slot = 1",
                (nonce, ciphertext),
            )
        self.store.close()

        self.store = EncryptedStateStore(self.database, self.key_provider)
        self.assertEqual(self.store.task_runtime(), _next_task_state())
        self.assertTrue(self.store.verify_integrity(self.authority))
        manifest = self.store._execute(
            "SELECT nonce, ciphertext FROM integrity_manifest_v1 WHERE slot = 1"
        ).fetchone()
        self.assertEqual(
            self.store._open("integrity-manifest", *manifest)["fingerprint"],
            self.store._integrity_fingerprint(),
        )

    def test_legacy_manifest_cannot_adopt_existing_health_command_receipt(
        self,
    ) -> None:
        command = _command()
        self.store.save_health_command_receipt(_receipt(command))
        legacy_fingerprint = (
            self.store._pre_ticket115_health_command_integrity_fingerprint()
        )
        with self.store.transaction() as connection:
            self.store._assert_integrity_manifest_before_mutation()
            nonce, ciphertext = self.store._seal(
                "integrity-manifest",
                {"fingerprint": legacy_fingerprint},
            )
            connection.execute(
                "UPDATE integrity_manifest_v1 SET nonce = ?, ciphertext = ? "
                "WHERE slot = 1",
                (nonce, ciphertext),
            )
        self.store.close()

        self.store = EncryptedStateStore(self.database, self.key_provider)
        with self.assertRaisesRegex(
            KeyUnavailable,
            "health state integrity manifest mismatch",
        ):
            self.store.verify_integrity(self.authority)

    def test_prepared_mutation_round_trip_supports_receipt_and_legacy_shape(self) -> None:
        receipt = _receipt(_command())
        mutation = self._mutation(receipt)
        self.assertEqual(
            Ticket115PreparedMutation.from_storage(mutation.to_storage()),
            mutation,
        )
        self.assertEqual(mutation.health_command_receipt, receipt)

        legacy = self._mutation(None)
        legacy_storage = legacy.to_storage()
        legacy_storage.pop("health_command_receipt")
        self.assertEqual(
            Ticket115PreparedMutation.from_storage(legacy_storage),
            legacy,
        )

    def test_finalize_atomically_publishes_task_and_health_command_receipt(self) -> None:
        command = _command()
        receipt = _receipt(command)
        mutation = self._mutation(receipt)
        self.store.prepare_ticket115_mutation(mutation)
        committed = self._mark_committed(mutation)

        self.assertIsNone(self.store.task_runtime())
        self.assertIsNone(self.store.lookup_health_command_receipt(command))
        self.store.finalize_ticket115_mutation(
            mutation.prepared.target.record_id,
            committed,
        )

        self.assertEqual(self.store.task_runtime(), mutation.task_state)
        self.assertEqual(
            self.store.lookup_health_command_receipt(command),
            receipt,
        )
        self.assertTrue(self.store.verify_integrity(committed.committed))

    def test_finalize_receipt_conflict_rolls_back_every_aggregate(self) -> None:
        command = _command()
        mutation = self._mutation(_receipt(command))
        self.store.prepare_ticket115_mutation(mutation)
        committed = self._mark_committed(mutation)

        conflicting_command = _command(
            payload={"task_id": "task:1", "phase": "solved"}
        )
        conflicting_receipt = _receipt(conflicting_command, result="conflict")
        self.store.save_health_command_receipt(conflicting_receipt)

        with self.assertRaisesRegex(CausalIdConflict, "causal-id-conflict"):
            self.store.finalize_ticket115_mutation(
                mutation.prepared.target.record_id,
                committed,
            )

        self.assertIsNone(self.store.task_runtime())
        self.assertEqual(
            self.store.lookup_health_command_receipt(conflicting_command),
            conflicting_receipt,
        )
        self.assertEqual(self.store.pending_ticket115_mutation(), mutation)

    def test_integrity_scan_rejects_authenticated_receipt_index_mismatch(self) -> None:
        command = _command()
        receipt = _receipt(command)
        self.store.save_health_command_receipt(receipt)
        with self.store.transaction() as connection:
            self.store._assert_integrity_manifest_before_mutation()
            nonce, ciphertext = self.store._seal(
                "ticket115-health-command-receipt:" + command.causal_id,
                HealthCommandReceipt(
                    causal_id="health-command:other",
                    command_digest=receipt.command_digest,
                    result=receipt.result,
                ).to_storage(),
            )
            connection.execute(
                "UPDATE ticket115_health_command_receipts_v1 "
                "SET nonce = ?, ciphertext = ? WHERE causal_id = ?",
                (nonce, ciphertext, command.causal_id),
            )
            self.store._refresh_integrity_manifest(connection)

        with self.assertRaisesRegex(
            KeyUnavailable,
            "health command receipt causal identifier mismatch",
        ):
            self.store.verify_integrity(self.authority)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from partner_health_steward.coordination import DailyHealthState
from partner_health_steward.current_head import InMemoryCurrentHead
from partner_health_steward.storage import (
    EncryptedStateStore,
    KeyUnavailable,
    StaticKeyProvider,
)


class Ticket112StorageMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.key_provider = StaticKeyProvider(
            b"m" * 32,
            key_id="ticket112-migration-key",
        )
        self.authority = InMemoryCurrentHead(
            installation_id="ticket112-migration-installation",
            site="ticket112-migration-site",
            writer_capability="ticket112-migration-writer",
        ).read().head.as_authority()

    @staticmethod
    def _install_pre_ticket112_manifest(store: EncryptedStateStore) -> None:
        with store.transaction() as connection:
            legacy_fingerprint = store._integrity_fingerprint(
                include_ticket112=False,
            )
            nonce, ciphertext = store._seal(
                "integrity-manifest",
                {"fingerprint": legacy_fingerprint},
            )
            connection.execute(
                "UPDATE integrity_manifest_v1 SET nonce = ?, ciphertext = ? "
                "WHERE slot = 1",
                (nonce, ciphertext),
            )

    def test_pre_ticket112_manifest_migrates_only_when_ticket112_tables_are_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "pre-ticket112-empty.sqlite")
            store = EncryptedStateStore(database, self.key_provider)
            store.seed_finalized_authority(self.authority)
            self.assertEqual(store.daily_state(), DailyHealthState.empty())
            self.assertIsNone(store.unresolved_daily_turn())
            self._install_pre_ticket112_manifest(store)
            store.close()

            migrated = EncryptedStateStore(database, self.key_provider)
            try:
                self.assertTrue(migrated.verify_integrity(self.authority))
                self.assertEqual(
                    migrated._integrity_fingerprint(),
                    migrated._open(
                        "integrity-manifest",
                        *migrated._execute(
                            "SELECT nonce, ciphertext FROM integrity_manifest_v1 "
                            "WHERE slot = 1"
                        ).fetchone(),
                    )["fingerprint"],
                )
            finally:
                migrated.close()

            restarted = EncryptedStateStore(database, self.key_provider)
            try:
                self.assertTrue(restarted.verify_integrity(self.authority))
                self.assertEqual(restarted.daily_state(), DailyHealthState.empty())
                self.assertIsNone(restarted.unresolved_daily_turn())
            finally:
                restarted.close()

    def test_pre_ticket112_manifest_with_ticket112_data_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "pre-ticket112-nonempty.sqlite")
            store = EncryptedStateStore(database, self.key_provider)
            store.seed_finalized_authority(self.authority)
            with store.transaction() as connection:
                nonce, ciphertext = store._seal(
                    "daily-health-state",
                    DailyHealthState.empty().to_storage(),
                )
                connection.execute(
                    "INSERT INTO daily_health_state_v1(slot, nonce, ciphertext) "
                    "VALUES (1, ?, ?)",
                    (nonce, ciphertext),
                )
            self._install_pre_ticket112_manifest(store)
            store.close()

            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                with self.assertRaisesRegex(
                    KeyUnavailable,
                    "health state integrity manifest mismatch",
                ):
                    reopened.verify_integrity(self.authority)
                with self.assertRaisesRegex(
                    KeyUnavailable,
                    "health state integrity manifest mismatch",
                ):
                    reopened.seed_finalized_authority(self.authority)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()

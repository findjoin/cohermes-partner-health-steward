from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import export_attachments
from export_attachments import ExportAttachmentError, PrivateJsonExportStore


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now


class PrivateJsonExportStoreTests(unittest.TestCase):
    def _store(
        self,
        root: Path,
        *,
        now: dt.datetime | None = None,
    ) -> tuple[PrivateJsonExportStore, list[Path]]:
        verified: list[Path] = []

        def verify(path: Path) -> None:
            verified.append(path)

        return (
            PrivateJsonExportStore(
                root,
                tmpfs_verifier=verify,
                clock=FixedClock(
                    now
                    or dt.datetime(2026, 8, 11, 8, 0, tzinfo=dt.timezone.utc)
                ),
            ),
            verified,
        )

    def test_write_json_uses_a_private_file_and_remove_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private-exports"
            root.mkdir()
            store, verified = self._store(root)

            attachment = store.write_json(
                {
                    "export_schema_version": 1,
                    "profile": {"note": "私密健康内容"},
                }
            )

            self.assertEqual(attachment.path.parent, root)
            self.assertTrue(attachment.path.name.startswith("health-export-"))
            self.assertEqual(attachment.path.suffix, ".json")
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(attachment.path.stat().st_mode), 0o600)
            self.assertEqual(
                json.loads(attachment.path.read_text(encoding="utf-8")),
                {
                    "export_schema_version": 1,
                    "profile": {"note": "私密健康内容"},
                },
            )
            self.assertGreaterEqual(len(verified), 2)
            self.assertTrue(all(path == root for path in verified))

            self.assertTrue(attachment.remove())
            self.assertFalse(attachment.path.exists())
            self.assertFalse(attachment.remove())

    def test_cleanup_removes_only_expired_component_orphans(self) -> None:
        now = dt.datetime(2026, 8, 11, 8, 0, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private-exports"
            root.mkdir()
            store, _verified = self._store(root, now=now)
            expired = store.write_json({"profile": {"note": "expired"}})
            retained = store.write_json({"profile": {"note": "retained"}})
            unrelated = root / "unrelated.json"
            unrelated.write_text('{"note":"must-not-be-deleted"}', encoding="utf-8")
            stale_epoch = (now - dt.timedelta(hours=24, seconds=1)).timestamp()
            os.utime(expired.path, (stale_epoch, stale_epoch))

            self.assertEqual(store.cleanup_orphans(), 1)
            self.assertFalse(expired.path.exists())
            self.assertTrue(retained.path.exists())
            self.assertTrue(unrelated.exists())

    def test_cleanup_removes_an_orphan_at_the_twenty_four_hour_boundary(self) -> None:
        now = dt.datetime(2026, 8, 11, 8, 0, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private-exports"
            root.mkdir()
            store, _verified = self._store(root, now=now)
            attachment = store.write_json({"profile": {"note": "boundary"}})
            boundary_epoch = (now - dt.timedelta(hours=24)).timestamp()
            os.utime(attachment.path, (boundary_epoch, boundary_epoch))

            self.assertEqual(store.cleanup_orphans(), 1)
            self.assertFalse(attachment.path.exists())

    def test_cleanup_reserves_timer_margin_before_the_twenty_four_hour_limit(self) -> None:
        now = dt.datetime(2026, 8, 11, 8, 0, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private-exports"
            root.mkdir()
            store, _verified = self._store(root, now=now)
            attachment = store.write_json({"profile": {"note": "timer-margin"}})
            margin_epoch = (now - dt.timedelta(hours=22)).timestamp()
            os.utime(attachment.path, (margin_epoch, margin_epoch))

            self.assertEqual(store.cleanup_orphans(), 1)
            self.assertFalse(attachment.path.exists())

    def test_cleanup_cli_is_silent_and_removes_only_expired_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private-exports"
            root.mkdir()
            expired = root / "health-export-cli-expired.json"
            expired.write_text('{"private_health_text":"过期正文"}', encoding="utf-8")
            retained = root / "health-export-cli-retained.json"
            retained.write_text('{"private_health_text":"当前正文"}', encoding="utf-8")
            unrelated = root / "unrelated.json"
            unrelated.write_text('{"private_health_text":"不得清理"}', encoding="utf-8")
            stale_epoch = (
                dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=25)
            ).timestamp()
            os.utime(expired, (stale_epoch, stale_epoch))
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch.object(export_attachments, "verify_private_linux_tmpfs"),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                result = export_attachments.main(
                    ["--cleanup", "--directory", str(root)]
                )

            self.assertEqual(result, 0)
            self.assertFalse(expired.exists())
            self.assertTrue(retained.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")

    def test_default_verifier_fails_closed_for_a_non_private_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "not-private"
            root.mkdir()
            os.chmod(root, 0o755)

            with self.assertRaisesRegex(
                ExportAttachmentError,
                "export-(private-directory-required|tmpfs-linux-required)",
            ):
                PrivateJsonExportStore(root)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux tmpfs only")
    def test_default_verifier_accepts_a_private_linux_tmpfs_directory(self) -> None:
        shm = Path("/dev/shm")
        if not shm.is_dir():
            self.skipTest("/dev/shm is unavailable")
        with tempfile.TemporaryDirectory(dir=shm) as temp:
            root = Path(temp)
            os.chmod(root, 0o700)
            store = PrivateJsonExportStore(root)

            attachment = store.write_json({"export_schema_version": 1})
            self.assertTrue(attachment.path.exists())
            attachment.remove()

    def test_invalid_export_value_is_rejected_without_creating_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private-exports"
            root.mkdir()
            store, _verified = self._store(root)

            with self.assertRaisesRegex(ExportAttachmentError, "export-json-invalid"):
                store.write_json({"not_json": object()})

            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

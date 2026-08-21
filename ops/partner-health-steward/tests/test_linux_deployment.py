from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deployment import (  # noqa: E402
    DeploymentConfig,
    DeploymentError,
    DeploymentManager,
    EXPORT_CLEANUP_TIMER,
)
from health_model import HealthModelConfig  # noqa: E402
from hermes_jobs import fixed_job_specs  # noqa: E402
from sidecar.store import HealthSidecarStore  # noqa: E402


class FakeLinuxHost:
    def __init__(self) -> None:
        self.groups: dict[str, int] = {}
        self.users: dict[str, tuple[int, int, set[str]]] = {}
        self.ownership: list[tuple[str, str, str, bool]] = []
        self.commands: list[tuple[str, tuple[str, ...], dict[str, str]]] = []
        self.services: list[tuple[str, str]] = []
        self.active_services: set[str] = set()
        self.fail_once_start: str | None = None
        self.ready = True
        self.ready_sequence: list[bool] = []
        self.run_as_partner_active: list[bool] = []
        self._next_id = 2100

    def ensure_group(self, name: str) -> int:
        if name not in self.groups:
            self.groups[name] = self._next_id
            self._next_id += 1
        return self.groups[name]

    def ensure_user(
        self,
        name: str,
        *,
        home: str,
        primary_group: str,
        supplementary_groups: tuple[str, ...] = (),
    ) -> tuple[int, int]:
        del home
        primary_gid = self.ensure_group(primary_group)
        self.users[name] = (
            self.users.get(name, (self._next_id, primary_gid, set()))[0],
            primary_gid,
            set(supplementary_groups),
        )
        if self.users[name][0] == self._next_id:
            self._next_id += 1
        return self.users[name][0], primary_gid

    def user_ids(self, name: str) -> tuple[int, int] | None:
        record = self.users.get(name)
        return None if record is None else (record[0], record[1])

    def group_id(self, name: str) -> int | None:
        return self.groups.get(name)

    def group_members(self, name: str) -> set[str]:
        return {
            user
            for user, (_uid, _gid, supplementary) in self.users.items()
            if name in supplementary or self.groups.get(name) == _gid
        }

    def set_owner(self, path: Path, user: str, group: str, *, recursive: bool = False) -> None:
        self.ownership.append((str(path), user, group, recursive))

    def run_as(self, user: str, argv: list[str], env: dict[str, str]) -> None:
        self.run_as_partner_active.append(
            "hermes-gateway-partner-health-steward.service" in self.active_services
        )
        self.commands.append((user, tuple(argv), dict(env)))

    def service(self, action: str, unit: str) -> None:
        self.services.append((action, unit))
        if action == "start" and self.fail_once_start == unit:
            self.fail_once_start = None
            raise RuntimeError("simulated-service-start-failure")
        if action in {"start", "restart"}:
            self.active_services.add(unit)
        elif action == "stop":
            self.active_services.discard(unit)

    def daemon_reload(self) -> None:
        self.services.append(("daemon-reload", "systemd"))

    def service_active(self, unit: str) -> bool:
        return unit in self.active_services

    def legacy_partner_active(self) -> bool:
        return "hermes-gateway-partner.service" in self.active_services

    def process_ids(self, pid: int) -> tuple[int, int] | None:
        del pid
        return None

    def sidecar_ready(
        self, user: str, socket_path: str, python: str, *, timeout_seconds: float
    ) -> bool:
        del user, socket_path, python, timeout_seconds
        ready = self.ready_sequence.pop(0) if self.ready_sequence else self.ready
        if not ready:
            self.active_services.discard("health-sidecar.service")
        return ready and "health-sidecar.service" in self.active_services


class LinuxDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host_root = Path(self.temp.name) / "host"
        self.host_root.mkdir()
        self.legacy_home = self.host_root / "root/.hermes/profiles/partner"
        self.legacy_home.mkdir(parents=True)
        (self.legacy_home / "config.yaml").write_text(
            "plugins:\n  enabled:\n    - existing-plugin\n",
            encoding="utf-8",
        )
        (self.legacy_home / ".env").write_text("EXISTING_SECRET=preserve\n", encoding="utf-8")
        self.default_marker = self.host_root / "root/.hermes/config.yaml"
        self.default_marker.parent.mkdir(parents=True, exist_ok=True)
        self.default_marker.write_text("default-profile-marker\n", encoding="utf-8")
        self.public_key = Path(self.temp.name) / "receipt-public.key"
        self.public_key.write_bytes(bytes(range(32)))
        self.health_model_config = Path(self.temp.name) / "health-model.json"
        self.health_model_config.write_text(
            json.dumps(
                {
                    "provider": "custom",
                    "endpoint": "https://health-model.example/v1",
                    "model_id": "health-model-v1",
                    "privacy_mode": "isolated-health",
                    "auth_profile": "partner",
                }
            ),
            encoding="utf-8",
        )
        self.health_source_catalog = Path(self.temp.name) / "health-source-catalog.json"
        self.health_source_catalog.write_text(
            json.dumps(
                {
                    "catalog_schema_version": 1,
                    "keyword_urls": {"sleep": "https://www.who.int/health/sleep"},
                }
            ),
            encoding="utf-8",
        )
        self.sidecar_source_metadata = Path(self.temp.name) / "sidecar-source-metadata.json"
        self.sidecar_source_metadata.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "documents": {
                        "https://www.who.int/health/sleep": {
                            "source_type": "clinical_guideline",
                            "title": "Controlled sleep guidance",
                            "key_excerpt": "Controlled public health source.",
                            "tags": {
                                "topic": ["sleep"],
                                "symptom_behavior": ["insomnia"],
                                "target_population": ["adult"],
                                "evidence_type": ["clinical_guideline"],
                                "region_language": ["en-US"],
                                "freshness": ["current"],
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.sidecar_model_api_key = Path(self.temp.name) / "sidecar-health-model.key"
        self.sidecar_model_api_key.write_text("dedicated-model-key\n", encoding="utf-8")
        self.sidecar_model_api_key.chmod(0o600)
        self.sidecar_weixin_token = Path(self.temp.name) / "sidecar-weixin.token"
        self.sidecar_weixin_token.write_text("dedicated-weixin-token\n", encoding="utf-8")
        self.sidecar_weixin_token.chmod(0o600)
        self.host = FakeLinuxHost()

    def config(self, release_id: str = "2026.08.09.1") -> DeploymentConfig:
        return DeploymentConfig(
            root=self.host_root,
            source_root=ROOT,
            release_id=release_id,
            receipt_public_key_source=self.public_key,
            sidecar_python="/opt/hermes-venv/bin/python",
            hermes_python="/opt/hermes-venv/bin/python",
            partner_exec_start="/opt/hermes-venv/bin/python -m hermes_cli gateway",
            expected_owner_sender_id="wx-owner",
            expected_viewer_sender_id="wx-viewer",
            health_model_config_source=self.health_model_config,
            health_source_catalog_source=self.health_source_catalog,
            sidecar_source_metadata_source=self.sidecar_source_metadata,
            sidecar_health_model_api_key_source=self.sidecar_model_api_key,
            sidecar_weixin_token_source=self.sidecar_weixin_token,
            receipt_signer_socket="/run/partner-health-steward/receipt-signer.sock",
            hermes_source_root="/opt/hermes-agent",
            accepted_hermes_version="0.20.0",
            weixin_base_url="https://weixin.example/api",
            weixin_cdn_base_url="https://weixin.example/cdn",
        )

    @staticmethod
    def create_encrypted_backup(state_dir: Path, name: str) -> tuple[bytes, bytes]:
        store = HealthSidecarStore(
            state_dir / "state.sqlite.enc", state_dir / "sidecar.key"
        )
        store.write_subject_status("deployment-verification", {"sequence": 1})
        store.write_subject_status("deployment-verification", {"sequence": 2})
        backup = sorted(store.backup_dir.glob("*.bak"))[-1]
        named = store.backup_dir / name
        shutil.copy2(backup, named)
        return store.store_path.read_bytes(), named.read_bytes()

    def test_install_stages_only_allowlisted_assets_and_isolated_units(self) -> None:
        manager = DeploymentManager(self.config(), host=self.host)
        result = manager.install()

        release = self.host_root / "opt/partner-health-steward/releases/2026.08.09.1"
        self.assertEqual(result["result"], "installed")
        self.assertTrue((release / "sidecar/server.py").is_file())
        self.assertTrue((release / "hermes_jobs.py").is_file())
        self.assertTrue((release / "job_authorization.py").is_file())
        self.assertTrue((release / "health_model.py").is_file())
        self.assertTrue((release / "health_turn.py").is_file())
        self.assertTrue((release / "health_turn_answer.py").is_file())
        self.assertTrue((release / "owner_controls.py").is_file())
        self.assertTrue((release / "export_attachments.py").is_file())
        self.assertTrue((release / "weixin_ingress.py").is_file())
        self.assertTrue((release / "plugin/health-steward/plugin.yaml").is_file())
        self.assertTrue((release / "scripts/health_steward_daily_snapshot.py").is_file())
        self.assertTrue((release / "scripts/linux_health_smoke_wizard.sh").is_file())
        self.assertFalse((release / "plugin/health-guard").exists())
        self.assertFalse((release / "plugin/health-autonomy").exists())
        self.assertFalse((release / ".research").exists())

        sidecar_unit = (self.host_root / "etc/systemd/system/health-sidecar.service").read_text(
            encoding="utf-8"
        )
        partner_unit = (
            self.host_root
            / "etc/systemd/system/hermes-gateway-partner-health-steward.service"
        ).read_text(encoding="utf-8")
        self.assertIn("User=health-sidecar", sidecar_unit)
        self.assertIn("NoNewPrivileges=true", sidecar_unit)
        self.assertIn("RuntimeDirectory=health-sidecar", sidecar_unit)
        self.assertIn(
            "ExecStartPre=/bin/chgrp health-sidecar-client /run/health-sidecar",
            sidecar_unit,
        )
        self.assertIn("RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6", sidecar_unit)
        self.assertNotIn("ListenStream", sidecar_unit)
        self.assertIn("User=hermes-partner", partner_unit)
        self.assertIn("SupplementaryGroups=health-sidecar-client", partner_unit)
        self.assertIn("RuntimeDirectory=partner-health-steward-export", partner_unit)
        self.assertIn("RuntimeDirectoryMode=0700", partner_unit)
        self.assertIn(
            "InaccessiblePaths=/var/lib/health-sidecar/state /etc/health-sidecar",
            partner_unit,
        )
        self.assertIn(
            "ReadOnlyPaths=/opt/partner-health-steward /var/lib/health-sidecar/projection",
            partner_unit,
        )
        self.assertNotIn("/root/.hermes", partner_unit)
        self.assertIn(
            "ReadWritePaths=/var/lib/hermes-partner /run/partner-health-steward-export",
            partner_unit,
        )

        sidecar_env = (self.host_root / "etc/health-sidecar/health-sidecar.env").read_text(
            encoding="utf-8"
        )
        partner_env = (
            self.host_root / "etc/partner-health-steward/partner.env"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "HEALTH_STEWARD_MEMORY_PROJECTION_PATH=/var/lib/health-sidecar/projection/memory.json",
            partner_env,
        )
        self.assertIn("HEALTH_STEWARD_EXPECTED_OWNER_SENDER_ID=wx-owner", partner_env)
        self.assertIn("HEALTH_STEWARD_EXPECTED_VIEWER_SENDER_ID=wx-viewer", partner_env)
        self.assertIn(
            "HEALTH_STEWARD_DELIVERY_LEDGER_PATH=/var/lib/hermes-partner/health-delivery.sqlite3",
            partner_env,
        )
        self.assertIn(
            "HEALTH_STEWARD_HEALTH_MODEL_ATTESTATION_PATH=/var/lib/hermes-partner/health-model-attestation.json",
            partner_env,
        )
        self.assertIn(
            "HEALTH_STEWARD_HEALTH_MODEL_CONFIG=/etc/partner-health-steward/health-model.json",
            partner_env,
        )
        self.assertIn(
            "HEALTH_STEWARD_JOB_AUTHORIZATION_SECRET=/var/lib/hermes-partner/.hermes/profiles/partner/private/health-steward-job-authorization.key",
            partner_env,
        )
        self.assertIn(
            "HEALTH_STEWARD_HEALTH_SOURCE_CATALOG=/etc/partner-health-steward/health-source-catalog.json",
            partner_env,
        )
        self.assertIn(
            "HEALTH_STEWARD_HERMES_SOURCE_ROOT=/opt/hermes-agent", partner_env
        )
        self.assertIn("HEALTH_STEWARD_ACCEPTED_HERMES_VERSION=0.20.0", partner_env)
        self.assertIn("HERMES_TIMEZONE=Asia/Shanghai", partner_env)
        self.assertIn(
            "HEALTH_STEWARD_RECEIPT_SIGNER_SOCKET=/run/partner-health-steward/receipt-signer.sock",
            partner_env,
        )
        self.assertIn(
            "HEALTH_STEWARD_EXPORT_TMPDIR=/run/partner-health-steward-export",
            partner_env,
        )
        self.assertIn("WEIXIN_DM_POLICY=allowlist", partner_env)
        self.assertIn("WEIXIN_ALLOWED_USERS=wx-owner,wx-viewer", partner_env)
        self.assertIn("HEALTH_SIDECAR_SOCKET=/run/health-sidecar/health.sock", sidecar_env)
        self.assertIn("HEALTH_SIDECAR_SOCKET_MODE=660", sidecar_env)
        self.assertIn("HEALTH_SIDECAR_SUBJECT=profile", sidecar_env)
        self.assertIn("HEALTH_SIDECAR_EXPECTED_OWNER_SENDER_ID=wx-owner", sidecar_env)
        self.assertIn("HEALTH_SIDECAR_EXPECTED_VIEWER_SENDER_ID=wx-viewer", sidecar_env)
        self.assertIn(
            "HEALTH_SIDECAR_HEALTH_MODEL_CONFIG=/etc/health-sidecar/health-model.json",
            sidecar_env,
        )
        self.assertIn(
            "HEALTH_SIDECAR_HEALTH_MODEL_API_KEY_PATH=/etc/health-sidecar/health-model.key",
            sidecar_env,
        )
        self.assertIn(
            "HEALTH_SIDECAR_SOURCE_METADATA=/etc/health-sidecar/source-metadata.json",
            sidecar_env,
        )
        self.assertIn(
            "HEALTH_SIDECAR_DELIVERY_LEDGER_PATH=/var/lib/health-sidecar/delivery.sqlite3",
            sidecar_env,
        )
        self.assertIn(
            "HEALTH_SIDECAR_JOB_AUTHORIZATION_SECRET_PATH=/etc/health-sidecar/job-authorization.key",
            sidecar_env,
        )
        self.assertIn("HEALTH_SIDECAR_HERMES_SOURCE_ROOT=/opt/hermes-agent", sidecar_env)
        self.assertIn("HEALTH_SIDECAR_ACCEPTED_HERMES_VERSION=0.20.0", sidecar_env)
        self.assertIn("HEALTH_SIDECAR_WEIXIN_BASE_URL=https://weixin.example/api", sidecar_env)
        self.assertIn("HEALTH_SIDECAR_WEIXIN_CDN_BASE_URL=https://weixin.example/cdn", sidecar_env)
        self.assertNotIn("dedicated-model-key", sidecar_env)
        self.assertNotIn("dedicated-weixin-token", sidecar_env)
        self.assertIn(
            f"HEALTH_SIDECAR_ALLOWED_UIDS={self.host.users['hermes-partner'][0]}",
            sidecar_env,
        )
        self.assertIn(
            f"HEALTH_SIDECAR_ALLOWED_GIDS={self.host.groups['health-sidecar-client']}",
            sidecar_env,
        )
        tmpfiles = (
            self.host_root / "etc/tmpfiles.d/partner-health-steward-export.conf"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "D /run/partner-health-steward-export 0700 hermes-partner hermes-partner 1d",
            tmpfiles,
        )

        migrated = self.host_root / "var/lib/hermes-partner/.hermes/profiles/partner"
        self.assertEqual((migrated / ".env").read_text(encoding="utf-8"), "EXISTING_SECRET=preserve\n")
        self.assertEqual(self.default_marker.read_text(encoding="utf-8"), "default-profile-marker\n")
        self.assertTrue(any(item[0] == "hermes-partner" for item in self.host.commands))
        job_installer_calls = [
            command
            for command in self.host.commands
            if command[1][-1].endswith("scripts/install_health_steward_jobs.py")
        ]
        self.assertEqual(len(job_installer_calls), 1)
        self.assertEqual(
            job_installer_calls[0][2]["HEALTH_STEWARD_HEALTH_MODEL_CONFIG"],
            "/etc/partner-health-steward/health-model.json",
        )
        partner_authorization_key = self.host_root / (
            "var/lib/hermes-partner/.hermes/profiles/partner/private/"
            "health-steward-job-authorization.key"
        )
        sidecar_authorization_key = self.host_root / "etc/health-sidecar/job-authorization.key"
        self.assertGreaterEqual(len(partner_authorization_key.read_bytes()), 32)
        self.assertEqual(
            sidecar_authorization_key.read_bytes(), partner_authorization_key.read_bytes()
        )
        # Windows maps owner-only read mode to a read-only file for all
        # identities; the Linux unit/runtime verifier owns the exact 0400
        # permission assertion.  Both fake-host files must still be immutable.
        self.assertEqual(stat.S_IMODE(partner_authorization_key.stat().st_mode) & 0o222, 0)
        self.assertEqual(stat.S_IMODE(sidecar_authorization_key.stat().st_mode) & 0o222, 0)
        self.assertNotIn(("start", "health-sidecar.service"), self.host.services)
        self.assertTrue(
            any(
                Path(item[0]) == self.host_root / "var/lib/health-sidecar"
                and item[1:] == ("health-sidecar", "health-sidecar-client", False)
                for item in self.host.ownership
            )
        )
        self.assertTrue(
            any(
                Path(item[0]) == self.host_root / "var/lib/health-sidecar/state"
                and item[1:] == ("health-sidecar", "health-sidecar", True)
                for item in self.host.ownership
            )
        )
        self.assertTrue(
            any(
                Path(item[0]) == self.host_root / "var/lib/health-sidecar/projection"
                and item[1:] == ("health-sidecar", "health-sidecar-client", True)
                for item in self.host.ownership
            )
        )
        self.assertTrue(
            any(
                Path(item[0]) == self.host_root / "etc/partner-health-steward"
                and item[1:] == ("hermes-partner", "hermes-partner", True)
                for item in self.host.ownership
            )
        )
        self.assertEqual(
            stat.S_IMODE(
                (self.host_root / "etc/health-sidecar/receipt-public.key").stat().st_mode
            )
            & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH),
            0,
        )
        self.assertEqual(
            (self.host_root / "etc/partner-health-steward/health-model.json").read_bytes(),
            self.health_model_config.read_bytes(),
        )
        self.assertEqual(
            (self.host_root / "etc/health-sidecar/health-model.key").read_text(
                encoding="utf-8"
            ),
            "dedicated-model-key\n",
        )

    def test_install_is_idempotent_then_upgrade_and_rollback_switch_release(self) -> None:
        first = DeploymentManager(self.config("r1"), host=self.host)
        first.install()
        first.install()
        first.start()
        self.assertIn(EXPORT_CLEANUP_TIMER, self.host.active_services)
        state_path = self.host_root / "var/lib/partner-health-steward/deployment-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["current_release"], "r1")
        self.assertIsNone(state["previous_release"])
        self.assertIsNone(state["rollback_completed_from"])

        second = DeploymentManager(self.config("r2"), host=self.host)
        second.upgrade()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            state,
            {
                "current_release": "r2",
                "previous_release": "r1",
                "rollback_completed_from": None,
            },
        )
        self.assertIn("/opt/partner-health-steward/releases/r2", (
            self.host_root / "etc/partner-health-steward/partner.env"
        ).read_text(encoding="utf-8"))
        self.assertIn(("enable", EXPORT_CLEANUP_TIMER), self.host.services)
        self.assertIn(("start", EXPORT_CLEANUP_TIMER), self.host.services)
        self.assertIn(EXPORT_CLEANUP_TIMER, self.host.active_services)

        second.rollback()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            state,
            {
                "current_release": "r1",
                "previous_release": "r2",
                "rollback_completed_from": "r2",
            },
        )
        self.assertIn("/opt/partner-health-steward/releases/r1", (
            self.host_root / "etc/partner-health-steward/partner.env"
        ).read_text(encoding="utf-8"))
        self.assertIn(("restart", "health-sidecar.service"), self.host.services)
        self.assertIn(("start", "hermes-gateway-partner-health-steward.service"), self.host.services)
        self.assertIn(EXPORT_CLEANUP_TIMER, self.host.active_services)

        service_count = len(self.host.services)
        repeated = second.rollback()
        self.assertEqual(repeated["result"], "already-rolled-back")
        self.assertEqual(len(self.host.services), service_count)

    def test_preflight_rejects_invalid_key_and_non_partner_migration_source(self) -> None:
        self.public_key.write_bytes(b"short")
        with self.assertRaisesRegex(DeploymentError, "receipt-public-key"):
            DeploymentManager(self.config(), host=self.host).preflight()

        self.public_key.write_bytes(bytes(range(32)))
        bad = self.config()
        object.__setattr__(bad, "legacy_partner_home", "/root/.hermes")
        with self.assertRaisesRegex(DeploymentError, "partner-profile"):
            DeploymentManager(bad, host=self.host).preflight()

        same_identity = self.config()
        object.__setattr__(same_identity, "expected_viewer_sender_id", "wx-owner")
        with self.assertRaisesRegex(DeploymentError, "viewer-must-not-be-owner"):
            DeploymentManager(same_identity, host=self.host).preflight()

    def test_static_verification_rejects_viewer_identity_drift(self) -> None:
        manager = DeploymentManager(self.config(), host=self.host)
        manager.install()
        partner_env = self.host_root / "etc/partner-health-steward/partner.env"
        partner_env.write_text(
            partner_env.read_text(encoding="utf-8").replace(
                "HEALTH_STEWARD_EXPECTED_VIEWER_SENDER_ID=wx-viewer",
                "HEALTH_STEWARD_EXPECTED_VIEWER_SENDER_ID=wx-other",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DeploymentError, "static-deployment"):
            manager.verify_static()

    def test_failed_install_or_upgrade_cannot_rotate_the_receipt_key(self) -> None:
        first = DeploymentManager(self.config("r1"), host=self.host)
        first.install()
        installed_key = self.host_root / "etc/health-sidecar/receipt-public.key"
        original = installed_key.read_bytes()
        replacement_source = Path(self.temp.name) / "replacement-public.key"
        replacement_source.write_bytes(bytes(reversed(range(32))))
        replacement = self.config("r2")
        object.__setattr__(replacement, "receipt_public_key_source", replacement_source)

        with self.assertRaisesRegex(DeploymentError, "requires-upgrade"):
            DeploymentManager(replacement, host=self.host).install()
        self.assertEqual(installed_key.read_bytes(), original)
        with self.assertRaisesRegex(DeploymentError, "public-key-mismatch"):
            DeploymentManager(replacement, host=self.host).upgrade()
        self.assertEqual(installed_key.read_bytes(), original)

    def test_restore_rejects_path_escape_and_copies_only_encrypted_bytes(self) -> None:
        manager = DeploymentManager(self.config(), host=self.host)
        manager.install()
        manager.start()
        state_dir = self.host_root / "var/lib/health-sidecar/state"
        state_file = state_dir / "state.sqlite.enc"
        backups = state_dir / "backups"
        _current_bytes, backup_bytes = self.create_encrypted_backup(state_dir, "known.bak")

        with self.assertRaisesRegex(DeploymentError, "backup-name"):
            manager.restore_backup("../known.bak")
        (backups / "plain.bak").write_bytes(b"SQLite format 3\0" + b"x" * 80)
        with self.assertRaisesRegex(DeploymentError, "plaintext"):
            manager.restore_backup("plain.bak")
        (backups / "unauthenticated.bak").write_bytes(b"not-authenticated" * 8)
        with self.assertRaisesRegex(DeploymentError, "authentication"):
            manager.restore_backup("unauthenticated.bak")

        result = manager.restore_backup("known.bak")
        self.assertEqual(result["result"], "restored")
        self.assertEqual(state_file.read_bytes(), backup_bytes)
        self.assertTrue(any(backups.glob("pre-restore-*.bak")))
        self.assertEqual(
            self.host.services[-4:],
            [
                ("stop", "hermes-gateway-partner-health-steward.service"),
                ("stop", "health-sidecar.service"),
                ("start", "health-sidecar.service"),
                ("start", "hermes-gateway-partner-health-steward.service"),
            ],
        )

    def test_restore_evidence_does_not_claim_copy_when_state_was_absent(self) -> None:
        manager = DeploymentManager(self.config(), host=self.host)
        manager.install()
        state_dir = self.host_root / "var/lib/health-sidecar/state"
        state_file = state_dir / "state.sqlite.enc"
        self.create_encrypted_backup(state_dir, "known.bak")
        state_file.unlink()

        manager.restore_backup("known.bak")

        evidence_dir = self.host_root / "var/lib/partner-health-steward/evidence"
        latest = max(evidence_dir.glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
        record = json.loads(latest.read_text(encoding="utf-8"))
        self.assertEqual(record["action"], "restore")
        self.assertFalse(record["checks"]["pre_restore_copy"])

    def test_restore_rolls_back_state_if_sidecar_rejects_candidate_backup(self) -> None:
        manager = DeploymentManager(self.config(), host=self.host)
        manager.install()
        manager.start()
        state_dir = self.host_root / "var/lib/health-sidecar/state"
        state_file = state_dir / "state.sqlite.enc"
        old, _candidate = self.create_encrypted_backup(state_dir, "candidate.bak")
        self.host.ready_sequence = [False, True]

        with self.assertRaisesRegex(DeploymentError, "restore-rolled-back"):
            manager.restore_backup("candidate.bak")
        self.assertEqual(state_file.read_bytes(), old)
        self.assertIn("health-sidecar.service", self.host.active_services)
        self.assertIn(
            "hermes-gateway-partner-health-steward.service", self.host.active_services
        )
        self.assertIn(EXPORT_CLEANUP_TIMER, self.host.active_services)

    def test_start_refuses_duplicate_legacy_partner_gateway(self) -> None:
        manager = DeploymentManager(self.config(), host=self.host)
        manager.install()
        self.host.active_services.add("hermes-gateway-partner.service")
        with self.assertRaisesRegex(DeploymentError, "legacy-partner"):
            manager.start()
        self.assertNotIn(("start", "health-sidecar.service"), self.host.services)

    def test_upgrade_waits_for_sidecar_and_does_not_record_false_success(self) -> None:
        first = DeploymentManager(self.config("r1"), host=self.host)
        first.install()
        first.start()
        self.host.ready_sequence = [False, True]

        with self.assertRaisesRegex(DeploymentError, "upgrade-sidecar-not-ready"):
            DeploymentManager(self.config("r2"), host=self.host).upgrade()

        evidence_dir = self.host_root / "var/lib/partner-health-steward/evidence"
        evidence = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in evidence_dir.glob("*.json")
        ]
        self.assertFalse(
            any(item["action"] == "upgrade" and item["result"] == "upgraded" for item in evidence)
        )
        state_path = self.host_root / "var/lib/partner-health-steward/deployment-state.json"
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["current_release"],
            "r1",
        )
        self.assertIn("health-sidecar.service", self.host.active_services)
        self.assertIn(
            "hermes-gateway-partner-health-steward.service", self.host.active_services
        )

        result = DeploymentManager(self.config("r2"), host=self.host).upgrade()
        self.assertEqual(result["result"], "upgraded")
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["current_release"],
            "r2",
        )

    def test_failed_upgrade_restores_export_cleanup_timer(self) -> None:
        first = DeploymentManager(self.config("r1"), host=self.host)
        first.install()
        first.start()
        self.assertIn(EXPORT_CLEANUP_TIMER, self.host.active_services)
        self.host.fail_once_start = EXPORT_CLEANUP_TIMER

        with self.assertRaisesRegex(RuntimeError, "simulated-service-start-failure"):
            DeploymentManager(self.config("r2"), host=self.host).upgrade()

        state_path = self.host_root / "var/lib/partner-health-steward/deployment-state.json"
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["current_release"],
            "r1",
        )
        self.assertIn(EXPORT_CLEANUP_TIMER, self.host.active_services)
        timer_starts = [
            action
            for action, unit in self.host.services
            if unit == EXPORT_CLEANUP_TIMER and action == "start"
        ]
        self.assertGreaterEqual(len(timer_starts), 2)

    def test_failed_rollback_restores_current_release_and_can_be_retried(self) -> None:
        first = DeploymentManager(self.config("r1"), host=self.host)
        first.install()
        first.start()
        second = DeploymentManager(self.config("r2"), host=self.host)
        second.upgrade()
        state_path = self.host_root / "var/lib/partner-health-steward/deployment-state.json"
        self.host.ready_sequence = [False, True]
        self.host.run_as_partner_active.clear()

        with self.assertRaisesRegex(DeploymentError, "rollback-sidecar-not-ready"):
            second.rollback()

        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["current_release"],
            "r2",
        )
        self.assertTrue(self.host.run_as_partner_active)
        self.assertFalse(any(self.host.run_as_partner_active))
        self.assertIn("health-sidecar.service", self.host.active_services)
        self.assertIn(
            "hermes-gateway-partner-health-steward.service", self.host.active_services
        )

        result = second.rollback()
        self.assertEqual(result["result"], "rolled-back")
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["current_release"],
            "r1",
        )

    def test_evidence_release_comes_from_installed_state_not_cli_argument(self) -> None:
        DeploymentManager(self.config("r1"), host=self.host).install()
        DeploymentManager(self.config("not-current"), host=self.host).stop()
        evidence_dir = self.host_root / "var/lib/partner-health-steward/evidence"
        latest = max(evidence_dir.glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
        record = json.loads(latest.read_text(encoding="utf-8"))
        self.assertEqual(record["action"], "stop")
        self.assertEqual(record["release_id"], "r1")

    def test_evidence_and_release_manifest_are_content_free(self) -> None:
        manager = DeploymentManager(self.config(), host=self.host)
        manager.install()
        evidence_dir = self.host_root / "var/lib/partner-health-steward/evidence"
        evidence = [json.loads(path.read_text(encoding="utf-8")) for path in evidence_dir.glob("*.json")]
        self.assertTrue(evidence)
        serialized = json.dumps(evidence, ensure_ascii=False)
        self.assertNotIn("EXISTING_SECRET", serialized)
        self.assertNotIn("receipt-public", serialized)
        self.assertEqual(
            set(evidence[-1]),
            {"action", "result", "release_id", "recorded_utc", "checks"},
        )

        release = self.host_root / "opt/partner-health-steward/releases/2026.08.09.1"
        manifest = json.loads((release / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["files"])
        self.assertTrue(all(not path.startswith(".research/") for path in manifest["files"]))
        self.assertTrue(all("health-guard" not in path for path in manifest["files"]))
        self.assertTrue(all("health-autonomy" not in path for path in manifest["files"]))

    def test_fixed_job_verification_rejects_a_third_health_cron(self) -> None:
        manager = DeploymentManager(self.config(), host=self.host)
        manager.install()
        cron_dir = self.host_root / "var/lib/hermes-partner/.hermes/profiles/partner/cron"
        cron_dir.mkdir(parents=True, exist_ok=True)
        model_config = HealthModelConfig.from_file(self.health_model_config)
        records = [
            spec.to_job_record(f"job-{index}")
            for index, spec in enumerate(fixed_job_specs(model_config))
        ]
        (cron_dir / "jobs.json").write_text(
            json.dumps({"jobs": records}), encoding="utf-8"
        )
        self.assertTrue(manager.verify_fixed_jobs())
        records[0]["model"] = "ordinary-chat-model"
        (cron_dir / "jobs.json").write_text(
            json.dumps({"jobs": records}), encoding="utf-8"
        )
        self.assertFalse(manager.verify_fixed_jobs())
        records[0]["model"] = model_config.model_id
        records.append({"id": "third", "name": "health-extra-cron"})
        (cron_dir / "jobs.json").write_text(
            json.dumps({"jobs": records}), encoding="utf-8"
        )
        self.assertFalse(manager.verify_fixed_jobs())

    def test_offline_lifecycle_verifier_proves_key_and_day_30_contract(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/verify_health_steward_lifecycle.py")],
            check=True,
            text=True,
            capture_output=True,
        )
        evidence = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(evidence["result"], "passed")
        self.assertTrue(evidence["profile_key_destroyed"])
        self.assertTrue(evidence["backup_undecryptable"])
        self.assertTrue(evidence["day_30_purge"])

    def test_job_smoke_accepts_only_current_successful_daily_evidence(self) -> None:
        script = ROOT / "scripts/verify_health_steward_job_smoke.py"
        spec = importlib.util.spec_from_file_location("health_job_smoke", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with mock.patch.dict(
            os.environ,
            {"HEALTH_STEWARD_HEALTH_MODEL_CONFIG": str(self.health_model_config)},
            clear=False,
        ):
            smoke_specs = module._fixed_specs()
        self.assertTrue(all(spec.model_provider == "custom" for spec in smoke_specs))
        with mock.patch.dict(
            os.environ,
            {"HEALTH_STEWARD_HEALTH_MODEL_CONFIG": ""},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "health-model-config-unavailable"):
                module._fixed_specs()

        now = dt.datetime(2026, 8, 9, 1, 0, tzinfo=dt.timezone.utc)
        current = {"last_run_at": "2026-08-09T04:03:00+08:00", "last_status": "ok"}
        stale = {"last_run_at": "2026-08-08T04:03:00+08:00", "last_status": "ok"}
        failed = {"last_run_at": "2026-08-09T04:03:00+08:00", "last_status": "error"}
        self.assertTrue(module._ran_today(current, now))
        self.assertFalse(module._ran_today(stale, now))
        self.assertFalse(module._ran_today(failed, now))

        events = [
            {
                "utc": "2026-08-08T20:01:00+00:00",
                "event": "daily_review_snapshot",
                "details": {"subject": "profile", "result": "provided"},
            },
            {
                "utc": "2026-08-08T20:02:00+00:00",
                "event": "daily_review_completed",
                "details": {"subject": "profile", "local_date": "2026-08-09"},
            },
        ]
        self.assertTrue(module._has_current_daily_audit(events, now))
        self.assertFalse(module._has_current_daily_audit(events[:1], now))


if __name__ == "__main__":
    unittest.main()

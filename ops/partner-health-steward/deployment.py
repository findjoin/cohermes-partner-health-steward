"""Repeatable partner-only Linux deployment for the health steward.

The module deliberately separates file staging from service start.  ``install``
never cuts over the live partner gateway; Ticket 15 must make that explicit
operator decision after the Linux verification commands pass.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

try:  # Linux-only modules; the filesystem package is unit-tested on Windows.
    import grp
    import pwd
except ImportError:  # pragma: no cover - exercised by the Windows test host
    grp = None  # type: ignore[assignment]
    pwd = None  # type: ignore[assignment]


PARTNER_USER = "hermes-partner"
SIDECAR_USER = "health-sidecar"
CLIENT_GROUP = "health-sidecar-client"
PARTNER_UNIT = "hermes-gateway-partner-health-steward.service"
SIDECAR_UNIT = "health-sidecar.service"
LEGACY_PARTNER_UNIT = "hermes-gateway-partner.service"
SOCKET_PATH = "/run/health-sidecar/health.sock"
PARTNER_HOME = "/var/lib/hermes-partner/.hermes/profiles/partner"
LEGACY_PARTNER_HOME = "/root/.hermes/profiles/partner"
STATE_PATH = "/var/lib/health-sidecar/state/state.sqlite.enc"
KEY_PATH = "/var/lib/health-sidecar/state/sidecar.key"
PUBLIC_KEY_PATH = "/etc/health-sidecar/receipt-public.key"
SIDECAR_JOB_AUTHORIZATION_SECRET_PATH = "/etc/health-sidecar/job-authorization.key"
PARTNER_JOB_AUTHORIZATION_SECRET_PATH = (
    "/var/lib/hermes-partner/.hermes/profiles/partner/private/"
    "health-steward-job-authorization.key"
)
PROJECTION_PATH = "/var/lib/health-sidecar/projection/memory.json"
STATE_RECORD_PATH = "/var/lib/partner-health-steward/deployment-state.json"
DELIVERY_LEDGER_PATH = "/var/lib/hermes-partner/health-delivery.sqlite3"
SIDECAR_DELIVERY_LEDGER_PATH = "/var/lib/health-sidecar/delivery.sqlite3"
HEALTH_MODEL_ATTESTATION_PATH = "/var/lib/hermes-partner/health-model-attestation.json"
PARTNER_HEALTH_MODEL_CONFIG_PATH = "/etc/partner-health-steward/health-model.json"
PARTNER_HEALTH_SOURCE_CATALOG_PATH = "/etc/partner-health-steward/health-source-catalog.json"
SIDECAR_HEALTH_MODEL_CONFIG_PATH = "/etc/health-sidecar/health-model.json"
SIDECAR_HEALTH_MODEL_API_KEY_PATH = "/etc/health-sidecar/health-model.key"
SIDECAR_WEIXIN_TOKEN_PATH = "/etc/health-sidecar/weixin.token"
SIDECAR_SOURCE_METADATA_PATH = "/etc/health-sidecar/source-metadata.json"
EXPORT_TMPDIR = "/run/partner-health-steward-export"
EXPORT_TMPFILES_PATH = "/etc/tmpfiles.d/partner-health-steward-export.conf"
EXPORT_CLEANUP_UNIT = "partner-health-steward-export-cleanup.service"
EXPORT_CLEANUP_TIMER = "partner-health-steward-export-cleanup.timer"

_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_BACKUP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ENCRYPTED_DATABASE_MINIMUM = 12 + 32 + 1

_RELEASE_FILES = (
    "deployment.py",
    "export_attachments.py",
    "health_model.py",
    "health_turn.py",
    "health_turn_answer.py",
    "hermes_jobs.py",
    "job_authorization.py",
    "owner_controls.py",
    "plugin/health-steward",
    "sidecar",
    "weixin_ingress.py",
    "scripts/deploy_health_steward.py",
    "scripts/health_steward_snapshot.py",
    "scripts/health_steward_daily_snapshot.py",
    "scripts/health_steward_dispatch_snapshot.py",
    "scripts/install_health_steward_jobs.py",
    "scripts/linux_health_smoke_wizard.sh",
    "scripts/verify_health_steward_lifecycle.py",
    "scripts/verify_health_steward_job_smoke.py",
    "LINUX_DEPLOYMENT.md",
)


class DeploymentError(RuntimeError):
    """Fail-closed deployment validation error."""


class HostOperations(Protocol):
    def ensure_group(self, name: str) -> int: ...

    def ensure_user(
        self,
        name: str,
        *,
        home: str,
        primary_group: str,
        supplementary_groups: tuple[str, ...] = (),
    ) -> tuple[int, int]: ...

    def user_ids(self, name: str) -> tuple[int, int] | None: ...

    def group_id(self, name: str) -> int | None: ...

    def group_members(self, name: str) -> set[str]: ...

    def set_owner(self, path: Path, user: str, group: str, *, recursive: bool = False) -> None: ...

    def run_as(self, user: str, argv: list[str], env: dict[str, str]) -> None: ...

    def service(self, action: str, unit: str) -> None: ...

    def daemon_reload(self) -> None: ...

    def service_active(self, unit: str) -> bool: ...

    def legacy_partner_active(self) -> bool: ...

    def process_ids(self, pid: int) -> tuple[int, int] | None: ...

    def sidecar_ready(
        self, user: str, socket_path: str, python: str, *, timeout_seconds: float
    ) -> bool: ...


@dataclass(frozen=True)
class DeploymentConfig:
    root: Path
    source_root: Path
    release_id: str
    receipt_public_key_source: Path
    sidecar_python: str
    hermes_python: str
    partner_exec_start: str
    expected_owner_sender_id: str
    expected_viewer_sender_id: str
    health_model_config_source: Path
    health_source_catalog_source: Path
    sidecar_source_metadata_source: Path
    sidecar_health_model_api_key_source: Path
    sidecar_weixin_token_source: Path
    receipt_signer_socket: str
    hermes_source_root: str
    accepted_hermes_version: str
    weixin_base_url: str
    weixin_cdn_base_url: str
    legacy_partner_home: str = LEGACY_PARTNER_HOME
    partner_home: str = PARTNER_HOME
    timezone: str = "Asia/Shanghai"
    subject: str = "profile"
    approved_guideline_hosts: tuple[str, ...] = ()


class SystemHost:
    """Linux account, ownership, command and systemd operations."""

    @staticmethod
    def _run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def ensure_group(self, name: str) -> int:
        self._require_linux_accounts()
        assert grp is not None
        try:
            return int(grp.getgrnam(name).gr_gid)
        except KeyError:
            self._run(["groupadd", "--system", name])
            return int(grp.getgrnam(name).gr_gid)

    def ensure_user(
        self,
        name: str,
        *,
        home: str,
        primary_group: str,
        supplementary_groups: tuple[str, ...] = (),
    ) -> tuple[int, int]:
        self._require_linux_accounts()
        assert pwd is not None and grp is not None
        self.ensure_group(primary_group)
        try:
            record = pwd.getpwnam(name)
        except KeyError:
            self._run(
                [
                    "useradd",
                    "--system",
                    "--home-dir",
                    home,
                    "--create-home",
                    "--shell",
                    "/usr/sbin/nologin",
                    "--gid",
                    primary_group,
                    name,
                ]
            )
            record = pwd.getpwnam(name)
        if supplementary_groups:
            self._run(["usermod", "--append", "--groups", ",".join(supplementary_groups), name])
            record = pwd.getpwnam(name)
        primary_gid = grp.getgrnam(primary_group).gr_gid
        if (
            record.pw_dir != home
            or record.pw_shell != "/usr/sbin/nologin"
            or record.pw_gid != primary_gid
        ):
            raise DeploymentError(f"existing-account-contract-mismatch:{name}")
        return int(record.pw_uid), int(record.pw_gid)

    def user_ids(self, name: str) -> tuple[int, int] | None:
        self._require_linux_accounts()
        assert pwd is not None
        try:
            record = pwd.getpwnam(name)
        except KeyError:
            return None
        return int(record.pw_uid), int(record.pw_gid)

    def group_id(self, name: str) -> int | None:
        self._require_linux_accounts()
        assert grp is not None
        try:
            return int(grp.getgrnam(name).gr_gid)
        except KeyError:
            return None

    def group_members(self, name: str) -> set[str]:
        self._require_linux_accounts()
        assert grp is not None and pwd is not None
        record = grp.getgrnam(name)
        members = set(record.gr_mem)
        members.update(item.pw_name for item in pwd.getpwall() if item.pw_gid == record.gr_gid)
        return members

    def set_owner(self, path: Path, user: str, group: str, *, recursive: bool = False) -> None:
        self._require_linux_accounts()
        assert pwd is not None and grp is not None
        uid = pwd.getpwnam(user).pw_uid
        gid = grp.getgrnam(group).gr_gid
        targets = [path]
        if recursive and path.is_dir():
            targets.extend(path.rglob("*"))
        for target in targets:
            os.chown(target, uid, gid, follow_symlinks=False)

    def run_as(self, user: str, argv: list[str], env: dict[str, str]) -> None:
        command = ["runuser", "--user", user, "--", "env"]
        command.extend(f"{key}={value}" for key, value in sorted(env.items()))
        command.extend(argv)
        self._run(command)

    def service(self, action: str, unit: str) -> None:
        if action not in {"enable", "disable", "start", "stop", "restart"}:
            raise DeploymentError(f"unsupported-service-action:{action}")
        self._run(["systemctl", action, unit])

    def service_active(self, unit: str) -> bool:
        result = self._run(["systemctl", "is-active", "--quiet", unit], check=False)
        return result.returncode == 0

    def legacy_partner_active(self) -> bool:
        if self.service_active(LEGACY_PARTNER_UNIT):
            return True
        environment = dict(os.environ)
        environment["XDG_RUNTIME_DIR"] = "/run/user/0"
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", LEGACY_PARTNER_UNIT],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        return result.returncode == 0

    def process_ids(self, pid: int) -> tuple[int, int] | None:
        try:
            lines = Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        values: dict[str, int] = {}
        for line in lines:
            if line.startswith("Uid:"):
                values["uid"] = int(line.split()[1])
            elif line.startswith("Gid:"):
                values["gid"] = int(line.split()[1])
        if set(values) != {"uid", "gid"}:
            return None
        return values["uid"], values["gid"]

    def sidecar_ready(
        self, user: str, socket_path: str, python: str, *, timeout_seconds: float
    ) -> bool:
        probe = (
            "import socket,sys;"
            "s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);"
            "s.settimeout(1);s.connect(sys.argv[1]);s.close()"
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result = self._run(
                ["runuser", "--user", user, "--", python, "-c", probe, socket_path],
                check=False,
            )
            if result.returncode == 0:
                return True
            time.sleep(0.2)
        return False

    def daemon_reload(self) -> None:
        self._run(["systemctl", "daemon-reload"])

    def service_property(self, unit: str, field: str) -> str:
        result = self._run(["systemctl", "show", unit, f"--property={field}", "--value"])
        return result.stdout.strip()

    def can_read(self, user: str, path: str) -> bool:
        result = self._run(
            ["runuser", "--user", user, "--", "test", "-r", path], check=False
        )
        return result.returncode == 0

    def tcp_listener_lines(self) -> list[str]:
        result = self._run(["ss", "--tcp", "--listening", "--numeric", "--processes", "--no-header"])
        return [line for line in result.stdout.splitlines() if line.strip()]

    @staticmethod
    def _require_linux_accounts() -> None:
        if pwd is None or grp is None:
            raise DeploymentError("linux-account-operations-required")


class DeploymentManager:
    def __init__(self, config: DeploymentConfig, *, host: HostOperations | None = None) -> None:
        self.config = config
        self.host = host or SystemHost()
        self.root = config.root.resolve()

    def host_path(self, absolute_path: str) -> Path:
        if not absolute_path.startswith("/") or "\0" in absolute_path:
            raise DeploymentError(f"absolute-linux-path-required:{absolute_path}")
        parts = [part for part in absolute_path.split("/") if part]
        if any(part in {".", ".."} for part in parts):
            raise DeploymentError(f"unsafe-linux-path:{absolute_path}")
        return self.root.joinpath(*parts)

    def preflight(self) -> dict[str, Any]:
        cfg = self.config
        if not _RELEASE_ID.fullmatch(cfg.release_id):
            raise DeploymentError("invalid-release-id")
        source = cfg.source_root.resolve()
        for relative in _RELEASE_FILES:
            if not (source / relative).exists():
                raise DeploymentError(f"release-source-missing:{relative}")
        key = cfg.receipt_public_key_source.read_bytes()
        if len(key) != 32:
            raise DeploymentError("invalid-receipt-public-key-length")
        runtime_inputs = (
            cfg.health_model_config_source,
            cfg.health_source_catalog_source,
            cfg.sidecar_source_metadata_source,
            cfg.sidecar_health_model_api_key_source,
            cfg.sidecar_weixin_token_source,
        )
        for runtime_input in runtime_inputs:
            path = Path(runtime_input).expanduser()
            if path.is_symlink() or not path.is_file():
                raise DeploymentError("production-runtime-input-unavailable")
        try:
            from health_model import HealthModelConfig
            from health_turn import HealthSourceCatalog
            from sidecar.production_ports import ApprovedSourceFetch

            health_model_config = HealthModelConfig.from_file(
                cfg.health_model_config_source
            )
            HealthSourceCatalog.from_file(cfg.health_source_catalog_source)
            ApprovedSourceFetch.from_file(cfg.sidecar_source_metadata_source)
        except Exception as exc:
            raise DeploymentError("production-runtime-input-invalid") from exc
        if health_model_config.auth_profile != "partner":
            raise DeploymentError("health-model-auth-profile-must-be-partner")
        for secret_path in (
            cfg.sidecar_health_model_api_key_source,
            cfg.sidecar_weixin_token_source,
        ):
            try:
                if not Path(secret_path).read_text(encoding="utf-8").strip():
                    raise ValueError("empty")
            except (OSError, UnicodeError, ValueError) as exc:
                raise DeploymentError("production-runtime-secret-unavailable") from exc
        for value, code in (
            (cfg.receipt_signer_socket, "receipt-signer-socket"),
            (cfg.hermes_source_root, "hermes-source-root"),
        ):
            if (
                not isinstance(value, str)
                or not value.startswith("/")
                or not re.fullmatch(r"/[A-Za-z0-9._:/-]{0,255}", value)
            ):
                raise DeploymentError(f"invalid-{code}")
        if (
            not isinstance(cfg.accepted_hermes_version, str)
            or not _SAFE_TOKEN.fullmatch(cfg.accepted_hermes_version)
        ):
            raise DeploymentError("invalid-accepted-hermes-version")
        for value, code in (
            (cfg.weixin_base_url, "weixin-base-url"),
            (cfg.weixin_cdn_base_url, "weixin-cdn-url"),
        ):
            if (
                not isinstance(value, str)
                or not value.startswith("https://")
                or not _SAFE_TOKEN.fullmatch(value)
            ):
                raise DeploymentError(f"invalid-{code}")
        self._require_partner_profile(cfg.legacy_partner_home)
        self._require_partner_profile(cfg.partner_home)
        if cfg.legacy_partner_home == cfg.partner_home:
            raise DeploymentError("partner-migration-source-equals-target")
        for executable in (cfg.sidecar_python, cfg.hermes_python):
            if not executable.startswith("/") or "\n" in executable or "\r" in executable:
                raise DeploymentError("absolute-python-path-required")
        self._partner_exec_tokens()
        if not _SAFE_TOKEN.fullmatch(cfg.subject) or not _SAFE_TOKEN.fullmatch(cfg.timezone):
            raise DeploymentError("invalid-deployment-token")
        for value in (
            cfg.expected_owner_sender_id,
            cfg.expected_viewer_sender_id,
        ):
            if (
                not isinstance(value, str)
                or not value
                or any(char in value for char in "\x00\r\n\"'")
                or any(char.isspace() for char in value)
            ):
                raise DeploymentError("invalid-weixin-sender-id")
        if cfg.expected_owner_sender_id == cfg.expected_viewer_sender_id:
            raise DeploymentError("viewer-must-not-be-owner")
        legacy = self.host_path(cfg.legacy_partner_home)
        target = self.host_path(cfg.partner_home)
        if not legacy.is_dir() and not target.is_dir():
            raise DeploymentError("partner-profile-source-unavailable")
        return {
            "action": "preflight",
            "result": "passed",
            "release_id": cfg.release_id,
            "checks": {
                "partner_scope": True,
                "raw_ed25519_public_key": True,
                "allowlisted_release": True,
            },
        }

    def install(self) -> dict[str, Any]:
        return self._install(allow_upgrade=False, restart=False)

    def upgrade(self) -> dict[str, Any]:
        return self._install(allow_upgrade=True, restart=True)

    def _install(self, *, allow_upgrade: bool, restart: bool) -> dict[str, Any]:
        self._require_mutation_authority()
        self.preflight()
        old_state = self._read_deployment_state()
        current = old_state.get("current_release")
        if current and current != self.config.release_id and not allow_upgrade:
            raise DeploymentError("existing-release-requires-upgrade")
        existing_public_key = self.host_path(PUBLIC_KEY_PATH)
        if (
            existing_public_key.is_file()
            and existing_public_key.read_bytes()
            != self.config.receipt_public_key_source.read_bytes()
        ):
            raise DeploymentError("receipt-public-key-mismatch")
        client_gid = self.host.ensure_group(CLIENT_GROUP)
        self.host.ensure_group(PARTNER_USER)
        self.host.ensure_group(SIDECAR_USER)
        partner_uid, _ = self.host.ensure_user(
            PARTNER_USER,
            home="/var/lib/hermes-partner",
            primary_group=PARTNER_USER,
            supplementary_groups=(CLIENT_GROUP,),
        )
        self.host.ensure_user(
            SIDECAR_USER,
            home="/var/lib/health-sidecar",
            primary_group=SIDECAR_USER,
            supplementary_groups=(CLIENT_GROUP,),
        )
        if self.host.group_members(CLIENT_GROUP) != {PARTNER_USER, SIDECAR_USER}:
            raise DeploymentError("socket-client-group-has-unexpected-members")

        release = self._stage_release()
        self._prepare_directories()
        self._migrate_partner_profile()
        self._install_public_key()
        self._write_projection_bridge()
        self._install_production_runtime_inputs()

        sidecar_was_active = self.host.service_active(SIDECAR_UNIT) if restart else False
        partner_was_active = self.host.service_active(PARTNER_UNIT) if restart else False
        export_timer_was_active = (
            self.host.service_active(EXPORT_CLEANUP_TIMER) if restart else False
        )
        if partner_was_active and not sidecar_was_active:
            raise DeploymentError("upgrade-runtime-inconsistent")
        current_release = None
        if restart and current:
            current_release = self.host_path(
                f"/opt/partner-health-steward/releases/{current}"
            )
            self._verify_release(current_release)
        if partner_was_active:
            self.host.service("stop", PARTNER_UNIT)

        new_state = {
            "current_release": self.config.release_id,
            "previous_release": current if current != self.config.release_id else old_state.get("previous_release"),
            "rollback_completed_from": None,
        }
        try:
            self._activate_release(
                self.config.release_id, release, partner_uid, client_gid
            )
            self._write_units()
            self.host.daemon_reload()
            if sidecar_was_active:
                self.host.service("restart", SIDECAR_UNIT)
                if not self.host.sidecar_ready(
                    PARTNER_USER,
                    SOCKET_PATH,
                    self.config.hermes_python,
                    timeout_seconds=10,
                ):
                    raise DeploymentError("upgrade-sidecar-not-ready")
            if partner_was_active:
                self.host.service("start", PARTNER_UNIT)
                self._start_export_cleanup_timer(release)
        except Exception:
            if restart and current_release is not None:
                try:
                    self._recover_runtime_release(
                        current,
                        current_release,
                        partner_uid,
                        client_gid,
                        sidecar_was_active=sidecar_was_active,
                        partner_was_active=partner_was_active,
                        export_timer_was_active=export_timer_was_active,
                    )
                except Exception as recovery_exc:
                    raise DeploymentError("upgrade-runtime-recovery-failed") from recovery_exc
            raise
        self._write_deployment_state(new_state)
        result = "upgraded" if allow_upgrade and current != self.config.release_id else "installed"
        self._record_evidence(
            "upgrade" if allow_upgrade else "install",
            result,
            {
                "partner_only": True,
                "separate_accounts": True,
                "private_socket_configuration_written": True,
                "release_manifest_verified": True,
                "jobs_install_requested": True,
            },
        )
        return {"action": "upgrade" if allow_upgrade else "install", "result": result}

    def start(self) -> dict[str, Any]:
        self._require_mutation_authority()
        state = self._require_installed_state()
        release = self.host_path(
            f"/opt/partner-health-steward/releases/{state['current_release']}"
        )
        if self.host.legacy_partner_active():
            raise DeploymentError("legacy-partner-service-still-active")
        self.host.daemon_reload()
        self.host.service("enable", SIDECAR_UNIT)
        self.host.service("enable", PARTNER_UNIT)
        self.host.service("start", SIDECAR_UNIT)
        if not self.host.sidecar_ready(
            PARTNER_USER, SOCKET_PATH, self.config.hermes_python, timeout_seconds=10
        ):
            self.host.service("stop", SIDECAR_UNIT)
            raise DeploymentError("sidecar-not-ready")
        try:
            self.host.service("start", PARTNER_UNIT)
            self._start_export_cleanup_timer(release)
        except Exception:
            self.host.service("stop", PARTNER_UNIT)
            self.host.service("stop", SIDECAR_UNIT)
            raise
        self._record_evidence("start", "started", {"sidecar_first": True, "partner_only": True})
        return {"action": "start", "result": "started"}

    def stop(self) -> dict[str, Any]:
        self._require_mutation_authority()
        self._require_installed_state()
        self.host.service("stop", PARTNER_UNIT)
        self.host.service("stop", SIDECAR_UNIT)
        self._record_evidence("stop", "stopped", {"partner_first": True, "partner_only": True})
        return {"action": "stop", "result": "stopped"}

    def rollback(self) -> dict[str, Any]:
        self._require_mutation_authority()
        state = self._require_installed_state()
        previous = state.get("previous_release")
        current = state.get("current_release")
        if state.get("rollback_completed_from") == previous:
            return {
                "action": "rollback",
                "result": "already-rolled-back",
                "release_id": current,
            }
        if not isinstance(previous, str) or not _RELEASE_ID.fullmatch(previous):
            raise DeploymentError("rollback-release-unavailable")
        release = self.host_path(f"/opt/partner-health-steward/releases/{previous}")
        self._verify_release(release)
        partner_ids = self.host.user_ids(PARTNER_USER)
        client_gid = self.host.group_id(CLIENT_GROUP)
        if partner_ids is None or client_gid is None:
            raise DeploymentError("deployment-accounts-unavailable")
        sidecar_was_active = self.host.service_active(SIDECAR_UNIT)
        partner_was_active = self.host.service_active(PARTNER_UNIT)
        export_timer_was_active = self.host.service_active(EXPORT_CLEANUP_TIMER)
        current_release = self.host_path(
            f"/opt/partner-health-steward/releases/{current}"
        )
        self._verify_release(current_release)
        if partner_was_active:
            if not sidecar_was_active:
                raise DeploymentError("rollback-runtime-inconsistent")
            self.host.service("stop", PARTNER_UNIT)
        try:
            self._activate_release(previous, release, partner_ids[0], client_gid)
            self.host.daemon_reload()
            if sidecar_was_active:
                self.host.service("restart", SIDECAR_UNIT)
                if not self.host.sidecar_ready(
                    PARTNER_USER,
                    SOCKET_PATH,
                    self.config.hermes_python,
                    timeout_seconds=10,
                ):
                    raise DeploymentError("rollback-sidecar-not-ready")
            if partner_was_active:
                self.host.service("start", PARTNER_UNIT)
                self._start_export_cleanup_timer(release)
            elif not self._release_supports_export_cleanup(release):
                self._stop_export_cleanup_timer()
        except Exception:
            try:
                self._recover_runtime_release(
                    current,
                    current_release,
                    partner_ids[0],
                    client_gid,
                    sidecar_was_active=sidecar_was_active,
                    partner_was_active=partner_was_active,
                    export_timer_was_active=export_timer_was_active,
                )
            except Exception as recovery_exc:
                raise DeploymentError("rollback-runtime-recovery-failed") from recovery_exc
            raise
        self._write_deployment_state(
            {
                "current_release": previous,
                "previous_release": current,
                "rollback_completed_from": current,
            }
        )
        self._record_evidence(
            "rollback", "rolled-back", {"release_manifest_verified": True, "partner_only": True}
        )
        return {"action": "rollback", "result": "rolled-back", "release_id": previous}

    def restore_backup(self, backup_name: str) -> dict[str, Any]:
        self._require_mutation_authority()
        self._require_installed_state()
        if not _BACKUP_NAME.fullmatch(backup_name) or Path(backup_name).name != backup_name:
            raise DeploymentError("invalid-backup-name")
        state_path = self.host_path(STATE_PATH)
        backup_dir = state_path.parent / "backups"
        source = backup_dir / backup_name
        if source.is_symlink():
            raise DeploymentError("backup-symlink-refused")
        if not source.is_file():
            raise DeploymentError("backup-unavailable")
        blob = source.read_bytes()
        if blob.startswith(b"SQLite format 3\0"):
            raise DeploymentError("plaintext-backup-refused")
        if len(blob) < _ENCRYPTED_DATABASE_MINIMUM:
            raise DeploymentError("encrypted-backup-too-short")
        try:
            from sidecar.store import StoreError, validate_encrypted_database_backup

            validate_encrypted_database_backup(source, self.host_path(KEY_PATH))
        except StoreError as exc:
            raise DeploymentError("encrypted-backup-authentication-failed") from exc

        partner_was_active = self.host.service_active(PARTNER_UNIT)
        sidecar_was_active = self.host.service_active(SIDECAR_UNIT)
        if partner_was_active:
            self.host.service("stop", PARTNER_UNIT)
        if sidecar_was_active:
            self.host.service("stop", SIDECAR_UNIT)
        before: Path | None = None
        try:
            if state_path.is_file():
                stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                before = backup_dir / f"pre-restore-{stamp}.bak"
                shutil.copy2(state_path, before)
                before.chmod(0o600)
                self.host.set_owner(before, SIDECAR_USER, SIDECAR_USER)
            self._atomic_write_bytes(state_path, blob, mode=0o600)
            self.host.set_owner(state_path, SIDECAR_USER, SIDECAR_USER)
            if sidecar_was_active:
                self.host.service("start", SIDECAR_UNIT)
                if not self.host.sidecar_ready(
                    PARTNER_USER,
                    SOCKET_PATH,
                    self.config.hermes_python,
                    timeout_seconds=10,
                ):
                    raise DeploymentError("restored-sidecar-not-ready")
            if partner_was_active:
                self.host.service("start", PARTNER_UNIT)
        except Exception as exc:
            if sidecar_was_active:
                self.host.service("stop", SIDECAR_UNIT)
            if before is not None and before.is_file():
                self._atomic_write_bytes(state_path, before.read_bytes(), mode=0o600)
                self.host.set_owner(state_path, SIDECAR_USER, SIDECAR_USER)
            if sidecar_was_active:
                self.host.service("start", SIDECAR_UNIT)
                if not self.host.sidecar_ready(
                    PARTNER_USER,
                    SOCKET_PATH,
                    self.config.hermes_python,
                    timeout_seconds=10,
                ):
                    raise DeploymentError("backup-restore-and-rollback-failed") from exc
            if partner_was_active:
                self.host.service("start", PARTNER_UNIT)
            raise DeploymentError("backup-restore-rolled-back") from exc
        self._record_evidence(
            "restore",
            "restored",
            {"encrypted_backup": True, "pre_restore_copy": before is not None},
        )
        return {"action": "restore", "result": "restored"}

    def verify_static(self) -> dict[str, Any]:
        state = self._require_installed_state()
        release_id = state["current_release"]
        release = self.host_path(f"/opt/partner-health-steward/releases/{release_id}")
        self._verify_release(release)
        sidecar = self.host_path("/etc/systemd/system/health-sidecar.service").read_text(
            encoding="utf-8"
        )
        partner = self.host_path(
            "/etc/systemd/system/hermes-gateway-partner-health-steward.service"
        ).read_text(encoding="utf-8")
        export_tmpfiles = self.host_path(EXPORT_TMPFILES_PATH).read_text(
            encoding="utf-8"
        )
        export_cleanup_unit = self.host_path(
            f"/etc/systemd/system/{EXPORT_CLEANUP_UNIT}"
        ).read_text(encoding="utf-8")
        export_cleanup_timer = self.host_path(
            f"/etc/systemd/system/{EXPORT_CLEANUP_TIMER}"
        ).read_text(encoding="utf-8")
        partner_env = set(
            self.host_path(
                "/etc/partner-health-steward/partner.env"
            ).read_text(encoding="utf-8").splitlines()
        )
        sidecar_env = set(
            self.host_path(
                "/etc/health-sidecar/health-sidecar.env"
            ).read_text(encoding="utf-8").splitlines()
        )
        owner = self.config.expected_owner_sender_id
        viewer = self.config.expected_viewer_sender_id
        checks = {
            "release_manifest": True,
            "sidecar_account": "User=health-sidecar" in sidecar,
            "partner_account": "User=hermes-partner" in partner,
            "no_socket_unit_tcp_listener": "ListenStream" not in sidecar,
            "partner_state_inaccessible": (
                "InaccessiblePaths=/var/lib/health-sidecar/state /etc/health-sidecar"
                in partner
            ),
            "partner_identity_configuration": {
                f"HEALTH_STEWARD_EXPECTED_OWNER_SENDER_ID={owner}",
                f"HEALTH_STEWARD_EXPECTED_VIEWER_SENDER_ID={viewer}",
                f"WEIXIN_ALLOWED_USERS={owner},{viewer}",
                "WEIXIN_DM_POLICY=allowlist",
            }.issubset(partner_env),
            "private_export_configuration": {
                f"HEALTH_STEWARD_DELIVERY_LEDGER_PATH={DELIVERY_LEDGER_PATH}",
                (
                    "HEALTH_STEWARD_HEALTH_MODEL_ATTESTATION_PATH="
                    f"{HEALTH_MODEL_ATTESTATION_PATH}"
                ),
                f"HEALTH_STEWARD_EXPORT_TMPDIR={EXPORT_TMPDIR}",
            }.issubset(partner_env)
            and "RuntimeDirectory=partner-health-steward-export" in partner
            and "RuntimeDirectoryMode=0700" in partner
            and f"ReadWritePaths=/var/lib/hermes-partner {EXPORT_TMPDIR}" in partner
            and (
                "D /run/partner-health-steward-export 0700 "
                "hermes-partner hermes-partner 1d"
            ) in export_tmpfiles,
            "private_export_cleanup_timer": (
                "--cleanup --directory ${HEALTH_STEWARD_EXPORT_TMPDIR}"
                in export_cleanup_unit
                and "User=hermes-partner" in export_cleanup_unit
                and f"ReadWritePaths={EXPORT_TMPDIR}" in export_cleanup_unit
                and "OnCalendar=hourly" in export_cleanup_timer
                and "Persistent=true" in export_cleanup_timer
                and f"Unit={EXPORT_CLEANUP_UNIT}" in export_cleanup_timer
            ),
            "sidecar_identity_configuration": {
                f"HEALTH_SIDECAR_EXPECTED_OWNER_SENDER_ID={owner}",
                f"HEALTH_SIDECAR_EXPECTED_VIEWER_SENDER_ID={viewer}",
            }.issubset(sidecar_env),
            "production_job_port_configuration": {
                (
                    "HEALTH_STEWARD_HEALTH_MODEL_CONFIG="
                    f"{PARTNER_HEALTH_MODEL_CONFIG_PATH}"
                ),
                (
                    "HEALTH_STEWARD_HEALTH_SOURCE_CATALOG="
                    f"{PARTNER_HEALTH_SOURCE_CATALOG_PATH}"
                ),
                (
                    "HEALTH_STEWARD_HERMES_SOURCE_ROOT="
                    f"{self.config.hermes_source_root}"
                ),
                (
                    "HEALTH_STEWARD_ACCEPTED_HERMES_VERSION="
                    f"{self.config.accepted_hermes_version}"
                ),
                (
                    "HEALTH_STEWARD_RECEIPT_SIGNER_SOCKET="
                    f"{self.config.receipt_signer_socket}"
                ),
                (
                    "HEALTH_STEWARD_JOB_AUTHORIZATION_SECRET="
                    f"{PARTNER_JOB_AUTHORIZATION_SECRET_PATH}"
                ),
                f"HERMES_TIMEZONE={self.config.timezone}",
            }.issubset(partner_env)
            and {
                (
                    "HEALTH_SIDECAR_HEALTH_MODEL_CONFIG="
                    f"{SIDECAR_HEALTH_MODEL_CONFIG_PATH}"
                ),
                (
                    "HEALTH_SIDECAR_HEALTH_MODEL_API_KEY_PATH="
                    f"{SIDECAR_HEALTH_MODEL_API_KEY_PATH}"
                ),
                (
                    "HEALTH_SIDECAR_SOURCE_METADATA="
                    f"{SIDECAR_SOURCE_METADATA_PATH}"
                ),
                (
                    "HEALTH_SIDECAR_DELIVERY_LEDGER_PATH="
                    f"{SIDECAR_DELIVERY_LEDGER_PATH}"
                ),
                (
                    "HEALTH_SIDECAR_HERMES_SOURCE_ROOT="
                    f"{self.config.hermes_source_root}"
                ),
                (
                    "HEALTH_SIDECAR_ACCEPTED_HERMES_VERSION="
                    f"{self.config.accepted_hermes_version}"
                ),
                (
                    "HEALTH_SIDECAR_WEIXIN_BASE_URL="
                    f"{self.config.weixin_base_url}"
                ),
                (
                    "HEALTH_SIDECAR_WEIXIN_CDN_BASE_URL="
                    f"{self.config.weixin_cdn_base_url}"
                ),
                (
                    "HEALTH_SIDECAR_WEIXIN_TOKEN_PATH="
                    f"{SIDECAR_WEIXIN_TOKEN_PATH}"
                ),
                (
                    "HEALTH_SIDECAR_JOB_AUTHORIZATION_SECRET_PATH="
                    f"{SIDECAR_JOB_AUTHORIZATION_SECRET_PATH}"
                ),
            }.issubset(sidecar_env)
            and "InaccessiblePaths=/var/lib/hermes-partner /root" in sidecar
            and f"ReadWritePaths=/var/lib/health-sidecar /run/health-sidecar" in sidecar,
        }
        if not all(checks.values()):
            raise DeploymentError("static-deployment-verification-failed")
        return {"action": "verify-static", "result": "passed", "checks": checks}

    def verify_runtime(self) -> dict[str, Any]:
        self.verify_static()
        if not isinstance(self.host, SystemHost):
            raise DeploymentError("runtime-verification-requires-system-host")
        partner_ids = self.host.user_ids(PARTNER_USER)
        sidecar_ids = self.host.user_ids(SIDECAR_USER)
        client_gid = self.host.group_id(CLIENT_GROUP)
        socket_path = self.host_path(SOCKET_PATH)
        state_path = self.host_path(STATE_PATH)
        key_path = self.host_path(KEY_PATH)
        cache_path = state_path.parent / "source-cache"
        partner_config = self.host_path(f"{self.config.partner_home}/config.yaml")
        if (
            partner_ids is None
            or sidecar_ids is None
            or client_gid is None
            or not socket_path.exists()
            or not state_path.is_file()
            or not key_path.is_file()
            or not cache_path.is_dir()
            or not partner_config.is_file()
        ):
            raise DeploymentError("runtime-boundary-unavailable")
        socket_stat = socket_path.stat()
        partner_pid_text = self.host.service_property(PARTNER_UNIT, "MainPID")
        sidecar_pid_text = self.host.service_property(SIDECAR_UNIT, "MainPID")
        partner_pid = int(partner_pid_text) if partner_pid_text.isdigit() else 0
        sidecar_pid = int(sidecar_pid_text) if sidecar_pid_text.isdigit() else 0
        checks = {
            "partner_service_active": self.host.service_property(PARTNER_UNIT, "ActiveState")
            == "active",
            "sidecar_service_active": self.host.service_property(SIDECAR_UNIT, "ActiveState")
            == "active",
            "partner_process_user": partner_pid > 0
            and self.host.process_ids(partner_pid) == partner_ids,
            "sidecar_process_user": sidecar_pid > 0
            and self.host.process_ids(sidecar_pid) == sidecar_ids,
            "socket_owner": socket_stat.st_uid == sidecar_ids[0],
            "socket_group": socket_stat.st_gid == client_gid,
            "socket_mode": stat.S_IMODE(socket_stat.st_mode) == 0o660,
            "socket_type": stat.S_ISSOCK(socket_stat.st_mode),
            "socket_group_members": self.host.group_members(CLIENT_GROUP)
            == {PARTNER_USER, SIDECAR_USER},
            "partner_cannot_read_state": not self.host.can_read(PARTNER_USER, STATE_PATH),
            "partner_cannot_read_key": not self.host.can_read(PARTNER_USER, KEY_PATH),
            "partner_cannot_read_source_cache": not self.host.can_read(
                PARTNER_USER, "/var/lib/health-sidecar/state/source-cache"
            ),
            "partner_can_read_projection": self.host.can_read(
                PARTNER_USER, PROJECTION_PATH
            ),
            "sidecar_cannot_read_partner_profile": not self.host.can_read(
                SIDECAR_USER, f"{self.config.partner_home}/config.yaml"
            ),
            "exact_two_health_jobs": self.verify_fixed_jobs(),
            "partner_socket_round_trip": self.host.sidecar_ready(
                PARTNER_USER, SOCKET_PATH, self.config.hermes_python, timeout_seconds=3
            ),
        }
        checks["no_sidecar_tcp_listener"] = (
            sidecar_pid > 0
            and all(f"pid={sidecar_pid}," not in line for line in self.host.tcp_listener_lines())
        )
        if not all(checks.values()):
            raise DeploymentError("runtime-deployment-verification-failed")
        self._record_evidence("verify-runtime", "passed", checks)
        return {"action": "verify-runtime", "result": "passed", "checks": checks}

    def verify_fixed_jobs(self) -> bool:
        jobs_path = self.host_path(f"{self.config.partner_home}/cron/jobs.json")
        if not jobs_path.is_file():
            return False
        try:
            payload = json.loads(jobs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if isinstance(payload, dict):
            jobs = payload.get("jobs")
        elif isinstance(payload, list):
            jobs = payload
        else:
            return False
        if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
            return False
        from health_model import HealthModelConfig
        from hermes_jobs import fixed_job_specs, job_matches_spec

        try:
            health_model = HealthModelConfig.from_file(
                self.host_path(PARTNER_HEALTH_MODEL_CONFIG_PATH)
            )
        except Exception:
            return False
        specs = fixed_job_specs(health_model)
        managed_names = {spec.name for spec in specs}
        health_jobs = [
            job
            for job in jobs
            if isinstance(job.get("name"), str)
            and job["name"].lower().startswith(("health-", "health_"))
        ]
        if len(health_jobs) != 2 or {job["name"] for job in health_jobs} != managed_names:
            return False
        by_name = {job["name"]: job for job in health_jobs}
        return all(job_matches_spec(by_name[spec.name], spec) for spec in specs)

    def _stage_release(self) -> Path:
        releases = self.host_path("/opt/partner-health-steward/releases")
        releases.mkdir(parents=True, exist_ok=True)
        releases.chmod(0o755)
        target = releases / self.config.release_id
        if target.is_symlink():
            raise DeploymentError("release-symlink-refused")
        staging: Path | None = Path(
            tempfile.mkdtemp(prefix=f".{self.config.release_id}-", dir=releases)
        )
        try:
            for relative in _RELEASE_FILES:
                source = self.config.source_root.resolve() / relative
                self._reject_symlinks(source)
                assert staging is not None
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(
                        source,
                        destination,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
                    )
                else:
                    shutil.copy2(source, destination)
            assert staging is not None
            manifest = self._build_manifest(staging)
            self._atomic_write_text(
                staging / "MANIFEST.json",
                json.dumps(manifest, sort_keys=True, indent=2) + "\n",
                mode=0o644,
            )
            if target.exists():
                self._verify_release(target)
                existing = json.loads((target / "MANIFEST.json").read_text(encoding="utf-8"))
                if existing != manifest:
                    raise DeploymentError("release-id-content-mismatch")
                return target
            os.replace(staging, target)
            staging = None
            self._make_tree_read_only(target)
            self.host.set_owner(target, "root", "root", recursive=True)
            return target
        finally:
            if staging is not None and staging.exists():
                shutil.rmtree(staging)

    def _prepare_directories(self) -> None:
        directories = {
            "/etc/health-sidecar": 0o750,
            "/etc/partner-health-steward": 0o750,
            "/var/lib/health-sidecar": 0o710,
            "/var/lib/health-sidecar/state": 0o700,
            "/var/lib/health-sidecar/state/backups": 0o700,
            "/var/lib/health-sidecar/state/profile-keys": 0o700,
            "/var/lib/health-sidecar/state/source-cache": 0o700,
            "/var/lib/health-sidecar/projection": 0o2750,
            "/var/lib/hermes-partner": 0o700,
            "/var/lib/partner-health-steward": 0o700,
            "/var/lib/partner-health-steward/evidence": 0o700,
            "/run/health-sidecar": 0o750,
            "/etc/systemd/system": 0o755,
        }
        for path, mode in directories.items():
            target = self.host_path(path)
            target.mkdir(parents=True, exist_ok=True)
            target.chmod(mode)
        self.host.set_owner(
            self.host_path("/var/lib/health-sidecar"), SIDECAR_USER, CLIENT_GROUP
        )
        self.host.set_owner(
            self.host_path("/var/lib/health-sidecar/state"),
            SIDECAR_USER,
            SIDECAR_USER,
            recursive=True,
        )
        self.host.set_owner(
            self.host_path("/var/lib/health-sidecar/projection"),
            SIDECAR_USER,
            CLIENT_GROUP,
            recursive=True,
        )
        self.host.set_owner(
            self.host_path("/etc/health-sidecar"), SIDECAR_USER, SIDECAR_USER, recursive=True
        )
        self.host.set_owner(
            self.host_path("/etc/partner-health-steward"),
            PARTNER_USER,
            PARTNER_USER,
            recursive=True,
        )
        self.host.set_owner(
            self.host_path("/var/lib/hermes-partner"), PARTNER_USER, PARTNER_USER, recursive=True
        )
        self.host.set_owner(
            self.host_path("/run/health-sidecar"), SIDECAR_USER, CLIENT_GROUP, recursive=True
        )

    def _migrate_partner_profile(self) -> None:
        source = self.host_path(self.config.legacy_partner_home)
        target = self.host_path(self.config.partner_home)
        if target.exists():
            if not target.is_dir():
                raise DeploymentError("partner-profile-target-not-directory")
        else:
            if not source.is_dir():
                raise DeploymentError("partner-profile-source-unavailable")
            self._reject_symlinks(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target)
        self._reject_symlinks(target)
        target.chmod(0o700)
        self.host.set_owner(target, PARTNER_USER, PARTNER_USER, recursive=True)

    def _install_public_key(self) -> None:
        destination = self.host_path(PUBLIC_KEY_PATH)
        self._atomic_write_bytes(destination, self.config.receipt_public_key_source.read_bytes(), mode=0o400)
        self.host.set_owner(destination, SIDECAR_USER, SIDECAR_USER)

    def _install_production_runtime_inputs(self) -> None:
        """Copy explicit production inputs into their owning account's tree.

        The health-model recipient snapshot is non-secret and is copied to both
        accounts so the fixed Job can bind its native Hermes record to exactly
        the same model that the sidecar dispatch adapter uses.  Credentials and
        Weixin delivery data never enter the partner tree.
        """
        cfg = self.config
        copies = (
            (
                cfg.health_model_config_source,
                PARTNER_HEALTH_MODEL_CONFIG_PATH,
                PARTNER_USER,
                PARTNER_USER,
            ),
            (
                cfg.health_source_catalog_source,
                PARTNER_HEALTH_SOURCE_CATALOG_PATH,
                PARTNER_USER,
                PARTNER_USER,
            ),
            (
                cfg.health_model_config_source,
                SIDECAR_HEALTH_MODEL_CONFIG_PATH,
                SIDECAR_USER,
                SIDECAR_USER,
            ),
            (
                cfg.sidecar_source_metadata_source,
                SIDECAR_SOURCE_METADATA_PATH,
                SIDECAR_USER,
                SIDECAR_USER,
            ),
            (
                cfg.sidecar_health_model_api_key_source,
                SIDECAR_HEALTH_MODEL_API_KEY_PATH,
                SIDECAR_USER,
                SIDECAR_USER,
            ),
            (
                cfg.sidecar_weixin_token_source,
                SIDECAR_WEIXIN_TOKEN_PATH,
                SIDECAR_USER,
                SIDECAR_USER,
            ),
        )
        for source, destination, owner, group in copies:
            self._atomic_write_bytes(
                self.host_path(destination), Path(source).read_bytes(), mode=0o400
            )
            self.host.set_owner(self.host_path(destination), owner, group)

    def _write_projection_bridge(self) -> None:
        projection = self.host_path(PROJECTION_PATH)
        if not projection.exists():
            self._atomic_write_text(projection, "{}\n", mode=0o640)
        else:
            projection.chmod(0o640)
        self.host.set_owner(projection, SIDECAR_USER, CLIENT_GROUP)

    def _write_runtime_configuration(self, *, release_id: str, partner_uid: int, client_gid: int) -> None:
        release = f"/opt/partner-health-steward/releases/{release_id}"
        partner_env = {
            "HEALTH_STEWARD_ACCEPTED_HERMES_VERSION": (
                self.config.accepted_hermes_version
            ),
            "HEALTH_STEWARD_EXPECTED_OWNER_SENDER_ID": (
                self.config.expected_owner_sender_id
            ),
            "HEALTH_STEWARD_EXPECTED_VIEWER_SENDER_ID": (
                self.config.expected_viewer_sender_id
            ),
            "HEALTH_STEWARD_SOCKET": SOCKET_PATH,
            "HEALTH_STEWARD_MEMORY_PROJECTION_PATH": PROJECTION_PATH,
            "HEALTH_STEWARD_HEALTH_MODEL_CONFIG": PARTNER_HEALTH_MODEL_CONFIG_PATH,
            "HEALTH_STEWARD_HEALTH_SOURCE_CATALOG": (
                PARTNER_HEALTH_SOURCE_CATALOG_PATH
            ),
            "HEALTH_STEWARD_HERMES_SOURCE_ROOT": self.config.hermes_source_root,
            "HEALTH_STEWARD_RECEIPT_SIGNER_SOCKET": (
                self.config.receipt_signer_socket
            ),
            "HEALTH_STEWARD_SOURCE_ROOT": release,
            "HEALTH_STEWARD_DELIVERY_LEDGER_PATH": DELIVERY_LEDGER_PATH,
            "HEALTH_STEWARD_HEALTH_MODEL_ATTESTATION_PATH": (
                HEALTH_MODEL_ATTESTATION_PATH
            ),
            "HEALTH_STEWARD_JOB_AUTHORIZATION_SECRET": (
                PARTNER_JOB_AUTHORIZATION_SECRET_PATH
            ),
            "HEALTH_STEWARD_EXPORT_TMPDIR": EXPORT_TMPDIR,
            "HEALTH_STEWARD_SUBJECT": self.config.subject,
            "HEALTH_STEWARD_TIMEZONE": self.config.timezone,
            # Hermes evaluates native Cron expressions in this configured IANA
            # zone.  Keep it equal to the owner zone so `0 4 * * *` means the
            # required owner-local 04:00 rather than host-local 04:00.
            "HERMES_TIMEZONE": self.config.timezone,
            "HERMES_HOME": self.config.partner_home,
            "WEIXIN_ALLOWED_USERS": (
                f"{self.config.expected_owner_sender_id},"
                f"{self.config.expected_viewer_sender_id}"
            ),
            "WEIXIN_DM_POLICY": "allowlist",
            "PATH": (
                f"{Path(self.config.hermes_python).parent.as_posix()}:"
                "/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin"
            ),
            "PYTHONPATH": release,
            "VIRTUAL_ENV": Path(self.config.hermes_python).parent.parent.as_posix(),
        }
        sidecar_env = {
            "HEALTH_SIDECAR_ACCEPTED_HERMES_VERSION": (
                self.config.accepted_hermes_version
            ),
            "HEALTH_SIDECAR_ALLOWED_GIDS": str(client_gid),
            "HEALTH_SIDECAR_ALLOWED_UIDS": str(partner_uid),
            "HEALTH_SIDECAR_APPROVED_GUIDELINE_HOSTS": ",".join(
                self.config.approved_guideline_hosts
            ),
            "HEALTH_SIDECAR_EXPECTED_OWNER_SENDER_ID": (
                self.config.expected_owner_sender_id
            ),
            "HEALTH_SIDECAR_EXPECTED_VIEWER_SENDER_ID": (
                self.config.expected_viewer_sender_id
            ),
            "HEALTH_SIDECAR_DELIVERY_LEDGER_PATH": SIDECAR_DELIVERY_LEDGER_PATH,
            "HEALTH_SIDECAR_HEALTH_MODEL_API_KEY_PATH": (
                SIDECAR_HEALTH_MODEL_API_KEY_PATH
            ),
            "HEALTH_SIDECAR_HEALTH_MODEL_CONFIG": (
                SIDECAR_HEALTH_MODEL_CONFIG_PATH
            ),
            "HEALTH_SIDECAR_HERMES_SOURCE_ROOT": self.config.hermes_source_root,
            "HEALTH_SIDECAR_KEY_PATH": KEY_PATH,
            "HEALTH_SIDECAR_JOB_AUTHORIZATION_SECRET_PATH": (
                SIDECAR_JOB_AUTHORIZATION_SECRET_PATH
            ),
            "HEALTH_SIDECAR_MEMORY_PROJECTION_PATH": PROJECTION_PATH,
            "HEALTH_SIDECAR_RECEIPT_PUBLIC_KEY_PATH": PUBLIC_KEY_PATH,
            "HEALTH_SIDECAR_SOCKET": SOCKET_PATH,
            "HEALTH_SIDECAR_SUBJECT": self.config.subject,
            "HEALTH_SIDECAR_SOCKET_GID": str(client_gid),
            "HEALTH_SIDECAR_SOCKET_MODE": "660",
            "HEALTH_SIDECAR_SOURCE_METADATA": SIDECAR_SOURCE_METADATA_PATH,
            "HEALTH_SIDECAR_STATE_PATH": STATE_PATH,
            "HEALTH_SIDECAR_WEIXIN_BASE_URL": self.config.weixin_base_url,
            "HEALTH_SIDECAR_WEIXIN_CDN_BASE_URL": self.config.weixin_cdn_base_url,
            "HEALTH_SIDECAR_WEIXIN_TOKEN_PATH": SIDECAR_WEIXIN_TOKEN_PATH,
            "PYTHONPATH": release,
        }
        self._write_env_file(
            self.host_path("/etc/partner-health-steward/partner.env"), partner_env
        )
        self._write_env_file(
            self.host_path("/etc/health-sidecar/health-sidecar.env"), sidecar_env
        )

    def _write_units(self) -> None:
        sidecar_unit = f"""[Unit]
Description=Partner health sidecar
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={SIDECAR_USER}
Group={SIDECAR_USER}
EnvironmentFile=/etc/health-sidecar/health-sidecar.env
WorkingDirectory=/var/lib/health-sidecar
RuntimeDirectory=health-sidecar
RuntimeDirectoryMode=0750
ExecStartPre=/bin/chgrp health-sidecar-client /run/health-sidecar
ExecStart={self.config.sidecar_python} -m sidecar.server
Restart=on-failure
RestartSec=5s
UMask=0007
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadOnlyPaths=/opt/partner-health-steward /etc/health-sidecar
ReadWritePaths=/var/lib/health-sidecar /run/health-sidecar
InaccessiblePaths=/var/lib/hermes-partner /root

[Install]
WantedBy=multi-user.target
"""
        partner_unit = f"""[Unit]
Description=Restricted partner Hermes gateway for health steward
Requires={SIDECAR_UNIT}
After=network-online.target {SIDECAR_UNIT}
Wants=network-online.target

[Service]
Type=simple
User={PARTNER_USER}
Group={PARTNER_USER}
SupplementaryGroups={CLIENT_GROUP}
EnvironmentFile=/etc/partner-health-steward/partner.env
WorkingDirectory=/var/lib/hermes-partner
RuntimeDirectory=partner-health-steward-export
RuntimeDirectoryMode=0700
ExecStart={' '.join(self._partner_exec_tokens())}
ExecReload=/bin/kill -USR1 $MAINPID
ExecStopPost=-{self.config.hermes_python} -m gateway.cgroup_cleanup
Restart=always
RestartSec=5s
RestartForceExitStatus=75
RestartPreventExitStatus=78
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=60
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadOnlyPaths=/opt/partner-health-steward /var/lib/health-sidecar/projection
ReadWritePaths=/var/lib/hermes-partner /run/partner-health-steward-export
InaccessiblePaths=/var/lib/health-sidecar/state /etc/health-sidecar

[Install]
WantedBy=multi-user.target
"""
        export_cleanup_unit = f"""[Unit]
Description=Private partner health-export orphan cleanup
After={PARTNER_UNIT}
ConditionPathIsDirectory={EXPORT_TMPDIR}

[Service]
Type=oneshot
User={PARTNER_USER}
Group={PARTNER_USER}
EnvironmentFile=/etc/partner-health-steward/partner.env
WorkingDirectory=/var/lib/hermes-partner
ExecStart={self.config.hermes_python} -m export_attachments --cleanup --directory ${{HEALTH_STEWARD_EXPORT_TMPDIR}}
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadOnlyPaths=/opt/partner-health-steward
ReadWritePaths={EXPORT_TMPDIR}
InaccessiblePaths=/var/lib/health-sidecar/state /etc/health-sidecar
"""
        export_cleanup_timer = f"""[Unit]
Description=Hourly private partner health-export orphan cleanup

[Timer]
OnCalendar=hourly
AccuracySec=1min
Persistent=true
Unit={EXPORT_CLEANUP_UNIT}

[Install]
WantedBy=timers.target
"""
        self._atomic_write_text(
            self.host_path("/etc/systemd/system/health-sidecar.service"),
            sidecar_unit,
            mode=0o644,
        )
        self._atomic_write_text(
            self.host_path(EXPORT_TMPFILES_PATH),
            "# Fallback cleanup; the enabled hourly cleanup timer enforces the bound.\n"
            "D /run/partner-health-steward-export 0700 hermes-partner hermes-partner 1d\n",
            mode=0o644,
        )
        self._atomic_write_text(
            self.host_path(
                "/etc/systemd/system/hermes-gateway-partner-health-steward.service"
            ),
            partner_unit,
            mode=0o644,
        )
        self._atomic_write_text(
            self.host_path(f"/etc/systemd/system/{EXPORT_CLEANUP_UNIT}"),
            export_cleanup_unit,
            mode=0o644,
        )
        self._atomic_write_text(
            self.host_path(f"/etc/systemd/system/{EXPORT_CLEANUP_TIMER}"),
            export_cleanup_timer,
            mode=0o644,
        )

    def _activate_release(
        self,
        release_id: str,
        release: Path,
        partner_uid: int,
        client_gid: int,
    ) -> None:
        self._write_runtime_configuration(
            release_id=release_id,
            partner_uid=partner_uid,
            client_gid=client_gid,
        )
        self._install_partner_assets(release)

    def _recover_runtime_release(
        self,
        release_id: str,
        release: Path,
        partner_uid: int,
        client_gid: int,
        *,
        sidecar_was_active: bool,
        partner_was_active: bool,
        export_timer_was_active: bool,
    ) -> None:
        self._activate_release(release_id, release, partner_uid, client_gid)
        self.host.daemon_reload()
        if sidecar_was_active:
            self.host.service("restart", SIDECAR_UNIT)
            if not self.host.sidecar_ready(
                PARTNER_USER,
                SOCKET_PATH,
                self.config.hermes_python,
                timeout_seconds=10,
            ):
                raise DeploymentError("runtime-recovery-sidecar-not-ready")
        if partner_was_active:
            self.host.service("start", PARTNER_UNIT)
        if self._release_supports_export_cleanup(release) and export_timer_was_active:
            self._start_export_cleanup_timer(release)
        else:
            self._stop_export_cleanup_timer()

    @staticmethod
    def _release_supports_export_cleanup(release: Path) -> bool:
        """Whether this release contains the timer's import target."""
        return (release / "export_attachments.py").is_file()

    def _start_export_cleanup_timer(self, release: Path) -> None:
        if not self._release_supports_export_cleanup(release):
            self._stop_export_cleanup_timer()
            return
        self.host.service("enable", EXPORT_CLEANUP_TIMER)
        self.host.service("start", EXPORT_CLEANUP_TIMER)

    def _stop_export_cleanup_timer(self) -> None:
        timer_unit = self.host_path(f"/etc/systemd/system/{EXPORT_CLEANUP_TIMER}")
        if not timer_unit.exists():
            return
        self.host.service("stop", EXPORT_CLEANUP_TIMER)
        self.host.service("disable", EXPORT_CLEANUP_TIMER)

    def _install_partner_assets(self, release: Path) -> None:
        partner_secret = self.host_path(PARTNER_JOB_AUTHORIZATION_SECRET_PATH)
        if not partner_secret.exists():
            self._atomic_write_bytes(partner_secret, os.urandom(32), mode=0o400)
            self.host.set_owner(partner_secret, PARTNER_USER, PARTNER_USER)
        env = {
            "HEALTH_STEWARD_HEALTH_MODEL_CONFIG": (
                PARTNER_HEALTH_MODEL_CONFIG_PATH
            ),
            "HEALTH_STEWARD_SOURCE_ROOT": self._virtual_path(release),
            "HERMES_HOME": self.config.partner_home,
            "PYTHONPATH": self._virtual_path(release),
        }
        installer = f"{self._virtual_path(release)}/scripts/install_health_steward_jobs.py"
        self.host.run_as(PARTNER_USER, [self.config.hermes_python, installer], env)
        if not partner_secret.is_file():
            raise DeploymentError("job-authorization-secret-unavailable")
        secret = partner_secret.read_bytes()
        if len(secret) < 32:
            raise DeploymentError("job-authorization-secret-invalid")
        sidecar_secret = self.host_path(SIDECAR_JOB_AUTHORIZATION_SECRET_PATH)
        if sidecar_secret.exists() and sidecar_secret.read_bytes() != secret:
            raise DeploymentError("job-authorization-secret-mismatch")
        self._atomic_write_bytes(sidecar_secret, secret, mode=0o400)
        self.host.set_owner(sidecar_secret, SIDECAR_USER, SIDECAR_USER)
        plugin_actions = [("enable", "health-steward")]
        partner_plugins = self.host_path(f"{self.config.partner_home}/plugins")
        for legacy_plugin in ("health-guard", "health-autonomy"):
            if (partner_plugins / legacy_plugin).is_dir():
                plugin_actions.append(("disable", legacy_plugin))
        for action, plugin in plugin_actions:
            argv = [
                self.config.hermes_python,
                "-m",
                "hermes_cli.main",
                "plugins",
                action,
                plugin,
            ]
            if action == "enable":
                argv.append("--no-allow-tool-override")
            self.host.run_as(PARTNER_USER, argv, env)

    def _read_deployment_state(self) -> dict[str, Any]:
        path = self.host_path(STATE_RECORD_PATH)
        if path.is_symlink():
            raise DeploymentError("deployment-state-symlink-refused")
        if not path.exists():
            return {
                "current_release": None,
                "previous_release": None,
                "rollback_completed_from": None,
            }
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeploymentError("invalid-deployment-state") from exc
        if set(state) == {"current_release", "previous_release"}:
            state["rollback_completed_from"] = None
        if set(state) != {
            "current_release",
            "previous_release",
            "rollback_completed_from",
        }:
            raise DeploymentError("invalid-deployment-state")
        for value in state.values():
            if value is not None and (not isinstance(value, str) or not _RELEASE_ID.fullmatch(value)):
                raise DeploymentError("invalid-deployment-state")
        return state

    def _write_deployment_state(self, state: dict[str, Any]) -> None:
        self._atomic_write_text(
            self.host_path(STATE_RECORD_PATH),
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
            mode=0o600,
        )

    def _require_installed_state(self) -> dict[str, Any]:
        state = self._read_deployment_state()
        current = state.get("current_release")
        if not isinstance(current, str) or not _RELEASE_ID.fullmatch(current):
            raise DeploymentError("deployment-not-installed")
        return state

    def _record_evidence(self, action: str, result: str, checks: dict[str, bool]) -> None:
        if not _SAFE_TOKEN.fullmatch(action) or not _SAFE_TOKEN.fullmatch(result):
            raise DeploymentError("unsafe-evidence-token")
        if not checks or any(
            not _SAFE_TOKEN.fullmatch(key) or not isinstance(value, bool)
            for key, value in checks.items()
        ):
            raise DeploymentError("unsafe-evidence-checks")
        now = dt.datetime.now(dt.timezone.utc)
        current_release = self._require_installed_state()["current_release"]
        record = {
            "action": action,
            "result": result,
            "release_id": current_release,
            "recorded_utc": now.isoformat(),
            "checks": checks,
        }
        name = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{action}.json"
        self._atomic_write_text(
            self.host_path(f"/var/lib/partner-health-steward/evidence/{name}"),
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
            mode=0o600,
        )

    def _write_env_file(self, path: Path, values: dict[str, str]) -> None:
        lines: list[str] = []
        for key, value in sorted(values.items()):
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                raise DeploymentError("invalid-environment-key")
            if any(char in value for char in "\x00\r\n\"'") or any(char.isspace() for char in value):
                raise DeploymentError(f"unsafe-environment-value:{key}")
            lines.append(f"{key}={value}")
        self._atomic_write_text(path, "\n".join(lines) + "\n", mode=0o640)

    def _build_manifest(self, release: Path) -> dict[str, Any]:
        files: dict[str, str] = {}
        for path in sorted(item for item in release.rglob("*") if item.is_file()):
            relative = path.relative_to(release).as_posix()
            if relative == "MANIFEST.json":
                continue
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"schema_version": 1, "files": files}

    def _verify_release(self, release: Path) -> None:
        manifest_path = release / "MANIFEST.json"
        if not manifest_path.is_file():
            raise DeploymentError("release-manifest-unavailable")
        try:
            expected = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DeploymentError("invalid-release-manifest") from exc
        if expected != self._build_manifest(release):
            raise DeploymentError("release-manifest-mismatch")
        forbidden = (".research/", "plugin/health-guard/", "plugin/health-autonomy/")
        if any(path.startswith(forbidden) for path in expected.get("files", {})):
            raise DeploymentError("forbidden-release-asset")

    @staticmethod
    def _reject_symlinks(path: Path) -> None:
        if path.is_symlink():
            raise DeploymentError(f"release-symlink-refused:{path.name}")
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_symlink():
                    raise DeploymentError(f"release-symlink-refused:{child.name}")

    @staticmethod
    def _make_tree_read_only(path: Path) -> None:
        for child in path.rglob("*"):
            child.chmod(0o555 if child.is_dir() else 0o444)
        path.chmod(0o555)

    @staticmethod
    def _require_partner_profile(path: str) -> None:
        normalized = path.rstrip("/")
        if not normalized.endswith("/profiles/partner") or not normalized.startswith("/"):
            raise DeploymentError(f"deployment-requires-partner-profile:{path}")

    def _virtual_path(self, host_path: Path) -> str:
        try:
            relative = host_path.resolve().relative_to(self.root)
        except ValueError as exc:
            raise DeploymentError("path-outside-deployment-root") from exc
        return "/" + relative.as_posix()

    def _partner_exec_tokens(self) -> tuple[str, ...]:
        try:
            tokens = tuple(shlex.split(self.config.partner_exec_start, posix=True))
        except ValueError as exc:
            raise DeploymentError("invalid-partner-exec-start") from exc
        if not tokens or not tokens[0].startswith("/"):
            raise DeploymentError("absolute-partner-exec-start-required")
        if any(
            not re.fullmatch(r"[A-Za-z0-9_./:=,@+-]+", token)
            for token in tokens
        ):
            raise DeploymentError("unsafe-partner-exec-start-token")
        return tokens

    def _require_mutation_authority(self) -> None:
        if not isinstance(self.host, SystemHost):
            return
        if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0:
            raise DeploymentError("root-linux-required-for-deployment-mutation")
        if self.root != Path("/").resolve():
            raise DeploymentError("system-host-requires-root-filesystem")

    @staticmethod
    def _atomic_write_text(path: Path, text: str, *, mode: int) -> None:
        DeploymentManager._atomic_write_bytes(path, text.encode("utf-8"), mode=mode)

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes, *, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temp = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temp.chmod(0o600)
            if path.exists():
                path.chmod(0o600)
            os.replace(temp, path)
            path.chmod(mode)
        finally:
            if temp.exists():
                temp.chmod(0o600)
                temp.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="deploy the isolated partner health steward")
    parser.add_argument(
        "action",
        choices=("preflight", "install", "start", "stop", "upgrade", "rollback", "restore", "verify-static", "verify-runtime"),
    )
    parser.add_argument("--root", default="/")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--receipt-public-key", required=True)
    parser.add_argument("--sidecar-python", required=True)
    parser.add_argument("--hermes-python", required=True)
    parser.add_argument("--partner-exec-start", required=True)
    parser.add_argument("--expected-owner-sender-id", required=True)
    parser.add_argument("--expected-viewer-sender-id", required=True)
    parser.add_argument("--health-model-config", required=True)
    parser.add_argument("--health-source-catalog", required=True)
    parser.add_argument("--sidecar-source-metadata", required=True)
    parser.add_argument("--sidecar-health-model-api-key", required=True)
    parser.add_argument("--sidecar-weixin-token", required=True)
    parser.add_argument("--receipt-signer-socket", required=True)
    parser.add_argument("--hermes-source-root", required=True)
    parser.add_argument("--accepted-hermes-version", required=True)
    parser.add_argument("--weixin-base-url", required=True)
    parser.add_argument("--weixin-cdn-base-url", required=True)
    parser.add_argument("--legacy-partner-home", default=LEGACY_PARTNER_HOME)
    parser.add_argument("--partner-home", default=PARTNER_HOME)
    parser.add_argument("--subject", default="profile")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--approved-guideline-host", action="append", default=[])
    parser.add_argument("--backup-name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = DeploymentConfig(
        root=Path(args.root),
        source_root=Path(args.source_root),
        release_id=args.release_id,
        receipt_public_key_source=Path(args.receipt_public_key),
        sidecar_python=args.sidecar_python,
        hermes_python=args.hermes_python,
        partner_exec_start=args.partner_exec_start,
        expected_owner_sender_id=args.expected_owner_sender_id,
        expected_viewer_sender_id=args.expected_viewer_sender_id,
        health_model_config_source=Path(args.health_model_config),
        health_source_catalog_source=Path(args.health_source_catalog),
        sidecar_source_metadata_source=Path(args.sidecar_source_metadata),
        sidecar_health_model_api_key_source=Path(
            args.sidecar_health_model_api_key
        ),
        sidecar_weixin_token_source=Path(args.sidecar_weixin_token),
        receipt_signer_socket=args.receipt_signer_socket,
        hermes_source_root=args.hermes_source_root,
        accepted_hermes_version=args.accepted_hermes_version,
        weixin_base_url=args.weixin_base_url,
        weixin_cdn_base_url=args.weixin_cdn_base_url,
        legacy_partner_home=args.legacy_partner_home,
        partner_home=args.partner_home,
        subject=args.subject,
        timezone=args.timezone,
        approved_guideline_hosts=tuple(args.approved_guideline_host),
    )
    manager = DeploymentManager(config)
    methods = {
        "preflight": manager.preflight,
        "install": manager.install,
        "start": manager.start,
        "stop": manager.stop,
        "upgrade": manager.upgrade,
        "rollback": manager.rollback,
        "verify-static": manager.verify_static,
        "verify-runtime": manager.verify_runtime,
    }
    if args.action == "restore":
        if not args.backup_name:
            raise DeploymentError("backup-name-required")
        result = manager.restore_backup(args.backup_name)
    else:
        result = methods[args.action]()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Explicit operator action: install/verify the two fixed partner Jobs."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


def _make_private_tree(path: Path) -> None:
    for child in path.rglob("*"):
        child.chmod(0o700 if child.is_dir() else 0o600)
    path.chmod(0o700)


def _remove_managed_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in path.rglob("*"):
        try:
            child.chmod(0o700 if child.is_dir() else 0o600)
        except OSError:
            pass
    path.chmod(0o700)
    shutil.rmtree(path)


def _replace_plugin_tree(source: Path, target: Path) -> None:
    """Atomically replace the managed plugin even when release files are 0444."""
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    backup = target.parent / f".{target.name}.previous"
    try:
        shutil.rmtree(temporary)
        shutil.copytree(source, temporary)
        _make_private_tree(temporary)
        if backup.exists():
            _remove_managed_tree(backup)
        if target.exists():
            os.replace(target, backup)
        os.replace(temporary, target)
        if backup.exists():
            _remove_managed_tree(backup)
    except Exception:
        if not target.exists() and backup.exists():
            os.replace(backup, target)
        raise
    finally:
        if temporary.exists():
            _remove_managed_tree(temporary)


def _replace_script(source: Path, target: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(0o600)
        if target.exists():
            target.chmod(0o600)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def install_assets(source_root: Path, hermes_home: Path) -> list[Path]:
    """Install only partner-owned plugin/scripts into one Hermes profile."""
    source_root = source_root.expanduser().resolve()
    hermes_home = hermes_home.expanduser().resolve()
    plugin_source = source_root / "plugin" / "health-steward"
    if not plugin_source.is_dir():
        raise RuntimeError(f"health-plugin-unavailable:{plugin_source}")
    plugin_target = hermes_home / "plugins" / "health-steward"
    plugin_target.parent.mkdir(parents=True, exist_ok=True)
    _replace_plugin_tree(plugin_source, plugin_target)

    scripts_target = hermes_home / "scripts"
    scripts_target.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    for name in (
        "health_steward_snapshot.py",
        "health_steward_daily_snapshot.py",
        "health_steward_dispatch_snapshot.py",
        "install_health_steward_jobs.py",
    ):
        source = source_root / "scripts" / name
        if not source.is_file():
            raise RuntimeError(f"health-script-unavailable:{source}")
        target = scripts_target / name
        _replace_script(source, target)
        installed.append(target)
    installed.append(plugin_target)
    return installed


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home()).expanduser().resolve()
    except Exception:
        return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser().resolve()


def _require_partner_home(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.name != "partner" or path.parent.name != "profiles":
        raise RuntimeError(f"health-installer-requires-partner-profile:{path}")
    return path


def main() -> int:
    source_root = os.environ.get("HEALTH_STEWARD_SOURCE_ROOT", "").strip()
    source_path = Path(source_root).expanduser().resolve() if source_root else Path(__file__).resolve().parents[1]
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))
    hermes_home = _require_partner_home(_hermes_home())
    installed = install_assets(source_path, hermes_home)
    from hermes_jobs import (
        ensure_capability_secret,
        ensure_job_action_authorization_secret,
        install_fixed_jobs,
    )

    capability_secret = ensure_capability_secret(
        hermes_home / "private" / "health-steward-capability.key"
    )
    job_authorization_secret = ensure_job_action_authorization_secret(
        hermes_home / "private" / "health-steward-job-authorization.key"
    )
    jobs = install_fixed_jobs()
    print("installed health-steward assets: " + ", ".join(str(path) for path in installed))
    print("installed fixed-job capability key: " + str(capability_secret))
    print("installed sidecar Job authorization key: " + str(job_authorization_secret))
    print("installed fixed health jobs: " + ", ".join(str(job.get("name")) for job in jobs))
    print("enable plugin 'health-steward' in the partner profile's plugins.enabled list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

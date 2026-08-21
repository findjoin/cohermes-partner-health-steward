"""Fixed no-agent dispatcher for the partner health-autonomy plugin."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _load_autonomy_module():
    hermes_home = Path(os.environ.get("HERMES_HOME", "/root/.hermes/profiles/partner"))
    module_path = hermes_home / "plugins" / "health-autonomy" / "autonomy.py"
    if not module_path.is_file():
        raise RuntimeError("health-autonomy core is missing")
    spec = importlib.util.spec_from_file_location(
        "health_autonomy_dispatch_core", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("health-autonomy core cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _admin_audit(event: str, error: BaseException | None = None) -> None:
    """Emit a metadata-only operator event without writing to chat stdout.

    The scheduler captures stderr, so ordinary logging is not a durable
    operator channel for a successful no-agent run.  On Unix, syslog reaches
    the service journal.  Never include exception text: it can contain private
    paths or health-state fragments.
    """
    try:
        import syslog

        suffix = f" error_type={type(error).__name__}" if error else ""
        syslog.openlog(ident="hermes-health-autonomy")
        syslog.syslog(
            syslog.LOG_ERR if error else syslog.LOG_WARNING,
            f"dispatcher_event={event}{suffix}",
        )
    except Exception:
        # Chat silence is the safety property.  An unavailable local syslog
        # must not turn a quarantined tick into a user-visible cron failure.
        pass


def _run_verified_dispatch() -> int:
    module = _load_autonomy_module()
    store = module.HealthAutonomyStore()
    managed_job_id, subject_key, route_fingerprint = store.dispatcher_binding()
    current_job_id = str(os.environ.get("HERMES_CRON_JOB_ID") or "").strip()
    current_job_fingerprint = str(
        os.environ.get("HERMES_CRON_JOB_FINGERPRINT") or ""
    ).strip()
    try:
        verified = bool(route_fingerprint) and module.HermesCronBridge().verify_runtime_dispatcher(
            current_job_id,
            current_job_fingerprint,
            managed_job_id,
            subject_key,
            store.dispatcher_route_matches,
        )
    except Exception:
        verified = False
    if not verified:
        try:
            store.quarantine_dispatcher(expected_subject_key=subject_key)
        except Exception as exc:
            _admin_audit("quarantine_failed", exc)
        try:
            store.housekeep()
        except Exception as exc:
            _admin_audit("housekeeping_failed", exc)
        _admin_audit("runtime_fingerprint_rejected")
        # no_agent non-zero exits are converted by Hermes into a watchdog
        # message delivered to job.origin.  A quarantine must therefore be a
        # successful, empty-stdout tick, not an ordinary script failure.
        return 0
    output = store.dispatch_due()
    if output:
        print(output)
    return 0


def main() -> int:
    """Fail closed and silently for every internal dispatcher failure."""
    try:
        return _run_verified_dispatch()
    except Exception as exc:
        _admin_audit("internal_failure", exc)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

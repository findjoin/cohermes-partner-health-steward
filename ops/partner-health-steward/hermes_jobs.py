"""The partner Hermes integration contract for the health sidecar.

This module deliberately contains no Hermes-core patch and no sidecar storage
access.  It describes the two jobs that are installed by an operator and the
small runtime used by those jobs.  Derived health tasks are never represented
in this module as native Cron records.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from job_authorization import (
    ensure_job_authorization_secret,
    issue_job_action_authorization,
    read_job_authorization_secret,
)


DAILY_JOB_NAME = "health-daily-profile-review"
DISPATCH_JOB_NAME = "health-due-task-dispatch"
DAILY_ROLE = "daily_profile_review"
DISPATCH_ROLE = "due_task_dispatch"
DAILY_SCHEDULE = "0 4 * * *"
DISPATCH_SCHEDULE = "every 5m"
DAILY_SCRIPT = "health_steward_daily_snapshot.py"
DISPATCH_SCRIPT = "health_steward_dispatch_snapshot.py"
DAILY_TOOLSET = "health_steward_daily"
DISPATCH_TOOLSET = "health_steward_dispatch"
NO_MCP_TOOLSET = "no_mcp"
CAPABILITY_TTL_SECONDS = 600
_CAPABILITY_NONCE = re.compile(r"^[0-9a-f]{32}$")

DAILY_PROMPT = (
    "You are the fixed health daily-review Job. The supplied capability is opaque; "
    "do not infer, request, or construct health content from it. Copy it into one "
    "health_daily_review tool call. The production plugin obtains the current "
    "sidecar snapshot and performs the fresh pinned health-model plan itself. "
    "Do not send a message, write files, access health storage, or manage Cron. "
    "Call the tool once, then answer exactly [SILENT]."
)
DISPATCH_PROMPT = (
    "You are the fixed health due-task dispatcher Job. Use only the supplied "
    "controlled sidecar snapshot and copy its capability into one call to "
    "health_dispatch_due_tasks. The "
    "sidecar alone decides whether to render or send a due task. Do not modify "
    "profiles, source cards, tasks, files, or Cron, and answer exactly [SILENT]."
)


class FixedJobConfigurationError(RuntimeError):
    """Raised when a managed Job is missing, duplicated, or drifted."""


@dataclass(frozen=True)
class FixedJobSpec:
    role: str
    name: str
    schedule: str
    script: str
    prompt: str
    description: str
    fresh_session: bool = True
    no_agent: bool = False
    attach_to_session: bool = False
    # ``no_mcp`` is Hermes' explicit sentinel for an empty MCP allowlist.
    # Without it the scheduler unions every globally enabled MCP server into
    # the per-job toolset, defeating the fixed-job boundary.
    enabled_toolsets: tuple[str, ...] = (DAILY_TOOLSET, NO_MCP_TOOLSET)
    # These are deliberately part of the persisted Cron record rather than
    # inferred from the partner's ordinary chat configuration.  They are set
    # only when the operator loads the dedicated health-model snapshot.
    model_provider: str | None = None
    model_id: str | None = None
    model_base_url: str | None = None

    def to_job_record(self, job_id: str) -> dict[str, Any]:
        """Return the canonical fields we expect from Hermes ``create_job``."""
        record = {
            "id": str(job_id),
            "name": self.name,
            "prompt": self.prompt,
            "schedule": self.schedule,
            "repeat": None,
            "deliver": "local",
            "origin": None,
            "script": self.script,
            "no_agent": self.no_agent,
            "attach_to_session": self.attach_to_session,
            "enabled_toolsets": list(self.enabled_toolsets),
            "skills": [],
            "context_from": None,
            "description": self.description,
        }
        model_binding = (
            self.model_provider,
            self.model_id,
            self.model_base_url,
        )
        if any(model_binding):
            if not all(model_binding):
                raise FixedJobConfigurationError("health-model-binding-invalid")
            record.update(
                {
                    "provider": self.model_provider,
                    "model": self.model_id,
                    "base_url": self.model_base_url,
                }
            )
        return record


_SPECS = (
    FixedJobSpec(
        DAILY_ROLE,
        DAILY_JOB_NAME,
        DAILY_SCHEDULE,
        DAILY_SCRIPT,
        DAILY_PROMPT,
        "Fixed 04:00 owner-time daily health review",
    ),
    FixedJobSpec(
        DISPATCH_ROLE,
        DISPATCH_JOB_NAME,
        DISPATCH_SCHEDULE,
        DISPATCH_SCRIPT,
        DISPATCH_PROMPT,
        "Fixed five-minute health due-task dispatcher",
        enabled_toolsets=(DISPATCH_TOOLSET, NO_MCP_TOOLSET),
    ),
)
_SPECS_BY_ROLE = {spec.role: spec for spec in _SPECS}
_SPECS_BY_NAME = {spec.name: spec for spec in _SPECS}
_SPECS_BY_SCRIPT = {spec.script: spec for spec in _SPECS}


def fixed_job_specs(health_model_config: Any | None = None) -> tuple[FixedJobSpec, ...]:
    """Return the immutable two-job contract, optionally model-bound.

    The unbound shape is retained for pure contract tests.  Installation and
    scheduler-backed execution always load the dedicated configuration and
    therefore receive records with explicit provider/model/base-url fields.
    """
    if health_model_config is None:
        return _SPECS
    provider = str(getattr(health_model_config, "provider", "") or "").strip()
    model_id = str(getattr(health_model_config, "model_id", "") or "").strip()
    endpoint = str(getattr(health_model_config, "endpoint", "") or "").strip()
    if not all((provider, model_id, endpoint)):
        raise FixedJobConfigurationError("health-model-binding-invalid")
    return tuple(
        replace(
            spec,
            model_provider=provider,
            model_id=model_id,
            model_base_url=endpoint,
        )
        for spec in _SPECS
    )


def _schedule_matches(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value.strip() == expected
    if not isinstance(value, Mapping):
        return False
    if expected == DISPATCH_SCHEDULE:
        return value.get("kind") == "interval" and int(value.get("minutes", 0)) == 5
    return value.get("kind") == "cron" and str(value.get("expr", "")).strip() == DAILY_SCHEDULE


def job_matches_spec(job: Mapping[str, Any], spec: FixedJobSpec) -> bool:
    """Check the non-bookkeeping fields that make a Job managed and safe."""
    if not isinstance(job, Mapping):
        return False
    repeat = job.get("repeat")
    repeat_ok = repeat is None or (
        isinstance(repeat, Mapping) and repeat.get("times") is None
    )
    toolsets = job.get("enabled_toolsets")
    if isinstance(toolsets, str):
        toolsets = [toolsets]
    if "enabled" in job and job.get("enabled") is not True:
        return False
    if "state" in job and job.get("state") in {"paused", "disabled"}:
        return False
    model_binding = (
        spec.model_provider,
        spec.model_id,
        spec.model_base_url,
    )
    if any(model_binding):
        model_matches = bool(
            all(model_binding)
            and job.get("provider") == spec.model_provider
            and job.get("model") == spec.model_id
            and job.get("base_url") == spec.model_base_url
        )
    else:
        model_matches = not job.get("model") and not job.get("provider") and not job.get("base_url")
    return bool(
        job.get("name") == spec.name
        and job.get("prompt") == spec.prompt
        and _schedule_matches(job.get("schedule"), spec.schedule)
        and job.get("script") == spec.script
        and job.get("no_agent") is spec.no_agent
        and job.get("attach_to_session") is spec.attach_to_session
        and job.get("deliver") == "local"
        and not job.get("origin")
        and repeat_ok
        and tuple(toolsets or ()) == spec.enabled_toolsets
        and not job.get("skills")
        and not job.get("skill")
        and not job.get("context_from")
        and not job.get("workdir")
        and model_matches
    )


def _backend_default() -> Any:
    from cron import jobs as cron_jobs

    return cron_jobs


def _load_fixed_health_model_config(
    path: str | os.PathLike[str] | None = None,
) -> Any:
    raw_path = str(
        path or os.environ.get("HEALTH_STEWARD_HEALTH_MODEL_CONFIG", "")
    ).strip()
    if not raw_path:
        raise FixedJobConfigurationError("health-model-config-required")
    try:
        from health_model import HealthModelConfig

        return HealthModelConfig.from_file(raw_path)
    except Exception as exc:
        raise FixedJobConfigurationError("health-model-config-unavailable") from exc


def install_fixed_jobs(
    backend: Any | None = None,
    *,
    health_model_config: Any | None = None,
) -> list[dict[str, Any]]:
    """Idempotently install the two fixed Jobs through Hermes' public CRUD API.

    This function is an operator/deployment action.  It is not called from a
    Job or from plugin registration, and it never updates or removes an
    unrelated Cron record.
    """
    health_model_config = health_model_config or _load_fixed_health_model_config()
    specs = fixed_job_specs(health_model_config)
    specs_by_name = {spec.name: spec for spec in specs}
    specs_by_script = {spec.script: spec for spec in specs}
    backend = backend or _backend_default()
    jobs = list(backend.list_jobs(include_disabled=True))
    if not all(isinstance(job, Mapping) for job in jobs):
        raise FixedJobConfigurationError("invalid-cron-record")
    managed_names = set(specs_by_name)
    managed_scripts = set(specs_by_script)
    collisions = [
        job
        for job in jobs
        if job.get("name") in managed_names or job.get("script") in managed_scripts
    ]
    by_name: dict[str, dict[str, Any]] = {}
    for job in collisions:
        name = str(job.get("name") or "")
        spec = specs_by_name.get(name) or specs_by_script.get(str(job.get("script") or ""))
        if spec is None or name in by_name:
            raise FixedJobConfigurationError("duplicate-health-job")
        if not job_matches_spec(job, spec):
            raise FixedJobConfigurationError(f"health-job-drift:{spec.role}")
        by_name[spec.name] = dict(job)

    for spec in specs:
        if spec.name in by_name:
            continue
        created = backend.create_job(
            prompt=spec.prompt,
            schedule=spec.schedule,
            name=spec.name,
            repeat=None,
            deliver="local",
            origin=None,
            script=spec.script,
            no_agent=spec.no_agent,
            attach_to_session=spec.attach_to_session,
            enabled_toolsets=list(spec.enabled_toolsets),
            provider=spec.model_provider,
            model=spec.model_id,
            base_url=spec.model_base_url,
        )
        if not isinstance(created, Mapping) or not created.get("id"):
            raise FixedJobConfigurationError(f"health-job-create-invalid:{spec.role}")
        by_name[spec.name] = dict(created)
    return [copy.deepcopy(by_name[spec.name]) for spec in specs]


def _job_fingerprint(job: Mapping[str, Any]) -> str:
    """Fallback fingerprint for tests; production uses Hermes' scheduler hash."""
    encoded = json.dumps(dict(job), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_runtime_job(
    role: str,
    environment: Mapping[str, str],
    jobs: Sequence[Mapping[str, Any]],
    fingerprint: Callable[[Mapping[str, Any]], str] | None = None,
    health_model_config: Any | None = None,
) -> bool:
    """Verify the scheduler-injected identity and the unique persisted Job."""
    specs_by_role = {
        spec.role: spec for spec in fixed_job_specs(health_model_config)
    }
    spec = specs_by_role.get(str(role))
    if spec is None:
        return False
    job_id = str(environment.get("HERMES_CRON_JOB_ID") or "").strip()
    claimed_fingerprint = str(environment.get("HERMES_CRON_JOB_FINGERPRINT") or "").strip()
    if not job_id or not claimed_fingerprint:
        return False
    matches = [job for job in jobs if str(job.get("id") or "") == job_id]
    if len(matches) != 1 or not job_matches_spec(matches[0], spec):
        return False
    fingerprint = fingerprint or _job_fingerprint
    try:
        actual = str(fingerprint(matches[0])).strip()
    except Exception:
        return False
    return bool(actual and hmac.compare_digest(actual, claimed_fingerprint))


def _capability_secret_path(path: str | os.PathLike[str] | None = None) -> Path:
    raw = str(path or os.environ.get("HEALTH_STEWARD_CAPABILITY_SECRET", "")).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser().resolve()
    return home / "private" / "health-steward-capability.key"


def _job_authorization_secret_path(
    path: str | os.PathLike[str] | None = None,
) -> Path:
    raw = str(
        path or os.environ.get("HEALTH_STEWARD_JOB_AUTHORIZATION_SECRET", "")
    ).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser().resolve()
    return home / "private" / "health-steward-job-authorization.key"


def _read_capability_secret(path: str | os.PathLike[str] | None = None) -> bytes:
    secret_path = _capability_secret_path(path)
    secret = secret_path.read_bytes()
    if len(secret) < 32:
        raise RuntimeError("health-capability-secret-invalid")
    return secret


def ensure_capability_secret(path: str | os.PathLike[str] | None = None) -> Path:
    """Create the integration-only signing key without overwriting an existing key."""
    secret_path = _capability_secret_path(path)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if not secret_path.exists():
        secret_path.write_bytes(secrets.token_bytes(32))
        try:
            secret_path.chmod(0o600)
        except OSError:
            pass
    _read_capability_secret(secret_path)
    return secret_path


def ensure_job_action_authorization_secret(
    path: str | os.PathLike[str] | None = None,
) -> Path:
    """Create the separate partner-to-sidecar delegation key once."""
    return ensure_job_authorization_secret(_job_authorization_secret_path(path))


def issue_sidecar_job_authorization(
    role: str,
    subject: str,
    capability: str,
    *,
    secret_path: str | os.PathLike[str] | None = None,
    issued_utc: dt.datetime | None = None,
) -> str:
    """Delegate one already-verified Job execution to the private sidecar."""
    return issue_job_action_authorization(
        read_job_authorization_secret(_job_authorization_secret_path(secret_path)),
        role=role,
        subject=subject,
        capability=capability,
        issued_utc=issued_utc,
    )


def _capability_consumption_dir(path: str | os.PathLike[str] | None = None) -> Path:
    secret_path = _capability_secret_path(path)
    return secret_path.parent / f"{secret_path.name}.consumed"


def _consume_capability_nonce(
    nonce: Any,
    issued_utc: dt.datetime,
    now_utc: dt.datetime,
    secret_path: str | os.PathLike[str] | None = None,
) -> bool:
    """Atomically consume one valid capability nonce in the partner private tree."""
    if not isinstance(nonce, str) or not _CAPABILITY_NONCE.fullmatch(nonce):
        return False
    directory = _capability_consumption_dir(secret_path)
    try:
        if directory.is_symlink():
            return False
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.is_dir() or directory.is_symlink():
            return False
        try:
            directory.chmod(0o700)
        except OSError:
            pass
        for marker in directory.iterdir():
            if marker.is_symlink() or not marker.is_file():
                continue
            try:
                marked = dt.datetime.fromisoformat(marker.read_text(encoding="utf-8"))
                if marked.tzinfo is None:
                    continue
                age = (
                    now_utc.astimezone(dt.timezone.utc)
                    - marked.astimezone(dt.timezone.utc)
                ).total_seconds()
                if age > CAPABILITY_TTL_SECONDS + 60:
                    marker.unlink()
            except (OSError, UnicodeError, ValueError):
                continue
        marker = directory / nonce
        descriptor = os.open(
            marker,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            os.write(
                descriptor,
                issued_utc.astimezone(dt.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .encode("ascii"),
            )
        finally:
            os.close(descriptor)
        try:
            marker.chmod(0o600)
        except OSError:
            pass
        return True
    except (FileExistsError, OSError):
        return False


def _capability_body(payload: Mapping[str, str]) -> str:
    encoded = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")


def issue_job_capability(
    role: str,
    job_id: str,
    fingerprint: str,
    issued_utc: dt.datetime | None = None,
    secret_path: str | os.PathLike[str] | None = None,
) -> str:
    """Sign one short-lived capability after the scheduler identity is verified."""
    if role not in _SPECS_BY_ROLE or not str(job_id).strip() or not str(fingerprint).strip():
        raise ValueError("invalid-health-capability-claims")
    issued = issued_utc or dt.datetime.now(dt.timezone.utc)
    if issued.tzinfo is None:
        raise ValueError("capability-time-must-be-aware")
    payload = {
        "role": role,
        "job_id": str(job_id).strip(),
        "fingerprint": str(fingerprint).strip(),
        "issued_utc": issued.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "nonce": secrets.token_hex(16),
    }
    body = _capability_body(payload)
    signature = hmac.new(
        _read_capability_secret(secret_path), body.encode(), hashlib.sha256
    ).hexdigest()
    return f"{body}.{signature}"


def verify_job_capability(
    token: str,
    role: str,
    *,
    jobs: Sequence[Mapping[str, Any]] | None = None,
    fingerprint: Callable[[Mapping[str, Any]], str] | None = None,
    now_utc: dt.datetime | None = None,
    secret_path: str | os.PathLike[str] | None = None,
    health_model_config: Any | None = None,
) -> bool:
    """Verify and atomically consume one Job capability exactly once."""
    try:
        body, signature = str(token).split(".", 1)
        expected = hmac.new(
            _read_capability_secret(secret_path), body.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if (
            not isinstance(payload, Mapping)
            or payload.get("role") != role
            or not _CAPABILITY_NONCE.fullmatch(str(payload.get("nonce") or ""))
        ):
            return False
        issued = dt.datetime.fromisoformat(str(payload.get("issued_utc")))
        if issued.tzinfo is None:
            return False
        now = now_utc or dt.datetime.now(dt.timezone.utc)
        if now.tzinfo is None:
            return False
        age = (
            now.astimezone(dt.timezone.utc) - issued.astimezone(dt.timezone.utc)
        ).total_seconds()
        if age < -60 or age > CAPABILITY_TTL_SECONDS:
            return False
        if jobs is None or fingerprint is None:
            from cron import jobs as cron_jobs
            from cron import scheduler

            jobs = cron_jobs.list_jobs(include_disabled=True)
            fingerprint = getattr(scheduler, "_runtime_job_fingerprint")
            health_model_config = (
                health_model_config or _load_fixed_health_model_config()
            )
        environment = {
            "HERMES_CRON_JOB_ID": str(payload.get("job_id") or ""),
            "HERMES_CRON_JOB_FINGERPRINT": str(payload.get("fingerprint") or ""),
        }
        if not verify_runtime_job(
            role,
            environment,
            jobs,
            fingerprint,
            health_model_config=health_model_config,
        ):
            return False
        return _consume_capability_nonce(
            payload["nonce"],
            issued,
            now,
            secret_path=secret_path,
        )
    except Exception:
        return False


def _zone(name: str) -> dt.tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Asia/Shanghai":
            return dt.timezone(dt.timedelta(hours=8), name=name)
        if name in {"UTC", "Etc/UTC"}:
            return dt.timezone.utc
        raise ValueError(f"unknown-timezone:{name}")


class JobRuntime:
    """Permission-separated, testable calls made by the two fixed Jobs."""

    def __init__(self, adapter: Any, subject: str, timezone: str, clock: Any) -> None:
        if not subject.strip():
            raise ValueError("subject-required")
        _zone(timezone)
        for method in (
            "daily_review_snapshot",
            "run_daily_review",
            "execute_daily_review",
            "dispatch_due_tasks",
        ):
            if not callable(getattr(adapter, method, None)):
                raise TypeError(f"adapter-missing:{method}")
        self.adapter = adapter
        self.subject = subject.strip()
        self.timezone = timezone
        self.clock = clock

    def _now(self) -> dt.datetime:
        now = self.clock.now_utc() if hasattr(self.clock, "now_utc") else self.clock()
        if not isinstance(now, dt.datetime) or now.tzinfo is None:
            raise ValueError("clock-must-return-aware-datetime")
        return now.astimezone(dt.timezone.utc).replace(microsecond=0)

    def _review_utc(self) -> str:
        now = self._now()
        local = now.astimezone(_zone(self.timezone)).replace(
            hour=4, minute=0, second=0, microsecond=0
        )
        return local.astimezone(dt.timezone.utc).isoformat()

    def current_utc(self) -> dt.datetime:
        """Return the scheduler-owned current time for delegated proof expiry."""
        return self._now()

    def daily_snapshot(self) -> Mapping[str, Any]:
        return self.adapter.daily_review_snapshot(
            self.subject, self._review_utc(), self.timezone
        )

    def daily_apply(self, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(plan, Mapping):
            raise ValueError("daily-plan-must-be-object")
        return self.adapter.run_daily_review(
            self.subject, self._review_utc(), self.timezone, dict(plan)
        )

    def execute_daily_review(self, job_authorization: str) -> Mapping[str, Any]:
        """Ask the sidecar-owned pinned executor to run one delegated Job attempt."""
        if not isinstance(job_authorization, str) or not job_authorization.strip():
            raise ValueError("job-authorization-required")
        return self.adapter.execute_daily_review(
            self.subject, self._review_utc(), self.timezone, job_authorization
        )

    def dispatch(self, job_authorization: str) -> Mapping[str, Any]:
        if not isinstance(job_authorization, str) or not job_authorization.strip():
            raise ValueError("job-authorization-required")
        return self.adapter.dispatch_due_tasks(
            self.subject, self._now().isoformat(), job_authorization
        )

    def dispatch_snapshot(self) -> Mapping[str, Any]:
        """Return non-content context; dispatch re-reads authoritative state in sidecar."""
        return {
            "subject": self.subject,
            "now_utc": self._now().isoformat(),
            "action": "health_dispatch_due_tasks",
            "authority": "sidecar-current-snapshot",
        }


def _source_root() -> Path:
    raw = os.environ.get("HEALTH_STEWARD_SOURCE_ROOT", "").strip()
    if not raw:
        raise RuntimeError("health-source-root-unconfigured")
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError("health-source-root-unavailable")
    return path


def load_runtime_from_environment(clock: Any | None = None) -> JobRuntime:
    source_root = _source_root()
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from sidecar import PartnerHealthAdapter

    socket_path = os.environ.get(
        "HEALTH_STEWARD_SOCKET", "/run/health-sidecar/health.sock"
    ).strip()
    subject = os.environ.get("HEALTH_STEWARD_SUBJECT", "profile").strip()
    timezone = os.environ.get("HEALTH_STEWARD_TIMEZONE", "Asia/Shanghai").strip()
    if not socket_path:
        raise RuntimeError("health-socket-unconfigured")
    if clock is None:
        from sidecar.store import SystemClock

        clock = SystemClock()
    return JobRuntime(PartnerHealthAdapter(socket_path), subject, timezone, clock)


def snapshot_for_role(role: str) -> Mapping[str, Any]:
    """Read a controlled snapshot for the pre-run script; failures are caller-owned."""
    # The scheduler strips caller-provided identity claims and injects these
    # values for the exact in-memory Job snapshot.  A manually run script or a
    # stale/edited Cron record therefore cannot obtain a health snapshot.
    try:
        from cron import jobs as cron_jobs
        from cron import scheduler

        if not verify_runtime_job(
            role,
            os.environ,
            cron_jobs.list_jobs(include_disabled=True),
            getattr(scheduler, "_runtime_job_fingerprint"),
            health_model_config=_load_fixed_health_model_config(),
        ):
            raise RuntimeError("fixed-job-identity-invalid")
    except Exception as exc:
        if str(exc) == "fixed-job-identity-invalid":
            raise
        raise RuntimeError("hermes-scheduler-unavailable") from exc
    if role == DAILY_ROLE:
        # Do not place health content into the native Cron agent context.  The
        # plugin reloads the current snapshot only after it consumes this
        # capability, then calls the direct pinned health-model boundary.
        snapshot = {
            "action": "health_daily_review",
            "authority": "sidecar-current-snapshot",
        }
    elif role == DISPATCH_ROLE:
        runtime = load_runtime_from_environment()
        snapshot = runtime.dispatch_snapshot()
    else:
        raise ValueError("unknown-health-job-role")
    capability = issue_job_capability(
        role,
        os.environ["HERMES_CRON_JOB_ID"],
        os.environ["HERMES_CRON_JOB_FINGERPRINT"],
    )
    return {
        "role": role,
        "snapshot": copy.deepcopy(dict(snapshot)),
        "capability": capability,
    }


__all__ = [
    "DAILY_JOB_NAME",
    "DISPATCH_JOB_NAME",
    "DAILY_ROLE",
    "DISPATCH_ROLE",
    "FixedJobConfigurationError",
    "FixedJobSpec",
    "CAPABILITY_TTL_SECONDS",
    "JobRuntime",
    "ensure_capability_secret",
    "ensure_job_action_authorization_secret",
    "fixed_job_specs",
    "install_fixed_jobs",
    "issue_job_capability",
    "issue_sidecar_job_authorization",
    "job_matches_spec",
    "load_runtime_from_environment",
    "snapshot_for_role",
    "verify_runtime_job",
    "verify_job_capability",
]

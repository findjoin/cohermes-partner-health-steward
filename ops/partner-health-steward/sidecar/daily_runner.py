"""Durable execution owner for the fixed 04:00 daily review.

The native Hermes Job is deliberately only an authenticated trigger.  This
module owns the health-bearing snapshot, the direct pinned model call, and the
single persisted retry so a gateway restart cannot turn a model failure into a
lost daily review.
"""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any, Callable, Mapping

from .profile import ProfileStoreError
from .tasks import DAILY_REVIEW_RETRY_GRACE, _zone


DAILY_REVIEW_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome"],
    "properties": {
        "outcome": {"type": "string", "enum": ["no_action", "tasks", "failure"]},
        "tasks": {"type": "array", "maxItems": 20, "items": {"type": "object"}},
        "reason": {"type": "string", "maxLength": 200},
        "maintenance": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "refresh_profile": {"type": "boolean"},
                "source_scan_candidates": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {"type": "string", "minLength": 1, "maxLength": 2048},
                },
            },
        },
    },
}

DAILY_REVIEW_INSTRUCTIONS = (
    "Produce only one structured daily health-review plan. Use the supplied current "
    "profile, evidence, feedback and source cards; never diagnose, change medication, "
    "or draft/send a final message. Choose no_action or evidence-bound candidate tasks. "
    "Every task must be low risk and include the required references and time window. "
    "If a safe plan cannot be made, return outcome failure."
)

_TERMINAL_SNAPSHOT_RESULTS = frozenset(
    {
        "already_completed",
        "retry_not_due",
        "retry_exhausted",
        "retry_window_expired",
        "recording_stopped",
    }
)
GATEWAY_JOB_LEASE_SECONDS = 60


class GatewayJobLease:
    """In-memory proof that a validated partner Job is presently executing.

    The lease is deliberately shorter than the five-minute dispatcher cadence.
    A retry may begin only after a newly authenticated daily/dispatch Job
    refreshes it; a sidecar restart or a stopped Gateway therefore cannot wake
    an autonomous health-model call from persisted state alone.
    """

    def __init__(
        self,
        now_utc: Callable[[], dt.datetime],
        *,
        duration_seconds: int = GATEWAY_JOB_LEASE_SECONDS,
    ) -> None:
        if duration_seconds <= 0:
            raise ValueError("gateway-job-lease-duration-invalid")
        self._now_utc = now_utc
        self._duration = dt.timedelta(seconds=duration_seconds)
        self._last_seen: dt.datetime | None = None
        self._lock = threading.Lock()

    def renew(self) -> None:
        now = self._now_utc().astimezone(dt.timezone.utc)
        with self._lock:
            self._last_seen = now

    def active(self) -> bool:
        now = self._now_utc().astimezone(dt.timezone.utc)
        with self._lock:
            if self._last_seen is None:
                return False
            elapsed = now - self._last_seen
            # A backward wall-clock jump must fail closed rather than extend a
            # stale Gateway proof indefinitely.
            return dt.timedelta(0) <= elapsed <= self._duration


class DailyReviewExecutor:
    """Run and recover the one allowed daily-review retry for one subject.

    ``run_initial`` is called only by the capability-gated daily Job.  The
    background loop never receives a capability and can only resume a
    previously persisted attempt-one failure for its configured subject.
    """

    def __init__(
        self,
        *,
        store: Any,
        source_library: Any,
        model: Any,
        subject: str,
        gateway_live: Callable[[], bool],
    ) -> None:
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("daily-review-subject-required")
        if not callable(getattr(model, "complete_daily_review", None)):
            raise ValueError("daily-review-model-required")
        if not callable(gateway_live):
            raise ValueError("daily-review-gateway-lease-required")
        self.store = store
        self.source_library = source_library
        self.model = model
        self.subject = subject.strip()
        self._gateway_live = gateway_live
        self._attempt_lock = threading.RLock()
        self._stopped = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def run_initial(self, review_utc: str, timezone: str) -> Mapping[str, Any]:
        """Execute the initial 04:00 attempt after the Job capability is checked."""
        if not self._gateway_available():
            return {"result": "gateway_unavailable", "created_tasks": []}
        return self._run_attempt(review_utc, timezone)

    def _gateway_available(self) -> bool:
        try:
            return bool(self._gateway_live())
        except Exception:
            return False

    def _run_attempt(
        self,
        review_utc: str,
        timezone: str,
        *,
        retry_only: bool = False,
    ) -> Mapping[str, Any]:
        with self._attempt_lock:
            snapshot = self.store.daily_review_snapshot(
                self.subject,
                review_utc,
                timezone,
                retry_only=retry_only,
            )
            if isinstance(snapshot, Mapping) and snapshot.get("result") in _TERMINAL_SNAPSHOT_RESULTS:
                return dict(snapshot)
            if not isinstance(snapshot, Mapping):
                raise RuntimeError("daily-review-snapshot-invalid")
            try:
                plan = self.model.complete_daily_review(dict(snapshot))
                if not isinstance(plan, Mapping):
                    raise RuntimeError("daily-review-model-invalid")
            except Exception:
                # Model/provider/parse errors are deliberately mapped to the
                # sidecar's deterministic content-free failure route.  That
                # route writes retry_after_utc and the audit event atomically.
                plan = {"outcome": "failure"}
            result = self.store.run_daily_review(
                self.subject,
                review_utc,
                timezone,
                plan,
                source_library=self.source_library,
                retry_only=retry_only,
            )
            if isinstance(result, Mapping) and result.get("retry_after_utc"):
                self._wake.set()
            return dict(result)

    def _pending_retry(self) -> tuple[str, str, dt.datetime] | None:
        try:
            profile = self.store.read_subject_status(
                self.subject,
                _allow_profile_state=True,
            )
        except Exception:
            return None
        if not isinstance(profile, Mapping):
            return None
        timezone = profile.get("owner_timezone")
        if not isinstance(timezone, str) or not timezone.strip():
            return None
        try:
            zone = _zone(timezone)
        except ProfileStoreError:
            return None
        now = self.store.now_utc().astimezone(dt.timezone.utc)
        local_date = now.astimezone(zone).date().isoformat()
        runs = profile.get("daily_review_runs", [])
        if not isinstance(runs, list):
            return None
        current = next(
            (
                item
                for item in reversed(runs)
                if isinstance(item, Mapping) and item.get("local_date") == local_date
            ),
            None,
        )
        try:
            attempt = int(current.get("attempt", 0) or 0) if isinstance(current, Mapping) else 0
        except (TypeError, ValueError):
            return None
        if (
            not isinstance(current, Mapping)
            or current.get("status") != "failed"
            or attempt != 1
        ):
            return None
        review_utc = current.get("review_utc")
        retry_after = current.get("retry_after_utc")
        if not isinstance(review_utc, str) or not review_utc.strip():
            return None
        if not isinstance(retry_after, str) or not retry_after.strip():
            return None
        try:
            due = dt.datetime.fromisoformat(retry_after.replace("Z", "+00:00"))
        except ValueError:
            return None
        if due.tzinfo is None:
            return None
        return review_utc, timezone, due.astimezone(dt.timezone.utc)

    def run_due_retries(self) -> list[Mapping[str, Any]]:
        """Recover the persisted retry at most once, including after restart."""
        pending = self._pending_retry()
        if pending is None:
            return []
        review_utc, timezone, due = pending
        now = self.store.now_utc().astimezone(dt.timezone.utc)
        if now < due:
            return []
        if now > due + DAILY_REVIEW_RETRY_GRACE:
            try:
                return [
                    self.store.expire_daily_review_retry(
                        self.subject, review_utc, timezone
                    )
                ]
            except Exception:
                return []
        if not self._gateway_available():
            return []
        try:
            return [self._run_attempt(review_utc, timezone, retry_only=True)]
        except Exception:
            # An unavailable store cannot safely manufacture a retry result.
            # Keep the persisted attempt-one record for the next worker wake.
            return []

    def _next_wait_seconds(self) -> float:
        pending = self._pending_retry()
        if pending is None:
            return 60.0
        _review_utc, _timezone, due = pending
        now = self.store.now_utc().astimezone(dt.timezone.utc)
        # A failed socket/store attempt leaves the persisted retry record in
        # place.  Do not hot-loop on it; the next bounded worker wake can
        # recover it once the dependency returns.
        return max(60.0, (due - now).total_seconds())

    def _run_loop(self) -> None:
        while not self._stopped.is_set():
            self.run_due_retries()
            self._wake.wait(self._next_wait_seconds())
            self._wake.clear()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            name="health-daily-review-retry",
            daemon=True,
        )
        self._thread.start()

    def wake(self) -> None:
        """Promptly recheck a retry after a verified Gateway Job arrives."""
        self._wake.set()

    def stop(self) -> None:
        self._stopped.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


__all__ = [
    "DAILY_REVIEW_INSTRUCTIONS",
    "DAILY_REVIEW_PLAN_SCHEMA",
    "DailyReviewExecutor",
    "GatewayJobLease",
]

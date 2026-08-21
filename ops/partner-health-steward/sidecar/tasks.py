"""Daily review snapshots and fail-closed derived-task planning."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import uuid
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .profile import (
    ProfileStoreError,
    _compact_conclusions,
    _expired,
    _profile_from_status,
    _refresh_preference_lifecycle,
)
from .store import HealthSidecarStore, StoreError


DEFAULT_OWNER_TIMEZONE = "Asia/Shanghai"
DAILY_REVIEW_LOCAL_HOUR = 4
DAILY_REVIEW_RETRY_DELAY = dt.timedelta(minutes=10)
# The retry is a deliberate one-shot at +10 minutes, not a deferred catch-up
# task. One minute accounts for scheduler/socket jitter while preventing a
# same-day restart hours later from manufacturing another health model call.
DAILY_REVIEW_RETRY_GRACE = dt.timedelta(minutes=1)
DAILY_REVIEW_CLOCK_SKEW = dt.timedelta(minutes=1)
UNANSWERED_TOPIC_BACKOFF = dt.timedelta(hours=72)
NIGHT_START_LOCAL_HOUR = 22
NIGHT_END_LOCAL_HOUR = 6
WEEKLY_REPORT_TASK_TYPE = "profile_difference_report"
WEEKLY_REPORT_LOCAL_HOUR = 10
WEEKLY_REPORT_WINDOW = dt.timedelta(hours=1)
TASK_STATUSES = {"candidate", "scheduled", "due_for_render"}
ALLOWED_TASK_TYPES = {
    WEEKLY_REPORT_TASK_TYPE,
    "profile_completion_question",
    "status_follow_up",
    "care_message",
    "low_risk_reminder",
    "immediate_conversation",
    "future_contact",
}
FORBIDDEN_TASK_TYPES = {"diagnosis", "medication_change", "external_notification"}
FINAL_COPY_KEYS = {
    "message",
    "message_copy",
    "final_message",
    "body",
    "content",
    "prompt",
    "text",
}
TASK_FIELDS = {
    "task_type",
    "purpose",
    "evidence_ids",
    "conclusion_keys",
    "source_card_ids",
    "time_window",
    "valid_until_utc",
    "dedupe_key",
    "topic_key",
    "timing_rationale",
    "policy_constraints",
    "recipient_sender_id",
    "report_id",
    "report_from_version_id",
    "report_to_version_id",
    "report_change_refs",
}
PLAN_FIELDS = {"outcome", "tasks", "reason", "maintenance"}


def _utc(value: Any, code: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProfileStoreError(code)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProfileStoreError(code) from exc
    if parsed.tzinfo is None:
        raise ProfileStoreError(code)
    return parsed.astimezone(dt.timezone.utc)


def _timezone(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileStoreError("owner-timezone-required")
    value = value.strip()
    _zone(value)
    return value


def _zone(value: str) -> dt.tzinfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        # The deployment baseline uses Asia/Shanghai, which has a stable
        # UTC+08:00 offset in the supported operating window.  Keep this
        # fallback so a minimal Python install without the optional tzdata
        # package still honors the explicit default timezone.
        if value == "Asia/Shanghai":
            return dt.timezone(dt.timedelta(hours=8), name=value)
        if value in {"UTC", "Etc/UTC"}:
            return dt.timezone.utc
        raise ProfileStoreError("unknown-owner-timezone") from exc


def _contains_final_copy(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).casefold() in FINAL_COPY_KEYS
            or _contains_final_copy(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_final_copy(item) for item in value)
    return False


def _profile_timezone(profile: Mapping[str, Any]) -> str:
    return _timezone(profile.get("owner_timezone", DEFAULT_OWNER_TIMEZONE))


def _is_night_local(now: dt.datetime, timezone: str) -> bool:
    hour = now.astimezone(_zone(timezone)).hour
    return hour >= NIGHT_START_LOCAL_HOUR or hour < NIGHT_END_LOCAL_HOUR


def _proactive_pause_active(proactive: Any, now: dt.datetime) -> bool:
    if not isinstance(proactive, Mapping) or not proactive.get("paused"):
        return False
    pause_until = proactive.get("pause_until_utc")
    if pause_until in (None, ""):
        return True
    return _utc(pause_until, "invalid-pause-time") > now


def _task_topic_key(task: Mapping[str, Any]) -> str:
    conclusion_keys = task.get("conclusion_keys")
    evidence_ids = task.get("evidence_ids")
    if isinstance(conclusion_keys, list) and conclusion_keys:
        basis = "conclusion:" + "|".join(
            sorted({str(item).strip() for item in conclusion_keys if str(item).strip()})
        )
        if basis != "conclusion:":
            return basis if len(basis) <= 120 else "conclusion:" + hashlib.sha256(basis.encode()).hexdigest()[:32]
    if isinstance(evidence_ids, list) and evidence_ids:
        basis = "evidence:" + "|".join(
            sorted({str(item).strip() for item in evidence_ids if str(item).strip()})
        )
        if basis != "evidence:":
            return basis if len(basis) <= 120 else "evidence:" + hashlib.sha256(basis.encode()).hexdigest()[:32]
    return str(task.get("topic_key") or task.get("dedupe_key") or "").strip()


def _unanswered_topic_blocked(
    profile: Mapping[str, Any], task: Mapping[str, Any], now: dt.datetime
) -> bool:
    topic_key = _task_topic_key(task)
    if not topic_key:
        return False
    for prior in profile.get("tasks", []):
        if not isinstance(prior, Mapping) or prior.get("status") != "sent":
            continue
        if _task_topic_key(prior) != topic_key:
            continue
        sent_utc = prior.get("sent_utc")
        if not sent_utc:
            continue
        try:
            sent = _utc(sent_utc, "invalid-task-sent-time")
        except ProfileStoreError:
            continue
        if sent > now:
            continue
        reply_utc = prior.get("owner_reply_utc")
        if reply_utc:
            try:
                if _utc(reply_utc, "invalid-owner-reply-time") > sent:
                    continue
            except ProfileStoreError:
                pass
        if now - sent < UNANSWERED_TOPIC_BACKOFF:
            return True
    return False


_REPORT_VIEW_PERMISSIONS = {"profile", "evidence", "tasks", "reports", "audit"}
_REPORT_TASK_EVENTS = {"task_sent", "task_skipped", "task_failed"}
_REPORT_AUTH_EVENTS = {"access_grant", "access_revoke"}
_REPORT_DELETE_EVENTS = {"profile_deleted", "profile_delete_failed"}
_REPORT_CHANGE_REF_LISTS = {
    "added_conclusion_keys",
    "removed_conclusion_keys",
    "changed_conclusion_keys",
    "evidence_added_ids",
    "evidence_revoked_ids",
}
_REPORT_AUDIT_REF_LISTS = {
    "task_event_refs",
    "authorization_event_refs",
    "deletion_event_refs",
    "daily_review_failure_refs",
    "audit_refs",
}


def _validate_report_change_refs(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProfileStoreError("weekly-report-references-required")
    allowed = _REPORT_CHANGE_REF_LISTS | _REPORT_AUDIT_REF_LISTS | {
        "from_version_id",
        "to_version_id",
        "profile_summary_changed",
    }
    if set(value).difference(allowed):
        raise ProfileStoreError("weekly-report-reference-fields-unsupported")
    normalized: dict[str, Any] = {}
    for field in _REPORT_CHANGE_REF_LISTS:
        entries = value.get(field, [])
        if not isinstance(entries, list) or len(entries) > 200 or not all(
            isinstance(item, str) and item.strip() and len(item) <= 120
            for item in entries
        ):
            raise ProfileStoreError("weekly-report-reference-list-invalid")
        normalized[field] = list(dict.fromkeys(item.strip() for item in entries))
    for field in _REPORT_AUDIT_REF_LISTS:
        entries = value.get(field, [])
        if not isinstance(entries, list) or len(entries) > 200:
            raise ProfileStoreError("weekly-report-audit-reference-list-invalid")
        normalized_entries = []
        for entry in entries:
            if not isinstance(entry, Mapping) or set(entry).difference(
                {"ref", "utc", "event", "object_id"}
            ):
                raise ProfileStoreError("weekly-report-audit-reference-invalid")
            if not all(
                isinstance(entry.get(key), str)
                and entry.get(key).strip()
                and len(entry.get(key)) <= 160
                for key in ("ref", "utc", "event")
            ):
                raise ProfileStoreError("weekly-report-audit-reference-invalid")
            normalized_entry = {
                key: entry[key]
                for key in ("ref", "utc", "event", "object_id")
                if key in entry
            }
            if "object_id" in normalized_entry and not str(
                normalized_entry["object_id"]
            ).strip():
                raise ProfileStoreError("weekly-report-audit-reference-invalid")
            normalized_entries.append(normalized_entry)
        normalized[field] = normalized_entries
    for field in ("from_version_id", "to_version_id"):
        item = value.get(field)
        if item not in (None, "") and (
            not isinstance(item, str) or not item.strip() or len(item) > 120
        ):
            raise ProfileStoreError("weekly-report-version-reference-invalid")
        normalized[field] = item.strip() if isinstance(item, str) and item.strip() else None
    if not isinstance(value.get("profile_summary_changed"), bool):
        raise ProfileStoreError("weekly-report-summary-reference-invalid")
    normalized["profile_summary_changed"] = value["profile_summary_changed"]
    return normalized


def _version_by_id(profile: Mapping[str, Any], version_id: Any) -> Mapping[str, Any] | None:
    if not isinstance(version_id, str) or not version_id:
        return None
    for version in profile.get("profile_versions", []):
        if isinstance(version, Mapping) and version.get("version_id") == version_id:
            return version
    return None


def _audit_reference(event_index: int, event: Mapping[str, Any]) -> dict[str, str]:
    details = event.get("details")
    object_id = ""
    if isinstance(details, Mapping):
        object_id = str(
            details.get("object_id")
            or details.get("task_id")
            or details.get("grant_id")
            or ""
        )
    reference = {
        "ref": f"audit-{event_index}",
        "utc": str(event.get("utc", "")),
        "event": str(event.get("event", "")),
    }
    if object_id:
        reference["object_id"] = object_id
    return reference


def _weekly_report_change_refs(
    store: HealthSidecarStore,
    subject: str,
    profile: Mapping[str, Any],
    from_version_id: str | None,
    to_version_id: str,
    now: dt.datetime,
    audit_since_utc: dt.datetime | None = None,
    ignore_audit_object_ids: set[str] | None = None,
) -> dict[str, Any]:
    current = _version_by_id(profile, to_version_id)
    if current is None:
        raise ProfileStoreError("weekly-report-version-invalid")
    previous = _version_by_id(profile, from_version_id)
    previous_conclusions = {
        str(item.get("dedupe_key")): dict(item)
        for item in (previous or {}).get("conclusions", [])
        if isinstance(item, Mapping) and item.get("dedupe_key")
    }
    current_conclusions = {
        str(item.get("dedupe_key")): dict(item)
        for item in current.get("conclusions", [])
        if isinstance(item, Mapping) and item.get("dedupe_key")
    }
    previous_keys = set(previous_conclusions)
    current_keys = set(current_conclusions)
    changed_keys = sorted(
        key
        for key in previous_keys & current_keys
        if previous_conclusions[key] != current_conclusions[key]
    )
    previous_evidence = set(str(item) for item in (previous or {}).get("evidence_ids", []))
    current_evidence = set(str(item) for item in current.get("evidence_ids", []))
    since_utc = _utc(
        previous.get("created_utc") if previous else current.get("created_utc"),
        "weekly-report-version-time-invalid",
    )
    evidence_since_utc = audit_since_utc or since_utc
    audit_refs: list[dict[str, str]] = []
    task_refs: list[dict[str, str]] = []
    authorization_refs: list[dict[str, str]] = []
    deletion_refs: list[dict[str, str]] = []
    daily_review_failure_refs: list[dict[str, str]] = []
    for index, event in enumerate(store.read_audit_events(limit=None)):
        if not isinstance(event, Mapping):
            continue
        details = event.get("details")
        if not isinstance(details, Mapping) or details.get("subject") != subject:
            continue
        try:
            event_utc = _utc(event.get("utc"), "weekly-report-audit-time-invalid")
        except ProfileStoreError:
            continue
        if audit_since_utc is not None:
            if event_utc <= audit_since_utc or event_utc > now:
                continue
        elif event_utc < since_utc or event_utc > now:
            continue
        event_name = str(event.get("event", ""))
        reference = _audit_reference(index, event)
        if (
            event_name in _REPORT_TASK_EVENTS
            and ignore_audit_object_ids
            and reference.get("object_id") in ignore_audit_object_ids
        ):
            continue
        if event_name in _REPORT_TASK_EVENTS:
            task_refs.append(reference)
        elif event_name in _REPORT_AUTH_EVENTS:
            authorization_refs.append(reference)
        elif event_name in _REPORT_DELETE_EVENTS:
            deletion_refs.append(reference)
        elif event_name == "daily_review_failed":
            daily_review_failure_refs.append(reference)
        if event_name in (
            _REPORT_TASK_EVENTS
            | _REPORT_AUTH_EVENTS
            | _REPORT_DELETE_EVENTS
            | {"daily_review_failed"}
        ):
            audit_refs.append(reference)

    revoked_ids = sorted(
        str(item.get("evidence_id"))
        for item in profile.get("evidence", [])
        if isinstance(item, Mapping)
        and item.get("revoked_utc")
        and _utc(item.get("revoked_utc"), "weekly-report-evidence-time-invalid") > evidence_since_utc
        and _utc(item.get("revoked_utc"), "weekly-report-evidence-time-invalid") <= now
    )
    previous_summary = str(previous.get("profile_summary_zh", "")) if previous else ""
    return {
        "from_version_id": from_version_id,
        "to_version_id": to_version_id,
        "added_conclusion_keys": sorted(current_keys - previous_keys),
        "removed_conclusion_keys": sorted(previous_keys - current_keys),
        "changed_conclusion_keys": changed_keys,
        "profile_summary_changed": previous_summary
        != str(current.get("profile_summary_zh", "")),
        "evidence_added_ids": sorted(current_evidence - previous_evidence),
        "evidence_revoked_ids": revoked_ids,
        "task_event_refs": task_refs,
        "authorization_event_refs": authorization_refs,
        "deletion_event_refs": deletion_refs,
        "daily_review_failure_refs": daily_review_failure_refs,
        "audit_refs": audit_refs,
    }


def _weekly_report_candidates(
    store: HealthSidecarStore,
    subject: str,
    profile: Mapping[str, Any],
    review_time: dt.datetime,
    timezone: str,
    now: dt.datetime,
) -> list[dict[str, Any]]:
    if (
        store.expected_viewer_sender_id
        and profile.get("viewer_configuration_sender_id")
        != store.expected_viewer_sender_id
    ):
        return []
    local_review = review_time.astimezone(_zone(timezone))
    if local_review.weekday() != 6:
        return []
    current_version_id = profile.get("current_version_id")
    if not isinstance(current_version_id, str) or not current_version_id:
        return []
    versions = [
        version
        for version in profile.get("profile_versions", [])
        if isinstance(version, Mapping) and version.get("version_id")
    ]
    current_index = next(
        (index for index, version in enumerate(versions) if version.get("version_id") == current_version_id),
        None,
    )
    if current_index is None:
        return []
    adjacent_from_version_id = (
        str(versions[current_index - 1].get("version_id"))
        if current_index > 0
        else None
    )
    report_start_local = local_review.replace(
        hour=WEEKLY_REPORT_LOCAL_HOUR, minute=0, second=0, microsecond=0
    )
    report_start = report_start_local.astimezone(dt.timezone.utc)
    report_end = report_start + WEEKLY_REPORT_WINDOW
    candidates: list[dict[str, Any]] = []
    for grant in profile.get("viewer_grants", []):
        if not isinstance(grant, Mapping) or not grant.get("active", True):
            continue
        permissions = set(grant.get("permissions", []))
        if not _REPORT_VIEW_PERMISSIONS.issubset(permissions):
            continue
        viewer = str(grant.get("viewer_sender_id", "")).strip()
        if not viewer:
            continue
        if (
            store.expected_viewer_sender_id
            and viewer != store.expected_viewer_sender_id
        ):
            continue
        last_report = next(
            (
                report
                for report in reversed(profile.get("reports", []))
                if isinstance(report, Mapping)
                and report.get("to_version_id")
                and report.get("recipient_sender_id") == viewer
            ),
            None,
        )
        from_version_id = adjacent_from_version_id
        if last_report and last_report.get("to_version_id") == current_version_id:
            # Keep the weekly task explicit, but compare the version with itself
            # so an unchanged week can be rendered as a truthful no-change skip.
            from_version_id = current_version_id
        if last_report:
            audit_since_utc = _utc(
                last_report.get("created_utc"),
                "weekly-report-baseline-time-invalid",
            )
            ignore_audit_object_ids = (
                {str(last_report.get("task_id"))}
                if last_report.get("task_id")
                else set()
            )
        else:
            audit_since_utc = None
            ignore_audit_object_ids = set()
        change_refs = _weekly_report_change_refs(
            store,
            subject,
            profile,
            from_version_id,
            current_version_id,
            now,
            audit_since_utc,
            ignore_audit_object_ids,
        )
        report_id = f"report-{local_review.date().isoformat()}-{uuid.uuid4().hex}"
        candidates.append(
            {
                "task_type": WEEKLY_REPORT_TASK_TYPE,
                "purpose": f"weekly profile difference report for {viewer}",
                "evidence_ids": [],
                "conclusion_keys": [],
                "source_card_ids": [],
                "time_window": {
                    "start_utc": report_start.isoformat(),
                    "end_utc": report_end.isoformat(),
                },
                "valid_until_utc": report_end.isoformat(),
                "dedupe_key": f"weekly-report:{local_review.date().isoformat()}:{viewer}",
                "topic_key": f"weekly-report:{local_review.date().isoformat()}:{viewer}",
                "timing_rationale": "fixed Sunday 10:00 owner-time report",
                "policy_constraints": {"viewer_report": True},
                "recipient_sender_id": viewer,
                "report_id": report_id,
                "report_from_version_id": from_version_id,
                "report_to_version_id": current_version_id,
                "report_change_refs": copy.deepcopy(change_refs),
            }
        )
    return candidates


def _review_local_date(review_utc: dt.datetime, timezone: str) -> str:
    return review_utc.astimezone(_zone(timezone)).date().isoformat()


def _validate_review_time(
    store: HealthSidecarStore,
    review_utc: Any,
    timezone: Any,
    *,
    retry_only: bool = False,
) -> tuple[dt.datetime, str, str]:
    review_time = _utc(review_utc, "invalid-review-utc")
    zone = _timezone(timezone)
    now = store.now_utc().astimezone(dt.timezone.utc)
    local = review_time.astimezone(_zone(zone))
    if local.hour != DAILY_REVIEW_LOCAL_HOUR or local.minute != 0 or local.second != 0:
        raise ProfileStoreError("daily-review-not-at-owner-0400")
    current_local = now.astimezone(_zone(zone))
    if local.date() != current_local.date():
        raise ProfileStoreError("daily-review-date-not-current")
    if review_time > now + DAILY_REVIEW_CLOCK_SKEW:
        raise ProfileStoreError("daily-review-time-in-future")
    # The native daily Job is a strict 04:00 trigger, not a catch-up queue.
    # Its first attempt may absorb only ordinary scheduler jitter.  The
    # explicitly persisted retry path below is the sole way to run later.
    if not retry_only and review_time < now - DAILY_REVIEW_CLOCK_SKEW:
        raise ProfileStoreError("daily-review-time-too-old")
    return review_time, zone, local.date().isoformat()


def _valid_evidence(profile: Mapping[str, Any], now: dt.datetime) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for evidence in profile.get("evidence", []):
        if not isinstance(evidence, Mapping):
            continue
        if evidence.get("revoked_utc"):
            continue
        try:
            valid_until = evidence.get("valid_until_utc")
            if valid_until and _utc(valid_until, "invalid-evidence-validity") <= now:
                continue
        except ProfileStoreError:
            continue
        valid.append(copy.deepcopy(dict(evidence)))
    return valid


def _snapshot(
    store: HealthSidecarStore,
    subject: str,
    profile: Mapping[str, Any],
    review_utc: dt.datetime,
    timezone: str,
) -> dict[str, Any]:
    now = store.now_utc().astimezone(dt.timezone.utc)
    source_state = store.read_source_library_state() or {}
    cards = [
        copy.deepcopy(dict(card))
        for card in source_state.get("cards", [])
        if isinstance(card, Mapping) and card.get("current", True)
    ]
    tasks = [
        copy.deepcopy(dict(task))
        for task in profile.get("tasks", [])
        if isinstance(task, Mapping)
    ]
    active_grants = [
        grant
        for grant in profile.get("viewer_grants", [])
        if (
            isinstance(grant, Mapping)
            and grant.get("active", True)
            and (
                not store.expected_viewer_sender_id
                or (
                    profile.get("viewer_configuration_sender_id")
                    == store.expected_viewer_sender_id
                    and grant.get("viewer_sender_id")
                    == store.expected_viewer_sender_id
                )
            )
        )
    ]
    snapshot = {
        "subject": subject,
        "review_utc": review_utc.replace(microsecond=0).isoformat(),
        "owner_timezone": timezone,
        "recording_status": str(
            profile.get("recording_status", "recording_enabled")
        ),
        "profile": {
            "profile_summary_zh": str(profile.get("profile_summary_zh", "")),
            "current_version_id": profile.get("current_version_id"),
            "conclusions": copy.deepcopy(list(profile.get("conclusions", []))),
            "deferred_conclusions": copy.deepcopy(
                list(profile.get("deferred_conclusions", []))
            ),
        },
        "evidence": _valid_evidence(profile, now),
        "source_cards": cards,
        "tasks": tasks,
        "task_feedback": [
            copy.deepcopy(dict(task.get("feedback")))
            for task in tasks
            if isinstance(task.get("feedback"), Mapping)
        ],
        "authorization": {
            "owner_bound": bool(profile.get("owner_sender_id")),
            "active_viewer_count": len(active_grants),
        },
        "proactive_contact": copy.deepcopy(
            dict(profile.get("proactive_contact", {}))
            if isinstance(profile.get("proactive_contact", {}), Mapping)
            else {}
        ),
    }
    return snapshot


def _recording_stopped_snapshot(
    subject: str, review_utc: dt.datetime, timezone: str
) -> dict[str, Any]:
    """Return a no-content Job snapshot while recording is stopped."""
    return {
        "subject": subject,
        "review_utc": review_utc.replace(microsecond=0).isoformat(),
        "owner_timezone": timezone,
        "recording_status": "recording_stopped",
        "profile": {},
        "evidence": [],
        "source_cards": [],
        "tasks": [],
        "task_feedback": [],
        "authorization": {
            "owner_bound": True,
            "active_viewer_count": 0,
        },
        "proactive_contact": {
            "paused": True,
            "pause_until_utc": None,
        },
    }


def _recording_stopped_result(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "result": "recording_stopped",
        "attempt": 0,
        "created_tasks": [],
        "snapshot": copy.deepcopy(dict(snapshot)),
    }


def daily_review_snapshot(
    store: HealthSidecarStore,
    subject: str,
    review_utc: str,
    timezone: str,
    *,
    retry_only: bool = False,
) -> Mapping[str, Any]:
    subject = subject.strip()
    if not subject:
        raise ProfileStoreError("subject-required")
    # The snapshot and a concurrent owner stop are linearized by the same
    # state lock.  A stop that completes first can therefore never be followed
    # by a stale health-bearing snapshot assembled from the previous state.
    with store._state_lock:
        profile = _profile_from_status(
            store.read_subject_status(subject, _allow_profile_state=True)
        )
        review_time, zone, local_date = _validate_review_time(
            store, review_utc, timezone, retry_only=retry_only
        )
        expected_zone = _profile_timezone(profile)
        if zone != expected_zone:
            raise ProfileStoreError("owner-timezone-mismatch")
        if profile.get("recording_status") == "recording_stopped":
            return _recording_stopped_snapshot(subject, review_time, zone)
        runs = [
            copy.deepcopy(dict(run))
            for run in profile.get("daily_review_runs", [])
            if isinstance(run, Mapping)
        ]
        current_run = next(
            (run for run in reversed(runs) if run.get("local_date") == local_date),
            None,
        )
        if current_run and current_run.get("status") == "completed":
            # The fixed Job may be invoked again by a scheduler recovery, but
            # that must not expose a new health snapshot or make another model
            # call after today's review already completed.
            return {
                "result": "already_completed",
                "attempt": current_run.get("attempt", 1),
                "created_tasks": [],
            }
        if current_run and current_run.get("status") == "failed":
            attempt = int(current_run.get("attempt", 0) or 0)
            retry_after_raw = current_run.get("retry_after_utc")
            if attempt != 1 or not isinstance(retry_after_raw, str):
                return {
                    "result": "retry_exhausted",
                    "attempt": attempt,
                    "created_tasks": [],
                }
            retry_after = _utc(retry_after_raw, "invalid-retry-time")
            now = store.now_utc().astimezone(dt.timezone.utc)
            if now < retry_after:
                return {
                    "result": "retry_not_due",
                    "attempt": attempt,
                    "retry_after_utc": retry_after.replace(microsecond=0).isoformat(),
                    "created_tasks": [],
                }
            if now > retry_after + DAILY_REVIEW_RETRY_GRACE:
                return {
                    "result": "retry_window_expired",
                    "attempt": attempt,
                    "created_tasks": [],
                }
        return _snapshot(store, subject, profile, review_time, zone)


def _unfinished(tasks: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [task for task in tasks if task.get("status") in TASK_STATUSES]


def _maintenance_plan(
    plan: Mapping[str, Any], source_library: Any | None
) -> dict[str, Any]:
    unknown = set(plan).difference(PLAN_FIELDS)
    if unknown:
        raise ProfileStoreError("daily-review-plan-fields-unsupported")
    raw = plan.get("maintenance", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ProfileStoreError("daily-review-maintenance-invalid")
    if set(raw).difference({"refresh_profile", "source_scan_candidates"}):
        raise ProfileStoreError("daily-review-maintenance-fields-unsupported")
    refresh_profile = raw.get("refresh_profile", True)
    if not isinstance(refresh_profile, bool):
        raise ProfileStoreError("daily-review-refresh-profile-invalid")
    candidates = raw.get("source_scan_candidates", [])
    if not isinstance(candidates, list) or not all(
        isinstance(item, str) and item.strip() for item in candidates
    ):
        raise ProfileStoreError("daily-review-source-candidates-invalid")
    if len(candidates) > 20:
        raise ProfileStoreError("daily-review-source-candidates-overflow")
    if candidates and source_library is None:
        raise ProfileStoreError("daily-review-source-library-unavailable")
    return {
        "refresh_profile": refresh_profile,
        "source_scan_candidates": list(dict.fromkeys(candidates)),
    }


def _refresh_profile_state(profile: Mapping[str, Any], now: dt.datetime) -> dict[str, Any]:
    updated = _profile_from_status(profile)
    conclusions = list(updated.get("conclusions", [])) + list(
        updated.get("deferred_conclusions", [])
    )
    _refresh_preference_lifecycle(conclusions, now)
    active = [
        item
        for item in conclusions
        if item.get("active", True) and not _expired(item, now)
    ]
    pending = [item for item in conclusions if not item.get("active", True)]
    compacted, summary, deferred = _compact_conclusions(active, now)
    updated["conclusions"] = compacted + pending
    updated["profile_summary_zh"] = summary
    updated["deferred_conclusions"] = deferred
    return updated


def _validate_task(
    task: Any,
    snapshot: Mapping[str, Any],
    profile: Mapping[str, Any],
    now: dt.datetime,
    *,
    allow_system_report: bool = False,
) -> dict[str, Any]:
    if not isinstance(task, Mapping):
        raise ProfileStoreError("daily-task-must-be-object")
    if _contains_final_copy(task):
        raise ProfileStoreError("daily-task-final-copy-forbidden")
    unknown = set(task).difference(TASK_FIELDS)
    if unknown:
        raise ProfileStoreError("daily-task-fields-unsupported")
    task_type = task.get("task_type")
    if task_type in FORBIDDEN_TASK_TYPES:
        raise ProfileStoreError("daily-task-type-forbidden")
    if task_type not in ALLOWED_TASK_TYPES:
        raise ProfileStoreError("daily-task-type-not-allowed")
    if task_type == WEEKLY_REPORT_TASK_TYPE and not allow_system_report:
        raise ProfileStoreError("weekly-report-system-generated")
    purpose = task.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 160:
        raise ProfileStoreError("daily-task-purpose-invalid")
    evidence_ids = task.get("evidence_ids")
    if (
        not isinstance(evidence_ids, list)
        or (task_type != WEEKLY_REPORT_TASK_TYPE and not evidence_ids)
        or not all(isinstance(item, str) and item.strip() for item in evidence_ids)
    ):
        raise ProfileStoreError("daily-task-evidence-required")
    valid_evidence_ids = {
        str(item.get("evidence_id"))
        for item in snapshot.get("evidence", [])
        if isinstance(item, Mapping)
    }
    if not set(evidence_ids).issubset(valid_evidence_ids):
        raise ProfileStoreError("daily-task-evidence-invalid")
    time_window = task.get("time_window")
    if not isinstance(time_window, Mapping):
        raise ProfileStoreError("daily-task-time-window-required")
    start = _utc(time_window.get("start_utc"), "daily-task-start-invalid")
    end = _utc(time_window.get("end_utc"), "daily-task-end-invalid")
    valid_until = _utc(task.get("valid_until_utc"), "daily-task-validity-invalid")
    if start < now or end <= start or valid_until < end:
        raise ProfileStoreError("daily-task-time-window-invalid")
    dedupe_key = task.get("dedupe_key")
    if not isinstance(dedupe_key, str) or not dedupe_key.strip() or len(dedupe_key) > 120:
        raise ProfileStoreError("daily-task-dedupe-key-invalid")
    topic_key = task.get("topic_key", dedupe_key)
    if not isinstance(topic_key, str) or not topic_key.strip() or len(topic_key) > 120:
        raise ProfileStoreError("daily-task-topic-key-invalid")
    timing_rationale = task.get("timing_rationale")
    if timing_rationale is not None and (
        not isinstance(timing_rationale, str)
        or not timing_rationale.strip()
        or len(timing_rationale) > 200
    ):
        raise ProfileStoreError("daily-task-timing-rationale-invalid")
    policy = task.get("policy_constraints")
    if not isinstance(policy, Mapping):
        raise ProfileStoreError("daily-task-policy-required")
    if any(
        bool(policy.get(key))
        for key in ("diagnosis", "medication_change", "external_notification")
    ):
        raise ProfileStoreError("daily-task-policy-forbidden")
    if task_type == "low_risk_reminder" and policy.get("low_risk") is not True:
        raise ProfileStoreError("low-risk-reminder-not-authorized")
    conclusion_keys = task.get("conclusion_keys", [])
    if not isinstance(conclusion_keys, list) or not all(
        isinstance(item, str) and item.strip() for item in conclusion_keys
    ):
        raise ProfileStoreError("daily-task-conclusions-invalid")
    conclusions = {
        str(item.get("dedupe_key")): item
        for item in profile.get("conclusions", [])
        if isinstance(item, Mapping) and item.get("dedupe_key")
    }
    if not set(conclusion_keys).issubset(conclusions):
        raise ProfileStoreError("daily-task-conclusion-invalid")
    source_card_ids = task.get("source_card_ids", [])
    if not isinstance(source_card_ids, list) or not all(
        isinstance(item, str) and item.strip() for item in source_card_ids
    ):
        raise ProfileStoreError("daily-task-source-cards-invalid")
    available_cards = {
        str(item.get("card_id"))
        for item in snapshot.get("source_cards", [])
        if isinstance(item, Mapping) and item.get("card_id")
    }
    if not set(source_card_ids).issubset(available_cards):
        raise ProfileStoreError("daily-task-source-card-invalid")
    if task_type == WEEKLY_REPORT_TASK_TYPE:
        recipient = task.get("recipient_sender_id")
        if not isinstance(recipient, str) or not recipient.strip():
            raise ProfileStoreError("weekly-report-recipient-required")
        if not any(
            isinstance(grant, Mapping)
            and grant.get("active", True)
            and grant.get("viewer_sender_id") == recipient.strip()
            and _REPORT_VIEW_PERMISSIONS.issubset(set(grant.get("permissions", [])))
            for grant in profile.get("viewer_grants", [])
        ):
            raise ProfileStoreError("weekly-report-recipient-unauthorized")
        report_id = task.get("report_id")
        report_to = task.get("report_to_version_id")
        report_refs = task.get("report_change_refs")
        if (
            not isinstance(report_id, str)
            or not report_id.strip()
            or not isinstance(report_to, str)
            or not report_to.strip()
            or not isinstance(report_refs, Mapping)
        ):
            raise ProfileStoreError("weekly-report-references-required")
        if _contains_final_copy(report_refs):
            raise ProfileStoreError("weekly-report-content-forbidden")
        normalized_report_refs = _validate_report_change_refs(report_refs)
        if normalized_report_refs["to_version_id"] not in (None, report_to.strip()):
            raise ProfileStoreError("weekly-report-version-reference-mismatch")
    elif any(
        task.get(field) is not None
        for field in (
            "recipient_sender_id",
            "report_id",
            "report_from_version_id",
            "report_to_version_id",
            "report_change_refs",
        )
    ):
        raise ProfileStoreError("weekly-report-fields-only")
    if task_type == "profile_completion_question":
        hypothesis_keys = [
            key
            for key in conclusion_keys
            if conclusions[key].get("status") == "unverified_hypothesis"
        ]
        if not hypothesis_keys:
            raise ProfileStoreError("completion-task-requires-hypothesis")
        if any(conclusions[key].get("completion_question_issued") for key in hypothesis_keys):
            raise ProfileStoreError("completion-question-already-issued")
        existing_tasks = _unfinished(
            [
                item
                for item in profile.get("tasks", [])
                if isinstance(item, Mapping)
            ]
        )
        if any(
            item.get("task_type") == "profile_completion_question"
            and set(hypothesis_keys).intersection(item.get("conclusion_keys", []))
            for item in existing_tasks
        ):
            raise ProfileStoreError("completion-question-already-issued")
    elif any(
        conclusions[key].get("status") == "unverified_hypothesis"
        for key in conclusion_keys
    ):
        raise ProfileStoreError("hypothesis-requires-completion-question")
    normalized_topic_key = _task_topic_key(
        {
            "conclusion_keys": list(dict.fromkeys(conclusion_keys)),
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "topic_key": topic_key.strip(),
            "dedupe_key": dedupe_key.strip(),
        }
    )
    if not normalized_topic_key:
        raise ProfileStoreError("daily-task-topic-key-invalid")
    normalized = {
        "task_type": task_type,
        "purpose": purpose.strip(),
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
        "conclusion_keys": list(dict.fromkeys(conclusion_keys)),
        "source_card_ids": list(dict.fromkeys(source_card_ids)),
        "time_window": {
            "start_utc": start.replace(microsecond=0).isoformat(),
            "end_utc": end.replace(microsecond=0).isoformat(),
        },
        "valid_until_utc": valid_until.replace(microsecond=0).isoformat(),
        "dedupe_key": dedupe_key.strip(),
        # The model may provide a label for display, but the backoff identity
        # is derived from verified evidence/conclusion references so a renamed
        # topic cannot evade the 72-hour unanswered-contact window.
        "topic_key": normalized_topic_key,
        "timing_rationale": timing_rationale.strip()
        if isinstance(timing_rationale, str)
        else None,
        "conclusion_last_evidence_utc": {
            key: str(conclusions[key].get("last_evidence_utc"))
            for key in conclusion_keys
            if key in conclusions and conclusions[key].get("last_evidence_utc")
        },
        "policy_constraints": copy.deepcopy(dict(policy)),
    }
    if task_type == WEEKLY_REPORT_TASK_TYPE:
        normalized.update(
            {
                "recipient_sender_id": recipient.strip(),
                "report_id": report_id.strip(),
                "report_from_version_id": (
                    task.get("report_from_version_id").strip()
                    if isinstance(task.get("report_from_version_id"), str)
                    and task.get("report_from_version_id").strip()
                    else None
                ),
                "report_to_version_id": report_to.strip(),
                "report_change_refs": normalized_report_refs,
            }
        )
    return normalized


def _failure_result(
    snapshot: Mapping[str, Any], attempt: int, reason: str, retry_after: dt.datetime | None
) -> dict[str, Any]:
    return {
        "result": "failed",
        "attempt": attempt,
        "reason": reason,
        "retry_after_utc": retry_after.replace(microsecond=0).isoformat()
        if retry_after
        else None,
        "created_tasks": [],
        "snapshot": copy.deepcopy(dict(snapshot)),
    }


def expire_daily_review_retry(
    store: HealthSidecarStore,
    subject: str,
    review_utc: str,
    timezone: str,
) -> Mapping[str, Any]:
    """Terminally record a retry that missed the tightly bounded +10m window.

    This path makes no snapshot and no model call. It exists so a sidecar or
    Gateway outage cannot be converted into a late same-day health decision.
    """
    subject = subject.strip()
    if not subject:
        raise ProfileStoreError("subject-required")
    review_time, zone, local_date = _validate_review_time(
        store, review_utc, timezone, retry_only=True
    )
    now = store.now_utc().astimezone(dt.timezone.utc)

    def record_expiry(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], None]:
        updated = _profile_from_status(current)
        if updated.get("recording_status") == "recording_stopped":
            raise ProfileStoreError("health-recording-stopped")
        if _profile_timezone(updated) != zone:
            raise ProfileStoreError("owner-timezone-mismatch")
        runs = [
            copy.deepcopy(dict(run))
            for run in updated.get("daily_review_runs", [])
            if isinstance(run, Mapping)
        ]
        prior = next(
            (run for run in reversed(runs) if run.get("local_date") == local_date),
            None,
        )
        if not isinstance(prior, Mapping):
            raise ProfileStoreError("daily-review-retry-missing")
        if prior.get("status") != "failed" or int(prior.get("attempt", 0) or 0) != 1:
            raise ProfileStoreError("daily-review-retry-not-pending")
        retry_after = _utc(prior.get("retry_after_utc"), "invalid-retry-time")
        if now <= retry_after + DAILY_REVIEW_RETRY_GRACE:
            raise ProfileStoreError("daily-review-retry-window-open")
        history = [run for run in runs if run.get("local_date") != local_date]
        history.append(
            {
                "run_id": f"review-{uuid.uuid4().hex}",
                "local_date": local_date,
                "review_utc": review_time.replace(microsecond=0).isoformat(),
                "status": "failed",
                "attempt": 2,
                "reason": "daily-review-retry-window-expired",
                "retry_after_utc": None,
                "finished_utc": now.replace(microsecond=0).isoformat(),
            }
        )
        updated["daily_review_runs"] = history[-31:]
        return updated, None

    def audit_builder(_: None) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        return (
            (
                "daily_review_failed",
                {
                    "subject": subject,
                    "local_date": local_date,
                    "attempt": 2,
                    "actor_role": "daily-review",
                    "action": "health.daily_review",
                    "object_id": local_date,
                    "result": "failed",
                    "reason": "daily-review-retry-window-expired",
                },
            ),
        )

    try:
        store.mutate_subject_status(subject, record_expiry, audit_builder=audit_builder)
    except ProfileStoreError as exc:
        if str(exc) != "health-recording-stopped":
            raise
        return {
            "result": "recording_stopped",
            "attempt": 0,
            "created_tasks": [],
        }
    return {
        "result": "retry_window_expired",
        "attempt": 2,
        "created_tasks": [],
    }


def run_daily_review(
    store: HealthSidecarStore,
    subject: str,
    review_utc: str,
    timezone: str,
    plan: Mapping[str, Any],
    source_library: Any | None = None,
    *,
    retry_only: bool = False,
) -> Mapping[str, Any]:
    subject = subject.strip()
    if not subject:
        raise ProfileStoreError("subject-required")
    profile = _profile_from_status(
        store.read_subject_status(subject, _allow_profile_state=True)
    )
    review_time, zone, local_date = _validate_review_time(
        store, review_utc, timezone, retry_only=retry_only
    )
    if zone != _profile_timezone(profile):
        raise ProfileStoreError("owner-timezone-mismatch")
    if profile.get("recording_status") == "recording_stopped":
        return _recording_stopped_result(
            _recording_stopped_snapshot(subject, review_time, zone)
        )
    snapshot = _snapshot(store, subject, profile, review_time, zone)
    now = store.now_utc().astimezone(dt.timezone.utc)
    maintenance: dict[str, Any] = {
        "refresh_profile": True,
        "source_scan_candidates": [],
    }
    source_scan_result: Mapping[str, Any] | None = None
    preflight_failure: str | None = None
    runs = [
        copy.deepcopy(dict(run))
        for run in profile.get("daily_review_runs", [])
        if isinstance(run, Mapping)
    ]
    current_run = next(
        (run for run in reversed(runs) if run.get("local_date") == local_date), None
    )
    if current_run and current_run.get("status") == "completed":
        return {
            "result": "already_completed",
            "attempt": current_run.get("attempt", 1),
            "created_tasks": [],
            "snapshot": snapshot,
        }
    attempt = int(current_run.get("attempt", 0)) + 1 if current_run else 1
    if current_run and current_run.get("retry_after_utc"):
        retry_after = _utc(current_run["retry_after_utc"], "invalid-retry-time")
        if now < retry_after:
            return {
                "result": "retry_not_due",
                "attempt": current_run.get("attempt", 1),
                "retry_after_utc": retry_after.replace(microsecond=0).isoformat(),
                "created_tasks": [],
                "snapshot": snapshot,
            }
        if now > retry_after + DAILY_REVIEW_RETRY_GRACE:
            return {
                "result": "retry_window_expired",
                "attempt": current_run.get("attempt", 1),
                "created_tasks": [],
                "snapshot": snapshot,
            }
    if attempt > 2:
        return _failure_result(snapshot, attempt, "daily-review-retry-exhausted", None)

    if isinstance(plan, Mapping):
        try:
            maintenance = _maintenance_plan(plan, source_library)
            candidates = maintenance["source_scan_candidates"]
            if candidates:
                def recording_active() -> bool:
                    live = _profile_from_status(
                        store.read_subject_status(
                            subject, _allow_profile_state=True
                        )
                    )
                    return live.get("recording_status") != "recording_stopped"

                with store._state_lock:
                    if not recording_active():
                        return _recording_stopped_result(
                            _recording_stopped_snapshot(subject, review_time, zone)
                        )
                source_scan_result = source_library.scan(
                    candidates,
                    continue_check=recording_active,
                )
                # A model-proposed source candidate is not optional evidence
                # once the plan asks the sidecar to retrieve it. A rejected
                # whitelist fetch must take the daily failure/retry route,
                # never leave a seemingly successful task plan behind.
                if source_scan_result.get("rejected"):
                    raise ProfileStoreError("daily-review-source-failure")
                with store._state_lock:
                    if not recording_active():
                        return _recording_stopped_result(
                            _recording_stopped_snapshot(subject, review_time, zone)
                        )
                    live_profile = _profile_from_status(
                        store.read_subject_status(
                            subject, _allow_profile_state=True
                        )
                    )
                    snapshot = _snapshot(
                        store, subject, live_profile, review_time, zone
                    )
        except (ProfileStoreError, StoreError) as exc:
            if str(exc) == "health-recording-stopped":
                return _recording_stopped_result(
                    _recording_stopped_snapshot(subject, review_time, zone)
                )
            preflight_failure = str(exc)

    proactive = profile.get("proactive_contact", {})
    try:
        paused = (
            profile.get("recording_status") == "recording_stopped"
            or _proactive_pause_active(proactive, now)
        )
    except ProfileStoreError:
        paused = True
    outcome = "no_action" if paused else (plan.get("outcome") if isinstance(plan, Mapping) else None)
    failure_reason: str | None = preflight_failure
    validated_tasks: list[dict[str, Any]] = []
    deferred_tasks: list[dict[str, str]] = []
    result_reason: str | None = "proactive-contact-paused" if paused else None
    if not paused and isinstance(plan, Mapping):
        plan_reason = plan.get("reason")
        if isinstance(plan_reason, str) and plan_reason.strip() and len(plan_reason) <= 200:
            result_reason = plan_reason.strip()
    try:
        if failure_reason:
            pass
        elif paused:
            pass
        elif not isinstance(plan, Mapping):
            raise ProfileStoreError("daily-review-plan-must-be-object")
        elif outcome == "failure":
            # The model may report a useful internal reason, but it must never
            # become content-bearing audit data.  Keep the external result
            # deterministic and content-free.
            failure_reason = "daily-review-model-failure"
        elif outcome == "no_action":
            if plan.get("tasks") not in (None, []):
                raise ProfileStoreError("no-action-cannot-carry-tasks")
        elif outcome == "tasks":
            raw_tasks = plan.get("tasks")
            if not isinstance(raw_tasks, list):
                raise ProfileStoreError("daily-task-list-required")
            completion_hypotheses: set[str] = set()
            for raw_task in raw_tasks:
                validated = _validate_task(raw_task, snapshot, profile, now)
                purpose = validated["purpose"]
                if any(
                    isinstance(existing, Mapping)
                    and existing.get("status") in TASK_STATUSES
                    and str(existing.get("purpose", "")).strip() == purpose
                    for existing in profile.get("tasks", [])
                ):
                    deferred_tasks.append(
                        {
                            "dedupe_key": validated["dedupe_key"],
                            "topic_key": validated["topic_key"],
                            "reason": "unfinished-purpose",
                        }
                    )
                    continue
                if _unanswered_topic_blocked(profile, validated, now):
                    deferred_tasks.append(
                        {
                            "dedupe_key": validated["dedupe_key"],
                            "topic_key": validated["topic_key"],
                            "reason": "unanswered-topic-backoff",
                        }
                    )
                    continue
                if validated["task_type"] == "profile_completion_question":
                    duplicate_hypotheses = completion_hypotheses.intersection(
                        validated["conclusion_keys"]
                    )
                    if duplicate_hypotheses:
                        raise ProfileStoreError("completion-question-already-issued")
                    completion_hypotheses.update(validated["conclusion_keys"])
                validated_tasks.append(validated)
        else:
            raise ProfileStoreError("daily-review-outcome-invalid")
    except ProfileStoreError as exc:
        failure_reason = str(exc)

    if not failure_reason and not paused:
        try:
            for report_task in _weekly_report_candidates(
                store, subject, profile, review_time, zone, now
            ):
                validated_tasks.append(
                    _validate_task(
                        report_task,
                        snapshot,
                        profile,
                        now,
                        allow_system_report=True,
                    )
                )
        except ProfileStoreError as exc:
            failure_reason = str(exc)

    if failure_reason:
        # A recovery is tied to this owner-local 04:00 review, not to the
        # eventual time at which a slow provider happened to fail.  Otherwise
        # a delayed first attempt could silently move the one permitted retry
        # to 04:16/04:20 and become a second catch-up schedule.
        retry_after = (
            review_time + DAILY_REVIEW_RETRY_DELAY
            if attempt == 1
            and now <= review_time + DAILY_REVIEW_RETRY_DELAY + DAILY_REVIEW_RETRY_GRACE
            else None
        )
        result = _failure_result(snapshot, attempt, failure_reason, retry_after)
        if source_scan_result is not None:
            result["source_scan"] = copy.deepcopy(dict(source_scan_result))

        def record_failure(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], None]:
            updated = _profile_from_status(current)
            if updated.get("recording_status") == "recording_stopped":
                raise ProfileStoreError("health-recording-stopped")
            history = [
                item
                for item in updated.get("daily_review_runs", [])
                if item.get("local_date") != local_date
            ]
            history.append(
                {
                    "run_id": f"review-{uuid.uuid4().hex}",
                    "local_date": local_date,
                    "review_utc": review_time.replace(microsecond=0).isoformat(),
                    "status": "failed",
                    "attempt": attempt,
                    "reason": failure_reason,
                    "retry_after_utc": result["retry_after_utc"],
                    "finished_utc": now.replace(microsecond=0).isoformat(),
                }
            )
            updated["daily_review_runs"] = history[-31:]
            return updated, None

        def failure_audit_builder(
            _: None,
        ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
            return (
                (
                    "daily_review_failed",
                    {
                        "subject": subject,
                        "local_date": local_date,
                        "attempt": attempt,
                        "actor_role": "daily-review",
                        "action": "health.daily_review",
                        "object_id": local_date,
                        "result": "failed",
                        "reason": "daily-review-failed",
                    },
                ),
            )

        try:
            store.mutate_subject_status(
                subject,
                record_failure,
                audit_builder=failure_audit_builder,
            )
        except ProfileStoreError as exc:
            if str(exc) != "health-recording-stopped":
                raise
            return _recording_stopped_result(
                _recording_stopped_snapshot(subject, review_time, zone)
            )
        return result

    existing_tasks = [
        copy.deepcopy(dict(task))
        for task in profile.get("tasks", [])
        if isinstance(task, Mapping)
    ]
    existing_dedupe = {
        str(task.get("dedupe_key"))
        for task in _unfinished(existing_tasks)
        if task.get("dedupe_key")
    }
    existing_purposes = {
        str(task.get("purpose")).strip()
        for task in _unfinished(existing_tasks)
        if isinstance(task.get("purpose"), str) and task.get("purpose").strip()
    }
    created: list[dict[str, Any]] = []
    run_id = f"review-{uuid.uuid4().hex}"
    for task in validated_tasks:
        if (
            task["dedupe_key"] in existing_dedupe
            or task["purpose"] in existing_purposes
            or any(
                item["dedupe_key"] == task["dedupe_key"]
                or item["purpose"] == task["purpose"]
                for item in created
            )
        ):
            continue
        created.append(
            {
                "task_id": f"task-{uuid.uuid4().hex}",
                **task,
                "status": "candidate",
                "created_utc": now.replace(microsecond=0).isoformat(),
                "review_local_date": local_date,
                "review_run_id": run_id,
                "cancel_reason": None,
                "dispatch_attempts": 0,
                "retry_after_utc": None,
                "failure_code": None,
                "dispatch_claim_id": None,
                "dispatch_claimed_utc": None,
                "delivery_key": None,
                "updated_utc": now.replace(microsecond=0).isoformat(),
            }
        )
    result_name = "tasks_created" if created else "no_action"
    if not created and deferred_tasks and result_reason is None:
        result_reason = deferred_tasks[0]["reason"]

    def record_success(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], None]:
        updated = _profile_from_status(current)
        if updated.get("recording_status") == "recording_stopped":
            raise ProfileStoreError("health-recording-stopped")
        if maintenance["refresh_profile"]:
            updated = _refresh_profile_state(updated, now)
        completion_keys = {
            key
            for task in created
            if task["task_type"] == "profile_completion_question"
            for key in task["conclusion_keys"]
        }
        if completion_keys:
            for collection_name in ("conclusions", "deferred_conclusions"):
                updated[collection_name] = [
                    {
                        **dict(item),
                        "completion_question_issued": True,
                    }
                    if isinstance(item, Mapping)
                    and item.get("dedupe_key") in completion_keys
                    else item
                    for item in updated.get(collection_name, [])
                ]
        reports = copy.deepcopy(list(updated.get("reports", [])))
        existing_report_ids = {
            str(item.get("report_id"))
            for item in reports
            if isinstance(item, Mapping) and item.get("report_id")
        }
        for task in created:
            if task.get("task_type") != WEEKLY_REPORT_TASK_TYPE:
                continue
            report_id = str(task["report_id"])
            if report_id in existing_report_ids:
                continue
            reports.append(
                {
                    "report_id": report_id,
                    "task_id": task["task_id"],
                    "recipient_sender_id": task["recipient_sender_id"],
                    "from_version_id": task.get("report_from_version_id"),
                    "to_version_id": task["report_to_version_id"],
                    "change_refs": copy.deepcopy(task["report_change_refs"]),
                    "status": "scheduled",
                    "created_utc": now.replace(microsecond=0).isoformat(),
                    "sent_utc": None,
                }
            )
        updated["reports"] = reports
        updated["tasks"] = [*updated.get("tasks", []), *created]
        history = [
            item
            for item in updated.get("daily_review_runs", [])
            if item.get("local_date") != local_date
        ]
        history.append(
            {
                "run_id": run_id,
                "local_date": local_date,
                "review_utc": review_time.replace(microsecond=0).isoformat(),
                "status": "completed",
                "attempt": attempt,
                "outcome": result_name,
                "reason": result_reason,
                "task_ids": [task["task_id"] for task in created],
                "deferred_task_count": len(deferred_tasks),
                "finished_utc": now.replace(microsecond=0).isoformat(),
            }
        )
        updated["daily_review_runs"] = history[-31:]
        return updated, None

    def success_audit_builder(
        _: None,
    ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        return (
            (
                "daily_review_completed",
                {
                    "subject": subject,
                    "local_date": local_date,
                    "attempt": attempt,
                    "actor_role": "daily-review",
                    "action": "health.daily_review",
                    "object_id": local_date,
                    "result": result_name,
                    "task_count": len(created),
                },
            ),
            *(
                (
                    "derived_task_created",
                    {
                        "subject": subject,
                        "task_id": task["task_id"],
                        "task_type": task["task_type"],
                        "actor_role": "daily-review",
                        "action": "health.task.create",
                        "object_id": task["task_id"],
                        "result": "created",
                        "evidence_ids": list(task["evidence_ids"]),
                    },
                )
                for task in created
            ),
        )

    try:
        store.mutate_subject_status(
            subject,
            record_success,
            audit_builder=success_audit_builder,
        )
    except ProfileStoreError as exc:
        if str(exc) != "health-recording-stopped":
            raise
        return _recording_stopped_result(
            _recording_stopped_snapshot(subject, review_time, zone)
        )
    result = {
        "result": result_name,
        "attempt": attempt,
        "created_tasks": copy.deepcopy(created),
        "deferred_tasks": copy.deepcopy(deferred_tasks),
        "snapshot": snapshot,
        "maintenance": {
            "profile_refreshed": bool(maintenance["refresh_profile"]),
            "source_scan": copy.deepcopy(dict(source_scan_result))
            if source_scan_result is not None
            else None,
        },
    }
    if result_reason:
        result["reason"] = result_reason
    return result

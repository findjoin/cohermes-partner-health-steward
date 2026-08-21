"""Render and dispatch due derived tasks from a current health snapshot."""

from __future__ import annotations

import copy
import datetime as dt
import uuid
from contextlib import contextmanager
from typing import Any, Mapping

from .profile import ProfileStoreError, _expired, _profile_from_status
from .store import HealthSidecarStore
from .weixin_delivery import ChannelSendUncertainError
from .tasks import (
    TASK_STATUSES,
    _is_night_local,
    _profile_timezone,
    _proactive_pause_active,
    _unanswered_topic_blocked,
    _utc,
    _valid_evidence,
    WEEKLY_REPORT_TASK_TYPE,
)


DISPATCH_RETRY_DELAY = dt.timedelta(minutes=15)
DISPATCH_CLOCK_SKEW = dt.timedelta(minutes=1)
DISPATCH_CLAIM_LEASE = dt.timedelta(minutes=10)
AUTOMATIC_MESSAGE_WINDOW = dt.timedelta(hours=24)
MAX_AUTOMATIC_MESSAGES_24H = 100
RENDERABLE_STATUSES = {"candidate", "scheduled", "due_for_render"}
_CLAIM_UNCHECKED = object()
MAX_RENDER_MESSAGE_CHARS = 2000
RENDER_PROMPT = (
    "Render exactly one decision for this due health task. Return a JSON object "
    "with decision='send' or decision='skip'. A send must include only a current "
    "message and a short reason; a skip must include a short reason and no message. "
    "The health snapshot is authoritative; do not modify profile, sources, tasks, "
    "memory, or Cron."
)
REPORT_RENDER_PROMPT = (
    "Render one weekly profile-difference report decision from context.report. "
    "Return a JSON object with decision='send' or decision='skip'. A send may "
    "contain only summary='...' and reference_ids=[...] from the supplied "
    "change references; never reconstruct profile text, evidence excerpts, or "
    "chat history. If the change references are empty, skip with exactly "
    "reason='no-substantive-change'."
)


def _safe_reason(code: str) -> str:
    return code if code and code.replace("-", "").isalnum() else "dispatch-failed"


def _current_time(store: HealthSidecarStore, value: Any) -> dt.datetime:
    provided = _utc(value, "invalid-dispatch-utc")
    current = store.now_utc().astimezone(dt.timezone.utc)
    if abs(provided - current) > DISPATCH_CLOCK_SKEW:
        raise ProfileStoreError("dispatch-time-mismatch")
    return current.replace(microsecond=0)


def _parse_optional_utc(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    try:
        return _utc(value, "invalid-task-time")
    except ProfileStoreError:
        return None


def _source_cards(
    store: HealthSidecarStore, source_library: Any | None = None
) -> dict[str, dict[str, Any]]:
    def read() -> dict[str, dict[str, Any]]:
        state = store.read_source_library_state() or {}
        return {
            str(card.get("card_id")): copy.deepcopy(dict(card))
            for card in state.get("cards", [])
            if isinstance(card, Mapping) and card.get("card_id")
        }

    if source_library is not None and getattr(source_library, "store", None) is store:
        with store.source_library_lock():
            return read()
    return read()


def _automatic_message_count(
    profile: Mapping[str, Any], now: dt.datetime
) -> int:
    cutoff = now - AUTOMATIC_MESSAGE_WINDOW
    count = 0
    for task in profile.get("tasks", []):
        if not isinstance(task, Mapping) or task.get("status") != "sent":
            continue
        sent_utc = _parse_optional_utc(task.get("sent_utc"))
        if sent_utc is not None and cutoff < sent_utc <= now:
            count += 1
    return count


@contextmanager
def _dispatch_critical_section(
    store: HealthSidecarStore, source_library: Any | None
):
    """Use the same source-lock -> state-lock order as SourceLibrary writes."""
    if source_library is not None and getattr(source_library, "store", None) is store:
        with store.source_library_lock():
            with store.dispatch_lock():
                yield
        return
    with store.dispatch_lock():
        yield


def _task_snapshot(
    store: HealthSidecarStore,
    subject: str,
    profile: Mapping[str, Any],
    task: Mapping[str, Any],
    now: dt.datetime,
    source_cards: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    evidence = _valid_evidence(profile, now)
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in evidence
        if item.get("evidence_id")
    }
    conclusion_by_key = {
        str(item.get("dedupe_key")): item
        for item in profile.get("conclusions", [])
        if isinstance(item, Mapping) and item.get("dedupe_key")
    }
    evidence_ids = [str(item) for item in task.get("evidence_ids", [])]
    conclusion_keys = [str(item) for item in task.get("conclusion_keys", [])]
    source_card_ids = [str(item) for item in task.get("source_card_ids", [])]
    preferences = [
        copy.deepcopy(dict(item))
        for item in profile.get("conclusions", [])
        if isinstance(item, Mapping)
        and item.get("category") == "interaction_preference"
        and item.get("active", True)
        and not _expired(item, now)
    ]
    snapshot = {
        "subject": subject,
        "task": {
            key: copy.deepcopy(task[key])
            for key in (
                "task_id",
                "task_type",
                "purpose",
                "time_window",
                "valid_until_utc",
                "evidence_ids",
                "conclusion_keys",
                "source_card_ids",
                "policy_constraints",
                "topic_key",
                "timing_rationale",
                "owner_reply_utc",
                "conclusion_last_evidence_utc",
                "recipient_sender_id",
                "report_id",
                "report_from_version_id",
                "report_to_version_id",
                "report_change_refs",
            )
            if key in task
        },
        "profile": {
            "profile_summary_zh": str(profile.get("profile_summary_zh", "")),
            "conclusions": [
                copy.deepcopy(dict(conclusion_by_key[key]))
                for key in conclusion_keys
                if key in conclusion_by_key
            ],
        },
        "evidence": [
            copy.deepcopy(evidence_by_id[key])
            for key in evidence_ids
            if key in evidence_by_id
        ],
        "source_cards": [
            copy.deepcopy(dict(source_cards[key]))
            for key in source_card_ids
            if key in source_cards
        ],
        "authorized_preferences": preferences,
        "recent_messages": store.recent_profile_messages(
            subject, str(profile.get("owner_sender_id"))
        )[-3:],
        "authorization": {
            "owner_bound": bool(profile.get("owner_sender_id")),
            "proactive_contact": copy.deepcopy(
                dict(profile.get("proactive_contact", {}))
                if isinstance(profile.get("proactive_contact", {}), Mapping)
                else {}
            ),
        },
        "now_utc": now.isoformat(),
    }
    if task.get("task_type") == WEEKLY_REPORT_TASK_TYPE:
        snapshot["report"] = {
            "report_id": task.get("report_id"),
            "recipient_sender_id": task.get("recipient_sender_id"),
            "from_version_id": task.get("report_from_version_id"),
            "to_version_id": task.get("report_to_version_id"),
            "change_refs": copy.deepcopy(task.get("report_change_refs", {})),
        }
        # A report render receives references only. It must not receive the
        # compact profile, evidence excerpts, or the ephemeral chat window.
        snapshot["profile"] = {
            "current_version_id": profile.get("current_version_id"),
        }
        snapshot["evidence"] = []
        snapshot["source_cards"] = []
        snapshot["authorized_preferences"] = []
        snapshot["recent_messages"] = []
    return snapshot


def _skip_reason(
    profile: Mapping[str, Any],
    task: Mapping[str, Any],
    now: dt.datetime,
    source_cards: Mapping[str, Mapping[str, Any]],
    expected_viewer_sender_id: str = "",
) -> str | None:
    if not profile.get("owner_sender_id"):
        return "authorization-invalid"
    if profile.get("recording_status") == "recording_stopped":
        return "health-recording-stopped"
    proactive = profile.get("proactive_contact", {})
    try:
        paused = _proactive_pause_active(proactive, now)
    except ProfileStoreError:
        return "authorization-invalid"
    if paused:
        return "proactive-contact-paused"
    if _automatic_message_count(profile, now) >= MAX_AUTOMATIC_MESSAGES_24H:
        return "capacity_exhausted"
    if task.get("task_type") == WEEKLY_REPORT_TASK_TYPE:
        recipient = str(task.get("recipient_sender_id", "")).strip()
        if (
            not recipient
            or (
                expected_viewer_sender_id
                and (
                    recipient != expected_viewer_sender_id
                    or profile.get("viewer_configuration_sender_id")
                    != expected_viewer_sender_id
                )
            )
            or not any(
                isinstance(grant, Mapping)
                and grant.get("active", True)
                and grant.get("viewer_sender_id") == recipient
                and {
                    "profile",
                    "evidence",
                    "tasks",
                    "reports",
                    "audit",
                }.issubset(set(grant.get("permissions", [])))
                for grant in profile.get("viewer_grants", [])
            )
        ):
            return "report-authorization-invalid"
        if not isinstance(task.get("report_change_refs"), Mapping):
            return "report-invalid"
    valid_until = _parse_optional_utc(task.get("valid_until_utc"))
    if valid_until is None or valid_until <= now:
        return "task-expired"
    window = task.get("time_window")
    if not isinstance(window, Mapping):
        return "task-invalid"
    start = _parse_optional_utc(window.get("start_utc"))
    end = _parse_optional_utc(window.get("end_utc"))
    if start is None or end is None or end <= start:
        return "task-invalid"
    if end <= now:
        return "task-window-expired"
    if _is_night_local(now, _profile_timezone(profile)) and not str(
        task.get("timing_rationale") or ""
    ).strip():
        return "night-timing-rationale-missing"
    evidence_ids = {str(item.get("evidence_id")) for item in _valid_evidence(profile, now)}
    if not set(task.get("evidence_ids", [])).issubset(evidence_ids):
        return "evidence-invalid"
    conclusions = {
        str(item.get("dedupe_key")): item
        for item in profile.get("conclusions", [])
        if isinstance(item, Mapping) and item.get("dedupe_key")
    }
    for key in task.get("conclusion_keys", []):
        conclusion = conclusions.get(str(key))
        if conclusion is None or not conclusion.get("active", True) or _expired(conclusion, now):
            return "conclusion-invalid"
        recorded_evidence_time = dict(
            task.get("conclusion_last_evidence_utc", {})
        ).get(str(key))
        if (
            recorded_evidence_time
            and str(conclusion.get("last_evidence_utc")) != str(recorded_evidence_time)
        ):
            return "conclusion-superseded"
        if (
            conclusion.get("status") == "unverified_hypothesis"
            and task.get("task_type") != "profile_completion_question"
        ):
            return "conclusion-unverified"
    if _unanswered_topic_blocked(profile, task, now):
        return "unanswered-topic-backoff"
    task_id = str(task.get("task_id", ""))
    dedupe_key = task.get("dedupe_key")
    if dedupe_key:
        for other in profile.get("tasks", []):
            if not isinstance(other, Mapping) or other.get("task_id") == task_id:
                continue
            if (
                other.get("status") in TASK_STATUSES
                and other.get("dedupe_key") == dedupe_key
            ):
                return "duplicate-task"
            if (
                other.get("status") in TASK_STATUSES
                and str(other.get("purpose", "")).strip()
                == str(task.get("purpose", "")).strip()
            ):
                return "duplicate-purpose"
    for card_id in task.get("source_card_ids", []):
        card = source_cards.get(str(card_id))
        if card is None or not card.get("current", True):
            return "source-card-stale"
        due = _parse_optional_utc(card.get("review_due_utc"))
        if due is not None and due <= now:
            return "source-card-stale"
    return None


def _validate_render_result(value: Any) -> tuple[str, str | None, str] | None:
    if not isinstance(value, Mapping):
        return None
    if set(value).difference({"decision", "message", "reason"}):
        return None
    decision = value.get("decision")
    reason = value.get("reason")
    if decision not in {"send", "skip"}:
        return None
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
        return None
    reason = reason.strip()
    if decision == "skip":
        if "message" in value:
            return None
        return "skip", None, reason
    message = value.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_RENDER_MESSAGE_CHARS:
        return None
    return "send", message.strip(), reason


def _validate_report_render_result(
    value: Any, task: Mapping[str, Any]
) -> tuple[str, str | None, str] | None:
    """Validate a report decision and construct its bounded channel body."""
    if not isinstance(value, Mapping) or set(value).difference(
        {"decision", "summary", "reference_ids", "reason"}
    ):
        return None
    decision = value.get("decision")
    reason = value.get("reason")
    if decision not in {"send", "skip"}:
        return None
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
        return None
    reason = reason.strip()
    refs = task.get("report_change_refs")
    if not isinstance(refs, Mapping):
        return None
    known_refs: set[str] = set()
    for field in (
        "added_conclusion_keys",
        "removed_conclusion_keys",
        "changed_conclusion_keys",
        "evidence_added_ids",
        "evidence_revoked_ids",
    ):
        known_refs.update(
            item.strip()
            for item in refs.get(field, [])
            if isinstance(item, str) and item.strip()
        )
    for field in (
        "task_event_refs",
        "authorization_event_refs",
        "deletion_event_refs",
        "daily_review_failure_refs",
        "audit_refs",
    ):
        known_refs.update(
            str(item.get("ref")).strip()
            for item in refs.get(field, [])
            if isinstance(item, Mapping) and str(item.get("ref", "")).strip()
        )
    for field in ("from_version_id", "to_version_id"):
        value_ref = refs.get(field)
        if isinstance(value_ref, str) and value_ref.strip():
            known_refs.add(value_ref.strip())
    substantive = any(
        bool(refs.get(field))
        for field in (
            "added_conclusion_keys",
            "removed_conclusion_keys",
            "changed_conclusion_keys",
            "profile_summary_changed",
            "evidence_added_ids",
            "evidence_revoked_ids",
            "task_event_refs",
            "authorization_event_refs",
            "deletion_event_refs",
            "daily_review_failure_refs",
        )
    )
    if decision == "skip":
        if any(key in value for key in ("summary", "reference_ids")):
            return None
        if not substantive and reason != "no-substantive-change":
            return None
        return "skip", None, reason
    summary = value.get("summary")
    reference_ids = value.get("reference_ids")
    if (
        not substantive
        or not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > 1000
        or not isinstance(reference_ids, list)
        or not reference_ids
        or len(reference_ids) > 20
        or not all(
            isinstance(item, str)
            and item.strip()
            and item.strip() in known_refs
            for item in reference_ids
        )
    ):
        return None
    normalized_refs = list(dict.fromkeys(item.strip() for item in reference_ids))
    message = f"{summary.strip()}\nReferences: {', '.join(normalized_refs)}"
    if len(message) > MAX_RENDER_MESSAGE_CHARS:
        return None
    return "send", message, reason


def _mutate_task(
    store: HealthSidecarStore,
    subject: str,
    task_id: str,
    updates: Mapping[str, Any],
    *,
    expected_statuses: set[str] | None = None,
    expected_claim_id: str | None | object = _CLAIM_UNCHECKED,
    audit_event: tuple[str, Mapping[str, Any]] | None = None,
) -> Mapping[str, Any] | None:
    def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        profile = _profile_from_status(current)
        tasks = copy.deepcopy(list(profile.get("tasks", [])))
        found = False
        updated_task: dict[str, Any] | None = None
        for index, item in enumerate(tasks):
            if isinstance(item, Mapping) and item.get("task_id") == task_id:
                updated_task = {**dict(item), **copy.deepcopy(dict(updates))}
                tasks[index] = updated_task
                found = True
                break
        if not found or updated_task is None:
            raise ProfileStoreError("task-not-found")
        profile["tasks"] = tasks
        report_id = updated_task.get("report_id")
        if report_id:
            reports = copy.deepcopy(list(profile.get("reports", [])))
            for report_index, report in enumerate(reports):
                if not isinstance(report, Mapping) or report.get("report_id") != report_id:
                    continue
                report_update = dict(report)
                report_update["status"] = updated_task.get("status")
                if updated_task.get("sent_utc"):
                    report_update["sent_utc"] = updated_task.get("sent_utc")
                if updated_task.get("skip_reason"):
                    report_update["skip_reason"] = updated_task.get("skip_reason")
                if updated_task.get("failure_code"):
                    report_update["failure_code"] = updated_task.get("failure_code")
                reports[report_index] = report_update
            profile["reports"] = reports
        return profile, copy.deepcopy(updated_task)

    with store._state_lock:
        current = _profile_from_status(
            store.read_subject_status(subject, _allow_profile_state=True)
        )
        if current.get("recording_status") == "recording_stopped":
            return None
        current_task = next(
            (
                item
                for item in current.get("tasks", [])
                if isinstance(item, Mapping) and item.get("task_id") == task_id
            ),
            None,
        )
        if current_task is None:
            return None
        if (
            expected_statuses is not None
            and current_task.get("status") not in expected_statuses
        ):
            return None
        if (
            expected_claim_id is not _CLAIM_UNCHECKED
            and current_task.get("dispatch_claim_id") != expected_claim_id
        ):
            return None

        def audit_builder(_result):
            return (audit_event,) if audit_event is not None else ()

        return store.mutate_subject_status(
            subject,
            mutate,
            audit_builder=audit_builder if audit_event is not None else None,
        )


def _claim_task(
    store: HealthSidecarStore,
    subject: str,
    task_id: str,
    now: dt.datetime,
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    claim_id = uuid.uuid4().hex
    claimed: tuple[Mapping[str, Any], Mapping[str, Any]] | None = None

    def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], None]:
        nonlocal claimed
        profile = _profile_from_status(current)
        tasks = copy.deepcopy(list(profile.get("tasks", [])))
        for index, item in enumerate(tasks):
            if not isinstance(item, Mapping) or item.get("task_id") != task_id:
                continue
            task = dict(item)
            if task.get("status") not in RENDERABLE_STATUSES:
                return profile, None
            retry_after = _parse_optional_utc(task.get("retry_after_utc"))
            if retry_after is not None and retry_after > now:
                return profile, None
            existing_claim = str(task.get("dispatch_claim_id") or "")
            claimed_at = _parse_optional_utc(task.get("dispatch_claimed_utc"))
            if (
                existing_claim
                and claimed_at is not None
                and now - claimed_at < DISPATCH_CLAIM_LEASE
            ):
                return profile, None
            delivery_key = str(task.get("delivery_key") or f"health-task:{subject}:{task_id}")
            task.update(
                {
                    "status": "due_for_render",
                    "dispatch_claim_id": claim_id,
                    "dispatch_claimed_utc": now.isoformat(),
                    "delivery_key": delivery_key,
                    "updated_utc": now.isoformat(),
                }
            )
            tasks[index] = task
            profile["tasks"] = tasks
            claimed = (copy.deepcopy(profile), copy.deepcopy(task))
            return profile, None
        return profile, None

    store.mutate_subject_status(subject, mutate)
    return claimed


def _failure_update(
    store: HealthSidecarStore,
    subject: str,
    task: Mapping[str, Any],
    now: dt.datetime,
    code: str,
    *,
    force_terminal: bool = False,
) -> tuple[bool, str | None] | None:
    attempt = int(task.get("dispatch_attempts", 0) or 0) + 1
    terminal = force_terminal or attempt >= 2
    retry_after = None if terminal else now + DISPATCH_RETRY_DELAY
    task_id = str(task["task_id"])
    updated = _mutate_task(
        store,
        subject,
        task_id,
        {
            "status": "failed" if terminal else "due_for_render",
            "dispatch_attempts": attempt,
            "retry_after_utc": retry_after.isoformat() if retry_after else None,
            "failure_code": _safe_reason(code),
            "dispatch_claim_id": None,
            "dispatch_claimed_utc": None,
            "updated_utc": now.isoformat(),
        },
        expected_statuses=RENDERABLE_STATUSES,
        expected_claim_id=task.get("dispatch_claim_id"),
        audit_event=(
            "task_failed",
            {
                "subject": subject,
                "actor_role": "dispatcher",
                "action": "task.dispatch",
                "object_id": task_id,
                "recipient_id": str(task.get("recipient_sender_id") or subject),
                "result": "failed",
                "reason": _safe_reason(code),
                "evidence_ids": [
                    str(item) for item in task.get("evidence_ids", [])
                ],
            },
        ),
    )
    if updated is None:
        return None
    return terminal, retry_after.isoformat() if retry_after else None


def _audit_task(
    store: HealthSidecarStore,
    event: str,
    subject: str,
    task: Mapping[str, Any],
    *,
    action: str,
    result: str,
    reason: str,
) -> None:
    store.append_audit_event(
        event,
        {
            "subject": subject,
            "actor_role": "dispatcher",
            "action": action,
            "object_id": str(task.get("task_id", "")),
            "recipient_id": str(task.get("recipient_sender_id") or subject),
            "result": result,
            "reason": _safe_reason(reason),
            "evidence_ids": [str(item) for item in task.get("evidence_ids", [])],
        },
    )


def _send_once(
    channel_send: Any,
    recipient: str,
    message: str,
    delivery_key: str,
) -> None:
    sender = getattr(channel_send, "send_once", None)
    if callable(sender):
        try:
            sent = sender(recipient, message, delivery_key)
        except ChannelSendUncertainError as exc:
            raise RuntimeError("channel-send-uncertain") from exc
        except Exception as exc:
            raise RuntimeError("channel-send-failed") from exc
        if sent is False:
            raise RuntimeError("channel-send-failed")
        return
    # A channel without the idempotent port cannot be safely used by the
    # dispatcher: even a successful hand-off followed by a state-write error
    # could otherwise be emitted twice on the retry path.
    raise RuntimeError("channel-send-unavailable")


def _complete_fresh(
    llm: Any, prompt: str, context: Mapping[str, Any], session_id: str
) -> Any:
    complete = getattr(llm, "complete_fresh", None)
    if not callable(complete):
        raise RuntimeError("llm-fresh-session-unavailable")
    return complete(prompt, context, session_id)


def dispatch_due_tasks(
    store: HealthSidecarStore,
    subject: str,
    now_utc: str,
    llm: Any | None,
    channel_send: Any | None,
    source_library: Any | None = None,
) -> Mapping[str, Any]:
    subject = subject.strip()
    if not subject:
        raise ProfileStoreError("subject-required")
    now = _current_time(store, now_utc)
    profile = _profile_from_status(
        store.read_subject_status(subject, _allow_profile_state=True)
    )
    source_cards = _source_cards(store, source_library)
    result: dict[str, Any] = {
        "processed": [],
        "sent": [],
        "skipped": [],
        "failed": [],
        "retry_not_due": [],
        "retry_after_utc": {},
        "reasons": {},
    }
    tasks = [
        copy.deepcopy(dict(task))
        for task in profile.get("tasks", [])
        if isinstance(task, Mapping) and task.get("status") in RENDERABLE_STATUSES
    ]
    sent_purposes: set[str] = set()
    for original_task in tasks:
        task_id = str(original_task.get("task_id", ""))
        if not task_id:
            continue
        live_profile = _profile_from_status(
            store.read_subject_status(subject, _allow_profile_state=True)
        )
        task = next(
            (
                copy.deepcopy(dict(item))
                for item in live_profile.get("tasks", [])
                if isinstance(item, Mapping)
                and item.get("task_id") == task_id
                and item.get("status") in RENDERABLE_STATUSES
            ),
            None,
        )
        if task is None:
            continue
        source_cards = _source_cards(store, source_library)
        retry_after_raw = task.get("retry_after_utc")
        retry_after = _parse_optional_utc(retry_after_raw)
        if retry_after_raw not in (None, "") and retry_after is None:
            reason = "task-invalid"
        elif retry_after is not None and retry_after > now:
            result["retry_not_due"].append(task_id)
            result["retry_after_utc"][task_id] = retry_after.isoformat()
            continue
        else:
            window = task.get("time_window")
            end = _parse_optional_utc(window.get("end_utc")) if isinstance(window, Mapping) else None
            start = _parse_optional_utc(window.get("start_utc")) if isinstance(window, Mapping) else None
            if not isinstance(window, Mapping) or start is None or end is None:
                reason = "task-invalid"
            elif end <= now:
                reason = "task-window-expired"
            elif start > now:
                continue
            elif str(task.get("purpose", "")).strip() in sent_purposes:
                reason = "duplicate-purpose"
            else:
                reason = _skip_reason(
                    live_profile,
                    task,
                    now,
                    source_cards,
                    store.expected_viewer_sender_id,
                )
        result["processed"].append(task_id)
        if reason is not None:
            updated = _mutate_task(
                store,
                subject,
                task_id,
                {
                    "status": "skipped",
                    "skip_reason": reason,
                    "dispatch_claim_id": None,
                    "dispatch_claimed_utc": None,
                    "updated_utc": now.isoformat(),
                },
                expected_statuses=RENDERABLE_STATUSES,
            )
            if updated is None:
                continue
            result["skipped"].append(task_id)
            result["reasons"][task_id] = reason
            _audit_task(
                store, "task_skipped", subject, task,
                action="task.skip", result="skipped", reason=reason
            )
            continue
        if llm is None or channel_send is None:
            failure = _failure_update(
                store, subject, task, now, "dispatch-dependency-unavailable"
            )
            if failure is None:
                continue
            _, retry_after_value = failure
            result["failed"].append(task_id)
            if retry_after_value:
                result["retry_after_utc"][task_id] = retry_after_value
            continue
        claimed = _claim_task(store, subject, task_id, now)
        if claimed is None:
            continue
        claimed_profile, claimed_task = claimed
        try:
            context = _task_snapshot(
                store, subject, claimed_profile, claimed_task, now, source_cards
            )
            try:
                raw_rendered = _complete_fresh(
                    llm,
                    REPORT_RENDER_PROMPT
                    if claimed_task.get("task_type") == WEEKLY_REPORT_TASK_TYPE
                    else RENDER_PROMPT,
                    context,
                    f"dispatch:{subject}:{task_id}:{uuid.uuid4().hex}",
                )
                rendered = (
                    _validate_report_render_result(raw_rendered, claimed_task)
                    if claimed_task.get("task_type") == WEEKLY_REPORT_TASK_TYPE
                    else _validate_render_result(raw_rendered)
                )
            except Exception as exc:
                raise RuntimeError("llm-failed") from exc
            if rendered is None:
                raise RuntimeError("llm-invalid-decision")
            decision, message, model_reason = rendered
            if decision == "skip":
                updated = _mutate_task(
                    store,
                    subject,
                    task_id,
                    {
                        "status": "skipped",
                        "skip_reason": f"llm:{model_reason}",
                        "dispatch_attempts": int(claimed_task.get("dispatch_attempts", 0) or 0) + 1,
                        "dispatch_claim_id": None,
                        "dispatch_claimed_utc": None,
                        "updated_utc": now.isoformat(),
                    },
                    expected_statuses={"due_for_render"},
                    expected_claim_id=str(claimed_task.get("dispatch_claim_id")),
                )
                if updated is None:
                    continue
                result["skipped"].append(task_id)
                result["reasons"][task_id] = model_reason
                _audit_task(
                    store, "task_skipped", subject, claimed_task,
                    action="task.skip", result="skipped", reason="model-skip"
                )
                continue
            # Re-read and revalidate while holding the same state lock used by
            # all profile mutations.  The channel hand-off is inside this
            # section, so a pause/revocation cannot race a stale send.
            with _dispatch_critical_section(store, source_library):
                final_profile = _profile_from_status(
                    store.read_subject_status(subject, _allow_profile_state=True)
                )
                final_task = next(
                    (
                        copy.deepcopy(dict(item))
                        for item in final_profile.get("tasks", [])
                        if isinstance(item, Mapping)
                        and item.get("task_id") == task_id
                    ),
                    None,
                )
                final_cards = _source_cards(store, source_library)
                final_now = store.now_utc().astimezone(dt.timezone.utc).replace(microsecond=0)
                if (
                    final_task is None
                    or final_task.get("status") != "due_for_render"
                    or final_task.get("dispatch_claim_id") != claimed_task.get("dispatch_claim_id")
                ):
                    continue
                final_reason = _skip_reason(
                    final_profile,
                    final_task,
                    final_now,
                    final_cards,
                    store.expected_viewer_sender_id,
                )
                if final_reason is not None:
                    updated = _mutate_task(
                        store,
                        subject,
                        task_id,
                        {
                            "status": "skipped",
                            "skip_reason": final_reason,
                            "dispatch_claim_id": None,
                            "dispatch_claimed_utc": None,
                            "updated_utc": final_now.isoformat(),
                        },
                        expected_statuses={"due_for_render"},
                        expected_claim_id=str(final_task.get("dispatch_claim_id")),
                    )
                    if updated is None:
                        continue
                    result["skipped"].append(task_id)
                    result["reasons"][task_id] = final_reason
                    _audit_task(
                        store, "task_skipped", subject, final_task,
                        action="task.skip", result="skipped", reason=final_reason
                    )
                    continue
                try:
                    _send_once(
                        channel_send,
                        str(
                            final_task.get("recipient_sender_id")
                            or final_profile["owner_sender_id"]
                        ),
                        str(message),
                        str(final_task.get("delivery_key") or f"health-task:{subject}:{task_id}"),
                    )
                except RuntimeError as exc:
                    code = str(exc)
                    force_terminal = code == "channel-send-uncertain"
                    # Leave the lock before retry bookkeeping, but preserve
                    # the exact task snapshot used for the attempt.
                    raise RuntimeError(
                        f"{code}:terminal" if force_terminal else code
                    ) from exc
                try:
                    updated = _mutate_task(
                        store,
                        subject,
                        task_id,
                        {
                            "status": "sent",
                            "sent_utc": final_now.isoformat(),
                            "dispatch_attempts": int(final_task.get("dispatch_attempts", 0) or 0) + 1,
                            "retry_after_utc": None,
                            "failure_code": None,
                            "dispatch_claim_id": None,
                            "dispatch_claimed_utc": None,
                            "updated_utc": final_now.isoformat(),
                        },
                        expected_statuses={"due_for_render"},
                        expected_claim_id=str(final_task.get("dispatch_claim_id")),
                    )
                    if updated is None:
                        raise RuntimeError("sent-state-unknown")
                except Exception as exc:
                    # The channel has already accepted the idempotent key.  A
                    # state-write failure must never schedule an unconstrained
                    # duplicate attempt; leave a terminal, auditable outcome.
                    raise RuntimeError("sent-state-unknown") from exc
                result["sent"].append(task_id)
                sent_purposes.add(str(final_task.get("purpose", "")).strip())
                _audit_task(
                    store, "task_sent", subject, final_task,
                    action="task.send", result="sent", reason="rendered-send"
                )
        except Exception as exc:
            raw_code = str(exc).split(":", 1)[0]
            if raw_code in {"profile-not-bound", "profile-state-corrupt", "task-not-found"}:
                # Deletion or an invalidated profile is terminal for this
                # task.  There is no profile left in which to write a retry
                # state, so never turn the condition into a retry loop.
                result["skipped"].append(task_id)
                result["reasons"][task_id] = "profile-invalidated"
                continue
            code = raw_code if raw_code in {
                "llm-failed",
                "llm-invalid-decision",
                "llm-fresh-session-unavailable",
                "channel-send-failed",
                "channel-send-uncertain",
                "channel-send-unavailable",
                "sent-state-unknown",
            } else "dispatch-failed"
            force_terminal = raw_code in {"channel-send-uncertain", "sent-state-unknown"}
            failure = _failure_update(
                store, subject, claimed_task, now, code, force_terminal=force_terminal
            )
            if failure is None:
                continue
            _, retry_after_value = failure
            result["failed"].append(task_id)
            if retry_after_value:
                result["retry_after_utc"][task_id] = retry_after_value
    store.append_audit_event(
        "dispatcher_heartbeat",
        {
            "subject": subject,
            "actor_role": "dispatcher",
            "action": "dispatcher.heartbeat",
            "object_id": f"dispatcher:{subject}",
            "result": "healthy",
            "heartbeat": True,
        },
    )
    store.append_audit_event(
        "dispatcher_run",
        {
            "subject": subject,
            "actor_role": "dispatcher",
            "action": "dispatcher.run",
            "object_id": f"dispatcher:{subject}",
            "result": "completed",
            "reason": "poll-completed",
            "processed": len(result["processed"]),
            "sent": len(result["sent"]),
            "skipped": len(result["skipped"]),
            "failed": len(result["failed"]),
        },
    )
    return result

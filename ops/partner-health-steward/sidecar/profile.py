"""Evidence and compact-profile domain operations for the partner sidecar.

The module accepts only structured candidate writes from the partner adapter.
It never stores a complete chat message: an admitted evidence excerpt is the
only source text retained, and it is bounded to 300 characters.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
import uuid
from typing import Any, Mapping

from .health_turn_context import (
    HEALTH_TURN_CONTEXT_SCHEMA_VERSION,
    MAX_HEALTH_TURN_EVIDENCE_IDS,
    MAX_HEALTH_TURN_EVIDENCE_IDS_PER_CONCLUSION,
)
from .protocol import (
    ACTION_HEALTH_TURN_CONTEXT_READ,
    HEALTH_TURN_CONTEXT_EVIDENCE_KIND,
)
from .store import HealthSidecarStore, StoreError


PROFILE_SCHEMA_VERSION = 1
MAX_EXCERPT_CHARS = 300
MAX_SUMMARY_CHARS = 300
MAX_STAGED_MESSAGE_CHARS = 16_384
CONSENTED_ATTEMPT_MAX_SECONDS = 15
TRUSTED_ENVELOPE_MAX_SECONDS = 600

EVIDENCE_KINDS = {
    "direct_statement",
    "measurement",
    "owner_relayed_clinician",
}
NON_PERSONAL_EVIDENCE_KINDS = {
    "ordinary_chat",
    "non_owner",
    "source_card",
    "model_inference",
}
CATEGORY_CAPS = {
    "state": 2,
    "habit_goal": 3,
    "interaction_preference": 2,
    "task_context": 1,
}
CATEGORY_DEFAULT_VALIDITY = {
    "state": dt.timedelta(hours=24),
    "habit_goal": dt.timedelta(days=30),
    "interaction_preference": dt.timedelta(days=60),
    "task_context": dt.timedelta(days=30),
}
# Persistence requires evidence from distinct observation times; the spec does
# not impose an arbitrary hour/day threshold, so equal timestamps do not count.
MIN_CONFLICT_PERSISTENCE = dt.timedelta(0)
CATEGORY_ORDER = tuple(CATEGORY_CAPS)
CONCLUSION_STATUSES = {"fact", "tendency", "unverified_hypothesis"}


class ProfileStoreError(StoreError):
    """A safe, content-free validation failure for a profile operation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _utc_iso(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileStoreError("invalid-utc")
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProfileStoreError("invalid-utc") from exc
    if parsed.tzinfo is None:
        raise ProfileStoreError("utc-must-be-aware")
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def _now_utc(store: HealthSidecarStore) -> dt.datetime:
    return store.now_utc().replace(microsecond=0)


def _ensure_trusted_ingress_deadline(
    store: HealthSidecarStore,
    message_time: dt.datetime,
    attempt_time: dt.datetime,
) -> None:
    now = _now_utc(store)
    if (
        attempt_time < message_time
        or attempt_time
        > message_time + dt.timedelta(seconds=TRUSTED_ENVELOPE_MAX_SECONDS)
        or attempt_time > now + dt.timedelta(seconds=60)
    ):
        raise ProfileStoreError("health-ingress-attempt-invalid")
    if now >= attempt_time + dt.timedelta(seconds=CONSENTED_ATTEMPT_MAX_SECONDS):
        raise ProfileStoreError("health-ingress-deadline-exceeded")


def _non_empty(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileStoreError(code)
    return value.strip()


def _has_markdown(value: str) -> bool:
    if any(marker in value for marker in ("`", "*", "_", "~")):
        return True
    return bool(
        re.search(
            r"```|`|(^|\n)\s*#{1,6}\s|(^|\n)\s*[-*+]\s|(^|\n)\s*\d+\.\s|!\[[^]]*\]\([^)]*\)|\[[^]]+\]\([^)]*\)",
            value,
        )
    )


def _validate_excerpt(candidate: Mapping[str, Any]) -> str:
    if "source_text" in candidate or "message_text" in candidate:
        raise ProfileStoreError("full-message-not-accepted")
    excerpt = _non_empty(candidate.get("excerpt"), "evidence-excerpt-required")
    if len(excerpt) > MAX_EXCERPT_CHARS:
        raise ProfileStoreError("evidence-excerpt-too-long")
    return excerpt


def _validate_measurement(candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = candidate.get("evidence_kind")
    measurement = candidate.get("measurement")
    if kind != "measurement":
        if measurement is not None:
            raise ProfileStoreError("measurement-kind-required")
        return None
    if not isinstance(measurement, Mapping):
        raise ProfileStoreError("measurement-required")
    measurement_type = _non_empty(measurement.get("type"), "measurement-type-required")
    value = measurement.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileStoreError("measurement-value-must-be-number")
    unit = _non_empty(measurement.get("unit"), "measurement-unit-required")
    observed_utc = _utc_iso(measurement.get("observed_utc"))
    return {
        "type": measurement_type,
        "value": value,
        "unit": unit,
        "observed_utc": observed_utc,
    }


EXCLUDED_PREFERENCE_SIGNALS = {
    "silence",
    "reply_speed",
    "one_off_emotion",
    "ordinary_chat",
}


def _validate_conclusion(
    raw: Any,
    evidence_id: str,
    evidence_utc: dt.datetime,
    evidence_kind: str,
    source_message_id: str,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ProfileStoreError("conclusion-must-be-object")
    category = _non_empty(raw.get("category"), "conclusion-category-required")
    if category not in CATEGORY_CAPS:
        raise ProfileStoreError("unsupported-conclusion-category")
    key = _non_empty(raw.get("dedupe_key"), "conclusion-dedupe-key-required")
    text = _non_empty(raw.get("text"), "conclusion-text-required")
    if len(text) > MAX_SUMMARY_CHARS:
        raise ProfileStoreError("conclusion-text-too-long")
    if _has_markdown(text):
        raise ProfileStoreError("profile-summary-markdown-forbidden")
    status = _non_empty(raw.get("status"), "conclusion-status-required")
    if status not in CONCLUSION_STATUSES:
        raise ProfileStoreError("unsupported-conclusion-status")
    priority = raw.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 1000:
        raise ProfileStoreError("invalid-conclusion-priority")
    task_dependency = raw.get("task_dependency", False)
    if not isinstance(task_dependency, bool):
        raise ProfileStoreError("invalid-task-dependency")
    if status == "unverified_hypothesis" and task_dependency:
        raise ProfileStoreError("hypothesis-task-not-allowed")
    completion_question = raw.get("completion_question", False)
    if not isinstance(completion_question, bool):
        raise ProfileStoreError("invalid-completion-question")
    conflict_key = raw.get("conflict_key")
    if conflict_key is not None:
        conflict_key = _non_empty(conflict_key, "invalid-conflict-key")
    high_impact = raw.get("high_impact", False)
    if not isinstance(high_impact, bool):
        raise ProfileStoreError("invalid-high-impact")
    active = True
    preference_mode = None
    preference_signal = None
    behavior_ids: list[str] = []
    behavior_events: list[dict[str, str]] = []
    behavior_direction = None
    if category == "interaction_preference":
        preference_mode = raw.get("preference_mode", "explicit")
        if preference_mode not in {"explicit", "implicit"}:
            raise ProfileStoreError("invalid-preference-mode")
        preference_signal = raw.get("preference_signal")
        if preference_signal is not None:
            preference_signal = _non_empty(
                preference_signal, "invalid-preference-signal"
            )
        if preference_signal in EXCLUDED_PREFERENCE_SIGNALS:
            raise ProfileStoreError("preference-evidence-excluded")
        if preference_mode == "implicit":
            if preference_signal is None:
                raise ProfileStoreError("preference-signal-required")
            behavior_id = _non_empty(raw.get("behavior_id"), "behavior-id-required")
            behavior_ids = [behavior_id]
            behavior_events = [
                {
                    "behavior_id": behavior_id,
                    "source_message_id": source_message_id,
                    "observed_utc": evidence_utc.isoformat(),
                    "evidence_id": evidence_id,
                }
            ]
            behavior_direction = _non_empty(
                raw.get("behavior_direction", "support"),
                "invalid-behavior-direction",
            )
            active = False
            status = "unverified_hypothesis"
            task_dependency = False
            completion_question = False
    valid_until = raw.get("valid_until_utc")
    if evidence_kind == "measurement":
        normalized_valid_until = None
    elif valid_until is None:
        normalized_valid_until = (
            evidence_utc + CATEGORY_DEFAULT_VALIDITY[category]
        ).isoformat()
    else:
        normalized_valid_until = _utc_iso(valid_until)
    aliases = raw.get("aliases", [])
    if not isinstance(aliases, (list, tuple)) or not all(isinstance(item, str) for item in aliases):
        raise ProfileStoreError("invalid-conclusion-aliases")
    normalized_aliases = sorted({key, *(item.strip() for item in aliases if item.strip())})
    return {
        "category": category,
        "dedupe_key": key,
        "aliases": normalized_aliases,
        "text": text,
        "status": status,
        "priority": priority,
        "task_dependency": task_dependency,
        "valid_until_utc": normalized_valid_until,
        "evidence_ids": [evidence_id],
        "source_message_ids": [source_message_id],
        "evidence_kind": evidence_kind,
        "last_evidence_utc": evidence_utc.isoformat(),
        "automatic_task_eligible": status in {"fact", "tendency"} and active,
        "completion_question_issued": completion_question,
        "active": active,
        "conflict_key": conflict_key,
        "high_impact": high_impact,
        "preference_mode": preference_mode,
        "preference_signal": preference_signal,
        "behavior_ids": behavior_ids,
        "behavior_events": behavior_events,
        "behavior_direction": behavior_direction,
        "historical": evidence_kind == "measurement",
    }


def _expired(conclusion: Mapping[str, Any], now: dt.datetime) -> bool:
    if conclusion.get("historical"):
        return False
    valid_until = conclusion.get("valid_until_utc")
    if not valid_until:
        return False
    try:
        expiry = dt.datetime.fromisoformat(str(valid_until))
    except ValueError:
        return True
    return expiry <= now


def _same_conclusion(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if left.get("category") != right.get("category"):
        return False
    if (
        left.get("preference_mode") == "implicit"
        and right.get("preference_mode") == "implicit"
        and left.get("behavior_direction") != right.get("behavior_direction")
    ):
        return False
    if (
        left.get("conflict_key")
        and left.get("conflict_key") == right.get("conflict_key")
        and left.get("text") != right.get("text")
    ):
        return False
    left_keys = set(left.get("aliases", [])) | {str(left.get("dedupe_key", ""))}
    right_keys = set(right.get("aliases", [])) | {str(right.get("dedupe_key", ""))}
    return bool(left_keys & right_keys)


def _merge_conclusions(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = copy.deepcopy(existing)
    for candidate in incoming:
        for index, prior in enumerate(merged):
            if not _same_conclusion(prior, candidate):
                continue
            if prior.get("evidence_kind") == "measurement" or candidate.get(
                "evidence_kind"
            ) == "measurement":
                continue
            prior_time = str(prior.get("last_evidence_utc", ""))
            candidate_time = str(candidate.get("last_evidence_utc", ""))
            replacement = copy.deepcopy(
                prior if candidate_time < prior_time else candidate
            )
            replacement["evidence_ids"] = list(
                dict.fromkeys(
                    [*prior.get("evidence_ids", []), *candidate.get("evidence_ids", [])]
                )
            )
            replacement["source_message_ids"] = sorted(
                set(prior.get("source_message_ids", []))
                | set(candidate.get("source_message_ids", []))
            )
            replacement["aliases"] = sorted(
                set(prior.get("aliases", [])) | set(candidate.get("aliases", []))
            )
            replacement["behavior_ids"] = sorted(
                set(prior.get("behavior_ids", []))
                | set(candidate.get("behavior_ids", []))
            )
            events_by_source = {
                str(event.get("source_message_id", event.get("evidence_id", ""))): event
                for event in [
                    *prior.get("behavior_events", []),
                    *candidate.get("behavior_events", []),
                ]
                if event.get("behavior_id")
                and event.get("source_message_id", event.get("evidence_id"))
            }
            replacement["behavior_events"] = sorted(
                events_by_source.values(), key=lambda event: event["observed_utc"]
            )
            replacement["completion_question_issued"] = bool(
                prior.get("completion_question_issued")
                or candidate.get("completion_question_issued")
            )
            if replacement.get("preference_mode") == "implicit":
                replacement["active"] = len(replacement["behavior_ids"]) >= 3
                replacement["status"] = (
                    "fact" if replacement["active"] else "unverified_hypothesis"
                )
            replacement["automatic_task_eligible"] = bool(
                replacement.get("active", True)
                and replacement.get("status") in {"fact", "tendency"}
            )
            merged[index] = replacement
            break
        else:
            merged.append(copy.deepcopy(candidate))
    return merged


def _refresh_preference_lifecycle(
    conclusions: list[dict[str, Any]], now: dt.datetime
) -> None:
    window_start = now - CATEGORY_DEFAULT_VALIDITY["interaction_preference"]
    for item in conclusions:
        if item.get("category") != "interaction_preference":
            continue
        if item.get("preference_mode") != "implicit":
            item["active"] = True
            item["automatic_task_eligible"] = item.get("status") in {
                "fact",
                "tendency",
            }
            continue
        events = []
        for event in item.get("behavior_events", []):
            try:
                observed = dt.datetime.fromisoformat(str(event["observed_utc"]))
            except (KeyError, TypeError, ValueError):
                continue
            if window_start <= observed <= now:
                events.append(dict(event))
        item["behavior_events"] = sorted(
            {
                event.get("source_message_id", event.get("evidence_id", "")): event
                for event in events
                if event.get("behavior_id")
                and event.get("source_message_id", event.get("evidence_id"))
            }.values(),
            key=lambda event: event["observed_utc"],
        )
        item["behavior_ids"] = [
            event["behavior_id"] for event in item["behavior_events"]
        ]
        item["active"] = len(item["behavior_events"]) >= 3
        item["status"] = "fact" if item["active"] else "unverified_hypothesis"
        item["automatic_task_eligible"] = item["active"]
        if item["behavior_events"]:
            latest = max(event["observed_utc"] for event in item["behavior_events"])
            latest_dt = dt.datetime.fromisoformat(latest)
            item["valid_until_utc"] = (
                latest_dt + CATEGORY_DEFAULT_VALIDITY["interaction_preference"]
            ).isoformat()


def _apply_conflicts(conclusions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in conclusions:
        key = item.get("conflict_key")
        if key and not item.get("historical"):
            grouped.setdefault(str(key), []).append(item)
    result = list(conclusions)
    for conflict_key, items in grouped.items():
        texts = {str(item.get("text", "")) for item in items}
        if len(texts) < 2 or not any(item.get("high_impact") for item in items):
            continue
        evidence_times = []
        source_message_ids = set()
        for item in items:
            source_message_ids.update(item.get("source_message_ids", []))
            try:
                evidence_times.append(
                    dt.datetime.fromisoformat(str(item["last_evidence_utc"]))
                )
            except (KeyError, TypeError, ValueError):
                continue
        if (
            len(source_message_ids) < 2
            or not evidence_times
            or max(evidence_times) - min(evidence_times) <= MIN_CONFLICT_PERSISTENCE
        ):
            continue
        latest_evidence = max(evidence_times)
        evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for item in items
                for evidence_id in item.get("evidence_ids", [])
            )
        )
        generated = {
            "category": items[0]["category"],
            "dedupe_key": f"conflict:{conflict_key}",
            "aliases": sorted(
                {f"conflict:{conflict_key}"}
                | {
                    str(item.get("dedupe_key"))
                    for item in items
                    if item.get("dedupe_key")
                }
            ),
            "text": f"待核实：{conflict_key}",
            "status": "unverified_hypothesis",
            "priority": max(int(item.get("priority", 0)) for item in items),
            "task_dependency": False,
            "valid_until_utc": (
                latest_evidence + CATEGORY_DEFAULT_VALIDITY[items[0]["category"]]
            ).isoformat(),
            "evidence_ids": evidence_ids,
            "source_message_ids": sorted(source_message_ids),
            "evidence_kind": "direct_statement",
            "last_evidence_utc": latest_evidence.isoformat(),
            "automatic_task_eligible": False,
            "completion_question_issued": True,
            "active": True,
            "conflict_key": conflict_key,
            "high_impact": True,
            "preference_mode": None,
            "preference_signal": None,
            "behavior_ids": [],
            "behavior_events": [],
            "behavior_direction": None,
            "historical": False,
        }
        result = [item for item in result if item not in items]
        result.append(generated)
    return result


def _summary(conclusions: list[dict[str, Any]]) -> str:
    conclusions = [
        item
        for item in conclusions
        if item.get("active", True) and not item.get("historical")
    ]
    ordered = sorted(
        conclusions,
        key=lambda item: (
            CATEGORY_ORDER.index(str(item["category"])),
            -int(item["priority"]),
            str(item["dedupe_key"]),
        ),
    )
    return "；".join(str(item["text"]) for item in ordered)


def _compact_conclusions(
    conclusions: list[dict[str, Any]], now: dt.datetime
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    active = [item for item in conclusions if not _expired(item, now)]
    historical = [item for item in active if item.get("historical")]
    active = [item for item in active if not item.get("historical")]
    deferred: list[dict[str, Any]] = []
    for category, cap in CATEGORY_CAPS.items():
        category_items = [item for item in active if item["category"] == category]
        category_items.sort(
            key=lambda item: (bool(item.get("task_dependency")), int(item["priority"])),
            reverse=True,
        )
        if sum(bool(item.get("task_dependency")) for item in category_items) > cap:
            raise ProfileStoreError("summary_overflow")
        keep = set(id(item) for item in category_items[:cap])
        deferred.extend(
            copy.deepcopy(item)
            for item in category_items[cap:]
            if not item.get("task_dependency")
        )
        active = [item for item in active if item["category"] != category or id(item) in keep]

    while True:
        summary = _summary(active)
        if len(summary) <= MAX_SUMMARY_CHARS:
            if _has_markdown(summary):
                raise ProfileStoreError("profile-summary-markdown-forbidden")
            return historical + active, summary, deferred
        removable = [item for item in active if not item.get("task_dependency")]
        if not removable:
            raise ProfileStoreError("summary_overflow")
        victim = min(removable, key=lambda item: (int(item["priority"]), str(item["dedupe_key"])))
        active.remove(victim)
        deferred.append(copy.deepcopy(victim))


def _empty_profile(owner_sender_id: str | None = None) -> dict[str, Any]:
    return {
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "owner_sender_id": owner_sender_id,
        "evidence": [],
        "profile_versions": [],
        "current_version_id": None,
        "profile_summary_zh": "",
        "conclusions": [],
        "deferred_conclusions": [],
        "owner_timezone": "Asia/Shanghai",
        "recording_status": "recording_enabled",
        "proactive_contact": {"paused": False},
        "tasks": [],
        "reports": [],
        "daily_review_runs": [],
        "viewer_grants": [],
        "access_receipt_ids": [],
    }


def _profile_from_status(status: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(status, Mapping) or status.get("profile_schema_version") != PROFILE_SCHEMA_VERSION:
        raise ProfileStoreError("profile-not-bound")
    required = {"owner_sender_id", "evidence", "profile_versions", "current_version_id"}
    if not required.issubset(status):
        raise ProfileStoreError("profile-state-corrupt")
    return copy.deepcopy(dict(status))


def bind_profile_owner(
    store: HealthSidecarStore,
    subject: str,
    owner_sender_id: str,
    verification_token: str,
) -> bool:
    if store.expected_owner_sender_id:
        raise ProfileStoreError("legacy-profile-ingress-disabled")
    subject = _non_empty(subject, "subject-required")
    owner_sender_id = _non_empty(owner_sender_id, "owner-sender-required")
    if not store.verify_owner_binding(
        subject=subject, owner_sender_id=owner_sender_id, token=verification_token
    ):
        raise ProfileStoreError("unverified-owner-binding")

    def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], bool]:
        if not current:
            return _empty_profile(owner_sender_id), True
        profile = _profile_from_status(current)
        existing = profile.get("owner_sender_id")
        if existing and existing != owner_sender_id:
            raise ProfileStoreError("owner-already-bound")
        profile["owner_sender_id"] = owner_sender_id
        return profile, existing is None

    return store.mutate_subject_status(subject, mutate)


def stage_profile_message(
    store: HealthSidecarStore,
    subject: str,
    sender_id: str,
    message_id: str,
    message_utc: str,
    message_text: str,
    evidence_kind: str,
    verification_token: str,
) -> bool:
    """Stage one verified inbound message in memory for one candidate write.

    The partner adapter supplies the sender identity and eligible evidence kind
    after Hermes has verified and classified the inbound event. The message
    body never enters encrypted state or audit. Only the latest three messages
    per subject are retained in this process.
    """
    if store.expected_owner_sender_id:
        raise ProfileStoreError("legacy-profile-ingress-disabled")
    subject = _non_empty(subject, "subject-required")
    sender_id = _non_empty(sender_id, "sender-required")
    message_id = _non_empty(message_id, "source-message-id-required")
    message_utc = _utc_iso(message_utc)
    evidence_kind = _non_empty(evidence_kind, "profile-message-kind-required")
    if evidence_kind not in EVIDENCE_KINDS:
        raise ProfileStoreError("profile-message-not-eligible")
    if not isinstance(message_text, str) or not message_text.strip():
        raise ProfileStoreError("message-text-required")
    if len(message_text) > MAX_STAGED_MESSAGE_CHARS:
        raise ProfileStoreError("message-text-too-long")
    if not store.verify_inbound_message(
        subject=subject,
        sender_id=sender_id,
        message_id=message_id,
        message_utc=message_utc,
        message_text=message_text,
        evidence_kind=evidence_kind,
        token=verification_token,
    ):
        raise ProfileStoreError("unverified-inbound-message")
    # Serialize the owner/profile check and both ephemeral writes with
    # deletion.  Otherwise a stage request that read the owner just before a
    # delete could repopulate the in-memory window after deletion completed.
    with store._recent_message_lock:
        profile = _profile_from_status(
            store.read_subject_status(subject, _allow_profile_state=True)
        )
        if profile.get("owner_sender_id") != sender_id:
            raise ProfileStoreError("non-owner-message")
        if any(
            item.get("source_message_id") == message_id
            for item in profile.get("evidence", [])
        ):
            raise ProfileStoreError("duplicate-source-message")
        with store._state_lock:
            staged = store._staged_profile_messages.setdefault(subject, [])
            if any(item.get("message_id") == message_id for item in staged):
                raise ProfileStoreError("source-message-already-staged")
            staged.append(
                {
                    "message_id": message_id,
                    "sender_id": sender_id,
                    "message_utc": message_utc,
                    "text": message_text,
                    "evidence_kind": evidence_kind,
                }
            )
            del staged[:-3]
            store.remember_recent_profile_message(
                subject, sender_id, message_id, message_utc, message_text
            )
            store._record_owner_reply(subject, sender_id, message_utc)
    return True


def _validate_staged_message(
    store: HealthSidecarStore,
    subject: str,
    sender_id: str,
    source_message_id: str,
    source_utc: str,
    excerpt: str,
    evidence_kind: str,
) -> None:
    with store._state_lock:
        staged = store._staged_profile_messages.get(subject, [])
        matching_index = next(
            (
                index
                for index, item in enumerate(staged)
                if item.get("message_id") == source_message_id
            ),
            None,
        )
        if matching_index is None:
            raise ProfileStoreError("source-message-not-staged")
        message = staged[matching_index]
    if message.get("sender_id") != sender_id:
        raise ProfileStoreError("non-owner-evidence")
    if message.get("message_utc") != source_utc:
        raise ProfileStoreError("source-time-mismatch")
    if message.get("evidence_kind") != evidence_kind:
        raise ProfileStoreError("source-kind-mismatch")
    if excerpt not in str(message.get("text", "")):
        raise ProfileStoreError("evidence-excerpt-not-in-source")


def _remove_staged_message(
    store: HealthSidecarStore, subject: str, source_message_id: str
) -> None:
    with store._state_lock:
        staged = store._staged_profile_messages.get(subject, [])
        for index, item in enumerate(staged):
            if item.get("message_id") == source_message_id:
                staged.pop(index)
                break


def _candidate_mutator(
    store: HealthSidecarStore,
    sender_id: str,
    candidate: Mapping[str, Any],
    source_validator: Any,
) -> tuple[Any, str]:
    if not isinstance(candidate, Mapping):
        raise ProfileStoreError("candidate-must-be-object")
    kind = _non_empty(candidate.get("evidence_kind"), "evidence-kind-required")
    if kind in NON_PERSONAL_EVIDENCE_KINDS or kind not in EVIDENCE_KINDS:
        raise ProfileStoreError("not-personal-evidence")
    source_message_id = _non_empty(candidate.get("source_message_id"), "source-message-id-required")
    source_utc = _utc_iso(candidate.get("source_utc"))
    excerpt = _validate_excerpt(candidate)
    measurement = _validate_measurement(candidate)
    evidence_id = f"ev-{uuid.uuid4().hex}"
    raw_conclusions = candidate.get("conclusions", [])
    if not isinstance(raw_conclusions, (list, tuple)):
        raise ProfileStoreError("conclusions-must-be-list")
    admitted_now = _now_utc(store)
    evidence_time = dt.datetime.fromisoformat(source_utc)
    incoming = [
        _validate_conclusion(item, evidence_id, evidence_time, kind, source_message_id)
        for item in raw_conclusions
    ]

    def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        profile = _profile_from_status(current)
        if profile.get("owner_sender_id") != sender_id:
            raise ProfileStoreError("non-owner-evidence")
        if any(
            item.get("source_message_id") == source_message_id
            for item in profile.get("evidence", [])
        ):
            raise ProfileStoreError("duplicate-source-message")
        source_validator(
            sender_id,
            source_message_id,
            source_utc,
            excerpt,
            kind,
        )
        now = _now_utc(store)
        current_version = None
        for version in profile["profile_versions"]:
            if version.get("version_id") == profile.get("current_version_id"):
                current_version = version
                break
        prior_conclusions = list(current_version.get("conclusions", [])) if current_version else []
        prior_conclusions.extend(profile.get("deferred_conclusions", []))
        for candidate in incoming:
            if not candidate.get("completion_question_issued"):
                continue
            if any(
                prior.get("completion_question_issued")
                and _same_conclusion(prior, candidate)
                for prior in prior_conclusions
            ):
                raise ProfileStoreError("completion-question-already-issued")
        merged = _merge_conclusions(prior_conclusions, incoming)
        _refresh_preference_lifecycle(merged, now)
        merged = _apply_conflicts(merged)
        pending = [
            item for item in merged if not _expired(item, now) and not item.get("active", True)
        ]
        eligible = [
            item for item in merged if item.get("active", True) and not _expired(item, now)
        ]
        compacted, summary, deferred = _compact_conclusions(eligible, now)
        retained = compacted + pending
        evidence = {
            "evidence_id": evidence_id,
            "kind": kind,
            "source_message_id": source_message_id,
            "source_utc": source_utc,
            "excerpt": excerpt,
            "measurement": measurement,
            "owner_relayed": kind == "owner_relayed_clinician",
            "admitted_utc": now.isoformat(),
        }
        version_id = f"pv-{uuid.uuid4().hex}"
        version = {
            "version_id": version_id,
            "created_utc": now.isoformat(),
            "profile_summary_zh": summary,
            "conclusions": retained,
            "evidence_ids": [evidence_id]
            + list(current_version.get("evidence_ids", []))
            if current_version
            else [evidence_id],
        }
        updated = copy.deepcopy(profile)
        updated["evidence"].append(evidence)
        updated["profile_versions"].append(version)
        updated["current_version_id"] = version_id
        updated["profile_summary_zh"] = summary
        updated["conclusions"] = retained
        updated["deferred_conclusions"] = deferred
        return updated, {
            "version_id": version_id,
            "evidence_id": evidence_id,
            "profile_summary_zh": summary,
            "conclusions": copy.deepcopy(retained),
        }

    return mutate, source_message_id


def record_profile_candidate(
    store: HealthSidecarStore,
    subject: str,
    sender_id: str,
    candidate: Mapping[str, Any],
) -> Mapping[str, Any]:
    if store.expected_owner_sender_id:
        raise ProfileStoreError("legacy-profile-ingress-disabled")
    subject = _non_empty(subject, "subject-required")
    sender_id = _non_empty(sender_id, "sender-required")

    def validate_staged(
        checked_sender_id: str,
        source_message_id: str,
        source_utc: str,
        excerpt: str,
        evidence_kind: str,
    ) -> None:
        _validate_staged_message(
            store,
            subject,
            checked_sender_id,
            source_message_id,
            source_utc,
            excerpt,
            evidence_kind,
        )

    mutate, source_message_id = _candidate_mutator(
        store, sender_id, candidate, validate_staged
    )

    with store._state_lock:
        result = store.mutate_subject_status(subject, mutate)
        _remove_staged_message(store, subject, source_message_id)
        return result


def admit_consented_profile_candidate(
    store: HealthSidecarStore,
    *,
    subject: str,
    sender_id: str,
    message_id: str,
    message_utc: str,
    message_text: str,
    evidence_kind: str,
    channel: str,
    profile_name: str,
    verification_token: str,
    candidate: Mapping[str, Any],
    attempt_utc: str | None = None,
    audit_context: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Verify one pre-batch Weixin envelope and atomically bind/write it."""
    subject = _non_empty(subject, "subject-required")
    sender_id = _non_empty(sender_id, "sender-required")
    message_id = _non_empty(message_id, "source-message-id-required")
    message_utc = _utc_iso(message_utc)
    message_time = dt.datetime.fromisoformat(message_utc)
    attempt_utc = _utc_iso(attempt_utc or message_utc)
    attempt_time = dt.datetime.fromisoformat(attempt_utc)
    evidence_kind = _non_empty(evidence_kind, "profile-message-kind-required")
    channel = _non_empty(channel, "channel-required")
    profile_name = _non_empty(profile_name, "profile-name-required")
    if channel != "weixin" or profile_name != "partner":
        raise ProfileStoreError("untrusted-ingress-route")
    if evidence_kind not in EVIDENCE_KINDS:
        raise ProfileStoreError("profile-message-not-eligible")
    if not isinstance(message_text, str) or not message_text.strip():
        raise ProfileStoreError("message-text-required")
    if len(message_text) > MAX_STAGED_MESSAGE_CHARS:
        raise ProfileStoreError("message-text-too-long")
    if not store.health_recording_enabled(subject, sender_id):
        raise ProfileStoreError("recording-not-enabled")
    if not store.message_verifier.verify_ingress_receipt(
        action="health.profile.message.admit",
        subject=subject,
        sender_id=sender_id,
        message_id=message_id,
        message_utc=message_utc,
        message_text=message_text,
        evidence_kind=evidence_kind,
        channel=channel,
        profile_name=profile_name,
        attempt_utc=attempt_utc,
        token=verification_token,
    ):
        raise ProfileStoreError("unverified-inbound-message")
    # Reuse the sidecar-controlled short receipt window.  Successful writes
    # are one-time by source_message_id in the evidence ledger; failures may
    # be safely corrected and retried without leaving a partial profile.
    store._validate_access_receipt(subject, message_id, message_utc)

    def ensure_admission_deadline() -> None:
        _ensure_trusted_ingress_deadline(store, message_time, attempt_time)

    ensure_admission_deadline()

    def validate_envelope(
        checked_sender_id: str,
        source_message_id: str,
        source_utc: str,
        excerpt: str,
        checked_kind: str,
    ) -> None:
        if checked_sender_id != sender_id:
            raise ProfileStoreError("non-owner-evidence")
        if source_message_id != message_id:
            raise ProfileStoreError("source-message-mismatch")
        if source_utc != message_utc:
            raise ProfileStoreError("source-time-mismatch")
        if checked_kind != evidence_kind:
            raise ProfileStoreError("source-kind-mismatch")
        if excerpt not in message_text:
            raise ProfileStoreError("evidence-excerpt-not-in-source")

    candidate_mutate, _ = _candidate_mutator(
        store, sender_id, candidate, validate_envelope
    )

    def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        ensure_admission_deadline()
        # The recording-state check must share the state lock with this
        # mutation. If stop-recording commits first, this attempt cannot write;
        # if this attempt commits first, stop waits and then becomes final.
        if not store.health_recording_enabled(subject, sender_id):
            raise ProfileStoreError("recording-not-enabled")
        if not current:
            current = _empty_profile(sender_id)
        else:
            existing = _profile_from_status(current)
            if existing.get("owner_sender_id") != sender_id:
                raise ProfileStoreError("owner-already-bound")
            current = existing
        updated, result = candidate_mutate(current)
        updated, _ = store._apply_owner_reply_to_profile(
            updated, sender_id, message_utc
        )
        ensure_admission_deadline()
        return updated, result

    def audit_builder(
        result: Mapping[str, Any],
    ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        details: dict[str, Any] = {
            "subject": subject,
            "actor_role": "owner",
            "actor_id": sender_id,
            "action": "health.profile.message.admit",
            "object_id": result["version_id"],
            "result": "accepted",
            "evidence_id": result["evidence_id"],
            "evidence_ids": [result["evidence_id"]],
            "version_id": result["version_id"],
        }
        for key in ("peer_uid", "peer_gid"):
            value = dict(audit_context or {}).get(key)
            if isinstance(value, int):
                details[key] = value
        return (("profile_candidate_accepted", details),)

    with store._recent_message_lock:
        result = store.mutate_subject_status(
            subject,
            mutate,
            audit_builder=audit_builder,
            commit_validator=ensure_admission_deadline,
        )
        store.remember_recent_profile_message(
            subject, sender_id, message_id, message_utc, message_text
        )
    return {**dict(result), "changed": True}


def read_health_turn_context(
    store: HealthSidecarStore,
    *,
    subject: str,
    sender_id: str,
    message_id: str,
    message_utc: str,
    message_text: str,
    channel: str,
    profile_name: str,
    attempt_utc: str,
    verification_token: str,
) -> Mapping[str, Any]:
    """Read only the bounded profile fields authorized for one health turn."""
    subject = _non_empty(subject, "subject-required")
    sender_id = _non_empty(sender_id, "sender-required")
    message_id = _non_empty(message_id, "source-message-id-required")
    message_utc = _utc_iso(message_utc)
    message_time = dt.datetime.fromisoformat(message_utc)
    attempt_utc = _utc_iso(attempt_utc)
    attempt_time = dt.datetime.fromisoformat(attempt_utc)
    channel = _non_empty(channel, "channel-required")
    profile_name = _non_empty(profile_name, "profile-name-required")
    verification_token = _non_empty(
        verification_token, "verification-token-required"
    )
    if channel != "weixin" or profile_name != "partner":
        raise ProfileStoreError("untrusted-ingress-route")
    if not isinstance(message_text, str) or not message_text.strip():
        raise ProfileStoreError("message-text-required")
    if len(message_text) > MAX_STAGED_MESSAGE_CHARS:
        raise ProfileStoreError("message-text-too-long")
    if not store.health_recording_enabled(subject, sender_id):
        raise ProfileStoreError("recording-not-enabled")
    if not store.message_verifier.verify_ingress_receipt(
        action=ACTION_HEALTH_TURN_CONTEXT_READ,
        subject=subject,
        sender_id=sender_id,
        message_id=message_id,
        message_utc=message_utc,
        message_text=message_text,
        evidence_kind=HEALTH_TURN_CONTEXT_EVIDENCE_KIND,
        channel=channel,
        profile_name=profile_name,
        attempt_utc=attempt_utc,
        token=verification_token,
    ):
        raise ProfileStoreError("unverified-inbound-message")
    _ensure_trusted_ingress_deadline(store, message_time, attempt_time)
    # The context receipt authorizes one model-visible projection only.  Claim
    # it before reading profile content so concurrent or replayed delivery of
    # the same Weixin event cannot expose the snapshot to the model twice.
    store.consume_access_receipt(subject, message_id, message_utc)

    with store._state_lock:
        _ensure_trusted_ingress_deadline(store, message_time, attempt_time)
        if not store.health_recording_enabled(subject, sender_id):
            raise ProfileStoreError("recording-not-enabled")
        status = store.read_subject_status(subject, _allow_profile_state=True)
        if status is None:
            return {
                "context_schema_version": HEALTH_TURN_CONTEXT_SCHEMA_VERSION,
                "current_version_id": None,
                "profile_summary_zh": "",
                "evidence_ids": [],
            }
        profile = _profile_from_status(status)
        if profile.get("owner_sender_id") != sender_id:
            raise ProfileStoreError("profile-read-not-authorized")

        current_version_id = profile.get("current_version_id")
        if current_version_id is not None and (
            not isinstance(current_version_id, str) or not current_version_id.strip()
        ):
            raise ProfileStoreError("profile-state-corrupt")
        conclusions = [
            copy.deepcopy(dict(item))
            for item in [
                *profile.get("conclusions", []),
                *profile.get("deferred_conclusions", []),
            ]
            if isinstance(item, Mapping)
        ]
        if len(conclusions) != len(profile.get("conclusions", [])) + len(
            profile.get("deferred_conclusions", [])
        ):
            raise ProfileStoreError("profile-state-corrupt")
        now = _now_utc(store)
        _refresh_preference_lifecycle(conclusions, now)
        retained, summary, _deferred = _compact_conclusions(conclusions, now)
        represented = sorted(
            (
                item
                for item in retained
                if item.get("active", True) and not item.get("historical")
            ),
            key=lambda item: (
                CATEGORY_ORDER.index(str(item["category"])),
                -int(item["priority"]),
                str(item["dedupe_key"]),
            ),
        )
        evidence_ids: list[str] = []
        for conclusion in represented:
            source_message_ids = conclusion.get("source_message_ids", [])
            if not isinstance(source_message_ids, list) or not all(
                isinstance(item, str) and item.strip()
                for item in source_message_ids
            ):
                raise ProfileStoreError("profile-state-corrupt")
            if message_id not in source_message_ids:
                continue
            raw_ids = conclusion.get("evidence_ids", [])
            if not isinstance(raw_ids, list) or not all(
                isinstance(item, str) and item.strip() for item in raw_ids
            ):
                raise ProfileStoreError("profile-state-corrupt")
            for evidence_id in raw_ids[-MAX_HEALTH_TURN_EVIDENCE_IDS_PER_CONCLUSION:]:
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
        if len(evidence_ids) > MAX_HEALTH_TURN_EVIDENCE_IDS:
            raise ProfileStoreError("profile-state-corrupt")
        _ensure_trusted_ingress_deadline(store, message_time, attempt_time)
        return {
            "context_schema_version": HEALTH_TURN_CONTEXT_SCHEMA_VERSION,
            "current_version_id": current_version_id,
            "profile_summary_zh": summary,
            "evidence_ids": evidence_ids,
        }


def read_profile(
    store: HealthSidecarStore, subject: str, sender_id: str
) -> Mapping[str, Any]:
    subject = _non_empty(subject, "subject-required")
    sender_id = _non_empty(sender_id, "sender-required")
    profile = _profile_from_status(
        store.read_subject_status(subject, _allow_profile_state=True)
    )
    if profile.get("owner_sender_id") != sender_id:
        raise ProfileStoreError("profile-read-not-authorized")
    return profile

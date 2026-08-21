"""Bounded, public projection for one reactive health-turn context."""

from __future__ import annotations

import copy
from typing import Any, Mapping


HEALTH_TURN_CONTEXT_SCHEMA_VERSION = 1

# The compact profile contains at most eight represented conclusions.  Three
# evidence references per conclusion preserves the existing three-signal rule
# for implicit preferences while bounding the complete turn projection.
MAX_HEALTH_TURN_EVIDENCE_IDS_PER_CONCLUSION = 3
MAX_HEALTH_TURN_EVIDENCE_IDS = 8 * MAX_HEALTH_TURN_EVIDENCE_IDS_PER_CONCLUSION

# A source excerpt is capped at 8 KiB by SourceLibrary.  Eight cards therefore
# leave ample room for the remaining context inside the 128 KiB socket frame.
MAX_HEALTH_TURN_SOURCE_CARDS = 8

PROFILE_CONTEXT_FIELDS = {
    "context_schema_version",
    "current_version_id",
    "profile_summary_zh",
    "evidence_ids",
}
HEALTH_TURN_CONTEXT_FIELDS = PROFILE_CONTEXT_FIELDS | {
    "source_cards",
    "source_status",
}
PUBLIC_SOURCE_CARD_FIELDS = (
    "card_id",
    "url",
    "source_type",
    "title",
    "version_hash",
    "key_excerpt",
    "tags",
    "fetched_utc",
    "review_due_utc",
    "untrusted_data",
)


class HealthTurnContextError(ValueError):
    """Raised when a health-turn projection could expose malformed context."""


def _required_text(value: Any, code: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise HealthTurnContextError(code)
    return value


def _validate_evidence_ids(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_HEALTH_TURN_EVIDENCE_IDS:
        raise HealthTurnContextError("invalid-health-turn-evidence-ids")
    evidence_ids: list[str] = []
    for item in value:
        evidence_id = _required_text(item, "invalid-health-turn-evidence-ids").strip()
        if evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)
    if len(evidence_ids) != len(value):
        raise HealthTurnContextError("invalid-health-turn-evidence-ids")
    return evidence_ids


def _validate_tags(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        raise HealthTurnContextError("invalid-health-turn-source-card")
    tags: dict[str, list[str]] = {}
    for category, raw_values in value.items():
        if not isinstance(category, str) or not category.strip():
            raise HealthTurnContextError("invalid-health-turn-source-card")
        if not isinstance(raw_values, list) or not all(
            isinstance(item, str) and item.strip() for item in raw_values
        ):
            raise HealthTurnContextError("invalid-health-turn-source-card")
        tags[category] = list(raw_values)
    return tags


def _validate_source_card(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(PUBLIC_SOURCE_CARD_FIELDS):
        raise HealthTurnContextError("invalid-health-turn-source-card")
    card = dict(value)
    for field in (
        "card_id",
        "url",
        "source_type",
        "version_hash",
        "key_excerpt",
        "fetched_utc",
        "review_due_utc",
    ):
        card[field] = _required_text(
            card.get(field), "invalid-health-turn-source-card"
        )
    card["title"] = _required_text(
        card.get("title"), "invalid-health-turn-source-card", allow_empty=True
    )
    card["tags"] = _validate_tags(card.get("tags"))
    if card.get("untrusted_data") is not True:
        raise HealthTurnContextError("invalid-health-turn-source-card")
    return copy.deepcopy(card)


def validate_health_turn_context(value: Any) -> dict[str, Any]:
    """Validate and copy the exact model-visible health-turn context shape."""
    if not isinstance(value, Mapping) or set(value) != HEALTH_TURN_CONTEXT_FIELDS:
        raise HealthTurnContextError("invalid-health-turn-context")
    context = dict(value)
    if context.get("context_schema_version") != HEALTH_TURN_CONTEXT_SCHEMA_VERSION:
        raise HealthTurnContextError("invalid-health-turn-context-version")
    current_version_id = context.get("current_version_id")
    if current_version_id is not None:
        current_version_id = _required_text(
            current_version_id, "invalid-health-turn-current-version"
        ).strip()
    summary = _required_text(
        context.get("profile_summary_zh"),
        "invalid-health-turn-profile-summary",
        allow_empty=True,
    )
    if len(summary) > 300:
        raise HealthTurnContextError("invalid-health-turn-profile-summary")
    evidence_ids = _validate_evidence_ids(context.get("evidence_ids"))

    source_cards = context.get("source_cards")
    if not isinstance(source_cards, list) or len(source_cards) > MAX_HEALTH_TURN_SOURCE_CARDS:
        raise HealthTurnContextError("invalid-health-turn-source-cards")
    projected_cards = [_validate_source_card(card) for card in source_cards]

    source_status = context.get("source_status")
    if not isinstance(source_status, Mapping) or set(source_status) != {
        "verified",
        "source",
        "reason",
    }:
        raise HealthTurnContextError("invalid-health-turn-source-status")
    verified = source_status.get("verified")
    if not isinstance(verified, bool):
        raise HealthTurnContextError("invalid-health-turn-source-status")
    source = _required_text(
        source_status.get("source"), "invalid-health-turn-source-status"
    ).strip()
    reason = source_status.get("reason")
    if reason is not None:
        reason = _required_text(reason, "invalid-health-turn-source-status").strip()
    if verified != bool(projected_cards):
        raise HealthTurnContextError("invalid-health-turn-source-status")

    return {
        "context_schema_version": HEALTH_TURN_CONTEXT_SCHEMA_VERSION,
        "current_version_id": current_version_id,
        "profile_summary_zh": summary,
        "evidence_ids": evidence_ids,
        "source_cards": projected_cards,
        "source_status": {
            "verified": verified,
            "source": source,
            "reason": reason,
        },
    }


def compose_health_turn_context(
    profile_context: Mapping[str, Any], source_result: Mapping[str, Any]
) -> dict[str, Any]:
    """Combine private profile/source state into the exact public projection."""
    if not isinstance(profile_context, Mapping) or set(profile_context) != PROFILE_CONTEXT_FIELDS:
        raise HealthTurnContextError("invalid-health-turn-profile-context")
    if not isinstance(source_result, Mapping):
        raise HealthTurnContextError("invalid-health-turn-source-result")
    verified = source_result.get("verified")
    source = source_result.get("source")
    cards = source_result.get("cards")
    if not isinstance(verified, bool) or not isinstance(source, str) or not source.strip():
        raise HealthTurnContextError("invalid-health-turn-source-result")
    if not isinstance(cards, list):
        raise HealthTurnContextError("invalid-health-turn-source-result")
    if not verified and cards:
        raise HealthTurnContextError("invalid-health-turn-source-result")
    if verified and not cards:
        raise HealthTurnContextError("invalid-health-turn-source-result")

    public_cards: list[dict[str, Any]] = []
    if verified:
        for raw_card in cards[:MAX_HEALTH_TURN_SOURCE_CARDS]:
            if not isinstance(raw_card, Mapping):
                raise HealthTurnContextError("invalid-health-turn-source-card")
            public_cards.append(
                {
                    field: copy.deepcopy(raw_card.get(field))
                    for field in PUBLIC_SOURCE_CARD_FIELDS
                }
            )
    reason = source_result.get("reason")
    context = {
        **dict(profile_context),
        "source_cards": public_cards,
        "source_status": {
            "verified": verified,
            "source": source,
            "reason": reason if reason is not None else None,
        },
    }
    return validate_health_turn_context(context)

"""Closed first-release topology for the owner's health portrait.

The portrait schema is deliberately data-only.  It fixes the six primary
domains and all 45 basic secondary topics agreed in Ticket 73, so runtime
components can validate references without asking a model to invent or repair
taxonomy.  Schema extension is a later, owner-approved capability; this
release therefore rejects every unknown domain or child topic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


class PortraitSchemaValidationError(ValueError):
    """Raised when a schema release or topic reference is not exact."""


PORTRAIT_SCHEMA_VERSION: Final = "portrait-schema-v1"

_DOMAIN_TOPIC_SLUGS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "clinical-and-safety",
        (
            "symptoms-and-health-problems",
            "owner-relayed-clinician-conclusions-and-history",
            "medication",
            "allergies-intolerances-and-danger-alerts",
            "tests-labs-and-vital-signs",
            "immunization",
            "procedures-and-surgery",
            "medical-devices",
            "family-history",
            "reproductive-health",
        ),
    ),
    (
        "physical-function-and-experience",
        (
            "pain",
            "fatigue-and-energy",
            "sleep",
            "sensory-function",
            "cardiopulmonary",
            "digestive-and-metabolic",
            "genitourinary",
            "movement-and-other-physical-function",
            "impact-on-daily-life",
        ),
    ),
    (
        "mental-cognitive-and-wellbeing",
        (
            "mood",
            "anxiety-and-stress",
            "positive-affect-and-life-satisfaction",
            "coping",
            "attention-memory-learning-and-decision-making",
            "psychological-distress",
            "functional-impairment",
            "self-harm-risk",
        ),
    ),
    (
        "activity-and-social-participation",
        (
            "communication-and-learning",
            "mobility",
            "self-care",
            "domestic-life",
            "education-and-work",
            "relationships",
            "social-roles-and-community-participation",
        ),
    ),
    (
        "health-behaviour-and-exposure",
        (
            "physical-activity",
            "dietary-pattern",
            "sleep-routine",
            "tobacco-and-nicotine",
            "alcohol-and-other-substances",
            "other-relevant-exposures",
        ),
    ),
    (
        "owner-goals-values-and-care-preferences",
        (
            "desired-health-or-functional-outcomes",
            "priorities",
            "time-horizon",
            "acceptable-burden-and-tradeoffs",
            "health-and-care-preferences",
        ),
    ),
)

PORTRAIT_DOMAIN_REFS: Final[tuple[str, ...]] = tuple(
    domain_ref for domain_ref, _topic_slugs in _DOMAIN_TOPIC_SLUGS
)
PORTRAIT_TOPIC_REFS: Final[tuple[str, ...]] = tuple(
    f"{domain_ref}/{topic_slug}"
    for domain_ref, topic_slugs in _DOMAIN_TOPIC_SLUGS
    for topic_slug in topic_slugs
)
PORTRAIT_TOPIC_REFS_BY_DOMAIN: Final[Mapping[str, tuple[str, ...]]] = (
    MappingProxyType(
        {
            domain_ref: tuple(
                f"{domain_ref}/{topic_slug}" for topic_slug in topic_slugs
            )
            for domain_ref, topic_slugs in _DOMAIN_TOPIC_SLUGS
        }
    )
)


def _release_digest(version: str, ordered_topic_refs: tuple[str, ...]) -> str:
    canonical = json.dumps(
        {
            "ordered_topic_refs": list(ordered_topic_refs),
            "version": version,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


@dataclass(frozen=True, slots=True)
class PortraitSchemaRelease:
    """Immutable identity and ordering of an approved portrait topology."""

    version: str = PORTRAIT_SCHEMA_VERSION
    ordered_topic_refs: tuple[str, ...] = PORTRAIT_TOPIC_REFS

    def __post_init__(self) -> None:
        if type(self.version) is not str or self.version != PORTRAIT_SCHEMA_VERSION:
            raise PortraitSchemaValidationError("unknown portrait schema version")
        if (
            type(self.ordered_topic_refs) is not tuple
            or self.ordered_topic_refs != PORTRAIT_TOPIC_REFS
            or any(type(topic_ref) is not str for topic_ref in self.ordered_topic_refs)
        ):
            raise PortraitSchemaValidationError(
                "portrait schema topics do not match the approved release"
            )

    @property
    def domain_refs(self) -> tuple[str, ...]:
        """Return the six primary domains in their approved display order."""

        return PORTRAIT_DOMAIN_REFS

    @property
    def topic_refs_by_domain(self) -> Mapping[str, tuple[str, ...]]:
        """Return an immutable domain-to-topic index for display navigation."""

        return PORTRAIT_TOPIC_REFS_BY_DOMAIN

    @property
    def digest(self) -> str:
        """Return the SHA-256 identity of version plus exact topic ordering."""

        return _release_digest(self.version, self.ordered_topic_refs)

    def validate_topic_ref(self, topic_ref: object) -> str:
        """Return an exact approved reference, rejecting every extension."""

        if type(topic_ref) is not str or topic_ref not in PORTRAIT_TOPIC_REFS:
            raise PortraitSchemaValidationError("unknown portrait topic reference")
        return topic_ref

    def to_wire(self) -> dict[str, object]:
        """Serialize a canonical, self-identifying release descriptor."""

        return {
            "version": self.version,
            "ordered_topic_refs": list(self.ordered_topic_refs),
            "digest": self.digest,
        }

    @classmethod
    def from_wire(cls, value: object) -> "PortraitSchemaRelease":
        """Parse only the exact release descriptor; fail closed on drift."""

        if type(value) is not dict or set(value) != {
            "version",
            "ordered_topic_refs",
            "digest",
        }:
            raise PortraitSchemaValidationError("invalid portrait schema wire fields")
        version = value["version"]
        topic_refs = value["ordered_topic_refs"]
        digest = value["digest"]
        if type(version) is not str or type(topic_refs) is not list:
            raise PortraitSchemaValidationError("invalid portrait schema wire values")
        if any(type(topic_ref) is not str for topic_ref in topic_refs):
            raise PortraitSchemaValidationError("invalid portrait schema topic values")
        release = cls(version=version, ordered_topic_refs=tuple(topic_refs))
        if type(digest) is not str or digest != release.digest:
            raise PortraitSchemaValidationError("portrait schema digest mismatch")
        return release


FIRST_RELEASE_PORTRAIT_SCHEMA: Final = PortraitSchemaRelease()


def validate_topic_ref(topic_ref: object) -> str:
    """Validate against the only currently approved portrait release."""

    return FIRST_RELEASE_PORTRAIT_SCHEMA.validate_topic_ref(topic_ref)


__all__ = [
    "FIRST_RELEASE_PORTRAIT_SCHEMA",
    "PORTRAIT_DOMAIN_REFS",
    "PORTRAIT_SCHEMA_VERSION",
    "PORTRAIT_TOPIC_REFS",
    "PORTRAIT_TOPIC_REFS_BY_DOMAIN",
    "PortraitSchemaRelease",
    "PortraitSchemaValidationError",
    "validate_topic_ref",
]

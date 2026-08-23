"""Owner-independent governed knowledge value contracts for Ticket 113."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


class KnowledgeContractViolation(ValueError):
    """A value cannot cross the governed knowledge seam."""


@dataclass(frozen=True)
class KnowledgeGap:
    """An explicit reason that governed knowledge cannot be released."""

    topic_id: str
    reason_code: str

    def __post_init__(self) -> None:
        _text(self.topic_id, "knowledge topic")
        _text(self.reason_code, "knowledge gap reason")


def _mapping(value: object, fields: frozenset[str], name: str) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != fields:
        raise KnowledgeContractViolation(f"invalid {name}")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > 65536:
        raise KnowledgeContractViolation(f"invalid {name}")
    return value


def _texts(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise KnowledgeContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise KnowledgeContractViolation(f"invalid {name}")
    return result


def _time(value: object, name: str) -> str:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise KnowledgeContractViolation(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KnowledgeContractViolation(f"invalid {name}")
    return text


def _sha(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise KnowledgeContractViolation(f"invalid {name}")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise KnowledgeContractViolation(f"invalid {name}") from exc
    return text


@dataclass(frozen=True)
class KnowledgePublicationInput:
    topic_id: str
    governance_schedule_id: str
    source_id: str
    source_version: str
    rights_status: str
    chinese_status: str
    applicability: tuple[str, ...]
    professional_review_status: str
    professional_review_ref: str
    content: str
    published_at: str
    expires_at: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.topic_id, "knowledge topic"),
            (self.governance_schedule_id, "governance schedule"),
            (self.source_id, "knowledge source"),
            (self.source_version, "source version"),
            (self.rights_status, "rights status"),
            (self.chinese_status, "Chinese status"),
            (self.professional_review_status, "professional review status"),
            (self.professional_review_ref, "professional review reference"),
            (self.content, "knowledge content"),
        ):
            _text(value, name)
        if type(self.applicability) is not tuple or not self.applicability or any(type(item) is not str or not item for item in self.applicability):
            raise KnowledgeContractViolation("invalid knowledge applicability")
        _time(self.published_at, "publication time")
        _time(self.expires_at, "expiry time")

    def to_wire(self) -> dict[str, object]:
        return {
            "topic_id": self.topic_id,
            "governance_schedule_id": self.governance_schedule_id,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "rights_status": self.rights_status,
            "chinese_status": self.chinese_status,
            "applicability": list(self.applicability),
            "professional_review_status": self.professional_review_status,
            "professional_review_ref": self.professional_review_ref,
            "content": self.content,
            "published_at": self.published_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_wire(cls, value: object) -> "KnowledgePublicationInput":
        fields = _mapping(value, frozenset({
            "topic_id", "governance_schedule_id", "source_id", "source_version",
            "rights_status", "chinese_status", "applicability",
            "professional_review_status", "professional_review_ref", "content",
            "published_at", "expires_at",
        }), "knowledge publication input")
        return cls(
            _text(fields["topic_id"], "knowledge topic"),
            _text(fields["governance_schedule_id"], "governance schedule"),
            _text(fields["source_id"], "knowledge source"),
            _text(fields["source_version"], "source version"),
            _text(fields["rights_status"], "rights status"),
            _text(fields["chinese_status"], "Chinese status"),
            _texts(fields["applicability"], "knowledge applicability"),
            _text(fields["professional_review_status"], "professional review status"),
            _text(fields["professional_review_ref"], "professional review reference"),
            _text(fields["content"], "knowledge content"),
            _time(fields["published_at"], "publication time"),
            _time(fields["expires_at"], "expiry time"),
        )


@dataclass(frozen=True)
class KnowledgeRelease:
    release_id: str
    release_version: str
    stage: str
    topic_id: str
    source_id: str
    source_version: str
    rights_status: str
    chinese_status: str
    applicability: tuple[str, ...]
    professional_review_status: str
    professional_review_ref: str
    content_hash: str
    published_at: str
    expires_at: str
    withdrawn: bool

    def __post_init__(self) -> None:
        for value, name in (
            (self.release_id, "release identifier"),
            (self.release_version, "release version"),
            (self.topic_id, "knowledge topic"),
            (self.source_id, "knowledge source"),
            (self.source_version, "source version"),
            (self.rights_status, "rights status"),
            (self.chinese_status, "Chinese status"),
            (self.professional_review_status, "professional review status"),
            (self.professional_review_ref, "professional review reference"),
        ):
            _text(value, name)
        if self.stage != "staged":
            raise KnowledgeContractViolation("knowledge release must be staged")
        if type(self.applicability) is not tuple or not self.applicability or any(type(item) is not str or not item for item in self.applicability):
            raise KnowledgeContractViolation("invalid knowledge applicability")
        _sha(self.content_hash, "knowledge content hash")
        _time(self.published_at, "publication time")
        _time(self.expires_at, "expiry time")
        if type(self.withdrawn) is not bool:
            raise KnowledgeContractViolation("invalid withdrawal status")

    def to_wire(self) -> dict[str, object]:
        return {
            "release_id": self.release_id,
            "release_version": self.release_version,
            "stage": self.stage,
            "topic_id": self.topic_id,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "rights_status": self.rights_status,
            "chinese_status": self.chinese_status,
            "applicability": list(self.applicability),
            "professional_review_status": self.professional_review_status,
            "professional_review_ref": self.professional_review_ref,
            "content_hash": self.content_hash,
            "published_at": self.published_at,
            "expires_at": self.expires_at,
            "withdrawn": self.withdrawn,
        }

    @classmethod
    def from_wire(cls, value: object) -> "KnowledgeRelease":
        fields = _mapping(value, frozenset({
            "release_id", "release_version", "stage", "topic_id", "source_id",
            "source_version", "rights_status", "chinese_status", "applicability",
            "professional_review_status", "professional_review_ref", "content_hash",
            "published_at", "expires_at", "withdrawn",
        }), "knowledge release")
        withdrawn = fields["withdrawn"]
        if type(withdrawn) is not bool:
            raise KnowledgeContractViolation("invalid withdrawal status")
        return cls(
            _text(fields["release_id"], "release identifier"),
            _text(fields["release_version"], "release version"),
            _text(fields["stage"], "release stage"),
            _text(fields["topic_id"], "knowledge topic"),
            _text(fields["source_id"], "knowledge source"),
            _text(fields["source_version"], "source version"),
            _text(fields["rights_status"], "rights status"),
            _text(fields["chinese_status"], "Chinese status"),
            _texts(fields["applicability"], "knowledge applicability"),
            _text(fields["professional_review_status"], "professional review status"),
            _text(fields["professional_review_ref"], "professional review reference"),
            _sha(fields["content_hash"], "knowledge content hash"),
            _time(fields["published_at"], "publication time"),
            _time(fields["expires_at"], "expiry time"),
            withdrawn,
        )


class KnowledgePublisher:
    """Build deterministic staged releases from owner-independent input only."""

    def publish(
        self,
        publication: KnowledgePublicationInput,
        *,
        release_version: str,
    ) -> KnowledgeRelease | KnowledgeGap:
        version = _text(release_version, "release version")
        if publication.rights_status != "approved":
            return KnowledgeGap(publication.topic_id, "knowledge-rights-gap")
        if publication.chinese_status != "reviewed-chinese":
            return KnowledgeGap(publication.topic_id, "knowledge-chinese-gap")
        if publication.professional_review_status != "approved":
            return KnowledgeGap(publication.topic_id, "knowledge-review-gap")
        content_hash = "sha256:" + hashlib.sha256(publication.content.encode("utf-8")).hexdigest()
        return KnowledgeRelease(
            release_id="knowledge-release:" + content_hash[7:],
            release_version=version,
            stage="staged",
            topic_id=publication.topic_id,
            source_id=publication.source_id,
            source_version=publication.source_version,
            rights_status=publication.rights_status,
            chinese_status=publication.chinese_status,
            applicability=publication.applicability,
            professional_review_status=publication.professional_review_status,
            professional_review_ref=publication.professional_review_ref,
            content_hash=content_hash,
            published_at=publication.published_at,
            expires_at=publication.expires_at,
            withdrawn=False,
        )


class ImmutableKnowledgeRegistry:
    """Retain immutable content-addressed staged releases in memory."""

    def __init__(self) -> None:
        self._by_release_id: dict[str, KnowledgeRelease] = {}
        self._by_topic_version: dict[tuple[str, str], KnowledgeRelease] = {}

    def stage(self, release: KnowledgeRelease) -> KnowledgeRelease:
        expected_id = "knowledge-release:" + release.content_hash[7:]
        if release.release_id != expected_id:
            raise KnowledgeContractViolation("release identifier does not match content hash")
        existing = self._by_release_id.get(release.release_id)
        if existing is not None and existing != release:
            raise KnowledgeContractViolation("content-addressed release is immutable")
        version_key = (release.topic_id, release.release_version)
        versioned = self._by_topic_version.get(version_key)
        if versioned is not None and versioned != release:
            raise KnowledgeContractViolation("knowledge release version is immutable")
        self._by_release_id[release.release_id] = release
        self._by_topic_version[version_key] = release
        return release

    def resolve(self, topic_id: str, *, at: str) -> KnowledgeRelease | KnowledgeGap:
        topic = _text(topic_id, "knowledge topic")
        at_text = _time(at, "knowledge resolution time")
        at_time = datetime.fromisoformat(at_text)
        releases = [
            release
            for (release_topic, _), release in self._by_topic_version.items()
            if release_topic == topic and datetime.fromisoformat(release.published_at) <= at_time
        ]
        if not releases:
            return KnowledgeGap(topic, "knowledge-missing")
        release = max(
            releases,
            key=lambda item: (
                datetime.fromisoformat(item.published_at),
                item.release_version,
            ),
        )
        if release.withdrawn:
            return KnowledgeGap(topic, "knowledge-withdrawn")
        if at_time >= datetime.fromisoformat(release.expires_at):
            return KnowledgeGap(topic, "knowledge-expired")
        return release

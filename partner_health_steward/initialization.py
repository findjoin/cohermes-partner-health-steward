"""Typed owner-initialization values and system-attested ``health-init`` use.

The classes in this module deliberately separate three claims:

* an owner supplied a complete initialization candidate;
* the versioned ``health-init`` asset actually ran in this process; and
* a core accepted the resulting fact into a prepared authority transition.

Neither a caller-supplied boolean nor model-authored text can construct the
second claim.  Only :class:`HealthInitAttestor` can authenticate it, and the
proof is bound to the exact owner request and admitted source delivery.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .authority import (
    AuthoritySnapshot,
    AuthorityValidationError,
    validate_opaque_text,
)


HEALTH_INIT_CANONICAL_NAME = "health-init"
INITIAL_DATA_BOUNDARY = (
    "health-portrait",
    "health-evidence",
    "health-tasks",
)
INITIALIZATION_DISCLOSED_TOPICS = (
    "health-data-scope",
    "daily-review",
    "health-task-automation",
    "proactive-support",
    "first-hop-model-route",
    "support-contact",
    "owner-data-rights",
    "unknown-effects-not-retried",
)
INITIAL_PORTRAIT_DOMAINS = (
    "clinical-and-safety",
    "physical-function-and-experience",
    "mental-cognitive-and-wellbeing",
    "activity-and-social-participation",
    "health-behaviour-and-exposure",
    "owner-goals-values-and-care-preferences",
)

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_HMAC_SHA256_RE = re.compile(r"hmac-sha256:[0-9a-f]{64}\Z")
_CONTACT_WINDOW_RE = re.compile(
    r"(?P<start_hour>[01][0-9]|2[0-3]):(?P<start_minute>[0-5][0-9])-"
    r"(?P<end_hour>[01][0-9]|2[0-3]):(?P<end_minute>[0-5][0-9])\Z"
)


def _required_mapping(
    value: object,
    fields: frozenset[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise AuthorityValidationError(f"invalid {name}")
    return value


def _required_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise AuthorityValidationError(f"invalid {name}")
    return value


def _required_text_tuple(
    value: object,
    name: str,
    *,
    expected: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise AuthorityValidationError(f"invalid {name}")
    validated = tuple(validate_opaque_text(item, name) for item in value)
    if validated != value or (expected is not None and validated != expected):
        raise AuthorityValidationError(f"invalid {name}")
    return validated


def _required_storage_text_list(
    value: object,
    name: str,
) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise AuthorityValidationError(f"invalid {name}")
    validated = tuple(validate_opaque_text(item, name) for item in value)
    if list(validated) != value:
        raise AuthorityValidationError(f"invalid {name}")
    return validated


def _sha256_text(value: object, name: str) -> str:
    text = validate_opaque_text(value, name)
    if _SHA256_RE.fullmatch(text) is None:
        raise AuthorityValidationError(f"invalid {name}")
    return text


def _timestamp(value: object, name: str) -> str:
    text = validate_opaque_text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AuthorityValidationError(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError(f"invalid {name}")
    return text


def _iana_timezone(value: object) -> str:
    text = validate_opaque_text(value, "timezone")
    # IANA identifiers are names, never an unscoped numeric offset.  ZoneInfo
    # is authoritative when the host ships tzdata.  Some supported Windows
    # hosts do not, so dateutil's bundled IANA database is the narrow fallback.
    if text.startswith(("+", "-")) or "/" not in text and text != "UTC":
        raise AuthorityValidationError("invalid timezone")
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError:
        try:
            from dateutil.tz import gettz  # type: ignore[import-not-found]
        except ImportError as exc:
            if text not in {"Asia/Shanghai", "Etc/UTC", "UTC"}:
                raise AuthorityValidationError("invalid timezone") from exc
        else:
            if gettz(text) is None:
                raise AuthorityValidationError("invalid timezone")
    return text


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError) as exc:
        raise AuthorityValidationError("invalid canonical initialization value") from exc


def stable_digest(value: object) -> str:
    """Return the one canonical digest format used by initialization values."""

    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class HealthInitAsset:
    """The exact approved, versioned initialization asset that was executed."""

    version: str
    asset_digest: str
    disclosure_version: str
    canonical_name: str = HEALTH_INIT_CANONICAL_NAME

    def __post_init__(self) -> None:
        validate_opaque_text(self.version, "health-init version")
        _sha256_text(self.asset_digest, "health-init asset digest")
        validate_opaque_text(self.disclosure_version, "health-init disclosure version")
        if (
            type(self.canonical_name) is not str
            or self.canonical_name != HEALTH_INIT_CANONICAL_NAME
        ):
            raise AuthorityValidationError("invalid health-init canonical name")

    def to_storage(self) -> dict[str, object]:
        return {
            "canonical_name": self.canonical_name,
            "version": self.version,
            "asset_digest": self.asset_digest,
            "disclosure_version": self.disclosure_version,
        }

    @classmethod
    def from_storage(cls, value: object) -> "HealthInitAsset":
        stored = _required_mapping(
            value,
            frozenset(
                {"canonical_name", "version", "asset_digest", "disclosure_version"}
            ),
            "health-init asset",
        )
        return cls(
            canonical_name=stored["canonical_name"],  # type: ignore[arg-type]
            version=stored["version"],  # type: ignore[arg-type]
            asset_digest=stored["asset_digest"],  # type: ignore[arg-type]
            disclosure_version=stored["disclosure_version"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class InitialPreferences:
    """The small preference surface actually opened during initialization."""

    contact_window: str
    expression_style: str
    proactive_support: bool

    def __post_init__(self) -> None:
        contact_window = validate_opaque_text(self.contact_window, "contact window")
        if _CONTACT_WINDOW_RE.fullmatch(contact_window) is None:
            raise AuthorityValidationError("invalid contact window")
        validate_opaque_text(self.expression_style, "expression style")
        _required_bool(self.proactive_support, "proactive support")

    def to_storage(self) -> dict[str, object]:
        return {
            "contact_window": self.contact_window,
            "expression_style": self.expression_style,
            "proactive_support": self.proactive_support,
        }

    @classmethod
    def from_storage(cls, value: object) -> "InitialPreferences":
        stored = _required_mapping(
            value,
            frozenset({"contact_window", "expression_style", "proactive_support"}),
            "initial preferences",
        )
        return cls(
            contact_window=stored["contact_window"],  # type: ignore[arg-type]
            expression_style=stored["expression_style"],  # type: ignore[arg-type]
            proactive_support=stored["proactive_support"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class SupportContactBoundary:
    """A configured contact reference, not approval or proof of delivery."""

    contact_ref: str
    method: str
    purpose: str

    def __post_init__(self) -> None:
        validate_opaque_text(self.contact_ref, "support contact reference")
        if type(self.method) is not str or self.method != "weixin":
            raise AuthorityValidationError("invalid support contact method")
        if type(self.purpose) is not str or self.purpose != "emergency-support":
            raise AuthorityValidationError("invalid support contact purpose")

    def to_storage(self) -> dict[str, object]:
        return {
            "contact_ref": self.contact_ref,
            "method": self.method,
            "purpose": self.purpose,
        }

    @classmethod
    def from_storage(cls, value: object) -> "SupportContactBoundary":
        stored = _required_mapping(
            value,
            frozenset({"contact_ref", "method", "purpose"}),
            "support contact boundary",
        )
        return cls(
            contact_ref=stored["contact_ref"],  # type: ignore[arg-type]
            method=stored["method"],  # type: ignore[arg-type]
            purpose=stored["purpose"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class OwnerInitialization:
    """One complete owner candidate, still distinct from an enabled result."""

    workflow_id: str
    admission_causal_id: str
    owner_consent: bool
    first_hop_route: str
    first_hop_route_consent: bool
    timezone: str
    preferences: InitialPreferences
    data_boundary: tuple[str, ...]
    support_contact: SupportContactBoundary | None

    def __post_init__(self) -> None:
        validate_opaque_text(self.workflow_id, "initialization workflow identifier")
        validate_opaque_text(self.admission_causal_id, "admission causal identifier")
        _required_bool(self.owner_consent, "owner consent")
        validate_opaque_text(self.first_hop_route, "first-hop route")
        _required_bool(self.first_hop_route_consent, "first-hop route consent")
        _iana_timezone(self.timezone)
        if type(self.preferences) is not InitialPreferences:
            raise AuthorityValidationError("invalid initial preferences")
        _required_text_tuple(
            self.data_boundary,
            "initial data boundary",
            expected=INITIAL_DATA_BOUNDARY,
        )
        if (
            self.support_contact is not None
            and type(self.support_contact) is not SupportContactBoundary
        ):
            raise AuthorityValidationError("invalid support contact boundary")

    @property
    def incomplete_reason(self) -> str | None:
        if not self.owner_consent:
            return "owner-consent-required"
        if not self.first_hop_route_consent:
            return "first-hop-route-consent-required"
        return None

    def require_complete(self) -> None:
        reason = self.incomplete_reason
        if reason is not None:
            raise AuthorityValidationError(reason)

    def to_storage(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "admission_causal_id": self.admission_causal_id,
            "owner_consent": self.owner_consent,
            "first_hop_route": self.first_hop_route,
            "first_hop_route_consent": self.first_hop_route_consent,
            "timezone": self.timezone,
            "preferences": self.preferences.to_storage(),
            "data_boundary": list(self.data_boundary),
            "support_contact": (
                None if self.support_contact is None else self.support_contact.to_storage()
            ),
        }

    @classmethod
    def from_storage(cls, value: object) -> "OwnerInitialization":
        stored = _required_mapping(
            value,
            frozenset(
                {
                    "workflow_id",
                    "admission_causal_id",
                    "owner_consent",
                    "first_hop_route",
                    "first_hop_route_consent",
                    "timezone",
                    "preferences",
                    "data_boundary",
                    "support_contact",
                }
            ),
            "owner initialization",
        )
        return cls(
            workflow_id=stored["workflow_id"],  # type: ignore[arg-type]
            admission_causal_id=stored["admission_causal_id"],  # type: ignore[arg-type]
            owner_consent=stored["owner_consent"],  # type: ignore[arg-type]
            first_hop_route=stored["first_hop_route"],  # type: ignore[arg-type]
            first_hop_route_consent=stored["first_hop_route_consent"],  # type: ignore[arg-type]
            timezone=stored["timezone"],  # type: ignore[arg-type]
            preferences=InitialPreferences.from_storage(stored["preferences"]),
            data_boundary=_required_storage_text_list(
                stored["data_boundary"], "initial data boundary"
            ),
            support_contact=(
                None
                if stored["support_contact"] is None
                else SupportContactBoundary.from_storage(stored["support_contact"])
            ),
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_storage())

    @property
    def request_digest(self) -> str:
        return self.digest

    def canonical_digest(self) -> str:
        return self.digest


@dataclass(frozen=True)
class OwnerConsentEvidence:
    """Owner-visible consent callback bound to one admitted initialization source.

    The adapter may only construct this payload after presenting the approved
    disclosure.  Core reparses the admitted message body and binds it to the
    exact candidate, so caller-supplied booleans alone cannot prove consent.
    """

    workflow_id: str
    admission_causal_id: str
    initialization_digest: str
    disclosure_version: str
    disclosed_topics: tuple[str, ...]
    owner_confirmed: bool
    first_hop_route_confirmed: bool
    schema: str = "health-init-owner-consent-v1"

    def __post_init__(self) -> None:
        if type(self.schema) is not str or self.schema != "health-init-owner-consent-v1":
            raise AuthorityValidationError("invalid owner consent evidence")
        validate_opaque_text(self.workflow_id, "initialization workflow identifier")
        validate_opaque_text(self.admission_causal_id, "admission causal identifier")
        _sha256_text(self.initialization_digest, "initialization digest")
        validate_opaque_text(self.disclosure_version, "health-init disclosure version")
        _required_text_tuple(
            self.disclosed_topics,
            "initialization disclosed topics",
            expected=INITIALIZATION_DISCLOSED_TOPICS,
        )
        _required_bool(self.owner_confirmed, "owner consent confirmation")
        _required_bool(
            self.first_hop_route_confirmed,
            "first-hop route confirmation",
        )

    @classmethod
    def for_initialization(
        cls,
        initialization: OwnerInitialization,
        asset: HealthInitAsset,
    ) -> "OwnerConsentEvidence":
        if type(initialization) is not OwnerInitialization or type(asset) is not HealthInitAsset:
            raise AuthorityValidationError("invalid owner consent evidence")
        initialization.require_complete()
        return cls(
            workflow_id=initialization.workflow_id,
            admission_causal_id=initialization.admission_causal_id,
            initialization_digest=initialization.digest,
            disclosure_version=asset.disclosure_version,
            disclosed_topics=INITIALIZATION_DISCLOSED_TOPICS,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "workflow_id": self.workflow_id,
            "admission_causal_id": self.admission_causal_id,
            "initialization_digest": self.initialization_digest,
            "disclosure_version": self.disclosure_version,
            "disclosed_topics": list(self.disclosed_topics),
            "owner_confirmed": self.owner_confirmed,
            "first_hop_route_confirmed": self.first_hop_route_confirmed,
        }

    def to_message_body(self) -> str:
        return _canonical_bytes(self.to_storage()).decode("utf-8")

    @classmethod
    def from_message_body(cls, value: object) -> "OwnerConsentEvidence":
        if type(value) is not str or not value:
            raise AuthorityValidationError("invalid owner consent evidence")
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise AuthorityValidationError("invalid owner consent evidence") from exc
        if len(encoded) > 16_384:
            raise AuthorityValidationError("invalid owner consent evidence")

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in pairs:
                if type(key) is not str or key in result:
                    raise AuthorityValidationError("invalid owner consent evidence")
                result[key] = item
            return result

        try:
            decoded = json.loads(value, object_pairs_hook=reject_duplicate_keys)
        except (
            json.JSONDecodeError,
            UnicodeError,
            RecursionError,
            AuthorityValidationError,
        ) as exc:
            raise AuthorityValidationError("invalid owner consent evidence") from exc
        return cls.from_storage(decoded)

    @classmethod
    def from_storage(cls, value: object) -> "OwnerConsentEvidence":
        stored = _required_mapping(
            value,
            frozenset(
                {
                    "schema",
                    "workflow_id",
                    "admission_causal_id",
                    "initialization_digest",
                    "disclosure_version",
                    "disclosed_topics",
                    "owner_confirmed",
                    "first_hop_route_confirmed",
                }
            ),
            "owner consent evidence",
        )
        return cls(
            schema=stored["schema"],  # type: ignore[arg-type]
            workflow_id=stored["workflow_id"],  # type: ignore[arg-type]
            admission_causal_id=stored["admission_causal_id"],  # type: ignore[arg-type]
            initialization_digest=stored["initialization_digest"],  # type: ignore[arg-type]
            disclosure_version=stored["disclosure_version"],  # type: ignore[arg-type]
            disclosed_topics=_required_storage_text_list(
                stored["disclosed_topics"],
                "initialization disclosed topics",
            ),
            owner_confirmed=stored["owner_confirmed"],  # type: ignore[arg-type]
            first_hop_route_confirmed=stored["first_hop_route_confirmed"],  # type: ignore[arg-type]
        )

    def matches(
        self,
        initialization: OwnerInitialization,
        asset: HealthInitAsset,
    ) -> bool:
        return (
            type(initialization) is OwnerInitialization
            and type(asset) is HealthInitAsset
            and self.workflow_id == initialization.workflow_id
            and self.admission_causal_id == initialization.admission_causal_id
            and self.initialization_digest == initialization.digest
            and self.disclosure_version == asset.disclosure_version
            and self.disclosed_topics == INITIALIZATION_DISCLOSED_TOPICS
            and self.owner_confirmed is True
            and self.first_hop_route_confirmed is True
        )


@dataclass(frozen=True)
class SkillUseFact:
    """Minimal durable system fact for one actual ``health-init`` execution."""

    canonical_name: str
    version: str
    asset_digest: str
    disclosure_version: str
    used_at: str
    workflow_id: str
    admission_causal_id: str

    def __post_init__(self) -> None:
        if (
            type(self.canonical_name) is not str
            or self.canonical_name != HEALTH_INIT_CANONICAL_NAME
        ):
            raise AuthorityValidationError("invalid health-init canonical name")
        validate_opaque_text(self.version, "health-init version")
        _sha256_text(self.asset_digest, "health-init asset digest")
        validate_opaque_text(self.disclosure_version, "health-init disclosure version")
        _timestamp(self.used_at, "health-init used_at")
        validate_opaque_text(self.workflow_id, "initialization workflow identifier")
        validate_opaque_text(self.admission_causal_id, "admission causal identifier")

    def to_storage(self) -> dict[str, object]:
        return {
            "canonical_name": self.canonical_name,
            "version": self.version,
            "asset_digest": self.asset_digest,
            "disclosure_version": self.disclosure_version,
            "used_at": self.used_at,
            "workflow_id": self.workflow_id,
            "admission_causal_id": self.admission_causal_id,
        }

    @classmethod
    def from_storage(cls, value: object) -> "SkillUseFact":
        stored = _required_mapping(
            value,
            frozenset(
                {
                    "canonical_name",
                    "version",
                    "asset_digest",
                    "disclosure_version",
                    "used_at",
                    "workflow_id",
                    "admission_causal_id",
                }
            ),
            "health-init use fact",
        )
        return cls(**stored)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SkillUseProof:
    """HMAC-authenticated system proof; never a caller assertion of use."""

    skill_use: SkillUseFact
    request_digest: str
    key_id: str
    signature: str

    def __post_init__(self) -> None:
        if type(self.skill_use) is not SkillUseFact:
            raise AuthorityValidationError("invalid health-init use fact")
        _sha256_text(self.request_digest, "health-init request digest")
        validate_opaque_text(self.key_id, "health-init attestor key identifier")
        signature = validate_opaque_text(self.signature, "health-init signature")
        if _HMAC_SHA256_RE.fullmatch(signature) is None:
            raise AuthorityValidationError("invalid health-init signature")

    @property
    def fact(self) -> SkillUseFact:
        return self.skill_use

    @property
    def workflow_id(self) -> str:
        return self.skill_use.workflow_id

    @property
    def admission_causal_id(self) -> str:
        return self.skill_use.admission_causal_id

    def unsigned_storage(self) -> dict[str, object]:
        return {
            "skill_use": self.skill_use.to_storage(),
            "request_digest": self.request_digest,
            "key_id": self.key_id,
        }

    def to_storage(self) -> dict[str, object]:
        return {**self.unsigned_storage(), "signature": self.signature}

    @classmethod
    def from_storage(cls, value: object) -> "SkillUseProof":
        stored = _required_mapping(
            value,
            frozenset({"skill_use", "request_digest", "key_id", "signature"}),
            "health-init use proof",
        )
        return cls(
            skill_use=SkillUseFact.from_storage(stored["skill_use"]),
            request_digest=stored["request_digest"],  # type: ignore[arg-type]
            key_id=stored["key_id"],  # type: ignore[arg-type]
            signature=stored["signature"],  # type: ignore[arg-type]
        )


class HealthInitAttestor:
    """Host-held HMAC authority for actual health-init runtime executions."""

    __slots__ = ("_key", "_key_id")

    def __init__(self, key: bytes, *, key_id: str) -> None:
        if type(key) is not bytes or len(key) < 32:
            raise AuthorityValidationError("invalid health-init attestor key")
        self._key = key
        self._key_id = validate_opaque_text(key_id, "health-init attestor key identifier")

    @property
    def key_id(self) -> str:
        return self._key_id

    def _signature(self, unsigned: Mapping[str, object]) -> str:
        return "hmac-sha256:" + hmac.new(
            self._key,
            _canonical_bytes(dict(unsigned)),
            hashlib.sha256,
        ).hexdigest()

    def sign(
        self,
        skill_use: SkillUseFact,
        *,
        request_digest: str,
    ) -> SkillUseProof:
        if type(skill_use) is not SkillUseFact:
            raise AuthorityValidationError("invalid health-init use fact")
        request_digest = _sha256_text(request_digest, "health-init request digest")
        unsigned = {
            "skill_use": skill_use.to_storage(),
            "request_digest": request_digest,
            "key_id": self.key_id,
        }
        return SkillUseProof(
            skill_use=skill_use,
            request_digest=request_digest,
            key_id=self.key_id,
            signature=self._signature(unsigned),
        )

    def verify(
        self,
        proof: object,
        initialization: OwnerInitialization | None = None,
    ) -> bool:
        if type(proof) is not SkillUseProof or proof.key_id != self.key_id:
            return False
        if initialization is not None:
            if type(initialization) is not OwnerInitialization:
                return False
            if (
                proof.request_digest != initialization.digest
                or proof.workflow_id != initialization.workflow_id
                or proof.admission_causal_id != initialization.admission_causal_id
            ):
                return False
        expected = self._signature(proof.unsigned_storage())
        return hmac.compare_digest(expected, proof.signature)


class HealthInitRuntime:
    """Executes one approved asset and caches exact workflow replay proofs."""

    def __init__(
        self,
        asset: HealthInitAsset,
        attestor: HealthInitAttestor,
        *,
        clock: Callable[[], datetime] | None = None,
        executor: Callable[[HealthInitAsset, OwnerInitialization], bool] | None = None,
    ) -> None:
        if type(asset) is not HealthInitAsset or type(attestor) is not HealthInitAttestor:
            raise AuthorityValidationError("invalid health-init runtime")
        if clock is not None and not callable(clock):
            raise AuthorityValidationError("invalid health-init clock")
        if executor is not None and not callable(executor):
            raise AuthorityValidationError("invalid health-init executor")
        self._asset = asset
        self._attestor = attestor
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._executor = executor or self._execute_builtin_asset
        self._lock = threading.Lock()
        self._workflow_proofs: dict[str, tuple[str, SkillUseProof]] = {}

    @property
    def asset(self) -> HealthInitAsset:
        return self._asset

    def run(self, initialization: OwnerInitialization) -> SkillUseProof:
        if type(initialization) is not OwnerInitialization:
            raise AuthorityValidationError("invalid owner initialization")
        initialization.require_complete()
        request_digest = initialization.digest
        with self._lock:
            existing = self._workflow_proofs.get(initialization.workflow_id)
            if existing is not None:
                existing_digest, proof = existing
                if existing_digest != request_digest:
                    raise AuthorityValidationError("health-init workflow conflict")
                return proof
            try:
                executed = self._executor(self._asset, initialization)
            except Exception as exc:
                raise AuthorityValidationError("health-init-execution-failed") from exc
            if executed is not True:
                raise AuthorityValidationError("health-init-execution-failed")
            used_at_value = self._clock()
            if type(used_at_value) is not datetime:
                raise AuthorityValidationError("invalid health-init clock result")
            if used_at_value.tzinfo is None or used_at_value.utcoffset() is None:
                raise AuthorityValidationError("invalid health-init clock result")
            used_at = used_at_value.isoformat()
            skill_use = SkillUseFact(
                canonical_name=self._asset.canonical_name,
                version=self._asset.version,
                asset_digest=self._asset.asset_digest,
                disclosure_version=self._asset.disclosure_version,
                used_at=used_at,
                workflow_id=initialization.workflow_id,
                admission_causal_id=initialization.admission_causal_id,
            )
            proof = self._attestor.sign(skill_use, request_digest=request_digest)
            self._workflow_proofs[initialization.workflow_id] = (request_digest, proof)
            return proof

    @staticmethod
    def _execute_builtin_asset(
        asset: HealthInitAsset,
        initialization: OwnerInitialization,
    ) -> bool:
        """Run the deterministic built-in initialization disclosure contract."""

        return (
            type(asset) is HealthInitAsset
            and type(initialization) is OwnerInitialization
            and initialization.incomplete_reason is None
            and asset.canonical_name == HEALTH_INIT_CANONICAL_NAME
            and bool(INITIALIZATION_DISCLOSED_TOPICS)
        )

    # Narrow aliases keep the Plugin seam descriptive without providing a
    # second path that could issue a different proof.
    execute = run
    use = run


@dataclass(frozen=True)
class InitialPortrait:
    """A blank six-domain portrait; initialization cannot backfill history."""

    domain_states: tuple[str, ...] = field(default_factory=lambda: ("unknown",) * 6)

    def __post_init__(self) -> None:
        states = _required_text_tuple(self.domain_states, "initial portrait domain states")
        if states != ("unknown",) * len(INITIAL_PORTRAIT_DOMAINS):
            raise AuthorityValidationError("invalid initial portrait domain states")

    @property
    def domains(self) -> tuple[str, ...]:
        return INITIAL_PORTRAIT_DOMAINS

    def to_storage(self) -> dict[str, object]:
        return {"domain_states": list(self.domain_states)}

    @classmethod
    def from_storage(cls, value: object) -> "InitialPortrait":
        stored = _required_mapping(
            value,
            frozenset({"domain_states"}),
            "initial portrait",
        )
        return cls(
            domain_states=_required_storage_text_list(
                stored["domain_states"], "initial portrait domain states"
            )
        )


@dataclass(frozen=True)
class InitializationDraft:
    """Complete local content bound to one Ticket 110 prepare transition."""

    owner: OwnerInitialization
    source_causal_id: str
    skill_proof: SkillUseProof
    owner_consent_evidence: OwnerConsentEvidence
    key_id: str
    prepared_authority: AuthoritySnapshot
    record_id: str
    revision_digest: str
    transition_id: str
    initial_portrait: InitialPortrait = field(default_factory=InitialPortrait)
    disclosed_topics: tuple[str, ...] = INITIALIZATION_DISCLOSED_TOPICS

    def __post_init__(self) -> None:
        if type(self.owner) is not OwnerInitialization:
            raise AuthorityValidationError("invalid owner initialization")
        self.owner.require_complete()
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        if self.source_causal_id != self.owner.admission_causal_id:
            raise AuthorityValidationError("initialization source causal mismatch")
        if type(self.skill_proof) is not SkillUseProof:
            raise AuthorityValidationError("invalid health-init use proof")
        if (
            self.skill_proof.workflow_id != self.owner.workflow_id
            or self.skill_proof.admission_causal_id != self.source_causal_id
            or self.skill_proof.request_digest != self.owner.digest
        ):
            raise AuthorityValidationError("health-init use binding mismatch")
        if (
            type(self.owner_consent_evidence) is not OwnerConsentEvidence
            or self.owner_consent_evidence.workflow_id != self.owner.workflow_id
            or self.owner_consent_evidence.admission_causal_id != self.source_causal_id
            or self.owner_consent_evidence.initialization_digest != self.owner.digest
            or self.owner_consent_evidence.disclosure_version
            != self.skill_proof.skill_use.disclosure_version
            or self.owner_consent_evidence.disclosed_topics
            != INITIALIZATION_DISCLOSED_TOPICS
            or self.owner_consent_evidence.owner_confirmed is not True
            or self.owner_consent_evidence.first_hop_route_confirmed is not True
        ):
            raise AuthorityValidationError("owner consent evidence binding mismatch")
        validate_opaque_text(self.key_id, "initialization key identifier")
        if (
            type(self.prepared_authority) is not AuthoritySnapshot
            or self.prepared_authority.terminal
        ):
            raise AuthorityValidationError("invalid prepared authority")
        validate_opaque_text(self.record_id, "initialization record identifier")
        validate_opaque_text(self.revision_digest, "initialization revision digest")
        validate_opaque_text(self.transition_id, "initialization transition identifier")
        if type(self.initial_portrait) is not InitialPortrait:
            raise AuthorityValidationError("invalid initial portrait")
        _required_text_tuple(
            self.disclosed_topics,
            "initialization disclosed topics",
            expected=INITIALIZATION_DISCLOSED_TOPICS,
        )

    @property
    def owner_initialization(self) -> OwnerInitialization:
        return self.owner

    @property
    def skill_use(self) -> SkillUseFact:
        return self.skill_proof.skill_use

    def to_storage(self) -> dict[str, object]:
        return {
            "owner": self.owner.to_storage(),
            "source_causal_id": self.source_causal_id,
            "skill_proof": self.skill_proof.to_storage(),
            "owner_consent_evidence": self.owner_consent_evidence.to_storage(),
            "key_id": self.key_id,
            "prepared_authority": self.prepared_authority.to_storage(),
            "record_id": self.record_id,
            "revision_digest": self.revision_digest,
            "transition_id": self.transition_id,
            "initial_portrait": self.initial_portrait.to_storage(),
            "disclosed_topics": list(self.disclosed_topics),
        }

    @classmethod
    def from_storage(cls, value: object) -> "InitializationDraft":
        stored = _required_mapping(
            value,
            frozenset(
                {
                    "owner",
                    "source_causal_id",
                    "skill_proof",
                    "owner_consent_evidence",
                    "key_id",
                    "prepared_authority",
                    "record_id",
                    "revision_digest",
                    "transition_id",
                    "initial_portrait",
                    "disclosed_topics",
                }
            ),
            "initialization draft",
        )
        return cls(
            owner=OwnerInitialization.from_storage(stored["owner"]),
            source_causal_id=stored["source_causal_id"],  # type: ignore[arg-type]
            skill_proof=SkillUseProof.from_storage(stored["skill_proof"]),
            owner_consent_evidence=OwnerConsentEvidence.from_storage(
                stored["owner_consent_evidence"]
            ),
            key_id=stored["key_id"],  # type: ignore[arg-type]
            prepared_authority=AuthoritySnapshot.from_storage(stored["prepared_authority"]),
            record_id=stored["record_id"],  # type: ignore[arg-type]
            revision_digest=stored["revision_digest"],  # type: ignore[arg-type]
            transition_id=stored["transition_id"],  # type: ignore[arg-type]
            initial_portrait=InitialPortrait.from_storage(stored["initial_portrait"]),
            disclosed_topics=_required_storage_text_list(
                stored["disclosed_topics"], "initialization disclosed topics"
            ),
        )

    @property
    def content_digest(self) -> str:
        return stable_digest(self.to_storage())

    def projection(
        self,
        *,
        phase: str = "prepared",
        enabled: bool = False,
    ) -> "InitializationProjection":
        if phase not in {"prepared", "committed", "unknown", "enabled"}:
            raise AuthorityValidationError("invalid initialization phase")
        return InitializationProjection(
            phase=phase,
            enabled=enabled,
            skill_use=self.skill_use,
            first_hop_route=self.owner.first_hop_route,
            timezone=self.owner.timezone,
            key_id=self.key_id,
            prepared_authority=self.prepared_authority,
            initial_portrait=self.initial_portrait,
            disclosed_topics=self.disclosed_topics,
            support_contact=self.owner.support_contact,
            record_id=self.record_id,
            revision_digest=self.revision_digest,
            transition_id=self.transition_id,
            business_state=phase,
            disclosure_state="formed",
            owner_delivery_state="unknown" if phase == "enabled" else "not-attempted",
            support_contact_approval_state=(
                "not-configured"
                if self.owner.support_contact is None
                else "approved-boundary"
                if phase == "enabled"
                else "not-effective"
            ),
        )


@dataclass(frozen=True)
class InitializationProjection:
    """Read-only initialization status; only finalized state may be enabled."""

    phase: str
    enabled: bool
    skill_use: SkillUseFact | None
    first_hop_route: str | None
    timezone: str | None
    key_id: str | None
    prepared_authority: AuthoritySnapshot | None
    initial_portrait: InitialPortrait | None
    disclosed_topics: tuple[str, ...]
    support_contact: SupportContactBoundary | None
    record_id: str | None
    revision_digest: str | None
    transition_id: str | None
    business_state: str
    disclosure_state: str
    owner_delivery_state: str
    support_contact_approval_state: str

    def __post_init__(self) -> None:
        allowed_phases = {
            "uninitialized",
            "cannot-confirm",
            "prepared",
            "committed",
            "unknown",
            "enabled",
        }
        if type(self.phase) is not str or self.phase not in allowed_phases:
            raise AuthorityValidationError("invalid initialization phase")
        _required_bool(self.enabled, "initialization enabled")
        if self.enabled != (self.phase == "enabled"):
            raise AuthorityValidationError("invalid initialization enabled state")
        if self.business_state != self.phase:
            raise AuthorityValidationError("invalid initialization business state")
        if self.phase in {"uninitialized", "cannot-confirm"}:
            if any(
                value is not None
                for value in (
                    self.skill_use,
                    self.first_hop_route,
                    self.timezone,
                    self.key_id,
                    self.prepared_authority,
                    self.initial_portrait,
                    self.support_contact,
                    self.record_id,
                    self.revision_digest,
                    self.transition_id,
                )
            ) or self.disclosed_topics != ():
                raise AuthorityValidationError("invalid uninitialized projection")
            expected_layers = (
                ("not-formed", "not-attempted", "not-effective")
                if self.phase == "uninitialized"
                else ("cannot-confirm", "cannot-confirm", "cannot-confirm")
            )
            if (
                self.disclosure_state,
                self.owner_delivery_state,
                self.support_contact_approval_state,
            ) != expected_layers:
                raise AuthorityValidationError("invalid unavailable initialization layers")
            return
        if type(self.skill_use) is not SkillUseFact:
            raise AuthorityValidationError("invalid health-init use fact")
        validate_opaque_text(self.first_hop_route, "first-hop route")
        _iana_timezone(self.timezone)
        validate_opaque_text(self.key_id, "initialization key identifier")
        if (
            type(self.prepared_authority) is not AuthoritySnapshot
            or self.prepared_authority.terminal
        ):
            raise AuthorityValidationError("invalid prepared authority")
        if type(self.initial_portrait) is not InitialPortrait:
            raise AuthorityValidationError("invalid initial portrait")
        if (
            self.support_contact is not None
            and type(self.support_contact) is not SupportContactBoundary
        ):
            raise AuthorityValidationError("invalid support contact boundary")
        validate_opaque_text(self.record_id, "initialization record identifier")
        validate_opaque_text(self.revision_digest, "initialization revision digest")
        validate_opaque_text(self.transition_id, "initialization transition identifier")
        _required_text_tuple(
            self.disclosed_topics,
            "initialization disclosed topics",
            expected=INITIALIZATION_DISCLOSED_TOPICS,
        )
        if self.disclosure_state != "formed":
            raise AuthorityValidationError("invalid initialization disclosure state")
        expected_delivery = "unknown" if self.phase == "enabled" else "not-attempted"
        if self.owner_delivery_state != expected_delivery:
            raise AuthorityValidationError("invalid initialization delivery state")
        expected_contact = (
            "not-configured"
            if self.support_contact is None
            else "approved-boundary"
            if self.phase == "enabled"
            else "not-effective"
        )
        if self.support_contact_approval_state != expected_contact:
            raise AuthorityValidationError("invalid support contact approval state")

    @classmethod
    def uninitialized(cls) -> "InitializationProjection":
        return cls(
            phase="uninitialized",
            enabled=False,
            skill_use=None,
            first_hop_route=None,
            timezone=None,
            key_id=None,
            prepared_authority=None,
            initial_portrait=None,
            disclosed_topics=(),
            support_contact=None,
            record_id=None,
            revision_digest=None,
            transition_id=None,
            business_state="uninitialized",
            disclosure_state="not-formed",
            owner_delivery_state="not-attempted",
            support_contact_approval_state="not-effective",
        )

    @classmethod
    def cannot_confirm(cls) -> "InitializationProjection":
        return cls(
            phase="cannot-confirm",
            enabled=False,
            skill_use=None,
            first_hop_route=None,
            timezone=None,
            key_id=None,
            prepared_authority=None,
            initial_portrait=None,
            disclosed_topics=(),
            support_contact=None,
            record_id=None,
            revision_digest=None,
            transition_id=None,
            business_state="cannot-confirm",
            disclosure_state="cannot-confirm",
            owner_delivery_state="cannot-confirm",
            support_contact_approval_state="cannot-confirm",
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "enabled": self.enabled,
            "skill_use": None if self.skill_use is None else self.skill_use.to_storage(),
            "first_hop_route": self.first_hop_route,
            "timezone": self.timezone,
            "key_id": self.key_id,
            "prepared_authority": (
                None if self.prepared_authority is None else self.prepared_authority.to_storage()
            ),
            "initial_portrait": (
                None if self.initial_portrait is None else self.initial_portrait.to_storage()
            ),
            "disclosed_topics": list(self.disclosed_topics),
            "support_contact": (
                None if self.support_contact is None else self.support_contact.to_storage()
            ),
            "record_id": self.record_id,
            "revision_digest": self.revision_digest,
            "transition_id": self.transition_id,
            "business_state": self.business_state,
            "disclosure_state": self.disclosure_state,
            "owner_delivery_state": self.owner_delivery_state,
            "support_contact_approval_state": self.support_contact_approval_state,
        }

    @classmethod
    def from_storage(cls, value: object) -> "InitializationProjection":
        stored = _required_mapping(
            value,
            frozenset(
                {
                    "phase",
                    "enabled",
                    "skill_use",
                    "first_hop_route",
                    "timezone",
                    "key_id",
                    "prepared_authority",
                    "initial_portrait",
                    "disclosed_topics",
                    "support_contact",
                    "record_id",
                    "revision_digest",
                    "transition_id",
                    "business_state",
                    "disclosure_state",
                    "owner_delivery_state",
                    "support_contact_approval_state",
                }
            ),
            "initialization projection",
        )
        topics_value = stored["disclosed_topics"]
        if type(topics_value) is not list:
            raise AuthorityValidationError("invalid initialization disclosed topics")
        topics = tuple(topics_value)
        return cls(
            phase=stored["phase"],  # type: ignore[arg-type]
            enabled=stored["enabled"],  # type: ignore[arg-type]
            skill_use=(
                None
                if stored["skill_use"] is None
                else SkillUseFact.from_storage(stored["skill_use"])
            ),
            first_hop_route=stored["first_hop_route"],  # type: ignore[arg-type]
            timezone=stored["timezone"],  # type: ignore[arg-type]
            key_id=stored["key_id"],  # type: ignore[arg-type]
            prepared_authority=(
                None
                if stored["prepared_authority"] is None
                else AuthoritySnapshot.from_storage(stored["prepared_authority"])
            ),
            initial_portrait=(
                None
                if stored["initial_portrait"] is None
                else InitialPortrait.from_storage(stored["initial_portrait"])
            ),
            disclosed_topics=topics,  # validated by __post_init__
            support_contact=(
                None
                if stored["support_contact"] is None
                else SupportContactBoundary.from_storage(stored["support_contact"])
            ),
            record_id=stored["record_id"],  # type: ignore[arg-type]
            revision_digest=stored["revision_digest"],  # type: ignore[arg-type]
            transition_id=stored["transition_id"],  # type: ignore[arg-type]
            business_state=stored["business_state"],  # type: ignore[arg-type]
            disclosure_state=stored["disclosure_state"],  # type: ignore[arg-type]
            owner_delivery_state=stored["owner_delivery_state"],  # type: ignore[arg-type]
            support_contact_approval_state=stored[
                "support_contact_approval_state"
            ],  # type: ignore[arg-type]
        )


__all__ = [
    "HEALTH_INIT_CANONICAL_NAME",
    "INITIAL_DATA_BOUNDARY",
    "INITIALIZATION_DISCLOSED_TOPICS",
    "INITIAL_PORTRAIT_DOMAINS",
    "HealthInitAsset",
    "HealthInitAttestor",
    "HealthInitRuntime",
    "InitialPreferences",
    "InitialPortrait",
    "InitializationDraft",
    "InitializationProjection",
    "OwnerConsentEvidence",
    "OwnerInitialization",
    "SkillUseFact",
    "SkillUseProof",
    "SupportContactBoundary",
    "stable_digest",
]

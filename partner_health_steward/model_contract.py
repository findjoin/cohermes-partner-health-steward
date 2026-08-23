"""Strict, content-ephemeral model contracts for Ticket 113."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit

from .answer_resolution import ModelEffectReport
from .initialization import stable_digest
from .nondiagnostic import NonDiagnosticCandidate, NonDiagnosticContractViolation


class ModelContractViolation(ValueError):
    """A model value cannot cross the strict health model seam."""


SYNTHETIC_STRICT_SCHEMA_NAME = "nondiagnostic-candidate-v1"
SYNTHETIC_STRICT_SCHEMA_DIGEST = "sha256:" + "b" * 64


def _mapping(value: object, fields: frozenset[str], name: str) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != fields:
        raise ModelContractViolation(f"invalid {name}")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > 16384:
        raise ModelContractViolation(f"invalid {name}")
    return value


def _sha(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise ModelContractViolation(f"invalid {name}")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise ModelContractViolation(f"invalid {name}") from exc
    return text


def _integer(value: object, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise ModelContractViolation(f"invalid {name}")
    return value


def _texts(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise ModelContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ModelContractViolation(f"invalid {name}")
    return result


def _canonical_url(value: object) -> str:
    text = _text(value, "canonical base URL")
    parsed = urlsplit(text)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ModelContractViolation("invalid canonical base URL")
    canonical = urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))
    if text != canonical:
        raise ModelContractViolation("base URL is not canonical")
    return text


def _freeze_json(value: object, name: str) -> object:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is list:
        return tuple(_freeze_json(item, name) for item in value)
    if type(value) is dict:
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ModelContractViolation(f"invalid {name}")
            frozen[key] = _freeze_json(item, name)
        return MappingProxyType(frozen)
    raise ModelContractViolation(f"invalid {name}")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class FirstHopRoute:
    route_id: str
    provider: str
    canonical_base_url: str
    api_mode: str
    requested_model: str
    configuration_generation: int
    owner_consent_fingerprint: str

    def __post_init__(self) -> None:
        _text(self.route_id, "route identifier")
        _text(self.provider, "provider")
        _canonical_url(self.canonical_base_url)
        _text(self.api_mode, "API mode")
        _text(self.requested_model, "requested model")
        _integer(self.configuration_generation, "configuration generation", positive=True)
        _sha(self.owner_consent_fingerprint, "owner consent fingerprint")

    def to_wire(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "provider": self.provider,
            "canonical_base_url": self.canonical_base_url,
            "api_mode": self.api_mode,
            "requested_model": self.requested_model,
            "configuration_generation": self.configuration_generation,
            "owner_consent_fingerprint": self.owner_consent_fingerprint,
        }

    @classmethod
    def from_wire(cls, value: object) -> "FirstHopRoute":
        fields = _mapping(value, frozenset({
            "route_id", "provider", "canonical_base_url", "api_mode",
            "requested_model", "configuration_generation", "owner_consent_fingerprint",
        }), "first-hop route")
        return cls(
            _text(fields["route_id"], "route identifier"),
            _text(fields["provider"], "provider"),
            _canonical_url(fields["canonical_base_url"]),
            _text(fields["api_mode"], "API mode"),
            _text(fields["requested_model"], "requested model"),
            _integer(fields["configuration_generation"], "configuration generation", positive=True),
            _sha(fields["owner_consent_fingerprint"], "owner consent fingerprint"),
        )


@dataclass(frozen=True)
class CapabilityProfile:
    profile_id: str
    profile_version: str
    synthetic: bool
    route_id: str
    provider: str
    canonical_base_url: str
    api_mode: str
    requested_model: str
    allowed_actual_models: tuple[str, ...]
    configuration_generation: int
    input_measurement_method: str
    fixed_wrapper_tokens: int
    output_reservation_tokens: int
    common_context_lower_bound_tokens: int
    evidence_refs: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, name in (
            (self.profile_id, "profile identifier"),
            (self.profile_version, "profile version"),
            (self.route_id, "route identifier"),
            (self.provider, "provider"),
            (self.api_mode, "API mode"),
            (self.requested_model, "requested model"),
            (self.input_measurement_method, "input measurement method"),
        ):
            _text(value, name)
        if type(self.synthetic) is not bool:
            raise ModelContractViolation("invalid synthetic profile marker")
        _canonical_url(self.canonical_base_url)
        if type(self.allowed_actual_models) is not tuple or not self.allowed_actual_models:
            raise ModelContractViolation("invalid allowed actual models")
        if any(type(item) is not str or not item for item in self.allowed_actual_models):
            raise ModelContractViolation("invalid allowed actual models")
        if len(set(self.allowed_actual_models)) != len(self.allowed_actual_models):
            raise ModelContractViolation("invalid allowed actual models")
        _integer(self.configuration_generation, "configuration generation", positive=True)
        _integer(self.fixed_wrapper_tokens, "fixed wrapper tokens")
        _integer(self.output_reservation_tokens, "output reservation tokens", positive=True)
        _integer(self.common_context_lower_bound_tokens, "common context lower bound tokens", positive=True)
        for values, name in (
            (self.evidence_refs, "capability evidence references"),
            (self.invalidation_conditions, "profile invalidation conditions"),
        ):
            if type(values) is not tuple or not values or any(type(item) is not str or not item for item in values):
                raise ModelContractViolation(f"invalid {name}")

    def to_wire(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "synthetic": self.synthetic,
            "route_id": self.route_id,
            "provider": self.provider,
            "canonical_base_url": self.canonical_base_url,
            "api_mode": self.api_mode,
            "requested_model": self.requested_model,
            "allowed_actual_models": list(self.allowed_actual_models),
            "configuration_generation": self.configuration_generation,
            "input_measurement_method": self.input_measurement_method,
            "fixed_wrapper_tokens": self.fixed_wrapper_tokens,
            "output_reservation_tokens": self.output_reservation_tokens,
            "common_context_lower_bound_tokens": self.common_context_lower_bound_tokens,
            "evidence_refs": list(self.evidence_refs),
            "invalidation_conditions": list(self.invalidation_conditions),
        }

    @classmethod
    def from_wire(cls, value: object) -> "CapabilityProfile":
        fields = _mapping(value, frozenset({
            "profile_id", "profile_version", "synthetic", "route_id", "provider",
            "canonical_base_url", "api_mode", "requested_model", "allowed_actual_models",
            "configuration_generation", "input_measurement_method", "fixed_wrapper_tokens",
            "output_reservation_tokens", "common_context_lower_bound_tokens", "evidence_refs",
            "invalidation_conditions",
        }), "capability profile")
        synthetic = fields["synthetic"]
        if type(synthetic) is not bool:
            raise ModelContractViolation("invalid synthetic profile marker")
        return cls(
            _text(fields["profile_id"], "profile identifier"),
            _text(fields["profile_version"], "profile version"),
            synthetic,
            _text(fields["route_id"], "route identifier"),
            _text(fields["provider"], "provider"),
            _canonical_url(fields["canonical_base_url"]),
            _text(fields["api_mode"], "API mode"),
            _text(fields["requested_model"], "requested model"),
            _texts(fields["allowed_actual_models"], "allowed actual models"),
            _integer(fields["configuration_generation"], "configuration generation", positive=True),
            _text(fields["input_measurement_method"], "input measurement method"),
            _integer(fields["fixed_wrapper_tokens"], "fixed wrapper tokens"),
            _integer(fields["output_reservation_tokens"], "output reservation tokens", positive=True),
            _integer(fields["common_context_lower_bound_tokens"], "common context lower bound tokens", positive=True),
            _texts(fields["evidence_refs"], "capability evidence references"),
            _texts(fields["invalidation_conditions"], "profile invalidation conditions"),
        )


@dataclass(frozen=True)
class ModelMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if type(self.role) is not str or self.role not in {
            "system",
            "user",
            "assistant",
        }:
            raise ModelContractViolation("invalid model message role")
        _text(self.content, "model message content")

    def to_wire(self) -> dict[str, object]:
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_wire(cls, value: object) -> "ModelMessage":
        fields = _mapping(value, frozenset({"role", "content"}), "model message")
        return cls(_text(fields["role"], "model message role"), _text(fields["content"], "model message content"))


@dataclass(frozen=True)
class StrictModelRequest:
    route: FirstHopRoute
    capability_profile: CapabilityProfile
    messages: tuple[ModelMessage, ...]
    final_input_digest: str
    final_input_upper_bound_tokens: int
    output_reservation_tokens: int
    strict_schema_name: str
    strict_schema_digest: str

    def __post_init__(self) -> None:
        if type(self.route) is not FirstHopRoute or type(self.capability_profile) is not CapabilityProfile:
            raise ModelContractViolation("invalid strict model authority")
        if type(self.messages) is not tuple or not self.messages or any(type(item) is not ModelMessage for item in self.messages):
            raise ModelContractViolation("invalid model messages")
        _sha(self.final_input_digest, "final input digest")
        if self.final_input_digest != stable_digest(
            {"messages": [ModelMessage.to_wire(item) for item in self.messages]}
        ):
            raise ModelContractViolation("final input digest does not match messages")
        _integer(self.final_input_upper_bound_tokens, "final input upper bound tokens", positive=True)
        _integer(self.output_reservation_tokens, "output reservation tokens", positive=True)
        _text(self.strict_schema_name, "strict schema name")
        _sha(self.strict_schema_digest, "strict schema digest")

    def to_wire(self) -> dict[str, object]:
        return {
            "route": FirstHopRoute.to_wire(self.route),
            "capability_profile": CapabilityProfile.to_wire(
                self.capability_profile
            ),
            "messages": [ModelMessage.to_wire(item) for item in self.messages],
            "final_input_digest": self.final_input_digest,
            "final_input_upper_bound_tokens": self.final_input_upper_bound_tokens,
            "output_reservation_tokens": self.output_reservation_tokens,
            "strict_schema_name": self.strict_schema_name,
            "strict_schema_digest": self.strict_schema_digest,
        }

    @property
    def digest(self) -> str:
        """Content-address the exact final request admitted to the model seam."""

        return stable_digest(StrictModelRequest.to_wire(self))

    def canonical_copy(self) -> "StrictModelRequest":
        """Rebuild an exact request without caller-owned instance attributes."""

        if type(self) is not StrictModelRequest:
            raise ModelContractViolation("invalid strict model request")
        route = object.__getattribute__(self, "route")
        capability_profile = object.__getattribute__(self, "capability_profile")
        messages = object.__getattribute__(self, "messages")
        if (
            type(route) is not FirstHopRoute
            or type(capability_profile) is not CapabilityProfile
            or type(messages) is not tuple
            or not messages
            or any(type(item) is not ModelMessage for item in messages)
        ):
            raise ModelContractViolation("invalid strict model authority")
        FirstHopRoute.__post_init__(route)
        CapabilityProfile.__post_init__(capability_profile)
        for item in messages:
            ModelMessage.__post_init__(item)
        return StrictModelRequest.from_wire(
            {
                "route": FirstHopRoute.to_wire(route),
                "capability_profile": CapabilityProfile.to_wire(
                    capability_profile
                ),
                "messages": [ModelMessage.to_wire(item) for item in messages],
                "final_input_digest": object.__getattribute__(
                    self,
                    "final_input_digest",
                ),
                "final_input_upper_bound_tokens": object.__getattribute__(
                    self,
                    "final_input_upper_bound_tokens",
                ),
                "output_reservation_tokens": object.__getattribute__(
                    self,
                    "output_reservation_tokens",
                ),
                "strict_schema_name": object.__getattribute__(
                    self,
                    "strict_schema_name",
                ),
                "strict_schema_digest": object.__getattribute__(
                    self,
                    "strict_schema_digest",
                ),
            }
        )

    @classmethod
    def from_wire(cls, value: object) -> "StrictModelRequest":
        fields = _mapping(value, frozenset({
            "route", "capability_profile", "messages", "final_input_digest",
            "final_input_upper_bound_tokens", "output_reservation_tokens",
            "strict_schema_name", "strict_schema_digest",
        }), "strict model request")
        messages = fields["messages"]
        if type(messages) is not list or not messages:
            raise ModelContractViolation("invalid model messages")
        return cls(
            FirstHopRoute.from_wire(fields["route"]),
            CapabilityProfile.from_wire(fields["capability_profile"]),
            tuple(ModelMessage.from_wire(item) for item in messages),
            _sha(fields["final_input_digest"], "final input digest"),
            _integer(fields["final_input_upper_bound_tokens"], "final input upper bound tokens", positive=True),
            _integer(fields["output_reservation_tokens"], "output reservation tokens", positive=True),
            _text(fields["strict_schema_name"], "strict schema name"),
            _sha(fields["strict_schema_digest"], "strict schema digest"),
        )


@dataclass(frozen=True)
class ModelTransportResult:
    response_id: str
    requested_model: str
    actual_model: str
    status: str
    incomplete_reason: str | None
    failure_reason: str | None
    usage_input_tokens: int
    usage_output_tokens: int
    fallback_observed: bool
    truncated: bool
    terminal_proven: bool
    structured_output: Mapping[str, object] | None

    def __post_init__(self) -> None:
        _text(self.response_id, "response identifier")
        _text(self.requested_model, "requested model")
        _text(self.actual_model, "actual model")
        if self.status not in {"completed", "incomplete", "failed", "unknown"}:
            raise ModelContractViolation("invalid model terminal status")
        for value, name in ((self.incomplete_reason, "incomplete reason"), (self.failure_reason, "failure reason")):
            if value is not None:
                _text(value, name)
        _integer(self.usage_input_tokens, "input usage tokens")
        _integer(self.usage_output_tokens, "output usage tokens")
        if any(type(value) is not bool for value in (self.fallback_observed, self.truncated, self.terminal_proven)):
            raise ModelContractViolation("invalid model result facts")
        if self.status == "completed":
            if (
                not self.terminal_proven
                or not isinstance(self.structured_output, Mapping)
                or self.incomplete_reason is not None
                or self.failure_reason is not None
            ):
                raise ModelContractViolation("invalid completed model result")
            try:
                frozen_output = _freeze_json(
                    _thaw_json(self.structured_output),
                    "structured model output",
                )
            except ModelContractViolation:
                raise
            except Exception as exc:
                raise ModelContractViolation(
                    "invalid structured model output"
                ) from exc
            if not isinstance(frozen_output, Mapping):
                raise ModelContractViolation("invalid structured model output")
            object.__setattr__(self, "structured_output", frozen_output)
        elif self.structured_output is not None:
            raise ModelContractViolation("non-completed result cannot carry structured output")
        if self.status in {"incomplete", "failed"} and not self.terminal_proven:
            raise ModelContractViolation("known model result must prove terminality")
        if self.status == "incomplete" and (
            self.incomplete_reason is None or self.failure_reason is not None
        ):
            raise ModelContractViolation("exclusive incomplete reason required")
        if self.status == "failed" and (
            self.failure_reason is None or self.incomplete_reason is not None
        ):
            raise ModelContractViolation("exclusive failure reason required")
        if self.status == "unknown" and self.terminal_proven:
            raise ModelContractViolation("unknown result cannot prove terminality")
        if self.status == "unknown" and (
            self.incomplete_reason is not None or self.failure_reason is not None
        ):
            raise ModelContractViolation("unknown result cannot claim a terminal reason")

    def to_wire(self) -> dict[str, object]:
        return {
            "response_id": self.response_id,
            "requested_model": self.requested_model,
            "actual_model": self.actual_model,
            "status": self.status,
            "incomplete_reason": self.incomplete_reason,
            "failure_reason": self.failure_reason,
            "usage_input_tokens": self.usage_input_tokens,
            "usage_output_tokens": self.usage_output_tokens,
            "fallback_observed": self.fallback_observed,
            "truncated": self.truncated,
            "terminal_proven": self.terminal_proven,
            "structured_output": None if self.structured_output is None else _thaw_json(self.structured_output),
        }

    def canonical_copy(self) -> "ModelTransportResult":
        """Revalidate one observed result without instance-level method hooks."""

        return ModelTransportResult.from_wire(ModelTransportResult.to_wire(self))

    @classmethod
    def from_wire(cls, value: object) -> "ModelTransportResult":
        fields = _mapping(value, frozenset({
            "response_id", "requested_model", "actual_model", "status", "incomplete_reason",
            "failure_reason", "usage_input_tokens", "usage_output_tokens", "fallback_observed",
            "truncated", "terminal_proven", "structured_output",
        }), "model transport result")
        for key in ("fallback_observed", "truncated", "terminal_proven"):
            if type(fields[key]) is not bool:
                raise ModelContractViolation("invalid model result facts")
        structured = fields["structured_output"]
        if structured is not None and type(structured) is not dict:
            raise ModelContractViolation("invalid structured model output")
        incomplete = fields["incomplete_reason"]
        failure = fields["failure_reason"]
        if incomplete is not None:
            incomplete = _text(incomplete, "incomplete reason")
        if failure is not None:
            failure = _text(failure, "failure reason")
        frozen = None if structured is None else _freeze_json(structured, "structured model output")
        if frozen is not None and not isinstance(frozen, Mapping):
            raise ModelContractViolation("invalid structured model output")
        return cls(
            _text(fields["response_id"], "response identifier"),
            _text(fields["requested_model"], "requested model"),
            _text(fields["actual_model"], "actual model"),
            _text(fields["status"], "model terminal status"),
            incomplete,
            failure,
            _integer(fields["usage_input_tokens"], "input usage tokens"),
            _integer(fields["usage_output_tokens"], "output usage tokens"),
            fields["fallback_observed"],  # type: ignore[arg-type]
            fields["truncated"],  # type: ignore[arg-type]
            fields["terminal_proven"],  # type: ignore[arg-type]
            frozen,  # type: ignore[arg-type]
        )


class StrictModelAdapter(Protocol):
    """The single controlled model-effect boundary used by the strict port."""

    def execute(self, payload: object) -> ModelTransportResult:
        """Execute one already-validated model payload."""


@dataclass(frozen=True)
class StrictModelOutcome:
    """Ephemeral facts produced by the strict model port."""

    disposition: str
    model_effect: str
    reason_code: str | None
    candidate: Mapping[str, object] | None
    transport_reason: str | None = None
    model_report: ModelEffectReport | None = None


class StrictHealthLLM:
    """Validate authority facts before allowing the one model effect."""

    def __init__(
        self,
        route: FirstHopRoute,
        capability_profile: CapabilityProfile,
        strict_schema_name: str = SYNTHETIC_STRICT_SCHEMA_NAME,
        strict_schema_digest: str = SYNTHETIC_STRICT_SCHEMA_DIGEST,
    ) -> None:
        if type(route) is not FirstHopRoute or type(capability_profile) is not CapabilityProfile:
            raise ModelContractViolation("invalid current model authority")
        route_facts = (
            route.route_id,
            route.provider,
            route.canonical_base_url,
            route.api_mode,
            route.requested_model,
            route.configuration_generation,
        )
        profile_route_facts = (
            capability_profile.route_id,
            capability_profile.provider,
            capability_profile.canonical_base_url,
            capability_profile.api_mode,
            capability_profile.requested_model,
            capability_profile.configuration_generation,
        )
        if profile_route_facts != route_facts:
            raise ModelContractViolation("capability profile does not bind current route")
        self._route = route
        self._capability_profile = capability_profile
        self._strict_schema_name = _text(strict_schema_name, "strict schema name")
        self._strict_schema_digest = _sha(strict_schema_digest, "strict schema digest")

    @property
    def model_authority_digest(self) -> str:
        """Bind the current route, profile, consent, and strict output schema."""

        return stable_digest(
            {
                "route": FirstHopRoute.to_wire(self._route),
                "capability_profile": CapabilityProfile.to_wire(
                    self._capability_profile
                ),
                "strict_schema_name": self._strict_schema_name,
                "strict_schema_digest": self._strict_schema_digest,
            }
        )

    def canonical_copy(self) -> "StrictHealthLLM":
        """Rebuild current authority without caller-owned method shadows."""

        if type(self) is not StrictHealthLLM:
            raise ModelContractViolation("invalid current model authority")
        route = object.__getattribute__(self, "_route")
        capability_profile = object.__getattribute__(self, "_capability_profile")
        if (
            type(route) is not FirstHopRoute
            or type(capability_profile) is not CapabilityProfile
        ):
            raise ModelContractViolation("invalid current model authority")
        FirstHopRoute.__post_init__(route)
        CapabilityProfile.__post_init__(capability_profile)
        return StrictHealthLLM(
            FirstHopRoute.from_wire(FirstHopRoute.to_wire(route)),
            CapabilityProfile.from_wire(
                CapabilityProfile.to_wire(capability_profile)
            ),
            strict_schema_name=object.__getattribute__(
                self,
                "_strict_schema_name",
            ),
            strict_schema_digest=object.__getattribute__(
                self,
                "_strict_schema_digest",
            ),
        )

    @staticmethod
    def _report(
        result: ModelTransportResult,
        reason_code: str | None,
        *,
        candidate_digest: str | None = None,
    ) -> ModelEffectReport:
        result_identity = ModelTransportResult.to_wire(result)
        return ModelEffectReport(
            model_status=result.status,
            transport_attempted=True,
            terminal_proven=result.terminal_proven,
            requested_model=result.requested_model,
            actual_model=result.actual_model,
            fallback_observed=result.fallback_observed,
            truncated=result.truncated,
            reason_code=reason_code,
            result_digest=stable_digest(result_identity),
            candidate_digest=candidate_digest,
        )

    def preflight(
        self,
        request: StrictModelRequest,
    ) -> StrictModelOutcome | None:
        if request.route.route_id != self._route.route_id:
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="route-id-drift",
                candidate=None,
            )
        if request.route.provider != self._route.provider:
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="provider-drift",
                candidate=None,
            )
        if request.route.canonical_base_url != self._route.canonical_base_url:
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="base-url-drift",
                candidate=None,
            )
        if request.route.api_mode != self._route.api_mode:
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="api-mode-drift",
                candidate=None,
            )
        if request.route.requested_model != self._route.requested_model:
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="requested-model-drift",
                candidate=None,
            )
        if request.route.configuration_generation != self._route.configuration_generation:
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="configuration-generation-drift",
                candidate=None,
            )
        if request.route.owner_consent_fingerprint != self._route.owner_consent_fingerprint:
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="owner-consent-drift",
                candidate=None,
            )
        if request.capability_profile != self._capability_profile:
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="capability-profile-drift",
                candidate=None,
            )
        if request.output_reservation_tokens != request.capability_profile.output_reservation_tokens:
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="output-reservation-drift",
                candidate=None,
            )
        if (
            request.strict_schema_name != self._strict_schema_name
            or request.strict_schema_digest != self._strict_schema_digest
        ):
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="strict-schema-drift",
                candidate=None,
            )
        required_capacity = (
            request.final_input_upper_bound_tokens
            + request.capability_profile.fixed_wrapper_tokens
            + request.output_reservation_tokens
        )
        measured_input_upper_bound = len(
            json.dumps(
                [item.to_wire() for item in request.messages],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        if (
            not request.capability_profile.synthetic
            or request.capability_profile.input_measurement_method
            != "synthetic-utf8-byte-upper-bound-v1"
            or request.final_input_upper_bound_tokens < measured_input_upper_bound
            or required_capacity
            > request.capability_profile.common_context_lower_bound_tokens
        ):
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="capacity-unavailable",
                candidate=None,
            )
        return None

    def transport_unknown_outcome(
        self,
        request: StrictModelRequest,
    ) -> StrictModelOutcome:
        """Return the only result allowed after an unclassifiable transport attempt."""

        preflight = StrictHealthLLM.preflight(self, request)
        if preflight is not None:
            return preflight
        report = ModelEffectReport(
            model_status="unknown",
            transport_attempted=True,
            terminal_proven=False,
            requested_model=request.route.requested_model,
            actual_model=None,
            fallback_observed=False,
            truncated=False,
            reason_code="model-effect-unknown",
            result_digest=stable_digest(
                {
                    "kind": "transport-attempt-unknown-v1",
                    "strict_request_digest": stable_digest(
                        StrictModelRequest.to_wire(request)
                    ),
                }
            ),
        )
        return StrictModelOutcome(
            disposition="unknown",
            model_effect="unknown",
            reason_code="model-effect-unknown",
            candidate=None,
            model_report=report,
        )

    def resolve_transport_result(
        self,
        request: StrictModelRequest,
        result: ModelTransportResult,
    ) -> StrictModelOutcome:
        """Validate one already-observed exact transport result without I/O."""

        preflight = StrictHealthLLM.preflight(self, request)
        if preflight is not None:
            return preflight
        if type(result) is not ModelTransportResult:
            return StrictHealthLLM.transport_unknown_outcome(self, request)
        if result.status == "unknown":
            report = StrictHealthLLM._report(result, "model-effect-unknown")
            return StrictModelOutcome(
                disposition="unknown",
                model_effect="unknown",
                reason_code="model-effect-unknown",
                candidate=None,
                model_report=report,
            )
        if result.requested_model != request.route.requested_model:
            report = StrictHealthLLM._report(
                result,
                "transport-requested-model-drift",
            )
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect=result.status,
                reason_code="transport-requested-model-drift",
                candidate=None,
                model_report=report,
            )
        if result.fallback_observed:
            report = StrictHealthLLM._report(result, "fallback-observed")
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect=result.status,
                reason_code="fallback-observed",
                candidate=None,
                model_report=report,
            )
        if result.actual_model not in request.capability_profile.allowed_actual_models:
            report = StrictHealthLLM._report(result, "actual-model-drift")
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect=result.status,
                reason_code="actual-model-drift",
                candidate=None,
                model_report=report,
            )
        if result.truncated:
            report = StrictHealthLLM._report(result, "model-output-truncated")
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect=result.status,
                reason_code="model-output-truncated",
                candidate=None,
                model_report=report,
            )
        if result.status == "completed" and not result.truncated:
            candidate = _thaw_json(result.structured_output)
            if not isinstance(candidate, Mapping):
                raise ModelContractViolation("completed result lacks structured output")
            try:
                validated = NonDiagnosticCandidate.from_wire(candidate)
            except NonDiagnosticContractViolation:
                report = StrictHealthLLM._report(result, "strict-schema-error")
                return StrictModelOutcome(
                    disposition="failed-closed",
                    model_effect="completed",
                    reason_code="strict-schema-error",
                    candidate=None,
                    model_report=report,
                )
            candidate_digest = stable_digest(validated.to_wire())
            report = StrictHealthLLM._report(
                result,
                None,
                candidate_digest=candidate_digest,
            )
            return StrictModelOutcome(
                disposition="candidate",
                model_effect="completed",
                reason_code=None,
                candidate=validated.to_wire(),
                model_report=report,
            )
        if result.status == "incomplete":
            report = StrictHealthLLM._report(result, "model-incomplete")
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="incomplete",
                reason_code="model-incomplete",
                candidate=None,
                transport_reason=result.incomplete_reason,
                model_report=report,
            )
        if result.status == "failed":
            report = StrictHealthLLM._report(result, "model-failed")
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="failed",
                reason_code="model-failed",
                candidate=None,
                transport_reason=result.failure_reason,
                model_report=report,
            )
        raise NotImplementedError("remaining strict-port result cases are not implemented")

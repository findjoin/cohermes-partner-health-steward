"""One-shot Responses transport and profile-bound production measurement.

This module consumes the target-local, approved capability artifacts.  It does
not establish their medical, provider, or approval facts.  In particular a
configured context window is never converted into a capability profile here.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Mapping

from .initialization import stable_digest
from .knowledge import (
    ImmutableKnowledgeRegistry, KnowledgeContractViolation, KnowledgeGap,
    KnowledgePublicationInput, KnowledgePublisher, KnowledgeRelease,
)
from .model_contract import (
    CapabilityProfile, FirstHopRoute, ModelContractViolation,
    ModelTransportResult, StrictHealthLLM, StrictModelRequest,
    _freeze_json, _thaw_json,
)


_METHOD = "responses-final-wire-utf8-upper-bound-v1"
_EVIDENCE_FIELDS = frozenset({
    "contract", "profile_binding_digest", "schema_digest", "wire_builder_version",
    "method_id", "issued_at", "expires_at", "capacity_evidence_ref",
    "tokenizer_evidence_ref", "approval_ref",
})
_BODY_FIELDS = frozenset({
    "model", "instructions", "input", "store", "stream", "max_output_tokens", "text",
})
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise ModelContractViolation("invalid model JSON") from None


def _text(value: object) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > 16384:
        raise ModelContractViolation("invalid model metadata")
    return value


def _time(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value))
    except (TypeError, ValueError):
        raise ModelContractViolation("invalid measurement time") from None
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ModelContractViolation("measurement time must be UTC")
    return parsed


def _loads(value: str | bytes) -> object:
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ModelContractViolation("duplicate model JSON key")
            result[key] = item
        return result

    def invalid_constant(_value):
        raise ModelContractViolation("invalid model JSON number")

    try:
        return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (TypeError, ValueError, UnicodeError):
        raise ModelContractViolation("invalid model JSON") from None


def _validate_schema(schema: object) -> None:
    """Accept the bounded JSON-schema subset emitted by this release."""
    allowed = {"type", "properties", "required", "additionalProperties", "items",
               "enum", "const", "description", "minItems", "maxItems",
               "minLength", "maxLength", "minimum", "maximum", "anyOf"}
    if type(schema) is not dict or not schema or not set(schema).issubset(allowed):
        raise ModelContractViolation("unsupported governed schema")
    kind = schema.get("type")
    kinds = kind if type(kind) is list else [kind]
    if "anyOf" in schema:
        if type(schema["anyOf"]) is not list or not schema["anyOf"]:
            raise ModelContractViolation("invalid governed schema alternatives")
        for item in schema["anyOf"]:
            _validate_schema(item)
    elif not kinds or any(k not in {"object", "array", "string", "integer", "number",
                                    "boolean", "null"} for k in kinds):
        raise ModelContractViolation("invalid governed schema type")
    if "object" in kinds:
        props, required = schema.get("properties"), schema.get("required")
        if (type(props) is not dict or type(required) is not list
                or any(type(key) is not str for key in props)
                or any(type(key) is not str or key not in props for key in required)
                or len(set(required)) != len(required)
                or schema.get("additionalProperties") is not False):
            raise ModelContractViolation("invalid governed object schema")
        for child in props.values():
            _validate_schema(child)
    if "array" in kinds:
        _validate_schema(schema.get("items"))
    if "enum" in schema and (type(schema["enum"]) is not list or not schema["enum"]):
        raise ModelContractViolation("invalid governed enum")
    for field in ("minItems", "maxItems", "minLength", "maxLength"):
        if field in schema and (type(schema[field]) is not int or schema[field] < 0):
            raise ModelContractViolation("invalid governed schema bound")
    for field in ("minimum", "maximum"):
        if field in schema and (type(schema[field]) not in {int, float}
                                or not math.isfinite(schema[field])):
            raise ModelContractViolation("invalid governed numeric bound")
    _canonical(schema)


def _matches(value: object, schema: dict) -> bool:
    if "anyOf" in schema and not any(_matches(value, part) for part in schema["anyOf"]):
        return False
    if "const" in schema and _canonical(value) != _canonical(schema["const"]):
        return False
    if "enum" in schema and not any(_canonical(value) == _canonical(x) for x in schema["enum"]):
        return False
    kind = schema.get("type")
    if kind is None:
        return True
    kinds = kind if type(kind) is list else [kind]
    actual = {dict: "object", list: "array", str: "string", int: "integer",
              float: "number", bool: "boolean", type(None): "null"}.get(type(value))
    if actual not in kinds and not (actual == "integer" and "number" in kinds):
        return False
    if actual == "object":
        props = schema["properties"]
        return (set(schema["required"]).issubset(value) and set(value).issubset(props)
                and all(_matches(item, props[key]) for key, item in value.items()))
    if actual == "array":
        return (schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", len(value))
                and all(_matches(item, schema["items"]) for item in value))
    if actual == "string":
        return schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value))
    if actual in {"integer", "number"}:
        return (math.isfinite(value) and schema.get("minimum", value) <= value
                <= schema.get("maximum", value))
    return True


@dataclass(frozen=True, init=False, repr=False)
class ProfileBoundInputMeasurementStrategy:
    """A specific approved measurement method, never an arbitrary callback."""

    _profile: CapabilityProfile
    _schema: object
    _evidence: object
    _clock: Callable[[], datetime]

    def __init__(self, profile, *, schema, measurement_evidence, clock=None):
        if type(profile) is not CapabilityProfile:
            raise ModelContractViolation("invalid production profile")
        profile = CapabilityProfile.from_wire(CapabilityProfile.to_wire(profile))
        if (profile.synthetic or profile.api_mode != "codex_responses"
                or profile.input_measurement_method != _METHOD):
            raise ModelContractViolation("unsupported production measurement")
        _validate_schema(schema)
        if type(measurement_evidence) is not dict or set(measurement_evidence) != _EVIDENCE_FIELDS:
            raise ModelContractViolation("invalid measurement evidence")
        evidence = copy.deepcopy(measurement_evidence)
        binding = profile.to_wire()
        binding.pop("evidence_refs")
        if (evidence["contract"] != "ticket125-model-measurement-evidence-v1"
                or evidence["wire_builder_version"] != "responses-fixed-wire-v1"
                or evidence["method_id"] != _METHOD
                or evidence["profile_binding_digest"] != stable_digest(binding)
                or evidence["schema_digest"] != stable_digest(schema)
                or stable_digest(evidence) not in profile.evidence_refs):
            raise ModelContractViolation("unbound measurement evidence")
        for ref in ("capacity_evidence_ref", "tokenizer_evidence_ref", "approval_ref"):
            _text(evidence[ref])
        if _time(evidence["issued_at"]) >= _time(evidence["expires_at"]):
            raise ModelContractViolation("invalid measurement validity interval")
        if clock is not None and not callable(clock):
            raise ModelContractViolation("invalid measurement clock")
        object.__setattr__(self, "_profile", profile)
        object.__setattr__(self, "_schema", _freeze_json(copy.deepcopy(schema), "governed schema"))
        object.__setattr__(self, "_evidence", _freeze_json(evidence, "measurement evidence"))
        object.__setattr__(self, "_clock", clock or (lambda: datetime.now(timezone.utc)))

    def canonical_copy(self):
        if type(self) is not ProfileBoundInputMeasurementStrategy:
            raise ModelContractViolation("invalid production measurement strategy")
        return ProfileBoundInputMeasurementStrategy(
            object.__getattribute__(self, "_profile"),
            schema=_thaw_json(object.__getattribute__(self, "_schema")),
            measurement_evidence=_thaw_json(object.__getattribute__(self, "_evidence")),
            clock=object.__getattribute__(self, "_clock"),
        )

    def _now(self):
        now = object.__getattribute__(self, "_clock")()
        if type(now) is not datetime or now.utcoffset() is None:
            raise ModelContractViolation("invalid measurement clock value")
        return now

    def _body(self, request):
        request = StrictModelRequest.canonical_copy(request)
        profile = object.__getattribute__(self, "_profile")
        schema = _thaw_json(object.__getattribute__(self, "_schema"))
        facts = (request.route.route_id, request.route.provider, request.route.canonical_base_url,
                 request.route.api_mode, request.route.requested_model,
                 request.route.configuration_generation)
        expected = (profile.route_id, profile.provider, profile.canonical_base_url,
                    profile.api_mode, profile.requested_model, profile.configuration_generation)
        if (request.capability_profile != profile or facts != expected
                or request.strict_schema_digest != stable_digest(schema)
                or request.output_reservation_tokens != profile.output_reservation_tokens):
            raise ModelContractViolation("production measurement authority drift")
        instructions = []
        messages = []
        seen_input = False
        for message in request.messages:
            if not message.content.strip():
                raise ModelContractViolation("empty production model message")
            if message.role == "system":
                if seen_input:
                    raise ModelContractViolation("interleaved production system message")
                instructions.append(message.content)
            else:
                seen_input = True
                messages.append({
                    "role": message.role,
                    "content": [{"type": "output_text" if message.role == "assistant" else "input_text",
                                 "text": message.content}],
                })
        if not instructions or not messages:
            raise ModelContractViolation("incomplete production model input")
        return {
            "model": request.route.requested_model, "instructions": "\n\n".join(instructions),
            "input": messages, "store": False, "stream": True,
            "max_output_tokens": request.output_reservation_tokens,
            "text": {"format": {"type": "json_schema", "name": request.strict_schema_name,
                                "schema": schema, "strict": True}},
        }

    def measure(self, request: StrictModelRequest) -> int:
        strategy = ProfileBoundInputMeasurementStrategy.canonical_copy(self)
        body = ProfileBoundInputMeasurementStrategy._body(strategy, request)
        evidence = object.__getattribute__(strategy, "_evidence")
        now = ProfileBoundInputMeasurementStrategy._now(strategy)
        if not _time(evidence["issued_at"]) <= now < _time(evidence["expires_at"]):
            raise ModelContractViolation("measurement evidence is not current")
        return len(_canonical(body))

    def _expired_after_attempt(self, request: StrictModelRequest) -> bool:
        """Recognize only time expiry, without weakening other admission facts."""
        strategy = ProfileBoundInputMeasurementStrategy.canonical_copy(self)
        body = ProfileBoundInputMeasurementStrategy._body(strategy, request)
        profile = object.__getattribute__(strategy, "_profile")
        if (request.final_input_upper_bound_tokens < len(_canonical(body))
                or request.final_input_upper_bound_tokens + profile.fixed_wrapper_tokens
                + request.output_reservation_tokens > profile.common_context_lower_bound_tokens):
            return False
        evidence = object.__getattribute__(strategy, "_evidence")
        return ProfileBoundInputMeasurementStrategy._now(strategy) >= _time(evidence["expires_at"])


class BoundResponsesTransport:
    """One HTTPS POST to the bound route, with no retry/redirect/proxy fallback."""

    def __init__(self, route, *, credential_provider, timeout_seconds=60.0):
        if type(route) is not FirstHopRoute or route.api_mode != "codex_responses":
            raise ModelContractViolation("invalid Responses transport route")
        if not callable(credential_provider):
            raise ModelContractViolation("missing model credential capability")
        if (type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 600):
            raise ModelContractViolation("invalid Responses timeout")
        self._route = FirstHopRoute.from_wire(route.to_wire())
        self._credential_provider = credential_provider
        self._timeout = float(timeout_seconds)

    @property
    def route(self):
        return self._route

    def send(self, body):
        if (type(body) is not dict or set(body) != _BODY_FIELDS
                or body["model"] != self._route.requested_model
                or body["store"] is not False or body["stream"] is not True):
            raise ModelContractViolation("invalid bound Responses body")
        encoded = _canonical(body)
        try:
            import httpx
            credential = self._credential_provider()
            if (type(credential) is not str or not credential or len(credential) > 16384
                    or "\r" in credential or "\n" in credential):
                raise ValueError("invalid credential")
            with httpx.Client(
                timeout=self._timeout, trust_env=False, follow_redirects=False,
                transport=httpx.HTTPTransport(retries=0),
            ) as client:
                with client.stream(
                    "POST", self._route.canonical_base_url + "/responses", content=encoded,
                    headers={"Authorization": "Bearer " + credential,
                             "Content-Type": "application/json", "Accept": "text/event-stream"},
                ) as response:
                    if response.status_code != 200:
                        raise ValueError("unconfirmed model result")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type == "text/event-stream":
                        return _read_sse(response)
                    if content_type != "application/json":
                        raise ValueError("unconfirmed model response format")
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > _MAX_RESPONSE_BYTES:
                            raise ValueError("oversized model result")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
            return _loads(raw)
        except Exception:
            # Never chain raw HTTP errors, headers, endpoint bodies or keys.
            raise ModelContractViolation("Responses result is unconfirmed") from None


def _read_sse(response):
    """Stop at an observed terminal rather than lose it waiting for HTTP EOF."""
    events, data, pending, size = [], [], b"", 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > _MAX_RESPONSE_BYTES:
            raise ModelContractViolation("oversized model event stream")
        pending += chunk
        while b"\n" in pending:
            encoded, pending = pending.split(b"\n", 1)
            line = encoded.rstrip(b"\r").decode("utf-8")
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif not line and data:
                item = "\n".join(data)
                data = []
                if item == "[DONE]":
                    return events
                event = _loads(item)
                if type(event) is not dict:
                    raise ModelContractViolation("invalid model stream event")
                events.append(event)
                if len(events) > 4096:
                    raise ModelContractViolation("oversized model event sequence")
                if event.get("type") in {"response.completed", "response.incomplete", "response.failed"}:
                    return events
    # A terminal event must be fully delimited; partial trailing data is not it.
    return events


class ProductionModelAdapter:
    """Execute the exact authorized request once and retain raw terminal facts."""

    def __init__(self, route, profile, *, transport, measurement_strategy):
        if type(route) is not FirstHopRoute or type(profile) is not CapabilityProfile:
            raise ModelContractViolation("invalid production model binding")
        self._route = FirstHopRoute.from_wire(route.to_wire())
        self._profile = CapabilityProfile.from_wire(profile.to_wire())
        self._strategy = ProfileBoundInputMeasurementStrategy.canonical_copy(measurement_strategy)
        if object.__getattribute__(self._strategy, "_profile") != self._profile:
            raise ModelContractViolation("production model profile drift")
        if getattr(transport, "route", None) != self._route or not callable(getattr(transport, "send", None)):
            raise ModelContractViolation("production model transport drift")
        self._transport = transport

    def execute(self, payload) -> ModelTransportResult:
        request = StrictModelRequest.from_wire(payload)
        if request.route != self._route or request.capability_profile != self._profile:
            raise ModelContractViolation("production model request drift")
        llm = StrictHealthLLM(self._route, self._profile, request.strict_schema_name,
                              request.strict_schema_digest, measurement_strategy=self._strategy)
        if StrictHealthLLM.preflight(llm, request) is not None:
            raise ModelContractViolation("production model preflight rejected")
        body = ProfileBoundInputMeasurementStrategy._body(self._strategy, request)
        # Check immediately before the irreversible send, including exact bytes.
        if (getattr(self._transport, "route", None) != self._route
                or ProfileBoundInputMeasurementStrategy.measure(self._strategy, request)
                > request.final_input_upper_bound_tokens):
            raise ModelContractViolation("production model authority changed")
        try:
            raw = self._transport.send(body)
            terminal = self._terminal(raw)
            return self._result(request, terminal)
        except Exception:
            return ModelTransportResult(
                response_id="unconfirmed:" + request.digest.removeprefix("sha256:"),
                requested_model=request.route.requested_model, actual_model="unconfirmed",
                status="unknown", incomplete_reason=None, failure_reason=None,
                usage_input_tokens=0, usage_output_tokens=0, fallback_observed=False,
                truncated=False, terminal_proven=False, structured_output=None,
            )

    @staticmethod
    def _terminal(raw):
        if type(raw) is dict:
            return raw
        if isinstance(raw, (str, bytes, Mapping)):
            raise ModelContractViolation("invalid raw model result")
        terminal, response_id, completed_items = None, None, []
        count, size = 0, 0
        for event in raw:
            count += 1
            size += len(_canonical(event))
            if count > 4096 or size > _MAX_RESPONSE_BYTES or type(event) is not dict:
                raise ModelContractViolation("invalid model event sequence")
            kind = event.get("type")
            if type(kind) is not str or "function_call" in kind or "web_search" in kind:
                raise ModelContractViolation("unexpected model event")
            if kind == "error":
                raise ModelContractViolation("unconfirmed model event")
            response = event.get("response")
            event_id = event.get("response_id")
            if type(response) is dict:
                event_id = response.get("id", event_id)
            if event_id is not None:
                event_id = _text(event_id)
                if response_id is not None and response_id != event_id:
                    raise ModelContractViolation("model response identity conflict")
                response_id = event_id
            if kind == "response.output_item.done":
                item = event.get("item")
                if type(item) is not dict or item.get("type") not in {"message", "reasoning"}:
                    raise ModelContractViolation("unexpected model output item")
                completed_items.append(item)
            if kind in {"response.completed", "response.incomplete", "response.failed"}:
                if (type(response) is not dict or response.get("status") != kind.removeprefix("response.")
                        or terminal is not None and _canonical(terminal) != _canonical(response)):
                    raise ModelContractViolation("model terminal conflict")
                terminal = copy.deepcopy(response)
        if terminal is None:
            raise ModelContractViolation("model terminal not observed")
        if terminal.get("output") is None and completed_items:
            terminal["output"] = completed_items
        return terminal

    def _result(self, request, raw):
        _canonical(raw)
        if len(_canonical(raw)) > _MAX_RESPONSE_BYTES:
            raise ModelContractViolation("oversized model terminal")
        response_id, actual_model = _text(raw.get("id")), _text(raw.get("model"))
        status, usage = raw.get("status"), raw.get("usage")
        if status not in {"completed", "incomplete", "failed"} or type(usage) is not dict:
            raise ModelContractViolation("unconfirmed model terminal metadata")
        for name in ("input_tokens", "output_tokens"):
            if type(usage.get(name)) is not int or usage[name] < 0:
                raise ModelContractViolation("unconfirmed model usage")
        output = raw.get("output")
        if type(output) is not list or any(type(x) is not dict or x.get("type") not in {"message", "reasoning"} for x in output):
            raise ModelContractViolation("unexpected model output")
        fallback = raw.get("fallback_observed", False)
        truncated = raw.get("truncated", False)
        if type(fallback) is not bool or type(truncated) is not bool:
            raise ModelContractViolation("invalid model result flags")
        candidate, incomplete, failed = None, None, None
        if status == "completed":
            if raw.get("incomplete_details") is not None or raw.get("error") is not None:
                raise ModelContractViolation("conflicting model terminal")
            texts = []
            for item in output:
                if item["type"] == "reasoning":
                    continue
                if item.get("status") != "completed" or type(item.get("content")) is not list:
                    raise ModelContractViolation("incomplete model output item")
                for content in item["content"]:
                    if type(content) is not dict or content.get("type") != "output_text":
                        raise ModelContractViolation("unexpected model content")
                    texts.append(_text(content.get("text")))
            if len(texts) != 1:
                raise ModelContractViolation("ambiguous model structured output")
            candidate = _loads(texts[0])
            if type(candidate) is not dict or not _matches(candidate, _thaw_json(self._strategy._schema)):
                raise ModelContractViolation("invalid model structured output")
        elif status == "incomplete":
            details = raw.get("incomplete_details")
            if type(details) is not dict or raw.get("error") is not None:
                raise ModelContractViolation("invalid incomplete model result")
            reason = _text(details.get("reason"))
            incomplete = reason if reason in {"max_output_tokens", "content_filter"} else "provider-incomplete"
        else:
            error = raw.get("error")
            if type(error) is not dict or raw.get("incomplete_details") is not None:
                raise ModelContractViolation("invalid failed model result")
            code = _text(error.get("code"))
            failed = code if code in {"server_error", "rate_limit_exceeded", "invalid_request", "content_filter"} else "provider-failed"
        return ModelTransportResult(response_id, request.route.requested_model, actual_model,
                                    status, incomplete, failed, usage["input_tokens"],
                                    usage["output_tokens"], fallback, truncated, True, candidate)


def load_governed_knowledge_artifact(artifact, *, expected_digest, at):
    """Rebuild an owner-independent publication before admitting its metadata."""
    fields = {"contract", "publication", "release_version", "release"}
    if (type(artifact) is not dict or set(artifact) != fields
            or artifact["contract"] != "ticket125-governed-knowledge-artifact-v1"
            or stable_digest(artifact) != expected_digest):
        raise KnowledgeContractViolation("invalid governed knowledge artifact")
    publication = KnowledgePublicationInput.from_wire(artifact["publication"])
    rebuilt = KnowledgePublisher().publish(publication, release_version=artifact["release_version"])
    if type(rebuilt) is KnowledgeGap:
        return rebuilt
    declared = KnowledgeRelease.from_wire(artifact["release"])
    if rebuilt != replace(declared, withdrawn=False):
        raise KnowledgeContractViolation("governed knowledge publication mismatch")
    registry = ImmutableKnowledgeRegistry()
    registry.stage(declared)
    return registry.resolve(declared.topic_id, at=at)

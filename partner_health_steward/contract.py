"""Strict, typed private Plugin/core command and result protocol."""

from __future__ import annotations

import json
import struct
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

from .admission import AdmissionPolicy, SourceEnvelope
from .authority import EffectIntent, MAX_OPAQUE_TEXT_BYTES
from .coordination import DailyTurnDraft, DailyTurnResult
from .initialization import InitializationDisclosure, OwnerInitialization, SkillUseProof


PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 64 * 1024
# Protocol strings and all typed authority fields share one representability
# boundary.  A current-head response outside it is untrusted and fail-closed.
MAX_ID_BYTES = MAX_OPAQUE_TEXT_BYTES


class ProtocolViolation(ValueError):
    """Raised when a private protocol frame cannot be trusted."""


class IncompleteResult(ProtocolViolation):
    """Raised when an effect result has no complete terminal state."""


def _bounded_text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise ProtocolViolation(f"invalid {name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ProtocolViolation(f"invalid {name}") from exc
    if len(encoded) > MAX_ID_BYTES:
        raise ProtocolViolation(f"invalid {name}")
    return value


def _strict_mapping(value: object, fields: frozenset[str], name: str) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise ProtocolViolation(f"invalid {name} fields")
    return value


class _WireValue(Mapping[str, object]):
    """A typed value that remains read-compatible with the test wire seam."""

    def __getitem__(self, key: str) -> object:
        return self.to_wire()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_wire())

    def __len__(self) -> int:
        return len(self.to_wire())

    def to_wire(self) -> dict[str, object]:
        raise NotImplementedError


class CommandPayload(_WireValue):
    pass


@dataclass(frozen=True)
class ProbePayload(CommandPayload):
    def to_wire(self) -> dict[str, object]:
        return {}


@dataclass(frozen=True)
class InboundAdmitPayload(CommandPayload):
    envelope: SourceEnvelope
    admission_policy: AdmissionPolicy

    def __post_init__(self) -> None:
        if type(self.envelope) is not SourceEnvelope:
            raise ProtocolViolation("invalid source envelope")
        if type(self.admission_policy) is not AdmissionPolicy:
            raise ProtocolViolation("invalid admission policy")

    def to_wire(self) -> dict[str, object]:
        return {
            "envelope": self.envelope.to_storage(),
            "admission_policy": self.admission_policy.to_storage(),
        }


@dataclass(frozen=True)
class InitializationPreparePayload(CommandPayload):
    initialization: OwnerInitialization
    skill_proof: SkillUseProof

    def __post_init__(self) -> None:
        if type(self.initialization) is not OwnerInitialization:
            raise ProtocolViolation("invalid owner initialization")
        if type(self.skill_proof) is not SkillUseProof:
            raise ProtocolViolation("invalid health-init proof")

    def to_wire(self) -> dict[str, object]:
        return {
            "initialization": self.initialization.to_storage(),
            "skill_proof": self.skill_proof.to_storage(),
        }


@dataclass(frozen=True)
class DailyTurnPreparePayload(CommandPayload):
    draft: DailyTurnDraft

    def __post_init__(self) -> None:
        if type(self.draft) is not DailyTurnDraft:
            raise ProtocolViolation("invalid daily turn draft")

    def to_wire(self) -> dict[str, object]:
        return {"draft": self.draft.to_storage()}


@dataclass(frozen=True)
class InitializationDisclosurePayload(CommandPayload):
    initialization: OwnerInitialization
    disclosure: InitializationDisclosure
    admission_policy: AdmissionPolicy

    def __post_init__(self) -> None:
        if type(self.initialization) is not OwnerInitialization:
            raise ProtocolViolation("invalid owner initialization")
        if type(self.disclosure) is not InitializationDisclosure:
            raise ProtocolViolation("invalid initialization disclosure")
        if type(self.admission_policy) is not AdmissionPolicy:
            raise ProtocolViolation("invalid admission policy")

    def to_wire(self) -> dict[str, object]:
        return {
            "initialization": self.initialization.to_storage(),
            "disclosure": self.disclosure.to_storage(),
            "admission_policy": self.admission_policy.to_storage(),
        }


@dataclass(frozen=True)
class NativeCursorResultPayload(CommandPayload):
    source_causal_id: str
    native_cursor: str
    status: str

    def __post_init__(self) -> None:
        _bounded_text(self.source_causal_id, "source causal identifier")
        _bounded_text(self.native_cursor, "native cursor")
        if type(self.status) is not str or self.status not in {"advanced", "unknown"}:
            raise ProtocolViolation("invalid native cursor status")

    def to_wire(self) -> dict[str, object]:
        return {
            "source_causal_id": self.source_causal_id,
            "native_cursor": self.native_cursor,
            "status": self.status,
        }


@dataclass(frozen=True)
class StateCandidatePayload(CommandPayload):
    record_id: str
    revision_digest: str
    transition_id: str
    payload_digest: str

    def __post_init__(self) -> None:
        _bounded_text(self.record_id, "record_id")
        _bounded_text(self.revision_digest, "revision_digest")
        _bounded_text(self.transition_id, "transition_id")
        _bounded_text(self.payload_digest, "payload_digest")

    def to_wire(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "revision_digest": self.revision_digest,
            "transition_id": self.transition_id,
            "payload_digest": self.payload_digest,
        }


@dataclass(frozen=True)
class StateCommitPayload(CommandPayload):
    record_id: str
    revision_digest: str
    transition_id: str
    writer_fence: str

    def __post_init__(self) -> None:
        _bounded_text(self.record_id, "record_id")
        _bounded_text(self.revision_digest, "revision_digest")
        _bounded_text(self.transition_id, "transition_id")
        _bounded_text(self.writer_fence, "writer_fence")

    def to_wire(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "revision_digest": self.revision_digest,
            "transition_id": self.transition_id,
            "writer_fence": self.writer_fence,
        }


@dataclass(frozen=True)
class EffectRequestPayload(CommandPayload):
    effect_kind: str
    request_digest: str

    def __post_init__(self) -> None:
        _bounded_text(self.effect_kind, "effect_kind")
        _bounded_text(self.request_digest, "request_digest")
        if self.effect_kind not in {"model-work", "owner-delivery", "contact-delivery"}:
            raise ProtocolViolation("invalid effect kind")

    def to_wire(self) -> dict[str, object]:
        return {"effect_kind": self.effect_kind, "request_digest": self.request_digest}


@dataclass(frozen=True)
class EffectResultPayload(CommandPayload):
    effect_id: str
    intent_digest: str
    lease_id: str
    completion_capability: str
    status: str
    terminal: bool
    result_digest: str

    def __post_init__(self) -> None:
        _bounded_text(self.effect_id, "effect_id")
        _bounded_text(self.intent_digest, "intent_digest")
        _bounded_text(self.lease_id, "lease_id")
        _bounded_text(self.completion_capability, "completion_capability")
        _bounded_text(self.status, "status")
        _bounded_text(self.result_digest, "result_digest")
        if self.status not in {"accepted", "rejected", "unknown"}:
            raise ProtocolViolation("invalid effect status")
        if type(self.terminal) is not bool:
            raise ProtocolViolation("effect terminal must be boolean")
        if self.status == "unknown" and not self.terminal:
            raise IncompleteResult("unknown effect must be terminal")

    def to_wire(self) -> dict[str, object]:
        return {
            "effect_id": self.effect_id,
            "intent_digest": self.intent_digest,
            "lease_id": self.lease_id,
            "completion_capability": self.completion_capability,
            "status": self.status,
            "terminal": self.terminal,
            "result_digest": self.result_digest,
        }


_PAYLOAD_TYPES: dict[str, type[CommandPayload]] = {
    "probe": ProbePayload,
    "inbound.admit": InboundAdmitPayload,
    "initialization.disclose": InitializationDisclosurePayload,
    "initialization.prepare": InitializationPreparePayload,
    "turn.prepare": DailyTurnPreparePayload,
    "cursor.result": NativeCursorResultPayload,
    "state.candidate": StateCandidatePayload,
    "state.prepare": StateCandidatePayload,
    "state.commit": StateCommitPayload,
    "state.finalize": StateCommitPayload,
    "effect.request": EffectRequestPayload,
    "effect.result": EffectResultPayload,
}

_ACTION_SCOPES = {
    "probe": "probe",
    "inbound.admit": "inbound:admit",
    "initialization.disclose": "initialization:disclose",
    "initialization.prepare": "initialization:prepare",
    "turn.prepare": "turn:prepare",
    "cursor.result": "cursor:result",
    "state.candidate": "state:candidate",
    "state.prepare": "state:prepare",
    "state.commit": "state:commit",
    "state.finalize": "state:finalize",
    "effect.request": "effect:request",
    "effect.result": "effect:result",
}

_TOP_LEVEL_KEYS = frozenset(
    {
        "protocol_version",
        "peer",
        "action",
        "source",
        "causal_id",
        "generation",
        "scope",
        "payload",
    }
)


def _parse_payload(action: str, value: object) -> CommandPayload:
    payload_type = _PAYLOAD_TYPES.get(action)
    if payload_type is None:
        raise ProtocolViolation("unknown action")
    if type(value) is payload_type:
        return value
    if isinstance(value, CommandPayload):
        raise ProtocolViolation("invalid payload for action")
    if payload_type is ProbePayload:
        _strict_mapping(value, frozenset(), "payload")
        return ProbePayload()
    if payload_type is InboundAdmitPayload:
        fields = _strict_mapping(
            value,
            frozenset({"envelope", "admission_policy"}),
            "payload",
        )
        try:
            envelope = SourceEnvelope.from_storage(fields["envelope"])
            admission_policy = AdmissionPolicy.from_storage(
                fields["admission_policy"]
            )
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("invalid source envelope") from exc
        return InboundAdmitPayload(envelope, admission_policy)
    if payload_type is InitializationDisclosurePayload:
        fields = _strict_mapping(
            value,
            frozenset({"initialization", "disclosure", "admission_policy"}),
            "payload",
        )
        try:
            initialization = OwnerInitialization.from_storage(fields["initialization"])
            disclosure = InitializationDisclosure.from_storage(fields["disclosure"])
            admission_policy = AdmissionPolicy.from_storage(
                fields["admission_policy"]
            )
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("invalid initialization disclosure payload") from exc
        return InitializationDisclosurePayload(
            initialization,
            disclosure,
            admission_policy,
        )
    if payload_type is InitializationPreparePayload:
        fields = _strict_mapping(
            value,
            frozenset({"initialization", "skill_proof"}),
            "payload",
        )
        try:
            initialization = OwnerInitialization.from_storage(fields["initialization"])
            proof = SkillUseProof.from_storage(fields["skill_proof"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("invalid initialization payload") from exc
        return InitializationPreparePayload(initialization, proof)
    if payload_type is DailyTurnPreparePayload:
        fields = _strict_mapping(value, frozenset({"draft"}), "payload")
        try:
            draft = DailyTurnDraft.from_storage(fields["draft"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("invalid daily turn payload") from exc
        return DailyTurnPreparePayload(draft)
    if payload_type is NativeCursorResultPayload:
        fields = _strict_mapping(
            value,
            frozenset({"source_causal_id", "native_cursor", "status"}),
            "payload",
        )
        return NativeCursorResultPayload(
            _bounded_text(fields["source_causal_id"], "source causal identifier"),
            _bounded_text(fields["native_cursor"], "native cursor"),
            _bounded_text(fields["status"], "native cursor status"),
        )
    if payload_type is StateCandidatePayload:
        fields = _strict_mapping(
            value,
            frozenset({"record_id", "revision_digest", "transition_id", "payload_digest"}),
            "payload",
        )
        return StateCandidatePayload(
            _bounded_text(fields["record_id"], "record_id"),
            _bounded_text(fields["revision_digest"], "revision_digest"),
            _bounded_text(fields["transition_id"], "transition_id"),
            _bounded_text(fields["payload_digest"], "payload_digest"),
        )
    if payload_type is StateCommitPayload:
        fields = _strict_mapping(
            value,
            frozenset({"record_id", "revision_digest", "transition_id", "writer_fence"}),
            "payload",
        )
        return StateCommitPayload(
            _bounded_text(fields["record_id"], "record_id"),
            _bounded_text(fields["revision_digest"], "revision_digest"),
            _bounded_text(fields["transition_id"], "transition_id"),
            _bounded_text(fields["writer_fence"], "writer_fence"),
        )
    if payload_type is EffectRequestPayload:
        fields = _strict_mapping(value, frozenset({"effect_kind", "request_digest"}), "payload")
        return EffectRequestPayload(
            _bounded_text(fields["effect_kind"], "effect_kind"),
            _bounded_text(fields["request_digest"], "request_digest"),
        )
    fields = _strict_mapping(
        value,
        frozenset(
            {"effect_id", "intent_digest", "lease_id", "completion_capability", "status", "terminal", "result_digest"}
        ),
        "payload",
    )
    return EffectResultPayload(
        _bounded_text(fields["effect_id"], "effect_id"),
        _bounded_text(fields["intent_digest"], "intent_digest"),
        _bounded_text(fields["lease_id"], "lease_id"),
        _bounded_text(fields["completion_capability"], "completion_capability"),
        _bounded_text(fields["status"], "status"),
        fields["terminal"] if type(fields["terminal"]) is bool else _invalid_terminal(),
        _bounded_text(fields["result_digest"], "result_digest"),
    )


def _invalid_terminal() -> bool:
    raise ProtocolViolation("effect terminal must be boolean")


class ResponseMeta(_WireValue):
    pass


@dataclass(frozen=True)
class EmptyMeta(ResponseMeta):
    def to_wire(self) -> dict[str, object]:
        return {}


@dataclass(frozen=True)
class ProbeMeta(ResponseMeta):
    probe_state: str

    def __post_init__(self) -> None:
        if (
            type(self.probe_state) is not str
            or self.probe_state not in {"healthy", "unavailable", "unknown"}
        ):
            raise ProtocolViolation("invalid probe metadata")

    def to_wire(self) -> dict[str, object]:
        return {"probe_state": self.probe_state}


@dataclass(frozen=True)
class CommitMeta(ResponseMeta):
    generation: int
    writer_fence: str

    def __post_init__(self) -> None:
        if type(self.generation) is not int or self.generation < 1:
            raise ProtocolViolation("invalid commit generation")
        _bounded_text(self.writer_fence, "writer_fence")

    def to_wire(self) -> dict[str, object]:
        return {"generation": self.generation, "writer_fence": self.writer_fence}


@dataclass(frozen=True)
class EffectIntentMeta(ResponseMeta):
    intent: EffectIntent

    def __post_init__(self) -> None:
        if type(self.intent) is not EffectIntent:
            raise ProtocolViolation("invalid effect metadata")

    def to_wire(self) -> dict[str, object]:
        return self.intent.to_wire_metadata()


@dataclass(frozen=True)
class DailyTurnMeta(ResponseMeta):
    turn_result: DailyTurnResult

    def __post_init__(self) -> None:
        if type(self.turn_result) is not DailyTurnResult:
            raise ProtocolViolation("invalid daily turn metadata")

    def to_wire(self) -> dict[str, object]:
        return {"turn_result": self.turn_result.to_storage()}


def _parse_response_meta(value: object) -> ResponseMeta:
    if type(value) in {
        EmptyMeta,
        ProbeMeta,
        CommitMeta,
        EffectIntentMeta,
        DailyTurnMeta,
    }:
        return value
    if isinstance(value, ResponseMeta) or type(value) is not dict:
        raise ProtocolViolation("invalid response metadata")
    keys = set(value)
    if keys == set():
        return EmptyMeta()
    if keys == {"probe_state"}:
        return ProbeMeta(_bounded_text(value["probe_state"], "probe_state"))
    if keys == {"generation", "writer_fence"}:
        return CommitMeta(value["generation"], _bounded_text(value["writer_fence"], "writer_fence"))
    if keys == {"turn_result"}:
        try:
            turn_result = DailyTurnResult.from_storage(value["turn_result"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("invalid daily turn metadata") from exc
        return DailyTurnMeta(turn_result)
    effect_fields = {"effect_id", "effect_kind", "intent_digest", "authority"}
    if keys == effect_fields:
        try:
            intent = EffectIntent.from_wire_metadata(value)
        except ValueError as exc:
            raise ProtocolViolation("invalid effect metadata") from exc
        return EffectIntentMeta(intent)
    raise ProtocolViolation("invalid response metadata")


@dataclass(frozen=True)
class CommandEnvelope:
    peer: str
    action: str
    source: str
    causal_id: str
    generation: int
    scope: tuple[str, ...]
    payload: CommandPayload | Mapping[str, object] = field(default_factory=ProbePayload)
    protocol_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.protocol_version) is not int
            or self.protocol_version != PROTOCOL_VERSION
        ):
            raise ProtocolViolation("unsupported protocol version")
        if type(self.peer) is not str or self.peer != "plugin":
            raise ProtocolViolation("untrusted peer")
        _bounded_text(self.action, "action")
        _bounded_text(self.source, "source")
        _bounded_text(self.causal_id, "causal_id")
        if type(self.generation) is not int or self.generation < 1:
            raise ProtocolViolation("invalid generation")
        expected_scope = _ACTION_SCOPES.get(self.action)
        if expected_scope is None:
            raise ProtocolViolation("unknown action")
        if (
            type(self.scope) is not tuple
            or not self.scope
            or any(type(item) is not str for item in self.scope)
            or self.scope != (expected_scope,)
        ):
            raise ProtocolViolation("permission scope denied")
        object.__setattr__(self, "payload", _parse_payload(self.action, self.payload))

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "peer": self.peer,
            "action": self.action,
            "source": self.source,
            "causal_id": self.causal_id,
            "generation": self.generation,
            "scope": list(self.scope),
            "payload": self.payload.to_wire(),
        }

    @classmethod
    def from_wire(cls, value: Mapping[str, object]) -> "CommandEnvelope":
        if type(value) is not dict or set(value) != _TOP_LEVEL_KEYS:
            raise ProtocolViolation("invalid command envelope fields")
        scope = value["scope"]
        if type(scope) is not list:
            raise ProtocolViolation("scope must be a list")
        return cls(
            protocol_version=value["protocol_version"],
            peer=value["peer"],
            action=value["action"],
            source=value["source"],
            causal_id=value["causal_id"],
            generation=value["generation"],
            scope=tuple(scope),
            payload=value["payload"],
        )


@dataclass(frozen=True)
class Response:
    status: str
    causal_id: str | None = None
    reason_code: str | None = None
    meta: ResponseMeta | Mapping[str, object] = field(default_factory=EmptyMeta)

    def __post_init__(self) -> None:
        if (
            type(self.status) is not str
            or self.status not in {"accepted", "replayed", "rejected", "unavailable", "unknown"}
        ):
            raise ProtocolViolation("invalid response status")
        if self.causal_id is not None:
            _bounded_text(self.causal_id, "causal_id")
        if self.reason_code is not None:
            _bounded_text(self.reason_code, "reason_code")
        object.__setattr__(self, "meta", _parse_response_meta(self.meta))

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "status": self.status,
            "causal_id": self.causal_id,
            "reason_code": self.reason_code,
            "meta": self.meta.to_wire(),
        }

    @classmethod
    def from_wire(cls, value: Mapping[str, object]) -> "Response":
        expected = {"protocol_version", "status", "causal_id", "reason_code", "meta"}
        if type(value) is not dict or set(value) != expected:
            raise ProtocolViolation("invalid response fields")
        if (
            type(value["protocol_version"]) is not int
            or value["protocol_version"] != PROTOCOL_VERSION
        ):
            raise ProtocolViolation("unsupported response version")
        return cls(value["status"], value["causal_id"], value["reason_code"], value["meta"])


def _json_bytes(value: Mapping[str, object]) -> bytes:
    try:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProtocolViolation("unserializable protocol value") from exc
    if len(body) > MAX_FRAME_BYTES:
        raise ProtocolViolation("frame too large")
    return body


def encode_frame(envelope: CommandEnvelope) -> bytes:
    body = _json_bytes(envelope.to_wire())
    return struct.pack(">I", len(body)) + body


def decode_frame(frame: bytes) -> CommandEnvelope:
    if not isinstance(frame, (bytes, bytearray, memoryview)) or len(frame) < 4:
        raise ProtocolViolation("truncated frame header")
    frame = bytes(frame)
    declared = struct.unpack(">I", frame[:4])[0]
    if declared > MAX_FRAME_BYTES or declared != len(frame) - 4:
        raise ProtocolViolation("truncated or trailing frame")
    try:
        value = json.loads(frame[4:].decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ProtocolViolation("invalid frame JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation("invalid command envelope fields")
    return CommandEnvelope.from_wire(value)


def canonicalize_command(value: object) -> CommandEnvelope:
    """Re-enter the strict wire parser for a direct in-process command.

    ``CommandEnvelope`` is an immutable convenience type, not a security
    boundary: hostile in-process callers can still construct or mutate an
    object without invoking ``__post_init__``.  Only the exact concrete type
    is accepted here, then its public wire representation is parsed again
    before any causal ID, scope, or payload field reaches storage.
    """

    if type(value) is not CommandEnvelope:
        raise ProtocolViolation("invalid command envelope")
    try:
        return decode_frame(encode_frame(value))
    except (AttributeError, TypeError, ValueError, ProtocolViolation) as exc:
        raise ProtocolViolation("invalid command envelope") from exc


def encode_raw_response(response: Response) -> bytes:
    body = _json_bytes(response.to_wire())
    return struct.pack(">I", len(body)) + body


def decode_response_frame(frame: bytes) -> Response:
    if not isinstance(frame, (bytes, bytearray, memoryview)) or len(frame) < 4:
        raise ProtocolViolation("truncated response header")
    frame = bytes(frame)
    declared = struct.unpack(">I", frame[:4])[0]
    if declared > MAX_FRAME_BYTES or declared != len(frame) - 4:
        raise ProtocolViolation("truncated or trailing response")
    try:
        value = json.loads(frame[4:].decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ProtocolViolation("invalid response JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation("invalid response fields")
    return Response.from_wire(value)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous duplicate JSON names before protocol interpretation."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolViolation("duplicate JSON field")
        result[key] = value
    return result

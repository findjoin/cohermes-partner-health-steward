"""Strict, private Plugin/core command and result protocol."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any, Mapping


PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 64 * 1024
MAX_ID_BYTES = 256


class ProtocolViolation(ValueError):
    """Raised when a private protocol frame cannot be trusted."""


class IncompleteResult(ProtocolViolation):
    """Raised when an effect result has no complete terminal state."""


_ACTION_FIELDS: dict[str, tuple[set[str], set[str], str]] = {
    "probe": (set(), set(), "probe"),
    "state.candidate": (
        {"record_id", "revision_digest", "transition_id", "payload_digest"},
        set(),
        "state:candidate",
    ),
    "state.prepare": (
        {"record_id", "revision_digest", "transition_id", "payload_digest"},
        set(),
        "state:prepare",
    ),
    "state.commit": (
        {"record_id", "revision_digest", "transition_id"},
        {"writer_fence"},
        "state:commit",
    ),
    "state.finalize": (
        {"record_id", "revision_digest", "transition_id", "writer_fence"},
        set(),
        "state:finalize",
    ),
    "effect.result": (
        {"effect_id", "status", "terminal", "result_digest"},
        set(),
        "effect:result",
    ),
}

_TOP_LEVEL_KEYS = {
    "protocol_version",
    "peer",
    "action",
    "source",
    "causal_id",
    "generation",
    "scope",
    "payload",
}


def _bounded_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_ID_BYTES:
        raise ProtocolViolation(f"invalid {name}")
    return value


@dataclass(frozen=True)
class CommandEnvelope:
    peer: str
    action: str
    source: str
    causal_id: str
    generation: int
    scope: tuple[str, ...]
    payload: Mapping[str, Any] = field(default_factory=dict)
    protocol_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.protocol_version != PROTOCOL_VERSION:
            raise ProtocolViolation("unsupported protocol version")
        if self.peer != "plugin":
            raise ProtocolViolation("untrusted peer")
        _bounded_text(self.source, "source")
        _bounded_text(self.causal_id, "causal_id")
        if not isinstance(self.generation, int) or isinstance(self.generation, bool) or self.generation < 1:
            raise ProtocolViolation("invalid generation")
        if self.action not in _ACTION_FIELDS:
            raise ProtocolViolation("unknown action")
        if not isinstance(self.scope, tuple) or not self.scope or any(not isinstance(item, str) for item in self.scope):
            raise ProtocolViolation("invalid permission scope")
        required, optional, expected_scope = _ACTION_FIELDS[self.action]
        if expected_scope not in self.scope:
            raise ProtocolViolation("permission scope denied")
        if not isinstance(self.payload, Mapping):
            raise ProtocolViolation("payload must be an object")
        keys = set(self.payload)
        if keys != required | (keys & optional):
            missing = required - keys
            extra = keys - required - optional
            raise ProtocolViolation(f"invalid payload fields missing={sorted(missing)} extra={sorted(extra)}")
        for key in required | optional:
            if key in self.payload and not isinstance(self.payload[key], (str, int, bool)):
                raise ProtocolViolation(f"invalid payload field: {key}")
        if self.action == "effect.result":
            status = self.payload["status"]
            if status not in {"accepted", "rejected", "unknown"}:
                raise ProtocolViolation("invalid effect status")
            if not isinstance(self.payload["terminal"], bool):
                raise ProtocolViolation("effect terminal must be boolean")
            if status == "unknown" and not self.payload["terminal"]:
                raise IncompleteResult("unknown effect must be terminal")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "peer": self.peer,
            "action": self.action,
            "source": self.source,
            "causal_id": self.causal_id,
            "generation": self.generation,
            "scope": list(self.scope),
            "payload": dict(self.payload),
        }

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> "CommandEnvelope":
        if not isinstance(value, Mapping) or set(value) != _TOP_LEVEL_KEYS:
            raise ProtocolViolation("invalid command envelope fields")
        scope = value["scope"]
        if not isinstance(scope, list):
            raise ProtocolViolation("scope must be a list")
        payload = value["payload"]
        return cls(
            protocol_version=value["protocol_version"],
            peer=value["peer"],
            action=value["action"],
            source=value["source"],
            causal_id=value["causal_id"],
            generation=value["generation"],
            scope=tuple(scope),
            payload=payload,
        )


@dataclass(frozen=True)
class Response:
    status: str
    causal_id: str | None = None
    reason_code: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"accepted", "replayed", "rejected", "unavailable", "unknown"}:
            raise ProtocolViolation("invalid response status")
        if self.causal_id is not None:
            _bounded_text(self.causal_id, "causal_id")
        if not isinstance(self.meta, Mapping):
            raise ProtocolViolation("invalid response metadata")

    def to_wire(self) -> dict[str, Any]:
        # Metadata is limited to opaque protocol facts; never include content.
        return {
            "protocol_version": PROTOCOL_VERSION,
            "status": self.status,
            "causal_id": self.causal_id,
            "reason_code": self.reason_code,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> "Response":
        if not isinstance(value, Mapping) or set(value) != {"protocol_version", "status", "causal_id", "reason_code", "meta"}:
            raise ProtocolViolation("invalid response fields")
        if value["protocol_version"] != PROTOCOL_VERSION:
            raise ProtocolViolation("unsupported response version")
        return cls(value["status"], value["causal_id"], value["reason_code"], value["meta"])


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError) as exc:
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
        value = json.loads(frame[4:].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("invalid frame JSON") from exc
    return CommandEnvelope.from_wire(value)


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
        value = json.loads(frame[4:].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("invalid response JSON") from exc
    return Response.from_wire(value)

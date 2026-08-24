"""Strict Ticket 115 health-command authority and replay receipts."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from .authority import MAX_OPAQUE_TEXT_BYTES


MAX_HEALTH_COMMAND_JSON_BYTES = 64 * 1024


class HealthCommandContractViolation(ValueError):
    """A health command or receipt cannot be treated as trusted authority."""


def _bounded_text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise HealthCommandContractViolation(f"invalid {name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HealthCommandContractViolation(f"invalid {name}") from exc
    if len(encoded) > MAX_OPAQUE_TEXT_BYTES:
        raise HealthCommandContractViolation(f"invalid {name}")
    return value


def _validate_json_value(value: object, name: str) -> None:
    value_type = type(value)
    if value is None or value_type in {bool, int}:
        return
    if value_type is float:
        if not math.isfinite(value):
            raise HealthCommandContractViolation(f"invalid {name}")
        return
    if value_type is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise HealthCommandContractViolation(f"invalid {name}") from exc
        return
    if value_type is list:
        for item in value:
            _validate_json_value(item, name)
        return
    if value_type is dict:
        for key, item in value.items():
            if type(key) is not str or not key:
                raise HealthCommandContractViolation(f"invalid {name}")
            try:
                key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise HealthCommandContractViolation(f"invalid {name}") from exc
            _validate_json_value(item, name)
        return
    raise HealthCommandContractViolation(f"invalid {name}")


def _canonical_json_object(value: object, name: str) -> str:
    if type(value) is not dict:
        raise HealthCommandContractViolation(f"invalid {name}")
    try:
        _validate_json_value(value, name)
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        encoded = canonical.encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeEncodeError) as exc:
        raise HealthCommandContractViolation(f"invalid {name}") from exc
    if len(encoded) > MAX_HEALTH_COMMAND_JSON_BYTES:
        raise HealthCommandContractViolation(f"invalid {name}")
    return canonical


def _json_object_copy(canonical: str) -> dict[str, object]:
    value = json.loads(canonical)
    if type(value) is not dict:  # pragma: no cover - produced internally
        raise HealthCommandContractViolation("invalid canonical JSON object")
    return value


def _sha256_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != len("sha256:") + 64
    ):
        raise HealthCommandContractViolation(f"invalid {name}")
    try:
        int(value.removeprefix("sha256:"), 16)
    except ValueError as exc:
        raise HealthCommandContractViolation(f"invalid {name}") from exc
    return value


@dataclass(frozen=True, init=False)
class TrustedHealthCommand:
    """One immutable semantic command carrying its complete trusted context."""

    action: str
    source: str
    causal_id: str
    generation: int
    scope: tuple[str, ...]
    _payload_json: str = field(repr=False)

    def __init__(
        self,
        *,
        action: str,
        source: str,
        causal_id: str,
        generation: int,
        scope: tuple[str, ...],
        payload: dict[str, object],
    ) -> None:
        action = _bounded_text(action, "health command action")
        source = _bounded_text(source, "health command source")
        causal_id = _bounded_text(causal_id, "health command causal identifier")
        if type(generation) is not int or generation < 1:
            raise HealthCommandContractViolation(
                "invalid health command generation"
            )
        if (
            type(scope) is not tuple
            or len(scope) != 1
            or any(type(item) is not str for item in scope)
        ):
            raise HealthCommandContractViolation("invalid health command scope")
        canonical_scope = tuple(
            _bounded_text(item, "health command scope") for item in scope
        )
        payload_json = _canonical_json_object(
            payload,
            "health command payload",
        )
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "causal_id", causal_id)
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "scope", canonical_scope)
        object.__setattr__(self, "_payload_json", payload_json)

    @property
    def payload(self) -> dict[str, object]:
        """Return a defensive copy of the canonical command payload."""

        return _json_object_copy(self._payload_json)

    @property
    def command_digest(self) -> str:
        return _sha256_digest(
            {
                "kind": "trusted-health-command-v1",
                "command": self.to_wire(),
            }
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "action": self.action,
            "source": self.source,
            "causal_id": self.causal_id,
            "generation": self.generation,
            "scope": list(self.scope),
            "payload": self.payload,
        }

    @classmethod
    def from_wire(cls, value: object) -> "TrustedHealthCommand":
        fields = frozenset(
            {"action", "source", "causal_id", "generation", "scope", "payload"}
        )
        if type(value) is not dict or frozenset(value) != fields:
            raise HealthCommandContractViolation(
                "invalid health command fields"
            )
        scope = value["scope"]
        if type(scope) is not list:
            raise HealthCommandContractViolation(
                "invalid health command scope"
            )
        return cls(
            action=value["action"],  # type: ignore[arg-type]
            source=value["source"],  # type: ignore[arg-type]
            causal_id=value["causal_id"],  # type: ignore[arg-type]
            generation=value["generation"],  # type: ignore[arg-type]
            scope=tuple(scope),
            payload=value["payload"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, init=False)
class HealthCommandReceipt:
    """The immutable exact-replay result for one trusted health command."""

    causal_id: str
    command_digest: str
    _result_json: str = field(repr=False)

    def __init__(
        self,
        *,
        causal_id: str,
        command_digest: str,
        result: dict[str, object],
    ) -> None:
        causal_id = _bounded_text(
            causal_id,
            "health command receipt causal identifier",
        )
        command_digest = _digest(
            command_digest,
            "health command receipt digest",
        )
        result_json = _canonical_json_object(
            result,
            "health command receipt result",
        )
        object.__setattr__(self, "causal_id", causal_id)
        object.__setattr__(self, "command_digest", command_digest)
        object.__setattr__(self, "_result_json", result_json)

    @property
    def result(self) -> dict[str, object]:
        """Return a defensive copy of the canonical replay result."""

        return _json_object_copy(self._result_json)

    def to_storage(self) -> dict[str, object]:
        return {
            "causal_id": self.causal_id,
            "command_digest": self.command_digest,
            "result": self.result,
        }

    @classmethod
    def from_storage(cls, value: object) -> "HealthCommandReceipt":
        fields = frozenset({"causal_id", "command_digest", "result"})
        if type(value) is not dict or frozenset(value) != fields:
            raise HealthCommandContractViolation(
                "invalid health command receipt fields"
            )
        return cls(
            causal_id=value["causal_id"],  # type: ignore[arg-type]
            command_digest=value["command_digest"],  # type: ignore[arg-type]
            result=value["result"],  # type: ignore[arg-type]
        )

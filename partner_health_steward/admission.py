"""Typed unique-Weixin admission values for the Partner health Plugin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .authority import AuthorityValidationError, validate_opaque_text


MAX_MESSAGE_BODY_BYTES = 16 * 1024


class MessageBody(Protocol):
    """Lazily materialized body supplied by the native Weixin adapter."""

    def read(self) -> str: ...


def _optional_opaque_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return validate_opaque_text(value, name)


def _timestamp(value: object, name: str) -> str:
    text = validate_opaque_text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AuthorityValidationError(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError(f"invalid {name}")
    return text


def _message_body(value: object) -> str:
    if type(value) is not str or not value:
        raise AuthorityValidationError("invalid message body")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AuthorityValidationError("invalid message body") from exc
    if len(encoded) > MAX_MESSAGE_BODY_BYTES:
        raise AuthorityValidationError("invalid message body")
    return value


@dataclass(frozen=True)
class AdmissionPolicy:
    """Exactly one technical Partner/private-owner admission tuple.

    This is a transport allowlist only.  It deliberately contains no claim
    about the natural person behind the configured sender and no consent bit.
    """

    partner_id: str
    owner_sender_id: str
    conversation_id: str
    channel: str = "weixin"
    entrypoint: str = "health_weixin"

    def __post_init__(self) -> None:
        validate_opaque_text(self.partner_id, "partner_id")
        validate_opaque_text(self.owner_sender_id, "owner_sender_id")
        validate_opaque_text(self.conversation_id, "conversation_id")
        if self.channel != "weixin" or self.entrypoint != "health_weixin":
            raise AuthorityValidationError("invalid admission policy")

    def rejection_reason(self, message: object) -> str | None:
        """Classify headers without materializing a possibly sensitive body."""

        if type(message) is not RawWeixinMessage:
            return "invalid-weixin-source"
        if message.entrypoint == "medical" or message.requested_capability == "medical":
            return "legacy-medical-entrypoint-denied"
        values = (
            (message.channel, self.channel),
            (message.partner_id, self.partner_id),
            (message.sender_id, self.owner_sender_id),
            (message.conversation_id, self.conversation_id),
            (message.chat_type, "private"),
            (message.entrypoint, self.entrypoint),
        )
        if any(type(actual) is not str or actual != expected for actual, expected in values):
            return "unique-private-source-denied"
        if message.requested_capability != "health-init":
            return "initialization-required"
        return None

    def accepts(self, envelope: object) -> bool:
        if type(envelope) is not SourceEnvelope:
            return False
        return (
            envelope.channel == self.channel
            and envelope.partner_id == self.partner_id
            and envelope.sender_id == self.owner_sender_id
            and envelope.conversation_id == self.conversation_id
            and envelope.chat_type == "private"
            and envelope.entrypoint == self.entrypoint
            and envelope.requested_capability == "health-init"
        )

    def to_storage(self) -> dict[str, object]:
        """Serialize the exact technical entrypoint that issued authority."""

        return {
            "partner_id": self.partner_id,
            "owner_sender_id": self.owner_sender_id,
            "conversation_id": self.conversation_id,
            "channel": self.channel,
            "entrypoint": self.entrypoint,
        }

    @classmethod
    def from_storage(cls, value: object) -> "AdmissionPolicy":
        fields = {
            "partner_id",
            "owner_sender_id",
            "conversation_id",
            "channel",
            "entrypoint",
        }
        if type(value) is not dict or set(value) != fields:
            raise AuthorityValidationError("invalid admission policy")
        return cls(
            partner_id=value["partner_id"],  # type: ignore[arg-type]
            owner_sender_id=value["owner_sender_id"],  # type: ignore[arg-type]
            conversation_id=value["conversation_id"],  # type: ignore[arg-type]
            channel=value["channel"],  # type: ignore[arg-type]
            entrypoint=value["entrypoint"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class RawWeixinMessage:
    """Untrusted native message headers plus a lazy body handle."""

    causal_id: object
    generation: object
    channel: object
    partner_id: object
    sender_id: object
    conversation_id: object
    chat_type: object
    entrypoint: object
    requested_capability: object
    message_id: object
    protocol_timestamp: object
    received_at: object
    native_cursor: object
    body: object


@dataclass(frozen=True)
class SourceEnvelope:
    """One faithful health-path observation after technical admission."""

    causal_id: str
    generation: int
    channel: str
    partner_id: str
    sender_id: str
    conversation_id: str
    chat_type: str
    entrypoint: str
    requested_capability: str
    message_id: str | None
    protocol_timestamp: str | None
    received_at: str
    native_cursor: str
    body: str | None

    def __post_init__(self) -> None:
        validate_opaque_text(self.causal_id, "causal_id")
        if type(self.generation) is not int or self.generation < 1:
            raise AuthorityValidationError("invalid generation")
        validate_opaque_text(self.channel, "channel")
        validate_opaque_text(self.partner_id, "partner_id")
        validate_opaque_text(self.sender_id, "sender_id")
        validate_opaque_text(self.conversation_id, "conversation_id")
        validate_opaque_text(self.chat_type, "chat_type")
        validate_opaque_text(self.entrypoint, "entrypoint")
        validate_opaque_text(self.requested_capability, "requested_capability")
        _optional_opaque_text(self.message_id, "message_id")
        if self.protocol_timestamp is not None:
            _timestamp(self.protocol_timestamp, "protocol_timestamp")
        _timestamp(self.received_at, "received_at")
        validate_opaque_text(self.native_cursor, "native_cursor")
        if self.body is not None:
            _message_body(self.body)

    def to_storage(self) -> dict[str, object]:
        return {
            "causal_id": self.causal_id,
            "generation": self.generation,
            "channel": self.channel,
            "partner_id": self.partner_id,
            "sender_id": self.sender_id,
            "conversation_id": self.conversation_id,
            "chat_type": self.chat_type,
            "entrypoint": self.entrypoint,
            "requested_capability": self.requested_capability,
            "message_id": self.message_id,
            "protocol_timestamp": self.protocol_timestamp,
            "received_at": self.received_at,
            "native_cursor": self.native_cursor,
            "body": self.body,
        }

    def without_body(self) -> "SourceEnvelope":
        return SourceEnvelope(
            causal_id=self.causal_id,
            generation=self.generation,
            channel=self.channel,
            partner_id=self.partner_id,
            sender_id=self.sender_id,
            conversation_id=self.conversation_id,
            chat_type=self.chat_type,
            entrypoint=self.entrypoint,
            requested_capability=self.requested_capability,
            message_id=self.message_id,
            protocol_timestamp=self.protocol_timestamp,
            received_at=self.received_at,
            native_cursor=self.native_cursor,
            body=None,
        )

    @classmethod
    def from_storage(cls, value: object) -> "SourceEnvelope":
        fields = {
            "causal_id",
            "generation",
            "channel",
            "partner_id",
            "sender_id",
            "conversation_id",
            "chat_type",
            "entrypoint",
            "requested_capability",
            "message_id",
            "protocol_timestamp",
            "received_at",
            "native_cursor",
            "body",
        }
        if type(value) is not dict or set(value) != fields:
            raise AuthorityValidationError("invalid source envelope")
        return cls(**value)


@dataclass(frozen=True)
class SourceReceipt:
    """Managed source observation and its non-conclusive replay relation."""

    envelope: SourceEnvelope
    relation: str
    related_causal_id: str | None
    managed_cursor_state: str
    native_cursor_state: str

    def __post_init__(self) -> None:
        if type(self.envelope) is not SourceEnvelope:
            raise AuthorityValidationError("invalid source receipt")
        if self.relation not in {
            "first-observation",
            "possible-replay",
            "replay-unknown",
        }:
            raise AuthorityValidationError("invalid source relation")
        _optional_opaque_text(self.related_causal_id, "related_causal_id")
        if self.relation == "first-observation" and (
            self.envelope.message_id is None or self.related_causal_id is not None
        ):
            raise AuthorityValidationError("invalid source relation")
        if self.relation == "possible-replay" and (
            self.envelope.message_id is None or self.related_causal_id is None
        ):
            raise AuthorityValidationError("invalid source relation")
        if self.relation == "replay-unknown" and (
            self.envelope.message_id is not None or self.related_causal_id is not None
        ):
            raise AuthorityValidationError("invalid source relation")
        if self.managed_cursor_state not in {"held", "superseded", "committed"}:
            raise AuthorityValidationError("invalid source cursor state")
        if self.native_cursor_state not in {
            "not-ready",
            "ready",
            "executing",
            "advanced",
            "unknown",
        }:
            raise AuthorityValidationError("invalid source cursor state")
        if (
            self.managed_cursor_state in {"held", "superseded"}
            and self.native_cursor_state != "not-ready"
        ):
            raise AuthorityValidationError("invalid source cursor state")
        if self.managed_cursor_state == "committed" and self.native_cursor_state == "not-ready":
            raise AuthorityValidationError("invalid source cursor state")
        if (
            self.managed_cursor_state in {"held", "superseded"}
            and self.envelope.body is None
        ):
            raise AuthorityValidationError("held source body is missing")
        if self.managed_cursor_state == "committed" and self.envelope.body is not None:
            raise AuthorityValidationError("committed source body was not released")

    def to_storage(self) -> dict[str, object]:
        return {
            "envelope": self.envelope.to_storage(),
            "relation": self.relation,
            "related_causal_id": self.related_causal_id,
            "managed_cursor_state": self.managed_cursor_state,
            "native_cursor_state": self.native_cursor_state,
        }

    @classmethod
    def from_storage(cls, value: object) -> "SourceReceipt":
        fields = {
            "envelope",
            "relation",
            "related_causal_id",
            "managed_cursor_state",
            "native_cursor_state",
        }
        if type(value) is not dict or set(value) != fields:
            raise AuthorityValidationError("invalid source receipt")
        return cls(
            envelope=SourceEnvelope.from_storage(value["envelope"]),
            relation=value["relation"],
            related_causal_id=value["related_causal_id"],
            managed_cursor_state=value["managed_cursor_state"],
            native_cursor_state=value["native_cursor_state"],
        )

    def with_business_committed(self) -> "SourceReceipt":
        return SourceReceipt(
            envelope=self.envelope.without_body(),
            relation=self.relation,
            related_causal_id=self.related_causal_id,
            managed_cursor_state="committed",
            native_cursor_state="ready",
        )

    def with_resolution_superseded(self) -> "SourceReceipt":
        if self.managed_cursor_state != "held":
            raise AuthorityValidationError("initialization source is not active")
        return SourceReceipt(
            envelope=self.envelope,
            relation=self.relation,
            related_causal_id=self.related_causal_id,
            managed_cursor_state="superseded",
            native_cursor_state="not-ready",
        )

    def with_native_cursor_state(self, state: str) -> "SourceReceipt":
        return SourceReceipt(
            envelope=self.envelope,
            relation=self.relation,
            related_causal_id=self.related_causal_id,
            managed_cursor_state="committed",
            native_cursor_state=state,
        )


@dataclass(frozen=True)
class NativeCursorDirective:
    """Permission for the native adapter to advance one exact source cursor."""

    source_causal_id: str
    native_cursor: str
    initialization_transition_id: str

    def __post_init__(self) -> None:
        validate_opaque_text(self.source_causal_id, "source causal identifier")
        validate_opaque_text(self.native_cursor, "native cursor")
        validate_opaque_text(
            self.initialization_transition_id,
            "initialization transition identifier",
        )


def materialize_source(message: RawWeixinMessage) -> SourceEnvelope:
    # Validate every transport header before dereferencing a potentially
    # sensitive lazy body.  A malformed delivery must not leak even one body
    # read into logging, deduplication, or error handling.
    validate_opaque_text(message.causal_id, "causal_id")
    if type(message.generation) is not int or message.generation < 1:
        raise AuthorityValidationError("invalid generation")
    for value, name in (
        (message.channel, "channel"),
        (message.partner_id, "partner_id"),
        (message.sender_id, "sender_id"),
        (message.conversation_id, "conversation_id"),
        (message.chat_type, "chat_type"),
        (message.entrypoint, "entrypoint"),
        (message.requested_capability, "requested_capability"),
    ):
        validate_opaque_text(value, name)
    _optional_opaque_text(message.message_id, "message_id")
    if message.protocol_timestamp is not None:
        _timestamp(message.protocol_timestamp, "protocol_timestamp")
    _timestamp(message.received_at, "received_at")
    validate_opaque_text(message.native_cursor, "native_cursor")
    if type(message.body) is str:
        body = message.body
    else:
        reader = getattr(message.body, "read", None)
        if not callable(reader):
            raise AuthorityValidationError("invalid message body source")
        try:
            body = reader()
        except Exception as exc:
            raise AuthorityValidationError("message body unavailable") from exc
    return SourceEnvelope(
        causal_id=message.causal_id,
        generation=message.generation,
        channel=message.channel,
        partner_id=message.partner_id,
        sender_id=message.sender_id,
        conversation_id=message.conversation_id,
        chat_type=message.chat_type,
        entrypoint=message.entrypoint,
        requested_capability=message.requested_capability,
        message_id=message.message_id,
        protocol_timestamp=message.protocol_timestamp,
        received_at=message.received_at,
        native_cursor=message.native_cursor,
        body=body,
    )

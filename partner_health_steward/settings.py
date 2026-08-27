"""Strict owner-settings value contracts for Ticket 114.

This module deliberately contains value objects only.  Authoritative state
transitions, persistence, and command orchestration belong to the later
Ticket 114 implementation slices.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import (
    date,
    datetime,
    timedelta,
    timezone as datetime_timezone,
    tzinfo as datetime_tzinfo,
)
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .tasks import TaskOwnerMutation


class SettingsContractViolation(ValueError):
    """A value cannot cross the owner-settings contract seam."""


ORDINARY_NOTIFICATION_KINDS = (
    "new_task",
    "ordinary_stage_change",
    "care_reminder",
    "task_terminal",
    "review_summary",
)
NOTIFICATION_STATES = (
    "not-configured",
    "enabled",
    "disabled",
)


_CONTROL_NAMES = frozenset(
    {
        "proactive_support",
        "recording",
        "task",
        "execution_scope_approval",
        "support_contact",
    }
)
_AUTHORITY_STATUSES = frozenset({"approved", "revoked", "invalidated"})


def _mapping(
    value: object,
    fields: frozenset[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != fields:
        raise SettingsContractViolation(f"invalid {name}")
    return value


def _text(value: object, name: str, *, wildcard: bool = False) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value.encode("utf-8")) > 65_536
        or (not wildcard and "*" in value)
    ):
        raise SettingsContractViolation(f"invalid {name}")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise SettingsContractViolation(f"invalid {name}")
    return value


def _nonnegative_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise SettingsContractViolation(f"invalid {name}")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise SettingsContractViolation(f"invalid {name}")
    return value


def _utc_time(value: object, name: str) -> str:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SettingsContractViolation(f"invalid {name}") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset() != timedelta(0)
    ):
        raise SettingsContractViolation(f"invalid {name}")
    return text


def _local_date(value: object, name: str) -> str:
    text = _text(value, name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise SettingsContractViolation(f"invalid {name}") from exc
    if parsed.isoformat() != text:
        raise SettingsContractViolation(f"invalid {name}")
    return text


def _sha256(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise SettingsContractViolation(f"invalid {name}")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise SettingsContractViolation(f"invalid {name}") from exc
    return text


def _optional_sha256(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, name)


def _wire_texts(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise SettingsContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise SettingsContractViolation(f"invalid {name}")
    return result


def _tuple_texts(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise SettingsContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise SettingsContractViolation(f"invalid {name}")
    return result


def _wire_texts_allow_empty(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise SettingsContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise SettingsContractViolation(f"invalid {name}")
    return result


def _tuple_texts_allow_empty(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise SettingsContractViolation(f"invalid {name}")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise SettingsContractViolation(f"invalid {name}")
    return result


def _setting_scalar(value: object, name: str) -> object:
    if value is None or type(value) in {str, bool, int}:
        return value
    raise SettingsContractViolation(f"invalid {name}")


def _field_name(value: object) -> str:
    text = _text(value, "settings field")
    if text in {"all", "settings"}:
        raise SettingsContractViolation("invalid settings field")
    return text


def _iana_timezone(value: object, name: str) -> str:
    text = _text(value, name)
    if text.startswith(("+", "-")) or ("/" not in text and text != "UTC"):
        raise SettingsContractViolation(f"invalid {name}")
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError:
        try:
            from dateutil.tz import gettz  # type: ignore[import-not-found]
        except ImportError as exc:
            if text not in {"Asia/Shanghai", "Etc/UTC", "UTC"}:
                raise SettingsContractViolation(f"invalid {name}") from exc
        else:
            if gettz(text) is None:
                raise SettingsContractViolation(f"invalid {name}")
    return text


def _read_only(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _read_only(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_read_only(item) for item in value)
    return value


@dataclass(frozen=True)
class FieldUpdate:
    field_name: str
    old_value: object
    new_value: object
    generation: int
    effective_at_utc: str

    def __post_init__(self) -> None:
        _field_name(self.field_name)
        _setting_scalar(self.old_value, "old settings value")
        _setting_scalar(self.new_value, "new settings value")
        _positive_integer(self.generation, "settings generation")
        _utc_time(self.effective_at_utc, "settings effective time")

    def to_wire(self) -> dict[str, object]:
        return {
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "generation": self.generation,
            "effective_at_utc": self.effective_at_utc,
        }

    @classmethod
    def from_wire(cls, value: object) -> "FieldUpdate":
        fields = _mapping(
            value,
            frozenset(
                {
                    "field_name",
                    "old_value",
                    "new_value",
                    "generation",
                    "effective_at_utc",
                }
            ),
            "field update",
        )
        return cls(
            field_name=_field_name(fields["field_name"]),
            old_value=_setting_scalar(fields["old_value"], "old settings value"),
            new_value=_setting_scalar(fields["new_value"], "new settings value"),
            generation=_positive_integer(fields["generation"], "settings generation"),
            effective_at_utc=_utc_time(
                fields["effective_at_utc"], "settings effective time"
            ),
        )


@dataclass(frozen=True)
class NotificationUpdate:
    kind: str
    old_state: str
    new_state: str
    generation: int
    effective_at_utc: str

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in ORDINARY_NOTIFICATION_KINDS:
            raise SettingsContractViolation("invalid ordinary notification kind")
        if type(self.old_state) is not str or self.old_state not in NOTIFICATION_STATES:
            raise SettingsContractViolation("invalid old notification state")
        if type(self.new_state) is not str or self.new_state not in {
            "enabled",
            "disabled",
        }:
            raise SettingsContractViolation("invalid new notification state")
        _positive_integer(self.generation, "notification generation")
        _utc_time(self.effective_at_utc, "notification effective time")

    def to_wire(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "old_state": self.old_state,
            "new_state": self.new_state,
            "generation": self.generation,
            "effective_at_utc": self.effective_at_utc,
        }

    @classmethod
    def from_wire(cls, value: object) -> "NotificationUpdate":
        fields = _mapping(
            value,
            frozenset(
                {
                    "kind",
                    "old_state",
                    "new_state",
                    "generation",
                    "effective_at_utc",
                }
            ),
            "notification update",
        )
        kind = fields["kind"]
        if type(kind) is not str or kind not in ORDINARY_NOTIFICATION_KINDS:
            raise SettingsContractViolation("invalid ordinary notification kind")
        return cls(
            kind=kind,
            old_state=fields["old_state"],  # type: ignore[arg-type]
            new_state=fields["new_state"],  # type: ignore[arg-type]
            generation=_positive_integer(fields["generation"], "notification generation"),
            effective_at_utc=_utc_time(
                fields["effective_at_utc"], "notification effective time"
            ),
        )


@dataclass(frozen=True)
class ControlUpdate:
    control_name: str
    operation: str
    target_ref: str | None
    generation: int
    effective_at_utc: str

    def __post_init__(self) -> None:
        if type(self.control_name) is not str or self.control_name not in _CONTROL_NAMES:
            raise SettingsContractViolation("invalid explicit control name")
        _text(self.operation, "control operation")
        _optional_text(self.target_ref, "control target reference")
        _positive_integer(self.generation, "control generation")
        _utc_time(self.effective_at_utc, "control effective time")

    def to_wire(self) -> dict[str, object]:
        return {
            "control_name": self.control_name,
            "operation": self.operation,
            "target_ref": self.target_ref,
            "generation": self.generation,
            "effective_at_utc": self.effective_at_utc,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ControlUpdate":
        fields = _mapping(
            value,
            frozenset(
                {
                    "control_name",
                    "operation",
                    "target_ref",
                    "generation",
                    "effective_at_utc",
                }
            ),
            "control update",
        )
        control_name = fields["control_name"]
        if type(control_name) is not str or control_name not in _CONTROL_NAMES:
            raise SettingsContractViolation("invalid explicit control name")
        return cls(
            control_name=control_name,
            operation=_text(fields["operation"], "control operation"),
            target_ref=_optional_text(fields["target_ref"], "control target reference"),
            generation=_positive_integer(fields["generation"], "control generation"),
            effective_at_utc=_utc_time(
                fields["effective_at_utc"], "control effective time"
            ),
        )


@dataclass(frozen=True)
class OwnerCommandContext:
    command_id: str
    causal_id: str
    actor_kind: str
    owner_id: str
    installation_id: str
    permission: str
    context_ref: str
    generation: int
    writer_fence: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.command_id, "owner command identifier"),
            (self.causal_id, "owner command causal identifier"),
            (self.owner_id, "owner identifier"),
            (self.installation_id, "installation identifier"),
            (self.permission, "owner command permission"),
            (self.context_ref, "owner command context reference"),
            (self.writer_fence, "owner command writer fence"),
        ):
            _text(value, name)
        if type(self.actor_kind) is not str or self.actor_kind != "current_owner":
            raise SettingsContractViolation("owner command must be authored by current owner")
        _positive_integer(self.generation, "owner command generation")

    def to_wire(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "causal_id": self.causal_id,
            "actor_kind": self.actor_kind,
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "permission": self.permission,
            "context_ref": self.context_ref,
            "generation": self.generation,
            "writer_fence": self.writer_fence,
        }

    @classmethod
    def from_wire(cls, value: object) -> "OwnerCommandContext":
        fields = _mapping(
            value,
            frozenset(
                {
                    "command_id",
                    "causal_id",
                    "actor_kind",
                    "owner_id",
                    "installation_id",
                    "permission",
                    "context_ref",
                    "generation",
                    "writer_fence",
                }
            ),
            "owner command context",
        )
        return cls(
            command_id=_text(fields["command_id"], "owner command identifier"),
            causal_id=_text(fields["causal_id"], "owner command causal identifier"),
            actor_kind=_text(fields["actor_kind"], "owner command actor"),
            owner_id=_text(fields["owner_id"], "owner identifier"),
            installation_id=_text(fields["installation_id"], "installation identifier"),
            permission=_text(fields["permission"], "owner command permission"),
            context_ref=_text(
                fields["context_ref"], "owner command context reference"
            ),
            generation=_positive_integer(
                fields["generation"], "owner command generation"
            ),
            writer_fence=_text(fields["writer_fence"], "owner command writer fence"),
        )


@dataclass(frozen=True)
class ExecutionScopeApproval:
    approval_id: str
    approval_version: int
    owner_id: str
    installation_id: str
    task_id: str
    effect_request_id: str
    assignee: str
    purpose: str
    allowed_data_categories: tuple[str, ...]
    allowed_data_refs: tuple[str, ...]
    first_hop_recipient: str
    external_effect_kind: str
    max_attempts: int
    min_contact_interval_seconds: int
    expires_at_utc: str
    route_id: str
    configuration_generation: int
    disclosure_version: str
    revoked: bool
    revoked_at_utc: str | None

    def __post_init__(self) -> None:
        for value, name in (
            (self.approval_id, "approval identifier"),
            (self.owner_id, "approval owner"),
            (self.installation_id, "approval installation"),
            (self.task_id, "approval task"),
            (self.effect_request_id, "approval effect request"),
            (self.assignee, "approval assignee"),
            (self.purpose, "approval purpose"),
            (self.first_hop_recipient, "approval first-hop recipient"),
            (self.external_effect_kind, "approval external effect kind"),
            (self.route_id, "approval route"),
            (self.disclosure_version, "approval disclosure version"),
        ):
            _text(value, name)
        _positive_integer(self.approval_version, "approval version")
        _tuple_texts(self.allowed_data_categories, "allowed data categories")
        _tuple_texts(self.allowed_data_refs, "allowed data references")
        _positive_integer(self.max_attempts, "maximum attempts")
        _nonnegative_integer(
            self.min_contact_interval_seconds, "minimum contact interval"
        )
        _utc_time(self.expires_at_utc, "approval expiry")
        _positive_integer(
            self.configuration_generation, "approval configuration generation"
        )
        _boolean(self.revoked, "approval revoked status")
        if self.revoked:
            if self.revoked_at_utc is None:
                raise SettingsContractViolation("revoked approval requires revocation time")
            _utc_time(self.revoked_at_utc, "approval revocation time")
        elif self.revoked_at_utc is not None:
            raise SettingsContractViolation(
                "current approval cannot carry a revocation time"
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "approval_id": self.approval_id,
            "approval_version": self.approval_version,
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "task_id": self.task_id,
            "effect_request_id": self.effect_request_id,
            "assignee": self.assignee,
            "purpose": self.purpose,
            "allowed_data_categories": list(self.allowed_data_categories),
            "allowed_data_refs": list(self.allowed_data_refs),
            "first_hop_recipient": self.first_hop_recipient,
            "external_effect_kind": self.external_effect_kind,
            "max_attempts": self.max_attempts,
            "min_contact_interval_seconds": self.min_contact_interval_seconds,
            "expires_at_utc": self.expires_at_utc,
            "route_id": self.route_id,
            "configuration_generation": self.configuration_generation,
            "disclosure_version": self.disclosure_version,
            "revoked": self.revoked,
            "revoked_at_utc": self.revoked_at_utc,
        }

    def consumer_view(self) -> Mapping[str, object]:
        """Return a deeply read-only value for validate/consume-only clients."""

        value = _read_only(self.to_wire())
        if not isinstance(value, Mapping):  # pragma: no cover - helper invariant
            raise SettingsContractViolation("invalid approval consumer view")
        return value

    @classmethod
    def from_wire(cls, value: object) -> "ExecutionScopeApproval":
        fields = _mapping(
            value,
            frozenset(
                {
                    "approval_id",
                    "approval_version",
                    "owner_id",
                    "installation_id",
                    "task_id",
                    "effect_request_id",
                    "assignee",
                    "purpose",
                    "allowed_data_categories",
                    "allowed_data_refs",
                    "first_hop_recipient",
                    "external_effect_kind",
                    "max_attempts",
                    "min_contact_interval_seconds",
                    "expires_at_utc",
                    "route_id",
                    "configuration_generation",
                    "disclosure_version",
                    "revoked",
                    "revoked_at_utc",
                }
            ),
            "execution-scope approval",
        )
        revoked = _boolean(fields["revoked"], "approval revoked status")
        revoked_at = fields["revoked_at_utc"]
        if revoked:
            if revoked_at is None:
                raise SettingsContractViolation("revoked approval requires revocation time")
            parsed_revoked_at = _utc_time(revoked_at, "approval revocation time")
        else:
            if revoked_at is not None:
                raise SettingsContractViolation(
                    "current approval cannot carry a revocation time"
                )
            parsed_revoked_at = None
        return cls(
            approval_id=_text(fields["approval_id"], "approval identifier"),
            approval_version=_positive_integer(
                fields["approval_version"], "approval version"
            ),
            owner_id=_text(fields["owner_id"], "approval owner"),
            installation_id=_text(
                fields["installation_id"], "approval installation"
            ),
            task_id=_text(fields["task_id"], "approval task"),
            effect_request_id=_text(
                fields["effect_request_id"], "approval effect request"
            ),
            assignee=_text(fields["assignee"], "approval assignee"),
            purpose=_text(fields["purpose"], "approval purpose"),
            allowed_data_categories=_wire_texts(
                fields["allowed_data_categories"], "allowed data categories"
            ),
            allowed_data_refs=_wire_texts(
                fields["allowed_data_refs"], "allowed data references"
            ),
            first_hop_recipient=_text(
                fields["first_hop_recipient"], "approval first-hop recipient"
            ),
            external_effect_kind=_text(
                fields["external_effect_kind"], "approval external effect kind"
            ),
            max_attempts=_positive_integer(
                fields["max_attempts"], "maximum attempts"
            ),
            min_contact_interval_seconds=_nonnegative_integer(
                fields["min_contact_interval_seconds"], "minimum contact interval"
            ),
            expires_at_utc=_utc_time(fields["expires_at_utc"], "approval expiry"),
            route_id=_text(fields["route_id"], "approval route"),
            configuration_generation=_positive_integer(
                fields["configuration_generation"],
                "approval configuration generation",
            ),
            disclosure_version=_text(
                fields["disclosure_version"], "approval disclosure version"
            ),
            revoked=revoked,
            revoked_at_utc=parsed_revoked_at,
        )


@dataclass(frozen=True)
class ExecutionScopeConsumptionRequest:
    """Typed, non-persistent facts for one proposed approval consumption."""

    approval_id: str
    approval_version: int
    owner_id: str
    installation_id: str
    task_id: str
    effect_request_id: str
    assignee: str
    purpose: str
    data_categories: tuple[str, ...]
    data_refs: tuple[str, ...]
    first_hop_recipient: str
    external_effect_kind: str
    attempts_used: int
    last_contact_at_utc: str | None
    evaluated_at_utc: str
    route_id: str
    configuration_generation: int
    disclosure_version: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.approval_id, "consumption approval identifier"),
            (self.owner_id, "consumption owner"),
            (self.installation_id, "consumption installation"),
            (self.task_id, "consumption task"),
            (self.effect_request_id, "consumption effect request"),
            (self.assignee, "consumption assignee"),
            (self.purpose, "consumption purpose"),
            (self.first_hop_recipient, "consumption first-hop recipient"),
            (self.external_effect_kind, "consumption external effect kind"),
            (self.route_id, "consumption route"),
            (self.disclosure_version, "consumption disclosure version"),
        ):
            _text(value, name)
        _positive_integer(self.approval_version, "consumption approval version")
        _tuple_texts(self.data_categories, "consumption data categories")
        _tuple_texts(self.data_refs, "consumption data references")
        _nonnegative_integer(self.attempts_used, "consumption attempts used")
        evaluated_at = _utc_time(
            self.evaluated_at_utc, "consumption evaluation time"
        )
        if self.last_contact_at_utc is not None:
            last_contact_at = _utc_time(
                self.last_contact_at_utc, "last contact time"
            )
            if datetime.fromisoformat(last_contact_at) > datetime.fromisoformat(
                evaluated_at
            ):
                raise SettingsContractViolation(
                    "last contact time cannot follow consumption evaluation"
                )
        _positive_integer(
            self.configuration_generation,
            "consumption configuration generation",
        )


@dataclass(frozen=True)
class ExecutionScopeConsumptionDecision:
    approval_id: str
    approval_version: int
    allowed: bool
    reason: str

    def __post_init__(self) -> None:
        _text(self.approval_id, "consumption decision approval identifier")
        _positive_integer(
            self.approval_version, "consumption decision approval version"
        )
        _boolean(self.allowed, "consumption decision")
        _text(self.reason, "consumption decision reason")


@dataclass(frozen=True)
class OwnerControlCommand:
    context: OwnerCommandContext
    control_update: ControlUpdate
    execution_scope_approval: ExecutionScopeApproval | None
    task_mutation: TaskOwnerMutation | None = None

    def __post_init__(self) -> None:
        if type(self.context) is not OwnerCommandContext:
            raise SettingsContractViolation("invalid owner command context")
        if type(self.control_update) is not ControlUpdate:
            raise SettingsContractViolation("invalid control update")
        if (
            self.execution_scope_approval is not None
            and type(self.execution_scope_approval) is not ExecutionScopeApproval
        ):
            raise SettingsContractViolation("invalid execution-scope approval")
        if (
            self.task_mutation is not None
            and type(self.task_mutation) is not TaskOwnerMutation
        ):
            raise SettingsContractViolation("invalid owner task mutation")
        if self.context.permission != "health_settings.write":
            raise SettingsContractViolation("invalid owner settings permission")
        if self.context.generation != self.control_update.generation:
            raise SettingsContractViolation("control command generation mismatch")

        approval = self.execution_scope_approval
        update = self.control_update
        mutation = self.task_mutation
        if mutation is not None:
            if (
                update.control_name != "task"
                or update.operation != mutation.operation
                or update.target_ref != mutation.task_id
                or self.execution_scope_approval is not None
            ):
                raise SettingsContractViolation("owner task mutation target mismatch")
        elif update.control_name == "task" and update.operation in {
            "defer",
            "adjust",
        }:
            raise SettingsContractViolation(
                "task defer or adjust requires owner task mutation"
            )
        if approval is not None:
            if update.control_name != "execution_scope_approval":
                raise SettingsContractViolation(
                    "execution approval cannot accompany another control"
                )
            if update.target_ref != approval.approval_id:
                raise SettingsContractViolation("execution approval target mismatch")
            if (
                approval.owner_id != self.context.owner_id
                or approval.installation_id != self.context.installation_id
            ):
                raise SettingsContractViolation("execution approval authority mismatch")
        elif (
            update.control_name == "execution_scope_approval"
            and update.operation in {"grant", "revise"}
        ):
            raise SettingsContractViolation("approval mutation requires exact approval")

        if (
            update.control_name == "execution_scope_approval"
            and update.target_ref is None
        ):
            raise SettingsContractViolation("approval control requires target reference")

    def to_wire(self) -> dict[str, object]:
        wire = {
            "context": self.context.to_wire(),
            "control_update": self.control_update.to_wire(),
            "execution_scope_approval": (
                None
                if self.execution_scope_approval is None
                else self.execution_scope_approval.to_wire()
            ),
        }
        if self.task_mutation is not None:
            wire["task_mutation"] = self.task_mutation.to_storage()
        return wire

    @classmethod
    def from_wire(cls, value: object) -> "OwnerControlCommand":
        old_fields = frozenset(
            {"context", "control_update", "execution_scope_approval"}
        )
        new_fields = old_fields | {"task_mutation"}
        if type(value) is not dict or frozenset(value) not in {old_fields, new_fields}:
            raise SettingsContractViolation("invalid owner control command")
        fields = value
        approval_wire = fields["execution_scope_approval"]
        if approval_wire is None:
            approval = None
        else:
            approval = ExecutionScopeApproval.from_wire(approval_wire)
        raw_mutation = fields.get("task_mutation")
        return cls(
            context=OwnerCommandContext.from_wire(fields["context"]),
            control_update=ControlUpdate.from_wire(fields["control_update"]),
            execution_scope_approval=approval,
            task_mutation=(
                None
                if raw_mutation is None
                else TaskOwnerMutation.from_storage(raw_mutation)
            ),
        )


@dataclass(frozen=True)
class TimezoneTransition:
    transition_id: str
    owner_id: str
    installation_id: str
    settings_version: int
    previous_timezone: str
    new_timezone: str
    requested_at_utc: str
    first_review_local_date: str
    effective_at_utc: str

    def __post_init__(self) -> None:
        _text(self.transition_id, "timezone transition identifier")
        _text(self.owner_id, "timezone transition owner")
        _text(self.installation_id, "timezone transition installation")
        _positive_integer(
            self.settings_version,
            "timezone transition settings version",
        )
        _iana_timezone(self.previous_timezone, "previous timezone")
        _iana_timezone(self.new_timezone, "new timezone")
        requested = _utc_time(self.requested_at_utc, "timezone request time")
        _local_date(self.first_review_local_date, "first review local date")
        effective = _utc_time(self.effective_at_utc, "timezone effective time")
        if datetime.fromisoformat(effective) <= datetime.fromisoformat(requested):
            raise SettingsContractViolation(
                "timezone transition must become effective after its request"
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "transition_id": self.transition_id,
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "settings_version": self.settings_version,
            "previous_timezone": self.previous_timezone,
            "new_timezone": self.new_timezone,
            "requested_at_utc": self.requested_at_utc,
            "first_review_local_date": self.first_review_local_date,
            "effective_at_utc": self.effective_at_utc,
        }

    @classmethod
    def from_wire(cls, value: object) -> "TimezoneTransition":
        fields = _mapping(
            value,
            frozenset(
                {
                    "transition_id",
                    "owner_id",
                    "installation_id",
                    "settings_version",
                    "previous_timezone",
                    "new_timezone",
                    "requested_at_utc",
                    "first_review_local_date",
                    "effective_at_utc",
                }
            ),
            "timezone transition",
        )
        return cls(
            transition_id=_text(
                fields["transition_id"], "timezone transition identifier"
            ),
            owner_id=_text(fields["owner_id"], "timezone transition owner"),
            installation_id=_text(
                fields["installation_id"], "timezone transition installation"
            ),
            settings_version=_positive_integer(
                fields["settings_version"],
                "timezone transition settings version",
            ),
            previous_timezone=_iana_timezone(
                fields["previous_timezone"], "previous timezone"
            ),
            new_timezone=_iana_timezone(fields["new_timezone"], "new timezone"),
            requested_at_utc=_utc_time(
                fields["requested_at_utc"], "timezone request time"
            ),
            first_review_local_date=_local_date(
                fields["first_review_local_date"], "first review local date"
            ),
            effective_at_utc=_utc_time(
                fields["effective_at_utc"], "timezone effective time"
            ),
        )


@dataclass(frozen=True)
class ConsentRenewal:
    renewal_id: str
    context: OwnerCommandContext
    route_id: str
    first_hop_recipient: str
    configuration_generation: int
    disclosure_version: str
    disclosure_digest: str
    consented_at_utc: str

    def __post_init__(self) -> None:
        _text(self.renewal_id, "consent renewal identifier")
        if type(self.context) is not OwnerCommandContext:
            raise SettingsContractViolation("invalid consent renewal context")
        if self.context.permission != "health_settings.write":
            raise SettingsContractViolation("invalid consent renewal permission")
        _text(self.route_id, "consent route")
        _text(self.first_hop_recipient, "consent first-hop recipient")
        _positive_integer(
            self.configuration_generation, "consent configuration generation"
        )
        _text(self.disclosure_version, "consent disclosure version")
        _sha256(self.disclosure_digest, "consent disclosure digest")
        _utc_time(self.consented_at_utc, "consent time")

    def to_wire(self) -> dict[str, object]:
        return {
            "renewal_id": self.renewal_id,
            "context": self.context.to_wire(),
            "route_id": self.route_id,
            "first_hop_recipient": self.first_hop_recipient,
            "configuration_generation": self.configuration_generation,
            "disclosure_version": self.disclosure_version,
            "disclosure_digest": self.disclosure_digest,
            "consented_at_utc": self.consented_at_utc,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ConsentRenewal":
        fields = _mapping(
            value,
            frozenset(
                {
                    "renewal_id",
                    "context",
                    "route_id",
                    "first_hop_recipient",
                    "configuration_generation",
                    "disclosure_version",
                    "disclosure_digest",
                    "consented_at_utc",
                }
            ),
            "consent renewal",
        )
        return cls(
            renewal_id=_text(fields["renewal_id"], "consent renewal identifier"),
            context=OwnerCommandContext.from_wire(fields["context"]),
            route_id=_text(fields["route_id"], "consent route"),
            first_hop_recipient=_text(
                fields["first_hop_recipient"], "consent first-hop recipient"
            ),
            configuration_generation=_positive_integer(
                fields["configuration_generation"],
                "consent configuration generation",
            ),
            disclosure_version=_text(
                fields["disclosure_version"], "consent disclosure version"
            ),
            disclosure_digest=_sha256(
                fields["disclosure_digest"], "consent disclosure digest"
            ),
            consented_at_utc=_utc_time(fields["consented_at_utc"], "consent time"),
        )


def _contact_binding(
    *,
    contact_id: str,
    owner_id: str,
    installation_id: str,
    method_kind: str,
    method_value: str,
    purpose: str,
    minimum_alert_fields: tuple[str, ...],
    route_id: str,
    route_generation: int,
    disclosure_version: str,
) -> str:
    bound = {
        "contact_id": contact_id,
        "owner_id": owner_id,
        "installation_id": installation_id,
        "method_kind": method_kind,
        "method_value": method_value,
        "purpose": purpose,
        "minimum_alert_fields": list(minimum_alert_fields),
        "route_id": route_id,
        "route_generation": route_generation,
        "disclosure_version": disclosure_version,
    }
    canonical = json.dumps(
        bound,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class SupportContactSettings:
    contact_id: str
    version: int
    owner_id: str
    installation_id: str
    identity_label: str
    method_kind: str
    method_value: str
    purpose: str
    minimum_alert_fields: tuple[str, ...]
    route_id: str
    route_generation: int
    disclosure_version: str
    dedicated_paused: bool
    alert_authority_status: str
    alert_approval_id: str | None
    alert_authority_binding: str | None
    correction_authority_status: str
    correction_authority_id: str | None
    correction_authority_binding: str | None
    max_corrections_per_alert: int

    def __post_init__(self) -> None:
        for value, name in (
            (self.contact_id, "support contact identifier"),
            (self.owner_id, "support contact owner"),
            (self.installation_id, "support contact installation"),
            (self.identity_label, "support contact identity"),
            (self.method_kind, "support contact method kind"),
            (self.method_value, "support contact method value"),
            (self.purpose, "support contact purpose"),
            (self.route_id, "support contact route"),
            (self.disclosure_version, "support contact disclosure version"),
        ):
            _text(value, name)
        _positive_integer(self.version, "support contact version")
        _tuple_texts(self.minimum_alert_fields, "minimum alert fields")
        _positive_integer(self.route_generation, "support contact route generation")
        _boolean(self.dedicated_paused, "support contact pause status")
        if type(self.max_corrections_per_alert) is not int or self.max_corrections_per_alert != 1:
            raise SettingsContractViolation(
                "support contact permits exactly one correction per alert"
            )

        expected_binding = self.expected_authority_binding()
        self._validate_authority(
            "alert",
            self.alert_authority_status,
            self.alert_approval_id,
            self.alert_authority_binding,
            expected_binding,
        )
        self._validate_authority(
            "correction",
            self.correction_authority_status,
            self.correction_authority_id,
            self.correction_authority_binding,
            expected_binding,
        )

    @staticmethod
    def _validate_authority(
        name: str,
        status: object,
        authority_id: object,
        binding: object,
        expected_binding: str,
    ) -> None:
        if type(status) is not str or status not in _AUTHORITY_STATUSES:
            raise SettingsContractViolation(f"invalid {name} authority status")
        parsed_id = _optional_text(authority_id, f"{name} authority identifier")
        parsed_binding = _optional_sha256(binding, f"{name} authority binding")
        if status == "invalidated":
            if parsed_id is not None or parsed_binding is not None:
                raise SettingsContractViolation(
                    f"invalidated {name} authority must be cleared"
                )
            return
        if parsed_id is None or parsed_binding != expected_binding:
            raise SettingsContractViolation(f"invalid {name} authority binding")

    def expected_authority_binding(self) -> str:
        """Return the exact contact/method/route binding consumers must match."""

        return _contact_binding(
            contact_id=self.contact_id,
            owner_id=self.owner_id,
            installation_id=self.installation_id,
            method_kind=self.method_kind,
            method_value=self.method_value,
            purpose=self.purpose,
            minimum_alert_fields=self.minimum_alert_fields,
            route_id=self.route_id,
            route_generation=self.route_generation,
            disclosure_version=self.disclosure_version,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "contact_id": self.contact_id,
            "version": self.version,
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "identity_label": self.identity_label,
            "method_kind": self.method_kind,
            "method_value": self.method_value,
            "purpose": self.purpose,
            "minimum_alert_fields": list(self.minimum_alert_fields),
            "route_id": self.route_id,
            "route_generation": self.route_generation,
            "disclosure_version": self.disclosure_version,
            "dedicated_paused": self.dedicated_paused,
            "alert_authority_status": self.alert_authority_status,
            "alert_approval_id": self.alert_approval_id,
            "alert_authority_binding": self.alert_authority_binding,
            "correction_authority_status": self.correction_authority_status,
            "correction_authority_id": self.correction_authority_id,
            "correction_authority_binding": self.correction_authority_binding,
            "max_corrections_per_alert": self.max_corrections_per_alert,
        }

    def consumer_view(self) -> Mapping[str, object]:
        """Return a deeply read-only contact value for Ticket 116 consumers."""

        value = _read_only(self.to_wire())
        if not isinstance(value, Mapping):  # pragma: no cover - helper invariant
            raise SettingsContractViolation("invalid support-contact consumer view")
        return value

    def invalidated_for_replacement(
        self,
        *,
        contact_id: str | None = None,
        method_kind: str | None = None,
        method_value: str | None = None,
        route_id: str | None = None,
        route_generation: int | None = None,
        disclosure_version: str | None = None,
        version: int | None = None,
    ) -> "SupportContactSettings":
        """Build a replacement boundary with both prior authorities cleared."""

        changes = {
            "contact_id": self.contact_id if contact_id is None else contact_id,
            "method_kind": self.method_kind if method_kind is None else method_kind,
            "method_value": self.method_value if method_value is None else method_value,
            "route_id": self.route_id if route_id is None else route_id,
            "route_generation": (
                self.route_generation if route_generation is None else route_generation
            ),
            "disclosure_version": (
                self.disclosure_version
                if disclosure_version is None
                else disclosure_version
            ),
        }
        if all(getattr(self, name) == value for name, value in changes.items()):
            raise SettingsContractViolation(
                "support-contact replacement must change its authority boundary"
            )
        return replace(
            self,
            **changes,
            version=self.version + 1 if version is None else version,
            alert_authority_status="invalidated",
            alert_approval_id=None,
            alert_authority_binding=None,
            correction_authority_status="invalidated",
            correction_authority_id=None,
            correction_authority_binding=None,
        )

    @classmethod
    def from_wire(cls, value: object) -> "SupportContactSettings":
        fields = _mapping(
            value,
            frozenset(
                {
                    "contact_id",
                    "version",
                    "owner_id",
                    "installation_id",
                    "identity_label",
                    "method_kind",
                    "method_value",
                    "purpose",
                    "minimum_alert_fields",
                    "route_id",
                    "route_generation",
                    "disclosure_version",
                    "dedicated_paused",
                    "alert_authority_status",
                    "alert_approval_id",
                    "alert_authority_binding",
                    "correction_authority_status",
                    "correction_authority_id",
                    "correction_authority_binding",
                    "max_corrections_per_alert",
                }
            ),
            "support-contact settings",
        )
        return cls(
            contact_id=_text(fields["contact_id"], "support contact identifier"),
            version=_positive_integer(fields["version"], "support contact version"),
            owner_id=_text(fields["owner_id"], "support contact owner"),
            installation_id=_text(
                fields["installation_id"], "support contact installation"
            ),
            identity_label=_text(
                fields["identity_label"], "support contact identity"
            ),
            method_kind=_text(fields["method_kind"], "support contact method kind"),
            method_value=_text(
                fields["method_value"], "support contact method value"
            ),
            purpose=_text(fields["purpose"], "support contact purpose"),
            minimum_alert_fields=_wire_texts(
                fields["minimum_alert_fields"], "minimum alert fields"
            ),
            route_id=_text(fields["route_id"], "support contact route"),
            route_generation=_positive_integer(
                fields["route_generation"], "support contact route generation"
            ),
            disclosure_version=_text(
                fields["disclosure_version"], "support contact disclosure version"
            ),
            dedicated_paused=_boolean(
                fields["dedicated_paused"], "support contact pause status"
            ),
            alert_authority_status=_text(
                fields["alert_authority_status"], "alert authority status"
            ),
            alert_approval_id=_optional_text(
                fields["alert_approval_id"], "alert authority identifier"
            ),
            alert_authority_binding=_optional_sha256(
                fields["alert_authority_binding"], "alert authority binding"
            ),
            correction_authority_status=_text(
                fields["correction_authority_status"],
                "correction authority status",
            ),
            correction_authority_id=_optional_text(
                fields["correction_authority_id"],
                "correction authority identifier",
            ),
            correction_authority_binding=_optional_sha256(
                fields["correction_authority_binding"],
                "correction authority binding",
            ),
            max_corrections_per_alert=_positive_integer(
                fields["max_corrections_per_alert"],
                "maximum corrections per alert",
            ),
        )


@dataclass(frozen=True)
class RouteConfigurationUpdate:
    """Current first-hop route facts that may invalidate prior consent."""

    route_id: str
    first_hop_recipient: str
    configuration_generation: int
    disclosure_version: str
    generation: int

    def __post_init__(self) -> None:
        _text(self.route_id, "current route identifier")
        _text(self.first_hop_recipient, "current first-hop recipient")
        _positive_integer(
            self.configuration_generation, "current configuration generation"
        )
        _text(self.disclosure_version, "current disclosure version")
        _positive_integer(self.generation, "route fact generation")

    def to_wire(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "first_hop_recipient": self.first_hop_recipient,
            "configuration_generation": self.configuration_generation,
            "disclosure_version": self.disclosure_version,
            "generation": self.generation,
        }

    @classmethod
    def from_wire(cls, value: object) -> "RouteConfigurationUpdate":
        fields = _mapping(
            value,
            frozenset(
                {
                    "route_id",
                    "first_hop_recipient",
                    "configuration_generation",
                    "disclosure_version",
                    "generation",
                }
            ),
            "route configuration update",
        )
        return cls(
            route_id=_text(fields["route_id"], "current route identifier"),
            first_hop_recipient=_text(
                fields["first_hop_recipient"], "current first-hop recipient"
            ),
            configuration_generation=_positive_integer(
                fields["configuration_generation"],
                "current configuration generation",
            ),
            disclosure_version=_text(
                fields["disclosure_version"], "current disclosure version"
            ),
            generation=_positive_integer(fields["generation"], "route fact generation"),
        )


@dataclass(frozen=True)
class CloseButRetainRequest:
    """Ambiguous owner wording that must be clarified, never guessed."""

    context: OwnerCommandContext

    def __post_init__(self) -> None:
        if type(self.context) is not OwnerCommandContext:
            raise SettingsContractViolation("invalid close-but-retain context")
        if self.context.permission != "health_settings.write":
            raise SettingsContractViolation("invalid close-but-retain permission")

    def to_wire(self) -> dict[str, object]:
        return {"context": self.context.to_wire()}

    @classmethod
    def from_wire(cls, value: object) -> "CloseButRetainRequest":
        fields = _mapping(
            value,
            frozenset({"context"}),
            "close-but-retain request",
        )
        return cls(context=OwnerCommandContext.from_wire(fields["context"]))


_SUPPORT_CONTACT_OPERATIONS = frozenset(
    {
        "configure",
        "replace",
        "change_method",
        "pause",
        "resume",
        "grant_alert_authority",
        "revoke_alert_authority",
        "grant_correction_authority",
        "revoke_correction_authority",
    }
)
_SUPPORT_CONTACT_REPLACEMENTS = frozenset({"replace", "change_method"})
_SUPPORT_CONTACT_AUTHORITY_OPERATIONS = frozenset(
    {
        "grant_alert_authority",
        "revoke_alert_authority",
        "grant_correction_authority",
        "revoke_correction_authority",
    }
)


@dataclass(frozen=True)
class SupportContactCommand:
    """One owner-authored mutation of the current support-contact boundary."""

    context: OwnerCommandContext
    operation: str
    contact: SupportContactSettings | None
    authority_id: str | None
    expected_contact_version: int | None
    expected_route_id: str | None
    expected_route_generation: int | None

    def __post_init__(self) -> None:
        if type(self.context) is not OwnerCommandContext:
            raise SettingsContractViolation("invalid support-contact command context")
        if self.context.permission != "health_settings.write":
            raise SettingsContractViolation("invalid support-contact permission")
        if type(self.operation) is not str or self.operation not in _SUPPORT_CONTACT_OPERATIONS:
            raise SettingsContractViolation("invalid support-contact operation")
        if self.operation == "configure":
            if any(
                value is not None
                for value in (
                    self.expected_contact_version,
                    self.expected_route_id,
                    self.expected_route_generation,
                )
            ):
                raise SettingsContractViolation(
                    "first support-contact configuration cannot name an old boundary"
                )
            if type(self.contact) is not SupportContactSettings:
                raise SettingsContractViolation(
                    "support-contact configuration requires the exact new contact"
                )
            if self.authority_id is not None:
                raise SettingsContractViolation(
                    "support-contact configuration cannot carry an authority identifier"
                )
        else:
            _positive_integer(self.expected_contact_version, "expected contact version")
            _text(self.expected_route_id, "expected support-contact route")
            _positive_integer(
                self.expected_route_generation,
                "expected support-contact route generation",
            )
        if self.operation in _SUPPORT_CONTACT_REPLACEMENTS:
            if type(self.contact) is not SupportContactSettings:
                raise SettingsContractViolation(
                    "support-contact replacement requires the exact new contact"
                )
            if self.authority_id is not None:
                raise SettingsContractViolation(
                    "support-contact replacement cannot carry an authority identifier"
                )
        elif self.operation != "configure":
            if self.contact is not None:
                raise SettingsContractViolation(
                    "support-contact control cannot carry a replacement contact"
                )
            if self.operation in _SUPPORT_CONTACT_AUTHORITY_OPERATIONS:
                if self.authority_id is None and self.operation not in {
                    "revoke_alert_authority",
                    "revoke_correction_authority",
                }:
                    raise SettingsContractViolation(
                        "support-contact authority identifier required"
                    )
                if self.authority_id is not None:
                    _text(self.authority_id, "support-contact authority identifier")
            elif self.authority_id is not None:
                raise SettingsContractViolation(
                    "support-contact pause control cannot carry authority"
                )

    def to_wire(self) -> dict[str, object]:
        return {
            "context": self.context.to_wire(),
            "operation": self.operation,
            "contact": None if self.contact is None else self.contact.to_wire(),
            "authority_id": self.authority_id,
            "expected_contact_version": self.expected_contact_version,
            "expected_route_id": self.expected_route_id,
            "expected_route_generation": self.expected_route_generation,
        }

    @classmethod
    def from_wire(cls, value: object) -> "SupportContactCommand":
        fields = _mapping(
            value,
            frozenset(
                {
                    "context",
                    "operation",
                    "contact",
                    "authority_id",
                    "expected_contact_version",
                    "expected_route_id",
                    "expected_route_generation",
                }
            ),
            "support-contact command",
        )
        contact_wire = fields["contact"]
        return cls(
            context=OwnerCommandContext.from_wire(fields["context"]),
            operation=_text(fields["operation"], "support-contact operation"),
            contact=(
                None
                if contact_wire is None
                else SupportContactSettings.from_wire(contact_wire)
            ),
            authority_id=_optional_text(
                fields["authority_id"], "support-contact authority identifier"
            ),
            expected_contact_version=(
                None
                if fields["expected_contact_version"] is None
                else _positive_integer(
                    fields["expected_contact_version"], "expected contact version"
                )
            ),
            expected_route_id=_optional_text(
                fields["expected_route_id"], "expected support-contact route"
            ),
            expected_route_generation=(
                None
                if fields["expected_route_generation"] is None
                else _positive_integer(
                    fields["expected_route_generation"],
                    "expected support-contact route generation",
                )
            ),
        )


@dataclass(frozen=True)
class OwnerSettingsState:
    """Immutable in-memory projection of the Ticket 114 owner authority."""

    owner_id: str
    installation_id: str
    version: int
    timezone: str
    contact_window: str
    expression_style: str
    proactive_contact: bool
    ordinary_notifications: tuple[tuple[str, str], ...]
    proactive_support_paused: bool
    recording_stopped: bool
    recording_stopped_at_utc: str | None
    cancelled_task_refs: tuple[str, ...]
    recording_exclusions: tuple[tuple[str, str], ...]
    timezone_transition: TimezoneTransition | None
    completed_review_keys: tuple[str, ...]
    consent_enabled: bool
    consent_data_scope: tuple[str, ...]
    consent_route_id: str
    consent_first_hop_recipient: str
    consent_configuration_generation: int
    consent_generation: int
    consent_disclosure_version: str
    consent_disclosure_digest: str
    consent_path_status: str
    consent_pause_reason: str | None
    current_route_id: str
    current_first_hop_recipient: str
    current_configuration_generation: int
    current_disclosure_version: str
    approvals: tuple[ExecutionScopeApproval, ...]
    support_contact: SupportContactSettings | None
    receipts: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        _text(self.owner_id, "settings owner")
        _text(self.installation_id, "settings installation")
        _positive_integer(self.version, "settings version")
        _iana_timezone(self.timezone, "settings timezone")
        _contact_window(self.contact_window)
        _text(self.expression_style, "expression style")
        _boolean(self.proactive_contact, "proactive-contact preference")
        if (
            type(self.ordinary_notifications) is not tuple
            or tuple(kind for kind, _ in self.ordinary_notifications)
            != ORDINARY_NOTIFICATION_KINDS
            or any(
                type(state) is not str or state not in NOTIFICATION_STATES
                for _, state in self.ordinary_notifications
            )
        ):
            raise SettingsContractViolation("invalid ordinary notification state")
        _boolean(self.proactive_support_paused, "proactive-support pause state")
        _boolean(self.recording_stopped, "recording stop state")
        if self.recording_stopped:
            if self.recording_stopped_at_utc is None:
                raise SettingsContractViolation("stopped recording requires stop time")
            _utc_time(self.recording_stopped_at_utc, "recording stop time")
        elif self.recording_stopped_at_utc is not None:
            raise SettingsContractViolation("active recording cannot retain stop time")
        _tuple_texts_allow_empty(self.cancelled_task_refs, "cancelled task references")
        if type(self.recording_exclusions) is not tuple:
            raise SettingsContractViolation("invalid recording exclusions")
        for exclusion in self.recording_exclusions:
            if type(exclusion) is not tuple or len(exclusion) != 2:
                raise SettingsContractViolation("invalid recording exclusion")
            stopped = _utc_time(exclusion[0], "recording exclusion stop time")
            resumed = _utc_time(exclusion[1], "recording exclusion resume time")
            if datetime.fromisoformat(resumed) <= datetime.fromisoformat(stopped):
                raise SettingsContractViolation("invalid recording exclusion interval")
        if self.timezone_transition is not None:
            if type(self.timezone_transition) is not TimezoneTransition:
                raise SettingsContractViolation("invalid pending timezone transition")
            if (
                self.timezone_transition.owner_id != self.owner_id
                or self.timezone_transition.installation_id != self.installation_id
                or self.timezone_transition.previous_timezone != self.timezone
            ):
                raise SettingsContractViolation("timezone transition authority mismatch")
        _tuple_texts_allow_empty(self.completed_review_keys, "completed review keys")
        _boolean(self.consent_enabled, "consent enablement")
        _tuple_texts(self.consent_data_scope, "consent data scope")
        for value, name in (
            (self.consent_route_id, "consented route"),
            (self.consent_first_hop_recipient, "consented first-hop recipient"),
            (self.consent_disclosure_version, "consented disclosure version"),
            (self.current_route_id, "current route"),
            (self.current_first_hop_recipient, "current first-hop recipient"),
            (self.current_disclosure_version, "current disclosure version"),
        ):
            _text(value, name)
        _positive_integer(
            self.consent_configuration_generation,
            "consented configuration generation",
        )
        _positive_integer(self.consent_generation, "consent generation")
        _sha256(self.consent_disclosure_digest, "consent disclosure digest")
        if self.consent_path_status not in {"active", "paused"}:
            raise SettingsContractViolation("invalid consent path state")
        if self.consent_path_status == "active":
            if self.consent_pause_reason is not None:
                raise SettingsContractViolation("active consent path cannot be paused")
        else:
            _text(self.consent_pause_reason, "consent pause reason")
        _positive_integer(
            self.current_configuration_generation,
            "current configuration generation",
        )
        if type(self.approvals) is not tuple:
            raise SettingsContractViolation("invalid execution approvals")
        approval_ids: list[str] = []
        for approval in self.approvals:
            if type(approval) is not ExecutionScopeApproval:
                raise SettingsContractViolation("invalid execution approval")
            if (
                approval.owner_id != self.owner_id
                or approval.installation_id != self.installation_id
            ):
                raise SettingsContractViolation("execution approval authority mismatch")
            approval_ids.append(approval.approval_id)
        if approval_ids != sorted(approval_ids) or len(approval_ids) != len(set(approval_ids)):
            raise SettingsContractViolation("execution approvals must be uniquely ordered")
        if self.support_contact is not None:
            if type(self.support_contact) is not SupportContactSettings:
                raise SettingsContractViolation("invalid current support contact")
            if (
                self.support_contact.owner_id != self.owner_id
                or self.support_contact.installation_id != self.installation_id
            ):
                raise SettingsContractViolation("support-contact authority mismatch")
        if type(self.receipts) is not tuple:
            raise SettingsContractViolation("invalid settings receipts")
        identities: set[str] = set()
        for receipt in self.receipts:
            if type(receipt) is not tuple or len(receipt) != 3:
                raise SettingsContractViolation("invalid settings receipt")
            identity = _text(receipt[0], "settings receipt identity", wildcard=True)
            _sha256(receipt[1], "settings receipt digest")
            result_json = _text(receipt[2], "settings receipt result", wildcard=True)
            try:
                parsed = json.loads(result_json)
            except (TypeError, ValueError) as exc:
                raise SettingsContractViolation("invalid settings receipt result") from exc
            if type(parsed) is not dict or _canonical_json(parsed) != result_json:
                raise SettingsContractViolation("noncanonical settings receipt result")
            if identity in identities:
                raise SettingsContractViolation("duplicate settings receipt identity")
            identities.add(identity)

    def excludes_health_recording(self, protocol_timestamp: str | None) -> bool:
        """Fail closed for an active stop or an unprovable historical backlog.

        Completed recording exclusions are half-open UTC intervals
        ``[stopped, resumed)``.  Once such an interval exists, a source with no
        native event time cannot prove that it was created after recording
        resumed, so it may be used only through the body-free temporary path.
        """

        if self.recording_stopped:
            return True
        if not self.recording_exclusions:
            return False
        if protocol_timestamp is None:
            return True
        try:
            event_time = datetime.fromisoformat(
                _text(protocol_timestamp, "source protocol timestamp")
            )
        except ValueError as exc:
            raise SettingsContractViolation(
                "invalid source protocol timestamp"
            ) from exc
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise SettingsContractViolation("invalid source protocol timestamp")
        event_time = event_time.astimezone(datetime_timezone.utc)
        return any(
            datetime.fromisoformat(stopped) <= event_time
            < datetime.fromisoformat(resumed)
            for stopped, resumed in self.recording_exclusions
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "version": self.version,
            "timezone": self.timezone,
            "preferences": {
                "contact_window": self.contact_window,
                "expression_style": self.expression_style,
                "proactive_contact": self.proactive_contact,
            },
            "ordinary_notifications": {
                kind: enabled for kind, enabled in self.ordinary_notifications
            },
            "controls": {
                "proactive_support_paused": self.proactive_support_paused,
                "recording_stopped": self.recording_stopped,
                "recording_stopped_at_utc": self.recording_stopped_at_utc,
                "cancelled_task_refs": list(self.cancelled_task_refs),
            },
            "recording_exclusions": [
                {
                    "stopped_at_utc": stopped,
                    "resumed_at_utc": resumed,
                    "backfill_allowed": False,
                }
                for stopped, resumed in self.recording_exclusions
            ],
            "timezone_transition": (
                None
                if self.timezone_transition is None
                else self.timezone_transition.to_wire()
            ),
            "completed_review_keys": list(self.completed_review_keys),
            "consent": {
                "enabled": self.consent_enabled,
                "data_scope": list(self.consent_data_scope),
                "route_id": self.consent_route_id,
                "first_hop_recipient": self.consent_first_hop_recipient,
                "configuration_generation": self.consent_configuration_generation,
                "consent_generation": self.consent_generation,
                "disclosure_version": self.consent_disclosure_version,
                "disclosure_digest": self.consent_disclosure_digest,
                "path_status": self.consent_path_status,
                "pause_reason": self.consent_pause_reason,
            },
            "current_route_configuration": {
                "route_id": self.current_route_id,
                "first_hop_recipient": self.current_first_hop_recipient,
                "configuration_generation": self.current_configuration_generation,
                "disclosure_version": self.current_disclosure_version,
            },
            "execution_scope_approvals": [
                approval.to_wire() for approval in self.approvals
            ],
            "support_contact": (
                None
                if self.support_contact is None
                else self.support_contact.to_wire()
            ),
            "receipts": [
                {"identity": identity, "digest": digest, "result_json": result_json}
                for identity, digest, result_json in self.receipts
            ],
        }

    @classmethod
    def from_wire(cls, value: object) -> "OwnerSettingsState":
        fields = _mapping(
            value,
            frozenset(
                {
                    "schema_version",
                    "owner_id",
                    "installation_id",
                    "version",
                    "timezone",
                    "preferences",
                    "ordinary_notifications",
                    "controls",
                    "recording_exclusions",
                    "timezone_transition",
                    "completed_review_keys",
                    "consent",
                    "current_route_configuration",
                    "execution_scope_approvals",
                    "support_contact",
                    "receipts",
                }
            ),
            "owner settings state",
        )
        if fields["schema_version"] != 2:
            raise SettingsContractViolation("unsupported owner settings schema")
        preferences = _mapping(
            fields["preferences"],
            frozenset({"contact_window", "expression_style", "proactive_contact"}),
            "owner preferences",
        )
        notifications = _mapping(
            fields["ordinary_notifications"],
            frozenset(ORDINARY_NOTIFICATION_KINDS),
            "ordinary notifications",
        )
        controls = _mapping(
            fields["controls"],
            frozenset(
                {
                    "proactive_support_paused",
                    "recording_stopped",
                    "recording_stopped_at_utc",
                    "cancelled_task_refs",
                }
            ),
            "owner controls",
        )
        exclusions_wire = fields["recording_exclusions"]
        if type(exclusions_wire) is not list:
            raise SettingsContractViolation("invalid recording exclusions")
        exclusions: list[tuple[str, str]] = []
        for item in exclusions_wire:
            exclusion = _mapping(
                item,
                frozenset(
                    {"stopped_at_utc", "resumed_at_utc", "backfill_allowed"}
                ),
                "recording exclusion",
            )
            if exclusion["backfill_allowed"] is not False:
                raise SettingsContractViolation("recording backfill is forbidden")
            exclusions.append(
                (
                    _utc_time(exclusion["stopped_at_utc"], "recording stop time"),
                    _utc_time(exclusion["resumed_at_utc"], "recording resume time"),
                )
            )
        consent = _mapping(
            fields["consent"],
            frozenset(
                {
                    "enabled",
                    "data_scope",
                    "route_id",
                    "first_hop_recipient",
                    "configuration_generation",
                    "consent_generation",
                    "disclosure_version",
                    "disclosure_digest",
                    "path_status",
                    "pause_reason",
                }
            ),
            "consent state",
        )
        route = _mapping(
            fields["current_route_configuration"],
            frozenset(
                {
                    "route_id",
                    "first_hop_recipient",
                    "configuration_generation",
                    "disclosure_version",
                }
            ),
            "current route configuration",
        )
        approvals_wire = fields["execution_scope_approvals"]
        if type(approvals_wire) is not list:
            raise SettingsContractViolation("invalid execution approvals")
        receipts_wire = fields["receipts"]
        if type(receipts_wire) is not list:
            raise SettingsContractViolation("invalid settings receipts")
        receipts: list[tuple[str, str, str]] = []
        for item in receipts_wire:
            receipt = _mapping(
                item,
                frozenset({"identity", "digest", "result_json"}),
                "settings receipt",
            )
            receipts.append(
                (
                    _text(receipt["identity"], "settings receipt identity", wildcard=True),
                    _sha256(receipt["digest"], "settings receipt digest"),
                    _text(receipt["result_json"], "settings receipt result", wildcard=True),
                )
            )
        transition_wire = fields["timezone_transition"]
        stopped_at = controls["recording_stopped_at_utc"]
        pause_reason = consent["pause_reason"]
        return cls(
            owner_id=_text(fields["owner_id"], "settings owner"),
            installation_id=_text(
                fields["installation_id"], "settings installation"
            ),
            version=_positive_integer(fields["version"], "settings version"),
            timezone=_iana_timezone(fields["timezone"], "settings timezone"),
            contact_window=_contact_window(preferences["contact_window"]),
            expression_style=_text(
                preferences["expression_style"], "expression style"
            ),
            proactive_contact=_boolean(
                preferences["proactive_contact"], "proactive-contact preference"
            ),
            ordinary_notifications=tuple(
                (
                    kind,
                    _notification_state(
                        notifications[kind], f"{kind} notification state"
                    ),
                )
                for kind in ORDINARY_NOTIFICATION_KINDS
            ),
            proactive_support_paused=_boolean(
                controls["proactive_support_paused"],
                "proactive-support pause state",
            ),
            recording_stopped=_boolean(
                controls["recording_stopped"], "recording stop state"
            ),
            recording_stopped_at_utc=(
                None
                if stopped_at is None
                else _utc_time(stopped_at, "recording stop time")
            ),
            cancelled_task_refs=_wire_texts_allow_empty(
                controls["cancelled_task_refs"], "cancelled task references"
            ),
            recording_exclusions=tuple(exclusions),
            timezone_transition=(
                None
                if transition_wire is None
                else TimezoneTransition.from_wire(transition_wire)
            ),
            completed_review_keys=_wire_texts_allow_empty(
                fields["completed_review_keys"], "completed review keys"
            ),
            consent_enabled=_boolean(consent["enabled"], "consent enablement"),
            consent_data_scope=_wire_texts(consent["data_scope"], "consent data scope"),
            consent_route_id=_text(consent["route_id"], "consented route"),
            consent_first_hop_recipient=_text(
                consent["first_hop_recipient"], "consented first-hop recipient"
            ),
            consent_configuration_generation=_positive_integer(
                consent["configuration_generation"],
                "consented configuration generation",
            ),
            consent_generation=_positive_integer(
                consent["consent_generation"], "consent generation"
            ),
            consent_disclosure_version=_text(
                consent["disclosure_version"], "consented disclosure version"
            ),
            consent_disclosure_digest=_sha256(
                consent["disclosure_digest"], "consent disclosure digest"
            ),
            consent_path_status=_text(consent["path_status"], "consent path state"),
            consent_pause_reason=(
                None
                if pause_reason is None
                else _text(pause_reason, "consent pause reason")
            ),
            current_route_id=_text(route["route_id"], "current route"),
            current_first_hop_recipient=_text(
                route["first_hop_recipient"], "current first-hop recipient"
            ),
            current_configuration_generation=_positive_integer(
                route["configuration_generation"],
                "current configuration generation",
            ),
            current_disclosure_version=_text(
                route["disclosure_version"], "current disclosure version"
            ),
            approvals=tuple(
                sorted(
                    (
                        ExecutionScopeApproval.from_wire(item)
                        for item in approvals_wire
                    ),
                    key=lambda approval: approval.approval_id,
                )
            ),
            support_contact=(
                None
                if fields["support_contact"] is None
                else SupportContactSettings.from_wire(fields["support_contact"])
            ),
            receipts=tuple(receipts),
        )


@dataclass(frozen=True)
class OwnerSettingsTransition:
    state: OwnerSettingsState
    result: dict[str, object]
    replayed: bool = False

    def __post_init__(self) -> None:
        if type(self.state) is not OwnerSettingsState:
            raise SettingsContractViolation("invalid owner settings transition state")
        if type(self.result) is not dict:
            raise SettingsContractViolation("invalid owner settings transition result")
        _boolean(self.replayed, "owner settings replay state")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


_CONTACT_WINDOW_RE = re.compile(
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]-(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z"
)


def _contact_window(value: object) -> str:
    text = _text(value, "contact window")
    if _CONTACT_WINDOW_RE.fullmatch(text) is None:
        raise SettingsContractViolation("invalid contact window")
    return text


def _notification_state(value: object, name: str) -> str:
    if type(value) is not str or value not in NOTIFICATION_STATES:
        raise SettingsContractViolation(f"invalid {name}")
    return value


_OWNER_SETTINGS_COMMAND_TYPES = (
    FieldUpdate,
    NotificationUpdate,
    ControlUpdate,
    OwnerControlCommand,
    ConsentRenewal,
    CloseButRetainRequest,
    SupportContactCommand,
)


def _command_identity_and_digest(command: object) -> tuple[str, str]:
    if type(command) not in _OWNER_SETTINGS_COMMAND_TYPES:
        raise SettingsContractViolation("unsupported owner settings command")
    wire = command.to_wire()  # type: ignore[union-attr]
    body = {"kind": type(command).__name__, "command": wire}
    digest = "sha256:" + hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    context = getattr(command, "context", None)
    if type(context) is OwnerCommandContext:
        identity = "owner-command:" + context.command_id
    else:
        identity = "command-digest:" + digest
    return identity, digest


def _replay_result(
    state: OwnerSettingsState,
    identity: str,
    digest: str,
) -> dict[str, object] | None:
    for receipt_identity, receipt_digest, result_json in state.receipts:
        if receipt_identity != identity:
            continue
        if receipt_digest != digest:
            raise SettingsContractViolation(
                "owner command identifier was already used for another command"
            )
        parsed = json.loads(result_json)
        if type(parsed) is not dict:  # pragma: no cover - state invariant
            raise SettingsContractViolation("invalid replay result")
        return parsed
    return None


def _with_receipt(
    state: OwnerSettingsState,
    identity: str,
    digest: str,
    result: dict[str, object],
) -> OwnerSettingsState:
    return replace(
        state,
        version=state.version + 1,
        receipts=state.receipts + ((identity, digest, _canonical_json(result)),),
    )


def _validate_owner_context(
    state: OwnerSettingsState,
    context: OwnerCommandContext,
) -> None:
    if (
        context.actor_kind != "current_owner"
        or context.permission != "health_settings.write"
        or context.owner_id != state.owner_id
        or context.installation_id != state.installation_id
    ):
        raise SettingsContractViolation("owner command authority mismatch")


def _command_generation(command: object) -> int:
    context = getattr(command, "context", None)
    if type(context) is OwnerCommandContext:
        return context.generation
    generation = getattr(command, "generation", None)
    return _positive_integer(generation, "owner command current-head generation")


def _validate_command_cas(
    command: object,
    *,
    current_head_generation: int,
    current_writer_fence: str,
) -> None:
    head_generation = _positive_integer(
        current_head_generation, "current-head generation"
    )
    writer_fence = _text(current_writer_fence, "current writer fence")
    if _command_generation(command) != head_generation:
        raise SettingsContractViolation("stale current-head generation")
    context = getattr(command, "context", None)
    if type(context) is OwnerCommandContext and context.writer_fence != writer_fence:
        raise SettingsContractViolation("stale current writer fence")


def _timezone_info(timezone_name: str) -> datetime_tzinfo:
    parsed_name = _iana_timezone(timezone_name, "timezone")
    try:
        return ZoneInfo(parsed_name)
    except ZoneInfoNotFoundError:
        try:
            from dateutil.tz import gettz  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - validated by _iana_timezone
            raise SettingsContractViolation("timezone database is unavailable") from exc
        zone = gettz(parsed_name)
        if zone is None:  # pragma: no cover - validated by _iana_timezone
            raise SettingsContractViolation("timezone database is unavailable")
        return zone


def _valid_utc_instants(
    local_naive: datetime, zone: datetime_tzinfo
) -> tuple[datetime, ...]:
    instants: set[datetime] = set()
    for fold in (0, 1):
        local = local_naive.replace(tzinfo=zone, fold=fold)
        candidate = local.astimezone(datetime_timezone.utc)
        round_trip = candidate.astimezone(zone)
        if round_trip.replace(tzinfo=None) == local_naive:
            instants.add(candidate)
    return tuple(sorted(instants))


def _next_valid_local_day_start(
    requested_at_utc: str,
    timezone_name: str,
) -> tuple[str, str]:
    requested = datetime.fromisoformat(_utc_time(requested_at_utc, "timezone request time"))
    zone = _timezone_info(timezone_name)
    candidate_date = requested.astimezone(zone).date() + timedelta(days=1)
    for _ in range(370):
        local_midnight = datetime(
            candidate_date.year,
            candidate_date.month,
            candidate_date.day,
        )
        for second in range(24 * 60 * 60):
            instants = _valid_utc_instants(
                local_midnight + timedelta(seconds=second), zone
            )
            if instants:
                return candidate_date.isoformat(), instants[0].isoformat()
        candidate_date += timedelta(days=1)
    raise SettingsContractViolation("no next valid local review day")


def _approval_map(
    state: OwnerSettingsState,
) -> dict[str, ExecutionScopeApproval]:
    return {approval.approval_id: approval for approval in state.approvals}


def _sorted_approvals(
    approvals: Mapping[str, ExecutionScopeApproval],
) -> tuple[ExecutionScopeApproval, ...]:
    return tuple(approvals[key] for key in sorted(approvals))


class OwnerSettingsEngine:
    """Pure state-machine seam; persistence and writer CAS remain outside it."""

    @staticmethod
    def seed(
        *,
        owner_id: str,
        installation_id: str,
        version: int,
        timezone: str,
        preferences: object,
        consent: object,
        contact: SupportContactSettings | None,
        completed_review_keys: tuple[str, ...],
    ) -> OwnerSettingsState:
        parsed_preferences = _mapping(
            preferences,
            frozenset(
                {
                    "contact_window",
                    "expression_style",
                    "proactive_contact",
                    "ordinary_notifications",
                }
            ),
            "initial owner preferences",
        )
        notifications = _mapping(
            parsed_preferences["ordinary_notifications"],
            frozenset(ORDINARY_NOTIFICATION_KINDS),
            "initial ordinary notifications",
        )
        parsed_consent = _mapping(
            consent,
            frozenset(
                {
                    "enabled",
                    "data_scope",
                    "route_id",
                    "first_hop_recipient",
                    "configuration_generation",
                    "consent_generation",
                    "disclosure_version",
                    "disclosure_digest",
                }
            ),
            "initial consent",
        )
        parsed_owner = _text(owner_id, "settings owner")
        parsed_installation = _text(installation_id, "settings installation")
        parsed_version = _positive_integer(version, "settings version")
        if contact is not None:
            if type(contact) is not SupportContactSettings:
                raise SettingsContractViolation("invalid current support contact")
            if (
                contact.owner_id != parsed_owner
                or contact.installation_id != parsed_installation
            ):
                raise SettingsContractViolation("support-contact authority mismatch")
        consent_generation = _positive_integer(
            parsed_consent["consent_generation"], "consent generation"
        )
        route_id = _text(parsed_consent["route_id"], "consented route")
        recipient = _text(
            parsed_consent["first_hop_recipient"], "consented first-hop recipient"
        )
        configuration_generation = _positive_integer(
            parsed_consent["configuration_generation"],
            "consented configuration generation",
        )
        disclosure_version = _text(
            parsed_consent["disclosure_version"], "consented disclosure version"
        )
        return OwnerSettingsState(
            owner_id=parsed_owner,
            installation_id=parsed_installation,
            version=parsed_version,
            timezone=_iana_timezone(timezone, "settings timezone"),
            contact_window=_contact_window(parsed_preferences["contact_window"]),
            expression_style=_text(
                parsed_preferences["expression_style"], "expression style"
            ),
            proactive_contact=_boolean(
                parsed_preferences["proactive_contact"],
                "proactive-contact preference",
            ),
            ordinary_notifications=tuple(
                (
                    kind,
                    _notification_state(
                        notifications[kind], f"{kind} notification state"
                    ),
                )
                for kind in ORDINARY_NOTIFICATION_KINDS
            ),
            proactive_support_paused=False,
            recording_stopped=False,
            recording_stopped_at_utc=None,
            cancelled_task_refs=(),
            recording_exclusions=(),
            timezone_transition=None,
            completed_review_keys=_tuple_texts_allow_empty(
                completed_review_keys, "completed review keys"
            ),
            consent_enabled=_boolean(parsed_consent["enabled"], "consent enablement"),
            consent_data_scope=_tuple_texts(
                parsed_consent["data_scope"], "consent data scope"
            ),
            consent_route_id=route_id,
            consent_first_hop_recipient=recipient,
            consent_configuration_generation=configuration_generation,
            consent_generation=consent_generation,
            consent_disclosure_version=disclosure_version,
            consent_disclosure_digest=_sha256(
                parsed_consent["disclosure_digest"], "consent disclosure digest"
            ),
            consent_path_status="active",
            consent_pause_reason=None,
            current_route_id=route_id,
            current_first_hop_recipient=recipient,
            current_configuration_generation=configuration_generation,
            current_disclosure_version=disclosure_version,
            approvals=(),
            support_contact=contact,
            receipts=(),
        )

    @staticmethod
    def managed_view(
        state: OwnerSettingsState,
        *,
        requester_owner_id: str,
    ) -> dict[str, object]:
        if type(state) is not OwnerSettingsState:
            raise SettingsContractViolation("invalid owner settings state")
        if requester_owner_id != state.owner_id:
            raise SettingsContractViolation("managed settings read is owner-scoped")
        transition = (
            None
            if state.timezone_transition is None
            else state.timezone_transition.to_wire()
        )
        required_redisclosure = None
        if state.consent_path_status == "paused":
            required_redisclosure = {
                "route_id": state.current_route_id,
                "first_hop_recipient": state.current_first_hop_recipient,
                "configuration_generation": state.current_configuration_generation,
                "disclosure_version": state.current_disclosure_version,
            }
        if state.support_contact is None:
            contact: dict[str, object] = {
                "configuration_status": "not-configured"
            }
        else:
            contact = state.support_contact.to_wire()
            contact["configuration_status"] = "configured"
            contact["minimum_alert_fields"] = tuple(
                state.support_contact.minimum_alert_fields
            )
        return {
            "owner_id": state.owner_id,
            "installation_id": state.installation_id,
            "version": state.version,
            "timezone": state.timezone,
            "preferences": {
                "contact_window": state.contact_window,
                "expression_style": state.expression_style,
                "proactive_contact": state.proactive_contact,
            },
            "ordinary_notifications": dict(state.ordinary_notifications),
            "controls": {
                "proactive_support_paused": state.proactive_support_paused,
                "recording_stopped": state.recording_stopped,
                "cancelled_task_refs": tuple(state.cancelled_task_refs),
            },
            "recording_exclusions": tuple(
                {
                    "stopped_at_utc": stopped,
                    "resumed_at_utc": resumed,
                    "backfill_allowed": False,
                }
                for stopped, resumed in state.recording_exclusions
            ),
            "timezone_transition": transition,
            "pending_timezone_transitions": (
                () if transition is None else (dict(transition),)
            ),
            "completed_review_keys": tuple(state.completed_review_keys),
            "review_policy": {
                "backfill_local_dates": (),
                "replay_completed_review_keys": (),
            },
            "consent": {
                "enabled": state.consent_enabled,
                "data_scope": tuple(state.consent_data_scope),
                "route_id": state.consent_route_id,
                "first_hop_recipient": state.consent_first_hop_recipient,
                "configuration_generation": state.consent_configuration_generation,
                "consent_generation": state.consent_generation,
                "disclosure_version": state.consent_disclosure_version,
                "disclosure_digest": state.consent_disclosure_digest,
                "path_status": state.consent_path_status,
                "pause_reason": state.consent_pause_reason,
                "required_redisclosure": required_redisclosure,
            },
            "execution_scope_approvals": {
                approval.approval_id: approval.to_wire()
                for approval in state.approvals
            },
            "support_contact": contact,
        }

    @staticmethod
    def activate_due_timezone_transition(
        state: OwnerSettingsState,
        *,
        observed_at_utc: str,
    ) -> OwnerSettingsTransition:
        """Apply a persisted timezone transition only once its instant is due."""

        if type(state) is not OwnerSettingsState:
            raise SettingsContractViolation("invalid owner settings state")
        observed_at = _utc_time(
            observed_at_utc, "timezone transition observation time"
        )
        pending = state.timezone_transition
        if pending is None:
            return OwnerSettingsTransition(
                state=state,
                result={
                    "kind": "timezone_transition_activation",
                    "outcome": "no_pending_transition",
                    "state_changed": False,
                    "observed_at_utc": observed_at,
                },
            )
        result = {
            "kind": "timezone_transition_activation",
            "transition_id": pending.transition_id,
            "previous_timezone": pending.previous_timezone,
            "timezone": pending.new_timezone,
            "effective_at_utc": pending.effective_at_utc,
            "observed_at_utc": observed_at,
        }
        if datetime.fromisoformat(observed_at) < datetime.fromisoformat(
            pending.effective_at_utc
        ):
            return OwnerSettingsTransition(
                state=state,
                result={
                    **result,
                    "outcome": "pending",
                    "state_changed": False,
                },
            )
        return OwnerSettingsTransition(
            state=replace(
                state,
                timezone=pending.new_timezone,
                timezone_transition=None,
            ),
            result={
                **result,
                "outcome": "activated",
                "state_changed": True,
            },
        )

    @classmethod
    def apply(
        cls,
        state: OwnerSettingsState,
        command: object,
        *,
        core_committed_at_utc: str,
        current_head_generation: int,
        current_writer_fence: str,
    ) -> OwnerSettingsTransition:
        if type(state) is not OwnerSettingsState:
            raise SettingsContractViolation("invalid owner settings state")
        committed_at = _utc_time(
            core_committed_at_utc, "core-committed settings time"
        )
        if type(command) not in _OWNER_SETTINGS_COMMAND_TYPES:
            raise SettingsContractViolation("unsupported owner settings command")
        _validate_command_cas(
            command,
            current_head_generation=current_head_generation,
            current_writer_fence=current_writer_fence,
        )
        if type(command) is CloseButRetainRequest:
            _validate_owner_context(state, command.context)
            return OwnerSettingsTransition(
                state=state,
                result={
                    "kind": "close_but_retain",
                    "outcome": "clarification_required",
                    "state_changed": False,
                    "clarify_controls": (
                        "proactive_support",
                        "recording",
                        "task",
                        "execution_scope_approval",
                    ),
                },
            )
        identity, digest = _command_identity_and_digest(command)
        replay = _replay_result(state, identity, digest)
        if replay is not None:
            return OwnerSettingsTransition(state=state, result=replay, replayed=True)
        if type(command) is FieldUpdate:
            next_state, result = cls._apply_field(
                state, command, committed_at
            )
        elif type(command) is NotificationUpdate:
            next_state, result = cls._apply_notification(
                state, command, committed_at
            )
        elif type(command) is ControlUpdate:
            next_state, result = cls._apply_control(
                state, command, committed_at
            )
        elif type(command) is OwnerControlCommand:
            next_state, result = cls._apply_owner_control(
                state, command, committed_at
            )
        elif type(command) is ConsentRenewal:
            next_state, result = cls._apply_consent_renewal(state, command)
        elif type(command) is SupportContactCommand:
            next_state, result = cls._apply_support_contact(state, command)
        else:  # pragma: no cover - exhaustive exact-type dispatch
            raise SettingsContractViolation("unsupported owner settings command")
        committed_state = _with_receipt(next_state, identity, digest, result)
        return OwnerSettingsTransition(state=committed_state, result=result)

    @classmethod
    def observe_route_configuration(
        cls,
        state: OwnerSettingsState,
        fact: RouteConfigurationUpdate,
    ) -> OwnerSettingsTransition:
        """Project a core-owned route fact without treating it as an owner command."""

        if type(state) is not OwnerSettingsState:
            raise SettingsContractViolation("invalid owner settings state")
        if type(fact) is not RouteConfigurationUpdate:
            raise SettingsContractViolation("invalid route configuration fact")
        next_state, result = cls._apply_route(state, fact)
        return OwnerSettingsTransition(state=next_state, result=result)

    @staticmethod
    def _apply_field(
        state: OwnerSettingsState,
        command: FieldUpdate,
        committed_at: str,
    ) -> tuple[OwnerSettingsState, dict[str, object]]:
        if command.field_name not in {
            "timezone",
            "contact_window",
            "expression_style",
            "proactive_contact",
        }:
            raise SettingsContractViolation("unknown independently mutable setting")
        current: object = {
            "timezone": state.timezone,
            "contact_window": state.contact_window,
            "expression_style": state.expression_style,
            "proactive_contact": state.proactive_contact,
        }[command.field_name]
        if command.old_value != current:
            raise SettingsContractViolation("stale owner setting value")
        if command.new_value == current:
            raise SettingsContractViolation("owner setting update is a no-op")

        effective_at = committed_at
        if command.field_name == "timezone":
            new_timezone = _iana_timezone(command.new_value, "new timezone")
            first_review_date, effective_at = _next_valid_local_day_start(
                committed_at, new_timezone
            )
            transition_body = {
                "owner_id": state.owner_id,
                "installation_id": state.installation_id,
                "settings_version": state.version + 1,
                "previous_timezone": state.timezone,
                "new_timezone": new_timezone,
                "requested_at_utc": committed_at,
                "first_review_local_date": first_review_date,
                "effective_at_utc": effective_at,
            }
            transition_digest = hashlib.sha256(
                _canonical_json(transition_body).encode("utf-8")
            ).hexdigest()
            timezone_transition = TimezoneTransition(
                transition_id="timezone-transition:" + transition_digest,
                **transition_body,
            )
            next_state = replace(state, timezone_transition=timezone_transition)
        elif command.field_name == "contact_window":
            next_state = replace(
                state, contact_window=_contact_window(command.new_value)
            )
        elif command.field_name == "expression_style":
            next_state = replace(
                state,
                expression_style=_text(command.new_value, "expression style"),
            )
        else:
            next_state = replace(
                state,
                proactive_contact=_boolean(
                    command.new_value, "proactive-contact preference"
                ),
            )
        return next_state, {
            "kind": "field_update",
            "field_name": command.field_name,
            "old_value": command.old_value,
            "new_value": command.new_value,
            "settings_version": state.version + 1,
            "effective_at_utc": effective_at,
        }

    @staticmethod
    def _apply_notification(
        state: OwnerSettingsState,
        command: NotificationUpdate,
        committed_at: str,
    ) -> tuple[OwnerSettingsState, dict[str, object]]:
        notifications = dict(state.ordinary_notifications)
        if notifications[command.kind] != command.old_state:
            raise SettingsContractViolation("stale ordinary notification value")
        if command.new_state == command.old_state:
            raise SettingsContractViolation("ordinary notification update is a no-op")
        notifications[command.kind] = command.new_state
        next_state = replace(
            state,
            ordinary_notifications=tuple(
                (kind, notifications[kind]) for kind in ORDINARY_NOTIFICATION_KINDS
            ),
        )
        return next_state, {
            "kind": "notification_update",
            "notification_kind": command.kind,
            "old_state": command.old_state,
            "new_state": command.new_state,
            "settings_version": state.version + 1,
            "effective_at_utc": committed_at,
        }

    @staticmethod
    def _apply_control(
        state: OwnerSettingsState,
        command: ControlUpdate,
        committed_at: str,
    ) -> tuple[OwnerSettingsState, dict[str, object]]:
        name = command.control_name
        operation = command.operation
        if name == "proactive_support":
            if command.target_ref is not None or operation not in {"pause", "resume"}:
                raise SettingsContractViolation("invalid proactive-support control")
            desired = operation == "pause"
            if state.proactive_support_paused is desired:
                raise SettingsContractViolation("proactive-support control already applied")
            next_state = replace(state, proactive_support_paused=desired)
        elif name == "recording":
            if command.target_ref is not None or operation not in {"stop", "resume"}:
                raise SettingsContractViolation("invalid recording control")
            if operation == "stop":
                if state.recording_stopped:
                    raise SettingsContractViolation("recording is already stopped")
                next_state = replace(
                    state,
                    recording_stopped=True,
                    recording_stopped_at_utc=committed_at,
                )
            else:
                if not state.recording_stopped or state.recording_stopped_at_utc is None:
                    raise SettingsContractViolation("recording is not stopped")
                if datetime.fromisoformat(committed_at) <= datetime.fromisoformat(
                    state.recording_stopped_at_utc
                ):
                    raise SettingsContractViolation("recording resume must follow stop")
                next_state = replace(
                    state,
                    recording_stopped=False,
                    recording_stopped_at_utc=None,
                    recording_exclusions=state.recording_exclusions
                    + ((state.recording_stopped_at_utc, committed_at),),
                )
        elif name == "task":
            if operation != "cancel" or command.target_ref is None:
                raise SettingsContractViolation("invalid task control")
            if command.target_ref in state.cancelled_task_refs:
                raise SettingsContractViolation("task is already cancelled")
            next_state = replace(
                state,
                cancelled_task_refs=tuple(
                    sorted(state.cancelled_task_refs + (command.target_ref,))
                ),
            )
        else:
            raise SettingsContractViolation(
                "authority and support-contact controls require owner command context"
            )
        return next_state, {
            "kind": "control_update",
            "control_name": name,
            "operation": operation,
            "target_ref": command.target_ref,
            "settings_version": state.version + 1,
            "effective_at_utc": committed_at,
        }

    @classmethod
    def _apply_owner_control(
        cls,
        state: OwnerSettingsState,
        command: OwnerControlCommand,
        committed_at: str,
    ) -> tuple[OwnerSettingsState, dict[str, object]]:
        _validate_owner_context(state, command.context)
        update = command.control_update
        if command.task_mutation is not None:
            return state, {
                "kind": "task_control",
                "operation": command.task_mutation.operation,
                "task_id": command.task_mutation.task_id,
                "settings_version": state.version + 1,
                "effective_at_utc": committed_at,
            }
        if update.control_name != "execution_scope_approval":
            return cls._apply_control(
                state, update, committed_at
            )
        target = update.target_ref
        if target is None:  # pragma: no cover - contract invariant
            raise SettingsContractViolation("execution approval requires target")
        approvals = _approval_map(state)
        current = approvals.get(target)
        candidate = command.execution_scope_approval
        operation = update.operation
        if operation == "grant":
            if current is not None or candidate is None:
                raise SettingsContractViolation("execution approval already exists")
            if candidate.approval_version != 1 or candidate.revoked:
                raise SettingsContractViolation("new approval must start at active version one")
            approvals[target] = candidate
        elif operation == "revise":
            if current is None or candidate is None or current.revoked:
                raise SettingsContractViolation("no active execution approval to revise")
            if candidate.approval_version != current.approval_version + 1:
                raise SettingsContractViolation(
                    "execution approval revision requires the next owner-approved version"
                )
            if candidate.revoked:
                raise SettingsContractViolation("approval revision cannot be pre-revoked")
            approvals[target] = candidate
        elif operation == "revoke":
            if candidate is not None or current is None or current.revoked:
                raise SettingsContractViolation("no active execution approval to revoke")
            approvals[target] = replace(
                current,
                approval_version=current.approval_version + 1,
                revoked=True,
                revoked_at_utc=committed_at,
            )
        else:
            raise SettingsContractViolation("invalid execution approval operation")
        current_after = approvals[target]
        next_state = replace(state, approvals=_sorted_approvals(approvals))
        return next_state, {
            "kind": "execution_scope_approval",
            "operation": operation,
            "approval": current_after.to_wire(),
            "settings_version": state.version + 1,
            "effective_at_utc": committed_at,
        }

    @staticmethod
    def _apply_route(
        state: OwnerSettingsState,
        command: RouteConfigurationUpdate,
    ) -> tuple[OwnerSettingsState, dict[str, object]]:
        if (
            command.configuration_generation
            < state.current_configuration_generation
        ):
            raise SettingsContractViolation("stale route configuration fact")
        current = (
            state.current_route_id,
            state.current_first_hop_recipient,
            state.current_configuration_generation,
            state.current_disclosure_version,
        )
        incoming = (
            command.route_id,
            command.first_hop_recipient,
            command.configuration_generation,
            command.disclosure_version,
        )
        if incoming == current:
            return state, {
                "kind": "route_configuration_observation",
                "route_fact_generation": command.generation,
                "outcome": "unchanged",
                "state_changed": False,
                "settings_version": state.version,
            }
        if (
            command.route_id != state.consent_route_id
            or command.first_hop_recipient != state.consent_first_hop_recipient
        ):
            pause_reason = "first_hop_route_changed"
        elif (
            command.configuration_generation
            != state.consent_configuration_generation
        ):
            pause_reason = "configuration_generation_changed"
        elif command.disclosure_version != state.consent_disclosure_version:
            pause_reason = "disclosure_version_changed"
        else:
            pause_reason = None
        next_state = replace(
            state,
            current_route_id=command.route_id,
            current_first_hop_recipient=command.first_hop_recipient,
            current_configuration_generation=command.configuration_generation,
            current_disclosure_version=command.disclosure_version,
            consent_path_status="active" if pause_reason is None else "paused",
            consent_pause_reason=pause_reason,
        )
        return next_state, {
            "kind": "route_configuration_observation",
            "route_fact_generation": command.generation,
            "route_id": command.route_id,
            "first_hop_recipient": command.first_hop_recipient,
            "configuration_generation": command.configuration_generation,
            "disclosure_version": command.disclosure_version,
            "path_status": next_state.consent_path_status,
            "pause_reason": pause_reason,
            "state_changed": True,
            "settings_version": state.version,
        }

    @staticmethod
    def _apply_consent_renewal(
        state: OwnerSettingsState,
        command: ConsentRenewal,
    ) -> tuple[OwnerSettingsState, dict[str, object]]:
        _validate_owner_context(state, command.context)
        expected = (
            state.current_route_id,
            state.current_first_hop_recipient,
            state.current_configuration_generation,
            state.current_disclosure_version,
        )
        supplied = (
            command.route_id,
            command.first_hop_recipient,
            command.configuration_generation,
            command.disclosure_version,
        )
        if supplied != expected:
            raise SettingsContractViolation(
                "consent renewal does not match the exact current disclosure"
            )
        next_state = replace(
            state,
            consent_route_id=command.route_id,
            consent_first_hop_recipient=command.first_hop_recipient,
            consent_configuration_generation=command.configuration_generation,
            consent_generation=state.consent_generation + 1,
            consent_disclosure_version=command.disclosure_version,
            consent_disclosure_digest=command.disclosure_digest,
            consent_path_status="active",
            consent_pause_reason=None,
        )
        return next_state, {
            "kind": "consent_renewal",
            "renewal_id": command.renewal_id,
            "route_id": command.route_id,
            "first_hop_recipient": command.first_hop_recipient,
            "configuration_generation": command.configuration_generation,
            "disclosure_version": command.disclosure_version,
            "consented_at_utc": command.consented_at_utc,
            "path_status": "active",
            "settings_version": state.version + 1,
        }

    @staticmethod
    def _apply_support_contact(
        state: OwnerSettingsState,
        command: SupportContactCommand,
    ) -> tuple[OwnerSettingsState, dict[str, object]]:
        _validate_owner_context(state, command.context)
        current = state.support_contact
        operation = command.operation
        candidate = command.contact
        authority_id = command.authority_id
        if operation == "configure":
            if current is not None:
                raise SettingsContractViolation("support contact is already configured")
            if candidate is None:  # pragma: no cover - contract invariant
                raise SettingsContractViolation("missing support-contact configuration")
            if (
                candidate.owner_id != state.owner_id
                or candidate.installation_id != state.installation_id
                or candidate.version != 1
                or candidate.alert_authority_status != "invalidated"
                or candidate.correction_authority_status != "invalidated"
            ):
                raise SettingsContractViolation(
                    "first support contact must be unapproved owner version one"
                )
            updated = candidate
        else:
            if current is None:
                raise SettingsContractViolation("support contact is not configured")
            if (
                command.expected_contact_version != current.version
                or command.expected_route_id != current.route_id
                or command.expected_route_generation != current.route_generation
            ):
                raise SettingsContractViolation("stale support-contact boundary")
        if operation in _SUPPORT_CONTACT_REPLACEMENTS:
            if candidate is None:  # pragma: no cover - contract invariant
                raise SettingsContractViolation("missing support-contact replacement")
            if (
                candidate.owner_id != state.owner_id
                or candidate.installation_id != state.installation_id
                or candidate.version != current.version + 1
                or candidate.alert_authority_status != "invalidated"
                or candidate.correction_authority_status != "invalidated"
            ):
                raise SettingsContractViolation(
                    "replacement must be the next invalidated owner contact version"
                )
            if operation == "replace" and candidate.contact_id == current.contact_id:
                raise SettingsContractViolation("replacement must identify a new contact")
            if operation == "change_method":
                if candidate.contact_id != current.contact_id:
                    raise SettingsContractViolation(
                        "method change cannot replace the contact identity"
                    )
                if (
                    candidate.method_kind == current.method_kind
                    and candidate.method_value == current.method_value
                ):
                    raise SettingsContractViolation(
                        "method change must change the contact method"
                    )
            updated = candidate
        elif operation == "configure":
            pass
        elif operation == "pause":
            if current.dedicated_paused:
                raise SettingsContractViolation("support contact is already paused")
            updated = replace(
                current,
                version=current.version + 1,
                dedicated_paused=True,
            )
        elif operation == "resume":
            if not current.dedicated_paused:
                raise SettingsContractViolation("support contact is not paused")
            updated = replace(
                current,
                version=current.version + 1,
                dedicated_paused=False,
            )
        elif operation == "grant_alert_authority":
            if authority_id is None:  # pragma: no cover - contract invariant
                raise SettingsContractViolation("missing alert authority identifier")
            if current.alert_authority_status == "approved":
                raise SettingsContractViolation("alert authority is already approved")
            updated = replace(
                current,
                version=current.version + 1,
                alert_authority_status="approved",
                alert_approval_id=authority_id,
                alert_authority_binding=current.expected_authority_binding(),
            )
        elif operation == "revoke_alert_authority":
            authority_id = authority_id or current.alert_approval_id
            if (
                current.alert_authority_status != "approved"
                or authority_id != current.alert_approval_id
            ):
                raise SettingsContractViolation("no matching alert authority to revoke")
            updated = replace(
                current,
                version=current.version + 1,
                alert_authority_status="revoked",
            )
        elif operation == "grant_correction_authority":
            if authority_id is None:  # pragma: no cover - contract invariant
                raise SettingsContractViolation("missing correction authority identifier")
            if current.correction_authority_status == "approved":
                raise SettingsContractViolation("correction authority is already approved")
            updated = replace(
                current,
                version=current.version + 1,
                correction_authority_status="approved",
                correction_authority_id=authority_id,
                correction_authority_binding=current.expected_authority_binding(),
            )
        elif operation == "revoke_correction_authority":
            authority_id = authority_id or current.correction_authority_id
            if (
                current.correction_authority_status != "approved"
                or authority_id != current.correction_authority_id
            ):
                raise SettingsContractViolation(
                    "no matching correction authority to revoke"
                )
            updated = replace(
                current,
                version=current.version + 1,
                correction_authority_status="revoked",
            )
        else:  # pragma: no cover - strict command contract
            raise SettingsContractViolation("invalid support-contact operation")
        next_state = replace(state, support_contact=updated)
        return next_state, {
            "kind": "support_contact_update",
            "operation": operation,
            "support_contact": updated.to_wire(),
            "settings_version": state.version + 1,
        }

    @staticmethod
    def validate_execution_scope_consumption(
        state: OwnerSettingsState,
        request: ExecutionScopeConsumptionRequest,
    ) -> ExecutionScopeConsumptionDecision:
        """Validate one proposed effect without persisting attempt/cadence facts."""

        if type(state) is not OwnerSettingsState:
            raise SettingsContractViolation("invalid owner settings state")
        if type(request) is not ExecutionScopeConsumptionRequest:
            raise SettingsContractViolation("invalid execution-scope consumption")

        def decision(allowed: bool, reason: str) -> ExecutionScopeConsumptionDecision:
            return ExecutionScopeConsumptionDecision(
                approval_id=request.approval_id,
                approval_version=request.approval_version,
                allowed=allowed,
                reason=reason,
            )

        approval = _approval_map(state).get(request.approval_id)
        if (
            approval is None
            or approval.approval_version != request.approval_version
        ):
            return decision(False, "approval_not_current")
        if (
            request.owner_id != state.owner_id
            or request.installation_id != state.installation_id
            or approval.owner_id != request.owner_id
            or approval.installation_id != request.installation_id
        ):
            return decision(False, "approval_authority_mismatch")
        if approval.revoked:
            return decision(False, "approval_revoked")
        if datetime.fromisoformat(request.evaluated_at_utc) >= datetime.fromisoformat(
            approval.expires_at_utc
        ):
            return decision(False, "approval_expired")

        exact_fields = (
            (request.route_id, approval.route_id, "route_mismatch"),
            (
                request.configuration_generation,
                approval.configuration_generation,
                "configuration_generation_mismatch",
            ),
            (
                request.disclosure_version,
                approval.disclosure_version,
                "disclosure_version_mismatch",
            ),
            (
                request.first_hop_recipient,
                approval.first_hop_recipient,
                "first_hop_recipient_mismatch",
            ),
            (request.task_id, approval.task_id, "task_mismatch"),
            (
                request.effect_request_id,
                approval.effect_request_id,
                "effect_request_mismatch",
            ),
            (request.assignee, approval.assignee, "assignee_mismatch"),
            (request.purpose, approval.purpose, "purpose_mismatch"),
            (
                request.external_effect_kind,
                approval.external_effect_kind,
                "external_effect_kind_mismatch",
            ),
        )
        for supplied, approved, reason in exact_fields:
            if supplied != approved:
                return decision(False, reason)
        if not set(request.data_categories).issubset(
            approval.allowed_data_categories
        ):
            return decision(False, "data_category_outside_scope")
        if not set(request.data_refs).issubset(approval.allowed_data_refs):
            return decision(False, "data_reference_outside_scope")
        if request.attempts_used >= approval.max_attempts:
            return decision(False, "maximum_attempts_reached")
        if request.last_contact_at_utc is not None:
            elapsed_seconds = (
                datetime.fromisoformat(request.evaluated_at_utc)
                - datetime.fromisoformat(request.last_contact_at_utc)
            ).total_seconds()
            if elapsed_seconds < approval.min_contact_interval_seconds:
                return decision(False, "minimum_contact_interval_not_elapsed")
        return decision(True, "approval_current_and_within_scope")

    @staticmethod
    def rejudge_effect(
        state: OwnerSettingsState,
        *,
        effect_request_id: str,
        observed_outcome: str,
        effect_kind: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, object]:
        if type(state) is not OwnerSettingsState:
            raise SettingsContractViolation("invalid owner settings state")
        _text(effect_request_id, "effect request identifier")
        outcome = _text(observed_outcome, "observed effect outcome")
        if outcome == "unknown":
            return {
                "effect_request_id": effect_request_id,
                "outcome": "unknown",
                "action": "freeze_pending_owner_decision",
                "may_retry": False,
            }
        if outcome == "unknown-revocation":
            if approval_id is None:
                raise SettingsContractViolation(
                    "unknown revocation requires the affected approval"
                )
            _text(approval_id, "execution approval identifier")
            return {
                "effect_request_id": effect_request_id,
                "approval_id": approval_id,
                "approval_consumable": False,
                "action": "freeze_pending_authority_confirmation",
                "may_retry": False,
            }
        if outcome != "unsent":
            raise SettingsContractViolation("unsupported effect observation")
        if state.proactive_support_paused and effect_kind == "care_reminder":
            return {
                "effect_request_id": effect_request_id,
                "allowed": False,
                "reason": "proactive_support_paused",
                "action": "suppress_without_backfill",
                "may_retry": False,
            }
        if approval_id is not None:
            approval = _approval_map(state).get(approval_id)
            if approval is None or approval.effect_request_id != effect_request_id:
                return {
                    "effect_request_id": effect_request_id,
                    "approval_id": approval_id,
                    "allowed": False,
                    "reason": "approval_not_current",
                    "action": "suppress_without_backfill",
                    "may_retry": False,
                }
            if approval.revoked:
                return {
                    "effect_request_id": effect_request_id,
                    "approval_id": approval_id,
                    "allowed": False,
                    "reason": "approval_revoked",
                    "action": "suppress_without_backfill",
                    "may_retry": False,
                }
        return {
            "effect_request_id": effect_request_id,
            "allowed": True,
            "reason": "current_controls_allow",
            "action": "proceed_once",
            "may_retry": True,
        }


__all__ = [
    "SettingsContractViolation",
    "ORDINARY_NOTIFICATION_KINDS",
    "NOTIFICATION_STATES",
    "FieldUpdate",
    "NotificationUpdate",
    "ControlUpdate",
    "OwnerCommandContext",
    "OwnerControlCommand",
    "TimezoneTransition",
    "ConsentRenewal",
    "ExecutionScopeApproval",
    "ExecutionScopeConsumptionRequest",
    "ExecutionScopeConsumptionDecision",
    "SupportContactSettings",
    "RouteConfigurationUpdate",
    "CloseButRetainRequest",
    "SupportContactCommand",
    "OwnerSettingsState",
    "OwnerSettingsTransition",
    "OwnerSettingsEngine",
]

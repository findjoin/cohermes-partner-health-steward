"""Strict owner-mutation values for the Ticket 114 authority writer.

This module defines values only.  It does not own a settings store, a rights
store, or a second daily-health truth.  A correction remains a Ticket 112
``DailyTurnDraft`` and exposes that draft's existing state-transition targets.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TypeAlias

from .authority import MAX_OPAQUE_TEXT_BYTES
from .coordination import (
    DailyTurnDraft,
    EvidenceMaintenanceRequest,
)
from .rights import (
    CorrectionRevision,
    ManagedObjectReference,
    PendingCorrectionDraft,
)
from .settings import (
    CloseButRetainRequest,
    ConsentRenewal,
    ControlUpdate,
    FieldUpdate,
    NotificationUpdate,
    OwnerCommandContext,
    OwnerControlCommand,
    OwnerSettingsState,
    SupportContactCommand,
)


class OwnerAuthorityContractViolation(ValueError):
    """An owner mutation cannot cross the core authority seam."""


OWNER_MUTATION_PERMISSIONS = frozenset(
    {
        "health_settings.write",
        "health_data.correct",
        "health_data.read",
        "health_data.export",
    }
)

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")

OwnerSettingsCommand: TypeAlias = (
    FieldUpdate
    | NotificationUpdate
    | ControlUpdate
    | OwnerControlCommand
    | ConsentRenewal
    | CloseButRetainRequest
    | SupportContactCommand
)

_SETTINGS_COMMAND_TYPES = (
    FieldUpdate,
    NotificationUpdate,
    ControlUpdate,
    OwnerControlCommand,
    ConsentRenewal,
    CloseButRetainRequest,
    SupportContactCommand,
)
_SETTINGS_COMMAND_BY_TAG = {
    value.__name__: value for value in _SETTINGS_COMMAND_TYPES
}


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or not value.strip() or value == "*":
        raise OwnerAuthorityContractViolation(f"invalid {name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise OwnerAuthorityContractViolation(f"invalid {name}") from exc
    if len(encoded) > MAX_OPAQUE_TEXT_BYTES:
        raise OwnerAuthorityContractViolation(f"invalid {name}")
    return value


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise OwnerAuthorityContractViolation(f"invalid {name}")
    return value


def _sha256(value: object, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise OwnerAuthorityContractViolation(f"invalid {name}")
    return value


def _utc_time(value: object, name: str) -> str:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise OwnerAuthorityContractViolation(f"invalid {name}") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset() != timedelta(0)
    ):
        raise OwnerAuthorityContractViolation(f"invalid {name}")
    return text


def _mapping(
    value: object,
    fields: frozenset[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise OwnerAuthorityContractViolation(f"invalid {name} fields")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise OwnerAuthorityContractViolation(
            "owner mutation is not JSON serializable"
        ) from exc


def _digest(value: object) -> str:
    body = _canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _thaw_json(value: object, name: str, *, depth: int = 0) -> object:
    """Detach one rights-owned frozen JSON value for strict wire storage."""

    if depth > 32:
        raise OwnerAuthorityContractViolation(f"invalid {name}")
    if value is None or type(value) in {bool, int, str}:
        if type(value) is str:
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise OwnerAuthorityContractViolation(f"invalid {name}") from exc
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise OwnerAuthorityContractViolation(f"invalid {name}")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise OwnerAuthorityContractViolation(f"invalid {name}")
            try:
                key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise OwnerAuthorityContractViolation(f"invalid {name}") from exc
            result[key] = _thaw_json(item, name, depth=depth + 1)
        return result
    if type(value) in {tuple, list}:
        return [
            _thaw_json(item, name, depth=depth + 1)
            for item in value
        ]
    raise OwnerAuthorityContractViolation(f"invalid {name}")


def _settings_command_to_storage(
    command: OwnerSettingsCommand | None,
) -> dict[str, object] | None:
    if command is None:
        return None
    if type(command) not in _SETTINGS_COMMAND_TYPES:
        raise OwnerAuthorityContractViolation("unsupported owner settings command")
    return {
        "kind": type(command).__name__,
        "command": command.to_wire(),
    }


def _settings_command_from_storage(
    value: object,
) -> OwnerSettingsCommand | None:
    if value is None:
        return None
    fields = _mapping(
        value,
        frozenset({"kind", "command"}),
        "tagged owner settings command",
    )
    kind = _text(fields["kind"], "owner settings command kind")
    command_type = _SETTINGS_COMMAND_BY_TAG.get(kind)
    if command_type is None:
        raise OwnerAuthorityContractViolation("unsupported owner settings command")
    try:
        command = command_type.from_wire(fields["command"])
    except (TypeError, ValueError) as exc:
        raise OwnerAuthorityContractViolation(
            "invalid owner settings command"
        ) from exc
    if type(command) is not command_type:
        raise OwnerAuthorityContractViolation("invalid owner settings command")
    return command


def _pending_correction_to_storage(
    pending: PendingCorrectionDraft | None,
) -> dict[str, object] | None:
    if pending is None:
        return None
    if type(pending) is not PendingCorrectionDraft:
        raise OwnerAuthorityContractViolation("invalid pending correction")
    return {
        "owner_id": pending.owner_id,
        "installation_id": pending.installation_id,
        "base_state_digest": pending.base_state_digest,
        "target_ref": pending.target_ref.to_wire(),
        "revision": pending.revision.to_wire(),
        "previous_value": _thaw_json(
            pending.previous_value,
            "pending correction previous value",
        ),
        "maintenance_request": pending.maintenance_request.to_storage(),
    }


def _pending_correction_from_storage(
    value: object,
) -> PendingCorrectionDraft | None:
    if value is None:
        return None
    fields = _mapping(
        value,
        frozenset(
            {
                "owner_id",
                "installation_id",
                "base_state_digest",
                "target_ref",
                "revision",
                "previous_value",
                "maintenance_request",
            }
        ),
        "pending correction",
    )
    try:
        return PendingCorrectionDraft(
            owner_id=_text(fields["owner_id"], "pending correction owner"),
            installation_id=_text(
                fields["installation_id"],
                "pending correction installation",
            ),
            base_state_digest=_sha256(
                fields["base_state_digest"],
                "pending correction base state digest",
            ),
            target_ref=ManagedObjectReference.from_wire(fields["target_ref"]),
            revision=CorrectionRevision.from_wire(fields["revision"]),
            previous_value=_thaw_json(
                fields["previous_value"],
                "pending correction previous value",
            ),
            maintenance_request=EvidenceMaintenanceRequest.from_storage(
                fields["maintenance_request"]
            ),
        )
    except (TypeError, ValueError) as exc:
        raise OwnerAuthorityContractViolation("invalid pending correction") from exc


def _binding_digest(
    *,
    context: "OwnerMutationContext",
    expected_settings_version: int,
    requested_at_utc: str,
    settings_command: OwnerSettingsCommand | None,
    pending_correction: PendingCorrectionDraft | None,
) -> str:
    """Bind business authority while deliberately excluding the daily draft.

    A complete daily draft carries this digest, so including that draft here
    would create a circular digest dependency.
    """

    return _digest(
        {
            "schema_version": 1,
            "context": context.to_storage(),
            "expected_settings_version": expected_settings_version,
            "requested_at_utc": requested_at_utc,
            "settings_command": _settings_command_to_storage(settings_command),
            "pending_correction": _pending_correction_to_storage(
                pending_correction
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class OwnerMutationContext:
    command_id: str
    causal_id: str
    actor_kind: str
    owner_id: str
    installation_id: str
    permissions: tuple[str, ...]
    context_ref: str
    current_head_generation: int
    writer_fence: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.command_id, "owner mutation command identifier"),
            (self.causal_id, "owner mutation causal identifier"),
            (self.owner_id, "owner identifier"),
            (self.installation_id, "installation identifier"),
            (self.context_ref, "owner mutation context reference"),
            (self.writer_fence, "owner mutation writer fence"),
        ):
            _text(value, name)
        if type(self.actor_kind) is not str or self.actor_kind != "current_owner":
            raise OwnerAuthorityContractViolation(
                "owner mutation must be authored by current owner"
            )
        if (
            type(self.permissions) is not tuple
            or not self.permissions
            or any(
                type(permission) is not str
                or permission not in OWNER_MUTATION_PERMISSIONS
                for permission in self.permissions
            )
            or self.permissions != tuple(sorted(set(self.permissions)))
        ):
            raise OwnerAuthorityContractViolation(
                "invalid owner mutation permissions"
            )
        _positive_integer(
            self.current_head_generation,
            "owner mutation current-head generation",
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "causal_id": self.causal_id,
            "actor_kind": self.actor_kind,
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "permissions": list(self.permissions),
            "context_ref": self.context_ref,
            "current_head_generation": self.current_head_generation,
            "writer_fence": self.writer_fence,
        }

    @classmethod
    def from_storage(cls, value: object) -> "OwnerMutationContext":
        fields = _mapping(
            value,
            frozenset(
                {
                    "command_id",
                    "causal_id",
                    "actor_kind",
                    "owner_id",
                    "installation_id",
                    "permissions",
                    "context_ref",
                    "current_head_generation",
                    "writer_fence",
                }
            ),
            "owner mutation context",
        )
        raw_permissions = fields["permissions"]
        if type(raw_permissions) is not list:
            raise OwnerAuthorityContractViolation(
                "invalid owner mutation permissions"
            )
        return cls(
            command_id=_text(
                fields["command_id"],
                "owner mutation command identifier",
            ),
            causal_id=_text(
                fields["causal_id"],
                "owner mutation causal identifier",
            ),
            actor_kind=_text(fields["actor_kind"], "owner mutation actor"),
            owner_id=_text(fields["owner_id"], "owner identifier"),
            installation_id=_text(
                fields["installation_id"],
                "installation identifier",
            ),
            permissions=tuple(raw_permissions),
            context_ref=_text(
                fields["context_ref"],
                "owner mutation context reference",
            ),
            current_head_generation=_positive_integer(
                fields["current_head_generation"],
                "owner mutation current-head generation",
            ),
            writer_fence=_text(
                fields["writer_fence"],
                "owner mutation writer fence",
            ),
        )


@dataclass(frozen=True, slots=True)
class OwnerMutationRequest:
    context: OwnerMutationContext
    expected_settings_version: int
    requested_at_utc: str
    settings_command: OwnerSettingsCommand | None
    pending_correction: PendingCorrectionDraft | None
    daily_turn_draft: DailyTurnDraft | None
    owner_authority_binding_digest: str

    def __post_init__(self) -> None:
        if type(self.context) is not OwnerMutationContext:
            raise OwnerAuthorityContractViolation("invalid owner mutation context")
        _positive_integer(
            self.expected_settings_version,
            "expected owner settings version",
        )
        _utc_time(self.requested_at_utc, "owner mutation request time")
        if (
            self.settings_command is not None
            and type(self.settings_command) not in _SETTINGS_COMMAND_TYPES
        ):
            raise OwnerAuthorityContractViolation(
                "unsupported owner settings command"
            )
        if (
            self.pending_correction is not None
            and type(self.pending_correction) is not PendingCorrectionDraft
        ):
            raise OwnerAuthorityContractViolation("invalid pending correction")
        if (
            self.daily_turn_draft is not None
            and type(self.daily_turn_draft) is not DailyTurnDraft
        ):
            raise OwnerAuthorityContractViolation("invalid daily turn draft")
        if self.settings_command is None and self.pending_correction is None:
            raise OwnerAuthorityContractViolation(
                "owner mutation requires settings or correction"
            )
        if (self.pending_correction is None) != (self.daily_turn_draft is None):
            raise OwnerAuthorityContractViolation(
                "correction requires one complete daily turn draft"
            )

        if self.settings_command is not None:
            if "health_settings.write" not in self.context.permissions:
                raise OwnerAuthorityContractViolation(
                    "owner settings permission required"
                )
            self._validate_settings_command_authority(self.settings_command)

        if self.pending_correction is not None:
            if "health_data.correct" not in self.context.permissions:
                raise OwnerAuthorityContractViolation(
                    "health correction permission required"
                )
            if (
                self.pending_correction.owner_id != self.context.owner_id
                or self.pending_correction.installation_id
                != self.context.installation_id
            ):
                raise OwnerAuthorityContractViolation(
                    "pending correction authority mismatch"
                )

        binding = _sha256(
            self.owner_authority_binding_digest,
            "owner authority binding digest",
        )
        expected_binding = _binding_digest(
            context=self.context,
            expected_settings_version=self.expected_settings_version,
            requested_at_utc=self.requested_at_utc,
            settings_command=self.settings_command,
            pending_correction=self.pending_correction,
        )
        if not hmac.compare_digest(binding, expected_binding):
            raise OwnerAuthorityContractViolation(
                "owner authority binding digest mismatch"
            )
        if (
            self.daily_turn_draft is not None
            and self.daily_turn_draft.owner_authority_binding_digest != binding
        ):
            raise OwnerAuthorityContractViolation(
                "daily turn owner authority binding mismatch"
            )

    def _validate_settings_command_authority(
        self,
        command: OwnerSettingsCommand,
    ) -> None:
        nested = getattr(command, "context", None)
        if nested is not None:
            if type(nested) is not OwnerCommandContext:
                raise OwnerAuthorityContractViolation(
                    "invalid nested owner settings context"
                )
            if (
                nested.owner_id != self.context.owner_id
                or nested.installation_id != self.context.installation_id
                or nested.generation != self.context.current_head_generation
                or nested.writer_fence != self.context.writer_fence
            ):
                raise OwnerAuthorityContractViolation(
                    "owner settings command authority mismatch"
                )
            return
        generation = getattr(command, "generation", None)
        if generation != self.context.current_head_generation:
            raise OwnerAuthorityContractViolation(
                "owner settings command generation mismatch"
            )

    @classmethod
    def form(
        cls,
        *,
        context: OwnerMutationContext,
        expected_settings_version: int,
        requested_at_utc: str,
        settings_command: OwnerSettingsCommand | None = None,
        pending_correction: PendingCorrectionDraft | None = None,
        daily_turn_draft: DailyTurnDraft | None = None,
    ) -> "OwnerMutationRequest":
        parsed_version = _positive_integer(
            expected_settings_version,
            "expected owner settings version",
        )
        parsed_time = _utc_time(requested_at_utc, "owner mutation request time")
        if type(context) is not OwnerMutationContext:
            raise OwnerAuthorityContractViolation("invalid owner mutation context")
        binding = _binding_digest(
            context=context,
            expected_settings_version=parsed_version,
            requested_at_utc=parsed_time,
            settings_command=settings_command,
            pending_correction=pending_correction,
        )
        bound_daily = daily_turn_draft
        if (
            type(bound_daily) is DailyTurnDraft
            and bound_daily.owner_authority_binding_digest is None
        ):
            bound_daily = replace(
                bound_daily,
                owner_authority_binding_digest=binding,
            )
        return cls(
            context=context,
            expected_settings_version=parsed_version,
            requested_at_utc=parsed_time,
            settings_command=settings_command,
            pending_correction=pending_correction,
            daily_turn_draft=bound_daily,
            owner_authority_binding_digest=binding,
        )

    @property
    def record_id(self) -> str:
        if self.daily_turn_draft is not None:
            return self.daily_turn_draft.record_id
        return (
            "owner-settings:"
            + self.owner_authority_binding_digest.removeprefix("sha256:")
        )

    @property
    def revision_digest(self) -> str:
        if self.daily_turn_draft is not None:
            return self.daily_turn_draft.revision_digest
        return _digest(
            {
                "kind": "owner-settings-revision",
                "binding": self.owner_authority_binding_digest,
            }
        )

    @property
    def transition_id(self) -> str:
        if self.daily_turn_draft is not None:
            return self.daily_turn_draft.transition_id
        digest = _digest(
            {
                "kind": "owner-settings-transition",
                "binding": self.owner_authority_binding_digest,
            }
        )
        return "owner-settings-transition:" + digest.removeprefix("sha256:")

    @property
    def payload_digest(self) -> str:
        if self.daily_turn_draft is not None:
            return self.daily_turn_draft.payload_digest
        return _digest(
            {
                "kind": "owner-settings-payload",
                "binding": self.owner_authority_binding_digest,
            }
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "context": self.context.to_storage(),
            "expected_settings_version": self.expected_settings_version,
            "requested_at_utc": self.requested_at_utc,
            "settings_command": _settings_command_to_storage(
                self.settings_command
            ),
            "pending_correction": _pending_correction_to_storage(
                self.pending_correction
            ),
            "daily_turn_draft": (
                None
                if self.daily_turn_draft is None
                else self.daily_turn_draft.to_storage()
            ),
            "owner_authority_binding_digest": (
                self.owner_authority_binding_digest
            ),
        }

    @classmethod
    def from_storage(cls, value: object) -> "OwnerMutationRequest":
        fields = _mapping(
            value,
            frozenset(
                {
                    "context",
                    "expected_settings_version",
                    "requested_at_utc",
                    "settings_command",
                    "pending_correction",
                    "daily_turn_draft",
                    "owner_authority_binding_digest",
                }
            ),
            "owner mutation request",
        )
        raw_daily = fields["daily_turn_draft"]
        if raw_daily is not None and type(raw_daily) is not dict:
            raise OwnerAuthorityContractViolation("invalid daily turn draft")
        try:
            daily = (
                None
                if raw_daily is None
                else DailyTurnDraft.from_storage(raw_daily)
            )
        except (TypeError, ValueError) as exc:
            raise OwnerAuthorityContractViolation(
                "invalid daily turn draft"
            ) from exc
        return cls(
            context=OwnerMutationContext.from_storage(fields["context"]),
            expected_settings_version=_positive_integer(
                fields["expected_settings_version"],
                "expected owner settings version",
            ),
            requested_at_utc=_utc_time(
                fields["requested_at_utc"],
                "owner mutation request time",
            ),
            settings_command=_settings_command_from_storage(
                fields["settings_command"]
            ),
            pending_correction=_pending_correction_from_storage(
                fields["pending_correction"]
            ),
            daily_turn_draft=daily,
            owner_authority_binding_digest=_sha256(
                fields["owner_authority_binding_digest"],
                "owner authority binding digest",
            ),
        )


@dataclass(frozen=True, slots=True)
class OwnerPreparedMutation:
    """Prepared business values awaiting the existing state CAS/finalize path."""

    request: OwnerMutationRequest
    next_settings: OwnerSettingsState
    settings_result: dict[str, object] | None
    daily_result_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.request) is not OwnerMutationRequest:
            raise OwnerAuthorityContractViolation("invalid owner mutation request")
        if type(self.next_settings) is not OwnerSettingsState:
            raise OwnerAuthorityContractViolation("invalid next owner settings")
        if (
            self.next_settings.owner_id != self.request.context.owner_id
            or self.next_settings.installation_id
            != self.request.context.installation_id
            or self.next_settings.version
            not in {
                self.request.expected_settings_version,
                self.request.expected_settings_version + 1,
            }
        ):
            raise OwnerAuthorityContractViolation(
                "next owner settings authority mismatch"
            )
        if self.request.settings_command is None:
            if self.settings_result is not None:
                raise OwnerAuthorityContractViolation(
                    "correction-only mutation cannot carry settings result"
                )
        elif type(self.settings_result) is not dict:
            raise OwnerAuthorityContractViolation(
                "settings mutation requires settings result"
            )
        if self.settings_result is not None:
            # Verify and detach nested mutable caller values.
            normalized = json.loads(_canonical_json(self.settings_result))
            if type(normalized) is not dict:
                raise OwnerAuthorityContractViolation(
                    "invalid owner settings result"
                )
            object.__setattr__(self, "settings_result", normalized)
        if self.daily_result_digest is not None:
            _sha256(self.daily_result_digest, "daily turn result digest")
            if self.request.pending_correction is None:
                raise OwnerAuthorityContractViolation(
                    "settings-only mutation cannot carry daily result"
                )

    @property
    def record_id(self) -> str:
        return self.request.record_id

    @property
    def revision_digest(self) -> str:
        return self.request.revision_digest

    @property
    def transition_id(self) -> str:
        return self.request.transition_id

    @property
    def payload_digest(self) -> str:
        return self.request.payload_digest

    def to_storage(self) -> dict[str, object]:
        return {
            "request": self.request.to_storage(),
            "next_settings": self.next_settings.to_wire(),
            "settings_result": self.settings_result,
            "daily_result_digest": self.daily_result_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "OwnerPreparedMutation":
        fields = _mapping(
            value,
            frozenset(
                {
                    "request",
                    "next_settings",
                    "settings_result",
                    "daily_result_digest",
                }
            ),
            "prepared owner mutation",
        )
        raw_result = fields["settings_result"]
        if raw_result is not None and type(raw_result) is not dict:
            raise OwnerAuthorityContractViolation(
                "invalid owner settings result"
            )
        raw_daily_digest = fields["daily_result_digest"]
        return cls(
            request=OwnerMutationRequest.from_storage(fields["request"]),
            next_settings=OwnerSettingsState.from_wire(fields["next_settings"]),
            settings_result=raw_result,
            daily_result_digest=(
                None
                if raw_daily_digest is None
                else _sha256(raw_daily_digest, "daily turn result digest")
            ),
        )


__all__ = [
    "OWNER_MUTATION_PERMISSIONS",
    "OwnerAuthorityContractViolation",
    "OwnerMutationContext",
    "OwnerMutationRequest",
    "OwnerPreparedMutation",
    "OwnerSettingsCommand",
]

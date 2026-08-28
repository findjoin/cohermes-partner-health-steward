"""Core-owned encrypted local state store for synthetic validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .admission import SourceEnvelope, SourceReceipt
from .answer_resolution import ModelEffectReport
from .authority import (
    AuthoritySnapshot,
    AuthorityValidationError,
    ClaimingEffect,
    CommittedTransition,
    EffectIntent,
    ExecutingEffect,
    PreparedTransition,
    RevisionTarget,
    TerminalEffect,
    holder_id_for,
    validate_committed_transition,
    validate_opaque_text,
    validate_controlled_effect_kind,
)
from .contract import (
    CommandEnvelope,
    DailyTurnPreparePayload,
    EffectResultPayload,
    OwnerPreparePayload,
    ProtocolViolation,
    Response,
    StateCommitPayload,
)
from .coordination import (
    DailyHealthState,
    DailySkillUseFact,
    DailyTurnDraft,
    DailyTurnResult,
)
from .delivery import DeliveryOutboxState
from .health_commands import (
    HealthCommandContractViolation,
    HealthCommandReceipt,
    TrustedHealthCommand,
)
from .initialization import (
    InitializationDisclosureChallenge,
    InitializationDraft,
    stable_digest,
)
from .owner_authority import OwnerPreparedMutation
from .review import DailyReviewLedger
from .settings import OwnerSettingsState
from .status import StatusContractViolation, StatusProjection, StatusTransition
from .tasks import TaskRuntimeState


class KeyUnavailable(RuntimeError):
    pass


class StoreUnavailable(RuntimeError):
    """SQLite could not complete a durable health-state operation."""


class CausalIdConflict(RuntimeError):
    """A causal ID was reused with a different command envelope."""


@dataclass(frozen=True)
class Ticket115PreparedMutation:
    """One complete Ticket 115 aggregate revision awaiting current-head CAS."""

    prepared: PreparedTransition
    owner_id: str
    installation_id: str
    base_task_digest: str
    base_review_digest: str
    base_delivery_digest: str
    task_state: TaskRuntimeState
    review_state: DailyReviewLedger
    delivery_state: DeliveryOutboxState
    health_command_receipt: HealthCommandReceipt | None = None
    base_status_digest: str | None = None
    status_projection: StatusProjection | None = None
    managed_effect_intent: EffectIntent | None = None

    def __post_init__(self) -> None:
        if type(self.prepared) is not PreparedTransition:
            raise AuthorityValidationError("invalid ticket115 preparation")
        validate_opaque_text(self.owner_id, "ticket115 owner identifier")
        validate_opaque_text(
            self.installation_id,
            "ticket115 installation identifier",
        )
        for digest, name in (
            (self.base_task_digest, "ticket115 base task digest"),
            (self.base_review_digest, "ticket115 base review digest"),
            (self.base_delivery_digest, "ticket115 base delivery digest"),
        ):
            _owner_recovery_digest(digest, name)
        if (
            type(self.task_state) is not TaskRuntimeState
            or type(self.review_state) is not DailyReviewLedger
            or type(self.delivery_state) is not DeliveryOutboxState
        ):
            raise AuthorityValidationError("invalid ticket115 aggregate payload")
        if self.health_command_receipt is not None and (
            type(self.health_command_receipt) is not HealthCommandReceipt
        ):
            raise AuthorityValidationError("invalid ticket115 health command receipt")
        if self.managed_effect_intent is not None and (
            type(self.managed_effect_intent) is not EffectIntent
            or self.managed_effect_intent.authority != self.prepared.base
            or self.health_command_receipt is None
        ):
            raise AuthorityValidationError("invalid ticket115 managed effect intent")
        if self.status_projection is None:
            if self.base_status_digest is not None:
                raise AuthorityValidationError(
                    "ticket115 status base without projection"
                )
        else:
            if type(self.status_projection) is not StatusProjection:
                raise AuthorityValidationError(
                    "invalid ticket115 status projection"
                )
            if self.base_status_digest is not None:
                _owner_recovery_digest(
                    self.base_status_digest,
                    "ticket115 base status digest",
                )
        authorities = {
            (self.task_state.owner_id, self.task_state.installation_id),
            (self.review_state.owner_id, self.review_state.installation_id),
            (self.delivery_state.owner_id, self.delivery_state.installation_id),
        }
        if authorities != {(self.owner_id, self.installation_id)}:
            raise AuthorityValidationError("ticket115 aggregate authority mismatch")
        if self.prepared.base.installation_id != self.installation_id:
            raise AuthorityValidationError("ticket115 preparation installation mismatch")
        target = self.prepared.target
        if target.revision_digest != self.next_state_digest:
            raise AuthorityValidationError("ticket115 revision digest mismatch")
        if target.payload_digest != self.mutation_digest:
            raise AuthorityValidationError("ticket115 mutation digest mismatch")

    @staticmethod
    def state_digest(
        task_state: TaskRuntimeState,
        review_state: DailyReviewLedger,
        delivery_state: DeliveryOutboxState,
        status_projection: StatusProjection | None = None,
    ) -> str:
        value: dict[str, object] = {
            "kind": "ticket115-authoritative-state-v1",
            "task_state": task_state.to_storage(),
            "review_state": review_state.to_storage(),
            "delivery_state": delivery_state.to_wire(),
        }
        if status_projection is not None:
            value["status_projection"] = status_projection.to_storage()
        return stable_digest(value)

    @property
    def next_state_digest(self) -> str:
        return self.state_digest(
            self.task_state,
            self.review_state,
            self.delivery_state,
            self.status_projection,
        )

    @property
    def mutation_digest(self) -> str:
        return self._mutation_digest(
            base_task_digest=self.base_task_digest,
            base_review_digest=self.base_review_digest,
            base_delivery_digest=self.base_delivery_digest,
            next_state_digest=self.next_state_digest,
            health_command_receipt=self.health_command_receipt,
            managed_effect_intent=self.managed_effect_intent,
            base_status_digest=self.base_status_digest,
            includes_status=self.status_projection is not None,
        )

    @staticmethod
    def _mutation_digest(
        *,
        base_task_digest: str,
        base_review_digest: str,
        base_delivery_digest: str,
        next_state_digest: str,
        health_command_receipt: HealthCommandReceipt | None,
        managed_effect_intent: EffectIntent | None = None,
        base_status_digest: str | None = None,
        includes_status: bool = False,
    ) -> str:
        value: dict[str, object] = {
            "kind": "ticket115-prepared-mutation-v1",
            "base": {
                "task": base_task_digest,
                "review": base_review_digest,
                "delivery": base_delivery_digest,
            },
            "next_state_digest": next_state_digest,
        }
        if health_command_receipt is not None:
            value["health_command_receipt"] = (
                health_command_receipt.to_storage()
            )
        if managed_effect_intent is not None:
            value["managed_effect_intent"] = managed_effect_intent.to_storage()
        if includes_status:
            value["base"]["status"] = base_status_digest  # type: ignore[index]
        return stable_digest(value)

    @classmethod
    def prepare(
        cls,
        *,
        base: AuthoritySnapshot,
        current_task_state: TaskRuntimeState,
        current_review_state: DailyReviewLedger,
        current_delivery_state: DeliveryOutboxState,
        task_state: TaskRuntimeState,
        review_state: DailyReviewLedger,
        delivery_state: DeliveryOutboxState,
        health_command_receipt: HealthCommandReceipt | None = None,
        managed_effect_intent: EffectIntent | None = None,
        current_status_projection: StatusProjection | None = None,
        status_projection: StatusProjection | None = None,
    ) -> "Ticket115PreparedMutation":
        base_digests = (
            stable_digest(current_task_state.to_storage()),
            stable_digest(current_review_state.to_storage()),
            stable_digest(current_delivery_state.to_wire()),
        )
        next_state_digest = cls.state_digest(
            task_state,
            review_state,
            delivery_state,
            status_projection,
        )
        base_status_digest = (
            None
            if current_status_projection is None
            else stable_digest(current_status_projection.to_storage())
        )
        mutation_digest = cls._mutation_digest(
            base_task_digest=base_digests[0],
            base_review_digest=base_digests[1],
            base_delivery_digest=base_digests[2],
            next_state_digest=next_state_digest,
            health_command_receipt=health_command_receipt,
            managed_effect_intent=managed_effect_intent,
            base_status_digest=base_status_digest,
            includes_status=status_projection is not None,
        )
        identity = stable_digest(
            {
                "kind": "ticket115-transition-v1",
                "base": base.to_storage(),
                "mutation_digest": mutation_digest,
            }
        ).removeprefix("sha256:")
        prepared = PreparedTransition(
            target=RevisionTarget(
                record_id="ticket115-mutation:" + identity,
                revision_digest=next_state_digest,
                transition_id="transition:ticket115:" + identity,
                payload_digest=mutation_digest,
            ),
            base=base,
        )
        return cls(
            prepared=prepared,
            owner_id=task_state.owner_id,
            installation_id=task_state.installation_id,
            base_task_digest=base_digests[0],
            base_review_digest=base_digests[1],
            base_delivery_digest=base_digests[2],
            task_state=task_state,
            review_state=review_state,
            delivery_state=delivery_state,
            health_command_receipt=health_command_receipt,
            managed_effect_intent=managed_effect_intent,
            base_status_digest=base_status_digest,
            status_projection=status_projection,
        )

    def to_storage(self) -> dict[str, object]:
        value: dict[str, object] = {
            "prepared": self.prepared.to_storage(),
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "base_task_digest": self.base_task_digest,
            "base_review_digest": self.base_review_digest,
            "base_delivery_digest": self.base_delivery_digest,
            "task_state": self.task_state.to_storage(),
            "review_state": self.review_state.to_storage(),
            "delivery_state": self.delivery_state.to_wire(),
            "health_command_receipt": (
                None
                if self.health_command_receipt is None
                else self.health_command_receipt.to_storage()
            ),
        }
        if self.managed_effect_intent is not None:
            value["managed_effect_intent"] = (
                self.managed_effect_intent.to_storage()
            )
        if self.status_projection is not None:
            value["base_status_digest"] = self.base_status_digest
            value["status_projection"] = self.status_projection.to_storage()
        return value

    @classmethod
    def from_storage(cls, value: object) -> "Ticket115PreparedMutation":
        legacy_fields = frozenset(
            {
                "prepared",
                "owner_id",
                "installation_id",
                "base_task_digest",
                "base_review_digest",
                "base_delivery_digest",
                "task_state",
                "review_state",
                "delivery_state",
            }
        )
        status_fields = frozenset(
            {"base_status_digest", "status_projection"}
        )
        allowed_fields = {
            legacy_fields,
            legacy_fields | {"health_command_receipt"},
            legacy_fields | {"health_command_receipt", "managed_effect_intent"},
            legacy_fields | status_fields,
            legacy_fields | {"health_command_receipt"} | status_fields,
            legacy_fields
            | {"health_command_receipt", "managed_effect_intent"}
            | status_fields,
        }
        if type(value) is not dict or frozenset(value) not in allowed_fields:
            raise KeyUnavailable("invalid ticket115 prepared mutation")
        stored = value
        try:
            receipt_wire = stored.get("health_command_receipt")
            return cls(
                prepared=PreparedTransition.from_storage(stored["prepared"]),
                owner_id=stored["owner_id"],  # type: ignore[arg-type]
                installation_id=stored["installation_id"],  # type: ignore[arg-type]
                base_task_digest=stored["base_task_digest"],  # type: ignore[arg-type]
                base_review_digest=stored["base_review_digest"],  # type: ignore[arg-type]
                base_delivery_digest=stored["base_delivery_digest"],  # type: ignore[arg-type]
                task_state=TaskRuntimeState.from_storage(stored["task_state"]),
                review_state=DailyReviewLedger.from_storage(stored["review_state"]),
                delivery_state=DeliveryOutboxState.from_wire(
                    stored["delivery_state"]
                ),
                health_command_receipt=(
                    None
                    if receipt_wire is None
                    else HealthCommandReceipt.from_storage(receipt_wire)
                ),
                managed_effect_intent=(
                    None
                    if stored.get("managed_effect_intent") is None
                    else EffectIntent.from_storage(
                        stored["managed_effect_intent"]
                    )
                ),
                base_status_digest=stored.get("base_status_digest"),  # type: ignore[arg-type]
                status_projection=(
                    None
                    if stored.get("status_projection") is None
                    else StatusProjection.from_storage(
                        stored["status_projection"]
                    )
                ),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, AuthorityValidationError):
                raise
            raise AuthorityValidationError(
                "invalid ticket115 prepared mutation"
            ) from exc


def _owner_recovery_digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != len("sha256:") + 64
    ):
        raise AuthorityValidationError(f"invalid {name}")
    try:
        int(value.removeprefix("sha256:"), 16)
    except ValueError as exc:
        raise AuthorityValidationError(f"invalid {name}") from exc
    return value


def _strict_storage_mapping(
    value: object,
    fields: frozenset[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise KeyUnavailable(f"invalid {name}")
    return value


def _strict_storage_list(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise KeyUnavailable(f"invalid {name}")
    return value


@dataclass(frozen=True)
class OwnerPreparedCorrectionRecovery:
    """Body-free recovery authority for one prepared owner correction.

    Ticket 112's prepared daily aggregate is the sole durable copy of the
    correction body.  This value binds that aggregate to the owner command and
    retains only the business values needed to resume commit/finalize.
    """

    command_id: str
    record_id: str
    revision_digest: str
    transition_id: str
    payload_digest: str
    owner_id: str
    installation_id: str
    current_head_generation: int
    writer_fence: str
    expected_settings_version: int
    owner_authority_binding_digest: str
    next_settings: OwnerSettingsState
    settings_result: dict[str, object] | None
    daily_source_causal_id: str
    daily_result_digest: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.command_id, "owner mutation command identifier"),
            (self.record_id, "owner mutation record identifier"),
            (self.transition_id, "owner mutation transition identifier"),
            (self.owner_id, "owner identifier"),
            (self.installation_id, "installation identifier"),
            (self.writer_fence, "owner mutation writer fence"),
            (self.daily_source_causal_id, "daily source causal identifier"),
        ):
            validate_opaque_text(value, name)
        _owner_recovery_digest(
            self.revision_digest,
            "owner mutation revision digest",
        )
        _owner_recovery_digest(
            self.payload_digest,
            "owner mutation payload digest",
        )
        _owner_recovery_digest(
            self.owner_authority_binding_digest,
            "owner authority binding digest",
        )
        _owner_recovery_digest(
            self.daily_result_digest,
            "owner mutation daily result digest",
        )
        if (
            type(self.current_head_generation) is not int
            or self.current_head_generation < 1
            or type(self.expected_settings_version) is not int
            or self.expected_settings_version < 1
        ):
            raise AuthorityValidationError("invalid owner recovery version")
        if type(self.next_settings) is not OwnerSettingsState or (
            self.next_settings.owner_id != self.owner_id
            or self.next_settings.installation_id != self.installation_id
            or self.next_settings.version
            not in {
                self.expected_settings_version,
                self.expected_settings_version + 1,
            }
        ):
            raise AuthorityValidationError(
                "owner recovery settings authority mismatch"
            )
        if self.settings_result is not None:
            if type(self.settings_result) is not dict:
                raise AuthorityValidationError("invalid owner settings result")
            try:
                normalized = json.loads(
                    json.dumps(
                        self.settings_result,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise AuthorityValidationError(
                    "invalid owner settings result"
                ) from exc
            object.__setattr__(self, "settings_result", normalized)

    @classmethod
    def for_preparation(
        cls,
        prepared: OwnerPreparedMutation,
    ) -> "OwnerPreparedCorrectionRecovery":
        if type(prepared) is not OwnerPreparedMutation:
            raise AuthorityValidationError("prepared owner mutation required")
        request = prepared.request
        daily = request.daily_turn_draft
        if (
            request.pending_correction is None
            or daily is None
            or prepared.daily_result_digest is None
        ):
            raise AuthorityValidationError(
                "prepared owner correction required"
            )
        return cls(
            command_id=request.context.command_id,
            record_id=prepared.record_id,
            revision_digest=prepared.revision_digest,
            transition_id=prepared.transition_id,
            payload_digest=prepared.payload_digest,
            owner_id=request.context.owner_id,
            installation_id=request.context.installation_id,
            current_head_generation=(
                request.context.current_head_generation
            ),
            writer_fence=request.context.writer_fence,
            expected_settings_version=request.expected_settings_version,
            owner_authority_binding_digest=(
                request.owner_authority_binding_digest
            ),
            next_settings=prepared.next_settings,
            settings_result=prepared.settings_result,
            daily_source_causal_id=daily.source_causal_id,
            daily_result_digest=prepared.daily_result_digest,
        )

    def matches_prepared(self, prepared: OwnerPreparedMutation) -> bool:
        try:
            return self == type(self).for_preparation(prepared)
        except AuthorityValidationError:
            return False

    def matches_daily(self, daily: DailyTurnDraft) -> bool:
        return (
            type(daily) is DailyTurnDraft
            and daily.turn_kind == "complete-turn"
            and daily.source_causal_id == self.daily_source_causal_id
            and daily.record_id == self.record_id
            and daily.revision_digest == self.revision_digest
            and daily.transition_id == self.transition_id
            and daily.payload_digest == self.payload_digest
            and daily.owner_authority_binding_digest
            == self.owner_authority_binding_digest
            and daily.owner_correction_revision is not None
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "owner_id": self.owner_id,
            "installation_id": self.installation_id,
            "current_head_generation": self.current_head_generation,
            "writer_fence": self.writer_fence,
            "expected_settings_version": self.expected_settings_version,
            "owner_authority_binding_digest": (
                self.owner_authority_binding_digest
            ),
            "next_settings": self.next_settings.to_wire(),
            "settings_result": self.settings_result,
            "daily_turn_ref": {
                "source_causal_id": self.daily_source_causal_id,
                "record_id": self.record_id,
                "revision_digest": self.revision_digest,
                "transition_id": self.transition_id,
                "payload_digest": self.payload_digest,
                "result_digest": self.daily_result_digest,
            },
        }

    @classmethod
    def from_storage(
        cls,
        value: object,
    ) -> "OwnerPreparedCorrectionRecovery":
        fields = {
            "command_id",
            "owner_id",
            "installation_id",
            "current_head_generation",
            "writer_fence",
            "expected_settings_version",
            "owner_authority_binding_digest",
            "next_settings",
            "settings_result",
            "daily_turn_ref",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise AuthorityValidationError("invalid owner correction recovery")
        daily_ref = value["daily_turn_ref"]
        if not isinstance(daily_ref, Mapping) or set(daily_ref) != {
            "source_causal_id",
            "record_id",
            "revision_digest",
            "transition_id",
            "payload_digest",
            "result_digest",
        }:
            raise AuthorityValidationError("invalid owner daily-turn reference")
        return cls(
            command_id=value["command_id"],  # type: ignore[arg-type]
            record_id=daily_ref["record_id"],  # type: ignore[arg-type]
            revision_digest=daily_ref["revision_digest"],  # type: ignore[arg-type]
            transition_id=daily_ref["transition_id"],  # type: ignore[arg-type]
            payload_digest=daily_ref["payload_digest"],  # type: ignore[arg-type]
            owner_id=value["owner_id"],  # type: ignore[arg-type]
            installation_id=value["installation_id"],  # type: ignore[arg-type]
            current_head_generation=value["current_head_generation"],  # type: ignore[arg-type]
            writer_fence=value["writer_fence"],  # type: ignore[arg-type]
            expected_settings_version=value["expected_settings_version"],  # type: ignore[arg-type]
            owner_authority_binding_digest=value[  # type: ignore[arg-type]
                "owner_authority_binding_digest"
            ],
            next_settings=OwnerSettingsState.from_wire(
                value["next_settings"]
            ),
            settings_result=value["settings_result"],  # type: ignore[arg-type]
            daily_source_causal_id=daily_ref["source_causal_id"],  # type: ignore[arg-type]
            daily_result_digest=daily_ref["result_digest"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class _ExactCommandReceipt:
    command: CommandEnvelope
    response: Response


@dataclass(frozen=True)
class _DigestCommandReceipt:
    command_digest: str
    response: Response


@dataclass(frozen=True)
class StoredInitialization:
    """One encrypted owner-initialization aggregate and its durable phase."""

    phase: str
    draft: InitializationDraft


@dataclass(frozen=True)
class OwnerMutationTerminalReceipt:
    """Health-body-free terminal proof for one finalized owner mutation."""

    command_id: str
    record_id: str
    revision_digest: str
    transition_id: str
    owner_authority_binding_digest: str
    base_settings_version: int
    settings_version: int
    next_settings_digest: str
    settings_result: dict[str, object] | None
    daily_result_digest: str | None

    def __post_init__(self) -> None:
        validate_opaque_text(self.command_id, "owner mutation command identifier")
        validate_opaque_text(self.record_id, "owner mutation record identifier")
        self._validate_digest(
            self.revision_digest,
            "owner mutation revision digest",
        )
        validate_opaque_text(
            self.transition_id,
            "owner mutation transition identifier",
        )
        self._validate_digest(
            self.owner_authority_binding_digest,
            "owner authority binding digest",
        )
        if (
            type(self.base_settings_version) is not int
            or self.base_settings_version < 1
        ):
            raise AuthorityValidationError("invalid base owner settings version")
        if type(self.settings_version) is not int or self.settings_version < 1:
            raise AuthorityValidationError("invalid owner settings version")
        if self.settings_version not in {
            self.base_settings_version,
            self.base_settings_version + 1,
        }:
            raise AuthorityValidationError("invalid owner settings version transition")
        self._validate_digest(
            self.next_settings_digest,
            "next owner settings digest",
        )
        if self.settings_result is not None:
            if type(self.settings_result) is not dict:
                raise AuthorityValidationError("invalid owner settings result")
            try:
                normalized = json.loads(
                    json.dumps(
                        self.settings_result,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise AuthorityValidationError(
                    "invalid owner settings result"
                ) from exc
            if type(normalized) is not dict:
                raise AuthorityValidationError("invalid owner settings result")
            object.__setattr__(self, "settings_result", normalized)
        if self.daily_result_digest is not None:
            self._validate_digest(
                self.daily_result_digest,
                "owner mutation daily result digest",
            )

    @staticmethod
    def _validate_digest(value: object, name: str) -> str:
        if (
            type(value) is not str
            or not value.startswith("sha256:")
            or len(value) != len("sha256:") + 64
        ):
            raise AuthorityValidationError(f"invalid {name}")
        try:
            int(value.removeprefix("sha256:"), 16)
        except ValueError as exc:
            raise AuthorityValidationError(f"invalid {name}") from exc
        return value

    @classmethod
    def for_finalization(
        cls,
        prepared: OwnerPreparedMutation | OwnerPreparedCorrectionRecovery,
    ) -> "OwnerMutationTerminalReceipt":
        if type(prepared) is OwnerPreparedCorrectionRecovery:
            return cls(
                command_id=prepared.command_id,
                record_id=prepared.record_id,
                revision_digest=prepared.revision_digest,
                transition_id=prepared.transition_id,
                owner_authority_binding_digest=(
                    prepared.owner_authority_binding_digest
                ),
                base_settings_version=prepared.expected_settings_version,
                settings_version=prepared.next_settings.version,
                next_settings_digest=stable_digest(
                    prepared.next_settings.to_wire()
                ),
                settings_result=prepared.settings_result,
                daily_result_digest=prepared.daily_result_digest,
            )
        if type(prepared) is not OwnerPreparedMutation:
            raise AuthorityValidationError("prepared owner mutation required")
        if (
            prepared.request.pending_correction is not None
            and prepared.daily_result_digest is None
        ):
            raise AuthorityValidationError(
                "owner correction daily result digest required"
            )
        return cls(
            command_id=prepared.request.context.command_id,
            record_id=prepared.record_id,
            revision_digest=prepared.revision_digest,
            transition_id=prepared.transition_id,
            owner_authority_binding_digest=(
                prepared.request.owner_authority_binding_digest
            ),
            base_settings_version=prepared.request.expected_settings_version,
            settings_version=prepared.next_settings.version,
            next_settings_digest=stable_digest(
                prepared.next_settings.to_wire()
            ),
            settings_result=prepared.settings_result,
            daily_result_digest=prepared.daily_result_digest,
        )

    def matches(
        self,
        prepared: OwnerPreparedMutation | OwnerPreparedCorrectionRecovery,
    ) -> bool:
        return (
            type(prepared)
            in {OwnerPreparedMutation, OwnerPreparedCorrectionRecovery}
            and self == type(self).for_finalization(prepared)
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "record_id": self.record_id,
            "revision_digest": self.revision_digest,
            "transition_id": self.transition_id,
            "owner_authority_binding_digest": (
                self.owner_authority_binding_digest
            ),
            "base_settings_version": self.base_settings_version,
            "settings_version": self.settings_version,
            "next_settings_digest": self.next_settings_digest,
            "settings_result": self.settings_result,
            "daily_result_digest": self.daily_result_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "OwnerMutationTerminalReceipt":
        fields = {
            "command_id",
            "record_id",
            "revision_digest",
            "transition_id",
            "owner_authority_binding_digest",
            "base_settings_version",
            "settings_version",
            "next_settings_digest",
            "settings_result",
            "daily_result_digest",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise AuthorityValidationError("invalid owner mutation terminal receipt")
        return cls(
            command_id=value["command_id"],  # type: ignore[arg-type]
            record_id=value["record_id"],  # type: ignore[arg-type]
            revision_digest=value["revision_digest"],  # type: ignore[arg-type]
            transition_id=value["transition_id"],  # type: ignore[arg-type]
            owner_authority_binding_digest=value[  # type: ignore[arg-type]
                "owner_authority_binding_digest"
            ],
            base_settings_version=value["base_settings_version"],  # type: ignore[arg-type]
            settings_version=value["settings_version"],  # type: ignore[arg-type]
            next_settings_digest=value["next_settings_digest"],  # type: ignore[arg-type]
            settings_result=value["settings_result"],  # type: ignore[arg-type]
            daily_result_digest=value["daily_result_digest"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class StoredOwnerMutation:
    """One encrypted prepared mutation or its body-free terminal receipt."""

    phase: str
    prepared: (
        OwnerPreparedMutation | OwnerPreparedCorrectionRecovery | None
    )
    terminal: OwnerMutationTerminalReceipt | None

    def __post_init__(self) -> None:
        if self.phase == "prepared":
            if (
                type(self.prepared)
                not in {
                    OwnerPreparedMutation,
                    OwnerPreparedCorrectionRecovery,
                }
                or self.terminal is not None
            ):
                raise AuthorityValidationError("invalid prepared owner mutation")
        elif self.phase == "finalized":
            if (
                self.prepared is not None
                or type(self.terminal) is not OwnerMutationTerminalReceipt
            ):
                raise AuthorityValidationError("invalid finalized owner mutation")
        else:
            raise AuthorityValidationError("invalid owner mutation phase")

    @property
    def command_id(self) -> str:
        if type(self.prepared) is OwnerPreparedCorrectionRecovery:
            return self.prepared.command_id
        if type(self.prepared) is OwnerPreparedMutation:
            return self.prepared.request.context.command_id
        if self.terminal is None:  # pragma: no cover - dataclass invariant
            raise AuthorityValidationError("owner mutation terminal required")
        return self.terminal.command_id

    @property
    def record_id(self) -> str:
        if type(self.prepared) in {
            OwnerPreparedMutation,
            OwnerPreparedCorrectionRecovery,
        }:
            return self.prepared.record_id
        if self.terminal is None:  # pragma: no cover - dataclass invariant
            raise AuthorityValidationError("owner mutation terminal required")
        return self.terminal.record_id

    def to_storage(self) -> dict[str, object]:
        if type(self.prepared) is OwnerPreparedCorrectionRecovery:
            prepared_wire: object = {
                "kind": "correction-recovery-v1",
                "recovery": self.prepared.to_storage(),
            }
        elif type(self.prepared) is OwnerPreparedMutation:
            prepared_wire = self.prepared.to_storage()
        else:
            prepared_wire = None
        return {
            "phase": self.phase,
            "prepared": prepared_wire,
            "terminal": (
                None if self.terminal is None else self.terminal.to_storage()
            ),
        }

    @classmethod
    def from_storage(cls, value: object) -> "StoredOwnerMutation":
        if not isinstance(value, Mapping) or set(value) != {
            "phase",
            "prepared",
            "terminal",
        }:
            raise AuthorityValidationError("invalid stored owner mutation")
        phase = value["phase"]
        if phase == "prepared":
            if value["prepared"] is None or value["terminal"] is not None:
                raise AuthorityValidationError("invalid prepared owner mutation")
            raw_prepared = value["prepared"]
            if (
                isinstance(raw_prepared, Mapping)
                and set(raw_prepared) == {"kind", "recovery"}
                and raw_prepared["kind"] == "correction-recovery-v1"
            ):
                prepared = OwnerPreparedCorrectionRecovery.from_storage(
                    raw_prepared["recovery"]
                )
            else:
                prepared = OwnerPreparedMutation.from_storage(raw_prepared)
            return cls(
                phase=phase,
                prepared=prepared,
                terminal=None,
            )
        if phase == "finalized":
            if value["prepared"] is not None or value["terminal"] is None:
                raise AuthorityValidationError("invalid finalized owner mutation")
            return cls(
                phase=phase,
                prepared=None,
                terminal=OwnerMutationTerminalReceipt.from_storage(
                    value["terminal"]
                ),
            )
        raise AuthorityValidationError("invalid owner mutation phase")


@dataclass(frozen=True)
class DailyTurnTerminalReceipt:
    """Body-free authenticated link from one finalized turn to its aggregate.

    The full draft is recovery authority only while a turn is unresolved.  At
    finalization the store keeps this bounded identity/digest projection so
    integrity verification can bind the ordered terminal chain to the current
    aggregate without replaying historical owner content.
    """

    source_causal_id: str
    record_id: str
    revision_digest: str
    transition_id: str
    payload_digest: str
    base_state_digest: str
    completion_base_state_digest: str
    evidence_stage_record_id: str
    evidence_stage_revision_digest: str
    evidence_stage_transition_id: str
    evidence_stage_payload_digest: str
    result_digest: str
    state_digest: str
    previous_terminal_digest: str | None
    ordinal: int
    skill_uses: tuple[DailySkillUseFact, ...]
    skill_proof_digests: tuple[str, ...]
    stage_kind: str = "complete-turn"

    def __post_init__(self) -> None:
        for value, name in (
            (self.source_causal_id, "source causal identifier"),
            (self.record_id, "daily turn record identifier"),
            (self.transition_id, "daily turn transition identifier"),
            (self.evidence_stage_record_id, "evidence stage record identifier"),
            (self.evidence_stage_transition_id, "evidence stage transition identifier"),
        ):
            validate_opaque_text(value, name)
        for value, name in (
            (self.revision_digest, "daily turn revision digest"),
            (self.payload_digest, "daily turn payload digest"),
            (self.base_state_digest, "daily turn base state digest"),
            (self.completion_base_state_digest, "daily completion base state digest"),
            (self.evidence_stage_revision_digest, "evidence stage revision digest"),
            (self.evidence_stage_payload_digest, "evidence stage payload digest"),
            (self.result_digest, "daily turn result digest"),
            (self.state_digest, "daily turn state digest"),
        ):
            self._validate_digest(value, name)
        if self.previous_terminal_digest is not None:
            self._validate_digest(
                self.previous_terminal_digest,
                "previous daily terminal digest",
            )
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise AuthorityValidationError("invalid daily terminal ordinal")
        if (
            type(self.skill_uses) is not tuple
            or not self.skill_uses
            or any(type(item) is not DailySkillUseFact for item in self.skill_uses)
            or type(self.skill_proof_digests) is not tuple
            or len(self.skill_proof_digests) != len(self.skill_uses)
        ):
            raise AuthorityValidationError("invalid daily terminal Skill uses")
        for proof_digest in self.skill_proof_digests:
            self._validate_digest(proof_digest, "daily Skill proof digest")
        for index, skill_use in enumerate(self.skill_uses):
            expected_parent = (
                None if index == 0 else self.skill_proof_digests[index - 1]
            )
            if (
                skill_use.source_causal_id != self.source_causal_id
                or skill_use.sequence_index != index
                or skill_use.parent_proof_digest != expected_parent
            ):
                raise AuthorityValidationError("invalid daily terminal Skill chain")
        if (
            self.skill_uses[0].canonical_name != "health-steward"
            or self.skill_uses[0].action != "plan"
            or self.skill_uses[-1].canonical_name != "health-steward"
            or self.skill_uses[-1].action != "resolve"
        ):
            raise AuthorityValidationError("invalid daily terminal stewardship")
        if self.stage_kind != "complete-turn":
            raise AuthorityValidationError("invalid daily terminal stage")

    @staticmethod
    def _validate_digest(value: object, name: str) -> str:
        if (
            type(value) is not str
            or not value.startswith("sha256:")
            or len(value) != len("sha256:") + 64
        ):
            raise AuthorityValidationError(f"invalid {name}")
        try:
            int(value.removeprefix("sha256:"), 16)
        except ValueError as exc:
            raise AuthorityValidationError(f"invalid {name}") from exc
        return value

    @classmethod
    def for_finalization(
        cls,
        draft: DailyTurnDraft,
        result: DailyTurnResult,
        state: DailyHealthState,
        *,
        previous_terminal_digest: str | None,
    ) -> "DailyTurnTerminalReceipt":
        if type(draft) is not DailyTurnDraft or type(result) is not DailyTurnResult:
            raise AuthorityValidationError("invalid finalized daily turn")
        if type(state) is not DailyHealthState:
            raise AuthorityValidationError("invalid daily health state")
        evidence_stage = draft.evidence_stage
        if (
            draft.turn_kind != "complete-turn"
            or type(evidence_stage) is not DailyTurnDraft
            or evidence_stage.turn_kind != "evidence-stage"
        ):
            raise AuthorityValidationError("complete daily turn required")
        return cls(
            source_causal_id=draft.source_causal_id,
            record_id=draft.record_id,
            revision_digest=draft.revision_digest,
            transition_id=draft.transition_id,
            payload_digest=draft.payload_digest,
            base_state_digest=evidence_stage.base_state_digest,
            completion_base_state_digest=draft.base_state_digest,
            evidence_stage_record_id=evidence_stage.record_id,
            evidence_stage_revision_digest=evidence_stage.revision_digest,
            evidence_stage_transition_id=evidence_stage.transition_id,
            evidence_stage_payload_digest=evidence_stage.payload_digest,
            result_digest=stable_digest(result.to_storage()),
            state_digest=state.digest,
            previous_terminal_digest=previous_terminal_digest,
            ordinal=len(state.processed_source_causal_ids),
            skill_uses=tuple(proof.skill_use for proof in draft.skill_proofs),
            skill_proof_digests=tuple(proof.digest for proof in draft.skill_proofs),
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_storage())

    def matches_draft(self, draft: DailyTurnDraft) -> bool:
        evidence_stage = (
            draft.evidence_stage if type(draft) is DailyTurnDraft else None
        )
        return type(evidence_stage) is DailyTurnDraft and (
            self.source_causal_id == draft.source_causal_id
            and self.record_id == draft.record_id
            and self.revision_digest == draft.revision_digest
            and self.transition_id == draft.transition_id
            and self.payload_digest == draft.payload_digest
            and self.base_state_digest == evidence_stage.base_state_digest
            and self.completion_base_state_digest == draft.base_state_digest
            and self.evidence_stage_record_id == evidence_stage.record_id
            and self.evidence_stage_revision_digest == evidence_stage.revision_digest
            and self.evidence_stage_transition_id == evidence_stage.transition_id
            and self.evidence_stage_payload_digest == evidence_stage.payload_digest
        )

    def to_storage(self) -> dict[str, object]:
        return {
            "source_causal_id": self.source_causal_id,
            "record_id": self.record_id,
            "revision_digest": self.revision_digest,
            "transition_id": self.transition_id,
            "payload_digest": self.payload_digest,
            "base_state_digest": self.base_state_digest,
            "completion_base_state_digest": self.completion_base_state_digest,
            "evidence_stage_record_id": self.evidence_stage_record_id,
            "evidence_stage_revision_digest": self.evidence_stage_revision_digest,
            "evidence_stage_transition_id": self.evidence_stage_transition_id,
            "evidence_stage_payload_digest": self.evidence_stage_payload_digest,
            "result_digest": self.result_digest,
            "state_digest": self.state_digest,
            "previous_terminal_digest": self.previous_terminal_digest,
            "ordinal": self.ordinal,
            "skill_uses": [item.to_storage() for item in self.skill_uses],
            "skill_proof_digests": list(self.skill_proof_digests),
            "stage_kind": self.stage_kind,
        }

    @classmethod
    def from_storage(cls, value: object) -> "DailyTurnTerminalReceipt":
        fields = {
            "source_causal_id",
            "record_id",
            "revision_digest",
            "transition_id",
            "payload_digest",
            "base_state_digest",
            "completion_base_state_digest",
            "evidence_stage_record_id",
            "evidence_stage_revision_digest",
            "evidence_stage_transition_id",
            "evidence_stage_payload_digest",
            "result_digest",
            "state_digest",
            "previous_terminal_digest",
            "ordinal",
            "skill_uses",
            "skill_proof_digests",
            "stage_kind",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise AuthorityValidationError("invalid daily terminal receipt")
        skill_uses = value["skill_uses"]
        skill_proof_digests = value["skill_proof_digests"]
        if type(skill_uses) is not list or type(skill_proof_digests) is not list:
            raise AuthorityValidationError("invalid daily terminal Skill uses")
        return cls(
            source_causal_id=value["source_causal_id"],  # type: ignore[arg-type]
            record_id=value["record_id"],  # type: ignore[arg-type]
            revision_digest=value["revision_digest"],  # type: ignore[arg-type]
            transition_id=value["transition_id"],  # type: ignore[arg-type]
            payload_digest=value["payload_digest"],  # type: ignore[arg-type]
            base_state_digest=value["base_state_digest"],  # type: ignore[arg-type]
            completion_base_state_digest=value["completion_base_state_digest"],  # type: ignore[arg-type]
            evidence_stage_record_id=value["evidence_stage_record_id"],  # type: ignore[arg-type]
            evidence_stage_revision_digest=value["evidence_stage_revision_digest"],  # type: ignore[arg-type]
            evidence_stage_transition_id=value["evidence_stage_transition_id"],  # type: ignore[arg-type]
            evidence_stage_payload_digest=value["evidence_stage_payload_digest"],  # type: ignore[arg-type]
            result_digest=value["result_digest"],  # type: ignore[arg-type]
            state_digest=value["state_digest"],  # type: ignore[arg-type]
            previous_terminal_digest=value["previous_terminal_digest"],  # type: ignore[arg-type]
            ordinal=value["ordinal"],  # type: ignore[arg-type]
            skill_uses=tuple(
                DailySkillUseFact.from_storage(item) for item in skill_uses
            ),
            skill_proof_digests=tuple(skill_proof_digests),  # type: ignore[arg-type]
            stage_kind=value["stage_kind"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class StoredDailyTurn:
    """One encrypted post-initialization turn and its durable phase.

    Intermediate phases retain the immutable draft but never claim a business
    result.  A finalized row contains only a body-free terminal receipt and,
    while still useful for exact replay, the minimal result projection.  Later
    evidence compaction may erase that projection without weakening the
    immutable terminal digest chain.
    """

    phase: str
    draft: DailyTurnDraft | None
    result: DailyTurnResult | None
    terminal: DailyTurnTerminalReceipt | None = None
    evidence_state_digest: str | None = None

    def __post_init__(self) -> None:
        if self.phase == "finalized":
            if (
                self.draft is not None
                or type(self.terminal) is not DailyTurnTerminalReceipt
                or self.evidence_state_digest is not None
            ):
                raise AuthorityValidationError("invalid finalized daily turn")
            if self.result is not None and type(self.result) is not DailyTurnResult:
                raise AuthorityValidationError("invalid finalized daily result")
        elif self.phase == "evidence-finalized":
            if (
                type(self.draft) is not DailyTurnDraft
                or self.draft.turn_kind != "evidence-stage"
                or self.result is not None
                or self.terminal is not None
                or self.evidence_state_digest is None
            ):
                raise AuthorityValidationError("invalid finalized evidence stage")
            DailyTurnTerminalReceipt._validate_digest(
                self.evidence_state_digest,
                "evidence stage state digest",
            )
        elif (
            self.phase not in {"prepared", "unknown", "committed"}
            or type(self.draft) is not DailyTurnDraft
            or self.result is not None
            or self.terminal is not None
            or self.evidence_state_digest is not None
        ):
            raise AuthorityValidationError("invalid unresolved daily turn")

    @property
    def source_causal_id(self) -> str:
        return (
            self.draft.source_causal_id
            if self.draft is not None
            else self._terminal().source_causal_id
        )

    @property
    def record_id(self) -> str:
        return self.draft.record_id if self.draft is not None else self._terminal().record_id

    def _terminal(self) -> DailyTurnTerminalReceipt:
        if self.terminal is None:
            raise AuthorityValidationError("daily terminal receipt required")
        return self.terminal


@dataclass(frozen=True)
class PendingCommand:
    """The only command allowed to reconcile one unresolved remote transition."""

    record_id: str
    command: CommandEnvelope
    remote_attempted: bool


@dataclass(frozen=True)
class PendingEffectResult:
    """A redacted, exact causal owner for one unresolved effect terminal result.

    The raw completion capability is deliberately never serialised.  Its
    one-way holder binding, plus every command authority field that can alter
    the result, is retained so only the original causal request can reconcile
    a response-lost release.
    """

    effect_id: str
    causal_id: str
    protocol_version: int
    peer: str
    source: str
    generation: int
    scope: tuple[str, ...]
    intent_digest: str
    lease_id: str
    holder_id: str
    status: str
    terminal: bool
    result_digest: str
    model_report: ModelEffectReport | None
    remote_attempted: bool

    @classmethod
    def from_command(
        cls,
        command: CommandEnvelope,
        execution: ExecutingEffect,
        *,
        remote_attempted: bool,
    ) -> "PendingEffectResult":
        if command.action != "effect.result" or not isinstance(command.payload, EffectResultPayload):
            raise ProtocolViolation("invalid effect result reservation")
        payload = command.payload
        if (
            payload.effect_id != execution.intent.effect_id
            or payload.intent_digest != execution.intent.intent_digest
            or payload.lease_id != execution.lease.lease_id
            or holder_id_for(payload.completion_capability) != execution.lease.holder_id
        ):
            raise ProtocolViolation("effect-execution-capability-required")
        return cls(
            effect_id=payload.effect_id,
            causal_id=command.causal_id,
            protocol_version=command.protocol_version,
            peer=command.peer,
            source=command.source,
            generation=command.generation,
            scope=command.scope,
            intent_digest=payload.intent_digest,
            lease_id=payload.lease_id,
            holder_id=execution.lease.holder_id,
            status=payload.status,
            terminal=payload.terminal,
            result_digest=payload.result_digest,
            model_report=payload.model_report,
            remote_attempted=remote_attempted,
        )

    def matches(self, command: CommandEnvelope, execution: ExecutingEffect) -> bool:
        candidate = self.from_command(command, execution, remote_attempted=self.remote_attempted)
        return candidate == self

    def to_storage(self) -> dict[str, object]:
        return {
            "effect_id": self.effect_id,
            "causal_id": self.causal_id,
            "protocol_version": self.protocol_version,
            "peer": self.peer,
            "source": self.source,
            "generation": self.generation,
            "scope": list(self.scope),
            "intent_digest": self.intent_digest,
            "lease_id": self.lease_id,
            "holder_id": self.holder_id,
            "status": self.status,
            "terminal": self.terminal,
            "result_digest": self.result_digest,
            "model_report": (
                None if self.model_report is None else self.model_report.to_storage()
            ),
            "remote_attempted": self.remote_attempted,
        }

    @classmethod
    def from_storage(cls, value: object) -> "PendingEffectResult":
        legacy = {
            "effect_id",
            "causal_id",
            "protocol_version",
            "peer",
            "source",
            "generation",
            "scope",
            "intent_digest",
            "lease_id",
            "holder_id",
            "status",
            "terminal",
            "result_digest",
            "remote_attempted",
        }
        if not isinstance(value, Mapping) or set(value) not in (
            legacy,
            legacy | {"model_report"},
        ):
            raise KeyUnavailable("invalid pending effect result")
        scope_value = value["scope"]
        if not isinstance(scope_value, list):
            raise KeyUnavailable("invalid pending effect result")
        try:
            raw_report = value.get("model_report")
            model_report = (
                None
                if raw_report is None
                else ModelEffectReport.from_storage(raw_report)
            )
            payload = EffectResultPayload(
                effect_id=value["effect_id"],
                intent_digest=value["intent_digest"],
                lease_id=value["lease_id"],
                completion_capability=value["holder_id"],
                status=value["status"],
                terminal=value["terminal"],
                result_digest=value["result_digest"],
                model_report=model_report,
            )
            command = CommandEnvelope(
                peer=value["peer"],
                action="effect.result",
                source=value["source"],
                causal_id=value["causal_id"],
                generation=value["generation"],
                scope=tuple(scope_value),
                payload=payload,
                protocol_version=value["protocol_version"],
            )
        except (ProtocolViolation, TypeError, ValueError) as exc:
            raise KeyUnavailable("invalid pending effect result") from exc
        if not isinstance(value["remote_attempted"], bool):
            raise KeyUnavailable("invalid pending effect result")
        return cls(
            effect_id=payload.effect_id,
            causal_id=command.causal_id,
            protocol_version=command.protocol_version,
            peer=command.peer,
            source=command.source,
            generation=command.generation,
            scope=command.scope,
            intent_digest=payload.intent_digest,
            lease_id=payload.lease_id,
            holder_id=payload.completion_capability,
            status=payload.status,
            terminal=payload.terminal,
            result_digest=payload.result_digest,
            model_report=payload.model_report,
            remote_attempted=value["remote_attempted"],
        )


@dataclass(frozen=True)
class CurrentHeadRecoveryBinding:
    """The one exact command permitted to close an interrupted observation."""

    action: str
    causal_id: str
    command_digest: str

    @classmethod
    def from_command(cls, command: CommandEnvelope) -> "CurrentHeadRecoveryBinding":
        if command.action not in {"state.commit", "effect.result"}:
            raise ProtocolViolation("current-head recovery action is not supported")
        wire = EncryptedStateStore._receipt_command_wire(command)
        try:
            canonical = json.dumps(wire, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
            raise ProtocolViolation("invalid current-head recovery command") from exc
        return cls(
            action=command.action,
            causal_id=command.causal_id,
            command_digest="sha256:" + hashlib.sha256(canonical).hexdigest(),
        )

    def matches(self, command: CommandEnvelope) -> bool:
        try:
            return self == self.from_command(command)
        except ProtocolViolation:
            return False

    def to_storage(self) -> dict[str, object]:
        return {
            "action": self.action,
            "causal_id": self.causal_id,
            "command_digest": self.command_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "CurrentHeadRecoveryBinding":
        if not isinstance(value, Mapping) or set(value) != {"action", "causal_id", "command_digest"}:
            raise KeyUnavailable("invalid current-head recovery binding")
        action = value["action"]
        causal_id = value["causal_id"]
        command_digest = value["command_digest"]
        if (
            action not in {"state.commit", "effect.result"}
            or not isinstance(causal_id, str)
            or not causal_id
            or not isinstance(command_digest, str)
            or not command_digest.startswith("sha256:")
            or len(command_digest) != len("sha256:") + 64
        ):
            raise KeyUnavailable("invalid current-head recovery binding")
        return cls(action=action, causal_id=causal_id, command_digest=command_digest)


@dataclass(frozen=True)
class CurrentHeadObservationGuard:
    """Durable terminal tripwire, optionally recoverable by one exact command."""

    binding: CurrentHeadRecoveryBinding | None

    def to_storage(self) -> dict[str, object]:
        return {
            "binding": None if self.binding is None else self.binding.to_storage(),
        }

    @classmethod
    def from_storage(cls, value: object) -> "CurrentHeadObservationGuard":
        if not isinstance(value, Mapping) or set(value) != {"binding"}:
            raise KeyUnavailable("invalid current-head observation guard")
        binding = value["binding"]
        if binding is None:
            return cls(binding=None)
        return cls(binding=CurrentHeadRecoveryBinding.from_storage(binding))


@dataclass(frozen=True)
class StoredRecord:
    """A decrypted, state-discriminated local transition record."""

    state: str
    revision_digest: str
    transition_id: str
    payload: RevisionTarget | PreparedTransition | CommittedTransition


@dataclass(frozen=True)
class StoredEffect:
    """A decrypted, state-discriminated core effect record."""

    state: str
    payload: EffectIntent | ClaimingEffect | ExecutingEffect | TerminalEffect


class KeyProvider(Protocol):
    @property
    def key_id(self) -> str: ...

    def get_key(self) -> bytes: ...


class StaticKeyProvider:
    def __init__(self, key: bytes, key_id: str) -> None:
        if not isinstance(key, bytes) or len(key) not in {16, 24, 32}:
            raise ValueError("AES key must be 128, 192, or 256 bits")
        self._key = bytes(key)
        self._key_id = key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    def get_key(self) -> bytes:
        return self._key


class EncryptedStateStore:
    """A single-writer SQLite domain; payloads never sit in plaintext columns."""

    def __init__(self, database: str, key_provider: KeyProvider) -> None:
        self._key_provider = key_provider
        self._transaction_lock = threading.RLock()
        self._transaction_depth = 0
        self._poisoned = False
        self._connection = sqlite3.connect(database, uri=database.startswith("file:"), check_same_thread=False)
        self._execute("PRAGMA foreign_keys = ON")
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS health_records (
                record_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                revision_digest TEXT NOT NULL,
                transition_id TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS effects (
                effect_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS finalized_authority (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        # V1 receipts only retained status/reason and cannot truthfully replay a
        # response.  V2 stores the complete encrypted command/response pair.
        self._execute(
            "CREATE TABLE IF NOT EXISTS receipts (causal_id TEXT PRIMARY KEY, status TEXT NOT NULL, reason_code TEXT)"
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS command_receipts_v2 (
                causal_id TEXT PRIMARY KEY,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS pending_commands_v1 (
                causal_id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL UNIQUE,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS pending_effect_results_v1 (
                effect_id TEXT PRIMARY KEY,
                causal_id TEXT NOT NULL UNIQUE,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS key_check (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                key_id TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS integrity_manifest_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS terminal_observation_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS current_head_observation_guard_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS lifecycle_state_v1 (
                operation_ref TEXT PRIMARY KEY,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS source_envelopes_v1 (
                causal_id TEXT PRIMARY KEY,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS initialization_disclosure_challenges_v1 (
                disclosure_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL UNIQUE,
                admission_causal_id TEXT NOT NULL UNIQUE,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS owner_initialization_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                record_id TEXT NOT NULL UNIQUE,
                phase TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS daily_turns_v1 (
                source_causal_id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL UNIQUE,
                phase TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS daily_health_state_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS owner_settings_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS owner_mutations_v1 (
                command_id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL UNIQUE,
                phase TEXT NOT NULL CHECK(phase IN ('prepared', 'finalized')),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS business_status_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS task_runtime_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS ticket115_health_command_receipts_v1 (
                causal_id TEXT PRIMARY KEY,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS ticket115_mutations_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                record_id TEXT NOT NULL UNIQUE,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS daily_reviews_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS owner_outbox_v1 (
                intent_id TEXT PRIMARY KEY,
                state_version INTEGER NOT NULL CHECK(state_version >= 1),
                phase TEXT NOT NULL CHECK(
                    phase IN ('committed', 'claiming', 'executing', 'terminal')
                ),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS owner_delivery_observations_v1 (
                observation_id TEXT PRIMARY KEY,
                intent_id TEXT NOT NULL,
                layer TEXT NOT NULL CHECK(
                    layer IN (
                        'formed',
                        'submitted',
                        'attempted',
                        'accepted',
                        'rejected',
                        'delivered',
                        'read',
                        'unknown'
                    )
                ),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL,
                FOREIGN KEY(intent_id) REFERENCES owner_outbox_v1(intent_id)
                    ON DELETE CASCADE
            )
            """
        )
        self._execute(
            """
            CREATE INDEX IF NOT EXISTS owner_delivery_observations_intent_v1
            ON owner_delivery_observations_v1(intent_id, observation_id)
            """
        )
        self._commit("health state initialization unavailable")
        self._initialize_or_verify_key_check()
        self._initialize_integrity_manifest()

    @property
    def key_id(self) -> str:
        try:
            key_id = self._key_provider.key_id
        except Exception as exc:  # key identity is part of the key boundary
            raise KeyUnavailable("health key identity unavailable") from exc
        if not isinstance(key_id, str) or not key_id:
            raise KeyUnavailable("health key identity invalid")
        return key_id

    def _execute(self, statement: str, parameters: tuple[object, ...] = ()) -> sqlite3.Cursor:
        """Run a direct SQLite operation through the fail-closed store boundary."""

        self._ensure_available()
        try:
            return self._connection.execute(statement, parameters)
        except sqlite3.Error as exc:
            raise StoreUnavailable("health state database unavailable") from exc

    def _ensure_available(self) -> None:
        if self._poisoned:
            raise StoreUnavailable("health state connection is unavailable")
        try:
            unresolved_transaction = self._transaction_depth == 0 and self._connection.in_transaction
        except sqlite3.Error as exc:
            self._poisoned = True
            raise StoreUnavailable("health state connection is unavailable") from exc
        if unresolved_transaction:
            self._poisoned = True
            raise StoreUnavailable("health state transaction is unresolved")

    def _commit(self, message: str) -> None:
        try:
            self._connection.commit()
        except sqlite3.Error as exc:
            self._rollback_after_transaction_failure()
            raise StoreUnavailable(message) from exc

    def _cipher(self) -> AESGCM:
        try:
            key = self._key_provider.get_key()
        except Exception as exc:  # key boundary deliberately collapses provider details
            raise KeyUnavailable("health key unavailable") from exc
        if not isinstance(key, bytes) or len(key) not in {16, 24, 32}:
            raise KeyUnavailable("health key invalid")
        return AESGCM(key)

    def _seal(self, aad: str, value: object) -> tuple[bytes, bytes]:
        try:
            plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
            raise KeyUnavailable("health state serialization failed") from exc
        nonce = secrets.token_bytes(12)
        return nonce, self._cipher().encrypt(nonce, plaintext, aad.encode("utf-8"))

    def _open(self, aad: str, nonce: bytes, ciphertext: bytes) -> object:
        if not isinstance(nonce, (bytes, bytearray, memoryview)) or not isinstance(
            ciphertext, (bytes, bytearray, memoryview)
        ):
            raise KeyUnavailable("health state authentication failed")
        try:
            plaintext = self._cipher().decrypt(bytes(nonce), bytes(ciphertext), aad.encode("utf-8"))
            return json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise KeyUnavailable("health state authentication failed") from exc

    def _initialize_or_verify_key_check(self) -> None:
        row = self._execute("SELECT key_id, nonce, ciphertext FROM key_check WHERE slot = 1").fetchone()
        if row is None:
            nonce, ciphertext = self._seal("key-check", {"marker": "health-core-key-check"})
            if self._transaction_depth > 0:
                self._execute(
                    "INSERT INTO key_check(slot, key_id, nonce, ciphertext) VALUES (1, ?, ?, ?)",
                    (self.key_id, nonce, ciphertext),
                )
            else:
                with self.transaction() as connection:
                    connection.execute(
                        "INSERT INTO key_check(slot, key_id, nonce, ciphertext) VALUES (1, ?, ?, ?)",
                        (self.key_id, nonce, ciphertext),
                    )
            return
        if row[0] != self.key_id or self._open("key-check", row[1], row[2]) != {"marker": "health-core-key-check"}:
            raise KeyUnavailable("health key does not match state domain")

    def _initialize_integrity_manifest(self) -> None:
        """Create a signed empty-domain manifest only for a fresh store.

        A pre-existing state domain without a manifest is not silently adopted:
        it remains unavailable so an upgrade cannot turn unauthenticated old
        rows into trusted current health state.
        """

        manifest_row = self._execute(
            "SELECT nonce, ciphertext FROM integrity_manifest_v1 WHERE slot = 1"
        ).fetchone()
        if manifest_row is not None:
            try:
                stored = self._open("integrity-manifest", manifest_row[0], manifest_row[1])
            except KeyUnavailable:
                return
            if not isinstance(stored, Mapping) or set(stored) != {"fingerprint"}:
                return
            fingerprint = stored["fingerprint"]
            if fingerprint == self._integrity_fingerprint():
                return
            ticket111_tables = (
                "source_envelopes_v1",
                "initialization_disclosure_challenges_v1",
                "owner_initialization_v1",
            )
            ticket112_tables = ("daily_turns_v1", "daily_health_state_v1")
            ticket114_status_tables = ("business_status_v1",)
            ticket114_tables = (
                "owner_settings_v1",
                "owner_mutations_v1",
                *ticket114_status_tables,
            )
            ticket115_tables = (
                "task_runtime_v1",
                "ticket115_health_command_receipts_v1",
                "ticket115_mutations_v1",
                "daily_reviews_v1",
                "owner_outbox_v1",
                "owner_delivery_observations_v1",
            )
            migration_tables: tuple[str, ...] | None = None
            migration_shape: dict[str, bool] | None = None
            pre_ticket115_migration = False
            pre_health_command_migration = False
            if isinstance(fingerprint, str):
                if (
                    fingerprint
                    == self._pre_ticket115_health_command_integrity_fingerprint()
                    and self._execute(
                        "SELECT 1 FROM "
                        "ticket115_health_command_receipts_v1 LIMIT 1"
                    ).fetchone()
                    is None
                ):
                    migration_tables = (
                        "ticket115_health_command_receipts_v1",
                    )
                    migration_shape = {}
                    pre_health_command_migration = True
                elif (
                    fingerprint
                    == self._pre_ticket115_integrity_fingerprint()
                    and all(
                        self._execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                        is None
                        for table in ticket115_tables
                    )
                ):
                    migration_tables = ticket115_tables
                    migration_shape = {}
                    pre_ticket115_migration = True
                elif (
                    fingerprint
                    == self._integrity_fingerprint(
                        include_ticket114_status=False,
                    )
                    and all(
                        self._execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                        is None
                        for table in (*ticket114_status_tables, *ticket115_tables)
                    )
                ):
                    migration_tables = (
                        *ticket114_status_tables,
                        *ticket115_tables,
                    )
                    migration_shape = {"include_ticket114_status": False}
                elif (
                    fingerprint
                    == self._integrity_fingerprint(include_ticket114=False)
                    and all(
                        self._execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                        is None
                        for table in (*ticket114_tables, *ticket115_tables)
                    )
                ):
                    migration_tables = (*ticket114_tables, *ticket115_tables)
                    migration_shape = {"include_ticket114": False}
                elif (
                    fingerprint
                    == self._integrity_fingerprint(
                        include_ticket112=False,
                        include_ticket114=False,
                    )
                    and all(
                        self._execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                        is None
                        for table in (
                            *ticket112_tables,
                            *ticket114_tables,
                            *ticket115_tables,
                        )
                    )
                ):
                    migration_tables = (
                        *ticket112_tables,
                        *ticket114_tables,
                        *ticket115_tables,
                    )
                    migration_shape = {
                        "include_ticket112": False,
                        "include_ticket114": False,
                    }
                elif (
                    fingerprint
                    == self._integrity_fingerprint(
                        include_ticket111=False,
                        include_ticket112=False,
                        include_ticket114=False,
                    )
                    and all(
                        self._execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                        is None
                        for table in (
                            *ticket111_tables,
                            *ticket112_tables,
                            *ticket114_tables,
                            *ticket115_tables,
                        )
                    )
                ):
                    migration_tables = (
                        *ticket111_tables,
                        *ticket112_tables,
                        *ticket114_tables,
                        *ticket115_tables,
                    )
                    migration_shape = {
                        "include_ticket111": False,
                        "include_ticket112": False,
                        "include_ticket114": False,
                    }
            if migration_tables is None or migration_shape is None:
                return
            with self.transaction() as connection:
                current_row = connection.execute(
                    "SELECT nonce, ciphertext FROM integrity_manifest_v1 WHERE slot = 1"
                ).fetchone()
                if current_row is None:
                    return
                current_stored = self._open(
                    "integrity-manifest",
                    current_row[0],
                    current_row[1],
                )
                if (
                    current_stored != stored
                    or fingerprint
                    != (
                        self._pre_ticket115_health_command_integrity_fingerprint()
                        if pre_health_command_migration
                        else self._pre_ticket115_integrity_fingerprint()
                        if pre_ticket115_migration
                        else self._integrity_fingerprint(**migration_shape)
                    )
                    or any(
                        connection.execute(
                            f"SELECT 1 FROM {table} LIMIT 1"
                        ).fetchone()
                        is not None
                        for table in migration_tables
                    )
                ):
                    return
                self._refresh_integrity_manifest(connection)
            return
        populated_tables = (
            "health_records",
            "effects",
            "finalized_authority",
            "receipts",
            "command_receipts_v2",
            "pending_commands_v1",
            "pending_effect_results_v1",
            "terminal_observation_v1",
            "current_head_observation_guard_v1",
            "lifecycle_state_v1",
            "source_envelopes_v1",
            "initialization_disclosure_challenges_v1",
            "owner_initialization_v1",
            "daily_turns_v1",
            "daily_health_state_v1",
            "owner_settings_v1",
            "owner_mutations_v1",
            "business_status_v1",
            "task_runtime_v1",
            "ticket115_health_command_receipts_v1",
            "ticket115_mutations_v1",
            "daily_reviews_v1",
            "owner_outbox_v1",
            "owner_delivery_observations_v1",
        )
        if any(self._execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None for table in populated_tables):
            return
        with self.transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM integrity_manifest_v1 WHERE slot = 1"
                ).fetchone()
                is not None
                or any(
                    connection.execute(
                        f"SELECT 1 FROM {table} LIMIT 1"
                    ).fetchone()
                    is not None
                    for table in populated_tables
                )
            ):
                return
            self._refresh_integrity_manifest(connection)

    def _integrity_fingerprint(
        self,
        *,
        include_ticket111: bool = True,
        include_ticket112: bool | None = None,
        include_ticket114: bool | None = None,
        include_ticket114_status: bool | None = None,
        include_ticket115: bool | None = None,
        include_ticket115_health_commands: bool | None = None,
    ) -> str:
        """Hash every mutable domain row except the manifest itself."""

        if include_ticket112 is None:
            # A caller asking for the pre-Ticket-111 shape is necessarily also
            # asking for the pre-Ticket-112 shape.  Explicit values are used by
            # the staged migration logic when only the newest tables are absent.
            include_ticket112 = include_ticket111
        if include_ticket114 is None:
            include_ticket114 = include_ticket112
        if include_ticket114_status is None:
            include_ticket114_status = include_ticket114
        if include_ticket115 is None:
            include_ticket115 = include_ticket114_status
        if include_ticket115_health_commands is None:
            include_ticket115_health_commands = include_ticket115

        tables = {
            "records": self._execute(
                "SELECT record_id, state, revision_digest, transition_id, nonce, ciphertext "
                "FROM health_records ORDER BY record_id"
            ).fetchall(),
            "effects": self._execute(
                "SELECT effect_id, state, nonce, ciphertext FROM effects ORDER BY effect_id"
            ).fetchall(),
            "authority": self._execute(
                "SELECT slot, nonce, ciphertext FROM finalized_authority ORDER BY slot"
            ).fetchall(),
            "legacy_receipts": self._execute(
                "SELECT causal_id, status, reason_code FROM receipts ORDER BY causal_id"
            ).fetchall(),
            "receipts": self._execute(
                "SELECT causal_id, nonce, ciphertext FROM command_receipts_v2 ORDER BY causal_id"
            ).fetchall(),
            "pending": self._execute(
                "SELECT causal_id, record_id, nonce, ciphertext FROM pending_commands_v1 ORDER BY causal_id"
            ).fetchall(),
            "pending_effect_results": self._execute(
                "SELECT effect_id, causal_id, nonce, ciphertext FROM pending_effect_results_v1 ORDER BY effect_id"
            ).fetchall(),
            "terminal_observation": self._execute(
                "SELECT slot, nonce, ciphertext FROM terminal_observation_v1 ORDER BY slot"
            ).fetchall(),
            "current_head_observation_guard": self._execute(
                "SELECT slot, nonce, ciphertext FROM current_head_observation_guard_v1 ORDER BY slot"
            ).fetchall(),
            "lifecycle_state": self._execute(
                "SELECT operation_ref, nonce, ciphertext "
                "FROM lifecycle_state_v1 ORDER BY operation_ref"
            ).fetchall(),
        }
        if include_ticket111:
            tables.update(
                {
                    # Conflict resolution treats SQLite insertion order as an
                    # authority fact.  Authenticate rowid itself so a raw row
                    # reorder cannot turn a predeclared future source into a
                    # later owner decision without invalidating the manifest.
                    "source_envelopes": self._execute(
                        "SELECT rowid, causal_id, nonce, ciphertext "
                        "FROM source_envelopes_v1 ORDER BY rowid"
                    ).fetchall(),
                    "initialization_disclosure_challenges": self._execute(
                        "SELECT disclosure_id, workflow_id, admission_causal_id, "
                        "nonce, ciphertext FROM initialization_disclosure_challenges_v1 "
                        "ORDER BY disclosure_id"
                    ).fetchall(),
                    "owner_initialization": self._execute(
                        "SELECT slot, record_id, phase, nonce, ciphertext "
                        "FROM owner_initialization_v1 ORDER BY slot"
                    ).fetchall(),
                }
            )
        if include_ticket112:
            tables.update(
                {
                    "daily_turns": self._execute(
                        "SELECT source_causal_id, record_id, phase, nonce, ciphertext "
                        "FROM daily_turns_v1 ORDER BY source_causal_id"
                    ).fetchall(),
                    "daily_health_state": self._execute(
                        "SELECT slot, nonce, ciphertext "
                        "FROM daily_health_state_v1 ORDER BY slot"
                    ).fetchall(),
                }
            )
        if include_ticket114:
            tables.update(
                {
                    "owner_settings": self._execute(
                        "SELECT slot, nonce, ciphertext "
                        "FROM owner_settings_v1 ORDER BY slot"
                    ).fetchall(),
                    "owner_mutations": self._execute(
                        "SELECT command_id, record_id, phase, nonce, ciphertext "
                        "FROM owner_mutations_v1 ORDER BY command_id"
                    ).fetchall(),
                }
            )
        if include_ticket114_status:
            tables["business_status"] = self._execute(
                "SELECT slot, nonce, ciphertext "
                "FROM business_status_v1 ORDER BY slot"
            ).fetchall()
        if include_ticket115:
            tables.update(
                {
                    "task_runtime": self._execute(
                        "SELECT slot, nonce, ciphertext "
                        "FROM task_runtime_v1 ORDER BY slot"
                    ).fetchall(),
                    "ticket115_mutations": self._execute(
                        "SELECT slot, record_id, nonce, ciphertext "
                        "FROM ticket115_mutations_v1 ORDER BY slot"
                    ).fetchall(),
                    "daily_reviews": self._execute(
                        "SELECT slot, nonce, ciphertext "
                        "FROM daily_reviews_v1 ORDER BY slot"
                    ).fetchall(),
                    "owner_outbox": self._execute(
                        "SELECT intent_id, state_version, phase, nonce, ciphertext "
                        "FROM owner_outbox_v1 ORDER BY intent_id"
                    ).fetchall(),
                    "owner_delivery_observations": self._execute(
                        "SELECT observation_id, intent_id, layer, nonce, ciphertext "
                        "FROM owner_delivery_observations_v1 "
                        "ORDER BY observation_id"
                    ).fetchall(),
                }
            )
        if include_ticket115_health_commands:
            tables["ticket115_health_command_receipts"] = self._execute(
                "SELECT causal_id, nonce, ciphertext "
                "FROM ticket115_health_command_receipts_v1 "
                "ORDER BY causal_id"
            ).fetchall()

        def wire_value(value: object) -> object:
            if isinstance(value, bytes):
                return {"bytes": value.hex()}
            if isinstance(value, memoryview):
                return {"bytes": value.tobytes().hex()}
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            return {"unsupported": repr(value)}

        wire_tables = {
            table: [[wire_value(field) for field in row] for row in rows]
            for table, rows in tables.items()
        }
        encoded = json.dumps(wire_tables, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _pre_ticket115_integrity_fingerprint(self) -> str:
        """Return the signed shape immediately before Ticket 115.

        Call the base implementation directly so older test and deployment
        subclasses that override ``_integrity_fingerprint`` with the Ticket
        114 signature remain compatible during startup migration.
        """

        return EncryptedStateStore._integrity_fingerprint(
            self,
            include_ticket115=False,
        )

    def _pre_ticket115_health_command_integrity_fingerprint(self) -> str:
        """Return Ticket 115's signed shape before trusted command receipts."""

        return EncryptedStateStore._integrity_fingerprint(
            self,
            include_ticket115=True,
            include_ticket115_health_commands=False,
        )

    def _refresh_integrity_manifest(self, connection: sqlite3.Connection) -> None:
        fingerprint = self._integrity_fingerprint()
        nonce, ciphertext = self._seal("integrity-manifest", {"fingerprint": fingerprint})
        connection.execute(
            """
            INSERT INTO integrity_manifest_v1(slot, nonce, ciphertext)
            VALUES (1, ?, ?)
            ON CONFLICT(slot) DO UPDATE SET nonce=excluded.nonce, ciphertext=excluded.ciphertext
            """,
            (nonce, ciphertext),
        )

    def _verify_integrity_manifest(self) -> None:
        row = self._execute(
            "SELECT nonce, ciphertext FROM integrity_manifest_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            raise KeyUnavailable("health state integrity manifest missing")
        stored = self._open("integrity-manifest", row[0], row[1])
        if not isinstance(stored, Mapping) or set(stored) != {"fingerprint"}:
            raise KeyUnavailable("health state integrity manifest invalid")
        fingerprint = stored["fingerprint"]
        if not isinstance(fingerprint, str) or fingerprint != self._integrity_fingerprint():
            raise KeyUnavailable("health state integrity manifest mismatch")

    def _assert_integrity_manifest_before_mutation(self) -> None:
        """Refuse to let a normal write re-sign externally altered state."""

        self._verify_integrity_manifest()

    def verify_key(self) -> str:
        self._initialize_or_verify_key_check()
        return self.key_id

    def terminal_observed(self) -> bool:
        """Return whether this durable state domain has observed a terminal head.

        The latch is deliberately irreversible through normal core APIs.  A
        same-named current-head recreated at an older nonterminal revision
        cannot reopen health/model/outbound paths after terminal observation.
        """

        row = self._execute(
            "SELECT nonce, ciphertext FROM terminal_observation_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            return False
        if self._open("terminal-observation", row[0], row[1]) != {"terminal": True}:
            raise KeyUnavailable("invalid terminal observation")
        return True

    def latch_terminal_observation(self) -> None:
        """Durably close this state domain after a current-head terminal read."""

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            row = connection.execute(
                "SELECT nonce, ciphertext FROM terminal_observation_v1 WHERE slot = 1"
            ).fetchone()
            if row is not None:
                if self._open("terminal-observation", row[0], row[1]) != {"terminal": True}:
                    raise KeyUnavailable("invalid terminal observation")
                return
            nonce, ciphertext = self._seal("terminal-observation", {"terminal": True})
            connection.execute(
                "INSERT INTO terminal_observation_v1(slot, nonce, ciphertext) VALUES (1, ?, ?)",
                (nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    def current_head_observation_guard(self) -> CurrentHeadObservationGuard | None:
        row = self._execute(
            "SELECT nonce, ciphertext FROM current_head_observation_guard_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            return None
        return CurrentHeadObservationGuard.from_storage(
            self._open("current-head-observation-guard", row[0], row[1])
        )

    def current_head_observation_incomplete(self) -> bool:
        return self.current_head_observation_guard() is not None

    def arm_current_head_observation(
        self,
        binding: CurrentHeadRecoveryBinding | None = None,
    ) -> None:
        """Commit a pre-read tripwire before observing current-head state."""

        desired = CurrentHeadObservationGuard(binding=binding)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            row = connection.execute(
                "SELECT nonce, ciphertext FROM current_head_observation_guard_v1 WHERE slot = 1"
            ).fetchone()
            if row is not None:
                existing = CurrentHeadObservationGuard.from_storage(
                    self._open("current-head-observation-guard", row[0], row[1])
                )
                if existing != desired:
                    raise StoreUnavailable("current-head observation already incomplete")
                return
            nonce, ciphertext = self._seal("current-head-observation-guard", desired.to_storage())
            connection.execute(
                "INSERT INTO current_head_observation_guard_v1(slot, nonce, ciphertext) VALUES (1, ?, ?)",
                (nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    def clear_current_head_observation(
        self,
        binding: CurrentHeadRecoveryBinding | None = None,
    ) -> None:
        """Clear a completed nonterminal read tripwire in the same state domain."""

        expected = CurrentHeadObservationGuard(binding=binding)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            row = connection.execute(
                "SELECT nonce, ciphertext FROM current_head_observation_guard_v1 WHERE slot = 1"
            ).fetchone()
            if row is None:
                return
            existing = CurrentHeadObservationGuard.from_storage(
                self._open("current-head-observation-guard", row[0], row[1])
            )
            if existing != expected:
                raise StoreUnavailable("current-head observation guard binding mismatch")
            cursor = connection.execute("DELETE FROM current_head_observation_guard_v1 WHERE slot = 1")
            if cursor.rowcount:
                self._refresh_integrity_manifest(connection)

    def replace_current_head_observation(
        self,
        expected_binding: CurrentHeadRecoveryBinding | None,
        next_binding: CurrentHeadRecoveryBinding | None,
    ) -> None:
        """Atomically retarget a live tripwire to the next remote phase."""

        expected = CurrentHeadObservationGuard(binding=expected_binding)
        replacement = CurrentHeadObservationGuard(binding=next_binding)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            row = connection.execute(
                "SELECT nonce, ciphertext FROM current_head_observation_guard_v1 WHERE slot = 1"
            ).fetchone()
            if row is None:
                raise StoreUnavailable("current-head observation guard missing")
            existing = CurrentHeadObservationGuard.from_storage(
                self._open("current-head-observation-guard", row[0], row[1])
            )
            if existing != expected:
                raise StoreUnavailable("current-head observation guard binding mismatch")
            nonce, ciphertext = self._seal("current-head-observation-guard", replacement.to_storage())
            connection.execute(
                "UPDATE current_head_observation_guard_v1 SET nonce = ?, ciphertext = ? WHERE slot = 1",
                (nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    @contextmanager
    def serialized(self) -> Iterator[None]:
        """Hold the local single-writer lane across a remote CAS boundary.

        A commit first durably journals its causal identity, then may call the
        remote current-head port, and finally persists the local transition and
        replay receipt.  The journal must be its own committed transaction, but
        those phases still need one in-process writer lane.
        """

        with self._transaction_lock:
            yield

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One re-entrant transaction for a domain mutation and its receipt."""

        self._transaction_lock.acquire()
        outermost = self._transaction_depth == 0
        try:
            self._ensure_available()
            if outermost:
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                except sqlite3.Error as exc:
                    raise StoreUnavailable("health state transaction unavailable") from exc
            self._transaction_depth += 1
            try:
                yield self._connection
            except BaseException as exc:
                self._transaction_depth -= 1
                if outermost:
                    self._rollback_after_transaction_failure()
                if isinstance(exc, sqlite3.Error):
                    raise StoreUnavailable("health state transaction operation unavailable") from exc
                raise
            else:
                self._transaction_depth -= 1
                if outermost:
                    try:
                        self._connection.commit()
                    except sqlite3.Error as exc:
                        self._rollback_after_transaction_failure()
                        raise StoreUnavailable("health state commit unavailable") from exc
        finally:
            self._transaction_lock.release()

    def _rollback_after_transaction_failure(self) -> None:
        try:
            self._connection.rollback()
            if self._connection.in_transaction:
                self._poisoned = True
        except sqlite3.Error:
            # A connection that cannot roll back may expose uncommitted rows to
            # later reads.  It is permanently fail-closed until rebuilt.
            self._poisoned = True

    def receipt(self, command: CommandEnvelope) -> Response | None:
        row = self._execute(
            "SELECT nonce, ciphertext FROM command_receipts_v2 WHERE causal_id = ?",
            (command.causal_id,),
        ).fetchone()
        if row is None:
            legacy = self._execute(
                "SELECT 1 FROM receipts WHERE causal_id = ?",
                (command.causal_id,),
            ).fetchone()
            if legacy is not None:
                raise CausalIdConflict("legacy-receipt-unreplayable")
            return None
        stored = self._decode_receipt(command.causal_id, row[0], row[1])
        if isinstance(stored, _ExactCommandReceipt):
            if stored.command.to_wire() != self._receipt_command_wire(command):
                raise CausalIdConflict("causal-id-conflict")
        elif not hmac.compare_digest(
            stored.command_digest,
            self._receipt_command_digest(command),
        ):
            raise CausalIdConflict("causal-id-conflict")
        return stored.response

    @staticmethod
    def _health_command_receipt_aad(causal_id: str) -> str:
        return "ticket115-health-command-receipt:" + causal_id

    def _decode_health_command_receipt(
        self,
        causal_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> HealthCommandReceipt:
        try:
            wire = self._open(
                self._health_command_receipt_aad(causal_id),
                nonce,
                ciphertext,
            )
            receipt = HealthCommandReceipt.from_storage(wire)
        except HealthCommandContractViolation as exc:
            raise KeyUnavailable("invalid health command receipt") from exc
        if receipt.causal_id != causal_id:
            raise KeyUnavailable(
                "health command receipt causal identifier mismatch"
            )
        if receipt.to_storage() != wire:
            raise KeyUnavailable("health command receipt round-trip mismatch")
        return receipt

    def _health_command_receipt_for_causal_id(
        self,
        causal_id: str,
    ) -> HealthCommandReceipt | None:
        validate_opaque_text(causal_id, "health command causal identifier")
        row = self._execute(
            "SELECT nonce, ciphertext "
            "FROM ticket115_health_command_receipts_v1 "
            "WHERE causal_id = ?",
            (causal_id,),
        ).fetchone()
        if row is None:
            return None
        return self._decode_health_command_receipt(causal_id, row[0], row[1])

    def lookup_health_command_receipt(
        self,
        command: TrustedHealthCommand,
    ) -> HealthCommandReceipt | None:
        """Return an exact replay or reject reuse of its causal identifier."""

        if type(command) is not TrustedHealthCommand:
            raise AuthorityValidationError("trusted health command required")
        receipt = self._health_command_receipt_for_causal_id(
            command.causal_id
        )
        if receipt is not None and not hmac.compare_digest(
            receipt.command_digest,
            command.command_digest,
        ):
            raise CausalIdConflict("causal-id-conflict")
        return receipt

    def health_command_receipts(self) -> tuple[HealthCommandReceipt, ...]:
        """Return the append-only managed command ledger in commit order."""

        rows = self._execute(
            "SELECT causal_id, nonce, ciphertext "
            "FROM ticket115_health_command_receipts_v1 ORDER BY rowid"
        ).fetchall()
        return tuple(
            self._decode_health_command_receipt(causal_id, nonce, ciphertext)
            for causal_id, nonce, ciphertext in rows
        )

    def _write_health_command_receipt(
        self,
        connection: sqlite3.Connection,
        receipt: HealthCommandReceipt,
    ) -> bool:
        if type(receipt) is not HealthCommandReceipt:
            raise AuthorityValidationError("health command receipt required")
        existing = self._health_command_receipt_for_causal_id(
            receipt.causal_id
        )
        if existing is not None:
            if not hmac.compare_digest(
                existing.command_digest,
                receipt.command_digest,
            ):
                raise CausalIdConflict("causal-id-conflict")
            if existing != receipt:
                raise AuthorityValidationError(
                    "health command receipt result conflict"
                )
            return False
        nonce, ciphertext = self._seal(
            self._health_command_receipt_aad(receipt.causal_id),
            receipt.to_storage(),
        )
        try:
            connection.execute(
                "INSERT INTO ticket115_health_command_receipts_v1("
                "causal_id, nonce, ciphertext) VALUES (?, ?, ?)",
                (receipt.causal_id, nonce, ciphertext),
            )
        except sqlite3.IntegrityError as exc:
            raise CausalIdConflict("causal-id-conflict") from exc
        return True

    def _write_managed_effect_intent(
        self,
        connection: sqlite3.Connection,
        effect_intent: EffectIntent,
    ) -> None:
        if type(effect_intent) is not EffectIntent:
            raise AuthorityValidationError("managed effect intent required")
        self._validate_effect_write(
            effect_intent.effect_id,
            "intent",
            effect_intent,
        )
        existing = self.effect(effect_intent.effect_id)
        if existing is not None and (
            existing.state != "intent"
            or existing.payload != effect_intent
        ):
            raise AuthorityValidationError("managed effect intent conflict")
        if existing is None:
            nonce, ciphertext = self._seal(
                f"effect:{effect_intent.effect_id}:intent",
                effect_intent.to_storage(),
            )
            connection.execute(
                "INSERT INTO effects(effect_id, state, nonce, ciphertext) "
                "VALUES (?, 'intent', ?, ?)",
                (effect_intent.effect_id, nonce, ciphertext),
            )

    def commit_managed_command_intent(
        self,
        receipt: HealthCommandReceipt,
        effect_intent: EffectIntent | None = None,
        delivery_state: DeliveryOutboxState | None = None,
    ) -> None:
        """Atomically append a managed receipt, effect, and delivery facts."""

        if type(receipt) is not HealthCommandReceipt:
            raise AuthorityValidationError("health command receipt required")
        if effect_intent is not None and type(effect_intent) is not EffectIntent:
            raise AuthorityValidationError("managed effect intent required")
        if (
            delivery_state is not None
            and type(delivery_state) is not DeliveryOutboxState
        ):
            raise AuthorityValidationError("managed delivery state required")
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            self._write_health_command_receipt(connection, receipt)
            if effect_intent is not None:
                self._write_managed_effect_intent(connection, effect_intent)
            if delivery_state is not None:
                self._commit_ticket115_facts_in_transaction(
                    connection,
                    task_state=None,
                    review_state=None,
                    delivery_state=delivery_state,
                )
            self._refresh_integrity_manifest(connection)

    def save_health_command_receipt(
        self,
        receipt: HealthCommandReceipt,
    ) -> None:
        """Persist one encrypted immutable Ticket 115 replay receipt."""

        if type(receipt) is not HealthCommandReceipt:
            raise AuthorityValidationError("health command receipt required")
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            changed = self._write_health_command_receipt(connection, receipt)
            if changed:
                self._refresh_integrity_manifest(connection)

    def pending_command(self, command: CommandEnvelope) -> PendingCommand | None:
        row = self._execute(
            "SELECT record_id, nonce, ciphertext FROM pending_commands_v1 WHERE causal_id = ?",
            (command.causal_id,),
        ).fetchone()
        if row is None:
            return None
        pending = self._decode_pending(command.causal_id, row[0], row[1], row[2])
        if pending.command.to_wire() != command.to_wire():
            raise CausalIdConflict("causal-id-conflict")
        return pending

    def pending_for_record(self, record_id: str) -> PendingCommand | None:
        row = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM pending_commands_v1 WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return self._decode_pending(row[0], record_id, row[1], row[2])

    def has_pending_causal_id(self, causal_id: str) -> bool:
        return (
            self._execute(
                "SELECT 1 FROM pending_commands_v1 WHERE causal_id = ?",
                (causal_id,),
            ).fetchone()
            is not None
            or self._execute(
                "SELECT 1 FROM pending_effect_results_v1 WHERE causal_id = ?",
                (causal_id,),
            ).fetchone()
            is not None
        )

    def has_pending_commands(self) -> bool:
        return (
            self._execute("SELECT 1 FROM pending_commands_v1 LIMIT 1").fetchone()
            is not None
        )

    def pending_effect_result(self, effect_id: str) -> PendingEffectResult | None:
        row = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM pending_effect_results_v1 WHERE effect_id = ?",
            (effect_id,),
        ).fetchone()
        if row is None:
            return None
        return self._decode_pending_effect_result(effect_id, row[0], row[1], row[2])

    def reserve_pending_effect_result(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
    ) -> PendingEffectResult:
        """Give one exact effect terminal command durable recovery ownership."""

        attempt = PendingEffectResult.from_command(command, execution, remote_attempted=False)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            existing = self.pending_effect_result(attempt.effect_id)
            if existing is not None:
                if not existing.matches(command, execution):
                    raise CausalIdConflict("causal-id-conflict")
                return existing
            nonce, ciphertext = self._seal(
                f"pending-effect:{attempt.effect_id}",
                attempt.to_storage(),
            )
            try:
                connection.execute(
                    "INSERT INTO pending_effect_results_v1(effect_id, causal_id, nonce, ciphertext) VALUES (?, ?, ?, ?)",
                    (attempt.effect_id, attempt.causal_id, nonce, ciphertext),
                )
            except sqlite3.IntegrityError as exc:
                raise CausalIdConflict("causal-id-conflict") from exc
            self._refresh_integrity_manifest(connection)
        return attempt

    def mark_pending_effect_result_attempted(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
    ) -> PendingEffectResult:
        """Record that the exact owner is entering the remote release phase."""

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            pending = self.pending_effect_result(execution.intent.effect_id)
            if pending is None:
                raise KeyUnavailable("pending effect result missing")
            if not pending.matches(command, execution):
                raise CausalIdConflict("causal-id-conflict")
            if pending.remote_attempted:
                return pending
            attempted = PendingEffectResult.from_command(command, execution, remote_attempted=True)
            nonce, ciphertext = self._seal(
                f"pending-effect:{attempted.effect_id}",
                attempted.to_storage(),
            )
            connection.execute(
                "UPDATE pending_effect_results_v1 SET nonce = ?, ciphertext = ? WHERE effect_id = ?",
                (nonce, ciphertext, attempted.effect_id),
            )
            self._refresh_integrity_manifest(connection)
            return attempted

    def clear_unattempted_pending_effect_result(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
    ) -> bool:
        """Release only an exact effect owner that never reached remote release."""

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            pending = self.pending_effect_result(execution.intent.effect_id)
            if pending is None:
                return False
            if not pending.matches(command, execution):
                raise CausalIdConflict("causal-id-conflict")
            if pending.remote_attempted:
                return False
            connection.execute(
                "DELETE FROM pending_effect_results_v1 WHERE effect_id = ?",
                (execution.intent.effect_id,),
            )
            self._refresh_integrity_manifest(connection)
            return True

    def clear_pending_effect_result(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
    ) -> None:
        """Delete only the exact owner whose terminal result was committed."""

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            pending = self.pending_effect_result(execution.intent.effect_id)
            if pending is None:
                raise KeyUnavailable("pending effect result missing")
            if not pending.matches(command, execution):
                raise CausalIdConflict("causal-id-conflict")
            connection.execute(
                "DELETE FROM pending_effect_results_v1 WHERE effect_id = ?",
                (execution.intent.effect_id,),
            )
            self._refresh_integrity_manifest(connection)

    def reserve_pending_commit(self, command: CommandEnvelope, expected: PreparedTransition) -> bool:
        """Atomically reserve a still-prepared revision for one commit command.

        The caller has already read current-head and proved it equals
        ``expected.base``.  This SQLite transaction repeats the local record and
        pending checks immediately before insertion, preventing a second core
        process from inserting an orphan journal after another process finalizes
        the same record.
        """

        if not isinstance(expected, PreparedTransition):
            raise AuthorityValidationError("invalid pending commit preparation")
        payload = command.payload
        if not isinstance(payload, StateCommitPayload):
            raise ProtocolViolation("invalid commit payload")
        if (
            not expected.target.matches_commit(
                record_id=payload.record_id,
                revision_digest=payload.revision_digest,
                transition_id=payload.transition_id,
            )
            or command.generation != expected.base.generation
            or payload.writer_fence != expected.base.writer_fence
        ):
            raise ProtocolViolation("invalid pending commit target")
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            current = self.record(payload.record_id)
            if current is None or current.state != "prepared" or current.payload != expected:
                return False
            pending = self.pending_for_record(payload.record_id)
            if pending is not None:
                if pending.command.to_wire() != command.to_wire():
                    raise CausalIdConflict("causal-id-conflict")
                return True
            nonce, ciphertext = self._seal(
                f"pending:{command.causal_id}",
                {
                    "record_id": payload.record_id,
                    "command": command.to_wire(),
                    "remote_attempted": False,
                },
            )
            try:
                connection.execute(
                    "INSERT INTO pending_commands_v1(causal_id, record_id, nonce, ciphertext) VALUES (?, ?, ?, ?)",
                    (command.causal_id, payload.record_id, nonce, ciphertext),
                )
            except sqlite3.IntegrityError as exc:
                prior = self.pending_command(command)
                if prior is None or prior.record_id != payload.record_id:
                    raise CausalIdConflict("causal-id-conflict") from exc
            self._refresh_integrity_manifest(connection)
            return True

    def mark_pending_remote_attempted(self, command: CommandEnvelope) -> None:
        """Atomically mark the exact journal after its final pre-CAS read.

        Recovery may only treat a journal as ambiguous once this marker has
        committed.  An unattempted reservation is safe to discard when the
        second current-head read proves the prepared authority already stale.
        """

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            pending = self.pending_command(command)
            if pending is None:
                raise KeyUnavailable("pending command missing")
            if pending.remote_attempted:
                return
            nonce, ciphertext = self._seal(
                f"pending:{command.causal_id}",
                {
                    "record_id": pending.record_id,
                    "command": command.to_wire(),
                    "remote_attempted": True,
                },
            )
            connection.execute(
                "UPDATE pending_commands_v1 SET nonce = ?, ciphertext = ? WHERE causal_id = ?",
                (nonce, ciphertext, command.causal_id),
            )
            self._refresh_integrity_manifest(connection)

    def clear_unattempted_pending_command(self, command: CommandEnvelope) -> bool:
        """Discard only a definitely unattempted exact causal reservation."""

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            pending = self.pending_command(command)
            if pending is None:
                return False
            if pending.remote_attempted:
                return False
            connection.execute("DELETE FROM pending_commands_v1 WHERE causal_id = ?", (command.causal_id,))
            self._refresh_integrity_manifest(connection)
            return True

    def write_pending_command(
        self,
        command: CommandEnvelope,
        record_id: str,
        *,
        remote_attempted: bool = False,
    ) -> None:
        if not isinstance(remote_attempted, bool):
            raise AuthorityValidationError("invalid pending command phase")
        nonce, ciphertext = self._seal(
            f"pending:{command.causal_id}",
            {
                "record_id": record_id,
                "command": command.to_wire(),
                "remote_attempted": remote_attempted,
            },
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            try:
                connection.execute(
                    "INSERT INTO pending_commands_v1(causal_id, record_id, nonce, ciphertext) VALUES (?, ?, ?, ?)",
                    (command.causal_id, record_id, nonce, ciphertext),
                )
            except sqlite3.IntegrityError as exc:
                prior = self.pending_command(command)
                if prior is None or prior.record_id != record_id:
                    raise CausalIdConflict("causal-id-conflict") from exc
            self._refresh_integrity_manifest(connection)

    def clear_pending_command(self, causal_id: str) -> None:
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            connection.execute("DELETE FROM pending_commands_v1 WHERE causal_id = ?", (causal_id,))
            self._refresh_integrity_manifest(connection)

    def save_receipt(self, command: CommandEnvelope, response: Response) -> None:
        """Persist an exact replay response inside the caller's transaction."""

        if response.causal_id != command.causal_id:
            raise KeyUnavailable("receipt causal identifier mismatch")
        content = (
            {
                "kind": "command-digest-v1",
                "command_digest": self._receipt_command_digest(command),
                "response": response.to_wire(),
            }
            if (
                command.action == "turn.prepare"
                and isinstance(command.payload, DailyTurnPreparePayload)
            )
            or (
                command.action == "owner.prepare"
                and isinstance(command.payload, OwnerPreparePayload)
            )
            else {
                "command": self._receipt_command_wire(command),
                "response": response.to_wire(),
            }
        )
        nonce, ciphertext = self._seal(
            f"receipt:v2:{command.causal_id}",
            content,
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            try:
                connection.execute(
                    "INSERT INTO command_receipts_v2(causal_id, nonce, ciphertext) VALUES (?, ?, ?)",
                    (command.causal_id, nonce, ciphertext),
                )
            except sqlite3.IntegrityError as exc:
                prior = self.receipt(command)
                if prior is None:
                    raise KeyUnavailable("receipt write conflict") from exc
                if prior.to_wire() != response.to_wire():
                    raise CausalIdConflict("causal-id-conflict") from exc
            self._refresh_integrity_manifest(connection)

    def save_initialization_disclosure_challenge(
        self,
        challenge: InitializationDisclosureChallenge,
    ) -> None:
        """Persist a pre-consent challenge before its owner source may exist."""

        if type(challenge) is not InitializationDisclosureChallenge:
            raise AuthorityValidationError("invalid initialization disclosure challenge")
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            if self.source_receipt(challenge.admission_causal_id) is not None:
                raise AuthorityValidationError(
                    "initialization-disclosure-before-consent-required"
                )
            rows = connection.execute(
                "SELECT disclosure_id, workflow_id, admission_causal_id, nonce, ciphertext "
                "FROM initialization_disclosure_challenges_v1 "
                "WHERE disclosure_id = ? OR workflow_id = ? OR admission_causal_id = ?",
                (
                    challenge.disclosure_id,
                    challenge.workflow_id,
                    challenge.admission_causal_id,
                ),
            ).fetchall()
            if rows:
                if len(rows) == 1 and self._decode_initialization_disclosure_challenge(
                    *rows[0]
                ) == challenge:
                    return
                raise AuthorityValidationError("health-init workflow conflict")
            nonce, ciphertext = self._seal(
                f"initialization-disclosure:{challenge.disclosure_id}",
                challenge.to_storage(),
            )
            connection.execute(
                "INSERT INTO initialization_disclosure_challenges_v1("
                "disclosure_id, workflow_id, admission_causal_id, nonce, ciphertext"
                ") VALUES (?, ?, ?, ?, ?)",
                (
                    challenge.disclosure_id,
                    challenge.workflow_id,
                    challenge.admission_causal_id,
                    nonce,
                    ciphertext,
                ),
            )
            self._refresh_integrity_manifest(connection)

    def initialization_disclosure_challenge(
        self,
        disclosure_id: str,
    ) -> InitializationDisclosureChallenge | None:
        validate_opaque_text(disclosure_id, "initialization disclosure identifier")
        row = self._execute(
            "SELECT disclosure_id, workflow_id, admission_causal_id, nonce, ciphertext "
            "FROM initialization_disclosure_challenges_v1 WHERE disclosure_id = ?",
            (disclosure_id,),
        ).fetchone()
        return (
            None
            if row is None
            else self._decode_initialization_disclosure_challenge(*row)
        )

    def initialization_disclosure_for_workflow(
        self,
        workflow_id: str,
    ) -> InitializationDisclosureChallenge | None:
        validate_opaque_text(workflow_id, "initialization workflow identifier")
        row = self._execute(
            "SELECT disclosure_id, workflow_id, admission_causal_id, nonce, ciphertext "
            "FROM initialization_disclosure_challenges_v1 WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()
        return (
            None
            if row is None
            else self._decode_initialization_disclosure_challenge(*row)
        )

    def _decode_initialization_disclosure_challenge(
        self,
        disclosure_id: object,
        workflow_id: object,
        admission_causal_id: object,
        nonce: object,
        ciphertext: object,
    ) -> InitializationDisclosureChallenge:
        if not all(
            type(value) is str and value
            for value in (disclosure_id, workflow_id, admission_causal_id)
        ):
            raise KeyUnavailable("invalid initialization disclosure challenge")
        try:
            challenge = InitializationDisclosureChallenge.from_storage(
                self._open(
                    f"initialization-disclosure:{disclosure_id}",
                    nonce,  # type: ignore[arg-type]
                    ciphertext,  # type: ignore[arg-type]
                )
            )
        except AuthorityValidationError as exc:
            raise KeyUnavailable("invalid initialization disclosure challenge") from exc
        if (
            challenge.disclosure_id != disclosure_id
            or challenge.workflow_id != workflow_id
            or challenge.admission_causal_id != admission_causal_id
        ):
            raise KeyUnavailable("initialization disclosure challenge mismatch")
        return challenge

    def clear_initialization_disclosure_challenges(self) -> None:
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            cursor = connection.execute(
                "DELETE FROM initialization_disclosure_challenges_v1"
            )
            if cursor.rowcount:
                self._refresh_integrity_manifest(connection)

    def save_source_envelope(
        self,
        envelope: SourceEnvelope,
        *,
        confirm_native_replay: bool = False,
        retain_body: bool = True,
    ) -> SourceReceipt:
        """Persist one admitted source observation inside the caller transaction."""

        if type(envelope) is not SourceEnvelope:
            raise AuthorityValidationError("invalid source envelope")
        if type(confirm_native_replay) is not bool:
            raise AuthorityValidationError("invalid native replay policy")
        if type(retain_body) is not bool:
            raise AuthorityValidationError("invalid source body retention policy")
        native_event_digest = (
            None
            if envelope.message_id is None
            else self._native_event_digest(envelope)
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            same_causal = self.source_receipt(envelope.causal_id)
            if same_causal is not None:
                if not same_causal.matches_exact_delivery(
                    envelope,
                    native_event_digest,
                ):
                    raise CausalIdConflict("causal-id-conflict")
                return same_causal
            related_causal_id = None
            related_receipt = None
            if envelope.message_id is not None:
                rows = connection.execute(
                    "SELECT causal_id, nonce, ciphertext FROM source_envelopes_v1 ORDER BY rowid"
                ).fetchall()
                for causal_id, existing_nonce, existing_ciphertext in rows:
                    existing_receipt = SourceReceipt.from_storage(
                        self._open(
                            f"source-envelope:{causal_id}",
                            existing_nonce,
                            existing_ciphertext,
                        )
                    )
                    existing = existing_receipt.envelope
                    if (
                        existing.channel == envelope.channel
                        and existing.partner_id == envelope.partner_id
                        and existing.sender_id == envelope.sender_id
                        and existing.conversation_id == envelope.conversation_id
                        and existing.message_id == envelope.message_id
                    ):
                        related_causal_id = causal_id
                        related_receipt = existing_receipt
                        break
            business_source_causal_id = None
            if (
                confirm_native_replay
                and related_receipt is not None
                and related_receipt.native_event_digest is not None
                and native_event_digest is not None
                and hmac.compare_digest(
                    related_receipt.native_event_digest,
                    native_event_digest,
                )
            ):
                business_source_causal_id = related_receipt.business_causal_id
            if (
                business_source_causal_id is not None
                and related_receipt is not None
                and related_receipt.managed_cursor_state == "recording-excluded"
            ):
                # Exclusion is a property of the proven native event, not of
                # one delivery-local causal ID.  Never create a durable held
                # plaintext alias after recording resumes.
                retain_body = False
            receipt = SourceReceipt(
                envelope=(envelope if retain_body else envelope.without_body()),
                relation=(
                    "replay-unknown"
                    if envelope.message_id is None
                    else "first-observation"
                    if related_causal_id is None
                    else "possible-replay"
                ),
                related_causal_id=related_causal_id,
                managed_cursor_state=(
                    "held" if retain_body else "recording-excluded"
                ),
                native_cursor_state="not-ready",
                native_event_digest=native_event_digest,
                business_source_causal_id=business_source_causal_id,
            )
            nonce, ciphertext = self._seal(
                f"source-envelope:{envelope.causal_id}",
                receipt.to_storage(),
            )
            connection.execute(
                "INSERT INTO source_envelopes_v1(causal_id, nonce, ciphertext) VALUES (?, ?, ?)",
                (envelope.causal_id, nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)
            return receipt

    def source_receipt_matches_exact_delivery(
        self,
        receipt: SourceReceipt,
        envelope: SourceEnvelope,
    ) -> bool:
        if type(receipt) is not SourceReceipt or type(envelope) is not SourceEnvelope:
            return False
        digest = (
            None
            if envelope.message_id is None or type(envelope.body) is not str
            else self._native_event_digest(envelope)
        )
        return receipt.matches_exact_delivery(envelope, digest)

    def _native_event_digest(self, envelope: SourceEnvelope) -> str:
        """Produce the long-lived, domain-separated keyed native fingerprint."""

        if type(envelope) is not SourceEnvelope:
            raise AuthorityValidationError("invalid source envelope")
        try:
            canonical = json.dumps(
                envelope.native_event_fingerprint_material,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            master_key = self._key_provider.get_key()
        except (
            TypeError,
            ValueError,
            UnicodeEncodeError,
            RecursionError,
        ) as exc:
            raise KeyUnavailable("native event fingerprint unavailable") from exc
        except Exception as exc:
            raise KeyUnavailable("health key unavailable") from exc
        if not isinstance(master_key, bytes) or len(master_key) not in {16, 24, 32}:
            raise KeyUnavailable("health key invalid")
        digest_key = hmac.new(
            master_key,
            b"partner-health-steward/native-event-digest-key/v1",
            hashlib.sha256,
        ).digest()
        digest = hmac.new(
            digest_key,
            b"partner-health-steward/native-event/v1\x00" + canonical,
            hashlib.sha256,
        ).hexdigest()
        return "hmac-sha256:" + digest

    def source_envelope(self, causal_id: str) -> SourceEnvelope | None:
        receipt = self.source_receipt(causal_id)
        return None if receipt is None else receipt.envelope

    def source_receipt(self, causal_id: str) -> SourceReceipt | None:
        validate_opaque_text(causal_id, "causal_id")
        row = self._execute(
            "SELECT nonce, ciphertext FROM source_envelopes_v1 WHERE causal_id = ?",
            (causal_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            receipt = SourceReceipt.from_storage(
                self._open(f"source-envelope:{causal_id}", row[0], row[1])
            )
        except AuthorityValidationError as exc:
            raise KeyUnavailable("invalid source receipt") from exc
        if receipt.envelope.causal_id != causal_id:
            raise KeyUnavailable("source envelope causal identifier mismatch")
        return receipt

    def held_source_receipts(self) -> tuple[SourceReceipt, ...]:
        """Return every unresolved admitted source in stable arrival order."""

        rows = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM source_envelopes_v1 ORDER BY rowid"
        ).fetchall()
        held: list[SourceReceipt] = []
        for causal_id, nonce, ciphertext in rows:
            try:
                receipt = SourceReceipt.from_storage(
                    self._open(f"source-envelope:{causal_id}", nonce, ciphertext)
                )
            except AuthorityValidationError as exc:
                raise KeyUnavailable("invalid source receipt") from exc
            if receipt.envelope.causal_id != causal_id:
                raise KeyUnavailable("source envelope causal identifier mismatch")
            if receipt.managed_cursor_state in {"held", "superseded"}:
                held.append(receipt)
        return tuple(held)

    def supersede_initialization_resolution_source(
        self,
        causal_id: str,
    ) -> SourceReceipt:
        """Retire one stale resolution slot without advancing either cursor."""

        receipt = self.source_receipt(causal_id)
        if receipt is None:
            raise AuthorityValidationError("initialization source required")
        return self._replace_source_receipt(
            receipt.with_resolution_superseded()
        )

    def reject_source_native_replay(self, causal_id: str) -> SourceReceipt:
        """Clear an unprovable/conflicting native body without releasing cursor."""

        receipt = self.source_receipt(causal_id)
        if receipt is None:
            raise AuthorityValidationError("unresolved native replay required")
        if receipt.managed_cursor_state == "rejected":
            return receipt
        return self._replace_source_receipt(
            receipt.with_native_replay_rejected()
        )

    def reject_source_recording(self, causal_id: str) -> SourceReceipt:
        """Remove a stopped-recording source body while keeping replay proof."""

        receipt = self.source_receipt(causal_id)
        if receipt is None:
            raise AuthorityValidationError("recording source required")
        return self._replace_source_receipt(receipt.with_recording_rejected())

    def mark_source_business_committed(self, causal_id: str) -> SourceReceipt:
        return self.mark_source_business_committed_many((causal_id,))[0]

    def mark_daily_source_family_business_committed(
        self,
        business_source_causal_id: str,
    ) -> tuple[SourceReceipt, ...]:
        """Release one canonical daily source and every proven native alias."""

        validate_opaque_text(
            business_source_causal_id,
            "business_source_causal_id",
        )
        rows = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM source_envelopes_v1 "
            "ORDER BY rowid"
        ).fetchall()
        causal_ids: list[str] = []
        for causal_id, nonce, ciphertext in rows:
            try:
                receipt = SourceReceipt.from_storage(
                    self._open(f"source-envelope:{causal_id}", nonce, ciphertext)
                )
            except AuthorityValidationError as exc:
                raise KeyUnavailable("invalid source receipt") from exc
            if (
                causal_id == business_source_causal_id
                or receipt.business_source_causal_id
                == business_source_causal_id
            ):
                causal_ids.append(causal_id)
        if business_source_causal_id not in causal_ids:
            raise AuthorityValidationError("daily source required")
        return self.mark_source_business_committed_many(tuple(causal_ids))

    def mark_source_business_committed_many(
        self,
        causal_ids: tuple[str, ...],
    ) -> tuple[SourceReceipt, ...]:
        """Clear and release one frozen initialization source set atomically."""

        if type(causal_ids) is not tuple or not causal_ids:
            raise AuthorityValidationError("initialization source required")
        validated = tuple(validate_opaque_text(item, "causal_id") for item in causal_ids)
        if validated != causal_ids or len(set(validated)) != len(validated):
            raise AuthorityValidationError("invalid initialization source set")
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            committed: list[SourceReceipt] = []
            for causal_id in validated:
                receipt = self.source_receipt(causal_id)
                if receipt is None:
                    raise AuthorityValidationError("initialization source required")
                replacement = (
                    receipt
                    if receipt.managed_cursor_state == "committed"
                    else receipt.with_business_committed()
                )
                if replacement != receipt:
                    nonce, ciphertext = self._seal(
                        f"source-envelope:{causal_id}",
                        replacement.to_storage(),
                    )
                    cursor = connection.execute(
                        "UPDATE source_envelopes_v1 SET nonce = ?, ciphertext = ? "
                        "WHERE causal_id = ?",
                        (nonce, ciphertext, causal_id),
                    )
                    if cursor.rowcount != 1:
                        raise AuthorityValidationError("initialization source required")
                committed.append(replacement)
            self._refresh_integrity_manifest(connection)
        return tuple(committed)

    def mark_native_cursor_state(self, causal_id: str, state: str) -> SourceReceipt:
        receipt = self.source_receipt(causal_id)
        if receipt is None or receipt.managed_cursor_state != "committed":
            raise AuthorityValidationError("native cursor is not ready")
        if state not in {"executing", "advanced", "unknown"}:
            raise AuthorityValidationError("invalid native cursor result")
        if receipt.native_cursor_state == state:
            return receipt
        expected = "ready" if state == "executing" else "executing"
        if receipt.native_cursor_state != expected:
            raise AuthorityValidationError("native cursor result is terminal")
        return self._replace_source_receipt(receipt.with_native_cursor_state(state))

    def _replace_source_receipt(self, receipt: SourceReceipt) -> SourceReceipt:
        causal_id = receipt.envelope.causal_id
        nonce, ciphertext = self._seal(
            f"source-envelope:{causal_id}",
            receipt.to_storage(),
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            cursor = connection.execute(
                "UPDATE source_envelopes_v1 SET nonce = ?, ciphertext = ? WHERE causal_id = ?",
                (nonce, ciphertext, causal_id),
            )
            if cursor.rowcount != 1:
                raise AuthorityValidationError("initialization source required")
            if receipt.native_cursor_state == "advanced":
                row = connection.execute(
                    "SELECT source_causal_id, record_id, phase, nonce, ciphertext "
                    "FROM daily_turns_v1 WHERE source_causal_id = ?",
                    (causal_id,),
                ).fetchone()
                if row is not None:
                    turn = self._decode_daily_turn(*row)
                    if turn.phase == "finalized" and turn.result is not None:
                        self._write_daily_turn_terminal_row(
                            connection,
                            turn._terminal(),
                            None,
                        )
            self._refresh_integrity_manifest(connection)
        return receipt

    def write_initialization(self, phase: str, draft: InitializationDraft) -> None:
        """Create or advance the singleton initialization aggregate.

        Callers normally hold the outer command transaction.  Nested store
        transactions deliberately share that transaction, so the aggregate,
        generic transition record, and command receipt commit or roll back as
        one unit.
        """

        if phase not in {"prepared", "committed", "unknown", "enabled"}:
            raise AuthorityValidationError("invalid initialization phase")
        if type(draft) is not InitializationDraft:
            raise AuthorityValidationError("invalid initialization draft")
        nonce, ciphertext = self._seal(
            f"owner-initialization:{draft.record_id}:{phase}",
            draft.to_storage(),
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            existing = connection.execute(
                "SELECT record_id, phase, nonce, ciphertext "
                "FROM owner_initialization_v1 WHERE slot = 1"
            ).fetchone()
            if existing is not None:
                current = self._decode_initialization(*existing)
                if current.draft != draft:
                    raise AuthorityValidationError("initialization already exists")
                allowed = {
                    "prepared": {"prepared", "unknown", "committed"},
                    "unknown": {"unknown", "prepared", "committed"},
                    "committed": {"committed", "enabled"},
                    "enabled": {"enabled"},
                }
                if phase not in allowed[current.phase]:
                    raise AuthorityValidationError("invalid initialization transition")
            connection.execute(
                """
                INSERT INTO owner_initialization_v1(slot, record_id, phase, nonce, ciphertext)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(slot) DO UPDATE SET
                    record_id=excluded.record_id,
                    phase=excluded.phase,
                    nonce=excluded.nonce,
                    ciphertext=excluded.ciphertext
                """,
                (draft.record_id, phase, nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    def initialization(self) -> StoredInitialization | None:
        row = self._execute(
            "SELECT record_id, phase, nonce, ciphertext "
            "FROM owner_initialization_v1 WHERE slot = 1"
        ).fetchone()
        return None if row is None else self._decode_initialization(*row)

    def _decode_initialization(
        self,
        record_id: object,
        phase: object,
        nonce: object,
        ciphertext: object,
    ) -> StoredInitialization:
        if type(record_id) is not str or not record_id:
            raise KeyUnavailable("invalid initialization record identifier")
        if type(phase) is not str or phase not in {"prepared", "committed", "unknown", "enabled"}:
            raise KeyUnavailable("invalid initialization phase")
        try:
            draft = InitializationDraft.from_storage(
                self._open(
                    f"owner-initialization:{record_id}:{phase}",
                    nonce,
                    ciphertext,
                )
            )
        except AuthorityValidationError as exc:
            raise KeyUnavailable("invalid initialization aggregate") from exc
        if draft.record_id != record_id:
            raise KeyUnavailable("initialization record identifier mismatch")
        return StoredInitialization(phase=phase, draft=draft)

    def business_status_projection(self) -> StatusProjection | None:
        """Return the last owner-visible business projection, if observed."""

        row = self._execute(
            "SELECT nonce, ciphertext FROM business_status_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            return None
        try:
            return StatusProjection.from_storage(
                self._open("business-status", row[0], row[1])
            )
        except StatusContractViolation as exc:
            raise KeyUnavailable("invalid business status projection") from exc

    def _business_status_projection_in_connection(
        self,
        connection: sqlite3.Connection,
    ) -> StatusProjection | None:
        row = connection.execute(
            "SELECT nonce, ciphertext FROM business_status_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            return None
        try:
            return StatusProjection.from_storage(
                self._open("business-status", row[0], row[1])
            )
        except StatusContractViolation as exc:
            raise KeyUnavailable("invalid business status projection") from exc

    def _write_business_status_in_transaction(
        self,
        connection: sqlite3.Connection,
        projection: StatusProjection,
    ) -> StatusProjection | None:
        if type(projection) is not StatusProjection:
            raise AuthorityValidationError("invalid business status projection")
        previous = self._business_status_projection_in_connection(connection)
        if previous == projection:
            return previous
        nonce, ciphertext = self._seal(
            "business-status",
            projection.to_storage(),
        )
        connection.execute(
            """
            INSERT INTO business_status_v1(slot, nonce, ciphertext)
            VALUES (1, ?, ?)
            ON CONFLICT(slot) DO UPDATE SET
                nonce=excluded.nonce,
                ciphertext=excluded.ciphertext
            """,
            (nonce, ciphertext),
        )
        return previous

    def remember_business_status(
        self,
        projection: StatusProjection,
    ) -> StatusProjection | None:
        """Atomically replace the projection and return its durable predecessor.

        Returning the predecessor from the same transaction lets core decide
        whether this exact read owns a state-change notification.  A concurrent
        or restarted replay sees the newly stored projection and therefore
        cannot emit that transition a second time.
        """

        if type(projection) is not StatusProjection:
            raise AuthorityValidationError("invalid business status projection")
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            previous = self._write_business_status_in_transaction(
                connection,
                projection,
            )
            self._refresh_integrity_manifest(connection)
            return previous

    @staticmethod
    def _task_runtime_wire(state: object) -> dict[str, object]:
        from .tasking import TaskRuntimeState

        if type(state) is not TaskRuntimeState:
            raise AuthorityValidationError("invalid task runtime aggregate")
        return state.to_storage()

    @staticmethod
    def _task_runtime_from_wire(value: object) -> object:
        from .tasking import TaskRuntimeState

        try:
            return TaskRuntimeState.from_storage(value)
        except (TypeError, ValueError) as exc:
            raise KeyUnavailable("invalid task runtime aggregate") from exc

    def task_runtime(self) -> object | None:
        row = self._execute(
            "SELECT nonce, ciphertext FROM task_runtime_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            return None
        try:
            wire = self._open("task-runtime:v1", row[0], row[1])
            state = self._task_runtime_from_wire(wire)
        except (ImportError, TypeError, ValueError) as exc:
            raise KeyUnavailable("invalid task runtime aggregate") from exc
        if self._task_runtime_wire(state) != wire:
            raise KeyUnavailable("task runtime round-trip mismatch")
        return state

    @staticmethod
    def _daily_review_ledger_wire(ledger: object) -> dict[str, object]:
        from .review import DailyReviewLedger

        if type(ledger) is not DailyReviewLedger:
            raise AuthorityValidationError("invalid daily review ledger")
        return ledger.to_storage()

    @staticmethod
    def _daily_review_ledger_from_wire(value: object) -> object:
        from .review import DailyReviewLedger

        try:
            return DailyReviewLedger.from_storage(value)
        except (TypeError, ValueError) as exc:
            raise KeyUnavailable("invalid daily review ledger") from exc

    def daily_review_ledger(self) -> object | None:
        row = self._execute(
            "SELECT nonce, ciphertext FROM daily_reviews_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            return None
        wire = self._open(
            "daily-review-ledger:v1",
            row[0],
            row[1],
        )
        ledger = self._daily_review_ledger_from_wire(wire)
        if self._daily_review_ledger_wire(ledger) != wire:
            raise KeyUnavailable("daily review ledger round-trip mismatch")
        return ledger

    def daily_review(self, review_key: str) -> object | None:
        validate_opaque_text(review_key, "daily review key")
        ledger = self.daily_review_ledger()
        if ledger is None:
            return None
        for record in ledger.completed:
            if record.key.value == review_key:
                return record
        if ledger.pending is not None and ledger.pending.key.value == review_key:
            return ledger.pending
        return None

    @staticmethod
    def _delivery_phase(record: object) -> str:
        from .delivery import OutboxRecord

        if type(record) is not OutboxRecord:
            raise AuthorityValidationError("invalid owner outbox record")
        if any(
            record.has_fact(kind)
            for kind in (
                "accepted",
                "rejected",
                "delivered",
                "read",
                "unknown",
            )
        ):
            return "terminal"
        if record.has_fact("attempted"):
            return "executing"
        if record.leases:
            return "claiming"
        return "committed"

    @staticmethod
    def _delivery_observation_id(intent_id: str, layer: str) -> str:
        return (
            "delivery-observation:"
            + stable_digest(
                {"intent_id": intent_id, "layer": layer}
            ).removeprefix("sha256:")
        )

    def delivery_outbox_state(
        self,
        owner_id: str,
        installation_id: str,
    ) -> object:
        from .delivery import (
            DELIVERY_FACT_KINDS,
            DeliveryFact,
            DeliveryLease,
            DeliveryOutboxState,
            OutboxIntent,
            OutboxRecord,
        )

        validate_opaque_text(owner_id, "delivery owner")
        validate_opaque_text(installation_id, "delivery installation")
        rows = self._execute(
            "SELECT intent_id, state_version, phase, nonce, ciphertext "
            "FROM owner_outbox_v1 ORDER BY intent_id"
        ).fetchall()
        if not rows:
            if self._execute(
                "SELECT 1 FROM owner_delivery_observations_v1 LIMIT 1"
            ).fetchone() is not None:
                raise KeyUnavailable("delivery observation has no outbox intent")
            return DeliveryOutboxState.empty(owner_id, installation_id)
        versions: set[int] = set()
        records: list[OutboxRecord] = []
        fact_order = {
            kind: index for index, kind in enumerate(DELIVERY_FACT_KINDS)
        }
        for intent_id, state_version, phase, nonce, ciphertext in rows:
            if (
                type(intent_id) is not str
                or type(state_version) is not int
                or state_version < 1
                or phase
                not in {"committed", "claiming", "executing", "terminal"}
            ):
                raise KeyUnavailable("invalid owner outbox row")
            versions.add(state_version)
            value = _strict_storage_mapping(
                self._open(
                    f"owner-outbox:{intent_id}:{phase}",
                    nonce,
                    ciphertext,
                ),
                frozenset({"intent", "leases"}),
                "owner outbox record",
            )
            try:
                intent = OutboxIntent.from_wire(value["intent"])
                leases = tuple(
                    DeliveryLease.from_wire(item)
                    for item in _strict_storage_list(
                        value["leases"], "delivery leases"
                    )
                )
            except (TypeError, ValueError) as exc:
                raise KeyUnavailable("invalid owner outbox record") from exc
            if (
                intent.to_wire() != value["intent"]
                or [lease.to_wire() for lease in leases] != value["leases"]
            ):
                raise KeyUnavailable("owner outbox round-trip mismatch")
            if (
                intent.intent_id != intent_id
                or intent.owner_id != owner_id
                or intent.installation_id != installation_id
            ):
                raise KeyUnavailable("owner outbox authority mismatch")
            fact_rows = self._execute(
                "SELECT observation_id, layer, nonce, ciphertext "
                "FROM owner_delivery_observations_v1 "
                "WHERE intent_id = ? ORDER BY observation_id",
                (intent_id,),
            ).fetchall()
            facts: list[DeliveryFact] = []
            for observation_id, layer, fact_nonce, fact_ciphertext in fact_rows:
                if type(layer) is not str or layer not in fact_order:
                    raise KeyUnavailable("invalid delivery observation layer")
                expected_id = self._delivery_observation_id(intent_id, layer)
                if observation_id != expected_id:
                    raise KeyUnavailable("delivery observation identifier mismatch")
                try:
                    fact_wire = self._open(
                        f"owner-delivery-observation:{observation_id}:"
                        f"{intent_id}:{layer}",
                        fact_nonce,
                        fact_ciphertext,
                    )
                    fact = DeliveryFact.from_wire(
                        fact_wire
                    )
                except (TypeError, ValueError) as exc:
                    raise KeyUnavailable(
                        "invalid delivery observation"
                    ) from exc
                if fact.kind != layer:
                    raise KeyUnavailable("delivery observation layer mismatch")
                if fact.to_wire() != fact_wire:
                    raise KeyUnavailable(
                        "delivery observation round-trip mismatch"
                    )
                facts.append(fact)
            facts.sort(key=lambda fact: fact_order[fact.kind])
            try:
                record = OutboxRecord(
                    intent=intent,
                    facts=tuple(facts),
                    leases=leases,
                )
            except (TypeError, ValueError) as exc:
                raise KeyUnavailable("invalid owner outbox record") from exc
            if self._delivery_phase(record) != phase:
                raise KeyUnavailable("owner outbox phase mismatch")
            records.append(record)
        if len(versions) != 1:
            raise KeyUnavailable("owner outbox version mismatch")
        version = next(iter(versions))
        try:
            return DeliveryOutboxState(
                owner_id=owner_id,
                installation_id=installation_id,
                version=version,
                records=tuple(records),
            )
        except (TypeError, ValueError) as exc:
            raise KeyUnavailable("invalid delivery outbox aggregate") from exc

    def _write_task_runtime(
        self,
        connection: sqlite3.Connection,
        state: object,
    ) -> None:
        current = self.task_runtime()
        if current == state:
            return
        if current is not None and (
            current.owner_id != state.owner_id
            or current.installation_id != state.installation_id
            or state.version != current.version + 1
        ):
            raise AuthorityValidationError("stale task runtime version")
        if current is None and state.version not in {0, 1}:
            raise AuthorityValidationError("invalid initial task runtime version")
        nonce, ciphertext = self._seal(
            "task-runtime:v1",
            self._task_runtime_wire(state),
        )
        connection.execute(
            "INSERT INTO task_runtime_v1(slot, nonce, ciphertext) "
            "VALUES (1, ?, ?) "
            "ON CONFLICT(slot) DO UPDATE SET "
            "nonce=excluded.nonce, ciphertext=excluded.ciphertext",
            (nonce, ciphertext),
        )

    def _ticket115_states(
        self,
        owner_id: str,
        installation_id: str,
    ) -> tuple[TaskRuntimeState, DailyReviewLedger, DeliveryOutboxState]:
        task_state = self.task_runtime()
        review_state = self.daily_review_ledger()
        return (
            TaskRuntimeState.empty(owner_id, installation_id)
            if task_state is None
            else task_state,
            DailyReviewLedger.empty(owner_id, installation_id)
            if review_state is None
            else review_state,
            self.delivery_outbox_state(owner_id, installation_id),
        )

    @staticmethod
    def _ticket115_state_digests(
        states: tuple[
            TaskRuntimeState,
            DailyReviewLedger,
            DeliveryOutboxState,
        ],
    ) -> tuple[str, str, str]:
        task_state, review_state, delivery_state = states
        return (
            stable_digest(task_state.to_storage()),
            stable_digest(review_state.to_storage()),
            stable_digest(delivery_state.to_wire()),
        )

    def ticket115_mutation_for_record(
        self,
        record_id: str,
    ) -> Ticket115PreparedMutation | None:
        validate_opaque_text(record_id, "ticket115 mutation record identifier")
        row = self._execute(
            "SELECT nonce, ciphertext FROM ticket115_mutations_v1 "
            "WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            mutation = Ticket115PreparedMutation.from_storage(
                self._open(
                    f"ticket115-mutation:{record_id}",
                    row[0],
                    row[1],
                )
            )
        except (AuthorityValidationError, TypeError, ValueError) as exc:
            raise KeyUnavailable("invalid ticket115 prepared mutation") from exc
        if mutation.prepared.target.record_id != record_id:
            raise KeyUnavailable("ticket115 mutation record mismatch")
        return mutation

    def pending_ticket115_mutation(self) -> Ticket115PreparedMutation | None:
        rows = self._execute(
            "SELECT record_id FROM ticket115_mutations_v1 ORDER BY slot"
        ).fetchall()
        if len(rows) > 1:
            raise KeyUnavailable("multiple ticket115 prepared mutations")
        return None if not rows else self.ticket115_mutation_for_record(rows[0][0])

    def ticket115_mutation_base_is_current(
        self,
        mutation: Ticket115PreparedMutation,
    ) -> bool:
        if type(mutation) is not Ticket115PreparedMutation:
            return False
        current = self._ticket115_states(
            mutation.owner_id,
            mutation.installation_id,
        )
        if self._ticket115_state_digests(current) != (
            mutation.base_task_digest,
            mutation.base_review_digest,
            mutation.base_delivery_digest,
        ):
            return False
        if mutation.status_projection is None:
            return True
        current_status = self.business_status_projection()
        current_status_digest = (
            None
            if current_status is None
            else stable_digest(current_status.to_storage())
        )
        return current_status_digest == mutation.base_status_digest

    def prepare_ticket115_mutation(
        self,
        mutation: Ticket115PreparedMutation,
    ) -> None:
        """Durably bind one aggregate body to its invisible prepared revision."""

        if type(mutation) is not Ticket115PreparedMutation:
            raise AuthorityValidationError("ticket115 preparation required")
        target = mutation.prepared.target
        nonce, ciphertext = self._seal(
            f"ticket115-mutation:{target.record_id}",
            mutation.to_storage(),
        )
        record_nonce, record_ciphertext = self._seal(
            f"record:{target.record_id}:prepared",
            mutation.prepared.to_storage(),
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            if self.pending_ticket115_mutation() is not None:
                raise AuthorityValidationError(
                    "ticket115 mutation already prepared"
                )
            if self.record(target.record_id) is not None:
                raise AuthorityValidationError(
                    "ticket115 mutation record already exists"
                )
            if not self.ticket115_mutation_base_is_current(mutation):
                raise AuthorityValidationError("ticket115 mutation base changed")
            local_authority = self.finalized_authority()
            if local_authority != mutation.prepared.base:
                raise AuthorityValidationError(
                    "ticket115 preparation authority changed"
                )
            self._validate_record_write(
                target.record_id,
                "prepared",
                target.revision_digest,
                target.transition_id,
                mutation.prepared,
            )
            self._write_record_row(
                connection,
                target.record_id,
                "prepared",
                target.revision_digest,
                target.transition_id,
                record_nonce,
                record_ciphertext,
            )
            connection.execute(
                "INSERT INTO ticket115_mutations_v1("
                "slot, record_id, nonce, ciphertext"
                ") VALUES (1, ?, ?, ?)",
                (target.record_id, nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    def _write_daily_review_ledger(
        self,
        connection: sqlite3.Connection,
        state: object,
    ) -> None:
        current = self.daily_review_ledger()
        if current == state:
            return
        if current is not None and (
            current.owner_id != state.owner_id
            or current.installation_id != state.installation_id
            or state.version != current.version + 1
        ):
            raise AuthorityValidationError("stale daily review ledger version")
        if current is None and state.version not in {0, 1}:
            raise AuthorityValidationError("invalid initial daily review version")
        nonce, ciphertext = self._seal(
            "daily-review-ledger:v1",
            self._daily_review_ledger_wire(state),
        )
        connection.execute(
            "INSERT INTO daily_reviews_v1(slot, nonce, ciphertext) "
            "VALUES (1, ?, ?) "
            "ON CONFLICT(slot) DO UPDATE SET "
            "nonce=excluded.nonce, ciphertext=excluded.ciphertext",
            (nonce, ciphertext),
        )

    def _new_notifying_review_records(self, state: object) -> tuple[object, ...]:
        def identity(record: object) -> tuple[str, str]:
            return record.key.value, record.result_digest

        current = self.daily_review_ledger()
        current_records = () if current is None else current.completed
        next_by_key = {
            record.key.value: record
            for record in state.completed
        }
        if any(
            next_by_key.get(record.key.value) != record
            for record in current_records
        ):
            raise AuthorityValidationError(
                "completed daily review history is append-only"
            )
        known = {
            identity(record)
            for record in current_records
        }
        return tuple(
            record
            for record in state.completed
            if record.notification_required
            and identity(record) not in known
        )

    def _write_delivery_outbox(
        self,
        connection: sqlite3.Connection,
        state: object,
    ) -> None:
        from .delivery import DeliveryOutboxState

        if type(state) is not DeliveryOutboxState:
            raise AuthorityValidationError("invalid delivery outbox aggregate")
        current = self.delivery_outbox_state(
            state.owner_id,
            state.installation_id,
        )
        if current == state:
            return
        if state.version != current.version + 1:
            raise AuthorityValidationError("stale delivery outbox version")
        if not state.records:
            raise AuthorityValidationError(
                "nonzero delivery outbox cannot discard every intent"
            )
        current_by_intent = {
            record.intent.intent_id: record
            for record in current.records
        }
        next_by_intent = {
            record.intent.intent_id: record
            for record in state.records
        }
        for intent_id, previous in current_by_intent.items():
            next_record = next_by_intent.get(intent_id)
            if next_record is None:
                raise AuthorityValidationError(
                    "owner outbox history is append-only"
                )
            if next_record.intent != previous.intent:
                raise AuthorityValidationError(
                    "owner outbox intent is immutable"
                )
            next_facts = {
                fact.kind: fact
                for fact in next_record.facts
            }
            if any(
                next_facts.get(fact.kind) != fact
                for fact in previous.facts
            ):
                raise AuthorityValidationError(
                    "owner delivery facts are append-only"
                )
            if next_record.leases[: len(previous.leases)] != previous.leases:
                raise AuthorityValidationError(
                    "owner delivery leases are append-only"
                )
        for record in state.records:
            phase = self._delivery_phase(record)
            intent_id = record.intent.intent_id
            value = {
                "intent": record.intent.to_wire(),
                "leases": [lease.to_wire() for lease in record.leases],
            }
            previous = current_by_intent.get(intent_id)
            if previous is None:
                nonce, ciphertext = self._seal(
                    f"owner-outbox:{intent_id}:{phase}",
                    value,
                )
                connection.execute(
                    "INSERT INTO owner_outbox_v1("
                    "intent_id, state_version, phase, nonce, ciphertext"
                    ") VALUES (?, ?, ?, ?, ?)",
                    (intent_id, state.version, phase, nonce, ciphertext),
                )
            else:
                nonce, ciphertext = self._seal(
                    f"owner-outbox:{intent_id}:{phase}",
                    value,
                )
                connection.execute(
                    "UPDATE owner_outbox_v1 SET "
                    "state_version = ?, phase = ?, nonce = ?, ciphertext = ? "
                    "WHERE intent_id = ?",
                    (state.version, phase, nonce, ciphertext, intent_id),
                )
            previous_fact_kinds = (
                frozenset()
                if previous is None
                else frozenset(fact.kind for fact in previous.facts)
            )
            for fact in record.facts:
                if fact.kind in previous_fact_kinds:
                    continue
                observation_id = self._delivery_observation_id(
                    intent_id,
                    fact.kind,
                )
                fact_nonce, fact_ciphertext = self._seal(
                    f"owner-delivery-observation:{observation_id}:"
                    f"{intent_id}:{fact.kind}",
                    fact.to_wire(),
                )
                connection.execute(
                    "INSERT INTO owner_delivery_observations_v1("
                    "observation_id, intent_id, layer, nonce, ciphertext"
                    ") VALUES (?, ?, ?, ?, ?)",
                    (
                        observation_id,
                        intent_id,
                        fact.kind,
                        fact_nonce,
                        fact_ciphertext,
                    ),
                )

    def _commit_ticket115_facts_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        task_state: TaskRuntimeState | None,
        review_state: DailyReviewLedger | None,
        delivery_state: DeliveryOutboxState | None,
        status_projection: StatusProjection | None = None,
    ) -> None:
        notifying_reviews = (
            ()
            if review_state is None
            else self._new_notifying_review_records(review_state)
        )
        if notifying_reviews:
            if delivery_state is None:
                raise AuthorityValidationError(
                    "notifying daily review requires atomic outbox state"
                )
            current_delivery = self.delivery_outbox_state(
                delivery_state.owner_id,
                delivery_state.installation_id,
            )
            current_intents = {
                record.intent.intent_id
                for record in current_delivery.records
            }
            new_records = tuple(
                record
                for record in delivery_state.records
                if record.intent.intent_id not in current_intents
            )
            for review in notifying_reviews:
                matching = tuple(
                    record
                    for record in new_records
                    if record.intent.effect_kind == "owner-delivery"
                    and record.intent.business_fact_ref == review.key.value
                    and record.intent.business_revision_digest
                    == review.result_digest
                    and record.intent.source_ref in review.action_refs
                )
                if len(matching) != 1:
                    raise AuthorityValidationError(
                        "notifying daily review requires its exact new "
                        "owner-delivery intent"
                    )
        if task_state is not None:
            self._write_task_runtime(connection, task_state)
        if review_state is not None:
            self._write_daily_review_ledger(connection, review_state)
        if delivery_state is not None:
            self._write_delivery_outbox(connection, delivery_state)
        if status_projection is not None:
            self._write_business_status_in_transaction(
                connection,
                status_projection,
            )

    def commit_ticket115_facts(
        self,
        *,
        task_state: object | None = None,
        review_state: object | None = None,
        delivery_state: object | None = None,
    ) -> None:
        """Atomically commit task/review facts and their owner outbox state."""

        from .delivery import DeliveryOutboxState
        from .review import DailyReviewLedger
        from .tasking import TaskRuntimeState

        if task_state is not None and type(task_state) is not TaskRuntimeState:
            raise AuthorityValidationError("invalid task runtime aggregate")
        if review_state is not None and type(review_state) is not DailyReviewLedger:
            raise AuthorityValidationError("invalid daily review ledger")
        if delivery_state is not None and type(delivery_state) is not DeliveryOutboxState:
            raise AuthorityValidationError("invalid delivery outbox aggregate")
        if task_state is None and review_state is None and delivery_state is None:
            raise AuthorityValidationError("ticket115 fact required")
        authorities = set()
        if task_state is not None:
            authorities.add((task_state.owner_id, task_state.installation_id))
        if review_state is not None:
            authorities.add(
                (
                    review_state.owner_id,
                    review_state.installation_id,
                )
            )
        if delivery_state is not None:
            authorities.add(
                (delivery_state.owner_id, delivery_state.installation_id)
            )
        if len(authorities) != 1:
            raise AuthorityValidationError("ticket115 authority mismatch")
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            self._commit_ticket115_facts_in_transaction(
                connection,
                task_state=task_state,
                review_state=review_state,
                delivery_state=delivery_state,
            )
            self._refresh_integrity_manifest(connection)

    def finalize_ticket115_mutation(
        self,
        record_id: str,
        committed: CommittedTransition,
    ) -> None:
        """Atomically expose the prepared aggregates and advance local authority."""

        validate_opaque_text(record_id, "ticket115 mutation record identifier")
        committed = validate_committed_transition(committed)
        mutation = self.ticket115_mutation_for_record(record_id)
        if mutation is None or mutation.prepared != committed.prepared:
            raise AuthorityValidationError("ticket115 mutation commitment mismatch")
        target = committed.prepared.target
        self._validate_record_write(
            record_id,
            "final",
            target.revision_digest,
            target.transition_id,
            committed,
        )
        record_nonce, record_ciphertext = self._seal(
            f"record:{record_id}:final",
            committed.to_storage(),
        )
        authority_nonce, authority_ciphertext = self._seal_finalized_authority(
            committed.committed,
            record_id,
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            current = self.record(record_id)
            durable = self.ticket115_mutation_for_record(record_id)
            if (
                current is None
                or current.state != "committed"
                or current.payload != committed
                or durable != mutation
                or not self.ticket115_mutation_base_is_current(mutation)
            ):
                raise AuthorityValidationError(
                    "ticket115 mutation finalization changed"
                )
            self._commit_ticket115_facts_in_transaction(
                connection,
                task_state=mutation.task_state,
                review_state=mutation.review_state,
                delivery_state=mutation.delivery_state,
                status_projection=mutation.status_projection,
            )
            if mutation.health_command_receipt is not None:
                self._write_health_command_receipt(
                    connection,
                    mutation.health_command_receipt,
                )
            if mutation.managed_effect_intent is not None:
                intent = mutation.managed_effect_intent
                self._write_managed_effect_intent(
                    connection,
                    EffectIntent(
                        effect_id=intent.effect_id,
                        effect_kind=intent.effect_kind,
                        intent_digest=intent.intent_digest,
                        authority=committed.committed,
                        business_source_causal_id=(
                            intent.business_source_causal_id
                        ),
                    ),
                )
            self._write_record_row(
                connection,
                record_id,
                "final",
                target.revision_digest,
                target.transition_id,
                record_nonce,
                record_ciphertext,
            )
            self._write_finalized_authority_row(
                connection,
                authority_nonce,
                authority_ciphertext,
            )
            cursor = connection.execute(
                "DELETE FROM ticket115_mutations_v1 "
                "WHERE slot = 1 AND record_id = ?",
                (record_id,),
            )
            if cursor.rowcount != 1:
                raise AuthorityValidationError(
                    "ticket115 mutation finalization changed"
                )
            self._refresh_integrity_manifest(connection)

    def remember_task_runtime(self, state: object) -> None:
        self.commit_ticket115_facts(task_state=state)

    def remember_daily_review(self, state: object) -> None:
        self.commit_ticket115_facts(review_state=state)

    def remember_delivery_outbox(self, state: object) -> None:
        self.commit_ticket115_facts(delivery_state=state)

    def owner_settings(self) -> OwnerSettingsState | None:
        """Return the single encrypted current owner-settings aggregate."""

        row = self._execute(
            "SELECT nonce, ciphertext FROM owner_settings_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            return None
        try:
            return OwnerSettingsState.from_wire(
                self._open("owner-settings:v1", row[0], row[1])
            )
        except (TypeError, ValueError) as exc:
            raise KeyUnavailable("invalid owner settings aggregate") from exc

    def write_owner_mutation(
        self,
        prepared: OwnerPreparedMutation,
    ) -> StoredOwnerMutation:
        """Persist one exact prepared owner mutation as the recovery authority."""

        if type(prepared) is not OwnerPreparedMutation:
            raise AuthorityValidationError("prepared owner mutation required")
        stored_prepared: (
            OwnerPreparedMutation | OwnerPreparedCorrectionRecovery
        ) = prepared
        if prepared.request.pending_correction is not None:
            stored_prepared = OwnerPreparedCorrectionRecovery.for_preparation(
                prepared
            )
        command_id = prepared.request.context.command_id
        record_id = prepared.record_id
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            rows = connection.execute(
                "SELECT command_id, record_id, phase, nonce, ciphertext "
                "FROM owner_mutations_v1 "
                "WHERE command_id = ? OR record_id = ?",
                (command_id, record_id),
            ).fetchall()
            if rows:
                if len(rows) == 1:
                    existing = self._decode_owner_mutation(*rows[0])
                    if (
                        existing.command_id == command_id
                        and existing.record_id == record_id
                        and (
                            (
                                existing.phase == "prepared"
                                and existing.prepared == stored_prepared
                            )
                            or (
                                existing.phase == "finalized"
                                and existing.terminal is not None
                                and existing.terminal.matches(prepared)
                            )
                        )
                    ):
                        return existing
                raise AuthorityValidationError("owner mutation identity conflict")
            unresolved = connection.execute(
                "SELECT command_id FROM owner_mutations_v1 "
                "WHERE phase = 'prepared' LIMIT 2"
            ).fetchall()
            if unresolved:
                raise AuthorityValidationError("owner mutation lease already owned")
            stored = StoredOwnerMutation(
                phase="prepared",
                prepared=stored_prepared,
                terminal=None,
            )
            nonce, ciphertext = self._seal(
                f"owner-mutation:{command_id}:{record_id}:prepared",
                stored.to_storage(),
            )
            connection.execute(
                "INSERT INTO owner_mutations_v1("
                "command_id, record_id, phase, nonce, ciphertext"
                ") VALUES (?, ?, 'prepared', ?, ?)",
                (command_id, record_id, nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)
            return stored

    def owner_mutation(self, command_id: str) -> StoredOwnerMutation | None:
        validate_opaque_text(command_id, "owner mutation command identifier")
        row = self._execute(
            "SELECT command_id, record_id, phase, nonce, ciphertext "
            "FROM owner_mutations_v1 WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        return None if row is None else self._decode_owner_mutation(*row)

    def owner_mutation_for_record(
        self,
        record_id: str,
    ) -> StoredOwnerMutation | None:
        validate_opaque_text(record_id, "owner mutation record identifier")
        row = self._execute(
            "SELECT command_id, record_id, phase, nonce, ciphertext "
            "FROM owner_mutations_v1 WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        return None if row is None else self._decode_owner_mutation(*row)

    def finalize_owner_mutation(
        self,
        prepared: OwnerPreparedMutation | OwnerPreparedCorrectionRecovery,
        *,
        task_state: TaskRuntimeState | None = None,
    ) -> StoredOwnerMutation:
        """Atomically publish settings, task control, and the terminal receipt."""

        if type(prepared) not in {
            OwnerPreparedMutation,
            OwnerPreparedCorrectionRecovery,
        }:
            raise AuthorityValidationError("prepared owner mutation required")
        durable_prepared = prepared
        if (
            type(prepared) is OwnerPreparedMutation
            and prepared.request.pending_correction is not None
        ):
            durable_prepared = (
                OwnerPreparedCorrectionRecovery.for_preparation(prepared)
            )
        if type(durable_prepared) is OwnerPreparedCorrectionRecovery:
            command_id = durable_prepared.command_id
            expected_settings_version = (
                durable_prepared.expected_settings_version
            )
            next_settings = durable_prepared.next_settings
        else:
            command_id = durable_prepared.request.context.command_id
            expected_settings_version = (
                durable_prepared.request.expected_settings_version
            )
            next_settings = durable_prepared.next_settings
        if task_state is not None and (
            type(task_state) is not TaskRuntimeState
            or task_state.owner_id != next_settings.owner_id
            or task_state.installation_id != next_settings.installation_id
        ):
            raise AuthorityValidationError("owner task runtime authority mismatch")
        record_id = prepared.record_id
        terminal = OwnerMutationTerminalReceipt.for_finalization(
            durable_prepared
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            row = connection.execute(
                "SELECT command_id, record_id, phase, nonce, ciphertext "
                "FROM owner_mutations_v1 WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if row is None:
                raise AuthorityValidationError("prepared owner mutation required")
            existing = self._decode_owner_mutation(*row)
            if existing.record_id != record_id:
                raise AuthorityValidationError("owner mutation identity conflict")
            if existing.phase == "finalized":
                if existing.terminal != terminal:
                    raise AuthorityValidationError("finalized owner mutation mismatch")
                current_settings = self.owner_settings()
                if current_settings is None or (
                    current_settings.owner_id != next_settings.owner_id
                    or current_settings.installation_id
                    != next_settings.installation_id
                    or current_settings.version < terminal.settings_version
                ):
                    raise KeyUnavailable("owner settings aggregate mismatch")
                return existing
            if existing.prepared != durable_prepared:
                raise AuthorityValidationError("prepared owner mutation mismatch")
            current_settings = self.owner_settings()
            if current_settings is not None and (
                current_settings.owner_id != next_settings.owner_id
                or current_settings.installation_id
                != next_settings.installation_id
                or current_settings.version
                != expected_settings_version
            ):
                raise AuthorityValidationError("stale owner settings version")
            if type(durable_prepared) is OwnerPreparedCorrectionRecovery:
                daily_turn = self._daily_turn_row(
                    durable_prepared.daily_source_causal_id
                )
                if (
                    daily_turn is None
                    or daily_turn.phase != "finalized"
                    or daily_turn.terminal is None
                    or daily_turn.terminal.source_causal_id
                    != durable_prepared.daily_source_causal_id
                    or daily_turn.terminal.record_id
                    != durable_prepared.record_id
                    or daily_turn.terminal.revision_digest
                    != durable_prepared.revision_digest
                    or daily_turn.terminal.transition_id
                    != durable_prepared.transition_id
                    or daily_turn.terminal.payload_digest
                    != durable_prepared.payload_digest
                    or daily_turn.terminal.result_digest
                    != durable_prepared.daily_result_digest
                ):
                    raise AuthorityValidationError(
                        "finalized owner correction result required"
                    )
            elif durable_prepared.request.daily_turn_draft is not None:
                daily_draft = durable_prepared.request.daily_turn_draft
                daily_turn = self._daily_turn_row(daily_draft.source_causal_id)
                if (
                    durable_prepared.daily_result_digest is None
                    or daily_turn is None
                    or daily_turn.phase != "finalized"
                    or daily_turn.terminal is None
                    or not daily_turn.terminal.matches_draft(daily_draft)
                    or daily_turn.terminal.result_digest
                    != durable_prepared.daily_result_digest
                ):
                    raise AuthorityValidationError(
                        "finalized owner correction result required"
                    )

            settings_nonce, settings_ciphertext = self._seal(
                "owner-settings:v1",
                next_settings.to_wire(),
            )
            connection.execute(
                "INSERT INTO owner_settings_v1(slot, nonce, ciphertext) "
                "VALUES (1, ?, ?) "
                "ON CONFLICT(slot) DO UPDATE SET "
                "nonce=excluded.nonce, ciphertext=excluded.ciphertext",
                (settings_nonce, settings_ciphertext),
            )
            if task_state is not None:
                self._write_task_runtime(connection, task_state)
            stored = StoredOwnerMutation(
                phase="finalized",
                prepared=None,
                terminal=terminal,
            )
            mutation_nonce, mutation_ciphertext = self._seal(
                f"owner-mutation:{command_id}:{record_id}:finalized",
                stored.to_storage(),
            )
            connection.execute(
                "UPDATE owner_mutations_v1 SET "
                "phase = 'finalized', nonce = ?, ciphertext = ? "
                "WHERE command_id = ? AND record_id = ? AND phase = 'prepared'",
                (
                    mutation_nonce,
                    mutation_ciphertext,
                    command_id,
                    record_id,
                ),
            )
            self._redact_owner_prepare_receipts(
                connection,
                durable_prepared,
            )
            self._refresh_integrity_manifest(connection)
            return stored

    def _decode_owner_mutation(
        self,
        command_id: object,
        record_id: object,
        phase: object,
        nonce: object,
        ciphertext: object,
    ) -> StoredOwnerMutation:
        if type(command_id) is not str or not command_id:
            raise KeyUnavailable("invalid owner mutation command identifier")
        if type(record_id) is not str or not record_id:
            raise KeyUnavailable("invalid owner mutation record identifier")
        if phase not in {"prepared", "finalized"}:
            raise KeyUnavailable("invalid owner mutation phase")
        try:
            stored = StoredOwnerMutation.from_storage(
                self._open(
                    f"owner-mutation:{command_id}:{record_id}:{phase}",
                    nonce,  # type: ignore[arg-type]
                    ciphertext,  # type: ignore[arg-type]
                )
            )
        except (AuthorityValidationError, TypeError, ValueError) as exc:
            raise KeyUnavailable("invalid owner mutation") from exc
        if (
            stored.command_id != command_id
            or stored.record_id != record_id
            or stored.phase != phase
        ):
            raise KeyUnavailable("owner mutation identifier mismatch")
        return stored

    def write_daily_turn(
        self,
        phase: str,
        draft: DailyTurnDraft,
        result: DailyTurnResult | None = None,
    ) -> None:
        """Create or advance one encrypted post-initialization turn.

        The generic transition record is the commit authority.  Every daily
        row must therefore match its exact phase and target before the row can
        be written.  Finalization is normally performed through
        :meth:`finalize_daily_turn`, which updates the daily aggregate and the
        turn result atomically; a direct finalized write is accepted only as
        an idempotent replay of an already-finalized aggregate.
        """

        self._validate_daily_turn_value(phase, draft, result)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            existing = self._daily_turn_row(draft.source_causal_id)
            if phase == "finalized":
                if (
                    existing is None
                    or existing.phase != "finalized"
                    or existing.terminal is None
                    or not existing.terminal.matches_draft(draft)
                    or type(result) is not DailyTurnResult
                    or stable_digest(result.to_storage())
                    != existing.terminal.result_digest
                ):
                    raise AuthorityValidationError(
                        "finalized daily turn must already exist"
                    )
                self._validate_daily_terminal_record_binding(existing.terminal)
                return
            self._validate_daily_turn_record_binding(draft, phase)
            if existing is None:
                if phase != "prepared":
                    raise AuthorityValidationError("daily turn must begin prepared")
                if draft.turn_kind != "evidence-stage":
                    raise AuthorityValidationError(
                        "daily turn must begin with evidence stage"
                    )
                if self.unresolved_daily_turn() is not None:
                    raise AuthorityValidationError("daily turn lease already owned")
            elif existing.phase == "evidence-finalized":
                if (
                    phase != "prepared"
                    or draft.turn_kind != "complete-turn"
                    or existing.draft is None
                    or draft.evidence_stage != existing.draft
                    or draft.base_state_digest != existing.evidence_state_digest
                ):
                    raise AuthorityValidationError(
                        "complete turn must continue exact evidence stage"
                    )
            else:
                if existing.draft is None or existing.draft != draft:
                    raise AuthorityValidationError("daily source already has another turn")
                allowed = {
                    "prepared": {"prepared", "unknown", "committed"},
                    "unknown": {"unknown", "prepared", "committed"},
                    "committed": {"committed"},
                }
                if phase not in allowed[existing.phase]:
                    raise AuthorityValidationError("invalid daily turn transition")
            self._write_daily_turn_row(connection, phase, draft, result)
            self._refresh_integrity_manifest(connection)

    def daily_turn(self, source_causal_id: str) -> StoredDailyTurn | None:
        validate_opaque_text(source_causal_id, "source causal identifier")
        turn = self._daily_turn_row(source_causal_id)
        if turn is not None:
            if turn.draft is not None:
                self._validate_daily_turn_record_binding(turn.draft, turn.phase)
            else:
                self._validate_daily_terminal_record_binding(turn._terminal())
        return turn

    def daily_turn_for_record(self, record_id: str) -> StoredDailyTurn | None:
        validate_opaque_text(record_id, "daily turn record identifier")
        row = self._execute(
            "SELECT source_causal_id, record_id, phase, nonce, ciphertext "
            "FROM daily_turns_v1 WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        turn = self._decode_daily_turn(*row)
        if turn.draft is not None:
            self._validate_daily_turn_record_binding(turn.draft, turn.phase)
        else:
            self._validate_daily_terminal_record_binding(turn._terminal())
        return turn

    def unresolved_daily_turn(self) -> StoredDailyTurn | None:
        """Return the single authoritative unfinished daily turn, if any.

        Ticket 112 deliberately permits only one core-owned daily transition
        lease at a time.  This is a read-only projection over the encrypted
        turn journal: callers may use it while holding the store transaction
        that will create a new prepared row.  Multiple unfinished rows, or a
        draft based on any state other than the current committed aggregate,
        are impossible under that contract and therefore fail closed instead
        of selecting an arbitrary owner.
        """

        self._verify_integrity_manifest()
        rows = self._execute(
            "SELECT source_causal_id, record_id, phase, nonce, ciphertext "
            "FROM daily_turns_v1 "
            "WHERE phase IN ('prepared', 'unknown', 'committed', 'evidence-finalized') "
            "ORDER BY source_causal_id"
        ).fetchall()
        if len(rows) > 1:
            raise KeyUnavailable("multiple unresolved daily turns")
        if not rows:
            return None
        turn = self._decode_daily_turn(*rows[0])
        if turn.draft is None:
            raise KeyUnavailable("unresolved daily turn draft missing")
        self._validate_daily_turn_record_binding(turn.draft, turn.phase)
        current_state_digest = self.daily_state().digest
        if turn.phase == "evidence-finalized":
            if (
                turn.draft.base_state_digest != current_state_digest
                or turn.evidence_state_digest
                != self.daily_state().apply_evidence_stage(turn.draft).digest
            ):
                raise KeyUnavailable("evidence stage state mismatch")
        elif turn.draft.turn_kind == "complete-turn":
            evidence_stage = turn.draft.evidence_stage
            if (
                type(evidence_stage) is not DailyTurnDraft
                or evidence_stage.base_state_digest != current_state_digest
                or turn.draft.base_state_digest
                != self.daily_state().apply_evidence_stage(evidence_stage).digest
            ):
                raise KeyUnavailable("daily completion base state mismatch")
        elif turn.draft.base_state_digest != current_state_digest:
            raise KeyUnavailable("daily turn base state mismatch")
        return turn

    def daily_state(self) -> DailyHealthState:
        row = self._execute(
            "SELECT nonce, ciphertext FROM daily_health_state_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            return DailyHealthState.empty()
        try:
            return DailyHealthState.from_storage(
                self._open("daily-health-state", row[0], row[1])
            )
        except AuthorityValidationError as exc:
            raise KeyUnavailable("invalid daily health state") from exc

    def finalize_daily_evidence_stage(
        self,
        draft: DailyTurnDraft,
    ) -> DailyHealthState:
        """Commit evidence only while retaining the source's overall lease."""

        if type(draft) is not DailyTurnDraft or draft.turn_kind != "evidence-stage":
            raise AuthorityValidationError("evidence stage draft required")
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            existing = self._daily_turn_row(draft.source_causal_id)
            if (
                existing is None
                or existing.phase != "committed"
                or existing.draft != draft
            ):
                raise AuthorityValidationError("committed evidence stage required")
            self._validate_daily_turn_record_binding(
                draft,
                "evidence-finalized",
            )
            current_state = self.daily_state()
            # The stage is durable recovery authority, not a published health
            # revision.  Materialize its digest only so the exact continuation
            # can be bound; evidence, portrait and reply intent publish together
            # when the complete turn finalizes.
            next_state = current_state.apply_evidence_stage(draft)
            self._write_daily_turn_row(
                connection,
                "evidence-finalized",
                draft,
                None,
                evidence_state_digest=next_state.digest,
            )
            self._refresh_integrity_manifest(connection)
            return next_state

    def finalize_daily_turn(self, draft: DailyTurnDraft) -> DailyTurnResult:
        """Apply one committed draft and persist its result atomically."""

        if type(draft) is not DailyTurnDraft or draft.turn_kind != "complete-turn":
            raise AuthorityValidationError("complete daily turn draft required")
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            existing = self._daily_turn_row(draft.source_causal_id)
            if existing is None:
                raise AuthorityValidationError("committed daily turn required")
            if existing.phase == "finalized":
                terminal = existing.terminal
                result = self._daily_result_for_draft(draft)
                if (
                    terminal is None
                    or not terminal.matches_draft(draft)
                    or stable_digest(result.to_storage()) != terminal.result_digest
                ):
                    raise AuthorityValidationError("finalized daily turn mismatch")
                self._validate_daily_terminal_record_binding(terminal)
                if draft.source_causal_id not in self.daily_state().processed_source_causal_ids:
                    raise KeyUnavailable("daily turn aggregate mismatch")
                return existing.result if existing.result is not None else result
            if existing.draft is None or existing.draft != draft or existing.phase != "committed":
                raise AuthorityValidationError("committed daily turn required")
            self._validate_daily_turn_record_binding(draft, "finalized")
            current_state = self.daily_state()
            evidence_stage = draft.evidence_stage
            if type(evidence_stage) is not DailyTurnDraft:
                raise AuthorityValidationError("complete turn evidence stage required")
            post_stage_state = current_state.apply_evidence_stage(evidence_stage)
            if post_stage_state.digest != draft.base_state_digest:
                raise AuthorityValidationError("daily completion base state changed")
            next_state, result = post_stage_state.apply(draft)
            previous_terminal_digest = None
            if current_state.processed_source_causal_ids:
                previous_source = current_state.processed_source_causal_ids[-1]
                previous = self._daily_turn_row(previous_source)
                if (
                    previous is None
                    or previous.phase != "finalized"
                    or previous.terminal is None
                ):
                    raise KeyUnavailable("daily terminal chain is incomplete")
                previous_terminal_digest = previous.terminal.digest
            terminal = DailyTurnTerminalReceipt.for_finalization(
                draft,
                result,
                next_state,
                previous_terminal_digest=previous_terminal_digest,
            )
            state_nonce, state_ciphertext = self._seal(
                "daily-health-state",
                next_state.to_storage(),
            )
            connection.execute(
                """
                INSERT INTO daily_health_state_v1(slot, nonce, ciphertext)
                VALUES (1, ?, ?)
                ON CONFLICT(slot) DO UPDATE SET
                    nonce=excluded.nonce,
                    ciphertext=excluded.ciphertext
                """,
                (state_nonce, state_ciphertext),
            )
            self._write_daily_turn_terminal_row(
                connection,
                terminal,
                result,
            )
            self._redact_daily_prepare_receipts(
                connection,
                draft.source_causal_id,
            )
            retired_evidence_ids = {
                evidence_id
                for compaction in draft.evidence_stage.evidence_compactions
                for evidence_id in compaction.retire_evidence_ids
            }
            if retired_evidence_ids:
                self._scrub_compacted_terminal_results(
                    connection,
                    retired_evidence_ids,
                    exclude_source_causal_id=draft.source_causal_id,
                )
            self._refresh_integrity_manifest(connection)
            return result

    def _daily_turn_row(self, source_causal_id: str) -> StoredDailyTurn | None:
        row = self._execute(
            "SELECT source_causal_id, record_id, phase, nonce, ciphertext "
            "FROM daily_turns_v1 WHERE source_causal_id = ?",
            (source_causal_id,),
        ).fetchone()
        return None if row is None else self._decode_daily_turn(*row)

    def _decode_daily_turn(
        self,
        source_causal_id: object,
        record_id: object,
        phase: object,
        nonce: object,
        ciphertext: object,
    ) -> StoredDailyTurn:
        if type(source_causal_id) is not str or not source_causal_id:
            raise KeyUnavailable("invalid daily turn source identifier")
        if type(record_id) is not str or not record_id:
            raise KeyUnavailable("invalid daily turn record identifier")
        if type(phase) is not str or phase not in {
            "prepared",
            "unknown",
            "committed",
            "evidence-finalized",
            "finalized",
        }:
            raise KeyUnavailable("invalid daily turn phase")
        stored = self._open(
            f"daily-turn:{source_causal_id}:{record_id}:{phase}",
            nonce,  # type: ignore[arg-type]
            ciphertext,  # type: ignore[arg-type]
        )
        try:
            if phase == "finalized":
                if not isinstance(stored, Mapping) or set(stored) != {
                    "terminal",
                    "result",
                }:
                    raise AuthorityValidationError("invalid finalized daily turn")
                terminal = DailyTurnTerminalReceipt.from_storage(stored["terminal"])
                result = (
                    None
                    if stored["result"] is None
                    else DailyTurnResult.from_storage(stored["result"])
                )
                if (
                    terminal.source_causal_id != source_causal_id
                    or terminal.record_id != record_id
                    or (
                        result is not None
                        and (
                            result.source_causal_id != source_causal_id
                            or result.record_id != record_id
                            or result.transition_id != terminal.transition_id
                            or stable_digest(result.to_storage())
                            != terminal.result_digest
                        )
                    )
                ):
                    raise AuthorityValidationError("daily terminal identifier mismatch")
                return StoredDailyTurn(
                    phase=phase,
                    draft=None,
                    result=result,
                    terminal=terminal,
                )
            if phase == "evidence-finalized":
                if not isinstance(stored, Mapping) or set(stored) != {
                    "draft",
                    "evidence_state_digest",
                }:
                    raise AuthorityValidationError(
                        "invalid finalized evidence stage"
                    )
                draft = DailyTurnDraft.from_storage(stored["draft"])
                evidence_state_digest = stored["evidence_state_digest"]
                if type(evidence_state_digest) is not str:
                    raise AuthorityValidationError(
                        "invalid evidence stage state digest"
                    )
                self._validate_daily_turn_value(phase, draft, None)
                if (
                    draft.source_causal_id != source_causal_id
                    or draft.record_id != record_id
                ):
                    raise AuthorityValidationError(
                        "evidence stage identifier mismatch"
                    )
                return StoredDailyTurn(
                    phase=phase,
                    draft=draft,
                    result=None,
                    terminal=None,
                    evidence_state_digest=evidence_state_digest,
                )
            if not isinstance(stored, Mapping) or set(stored) != {"draft", "result"}:
                raise AuthorityValidationError("invalid unresolved daily turn")
            draft = DailyTurnDraft.from_storage(stored["draft"])
            result = None
            if stored["result"] is not None:
                raise AuthorityValidationError("unresolved daily result forbidden")
            self._validate_daily_turn_value(phase, draft, result)
        except AuthorityValidationError as exc:
            raise KeyUnavailable("invalid daily turn") from exc
        if draft.source_causal_id != source_causal_id or draft.record_id != record_id:
            raise KeyUnavailable("daily turn identifier mismatch")
        return StoredDailyTurn(
            phase=phase,
            draft=draft,
            result=result,
            terminal=None,
            evidence_state_digest=None,
        )

    @staticmethod
    def _validate_daily_turn_value(
        phase: object,
        draft: object,
        result: object,
    ) -> None:
        if type(phase) is not str or phase not in {
            "prepared",
            "unknown",
            "committed",
            "evidence-finalized",
            "finalized",
        }:
            raise AuthorityValidationError("invalid daily turn phase")
        if type(draft) is not DailyTurnDraft:
            raise AuthorityValidationError("invalid daily turn draft")
        if phase == "evidence-finalized":
            if draft.turn_kind != "evidence-stage" or result is not None:
                raise AuthorityValidationError("invalid finalized evidence stage")
        elif phase == "finalized":
            if type(result) is not DailyTurnResult:
                raise AuthorityValidationError("finalized daily turn result required")
            expected = EncryptedStateStore._daily_result_for_draft(draft)
            if result != expected:
                raise AuthorityValidationError("daily turn result mismatch")
        elif result is not None:
            raise AuthorityValidationError("intermediate daily turn has a result")

    @staticmethod
    def _daily_result_for_draft(draft: DailyTurnDraft) -> DailyTurnResult:
        evidence_stage = draft.evidence_stage
        if draft.turn_kind != "complete-turn" or type(evidence_stage) is not DailyTurnDraft:
            raise AuthorityValidationError("complete daily turn required")
        return DailyTurnResult(
            draft.source_causal_id,
            draft.record_id,
            draft.transition_id,
            tuple(card.evidence_id for card in evidence_stage.evidence_cards),
            draft.steward_resolution.commit_portrait_topic_refs,
            draft.skill_disclosures,
            draft.owner_reply,
            draft.steward_resolution.commit_evidence_change_ids,
            (
                None
                if draft.model_answer_resolution is None
                else draft.model_answer_resolution.status
            ),
            (
                None
                if draft.model_answer_resolution is None
                else draft.model_answer_resolution.digest
            ),
        )

    def _validate_daily_turn_record_binding(
        self,
        draft: DailyTurnDraft,
        phase: str,
    ) -> None:
        record = self.record(draft.record_id)
        expected_record_phase = {
            "prepared": "prepared",
            "unknown": "unknown",
            "committed": "committed",
            "evidence-finalized": "final",
            "finalized": "final",
        }[phase]
        if (
            record is None
            or record.state != expected_record_phase
            or record.revision_digest != draft.revision_digest
            or record.transition_id != draft.transition_id
        ):
            raise KeyUnavailable("daily turn transition mismatch")
        payload = record.payload
        if type(payload) is PreparedTransition:
            target = payload.target
        elif type(payload) is CommittedTransition:
            target = payload.prepared.target
        else:
            raise KeyUnavailable("daily turn transition mismatch")
        if (
            target.record_id != draft.record_id
            or target.revision_digest != draft.revision_digest
            or target.transition_id != draft.transition_id
            or target.payload_digest != draft.payload_digest
        ):
            raise KeyUnavailable("daily turn transition mismatch")

    def _validate_daily_terminal_record_binding(
        self,
        terminal: DailyTurnTerminalReceipt,
    ) -> None:
        for record_id, revision_digest, transition_id, payload_digest in (
            (
                terminal.evidence_stage_record_id,
                terminal.evidence_stage_revision_digest,
                terminal.evidence_stage_transition_id,
                terminal.evidence_stage_payload_digest,
            ),
            (
                terminal.record_id,
                terminal.revision_digest,
                terminal.transition_id,
                terminal.payload_digest,
            ),
        ):
            record = self.record(record_id)
            if (
                record is None
                or record.state != "final"
                or record.revision_digest != revision_digest
                or record.transition_id != transition_id
                or type(record.payload) is not CommittedTransition
            ):
                raise KeyUnavailable("daily terminal transition mismatch")
            target = record.payload.prepared.target
            if (
                target.record_id != record_id
                or target.revision_digest != revision_digest
                or target.transition_id != transition_id
                or target.payload_digest != payload_digest
            ):
                raise KeyUnavailable("daily terminal transition mismatch")

    def _write_daily_turn_row(
        self,
        connection: sqlite3.Connection,
        phase: str,
        draft: DailyTurnDraft,
        result: DailyTurnResult | None,
        *,
        evidence_state_digest: str | None = None,
    ) -> None:
        if phase == "finalized":
            raise AuthorityValidationError("finalized daily draft cannot be retained")
        if phase == "evidence-finalized":
            if evidence_state_digest is None:
                raise AuthorityValidationError("evidence stage state digest required")
            sealed_value = {
                "draft": draft.to_storage(),
                "evidence_state_digest": evidence_state_digest,
            }
        else:
            if evidence_state_digest is not None:
                raise AuthorityValidationError("unexpected evidence stage state digest")
            sealed_value = {
                "draft": draft.to_storage(),
                "result": None if result is None else result.to_storage(),
            }
        nonce, ciphertext = self._seal(
            f"daily-turn:{draft.source_causal_id}:{draft.record_id}:{phase}",
            sealed_value,
        )
        connection.execute(
            """
            INSERT INTO daily_turns_v1(
                source_causal_id, record_id, phase, nonce, ciphertext
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_causal_id) DO UPDATE SET
                record_id=excluded.record_id,
                phase=excluded.phase,
                nonce=excluded.nonce,
                ciphertext=excluded.ciphertext
            """,
            (
                draft.source_causal_id,
                draft.record_id,
                phase,
                nonce,
                ciphertext,
            ),
        )

    def _write_daily_turn_terminal_row(
        self,
        connection: sqlite3.Connection,
        terminal: DailyTurnTerminalReceipt,
        result: DailyTurnResult | None,
    ) -> None:
        if (
            result is not None
            and (
                result.source_causal_id != terminal.source_causal_id
                or result.record_id != terminal.record_id
                or result.transition_id != terminal.transition_id
                or stable_digest(result.to_storage()) != terminal.result_digest
            )
        ):
            raise AuthorityValidationError("daily terminal result mismatch")
        nonce, ciphertext = self._seal(
            (
                f"daily-turn:{terminal.source_causal_id}:"
                f"{terminal.record_id}:finalized"
            ),
            {
                "terminal": terminal.to_storage(),
                "result": None if result is None else result.to_storage(),
            },
        )
        connection.execute(
            """
            INSERT INTO daily_turns_v1(
                source_causal_id, record_id, phase, nonce, ciphertext
            ) VALUES (?, ?, 'finalized', ?, ?)
            ON CONFLICT(source_causal_id) DO UPDATE SET
                record_id=excluded.record_id,
                phase=excluded.phase,
                nonce=excluded.nonce,
                ciphertext=excluded.ciphertext
            """,
            (
                terminal.source_causal_id,
                terminal.record_id,
                nonce,
                ciphertext,
            ),
        )

    def _redact_owner_prepare_receipts(
        self,
        connection: sqlite3.Connection,
        prepared: OwnerPreparedMutation | OwnerPreparedCorrectionRecovery,
    ) -> None:
        """Replace a finalized owner prepare body with its exact command digest."""

        if type(prepared) is OwnerPreparedCorrectionRecovery:
            expected_binding = prepared.owner_authority_binding_digest
            expected_command_id = prepared.command_id
        elif type(prepared) is OwnerPreparedMutation:
            expected_binding = (
                prepared.request.owner_authority_binding_digest
            )
            expected_command_id = prepared.request.context.command_id
        else:
            raise AuthorityValidationError("prepared owner mutation required")

        rows = connection.execute(
            "SELECT causal_id, nonce, ciphertext FROM command_receipts_v2"
        ).fetchall()
        replacements: list[tuple[bytes, bytes, str]] = []
        for causal_id, nonce, ciphertext in rows:
            stored = self._decode_receipt(causal_id, nonce, ciphertext)
            if not isinstance(stored, _ExactCommandReceipt):
                continue
            command = stored.command
            if (
                command.action == "owner.prepare"
                and isinstance(command.payload, OwnerPreparePayload)
                and command.payload.request.context.command_id
                == expected_command_id
                and command.payload.request.owner_authority_binding_digest
                == expected_binding
            ):
                if stored.response.meta.to_wire() != {}:
                    raise KeyUnavailable(
                        "owner prepare receipt response is not body-free"
                    )
                redacted_nonce, redacted_ciphertext = self._seal(
                    f"receipt:v2:{causal_id}",
                    {
                        "kind": "command-digest-v1",
                        "command_digest": self._receipt_command_digest(command),
                        "response": stored.response.to_wire(),
                    },
                )
                replacements.append(
                    (redacted_nonce, redacted_ciphertext, causal_id)
                )
        for redacted_nonce, redacted_ciphertext, causal_id in replacements:
            connection.execute(
                "UPDATE command_receipts_v2 SET nonce = ?, ciphertext = ? "
                "WHERE causal_id = ?",
                (redacted_nonce, redacted_ciphertext, causal_id),
            )

    def _redact_daily_prepare_receipts(
        self,
        connection: sqlite3.Connection,
        source_causal_id: str,
    ) -> None:
        """Replace recovery-only full drafts with exact body-free replay tombstones."""

        rows = connection.execute(
            "SELECT causal_id, nonce, ciphertext FROM command_receipts_v2"
        ).fetchall()
        replacements: list[tuple[bytes, bytes, str]] = []
        for causal_id, nonce, ciphertext in rows:
            stored = self._decode_receipt(causal_id, nonce, ciphertext)
            if not isinstance(stored, _ExactCommandReceipt):
                continue
            command = stored.command
            if (
                command.action == "turn.prepare"
                and isinstance(command.payload, DailyTurnPreparePayload)
                and command.payload.draft.source_causal_id == source_causal_id
            ):
                # A prepare response is deliberately content-free.  Refuse to
                # preserve an unexpected projection while scrubbing its draft.
                if stored.response.meta.to_wire() != {}:
                    raise KeyUnavailable("daily prepare receipt response is not body-free")
                redacted_nonce, redacted_ciphertext = self._seal(
                    f"receipt:v2:{causal_id}",
                    {
                        "kind": "command-digest-v1",
                        "command_digest": self._receipt_command_digest(command),
                        "response": stored.response.to_wire(),
                    },
                )
                replacements.append(
                    (redacted_nonce, redacted_ciphertext, causal_id)
                )
        for redacted_nonce, redacted_ciphertext, causal_id in replacements:
            connection.execute(
                "UPDATE command_receipts_v2 SET nonce = ?, ciphertext = ? "
                "WHERE causal_id = ?",
                (redacted_nonce, redacted_ciphertext, causal_id),
            )

    def _scrub_compacted_terminal_results(
        self,
        connection: sqlite3.Connection,
        retired_evidence_ids: set[str],
        *,
        exclude_source_causal_id: str,
    ) -> None:
        """Drop obsolete replay text once its committed evidence is summarized.

        The immutable terminal receipt continues to bind the original result
        digest and state-chain position.  Only the optional replay projection
        is erased, so retired detail and predecessor-summary literals cannot
        survive in finalized daily rows.
        """

        rows = connection.execute(
            "SELECT source_causal_id, record_id, phase, nonce, ciphertext "
            "FROM daily_turns_v1 WHERE phase = 'finalized'"
        ).fetchall()
        for row in rows:
            turn = self._decode_daily_turn(*row)
            if (
                turn.source_causal_id == exclude_source_causal_id
                or turn.result is None
                or not set(turn.result.evidence_ids) & retired_evidence_ids
            ):
                continue
            self._write_daily_turn_terminal_row(
                connection,
                turn._terminal(),
                None,
            )

    def write_record(
        self,
        record_id: str,
        state: str,
        revision_digest: str,
        transition_id: str,
        payload: RevisionTarget | PreparedTransition | CommittedTransition,
    ) -> None:
        self._validate_record_write(record_id, state, revision_digest, transition_id, payload)
        nonce, ciphertext = self._seal(f"record:{record_id}:{state}", payload.to_storage())
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            self._write_record_row(
                connection,
                record_id,
                state,
                revision_digest,
                transition_id,
                nonce,
                ciphertext,
            )
            self._refresh_integrity_manifest(connection)

    def write_finalized_record(
        self,
        record_id: str,
        revision_digest: str,
        transition_id: str,
        payload: CommittedTransition,
        authority: AuthoritySnapshot,
    ) -> None:
        self._validate_record_write(record_id, "final", revision_digest, transition_id, payload)
        if not isinstance(authority, AuthoritySnapshot) or payload.committed != authority:
            raise AuthorityValidationError("finalized authority mismatch")
        record_nonce, record_ciphertext = self._seal(f"record:{record_id}:final", payload.to_storage())
        authority_nonce, authority_ciphertext = self._seal_finalized_authority(authority, record_id)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            self._write_record_row(
                connection,
                record_id,
                "final",
                revision_digest,
                transition_id,
                record_nonce,
                record_ciphertext,
            )
            self._write_finalized_authority_row(connection, authority_nonce, authority_ciphertext)
            self._refresh_integrity_manifest(connection)

    def seed_finalized_authority(self, authority: AuthoritySnapshot) -> bool:
        if not isinstance(authority, AuthoritySnapshot):
            raise AuthorityValidationError("invalid finalized authority")
        # Synthetic setup may anchor an already-finalized installation before
        # this skeleton has a business record.  A real `write_finalized_record`
        # always carries the exact final-record identifier below.
        nonce, ciphertext = self._seal_finalized_authority(authority, None)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            cursor = connection.execute(
                "INSERT OR IGNORE INTO finalized_authority(slot, nonce, ciphertext) VALUES (1, ?, ?)",
                (nonce, ciphertext),
            )
            if cursor.rowcount == 1:
                self._refresh_integrity_manifest(connection)
        return cursor.rowcount == 1

    def finalized_authority(self) -> AuthoritySnapshot | None:
        proof = self._finalized_proof()
        return None if proof is None else proof[0]

    def replace_finalized_authority(self, authority: AuthoritySnapshot) -> None:
        """Move the local authority anchor after an authenticated handoff."""

        if type(authority) is not AuthoritySnapshot or authority.terminal:
            raise AuthorityValidationError("invalid transferred authority")
        proof = self._finalized_proof()
        if proof is None:
            raise AuthorityValidationError("local finalized authority missing")
        record_id = proof[1]
        nonce, ciphertext = self._seal_finalized_authority(authority, record_id)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            current = self._finalized_proof()
            if current != proof:
                raise AuthorityValidationError("local finalized authority changed")
            self._write_finalized_authority_row(connection, nonce, ciphertext)
            self._refresh_integrity_manifest(connection)

    @staticmethod
    def _lifecycle_state_aad(operation_ref: str) -> str:
        return "lifecycle-state:" + operation_ref

    def lifecycle_state(self, operation_ref: str) -> dict[str, object] | None:
        """Read one encrypted, body-free lifecycle coordination record."""

        validate_opaque_text(operation_ref, "lifecycle operation reference")
        row = self._execute(
            "SELECT nonce, ciphertext FROM lifecycle_state_v1 "
            "WHERE operation_ref = ?",
            (operation_ref,),
        ).fetchone()
        if row is None:
            return None
        value = self._open(self._lifecycle_state_aad(operation_ref), row[0], row[1])
        if type(value) is not dict or value.get("operation_ref") != operation_ref:
            raise KeyUnavailable("invalid lifecycle state")
        return value

    def lifecycle_states(self) -> tuple[dict[str, object], ...]:
        rows = self._execute(
            "SELECT operation_ref, nonce, ciphertext "
            "FROM lifecycle_state_v1 ORDER BY operation_ref"
        ).fetchall()
        values: list[dict[str, object]] = []
        for operation_ref, nonce, ciphertext in rows:
            value = self._open(
                self._lifecycle_state_aad(operation_ref),
                nonce,
                ciphertext,
            )
            if type(value) is not dict or value.get("operation_ref") != operation_ref:
                raise KeyUnavailable("invalid lifecycle state")
            values.append(value)
        return tuple(values)

    def save_lifecycle_state(self, state: Mapping[str, object]) -> None:
        if type(state) is not dict:
            raise AuthorityValidationError("invalid lifecycle state")
        operation_ref = state.get("operation_ref")
        validate_opaque_text(operation_ref, "lifecycle operation reference")
        nonce, ciphertext = self._seal(
            self._lifecycle_state_aad(operation_ref),
            state,
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            connection.execute(
                """
                INSERT INTO lifecycle_state_v1(operation_ref, nonce, ciphertext)
                VALUES (?, ?, ?)
                ON CONFLICT(operation_ref) DO UPDATE SET
                    nonce=excluded.nonce,
                    ciphertext=excluded.ciphertext
                """,
                (operation_ref, nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    def lifecycle_table_names(self) -> tuple[str, ...]:
        rows = self._execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        return tuple(name for (name,) in rows if isinstance(name, str))

    def purge_all_local_state(self) -> None:
        """Permanently empty every local SQLite table after key confirmation."""

        with self._transaction_lock:
            self._ensure_available()
            try:
                tables = self.lifecycle_table_names()
                self._connection.execute("PRAGMA foreign_keys = OFF")
                for table in tables:
                    quoted = '"' + table.replace('"', '""') + '"'
                    self._connection.execute("DELETE FROM " + quoted)
                self._connection.commit()
                self._connection.execute("PRAGMA foreign_keys = ON")
            except sqlite3.Error as exc:
                try:
                    self._connection.rollback()
                    self._connection.execute("PRAGMA foreign_keys = ON")
                except sqlite3.Error:
                    self._poisoned = True
                raise StoreUnavailable("health state purge unavailable") from exc

    def _finalized_proof(self) -> tuple[AuthoritySnapshot, str | None] | None:
        row = self._execute(
            "SELECT nonce, ciphertext FROM finalized_authority WHERE slot = 1"
        ).fetchone()
        if row is None:
            return None
        try:
            stored = self._open("finalized-authority", row[0], row[1])
            if isinstance(stored, Mapping) and set(stored) == {"authority", "record_id"}:
                record_id = stored["record_id"]
                if record_id is not None:
                    if not isinstance(record_id, str) or not record_id:
                        raise AuthorityValidationError("invalid finalized record identifier")
                return AuthoritySnapshot.from_storage(stored["authority"]), record_id
            # Read old synthetic anchors only as bootstrap anchors.  They are
            # never emitted by this version after a business finalization.
            return AuthoritySnapshot.from_storage(stored), None
        except ValueError as exc:
            raise KeyUnavailable("invalid finalized authority") from exc

    def record(self, record_id: str) -> StoredRecord | None:
        row = self._execute(
            "SELECT state, revision_digest, transition_id, nonce, ciphertext FROM health_records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return StoredRecord(
            state=row[0],
            revision_digest=row[1],
            transition_id=row[2],
            payload=self._decode_record_payload(
                row[0],
                self._open(f"record:{record_id}:{row[0]}", row[3], row[4]),
            ),
        )

    def record_state(self, record_id: str) -> str | None:
        row = self._execute("SELECT state FROM health_records WHERE record_id = ?", (record_id,)).fetchone()
        return None if row is None else row[0]

    def count_records(self) -> int:
        return int(self._execute("SELECT COUNT(*) FROM health_records").fetchone()[0])

    def unresolved_states(self) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in self._execute(
                "SELECT state FROM health_records WHERE state IN ('prepared', 'committed', 'unknown') ORDER BY record_id"
            ).fetchall()
        )

    def write_effect(
        self,
        effect_id: str,
        state: str,
        payload: EffectIntent | ClaimingEffect | ExecutingEffect | TerminalEffect,
    ) -> None:
        self._validate_effect_write(effect_id, state, payload)
        nonce, ciphertext = self._seal(f"effect:{effect_id}:{state}", payload.to_storage())
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            connection.execute(
                "INSERT INTO effects(effect_id, state, nonce, ciphertext) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(effect_id) DO UPDATE SET state=excluded.state, nonce=excluded.nonce, ciphertext=excluded.ciphertext",
                (effect_id, state, nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    def effect(self, effect_id: str) -> StoredEffect | None:
        row = self._execute(
            "SELECT state, nonce, ciphertext FROM effects WHERE effect_id = ?", (effect_id,)
        ).fetchone()
        if row is None:
            return None
        return StoredEffect(
            state=row[0],
            payload=self._decode_effect_payload(
                row[0],
                self._open(f"effect:{effect_id}:{row[0]}", row[1], row[2]),
            ),
        )

    def effect_state(self, effect_id: str) -> str | None:
        row = self._execute("SELECT state FROM effects WHERE effect_id = ?", (effect_id,)).fetchone()
        return None if row is None else row[0]

    def model_effect_for_source(self, source_causal_id: str) -> StoredEffect | None:
        """Return the unique model effect durably bound to one business source."""

        validate_opaque_text(source_causal_id, "effect business source causal identifier")
        matches: list[StoredEffect] = []
        rows = self._execute(
            "SELECT effect_id, state, nonce, ciphertext FROM effects ORDER BY effect_id"
        ).fetchall()
        for effect_id, state, nonce, ciphertext in rows:
            payload = self._decode_effect_payload(
                state,
                self._open(f"effect:{effect_id}:{state}", nonce, ciphertext),
            )
            intent = (
                payload
                if type(payload) is EffectIntent
                else payload.intent
                if type(payload) in {ClaimingEffect, ExecutingEffect, TerminalEffect}
                else None
            )
            if (
                type(intent) is EffectIntent
                and intent.effect_kind == "model-work"
                and intent.business_source_causal_id == source_causal_id
            ):
                matches.append(StoredEffect(state=state, payload=payload))
        if len(matches) > 1:
            raise KeyUnavailable("multiple model effects bound to one business source")
        return None if not matches else matches[0]

    def unresolved_effects(self) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in self._execute(
                "SELECT effect_id FROM effects WHERE state IN ('intent', 'claiming', 'executing', 'unknown') ORDER BY effect_id"
            ).fetchall()
        )

    def count_effects(self) -> int:
        return int(self._execute("SELECT COUNT(*) FROM effects").fetchone()[0])

    def _verify_ticket115_aggregates(
        self,
        current_owner_settings: OwnerSettingsState | None,
    ) -> None:
        task_rows = self._execute(
            "SELECT slot FROM task_runtime_v1 ORDER BY slot"
        ).fetchall()
        review_rows = self._execute(
            "SELECT slot FROM daily_reviews_v1 ORDER BY slot"
        ).fetchall()
        if len(task_rows) > 1:
            raise KeyUnavailable("multiple task runtime aggregates")
        if len(review_rows) > 1:
            raise KeyUnavailable("multiple daily review ledgers")
        task_state = self.task_runtime()
        review_state = self.daily_review_ledger()
        mutation_rows = self._execute(
            "SELECT record_id FROM ticket115_mutations_v1 ORDER BY slot"
        ).fetchall()
        if len(mutation_rows) > 1:
            raise KeyUnavailable("multiple ticket115 prepared mutations")
        mutation = (
            None
            if not mutation_rows
            else self.ticket115_mutation_for_record(mutation_rows[0][0])
        )
        if mutation is not None:
            record = self.record(mutation.prepared.target.record_id)
            record_prepared = (
                None
                if record is None
                else record.payload
                if type(record.payload) is PreparedTransition
                else record.payload.prepared
                if type(record.payload) is CommittedTransition
                else None
            )
            if (
                record is None
                or record.state not in {"prepared", "unknown", "committed"}
                or record_prepared != mutation.prepared
                or not self.ticket115_mutation_base_is_current(mutation)
            ):
                raise KeyUnavailable("ticket115 mutation transition mismatch")
        unresolved_ticket115_records = self._execute(
            "SELECT record_id FROM health_records "
            "WHERE record_id LIKE 'ticket115-mutation:%' "
            "AND state IN ('prepared', 'unknown', 'committed')"
        ).fetchall()
        if (
            len(unresolved_ticket115_records) != (0 if mutation is None else 1)
            or (
                mutation is not None
                and unresolved_ticket115_records[0][0]
                != mutation.prepared.target.record_id
            )
        ):
            raise KeyUnavailable("ticket115 mutation body missing")
        orphan = self._execute(
            "SELECT 1 FROM owner_delivery_observations_v1 AS observation "
            "LEFT JOIN owner_outbox_v1 AS intent "
            "ON intent.intent_id = observation.intent_id "
            "WHERE intent.intent_id IS NULL LIMIT 1"
        ).fetchone()
        if orphan is not None:
            raise KeyUnavailable("delivery observation has no outbox intent")

        delivery_state = None
        first_outbox = self._execute(
            "SELECT intent_id, phase, nonce, ciphertext "
            "FROM owner_outbox_v1 ORDER BY intent_id LIMIT 1"
        ).fetchone()
        if first_outbox is not None:
            from .delivery import OutboxIntent

            intent_id, phase, nonce, ciphertext = first_outbox
            value = _strict_storage_mapping(
                self._open(
                    f"owner-outbox:{intent_id}:{phase}",
                    nonce,
                    ciphertext,
                ),
                frozenset({"intent", "leases"}),
                "owner outbox record",
            )
            try:
                first_intent = OutboxIntent.from_wire(value["intent"])
            except (TypeError, ValueError) as exc:
                raise KeyUnavailable("invalid owner outbox record") from exc
            delivery_state = self.delivery_outbox_state(
                first_intent.owner_id,
                first_intent.installation_id,
            )
        elif self._execute(
            "SELECT 1 FROM owner_delivery_observations_v1 LIMIT 1"
        ).fetchone() is not None:
            raise KeyUnavailable("delivery observation has no outbox intent")

        authorities = {
            (state.owner_id, state.installation_id)
            for state in (task_state, review_state, delivery_state)
            if state is not None
        }
        if len(authorities) > 1:
            raise KeyUnavailable("ticket115 aggregate authority mismatch")
        if current_owner_settings is not None and authorities and authorities != {
            (
                current_owner_settings.owner_id,
                current_owner_settings.installation_id,
            )
        }:
            raise KeyUnavailable("ticket115 owner settings authority mismatch")
        if current_owner_settings is not None and mutation is not None and (
            mutation.owner_id != current_owner_settings.owner_id
            or mutation.installation_id
            != current_owner_settings.installation_id
        ):
            raise KeyUnavailable("ticket115 mutation owner settings mismatch")

    def verify_integrity(self, expected_authority: AuthoritySnapshot) -> bool:
        """Authenticate every local row before a probe can report healthy.

        SQLite state labels and identifiers are plaintext indexes.  They are
        never proof on their own: this scan decrypts every payload using its
        label-bound AAD and revalidates its typed relation to the indexes.
        The returned boolean additionally proves that a business finalization
        still has the encrypted final-record proof named by the authority row.
        """

        if not isinstance(expected_authority, AuthoritySnapshot):
            raise AuthorityValidationError("invalid expected finalized authority")
        self._verify_integrity_manifest()
        proof = self._finalized_proof()
        if proof is None:
            return False
        authority, finalized_record_id = proof
        if authority != expected_authority:
            return False

        final_record_found = finalized_record_id is None
        record_rows = self._execute(
            "SELECT record_id, state, revision_digest, transition_id, nonce, ciphertext "
            "FROM health_records ORDER BY record_id"
        ).fetchall()
        for record_id, state, revision_digest, transition_id, nonce, ciphertext in record_rows:
            try:
                payload = self._decode_record_payload(
                    state,
                    self._open(f"record:{record_id}:{state}", nonce, ciphertext),
                )
                self._validate_record_write(record_id, state, revision_digest, transition_id, payload)
            except AuthorityValidationError as exc:
                raise KeyUnavailable("invalid transition record") from exc
            if record_id == finalized_record_id:
                if (
                    state != "final"
                    or not isinstance(payload, CommittedTransition)
                    or payload.committed != authority
                ):
                    raise KeyUnavailable("finalized record authority mismatch")
                final_record_found = True

        effect_rows = self._execute(
            "SELECT effect_id, state, nonce, ciphertext FROM effects ORDER BY effect_id"
        ).fetchall()
        for effect_id, state, nonce, ciphertext in effect_rows:
            try:
                payload = self._decode_effect_payload(
                    state,
                    self._open(f"effect:{effect_id}:{state}", nonce, ciphertext),
                )
                self._validate_effect_write(effect_id, state, payload)
            except AuthorityValidationError as exc:
                raise KeyUnavailable("invalid effect record") from exc

        pending_rows = self._execute(
            "SELECT causal_id, record_id, nonce, ciphertext FROM pending_commands_v1 ORDER BY causal_id"
        ).fetchall()
        for causal_id, record_id, nonce, ciphertext in pending_rows:
            self._decode_pending(causal_id, record_id, nonce, ciphertext)

        pending_effect_rows = self._execute(
            "SELECT effect_id, causal_id, nonce, ciphertext FROM pending_effect_results_v1 ORDER BY effect_id"
        ).fetchall()
        for effect_id, causal_id, nonce, ciphertext in pending_effect_rows:
            self._decode_pending_effect_result(effect_id, causal_id, nonce, ciphertext)

        receipt_rows = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM command_receipts_v2 ORDER BY causal_id"
        ).fetchall()
        for causal_id, nonce, ciphertext in receipt_rows:
            self._decode_receipt(causal_id, nonce, ciphertext)

        health_command_receipt_rows = self._execute(
            "SELECT causal_id, nonce, ciphertext "
            "FROM ticket115_health_command_receipts_v1 ORDER BY causal_id"
        ).fetchall()
        for causal_id, nonce, ciphertext in health_command_receipt_rows:
            self._decode_health_command_receipt(
                causal_id,
                nonce,
                ciphertext,
            )

        source_rows = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM source_envelopes_v1 ORDER BY causal_id"
        ).fetchall()
        for causal_id, nonce, ciphertext in source_rows:
            try:
                receipt = SourceReceipt.from_storage(
                    self._open(f"source-envelope:{causal_id}", nonce, ciphertext)
                )
            except AuthorityValidationError as exc:
                raise KeyUnavailable("invalid source envelope") from exc
            if receipt.envelope.causal_id != causal_id:
                raise KeyUnavailable("source envelope causal identifier mismatch")

        disclosure_rows = self._execute(
            "SELECT disclosure_id, workflow_id, admission_causal_id, nonce, ciphertext "
            "FROM initialization_disclosure_challenges_v1 ORDER BY disclosure_id"
        ).fetchall()
        for row in disclosure_rows:
            self._decode_initialization_disclosure_challenge(*row)

        initialization_rows = self._execute(
            "SELECT record_id, phase, nonce, ciphertext "
            "FROM owner_initialization_v1 ORDER BY slot"
        ).fetchall()
        if len(initialization_rows) > 1:
            raise KeyUnavailable("multiple initialization aggregates")
        for row in initialization_rows:
            initialization = self._decode_initialization(*row)
            record = self.record(initialization.draft.record_id)
            expected_record_phase = {
                "prepared": "prepared",
                "unknown": "unknown",
                "committed": "committed",
                "enabled": "final",
            }[initialization.phase]
            if (
                record is None
                or record.state != expected_record_phase
                or record.revision_digest != initialization.draft.revision_digest
                or record.transition_id != initialization.draft.transition_id
            ):
                raise KeyUnavailable("initialization transition mismatch")

        daily_rows = self._execute(
            "SELECT source_causal_id, record_id, phase, nonce, ciphertext "
            "FROM daily_turns_v1 ORDER BY source_causal_id"
        ).fetchall()
        daily_turns: dict[str, StoredDailyTurn] = {}
        for row in daily_rows:
            turn = self._decode_daily_turn(*row)
            if turn.draft is not None:
                self._validate_daily_turn_record_binding(turn.draft, turn.phase)
            else:
                self._validate_daily_terminal_record_binding(turn._terminal())
            if turn.source_causal_id in daily_turns:
                raise KeyUnavailable("duplicate daily turn source")
            daily_turns[turn.source_causal_id] = turn

        daily_state_rows = self._execute(
            "SELECT nonce, ciphertext FROM daily_health_state_v1 ORDER BY slot"
        ).fetchall()
        if len(daily_state_rows) > 1:
            raise KeyUnavailable("multiple daily health aggregates")
        daily_state = self.daily_state()
        processed_sources = set(daily_state.processed_source_causal_ids)
        if len(processed_sources) != len(daily_state.processed_source_causal_ids):
            raise KeyUnavailable("duplicate processed daily source")
        previous_terminal_digest = None
        expected_base_state_digest = DailyHealthState.empty().digest
        last_terminal: DailyTurnTerminalReceipt | None = None
        for ordinal, source_causal_id in enumerate(
            daily_state.processed_source_causal_ids,
            start=1,
        ):
            stored_turn = daily_turns.get(source_causal_id)
            if (
                stored_turn is None
                or stored_turn.phase != "finalized"
                or stored_turn.draft is not None
                or stored_turn.terminal is None
            ):
                raise KeyUnavailable("daily health aggregate turn mismatch")
            terminal = stored_turn.terminal
            if (
                terminal.ordinal != ordinal
                or terminal.previous_terminal_digest != previous_terminal_digest
                or terminal.base_state_digest != expected_base_state_digest
            ):
                raise KeyUnavailable("daily terminal chain mismatch")
            previous_terminal_digest = terminal.digest
            expected_base_state_digest = terminal.state_digest
            last_terminal = terminal
        if (
            last_terminal is not None
            and last_terminal.state_digest != daily_state.digest
        ):
            raise KeyUnavailable("daily health aggregate mismatch")
        if last_terminal is None and daily_state != DailyHealthState.empty():
            raise KeyUnavailable("daily health aggregate has no terminal chain")
        for source_causal_id, turn in daily_turns.items():
            if (turn.phase == "finalized") != (source_causal_id in processed_sources):
                raise KeyUnavailable("daily turn phase and aggregate mismatch")
            if turn.phase == "finalized":
                continue
            draft = turn.draft
            if draft is None:
                raise KeyUnavailable("unresolved daily turn draft missing")
            if draft.turn_kind == "evidence-stage":
                if draft.base_state_digest != daily_state.digest:
                    raise KeyUnavailable("daily turn base state mismatch")
                if turn.phase == "evidence-finalized":
                    if (
                        turn.evidence_state_digest
                        != daily_state.apply_evidence_stage(draft).digest
                    ):
                        raise KeyUnavailable("evidence stage state mismatch")
                elif turn.evidence_state_digest is not None:
                    raise KeyUnavailable("unexpected evidence stage state digest")
            else:
                evidence_stage = draft.evidence_stage
                if (
                    type(evidence_stage) is not DailyTurnDraft
                    or turn.phase == "evidence-finalized"
                    or evidence_stage.base_state_digest != daily_state.digest
                    or draft.base_state_digest
                    != daily_state.apply_evidence_stage(evidence_stage).digest
                ):
                    raise KeyUnavailable("daily completion base state mismatch")
                self._validate_daily_turn_record_binding(
                    evidence_stage,
                    "evidence-finalized",
                )
        if sum(turn.phase != "finalized" for turn in daily_turns.values()) > 1:
            raise KeyUnavailable("multiple unresolved daily turns")
        if processed_sources and not daily_state_rows:
            raise KeyUnavailable("daily health aggregate missing")

        owner_settings_rows = self._execute(
            "SELECT nonce, ciphertext FROM owner_settings_v1 ORDER BY slot"
        ).fetchall()
        if len(owner_settings_rows) > 1:
            raise KeyUnavailable("multiple owner settings aggregates")
        current_owner_settings = self.owner_settings()
        owner_mutation_rows = self._execute(
            "SELECT command_id, record_id, phase, nonce, ciphertext "
            "FROM owner_mutations_v1 ORDER BY command_id"
        ).fetchall()
        owner_mutations = tuple(
            self._decode_owner_mutation(*row) for row in owner_mutation_rows
        )
        unresolved_owner_mutations = tuple(
            mutation
            for mutation in owner_mutations
            if mutation.phase == "prepared"
        )
        if len(unresolved_owner_mutations) > 1:
            raise KeyUnavailable("multiple unresolved owner mutations")
        finalized_owner_chain: list[
            tuple[int, OwnerMutationTerminalReceipt]
        ] = []
        for mutation in owner_mutations:
            record = self.record(mutation.record_id)
            if record is None:
                raise KeyUnavailable("owner mutation transition missing")
            record_authority = (
                record.payload
                if isinstance(record.payload, PreparedTransition)
                else record.payload.prepared
                if isinstance(record.payload, CommittedTransition)
                else None
            )
            if (
                type(record_authority) is not PreparedTransition
                or not record_authority.target.matches_commit(
                    record_id=mutation.record_id,
                    revision_digest=record.revision_digest,
                    transition_id=record.transition_id,
                )
            ):
                raise KeyUnavailable("owner mutation transition mismatch")
            if mutation.phase == "prepared":
                prepared = mutation.prepared
                if prepared is None:  # pragma: no cover - decoded invariant
                    raise KeyUnavailable("prepared owner mutation body missing")
                if (
                    record.state not in {"prepared", "unknown", "committed"}
                    or prepared.record_id != mutation.record_id
                    or prepared.revision_digest != record.revision_digest
                    or prepared.transition_id != record.transition_id
                ):
                    raise KeyUnavailable("prepared owner mutation target mismatch")
                if type(prepared) is OwnerPreparedCorrectionRecovery:
                    prepared_owner_id = prepared.owner_id
                    prepared_installation_id = prepared.installation_id
                    prepared_settings_version = (
                        prepared.expected_settings_version
                    )
                    daily = daily_turns.get(
                        prepared.daily_source_causal_id
                    )
                    if (
                        daily is None
                        or daily.draft is None
                        or not prepared.matches_daily(daily.draft)
                    ):
                        raise KeyUnavailable(
                            "prepared owner correction aggregate mismatch"
                        )
                elif type(prepared) is OwnerPreparedMutation:
                    prepared_owner_id = prepared.request.context.owner_id
                    prepared_installation_id = (
                        prepared.request.context.installation_id
                    )
                    prepared_settings_version = (
                        prepared.request.expected_settings_version
                    )
                else:  # pragma: no cover - StoredOwnerMutation invariant
                    raise KeyUnavailable("prepared owner mutation body missing")
                if current_owner_settings is not None and (
                    prepared_owner_id != current_owner_settings.owner_id
                    or prepared_installation_id
                    != current_owner_settings.installation_id
                    or prepared_settings_version
                    != current_owner_settings.version
                ):
                    raise KeyUnavailable("prepared owner mutation base mismatch")
                continue
            terminal = mutation.terminal
            if (
                terminal is None
                or current_owner_settings is None
                or terminal.settings_version > current_owner_settings.version
            ):
                raise KeyUnavailable("finalized owner mutation aggregate mismatch")
            if (
                record.state != "final"
                or terminal.record_id != mutation.record_id
                or terminal.revision_digest != record.revision_digest
                or terminal.transition_id != record.transition_id
            ):
                raise KeyUnavailable("finalized owner mutation target mismatch")
            result_version = (
                None
                if terminal.settings_result is None
                else terminal.settings_result.get("settings_version")
            )
            if (
                terminal.settings_result is None
                and terminal.settings_version != terminal.base_settings_version
            ) or (
                result_version is not None
                and result_version != terminal.settings_version
            ):
                raise KeyUnavailable("finalized owner settings result mismatch")
            finalized_owner_chain.append(
                (record_authority.base.generation, terminal)
            )
            if terminal.daily_result_digest is not None:
                daily_turn = self.daily_turn_for_record(terminal.record_id)
                if (
                    daily_turn is None
                    or daily_turn.phase != "finalized"
                    or daily_turn.terminal is None
                    or daily_turn.terminal.result_digest
                    != terminal.daily_result_digest
                ):
                    raise KeyUnavailable(
                        "finalized owner correction aggregate mismatch"
                    )
        if current_owner_settings is not None and not finalized_owner_chain:
            raise KeyUnavailable("owner settings aggregate has no terminal chain")
        finalized_owner_chain.sort(key=lambda item: item[0])
        if finalized_owner_chain:
            generations = tuple(item[0] for item in finalized_owner_chain)
            if len(set(generations)) != len(generations):
                raise KeyUnavailable("owner mutation generation chain mismatch")
            previous_settings_version = 1
            for _, terminal in finalized_owner_chain:
                if terminal.base_settings_version != previous_settings_version:
                    raise KeyUnavailable("owner settings version chain mismatch")
                previous_settings_version = terminal.settings_version
            if (
                current_owner_settings is None
                or previous_settings_version != current_owner_settings.version
                or finalized_owner_chain[-1][1].next_settings_digest
                != stable_digest(current_owner_settings.to_wire())
            ):
                raise KeyUnavailable("owner settings terminal digest mismatch")

        business_status_rows = self._execute(
            "SELECT nonce, ciphertext FROM business_status_v1 ORDER BY slot"
        ).fetchall()
        if len(business_status_rows) > 1:
            raise KeyUnavailable("multiple business status projections")
        if business_status_rows:
            self.business_status_projection()

        self._verify_ticket115_aggregates(current_owner_settings)

        # A terminal latch must itself be authenticated; its row is also part
        # of the signed inventory above, so raw deletion cannot silently reopen
        # the state domain.
        self.terminal_observed()
        self.current_head_observation_incomplete()

        if self._execute("SELECT 1 FROM receipts LIMIT 1").fetchone() is not None:
            # V1 rows do not retain an authenticated command/response pair and
            # therefore cannot prove an exact replay contract.
            raise KeyUnavailable("legacy receipt is unverifiable")
        return final_record_found

    def raw_storage_bytes(self) -> bytes:
        record_rows = self._execute(
            "SELECT record_id, state, revision_digest, transition_id, nonce, ciphertext FROM health_records"
        ).fetchall()
        effect_rows = self._execute("SELECT effect_id, state, nonce, ciphertext FROM effects").fetchall()
        authority_rows = self._execute(
            "SELECT nonce, ciphertext FROM finalized_authority"
        ).fetchall()
        receipt_rows = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM command_receipts_v2"
        ).fetchall()
        health_command_receipt_rows = self._execute(
            "SELECT causal_id, nonce, ciphertext "
            "FROM ticket115_health_command_receipts_v1"
        ).fetchall()
        pending_rows = self._execute(
            "SELECT causal_id, record_id, nonce, ciphertext FROM pending_commands_v1"
        ).fetchall()
        pending_effect_rows = self._execute(
            "SELECT effect_id, causal_id, nonce, ciphertext FROM pending_effect_results_v1"
        ).fetchall()
        terminal_rows = self._execute(
            "SELECT nonce, ciphertext FROM terminal_observation_v1"
        ).fetchall()
        observation_guard_rows = self._execute(
            "SELECT nonce, ciphertext FROM current_head_observation_guard_v1"
        ).fetchall()
        source_rows = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM source_envelopes_v1"
        ).fetchall()
        initialization_rows = self._execute(
            "SELECT record_id, phase, nonce, ciphertext FROM owner_initialization_v1"
        ).fetchall()
        daily_turn_rows = self._execute(
            "SELECT source_causal_id, record_id, phase, nonce, ciphertext "
            "FROM daily_turns_v1"
        ).fetchall()
        daily_state_rows = self._execute(
            "SELECT slot, nonce, ciphertext FROM daily_health_state_v1"
        ).fetchall()
        owner_settings_rows = self._execute(
            "SELECT slot, nonce, ciphertext FROM owner_settings_v1"
        ).fetchall()
        owner_mutation_rows = self._execute(
            "SELECT command_id, record_id, phase, nonce, ciphertext "
            "FROM owner_mutations_v1"
        ).fetchall()
        business_status_rows = self._execute(
            "SELECT slot, nonce, ciphertext FROM business_status_v1"
        ).fetchall()
        task_runtime_rows = self._execute(
            "SELECT slot, nonce, ciphertext FROM task_runtime_v1"
        ).fetchall()
        ticket115_mutation_rows = self._execute(
            "SELECT slot, record_id, nonce, ciphertext "
            "FROM ticket115_mutations_v1"
        ).fetchall()
        daily_review_rows = self._execute(
            "SELECT slot, nonce, ciphertext FROM daily_reviews_v1"
        ).fetchall()
        owner_outbox_rows = self._execute(
            "SELECT intent_id, state_version, phase, nonce, ciphertext "
            "FROM owner_outbox_v1"
        ).fetchall()
        owner_delivery_rows = self._execute(
            "SELECT observation_id, intent_id, layer, nonce, ciphertext "
            "FROM owner_delivery_observations_v1"
        ).fetchall()
        return repr(
            (
                record_rows,
                effect_rows,
                authority_rows,
                receipt_rows,
                health_command_receipt_rows,
                pending_rows,
                pending_effect_rows,
                terminal_rows,
                observation_guard_rows,
                source_rows,
                initialization_rows,
                daily_turn_rows,
                daily_state_rows,
                owner_settings_rows,
                owner_mutation_rows,
                business_status_rows,
                task_runtime_rows,
                ticket115_mutation_rows,
                daily_review_rows,
                owner_outbox_rows,
                owner_delivery_rows,
            )
        ).encode("utf-8")

    def _decode_pending(
        self,
        causal_id: str,
        record_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> PendingCommand:
        stored = self._open(f"pending:{causal_id}", nonce, ciphertext)
        if (
            not isinstance(stored, Mapping)
            or set(stored) != {"record_id", "command", "remote_attempted"}
        ):
            raise KeyUnavailable("invalid pending command")
        if (
            stored["record_id"] != record_id
            or not isinstance(stored["command"], Mapping)
            or not isinstance(stored["remote_attempted"], bool)
        ):
            raise KeyUnavailable("invalid pending command")
        try:
            command = CommandEnvelope.from_wire(stored["command"])
        except ProtocolViolation as exc:
            raise KeyUnavailable("invalid pending command") from exc
        if command.causal_id != causal_id:
            raise KeyUnavailable("invalid pending command")
        return PendingCommand(
            record_id=record_id,
            command=command,
            remote_attempted=stored["remote_attempted"],
        )

    def _decode_pending_effect_result(
        self,
        effect_id: str,
        causal_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> PendingEffectResult:
        attempt = PendingEffectResult.from_storage(
            self._open(f"pending-effect:{effect_id}", nonce, ciphertext)
        )
        if attempt.effect_id != effect_id or attempt.causal_id != causal_id:
            raise KeyUnavailable("invalid pending effect result")
        return attempt

    @staticmethod
    def _receipt_command_wire(command: CommandEnvelope) -> dict[str, object]:
        """Return an exact replay identity without persisting a bearer secret.

        Effect-result completion capabilities are transport-only.  Receipts
        retain a one-way holder binding instead, which still distinguishes the
        original causal command while preventing a state/key clone from
        recovering an active execution capability after a rejected response.
        """

        wire = command.to_wire()
        if command.action == "inbound.admit":
            payload = wire.get("payload")
            if not isinstance(payload, dict):
                raise KeyUnavailable("invalid inbound receipt")
            envelope = payload.get("envelope")
            if not isinstance(envelope, dict):
                raise KeyUnavailable("invalid inbound receipt")
            body = envelope.get("body")
            if type(body) is not str:
                raise KeyUnavailable("invalid inbound receipt")
            envelope["body"] = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
            return wire
        if command.action != "effect.result":
            return wire
        payload = wire["payload"]
        if not isinstance(payload, dict):
            raise KeyUnavailable("invalid effect result receipt")
        capability = payload.get("completion_capability")
        try:
            payload["completion_capability"] = holder_id_for(capability)
        except ValueError as exc:
            raise KeyUnavailable("invalid effect result receipt") from exc
        return wire

    @classmethod
    def _receipt_command_digest(cls, command: CommandEnvelope) -> str:
        """Bind the complete redacted receipt identity without retaining its body."""

        wire = cls._receipt_command_wire(command)
        try:
            canonical = json.dumps(
                wire,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
            raise KeyUnavailable("invalid receipt command") from exc
        return "sha256:" + hashlib.sha256(canonical).hexdigest()

    def _decode_receipt(
        self,
        causal_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> _ExactCommandReceipt | _DigestCommandReceipt:
        stored = self._open(f"receipt:v2:{causal_id}", nonce, ciphertext)
        if not isinstance(stored, Mapping):
            raise KeyUnavailable("invalid command receipt")
        stored_response = stored.get("response")
        if not isinstance(stored_response, Mapping):
            raise KeyUnavailable("invalid command receipt")
        try:
            response = Response.from_wire(stored_response)
        except ProtocolViolation as exc:
            raise KeyUnavailable("invalid command receipt") from exc
        if response.causal_id != causal_id:
            raise KeyUnavailable("invalid command receipt")
        if set(stored) == {"command", "response"}:
            stored_command = stored["command"]
            if not isinstance(stored_command, Mapping):
                raise KeyUnavailable("invalid command receipt")
            try:
                command = CommandEnvelope.from_wire(stored_command)
            except ProtocolViolation as exc:
                raise KeyUnavailable("invalid command receipt") from exc
            if command.causal_id != causal_id:
                raise KeyUnavailable("invalid command receipt")
            return _ExactCommandReceipt(command, response)
        if set(stored) != {"kind", "command_digest", "response"}:
            raise KeyUnavailable("invalid command receipt")
        command_digest = stored["command_digest"]
        if (
            stored["kind"] != "command-digest-v1"
            or type(command_digest) is not str
            or not command_digest.startswith("sha256:")
            or len(command_digest) != len("sha256:") + 64
        ):
            raise KeyUnavailable("invalid command receipt")
        try:
            int(command_digest.removeprefix("sha256:"), 16)
        except ValueError as exc:
            raise KeyUnavailable("invalid command receipt") from exc
        return _DigestCommandReceipt(command_digest, response)

    def _seal_finalized_authority(
        self,
        authority: AuthoritySnapshot,
        record_id: str | None,
    ) -> tuple[bytes, bytes]:
        if not isinstance(authority, AuthoritySnapshot):
            raise AuthorityValidationError("invalid finalized authority")
        if record_id is not None and (not isinstance(record_id, str) or not record_id):
            raise AuthorityValidationError("invalid finalized record identifier")
        return self._seal(
            "finalized-authority",
            {"authority": authority.to_storage(), "record_id": record_id},
        )

    @staticmethod
    def _validate_record_write(
        record_id: str,
        state: str,
        revision_digest: str,
        transition_id: str,
        payload: RevisionTarget | PreparedTransition | CommittedTransition,
    ) -> None:
        if state == "candidate" and type(payload) is RevisionTarget:
            target = payload
        elif state in {"prepared", "unknown"} and type(payload) is PreparedTransition:
            target = payload.target
        elif state in {"committed", "final"} and type(payload) is CommittedTransition:
            target = validate_committed_transition(payload).prepared.target
        else:
            raise AuthorityValidationError("record state and payload mismatch")
        if (
            record_id != target.record_id
            or revision_digest != target.revision_digest
            or transition_id != target.transition_id
        ):
            raise AuthorityValidationError("record target mismatch")

    @staticmethod
    def _validate_effect_write(
        effect_id: str,
        state: str,
        payload: EffectIntent | ClaimingEffect | ExecutingEffect | TerminalEffect,
    ) -> None:
        if state == "intent" and type(payload) is EffectIntent:
            intent = payload
        elif state == "claiming" and type(payload) is ClaimingEffect:
            intent = payload.intent
        elif state == "executing" and type(payload) is ExecutingEffect:
            intent = payload.intent
        elif state in {"accepted", "rejected", "unknown"} and type(payload) is TerminalEffect:
            if state != payload.status:
                raise AuthorityValidationError("effect terminal state mismatch")
            intent = payload.intent
        else:
            raise AuthorityValidationError("effect state and payload mismatch")
        if effect_id != intent.effect_id:
            raise AuthorityValidationError("effect identifier mismatch")
        validate_controlled_effect_kind(intent.effect_kind)

    @staticmethod
    def _decode_record_payload(
        state: str,
        value: object,
    ) -> RevisionTarget | PreparedTransition | CommittedTransition:
        try:
            if state == "candidate":
                return RevisionTarget.from_storage(value)
            if state in {"prepared", "unknown"}:
                return PreparedTransition.from_storage(value)
            if state in {"committed", "final"}:
                return CommittedTransition.from_storage(value)
        except AuthorityValidationError as exc:
            raise KeyUnavailable("invalid transition record") from exc
        raise KeyUnavailable("invalid transition record state")

    @staticmethod
    def _decode_effect_payload(
        state: str,
        value: object,
    ) -> EffectIntent | ClaimingEffect | ExecutingEffect | TerminalEffect:
        try:
            if state == "intent":
                return EffectIntent.from_storage(value)
            if state == "claiming":
                return ClaimingEffect.from_storage(value)
            if state == "executing":
                return ExecutingEffect.from_storage(value)
            if state in {"accepted", "rejected", "unknown"}:
                return TerminalEffect.from_storage(value)
        except AuthorityValidationError as exc:
            raise KeyUnavailable("invalid effect record") from exc
        raise KeyUnavailable("invalid effect record state")

    @staticmethod
    def _write_record_row(
        connection: sqlite3.Connection,
        record_id: str,
        state: str,
        revision_digest: str,
        transition_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> None:
        connection.execute(
            """
            INSERT INTO health_records(record_id, state, revision_digest, transition_id, nonce, ciphertext)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id) DO UPDATE SET state=excluded.state,
                revision_digest=excluded.revision_digest, transition_id=excluded.transition_id,
                nonce=excluded.nonce, ciphertext=excluded.ciphertext
            """,
            (record_id, state, revision_digest, transition_id, nonce, ciphertext),
        )

    @staticmethod
    def _write_finalized_authority_row(
        connection: sqlite3.Connection,
        nonce: bytes,
        ciphertext: bytes,
    ) -> None:
        connection.execute(
            """
            INSERT INTO finalized_authority(slot, nonce, ciphertext)
            VALUES (1, ?, ?)
            ON CONFLICT(slot) DO UPDATE SET nonce=excluded.nonce, ciphertext=excluded.ciphertext
            """,
            (nonce, ciphertext),
        )

    def close(self) -> None:
        self._connection.close()

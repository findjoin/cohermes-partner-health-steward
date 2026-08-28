"""Body-free lifecycle coordination for the Ticket 117 public seam."""

from __future__ import annotations

import copy
import sqlite3
from collections.abc import Callable, Mapping
from typing import Any

from .authority import AuthoritySnapshot, AuthorityValidationError, validate_opaque_text
from .current_head import (
    AppliedLifecycleTransition,
    HeadConflict,
    HeadSnapshot,
    HeadTimeout,
    HeadUnknown,
    LifecycleTransitionIdentity,
    LifecycleTransitionRequest,
    TransitionNotFound,
)
from .initialization import stable_digest
from .storage import EncryptedStateStore, KeyUnavailable, StoreUnavailable


LIFECYCLE_DELETE_SEMANTICS = "permanent-delete-all-health-data"
LIFECYCLE_REGISTRY_FAMILIES = (
    "authority-receipt-guard",
    "initialization",
    "source",
    "portrait",
    "evidence",
    "rights",
    "settings-control-approval",
    "task-review",
    "model",
    "diagnosis-safety",
    "support-contact",
    "business-status",
    "outbox-delivery-unknown",
    "lifecycle-migration-staging",
)
LIFECYCLE_PURGE_BINDINGS = tuple(
    f"purge:{family}:v1" for family in LIFECYCLE_REGISTRY_FAMILIES
)
LIFECYCLE_CONFIG_FIELDS = frozenset(
    {
        "contract",
        "mode",
        "semantic_registry",
        "release",
        "destroyable_key_adapter",
        "managed_replica_adapter",
        "migration_artifact_adapter",
    }
)
LIFECYCLE_RELEASE_FIELDS = frozenset(
    {
        "product_release",
        "adr",
        "skills",
        "plugin_core_bundle",
        "adapter_model_interface_bundle",
        "knowledge_safety_diagnostic_bundle",
        "hermes_artifact",
        "required_patch",
        "disabled_native_entry_assertion",
        "schema",
        "observer_identity",
        "acl_service",
        "secret_requirements",
        "unbound_real_providers",
    }
)
LIFECYCLE_STORAGE_TABLES = frozenset(
    {
        "health_records",
        "effects",
        "finalized_authority",
        "receipts",
        "command_receipts_v2",
        "pending_commands_v1",
        "pending_effect_results_v1",
        "key_check",
        "integrity_manifest_v1",
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
    }
)


def _sha256(value: object, name: str) -> str:
    if type(value) is not str or not value.startswith("sha256:") or len(value) != 71:
        raise ValueError(f"invalid {name}")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ValueError(f"invalid {name}") from exc
    return value


def _copy(value: object) -> object:
    return copy.deepcopy(value)


def _authority(value: object) -> AuthoritySnapshot:
    if type(value) is not dict:
        raise ValueError("invalid lifecycle authority")
    return AuthoritySnapshot.from_storage(value)


def _authority_wire(value: AuthoritySnapshot) -> dict[str, object]:
    return value.to_storage()


class LifecycleCoordinator:
    """Own the one deep lifecycle workflow behind the plugin's public seam."""

    def __init__(
        self,
        store: EncryptedStateStore,
        *,
        current_head_read: Callable[[], AuthoritySnapshot],
        writer_proof: Callable[[AuthoritySnapshot], object],
        transition: Callable[[LifecycleTransitionRequest], AuthoritySnapshot],
        lookup: Callable[[LifecycleTransitionIdentity], AppliedLifecycleTransition],
        replace_authority: Callable[[AuthoritySnapshot], None],
        form_notice: Callable[[str, Mapping[str, object]], str],
        notice_layer: Callable[[str], str | None],
        route_and_consent_current: Callable[[], bool],
        config: Mapping[str, object] | None,
    ) -> None:
        self._store = store
        self._current_head_read = current_head_read
        self._writer_proof = writer_proof
        self._transition = transition
        self._lookup = lookup
        self._replace_authority = replace_authority
        self._form_notice = form_notice
        self._notice_layer = notice_layer
        self._route_and_consent_current = route_and_consent_current
        self._config = config
        self._states: dict[str, dict[str, object]] = {}
        self._configuration_error: str | None = None
        self._recover_unknown_transitions()

    @property
    def config(self) -> Mapping[str, object] | None:
        return self._config

    def _load(self, operation_ref: str) -> dict[str, object] | None:
        cached = self._states.get(operation_ref)
        try:
            state = self._store.lifecycle_state(operation_ref)
        except (KeyUnavailable, StoreUnavailable, sqlite3.Error):
            state = None
        if state is not None:
            self._states[operation_ref] = state
            return state
        return cached

    def _all_states(self) -> tuple[dict[str, object], ...]:
        try:
            states = self._store.lifecycle_states()
        except (KeyUnavailable, StoreUnavailable, sqlite3.Error):
            states = ()
        if states:
            for state in states:
                operation_ref = state.get("operation_ref")
                if type(operation_ref) is str:
                    self._states[operation_ref] = state
            return states
        return tuple(self._states.values())

    def _save(self, state: dict[str, object]) -> None:
        self._store.save_lifecycle_state(state)
        self._states[state["operation_ref"]] = copy.deepcopy(state)  # type: ignore[index]

    def _valid_configuration(self) -> bool:
        self._configuration_error = None
        config = self._config
        try:
            if type(config) is not dict or frozenset(config) != LIFECYCLE_CONFIG_FIELDS:
                raise ValueError("configuration fields")
            if config["contract"] != "ticket117-lifecycle-config-v1":
                raise ValueError("configuration contract")
            mode = config["mode"]
            if mode not in {"source", "offline-staging"}:
                raise ValueError("configuration mode")
            registry = config["semantic_registry"]
            if type(registry) is not list or len(registry) != len(LIFECYCLE_REGISTRY_FAMILIES):
                raise ValueError("semantic registry cardinality")
            seen: set[str] = set()
            for entry in registry:
                if type(entry) is not dict or frozenset(entry) != frozenset(
                    {"family", "snapshot_codec", "purge_binding", "source_continuity"}
                ):
                    raise ValueError("semantic registry entry")
                family = entry["family"]
                if (
                    type(family) is not str
                    or family not in LIFECYCLE_REGISTRY_FAMILIES
                    or family in seen
                    or entry["snapshot_codec"] != f"codec:{family}:v1"
                    or entry["purge_binding"] != f"purge:{family}:v1"
                    or entry["source_continuity"] != "preserve"
                ):
                    raise ValueError("semantic registry value")
                seen.add(family)
            if seen != set(LIFECYCLE_REGISTRY_FAMILIES):
                raise ValueError("semantic registry set")
            release = config["release"]
            if type(release) is not dict or frozenset(release) != LIFECYCLE_RELEASE_FIELDS:
                raise ValueError("release fields")
            if release["disabled_native_entry_assertion"] is not True:
                raise ValueError("native entry assertion")
            if release["schema"] != "ticket117-semantic-state-v1":
                raise ValueError("semantic schema")
            requirements = release["secret_requirements"]
            if requirements != ["health-key-ref", "target-fence-ref"]:
                raise ValueError("secret requirements")
            if type(release["skills"]) is not list or not all(
                type(item) is str for item in release["skills"]
            ):
                raise ValueError("release skills")
            for key in (
                "product_release",
                "adr",
                "plugin_core_bundle",
                "adapter_model_interface_bundle",
                "knowledge_safety_diagnostic_bundle",
                "hermes_artifact",
                "required_patch",
                "observer_identity",
                "acl_service",
            ):
                if type(release[key]) is not str or not release[key]:
                    raise ValueError("release value")
            providers = release["unbound_real_providers"]
            if type(providers) is not list or not all(type(item) is str for item in providers):
                raise ValueError("unbound provider list")
            if self._store.lifecycle_table_names() != tuple(sorted(LIFECYCLE_STORAGE_TABLES)):
                raise ValueError("managed storage inventory")
            key_adapter = config["destroyable_key_adapter"]
            replica_adapter = config["managed_replica_adapter"]
            artifact_adapter = config["migration_artifact_adapter"]
            if any(
                not callable(getattr(adapter, method, None))
                for adapter, methods in (
                    (key_adapter, ("destroy", "absence")),
                    (replica_adapter, ("enumerate", "purge", "absence")),
                    (artifact_adapter, ("put", "get", "remove")),
                )
                for method in methods
            ):
                raise ValueError("adapter role")
            enumeration = replica_adapter.enumerate(
                {"installation_id": self._installation_id()}
            )
            if type(enumeration) is not dict:
                raise ValueError("replica enumeration")
            configured = enumeration.get("configured")
            remains = enumeration.get("remains_unproven")
            if type(configured) is not list or type(remains) is not list:
                raise ValueError("replica enumeration shape")
            if set(configured) != set(LIFECYCLE_PURGE_BINDINGS) or len(configured) != len(
                LIFECYCLE_PURGE_BINDINGS
            ):
                raise ValueError("replica binding set")
            if providers != remains:
                raise ValueError("unbound provider facts")
        except (AuthorityValidationError, KeyUnavailable, StoreUnavailable, TypeError, ValueError):
            self._configuration_error = "lifecycle-configuration-invalid"
            return False
        return True

    def _installation_id(self) -> str:
        try:
            authority = self._current_head_read()
            return authority.installation_id
        except Exception:
            for state in self._all_states():
                authority = state.get("authority_binding")
                if type(authority) is dict and type(authority.get("installation_id")) is str:
                    return authority["installation_id"]  # type: ignore[return-value]
            return "unknown-installation"

    def _current_head(self) -> AuthoritySnapshot:
        authority = self._current_head_read()
        if type(authority) is not AuthoritySnapshot:
            raise AuthorityValidationError("current lifecycle authority unavailable")
        return authority

    @staticmethod
    def _payload_digest(payload: Mapping[str, object]) -> str:
        return stable_digest(dict(payload))

    @staticmethod
    def _request_digest(kind: str, operation_ref: str, payload_digest: str) -> str:
        return stable_digest(
            {
                "contract": "ticket117-lifecycle-transition-v1",
                "kind": kind,
                "operation_ref": operation_ref,
                "payload_digest": payload_digest,
            }
        )

    @staticmethod
    def _transition_id(kind: str, operation_ref: str) -> str:
        prefix = "terminal-delete" if kind == "delete-all" else "writer-transfer"
        return f"lifecycle:{prefix}:{operation_ref}"

    def _new_state(
        self,
        *,
        operation_ref: str,
        kind: str,
        payload_digest: str,
        authority: AuthoritySnapshot,
        phase: str,
        source_active: bool,
        target_active: bool,
    ) -> dict[str, object]:
        return {
            "operation_ref": operation_ref,
            "kind": kind,
            "payload_digest": payload_digest,
            "phase": phase,
            "source_active": source_active,
            "target_active": target_active,
            "authority_binding": _authority_wire(authority),
            "expected_authority": _authority_wire(authority),
            "transition_kind": (
                "terminal-delete" if kind == "delete-all" else "writer-transfer"
            ),
            "transition_id": self._transition_id(kind, operation_ref),
            "operation_digest": self._request_digest(kind, operation_ref, payload_digest),
            "revision_digest": authority.revision_digest,
            "writer_fence": authority.writer_fence,
            "target_site": None,
            "target_writer_fence_ref": None,
            "package_ref": None,
            "manifest_digest": None,
            "notice_ref": None,
            "target_accepted": False,
            "reason_code": None,
            "remains_unproven": [],
        }

    def _state_result(
        self,
        state: Mapping[str, object],
        *,
        status: str | None = None,
        reason_code: str | None = None,
        authority: AuthoritySnapshot | None = None,
    ) -> dict[str, object]:
        phase = state.get("phase")
        if status is None:
            status = {
                "notice-pending": "notice-pending",
                "manifest-ready": "manifest-ready",
                "target-staged": "manifest-ready",
                "transferred": "completed",
                "completed": "completed",
                "terminal-unknown": "unknown",
                "transfer-unknown": "unknown",
                "transfer-conflict": "rejected",
                "frozen": "rejected",
                "terminal-confirmed-cleanup-pending": "unknown",
                "cleanup-pending": "unknown",
            }.get(phase, "rejected")
        if authority is None:
            authority = self._authority_for_read(state)
        result: dict[str, object] = {
            "status": status,
            "operation_ref": state.get("operation_ref"),
            "phase": phase,
            "package_ref": state.get("package_ref"),
            "manifest_ref": state.get("package_ref"),
            "manifest_digest": state.get("manifest_digest"),
            "source_active": state.get("source_active", False),
            "target_active": state.get("target_active", False),
            "reason_code": (
                state.get("reason_code") if reason_code is None else reason_code
            ),
            "remains_unproven": list(state.get("remains_unproven", [])),
        }
        result["authority_binding"] = _authority_wire(authority)
        return result

    def _authority_for_read(self, state: Mapping[str, object]) -> AuthoritySnapshot:
        try:
            return self._current_head()
        except Exception:
            try:
                return _authority(state["authority_binding"])
            except (KeyError, TypeError, ValueError, AuthorityValidationError):
                return AuthoritySnapshot(
                    installation_id="unknown-installation",
                    generation=1,
                    revision_digest="sha256:" + "0" * 64,
                    transition_id="transition:unknown",
                    writer_fence="fence:unknown",
                    terminal=True,
                    site="unknown-site",
                )

    def _read_derived_terminal(self, operation_ref: str | None) -> dict[str, object] | None:
        try:
            authority = self._current_head()
        except Exception:
            return None
        if not authority.terminal or not authority.transition_id.startswith(
            "lifecycle:terminal-delete:"
        ):
            return None
        derived_ref = authority.transition_id.removeprefix("lifecycle:terminal-delete:")
        if operation_ref is not None and derived_ref != operation_ref:
            return None
        state = self._new_state(
            operation_ref=derived_ref,
            kind="delete-all",
            payload_digest=stable_digest({"derived": derived_ref}),
            authority=authority,
            phase="completed",
            source_active=False,
            target_active=False,
        )
        state["authority_binding"] = _authority_wire(authority)
        state["expected_authority"] = _authority_wire(authority)
        state["remains_unproven"] = self._configured_unproven_providers()
        return state

    def _configured_unproven_providers(self) -> list[object]:
        config = self._config
        if type(config) is dict and type(config.get("release")) is dict:
            providers = config["release"].get("unbound_real_providers")
            if type(providers) is list:
                return list(providers)
        return []

    def read(self, operation_ref: str | None) -> dict[str, object]:
        if operation_ref is not None:
            validate_opaque_text(operation_ref, "lifecycle operation reference")
        state = None if operation_ref is None else self._load(operation_ref)
        if state is None:
            derived = self._read_derived_terminal(operation_ref)
            if derived is not None:
                state = derived
            elif operation_ref is None:
                states = self._all_states()
                state = None if not states else states[-1]
        if state is None:
            try:
                authority = self._current_head()
            except Exception:
                authority = AuthoritySnapshot(
                    installation_id="unknown-installation",
                    generation=1,
                    revision_digest="sha256:" + "0" * 64,
                    transition_id="transition:unknown",
                    writer_fence="fence:unknown",
                    terminal=False,
                    site="unknown-site",
                )
            mode = self._config.get("mode") if type(self._config) is dict else "source"
            return {
                "operation_ref": None,
                "phase": "idle",
                "mode": mode,
                "source_active": mode == "source" and not authority.terminal,
                "target_active": False,
                "package_ref": None,
                "manifest_ref": None,
                "manifest_digest": None,
                "reason_code": None,
                "remains_unproven": [],
                "authority_binding": _authority_wire(authority),
            }
        result = self._state_result(state, status=None)
        if state.get("kind") == "delete-all" and state.get("phase") == "completed":
            result["mode"] = "terminal"
        elif state.get("target_active") is True:
            result["mode"] = "active"
        else:
            result["mode"] = (
                self._config.get("mode") if type(self._config) is dict else "source"
            )
        return result

    def configuration_healthy(self) -> bool:
        if self._read_derived_terminal(None) is not None:
            return False
        state = self._latest_operational_state()
        if state is not None and state.get("phase") in {
            "frozen",
            "terminal-pending",
            "terminal-confirmed-cleanup-pending",
            "cleanup-pending",
            "terminal-unknown",
            "transfer-pending",
            "transfer-unknown",
            "transfer-conflict",
        }:
            return False
        return self._valid_configuration()

    def blocks_normal_operations(self) -> bool:
        if self._read_derived_terminal(None) is not None:
            return True
        if not self._valid_configuration():
            return True
        state = self._latest_operational_state()
        if state is None:
            return type(self._config) is dict and self._config.get("mode") == "offline-staging"
        phase = state.get("phase")
        if state.get("kind") == "delete-all":
            return phase != "notice-pending"
        if self._config.get("mode") == "offline-staging":  # type: ignore[union-attr]
            return state.get("target_active") is not True
        return state.get("source_active") is not True or phase != "manifest-ready"

    def allows_pre_freeze_effect_overlap(self) -> bool:
        """Allow already-admitted work to finish before the terminal CAS."""

        if not self._valid_configuration():
            return False
        if self._config.get("mode") != "source":  # type: ignore[union-attr]
            return False
        state = self._latest_operational_state()
        return bool(
            state is not None
            and state.get("kind") == "delete-all"
            and state.get("phase") == "notice-pending"
            and state.get("source_active") is True
        )

    def probe_allowed(self) -> tuple[bool, str]:
        if self._read_derived_terminal(None) is not None:
            return False, "current-head-terminal"
        state = self._latest_operational_state()
        if not self._valid_configuration():
            return False, self._configuration_error or "lifecycle-configuration-invalid"
        if type(self._config) is dict and self._config.get("mode") == "offline-staging":
            if state is None or state.get("target_active") is not True:
                return False, "lifecycle-target-not-active"
        elif state is not None and state.get("source_active") is not True:
            return False, "lifecycle-frozen"
        return True, "contract-ok"

    def _latest_operational_state(self) -> dict[str, object] | None:
        states = self._all_states()
        if not states:
            return None
        # A terminal/frozen state is the only safe winner if more than one
        # lifecycle record is present in a copied domain.
        for state in states:
            if state.get("phase") in {
                "completed",
                "terminal-unknown",
                "terminal-confirmed-cleanup-pending",
                "transfer-unknown",
                "transfer-conflict",
            }:
                return state
        return states[-1]

    def execute(self, command: Any) -> dict[str, object]:
        payload = command.payload
        if type(payload) is not dict or payload.get("kind") not in {
            "delete-all",
            "prepare-migration",
            "accept-migration",
        }:
            return {"status": "rejected", "reason_code": "invalid-lifecycle-payload"}
        if payload["kind"] == "delete-all":
            return self._execute_delete(command, payload)
        if payload["kind"] == "prepare-migration":
            return self._execute_prepare_migration(command, payload)
        return self._execute_accept_migration(command, payload)

    @staticmethod
    def _strict_fields(payload: Mapping[str, object], fields: frozenset[str]) -> bool:
        return frozenset(payload) == fields

    def _new_command_authority_ok(
        self,
        command: Any,
        authority: AuthoritySnapshot,
    ) -> bool:
        return command.generation == authority.generation

    def _execute_delete(self, command: Any, payload: dict[str, object]) -> dict[str, object]:
        if not self._strict_fields(
            payload,
            frozenset({"kind", "operation_ref", "owner_command_ref", "semantics"}),
        ):
            return {"status": "rejected", "reason_code": "invalid-delete-fields"}
        operation_ref = payload.get("operation_ref")
        if (
            type(operation_ref) is not str
            or payload.get("semantics") != LIFECYCLE_DELETE_SEMANTICS
            or payload.get("owner_command_ref") != f"owner-command:{operation_ref}"
        ):
            return {"status": "rejected", "reason_code": "delete-semantics-not-exact"}
        state = self._load(operation_ref)
        payload_digest = self._payload_digest(payload)
        if state is not None:
            if state.get("kind") != "delete-all" or state.get("payload_digest") != payload_digest:
                return {"status": "rejected", "reason_code": "lifecycle-operation-conflict"}
            if state.get("phase") == "notice-pending":
                layer = self._notice_layer(operation_ref)
                if layer in {"accepted", "delivered", "read"}:
                    return self._complete_delete(state)
                if layer == "unknown":
                    state["phase"] = "terminal-unknown"
                    state["reason_code"] = "lifecycle-notice-unknown"
                    self._save(state)
                    return self._state_result(state, status="unknown")
                return self._state_result(state, status="notice-pending")
            return self._state_result(state)
        if not self._valid_configuration():
            return {"status": "rejected", "reason_code": self._configuration_error}
        try:
            authority = self._current_head()
            if authority.terminal or not self._new_command_authority_ok(command, authority):
                return {"status": "rejected", "reason_code": "generation-mismatch"}
            notice_ref = self._form_notice(operation_ref, payload)
            authority = self._current_head()
            state = self._new_state(
                operation_ref=operation_ref,
                kind="delete-all",
                payload_digest=payload_digest,
                authority=authority,
                phase="notice-pending",
                source_active=True,
                target_active=False,
            )
            state["notice_ref"] = notice_ref
            self._save(state)
            return self._state_result(state, status="notice-pending", authority=authority)
        except Exception:
            return {"status": "rejected", "reason_code": "lifecycle-preparation-unavailable"}

    def _lifecycle_identity(self, state: Mapping[str, object]) -> LifecycleTransitionIdentity:
        expected = _authority(state["expected_authority"])
        return LifecycleTransitionIdentity(
            kind=state["transition_kind"],  # type: ignore[arg-type]
            expected=expected,
            operation_ref=state["operation_ref"],  # type: ignore[arg-type]
            transition_id=state["transition_id"],  # type: ignore[arg-type]
            revision_digest=state["revision_digest"],  # type: ignore[arg-type]
            writer_fence=state["writer_fence"],  # type: ignore[arg-type]
            operation_digest=state["operation_digest"],  # type: ignore[arg-type]
            target_site=state.get("target_site"),  # type: ignore[arg-type]
            target_writer_fence_ref=state.get("target_writer_fence_ref"),  # type: ignore[arg-type]
        )

    def _complete_delete(self, state: dict[str, object]) -> dict[str, object]:
        try:
            authority = self._current_head()
            proof = self._writer_proof(authority)
            if proof is None:
                raise AuthorityValidationError("current-writer-holder-missing")
            state["phase"] = "frozen"
            state["source_active"] = False
            state["target_active"] = False
            state["expected_authority"] = _authority_wire(authority)
            state["authority_binding"] = _authority_wire(authority)
            state["revision_digest"] = authority.revision_digest
            state["writer_fence"] = authority.writer_fence
            self._save(state)
            request = LifecycleTransitionRequest(
                kind="terminal-delete",
                expected=authority,
                operation_ref=state["operation_ref"],  # type: ignore[arg-type]
                transition_id=state["transition_id"],  # type: ignore[arg-type]
                revision_digest=authority.revision_digest,
                writer_fence=authority.writer_fence,
                operation_digest=state["operation_digest"],  # type: ignore[arg-type]
                writer_proof=proof,
            )
            try:
                applied = self._transition(request)
            except HeadConflict:
                state["reason_code"] = "current-head-conflict"
                self._save(state)
                return self._state_result(state, status="rejected", reason_code=state["reason_code"])
            except (HeadUnknown, HeadTimeout):
                state["phase"] = "terminal-unknown"
                state["reason_code"] = "current-head-unknown"
                self._save(state)
                return self._state_result(state, status="unknown")
            except Exception:
                state["phase"] = "terminal-unknown"
                state["reason_code"] = "current-head-unavailable"
                self._save(state)
                return self._state_result(state, status="unknown")
            state["phase"] = "terminal-confirmed-cleanup-pending"
            state["authority_binding"] = _authority_wire(applied)
            self._save(state)
            return self._cleanup_delete(state, applied)
        except Exception:
            state["phase"] = "frozen"
            state["reason_code"] = "lifecycle-freeze-unavailable"
            try:
                self._save(state)
            except Exception:
                pass
            return self._state_result(state, status="rejected")

    def _cleanup_delete(
        self,
        state: dict[str, object],
        authority: AuthoritySnapshot,
    ) -> dict[str, object]:
        request = {
            "operation_ref": state["operation_ref"],
            "authority_binding": _authority_wire(authority),
            "transition_id": state["transition_id"],
        }
        key_adapter = self._config["destroyable_key_adapter"]  # type: ignore[index]
        replica_adapter = self._config["managed_replica_adapter"]  # type: ignore[index]
        try:
            destroyed = key_adapter.destroy(request)
            if type(destroyed) is not dict or destroyed.get("status") != "confirmed":
                raise ValueError("key destruction unconfirmed")
            absent = key_adapter.absence(request)
            if type(absent) is not dict or absent.get("status") != "absent":
                raise ValueError("key absence unconfirmed")
        except Exception:
            state["phase"] = "terminal-confirmed-cleanup-pending"
            state["reason_code"] = "key-destruction-unknown"
            try:
                self._save(state)
            except Exception:
                pass
            return self._state_result(state, status="unknown")
        try:
            purged = replica_adapter.purge(request)
            if type(purged) is not dict or purged.get("status") != "confirmed":
                raise ValueError("replica purge unconfirmed")
            absent = replica_adapter.absence(request)
            if type(absent) is not dict or absent.get("status") != "absent":
                raise ValueError("replica absence unconfirmed")
            remains = absent.get("remains_unproven", self._configured_unproven_providers())
            if type(remains) is not list:
                raise ValueError("replica absence facts")
            state["remains_unproven"] = list(remains)
        except Exception:
            state["phase"] = "cleanup-pending"
            state["reason_code"] = "replica-cleanup-unknown"
            try:
                self._save(state)
            except Exception:
                pass
            return self._state_result(state, status="unknown")
        state["phase"] = "completed"
        state["source_active"] = False
        state["target_active"] = False
        state["reason_code"] = None
        try:
            self._save(state)
            self._store.purge_all_local_state()
        except Exception:
            state["phase"] = "cleanup-pending"
            state["reason_code"] = "local-purge-unavailable"
            try:
                self._save(state)
            except Exception:
                pass
            return self._state_result(state, status="unknown")
        return self._state_result(state, status="completed", authority=authority)

    def _execute_prepare_migration(
        self,
        command: Any,
        payload: dict[str, object],
    ) -> dict[str, object]:
        fields = frozenset(
            {
                "kind",
                "operation_ref",
                "target_site",
                "target_writer_fence_ref",
                "artifact_sink_ref",
            }
        )
        if not self._strict_fields(payload, fields):
            return {"status": "rejected", "reason_code": "invalid-migration-fields"}
        operation_ref = payload.get("operation_ref")
        target_site = payload.get("target_site")
        target_fence = payload.get("target_writer_fence_ref")
        sink_ref = payload.get("artifact_sink_ref")
        if not all(type(value) is str and bool(value) for value in (operation_ref, target_site, target_fence, sink_ref)):
            return {"status": "rejected", "reason_code": "invalid-migration-reference"}
        payload_digest = self._payload_digest(payload)
        state = self._load(operation_ref)  # type: ignore[arg-type]
        if state is not None:
            if state.get("kind") != "prepare-migration" or state.get("payload_digest") != payload_digest:
                return {"status": "rejected", "reason_code": "lifecycle-operation-conflict"}
            if state.get("target_accepted") is True and state.get("phase") in {
                "manifest-ready",
                "target-staged",
            }:
                return self._complete_transfer(state)
            return self._state_result(state)
        if not self._valid_configuration():
            return {"status": "rejected", "reason_code": self._configuration_error}
        try:
            authority = self._current_head()
            if authority.terminal or not self._new_command_authority_ok(command, authority):
                return {"status": "rejected", "reason_code": "generation-mismatch"}
            proof = self._writer_proof(authority)
            if proof is None:
                return {"status": "rejected", "reason_code": "current-writer-holder-missing"}
            registry = copy.deepcopy(self._config["semantic_registry"])  # type: ignore[index]
            release = copy.deepcopy(self._config["release"])  # type: ignore[index]
            package_ref = f"lifecycle-package:{operation_ref}"
            manifest = {
                "contract": "ticket117-semantic-manifest-v1",
                "operation_ref": operation_ref,
                "source_authority": _authority_wire(authority),
                "semantic_registry": registry,
                "release": release,
                "target_site": target_site,
                "target_writer_fence_ref": target_fence,
                "artifact_sink_ref": sink_ref,
                "semantic_state_digest": stable_digest(
                    {
                        "contract": "ticket117-semantic-continuity-v1",
                        "source_authority": _authority_wire(authority),
                        "source_continuity": "preserve",
                    }
                ),
            }
            package: dict[str, object] = {
                "contract": "ticket117-opaque-migration-package-v1",
                "manifest": manifest,
            }
            manifest_digest = stable_digest(package)
            artifact = self._config["migration_artifact_adapter"]  # type: ignore[index]
            stored = artifact.put(package_ref, package)
            if type(stored) is not dict or stored.get("status") != "confirmed":
                return {"status": "rejected", "reason_code": "migration-artifact-unavailable"}
            state = self._new_state(
                operation_ref=operation_ref,  # type: ignore[arg-type]
                kind="prepare-migration",
                payload_digest=payload_digest,
                authority=authority,
                phase="manifest-ready",
                source_active=True,
                target_active=False,
            )
            state.update(
                {
                    "target_site": target_site,
                    "target_writer_fence_ref": target_fence,
                    "artifact_sink_ref": sink_ref,
                    "package_ref": package_ref,
                    "manifest_digest": manifest_digest,
                    "manifest": manifest,
                }
            )
            self._save(state)
            result = self._state_result(state, status="manifest-ready", authority=authority)
            result["package_ref"] = package_ref
            result["manifest_ref"] = package_ref
            result["manifest_digest"] = manifest_digest
            return result
        except Exception:
            return {"status": "rejected", "reason_code": "migration-preparation-unavailable"}

    def _execute_accept_migration(
        self,
        command: Any,
        payload: dict[str, object],
    ) -> dict[str, object]:
        fields = frozenset({"kind", "operation_ref", "package_ref", "manifest_digest"})
        if not self._strict_fields(payload, fields):
            return {"status": "rejected", "reason_code": "invalid-accept-fields"}
        operation_ref = payload.get("operation_ref")
        package_ref = payload.get("package_ref")
        manifest_digest = payload.get("manifest_digest")
        if not all(type(value) is str and bool(value) for value in (operation_ref, package_ref)):
            return {"status": "rejected", "reason_code": "invalid-accept-reference"}
        try:
            _sha256(manifest_digest, "migration manifest digest")
        except ValueError:
            return {"status": "rejected", "reason_code": "invalid-manifest-digest"}
        state = self._load(operation_ref)  # type: ignore[arg-type]
        if state is None or state.get("kind") != "prepare-migration":
            return {"status": "rejected", "reason_code": "migration-manifest-missing"}
        if state.get("package_ref") != package_ref or state.get("manifest_digest") != manifest_digest:
            return self._state_result(state, status="rejected", reason_code="migration-manifest-mismatch")
        if state.get("target_accepted") is True:
            return self._state_result(state, status="manifest-ready")
        if not self._valid_configuration():
            return self._state_result(state, status="rejected", reason_code=self._configuration_error)
        if not self._route_and_consent_current():
            return self._state_result(state, status="rejected", reason_code="route-consent-not-current")
        try:
            authority = self._current_head()
            if authority.terminal or not self._new_command_authority_ok(command, authority):
                return self._state_result(state, status="rejected", reason_code="generation-mismatch")
            source_authority = _authority(state["authority_binding"])
            if authority.installation_id != source_authority.installation_id or authority != source_authority:
                return self._state_result(state, status="rejected", reason_code="source-authority-mismatch")
            artifact = self._config["migration_artifact_adapter"]  # type: ignore[index]
            package = artifact.get(package_ref)
            if type(package) is not dict or stable_digest(package) != manifest_digest:
                return self._state_result(state, status="rejected", reason_code="migration-artifact-integrity")
            manifest = package.get("manifest")
            if type(manifest) is not dict or package.get("contract") != "ticket117-opaque-migration-package-v1":
                return self._state_result(state, status="rejected", reason_code="migration-manifest-invalid")
            if (
                manifest.get("operation_ref") != operation_ref
                or manifest.get("source_authority") != _authority_wire(source_authority)
                or manifest.get("semantic_registry") != self._config["semantic_registry"]  # type: ignore[index]
                or manifest.get("release") != self._config["release"]  # type: ignore[index]
                or manifest.get("target_site") != state.get("target_site")
                or manifest.get("target_writer_fence_ref") != state.get("target_writer_fence_ref")
            ):
                return self._state_result(state, status="rejected", reason_code="migration-manifest-configuration")
            state["target_accepted"] = True
            state["source_active"] = False
            state["target_active"] = False
            state["phase"] = "target-staged"
            state["manifest"] = manifest
            self._save(state)
            return self._state_result(state, status="manifest-ready", authority=authority)
        except Exception:
            return self._state_result(state, status="rejected", reason_code="migration-acceptance-unavailable")

    def _complete_transfer(self, state: dict[str, object]) -> dict[str, object]:
        try:
            authority = self._current_head()
            proof = self._writer_proof(authority)
            if proof is None:
                raise AuthorityValidationError("current-writer-holder-missing")
            state["phase"] = "transfer-pending"
            state["source_active"] = False
            state["target_active"] = False
            state["expected_authority"] = _authority_wire(authority)
            state["authority_binding"] = _authority_wire(authority)
            state["revision_digest"] = authority.revision_digest
            state["writer_fence"] = authority.writer_fence
            self._save(state)
            request = LifecycleTransitionRequest(
                kind="writer-transfer",
                expected=authority,
                operation_ref=state["operation_ref"],  # type: ignore[arg-type]
                transition_id=state["transition_id"],  # type: ignore[arg-type]
                revision_digest=authority.revision_digest,
                writer_fence=authority.writer_fence,
                operation_digest=state["operation_digest"],  # type: ignore[arg-type]
                writer_proof=proof,
                target_site=state["target_site"],  # type: ignore[arg-type]
                target_writer_fence_ref=state["target_writer_fence_ref"],  # type: ignore[arg-type]
            )
            try:
                applied = self._transition(request)
            except HeadConflict:
                state["phase"] = "transfer-conflict"
                state["reason_code"] = "current-head-conflict"
                self._save(state)
                return self._state_result(state, status="rejected")
            except (HeadUnknown, HeadTimeout):
                state["phase"] = "transfer-unknown"
                state["reason_code"] = "current-head-unknown"
                self._save(state)
                return self._state_result(state, status="unknown")
            except Exception:
                state["phase"] = "transfer-unknown"
                state["reason_code"] = "current-head-unavailable"
                self._save(state)
                return self._state_result(state, status="unknown")
            try:
                self._replace_authority(applied)
            except Exception:
                state["phase"] = "transfer-unknown"
                state["reason_code"] = "local-authority-handoff-unavailable"
                self._save(state)
                return self._state_result(state, status="unknown", authority=applied)
            state["phase"] = "transferred"
            state["authority_binding"] = _authority_wire(applied)
            state["source_active"] = False
            state["target_active"] = True
            state["reason_code"] = None
            self._save(state)
            return self._state_result(state, status="completed", authority=applied)
        except Exception:
            state["phase"] = "transfer-unknown"
            state["source_active"] = False
            state["target_active"] = False
            state["reason_code"] = "migration-transfer-unavailable"
            try:
                self._save(state)
            except Exception:
                pass
            return self._state_result(state, status="unknown")

    def _recover_unknown_transitions(self) -> None:
        for state in self._all_states():
            if state.get("phase") not in {"terminal-unknown", "transfer-unknown"}:
                continue
            try:
                receipt = self._lookup(self._lifecycle_identity(state))
            except (HeadUnknown, HeadTimeout, HeadConflict, TransitionNotFound, Exception):
                continue
            if not isinstance(receipt, AppliedLifecycleTransition):
                continue
            applied = receipt.applied.as_authority()
            if state.get("phase") == "transfer-unknown":
                try:
                    self._replace_authority(applied)
                except Exception:
                    continue
                state["phase"] = "transferred"
                state["source_active"] = False
                state["target_active"] = True
                state["reason_code"] = None
            state["authority_binding"] = _authority_wire(applied)
            try:
                self._save(state)
            except Exception:
                continue


__all__ = ["LifecycleCoordinator"]

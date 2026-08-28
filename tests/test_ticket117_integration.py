"""Verifier-owned RED gates for Ticket 117 public lifecycle behavior.

Acceptance observes only HealthPlugin health_operation, bounded managed reads,
existing model/outbound gates, and replaceable system-boundary adapters.  No
assertion reads private SQL, helper state, or a lifecycle implementation type.
"""

from __future__ import annotations

import copy
import unittest
from collections.abc import Mapping
from dataclasses import replace
from unittest.mock import patch

from partner_health_steward import HealthCore, HealthPlugin, settings
from partner_health_steward.authority import (
    AuthorityValidationError,
    EffectIntent,
    WriterHolderClaim,
)
from partner_health_steward.contract import ProtocolViolation, Response
from partner_health_steward.core import InMemoryWriterFenceVault
from partner_health_steward.current_head import (
    HeadConflict,
    HeadUnknown,
    InMemoryCurrentHead,
)
from partner_health_steward.delivery import OwnerDeliveryTransportResult
from partner_health_steward.model_contract import StrictModelRequest
from partner_health_steward.storage import EncryptedStateStore
from tests import test_ticket114_authority_integration as ticket114_integration
from tests import test_ticket116_integration as ticket116_integration


_PEER = "plugin"
_DELETE_SEMANTICS = "permanent-delete-all-health-data"
_REGISTRY_FAMILIES = (
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
_CONFIGURED_REPLICA_BINDINGS = (
    "purge:authority-receipt-guard:v1",
    "purge:initialization:v1",
    "purge:source:v1",
    "purge:portrait:v1",
    "purge:evidence:v1",
    "purge:rights:v1",
    "purge:settings-control-approval:v1",
    "purge:task-review:v1",
    "purge:model:v1",
    "purge:diagnosis-safety:v1",
    "purge:support-contact:v1",
    "purge:business-status:v1",
    "purge:outbox-delivery-unknown:v1",
    "purge:lifecycle-migration-staging:v1",
)


class _BoundaryEvents:
    def __init__(self) -> None:
        self.values: list[tuple[str, object]] = []

    def add(self, name: str, value: object) -> None:
        self.values.append((name, copy.deepcopy(value)))


class _DestroyableKeyAdapter:
    """Synthetic external key boundary; it never receives health body."""

    def __init__(self, events: _BoundaryEvents) -> None:
        self.events = events
        self.present = True
        self.calls = 0
        self.unknown = False

    def destroy(self, request: object) -> dict[str, object]:
        self.calls += 1
        self.events.add("key.destroy", request)
        if self.unknown:
            return {"status": "unknown"}
        self.present = False
        return {"status": "confirmed"}

    def absence(self, request: object) -> dict[str, object]:
        self.events.add("key.absence", request)
        return {"status": "absent" if not self.present else "present"}


class _ManagedReplicaAdapter:
    """Configured synthetic replicas; unbound real providers stay unproven."""

    def __init__(
        self,
        events: _BoundaryEvents,
        configured: tuple[str, ...] = _CONFIGURED_REPLICA_BINDINGS,
    ) -> None:
        self.events = events
        self.objects = {binding: f"SYNTHETIC:{binding}" for binding in configured}
        self.unproven = ("real-backup-provider", "retired-vm-provider")
        self.calls = 0

    def enumerate(self, request: object) -> dict[str, object]:
        self.events.add("replica.enumerate", request)
        return {
            "configured": list(self.objects),
            "remains_unproven": list(self.unproven),
        }

    def purge(self, request: object) -> dict[str, object]:
        self.calls += 1
        self.events.add("replica.purge", request)
        self.objects.clear()
        return {"status": "confirmed"}

    def absence(self, request: object) -> dict[str, object]:
        self.events.add("replica.absence", request)
        return {
            "status": "absent" if not self.objects else "present",
            "remains_unproven": list(self.unproven),
        }


class _MigrationArtifactAdapter:
    """Encrypted-package boundary; package bytes are not current truth."""

    def __init__(self, events: _BoundaryEvents) -> None:
        self.events = events
        self.packages: dict[str, object] = {}
        self.role_calls: list[str] = []

    def put(self, package_ref: str, package: object) -> dict[str, object]:
        self.role_calls.append("artifact.put")
        self.events.add("artifact.put", {"package_ref": package_ref})
        self.packages[package_ref] = copy.deepcopy(package)
        return {"status": "confirmed", "package_ref": package_ref}

    def get(self, package_ref: str) -> object | None:
        self.role_calls.append("artifact.get")
        self.events.add("artifact.get", {"package_ref": package_ref})
        package = self.packages.get(package_ref)
        return None if package is None else copy.deepcopy(package)

    def remove(self, package_ref: str) -> dict[str, object]:
        self.role_calls.append("artifact.remove")
        self.events.add("artifact.remove", {"package_ref": package_ref})
        self.packages.pop(package_ref, None)
        return {"status": "confirmed"}


class _LifecycleHeadBoundary:
    """Fault-injecting current-head boundary without knowing lifecycle types."""

    def __init__(self, delegate: object) -> None:
        self.delegate = delegate
        self.mutable_calls = 0
        self.lookup_calls = 0
        self.failure = "none"

    def __getattr__(self, name: str) -> object:
        return getattr(self.delegate, name)

    def conditional_lifecycle_transition(self, request: object) -> object:
        self.mutable_calls += 1
        if self.failure == "conflict":
            raise HeadConflict("synthetic lifecycle conflict")
        method = getattr(self.delegate, "conditional_lifecycle_transition")
        result = method(request)
        if self.failure == "unknown-after-apply":
            raise HeadUnknown("synthetic lifecycle response loss")
        return result

    def lookup_lifecycle_transition(self, identity: object) -> object:
        self.lookup_calls += 1
        if self.failure == "lookup-unavailable":
            raise HeadUnknown("synthetic lifecycle lookup unavailable")
        method = getattr(self.delegate, "lookup_lifecycle_transition")
        return method(identity)


class _DeliveryAdapter:
    def __init__(self, status: str = "accepted") -> None:
        self.status = status
        self.calls = 0
        self.wires: list[dict[str, object]] = []

    def send(self, wire: object) -> dict[str, object]:
        if type(wire) is not dict:
            raise AssertionError("delivery adapter received a non-wire value")
        self.calls += 1
        self.wires.append(dict(wire))
        return OwnerDeliveryTransportResult(
            status=self.status,
            result_ref=f"ticket117-delivery-result:{self.calls}",
            evidence_ref=f"ticket117-delivery-evidence:{self.calls}",
        ).to_wire()


class _RaisingDeliveryAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, wire: object) -> dict[str, object]:
        if type(wire) is not dict:
            raise AssertionError("delivery adapter received a non-wire value")
        self.calls += 1
        raise TimeoutError("synthetic result ownership is unknown")


class _NeverModelAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, wire: object) -> object:
        del wire
        self.calls += 1
        raise AssertionError("frozen health state reached the model adapter")


class Ticket117VerificationTests(unittest.TestCase):
    """Nine public-seam gates, one for each Ticket 117 acceptance ID."""

    maxDiff = None

    def setUp(self) -> None:
        self.v116 = ticket116_integration.Ticket116VerificationTests(
            "test_v116_12_status_uses_typed_safety_and_diagnostic_scope_facts"
        )
        self.v116.setUp()
        self.v116._restart_with_assets(self.v116._synthetic_assets())
        self.events = _BoundaryEvents()
        self.keys = _DestroyableKeyAdapter(self.events)
        self.replicas = _ManagedReplicaAdapter(self.events)
        self.artifacts = _MigrationArtifactAdapter(self.events)
        self.head = _LifecycleHeadBoundary(self.v116.base.head)
        self._command_index = 0
        self._extra_harnesses: list[unittest.TestCase] = []

    def tearDown(self) -> None:
        for harness in reversed(self._extra_harnesses):
            harness.tearDown()
        self.v116.tearDown()

    @property
    def plugin(self) -> HealthPlugin:
        return self.v116.base.plugin

    def _require_lifecycle(self, *, root: bool) -> None:
        reader = getattr(self.plugin, "managed_lifecycle_read", None)
        if callable(reader):
            return
        message = "V117-01 prerequisite: managed lifecycle public seam is not implemented"
        if root:
            raise AssertionError(message)
        self.skipTest(message)

    def _lifecycle_config(
        self,
        *,
        mode: str = "source",
        artifact: object | None = None,
        replica: object | None = None,
        registry_families: tuple[str, ...] = _REGISTRY_FAMILIES,
        mutation: str | None = None,
    ) -> dict[str, object]:
        config: dict[str, object] = {
            "contract": "ticket117-lifecycle-config-v1",
            "mode": mode,
            "semantic_registry": [
                {
                    "family": family,
                    "snapshot_codec": f"codec:{family}:v1",
                    "purge_binding": f"purge:{family}:v1",
                    "source_continuity": "preserve",
                }
                for family in registry_families
            ],
            "release": {
                "product_release": "ticket117-synthetic-release-v1",
                "adr": "ADR-0022",
                "skills": [
                    "health-init",
                    "health-steward",
                    "health-settings",
                    "health-portrait",
                    "health-evidence",
                    "health-owner-inquiry",
                    "health-literature",
                ],
                "plugin_core_bundle": "sha256:" + ("1" * 64),
                "adapter_model_interface_bundle": "sha256:" + ("2" * 64),
                "knowledge_safety_diagnostic_bundle": "sha256:" + ("3" * 64),
                "hermes_artifact": "sha256:" + ("4" * 64),
                "required_patch": "sha256:" + ("5" * 64),
                "disabled_native_entry_assertion": True,
                "schema": "ticket117-semantic-state-v1",
                "observer_identity": "observer:ticket117-synthetic",
                "acl_service": "acl-service:ticket117-synthetic",
                "secret_requirements": ["health-key-ref", "target-fence-ref"],
                "unbound_real_providers": list(self.replicas.unproven),
            },
            "destroyable_key_adapter": self.keys,
            "managed_replica_adapter": self.replicas if replica is None else replica,
            "migration_artifact_adapter": self.artifacts if artifact is None else artifact,
        }
        registry = config["semantic_registry"]
        release = config["release"]
        assert isinstance(registry, list)
        assert isinstance(release, dict)
        if mutation == "registry-missing":
            registry.pop()
        elif mutation == "registry-extra":
            registry.append(
                {
                    "family": "unregistered-managed-family",
                    "snapshot_codec": "codec:unregistered:v1",
                    "purge_binding": "purge:unregistered:v1",
                    "source_continuity": "preserve",
                }
            )
        elif mutation == "release-bundle-schema-drift":
            release["product_release"] = "ticket117-foreign-release"
            release["plugin_core_bundle"] = "sha256:" + ("9" * 64)
            release["adapter_model_interface_bundle"] = "sha256:" + ("8" * 64)
            release["knowledge_safety_diagnostic_bundle"] = "sha256:" + ("7" * 64)
            release["schema"] = "ticket117-foreign-schema"
        elif mutation == "governance-artifact-drift":
            release["adr"] = "ADR-ticket117-foreign"
            release["skills"] = [
                "health-init",
                "health-steward",
                "health-settings",
                "health-portrait",
                "health-evidence",
                "health-owner-inquiry",
                "health-unapproved-skill",
            ]
            release["hermes_artifact"] = "sha256:" + ("6" * 64)
            release["required_patch"] = "sha256:" + ("0" * 64)
            release["disabled_native_entry_assertion"] = False
        elif mutation == "observer-acl-drift":
            release["observer_identity"] = "observer:ticket117-foreign"
            release["acl_service"] = "acl-service:ticket117-foreign"
        elif mutation == "secret-policy-violation":
            release["api_token"] = "SYNTHETIC-PLAINTEXT-SECRET-MUST-REJECT"
        elif mutation is not None:
            raise AssertionError(f"unknown Ticket 117 config mutation: {mutation}")
        return config

    def _restart_lifecycle(
        self,
        *,
        root: bool,
        mode: str = "source",
        close_existing: bool = True,
        registry_families: tuple[str, ...] = _REGISTRY_FAMILIES,
        config_mutation: str | None = None,
    ) -> None:
        assets = self.v116._synthetic_assets()
        if close_existing:
            self.assertTrue(self.v116.base.core.close().complete)
        try:
            core = HealthCore(
                self.v116.base.store,
                self.head,  # type: ignore[arg-type]
                execution_capability_vault=self.v116.harness.execution_vault,
                writer_fence_vault=self.v116.base.writer_vault,
                admission_policy=self.v116.base.policy,
                health_init_verifier=self.v116.base.init_attestor,
                health_init_asset=self.v116.base.init_asset,
                daily_skill_verifier=self.v116.base.daily_attestor,
                daily_skill_bundle=self.v116.base.daily_bundle,
                owner_settings_clock=lambda: self.v116.base.owner_clock_value,
                route_configuration_provider=lambda: self.v116.harness.route_fact,
                status_fact_authority=self.v116.harness.status_authority,
                business_status_clock=lambda: self.v116.base.status_clock_value,
                model_authority_digest=self.v116.llm.model_authority_digest,
                knowledge_releases=(self.v116.knowledge_release,),
                knowledge_valid_at=self.v116.knowledge_now.isoformat(),
                knowledge_clock=lambda: self.v116.knowledge_now,
                safety_diagnostic_assets=assets,
                lifecycle_config=self._lifecycle_config(
                    mode=mode,
                    registry_families=registry_families,
                    mutation=config_mutation,
                ),
            )
        except TypeError as exc:
            message = "V117-01 prerequisite: lifecycle construction seam is not implemented"
            if root:
                raise AssertionError(message) from exc
            self.skipTest(message)
        plugin = HealthPlugin(
            core,
            admission_policy=self.v116.base.policy,
            health_init_runtime=self.v116.base.init_runtime,
            coarse_router=self.v116.base.router,
            daily_skill_runtime=self.v116.base.sleep_runtime,
        )
        self.v116.base.core = core
        self.v116.base.plugin = plugin
        self.v116.base.correction_plugin = plugin

    def _context(
        self,
        *,
        kind: str,
        causal_id: str | None = None,
        generation: int | None = None,
        source: str | None = None,
        scope: str | None = None,
    ) -> dict[str, object]:
        self._command_index += 1
        default_source = (
            "owner_rights_runtime" if kind == "delete-all" else "migration_runtime"
        )
        default_scope = {
            "delete-all": "lifecycle:delete",
            "prepare-migration": "lifecycle:prepare-migration",
            "accept-migration": "lifecycle:accept-migration",
        }[kind]
        return {
            "source": default_source if source is None else source,
            "causal_id": causal_id
            or f"ticket117-command:{self._testMethodName}:{self._command_index}",
            "generation": (
                self.head.read().head.generation
                if generation is None
                else generation
            ),
            "scope": [default_scope if scope is None else scope],
        }

    def _execute(
        self,
        payload: dict[str, object],
        *,
        context: dict[str, object] | None = None,
        plugin: HealthPlugin | None = None,
    ) -> dict[str, object]:
        kind = payload.get("kind")
        if type(kind) is not str:
            raise AssertionError("Ticket 117 test payload has no kind")
        try:
            result = (self.plugin if plugin is None else plugin).health_operation(
                "lifecycle.execute",
                payload,
                context=self._context(kind=kind) if context is None else context,
                peer_id=_PEER,
            )
        except (ProtocolViolation, AuthorityValidationError) as exc:
            raise AssertionError(
                f"Ticket 117 public lifecycle action is unavailable: {exc}"
            ) from exc
        if type(result) is not dict:
            raise AssertionError("Ticket 117 lifecycle action did not return a wire mapping")
        return result

    def _read(
        self,
        operation_ref: str | None = None,
        *,
        plugin: HealthPlugin | None = None,
    ) -> dict[str, object]:
        reader = getattr(self.plugin if plugin is None else plugin, "managed_lifecycle_read", None)
        if not callable(reader):
            raise AssertionError("Ticket 117 managed lifecycle read is unavailable")
        try:
            result = reader(operation_ref, peer_id=_PEER)
        except (ProtocolViolation, AuthorityValidationError) as exc:
            raise AssertionError(f"Ticket 117 lifecycle read is unavailable: {exc}") from exc
        if type(result) is not dict:
            raise AssertionError("Ticket 117 lifecycle read did not return a wire mapping")
        forbidden = ("health_body", "snapshot_body", "key_material", "credential", "sql")
        rendered = repr(result).lower()
        self.assertFalse(any(value in rendered for value in forbidden), result)
        return result

    def _offline_target(
        self,
        *,
        config_mutation: str | None = None,
        current_head: object | None = None,
        current_head_capability: str | None = None,
        route_drift: bool = False,
    ) -> HealthPlugin:
        """Build a second Core whose only admitted command is accept-migration."""

        target = ticket116_integration.Ticket116VerificationTests(
            "test_v116_12_status_uses_typed_safety_and_diagnostic_scope_facts"
        )
        target.setUp()
        self._extra_harnesses.append(target)
        target._restart_with_assets(target._synthetic_assets())
        if route_drift:
            target.harness.route_fact = replace(
                target.harness.route_fact,
                configuration_generation=(
                    target.harness.route_fact.configuration_generation + 1
                ),
                generation=target.harness.route_fact.generation + 1,
            )
        self.assertTrue(target.base.core.close().complete)
        target_head = self.head if current_head is None else current_head
        if current_head_capability is not None:
            target_snapshot = target_head.read().head  # type: ignore[union-attr]
            target.base.writer_vault.bind(
                target_snapshot.as_authority(),
                current_head_capability,
            )
        core = HealthCore(
            target.base.store,
            target_head,  # type: ignore[arg-type]
            execution_capability_vault=target.harness.execution_vault,
            writer_fence_vault=target.base.writer_vault,
            admission_policy=target.base.policy,
            health_init_verifier=target.base.init_attestor,
            health_init_asset=target.base.init_asset,
            daily_skill_verifier=target.base.daily_attestor,
            daily_skill_bundle=target.base.daily_bundle,
            owner_settings_clock=lambda: target.base.owner_clock_value,
            route_configuration_provider=lambda: target.harness.route_fact,
            status_fact_authority=target.harness.status_authority,
            business_status_clock=lambda: target.base.status_clock_value,
            model_authority_digest=target.llm.model_authority_digest,
            knowledge_releases=(target.knowledge_release,),
            knowledge_valid_at=target.knowledge_now.isoformat(),
            knowledge_clock=lambda: target.knowledge_now,
            safety_diagnostic_assets=target._synthetic_assets(),
            lifecycle_config=self._lifecycle_config(
                mode="offline-staging",
                mutation=config_mutation,
            ),
        )
        plugin = HealthPlugin(
            core,
            admission_policy=target.base.policy,
            health_init_runtime=target.base.init_runtime,
            coarse_router=target.base.router,
            daily_skill_runtime=target.base.sleep_runtime,
        )
        target.base.core = core
        target.base.plugin = plugin
        target.base.correction_plugin = plugin
        self.assertFalse(plugin.health_writes_allowed())
        self.assertFalse(plugin.model_effects_allowed())
        self.assertFalse(plugin.outbound_effects_allowed())
        return plugin

    def _fresh_blank_installation(self) -> HealthPlugin:
        """Use the existing public initialization fixture with a new head/key."""

        new_installation = "partner-installation-after-ticket117-delete"
        original_provider = ticket114_integration.StaticKeyProvider

        def fresh_key_provider(_: bytes, key_id: str) -> object:
            del key_id
            return original_provider(
                b"n" * 32,
                key_id="ticket117-new-blank-health-key",
            )

        with (
            patch.object(ticket114_integration, "_INSTALLATION_ID", new_installation),
            patch.object(ticket116_integration, "_INSTALLATION_ID", new_installation),
            patch.object(
                ticket114_integration,
                "StaticKeyProvider",
                side_effect=fresh_key_provider,
            ),
        ):
            blank = ticket116_integration.Ticket116VerificationTests(
                "test_v116_12_status_uses_typed_safety_and_diagnostic_scope_facts"
            )
            blank.setUp()
            blank._restart_with_assets(blank._synthetic_assets())
        self._extra_harnesses.append(blank)
        projection = blank.plugin.initialization_status(peer_id=_PEER)
        self.assertEqual(projection.phase, "enabled")
        self.assertEqual(projection.key_id, "ticket117-new-blank-health-key")
        self.assertIsNotNone(projection.prepared_authority)
        assert projection.prepared_authority is not None
        self.assertEqual(
            projection.prepared_authority.installation_id,
            new_installation,
        )
        return blank.plugin

    @staticmethod
    def _public_semantic_views(plugin: HealthPlugin) -> dict[str, object]:
        """Tickets 110-116 public semantic projections, never private storage."""

        return {
            "ticket110_probe": plugin.probe(),
            "ticket110_gates": {
                "health": plugin.health_writes_allowed(),
                "model": plugin.model_effects_allowed(),
                "outbound": plugin.outbound_effects_allowed(),
            },
            "ticket111_initialization": plugin.initialization_status(peer_id=_PEER),
            "ticket112_113_daily_state": plugin.daily_state(peer_id=_PEER),
            "ticket114_rights": plugin.managed_rights_read_current(peer_id=_PEER),
            "ticket114_settings": plugin.managed_owner_settings_read(peer_id=_PEER),
            "ticket114_status": plugin.business_status(peer_id=_PEER),
            "ticket115_tasks_review_delivery": plugin.managed_ticket115_read(
                peer_id=_PEER
            ),
            "ticket116_safety_diagnosis": plugin.managed_safety_diagnosis_read(
                peer_id=_PEER
            ),
        }

    def _registry_exact_sets(self) -> tuple[set[str], set[str]]:
        registry = self._lifecycle_config()["semantic_registry"]
        self.assertIsInstance(registry, list)
        assert isinstance(registry, list)
        families: set[str] = set()
        purge_bindings: set[str] = set()
        for entry in registry:
            self.assertIsInstance(entry, Mapping)
            assert isinstance(entry, Mapping)
            families.add(entry["family"])  # type: ignore[arg-type]
            purge_bindings.add(entry["purge_binding"])  # type: ignore[arg-type]
        return families, purge_bindings

    def _form_owner_delivery_grant(self) -> tuple[str, object, object]:
        """Create one real runnable task/outbox intent and unstarted grant."""

        task_id, effect_request_id = self.v116.harness._admit_review_task()
        intent_id = self.v116.harness._commit_review_outbox(
            task_id,
            effect_request_id,
        )
        attempted = "2026-08-28T00:58:00+00:00"
        self.plugin.controlled_effect(
            "owner-delivery.prepare",
            {"intent_id": intent_id, "attempted_at_utc": attempted},
            peer_id=_PEER,
        )
        issued = self.plugin.controlled_effect(
            "owner-delivery.issue",
            {"intent_id": intent_id},
            peer_id=_PEER,
        )
        response = Response.from_wire(issued["response"])
        self.assertEqual(response.status, "accepted", response)
        assert response.meta is not None
        intent = response.meta.intent
        grant = self.plugin.claim_effect_execution(intent)
        self.assertIsNotNone(grant)
        return task_id, intent, grant

    def _form_strict_model_grant(
        self,
        *,
        source_suffix: str,
    ) -> tuple[StrictModelRequest, str, object]:
        """Create one real strict request/intent and unstarted execution grant."""

        payload = self.v116._diagnosis_prepare_payload(source_suffix=source_suffix)
        prepared = self.v116._health(
            "diagnosis.prepare",
            payload,
            suffix=source_suffix,
        )
        self.assertEqual(prepared.get("status"), "model-ready", prepared)
        intent = EffectIntent.from_wire_metadata(prepared.get("model_intent"))
        request = StrictModelRequest.from_wire(prepared.get("request"))
        grant = self.plugin.claim_effect_execution(intent)
        self.assertIsNotNone(grant)
        source_causal_id = payload["source_causal_id"]
        self.assertIsInstance(source_causal_id, str)
        return request, source_causal_id, grant  # type: ignore[return-value]

    def _seed_unknown_owner_delivery(self) -> tuple[str, object, object]:
        task_id, intent, grant = self._form_owner_delivery_grant()
        adapter = _RaisingDeliveryAdapter()
        result = self.plugin.controlled_effect(
            "owner-delivery.execute",
            {
                "intent_id": intent.effect_id,
                "attempted_at_utc": "2026-08-28T00:58:00+00:00",
                "observed_at_utc": "2026-08-28T00:58:01+00:00",
            },
            grant=grant,
            transport=adapter,
            peer_id=_PEER,
        )
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(result["transport_result"]["status"], "unknown")
        return task_id, intent, grant

    @staticmethod
    def _delete_payload(operation_ref: str) -> dict[str, object]:
        return {
            "kind": "delete-all",
            "operation_ref": operation_ref,
            "owner_command_ref": f"owner-command:{operation_ref}",
            "semantics": _DELETE_SEMANTICS,
        }

    def _complete_notice(
        self,
        operation_ref: str,
        payload: dict[str, object],
        context: dict[str, object],
        *,
        before_resume: object | None = None,
    ) -> None:
        result = self._execute(payload, context=context)
        self.assertEqual(result.get("status"), "notice-pending", result)
        view = self.plugin.managed_ticket115_read(peer_id=_PEER)
        matching = [
            item
            for item in view["owner_deliveries"]
            if item["intent"].get("effect_request_id") == operation_ref
            or item["intent"].get("payload_ref") == f"lifecycle-notice:{operation_ref}"
        ]
        self.assertEqual(len(matching), 1, view)
        intent_id = matching[0]["intent"]["intent_id"]
        attempted = "2026-08-28T01:00:00+00:00"
        self.plugin.controlled_effect(
            "owner-delivery.prepare",
            {"intent_id": intent_id, "attempted_at_utc": attempted},
            peer_id=_PEER,
        )
        issued = self.plugin.controlled_effect(
            "owner-delivery.issue", {"intent_id": intent_id}, peer_id=_PEER
        )
        response = Response.from_wire(issued["response"])
        self.assertEqual(response.status, "accepted", response)
        assert response.meta is not None
        grant = self.plugin.claim_effect_execution(response.meta.intent)
        self.assertIsNotNone(grant)
        adapter = _DeliveryAdapter()
        self.plugin.controlled_effect(
            "owner-delivery.execute",
            {
                "intent_id": intent_id,
                "attempted_at_utc": attempted,
                "observed_at_utc": "2026-08-28T01:00:01+00:00",
            },
            grant=grant,
            transport=adapter,
            peer_id=_PEER,
        )
        self.assertEqual(adapter.calls, 1)
        if before_resume is not None:
            if not callable(before_resume):
                raise AssertionError("invalid Ticket 117 before-resume callback")
            before_resume()
        resumed = self._execute(payload, context=context)
        self.assertIn(
            resumed.get("status"),
            {"completed", "replayed", "rejected", "unknown"},
            resumed,
        )

    def _start_delete(
        self,
        operation_ref: str,
        *,
        before_resume: object | None = None,
    ) -> dict[str, object]:
        payload = self._delete_payload(operation_ref)
        context = self._context(
            kind="delete-all",
            causal_id=f"ticket117-delete-causal:{operation_ref}",
        )
        self._complete_notice(
            operation_ref,
            payload,
            context,
            before_resume=before_resume,
        )
        return self._read(operation_ref)

    def _prepare_migration(self, operation_ref: str) -> dict[str, object]:
        return self._execute(
            {
                "kind": "prepare-migration",
                "operation_ref": operation_ref,
                "target_site": "synthetic-target-site",
                "target_writer_fence_ref": "target-fence-ref:ticket117",
                "artifact_sink_ref": "artifact-sink:ticket117",
            }
        )

    @staticmethod
    def _lifecycle_state_without_authority(view: Mapping[str, object]) -> dict[str, object]:
        return {
            key: copy.deepcopy(value)
            for key, value in view.items()
            if key != "authority_binding"
        }

    def _commit_owner_request(self, request: object) -> None:
        self.assertEqual(self.v116.base._prepare(request).status, "accepted")
        self.assertEqual(self.v116.base._commit(request).status, "accepted")
        self.assertEqual(self.v116.base._finalize(request).status, "accepted")

    def test_v117_01_freeze_closes_every_health_effect_before_terminal(self) -> None:
        """A1: freeze cannot leave task/model/outbound work admitted."""

        self._require_lifecycle(root=True)
        self._restart_lifecycle(root=True)
        admitted: dict[str, object] = {}

        def form_real_inflight_work() -> None:
            task_id, intent, grant = self._form_owner_delivery_grant()
            model_request, model_source, model_grant = self._form_strict_model_grant(
                source_suffix="ticket117-model-before-freeze"
            )
            admitted.update(
                task_id=task_id,
                intent=intent,
                grant=grant,
                model_request=model_request,
                model_source=model_source,
                model_grant=model_grant,
            )

        self.head.failure = "conflict"
        lifecycle = self._start_delete(
            "delete-freeze-all-effects",
            before_resume=form_real_inflight_work,
        )
        self.assertIn(lifecycle.get("phase"), {"frozen", "terminal-pending"}, lifecycle)
        self.assertFalse(self.plugin.health_writes_allowed())
        self.assertFalse(self.plugin.model_effects_allowed())
        self.assertFalse(self.plugin.outbound_effects_allowed())
        task_id = admitted["task_id"]
        intent = admitted["intent"]
        grant = admitted["grant"]
        blocked_transport = _DeliveryAdapter()
        try:
            self.plugin.controlled_effect(
                "owner-delivery.execute",
                {
                    "intent_id": intent.effect_id,  # type: ignore[attr-defined]
                    "attempted_at_utc": "2026-08-28T00:58:00+00:00",
                    "observed_at_utc": "2026-08-28T01:01:00+00:00",
                },
                grant=grant,  # type: ignore[arg-type]
                transport=blocked_transport,
                peer_id=_PEER,
            )
        except (ProtocolViolation, AuthorityValidationError):
            pass
        self.assertEqual(blocked_transport.calls, 0)
        self.assertIsNone(self.plugin.claim_effect_execution(intent))  # type: ignore[arg-type]

        never_model = _NeverModelAdapter()
        model_outcome = self.plugin.execute_strict_health_model(
            self.v116.llm,
            admitted["model_request"],  # type: ignore[arg-type]
            admitted["model_source"],  # type: ignore[arg-type]
            admitted["model_grant"],  # type: ignore[arg-type]
            never_model,
        )
        self.assertEqual(
            (model_outcome.disposition, model_outcome.model_effect),
            ("failed-closed", "not-started"),
        )
        self.assertEqual(never_model.calls, 0)

        task_context = {
            "source": "health_tasks",
            "causal_id": "ticket117-task-after-freeze",
            "generation": self.head.read().head.generation,
            "scope": ["task:advance"],
        }
        try:
            task_result = self.plugin.health_operation(
                "task.advance",
                {
                    "task_id": task_id,
                    "phase": "in-progress",
                    "advanced_at_utc": "2026-08-28T01:02:00+00:00",
                },
                context=task_context,
                peer_id=_PEER,
            )
        except (ProtocolViolation, AuthorityValidationError):
            task_result = {"status": "rejected"}
        self.assertEqual(task_result.get("status"), "rejected", task_result)

        try:
            model_prepare = self.plugin.health_operation(
                "diagnosis.prepare",
                self.v116._diagnosis_prepare_payload(
                    source_suffix="ticket117-after-freeze"
                ),
                context={
                    "source": "diagnostic_runtime",
                    "causal_id": "ticket117-model-after-freeze",
                    "generation": self.head.read().head.generation,
                    "scope": ["diagnosis:prepare"],
                },
                peer_id=_PEER,
            )
        except (ProtocolViolation, AuthorityValidationError):
            model_prepare = {"status": "rejected"}
        self.assertEqual(model_prepare.get("status"), "rejected", model_prepare)
        self.assertNotIn("model_intent", model_prepare)
        self.assertEqual(never_model.calls, 0)

        managed_reads = (
            self.plugin.managed_owner_settings_read,
            self.plugin.managed_ticket115_read,
            self.plugin.managed_safety_diagnosis_read,
            self.plugin.managed_rights_read_current,
        )
        for managed_read in managed_reads:
            with self.subTest(blocked_managed_read=managed_read.__name__):
                with self.assertRaises(AuthorityValidationError):
                    managed_read(peer_id=_PEER)
        self.assertEqual(self.keys.calls, 0)
        self.assertEqual(self.replicas.calls, 0)
        self._restart_lifecycle(root=True)
        self.assertFalse(self.plugin.health_writes_allowed())
        self.assertFalse(self.plugin.model_effects_allowed())
        self.assertFalse(self.plugin.outbound_effects_allowed())

    def test_v117_02_terminal_cleanup_is_key_first_body_free_and_complete_only_when_proven(self) -> None:
        """A2: terminal cleanup cannot reopen health state or skip a binding."""

        self._require_lifecycle(root=False)
        self._restart_lifecycle(root=False)
        _, registry_purge_bindings = self._registry_exact_sets()
        configured = self.replicas.enumerate(
            {"installation_id": self.head.read().head.installation_id}
        )["configured"]
        self.assertEqual(set(configured), registry_purge_bindings)

        def assert_no_cleanup_before_terminal() -> None:
            self.assertEqual(self.keys.calls, 0)
            self.assertEqual(self.replicas.calls, 0)

        lifecycle = self._start_delete(
            "delete-key-first-purge",
            before_resume=assert_no_cleanup_before_terminal,
        )
        self.assertEqual(lifecycle.get("phase"), "completed", lifecycle)
        names = [name for name, _ in self.events.values]
        self.assertLess(names.index("key.destroy"), names.index("key.absence"))
        self.assertLess(names.index("key.absence"), names.index("replica.purge"))
        self.assertLess(names.index("replica.purge"), names.index("replica.absence"))
        self.assertFalse(self.keys.present)
        self.assertEqual(self.replicas.objects, {})
        self.assertEqual(
            lifecycle.get("remains_unproven"),
            list(self.replicas.unproven),
        )
        # Storage-system-boundary absence oracle: enumerate generic local
        # SQLite tables and count rows only.  It never reads columns, payloads,
        # or hard-coded product table names.
        connection = getattr(self.v116.base.store, "_connection")
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        self.assertTrue(table_rows)
        for (table_name,) in table_rows:
            self.assertIsInstance(table_name, str)
            quoted_name = '"' + table_name.replace('"', '""') + '"'
            count_row = connection.execute(
                f"SELECT COUNT(*) FROM {quoted_name}"
            ).fetchone()
            self.assertIsNotNone(count_row)
            self.assertEqual(count_row[0], 0, table_name)
        self.assertFalse(self.plugin.health_writes_allowed())
        self.assertFalse(self.plugin.model_effects_allowed())
        self.assertFalse(self.plugin.outbound_effects_allowed())
        # Prove terminal cleanup/readback does not reopen or decrypt the old
        # health database: the ordinary Core and SQLite connection are closed
        # before the body-free lifecycle runner is reconstructed.
        self.assertTrue(self.v116.base.core.close().complete)
        self.v116.base.store.close()
        self._restart_lifecycle(root=False, close_existing=False)
        restarted = self._read("delete-key-first-purge")
        self.assertEqual(restarted.get("phase"), "completed", restarted)
        self.assertEqual(self.keys.calls, 1)
        self.assertEqual(self.replicas.calls, 1)

        # A separately enumerated configured replica cannot be hidden by the
        # registry that drives cleanup.  Construction may continue only in a
        # publicly fail-closed state.
        mismatch = type(self)(self._testMethodName)
        mismatch.setUp()
        self._extra_harnesses.append(mismatch)
        mismatch.replicas.objects[
            "purge:unregistered-configured-replica:v1"
        ] = "SYNTHETIC:UNREGISTERED"
        mismatch._restart_lifecycle(root=False)
        mismatch_probe = mismatch.plugin.probe()
        mismatch_state = getattr(mismatch_probe.state, "value", mismatch_probe.state)
        self.assertNotEqual(mismatch_state, "healthy")
        self.assertFalse(mismatch.plugin.health_writes_allowed())
        self.assertFalse(mismatch.plugin.model_effects_allowed())
        self.assertFalse(mismatch.plugin.outbound_effects_allowed())
        self.assertEqual(mismatch.keys.calls, 0)
        self.assertEqual(mismatch.replicas.calls, 0)

        # A confirmed terminal is not enough to call cleanup complete when the
        # first irreversible boundary cannot confirm key destruction.  This is
        # a separate instance so the completed path above remains observable.
        cleanup_unknown = type(self)(self._testMethodName)
        cleanup_unknown.setUp()
        self._extra_harnesses.append(cleanup_unknown)
        cleanup_unknown._require_lifecycle(root=False)
        cleanup_unknown._restart_lifecycle(root=False)
        cleanup_unknown.keys.unknown = True
        unknown_cleanup = cleanup_unknown._start_delete(
            "delete-key-destruction-unknown"
        )
        self.assertNotEqual(unknown_cleanup.get("phase"), "completed")
        self.assertIn(
            unknown_cleanup.get("phase"),
            {"unknown", "terminal-confirmed-cleanup-pending", "cleanup-pending"},
            unknown_cleanup,
        )
        self.assertEqual(cleanup_unknown.keys.calls, 1)
        self.assertTrue(cleanup_unknown.keys.present)
        self.assertEqual(cleanup_unknown.replicas.calls, 0)
        self.assertFalse(cleanup_unknown.plugin.health_writes_allowed())
        self.assertFalse(cleanup_unknown.plugin.model_effects_allowed())
        self.assertFalse(cleanup_unknown.plugin.outbound_effects_allowed())

    def test_v117_03_terminal_unknown_only_exactly_looks_up_original_transition(self) -> None:
        """A3: response loss cannot become a second terminal CAS or early purge."""

        self._require_lifecycle(root=False)
        self._restart_lifecycle(root=False)
        self.head.failure = "unknown-after-apply"
        first = self._start_delete("delete-terminal-response-loss")
        self.assertIn(first.get("phase"), {"terminal-unknown", "unknown"}, first)
        self.assertEqual(self.head.mutable_calls, 1)
        self.assertEqual(self.keys.calls, 0)
        self.assertEqual(self.replicas.calls, 0)
        self.head.failure = "lookup-unavailable"
        self._restart_lifecycle(root=False)
        replay = self._read("delete-terminal-response-loss")
        self.assertIn(replay.get("phase"), {"terminal-unknown", "unknown"}, replay)
        self.assertEqual(self.head.mutable_calls, 1)
        self.assertGreaterEqual(self.head.lookup_calls, 1)
        self.assertEqual(self.keys.calls, 0)
        self.assertEqual(self.replicas.calls, 0)

    def test_v117_04_terminal_snapshot_and_old_key_cannot_resurrect_state(self) -> None:
        """A4: an old readable snapshot is never current after terminal delete."""

        self._require_lifecycle(root=False)
        self.v116._activate_synthetic_scope_through_ticket119()
        old_task_id, old_intent, _ = self._seed_unknown_owner_delivery()
        before = self._public_semantic_views(self.plugin)
        old_initialization = self.plugin.initialization_status(peer_id=_PEER)
        old_authority = self.head.read().head.as_authority()
        # Private connection access is fault-fixture setup only: it copies the
        # real pre-terminal encrypted SQLite database.  No acceptance oracle
        # below inspects private rows or connection state.
        old_connection = getattr(self.v116.base.store, "_connection")
        old_database_snapshot = old_connection.serialize()
        self.assertIsNotNone(old_initialization.prepared_authority)
        self.assertIsNotNone(old_initialization.key_id)
        self.assertTrue(old_database_snapshot)
        old_rendered = repr(before)
        self.assertIn(old_task_id, old_rendered)
        self.assertIn(old_intent.effect_id, old_rendered)  # type: ignore[attr-defined]
        self.assertIn("unknown", old_rendered)
        self.assertTrue(
            before["ticket116_safety_diagnosis"]["diagnoses"],  # type: ignore[index]
            before,
        )
        self._restart_lifecycle(root=False)
        self._start_delete("delete-nonresurrection")
        self._restart_lifecycle(root=False)
        lifecycle = self._read("delete-nonresurrection")
        self.assertEqual(lifecycle.get("mode"), "terminal", lifecycle)
        authority = lifecycle.get("authority_binding")
        self.assertIsInstance(authority, Mapping)
        assert isinstance(authority, Mapping)
        self.assertTrue(authority.get("terminal"), authority)
        self.assertEqual(authority.get("installation_id"), old_authority.installation_id)
        self.assertFalse(self.plugin.health_writes_allowed())
        self.assertFalse(self.plugin.model_effects_allowed())
        self.assertFalse(self.plugin.outbound_effects_allowed())

        restored_store = EncryptedStateStore(
            "file:ticket117-v04-restored-old-db?mode=memory&cache=shared",
            ticket114_integration.StaticKeyProvider(
                b"u" * 32,
                key_id="ticket114-owner-state-key",
            ),
        )
        restored_connection = getattr(restored_store, "_connection")
        restored_connection.deserialize(old_database_snapshot)
        collision_core: HealthCore | None = None
        collision_rejection: Exception | None = None
        try:
            collision_core = HealthCore(
                restored_store,
                self.head,  # the same real terminal current-head boundary
                execution_capability_vault=self.v116.harness.execution_vault,
                writer_fence_vault=self.v116.base.writer_vault,
                admission_policy=self.v116.base.policy,
                health_init_verifier=self.v116.base.init_attestor,
                health_init_asset=self.v116.base.init_asset,
                daily_skill_verifier=self.v116.base.daily_attestor,
                daily_skill_bundle=self.v116.base.daily_bundle,
                owner_settings_clock=lambda: self.v116.base.owner_clock_value,
                route_configuration_provider=lambda: self.v116.harness.route_fact,
                status_fact_authority=self.v116.harness.status_authority,
                business_status_clock=lambda: self.v116.base.status_clock_value,
                model_authority_digest=self.v116.llm.model_authority_digest,
                knowledge_releases=(self.v116.knowledge_release,),
                knowledge_valid_at=self.v116.knowledge_now.isoformat(),
                knowledge_clock=lambda: self.v116.knowledge_now,
                safety_diagnostic_assets=self.v116._synthetic_assets(),
                lifecycle_config=self._lifecycle_config(),
            )
        except (AuthorityValidationError, ProtocolViolation) as exc:
            collision_rejection = exc

        if collision_core is None:
            self.assertIsNotNone(collision_rejection)
            restored_store.close()
        else:
            collision_plugin = HealthPlugin(
                collision_core,
                admission_policy=self.v116.base.policy,
                health_init_runtime=self.v116.base.init_runtime,
                coarse_router=self.v116.base.router,
                daily_skill_runtime=self.v116.base.sleep_runtime,
            )
            try:
                collision_probe = collision_plugin.probe()
                collision_state = getattr(
                    collision_probe.state,
                    "value",
                    collision_probe.state,
                )
                self.assertNotEqual(collision_state, "healthy")
                self.assertFalse(collision_plugin.health_writes_allowed())
                self.assertFalse(collision_plugin.model_effects_allowed())
                self.assertFalse(collision_plugin.outbound_effects_allowed())
            finally:
                collision_core.close()
                restored_store.close()

        blank = self._fresh_blank_installation()
        blank_views = self._public_semantic_views(blank)
        blank_initialization = blank.initialization_status(peer_id=_PEER)
        assert old_initialization.prepared_authority is not None
        assert blank_initialization.prepared_authority is not None
        self.assertNotEqual(
            blank_initialization.prepared_authority.installation_id,
            old_initialization.prepared_authority.installation_id,
        )
        self.assertNotEqual(blank_initialization.key_id, old_initialization.key_id)
        self.assertEqual(
            blank_views["ticket115_tasks_review_delivery"]["tasks"],  # type: ignore[index]
            [],
        )
        self.assertEqual(
            blank_views["ticket115_tasks_review_delivery"]["delivery_unknown_refs"],  # type: ignore[index]
            [],
        )
        self.assertEqual(
            blank_views["ticket116_safety_diagnosis"]["diagnoses"],  # type: ignore[index]
            [],
        )
        blank_rendered = repr(blank_views)
        self.assertNotIn(old_task_id, blank_rendered)
        self.assertNotIn(old_intent.effect_id, blank_rendered)  # type: ignore[attr-defined]
        self.assertNotIn("approval:ticket115-review-summary", blank_rendered)

    def test_v117_05_manifest_exact_set_hash_and_secret_policy_fail_closed(self) -> None:
        """A5: a DB copy or plausible digest is not a complete manifest."""

        self._require_lifecycle(root=False)
        self._restart_lifecycle(root=False)
        _, registry_purge_bindings = self._registry_exact_sets()
        configured = self.replicas.enumerate(
            {"installation_id": self.head.read().head.installation_id}
        )["configured"]
        self.assertEqual(set(configured), registry_purge_bindings)
        ready = self._prepare_migration("migration-manifest-exact-set")
        self.assertEqual(ready.get("status"), "manifest-ready", ready)
        package_ref = ready.get("package_ref")
        manifest_digest = ready.get("manifest_digest")
        self.assertIsInstance(package_ref, str)
        self.assertIsInstance(manifest_digest, str)
        package = self.artifacts.get(package_ref)  # type: ignore[arg-type]
        self.assertIsNotNone(package)

        # Wrong hash is submitted only through the public accept payload; the
        # verifier never parses or rewrites the opaque package.
        target = self._offline_target()
        wrong_hash = self._execute(
            {
                "kind": "accept-migration",
                "operation_ref": "migration-manifest-exact-set",
                "package_ref": package_ref,
                "manifest_digest": "sha256:" + ("0" * 64),
            },
            plugin=target,
        )
        self.assertEqual(wrong_hash.get("status"), "rejected", wrong_hash)
        self.assertIs(
            self._read("migration-manifest-exact-set", plugin=target).get(
                "target_active"
            ),
            False,
        )

        # Keep the advertised digest correct while replacing the opaque
        # package at its Adapter boundary.  The verifier never parses or
        # manufactures a product manifest.
        original_package = copy.deepcopy(package)
        self.artifacts.packages[package_ref] = {
            "opaque-corruption": "ticket117-package-content-replaced"
        }
        tampered_target = self._offline_target()
        tampered = self._execute(
            {
                "kind": "accept-migration",
                "operation_ref": "migration-manifest-exact-set",
                "package_ref": package_ref,
                "manifest_digest": manifest_digest,
            },
            plugin=tampered_target,
        )
        self.assertEqual(tampered.get("status"), "rejected", tampered)
        self.assertIs(
            self._read(
                "migration-manifest-exact-set", plugin=tampered_target
            ).get("target_active"),
            False,
        )
        self.artifacts.packages[package_ref] = original_package

        def assert_source_config_fails_closed(
            label: str,
            *,
            config_mutation: str | None = None,
            add_unregistered_store_object: bool = False,
        ) -> None:
            scenario = type(self)(self._testMethodName)
            scenario.setUp()
            self._extra_harnesses.append(scenario)
            if add_unregistered_store_object:
                connection = getattr(scenario.v116.base.store, "_connection")
                connection.execute(
                    "CREATE TABLE health_ticket117_unregistered_managed_v1 "
                    "(object_id TEXT PRIMARY KEY, payload BLOB NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO health_ticket117_unregistered_managed_v1 "
                    "(object_id, payload) VALUES (?, ?)",
                    ("ticket117-unregistered-object", b"encrypted-fixture"),
                )
                connection.commit()
            scenario._restart_lifecycle(
                root=False,
                config_mutation=config_mutation,
            )
            probe = scenario.plugin.probe()
            state = getattr(probe.state, "value", probe.state)
            self.assertNotEqual(state, "healthy", label)
            self.assertFalse(scenario.plugin.health_writes_allowed(), label)
            self.assertFalse(scenario.plugin.model_effects_allowed(), label)
            self.assertFalse(scenario.plugin.outbound_effects_allowed(), label)
            try:
                result = scenario.plugin.health_operation(
                    "lifecycle.execute",
                    {
                        "kind": "prepare-migration",
                        "operation_ref": f"migration-invalid-source:{label}",
                        "target_site": "synthetic-target-site",
                        "target_writer_fence_ref": "target-fence-ref:ticket117",
                        "artifact_sink_ref": "artifact-sink:ticket117",
                    },
                    context=scenario._context(kind="prepare-migration"),
                    peer_id=_PEER,
                )
            except (ProtocolViolation, AuthorityValidationError):
                result = {"status": "rejected"}
            self.assertEqual(result.get("status"), "rejected", result)
            self.assertEqual(scenario.artifacts.role_calls, [])

        source_faults = (
            ("store-unregistered", None, True),
            ("registry-missing", "registry-missing", False),
            ("registry-extra", "registry-extra", False),
            ("secret-policy", "secret-policy-violation", False),
        )
        for label, mutation, add_store_object in source_faults:
            with self.subTest(source_configuration_fault=label):
                assert_source_config_fails_closed(
                    label,
                    config_mutation=mutation,
                    add_unregistered_store_object=add_store_object,
                )

        # Remaining compatibility failures are target-owned configuration or
        # real current-head facts, not opaque package edits.
        foreign_head = InMemoryCurrentHead(
            "ticket117-foreign-installation",
            site="ticket117-foreign-site",
            writer_capability="ticket117-foreign-writer-capability",
        )
        target_faults = (
            ("release-bundle-schema", "release-bundle-schema-drift", None, None),
            ("governance-artifact", "governance-artifact-drift", None, None),
            (
                "current-head-observer-acl",
                "observer-acl-drift",
                foreign_head,
                "ticket117-foreign-writer-capability",
            ),
            ("route-consent-currentness", None, None, None),
        )
        for label, mutation, configured_head, configured_capability in target_faults:
            with self.subTest(target_configuration_fault=label):
                mismatched_target = self._offline_target(
                    config_mutation=mutation,
                    current_head=configured_head,
                    current_head_capability=configured_capability,
                    route_drift=label == "route-consent-currentness",
                )
                if label == "route-consent-currentness":
                    self.assertEqual(
                        mismatched_target.owner_settings_state(
                            peer_id=_PEER
                        ).consent_path_status,
                        "paused",
                    )
                context = None
                if configured_head is not None:
                    foreign_snapshot = foreign_head.read().head
                    context = {
                        "source": "migration_runtime",
                        "causal_id": f"ticket117-target-fault:{label}",
                        "generation": foreign_snapshot.generation,
                        "scope": ["lifecycle:accept-migration"],
                    }
                denied = self._execute(
                    {
                        "kind": "accept-migration",
                        "operation_ref": "migration-manifest-exact-set",
                        "package_ref": package_ref,
                        "manifest_digest": manifest_digest,
                    },
                    context=context,
                    plugin=mismatched_target,
                )
                self.assertEqual(denied.get("status"), "rejected", denied)
                target_read = self._read(
                    "migration-manifest-exact-set",
                    plugin=mismatched_target,
                )
                self.assertIs(target_read.get("target_active"), False)
                self.assertFalse(mismatched_target.health_writes_allowed())
                self.assertFalse(mismatched_target.model_effects_allowed())
                self.assertFalse(mismatched_target.outbound_effects_allowed())

    def test_v117_06_offline_target_activates_only_after_one_writer_transfer(self) -> None:
        """A6: target validation cannot create a dual-writer window."""

        self._require_lifecycle(root=False)
        self._restart_lifecycle(root=False)
        old_vm = self.plugin
        old_snapshot = self.head.read().head
        old_authority = old_snapshot.as_authority()
        old_vault = InMemoryWriterFenceVault()
        old_vault.bind(old_authority, self.v116.base.writer_capability)
        old_session = old_vault.acquire_or_resume(
            old_authority.installation_id,
            old_authority.site,
            WriterHolderClaim("writer-holder:ticket117-old-vm"),
        )
        self.assertIsNotNone(old_session)
        assert old_session is not None
        old_proof = old_session.proof_for(old_authority)
        self.assertIsNotNone(old_proof)
        task_id, effect_request_id = self.v116.harness._admit_review_task()
        intent_id = self.v116.harness._commit_review_outbox(
            task_id,
            effect_request_id,
        )
        old_model_request, old_model_source, old_model_grant = (
            self._form_strict_model_grant(
                source_suffix="ticket117-model-before-transfer"
            )
        )
        ready = self._prepare_migration("migration-one-cas")
        self.assertEqual(ready.get("status"), "manifest-ready", ready)
        before_cas = self._read("migration-one-cas")
        self.assertFalse(before_cas.get("target_active", False))
        self.assertFalse(self.plugin.health_writes_allowed())
        target = self._offline_target()
        accepted = self._execute(
            {
                "kind": "accept-migration",
                "operation_ref": "migration-one-cas",
                "package_ref": ready["package_ref"],
                "manifest_digest": ready["manifest_digest"],
            },
            plugin=target,
        )
        self.assertIn(accepted.get("status"), {"manifest-ready", "replayed"}, accepted)
        self.assertFalse(target.health_writes_allowed())
        completed = self._prepare_migration("migration-one-cas")
        self.assertIn(completed.get("status"), {"completed", "replayed"}, completed)
        self.assertEqual(self.head.mutable_calls, 1)
        source_final = self._read("migration-one-cas")
        target_final = self._read("migration-one-cas", plugin=target)
        self.assertFalse(source_final.get("source_active"), source_final)
        self.assertTrue(target_final.get("target_active"), target_final)
        self.assertFalse(self.plugin.health_writes_allowed())
        self.assertFalse(self.plugin.model_effects_allowed())
        self.assertFalse(self.plugin.outbound_effects_allowed())
        self.assertTrue(target.health_writes_allowed())
        self.assertTrue(target.model_effects_allowed())
        self.assertTrue(target.outbound_effects_allowed())
        self.assertFalse(self.head.validate_writer_fence(old_proof))

        old_model_adapter = _NeverModelAdapter()
        old_model_outcome = old_vm.execute_strict_health_model(
            self.v116.llm,
            old_model_request,
            old_model_source,
            old_model_grant,  # type: ignore[arg-type]
            old_model_adapter,
        )
        self.assertEqual(
            (old_model_outcome.disposition, old_model_outcome.model_effect),
            ("failed-closed", "not-started"),
        )
        self.assertEqual(old_model_adapter.calls, 0)

        old_context = {
            "source": "health_tasks",
            "causal_id": "ticket117-old-vm-task-after-transfer",
            "generation": old_snapshot.generation,
            "scope": ["task:advance"],
        }
        try:
            old_task_result = old_vm.health_operation(
                "task.advance",
                {
                    "task_id": task_id,
                    "phase": "in-progress",
                    "advanced_at_utc": "2026-08-28T02:00:00+00:00",
                },
                context=old_context,
                peer_id=_PEER,
            )
        except (ProtocolViolation, AuthorityValidationError):
            old_task_result = {"status": "rejected"}
        self.assertEqual(old_task_result.get("status"), "rejected", old_task_result)
        try:
            old_model_result = old_vm.health_operation(
                "diagnosis.prepare",
                self.v116._diagnosis_prepare_payload(
                    source_suffix="ticket117-old-vm-model"
                ),
                context={
                    "source": "diagnostic_runtime",
                    "causal_id": "ticket117-old-vm-model-after-transfer",
                    "generation": old_snapshot.generation,
                    "scope": ["diagnosis:prepare"],
                },
                peer_id=_PEER,
            )
        except (ProtocolViolation, AuthorityValidationError):
            old_model_result = {"status": "rejected"}
        self.assertEqual(old_model_result.get("status"), "rejected", old_model_result)
        self.assertNotIn("model_intent", old_model_result)
        with self.assertRaises((ProtocolViolation, AuthorityValidationError)):
            old_vm.controlled_effect(
                "owner-delivery.prepare",
                {
                    "intent_id": intent_id,
                    "attempted_at_utc": "2026-08-28T02:00:01+00:00",
                },
                peer_id=_PEER,
            )

        # A transfer CAS conflict is a separate authority outcome from the
        # successful transfer above: it must activate neither side and must not
        # invent an abort/unfreeze path for the source.
        conflict = type(self)(self._testMethodName)
        conflict.setUp()
        self._extra_harnesses.append(conflict)
        conflict._restart_lifecycle(root=False)
        conflict_ready = conflict._prepare_migration("migration-transfer-conflict")
        self.assertEqual(
            conflict_ready.get("status"),
            "manifest-ready",
            conflict_ready,
        )
        conflict_target = conflict._offline_target()
        conflict_accepted = conflict._execute(
            {
                "kind": "accept-migration",
                "operation_ref": "migration-transfer-conflict",
                "package_ref": conflict_ready["package_ref"],
                "manifest_digest": conflict_ready["manifest_digest"],
            },
            plugin=conflict_target,
        )
        self.assertIn(
            conflict_accepted.get("status"),
            {"manifest-ready", "replayed"},
            conflict_accepted,
        )
        conflict.head.failure = "conflict"
        conflict_result = conflict._prepare_migration("migration-transfer-conflict")
        self.assertEqual(conflict_result.get("status"), "rejected", conflict_result)
        conflict_source_read = conflict._read("migration-transfer-conflict")
        conflict_target_read = conflict._read(
            "migration-transfer-conflict",
            plugin=conflict_target,
        )
        self.assertIs(conflict_source_read.get("source_active"), False)
        self.assertIs(conflict_target_read.get("target_active"), False)
        self.assertFalse(conflict.plugin.health_writes_allowed())
        self.assertFalse(conflict.plugin.model_effects_allowed())
        self.assertFalse(conflict.plugin.outbound_effects_allowed())
        self.assertFalse(conflict_target.health_writes_allowed())
        self.assertFalse(conflict_target.model_effects_allowed())
        self.assertFalse(conflict_target.outbound_effects_allowed())
        self.assertEqual(conflict.head.mutable_calls, 1)

    def test_v117_07_transfer_unknown_closes_both_sides_and_preserves_unknown_effect(self) -> None:
        """A7: migration cannot turn a possibly-sent effect into replay work."""

        self._require_lifecycle(root=False)
        self._restart_lifecycle(root=False)
        old_vm = self.plugin
        _, unknown_intent, spent_grant = self._seed_unknown_owner_delivery()
        ready = self._prepare_migration("migration-transfer-unknown")
        package = self.artifacts.get(ready["package_ref"])
        self.assertIsNotNone(package)
        opaque_package_before = copy.deepcopy(package)
        target = self._offline_target()
        self.head.failure = "unknown-after-apply"
        result = self._execute(
            {
                "kind": "accept-migration",
                "operation_ref": "migration-transfer-unknown",
                "package_ref": ready["package_ref"],
                "manifest_digest": ready["manifest_digest"],
            },
            plugin=target,
        )
        self.assertIn(result.get("status"), {"manifest-ready", "replayed"}, result)
        resumed = self._prepare_migration("migration-transfer-unknown")
        self.assertEqual(resumed.get("status"), "unknown", resumed)
        source_read = self._read("migration-transfer-unknown")
        target_read = self._read("migration-transfer-unknown", plugin=target)
        self.assertIs(source_read.get("source_active"), False)
        self.assertIs(target_read.get("target_active"), False)
        retained = self.artifacts.get(ready["package_ref"])
        self.assertIsNotNone(retained)
        self.assertEqual(retained, opaque_package_before)
        replay_transport = _DeliveryAdapter()
        try:
            replay = old_vm.controlled_effect(
                "owner-delivery.execute",
                {
                    "intent_id": unknown_intent.effect_id,  # type: ignore[attr-defined]
                    "attempted_at_utc": "2026-08-28T02:10:00+00:00",
                    "observed_at_utc": "2026-08-28T02:10:01+00:00",
                },
                grant=spent_grant,  # type: ignore[arg-type]
                transport=replay_transport,
                peer_id=_PEER,
            )
        except (ProtocolViolation, AuthorityValidationError):
            replay = {"status": "rejected"}
        self.assertEqual(replay_transport.calls, 0)
        replay_status = (
            replay.get("transport_result", {}).get("status")
            if isinstance(replay.get("transport_result"), Mapping)
            else replay.get("status")
        )
        self.assertIn(replay_status, {"unknown", "rejected"}, replay)
        self.assertEqual(self.head.mutable_calls, 1)
        lookups_before_restart = self.head.lookup_calls
        self._restart_lifecycle(root=False)
        self.assertEqual(self.head.mutable_calls, 1)
        self.assertGreater(self.head.lookup_calls, lookups_before_restart)
        resolved_source = self._read("migration-transfer-unknown")
        resolved_target = self._read(
            "migration-transfer-unknown", plugin=target
        )
        self.assertIs(resolved_source.get("source_active"), False)
        self.assertIs(resolved_target.get("target_active"), True)
        retained_after_restart = self.artifacts.get(ready["package_ref"])
        self.assertIsNotNone(retained_after_restart)
        self.assertEqual(retained_after_restart, opaque_package_before)

        # If exact readback is itself unavailable, neither side may infer the
        # winner.  Recovery must still call lookup and never make a second CAS.
        unavailable = type(self)(self._testMethodName)
        unavailable.setUp()
        self._extra_harnesses.append(unavailable)
        unavailable._require_lifecycle(root=False)
        unavailable._restart_lifecycle(root=False)
        unavailable_ready = unavailable._prepare_migration(
            "migration-transfer-lookup-unavailable"
        )
        unavailable_target = unavailable._offline_target()
        unavailable.head.failure = "unknown-after-apply"
        staged = unavailable._execute(
            {
                "kind": "accept-migration",
                "operation_ref": "migration-transfer-lookup-unavailable",
                "package_ref": unavailable_ready["package_ref"],
                "manifest_digest": unavailable_ready["manifest_digest"],
            },
            plugin=unavailable_target,
        )
        self.assertIn(staged.get("status"), {"manifest-ready", "replayed"})
        unresolved = unavailable._prepare_migration(
            "migration-transfer-lookup-unavailable"
        )
        self.assertEqual(unresolved.get("status"), "unknown", unresolved)
        unavailable.head.failure = "lookup-unavailable"
        unavailable_lookups = unavailable.head.lookup_calls
        unavailable._restart_lifecycle(root=False)
        self.assertEqual(unavailable.head.mutable_calls, 1)
        self.assertGreater(unavailable.head.lookup_calls, unavailable_lookups)
        unavailable_source = unavailable._read(
            "migration-transfer-lookup-unavailable"
        )
        unavailable_target_view = unavailable._read(
            "migration-transfer-lookup-unavailable",
            plugin=unavailable_target,
        )
        self.assertIs(unavailable_source.get("source_active"), False)
        self.assertIs(unavailable_target_view.get("target_active"), False)
        self.assertFalse(unavailable.plugin.health_writes_allowed())
        self.assertFalse(unavailable.plugin.model_effects_allowed())
        self.assertFalse(unavailable.plugin.outbound_effects_allowed())
        self.assertFalse(unavailable_target.health_writes_allowed())
        self.assertFalse(unavailable_target.model_effects_allowed())
        self.assertFalse(unavailable_target.outbound_effects_allowed())

    def test_v117_08_semantic_round_trip_preserves_source_time_and_relationships(self) -> None:
        """A8: file-level equality cannot hide semantic loss or source rewrite."""

        self._require_lifecycle(root=False)
        self.v116._activate_synthetic_scope_through_ticket119()
        task_id, unknown_intent, _ = self._seed_unknown_owner_delivery()
        unknown_ref = unknown_intent.effect_id  # type: ignore[attr-defined]
        self.v116._health(
            "safety.evaluate",
            {
                "source_causal_id": "ticket117-semantic-source-continuity",
                "event_time": "2026-08-24T04:20:00+00:00",
                "safety_rule_bundle_hash": self.v116.safety_bundle_hash,
                "facts": {
                    "safety_capability": "available",
                    "danger": "unknown",
                    "scope": "in-scope",
                },
            },
            suffix="ticket117-semantic-source-continuity",
        )
        before = self._public_semantic_views(self.plugin)
        before_ticket = before["ticket115_tasks_review_delivery"]
        assert isinstance(before_ticket, Mapping)
        self.assertIn(unknown_ref, before_ticket["delivery_unknown_refs"])
        self.assertIn(task_id, repr(before))
        self.assertIn("ticket117-semantic-source-continuity", repr(before))
        self.assertIn("2026-08-24T04:20:00+00:00", repr(before))
        self._restart_lifecycle(root=False)
        ready = self._prepare_migration("migration-semantic-round-trip")
        target = self._offline_target()
        accepted = self._execute(
            {
                "kind": "accept-migration",
                "operation_ref": "migration-semantic-round-trip",
                "package_ref": ready["package_ref"],
                "manifest_digest": ready["manifest_digest"],
            },
            plugin=target,
        )
        self.assertIn(accepted.get("status"), {"manifest-ready", "replayed"}, accepted)
        completed = self._prepare_migration("migration-semantic-round-trip")
        self.assertIn(completed.get("status"), {"completed", "replayed"}, completed)
        after = self._public_semantic_views(target)
        self.assertEqual(after, before)
        after_ticket = after["ticket115_tasks_review_delivery"]
        assert isinstance(after_ticket, Mapping)
        self.assertIn(unknown_ref, after_ticket["delivery_unknown_refs"])
        rendered = repr(after)
        self.assertIn(task_id, rendered)
        self.assertIn(unknown_ref, rendered)
        self.assertIn("ticket117-semantic-source-continuity", rendered)
        self.assertIn("2026-08-24T04:20:00+00:00", rendered)
        self.assertNotIn("synthetic-target-site-rewritten-source", rendered)
        self.assertNotIn("migration-time-rewritten-event-time", rendered)

    def test_v117_09_only_exact_current_owner_delete_all_forms_one_notice(self) -> None:
        """A9: neighboring controls and vague close requests cannot terminalize."""

        self._require_lifecycle(root=False)
        self._restart_lifecycle(root=False)
        task_id, _ = self.v116.harness._admit_review_task()

        def assert_control_does_not_enter_lifecycle(operation: object) -> None:
            before = self._lifecycle_state_without_authority(self._read(None))
            operation()  # type: ignore[operator]
            after = self._lifecycle_state_without_authority(self._read(None))
            self.assertEqual(after, before)

        def pause_proactive_support() -> None:
            current = self.plugin.owner_settings_state(peer_id=_PEER)
            snapshot = self.head.read().head
            request = self.v116.base._owner_request(
                correction=False,
                settings_command=settings.ControlUpdate(
                    control_name="proactive_support",
                    operation="pause",
                    target_ref=None,
                    generation=snapshot.generation,
                    effective_at_utc="2026-08-28T02:20:00+00:00",
                ),
                expected_settings_version=current.version,
                command_suffix=":ticket117-pause-proactive-support",
            )
            self._commit_owner_request(request)

        def stop_recording() -> None:
            current = self.plugin.owner_settings_state(peer_id=_PEER)
            request = self.v116.base._owner_request(
                correction=False,
                control_name="recording",
                control_operation="stop",
                expected_settings_version=current.version,
                command_suffix=":ticket117-stop-recording",
            )
            self._commit_owner_request(request)

        def cancel_task() -> None:
            request = self.v116.harness._owner_task_cancellation_request(
                task_id,
                suffix=":ticket117-cancel-task",
            )
            self._commit_owner_request(request)

        def revoke_execution_approval() -> None:
            current = self.plugin.owner_settings_state(peer_id=_PEER)
            snapshot = self.head.read().head
            command = settings.OwnerControlCommand(
                context=settings.OwnerCommandContext(
                    command_id="settings-command:ticket117-revoke-approval",
                    causal_id="settings-source:ticket117-revoke-approval",
                    actor_kind="current_owner",
                    owner_id="owner-A",
                    installation_id=snapshot.installation_id,
                    permission="health_settings.write",
                    context_ref="managed-context:ticket117-revoke-approval",
                    generation=snapshot.generation,
                    writer_fence=snapshot.writer_fence,
                ),
                control_update=settings.ControlUpdate(
                    control_name="execution_scope_approval",
                    operation="revoke",
                    target_ref="approval:ticket115-review-summary",
                    generation=snapshot.generation,
                    effective_at_utc="2026-08-28T02:23:00+00:00",
                ),
                execution_scope_approval=None,
            )
            self.v116.harness._apply_owner_setting(
                command,
                expected_version=current.version,
                suffix=":ticket117-revoke-approval",
            )

        for label, operation in (
            ("pause-proactive-support", pause_proactive_support),
            ("stop-recording", stop_recording),
            ("cancel-task", cancel_task),
            ("revoke-approval", revoke_execution_approval),
        ):
            with self.subTest(adjacent_public_control=label):
                assert_control_does_not_enter_lifecycle(operation)

        baseline = self._lifecycle_state_without_authority(self._read(None))
        generation = self.head.read().head.generation
        cases = (
            ("wrong-owner", _DELETE_SEMANTICS, generation, "owner_rights_runtime", "lifecycle:delete", "owner-command:other"),
            ("old-generation", _DELETE_SEMANTICS, generation - 1, "owner_rights_runtime", "lifecycle:delete", "owner-command:old"),
            ("close-keep", "close-health-steward-but-keep-data", generation, "owner_rights_runtime", "lifecycle:delete", "owner-command:close"),
            ("missing-scope", _DELETE_SEMANTICS, generation, "owner_rights_runtime", None, "owner-command:missing-scope"),
            ("wrong-scope", _DELETE_SEMANTICS, generation, "owner_rights_runtime", "lifecycle:prepare-migration", "owner-command:wrong-scope"),
        )
        for label, semantics, command_generation, source, scope, owner_ref in cases:
            with self.subTest(rejected_delete_class=label):
                payload = self._delete_payload(f"invalid-{label}")
                payload["semantics"] = semantics
                payload["owner_command_ref"] = owner_ref
                context = self._context(
                    kind="delete-all",
                    generation=command_generation,
                    source=("untrusted_owner_runtime" if label == "wrong-owner" else source),
                    scope=("lifecycle:delete" if scope is None else scope),
                )
                if label == "missing-scope":
                    context.pop("scope")
                try:
                    result = self.plugin.health_operation(
                        "lifecycle.execute", payload, context=context, peer_id=_PEER
                    )
                except (ProtocolViolation, AuthorityValidationError):
                    result = {"status": "rejected"}
                self.assertEqual(result.get("status"), "rejected", result)
                self.assertEqual(
                    self._lifecycle_state_without_authority(self._read(None)),
                    baseline,
                )
        valid_ref = "delete-exact-current-owner"
        payload = self._delete_payload(valid_ref)
        context = self._context(
            kind="delete-all", causal_id=f"ticket117-delete-causal:{valid_ref}"
        )
        first = self._execute(payload, context=context)
        replay = self._execute(payload, context=context)
        self.assertEqual(first.get("status"), "notice-pending", first)
        self.assertIn(replay.get("status"), {"notice-pending", "replayed"}, replay)
        deliveries = self.plugin.managed_ticket115_read(peer_id=_PEER)["owner_deliveries"]
        notices = [
            item for item in deliveries
            if item["intent"].get("effect_request_id") == valid_ref
            or item["intent"].get("payload_ref") == f"lifecycle-notice:{valid_ref}"
        ]
        self.assertEqual(len(notices), 1)


if __name__ == "__main__":
    unittest.main()

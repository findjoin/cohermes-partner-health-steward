import sqlite3
import threading
import unittest
from dataclasses import replace

from partner_health_steward import HealthCore, HealthPlugin
from partner_health_steward.admission import AdmissionPolicy, RawWeixinMessage
from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.core import InMemoryWriterFenceVault
from partner_health_steward.contract import (
    CommandEnvelope,
    InitializationPreparePayload,
    ProtocolViolation,
)
from partner_health_steward.current_head import FailureMode, InMemoryCurrentHead
from partner_health_steward.initialization import (
    HealthInitAsset,
    HealthInitAttestor,
    HealthInitRuntime,
    InitialPreferences,
    OwnerInitialization,
    SupportContactBoundary,
)
from partner_health_steward.storage import EncryptedStateStore, StaticKeyProvider


class CountingBody:
    def __init__(self, text):
        self._text = text
        self.reads = 0

    def read(self):
        self.reads += 1
        return self._text


class FinalReceiptCommitFailureStore(EncryptedStateStore):
    """Fail one outer commit after the final response receipt is written."""

    def __init__(self, database, key_provider):
        super().__init__(database, key_provider)
        self.fail_after_receipt = False

    def save_receipt(self, *args, **kwargs):
        result = super().save_receipt(*args, **kwargs)
        if self.fail_after_receipt:
            self.fail_after_receipt = False
            self._connection.set_authorizer(self._deny_commit)
        return result

    @staticmethod
    def _deny_commit(action, argument_one, argument_two, database, trigger):
        del argument_two, database, trigger
        if action == sqlite3.SQLITE_TRANSACTION and argument_one == "COMMIT":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def clear_failure(self):
        self._connection.set_authorizer(None)


class Ticket111AdmissionInitializationTests(unittest.TestCase):
    def setUp(self):
        self.writer_capability = "synthetic-writer-capability"
        self.key_provider = StaticKeyProvider(b"i" * 32, key_id="synthetic-init-key")
        self.store = EncryptedStateStore(
            "file:ticket111?mode=memory&cache=shared",
            self.key_provider,
        )
        self.head = InMemoryCurrentHead(
            installation_id="partner-installation",
            site="partner-site",
            writer_capability=self.writer_capability,
        )
        authority = self.head.read().head.as_authority()
        self.store.seed_finalized_authority(authority)
        self.writer_vault = InMemoryWriterFenceVault()
        self.writer_vault.bind(authority, self.writer_capability)
        self.policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-A",
            conversation_id="private-A",
        )
        self.init_attestor = HealthInitAttestor(
            b"a" * 32,
            key_id="synthetic-health-init-attestor",
        )
        self.init_asset = HealthInitAsset(
            version="1.0.0",
            asset_digest="sha256:" + ("1" * 64),
            disclosure_version="health-init-disclosure-v1",
        )
        self.init_runtime = HealthInitRuntime(self.init_asset, self.init_attestor)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )

    def tearDown(self):
        self.core.close()
        self.store.close()

    def message(self, body, **changes):
        values = {
            "causal_id": "delivery-1",
            "generation": 1,
            "channel": "weixin",
            "partner_id": "partner-A",
            "sender_id": "owner-A",
            "conversation_id": "private-A",
            "chat_type": "private",
            "entrypoint": "health_weixin",
            "requested_capability": "health-init",
            "message_id": "wx-message-1",
            "protocol_timestamp": "2026-08-23T09:00:00+08:00",
            "received_at": "2026-08-23T09:00:01+08:00",
            "native_cursor": "cursor-1",
            "body": body,
        }
        values.update(changes)
        return RawWeixinMessage(**values)

    def initialization_request(self, **changes):
        values = {
            "workflow_id": "init-workflow-1",
            "admission_causal_id": "delivery-1",
            "owner_consent": True,
            "first_hop_route": "jojo-responses-v1",
            "first_hop_route_consent": True,
            "timezone": "Asia/Shanghai",
            "preferences": InitialPreferences(
                contact_window="09:00-21:00",
                expression_style="concise",
                proactive_support=True,
            ),
            "data_boundary": (
                "health-portrait",
                "health-evidence",
                "health-tasks",
            ),
            "support_contact": SupportContactBoundary(
                contact_ref="synthetic-contact",
                method="weixin",
                purpose="emergency-support",
            ),
        }
        values.update(changes)
        return OwnerInitialization(**values)

    def admit_and_prepare(self):
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(CountingBody("start synthetic initialization")),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        result = self.plugin.prepare_initialization(
            self.initialization_request(),
            peer_id="plugin",
        )
        self.assertEqual(result.status, "accepted")
        return result

    def test_only_the_unique_private_health_init_source_may_materialize_body_and_create_a_receipt(self):
        for owner_value in ("", ("owner-A", "owner-B"), None):
            with self.subTest(owner_value=owner_value):
                with self.assertRaises(AuthorityValidationError):
                    AdmissionPolicy(
                        partner_id="partner-A",
                        owner_sender_id=owner_value,
                        conversation_id="private-A",
                    )
        rejected_cases = (
            {"sender_id": "outsider"},
            {"chat_type": "group", "conversation_id": "group-A"},
            {"entrypoint": "medical", "requested_capability": "medical"},
            {"sender_id": None},
        )
        for index, changes in enumerate(rejected_cases, start=1):
            with self.subTest(changes=changes):
                body = CountingBody("synthetic private health text")
                result = self.plugin.receive_weixin(
                    self.message(body, causal_id=f"rejected-{index}", **changes),
                    peer_id="plugin",
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(body.reads, 0)
                self.assertIsNone(self.plugin.source_envelope(f"rejected-{index}", peer_id="plugin"))

        body = CountingBody("start synthetic initialization")
        result = self.plugin.receive_weixin(self.message(body), peer_id="plugin")

        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.reason_code, "initialization-source-admitted")
        self.assertEqual(body.reads, 1)
        envelope = self.plugin.source_envelope("delivery-1", peer_id="plugin")
        self.assertEqual(envelope.causal_id, "delivery-1")
        self.assertEqual(envelope.partner_id, "partner-A")
        self.assertEqual(envelope.sender_id, "owner-A")
        self.assertEqual(envelope.message_id, "wx-message-1")
        self.assertEqual(envelope.protocol_timestamp, "2026-08-23T09:00:00+08:00")
        self.assertEqual(envelope.received_at, "2026-08-23T09:00:01+08:00")
        self.assertEqual(envelope.native_cursor, "cursor-1")
        self.assertEqual(envelope.body, "start synthetic initialization")

    def test_malformed_source_headers_are_rejected_before_sensitive_body_read(self):
        cases = (
            {"causal_id": True},
            {"generation": True},
            {"message_id": True},
            {"protocol_timestamp": 1},
            {"native_cursor": ""},
        )
        for index, changes in enumerate(cases, start=1):
            with self.subTest(changes=changes):
                body = CountingBody("synthetic health body")
                changes.setdefault("causal_id", f"malformed-{index}")
                result = self.plugin.receive_weixin(
                    self.message(body, **changes),
                    peer_id="plugin",
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(result.reason_code, "invalid-weixin-source")
                self.assertEqual(body.reads, 0)

    def test_preinitialization_health_or_danger_chat_is_not_read_or_backfilled(self):
        for index, text in enumerate(
            ("synthetic health history", "synthetic danger statement"),
            start=1,
        ):
            body = CountingBody(text)
            result = self.plugin.receive_weixin(
                self.message(
                    body,
                    causal_id=f"ordinary-{index}",
                    requested_capability="ordinary-chat",
                ),
                peer_id="plugin",
            )
            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason_code, "initialization-required")
            self.assertEqual(body.reads, 0)
            self.assertIsNone(
                self.plugin.source_envelope(f"ordinary-{index}", peer_id="plugin")
            )
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "uninitialized",
        )
        self.assertEqual(self.store.count_records(), 0)
        self.assertFalse(self.plugin.health_writes_allowed())
        self.assertFalse(self.plugin.model_effects_allowed())
        self.assertFalse(self.plugin.outbound_effects_allowed())
        model_request = self.plugin.invoke(
            CommandEnvelope(
                peer="plugin",
                action="effect.request",
                source="synthetic-bypass",
                causal_id="preinit-model-bypass",
                generation=1,
                scope=("effect:request",),
                payload={
                    "effect_kind": "model-work",
                    "request_digest": "sha256:preinit-model",
                },
            ),
            peer_id="plugin",
        )
        self.assertEqual(model_request.status, "rejected")
        self.assertEqual(model_request.reason_code, "initialization-required")
        self.assertEqual(self.store.count_effects(), 0)

    def test_exact_replay_is_equivalent_while_each_distinct_delivery_keeps_its_source(self):
        first_message = self.message(CountingBody("same synthetic text"))
        first = self.plugin.receive_weixin(first_message, peer_id="plugin")
        replay = self.plugin.receive_weixin(
            self.message(CountingBody("same synthetic text")),
            peer_id="plugin",
        )

        self.assertEqual(replay.to_wire(), first.to_wire())
        first_receipt = self.plugin.source_receipt("delivery-1", peer_id="plugin")
        self.assertEqual(first_receipt.relation, "first-observation")
        self.assertIsNone(first_receipt.related_causal_id)
        self.assertEqual(first_receipt.managed_cursor_state, "held")
        self.assertEqual(first_receipt.native_cursor_state, "not-ready")

        second = self.plugin.receive_weixin(
            self.message(
                CountingBody("same synthetic text"),
                causal_id="delivery-2",
                message_id="wx-message-2",
                protocol_timestamp="2026-08-23T09:00:02+08:00",
                received_at="2026-08-23T09:00:03+08:00",
                native_cursor="cursor-2",
            ),
            peer_id="plugin",
        )
        self.assertEqual(second.status, "accepted")
        self.assertEqual(
            self.plugin.source_receipt("delivery-2", peer_id="plugin").relation,
            "first-observation",
        )

        possible_replay = self.plugin.receive_weixin(
            self.message(
                CountingBody("same synthetic text"),
                causal_id="delivery-3",
                received_at="2026-08-23T09:00:04+08:00",
                native_cursor="cursor-3",
            ),
            peer_id="plugin",
        )
        self.assertEqual(possible_replay.status, "accepted")
        replay_receipt = self.plugin.source_receipt("delivery-3", peer_id="plugin")
        self.assertEqual(replay_receipt.relation, "possible-replay")
        self.assertEqual(replay_receipt.related_causal_id, "delivery-1")
        self.assertEqual(replay_receipt.envelope.body, "same synthetic text")

    def test_health_init_runtime_proof_and_complete_candidate_are_required_for_prepare(self):
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(CountingBody("start synthetic initialization")),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        unproved_plugin = HealthPlugin(self.core, admission_policy=self.policy)
        without_runtime = unproved_plugin.prepare_initialization(
            self.initialization_request(),
            peer_id="plugin",
        )
        self.assertEqual(without_runtime.status, "unavailable")
        self.assertEqual(without_runtime.reason_code, "health-init-runtime-unavailable")
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "uninitialized",
        )

        invalid = self.plugin.prepare_initialization(
            self.initialization_request(owner_consent=False),
            peer_id="plugin",
        )
        self.assertEqual(invalid.status, "rejected")
        self.assertEqual(invalid.reason_code, "owner-consent-required")
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "uninitialized",
        )

        prepared = self.plugin.prepare_initialization(
            self.initialization_request(),
            peer_id="plugin",
        )
        prepared_replay = self.plugin.prepare_initialization(
            self.initialization_request(),
            peer_id="plugin",
        )

        self.assertEqual(prepared.status, "accepted")
        self.assertEqual(prepared.reason_code, "initialization-prepared")
        self.assertEqual(prepared_replay.to_wire(), prepared.to_wire())
        status = self.plugin.initialization_status(peer_id="plugin")
        self.assertEqual(status.phase, "prepared")
        self.assertFalse(status.enabled)
        self.assertEqual(status.skill_use.canonical_name, "health-init")
        self.assertEqual(status.skill_use.version, "1.0.0")
        self.assertEqual(status.skill_use.disclosure_version, "health-init-disclosure-v1")
        self.assertEqual(status.first_hop_route, "jojo-responses-v1")
        self.assertEqual(status.timezone, "Asia/Shanghai")
        self.assertEqual(status.key_id, "synthetic-init-key")
        self.assertEqual(status.prepared_authority.generation, 1)
        self.assertEqual(status.initial_portrait.domain_states, ("unknown",) * 6)
        self.assertEqual(
            status.disclosed_topics,
            (
                "health-data-scope",
                "daily-review",
                "health-task-automation",
                "proactive-support",
                "first-hop-model-route",
                "support-contact",
                "owner-data-rights",
                "unknown-effects-not-retried",
            ),
        )
        conflict = self.plugin.prepare_initialization(
            self.initialization_request(timezone="UTC"),
            peer_id="plugin",
        )
        self.assertEqual(conflict.status, "rejected")
        self.assertEqual(conflict.reason_code, "health-init workflow conflict")
        self.assertEqual(self.store.count_records(), 1)

    def test_wrong_asset_forged_proof_and_model_self_report_cannot_prepare(self):
        self.plugin.receive_weixin(
            self.message(CountingBody("start synthetic initialization")),
            peer_id="plugin",
        )
        initialization = self.initialization_request()
        wrong_asset = HealthInitAsset(
            version="9.9.9",
            asset_digest="sha256:" + ("9" * 64),
            disclosure_version="unapproved-disclosure",
        )
        wrong_proof = HealthInitRuntime(wrong_asset, self.init_attestor).run(initialization)
        wrong_asset_command = CommandEnvelope(
            peer="plugin",
            action="initialization.prepare",
            source="health_weixin",
            causal_id="wrong-asset-proof",
            generation=1,
            scope=("initialization:prepare",),
            payload=InitializationPreparePayload(initialization, wrong_proof),
        )
        wrong_asset_response = self.plugin.invoke(wrong_asset_command, peer_id="plugin")
        self.assertEqual(wrong_asset_response.status, "rejected")
        self.assertEqual(wrong_asset_response.reason_code, "health-init-proof-required")

        valid_proof = self.init_runtime.run(initialization)
        forged_proof = replace(
            valid_proof,
            signature="hmac-sha256:" + ("0" * 64),
        )
        forged_command = replace(
            wrong_asset_command,
            causal_id="forged-proof",
            payload=InitializationPreparePayload(initialization, forged_proof),
        )
        forged_response = self.plugin.invoke(forged_command, peer_id="plugin")
        self.assertEqual(forged_response.status, "rejected")
        self.assertEqual(forged_response.reason_code, "health-init-proof-required")

        with self.assertRaises(ProtocolViolation):
            CommandEnvelope(
                peer="plugin",
                action="initialization.prepare",
                source="model-self-report",
                causal_id="model-self-report",
                generation=1,
                scope=("initialization:prepare",),
                payload={
                    "initialization": initialization.to_storage(),
                    "skill_proof": True,
                },
            )
        self.assertEqual(self.store.count_records(), 0)
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "uninitialized",
        )

    def test_health_init_executor_failure_never_creates_use_fact_or_initialization(self):
        self.plugin.receive_weixin(
            self.message(CountingBody("start synthetic initialization")),
            peer_id="plugin",
        )
        failed_runtime = HealthInitRuntime(
            self.init_asset,
            self.init_attestor,
            executor=lambda asset, request: False,
        )
        failed_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=failed_runtime,
        )

        response = failed_plugin.prepare_initialization(
            self.initialization_request(),
            peer_id="plugin",
        )

        self.assertEqual(response.status, "unavailable")
        self.assertEqual(response.reason_code, "health-init-execution-failed")
        self.assertEqual(self.store.count_records(), 0)
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "uninitialized",
        )

    def test_initialization_protocol_rejects_wrong_types_extra_scope_and_generic_state_bypass(self):
        values = self.initialization_request().to_storage()
        invalid_values = (
            {**values, "workflow_id": True},
            {**values, "owner_consent": "true"},
            {**values, "first_hop_route_consent": 1},
            {**values, "timezone": "+08:00"},
            {
                **values,
                "preferences": {
                    **values["preferences"],
                    "proactive_support": 1,
                },
            },
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(AuthorityValidationError):
                    OwnerInitialization.from_storage(value)

        proof = self.init_runtime.run(self.initialization_request())
        with self.assertRaises(ProtocolViolation):
            CommandEnvelope(
                peer="plugin",
                action="initialization.prepare",
                source="health_weixin",
                causal_id="extra-scope",
                generation=1,
                scope=("initialization:prepare", "state:commit"),
                payload=InitializationPreparePayload(
                    self.initialization_request(),
                    proof,
                ),
            )

        generic = CommandEnvelope(
            peer="plugin",
            action="state.candidate",
            source="synthetic-bypass",
            causal_id="generic-initialization-bypass",
            generation=1,
            scope=("state:candidate",),
            payload={
                "record_id": "owner-initialization",
                "revision_digest": "sha256:generic",
                "transition_id": "generic-transition",
                "payload_digest": "sha256:generic-payload",
            },
        )
        bypass = self.plugin.invoke(generic, peer_id="plugin")
        self.assertEqual(bypass.status, "rejected")
        self.assertEqual(bypass.reason_code, "generic-initialization-action-denied")
        self.assertEqual(self.store.count_records(), 0)
        self.assertFalse(self.plugin.health_writes_allowed())

    def test_only_finalize_enables_the_product_and_transition_replays_are_equivalent(self):
        self.assertFalse(self.plugin.health_writes_allowed())
        self.admit_and_prepare()
        self.assertFalse(self.plugin.health_writes_allowed())

        committed = self.plugin.commit_initialization(peer_id="plugin")
        committed_replay = self.plugin.commit_initialization(peer_id="plugin")

        self.assertEqual(committed.status, "accepted")
        self.assertEqual(committed.reason_code, "current-head-advanced")
        self.assertEqual(committed_replay.to_wire(), committed.to_wire())
        self.assertEqual(committed.meta["generation"], 2)
        status = self.plugin.initialization_status(peer_id="plugin")
        self.assertEqual(status.phase, "committed")
        self.assertFalse(status.enabled)
        self.assertEqual(status.business_state, "committed")
        self.assertEqual(status.disclosure_state, "formed")
        self.assertEqual(status.owner_delivery_state, "not-attempted")
        self.assertEqual(status.support_contact_approval_state, "not-effective")
        self.assertFalse(self.plugin.health_writes_allowed())

        finalized = self.plugin.finalize_initialization(peer_id="plugin")
        finalized_replay = self.plugin.finalize_initialization(peer_id="plugin")

        self.assertEqual(finalized.status, "accepted")
        self.assertEqual(finalized.reason_code, "revision-finalized")
        self.assertEqual(finalized_replay.to_wire(), finalized.to_wire())
        status = self.plugin.initialization_status(peer_id="plugin")
        self.assertEqual(status.phase, "enabled")
        self.assertTrue(status.enabled)
        self.assertEqual(status.business_state, "enabled")
        self.assertEqual(status.disclosure_state, "formed")
        self.assertEqual(status.owner_delivery_state, "unknown")
        self.assertEqual(status.support_contact_approval_state, "approved-boundary")
        self.assertTrue(self.plugin.health_writes_allowed())

        contact_delivery = self.plugin.invoke(
            CommandEnvelope(
                peer="plugin",
                action="effect.request",
                source="health_weixin",
                causal_id="contact-delivery-still-forbidden",
                generation=2,
                scope=("effect:request",),
                payload={
                    "effect_kind": "contact-delivery",
                    "request_digest": "sha256:contact-delivery",
                },
            ),
            peer_id="plugin",
        )
        self.assertEqual(contact_delivery.status, "rejected")
        self.assertEqual(
            contact_delivery.reason_code,
            "contact-delivery-not-supported-in-ticket-110",
        )
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)

    def test_cursor_is_released_only_after_finalize_and_unknown_does_not_repeat_business(self):
        self.plugin.receive_weixin(
            self.message(CountingBody("start synthetic initialization")),
            peer_id="plugin",
        )
        initial_receipt = self.plugin.source_receipt("delivery-1", peer_id="plugin")
        self.assertEqual(initial_receipt.managed_cursor_state, "held")
        self.assertEqual(initial_receipt.native_cursor_state, "not-ready")
        self.assertIsNone(self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"))

        self.plugin.prepare_initialization(self.initialization_request(), peer_id="plugin")
        self.plugin.commit_initialization(peer_id="plugin")
        self.assertIsNone(self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"))

        self.plugin.finalize_initialization(peer_id="plugin")
        receipt = self.plugin.source_receipt("delivery-1", peer_id="plugin")
        self.assertEqual(receipt.managed_cursor_state, "committed")
        self.assertEqual(receipt.native_cursor_state, "ready")
        self.assertIsNone(receipt.envelope.body)
        directive = self.plugin.native_cursor_directive("delivery-1", peer_id="plugin")
        self.assertEqual(directive.native_cursor, "cursor-1")
        self.assertEqual(
            self.plugin.source_receipt("delivery-1", peer_id="plugin").native_cursor_state,
            "executing",
        )
        self.assertIsNone(self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"))

        unknown = self.plugin.record_native_cursor_result(
            directive,
            status="unknown",
            peer_id="plugin",
        )
        replay = self.plugin.record_native_cursor_result(
            directive,
            status="unknown",
            peer_id="plugin",
        )
        self.assertEqual(unknown.status, "unknown")
        self.assertEqual(unknown.reason_code, "native-cursor-unknown")
        self.assertEqual(replay.to_wire(), unknown.to_wire())
        self.assertEqual(
            self.plugin.source_receipt("delivery-1", peer_id="plugin").native_cursor_state,
            "unknown",
        )
        self.assertIsNone(self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"))
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)
        self.assertTrue(self.plugin.health_writes_allowed())

    def test_remote_cas_response_loss_recovers_by_transition_without_false_enablement(self):
        self.admit_and_prepare()
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")

        uncertain = self.plugin.commit_initialization(peer_id="plugin")

        self.assertEqual(uncertain.status, "unknown")
        self.assertEqual(self.head.read().head.generation, 2)
        status = self.plugin.initialization_status(peer_id="plugin")
        self.assertEqual(status.phase, "unknown")
        self.assertFalse(status.enabled)
        self.assertIsNone(self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"))

        self.head.clear_failure()
        recovered = self.plugin.commit_initialization(peer_id="plugin")
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(recovered.reason_code, "current-head-advanced")
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "committed",
        )
        self.assertFalse(self.plugin.health_writes_allowed())

        self.assertEqual(
            self.plugin.finalize_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)

    def test_enabled_state_survives_restart_and_transient_head_failure_recovers_in_place(self):
        self.admit_and_prepare()
        self.plugin.commit_initialization(peer_id="plugin")
        self.plugin.finalize_initialization(peer_id="plugin")
        self.assertTrue(self.plugin.health_writes_allowed())

        self.assertTrue(self.core.close().complete)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)
        self.assertTrue(self.plugin.health_writes_allowed())

        self.head.set_failure(FailureMode.TIMEOUT, operation="read")
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)
        self.assertFalse(self.plugin.health_writes_allowed())

        self.head.clear_failure()
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)
        self.assertTrue(self.plugin.health_writes_allowed())

    def test_prepared_initialization_cannot_cross_installations_with_matching_strings(self):
        self.admit_and_prepare()
        self.assertTrue(self.core.close().complete)

        foreign_head = InMemoryCurrentHead(
            installation_id="foreign-installation",
            site="partner-site",
            writer_capability=self.writer_capability,
        )
        foreign_vault = InMemoryWriterFenceVault()
        foreign_vault.bind(foreign_head.read().head.as_authority(), self.writer_capability)
        self.core = HealthCore(
            self.store,
            foreign_head,
            writer_fence_vault=foreign_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )

        response = self.plugin.commit_initialization(peer_id="plugin")

        self.assertEqual(response.status, "unavailable")
        self.assertIn(
            response.reason_code,
            {"current-writer-holder-missing", "prepared-installation-mismatch"},
        )
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "prepared",
        )
        self.assertEqual(foreign_head.read().head.generation, 1)
        self.assertFalse(self.plugin.health_writes_allowed())

    def test_finalize_business_cursor_and_response_receipt_are_one_atomic_commit(self):
        self.assertTrue(self.core.close().complete)
        self.store.close()
        self.store = FinalReceiptCommitFailureStore(
            "file:ticket111-final-receipt-failure?mode=memory&cache=shared",
            self.key_provider,
        )
        authority = self.head.read().head.as_authority()
        self.store.seed_finalized_authority(authority)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )
        self.admit_and_prepare()
        self.plugin.commit_initialization(peer_id="plugin")
        self.store.fail_after_receipt = True

        failed = self.plugin.finalize_initialization(peer_id="plugin")

        self.assertEqual(failed.status, "unavailable")
        self.store.clear_failure()
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "committed",
        )
        self.assertFalse(self.plugin.initialization_status(peer_id="plugin").enabled)
        self.assertIsNone(self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"))

        recovered = self.plugin.finalize_initialization(peer_id="plugin")
        self.assertEqual(recovered.status, "accepted")
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)
        self.assertEqual(
            self.plugin.source_receipt("delivery-1", peer_id="plugin").native_cursor_state,
            "ready",
        )

    def test_cursor_result_response_loss_replays_close_without_reissuing_execution(self):
        self.assertTrue(self.core.close().complete)
        self.store.close()
        self.store = FinalReceiptCommitFailureStore(
            "file:ticket111-cursor-receipt-failure?mode=memory&cache=shared",
            self.key_provider,
        )
        self.store.seed_finalized_authority(self.head.read().head.as_authority())
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )
        self.admit_and_prepare()
        self.plugin.commit_initialization(peer_id="plugin")
        self.plugin.finalize_initialization(peer_id="plugin")
        directive = self.plugin.native_cursor_directive("delivery-1", peer_id="plugin")
        self.assertIsNotNone(directive)
        self.assertIsNone(self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"))
        self.assertTrue(self.core.close().complete)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )
        self.assertIsNone(self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"))
        self.store.fail_after_receipt = True

        lost = self.plugin.record_native_cursor_result(
            directive,
            status="advanced",
            peer_id="plugin",
        )

        self.assertEqual(lost.status, "unavailable")
        self.store.clear_failure()
        self.assertEqual(
            self.plugin.source_receipt("delivery-1", peer_id="plugin").native_cursor_state,
            "executing",
        )
        self.assertIsNone(self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"))
        recovered = self.plugin.record_native_cursor_result(
            directive,
            status="advanced",
            peer_id="plugin",
        )
        replay = self.plugin.record_native_cursor_result(
            directive,
            status="advanced",
            peer_id="plugin",
        )
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(replay.to_wire(), recovered.to_wire())
        self.assertEqual(
            self.plugin.source_receipt("delivery-1", peer_id="plugin").native_cursor_state,
            "advanced",
        )
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)

    def test_concurrent_initialization_candidates_create_only_one_owner_aggregate(self):
        self.plugin.receive_weixin(
            self.message(CountingBody("initialize one")),
            peer_id="plugin",
        )
        self.plugin.receive_weixin(
            self.message(
                CountingBody("initialize two"),
                causal_id="delivery-2",
                message_id="wx-message-2",
                native_cursor="cursor-2",
            ),
            peer_id="plugin",
        )
        requests = (
            self.initialization_request(),
            self.initialization_request(
                workflow_id="init-workflow-2",
                admission_causal_id="delivery-2",
            ),
        )
        barrier = threading.Barrier(2)
        responses = []

        def prepare(request):
            barrier.wait(timeout=2)
            responses.append(
                self.plugin.prepare_initialization(request, peer_id="plugin")
            )

        workers = [threading.Thread(target=prepare, args=(request,)) for request in requests]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())

        self.assertEqual(sorted(response.status for response in responses), ["accepted", "rejected"])
        self.assertEqual(self.store.count_records(), 1)
        status = self.plugin.initialization_status(peer_id="plugin")
        self.assertEqual(status.phase, "prepared")
        self.assertIn(status.skill_use.workflow_id, {"init-workflow-1", "init-workflow-2"})
        winning_source = status.skill_use.admission_causal_id
        losing_source = "delivery-2" if winning_source == "delivery-1" else "delivery-1"
        self.plugin.commit_initialization(peer_id="plugin")
        self.plugin.finalize_initialization(peer_id="plugin")
        self.assertIsNotNone(
            self.plugin.native_cursor_directive(winning_source, peer_id="plugin")
        )
        self.assertIsNone(
            self.plugin.native_cursor_directive(losing_source, peer_id="plugin")
        )
        losing_receipt = self.plugin.source_receipt(losing_source, peer_id="plugin")
        self.assertEqual(losing_receipt.managed_cursor_state, "held")
        self.assertEqual(losing_receipt.native_cursor_state, "not-ready")


if __name__ == "__main__":
    unittest.main()

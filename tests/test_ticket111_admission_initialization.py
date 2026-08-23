import json
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from partner_health_steward import HealthCore, HealthPlugin
from partner_health_steward.admission import AdmissionPolicy, RawWeixinMessage
from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.core import (
    InMemoryExecutionCapabilityVault,
    InMemoryWriterFenceVault,
)
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
    OwnerConsentEvidence,
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
        self.init_runtime = HealthInitRuntime(
            self.init_asset,
            self.init_attestor,
            clock=lambda: datetime(2026, 8, 23, 0, 59, tzinfo=timezone.utc),
        )
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

    def consent_body(self, initialization=None, *, resolved_source_causal_ids=()):
        request = initialization or self.initialization_request()
        disclosure_request = replace(
            request,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        disclosure = self.plugin.form_initialization_disclosure(
            disclosure_request,
            peer_id="plugin",
        )
        return CountingBody(
            OwnerConsentEvidence.for_initialization(
                request,
                self.init_asset,
                disclosure,
                owner_confirmed=True,
                first_hop_route_confirmed=True,
                resolved_source_causal_ids=resolved_source_causal_ids,
            ).to_message_body()
        )

    def admit_and_prepare(self):
        initialization = self.initialization_request()
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(self.consent_body(initialization)),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        result = self.plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )
        self.assertEqual(result.status, "accepted")
        return result

    def test_only_the_unique_private_health_init_source_may_materialize_body_and_create_a_receipt(
        self,
    ):
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
                self.assertIsNone(
                    self.plugin.source_envelope(
                        f"rejected-{index}",
                        peer_id="plugin",
                    )
                )

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
            {"causal_id": "x" * 257},
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

    def test_missing_native_message_identifier_preserves_replay_ambiguity(self):
        for index in (1, 2):
            causal_id = f"unidentified-delivery-{index}"
            response = self.plugin.receive_weixin(
                self.message(
                    CountingBody("same unidentified synthetic text"),
                    causal_id=causal_id,
                    message_id=None,
                    native_cursor=f"unidentified-cursor-{index}",
                ),
                peer_id="plugin",
            )
            self.assertEqual(response.status, "accepted")
            receipt = self.plugin.source_receipt(causal_id, peer_id="plugin")
            self.assertEqual(receipt.relation, "replay-unknown")
            self.assertIsNone(receipt.related_causal_id)

    def test_health_init_runtime_proof_and_complete_candidate_are_required_for_prepare(self):
        initialization = self.initialization_request()
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(self.consent_body(initialization)),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        unproved_plugin = HealthPlugin(self.core, admission_policy=self.policy)
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "health-init-runtime-unavailable",
        ):
            unproved_plugin.form_initialization_disclosure(
                replace(
                    self.initialization_request(
                        workflow_id="unproved-workflow",
                        admission_causal_id="unproved-delivery",
                    ),
                    owner_consent=False,
                    first_hop_route_consent=False,
                ),
                peer_id="plugin",
            )
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

        prepared = unproved_plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )
        prepared_replay = self.plugin.prepare_initialization(
            initialization,
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

    def test_disclosure_challenge_is_prior_durable_and_owner_visible(self):
        initialization = self.initialization_request()
        preconsent = replace(
            initialization,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "initialization-disclosure-before-consent-required",
        ):
            self.plugin.form_initialization_disclosure(
                initialization,
                peer_id="plugin",
            )

        disclosure = self.plugin.form_initialization_disclosure(
            preconsent,
            peer_id="plugin",
        )
        notices = {
            notice.topic: notice.text
            for notice in disclosure.content.owner_visible_notices
        }
        self.assertEqual(set(notices), set(disclosure.content.disclosed_topics))
        self.assertIn("加密受管状态", notices["health-data-scope"])
        self.assertIn("自动复盘", notices["daily-review"])
        self.assertIn("自动建立、合并、重新判断并跟踪", notices["health-task-automation"])
        self.assertIn("当前控制与批准边界", notices["proactive-support"])
        self.assertIn("jojo-responses-v1", notices["first-hop-model-route"])
        self.assertIn("synthetic-contact", notices["support-contact"])
        self.assertIn("预置配置本身不构成授权", notices["support-contact"])
        self.assertIn("明确启用整个健康管家后", notices["support-contact"])
        self.assertIn("查看、纠正、导出和永久删除", notices["owner-data-rights"])
        self.assertIn("不会自动重试", notices["unknown-effects-not-retried"])

        self.assertTrue(self.core.close().complete)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )

        def must_not_execute(asset, request):
            del asset, request
            raise AssertionError("durable disclosure replay reran health-init")

        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=HealthInitRuntime(
                self.init_asset,
                self.init_attestor,
                executor=must_not_execute,
            ),
        )
        self.assertEqual(
            self.plugin.form_initialization_disclosure(
                preconsent,
                peer_id="plugin",
            ),
            disclosure,
        )

    def test_disclosure_policy_rotation_cannot_replay_or_prepare_old_authority(self):
        initialization = self.initialization_request()
        preconsent = replace(
            initialization,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        disclosure = self.plugin.form_initialization_disclosure(
            preconsent,
            peer_id="plugin",
        )
        evidence = OwnerConsentEvidence.for_initialization(
            initialization,
            self.init_asset,
            disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
        )
        self.assertTrue(self.core.close().complete)
        rotated_policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-B",
            conversation_id="private-B",
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=rotated_policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=rotated_policy,
            health_init_runtime=self.init_runtime,
        )

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "initialization-configuration-mismatch",
        ):
            self.plugin.form_initialization_disclosure(
                preconsent,
                peer_id="plugin",
            )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    evidence.to_message_body(),
                    sender_id="owner-B",
                    conversation_id="private-B",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        prepared = self.plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )

        self.assertEqual(
            (prepared.status, prepared.reason_code),
            ("unavailable", "initialization-configuration-mismatch"),
        )
        self.assertEqual(self.store.count_records(), 0)

        current = self.initialization_request(
            workflow_id="init-workflow-policy-B",
            admission_causal_id="delivery-policy-B",
            timezone="UTC",
        )
        current_disclosure = self.plugin.form_initialization_disclosure(
            replace(
                current,
                owner_consent=False,
                first_hop_route_consent=False,
            ),
            peer_id="plugin",
        )
        current_evidence = OwnerConsentEvidence.for_initialization(
            current,
            self.init_asset,
            current_disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    current_evidence.to_message_body(),
                    causal_id="delivery-policy-B",
                    sender_id="owner-B",
                    conversation_id="private-B",
                    message_id="wx-message-policy-B",
                    native_cursor="cursor-policy-B",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        current_prepared = self.plugin.prepare_initialization(
            current,
            peer_id="plugin",
        )

        self.assertEqual(current_prepared.status, "accepted")

    def test_disclosure_replay_requires_current_writer_and_live_authority(self):
        initialization = self.initialization_request()
        preconsent = replace(
            initialization,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        self.plugin.form_initialization_disclosure(
            preconsent,
            peer_id="plugin",
        )
        self.assertTrue(self.core.close().complete)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=InMemoryWriterFenceVault(),
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )
        self.assertEqual(
            self.plugin.probe().reason_code,
            "current-writer-holder-missing",
        )
        body = CountingBody("synthetic sensitive initialization body")
        unavailable_source = self.plugin.receive_weixin(
            self.message(body),
            peer_id="plugin",
        )
        self.assertEqual(
            (unavailable_source.status, unavailable_source.reason_code),
            ("unavailable", "current-writer-holder-missing"),
        )
        self.assertEqual(body.reads, 0)

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "current-writer-holder-missing",
        ):
            self.plugin.form_initialization_disclosure(
                preconsent,
                peer_id="plugin",
            )

    def test_plugin_and_core_admission_policy_divergence_fails_before_body_read(self):
        self.assertTrue(self.core.close().complete)
        core_policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-B",
            conversation_id="private-B",
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=core_policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )
        body = CountingBody("synthetic sensitive initialization body")

        probe = self.plugin.probe()
        admitted = self.plugin.receive_weixin(
            self.message(body),
            peer_id="plugin",
        )

        self.assertEqual(
            (probe.state.value, probe.reason_code),
            ("unavailable", "admission-policy-mismatch"),
        )
        self.assertEqual(
            (admitted.status, admitted.reason_code),
            ("unavailable", "admission-policy-mismatch"),
        )
        self.assertEqual(body.reads, 0)
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "initialization-configuration-mismatch",
        ):
            self.plugin.form_initialization_disclosure(
                replace(
                    self.initialization_request(),
                    owner_consent=False,
                    first_hop_route_consent=False,
                ),
                peer_id="plugin",
            )

    def test_unregistered_or_late_disclosure_cannot_authorize_owner_confirmation(self):
        initialization = self.initialization_request()
        preconsent = replace(
            initialization,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        detached_disclosure = HealthInitRuntime(
            self.init_asset,
            self.init_attestor,
        ).form_disclosure(preconsent)
        detached_evidence = OwnerConsentEvidence.for_initialization(
            initialization,
            self.init_asset,
            detached_disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(CountingBody(detached_evidence.to_message_body())),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        unregistered = self.plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )
        self.assertEqual(unregistered.status, "rejected")
        self.assertEqual(
            unregistered.reason_code,
            "health-init-disclosure-challenge-required",
        )

        late_initialization = self.initialization_request(
            workflow_id="init-workflow-late",
            admission_causal_id="delivery-late",
        )
        late_preconsent = replace(
            late_initialization,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        late_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=HealthInitRuntime(
                self.init_asset,
                self.init_attestor,
                clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
            ),
        )
        late_disclosure = late_plugin.form_initialization_disclosure(
            late_preconsent,
            peer_id="plugin",
        )
        late_evidence = OwnerConsentEvidence.for_initialization(
            late_initialization,
            self.init_asset,
            late_disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
        )
        self.assertEqual(
            late_plugin.receive_weixin(
                self.message(
                    CountingBody(late_evidence.to_message_body()),
                    causal_id="delivery-late",
                    message_id="wx-message-late",
                    native_cursor="cursor-late",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        late = late_plugin.prepare_initialization(
            late_initialization,
            peer_id="plugin",
        )
        self.assertEqual(late.status, "rejected")
        self.assertEqual(late.reason_code, "health-init-disclosure-order-invalid")
        self.assertEqual(self.store.count_records(), 0)

    def test_disclosure_must_precede_protocol_send_time_and_requires_it(self):
        initialization = self.initialization_request(
            workflow_id="init-workflow-protocol-late",
            admission_causal_id="delivery-protocol-late",
        )
        preconsent = replace(
            initialization,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=HealthInitRuntime(
                self.init_asset,
                self.init_attestor,
                clock=lambda: datetime(
                    2026,
                    8,
                    23,
                    1,
                    0,
                    0,
                    500_000,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        disclosure = plugin.form_initialization_disclosure(
            preconsent,
            peer_id="plugin",
        )
        evidence = OwnerConsentEvidence.for_initialization(
            initialization,
            self.init_asset,
            disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
        )
        admitted = plugin.receive_weixin(
            self.message(
                CountingBody(evidence.to_message_body()),
                causal_id="delivery-protocol-late",
                message_id="wx-message-protocol-late",
                native_cursor="cursor-protocol-late",
            ),
            peer_id="plugin",
        )

        self.assertEqual(admitted.status, "accepted")
        protocol_late = plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )
        self.assertEqual(protocol_late.status, "rejected")
        self.assertEqual(
            protocol_late.reason_code,
            "health-init-disclosure-order-invalid",
        )

        missing_initialization = self.initialization_request(
            workflow_id="init-workflow-protocol-missing",
            admission_causal_id="delivery-protocol-missing",
        )
        missing_preconsent = replace(
            missing_initialization,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        missing_disclosure = self.plugin.form_initialization_disclosure(
            missing_preconsent,
            peer_id="plugin",
        )
        missing_evidence = OwnerConsentEvidence.for_initialization(
            missing_initialization,
            self.init_asset,
            missing_disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
        )
        missing_admitted = self.plugin.receive_weixin(
            self.message(
                CountingBody(missing_evidence.to_message_body()),
                causal_id="delivery-protocol-missing",
                message_id="wx-message-protocol-missing",
                protocol_timestamp=None,
                native_cursor="cursor-protocol-missing",
            ),
            peer_id="plugin",
        )

        self.assertEqual(missing_admitted.status, "accepted")
        protocol_missing = self.plugin.prepare_initialization(
            missing_initialization,
            peer_id="plugin",
        )
        self.assertEqual(protocol_missing.status, "rejected")
        self.assertEqual(
            protocol_missing.reason_code,
            "health-init-disclosure-order-invalid",
        )

        equal_initialization = self.initialization_request(
            workflow_id="init-workflow-protocol-equal",
            admission_causal_id="delivery-protocol-equal",
        )
        equal_preconsent = replace(
            equal_initialization,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        equal_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=HealthInitRuntime(
                self.init_asset,
                self.init_attestor,
                clock=lambda: datetime(
                    2026,
                    8,
                    23,
                    1,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        equal_disclosure = equal_plugin.form_initialization_disclosure(
            equal_preconsent,
            peer_id="plugin",
        )
        equal_evidence = OwnerConsentEvidence.for_initialization(
            equal_initialization,
            self.init_asset,
            equal_disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
        )
        self.assertEqual(
            equal_plugin.receive_weixin(
                self.message(
                    CountingBody(equal_evidence.to_message_body()),
                    causal_id="delivery-protocol-equal",
                    message_id="wx-message-protocol-equal",
                    native_cursor="cursor-protocol-equal",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        protocol_equal = equal_plugin.prepare_initialization(
            equal_initialization,
            peer_id="plugin",
        )
        self.assertEqual(protocol_equal.status, "rejected")
        self.assertEqual(
            protocol_equal.reason_code,
            "health-init-disclosure-order-invalid",
        )
        self.assertEqual(self.store.count_records(), 0)

    def test_prepare_replay_after_runtime_restart_reuses_the_durable_exact_proof(self):
        initialization = self.initialization_request()
        self.plugin.receive_weixin(
            self.message(self.consent_body(initialization)),
            peer_id="plugin",
        )
        first = self.plugin.prepare_initialization(initialization, peer_id="plugin")
        self.assertEqual(first.status, "accepted")

        self.assertTrue(self.core.close().complete)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )

        def must_not_execute(asset, request):
            del asset, request
            raise AssertionError("durable replay reran health-init")

        restarted_runtime = HealthInitRuntime(
            self.init_asset,
            self.init_attestor,
            executor=must_not_execute,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=restarted_runtime,
        )

        replay = self.plugin.prepare_initialization(initialization, peer_id="plugin")
        self.assertEqual(replay.to_wire(), first.to_wire())
        conflict = self.plugin.prepare_initialization(
            self.initialization_request(timezone="UTC"),
            peer_id="plugin",
        )
        self.assertEqual(conflict.status, "rejected")
        self.assertEqual(conflict.reason_code, "health-init workflow conflict")

        self.assertEqual(
            self.plugin.commit_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.finalize_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertIsNone(
            self.plugin.source_envelope("delivery-1", peer_id="plugin").body
        )
        replay_after_release = self.plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )
        self.assertEqual(replay_after_release.to_wire(), first.to_wire())

    def test_wrong_asset_forged_proof_and_model_self_report_cannot_prepare(self):
        initialization = self.initialization_request()
        self.plugin.receive_weixin(
            self.message(self.consent_body(initialization)),
            peer_id="plugin",
        )
        wrong_asset = HealthInitAsset(
            version="9.9.9",
            asset_digest="sha256:" + ("9" * 64),
            disclosure_version="unapproved-disclosure",
        )
        wrong_proof = HealthInitRuntime(
            wrong_asset,
            self.init_attestor,
        ).form_disclosure(
            replace(
                initialization,
                owner_consent=False,
                first_hop_route_consent=False,
            )
        ).skill_proof
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

        valid_proof = self.init_runtime.form_disclosure(
            replace(
                initialization,
                owner_consent=False,
                first_hop_route_consent=False,
            )
        ).skill_proof
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
        initialization = self.initialization_request()
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

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "health-init-execution-failed",
        ):
            failed_plugin.form_initialization_disclosure(
                replace(
                    initialization,
                    owner_consent=False,
                    first_hop_route_consent=False,
                ),
                peer_id="plugin",
            )
        self.assertEqual(self.store.count_records(), 0)
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "uninitialized",
        )

    def test_caller_booleans_without_owner_message_consent_evidence_cannot_prepare(self):
        initialization = self.initialization_request(
            owner_consent=True,
            first_hop_route_consent=True,
        )
        self.plugin.receive_weixin(
            self.message(CountingBody("start synthetic initialization")),
            peer_id="plugin",
        )

        response = self.plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )

        self.assertEqual(response.status, "rejected")
        self.assertEqual(response.reason_code, "owner-consent-evidence-required")
        self.assertEqual(self.store.count_records(), 0)

        direct = self.plugin.invoke(
            CommandEnvelope(
                peer="plugin",
                action="initialization.prepare",
                source="health_weixin",
                causal_id="direct-prepare-without-owner-evidence",
                generation=1,
                scope=("initialization:prepare",),
                payload=InitializationPreparePayload(
                    initialization,
                    self.init_runtime.form_disclosure(
                        replace(
                            initialization,
                            owner_consent=False,
                            first_hop_route_consent=False,
                        )
                    ).skill_proof,
                ),
            ),
            peer_id="plugin",
        )
        self.assertEqual(direct.status, "rejected")
        self.assertEqual(direct.reason_code, "owner-consent-evidence-required")
        self.assertEqual(self.store.count_records(), 0)

    def test_owner_confirmation_without_prior_attested_disclosure_cannot_prepare(self):
        initialization = self.initialization_request()
        unattested_confirmation = json.dumps(
            {
                "schema": "health-init-owner-consent-v1",
                "workflow_id": initialization.workflow_id,
                "admission_causal_id": initialization.admission_causal_id,
                "initialization_digest": initialization.digest,
                "disclosure_version": self.init_asset.disclosure_version,
                "disclosed_topics": [
                    "health-data-scope",
                    "daily-review",
                    "health-task-automation",
                    "proactive-support",
                    "first-hop-model-route",
                    "support-contact",
                    "owner-data-rights",
                    "unknown-effects-not-retried",
                ],
                "owner_confirmed": True,
                "first_hop_route_confirmed": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self.plugin.receive_weixin(
            self.message(CountingBody(unattested_confirmation)),
            peer_id="plugin",
        )

        response = self.plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )

        self.assertEqual(response.status, "rejected")
        self.assertEqual(response.reason_code, "owner-consent-evidence-required")
        self.assertEqual(self.store.count_records(), 0)

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

        proof = self.init_runtime.form_disclosure(
            replace(
                self.initialization_request(),
                owner_consent=False,
                first_hop_route_consent=False,
            )
        ).skill_proof
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

    def test_initialization_without_preconfigured_support_contact_is_allowed(self):
        initialization = self.initialization_request(support_contact=None)
        admitted = self.plugin.receive_weixin(
            self.message(self.consent_body(initialization)),
            peer_id="plugin",
        )
        self.assertEqual(admitted.status, "accepted")
        self.assertEqual(
            self.plugin.prepare_initialization(initialization, peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(self.plugin.commit_initialization(peer_id="plugin").status, "accepted")
        self.assertEqual(self.plugin.finalize_initialization(peer_id="plugin").status, "accepted")

        status = self.plugin.initialization_status(peer_id="plugin")
        self.assertTrue(status.enabled)
        self.assertIsNone(status.support_contact)
        self.assertEqual(status.support_contact_approval_state, "not-configured")
        self.assertTrue(self.plugin.health_writes_allowed())
        self.assertFalse(self.plugin.outbound_effects_allowed())

    def test_divergent_plugin_cannot_claim_core_effect_execution(self):
        self.admit_and_prepare()
        self.assertEqual(
            self.plugin.commit_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.finalize_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertTrue(self.core.close().complete)
        execution_vault = InMemoryExecutionCapabilityVault()
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            execution_capability_vault=execution_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )
        issued = self.plugin.invoke(
            CommandEnvelope(
                peer="plugin",
                action="effect.request",
                source="health_weixin",
                causal_id="ticket111-model-effect",
                generation=2,
                scope=("effect:request",),
                payload={
                    "effect_kind": "model-work",
                    "request_digest": "sha256:ticket111-model-effect",
                },
            ),
            peer_id="plugin",
        )
        self.assertEqual(issued.status, "accepted")
        divergent = HealthPlugin(
            self.core,
            admission_policy=AdmissionPolicy(
                partner_id="partner-A",
                owner_sender_id="owner-B",
                conversation_id="private-B",
            ),
            health_init_runtime=self.init_runtime,
        )

        self.assertIsNone(divergent.claim_effect_execution(issued.meta.intent))
        self.assertIsNotNone(self.plugin.claim_effect_execution(issued.meta.intent))

    def test_core_configuration_drift_blocks_effect_intent_issue(self):
        self.admit_and_prepare()
        self.assertEqual(
            self.plugin.commit_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.finalize_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertTrue(self.core.close().complete)
        drifted_policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-B",
            conversation_id="private-B",
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            execution_capability_vault=InMemoryExecutionCapabilityVault(),
            admission_policy=drifted_policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=drifted_policy,
            health_init_runtime=self.init_runtime,
        )
        self.assertFalse(self.plugin.health_writes_allowed())
        self.assertFalse(self.plugin.model_effects_allowed())

        issued = self.plugin.invoke(
            CommandEnvelope(
                peer="plugin",
                action="effect.request",
                source="health_weixin",
                causal_id="drifted-ticket111-model-effect",
                generation=2,
                scope=("effect:request",),
                payload={
                    "effect_kind": "model-work",
                    "request_digest": "sha256:drifted-ticket111-model-effect",
                },
            ),
            peer_id="plugin",
        )

        self.assertEqual(
            (issued.status, issued.reason_code),
            ("unavailable", "initialization-configuration-mismatch"),
        )
        self.assertEqual(self.store.count_effects(), 0)

    def test_core_configuration_drift_blocks_existing_effect_claim(self):
        self.admit_and_prepare()
        self.assertEqual(
            self.plugin.commit_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.finalize_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertTrue(self.core.close().complete)
        execution_vault = InMemoryExecutionCapabilityVault()
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            execution_capability_vault=execution_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )
        issued = self.plugin.invoke(
            CommandEnvelope(
                peer="plugin",
                action="effect.request",
                source="health_weixin",
                causal_id="pre-drift-ticket111-model-effect",
                generation=2,
                scope=("effect:request",),
                payload={
                    "effect_kind": "model-work",
                    "request_digest": "sha256:pre-drift-ticket111-model-effect",
                },
            ),
            peer_id="plugin",
        )
        self.assertEqual(issued.status, "accepted")
        self.assertTrue(self.core.close().complete)
        drifted_policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-B",
            conversation_id="private-B",
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            execution_capability_vault=execution_vault,
            admission_policy=drifted_policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=drifted_policy,
            health_init_runtime=self.init_runtime,
        )

        self.assertFalse(self.plugin.health_writes_allowed())
        self.assertFalse(self.plugin.model_effects_allowed())
        self.assertIsNone(self.plugin.claim_effect_execution(issued.meta.intent))

    def test_cursor_is_released_only_after_finalize_and_unknown_does_not_repeat_business(self):
        initialization = self.initialization_request()
        self.plugin.receive_weixin(
            self.message(self.consent_body(initialization)),
            peer_id="plugin",
        )
        initial_receipt = self.plugin.source_receipt("delivery-1", peer_id="plugin")
        self.assertEqual(initial_receipt.managed_cursor_state, "held")
        self.assertEqual(initial_receipt.native_cursor_state, "not-ready")
        self.assertIsNone(self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"))

        self.plugin.prepare_initialization(initialization, peer_id="plugin")
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
        self.assertEqual(
            self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"),
            directive,
        )

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
        contradictory = self.plugin.record_native_cursor_result(
            directive,
            status="advanced",
            peer_id="plugin",
        )
        self.assertEqual(contradictory.status, "rejected")
        self.assertEqual(contradictory.reason_code, "native-cursor-result-terminal")
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

    def test_ambiguous_remote_commit_can_close_read_only_during_config_drift(self):
        self.admit_and_prepare()
        self.head.set_failure(FailureMode.UNKNOWN_AFTER_ADVANCE, operation="advance")
        self.assertEqual(
            self.plugin.commit_initialization(peer_id="plugin").status,
            "unknown",
        )
        self.head.clear_failure()

        self.assertTrue(self.core.close().complete)
        wrong_asset = HealthInitAsset(
            version="2.0.0",
            asset_digest="sha256:" + ("2" * 64),
            disclosure_version="health-init-disclosure-v2",
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=wrong_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
        )

        recovered = self.plugin.commit_initialization(peer_id="plugin")
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "committed",
        )
        denied_finalize = self.plugin.finalize_initialization(peer_id="plugin")
        self.assertEqual(denied_finalize.status, "unavailable")
        self.assertEqual(
            denied_finalize.reason_code,
            "initialization-configuration-mismatch",
        )

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
        self.assertEqual(self.plugin.finalize_initialization(peer_id="plugin").status, "accepted")
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

    def test_enabled_projection_requires_intact_local_authority_chain(self):
        self.admit_and_prepare()
        self.plugin.commit_initialization(peer_id="plugin")
        self.plugin.finalize_initialization(peer_id="plugin")
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)

        with self.store.transaction() as connection:
            connection.execute(
                "DELETE FROM health_records WHERE record_id = ?",
                ("owner-initialization",),
            )

        status = self.plugin.initialization_status(peer_id="plugin")
        self.assertEqual(status.phase, "cannot-confirm")
        self.assertFalse(status.enabled)
        self.assertFalse(self.plugin.health_writes_allowed())

    def test_maximum_workflow_identifier_uses_bounded_derived_command_ids(self):
        initialization = self.initialization_request(workflow_id="w" * 256)
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(self.consent_body(initialization)),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        prepared = self.plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )

        self.assertEqual(prepared.status, "accepted")
        self.assertEqual(self.plugin.commit_initialization(peer_id="plugin").status, "accepted")
        self.assertEqual(self.plugin.finalize_initialization(peer_id="plugin").status, "accepted")
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)

    def test_maximum_source_identifier_uses_bounded_cursor_result_id(self):
        source_causal_id = "s" * 256
        initialization = self.initialization_request(
            admission_causal_id=source_causal_id,
        )
        admitted = self.plugin.receive_weixin(
            self.message(
                self.consent_body(initialization),
                causal_id=source_causal_id,
            ),
            peer_id="plugin",
        )
        self.assertEqual(admitted.status, "accepted")
        self.assertEqual(
            self.plugin.prepare_initialization(
                initialization,
                peer_id="plugin",
            ).status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.commit_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.finalize_initialization(peer_id="plugin").status,
            "accepted",
        )
        directive = self.plugin.native_cursor_directive(
            source_causal_id,
            peer_id="plugin",
        )
        self.assertIsNotNone(directive)

        result = self.plugin.record_native_cursor_result(
            directive,
            status="advanced",
            peer_id="plugin",
        )

        self.assertEqual(result.status, "accepted")
        receipt = self.plugin.source_receipt(source_causal_id, peer_id="plugin")
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.native_cursor_state, "advanced")

    def test_ticket110_integrity_manifest_migrates_only_with_empty_ticket111_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "ticket110-upgrade.sqlite")
            store = EncryptedStateStore(database, self.key_provider)
            authority = self.head.read().head.as_authority()
            store.seed_finalized_authority(authority)
            with store.transaction() as connection:
                legacy_fingerprint = store._integrity_fingerprint(
                    include_ticket111=False
                )
                nonce, ciphertext = store._seal(
                    "integrity-manifest",
                    {"fingerprint": legacy_fingerprint},
                )
                connection.execute(
                    "UPDATE integrity_manifest_v1 SET nonce = ?, ciphertext = ? "
                    "WHERE slot = 1",
                    (nonce, ciphertext),
                )
            store.close()

            reopened = EncryptedStateStore(database, self.key_provider)
            try:
                self.assertTrue(reopened.verify_integrity(authority))
            finally:
                reopened.close()

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

    def test_commit_and_finalize_revalidate_current_admission_and_health_init_asset(self):
        self.admit_and_prepare()
        wrong_policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="different-owner",
            conversation_id="private-A",
        )
        wrong_asset = HealthInitAsset(
            version="2.0.0",
            asset_digest="sha256:" + ("2" * 64),
            disclosure_version="health-init-disclosure-v2",
        )

        def restart(*, policy, asset):
            self.assertTrue(self.core.close().complete)
            self.core = HealthCore(
                self.store,
                self.head,
                writer_fence_vault=self.writer_vault,
                admission_policy=policy,
                health_init_verifier=self.init_attestor,
                health_init_asset=asset,
            )
            self.plugin = HealthPlugin(
                self.core,
                admission_policy=policy,
                health_init_runtime=self.init_runtime,
            )

        restart(policy=wrong_policy, asset=self.init_asset)
        denied_policy_commit = self.plugin.commit_initialization(peer_id="plugin")
        self.assertEqual(denied_policy_commit.status, "unavailable")
        self.assertEqual(
            denied_policy_commit.reason_code,
            "initialization-configuration-mismatch",
        )
        self.assertEqual(self.head.read().head.generation, 1)

        restart(policy=self.policy, asset=wrong_asset)
        denied_asset_commit = self.plugin.commit_initialization(peer_id="plugin")
        self.assertEqual(denied_asset_commit.status, "unavailable")
        self.assertEqual(
            denied_asset_commit.reason_code,
            "initialization-configuration-mismatch",
        )
        self.assertEqual(self.head.read().head.generation, 1)

        restart(policy=self.policy, asset=self.init_asset)
        self.assertEqual(self.plugin.commit_initialization(peer_id="plugin").status, "accepted")
        self.assertEqual(self.head.read().head.generation, 2)

        restart(policy=wrong_policy, asset=self.init_asset)
        denied_policy_finalize = self.plugin.finalize_initialization(peer_id="plugin")
        self.assertEqual(denied_policy_finalize.status, "unavailable")
        self.assertEqual(
            denied_policy_finalize.reason_code,
            "initialization-configuration-mismatch",
        )
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "committed",
        )

        restart(policy=self.policy, asset=wrong_asset)
        denied_asset_finalize = self.plugin.finalize_initialization(peer_id="plugin")
        self.assertEqual(denied_asset_finalize.status, "unavailable")
        self.assertEqual(
            denied_asset_finalize.reason_code,
            "initialization-configuration-mismatch",
        )

        restart(policy=self.policy, asset=self.init_asset)
        self.assertEqual(self.plugin.finalize_initialization(peer_id="plugin").status, "accepted")
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)

        restart(policy=self.policy, asset=wrong_asset)
        self.assertTrue(self.plugin.initialization_status(peer_id="plugin").enabled)
        self.assertFalse(self.plugin.health_writes_allowed())
        self.assertFalse(self.plugin.model_effects_allowed())

        restart(policy=self.policy, asset=self.init_asset)
        self.assertTrue(self.plugin.health_writes_allowed())

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
        self.assertEqual(
            self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"),
            directive,
        )
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
        self.assertEqual(
            self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"),
            directive,
        )
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
        self.assertEqual(
            self.plugin.native_cursor_directive("delivery-1", peer_id="plugin"),
            directive,
        )
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

    def test_conflicting_initialization_candidates_wait_for_explicit_owner_resolution(self):
        requests = (
            self.initialization_request(),
            self.initialization_request(
                workflow_id="init-workflow-2",
                admission_causal_id="delivery-2",
                timezone="UTC",
            ),
        )
        self.plugin.receive_weixin(
            self.message(self.consent_body(requests[0])),
            peer_id="plugin",
        )
        self.plugin.receive_weixin(
            self.message(
                self.consent_body(requests[1]),
                causal_id="delivery-2",
                message_id="wx-message-2",
                native_cursor="cursor-2",
            ),
            peer_id="plugin",
        )
        barrier = threading.Barrier(2)
        responses = []

        def prepare(request):
            barrier.wait(timeout=2)
            responses.append(
                self.plugin.prepare_initialization(request, peer_id="plugin")
            )

        workers = [
            threading.Thread(target=prepare, args=(request,))
            for request in requests
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())

        self.assertEqual([response.status for response in responses], ["rejected"] * 2)
        self.assertEqual(
            {response.reason_code for response in responses},
            {"owner-resolution-required"},
        )
        self.assertEqual(self.store.count_records(), 0)
        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "uninitialized",
        )

        resolution = self.initialization_request(
            workflow_id="init-workflow-3",
            admission_causal_id="delivery-3",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    self.consent_body(
                        resolution,
                        resolved_source_causal_ids=("delivery-1", "delivery-2"),
                    ),
                    causal_id="delivery-3",
                    message_id="wx-message-3",
                    native_cursor="cursor-3",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.prepare_initialization(resolution, peer_id="plugin").status,
            "accepted",
        )
        late_body = CountingBody("late initialization candidate")
        late = self.plugin.receive_weixin(
            self.message(
                late_body,
                causal_id="delivery-4",
                message_id="wx-message-4",
                native_cursor="cursor-4",
            ),
            peer_id="plugin",
        )
        self.assertEqual(
            (late.status, late.reason_code),
            ("rejected", "initialization already exists"),
        )
        self.assertEqual(late_body.reads, 0)
        self.assertIsNone(self.plugin.source_receipt("delivery-4", peer_id="plugin"))
        self.plugin.commit_initialization(peer_id="plugin")
        self.plugin.finalize_initialization(peer_id="plugin")
        directives = {}
        for source_causal_id in ("delivery-1", "delivery-2", "delivery-3"):
            with self.subTest(source_causal_id=source_causal_id):
                receipt = self.plugin.source_receipt(source_causal_id, peer_id="plugin")
                self.assertEqual(receipt.managed_cursor_state, "committed")
                self.assertEqual(receipt.native_cursor_state, "ready")
                self.assertIsNone(receipt.envelope.body)
                directive = self.plugin.native_cursor_directive(
                    source_causal_id,
                    peer_id="plugin",
                )
                self.assertIsNotNone(directive)
                directives[source_causal_id] = directive
        resolved_cursor = self.plugin.record_native_cursor_result(
            directives["delivery-2"],
            status="advanced",
            peer_id="plugin",
        )
        self.assertEqual(resolved_cursor.status, "accepted")
        self.assertEqual(
            self.plugin.source_receipt(
                "delivery-2",
                peer_id="plugin",
            ).native_cursor_state,
            "advanced",
        )

    def test_conflict_resolution_cannot_predeclare_a_future_candidate(self):
        earlier = self.initialization_request()
        later = self.initialization_request(
            workflow_id="init-workflow-2",
            admission_causal_id="delivery-2",
            timezone="UTC",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    self.consent_body(
                        earlier,
                        resolved_source_causal_ids=("delivery-2",),
                    )
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    self.consent_body(later),
                    causal_id="delivery-2",
                    message_id="wx-message-2",
                    native_cursor="cursor-2",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        response = self.plugin.prepare_initialization(earlier, peer_id="plugin")

        self.assertEqual(response.status, "rejected")
        self.assertEqual(response.reason_code, "owner-resolution-required")
        self.assertEqual(self.store.count_records(), 0)
        for causal_id in ("delivery-1", "delivery-2"):
            self.assertEqual(
                self.plugin.source_receipt(causal_id, peer_id="plugin").managed_cursor_state,
                "held",
            )

    def test_source_arrival_order_is_covered_by_the_integrity_manifest(self):
        earlier = self.initialization_request()
        later = self.initialization_request(
            workflow_id="init-workflow-2",
            admission_causal_id="delivery-2",
            timezone="UTC",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    self.consent_body(
                        earlier,
                        resolved_source_causal_ids=("delivery-2",),
                    )
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    self.consent_body(later),
                    causal_id="delivery-2",
                    message_id="wx-message-2",
                    native_cursor="cursor-2",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        with self.store.transaction() as connection:
            rows = connection.execute(
                "SELECT causal_id, rowid FROM source_envelopes_v1 ORDER BY rowid"
            ).fetchall()
            self.assertEqual(
                tuple(row[0] for row in rows),
                ("delivery-1", "delivery-2"),
            )
            first_rowid = rows[0][1]
            second_rowid = rows[1][1]
            temporary_rowid = second_rowid + 10_000
            connection.execute(
                "UPDATE source_envelopes_v1 SET rowid = ? WHERE causal_id = ?",
                (temporary_rowid, "delivery-1"),
            )
            connection.execute(
                "UPDATE source_envelopes_v1 SET rowid = ? WHERE causal_id = ?",
                (first_rowid, "delivery-2"),
            )
            connection.execute(
                "UPDATE source_envelopes_v1 SET rowid = ? WHERE causal_id = ?",
                (second_rowid, "delivery-1"),
            )

        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "cannot-confirm",
        )
        self.assertNotEqual(
            self.plugin.prepare_initialization(earlier, peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(self.store.count_records(), 0)

    def test_asset_rotation_does_not_hide_older_conflicting_candidates(self):
        first = self.initialization_request()
        conflicting = self.initialization_request(
            workflow_id="init-workflow-2",
            admission_causal_id="delivery-2",
            timezone="UTC",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(self.consent_body(first)),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    self.consent_body(conflicting),
                    causal_id="delivery-2",
                    message_id="wx-message-2",
                    native_cursor="cursor-2",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        self.assertTrue(self.core.close().complete)
        rotated_asset = HealthInitAsset(
            version="2.0.0",
            asset_digest="sha256:" + ("2" * 64),
            disclosure_version="health-init-disclosure-v2",
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=rotated_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=HealthInitRuntime(
                rotated_asset,
                self.init_attestor,
                clock=lambda: datetime(
                    2026,
                    8,
                    23,
                    0,
                    59,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "initialization-configuration-mismatch",
        ):
            self.plugin.form_initialization_disclosure(
                replace(
                    first,
                    owner_consent=False,
                    first_hop_route_consent=False,
                ),
                peer_id="plugin",
            )
        current = self.initialization_request(
            workflow_id="init-workflow-3",
            admission_causal_id="delivery-3",
        )
        current_preconsent = replace(
            current,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        current_disclosure = self.plugin.form_initialization_disclosure(
            current_preconsent,
            peer_id="plugin",
        )
        current_body = CountingBody(
            OwnerConsentEvidence.for_initialization(
                current,
                rotated_asset,
                current_disclosure,
                owner_confirmed=True,
                first_hop_route_confirmed=True,
            ).to_message_body()
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    current_body,
                    causal_id="delivery-3",
                    message_id="wx-message-3",
                    native_cursor="cursor-3",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        unresolved = self.plugin.prepare_initialization(current, peer_id="plugin")

        self.assertEqual(unresolved.status, "rejected")
        self.assertEqual(unresolved.reason_code, "owner-resolution-required")
        self.assertEqual(self.store.count_records(), 0)

    def test_conflict_queue_reserves_one_transportable_resolution_source(self):
        prior_ids = tuple(f"delivery-{index}" for index in range(1, 7))
        for index, causal_id in enumerate(prior_ids, start=1):
            candidate = self.initialization_request(
                workflow_id=f"init-workflow-{index}",
                admission_causal_id=causal_id,
                timezone="UTC",
            )
            admitted = self.plugin.receive_weixin(
                self.message(
                    self.consent_body(candidate),
                    causal_id=causal_id,
                    message_id=f"wx-message-{index}",
                    native_cursor=f"cursor-{index}",
                ),
                peer_id="plugin",
            )
            self.assertEqual(admitted.status, "accepted")

        overflow = self.initialization_request(
            workflow_id="init-workflow-overflow",
            admission_causal_id="delivery-overflow",
        )
        overflow_body = self.consent_body(overflow)
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "too many resolved source causal identifiers",
        ):
            OwnerConsentEvidence.for_initialization(
                overflow,
                self.init_asset,
                self.plugin.form_initialization_disclosure(
                    replace(
                        overflow,
                        owner_consent=False,
                        first_hop_route_consent=False,
                    ),
                    peer_id="plugin",
                ),
                owner_confirmed=True,
                first_hop_route_confirmed=True,
                resolved_source_causal_ids=tuple(
                    f"unbounded-{index}" for index in range(7)
                ),
            )
        rejected = self.plugin.receive_weixin(
            self.message(
                overflow_body,
                causal_id="delivery-overflow",
                message_id="wx-message-overflow",
                native_cursor="cursor-overflow",
            ),
            peer_id="plugin",
        )
        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-resolution-required"),
        )
        self.assertIsNone(
            self.plugin.source_receipt("delivery-overflow", peer_id="plugin")
        )

        resolution = self.initialization_request(
            workflow_id="init-workflow-resolution",
            admission_causal_id="delivery-resolution",
        )
        resolution_body = self.consent_body(
            resolution,
            resolved_source_causal_ids=prior_ids,
        )
        self.assertLessEqual(
            len(resolution_body.read().encode("utf-8")),
            16_384,
        )
        accepted = self.plugin.receive_weixin(
            self.message(
                resolution_body,
                causal_id="delivery-resolution",
                message_id="wx-message-resolution",
                native_cursor="cursor-resolution",
            ),
            peer_id="plugin",
        )
        self.assertEqual(accepted.status, "accepted")
        self.assertEqual(
            self.plugin.prepare_initialization(
                resolution,
                peer_id="plugin",
            ).status,
            "accepted",
        )

    def test_disclosure_rejects_configuration_without_resolution_capacity(self):
        oversized_after_json_escaping = self.initialization_request(
            workflow_id="\x00" * 256,
            admission_causal_id="\x01" * 256,
            first_hop_route="\x02" * 256,
            support_contact=SupportContactBoundary(
                contact_ref="\x03" * 256,
                method="weixin",
                purpose="emergency-support",
            ),
        )

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "initialization-resolution-capacity-exceeded",
        ):
            self.plugin.form_initialization_disclosure(
                replace(
                    oversized_after_json_escaping,
                    owner_consent=False,
                    first_hop_route_consent=False,
                ),
                peer_id="plugin",
            )

        self.assertEqual(
            self.plugin.initialization_status(peer_id="plugin").phase,
            "uninitialized",
        )

    def test_stale_reserved_resolution_slot_is_replaced_after_configuration_rotation(self):
        prior_ids = tuple(f"delivery-{index}" for index in range(1, 7))
        for index, causal_id in enumerate(prior_ids, start=1):
            candidate = self.initialization_request(
                workflow_id=f"init-workflow-{index}",
                admission_causal_id=causal_id,
                timezone="UTC",
            )
            self.assertEqual(
                self.plugin.receive_weixin(
                    self.message(
                        self.consent_body(candidate),
                        causal_id=causal_id,
                        message_id=f"wx-message-{index}",
                        native_cursor=f"cursor-{index}",
                    ),
                    peer_id="plugin",
                ).status,
                "accepted",
            )
        stale_resolution = self.initialization_request(
            workflow_id="init-workflow-stale-resolution",
            admission_causal_id="delivery-stale-resolution",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    self.consent_body(
                        stale_resolution,
                        resolved_source_causal_ids=prior_ids,
                    ),
                    causal_id="delivery-stale-resolution",
                    message_id="wx-message-stale-resolution",
                    native_cursor="cursor-stale-resolution",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        self.assertTrue(self.core.close().complete)
        rotated_policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-B",
            conversation_id="private-B",
        )
        rotated_attestor = HealthInitAttestor(
            b"b" * 32,
            key_id="rotated-health-init-attestor",
        )
        rotated_asset = HealthInitAsset(
            version="2.0.0",
            asset_digest="sha256:" + ("2" * 64),
            disclosure_version="health-init-disclosure-v2",
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=rotated_policy,
            health_init_verifier=rotated_attestor,
            health_init_asset=rotated_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=rotated_policy,
            health_init_runtime=HealthInitRuntime(
                rotated_asset,
                rotated_attestor,
                clock=lambda: datetime(
                    2026,
                    8,
                    23,
                    0,
                    59,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        divergent_replacement = self.initialization_request(
            workflow_id="init-workflow-divergent-replacement",
            admission_causal_id="delivery-divergent-replacement",
            timezone="Europe/London",
        )
        divergent_preconsent = replace(
            divergent_replacement,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        divergent_disclosure = self.plugin.form_initialization_disclosure(
            divergent_preconsent,
            peer_id="plugin",
        )
        divergent_body = OwnerConsentEvidence.for_initialization(
            divergent_replacement,
            rotated_asset,
            divergent_disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
            resolved_source_causal_ids=prior_ids,
        ).to_message_body()

        rejected_divergence = self.plugin.receive_weixin(
            self.message(
                divergent_body,
                causal_id="delivery-divergent-replacement",
                sender_id="owner-B",
                conversation_id="private-B",
                message_id="wx-message-divergent-replacement",
                native_cursor="cursor-divergent-replacement",
            ),
            peer_id="plugin",
        )

        self.assertEqual(rejected_divergence.status, "rejected")
        self.assertEqual(
            rejected_divergence.reason_code,
            "owner-resolution-required",
        )
        self.assertEqual(
            self.plugin.source_receipt(
                "delivery-stale-resolution",
                peer_id="plugin",
            ).managed_cursor_state,
            "held",
        )
        replacement = self.initialization_request(
            workflow_id="init-workflow-replacement-resolution",
            admission_causal_id="delivery-replacement-resolution",
        )
        replacement_preconsent = replace(
            replacement,
            owner_consent=False,
            first_hop_route_consent=False,
        )
        replacement_disclosure = self.plugin.form_initialization_disclosure(
            replacement_preconsent,
            peer_id="plugin",
        )
        replacement_body = CountingBody(
            OwnerConsentEvidence.for_initialization(
                replacement,
                rotated_asset,
                replacement_disclosure,
                owner_confirmed=True,
                first_hop_route_confirmed=True,
                resolved_source_causal_ids=prior_ids,
            ).to_message_body()
        )

        admitted = self.plugin.receive_weixin(
            self.message(
                replacement_body,
                causal_id="delivery-replacement-resolution",
                sender_id="owner-B",
                conversation_id="private-B",
                message_id="wx-message-replacement-resolution",
                native_cursor="cursor-replacement-resolution",
            ),
            peer_id="plugin",
        )

        self.assertEqual(admitted.status, "accepted")
        stale_receipt = self.plugin.source_receipt(
            "delivery-stale-resolution",
            peer_id="plugin",
        )
        self.assertEqual(stale_receipt.managed_cursor_state, "superseded")
        self.assertIsNotNone(stale_receipt.envelope.body)
        self.assertEqual(len(self.store.held_source_receipts()), 8)

        self.assertTrue(self.core.close().complete)
        second_rotated_policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-C",
            conversation_id="private-C",
        )
        second_rotated_attestor = HealthInitAttestor(
            b"c" * 32,
            key_id="second-rotated-health-init-attestor",
        )
        second_rotated_asset = HealthInitAsset(
            version="3.0.0",
            asset_digest="sha256:" + ("3" * 64),
            disclosure_version="health-init-disclosure-v3",
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=second_rotated_policy,
            health_init_verifier=second_rotated_attestor,
            health_init_asset=second_rotated_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=second_rotated_policy,
            health_init_runtime=HealthInitRuntime(
                second_rotated_asset,
                second_rotated_attestor,
                clock=lambda: datetime(
                    2026,
                    8,
                    23,
                    0,
                    59,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        second_replacement = self.initialization_request(
            workflow_id="init-workflow-second-replacement",
            admission_causal_id="delivery-second-replacement",
        )
        second_disclosure = self.plugin.form_initialization_disclosure(
            replace(
                second_replacement,
                owner_consent=False,
                first_hop_route_consent=False,
            ),
            peer_id="plugin",
        )
        second_body = OwnerConsentEvidence.for_initialization(
            second_replacement,
            second_rotated_asset,
            second_disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
            resolved_source_causal_ids=prior_ids,
        ).to_message_body()

        second_rotation = self.plugin.receive_weixin(
            self.message(
                second_body,
                causal_id="delivery-second-replacement",
                sender_id="owner-C",
                conversation_id="private-C",
                message_id="wx-message-second-replacement",
                native_cursor="cursor-second-replacement",
            ),
            peer_id="plugin",
        )

        self.assertEqual(
            (second_rotation.status, second_rotation.reason_code),
            ("unavailable", "initialization-source-capacity-reached"),
        )
        self.assertIsNone(
            self.plugin.source_receipt(
                "delivery-second-replacement",
                peer_id="plugin",
            )
        )
        self.assertEqual(len(self.store.held_source_receipts()), 8)

        self.assertTrue(self.core.close().complete)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=rotated_policy,
            health_init_verifier=rotated_attestor,
            health_init_asset=rotated_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=rotated_policy,
            health_init_runtime=HealthInitRuntime(
                rotated_asset,
                rotated_attestor,
                clock=lambda: datetime(
                    2026,
                    8,
                    23,
                    0,
                    59,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        self.assertEqual(
            self.plugin.prepare_initialization(
                replacement,
                peer_id="plugin",
            ).status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.commit_initialization(peer_id="plugin").status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.finalize_initialization(peer_id="plugin").status,
            "accepted",
        )
        settled_stale = self.plugin.source_receipt(
            "delivery-stale-resolution",
            peer_id="plugin",
        )
        self.assertEqual(settled_stale.managed_cursor_state, "committed")
        self.assertEqual(settled_stale.native_cursor_state, "ready")
        self.assertIsNone(settled_stale.envelope.body)

    def test_attestor_rotation_does_not_hide_older_conflicting_candidates(self):
        first = self.initialization_request()
        conflicting = self.initialization_request(
            workflow_id="init-workflow-2",
            admission_causal_id="delivery-2",
            timezone="UTC",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(self.consent_body(first)),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    self.consent_body(conflicting),
                    causal_id="delivery-2",
                    message_id="wx-message-2",
                    native_cursor="cursor-2",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        self.assertTrue(self.core.close().complete)
        rotated_attestor = HealthInitAttestor(
            b"b" * 32,
            key_id="rotated-health-init-attestor",
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=rotated_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=HealthInitRuntime(
                self.init_asset,
                rotated_attestor,
                clock=lambda: datetime(
                    2026,
                    8,
                    23,
                    0,
                    59,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        with self.assertRaisesRegex(
            AuthorityValidationError,
            "initialization-configuration-mismatch",
        ):
            self.plugin.form_initialization_disclosure(
                replace(
                    first,
                    owner_consent=False,
                    first_hop_route_consent=False,
                ),
                peer_id="plugin",
            )
        current = self.initialization_request(
            workflow_id="init-workflow-3",
            admission_causal_id="delivery-3",
        )
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(
                    self.consent_body(current),
                    causal_id="delivery-3",
                    message_id="wx-message-3",
                    native_cursor="cursor-3",
                ),
                peer_id="plugin",
            ).status,
            "accepted",
        )

        unresolved = self.plugin.prepare_initialization(current, peer_id="plugin")

        self.assertEqual(unresolved.status, "rejected")
        self.assertEqual(unresolved.reason_code, "owner-resolution-required")
        self.assertEqual(self.store.count_records(), 0)

    def test_prepare_configuration_mismatch_does_not_poison_later_replay(self):
        initialization = self.initialization_request()
        self.assertEqual(
            self.plugin.receive_weixin(
                self.message(self.consent_body(initialization)),
                peer_id="plugin",
            ).status,
            "accepted",
        )
        self.assertTrue(self.core.close().complete)
        rotated_attestor = HealthInitAttestor(
            b"b" * 32,
            key_id="rotated-health-init-attestor",
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=rotated_attestor,
            health_init_asset=self.init_asset,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=HealthInitRuntime(
                self.init_asset,
                rotated_attestor,
            ),
        )

        mismatched = self.plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )

        self.assertEqual(
            (mismatched.status, mismatched.reason_code),
            ("unavailable", "initialization-configuration-mismatch"),
        )
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
        recovered = self.plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )
        replay = self.plugin.prepare_initialization(
            initialization,
            peer_id="plugin",
        )
        self.assertEqual(recovered.status, "accepted")
        self.assertEqual(replay.to_wire(), recovered.to_wire())

    def test_disclosure_configuration_mismatch_does_not_poison_later_replay(self):
        initialization = replace(
            self.initialization_request(),
            owner_consent=False,
            first_hop_route_consent=False,
        )
        rotated_attestor = HealthInitAttestor(
            b"b" * 32,
            key_id="rotated-health-init-attestor",
        )
        mismatched_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=HealthInitRuntime(
                self.init_asset,
                rotated_attestor,
            ),
        )

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "initialization-configuration-mismatch",
        ):
            mismatched_plugin.form_initialization_disclosure(
                initialization,
                peer_id="plugin",
            )

        recovered = self.plugin.form_initialization_disclosure(
            initialization,
            peer_id="plugin",
        )
        replay = self.plugin.form_initialization_disclosure(
            initialization,
            peer_id="plugin",
        )
        self.assertEqual(replay, recovered)

    def test_resolution_slot_configuration_mismatch_does_not_poison_source_replay(self):
        prior_ids = tuple(f"delivery-{index}" for index in range(1, 7))
        for index, causal_id in enumerate(prior_ids, start=1):
            candidate = self.initialization_request(
                workflow_id=f"init-workflow-{index}",
                admission_causal_id=causal_id,
                timezone="UTC",
            )
            self.assertEqual(
                self.plugin.receive_weixin(
                    self.message(
                        self.consent_body(candidate),
                        causal_id=causal_id,
                        message_id=f"wx-message-{index}",
                        native_cursor=f"cursor-{index}",
                    ),
                    peer_id="plugin",
                ).status,
                "accepted",
            )
        resolution = self.initialization_request(
            workflow_id="init-workflow-resolution-replay",
            admission_causal_id="delivery-resolution-replay",
        )
        resolution_body = self.consent_body(
            resolution,
            resolved_source_causal_ids=prior_ids,
        ).read()
        self.assertTrue(self.core.close().complete)
        rotated_attestor = HealthInitAttestor(
            b"b" * 32,
            key_id="rotated-health-init-attestor",
        )

        def restart(attestor):
            self.core = HealthCore(
                self.store,
                self.head,
                writer_fence_vault=self.writer_vault,
                admission_policy=self.policy,
                health_init_verifier=attestor,
                health_init_asset=self.init_asset,
            )
            self.plugin = HealthPlugin(
                self.core,
                admission_policy=self.policy,
                health_init_runtime=HealthInitRuntime(
                    self.init_asset,
                    attestor,
                ),
            )

        restart(rotated_attestor)
        mismatched = self.plugin.receive_weixin(
            self.message(
                CountingBody(resolution_body),
                causal_id="delivery-resolution-replay",
                message_id="wx-message-resolution-replay",
                native_cursor="cursor-resolution-replay",
            ),
            peer_id="plugin",
        )
        self.assertEqual(
            (mismatched.status, mismatched.reason_code),
            ("unavailable", "initialization-configuration-mismatch"),
        )
        self.assertIsNone(
            self.plugin.source_receipt(
                "delivery-resolution-replay",
                peer_id="plugin",
            )
        )
        self.assertTrue(self.core.close().complete)
        restart(self.init_attestor)

        recovered = self.plugin.receive_weixin(
            self.message(
                CountingBody(resolution_body),
                causal_id="delivery-resolution-replay",
                message_id="wx-message-resolution-replay",
                native_cursor="cursor-resolution-replay",
            ),
            peer_id="plugin",
        )

        self.assertEqual(recovered.status, "accepted")


if __name__ == "__main__":
    unittest.main()

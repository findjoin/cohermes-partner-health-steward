"""Ticket 114 A6: owner mutations use the one Ticket 110--112 writer.

Every test starts from a fresh encrypted store, current-head authority, and
completed Ticket 111 initialization. Correction cases then commit a genuine
Ticket 112 evidence stage and pass its bound complete draft through the public
owner ``prepare -> commit -> finalize`` API. No rights-owned seed or state is
created here; all correction observations come back through DailyHealthState.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from unittest.mock import patch

from partner_health_steward import HealthCore, HealthPlugin, rights, settings, status
from partner_health_steward.admission import (
    AdmissionPolicy,
    RawWeixinMessage,
    materialize_source,
)
from partner_health_steward.authority import AuthorityValidationError
from partner_health_steward.coordination import (
    AtomicEvidenceClaim,
    CoarseMessageRouter,
    DailySkillAsset,
    DailySkillAttestor,
    DailySkillBundle,
    DailySkillRuntime,
    DailyTurnDraft,
    EvidenceContext,
    EvidenceDecision,
    EvidenceMaintenanceRequest,
    EvidenceSeriesKey,
    OwnerInquiryContext,
    OwnerInquiryDecision,
    PersonalHealthFields,
    PortraitContext,
    PortraitDecision,
    StewardContext,
    StewardPlan,
    StewardResolution,
    StewardResolutionContext,
)
from partner_health_steward.contract import (
    CommitMeta,
    DailyTurnMeta,
    ProtocolViolation,
    Response,
)
from partner_health_steward.core import InMemoryWriterFenceVault
from partner_health_steward.current_head import FailureMode, InMemoryCurrentHead
from partner_health_steward.evidence_profile import PersonalEvidenceProfile
from partner_health_steward.initialization import (
    HealthInitAsset,
    HealthInitAttestor,
    HealthInitRuntime,
    InitialPreferences,
    OwnerConsentEvidence,
    OwnerInitialization,
    SupportContactBoundary,
)
from partner_health_steward.owner_authority import (
    OwnerAuthorityContractViolation,
    OwnerMutationContext,
    OwnerMutationRequest,
)
from partner_health_steward.storage import (
    EncryptedStateStore,
    KeyUnavailable,
    StaticKeyProvider,
    StoredOwnerMutation,
    StoreUnavailable,
)
from tests.test_ticket112_seven_skill_daily_turn import (
    CountingBody,
    SyntheticSleepTurnExecutor,
)


_OWNER_ID = "owner-A"
_INSTALLATION_ID = "partner-installation"
_PEER_ID = "plugin"
_REQUESTED_AT = "2026-08-24T02:00:00+00:00"
_CORRECTION_TOPIC = "physical-function-and-experience/sleep"
_DEFAULT_OWNER_COMMAND = object()


class _CountingCurrentHead(InMemoryCurrentHead):
    """Expose whether an exact replay attempted another remote CAS."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.advance_call_count = 0

    def conditional_advance(self, request: Any) -> Any:
        self.advance_call_count += 1
        return super().conditional_advance(request)


class _OwnerAuthorityFailureStore(EncryptedStateStore):
    """Test-local failures inside each owner persistence boundary."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fail_after_owner_prepare_write = False
        self.fail_after_owner_finalize_write = False
        self.fail_commit_after_receipt = False
        self.owner_prepare_write_count = 0
        self.owner_finalize_write_count = 0

    def write_owner_mutation(self, *args: Any, **kwargs: Any) -> Any:
        self.owner_prepare_write_count += 1
        result = super().write_owner_mutation(*args, **kwargs)
        if self.fail_after_owner_prepare_write:
            self.fail_after_owner_prepare_write = False
            raise StoreUnavailable("synthetic owner prepare failure")
        return result

    def finalize_owner_mutation(self, *args: Any, **kwargs: Any) -> Any:
        self.owner_finalize_write_count += 1
        result = super().finalize_owner_mutation(*args, **kwargs)
        if self.fail_after_owner_finalize_write:
            self.fail_after_owner_finalize_write = False
            raise StoreUnavailable("synthetic owner finalize failure")
        return result

    def save_receipt(self, *args: Any, **kwargs: Any) -> Any:
        result = super().save_receipt(*args, **kwargs)
        if self.fail_commit_after_receipt:
            self.fail_commit_after_receipt = False
            self._connection.set_authorizer(self._deny_commit)
        return result

    @staticmethod
    def _deny_commit(
        action: int,
        argument_one: str | None,
        argument_two: str | None,
        database: str | None,
        trigger: str | None,
    ) -> int:
        del argument_two, database, trigger
        if action == sqlite3.SQLITE_TRANSACTION and argument_one == "COMMIT":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def clear_commit_failure(self) -> None:
        self._connection.set_authorizer(None)


class _LegacyManifestRaceStore(EncryptedStateStore):
    """Delete a signed legacy row after the first pre-Ticket-114 scan."""

    def __init__(self, database: str, *args: Any, **kwargs: Any) -> None:
        self._race_database = database
        self.race_fired = False
        super().__init__(database, *args, **kwargs)

    def _integrity_fingerprint(
        self,
        *,
        include_ticket111: bool = True,
        include_ticket112: bool | None = None,
        include_ticket114: bool | None = None,
        include_ticket114_status: bool | None = None,
    ) -> str:
        fingerprint = super()._integrity_fingerprint(
            include_ticket111=include_ticket111,
            include_ticket112=include_ticket112,
            include_ticket114=include_ticket114,
            include_ticket114_status=include_ticket114_status,
        )
        if not self.race_fired and include_ticket114 is False:
            self.race_fired = True
            writer = sqlite3.connect(self._race_database)
            try:
                writer.execute("DELETE FROM finalized_authority WHERE slot = 1")
                writer.commit()
            finally:
                writer.close()
        return fingerprint


class _FreshManifestRaceStore(EncryptedStateStore):
    """Insert a state row after the fresh-domain scan but before its writer lock."""

    def __init__(self, database: str, *args: Any, **kwargs: Any) -> None:
        self._race_database = database
        self.race_fired = False
        self.injected_projection = status.StatusProjection(
            state="cannot-confirm",
            evaluated_at_utc="2026-08-24T00:00:00+00:00",
            affected_core_domains=("current_head",),
            isolated_noncore_domains=(),
            reason_codes=("current_head:unknown",),
            fact_set_digest="sha256:" + ("9" * 64),
        )
        super().__init__(database, *args, **kwargs)

    @contextmanager
    def transaction(self) -> Any:
        key_ready = self._connection.execute(
            "SELECT 1 FROM key_check WHERE slot = 1"
        ).fetchone()
        manifest_missing = self._connection.execute(
            "SELECT 1 FROM integrity_manifest_v1 WHERE slot = 1"
        ).fetchone() is None
        if not self.race_fired and key_ready is not None and manifest_missing:
            self.race_fired = True
            nonce, ciphertext = self._seal(
                "business-status",
                self.injected_projection.to_storage(),
            )
            writer = sqlite3.connect(self._race_database)
            try:
                writer.execute(
                    "INSERT INTO business_status_v1(slot, nonce, ciphertext) "
                    "VALUES (1, ?, ?)",
                    (nonce, ciphertext),
                )
                writer.commit()
            finally:
                writer.close()
        with super().transaction() as connection:
            yield connection


class _SyntheticCorrectionTurnExecutor:
    """Execute one exact PendingCorrectionDraft through Ticket 112 Skills."""

    def __init__(
        self,
        request: EvidenceMaintenanceRequest,
        *,
        extra_atomic_claims: tuple[AtomicEvidenceClaim, ...] = (),
    ) -> None:
        self.request = request
        self.extra_atomic_claims = extra_atomic_claims
        self.fail_next_resolution = True

    def __call__(self, skill_name: str, context: object) -> object:
        if skill_name == "health-steward":
            if type(context) is StewardContext:
                return StewardPlan(
                    purpose=self.request.purpose,
                    selected_skills=("health-evidence", "health-portrait"),
                    atomic_claims=self.extra_atomic_claims,
                    portrait_topic_refs=(_CORRECTION_TOPIC,),
                    evidence_maintenance_requests=(self.request,),
                )
            if type(context) is StewardResolutionContext:
                if self.fail_next_resolution:
                    self.fail_next_resolution = False
                    raise AuthorityValidationError(
                        "synthetic pause after correction evidence stage"
                    )
                return StewardResolution(
                    commit_evidence_ids=context.candidate_evidence_ids,
                    commit_portrait_topic_refs=(
                        context.candidate_portrait_topic_refs
                    ),
                    reply_atom_ids=tuple(
                        atom.atom_id for atom in context.reply_atoms
                    ),
                    commit_evidence_change_ids=(
                        context.candidate_evidence_change_ids
                    ),
                )
            raise TypeError("unexpected steward context")
        if skill_name == "health-evidence":
            if (
                type(context) is EvidenceContext
                and context.maintenance_request is None
                and context.atomic_claim in self.extra_atomic_claims
            ):
                assert context.atomic_claim is not None
                return EvidenceDecision.admit(context.atomic_claim)
            if (
                type(context) is not EvidenceContext
                or context.maintenance_request != self.request
                or self.request.replacement_claim is None
            ):
                raise TypeError("unexpected correction evidence context")
            return EvidenceDecision.correct(
                self.request.replacement_claim,
                self.request.target_evidence_ids,
                reason=self.request.reason,
            )
        if skill_name == "health-portrait":
            if type(context) is not PortraitContext:
                raise TypeError("unexpected correction portrait context")
            return PortraitDecision.withdraw(
                context.affected_topic_refs[0],
                "owner correction requires portrait rejudgment",
            )
        raise AssertionError(f"unexpected Skill execution: {skill_name}")


class _EchoingStoppedCorrectionCompletionExecutor(
    _SyntheticCorrectionTurnExecutor
):
    """Keep correction evidence exact, then echo source text as portrait reason."""

    def __init__(self, request: EvidenceMaintenanceRequest) -> None:
        super().__init__(request)
        self.echoed_text: str | None = None

    def __call__(self, skill_name: str, context: object) -> object:
        if skill_name == "health-steward" and type(context) is StewardContext:
            self.echoed_text = context.owner_message
        if skill_name == "health-portrait":
            if type(context) is not PortraitContext:
                raise TypeError("unexpected echoing correction portrait context")
            if self.echoed_text is None:
                raise AssertionError("echoing correction plan did not run")
            return PortraitDecision.withdraw(
                context.affected_topic_refs[0],
                self.echoed_text,
            )
        return super().__call__(skill_name, context)


class _SyntheticTemporaryAnswerExecutor:
    """Return one owner-facing question without creating health records."""

    def __call__(self, skill_name: str, context: object) -> object:
        if skill_name == "health-steward":
            if type(context) is StewardContext:
                return StewardPlan(
                    purpose="temporary-owner-answer",
                    selected_skills=("health-owner-inquiry",),
                    atomic_claims=(),
                    inquiry_gap="owner-requested temporary clarification",
                )
            if type(context) is StewardResolutionContext:
                return StewardResolution(
                    commit_evidence_ids=context.candidate_evidence_ids,
                    commit_portrait_topic_refs=context.candidate_portrait_topic_refs,
                    reply_atom_ids=tuple(
                        atom.atom_id for atom in context.reply_atoms
                    ),
                    commit_evidence_change_ids=(
                        context.candidate_evidence_change_ids
                    ),
                )
        if skill_name == "health-owner-inquiry":
            if type(context) is not OwnerInquiryContext:
                raise TypeError("unexpected owner inquiry context")
            return OwnerInquiryDecision.gap("required-context-unavailable")
        raise TypeError("unexpected temporary-answer skill context")


class _FailingTemporaryCompletionExecutor(_SyntheticTemporaryAnswerExecutor):
    """Form a body-free evidence stage, then fail its owner-answer completion."""

    def __call__(self, skill_name: str, context: object) -> object:
        if skill_name == "health-steward" and type(context) is StewardResolutionContext:
            raise AuthorityValidationError("synthetic temporary completion failure")
        return super().__call__(skill_name, context)


class _EchoingStoppedTemporaryExecutor:
    """Attempt to smuggle transformed owner text through a temporary draft."""

    def __init__(self, *, fail_resolution: bool) -> None:
        self.echoed_text: str | None = None
        self.fail_resolution = fail_resolution

    def __call__(self, skill_name: str, context: object) -> object:
        if skill_name == "health-steward":
            if type(context) is StewardContext:
                transformed = "|".join(
                    context.owner_message[index : index + 2]
                    for index in range(0, len(context.owner_message), 2)
                )
                self.echoed_text = transformed
                return StewardPlan(
                    purpose=f"temporary:{transformed}",
                    selected_skills=("health-owner-inquiry",),
                    atomic_claims=(),
                    inquiry_gap=transformed,
                )
            if type(context) is StewardResolutionContext:
                if self.fail_resolution:
                    raise AuthorityValidationError(
                        "synthetic echoing completion failure"
                    )
                return StewardResolution(
                    commit_evidence_ids=context.candidate_evidence_ids,
                    commit_portrait_topic_refs=(
                        context.candidate_portrait_topic_refs
                    ),
                    reply_atom_ids=tuple(
                        atom.atom_id for atom in context.reply_atoms
                    ),
                    commit_evidence_change_ids=(
                        context.candidate_evidence_change_ids
                    ),
                )
        if skill_name == "health-owner-inquiry":
            if type(context) is not OwnerInquiryContext:
                raise TypeError("unexpected echoing inquiry context")
            if self.echoed_text is None:
                raise AssertionError("echoing plan did not run")
            return OwnerInquiryDecision.gap(self.echoed_text)
        raise TypeError("unexpected echoing temporary context")


class _TerminalEchoingStoppedTemporaryExecutor(
    _SyntheticTemporaryAnswerExecutor
):
    """Keep the evidence stage canonical, then echo only in completion."""

    def __init__(self, *, before_inquiry_result: Callable[[], None]) -> None:
        self.echoed_text: str | None = None
        self.before_inquiry_result = before_inquiry_result

    def __call__(self, skill_name: str, context: object) -> object:
        if skill_name == "health-steward" and type(context) is StewardContext:
            self.echoed_text = context.owner_message
            return super().__call__(skill_name, context)
        if skill_name == "health-owner-inquiry":
            if type(context) is not OwnerInquiryContext:
                raise TypeError("unexpected terminal echoing inquiry context")
            if self.echoed_text is None:
                raise AssertionError("terminal echoing plan did not run")
            self.before_inquiry_result()
            return OwnerInquiryDecision.gap(self.echoed_text)
        return super().__call__(skill_name, context)


class _FailingStoppedRecordingExecutor:
    """Fail before a stopped-recording source can form any daily draft."""

    def __call__(self, skill_name: str, context: object) -> object:
        if skill_name == "health-steward" and type(context) is StewardContext:
            raise AuthorityValidationError("synthetic stopped-recording planner failure")
        raise TypeError("unexpected stopped-recording failure context")


class Ticket114AuthorityIntegrationTests(unittest.TestCase):
    """One independently visible black-box test per registered A6 Case."""

    maxDiff = None

    def setUp(self) -> None:
        self.writer_capability = "ticket114-owner-writer"
        uri_case = self._testMethodName.replace("_", "-")
        self.store = _OwnerAuthorityFailureStore(
            f"file:{uri_case}?mode=memory&cache=shared",
            StaticKeyProvider(b"u" * 32, key_id="ticket114-owner-state-key"),
        )
        self.head = _CountingCurrentHead(
            installation_id=_INSTALLATION_ID,
            site="partner-site",
            writer_capability=self.writer_capability,
        )
        authority = self.head.read().head.as_authority()
        self.store.seed_finalized_authority(authority)
        self.writer_vault = InMemoryWriterFenceVault()
        self.writer_vault.bind(authority, self.writer_capability)
        self.policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id=_OWNER_ID,
            conversation_id="private-A",
        )
        self.init_attestor = HealthInitAttestor(
            b"a" * 32,
            key_id="ticket114-health-init-attestor",
        )
        self.init_asset = HealthInitAsset(
            version="1.0.0",
            asset_digest="sha256:" + ("1" * 64),
            disclosure_version="health-init-disclosure-v1",
        )
        self.init_runtime = HealthInitRuntime(
            self.init_asset,
            self.init_attestor,
            clock=lambda: datetime(2026, 8, 24, 0, 59, tzinfo=timezone.utc),
        )
        self.route_classification = "ordinary"
        self.router = CoarseMessageRouter(
            classifier=lambda body, requested: self.route_classification
        )
        self.daily_attestor = DailySkillAttestor(
            b"s" * 32,
            key_id="ticket114-daily-skill-attestor",
        )
        self.daily_bundle = DailySkillBundle(
            tuple(
                DailySkillAsset(
                    canonical_name=canonical_name,
                    friendly_name=friendly_name,
                    role=role,
                    version="1.0.0",
                    asset_digest="sha256:" + (digit * 64),
                    disclosure_version="daily-skill-disclosure-v1",
                )
                for canonical_name, friendly_name, role, digit in (
                    ("health-steward", "健康管家", "A", "2"),
                    ("health-settings", "健康管家设置", "A", "3"),
                    ("health-portrait", "健康画像维护", "B", "4"),
                    ("health-evidence", "健康证据维护", "B", "5"),
                    ("health-owner-inquiry", "向主人补问", "B", "6"),
                    ("health-literature", "健康资料查找", "B", "7"),
                )
            )
        )
        self.sleep_executor = SyntheticSleepTurnExecutor()
        self.sleep_runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=self.sleep_executor,
            clock=lambda: datetime(2026, 8, 24, 1, 6, tzinfo=timezone.utc),
        )
        self.owner_clock_value = datetime(
            2026,
            8,
            24,
            2,
            30,
            tzinfo=timezone.utc,
        )
        self.status_clock_value = datetime(
            2026,
            8,
            24,
            12,
            0,
            tzinfo=timezone.utc,
        )
        self.status_authority = (
            status.CapabilityFactAuthority(
                authority_id="ticket114-production-status-authority",
                signing_key=b"ticket114-production-status-key",
                producer_contracts=dict(
                    status.PRODUCTION_STATUS_PRODUCER_CONTRACTS
                ),
            )
            if self._testMethodName
            in {
                "test_114_a5_c20_core_status_uses_real_authorities_and_keeps_future_domains_unknown",
                "test_114_a5_c21_status_transition_is_deduplicated_across_restart",
            }
            else None
        )
        core_options: dict[str, object] = {}
        if self.status_authority is not None:
            core_options.update(
                status_fact_authority=self.status_authority,
                business_status_clock=lambda: self.status_clock_value,
            )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
            daily_skill_verifier=self.daily_attestor,
            daily_skill_bundle=self.daily_bundle,
            owner_settings_clock=lambda: self.owner_clock_value,
            **core_options,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=self.sleep_runtime,
        )
        self._enable_product()
        self._seed_authoritative_evidence()

        self.correction_source_id = f"{self._testMethodName}:correction"
        self.pending_correction = None
        self.correction_stage = None
        self.complete_draft = None
        self.correction_plugin = self.plugin
        if self._testMethodName not in {
            "test_114_a1_c17_ticket111_preferences_seed_authoritative_settings",
            "test_114_a1_c18_finalized_status_recovers_exact_settings_result",
            "test_114_a2_c08_recording_stop_blocks_real_daily_body_commit",
            "test_114_a2_c09_recording_stop_allows_temporary_answer_without_body",
            "test_114_a2_c10_recording_stop_preserves_owner_correction_right",
            "test_114_a2_c11_recording_stop_never_persists_body_on_planner_failure",
            "test_114_a2_c12_exact_redelivery_rehydrates_only_transient_stopped_body",
            "test_114_a2_c13_delayed_first_delivery_from_exclusion_is_not_backfilled",
            "test_114_a2_c14_recording_excluded_native_alias_is_body_free_from_creation",
            "test_114_a2_c15_failed_stopped_planner_releases_transient_body",
            "test_114_a2_c16_stopped_prepare_rejection_receipt_is_body_free",
            "test_114_a2_c17_missing_event_time_after_exclusion_fails_closed",
            "test_114_a2_c18_missing_runtime_releases_transient_body",
            "test_114_a2_c19_status_failure_releases_transient_body",
            "test_114_a2_c20_admission_commit_rollback_releases_transient_body",
            "test_114_a2_c21_temporary_completion_failure_releases_transient_body",
            "test_114_a2_c22_correction_cas_owns_transient_body_until_finalize",
            "test_114_a2_c23_recording_stop_rejects_echoing_temporary_draft",
            "test_114_a2_c24_recording_stop_rejects_echoing_temporary_terminal",
            "test_114_a2_c25_recording_stop_rejects_mixed_correction_scope",
            "test_114_a2_c26_recording_stop_rejects_echoing_correction_completion",
            "test_114_a2_c27_recording_stop_rejects_unbound_correction_stage",
            "test_114_a2_c28_rejected_owner_prepare_releases_correction_plaintext",
            "test_114_a2_c30_stopped_correction_handoff_recovers_after_restart",
            "test_114_a2_c31_public_correction_handoff_rejects_wrong_body",
            "test_114_a2_c32_public_correction_handoff_requires_reregistration",
            "test_114_a2_c33_public_correction_handoff_rejects_forged_scope",
            "test_114_a2_c34_public_correction_handoff_cleans_up_owner_rejection",
            "test_114_a3_c25_public_rights_read_denies_wrong_owner_policy",
            "test_114_a3_c26_public_rights_read_denies_untrusted_peer",
            "test_114_a4_c13_core_activates_due_timezone_after_restart",
            "test_114_a5_c20_core_status_uses_real_authorities_and_keeps_future_domains_unknown",
            "test_114_a5_c21_status_transition_is_deduplicated_across_restart",
            "test_114_a6_c06_stale_writer_fence_fails_before_write",
            "test_114_a6_c10_concurrent_owner_lease_rejects_without_partial_record",
            "test_114_a6_c11_terminal_settings_digest_rejects_same_version_substitution",
            "test_114_a6_c12_terminal_binds_exact_generic_transition_target",
            "test_114_a6_c13_wrong_owner_fails_before_write",
            "test_114_a6_c14_wrong_installation_fails_before_write",
            "test_114_a6_c15_missing_settings_permission_fails_at_public_seam",
            "test_114_a6_c17_stale_current_head_generation_fails_before_write",
            "test_114_a6_c18_stale_settings_object_version_fails_before_write",
            "test_114_a6_c19_legacy_manifest_migration_rechecks_signed_shape_inside_lock",
            "test_114_a6_c20_fresh_manifest_rechecks_empty_domain_inside_lock",
            "test_114_a6_c23_owner_commit_recovers_stopped_correction_without_body",
            "test_114_a7_c11_owner_cannot_submit_route_authority_fact",
            "test_114_a7_c12_core_route_fact_pauses_until_exact_reconsent",
            "test_114_a9_c25_ticket111_contact_starts_without_execution_authority",
            "test_114_a9_c26_public_managed_read_configures_not_configured_contact",
            "test_114_a9_c27_public_method_change_invalidates_and_reapproves_exactly",
        }:
            self._build_and_commit_correction_stage()

    def tearDown(self) -> None:
        self.store.clear_commit_failure()
        self.head.clear_failure()
        self.core.close()
        self.store.close()

    def _initialization_request(self) -> OwnerInitialization:
        support_contact = (
            SupportContactBoundary(
                contact_ref="trusted-family-member",
                method="weixin",
                purpose="emergency-support",
            )
            if self._testMethodName
            == "test_114_a9_c25_ticket111_contact_starts_without_execution_authority"
            else None
        )
        return OwnerInitialization(
            workflow_id=f"{self._testMethodName}:initialization",
            admission_causal_id=f"{self._testMethodName}:initialization-source",
            owner_consent=True,
            first_hop_route="jojo-responses-v1",
            first_hop_route_consent=True,
            timezone="Asia/Shanghai",
            preferences=InitialPreferences(
                contact_window="09:00-21:00",
                expression_style="concise",
                proactive_support=True,
            ),
            data_boundary=(
                "health-portrait",
                "health-evidence",
                "health-tasks",
            ),
            support_contact=support_contact,
        )

    def _message(self, body: object, **changes: object) -> RawWeixinMessage:
        values: dict[str, object] = {
            "causal_id": f"{self._testMethodName}:initialization-source",
            "generation": 1,
            "channel": "weixin",
            "partner_id": "partner-A",
            "sender_id": _OWNER_ID,
            "conversation_id": "private-A",
            "chat_type": "private",
            "entrypoint": "health_weixin",
            "requested_capability": "health-init",
            "message_id": f"wx:{self._testMethodName}:initialization",
            "protocol_timestamp": "2026-08-24T09:00:00+08:00",
            "received_at": "2026-08-24T09:00:01+08:00",
            "native_cursor": f"cursor:{self._testMethodName}:initialization",
            "body": body,
        }
        values.update(changes)
        return RawWeixinMessage(**values)  # type: ignore[arg-type]

    def _enable_product(self) -> None:
        initialization = self._initialization_request()
        disclosure = self.plugin.form_initialization_disclosure(
            replace(
                initialization,
                owner_consent=False,
                first_hop_route_consent=False,
            ),
            peer_id=_PEER_ID,
        )
        consent = OwnerConsentEvidence.for_initialization(
            initialization,
            self.init_asset,
            disclosure,
            owner_confirmed=True,
            first_hop_route_confirmed=True,
        )
        admitted = self.plugin.receive_weixin(
            self._message(CountingBody(consent.to_message_body())),
            peer_id=_PEER_ID,
        )
        self.assertEqual(admitted.status, "accepted")
        self.assertEqual(
            self.plugin.prepare_initialization(
                initialization,
                peer_id=_PEER_ID,
            ).status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.commit_initialization(peer_id=_PEER_ID).status,
            "accepted",
        )
        self.assertEqual(
            self.plugin.finalize_initialization(peer_id=_PEER_ID).status,
            "accepted",
        )

    def _seed_authoritative_evidence(self) -> None:
        self.route_classification = "health"
        response = self.plugin.receive_weixin(
            self._message(
                CountingBody("我昨晚没睡好"),
                causal_id=f"{self._testMethodName}:baseline",
                generation=2,
                requested_capability="health-steward",
                message_id=f"wx:{self._testMethodName}:baseline",
                protocol_timestamp="2026-08-24T09:06:00+08:00",
                received_at="2026-08-24T09:06:01+08:00",
                native_cursor=f"cursor:{self._testMethodName}:baseline",
            ),
            peer_id=_PEER_ID,
        )
        self.assertEqual(response.status, "accepted", response)
        self.baseline_daily_state = self.plugin.daily_state(peer_id=_PEER_ID)
        self.assertEqual(len(self.baseline_daily_state.evidence_cards), 1)
        self.baseline_card = self.baseline_daily_state.evidence_cards[0]

    def _replacement_claim(self) -> AtomicEvidenceClaim:
        return AtomicEvidenceClaim(
            content="主人更正：昨晚睡眠体验尚可",
            evidence_type="personal-health",
            source_kind="owner-statement",
            occurred_at="2026-08-23",
            applicable_period="2026-08-23-night",
            purpose="correct-personal-evidence",
            uncertainty="主人主观体验",
            limitations=("单次陈述不证明长期趋势",),
            proves=("主人更正：昨晚睡眠体验尚可",),
            does_not_prove=("睡眠时长", "长期趋势", "失眠诊断"),
            topic_refs=(_CORRECTION_TOPIC,),
            specific_fields=PersonalHealthFields("owner-statement"),
            series_key=EvidenceSeriesKey(
                "personal-health",
                "subjective-sleep-experience",
                PersonalEvidenceProfile("owner-statement"),
                "single-night",
            ),
            time_certainty="known",
        )

    def _build_and_commit_correction_stage(self) -> None:
        self.pending_correction = self.plugin.managed_correction_draft(
            target_ref=rights.ManagedObjectReference(
                object_ref=self.baseline_card.evidence_id,
                installation_id=_INSTALLATION_ID,
                version=1,
            ),
            correction_id=f"correction:{self._testMethodName}",
            reason="主人更正已记录的睡眠体验",
            corrected_at_utc=_REQUESTED_AT,
            replacement_claim=self._replacement_claim(),
            correction_source_refs=(
                f"source:{self.correction_source_id}",
            ),
            affected_object_refs=(
                f"portrait-topic:{_CORRECTION_TOPIC}",
            ),
            disposition_requests=("rejudge",),
            peer_id=_PEER_ID,
        )
        extra_atomic_claims: tuple[AtomicEvidenceClaim, ...] = ()
        if (
            self._testMethodName
            == "test_114_a3_c23_owner_correction_rejects_extra_evidence_scope"
        ):
            extra_atomic_claims = (
                replace(
                    self._replacement_claim(),
                    content="未获本次纠正授权的另一条健康陈述",
                    occurred_at="2026-08-24",
                    applicable_period="2026-08-24-day",
                    proves=("未获本次纠正授权的另一条健康陈述",),
                    does_not_prove=("该陈述获本次纠正授权",),
                ),
            )
        correction_executor = (
            _EchoingStoppedCorrectionCompletionExecutor(
                self.pending_correction.maintenance_request
            )
            if self._testMethodName
            == "test_114_a2_c26_recording_stop_rejects_echoing_correction_completion"
            else _SyntheticCorrectionTurnExecutor(
                self.pending_correction.maintenance_request,
                extra_atomic_claims=extra_atomic_claims,
            )
        )
        correction_runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=correction_executor,
            clock=lambda: datetime(2026, 8, 24, 2, 1, tzinfo=timezone.utc),
        )
        self.correction_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=correction_runtime,
        )
        changes = {
            "causal_id": self.correction_source_id,
            "generation": self.head.read().head.generation,
            "requested_capability": "health-steward",
            "message_id": f"wx:{self.correction_source_id}",
            "protocol_timestamp": "2026-08-24T10:00:00+08:00",
            "received_at": "2026-08-24T10:00:01+08:00",
            "native_cursor": f"cursor:{self.correction_source_id}",
        }
        correction_body = (
            "CORRECTION-COMPLETION-SOURCE-SECRET-7529"
            if self._testMethodName
            == "test_114_a2_c26_recording_stop_rejects_echoing_correction_completion"
            else "请更正昨晚的睡眠记录"
        )
        interrupted = self.correction_plugin.receive_weixin(
            self._message(CountingBody(correction_body), **changes),
            peer_id=_PEER_ID,
        )
        self.assertEqual(interrupted.status, "unavailable", interrupted)
        status = self.core.daily_turn_status(self.correction_source_id)
        self.assertIsNotNone(status, interrupted)
        assert status is not None
        self.assertEqual(status.phase, "evidence-finalized")
        self.assertIs(type(status.draft), DailyTurnDraft)
        self.correction_stage = status.draft
        self.assertEqual(self.correction_stage.turn_kind, "evidence-stage")
        self.assertEqual(
            len(self.correction_stage.evidence_cards),
            1 + len(extra_atomic_claims),
        )
        self.assertEqual(
            len(self.correction_stage.evidence_applicability_changes),
            1,
        )
        self.assertEqual(
            sum(
                relation.relation_kind == "corrects"
                for relation in self.correction_stage.evidence_relations
            ),
            1,
        )
        post_stage = self.core.daily_turn_post_stage_state(
            self.correction_source_id
        )
        source = materialize_source(
            self._message(
                CountingBody(correction_body),
                **changes,
            )
        )
        try:
            self.complete_draft = correction_runtime.complete(
                source,
                post_stage,
                self.correction_stage,
            )
        except AuthorityValidationError:
            if (
                interrupted.reason_code
                != "owner-correction-handoff-required"
            ):
                raise
            self.complete_draft = correction_runtime.complete(
                source,
                post_stage,
                self.correction_stage,
            )
        self.assertEqual(self.complete_draft.turn_kind, "complete-turn")
        self.assertEqual(
            self.complete_draft.evidence_stage,
            self.correction_stage,
        )
        self.assertIsNone(self._daily_result_or_none())
        self.assertEqual(
            self.plugin.daily_state(peer_id=_PEER_ID),
            self.baseline_daily_state,
        )

    def _owner_request(
        self,
        *,
        settings_mutation: bool = True,
        correction: bool = True,
        stale_writer_fence: bool = False,
        control_name: str = "proactive_support",
        control_operation: str = "pause",
        command_suffix: str = "",
        settings_command: object = _DEFAULT_OWNER_COMMAND,
        expected_settings_version: int = 1,
        owner_id: str = _OWNER_ID,
        installation_id: str = _INSTALLATION_ID,
        permissions: tuple[str, ...] | None = None,
        current_head_generation: int | None = None,
    ) -> OwnerMutationRequest:
        snapshot = self.head.read().head
        writer_fence = (
            "fence:stale-owner-writer"
            if stale_writer_fence
            else snapshot.writer_fence
        )
        permission_values: list[str] = []
        if permissions is None:
            if settings_mutation:
                permission_values.append("health_settings.write")
            if correction:
                permission_values.append("health_data.correct")
        else:
            permission_values.extend(permissions)
        context = OwnerMutationContext(
            command_id=f"owner-mutation:{self._testMethodName}{command_suffix}",
            causal_id=(
                f"{self._testMethodName}:owner-command-source{command_suffix}"
            ),
            actor_kind="current_owner",
            owner_id=owner_id,
            installation_id=installation_id,
            permissions=tuple(sorted(permission_values)),
            context_ref=f"managed-context:{self._testMethodName}",
            current_head_generation=(
                snapshot.generation
                if current_head_generation is None
                else current_head_generation
            ),
            writer_fence=writer_fence,
        )
        command = settings_command
        if command is _DEFAULT_OWNER_COMMAND:
            command = (
                settings.ControlUpdate(
                    control_name=control_name,
                    operation=control_operation,
                    target_ref=None,
                    generation=snapshot.generation,
                    effective_at_utc=_REQUESTED_AT,
                )
                if settings_mutation
                else None
            )
        request = OwnerMutationRequest.form(
            context=context,
            expected_settings_version=expected_settings_version,
            requested_at_utc=_REQUESTED_AT,
            settings_command=command,
            pending_correction=(
                self.pending_correction if correction else None
            ),
            daily_turn_draft=self.complete_draft if correction else None,
        )
        if correction:
            self.assertIsNotNone(request.daily_turn_draft)
            self.assertEqual(
                request.daily_turn_draft.owner_authority_binding_digest,
                request.owner_authority_binding_digest,
            )
        return request

    @staticmethod
    def _forge_owner_request(
        request: OwnerMutationRequest,
        *,
        context: OwnerMutationContext,
    ) -> OwnerMutationRequest:
        """Model an exact-type hostile caller that bypassed dataclass init."""

        forged = object.__new__(OwnerMutationRequest)
        for name in (
            "context",
            "expected_settings_version",
            "requested_at_utc",
            "settings_command",
            "pending_correction",
            "daily_turn_draft",
            "owner_authority_binding_digest",
        ):
            object.__setattr__(
                forged,
                name,
                context if name == "context" else getattr(request, name),
            )
        return forged

    def _support_contact(
        self,
        *,
        version: int,
        method_kind: str = "weixin_user",
        method_value: str = "wxid_ticket114_contact",
        disclosure_version: str = "support-contact-disclosure-v1",
    ) -> settings.SupportContactSettings:
        return settings.SupportContactSettings(
            contact_id="support-contact:ticket114-current",
            version=version,
            owner_id=_OWNER_ID,
            installation_id=_INSTALLATION_ID,
            identity_label="主人可识别的可信联系人",
            method_kind=method_kind,
            method_value=method_value,
            purpose="minimum urgent-help contact alert",
            minimum_alert_fields=(
                "owner_recognizable_name",
                "event_time",
                "fixed_urgent_help_request",
            ),
            route_id="weixin-ilink-partner",
            route_generation=1,
            disclosure_version=disclosure_version,
            dedicated_paused=False,
            alert_authority_status="invalidated",
            alert_approval_id=None,
            alert_authority_binding=None,
            correction_authority_status="invalidated",
            correction_authority_id=None,
            correction_authority_binding=None,
            max_corrections_per_alert=1,
        )

    def _support_contact_command(
        self,
        operation: str,
        *,
        suffix: str,
        contact: settings.SupportContactSettings | None = None,
        authority_id: str | None = None,
        expected_contact_version: int | None = None,
        expected_route_id: str | None = None,
        expected_route_generation: int | None = None,
    ) -> settings.SupportContactCommand:
        authority = self.head.read().head
        return settings.SupportContactCommand(
            context=settings.OwnerCommandContext(
                command_id=f"contact-command:{self._testMethodName}:{suffix}",
                causal_id=f"contact-source:{self._testMethodName}:{suffix}",
                actor_kind="current_owner",
                owner_id=_OWNER_ID,
                installation_id=_INSTALLATION_ID,
                permission="health_settings.write",
                context_ref=f"managed-context:{self._testMethodName}:{suffix}",
                generation=authority.generation,
                writer_fence=authority.writer_fence,
            ),
            operation=operation,
            contact=contact,
            authority_id=authority_id,
            expected_contact_version=expected_contact_version,
            expected_route_id=expected_route_id,
            expected_route_generation=expected_route_generation,
        )

    def _commit_settings_command(
        self,
        command: object,
        *,
        suffix: str,
    ) -> None:
        current = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        request = self._owner_request(
            correction=False,
            settings_command=command,
            expected_settings_version=current.version,
            command_suffix=f":{suffix}",
        )
        self.assertEqual(self._prepare(request).status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        self.assertEqual(self._finalize(request).status, "accepted")

    def _business_snapshot(self) -> tuple[object, object, object]:
        return (
            self.correction_plugin.owner_settings_state(peer_id=_PEER_ID),
            self.correction_plugin.managed_rights_read_current(peer_id=_PEER_ID),
            self.correction_plugin.daily_state(peer_id=_PEER_ID),
        )

    def _stored_command_receipt(self, causal_id: str) -> object:
        row = self.store._execute(
            "SELECT nonce, ciphertext FROM command_receipts_v2 WHERE causal_id = ?",
            (causal_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        return self.store._open(
            f"receipt:v2:{causal_id}",
            row[0],
            row[1],
        )

    def _daily_result_or_none(self) -> object | None:
        try:
            return self.core.daily_turn_result(self.correction_source_id)
        except AuthorityValidationError:
            return None

    @staticmethod
    def _rights_from_stored_daily(state: object) -> tuple[object, ...]:
        projection = HealthCore._managed_rights_projection_from_state(
            state,
            owner_id=_OWNER_ID,
            installation_id=_INSTALLATION_ID,
        )
        requested = tuple(
            rights.ManagedObjectReference(
                object_ref=item.object_ref,
                installation_id=item.installation_id,
                version=item.version,
            )
            for item in projection.objects
            if item.current
            and item.object_ref in projection.permitted_object_refs
            and item.object_ref not in projection.revoked_object_refs
        )
        return rights.ManagedRightsService.managed_read(
            projection,
            requester_owner_id=_OWNER_ID,
            permission="health_data.read",
            requested_refs=requested,
        )

    def _assert_no_partial_result(
        self,
        before: tuple[object, object, object],
    ) -> None:
        before_settings, before_rights, before_daily = before
        stored_settings = self.store.owner_settings()
        self.assertIn(stored_settings, (None, before_settings))
        stored_daily = self.store.daily_state()
        self.assertEqual(stored_daily, before_daily)
        self.assertEqual(
            before_rights,
            self._rights_from_stored_daily(stored_daily),
        )
        self.assertIsNone(self._daily_result_or_none())
        self.assertNotIn(
            self.correction_source_id,
            stored_daily.processed_source_causal_ids,
        )

    def _prepare(self, request: OwnerMutationRequest) -> object:
        return self.correction_plugin.prepare_owner_mutation(
            request,
            peer_id=_PEER_ID,
        )

    def _commit(self, request: OwnerMutationRequest) -> object:
        return self.correction_plugin.commit_owner_mutation(
            request.context.command_id,
            peer_id=_PEER_ID,
        )

    def _finalize(self, request: OwnerMutationRequest) -> object:
        return self.correction_plugin.finalize_owner_mutation(
            request.context.command_id,
            peer_id=_PEER_ID,
        )

    def _status(self, request: OwnerMutationRequest) -> object:
        return self.correction_plugin.owner_mutation_status(
            request.context.command_id,
            peer_id=_PEER_ID,
        )

    def _restart_plugin(
        self,
        *,
        daily_skill_runtime: DailySkillRuntime | None = None,
    ) -> HealthPlugin:
        self.assertTrue(self.core.close().complete)
        core_options: dict[str, object] = {}
        if self.status_authority is not None:
            core_options.update(
                status_fact_authority=self.status_authority,
                business_status_clock=lambda: self.status_clock_value,
            )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
            daily_skill_verifier=self.daily_attestor,
            daily_skill_bundle=self.daily_bundle,
            owner_settings_clock=lambda: self.owner_clock_value,
            **core_options,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=(
                self.sleep_runtime
                if daily_skill_runtime is None
                else daily_skill_runtime
            ),
        )
        self.correction_plugin = self.plugin
        return self.plugin

    def _exact_redelivery(self, source_causal_id: str) -> RawWeixinMessage:
        receipt = self.store.source_receipt(source_causal_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        envelope = receipt.envelope
        self.assertIsNotNone(envelope.body)
        assert envelope.body is not None
        return RawWeixinMessage(
            causal_id=envelope.causal_id,
            generation=envelope.generation,
            channel=envelope.channel,
            partner_id=envelope.partner_id,
            sender_id=envelope.sender_id,
            conversation_id=envelope.conversation_id,
            chat_type=envelope.chat_type,
            entrypoint=envelope.entrypoint,
            requested_capability=envelope.requested_capability,
            message_id=envelope.message_id,
            protocol_timestamp=envelope.protocol_timestamp,
            received_at=envelope.received_at,
            native_cursor=envelope.native_cursor,
            body=CountingBody(envelope.body),
        )

    def _restarted_stopped_correction_submission(
        self,
        *,
        reregister: bool = True,
        pause_once: bool = False,
    ) -> tuple[
        HealthPlugin,
        rights.PendingCorrectionDraft,
        RawWeixinMessage,
        OwnerMutationContext,
    ]:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        self._build_and_commit_correction_stage()
        pending = self.pending_correction
        self.assertIsNotNone(pending)
        assert pending is not None
        executor = _SyntheticCorrectionTurnExecutor(
            pending.maintenance_request
        )
        executor.fail_next_resolution = pause_once
        runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=executor,
            clock=lambda: datetime(
                2026,
                8,
                24,
                2,
                1,
                tzinfo=timezone.utc,
            ),
        )
        restarted = self._restart_plugin(daily_skill_runtime=runtime)
        if reregister:
            pending = restarted.managed_correction_draft(
                target_ref=pending.target_ref,
                correction_id=pending.revision.correction_id,
                reason=pending.revision.reason,
                corrected_at_utc=pending.revision.corrected_at_utc,
                replacement_claim=self._replacement_claim(),
                correction_source_refs=pending.revision.source_refs,
                affected_object_refs=pending.revision.affected_object_refs,
                disposition_requests=pending.revision.disposition_requests,
                peer_id=_PEER_ID,
            )
        receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        envelope = receipt.envelope
        self.assertIsNone(envelope.body)
        redelivery = RawWeixinMessage(
            causal_id=envelope.causal_id,
            generation=envelope.generation,
            channel=envelope.channel,
            partner_id=envelope.partner_id,
            sender_id=envelope.sender_id,
            conversation_id=envelope.conversation_id,
            chat_type=envelope.chat_type,
            entrypoint=envelope.entrypoint,
            requested_capability=envelope.requested_capability,
            message_id=envelope.message_id,
            protocol_timestamp=envelope.protocol_timestamp,
            received_at=envelope.received_at,
            native_cursor=envelope.native_cursor,
            body=CountingBody("请更正昨晚的睡眠记录"),
        )
        snapshot = self.head.read().head
        context = OwnerMutationContext(
            command_id=f"owner-mutation:{self._testMethodName}",
            causal_id=f"{self._testMethodName}:owner-command-source",
            actor_kind="current_owner",
            owner_id=_OWNER_ID,
            installation_id=_INSTALLATION_ID,
            permissions=("health_data.correct",),
            context_ref=f"managed-context:{self._testMethodName}",
            current_head_generation=snapshot.generation,
            writer_fence=snapshot.writer_fence,
        )
        return restarted, pending, redelivery, context

    def test_114_a1_c17_ticket111_preferences_seed_authoritative_settings(self) -> None:
        current = self.plugin.owner_settings_state(peer_id=_PEER_ID)

        self.assertEqual(current.contact_window, "09:00-21:00")
        self.assertEqual(current.expression_style, "concise")
        self.assertTrue(current.proactive_contact)
        self.assertEqual(
            current.ordinary_notifications,
            tuple(
                (kind, "not-configured")
                for kind in settings.ORDINARY_NOTIFICATION_KINDS
            ),
        )
        self.assertIsNone(current.support_contact)
        self.assertEqual(current.version, 1)

    def test_114_a1_c18_finalized_status_recovers_exact_settings_result(self) -> None:
        current = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        command = settings.FieldUpdate(
            field_name="contact_window",
            old_value=current.contact_window,
            new_value="10:00-20:00",
            generation=self.head.read().head.generation,
            effective_at_utc=_REQUESTED_AT,
        )
        request = self._owner_request(
            correction=False,
            settings_command=command,
        )

        self.assertEqual(self._prepare(request).status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        self.assertEqual(self._finalize(request).status, "accepted")

        status_result = self._status(request)
        expected = {
            "kind": "field_update",
            "field_name": "contact_window",
            "old_value": "09:00-21:00",
            "new_value": "10:00-20:00",
            "settings_version": 2,
            "effective_at_utc": "2026-08-24T02:30:00+00:00",
        }
        self.assertIsNotNone(status_result)
        self.assertEqual(status_result.phase, "finalized")
        self.assertEqual(status_result.settings_version, 2)
        self.assertEqual(status_result.settings_result, expected)
        self.assertNotIn("generation", status_result.settings_result)

        stored = self.store.owner_mutation(request.context.command_id)
        self.assertIsNotNone(stored)
        self.assertIsNone(stored.prepared)
        self.assertIsNotNone(stored.terminal)
        terminal_wire = stored.terminal.to_storage()
        self.assertEqual(terminal_wire["settings_result"], expected)
        self.assertNotIn("pending_correction", repr(terminal_wire))
        self.assertNotIn("daily_turn_draft", repr(terminal_wire))
        self.assertNotIn("replacement_claim", repr(terminal_wire))

    def test_114_a2_c08_recording_stop_blocks_real_daily_body_commit(self) -> None:
        request = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
        )
        prepared = self._prepare(request)
        self.assertEqual(
            (prepared.status, prepared.reason_code),
            ("accepted", "owner-mutation-prepared"),
        )
        self.assertEqual(self._commit(request).status, "accepted")
        self.assertEqual(self._finalize(request).status, "accepted")
        stopped = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        self.assertTrue(stopped.recording_stopped)
        self.assertEqual(
            stopped.recording_stopped_at_utc,
            "2026-08-24T02:30:00+00:00",
        )
        before = self.plugin.daily_state(peer_id=_PEER_ID)
        source_id = f"{self._testMethodName}:blocked-recording"
        self.route_classification = "health"

        rejected = self.plugin.receive_weixin(
            self._message(
                CountingBody("今天新增一条个人健康记录"),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T11:00:00+08:00",
                received_at="2026-08-24T11:00:01+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.reason_code, "health-recording-stopped")
        self.assertEqual(self.plugin.daily_state(peer_id=_PEER_ID), before)
        self.assertIsNone(self.store.daily_turn(source_id))
        receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "recording-excluded")

    def test_114_a2_c09_recording_stop_allows_temporary_answer_without_body(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        before = self.plugin.daily_state(peer_id=_PEER_ID)
        temporary_runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=_SyntheticTemporaryAnswerExecutor(),
            clock=lambda: datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc),
        )
        temporary_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=temporary_runtime,
        )
        source_id = f"{self._testMethodName}:temporary-answer"
        self.route_classification = "health"

        answered = temporary_plugin.receive_weixin(
            self._message(
                CountingBody("请临时解释一下，不要保存为健康记录"),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T11:10:00+08:00",
                received_at="2026-08-24T11:10:01+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (answered.status, answered.reason_code),
            ("accepted", "daily-turn-finalized"),
        )
        self.assertIs(type(answered.meta), DailyTurnMeta)
        self.assertTrue(answered.meta.turn_result.owner_reply)
        after = self.plugin.daily_state(peer_id=_PEER_ID)
        self.assertEqual(after.evidence_cards, before.evidence_cards)
        self.assertEqual(after.portrait_topics, before.portrait_topics)
        self.assertEqual(
            after.evidence_applicability_changes,
            before.evidence_applicability_changes,
        )
        receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "committed")

    def test_114_a2_c10_recording_stop_preserves_owner_correction_right(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")

        self._build_and_commit_correction_stage()
        correction = self._owner_request(
            settings_mutation=False,
            expected_settings_version=2,
            command_suffix=":correction",
        )
        self.assertEqual(self._prepare(correction).status, "accepted")
        self.assertEqual(self._commit(correction).status, "accepted")
        self.assertEqual(self._finalize(correction).status, "accepted")

        current = tuple(
            item
            for item in self.plugin.managed_rights_read_current(peer_id=_PEER_ID)
            if item.object_ref == self.baseline_card.evidence_id
        )
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].version, 2)
        receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "committed")

    def test_114_a2_c11_recording_stop_never_persists_body_on_planner_failure(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        failing_runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=_FailingStoppedRecordingExecutor(),
            clock=lambda: datetime(2026, 8, 24, 3, 5, tzinfo=timezone.utc),
        )
        failing_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=failing_runtime,
        )
        source_id = f"{self._testMethodName}:planner-failure"
        self.route_classification = "health"

        failed = failing_plugin.receive_weixin(
            self._message(
                CountingBody("停止记录后这段敏感正文不得落入持久库"),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T11:20:00+08:00",
                received_at="2026-08-24T11:20:01+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (failed.status, failed.reason_code),
            ("unavailable", "daily-turn-candidate-invalid"),
        )
        receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "recording-excluded")

        uri_case = self._testMethodName.replace("_", "-")
        reopened = EncryptedStateStore(
            f"file:{uri_case}?mode=memory&cache=shared",
            StaticKeyProvider(b"u" * 32, key_id="ticket114-owner-state-key"),
        )
        try:
            restarted_receipt = reopened.source_receipt(source_id)
            self.assertIsNotNone(restarted_receipt)
            assert restarted_receipt is not None
            self.assertIsNone(restarted_receipt.envelope.body)
            self.assertEqual(
                restarted_receipt.managed_cursor_state,
                "recording-excluded",
            )
        finally:
            reopened.close()

    def test_114_a2_c12_exact_redelivery_rehydrates_only_transient_stopped_body(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        source_id = f"{self._testMethodName}:retry-after-restart"
        generation = self.head.read().head.generation
        message_fields = {
            "causal_id": source_id,
            "generation": generation,
            "requested_capability": "health-steward",
            "message_id": f"wx:{source_id}",
            "protocol_timestamp": "2026-08-24T11:30:00+08:00",
            "received_at": "2026-08-24T11:30:01+08:00",
            "native_cursor": f"cursor:{source_id}",
        }
        self.route_classification = "health"
        failing_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=_FailingStoppedRecordingExecutor(),
                clock=lambda: datetime(2026, 8, 24, 3, 10, tzinfo=timezone.utc),
            ),
        )
        failed = failing_plugin.receive_weixin(
            self._message(
                CountingBody("同一停止记录消息重投时只能短暂回到内存"),
                **message_fields,
            ),
            peer_id=_PEER_ID,
        )
        self.assertEqual(
            (failed.status, failed.reason_code),
            ("unavailable", "daily-turn-candidate-invalid"),
        )
        excluded = self.store.source_receipt(source_id)
        self.assertIsNotNone(excluded)
        assert excluded is not None
        self.assertIsNone(excluded.envelope.body)
        self.assertEqual(
            excluded.managed_cursor_state,
            "recording-excluded",
        )

        self.assertTrue(self.core.close().complete)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
            daily_skill_verifier=self.daily_attestor,
            daily_skill_bundle=self.daily_bundle,
            owner_settings_clock=lambda: self.owner_clock_value,
        )
        retry_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=_SyntheticTemporaryAnswerExecutor(),
                clock=lambda: datetime(2026, 8, 24, 3, 11, tzinfo=timezone.utc),
            ),
        )

        retried = retry_plugin.receive_weixin(
            self._message(
                CountingBody("同一停止记录消息重投时只能短暂回到内存"),
                **message_fields,
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (retried.status, retried.reason_code),
            ("accepted", "daily-turn-finalized"),
        )
        final_receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(final_receipt)
        assert final_receipt is not None
        self.assertIsNone(final_receipt.envelope.body)
        self.assertEqual(final_receipt.managed_cursor_state, "committed")

    def test_114_a2_c13_delayed_first_delivery_from_exclusion_is_not_backfilled(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        self.owner_clock_value = datetime(
            2026,
            8,
            24,
            4,
            0,
            tzinfo=timezone.utc,
        )
        resume = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="resume",
            command_suffix=":resume",
            expected_settings_version=2,
        )
        self.assertEqual(self._prepare(resume).status, "accepted")
        self.assertEqual(self._commit(resume).status, "accepted")
        self.assertEqual(self._finalize(resume).status, "accepted")
        before = self.plugin.daily_state(peer_id=_PEER_ID)
        source_id = f"{self._testMethodName}:delayed-first-delivery"
        self.route_classification = "health"

        rejected = self.plugin.receive_weixin(
            self._message(
                CountingBody("停录区间产生的延迟消息不得恢复后倒填"),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T11:00:00+08:00",
                received_at="2026-08-24T12:30:00+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "health-recording-stopped"),
        )
        self.assertEqual(self.plugin.daily_state(peer_id=_PEER_ID), before)
        self.assertIsNone(self.store.daily_turn(source_id))
        receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "recording-excluded")

    def test_114_a2_c14_recording_excluded_native_alias_is_body_free_from_creation(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        root_id = f"{self._testMethodName}:excluded-root"
        message_id = f"wx:{self._testMethodName}:native-event"
        body = "SENSITIVE-STOPPED-BODY"
        self.route_classification = "health"
        failing_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=_FailingStoppedRecordingExecutor(),
                clock=lambda: datetime(2026, 8, 24, 3, 10, tzinfo=timezone.utc),
            ),
        )
        failed = failing_plugin.receive_weixin(
            self._message(
                CountingBody(body),
                causal_id=root_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=message_id,
                protocol_timestamp="2026-08-24T10:00:00+08:00",
                received_at="2026-08-24T11:20:00+08:00",
                native_cursor=f"cursor:{root_id}",
            ),
            peer_id=_PEER_ID,
        )
        self.assertEqual(
            (failed.status, failed.reason_code),
            ("unavailable", "daily-turn-candidate-invalid"),
        )
        self.owner_clock_value = datetime(
            2026,
            8,
            24,
            4,
            0,
            tzinfo=timezone.utc,
        )
        resume = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="resume",
            command_suffix=":resume",
            expected_settings_version=2,
        )
        self.assertEqual(self._prepare(resume).status, "accepted")
        self.assertEqual(self._commit(resume).status, "accepted")
        self.assertEqual(self._finalize(resume).status, "accepted")
        alias_id = f"{self._testMethodName}:excluded-alias"

        replayed = self.plugin.receive_weixin(
            self._message(
                CountingBody(body),
                causal_id=alias_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=message_id,
                protocol_timestamp="2026-08-24T10:00:00+08:00",
                received_at="2026-08-24T12:30:00+08:00",
                native_cursor=f"cursor:{alias_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (replayed.status, replayed.reason_code),
            ("unavailable", "daily-source-native-replay-pending"),
        )
        alias = self.store.source_receipt(alias_id)
        self.assertIsNotNone(alias)
        assert alias is not None
        self.assertEqual(alias.relation, "possible-replay")
        self.assertEqual(alias.business_source_causal_id, root_id)
        self.assertIsNone(alias.envelope.body)
        self.assertEqual(alias.managed_cursor_state, "recording-excluded")

    def test_114_a2_c15_failed_stopped_planner_releases_transient_body(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        source_id = f"{self._testMethodName}:planner-failure"
        self.route_classification = "health"
        failing_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=_FailingStoppedRecordingExecutor(),
                clock=lambda: datetime(2026, 8, 24, 3, 10, tzinfo=timezone.utc),
            ),
        )

        failed = failing_plugin.receive_weixin(
            self._message(
                CountingBody("失败路径返回前必须释放内存中的停录正文"),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T11:30:00+08:00",
                received_at="2026-08-24T11:30:01+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (failed.status, failed.reason_code),
            ("unavailable", "daily-turn-candidate-invalid"),
        )
        self.assertNotIn(source_id, self.core._recording_excluded_sources)
        receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "recording-excluded")

    def test_114_a2_c16_stopped_prepare_rejection_receipt_is_body_free(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        source_id = f"{self._testMethodName}:stopped-candidate"
        self.route_classification = "health"

        rejected = self.plugin.receive_weixin(
            self._message(
                CountingBody("停录期间形成的候选正文不得复制进命令回执"),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T11:40:00+08:00",
                received_at="2026-08-24T11:40:01+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "health-recording-stopped"),
        )
        prepare_causal_id = HealthPlugin._daily_turn_causal_id(
            "evidence-prepare",
            source_id,
        )
        stored = self._stored_command_receipt(prepare_causal_id)
        self.assertEqual(
            set(stored),
            {"kind", "command_digest", "response"},
        )
        self.assertEqual(stored["kind"], "command-digest-v1")
        self.assertNotIn("draft", repr(stored))
        self.assertNotIn("evidence_cards", repr(stored))
        self.assertNotIn("portrait_topics", repr(stored))

    def test_114_a2_c17_missing_event_time_after_exclusion_fails_closed(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        self.owner_clock_value = datetime(
            2026,
            8,
            24,
            4,
            0,
            tzinfo=timezone.utc,
        )
        resume = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="resume",
            command_suffix=":resume",
            expected_settings_version=2,
        )
        self.assertEqual(self._prepare(resume).status, "accepted")
        self.assertEqual(self._commit(resume).status, "accepted")
        self.assertEqual(self._finalize(resume).status, "accepted")
        before = self.plugin.daily_state(peer_id=_PEER_ID)
        source_id = f"{self._testMethodName}:unknown-event-time"
        self.route_classification = "health"

        rejected = self.plugin.receive_weixin(
            self._message(
                CountingBody("没有事件时间，无法证明不是停录期积压"),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp=None,
                received_at="2026-08-24T12:30:00+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "health-recording-stopped"),
        )
        self.assertEqual(self.plugin.daily_state(peer_id=_PEER_ID), before)
        receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "recording-excluded")

    def test_114_a2_c18_missing_runtime_releases_transient_body(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        source_id = f"{self._testMethodName}:no-runtime"
        self.route_classification = "health"
        no_runtime_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=None,
        )

        unavailable = no_runtime_plugin.receive_weixin(
            self._message(
                CountingBody("NO-RUNTIME-SECRET"),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T11:50:00+08:00",
                received_at="2026-08-24T11:50:01+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (unavailable.status, unavailable.reason_code),
            ("unavailable", "daily-turn-runtime-unavailable"),
        )
        self.assertNotIn(source_id, self.core._recording_excluded_sources)
        receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "recording-excluded")

    def test_114_a2_c19_status_failure_releases_transient_body(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        source_id = f"{self._testMethodName}:status-failure"
        self.route_classification = "health"

        with patch.object(
            self.core,
            "daily_turn_status",
            side_effect=AuthorityValidationError("synthetic status failure"),
        ):
            failed = self.plugin.receive_weixin(
                self._message(
                    CountingBody("STATUS-FAILURE-SECRET"),
                    causal_id=source_id,
                    generation=self.head.read().head.generation,
                    requested_capability="health-steward",
                    message_id=f"wx:{source_id}",
                    protocol_timestamp="2026-08-24T11:55:00+08:00",
                    received_at="2026-08-24T11:55:01+08:00",
                    native_cursor=f"cursor:{source_id}",
                ),
                peer_id=_PEER_ID,
            )

        self.assertEqual(
            (failed.status, failed.reason_code),
            ("rejected", "invalid-weixin-source"),
        )
        self.assertNotIn(source_id, self.core._recording_excluded_sources)
        receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "recording-excluded")

    def test_114_a2_c20_admission_commit_rollback_releases_transient_body(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        source_id = f"{self._testMethodName}:receipt-rollback"
        self.route_classification = "health"
        self.store.fail_commit_after_receipt = True

        failed = self.plugin.receive_weixin(
            self._message(
                CountingBody("RECEIPT-COMMIT-FAILURE-SECRET"),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T11:56:00+08:00",
                received_at="2026-08-24T11:56:01+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )
        self.store.clear_commit_failure()

        self.assertEqual(
            (failed.status, failed.reason_code),
            ("unavailable", "health-state-unavailable"),
        )
        self.assertNotIn(source_id, self.core._recording_excluded_sources)
        self.assertIsNone(self.store.source_receipt(source_id))

    def test_114_a2_c21_temporary_completion_failure_releases_transient_body(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        source_id = f"{self._testMethodName}:temporary-complete-failure"
        message_fields = {
            "causal_id": source_id,
            "generation": self.head.read().head.generation,
            "requested_capability": "health-steward",
            "message_id": f"wx:{source_id}",
            "protocol_timestamp": "2026-08-24T11:57:00+08:00",
            "received_at": "2026-08-24T11:57:01+08:00",
            "native_cursor": f"cursor:{source_id}",
        }
        self.route_classification = "health"
        failing_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=_FailingTemporaryCompletionExecutor(),
                clock=lambda: datetime(2026, 8, 24, 3, 57, tzinfo=timezone.utc),
            ),
        )

        failed = failing_plugin.receive_weixin(
            self._message(
                CountingBody("TEMPORARY-COMPLETE-FAILURE-SECRET"),
                **message_fields,
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (failed.status, failed.reason_code),
            ("unavailable", "daily-turn-candidate-invalid"),
        )
        turn = self.store.daily_turn(source_id)
        self.assertIsNotNone(turn)
        assert turn is not None
        self.assertEqual(turn.phase, "evidence-finalized")
        self.assertNotIn(source_id, self.core._recording_excluded_sources)
        excluded = self.store.source_receipt(source_id)
        self.assertIsNotNone(excluded)
        assert excluded is not None
        self.assertIsNone(excluded.envelope.body)
        self.assertEqual(excluded.managed_cursor_state, "recording-excluded")

        retry_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=_SyntheticTemporaryAnswerExecutor(),
                clock=lambda: datetime(2026, 8, 24, 3, 58, tzinfo=timezone.utc),
            ),
        )
        retried = retry_plugin.receive_weixin(
            self._message(
                CountingBody("TEMPORARY-COMPLETE-FAILURE-SECRET"),
                **message_fields,
            ),
            peer_id=_PEER_ID,
        )
        self.assertEqual(
            (retried.status, retried.reason_code),
            ("accepted", "daily-turn-finalized"),
        )
        committed = self.store.source_receipt(source_id)
        self.assertIsNotNone(committed)
        assert committed is not None
        self.assertIsNone(committed.envelope.body)
        self.assertEqual(committed.managed_cursor_state, "committed")

    def test_114_a2_c22_correction_cas_owns_transient_body_until_finalize(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        self._build_and_commit_correction_stage()
        self.assertIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )
        correction = self._owner_request(
            settings_mutation=False,
            expected_settings_version=2,
            command_suffix=":correction",
        )

        prepared = self._prepare(correction)

        self.assertEqual(
            (prepared.status, prepared.reason_code),
            ("accepted", "owner-mutation-prepared"),
        )
        daily_turn = self.store.daily_turn(self.correction_source_id)
        self.assertIsNotNone(daily_turn)
        assert daily_turn is not None
        self.assertEqual(daily_turn.phase, "prepared")
        self.assertIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )
        receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "recording-excluded")
        owner_receipt = self._stored_command_receipt(
            correction.context.causal_id
        )
        self.assertEqual(
            set(owner_receipt),
            {"kind", "command_digest", "response"},
        )
        self.assertEqual(owner_receipt["kind"], "command-digest-v1")

        committed = self._commit(correction)

        self.assertEqual(
            (committed.status, committed.reason_code),
            ("accepted", "current-head-advanced"),
        )
        self.assertIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )
        committed_receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(committed_receipt)
        assert committed_receipt is not None
        self.assertIsNone(committed_receipt.envelope.body)
        self.assertEqual(
            committed_receipt.managed_cursor_state,
            "recording-excluded",
        )

        finalized = self._finalize(correction)

        self.assertEqual(
            (finalized.status, finalized.reason_code),
            ("accepted", "revision-finalized"),
        )
        self.assertNotIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )
        final_receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(final_receipt)
        assert final_receipt is not None
        self.assertIsNone(final_receipt.envelope.body)
        self.assertEqual(final_receipt.managed_cursor_state, "committed")

    def test_114_a2_c23_recording_stop_rejects_echoing_temporary_draft(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        source_id = f"{self._testMethodName}:echo-attempt"
        secret = "SENSITIVE-OWNER-HEALTH-CONTENT"
        executor = _EchoingStoppedTemporaryExecutor(fail_resolution=True)
        echoing_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda: datetime(2026, 8, 24, 3, 59, tzinfo=timezone.utc),
            ),
        )
        self.route_classification = "health"

        rejected = echoing_plugin.receive_weixin(
            self._message(
                CountingBody(secret),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T11:59:00+08:00",
                received_at="2026-08-24T11:59:01+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "health-recording-stopped"),
        )
        self.assertIsNotNone(executor.echoed_text)
        assert executor.echoed_text is not None
        self.assertIsNone(self.store.daily_turn(source_id))
        self.assertIsNone(self.core.daily_turn_status(source_id))
        self.assertNotIn(source_id, self.core._recording_excluded_sources)
        source_receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(source_receipt)
        assert source_receipt is not None
        self.assertIsNone(source_receipt.envelope.body)
        self.assertNotIn(secret, repr(source_receipt))
        self.assertNotIn(executor.echoed_text, repr(source_receipt))
        prepare_receipt = self._stored_command_receipt(
            HealthPlugin._daily_turn_causal_id(
                "evidence-prepare",
                source_id,
            )
        )
        self.assertEqual(
            set(prepare_receipt),
            {"kind", "command_digest", "response"},
        )
        self.assertNotIn(secret, repr(prepare_receipt))
        self.assertNotIn(executor.echoed_text, repr(prepare_receipt))

    def test_114_a2_c24_recording_stop_rejects_echoing_temporary_terminal(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        source_id = f"{self._testMethodName}:terminal-echo-attempt"
        secret = "FINALIZED-OWNER-HEALTH-CONTENT"
        executor = _TerminalEchoingStoppedTemporaryExecutor(
            before_inquiry_result=lambda: self.head.set_failure(
                FailureMode.CONFLICT,
                operation="advance",
            )
        )
        echoing_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=executor,
                clock=lambda: datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc),
            ),
        )
        self.route_classification = "health"

        rejected = echoing_plugin.receive_weixin(
            self._message(
                CountingBody(secret),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T12:00:00+08:00",
                received_at="2026-08-24T12:00:01+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )
        self.head.clear_failure()

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "health-recording-stopped"),
        )
        self.assertIsNotNone(executor.echoed_text)
        assert executor.echoed_text is not None
        daily = self.store.daily_turn(source_id)
        self.assertIsNotNone(daily)
        assert daily is not None
        self.assertEqual(daily.phase, "evidence-finalized")
        daily_status = self.core.daily_turn_status(source_id)
        self.assertIsNotNone(daily_status)
        assert daily_status is not None
        self.assertEqual(daily_status.phase, "evidence-finalized")
        self.assertIsNone(daily_status.terminal)
        self.assertEqual(daily_status.draft.purpose, "temporary-owner-answer")
        self.assertNotIn(secret, repr(daily_status.draft))
        self.assertNotIn(executor.echoed_text, repr(daily_status.draft))
        receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertEqual(receipt.managed_cursor_state, "recording-excluded")
        self.assertNotIn(secret, repr(receipt))
        self.assertNotIn(executor.echoed_text, repr(receipt))
        complete_prepare_receipt = self._stored_command_receipt(
            HealthPlugin._daily_turn_causal_id(
                "complete-prepare",
                source_id,
            )
        )
        self.assertEqual(
            set(complete_prepare_receipt),
            {"kind", "command_digest", "response"},
        )
        self.assertNotIn(secret, repr(complete_prepare_receipt))
        self.assertNotIn(executor.echoed_text, repr(complete_prepare_receipt))

    def test_114_a2_c25_recording_stop_rejects_mixed_correction_scope(self) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        before = self.plugin.daily_state(peer_id=_PEER_ID)
        pending = self.plugin.managed_correction_draft(
            target_ref=rights.ManagedObjectReference(
                object_ref=self.baseline_card.evidence_id,
                installation_id=_INSTALLATION_ID,
                version=1,
            ),
            correction_id=f"correction:{self._testMethodName}",
            reason="主人更正已记录的睡眠体验",
            corrected_at_utc=_REQUESTED_AT,
            replacement_claim=self._replacement_claim(),
            correction_source_refs=(f"source:{self.correction_source_id}",),
            affected_object_refs=(f"portrait-topic:{_CORRECTION_TOPIC}",),
            disposition_requests=("rejudge",),
            peer_id=_PEER_ID,
        )
        unauthorized = replace(
            self._replacement_claim(),
            content="UNAUTHORIZED-EXTRA-HEALTH-CONTENT",
            occurred_at="2026-08-24",
            applicable_period="2026-08-24-day",
            proves=("UNAUTHORIZED-EXTRA-HEALTH-CONTENT",),
            does_not_prove=("本陈述获主人纠正命令授权",),
        )
        mixed_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=_SyntheticCorrectionTurnExecutor(
                    pending.maintenance_request,
                    extra_atomic_claims=(unauthorized,),
                ),
                clock=lambda: datetime(2026, 8, 24, 4, 1, tzinfo=timezone.utc),
            ),
        )
        self.route_classification = "health"

        rejected = mixed_plugin.receive_weixin(
            self._message(
                CountingBody("请更正昨晚记录，但不得附带新增陈述"),
                causal_id=self.correction_source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{self.correction_source_id}",
                protocol_timestamp="2026-08-24T12:01:00+08:00",
                received_at="2026-08-24T12:01:01+08:00",
                native_cursor=f"cursor:{self.correction_source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "health-recording-stopped"),
        )
        self.assertEqual(self.plugin.daily_state(peer_id=_PEER_ID), before)
        self.assertIsNone(self.store.daily_turn(self.correction_source_id))
        self.assertIsNone(
            self.core.daily_turn_status(self.correction_source_id)
        )
        receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertNotIn(unauthorized.content, repr(receipt))

    def test_114_a2_c26_recording_stop_rejects_echoing_correction_completion(
        self,
    ) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        self._build_and_commit_correction_stage()
        secret = "CORRECTION-COMPLETION-SOURCE-SECRET-7529"
        self.assertIsNotNone(self.correction_stage)
        self.assertIsNotNone(self.complete_draft)
        assert self.correction_stage is not None
        assert self.complete_draft is not None
        self.assertTrue(
            self.correction_stage.recording_excluded_persistence_safe()
        )
        self.assertNotIn(secret, repr(self.correction_stage.to_storage()))
        self.assertIn(secret, repr(self.complete_draft.to_storage()))
        request = self._owner_request(
            settings_mutation=False,
            expected_settings_version=2,
        )
        before = self._business_snapshot()
        writes_before = self.store.owner_prepare_write_count

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "health-recording-stopped"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, writes_before)
        self.assertIsNone(self._status(request))
        self.assertEqual(self._business_snapshot(), before)
        durable_daily = self.store.daily_turn(self.correction_source_id)
        self.assertIsNotNone(durable_daily)
        assert durable_daily is not None
        self.assertEqual(durable_daily.phase, "evidence-finalized")
        self.assertNotIn(secret, repr(durable_daily))
        source_receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(source_receipt)
        assert source_receipt is not None
        self.assertIsNone(source_receipt.envelope.body)
        self.assertNotIn(secret, repr(source_receipt))
        prepare_receipt = self._stored_command_receipt(
            request.context.causal_id
        )
        self.assertEqual(
            set(prepare_receipt),
            {"kind", "command_digest", "response"},
        )
        self.assertNotIn(secret, repr(prepare_receipt))
        self.assertNotIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )

    def test_114_a2_c27_recording_stop_rejects_unbound_correction_stage(
        self,
    ) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        secret = "UNAUTHORIZED-STOPPED-SOURCE-BODY-88421"
        forged_claim = replace(
            self._replacement_claim(),
            content=secret,
            purpose=secret,
            limitations=(secret,),
            proves=(secret,),
            does_not_prove=(secret,),
        )
        forged_maintenance = EvidenceMaintenanceRequest(
            action="correct",
            target_evidence_ids=(self.baseline_card.evidence_id,),
            reason=secret,
            purpose=secret,
            replacement_claim=forged_claim,
        )
        source_id = f"{self._testMethodName}:unbound-correction"
        unbound_plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=DailySkillRuntime(
                self.daily_bundle,
                self.daily_attestor,
                executor=_SyntheticCorrectionTurnExecutor(
                    forged_maintenance
                ),
                clock=lambda: datetime(
                    2026,
                    8,
                    24,
                    4,
                    2,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        self.route_classification = "health"

        rejected = unbound_plugin.receive_weixin(
            self._message(
                CountingBody(secret),
                causal_id=source_id,
                generation=self.head.read().head.generation,
                requested_capability="health-steward",
                message_id=f"wx:{source_id}",
                protocol_timestamp="2026-08-24T12:02:00+08:00",
                received_at="2026-08-24T12:02:01+08:00",
                native_cursor=f"cursor:{source_id}",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "health-recording-stopped"),
        )
        self.assertIsNone(self.store.daily_turn(source_id))
        self.assertIsNone(self.core.daily_turn_status(source_id))
        self.assertNotIn(source_id, self.core._recording_excluded_sources)
        receipt = self.store.source_receipt(source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertNotIn(secret, repr(receipt))
        prepare_receipt = self._stored_command_receipt(
            HealthPlugin._daily_turn_causal_id(
                "evidence-prepare",
                source_id,
            )
        )
        self.assertEqual(
            set(prepare_receipt),
            {"kind", "command_digest", "response"},
        )
        self.assertNotIn(secret, repr(prepare_receipt))

    def test_114_a2_c28_rejected_owner_prepare_releases_correction_plaintext(
        self,
    ) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        self._build_and_commit_correction_stage()
        self.assertIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )
        request = self._owner_request(
            settings_mutation=False,
            expected_settings_version=99,
        )

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-settings-version-mismatch"),
        )
        self.assertIsNone(self._status(request))
        self.assertNotIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )
        durable_daily = self.store.daily_turn(self.correction_source_id)
        self.assertIsNotNone(durable_daily)
        assert durable_daily is not None
        self.assertEqual(durable_daily.phase, "evidence-finalized")
        receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        prepare_receipt = self._stored_command_receipt(
            request.context.causal_id
        )
        self.assertEqual(
            set(prepare_receipt),
            {"kind", "command_digest", "response"},
        )

    def test_114_a2_c29_prepared_correction_has_one_durable_body_copy(
        self,
    ) -> None:
        request = self._owner_request(settings_mutation=False)
        replacement_body = self._replacement_claim().content

        prepared = self._prepare(request)

        self.assertEqual(
            (prepared.status, prepared.reason_code),
            ("accepted", "owner-mutation-prepared"),
        )
        daily = self.store.daily_turn(self.correction_source_id)
        self.assertIsNotNone(daily)
        assert daily is not None
        self.assertEqual(daily.phase, "prepared")
        self.assertIn(replacement_body, repr(daily))
        row = self.store._execute(
            "SELECT command_id, record_id, phase, nonce, ciphertext "
            "FROM owner_mutations_v1 WHERE command_id = ?",
            (request.context.command_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        command_id, record_id, phase, nonce, ciphertext = row
        owner_wire = self.store._open(
            f"owner-mutation:{command_id}:{record_id}:{phase}",
            nonce,
            ciphertext,
        )
        self.assertNotIn(replacement_body, repr(owner_wire))
        self.assertNotIn("replacement_claim", repr(owner_wire))
        self.assertNotIn("daily_turn_draft", repr(owner_wire))
        self.assertIn("daily_turn_ref", repr(owner_wire))

    def test_114_a2_c30_stopped_correction_handoff_recovers_after_restart(
        self,
    ) -> None:
        stop = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":stop",
        )
        self.assertEqual(self._prepare(stop).status, "accepted")
        self.assertEqual(self._commit(stop).status, "accepted")
        self.assertEqual(self._finalize(stop).status, "accepted")
        self._build_and_commit_correction_stage()
        pending = self.pending_correction
        self.assertIsNotNone(pending)
        assert pending is not None
        runtime = DailySkillRuntime(
            self.daily_bundle,
            self.daily_attestor,
            executor=_SyntheticCorrectionTurnExecutor(
                pending.maintenance_request
            ),
            clock=lambda: datetime(
                2026,
                8,
                24,
                2,
                1,
                tzinfo=timezone.utc,
            ),
        )
        restarted = self._restart_plugin(daily_skill_runtime=runtime)
        recovered_pending = restarted.managed_correction_draft(
            target_ref=pending.target_ref,
            correction_id=pending.revision.correction_id,
            reason=pending.revision.reason,
            corrected_at_utc=pending.revision.corrected_at_utc,
            replacement_claim=self._replacement_claim(),
            correction_source_refs=pending.revision.source_refs,
            affected_object_refs=pending.revision.affected_object_refs,
            disposition_requests=pending.revision.disposition_requests,
            peer_id=_PEER_ID,
        )
        receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        envelope = receipt.envelope
        self.assertIsNone(envelope.body)
        redelivery = RawWeixinMessage(
            causal_id=envelope.causal_id,
            generation=envelope.generation,
            channel=envelope.channel,
            partner_id=envelope.partner_id,
            sender_id=envelope.sender_id,
            conversation_id=envelope.conversation_id,
            chat_type=envelope.chat_type,
            entrypoint=envelope.entrypoint,
            requested_capability=envelope.requested_capability,
            message_id=envelope.message_id,
            protocol_timestamp=envelope.protocol_timestamp,
            received_at=envelope.received_at,
            native_cursor=envelope.native_cursor,
            body=CountingBody("请更正昨晚的睡眠记录"),
        )

        snapshot = self.head.read().head
        context = OwnerMutationContext(
            command_id=f"owner-mutation:{self._testMethodName}",
            causal_id=f"{self._testMethodName}:owner-command-source",
            actor_kind="current_owner",
            owner_id=_OWNER_ID,
            installation_id=_INSTALLATION_ID,
            permissions=("health_data.correct",),
            context_ref=f"managed-context:{self._testMethodName}",
            current_head_generation=snapshot.generation,
            writer_fence=snapshot.writer_fence,
        )
        paused = restarted.prepare_owner_correction(
            pending=recovered_pending,
            source_message=redelivery,
            context=context,
            expected_settings_version=2,
            requested_at_utc=_REQUESTED_AT,
            peer_id=_PEER_ID,
        )
        self.assertEqual(
            (paused.status, paused.reason_code),
            ("unavailable", "daily-turn-candidate-invalid"),
        )
        self.assertIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )
        self.assertIn(
            self.correction_source_id,
            self.core._pending_correction_authorizations,
        )
        prepared = restarted.prepare_owner_correction(
            pending=recovered_pending,
            source_message=redelivery,
            context=context,
            expected_settings_version=2,
            requested_at_utc=_REQUESTED_AT,
            peer_id=_PEER_ID,
        )
        self.assertEqual(
            (prepared.status, prepared.reason_code),
            ("accepted", "owner-mutation-prepared"),
        )
        committed = restarted.commit_owner_mutation(
            context.command_id,
            peer_id=_PEER_ID,
        )
        self.assertEqual(committed.status, "accepted", committed)
        finalized = restarted.finalize_owner_mutation(
            context.command_id,
            peer_id=_PEER_ID,
        )
        self.assertEqual(finalized.status, "accepted", finalized)

    def test_114_a2_c31_public_correction_handoff_rejects_wrong_body(
        self,
    ) -> None:
        restarted, pending, redelivery, context = (
            self._restarted_stopped_correction_submission()
        )
        wrong_marker = "WRONG-CORRECTION-BODY-MUST-NOT-PERSIST-9142"
        wrong = replace(
            redelivery,
            body=CountingBody(wrong_marker),
        )

        rejected = restarted.prepare_owner_correction(
            pending=pending,
            source_message=wrong,
            context=context,
            expected_settings_version=2,
            requested_at_utc=_REQUESTED_AT,
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "causal-id-conflict"),
        )
        self.assertIsNone(self.store.owner_mutation(context.command_id))
        daily = self.store.daily_turn(self.correction_source_id)
        self.assertIsNotNone(daily)
        assert daily is not None
        self.assertEqual(daily.phase, "evidence-finalized")
        self.assertNotIn(wrong_marker, repr(daily))
        receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)
        self.assertNotIn(wrong_marker, repr(receipt))
        self.assertNotIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )

    def test_114_a2_c32_public_correction_handoff_requires_reregistration(
        self,
    ) -> None:
        restarted, pending, redelivery, context = (
            self._restarted_stopped_correction_submission(
                reregister=False,
            )
        )

        rejected = restarted.prepare_owner_correction(
            pending=pending,
            source_message=redelivery,
            context=context,
            expected_settings_version=2,
            requested_at_utc=_REQUESTED_AT,
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "health-recording-stopped"),
        )
        self.assertIsNone(self.store.owner_mutation(context.command_id))
        daily = self.store.daily_turn(self.correction_source_id)
        self.assertIsNotNone(daily)
        assert daily is not None
        self.assertEqual(daily.phase, "evidence-finalized")
        self.assertNotIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )
        self.assertNotIn(
            self.correction_source_id,
            self.core._pending_correction_authorizations,
        )

    def test_114_a2_c33_public_correction_handoff_rejects_forged_scope(
        self,
    ) -> None:
        restarted, pending, redelivery, context = (
            self._restarted_stopped_correction_submission()
        )
        forged = replace(
            pending,
            revision=replace(
                pending.revision,
                affected_object_refs=(
                    "portrait-topic:physical-function-and-experience/unrelated",
                ),
            ),
            previous_value=next(
                item.to_wire()["value"]
                for item in restarted.managed_rights_read_current(
                    peer_id=_PEER_ID
                )
                if item.object_ref == pending.target_ref.object_ref
            ),
        )

        rejected = restarted.prepare_owner_correction(
            pending=forged,
            source_message=redelivery,
            context=context,
            expected_settings_version=2,
            requested_at_utc=_REQUESTED_AT,
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-correction-affected-scope-mismatch"),
        )
        self.assertIsNone(self.store.owner_mutation(context.command_id))
        self.assertNotIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )
        self.assertNotIn(
            self.correction_source_id,
            self.core._pending_correction_authorizations,
        )

    def test_114_a2_c34_public_correction_handoff_cleans_up_owner_rejection(
        self,
    ) -> None:
        restarted, pending, redelivery, context = (
            self._restarted_stopped_correction_submission()
        )

        rejected = restarted.prepare_owner_correction(
            pending=pending,
            source_message=redelivery,
            context=context,
            expected_settings_version=99,
            requested_at_utc=_REQUESTED_AT,
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-settings-version-mismatch"),
        )
        self.assertIsNone(self.store.owner_mutation(context.command_id))
        self.assertNotIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )
        self.assertNotIn(
            self.correction_source_id,
            self.core._pending_correction_authorizations,
        )

    def test_114_a3_c20_finalized_ticket112_correction_revision_is_visible(self) -> None:
        request = self._owner_request(settings_mutation=False)
        before = self.store.daily_state()
        self.assertEqual(self._prepare(request).status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        self.assertEqual(self.store.daily_state(), before)

        self.assertEqual(self._finalize(request).status, "accepted")

        current_objects = self.plugin.managed_rights_read_current(peer_id=_PEER_ID)
        logical = tuple(
            item
            for item in current_objects
            if item.object_ref == self.baseline_card.evidence_id
        )
        self.assertEqual(len(logical), 1)
        self.assertEqual(logical[0].version, 2)
        self.assertTrue(logical[0].current)
        self.assertNotEqual(
            logical[0].evidence_refs,
            (self.baseline_card.evidence_id,),
        )
        self.assertEqual(
            logical[0].installation_id,
            _INSTALLATION_ID,
        )

    def test_114_a3_c21_forged_pending_metadata_is_rebound_to_current_projection(self) -> None:
        pending = self.pending_correction
        self.assertIsNotNone(pending)
        assert pending is not None
        forged_version = pending.target_ref.version + 7
        self.pending_correction = replace(
            pending,
            target_ref=replace(
                pending.target_ref,
                version=forged_version,
            ),
            revision=replace(
                pending.revision,
                previous_version=forged_version,
                revision_version=forged_version + 1,
            ),
            previous_value={"forged": "caller supplied old value"},
        )
        request = self._owner_request(settings_mutation=False)
        before = self.store.daily_state()

        rejected = self._prepare(request)

        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(
            rejected.reason_code,
            "owner-correction-target-mismatch",
        )
        self.assertIsNone(self.store.owner_mutation(request.context.command_id))
        self.assertIsNone(self.store.record(request.record_id))
        self.assertEqual(self.store.daily_state(), before)

    def test_114_a9_c25_ticket111_contact_starts_without_execution_authority(self) -> None:
        current = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        contact = current.support_contact

        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.identity_label, "trusted-family-member")
        self.assertEqual(contact.method_kind, "weixin")
        self.assertEqual(contact.method_value, "trusted-family-member")
        self.assertEqual(contact.purpose, "emergency-support")
        self.assertEqual(contact.version, 1)
        self.assertEqual(contact.route_generation, 1)
        self.assertEqual(contact.alert_authority_status, "invalidated")
        self.assertIsNone(contact.alert_approval_id)
        self.assertIsNone(contact.alert_authority_binding)
        self.assertEqual(contact.correction_authority_status, "invalidated")
        self.assertIsNone(contact.correction_authority_id)
        self.assertIsNone(contact.correction_authority_binding)
        self.assertFalse(self.core.outbound_effects_allowed())

    def test_114_a9_c26_public_managed_read_configures_not_configured_contact(self) -> None:
        before = self.plugin.managed_owner_settings_read(peer_id=_PEER_ID)
        self.assertEqual(
            before["support_contact"],
            {"configuration_status": "not-configured"},
        )
        advances_before = self.head.advance_call_count
        configured = self._support_contact(version=1)
        command = self._support_contact_command(
            "configure",
            suffix="configure",
            contact=configured,
        )

        self._commit_settings_command(command, suffix="configure")

        after = self.plugin.managed_owner_settings_read(peer_id=_PEER_ID)
        contact = after["support_contact"]
        self.assertEqual(
            {
                key: contact[key]
                for key in (
                    "configuration_status",
                    "version",
                    "identity_label",
                    "method_kind",
                    "method_value",
                    "purpose",
                    "minimum_alert_fields",
                    "route_id",
                    "route_generation",
                    "alert_authority_status",
                    "correction_authority_status",
                )
            },
            {
                "configuration_status": "configured",
                "version": 1,
                "identity_label": "主人可识别的可信联系人",
                "method_kind": "weixin_user",
                "method_value": "wxid_ticket114_contact",
                "purpose": "minimum urgent-help contact alert",
                "minimum_alert_fields": (
                    "owner_recognizable_name",
                    "event_time",
                    "fixed_urgent_help_request",
                ),
                "route_id": "weixin-ilink-partner",
                "route_generation": 1,
                "alert_authority_status": "invalidated",
                "correction_authority_status": "invalidated",
            },
        )
        self.assertEqual(self.head.advance_call_count, advances_before + 1)
        self.assertEqual(
            self.store._execute(
                "SELECT COUNT(*) FROM owner_mutations_v1"
            ).fetchone()[0],
            1,
        )

    def test_114_a9_c27_public_method_change_invalidates_and_reapproves_exactly(self) -> None:
        self._commit_settings_command(
            self._support_contact_command(
                "configure",
                suffix="configure",
                contact=self._support_contact(version=1),
            ),
            suffix="configure",
        )
        self._commit_settings_command(
            self._support_contact_command(
                "grant_alert_authority",
                suffix="grant-alert-old",
                authority_id="alert-approval:old-boundary",
                expected_contact_version=1,
                expected_route_id="weixin-ilink-partner",
                expected_route_generation=1,
            ),
            suffix="grant-alert-old",
        )
        self._commit_settings_command(
            self._support_contact_command(
                "grant_correction_authority",
                suffix="grant-correction-old",
                authority_id="correction-authority:old-boundary",
                expected_contact_version=2,
                expected_route_id="weixin-ilink-partner",
                expected_route_generation=1,
            ),
            suffix="grant-correction-old",
        )
        old_view = self.plugin.managed_owner_settings_read(peer_id=_PEER_ID)
        self.assertEqual(
            (
                old_view["support_contact"]["alert_authority_status"],
                old_view["support_contact"]["correction_authority_status"],
            ),
            ("approved", "approved"),
        )

        self._commit_settings_command(
            self._support_contact_command(
                "change_method",
                suffix="change-method",
                contact=self._support_contact(
                    version=4,
                    method_kind="telephone_e164",
                    method_value="+8613800138000",
                    disclosure_version="support-contact-disclosure-v2",
                ),
                expected_contact_version=3,
                expected_route_id="weixin-ilink-partner",
                expected_route_generation=1,
            ),
            suffix="change-method",
        )
        changed = self.plugin.managed_owner_settings_read(peer_id=_PEER_ID)
        self.assertEqual(
            (
                changed["support_contact"]["method_kind"],
                changed["support_contact"]["method_value"],
                changed["support_contact"]["alert_authority_status"],
                changed["support_contact"]["correction_authority_status"],
            ),
            (
                "telephone_e164",
                "+8613800138000",
                "invalidated",
                "invalidated",
            ),
        )

        self._commit_settings_command(
            self._support_contact_command(
                "grant_alert_authority",
                suffix="grant-alert-new",
                authority_id="alert-approval:new-boundary",
                expected_contact_version=4,
                expected_route_id="weixin-ilink-partner",
                expected_route_generation=1,
            ),
            suffix="grant-alert-new",
        )
        alert_only = self.plugin.managed_owner_settings_read(peer_id=_PEER_ID)
        self.assertEqual(
            (
                alert_only["support_contact"]["alert_authority_status"],
                alert_only["support_contact"]["correction_authority_status"],
            ),
            ("approved", "invalidated"),
        )

        self._commit_settings_command(
            self._support_contact_command(
                "grant_correction_authority",
                suffix="grant-correction-new",
                authority_id="correction-authority:new-boundary",
                expected_contact_version=5,
                expected_route_id="weixin-ilink-partner",
                expected_route_generation=1,
            ),
            suffix="grant-correction-new",
        )
        fully_reapproved = self.plugin.managed_owner_settings_read(
            peer_id=_PEER_ID
        )
        self.assertEqual(
            (
                fully_reapproved["support_contact"]["version"],
                fully_reapproved["support_contact"]["alert_authority_status"],
                fully_reapproved["support_contact"][
                    "correction_authority_status"
                ],
            ),
            (6, "approved", "approved"),
        )

    def test_114_a6_c01_prepare_failure_has_no_partial_result(self) -> None:
        request = self._owner_request()
        before = self._business_snapshot()
        self.store.fail_after_owner_prepare_write = True

        failed = self._prepare(request)

        self.assertEqual(failed.status, "unavailable")
        self.assertEqual(self.store.owner_prepare_write_count, 1)
        self.assertIsNone(self._status(request))
        self._assert_no_partial_result(before)

    def test_114_a6_c02_commit_failure_has_no_partial_result(self) -> None:
        request = self._owner_request()
        before = self._business_snapshot()
        prepared = self._prepare(request)
        self.assertEqual(prepared.status, "accepted")
        self.store.fail_commit_after_receipt = True

        failed = self._commit(request)
        self.store.clear_commit_failure()

        self.assertEqual(failed.status, "unavailable")
        self._assert_no_partial_result(before)

    def test_114_a6_c03_finalize_failure_has_no_partial_result(self) -> None:
        request = self._owner_request()
        before = self._business_snapshot()
        self.assertEqual(self._prepare(request).status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        self.store.fail_after_owner_finalize_write = True

        failed = self._finalize(request)

        self.assertEqual(failed.status, "unavailable")
        self.assertEqual(self.store.owner_finalize_write_count, 1)
        self._assert_no_partial_result(before)

    def test_114_a6_c04_cas_conflict_rolls_back(self) -> None:
        request = self._owner_request()
        before = self._business_snapshot()
        self.assertEqual(self._prepare(request).status, "accepted")
        generation_before = self.head.read().head.generation
        self.head.set_failure(FailureMode.CONFLICT, operation="advance")

        conflict = self._commit(request)
        self.head.clear_failure()

        self.assertEqual(conflict.status, "unavailable")
        self.assertEqual(self.head.read().head.generation, generation_before)
        self._assert_no_partial_result(before)

    def test_114_a6_c05_unknown_freezes_without_guessing(self) -> None:
        request = self._owner_request()
        before = self._business_snapshot()
        self.assertEqual(self._prepare(request).status, "accepted")
        self.head.set_failure(
            FailureMode.UNKNOWN_AFTER_ADVANCE,
            operation="advance",
        )

        unknown = self._commit(request)
        self.head.clear_failure()

        self.assertEqual(unknown.status, "unknown")
        owner_status = self._status(request)
        self.assertIsNotNone(owner_status)
        self.assertEqual(owner_status.phase, "unknown")
        frozen = self._finalize(request)
        self.assertEqual(frozen.status, "rejected")
        self.assertEqual(frozen.reason_code, "owner-mutation-not-committed")
        self._assert_no_partial_result(before)

    def test_114_a6_c06_stale_writer_fence_fails_before_write(self) -> None:
        request = self._owner_request(
            correction=False,
            stale_writer_fence=True,
        )
        before = self._business_snapshot()
        advances_before = self.head.advance_call_count

        rejected = self._prepare(request)

        self.assertEqual(rejected.status, "unavailable")
        self.assertEqual(self.store.owner_prepare_write_count, 0)
        self.assertEqual(self.head.advance_call_count, advances_before)
        self.assertIsNone(self._status(request))
        self.assertEqual(self._business_snapshot(), before)

    def test_114_a3_c23_owner_correction_rejects_extra_evidence_scope(self) -> None:
        request = self._owner_request(settings_mutation=False)
        before = self._business_snapshot()

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-correction-evidence-scope-mismatch"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, 0)
        self.assertIsNone(self._status(request))
        self.assertEqual(self._business_snapshot(), before)

    def test_114_a3_c24_owner_correction_binds_actual_daily_source(self) -> None:
        pending = self.pending_correction
        self.assertIsNotNone(pending)
        assert pending is not None
        self.pending_correction = replace(
            pending,
            revision=replace(
                pending.revision,
                source_refs=("source:forged-unrelated",),
            ),
            previous_value=next(
                item.to_wire()["value"]
                for item in self.plugin.managed_rights_read_current(
                    peer_id=_PEER_ID
                )
                if item.object_ref == pending.target_ref.object_ref
            ),
        )
        request = self._owner_request(settings_mutation=False)
        before = self._business_snapshot()

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-correction-source-mismatch"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, 0)
        self.assertIsNone(self._status(request))
        self.assertEqual(self._business_snapshot(), before)

    def test_114_a3_c25_public_rights_read_denies_wrong_owner_policy(self) -> None:
        wrong_policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-B",
            conversation_id="private-A",
        )
        wrong_owner_plugin = HealthPlugin(
            self.core,
            admission_policy=wrong_policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=self.sleep_runtime,
        )

        with self.assertRaisesRegex(
            AuthorityValidationError,
            "managed-rights-read-unavailable",
        ):
            wrong_owner_plugin.managed_rights_read_current(peer_id=_PEER_ID)
        self.assertFalse(hasattr(wrong_owner_plugin, "managed_rights_projection"))

    def test_114_a3_c26_public_rights_read_denies_untrusted_peer(self) -> None:
        with self.assertRaisesRegex(ProtocolViolation, "untrusted peer"):
            self.plugin.managed_rights_read_current(peer_id="ordinary-caller")

    def test_114_a3_c27_public_export_roundtrips_final_correction_metadata(self) -> None:
        request = self._owner_request(settings_mutation=False)
        self.assertEqual(self._prepare(request).status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        self.assertEqual(self._finalize(request).status, "accepted")
        current = next(
            item
            for item in self.plugin.managed_rights_read_current(
                peer_id=_PEER_ID
            )
            if item.object_ref == self.baseline_card.evidence_id
        )
        reference = rights.ManagedObjectReference(
            object_ref=current.object_ref,
            installation_id=current.installation_id,
            version=current.version,
        )

        exported = self.plugin.managed_rights_export(
            requested_refs=(reference,),
            snapshot_id=f"snapshot:{self._testMethodName}",
            created_at_utc="2026-08-24T04:00:00+00:00",
            peer_id=_PEER_ID,
        )
        parsed = rights.ManagedExport.from_wire(exported.to_wire())

        self.assertEqual(parsed, exported)
        self.assertEqual(parsed.snapshot.object_refs, (current.object_ref,))
        self.assertEqual(parsed.objects[0].version, 2)
        self.assertEqual(
            parsed.corrections,
            (self.pending_correction.revision,),
        )
        self.assertEqual(
            (
                parsed.corrections[0].correction_id,
                parsed.corrections[0].previous_version,
                parsed.corrections[0].revision_version,
                parsed.corrections[0].source_refs,
            ),
            (
                self.pending_correction.revision.correction_id,
                1,
                2,
                (f"source:{self.correction_source_id}",),
            ),
        )
        self.assertFalse(hasattr(rights.ManagedExport, "import_into_state"))

    def test_114_a3_c28_finalized_correction_prepare_receipt_is_body_free(self) -> None:
        request = self._owner_request(settings_mutation=False)
        prepared = self._prepare(request)
        self.assertEqual(prepared.status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        self.assertEqual(self._finalize(request).status, "accepted")

        stored = self._stored_command_receipt(request.context.causal_id)
        self.assertEqual(
            set(stored),
            {"kind", "command_digest", "response"},
        )
        self.assertEqual(stored["kind"], "command-digest-v1")
        self.assertNotIn("pending_correction", repr(stored))
        self.assertNotIn("daily_turn_draft", repr(stored))
        self.assertNotIn("replacement_claim", repr(stored))
        writes_before_replay = self.store.owner_prepare_write_count
        replayed = self._prepare(request)
        self.assertEqual(replayed.to_wire(), prepared.to_wire())
        self.assertEqual(
            self.store.owner_prepare_write_count,
            writes_before_replay,
        )

    def test_114_a3_c29_rejected_correction_prepare_receipt_is_body_free(self) -> None:
        pending = self.pending_correction
        self.assertIsNotNone(pending)
        assert pending is not None
        self.pending_correction = replace(
            pending,
            revision=replace(
                pending.revision,
                source_refs=("source:forged-unrelated",),
            ),
            previous_value=next(
                item.to_wire()["value"]
                for item in self.plugin.managed_rights_read_current(
                    peer_id=_PEER_ID
                )
                if item.object_ref == pending.target_ref.object_ref
            ),
        )
        request = self._owner_request(settings_mutation=False)

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-correction-source-mismatch"),
        )
        stored = self._stored_command_receipt(request.context.causal_id)
        self.assertEqual(
            set(stored),
            {"kind", "command_digest", "response"},
        )
        self.assertEqual(stored["kind"], "command-digest-v1")
        self.assertNotIn("pending_correction", repr(stored))
        self.assertNotIn("daily_turn_draft", repr(stored))
        self.assertNotIn("replacement_claim", repr(stored))
        writes_before_replay = self.store.owner_prepare_write_count
        replayed = self._prepare(request)
        self.assertEqual(replayed.to_wire(), rejected.to_wire())
        self.assertEqual(
            self.store.owner_prepare_write_count,
            writes_before_replay,
        )

    def test_114_a3_c30_correction_metadata_matches_actual_portrait_rejudgment(
        self,
    ) -> None:
        pending = self.pending_correction
        self.assertIsNotNone(pending)
        assert pending is not None
        self.pending_correction = self.plugin.managed_correction_draft(
            target_ref=pending.target_ref,
            correction_id=pending.revision.correction_id,
            reason=pending.revision.reason,
            corrected_at_utc=pending.revision.corrected_at_utc,
            replacement_claim=self._replacement_claim(),
            correction_source_refs=pending.revision.source_refs,
            affected_object_refs=(
                "portrait-topic:physical-function-and-experience/unrelated",
            ),
            disposition_requests=("rejudge",),
            peer_id=_PEER_ID,
        )
        request = self._owner_request(settings_mutation=False)
        before = self._business_snapshot()
        writes_before = self.store.owner_prepare_write_count

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-correction-affected-scope-mismatch"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, writes_before)
        self.assertIsNone(self._status(request))
        self.assertEqual(self._business_snapshot(), before)

    def test_114_a3_c31_correction_rejects_extra_unsupported_affected_scope(
        self,
    ) -> None:
        pending = self.pending_correction
        self.assertIsNotNone(pending)
        assert pending is not None
        self.pending_correction = self.plugin.managed_correction_draft(
            target_ref=pending.target_ref,
            correction_id=pending.revision.correction_id,
            reason=pending.revision.reason,
            corrected_at_utc=pending.revision.corrected_at_utc,
            replacement_claim=self._replacement_claim(),
            correction_source_refs=pending.revision.source_refs,
            affected_object_refs=(
                f"portrait-topic:{_CORRECTION_TOPIC}",
                "task:unrelated-object",
            ),
            disposition_requests=("rejudge",),
            peer_id=_PEER_ID,
        )
        request = self._owner_request(settings_mutation=False)
        before = self._business_snapshot()
        writes_before = self.store.owner_prepare_write_count

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-correction-affected-scope-mismatch"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, writes_before)
        self.assertIsNone(self._status(request))
        self.assertEqual(self._business_snapshot(), before)

    def test_114_a5_c20_core_status_uses_real_authorities_and_keeps_future_domains_unknown(self) -> None:
        result = self.plugin.business_status(peer_id=_PEER_ID)

        self.assertIs(type(result), status.BusinessStatusResult)
        self.assertEqual(result.projection.state, "cannot-confirm")
        self.assertIsNone(result.transition)
        self.assertTrue(
            {
                "safety",
                "diagnostic_scope",
                "model_route",
                "question_answering",
            }
            <= set(result.projection.affected_core_domains)
        )
        self.assertTrue(
            {
                "entry",
                "enablement",
                "keys_state",
                "portrait_evidence",
                "controls",
                "current_head",
            }.isdisjoint(result.projection.affected_core_domains)
        )
        self.assertFalse(hasattr(result, "facts"))
        self.assertFalse(
            any(
                proxy in reason
                for reason in result.projection.reason_codes
                for proxy in ("heartbeat", "process", "cron", "plugin-loaded")
            )
        )

    def test_114_a5_c21_status_transition_is_deduplicated_across_restart(self) -> None:
        prior = status.StatusProjection(
            state="active",
            evaluated_at_utc="2026-08-24T11:59:00+00:00",
            affected_core_domains=(),
            isolated_noncore_domains=(),
            reason_codes=(),
            fact_set_digest="sha256:" + ("f" * 64),
        )
        self.assertIsNone(self.store.remember_business_status(prior))

        first = self.plugin.business_status(peer_id=_PEER_ID)
        replay = self.plugin.business_status(peer_id=_PEER_ID)

        self.assertIsNotNone(first.transition)
        assert first.transition is not None
        self.assertEqual(first.transition.previous_state, "active")
        self.assertEqual(first.transition.current_state, "cannot-confirm")
        self.assertIsNone(replay.transition)
        self.assertEqual(replay.projection, first.projection)
        self.assertEqual(
            self.store.business_status_projection(),
            first.projection,
        )

        self.assertTrue(self.core.close().complete)
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
            daily_skill_verifier=self.daily_attestor,
            daily_skill_bundle=self.daily_bundle,
            owner_settings_clock=lambda: self.owner_clock_value,
            status_fact_authority=self.status_authority,
            business_status_clock=lambda: self.status_clock_value,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=self.sleep_runtime,
        )

        restarted = self.plugin.business_status(peer_id=_PEER_ID)

        self.assertEqual(restarted.projection, first.projection)
        self.assertIsNone(restarted.transition)

    def test_114_a4_c13_core_activates_due_timezone_after_restart(self) -> None:
        snapshot = self.head.read().head
        command = settings.FieldUpdate(
            field_name="timezone",
            old_value="Asia/Shanghai",
            new_value="America/New_York",
            generation=snapshot.generation,
            effective_at_utc=_REQUESTED_AT,
        )
        request = self._owner_request(
            correction=False,
            settings_command=command,
        )

        self.assertEqual(self._prepare(request).status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        self.assertEqual(self._finalize(request).status, "accepted")
        pending = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        self.assertEqual(pending.timezone, "Asia/Shanghai")
        self.assertIsNotNone(pending.timezone_transition)
        assert pending.timezone_transition is not None

        self.owner_clock_value = datetime.fromisoformat(
            pending.timezone_transition.effective_at_utc
        )
        activated = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        self.assertEqual(
            (
                activated.timezone,
                activated.timezone_transition,
                activated.version,
                activated.completed_review_keys,
            ),
            (
                "America/New_York",
                None,
                pending.version,
                pending.completed_review_keys,
            ),
        )

        self.core.close()
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
            daily_skill_verifier=self.daily_attestor,
            daily_skill_bundle=self.daily_bundle,
            owner_settings_clock=lambda: self.owner_clock_value,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=self.sleep_runtime,
        )
        restarted = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        self.assertEqual(restarted, activated)

    def test_114_a7_c11_owner_cannot_submit_route_authority_fact(self) -> None:
        snapshot = self.head.read().head
        route_fact = settings.RouteConfigurationUpdate(
            route_id="forged-owner-route",
            first_hop_recipient="forged-owner-recipient",
            configuration_generation=999,
            disclosure_version="forged-owner-disclosure",
            generation=snapshot.generation,
        )
        context = OwnerMutationContext(
            command_id=f"owner-mutation:{self._testMethodName}",
            causal_id=f"{self._testMethodName}:owner-command-source",
            actor_kind="current_owner",
            owner_id=_OWNER_ID,
            installation_id=_INSTALLATION_ID,
            permissions=("health_settings.write",),
            context_ref=f"managed-context:{self._testMethodName}",
            current_head_generation=snapshot.generation,
            writer_fence=snapshot.writer_fence,
        )
        before = self.plugin.owner_settings_state(peer_id=_PEER_ID)

        with self.assertRaises(OwnerAuthorityContractViolation):
            OwnerMutationRequest.form(
                context=context,
                expected_settings_version=before.version,
                requested_at_utc=_REQUESTED_AT,
                settings_command=route_fact,
            )

        self.assertEqual(
            self.plugin.owner_settings_state(peer_id=_PEER_ID),
            before,
        )
        self.assertEqual(self.store.owner_prepare_write_count, 0)

    def test_114_a7_c12_core_route_fact_pauses_until_exact_reconsent(self) -> None:
        route_fact = settings.RouteConfigurationUpdate(
            route_id="partner-first-hop-v2",
            first_hop_recipient="jojo-responses-v2",
            configuration_generation=2,
            disclosure_version="health-init-disclosure-v2",
            generation=2,
        )
        close_report = self.core.close()
        self.assertTrue(close_report.complete)
        self.writer_vault.bind(
            self.head.read().head.as_authority(),
            self.writer_capability,
        )
        self.core = HealthCore(
            self.store,
            self.head,
            writer_fence_vault=self.writer_vault,
            admission_policy=self.policy,
            health_init_verifier=self.init_attestor,
            health_init_asset=self.init_asset,
            daily_skill_verifier=self.daily_attestor,
            daily_skill_bundle=self.daily_bundle,
            owner_settings_clock=lambda: self.owner_clock_value,
            route_configuration_provider=lambda: route_fact,
        )
        self.plugin = HealthPlugin(
            self.core,
            admission_policy=self.policy,
            health_init_runtime=self.init_runtime,
            coarse_router=self.router,
            daily_skill_runtime=self.sleep_runtime,
        )
        self.correction_plugin = self.plugin

        drifted = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        self.assertEqual(
            (
                drifted.current_route_id,
                drifted.current_first_hop_recipient,
                drifted.current_configuration_generation,
                drifted.current_disclosure_version,
                drifted.consent_path_status,
            ),
            (
                route_fact.route_id,
                route_fact.first_hop_recipient,
                route_fact.configuration_generation,
                route_fact.disclosure_version,
                "paused",
            ),
        )

        snapshot = self.head.read().head
        renewal = settings.ConsentRenewal(
            renewal_id=f"consent-renewal:{self._testMethodName}",
            context=settings.OwnerCommandContext(
                command_id=f"settings-command:{self._testMethodName}",
                causal_id=f"settings-source:{self._testMethodName}",
                actor_kind="current_owner",
                owner_id=_OWNER_ID,
                installation_id=_INSTALLATION_ID,
                permission="health_settings.write",
                context_ref=f"managed-context:{self._testMethodName}",
                generation=snapshot.generation,
                writer_fence=snapshot.writer_fence,
            ),
            route_id=route_fact.route_id,
            first_hop_recipient=route_fact.first_hop_recipient,
            configuration_generation=route_fact.configuration_generation,
            disclosure_version=route_fact.disclosure_version,
            disclosure_digest="sha256:" + "e" * 64,
            consented_at_utc=_REQUESTED_AT,
        )
        request = self._owner_request(
            correction=False,
            settings_command=renewal,
            expected_settings_version=drifted.version,
        )
        prepared = self._prepare(request)
        self.assertEqual(
            (prepared.status, prepared.reason_code),
            ("accepted", "owner-mutation-prepared"),
        )
        self.assertEqual(self._commit(request).status, "accepted")
        self.assertEqual(self._finalize(request).status, "accepted")
        renewed = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        self.assertEqual(
            (
                renewed.consent_path_status,
                renewed.consent_route_id,
                renewed.consent_first_hop_recipient,
                renewed.consent_configuration_generation,
                renewed.consent_disclosure_version,
            ),
            (
                "active",
                route_fact.route_id,
                route_fact.first_hop_recipient,
                route_fact.configuration_generation,
                route_fact.disclosure_version,
            ),
        )

    def test_114_a6_c07_atomic_rollback_covers_settings_and_rights(self) -> None:
        request = self._owner_request()
        before_settings, before_rights, before_daily = self._business_snapshot()
        self.assertEqual(self._prepare(request).status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        self.store.fail_after_owner_finalize_write = True

        failed = self._finalize(request)

        self.assertEqual(failed.status, "unavailable")
        stored_settings = self.store.owner_settings()
        self.assertIn(stored_settings, (None, before_settings))
        stored_daily = self.store.daily_state()
        self.assertEqual(stored_daily, before_daily)
        self.assertEqual(
            before_rights,
            self._rights_from_stored_daily(stored_daily),
        )
        self.assertIsNone(self._daily_result_or_none())

    def test_114_a6_c08_idempotent_replay_has_one_result(self) -> None:
        request = self._owner_request()
        before_settings, _, before_daily = self._business_snapshot()
        advances_before = self.head.advance_call_count

        self.assertEqual(self._prepare(request).status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        finalized = self._finalize(request)

        self.assertEqual(finalized.status, "accepted")
        after_settings, after_rights, after_daily = self._business_snapshot()
        self.assertEqual(after_settings.version, before_settings.version + 1)
        self.assertEqual(
            len(after_daily.evidence_cards),
            len(before_daily.evidence_cards) + 1,
        )
        successor_ids = {
            card.evidence_id for card in after_daily.evidence_cards
        } - {card.evidence_id for card in before_daily.evidence_cards}
        self.assertEqual(len(successor_ids), 1)
        successor_id = next(iter(successor_ids))
        changes = tuple(
            change
            for change in after_daily.evidence_applicability_changes
            if change.target_evidence_id == self.baseline_card.evidence_id
        )
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].successor_evidence_id, successor_id)
        corrects = tuple(
            relation
            for relation in after_daily.evidence_relations
            if relation.relation_class == "history"
            and relation.relation_kind == "corrects"
            and relation.target_ref == self.baseline_card.evidence_id
        )
        self.assertEqual(len(corrects), 1)
        self.assertEqual(corrects[0].evidence_id, successor_id)
        self.assertEqual(
            after_daily.processed_source_causal_ids.count(
                self.correction_source_id
            ),
            1,
        )
        result = self.core.daily_turn_result(self.correction_source_id)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.owner_reply)
        self.assertEqual(
            self.store._execute(
                "SELECT COUNT(*) FROM daily_turns_v1 "
                "WHERE source_causal_id = ?",
                (self.correction_source_id,),
            ).fetchone()[0],
            1,
        )

        self.assertEqual(self.head.advance_call_count, advances_before + 1)
        self.assertEqual(
            after_rights,
            self.correction_plugin.managed_rights_read_current(peer_id=_PEER_ID),
        )
        finalized_status = self._status(request)
        self.assertIsNotNone(finalized_status)
        self.assertEqual(finalized_status.phase, "finalized")

        advances_after_first = self.head.advance_call_count
        self.assertEqual(self._prepare(request).status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        replayed = self._finalize(request)

        self.assertEqual(replayed.status, "accepted")
        self.assertEqual(self.head.advance_call_count, advances_after_first)
        self.assertEqual(
            self._business_snapshot(),
            (after_settings, after_rights, after_daily),
        )
        self.assertEqual(
            self.core.daily_turn_result(self.correction_source_id),
            result,
        )
        self.assertEqual(
            after_daily.processed_source_causal_ids.count(
                self.correction_source_id
            ),
            1,
        )
        self.assertEqual(
            self.store._execute(
                "SELECT COUNT(*) FROM daily_turns_v1 "
                "WHERE source_causal_id = ?",
                (self.correction_source_id,),
            ).fetchone()[0],
            1,
        )

    def test_114_a6_c10_concurrent_owner_lease_rejects_without_partial_record(self) -> None:
        first = self._owner_request(correction=False)
        second = self._owner_request(
            correction=False,
            control_name="recording",
            control_operation="stop",
            command_suffix=":second",
        )
        before = self.store.owner_settings()
        self.assertEqual(self._prepare(first).status, "accepted")

        rejected = self._prepare(second)

        self.assertEqual(rejected.status, "unavailable")
        self.assertEqual(rejected.reason_code, "local-transition-unresolved")
        self.assertIsNone(self.store.owner_mutation(second.context.command_id))
        self.assertIsNone(self.store.record(second.record_id))
        first_status = self._status(first)
        self.assertIsNotNone(first_status)
        self.assertEqual(first_status.phase, "prepared")
        self.assertEqual(self.store.owner_settings(), before)

    def test_114_a6_c11_terminal_settings_digest_rejects_same_version_substitution(self) -> None:
        initial = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        first = self._owner_request(
            correction=False,
            settings_command=settings.FieldUpdate(
                field_name="contact_window",
                old_value=initial.contact_window,
                new_value="10:00-20:00",
                generation=self.head.read().head.generation,
                effective_at_utc=_REQUESTED_AT,
            ),
        )
        self.assertEqual(self._prepare(first).status, "accepted")
        self.assertEqual(self._commit(first).status, "accepted")
        self.assertEqual(self._finalize(first).status, "accepted")

        after_first = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        second = self._owner_request(
            correction=False,
            settings_command=settings.FieldUpdate(
                field_name="expression_style",
                old_value=after_first.expression_style,
                new_value="detailed",
                generation=self.head.read().head.generation,
                effective_at_utc=_REQUESTED_AT,
            ),
            expected_settings_version=after_first.version,
            command_suffix=":second",
        )
        self.assertEqual(self._prepare(second).status, "accepted")
        self.assertEqual(self._commit(second).status, "accepted")
        self.assertEqual(self._finalize(second).status, "accepted")

        authority = self.store.finalized_authority()
        self.assertIsNotNone(authority)
        self.assertTrue(self.store.verify_integrity(authority))
        terminals = tuple(
            self.store.owner_mutation(command_id).terminal
            for command_id in (
                first.context.command_id,
                second.context.command_id,
            )
        )
        self.assertEqual(
            tuple(terminal.settings_version for terminal in terminals),
            (2, 3),
        )
        self.assertNotEqual(
            terminals[0].next_settings_digest,
            terminals[1].next_settings_digest,
        )

        current = self.store.owner_settings()
        self.assertIsNotNone(current)
        forged_wire = current.to_wire()
        forged_wire["preferences"]["contact_window"] = "11:00-19:00"
        forged = settings.OwnerSettingsState.from_wire(forged_wire)
        with self.store.transaction() as connection:
            self.store._assert_integrity_manifest_before_mutation()
            nonce, ciphertext = self.store._seal(
                "owner-settings:v1",
                forged.to_wire(),
            )
            connection.execute(
                "UPDATE owner_settings_v1 SET nonce = ?, ciphertext = ? "
                "WHERE slot = 1",
                (nonce, ciphertext),
            )
            self.store._refresh_integrity_manifest(connection)

        with self.assertRaises(KeyUnavailable):
            self.store.verify_integrity(authority)

    def test_114_a6_c19_legacy_manifest_migration_rechecks_signed_shape_inside_lock(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = f"{directory}/ticket114-legacy-race.sqlite"
            key_provider = StaticKeyProvider(
                b"m" * 32,
                key_id="ticket114-legacy-race-key",
            )
            authority = InMemoryCurrentHead(
                installation_id="ticket114-legacy-race-installation",
                site="ticket114-legacy-race-site",
                writer_capability="ticket114-legacy-race-writer",
            ).read().head.as_authority()
            legacy = EncryptedStateStore(database, key_provider)
            legacy.seed_finalized_authority(authority)
            with legacy.transaction() as connection:
                legacy_fingerprint = legacy._integrity_fingerprint(
                    include_ticket114=False,
                )
                nonce, ciphertext = legacy._seal(
                    "integrity-manifest",
                    {"fingerprint": legacy_fingerprint},
                )
                connection.execute(
                    "UPDATE integrity_manifest_v1 SET nonce = ?, ciphertext = ? "
                    "WHERE slot = 1",
                    (nonce, ciphertext),
                )
            legacy.close()

            raced = _LegacyManifestRaceStore(database, key_provider)
            try:
                self.assertTrue(raced.race_fired)
                with self.assertRaisesRegex(
                    KeyUnavailable,
                    "health state integrity manifest mismatch",
                ):
                    raced.verify_integrity(authority)
                manifest_row = raced._execute(
                    "SELECT nonce, ciphertext FROM integrity_manifest_v1 "
                    "WHERE slot = 1"
                ).fetchone()
                self.assertIsNotNone(manifest_row)
                stored = raced._open(
                    "integrity-manifest",
                    manifest_row[0],
                    manifest_row[1],
                )
                self.assertEqual(stored["fingerprint"], legacy_fingerprint)
                self.assertNotEqual(
                    stored["fingerprint"],
                    raced._integrity_fingerprint(),
                )
            finally:
                raced.close()

    def test_114_a6_c20_fresh_manifest_rechecks_empty_domain_inside_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = f"{directory}/ticket114-fresh-race.sqlite"
            raced = _FreshManifestRaceStore(
                database,
                StaticKeyProvider(
                    b"n" * 32,
                    key_id="ticket114-fresh-race-key",
                ),
            )
            try:
                self.assertTrue(raced.race_fired)
                self.assertEqual(
                    raced.business_status_projection(),
                    raced.injected_projection,
                )
                with self.assertRaisesRegex(
                    KeyUnavailable,
                    "health state integrity manifest missing",
                ):
                    raced._verify_integrity_manifest()
                self.assertIsNone(
                    raced._execute(
                        "SELECT nonce, ciphertext FROM integrity_manifest_v1 "
                        "WHERE slot = 1"
                    ).fetchone()
                )
            finally:
                raced.close()

    def test_114_a6_c21_owner_api_replays_daily_finalized_transition_after_restart(
        self,
    ) -> None:
        request = self._owner_request(settings_mutation=False)
        self.assertEqual(self._prepare(request).status, "accepted")
        prepared = self.core.daily_turn_status(self.correction_source_id)
        self.assertIsNotNone(prepared)
        assert prepared is not None
        self.assertEqual(prepared.phase, "prepared")
        redelivery = self._exact_redelivery(self.correction_source_id)
        restarted = self._restart_plugin()

        finalized_by_daily = restarted.receive_weixin(
            redelivery,
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (finalized_by_daily.status, finalized_by_daily.reason_code),
            ("accepted", "daily-turn-finalized"),
        )
        owner_status = restarted.owner_mutation_status(
            request.context.command_id,
            peer_id=_PEER_ID,
        )
        self.assertIsNotNone(owner_status)
        assert owner_status is not None
        self.assertEqual(owner_status.phase, "finalized")
        applied = self.head.read().head
        expected_commit = Response(
            "accepted",
            HealthPlugin._owner_mutation_causal_id(
                "commit",
                request.context.command_id,
            ),
            "current-head-advanced",
            CommitMeta(applied.generation, applied.writer_fence),
        )
        expected_finalize = Response(
            "accepted",
            HealthPlugin._owner_mutation_causal_id(
                "finalize",
                request.context.command_id,
            ),
            "revision-finalized",
        )
        advances_before_replay = self.head.advance_call_count

        replayed_commit = restarted.commit_owner_mutation(
            request.context.command_id,
            peer_id=_PEER_ID,
        )
        replayed_finalize = restarted.finalize_owner_mutation(
            request.context.command_id,
            peer_id=_PEER_ID,
        )

        self.assertEqual(replayed_commit, expected_commit)
        self.assertEqual(replayed_finalize, expected_finalize)
        self.assertEqual(
            self.head.advance_call_count,
            advances_before_replay,
        )
        self.assertEqual(
            restarted.owner_mutation_status(
                request.context.command_id,
                peer_id=_PEER_ID,
            ).phase,
            "finalized",
        )

    def test_114_a6_c22_owner_api_resumes_daily_committed_transition_after_restart(
        self,
    ) -> None:
        request = self._owner_request(settings_mutation=False)
        self.assertEqual(self._prepare(request).status, "accepted")
        restarted = self._restart_plugin()
        prepared = self.core.daily_turn_status(self.correction_source_id)
        self.assertIsNotNone(prepared)
        assert prepared is not None
        self.assertEqual(prepared.phase, "prepared")

        daily_commit = restarted.invoke(
            HealthPlugin._daily_transition_command(
                prepared,
                "state.commit",
            ),
            peer_id=_PEER_ID,
        )

        self.assertEqual(
            (daily_commit.status, daily_commit.reason_code),
            ("accepted", "current-head-advanced"),
        )
        self.assertIs(type(daily_commit.meta), CommitMeta)
        restarted = self._restart_plugin()
        committed = restarted.owner_mutation_status(
            request.context.command_id,
            peer_id=_PEER_ID,
        )
        self.assertIsNotNone(committed)
        assert committed is not None
        self.assertEqual(committed.phase, "committed")
        expected_commit = Response(
            "accepted",
            HealthPlugin._owner_mutation_causal_id(
                "commit",
                request.context.command_id,
            ),
            "current-head-advanced",
            daily_commit.meta,
        )
        expected_finalize = Response(
            "accepted",
            HealthPlugin._owner_mutation_causal_id(
                "finalize",
                request.context.command_id,
            ),
            "revision-finalized",
        )
        advances_after_daily_commit = self.head.advance_call_count

        owner_commit = restarted.commit_owner_mutation(
            request.context.command_id,
            peer_id=_PEER_ID,
        )
        owner_finalize = restarted.finalize_owner_mutation(
            request.context.command_id,
            peer_id=_PEER_ID,
        )
        replayed_commit = restarted.commit_owner_mutation(
            request.context.command_id,
            peer_id=_PEER_ID,
        )
        replayed_finalize = restarted.finalize_owner_mutation(
            request.context.command_id,
            peer_id=_PEER_ID,
        )

        self.assertEqual(owner_commit, expected_commit)
        self.assertEqual(owner_finalize, expected_finalize)
        self.assertEqual(replayed_commit, expected_commit)
        self.assertEqual(replayed_finalize, expected_finalize)
        self.assertEqual(
            self.head.advance_call_count,
            advances_after_daily_commit,
        )
        terminal = restarted.owner_mutation_status(
            request.context.command_id,
            peer_id=_PEER_ID,
        )
        self.assertIsNotNone(terminal)
        assert terminal is not None
        self.assertEqual(terminal.phase, "finalized")
        daily_terminal = self.core.daily_turn_status(
            self.correction_source_id
        )
        self.assertIsNotNone(daily_terminal)
        assert daily_terminal is not None
        self.assertEqual(daily_terminal.phase, "finalized")

    def test_114_a6_c23_owner_commit_recovers_stopped_correction_without_body(
        self,
    ) -> None:
        restarted, pending, redelivery, context = (
            self._restarted_stopped_correction_submission()
        )
        prepared = restarted.prepare_owner_correction(
            pending=pending,
            source_message=redelivery,
            context=context,
            expected_settings_version=2,
            requested_at_utc=_REQUESTED_AT,
            peer_id=_PEER_ID,
        )
        self.assertEqual(
            (prepared.status, prepared.reason_code),
            ("accepted", "owner-mutation-prepared"),
        )
        owner_row = self.store.owner_mutation(context.command_id)
        self.assertIsNotNone(owner_row)
        assert owner_row is not None
        self.assertNotIn(self._replacement_claim().content, repr(owner_row))
        receipt = self.store.source_receipt(self.correction_source_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIsNone(receipt.envelope.body)

        restarted = self._restart_plugin()
        status_before = restarted.owner_mutation_status(
            context.command_id,
            peer_id=_PEER_ID,
        )
        self.assertIsNotNone(status_before)
        assert status_before is not None
        self.assertEqual(status_before.phase, "prepared")
        self.assertNotIn(
            self.correction_source_id,
            self.core._recording_excluded_sources,
        )

        committed = restarted.commit_owner_mutation(
            context.command_id,
            peer_id=_PEER_ID,
        )
        finalized = restarted.finalize_owner_mutation(
            context.command_id,
            peer_id=_PEER_ID,
        )

        self.assertEqual(committed.status, "accepted", committed)
        self.assertEqual(finalized.status, "accepted", finalized)
        terminal = restarted.owner_mutation_status(
            context.command_id,
            peer_id=_PEER_ID,
        )
        self.assertIsNotNone(terminal)
        assert terminal is not None
        self.assertEqual(terminal.phase, "finalized")

    def test_114_a6_c12_terminal_binds_exact_generic_transition_target(self) -> None:
        request = self._owner_request(correction=False)
        self.assertEqual(self._prepare(request).status, "accepted")
        self.assertEqual(self._commit(request).status, "accepted")
        self.assertEqual(self._finalize(request).status, "accepted")
        authority = self.store.finalized_authority()
        self.assertIsNotNone(authority)
        self.assertTrue(self.store.verify_integrity(authority))

        stored = self.store.owner_mutation(request.context.command_id)
        self.assertIsNotNone(stored)
        self.assertIsNotNone(stored.terminal)
        forged_terminal = replace(
            stored.terminal,
            revision_digest="sha256:" + ("f" * 64),
            transition_id="owner-transition:forged-target",
        )
        forged = StoredOwnerMutation(
            phase="finalized",
            prepared=None,
            terminal=forged_terminal,
        )
        with self.store.transaction() as connection:
            self.store._assert_integrity_manifest_before_mutation()
            nonce, ciphertext = self.store._seal(
                f"owner-mutation:{stored.command_id}:{stored.record_id}:finalized",
                forged.to_storage(),
            )
            connection.execute(
                "UPDATE owner_mutations_v1 SET nonce = ?, ciphertext = ? "
                "WHERE command_id = ?",
                (nonce, ciphertext, stored.command_id),
            )
            self.store._refresh_integrity_manifest(connection)

        with self.assertRaises(KeyUnavailable):
            self.store.verify_integrity(authority)

    def test_114_a6_c13_wrong_owner_fails_before_write(self) -> None:
        request = self._owner_request(correction=False, owner_id="owner-B")
        before = self._business_snapshot()

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-authority-mismatch"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, 0)
        self.assertIsNone(self._status(request))
        self.assertEqual(self._business_snapshot(), before)

    def test_114_a6_c14_wrong_installation_fails_before_write(self) -> None:
        request = self._owner_request(
            correction=False,
            installation_id="another-installation",
        )
        before = self._business_snapshot()

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-authority-mismatch"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, 0)
        self.assertIsNone(self._status(request))
        self.assertEqual(self._business_snapshot(), before)

    def test_114_a6_c15_missing_settings_permission_fails_at_public_seam(self) -> None:
        valid = self._owner_request(correction=False)
        forged = self._forge_owner_request(
            valid,
            context=replace(
                valid.context,
                permissions=("health_data.read",),
            ),
        )
        before = self._business_snapshot()

        rejected = self._prepare(forged)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "invalid-command-envelope"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, 0)
        self.assertIsNone(self.store.owner_mutation(valid.context.command_id))
        self.assertEqual(self._business_snapshot(), before)

    def test_114_a6_c16_missing_correction_permission_fails_at_public_seam(self) -> None:
        valid = self._owner_request(settings_mutation=False)
        forged = self._forge_owner_request(
            valid,
            context=replace(
                valid.context,
                permissions=("health_data.read",),
            ),
        )
        before = self._business_snapshot()

        rejected = self._prepare(forged)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "invalid-command-envelope"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, 0)
        self.assertIsNone(self.store.owner_mutation(valid.context.command_id))
        self.assertEqual(self._business_snapshot(), before)

    def test_114_a6_c17_stale_current_head_generation_fails_before_write(self) -> None:
        current = self.head.read().head
        stale_generation = current.generation - 1
        request = self._owner_request(
            correction=False,
            current_head_generation=stale_generation,
            settings_command=settings.ControlUpdate(
                control_name="proactive_support",
                operation="pause",
                target_ref=None,
                generation=stale_generation,
                effective_at_utc=_REQUESTED_AT,
            ),
        )
        before = self._business_snapshot()

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "generation mismatch"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, 0)
        self.assertIsNone(self._status(request))
        self.assertEqual(self._business_snapshot(), before)

    def test_114_a6_c18_stale_settings_object_version_fails_before_write(self) -> None:
        current = self.plugin.owner_settings_state(peer_id=_PEER_ID)
        request = self._owner_request(
            correction=False,
            expected_settings_version=current.version + 1,
        )
        before = self._business_snapshot()

        rejected = self._prepare(request)

        self.assertEqual(
            (rejected.status, rejected.reason_code),
            ("rejected", "owner-settings-version-mismatch"),
        )
        self.assertEqual(self.store.owner_prepare_write_count, 0)
        self.assertIsNone(self._status(request))
        self.assertEqual(self._business_snapshot(), before)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

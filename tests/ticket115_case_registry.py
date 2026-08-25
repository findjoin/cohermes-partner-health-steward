"""Ordered, independently observable Ticket 115 acceptance cases."""

from __future__ import annotations

import importlib
import re


CASE_REGISTRY = (
    # A1: task identity, controls, scope, and successor relations.
    ("115-A1-C01", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a1_c01_defer_is_a_fact_and_keeps_active_label", "defer records an independent control fact while the task remains active"),
    ("115-A1-C02", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a1_c02_scope_expansion_creates_linked_waiting_task", "scope expansion creates a linked task waiting for approval"),
    ("115-A1-C03", "test_ticket115_tasks.Ticket115TaskEngineTests.test_engine_owns_initial_task_state_and_merges_duplicate_basis", "duplicate task basis merges source evidence without creating another active task"),
    ("115-A1-C04", "test_ticket115_integration.Ticket115IntegrationTests.test_owner_task_cancellation_tombstone_blocks_later_admission", "owner rejection cancels the basis and blocks the same task admission"),
    ("115-A1-C05", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a1_c05_scope_expansion_consumes_only_exact_current_approval", "only the exact current scope approval may be consumed"),
    ("115-A1-C06", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a1_c06_scope_expansion_requires_a_current_approval", "a bound scope expansion without current approval is rejected"),
    ("115-A1-C07", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a1_c07_revoked_scope_approval_is_rejected", "a revoked scope approval is rejected"),
    ("115-A1-C08", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a1_c08_phase_progression_keeps_the_active_primary_label", "phase advancement does not become a new primary label"),
    ("115-A1-C09", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a1_c09_primary_labels_are_mutually_exclusive", "the four primary labels are mutually exclusive"),
    ("115-A1-C10", "test_ticket115_tasks.Ticket115TaskEngineTests.test_terminal_task_cannot_reopen_but_can_link_an_explicit_successor", "a terminal task cannot reopen and can only link an explicit successor"),
    ("115-A1-C11", "test_ticket115_integration.Ticket115IntegrationTests.test_review_plugin_inputs_are_wake_only", "the plugin wake surface cannot write a candidate task directly"),
    # A2: task outcomes remain separate from ancillary facts.
    ("115-A2-C01", "test_ticket115_tasks.Ticket115TaskEngineTests.test_engine_owns_initial_task_state_and_merges_duplicate_basis", "candidate evidence and owner goals remain task source facts"),
    ("115-A2-C02", "test_ticket115_tasks.Ticket115DailyReviewTests.test_quiet_review_has_no_notification_and_commit_cannot_change_pending", "a reminder can be quiet without changing task outcome semantics"),
    ("115-A2-C03", "test_ticket115_integration.Ticket115IntegrationTests.test_core_solve_task_requires_current_evidence_card_revision", "acceptance uses current evidence rather than a stale data lookup"),
    ("115-A2-C04", "test_ticket115_integration.Ticket115IntegrationTests.test_owner_task_cancellation_atomically_closes_active_task_and_claim", "owner cancellation is a task control, not a solved result"),
    ("115-A2-C05", "test_ticket115_integration.Ticket115IntegrationTests.test_ticket115_status_domains_are_sealed_and_unknown_is_not_fault", "a capability or delivery gap does not become a fifth task label"),
    ("115-A2-C06", "test_ticket115_tasks.Ticket115TaskEngineTests.test_delivery_unknown_is_an_active_ancillary_fact_not_a_fifth_label", "unknown delivery remains an ancillary active fact"),
    ("115-A2-C07", "test_ticket115_tasks.Ticket115TaskEngineTests.test_solve_requires_acceptance_evidence_to_match_current_revisions", "solved requires acceptance evidence bound to current revisions"),
    # A3: owner-local-day review.
    ("115-A3-C01", "test_ticket115_tasks.Ticket115DailyReviewTests.test_local_day_key_is_timezone_and_dst_aware", "local day uses timezone and DST-aware identity"),
    ("115-A3-C02", "test_ticket115_tasks.Ticket115DailyReviewTests.test_same_day_crash_resumes_pending_then_commits_exactly_once", "same-day recovery resumes one pending review and commits once"),
    ("115-A3-C03", "test_ticket115_tasks.Ticket115DailyReviewTests.test_stale_pending_is_discarded_without_backlog_and_only_current_day_runs", "stale pending work does not create backlog"),
    ("115-A3-C04", "test_ticket115_tasks.Ticket115DailyReviewTests.test_timezone_change_suppresses_an_already_reviewed_local_date", "timezone change does not repeat an already reviewed local date"),
    ("115-A3-C05", "test_ticket115_tasks.Ticket115DailyReviewTests.test_quiet_review_has_no_notification_and_commit_cannot_change_pending", "no-action review remains quiet and immutable at commit"),
    ("115-A3-C06", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a3_c06_same_local_day_replay_does_not_create_a_second_review", "same-local-day replay returns one completed review"),
    # A4: atomic business and outbox persistence.
    ("115-A4-C01", "test_ticket115_storage.Ticket115TypedStorageTests.test_outbox_failure_rolls_back_task_and_review_business_state", "outbox failure rolls back task and review business facts"),
    ("115-A4-C02", "test_ticket115_integration.Ticket115IntegrationTests.test_review_and_outbox_rollback_together", "review and outbox commit atomically"),
    ("115-A4-C03", "test_ticket115_integration.Ticket115IntegrationTests.test_restart_recovers_abandoned_prepare_without_replaying_transport", "abandoned prepare recovers without transport replay"),
    ("115-A4-C04", "test_ticket115_plugin_delivery.Ticket115PluginDeliveryBoundaryTests.test_plugin_alone_sends_the_strict_authorized_wire_intent", "adapter effects occur only through the controlled plugin wire"),
    # A5: immutable, producer-bound delivery evidence.
    ("115-A5-C01", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a5_c01_delivery_evidence_accepts_only_layer_authority", "each evidence layer accepts only its declared producer"),
    ("115-A5-C02", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a5_c02_delivery_evidence_round_trip_preserves_replay_identity", "evidence storage preserves replay identity"),
    ("115-A5-C03", "test_ticket115_delivery.Ticket115DeliveryTests.test_accepted_delivered_and_read_are_distinct_facts", "accepted, delivered, and read remain distinct facts"),
    ("115-A5-C04", "test_ticket115_delivery.Ticket115DeliveryTests.test_rejected_is_an_explicit_interface_fact_not_owner_delivery", "rejected is an interface fact and cannot become owner delivery"),
    ("115-A5-C05", "test_ticket115_delivery.Ticket115DeliveryTests.test_unknown_freezes_automatic_retry_without_erasing_later_proof", "unknown freezes retry without erasing later proof"),
    ("115-A5-C06", "test_ticket115_storage.Ticket115TypedStorageTests.test_outbox_history_rejects_fact_deletion_and_modification", "delivery fact history is append-only"),
    ("115-A5-C07", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a5_c07_production_delivery_fact_exposes_bound_authoritative_evidence", "production delivery facts expose bound authoritative evidence"),
    ("115-A5-C08", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a5_c08_actual_action_requires_the_admitted_event_producer", "actual action requires an admitted-event producer"),
    ("115-A5-C09", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a5_c09_out_of_order_delivery_facts_are_rejected", "out-of-order layer facts are rejected"),
    ("115-A5-C10", "test_ticket115_delivery.Ticket115DeliveryTests.test_unknown_freezes_automatic_retry_without_erasing_later_proof", "duplicate observation replay does not overwrite a prior fact"),
    # A6: currentness, task runtime claim, and unknown freeze.
    ("115-A6-C01", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a6_c01_task_claim_lease_rejects_cross_epoch_and_stale_cas", "runtime claim rejects cross-epoch and stale CAS commits"),
    ("115-A6-C02", "test_ticket115_tasks.Ticket115TaskEngineTests.test_expired_task_lease_can_be_taken_over_but_live_lease_cannot", "live claims are exclusive and expired claims can be taken over"),
    ("115-A6-C03", "test_ticket115_integration.Ticket115IntegrationTests.test_delivery_rechecks_current_evidence_revision_before_adapter", "delivery rechecks current evidence before the adapter"),
    ("115-A6-C04", "test_ticket115_integration.Ticket115IntegrationTests.test_attempt_for_other_approval_does_not_consume_new_approval", "an old approval cannot consume a new approval"),
    ("115-A6-C05", "test_ticket115_integration.Ticket115IntegrationTests.test_restart_recovers_orphan_attempt_without_replaying_transport", "restart recovers an orphan attempt without replaying transport"),
    ("115-A6-C06", "test_ticket115_integration.Ticket115IntegrationTests.test_adapter_exception_freezes_unknown_until_independent_delivery", "adapter exception freezes unknown until independent evidence"),
    ("115-A6-C07", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a6_c07_task_engine_persists_runtime_epoch_claim_and_rejects_old_holder", "runtime epoch claims survive storage and reject old holders"),
    ("115-A6-C08", "test_ticket115_integration.Ticket115IntegrationTests.test_writer_proof_is_rechecked_after_attempt_before_adapter", "writer fence is rechecked immediately before transport"),
    ("115-A6-C09", "test_ticket115_integration.Ticket115IntegrationTests.test_review_commit_rejects_stale_day_and_fresh_state_change", "stale review state is rejected before effect formation"),
    # A7: sealed business status.
    ("115-A7-C01", "test_ticket115_integration.Ticket115IntegrationTests.test_ticket115_status_domains_are_sealed_and_unknown_is_not_fault", "task and delivery facts project into sealed business status"),
    ("115-A7-C02", "test_ticket114_status.Ticket114BusinessStatusTests.test_114_a5_c06_unknown_domain_or_producer_cannot_activate", "unknown domain or producer cannot activate status"),
    ("115-A7-C03", "test_ticket114_status.Ticket114BusinessStatusTests.test_114_a5_c11_identical_fact_replay_is_deterministic_and_emits_no_second_transition", "identical status fact replay emits no second transition"),
    # A8: mandatory, content-free action requests.
    ("115-A8-C01", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a8_c01_mandatory_request_is_content_free", "mandatory request carries no health body"),
    ("115-A8-C02", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a8_c02_mandatory_request_dedupes_replay_and_keeps_new_cause", "mandatory ledger deduplicates one causal state"),
    ("115-A8-C03", "test_ticket114_authority_integration.Ticket114AuthorityIntegrationTests.test_114_a5_c21_status_transition_is_deduplicated_across_restart", "status transition replay remains one causal request"),
    ("115-A8-C04", "test_ticket115_gap_contracts.Ticket115GapContractTests.test_115_a8_c04_status_transition_emits_one_content_free_request", "status transition forms one content-free request"),
    ("115-A8-C05", "test_ticket115_integration.Ticket115IntegrationTests.test_115_a8_c05_business_status_replay_emits_one_mandatory_request", "business-status replay emits one mandatory request for one state transition"),
    ("115-A8-C06", "test_ticket115_integration.Ticket115IntegrationTests.test_not_configured_notification_never_reaches_adapter", "ordinary notification suppression does not create a hidden delivery"),
)


_CASE_ID = re.compile(r"^115-A[1-8]-C[0-9]{2}$")


def validate_case_registry(*, resolve_tests: bool = False) -> None:
    """Validate case shape, ordering, and optionally every referenced test."""

    if not CASE_REGISTRY:
        raise AssertionError("Ticket 115 case registry is empty")
    ids = [case_id for case_id, _, _ in CASE_REGISTRY]
    if len(ids) != len(set(ids)):
        raise AssertionError("Ticket 115 case IDs must be unique")
    for case_id, test_path, observable in CASE_REGISTRY:
        if not _CASE_ID.fullmatch(case_id):
            raise AssertionError(f"invalid Ticket 115 case ID: {case_id}")
        if type(test_path) is not str or test_path.count(".") < 2:
            raise AssertionError(f"invalid test path for {case_id}")
        if type(observable) is not str or not observable.strip():
            raise AssertionError(f"missing observable description for {case_id}")
        if resolve_tests:
            module_name, class_name, method_name = test_path.rsplit(".", 2)
            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError:
                module = importlib.import_module("tests." + module_name)
            target = getattr(module, class_name, None)
            if target is None or not callable(getattr(target, method_name, None)):
                raise AssertionError(f"unresolved test target for {case_id}: {test_path}")


validate_case_registry()

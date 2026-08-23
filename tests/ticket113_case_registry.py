"""Ordered Ticket 113 acceptance cases.

The registry is deliberately data-only.  Each entry names one independently
visible unittest method; implementation evidence can therefore be generated
without treating a verdict-level aggregate assertion as case coverage.
"""

CASE_REGISTRY = (
    # 113-A1 -- final-wire route and consent authority.
    ("113-A1-C01", "test_ticket113_strict_port.test_113_a1_c01_provider_drift_fails_before_effect", "provider drift fails closed"),
    ("113-A1-C02", "test_ticket113_strict_port.test_113_a1_c02_base_url_drift_fails_before_effect", "canonical base URL drift fails closed"),
    ("113-A1-C03", "test_ticket113_strict_port.test_113_a1_c03_api_mode_drift_fails_before_effect", "API mode drift fails closed"),
    ("113-A1-C04", "test_ticket113_strict_port.test_113_a1_c04_requested_model_drift_fails_before_effect", "requested model drift fails closed"),
    ("113-A1-C05", "test_ticket113_strict_port.test_113_a1_c05_configuration_generation_drift_fails_before_effect", "configuration generation drift fails closed"),
    ("113-A1-C06", "test_ticket113_strict_port.test_113_a1_c06_owner_consent_drift_fails_before_effect", "owner-consent fingerprint drift fails closed"),
    ("113-A1-C07", "test_ticket113_strict_port.test_113_a1_c07_fallback_fact_rejects_candidate", "fallback fact rejects the candidate"),
    ("113-A1-C08", "test_ticket113_contract.test_113_a1_c08_request_contract_binds_exact_final_wire_authority", "request contract binds all final-wire authority fields"),
    ("113-A1-C09", "test_ticket113_strict_port.test_113_a1_c09_forbidden_bypass_is_observed_and_denied", "raw LLM and network or tool bypasses are denied"),

    # 113-A2 -- strict terminality, structure, capacity and actual model.
    ("113-A2-C01", "test_ticket113_strict_port.test_113_a2_c01_completed_strict_result_produces_one_candidate", "completed strict result produces a candidate"),
    ("113-A2-C02", "test_ticket113_strict_port.test_113_a2_c02_incomplete_result_produces_no_candidate", "incomplete result produces no candidate"),
    ("113-A2-C03", "test_ticket113_strict_port.test_113_a2_c03_failed_result_produces_no_candidate", "failed result produces no candidate"),
    ("113-A2-C04", "test_ticket113_strict_port.test_113_a2_c04_unknown_result_produces_no_candidate", "unknown result produces no candidate"),
    ("113-A2-C05", "test_ticket113_strict_port.test_113_a2_c05_truncated_result_produces_no_candidate", "truncated result produces no candidate"),
    ("113-A2-C06", "test_ticket113_strict_port.test_113_a2_c06_schema_error_produces_no_candidate", "strict schema error produces no candidate"),
    ("113-A2-C07", "test_ticket113_strict_port.test_113_a2_c07_capacity_shortfall_fails_before_effect", "capacity shortfall fails before an effect"),
    ("113-A2-C08", "test_ticket113_strict_port.test_113_a2_c08_actual_model_drift_rejects_candidate", "actual model drift rejects the candidate"),
    ("113-A2-C09", "test_ticket113_contract.test_113_a2_c09_transport_result_contract_preserves_four_terminal_states", "transport result contract preserves four terminal states"),
    ("113-A2-C10", "test_ticket113_strict_port.test_113_a2_c10_proxy_signals_do_not_infer_completion", "text stop usage and no-error do not infer completion"),

    # 113-A3 -- owner-independent governed knowledge.
    ("113-A3-C01", "test_ticket113_knowledge.test_113_a3_c01_publication_is_owner_independent", "publication is owner independent"),
    ("113-A3-C02", "test_ticket113_knowledge.test_113_a3_c02_content_hash_is_immutable", "content hash is immutable"),
    ("113-A3-C03", "test_ticket113_knowledge.test_113_a3_c03_release_version_is_immutable", "release version is immutable"),
    ("113-A3-C04", "test_ticket113_knowledge.test_113_a3_c04_expired_release_returns_gap", "expired release returns a gap"),
    ("113-A3-C05", "test_ticket113_knowledge.test_113_a3_c05_withdrawn_release_returns_gap", "withdrawn release returns a gap"),
    ("113-A3-C06", "test_ticket113_knowledge.test_113_a3_c06_rights_gap_blocks_release", "rights gap blocks release"),
    ("113-A3-C07", "test_ticket113_knowledge.test_113_a3_c07_chinese_status_gap_blocks_release", "Chinese-language gap blocks release"),
    ("113-A3-C08", "test_ticket113_knowledge.test_113_a3_c08_professional_review_gap_blocks_release", "professional review gap blocks release"),
    ("113-A3-C09", "test_ticket113_contract.test_113_a3_c09_publication_input_rejects_owner_derived_fields", "publication input rejects owner-derived fields"),
    ("113-A3-C10", "test_ticket113_contract.test_113_a3_c10_release_contract_is_strict_and_frozen", "release contract is strict and frozen"),
    ("113-A3-C11", "test_ticket113_knowledge.test_113_a3_c11_missing_knowledge_never_fetches_on_demand", "missing knowledge never fetches on demand"),

    # 113-A4 -- current, typed references and complete candidate sections.
    ("113-A4-C01", "test_ticket113_nondiagnostic.test_113_a4_c01_current_card_references_are_accepted", "current card references are accepted"),
    ("113-A4-C02", "test_ticket113_nondiagnostic.test_113_a4_c02_reference_types_cannot_be_interchanged", "personal and knowledge reference types cannot be interchanged"),
    ("113-A4-C03", "test_ticket113_nondiagnostic.test_113_a4_c03_missing_support_is_rejected", "missing support section is rejected"),
    ("113-A4-C04", "test_ticket113_nondiagnostic.test_113_a4_c04_missing_opposition_is_rejected", "missing opposition section is rejected"),
    ("113-A4-C05", "test_ticket113_nondiagnostic.test_113_a4_c05_missing_unknown_is_rejected", "missing unknown section is rejected"),
    ("113-A4-C06", "test_ticket113_nondiagnostic.test_113_a4_c06_missing_limitation_is_rejected", "missing limitation section is rejected"),
    ("113-A4-C07", "test_ticket113_nondiagnostic.test_113_a4_c07_stale_card_is_rejected", "stale card is rejected"),
    ("113-A4-C08", "test_ticket113_nondiagnostic.test_113_a4_c08_forged_identifier_is_rejected", "forged evidence knowledge claim or template ID is rejected"),
    ("113-A4-C09", "test_ticket113_contract.test_113_a4_c09_candidate_contract_forbids_model_draft_text", "candidate contract forbids model draft text"),

    # 113-A5 -- deterministic, approved rendering only.
    ("113-A5-C01", "test_ticket113_nondiagnostic.test_113_a5_c01_replay_renders_identical_reply", "replay renders an identical reply"),
    ("113-A5-C02", "test_ticket113_nondiagnostic.test_113_a5_c02_render_order_is_stable", "render order is stable"),
    ("113-A5-C03", "test_ticket113_nondiagnostic.test_113_a5_c03_illegal_medical_atom_cannot_be_constructed", "illegal medical atom cannot be constructed"),
    ("113-A5-C04", "test_ticket113_nondiagnostic.test_113_a5_c04_illegal_medical_atom_cannot_be_parsed", "illegal medical atom cannot be parsed"),
    ("113-A5-C05", "test_ticket113_nondiagnostic.test_113_a5_c05_candidate_is_not_persisted", "model candidate is not persisted"),
    ("113-A5-C06", "test_ticket113_contract.test_113_a5_c06_claim_atom_contract_excludes_medical_conclusions", "claim atom contract excludes medical conclusions"),
    ("113-A5-C07", "test_ticket113_contract.test_113_a5_c07_claim_atom_parser_rejects_illegal_kind", "claim atom parser rejects illegal kinds"),
    ("113-A5-C08", "test_ticket113_nondiagnostic.test_113_a5_c08_owner_and_general_knowledge_boundaries_remain_visible", "rendering keeps owner facts and general knowledge separate"),

    # 113-A6 -- existing effect, writer-fence, daily-turn and cursor authority.
    ("113-A6-C01", "test_ticket113_authority_integration.test_113_a6_c01_pre_call_reject_commits_failed_closed_without_body", "pre-call reject commits a body-free failed-closed result"),
    ("113-A6-C02", "test_ticket113_authority_integration.test_113_a6_c02_explicit_model_failure_commits_failed_closed_without_body", "explicit model failure commits a body-free failed-closed result"),
    ("113-A6-C03", "test_ticket113_authority_integration.test_113_a6_c03_effect_response_loss_freezes_retry", "effect response loss freezes retry"),
    ("113-A6-C04", "test_ticket113_authority_integration.test_113_a6_c04_current_head_unknown_freezes_retry", "current-head unknown freezes retry"),
    ("113-A6-C05", "test_ticket113_authority_integration.test_113_a6_c05_finalize_unknown_freezes_retry", "finalize unknown freezes retry"),
    ("113-A6-C06", "test_ticket113_authority_integration.test_113_a6_c06_replay_never_creates_a_second_effect_or_reply", "replay never creates a second effect or reply"),
    ("113-A6-C07", "test_ticket113_authority_integration.test_113_a6_c07_known_no_effect_failure_releases_cursor", "known no-effect failure releases the cursor"),
    ("113-A6-C08", "test_ticket113_authority_integration.test_113_a6_c08_unknown_effect_freezes_cursor", "unknown effect freezes the cursor"),
)

CONTRACT_CASE_IDS = frozenset(
    {
        "113-A1-C08",
        "113-A2-C09",
        "113-A3-C09",
        "113-A3-C10",
        "113-A4-C09",
        "113-A5-C06",
        "113-A5-C07",
    }
)

"""Deterministic Ticket 116 safety and staged-diagnosis domain helpers.

This module contains no I/O and owns no external authority.  It validates the
immutable constructor assets, derives the public diagnostic phase, and checks
the synthetic BMI candidate used by the isolated acceptance workflow.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Mapping

from .authority import AuthorityValidationError, validate_opaque_text


_SHA256_PREFIX = "sha256:"
_SCOPE_STATES = frozenset({"staged", "active"})


def _mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AuthorityValidationError(f"invalid {name}")
    return value


def _sha256(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(_SHA256_PREFIX)
        or len(value) != len(_SHA256_PREFIX) + 64
    ):
        raise AuthorityValidationError(f"invalid {name}")
    try:
        int(value.removeprefix(_SHA256_PREFIX), 16)
    except ValueError as exc:
        raise AuthorityValidationError(f"invalid {name}") from exc
    return value


def canonical_json_copy(value: object) -> object:
    try:
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    except (TypeError, ValueError) as exc:
        raise AuthorityValidationError("invalid Ticket 116 managed value") from exc


def validate_assets(value: object) -> dict[str, object]:
    """Return a primitive-safe immutable snapshot of constructor assets."""

    assets = _mapping(canonical_json_copy(value), "safety diagnostic assets")
    if assets.get("asset_contract") != "safety-diagnostic-assets-v1":
        raise AuthorityValidationError("invalid safety diagnostic asset contract")
    if type(assets.get("synthetic")) is not bool:
        raise AuthorityValidationError("invalid safety diagnostic synthetic flag")
    if type(assets.get("production_approval")) is not bool:
        raise AuthorityValidationError("invalid safety diagnostic approval flag")
    _sha256(assets.get("release_digest"), "safety diagnostic release digest")
    minimum = assets.get("minimum_help_bundle")
    if minimum is not None:
        _validate_minimum_help_bundle(minimum)
    safety = assets.get("safety_rule_bundle")
    if safety is not None:
        _validate_safety_rule_bundle(safety)
    scope = assets.get("diagnostic_scope_bundle")
    if scope is not None:
        _validate_scope_bundle(scope)
    return assets


def _validate_minimum_help_bundle(value: object) -> None:
    bundle = _mapping(value, "minimum help bundle")
    validate_opaque_text(bundle.get("bundle_id"), "minimum help bundle identifier")
    validate_opaque_text(bundle.get("version"), "minimum help bundle version")
    _sha256(bundle.get("bundle_hash"), "minimum help bundle hash")
    if bundle.get("language") != "zh-CN":
        raise AuthorityValidationError("minimum help bundle language unavailable")
    templates = _mapping(bundle.get("templates"), "minimum help templates")
    for name in ("minimum_help", "danger_owner", "danger_unknown", "out_of_scope"):
        template = _mapping(templates.get(name), f"minimum help template {name}")
        validate_opaque_text(template.get("template_ref"), "safety template reference")
        validate_opaque_text(template.get("text"), "safety template text")


def _validate_safety_rule_bundle(value: object) -> None:
    bundle = _mapping(value, "safety rule bundle")
    validate_opaque_text(bundle.get("bundle_id"), "safety rule bundle identifier")
    validate_opaque_text(bundle.get("version"), "safety rule bundle version")
    _sha256(bundle.get("bundle_hash"), "safety rule bundle hash")
    if type(bundle.get("synthetic")) is not bool:
        raise AuthorityValidationError("invalid safety rule synthetic flag")
    rules = bundle.get("rules")
    if type(rules) is not list:
        raise AuthorityValidationError("invalid safety rules")
    for item in rules:
        rule = _mapping(item, "safety rule")
        validate_opaque_text(rule.get("input"), "safety rule input")
        validate_opaque_text(rule.get("branch"), "safety rule branch")


def _validate_scope_bundle(value: object) -> None:
    bundle = _mapping(value, "diagnostic scope bundle")
    validate_opaque_text(bundle.get("scope_id"), "diagnostic scope identifier")
    validate_opaque_text(bundle.get("version"), "diagnostic scope version")
    _sha256(bundle.get("bundle_hash"), "diagnostic scope bundle hash")
    _sha256(bundle.get("release_digest"), "diagnostic scope release digest")
    if bundle.get("persistent_state") not in _SCOPE_STATES:
        raise AuthorityValidationError("invalid diagnostic scope state")
    if type(bundle.get("synthetic")) is not bool or type(bundle.get("medical_use")) is not bool:
        raise AuthorityValidationError("invalid diagnostic scope use flags")
    _mapping(bundle.get("prerequisites"), "diagnostic prerequisites")
    _mapping(bundle.get("population"), "diagnostic population")
    _mapping(bundle.get("measurements"), "diagnostic measurements")
    formula = _mapping(bundle.get("formula"), "diagnostic formula")
    if formula.get("expression") != "weight_kg / height_m^2":
        raise AuthorityValidationError("unsupported diagnostic formula")
    if formula.get("result_unit") != "kg/m^2":
        raise AuthorityValidationError("unsupported diagnostic result unit")
    if formula.get("comparison_uses_unrounded_value") is not True:
        raise AuthorityValidationError("diagnostic comparison precision unavailable")
    thresholds = bundle.get("thresholds")
    if type(thresholds) is not list or not thresholds:
        raise AuthorityValidationError("invalid diagnostic thresholds")
    for item in thresholds:
        threshold = _mapping(item, "diagnostic threshold")
        validate_opaque_text(threshold.get("label"), "diagnostic threshold label")
        try:
            Decimal(str(threshold.get("minimum_bmi")))
        except InvalidOperation as exc:
            raise AuthorityValidationError("invalid diagnostic threshold") from exc


def minimum_help_current(assets: Mapping[str, object]) -> bool:
    bundle = assets.get("minimum_help_bundle")
    if type(bundle) is not dict:
        return False
    return (
        bundle.get("language") == "zh-CN"
        and bundle.get("content_rights_status") in {"approved", "approved-synthetic"}
        and bundle.get("review_status") in {"approved", "approved-synthetic"}
        and bundle.get("parse_status") == "valid"
    )


def safety_rules_current(assets: Mapping[str, object]) -> bool:
    bundle = assets.get("safety_rule_bundle")
    return type(bundle) is dict and (
        bundle.get("rights_status") in {"approved", "approved-synthetic"}
        and bundle.get("review_status") in {"approved", "approved-synthetic"}
    )


def diagnostic_prerequisites_current(assets: Mapping[str, object]) -> bool:
    bundle = assets.get("diagnostic_scope_bundle")
    if type(bundle) is not dict:
        return False
    prerequisites = bundle.get("prerequisites")
    return type(prerequisites) is dict and bool(prerequisites) and all(
        value is True for value in prerequisites.values()
    )


def diagnostic_measurement_eligible(
    evidence: Mapping[str, object],
    scope_bundle: Mapping[str, object],
    *,
    observed_at_utc: datetime,
) -> bool:
    """Apply the bundle-bound BMI population and measurement exclusions."""

    population = scope_bundle.get("population")
    measurements = scope_bundle.get("measurements")
    if type(population) is not dict or type(measurements) is not dict:
        return False
    minimum_age = population.get("minimum_age_years")
    age = evidence.get("age_years")
    reliability_required = measurements.get("reliability_required")
    maximum_age = measurements.get("maximum_age_seconds")
    if (
        type(minimum_age) is not int
        or type(age) is not int
        or age < minimum_age
        or type(reliability_required) is not bool
        or evidence.get("reliable") is not reliability_required
        or type(maximum_age) is not int
        or maximum_age < 0
        or type(observed_at_utc) is not datetime
        or observed_at_utc.tzinfo is None
    ):
        return False
    pregnancy_status = evidence.get("pregnancy_status")
    if type(pregnancy_status) is not str:
        return False
    if population.get("pregnancy_allowed") is not True and pregnancy_status != "not-pregnant":
        return False
    try:
        measured_at = datetime.fromisoformat(str(evidence.get("measured_at_utc")))
    except (TypeError, ValueError):
        return False
    if measured_at.tzinfo is None:
        return False
    age_seconds = (
        observed_at_utc.astimezone(timezone.utc)
        - measured_at.astimezone(timezone.utc)
    ).total_seconds()
    return 0 <= age_seconds <= maximum_age


def template_ref(assets: Mapping[str, object], name: str) -> str:
    minimum = _mapping(assets.get("minimum_help_bundle"), "minimum help bundle")
    templates = _mapping(minimum.get("templates"), "minimum help templates")
    template = _mapping(templates.get(name), "minimum help template")
    return validate_opaque_text(template.get("template_ref"), "safety template reference")


def scope_wire(
    state: Mapping[str, object],
    assets: Mapping[str, object],
    *,
    acceptance_authorized: bool,
) -> dict[str, object]:
    scope = _mapping(assets.get("diagnostic_scope_bundle"), "diagnostic scope bundle")
    persistent = state["scope_state"]
    if persistent == "active" and diagnostic_prerequisites_current(assets):
        effective = "active"
    elif acceptance_authorized and diagnostic_prerequisites_current(assets):
        effective = "acceptance-authorized"
    elif diagnostic_prerequisites_current(assets):
        effective = "activation-ready"
    else:
        effective = "staged"
    return {
        "scope_id": scope["scope_id"],
        "bundle_hash": scope["bundle_hash"],
        "release_digest": scope["release_digest"],
        "persistent_state": "active" if effective == "active" else "staged",
        "effective_phase": effective,
        "acceptance_evidence_ref": state.get("acceptance_evidence_ref"),
        "synthetic": scope["synthetic"],
        "medical_use": scope["medical_use"],
    }


def owner_result(template_reference: str) -> dict[str, object]:
    return {
        "template_ref": template_reference,
        "rendering": {"language": "zh-CN", "deterministic": True},
    }


def safety_branch(facts: object) -> str:
    value = _mapping(facts, "safety facts")
    if value.get("safety_capability") != "available":
        return "safety-capability-unavailable"
    if value.get("danger") == "confirmed":
        return "danger-escalation"
    if value.get("danger") not in {"not-present", "confirmed"}:
        return "danger-unknown"
    if value.get("scope") != "in-scope":
        return "out-of-scope"
    return "in-scope"


def recompute_bmi(
    evidence: Mapping[str, object],
    scope_bundle: Mapping[str, object],
) -> tuple[str, str, str]:
    try:
        height = Decimal(str(evidence["height_m"]))
        weight = Decimal(str(evidence["weight_kg"]))
    except (KeyError, InvalidOperation) as exc:
        raise AuthorityValidationError("invalid BMI physical quantities") from exc
    if height <= 0 or weight <= 0:
        raise AuthorityValidationError("invalid BMI physical quantities")
    bmi = weight / (height * height)
    thresholds = scope_bundle.get("thresholds")
    if type(thresholds) is not list:
        raise AuthorityValidationError("invalid BMI thresholds")
    selected: tuple[Decimal, str] | None = None
    for item in thresholds:
        threshold = _mapping(item, "BMI threshold")
        minimum = Decimal(str(threshold["minimum_bmi"]))
        label = validate_opaque_text(threshold["label"], "BMI threshold label")
        if minimum <= bmi and (selected is None or minimum > selected[0]):
            selected = (minimum, label)
    if selected is None:
        raise AuthorityValidationError("BMI classification unavailable")
    formula = _mapping(scope_bundle.get("formula"), "BMI formula")
    places = formula.get("display_decimal_places")
    if type(places) is not int or places < 0 or places > 6:
        raise AuthorityValidationError("invalid BMI display precision")
    quantum = Decimal(1).scaleb(-places)
    unrounded = format(bmi, "f")
    display = format(bmi.quantize(quantum, rounding=ROUND_HALF_UP), f".{places}f")
    return unrounded, display, selected[1]

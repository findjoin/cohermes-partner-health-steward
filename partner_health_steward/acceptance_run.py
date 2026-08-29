"""Ticket 119 release-bound acceptance-run orchestration.

This module deliberately owns only ordered acceptance evidence.  It neither
executes a business effect itself nor becomes an activation, current-head, or
delivery authority.  A target-local adapter is the sole external seam.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .host_contract import ReleaseManifest


_GATES = tuple(f"119-G{index:02d}" for index in range(1, 13))
_APPROVAL_GATES = frozenset({"119-G08", "119-G10", "119-G11", "119-G12"})
_RESULTS = frozenset({"passed", "failed", "cannot-confirm", "not-authorized"})
_EFFECT_STAGES = (
    "formed",
    "committed",
    "attempted",
    "interface_accepted",
    "delivered",
    "read_or_action",
    "correction",
    "unknown",
)
_G12_RECEIPTS = (
    "run_receipt_ref",
    "owner_acceptance_receipt_ref",
    "contact_acceptance_receipt_ref",
    "contact_correction_receipt_ref",
    "active_path_receipt_ref",
)
_OBSERVATION_FIELDS = frozenset(
    {
        "contract",
        "release_digest",
        "run_id",
        "gate_id",
        "execution_key",
        "environment_class",
        "observed_at_utc",
        "executor_digest",
        "step_digest",
        "fixture_digest",
        "result",
        "evidence_refs",
        "blocking_evidence_refs",
        "rollback_ref",
        "rollback_status",
        "impact_ref",
        "next_step_ref",
        "acceptance_receipt_refs",
        "effect_stage_refs",
    }
)
_REPORT_FIELDS = frozenset(
    {
        "contract",
        "release_digest",
        "run_id",
        "executed_at_utc",
        "environment_class",
        "target_ref",
        "approval_refs",
        "evidence_scope",
        "gates",
        "technical_gate_verdict",
        "target_binding_verdict",
        "real_interface_verdict",
        "deployment",
        "diagnostic_scope_phase",
        "active",
        "product_acceptance",
        "stable_operation",
        "run_verdict",
        "report_digest",
    }
)
_EXECUTED_GATE_FIELDS = frozenset(
    {
        "gate_id",
        "result",
        "execution_key",
        "target_ref",
        "approval_ref",
        "environment_class",
        "observed_at_utc",
        "executor_digest",
        "step_digest",
        "fixture_digest",
        "evidence_refs",
        "blocking_evidence_refs",
        "rollback_ref",
        "rollback_status",
        "impact_ref",
        "next_step_ref",
        "acceptance_receipt_refs",
        "effect_stage_refs",
        "blocked_by_gate",
    }
)
_BLOCKED_GATE_FIELDS = frozenset(
    {
        "gate_id",
        "result",
        "execution_key",
        "target_ref",
        "approval_ref",
        "environment_class",
        "observed_at_utc",
        "executor_digest",
        "step_digest",
        "fixture_digest",
        "evidence_refs",
        "blocking_evidence_refs",
        "rollback_ref",
        "rollback_status",
        "impact_ref",
        "next_step_ref",
        "acceptance_receipt_refs",
        "effect_stage_refs",
        "blocked_by_gate",
    }
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_OPAQUE_REF = re.compile(r"[^\s\\/]{1,256}\Z")


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _plain_string(value: object) -> str | None:
    return value if type(value) is str and value else None


def _opaque_ref(value: object) -> str | None:
    if type(value) is not str or _OPAQUE_REF.fullmatch(value) is None:
        return None
    return value


def _digest_ref(value: object) -> str | None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        return None
    return value


def _ref_list(value: object) -> list[str] | None:
    if type(value) is not list:
        return None
    result: list[str] = []
    for item in value:
        reference = _opaque_ref(item)
        if reference is None:
            return None
        result.append(reference)
    if len(result) != len(set(result)):
        return None
    return result


def _fixture_environment(environment_class: str) -> bool:
    normalized = environment_class.lower()
    return any(
        marker in normalized
        for marker in ("synthetic", "fixture", "deny-network", "test")
    )


def _execution_key(release_digest: str, run_id: str, gate_id: str) -> str:
    identity = {
        "contract": "ticket119-gate-execution-key-v1",
        "release_digest": release_digest,
        "run_id": run_id,
        "gate_id": gate_id,
    }
    return "ticket119:" + _digest(identity).removeprefix("sha256:")


@dataclass(frozen=True, repr=False)
class AcceptanceRunReport:
    """An immutable release/run-bound acceptance report."""

    _wire: dict[str, object]

    def to_wire(self) -> dict[str, object]:
        return copy.deepcopy(self._wire)


class AcceptanceRunContract:
    """Run the fixed Ticket 119 gate sequence through one external seam."""

    def run(
        self,
        current_release_manifest: ReleaseManifest,
        gate_executor: object,
        run_context: Mapping[str, object],
    ) -> AcceptanceRunReport:
        manifest_wire = self._manifest_wire(current_release_manifest)
        context = self._context(run_context)
        existing = context["existing_report"]
        if existing is not None:
            if self._valid_replay(existing, manifest_wire, context):
                return AcceptanceRunReport(copy.deepcopy(existing))
            return AcceptanceRunReport(self._rejected_replay(manifest_wire, context))

        execute = getattr(gate_executor, "execute", None)
        if not callable(execute):
            raise ValueError("gate executor is unavailable")

        gates: list[dict[str, object]] = []
        frontier: str | None = None
        for gate_id in _GATES:
            approval_ref = context["approval_refs"].get(gate_id)
            if frontier is not None:
                gates.append(
                    self._blocked_gate(
                        gate_id,
                        manifest_wire["release_digest"],
                        context,
                        approval_ref,
                        frontier,
                    )
                )
                continue
            if gate_id in _APPROVAL_GATES and approval_ref is None:
                gate = self._not_authorized_gate(
                    gate_id,
                    manifest_wire["release_digest"],
                    context,
                    approval_ref,
                )
            else:
                gate = self._execute_gate(
                    execute,
                    gate_id,
                    manifest_wire["release_digest"],
                    context,
                    approval_ref,
                )
            gates.append(gate)
            if gate["result"] != "passed":
                frontier = gate_id
        return AcceptanceRunReport(self._report(manifest_wire, context, gates))

    @staticmethod
    def _manifest_wire(value: object) -> dict[str, object]:
        if not isinstance(value, ReleaseManifest):
            raise ValueError("current release manifest must be a ReleaseManifest")
        wire = value.to_wire()
        if type(wire) is not dict:
            raise ValueError("current release manifest is invalid")
        digest = _digest_ref(wire.get("release_digest"))
        if wire.get("contract") != "ticket118-release-manifest-v1" or digest is None:
            raise ValueError("current release manifest is invalid")
        identity = copy.deepcopy(wire)
        identity.pop("release_digest", None)
        try:
            expected = _digest(identity)
        except (TypeError, ValueError) as exc:
            raise ValueError("current release manifest is invalid") from exc
        if expected != digest:
            raise ValueError("current release manifest digest is invalid")
        return wire

    @staticmethod
    def _context(value: Mapping[str, object]) -> dict[str, Any]:
        if type(value) is not dict or set(value) != {
            "contract",
            "run_id",
            "executed_at_utc",
            "environment_class",
            "target_ref",
            "approval_refs",
            "existing_report",
        }:
            raise ValueError("acceptance run context is invalid")
        if value.get("contract") != "ticket119-run-context-v1":
            raise ValueError("acceptance run context is invalid")
        run_id = _opaque_ref(value.get("run_id"))
        executed_at_utc = _plain_string(value.get("executed_at_utc"))
        environment_class = _opaque_ref(value.get("environment_class"))
        target_ref = _opaque_ref(value.get("target_ref"))
        if None in {run_id, executed_at_utc, environment_class, target_ref}:
            raise ValueError("acceptance run context is invalid")
        approvals = value.get("approval_refs")
        if type(approvals) is not dict or not set(approvals).issubset(_APPROVAL_GATES):
            raise ValueError("acceptance approval refs are invalid")
        normalized_approvals: dict[str, str] = {}
        for gate_id, approval_ref in approvals.items():
            if type(gate_id) is not str:
                raise ValueError("acceptance approval refs are invalid")
            normalized = _opaque_ref(approval_ref)
            if normalized is None:
                raise ValueError("acceptance approval refs are invalid")
            normalized_approvals[gate_id] = normalized
        existing = value.get("existing_report")
        if existing is not None and type(existing) is not dict:
            raise ValueError("existing acceptance report is invalid")
        return {
            "run_id": run_id,
            "executed_at_utc": executed_at_utc,
            "environment_class": environment_class,
            "target_ref": target_ref,
            "approval_refs": normalized_approvals,
            "existing_report": None if existing is None else copy.deepcopy(existing),
        }

    def _execute_gate(
        self,
        execute: object,
        gate_id: str,
        release_digest: str,
        context: Mapping[str, Any],
        approval_ref: str | None,
    ) -> dict[str, object]:
        request = {
            "contract": "ticket119-gate-request-v1",
            "release_digest": release_digest,
            "run_id": context["run_id"],
            "gate_id": gate_id,
            "execution_key": _execution_key(release_digest, context["run_id"], gate_id),
            "environment_class": context["environment_class"],
            "executed_at_utc": context["executed_at_utc"],
            "target_ref": context["target_ref"],
            "approval_ref": approval_ref,
        }
        try:
            observation = execute(copy.deepcopy(request))  # type: ignore[operator]
        except Exception:
            return self._cannot_confirm_gate(gate_id, release_digest, context, approval_ref)
        return self._observation_gate(
            observation,
            request,
            gate_id,
            release_digest,
            context,
            approval_ref,
        )

    def _observation_gate(
        self,
        observation: object,
        request: Mapping[str, object],
        gate_id: str,
        release_digest: str,
        context: Mapping[str, Any],
        approval_ref: str | None,
    ) -> dict[str, object]:
        if type(observation) is not dict or frozenset(observation) != _OBSERVATION_FIELDS:
            return self._cannot_confirm_gate(gate_id, release_digest, context, approval_ref)
        if (
            observation.get("contract") != "ticket119-gate-observation-v1"
            or observation.get("release_digest") != release_digest
            or observation.get("run_id") != context["run_id"]
            or observation.get("gate_id") != gate_id
            or observation.get("execution_key") != request["execution_key"]
            or observation.get("environment_class") != context["environment_class"]
            or observation.get("observed_at_utc") != context["executed_at_utc"]
        ):
            return self._cannot_confirm_gate(gate_id, release_digest, context, approval_ref)
        result = observation.get("result")
        if result not in _RESULTS:
            return self._cannot_confirm_gate(gate_id, release_digest, context, approval_ref)
        executor_digest = _digest_ref(observation.get("executor_digest"))
        step_digest = _digest_ref(observation.get("step_digest"))
        fixture_digest = _digest_ref(observation.get("fixture_digest"))
        evidence_refs = _ref_list(observation.get("evidence_refs"))
        blocking_refs = _ref_list(observation.get("blocking_evidence_refs"))
        rollback_ref = _opaque_ref(observation.get("rollback_ref"))
        rollback_status = _opaque_ref(observation.get("rollback_status"))
        impact_ref = _opaque_ref(observation.get("impact_ref"))
        next_step_ref = _opaque_ref(observation.get("next_step_ref"))
        if any(
            value is None
            for value in (
                executor_digest,
                step_digest,
                fixture_digest,
                evidence_refs,
                blocking_refs,
                rollback_ref,
                rollback_status,
                impact_ref,
                next_step_ref,
            )
        ):
            return self._cannot_confirm_gate(gate_id, release_digest, context, approval_ref)
        effect_refs = self._effect_stage_refs(observation.get("effect_stage_refs"), gate_id)
        receipt_refs = self._receipt_refs(
            observation.get("acceptance_receipt_refs"), gate_id
        )
        if effect_refs is None or receipt_refs is None:
            return self._cannot_confirm_gate(gate_id, release_digest, context, approval_ref)
        if gate_id == "119-G08" and blocking_refs:
            result = "cannot-confirm"
        if gate_id in {"119-G11", "119-G12"} and (
            effect_refs["unknown"] is not None
            or (
                effect_refs["interface_accepted"] is not None
                and (
                    effect_refs["delivered"] is None
                    or effect_refs["read_or_action"] is None
                )
            )
        ):
            result = "cannot-confirm"
        if gate_id == "119-G12" and result == "passed" and receipt_refs is None:
            result = "cannot-confirm"
        return {
            "gate_id": gate_id,
            "result": result,
            "execution_key": request["execution_key"],
            "target_ref": context["target_ref"],
            "approval_ref": approval_ref,
            "environment_class": context["environment_class"],
            "observed_at_utc": context["executed_at_utc"],
            "executor_digest": executor_digest,
            "step_digest": step_digest,
            "fixture_digest": fixture_digest,
            "evidence_refs": evidence_refs,
            "blocking_evidence_refs": blocking_refs,
            "rollback_ref": rollback_ref,
            "rollback_status": rollback_status,
            "impact_ref": impact_ref,
            "next_step_ref": next_step_ref,
            "acceptance_receipt_refs": (
                receipt_refs if gate_id == "119-G12" else None
            ),
            "effect_stage_refs": (
                effect_refs if gate_id in {"119-G11", "119-G12"} else None
            ),
            "blocked_by_gate": None,
        }

    @staticmethod
    def _effect_stage_refs(value: object, gate_id: str) -> dict[str, str | None] | None:
        if gate_id not in {"119-G11", "119-G12"}:
            return {} if value is None else None
        if type(value) is not dict or set(value) != set(_EFFECT_STAGES):
            return None
        normalized: dict[str, str | None] = {}
        seen: set[str] = set()
        for stage in _EFFECT_STAGES:
            stage_ref = value[stage]
            if stage_ref is not None:
                stage_ref = _opaque_ref(stage_ref)
                if stage_ref is None or stage_ref in seen:
                    return None
                seen.add(stage_ref)
            normalized[stage] = stage_ref
        return normalized

    @staticmethod
    def _receipt_refs(value: object, gate_id: str) -> dict[str, str] | None:
        if gate_id != "119-G12":
            return {} if value is None else None
        if type(value) is not dict or set(value) != set(_G12_RECEIPTS):
            return None
        normalized: dict[str, str] = {}
        for receipt in _G12_RECEIPTS:
            receipt_ref = _opaque_ref(value[receipt])
            if receipt_ref is None:
                return None
            normalized[receipt] = receipt_ref
        if len(set(normalized.values())) != len(normalized):
            return None
        return normalized

    def _not_authorized_gate(
        self,
        gate_id: str,
        release_digest: str,
        context: Mapping[str, Any],
        approval_ref: str | None,
    ) -> dict[str, object]:
        gate = self._cannot_confirm_gate(gate_id, release_digest, context, approval_ref)
        gate["result"] = "not-authorized"
        gate["rollback_status"] = "not-authorized"
        gate["impact_ref"] = "impact:authorization-required"
        gate["next_step_ref"] = "next:obtain-current-approval"
        return gate

    @staticmethod
    def _cannot_confirm_gate(
        gate_id: str,
        release_digest: str,
        context: Mapping[str, Any],
        approval_ref: str | None,
    ) -> dict[str, object]:
        return {
            "gate_id": gate_id,
            "result": "cannot-confirm",
            "execution_key": _execution_key(release_digest, context["run_id"], gate_id),
            "target_ref": context["target_ref"],
            "approval_ref": approval_ref,
            "environment_class": context["environment_class"],
            "observed_at_utc": context["executed_at_utc"],
            "executor_digest": None,
            "step_digest": None,
            "fixture_digest": None,
            "evidence_refs": [],
            "blocking_evidence_refs": [],
            "rollback_ref": None,
            "rollback_status": "cannot-confirm",
            "impact_ref": "impact:gate-evidence-unavailable",
            "next_step_ref": "next:stop-and-create-new-run",
            "acceptance_receipt_refs": None,
            "effect_stage_refs": None,
            "blocked_by_gate": None,
        }

    @staticmethod
    def _blocked_gate(
        gate_id: str,
        release_digest: str,
        context: Mapping[str, Any],
        approval_ref: str | None,
        blocked_by_gate: str,
    ) -> dict[str, object]:
        return {
            "gate_id": gate_id,
            "result": "blocked",
            "execution_key": _execution_key(release_digest, context["run_id"], gate_id),
            "target_ref": context["target_ref"],
            "approval_ref": approval_ref,
            "environment_class": context["environment_class"],
            "observed_at_utc": context["executed_at_utc"],
            "executor_digest": None,
            "step_digest": None,
            "fixture_digest": None,
            "evidence_refs": [],
            "blocking_evidence_refs": [],
            "rollback_ref": None,
            "rollback_status": "not-executed",
            "impact_ref": "impact:blocked-by-prerequisite",
            "next_step_ref": "next:resolve-frontier-in-new-run",
            "acceptance_receipt_refs": None,
            "effect_stage_refs": None,
            "blocked_by_gate": blocked_by_gate,
        }

    def _report(
        self,
        manifest_wire: Mapping[str, object],
        context: Mapping[str, Any],
        gates: list[dict[str, object]],
    ) -> dict[str, object]:
        environment_class = context["environment_class"]
        if _fixture_environment(environment_class):
            scope = "contract-fixture"
        elif "target-local" in environment_class.lower():
            scope = "target-local-attestation"
        else:
            scope = "target-attestation-required"
        results = [gate["result"] for gate in gates]
        if "failed" in results:
            run_verdict = "failed"
        elif "cannot-confirm" in results:
            run_verdict = "cannot-confirm"
        elif "not-authorized" in results:
            run_verdict = "not-authorized"
        elif "blocked" in results:
            run_verdict = "blocked"
        else:
            run_verdict = "passed"
        all_passed = all(result == "passed" for result in results)
        target_local_complete = scope == "target-local-attestation" and all_passed
        base: dict[str, object] = {
            "contract": "ticket119-acceptance-run-report-v1",
            "release_digest": manifest_wire["release_digest"],
            "run_id": context["run_id"],
            "executed_at_utc": context["executed_at_utc"],
            "environment_class": environment_class,
            "target_ref": context["target_ref"],
            "approval_refs": {
                gate_id: context["approval_refs"].get(gate_id)
                for gate_id in sorted(_APPROVAL_GATES)
            },
            "evidence_scope": scope,
            "gates": copy.deepcopy(gates),
            "technical_gate_verdict": (
                "passed" if target_local_complete else "evidence-required"
            ),
            "target_binding_verdict": (
                "passed" if target_local_complete else "evidence-required"
            ),
            "real_interface_verdict": (
                "passed" if target_local_complete else "evidence-required"
            ),
            "deployment": "passed" if target_local_complete else "evidence-required",
            "diagnostic_scope_phase": (
                "activation-ready"
                if scope == "target-local-attestation"
                and gates[_GATES.index("119-G07")]["result"] == "passed"
                else "staged"
            ),
            "active": "confirmed" if target_local_complete else "evidence-required",
            "product_acceptance": (
                "passed" if target_local_complete else "evidence-required"
            ),
            "stable_operation": "evidence-required",
            "run_verdict": run_verdict,
        }
        base["report_digest"] = _digest(base)
        return base

    def _valid_replay(
        self,
        candidate: Mapping[str, object],
        manifest_wire: Mapping[str, object],
        context: Mapping[str, Any],
    ) -> bool:
        if type(candidate) is not dict or frozenset(candidate) != _REPORT_FIELDS:
            return False
        candidate_digest = _digest_ref(candidate.get("report_digest"))
        if candidate_digest is None:
            return False
        identity = copy.deepcopy(candidate)
        identity.pop("report_digest", None)
        try:
            if _digest(identity) != candidate_digest:
                return False
        except (TypeError, ValueError):
            return False
        if (
            candidate.get("contract") != "ticket119-acceptance-run-report-v1"
            or candidate.get("release_digest") != manifest_wire["release_digest"]
            or candidate.get("run_id") != context["run_id"]
            or candidate.get("executed_at_utc") != context["executed_at_utc"]
            or candidate.get("environment_class") != context["environment_class"]
            or candidate.get("target_ref") != context["target_ref"]
        ):
            return False
        approvals = candidate.get("approval_refs")
        expected_approvals = {
            gate_id: context["approval_refs"].get(gate_id)
            for gate_id in sorted(_APPROVAL_GATES)
        }
        if approvals != expected_approvals:
            return False
        if candidate.get("evidence_scope") not in {
            "contract-fixture",
            "target-local-attestation",
            "target-attestation-required",
        }:
            return False
        if candidate.get("stable_operation") != "evidence-required":
            return False
        if candidate.get("diagnostic_scope_phase") not in {"staged", "activation-ready"}:
            return False
        if _fixture_environment(context["environment_class"]) and (
            candidate.get("evidence_scope") != "contract-fixture"
            or candidate.get("diagnostic_scope_phase") != "staged"
            or any(
                candidate.get(key) == "passed"
                for key in (
                    "technical_gate_verdict",
                    "target_binding_verdict",
                    "real_interface_verdict",
                    "deployment",
                    "product_acceptance",
                    "active",
                )
            )
        ):
            return False
        gates = candidate.get("gates")
        if type(gates) is not list or len(gates) != len(_GATES):
            return False
        frontier: str | None = None
        for gate_id, gate in zip(_GATES, gates, strict=True):
            if not self._valid_gate(gate, gate_id, manifest_wire["release_digest"], context):
                return False
            if frontier is not None:
                if gate.get("result") != "blocked" or gate.get("blocked_by_gate") != frontier:
                    return False
            elif gate.get("result") != "passed":
                frontier = gate_id
        return candidate == self._report(manifest_wire, context, gates)

    def _valid_gate(
        self,
        value: object,
        gate_id: str,
        release_digest: object,
        context: Mapping[str, Any],
    ) -> bool:
        if type(value) is not dict or frozenset(value) not in {
            _EXECUTED_GATE_FIELDS,
            _BLOCKED_GATE_FIELDS,
        }:
            return False
        if (
            value.get("gate_id") != gate_id
            or value.get("release_digest") not in {None, release_digest}
            or value.get("execution_key")
            != _execution_key(release_digest, context["run_id"], gate_id)
            or value.get("target_ref") != context["target_ref"]
            or value.get("approval_ref") != context["approval_refs"].get(gate_id)
            or value.get("environment_class") != context["environment_class"]
            or value.get("observed_at_utc") != context["executed_at_utc"]
        ):
            return False
        result = value.get("result")
        if result == "blocked":
            return (
                type(value.get("blocked_by_gate")) is str
                and value.get("executor_digest") is None
                and value.get("step_digest") is None
                and value.get("fixture_digest") is None
                and value.get("evidence_refs") == []
                and value.get("blocking_evidence_refs") == []
                and value.get("rollback_ref") is None
                and value.get("rollback_status") == "not-executed"
                and value.get("impact_ref") == "impact:blocked-by-prerequisite"
                and value.get("next_step_ref") == "next:resolve-frontier-in-new-run"
                and value.get("acceptance_receipt_refs") is None
                and value.get("effect_stage_refs") is None
            )
        if result not in _RESULTS or value.get("blocked_by_gate") is not None:
            return False
        if result == "cannot-confirm" and value.get("executor_digest") is None:
            return (
                value.get("step_digest") is None
                and value.get("fixture_digest") is None
                and value.get("evidence_refs") == []
                and value.get("blocking_evidence_refs") == []
                and value.get("rollback_ref") is None
                and value.get("rollback_status") == "cannot-confirm"
                and value.get("impact_ref") == "impact:gate-evidence-unavailable"
                and value.get("next_step_ref") == "next:stop-and-create-new-run"
                and value.get("acceptance_receipt_refs") is None
                and value.get("effect_stage_refs") is None
            )
        if result == "not-authorized" and value.get("executor_digest") is None:
            return (
                value.get("step_digest") is None
                and value.get("fixture_digest") is None
                and value.get("evidence_refs") == []
                and value.get("blocking_evidence_refs") == []
                and value.get("rollback_ref") is None
                and value.get("rollback_status") == "not-authorized"
                and value.get("impact_ref") == "impact:authorization-required"
                and value.get("next_step_ref") == "next:obtain-current-approval"
                and value.get("acceptance_receipt_refs") is None
                and value.get("effect_stage_refs") is None
            )
        return (
            _digest_ref(value.get("executor_digest")) is not None
            and _digest_ref(value.get("step_digest")) is not None
            and _digest_ref(value.get("fixture_digest")) is not None
            and _ref_list(value.get("evidence_refs")) is not None
            and _ref_list(value.get("blocking_evidence_refs")) is not None
            and _opaque_ref(value.get("rollback_ref")) is not None
            and _opaque_ref(value.get("rollback_status")) is not None
            and _opaque_ref(value.get("impact_ref")) is not None
            and _opaque_ref(value.get("next_step_ref")) is not None
            and (
                value.get("effect_stage_refs") is None
                if gate_id not in {"119-G11", "119-G12"}
                else self._effect_stage_refs(value.get("effect_stage_refs"), gate_id)
                is not None
            )
            and (
                value.get("acceptance_receipt_refs") is None
                if gate_id != "119-G12"
                else self._receipt_refs(value.get("acceptance_receipt_refs"), gate_id)
                is not None
            )
        )

    def _rejected_replay(
        self,
        manifest_wire: Mapping[str, object],
        context: Mapping[str, Any],
    ) -> dict[str, object]:
        gates = [
            self._cannot_confirm_gate(
                _GATES[0],
                manifest_wire["release_digest"],
                context,
                context["approval_refs"].get(_GATES[0]),
            )
        ]
        gates.extend(
            self._blocked_gate(
                gate_id,
                manifest_wire["release_digest"],
                context,
                context["approval_refs"].get(gate_id),
                _GATES[0],
            )
            for gate_id in _GATES[1:]
        )
        return self._report(manifest_wire, context, gates)

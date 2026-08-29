"""Verifier-owned Ticket 119 acceptance-run gates.

The suite crosses one public seam only: AcceptanceRunContract.run.  It uses a
real Ticket 118 ReleaseManifest and a verifier-owned GateExecutor Adapter; it
never contacts a target, network, model, channel, owner, or contact.
"""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Mapping

import partner_health_steward as health_package


_GATES = tuple(f"119-G{index:02d}" for index in range(1, 13))
_APPROVAL_GATES = ("119-G08", "119-G10", "119-G11", "119-G12")
_SHA_A = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64
_PINNED_COMMIT = "3c27eb6234bf91b8ceee9e9071591b31e9b148cb"
_PINNED_FILES = {
    "hermes_cli/plugins.py": (
        "2f74ddb96ed024cd2e085c2181751c610811e47f79f66a1ba7ce205c766664d8"
    ),
    "gateway/platform_registry.py": (
        "f7ebc66c09d40e883617f1a1a6700f621b4b14f94849b131bfacf0a80a623c4b"
    ),
    "gateway/run.py": (
        "328950c2369af1ca62b9cb8c97aaf1c931e8020b2535078bc84a9de258c4dfb5"
    ),
    "gateway/platforms/weixin.py": (
        "9c0650b68acf5847ded1eb16c42f5d10dd37d0bddb17b65dcb7ff9c9d37857e5"
    ),
}
_TARGET_REQUIREMENTS = (
    "target-hermes-artifact",
    "target-required-patch",
    "target-plugin-binding",
    "target-service-identity",
    "target-unix-acl",
    "target-current-head",
    "target-native-entry-disabled",
)
_EXTERNAL_REQUIREMENTS = (
    "model-route-owner-consent",
    "knowledge-rights",
    "medical-review",
    "owner-acceptance",
)
_SECRET_CLASSES = (
    "credential",
    "token",
    "private-key",
    "contact-identity",
    "health-content",
    "partner-config-value",
)
_ARTIFACTS = (
    ("host/required.patch", "hermes-required-patch"),
    ("host/disabled-native-entry.assertion", "disabled-native-entry"),
    ("product/hermes_host.py", "hermes-host-health-weixin-adapter"),
    ("product/plugin.py", "health-plugin"),
    ("product/core.py", "health-core"),
    ("adapters/model.py", "model-adapter-interface"),
    ("adapters/delivery.py", "delivery-adapter-interface"),
    ("interfaces/core-command.json", "core-command-interface"),
    ("interfaces/core-managed-read.json", "core-managed-read-interface"),
    ("interfaces/core-controlled-effect.json", "core-controlled-effect-interface"),
    ("schemas/health-state.json", "health-state-schema"),
    ("model/capability-profile-schema.json", "capability-profile-schema"),
    ("model/capability-profile-builder.py", "capability-profile-builder"),
    ("model/capability-profile-validator.py", "capability-profile-validator"),
    ("bundles/minimum-help.json", "minimum-help-bundle"),
    ("bundles/knowledge.json", "knowledge-bundle"),
    ("bundles/safety.json", "safety-bundle"),
    ("bundles/diagnostic.json", "diagnostic-bundle"),
    ("migration/protocol.json", "migration-protocol"),
    ("migration/schema.json", "migration-schema"),
    ("migration/builder.py", "migration-builder"),
    ("migration/semantic-registry.json", "migration-semantic-registry"),
    ("migration/ticket117-synthetic-fixture.py", "migration-synthetic-fixture"),
    ("environment/python.txt", "python-constraint"),
    ("environment/dependencies.lock", "dependency-constraint"),
    ("environment/service-acl.json", "service-identity-acl-requirement"),
    ("skills/health-init/SKILL.md", "skill:health-init"),
    ("skills/health-steward/SKILL.md", "skill:health-steward"),
    ("skills/health-settings/SKILL.md", "skill:health-settings"),
    ("skills/health-portrait/SKILL.md", "skill:health-portrait"),
    ("skills/health-evidence/SKILL.md", "skill:health-evidence"),
    ("skills/health-owner-inquiry/SKILL.md", "skill:health-owner-inquiry"),
    ("skills/health-literature/SKILL.md", "skill:health-literature"),
)


def _wire(value: object, name: str) -> dict[str, object]:
    to_wire = getattr(value, "to_wire", None)
    if not callable(to_wire):
        raise AssertionError(f"{name} does not expose to_wire()")
    wire = to_wire()
    if type(wire) is not dict:
        raise AssertionError(f"{name} wire must be a plain mapping")
    return wire


def _gate_map(report_wire: Mapping[str, object]) -> dict[str, dict[str, object]]:
    gates = report_wire.get("gates")
    if type(gates) not in (list, tuple):
        raise AssertionError("acceptance report must expose ordered gates")
    result: dict[str, dict[str, object]] = {}
    for item in gates:
        if type(item) is not dict or type(item.get("gate_id")) is not str:
            raise AssertionError("acceptance report gate entry is invalid")
        result[item["gate_id"]] = item
    return result


def _g12_receipts(run_id: str) -> dict[str, str]:
    suffix = run_id.replace(":", "-")
    return {
        "run_receipt_ref": f"receipt:run:{suffix}",
        "owner_acceptance_receipt_ref": f"receipt:owner-acceptance:{suffix}",
        "contact_acceptance_receipt_ref": f"receipt:contact-acceptance:{suffix}",
        "contact_correction_receipt_ref": f"receipt:contact-correction:{suffix}",
        "active_path_receipt_ref": f"receipt:active-path:{suffix}",
    }


def _effect_stage_refs(
    run_id: str,
    gate_id: str,
    *,
    unknown_after_acceptance: bool = False,
) -> dict[str, str | None]:
    prefix = f"effect:{gate_id.lower()}:{run_id.replace(':', '-')}"
    return {
        "formed": prefix + ":formed",
        "committed": prefix + ":committed",
        "attempted": prefix + ":attempted",
        "interface_accepted": prefix + ":interface-accepted",
        "delivered": None if unknown_after_acceptance else prefix + ":delivered",
        "read_or_action": (
            None if unknown_after_acceptance else prefix + ":read-or-action"
        ),
        "correction": None,
        "unknown": prefix + ":unknown" if unknown_after_acceptance else None,
    }


def _canonical_report_digest(report_wire: Mapping[str, object]) -> str:
    identity = copy.deepcopy(dict(report_wire))
    identity.pop("report_digest", None)
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class _FakeGateExecutor:
    """A boundary fake; it never performs a real external action."""

    def __init__(
        self,
        *,
        results: Mapping[str, str] | None = None,
        mutations: Mapping[str, Mapping[str, object]] | None = None,
        preflight_not_authorized: tuple[str, ...] = (),
        fail_on_call: bool = False,
    ) -> None:
        self.results = dict(results or {})
        self.mutations = {
            gate: copy.deepcopy(dict(value))
            for gate, value in (mutations or {}).items()
        }
        self.fail_on_call = fail_on_call
        self.preflight_not_authorized = frozenset(preflight_not_authorized)
        self.calls: list[dict[str, object]] = []
        self.external_action_calls: list[str] = []

    def execute(self, request: Mapping[str, object]) -> dict[str, object]:
        if self.fail_on_call:
            raise AssertionError("replayed acceptance run called its executor")
        if type(request) is not dict:
            raise AssertionError("gate request must be a plain mapping")
        call = copy.deepcopy(request)
        self.calls.append(call)
        execution_key = call.get("execution_key")
        if type(execution_key) is not str:
            raise AssertionError("gate request lacks a stable execution key")
        gate_id = call.get("gate_id")
        if gate_id not in _GATES:
            raise AssertionError("gate request used an unknown gate")
        if "target_ref" not in call or "approval_ref" not in call:
            raise AssertionError("gate request omits target or approval context")
        run_id = call.get("run_id")
        if type(run_id) is not str:
            raise AssertionError("gate request lacks run identity")
        result = (
            "not-authorized"
            if gate_id in self.preflight_not_authorized
            else self.results.get(gate_id, "passed")
        )
        if result != "not-authorized":
            self.external_action_calls.append(execution_key)
        observation: dict[str, object] = {
            "contract": "ticket119-gate-observation-v1",
            "release_digest": call.get("release_digest"),
            "run_id": run_id,
            "gate_id": gate_id,
            "execution_key": execution_key,
            "environment_class": call.get("environment_class"),
            "observed_at_utc": call.get("executed_at_utc"),
            "executor_digest": _SHA_A,
            "step_digest": _SHA_A,
            "fixture_digest": _SHA_B,
            "result": result,
            "evidence_refs": [f"evidence:{gate_id.lower()}:{run_id}"],
            "blocking_evidence_refs": [],
            "rollback_ref": f"rollback:{gate_id.lower()}:{run_id}",
            "rollback_status": "available",
            "impact_ref": "impact:none",
            "next_step_ref": "next:ordered-gate",
            "acceptance_receipt_refs": (
                _g12_receipts(run_id) if gate_id == "119-G12" else None
            ),
            "effect_stage_refs": (
                _effect_stage_refs(run_id, gate_id)
                if gate_id in {"119-G11", "119-G12"}
                else None
            ),
        }
        observation.update(copy.deepcopy(self.mutations.get(gate_id, {})))
        return observation


class Ticket119VerificationTests(unittest.TestCase):
    """Seven gates, each killing one independent Ticket 119 reality error."""

    maxDiff = None

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="ticket119-release-")
        self.release_root = Path(self._temporary.name)
        self.artifacts = self._create_release_fixture(self.release_root)
        host_contract = getattr(health_package, "HostReleaseContract", None)
        if not callable(host_contract):
            raise AssertionError("Ticket 118 HostReleaseContract is unavailable")
        self.manifest = host_contract().build(self._release_sources())
        self.manifest_wire = _wire(self.manifest, "release manifest")
        self.contract: object | None = None

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _require_contract(self, *, root: bool) -> None:
        contract_type = getattr(health_package, "AcceptanceRunContract", None)
        if callable(contract_type):
            self.contract = contract_type()
            return
        message = (
            "V119-01 prerequisite: AcceptanceRunContract public Module "
            "is not implemented"
        )
        if root:
            raise AssertionError(message)
        self.skipTest(message)

    @staticmethod
    def _create_release_fixture(root: Path) -> tuple[dict[str, str], ...]:
        for relative, role in _ARTIFACTS:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"ticket119 verifier artifact: {role}\n", encoding="utf-8")
        return tuple({"path": path, "role": role} for path, role in _ARTIFACTS)

    def _release_sources(self) -> dict[str, object]:
        return {
            "contract": "ticket118-release-sources-v1",
            "repository_root": str(self.release_root),
            "artifacts": copy.deepcopy(list(self.artifacts)),
            "pinned_hermes": {
                "commit": _PINNED_COMMIT,
                "allowlisted_files": [
                    {"path": path, "sha256": digest}
                    for path, digest in _PINNED_FILES.items()
                ],
                "extractor_version": "ticket118-pinned-source-v1",
            },
            "environment_constraints": {
                "python": ">=3.11,<3.12",
                "core_port": (
                    "command-v1",
                    "managed-read-v1",
                    "controlled-effect-v1",
                ),
            },
            "target_binding_required": list(_TARGET_REQUIREMENTS),
            "external_approval_required": list(_EXTERNAL_REQUIREMENTS),
            "forbidden_secret_classes": list(_SECRET_CLASSES),
        }

    @staticmethod
    def _context(
        *,
        run_id: str = "acceptance-run:synthetic-001",
        approvals: tuple[str, ...] = _APPROVAL_GATES,
        approval_refs: Mapping[str, str] | None = None,
        existing_report: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        refs = (
            {
                gate: f"approval:{gate.lower()}:{run_id}"
                for gate in approvals
            }
            if approval_refs is None
            else copy.deepcopy(dict(approval_refs))
        )
        return {
            "contract": "ticket119-run-context-v1",
            "run_id": run_id,
            "executed_at_utc": "2026-08-30T12:00:00+00:00",
            "environment_class": "verifier-synthetic-deny-network",
            "target_ref": "target:disposable-ticket119",
            "approval_refs": refs,
            "existing_report": (
                None if existing_report is None else copy.deepcopy(dict(existing_report))
            ),
        }

    def _run(
        self,
        executor: _FakeGateExecutor,
        context: Mapping[str, object],
    ) -> tuple[object, dict[str, object]]:
        assert self.contract is not None
        run = getattr(self.contract, "run", None)
        if not callable(run):
            raise AssertionError("AcceptanceRunContract.run is unavailable")
        report = run(self.manifest, executor, copy.deepcopy(dict(context)))
        return report, _wire(report, "acceptance run report")

    def test_v119_01_order_is_fixed_and_first_nonpass_blocks_all_successors(self) -> None:
        self._require_contract(root=True)
        assert self.contract is not None
        cases = (
            ("failed", "119-G03", _APPROVAL_GATES),
            ("cannot-confirm", "119-G03", _APPROVAL_GATES),
            ("not-authorized", "119-G08", ()),
        )
        for frontier_result, frontier_gate, approvals in cases:
            with self.subTest(frontier_result=frontier_result):
                results = (
                    {frontier_gate: frontier_result}
                    if frontier_result != "not-authorized"
                    else {}
                )
                executor = _FakeGateExecutor(results=results)
                _report, wire = self._run(
                    executor,
                    self._context(
                        run_id=f"acceptance-run:order-{frontier_result}",
                        approvals=approvals,
                    ),
                )
                frontier_index = _GATES.index(frontier_gate)
                expected_calls = list(_GATES[: frontier_index + 1])
                if frontier_result == "not-authorized":
                    expected_calls.pop()
                self.assertEqual(
                    [call["gate_id"] for call in executor.calls], expected_calls
                )
                gates = _gate_map(wire)
                self.assertEqual(tuple(gates), _GATES)
                self.assertEqual(gates[frontier_gate]["result"], frontier_result)
                for gate_id in _GATES[frontier_index + 1 :]:
                    self.assertEqual(gates[gate_id]["result"], "blocked")
                    self.assertEqual(
                        gates[gate_id]["blocked_by_gate"], frontier_gate
                    )
                self.assertNotEqual(wire.get("product_acceptance"), "passed")

    def test_v119_02_observations_are_run_release_bound_and_report_is_immutable(self) -> None:
        self._require_contract(root=False)
        assert self.contract is not None
        run_id = "acceptance-run:tamper-001"
        report, valid_wire = self._run(_FakeGateExecutor(), self._context(run_id=run_id))
        self.assertEqual(
            valid_wire.get("report_digest"), _canonical_report_digest(valid_wire)
        )

        returned = _wire(report, "acceptance run report")
        returned_gates = _gate_map(returned)
        returned_gates["119-G01"]["evidence_refs"].append("evidence:nested-tamper")
        fresh = _wire(report, "acceptance run report")
        self.assertNotIn("evidence:nested-tamper", repr(fresh))
        self.assertEqual(fresh.get("report_digest"), _canonical_report_digest(fresh))

        nested_tamper = copy.deepcopy(valid_wire)
        _gate_map(nested_tamper)["119-G02"]["evidence_refs"].append(
            "evidence:forged-nested-ref"
        )
        fake_digest = copy.deepcopy(valid_wire)
        fake_digest["report_digest"] = "sha256:" + "0" * 64
        cross_run = copy.deepcopy(valid_wire)
        cross_run["run_id"] = "acceptance-run:other"
        cross_run["report_digest"] = _canonical_report_digest(cross_run)
        cross_release = copy.deepcopy(valid_wire)
        cross_release["release_digest"] = "sha256:" + "f" * 64
        cross_release["report_digest"] = _canonical_report_digest(cross_release)

        contract_type = type(self.contract)
        for name, existing in (
            ("nested-tamper", nested_tamper),
            ("fixed-fake-digest", fake_digest),
            ("cross-run", cross_run),
            ("cross-release", cross_release),
        ):
            with self.subTest(name=name):
                self.contract = contract_type()
                executor = _FakeGateExecutor(fail_on_call=True)
                _rejected, rejected_wire = self._run(
                    executor,
                    self._context(run_id=run_id, existing_report=existing),
                )
                self.assertEqual(executor.calls, [])
                self.assertEqual(rejected_wire.get("run_verdict"), "cannot-confirm")
                self.assertNotEqual(
                    rejected_wire.get("product_acceptance"), "passed"
                )

    def test_v119_03_same_run_replay_never_repeats_an_external_gate(self) -> None:
        self._require_contract(root=False)
        assert self.contract is not None
        run_id = "acceptance-run:replay-001"
        first_executor = _FakeGateExecutor()
        first_report, first_wire = self._run(
            first_executor, self._context(run_id=run_id)
        )
        replay_executor = _FakeGateExecutor(fail_on_call=True)
        _replayed, replay_wire = self._run(
            replay_executor,
            self._context(run_id=run_id, existing_report=first_wire),
        )
        self.assertEqual(replay_wire, first_wire)
        self.assertEqual(replay_executor.calls, [])

        unknown_run = "acceptance-run:unknown-001"
        unknown_stages = _effect_stage_refs(
            unknown_run, "119-G11", unknown_after_acceptance=True
        )
        unknown_executor = _FakeGateExecutor(
            results={"119-G11": "cannot-confirm"},
            mutations={"119-G11": {"effect_stage_refs": unknown_stages}},
        )
        _unknown, unknown_wire = self._run(
            unknown_executor, self._context(run_id=unknown_run)
        )
        unknown_gates = _gate_map(unknown_wire)
        self.assertEqual(unknown_gates["119-G11"]["result"], "cannot-confirm")
        self.assertEqual(
            unknown_gates["119-G11"]["effect_stage_refs"], unknown_stages
        )
        self.assertIsNotNone(unknown_stages["interface_accepted"])
        self.assertIsNone(unknown_stages["delivered"])
        self.assertIsNone(unknown_stages["read_or_action"])
        self.assertIsNotNone(unknown_stages["unknown"])
        self.assertEqual(unknown_gates["119-G12"]["result"], "blocked")
        self.assertEqual(
            [call["gate_id"] for call in unknown_executor.calls].count("119-G11"),
            1,
        )
        self.assertEqual(
            len(set(unknown_executor.external_action_calls)),
            len(unknown_executor.external_action_calls),
        )
        unknown_replay_executor = _FakeGateExecutor(fail_on_call=True)
        _unknown_replay, unknown_replay_wire = self._run(
            unknown_replay_executor,
            self._context(run_id=unknown_run, existing_report=unknown_wire),
        )
        self.assertEqual(unknown_replay_wire, unknown_wire)
        self.assertEqual(unknown_replay_executor.calls, [])

        folded_ref = "effect:folded-interface-and-delivery"
        folded = _effect_stage_refs("acceptance-run:folded", "119-G11")
        folded["interface_accepted"] = folded_ref
        folded["delivered"] = folded_ref
        folded_executor = _FakeGateExecutor(
            mutations={"119-G11": {"effect_stage_refs": folded}}
        )
        _folded, folded_wire = self._run(
            folded_executor,
            self._context(run_id="acceptance-run:folded"),
        )
        self.assertEqual(
            _gate_map(folded_wire)["119-G11"]["result"], "cannot-confirm"
        )

    def test_v119_04_g07_never_activates_and_g12_needs_all_opaque_receipts(self) -> None:
        self._require_contract(root=False)
        assert self.contract is not None
        local_executor = _FakeGateExecutor()
        _local, local_wire = self._run(
            local_executor,
            self._context(
                run_id="acceptance-run:g07-only",
                approvals=(),
            ),
        )
        local_gates = _gate_map(local_wire)
        self.assertEqual(local_gates["119-G07"]["result"], "passed")
        self.assertEqual(local_wire.get("evidence_scope"), "contract-fixture")
        self.assertEqual(local_wire.get("diagnostic_scope_phase"), "staged")
        self.assertNotEqual(local_wire.get("product_acceptance"), "passed")

        incomplete_executor = _FakeGateExecutor(
            mutations={
                "119-G12": {
                    "acceptance_receipt_refs": {
                        key: value
                        for key, value in _g12_receipts("acceptance-run:g12-incomplete").items()
                        if key != "active_path_receipt_ref"
                    }
                }
            }
        )
        _incomplete, incomplete_wire = self._run(
            incomplete_executor,
            self._context(run_id="acceptance-run:g12-incomplete"),
        )
        self.assertEqual(
            _gate_map(incomplete_wire)["119-G12"]["result"], "cannot-confirm"
        )
        self.assertNotEqual(incomplete_wire.get("product_acceptance"), "passed")

        complete_run_id = "acceptance-run:g12-complete"
        complete_executor = _FakeGateExecutor()
        _complete, complete_wire = self._run(
            complete_executor,
            self._context(run_id=complete_run_id),
        )
        self.assertEqual(
            _gate_map(complete_wire)["119-G12"]["acceptance_receipt_refs"],
            _g12_receipts(complete_run_id),
        )
        self.assertEqual(complete_wire.get("evidence_scope"), "contract-fixture")
        self.assertEqual(complete_wire.get("diagnostic_scope_phase"), "staged")
        self.assertNotEqual(complete_wire.get("product_acceptance"), "passed")
        self.assertNotEqual(complete_wire.get("active"), "passed")
        self.assertEqual(complete_wire.get("stable_operation"), "evidence-required")

    def test_v119_05_g08_no_go_cannot_be_demoted_to_a_partial_pass(self) -> None:
        self._require_contract(root=False)
        assert self.contract is not None
        executor = _FakeGateExecutor(
            mutations={
                "119-G08": {
                    "result": "passed",
                    "blocking_evidence_refs": [
                        "no-go:current-head-or-rollback-not-closed"
                    ],
                }
            }
        )
        _report, wire = self._run(
            executor, self._context(run_id="acceptance-run:g08-no-go")
        )
        gates = _gate_map(wire)
        self.assertNotEqual(gates["119-G08"]["result"], "passed")
        self.assertEqual(gates["119-G09"]["result"], "blocked")
        self.assertNotIn("119-G09", [call["gate_id"] for call in executor.calls])

    def test_v119_06_external_gates_require_own_approval_and_g12_is_content_free(self) -> None:
        self._require_contract(root=False)
        assert self.contract is not None
        for missing_gate in _APPROVAL_GATES:
            with self.subTest(missing_gate=missing_gate):
                approvals = tuple(
                    gate for gate in _APPROVAL_GATES if gate != missing_gate
                )
                executor = _FakeGateExecutor()
                _report, wire = self._run(
                    executor,
                    self._context(
                        run_id=f"acceptance-run:missing-{missing_gate.lower()}",
                        approvals=approvals,
                    ),
                )
                gates = _gate_map(wire)
                self.assertEqual(gates[missing_gate]["result"], "not-authorized")
                self.assertNotIn(
                    missing_gate, [call["gate_id"] for call in executor.calls]
                )

        invalid_refs = (
            ("cross-gate", "approval:119-g11:borrowed"),
            ("withdrawn", "approval:119-g10:withdrawn"),
            ("wrong-binding", "approval:119-g10:other-run-or-target"),
        )
        for name, invalid_ref in invalid_refs:
            with self.subTest(preflight=name):
                run_id = f"acceptance-run:approval-{name}"
                refs = {
                    gate: f"approval:{gate.lower()}:{run_id}"
                    for gate in _APPROVAL_GATES
                }
                refs["119-G10"] = invalid_ref
                executor = _FakeGateExecutor(
                    preflight_not_authorized=("119-G10",)
                )
                _report, wire = self._run(
                    executor,
                    self._context(run_id=run_id, approval_refs=refs),
                )
                g10 = _gate_map(wire)["119-G10"]
                self.assertEqual(g10["result"], "not-authorized")
                self.assertEqual(g10["approval_ref"], invalid_ref)
                g10_request = next(
                    call for call in executor.calls if call["gate_id"] == "119-G10"
                )
                self.assertEqual(g10_request["target_ref"], "target:disposable-ticket119")
                self.assertEqual(g10_request["approval_ref"], invalid_ref)
                self.assertNotIn(
                    g10_request["execution_key"], executor.external_action_calls
                )

        for name, mutation, leaked_value in (
            (
                "identity",
                {"owner_id": "owner-identity-must-not-leave-target"},
                "owner-identity-must-not-leave-target",
            ),
            (
                "nested-body",
                {"payload": {"health_body": "private-body-must-not-leave-target"}},
                "private-body-must-not-leave-target",
            ),
        ):
            with self.subTest(leak=name):
                leaking_executor = _FakeGateExecutor(
                    mutations={"119-G12": mutation}
                )
                _leaking, leaking_wire = self._run(
                    leaking_executor,
                    self._context(run_id=f"acceptance-run:g12-leak-{name}"),
                )
                self.assertEqual(
                    _gate_map(leaking_wire)["119-G12"]["result"],
                    "cannot-confirm",
                )
                self.assertNotIn(leaked_value, repr(leaking_wire))

    def test_v119_07_local_pass_is_not_deployment_acceptance_or_stability(self) -> None:
        self._require_contract(root=False)
        assert self.contract is not None
        local_executor = _FakeGateExecutor()
        _local, local_wire = self._run(
            local_executor,
            self._context(
                run_id="acceptance-run:local-nine",
                approvals=("119-G08",),
            ),
        )
        local_gates = _gate_map(local_wire)
        self.assertTrue(all(local_gates[gate]["result"] == "passed" for gate in _GATES[:9]))
        self.assertEqual(local_wire.get("evidence_scope"), "contract-fixture")
        self.assertNotEqual(local_wire.get("technical_gate_verdict"), "passed")
        self.assertNotEqual(local_wire.get("target_binding_verdict"), "passed")
        self.assertNotEqual(local_wire.get("real_interface_verdict"), "passed")
        self.assertNotEqual(local_wire.get("product_acceptance"), "passed")
        self.assertEqual(local_wire.get("diagnostic_scope_phase"), "staged")
        self.assertNotEqual(local_wire.get("active"), "passed")
        self.assertEqual(local_wire.get("stable_operation"), "evidence-required")
        self.assertNotEqual(local_wire.get("deployment"), "passed")

        full_executor = _FakeGateExecutor()
        _full, full_wire = self._run(
            full_executor,
            self._context(run_id="acceptance-run:full-twelve"),
        )
        self.assertTrue(
            all(
                gate["result"] == "passed"
                for gate in _gate_map(full_wire).values()
            )
        )
        self.assertEqual(full_wire.get("evidence_scope"), "contract-fixture")
        self.assertNotEqual(full_wire.get("technical_gate_verdict"), "passed")
        self.assertNotEqual(full_wire.get("target_binding_verdict"), "passed")
        self.assertNotEqual(full_wire.get("real_interface_verdict"), "passed")
        self.assertNotEqual(full_wire.get("deployment"), "passed")
        self.assertEqual(full_wire.get("diagnostic_scope_phase"), "staged")
        self.assertNotEqual(full_wire.get("active"), "passed")
        self.assertNotEqual(full_wire.get("product_acceptance"), "passed")
        self.assertEqual(full_wire.get("stable_operation"), "evidence-required")


if __name__ == "__main__":
    unittest.main()

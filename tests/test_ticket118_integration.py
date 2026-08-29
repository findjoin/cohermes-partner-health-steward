"""Verifier-owned RED gates for Ticket 118's public release/host seam.

The suite observes only HostReleaseContract.build/verify/assess and synthetic
system-boundary adapter records.  It never reads a Partner profile, secrets,
health data, product private helpers, or release implementation state.
"""

from __future__ import annotations

import copy
import hashlib
import os
import subprocess
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import partner_health_steward as health_package


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
_SKILLS = (
    "health-init",
    "health-steward",
    "health-settings",
    "health-portrait",
    "health-evidence",
    "health-owner-inquiry",
    "health-literature",
)
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


class _SyntheticEffectAdapter:
    """External-effect boundary used only to prove a forged effect is not run."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    def execute(self, intent: object) -> Mapping[str, object]:
        self.calls.append(copy.deepcopy(intent))
        return {
            "status": "completed",
            "terminal": True,
            "result_ref": "synthetic-result:ticket118",
        }


class _SyntheticCredentialAdapter:
    """Local credential observation; Linux kernel enforcement belongs to 119."""

    def __init__(self, *, peer: str = "plugin") -> None:
        self.peer = peer

    def observe(self) -> Mapping[str, object]:
        return {
            "peer": self.peer,
            "service": "health-core",
            "acl": "allowed",
            "enforcement": "synthetic-contract-only",
        }


class _SyntheticCorePortAdapter:
    """Three-interface Adapter; a callback failure must close the host entry."""

    def __init__(self, *, callback_fails: bool = False) -> None:
        self.callback_fails = callback_fails
        self.calls: list[str] = []

    def command(self, value: object) -> Mapping[str, object]:
        del value
        self.calls.append("command")
        if self.callback_fails:
            raise RuntimeError("synthetic core callback unavailable")
        return {"status": "accepted", "terminal": True}

    def managed_read(self, value: object) -> Mapping[str, object]:
        del value
        self.calls.append("managed-read")
        return {"status": "available", "projection": {}}

    def execute_effect(self, value: object) -> Mapping[str, object]:
        del value
        self.calls.append("controlled-effect")
        return {"status": "accepted", "terminal": True}


def _wire(value: object, name: str) -> dict[str, object]:
    if type(value) is dict:
        return copy.deepcopy(value)
    to_wire = getattr(value, "to_wire", None)
    if not callable(to_wire):
        raise AssertionError(f"{name} does not expose to_wire()")
    wire = to_wire()
    if type(wire) is not dict:
        raise AssertionError(f"{name}.to_wire() did not return a dict")
    return copy.deepcopy(wire)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Ticket118VerificationTests(unittest.TestCase):
    """Seven public-seam gates, one for each Ticket 118 acceptance ID."""

    maxDiff = None

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="ticket118-release-")
        self.release_root = Path(self._temporary.name)
        self.artifacts = self._create_release_fixture(self.release_root)
        pinned_source = os.environ.get("TICKET118_PINNED_HERMES_SOURCE")
        self.pinned_root = None if pinned_source is None else Path(pinned_source)
        self.contract: object | None = None

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _require_contract(self, *, root: bool) -> None:
        contract_type = getattr(health_package, "HostReleaseContract", None)
        if callable(contract_type):
            self.contract = contract_type()
            return
        message = (
            "V118-01 prerequisite: HostReleaseContract public Module is not implemented"
        )
        if root:
            raise AssertionError(message)
        self.skipTest(message)

    @staticmethod
    def _create_release_fixture(root: Path) -> tuple[dict[str, str], ...]:
        artifacts: list[tuple[str, str, str]] = [
            ("host/required.patch", "hermes-required-patch", "PATCH:pre-native-v1\n"),
            (
                "host/disabled-native-entry.assertion",
                "disabled-native-entry",
                "ASSERT:native-health-disabled-v1\n",
            ),
            ("product/plugin.py", "health-plugin", "PLUGIN:health-weixin-v1\n"),
            ("product/core.py", "health-core", "CORE:single-writer-v1\n"),
            ("adapters/health_weixin.py", "health-weixin-adapter", "WEIXIN:v1\n"),
            ("adapters/model.py", "model-adapter-interface", "MODEL-ADAPTER:v1\n"),
            (
                "adapters/delivery.py",
                "delivery-adapter-interface",
                "DELIVERY-ADAPTER:v1\n",
            ),
            ("interfaces/core-command.json", "core-command-interface", "{\"v\":1}\n"),
            (
                "interfaces/core-managed-read.json",
                "core-managed-read-interface",
                "{\"v\":1}\n",
            ),
            (
                "interfaces/core-controlled-effect.json",
                "core-controlled-effect-interface",
                "{\"v\":1}\n",
            ),
            ("schemas/health-state.json", "health-state-schema", "{\"v\":1}\n"),
            (
                "model/capability-profile-schema.json",
                "capability-profile-schema",
                "{\"v\":1}\n",
            ),
            (
                "model/capability-profile-builder.py",
                "capability-profile-builder",
                "CAPABILITY-BUILDER:v1\n",
            ),
            (
                "model/capability-profile-validator.py",
                "capability-profile-validator",
                "CAPABILITY-VALIDATOR:v1\n",
            ),
            (
                "bundles/minimum-help.json",
                "minimum-help-bundle",
                "{\"bundle\":\"minimum-help-v1\"}\n",
            ),
            ("bundles/knowledge.json", "knowledge-bundle", "{\"bundle\":\"knowledge-v1\"}\n"),
            ("bundles/safety.json", "safety-bundle", "{\"bundle\":\"safety-v1\"}\n"),
            (
                "bundles/diagnostic.json",
                "diagnostic-bundle",
                "{\"bundle\":\"diagnostic-v1\"}\n",
            ),
            ("migration/protocol.json", "migration-protocol", "{\"v\":1}\n"),
            ("migration/schema.json", "migration-schema", "{\"v\":1}\n"),
            ("migration/builder.py", "migration-builder", "MIGRATION-BUILDER:v1\n"),
            (
                "migration/semantic-registry.json",
                "migration-semantic-registry",
                "{\"families\":[\"synthetic\"]}\n",
            ),
            ("environment/python.txt", "python-constraint", ">=3.11,<3.12\n"),
            ("environment/dependencies.lock", "dependency-constraint", "synthetic==1\n"),
            (
                "environment/service-acl.json",
                "service-identity-acl-requirement",
                "{\"service\":\"health-core\",\"acl\":\"required\"}\n",
            ),
        ]
        for index, skill in enumerate(_SKILLS, start=1):
            artifacts.append(
                (
                    f"skills/{skill}/SKILL.md",
                    f"skill:{skill}",
                    f"# {skill}\nversion: 1.0.{index}\n",
                )
            )
        for relative, _role, body in artifacts:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8", newline="\n")
        runtime = root / "runtime" / "instance-manifest.json"
        runtime.parent.mkdir(parents=True, exist_ok=True)
        runtime.write_text('{"generation":1,"site":"synthetic-a"}\n', encoding="utf-8")
        return tuple({"path": path, "role": role} for path, role, _body in artifacts)

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

    def _build(self, sources: Mapping[str, object] | None = None) -> tuple[object, dict[str, object]]:
        assert self.contract is not None
        build = getattr(self.contract, "build", None)
        if not callable(build):
            raise AssertionError("HostReleaseContract.build is unavailable")
        manifest = build(self._release_sources() if sources is None else sources)
        return manifest, _wire(manifest, "release manifest")

    def _pinned_source(
        self,
        *,
        credential_adapter: _SyntheticCredentialAdapter | None = None,
        core_port_adapter: _SyntheticCorePortAdapter | None = None,
        effect_adapter: _SyntheticEffectAdapter | None = None,
        controlled_effect_probe: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if self.pinned_root is None:
            raise AssertionError(
                "TICKET118_PINNED_HERMES_SOURCE must name the local pinned checkout"
            )
        source: dict[str, object] = {
            "contract": "ticket118-pinned-hermes-source-v1",
            "root": str(self.pinned_root),
            "commit": _PINNED_COMMIT,
            "allowlisted_files": [
                {"path": path, "sha256": digest}
                for path, digest in _PINNED_FILES.items()
            ],
            "credential_adapter": (
                _SyntheticCredentialAdapter()
                if credential_adapter is None
                else credential_adapter
            ),
            "core_port_adapter": (
                _SyntheticCorePortAdapter()
                if core_port_adapter is None
                else core_port_adapter
            ),
        }
        if effect_adapter is not None:
            source["effect_adapter"] = effect_adapter
        if controlled_effect_probe is not None:
            source["controlled_effect_probe"] = copy.deepcopy(
                dict(controlled_effect_probe)
            )
        return source

    def _verify(
        self,
        manifest: object,
        source: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        assert self.contract is not None
        verify = getattr(self.contract, "verify", None)
        if not callable(verify):
            raise AssertionError("HostReleaseContract.verify is unavailable")
        report = verify(manifest, self._pinned_source() if source is None else source)
        return _wire(report, "host contract report")

    def _assess(self, assessment: Mapping[str, object]) -> dict[str, object]:
        assert self.contract is not None
        assess = getattr(self.contract, "assess", None)
        if not callable(assess):
            raise AssertionError("HostReleaseContract.assess is unavailable")
        return _wire(assess(assessment), "readiness report")

    def test_v118_01_release_is_reproducible_complete_and_instance_free(self) -> None:
        """A1: a managed artifact cannot drift without changing the release."""

        self._require_contract(root=True)
        first, first_wire = self._build()
        _second, second_wire = self._build()
        self.assertEqual(first_wire, second_wire)
        self.assertEqual(first_wire.get("contract"), "ticket118-release-manifest-v1")
        digest = first_wire.get("release_digest")
        self.assertIsInstance(digest, str)
        self.assertTrue(str(digest).startswith("sha256:"), digest)

        verified = first_wire.get("repository_verified")
        self.assertIsInstance(verified, list)
        verified_roles = {
            item.get("role")
            for item in verified  # type: ignore[union-attr]
            if type(item) is dict
        }
        self.assertEqual(verified_roles, {item["role"] for item in self.artifacts})
        self.assertNotIn(str(self.release_root), repr(first_wire))
        self.assertNotIn("synthetic-a", repr(first_wire))

        outside = self.release_root / "runtime" / "instance-manifest.json"
        outside.write_text('{"generation":99,"site":"synthetic-b"}\n', encoding="utf-8")
        _outside_manifest, outside_wire = self._build()
        self.assertEqual(outside_wire, first_wire)

        minimum = self.release_root / "bundles" / "minimum-help.json"
        minimum.write_text('{"bundle":"minimum-help-v2"}\n', encoding="utf-8")
        _changed, changed_wire = self._build()
        self.assertNotEqual(changed_wire.get("release_digest"), digest)
        self.assertNotEqual(_wire(first, "release manifest"), changed_wire)

    def test_v118_02_real_pinned_lifecycle_registers_only_health_weixin(self) -> None:
        """A2: a hand-written host stub cannot satisfy positive evidence."""

        self._require_contract(root=False)
        self.assertIsNotNone(
            self.pinned_root,
            "TICKET118_PINNED_HERMES_SOURCE must name the local pinned checkout",
        )
        assert self.pinned_root is not None
        self.assertTrue(self.pinned_root.is_dir(), self.pinned_root)
        head = subprocess.run(
            ["git", "-C", str(self.pinned_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(head, _PINNED_COMMIT)
        for relative, expected in _PINNED_FILES.items():
            with self.subTest(upstream_file=relative):
                self.assertEqual(_sha256(self.pinned_root / relative), expected)

        manifest, _wire_manifest = self._build()
        report = self._verify(manifest)
        self.assertEqual(report.get("verdict"), "pass", report)
        self.assertIsInstance(report.get("activation_proof"), str)
        lifecycle = report.get("pinned_lifecycle")
        self.assertIsInstance(lifecycle, dict)
        self.assertTrue(lifecycle.get("actual_interface_loaded"))  # type: ignore[union-attr]
        self.assertEqual(lifecycle.get("commit"), _PINNED_COMMIT)  # type: ignore[union-attr]
        self.assertEqual(lifecycle.get("registered_platforms"), ["health_weixin"])  # type: ignore[union-attr]
        self.assertEqual(
            lifecycle.get("lifecycle_results"),  # type: ignore[union-attr]
            {"register": "pass", "factory": "pass", "start": "pass", "stop": "pass"},
        )
        self.assertEqual(lifecycle.get("entry_order"), "pre-native")  # type: ignore[union-attr]

        wrong = self._pinned_source()
        wrong_files = copy.deepcopy(wrong["allowlisted_files"])
        assert type(wrong_files) is list and type(wrong_files[0]) is dict
        wrong_files[0]["sha256"] = "0" * 64
        wrong["allowlisted_files"] = wrong_files
        rejected = self._verify(manifest, wrong)
        self.assertEqual(rejected.get("verdict"), "fail")
        self.assertIsNone(rejected.get("activation_proof"))

    def test_v118_03_core_port_is_three_strict_fail_closed_interfaces(self) -> None:
        """A3: a socket shell cannot hide direct or incomplete core effects."""

        self._require_contract(root=False)
        manifest, _manifest_wire = self._build()
        report = self._verify(manifest)
        port = report.get("core_port")
        self.assertIsInstance(port, dict)
        self.assertEqual(
            port.get("interfaces"),  # type: ignore[union-attr]
            ["command", "managed-read", "controlled-effect"],
        )
        self.assertFalse(port.get("generic_rpc"))  # type: ignore[union-attr]
        self.assertEqual(port.get("frame"), "protocol-v1-length-canonical-json-64k")  # type: ignore[union-attr]

        failed = self._verify(
            manifest,
            self._pinned_source(
                credential_adapter=_SyntheticCredentialAdapter(peer="ordinary-agent")
            ),
        )
        self.assertEqual(failed.get("verdict"), "fail")
        self.assertIsNone(failed.get("activation_proof"))

    def test_v118_04_adapters_cannot_forge_intent_terminal_or_state(self) -> None:
        """A4: a transport cannot turn its own observation into health truth."""

        self._require_contract(root=False)
        manifest, _manifest_wire = self._build()
        adapter = _SyntheticEffectAdapter()
        report = self._verify(
            manifest,
            self._pinned_source(
                effect_adapter=adapter,
                controlled_effect_probe={
                    "intent_id": "synthetic-forged-intent",
                    "authority": "adapter-self-issued",
                    "terminal": {"status": "completed", "terminal": True},
                },
            ),
        )
        self.assertEqual(report.get("verdict"), "fail")
        self.assertEqual(adapter.calls, [])
        self.assertIsNone(report.get("activation_proof"))
        positive = self._verify(manifest)
        authority = positive.get("controlled_effect")
        self.assertIsInstance(authority, dict)
        self.assertTrue(authority.get("core_issued_intent_required"))  # type: ignore[union-attr]
        self.assertTrue(authority.get("complete_terminal_required"))  # type: ignore[union-attr]
        self.assertEqual(
            authority.get("forbidden_write_interfaces"),  # type: ignore[union-attr]
            ["session", "memory", "observer", "generic-state-rpc"],
        )

    def test_v118_05_old_health_entries_never_return_on_host_failure(self) -> None:
        """A5: a disabled assertion cannot replace actual reachability proof."""

        self._require_contract(root=False)
        manifest, _manifest_wire = self._build()
        report = self._verify(manifest)
        entry = report.get("entrypoints")
        self.assertIsInstance(entry, dict)
        self.assertEqual(entry.get("reachable_health_entries"), ["health_weixin"])  # type: ignore[union-attr]
        self.assertEqual(entry.get("blocked_entries"), [  # type: ignore[union-attr]
            "medical",
            "health-autonomy",
            "health-guard",
            "native-health",
            "ordinary-agent-health",
        ])
        self.assertTrue(entry.get("required_patch_hash_bound"))  # type: ignore[union-attr]
        self.assertTrue(entry.get("native_disable_hash_bound"))  # type: ignore[union-attr]

        failed = self._verify(
            manifest,
            self._pinned_source(
                core_port_adapter=_SyntheticCorePortAdapter(callback_fails=True)
            ),
        )
        self.assertEqual(failed.get("verdict"), "fail")
        self.assertEqual(
            failed.get("reachable_health_entries"),
            [],
        )
        self.assertIsNone(failed.get("activation_proof"))

    def test_v118_06_readiness_preserves_unknown_and_rejects_unsafe_rollback(self) -> None:
        """A6: missing target facts cannot be skipped or replaced by old files."""

        self._require_contract(root=False)
        manifest, manifest_wire = self._build()
        host_report = self._verify(manifest)

        install = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "install",
                "release_manifest": manifest_wire,
                "host_report": host_report,
                "target_observations": {},
            }
        )
        self.assertEqual(install.get("verdict"), "cannot-confirm")
        self.assertEqual(set(install.get("missing_requirements", [])), set(_TARGET_REQUIREMENTS))

        upgrade = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "upgrade",
                "release_manifest": manifest_wire,
                "host_report": host_report,
                "target_observations": {
                    requirement: "verified" for requirement in _TARGET_REQUIREMENTS
                },
                "compatibility": {"schema": "drift"},
            }
        )
        self.assertEqual(upgrade.get("verdict"), "fail")

        rollback = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "rollback",
                "release_manifest": manifest_wire,
                "host_report": host_report,
                "target_observations": {
                    requirement: "verified" for requirement in _TARGET_REQUIREMENTS
                },
                "compatibility": {
                    "semantic_manifest": "compatible",
                    "generation": "stale",
                    "writer_fence": "stale",
                },
            }
        )
        self.assertEqual(rollback.get("verdict"), "fail")
        self.assertFalse(rollback.get("restore_instance_state", True))

    def test_v118_07_release_classification_never_leaks_or_promotes_target_facts(self) -> None:
        """A7: synthetic or secret values cannot become release/Partner proof."""

        self._require_contract(root=False)
        _manifest, wire = self._build()
        target = set(wire.get("target_binding_required", []))
        external = set(wire.get("external_approval_required", []))
        forbidden = set(wire.get("forbidden_secret_classes", []))
        self.assertEqual(target, set(_TARGET_REQUIREMENTS))
        self.assertEqual(external, set(_EXTERNAL_REQUIREMENTS))
        self.assertEqual(forbidden, set(_SECRET_CLASSES))
        self.assertFalse(target & external)
        self.assertFalse(target & forbidden)
        self.assertFalse(external & forbidden)
        for marker in ("TICKET118_SYNTHETIC_TOKEN_SHOULD_NOT_LEAK", r"C:\owner\health.db"):
            with self.subTest(marker=marker):
                path = self.release_root / "bundles" / "knowledge.json"
                original = path.read_text(encoding="utf-8")
                path.write_text(marker, encoding="utf-8")
                try:
                    with self.assertRaises(ValueError):
                        self._build()
                finally:
                    path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

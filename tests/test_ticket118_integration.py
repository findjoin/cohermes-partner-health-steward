"""Verifier-owned RED gates for Ticket 118's public release/host seam.

The suite observes only HostReleaseContract.build/verify/assess and synthetic
system-boundary adapter records.  It never reads a Partner profile, secrets,
health data, product private helpers, or release implementation state.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import partner_health_steward as health_package


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
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
    """External-effect Adapter whose call record is the independent oracle."""

    def __init__(self, result: Mapping[str, object] | None = None) -> None:
        self.calls: list[object] = []
        self._result = dict(
            {
                "status": "accepted",
                "terminal": True,
                "result_ref": "synthetic-result:ticket118",
            }
            if result is None
            else result
        )

    def execute(self, intent: object) -> Mapping[str, object]:
        self.calls.append(copy.deepcopy(intent))
        return copy.deepcopy(self._result)


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


class _RealSocketCorePortAdapter:
    """Real local socket transport into the existing strict HealthPlugin frame seam."""

    def __init__(
        self,
        *,
        callback_fails: bool = False,
        frame_fault: str | None = None,
        terminal: bool = True,
    ) -> None:
        self.callback_fails = callback_fails
        self.frame_fault = frame_fault
        self.terminal = terminal
        self.calls: list[str] = []
        self.frames: list[bytes] = []
        self.responses: list[bytes] = []
        self._harness: object | None = None

    def close(self) -> None:
        harness, self._harness = self._harness, None
        if harness is not None:
            harness.tearDown()

    def _plugin(self) -> object:
        if self._harness is None:
            from tests.test_ticket110_boundary import Ticket110BoundaryTests

            harness = Ticket110BoundaryTests("test_probe_is_read_only")
            harness.setUp()
            self._harness = harness
        return self._harness.plugin

    def _mutate_frame(self, frame: bytes) -> bytes:
        if self.frame_fault == "truncated":
            return frame[:-1]
        if self.frame_fault == "trailing":
            return frame + b"x"
        if self.frame_fault == "unknown-kind":
            value = json.loads(frame[4:].decode("utf-8"))
            value["action"] = "unknown.kind"
            body = json.dumps(
                value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            return struct.pack(">I", len(body)) + body
        return frame

    @staticmethod
    def _socket_pair() -> tuple[socket.socket, socket.socket]:
        if hasattr(socket, "AF_UNIX"):
            return socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        # This Python build lacks AF_UNIX.  The same real byte-stream framing
        # Seam is exercised locally; Linux peer credentials remain Ticket 119.
        return socket.socketpair()

    def command(self, value: object) -> bytes:
        self.calls.append("command")
        if self.callback_fails:
            raise RuntimeError("synthetic core callback unavailable")
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("CorePort.command requires one encoded frame")
        frame = self._mutate_frame(bytes(value))
        self.frames.append(frame)
        client, server = self._socket_pair()
        try:
            client.sendall(frame)
            client.shutdown(socket.SHUT_WR)
            received = bytearray()
            while True:
                chunk = server.recv(65536)
                if not chunk:
                    break
                received.extend(chunk)
            response = self._plugin().handle_frame(bytes(received), peer_id="plugin")
            server.sendall(response)
            server.shutdown(socket.SHUT_WR)
            returned = bytearray()
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                returned.extend(chunk)
            response_frame = bytes(returned)
            self.responses.append(response_frame)
            return response_frame
        finally:
            client.close()
            server.close()

    def managed_read(self, value: object) -> Mapping[str, object]:
        del value
        self.calls.append("managed-read")
        return {"status": "available", "projection": {}}

    def execute_effect(self, value: object) -> Mapping[str, object]:
        del value
        self.calls.append("controlled-effect")
        return {"status": "accepted", "terminal": self.terminal}


class _PinnedHermesObserver:
    """Independent observation of calls into the real pinned host classes."""

    def __init__(self, registry: object) -> None:
        self.registry = registry
        self.register_calls: list[dict[str, object]] = []
        self.manager_types: list[type[object]] = []
        self.factory_instances: list[object] = []
        self.lifecycle_calls: list[str] = []

    def observe_registration(
        self,
        context: object,
        args: tuple[object, ...],
        kwargs: Mapping[str, object],
    ) -> None:
        name = kwargs.get("name", args[0] if args else None)
        factory = kwargs.get("adapter_factory", args[2] if len(args) > 2 else None)
        self.register_calls.append({"name": name, "factory": factory})
        self.manager_types.append(type(getattr(context, "_manager", None)))

    def exercise_factory(self, entry: object, core_port: object) -> None:
        factory = getattr(entry, "adapter_factory", None)
        if not callable(factory):
            raise AssertionError("health_weixin registration has no factory")
        adapter = factory(
            SimpleNamespace(
                enabled=True,
                extra={
                    "ticket118_offline_verification": True,
                    "core_port_adapter": core_port,
                },
            )
        )
        self.factory_instances.append(adapter)
        for method_name in ("start", "stop"):
            method = getattr(adapter, method_name, None)
            if not callable(method):
                raise AssertionError(
                    f"health_weixin Adapter has no {method_name} lifecycle Interface"
                )
            result = method()
            if inspect.isawaitable(result):
                import asyncio

                asyncio.run(result)
            self.lifecycle_calls.append(method_name)


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


@contextmanager
def _observe_pinned_hermes(root: Path):
    """Patch only observation points while retaining real pinned behavior."""

    root_text = str(root.resolve())
    inserted = root_text not in sys.path
    if inserted:
        sys.path.insert(0, root_text)
    try:
        plugins = importlib.import_module("hermes_cli.plugins")
        registry_module = importlib.import_module("gateway.platform_registry")
        for module in (plugins, registry_module):
            module_path = Path(inspect.getsourcefile(module) or "").resolve()
            if root.resolve() not in module_path.parents:
                raise AssertionError(f"pinned Hermes module loaded outside checkout: {module_path}")
        registry = registry_module.PlatformRegistry()
        observer = _PinnedHermesObserver(registry)
        original = plugins.PluginContext.register_platform

        def observed_register(context: object, *args: object, **kwargs: object) -> None:
            observer.observe_registration(context, args, kwargs)
            original(context, *args, **kwargs)

        with patch.object(registry_module, "platform_registry", registry), patch.object(
            plugins.PluginContext, "register_platform", observed_register
        ):
            yield observer
    finally:
        if inserted:
            sys.path.remove(root_text)


@contextmanager
def _core_issued_effect_probe():
    """Yield one real current core intent/grant and close its local authority store."""

    from tests.test_ticket110_boundary import Ticket110BoundaryTests

    harness = Ticket110BoundaryTests("test_probe_is_read_only")
    harness.setUp()
    try:
        issued = harness.send(
            harness.command(
                "effect.request",
                "ticket118-effect",
                harness.effect_request_payload(request_digest="sha256:ticket118-effect"),
            )
        )
        if issued.status != "accepted":
            raise AssertionError(f"core failed to issue controlled effect: {issued.status}")
        intent = issued.meta.intent
        grant = harness.plugin.claim_effect_execution(intent)
        if grant is None:
            raise AssertionError("core failed to grant controlled effect execution")
        yield harness, intent, grant
    finally:
        harness.tearDown()


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
        self._core_port_adapters: list[_RealSocketCorePortAdapter] = []

    def tearDown(self) -> None:
        for adapter in self._core_port_adapters:
            adapter.close()
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
            (
                "migration/ticket117-synthetic-fixture.py",
                "migration-synthetic-fixture",
                "REPLACED-BY-CURRENT-TICKET117-FIXTURE\n",
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
        # These are the real current plugin/host/adapter artifacts.  Positive
        # host evidence must load them into the pinned Hermes checkout; marker
        # files are not allowed to stand in for current integration code.
        current_sources = {
            "host/required.patch": (
                _REPOSITORY_ROOT
                / "ops/partner-health-steward/plugin/health-steward/__init__.py"
            ),
            "host/disabled-native-entry.assertion": (
                _REPOSITORY_ROOT / "ops/partner-health-steward/deployment.py"
            ),
            "product/plugin.py": _REPOSITORY_ROOT / "partner_health_steward/plugin.py",
            "product/core.py": _REPOSITORY_ROOT / "partner_health_steward/core.py",
            "adapters/health_weixin.py": (
                _REPOSITORY_ROOT
                / "ops/partner-health-steward/plugin/health-steward/weixin_adapter.py"
            ),
            "adapters/model.py": (
                _REPOSITORY_ROOT / "partner_health_steward/model_contract.py"
            ),
            "adapters/delivery.py": (
                _REPOSITORY_ROOT / "partner_health_steward/delivery.py"
            ),
            "migration/ticket117-synthetic-fixture.py": (
                _REPOSITORY_ROOT / "tests/test_ticket117_integration.py"
            ),
        }
        for relative, source in current_sources.items():
            shutil.copyfile(source, root / relative)
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
        core_port_adapter: _RealSocketCorePortAdapter | None = None,
        effect_adapter: _SyntheticEffectAdapter | None = None,
        controlled_effect_probe: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if self.pinned_root is None:
            raise AssertionError(
                "TICKET118_PINNED_HERMES_SOURCE must name the local pinned checkout"
            )
        selected_core_port = (
            _RealSocketCorePortAdapter()
            if core_port_adapter is None
            else core_port_adapter
        )
        self._core_port_adapters.append(selected_core_port)
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
            "core_port_adapter": selected_core_port,
        }
        if effect_adapter is not None:
            source["effect_adapter"] = effect_adapter
        if controlled_effect_probe is not None:
            source["controlled_effect_probe"] = dict(controlled_effect_probe)
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
        expected_verified = sorted(
            (
                {
                    "path": item["path"],
                    "role": item["role"],
                    "sha256": "sha256:" + _sha256(self.release_root / item["path"]),
                }
                for item in self.artifacts
            ),
            key=lambda item: item["path"],
        )
        self.assertTrue(all(type(item) is dict for item in verified), verified)
        actual_verified = sorted(
            (copy.deepcopy(item) for item in verified),  # type: ignore[union-attr]
            key=lambda item: item.get("path", ""),
        )
        self.assertEqual(actual_verified, expected_verified)
        self.assertNotIn(str(self.release_root), repr(first_wire))
        self.assertNotIn("synthetic-a", repr(first_wire))

        outside = self.release_root / "runtime" / "instance-manifest.json"
        outside.write_text('{"generation":99,"site":"synthetic-b"}\n', encoding="utf-8")
        _outside_manifest, outside_wire = self._build()
        self.assertEqual(outside_wire, first_wire)

        # One equivalence loop proves every managed artifact participates in
        # the release digest; it is not a field/artifact Cartesian matrix.
        for artifact in self.artifacts:
            with self.subTest(managed_artifact=artifact["path"]):
                path = self.release_root / artifact["path"]
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"\nTICKET118-MANAGED-DRIFT\n")
                    _changed, changed_wire = self._build()
                    self.assertNotEqual(changed_wire.get("release_digest"), digest)
                    self.assertNotEqual(_wire(first, "release manifest"), changed_wire)
                finally:
                    path.write_bytes(original)

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
        positive_source = self._pinned_source()
        with _observe_pinned_hermes(self.pinned_root) as observer:
            report = self._verify(manifest, positive_source)
            entries = observer.registry.all_entries()
            self.assertEqual([entry.name for entry in entries], ["health_weixin"])
            self.assertEqual(
                [call["name"] for call in observer.register_calls],
                ["health_weixin"],
            )
            plugins = importlib.import_module("hermes_cli.plugins")
            self.assertEqual(observer.manager_types, [plugins.PluginManager])
            entry = observer.registry.get("health_weixin")
            self.assertIsNotNone(entry)
            observer.exercise_factory(entry, positive_source["core_port_adapter"])

        self.assertEqual(report.get("verdict"), "pass", report)
        self.assertIsInstance(report.get("activation_proof"), str)
        self.assertEqual(observer.lifecycle_calls, ["start", "stop"])
        self.assertEqual(len(observer.factory_instances), 1)
        adapter_source = Path(
            inspect.getsourcefile(type(observer.factory_instances[0])) or ""
        ).resolve()
        self.assertEqual(
            adapter_source,
            (self.release_root / "adapters/health_weixin.py").resolve(),
            "factory must load the allowlisted release artifact, not the source tree",
        )
        self.assertEqual(
            _sha256(adapter_source),
            _sha256(self.release_root / "adapters/health_weixin.py"),
            "factory must instantiate the current release Adapter artifact",
        )

        wrong = self._pinned_source()
        wrong_files = copy.deepcopy(wrong["allowlisted_files"])
        assert type(wrong_files) is list and type(wrong_files[0]) is dict
        wrong_files[0]["sha256"] = "0" * 64
        wrong["allowlisted_files"] = wrong_files
        with _observe_pinned_hermes(self.pinned_root) as rejected_observer:
            rejected = self._verify(manifest, wrong)
        self.assertEqual(rejected.get("verdict"), "fail")
        self.assertIsNone(rejected.get("activation_proof"))
        self.assertEqual(rejected_observer.register_calls, [])

    def test_v118_03_core_port_is_three_strict_fail_closed_interfaces(self) -> None:
        """A3: a socket shell cannot hide direct or incomplete core effects."""

        self._require_contract(root=False)
        manifest, _manifest_wire = self._build()
        positive_adapter = _RealSocketCorePortAdapter()
        report = self._verify(
            manifest,
            self._pinned_source(core_port_adapter=positive_adapter),
        )
        self.assertEqual(report.get("verdict"), "pass", report)
        self.assertGreaterEqual(len(positive_adapter.frames), 1)
        self.assertEqual(len(positive_adapter.responses), len(positive_adapter.frames))
        from partner_health_steward.contract import decode_frame, decode_response_frame

        for frame, response in zip(
            positive_adapter.frames, positive_adapter.responses, strict=True
        ):
            self.assertEqual(decode_frame(frame).peer, "plugin")
            self.assertIn(
                decode_response_frame(response).status,
                {"accepted", "replayed"},
            )

        variants = (
            (
                "wrong-peer",
                _SyntheticCredentialAdapter(peer="ordinary-agent"),
                _RealSocketCorePortAdapter(),
            ),
            (
                "truncated-frame",
                _SyntheticCredentialAdapter(),
                _RealSocketCorePortAdapter(frame_fault="truncated"),
            ),
            (
                "trailing-frame",
                _SyntheticCredentialAdapter(),
                _RealSocketCorePortAdapter(frame_fault="trailing"),
            ),
            (
                "unknown-kind",
                _SyntheticCredentialAdapter(),
                _RealSocketCorePortAdapter(frame_fault="unknown-kind"),
            ),
            (
                "incomplete-terminal",
                _SyntheticCredentialAdapter(),
                _RealSocketCorePortAdapter(terminal=False),
            ),
        )
        for label, credential, core_port in variants:
            with self.subTest(representative_fault=label):
                failed = self._verify(
                    manifest,
                    self._pinned_source(
                        credential_adapter=credential,
                        core_port_adapter=core_port,
                    ),
                )
                self.assertIn(failed.get("verdict"), {"fail", "cannot-confirm"})
                self.assertIsNone(failed.get("activation_proof"))

    def test_v118_04_adapters_cannot_forge_intent_terminal_or_state(self) -> None:
        """A4: a transport cannot turn its own observation into health truth."""

        self._require_contract(root=False)
        manifest, _manifest_wire = self._build()
        with _core_issued_effect_probe() as (_harness, intent, grant):
            legal_adapter = _SyntheticEffectAdapter()
            legal = self._verify(
                manifest,
                self._pinned_source(
                    effect_adapter=legal_adapter,
                    controlled_effect_probe={"intent": intent, "grant": grant},
                ),
            )
            self.assertEqual(legal.get("verdict"), "pass", legal)
            self.assertEqual(len(legal_adapter.calls), 1)

            stale_authority = replace(
                intent.authority,
                writer_fence="fence:ticket118-stale",
            )
            stale_intent = replace(intent, authority=stale_authority)
            faults = (
                (
                    "forged-intent",
                    {
                        "intent": {
                            "effect_id": "effect:forged",
                            "effect_kind": "model-work",
                            "intent_digest": "sha256:forged",
                            "authority": "adapter-self-issued",
                        },
                        "grant": grant,
                    },
                    _SyntheticEffectAdapter(),
                    0,
                ),
                (
                    "stale-writer-fence",
                    {"intent": stale_intent, "grant": grant},
                    _SyntheticEffectAdapter(),
                    0,
                ),
                (
                    "missing-terminal",
                    {"intent": intent, "grant": grant},
                    _SyntheticEffectAdapter(
                        {"status": "accepted", "result_ref": "synthetic:missing"}
                    ),
                    1,
                ),
            )
            for label, probe, adapter, expected_calls in faults:
                with self.subTest(representative_fault=label):
                    rejected = self._verify(
                        manifest,
                        self._pinned_source(
                            effect_adapter=adapter,
                            controlled_effect_probe=probe,
                        ),
                    )
                    self.assertIn(
                        rejected.get("verdict"), {"fail", "cannot-confirm"}
                    )
                    self.assertEqual(len(adapter.calls), expected_calls)
                    self.assertIsNone(rejected.get("activation_proof"))

        self.assertNotIn("session", repr(legal_adapter.calls).lower())
        self.assertNotIn("memory", repr(legal_adapter.calls).lower())
        self.assertNotIn("observer", repr(legal_adapter.calls).lower())
        self.assertNotIn("generic-state-rpc", repr(legal_adapter.calls).lower())

    def test_v118_05_old_health_entries_never_return_on_host_failure(self) -> None:
        """A5: a disabled assertion cannot replace actual reachability proof."""

        self._require_contract(root=False)
        manifest, _manifest_wire = self._build()
        failing_core = _RealSocketCorePortAdapter(callback_fails=True)
        assert self.pinned_root is not None
        with _observe_pinned_hermes(self.pinned_root) as observer:
            failed = self._verify(
                manifest,
                self._pinned_source(core_port_adapter=failing_core),
            )
            self.assertTrue(
                all(call["name"] == "health_weixin" for call in observer.register_calls),
                observer.register_calls,
            )
            self.assertEqual(observer.registry.all_entries(), [])
            for obsolete in (
                "medical",
                "health-autonomy",
                "health-guard",
                "native-health",
                "ordinary-agent-health",
                "weixin",
            ):
                with self.subTest(obsolete_health_entry=obsolete):
                    self.assertIsNone(observer.registry.get(obsolete))
        self.assertEqual(failed.get("verdict"), "fail")
        self.assertIsNone(failed.get("activation_proof"))
        self.assertEqual(failing_core.calls, ["command"])

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

        synthetic_install = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "install",
                "release_manifest": manifest_wire,
                "host_report": host_report,
                "target_observations": {
                    requirement: {
                        "status": "verified",
                        "evidence_class": "synthetic",
                    }
                    for requirement in _TARGET_REQUIREMENTS
                },
            }
        )
        self.assertEqual(synthetic_install.get("verdict"), "cannot-confirm")

        offline_upgrade = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "upgrade",
                "assessment_scope": "offline-release-compatibility",
                "release_manifest": manifest_wire,
                "host_report": host_report,
                "target_binding_required": [],
                "target_observations": {},
                "compatibility": {
                    "artifact_graph": "compatible",
                    "schema": "compatible",
                    "migration": "compatible",
                },
            }
        )
        self.assertEqual(offline_upgrade.get("verdict"), "pass", offline_upgrade)
        self.assertEqual(
            offline_upgrade.get("assessment_scope"),
            "offline-release-compatibility",
        )
        self.assertIsNone(offline_upgrade.get("activation_proof"))

        upgrade = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "upgrade",
                "release_manifest": manifest_wire,
                "host_report": host_report,
                "target_observations": {
                    requirement: {
                        "status": "verified",
                        "evidence_class": "synthetic",
                    }
                    for requirement in _TARGET_REQUIREMENTS
                },
                "compatibility": {"schema": "drift"},
            }
        )
        self.assertEqual(upgrade.get("verdict"), "fail")

        offline_rollback = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "rollback",
                "assessment_scope": "offline-release-compatibility",
                "release_manifest": manifest_wire,
                "host_report": host_report,
                "target_binding_required": [],
                "target_observations": {},
                "compatibility": {
                    "semantic_manifest": "compatible",
                    "generation": "current",
                    "writer_fence": "current",
                },
            }
        )
        self.assertEqual(offline_rollback.get("verdict"), "pass", offline_rollback)
        self.assertEqual(
            offline_rollback.get("assessment_scope"),
            "offline-release-compatibility",
        )
        self.assertIsNone(offline_rollback.get("activation_proof"))
        self.assertFalse(offline_rollback.get("restore_instance_state", True))

        rollback = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "rollback",
                "release_manifest": manifest_wire,
                "host_report": host_report,
                "target_observations": {
                    requirement: {
                        "status": "verified",
                        "evidence_class": "synthetic",
                    }
                    for requirement in _TARGET_REQUIREMENTS
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
        manifest, wire = self._build()
        target = set(wire.get("target_binding_required", []))
        external = set(wire.get("external_approval_required", []))
        forbidden = set(wire.get("forbidden_secret_classes", []))
        self.assertEqual(target, set(_TARGET_REQUIREMENTS))
        self.assertEqual(external, set(_EXTERNAL_REQUIREMENTS))
        self.assertEqual(forbidden, set(_SECRET_CLASSES))
        self.assertFalse(target & external)
        self.assertFalse(target & forbidden)
        self.assertFalse(external & forbidden)

        host_report = self._verify(manifest)
        synthetic_partner = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "install",
                "release_manifest": wire,
                "host_report": host_report,
                "target_observations": {
                    requirement: {
                        "status": "verified",
                        "compatible": True,
                        "evidence_class": "synthetic",
                    }
                    for requirement in _TARGET_REQUIREMENTS
                },
                "compatibility": {
                    "artifact_graph": "compatible",
                    "schema": "compatible",
                    "semantic_manifest": "compatible",
                },
            }
        )
        self.assertEqual(synthetic_partner.get("verdict"), "cannot-confirm")
        self.assertIsNone(synthetic_partner.get("activation_proof"))
        self.assertNotEqual(synthetic_partner.get("partner_verdict"), "pass")
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

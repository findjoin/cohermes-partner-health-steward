"""Verifier-owned Ticket 120 release and default-only staging contract."""

from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_PINNED_HERMES_SOURCE = Path(
    os.environ.get(
        "TICKET118_PINNED_HERMES_SOURCE",
        r"D:\CodexData\tmp\ticket118-hermes-3c27eb",
    )
)
_SKILLS = (
    "health-init",
    "health-steward",
    "health-settings",
    "health-portrait",
    "health-evidence",
    "health-owner-inquiry",
    "health-literature",
)
_DEFAULT_TARGET = {
    "profile": "default",
    "hermes_home": "/root/.hermes",
    "service": "hermes-gateway.service",
}
_TICKET118_MARKER_EXCEPTION_PATH = (
    "plugin/health-weixin/partner_health_steward/host_contract.py"
)
_REQUIRED_ARTIFACTS = (
    ("hermes-required-patch", "host/required.patch"),
    ("disabled-native-entry", "host/disabled-native-entry.assertion"),
    ("hermes-host-health-weixin-adapter", "product/hermes_host.py"),
    ("health-plugin", "product/plugin.py"),
    ("health-core", "product/core.py"),
    ("model-adapter-interface", "adapters/model.py"),
    ("delivery-adapter-interface", "adapters/delivery.py"),
    ("core-command-interface", "interfaces/core-command.json"),
    ("core-managed-read-interface", "interfaces/core-managed-read.json"),
    ("core-controlled-effect-interface", "interfaces/core-controlled-effect.json"),
    ("health-state-schema", "schemas/health-state.json"),
    ("capability-profile-schema", "model/capability-profile-schema.json"),
    ("capability-profile-builder", "model/capability-profile-builder.py"),
    ("capability-profile-validator", "model/capability-profile-validator.py"),
    ("minimum-help-bundle", "bundles/minimum-help.json"),
    ("knowledge-bundle", "bundles/knowledge.json"),
    ("safety-bundle", "bundles/safety.json"),
    ("diagnostic-bundle", "bundles/diagnostic.json"),
    ("migration-protocol", "migration/protocol.json"),
    ("migration-schema", "migration/schema.json"),
    ("migration-builder", "migration/builder.py"),
    ("migration-semantic-registry", "migration/semantic-registry.json"),
    ("migration-synthetic-fixture", "migration/ticket117-synthetic-fixture.py"),
    ("python-constraint", "environment/python.txt"),
    ("dependency-constraint", "environment/dependencies.lock"),
    ("service-identity-acl-requirement", "environment/service-acl.json"),
    *((f"skill:{name}", f"skills/{name}/SKILL.md") for name in _SKILLS),
)
_OBSERVATION_FIELDS = {
    "contract",
    "release_digest",
    "verdict",
    "backup_ref",
    "plugin_state",
    "service",
    "rollback",
    "steps",
    "reason",
    "idempotent",
}
_OBSERVATION_STEPS = {
    "permit-read",
    "permit-consumed",
    "backup",
    "stage",
    "install",
    "restart",
    "is-active",
    "restore",
}


class _ServiceController:
    """Test-only target-local service oracle; never invokes systemd."""

    def __init__(
        self,
        *,
        events: list[str],
        restart_results: list[bool] | None = None,
        active_results: list[bool] | None = None,
    ) -> None:
        self.events = events
        self.restart_results = list(restart_results or (True,))
        self.active_results = list(active_results or ())
        self.calls: list[tuple[str, str]] = []

    def restart(self, service: str) -> bool:
        if service != _DEFAULT_TARGET["service"]:
            raise AssertionError(f"non-default service requested: {service}")
        self.events.append("restart")
        self.calls.append(("restart", service))
        return self.restart_results.pop(0) if self.restart_results else False

    def is_active(self, service: str) -> bool:
        if service != _DEFAULT_TARGET["service"]:
            raise AssertionError(f"non-default service requested: {service}")
        self.events.append("is-active")
        self.calls.append(("is-active", service))
        if self.active_results:
            return self.active_results.pop(0)
        return True


class _DefaultTargetOperations:
    """Temporary backing for the private default-local operations factory."""

    def __init__(
        self,
        root: Path,
        *,
        permit: dict[str, object] | None = None,
        permit_state: str = "valid",
        tamper_after_stage: bool = False,
        extra_after_stage: bool = False,
        install_fails: bool = False,
        restore_ok: bool = True,
    ) -> None:
        self.root = root
        self.events: list[str] = []
        self._backup: Path | None = None
        self._permit = copy.deepcopy(permit)
        self._permit_state = permit_state
        self._consumed_key: str | None = None
        self._tamper_after_stage = tamper_after_stage
        self._extra_after_stage = extra_after_stage
        self._install_fails = install_fails
        self._restore_ok = restore_ok

    @property
    def plugin_root(self) -> Path:
        return self.root / "plugins"

    @property
    def metadata_root(self) -> Path:
        return self.root / "ticket120-release-metadata"

    def deployment_permit(
        self,
        approval_ref: str,
        expected: dict[str, object],
    ) -> str:
        self.events.append("permit-read")
        if self._permit_state != "valid" or self._permit is None:
            return "not-authorized"
        permit_body = {
            name: self._permit.get(name)
            for name in (
                "contract",
                "release_digest",
                "run_id",
                "gate_id",
                "target",
                "expires_at",
            )
        }
        if self._permit.get("digest") != "sha256:" + hashlib.sha256(
            json.dumps(permit_body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest():
            return "not-authorized"
        expires_at = self._permit.get("expires_at")
        if type(expires_at) is not str or expires_at <= "2026-08-30T00:00:00+00:00":
            return "not-authorized"
        if self._permit.get("digest") != approval_ref:
            return "not-authorized"
        for name, value in expected.items():
            if name == "execution_key":
                continue
            if self._permit.get(name) != value:
                return "not-authorized"
        if self._consumed_key is not None:
            return "replay" if self._consumed_key == expected["execution_key"] else "not-authorized"
        return "authorized"

    def consume_deployment_permit(self, approval_ref: str, execution_key: str) -> bool:
        self.events.append("permit-consumed")
        if self._permit is None or self._permit.get("digest") != approval_ref:
            return False
        if self._consumed_key is not None:
            return self._consumed_key == execution_key
        self._consumed_key = execution_key
        return True

    def backup(self) -> str:
        self.events.append("backup")
        self._backup = self.root / "ticket120-backup"
        if self._backup.exists():
            shutil.rmtree(self._backup)
        if self.plugin_root.exists():
            shutil.copytree(self.plugin_root, self._backup / "plugins")
        if self.metadata_root.exists():
            shutil.copytree(self.metadata_root, self._backup / "ticket120-release-metadata")
        return "backup:ticket120"

    def stage(self, release_directory: Path, release_digest: str) -> None:
        self.events.append("stage")
        staged = self.root / "releases" / release_digest.removeprefix("sha256:")
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(release_directory, staged)
        if self._tamper_after_stage:
            skill = staged / "skills" / "health-steward" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
        if self._extra_after_stage:
            (staged / "plugin" / "health-weixin" / "unlisted.py").write_text(
                "unexpected\n", encoding="utf-8"
            )

    def install(self, release_digest: str, execution_key: str) -> None:
        self.events.append("install")
        staged = self.root / "releases" / release_digest.removeprefix("sha256:")
        source = staged / "plugin" / "health-weixin"
        target = self.plugin_root / "health-weixin"
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        self.metadata_root.mkdir(parents=True, exist_ok=True)
        (self.metadata_root / "health-weixin.json").write_text(
            json.dumps({"release_digest": release_digest, "execution_key": execution_key}, sort_keys=True),
            encoding="utf-8",
        )
        if self._install_fails:
            raise RuntimeError("simulated-partial-install")

    def is_staged(self, release_digest: str, execution_key: str) -> bool:
        staged = self.root / "releases" / release_digest.removeprefix("sha256:")
        return (
            (staged / "release-manifest.json").is_file()
            and (self.plugin_root / "health-weixin" / "plugin.yaml").is_file()
            and (self.metadata_root / "health-weixin.json").is_file()
            and json.loads((self.metadata_root / "health-weixin.json").read_text(encoding="utf-8")) == {"release_digest": release_digest, "execution_key": execution_key}
        )

    def restore(self, backup_ref: str) -> bool:
        self.events.append("restore")
        if backup_ref != "backup:ticket120" or self._backup is None or not self._restore_ok:
            return False
        if self.plugin_root.exists():
            shutil.rmtree(self.plugin_root)
        source = self._backup / "plugins"
        if source.exists():
            shutil.copytree(source, self.plugin_root)
        if self.metadata_root.exists():
            shutil.rmtree(self.metadata_root)
        metadata = self._backup / "ticket120-release-metadata"
        if metadata.exists():
            shutil.copytree(metadata, self.metadata_root)
        return True


class Ticket120VerificationTests(unittest.TestCase):
    """Seven public-seam gates for the frozen default-only deployment scope."""

    maxDiff = None

    def setUp(self) -> None:
        linux_v07 = os.environ.get("TICKET120_LINUX_V07") == "1"
        self._temporary = tempfile.TemporaryDirectory(
            prefix="ticket120-v07-" if linux_v07 else "ticket120-",
            dir="/tmp" if linux_v07 else None,
        )
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    @staticmethod
    def _health_package() -> object | None:
        try:
            import partner_health_steward as package
        except ModuleNotFoundError:
            return None
        return package

    def _require_contract(self, *, root: bool) -> tuple[object, object]:
        package = self._health_package()
        publisher = getattr(package, "HermesReleasePublisher", None)
        executor = getattr(package, "DefaultOnlyGateExecutor", None)
        if callable(publisher) and callable(executor):
            return publisher, executor
        message = "V120-01 prerequisite: HermesReleasePublisher and DefaultOnlyGateExecutor public Modules are not implemented"
        if root:
            self.fail(message)
        self.skipTest(message)

    def _build_release(self, publisher_type: object) -> object:
        assert callable(publisher_type)
        return publisher_type(_REPOSITORY_ROOT).build(self.root / "published")

    @staticmethod
    def _published_wire(value: object) -> dict[str, object]:
        method = getattr(value, "to_wire", None)
        if not callable(method):
            raise AssertionError("published release lacks to_wire()")
        result = method()
        if type(result) is not dict or set(result) != {"contract", "release_digest", "host_release_digest", "state", "files"}:
            raise AssertionError("published release wire is not strict")
        return result

    @staticmethod
    def _observation_wire(value: object) -> dict[str, object]:
        method = getattr(value, "to_wire", None)
        if not callable(method):
            raise AssertionError("GateObservation lacks to_wire()")
        result = method()
        if type(result) is not dict or set(result) != _OBSERVATION_FIELDS:
            raise AssertionError("GateObservation wire is not strict")
        if result.get("contract") != "ticket120-gate-observation-v1":
            raise AssertionError("GateObservation contract is invalid")
        digest = result.get("release_digest")
        if digest is not None and (
            type(digest) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        ):
            raise AssertionError("GateObservation digest is invalid")
        if result.get("verdict") not in {"staged", "rejected", "not-authorized", "failed", "cannot-confirm"}:
            raise AssertionError("GateObservation verdict is invalid")
        backup_ref = result.get("backup_ref")
        if backup_ref is not None and (
            type(backup_ref) is not str or re.fullmatch(r"backup:[a-z0-9-]+", backup_ref) is None
        ):
            raise AssertionError("GateObservation backup ref is invalid")
        if result.get("plugin_state") not in {"not-installed", "discovered-staged"}:
            raise AssertionError("GateObservation plugin state is invalid")
        if result.get("service") not in {"not-called", "default-active", "restart-failed", "postcheck-failed", "rollback-active", "cannot-confirm"}:
            raise AssertionError("GateObservation service is invalid")
        if result.get("rollback") not in {"not-needed", "completed", "cannot-confirm"}:
            raise AssertionError("GateObservation rollback is invalid")
        steps = result.get("steps")
        if type(steps) is not list or any(type(step) is not str or step not in _OBSERVATION_STEPS for step in steps):
            raise AssertionError("GateObservation steps are invalid")
        if result.get("reason") not in {
            "staged",
            "request-invalid",
            "release-invalid",
            "permit-not-authorized",
            "stage-invalid",
            "install-failed",
            "restart-failed",
            "postcheck-failed",
            "rollback-unconfirmed",
        }:
            raise AssertionError("GateObservation reason is invalid")
        if type(result.get("idempotent")) is not bool:
            raise AssertionError("GateObservation idempotence is invalid")
        Ticket120VerificationTests._assert_observation_safe(result)
        return result

    @staticmethod
    def _assert_observation_safe(value: object) -> None:
        if type(value) is dict:
            for child in value.values():
                Ticket120VerificationTests._assert_observation_safe(child)
        elif type(value) is list:
            for child in value:
                Ticket120VerificationTests._assert_observation_safe(child)
        elif type(value) is str:
            if re.search(
                r"(^/|^[A-Za-z]:[\\\\/]|^\\\\\\\\|/(?:root|tmp|etc|var|home|Users)/|token|secret|password|credential|config)",
                value,
                flags=re.IGNORECASE,
            ):
                raise AssertionError(f"unsafe observation value: {value!r}")

    def _release_directory(self, published: object) -> Path:
        digest = self._published_wire(published)["release_digest"]
        if type(digest) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise AssertionError("published release digest is invalid")
        return self.root / "published" / digest.removeprefix("sha256:")

    @staticmethod
    def _sha256(path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _canonical_bytes(value: object) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def _prepare_target(self, name: str) -> Path:
        target = self.root / name
        legacy = target / "plugins" / "legacy" / "marker.txt"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("before-ticket120\n", encoding="utf-8")
        return target

    def _request(
        self,
        published: object,
        *,
        run_id: str | None = None,
        target: dict[str, str] | None = None,
        approval_ref: str | None = None,
    ) -> dict[str, object]:
        if run_id is None:
            run_id = os.environ.get("TICKET120_RUN_ID", "ticket120-run-001")
        digest = self._published_wire(published)["release_digest"]
        if type(digest) is not str:
            raise AssertionError("published release digest is unavailable")
        return {
            "contract": "ticket120-default-stage-install-v1",
            "target": copy.deepcopy(_DEFAULT_TARGET if target is None else target),
            "release_directory": str(self._release_directory(published)),
            "run_id": run_id,
            "gate_id": "119-G10",
            "approval_ref": approval_ref or self._permit_for(digest, run_id)["digest"],
        }

    def _permit_for(
        self,
        release_digest: str,
        run_id: str,
        *,
        gate_id: str = "119-G10",
        target: dict[str, str] | None = None,
        expires_at: str = "2099-01-01T00:00:00+00:00",
    ) -> dict[str, object]:
        wire = {
            "contract": "ticket120-deployment-permit-v1",
            "release_digest": release_digest,
            "run_id": run_id,
            "gate_id": gate_id,
            "target": copy.deepcopy(_DEFAULT_TARGET if target is None else target),
            "expires_at": expires_at,
        }
        return {
            **wire,
            "digest": "sha256:" + hashlib.sha256(self._canonical_bytes(wire)).hexdigest(),
        }

    @staticmethod
    def _execute(executor: object, request: dict[str, object]) -> dict[str, object]:
        execute = getattr(executor, "execute", None)
        if not callable(execute):
            raise AssertionError("DefaultOnlyGateExecutor.execute is unavailable")
        return Ticket120VerificationTests._observation_wire(execute(request))

    @contextmanager
    def _simulated_executor(
        self,
        executor_type: object,
        target_root: Path,
        *,
        permit: dict[str, object] | None,
        permit_state: str = "valid",
        restart_results: list[bool] | None = None,
        active_results: list[bool] | None = None,
        tamper_after_stage: bool = False,
        extra_after_stage: bool = False,
        install_fails: bool = False,
        restore_ok: bool = True,
    ):
        assert callable(executor_type)
        operations = _DefaultTargetOperations(
            target_root,
            permit=permit,
            permit_state=permit_state,
            tamper_after_stage=tamper_after_stage,
            extra_after_stage=extra_after_stage,
            install_fails=install_fails,
            restore_ok=restore_ok,
        )
        controller = _ServiceController(
            events=operations.events,
            restart_results=restart_results,
            active_results=active_results,
        )
        with patch("partner_health_steward.release_deployment._default_target_operations", return_value=operations) as target_factory, patch("partner_health_steward.release_deployment._default_service_controller", return_value=controller) as service_factory:
            yield executor_type(), operations, target_factory, service_factory

    def _assert_release_closed(self, published: object) -> dict[str, object]:
        wire = self._published_wire(published)
        self.assertEqual(wire["contract"], "ticket120-hermes-release-v1")
        self.assertEqual(wire["state"], "staged")
        release = self._release_directory(published)
        self.assertEqual(release.name, wire["release_digest"].removeprefix("sha256:"))
        manifest_path = release / "release-manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, wire)
        host_manifest = json.loads((release / "host-release-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(host_manifest["release_digest"], wire["host_release_digest"])
        self.assertEqual(
            tuple(
                (item["role"], item["path"])
                for item in host_manifest["repository_verified"]
            ),
            tuple(sorted(_REQUIRED_ARTIFACTS, key=lambda item: item[1])),
        )
        self.assertEqual(
            wire["release_digest"],
            "sha256:" + hashlib.sha256(self._canonical_bytes({
                "contract": wire["contract"],
                "state": wire["state"],
                "files": wire["files"],
                "host_release_manifest": host_manifest,
            })).hexdigest(),
        )
        self.assertIsInstance(wire["files"], list)
        declared: dict[str, str] = {}
        for item in wire["files"]:
            self.assertIsInstance(item, dict)
            assert isinstance(item, dict)
            self.assertEqual(set(item), {"path", "sha256"})
            path, digest = item["path"], item["sha256"]
            self.assertIsInstance(path, str)
            self.assertIsInstance(digest, str)
            assert isinstance(path, str) and isinstance(digest, str)
            self.assertRegex(path, r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$")
            self.assertNotIn("\\\\", path)
            self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
            self.assertNotIn(path, declared)
            declared[path] = digest
        actual = {path.relative_to(release).as_posix(): self._sha256(path) for path in release.rglob("*") if path.is_file() and path != manifest_path}
        self.assertEqual(declared, actual)
        release_sources = {
            "contract": "ticket118-release-sources-v1",
            "repository_root": str(release),
            "artifacts": [
                {"path": item["path"], "role": item["role"]}
                for item in host_manifest["repository_verified"]
            ],
            "pinned_hermes": host_manifest["pinned_hermes"],
            "environment_constraints": host_manifest["environment_constraints"],
            "target_binding_required": host_manifest["target_binding_required"],
            "external_approval_required": host_manifest["external_approval_required"],
            "forbidden_secret_classes": host_manifest["forbidden_secret_classes"],
        }
        package = self._health_package()
        if package is None:
            raise AssertionError("HostReleaseContract package is unavailable")
        rebuilt = package.HostReleaseContract().build(release_sources).to_wire()
        self.assertEqual(rebuilt, host_manifest)
        for name in ("minimum-help", "knowledge", "safety", "diagnostic"):
            bundle = json.loads((release / "bundles" / f"{name}.json").read_text(encoding="utf-8"))
            self.assertEqual(bundle, {"availability": "unavailable", "status": "staged"})
        return wire

    def _verify_isolated_plugin(self, release: Path) -> None:
        plugin = release / "plugin" / "health-weixin"
        self.assertEqual(self._sha256(plugin / "partner_health_steward" / "hermes_host.py"), self._sha256(_REPOSITORY_ROOT / "partner_health_steward" / "hermes_host.py"))
        self.assertEqual(self._sha256(plugin / "partner_health_steward" / "host_contract.py"), self._sha256(_REPOSITORY_ROOT / "partner_health_steward" / "host_contract.py"))
        hermes_home = self.root / "isolated-hermes-home"
        target_plugin = hermes_home / "plugins" / "health-weixin"
        target_plugin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(plugin, target_plugin)
        (hermes_home / "config.yaml").write_text(
            "plugins:\n  enabled:\n    - health-weixin\n",
            encoding="utf-8",
        )
        script = self.root / "isolated_plugin_check.py"
        script.write_text("""
import json
import os
import sys
from pathlib import Path
home = Path(sys.argv[1])
pinned = sys.argv[2]
os.environ['HERMES_HOME'] = str(home)
os.environ['HOME'] = str(home.parent)
sys.path.insert(0, pinned)
from hermes_cli.plugins import PluginManager
manager = PluginManager()
manager.discover_and_load()
loaded = manager._plugins['health-weixin']
from gateway.platform_registry import platform_registry
entry = platform_registry.get('health_weixin')
module = loaded.module
from partner_health_steward import hermes_host as host
print(json.dumps({'enabled': loaded.enabled, 'kind': loaded.manifest.kind, 'name': loaded.manifest.name, 'platform': entry.name, 'check': entry.check_fn(), 'same': module.register is host.register}))
""".strip(), encoding="utf-8")
        result = subprocess.run([sys.executable, "-I", str(script), str(hermes_home), str(_PINNED_HERMES_SOURCE)], cwd=self.root, check=False, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"enabled": True, "kind": "platform", "name": "health-weixin", "platform": "health_weixin", "check": False, "same": True})

    def _verify_staged_runtime(self, release: Path) -> None:
        runtime_path = release / "runtime" / "core_port_server.py"
        spec = importlib.util.spec_from_file_location("ticket120_runtime", runtime_path)
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        server = module.StagedCorePortServer()
        endpoint = server.start()
        try:
            for kind in ("command", "managed-read", "controlled-effect"):
                with socket.create_connection((endpoint["host"], endpoint["port"]), timeout=2) as client:
                    request = {"protocol_version": 1, "kind": kind, "request_id": f"ticket120-{kind}", "payload": {}}
                    body = json.dumps(request, separators=(",", ":"), sort_keys=True).encode("utf-8")
                    client.sendall(struct.pack(">I", len(body)) + body)
                    length = struct.unpack(">I", self._recv_exact(client, 4))[0]
                    response = json.loads(self._recv_exact(client, length).decode("utf-8"))
                    self.assertEqual(response.get("kind"), kind)
                    self.assertEqual(response.get("request_id"), request["request_id"])
                    self.assertEqual(response.get("status"), "rejected")
                    self.assertEqual(response.get("payload"), {"reason": "health-core-staged"})
            invalid_bodies = (
                json.dumps({"protocol_version": 2, "kind": "command", "request_id": "bad-version", "payload": {}}, separators=(",", ":")).encode("utf-8"),
                json.dumps({"protocol_version": 1, "kind": "unknown", "request_id": "bad-kind", "payload": {}}, separators=(",", ":")).encode("utf-8"),
                json.dumps({"protocol_version": 1, "kind": "command", "request_id": "extra", "payload": {}, "unexpected": True}, separators=(",", ":")).encode("utf-8"),
                b'{"protocol_version":1,"kind":"command","kind":"command","request_id":"duplicate","payload":{}}',
                b'{"protocol_version":true,"kind":"command","request_id":"wrong-type","payload":{}}',
                b'{ "kind": "command", "payload": {}, "protocol_version": 1, "request_id": "noncanonical" }',
            )
            for body in invalid_bodies:
                with socket.create_connection((endpoint["host"], endpoint["port"]), timeout=2) as client:
                    client.sendall(struct.pack(">I", len(body)) + body)
                    client.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1), b"")
            for declared, body in ((16, b"{}"), (65537, b"")):
                with socket.create_connection((endpoint["host"], endpoint["port"]), timeout=2) as client:
                    client.sendall(struct.pack(">I", declared) + body)
                    client.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1), b"")
        finally:
            server.close()

    def _assert_release_marker_policy(self, release: Path) -> None:
        """Keep the one hash-bound policy constant distinct from fixtures."""

        exception = release / Path(*_TICKET118_MARKER_EXCEPTION_PATH.split("/"))
        source = _REPOSITORY_ROOT / "partner_health_steward" / "host_contract.py"
        self.assertTrue(exception.is_file())
        self.assertIn("TICKET118_", source.read_text(encoding="utf-8"))
        self.assertEqual(self._sha256(exception), self._sha256(source))

        marker_paths: set[str] = set()
        for path in release.rglob("*"):
            if not stat.S_ISREG(path.lstat().st_mode):
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("MISSING-CURRENT", text, path)
            self.assertNotIn("REPLACED-BY-CURRENT", text, path)
            if "TICKET118_" in text:
                marker_paths.add(path.relative_to(release).as_posix())
        self.assertEqual(marker_paths, {_TICKET118_MARKER_EXCEPTION_PATH})

    @staticmethod
    def _recv_exact(client: socket.socket, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = client.recv(remaining)
            if not chunk:
                raise AssertionError("staged runtime truncated a frame")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def test_v120_01_builds_closed_release_plugin_and_staged_runtime(self) -> None:
        publisher_type, _executor_type = self._require_contract(root=True)
        first = self._build_release(publisher_type)
        second = self._build_release(publisher_type)
        first_wire = self._assert_release_closed(first)
        self.assertEqual(first_wire, self._assert_release_closed(second))
        release = self._release_directory(first)
        manifest = (release / "plugin" / "health-weixin" / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("name: health-weixin", manifest)
        self.assertIn("kind: platform", manifest)
        for skill in _SKILLS:
            body = (release / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(skill, body)
            self.assertIn("staged", body)
        self._assert_release_marker_policy(release)
        marker_probe = self.root / "marker-policy-probe"
        shutil.copytree(release, marker_probe)
        extra_marker = marker_probe / "plugin" / "health-weixin" / "__init__.py"
        extra_marker.write_text(
            extra_marker.read_text(encoding="utf-8") + "TICKET118_\n",
            encoding="utf-8",
        )
        with self.assertRaises(AssertionError):
            self._assert_release_marker_policy(marker_probe)
        self._verify_isolated_plugin(release)
        self._verify_staged_runtime(release)

    def test_v120_02_rejects_nondefault_and_unknown_requests_before_factories(self) -> None:
        publisher_type, executor_type = self._require_contract(root=False)
        published = self._build_release(publisher_type)
        self.assertEqual(list(inspect.signature(executor_type).parameters), [])
        invalid_requests: list[dict[str, object]] = []
        for target in (
            {"profile": "partner", "hermes_home": "/root/.hermes/profiles/partner", "service": "hermes-gateway-partner.service"},
            {"profile": "other", "hermes_home": "/root/.hermes/profiles/other", "service": "hermes-gateway.service"},
            {"profile": "default", "hermes_home": "/root/.hermes", "service": "other.service"},
            {"profile": "default", "hermes_home": "/root/.hermes/profiles/partner", "service": "hermes-gateway.service"},
            {"profile": "partner", "hermes_home": "/root/.hermes", "service": "hermes-gateway.service"},
            {"profile": "default", "hermes_home": "/root/.hermes", "service": "hermes-gateway-partner.service"},
        ):
            invalid_requests.append(self._request(published, target=target))
        extra_top = self._request(published)
        extra_top["unexpected"] = "nope"
        invalid_requests.append(extra_top)
        extra_target = self._request(published)
        extra_target["target"]["unexpected"] = "nope"  # type: ignore[index]
        invalid_requests.append(extra_target)
        for request in invalid_requests:
            with self.subTest(request=request):
                with patch("partner_health_steward.release_deployment._default_target_operations", side_effect=AssertionError("invalid request reached target operations")) as target_factory, patch("partner_health_steward.release_deployment._default_service_controller", side_effect=AssertionError("invalid request reached service controller")) as service_factory:
                    wire = self._execute(executor_type(), request)
                self.assertEqual(wire.get("verdict"), "rejected")
                target_factory.assert_not_called()
                service_factory.assert_not_called()

        digest = self._published_wire(published)["release_digest"]
        assert isinstance(digest, str)
        request = self._request(published)
        permit_cases = (
            ("missing", None, "missing"),
            ("owner-mode-or-file", self._permit_for(digest, request["run_id"]), "unsafe-file"),
            ("wrong-release", self._permit_for("sha256:" + "0" * 64, request["run_id"]), "valid"),
            ("wrong-run", self._permit_for(digest, "ticket120-run-other"), "valid"),
            ("wrong-gate", self._permit_for(digest, request["run_id"], gate_id="119-G11"), "valid"),
            ("wrong-target", self._permit_for(digest, request["run_id"], target={"profile": "partner", "hermes_home": "/root/.hermes/profiles/partner", "service": "hermes-gateway-partner.service"}), "valid"),
            ("expired", self._permit_for(digest, request["run_id"], expires_at="2000-01-01T00:00:00+00:00"), "valid"),
            ("revoked", self._permit_for(digest, request["run_id"]), "revoked"),
        )
        for name, permit, permit_state in permit_cases:
            with self.subTest(permit=name):
                target_root = self._prepare_target(f"target-v02-{name}")
                with self._simulated_executor(executor_type, target_root, permit=permit, permit_state=permit_state) as (executor, operations, _target_factory, service_factory):
                    wire = self._execute(executor, request)
                self.assertEqual(wire.get("verdict"), "not-authorized")
                self.assertEqual(operations.events, ["permit-read"])
                service_factory.assert_not_called()
                self.assertFalse((target_root / "plugins" / "health-weixin").exists())
        forged = self._permit_for(digest, request["run_id"])
        forged["digest"] = "sha256:" + "f" * 64
        target_root = self._prepare_target("target-v02-forged-digest")
        with self._simulated_executor(executor_type, target_root, permit=forged) as (executor, operations, _target_factory, service_factory):
            wire = self._execute(executor, self._request(published, approval_ref=forged["digest"]))
        self.assertEqual(wire.get("verdict"), "not-authorized")
        self.assertEqual(operations.events, ["permit-read"])
        service_factory.assert_not_called()

    def test_v120_03_backup_stage_install_and_default_only_restart(self) -> None:
        publisher_type, executor_type = self._require_contract(root=False)
        published = self._build_release(publisher_type)
        release_wire = self._published_wire(published)
        request = self._request(published)
        permit = self._permit_for(release_wire["release_digest"], request["run_id"])
        target_root = self._prepare_target("target-v03")
        with self._simulated_executor(executor_type, target_root, permit=permit) as (executor, operations, _target_factory, _service_factory):
            observation = self._execute(executor, request)
        self.assertEqual(observation.get("verdict"), "staged")
        self.assertEqual(observation.get("plugin_state"), "discovered-staged")
        self.assertEqual(operations.events, ["permit-read", "permit-consumed", "backup", "stage", "install", "restart", "is-active"])
        staged = target_root / "releases" / release_wire["release_digest"].removeprefix("sha256:")
        self.assertTrue((staged / "release-manifest.json").is_file())
        self.assertEqual(self._sha256(staged / "plugin" / "health-weixin" / "__init__.py"), self._sha256(target_root / "plugins" / "health-weixin" / "__init__.py"))
        for source in self._release_directory(published).rglob("*"):
            if source.is_file():
                staged_path = staged / source.relative_to(self._release_directory(published))
                self.assertEqual(self._sha256(staged_path), self._sha256(source))
        for name, mutation in (("stage-tamper", {"tamper_after_stage": True}), ("stage-extra-file", {"extra_after_stage": True})):
            with self.subTest(stage_mutation=name):
                target_root = self._prepare_target(f"target-v03-{name}")
                with self._simulated_executor(executor_type, target_root, permit=permit, **mutation) as (executor, operations, _target_factory, _service_factory):
                    tampered = self._execute(executor, request)
                self.assertEqual(tampered.get("verdict"), "rejected")
                self.assertEqual(operations.events, ["permit-read", "permit-consumed", "backup", "stage"])
                self.assertFalse((target_root / "plugins" / "health-weixin").exists())

    def test_v120_04_restart_failure_restores_default_target_and_rechecks(self) -> None:
        publisher_type, executor_type = self._require_contract(root=False)
        published = self._build_release(publisher_type)
        release_digest = self._published_wire(published)["release_digest"]
        assert isinstance(release_digest, str)
        for name, options in (("restart", {"restart_results": [False, True], "active_results": [True]}), ("partial-install", {"install_fails": True, "restart_results": [True], "active_results": [True]})):
            with self.subTest(name=name):
                request = self._request(published, run_id=f"ticket120-run-v04-{name}")
                permit = self._permit_for(release_digest, request["run_id"])
                target_root = self._prepare_target(f"target-v04-{name}")
                with self._simulated_executor(executor_type, target_root, permit=permit, **options) as (executor, operations, _target_factory, _service_factory):
                    wire = self._execute(executor, request)
                self.assertEqual(wire.get("verdict"), "failed")
                self.assertEqual(wire.get("rollback"), "completed")
                self.assertEqual(operations.events[-3:], ["restore", "restart", "is-active"])
                self.assertFalse((target_root / "plugins" / "health-weixin").exists())
                self.assertFalse((target_root / "ticket120-release-metadata" / "health-weixin.json").exists())
                self.assertEqual((target_root / "plugins" / "legacy" / "marker.txt").read_text(encoding="utf-8"), "before-ticket120\n")

    def test_v120_05_postcheck_failure_rolls_back_or_cannot_confirm(self) -> None:
        publisher_type, executor_type = self._require_contract(root=False)
        published = self._build_release(publisher_type)
        release_digest = self._published_wire(published)["release_digest"]
        assert isinstance(release_digest, str)
        cases = (
            ("recovered", {"restart_results": [True, True], "active_results": [False, True]}, "failed", "completed"),
            ("restore-unconfirmed", {"restart_results": [True], "active_results": [False], "restore_ok": False}, "cannot-confirm", "cannot-confirm"),
            ("rollback-restart-unconfirmed", {"restart_results": [True, False], "active_results": [False]}, "cannot-confirm", "cannot-confirm"),
            ("rollback-active-unconfirmed", {"restart_results": [True, True], "active_results": [False, False]}, "cannot-confirm", "cannot-confirm"),
        )
        for name, options, verdict, rollback in cases:
            with self.subTest(name=name):
                target_root = self._prepare_target(f"target-v05-{name}")
                request = self._request(published, run_id=f"ticket120-run-v05-{name}")
                permit = self._permit_for(release_digest, request["run_id"])
                with self._simulated_executor(executor_type, target_root, permit=permit, **options) as (executor, operations, _target_factory, _service_factory):
                    wire = self._execute(executor, request)
                self.assertEqual(wire.get("verdict"), verdict)
                self.assertEqual(wire.get("rollback"), rollback)
                self.assertIn("restore", operations.events)
                if name != "restore-unconfirmed":
                    self.assertEqual(operations.events[-3:], ["restore", "restart", "is-active"])
                    self.assertFalse((target_root / "plugins" / "health-weixin").exists())

    def test_v120_06_same_digest_is_idempotent_without_second_effect(self) -> None:
        publisher_type, executor_type = self._require_contract(root=False)
        published = self._build_release(publisher_type)
        request = self._request(published, run_id="ticket120-run-v06")
        release_digest = self._published_wire(published)["release_digest"]
        assert isinstance(release_digest, str)
        permit = self._permit_for(release_digest, request["run_id"])
        target_root = self._prepare_target("target-v06")
        with self._simulated_executor(executor_type, target_root, permit=permit) as (executor, operations, _target_factory, _service_factory):
            first = self._execute(executor, request)
            events_after_first = list(operations.events)
            second = self._execute(executor_type(), request)
        self.assertEqual(first.get("verdict"), "staged")
        self.assertEqual(second.get("verdict"), "staged")
        self.assertIs(second.get("idempotent"), True)
        self.assertEqual(operations.events, events_after_first)

        other_request = self._request(published, run_id="ticket120-run-v06-other", approval_ref=permit["digest"])
        with self._simulated_executor(executor_type, self._prepare_target("target-v06-other"), permit=permit) as (executor, operations, _target_factory, _service_factory):
            consumed = self._execute(executor, request)
            reused = self._execute(executor_type(), other_request)
        self.assertEqual(consumed.get("verdict"), "staged")
        self.assertEqual(reused.get("verdict"), "not-authorized")
        self.assertNotIn("backup", operations.events[len(events_after_first):])

    def test_v120_07_rejects_tamper_before_operations_and_keeps_wire_safe(self) -> None:
        if os.environ.get("TICKET120_LINUX_V07") != "1":
            self.skipTest("V120-07 runs only on the isolated Linux symlink verifier")
        if sys.platform != "linux" or not Path("/tmp").is_dir():
            self.fail("V120-07 requires a Linux /tmp isolated directory")
        run_id = os.environ.get("TICKET120_RUN_ID")
        tree = os.environ.get("TICKET120_GIT_TREE")
        tree_object_value = os.environ.get("TICKET120_GIT_TREE_OBJECT")
        verifier_blob = os.environ.get("TICKET120_VERIFIER_BLOB")
        if not all(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) for value in (tree, verifier_blob)) or type(tree_object_value) is not str or type(run_id) is not str or not run_id:
            self.fail("V120-07 evidence binding is unavailable")
        tree_object = Path(tree_object_value).resolve()
        temporary_root = Path.cwd().resolve()
        if tree_object.parent != temporary_root or not tree_object.is_file() or tree_object.is_symlink() or temporary_root.parent != Path("/tmp") or not temporary_root.name.startswith("ticket120-v07-"):
            self.fail("V120-07 tree object is outside its isolated directory")
        tree_bytes = tree_object.read_bytes()
        actual_tree = hashlib.sha1(
            b"tree " + str(len(tree_bytes)).encode("ascii") + b"\0" + tree_bytes
        ).hexdigest()
        self.assertEqual(actual_tree, tree)
        actual_blob = hashlib.sha1(
            b"blob " + str(len(Path(__file__).read_bytes())).encode("ascii") + b"\0" + Path(__file__).read_bytes()
        ).hexdigest()
        self.assertEqual(actual_blob, verifier_blob)
        with tempfile.TemporaryDirectory(prefix="ticket120-v07-", dir="/tmp") as directory:
            isolated = Path(directory).resolve()
            self.assertEqual(isolated.parent, Path("/tmp"))
            regular = isolated / "regular.txt"
            regular.write_text("ticket120-v07\n", encoding="utf-8")
            link = isolated / "link.txt"
            os.symlink("regular.txt", link)
            self.assertTrue(link.is_symlink())
            self.assertTrue(link.is_file())
            fifo = isolated / "probe.fifo"
            os.mkfifo(fifo)
            self.assertTrue(stat.S_ISFIFO(fifo.lstat().st_mode))
        if self._health_package() is None:
            self.skipTest(
                "V120-07 Linux symlink/FIFO mechanical probe verified; "
                "V120-01 prerequisite: HermesReleasePublisher and "
                "DefaultOnlyGateExecutor public Modules are not implemented"
            )
        publisher_type, executor_type = self._require_contract(root=False)
        def recompute_distribution_digest(release: Path) -> None:
            path = release / "release-manifest.json"
            body = json.loads(path.read_text(encoding="utf-8"))
            host = json.loads((release / "host-release-manifest.json").read_text(encoding="utf-8"))
            body["release_digest"] = "sha256:" + hashlib.sha256(
                self._canonical_bytes(
                    {
                        "contract": body["contract"],
                        "state": body["state"],
                        "files": body["files"],
                        "host_release_manifest": host,
                    }
                )
            ).hexdigest()
            path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")

        def tamper_skill(release: Path) -> None:
            skill = release / "skills" / "health-steward" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")

        def add_unlisted(release: Path) -> None:
            (release / "plugin" / "health-weixin" / "unlisted.py").write_text("unexpected\n", encoding="utf-8")

        def add_symlink(release: Path) -> None:
            os.symlink("__init__.py", release / "plugin" / "health-weixin" / "link.py")

        def add_nonregular(release: Path) -> None:
            fifo = release / "plugin" / "health-weixin" / "unlisted.fifo"
            os.mkfifo(fifo)
            self.assertTrue(stat.S_ISFIFO(fifo.lstat().st_mode))

        def tamper_host_manifest(release: Path) -> None:
            path = release / "host-release-manifest.json"
            body = json.loads(path.read_text(encoding="utf-8"))
            body["environment_constraints"]["python"] = ">=0"
            path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
            recompute_distribution_digest(release)

        def unknown_distribution_field(release: Path) -> None:
            path = release / "release-manifest.json"
            body = json.loads(path.read_text(encoding="utf-8"))
            body["unexpected"] = "nope"
            path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")

        def duplicate_distribution_file(release: Path) -> None:
            path = release / "release-manifest.json"
            body = json.loads(path.read_text(encoding="utf-8"))
            body["files"].append(copy.deepcopy(body["files"][0]))
            path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
            recompute_distribution_digest(release)

        expected_release_digest = os.environ.get("TICKET120_RELEASE_DIGEST")
        for name, mutate in (("skill", tamper_skill), ("unlisted", add_unlisted), ("symlink", add_symlink), ("nonregular", add_nonregular), ("host-manifest", tamper_host_manifest), ("distribution-unknown", unknown_distribution_field), ("distribution-duplicate", duplicate_distribution_file)):
            with self.subTest(tamper=name):
                published = self._build_release(publisher_type)
                if expected_release_digest is None:
                    self.fail("V120-07 release digest binding is unavailable")
                self.assertEqual(self._published_wire(published)["release_digest"], expected_release_digest)
                mutate(self._release_directory(published))
                with patch("partner_health_steward.release_deployment._default_target_operations", side_effect=AssertionError("tampered release reached target operations")) as target_factory, patch("partner_health_steward.release_deployment._default_service_controller", side_effect=AssertionError("tampered release reached service controller")) as service_factory:
                    wire = self._execute(executor_type(), self._request(published))
                self.assertEqual(wire.get("verdict"), "rejected")
                target_factory.assert_not_called()
                service_factory.assert_not_called()
        published = self._build_release(publisher_type)
        invalid_path = self._request(published)
        invalid_path["release_directory"] = "../outside"
        with patch("partner_health_steward.release_deployment._default_target_operations", side_effect=AssertionError("invalid path reached target operations")) as target_factory, patch("partner_health_steward.release_deployment._default_service_controller", side_effect=AssertionError("invalid path reached service controller")) as service_factory:
            wire = self._execute(executor_type(), invalid_path)
        self.assertEqual(wire.get("verdict"), "rejected")
        target_factory.assert_not_called()
        service_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()

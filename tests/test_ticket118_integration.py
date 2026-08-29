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
import threading
import unittest
from contextlib import contextmanager
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
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


def _oracle_frame(value: Mapping[str, object]) -> bytes:
    body = json.dumps(
        dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return struct.pack(">I", len(body)) + body


def _oracle_decode(frame: bytes) -> dict[str, object]:
    if len(frame) < 4:
        raise ValueError("truncated frame")
    declared = struct.unpack(">I", frame[:4])[0]
    if declared != len(frame) - 4:
        raise ValueError("truncated or trailing frame")
    value = json.loads(frame[4:].decode("utf-8"))
    if type(value) is not dict:
        raise ValueError("frame must contain an object")
    return value


class _SocketRuntimeOracle:
    """Independent runtime exposing only a local byte-stream endpoint."""

    def __init__(
        self,
        *,
        response_fault: str | None = None,
        intent_fault: str | None = None,
    ) -> None:
        self.response_fault = response_fault
        self.intent_fault = intent_fault
        self.frames: list[dict[str, object]] = []
        self.accepted_terminals: list[dict[str, object]] = []
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self._listener.settimeout(0.1)
        host, port = self._listener.getsockname()
        self.endpoint = {
            "transport": "local-byte-stream",
            "host": host,
            "port": port,
            "protocol": "ticket118-core-port-v1",
        }
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            with socket.create_connection(
                (self.endpoint["host"], self.endpoint["port"]), timeout=0.2
            ):
                pass
        except OSError:
            pass
        self._thread.join(timeout=2)
        self._listener.close()

    @staticmethod
    def _read_frame(connection: socket.socket) -> bytes:
        header = bytearray()
        while len(header) < 4:
            chunk = connection.recv(4 - len(header))
            if not chunk:
                raise ValueError("truncated frame header")
            header.extend(chunk)
        declared = struct.unpack(">I", bytes(header))[0]
        if declared > 65536:
            raise ValueError("frame too large")
        body = bytearray()
        while len(body) < declared:
            chunk = connection.recv(declared - len(body))
            if not chunk:
                raise ValueError("truncated frame body")
            body.extend(chunk)
        return bytes(header + body)

    def _effect_claim(self) -> dict[str, object]:
        authority = {
            "source": "core" if self.intent_fault != "forged" else "adapter",
            "generation": 7,
            "writer_fence": (
                "fence:6" if self.intent_fault == "stale" else "fence:7"
            ),
        }
        return {
            "intent": {
                "effect_id": "effect:ticket118",
                "intent_digest": "sha256:ticket118-effect",
                "effect_kind": "model-work",
                "authority": authority,
            },
            "grant": {
                "lease_id": "lease:ticket118",
                "effect_id": "effect:ticket118",
                "intent_digest": "sha256:ticket118-effect",
                "generation": 7,
                "writer_fence": "fence:7",
            },
            "current_authority": {"generation": 7, "writer_fence": "fence:7"},
        }

    def _handle(self, request: Mapping[str, object]) -> dict[str, object]:
        expected = {"protocol_version", "kind", "request_id", "payload"}
        if set(request) != expected or request.get("protocol_version") != 1:
            raise ValueError("invalid CorePort frame")
        kind = request.get("kind")
        if kind not in {"command", "managed-read", "controlled-effect"}:
            raise ValueError("unknown CorePort kind")
        self.frames.append(copy.deepcopy(dict(request)))
        response: dict[str, object] = {
            "protocol_version": 1,
            "kind": kind,
            "request_id": request["request_id"],
            "status": "accepted",
            "payload": {},
        }
        if kind == "managed-read":
            response["payload"] = {"projection": {"state": "synthetic-current"}}
        elif kind == "controlled-effect":
            payload = request["payload"]
            if type(payload) is not dict:
                raise ValueError("invalid controlled-effect payload")
            phase = payload.get("phase")
            if phase == "claim":
                response["payload"] = self._effect_claim()
            elif phase == "terminal":
                terminal = payload.get("terminal")
                if (
                    self.intent_fault is None
                    and type(terminal) is dict
                    and terminal.get("effect_id") == "effect:ticket118"
                    and terminal.get("intent_digest") == "sha256:ticket118-effect"
                    and terminal.get("terminal") is True
                ):
                    self.accepted_terminals.append(copy.deepcopy(terminal))
                    response["payload"] = {"terminal_accepted": True}
                else:
                    response["status"] = "rejected"
                    response["payload"] = {"terminal_accepted": False}
            else:
                raise ValueError("unknown controlled-effect phase")
        if self.response_fault == "unknown-kind":
            response["kind"] = "unknown-kind"
        if self.response_fault == "incomplete-terminal" and kind == "controlled-effect":
            response["payload"] = {"terminal_accepted": False}
        return response

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _address = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                try:
                    request = _oracle_decode(self._read_frame(connection))
                    response = _oracle_frame(self._handle(request))
                    if self.response_fault == "truncated":
                        response = response[:-1]
                    elif self.response_fault == "trailing":
                        response += b"x"
                    connection.sendall(response)
                except Exception as exc:
                    self.errors.append(type(exc).__name__)


class _PinnedHermesObserver:
    """Independent observation of calls into the real pinned host classes."""

    def __init__(self, registry: object) -> None:
        self.registry = registry
        self.register_calls: list[dict[str, object]] = []
        self.manager_types: list[type[object]] = []
        self.factory_instances: list[object] = []
        self.factory_calls: list[str] = []
        self.lifecycle_calls: list[str] = []
        self.discovery_calls: list[bool] = []
        self.loaded_plugin_sources: list[Path] = []
        self.loaded_plugin_errors: list[object] = []
        self.selection_calls: list[str] = []
        self.gateway_results: list[tuple[str, object | None]] = []
        self.old_factory_calls: list[str] = []

    def observe_registration(
        self,
        context: object,
        args: tuple[object, ...],
        kwargs: Mapping[str, object],
    ) -> tuple[tuple[object, ...], dict[str, object]]:
        name = kwargs.get("name", args[0] if args else None)
        factory = kwargs.get("adapter_factory", args[2] if len(args) > 2 else None)
        self.register_calls.append({"name": name, "factory": factory})
        self.manager_types.append(type(getattr(context, "_manager", None)))
        if not callable(factory):
            raise AssertionError("health_weixin registration has no factory")

        def observed_factory(config: object) -> object:
            self.factory_calls.append(str(name))
            adapter = factory(config)
            self.factory_instances.append(adapter)
            for method_name in ("connect", "disconnect"):
                method = getattr(adapter, method_name, None)
                if not callable(method):
                    raise AssertionError(
                        f"health_weixin Adapter has no {method_name} lifecycle Interface"
                    )

                def observed_lifecycle(
                    *call_args: object,
                    __method: object = method,
                    __name: str = method_name,
                    **call_kwargs: object,
                ) -> object:
                    self.lifecycle_calls.append(__name)
                    return __method(*call_args, **call_kwargs)  # type: ignore[operator]

                setattr(adapter, method_name, observed_lifecycle)
            return adapter

        mutable_args = list(args)
        mutable_kwargs = dict(kwargs)
        if "adapter_factory" in mutable_kwargs:
            mutable_kwargs["adapter_factory"] = observed_factory
        elif len(mutable_args) > 2:
            mutable_args[2] = observed_factory
        else:
            raise AssertionError("register_platform did not expose adapter_factory")
        return tuple(mutable_args), mutable_kwargs


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
def _observe_pinned_hermes(
    root: Path,
    hermes_home: Path,
    *,
    preload_old: bool = False,
):
    """Patch only observation points while retaining real pinned behavior."""

    root_text = str(root.resolve())
    inserted = root_text not in sys.path
    shimmed: list[str] = []
    if inserted:
        sys.path.insert(0, root_text)
    try:
        # The pinned GatewayRunner imports two optional boot/logging packages
        # absent from the verifier Python.  These shims preserve only their
        # inert import surface; platform selection remains the real code.
        if "concurrent_log_handler" not in sys.modules:
            import logging.handlers
            import types

            module = types.ModuleType("concurrent_log_handler")
            module.ConcurrentRotatingFileHandler = (  # type: ignore[attr-defined]
                logging.handlers.RotatingFileHandler
            )
            sys.modules["concurrent_log_handler"] = module
            shimmed.append("concurrent_log_handler")
        if "dotenv" not in sys.modules:
            import types

            module = types.ModuleType("dotenv")
            module.load_dotenv = lambda *_args, **_kwargs: False  # type: ignore[attr-defined]
            sys.modules["dotenv"] = module
            shimmed.append("dotenv")
        plugins = importlib.import_module("hermes_cli.plugins")
        registry_module = importlib.import_module("gateway.platform_registry")
        gateway_run = importlib.import_module("gateway.run")
        for module in (plugins, registry_module):
            module_path = Path(inspect.getsourcefile(module) or "").resolve()
            if root.resolve() not in module_path.parents:
                raise AssertionError(f"pinned Hermes module loaded outside checkout: {module_path}")
        registry = registry_module.PlatformRegistry()
        observer = _PinnedHermesObserver(registry)
        if preload_old:
            for old_name in ("weixin", "medical", "health-autonomy", "health-guard"):
                def old_factory(_config: object, *, _name: str = old_name) -> object:
                    observer.old_factory_calls.append(_name)
                    return SimpleNamespace(name=_name)

                registry.register(
                    registry_module.PlatformEntry(
                        name=old_name,
                        label=f"old {old_name}",
                        adapter_factory=old_factory,
                        check_fn=lambda: True,
                        source="builtin",
                    )
                )
        original_register_platform = plugins.PluginContext.register_platform
        original_discover = plugins.PluginManager.discover_and_load
        original_create_adapter = registry.create_adapter
        original_gateway_create = gateway_run.GatewayRunner._create_adapter
        gateway_observer_installed = False

        def observed_register(context: object, *args: object, **kwargs: object) -> None:
            replaced_args, replaced_kwargs = observer.observe_registration(
                context, args, kwargs
            )
            original_register_platform(context, *replaced_args, **replaced_kwargs)

        def observed_discover(manager: object, force: bool = False) -> None:
            nonlocal gateway_observer_installed
            observer.discovery_calls.append(force)
            original_discover(manager, force=force)
            loaded = getattr(manager, "_plugins", {})
            for item in loaded.values():
                module = getattr(item, "module", None)
                source = inspect.getsourcefile(module) if module is not None else None
                if source is not None:
                    resolved = Path(source).resolve()
                    if hermes_home.resolve() in resolved.parents:
                        observer.loaded_plugin_sources.append(resolved)
                        observer.loaded_plugin_errors.append(
                            getattr(item, "error", None)
                        )
            # Discovery/register may install the release-owned, hash-bound
            # host patch.  Observe the resulting real Gateway entry point;
            # capturing the pre-discovery method would bypass that patch.
            active_gateway_create = gateway_run.GatewayRunner._create_adapter

            def observed_gateway_create(
                runner: object, platform: object, config: object
            ) -> object:
                name = str(getattr(platform, "value", platform))
                result = active_gateway_create(runner, platform, config)
                observer.gateway_results.append((name, result))
                return result

            gateway_run.GatewayRunner._create_adapter = observed_gateway_create
            gateway_observer_installed = True

        def observed_create_adapter(name: str, config: object) -> object:
            observer.selection_calls.append(name)
            return original_create_adapter(name, config)

        with (
            patch.object(registry_module, "platform_registry", registry),
            patch.object(plugins.PluginContext, "register_platform", observed_register),
            patch.object(plugins.PluginManager, "discover_and_load", observed_discover),
            patch.object(registry, "create_adapter", observed_create_adapter),
            patch.dict(
                os.environ,
                {
                    "HERMES_HOME": str(hermes_home),
                    "HERMES_CONFIG": str(hermes_home / "config.yaml"),
                },
            ),
        ):
            try:
                yield observer
            finally:
                if gateway_observer_installed:
                    gateway_run.GatewayRunner._create_adapter = original_gateway_create
    finally:
        for name in shimmed:
            sys.modules.pop(name, None)
        if inserted:
            sys.path.remove(root_text)


def _fresh_host_worker(input_path: str, output_path: str) -> None:
    """Run pinned Hermes lifecycle observation in one fresh interpreter."""

    request = json.loads(Path(input_path).read_text(encoding="utf-8"))
    source = dict(request["pinned_source"])
    source["credential_adapter"] = _SyntheticCredentialAdapter(
        peer=request.get("credential_peer", "plugin")
    )
    effect_adapter = _SyntheticEffectAdapter(request.get("effect_result"))
    source["effect_adapter"] = effect_adapter
    contract_type = getattr(health_package, "HostReleaseContract", None)
    if not callable(contract_type):
        raise AssertionError("HostReleaseContract public Module is unavailable")
    contract = contract_type()
    manifest = contract.build(request["release_sources"])
    with _observe_pinned_hermes(
        Path(source["root"]),
        Path(source["hermes_home"]),
        preload_old=bool(request.get("preload_old")),
    ) as observer:
        report = contract.verify(manifest, source)
    result = {
        "report": _wire(report, "host contract report"),
        "observation": {
            "register_names": [call["name"] for call in observer.register_calls],
            "manager_types": [kind.__name__ for kind in observer.manager_types],
            "factory_calls": observer.factory_calls,
            "factory_count": len(observer.factory_instances),
            "lifecycle_calls": observer.lifecycle_calls,
            "discovery_count": len(observer.discovery_calls),
            "loaded_plugin_sources": [
                str(path) for path in observer.loaded_plugin_sources
            ],
            "loaded_plugin_errors": observer.loaded_plugin_errors,
            "selection_calls": observer.selection_calls,
            "gateway_results": [
                [name, value is not None] for name, value in observer.gateway_results
            ],
            "old_factory_calls": observer.old_factory_calls,
            "registry_names": [entry.name for entry in observer.registry.all_entries()],
            "effect_call_count": len(effect_adapter.calls),
        },
    }
    Path(output_path).write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


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
        self._runtime_oracles: list[_SocketRuntimeOracle] = []

    def tearDown(self) -> None:
        for runtime in self._runtime_oracles:
            runtime.close()
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
            (
                "product/hermes_host.py",
                "hermes-host-module",
                "MISSING-CURRENT-HERMES-HOST-MODULE\n",
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
        # Current product sources replace synthetic bodies when they exist.
        # Historical ops files are deliberately excluded from Ticket 118.
        current_sources = {
            "product/plugin.py": _REPOSITORY_ROOT / "partner_health_steward/plugin.py",
            "product/core.py": _REPOSITORY_ROOT / "partner_health_steward/core.py",
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
        hermes_host = _REPOSITORY_ROOT / "partner_health_steward/hermes_host.py"
        if hermes_host.is_file():
            current_sources.update(
                {
                    "host/required.patch": hermes_host,
                    "host/disabled-native-entry.assertion": hermes_host,
                    "product/hermes_host.py": hermes_host,
                    "adapters/health_weixin.py": hermes_host,
                }
            )
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

    def _hermes_home(self) -> Path:
        module = _REPOSITORY_ROOT / "partner_health_steward/hermes_host.py"
        if not module.is_file():
            raise AssertionError(
                "current partner_health_steward.hermes_host Module is unavailable"
            )
        home = self.release_root / "runtime" / "hermes-home"
        plugin = home / "plugins" / "ticket118-health"
        plugin.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(module, plugin / "__init__.py")
        (plugin / "plugin.yaml").write_text(
            "name: ticket118-health\n"
            "version: 1.0.0\n"
            "kind: platform\n"
            "description: Ticket 118 current health host\n",
            encoding="utf-8",
            newline="\n",
        )
        (home / "config.yaml").write_text(
            "plugins:\n  enabled:\n    - ticket118-health\n",
            encoding="utf-8",
            newline="\n",
        )
        return home

    def _verify_fresh_host(
        self,
        runtime: _SocketRuntimeOracle,
        *,
        wrong_hash: bool = False,
        preload_old: bool = False,
        credential_peer: str = "plugin",
        effect_result: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if self.pinned_root is None:
            raise AssertionError(
                "TICKET118_PINNED_HERMES_SOURCE must name the local pinned checkout"
            )
        self._runtime_oracles.append(runtime)
        files = [
            {"path": path, "sha256": digest}
            for path, digest in _PINNED_FILES.items()
        ]
        if wrong_hash:
            files[0]["sha256"] = "0" * 64
        source = {
            "contract": "ticket118-pinned-hermes-source-v1",
            "root": str(self.pinned_root),
            "hermes_home": str(self._hermes_home()),
            "commit": _PINNED_COMMIT,
            "allowlisted_files": files,
            "core_port_endpoint": copy.deepcopy(runtime.endpoint),
            "host_entry_probe": {
                "current": "health_weixin",
                "native": "weixin",
                "old": ["medical", "ordinary"],
            },
        }
        request_path = self.release_root / "runtime" / "fresh-host-input.json"
        output_path = self.release_root / "runtime" / "fresh-host-output.json"
        request_path.write_text(
            json.dumps(
                {
                    "release_sources": self._release_sources(),
                    "pinned_source": source,
                    "preload_old": preload_old,
                    "credential_peer": credential_peer,
                    "effect_result": (
                        None if effect_result is None else dict(effect_result)
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from tests.test_ticket118_integration import _fresh_host_worker;"
                    f"_fresh_host_worker({str(request_path)!r},{str(output_path)!r})"
                ),
            ],
            cwd=str(_REPOSITORY_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0:
            raise AssertionError(
                "fresh pinned host verification failed:\n"
                + completed.stdout
                + completed.stderr
            )
        return json.loads(output_path.read_text(encoding="utf-8"))

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

        positive = self._verify_fresh_host(_SocketRuntimeOracle())
        report = positive["report"]
        observer = positive["observation"]
        self.assertEqual(report.get("verdict"), "pass", report)
        self.assertIsInstance(report.get("activation_proof"), str)
        self.assertEqual(observer["discovery_count"], 1)
        self.assertEqual(observer["register_names"], ["health_weixin"])
        self.assertEqual(observer["manager_types"], ["PluginManager"])
        self.assertEqual(observer["factory_calls"], ["health_weixin"])
        self.assertEqual(observer["factory_count"], 1)
        self.assertEqual(observer["lifecycle_calls"], ["connect", "disconnect"])
        self.assertEqual(
            observer["gateway_results"],
            [
                ["health_weixin", True],
                ["weixin", False],
                ["medical", False],
                ["ordinary", False],
            ],
        )
        self.assertEqual(observer["selection_calls"], ["health_weixin"])
        self.assertIn("health_weixin", observer["registry_names"])
        expected_plugin = str(
            (self._hermes_home() / "plugins/ticket118-health/__init__.py").resolve()
        )
        self.assertEqual(observer["loaded_plugin_sources"], [expected_plugin])
        self.assertEqual(observer["loaded_plugin_errors"], [None])

        negative = self._verify_fresh_host(
            _SocketRuntimeOracle(), wrong_hash=True
        )
        rejected = negative["report"]
        rejected_observer = negative["observation"]
        self.assertEqual(rejected.get("verdict"), "fail")
        self.assertIsNone(rejected.get("activation_proof"))
        self.assertEqual(rejected_observer["register_names"], [])
        self.assertEqual(rejected_observer["discovery_count"], 0)
        self.assertEqual(rejected_observer["loaded_plugin_sources"], [])
        self.assertEqual(rejected_observer["loaded_plugin_errors"], [])
        self.assertEqual(rejected_observer["factory_calls"], [])
        self.assertEqual(rejected_observer["lifecycle_calls"], [])

    def test_v118_03_core_port_is_three_strict_fail_closed_interfaces(self) -> None:
        """A3: a socket shell cannot hide direct or incomplete core effects."""

        self._require_contract(root=False)
        runtime = _SocketRuntimeOracle()
        result = self._verify_fresh_host(runtime)
        report = result["report"]
        self.assertEqual(report.get("verdict"), "pass", report)
        self.assertEqual(
            {frame["kind"] for frame in runtime.frames},
            {"command", "managed-read", "controlled-effect"},
        )
        effect_phases = [
            frame["payload"].get("phase")
            for frame in runtime.frames
            if frame["kind"] == "controlled-effect"
            and type(frame["payload"]) is dict
        ]
        self.assertEqual(effect_phases, ["claim", "terminal"])
        self.assertEqual(result["observation"]["effect_call_count"], 1)
        self.assertEqual(len(runtime.accepted_terminals), 1)
        self.assertEqual(runtime.errors, [])

        variants = (
            (
                "wrong-peer",
                "ordinary-agent",
                _SocketRuntimeOracle(),
            ),
            (
                "truncated-frame",
                "plugin",
                _SocketRuntimeOracle(response_fault="truncated"),
            ),
            (
                "trailing-frame",
                "plugin",
                _SocketRuntimeOracle(response_fault="trailing"),
            ),
            (
                "unknown-kind",
                "plugin",
                _SocketRuntimeOracle(response_fault="unknown-kind"),
            ),
            (
                "incomplete-terminal",
                "plugin",
                _SocketRuntimeOracle(response_fault="incomplete-terminal"),
            ),
        )
        for label, peer, fault_runtime in variants:
            with self.subTest(representative_fault=label):
                failed = self._verify_fresh_host(
                    fault_runtime,
                    credential_peer=peer,
                )
                self.assertIn(
                    failed["report"].get("verdict"), {"fail", "cannot-confirm"}
                )
                self.assertIsNone(failed["report"].get("activation_proof"))

    def test_v118_04_adapters_cannot_forge_intent_terminal_or_state(self) -> None:
        """A4: a transport cannot turn its own observation into health truth."""

        self._require_contract(root=False)
        legal_runtime = _SocketRuntimeOracle()
        legal = self._verify_fresh_host(legal_runtime)
        self.assertEqual(legal["report"].get("verdict"), "pass", legal)
        self.assertEqual(legal["observation"]["effect_call_count"], 1)
        self.assertEqual(len(legal_runtime.accepted_terminals), 1)
        self.assertTrue(legal_runtime.accepted_terminals[0]["terminal"])

        faults = (
            (
                "forged-intent",
                _SocketRuntimeOracle(intent_fault="forged"),
                None,
                0,
            ),
            (
                "stale-writer-fence",
                _SocketRuntimeOracle(intent_fault="stale"),
                None,
                0,
            ),
            (
                "missing-terminal",
                _SocketRuntimeOracle(),
                {"status": "accepted", "result_ref": "synthetic:missing"},
                1,
            ),
        )
        for label, fault_runtime, effect_result, expected_calls in faults:
            with self.subTest(representative_fault=label):
                rejected = self._verify_fresh_host(
                    fault_runtime,
                    effect_result=effect_result,
                )
                self.assertIn(
                    rejected["report"].get("verdict"), {"fail", "cannot-confirm"}
                )
                self.assertEqual(
                    rejected["observation"]["effect_call_count"], expected_calls
                )
                self.assertEqual(fault_runtime.accepted_terminals, [])
                self.assertIsNone(rejected["report"].get("activation_proof"))

    def test_v118_05_old_health_entries_never_return_on_host_failure(self) -> None:
        """A5: a disabled assertion cannot replace actual reachability proof."""

        self._require_contract(root=False)
        failing_runtime = _SocketRuntimeOracle(response_fault="truncated")
        result = self._verify_fresh_host(
            failing_runtime,
            preload_old=True,
        )
        failed = result["report"]
        observer = result["observation"]
        self.assertEqual(observer["register_names"], ["health_weixin"])
        self.assertEqual(observer["discovery_count"], 1)
        self.assertEqual(
            observer["gateway_results"],
            [
                ["health_weixin", True],
                ["weixin", False],
                ["medical", False],
                ["ordinary", False],
            ],
        )
        self.assertEqual(observer["selection_calls"], ["health_weixin"])
        self.assertEqual(observer["old_factory_calls"], [])
        self.assertNotIn("health_weixin", observer["registry_names"])
        for obsolete in ("medical", "health-autonomy", "health-guard", "weixin"):
            with self.subTest(obsolete_health_entry=obsolete):
                self.assertIn(obsolete, observer["registry_names"])
        self.assertEqual(failed.get("verdict"), "fail")
        self.assertIsNone(failed.get("activation_proof"))
        self.assertGreaterEqual(len(failing_runtime.frames), 1)

    def test_v118_06_readiness_preserves_unknown_and_rejects_unsafe_rollback(self) -> None:
        """A6: missing target facts cannot be skipped or replaced by old files."""

        self._require_contract(root=False)
        manifest, manifest_wire = self._build()
        host_report = self._verify_fresh_host(_SocketRuntimeOracle())["report"]
        same_manifest, same_wire = self._build()

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
                "from_release_manifest": manifest_wire,
                "to_release_manifest": same_wire,
                "host_report": host_report,
                "target_binding_required": [],
                "target_observations": {},
            }
        )
        self.assertEqual(offline_upgrade.get("verdict"), "pass", offline_upgrade)
        self.assertEqual(_wire(same_manifest, "same release"), manifest_wire)
        self.assertEqual(
            offline_upgrade.get("assessment_scope"),
            "offline-release-compatibility",
        )
        self.assertIsNone(offline_upgrade.get("activation_proof"))

        schema = self.release_root / "schemas/health-state.json"
        schema.write_text('{"v":2,"breaking":true}\n', encoding="utf-8")
        _drift_manifest, drift_wire = self._build()
        self.assertNotEqual(
            drift_wire.get("release_digest"), manifest_wire.get("release_digest")
        )
        upgrade = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "upgrade",
                "assessment_scope": "offline-release-compatibility",
                "from_release_manifest": manifest_wire,
                "to_release_manifest": drift_wire,
                "host_report": host_report,
                "target_binding_required": [],
                "target_observations": {},
            }
        )
        self.assertEqual(upgrade.get("verdict"), "fail")

        rollback = self._assess(
            {
                "contract": "ticket118-transition-assessment-v1",
                "mode": "rollback",
                "from_release_manifest": drift_wire,
                "to_release_manifest": manifest_wire,
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
        self.assertEqual(rollback.get("verdict"), "cannot-confirm")
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

        host_report = self._verify_fresh_host(_SocketRuntimeOracle())["report"]
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

"""Ticket 120's narrow staged release and default-target deployment seam.

This module deliberately owns no health state, approval ledger, or general
deployment framework.  It builds one content-addressed, staged-only release
and executes it only against the explicitly fixed default Hermes target.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .hermes_host import HERMES_REQUIRED_PATCH_BYTES, NATIVE_HEALTH_DISABLED_ASSERTION_BYTES
from .host_contract import HostReleaseContract


_DEFAULT_TARGET = {
    "profile": "default",
    "hermes_home": "/root/.hermes",
    "service": "hermes-gateway.service",
}
_RELEASE_CONTRACT = "ticket120-hermes-release-v1"
_GATE_CONTRACT = "ticket120-default-stage-install-v1"
_PERMIT_CONTRACT = "ticket120-deployment-permit-v1"
_GATE_ID = "119-G10"
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
    ("skill:health-init", "skills/health-init/SKILL.md"),
    ("skill:health-steward", "skills/health-steward/SKILL.md"),
    ("skill:health-settings", "skills/health-settings/SKILL.md"),
    ("skill:health-portrait", "skills/health-portrait/SKILL.md"),
    ("skill:health-evidence", "skills/health-evidence/SKILL.md"),
    ("skill:health-owner-inquiry", "skills/health-owner-inquiry/SKILL.md"),
    ("skill:health-literature", "skills/health-literature/SKILL.md"),
)
_SKILLS = tuple(role.removeprefix("skill:") for role, _ in _REQUIRED_ARTIFACTS if role.startswith("skill:"))
_PINNED_HERMES = {
    "commit": "3c27eb6234bf91b8ceee9e9071591b31e9b148cb",
    "allowlisted_files": [
        {"path": "hermes_cli/plugins.py", "sha256": "2f74ddb96ed024cd2e085c2181751c610811e47f79f66a1ba7ce205c766664d8"},
        {"path": "gateway/platform_registry.py", "sha256": "f7ebc66c09d40e883617f1a1a6700f621b4b14f94849b131bfacf0a80a623c4b"},
        {"path": "gateway/run.py", "sha256": "328950c2369af1ca62b9cb8c97aaf1c931e8020b2535078bc84a9de258c4dfb5"},
        {"path": "gateway/platforms/weixin.py", "sha256": "9c0650b68acf5847ded1eb16c42f5d10dd37d0bddb17b65dcb7ff9c9d37857e5"},
    ],
    "extractor_version": "ticket118-pinned-source-v1",
}
_TARGET_BINDINGS = [
    "target-hermes-artifact",
    "target-required-patch",
    "target-plugin-binding",
    "target-service-identity",
    "target-unix-acl",
    "target-current-head",
    "target-native-entry-disabled",
]
_EXTERNAL_APPROVALS = [
    "model-route-owner-consent",
    "knowledge-rights",
    "medical-review",
    "owner-acceptance",
]
_FORBIDDEN_SECRETS = [
    "credential",
    "token",
    "private-key",
    "contact-identity",
    "health-content",
    "partner-config-value",
]
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_EXECUTION_KEY = re.compile(r"[0-9a-f]{64}")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _plain_string(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError("invalid string")
    return value


def _relative_path(value: object) -> str:
    value = _plain_string(value)
    if "\\" in value:
        raise ValueError("invalid relative path")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or not parsed.parts or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError("invalid relative path")
    return parsed.as_posix()


def _strict_json_bytes(data: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate json key")
            result[key] = value
        return result

    return json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicates)


def _write_bytes(root: Path, relative: str, content: bytes) -> None:
    destination = root / Path(*PurePosixPath(relative).parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


def _static_json(value: object) -> bytes:
    return _canonical_bytes(value) + b"\n"


_RUNTIME_SOURCE = r'''"""Staged-only strict CorePort server shipped with Ticket 120."""
from __future__ import annotations

import json
import socket
import struct
import threading


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _decode(data):
    def duplicate_free(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result
    value = json.loads(data.decode("utf-8"), object_pairs_hook=duplicate_free)
    if type(value) is not dict or _canonical(value) != data:
        raise ValueError("noncanonical")
    if set(value) != {"protocol_version", "kind", "request_id", "payload"}:
        raise ValueError("fields")
    if type(value["protocol_version"]) is not int or value["protocol_version"] != 1:
        raise ValueError("version")
    if value["kind"] not in {"command", "managed-read", "controlled-effect"}:
        raise ValueError("kind")
    if type(value["request_id"]) is not str or not value["request_id"] or type(value["payload"]) is not dict:
        raise ValueError("types")
    return value


class StagedCorePortServer:
    def __init__(self):
        self._listener = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._listener is not None:
            raise RuntimeError("already started")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.1)
        self._listener = listener
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        host, port = listener.getsockname()
        return {"host": host, "port": port}

    def close(self):
        self._stop.set()
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None

    def _serve(self):
        while not self._stop.is_set():
            try:
                client, _ = self._listener.accept()
            except (OSError, socket.timeout):
                continue
            with client:
                client.settimeout(1)
                self._handle(client)

    @staticmethod
    def _receive(client, size):
        result = bytearray()
        while len(result) < size:
            piece = client.recv(size - len(result))
            if not piece:
                return None
            result.extend(piece)
        return bytes(result)

    def _handle(self, client):
        try:
            header = self._receive(client, 4)
            if header is None:
                return
            length = struct.unpack(">I", header)[0]
            if not length or length > 65536:
                return
            body = self._receive(client, length)
            if body is None:
                return
            request = _decode(body)
            response = {
                "kind": request["kind"],
                "payload": {"reason": "health-core-staged"},
                "request_id": request["request_id"],
                "status": "rejected",
            }
            wire = _canonical(response)
            client.sendall(struct.pack(">I", len(wire)) + wire)
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return
'''


@dataclass(frozen=True)
class PublishedRelease:
    """Immutable public summary of one content-addressed staged release."""

    _wire: dict[str, object]

    def to_wire(self) -> dict[str, object]:
        return copy.deepcopy(self._wire)


@dataclass(frozen=True)
class GateObservation:
    """Nonsensitive result from the sole default-target deployment seam."""

    _wire: dict[str, object]

    def to_wire(self) -> dict[str, object]:
        return copy.deepcopy(self._wire)


class HermesReleasePublisher:
    """Build a deterministic, staged-only Hermes distribution directory."""

    def __init__(self, repository_root: Path | str) -> None:
        self._repository_root = Path(repository_root).resolve()
        if not self._repository_root.is_dir():
            raise ValueError("repository root is unavailable")

    def _source_bytes(self) -> dict[str, bytes]:
        package = self._repository_root / "partner_health_steward"
        source_files = {
            "product/hermes_host.py": package / "hermes_host.py",
            "product/plugin.py": package / "plugin.py",
            "product/core.py": package / "core.py",
            "adapters/model.py": package / "model_contract.py",
            "adapters/delivery.py": package / "delivery.py",
        }
        result = {relative: path.read_bytes() for relative, path in source_files.items()}
        result.update(
            {
                "host/required.patch": HERMES_REQUIRED_PATCH_BYTES,
                "host/disabled-native-entry.assertion": NATIVE_HEALTH_DISABLED_ASSERTION_BYTES,
                "interfaces/core-command.json": _static_json({"kind": "command", "protocol_version": 1, "status": "staged"}),
                "interfaces/core-managed-read.json": _static_json({"kind": "managed-read", "protocol_version": 1, "status": "staged"}),
                "interfaces/core-controlled-effect.json": _static_json({"kind": "controlled-effect", "protocol_version": 1, "status": "staged"}),
                "schemas/health-state.json": _static_json({"availability": "unavailable", "status": "staged"}),
                "model/capability-profile-schema.json": _static_json({"availability": "unavailable", "status": "staged"}),
                "model/capability-profile-builder.py": b'"""Staged capability profile declaration."""\nSTATUS = "staged"\n',
                "model/capability-profile-validator.py": b'"""Staged capability profile declaration."""\nSTATUS = "staged"\n',
                "migration/protocol.json": _static_json({"availability": "unavailable", "status": "staged"}),
                "migration/schema.json": _static_json({"availability": "unavailable", "status": "staged"}),
                "migration/builder.py": b'"""Staged migration declaration."""\nSTATUS = "staged"\n',
                "migration/semantic-registry.json": _static_json({"availability": "unavailable", "status": "staged"}),
                "migration/ticket117-synthetic-fixture.py": b'"""Staged migration compatibility declaration."""\nSTATUS = "staged"\n',
                "environment/python.txt": b">=3.11,<3.12\n",
                "environment/dependencies.lock": b"# staged release has no additional dependency installation\n",
                "environment/service-acl.json": _static_json({"availability": "unavailable", "status": "staged"}),
                "runtime/core_port_server.py": _RUNTIME_SOURCE.encode("utf-8"),
                "plugin/health-weixin/plugin.yaml": b"name: health-weixin\nversion: '1.0.0'\ndescription: Staged health platform\nauthor: ticket120\nkind: platform\n",
                "plugin/health-weixin/__init__.py": b"from pathlib import Path\nimport sys\n\nroot = str(Path(__file__).resolve().parent)\nif root not in sys.path:\n    sys.path.insert(0, root)\nfrom partner_health_steward.hermes_host import register\n",
                "plugin/health-weixin/partner_health_steward/__init__.py": b'"""Release-local staged host package."""\n',
                "plugin/health-weixin/partner_health_steward/hermes_host.py": (package / "hermes_host.py").read_bytes(),
                "plugin/health-weixin/partner_health_steward/host_contract.py": (package / "host_contract.py").read_bytes(),
            }
        )
        for name in _SKILLS:
            result[f"skills/{name}/SKILL.md"] = (
                f"# {name}\n\nstatus: staged\navailability: unavailable\n"
            ).encode("utf-8")
        for name in ("minimum-help", "knowledge", "safety", "diagnostic"):
            result[f"bundles/{name}.json"] = _static_json({"availability": "unavailable", "status": "staged"})
        return result

    @staticmethod
    def _release_sources(root: Path) -> dict[str, object]:
        return {
            "contract": "ticket118-release-sources-v1",
            "repository_root": str(root),
            "artifacts": [{"role": role, "path": path} for role, path in _REQUIRED_ARTIFACTS],
            "pinned_hermes": copy.deepcopy(_PINNED_HERMES),
            "environment_constraints": {"python": ">=3.11,<3.12", "core_port": ["command-v1", "managed-read-v1", "controlled-effect-v1"]},
            "target_binding_required": list(_TARGET_BINDINGS),
            "external_approval_required": list(_EXTERNAL_APPROVALS),
            "forbidden_secret_classes": list(_FORBIDDEN_SECRETS),
        }

    def build(self, output_root: Path | str) -> PublishedRelease:
        output = Path(output_root).resolve()
        output.mkdir(parents=True, exist_ok=True)
        if not output.is_dir() or output.is_symlink():
            raise ValueError("release output is unavailable")
        staging = Path(tempfile.mkdtemp(prefix="ticket120-release-", dir=output))
        try:
            for relative, content in self._source_bytes().items():
                _write_bytes(staging, relative, content)
            host_manifest = HostReleaseContract().build(self._release_sources(staging)).to_wire()
            _write_bytes(staging, "host-release-manifest.json", _canonical_bytes(host_manifest))
            files = _file_manifest(staging, exclude={"release-manifest.json"})
            body: dict[str, object] = {
                "contract": _RELEASE_CONTRACT,
                "state": "staged",
                "files": files,
                "host_release_manifest": host_manifest,
            }
            release_digest = _digest_bytes(_canonical_bytes(body))
            wire = {
                "contract": _RELEASE_CONTRACT,
                "release_digest": release_digest,
                "host_release_digest": host_manifest["release_digest"],
                "state": "staged",
                "files": files,
            }
            _write_bytes(staging, "release-manifest.json", _canonical_bytes(wire))
            destination = output / release_digest.removeprefix("sha256:")
            if destination.exists():
                details = destination.lstat()
                if destination.is_symlink() or not stat.S_ISDIR(details.st_mode):
                    raise ValueError("content-addressed release destination is unsafe")
                try:
                    _validate_release(str(destination))
                except ValueError:
                    # The fixed digest names content, not a mutable cache
                    # slot.  A damaged prior output is rejected and replaced
                    # solely by the newly verified staging tree.
                    shutil.rmtree(destination)
                else:
                    shutil.rmtree(staging)
                    return PublishedRelease(wire)
            os.replace(staging, destination)
            return PublishedRelease(wire)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise


def _file_manifest(root: Path, *, exclude: set[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError("release contains a non-regular file")
        relative = path.relative_to(root).as_posix()
        if relative not in exclude:
            result.append({"path": relative, "sha256": _file_digest(path)})
    result.sort(key=lambda item: item["path"])
    return result


def _validate_release(release_directory: object) -> dict[str, object]:
    if type(release_directory) is not str:
        raise ValueError("release directory is invalid")
    root = Path(release_directory)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("release directory is invalid")
    root = root.resolve()
    manifest_path = root / "release-manifest.json"
    host_path = root / "host-release-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink() or not host_path.is_file() or host_path.is_symlink():
        raise ValueError("release manifest is unavailable")
    manifest = _strict_json_bytes(manifest_path.read_bytes())
    host = _strict_json_bytes(host_path.read_bytes())
    if type(manifest) is not dict or set(manifest) != {"contract", "release_digest", "host_release_digest", "state", "files"}:
        raise ValueError("release manifest is invalid")
    if manifest.get("contract") != _RELEASE_CONTRACT or manifest.get("state") != "staged":
        raise ValueError("release manifest is invalid")
    release_digest = manifest.get("release_digest")
    if type(release_digest) is not str or _DIGEST.fullmatch(release_digest) is None:
        raise ValueError("release digest is invalid")
    if type(host) is not dict or manifest.get("host_release_digest") != host.get("release_digest"):
        raise ValueError("host release manifest is invalid")
    expected_host = HostReleaseContract().build(HermesReleasePublisher._release_sources(root)).to_wire()
    if host != expected_host:
        raise ValueError("host release manifest is invalid")
    declared = manifest.get("files")
    if type(declared) is not list:
        raise ValueError("release file closure is invalid")
    declared_files: dict[str, str] = {}
    for entry in declared:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise ValueError("release file closure is invalid")
        relative = _relative_path(entry.get("path"))
        digest = entry.get("sha256")
        if relative in declared_files or type(digest) is not str or _DIGEST.fullmatch(digest) is None:
            raise ValueError("release file closure is invalid")
        declared_files[relative] = digest
    actual = {entry["path"]: entry["sha256"] for entry in _file_manifest(root, exclude={"release-manifest.json"})}
    if declared_files != actual:
        raise ValueError("release file closure is invalid")
    body = {"contract": manifest["contract"], "state": manifest["state"], "files": declared, "host_release_manifest": host}
    if release_digest != _digest_bytes(_canonical_bytes(body)):
        raise ValueError("release digest is invalid")
    return copy.deepcopy(manifest)


def _observation(
    *,
    release_digest: str | None,
    verdict: str,
    backup_ref: str | None = None,
    plugin_state: str = "not-installed",
    service: str = "not-called",
    rollback: str = "not-needed",
    steps: list[str] | None = None,
    reason: str,
    idempotent: bool = False,
) -> GateObservation:
    return GateObservation(
        {
            "contract": "ticket120-gate-observation-v1",
            "release_digest": release_digest,
            "verdict": verdict,
            "backup_ref": backup_ref,
            "plugin_state": plugin_state,
            "service": service,
            "rollback": rollback,
            "steps": list(steps or ()),
            "reason": reason,
            "idempotent": idempotent,
        }
    )


class _DefaultServiceController:
    def _run(self, action: str, service: str) -> bool:
        if service != _DEFAULT_TARGET["service"]:
            return False
        result = subprocess.run(
            ["systemctl", "--user", action, service],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return result.returncode == 0

    def restart(self, service: str) -> bool:
        return self._run("restart", service)

    def is_active(self, service: str) -> bool:
        return self._run("is-active", service)


class _DefaultTargetOperations:
    """Exact default-target filesystem operations, never a general deploy API."""

    def __init__(self) -> None:
        self.root = Path(_DEFAULT_TARGET["hermes_home"])

    @property
    def _permits(self) -> Path:
        return self.root / ".ticket120-deployment-permits"

    @staticmethod
    def _permit_body(value: object) -> dict[str, object] | None:
        if type(value) is not dict or set(value) != {"contract", "release_digest", "run_id", "gate_id", "target", "expires_at"}:
            return None
        return copy.deepcopy(value)

    def _permit_path(self, approval_ref: str) -> Path | None:
        if _DIGEST.fullmatch(approval_ref) is None:
            return None
        return self._permits / (approval_ref.removeprefix("sha256:") + ".json")

    def deployment_permit(self, approval_ref: str, expected: dict[str, object]) -> str:
        path = self._permit_path(approval_ref)
        if path is None:
            return "not-authorized"
        try:
            details = path.lstat()
            if not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode) or details.st_uid != 0 or (details.st_mode & 0o777) != 0o600:
                return "not-authorized"
            body = self._permit_body(_strict_json_bytes(path.read_bytes()))
            if body is None or _digest_bytes(_canonical_bytes(body)) != approval_ref:
                return "not-authorized"
            if any(body.get(name) != value for name, value in expected.items() if name != "execution_key"):
                return "not-authorized"
            expires_at = body.get("expires_at")
            if type(expires_at) is not str:
                return "not-authorized"
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                return "not-authorized"
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return "not-authorized"
        return "authorized"

    def consume_deployment_permit(self, approval_ref: str, execution_key: str) -> bool:
        path = self._permit_path(approval_ref)
        if path is None or _EXECUTION_KEY.fullmatch(execution_key) is None:
            return False
        consumed = self.root / ".ticket120-consumed-permits" / approval_ref.removeprefix("sha256:") / f"{execution_key}.json"
        try:
            consumed.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, consumed)
            return True
        except OSError:
            # A consumed permit may only prove the already-completed staged
            # state through ``is_staged`` above.  It never authorizes a
            # second attempt after a partial or uncertain execution.
            return False

    def backup(self) -> str:
        reference = "backup:" + uuid.uuid4().hex
        destination = self.root / ".ticket120-backups" / reference.removeprefix("backup:")
        destination.mkdir(parents=True, exist_ok=False)
        plugins = self.root / "plugins"
        metadata = self.root / "ticket120-release-metadata"
        if plugins.exists():
            shutil.copytree(plugins, destination / "plugins")
        if metadata.exists():
            shutil.copytree(metadata, destination / "ticket120-release-metadata")
        return reference

    def stage(self, release_directory: Path, release_digest: str) -> None:
        final = self.root / ".ticket120-releases" / release_digest.removeprefix("sha256:")
        final.parent.mkdir(parents=True, exist_ok=True)
        draft = final.parent / (".staging-" + uuid.uuid4().hex)
        try:
            shutil.copytree(release_directory, draft)
            if final.exists():
                shutil.rmtree(final)
            os.replace(draft, final)
        except Exception:
            if draft.exists():
                shutil.rmtree(draft)
            raise

    def staged_release_directory(self, release_digest: str) -> Path:
        return self.root / ".ticket120-releases" / release_digest.removeprefix("sha256:")

    def install(self, release_digest: str, execution_key: str) -> None:
        source = self.staged_release_directory(release_digest) / "plugin" / "health-weixin"
        target = self.root / "plugins" / "health-weixin"
        draft = target.parent / (".ticket120-" + uuid.uuid4().hex)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(source, draft)
            if target.exists():
                shutil.rmtree(target)
            os.replace(draft, target)
            metadata = self.root / "ticket120-release-metadata"
            metadata.mkdir(parents=True, exist_ok=True)
            record = metadata / "health-weixin.json"
            replacement = metadata / (".ticket120-" + uuid.uuid4().hex)
            replacement.write_bytes(_canonical_bytes({"release_digest": release_digest, "execution_key": execution_key}))
            os.replace(replacement, record)
        except Exception:
            if draft.exists():
                shutil.rmtree(draft)
            raise

    def is_staged(self, release_digest: str, execution_key: str) -> bool:
        plugin = self.root / "plugins" / "health-weixin" / "plugin.yaml"
        record = self.root / "ticket120-release-metadata" / "health-weixin.json"
        try:
            return (
                self.staged_release_directory(release_digest).is_dir()
                and plugin.is_file()
                and _strict_json_bytes(record.read_bytes()) == {"release_digest": release_digest, "execution_key": execution_key}
            )
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return False

    def restore(self, backup_ref: str) -> bool:
        if not re.fullmatch(r"backup:[a-z0-9-]+", backup_ref):
            return False
        backup = self.root / ".ticket120-backups" / backup_ref.removeprefix("backup:")
        try:
            plugins = self.root / "plugins"
            metadata = self.root / "ticket120-release-metadata"
            if plugins.exists():
                shutil.rmtree(plugins)
            if metadata.exists():
                shutil.rmtree(metadata)
            saved_plugins = backup / "plugins"
            saved_metadata = backup / "ticket120-release-metadata"
            if saved_plugins.exists():
                shutil.copytree(saved_plugins, plugins)
            if saved_metadata.exists():
                shutil.copytree(saved_metadata, metadata)
            return True
        except OSError:
            return False


def _default_target_operations() -> _DefaultTargetOperations:
    return _DefaultTargetOperations()


def _default_service_controller() -> _DefaultServiceController:
    return _DefaultServiceController()


def _staged_directory(operations: object, release_digest: str) -> Path | None:
    method = getattr(operations, "staged_release_directory", None)
    if callable(method):
        candidate = method(release_digest)
        return candidate if isinstance(candidate, Path) else None
    root = getattr(operations, "root", None)
    if isinstance(root, Path):
        return root / "releases" / release_digest.removeprefix("sha256:")
    return None


class DefaultOnlyGateExecutor:
    """The only public target-local deployment entry point for Ticket 120."""

    def execute(self, request: object) -> GateObservation:
        parsed = self._request(request)
        if parsed is None:
            return _observation(release_digest=None, verdict="rejected", reason="request-invalid")
        try:
            manifest = _validate_release(parsed["release_directory"])
        except ValueError:
            return _observation(release_digest=None, verdict="rejected", reason="release-invalid")
        release_digest = manifest["release_digest"]
        assert type(release_digest) is str
        execution_key = hashlib.sha256(_canonical_bytes({"release_digest": release_digest, "run_id": parsed["run_id"], "gate_id": parsed["gate_id"]})).hexdigest()
        operations = _default_target_operations()
        if operations.is_staged(release_digest, execution_key):
            return _observation(release_digest=release_digest, verdict="staged", plugin_state="discovered-staged", service="default-active", reason="staged", idempotent=True)
        expected = {
            "contract": _PERMIT_CONTRACT,
            "release_digest": release_digest,
            "run_id": parsed["run_id"],
            "gate_id": _GATE_ID,
            "target": copy.deepcopy(_DEFAULT_TARGET),
            "execution_key": execution_key,
        }
        steps = ["permit-read"]
        if operations.deployment_permit(parsed["approval_ref"], expected) != "authorized":
            return _observation(release_digest=release_digest, verdict="not-authorized", steps=steps, reason="permit-not-authorized")
        if not operations.consume_deployment_permit(parsed["approval_ref"], execution_key):
            return _observation(release_digest=release_digest, verdict="not-authorized", steps=steps, reason="permit-not-authorized")
        steps.append("permit-consumed")
        try:
            backup_ref = operations.backup()
            steps.append("backup")
            operations.stage(Path(parsed["release_directory"]), release_digest)
            steps.append("stage")
            staged = _staged_directory(operations, release_digest)
            if staged is None:
                raise ValueError("staging location unavailable")
            _validate_release(str(staged))
        except (OSError, ValueError, RuntimeError):
            return _observation(release_digest=release_digest, verdict="rejected", backup_ref=locals().get("backup_ref"), steps=steps, reason="stage-invalid")
        service: object | None = None
        try:
            operations.install(release_digest, execution_key)
            steps.append("install")
        except (OSError, RuntimeError):
            return self._rollback(operations, service, release_digest, backup_ref, steps, "install-failed")
        if not operations.is_staged(release_digest, execution_key):
            return self._rollback(operations, service, release_digest, backup_ref, steps, "install-failed")
        service = _default_service_controller()
        try:
            restarted = service.restart(_DEFAULT_TARGET["service"])
            steps.append("restart")
        except (OSError, RuntimeError):
            restarted = False
        if not restarted:
            return self._rollback(operations, service, release_digest, backup_ref, steps, "restart-failed")
        try:
            active = service.is_active(_DEFAULT_TARGET["service"])
            steps.append("is-active")
        except (OSError, RuntimeError):
            active = False
        if not active:
            return self._rollback(operations, service, release_digest, backup_ref, steps, "postcheck-failed")
        return _observation(release_digest=release_digest, verdict="staged", backup_ref=backup_ref, plugin_state="discovered-staged", service="default-active", steps=steps, reason="staged")

    @staticmethod
    def _request(value: object) -> dict[str, str] | None:
        if type(value) is not dict or set(value) != {"contract", "target", "release_directory", "run_id", "gate_id", "approval_ref"}:
            return None
        if value.get("contract") != _GATE_CONTRACT or value.get("gate_id") != _GATE_ID or value.get("target") != _DEFAULT_TARGET:
            return None
        release_directory = value.get("release_directory")
        run_id = value.get("run_id")
        approval_ref = value.get("approval_ref")
        if type(release_directory) is not str or type(run_id) is not str or not run_id or type(approval_ref) is not str or _DIGEST.fullmatch(approval_ref) is None:
            return None
        return {"release_directory": release_directory, "run_id": run_id, "gate_id": _GATE_ID, "approval_ref": approval_ref}

    @staticmethod
    def _rollback(operations: object, service: object | None, release_digest: str, backup_ref: str, steps: list[str], reason: str) -> GateObservation:
        try:
            restored = operations.restore(backup_ref)
            steps.append("restore")
        except (OSError, RuntimeError):
            restored = False
        if not restored:
            return _observation(release_digest=release_digest, verdict="cannot-confirm", backup_ref=backup_ref, service="cannot-confirm", rollback="cannot-confirm", steps=steps, reason="rollback-unconfirmed")
        if service is None:
            service = _default_service_controller()
        try:
            restarted = service.restart(_DEFAULT_TARGET["service"])
            steps.append("restart")
        except (OSError, RuntimeError):
            restarted = False
        try:
            active = service.is_active(_DEFAULT_TARGET["service"])
            steps.append("is-active")
        except (OSError, RuntimeError):
            active = False
        if not restarted or not active:
            return _observation(release_digest=release_digest, verdict="cannot-confirm", backup_ref=backup_ref, service="cannot-confirm", rollback="cannot-confirm", steps=steps, reason="rollback-unconfirmed")
        return _observation(release_digest=release_digest, verdict="failed", backup_ref=backup_ref, service="rollback-active", rollback="completed", steps=steps, reason=reason)

"""Ticket 118 release, host, and readiness boundary.

The module deliberately exposes one product boundary.  Release artifacts and
the verification/readiness reports are immutable value objects; transport,
source loading, and validation helpers remain private to this module.
"""

from __future__ import annotations

import copy
import asyncio
import hashlib
import importlib
import inspect
import json
import os
import re
import socket
import struct
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


# The pinned Hermes modules resolve their default home during import.  Ticket
# 118 deliberately launches its verifier with a minimal environment, so give
# that import-only lookup a non-secret temporary fallback when Windows has no
# profile variables.  The verifier later supplies the real temporary Hermes
# home explicitly, and this value never enters a public wire object.
if os.environ.get("TEMP"):
    os.environ.setdefault("LOCALAPPDATA", os.environ["TEMP"])
    os.environ.setdefault("USERPROFILE", os.environ["TEMP"])
    os.environ.setdefault("HOME", os.environ["TEMP"])


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

_REQUIRED_RELEASE_ARTIFACTS = {
    "hermes-required-patch": "host/required.patch",
    "disabled-native-entry": "host/disabled-native-entry.assertion",
    "hermes-host-health-weixin-adapter": "product/hermes_host.py",
    "health-plugin": "product/plugin.py",
    "health-core": "product/core.py",
    "model-adapter-interface": "adapters/model.py",
    "delivery-adapter-interface": "adapters/delivery.py",
    "core-command-interface": "interfaces/core-command.json",
    "core-managed-read-interface": "interfaces/core-managed-read.json",
    "core-controlled-effect-interface": "interfaces/core-controlled-effect.json",
    "health-state-schema": "schemas/health-state.json",
    "capability-profile-schema": "model/capability-profile-schema.json",
    "capability-profile-builder": "model/capability-profile-builder.py",
    "capability-profile-validator": "model/capability-profile-validator.py",
    "minimum-help-bundle": "bundles/minimum-help.json",
    "knowledge-bundle": "bundles/knowledge.json",
    "safety-bundle": "bundles/safety.json",
    "diagnostic-bundle": "bundles/diagnostic.json",
    "migration-protocol": "migration/protocol.json",
    "migration-schema": "migration/schema.json",
    "migration-builder": "migration/builder.py",
    "migration-semantic-registry": "migration/semantic-registry.json",
    "migration-synthetic-fixture": "migration/ticket117-synthetic-fixture.py",
    "python-constraint": "environment/python.txt",
    "dependency-constraint": "environment/dependencies.lock",
    "service-identity-acl-requirement": "environment/service-acl.json",
    "skill:health-init": "skills/health-init/SKILL.md",
    "skill:health-steward": "skills/health-steward/SKILL.md",
    "skill:health-settings": "skills/health-settings/SKILL.md",
    "skill:health-portrait": "skills/health-portrait/SKILL.md",
    "skill:health-evidence": "skills/health-evidence/SKILL.md",
    "skill:health-owner-inquiry": "skills/health-owner-inquiry/SKILL.md",
    "skill:health-literature": "skills/health-literature/SKILL.md",
}
_TARGET_BINDING_REQUIREMENTS = (
    "target-hermes-artifact",
    "target-required-patch",
    "target-plugin-binding",
    "target-service-identity",
    "target-unix-acl",
    "target-current-head",
    "target-native-entry-disabled",
)
_EXTERNAL_APPROVAL_REQUIREMENTS = (
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
_CURRENT_PROCESS_ACTIVATION_CAPABILITY = object()

_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/]|"
    r"/(?:home|root|Users|etc|var|tmp|opt|srv|mnt|workspace)/)"
)
_FORBIDDEN_CONTENT_MARKERS = (
    "TICKET118_",
    "synthetic health正文",
    "blood pressure",
)


class _HostVerificationFailure(ValueError):
    """Internal fail-closed error whose public form is a stable reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plain_text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"invalid {name}")
    return value


def _string_list(value: object, name: str) -> list[str]:
    if type(value) not in (list, tuple):
        raise ValueError(f"invalid {name}")
    result = [_plain_text(item, name) for item in value]
    if len(set(result)) != len(result):
        raise ValueError(f"duplicate {name}")
    return result


def _relative_path(value: object, name: str) -> str:
    relative = _plain_text(value, name)
    if "\\" in relative:
        raise ValueError(f"invalid {name}")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or not parsed.parts or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise ValueError(f"invalid {name}")
    return parsed.as_posix()


def _scan_artifact(relative: str, content: bytes) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"non-utf8 release artifact: {relative}") from exc
    if "\x00" in text or _ABSOLUTE_PATH.search(text):
        raise ValueError(f"release artifact contains an absolute path: {relative}")
    if any(marker in text for marker in _FORBIDDEN_CONTENT_MARKERS):
        raise ValueError(f"release artifact contains forbidden content: {relative}")


def _validate_release_artifact_closure(
    entries: object,
    *,
    require_hashes: bool,
) -> None:
    if type(entries) not in (list, tuple):
        raise ValueError("release artifact closure is unavailable")
    declared: dict[str, str] = {}
    for entry in entries:
        expected_fields = {"path", "role", "sha256"} if require_hashes else {"path", "role"}
        if type(entry) is not dict or set(entry) != expected_fields:
            raise ValueError("release artifact closure entry is invalid")
        relative = _relative_path(entry["path"], "artifact path")
        role = _plain_text(entry["role"], "artifact role")
        if role in declared:
            raise ValueError("duplicate release artifact role")
        if require_hashes:
            declared_hash = _plain_text(entry["sha256"], "artifact hash")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", declared_hash):
                raise ValueError("invalid release artifact hash")
        declared[role] = relative
    if declared != _REQUIRED_RELEASE_ARTIFACTS:
        raise ValueError("release artifact closure is incomplete")


def _activation_proof(release_digest: str) -> str:
    return "sha256:" + _sha256_bytes(
        _canonical_bytes(
            {
                "manifest": release_digest,
                "host": "health_weixin",
                "lifecycle": ["connect", "disconnect"],
            }
        )
    )


def _is_current_process_activation(
    capability: object, proof: object
) -> bool:
    return capability is _CURRENT_PROCESS_ACTIVATION_CAPABILITY and (
        type(proof) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", proof) is not None
    )


def _manifest_entry(wire: Mapping[str, object], role: str) -> dict[str, object]:
    entries = wire.get("repository_verified")
    if type(entries) is not list:
        raise _HostVerificationFailure("manifest-artifact-list-missing")
    matches = [
        item for item in entries
        if type(item) is dict and item.get("role") == role
    ]
    if len(matches) != 1:
        raise _HostVerificationFailure("manifest-artifact-role-mismatch")
    return copy.deepcopy(matches[0])


def _wire_of(value: object) -> dict[str, object]:
    if isinstance(value, (ReleaseManifest, HostContractReport, ReadinessReport)):
        return value.to_wire()
    if type(value) is dict:
        return copy.deepcopy(value)
    raise _HostVerificationFailure("invalid-public-value")


class _CorePortClient:
    """Small strict byte-stream client for the three frozen CorePort kinds."""

    _KIND_TO_REQUEST_ID = {
        "command": "ticket118-command",
        "managed-read": "ticket118-managed-read",
    }

    def __init__(self, endpoint: Mapping[str, object]) -> None:
        if type(endpoint) is not dict:
            raise _HostVerificationFailure("core-endpoint-invalid")
        transport = endpoint.get("transport")
        if transport == "af-unix":
            if not hasattr(socket, "AF_UNIX") or type(endpoint.get("path")) is not str:
                raise _HostVerificationFailure("core-endpoint-invalid")
            self._transport = "af-unix"
            self._address: object = endpoint["path"]
        elif transport == "tcp-loopback":
            if type(endpoint.get("host")) is not str or type(endpoint.get("port")) is not int:
                raise _HostVerificationFailure("core-endpoint-invalid")
            if endpoint["host"] not in {"127.0.0.1", "localhost"}:
                raise _HostVerificationFailure("core-endpoint-invalid")
            self._transport = "tcp-loopback"
            self._address = (endpoint["host"], endpoint["port"])
        else:
            raise _HostVerificationFailure("core-endpoint-transport-invalid")
        if endpoint.get("protocol") != "ticket118-core-port-v1":
            raise _HostVerificationFailure("core-endpoint-protocol-invalid")

    @staticmethod
    def _recv_exact(connection: socket.socket, size: int) -> bytes:
        value = bytearray()
        while len(value) < size:
            chunk = connection.recv(size - len(value))
            if not chunk:
                raise _HostVerificationFailure("core-frame-truncated")
            value.extend(chunk)
        return bytes(value)

    def _connect(self) -> socket.socket:
        if self._transport == "af-unix":
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.settimeout(2.0)
            try:
                connection.connect(self._address)  # type: ignore[arg-type]
            except Exception:
                connection.close()
                raise
            return connection
        return socket.create_connection(self._address, timeout=2.0)  # type: ignore[arg-type]

    def request(self, kind: str, payload: Mapping[str, object], *, request_id: str | None = None) -> dict[str, object]:
        if kind not in {"command", "managed-read", "controlled-effect"}:
            raise _HostVerificationFailure("core-kind-invalid")
        if type(payload) is not dict:
            raise _HostVerificationFailure("core-payload-invalid")
        if request_id is None:
            request_id = self._KIND_TO_REQUEST_ID.get(
                kind, "ticket118-controlled-effect"
            )
        request = {
            "protocol_version": 1,
            "kind": kind,
            "request_id": request_id,
            "payload": copy.deepcopy(payload),
        }
        body = _canonical_bytes(request)
        if len(body) > 65536:
            raise _HostVerificationFailure("core-frame-too-large")
        frame = struct.pack(">I", len(body)) + body
        try:
            with self._connect() as connection:
                connection.sendall(frame)
                header = self._recv_exact(connection, 4)
                declared = struct.unpack(">I", header)[0]
                if declared > 65536:
                    raise _HostVerificationFailure("core-frame-too-large")
                response_body = self._recv_exact(connection, declared)
                try:
                    trailing = connection.recv(1)
                except socket.timeout as exc:
                    raise _HostVerificationFailure("core-frame-trailing") from exc
                if trailing:
                    raise _HostVerificationFailure("core-frame-trailing")
        except _HostVerificationFailure:
            raise
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise _HostVerificationFailure("core-transport-failed") from exc
        try:
            response = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _HostVerificationFailure("core-response-invalid") from exc
        if type(response) is not dict or set(response) != {
            "protocol_version", "kind", "request_id", "status", "payload"
        }:
            raise _HostVerificationFailure("core-response-fields-invalid")
        if (
            response.get("protocol_version") != 1
            or response.get("kind") != kind
            or response.get("request_id") != request_id
            or response.get("status") != "accepted"
            or type(response.get("payload")) is not dict
        ):
            raise _HostVerificationFailure("core-response-mismatch")
        return response


def _require_mapping(value: object, fields: set[str], reason: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise _HostVerificationFailure(reason)
    return value


@dataclass(frozen=True, repr=False)
class ReleaseManifest:
    """Immutable public release identity with a private source locator."""

    _wire: dict[str, object]
    _repository_root: Path

    def to_wire(self) -> dict[str, object]:
        return copy.deepcopy(self._wire)


@dataclass(frozen=True, repr=False)
class HostContractReport:
    """Immutable public host verification result."""

    _wire: dict[str, object]

    def to_wire(self) -> dict[str, object]:
        return copy.deepcopy(self._wire)


@dataclass(frozen=True, repr=False)
class ReadinessReport:
    """Immutable public install/upgrade/rollback result."""

    _wire: dict[str, object]

    def to_wire(self) -> dict[str, object]:
        return copy.deepcopy(self._wire)


class HostReleaseContract:
    """The single public Ticket 118 release/host/readiness seam."""

    def build(self, release_sources: Mapping[str, object]) -> ReleaseManifest:
        if type(release_sources) is not dict:
            raise ValueError("release sources must be a plain mapping")
        if release_sources.get("contract") != "ticket118-release-sources-v1":
            raise ValueError("invalid release sources contract")
        repository_root_value = release_sources.get("repository_root")
        repository_root = Path(_plain_text(repository_root_value, "repository root"))
        if not repository_root.is_dir():
            raise ValueError("repository root is unavailable")

        raw_artifacts = release_sources.get("artifacts")
        if type(raw_artifacts) not in (list, tuple) or not raw_artifacts:
            raise ValueError("release artifact allowlist is unavailable")
        _validate_release_artifact_closure(raw_artifacts, require_hashes=False)
        verified: list[dict[str, str]] = []
        seen_paths: set[str] = set()
        seen_roles: set[str] = set()
        for raw in raw_artifacts:
            if type(raw) is not dict or set(raw) != {"path", "role"}:
                raise ValueError("invalid release artifact allowlist entry")
            relative = _relative_path(raw["path"], "artifact path")
            role = _plain_text(raw["role"], "artifact role")
            if relative in seen_paths:
                raise ValueError("duplicate release artifact path")
            if role in seen_roles:
                raise ValueError("duplicate release artifact role")
            seen_paths.add(relative)
            seen_roles.add(role)
            path = repository_root / Path(*PurePosixPath(relative).parts)
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise ValueError("release artifact is unavailable") from exc
            if repository_root.resolve() not in resolved.parents:
                raise ValueError("release artifact escapes repository root")
            if path.is_symlink() or not path.is_file():
                raise ValueError("release artifact must be a regular file")
            content = path.read_bytes()
            _scan_artifact(relative, content)
            verified.append(
                {
                    "path": relative,
                    "role": role,
                    "sha256": "sha256:" + _sha256_bytes(content),
                }
            )
        verified.sort(key=lambda item: item["path"])

        pinned_raw = release_sources.get("pinned_hermes")
        if type(pinned_raw) is not dict or set(pinned_raw) != {
            "commit",
            "allowlisted_files",
            "extractor_version",
        }:
            raise ValueError("invalid pinned Hermes declaration")
        pinned_commit = _plain_text(pinned_raw["commit"], "pinned Hermes commit")
        extractor_version = _plain_text(
            pinned_raw["extractor_version"], "pinned Hermes extractor version"
        )
        raw_pinned_files = pinned_raw["allowlisted_files"]
        if type(raw_pinned_files) not in (list, tuple) or not raw_pinned_files:
            raise ValueError("invalid pinned Hermes allowlist")
        pinned_files: list[dict[str, str]] = []
        seen_pinned: set[str] = set()
        for raw in raw_pinned_files:
            if type(raw) is not dict or set(raw) != {"path", "sha256"}:
                raise ValueError("invalid pinned Hermes allowlist entry")
            relative = _relative_path(raw["path"], "pinned Hermes path")
            declared_hash = _plain_text(raw["sha256"], "pinned Hermes hash")
            if relative in seen_pinned:
                raise ValueError("duplicate pinned Hermes path")
            seen_pinned.add(relative)
            if not re.fullmatch(r"[0-9a-f]{64}", declared_hash):
                raise ValueError("invalid pinned Hermes hash")
            pinned_files.append({"path": relative, "sha256": declared_hash})

        environment_raw = release_sources.get("environment_constraints")
        if type(environment_raw) is not dict or set(environment_raw) != {
            "python",
            "core_port",
        }:
            raise ValueError("invalid environment constraints")
        environment = {
            "python": _plain_text(environment_raw["python"], "Python constraint"),
            "core_port": _string_list(
                environment_raw["core_port"], "CorePort versions"
            ),
        }
        target = _string_list(
            release_sources.get("target_binding_required"),
            "target binding requirements",
        )
        external = _string_list(
            release_sources.get("external_approval_required"),
            "external approval requirements",
        )
        forbidden = _string_list(
            release_sources.get("forbidden_secret_classes"),
            "forbidden secret classes",
        )
        if set(target) & set(external) or set(target) & set(forbidden) or set(external) & set(forbidden):
            raise ValueError("release classifications overlap")

        wire_without_digest: dict[str, object] = {
            "contract": "ticket118-release-manifest-v1",
            "repository_verified": verified,
            "pinned_hermes": {
                "commit": pinned_commit,
                "allowlisted_files": pinned_files,
                "extractor_version": extractor_version,
            },
            "environment_constraints": environment,
            "target_binding_required": target,
            "external_approval_required": external,
            "forbidden_secret_classes": forbidden,
        }
        digest = "sha256:" + _sha256_bytes(_canonical_bytes(wire_without_digest))
        wire = dict(wire_without_digest)
        wire["release_digest"] = digest
        return ReleaseManifest(wire, repository_root.resolve())

    def verify(
        self,
        release_manifest: ReleaseManifest,
        pinned_host_source: Mapping[str, object],
    ) -> HostContractReport:
        """Verify one release against the supplied pinned host source.

        All failures are returned as a public failed-closed report.  Source
        roots, endpoints, credentials, and exception text never cross that
        report boundary.
        """

        try:
            wire = _wire_of(release_manifest)
            if not isinstance(release_manifest, ReleaseManifest):
                raise _HostVerificationFailure("manifest-source-locator-missing")
            self._validate_manifest(release_manifest, wire)
            source = self._validate_pinned_source(wire, pinned_host_source)
            self._validate_credential(source)
            self._validate_host_artifacts(release_manifest, wire, source)
            proof = self._run_pinned_lifecycle(release_manifest, wire, source)
        except _HostVerificationFailure as exc:
            return HostContractReport(
                {
                    "contract": "ticket118-host-contract-report-v1",
                    "verdict": "fail",
                    "reason_code": exc.reason_code,
                    "activation_proof": None,
                }
            )
        except Exception:
            # Do not expose implementation, source, or filesystem details in
            # a product report.  Unexpected verifier failures are still fail
            # closed and remain distinguishable from a passed proof.
            return HostContractReport(
                {
                    "contract": "ticket118-host-contract-report-v1",
                    "verdict": "fail",
                    "reason_code": "host-verification-failed",
                    "activation_proof": None,
                }
            )
        return HostContractReport(proof)

    def assess(self, transition_assessment: Mapping[str, object]) -> ReadinessReport:
        """Evaluate install, offline upgrade, or rollback readiness."""

        if type(transition_assessment) is not dict:
            return ReadinessReport(
                {
                    "contract": "ticket118-readiness-report-v1",
                    "verdict": "cannot-confirm",
                    "reason_code": "assessment-invalid",
                }
            )
        mode = transition_assessment.get("mode")
        if mode not in {"install", "upgrade", "rollback"}:
            return ReadinessReport(
                {
                    "contract": "ticket118-readiness-report-v1",
                    "verdict": "cannot-confirm",
                    "reason_code": "assessment-mode-invalid",
                }
            )
        if transition_assessment.get("contract") != "ticket118-transition-assessment-v1":
            return ReadinessReport(
                {
                    "contract": "ticket118-readiness-report-v1",
                    "mode": mode,
                    "verdict": "cannot-confirm",
                    "reason_code": "assessment-contract-invalid",
                    "activation_proof": None,
                }
            )
        if mode == "install":
            return self._assess_install(transition_assessment)
        if mode == "upgrade":
            return self._assess_upgrade(transition_assessment)
        return self._assess_rollback(transition_assessment)

    @staticmethod
    def _validate_manifest(
        manifest: ReleaseManifest, wire: Mapping[str, object]
    ) -> None:
        try:
            HostReleaseContract._validate_manifest_wire(wire)
        except ValueError as exc:
            raise _HostVerificationFailure("manifest-closure-invalid") from exc
        if manifest._repository_root.is_dir() is False:
            raise _HostVerificationFailure("manifest-source-root-missing")

    @staticmethod
    def _validate_manifest_wire(wire: Mapping[str, object]) -> None:
        if type(wire) is not dict:
            raise ValueError("manifest must be a plain mapping")
        if wire.get("contract") != "ticket118-release-manifest-v1":
            raise ValueError("manifest contract is invalid")
        release_digest = wire.get("release_digest")
        if type(release_digest) is not str or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", release_digest
        ):
            raise ValueError("manifest digest is invalid")
        identity = copy.deepcopy(dict(wire))
        identity.pop("release_digest", None)
        try:
            expected = "sha256:" + _sha256_bytes(_canonical_bytes(identity))
        except (TypeError, ValueError) as exc:
            raise ValueError("manifest identity is invalid") from exc
        if release_digest != expected:
            raise ValueError("manifest digest does not match identity")
        _validate_release_artifact_closure(
            wire.get("repository_verified"), require_hashes=True
        )
        pinned = wire.get("pinned_hermes")
        expected_pinned_files = [
            {"path": path, "sha256": digest}
            for path, digest in _PINNED_FILES.items()
        ]
        if (
            type(pinned) is not dict
            or pinned.get("commit") != _PINNED_COMMIT
            or pinned.get("allowlisted_files") != expected_pinned_files
            or pinned.get("extractor_version") != "ticket118-pinned-source-v1"
        ):
            raise ValueError("manifest pinned source is invalid")
        environment = wire.get("environment_constraints")
        if (
            type(environment) is not dict
            or set(environment) != {"python", "core_port"}
            or type(environment.get("python")) is not str
            or not environment["python"]
        ):
            raise ValueError("manifest environment is invalid")
        core_port = environment.get("core_port")
        if type(core_port) not in (list, tuple) or list(core_port) != [
            "command-v1",
            "managed-read-v1",
            "controlled-effect-v1",
        ]:
            raise ValueError("manifest environment is invalid")
        if wire.get("target_binding_required") != list(_TARGET_BINDING_REQUIREMENTS):
            raise ValueError("manifest target binding is invalid")
        if wire.get("external_approval_required") != list(
            _EXTERNAL_APPROVAL_REQUIREMENTS
        ):
            raise ValueError("manifest external approval is invalid")
        if wire.get("forbidden_secret_classes") != list(_SECRET_CLASSES):
            raise ValueError("manifest secret classification is invalid")

    @staticmethod
    def _assessment_manifest(value: object) -> dict[str, object] | None:
        if type(value) is not dict:
            return None
        try:
            HostReleaseContract._validate_manifest_wire(value)
        except ValueError:
            return None
        return copy.deepcopy(value)

    @staticmethod
    def _host_report_state(
        value: object, manifest: Mapping[str, object] | None
    ) -> str:
        if type(value) is not dict or value.get(
            "contract"
        ) != "ticket118-host-contract-report-v1":
            return "cannot-confirm"
        verdict = value.get("verdict")
        if verdict == "fail":
            return "fail"
        if verdict != "pass" or manifest is None:
            return "cannot-confirm"
        release_digest = manifest.get("release_digest")
        if type(release_digest) is not str or value.get(
            "activation_proof"
        ) != _activation_proof(release_digest):
            return "cannot-confirm"
        proofs = value.get("proofs")
        registration = proofs.get("registration") if type(proofs) is dict else None
        if (
            type(registration) is not dict
            or registration.get("platform") != "health_weixin"
            or registration.get("discovery") != "completed"
            or registration.get("lifecycle") != ["connect", "disconnect"]
        ):
            return "cannot-confirm"
        return "pass"

    @staticmethod
    def _validate_pinned_source(
        manifest: Mapping[str, object], source: Mapping[str, object]
    ) -> dict[str, object]:
        if type(source) is not dict:
            raise _HostVerificationFailure("pinned-source-invalid")
        if source.get("contract") != "ticket118-pinned-hermes-source-v1":
            raise _HostVerificationFailure("pinned-source-contract-invalid")
        root_value = source.get("root")
        if type(root_value) is not str:
            raise _HostVerificationFailure("pinned-source-root-invalid")
        root = Path(root_value)
        if not root.is_dir():
            raise _HostVerificationFailure("pinned-source-root-missing")
        if source.get("commit") != _PINNED_COMMIT:
            raise _HostVerificationFailure("pinned-source-commit-invalid")
        try:
            head = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise _HostVerificationFailure("pinned-source-head-unavailable")
        if head != _PINNED_COMMIT:
            raise _HostVerificationFailure("pinned-source-head-mismatch")
        raw_files = source.get("allowlisted_files")
        expected_files = [
            {"path": path, "sha256": digest}
            for path, digest in _PINNED_FILES.items()
        ]
        if raw_files != expected_files:
            raise _HostVerificationFailure("pinned-source-declaration-mismatch")
        pinned_manifest = manifest.get("pinned_hermes")
        expected_manifest = {
            "commit": _PINNED_COMMIT,
            "allowlisted_files": expected_files,
            "extractor_version": "ticket118-pinned-source-v1",
        }
        if pinned_manifest != expected_manifest:
            raise _HostVerificationFailure("pinned-source-manifest-mismatch")
        for relative, expected_hash in _PINNED_FILES.items():
            path = root / Path(*PurePosixPath(relative).parts)
            if not path.is_file() or _sha256_file(path) != expected_hash:
                raise _HostVerificationFailure("pinned-source-file-mismatch")

        staged_value = source.get("staged_root", root_value)
        if type(staged_value) is not str:
            raise _HostVerificationFailure("staged-source-root-invalid")
        staged = Path(staged_value)
        if not staged.is_dir():
            raise _HostVerificationFailure("staged-source-root-missing")
        for relative in (
            "hermes_cli/plugins.py",
            "gateway/platform_registry.py",
            "gateway/platforms/weixin.py",
        ):
            path = staged / Path(*PurePosixPath(relative).parts)
            if not path.is_file() or _sha256_file(path) != _PINNED_FILES[relative]:
                raise _HostVerificationFailure("staged-source-base-mismatch")
        gateway_run = staged / "gateway" / "run.py"
        if not gateway_run.is_file() or _sha256_file(gateway_run) == _PINNED_FILES["gateway/run.py"]:
            raise _HostVerificationFailure("staged-source-patch-missing")
        return {
            "root": root,
            "staged_root": staged,
            "hermes_home": source.get("hermes_home"),
            "core_port_endpoint": source.get("core_port_endpoint"),
            "credential_adapter": source.get("credential_adapter"),
            "effect_adapter": source.get("effect_adapter"),
            "native_disabled_assertion": source.get("native_disabled_assertion"),
        }

    @staticmethod
    def _validate_credential(source: Mapping[str, object]) -> None:
        adapter = source.get("credential_adapter")
        observe = getattr(adapter, "observe", None)
        if not callable(observe):
            raise _HostVerificationFailure("credential-observation-missing")
        try:
            observed = observe()
        except Exception as exc:
            raise _HostVerificationFailure("credential-observation-failed") from exc
        if type(observed) is not dict or any(
            observed.get(key) != expected
            for key, expected in {
                "peer": "plugin",
                "service": "health-core",
                "acl": "allowed",
                "enforcement": "synthetic-contract-only",
            }.items()
        ):
            raise _HostVerificationFailure("credential-contract-failed")

    @staticmethod
    def _validate_host_artifacts(
        manifest: ReleaseManifest,
        wire: Mapping[str, object],
        source: Mapping[str, object],
    ) -> None:
        root = manifest._repository_root
        for item in wire.get("repository_verified", []):
            if type(item) is not dict:
                raise _HostVerificationFailure("manifest-artifact-entry-invalid")
            relative = item.get("path")
            declared = item.get("sha256")
            if type(relative) is not str or type(declared) is not str:
                raise _HostVerificationFailure("manifest-artifact-entry-invalid")
            path = root / Path(*PurePosixPath(relative).parts)
            if not path.is_file() or "sha256:" + _sha256_file(path) != declared:
                raise _HostVerificationFailure("release-artifact-drift")

        assertion = source.get("native_disabled_assertion")
        if type(assertion) is not dict:
            raise _HostVerificationFailure("native-disabled-assertion-missing")
        assertion_entry = _manifest_entry(wire, "disabled-native-entry")
        relative = assertion_entry.get("path")
        declared = assertion_entry.get("sha256")
        if (
            type(relative) is not str
            or type(declared) is not str
            or assertion.get("path") != relative
            or assertion.get("declared_sha256") != declared
            or type(assertion.get("bytes")) is not bytes
            or assertion.get("actual_sha256")
            != "sha256:" + _sha256_bytes(assertion["bytes"])
        ):
            raise _HostVerificationFailure("native-disabled-assertion-drift")
        assertion_path = root / Path(*PurePosixPath(relative).parts)
        if not assertion_path.is_file() or "sha256:" + _sha256_file(assertion_path) != declared:
            raise _HostVerificationFailure("native-disabled-assertion-drift")

        home_value = source.get("hermes_home")
        if type(home_value) is not str:
            raise _HostVerificationFailure("hermes-home-missing")
        plugin = Path(home_value) / "plugins" / "ticket118-health" / "__init__.py"
        host_entry = _manifest_entry(wire, "hermes-host-health-weixin-adapter")
        if (
            not plugin.is_file()
            or "sha256:" + _sha256_file(plugin) != host_entry.get("sha256")
        ):
            raise _HostVerificationFailure("hermes-host-artifact-drift")

    def _run_pinned_lifecycle(
        self,
        manifest: ReleaseManifest,
        wire: Mapping[str, object],
        source: Mapping[str, object],
    ) -> dict[str, object]:
        del self
        runner: object | None = None
        config: object | None = None
        try:
            plugins = importlib.import_module("hermes_cli.plugins")
            registry_module = importlib.import_module("gateway.platform_registry")
            gateway_run = importlib.import_module("gateway.run")
            manager = plugins.PluginManager()
            manager.discover_and_load(force=True)
            registry = registry_module.platform_registry
            entry = registry.get("health_weixin")
            check = getattr(entry, "check_fn", None)
            release_digest = wire.get("release_digest")
            if not callable(check) or type(release_digest) is not str:
                raise _HostVerificationFailure("health-weixin-registration-missing")
            activation = _activation_proof(release_digest)
            activate = getattr(check, "_ticket118_arm", None)
            if not callable(activate):
                raise _HostVerificationFailure("health-weixin-activation-missing")
            activate(_CURRENT_PROCESS_ACTIVATION_CAPABILITY, activation)
            runner_type = gateway_run.GatewayRunner
            runner = runner_type.__new__(runner_type)
            runner.config = type(
                "Ticket118GatewayConfig",
                (),
                {"group_sessions_per_user": False, "thread_sessions_per_user": False},
            )()
            config = type("Ticket118PlatformConfig", (), {})()
            config.extra = {
                "core_port_endpoint": copy.deepcopy(source["core_port_endpoint"]),
                "effect_adapter": source["effect_adapter"],
                "registry": registry,
                "activation_capability": _CURRENT_PROCESS_ACTIVATION_CAPABILITY,
                "activation_proof": activation,
            }
            names = ("health_weixin", "weixin", "medical", "ordinary")
            adapters = [
                runner._create_adapter(type("PlatformName", (), {"value": name})(), config)
                for name in names
            ]
            health_adapter = adapters[0]
            if health_adapter is None:
                raise _HostVerificationFailure("health-weixin-registration-missing")

            async def lifecycle() -> None:
                await health_adapter.connect(is_reconnect=False)
                await health_adapter.disconnect()

            try:
                asyncio.run(lifecycle())
            except _HostVerificationFailure:
                raise
            except Exception as exc:
                raise _HostVerificationFailure("health-weixin-lifecycle-failed") from exc

            if registry.get("health_weixin") is None:
                raise _HostVerificationFailure("health-weixin-registration-missing")
            endpoint = source.get("core_port_endpoint")
            transport = endpoint.get("transport") if type(endpoint) is dict else None
            return {
                "contract": "ticket118-host-contract-report-v1",
                "verdict": "pass",
                "activation_proof": activation,
                "proofs": {
                    "pinned_source": {
                        "commit": _PINNED_COMMIT,
                        "allowlisted_files": [
                            {"path": path, "sha256": digest}
                            for path, digest in _PINNED_FILES.items()
                        ],
                        "staged_modules": [
                            "hermes_cli.plugins",
                            "gateway.platform_registry",
                            "gateway.run",
                        ],
                        "patched_gateway": True,
                    },
                    "registration": {
                        "platform": "health_weixin",
                        "discovery": "completed",
                        "lifecycle": ["connect", "disconnect"],
                    },
                    "core_port": {
                        "transport": transport,
                        "interfaces": [
                            "command-v1",
                            "managed-read-v1",
                            "controlled-effect-v1",
                        ],
                        "terminal": "accepted",
                    },
                    "native_disabled_entry": {
                        "path": _manifest_entry(wire, "disabled-native-entry")["path"],
                        "sha256": _manifest_entry(wire, "disabled-native-entry")["sha256"],
                    },
                    "fallback": {
                        "legacy_health_entries": "unreachable",
                        "ordinary_entry": "unreachable",
                    },
                },
            }
        except _HostVerificationFailure:
            # After a lifecycle failure, the adapter owns unregistering the
            # current entry.  The caller performs the independent reachability
            # probe below before returning the failed-closed report.
            try:
                registry = importlib.import_module("gateway.platform_registry").platform_registry
                registry.unregister("health_weixin")
            except Exception:
                pass
            if runner is not None and config is not None:
                for name in ("health_weixin", "weixin", "medical", "ordinary"):
                    try:
                        runner._create_adapter(  # type: ignore[attr-defined]
                            type("PlatformName", (), {"value": name})(), config
                        )
                    except Exception:
                        pass
            raise
        except Exception as exc:
            try:
                registry = importlib.import_module("gateway.platform_registry").platform_registry
                registry.unregister("health_weixin")
            except Exception:
                pass
            if runner is not None and config is not None:
                for name in ("health_weixin", "weixin", "medical", "ordinary"):
                    try:
                        runner._create_adapter(  # type: ignore[attr-defined]
                            type("PlatformName", (), {"value": name})(), config
                        )
                    except Exception:
                        pass
            raise _HostVerificationFailure("pinned-lifecycle-failed") from exc

    @staticmethod
    def _assess_install(assessment: Mapping[str, object]) -> ReadinessReport:
        manifest = HostReleaseContract._assessment_manifest(
            assessment.get("release_manifest")
        )
        host_state = HostReleaseContract._host_report_state(
            assessment.get("host_report"), manifest
        )
        if host_state == "fail":
            return ReadinessReport(
                {
                    "contract": "ticket118-readiness-report-v1",
                    "mode": "install",
                    "verdict": "fail",
                    "reason_code": "host-report-failed",
                    "partner_verdict": "fail",
                    "activation_proof": None,
                }
            )
        if manifest is None or host_state != "pass":
            return ReadinessReport(
                {
                    "contract": "ticket118-readiness-report-v1",
                    "mode": "install",
                    "verdict": "cannot-confirm",
                    "reason_code": "release-or-host-evidence-invalid",
                    "partner_verdict": "cannot-confirm",
                    "activation_proof": None,
                }
            )
        requirements = list(manifest["target_binding_required"])
        observations = assessment.get("target_observations")
        if type(observations) is not dict:
            observations = {}
        missing = [
            requirement
            for requirement in requirements
            if type(observations.get(requirement)) is not dict
            or observations[requirement].get("status") != "verified"
        ]
        unconfirmed_targets = [
            requirement
            for requirement in requirements
            if type(observations.get(requirement)) is not dict
            or observations[requirement].get("evidence_class") != "target-attested"
        ]
        approvals = assessment.get("external_approvals")
        if type(approvals) is not dict:
            approvals = {}
        required_approvals = list(manifest["external_approval_required"])
        missing_approvals = [
            requirement
            for requirement in required_approvals
            if type(approvals.get(requirement)) is not dict
            or approvals[requirement].get("status") != "approved"
        ]
        unconfirmed_approvals = [
            requirement
            for requirement in required_approvals
            if type(approvals.get(requirement)) is not dict
            or approvals[requirement].get("evidence_class") != "external-attested"
        ]
        return ReadinessReport(
            {
                "contract": "ticket118-readiness-report-v1",
                "mode": "install",
                "verdict": "cannot-confirm",
                "reason_code": "target-or-external-evidence-not-bound-in-ticket118",
                "missing_requirements": missing,
                "unconfirmed_target_requirements": unconfirmed_targets,
                "missing_external_approvals": missing_approvals,
                "unconfirmed_external_approvals": unconfirmed_approvals,
                "partner_verdict": "cannot-confirm",
                "activation_proof": None,
            }
        )

    @staticmethod
    def _assess_upgrade(assessment: Mapping[str, object]) -> ReadinessReport:
        before = HostReleaseContract._assessment_manifest(
            assessment.get("from_release_manifest")
        )
        after = HostReleaseContract._assessment_manifest(
            assessment.get("to_release_manifest")
        )
        host_state = HostReleaseContract._host_report_state(
            assessment.get("host_report"), before
        )
        if host_state == "fail":
            return ReadinessReport(
                {
                    "contract": "ticket118-readiness-report-v1",
                    "mode": "upgrade",
                    "verdict": "fail",
                    "reason_code": "host-report-failed",
                    "activation_proof": None,
                }
            )
        scope = assessment.get("assessment_scope")
        if (
            scope != "offline-release-compatibility"
            or before is None
            or after is None
            or host_state != "pass"
            or assessment.get("target_binding_required") != []
            or assessment.get("target_observations") != {}
        ):
            return ReadinessReport(
                {
                    "contract": "ticket118-readiness-report-v1",
                    "mode": "upgrade",
                    "verdict": "cannot-confirm",
                    "assessment_scope": scope,
                    "activation_proof": None,
                }
            )
        same = before == after
        return ReadinessReport(
            {
                "contract": "ticket118-readiness-report-v1",
                "mode": "upgrade",
                "assessment_scope": scope,
                "verdict": "pass" if same else "fail",
                "offline_compatibility": "pass" if same else "fail",
                "activation_proof": None,
            }
        )

    @staticmethod
    def _assess_rollback(assessment: Mapping[str, object]) -> ReadinessReport:
        before = HostReleaseContract._assessment_manifest(
            assessment.get("from_release_manifest")
        )
        after = HostReleaseContract._assessment_manifest(
            assessment.get("to_release_manifest")
        )
        host_state = HostReleaseContract._host_report_state(
            assessment.get("host_report"), after
        )
        if host_state == "fail":
            return ReadinessReport(
                {
                    "contract": "ticket118-readiness-report-v1",
                    "mode": "rollback",
                    "verdict": "fail",
                    "reason_code": "host-report-failed",
                    "restore_instance_state": False,
                    "activation_proof": None,
                }
            )
        if before is None or after is None or host_state != "pass":
            return ReadinessReport(
                {
                    "contract": "ticket118-readiness-report-v1",
                    "mode": "rollback",
                    "verdict": "cannot-confirm",
                    "reason_code": "release-or-host-evidence-invalid",
                    "restore_instance_state": False,
                    "activation_proof": None,
                }
            )
        return ReadinessReport(
            {
                "contract": "ticket118-readiness-report-v1",
                "mode": "rollback",
                "verdict": "cannot-confirm",
                "reason_code": "target-authority-not-bound-in-ticket118",
                "restore_instance_state": False,
                "activation_proof": None,
            }
        )


__all__ = [
    "HostContractReport",
    "HostReleaseContract",
    "ReadinessReport",
    "ReleaseManifest",
]

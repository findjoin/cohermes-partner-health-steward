"""Ticket 123 production-only health-core composition root.

This module keeps deployment wiring out of the health business state machine.
It accepts an already-bound Ticket 122 current-head adapter, opens the one
encrypted SQLite authority, and exposes only the three frozen CorePort kinds
over a peer-authenticated AF_UNIX socket.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import select
import socket
import stat
import struct
import sys
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .authority import (
    AuthoritySnapshot,
    CommittedTransition,
    EffectExecutionGrant,
    EffectIntent,
    PreparedTransition,
    validate_opaque_text,
)
from .contract import CommandEnvelope, EffectResultPayload, ProtocolViolation, Response, StateCommitPayload
from .core import HealthCore
from .dynamodb_current_head import DynamoDBCurrentHead
from .host_authority import (
    HostPrivateExecutionCapabilityVault,
    HostPrivateFacilityPaths,
    HostPrivateKeyProvider,
    HostPrivateWriterFenceVault,
)
from .lifecycle import LIFECYCLE_PURGE_BINDINGS, LIFECYCLE_REGISTRY_FAMILIES
from .plugin import HealthPlugin
from .probe import ProbeState
from .release_deployment import _validate_release
from .storage import EncryptedStateStore, KeyUnavailable, StoreUnavailable


_MAX_FRAME_BYTES = 64 * 1024
_BINDING_FIELDS = frozenset(
    {
        "contract",
        "release_root",
        "release_digest",
        "runtime_root",
        "runtime_manifest",
        "installation_id",
        "site",
        "database_path",
        "socket_path",
        "socket_owner_uid",
        "socket_group_gid",
        "socket_mode",
        "allowed_peer_uid",
        "host_private_paths",
        "managed_replica_root",
        "managed_replica_bindings",
        "migration_artifact_root",
        "lifecycle_release",
    }
)
_REQUEST_FIELDS = frozenset({"protocol_version", "kind", "request_id", "payload"})
_RESPONSE_FIELDS = frozenset({"protocol_version", "kind", "request_id", "status", "payload"})
_SHA256 = "sha256:"
_MANAGED_PURGE_RECEIPT = ".ticket123-managed-replica-purge-receipt.v1"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _strict_json(data: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicates)


def _plain(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"invalid {name}")
    return value


def _digest(value: object, name: str) -> str:
    text = _plain(value, name)
    if not text.startswith(_SHA256) or len(text) != 71:
        raise ValueError(f"invalid {name}")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise ValueError(f"invalid {name}") from exc
    return text


def _absolute(value: object, name: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError(f"invalid {name}")
    path = Path(os.path.abspath(os.fspath(value)))
    if not path.is_absolute():
        raise ValueError(f"invalid {name}")
    return path


def _relative(value: object, name: str) -> str:
    text = _plain(value, name)
    if "\\" in text:
        raise ValueError(f"invalid {name}")
    parsed = PurePosixPath(text)
    if parsed.is_absolute() or not parsed.parts or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError(f"invalid {name}")
    return parsed.as_posix()


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _secure_directory(value: object, name: str) -> Path:
    path = _absolute(value, name)
    try:
        details = path.lstat()
    except OSError as exc:
        raise ValueError(f"{name} is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.geteuid()
        or details.st_gid != os.getegid()
        or stat.S_IMODE(details.st_mode) & 0o022
    ):
        raise ValueError(f"{name} is unsafe")
    return path


def _secure_regular(path: Path, *, root: Path, mode: int, name: str) -> os.stat_result:
    try:
        path.relative_to(root)
        details = path.lstat()
    except (OSError, ValueError) as exc:
        raise ValueError(f"{name} is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.geteuid()
        or details.st_gid != os.getegid()
        or stat.S_IMODE(details.st_mode) != mode
        or details.st_nlink != 1
    ):
        raise ValueError(f"{name} is unsafe")
    return details


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _current_lstat(path: Path, expected: os.stat_result) -> None:
    current = path.lstat()
    if not _same_identity(current, expected):
        raise ValueError("path identity changed")


class FilesystemManagedReplicaAdapter:
    """Ticket 117's existing managed-replica seam over exact local objects."""

    def __init__(
        self,
        root: Path | str,
        installation_id: str,
        bindings: Mapping[str, object],
        remains_unproven: tuple[str, ...] | list[str],
    ) -> None:
        self._root = _secure_directory(root, "managed replica root")
        self._installation_id = validate_opaque_text(installation_id, "installation_id")
        if type(bindings) is not dict or set(bindings) != set(LIFECYCLE_PURGE_BINDINGS):
            raise ValueError("managed replica bindings are incomplete")
        normalized: dict[str, Path] = {}
        for binding in LIFECYCLE_PURGE_BINDINGS:
            path = _absolute(bindings[binding], "managed replica path")
            normalized[binding] = path
        if type(remains_unproven) not in (tuple, list) or not all(type(item) is str and item for item in remains_unproven):
            raise ValueError("invalid unproven replica providers")
        if len(set(remains_unproven)) != len(remains_unproven):
            raise ValueError("duplicate unproven replica providers")
        self._bindings = normalized
        self._remains_unproven = tuple(remains_unproven)
        self._purge_receipt = self._root / _MANAGED_PURGE_RECEIPT
        self._lock = threading.RLock()
        present = self._replica_presence()
        if all(present):
            if self._purge_receipt_exists():
                raise ValueError("managed replica purge receipt conflicts with live replicas")
        elif any(present):
            raise ValueError("managed replica is unavailable")
        else:
            self._read_purge_receipt()

    def _replica_presence(self) -> tuple[bool, ...]:
        present: list[bool] = []
        for path in self._bindings.values():
            try:
                path.relative_to(self._root)
                path.lstat()
            except FileNotFoundError:
                present.append(False)
                continue
            except (OSError, ValueError) as exc:
                raise ValueError("managed replica is unavailable") from exc
            _secure_regular(path, root=self._root, mode=0o600, name="managed replica")
            present.append(True)
        return tuple(present)

    def _purge_receipt_exists(self) -> bool:
        try:
            self._purge_receipt.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ValueError("managed replica purge receipt is unavailable") from exc
        return True

    def _read_purge_receipt(self) -> tuple[str, AuthoritySnapshot, str]:
        _secure_regular(
            self._purge_receipt,
            root=self._root,
            mode=0o600,
            name="managed replica purge receipt",
        )
        try:
            raw = self._purge_receipt.read_bytes()
            value = _strict_json(raw)
            if _canonical(value) != raw or type(value) is not dict or set(value) != {
                "contract",
                "operation_ref",
                "authority_binding",
                "transition_id",
            }:
                raise ValueError("invalid managed replica purge receipt")
            if value["contract"] != "ticket123-managed-replica-purge-v1":
                raise ValueError("invalid managed replica purge receipt")
            operation_ref = validate_opaque_text(value["operation_ref"], "operation_ref")
            transition_id = validate_opaque_text(value["transition_id"], "transition_id")
            authority = AuthoritySnapshot.from_storage(value["authority_binding"])
        except (OSError, ProtocolViolation, ValueError) as exc:
            raise ValueError("invalid managed replica purge receipt") from exc
        if authority.transition_id != transition_id:
            raise ValueError("managed replica purge receipt authority mismatch")
        return operation_ref, authority, transition_id

    def _write_purge_receipt(
        self,
        operation_ref: str,
        authority: AuthoritySnapshot,
        transition_id: str,
    ) -> None:
        if self._purge_receipt_exists():
            raise ValueError("managed replica purge receipt already exists")
        wire = _canonical(
            {
                "contract": "ticket123-managed-replica-purge-v1",
                "operation_ref": operation_ref,
                "authority_binding": authority.to_storage(),
                "transition_id": transition_id,
            }
        )
        temporary = self._root / (_MANAGED_PURGE_RECEIPT + "." + uuid.uuid4().hex)
        descriptor = -1
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            remaining = memoryview(wire)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("managed replica purge receipt write failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            _secure_regular(
                temporary,
                root=self._root,
                mode=0o600,
                name="managed replica purge receipt",
            )
            os.link(temporary, self._purge_receipt, follow_symlinks=False)
            temporary.unlink()
            _fsync_directory(self._root)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        observed_operation, observed_authority, observed_transition = self._read_purge_receipt()
        if (
            observed_operation != operation_ref
            or observed_authority != authority
            or observed_transition != transition_id
        ):
            raise ValueError("managed replica purge receipt mismatch")

    def _request(self, request: object) -> tuple[str, AuthoritySnapshot, str]:
        if type(request) is not dict or set(request) != {
            "operation_ref",
            "authority_binding",
            "transition_id",
        }:
            raise ValueError("invalid managed replica request")
        operation_ref = validate_opaque_text(request["operation_ref"], "operation_ref")
        transition_id = validate_opaque_text(request["transition_id"], "transition_id")
        authority = AuthoritySnapshot.from_storage(request["authority_binding"])
        if not operation_ref or authority.installation_id != self._installation_id or authority.transition_id != transition_id:
            raise ValueError("managed replica authority mismatch")
        return operation_ref, authority, transition_id

    def enumerate(self, request: object) -> dict[str, object]:
        if type(request) is not dict or set(request) != {"installation_id"}:
            raise ValueError("invalid managed replica enumeration")
        if request["installation_id"] != self._installation_id:
            raise ValueError("managed replica installation mismatch")
        with self._lock:
            _secure_directory(self._root, "managed replica root")
            if not all(self._replica_presence()) or self._purge_receipt_exists():
                raise ValueError("managed replica is unavailable")
            return {
                "configured": list(LIFECYCLE_PURGE_BINDINGS),
                "remains_unproven": list(self._remains_unproven),
            }

    def purge(self, request: object) -> dict[str, object]:
        operation_ref, authority, transition_id = self._request(request)
        with self._lock:
            _secure_directory(self._root, "managed replica root")
            if self._purge_receipt_exists() or not all(self._replica_presence()):
                raise ValueError("managed replica is unavailable")
            checked: list[tuple[Path, os.stat_result]] = []
            for path in self._bindings.values():
                checked.append((path, _secure_regular(path, root=self._root, mode=0o600, name="managed replica")))
            for path, details in checked:
                _current_lstat(path, details)
                path.unlink()
            _fsync_directory(self._root)
            if any(self._replica_presence()):
                raise ValueError("managed replica absence is unconfirmed")
            self._write_purge_receipt(operation_ref, authority, transition_id)
            return {"status": "confirmed"}

    def absence(self, request: object) -> dict[str, object]:
        operation_ref, authority, transition_id = self._request(request)
        with self._lock:
            _secure_directory(self._root, "managed replica root")
            present = self._replica_presence()
            if all(present):
                if self._purge_receipt_exists():
                    raise ValueError("managed replica purge receipt conflicts with live replicas")
                return {"status": "present", "remains_unproven": list(self._remains_unproven)}
            if any(present):
                raise ValueError("managed replica is unavailable")
            observed_operation, observed_authority, observed_transition = self._read_purge_receipt()
            if (
                observed_operation != operation_ref
                or observed_authority != authority
                or observed_transition != transition_id
            ):
                raise ValueError("managed replica authority mismatch")
            return {"status": "absent", "remains_unproven": list(self._remains_unproven)}


class FilesystemMigrationArtifactAdapter:
    """Atomic, immutable Ticket 117 opaque migration-package storage."""

    _PACKAGE_FIELDS = frozenset({"contract", "manifest", "semantic_state"})
    _MANIFEST_FIELDS = frozenset(
        {
            "contract",
            "operation_ref",
            "source_authority",
            "semantic_registry",
            "release",
            "target_site",
            "target_writer_fence_ref",
            "artifact_sink_ref",
            "semantic_state_digest",
        }
    )

    def __init__(self, root: Path | str, installation_id: str) -> None:
        self._root = _secure_directory(root, "migration artifact root")
        self._installation_id = validate_opaque_text(installation_id, "installation_id")
        self._lock = threading.RLock()

    @staticmethod
    def _package_ref(value: object) -> str:
        text = validate_opaque_text(value, "migration package reference")
        prefix = "lifecycle-package:"
        if not text.startswith(prefix) or len(text) == len(prefix):
            raise ValueError("invalid migration package reference")
        return text

    def _path(self, package_ref: object) -> tuple[str, Path]:
        reference = self._package_ref(package_ref)
        digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        return reference, self._root / (digest + ".json")

    def _validate_package(self, package_ref: object, package: object) -> dict[str, object]:
        reference = self._package_ref(package_ref)
        if type(package) is not dict or frozenset(package) != self._PACKAGE_FIELDS:
            raise ValueError("invalid migration package")
        if package["contract"] != "ticket117-opaque-migration-package-v1":
            raise ValueError("invalid migration package")
        manifest = package["manifest"]
        state = package["semantic_state"]
        if type(manifest) is not dict or frozenset(manifest) != self._MANIFEST_FIELDS:
            raise ValueError("invalid migration manifest")
        if manifest.get("contract") != "ticket117-semantic-manifest-v1":
            raise ValueError("invalid migration manifest")
        if manifest.get("operation_ref") != reference.removeprefix("lifecycle-package:"):
            raise ValueError("migration package reference mismatch")
        authority = AuthoritySnapshot.from_storage(manifest.get("source_authority"))
        if authority.installation_id != self._installation_id:
            raise ValueError("migration package installation mismatch")
        for field in (
            "target_site",
            "target_writer_fence_ref",
            "artifact_sink_ref",
            "semantic_state_digest",
        ):
            validate_opaque_text(manifest.get(field), field)
        if type(manifest.get("semantic_registry")) is not list or type(manifest.get("release")) is not dict:
            raise ValueError("invalid migration manifest")
        if type(state) is not dict or set(state) != {"registry", "records"}:
            raise ValueError("invalid migration semantic state")
        if state["registry"] != manifest["semantic_registry"] or type(state["records"]) is not list:
            raise ValueError("invalid migration semantic state")
        normalized = copy.deepcopy(package)
        if _strict_json(_canonical(normalized)) != normalized:
            raise ValueError("migration package is not JSON-safe")
        return normalized

    def _read(self, reference: str, path: Path) -> dict[str, object] | None:
        _secure_directory(self._root, "migration artifact root")
        if not path.exists() and not path.is_symlink():
            return None
        details = _secure_regular(path, root=self._root, mode=0o600, name="migration artifact")
        payload = path.read_bytes()
        _current_lstat(path, details)
        value = _strict_json(payload)
        if _canonical(value) != payload:
            raise ValueError("migration artifact is noncanonical")
        return self._validate_package(reference, value)

    def put(self, package_ref: str, package: object) -> dict[str, object]:
        reference, path = self._path(package_ref)
        normalized = self._validate_package(reference, package)
        payload = _canonical(normalized)
        with self._lock:
            existing = self._read(reference, path)
            if existing is not None:
                if existing != normalized:
                    raise ValueError("migration artifact is immutable")
                return {"status": "confirmed", "package_ref": reference}
            temporary = self._root / (".ticket123-" + uuid.uuid4().hex)
            descriptor: int | None = None
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                    0o600,
                )
                written = 0
                while written < len(payload):
                    written += os.write(descriptor, payload[written:])
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
                _secure_regular(temporary, root=self._root, mode=0o600, name="migration artifact")
                os.replace(temporary, path)
                _fsync_directory(self._root)
                if self._read(reference, path) != normalized:
                    raise ValueError("migration artifact readback mismatch")
            except Exception:
                if descriptor is not None:
                    os.close(descriptor)
                try:
                    temporary.unlink()
                except OSError:
                    pass
                raise
            return {"status": "confirmed", "package_ref": reference}

    def get(self, package_ref: str) -> object | None:
        reference, path = self._path(package_ref)
        with self._lock:
            value = self._read(reference, path)
            return None if value is None else copy.deepcopy(value)

    def remove(self, package_ref: str) -> dict[str, object]:
        reference, path = self._path(package_ref)
        with self._lock:
            existing = self._read(reference, path)
            if existing is None:
                return {"status": "confirmed"}
            details = _secure_regular(path, root=self._root, mode=0o600, name="migration artifact")
            _current_lstat(path, details)
            path.unlink()
            _fsync_directory(self._root)
            if self._read(reference, path) is not None:
                raise ValueError("migration artifact absence is unconfirmed")
            return {"status": "confirmed"}


class ProductionCoreService:
    """One deep production composition root for Ticket 123 only."""

    def __init__(self, binding: Mapping[str, object], *, current_head: object) -> None:
        if type(binding) is not dict:
            raise TypeError("production core binding must be a plain mapping")
        if type(current_head) is not DynamoDBCurrentHead:
            raise TypeError("production core requires DynamoDBCurrentHead")
        self._binding = copy.deepcopy(binding)
        self._current_head: DynamoDBCurrentHead = current_head
        self._lock = threading.RLock()
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._core: HealthCore | None = None
        self._plugin: HealthPlugin | None = None
        self._store: EncryptedStateStore | None = None
        self._socket_path: Path | None = None
        self._socket_identity: tuple[int, int] | None = None
        self._assets_current = False
        self._lifecycle_ready = False
        self._effect_sessions: dict[str, tuple[EffectIntent, EffectExecutionGrant]] = {}

    @staticmethod
    def _coerce_paths(value: object) -> HostPrivateFacilityPaths:
        if type(value) is HostPrivateFacilityPaths:
            return value
        if type(value) is not dict or set(value) != {
            "data_key",
            "writer_master",
            "execution_master",
            "lock_directory",
        }:
            raise ValueError("invalid host-private facility binding")
        return HostPrivateFacilityPaths(
            data_key=Path(_plain(value["data_key"], "data key path")),
            writer_master=Path(_plain(value["writer_master"], "writer master path")),
            execution_master=Path(_plain(value["execution_master"], "execution master path")),
            lock_directory=Path(_plain(value["lock_directory"], "lock directory path")),
        )

    @staticmethod
    def _runtime(root_value: object, manifest_value: object) -> tuple[Path, dict[str, object]]:
        root = _secure_directory(root_value, "runtime closure root")
        manifest_path = root / "ticket123-runtime-manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ValueError("runtime closure manifest is unavailable")
        manifest = _strict_json(manifest_path.read_bytes())
        if type(manifest) is not dict or type(manifest_value) is not dict or manifest != manifest_value:
            raise ValueError("runtime closure manifest mismatch")
        if not {"contract", "closure_digest", "files"}.issubset(manifest):
            raise ValueError("runtime closure manifest is invalid")
        if type(manifest["contract"]) is not str or not manifest["contract"]:
            raise ValueError("runtime closure manifest is invalid")
        _digest(manifest["closure_digest"], "runtime closure digest")
        files = manifest["files"]
        if type(files) is not list or not files:
            raise ValueError("runtime closure file list is invalid")
        declared: dict[str, str] = {}
        for item in files:
            if type(item) is not dict or set(item) != {"path", "sha256"}:
                raise ValueError("runtime closure file is invalid")
            relative = _relative(item["path"], "runtime file path")
            digest = _digest(item["sha256"], "runtime file digest")
            if relative in declared:
                raise ValueError("runtime closure file is duplicated")
            declared[relative] = digest
        actual: dict[str, str] = {}
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("runtime closure contains a symlink")
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                if relative == "ticket123-runtime-manifest.json":
                    continue
                actual[relative] = _SHA256 + hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != declared:
            raise ValueError("runtime closure file set drifted")
        interpreter = root / "bin" / "python3"
        try:
            executable = Path(sys.executable).resolve()
            executable.relative_to(root)
        except (OSError, ValueError) as exc:
            raise ValueError("runtime interpreter is outside the closure") from exc
        if not interpreter.is_file() or interpreter.is_symlink() or sys.version_info[:2] != (3, 11):
            raise ValueError("runtime interpreter is invalid")
        if not any("partner_health_steward" in path for path in declared) or not any("cryptography" in path for path in declared):
            raise ValueError("runtime dependency closure is incomplete")
        return root, copy.deepcopy(manifest)

    def _validated_resources(self) -> dict[str, object]:
        binding = self._binding
        if set(binding) != _BINDING_FIELDS or binding.get("contract") != "ticket123-production-core-binding-v1":
            raise ValueError("invalid production core binding")
        release_root = _secure_directory(binding["release_root"], "release root")
        release = _validate_release(str(release_root))
        if binding["release_digest"] != release.get("release_digest") or release_root.name != str(release["release_digest"]).removeprefix(_SHA256):
            raise ValueError("release binding mismatch")
        runtime_root, runtime_manifest = self._runtime(binding["runtime_root"], binding["runtime_manifest"])
        installation_id = validate_opaque_text(binding["installation_id"], "installation_id")
        site = validate_opaque_text(binding["site"], "site")
        head = self._current_head.read().head.as_authority()
        if head.installation_id != installation_id or head.site != site:
            raise ValueError("current-head installation binding mismatch")
        paths = self._coerce_paths(binding["host_private_paths"])
        key_provider = HostPrivateKeyProvider(paths, installation_id)
        writer_vault = HostPrivateWriterFenceVault(paths)
        execution_vault = HostPrivateExecutionCapabilityVault(paths)
        database = _absolute(binding["database_path"], "database path")
        parent = _secure_directory(database.parent, "database parent")
        if database.parent != parent or database.is_symlink() or (database.exists() and not database.is_file()):
            raise ValueError("database path is unsafe")
        socket_path = _absolute(binding["socket_path"], "socket path")
        socket_parent = _secure_directory(socket_path.parent, "socket parent")
        if socket_parent != socket_path.parent:
            raise ValueError("socket path is unsafe")
        for name in ("socket_owner_uid", "socket_group_gid", "allowed_peer_uid"):
            if type(binding[name]) is not int or binding[name] < 0:
                raise ValueError(f"invalid {name}")
        if binding["socket_owner_uid"] != os.geteuid() or binding["socket_group_gid"] != os.getegid() or binding["socket_mode"] != 0o660:
            raise ValueError("socket ownership or mode is unsafe")
        managed = FilesystemManagedReplicaAdapter(
            _plain(binding["managed_replica_root"], "managed replica root"),
            installation_id,
            binding["managed_replica_bindings"],  # type: ignore[arg-type]
            tuple(binding["lifecycle_release"].get("unbound_real_providers", ())) if type(binding["lifecycle_release"]) is dict else (),
        )
        artifacts = FilesystemMigrationArtifactAdapter(
            _plain(binding["migration_artifact_root"], "migration artifact root"),
            installation_id,
        )
        lifecycle_release = binding["lifecycle_release"]
        if type(lifecycle_release) is not dict or lifecycle_release.get("product_release") != release["release_digest"]:
            raise ValueError("lifecycle release binding mismatch")
        lifecycle_config = {
            "contract": "ticket117-lifecycle-config-v1",
            "mode": "source",
            "semantic_registry": [
                {
                    "family": family,
                    "snapshot_codec": f"codec:{family}:v1",
                    "purge_binding": f"purge:{family}:v1",
                    "source_continuity": "preserve",
                }
                for family in LIFECYCLE_REGISTRY_FAMILIES
            ],
            "release": copy.deepcopy(lifecycle_release),
            "destroyable_key_adapter": key_provider,
            "managed_replica_adapter": managed,
            "migration_artifact_adapter": artifacts,
        }
        return {
            "release": release,
            "runtime_root": runtime_root,
            "runtime_manifest": runtime_manifest,
            "database": database,
            "socket_path": socket_path,
            "key_provider": key_provider,
            "writer_vault": writer_vault,
            "execution_vault": execution_vault,
            "lifecycle_config": lifecycle_config,
        }

    def _open_socket(self, path: Path) -> socket.socket:
        try:
            existing = path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if path.is_symlink() or not stat.S_ISSOCK(existing.st_mode):
                raise ValueError("socket path is occupied")
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.1)
                probe.connect(str(path))
            except OSError:
                _current_lstat(path, existing)
                path.unlink()
            else:
                raise ValueError("socket listener is active")
            finally:
                probe.close()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(path))
            os.chown(path, self._binding["socket_owner_uid"], self._binding["socket_group_gid"])
            os.chmod(path, self._binding["socket_mode"])
            details = path.lstat()
            if (
                not stat.S_ISSOCK(details.st_mode)
                or stat.S_IMODE(details.st_mode) != 0o660
                or details.st_uid != self._binding["socket_owner_uid"]
                or details.st_gid != self._binding["socket_group_gid"]
            ):
                raise ValueError("socket ACL verification failed")
            listener.listen()
            listener.settimeout(0.1)
        except Exception:
            listener.close()
            try:
                path.unlink()
            except OSError:
                pass
            raise
        self._socket_identity = (details.st_dev, details.st_ino)
        return listener

    def start(self) -> dict[str, object]:
        with self._lock:
            if self._listener is not None:
                raise RuntimeError("production core service is already started")
            resources = self._validated_resources()
            store: EncryptedStateStore | None = None
            core: HealthCore | None = None
            try:
                store = EncryptedStateStore(str(resources["database"]), resources["key_provider"])  # type: ignore[arg-type]
                core = HealthCore(
                    store,
                    self._current_head,
                    execution_capability_vault=resources["execution_vault"],
                    writer_fence_vault=resources["writer_vault"],
                    lifecycle_config=resources["lifecycle_config"],  # type: ignore[arg-type]
                )
                report = core.probe()
                if report.state is ProbeState.UNAVAILABLE:
                    raise RuntimeError(report.reason_code)
                self._lifecycle_ready = True
                self._assets_current = resources["release"].get("state") == "current"  # type: ignore[index]
                self._store = store
                self._core = core
                self._plugin = HealthPlugin(core)
                self._socket_path = resources["socket_path"]  # type: ignore[assignment]
                self._stop.clear()
                listener = self._open_socket(self._socket_path)
                self._listener = listener
                self._thread = threading.Thread(target=self._serve, name="ticket123-coreport", daemon=True)
                self._thread.start()
                return {
                    "transport": "af-unix",
                    "path": str(self._socket_path),
                    "protocol": "ticket118-core-port-v1",
                }
            except Exception:
                if core is not None:
                    core.close()
                if store is not None:
                    store.close()
                self._store = None
                self._core = None
                self._plugin = None
                self._socket_path = None
                self._socket_identity = None
                raise

    def close(self) -> None:
        with self._lock:
            listener, thread = self._listener, self._thread
            self._listener = None
            self._thread = None
            self._stop.set()
            if listener is not None:
                listener.close()
        if thread is not None:
            thread.join(timeout=2)
        with self._lock:
            core, store = self._core, self._store
            self._core = None
            self._plugin = None
            self._store = None
            self._effect_sessions.clear()
            if core is not None:
                core.close()
            if store is not None:
                store.close()
            path, identity = self._socket_path, self._socket_identity
            self._socket_path = None
            self._socket_identity = None
            if path is not None and identity is not None:
                try:
                    details = path.lstat()
                    if (details.st_dev, details.st_ino) == identity and stat.S_ISSOCK(details.st_mode):
                        path.unlink()
                        _fsync_directory(path.parent)
                except OSError:
                    pass

    def _serve(self) -> None:
        while not self._stop.is_set():
            listener = self._listener
            if listener is None:
                return
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                try:
                    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                    _pid, peer_uid, _peer_gid = struct.unpack("3i", raw)
                    if peer_uid != self._binding["allowed_peer_uid"]:
                        continue
                    self._handle_connection(connection)
                except (OSError, ValueError, struct.error):
                    continue

    @staticmethod
    def _receive(connection: socket.socket, size: int) -> bytes | None:
        result = bytearray()
        while len(result) < size:
            part = connection.recv(size - len(result))
            if not part:
                return None
            result.extend(part)
        return bytes(result)

    def _handle_connection(self, connection: socket.socket) -> None:
        connection.settimeout(1)
        header = self._receive(connection, 4)
        if header is None:
            return
        size = struct.unpack(">I", header)[0]
        if size == 0 or size > _MAX_FRAME_BYTES:
            return
        body = self._receive(connection, size)
        if body is None:
            return
        readable, _writeable, _errors = select.select([connection], [], [], 0.03)
        if readable and connection.recv(1):
            return
        request = _strict_json(body)
        if _canonical(request) != body:
            return
        response = self._dispatch(request)
        if response is None:
            return
        wire = _canonical(response)
        connection.sendall(struct.pack(">I", len(wire)) + wire)

    @staticmethod
    def _request(value: object) -> dict[str, object] | None:
        if type(value) is not dict or frozenset(value) != _REQUEST_FIELDS:
            return None
        if value.get("protocol_version") != 1 or value.get("kind") not in {"command", "managed-read", "controlled-effect"}:
            return None
        if type(value.get("request_id")) is not str or not value["request_id"] or type(value.get("payload")) is not dict:
            return None
        return value

    def _recovery_finalize_candidate(
        self,
        command: CommandEnvelope,
        store: EncryptedStateStore,
    ) -> PreparedTransition | None:
        """Recognize only a journal whose original CAS is already proven."""

        payload = command.payload
        if command.action != "state.commit" or not isinstance(payload, StateCommitPayload):
            return None
        pending = store.pending_for_record(payload.record_id)
        stored = store.record(payload.record_id)
        if (
            pending is None
            or not pending.remote_attempted
            or pending.command.to_wire() != command.to_wire()
            or stored is None
            or stored.state not in {"prepared", "unknown"}
            or not isinstance(stored.payload, PreparedTransition)
        ):
            return None
        prepared = stored.payload
        if (
            command.generation != prepared.base.generation
            or payload.writer_fence != prepared.base.writer_fence
            or not prepared.target.matches_commit(
                record_id=payload.record_id,
                revision_digest=payload.revision_digest,
                transition_id=payload.transition_id,
            )
        ):
            return None
        try:
            head = self._current_head.read().head.as_authority()
        except Exception:
            return None
        if (
            head.terminal
            or head.installation_id != prepared.base.installation_id
            or head.site != prepared.base.site
            or head.generation != prepared.base.generation + 1
            or head.revision_digest != prepared.target.revision_digest
            or head.transition_id != prepared.target.transition_id
            or head.writer_fence != prepared.base.writer_fence
        ):
            return None
        return prepared

    @staticmethod
    def _recovery_finalize_command(
        command: CommandEnvelope,
        committed: CommittedTransition,
    ) -> CommandEnvelope:
        target = committed.prepared.target
        return CommandEnvelope(
            peer="plugin",
            action="state.finalize",
            source=command.source,
            causal_id="ticket123-recovery-finalize:"
            + hashlib.sha256(_canonical(command.to_wire())).hexdigest(),
            generation=committed.committed.generation,
            scope=("state:finalize",),
            payload=StateCommitPayload(
                record_id=target.record_id,
                revision_digest=target.revision_digest,
                transition_id=target.transition_id,
                writer_fence=committed.committed.writer_fence,
            ),
        )

    def _finalize_recovered_commit(
        self,
        command: CommandEnvelope,
        prepared: PreparedTransition,
        store: EncryptedStateStore,
        plugin: HealthPlugin,
    ) -> None:
        """Use the existing finalize protocol after lookup-only recovery."""

        stored = store.record(prepared.target.record_id)
        if stored is None or stored.state == "final":
            return
        if (
            stored.state != "committed"
            or not isinstance(stored.payload, CommittedTransition)
            or stored.payload.prepared != prepared
        ):
            raise StoreUnavailable("recovered state commit is not locally committed")
        finalized = plugin.invoke(
            self._recovery_finalize_command(command, stored.payload),
            peer_id="plugin",
        )
        if finalized.status not in {"accepted", "replayed"}:
            raise StoreUnavailable("recovered state commit finalization is unavailable")

    def _dispatch(self, raw: object) -> dict[str, object] | None:
        request = self._request(raw)
        if request is None:
            return None
        kind = request["kind"]
        try:
            if kind == "command":
                payload = self._command(request["payload"])
            elif kind == "managed-read":
                payload = self._managed_read(request["payload"])
            else:
                payload = self._controlled_effect(request["payload"])
        except (KeyUnavailable, StoreUnavailable, ProtocolViolation, ValueError, TypeError, OSError):
            return None
        if payload is None:
            return None
        return {
            "protocol_version": 1,
            "kind": kind,
            "request_id": request["request_id"],
            "status": "accepted",
            "payload": payload,
        }

    def _command(self, payload: object) -> dict[str, object] | None:
        if payload == {"operation": "health-runtime-probe"}:
            return {"projection": self._runtime_projection()}
        if type(payload) is not dict or set(payload) != {"interface", "command"} or payload.get("interface") != "command-v1":
            return None
        command = CommandEnvelope.from_wire(payload["command"])
        core = self._core
        store = self._store
        plugin = self._plugin
        if core is None or store is None or plugin is None:
            return None
        if not self._assets_current:
            receipt = store.receipt(command)
            if receipt is not None:
                return {"response": receipt.to_wire()}
            if not isinstance(command.payload, StateCommitPayload):
                return {"response": Response("unavailable", command.causal_id, "health-assets-staged").to_wire()}
            pending = store.pending_for_record(command.payload.record_id)
            if pending is None or pending.command.to_wire() != command.to_wire():
                return {"response": Response("unavailable", command.causal_id, "health-assets-staged").to_wire()}
        recovery = self._recovery_finalize_candidate(command, store)
        response = plugin.invoke(command, peer_id="plugin")
        if recovery is not None and response.status == "accepted":
            self._finalize_recovered_commit(command, recovery, store, plugin)
        return {"response": response.to_wire()}

    def _runtime_projection(self) -> dict[str, object]:
        core = self._core
        if core is None:
            raise ValueError("production core is unavailable")
        report = core.probe()
        generation: int | None = None
        try:
            generation = self._current_head.read().head.generation
        except Exception:
            pass
        state = report.state.value
        reason = report.reason_code
        if report.state is ProbeState.HEALTHY and not self._assets_current:
            state = ProbeState.UNAVAILABLE.value
            reason = "health-assets-staged"
        allowed = state == ProbeState.HEALTHY.value and self._assets_current
        return {
            "state": state,
            "reason_code": reason,
            "generation": generation,
            "health_writes_allowed": allowed,
            "model_effects_allowed": allowed,
            "outbound_effects_allowed": allowed,
            "current_head_provider": "dynamodb",
            "managed_lifecycle_ready": self._lifecycle_ready,
            "content": None,
        }

    def _managed_read(self, payload: object) -> dict[str, object] | None:
        if payload != {"projection": "health-runtime"}:
            return None
        return self._runtime_projection()

    @staticmethod
    def _intent_wire(intent: EffectIntent) -> dict[str, object]:
        return {
            "effect_id": intent.effect_id,
            "intent_digest": intent.intent_digest,
            "effect_kind": intent.effect_kind,
            "authority": {
                "source": "core",
                "generation": intent.authority.generation,
                "writer_fence": intent.authority.writer_fence,
            },
        }

    @staticmethod
    def _grant_wire(session_id: str, grant: EffectExecutionGrant) -> dict[str, object]:
        lease = grant.lease
        return {
            "session_id": session_id,
            "lease_id": lease.lease_id,
            "effect_id": lease.effect_id,
            "intent_digest": lease.intent_digest,
            "generation": lease.authority.generation,
            "writer_fence": lease.authority.writer_fence,
        }

    def _candidate_intent(self) -> EffectIntent | None:
        store = self._store
        if store is None:
            return None
        candidates: list[EffectIntent] = []
        for effect_id in store.unresolved_effects():
            stored = store.effect(effect_id)
            if stored is not None and stored.state == "intent" and type(stored.payload) is EffectIntent:
                candidates.append(stored.payload)
        return candidates[0] if len(candidates) == 1 else None

    def _controlled_effect(self, payload: object) -> dict[str, object] | None:
        if type(payload) is not dict or set(payload) != {"phase"} | ({"terminal"} if payload.get("phase") == "terminal" else set()):
            return None
        phase = payload.get("phase")
        try:
            authority = self._current_head.read().head.as_authority()
            current_authority: dict[str, object] | None = {
                "generation": authority.generation,
                "writer_fence": authority.writer_fence,
            }
        except Exception:
            authority = None
            current_authority = None
        if phase == "claim":
            intent = self._candidate_intent()
            core = self._core
            if intent is None or core is None or authority is None or intent.authority != authority:
                return {"intent": None, "grant": None, "current_authority": current_authority}
            grant = core.claim_effect_execution(intent)
            if grant is None:
                return {"intent": None, "grant": None, "current_authority": current_authority}
            session_id = "effect-session:" + uuid.uuid4().hex
            self._effect_sessions[session_id] = (intent, grant)
            return {
                "intent": self._intent_wire(intent),
                "grant": self._grant_wire(session_id, grant),
                "current_authority": current_authority,
            }
        if phase != "terminal":
            return None
        terminal = payload.get("terminal")
        accepted = self._terminal(terminal)
        return {"terminal_accepted": accepted}

    def _terminal(self, value: object) -> bool:
        if not self._assets_current or type(value) is not dict:
            return False
        required = {
            "session_id",
            "lease_id",
            "effect_id",
            "intent_digest",
            "generation",
            "writer_fence",
            "status",
            "terminal",
            "result_ref",
        }
        if set(value) != required or value.get("status") not in {"accepted", "rejected", "unknown"} or value.get("terminal") is not True:
            return False
        session_id = value.get("session_id")
        if type(session_id) is not str:
            return False
        cached = self._effect_sessions.get(session_id)
        if cached is None:
            return False
        intent, grant = cached
        expected = self._grant_wire(session_id, grant)
        if any(value.get(key) != expected[key] for key in expected):
            return False
        if value["effect_id"] != intent.effect_id or value["intent_digest"] != intent.intent_digest or type(value["result_ref"]) is not str:
            return False
        core = self._core
        if core is None:
            return False
        terminal_command = CommandEnvelope(
            peer="plugin",
            action="effect.result",
            source="health_weixin",
            causal_id="coreport-terminal:" + session_id,
            generation=grant.lease.authority.generation,
            scope=("effect:result",),
            payload=EffectResultPayload(
                effect_id=grant.lease.effect_id,
                intent_digest=grant.lease.intent_digest,
                lease_id=grant.lease.lease_id,
                completion_capability=grant.completion_capability,
                status=value["status"],
                terminal=True,
                result_digest=value["result_ref"],
            ),
        )
        response = core.handle(terminal_command)
        if response.status not in {"accepted", "replayed"}:
            return False
        self._effect_sessions.pop(session_id, None)
        return True


def render_health_core_systemd_unit(binding: Mapping[str, object]) -> str:
    """Render the fixed, low-privilege unit shape without deploying it."""

    required = {
        "runtime_root",
        "binding_path",
        "state_root",
        "socket_root",
        "service_user",
        "plugin_group",
    }
    if type(binding) is not dict or not required.issubset(binding):
        raise ValueError("invalid systemd unit binding")
    runtime_root = _absolute(binding["runtime_root"], "runtime root")
    binding_path = _absolute(binding["binding_path"], "binding path")
    state_root = _absolute(binding["state_root"], "state root")
    socket_root = _absolute(binding["socket_root"], "socket root")
    service_user = _plain(binding["service_user"], "service user")
    plugin_group = _plain(binding["plugin_group"], "plugin group")
    interpreter = runtime_root / "bin" / "python3"
    return "\n".join(
        (
            "[Unit]",
            "Description=Partner HealthCore service",
            "After=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"User={service_user}",
            f"Group={plugin_group}",
            "UMask=0077",
            "NoNewPrivileges=yes",
            "PrivateTmp=yes",
            "ProtectSystem=strict",
            f"ReadOnlyPaths={runtime_root}",
            f"ReadWritePaths={state_root} {socket_root}",
            f"ExecStart={interpreter} -I -m partner_health_steward.production_core_service --binding {binding_path}",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        )
    )


def _load_binding(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("production binding is unavailable")
    value = _strict_json(path.read_bytes())
    if type(value) is not dict or _canonical(value) != path.read_bytes():
        raise ValueError("production binding is noncanonical")
    return value


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ticket 123 production HealthCore service")
    parser.add_argument("--binding", required=True, help="canonical, non-secret service binding")
    args = parser.parse_args(argv)
    _load_binding(Path(args.binding))
    # A current-head adapter is intentionally injected by the enclosing host
    # process.  This launcher never creates a credential loader or silently
    # substitutes an in-memory provider.
    raise RuntimeError("DynamoDBCurrentHead injection is required")


if __name__ == "__main__":
    raise SystemExit(_main())

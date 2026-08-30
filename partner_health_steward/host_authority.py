"""Linux host-private authorities for the production health-core process.

The public objects in this module implement the existing key, writer-fence,
and execution-capability interfaces.  Secret material remains in pinned
host-private files and is never included in representations or errors.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final

try:  # Importable on non-Linux hosts so platform gates can report honestly.
    import fcntl
except ImportError:  # pragma: no cover - exercised by the Windows gate host
    fcntl = None  # type: ignore[assignment]

from .authority import (
    AuthoritySnapshot,
    ExecutionCapabilityBinding,
    WriterFenceProof,
    WriterHolderClaim,
    holder_id_for,
    validate_opaque_text,
)


_DATA_TOMBSTONE_CONTRACT: Final = "partner-health-steward/data-key-tombstone"
_DATA_TOMBSTONE_VERSION: Final = 1
_WRITER_NONCE_DOMAIN: Final = b"partner-health-steward/writer-nonce/v1\0"
_WRITER_CAPABILITY_DOMAIN: Final = b"partner-health-steward/writer-capability/v1\0"
_EXECUTION_CAPABILITY_DOMAIN: Final = (
    b"partner-health-steward/execution-capability/v1\0"
)
_MAX_TOMBSTONE_BYTES: Final = 4096


class HostAuthorityUnavailable(RuntimeError):
    """The host-private facility cannot be proven current and safe."""


def _require_linux() -> None:
    if os.name != "posix" or fcntl is None or not hasattr(os, "geteuid"):
        raise HostAuthorityUnavailable("host-private authority unavailable")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_path(value: os.PathLike[str] | str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise TypeError("invalid host-private facility path")
    try:
        return Path(os.path.abspath(os.fspath(value)))
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError("invalid host-private facility path") from exc


def _validate_directory_stat(value: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_gid != os.getegid()
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        raise HostAuthorityUnavailable("host-private directory unavailable")


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


class _DirectoryHandle:
    def __init__(self, path: Path) -> None:
        _require_linux()
        self.path = path
        self._broken = False
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            before = os.stat(path, follow_symlinks=False)
            _validate_directory_stat(before)
            self.fd = os.open(path, flags)
            opened = os.fstat(self.fd)
            _validate_directory_stat(opened)
            if not _same_identity(before, opened):
                raise HostAuthorityUnavailable("host-private directory unavailable")
            self._identity = (opened.st_dev, opened.st_ino)
        except Exception as exc:
            fd = getattr(self, "fd", None)
            if fd is not None:
                os.close(fd)
            if isinstance(exc, HostAuthorityUnavailable):
                raise
            raise HostAuthorityUnavailable(
                "host-private directory unavailable"
            ) from None

    def check_current(self) -> None:
        if self._broken:
            raise HostAuthorityUnavailable("host-private directory unavailable")
        try:
            opened = os.fstat(self.fd)
            current = os.stat(self.path, follow_symlinks=False)
            _validate_directory_stat(opened)
            _validate_directory_stat(current)
            if (
                (opened.st_dev, opened.st_ino) != self._identity
                or not _same_identity(opened, current)
            ):
                raise HostAuthorityUnavailable(
                    "host-private directory unavailable"
                )
        except Exception:
            self._broken = True
            raise HostAuthorityUnavailable(
                "host-private directory unavailable"
            ) from None

    def close(self) -> None:
        fd = getattr(self, "fd", None)
        if fd is not None:
            self.fd = None  # type: ignore[assignment]
            os.close(fd)


def _validate_private_file_stat(value: os.stat_result, *, max_size: int) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_gid != os.getegid()
        or stat.S_IMODE(value.st_mode) != 0o400
        or value.st_nlink != 1
        or value.st_size < 1
        or value.st_size > max_size
    ):
        raise HostAuthorityUnavailable("host-private file unavailable")


def _pread_all(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(fd, size - offset, offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    value = b"".join(chunks)
    if len(value) != size or os.pread(fd, 1, size):
        raise HostAuthorityUnavailable("host-private file unavailable")
    return value


class _PinnedPrivateFile:
    def __init__(self, path: Path, *, max_size: int) -> None:
        _require_linux()
        self.path = path
        self._max_size = max_size
        self._broken = False
        self._directory = _DirectoryHandle(path.parent)
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            before = os.stat(
                path.name,
                dir_fd=self._directory.fd,
                follow_symlinks=False,
            )
            _validate_private_file_stat(before, max_size=max_size)
            self.fd = os.open(path.name, flags, dir_fd=self._directory.fd)
            opened = os.fstat(self.fd)
            _validate_private_file_stat(opened, max_size=max_size)
            if not _same_identity(before, opened):
                raise HostAuthorityUnavailable("host-private file unavailable")
            initial = _pread_all(self.fd, opened.st_size)
            self._identity = (opened.st_dev, opened.st_ino)
            self._content_digest = hashlib.sha256(initial).digest()
        except Exception as exc:
            fd = getattr(self, "fd", None)
            if fd is not None:
                os.close(fd)
            self._directory.close()
            if isinstance(exc, HostAuthorityUnavailable):
                raise
            raise HostAuthorityUnavailable("host-private file unavailable") from None

    def read_current(self) -> bytes:
        if self._broken:
            raise HostAuthorityUnavailable("host-private file unavailable")
        try:
            self._directory.check_current()
            opened = os.fstat(self.fd)
            current = os.stat(
                self.path.name,
                dir_fd=self._directory.fd,
                follow_symlinks=False,
            )
            _validate_private_file_stat(opened, max_size=self._max_size)
            _validate_private_file_stat(current, max_size=self._max_size)
            if (
                (opened.st_dev, opened.st_ino) != self._identity
                or not _same_identity(opened, current)
            ):
                raise HostAuthorityUnavailable("host-private file unavailable")
            value = _pread_all(self.fd, opened.st_size)
            if not hmac.compare_digest(
                hashlib.sha256(value).digest(), self._content_digest
            ):
                raise HostAuthorityUnavailable("host-private file unavailable")
            return value
        except Exception:
            self._broken = True
            raise HostAuthorityUnavailable("host-private file unavailable") from None

    @property
    def directory_fd(self) -> int:
        self._directory.check_current()
        return self._directory.fd

    def close(self) -> None:
        fd = getattr(self, "fd", None)
        if fd is not None:
            self.fd = None  # type: ignore[assignment]
            os.close(fd)
        self._directory.close()


def _open_secret(path: Path) -> _PinnedPrivateFile:
    pinned = _PinnedPrivateFile(path, max_size=32)
    try:
        if len(pinned.read_current()) != 32:
            raise HostAuthorityUnavailable("host-private secret unavailable")
        return pinned
    except Exception:
        pinned.close()
        raise HostAuthorityUnavailable("host-private secret unavailable") from None


@dataclass(frozen=True, repr=False)
class HostPrivateFacilityPaths:
    """Immutable binding to the four deployment-provisioned facility paths."""

    data_key: Path
    writer_master: Path
    execution_master: Path
    lock_directory: Path

    def __post_init__(self) -> None:
        for name in (
            "data_key",
            "writer_master",
            "execution_master",
            "lock_directory",
        ):
            object.__setattr__(self, name, _safe_path(getattr(self, name)))

    def __repr__(self) -> str:
        return "HostPrivateFacilityPaths(<host-private>)"


def _validate_paths(value: object) -> HostPrivateFacilityPaths:
    if type(value) is not HostPrivateFacilityPaths:
        raise TypeError("invalid host-private facility binding")
    return value


def _parse_tombstone(value: bytes) -> tuple[str, str]:
    try:
        stored = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HostAuthorityUnavailable("data-key state unavailable") from None
    if type(stored) is not dict or set(stored) != {
        "contract",
        "version",
        "key_id",
        "request_digest",
    }:
        raise HostAuthorityUnavailable("data-key state unavailable")
    if (
        stored["contract"] != _DATA_TOMBSTONE_CONTRACT
        or stored["version"] != _DATA_TOMBSTONE_VERSION
        or type(stored["key_id"]) is not str
        or not stored["key_id"].startswith("key:v1:")
        or len(stored["key_id"]) != 71
        or stored["key_id"].lower() != stored["key_id"]
        or type(stored["request_digest"]) is not str
        or len(stored["request_digest"]) != 64
        or stored["request_digest"].lower() != stored["request_digest"]
    ):
        raise HostAuthorityUnavailable("data-key state unavailable")
    try:
        int(stored["key_id"][7:], 16)
        int(stored["request_digest"], 16)
    except ValueError:
        raise HostAuthorityUnavailable("data-key state unavailable") from None
    return stored["key_id"], stored["request_digest"]


def _terminal_request_digest(
    request: object, installation_id: str
) -> tuple[str, dict[str, object]]:
    if type(request) is not dict or set(request) != {
        "operation_ref",
        "authority_binding",
        "transition_id",
    }:
        raise ValueError("invalid data-key lifecycle request")
    operation_ref = validate_opaque_text(request["operation_ref"], "operation_ref")
    transition_id = validate_opaque_text(request["transition_id"], "transition_id")
    authority = AuthoritySnapshot.from_storage(request["authority_binding"])
    if (
        not authority.terminal
        or authority.installation_id != installation_id
        or authority.transition_id != transition_id
    ):
        raise ValueError("invalid data-key lifecycle binding")
    normalized = {
        "operation_ref": operation_ref,
        "authority_binding": authority.to_storage(),
        "transition_id": transition_id,
    }
    return hashlib.sha256(_canonical(normalized)).hexdigest(), normalized


class HostPrivateKeyProvider:
    """Pinned data-key provider with exact terminal destruction semantics."""

    def __init__(self, paths: HostPrivateFacilityPaths, installation_id: str) -> None:
        self._paths = _validate_paths(paths)
        self._installation_id = validate_opaque_text(
            installation_id, "installation_id"
        )
        self._lock = threading.RLock()
        self._pinned = _PinnedPrivateFile(
            self._paths.data_key, max_size=_MAX_TOMBSTONE_BYTES
        )
        try:
            value = self._pinned.read_current()
            if len(value) == 32:
                self._state = "present"
                self._key_id = "key:v1:" + hashlib.sha256(value).hexdigest()
                self._request_digest: str | None = None
            else:
                self._state = "absent"
                self._key_id, self._request_digest = _parse_tombstone(value)
        except Exception:
            self._pinned.close()
            raise

    @property
    def key_id(self) -> str:
        with self._lock:
            self._pinned.read_current()
            return self._key_id

    def get_key(self) -> bytes:
        with self._lock:
            if self._state != "present":
                raise HostAuthorityUnavailable("data key unavailable")
            value = self._pinned.read_current()
            if len(value) != 32:
                raise HostAuthorityUnavailable("data key unavailable")
            return memoryview(value).tobytes()

    def destroy(self, request: object) -> dict[str, object]:
        request_digest, _ = _terminal_request_digest(
            request, self._installation_id
        )
        with self._lock:
            current = self._pinned.read_current()
            if self._state == "absent":
                if not secrets.compare_digest(
                    request_digest, self._request_digest or ""
                ):
                    raise ValueError("data-key tombstone binding mismatch")
                return {"status": "confirmed"}
            if len(current) != 32:
                raise HostAuthorityUnavailable("data key unavailable")
            tombstone = _canonical(
                {
                    "contract": _DATA_TOMBSTONE_CONTRACT,
                    "version": _DATA_TOMBSTONE_VERSION,
                    "key_id": self._key_id,
                    "request_digest": request_digest,
                }
            )
            self._replace_with_tombstone(tombstone)
            self._state = "absent"
            self._request_digest = request_digest
            return {"status": "confirmed"}

    def absence(self, request: object) -> dict[str, object]:
        request_digest, _ = _terminal_request_digest(
            request, self._installation_id
        )
        with self._lock:
            self._pinned.read_current()
            if self._state == "present":
                return {"status": "present"}
            if not secrets.compare_digest(
                request_digest, self._request_digest or ""
            ):
                raise ValueError("data-key tombstone binding mismatch")
            return {"status": "absent"}

    def _replace_with_tombstone(self, tombstone: bytes) -> None:
        directory_fd = self._pinned.directory_fd
        temporary = ".ticket121-tombstone-" + secrets.token_hex(16)
        fd: int | None = None
        try:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_CLOEXEC
                | os.O_NOFOLLOW
            )
            fd = os.open(temporary, flags, 0o400, dir_fd=directory_fd)
            offset = 0
            while offset < len(tombstone):
                offset += os.write(fd, tombstone[offset:])
            os.fsync(fd)
            os.close(fd)
            fd = None
            self._pinned.read_current()
            os.replace(
                temporary,
                self._paths.data_key.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
            old = self._pinned
            self._pinned = _PinnedPrivateFile(
                self._paths.data_key, max_size=_MAX_TOMBSTONE_BYTES
            )
            parsed_key_id, _ = _parse_tombstone(self._pinned.read_current())
            if parsed_key_id != self._key_id:
                raise HostAuthorityUnavailable("data-key state unavailable")
            old.close()
        except Exception:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except OSError:
                pass
            raise HostAuthorityUnavailable("data-key destruction unavailable") from None


def _writer_nonce(
    master: bytes, installation_id: str, site: str, epoch_ref: str
) -> str:
    raw = hmac.new(
        master,
        _WRITER_NONCE_DOMAIN
        + _canonical([installation_id, site, epoch_ref]),
        hashlib.sha256,
    ).digest()[:16]
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _writer_capability(
    master: bytes, installation_id: str, site: str, nonce: str
) -> str:
    return hmac.new(
        master,
        _WRITER_CAPABILITY_DOMAIN + _canonical([installation_id, site, nonce]),
        hashlib.sha256,
    ).hexdigest()


def _parse_fence_ref(value: object) -> tuple[str, str] | None:
    if type(value) is not str:
        return None
    parts = value.split(":")
    if len(parts) != 4 or parts[:2] != ["fence", "v1"]:
        return None
    nonce, digest = parts[2], parts[3]
    if (
        re.fullmatch(r"[A-Za-z0-9_-]{22}", nonce) is None
        or len(digest) != 64
        or digest.lower() != digest
    ):
        return None
    try:
        decoded = base64.urlsafe_b64decode(nonce + "==")
        int(digest, 16)
    except (ValueError, TypeError):
        return None
    if len(decoded) != 16:
        return None
    return nonce, digest


def _validate_lock_stat(value: os.stat_result) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_gid != os.getegid()
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_nlink != 1
    ):
        raise HostAuthorityUnavailable("host-private lock unavailable")


def _acquire_lock(directory: _DirectoryHandle, name: str) -> int | None:
    directory.check_current()
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, 0o600, dir_fd=directory.fd)
        opened = os.fstat(fd)
        current = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
        _validate_lock_stat(opened)
        _validate_lock_stat(current)
        if not _same_identity(opened, current):
            raise HostAuthorityUnavailable("host-private lock unavailable")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                os.close(fd)
                return None
            raise
        return fd
    except Exception as exc:
        candidate = locals().get("fd")
        if isinstance(candidate, int):
            try:
                os.close(candidate)
            except OSError:
                pass
        if isinstance(exc, HostAuthorityUnavailable):
            raise
        raise HostAuthorityUnavailable("host-private lock unavailable") from None


class _WriterHolderSession:
    def __init__(
        self,
        vault: "HostPrivateWriterFenceVault",
        installation_id: str,
        site: str,
        lock_fd: int,
    ) -> None:
        self._vault = vault
        self._installation_id = installation_id
        self._site = site
        self._lock_fd: int | None = lock_fd
        self._lock = threading.RLock()

    def active(self) -> bool:
        with self._lock:
            if self._lock_fd is None:
                return False
            try:
                self._vault._master.read_current()
                self._vault._locks.check_current()
                return True
            except Exception:
                return False

    def proof_for(self, authority: AuthoritySnapshot) -> WriterFenceProof | None:
        with self._lock:
            if (
                self._lock_fd is None
                or type(authority) is not AuthoritySnapshot
                or authority.terminal
                or authority.installation_id != self._installation_id
                or authority.site != self._site
            ):
                return None
            try:
                return self._vault._proof_for(authority)
            except Exception:
                return None

    def release(self) -> None:
        with self._lock:
            if self._lock_fd is None:
                return
            fd = self._lock_fd
            self._lock_fd = None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


class HostPrivateWriterFenceVault:
    """Linux-flock writer holder backed by the pinned writer master."""

    def __init__(self, paths: HostPrivateFacilityPaths) -> None:
        self._paths = _validate_paths(paths)
        self._master = _open_secret(self._paths.writer_master)
        try:
            self._locks = _DirectoryHandle(self._paths.lock_directory)
        except Exception:
            self._master.close()
            raise

    def prepare_fence_ref(
        self, installation_id: str, site: str, epoch_ref: str
    ) -> str:
        installation_id = validate_opaque_text(
            installation_id, "installation_id"
        )
        site = validate_opaque_text(site, "site")
        epoch_ref = validate_opaque_text(epoch_ref, "epoch_ref")
        master = self._master.read_current()
        nonce = _writer_nonce(master, installation_id, site, epoch_ref)
        capability = _writer_capability(master, installation_id, site, nonce)
        digest = hashlib.sha256(capability.encode("ascii")).hexdigest()
        return f"fence:v1:{nonce}:{digest}"

    def acquire_or_resume(
        self,
        installation_id: str,
        site: str,
        holder: WriterHolderClaim,
    ) -> _WriterHolderSession | None:
        if type(holder) is not WriterHolderClaim:
            return None
        try:
            installation_id = validate_opaque_text(
                installation_id, "installation_id"
            )
            site = validate_opaque_text(site, "site")
            self._master.read_current()
            namespace = hashlib.sha256(
                _canonical([installation_id, site])
            ).hexdigest()
            fd = _acquire_lock(self._locks, f"writer-{namespace}.lock")
            if fd is None:
                return None
            return _WriterHolderSession(self, installation_id, site, fd)
        except Exception:
            return None

    def _proof_for(self, authority: AuthoritySnapshot) -> WriterFenceProof | None:
        parsed = _parse_fence_ref(authority.writer_fence)
        if parsed is None:
            return None
        nonce, expected_digest = parsed
        master = self._master.read_current()
        capability = _writer_capability(
            master, authority.installation_id, authority.site, nonce
        )
        actual_digest = hashlib.sha256(capability.encode("ascii")).hexdigest()
        if not secrets.compare_digest(actual_digest, expected_digest):
            return None
        return WriterFenceProof(authority=authority, capability=capability)


def _authority_digest(authority: AuthoritySnapshot) -> str:
    return hashlib.sha256(_canonical(authority.to_storage())).hexdigest()


def _writer_proof_is_valid(
    authority: AuthoritySnapshot, proof: WriterFenceProof, master: bytes
) -> bool:
    if proof.authority != authority:
        return False
    parsed = _parse_fence_ref(authority.writer_fence)
    if parsed is None:
        return False
    nonce, expected_digest = parsed
    expected_capability = _writer_capability(
        master, authority.installation_id, authority.site, nonce
    )
    return secrets.compare_digest(proof.capability, expected_capability) and secrets.compare_digest(
        hashlib.sha256(proof.capability.encode("ascii")).hexdigest(),
        expected_digest,
    )


class _ExecutionCapabilitySession:
    def __init__(
        self,
        vault: "HostPrivateExecutionCapabilityVault",
        authority: AuthoritySnapshot,
        writer_digest: str,
        lock_fd: int,
    ) -> None:
        self._vault = vault
        self._authority = authority
        self._writer_digest = writer_digest
        self._lock_fd: int | None = lock_fd
        self._lock = threading.RLock()

    def _capability_for(
        self, binding: ExecutionCapabilityBinding
    ) -> str | None:
        if (
            self._lock_fd is None
            or type(binding) is not ExecutionCapabilityBinding
            or binding.authority != self._authority
        ):
            return None
        try:
            self._vault._writer_master.read_current()
            master = self._vault._execution_master.read_current()
        except Exception:
            return None
        body = _EXECUTION_CAPABILITY_DOMAIN + _canonical(
            [
                binding.authority.to_storage(),
                binding.effect_id,
                binding.intent_digest,
                binding.vault_claim_ref,
                self._writer_digest,
            ]
        )
        return "execution:v1:" + hmac.new(
            master, body, hashlib.sha256
        ).hexdigest()

    def mint(self, binding: ExecutionCapabilityBinding) -> str | None:
        with self._lock:
            return self._capability_for(binding)

    def recover(
        self, binding: ExecutionCapabilityBinding, holder_id: str
    ) -> str | None:
        with self._lock:
            if type(holder_id) is not str:
                return None
            capability = self._capability_for(binding)
            if capability is None:
                return None
            expected_holder = holder_id_for(capability)
            if not secrets.compare_digest(holder_id, expected_holder):
                return None
            return capability

    def active(self) -> bool:
        with self._lock:
            if self._lock_fd is None:
                return False
            try:
                self._vault._writer_master.read_current()
                self._vault._execution_master.read_current()
                self._vault._locks.check_current()
                return True
            except Exception:
                return False

    def release(self) -> None:
        with self._lock:
            if self._lock_fd is None:
                return
            fd = self._lock_fd
            self._lock_fd = None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


class HostPrivateExecutionCapabilityVault:
    """Deterministic completion capabilities under an exclusive POSIX lease."""

    def __init__(self, paths: HostPrivateFacilityPaths) -> None:
        self._paths = _validate_paths(paths)
        self._writer_master = _open_secret(self._paths.writer_master)
        try:
            self._execution_master = _open_secret(self._paths.execution_master)
            self._locks = _DirectoryHandle(self._paths.lock_directory)
        except Exception:
            self._writer_master.close()
            execution = getattr(self, "_execution_master", None)
            if execution is not None:
                execution.close()
            raise

    def acquire_or_resume_session(
        self,
        authority: AuthoritySnapshot,
        writer_proof: WriterFenceProof,
    ) -> _ExecutionCapabilitySession | None:
        if (
            type(authority) is not AuthoritySnapshot
            or authority.terminal
            or type(writer_proof) is not WriterFenceProof
        ):
            return None
        try:
            writer_master = self._writer_master.read_current()
            self._execution_master.read_current()
            if not _writer_proof_is_valid(
                authority, writer_proof, writer_master
            ):
                return None
            authority_digest = _authority_digest(authority)
            fd = _acquire_lock(
                self._locks, f"execution-{authority_digest}.lock"
            )
            if fd is None:
                return None
            writer_digest = hashlib.sha256(
                writer_proof.capability.encode("ascii")
            ).hexdigest()
            return _ExecutionCapabilitySession(
                self, authority, writer_digest, fd
            )
        except Exception:
            return None


__all__ = [
    "HostAuthorityUnavailable",
    "HostPrivateExecutionCapabilityVault",
    "HostPrivateFacilityPaths",
    "HostPrivateKeyProvider",
    "HostPrivateWriterFenceVault",
]

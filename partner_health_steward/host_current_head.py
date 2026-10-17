"""Private, same-host SQLite current-head authority.

This provider deliberately has no whole-machine snapshot freshness guarantee.
It stores public authority and exact receipts, never writer capabilities or
health records. Existing installations can only be opened, not repaired.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import quote

from .authority import (
    AuthoritySnapshot, AuthorityValidationError, ExecutionLease, WriterFenceProof,
    validate_opaque_text,
)
from .current_head import (
    AdvanceIdentity, AdvanceRequest, AppliedLifecycleTransition, AppliedTransition,
    CurrentHeadError, ExecutionLeaseIdentity, ExecutionLeaseNotFound,
    ExecutionLeaseReceipt, ExecutionLeaseRelease, ExecutionLeaseRequest,
    HeadConflict, HeadRead, HeadSnapshot, HeadTerminal, HeadTimeout, HeadUnknown,
    LifecycleTransitionIdentity, LifecycleTransitionRequest, TransitionNotFound,
    _ExecutionOverlapPermit,
)


_FENCE_PATTERN = re.compile(r"fence:v1:[A-Za-z0-9_-]{22}:([0-9a-f]{64})")
_SCHEMA_VERSION = 1
_APPLICATION_ID = 0x48534844
_SCHEMA = {
    "namespace": "CREATE TABLE namespace (singleton INTEGER PRIMARY KEY CHECK(singleton=1), installation_id TEXT NOT NULL)",
    "head": "CREATE TABLE head (singleton INTEGER PRIMARY KEY CHECK(singleton=1), authority TEXT NOT NULL)",
    "transitions": "CREATE TABLE transitions (kind TEXT NOT NULL CHECK(kind IN ('advance','lifecycle')), record_key TEXT NOT NULL, identity TEXT NOT NULL, applied TEXT NOT NULL, PRIMARY KEY(kind,record_key))",
    "leases": "CREATE TABLE leases (effect_id TEXT PRIMARY KEY NOT NULL, identity TEXT NOT NULL, lease TEXT NOT NULL, released INTEGER NOT NULL CHECK(released IN (0,1)), release_digest TEXT, active INTEGER NOT NULL CHECK(active IN (0,1)))",
}
_ADVANCE_FIELDS = frozenset({"expected", "transition_id", "revision_digest", "writer_fence", "operation_digest"})
_LIFECYCLE_FIELDS = _ADVANCE_FIELDS | {"kind", "operation_ref", "target_site", "target_writer_fence_ref"}
_LEASE_FIELDS = frozenset({"expected", "effect_id", "intent_digest", "writer_fence", "holder_id"})


@dataclass(frozen=True)
class HostHeadBinding:
    database_path: str
    installation_id: str
    local_site: str
    local_writer_fence_ref: str

    def __post_init__(self) -> None:
        path = self.database_path
        if (type(path) is not str or not path.startswith("/") or "\x00" in path
                or path != os.path.normpath(path) or path.startswith("//")
                or not os.path.basename(path)):
            raise AuthorityValidationError("invalid host head path")
        validate_opaque_text(self.installation_id, "installation_id")
        validate_opaque_text(self.local_site, "local_site")
        validate_opaque_text(self.local_writer_fence_ref, "local_writer_fence_ref")
        if _FENCE_PATTERN.fullmatch(self.local_writer_fence_ref) is None:
            raise AuthorityValidationError("invalid host head public fence")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CurrentHeadError("host-head duplicate stored field")
        result[key] = value
    return result


def _load(text: object) -> object:
    if type(text) is not str:
        raise CurrentHeadError("host-head invalid stored value")
    try:
        return json.loads(text, object_pairs_hook=_unique_pairs)
    except (ValueError, RecursionError):
        raise CurrentHeadError("host-head invalid stored encoding") from None


def _identity_storage(identity: AdvanceIdentity | LifecycleTransitionIdentity | ExecutionLeaseIdentity) -> dict[str, object]:
    # Explicit public projections keep request proofs and internal permits out
    # of both SQLite and its journals, including on rejected requests.
    if type(identity) is ExecutionLeaseIdentity:
        return {"expected": identity.expected.to_storage(), "effect_id": identity.effect_id,
                "intent_digest": identity.intent_digest, "writer_fence": identity.writer_fence,
                "holder_id": identity.holder_id}
    result = {"expected": identity.expected.to_storage(), "transition_id": identity.transition_id,
              "revision_digest": identity.revision_digest, "writer_fence": identity.writer_fence,
              "operation_digest": identity.operation_digest}
    if type(identity) is LifecycleTransitionIdentity:
        result.update(kind=identity.kind, operation_ref=identity.operation_ref,
                      target_site=identity.target_site, target_writer_fence_ref=identity.target_writer_fence_ref)
    return result


def _decode_identity(text: object, kind: str) -> AdvanceIdentity | LifecycleTransitionIdentity | ExecutionLeaseIdentity:
    value = _load(text)
    fields = {"advance": _ADVANCE_FIELDS, "lifecycle": _LIFECYCLE_FIELDS, "lease": _LEASE_FIELDS}[kind]
    if type(value) is not dict or value.keys() != fields:
        raise CurrentHeadError("host-head invalid receipt fields")
    try:
        value["expected"] = AuthoritySnapshot.from_storage(value["expected"])
        constructor = {"advance": AdvanceIdentity, "lifecycle": LifecycleTransitionIdentity,
                       "lease": ExecutionLeaseIdentity}[kind]
        return constructor(**value)
    except (TypeError, ValueError):
        raise CurrentHeadError("host-head invalid receipt identity") from None


class HostSQLiteCurrentHead:
    """One private file with transactional head, receipts and live lease guards."""

    @property
    def provider_kind(self) -> str:
        return "host-sqlite"

    def __init__(self, binding: HostHeadBinding) -> None:
        self._open(binding, None)

    @classmethod
    def bootstrap(cls, binding: HostHeadBinding, initial_head: HeadSnapshot) -> HostSQLiteCurrentHead:
        if type(binding) is not HostHeadBinding or type(initial_head) is not HeadSnapshot:
            raise AuthorityValidationError("invalid host-head bootstrap")
        if (initial_head.generation != 1 or initial_head.terminal
                or initial_head.installation_id != binding.installation_id
                or initial_head.site != binding.local_site
                or initial_head.writer_fence != binding.local_writer_fence_ref):
            raise HeadConflict("host-head bootstrap authority conflict")
        provider = cls.__new__(cls)
        provider._open(binding, initial_head)
        return provider

    def _open(self, binding: HostHeadBinding, initial: HeadSnapshot | None) -> None:
        if type(binding) is not HostHeadBinding:
            raise AuthorityValidationError("invalid host head binding")
        self._binding = binding
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self._connection: sqlite3.Connection | None = None
        self._parent_fd = self._file_fd = -1
        self._name = os.path.basename(binding.database_path)
        try:
            # Walk without following a symlink in any path component. Keep the
            # parent open while SQLite opens the same file through that dirfd.
            self._parent_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
            for part in os.path.dirname(binding.database_path).split("/"):
                if not part:
                    continue
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=self._parent_fd)
                os.close(self._parent_fd)
                self._parent_fd = next_fd
            parent = os.fstat(self._parent_fd)
            self._private(parent, directory=True)
            self._parent_identity = (parent.st_dev, parent.st_ino)
            flags = os.O_RDWR | os.O_NOFOLLOW
            if initial is not None:
                flags |= os.O_CREAT | os.O_EXCL
            self._file_fd = os.open(self._name, flags, 0o600, dir_fd=self._parent_fd)
            opened = os.fstat(self._file_fd)
            self._private(opened)
            self._file_identity = (opened.st_dev, opened.st_ino)
            self._check_path()
            uri = "file:" + quote(f"/proc/self/fd/{self._parent_fd}/{self._name}", safe="/") + "?mode=rw"
            connection = sqlite3.connect(uri, uri=True, timeout=0.25, isolation_level=None,
                                         check_same_thread=False)
            self._connection = connection
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA temp_store=MEMORY")
            self._check_path()
            if initial is not None:
                connection.execute("PRAGMA journal_mode=DELETE")
                with self._transaction(write=True):
                    connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                    for statement in _SCHEMA.values():
                        connection.execute(statement)
                    connection.execute("INSERT INTO namespace VALUES (1,?)", (binding.installation_id,))
                    connection.execute("INSERT INTO head VALUES (1,?)", (_json(initial.to_storage()),))
                try:
                    os.fsync(self._parent_fd)
                except OSError:
                    raise HeadUnknown("host-head bootstrap durability unknown") from None
            self._validate_database()
        except CurrentHeadError:
            self.close()
            raise
        except (OSError, sqlite3.Error, ValueError):
            self.close()
            raise CurrentHeadError("host-head open failed") from None

    @staticmethod
    def _private(info: os.stat_result, *, directory: bool = False) -> None:
        if (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
                or (not stat.S_ISDIR(info.st_mode) if directory else
                    (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1))):
            raise CurrentHeadError("host-head unsafe filesystem identity")

    def _check_path(self) -> None:
        if self._pid != os.getpid() or self._parent_fd < 0 or self._file_fd < 0:
            raise CurrentHeadError("host-head closed or foreign process")
        try:
            parent = os.stat(os.path.dirname(self._binding.database_path), follow_symlinks=False)
            self._private(parent, directory=True)
            opened_parent = os.fstat(self._parent_fd)
            if (parent.st_dev, parent.st_ino) != self._parent_identity or (
                    opened_parent.st_dev, opened_parent.st_ino) != self._parent_identity:
                raise CurrentHeadError("host-head parent replaced")
            current = os.stat(self._name, dir_fd=self._parent_fd, follow_symlinks=False)
            opened = os.fstat(self._file_fd)
            self._private(current)
            self._private(opened)
            if (current.st_dev, current.st_ino) != self._file_identity or (
                    opened.st_dev, opened.st_ino) != self._file_identity:
                raise CurrentHeadError("host-head file replaced")
            for suffix in ("-journal", "-wal", "-shm"):
                try:
                    sidecar = os.stat(self._name + suffix, dir_fd=self._parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                self._private(sidecar)
        except OSError:
            raise CurrentHeadError("host-head filesystem check failed") from None

    def _validate_database(self) -> None:
        with self._transaction():
            connection = self._db()
            if (connection.execute("PRAGMA application_id").fetchone() != (_APPLICATION_ID,)
                    or connection.execute("PRAGMA user_version").fetchone() != (_SCHEMA_VERSION,)
                    or connection.execute("PRAGMA journal_mode").fetchone() != ("delete",)
                    or connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]):
                raise CurrentHeadError("host-head invalid database")
            schema = connection.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL").fetchall()
            if len(schema) != len(_SCHEMA) or dict(schema) != _SCHEMA:
                raise CurrentHeadError("host-head schema mismatch")
            if connection.execute("SELECT singleton,installation_id FROM namespace").fetchall() != [
                    (1, self._binding.installation_id)]:
                raise CurrentHeadError("host-head namespace mismatch")
            self._head()

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise CurrentHeadError("host-head closed")
        return self._connection

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[None]:
        with self._lock:
            self._check_path()
            connection = self._db()
            committing = committed = False
            try:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                self._check_path()
                yield
                self._check_path()
                committing = True
                connection.execute("COMMIT")
                committed = True
                self._check_path()
            except BaseException as exc:
                try:
                    if connection.in_transaction:
                        connection.rollback()
                except sqlite3.Error:
                    pass
                if write and committed:
                    raise HeadUnknown("host-head commit readback unknown") from None
                if isinstance(exc, sqlite3.Error):
                    code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
                    if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                        raise HeadTimeout("host-head lock timeout") from None
                    if write and committing:
                        raise HeadUnknown("host-head commit outcome unknown") from None
                    if isinstance(exc, sqlite3.IntegrityError):
                        raise HeadConflict("host-head receipt conflict") from None
                    raise CurrentHeadError("host-head database operation failed") from None
                raise

    def _head(self) -> HeadSnapshot:
        rows = self._db().execute("SELECT singleton,authority FROM head").fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            raise CurrentHeadError("host-head missing authority")
        try:
            authority = HeadSnapshot.from_storage(_load(rows[0][1]))
        except (ValueError, TypeError):
            raise CurrentHeadError("host-head invalid authority") from None
        if (authority.installation_id != self._binding.installation_id
                or _FENCE_PATTERN.fullmatch(authority.writer_fence) is None):
            raise CurrentHeadError("host-head authority namespace mismatch")
        return authority

    def _proof_matches(self, proof: WriterFenceProof, authority: AuthoritySnapshot) -> bool:
        if (type(proof) is not WriterFenceProof or proof.authority != authority
                or authority.installation_id != self._binding.installation_id
                or authority.site != self._binding.local_site
                or authority.writer_fence != self._binding.local_writer_fence_ref):
            return False
        match = _FENCE_PATTERN.fullmatch(authority.writer_fence)
        return match is not None and hmac.compare_digest(
            match.group(1), hashlib.sha256(proof.capability.encode("utf-8")).hexdigest())

    def _require_live(self, expected: AuthoritySnapshot, proof: WriterFenceProof) -> HeadSnapshot:
        head = self._head()
        if head.terminal:
            raise HeadTerminal("terminal current head")
        if head.as_authority() != expected or not self._proof_matches(proof, expected):
            raise HeadConflict("host-head current authority conflict")
        return head

    def read(self) -> HeadRead:
        with self._transaction():
            return HeadRead(self._head())

    def validate_writer_fence(self, proof: WriterFenceProof) -> bool:
        with self._transaction():
            head = self._head()
            if head.terminal:
                raise HeadTerminal("terminal current head")
            return self._proof_matches(proof, head.as_authority())

    def _active_effects(self) -> set[str]:
        result: set[str] = set()
        current = self._head()
        for row in self._db().execute("SELECT effect_id,identity,lease,released,release_digest,active FROM leases WHERE active=1"):
            receipt = self._decode_lease(row)
            if (receipt.released or receipt.lease.authority.site != current.site
                    or receipt.lease.authority.writer_fence != current.writer_fence):
                raise CurrentHeadError("host-head inconsistent live lease")
            result.add(receipt.request.effect_id)
        return result

    def _check_overlap(self, permit: _ExecutionOverlapPermit | None) -> None:
        active = self._active_effects()
        if permit is None:
            if active:
                raise HeadConflict("host-head active execution lease")
        elif type(permit) is not _ExecutionOverlapPermit or active != {permit.active_effect_id}:
            raise HeadConflict("host-head execution overlap conflict")

    @staticmethod
    def _transition_key(identity: AdvanceIdentity | LifecycleTransitionIdentity) -> str:
        reference = identity.operation_ref if type(identity) is LifecycleTransitionIdentity else identity.transition_id
        return _json([reference, identity.operation_digest])

    def _write_head(self, applied: HeadSnapshot) -> None:
        self._db().execute("UPDATE head SET authority=? WHERE singleton=1", (_json(applied.to_storage()),))

    def _write_transition(self, kind: str, identity: AdvanceIdentity | LifecycleTransitionIdentity, applied: HeadSnapshot) -> None:
        self._db().execute("INSERT INTO transitions VALUES (?,?,?,?)", (
            kind, self._transition_key(identity), _json(_identity_storage(identity)), _json(applied.to_storage())))
        self._write_head(applied)

    def conditional_advance(self, request: AdvanceRequest) -> HeadSnapshot:
        if type(request) is not AdvanceRequest:
            raise AuthorityValidationError("invalid advance request")
        with self._transaction(write=True):
            head = self._require_live(request.expected, request.writer_proof)
            self._check_overlap(request._execution_overlap)
            applied = HeadSnapshot(head.installation_id, head.generation + 1, request.revision_digest,
                                   request.transition_id, head.writer_fence, False, head.site)
            identity = request.identity()
            AppliedTransition(identity, applied)
            self._write_transition("advance", identity, applied)
            return applied

    def _lookup_transition(self, identity: AdvanceIdentity | LifecycleTransitionIdentity, kind: str) -> AppliedTransition | AppliedLifecycleTransition:
        row = self._db().execute("SELECT identity,applied FROM transitions WHERE kind=? AND record_key=?",
                                 (kind, self._transition_key(identity))).fetchone()
        if row is None:
            raise TransitionNotFound("host-head transition not found")
        stored = _decode_identity(row[0], kind)
        if stored != identity:
            raise HeadConflict("host-head transition identity conflict")
        try:
            applied = HeadSnapshot.from_storage(_load(row[1]))
            if (applied.installation_id != self._binding.installation_id
                    or _FENCE_PATTERN.fullmatch(applied.writer_fence) is None):
                raise CurrentHeadError("host-head receipt namespace mismatch")
            if kind == "advance":
                return AppliedTransition(stored, applied)
            if stored.kind == "writer-transfer" and applied.writer_fence != stored.target_writer_fence_ref:
                raise CurrentHeadError("host-head transfer receipt fence mismatch")
            return AppliedLifecycleTransition(stored, applied)
        except (ValueError, TypeError):
            raise CurrentHeadError("host-head invalid transition receipt") from None

    def lookup_transition(self, request: AdvanceIdentity) -> AppliedTransition:
        if type(request) is not AdvanceIdentity:
            raise AuthorityValidationError("invalid advance identity")
        with self._transaction():
            return self._lookup_transition(request, "advance")

    def conditional_lifecycle_transition(self, request: LifecycleTransitionRequest) -> HeadSnapshot:
        if type(request) is not LifecycleTransitionRequest:
            raise AuthorityValidationError("invalid lifecycle request")
        with self._transaction(write=True):
            head = self._require_live(request.expected, request.writer_proof)
            if request.kind == "terminal-delete":
                if self._active_effects():
                    raise HeadConflict("host-head active execution lease")
                fence, site = head.writer_fence, head.site
            else:
                fence, site = request.target_writer_fence_ref, request.target_site
                if fence == head.writer_fence or _FENCE_PATTERN.fullmatch(fence) is None:
                    raise HeadConflict("host-head transfer fence conflict")
            applied = HeadSnapshot(head.installation_id, head.generation + 1, request.revision_digest,
                                   request.transition_id, fence, request.kind == "terminal-delete", site)
            identity = request.identity()
            AppliedLifecycleTransition(identity, applied)
            self._write_transition("lifecycle", identity, applied)
            if request.kind == "writer-transfer":
                self._db().execute("UPDATE leases SET active=0 WHERE active=1")
            return applied

    def lookup_lifecycle_transition(self, identity: LifecycleTransitionIdentity) -> AppliedLifecycleTransition:
        if type(identity) is not LifecycleTransitionIdentity:
            raise AuthorityValidationError("invalid lifecycle identity")
        with self._transaction():
            return self._lookup_transition(identity, "lifecycle")

    def _decode_lease(self, row: tuple) -> ExecutionLeaseReceipt:
        effect_id, identity_text, lease_text, released, digest, active = row
        identity = _decode_identity(identity_text, "lease")
        try:
            lease = ExecutionLease.from_storage(_load(lease_text))
            if (type(released) is not int or released not in {0, 1} or type(active) is not int
                    or active not in {0, 1} or (released and active)
                    or effect_id != identity.effect_id
                    or identity.expected.installation_id != self._binding.installation_id):
                raise CurrentHeadError("host-head invalid lease state")
            return ExecutionLeaseReceipt(identity, lease, bool(released), digest)
        except (ValueError, TypeError):
            raise CurrentHeadError("host-head invalid lease receipt") from None

    def _lookup_lease(self, identity: ExecutionLeaseIdentity) -> ExecutionLeaseReceipt:
        row = self._db().execute("SELECT effect_id,identity,lease,released,release_digest,active FROM leases WHERE effect_id=?",
                                 (identity.effect_id,)).fetchone()
        if row is None:
            raise ExecutionLeaseNotFound("host-head execution lease not found")
        receipt = self._decode_lease(row)
        if receipt.request != identity:
            raise HeadConflict("host-head execution lease identity conflict")
        return receipt

    def acquire_execution_lease(self, request: ExecutionLeaseRequest) -> ExecutionLeaseReceipt:
        if type(request) is not ExecutionLeaseRequest:
            raise AuthorityValidationError("invalid execution lease request")
        with self._transaction(write=True):
            self._require_live(request.expected, request.writer_proof)
            identity = request.identity()
            try:
                return self._lookup_lease(identity)
            except ExecutionLeaseNotFound:
                pass
            self._check_overlap(request._execution_overlap)
            lease = ExecutionLease("lease:" + secrets.token_hex(24), request.effect_id, request.intent_digest,
                                   request.expected, request.holder_id)
            receipt = ExecutionLeaseReceipt(identity, lease, False)
            self._db().execute("INSERT INTO leases VALUES (?,?,?,0,NULL,1)", (
                identity.effect_id, _json(_identity_storage(identity)), _json(lease.to_storage())))
            return receipt

    def lookup_execution_lease(self, identity: ExecutionLeaseIdentity) -> ExecutionLeaseReceipt:
        if type(identity) is not ExecutionLeaseIdentity:
            raise AuthorityValidationError("invalid execution lease identity")
        with self._transaction():
            return self._lookup_lease(identity)

    def release_execution_lease(self, release: ExecutionLeaseRelease) -> ExecutionLeaseReceipt:
        if type(release) is not ExecutionLeaseRelease:
            raise AuthorityValidationError("invalid execution lease release")
        with self._transaction(write=True):
            head = self._head()
            if head.terminal:
                raise HeadTerminal("terminal current head")
            authority = release.lease.authority
            if (head.site != authority.site or head.writer_fence != authority.writer_fence
                    or not self._proof_matches(release.writer_proof, authority)):
                raise HeadConflict("host-head release authority conflict")
            identity = ExecutionLeaseIdentity(authority, release.lease.effect_id, release.lease.intent_digest,
                                              authority.writer_fence, release.lease.holder_id)
            known = self._lookup_lease(identity)
            if known.lease != release.lease:
                raise HeadConflict("host-head release lease conflict")
            if known.released:
                if known.released_operation_digest != release.operation_digest:
                    raise HeadConflict("host-head release ownership conflict")
                return known
            if identity.effect_id not in self._active_effects():
                raise HeadConflict("host-head release guard conflict")
            self._db().execute("UPDATE leases SET released=1,release_digest=?,active=0 WHERE effect_id=?",
                               (release.operation_digest, identity.effect_id))
            return ExecutionLeaseReceipt(identity, known.lease, True, release.operation_digest)

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            for name in ("_file_fd", "_parent_fd"):
                descriptor = getattr(self, name)
                if descriptor >= 0:
                    os.close(descriptor)
                    setattr(self, name, -1)


__all__ = ["HostHeadBinding", "HostSQLiteCurrentHead"]

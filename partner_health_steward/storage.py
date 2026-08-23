"""Core-owned encrypted local state store for synthetic validation."""

from __future__ import annotations

import json
import hashlib
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Mapping, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .authority import (
    AuthoritySnapshot,
    AuthorityValidationError,
    ClaimingEffect,
    CommittedTransition,
    EffectIntent,
    ExecutingEffect,
    PreparedTransition,
    RevisionTarget,
    TerminalEffect,
    holder_id_for,
    validate_committed_transition,
    validate_ticket110_effect_kind,
)
from .contract import CommandEnvelope, EffectResultPayload, ProtocolViolation, Response, StateCommitPayload


class KeyUnavailable(RuntimeError):
    pass


class StoreUnavailable(RuntimeError):
    """SQLite could not complete a durable health-state operation."""


class CausalIdConflict(RuntimeError):
    """A causal ID was reused with a different command envelope."""


@dataclass(frozen=True)
class PendingCommand:
    """The only command allowed to reconcile one unresolved remote transition."""

    record_id: str
    command: CommandEnvelope
    remote_attempted: bool


@dataclass(frozen=True)
class PendingEffectResult:
    """A redacted, exact causal owner for one unresolved effect terminal result.

    The raw completion capability is deliberately never serialised.  Its
    one-way holder binding, plus every command authority field that can alter
    the result, is retained so only the original causal request can reconcile
    a response-lost release.
    """

    effect_id: str
    causal_id: str
    protocol_version: int
    peer: str
    source: str
    generation: int
    scope: tuple[str, ...]
    intent_digest: str
    lease_id: str
    holder_id: str
    status: str
    terminal: bool
    result_digest: str
    remote_attempted: bool

    @classmethod
    def from_command(
        cls,
        command: CommandEnvelope,
        execution: ExecutingEffect,
        *,
        remote_attempted: bool,
    ) -> "PendingEffectResult":
        if command.action != "effect.result" or not isinstance(command.payload, EffectResultPayload):
            raise ProtocolViolation("invalid effect result reservation")
        payload = command.payload
        if (
            payload.effect_id != execution.intent.effect_id
            or payload.intent_digest != execution.intent.intent_digest
            or payload.lease_id != execution.lease.lease_id
            or holder_id_for(payload.completion_capability) != execution.lease.holder_id
        ):
            raise ProtocolViolation("effect-execution-capability-required")
        return cls(
            effect_id=payload.effect_id,
            causal_id=command.causal_id,
            protocol_version=command.protocol_version,
            peer=command.peer,
            source=command.source,
            generation=command.generation,
            scope=command.scope,
            intent_digest=payload.intent_digest,
            lease_id=payload.lease_id,
            holder_id=execution.lease.holder_id,
            status=payload.status,
            terminal=payload.terminal,
            result_digest=payload.result_digest,
            remote_attempted=remote_attempted,
        )

    def matches(self, command: CommandEnvelope, execution: ExecutingEffect) -> bool:
        candidate = self.from_command(command, execution, remote_attempted=self.remote_attempted)
        return candidate == self

    def to_storage(self) -> dict[str, object]:
        return {
            "effect_id": self.effect_id,
            "causal_id": self.causal_id,
            "protocol_version": self.protocol_version,
            "peer": self.peer,
            "source": self.source,
            "generation": self.generation,
            "scope": list(self.scope),
            "intent_digest": self.intent_digest,
            "lease_id": self.lease_id,
            "holder_id": self.holder_id,
            "status": self.status,
            "terminal": self.terminal,
            "result_digest": self.result_digest,
            "remote_attempted": self.remote_attempted,
        }

    @classmethod
    def from_storage(cls, value: object) -> "PendingEffectResult":
        required = {
            "effect_id",
            "causal_id",
            "protocol_version",
            "peer",
            "source",
            "generation",
            "scope",
            "intent_digest",
            "lease_id",
            "holder_id",
            "status",
            "terminal",
            "result_digest",
            "remote_attempted",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise KeyUnavailable("invalid pending effect result")
        scope_value = value["scope"]
        if not isinstance(scope_value, list):
            raise KeyUnavailable("invalid pending effect result")
        try:
            payload = EffectResultPayload(
                effect_id=value["effect_id"],
                intent_digest=value["intent_digest"],
                lease_id=value["lease_id"],
                completion_capability=value["holder_id"],
                status=value["status"],
                terminal=value["terminal"],
                result_digest=value["result_digest"],
            )
            command = CommandEnvelope(
                peer=value["peer"],
                action="effect.result",
                source=value["source"],
                causal_id=value["causal_id"],
                generation=value["generation"],
                scope=tuple(scope_value),
                payload=payload,
                protocol_version=value["protocol_version"],
            )
        except (ProtocolViolation, TypeError, ValueError) as exc:
            raise KeyUnavailable("invalid pending effect result") from exc
        if not isinstance(value["remote_attempted"], bool):
            raise KeyUnavailable("invalid pending effect result")
        return cls(
            effect_id=payload.effect_id,
            causal_id=command.causal_id,
            protocol_version=command.protocol_version,
            peer=command.peer,
            source=command.source,
            generation=command.generation,
            scope=command.scope,
            intent_digest=payload.intent_digest,
            lease_id=payload.lease_id,
            holder_id=payload.completion_capability,
            status=payload.status,
            terminal=payload.terminal,
            result_digest=payload.result_digest,
            remote_attempted=value["remote_attempted"],
        )


@dataclass(frozen=True)
class CurrentHeadRecoveryBinding:
    """The one exact command permitted to close an interrupted observation."""

    action: str
    causal_id: str
    command_digest: str

    @classmethod
    def from_command(cls, command: CommandEnvelope) -> "CurrentHeadRecoveryBinding":
        if command.action not in {"state.commit", "effect.result"}:
            raise ProtocolViolation("current-head recovery action is not supported")
        wire = EncryptedStateStore._receipt_command_wire(command)
        try:
            canonical = json.dumps(wire, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
            raise ProtocolViolation("invalid current-head recovery command") from exc
        return cls(
            action=command.action,
            causal_id=command.causal_id,
            command_digest="sha256:" + hashlib.sha256(canonical).hexdigest(),
        )

    def matches(self, command: CommandEnvelope) -> bool:
        try:
            return self == self.from_command(command)
        except ProtocolViolation:
            return False

    def to_storage(self) -> dict[str, object]:
        return {
            "action": self.action,
            "causal_id": self.causal_id,
            "command_digest": self.command_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "CurrentHeadRecoveryBinding":
        if not isinstance(value, Mapping) or set(value) != {"action", "causal_id", "command_digest"}:
            raise KeyUnavailable("invalid current-head recovery binding")
        action = value["action"]
        causal_id = value["causal_id"]
        command_digest = value["command_digest"]
        if (
            action not in {"state.commit", "effect.result"}
            or not isinstance(causal_id, str)
            or not causal_id
            or not isinstance(command_digest, str)
            or not command_digest.startswith("sha256:")
            or len(command_digest) != len("sha256:") + 64
        ):
            raise KeyUnavailable("invalid current-head recovery binding")
        return cls(action=action, causal_id=causal_id, command_digest=command_digest)


@dataclass(frozen=True)
class CurrentHeadObservationGuard:
    """Durable terminal tripwire, optionally recoverable by one exact command."""

    binding: CurrentHeadRecoveryBinding | None

    def to_storage(self) -> dict[str, object]:
        return {
            "binding": None if self.binding is None else self.binding.to_storage(),
        }

    @classmethod
    def from_storage(cls, value: object) -> "CurrentHeadObservationGuard":
        if not isinstance(value, Mapping) or set(value) != {"binding"}:
            raise KeyUnavailable("invalid current-head observation guard")
        binding = value["binding"]
        if binding is None:
            return cls(binding=None)
        return cls(binding=CurrentHeadRecoveryBinding.from_storage(binding))


@dataclass(frozen=True)
class StoredRecord:
    """A decrypted, state-discriminated local transition record."""

    state: str
    revision_digest: str
    transition_id: str
    payload: RevisionTarget | PreparedTransition | CommittedTransition


@dataclass(frozen=True)
class StoredEffect:
    """A decrypted, state-discriminated core effect record."""

    state: str
    payload: EffectIntent | ClaimingEffect | ExecutingEffect | TerminalEffect


class KeyProvider(Protocol):
    @property
    def key_id(self) -> str: ...

    def get_key(self) -> bytes: ...


class StaticKeyProvider:
    def __init__(self, key: bytes, key_id: str) -> None:
        if not isinstance(key, bytes) or len(key) not in {16, 24, 32}:
            raise ValueError("AES key must be 128, 192, or 256 bits")
        self._key = bytes(key)
        self._key_id = key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    def get_key(self) -> bytes:
        return self._key


class EncryptedStateStore:
    """A single-writer SQLite domain; payloads never sit in plaintext columns."""

    def __init__(self, database: str, key_provider: KeyProvider) -> None:
        self._key_provider = key_provider
        self._transaction_lock = threading.RLock()
        self._transaction_depth = 0
        self._poisoned = False
        self._connection = sqlite3.connect(database, uri=database.startswith("file:"), check_same_thread=False)
        self._execute("PRAGMA foreign_keys = ON")
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS health_records (
                record_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                revision_digest TEXT NOT NULL,
                transition_id TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS effects (
                effect_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS finalized_authority (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        # V1 receipts only retained status/reason and cannot truthfully replay a
        # response.  V2 stores the complete encrypted command/response pair.
        self._execute(
            "CREATE TABLE IF NOT EXISTS receipts (causal_id TEXT PRIMARY KEY, status TEXT NOT NULL, reason_code TEXT)"
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS command_receipts_v2 (
                causal_id TEXT PRIMARY KEY,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS pending_commands_v1 (
                causal_id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL UNIQUE,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS pending_effect_results_v1 (
                effect_id TEXT PRIMARY KEY,
                causal_id TEXT NOT NULL UNIQUE,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS key_check (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                key_id TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS integrity_manifest_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS terminal_observation_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS current_head_observation_guard_v1 (
                slot INTEGER PRIMARY KEY CHECK(slot = 1),
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._commit("health state initialization unavailable")
        self._initialize_or_verify_key_check()
        self._initialize_integrity_manifest()

    @property
    def key_id(self) -> str:
        try:
            key_id = self._key_provider.key_id
        except Exception as exc:  # key identity is part of the key boundary
            raise KeyUnavailable("health key identity unavailable") from exc
        if not isinstance(key_id, str) or not key_id:
            raise KeyUnavailable("health key identity invalid")
        return key_id

    def _execute(self, statement: str, parameters: tuple[object, ...] = ()) -> sqlite3.Cursor:
        """Run a direct SQLite operation through the fail-closed store boundary."""

        self._ensure_available()
        try:
            return self._connection.execute(statement, parameters)
        except sqlite3.Error as exc:
            raise StoreUnavailable("health state database unavailable") from exc

    def _ensure_available(self) -> None:
        if self._poisoned:
            raise StoreUnavailable("health state connection is unavailable")
        try:
            unresolved_transaction = self._transaction_depth == 0 and self._connection.in_transaction
        except sqlite3.Error as exc:
            self._poisoned = True
            raise StoreUnavailable("health state connection is unavailable") from exc
        if unresolved_transaction:
            self._poisoned = True
            raise StoreUnavailable("health state transaction is unresolved")

    def _commit(self, message: str) -> None:
        try:
            self._connection.commit()
        except sqlite3.Error as exc:
            self._rollback_after_transaction_failure()
            raise StoreUnavailable(message) from exc

    def _cipher(self) -> AESGCM:
        try:
            key = self._key_provider.get_key()
        except Exception as exc:  # key boundary deliberately collapses provider details
            raise KeyUnavailable("health key unavailable") from exc
        if not isinstance(key, bytes) or len(key) not in {16, 24, 32}:
            raise KeyUnavailable("health key invalid")
        return AESGCM(key)

    def _seal(self, aad: str, value: object) -> tuple[bytes, bytes]:
        try:
            plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
            raise KeyUnavailable("health state serialization failed") from exc
        nonce = secrets.token_bytes(12)
        return nonce, self._cipher().encrypt(nonce, plaintext, aad.encode("utf-8"))

    def _open(self, aad: str, nonce: bytes, ciphertext: bytes) -> object:
        if not isinstance(nonce, (bytes, bytearray, memoryview)) or not isinstance(
            ciphertext, (bytes, bytearray, memoryview)
        ):
            raise KeyUnavailable("health state authentication failed")
        try:
            plaintext = self._cipher().decrypt(bytes(nonce), bytes(ciphertext), aad.encode("utf-8"))
            return json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise KeyUnavailable("health state authentication failed") from exc

    def _initialize_or_verify_key_check(self) -> None:
        row = self._execute("SELECT key_id, nonce, ciphertext FROM key_check WHERE slot = 1").fetchone()
        if row is None:
            nonce, ciphertext = self._seal("key-check", {"marker": "health-core-key-check"})
            if self._transaction_depth > 0:
                self._execute(
                    "INSERT INTO key_check(slot, key_id, nonce, ciphertext) VALUES (1, ?, ?, ?)",
                    (self.key_id, nonce, ciphertext),
                )
            else:
                with self.transaction() as connection:
                    connection.execute(
                        "INSERT INTO key_check(slot, key_id, nonce, ciphertext) VALUES (1, ?, ?, ?)",
                        (self.key_id, nonce, ciphertext),
                    )
            return
        if row[0] != self.key_id or self._open("key-check", row[1], row[2]) != {"marker": "health-core-key-check"}:
            raise KeyUnavailable("health key does not match state domain")

    def _initialize_integrity_manifest(self) -> None:
        """Create a signed empty-domain manifest only for a fresh store.

        A pre-existing state domain without a manifest is not silently adopted:
        it remains unavailable so an upgrade cannot turn unauthenticated old
        rows into trusted current health state.
        """

        if self._execute("SELECT 1 FROM integrity_manifest_v1 WHERE slot = 1").fetchone() is not None:
            return
        populated_tables = (
            "health_records",
            "effects",
            "finalized_authority",
            "receipts",
            "command_receipts_v2",
            "pending_commands_v1",
            "pending_effect_results_v1",
            "terminal_observation_v1",
            "current_head_observation_guard_v1",
        )
        if any(self._execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None for table in populated_tables):
            return
        with self.transaction() as connection:
            self._refresh_integrity_manifest(connection)

    def _integrity_fingerprint(self) -> str:
        """Hash every mutable domain row except the manifest itself."""

        tables = {
            "records": self._execute(
                "SELECT record_id, state, revision_digest, transition_id, nonce, ciphertext "
                "FROM health_records ORDER BY record_id"
            ).fetchall(),
            "effects": self._execute(
                "SELECT effect_id, state, nonce, ciphertext FROM effects ORDER BY effect_id"
            ).fetchall(),
            "authority": self._execute(
                "SELECT slot, nonce, ciphertext FROM finalized_authority ORDER BY slot"
            ).fetchall(),
            "legacy_receipts": self._execute(
                "SELECT causal_id, status, reason_code FROM receipts ORDER BY causal_id"
            ).fetchall(),
            "receipts": self._execute(
                "SELECT causal_id, nonce, ciphertext FROM command_receipts_v2 ORDER BY causal_id"
            ).fetchall(),
            "pending": self._execute(
                "SELECT causal_id, record_id, nonce, ciphertext FROM pending_commands_v1 ORDER BY causal_id"
            ).fetchall(),
            "pending_effect_results": self._execute(
                "SELECT effect_id, causal_id, nonce, ciphertext FROM pending_effect_results_v1 ORDER BY effect_id"
            ).fetchall(),
            "terminal_observation": self._execute(
                "SELECT slot, nonce, ciphertext FROM terminal_observation_v1 ORDER BY slot"
            ).fetchall(),
            "current_head_observation_guard": self._execute(
                "SELECT slot, nonce, ciphertext FROM current_head_observation_guard_v1 ORDER BY slot"
            ).fetchall(),
        }

        def wire_value(value: object) -> object:
            if isinstance(value, bytes):
                return {"bytes": value.hex()}
            if isinstance(value, memoryview):
                return {"bytes": value.tobytes().hex()}
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            return {"unsupported": repr(value)}

        wire_tables = {
            table: [[wire_value(field) for field in row] for row in rows]
            for table, rows in tables.items()
        }
        encoded = json.dumps(wire_tables, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _refresh_integrity_manifest(self, connection: sqlite3.Connection) -> None:
        fingerprint = self._integrity_fingerprint()
        nonce, ciphertext = self._seal("integrity-manifest", {"fingerprint": fingerprint})
        connection.execute(
            """
            INSERT INTO integrity_manifest_v1(slot, nonce, ciphertext)
            VALUES (1, ?, ?)
            ON CONFLICT(slot) DO UPDATE SET nonce=excluded.nonce, ciphertext=excluded.ciphertext
            """,
            (nonce, ciphertext),
        )

    def _verify_integrity_manifest(self) -> None:
        row = self._execute(
            "SELECT nonce, ciphertext FROM integrity_manifest_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            raise KeyUnavailable("health state integrity manifest missing")
        stored = self._open("integrity-manifest", row[0], row[1])
        if not isinstance(stored, Mapping) or set(stored) != {"fingerprint"}:
            raise KeyUnavailable("health state integrity manifest invalid")
        fingerprint = stored["fingerprint"]
        if not isinstance(fingerprint, str) or fingerprint != self._integrity_fingerprint():
            raise KeyUnavailable("health state integrity manifest mismatch")

    def _assert_integrity_manifest_before_mutation(self) -> None:
        """Refuse to let a normal write re-sign externally altered state."""

        self._verify_integrity_manifest()

    def verify_key(self) -> str:
        self._initialize_or_verify_key_check()
        return self.key_id

    def terminal_observed(self) -> bool:
        """Return whether this durable state domain has observed a terminal head.

        The latch is deliberately irreversible through normal core APIs.  A
        same-named current-head recreated at an older nonterminal revision
        cannot reopen health/model/outbound paths after terminal observation.
        """

        row = self._execute(
            "SELECT nonce, ciphertext FROM terminal_observation_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            return False
        if self._open("terminal-observation", row[0], row[1]) != {"terminal": True}:
            raise KeyUnavailable("invalid terminal observation")
        return True

    def latch_terminal_observation(self) -> None:
        """Durably close this state domain after a current-head terminal read."""

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            row = connection.execute(
                "SELECT nonce, ciphertext FROM terminal_observation_v1 WHERE slot = 1"
            ).fetchone()
            if row is not None:
                if self._open("terminal-observation", row[0], row[1]) != {"terminal": True}:
                    raise KeyUnavailable("invalid terminal observation")
                return
            nonce, ciphertext = self._seal("terminal-observation", {"terminal": True})
            connection.execute(
                "INSERT INTO terminal_observation_v1(slot, nonce, ciphertext) VALUES (1, ?, ?)",
                (nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    def current_head_observation_guard(self) -> CurrentHeadObservationGuard | None:
        row = self._execute(
            "SELECT nonce, ciphertext FROM current_head_observation_guard_v1 WHERE slot = 1"
        ).fetchone()
        if row is None:
            return None
        return CurrentHeadObservationGuard.from_storage(
            self._open("current-head-observation-guard", row[0], row[1])
        )

    def current_head_observation_incomplete(self) -> bool:
        return self.current_head_observation_guard() is not None

    def arm_current_head_observation(
        self,
        binding: CurrentHeadRecoveryBinding | None = None,
    ) -> None:
        """Commit a pre-read tripwire before observing current-head state."""

        desired = CurrentHeadObservationGuard(binding=binding)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            row = connection.execute(
                "SELECT nonce, ciphertext FROM current_head_observation_guard_v1 WHERE slot = 1"
            ).fetchone()
            if row is not None:
                existing = CurrentHeadObservationGuard.from_storage(
                    self._open("current-head-observation-guard", row[0], row[1])
                )
                if existing != desired:
                    raise StoreUnavailable("current-head observation already incomplete")
                return
            nonce, ciphertext = self._seal("current-head-observation-guard", desired.to_storage())
            connection.execute(
                "INSERT INTO current_head_observation_guard_v1(slot, nonce, ciphertext) VALUES (1, ?, ?)",
                (nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    def clear_current_head_observation(
        self,
        binding: CurrentHeadRecoveryBinding | None = None,
    ) -> None:
        """Clear a completed nonterminal read tripwire in the same state domain."""

        expected = CurrentHeadObservationGuard(binding=binding)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            row = connection.execute(
                "SELECT nonce, ciphertext FROM current_head_observation_guard_v1 WHERE slot = 1"
            ).fetchone()
            if row is None:
                return
            existing = CurrentHeadObservationGuard.from_storage(
                self._open("current-head-observation-guard", row[0], row[1])
            )
            if existing != expected:
                raise StoreUnavailable("current-head observation guard binding mismatch")
            cursor = connection.execute("DELETE FROM current_head_observation_guard_v1 WHERE slot = 1")
            if cursor.rowcount:
                self._refresh_integrity_manifest(connection)

    def replace_current_head_observation(
        self,
        expected_binding: CurrentHeadRecoveryBinding | None,
        next_binding: CurrentHeadRecoveryBinding | None,
    ) -> None:
        """Atomically retarget a live tripwire to the next remote phase."""

        expected = CurrentHeadObservationGuard(binding=expected_binding)
        replacement = CurrentHeadObservationGuard(binding=next_binding)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            row = connection.execute(
                "SELECT nonce, ciphertext FROM current_head_observation_guard_v1 WHERE slot = 1"
            ).fetchone()
            if row is None:
                raise StoreUnavailable("current-head observation guard missing")
            existing = CurrentHeadObservationGuard.from_storage(
                self._open("current-head-observation-guard", row[0], row[1])
            )
            if existing != expected:
                raise StoreUnavailable("current-head observation guard binding mismatch")
            nonce, ciphertext = self._seal("current-head-observation-guard", replacement.to_storage())
            connection.execute(
                "UPDATE current_head_observation_guard_v1 SET nonce = ?, ciphertext = ? WHERE slot = 1",
                (nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    @contextmanager
    def serialized(self) -> Iterator[None]:
        """Hold the local single-writer lane across a remote CAS boundary.

        A commit first durably journals its causal identity, then may call the
        remote current-head port, and finally persists the local transition and
        replay receipt.  The journal must be its own committed transaction, but
        those phases still need one in-process writer lane.
        """

        with self._transaction_lock:
            yield

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One re-entrant transaction for a domain mutation and its receipt."""

        self._transaction_lock.acquire()
        outermost = self._transaction_depth == 0
        try:
            self._ensure_available()
            if outermost:
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                except sqlite3.Error as exc:
                    raise StoreUnavailable("health state transaction unavailable") from exc
            self._transaction_depth += 1
            try:
                yield self._connection
            except BaseException as exc:
                self._transaction_depth -= 1
                if outermost:
                    self._rollback_after_transaction_failure()
                if isinstance(exc, sqlite3.Error):
                    raise StoreUnavailable("health state transaction operation unavailable") from exc
                raise
            else:
                self._transaction_depth -= 1
                if outermost:
                    try:
                        self._connection.commit()
                    except sqlite3.Error as exc:
                        self._rollback_after_transaction_failure()
                        raise StoreUnavailable("health state commit unavailable") from exc
        finally:
            self._transaction_lock.release()

    def _rollback_after_transaction_failure(self) -> None:
        try:
            self._connection.rollback()
            if self._connection.in_transaction:
                self._poisoned = True
        except sqlite3.Error:
            # A connection that cannot roll back may expose uncommitted rows to
            # later reads.  It is permanently fail-closed until rebuilt.
            self._poisoned = True

    def receipt(self, command: CommandEnvelope) -> Response | None:
        row = self._execute(
            "SELECT nonce, ciphertext FROM command_receipts_v2 WHERE causal_id = ?",
            (command.causal_id,),
        ).fetchone()
        if row is None:
            legacy = self._execute(
                "SELECT 1 FROM receipts WHERE causal_id = ?",
                (command.causal_id,),
            ).fetchone()
            if legacy is not None:
                raise CausalIdConflict("legacy-receipt-unreplayable")
            return None
        stored_command, stored_response = self._decode_receipt(command.causal_id, row[0], row[1])
        if stored_command.to_wire() != self._receipt_command_wire(command):
            raise CausalIdConflict("causal-id-conflict")
        return stored_response

    def pending_command(self, command: CommandEnvelope) -> PendingCommand | None:
        row = self._execute(
            "SELECT record_id, nonce, ciphertext FROM pending_commands_v1 WHERE causal_id = ?",
            (command.causal_id,),
        ).fetchone()
        if row is None:
            return None
        pending = self._decode_pending(command.causal_id, row[0], row[1], row[2])
        if pending.command.to_wire() != command.to_wire():
            raise CausalIdConflict("causal-id-conflict")
        return pending

    def pending_for_record(self, record_id: str) -> PendingCommand | None:
        row = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM pending_commands_v1 WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return self._decode_pending(row[0], record_id, row[1], row[2])

    def has_pending_causal_id(self, causal_id: str) -> bool:
        return (
            self._execute(
                "SELECT 1 FROM pending_commands_v1 WHERE causal_id = ?",
                (causal_id,),
            ).fetchone()
            is not None
            or self._execute(
                "SELECT 1 FROM pending_effect_results_v1 WHERE causal_id = ?",
                (causal_id,),
            ).fetchone()
            is not None
        )

    def has_pending_commands(self) -> bool:
        return (
            self._execute("SELECT 1 FROM pending_commands_v1 LIMIT 1").fetchone()
            is not None
        )

    def pending_effect_result(self, effect_id: str) -> PendingEffectResult | None:
        row = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM pending_effect_results_v1 WHERE effect_id = ?",
            (effect_id,),
        ).fetchone()
        if row is None:
            return None
        return self._decode_pending_effect_result(effect_id, row[0], row[1], row[2])

    def reserve_pending_effect_result(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
    ) -> PendingEffectResult:
        """Give one exact effect terminal command durable recovery ownership."""

        attempt = PendingEffectResult.from_command(command, execution, remote_attempted=False)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            existing = self.pending_effect_result(attempt.effect_id)
            if existing is not None:
                if not existing.matches(command, execution):
                    raise CausalIdConflict("causal-id-conflict")
                return existing
            nonce, ciphertext = self._seal(
                f"pending-effect:{attempt.effect_id}",
                attempt.to_storage(),
            )
            try:
                connection.execute(
                    "INSERT INTO pending_effect_results_v1(effect_id, causal_id, nonce, ciphertext) VALUES (?, ?, ?, ?)",
                    (attempt.effect_id, attempt.causal_id, nonce, ciphertext),
                )
            except sqlite3.IntegrityError as exc:
                raise CausalIdConflict("causal-id-conflict") from exc
            self._refresh_integrity_manifest(connection)
        return attempt

    def mark_pending_effect_result_attempted(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
    ) -> PendingEffectResult:
        """Record that the exact owner is entering the remote release phase."""

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            pending = self.pending_effect_result(execution.intent.effect_id)
            if pending is None:
                raise KeyUnavailable("pending effect result missing")
            if not pending.matches(command, execution):
                raise CausalIdConflict("causal-id-conflict")
            if pending.remote_attempted:
                return pending
            attempted = PendingEffectResult.from_command(command, execution, remote_attempted=True)
            nonce, ciphertext = self._seal(
                f"pending-effect:{attempted.effect_id}",
                attempted.to_storage(),
            )
            connection.execute(
                "UPDATE pending_effect_results_v1 SET nonce = ?, ciphertext = ? WHERE effect_id = ?",
                (nonce, ciphertext, attempted.effect_id),
            )
            self._refresh_integrity_manifest(connection)
            return attempted

    def clear_unattempted_pending_effect_result(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
    ) -> bool:
        """Release only an exact effect owner that never reached remote release."""

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            pending = self.pending_effect_result(execution.intent.effect_id)
            if pending is None:
                return False
            if not pending.matches(command, execution):
                raise CausalIdConflict("causal-id-conflict")
            if pending.remote_attempted:
                return False
            connection.execute(
                "DELETE FROM pending_effect_results_v1 WHERE effect_id = ?",
                (execution.intent.effect_id,),
            )
            self._refresh_integrity_manifest(connection)
            return True

    def clear_pending_effect_result(
        self,
        command: CommandEnvelope,
        execution: ExecutingEffect,
    ) -> None:
        """Delete only the exact owner whose terminal result was committed."""

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            pending = self.pending_effect_result(execution.intent.effect_id)
            if pending is None:
                raise KeyUnavailable("pending effect result missing")
            if not pending.matches(command, execution):
                raise CausalIdConflict("causal-id-conflict")
            connection.execute(
                "DELETE FROM pending_effect_results_v1 WHERE effect_id = ?",
                (execution.intent.effect_id,),
            )
            self._refresh_integrity_manifest(connection)

    def reserve_pending_commit(self, command: CommandEnvelope, expected: PreparedTransition) -> bool:
        """Atomically reserve a still-prepared revision for one commit command.

        The caller has already read current-head and proved it equals
        ``expected.base``.  This SQLite transaction repeats the local record and
        pending checks immediately before insertion, preventing a second core
        process from inserting an orphan journal after another process finalizes
        the same record.
        """

        if not isinstance(expected, PreparedTransition):
            raise AuthorityValidationError("invalid pending commit preparation")
        payload = command.payload
        if not isinstance(payload, StateCommitPayload):
            raise ProtocolViolation("invalid commit payload")
        if (
            not expected.target.matches_commit(
                record_id=payload.record_id,
                revision_digest=payload.revision_digest,
                transition_id=payload.transition_id,
            )
            or command.generation != expected.base.generation
            or payload.writer_fence != expected.base.writer_fence
        ):
            raise ProtocolViolation("invalid pending commit target")
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            current = self.record(payload.record_id)
            if current is None or current.state != "prepared" or current.payload != expected:
                return False
            pending = self.pending_for_record(payload.record_id)
            if pending is not None:
                if pending.command.to_wire() != command.to_wire():
                    raise CausalIdConflict("causal-id-conflict")
                return True
            nonce, ciphertext = self._seal(
                f"pending:{command.causal_id}",
                {
                    "record_id": payload.record_id,
                    "command": command.to_wire(),
                    "remote_attempted": False,
                },
            )
            try:
                connection.execute(
                    "INSERT INTO pending_commands_v1(causal_id, record_id, nonce, ciphertext) VALUES (?, ?, ?, ?)",
                    (command.causal_id, payload.record_id, nonce, ciphertext),
                )
            except sqlite3.IntegrityError as exc:
                prior = self.pending_command(command)
                if prior is None or prior.record_id != payload.record_id:
                    raise CausalIdConflict("causal-id-conflict") from exc
            self._refresh_integrity_manifest(connection)
            return True

    def mark_pending_remote_attempted(self, command: CommandEnvelope) -> None:
        """Atomically mark the exact journal after its final pre-CAS read.

        Recovery may only treat a journal as ambiguous once this marker has
        committed.  An unattempted reservation is safe to discard when the
        second current-head read proves the prepared authority already stale.
        """

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            pending = self.pending_command(command)
            if pending is None:
                raise KeyUnavailable("pending command missing")
            if pending.remote_attempted:
                return
            nonce, ciphertext = self._seal(
                f"pending:{command.causal_id}",
                {
                    "record_id": pending.record_id,
                    "command": command.to_wire(),
                    "remote_attempted": True,
                },
            )
            connection.execute(
                "UPDATE pending_commands_v1 SET nonce = ?, ciphertext = ? WHERE causal_id = ?",
                (nonce, ciphertext, command.causal_id),
            )
            self._refresh_integrity_manifest(connection)

    def clear_unattempted_pending_command(self, command: CommandEnvelope) -> bool:
        """Discard only a definitely unattempted exact causal reservation."""

        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            pending = self.pending_command(command)
            if pending is None:
                return False
            if pending.remote_attempted:
                return False
            connection.execute("DELETE FROM pending_commands_v1 WHERE causal_id = ?", (command.causal_id,))
            self._refresh_integrity_manifest(connection)
            return True

    def write_pending_command(
        self,
        command: CommandEnvelope,
        record_id: str,
        *,
        remote_attempted: bool = False,
    ) -> None:
        if not isinstance(remote_attempted, bool):
            raise AuthorityValidationError("invalid pending command phase")
        nonce, ciphertext = self._seal(
            f"pending:{command.causal_id}",
            {
                "record_id": record_id,
                "command": command.to_wire(),
                "remote_attempted": remote_attempted,
            },
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            try:
                connection.execute(
                    "INSERT INTO pending_commands_v1(causal_id, record_id, nonce, ciphertext) VALUES (?, ?, ?, ?)",
                    (command.causal_id, record_id, nonce, ciphertext),
                )
            except sqlite3.IntegrityError as exc:
                prior = self.pending_command(command)
                if prior is None or prior.record_id != record_id:
                    raise CausalIdConflict("causal-id-conflict") from exc
            self._refresh_integrity_manifest(connection)

    def clear_pending_command(self, causal_id: str) -> None:
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            connection.execute("DELETE FROM pending_commands_v1 WHERE causal_id = ?", (causal_id,))
            self._refresh_integrity_manifest(connection)

    def save_receipt(self, command: CommandEnvelope, response: Response) -> None:
        """Persist an exact replay response inside the caller's transaction."""

        if response.causal_id != command.causal_id:
            raise KeyUnavailable("receipt causal identifier mismatch")
        receipt_command = self._receipt_command_wire(command)
        nonce, ciphertext = self._seal(
            f"receipt:v2:{command.causal_id}",
            {"command": receipt_command, "response": response.to_wire()},
        )
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            try:
                connection.execute(
                    "INSERT INTO command_receipts_v2(causal_id, nonce, ciphertext) VALUES (?, ?, ?)",
                    (command.causal_id, nonce, ciphertext),
                )
            except sqlite3.IntegrityError as exc:
                prior = self.receipt(command)
                if prior is None:
                    raise KeyUnavailable("receipt write conflict") from exc
                if prior.to_wire() != response.to_wire():
                    raise CausalIdConflict("causal-id-conflict") from exc
            self._refresh_integrity_manifest(connection)

    def write_record(
        self,
        record_id: str,
        state: str,
        revision_digest: str,
        transition_id: str,
        payload: RevisionTarget | PreparedTransition | CommittedTransition,
    ) -> None:
        self._validate_record_write(record_id, state, revision_digest, transition_id, payload)
        nonce, ciphertext = self._seal(f"record:{record_id}:{state}", payload.to_storage())
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            self._write_record_row(
                connection,
                record_id,
                state,
                revision_digest,
                transition_id,
                nonce,
                ciphertext,
            )
            self._refresh_integrity_manifest(connection)

    def write_finalized_record(
        self,
        record_id: str,
        revision_digest: str,
        transition_id: str,
        payload: CommittedTransition,
        authority: AuthoritySnapshot,
    ) -> None:
        self._validate_record_write(record_id, "final", revision_digest, transition_id, payload)
        if not isinstance(authority, AuthoritySnapshot) or payload.committed != authority:
            raise AuthorityValidationError("finalized authority mismatch")
        record_nonce, record_ciphertext = self._seal(f"record:{record_id}:final", payload.to_storage())
        authority_nonce, authority_ciphertext = self._seal_finalized_authority(authority, record_id)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            self._write_record_row(
                connection,
                record_id,
                "final",
                revision_digest,
                transition_id,
                record_nonce,
                record_ciphertext,
            )
            self._write_finalized_authority_row(connection, authority_nonce, authority_ciphertext)
            self._refresh_integrity_manifest(connection)

    def seed_finalized_authority(self, authority: AuthoritySnapshot) -> bool:
        if not isinstance(authority, AuthoritySnapshot):
            raise AuthorityValidationError("invalid finalized authority")
        # Synthetic setup may anchor an already-finalized installation before
        # this skeleton has a business record.  A real `write_finalized_record`
        # always carries the exact final-record identifier below.
        nonce, ciphertext = self._seal_finalized_authority(authority, None)
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            cursor = connection.execute(
                "INSERT OR IGNORE INTO finalized_authority(slot, nonce, ciphertext) VALUES (1, ?, ?)",
                (nonce, ciphertext),
            )
            if cursor.rowcount == 1:
                self._refresh_integrity_manifest(connection)
        return cursor.rowcount == 1

    def finalized_authority(self) -> AuthoritySnapshot | None:
        proof = self._finalized_proof()
        return None if proof is None else proof[0]

    def _finalized_proof(self) -> tuple[AuthoritySnapshot, str | None] | None:
        row = self._execute(
            "SELECT nonce, ciphertext FROM finalized_authority WHERE slot = 1"
        ).fetchone()
        if row is None:
            return None
        try:
            stored = self._open("finalized-authority", row[0], row[1])
            if isinstance(stored, Mapping) and set(stored) == {"authority", "record_id"}:
                record_id = stored["record_id"]
                if record_id is not None:
                    if not isinstance(record_id, str) or not record_id:
                        raise AuthorityValidationError("invalid finalized record identifier")
                return AuthoritySnapshot.from_storage(stored["authority"]), record_id
            # Read old synthetic anchors only as bootstrap anchors.  They are
            # never emitted by this version after a business finalization.
            return AuthoritySnapshot.from_storage(stored), None
        except ValueError as exc:
            raise KeyUnavailable("invalid finalized authority") from exc

    def record(self, record_id: str) -> StoredRecord | None:
        row = self._execute(
            "SELECT state, revision_digest, transition_id, nonce, ciphertext FROM health_records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return StoredRecord(
            state=row[0],
            revision_digest=row[1],
            transition_id=row[2],
            payload=self._decode_record_payload(
                row[0],
                self._open(f"record:{record_id}:{row[0]}", row[3], row[4]),
            ),
        )

    def record_state(self, record_id: str) -> str | None:
        row = self._execute("SELECT state FROM health_records WHERE record_id = ?", (record_id,)).fetchone()
        return None if row is None else row[0]

    def count_records(self) -> int:
        return int(self._execute("SELECT COUNT(*) FROM health_records").fetchone()[0])

    def unresolved_states(self) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in self._execute(
                "SELECT state FROM health_records WHERE state IN ('prepared', 'committed', 'unknown') ORDER BY record_id"
            ).fetchall()
        )

    def write_effect(
        self,
        effect_id: str,
        state: str,
        payload: EffectIntent | ClaimingEffect | ExecutingEffect | TerminalEffect,
    ) -> None:
        self._validate_effect_write(effect_id, state, payload)
        nonce, ciphertext = self._seal(f"effect:{effect_id}:{state}", payload.to_storage())
        with self.transaction() as connection:
            self._assert_integrity_manifest_before_mutation()
            connection.execute(
                "INSERT INTO effects(effect_id, state, nonce, ciphertext) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(effect_id) DO UPDATE SET state=excluded.state, nonce=excluded.nonce, ciphertext=excluded.ciphertext",
                (effect_id, state, nonce, ciphertext),
            )
            self._refresh_integrity_manifest(connection)

    def effect(self, effect_id: str) -> StoredEffect | None:
        row = self._execute(
            "SELECT state, nonce, ciphertext FROM effects WHERE effect_id = ?", (effect_id,)
        ).fetchone()
        if row is None:
            return None
        return StoredEffect(
            state=row[0],
            payload=self._decode_effect_payload(
                row[0],
                self._open(f"effect:{effect_id}:{row[0]}", row[1], row[2]),
            ),
        )

    def effect_state(self, effect_id: str) -> str | None:
        row = self._execute("SELECT state FROM effects WHERE effect_id = ?", (effect_id,)).fetchone()
        return None if row is None else row[0]

    def unresolved_effects(self) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in self._execute(
                "SELECT effect_id FROM effects WHERE state IN ('intent', 'claiming', 'executing', 'unknown') ORDER BY effect_id"
            ).fetchall()
        )

    def count_effects(self) -> int:
        return int(self._execute("SELECT COUNT(*) FROM effects").fetchone()[0])

    def verify_integrity(self, expected_authority: AuthoritySnapshot) -> bool:
        """Authenticate every local row before a probe can report healthy.

        SQLite state labels and identifiers are plaintext indexes.  They are
        never proof on their own: this scan decrypts every payload using its
        label-bound AAD and revalidates its typed relation to the indexes.
        The returned boolean additionally proves that a business finalization
        still has the encrypted final-record proof named by the authority row.
        """

        if not isinstance(expected_authority, AuthoritySnapshot):
            raise AuthorityValidationError("invalid expected finalized authority")
        self._verify_integrity_manifest()
        proof = self._finalized_proof()
        if proof is None:
            return False
        authority, finalized_record_id = proof
        if authority != expected_authority:
            return False

        final_record_found = finalized_record_id is None
        record_rows = self._execute(
            "SELECT record_id, state, revision_digest, transition_id, nonce, ciphertext "
            "FROM health_records ORDER BY record_id"
        ).fetchall()
        for record_id, state, revision_digest, transition_id, nonce, ciphertext in record_rows:
            try:
                payload = self._decode_record_payload(
                    state,
                    self._open(f"record:{record_id}:{state}", nonce, ciphertext),
                )
                self._validate_record_write(record_id, state, revision_digest, transition_id, payload)
            except AuthorityValidationError as exc:
                raise KeyUnavailable("invalid transition record") from exc
            if record_id == finalized_record_id:
                if (
                    state != "final"
                    or not isinstance(payload, CommittedTransition)
                    or payload.committed != authority
                ):
                    raise KeyUnavailable("finalized record authority mismatch")
                final_record_found = True

        effect_rows = self._execute(
            "SELECT effect_id, state, nonce, ciphertext FROM effects ORDER BY effect_id"
        ).fetchall()
        for effect_id, state, nonce, ciphertext in effect_rows:
            try:
                payload = self._decode_effect_payload(
                    state,
                    self._open(f"effect:{effect_id}:{state}", nonce, ciphertext),
                )
                self._validate_effect_write(effect_id, state, payload)
            except AuthorityValidationError as exc:
                raise KeyUnavailable("invalid effect record") from exc

        pending_rows = self._execute(
            "SELECT causal_id, record_id, nonce, ciphertext FROM pending_commands_v1 ORDER BY causal_id"
        ).fetchall()
        for causal_id, record_id, nonce, ciphertext in pending_rows:
            self._decode_pending(causal_id, record_id, nonce, ciphertext)

        pending_effect_rows = self._execute(
            "SELECT effect_id, causal_id, nonce, ciphertext FROM pending_effect_results_v1 ORDER BY effect_id"
        ).fetchall()
        for effect_id, causal_id, nonce, ciphertext in pending_effect_rows:
            self._decode_pending_effect_result(effect_id, causal_id, nonce, ciphertext)

        receipt_rows = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM command_receipts_v2 ORDER BY causal_id"
        ).fetchall()
        for causal_id, nonce, ciphertext in receipt_rows:
            self._decode_receipt(causal_id, nonce, ciphertext)

        # A terminal latch must itself be authenticated; its row is also part
        # of the signed inventory above, so raw deletion cannot silently reopen
        # the state domain.
        self.terminal_observed()
        self.current_head_observation_incomplete()

        if self._execute("SELECT 1 FROM receipts LIMIT 1").fetchone() is not None:
            # V1 rows do not retain an authenticated command/response pair and
            # therefore cannot prove an exact replay contract.
            raise KeyUnavailable("legacy receipt is unverifiable")
        return final_record_found

    def raw_storage_bytes(self) -> bytes:
        record_rows = self._execute(
            "SELECT record_id, state, revision_digest, transition_id, nonce, ciphertext FROM health_records"
        ).fetchall()
        effect_rows = self._execute("SELECT effect_id, state, nonce, ciphertext FROM effects").fetchall()
        authority_rows = self._execute(
            "SELECT nonce, ciphertext FROM finalized_authority"
        ).fetchall()
        receipt_rows = self._execute(
            "SELECT causal_id, nonce, ciphertext FROM command_receipts_v2"
        ).fetchall()
        pending_rows = self._execute(
            "SELECT causal_id, record_id, nonce, ciphertext FROM pending_commands_v1"
        ).fetchall()
        pending_effect_rows = self._execute(
            "SELECT effect_id, causal_id, nonce, ciphertext FROM pending_effect_results_v1"
        ).fetchall()
        terminal_rows = self._execute(
            "SELECT nonce, ciphertext FROM terminal_observation_v1"
        ).fetchall()
        observation_guard_rows = self._execute(
            "SELECT nonce, ciphertext FROM current_head_observation_guard_v1"
        ).fetchall()
        return repr(
            (
                record_rows,
                effect_rows,
                authority_rows,
                receipt_rows,
                pending_rows,
                pending_effect_rows,
                terminal_rows,
                observation_guard_rows,
            )
        ).encode("utf-8")

    def _decode_pending(
        self,
        causal_id: str,
        record_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> PendingCommand:
        stored = self._open(f"pending:{causal_id}", nonce, ciphertext)
        if (
            not isinstance(stored, Mapping)
            or set(stored) != {"record_id", "command", "remote_attempted"}
        ):
            raise KeyUnavailable("invalid pending command")
        if (
            stored["record_id"] != record_id
            or not isinstance(stored["command"], Mapping)
            or not isinstance(stored["remote_attempted"], bool)
        ):
            raise KeyUnavailable("invalid pending command")
        try:
            command = CommandEnvelope.from_wire(stored["command"])
        except ProtocolViolation as exc:
            raise KeyUnavailable("invalid pending command") from exc
        if command.causal_id != causal_id:
            raise KeyUnavailable("invalid pending command")
        return PendingCommand(
            record_id=record_id,
            command=command,
            remote_attempted=stored["remote_attempted"],
        )

    def _decode_pending_effect_result(
        self,
        effect_id: str,
        causal_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> PendingEffectResult:
        attempt = PendingEffectResult.from_storage(
            self._open(f"pending-effect:{effect_id}", nonce, ciphertext)
        )
        if attempt.effect_id != effect_id or attempt.causal_id != causal_id:
            raise KeyUnavailable("invalid pending effect result")
        return attempt

    @staticmethod
    def _receipt_command_wire(command: CommandEnvelope) -> dict[str, object]:
        """Return an exact replay identity without persisting a bearer secret.

        Effect-result completion capabilities are transport-only.  Receipts
        retain a one-way holder binding instead, which still distinguishes the
        original causal command while preventing a state/key clone from
        recovering an active execution capability after a rejected response.
        """

        wire = command.to_wire()
        if command.action != "effect.result":
            return wire
        payload = wire["payload"]
        if not isinstance(payload, dict):
            raise KeyUnavailable("invalid effect result receipt")
        capability = payload.get("completion_capability")
        try:
            payload["completion_capability"] = holder_id_for(capability)
        except ValueError as exc:
            raise KeyUnavailable("invalid effect result receipt") from exc
        return wire

    def _decode_receipt(
        self,
        causal_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> tuple[CommandEnvelope, Response]:
        stored = self._open(f"receipt:v2:{causal_id}", nonce, ciphertext)
        if not isinstance(stored, Mapping) or set(stored) != {"command", "response"}:
            raise KeyUnavailable("invalid command receipt")
        stored_command = stored["command"]
        stored_response = stored["response"]
        if not isinstance(stored_command, Mapping) or not isinstance(stored_response, Mapping):
            raise KeyUnavailable("invalid command receipt")
        try:
            command = CommandEnvelope.from_wire(stored_command)
            response = Response.from_wire(stored_response)
        except ProtocolViolation as exc:
            raise KeyUnavailable("invalid command receipt") from exc
        if command.causal_id != causal_id:
            raise KeyUnavailable("invalid command receipt")
        if response.causal_id != causal_id:
            raise KeyUnavailable("invalid command receipt")
        return command, response

    def _seal_finalized_authority(
        self,
        authority: AuthoritySnapshot,
        record_id: str | None,
    ) -> tuple[bytes, bytes]:
        if not isinstance(authority, AuthoritySnapshot):
            raise AuthorityValidationError("invalid finalized authority")
        if record_id is not None and (not isinstance(record_id, str) or not record_id):
            raise AuthorityValidationError("invalid finalized record identifier")
        return self._seal(
            "finalized-authority",
            {"authority": authority.to_storage(), "record_id": record_id},
        )

    @staticmethod
    def _validate_record_write(
        record_id: str,
        state: str,
        revision_digest: str,
        transition_id: str,
        payload: RevisionTarget | PreparedTransition | CommittedTransition,
    ) -> None:
        if state == "candidate" and type(payload) is RevisionTarget:
            target = payload
        elif state in {"prepared", "unknown"} and type(payload) is PreparedTransition:
            target = payload.target
        elif state in {"committed", "final"} and type(payload) is CommittedTransition:
            target = validate_committed_transition(payload).prepared.target
        else:
            raise AuthorityValidationError("record state and payload mismatch")
        if (
            record_id != target.record_id
            or revision_digest != target.revision_digest
            or transition_id != target.transition_id
        ):
            raise AuthorityValidationError("record target mismatch")

    @staticmethod
    def _validate_effect_write(
        effect_id: str,
        state: str,
        payload: EffectIntent | ClaimingEffect | ExecutingEffect | TerminalEffect,
    ) -> None:
        if state == "intent" and type(payload) is EffectIntent:
            intent = payload
        elif state == "claiming" and type(payload) is ClaimingEffect:
            intent = payload.intent
        elif state == "executing" and type(payload) is ExecutingEffect:
            intent = payload.intent
        elif state in {"accepted", "rejected", "unknown"} and type(payload) is TerminalEffect:
            if state != payload.status:
                raise AuthorityValidationError("effect terminal state mismatch")
            intent = payload.intent
        else:
            raise AuthorityValidationError("effect state and payload mismatch")
        if effect_id != intent.effect_id:
            raise AuthorityValidationError("effect identifier mismatch")
        validate_ticket110_effect_kind(intent.effect_kind)

    @staticmethod
    def _decode_record_payload(
        state: str,
        value: object,
    ) -> RevisionTarget | PreparedTransition | CommittedTransition:
        try:
            if state == "candidate":
                return RevisionTarget.from_storage(value)
            if state in {"prepared", "unknown"}:
                return PreparedTransition.from_storage(value)
            if state in {"committed", "final"}:
                return CommittedTransition.from_storage(value)
        except AuthorityValidationError as exc:
            raise KeyUnavailable("invalid transition record") from exc
        raise KeyUnavailable("invalid transition record state")

    @staticmethod
    def _decode_effect_payload(
        state: str,
        value: object,
    ) -> EffectIntent | ClaimingEffect | ExecutingEffect | TerminalEffect:
        try:
            if state == "intent":
                return EffectIntent.from_storage(value)
            if state == "claiming":
                return ClaimingEffect.from_storage(value)
            if state == "executing":
                return ExecutingEffect.from_storage(value)
            if state in {"accepted", "rejected", "unknown"}:
                return TerminalEffect.from_storage(value)
        except AuthorityValidationError as exc:
            raise KeyUnavailable("invalid effect record") from exc
        raise KeyUnavailable("invalid effect record state")

    @staticmethod
    def _write_record_row(
        connection: sqlite3.Connection,
        record_id: str,
        state: str,
        revision_digest: str,
        transition_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> None:
        connection.execute(
            """
            INSERT INTO health_records(record_id, state, revision_digest, transition_id, nonce, ciphertext)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id) DO UPDATE SET state=excluded.state,
                revision_digest=excluded.revision_digest, transition_id=excluded.transition_id,
                nonce=excluded.nonce, ciphertext=excluded.ciphertext
            """,
            (record_id, state, revision_digest, transition_id, nonce, ciphertext),
        )

    @staticmethod
    def _write_finalized_authority_row(
        connection: sqlite3.Connection,
        nonce: bytes,
        ciphertext: bytes,
    ) -> None:
        connection.execute(
            """
            INSERT INTO finalized_authority(slot, nonce, ciphertext)
            VALUES (1, ?, ?)
            ON CONFLICT(slot) DO UPDATE SET nonce=excluded.nonce, ciphertext=excluded.ciphertext
            """,
            (nonce, ciphertext),
        )

    def close(self) -> None:
        self._connection.close()

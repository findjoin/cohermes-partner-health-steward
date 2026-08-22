"""Core-owned encrypted local state store for synthetic validation."""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyUnavailable(RuntimeError):
    pass


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
        self._connection = sqlite3.connect(database, uri=database.startswith("file:"), check_same_thread=False)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(
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
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS effects (
                effect_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS receipts (causal_id TEXT PRIMARY KEY, status TEXT NOT NULL, reason_code TEXT)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS key_check (slot INTEGER PRIMARY KEY CHECK(slot = 1), key_id TEXT NOT NULL, nonce BLOB NOT NULL, ciphertext BLOB NOT NULL)"
        )
        self._connection.commit()
        self._initialize_or_verify_key_check()

    @property
    def key_id(self) -> str:
        return self._key_provider.key_id

    def _cipher(self) -> AESGCM:
        try:
            key = self._key_provider.get_key()
        except Exception as exc:  # key boundary deliberately collapses provider details
            raise KeyUnavailable("health key unavailable") from exc
        if not isinstance(key, bytes) or len(key) not in {16, 24, 32}:
            raise KeyUnavailable("health key invalid")
        return AESGCM(key)

    def _seal(self, aad: str, value: object) -> tuple[bytes, bytes]:
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return nonce, self._cipher().encrypt(nonce, plaintext, aad.encode("utf-8"))

    def _open(self, aad: str, nonce: bytes, ciphertext: bytes) -> object:
        try:
            plaintext = self._cipher().decrypt(nonce, ciphertext, aad.encode("utf-8"))
            return json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KeyUnavailable("health state authentication failed") from exc

    def _initialize_or_verify_key_check(self) -> None:
        row = self._connection.execute("SELECT key_id, nonce, ciphertext FROM key_check WHERE slot = 1").fetchone()
        if row is None:
            nonce, ciphertext = self._seal("key-check", {"marker": "health-core-key-check"})
            self._connection.execute(
                "INSERT INTO key_check(slot, key_id, nonce, ciphertext) VALUES (1, ?, ?, ?)",
                (self.key_id, nonce, ciphertext),
            )
            self._connection.commit()
            return
        if row[0] != self.key_id or self._open("key-check", row[1], row[2]) != {"marker": "health-core-key-check"}:
            raise KeyUnavailable("health key does not match state domain")

    def verify_key(self) -> str:
        self._initialize_or_verify_key_check()
        return self.key_id

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield self._connection
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def receipt(self, causal_id: str) -> tuple[str, str | None] | None:
        row = self._connection.execute("SELECT status, reason_code FROM receipts WHERE causal_id = ?", (causal_id,)).fetchone()
        return None if row is None else (row[0], row[1])

    def save_receipt(self, causal_id: str, status: str, reason_code: str | None = None) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO receipts(causal_id, status, reason_code) VALUES (?, ?, ?)",
            (causal_id, status, reason_code),
        )
        self._connection.commit()

    def write_record(self, record_id: str, state: str, revision_digest: str, transition_id: str, payload: object) -> None:
        nonce, ciphertext = self._seal(f"record:{record_id}:{state}", payload)
        self._connection.execute(
            """
            INSERT INTO health_records(record_id, state, revision_digest, transition_id, nonce, ciphertext)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id) DO UPDATE SET state=excluded.state,
                revision_digest=excluded.revision_digest, transition_id=excluded.transition_id,
                nonce=excluded.nonce, ciphertext=excluded.ciphertext
            """,
            (record_id, state, revision_digest, transition_id, nonce, ciphertext),
        )
        self._connection.commit()

    def record(self, record_id: str) -> tuple[str, str, str, object] | None:
        row = self._connection.execute(
            "SELECT state, revision_digest, transition_id, nonce, ciphertext FROM health_records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return row[0], row[1], row[2], self._open(f"record:{record_id}:{row[0]}", row[3], row[4])

    def record_state(self, record_id: str) -> str | None:
        row = self._connection.execute("SELECT state FROM health_records WHERE record_id = ?", (record_id,)).fetchone()
        return None if row is None else row[0]

    def count_records(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM health_records").fetchone()[0])

    def unresolved_states(self) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in self._connection.execute(
                "SELECT state FROM health_records WHERE state IN ('prepared', 'committed', 'unknown') ORDER BY record_id"
            ).fetchall()
        )

    def write_effect(self, effect_id: str, state: str, payload: object) -> None:
        nonce, ciphertext = self._seal(f"effect:{effect_id}:{state}", payload)
        self._connection.execute(
            "INSERT OR REPLACE INTO effects(effect_id, state, nonce, ciphertext) VALUES (?, ?, ?, ?)",
            (effect_id, state, nonce, ciphertext),
        )
        self._connection.commit()

    def effect_state(self, effect_id: str) -> str | None:
        row = self._connection.execute("SELECT state FROM effects WHERE effect_id = ?", (effect_id,)).fetchone()
        return None if row is None else row[0]

    def count_effects(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0])

    def raw_storage_bytes(self) -> bytes:
        record_rows = self._connection.execute(
            "SELECT record_id, state, revision_digest, transition_id, nonce, ciphertext FROM health_records"
        ).fetchall()
        effect_rows = self._connection.execute("SELECT effect_id, state, nonce, ciphertext FROM effects").fetchall()
        return repr((record_rows, effect_rows)).encode("utf-8")

    def close(self) -> None:
        self._connection.close()

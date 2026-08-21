"""Controlled historical state fixture for migration regression tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import shutil
from pathlib import Path


KEY_BYTES = 32
NONCE_BYTES = 16
MAC_BYTES = 32


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        output.extend(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(output[:length])


def _encrypt_payload(text: str, key: bytes) -> tuple[bytes, bytes, bytes]:
    plain = text.encode("utf-8")
    nonce = secrets.token_bytes(NONCE_BYTES)
    cipher = bytes(a ^ b for a, b in zip(plain, _keystream(key, nonce, len(plain))))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return nonce + mac + cipher, nonce, mac


def _wrap_record_key(master_key: bytes, record_key: bytes) -> str:
    nonce = secrets.token_bytes(NONCE_BYTES)
    wrapped = bytes(a ^ b for a, b in zip(record_key, _keystream(master_key, nonce, len(record_key))))
    mac = hmac.new(master_key, nonce + wrapped, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + mac + wrapped).decode("ascii")


def _encrypt_database(master_key: bytes, plain: bytes) -> bytes:
    nonce = secrets.token_bytes(NONCE_BYTES)
    cipher = bytes(a ^ b for a, b in zip(plain, _keystream(master_key, nonce, len(plain))))
    mac = hmac.new(master_key, nonce + cipher, hashlib.sha256).digest()
    return nonce + mac + cipher


def create_legacy_profile_fixture(
    state_path: Path,
    key_path: Path,
    backup_dir: Path,
    subject: str,
    status: dict,
) -> Path:
    """Write a pre-Ticket-07 master-scoped profile and encrypted backup."""
    master_key = key_path.read_bytes()
    record_key = secrets.token_bytes(KEY_BYTES)
    record_data = {
        "schema_version": 1,
        "subject": subject,
        "updated_utc": "2026-01-02T00:05:00+00:00",
        "version": 1,
        "status": status,
    }
    cipher_blob, nonce, mac = _encrypt_payload(
        json.dumps(record_data, ensure_ascii=False, sort_keys=True), record_key
    )
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE metadata(k TEXT PRIMARY KEY, v TEXT NOT NULL);")
        conn.executemany(
            "INSERT INTO metadata(k,v) VALUES(?,?);",
            [("schema_version", "1"), ("global_version", "1"), ("updated_utc", record_data["updated_utc"])],
        )
        conn.execute(
            """
            CREATE TABLE state_records(
                subject TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                version INTEGER NOT NULL,
                updated_utc TEXT NOT NULL,
                wrapped_key TEXT NOT NULL,
                nonce TEXT NOT NULL,
                mac TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO state_records(subject,schema_version,version,updated_utc,wrapped_key,nonce,mac,payload)
            VALUES(?,?,?,?,?,?,?,?);
            """,
            (
                subject,
                1,
                1,
                record_data["updated_utc"],
                _wrap_record_key(master_key, record_key),
                base64.urlsafe_b64encode(nonce).decode("ascii"),
                base64.urlsafe_b64encode(mac).decode("ascii"),
                base64.urlsafe_b64encode(cipher_blob).decode("ascii"),
            ),
        )
        encrypted = _encrypt_database(master_key, conn.serialize())
    finally:
        conn.close()

    state_path.write_bytes(encrypted)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{state_path.name}.20260102T000500000000Z.bak"
    shutil.copy2(state_path, backup)
    return backup

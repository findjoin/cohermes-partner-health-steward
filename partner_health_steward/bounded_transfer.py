"""Pure, bounded byte transport for one already authorized effect.

This module has no authority, I/O, persistence, retry or business state.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re

CHUNK_BYTES = 32768
MAX_TRANSFER_BYTES = 8388608
MAX_METADATA_BYTES = 16384
MAX_FRAME_BYTES = 65536


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def decode_canonical(data: bytes) -> object:
    if type(data) is not bytes or not 1 <= len(data) <= MAX_TRANSFER_BYTES:
        raise ValueError("invalid bounded transfer bytes")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate transfer field")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("invalid JSON constant")

    value = json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                       parse_constant=reject_constant)
    if canonical_bytes(value) != data:
        raise ValueError("noncanonical transfer")
    return value


def descriptor_for(data: bytes) -> dict:
    if type(data) is not bytes or not 1 <= len(data) <= MAX_TRANSFER_BYTES:
        raise ValueError("transfer outside byte limit")
    return {"size_bytes": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "chunk_count": (len(data) + CHUNK_BYTES - 1) // CHUNK_BYTES}


def validate_descriptor(value: object) -> dict:
    if type(value) is not dict or set(value) != {"size_bytes", "digest", "chunk_count"}:
        raise ValueError("invalid transfer descriptor")
    size, count, digest = value["size_bytes"], value["chunk_count"], value["digest"]
    if (type(size) is not int or not 1 <= size <= MAX_TRANSFER_BYTES
            or type(count) is not int or count != (size + CHUNK_BYTES - 1) // CHUNK_BYTES
            or type(digest) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None):
        raise ValueError("invalid transfer descriptor")
    return dict(value)


def chunk_bytes(data: bytes, index: int) -> bytes:
    descriptor = descriptor_for(data)
    if type(index) is not int or not 0 <= index < descriptor["chunk_count"]:
        raise ValueError("invalid transfer index")
    return data[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]


def encode_chunk(data: bytes, index: int) -> str:
    return base64.b64encode(chunk_bytes(data, index)).decode("ascii")


def decode_chunk(value: str, *, index: int, descriptor: dict) -> bytes:
    descriptor = validate_descriptor(descriptor)
    if (type(value) is not str or type(index) is not int
            or not 0 <= index < descriptor["chunk_count"]
            or len(value) > 4 * ((CHUNK_BYTES + 2) // 3)):
        raise ValueError("invalid transfer chunk")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid transfer base64") from exc
    expected = min(CHUNK_BYTES, descriptor["size_bytes"] - index * CHUNK_BYTES)
    if len(data) != expected or base64.b64encode(data).decode("ascii") != value:
        raise ValueError("invalid transfer chunk length or encoding")
    return data


def validate_bytes(data: bytes, descriptor: dict) -> bytes:
    if descriptor_for(data) != validate_descriptor(descriptor):
        raise ValueError("transfer size or digest mismatch")
    return data

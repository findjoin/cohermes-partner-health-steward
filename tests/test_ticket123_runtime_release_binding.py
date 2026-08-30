"""Ordinary regression coverage for Ticket 123 runtime/release binding."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from partner_health_steward.release_deployment import HermesReleasePublisher


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_ATTESTATION_PATH = "runtime/ticket123-runtime-closure-attestation.json"
_ATTESTATION_CONTRACT = "ticket123-runtime-closure-attestation-v1"
_CLOSURE_ALGORITHM = "sha256(canonical-json(files))"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _runtime_manifest() -> dict[str, object]:
    files = [
        {"path": "bin/python3", "sha256": "sha256:" + "1" * 64},
        {"path": "lib/python3.11/os.py", "sha256": "sha256:" + "2" * 64},
        {
            "path": "lib/python3.11/site-packages/cryptography/__init__.py",
            "sha256": "sha256:" + "3" * 64,
        },
        {
            "path": "lib/python3.11/site-packages/partner_health_steward/production_core_service.py",
            "sha256": "sha256:" + "4" * 64,
        },
    ]
    return {
        "contract": "ticket123-runtime-closure-v1",
        "files": files,
        "closure_digest": _digest(_canonical(files)),
    }


class Ticket123RuntimeReleaseBindingTests(unittest.TestCase):
    """The public publisher seam creates the sole attested current successor."""

    def test_current_successor_is_content_addressed_and_preserves_staged_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ticket123-release-binding-") as raw:
            output_root = Path(raw) / "releases"
            publisher = HermesReleasePublisher(_REPOSITORY_ROOT)
            staged = publisher.build(output_root)
            staged_wire = staged.to_wire()
            staged_digest = staged_wire["release_digest"]
            self.assertIsInstance(staged_digest, str)
            assert isinstance(staged_digest, str)
            staged_root = output_root / staged_digest.removeprefix("sha256:")
            staged_bytes = {
                path.relative_to(staged_root).as_posix(): path.read_bytes()
                for path in staged_root.rglob("*")
                if path.is_file() and not path.is_symlink()
            }
            runtime_manifest = _runtime_manifest()

            current = publisher.publish_current_successor(
                staged_root, copy.deepcopy(runtime_manifest)
            )

            current_wire = current.to_wire()
            self.assertEqual(current_wire["state"], "current")
            successor_digest = current_wire["release_digest"]
            self.assertIsInstance(successor_digest, str)
            assert isinstance(successor_digest, str)
            self.assertNotEqual(successor_digest, staged_digest)
            successor_root = output_root / successor_digest.removeprefix("sha256:")
            self.assertTrue(successor_root.is_dir())
            self.assertNotEqual(successor_root, staged_root)
            self.assertEqual(staged.to_wire(), staged_wire)
            self.assertEqual(
                staged_bytes,
                {
                    path.relative_to(staged_root).as_posix(): path.read_bytes()
                    for path in staged_root.rglob("*")
                    if path.is_file() and not path.is_symlink()
                },
            )

            release_manifest = json.loads(
                (successor_root / "release-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(release_manifest, current_wire)
            attestation_bytes = (successor_root / _ATTESTATION_PATH).read_bytes()
            self.assertEqual(
                json.loads(attestation_bytes.decode("utf-8")),
                {
                    "contract": _ATTESTATION_CONTRACT,
                    "closure_algorithm": _CLOSURE_ALGORITHM,
                    "expected_closure_digest": runtime_manifest["closure_digest"],
                },
            )
            self.assertNotIn("release_digest", attestation_bytes.decode("utf-8"))
            release_files = {
                entry["path"]: entry["sha256"] for entry in release_manifest["files"]
            }
            self.assertEqual(release_files[_ATTESTATION_PATH], _digest(attestation_bytes))
            host_manifest = json.loads(
                (successor_root / "host-release-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                successor_digest,
                _digest(
                    _canonical(
                        {
                            "contract": release_manifest["contract"],
                            "state": release_manifest["state"],
                            "files": release_manifest["files"],
                            "host_release_manifest": host_manifest,
                        }
                    )
                ),
            )

            invalid_manifest = copy.deepcopy(runtime_manifest)
            invalid_manifest["unexpected"] = True
            with self.assertRaises(ValueError):
                publisher.publish_current_successor(staged_root, invalid_manifest)

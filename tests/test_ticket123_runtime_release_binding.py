"""Ordinary regression coverage for Ticket 123 runtime/release binding."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from tests import test_ticket123_production_core_service as _frozen_ticket123


_SHA256 = "sha256:"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _closure_entry(manifest: dict[str, object], suffix: str) -> dict[str, object]:
    files = manifest.get("files")
    if type(files) is not list:
        raise AssertionError("runtime closure fixture is invalid")
    matches = [
        entry
        for entry in files
        if type(entry) is dict
        and type(entry.get("path")) is str
        and (entry["path"] == suffix or entry["path"].endswith("/" + suffix))
    ]
    if len(matches) != 1:
        raise AssertionError(f"runtime closure lacks one {suffix} entry")
    return matches[0]


def _update_entry(runtime_root: Path, manifest: dict[str, object], suffix: str, payload: bytes) -> None:
    entry = _closure_entry(manifest, suffix)
    relative = entry["path"]
    if type(relative) is not str:
        raise AssertionError("runtime closure path is invalid")
    path = runtime_root / relative
    path.write_bytes(payload)
    entry["sha256"] = _SHA256 + hashlib.sha256(payload).hexdigest()


def _run_release_unbound_runtime(root: Path) -> None:
    """Exercise only public start/probe behavior in the cloned runtime."""

    _frozen_ticket123.Ticket123ProductionCoreServiceTests.setUpClass()
    case = _frozen_ticket123.Ticket123ProductionCoreServiceTests(
        "test_v123_01_composition_is_release_bound_and_staged_is_truthfully_unavailable"
    )
    module, binding, current_head, _client = case._fixture(root)
    manifest = json.loads(
        (Path(binding["runtime_root"]) / "ticket123-runtime-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if binding["runtime_manifest"] != manifest:
        raise AssertionError("tampered runtime manifest did not reach the local binding")
    service_type = getattr(module, "ProductionCoreService", None)
    if not callable(service_type):
        raise AssertionError("ProductionCoreService is unavailable")
    service = service_type(copy.deepcopy(binding), current_head=current_head)
    socket_path = Path(binding["socket_path"])
    try:
        endpoint = service.start()
    except Exception:
        if socket_path.exists():
            raise AssertionError("rejected runtime created a CorePort socket")
        print("TICKET123-RUNTIME-RELEASE-REJECTED-BEFORE-ACTIVATION", flush=True)
        return
    try:
        response = case._request(endpoint, case._runtime_read())
        if response is None or response.get("status") != "accepted":
            raise AssertionError("accepted runtime did not expose the public runtime probe")
        print("TICKET123-RUNTIME-RELEASE-TAMPER-ACCEPTED", flush=True)
        raise AssertionError("release-unbound runtime activated a public CorePort")
    finally:
        service.close()


@unittest.skipUnless(sys.platform == "linux", "requires the Ticket 123 Linux runtime")
class Ticket123RuntimeReleaseBindingTests(unittest.TestCase):
    """A self-rehashed local runtime must still be bound to its release."""

    def test_self_rehashed_runtime_without_verified_release_content_is_rejected(self) -> None:
        _frozen_ticket123.Ticket123ProductionCoreServiceTests.setUpClass()
        fixture = _frozen_ticket123.Ticket123ProductionCoreServiceTests(
            "test_v123_01_composition_is_release_bound_and_staged_is_truthfully_unavailable"
        )
        runtime_root, _manifest = fixture._runtime()
        with tempfile.TemporaryDirectory(prefix="ticket123-release-binding-") as raw:
            root = Path(raw)
            cloned_runtime = root / "runtime"
            shutil.copytree(runtime_root, cloned_runtime)
            manifest_path = cloned_runtime / "ticket123-runtime-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if type(manifest) is not dict:
                self.fail("runtime closure fixture is invalid")

            _update_entry(
                cloned_runtime,
                manifest,
                "partner_health_steward/production_core_service.py",
                (_REPOSITORY_ROOT / "partner_health_steward" / "production_core_service.py").read_bytes(),
            )
            core_entry = _closure_entry(manifest, "partner_health_steward/core.py")
            core_relative = core_entry["path"]
            if type(core_relative) is not str:
                self.fail("runtime core path is invalid")
            core_payload = (cloned_runtime / core_relative).read_bytes() + b"\n# ticket123-release-binding-tamper\n"
            _update_entry(
                cloned_runtime,
                manifest,
                "partner_health_steward/core.py",
                core_payload,
            )
            files = manifest.get("files")
            if type(files) is not list:
                self.fail("runtime closure file table is invalid")
            manifest["closure_digest"] = _SHA256 + hashlib.sha256(_canonical(files)).hexdigest()
            manifest_path.write_bytes(_canonical(manifest))

            environment = dict(os.environ)
            environment["TICKET123_RUNTIME_ROOT"] = str(cloned_runtime)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [
                    str(cloned_runtime / "bin" / "python3"),
                    "-I",
                    "-B",
                    str(Path(__file__).resolve()),
                    "--release-unbound-runtime",
                    str(root / "process"),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "TICKET123-RUNTIME-RELEASE-REJECTED-BEFORE-ACTIVATION",
                result.stdout,
            )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--release-unbound-runtime":
        _run_release_unbound_runtime(Path(sys.argv[2]))
    else:
        unittest.main()

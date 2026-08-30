"""Verifier-owned frozen gates for Ticket 123.

The formal suite is Linux-only.  It crosses the production composition-root,
AF_UNIX CorePort and the two pre-existing Ticket 117 lifecycle adapter seams;
it never contacts AWS, Hermes, a model, Weixin or a real health directory.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from partner_health_steward.authority import AuthoritySnapshot
from partner_health_steward.lifecycle import LIFECYCLE_PURGE_BINDINGS
from partner_health_steward.release_deployment import HermesReleasePublisher
from partner_health_steward.storage import EncryptedStateStore


_INSTALLATION = "installation:t123-fixture"
_SITE = "site:t123-fixture"
_DATA_KEY = bytes(range(32))
_WRITER_MASTER = bytes(range(32, 64))
_EXECUTION_MASTER = bytes(range(64, 96))


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _recv_exact(connection: socket.socket, size: int) -> bytes | None:
    result = bytearray()
    while len(result) < size:
        part = connection.recv(size - len(result))
        if not part:
            return None
        result.extend(part)
    return bytes(result)


def _outer_frame(value: object) -> bytes:
    body = _canonical(value)
    return struct.pack(">I", len(body)) + body


def _decode_outer(frame: bytes) -> dict[str, object]:
    if len(frame) < 4:
        raise AssertionError("response is truncated")
    size = struct.unpack(">I", frame[:4])[0]
    if size != len(frame) - 4:
        raise AssertionError("response has trailing or truncated bytes")
    value = json.loads(frame[4:].decode("utf-8"))
    if type(value) is not dict:
        raise AssertionError("response is not a mapping")
    return value


class Ticket123ProductionCoreServiceTests(unittest.TestCase):
    """Seven gates, each killing one bounded Ticket 123 reality error."""

    module = None
    prerequisite_error: BaseException | None = None

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.module = importlib.import_module(
                "partner_health_steward.production_core_service"
            )
        except BaseException as exc:
            cls.prerequisite_error = exc

    def _require(self, *, red: bool = False):
        if self.module is None:
            message = "Ticket 123 production core service module is absent"
            if red:
                self.fail(message)
            self.skipTest(message)
        if sys.platform != "linux":
            self.skipTest("Ticket 123 formal gates require isolated Linux")
        return self.module

    @staticmethod
    def _facility(module: object, root: Path):
        facility = root / "authority"
        facility.mkdir(parents=True, mode=0o700)
        for name, value in (
            ("data-key.v1", _DATA_KEY),
            ("writer-master.v1", _WRITER_MASTER),
            ("execution-master.v1", _EXECUTION_MASTER),
        ):
            path = facility / name
            path.write_bytes(value)
            path.chmod(0o400)
        locks = facility / "locks"
        locks.mkdir(mode=0o700)
        return module.HostPrivateFacilityPaths(
            data_key=facility / "data-key.v1",
            writer_master=facility / "writer-master.v1",
            execution_master=facility / "execution-master.v1",
            lock_directory=locks,
        )

    def _runtime(self) -> tuple[Path, dict[str, object]]:
        raw = os.environ.get("TICKET123_RUNTIME_ROOT")
        if not raw:
            self.fail("TICKET123_RUNTIME_ROOT is required for the formal Linux gate")
        root = Path(raw).resolve()
        manifest_path = root / "ticket123-runtime-manifest.json"
        if not root.is_dir() or not manifest_path.is_file() or manifest_path.is_symlink():
            self.fail("Ticket 123 runtime closure is unavailable")
        try:
            executable = Path(sys.executable).resolve()
            executable.relative_to(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            self.fail("tests are not running from the declared runtime closure")
        if type(manifest) is not dict:
            self.fail("Ticket 123 runtime manifest is invalid")
        return root, manifest

    @staticmethod
    def _release(root: Path) -> tuple[Path, dict[str, object]]:
        published = HermesReleasePublisher(Path(__file__).resolve().parents[1]).build(
            root / "releases"
        )
        wire = published.to_wire()
        digest = wire["release_digest"]
        assert type(digest) is str
        return root / "releases" / digest.removeprefix("sha256:"), wire

    def _fixture(self, root: Path):
        module = self._require()
        host = importlib.import_module("partner_health_steward.host_authority")
        ddb = importlib.import_module("partner_health_steward.dynamodb_current_head")
        t122 = importlib.import_module("tests.test_ticket122_dynamodb_current_head")
        runtime_root, runtime_manifest = self._runtime()
        release_root, release_manifest = self._release(root)
        facility = self._facility(host, root)
        writer = host.HostPrivateWriterFenceVault(facility)
        fence = writer.prepare_fence_ref(
            _INSTALLATION, _SITE, "writer-epoch:t123-initial"
        )
        client = t122._ScriptedDynamo()
        client.records["HEAD"] = {
            "PK": {"S": _INSTALLATION},
            "SK": {"S": "HEAD"},
            "schema_version": {"N": "1"},
            "generation": {"N": "1"},
            "revision_digest": {"S": "sha256:t123-empty"},
            "transition_id": {"S": "transition:t123-empty"},
            "writer_fence": {"S": fence},
            "terminal": {"BOOL": False},
            "site": {"S": _SITE},
        }
        client.guard_generation = {"N": "1"}
        client.guard_fence = {"S": fence}
        current_head = ddb.DynamoDBCurrentHead(
            client,
            ddb.DynamoHeadBinding(
                region="us-east-1",
                table_name="t122-fixture",
                table_arn=t122._TABLE_ARN,
                table_id="11111111-2222-3333-4444-555555555555",
                installation_id=_INSTALLATION,
                local_site=_SITE,
                local_writer_fence_ref=fence,
            ),
        )
        authority = current_head.read().head.as_authority()
        database = root / "state" / "health.sqlite"
        database.parent.mkdir(mode=0o700)
        key_provider = host.HostPrivateKeyProvider(facility, _INSTALLATION)
        store = EncryptedStateStore(str(database), key_provider)
        store.seed_finalized_authority(authority)
        store.close()
        replica_root = root / "managed"
        replica_root.mkdir(mode=0o700)
        replica_bindings: dict[str, str] = {}
        for index, binding in enumerate(LIFECYCLE_PURGE_BINDINGS):
            target = replica_root / f"object-{index:02d}.managed"
            target.write_bytes(_canonical({"binding": binding}))
            target.chmod(0o600)
            replica_bindings[binding] = str(target)
        migration_root = root / "migration"
        migration_root.mkdir(mode=0o700)
        socket_root = root / "run"
        socket_root.mkdir(mode=0o700)
        binding = {
            "contract": "ticket123-production-core-binding-v1",
            "release_root": str(release_root),
            "release_digest": release_manifest["release_digest"],
            "runtime_root": str(runtime_root),
            "runtime_manifest": runtime_manifest,
            "installation_id": _INSTALLATION,
            "site": _SITE,
            "database_path": str(database),
            "socket_path": str(socket_root / "health-core.sock"),
            "socket_owner_uid": os.geteuid(),
            "socket_group_gid": os.getegid(),
            "socket_mode": 0o660,
            "allowed_peer_uid": os.geteuid(),
            "host_private_paths": facility,
            "managed_replica_root": str(replica_root),
            "managed_replica_bindings": replica_bindings,
            "migration_artifact_root": str(migration_root),
            "lifecycle_release": {
                "product_release": release_manifest["release_digest"],
                "adr": "ADR-0022",
                "skills": [
                    "health-init",
                    "health-steward",
                    "health-settings",
                    "health-portrait",
                    "health-evidence",
                    "health-owner-inquiry",
                    "health-literature",
                ],
                "plugin_core_bundle": "sha256:" + "1" * 64,
                "adapter_model_interface_bundle": "sha256:" + "2" * 64,
                "knowledge_safety_diagnostic_bundle": "sha256:" + "3" * 64,
                "hermes_artifact": "sha256:" + "4" * 64,
                "required_patch": "sha256:" + "5" * 64,
                "disabled_native_entry_assertion": True,
                "schema": "ticket117-semantic-state-v1",
                "observer_identity": "observer:ticket123-local",
                "acl_service": "acl-service:ticket123-local",
                "secret_requirements": ["health-key-ref", "target-fence-ref"],
                "unbound_real_providers": [],
            },
        }
        return module, binding, current_head, client

    @staticmethod
    def _start(module: object, binding: dict[str, object], current_head: object):
        service_type = getattr(module, "ProductionCoreService", None)
        if not callable(service_type):
            raise AssertionError("ProductionCoreService is not implemented")
        service = service_type(copy.deepcopy(binding), current_head=current_head)
        endpoint = service.start()
        if type(endpoint) is not dict:
            raise AssertionError("ProductionCoreService.start did not return an endpoint")
        return service, endpoint

    @staticmethod
    def _request(endpoint: dict[str, object], value: dict[str, object]) -> dict[str, object] | None:
        if endpoint.get("transport") != "af-unix" or type(endpoint.get("path")) is not str:
            raise AssertionError("production endpoint is not AF_UNIX")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(endpoint["path"])
            connection.sendall(_outer_frame(value))
            header = _recv_exact(connection, 4)
            if header is None:
                return None
            size = struct.unpack(">I", header)[0]
            body = _recv_exact(connection, size)
            if body is None:
                return None
            trailing = connection.recv(1)
            if trailing:
                raise AssertionError("production response has trailing bytes")
            return _decode_outer(header + body)

    @staticmethod
    def _runtime_read() -> dict[str, object]:
        return {
            "protocol_version": 1,
            "kind": "managed-read",
            "request_id": "ticket123-runtime-read",
            "payload": {"projection": "health-runtime"},
        }

    @staticmethod
    def _probe_command() -> dict[str, object]:
        return {
            "protocol_version": 1,
            "kind": "command",
            "request_id": "ticket123-command-probe",
            "payload": {
                "interface": "command-v1",
                "command": {
                    "protocol_version": 1,
                    "peer": "plugin",
                    "action": "probe",
                    "source": "health_weixin",
                    "causal_id": "ticket123-probe",
                    "generation": 1,
                    "scope": ["probe"],
                    "payload": {},
                },
            },
        }

    def test_v123_01_composition_is_release_bound_and_staged_is_truthfully_unavailable(self) -> None:
        self._require(red=True)
        with tempfile.TemporaryDirectory(prefix="ticket123-") as raw:
            root = Path(raw)
            module, binding, current_head, _client = self._fixture(root)
            service, endpoint = self._start(module, binding, current_head)
            try:
                response = self._request(endpoint, self._runtime_read())
                self.assertIsNotNone(response)
                assert response is not None
                self.assertEqual(response["status"], "accepted")
                projection = response["payload"]
                self.assertEqual(projection.get("state"), "unavailable")
                self.assertNotEqual(projection.get("reason_code"), "health-core-staged")
                self.assertEqual(projection.get("generation"), 1)
                self.assertFalse(projection.get("health_writes_allowed"))
                self.assertFalse(projection.get("model_effects_allowed"))
                self.assertFalse(projection.get("outbound_effects_allowed"))
            finally:
                service.close()

            for name, mutate in (
                ("release-digest", lambda value: value.__setitem__("release_digest", "sha256:" + "0" * 64)),
                ("runtime-digest", lambda value: value["runtime_manifest"].__setitem__("closure_digest", "sha256:" + "0" * 64)),
                ("wide-socket", lambda value: value.__setitem__("socket_mode", 0o666)),
            ):
                with self.subTest(name=name):
                    candidate = copy.deepcopy(binding)
                    candidate["socket_path"] = str(root / f"{name}.sock")
                    mutate(candidate)
                    with self.assertRaises(Exception):
                        self._start(module, candidate, current_head)
                    self.assertFalse(Path(candidate["socket_path"]).exists())

    def test_v123_02_af_unix_acl_and_peer_credentials_are_both_enforced(self) -> None:
        module = self._require()
        if os.geteuid() != 0:
            self.fail("V123-02 requires an isolated root-runner for wrong-UID SO_PEERCRED")
        import pwd

        with tempfile.TemporaryDirectory(prefix="ticket123-") as raw:
            root = Path(raw)
            module, binding, current_head, _client = self._fixture(root)
            service, endpoint = self._start(module, binding, current_head)
            socket_path = Path(endpoint["path"])
            try:
                details = socket_path.lstat()
                self.assertTrue(stat.S_ISSOCK(details.st_mode))
                self.assertEqual(stat.S_IMODE(details.st_mode), 0o660)
                self.assertEqual(details.st_uid, binding["socket_owner_uid"])
                self.assertEqual(details.st_gid, binding["socket_group_gid"])
                self.assertIsNotNone(self._request(endpoint, self._runtime_read()))

                wrong_uid = pwd.getpwnam("nobody").pw_uid
                socket_path.chmod(0o666)  # File ACL alone must not defeat SO_PEERCRED.
                script = """
import json, os, socket, struct, sys
os.setgid(int(sys.argv[2])); os.setuid(int(sys.argv[1]))
request={'protocol_version':1,'kind':'managed-read','request_id':'wrong-peer','payload':{'projection':'health-runtime'}}
body=json.dumps(request,separators=(',',':'),sort_keys=True).encode()
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.settimeout(1); s.connect(sys.argv[3]); s.sendall(struct.pack('>I',len(body))+body)
try: data=s.recv(1)
except Exception: data=b''
raise SystemExit(0 if data==b'' else 9)
"""
                wrong = subprocess.run(
                    [sys.executable, "-I", "-c", script, str(wrong_uid), str(wrong_uid), str(socket_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(wrong.returncode, 0, wrong.stderr)
            finally:
                service.close()
            self.assertFalse(socket_path.exists())

            symlink_binding = copy.deepcopy(binding)
            symlink_binding["socket_path"] = str(root / "symlink.sock")
            Path(symlink_binding["socket_path"]).symlink_to(root / "target.sock")
            with self.assertRaises(Exception):
                self._start(module, symlink_binding, current_head)

    def test_v123_03_all_three_coreport_kinds_use_one_strict_byte_stream(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket123-") as raw:
            module, binding, current_head, _client = self._fixture(Path(raw))
            service, endpoint = self._start(module, binding, current_head)
            try:
                command = self._request(endpoint, self._probe_command())
                managed = self._request(endpoint, self._runtime_read())
                controlled = self._request(
                    endpoint,
                    {
                        "protocol_version": 1,
                        "kind": "controlled-effect",
                        "request_id": "ticket123-forged-claim",
                        "payload": {
                            "phase": "claim",
                            "intent": {
                                "effect_id": "effect:forged",
                                "intent_digest": "sha256:forged",
                                "effect_kind": "model-work",
                                "authority": {
                                    "installation_id": _INSTALLATION,
                                    "generation": 1,
                                    "revision_digest": "sha256:t123-empty",
                                    "transition_id": "transition:t123-empty",
                                    "writer_fence": "fence:forged",
                                    "terminal": False,
                                    "site": _SITE,
                                },
                            },
                        },
                    },
                )
                self.assertEqual(command["kind"], "command")
                self.assertEqual(managed["kind"], "managed-read")
                self.assertEqual(controlled["kind"], "controlled-effect")
                self.assertIsNone(controlled["payload"].get("grant"))

                malformed = (
                    b'{"kind":"managed-read","kind":"command","payload":{},'
                    b'"protocol_version":1,"request_id":"duplicate"}'
                )
                cases = (
                    struct.pack(">I", len(malformed)) + malformed,
                    _outer_frame({"protocol_version": 1, "kind": "unknown", "request_id": "x", "payload": {}}),
                    struct.pack(">I", 9) + b"{}",
                    struct.pack(">I", 65537),
                )
                for frame in cases:
                    with self.subTest(frame=frame[:16]):
                        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                            connection.settimeout(1)
                            connection.connect(endpoint["path"])
                            connection.sendall(frame)
                            try:
                                observed = connection.recv(1)
                            except (ConnectionResetError, socket.timeout):
                                observed = b""
                            self.assertEqual(observed, b"")
            finally:
                service.close()

    def test_v123_04_restart_and_authority_faults_do_not_create_a_second_result(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket123-") as raw:
            module, binding, current_head, client = self._fixture(Path(raw))
            service, endpoint = self._start(module, binding, current_head)
            first = self._request(endpoint, self._probe_command())
            service.close()
            service, endpoint = self._start(module, binding, current_head)
            try:
                replay = self._request(endpoint, self._probe_command())
                self.assertEqual(replay, first)
                self.assertFalse(
                    any(name == "TransactWriteItems" for name, _ in client.calls)
                )
                client.get_error = TimeoutError("synthetic response unknown")
                unknown = self._request(endpoint, self._runtime_read())
                self.assertIn(unknown["payload"].get("state"), {"unavailable", "unknown"})
                self.assertFalse(unknown["payload"].get("model_effects_allowed"))
                self.assertFalse(unknown["payload"].get("outbound_effects_allowed"))
            finally:
                service.close()

    def test_v123_05_filesystem_lifecycle_adapters_are_atomic_and_restartable(self) -> None:
        module = self._require()
        managed_type = getattr(module, "FilesystemManagedReplicaAdapter", None)
        artifact_type = getattr(module, "FilesystemMigrationArtifactAdapter", None)
        self.assertTrue(callable(managed_type) and callable(artifact_type))
        with tempfile.TemporaryDirectory(prefix="ticket123-") as raw:
            root = Path(raw)
            managed_root = root / "managed"
            managed_root.mkdir(mode=0o700)
            bindings: dict[str, str] = {}
            for index, binding in enumerate(LIFECYCLE_PURGE_BINDINGS):
                path = managed_root / f"replica-{index:02d}"
                path.write_bytes(_canonical({"binding": binding}))
                path.chmod(0o600)
                bindings[binding] = str(path)
            request = {"installation_id": _INSTALLATION}
            managed = managed_type(managed_root, _INSTALLATION, bindings, ())
            self.assertEqual(
                set(managed.enumerate(request)["configured"]),
                set(LIFECYCLE_PURGE_BINDINGS),
            )
            purge = managed.purge(
                {
                    "installation_id": _INSTALLATION,
                    "operation_ref": "delete:t123",
                    "purge_bindings": list(LIFECYCLE_PURGE_BINDINGS),
                }
            )
            self.assertEqual(purge["status"], "confirmed")
            restarted = managed_type(managed_root, _INSTALLATION, bindings, ())
            self.assertEqual(restarted.absence(request)["status"], "absent")

            artifact_root = root / "artifacts"
            artifact_root.mkdir(mode=0o700)
            artifacts = artifact_type(artifact_root, _INSTALLATION)
            package = {"contract": "ticket117-migration-package-v1", "digest": "sha256:" + "a" * 64}
            self.assertEqual(artifacts.put("package:t123", package)["status"], "confirmed")
            self.assertEqual(
                artifact_type(artifact_root, _INSTALLATION).get("package:t123"),
                package,
            )
            self.assertEqual(artifacts.remove("package:t123")["status"], "confirmed")
            self.assertIsNone(artifacts.get("package:t123"))
            with self.assertRaises(Exception):
                artifacts.put("../escape", package)

    def test_v123_06_python_closure_and_systemd_process_are_fixed(self) -> None:
        module = self._require()
        runtime_root, manifest = self._runtime()
        self.assertEqual(sys.version_info[:2], (3, 11))
        files = manifest.get("files")
        self.assertIsInstance(files, list)
        declared = {
            item["path"]: item["sha256"]
            for item in files
            if type(item) is dict and set(item) == {"path", "sha256"}
        }
        self.assertTrue(declared)
        for relative, digest in declared.items():
            path = runtime_root / relative
            self.assertTrue(path.is_file() and not path.is_symlink())
            self.assertEqual("sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertTrue(any("partner_health_steward" in path for path in declared))
        self.assertTrue(any("cryptography" in path for path in declared))

        render = getattr(module, "render_health_core_systemd_unit", None)
        self.assertTrue(callable(render))
        unit = render(
            {
                "runtime_root": str(runtime_root),
                "binding_path": "/etc/partner-health-steward/health-core.json",
                "state_root": "/var/lib/partner-health-steward",
                "socket_root": "/run/partner-health-steward",
                "service_user": "partner-health-core",
                "plugin_group": "partner-health-plugin",
            }
        )
        self.assertIsInstance(unit, str)
        for required in (
            "User=partner-health-core",
            "Group=partner-health-plugin",
            "UMask=0077",
            "NoNewPrivileges=yes",
            "PrivateTmp=yes",
            "ProtectSystem=strict",
            str(runtime_root / "bin" / "python3"),
        ):
            self.assertIn(required, unit)
        self.assertNotIn("pip install", unit)
        self.assertNotIn("Environment=PYTHONPATH", unit)

        if subprocess.run(["systemctl", "is-system-running"], capture_output=True).returncode not in {0, 1}:
            self.fail("V123-06 requires a systemd transient-unit environment")
        unit_name = "ticket123-" + uuid.uuid4().hex
        probe = subprocess.run(
            [
                "systemd-run", "--quiet", "--wait", "--collect", "--pipe",
                f"--unit={unit_name}", "--property=NoNewPrivileges=yes",
                "--property=PrivateTmp=yes", "--property=UMask=0077",
                str(runtime_root / "bin" / "python3"), "-I", "-c",
                "import partner_health_steward; print('TICKET123-RUNTIME-OK')",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertIn("TICKET123-RUNTIME-OK", probe.stdout)

    def test_v123_07_no_plaintext_or_ordinary_state_copy_is_created(self) -> None:
        module = self._require()
        marker = "TICKET123-SYNTHETIC-HEALTH-MARKER"
        with tempfile.TemporaryDirectory(prefix="ticket123-") as raw:
            root = Path(raw)
            outside = root / "ordinary-session-sentinel"
            outside.write_text("ordinary-untouched", encoding="utf-8")
            module, binding, current_head, _client = self._fixture(root)
            service, endpoint = self._start(module, binding, current_head)
            try:
                request = self._probe_command()
                request["payload"]["unexpected_health_body"] = marker
                self.assertIsNone(self._request(endpoint, request))
            finally:
                service.close()
            self.assertEqual(outside.read_text(encoding="utf-8"), "ordinary-untouched")
            forbidden_roots = (
                Path(binding["release_root"]),
                Path(binding["runtime_root"]),
                Path(binding["migration_artifact_root"]),
            )
            for scan_root in forbidden_roots:
                for path in scan_root.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        self.assertNotIn(marker.encode(), path.read_bytes())
            database = Path(binding["database_path"])
            self.assertNotIn(marker.encode(), database.read_bytes())
            self.assertFalse(Path(binding["socket_path"]).exists())


if __name__ == "__main__":
    unittest.main()

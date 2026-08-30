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
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from partner_health_steward.admission import SourceEnvelope
from partner_health_steward.authority import (
    AuthoritySnapshot,
    EffectIntent,
    PreparedTransition,
    RevisionTarget,
    WriterHolderClaim,
)
from partner_health_steward.contract import CommandEnvelope, Response
from partner_health_steward.current_head import AdvanceRequest
from partner_health_steward.lifecycle import LIFECYCLE_PURGE_BINDINGS
from partner_health_steward.release_deployment import HermesReleasePublisher
from partner_health_steward.storage import CurrentHeadRecoveryBinding, EncryptedStateStore


_INSTALLATION = "installation:t123-fixture"
_SITE = "site:t123-fixture"
_DATA_KEY = hashlib.sha256(b"ticket123-verifier-data-key-v1").digest()
_WRITER_MASTER = hashlib.sha256(b"ticket123-verifier-writer-master-v1").digest()
_EXECUTION_MASTER = hashlib.sha256(
    b"ticket123-verifier-execution-master-v1"
).digest()
_REPLAY_CAUSAL_ID = "ticket123-managed-replay"
_REPLAY_REASON = "ticket123-encrypted-receipt"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _runtime_closure_digest(files: object) -> str:
    if type(files) is not list:
        raise AssertionError("runtime closure file table is invalid")
    return "sha256:" + hashlib.sha256(_canonical(files)).hexdigest()


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


def _process_tcp_listener_inodes() -> set[str]:
    listening: set[str] = set()
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        if not table.is_file():
            continue
        for line in table.read_text(encoding="ascii").splitlines()[1:]:
            fields = line.split()
            if len(fields) > 9 and fields[3] == "0A":
                listening.add(fields[9])
    owned: set[str] = set()
    for descriptor in Path("/proc/self/fd").iterdir():
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inode = target[8:-1]
            if inode in listening:
                owned.add(inode)
    return owned


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
        facility.mkdir(parents=True, mode=0o700, exist_ok=True)
        for name, value in (
            ("data-key.v1", _DATA_KEY),
            ("writer-master.v1", _WRITER_MASTER),
            ("execution-master.v1", _EXECUTION_MASTER),
        ):
            path = facility / name
            path.write_bytes(value)
            path.chmod(0o400)
        locks = facility / "locks"
        locks.mkdir(mode=0o700, exist_ok=True)
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

    @staticmethod
    def _as_current_release(binding: dict[str, object]) -> None:
        """Promote one verified fixture release without changing its assets."""

        release_root = Path(binding["release_root"])
        manifest_path = release_root / "release-manifest.json"
        host_path = release_root / "host-release-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        host = json.loads(host_path.read_text(encoding="utf-8"))
        manifest["state"] = "current"
        body = {
            "contract": manifest["contract"],
            "state": manifest["state"],
            "files": manifest["files"],
            "host_release_manifest": host,
        }
        digest = "sha256:" + hashlib.sha256(_canonical(body)).hexdigest()
        manifest["release_digest"] = digest
        destination = release_root.parent / digest.removeprefix("sha256:")
        if destination.exists():
            raise AssertionError("current release fixture already exists")
        manifest_path.write_bytes(_canonical(manifest))
        release_root.rename(destination)
        binding["release_root"] = str(destination)
        binding["release_digest"] = digest
        lifecycle_release = binding["lifecycle_release"]
        if type(lifecycle_release) is not dict:
            raise AssertionError("fixture lifecycle release is invalid")
        lifecycle_release["product_release"] = digest

    @staticmethod
    def _recovery_command() -> CommandEnvelope:
        return CommandEnvelope(
            peer="plugin",
            action="state.commit",
            source="health_weixin",
            causal_id="ticket123-recover-commit",
            generation=1,
            scope=("state:commit",),
            payload={
                "record_id": "record:t123-recovery",
                "revision_digest": "sha256:t123-recovered",
                "transition_id": "transition:t123-recovered",
                "writer_fence": "placeholder-replaced-by-fixture",
            },
        )

    def _fixture(
        self,
        root: Path,
        *,
        seed_effect: bool = False,
        seed_recovery: bool = False,
        client_factory: object | None = None,
    ):
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
        client = t122._ScriptedDynamo() if client_factory is None else client_factory()
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
        database.parent.mkdir(mode=0o700, exist_ok=True)
        key_provider = host.HostPrivateKeyProvider(facility, _INSTALLATION)
        store = EncryptedStateStore(str(database), key_provider)
        store.seed_finalized_authority(authority)
        replay_command = CommandEnvelope(
            peer="plugin",
            action="probe",
            source="health_weixin",
            causal_id=_REPLAY_CAUSAL_ID,
            generation=1,
            scope=("probe",),
            payload={},
        )
        store.save_receipt(
            replay_command,
            Response("replayed", _REPLAY_CAUSAL_ID, _REPLAY_REASON),
        )
        if seed_effect:
            store.write_effect(
                "effect:t123-host-vault",
                "intent",
                EffectIntent(
                    effect_id="effect:t123-host-vault",
                    effect_kind="model-work",
                    intent_digest="sha256:t123-host-vault-intent",
                    authority=authority,
                ),
            )
        if seed_recovery:
            target = RevisionTarget(
                "record:t123-recovery",
                "sha256:t123-recovered",
                "transition:t123-recovered",
                "sha256:t123-recovery-payload",
            )
            prepared = PreparedTransition(target, authority)
            recovery = self._recovery_command().to_wire()
            recovery["payload"]["writer_fence"] = authority.writer_fence
            recovery_command = CommandEnvelope.from_wire(recovery)
            store.write_record(
                target.record_id,
                "prepared",
                target.revision_digest,
                target.transition_id,
                prepared,
            )
            store.write_pending_command(
                recovery_command,
                target.record_id,
                remote_attempted=True,
            )
            holder = writer.acquire_or_resume(
                _INSTALLATION,
                _SITE,
                WriterHolderClaim("holder:t123-recovery-setup"),
            )
            if holder is None:
                raise AssertionError("cannot create Ticket 123 recovery fixture")
            try:
                proof = holder.proof_for(authority)
                if proof is None:
                    raise AssertionError("cannot prove Ticket 123 recovery fixture")
                current_head.conditional_advance(
                    AdvanceRequest(
                        expected=authority,
                        transition_id=target.transition_id,
                        revision_digest=target.revision_digest,
                        writer_fence=authority.writer_fence,
                        operation_digest=CurrentHeadRecoveryBinding.from_command(
                            recovery_command
                        ).command_digest,
                        writer_proof=proof,
                    )
                )
            finally:
                holder.release()
        store.close()
        replica_root = root / "managed"
        replica_root.mkdir(mode=0o700, exist_ok=True)
        replica_bindings: dict[str, str] = {}
        for index, binding in enumerate(LIFECYCLE_PURGE_BINDINGS):
            target = replica_root / f"object-{index:02d}.managed"
            target.write_bytes(_canonical({"binding": binding}))
            target.chmod(0o600)
            replica_bindings[binding] = str(target)
        migration_root = root / "migration"
        migration_root.mkdir(mode=0o700, exist_ok=True)
        socket_root = root / "run"
        socket_root.mkdir(mode=0o700, exist_ok=True)
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
        if endpoint.get("protocol") != "ticket118-core-port-v1":
            raise AssertionError("ProductionCoreService returned an incompatible endpoint")
        return service, endpoint

    @staticmethod
    def _request(
        endpoint: dict[str, object], value: dict[str, object], *, timeout: float = 2
    ) -> dict[str, object] | None:
        if endpoint.get("transport") != "af-unix" or type(endpoint.get("path")) is not str:
            raise AssertionError("production endpoint is not AF_UNIX")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(endpoint["path"])
            connection.sendall(_outer_frame(value))
            connection.shutdown(socket.SHUT_WR)
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
                    "causal_id": _REPLAY_CAUSAL_ID,
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
            module, binding, current_head, client = self._fixture(root)
            service, endpoint = self._start(module, binding, current_head)
            host = importlib.import_module("partner_health_steward.host_authority")
            competing_writer = host.HostPrivateWriterFenceVault(
                binding["host_private_paths"]
            )
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
                self.assertTrue(projection.get("managed_lifecycle_ready"))
                self.assertEqual(projection.get("current_head_provider"), "dynamodb")
                self.assertTrue(any(name == "GetItem" for name, _ in client.calls))
                self.assertIsNone(
                    competing_writer.acquire_or_resume(
                        _INSTALLATION,
                        _SITE,
                        WriterHolderClaim("holder:t123-competing-service"),
                    )
                )
            finally:
                service.close()
            released_holder = competing_writer.acquire_or_resume(
                _INSTALLATION,
                _SITE,
                WriterHolderClaim("holder:t123-after-close"),
            )
            self.assertIsNotNone(released_holder)
            released_holder.release()

            current_binding = copy.deepcopy(binding)
            self._as_current_release(current_binding)
            current_service, current_endpoint = self._start(
                module, current_binding, current_head
            )
            try:
                current_projection = self._request(
                    current_endpoint, self._runtime_read()
                )["payload"]
                self.assertEqual(current_projection.get("state"), "healthy")
                self.assertTrue(current_projection.get("health_writes_allowed"))
                self.assertTrue(current_projection.get("model_effects_allowed"))
                self.assertTrue(current_projection.get("outbound_effects_allowed"))
            finally:
                current_service.close()

            for name, mutate, provider in (
                ("release-digest", lambda value: value.__setitem__("release_digest", "sha256:" + "0" * 64), current_head),
                ("runtime-digest", lambda value: value["runtime_manifest"].__setitem__("closure_digest", "sha256:" + "0" * 64), current_head),
                ("wide-socket", lambda value: value.__setitem__("socket_mode", 0o666), current_head),
                ("wrong-installation", lambda value: value.__setitem__("installation_id", "installation:other"), current_head),
                ("wrong-site", lambda value: value.__setitem__("site", "site:other"), current_head),
                ("missing-facility", lambda value: value.__setitem__("host_private_paths", object()), current_head),
                ("missing-lifecycle-root", lambda value: value.__setitem__("managed_replica_root", str(root / "absent-managed")), current_head),
                ("in-memory-provider", lambda value: None, object()),
            ):
                with self.subTest(name=name):
                    candidate = copy.deepcopy(binding)
                    candidate["socket_path"] = str(root / f"{name}.sock")
                    mutate(candidate)
                    with self.assertRaises(Exception):
                        self._start(module, candidate, provider)
                    self.assertFalse(Path(candidate["socket_path"]).exists())

            effect_root = root / "execution-vault"
            _module, effect_binding, effect_head, _effect_client = self._fixture(
                effect_root, seed_effect=True
            )
            effect_service, effect_endpoint = self._start(
                module, effect_binding, effect_head
            )
            try:
                claim = self._request(
                    effect_endpoint,
                    {
                        "protocol_version": 1,
                        "kind": "controlled-effect",
                        "request_id": "ticket123-host-execution-claim",
                        "payload": {"phase": "claim"},
                    },
                )
                self.assertEqual(
                    claim["payload"].get("intent", {}).get("effect_id"),
                    "effect:t123-host-vault",
                )
                self.assertIsInstance(claim["payload"].get("grant"), dict)
            finally:
                effect_service.close()

            lost_root = root / "execution-key-loss"
            _module, lost_binding, lost_head, _lost_client = self._fixture(
                lost_root, seed_effect=True
            )
            lost_service, lost_endpoint = self._start(module, lost_binding, lost_head)
            try:
                Path(lost_binding["host_private_paths"].execution_master).unlink()
                denied = self._request(
                    lost_endpoint,
                    {
                        "protocol_version": 1,
                        "kind": "controlled-effect",
                        "request_id": "ticket123-lost-execution-key",
                        "payload": {"phase": "claim"},
                    },
                )
                self.assertIsNone(denied["payload"].get("grant"))
            finally:
                lost_service.close()

    def test_v123_02_af_unix_acl_and_peer_credentials_are_both_enforced(self) -> None:
        module = self._require()
        if os.geteuid() != 0:
            self.fail("V123-02 requires an isolated root-runner for wrong-UID SO_PEERCRED")
        import pwd

        with tempfile.TemporaryDirectory(prefix="ticket123-") as raw:
            root = Path(raw)
            tcp_before = _process_tcp_listener_inodes()
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
                self.assertEqual(_process_tcp_listener_inodes(), tcp_before)

                nobody = pwd.getpwnam("nobody")
                wrong_uid = nobody.pw_uid
                wrong_gid = nobody.pw_gid
                # Permit pathname traversal and a kernel-level connect so the
                # only remaining rejection oracle is the listener's SO_PEERCRED.
                root.chmod(0o711)
                socket_path.parent.chmod(0o711)
                socket_path.chmod(0o666)  # File ACL alone must not defeat SO_PEERCRED.
                script = """
import json, os, socket, struct, sys
os.setgid(int(sys.argv[2])); os.setuid(int(sys.argv[1]))
request={'protocol_version':1,'kind':'managed-read','request_id':'wrong-peer','payload':{'projection':'health-runtime'}}
body=json.dumps(request,separators=(',',':'),sort_keys=True).encode()
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.settimeout(1); s.connect(sys.argv[3])
try:
    s.sendall(struct.pack('>I',len(body))+body)
    try: data=s.recv(1)
    except ConnectionResetError: data=b''
except (BrokenPipeError, ConnectionResetError): data=b''
except socket.timeout: raise SystemExit(8)
raise SystemExit(0 if data==b'' else 9)
"""
                wrong = subprocess.run(
                    [sys.executable, "-I", "-B", "-c", script, str(wrong_uid), str(wrong_gid), str(socket_path)],
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

            active_path = root / "active-old.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as old_listener:
                old_listener.bind(str(active_path))
                old_listener.listen()
                old_inode = active_path.lstat().st_ino
                active_binding = copy.deepcopy(binding)
                active_binding["socket_path"] = str(active_path)
                with self.assertRaises(Exception):
                    self._start(module, active_binding, current_head)
                self.assertEqual(active_path.lstat().st_ino, old_inode)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(str(active_path))
            active_path.unlink()

    def test_v123_03_all_three_coreport_kinds_use_one_strict_byte_stream(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket123-") as raw:
            module, binding, current_head, client = self._fixture(Path(raw))
            service, endpoint = self._start(module, binding, current_head)
            try:
                host_command_request = {
                    "protocol_version": 1,
                    "kind": "command",
                    "request_id": "ticket118-command",
                    "payload": {"operation": "health-runtime-probe"},
                }
                command = self._request(endpoint, host_command_request)
                managed = self._request(endpoint, self._runtime_read())
                controlled = self._request(
                    endpoint,
                    {
                        "protocol_version": 1,
                        "kind": "controlled-effect",
                        "request_id": "ticket123-forged-claim",
                        "payload": {"phase": "claim"},
                    },
                )
                for request, response in (
                    (host_command_request, command),
                    (self._runtime_read(), managed),
                    ({"kind": "controlled-effect", "request_id": "ticket123-forged-claim"}, controlled),
                ):
                    self.assertEqual(
                        set(response),
                        {"protocol_version", "kind", "request_id", "status", "payload"},
                    )
                    self.assertEqual(response["protocol_version"], 1)
                    self.assertEqual(response["kind"], request["kind"])
                    self.assertEqual(response["request_id"], request["request_id"])
                    self.assertEqual(response["status"], "accepted")
                self.assertIsNone(controlled["payload"].get("grant"))
                self.assertIsNone(controlled["payload"].get("intent"))
                self.assertEqual(
                    controlled["payload"].get("current_authority", {}).get("generation"),
                    1,
                )
                forged = self._request(
                    endpoint,
                    {
                        "protocol_version": 1,
                        "kind": "controlled-effect",
                        "request_id": "ticket123-forged-intent",
                        "payload": {"phase": "claim", "intent": {"source": "caller"}},
                    },
                )
                self.assertIsNone(forged)
                incomplete_terminal = self._request(
                    endpoint,
                    {
                        "protocol_version": 1,
                        "kind": "controlled-effect",
                        "request_id": "ticket118-controlled-effect-terminal",
                        "payload": {"phase": "terminal", "terminal": {}},
                    },
                )
                self.assertEqual(incomplete_terminal["status"], "accepted")
                self.assertFalse(
                    incomplete_terminal["payload"].get("terminal_accepted")
                )

                # This exact response was encrypted before service startup.  A
                # byte-stream shell cannot produce it without dispatching the
                # typed CommandEnvelope through the real HealthCore/store.
                replay = self._request(endpoint, self._probe_command())
                self.assertEqual(
                    replay["payload"].get("response"),
                    Response("replayed", _REPLAY_CAUSAL_ID, _REPLAY_REASON).to_wire(),
                )

                # A complete request is delimited by the client half-close,
                # not by a speculative server-side timing window.  The
                # request is otherwise legal; a later tail must still stop it
                # before the managed-read can dereference current-head.
                calls_before_tail = len(client.calls)
                delayed_tail = _outer_frame(self._runtime_read())
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(2)
                    connection.connect(endpoint["path"])
                    connection.sendall(delayed_tail)
                    time.sleep(0.08)
                    try:
                        connection.sendall(b"tail")
                        connection.shutdown(socket.SHUT_WR)
                    except BrokenPipeError:
                        # The legacy 30ms window may already have dispatched
                        # and closed.  Its response remains the evidence that
                        # the later tail was not checked before dispatch.
                        pass
                    try:
                        observed = connection.recv(1)
                    except (ConnectionResetError, socket.timeout):
                        observed = b""
                self.assertEqual(observed, b"")
                self.assertEqual(len(client.calls), calls_before_tail)

                # A sender that never half-closes has not delimited its one
                # request.  The server must time out without dispatching it.
                calls_before_open_request = len(client.calls)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(2)
                    connection.connect(endpoint["path"])
                    connection.sendall(_outer_frame(self._runtime_read()))
                    self.assertEqual(connection.recv(1), b"")
                self.assertEqual(len(client.calls), calls_before_open_request)

                malformed = (
                    b'{"kind":"managed-read","kind":"command","payload":{},'
                    b'"protocol_version":1,"request_id":"duplicate"}'
                )
                cases = (
                    struct.pack(">I", len(malformed)) + malformed,
                    _outer_frame({"protocol_version": 1, "kind": "unknown", "request_id": "x", "payload": {}}),
                    _outer_frame({"protocol_version": 1, "kind": "managed-read", "request_id": "x", "payload": {}, "extra": True}),
                    struct.pack(">I", 9) + b"{}",
                    struct.pack(">I", 0),
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
            root = Path(raw)
            module, binding, current_head, client = self._fixture(root)
            service, endpoint = self._start(module, binding, current_head)
            first = self._request(endpoint, self._probe_command())
            service.close()
            service, endpoint = self._start(module, binding, current_head)
            try:
                replay = self._request(endpoint, self._probe_command())
                self.assertEqual(replay, first)
                self.assertEqual(
                    replay["payload"].get("response"),
                    Response("replayed", _REPLAY_CAUSAL_ID, _REPLAY_REASON).to_wire(),
                )
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

            for name, mutate in (
                (
                    "stale-fence",
                    lambda candidate, provider: provider.records["HEAD"].__setitem__(
                        "writer_fence", {"S": "fence:stale-ticket123"}
                    ),
                ),
                (
                    "key-loss",
                    lambda candidate, _provider: Path(
                        candidate["host_private_paths"].data_key
                    ).unlink(),
                ),
            ):
                with self.subTest(name=name):
                    fault_root = root / name
                    _module, candidate, provider_head, provider = self._fixture(fault_root)
                    candidate_service, candidate_endpoint = self._start(
                        module, candidate, provider_head
                    )
                    try:
                        mutate(candidate, provider)
                        request = self._probe_command()
                        request["request_id"] = f"ticket123-{name}"
                        request["payload"]["command"]["causal_id"] = f"ticket123-{name}"
                        response = self._request(candidate_endpoint, request)
                        self.assertIsNotNone(response)
                        self.assertIn(
                            response["payload"].get("response", {}).get("status"),
                            {"unavailable", "unknown", "rejected"},
                        )
                        self.assertFalse(
                            any(call == "TransactWriteItems" for call, _ in provider.calls)
                        )
                    finally:
                        candidate_service.close()

            recovery_root = root / "prepared-finalize-recovery"
            _module, recovery_binding, recovery_head, recovery_client = self._fixture(
                recovery_root, seed_recovery=True
            )
            recovery_wire = self._recovery_command().to_wire()
            recovery_wire["payload"]["writer_fence"] = recovery_head.read().head.writer_fence
            core_request = {
                "protocol_version": 1,
                "kind": "command",
                "request_id": "ticket123-prepared-finalize",
                "payload": {"interface": "command-v1", "command": recovery_wire},
            }
            recovery_service, recovery_endpoint = self._start(
                module, recovery_binding, recovery_head
            )
            recovery_client.calls.clear()
            try:
                finalized = self._request(recovery_endpoint, core_request)
                self.assertIn(
                    finalized["payload"].get("response", {}).get("status"),
                    {"accepted", "replayed"},
                )
                self.assertFalse(
                    any(name == "TransactWriteItems" for name, _ in recovery_client.calls)
                )
            finally:
                recovery_service.close()
            recovery_service, recovery_endpoint = self._start(
                module, recovery_binding, recovery_head
            )
            try:
                exact_replay = self._request(recovery_endpoint, core_request)
                self.assertEqual(exact_replay, finalized)
            finally:
                recovery_service.close()
            recovery_store = EncryptedStateStore(
                recovery_binding["database_path"],
                importlib.import_module(
                    "partner_health_steward.host_authority"
                ).HostPrivateKeyProvider(
                    recovery_binding["host_private_paths"],
                    recovery_binding["installation_id"],
                ),
            )
            try:
                self.assertEqual(
                    recovery_store.record_state("record:t123-recovery"), "final"
                )
                self.assertIsNotNone(
                    recovery_store.receipt(CommandEnvelope.from_wire(recovery_wire))
                )
            finally:
                recovery_store.close()

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
            authority = AuthoritySnapshot(
                _INSTALLATION,
                1,
                "sha256:t123-delete",
                "transition:t123-delete-authority",
                "fence:t123-delete",
                False,
                _SITE,
            ).to_storage()
            lifecycle_request = {
                "operation_ref": "delete:t123",
                "authority_binding": authority,
                "transition_id": authority["transition_id"],
            }
            purge = managed.purge(lifecycle_request)
            self.assertEqual(purge["status"], "confirmed")
            restarted = managed_type(managed_root, _INSTALLATION, bindings, ())
            self.assertEqual(restarted.absence(lifecycle_request)["status"], "absent")

            artifact_root = root / "artifacts"
            artifact_root.mkdir(mode=0o700)
            artifacts = artifact_type(artifact_root, _INSTALLATION)
            binding_registry = [
                {
                    "family": name,
                    "snapshot_codec": f"codec:{name}:v1",
                    "purge_binding": purge_binding,
                    "source_continuity": "preserve",
                }
                for index, purge_binding in enumerate(LIFECYCLE_PURGE_BINDINGS)
                for name in (f"managed-family-{index}",)
            ]
            package = {
                "contract": "ticket117-opaque-migration-package-v1",
                "manifest": {
                    "contract": "ticket117-semantic-manifest-v1",
                    "operation_ref": "migration:t123",
                    "source_authority": authority,
                    "semantic_registry": binding_registry,
                    "release": {"product_release": "sha256:" + "a" * 64},
                    "target_site": "site:t123-target",
                    "target_writer_fence_ref": "target-fence:t123",
                    "artifact_sink_ref": "artifact-sink:t123",
                    "semantic_state_digest": "sha256:" + "b" * 64,
                },
                "semantic_state": {"registry": binding_registry, "records": []},
            }
            observed: list[object] = []
            reader_errors: list[BaseException] = []
            reader_ready = threading.Event()
            observed_complete = threading.Event()
            completed = threading.Event()

            def read_until_written() -> None:
                try:
                    while not completed.is_set():
                        value = artifacts.get("lifecycle-package:migration:t123")
                        observed.append(value)
                        reader_ready.set()
                        if value == package:
                            observed_complete.set()
                except BaseException as exc:
                    reader_errors.append(exc)
                    completed.set()

            reader = threading.Thread(target=read_until_written)
            reader.start()
            try:
                self.assertTrue(reader_ready.wait(timeout=2))
                self.assertEqual(
                    artifacts.put("lifecycle-package:migration:t123", package)["status"],
                    "confirmed",
                )
                self.assertTrue(observed_complete.wait(timeout=2))
            finally:
                completed.set()
                reader.join(timeout=2)
            self.assertFalse(reader.is_alive())
            self.assertFalse(reader_errors)
            self.assertTrue(observed)
            self.assertIn(None, observed)
            self.assertIn(package, observed)
            self.assertTrue(all(item is None or item == package for item in observed))
            self.assertEqual(
                artifact_type(artifact_root, _INSTALLATION).get(
                    "lifecycle-package:migration:t123"
                ),
                package,
            )
            with self.assertRaises(Exception):
                artifacts.put(
                    "lifecycle-package:migration:t123",
                    {**package, "semantic_state": {"records": ["conflict"]}},
                )
            stored_files = [path for path in artifact_root.rglob("*") if path.is_file()]
            self.assertTrue(stored_files)
            hardlink = root / "artifact-hardlink"
            os.link(stored_files[0], hardlink)
            with self.assertRaises(Exception):
                artifacts.get("lifecycle-package:migration:t123")
            hardlink.unlink()
            self.assertEqual(
                artifacts.remove("lifecycle-package:migration:t123")["status"],
                "confirmed",
            )
            self.assertIsNone(artifacts.get("lifecycle-package:migration:t123"))
            with self.assertRaises(Exception):
                artifacts.put("../escape", package)

            real_root = root / "real-artifacts"
            real_root.mkdir(mode=0o700)
            linked_root = root / "linked-artifacts"
            linked_root.symlink_to(real_root, target_is_directory=True)
            with self.assertRaises(Exception):
                artifact_type(linked_root, _INSTALLATION)
            real_root.chmod(0o777)
            with self.assertRaises(Exception):
                artifact_type(real_root, _INSTALLATION)

    def test_v123_06_python_closure_and_systemd_process_are_fixed(self) -> None:
        module = self._require()
        runtime_root, manifest = self._runtime()
        self.assertEqual(sys.version_info[:2], (3, 11))
        files = manifest.get("files")
        self.assertIsInstance(files, list)
        self.assertEqual(manifest.get("closure_digest"), _runtime_closure_digest(files))
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
        expected_exec = (
            "ExecStart="
            + str(runtime_root / "bin" / "python3")
            + " -I -m partner_health_steward.production_core_service"
            + " --binding /etc/partner-health-steward/health-core.json"
        )
        self.assertIn(expected_exec, unit)
        self.assertNotIn("pip install", unit)
        self.assertNotIn("Environment=PYTHONPATH", unit)

        cli = subprocess.run(
            [
                str(runtime_root / "bin" / "python3"),
                "-I",
                "-B",
                "-m",
                "partner_health_steward.production_core_service",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertIn("--binding", cli.stdout)

        undeclared = runtime_root / ("ticket123-undeclared-" + uuid.uuid4().hex)
        undeclared.write_text("must invalidate the closure", encoding="utf-8")
        try:
            with tempfile.TemporaryDirectory(prefix="ticket123-extra-file-") as raw:
                module, binding, current_head, _client = self._fixture(Path(raw))
                with self.assertRaises(Exception):
                    self._start(module, binding, current_head)
                self.assertFalse(Path(binding["socket_path"]).exists())
        finally:
            undeclared.unlink()

        t122 = importlib.import_module("tests.test_ticket122_dynamodb_current_head")

        class BlockingDynamo(t122._ScriptedDynamo):
            def __init__(self) -> None:
                super().__init__()
                self.block_reads = threading.Event()
                self.read_entered = threading.Event()
                self.release_reads = threading.Event()

            def get_item(self, **kwargs):
                if self.block_reads.is_set():
                    self.read_entered.set()
                    if not self.release_reads.wait(timeout=5):
                        raise RuntimeError("blocked current-head probe timed out")
                return super().get_item(**kwargs)

        with tempfile.TemporaryDirectory(prefix="ticket123-close-drain-") as raw:
            root = Path(raw)
            module, binding, current_head, client = self._fixture(
                root, client_factory=BlockingDynamo
            )
            service, endpoint = self._start(module, binding, current_head)
            socket_path = Path(endpoint["path"])
            exchange_errors: list[BaseException] = []

            def exchange() -> None:
                try:
                    self._request(endpoint, self._runtime_read(), timeout=5)
                except BaseException as exc:
                    exchange_errors.append(exc)

            client.block_reads.set()
            worker = threading.Thread(target=exchange, name="ticket123-blocked-exchange")
            worker.start()
            self.assertTrue(client.read_entered.wait(timeout=2))
            try:
                with self.assertRaises(RuntimeError):
                    service.close()
                self.assertTrue(socket_path.exists())
                with self.assertRaises(RuntimeError):
                    service.start()
            finally:
                client.release_reads.set()
                worker.join(timeout=3)
                service.close()
            self.assertFalse(worker.is_alive())
            self.assertFalse(exchange_errors)
            self.assertFalse(socket_path.exists())

        # The runtime closure manifest and the start binding must not be able
        # to agree on a reordered, self-rehashed table.  Run the probe with a
        # copied closure so the persistent verifier runtime stays untouched.
        with tempfile.TemporaryDirectory(prefix="ticket123-runtime-tamper-") as raw:
            tamper_root = Path(raw)
            cloned_runtime = tamper_root / "runtime"
            shutil.copytree(runtime_root, cloned_runtime)
            environment = dict(os.environ)
            environment["TICKET123_RUNTIME_ROOT"] = str(cloned_runtime)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            tampered = subprocess.run(
                [
                    str(cloned_runtime / "bin" / "python3"),
                    "-I",
                    "-B",
                    str(Path(__file__).resolve()),
                    "--runtime-tamper",
                    str(tamper_root / "process"),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            )
            self.assertNotEqual(
                tampered.returncode,
                0,
                tampered.stdout + tampered.stderr,
            )

        if subprocess.run(["systemctl", "is-system-running"], capture_output=True).returncode not in {0, 1}:
            self.fail("V123-06 requires a systemd transient-unit environment")
        def run_unit(root: Path, mode: str) -> subprocess.CompletedProcess[str]:
            unit_name = "ticket123-" + uuid.uuid4().hex
            return subprocess.run(
                [
                    "systemd-run",
                    "--quiet",
                    "--wait",
                    "--collect",
                    "--pipe",
                    f"--unit={unit_name}",
                    "--property=NoNewPrivileges=yes",
                    "--property=PrivateTmp=yes",
                    "--property=UMask=0077",
                    f"--setenv=TICKET123_RUNTIME_ROOT={runtime_root}",
                    str(runtime_root / "bin" / "python3"),
                    "-I",
                    "-B",
                    str(Path(__file__).resolve()),
                    "--systemd-child",
                    str(root),
                    mode,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        verification_root = Path(__file__).resolve().parents[1]
        root_name = verification_root.name
        self.assertEqual(verification_root.parent, Path("/opt"))
        self.assertTrue(
            root_name.startswith("t123v-")
            and len(root_name) == len("t123v-") + 8
            and all(character in "0123456789abcdef" for character in root_name[6:])
        )
        process_parent = verification_root / "p"
        process_parent.mkdir(mode=0o700)
        process_parent.chmod(0o700)
        try:
            with tempfile.TemporaryDirectory(prefix="r-", dir=process_parent) as raw:
                process_root = Path(raw)
                normal_root = process_root / "n"
                crash_root = process_root / "c"
                for socket_path in (
                    normal_root / "run" / "health-core.sock",
                    crash_root / "run" / "health-core.sock",
                ):
                    self.assertLessEqual(
                        len(os.fsencode(socket_path)),
                        90,
                        f"V123-06 AF_UNIX path is too long: {socket_path}",
                    )
                normal = run_unit(normal_root, "normal")
                self.assertEqual(normal.returncode, 0, normal.stderr)
                self.assertIn("TICKET123-SERVICE-OK", normal.stdout)
                self.assertFalse((normal_root / "run" / "health-core.sock").exists())

                crashed = run_unit(crash_root, "crash")
                self.assertNotEqual(crashed.returncode, 0)
                stale_socket = crash_root / "run" / "health-core.sock"
                self.assertTrue(stale_socket.exists())
                with self.assertRaises(OSError):
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                        connection.connect(str(stale_socket))
                recovered = run_unit(crash_root, "normal")
                self.assertEqual(recovered.returncode, 0, recovered.stderr)
                self.assertIn("TICKET123-SERVICE-OK", recovered.stdout)
                self.assertFalse(stale_socket.exists())
        finally:
            process_parent.rmdir()

    def test_v123_07_no_plaintext_or_ordinary_state_copy_is_created(self) -> None:
        module = self._require()
        marker = "TICKET123-SYNTHETIC-HEALTH-MARKER"
        with tempfile.TemporaryDirectory(prefix="ticket123-") as raw:
            root = Path(raw)
            outside = root / "ordinary-session-sentinel"
            outside.write_text("ordinary-untouched", encoding="utf-8")
            module, binding, current_head, _client = self._fixture(root)
            host = importlib.import_module("partner_health_steward.host_authority")
            store = EncryptedStateStore(
                binding["database_path"],
                host.HostPrivateKeyProvider(
                    binding["host_private_paths"], binding["installation_id"]
                ),
            )
            envelope = SourceEnvelope(
                causal_id="source:t123-health-marker",
                generation=1,
                channel="weixin",
                partner_id="partner:t123",
                sender_id="owner:t123",
                conversation_id="conversation:t123",
                chat_type="private",
                entrypoint="health_weixin",
                requested_capability="health-init",
                message_id="message:t123-marker",
                protocol_timestamp="2026-08-30T08:00:00+00:00",
                received_at="2026-08-30T08:00:01+00:00",
                native_cursor="cursor:t123-marker",
                body=marker,
            )
            store.save_source_envelope(envelope, retain_body=True)
            store.close()
            service, endpoint = self._start(module, binding, current_head)
            try:
                response = self._request(endpoint, self._runtime_read())
                self.assertEqual(response["status"], "accepted")
            finally:
                service.close()
            readback = EncryptedStateStore(
                binding["database_path"],
                host.HostPrivateKeyProvider(
                    binding["host_private_paths"], binding["installation_id"]
                ),
            )
            try:
                receipt = readback.source_receipt(envelope.causal_id)
                self.assertIsNotNone(receipt)
                self.assertEqual(receipt.envelope.body, marker)
            finally:
                readback.close()
            self.assertEqual(outside.read_text(encoding="utf-8"), "ordinary-untouched")
            forbidden_roots = (
                Path(binding["release_root"]),
                Path(binding["runtime_root"]),
                Path(binding["migration_artifact_root"]),
                Path(binding["managed_replica_root"]),
                Path(binding["socket_path"]).parent,
            )
            forbidden_needles = (
                marker.encode(),
                _DATA_KEY,
                _WRITER_MASTER,
                _EXECUTION_MASTER,
            )
            for scan_root in forbidden_roots:
                for path in scan_root.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        payload = path.read_bytes()
                        for needle in forbidden_needles:
                            self.assertNotIn(needle, payload)
            database = Path(binding["database_path"])
            self.assertNotIn(marker.encode(), database.read_bytes())
            self.assertFalse(Path(binding["socket_path"]).exists())


def _run_runtime_tamper(root: Path) -> None:
    """Prove a self-rehashed runtime table cannot authorize service start."""

    Ticket123ProductionCoreServiceTests.setUpClass()
    case = Ticket123ProductionCoreServiceTests(
        "test_v123_06_python_closure_and_systemd_process_are_fixed"
    )
    module, binding, current_head, _client = case._fixture(root)
    runtime_root = Path(binding["runtime_root"])
    manifest_path = runtime_root / "ticket123-runtime-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest["files"]
    if type(files) is not list:
        raise AssertionError("runtime closure fixture is invalid")
    manifest["files"] = list(reversed(files))
    manifest["closure_digest"] = _runtime_closure_digest(manifest["files"])
    manifest_path.write_bytes(_canonical(manifest))
    binding["runtime_manifest"] = copy.deepcopy(manifest)
    service, _endpoint = case._start(module, binding, current_head)
    service.close()
    print("TICKET123-RUNTIME-TAMPER-ACCEPTED", flush=True)


def _run_systemd_child(root: Path, mode: str) -> None:
    """Start the real Ticket 123 service inside the transient unit process."""

    if mode not in {"normal", "crash"}:
        raise ValueError("invalid systemd child mode")
    Ticket123ProductionCoreServiceTests.setUpClass()
    case = Ticket123ProductionCoreServiceTests(
        "test_v123_01_composition_is_release_bound_and_staged_is_truthfully_unavailable"
    )
    module, binding, current_head, _client = case._fixture(root)
    service, endpoint = case._start(module, binding, current_head)
    if mode == "crash":
        print("TICKET123-SERVICE-CRASH-READY", flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("SIGKILL unexpectedly returned")
    try:
        response = case._request(endpoint, case._runtime_read())
        if response is None or response.get("status") != "accepted":
            raise AssertionError("production service did not answer inside systemd")
    finally:
        service.close()
    print("TICKET123-SERVICE-OK", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--runtime-tamper":
        _run_runtime_tamper(Path(sys.argv[2]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--systemd-child":
        _run_systemd_child(Path(sys.argv[2]), sys.argv[3])
    else:
        unittest.main()

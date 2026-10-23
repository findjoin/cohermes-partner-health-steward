"""Independent Ticket128 default deployment verification candidates.

Seven families cross public product behavior. All synthetic boundaries remain
contract fixtures; none attests a real model/channel call or human acceptance.
The current missing-public-interface result is prerequisite-red only.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import asyncio
import errno
import re
import shutil
import socket
import ssl
import struct
import threading
import time
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import partner_health_steward as health
from tests import test_ticket119_integration as original119

_REPOSITORY = Path(__file__).resolve().parents[1]
_FULL = tuple(f"119-G{i:02d}" for i in range(1, 13))
_ND = (*_FULL[:6], "128-ND07", *_FULL[7:11], "128-ND12")
_ND_APPROVALS = ("119-G08", "119-G10", "119-G11", "128-ND12")
_SHA = "sha256:" + "a" * 64
_STAGES = ("formed", "committed", "attempted", "interface_accepted", "delivered", "read_or_action", "correction", "unknown")
_RAW_INPUTS = Path(__file__).with_name("fixtures") / "ticket128_default_deployment_inputs.json"


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _wire(value):
    result = value.to_wire()
    if type(result) is not dict:
        raise AssertionError("public wire is not a plain mapping")
    return result


def _digest(value):
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


class _DecisionExecutor:
    """Only the external 119 GateExecutor Seam is synthetic here."""
    def __init__(self, *, frontier=None, mutation=None):
        self.calls = []
        self.frontier = frontier
        self.mutation = mutation

    def execute(self, request):
        call = copy.deepcopy(request)
        self.calls.append(call)
        gate = call["gate_id"]
        result = "cannot-confirm" if gate == self.frontier else "passed"
        stages = {stage: None for stage in _STAGES}
        if gate in {"119-G11", "119-G12", "128-ND12"}:
            for stage in _STAGES[:6]:
                stages[stage] = f"fixture:{gate}:{stage}"
        observation = {
            "contract": "ticket119-gate-observation-v1",
            "release_digest": call["release_digest"], "run_id": call["run_id"],
            "gate_id": gate, "execution_key": call["execution_key"],
            "environment_class": call["environment_class"], "observed_at_utc": call["executed_at_utc"],
            "executor_digest": _SHA, "step_digest": _SHA, "fixture_digest": _SHA,
            "result": result, "evidence_refs": [f"fixture:{gate}:evidence"],
            "blocking_evidence_refs": [], "rollback_ref": "fixture:rollback",
            "rollback_status": "available", "impact_ref": "fixture:impact-none", "next_step_ref": "fixture:next",
            "acceptance_receipt_refs": (original119._g12_receipts(call["run_id"]) if gate == "119-G12" else None),
            "effect_stage_refs": stages if gate in {"119-G11", "119-G12", "128-ND12"} else None,
        }
        if "run_scope" in call:
            observation["run_scope"] = call["run_scope"]
            observation["distribution_digest"] = call["distribution_digest"]
        if self.mutation:
            self.mutation(call, observation)
        return observation


class Ticket128DefaultDeploymentVerificationTests(unittest.TestCase):
    """Seven independent families, not seven counts as sufficiency evidence."""
    maxDiff = None

    def _public(self):
        loader = getattr(health, "load_default_live_runtime", None)
        executor = getattr(health, "DefaultAcceptanceGateExecutor", None)
        missing = [name for name, value in (("load_default_live_runtime", loader), ("DefaultAcceptanceGateExecutor", executor))
                   if not callable(value)]
        self.assertFalse(missing, "Ticket128 public prerequisites absent: " + ", ".join(missing) +
                         "; no internal case in this family has executed")
        return loader, executor

    def _manifest(self):
        fixture = original119.Ticket119VerificationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        return fixture.manifest

    @staticmethod
    def _context(scope="non-diagnostic", run="acceptance-run:ticket128-fixture", approvals=None, existing=None):
        value = original119.Ticket119VerificationTests._context(
            run_id=run,
            approvals=_ND_APPROVALS if approvals is None else approvals,
            existing_report=existing)
        if scope is not None:
            value["run_scope"] = scope
            value["distribution_digest"] = "sha256:" + "b" * 64
        return value

    def _assert_fixture_only(self, report):
        self.assertEqual(report["evidence_scope"], "contract-fixture")
        self.assertEqual(report["diagnostic_scope_phase"], "staged")
        for name in ("technical_gate_verdict", "target_binding_verdict", "real_interface_verdict", "deployment", "active", "product_acceptance"):
            self.assertNotIn(report[name], {"passed", "ready", "active", "activation-ready"}, name)
        self.assertEqual(report["stable_operation"], "evidence-required")

    def test_v128_01_fixed_scopes_bound_identity_and_legacy_report(self):
        self._public()
        manifest = self._manifest()
        contract = health.AcceptanceRunContract()
        # The exact old context remains full, retaining its schema and digest.
        old_context = self._context(None, run="acceptance-run:ticket128-characterization", approvals=("119-G08", "119-G10", "119-G11", "119-G12"))
        old_executor = original119._FakeGateExecutor()
        old_report = _wire(contract.run(manifest, old_executor, old_context))
        self.assertEqual(tuple(item["gate_id"] for item in old_report["gates"]), _FULL)
        self.assertNotIn("run_scope", old_report)
        self.assertEqual(old_report["report_digest"], "sha256:0b033c7e69690ea5fa0700c7d825bf6d1e175c71ed9568d0df87dff054ba6c8d")
        self.assertEqual(old_report["report_digest"], original119._canonical_report_digest(old_report))
        replay_executor = original119._FakeGateExecutor(fail_on_call=True)
        replay_context = copy.deepcopy(old_context)
        replay_context["existing_report"] = copy.deepcopy(old_report)
        self.assertEqual(_wire(contract.run(manifest, replay_executor, replay_context)), old_report)
        self.assertEqual(replay_executor.calls, [])
        nd = _DecisionExecutor()
        nd_context = self._context()
        report = _wire(contract.run(manifest, nd, nd_context))
        self.assertEqual(tuple(c["gate_id"] for c in nd.calls), _ND)
        self.assertEqual(tuple(item["gate_id"] for item in report["gates"]), _ND)
        self.assertEqual(report["run_scope"], "non-diagnostic")
        self.assertEqual(report["distribution_digest"], nd_context["distribution_digest"])
        self.assertTrue(all(call["run_scope"] == "non-diagnostic" and call["distribution_digest"] == nd_context["distribution_digest"] for call in nd.calls))
        self.assertEqual(report["report_digest"], original119._canonical_report_digest(report))
        self._assert_fixture_only(report)
        # Unknown frontier blocks the entire exact suffix; no per-position cross product.
        stopped = _DecisionExecutor(frontier="119-G11")
        stopped_report = _wire(contract.run(manifest, stopped, self._context(run="acceptance-run:ticket128-unknown")))
        self.assertEqual([c["gate_id"] for c in stopped.calls], list(_ND[:-1]))
        self.assertEqual(stopped_report["gates"][-1]["result"], "blocked")
        self.assertEqual(stopped_report["gates"][-1]["blocked_by_gate"], "119-G11")
        for name, context in (
            ("cross-scope", self._context("full", existing=report)),
            ("cross-target", dict(self._context(existing=report), target_ref="target:other")),
            ("same-host-other-distribution", dict(self._context(existing=report), distribution_digest="sha256:" + "c" * 64)),
            ("caller-order", dict(self._context(), gates=list(reversed(_ND)))),
            ("scope-without-distribution", {k: v for k, v in self._context().items() if k != "distribution_digest"}),
            ("distribution-without-scope", {k: v for k, v in self._context().items() if k != "run_scope"}),
        ):
            with self.subTest(reality_error=name):
                boundary = _DecisionExecutor()
                try:
                    rejected = _wire(contract.run(manifest, boundary, context))
                except (ValueError, TypeError):
                    pass
                else:
                    self.assertNotEqual(rejected.get("run_verdict"), "passed")
                self.assertEqual(boundary.calls, [])
        borrowed = _DecisionExecutor()
        borrowed_context = self._context(approvals=("119-G08", "119-G10", "119-G11", "119-G12"))
        borrowed_report = _wire(contract.run(manifest, borrowed, borrowed_context))
        self.assertNotIn("128-ND12", [c["gate_id"] for c in borrowed.calls])
        self.assertEqual(borrowed_report["gates"][-1]["result"], "not-authorized")
        # Exact ND replay freezes even unknown; existing reports do not resume.
        replay = _DecisionExecutor()
        self.assertEqual(_wire(contract.run(manifest, replay, self._context(existing=report))), report)
        self.assertEqual(replay.calls, [])

    def test_v128_02_same_publication_live_factory_and_exact_disclosure(self):
        self._public()
        self._run_formal_family("live")

    def test_v128_03_first_bootstrap_and_real_replica_absence(self):
        self._public()
        self._run_formal_family("bootstrap")

    def test_v128_04_default_only_complete_program_rollback(self):
        self._public()
        self._run_formal_family("rollback")

    def test_v128_05_three_real_os_roles_and_no_root_agent_bypass(self):
        self._public()
        self._run_formal_family("isolation")

    def test_v128_06_g11_single_attempt_native_action_and_original_cursor(self):
        self._public()
        self._run_formal_family("g11")

    def test_v128_07_nd12_native_feedback_is_only_an_nd_milestone(self):
        self._public()
        self._run_formal_family("nd12")

    def _run_formal_family(self, family):
        if os.environ.get("TICKET128_NAMESPACE_WORKER") != self.id():
            # Full unittest discover owns this parent test/count. The frozen
            # operator creates a fresh namespace then runs this exact method;
            # its real failure/exit status is attributed to this parent test.
            runner = _RAW_INPUTS.with_name("ticket128_namespace_runner.py")
            self.assertTrue(runner.is_file(), "verifier-owned namespace runner is required")
            runtime = os.environ.get("TICKET123_RUNTIME_ROOT")
            pinned = os.environ.get("TICKET118_PINNED_HERMES_SOURCE")
            self.assertTrue(runtime and pinned, "actual closure and pinned inputs are required")
            completed = subprocess.run([sys.executable, "-I", "-B", str(runner),
                "--runtime-root", runtime, "--verifier-root", str(_REPOSITORY),
                "--pinned-root", pinned, "--method", self.id()],
                text=True, capture_output=True, timeout=5610)
            self.assertEqual(completed.returncode, 0,
                "isolated family failed\n" + completed.stdout[-16000:] + completed.stderr[-16000:])
            return
        with _FormalNamespace(self) as fixture:
            getattr(fixture, "check_" + family)()


def _pointer(value, pointer):
    for part in pointer.strip("/").split("/") if pointer else ():
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return copy.deepcopy(value)


def _schema_example(schema):
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        return _schema_example(schema["anyOf"][0])
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((v for v in kind if v != "null"), "null")
    if kind == "object" or "properties" in schema:
        return {key: _schema_example(schema["properties"][key]) for key in schema.get("required", [])}
    if kind == "array":
        return [_schema_example(schema.get("items", {})) for _ in range(schema.get("minItems", 0))]
    return {"string": "offline connection test", "integer": 1, "number": 1,
            "boolean": False, "null": None}.get(kind, "offline")


class _FramePort:
    """Independent client of the existing public bounded CorePort protocol."""
    def __init__(self, path):
        self.path = path

    def request(self, kind, payload, *, request_id):
        raw = _canonical({"protocol_version": 1, "kind": kind,
                          "request_id": request_id, "payload": payload})
        if len(raw) > 65536:
            raise AssertionError("verifier CorePort frame exceeds the existing bound")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(8)
            client.connect(self.path)
            client.sendall(struct.pack(">I", len(raw)) + raw)
            def exact(count):
                result = b""
                while len(result) < count:
                    part = client.recv(count - len(result))
                    if not part:
                        raise AssertionError("CorePort closed before exact frame")
                    result += part
                return result
            size = struct.unpack(">I", exact(4))[0]
            if size > 65536:
                raise AssertionError("CorePort reply exceeds the existing bound")
            return json.loads(exact(size))


class _RawTLS:
    """Real loopback HTTPS; raw provider protocol only, never product verdicts."""
    def __init__(self, root):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import ipaddress
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                       .public_key(key.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
                       .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                      x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                                      x509.DNSName("ilinkai.weixin.qq.com"), x509.DNSName("novac2c.cdn.weixin.qq.com")]), critical=False)
                       .sign(key, hashes.SHA256()))
        self.ca = root / "offline-ca.pem"
        self.ca.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path = root / "offline-tls-key.pem"
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        key_path.chmod(0o600)
        self.ca.chmod(0o644)
        self.batches, self.requests, self.sends, self.cursors = [], [], [], []
        self.model_mode = "known"
        self.tool_command, self.tool_called = None, False
        self.candidates, self.default_answer = [], None
        self.media_ticket, self.ciphertext = None, None
        self.lock = threading.Lock()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                if size > 8 * 1024 * 1024:
                    self.send_error(413)
                    return
                raw = self.rfile.read(size)
                if self.path.startswith("/c2c/upload"):
                    with owner.lock:
                        owner.ciphertext = raw
                    self.send_response(200); self.send_header("x-encrypted-param", "synthetic-cdn-ticket")
                    self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")
                    return
                body = json.loads(raw)
                with owner.lock:
                    owner.requests.append((self.path, copy.deepcopy(body)))
                    if self.path.endswith("getupdates"):
                        owner.cursors.append(body.get("get_updates_buf", ""))
                        value = owner.batches.pop(0) if owner.batches else {
                            "ret": 0, "msgs": [], "get_updates_buf": body.get("get_updates_buf", "")}
                    elif self.path.endswith("getuploadurl"):
                        owner.media_ticket = copy.deepcopy(body)
                        value = {"ret": 0, "errcode": 0, "upload_param": "synthetic-upload-ticket"}
                    elif self.path.endswith("sendmessage"):
                        owner.sends.append(copy.deepcopy(body))
                        value = {"ret": 0, "errcode": 0}
                    elif self.path.endswith("getconfig"):
                        value = {"ret": 0, "typing_ticket": "ticket128-offline-typing"}
                    elif self.path.endswith("sendtyping"):
                        value = {"ret": 0, "errcode": 0}
                    elif self.path.endswith("responses") or self.path.endswith("chat/completions"):
                        if owner.model_mode == "unknown":
                            self.connection.shutdown(socket.SHUT_RDWR)
                            self.connection.close()
                            return
                        schema = body.get("text", {}).get("format", {}).get("schema", {})
                        schema_name = body.get("text", {}).get("format", {}).get("name", "")
                        stage = "intake" if schema_name == "nondiagnostic-intake-v1" else "answer"
                        if owner.candidates:
                            expected, candidate = owner.candidates.pop(0)
                            if expected != stage:
                                raise AssertionError("raw HTTP stage differs from queued source-bound response")
                        elif stage == "intake":
                            candidate = {"operation": "clarify", "facts": [], "question": None}
                        else:
                            candidate = owner.default_answer if owner.default_answer is not None else _schema_example(schema)
                        value = {"id": "response:ticket128-offline", "model": body.get("model"),
                                 "status": "completed", "usage": {"input_tokens": 30, "output_tokens": 8},
                                 "output": [{"type": "message", "status": "completed", "content": [
                                     {"type": "output_text", "text": json.dumps(candidate, ensure_ascii=False)}]}]}
                        if self.path.endswith("chat/completions"):
                            value = {"id": "chat:ticket128-offline", "model": body.get("model"),
                                     "choices": [{"index": 0, "message": {"role": "assistant", "content": "离线普通回复"},
                                                  "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 30, "completion_tokens": 8, "total_tokens": 38}}
                        if owner.tool_command and not owner.tool_called and "TICKET128_TOOL_PROBE" in json.dumps(body, ensure_ascii=False):
                            tool_names = [item.get("name", item.get("function", {}).get("name")) for item in body.get("tools", [])]
                            if "terminal" in tool_names:
                                owner.tool_called = True
                                arguments = json.dumps({"command": owner.tool_command})
                                if self.path.endswith("chat/completions"):
                                    value["choices"][0].update(finish_reason="tool_calls", message={"role":"assistant", "content":None,
                                        "tool_calls":[{"id":"call_ticket128_tool", "type":"function", "function":{"name":"terminal", "arguments":arguments}}]})
                                else:
                                    value["output"] = [{"type":"function_call", "call_id":"call_ticket128_tool", "name":"terminal", "arguments":arguments, "status":"completed"}]
                    else:
                        self.send_error(404)
                        return
                encoded = _canonical(value)
                streaming = self.path.endswith("chat/completions") and body.get("stream") is True
                if streaming:
                    choice = value["choices"][0]
                    message = choice["message"]
                    delta = {"role": "assistant", "content": message.get("content")}
                    if message.get("tool_calls"):
                        delta["tool_calls"] = [dict(item, index=index) for index, item in enumerate(message["tool_calls"])]
                    chunk = {"id": value["id"], "object": "chat.completion.chunk", "created": int(time.time()),
                             "model": value["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                    terminal = dict(chunk, choices=[{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}])
                    encoded = b"data: " + _canonical(chunk) + b"\n\ndata: " + _canonical(terminal) + b"\n\ndata: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                if self.path.endswith("getupdates"):
                    time.sleep(0.02)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.ca), str(key_path))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.origin = "https://localhost:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        # Exact pinned export API/CDN origins resolve only inside the owned
        # network namespace, with this verifier CA. Never bind host port443.
        self.pinned_server = ThreadingHTTPServer(("127.0.0.1", 443), Handler)
        self.pinned_server.daemon_threads = True
        self.pinned_server.socket = context.wrap_socket(self.pinned_server.socket, server_side=True)
        self.pinned_thread = threading.Thread(target=self.pinned_server.serve_forever, daemon=True)
        self.pinned_thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.pinned_server.shutdown(); self.pinned_server.server_close(); self.pinned_thread.join(timeout=3)

    def model_posts(self):
        with self.lock:
            return sum(path.endswith(("responses", "chat/completions")) for path, _ in self.requests)

    def native(self, admission, body, message_id, *, cursor=None):
        stamp = int(time.time() * 1000)
        native = {"message_id": message_id, "from_user_id": admission["owner_sender_id"],
                  "to_user_id": admission["partner_id"], "conversation_id": admission["conversation_id"],
                  "msg_type": 1, "chat_type": "private", "create_time_ms": stamp,
                  "context_token": "context:ticket128-offline", "item_list": [
                      {"type": 1, "text_item": {"text": body}}]}
        with self.lock:
            self.batches.append({"ret": 0, "msgs": [native],
                                 "get_updates_buf": cursor or "cursor:" + message_id})
        return native

    @staticmethod
    def text(send):
        chunks = []
        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "text" and isinstance(item, str):
                        chunks.append(item)
                    else:
                        visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        visit(send)
        return "\n".join(chunks)


class _FormalNamespace:
    """Data-only fixture; all decisions and OS/HTTP observations are independent.

    The operator prepares an owned mount namespace and private user-systemd bus.
    No command from fixture data is executed. Private JSON layout is located by
    the one verifier-owned raw fixture, not asserted as product architecture.
    """
    def __init__(self, case):
        self.case = case
        self.raw = json.loads(_RAW_INPUTS.read_text())
        self.processes = []

    def __enter__(self):
        c = self.case
        c.assertEqual(sys.platform, "linux", "formal Ticket128 gates require actual Linux")
        c.assertEqual(sys.version_info[:2], (3, 11), "actual declared Python3.11 is required; no version substitution")
        c.assertEqual(os.geteuid(), 0, "formal namespace controller must actually be root")
        raw_root = os.environ.get("TICKET128_NAMESPACE_ROOT")
        c.assertTrue(raw_root, "owned isolated namespace fixture is required")
        self.root = Path(raw_root).resolve()
        c.assertTrue(self.root.is_dir() and not self.root.is_symlink())
        c.assertNotEqual(os.readlink("/proc/self/ns/mnt"), os.readlink("/proc/1/ns/mnt"),
                         "tests must not touch the host mount namespace")
        self.home = Path("/root/.hermes")
        backing = os.environ.get("TICKET128_NAMESPACE_BACKING_ROOT", "")
        c.assertRegex(backing, r"^/opt/t128ns-family-[a-zA-Z0-9_-]+$")
        self.backing = Path(backing)
        home_mounts = [line.split(" - ", 1)[0].split() for line in Path("/proc/self/mountinfo").read_text().splitlines()
                       if line.split(" - ", 1)[0].split()[4] == str(self.home)]
        c.assertEqual(len(home_mounts), 1, "logical default needs its own kernel bind mount")
        c.assertEqual(home_mounts[0][3], str(self.backing / "default-home"))
        c.assertIn("rw", home_mounts[0][5].split(","))
        marker = self.home / ".ticket128-verifier-only"
        c.assertEqual(marker.read_text().strip(), str(self.root), "explicit owned-namespace marker missing")
        c.assertEqual(self.home.lstat().st_uid, 0)
        host_net = os.environ.get("TICKET128_HOST_NET_NS")
        c.assertRegex(host_net or "", r"^net:\[[0-9]+\]$")
        c.assertNotEqual(os.readlink("/proc/self/ns/net"), host_net,
                         "raw pinned HTTPS fixtures require an owned network namespace")
        for host in ("ilinkai.weixin.qq.com", "novac2c.cdn.weixin.qq.com"):
            c.assertEqual(socket.gethostbyname(host), "127.0.0.1", "pinned protocol host must resolve only to local raw fixture")
        consumed = self.root / ".ticket128-family-consumed"
        descriptor = os.open(consumed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, self.case._testMethodName.encode())
        os.close(descriptor)
        bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        c.assertTrue(bus.startswith("unix:path=" + str(self.root) + "/"), "a private user-manager bus is required")
        manager = self._command(["busctl", "--address=" + bus, "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                                 "org.freedesktop.DBus", "GetConnectionUnixProcessID", "s", "org.freedesktop.systemd1"])
        match = re.fullmatch(r"u ([0-9]+)\s*", manager)
        c.assertIsNotNone(match, "must establish actual private user-manager PID")
        self.manager_pid = int(match.group(1))
        c.assertEqual(os.readlink(f"/proc/{self.manager_pid}/ns/mnt"), os.readlink("/proc/self/ns/mnt"),
                      "systemctl manager must use the disposable mount namespace")
        runtime_root = os.environ.get("TICKET123_RUNTIME_ROOT")
        c.assertTrue(runtime_root, "actual formal closure location is required")
        self.runtime_root = Path(runtime_root).resolve()
        c.assertTrue(Path(sys.executable).resolve().is_relative_to(self.runtime_root))
        self.runtime_manifest = json.loads((self.runtime_root / "ticket123-runtime-manifest.json").read_text())
        pinned = os.environ.get("TICKET118_PINNED_HERMES_SOURCE")
        c.assertTrue(pinned, "actual pinned/shadow source input is required")
        self.pinned = Path(pinned).resolve()
        c.assertEqual(self._command(["git", "-C", str(self.pinned), "rev-parse", "HEAD"]).strip(),
                      "3c27eb6234bf91b8ceee9e9071591b31e9b148cb")
        self.work = Path(tempfile.mkdtemp(prefix="ticket128-verifier-", dir=self.root))
        # Public verifier code/TLS CA are not private health material. Low UID
        # ancestors must be traversable; private keys are never relaxed here.
        self.work.chmod(0o755)
        self.http = _RawTLS(self.work)
        self._env = dict(os.environ, SSL_CERT_FILE=str(self.http.ca), PYTHONDONTWRITEBYTECODE="1")
        self._command(["systemctl", "--user", "set-environment", "SSL_CERT_FILE=" + str(self.http.ca)])
        self.publisher = health.HermesReleasePublisher(_REPOSITORY)
        stage = _wire(self.publisher.build(self.work / "releases", resource_scope="non-diagnostic"))
        self.stage_root = self.work / "releases" / stage["release_digest"].removeprefix("sha256:")
        self.stage_snapshot = self._tree(self.stage_root)
        self.published = _wire(self.publisher.publish_current_successor(self.stage_root, self.runtime_manifest))
        self.release = self.work / "releases" / self.published["release_digest"].removeprefix("sha256:")
        c.assertEqual(self._tree(self.stage_root), self.stage_snapshot)
        c.assertEqual(self.published["state"], "current")
        c.assertNotEqual(self.published["release_digest"], self.published["host_release_digest"])
        self.run_id = "acceptance-run:ticket128-fixture-" + uuid.uuid4().hex
        # Real pinned credential loader, synthetic secrets only in this fresh
        # target. They never enter prepare input/release/report/Git.
        token = "SYNTHETIC128-" + uuid.uuid4().hex
        script = "import sys;sys.path.insert(0,sys.argv[1]);from gateway.platforms.weixin import save_weixin_account;save_weixin_account(sys.argv[2],account_id=sys.argv[3],token=sys.argv[4],base_url='https://ilinkai.weixin.qq.com')"
        self._command([sys.executable, "-I", "-B", "-c", script, str(self.pinned), str(self.home),
                       self.raw["admission_policy"]["partner_id"], token])
        environment = self.home / ".env"
        environment.write_text("JOJO_API_KEY=" + token + "\nOPENAI_API_KEY=SYNTHETIC128-ORDINARY-" + uuid.uuid4().hex +
                               "\nOPENAI_BASE_URL=" + self.http.origin + "/v1\n")
        environment.chmod(0o600)
        # Seed a real pre-existing quick-exec capability in this disposable
        # profile. The deployment must disable or reject it in relay mode.
        import yaml
        config_path = self.home / "config.yaml"
        config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
        config = config or {}
        config["model"] = {"provider": "custom", "default": "ticket128-ordinary-offline",
                           "base_url": self.http.origin + "/v1", "api_mode": "chat_completions"}
        self.quick_sentinel = self.work / "gateway-quickexec-ran"
        config.setdefault("quick_commands", {})["ticket128-quickexec"] = {
            "type": "exec", "command": "touch " + str(self.quick_sentinel)}
        self.plugin_sentinel = self.work / "gateway-plugin-command-ran"
        fixture_plugin = self.home / "plugins/ticket128-bypass"
        fixture_plugin.mkdir(parents=True)
        (fixture_plugin / "plugin.yaml").write_text("name: ticket128-bypass\nversion: 1.0.0\ndescription: Synthetic existing slash command fixture\n")
        (fixture_plugin / "__init__.py").write_text(
            "from pathlib import Path\ndef command(raw_args):\n    Path(" + repr(str(self.plugin_sentinel)) + ").write_text('synthetic root bypass')\n    return 'executed'\ndef register(ctx):\n    ctx.register_command('ticket128-plugin',handler=command)\n")
        config.setdefault("plugins", {}).setdefault("enabled", []).append("ticket128-bypass")
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True))
        config_path.chmod(0o600)
        self._prepare()
        return self

    def __exit__(self, *args):
        # Stop only units named by this disposable setup. Never restore a
        # healthy authority from a program snapshot during test teardown.
        if hasattr(self, "setup"):
            for role in reversed(self.slot("roles")):
                self._command(["systemctl", "--user", "stop", role["unit"]], check=False)
        if hasattr(self, "http"):
            self.http.close()
        return False

    def _command(self, argv, *, check=True):
        result = subprocess.run(argv, text=True, capture_output=True, env=getattr(self, "_env", None), timeout=60)
        if check:
            self.case.assertEqual(result.returncode, 0,
                                  "public command failed: " + " ".join(argv[:3]) + "\n" + result.stderr[-3000:])
        return result.stdout

    @staticmethod
    def _tree(root):
        result = {}
        if not root.exists():
            return result
        for path in sorted(root.rglob("*")):
            details = path.lstat()
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(details.st_mode):
                result[relative] = ("symlink", os.readlink(path))
            elif stat.S_ISREG(details.st_mode):
                result[relative] = ("file", details.st_uid, details.st_gid, stat.S_IMODE(details.st_mode),
                                    hashlib.sha256(path.read_bytes()).hexdigest())
            elif stat.S_ISDIR(details.st_mode):
                result[relative] = ("dir", details.st_uid, details.st_gid, stat.S_IMODE(details.st_mode))
        return result

    def _prepare(self, *, run_id=None, release=None):
        from partner_health_steward.model_contract import FirstHopRoute, NonDiagnosticOperationalBudget
        now = datetime.now(timezone.utc)
        route = FirstHopRoute("jojo-responses-v1", "jojo", self.http.origin + "/v1", "responses",
                              "ticket128-offline-model", 1, _digest({"source": "synthetic-boundary-input-only"}))
        budget = NonDiagnosticOperationalBudget("budget:ticket128-offline", "1", route, (route.requested_model,),
                "owner-decision:contract-fixture-not-real-approval", (now - timedelta(hours=1)).isoformat(),
                (now + timedelta(hours=1)).isoformat())
        raw = {"admission_policy": self.raw["admission_policy"], "route": route.to_wire(),
               "operational_budget": budget.to_wire(), "runtime_root": str(self.runtime_root),
               "pinned_hermes_root": str(self.pinned), "weixin_base_url": "https://ilinkai.weixin.qq.com",
               "timezone": "Asia/Shanghai", "preferences": {"contact_window": "09:00-21:00",
                   "expression_style": "concise", "proactive_support": False},
               "support_contact": None}
        raw_path = self.work / "target-input.json"
        raw_path.write_bytes(_canonical(raw))
        raw_path.chmod(0o600)
        command = [sys.executable, "-I", "-B", str(_REPOSITORY / "tools/ticket128_deploy.py"), "prepare",
                   "--release", str(release or self.release), "--run-id", run_id or self.run_id,
                   "--run-scope", "non-diagnostic", "--input", str(raw_path)]
        self.prepare_output = json.loads(self._command(command))
        # Every resource a controller will mutate must be backed by this
        # fixture, not only the profile. A private bus string is not proof.
        mounts = [(line.split(" - ", 1)[0].split()[4], line.split(" - ", 1)[0].split()[3])
                  for line in Path("/proc/self/mountinfo").read_text().splitlines()]
        for resource in self.prepare_output.get("program_resources", []):
            path = Path(resource).absolute()
            owned = path.is_relative_to(self.root) or path.is_relative_to(self.home)
            # Kernel mount roots use physical operator backing, which differs
            # from the short logical /run path needed by AF_UNIX sockets.
            owned = owned or any(path.is_relative_to(Path(mount)) and
                (source == str(self.backing) or source.startswith(str(self.backing) + "/"))
                for mount, source in mounts)
            self.case.assertTrue(owned, "program resource has no disposable backing: " + str(path))
        path = self.home / ".ticket128-deployment-binding.json"
        details = path.lstat()
        self.case.assertTrue(stat.S_ISREG(details.st_mode) and not path.is_symlink())
        self.case.assertEqual((details.st_uid, stat.S_IMODE(details.st_mode), details.st_nlink), (0, 0o600, 1))
        self.setup = json.loads(path.read_text())
        if release is not None:
            self.release = Path(release)
            self.published = json.loads((self.release / "release-manifest.json").read_text())
        # These selectors locate raw public-operation input, never verdicts.
        self.context = self.slot("run_context")
        self.context["environment_class"] = "verifier-synthetic-deny-network"
        self.case.assertEqual(self.context["run_scope"], "non-diagnostic")
        self.case.assertEqual(self.context["run_id"], run_id or self.run_id)

    def slot(self, name):
        return _pointer(self.setup, self.raw["binding_selectors"][name])

    def host_manifest(self):
        host = json.loads((self.release / "host-release-manifest.json").read_text())
        sources = {key: copy.deepcopy(host[key]) for key in (
            "pinned_hermes", "environment_constraints", "target_binding_required",
            "external_approval_required", "forbidden_secret_classes")}
        sources.update(contract="ticket118-release-sources-v1", repository_root=str(self.release),
                       artifacts=[{"path": item["path"], "role": item["role"]} for item in host["repository_verified"]])
        manifest = health.HostReleaseContract().build(sources)
        self.case.assertEqual(_wire(manifest)["release_digest"], self.published["host_release_digest"])
        return manifest

    def run_until(self, stop_gate="119-G11"):
        context = copy.deepcopy(self.context)
        # Missing next gate approval is the public bounded stop. No caller
        # gate list/order and no direct install of a future gate are used.
        context["approval_refs"].pop(stop_gate, None)
        report = _wire(health.AcceptanceRunContract().run(self.host_manifest(), health.DefaultAcceptanceGateExecutor(), context))
        self.case._assert_fixture_only(report)
        entries = {g["gate_id"]: g for g in report["gates"]}
        self.case.assertEqual(entries[stop_gate]["result"], "not-authorized")
        before = _ND[:_ND.index(stop_gate)]
        for gate in before:
            self.case.assertEqual(entries[gate]["result"], "passed", gate)
        self.setup = json.loads((self.home / ".ticket128-deployment-binding.json").read_text())
        return report

    def _rpc(self, kind, selector, name, payload=None):
        binding = self.slot("service_binding")
        identity = "ticket128-rpc:" + uuid.uuid4().hex
        result = _FramePort(binding["socket_path"]).request(kind,
            {"interface": "health-entry-v1", selector: name, "payload": payload or {}}, request_id=identity)
        self.case.assertEqual((result["protocol_version"], result["kind"], result["request_id"], result["status"]),
                              (1, kind, identity, "accepted"))
        return result["payload"]

    def read(self, projection, payload=None):
        return self._rpc("managed-read", "projection", projection, payload)

    def wake(self):
        # Existing trusted Plugin operation and existing delivery bridge. The
        # Core selects due work/current day; the verifier supplies no clock,
        # grant, ready flag, receipt, recipient or message body.
        from partner_health_steward.live_delivery import LiveWeixinDeliveryBridge
        from partner_health_steward.weixin_transport import WeixinTransportBinding, PinnedWeixinOwnerDeliveryAdapter
        from gateway.platforms.weixin import load_weixin_account
        account = load_weixin_account(str(self.home), self.raw["admission_policy"]["partner_id"])
        binding = WeixinTransportBinding(self.raw["admission_policy"]["partner_id"], "https://ilinkai.weixin.qq.com")
        import aiohttp
        def session_factory(**kwargs):
            return aiohttp.ClientSession(**kwargs, connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=str(self.http.ca))))
        bridge = LiveWeixinDeliveryBridge(_FramePort(self.slot("service_binding")["socket_path"]),
            lambda authorization: PinnedWeixinOwnerDeliveryAdapter(binding, authorization,
                token=account["token"], context_token_provider=lambda recipient: "context:ticket128-offline",
                session_factory=session_factory),
            clock=lambda: datetime.now(timezone.utc))
        observed = self._rpc("command", "operation", "governed-wake")
        self.case.assertEqual(observed["task_status"], "current")
        for reference in observed["delivery_refs"]:
            result = asyncio.run(bridge.send_committed(reference))
            self.case.assertTrue(result["handoff_complete"], result)
        return observed

    def _wait(self, predicate, *, seconds=12):
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            try:
                last = predicate()
            except (ConnectionError, OSError) as error:
                # Actual service restart may briefly have no listening socket.
                # Contract/shape/assertion failures are never hidden here.
                last = type(error).__name__
                time.sleep(0.02)
                continue
            if last:
                return last
            time.sleep(0.02)
        self.case.fail("public implementation did not reach bounded observation; last=" + repr(last))

    def enqueue(self, text, suffix, *, cursor=None):
        return self.http.native(self.raw["admission_policy"], text, "native128:" + suffix, cursor=cursor)

    def initialized(self):
        return self.read("health-entry-initialization")["initialization"]

    def initialize(self):
        before = len(self.http.sends)
        self.enqueue("/health-init", "begin-init")
        self._wait(lambda: len(self.http.sends) > before)
        text = "\n".join(_RawTLS.text(item) for item in self.http.sends[before:])
        self.case.assertIn("诊断未启用", text)
        self.case.assertIn("共同上下文", text)
        self.case.assertRegex(text, "快照|snapshot")
        self.case.assertEqual(self.initialized()["phase"], "uninitialized")
        command = re.search(r"/health-init-confirm\s+([^\s`]+)\s+([^\s`]+)", text)
        self.case.assertIsNotNone(command, "actual disclosure must supply the exact independent confirmation instruction")
        self.disclosure = self.read("health-entry-disclosure", {"workflow_id": command.group(1)})
        self.case.assertIsNotNone(self.disclosure["initialization"])
        self.case.assertIsNotNone(self.disclosure["disclosure"])
        self.enqueue(command.group(0) + "-forged", "forged-confirm-init")
        self._wait(lambda: not self.http.batches)
        time.sleep(0.1)
        self.case.assertEqual(self.initialized()["phase"], "uninitialized")
        self.enqueue(command.group(0), "confirm-init")
        self._wait(lambda: self.initialized()["phase"] == "enabled")
        self.case.assertTrue(self.initialized()["enabled"])

    def check_live(self):
        # prepare itself may not create health key/head/attestors or enable.
        binding = self.slot("service_binding")
        self.case.assertFalse(Path(binding["database_path"]).exists())
        old_default = self.publisher.build(self.work / "old-staged").to_wire()
        self.case.assertEqual(old_default["state"], "staged")
        self.run_until()
        observed = self._core_public("loader")
        self.case.assertEqual(observed["runtime_type"], "LiveHealthRuntime")
        self.case.assertEqual(observed["knowledge_count"], 0)
        self.case.assertTrue(observed["diagnostic_scope_absent"])
        self.case.assertEqual(self.initialized()["phase"], "uninitialized")
        before = self.http.model_posts()
        self.enqueue(self.raw["messages"]["health"], "health-preinit")
        self.enqueue(self.raw["messages"]["mixed"], "mixed-preinit")
        self.enqueue(self.raw["messages"]["uncertain"], "uncertain-preinit")
        time.sleep(0.1)
        self.case.assertEqual(self.http.model_posts(), before)
        self.case.assertEqual(self.initialized()["phase"], "uninitialized")
        self.initialize()
        from partner_health_steward.initialization import HealthInitAsset, InitializationDisclosure, OwnerInitialization
        content = InitializationDisclosure.from_storage(self.disclosure["disclosure"]).content
        initialization = OwnerInitialization.from_storage(self.disclosure["initialization"])
        asset = HealthInitAsset.from_storage(self._core_public("resources")["health_init_asset"])
        self.case.assertTrue(content.matches(initialization, asset))
        altered_notice = replace(content.owner_visible_notices[0], text=content.owner_visible_notices[0].text + " 未获准追加正文")
        self.case.assertFalse(replace(content, owner_visible_notices=(altered_notice, *content.owner_visible_notices[1:])).matches(initialization, asset))
        self.case.assertFalse(replace(content, version="unapproved-ticket128-version").matches(initialization, asset))
        self.case.assertFalse(content.matches(initialization, replace(asset, asset_digest="sha256:" + "0" * 64)))
        status = self.read("health-entry-business-status")["business_status"]["projection"]
        self.case.assertIn(status["state"], {"normal", "abnormal", "cannot-confirm"})
        self.case.assertNotEqual(status["state"], "active")
        # Tamper actual published bytes; neither arbitrary manifest rehash nor
        # a fake LiveHealthRuntime is allowed to make them current again.
        asset = Path(self.slot("service_binding")["release_root"]) / "skills/health-init/SKILL.md"
        original = asset.read_bytes()
        try:
            asset.write_bytes(original + b"\nTICKET128_RESOURCE_DRIFT\n")
            self.case.assertNotEqual(self._core_public("loader", check=False)["returncode"], 0)
        finally:
            asset.write_bytes(original)
        # Preserve exact old111 proof behavior; new content may not globally
        # turn matches into a permissive executor callback acceptance check.
        from tests.test_ticket111_admission_initialization import Ticket111AdmissionInitializationTests
        for name in ("test_wrong_asset_forged_proof_and_model_self_report_cannot_prepare",
                     "test_disclosure_challenge_is_prior_durable_and_owner_visible"):
            result = unittest.TestResult()
            Ticket111AdmissionInitializationTests(name).run(result)
            self.case.assertTrue(result.wasSuccessful(), result.errors + result.failures)

    def _core_public(self, operation, *, check=True):
        # Existing121/129 euid ownership checks are fixture preconditions.
        # Execute public reads under the actual running Core identity instead
        # of weakening/chowning its files for the root verifier.
        role = next(item for item in self.slot("roles") if item["role"] == "core")
        if not hasattr(self, "_core_identity"):
            pid = int(self._command(["systemctl", "--user", "show", role["unit"], "--property=MainPID", "--value"]).strip())
            fields = {line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in
                      Path(f"/proc/{pid}/status").read_text().splitlines() if ":" in line}
            self._core_identity = fields["Uid"].split()[1], fields["Gid"].split()[1]
            self._core_python = str(Path(f"/proc/{pid}/exe").resolve())
            self.case.assertEqual(hashlib.sha256(Path(self._core_python).read_bytes()).digest(),
                                  hashlib.sha256(Path(sys.executable).read_bytes()).digest(),
                                  "Core helper must use the actual same closure interpreter bytes")
        uid, gid = self._core_identity
        raw = {"release": self.slot("service_binding")["release_root"], "published": self.published,
               "live": self.slot("live_binding"), "service": self.slot("service_binding"),
               "head": self.slot("head_binding")}
        argv = ["setpriv", "--reuid", uid, "--regid", gid, "--clear-groups",
                self._core_python, "-I", "-B", "-c", _CORE_PUBLIC_READ, operation]
        env = {key: value for key, value in self._env.items() if not re.search(r"JOJO|WEIXIN|API.?KEY|TOKEN|SECRET", key, re.I)}
        result = subprocess.run(argv, input=_canonical(raw).decode(), capture_output=True, text=True, env=env, timeout=15)
        if not check:
            return {"returncode": result.returncode}
        self.case.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return json.loads(result.stdout)

    def _approved_candidate(self):
        resources = self._core_public("resources")
        claims = resources["claims"]
        template = resources["templates"][0]
        ids = {kind: [item["atom_id"] for item in claims if item["kind"] == kind]
               for kind in ("support", "opposition", "unknown", "limitation", "next-step")}
        self.case.assertTrue(all(ids.values()), "actual release must supply the fixed five governance sections")
        return {"owner_fact_refs": [], "knowledge_refs": [], "support": ids["support"],
                "opposition": ids["opposition"], "unknowns": ids["unknown"], "limitations": ids["limitation"],
                "next_steps": ids["next-step"], "claim_ids": [item for group in ids.values() for item in group],
                "template_id": template["template_id"]}

    def _authority_snapshot(self):
        return self._core_public("head")

    def _private_snapshot(self):
        binding = self.slot("service_binding")
        paths = binding["host_private_paths"]
        if not isinstance(paths, dict):
            paths = asdict(paths)
        result = {}
        for name, value in paths.items():
            path = Path(value)
            if path.is_file():
                details = path.lstat()
                self.case.assertEqual(stat.S_IMODE(details.st_mode), 0o400)
                self.case.assertEqual(details.st_nlink, 1)
                self.case.assertFalse(path.is_symlink())
                result[name] = (details.st_ino, hashlib.sha256(path.read_bytes()).hexdigest())
        return result

    def check_bootstrap(self):
        binding = self.slot("service_binding")
        self.case.assertFalse(Path(binding["database_path"]).exists(), "prepare must not bootstrap authority")
        self.run_until()
        first = self._authority_snapshot()
        keys = self._private_snapshot()
        self.case.assertEqual(first["generation"], 1)
        self.case.assertFalse(first["terminal"])
        self.case.assertGreaterEqual(len(keys), 3)
        # Real absence: do not make 14 files or a purge receipt as a prerequisite.
        root = Path(binding["managed_replica_root"])
        self.case.assertEqual(list(root.iterdir()), [])
        enumerated = self._core_public("replicas")
        from partner_health_steward.lifecycle import LIFECYCLE_PURGE_BINDINGS
        self.case.assertEqual(set(enumerated["configured"]), set(LIFECYCLE_PURGE_BINDINGS))
        self.case.assertEqual(list(root.iterdir()), [])
        foreign = root / "undeclared-object"
        foreign.write_bytes(b"synthetic external managed object")
        foreign.chmod(0o600)
        try:
            self.case.assertNotEqual(self._core_public("replicas", check=False)["returncode"], 0)
        finally:
            foreign.unlink()
        for role in self.slot("roles"):
            self._command(["systemctl", "--user", "restart", role["unit"]])
        self._wait(lambda: self.initialized()["phase"] == "uninitialized")
        self.case.assertEqual(self._authority_snapshot(), first)
        self.case.assertEqual(self._private_snapshot(), keys)
        # A partially retained first authority is not a fresh installation.
        # Losing one private capability with gen1/head already present must
        # fail closed, not silently mint a replacement key or installation.
        private = self.slot("service_binding")["host_private_paths"]
        data_key = Path(private["data_key"])
        held_key = data_key.with_name(data_key.name + ".fixture-held")
        for role in reversed(self.slot("roles")):
            self._command(["systemctl", "--user", "stop", role["unit"]])
        data_key.rename(held_key)
        try:
            self._prepare(run_id="acceptance-run:ticket128-partial-authority-" + uuid.uuid4().hex)
            partial = _wire(health.AcceptanceRunContract().run(self.host_manifest(), health.DefaultAcceptanceGateExecutor(), self.context))
            self.case.assertNotEqual(partial["run_verdict"], "passed")
            self.case.assertFalse(data_key.exists(), "partial authority must not be repaired by rebootstrap")
            self.case.assertEqual(self._authority_snapshot(), first)
        finally:
            held_key.rename(data_key)
        for role in self.slot("roles"):
            self._command(["systemctl", "--user", "start", role["unit"]])
        self._wait(lambda: self.initialized()["phase"] == "uninitialized")
        self.case.assertEqual(self._private_snapshot(), keys)
        self.initialize()
        advanced = self._authority_snapshot()
        self.case.assertGreater(advanced["generation"], first["generation"])
        self._prepare(run_id="acceptance-run:ticket128-rebootstrap-" + uuid.uuid4().hex)
        self.run_until()
        self.case.assertEqual(self._authority_snapshot(), advanced)
        self.case.assertEqual(self._private_snapshot(), keys)
        # Removal is deliberate destructive *fixture* injection. The production
        # public startup must not silently rebuild it as a new installation.
        head_values = self.slot("head_binding").get("binding", self.slot("head_binding"))
        head_path = Path(head_values["database_path"])
        for role in reversed(self.slot("roles")):
            self._command(["systemctl", "--user", "stop", role["unit"]])
        held = head_path.with_suffix(head_path.suffix + ".fixture-held")
        head_path.rename(held)
        try:
            self._prepare(run_id="acceptance-run:ticket128-missing-head-" + uuid.uuid4().hex)
            result = _wire(health.AcceptanceRunContract().run(self.host_manifest(), health.DefaultAcceptanceGateExecutor(), self.context))
            self.case.assertNotEqual(result["run_verdict"], "passed")
            self.case.assertFalse(head_path.exists(), "missing existing head must not be reconstructed")
            self.case.assertEqual(self._private_snapshot(), keys)
        finally:
            held.rename(head_path)

    def _program_snapshot(self):
        # Locations come from actual prepare output; only program resources are
        # included. Health files are independently checked, never restored here.
        resources = self.prepare_output.get("program_resources")
        self.case.assertIsInstance(resources, list, "public prepare must identify its bounded local program plan")
        self.case.assertGreaterEqual(len(set(resources)), 5, "an empty/duplicate plan cannot prove complete program rollback")
        self.case.assertTrue(any("plugins" in Path(value).parts for value in resources))
        self.case.assertTrue(any(Path(value).name == "config.yaml" for value in resources))
        for role in self.slot("roles"):
            self.case.assertTrue(any(Path(value) == Path(role["unit_path"]) or Path(role["unit_path"]).is_relative_to(Path(value)) for value in resources))
        result = {}
        for value in resources:
            path = Path(value)
            if path.exists() and path.is_dir():
                result[value] = self._tree(path)
            elif path.exists():
                details = path.lstat()
                result[value] = (details.st_uid, details.st_gid, stat.S_IMODE(details.st_mode), path.read_bytes())
            else:
                result[value] = None
        return result

    def _second_distribution(self):
        # A real same-H/different-D publication: this extra unused product
        # source is outside HostReleaseContract's allowlisted artifacts but is
        # collected by the same Publisher. No manifest is manually rehashed.
        source = self.work / ("second-source-" + uuid.uuid4().hex)
        shutil.copytree(_REPOSITORY, source, ignore=shutil.ignore_patterns(".git", ".scratch", "__pycache__"))
        (source / "partner_health_steward" / "ticket128_distribution_probe.py").write_text(
            '"""Unused verifier-only distribution identity input."""\n')
        publisher = health.HermesReleasePublisher(source)
        staged = _wire(publisher.build(self.work / "other-releases", resource_scope="non-diagnostic"))
        staged_root = self.work / "other-releases" / staged["release_digest"].removeprefix("sha256:")
        current = _wire(publisher.publish_current_successor(staged_root, self.runtime_manifest))
        self.case.assertEqual(current["host_release_digest"], self.published["host_release_digest"])
        self.case.assertNotEqual(current["release_digest"], self.published["release_digest"])
        return self.work / "other-releases" / current["release_digest"].removeprefix("sha256:")

    def check_rollback(self):
        # A wrong target in the fixed operation input must fail before creating
        # backup/provision/service state, even with a syntactically valid ref.
        setup_path = self.home / ".ticket128-deployment-binding.json"
        original = setup_path.read_bytes()
        before = self._tree(self.home)
        wrong = copy.deepcopy(self.setup)
        wrong["target"] = {"profile": "partner", "hermes_home": "/root/.hermes-partner",
                           "service": "hermes-gateway-partner.service"}
        setup_path.write_bytes(_canonical(wrong))
        try:
            result = _wire(health.AcceptanceRunContract().run(self.host_manifest(), health.DefaultAcceptanceGateExecutor(), self.context))
            self.case.assertNotEqual(result["run_verdict"], "passed")
            after = self._tree(self.home)
            # The injected binding itself is excluded; all other bytes/metadata
            # must remain identical and no partner path is ever created.
            before.pop(".ticket128-deployment-binding.json", None)
            after.pop(".ticket128-deployment-binding.json", None)
            self.case.assertEqual(after, before)
            self.case.assertFalse(Path("/root/.hermes-partner").exists())
        finally:
            setup_path.write_bytes(original)
        self.run_until()
        self.initialize()
        head, keys = self._authority_snapshot(), self._private_snapshot()
        old_context = copy.deepcopy(self.context)
        alternate = self._second_distribution()
        self._prepare(run_id="acceptance-run:ticket128-different-D-" + uuid.uuid4().hex, release=alternate)
        self.case.assertEqual(self.published["host_release_digest"], old_context.get("release_digest", self.published["host_release_digest"]))
        borrowed = copy.deepcopy(self.context)
        borrowed["approval_refs"] = copy.deepcopy(old_context["approval_refs"])
        untouched = self._program_snapshot()
        refused = _wire(health.AcceptanceRunContract().run(self.host_manifest(), health.DefaultAcceptanceGateExecutor(), borrowed))
        self.case.assertNotEqual(next(g for g in refused["gates"] if g["gate_id"] == "119-G10")["result"], "passed")
        self.case.assertEqual(self._program_snapshot(), untouched)
        self._prepare(run_id="acceptance-run:ticket128-rollback-" + uuid.uuid4().hex, release=alternate)
        program = self._program_snapshot()
        # Public service failure at the existing external service Seam. It is
        # not a fake product rollback decision: real backup/restore bytes run.
        real_run = subprocess.run
        failing = {"remaining": 1}
        def service_boundary(argv, *args, **kwargs):
            values = list(argv) if not isinstance(argv, str) else []
            if values[:2] == ["systemctl", "--user"] and "restart" in values and failing["remaining"]:
                failing["remaining"] -= 1
                return subprocess.CompletedProcess(argv, 1, "", "synthetic restart refusal")
            return real_run(argv, *args, **kwargs)
        with patch("subprocess.run", service_boundary):
            result = _wire(health.AcceptanceRunContract().run(self.host_manifest(), health.DefaultAcceptanceGateExecutor(), self.context))
        self.case.assertEqual(failing["remaining"], 0, "late service failure must actually be reached")
        g10 = next(item for item in result["gates"] if item["gate_id"] == "119-G10")
        self.case.assertIn(g10["result"], {"failed", "cannot-confirm"})
        self.case.assertEqual(self._program_snapshot(), program)
        self.case.assertEqual(self._authority_snapshot(), head)
        self.case.assertEqual(self._private_snapshot(), keys)
        self.case.assertEqual(self.initialized()["phase"], "enabled")
        # An unsafe pre-existing root-Agent baseline is a different reality
        # class. Do not restart it while retained health material exists.
        gateway = next(role for role in self.slot("roles") if role["role"] == "gateway")
        unit_path = Path(gateway["unit_path"])
        safe_unit = unit_path.read_bytes()
        unsafe_script = self.work / "unsafe_baseline.py"
        unsafe_script.write_text("from pathlib import Path\nPath(" + repr(str(self.work / "unsafe-started")) + ").write_text('unsafe root agent attempted')\n")
        unsafe = ("[Unit]\nDescription=unsafe root local fixture baseline\n[Service]\nExecStart=" + sys.executable + " " + str(unsafe_script) + "\n").encode()
        unit_path.write_bytes(unsafe)
        self._prepare(run_id="acceptance-run:ticket128-unsafe-rollback-" + uuid.uuid4().hex)
        failing["remaining"] = 1
        try:
            with patch("subprocess.run", service_boundary):
                failed = _wire(health.AcceptanceRunContract().run(self.host_manifest(), health.DefaultAcceptanceGateExecutor(), self.context))
            entry = next(item for item in failed["gates"] if item["gate_id"] == "119-G10")
            self.case.assertNotEqual(entry["result"], "passed")
            self.case.assertNotIn(entry.get("rollback_status"), {"completed", "confirmed"})
            self.case.assertEqual(self._authority_snapshot(), head)
            self.case.assertEqual(self._private_snapshot(), keys)
            state = self._command(["systemctl", "--user", "is-active", gateway["unit"]], check=False).strip()
            self.case.assertNotEqual(state, "active")
            self.case.assertFalse((self.work / "unsafe-started").exists(), "unsafe previous local execution must never start")
        finally:
            unit_path.write_bytes(safe_unit)
            self._command(["systemctl", "--user", "daemon-reload"])

    def check_isolation(self):
        self.run_until()
        roles = {role["role"]: role for role in self.slot("roles")}
        self.case.assertEqual(set(roles), {"gateway", "core", "ordinary"})
        identities = {}
        role_interpreters = {}
        for name, role in roles.items():
            pid = int(self._command(["systemctl", "--user", "show", role["unit"], "--property=MainPID", "--value"]).strip())
            self.case.assertGreater(pid, 1)
            status = Path(f"/proc/{pid}/status").read_text()
            fields = {line.split(":", 1)[0]: line.split(":", 1)[1].strip()
                      for line in status.splitlines() if ":" in line}
            uid = int(fields["Uid"].split()[1]); gid = int(fields["Gid"].split()[1])
            identities[name] = (uid, gid, pid)
            self.case.assertEqual(int(fields["CapEff"], 16), 0)
            self.case.assertEqual(fields["NoNewPrivs"], "1")
            executable = Path(f"/proc/{pid}/exe").resolve()
            role_interpreters[name] = str(executable)
            self.case.assertTrue(executable.name.startswith("python"))
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
            self.case.assertIn("-I", cmdline, "real role interpreter must be isolated")
            self.case.assertTrue("-m" in cmdline or any(value.startswith("/") and value.endswith(".py") for value in cmdline[1:]))
            declared_runtime = Path(role.get("runtime_root", self.slot("service_binding")["runtime_root"])).resolve()
            self.case.assertTrue(executable.is_relative_to(declared_runtime), "actual role executable escapes declared closure")
        self.case.assertEqual(identities["gateway"][0], 0)
        self.case.assertGreater(identities["core"][0], 0)
        self.case.assertGreater(identities["ordinary"][0], 0)
        self.case.assertNotEqual(identities["core"][0], identities["ordinary"][0])
        binding = self.slot("service_binding")
        protected = [binding["database_path"], self.slot("head_binding").get("binding", self.slot("head_binding"))["database_path"]]
        protected.extend(value for key, value in binding["host_private_paths"].items() if key != "lock_directory")
        # Public release/skill/rule code may be readable. Protect actual secret
        # capabilities, not arbitrary internal fields whose spelling has path.
        for pointer in self.raw["private_capability_selectors"]:
            value = _pointer(self.slot("live_binding"), pointer)
            self.case.assertIsInstance(value, str)
            protected.append(value)
        public_probe = self.work / "kernel_probe.py"
        public_probe.write_text(_KERNEL_PROBE)
        public_probe.chmod(0o644)
        probe_input = self.work / "kernel_input.json"
        probe_input.write_bytes(_canonical({"protected": protected, "socket": binding["socket_path"],
                                           "workspace": roles["ordinary"]["workspace"]}))
        probe_input.chmod(0o644)
        # Attach only a verifier ExecStartPost to each *actual generated* unit.
        # Same unit credentials/seccomp/mount policy apply; MainPID is still the
        # production role. No product test-mode or generic replacement daemon.
        original_units = {}
        probe_outputs = {}
        import shlex
        try:
            for name in ("core", "ordinary", "gateway"):
                role = roles[name]
                path = Path(role["unit_path"])
                original_units[name] = path.read_bytes()
                probe_outputs[name] = self.work / ("kernel-" + name + ".log")
                text = original_units[name].decode()
                role_python = str(Path(f"/proc/{identities[name][2]}/exe").resolve())
                line = "StandardOutput=append:" + str(probe_outputs[name]) + "\nExecStartPost=" + shlex.join([role_python, "-I", "-B", str(public_probe), name, str(probe_input)]) + "\n"
                self.case.assertIn("[Service]", text)
                text = text.replace("[Service]\n", "[Service]\n" + line, 1)
                path.write_text(text)
            self._command(["systemctl", "--user", "daemon-reload"])
            for name in ("core", "ordinary", "gateway"):
                role = roles[name]
                self._command(["systemctl", "--user", "restart", role["unit"]])
                invocation = self._command(["systemctl", "--user", "show", role["unit"],
                                            "--property=InvocationID", "--value"]).strip()
                self.case.assertRegex(invocation, r"^[0-9a-f]{32}$")
                self.case.assertTrue(probe_outputs[name].exists(), "actual unit output was not created")
                records = [json.loads(line.split("TICKET128_KERNEL ", 1)[1]) for line in probe_outputs[name].read_text().splitlines()
                           if "TICKET128_KERNEL " in line]
                self.case.assertTrue(records, "actual role-unit kernel probe did not execute")
                result = records[-1]
                self.case.assertEqual(result["role"], name)
                self.case.assertEqual(result["uid"], identities[name][0])
                if name in {"gateway", "ordinary"}:
                    self.case.assertTrue(result["file_errno"])
                    self.case.assertTrue(all(value in {errno.EACCES, errno.EPERM, errno.ENOENT}
                                             for value in result["file_errno"].values()), result)
                if name == "gateway":
                    self.case.assertEqual(result["coreport"], "accepted")
                if name == "ordinary":
                    self.case.assertNotEqual(result["coreport"], "accepted")
                if name == "core":
                    self.case.assertIn(result["inet_errno"], {errno.EAFNOSUPPORT, errno.EPERM, errno.EACCES})
                    self.case.assertEqual(result["credential_env_names"], [])
            # Actual ordinary Agent/tool subprocess, not only ExecStartPost.
            ordinary_output = Path(roles["ordinary"]["workspace"]) / "ticket128-tool-result.json"
            self.http.tool_command = shlex.join([role_interpreters["ordinary"], "-I", "-B", str(public_probe), "ordinary",
                                                 str(probe_input), str(ordinary_output)])
            before = len(self.http.sends)
            self.enqueue(self.raw["messages"]["ordinary_tool"], "ordinary-tool")
            self._wait(lambda: ordinary_output.exists(), seconds=30)
            tool_result = json.loads(ordinary_output.read_text())
            self.case.assertEqual(tool_result["uid"], identities["ordinary"][0])
            self.case.assertNotEqual(tool_result["pid"], identities["gateway"][2])
            self.case.assertTrue(tool_result["workspace_write"])
            self.case.assertTrue(all(value in {errno.EACCES, errno.EPERM, errno.ENOENT}
                                     for value in tool_result["file_errno"].values()))
            self.case.assertNotEqual(tool_result["coreport"], "accepted")
            self._wait(lambda: len(self.http.sends) > before)
            # Known root execution surfaces are exercised through actual native
            # ingress. No model/tool request may result from these commands.
            initial_posts = self.http.model_posts()
            initial_tool = ordinary_output.read_bytes()
            for index, body in enumerate(("/background TICKET128_LOCAL_FORBIDDEN", "/compress", "/update", "/ticket128-quickexec", "/ticket128-plugin")):
                before_reply = len(self.http.sends)
                cursor = "cursor:root-bypass-" + str(index)
                self.enqueue(body, "root-bypass-" + str(index), cursor=cursor)
                self._wait(lambda: cursor in self.http.cursors)
                self._wait(lambda: len(self.http.sends) > before_reply)
                refusal = "\n".join(_RawTLS.text(item) for item in self.http.sends[before_reply:])
                self.case.assertRegex(refusal, r"拒绝|禁用|不支持|不可用|relay|disabled|denied")
            self.case.assertFalse(self.quick_sentinel.exists(), "the real configured quick-exec must not run at Gateway UID")
            self.case.assertFalse(self.plugin_sentinel.exists(), "the real existing plugin command must not run at Gateway UID")
            self.case.assertEqual(self.http.model_posts(), initial_posts)
            self.case.assertEqual(ordinary_output.read_bytes(), initial_tool)
            # Stop the actual proxy worker: ordinary main turn must not become
            # a local Gateway model/Agent fallback.
            self._command(["systemctl", "--user", "stop", roles["ordinary"]["unit"]])
            self.enqueue(self.raw["messages"]["ordinary_greeting"], "proxy-down")
            time.sleep(0.2)
            self.case.assertEqual(self.http.model_posts(), initial_posts)
            self.case.assertEqual(self.initialized()["phase"], "uninitialized")
        finally:
            for name, content in original_units.items():
                Path(roles[name]["unit_path"]).write_bytes(content)
            self._command(["systemctl", "--user", "daemon-reload"])

    def _run_background(self, *, stop_nd12=True):
        self.http.default_answer = self._approved_candidate()
        self._prepare(run_id="acceptance-run:ticket128-native-" + uuid.uuid4().hex)
        context = copy.deepcopy(self.context)
        if stop_nd12:
            context["approval_refs"].pop("128-ND12", None)
        result = {}
        def run():
            try:
                result["report"] = _wire(health.AcceptanceRunContract().run(
                    self.host_manifest(), health.DefaultAcceptanceGateExecutor(), context))
            except BaseException as exc:
                result["error"] = exc
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, result, context

    def _wait_background_canary(self, thread, result, send_start):
        # A new run repeats the original local gates before G11. This is a
        # frontier observation budget, never extra time for a production gate.
        self._wait(lambda: len(self.http.sends) > send_start or not thread.is_alive(), seconds=1200)
        if not thread.is_alive():
            report = self._join_report(thread, result)
            self.case.fail("real gate frontier terminated before its canary: " + _canonical(report).decode())

    def _join_report(self, thread, result):
        thread.join(timeout=30)
        self.case.assertFalse(thread.is_alive(), "bounded real gate wait did not terminate")
        if "error" in result:
            raise result["error"]
        self.case.assertIn("report", result)
        report = result["report"]
        self.case._assert_fixture_only(report)
        return report

    def _actual_action(self, sends):
        text = "\n".join(_RawTLS.text(item) for item in sends)
        # Read the actual user instruction, not an internal parser/helper or a
        # test-specific command returned by a product test dispatcher.
        candidates = re.findall(r"`([^`\n]*\b[0-9a-f]{32,64}(?: 有用 清楚 可信)?)`", text)
        if not candidates:
            candidates = re.findall(r"(?m)^([^\n]{1,40} [0-9a-f]{32,64}(?: 有用 清楚 可信)?)$", text)
        self.case.assertEqual(len(set(candidates)), 1, "fixed connection/feedback instruction must be unambiguous")
        return candidates[0]

    def check_g11(self):
        self.run_until()
        before_sends, before_posts = len(self.http.sends), self.http.model_posts()
        thread, result, context = self._run_background()
        self._wait_background_canary(thread, result, before_sends)
        action = self._actual_action(self.http.sends[before_sends:])
        # An arbitrary ordinary message, extended body and wrong challenge may
        # not become the limited action or cause an ordinary Agent model call.
        count = self.http.model_posts()
        self.enqueue(action + " 我还要报告健康资料", "g11-extra-body")
        self.enqueue(re.sub(r"[0-9a-f]{32,64}", lambda match: "0" * len(match.group(0)), action), "g11-wrong-challenge")
        time.sleep(0.15)
        self.case.assertTrue(thread.is_alive())
        self.case.assertEqual(self.http.model_posts(), count)
        self.case.assertEqual(self.initialized()["phase"], "uninitialized")
        artifacts = Path(_pointer(self.prepare_output, self.raw["prepare_selectors"]["execution_artifacts_root"]))
        self.case.assertTrue(artifacts.is_dir())
        # Actual Core unavailability is an independent denial oracle. A
        # technical handler that bypasses the original accepted ordinary path
        # would consume this valid challenge and incorrectly finish/ACK.
        roles = {role["role"]: role for role in self.slot("roles")}
        receipt_before = self._tree(artifacts)
        self._command(["systemctl", "--user", "stop", roles["core"]["unit"]])
        native = self.enqueue(action, "g11-action", cursor="cursor:g11-action")
        self._wait(lambda: not self.http.batches)
        time.sleep(0.1)
        self.case.assertTrue(thread.is_alive())
        self.case.assertNotIn("cursor:g11-action", self.http.cursors)
        self.case.assertEqual((self.http.model_posts(), len(self.http.sends)), (before_posts + 1, before_sends + 1))
        self._command(["systemctl", "--user", "start", roles["core"]["unit"]])
        self._command(["systemctl", "--user", "restart", roles["gateway"]["unit"]])
        # Caps0/NNP Gateway really cannot persist into an owner-read-only
        # execution root. An ACK-before-receipt implementation is killed here.
        permissions = {path: stat.S_IMODE(path.stat().st_mode) for path in [artifacts, *artifacts.rglob("*")]
                       if path.is_file() or path.is_dir()}
        for path in sorted(permissions, key=lambda item: len(item.parts), reverse=True):
            path.chmod(0o500 if path.is_dir() else 0o400)
        try:
            with self.http.lock:
                self.http.batches.append({"ret": 0, "msgs": [copy.deepcopy(native)], "get_updates_buf": "cursor:g11-action"})
            self._wait(lambda: not self.http.batches)
            time.sleep(0.1)
            self.case.assertNotIn("cursor:g11-action", self.http.cursors)
            self.case.assertTrue(thread.is_alive(), "receipt write failure cannot claim gate completion")
        finally:
            for path, mode in permissions.items():
                path.chmod(mode)
        self._command(["systemctl", "--user", "restart", roles["gateway"]["unit"]])
        with self.http.lock:
            self.http.batches.append({"ret": 0, "msgs": [copy.deepcopy(native)], "get_updates_buf": "cursor:g11-action"})
        report = self._join_report(thread, result)
        entry = next(g for g in report["gates"] if g["gate_id"] == "119-G11")
        self.case.assertEqual(entry["result"], "passed")
        self.case.assertEqual(next(g for g in report["gates"] if g["gate_id"] == "128-ND12")["result"], "not-authorized")
        stages = entry["effect_stage_refs"]
        self.case.assertEqual(set(stages), set(_STAGES))
        self.case.assertIsNone(stages["unknown"])
        self.case.assertIsNone(stages["correction"])
        nonnull = [value for value in stages.values() if value is not None]
        self.case.assertEqual(len(nonnull), len(set(nonnull)))
        for stage in ("interface_accepted", "delivered", "read_or_action"):
            self.case.assertIsNotNone(stages[stage])
        self._wait(lambda: "cursor:g11-action" in self.http.cursors)
        self.case.assertNotEqual(self._tree(artifacts), receipt_before, "legal action must durably change the real execution artifact")
        totals = (self.http.model_posts(), len(self.http.sends))
        # Exact native event redelivery under a changed cursor must read the
        # same receipt and use the original poller. No new model/send/consent.
        replay = copy.deepcopy(native)
        self._command(["systemctl", "--user", "restart", roles["gateway"]["unit"]])
        with self.http.lock:
            self.http.batches.append({"ret": 0, "msgs": [replay], "get_updates_buf": "cursor:g11-redelivered"})
        self._wait(lambda: "cursor:g11-redelivered" in self.http.cursors)
        self.case.assertEqual((self.http.model_posts(), len(self.http.sends)), totals)
        self.case.assertEqual(self.initialized()["phase"], "uninitialized")
        # The exact technical replay cannot ACK a different unresolved health
        # source in the same raw batch. All health gates still apply.
        health_native = copy.deepcopy(native)
        health_native["message_id"] = "native128:g11-mixed-health"
        health_native["item_list"] = [{"type": 1, "text_item": {"text": self.raw["messages"]["health"]}}]
        with self.http.lock:
            self.http.batches.append({"ret": 0, "msgs": [copy.deepcopy(native), health_native],
                                      "get_updates_buf": "cursor:g11-mixed"})
        self._wait(lambda: not self.http.batches)
        time.sleep(0.1)
        self.case.assertNotIn("cursor:g11-mixed", self.http.cursors)
        self.case.assertEqual((self.http.model_posts(), len(self.http.sends)), totals)
        replay_context = copy.deepcopy(context)
        replay_context["existing_report"] = report
        self.case.assertEqual(_wire(health.AcceptanceRunContract().run(
            self.host_manifest(), health.DefaultAcceptanceGateExecutor(), replay_context)), report)
        self.case.assertEqual((self.http.model_posts(), len(self.http.sends)), totals)
        # A new real execution with a raw lost model terminal freezes without
        # allowing a changed run/key to repeat the same unconfirmed effect.
        self.http.model_mode = "unknown"
        self._prepare(run_id="acceptance-run:ticket128-g11-unknown-" + uuid.uuid4().hex)
        unknown_context = copy.deepcopy(self.context)
        unknown_context["approval_refs"].pop("128-ND12", None)
        unknown = _wire(health.AcceptanceRunContract().run(self.host_manifest(), health.DefaultAcceptanceGateExecutor(), unknown_context))
        unknown_entry = next(g for g in unknown["gates"] if g["gate_id"] == "119-G11")
        self.case.assertEqual(unknown_entry["result"], "cannot-confirm")
        after_unknown = (self.http.model_posts(), len(self.http.sends))
        self._prepare(run_id="acceptance-run:ticket128-g11-rekey-" + uuid.uuid4().hex)
        rekeyed = _wire(health.AcceptanceRunContract().run(self.host_manifest(), health.DefaultAcceptanceGateExecutor(), self.context))
        self.case.assertNotEqual(rekeyed["run_verdict"], "passed")
        self.case.assertEqual((self.http.model_posts(), len(self.http.sends)), after_unknown)
        self.case.assertEqual(totals[0], before_posts + 1, "one G11 model POST only")
        self.case.assertEqual(totals[1], before_sends + 1, "one G11 Weixin canary only")

    def check_nd12(self):
        self.run_until()
        before = len(self.http.sends)
        thread, result, context = self._run_background(stop_nd12=False)
        self._wait_background_canary(thread, result, before)
        g11_action = self._actual_action(self.http.sends[before:])
        self.enqueue(g11_action, "nd12-g11-action", cursor="cursor:nd12-g11-action")
        self._wait(lambda: "cursor:nd12-g11-action" in self.http.cursors)
        # The technical G11 action itself must never enable or count as the
        # owner's feedback. Native initialization is independently necessary.
        self.case.assertEqual(self.initialized()["phase"], "uninitialized")
        self.initialize()
        self.case.assertTrue(thread.is_alive(), "enabled/model/accepted is not owner sequence acceptance")
        # Observe the feedback boundary BEFORE the sequence. A fast legal
        # handler may send immediately after its last actual business fact.
        mark = len(self.http.sends)
        def turn(body, suffix, intake=None, *, answer=False, ack=True):
            start = len(self.http.sends)
            with self.http.lock:
                if intake is not None:
                    self.http.candidates.append(("intake", intake))
                    if answer:
                        self.http.candidates.append(("answer", self.http.default_answer))
            cursor = "cursor:nd12-" + suffix
            self.enqueue(body, "nd12-" + suffix, cursor=cursor)
            self._wait(lambda: len(self.http.sends) > start)
            if ack:
                self._wait(lambda: cursor in self.http.cursors)
            return "\n".join(_RawTLS.text(item) for item in self.http.sends[start:])
        # A genuine source-bound record, not a schema-shaped empty answer.
        body = "我昨晚睡了六小时"
        record = {"operation": "record", "facts": [{"start": 0, "end": len(body), "quote": body,
            "topic_ref": "physical-function-and-experience/sleep", "time_start": 1, "time_end": 3}], "question": None}
        turn(body, "record", record)
        facts = self._core_public("facts")
        self.case.assertGreater(facts["evidence_cards"], 0)
        self.case.assertGreater(facts["portrait_topics"], 0)
        # Questions use actual release-owned governance claims/templates.
        question = "健康管家如何使用我的资料？"
        intake = {"operation": "question", "facts": [], "question": {"start": 0, "end": len(question), "quote": question}}
        turn(question, "governance-answer", intake, answer=True)
        before_diagnosis = self.http.model_posts()
        refusal = turn("请计算我的BMI并诊断我是否肥胖", "diagnosis-refusal")
        self.case.assertRegex(refusal, r"未启用|不.*诊断|范围|不可用")
        self.case.assertEqual(self.http.model_posts(), before_diagnosis)
        # A real failed model response followed by a successful new source.
        # No unresolved unknown is invented merely to fill a checklist.
        turn("我今天精神很好", "known-failed", {"operation": "invalid", "facts": [], "question": None}, ack=False)
        failed = self._core_public("facts")
        self.case.assertGreater(failed["failed_model_effects"], 0)
        self.case.assertEqual(failed["unknown_model_effects"], 0)
        body2 = "我今天步行了十分钟"
        recovery = {"operation": "record", "facts": [{"start": 0, "end": len(body2), "quote": body2,
            "topic_ref": None, "time_start": 1, "time_end": 3}], "question": None}
        turn(body2, "recovered-record", recovery)
        self.case.assertGreater(self._core_public("facts")["evidence_cards"], facts["evidence_cards"])
        # Only the actual startup may drive scheduled work. No verifier wake
        # RPC or replacement bridge may stand in for the production lifecycle.
        from zoneinfo import ZoneInfo
        due = (datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(minutes=1, seconds=15)).replace(second=0, microsecond=0)
        task_text = turn("/health-task-once " + due.strftime("%Y-%m-%d %H:%M") + " 离线单次喝水提醒", "due-task")
        task_id = re.search(r"/health-task-cancel (task:[^\s。`]+)", task_text)
        self.case.assertIsNotNone(task_id, "task_id must come from the actual creation reply")
        self.case.assertLess(datetime.now(timezone.utc), due.astimezone(timezone.utc), "task creation must finish before its real due time")
        send_start = len(self.http.sends)
        def reminder_count():
            with self.http.lock:
                return sum("一次提醒：离线单次喝水提醒" in _RawTLS.text(v) for v in self.http.sends[send_start:])
        def naturally_current():
            count = reminder_count()
            self.case.assertLessEqual(count, 1, "natural scheduling must not resend the single reminder")
            if count == 0:
                return False
            self.case.assertGreaterEqual(datetime.now(timezone.utc), due.astimezone(timezone.utc))
            current = self._core_public("facts")
            return (task_id.group(1) in current["solved_tasks"]
                    and datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat() in current["review_days"])
        # Real-time observation budgets do not prescribe a timer implementation
        # or cadence. Empty native polls must suffice, with no extra input.
        until_due = max(0.0, (due.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())
        self._wait(naturally_current, seconds=until_due + 90)
        quiet_until = time.monotonic() + 65
        while time.monotonic() < quiet_until:
            self.case.assertEqual(reminder_count(), 1)
            time.sleep(min(0.2, max(0.0, quiet_until - time.monotonic())))
        self.case.assertEqual(reminder_count(), 1)
        cancelled = turn("/health-task-once 明天 09:00 离线待取消提醒", "cancel-task-create")
        cancel_id = re.search(r"/health-task-cancel (task:[^\s。`]+)", cancelled)
        self.case.assertIsNotNone(cancel_id)
        turn("/health-task-cancel " + cancel_id.group(1), "cancel-task")
        # These two independent controls must preserve one another.
        for suffix, command, paused, stopped in (
            ("pause", "/health-pause", True, False),
            ("stop", "/health-recording-stop", True, True),
            ("resume-proactive", "/health-resume", False, True),
            ("resume-recording", "/health-recording-resume", False, False)):
            turn(command, suffix)
            current = self._core_public("facts")
            self.case.assertEqual((current["proactive_paused"], current["recording_stopped"]), (paused, stopped))
        view = turn("/health-view 昨晚", "view")
        objects = json.JSONDecoder().raw_decode(view[view.index("["):])[0]
        self.case.assertTrue(objects)
        target = next(item["object_ref"] for item in objects if "昨晚" in _canonical(item).decode())
        correction_count = self._core_public("facts")["corrections"]
        turn("/health-correct " + target + " 我昨晚睡了七小时", "correct")
        self.case.assertGreater(self._core_public("facts")["corrections"], correction_count)
        turn("/health-export", "export")
        self._wait(lambda: self.http.ciphertext is not None and self.http.media_ticket is not None)
        from gateway.platforms.weixin import _aes128_ecb_decrypt
        from partner_health_steward.rights import ManagedExport
        plaintext = _aes128_ecb_decrypt(self.http.ciphertext, bytes.fromhex(self.http.media_ticket["aeskey"]))
        exported = json.loads(plaintext)
        self.case.assertEqual(ManagedExport.from_wire(exported).to_wire(), exported)
        self.case.assertIn("我昨晚睡了七小时", plaintext.decode())
        self.case.assertTrue(any(item.get("type") == 4 for send in self.http.sends[mark:]
            for item in send.get("msg", {}).get("item_list", [])), "actual export must be a file attachment")
        # The actual Core stores the authenticated export in its existing
        # encrypted SQLite store and streams that blob to the attachment above.
        # It does not create an external replica file or a purge receipt.
        self.case.assertEqual(list(Path(self.slot("service_binding")["managed_replica_root"]).iterdir()), [])
        self.case.assertTrue(self._core_public("replicas")["configured"])
        turn("/health-help", "minimum-help")
        resources = self._core_public("resources")
        danger = next((item["input"] for item in resources["safety_rules"] if item["branch"] == "danger-escalation"), None)
        self.case.assertIsNotNone(danger, "release must include an actually reviewed fixed nonmedical help rule")
        before_safety = self.http.model_posts()
        turn(danger, "fixed-safety-rule")
        self.case.assertEqual(self.http.model_posts(), before_safety)
        final_facts = self._core_public("facts")
        self.case.assertIn(datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(), final_facts["review_days"])
        self.case.assertIn(cancel_id.group(1), final_facts["cancelled_tasks"])
        self.case.assertIn(task_id.group(1), final_facts["solved_tasks"])
        self.case.assertTrue(final_facts["safety_results"])
        self.case.assertTrue(all(value == "unavailable" for value in final_facts["contact_alert_statuses"]))
        self.case.assertTrue(all(send.get("msg", {}).get("to_user_id") == self.raw["admission_policy"]["owner_sender_id"]
                                 for send in self.http.sends[mark:]), "unconfigured contact has zero sends")
        feedback_sends = self._wait(lambda: [item for item in self.http.sends[mark:]
                                  if "验收反馈" in _RawTLS.text(item)], seconds=30)
        feedback = self._actual_action(feedback_sends)
        self.case.assertRegex(feedback, r"^验收反馈 [0-9a-f]{32,64} 有用 清楚 可信$")
        self.case.assertNotEqual(feedback, g11_action)
        before_feedback = self.http.model_posts()
        before_feedback_head = self._authority_snapshot()
        self.enqueue(g11_action, "nd12-borrowed-g11")
        self.enqueue(re.sub(r"[0-9a-f]{32,64}", lambda match: "0" * len(match.group(0)), feedback), "nd12-wrong-challenge")
        time.sleep(0.1)
        self.case.assertTrue(thread.is_alive())
        self.case.assertEqual(self.http.model_posts(), before_feedback)
        self.case.assertEqual(self._authority_snapshot(), before_feedback_head, "technical feedback must not mutate health authority")
        self.enqueue(feedback, "nd12-feedback", cursor="cursor:nd12-feedback")
        report = self._join_report(thread, result)
        final = next(g for g in report["gates"] if g["gate_id"] == "128-ND12")
        self.case.assertEqual(final["result"], "passed")
        self.case.assertNotIn("119-G12", [g["gate_id"] for g in report["gates"]])
        self.case.assertEqual(report["diagnostic_scope_phase"], "staged")
        self.case.assertNotEqual(report["product_acceptance"], "passed")
        self.case.assertNotEqual(report["active"], "active")
        self.case.assertIn("non-diagnostic-owner-usable", _canonical(report).decode())
        self.case.assertEqual(self.http.model_posts(), before_feedback)
        self._wait(lambda: "cursor:nd12-feedback" in self.http.cursors)
        self.case.assertEqual(self._authority_snapshot(), before_feedback_head, "legal technical feedback must not mutate health authority")
        # Every event is an explicitly synthetic raw transport input. Even this
        # successful chain cannot claim an actual human/production acceptance.
        self.case._assert_fixture_only(report)


_CORE_PUBLIC_READ = r'''
import json,sys
from dataclasses import asdict
import partner_health_steward as health
from partner_health_steward.host_current_head import HostHeadBinding,HostSQLiteCurrentHead
from partner_health_steward.production_core_service import FilesystemManagedReplicaAdapter
value=json.load(sys.stdin)
operation=sys.argv[1]
if operation=="loader":
    from partner_health_steward.live_health import LiveHealthRuntime
    runtime=health.load_default_live_runtime(value["release"],value["live"])
    assert type(runtime) is LiveHealthRuntime
    runtime.validate_release(value["release"],value["published"])
    dependencies=runtime.core_dependencies()
    assert dependencies["safety_diagnostic_assets"]["diagnostic_scope_bundle"] is None
    print(json.dumps({"runtime_type":type(runtime).__name__,"knowledge_count":len(dependencies["knowledge_releases"]),"diagnostic_scope_absent":True}))
elif operation=="resources":
    runtime=health.load_default_live_runtime(value["release"],value["live"])
    dependencies=runtime.core_dependencies()
    print(json.dumps({"claims":[item.to_wire() for item in dependencies["approved_claims"]],"templates":[item.to_wire() for item in dependencies["approved_templates"]],"health_init_asset":dependencies["health_init_asset"].to_storage(),"safety_rules":dependencies["safety_diagnostic_assets"]["safety_rule_bundle"]["rules"]},sort_keys=True))
elif operation=="facts":
    from partner_health_steward.host_authority import HostPrivateFacilityPaths,HostPrivateKeyProvider
    from partner_health_steward.storage import EncryptedStateStore
    binding=value["service"]
    keys=HostPrivateKeyProvider(HostPrivateFacilityPaths(**binding["host_private_paths"]),binding["installation_id"])
    store=EncryptedStateStore("file:"+binding["database_path"]+"?mode=ro",keys)
    try:
        state=store.daily_state();settings=store.owner_settings();reviews=store.daily_review_ledger();tasks=store.task_runtime()
        receipts=store.native_cursor_receipts()
        effects=[store.model_effect_for_source(r.envelope.causal_id,stage) for r in receipts for stage in ("intake","answer")]
        reports=[getattr(e.payload,"model_report",None) for e in effects if e is not None]
        safety=[r.result for r in store.health_command_receipts() if r.result.get("_ticket116_action")=="safety.evaluate"]
        print(json.dumps({"evidence_cards":len(state.evidence_cards),"portrait_topics":len(state.portrait_topics),
          "corrections":len(state.owner_correction_revisions),"proactive_paused":settings.proactive_support_paused,
          "recording_stopped":settings.recording_stopped,"cancelled_tasks":list(settings.cancelled_task_refs),
          "solved_tasks":[] if tasks is None else [t.task_id for t in tasks.tasks if t.primary_label=="solved"],
          "review_days":[] if reviews is None else [r.key.local_date for r in reviews.completed],
          "failed_model_effects":sum(r is not None and r.terminal_proven and r.candidate_digest is None and r.reason_code is not None for r in reports),
          "unknown_model_effects":sum(e is not None and e.state=="unknown" for e in effects),
          "safety_results":[r["branch"] for r in safety],
          "contact_alert_statuses":["unavailable" if r.get("contact_alert") is None else "available" for r in safety],
          "sources":[{"message_id":r.envelope.message_id,"causal_id":r.envelope.causal_id,
                      "native_cursor_state":r.native_cursor_state,"managed_cursor_state":r.managed_cursor_state,
                      "body_absent":r.envelope.body is None} for r in receipts]},sort_keys=True))
    finally:store.close();keys.close()
elif operation=="head":
    binding=value["head"].get("binding",value["head"])
    head=HostSQLiteCurrentHead(HostHeadBinding(**binding))
    try:print(json.dumps(asdict(head.read().head),sort_keys=True))
    finally:head.close()
elif operation=="replicas":
    binding=value["service"]
    adapter=FilesystemManagedReplicaAdapter(binding["managed_replica_root"],binding["installation_id"],binding["managed_replica_bindings"],binding["lifecycle_release"]["unbound_real_providers"])
    print(json.dumps(adapter.enumerate({"installation_id":binding["installation_id"]}),sort_keys=True))
else:raise AssertionError("unknown verifier public read")
'''

_KERNEL_PROBE = r'''
import errno,json,os,re,socket,struct,sys,uuid
role=sys.argv[1]
data=json.load(open(sys.argv[2]))
result={"role":role,"uid":os.geteuid(),"gid":os.getegid(),"pid":os.getpid(),"file_errno":{}}
for path in data["protected"]:
    try:
        handle=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        os.close(handle)
        result["file_errno"][path]=0
    except OSError as error:
        result["file_errno"][path]=error.errno
try:
    value=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    value.close()
    result["inet_errno"]=0
except OSError as error:
    result["inet_errno"]=error.errno
result["credential_env_names"]=sorted(key for key in os.environ if re.search(r"JOJO|WEIXIN|API.?KEY|TOKEN|SECRET",key,re.I))
result["coreport"]="denied"
try:
    identity="kernel-probe:"+uuid.uuid4().hex
    wire={"protocol_version":1,"kind":"command","request_id":identity,"payload":{"operation":"health-runtime-probe"}}
    encoded=json.dumps(wire,separators=(",",":"),sort_keys=True).encode()
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(3);client.connect(data["socket"]);client.sendall(struct.pack(">I",len(encoded))+encoded)
        header=client.recv(4)
        if len(header)==4:
            count=struct.unpack(">I",header)[0];raw=b""
            while len(raw)<count:
                part=client.recv(count-len(raw))
                if not part:break
                raw+=part
            reply=json.loads(raw)
            if reply.get("status")=="accepted":result["coreport"]="accepted"
except (OSError,ValueError):pass
result["workspace_write"]=False
if role=="ordinary":
    try:
        path=os.path.join(data["workspace"],"ticket128-child-write")
        handle=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.write(handle,b"synthetic tool write");os.close(handle)
        os.unlink(path);result["workspace_write"]=True
    except OSError:pass
if len(sys.argv)>3:
    with open(sys.argv[3],"w") as handle:json.dump(result,handle,sort_keys=True)
print("TICKET128_KERNEL "+json.dumps(result,sort_keys=True),flush=True)
'''


if __name__ == "__main__":
    unittest.main()

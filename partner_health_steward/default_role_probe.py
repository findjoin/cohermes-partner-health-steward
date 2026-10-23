"""Bounded, temporary observations inside the three actual default units.

These observations join the original G10 execution artifact. They contain no
health bodies, configuration values, credential values or business approvals.
The child command is fixed; this is not a general command or target interface.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import socket
import stat
import struct
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

_MODULE = "partner_health_steward.default_role_probe"
_HOME = Path("/root/.hermes")
_STATE = Path("/var/lib/cohermes-default-core")
_SOCKET = Path("/run/cohermes-default/core.sock")
_ORDINARY = Path("/var/lib/cohermes-default-ordinary")
_UNITS = {"core": "cohermes-default-core.service", "ordinary": "cohermes-default-ordinary.service", "gateway": "hermes-gateway.service"}
_UNIT_ROOT = Path("/root/.config/systemd/user")
_CAPS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _status(pid):
    return {line.split(":", 1)[0]: line.split(":", 1)[1].strip()
            for line in Path(f"/proc/{pid}/status").read_text().splitlines() if ":" in line}


def _identity(pid):
    fields = _status(pid)
    return {"uid": int(fields["Uid"].split()[1]), "gid": int(fields["Gid"].split()[1]),
            "no_new_privs": fields["NoNewPrivs"] == "1",
            "capabilities_empty": all(int(fields[key], 16) == 0 for key in _CAPS),
            "cgroup": Path(f"/proc/{pid}/cgroup").read_text()}


def _parent_descriptor(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or not path.name:
        raise ValueError("invalid role observation path")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor); descriptor = child
        return descriptor, path.name
    except BaseException:
        os.close(descriptor)
        raise


def _create(path, value, mode):
    parent, name = _parent_descriptor(path)
    try:
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), mode)
            output.write(_canonical(value)); output.flush(); os.fsync(output.fileno())
    finally:
        os.close(parent)


def _read(path, *, uid, mode):
    parent, name = _parent_descriptor(path)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(descriptor, "rb") as source:
        details = os.fstat(source.fileno())
        if (not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_uid != uid
                or stat.S_IMODE(details.st_mode) != mode or not 0 < details.st_size <= 65536):
            raise ValueError("unsafe role observation file")
        data = source.read(65537)
        if len(data) > 65536: raise ValueError("role observation exceeds bound")
        return json.loads(data)


def _unlink(path):
    parent, name = _parent_descriptor(path)
    try:
        os.unlink(name, dir_fd=parent)
    finally:
        os.close(parent)


def _denied_read(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        return error.errno in {errno.EACCES, errno.EPERM}
    else:
        os.close(descriptor)
        return False


def _rpc_available():
    request = {"protocol_version": 1, "kind": "managed-read", "request_id": "role-probe:" + uuid.uuid4().hex,
               "payload": {"interface": "health-entry-v1", "projection": "health-entry-initialization", "payload": {}}}
    body = _canonical(request)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3); client.connect(str(_SOCKET))
        client.sendall(struct.pack(">I", len(body)) + body); client.shutdown(socket.SHUT_WR)
        def exact(length):
            result = b""
            while len(result) < length:
                chunk = client.recv(length - len(result))
                if not chunk: raise ValueError("role CorePort reply is incomplete")
                result += chunk
            return result
        length = struct.unpack(">I", exact(4))[0]
        if length > 65536: raise ValueError("role CorePort reply is oversized")
        reply = json.loads(exact(length))
    return reply.get("status") == "accepted" and reply.get("request_id") == request["request_id"]


def _kernel(role, spec):
    identity = _identity(os.getpid())
    expected = spec["roles"]["ordinary" if role == "ordinary-child" else role]
    if (identity["uid"] != expected["uid"] or identity["gid"] != expected["gid"]
            or not identity["no_new_privs"] or not identity["capabilities_empty"]):
        raise ValueError("actual role privilege boundary differs")
    try:
        inet = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError as error:
        inet_denied = error.errno in {errno.EACCES, errno.EPERM, errno.EAFNOSUPPORT}
    else:
        inet.close(); inet_denied = False
    facts = {"role": role, "pid": os.getpid(), **identity, "nonce": spec["nonce"],
             "invocation_id": os.environ.get("INVOCATION_ID"), "observed_monotonic_ns": time.monotonic_ns(),
             "interpreter_matches": Path(sys.executable).resolve() == Path(spec["interpreter"]).resolve(),
             "af_inet_kernel_denied": inet_denied}
    if not facts["interpreter_matches"]: raise ValueError("role interpreter differs")
    protected = [_STATE / "health.sqlite", _STATE / "current-head.sqlite", _STATE / "capabilities/data-key",
                 _STATE / "capabilities/writer-master", _STATE / "capabilities/execution-master",
                 _STATE / "capabilities/init-attestor", _STATE / "capabilities/daily-attestor",
                 _STATE / "capabilities/status-hmac"]
    if role in {"gateway", "ordinary", "ordinary-child"}:
        facts["all_health_files_unreadable"] = all(_denied_read(path) for path in protected)
        if not facts["all_health_files_unreadable"]: raise ValueError("role can read health authority")
    if role == "core":
        # Observe the real service environment as well as this same-unit
        # ExecStartPost, without retaining any environment value.
        facts["provider_or_channel_environment_absent"] = not any(
            re.search(r"API_KEY|WEIXIN|HERMES|AWS_|SSH_AUTH|GATEWAY_PROXY|HMAC", key, re.I) for key in os.environ)
        if not inet_denied or not facts["provider_or_channel_environment_absent"]:
            raise ValueError("Core network or environment boundary differs")
    if role in {"ordinary", "ordinary-child"}:
        facts["default_profile_unreadable"] = _denied_read(_HOME / ".env")
        facts["health_group_absent"] = spec["roles"]["core"]["gid"] not in {os.getgid(), *os.getgroups()}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            try: client.connect(str(_SOCKET))
            except OSError as error: denied = error.errno in {errno.EACCES, errno.EPERM}
            else: denied = False
        facts["core_socket_permission_denied"] = denied
        if not all(facts[key] for key in ("default_profile_unreadable", "health_group_absent", "core_socket_permission_denied")):
            raise ValueError("ordinary authority isolation differs")
        workspace = _ORDINARY / "workspace"
        if Path.cwd() != workspace: raise ValueError("ordinary tool workspace differs")
        facts["workspace_matches"] = True
    if role == "gateway":
        facts["coreport_available"] = _rpc_available()
        if not facts["coreport_available"]: raise ValueError("Gateway CorePort is unavailable")
    return facts


def _deny_external_probe_effects():
    # This audit hook protects this temporary probe from accidental external
    # effects during high-level imports. The AF_INET result above is obtained
    # first from the actual unit's kernel policy, independently of this hook.
    def audit(event, args):
        if event == "socket.getaddrinfo":
            raise PermissionError(errno.EPERM, "role probe external network is forbidden")
        if event in {"socket.connect", "socket.bind"} and args and getattr(args[0], "family", None) in {socket.AF_INET, socket.AF_INET6}:
            raise PermissionError(errno.EPERM, "role probe external network is forbidden")
    sys.addaudithook(audit)


def _gateway_guards(spec):
    from .default_runtime import _verify_sources, _coarse_classifier
    _verify_sources(spec["source_binding"])
    _deny_external_probe_effects()
    from run_agent import AIAgent
    from gateway.run import GatewayRunner
    try: AIAgent()
    except RuntimeError as error:
        local_agent_denied = str(error) == "relay-only Gateway cannot construct AIAgent"
    else: local_agent_denied = False
    if not local_agent_denied: raise ValueError("Gateway can construct a local Agent")
    async def commands():
        for text in ("/background", "/compress", "/update", "/role-probe-exec", "/role-probe-plugin"):
            result = await GatewayRunner._handle_message(object(), SimpleNamespace(text=text, internal=False))
            if result != "Relay commands disabled.": return False
        return await GatewayRunner._handle_message(object(), SimpleNamespace(text="role probe", internal=True)) == "Relay commands disabled."
    slash_denied = asyncio.run(commands())
    saved = os.environ.pop("GATEWAY_PROXY_URL", None)
    try:
        try: GatewayRunner._get_proxy_url(object())
        except RuntimeError as error: proxy_missing_denied = str(error) == "relay-only Gateway proxy is unavailable"
        else: proxy_missing_denied = False
        os.environ["GATEWAY_PROXY_URL"] = "http://127.0.0.1:8642"
        proxy_forced = GatewayRunner._get_proxy_url(object()) == "http://127.0.0.1:8642"
    finally:
        if saved is None: os.environ.pop("GATEWAY_PROXY_URL", None)
        else: os.environ["GATEWAY_PROXY_URL"] = saved
    resource = json.loads((Path(spec["source_binding"]["release_root"]) / "assets/non-diagnostic/runtime-resources.json").read_bytes())
    health_retained = _coarse_classifier(resource["coarse_rules"])("健康资料", "health-init") == "health"
    if not all((slash_denied, proxy_missing_denied, proxy_forced, health_retained)):
        raise ValueError("Gateway relay boundary differs")
    return {"local_agent_constructor_denied": local_agent_denied, "slash_and_internal_handlers_denied": slash_denied,
            "proxy_missing_rejected": proxy_missing_denied, "proxy_url_forced": proxy_forced,
            "health_content_classified_health": health_retained}


def _ordinary_tool(spec):
    from .default_runtime import _verify_sources
    _verify_sources(spec["source_binding"])
    _deny_external_probe_effects()
    from tools.terminal_tool import terminal_tool, cleanup_vm, _resolve_container_task_id, _get_env_config
    if _get_env_config()["env_type"] != "local":
        raise ValueError("ordinary terminal backend differs")
    task_id = "cohermes-role-probe-" + spec["nonce"]
    # The pinned tool may map this label to its process-local default. Clean
    # that actual owned environment so its atexit hook cannot run the global
    # orphan-scratch reaper. No other tool runs in this temporary process.
    environment_id = _resolve_container_task_id(task_id)
    argv = [sys.executable, "-I", "-B", "-m", _MODULE, "--role", "ordinary-child", "--input", spec["input_path"]]
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = json.loads(terminal_tool(command=shlex.join(argv), timeout=20, workdir=str(_ORDINARY / "workspace"),
                                              task_id=task_id, force=True))
        if result.get("exit_code") != 0: raise ValueError("actual ordinary terminal child failed")
        child = _read(spec["child_output"], uid=os.geteuid(), mode=0o600)
        if (child["nonce"] != spec["nonce"] or child["role"] != "ordinary-child" or child["cgroup"] != Path("/proc/self/cgroup").read_text()
                or child["observed_monotonic_ns"] < spec["created_monotonic_ns"]):
            raise ValueError("ordinary terminal child provenance differs")
        return child
    finally:
        cleanup_vm(environment_id)


def _probe_main(role, input_path):
    spec = _read(input_path, uid=0, mode=0o644)
    if (spec.get("contract") != "ticket128-role-probe-input-v1" or input_path != spec.get("input_path")
            or not re.fullmatch(r"[0-9a-f]{32}", spec.get("nonce", "")) or role not in {*_UNITS, "ordinary-child"}):
        raise ValueError("invalid fixed role probe input")
    expected_input = Path(spec["source_binding"]["runtime_root"]).parent / ("role-probe-" + spec["nonce"] + ".json")
    if Path(input_path) != expected_input: raise ValueError("role probe input locator differs")
    output = Path(spec["child_output"] if role == "ordinary-child" else spec["outputs"][role])
    parent = _ORDINARY / "workspace" if role in {"ordinary", "ordinary-child"} else (_STATE if role == "core" else _HOME)
    if output.parent != parent or output.name != "role-probe-" + spec["nonce"] + ("-child.json" if role == "ordinary-child" else ".json"):
        raise ValueError("role probe output locator differs")
    facts = _kernel(role, spec)
    if role == "gateway": facts.update(_gateway_guards(spec))
    elif role == "ordinary": facts["terminal_child"] = _ordinary_tool(spec)
    facts["passed"] = True
    _create(output, facts, 0o600)


def _manager_environment():
    return dict(os.environ, XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR", "/run/user/0"),
                DBUS_SESSION_BUS_ADDRESS=os.environ.get("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/0/bus"))


def _manager(*arguments):
    return subprocess.run(["systemctl", "--user", *arguments], env=_manager_environment(),
                          capture_output=True, text=True, timeout=60)


def run_default_role_probe(plan):
    """Observe fixed actual unit policies, then remove all temporary probes."""
    if os.geteuid() != 0: raise ValueError("default role observations require the root operator")
    role_list = plan["roles"]
    roles = {item["role"]: item for item in role_list}
    if set(roles) != set(_UNITS) or len(role_list) != 3:
        raise ValueError("default role set differs")
    for name, role in roles.items():
        if role["unit"] != _UNITS[name] or Path(role["unit_path"]) != _UNIT_ROOT / _UNITS[name]:
            raise ValueError("default role target differs")
        if (name == "gateway" and role["uid"] != 0) or (name != "gateway" and role["uid"] == 0):
            raise ValueError("default role identity differs")
    gateway = plan["gateway_config"]
    source = {key: gateway[key] for key in ("release_root", "runtime_root", "shadow_root", "source_manifest_path")}
    runtime = Path(source["runtime_root"])
    program = runtime.parent
    if program.parent != Path("/opt/cohermes-default/program") or program.name != plan["core_binding"]["release_digest"].removeprefix("sha256:"):
        raise ValueError("default observation program differs")
    nonce = uuid.uuid4().hex
    input_path = program / ("role-probe-" + nonce + ".json")
    outputs = {name: str(parent / ("role-probe-" + nonce + ".json")) for name, parent in
               (("core", _STATE), ("ordinary", _ORDINARY / "workspace"), ("gateway", _HOME))}
    spec = {"contract": "ticket128-role-probe-input-v1", "nonce": nonce, "created_monotonic_ns": time.monotonic_ns(),
            "input_path": str(input_path), "outputs": outputs, "child_output": str(_ORDINARY / "workspace" / ("role-probe-" + nonce + "-child.json")),
            "interpreter": str(runtime / "bin/python3"), "source_binding": source,
            "roles": {name: {"uid": role["uid"], "gid": role["gid"]} for name, role in roles.items()}}
    paths = [input_path, *(Path(value) for value in outputs.values()), Path(spec["child_output"])]
    dropins = []; created_directories = []; observed = {}; failure = None; cleanup_ok = True; current_role = None
    try:
        _create(input_path, spec, 0o644)
        for name in ("core", "ordinary", "gateway"):
            directory = Path(roles[name]["unit_path"] + ".d")
            if directory.is_symlink(): raise ValueError("default role drop-in is unsafe")
            if not directory.exists():
                directory.mkdir(mode=0o755); created_directories.append(directory)
            if directory.stat().st_uid != 0 or stat.S_IMODE(directory.stat().st_mode) & 0o022:
                raise ValueError("default role drop-in permissions differ")
            path = directory / ("95-cohermes-probe-" + nonce + ".conf")
            command = ["/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "LANG=C.UTF-8", "PYTHONDONTWRITEBYTECODE=1",
                       "INVOCATION_ID=${INVOCATION_ID}"]
            if name == "gateway": command += ["HOME=/root", "HERMES_HOME=" + str(_HOME), "COHERMES_RELAY_ONLY=1"]
            elif name == "ordinary": command += ["HOME=" + str(_ORDINARY), "HERMES_HOME=" + str(_ORDINARY)]
            command += [spec["interpreter"], "-I", "-B", "-m", _MODULE, "--role", name, "--input", str(input_path)]
            # systemd performs the single intended INVOCATION_ID expansion;
            # all other arguments are fixed trusted paths or opaque nonce.
            line = "[Service]\nExecStartPost=" + shlex.join(command) + "\n"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(descriptor, "w") as output:
                os.fchmod(output.fileno(), 0o644); output.write(line); output.flush(); os.fsync(output.fileno())
            dropins.append(path)
        if _manager("daemon-reload").returncode != 0: raise ValueError("role observation reload failed")
        for name in ("core", "ordinary", "gateway"):
            current_role = name
            role = roles[name]
            if _manager("restart", role["unit"]).returncode != 0: raise ValueError("actual role observation failed")
            reply = _manager("show", role["unit"], "--property=MainPID,ControlPID,InvocationID,ActiveState")
            details = dict(line.split("=", 1) for line in reply.stdout.splitlines() if "=" in line)
            if reply.returncode != 0 or details.get("ActiveState") != "active" or details.get("ControlPID") != "0":
                raise ValueError("actual role startup is not complete")
            actual = _identity(int(details["MainPID"]))
            proof = _read(outputs[name], uid=role["uid"], mode=0o600)
            if (proof.get("nonce") != nonce or proof.get("passed") is not True or proof.get("role") != name
                    or proof.get("observed_monotonic_ns", 0) < spec["created_monotonic_ns"]
                    or proof.get("invocation_id") != details.get("InvocationID")
                    or any(actual[key] != proof.get(key) for key in ("uid", "gid", "cgroup"))
                    or not actual["no_new_privs"] or not actual["capabilities_empty"]):
                raise ValueError("actual role observation binding differs")
            if name == "core":
                environment_keys = [entry.split(b"=", 1)[0].decode("ascii", "ignore") for entry in Path(f"/proc/{details['MainPID']}/environ").read_bytes().split(b"\0") if entry]
                proof["main_initial_credential_environment_absent"] = not any(re.search(r"API_KEY|WEIXIN|HERMES|AWS_|SSH_AUTH|GATEWAY_PROXY|HMAC", key, re.I) for key in environment_keys)
                if not proof["main_initial_credential_environment_absent"]: raise ValueError("actual Core environment differs")
                deadline = time.monotonic() + 20
                while True:
                    try:
                        if _rpc_available(): break
                    except (OSError, ValueError): pass
                    if time.monotonic() >= deadline: raise ValueError("actual Core readiness is unconfirmed")
                    time.sleep(.1)
            if name == "ordinary":
                environment_keys = [entry.split(b"=", 1)[0].decode("ascii", "ignore") for entry in Path(f"/proc/{details['MainPID']}/environ").read_bytes().split(b"\0") if entry]
                proof["main_initial_forbidden_environment_absent"] = not any(re.search(r"WEIXIN|HEALTH|HMAC|VAULT|WRITER|EXECUTION_MASTER|AWS_|SSH_AUTH", key, re.I) for key in environment_keys)
                if not proof["main_initial_forbidden_environment_absent"]: raise ValueError("ordinary initial execution environment differs")
            observed[name] = proof
    except Exception as error:
        failure = type(error).__name__
    finally:
        post_processes_finished = True
        if failure is not None:
            # A systemctl client timeout does not end the service job. Do not
            # delete inputs beneath a still-running ExecStartPost or child.
            for name in ("gateway", "ordinary", "core"):
                try:
                    if _manager("stop", roles[name]["unit"]).returncode != 0:
                        post_processes_finished = False
                except (OSError, subprocess.SubprocessError):
                    post_processes_finished = False
            for name in ("gateway", "ordinary", "core"):
                try:
                    check = _manager("show", roles[name]["unit"], "--property=MainPID,ControlPID,ActiveState")
                    state = dict(line.split("=", 1) for line in check.stdout.splitlines() if "=" in line)
                    if (check.returncode != 0 or state.get("MainPID") != "0" or state.get("ControlPID") != "0"
                            or state.get("ActiveState") not in {"inactive", "failed"}):
                        post_processes_finished = False
                except (OSError, subprocess.SubprocessError):
                    post_processes_finished = False
        if post_processes_finished:
            for path in reversed(dropins):
                try: _unlink(path)
                except OSError: cleanup_ok = False
            for directory in reversed(created_directories):
                try: directory.rmdir()
                except OSError: cleanup_ok = False
            for path in paths:
                try:
                    if path.exists() or path.is_symlink(): _unlink(path)
                except OSError: cleanup_ok = False
            try:
                cleanup_ok = _manager("daemon-reload").returncode == 0 and cleanup_ok
            except (OSError, subprocess.SubprocessError): cleanup_ok = False
            cleanup_ok = cleanup_ok and all(not path.exists() and not path.is_symlink() for path in (*paths, *dropins))
        else:
            cleanup_ok = False
    return {"contract": "ticket128-actual-default-role-facts-v1", "passed": failure is None and cleanup_ok and set(observed) == set(_UNITS),
            "roles": observed, "failure_kind": failure, "failed_role": current_role if failure else None, "temporary_probe_resources_removed": cleanup_ok}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=(*_UNITS, "ordinary-child"))
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    _probe_main(args.role, args.input)


if __name__ == "__main__":
    main()

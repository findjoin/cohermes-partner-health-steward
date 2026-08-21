#!/usr/bin/env python3
"""Fail-closed service preflight for the isolated partner health stack.

This script is intended for ``ExecStartPre`` on
``hermes-gateway-partner.service``.  It writes no state and uses only the
standard library.  A non-zero exit prevents a Gateway version/config drift
from silently starting without the busy/idle runtime guard.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import stat
import sys
from pathlib import Path
from typing import Optional


PARTNER_HOME = Path("/root/.hermes/profiles/partner")
GATEWAY_RUN = Path("/usr/local/lib/hermes-agent/gateway/run.py")
CRON_SCHEDULER = Path("/usr/local/lib/hermes-agent/cron/scheduler.py")
EXPECTED_PYTHON = Path("/usr/local/lib/hermes-agent/venv/bin/python")
EXPECTED_METHOD_HASHES = {
    "_handle_active_session_busy_message": (
        "3c00c9a7cf999f96d88bf082f09fbe7e581276c109e06fce26b81148cd487fe4"
    ),
    "_handle_message": (
        "eef720db2afa0bcc8c202307796da839148a51e1fa171dcc434371c9c5f1aefe"
    ),
}
EXPECTED_CRON_FUNCTION_HASHES = {
    "_runtime_job_fingerprint": "5e2b0c339ef681c80033c4c900cdea0a93ea9d0f8c9448ae5342e47214a41fba",
    "_run_job_script": "dc43945868ff3cb3bd315704ea88394e04319a4879011298e5c24ccb5f89efa8",
    "run_job": "072b11674ab25cee08b450421021d9760fd1bc55739433b8ef69efc525caa39b",
}
REMINDER_SHA256 = "0aea5a3b7bea4330d29a78a17926d5bf4392b067807c82ca68344246b0c79401"
EXPECTED_ARTIFACT_HASHES = {
    "plugins/health-guard/plugin.yaml": (
        "5318a497c5f0da1927efa69c69ef8027c6aa7328e692e8e3eed605fd69acf80b"
    ),
    "plugins/health-guard/__init__.py": (
        "bd076acb114e0aafa2381900805e328396ed5dd019d3ec6ff2501b795c625d7c"
    ),
    "plugins/health-guard/guard.py": (
        "9ba40d83f5fcb26074bb7f99075cd11ef67f90f09958542e7525cd4f0f6b6135"
    ),
    "plugins/health-autonomy/plugin.yaml": (
        "873bf3d0fd8bceb4aa98d938b5955fa11fb26f845b86b5097e80113ae17d71f8"
    ),
    "plugins/health-autonomy/__init__.py": (
        "fad66359790ce2e3fc713295667de6bddb0362d30aa91cfdffc7c70b0efc39d8"
    ),
    "plugins/health-autonomy/autonomy.py": (
        "86aee4c697079f46968927b3359d366cc60cd9735ab94920a26fb828523dcfee"
    ),
    "skills/health-steward/SKILL.md": (
        "bd3a73e3a9d334877ad3d02a66616debd6ab324a2e8b0c67965baee4de9d2179"
    ),
    "skills/health-steward/references/medical-safety-sources.md": (
        "a25f84bd9eb14f642a0d11c7ba6c5a71ecc4612ec1da97bf85a64ba501d09151"
    ),
    "scripts/health_reminder_generic.py": REMINDER_SHA256,
    "scripts/health_autonomy_dispatch.py": (
        "25e66420a7dbf695aae72ce5640c2b52ffcbad62f08d2b616ac66614fff04813"
    ),
}
EXPECTED_EXTERNAL_HASHES = {
    Path(
        "/root/.config/systemd/user/hermes-gateway-partner.service.d/"
        "hermes-gateway-partner-health-guard.conf"
    ): "3d868a0cd15a6444d6807a6757e59ab1e080573cb63c52687091af64911ac364",
}
EXPECTED_GUARD_HOOKS = {
    "pre_gateway_dispatch",
    "pre_llm_call",
    "pre_tool_call",
    "transform_llm_output",
}
EXPECTED_AUTONOMY_HOOKS = {
    "pre_gateway_dispatch",
    "pre_llm_call",
    "pre_tool_call",
}


def _fail(message: str) -> None:
    print(f"health-guard preflight: FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def _yaml_scalar(text: str, path: tuple[str, ...]) -> Optional[str]:
    """Read a simple scalar from the config's indentation hierarchy."""
    stack: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped or stripped.startswith("-"):
            continue
        key, value = stripped.split(":", 1)
        key = key.strip().strip("'\"")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        current_path = tuple(item[1] for item in stack) + (key,)
        value = value.strip()
        if current_path == path:
            return value.strip("'\"") if value else None
        if not value:
            stack.append((indent, key))
    return None


def _as_bool(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "on", "1"}:
        return True
    if normalized in {"false", "no", "off", "0"}:
        return False
    _fail(f"invalid boolean scalar: {value!r}")
    return default


def _yaml_list(text: str, path: tuple[str, ...]) -> list[str]:
    """Read a simple scalar list from an indentation-based YAML path."""
    stack: list[tuple[int, str]] = []
    collecting_indent: Optional[int] = None
    values: list[str] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if collecting_indent is not None:
            if indent <= collecting_indent:
                return values
            if stripped.startswith("-"):
                item = stripped[1:].split("#", 1)[0].strip().strip("'\"")
                if item:
                    values.append(item)
            continue

        if ":" not in stripped or stripped.startswith("-"):
            continue
        key, value = stripped.split(":", 1)
        key = key.strip().strip("'\"")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        current_path = tuple(item[1] for item in stack) + (key,)
        value = value.split("#", 1)[0].strip()
        if current_path == path:
            if not value:
                collecting_indent = indent
                continue
            if value.startswith("[") and value.endswith("]"):
                return [
                    item.strip().strip("'\"")
                    for item in value[1:-1].split(",")
                    if item.strip()
                ]
            _fail(f"expected YAML list at {'.'.join(path)}")
        if not value:
            stack.append((indent, key))
    return values


def _method_hashes(path: Path) -> dict[str, str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(True)
    tree = ast.parse(source)
    runner = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "GatewayRunner"
        ),
        None,
    )
    if runner is None:
        _fail("GatewayRunner class not found")
    hashes: dict[str, str] = {}
    for node in runner.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in EXPECTED_METHOD_HASHES:
            raw = "".join(lines[node.lineno - 1 : node.end_lineno])
            hashes[node.name] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return hashes


def _top_level_function_hashes(
    path: Path, expected_names: set[str]
) -> dict[str, str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(True)
    tree = ast.parse(source)
    hashes: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in expected_names
        ):
            raw = "".join(lines[node.lineno - 1 : node.end_lineno])
            hashes[node.name] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return hashes


def _verify_plugin_registration(
    plugin_dir: Path,
    plugin_name: str,
    expected_hooks: set[str],
    expected_commands: set[str],
) -> None:
    """Import and register the exact plugin in this short-lived process."""
    init_path = plugin_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        f"_{plugin_name.replace('-', '_')}_preflight_plugin",
        init_path,
        submodule_search_locations=[str(plugin_dir)],
    )
    if spec is None or spec.loader is None:
        _fail("cannot create health-guard plugin import spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module

    class ProbeContext:
        def __init__(self) -> None:
            self.profile_name = "partner"
            self.hooks: set[str] = set()
            self.commands: set[str] = set()

        def register_hook(self, name: str, callback) -> None:
            if not callable(callback):
                _fail(f"plugin hook is not callable: {name}")
            self.hooks.add(name)

        def register_command(self, name: str, *, handler, **kwargs) -> None:
            if not callable(handler):
                _fail(f"plugin command handler is not callable: {name}")
            self.commands.add(name)

    try:
        spec.loader.exec_module(module)
        context = ProbeContext()
        module.register(context)
    except Exception as exc:
        _fail(f"health-guard registration probe failed: {type(exc).__name__}: {exc}")
    if context.hooks != expected_hooks:
        _fail(f"{plugin_name} hooks mismatch: {sorted(context.hooks)}")
    if context.commands != expected_commands:
        _fail(f"{plugin_name} command mismatch: {sorted(context.commands)}")


def _require_root_owned_not_writable(path: Path, *, exact_mode: Optional[int] = None) -> None:
    try:
        metadata = path.stat()
    except OSError:
        _fail(f"required file missing: {path}")
    if metadata.st_uid != 0:
        _fail(f"file is not owned by root: {path}")
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & 0o022:
        _fail(f"file is group/world writable: {path} mode={mode:o}")
    if exact_mode is not None and mode != exact_mode:
        _fail(f"unexpected file mode: {path} mode={mode:o}, expected={exact_mode:o}")


def main() -> int:
    if os.environ.get("HEALTH_GUARD_TEST_MODE"):
        _fail("HEALTH_GUARD_TEST_MODE must be unset in production")
    if os.environ.get("HEALTH_AUTONOMY_TEST_MODE"):
        _fail("HEALTH_AUTONOMY_TEST_MODE must be unset in production")

    home = Path(os.environ.get("HERMES_HOME", "")).expanduser()
    try:
        resolved_home = home.resolve()
    except OSError:
        resolved_home = home.absolute()
    if resolved_home != PARTNER_HOME:
        _fail(f"HERMES_HOME must be {PARTNER_HOME}")
    if Path(sys.executable) != EXPECTED_PYTHON:
        _fail(f"preflight interpreter must be {EXPECTED_PYTHON}")

    config_path = PARTNER_HOME / "config.yaml"
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except OSError:
        _fail(f"cannot read {config_path}")

    multiplex = _as_bool(_yaml_scalar(config_text, ("multiplex_profiles",))) or _as_bool(
        _yaml_scalar(config_text, ("gateway", "multiplex_profiles"))
    )
    if multiplex:
        _fail("multiplex_profiles must be false for the partner-only runtime patch")
    if _yaml_scalar(config_text, ("timezone",)) != "Asia/Shanghai":
        _fail("timezone must be Asia/Shanghai")
    if _as_bool(_yaml_scalar(config_text, ("streaming", "enabled")), default=True):
        _fail("streaming.enabled must be false")
    enabled_plugins = {_item.strip() for _item in _yaml_list(config_text, ("plugins", "enabled"))}
    disabled_plugins = {_item.strip() for _item in _yaml_list(config_text, ("plugins", "disabled"))}
    if "health-guard" not in enabled_plugins:
        _fail("plugins.enabled must contain health-guard")
    if "health-autonomy" not in enabled_plugins:
        _fail("plugins.enabled must contain health-autonomy")
    if "health-guard" in disabled_plugins:
        _fail("plugins.disabled must not contain health-guard")
    if "health-autonomy" in disabled_plugins:
        _fail("plugins.disabled must not contain health-autonomy")

    if not GATEWAY_RUN.is_file():
        _fail(f"Hermes gateway source missing: {GATEWAY_RUN}")
    spec = importlib.util.find_spec("gateway.run")
    if spec is None or not spec.origin:
        _fail("gateway.run cannot be resolved by the service interpreter")
    try:
        resolved_origin = Path(spec.origin).resolve()
    except OSError:
        resolved_origin = Path(spec.origin).absolute()
    if resolved_origin != GATEWAY_RUN:
        _fail(f"gateway.run resolves to unexpected source: {resolved_origin}")
    actual_hashes = _method_hashes(GATEWAY_RUN)
    for method_name, expected in EXPECTED_METHOD_HASHES.items():
        if actual_hashes.get(method_name) != expected:
            _fail(f"unsupported Hermes source for {method_name}")
    if not CRON_SCHEDULER.is_file():
        _fail(f"Hermes cron scheduler source missing: {CRON_SCHEDULER}")
    cron_hashes = _top_level_function_hashes(
        CRON_SCHEDULER, set(EXPECTED_CRON_FUNCTION_HASHES)
    )
    for function_name, expected in EXPECTED_CRON_FUNCTION_HASHES.items():
        if cron_hashes.get(function_name) != expected:
            _fail(f"unsupported Hermes cron source for {function_name}")

    for relative_path, expected_hash in EXPECTED_ARTIFACT_HASHES.items():
        artifact = PARTNER_HOME / relative_path
        exact_mode = 0o500 if relative_path in {
            "scripts/health_reminder_generic.py",
            "scripts/health_autonomy_dispatch.py",
        } else None
        _require_root_owned_not_writable(artifact, exact_mode=exact_mode)
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected_hash:
            _fail(f"protected artifact hash mismatch: {relative_path}")
    for artifact, expected_hash in EXPECTED_EXTERNAL_HASHES.items():
        _require_root_owned_not_writable(artifact)
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected_hash:
            _fail(f"protected external artifact hash mismatch: {artifact}")

    _verify_plugin_registration(
        PARTNER_HOME / "plugins" / "health-guard",
        "health-guard",
        EXPECTED_GUARD_HOOKS,
        {"health-guard-safe"},
    )
    _verify_plugin_registration(
        PARTNER_HOME / "plugins" / "health-autonomy",
        "health-autonomy",
        EXPECTED_AUTONOMY_HOOKS,
        {"health-autonomy-safe"},
    )

    print("health-guard preflight: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

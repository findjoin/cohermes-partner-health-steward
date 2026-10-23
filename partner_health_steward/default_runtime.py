"""Fixed default composition and bounded three-role launch facilities.

Bindings contain locators and typed, non-secret facts. Health authority remains
in ProductionCoreService, its encrypted store and the host current-head.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import grp
import hashlib
import json
import os
import pwd
import re
import shutil
import signal
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .admission import AdmissionPolicy
from .coordination import CoarseMessageRouter, DailySkillAsset, DailySkillAttestor, DailySkillBundle
from .governed_nondiagnostic import GovernedNonDiagnosticRuntime
from .initialization import (HealthInitAsset, HealthInitAttestor, HealthInitRuntime,
    INITIAL_DATA_BOUNDARY, InitialPreferences, OwnerInitialization)
from .live_health import LiveHealthRuntime
from .model_adapter import NonDiagnosticBudgetInputMeasurementStrategy
from .model_contract import FirstHopRoute, ModelMessage, NonDiagnosticOperationalBudget, StrictHealthLLM
from .nondiagnostic import ApprovedClaimAtom, ApprovedReplyTemplate
from .settings import RouteConfigurationUpdate
from .status import CapabilityFactAuthority, PRODUCTION_STATUS_PRODUCER_CONTRACTS

HOME = Path("/root/.hermes")
PROGRAM = Path("/opt/cohermes-default/program")
STATE = Path("/var/lib/cohermes-default-core")
SOCKET_ROOT = Path("/run/cohermes-default")
ORDINARY = Path("/var/lib/cohermes-default-ordinary")
UNIT_ROOT = Path("/root/.config/systemd/user")
RESOURCE = "assets/non-diagnostic/runtime-resources.json"
_LIVE_FIELDS = {"contract", "installation_id", "admission_policy", "route", "operational_budget",
    "init_attestor_path", "daily_attestor_path", "status_hmac_path", "resource_paths"}
_TARGET_DIRTY_FILES = {"agent/display.py", "agent/transports/codex.py", "gateway/run.py", "package-lock.json",
                       "gateway/skill_disclosure.py"}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _json(path):
    from .production_core_service import _strict_json
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("default binding is unavailable")
    return _strict_json(path.read_bytes())


def _private_key(value):
    path = Path(value)
    details = path.lstat()
    parent = path.parent.lstat()
    if (path.is_symlink() or not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
            or details.st_uid != os.geteuid() or details.st_gid != os.getegid()
            or stat.S_IMODE(details.st_mode) != 0o400 or details.st_size != 32
            or path.parent.is_symlink() or (parent.st_uid, parent.st_gid, stat.S_IMODE(parent.st_mode))
            != (os.geteuid(), os.getegid(), 0o700)):
        raise ValueError("default private capability is unsafe")
    return path.read_bytes()


def _coarse_classifier(rules):
    if (type(rules) is not dict or rules.get("unknown") != "uncertain"
            or any(type(rules.get(k)) is not list for k in
                   ("health_terms", "ordinary_exact", "ordinary_nonhealth_prefixes"))):
        raise ValueError("invalid release coarse rules")
    terms = tuple(item.casefold() for item in rules["health_terms"])
    exact = tuple(rules["ordinary_exact"])
    if rules["ordinary_nonhealth_prefixes"]:
        raise ValueError("ordinary coarse rules require whole-message matching")
    def classify(body, capability):
        del capability
        if type(body) is not str or body != body.strip() or not body:
            return "uncertain"
        if body.startswith("/health") or any(word in body.casefold() for word in terms):
            return "health"
        if re.fullmatch(r"连接测试 [0-9a-f]{32}", body) or re.fullmatch(r"验收反馈 [0-9a-f]{32} 有用 清楚 可信", body):
            return "ordinary"
        # Relay rejects commands before Hermes command/plugin dispatch. They
        # contain no free health body and never become a worker turn.
        if re.fullmatch(r"/[A-Za-z0-9_-]+(?: [A-Za-z0-9_-]+)?", body):
            return "ordinary"
        if body in exact or re.fullmatch(r"请在普通工作区运行 [A-Z][A-Z0-9_]{0,63} 并报告结果", body):
            return "ordinary"
        return "uncertain"
    return classify


def _validate_live_product_source(release_root, runtime_root=None):
    package = Path(__file__).resolve().parent
    if runtime_root is not None and not package.is_relative_to(Path(runtime_root).resolve()):
        raise ValueError("default product import is outside the declared runtime")
    released = Path(release_root) / "plugin/health-weixin/partner_health_steward"
    for actual in package.rglob("*"):
        if not actual.is_file() or "__pycache__" in actual.parts or actual.suffix == ".pyc":
            continue
        source = released / actual.relative_to(package)
        if actual.is_symlink() or not source.is_file() or actual.read_bytes() != source.read_bytes():
            raise ValueError("default product import differs from its current distribution")


def load_default_live_runtime(release_root, binding) -> LiveHealthRuntime:
    """Load the fixed typed ND runtime without importing network credentials."""
    from .production_core_service import _validate_active_release
    if type(binding) is not dict or set(binding) != _LIVE_FIELDS or binding["contract"] != "ticket128-default-live-binding-v1":
        raise ValueError("invalid default live binding")
    root = Path(release_root)
    release = _validate_active_release(root)
    if release.get("state") != "current" or binding["resource_paths"] != {"runtime_resources": RESOURCE}:
        raise ValueError("default live release is unavailable")
    _validate_live_product_source(root)
    resources = _json(root / RESOURCE)
    if resources.get("contract") != "ticket128-project-nondiagnostic-resources-v1" or resources.get("knowledge_releases") != []:
        raise ValueError("invalid default non-diagnostic resources")
    policy = AdmissionPolicy.from_storage(binding["admission_policy"])
    route = FirstHopRoute.from_wire(binding["route"])
    budget = NonDiagnosticOperationalBudget.from_wire(binding["operational_budget"])
    if route != budget.route:
        raise ValueError("default route budget mismatch")
    asset = HealthInitAsset.from_storage(resources["health_init_asset"])
    if asset.disclosure_version != "health-init-nd-host-only-v1":
        raise ValueError("default disclosure version mismatch")
    init = HealthInitRuntime(asset, HealthInitAttestor(_private_key(binding["init_attestor_path"]),
        key_id="default-init:" + binding["installation_id"]))
    bundle = DailySkillBundle(tuple(DailySkillAsset.from_storage(item) for item in resources["daily_skill_assets"]))
    daily_attestor = DailySkillAttestor(_private_key(binding["daily_attestor_path"]),
        key_id="default-daily:" + binding["installation_id"])
    strategy = NonDiagnosticBudgetInputMeasurementStrategy(budget)
    llms = []
    for stage in ("intake", "answer"):
        request = strategy.prepare_request((ModelMessage("system", "固定非诊断受管处理"),
                                            ModelMessage("user", "运行时组合")), stage=stage)
        llms.append(StrictHealthLLM(route, budget, request.strict_schema_name,
            request.strict_schema_digest, measurement_strategy=strategy))
    governed = GovernedNonDiagnosticRuntime(*llms, strategy, bundle=bundle, attestor=daily_attestor)
    safety = copy.deepcopy(resources["safety_diagnostic_assets"])
    if safety.get("diagnostic_scope_bundle") is not None:
        raise ValueError("diagnosis is not enabled in default ND composition")
    safety["release_digest"] = release["release_digest"]
    route_fact = RouteConfigurationUpdate(route.route_id, route.route_id,
        route.configuration_generation, asset.disclosure_version, route.configuration_generation)
    options = {
        "route_configuration_provider": lambda: route_fact,
        "status_fact_authority": CapabilityFactAuthority(authority_id="default-status:" + binding["installation_id"],
            signing_key=_private_key(binding["status_hmac_path"]),
            producer_contracts=dict(PRODUCTION_STATUS_PRODUCER_CONTRACTS)),
        "model_authority_digest": llms[1].model_authority_digest,
        "knowledge_releases": (), "knowledge_valid_at": datetime.now(timezone.utc).isoformat(),
        "approved_claims": tuple(ApprovedClaimAtom.from_wire(item) for item in resources["approved_claims"]),
        "approved_templates": tuple(ApprovedReplyTemplate.from_wire(item) for item in resources["approved_templates"]),
        "safety_diagnostic_assets": safety,
    }
    paths = {name: f"skills/{name}/SKILL.md" for name in ("health-init", *(a.canonical_name for a in bundle.assets))}
    runtime = LiveHealthRuntime(policy, init, CoarseMessageRouter(_coarse_classifier(resources["coarse_rules"])),
        asset_paths=paths, core_options=options, governed_nondiagnostic_runtime=governed)
    runtime.validate_release(root, release)
    return runtime


def _account_plan(name, group, reserved):
    try:
        user = pwd.getpwnam(name)
        group_record = grp.getgrnam(group)
        if user.pw_uid == 0 or user.pw_gid != group_record.gr_gid:
            raise ValueError("default service identity conflicts")
        return {"user": name, "group": group, "uid": user.pw_uid, "gid": user.pw_gid}
    except KeyError:
        used_uids = {u.pw_uid for u in pwd.getpwall()} | reserved
        used_gids = {g.gr_gid for g in grp.getgrall()} | reserved
        number = next(value for value in range(950, 999) if value not in used_uids | used_gids)
        reserved.add(number)
        return {"user": name, "group": group, "uid": number, "gid": number}


def build_default_plan(release_root, facts, identity):
    """Plan fixed paths only. No accounts, keys, authority, units or effects."""
    from .production_core_service import _validate_active_release
    from .lifecycle import LIFECYCLE_PURGE_BINDINGS
    if type(facts) is not dict or type(identity) is not dict:
        raise ValueError("invalid default setup facts")
    if facts.get("support_contact") is not None:
        raise ValueError("default ND support contact is unavailable")
    release_root = Path(release_root).absolute()
    release = _validate_active_release(release_root)
    if release.get("state") != "current":
        raise ValueError("default requires current distribution")
    policy = AdmissionPolicy.from_storage(facts["admission_policy"])
    route = FirstHopRoute.from_wire(facts["route"])
    budget = NonDiagnosticOperationalBudget.from_wire(facts["operational_budget"])
    if budget.route != route:
        raise ValueError("default route budget mismatch")
    runtime_root = Path(facts["runtime_root"]).absolute()
    runtime_manifest = _json(runtime_root / "ticket123-runtime-manifest.json")
    from .release_deployment import _validate_ticket123_runtime_manifest
    _validate_ticket123_runtime_manifest(runtime_manifest)
    reserved = set()
    core_id = _account_plan("cohermes-core", "cohermes-health", reserved)
    ordinary_id = _account_plan("cohermes-ordinary", "cohermes-ordinary", reserved)
    distribution = release["release_digest"].removeprefix("sha256:")
    root = PROGRAM / distribution
    live_release, live_runtime, shadow = root / "releases" / distribution, root / "runtime", root / "hermes"
    instance, site = identity["installation_id"], identity["site"]
    live = {"contract": "ticket128-default-live-binding-v1", "installation_id": instance,
        "admission_policy": policy.to_storage(), "route": route.to_wire(), "operational_budget": budget.to_wire(),
        "init_attestor_path": str(STATE / "capabilities/init-attestor"),
        "daily_attestor_path": str(STATE / "capabilities/daily-attestor"),
        "status_hmac_path": str(STATE / "capabilities/status-hmac"),
        "resource_paths": {"runtime_resources": RESOURCE}}
    host = {"data_key": str(STATE / "capabilities/data-key"),
        "writer_master": str(STATE / "capabilities/writer-master"),
        "execution_master": str(STATE / "capabilities/execution-master"),
        "lock_directory": str(STATE / "locks")}
    lifecycle = {"product_release": release["release_digest"], "adr": "ADR-0022",
        "skills": ["health-init", *[item["canonical_name"] for item in _json(release_root / RESOURCE)["daily_skill_assets"]]],
        "plugin_core_bundle": _sha((release_root / "product/core.py").read_bytes()),
        "adapter_model_interface_bundle": _sha((release_root / "adapters/model.py").read_bytes()),
        "knowledge_safety_diagnostic_bundle": _sha((release_root / RESOURCE).read_bytes()),
        "hermes_artifact": release["host_release_digest"],
        "required_patch": _sha((release_root / "host/required.patch").read_bytes()),
        "disabled_native_entry_assertion": True, "schema": "ticket117-semantic-state-v1",
        "observer_identity": "observer:default-local", "acl_service": "acl:default-coreport",
        "secret_requirements": ["health-key-ref", "target-fence-ref"],
        "unbound_real_providers": ["vm-whole-machine-snapshots", "weixin-platform-and-owner-copies"]}
    core = {"contract": "ticket123-production-core-binding-v1", "release_root": str(live_release),
        "release_digest": release["release_digest"], "runtime_root": str(live_runtime), "runtime_manifest": runtime_manifest,
        "installation_id": instance, "site": site, "database_path": str(STATE / "health.sqlite"),
        "socket_path": str(SOCKET_ROOT / "core.sock"), "socket_owner_uid": core_id["uid"],
        "socket_group_gid": core_id["gid"], "socket_mode": 0o660, "allowed_peer_uid": 0,
        "host_private_paths": host, "managed_replica_root": str(STATE / "managed-replicas"),
        "managed_replica_bindings": {name: None for name in LIFECYCLE_PURGE_BINDINGS},
        "migration_artifact_root": str(STATE / "migration-artifacts"), "lifecycle_release": lifecycle}
    # The fence is filled by the original writer vault during the one real
    # bootstrap; a missing existing head never goes through that operation.
    head = {"contract": "health-current-head-binding-v1", "provider": "host-sqlite", "binding": {
        "database_path": str(STATE / "current-head.sqlite"), "installation_id": instance,
        "local_site": site, "local_writer_fence_ref": None}}
    if (STATE / "current-head.json").is_file():
        head = _json(STATE / "current-head.json")
        if head["binding"]["installation_id"] != instance or head["binding"]["local_site"] != site:
            raise ValueError("default existing installation identity mismatch")
    init = OwnerInitialization("workflow:default-template", "source:default-template", False,
        route.route_id, False, facts["timezone"], InitialPreferences.from_storage(facts["preferences"]),
        INITIAL_DATA_BOUNDARY, None)
    gateway = {"contract": "ticket128-default-gateway-binding-v1", "release_root": str(live_release),
        "runtime_root": str(live_runtime), "shadow_root": str(shadow),
        "core_port_endpoint": {"transport": "af-unix", "path": core["socket_path"], "protocol": "ticket118-core-port-v1"},
        "admission_policy": policy.to_storage(), "route": route.to_wire(), "budget": budget.to_wire(),
        "weixin_transport_binding": {"account_id": policy.partner_id, "base_url": facts["weixin_base_url"]},
        "initialization_template": init.to_storage(), "proxy_url": "http://127.0.0.1:8642",
        "proxy_key_path": str(root / "proxy-key"), "source_manifest_path": str(root / "source-manifest.json")}
    roles = []
    for role, unit, account in (("core", "cohermes-default-core.service", core_id),
                               ("ordinary", "cohermes-default-ordinary.service", ordinary_id),
                               ("gateway", "hermes-gateway.service", {"uid": 0, "gid": core_id["gid"], "user": "root", "group": core_id["group"]})):
        roles.append({"role": role, "unit": unit, "unit_path": str(UNIT_ROOT / unit),
            "runtime_root": str(live_runtime), **account,
            **({"workspace": str(ORDINARY / "workspace")} if role == "ordinary" else {})})
    return {"core_binding": core, "head_binding": head, "live_binding": live, "gateway_config": gateway,
        "roles": roles, "program_resources": [str(root), str(HOME / "config.yaml"), str(HOME / "plugins/health-weixin"),
            str(HOME / ".ticket128-gateway.json"), str(HOME / ".health-release.json"),
            str(PROGRAM / "ordinary.json"), str(ORDINARY / "config.yaml"), str(ORDINARY / ".env"),
            str(STATE / "core.json"), str(STATE / "live.json"),
            *[role["unit_path"] for role in roles], *[role["unit_path"] + ".d" for role in roles]],
        "program_plan": {"source_release_root": str(release_root), "source_runtime_root": str(runtime_root),
            "pinned_hermes_root": str(Path(facts["pinned_hermes_root"]).absolute()), "program_root": str(root),
            "core_identity": core_id, "ordinary_identity": ordinary_id}}


def _write(path, data, mode=0o600, uid=0, gid=0, *, exclusive=False):
    if type(data) is str:
        data = data.encode()
    path = Path(path)
    if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
        raise ValueError("unsafe default program resource")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, mode)
    try:
        os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _provision_account(account):
    try:
        existing = pwd.getpwnam(account["user"])
        if (existing.pw_uid, existing.pw_gid) != (account["uid"], account["gid"]):
            raise ValueError("default identity changed since prepare")
    except KeyError:
        subprocess.run(["groupadd", "--system", "--gid", str(account["gid"]), account["group"]], check=True, capture_output=True)
        subprocess.run(["useradd", "--system", "--uid", str(account["uid"]), "--gid", str(account["gid"]),
            "--no-create-home", "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin", account["user"]], check=True, capture_output=True)
    if set(os.getgrouplist(account["user"], account["gid"])) != {account["gid"]}:
        raise ValueError("default dedicated identity has unexpected supplementary groups")


def _directory(path, uid, gid, mode):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("unsafe default directory")
    if path.exists():
        details = path.stat()
        if not path.is_dir() or (details.st_uid, details.st_gid, stat.S_IMODE(details.st_mode)) != (uid, gid, mode):
            raise ValueError("existing default directory identity or permissions drift")
        return
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def _ordinary_provider_projection(config, values):
    """Project only the currently selected Hermes provider and its secrets."""
    from hermes_cli.config import get_compatible_custom_providers
    from hermes_cli.providers import custom_provider_aliases, get_provider
    model = copy.deepcopy(config.get("model"))
    if type(model) is not dict or not isinstance(model.get("provider"), str):
        raise ValueError("ordinary provider must be explicitly configured")
    requested = model["provider"].strip().lower()
    entries = get_compatible_custom_providers(config)
    matched = [entry for entry in entries if requested in custom_provider_aliases(entry.get("name", ""), entry.get("provider_key", ""))]
    if requested == "custom" and model.get("base_url"):
        matched = [entry for entry in entries if entry["base_url"].rstrip("/") == model["base_url"].rstrip("/")]
    if len(matched) > 1:
        raise ValueError("ordinary provider selection is ambiguous")
    selected = matched[0] if matched else model
    projected = {"model": model}
    if matched:
        key = selected.get("provider_key")
        if key:
            projected["providers"] = {key: copy.deepcopy(config["providers"][key])}
        else:
            projected["custom_providers"] = [copy.deepcopy(selected)]
    needed = set()
    explicit = selected.get("key_env", selected.get("api_key_env"))
    if explicit:
        needed.add(explicit)
    elif selected.get("base_url") and _host_provider_key(selected["base_url"], values):
        key = _host_provider_key(selected["base_url"], values)
        names = [name for name, value in values.items() if value == key and name.endswith("_API_KEY")]
        if len(names) != 1:
            raise ValueError("ordinary host-derived provider capability is ambiguous")
        needed.add(names[0])
    elif requested not in {"custom", "auto"} and not matched:
        definition = get_provider(requested, allow_network=False)
        if definition is None or definition.auth_type != "api_key":
            raise ValueError("ordinary provider has no explicit portable credential binding")
        available = [key for key in definition.api_key_env_vars if values.get(key)]
        if len(available) != 1:
            raise ValueError("ordinary provider credential is unavailable or ambiguous")
        needed.update(available)
        if definition.base_url_env_var and values.get(definition.base_url_env_var):
            needed.add(definition.base_url_env_var)
    elif (not selected.get("api_key") and selected.get("base_url")
            and selected["base_url"].rstrip("/") == str(values.get("OPENAI_BASE_URL", "")).rstrip("/")):
        # An explicitly configured OpenAI-compatible endpoint owns this pair;
        # it is never borrowed for an unrelated endpoint or health route.
        needed.update({"OPENAI_API_KEY", "OPENAI_BASE_URL"})
    def references(value):
        if isinstance(value, dict):
            for item in value.values(): references(item)
        elif isinstance(value, list):
            for item in value: references(item)
        elif isinstance(value, str):
            needed.update(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value))
    references(projected)
    if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
           or re.search(r"WEIXIN|HEALTH|HMAC|VAULT|WRITER|EXECUTION_MASTER|GATEWAY_PROXY", key, re.I) for key in needed):
        raise ValueError("ordinary provider requests a non-provider capability")
    if any(not isinstance(values.get(key), str) or not values[key] for key in needed):
        raise ValueError("ordinary provider credential is unavailable")
    if not needed and not selected.get("api_key"):
        raise ValueError("ordinary provider credential is not explicitly bound")
    return projected, {key: values[key] for key in needed}


def _host_provider_key(base_url, values):
    # Use pinned Hermes' own registrable-host derivation with its existing
    # context-local secret scope. No process environment mutation, provider
    # fallback, discovery, refresh, or network operation is involved.
    from hermes_cli.runtime_provider import _host_derived_api_key
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    token = set_secret_scope(values)
    try:
        return _host_derived_api_key(base_url)
    finally:
        reset_secret_scope(token)


def load_default_health_credential(route):
    """Resolve a provider credential only in the trusted default I/O process."""
    if type(route) is not FirstHopRoute:
        raise ValueError("invalid health provider route")
    import yaml
    from dotenv import dotenv_values
    from hermes_cli.config import get_compatible_custom_providers
    config = yaml.safe_load((HOME / "config.yaml").read_text()) or {}
    values = dotenv_values(HOME / ".env")
    entries = [entry for entry in get_compatible_custom_providers(config)
        if entry["base_url"].rstrip("/") == route.canonical_base_url.rstrip("/")]
    if len(entries) > 1:
        raise ValueError("health provider credential binding is ambiguous")
    model = config.get("model", {})
    if not entries and type(model) is dict and model.get("base_url", "").rstrip("/") == route.canonical_base_url.rstrip("/"):
        entries = [model]
    if len(entries) != 1:
        raise ValueError("health route has no current configured provider")
    entry = entries[0]
    name = entry.get("key_env", entry.get("api_key_env"))
    key = values.get(name) if name else entry.get("api_key")
    if key is None:
        key = _host_provider_key(route.canonical_base_url, values) or None
    if key is None and str(values.get("OPENAI_BASE_URL", "")).rstrip("/") == route.canonical_base_url.rstrip("/"):
        key = values.get("OPENAI_API_KEY")
    if type(key) is not str or not key:
        raise ValueError("health provider credential is unavailable")
    return key


def _bootstrap_core(plan):
    """Run as the Core identity, once, with all-or-none private facilities."""
    os.umask(0o077)
    from .host_authority import HostPrivateFacilityPaths, HostPrivateKeyProvider, HostPrivateWriterFenceVault
    from .host_current_head import HostHeadBinding, HostSQLiteCurrentHead
    from .current_head import HeadSnapshot
    from .storage import EncryptedStateStore
    core, live, head = plan["core_binding"], plan["live_binding"], plan["head_binding"]
    paths = HostPrivateFacilityPaths(**{k: Path(v) for k, v in core["host_private_paths"].items()})
    required = [paths.data_key, paths.writer_master, paths.execution_master,
                *(Path(live[k]) for k in ("init_attestor_path", "daily_attestor_path", "status_hmac_path"))]
    database, head_path = Path(core["database_path"]), Path(head["binding"]["database_path"])
    present = [p.exists() for p in (*required, database, head_path)]
    if any(present):
        if not all(present):
            raise ValueError("partial default authority cannot be bootstrapped")
        for path in required:
            _private_key(path)
        current = _json(STATE / "current-head.json")
        with_head = HostSQLiteCurrentHead(HostHeadBinding(**current["binding"]))
        try:
            if with_head.read().head.installation_id != core["installation_id"]:
                raise ValueError("existing default authority identity mismatch")
        finally:
            with_head.close()
        return
    # The directory must be a genuinely empty new namespace. A previously
    # retained WAL, capability, tombstone or stray object prevents bootstrap.
    permitted = {STATE / "capabilities", STATE / "locks", STATE / "managed-replicas", STATE / "migration-artifacts"}
    if any(path not in permitted for path in STATE.iterdir()) or any(any((STATE / name).iterdir()) for name in ("capabilities", "locks", "managed-replicas", "migration-artifacts")):
        raise ValueError("default authority namespace is not new")
    for path in required:
        _write(path, os.urandom(32), 0o400, os.geteuid(), os.getegid(), exclusive=True)
    writer = HostPrivateWriterFenceVault(paths)
    try:
        fence = writer.prepare_fence_ref(core["installation_id"], core["site"], "writer-epoch:default-genesis-v1")
    finally:
        writer.close()
    operation = {"contract": "default-empty-installation-genesis-v1", "installation_id": core["installation_id"],
        "site": core["site"], "writer_fence": fence, "empty_state": True}
    revision = _sha(_canonical(operation))
    snapshot = HeadSnapshot(core["installation_id"], 1, revision, "transition:genesis:" + revision[7:], fence, False, core["site"])
    head["binding"]["local_writer_fence_ref"] = fence
    keys = HostPrivateKeyProvider(paths, core["installation_id"])
    store = EncryptedStateStore(core["database_path"], keys)
    try:
        store.seed_finalized_authority(snapshot.as_authority())
    finally:
        store.close()
        keys.close()
    provider = HostSQLiteCurrentHead.bootstrap(HostHeadBinding(**head["binding"]), snapshot)
    provider.close()
    _write(STATE / "current-head.json", _canonical(head), 0o400, os.geteuid(), os.getegid(), exclusive=True)


def _source_manifest(root):
    root = Path(root)
    result = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink() or "__pycache__" in path.parts or path.suffix == ".pyc":
            raise ValueError("unbound executable source object")
        if path.is_file():
            result.append({"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())})
    return result


def _dirty_overlay(runtime_root):
    root = Path(runtime_root) / "hermes-target-dirty"
    if not root.exists():
        return []
    entries = _source_manifest(root)
    if {item["path"] for item in entries} != _TARGET_DIRTY_FILES:
        raise ValueError("target dirty source overlay is incomplete")
    return entries


def _copy_pinned_shadow(pinned, destination, runtime_root):
    """Copy actual fixed-commit tracked bytes, never a host working profile."""
    from .host_contract import _PINNED_COMMIT
    pinned = Path(pinned)
    if subprocess.run(["git", "-C", str(pinned), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip() != _PINNED_COMMIT:
        raise ValueError("default Hermes pin mismatch")
    overlay = {item["path"]: item["sha256"] for item in _dirty_overlay(runtime_root)}
    listing = subprocess.run(["git", "-C", str(pinned), "ls-tree", "-r", "-z", "--full-tree", "HEAD"],
        check=True, capture_output=True).stdout
    files = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, relative = record.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        relative = relative.decode("utf-8")
        if kind != "blob" or mode not in {"100644", "100755"} or "\n" in relative:
            raise ValueError("unsupported pinned source object")
        path = pinned / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("pinned tracked source is unavailable")
        files.append((relative, blob, int(mode, 8) & 0o777))
    actual = subprocess.run(["git", "-C", str(pinned), "hash-object", "--stdin-paths"],
        input="".join(relative + "\n" for relative, _, _ in files), check=True, capture_output=True, text=True).stdout.splitlines()
    if len(actual) != len(files):
        raise ValueError("pinned full tracked-source inventory unavailable")
    for (relative, expected, _), observed in zip(files, actual):
        if observed != expected and (relative not in overlay or _sha((pinned / relative).read_bytes()) != overlay[relative]):
            raise ValueError("pinned full tracked-source drift")
    helper = pinned / "gateway/skill_disclosure.py"
    if helper.exists() and ("gateway/skill_disclosure.py" not in overlay
            or helper.is_symlink() or _sha(helper.read_bytes()) != overlay["gateway/skill_disclosure.py"]):
        raise ValueError("target source dependency is not sealed")
    destination.mkdir(mode=0o755)
    # Git object bytes give one canonical source independent of checkout
    # autocrlf. Apply the separately sealed target changes afterwards.
    process = subprocess.Popen(["git", "-C", str(pinned), "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for relative, blob, mode in files:
            process.stdin.write((blob + "\n").encode("ascii"))
            process.stdin.flush()
            header = process.stdout.readline().decode("ascii").strip().split()
            if len(header) != 3 or header[:2] != [blob, "blob"]:
                raise ValueError("pinned Git source object unavailable")
            size = int(header[2])
            content = process.stdout.read(size)
            if len(content) != size or process.stdout.read(1) != b"\n":
                raise ValueError("pinned Git source object incomplete")
            target = destination / relative
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(mode)
        process.stdin.close()
        if process.wait(timeout=30) != 0:
            raise ValueError("pinned Git source reader failed")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
    for directory in (destination, *(path for path in destination.rglob("*") if path.is_dir())):
        directory.chmod(0o755)
    for relative in overlay:
        source = Path(runtime_root) / "hermes-target-dirty" / relative
        shutil.copyfile(source, destination / relative)
        (destination / relative).chmod(0o644)
    return [{"path": relative, "sha256": digest} for relative, digest in sorted(overlay.items())]


def _verify_sources(binding):
    from .production_core_service import _validate_active_release, _validate_current_runtime_attestation
    from .release_deployment import _validate_ticket123_runtime_manifest
    root = Path(binding["release_root"])
    release = _validate_active_release(root)
    runtime = Path(binding["runtime_root"])
    manifest = _validate_ticket123_runtime_manifest(_json(runtime / "ticket123-runtime-manifest.json"))
    # Gateway/worker are deliberately different UIDs. Preserve Core's own
    # identity checks; verify the same complete bytes and attestation here.
    for directory in (root, runtime):
        details = directory.lstat()
        if directory.is_symlink() or not stat.S_ISDIR(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o022:
            raise ValueError("unsafe default public program root")
    actual = {}
    for path in runtime.rglob("*"):
        if path.is_symlink():
            raise ValueError("default runtime symlink")
        if path.is_file() and path.name != "ticket123-runtime-manifest.json":
            actual[path.relative_to(runtime).as_posix()] = _sha(path.read_bytes())
    if actual != {item["path"]: item["sha256"] for item in manifest["files"]} or sys.version_info[:2] != (3, 11):
        raise ValueError("default runtime closure drift")
    _validate_current_runtime_attestation(root, release, manifest)
    _validate_live_product_source(root, runtime)
    expected = _json(binding["source_manifest_path"])
    shadow = Path(binding["shadow_root"])
    if expected.get("contract") != "ticket128-shadow-source-binding-v1" or expected["files"] != _source_manifest(shadow):
        raise ValueError("default shadow source drift")
    if (expected["distribution_digest"] != release["release_digest"]
            or expected.get("pinned_commit") != "3c27eb6234bf91b8ceee9e9071591b31e9b148cb"
            or expected.get("required_patch_sha256") != _sha((root / "host/required.patch").read_bytes())
            or expected.get("dirty_overlay") != _dirty_overlay(runtime)):
        raise ValueError("default shadow distribution mismatch")
    if Path(sys.executable).resolve().is_relative_to(runtime) is False:
        raise ValueError("default interpreter source mismatch")
    sys.path.insert(0, str(shadow))
    return release


def render_default_units(plan):
    core, gateway, program = plan["core_binding"], plan["gateway_config"], plan["program_plan"]
    interpreter = str(Path(core["runtime_root"]) / "bin/python3")
    common = ["Type=simple", "UMask=0077", "NoNewPrivileges=yes", "CapabilityBoundingSet=", "AmbientCapabilities=",
        "PrivateTmp=yes", "ProtectSystem=strict", "ProtectHome=read-only", "RestrictSUIDSGID=yes", "LockPersonality=yes"]
    result = {}
    for role in plan["roles"]:
        name = role["role"]
        lines = ["[Unit]", "Description=Default Hermes " + name]
        if name == "gateway":
            lines += ["Requires=cohermes-default-core.service cohermes-default-ordinary.service", "After=cohermes-default-core.service cohermes-default-ordinary.service"]
        lines += ["", "[Service]", *common, "User=" + role["user"], "Group=" + role["group"],
            "SupplementaryGroups=",
            "Environment=PYTHONDONTWRITEBYTECODE=1", "ReadOnlyPaths=" + str(program["program_root"])]
        if name == "core":
            lines += ["RestrictAddressFamilies=AF_UNIX", "UnsetEnvironment=JOJO_API_KEY OPENAI_API_KEY API_SERVER_KEY WEIXIN_TOKEN GATEWAY_PROXY_KEY",
                "ReadWritePaths=" + str(STATE) + " " + str(SOCKET_ROOT),
                "ExecStart=/usr/bin/env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 " + interpreter + " -I -B -m partner_health_steward.production_core_service --binding " + str(STATE / "core.json")
                + " --head-binding " + str(STATE / "current-head.json") + " --live-binding " + str(STATE / "live.json")]
        elif name == "ordinary":
            lines += ["Environment=HOME=" + str(ORDINARY), "Environment=HERMES_HOME=" + str(ORDINARY),
                "WorkingDirectory=" + str(ORDINARY / "workspace"),
                "InaccessiblePaths=" + str(STATE) + " " + str(SOCKET_ROOT) + " " + str(HOME),
                "ReadWritePaths=" + str(ORDINARY),
                "ExecStart=/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=" + str(ORDINARY)
                + " HERMES_HOME=" + str(ORDINARY) + " PYTHONDONTWRITEBYTECODE=1 SSL_CERT_FILE=${SSL_CERT_FILE} "
                + interpreter + " -I -B -m partner_health_steward.default_runtime --role ordinary --binding " + str(PROGRAM / "ordinary.json")]
        else:
            lines += ["Environment=HOME=/root", "Environment=HERMES_HOME=" + str(HOME),
                "Environment=COHERMES_RELAY_ONLY=1", "InaccessiblePaths=" + str(STATE),
                "ReadWritePaths=" + str(HOME),
                "ExecStart=/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/root HERMES_HOME=" + str(HOME)
                + " COHERMES_RELAY_ONLY=1 PYTHONDONTWRITEBYTECODE=1 SSL_CERT_FILE=${SSL_CERT_FILE} "
                + interpreter + " -I -B -m partner_health_steward.default_runtime --role gateway --binding " + str(HOME / ".ticket128-gateway.json")]
        lines += ["Restart=no", "TimeoutStopSec=30", "", "[Install]", "WantedBy=default.target", ""]
        result[role["unit"]] = "\n".join(lines)
    return result


def provision_default_plan(plan):
    """Install only this fixed plan; caller owns program backup/rollback."""
    if os.geteuid() != 0:
        raise ValueError("default provision requires the root operator")
    plan = copy.deepcopy(plan)
    program, core, gateway = plan["program_plan"], plan["core_binding"], plan["gateway_config"]
    if Path(core["database_path"]) != STATE / "health.sqlite" or Path(program["program_root"]).parent != PROGRAM:
        raise ValueError("invalid default provision target")
    for account in (program["core_identity"], program["ordinary_identity"]):
        _provision_account(account)
    uid, gid = program["core_identity"]["uid"], program["core_identity"]["gid"]
    root = Path(program["program_root"])
    for directory in (PROGRAM.parent, PROGRAM, root):
        _directory(directory, 0, 0, 0o755)
    for key, destination in (("source_release_root", Path(core["release_root"])), ("source_runtime_root", Path(core["runtime_root"]))):
        source = Path(program[key])
        if destination.parent != root:
            _directory(destination.parent, 0, 0, 0o755)
        if not destination.exists():
            shutil.copytree(source, destination, symlinks=False)
        elif _source_manifest(source) != _source_manifest(destination):
            raise ValueError("default immutable program resource drift")
        for path in [destination, *destination.rglob("*")]:
            if path.is_symlink():
                raise ValueError("default program symlink")
            os.chown(path, uid, gid)
            os.chmod(path, 0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    shadow = Path(gateway["shadow_root"])
    if not shadow.exists():
        pinned = Path(program["pinned_hermes_root"])
        _copy_pinned_shadow(pinned, shadow, core["runtime_root"])
        subprocess.run(["git", "apply", "--ignore-space-change", str(Path(core["release_root"]) / "host/required.patch")], cwd=shadow,
            check=True, capture_output=True)
    source_manifest = {"contract": "ticket128-shadow-source-binding-v1", "distribution_digest": core["release_digest"],
        "pinned_commit": "3c27eb6234bf91b8ceee9e9071591b31e9b148cb",
        "required_patch_sha256": _sha((Path(core["release_root"]) / "host/required.patch").read_bytes()),
        "dirty_overlay": _dirty_overlay(core["runtime_root"]),
        "files": _source_manifest(shadow)}
    source_path = Path(gateway["source_manifest_path"])
    if source_path.exists() and _json(source_path) != source_manifest:
        raise ValueError("default shadow manifest drift")
    _write(source_path, _canonical(source_manifest), 0o644)
    sys.path.insert(0, str(shadow))
    import yaml
    from dotenv import dotenv_values
    config_path = HOME / "config.yaml"
    config = yaml.safe_load(config_path.read_text()) if config_path.is_file() else {}
    config = config or {}
    values = dotenv_values(HOME / ".env")
    ordinary_config, ordinary_env = _ordinary_provider_projection(config, values)
    # Resolve both selected provider capabilities before creating authority.
    load_default_health_credential(FirstHopRoute.from_wire(gateway["route"]))
    for directory in (STATE, STATE / "capabilities", STATE / "locks", STATE / "managed-replicas", STATE / "migration-artifacts"):
        _directory(directory, uid, gid, 0o700)
    _directory(SOCKET_ROOT, uid, gid, 0o750)
    # No binding file is placed inside a fresh authority namespace until its
    # strict-empty bootstrap has completed.
    bootstrap = root / "bootstrap-input.json"
    _write(bootstrap, _canonical(plan), 0o644)
    subprocess.run(["setpriv", "--reuid", str(uid), "--regid", str(gid), "--clear-groups",
        str(Path(core["runtime_root"]) / "bin/python3"), "-I", "-B", "-m", "partner_health_steward.default_runtime",
        "--role", "bootstrap", "--binding", str(bootstrap)], check=True, capture_output=True)
    bootstrap.unlink()
    plan["head_binding"] = _json(STATE / "current-head.json")
    _write(STATE / "core.json", _canonical(core), 0o400, uid, gid)
    _write(STATE / "live.json", _canonical(plan["live_binding"]), 0o400, uid, gid)
    ordinary = program["ordinary_identity"]
    for directory in (ORDINARY, ORDINARY / "workspace"):
        _directory(directory, ordinary["uid"], ordinary["gid"], 0o700)
    proxy_path = Path(gateway["proxy_key_path"])
    if not proxy_path.exists():
        _write(proxy_path, uuid.uuid4().hex.encode(), 0o440, 0, ordinary["gid"], exclusive=True)
    ordinary_binding = {key: gateway[key] for key in ("release_root", "runtime_root", "shadow_root", "proxy_key_path", "source_manifest_path")}
    ordinary_binding.update(contract="ticket128-ordinary-worker-binding-v1", workspace=str(ORDINARY / "workspace"))
    _write(PROGRAM / "ordinary.json", _canonical(ordinary_binding), 0o644)
    ordinary_config.update(terminal={"backend": "local", "cwd": str(ORDINARY / "workspace")},
        plugins={"enabled": []}, toolsets=["terminal", "file"])
    _write(ORDINARY / "config.yaml", yaml.safe_dump(ordinary_config).encode(), 0o600, ordinary["uid"], ordinary["gid"])
    # Copy only the ordinary provider's capability. JOJO and Weixin remain in
    # the trusted Gateway, health facilities remain in the Core.
    _write(ORDINARY / ".env", "".join(k + "=" + json.dumps(v) + "\n" for k, v in ordinary_env.items()).encode(),
        0o600, ordinary["uid"], ordinary["gid"])
    config.setdefault("gateway", {}).update(proxy_url=gateway["proxy_url"], multiplex_profiles=False)
    config["multiplex_profiles"] = False
    config["quick_commands"] = {}
    config.setdefault("compression", {}).update(enabled=False)
    config["plugins"] = {"enabled": ["health-weixin"]}
    config.setdefault("platforms", {})["weixin"] = {"enabled": False}
    _write(config_path, yaml.safe_dump(config, allow_unicode=True).encode())
    plugin = HOME / "plugins/health-weixin"
    if plugin.exists():
        shutil.rmtree(plugin)
    shutil.copytree(Path(core["release_root"]) / "plugin/health-weixin", plugin)
    _write(HOME / ".ticket128-gateway.json", _canonical(gateway))
    _write(HOME / ".health-release.json", _canonical({"release_digest": core["release_digest"], "resource_scope": "non-diagnostic"}))
    for role in plan["roles"]:
        dropins = Path(role["unit_path"] + ".d")
        if dropins.is_symlink():
            raise ValueError("default unit drop-in symlink")
        if dropins.exists():
            shutil.rmtree(dropins)
        _write(role["unit_path"], render_default_units(plan)[role["unit"]], 0o644)
    return plan


def _ordinary_process_environment():
    # A root user manager can retain credentials, agent sockets, secret-store
    # locations or provider overrides under arbitrary names. Start with only
    # process presentation and public CA settings, then load this role's own
    # projected provider file. An inherited credential is never a fallback.
    retained = {name: os.environ[name] for name in (
        "LANG", "LC_ALL", "LC_CTYPE", "TERM", "SSL_CERT_FILE", "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    ) if name in os.environ}
    os.environ.clear()
    os.environ.update(retained)
    os.environ.update(HOME=str(ORDINARY), HERMES_HOME=str(ORDINARY),
        PATH="/usr/bin:/bin", PYTHONDONTWRITEBYTECODE="1")


async def _ordinary_main(binding):
    _ordinary_process_environment()
    _verify_sources(binding)
    from dotenv import load_dotenv
    load_dotenv(ORDINARY / ".env", override=True)
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    os.environ.pop("COHERMES_RELAY_ONLY", None)
    key = Path(binding["proxy_key_path"]).read_text()
    config = PlatformConfig(enabled=True, extra={"host": "127.0.0.1", "port": 8642, "key": key})
    adapter = APIServerAdapter(config)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    try:
        if not await adapter.connect():
            raise RuntimeError("ordinary worker connection failed")
        await stop.wait()
    finally:
        await adapter.disconnect()


def _pin_default_gateway_environment(binding):
    # dotenv is an operator credential input, not a profile/launch selector.
    # Pin these after reading it, before importing any Hermes config loader.
    os.environ.update(HOME="/root", HERMES_HOME=str(HOME),
        HERMES_PROFILE="default", HERMES_PROFILE_NAME="default",
        HERMES_CONFIG=str(HOME / "config.yaml"), HERMES_ENV=str(HOME / ".env"),
        GATEWAY_MULTIPLEX_PROFILES="0", COHERMES_RELAY_ONLY="1",
        GATEWAY_PROXY_URL=binding["proxy_url"],
        GATEWAY_PROXY_KEY=Path(binding["proxy_key_path"]).read_text(),
        HEALTH_WEIXIN_ALLOWED_USERS=binding["admission_policy"]["owner_sender_id"])


async def _gateway_main(binding):
    release = _verify_sources(binding)
    if os.environ.get("COHERMES_RELAY_ONLY") != "1":
        raise ValueError("default Gateway requires relay-only mode")
    from dotenv import load_dotenv
    load_dotenv(HOME / ".env", override=True)
    _pin_default_gateway_environment(binding)
    from gateway.platforms.weixin import load_weixin_account
    account = load_weixin_account(str(HOME), binding["admission_policy"]["partner_id"])
    if type(account) is not dict or not account.get("token"):
        raise ValueError("default Weixin account is unavailable")
    from .host_contract import arm_default_live_entry
    from hermes_cli.plugins import get_plugin_manager, discover_plugins
    from gateway.platform_registry import platform_registry
    from gateway.config import Platform, PlatformConfig
    from gateway.run import load_gateway_config_for_runner, start_gateway
    get_plugin_manager()
    discover_plugins()
    entry = platform_registry.get("health_weixin")
    arm_default_live_entry(release, binding, entry)
    config = load_gateway_config_for_runner()
    extra = {key: copy.deepcopy(binding[key]) for key in ("admission_policy", "core_port_endpoint", "initialization_template", "weixin_transport_binding")}
    # Only this verified default composition installs the periodic tick.
    extra["_periodic_current_wake"] = True
    extra["nondiagnostic_model_binding"] = {"route": copy.deepcopy(binding["route"]),
        "budget": copy.deepcopy(binding["budget"]),
        "credential_provider": lambda: load_default_health_credential(FirstHopRoute.from_wire(binding["route"]))}
    if "technical_acceptance" in binding:
        extra["technical_acceptance"] = copy.deepcopy(binding["technical_acceptance"])
    config.platforms[Platform("health_weixin")] = PlatformConfig(enabled=True, token=account["token"], extra=extra)
    for platform in tuple(config.platforms):
        if getattr(platform, "value", "") != "health_weixin":
            config.platforms[platform].enabled = False
    if await start_gateway(config) is not True:
        raise RuntimeError("default Gateway startup failed")


def _main(argv=None):
    parser = argparse.ArgumentParser(description="Fixed default health deployment role")
    parser.add_argument("--role", choices=("bootstrap", "ordinary", "gateway"), required=True)
    parser.add_argument("--binding", required=True)
    args = parser.parse_args(argv)
    path = Path(args.binding)
    details = path.lstat()
    if (path.is_symlink() or not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
            or details.st_uid != 0 or stat.S_IMODE(details.st_mode) & 0o022):
        raise ValueError("unsafe default role binding")
    if args.role == "gateway" and (path != HOME / ".ticket128-gateway.json" or stat.S_IMODE(details.st_mode) != 0o600):
        raise ValueError("invalid default Gateway binding location")
    if args.role == "ordinary" and path != PROGRAM / "ordinary.json":
        raise ValueError("invalid ordinary worker binding location")
    binding = _json(args.binding)
    if args.role == "bootstrap":
        _bootstrap_core(binding)
    elif args.role == "ordinary":
        asyncio.run(_ordinary_main(binding))
    else:
        asyncio.run(_gateway_main(binding))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

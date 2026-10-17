"""Release-bound business wiring over the existing three CorePort kinds."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from .admission import AdmissionPolicy, RawWeixinMessage
from .authority import AuthorityValidationError
from .contract import ProtocolViolation, Response
from .coordination import CoarseMessageRouter, DailySkillRuntime, DAILY_HEALTH_SKILL_NAMES
from .initialization import HealthInitRuntime, OwnerInitialization
from .plugin import HealthPlugin
from .probe import ProbeState


_INTERFACE = "health-entry-v1"
_HEADERS = frozenset({
    "causal_id", "channel", "partner_id", "sender_id", "conversation_id",
    "chat_type", "entrypoint", "message_id", "protocol_timestamp", "received_at",
    "native_cursor",
})
_MESSAGE = _HEADERS | {"generation", "requested_capability", "body"}
_CORE_OPTIONS = frozenset({
    "owner_settings_clock", "route_configuration_provider", "status_fact_authority",
    "business_status_clock", "model_authority_digest", "knowledge_releases",
    "knowledge_valid_at", "knowledge_clock", "approved_claims", "approved_templates",
    "safety_diagnostic_assets", "acceptance_evidence_provider",
})


def _mapping(value: object, fields: set | frozenset) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise ProtocolViolation("invalid health entry payload")
    return value


class LiveHealthCoreOperations:
    """A closed operation table; the Plugin remains the business authority."""

    def __init__(self, plugin, *, current_generation, wake_current=None):
        if type(plugin) is not HealthPlugin or not callable(current_generation):
            raise TypeError("invalid health entry dependencies")
        if wake_current is not None and not callable(wake_current):
            raise TypeError("invalid health entry wake callback")
        self._plugin = plugin
        self._generation = current_generation
        self._wake = wake_current

    def dispatch(self, kind, payload):
        selector = "operation" if kind == "command" else "projection"
        if kind not in {"command", "managed-read"}:
            raise ProtocolViolation("unsupported health entry kind")
        value = _mapping(payload, {"interface", selector, "payload"})
        if value["interface"] != _INTERFACE or type(value["payload"]) is not dict:
            raise ProtocolViolation("invalid health entry interface")
        name, data = value[selector], value["payload"]
        if type(name) is not str:
            raise ProtocolViolation("invalid health entry operation")
        if kind == "managed-read":
            return self._read(name, data)
        return self._command(name, data)

    def _read(self, name, data):
        plugin = self._plugin
        if name == "health-entry-delivery":
            intent_id = _mapping(data, {"intent_id"})["intent_id"]
            return {"delivery": plugin.live_delivery_status(intent_id, peer_id="plugin")}
        if name == "health-entry-preflight":
            headers = _mapping(data, {"headers"})["headers"]
            _mapping(headers, _HEADERS)
            try:
                generation = self._generation()
                if type(generation) is not int or generation < 1:
                    raise ValueError("invalid current generation")
            except Exception:
                return {"allowed": False, "current_generation": None,
                        "initialization_phase": "cannot-confirm",
                        "reason_code": "current-head-unavailable"}
            return plugin.live_entry_preflight(headers, generation=generation, peer_id="plugin")
        if name == "health-entry-disclosure":
            workflow = _mapping(data, {"workflow_id"})["workflow_id"]
            return plugin.live_entry_disclosure(workflow, peer_id="plugin")
        if name == "health-entry-cursor-directive":
            source = _mapping(data, {"source_causal_id"})["source_causal_id"]
            directive = plugin.native_cursor_directive(source, peer_id="plugin")
            return {"directive": None if directive is None else asdict(directive)}
        _mapping(data, set())
        if name == "health-entry-initialization":
            return {"initialization": plugin.initialization_status(peer_id="plugin").to_storage()}
        if name == "health-entry-native-cursor":
            return {"native_cursor": plugin.live_entry_native_cursor(peer_id="plugin")}
        if name == "health-entry-business-status":
            result = plugin.business_status(peer_id="plugin")
            return {"business_status": {"projection": result.projection.to_storage(),
                    "transition": None if result.transition is None else result.transition.to_storage()}}
        raise ProtocolViolation("unsupported health entry projection")

    def _command(self, name, data):
        plugin = self._plugin
        if name == "delivery-bind":
            reference = _mapping(data, {"binding"})["binding"]
            return plugin.bind_live_delivery(reference, peer_id="plugin")
        if name == "receive-weixin":
            wire = _mapping(_mapping(data, {"message"})["message"], _MESSAGE)
            message = RawWeixinMessage(**wire)
            return {"response": plugin.live_entry_receive_weixin(message, peer_id="plugin").to_wire()}
        if name in {"initialization-disclosure", "initialization-consent"}:
            initialization = OwnerInitialization.from_storage(
                _mapping(data, {"initialization"})["initialization"])
            if name == "initialization-disclosure":
                disclosure = plugin.form_initialization_disclosure(initialization, peer_id="plugin")
                return {"disclosure": disclosure.to_storage()}
            response = plugin.prepare_initialization(initialization, peer_id="plugin")
        elif name == "native-cursor-result":
            _mapping(data, {"source_causal_id", "status"})
            directive = plugin.native_cursor_directive(data["source_causal_id"], peer_id="plugin")
            if directive is None:
                response = Response("unavailable", reason_code="native-cursor-directive-unavailable")
            else:
                response = plugin.record_native_cursor_result(
                    directive, status=data["status"], peer_id="plugin")
        else:
            _mapping(data, set())
            if name == "initialization-commit":
                response = plugin.commit_initialization(peer_id="plugin")
            elif name == "initialization-finalize":
                response = plugin.finalize_initialization(peer_id="plugin")
            elif name == "wake-current":
                # Scheduling belongs to the existing runtime. No timer or
                # recovery replay is invented when no current task is due.
                if self._wake is not None:
                    response = self._wake()
                    if type(response) is not Response:
                        raise ProtocolViolation("invalid current wake result")
                else:
                    report = plugin.probe()
                    response = Response("accepted" if report.state is ProbeState.HEALTHY else "unavailable",
                                        reason_code=report.reason_code)
            else:
                raise ProtocolViolation("unsupported health entry operation")
        return {"response": response.to_wire()}


class LiveHealthRuntime:
    """Typed dependencies whose seven assets must belong to this release."""

    def __init__(self, admission_policy, health_init_runtime, coarse_router,
                 daily_skill_runtime, *, asset_paths, core_options=None):
        if (type(admission_policy) is not AdmissionPolicy
                or type(health_init_runtime) is not HealthInitRuntime
                or type(coarse_router) is not CoarseMessageRouter
                or type(daily_skill_runtime) is not DailySkillRuntime):
            raise TypeError("invalid live health runtime")
        names = {"health-init", *DAILY_HEALTH_SKILL_NAMES}
        if type(asset_paths) is not dict or set(asset_paths) != names:
            raise ValueError("incomplete live health assets")
        paths = {}
        for name, relative in asset_paths.items():
            if type(relative) is not str or "\\" in relative:
                raise ValueError("invalid live health asset path")
            path = PurePosixPath(relative)
            if (path.is_absolute() or not path.parts or any(p in {"", ".", ".."} for p in relative.split("/"))):
                raise ValueError("invalid live health asset path")
            paths[name] = path.as_posix()
        if core_options is None:
            core_options = {}
        if type(core_options) is not dict or not set(core_options).issubset(_CORE_OPTIONS):
            raise ValueError("unsupported live health core dependency")
        self._policy = admission_policy
        self._init = health_init_runtime
        self._router = coarse_router
        self._daily = daily_skill_runtime
        self._paths = paths
        self._options = dict(core_options)

    def validate_release(self, root, release):
        if type(release) is not dict or release.get("state") != "current":
            raise ValueError("live health release is not current")
        root = Path(root)
        assets = {"health-init": self._init.asset,
                  **{asset.canonical_name: asset for asset in self._daily.bundle.assets}}
        if set(assets) != set(self._paths):
            raise ValueError("live health assets do not match runtime")
        for name, relative in self._paths.items():
            path = root
            for part in PurePosixPath(relative).parts:
                path = path / part
                if path.is_symlink():
                    raise ValueError("live health asset is a symlink")
            if not path.is_file():
                raise ValueError("live health asset is unavailable")
            content = path.read_bytes()
            if "sha256:" + hashlib.sha256(content).hexdigest() != assets[name].asset_digest:
                raise ValueError("live health asset digest drift")
            text = content.decode("utf-8").lower()
            markers = {line.strip() for line in text.splitlines()}
            if (not text.strip() or "staged-only" in text or "runtime-unavailable" in text
                    or {"status: staged", "availability: unavailable"} & markers):
                raise ValueError("live health asset is staged")

    def core_dependencies(self):
        return {**self._options, "admission_policy": self._policy,
                "health_init_verifier": self._init.verifier,
                "health_init_asset": self._init.asset,
                "daily_skill_verifier": self._daily.verifier,
                "daily_skill_bundle": self._daily.bundle}

    def plugin(self, core):
        return HealthPlugin(core, admission_policy=self._policy,
                            health_init_runtime=self._init, coarse_router=self._router,
                            daily_skill_runtime=self._daily)

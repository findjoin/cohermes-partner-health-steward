"""The release-owned Hermes platform boundary for Ticket 118.

This module is copied byte-for-byte into the verifier's temporary Hermes home.
It registers exactly one platform and delegates all health work through the
three private CorePort operations owned by :mod:`host_contract`.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping

from partner_health_steward.host_contract import (
    _CorePortClient,
    _HostVerificationFailure,
    _is_current_process_activation,
    _require_mapping,
)


# This is deliberately an independent release artifact.  Applying it to the
# fixed upstream checkout makes the legacy/native gateway paths unavailable to
# the health release, while the platform registry remains the only selection
# point for the current health entry.
HERMES_REQUIRED_PATCH_BYTES = (
    b'diff --git a/gateway/run.py b/gateway/run.py\n'
    b'--- a/gateway/run.py\n'
    b'+++ b/gateway/run.py\n'
    b'@@ -13600,6 +13600,11 @@\n'
    b'         Checks the platform_registry first (plugin adapters), then falls\n'
    b'         through to the built-in if/elif chain for core platforms.\n'
    b'         """\n'
    b'+        # The health release never permits legacy or native health paths.\n'
    b'+        if getattr(platform, "value", None) in {\n'
    b'+            "weixin", "medical", "health-autonomy", "health-guard"\n'
    b'+        }:\n'
    b'+            return None\n'
    b'         if hasattr(config, "extra") and isinstance(config.extra, dict):\n'
    b'             config.extra.setdefault(\n'
    b'                 "group_sessions_per_user",\n'
    b'@@ -14216,6 +14221,9 @@\n'
    b'         6. Run agent conversation\n'
    b'         7. Return response\n'
    b'         """\n'
    b'+        if os.environ.get("COHERMES_RELAY_ONLY") == "1":\n'
    b'+            if bool(getattr(event, "internal", False)) or (event.text or "").lstrip().startswith("/"):\n'
    b'+                return "Relay commands disabled."\n'
    b'         source = event.source\n'
    b' \n'
    b'         # \xf0\x9f\x94\xb4 Cross-session leak guard. This handler runs inside a per-message\n'
    b'@@ -16483,7 +16491,7 @@\n'
    b'         #    by 30-50% on code/JSON-heavy sessions, but that just\n'
    b'         #    means hygiene fires a bit early \xe2\x80\x94 safe and harmless.\n'
    b'         # -----------------------------------------------------------------\n'
    b'-        if history and len(history) >= 4:\n'
    b'+        if history and len(history) >= 4 and os.environ.get("COHERMES_RELAY_ONLY") != "1":\n'
    b'             from agent.model_metadata import (\n'
    b'                 estimate_messages_tokens_rough,\n'
    b'                 get_model_context_length_async,\n'
    b'@@ -23489,6 +23497,11 @@\n'
    b'         Checks GATEWAY_PROXY_URL env var first (convenient for Docker),\n'
    b'         then ``gateway.proxy_url`` in config.yaml.\n'
    b'         """\n'
    b'+        if os.environ.get("COHERMES_RELAY_ONLY") == "1":\n'
    b'+            url = os.environ.get("GATEWAY_PROXY_URL", "")\n'
    b'+            if url != "http://127.0.0.1:8642":\n'
    b'+                raise RuntimeError("relay-only Gateway proxy is unavailable")\n'
    b'+            return url\n'
    b'         url = os.getenv("GATEWAY_PROXY_URL", "").strip()\n'
    b'         if url:\n'
    b'             return url.rstrip("/")\n'
    b'@@ -26643,7 +26656,7 @@\n'
    b'             runner._draining or runner._external_drain_active\n'
    b'         )\n'
    b'     cron_thread = threading.Thread(\n'
    b'-        target=cron_provider.start,\n'
    b'+        target=(lambda *_args, **_kwargs: cron_stop.wait()) if os.environ.get("COHERMES_RELAY_ONLY") == "1" else cron_provider.start,\n'
    b'         args=(cron_stop,),\n'
    b'         kwargs=cron_start_kwargs,\n'
    b'         daemon=True,\n'
    b'@@ -26655,7 +26668,7 @@\n'
    b'     # sweep, curator) \xe2\x80\x94 runs independently of which cron provider is active.\n'
    b'     # Shares cron_stop as the shutdown signal.\n'
    b'     housekeeping_thread = threading.Thread(\n'
    b'-        target=_start_gateway_housekeeping,\n'
    b'+        target=(lambda *_args, **_kwargs: cron_stop.wait()) if os.environ.get("COHERMES_RELAY_ONLY") == "1" else _start_gateway_housekeeping,\n'
    b'         args=(cron_stop,),\n'
    b'         kwargs={"adapters": runner.adapters, "loop": asyncio.get_running_loop()},\n'
    b'         daemon=True,\n'
    b'diff --git a/run_agent.py b/run_agent.py\n'
    b'--- a/run_agent.py\n'
    b'+++ b/run_agent.py\n'
    b'@@ -508,6 +508,8 @@\n'
    b'         requested_provider: str = None,\n'
    b'     ):\n'
    b'         """Forwarder \xe2\x80\x94 see ``agent.agent_init.init_agent``."""\n'
    b'+        if os.environ.get("COHERMES_RELAY_ONLY") == "1":\n'
    b'+            raise RuntimeError("relay-only Gateway cannot construct AIAgent")\n'
    b'         if tool_delay is not None:\n'
    b'             warnings.warn(\n'
    b'                 "tool_delay is deprecated and ignored; sequential tool calls "\n'
)

NATIVE_HEALTH_DISABLED_ASSERTION_BYTES = (
    b'{"contract":"native-health-disabled-v1","entry":"health_weixin",'
    b'"status":"disabled-before-native","version":"1"}\n'
)


class _ActivationState:
    """One registration's in-process activation state; never durable."""

    def __init__(self) -> None:
        self._armed = False
        self._active = False
        self._proof: str | None = None

    def arm(self, capability: object, proof: object) -> None:
        if not _is_current_process_activation(capability, proof):
            raise _HostVerificationFailure("health-activation-invalid")
        self._armed = True
        self._active = False
        self._proof = proof

    def can_create_adapter(self) -> bool:
        return self._armed or self._active

    def activate(self, capability: object, proof: object) -> None:
        if (
            not self._armed
            or self._proof != proof
            or not _is_current_process_activation(capability, proof)
        ):
            raise _HostVerificationFailure("health-activation-unproven")
        self._active = True

    def revoke(self) -> None:
        self._armed = False
        self._active = False
        self._proof = None


class _HealthWeixinAdapter:
    """Minimal platform adapter used by the real pinned Gateway lifecycle."""

    def __init__(self, config: object, activation: _ActivationState) -> None:
        extra = getattr(config, "extra", None)
        if type(extra) is not dict:
            raise _HostVerificationFailure("health-config-invalid")
        self._registry = extra.get("registry")
        self._effect_adapter = extra.get("effect_adapter")
        self._client = _CorePortClient(extra.get("core_port_endpoint"))
        self._activation = activation
        self._activation_capability = extra.get("activation_capability")
        self._activation_proof = extra.get("activation_proof")

    def _disable_current_entry(self) -> None:
        self._activation.revoke()
        unregister = getattr(self._registry, "unregister", None)
        if callable(unregister):
            unregister("health_weixin")

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        del is_reconnect
        try:
            self._activation.activate(
                self._activation_capability, self._activation_proof
            )
            self._client.request(
                "command", {"operation": "health-runtime-probe"}
            )
            self._client.request(
                "managed-read", {"projection": "health-runtime"}
            )
            claim_response = self._client.request(
                "controlled-effect",
                {"phase": "claim"},
                request_id="ticket118-controlled-effect-claim",
            )
            claim = _require_mapping(
                claim_response["payload"],
                {"intent", "grant", "current_authority"},
                "effect-claim",
            )
            intent = _require_mapping(
                claim["intent"],
                {"effect_id", "intent_digest", "effect_kind", "authority"},
                "effect-intent",
            )
            authority = _require_mapping(
                intent["authority"],
                {"source", "generation", "writer_fence"},
                "effect-authority",
            )
            grant = _require_mapping(
                claim["grant"],
                {
                    "session_id",
                    "lease_id",
                    "effect_id",
                    "intent_digest",
                    "generation",
                    "writer_fence",
                },
                "effect-grant",
            )
            current = _require_mapping(
                claim["current_authority"],
                {"generation", "writer_fence"},
                "current-authority",
            )
            if (
                authority.get("source") != "core"
                or authority.get("generation") != current.get("generation")
                or authority.get("writer_fence") != current.get("writer_fence")
                or intent.get("effect_kind") != "model-work"
                or grant.get("effect_id") != intent.get("effect_id")
                or grant.get("intent_digest") != intent.get("intent_digest")
                or grant.get("generation") != current.get("generation")
                or grant.get("writer_fence") != current.get("writer_fence")
            ):
                raise _HostVerificationFailure("effect-authority-mismatch")

            execute = getattr(self._effect_adapter, "execute", None)
            if not callable(execute):
                raise _HostVerificationFailure("effect-adapter-missing")
            result = execute(copy.deepcopy(intent))
            if not isinstance(result, Mapping):
                raise _HostVerificationFailure("effect-result-invalid")
            terminal: dict[str, object] = {
                key: grant[key]
                for key in (
                    "session_id",
                    "lease_id",
                    "effect_id",
                    "intent_digest",
                    "generation",
                    "writer_fence",
                )
            }
            for key in ("status", "terminal", "result_ref"):
                if key in result:
                    terminal[key] = copy.deepcopy(result[key])
            terminal_response = self._client.request(
                "controlled-effect",
                {"phase": "terminal", "terminal": terminal},
                request_id="ticket118-controlled-effect-terminal",
            )
            if terminal_response["payload"].get("terminal_accepted") is not True:
                raise _HostVerificationFailure("effect-terminal-rejected")
            return True
        except Exception:
            self._disable_current_entry()
            raise

    async def disconnect(self) -> bool:
        self._activation.revoke()
        return True


def register(ctx: object) -> None:
    """Register the sole current health entry with Hermes."""

    register_platform = getattr(ctx, "register_platform", None)
    if not callable(register_platform):
        raise RuntimeError("Hermes PluginContext lacks platform registration")
    activation = _ActivationState()

    def adapter_factory(config: object) -> object:
        extra = getattr(config, "extra", None)
        if type(extra) is dict and "admission_policy" in extra:
            # The actual registry checks this before constructing an adapter;
            # retain it here as well for callers holding the factory directly.
            # Only the existing verified-release bootstrap can arm this state.
            if not activation.can_create_adapter():
                raise _HostVerificationFailure("health-activation-unproven")
            from .live_weixin import LiveHealthWeixinAdapter

            return LiveHealthWeixinAdapter(config)
        return _HealthWeixinAdapter(config, activation)

    def arm(capability: object, proof: object) -> None:
        activation.arm(capability, proof)

    setattr(adapter_factory, "_ticket118_arm", arm)

    def check_fn() -> bool:
        return activation.can_create_adapter()

    setattr(check_fn, "_ticket118_arm", arm)
    register_platform(
        name="health_weixin",
        label="Health Weixin",
        adapter_factory=adapter_factory,
        check_fn=check_fn,
        allowed_users_env="HEALTH_WEIXIN_ALLOWED_USERS",
    )

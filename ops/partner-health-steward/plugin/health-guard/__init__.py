"""Health guard plugin for the isolated partner Hermes profile."""

from .guard import (
    health_safe_command,
    install_gateway_runtime_guard,
    pre_gateway_dispatch,
    pre_llm_call,
    pre_tool_call,
    transform_llm_output,
)


def register(ctx):
    """Register one deterministic slash command and four narrow safety hooks."""
    # Hermes swallows plugin registration errors and keeps the Gateway alive.
    # Deployment therefore also uses an ExecStartPre source/config verifier and
    # a real active-session acceptance test; this call installs the runtime part.
    install_gateway_runtime_guard()
    ctx.register_command(
        "health-guard-safe",
        handler=health_safe_command,
        description="Deterministic partner health safety response",
        args_hint="<internal-action>",
    )
    ctx.register_hook("pre_gateway_dispatch", pre_gateway_dispatch)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("transform_llm_output", transform_llm_output)

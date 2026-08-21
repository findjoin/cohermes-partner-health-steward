"""Partner Hermes plugin for health ingress and the two fixed sidecar Jobs.

The plugin exposes only two model tools.  The scheduler's pre-run script
verifies the persisted Job against the fixed contract before the fresh agent
session starts; ordinary chat cannot use these tools to reach the sidecar.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from tools.registry import tool_error, tool_result


DAILY_TOOL = "health_daily_review"
DISPATCH_TOOL = "health_dispatch_due_tasks"
PROJECTION_PATH = "/var/lib/health-sidecar/projection/memory.json"


def _import_hermes_jobs() -> Any:
    """Import the partner module from the configured, deployed source root."""
    source_root = os.environ.get("HEALTH_STEWARD_SOURCE_ROOT", "").strip()
    if not source_root:
        raise RuntimeError("health-source-root-unconfigured")
    source_path = Path(source_root).expanduser().resolve()
    if not source_path.is_dir():
        raise RuntimeError("health-source-root-unavailable")
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))
    import hermes_jobs

    return hermes_jobs


def _runtime_for_capability(role: str, capability: str):
    jobs = _import_hermes_jobs()
    if not jobs.verify_job_capability(capability, role):
        raise RuntimeError("fixed-job-capability-invalid")
    runtime = jobs.load_runtime_from_environment()
    return runtime, jobs.issue_sidecar_job_authorization(
        role, runtime.subject, capability, issued_utc=runtime.current_utc()
    )


def _build_partner_weixin_adapter(ctx: Any, config: Any):
    source_root = os.environ.get("HEALTH_STEWARD_SOURCE_ROOT", "").strip()
    if not source_root:
        raise RuntimeError("health-source-root-unconfigured")
    source_path = Path(source_root).expanduser().resolve()
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))

    from sidecar.adapter import PartnerHealthAdapter
    from sidecar.receipt_signer import ReceiptSignerClient
    from sidecar.weixin_delivery import (
        HermesWeixinTransport,
        WeixinHealthChannel,
    )
    from export_attachments import PrivateJsonExportStore
    from health_turn import HealthSourceCatalog, HealthTurnHandler
    from health_turn_answer import PinnedHealthTurnResponder
    from owner_controls import PartnerOwnerControlHandler, PinnedHealthViewAnalyzer
    from weixin_ingress import (
        HealthModelConfig,
        HermesFreshHealthClassifier,
        PartnerWeixinIngressCoordinator,
    )
    from .weixin_adapter import PartnerHealthWeixinAdapter

    socket_path = os.environ.get("HEALTH_STEWARD_SOCKET", "").strip()
    signer_socket = os.environ.get(
        "HEALTH_STEWARD_RECEIPT_SIGNER_SOCKET", ""
    ).strip()
    model_config_path = os.environ.get(
        "HEALTH_STEWARD_HEALTH_MODEL_CONFIG", ""
    ).strip()
    expected_owner = os.environ.get(
        "HEALTH_STEWARD_EXPECTED_OWNER_SENDER_ID", ""
    ).strip()
    expected_viewer = os.environ.get(
        "HEALTH_STEWARD_EXPECTED_VIEWER_SENDER_ID", ""
    ).strip()
    source_catalog_path = os.environ.get(
        "HEALTH_STEWARD_HEALTH_SOURCE_CATALOG", ""
    ).strip()
    hermes_source_root = os.environ.get(
        "HEALTH_STEWARD_HERMES_SOURCE_ROOT", ""
    ).strip()
    accepted_hermes_version = os.environ.get(
        "HEALTH_STEWARD_ACCEPTED_HERMES_VERSION", ""
    ).strip()
    delivery_ledger_path = os.environ.get(
        "HEALTH_STEWARD_DELIVERY_LEDGER_PATH", ""
    ).strip()
    attestation_path = os.environ.get(
        "HEALTH_STEWARD_HEALTH_MODEL_ATTESTATION_PATH", ""
    ).strip()
    export_tmpdir = os.environ.get("HEALTH_STEWARD_EXPORT_TMPDIR", "").strip()
    if not all(
        (
            socket_path,
            signer_socket,
            model_config_path,
            expected_owner,
            expected_viewer,
            source_catalog_path,
            hermes_source_root,
            accepted_hermes_version,
            delivery_ledger_path,
            attestation_path,
            export_tmpdir,
        )
    ):
        raise RuntimeError("health-weixin-ingress-unconfigured")
    health_model_config, config_digest = HealthModelConfig.snapshot_from_file(
        model_config_path
    )
    if health_model_config.auth_profile != ctx.profile_name:
        raise RuntimeError("health-model-auth-profile-mismatch")
    sidecar = PartnerHealthAdapter(socket_path)
    signer = ReceiptSignerClient(signer_socket)
    subject = os.environ.get("HEALTH_STEWARD_SUBJECT", "profile").strip() or "profile"
    coordinator = PartnerWeixinIngressCoordinator(
        sidecar,
        signer,
        HermesFreshHealthClassifier(ctx.llm, health_model_config),
        expected_owner_sender_id=expected_owner,
        subject=subject,
    )
    partner_extra = dict(getattr(config, "extra", {}) or {})
    partner_extra.update(
        {
            "dm_policy": "allowlist",
            "allow_from": [expected_owner, expected_viewer],
        }
    )
    partner_config = replace(config, extra=partner_extra)
    adapter = PartnerHealthWeixinAdapter(
        partner_config,
        coordinator,
        profile_name="partner",
        health_retry_enabled=True,
    )
    token = str(getattr(adapter, "_token", "") or "").strip()
    base_url = str(getattr(adapter, "_base_url", "") or "").strip()
    cdn_base_url = str(
        getattr(adapter, "_cdn_base_url", "") or ""
    ).strip()
    if not token or not base_url or not cdn_base_url:
        raise RuntimeError("health-weixin-delivery-unconfigured")
    transport = HermesWeixinTransport.from_hermes_source(
        hermes_source_root,
        token=token,
        base_url=base_url,
        cdn_base_url=cdn_base_url,
    )
    channel = WeixinHealthChannel(
        delivery_ledger_path,
        transport,
        accepted_hermes_version=accepted_hermes_version,
        audit_sink=sidecar,
        profile_subject=subject,
    )
    export_store = PrivateJsonExportStore(
        export_tmpdir,
        # Only non-Linux isolated tests lack a Linux tmpfs.  Linux always keeps
        # the component's strict mount, owner, and permission verification.
        tmpfs_verifier=(
            (lambda _directory: None)
            if (
                not sys.platform.startswith("linux")
                and os.environ.get("HEALTH_STEWARD_TEST_MODE") == "1"
            )
            else None
        ),
    )
    adapter.bind_owner_control_handler(
        PartnerOwnerControlHandler(
            sidecar,
            signer,
            channel,
            expected_owner_sender_id=expected_owner,
            expected_viewer_sender_id=expected_viewer,
            subject=subject,
            analyzer=PinnedHealthViewAnalyzer(ctx.llm, health_model_config),
            export_store=export_store,
        )
    )
    adapter.bind_health_turn_handler(
        HealthTurnHandler(
            context_loader=coordinator,
            source_reader=sidecar,
            responder=PinnedHealthTurnResponder(
                ctx.llm,
                health_model_config,
            ),
            channel=channel,
            source_catalog=HealthSourceCatalog.from_file(
                source_catalog_path
            ),
        )
    )
    _write_health_model_attestation(
        model_config_path,
        attestation_path,
        health_model_config,
        config_digest=config_digest,
    )
    return adapter


def _write_health_model_attestation(
    config_path: str,
    destination: str,
    config: Any,
    *,
    config_digest: str | None = None,
) -> None:
    """Atomically persist the content-free health-model recipient snapshot."""
    source = Path(config_path).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    if config_digest is None:
        try:
            config_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        except OSError as exc:
            raise RuntimeError("health-model-attestation-source-unavailable") from exc
    if (
        not isinstance(config_digest, str)
        or len(config_digest) != 64
        or any(character not in "0123456789abcdef" for character in config_digest)
    ):
        raise RuntimeError("health-model-attestation-digest-invalid")
    payload = {
        "attestation_schema_version": 1,
        "provider": config.provider,
        "endpoint": config.endpoint,
        "model_id": config.model_id,
        "privacy_mode": config.privacy_mode,
        "auth_profile": config.auth_profile,
        "config_sha256": config_digest,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, target)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        try:
            temporary.unlink()
        except OSError:
            pass


def _handle_daily_review(
    args: dict[str, Any],
    **_: Any,
) -> str:
    capability = args.get("capability") if isinstance(args, dict) else None
    if not isinstance(capability, str) or not capability.strip():
        return tool_error("daily-capability-required")
    try:
        runtime, job_authorization = _runtime_for_capability(
            "daily_profile_review", capability
        )
        # The sidecar owns the current snapshot, direct pinned model call and
        # durable retry.  The outer Cron agent therefore never receives
        # health content and cannot turn a provider fallback into a health
        # decision.
        result = runtime.execute_daily_review(job_authorization)
        return tool_result(result)
    except Exception:
        return tool_error("daily-review-sidecar-unavailable")


def _handle_dispatch(args: dict[str, Any], **_: Any) -> str:
    capability = args.get("capability") if isinstance(args, dict) else None
    if not isinstance(capability, str) or not capability.strip():
        return tool_error("dispatch-capability-required")
    try:
        runtime, job_authorization = _runtime_for_capability(
            "due_task_dispatch", capability
        )
        result = runtime.dispatch(job_authorization)
        return tool_result(result)
    except Exception:
        return tool_error("dispatch-sidecar-unavailable")


def _memory_projection_context(**kwargs: Any) -> dict[str, str] | None:
    if str(kwargs.get("session_id", "")).startswith("cron_"):
        return None
    raw_path = os.environ.get("HEALTH_STEWARD_MEMORY_PROJECTION_PATH", "").strip()
    if not raw_path:
        return None
    path = Path(raw_path).expanduser().resolve()
    if os.environ.get("HEALTH_STEWARD_TEST_MODE") != "1" and str(path) != PROJECTION_PATH:
        return None
    try:
        if path.stat().st_size > 8192:
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    subject = os.environ.get("HEALTH_STEWARD_SUBJECT", "profile").strip()
    projection = document.get(subject) if isinstance(document, dict) else None
    if not isinstance(projection, dict) or set(projection) != {
        "schema_version",
        "archive_pointer",
        "interaction_preferences",
        "proactive_contact",
    }:
        return None
    expected_pointer = f"health-sidecar://profile/{subject}"
    preferences = projection.get("interaction_preferences")
    proactive = projection.get("proactive_contact")
    if (
        projection.get("schema_version") != 1
        or projection.get("archive_pointer") != expected_pointer
        or not isinstance(preferences, list)
        or len(preferences) > 2
        or not all(
            isinstance(item, str) and item.strip() and len(item.strip()) <= 300
            for item in preferences
        )
        or not isinstance(proactive, dict)
        or set(proactive) != {"paused", "pause_until_utc"}
        or not isinstance(proactive.get("paused"), bool)
        or (
            proactive.get("pause_until_utc") is not None
            and not isinstance(proactive.get("pause_until_utc"), str)
        )
    ):
        return None
    payload = json.dumps(
        projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return {
        "context": (
            "<health-memory-projection source=\"sidecar-read-only\">"
            f"{payload}</health-memory-projection>"
        )
    }


def register(ctx: Any) -> None:
    if ctx.profile_name != "partner" and os.environ.get("HEALTH_STEWARD_TEST_MODE") != "1":
        raise RuntimeError("health-steward may only load in the partner profile")

    ctx.register_tool(
        name=DAILY_TOOL,
        toolset="health_steward_daily",
        schema={
            "type": "object",
            "properties": {
                "capability": {
                    "type": "string",
                    "description": "One-time opaque capability from the controlled Cron snapshot.",
                },
            },
            "required": ["capability"],
            "additionalProperties": False,
        },
        handler=lambda args, **kwargs: _handle_daily_review(args, ctx=ctx, **kwargs),
        description=(
            "Run one pinned daily health review through the private sidecar; "
            "the Job supplies no health plan or message text."
        ),
        emoji="🩺",
    )
    ctx.register_tool(
        name=DISPATCH_TOOL,
        toolset="health_steward_dispatch",
        schema={
            "type": "object",
            "properties": {
                "capability": {
                    "type": "string",
                    "description": "Short-lived capability from the controlled snapshot.",
                },
            },
            "required": ["capability"],
            "additionalProperties": False,
        },
        handler=_handle_dispatch,
        description="Run the private sidecar due-task dispatcher; it alone may render/send.",
        emoji="📨",
    )
    ctx.register_hook("pre_llm_call", _memory_projection_context)
    from gateway.platforms.weixin import check_weixin_requirements

    ctx.register_platform(
        name="weixin",
        label="Weixin (partner health ingress)",
        adapter_factory=lambda config: _build_partner_weixin_adapter(ctx, config),
        check_fn=check_weixin_requirements,
        required_env=[
            "HEALTH_STEWARD_SOCKET",
            "HEALTH_STEWARD_RECEIPT_SIGNER_SOCKET",
            "HEALTH_STEWARD_HEALTH_MODEL_CONFIG",
            "HEALTH_STEWARD_HEALTH_SOURCE_CATALOG",
            "HEALTH_STEWARD_EXPECTED_OWNER_SENDER_ID",
            "HEALTH_STEWARD_EXPECTED_VIEWER_SENDER_ID",
            "HEALTH_STEWARD_HERMES_SOURCE_ROOT",
            "HEALTH_STEWARD_ACCEPTED_HERMES_VERSION",
            "HEALTH_STEWARD_DELIVERY_LEDGER_PATH",
            "HEALTH_STEWARD_HEALTH_MODEL_ATTESTATION_PATH",
            "HEALTH_STEWARD_EXPORT_TMPDIR",
        ],
        emoji="💬",
        allowed_users_env="WEIXIN_ALLOWED_USERS",
        allow_all_env="WEIXIN_ALLOW_ALL_USERS",
        max_message_length=2000,
        pii_safe=True,
        platform_hint="Partner Weixin; health writes are handled before batching.",
    )


__all__ = [
    "DAILY_TOOL",
    "DISPATCH_TOOL",
    "_memory_projection_context",
    "register",
]

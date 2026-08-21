"""Hermes plugin entrypoint for partner health autonomy v0.2."""

from __future__ import annotations

import base64
import contextvars
import dataclasses
import hashlib
import hmac
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from .autonomy import (
    ACTIVATION_PREFIX,
    CONTROL_EXACT,
    HealthAutonomyEngine,
    activation_example,
)


logger = logging.getLogger(__name__)
_TEST_MODE_ENV = "HEALTH_AUTONOMY_TEST_MODE"
_RECENT_BINDING_SECONDS = 120.0
_MAX_RECENT_BINDINGS = 128


@dataclasses.dataclass(frozen=True)
class TrustedPrivateTurn:
    platform: str
    user_id: str
    chat_id: str
    thread_id: str
    message_id: str
    reply_to_message_id: str
    text_hash: str
    captured_monotonic: float


_TRUSTED_TURN: contextvars.ContextVar[Optional[TrustedPrivateTurn]] = (
    contextvars.ContextVar("health_autonomy_trusted_turn", default=None)
)
_RECENT_BINDINGS: "OrderedDict[str, TrustedPrivateTurn]" = OrderedDict()
_BINDING_LOCK = threading.Lock()
_ENGINE_LOCK = threading.Lock()
_ENGINE: Optional[HealthAutonomyEngine] = None
_CONTROL_TEXT_BY_ACTION = {action: text for text, action in CONTROL_EXACT.items()}


def _platform_value(platform: Any) -> str:
    value = getattr(platform, "value", platform)
    return str(value or "").strip().lower()


def _binding_key(platform: str, user_id: str) -> str:
    return f"{platform}|{user_id}"


def _remember(binding: TrustedPrivateTurn) -> None:
    key = _binding_key(binding.platform, binding.user_id)
    with _BINDING_LOCK:
        _RECENT_BINDINGS[key] = binding
        _RECENT_BINDINGS.move_to_end(key)
        while len(_RECENT_BINDINGS) > _MAX_RECENT_BINDINGS:
            _RECENT_BINDINGS.popitem(last=False)


def _forget_source(source: Any) -> None:
    platform = _platform_value(getattr(source, "platform", ""))
    user_id = str(getattr(source, "user_id", "") or "")
    if not platform or not user_id:
        return
    with _BINDING_LOCK:
        _RECENT_BINDINGS.pop(_binding_key(platform, user_id), None)


def _text_hash(text: str) -> str:
    return hashlib.sha256(str(text).strip().encode("utf-8")).hexdigest()


def _binding_matches_text(binding: TrustedPrivateTurn, text: str) -> bool:
    return hmac.compare_digest(binding.text_hash, _text_hash(text))


def _recent_binding(
    platform: str, user_id: str, user_message: str
) -> Optional[TrustedPrivateTurn]:
    if not platform or not user_id:
        return None
    key = _binding_key(platform.lower(), user_id)
    with _BINDING_LOCK:
        binding = _RECENT_BINDINGS.get(key)
        if not binding:
            return None
        if time.monotonic() - binding.captured_monotonic > _RECENT_BINDING_SECONDS:
            _RECENT_BINDINGS.pop(key, None)
            return None
        if binding.text_hash != _text_hash(user_message):
            return None
        return binding


def _engine() -> HealthAutonomyEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = HealthAutonomyEngine()
    return _ENGINE


def _routing(binding: TrustedPrivateTurn) -> dict[str, str]:
    return {
        "platform": binding.platform,
        "chat_id": binding.chat_id,
        "thread_id": binding.thread_id,
        "user_id": binding.user_id,
        "chat_type": "dm",
    }


def _encode_activation(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _reply_to_message_id(event: Any, source: Any) -> str:
    for owner in (event, source):
        for attribute in ("reply_to_message_id", "reply_message_id", "reply_to"):
            value = getattr(owner, attribute, None)
            if value is None:
                continue
            if not isinstance(value, (str, int)):
                value = getattr(value, "message_id", None) or getattr(value, "id", None)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
    return ""


def _decode_activation(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")


def pre_gateway_dispatch(event: Any, gateway: Any, **_: Any) -> Optional[dict[str, str]]:
    """Bind only an authenticated partner Telegram DM to the current task.

    Hermes fires this hook before its own auth gate.  We therefore call the
    gateway's real authorization function ourselves and fail closed: no trusted
    binding means no health persistence, cron mutation, or model injection.
    """
    _TRUSTED_TURN.set(None)
    source = getattr(event, "source", None)
    if source is None:
        return None
    # Invalidate any earlier DM fallback for this sender before validating the
    # new event.  A group/unauthorized event can never reuse private context.
    _forget_source(source)
    if bool(getattr(event, "internal", False)):
        return None
    if _platform_value(getattr(source, "platform", "")) != "telegram":
        return None
    if str(getattr(source, "chat_type", "") or "").lower() not in {"dm", "private"}:
        return None
    source_profile = str(getattr(source, "profile", "") or "")
    if source_profile and source_profile != "partner":
        return None
    check = getattr(gateway, "_is_user_authorized", None)
    if not callable(check):
        return None
    try:
        if not bool(check(source)):
            return None
    except Exception as exc:
        logger.error("health autonomy authorization check failed: %s", type(exc).__name__)
        return None

    user_id = str(getattr(source, "user_id", "") or "")
    chat_id = str(getattr(source, "chat_id", "") or "")
    message_id = str(
        getattr(event, "message_id", "")
        or getattr(source, "message_id", "")
        or ""
    )
    if not user_id or not chat_id:
        return None
    binding = TrustedPrivateTurn(
        platform="telegram",
        user_id=user_id,
        chat_id=chat_id,
        thread_id=str(getattr(source, "thread_id", "") or ""),
        message_id=message_id,
        reply_to_message_id=_reply_to_message_id(event, source),
        text_hash=_text_hash(str(getattr(event, "text", "") or "")),
        captured_monotonic=time.monotonic(),
    )
    _TRUSTED_TURN.set(binding)
    _remember(binding)

    text = str(getattr(event, "text", "") or "").strip()
    if text.startswith(ACTIVATION_PREFIX):
        return {
            "action": "rewrite",
            "text": f"/health-autonomy-safe activate {_encode_activation(text)}",
        }
    action = CONTROL_EXACT.get(text.rstrip("。"))
    if action:
        return {"action": "rewrite", "text": f"/health-autonomy-safe {action}"}
    return None


def health_autonomy_safe_command(raw_args: str) -> str:
    """Execute a control mutation only with a same-dispatch trusted binding."""
    binding = _TRUSTED_TURN.get()
    _TRUSTED_TURN.set(None)
    if binding is None:
        return "拒绝：此控制命令只能由 partner 本人在已授权 Telegram 私聊中发起。"
    if not binding.message_id:
        return "拒绝：当前平台消息缺少可用于防重放的 message_id。"
    parts = str(raw_args or "").strip().split(maxsplit=1)
    action = parts[0].lower() if parts else ""
    try:
        if action == "activate":
            if len(parts) != 2:
                raise ValueError("缺少授权载荷")
            text = _decode_activation(parts[1])
            if not text.startswith(ACTIVATION_PREFIX):
                raise ValueError("授权载荷格式不正确")
            if not _binding_matches_text(binding, text):
                raise ValueError("授权载荷与本人当前可见消息不一致")
            return _engine().activate(
                text,
                binding.message_id,
                _routing(binding),
            )
        if action in {"status", "pause", "resume", "revoke", "delete"}:
            visible_text = _CONTROL_TEXT_BY_ACTION[action]
            if not any(
                _binding_matches_text(binding, candidate)
                for candidate in (visible_text, visible_text + "。")
            ):
                raise ValueError("控制动作与本人当前可见消息不一致")
            return _engine().control(
                action,
                _routing(binding),
                source_message_id=binding.message_id,
            )
        raise ValueError("未知控制动作")
    except ValueError as exc:
        return f"未执行：{exc}。完整授权示例：\n{activation_example()}"
    except Exception as exc:
        logger.error("health autonomy control failed: %s", type(exc).__name__)
        return "健康管家控制操作未完成；没有把失败操作当作成功，请管理员检查本地审计。"


def pre_llm_call(
    session_id: str,
    user_message: str,
    platform: str = "",
    sender_id: str = "",
    **_: Any,
) -> Optional[dict[str, str]]:
    """Apply deterministic observations after the gateway auth path."""
    del session_id  # Health state is intentionally profile-scoped, not transcript-scoped.
    if str(user_message or "").lstrip().startswith("/"):
        return None
    binding = _TRUSTED_TURN.get()
    normalized_platform = str(platform or "").lower()
    normalized_sender = str(sender_id or "")
    if binding is not None:
        if binding.text_hash != _text_hash(str(user_message or "")):
            binding = None
        elif normalized_platform and normalized_platform != binding.platform:
            binding = None
        elif normalized_sender and normalized_sender != binding.user_id:
            binding = None
    if binding is None:
        binding = _recent_binding(
            normalized_platform, normalized_sender, str(user_message or "")
        )
    if binding is None:
        return None
    try:
        _result, context = _engine().observe(
            str(user_message or ""),
            binding.message_id,
            _routing(binding),
            reply_to_message_id=binding.reply_to_message_id or None,
        )
        return {"context": context} if context else None
    except Exception as exc:
        logger.error("health autonomy observation failed: %s", type(exc).__name__)
        return {
            "context": (
                "[health-autonomy-v02 unavailable] No structured profile, preference, "
                "or task change was confirmed for this turn. Do not claim otherwise."
            )
        }


def pre_tool_call(
    tool_name: str,
    args: dict[str, Any],
    **_: Any,
) -> Optional[dict[str, str]]:
    """Protect autonomy assets from model/tool mutation.

    This is defence in depth, not a substitute for deployment-time closure of
    Hermes CLI/API/Dashboard cron write paths.
    """
    name = str(tool_name or "").lower()
    flattened = str(args or {}).lower().replace("\\", "/")
    protected = (
        "health-autonomy",
        "health_autonomy",
        "health-autonomy-v02.sqlite3",
        "health_autonomy_dispatch.py",
        "health-autonomy-dispatch-v02",
    )
    if any(marker in flattened for marker in protected):
        return {
            "action": "block",
            "reason": "健康自治画像、策略、脚本和调度器只能由确定性插件控制。",
        }
    if name == "cronjob":
        job_id = str((args or {}).get("job_id") or "")
        try:
            managed_id = _engine().store.dispatcher_job_id() or ""
        except Exception:
            managed_id = ""
        if managed_id and job_id == managed_id:
            return {
                "action": "block",
                "reason": "模型不得修改健康自治调度器。",
            }
        health_words = ("健康", "喝水", "补水", "睡觉", "作息", "久坐", "服药", "吃药")
        if any(word in flattened for word in health_words):
            return {
                "action": "block",
                "reason": "健康任务只能由已授权的确定性自治策略创建。",
            }
    return None


def register(ctx: Any) -> None:
    """Register only in the isolated partner profile."""
    if ctx.profile_name != "partner" and os.environ.get(_TEST_MODE_ENV) != "1":
        raise RuntimeError("health-autonomy may only load in the partner profile")
    ctx.register_command(
        "health-autonomy-safe",
        handler=health_autonomy_safe_command,
        description="Internal deterministic health-autonomy control",
        args_hint="<internal-action>",
    )
    ctx.register_hook("pre_gateway_dispatch", pre_gateway_dispatch)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)


__all__ = [
    "health_autonomy_safe_command",
    "pre_gateway_dispatch",
    "pre_llm_call",
    "pre_tool_call",
    "register",
]

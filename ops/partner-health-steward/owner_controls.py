"""Authenticated owner/viewer controls delivered outside ordinary chat."""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
from dataclasses import dataclass, replace
from typing import Any, Mapping

from export_attachments import PreparedJsonExport
from health_model import HealthModelConfig, PinnedHealthModelClient, PinnedHealthModelError
from sidecar.health_turn_context import MAX_HEALTH_TURN_EVIDENCE_IDS
from weixin_ingress import TrustedWeixinEnvelope


VIEW_ACTION = "health.access.read"
GRANT_ACTION = "health.access.grant"
REVOKE_ACTION = "health.access.revoke"
PAUSE_PROACTIVE_ACTION = "health.proactive.pause"
RESUME_PROACTIVE_ACTION = "health.proactive.resume"
STOP_RECORDING_ACTION = "health.recording.stop"
RESUME_RECORDING_ACTION = "health.recording.resume"
ANALYZE_ACTION = "health.access.analyze"
EXPORT_ACTION = "health.profile.export"
DELETE_REQUEST_ACTION = "health.profile.delete.request"
DELETE_CONFIRM_ACTION = "health.profile.delete.confirm"
TRANSFER_OWNER_ACTION = "health.profile.owner.transfer"
RECOVER_OWNER_ACTION = "health.profile.owner.recover"

_PAUSE_DURATION = re.compile(
    r"(?<![0-9])(?P<count>[1-9][0-9]{0,3})(?P<unit>分钟|小时|天)"
)
_SERVICE_MARKER = re.compile(r"〔健康管家：[^〕]+〕")
_MAX_WEIXIN_TEXT_CHARS = 1800
_CHUNK_PAYLOAD_CHARS = 1740
_UNSAFE_COMMAND_CONTEXT = (
    "不",
    "勿",
    "别",
    "未",
    "否",
    "禁止",
    "拒绝",
    "如果",
    "假如",
    "要是",
    "除非",
    "为什么",
    "怎么",
    "如何",
    "什么意思",
    "怎样",
    "吗",
    "么",
    "？",
    "?",
    "“",
    "”",
    "‘",
    "’",
    '"',
    "'",
    "并",
    "同时",
    "然后",
    "以及",
    "或者",
    "和",
)
_HEALTH_OBJECT = r"(?:健康画像|健康档案|健康记录|健康信息)"
_PROACTIVE_OBJECT = r"(?:健康提醒|主动触达|主动健康联系)"
_PAUSE_ARGUMENT = r"(?:无限期|[0-9一二三四五六七八九十百千万零〇两]+(?:分钟|小时|天|日|周|星期|个月|月|年))"
_VIEW_COMMAND = re.compile(
    rf"^(?:请让我|请我|让我|请再次|再次|请|我想|我要)?查看"
    rf"(?:我的|当前|停止后的|恢复后的)?(?:完整)?{_HEALTH_OBJECT}"
    r"(?:当前状态|状态)?$"
)
_ANALYZE_COMMAND = re.compile(
    rf"^(?:请用健康模型|请让健康模型|用健康模型|让健康模型|请|我想|我要)?"
    rf"分析(?:我的当前|我的|当前)?{_HEALTH_OBJECT}$"
)
_STOP_RECORDING_COMMAND = re.compile(
    r"^(?:请再次|再次|请|我明确|我要|现在)?停止(?:我的)?健康记录$"
)
_RESUME_RECORDING_COMMAND = re.compile(
    r"^(?:请再次|再次|请|我明确|我要|现在)?恢复(?:我的)?健康记录$"
)
_PAUSE_PROACTIVE_COMMAND = re.compile(
    rf"^(?:请继续|继续|请|我要|现在)?(?:{_PAUSE_ARGUMENT})?暂停"
    rf"(?:我的)?{_PROACTIVE_OBJECT}(?:{_PAUSE_ARGUMENT})?$"
)
_RESUME_PROACTIVE_COMMAND = re.compile(
    rf"^(?:请再次|再次|请|我明确|我要|现在)?恢复(?:我的)?{_PROACTIVE_OBJECT}$"
)
_GRANT_COMMAND = re.compile(
    rf"^(?:请再次|再次|请|我|我要|我明确|现在)?授权"
    rf"[^，。！？!?]+?(?:查看|读取)(?:我的)?(?:完整)?{_HEALTH_OBJECT}"
    r"(?:查看权限|权限)?$"
)
_REVOKE_COMMANDS = (
    re.compile(
        rf"^(?:请再次|再次|请|我|我要|我明确|现在)?撤回"
        rf"[^，。！？!?]+?的?{_HEALTH_OBJECT}(?:查看权限|查看授权|权限|授权)$"
    ),
    re.compile(
        rf"^(?:请再次|再次|请|我|我要|我明确|现在)?取消授权"
        rf"[^，。！？!?]+?(?:查看|读取)(?:我的)?(?:完整)?{_HEALTH_OBJECT}$"
    ),
)
_EXPORT_COMMAND = re.compile(
    rf"^(?:请|请帮我|帮我|让我|我要)?导出(?:我的|当前)?(?:完整)?{_HEALTH_OBJECT}(?:JSON|json)?$"
)
_DELETE_REQUEST_COMMAND = re.compile(
    rf"^(?:请|请帮我|帮我|我明确|我要|现在)?删除(?:我的)?(?:完整)?{_HEALTH_OBJECT}$"
)
_DELETE_CONFIRM_COMMAND = re.compile(
    rf"^(?:请|我明确|现在)?确认删除(?:我的)?(?:完整)?{_HEALTH_OBJECT}$"
)
_TRANSFER_OWNER_COMMAND = re.compile(
    rf"^(?:请|请帮我|帮我|我要|现在)?将(?:我的)?{_HEALTH_OBJECT}"
    r"(?:主人身份)?迁移到(?P<sender>[A-Za-z0-9._:-]{1,128})$"
)
_RECOVER_OWNER_COMMAND = re.compile(
    rf"^(?:请|我要|现在)?使用(?:身份)?恢复码"
    r"(?P<code>[A-Za-z0-9_-]{43,128})恢复(?:我的)?"
    rf"{_HEALTH_OBJECT}$"
)
_OWNER_ONLY_ACTIONS = frozenset(
    {
        STOP_RECORDING_ACTION,
        RESUME_RECORDING_ACTION,
        PAUSE_PROACTIVE_ACTION,
        RESUME_PROACTIVE_ACTION,
        GRANT_ACTION,
        REVOKE_ACTION,
        EXPORT_ACTION,
        DELETE_REQUEST_ACTION,
        TRANSFER_OWNER_ACTION,
    }
)

HEALTH_VIEW_ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["analysis_text"],
    "properties": {"analysis_text": {"type": "string", "minLength": 1}},
}


@dataclass(frozen=True)
class OwnerControlOutcome:
    """Externally visible result of one intercepted control turn."""

    action: str
    delivered: bool


@dataclass(frozen=True)
class _PreparedOwnerControl:
    envelope: TrustedWeixinEnvelope
    action: str
    message: str | None
    label: str
    terminal_delivery: bool | None = None
    attachment: PreparedJsonExport | None = None
    recovery_recipient: str | None = None
    recovery_code: str | None = None
    deletion_terminal_notice: bool = False
    deletion_notice_recovery: bool = False


class _ControlValidationError(ValueError):
    pass


def _normalized_text(value: str) -> str:
    return "".join(str(value).strip().rstrip("。！!").split())


def _control_action(value: str) -> str | None:
    text = _normalized_text(value)
    if not text or any(phrase in text for phrase in _UNSAFE_COMMAND_CONTEXT):
        return None
    matches: list[str] = []
    for action, pattern in (
        (VIEW_ACTION, _VIEW_COMMAND),
        (ANALYZE_ACTION, _ANALYZE_COMMAND),
        (STOP_RECORDING_ACTION, _STOP_RECORDING_COMMAND),
        (RESUME_RECORDING_ACTION, _RESUME_RECORDING_COMMAND),
        (PAUSE_PROACTIVE_ACTION, _PAUSE_PROACTIVE_COMMAND),
        (RESUME_PROACTIVE_ACTION, _RESUME_PROACTIVE_COMMAND),
        (GRANT_ACTION, _GRANT_COMMAND),
        (EXPORT_ACTION, _EXPORT_COMMAND),
        (DELETE_REQUEST_ACTION, _DELETE_REQUEST_COMMAND),
        (DELETE_CONFIRM_ACTION, _DELETE_CONFIRM_COMMAND),
        (TRANSFER_OWNER_ACTION, _TRANSFER_OWNER_COMMAND),
        (RECOVER_OWNER_ACTION, _RECOVER_OWNER_COMMAND),
    ):
        if pattern.fullmatch(text):
            matches.append(action)
    if any(pattern.fullmatch(text) for pattern in _REVOKE_COMMANDS):
        matches.append(REVOKE_ACTION)
    return matches[0] if len(matches) == 1 else None


def _names_configured_viewer(value: str, viewer_sender_id: str) -> bool:
    text = _normalized_text(value)
    return "预配置查看者" in text or _normalized_text(viewer_sender_id) in text


def _transfer_target(value: str) -> str | None:
    match = _TRANSFER_OWNER_COMMAND.fullmatch(_normalized_text(value))
    return match.group("sender") if match is not None else None


def _recovery_code(value: str) -> str | None:
    match = _RECOVER_OWNER_COMMAND.fullmatch(_normalized_text(value))
    return match.group("code") if match is not None else None


def _pause_until_utc(value: str, message_utc: str) -> str | None:
    text = _normalized_text(value)
    matches = list(_PAUSE_DURATION.finditer(text))
    if not matches:
        if "无限期" in text:
            return None
        raise _ControlValidationError("pause-duration-required")
    if len(matches) != 1:
        raise _ControlValidationError("pause-duration-ambiguous")
    if "无限期" in text:
        raise _ControlValidationError("pause-duration-ambiguous")
    count = int(matches[0].group("count"))
    unit = matches[0].group("unit")
    delta = {
        "分钟": dt.timedelta(minutes=count),
        "小时": dt.timedelta(hours=count),
        "天": dt.timedelta(days=count),
    }[unit]
    try:
        observed = dt.datetime.fromisoformat(message_utc.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise _ControlValidationError("message-utc-invalid") from exc
    if observed.tzinfo is None:
        raise _ControlValidationError("message-utc-invalid")
    return (
        observed.astimezone(dt.timezone.utc) + delta
    ).replace(microsecond=0).isoformat()


class PartnerOwnerControlHandler:
    """Route recognized authenticated controls straight to the sidecar/channel."""

    def __init__(
        self,
        sidecar: Any,
        signer: Any,
        channel: Any,
        *,
        expected_owner_sender_id: str,
        expected_viewer_sender_id: str,
        subject: str = "profile",
        analyzer: Any | None = None,
        export_store: Any | None = None,
    ) -> None:
        self.sidecar = sidecar
        self.signer = signer
        self.channel = channel
        self.expected_owner_sender_id = str(expected_owner_sender_id).strip()
        self.expected_viewer_sender_id = str(expected_viewer_sender_id).strip()
        self.subject = str(subject).strip()
        self.analyzer = analyzer
        self.export_store = export_store
        self._control_lock = threading.Lock()
        self._recording_lock = threading.Lock()
        if not self.expected_owner_sender_id:
            raise ValueError("expected-owner-required")
        if not self.expected_viewer_sender_id:
            raise ValueError("expected-viewer-required")
        if self.expected_owner_sender_id == self.expected_viewer_sender_id:
            raise ValueError("viewer-must-not-be-owner")
        if not self.subject:
            raise ValueError("subject-required")

    def recognizes(self, envelope: TrustedWeixinEnvelope) -> bool:
        """Return whether this turn must bypass ordinary conversation."""
        return (
            isinstance(envelope, TrustedWeixinEnvelope)
            and envelope.channel == "weixin"
            and envelope.profile_name == "partner"
            and _control_action(envelope.message_text) is not None
        )

    def is_recording_transition(self, envelope: TrustedWeixinEnvelope) -> bool:
        """Return whether prepare must share the recording-state ingress gate."""
        return self.recognizes(envelope) and _control_action(
            envelope.message_text
        ) in {STOP_RECORDING_ACTION, RESUME_RECORDING_ACTION}

    def is_identity_recovery(self, envelope: TrustedWeixinEnvelope) -> bool:
        """Allow only the exact recovery-code command through an unknown DM."""
        return self.recognizes(envelope) and _control_action(
            envelope.message_text
        ) == RECOVER_OWNER_ACTION

    def _is_current_owner(self, sender_id: str) -> bool:
        normalized = str(sender_id or "").strip()
        if not normalized:
            return False
        status_reader = getattr(self.sidecar, "health_recording_status", None)
        if not callable(status_reader):
            return False
        try:
            return status_reader(self.subject, normalized) in {
                "recording_enabled",
                "recording_stopped",
            }
        except Exception:
            return False

    @staticmethod
    def _recovery_code_message(recovery_code: str) -> str:
        return (
            "请离线保存以下身份恢复码；它只显示这一次，"
            "不得转发给查看者、管理员或任何第三方：\n\n"
            f"{recovery_code}"
        )

    def deliver_initial_recovery_code(
        self, envelope: TrustedWeixinEnvelope, recovery_code: str
    ) -> bool:
        """Directly display the bootstrap code without ordinary-chat history."""
        if (
            not isinstance(envelope, TrustedWeixinEnvelope)
            or envelope.sender_id != self.expected_owner_sender_id
            or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", str(recovery_code))
        ):
            raise ValueError("initial-recovery-code-not-authorized")
        return self._deliver(
            envelope,
            "health.profile.owner.recovery.initial",
            self._recovery_code_message(recovery_code),
            label="身份恢复码",
        )

    @staticmethod
    def _render_view(view: Mapping[str, Any]) -> str:
        return json.dumps(
            {
                "view_schema_version": 1,
                "health_view": dict(view),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _split_message(message: str, *, label: str) -> tuple[str, ...]:
        if len(message) <= _MAX_WEIXIN_TEXT_CHARS:
            return (message,)
        payloads = tuple(
            message[index : index + _CHUNK_PAYLOAD_CHARS]
            for index in range(0, len(message), _CHUNK_PAYLOAD_CHARS)
        )
        total = len(payloads)
        parts = tuple(
            f"【{label} {index}/{total}】\n{payload}"
            for index, payload in enumerate(payloads, start=1)
        )
        if any(len(part) > _MAX_WEIXIN_TEXT_CHARS for part in parts):
            raise RuntimeError("weixin-control-chunk-too-long")
        return parts

    @staticmethod
    def _confirmed_change(result: Any) -> bool:
        if not isinstance(result, Mapping) or type(result.get("changed")) is not bool:
            raise RuntimeError("control-change-result-invalid")
        return bool(result["changed"])

    def _delivery_key(
        self,
        envelope: TrustedWeixinEnvelope,
        action: str,
    ) -> str:
        return (
            f"health-control:v1:{self.subject}:{envelope.sender_id}:"
            f"{envelope.message_id}:{action}"
        )

    def _terminal_delivery(
        self,
        envelope: TrustedWeixinEnvelope,
        action: str,
    ) -> bool | None:
        read_status = getattr(self.channel, "delivery_batch_status", None)
        try:
            if not callable(read_status):
                raise KeyError("delivery-batch-status-unavailable")
            status = read_status(self._delivery_key(envelope, action))
        except KeyError:
            read_status = getattr(self.channel, "delivery_status", None)
            if not callable(read_status):
                return None
            try:
                status = read_status(self._delivery_key(envelope, action))
            except KeyError:
                return None
        if not isinstance(status, Mapping):
            raise RuntimeError("control-delivery-status-invalid")
        state = str(status.get("status", ""))
        if state == "sent":
            return True
        if state == "rejected":
            return False
        raise RuntimeError("control-delivery-not-terminal")

    def _deliver(
        self,
        envelope: TrustedWeixinEnvelope,
        action: str,
        message: str,
        *,
        label: str,
        deletion_terminal_notice: bool = False,
        deletion_notice_recovery: bool = False,
    ) -> bool:
        parts = self._split_message(message, label=label)
        if deletion_terminal_notice:
            notice_method = (
                "recover_profile_deletion_notice_once"
                if deletion_notice_recovery
                else "send_profile_deletion_notice_once"
            )
            send_notice = getattr(self.channel, notice_method, None)
            if not callable(send_notice):
                raise RuntimeError("profile-deletion-notice-delivery-required")
            if deletion_notice_recovery:
                return send_notice(envelope.sender_id, parts) is True
            return send_notice(
                envelope.sender_id,
                parts,
                self._delivery_key(envelope, action),
            ) is True
        send_parts = getattr(self.channel, "send_text_parts_once", None)
        if not callable(send_parts):
            raise RuntimeError("idempotent-weixin-batch-required")
        return send_parts(
            envelope.sender_id,
            parts,
            self._delivery_key(envelope, action),
        ) is True

    def _deliver_json_attachment(
        self,
        envelope: TrustedWeixinEnvelope,
        action: str,
        attachment: PreparedJsonExport,
    ) -> bool:
        """Send the private export without placing its content in chat text."""
        send_attachment = getattr(self.channel, "send_json_attachment_once", None)
        if not callable(send_attachment):
            raise RuntimeError("idempotent-weixin-attachment-required")
        try:
            return send_attachment(
                envelope.sender_id,
                attachment.path,
                self._delivery_key(envelope, action),
            ) is True
        finally:
            # A rejected or uncertain handoff must not leave plaintext behind.
            attachment.remove()

    def _recognized_action(self, envelope: TrustedWeixinEnvelope) -> str:
        if not self.recognizes(envelope):
            raise ValueError("owner-control-not-recognized")
        action = _control_action(envelope.message_text)
        if action is None:
            raise ValueError("owner-control-not-recognized")
        return action

    def _prepare_locked(
        self,
        envelope: TrustedWeixinEnvelope,
        action: str,
    ) -> _PreparedOwnerControl:
        terminal = self._terminal_delivery(envelope, action)
        if terminal is not None:
            return _PreparedOwnerControl(
                envelope=envelope,
                action=action,
                message=None,
                label="",
                terminal_delivery=terminal,
            )
        label = "健康管家回复"
        attachment: PreparedJsonExport | None = None
        deletion_committed = False
        deletion_terminal_notice = False
        deletion_notice_recovery = False
        try:
            if action in _OWNER_ONLY_ACTIONS and not self._is_current_owner(
                envelope.sender_id
            ):
                raise _ControlValidationError("owner-control-not-authorized")
            if action in {GRANT_ACTION, REVOKE_ACTION} and not _names_configured_viewer(
                envelope.message_text,
                self.expected_viewer_sender_id,
            ):
                raise _ControlValidationError("viewer-target-not-configured")
            pause_until = (
                _pause_until_utc(envelope.message_text, envelope.message_utc)
                if action == PAUSE_PROACTIVE_ACTION
                else None
            )
            receipt_payload: dict[str, Any] = {
                "action": action,
                "subject": self.subject,
                "actor_sender_id": envelope.sender_id,
                "target_sender_id": (
                    self.expected_viewer_sender_id
                    if action in {GRANT_ACTION, REVOKE_ACTION}
                    else (
                        _transfer_target(envelope.message_text)
                        if action == TRANSFER_OWNER_ACTION
                        else envelope.sender_id
                    )
                ),
                "message_id": envelope.message_id,
                "message_utc": envelope.message_utc,
            }
            if action == PAUSE_PROACTIVE_ACTION:
                receipt_payload["pause_until_utc"] = pause_until
            if (
                not isinstance(receipt_payload["target_sender_id"], str)
                or not receipt_payload["target_sender_id"].strip()
            ):
                raise _ControlValidationError("owner-transfer-target-invalid")
            token = self.signer.sign_access(
                **receipt_payload,
            )
            if action == TRANSFER_OWNER_ACTION:
                target_sender_id = str(receipt_payload["target_sender_id"]).strip()
                transferred = self.sidecar.transfer_profile_owner(
                    self.subject,
                    envelope.sender_id,
                    target_sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                )
                recovery_code = (
                    transferred.get("recovery_code")
                    if isinstance(transferred, Mapping)
                    else None
                )
                if (
                    transferred.get("changed") is not True
                    or not isinstance(recovery_code, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", recovery_code)
                ):
                    raise RuntimeError("owner-transfer-invalid")
                message = (
                    "身份迁移已完成。旧身份的后续控制权已撤销，"
                    "新身份将收到一次性身份恢复码。"
                )
                label = "主人身份已迁移"
            elif action == RECOVER_OWNER_ACTION:
                supplied_code = _recovery_code(envelope.message_text)
                if supplied_code is None:
                    raise _ControlValidationError("owner-recovery-code-invalid")
                recovered = self.sidecar.recover_profile_owner(
                    self.subject,
                    envelope.sender_id,
                    supplied_code,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                )
                recovery_code = (
                    recovered.get("recovery_code")
                    if isinstance(recovered, Mapping)
                    else None
                )
                if (
                    recovered.get("changed") is not True
                    or not isinstance(recovery_code, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", recovery_code)
                ):
                    raise RuntimeError("owner-recovery-invalid")
                message = (
                    "身份恢复已完成。旧身份已失去后续控制权；"
                    "新的身份恢复码如下，它只显示一次：\n\n"
                    f"{recovery_code}"
                )
                label = "主人身份已恢复"
            elif action == EXPORT_ACTION:
                if self.export_store is None or not callable(
                    getattr(self.export_store, "write_json", None)
                ):
                    raise RuntimeError("private-export-store-unconfigured")
                exported = self.sidecar.export_profile(
                    self.subject,
                    envelope.sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                )
                if not isinstance(exported, Mapping):
                    raise RuntimeError("profile-export-invalid")
                attachment = self.export_store.write_json(exported)
                if not isinstance(attachment, PreparedJsonExport):
                    raise RuntimeError("profile-export-attachment-invalid")
                message = None
                label = "完整健康档案导出"
            elif action == DELETE_REQUEST_ACTION:
                requested = self.sidecar.request_profile_deletion(
                    self.subject,
                    envelope.sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                )
                if (
                    not isinstance(requested, Mapping)
                    or requested.get("deleted") is not False
                    or not isinstance(requested.get("expires_utc"), str)
                ):
                    raise RuntimeError("profile-deletion-request-invalid")
                message = (
                    "已记录删除请求，尚未删除任何健康内容。请在 10 分钟内发送“确认删除我的健康档案”完成第二次确认。\n\n"
                    "已发送的微信附件或普通聊天副本无法撤回。"
                )
                label = "健康档案删除确认"
            elif action == DELETE_CONFIRM_ACTION:
                status_reader = getattr(self.sidecar, "profile_deletion_status", None)
                if not callable(status_reader):
                    raise RuntimeError("profile-deletion-status-unavailable")
                deletion_status = status_reader(
                    self.subject,
                    envelope.sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                )
                if not isinstance(deletion_status, Mapping):
                    raise RuntimeError("profile-deletion-status-invalid")
                if deletion_status.get("deleted") is True:
                    # A process interruption can happen after the sidecar has
                    # destroyed the profile but before the ledger transaction
                    # finishes.  Complete that transaction before allowing its
                    # sole terminal acknowledgement to leave the channel.
                    complete_delivery = getattr(
                        self.channel, "complete_profile_deletion", None
                    )
                    if not callable(complete_delivery):
                        raise RuntimeError("profile-deletion-delivery-guard-required")
                    complete_delivery()
                    deletion_committed = True
                    deletion_terminal_notice = True
                    deletion_notice_recovery = True
                    message = (
                        "健康档案已永久删除，后续访问和投递已阻断。\n\n"
                        "已发送的微信附件或普通聊天副本无法撤回。"
                    )
                    label = "健康档案已删除"
                else:
                    request_message_id = deletion_status.get("request_message_id")
                    if (
                        deletion_status.get("deletion_pending") is not True
                        or not isinstance(request_message_id, str)
                        or not request_message_id.strip()
                    ):
                        raise _ControlValidationError("delete-confirmation-missing")
                    prepare_delivery = getattr(
                        self.channel, "prepare_profile_deletion", None
                    )
                    complete_delivery = getattr(
                        self.channel, "complete_profile_deletion", None
                    )
                    cancel_delivery = getattr(
                        self.channel, "cancel_profile_deletion", None
                    )
                    if not all(
                        callable(operation)
                        for operation in (
                            prepare_delivery,
                            complete_delivery,
                            cancel_delivery,
                        )
                    ):
                        raise RuntimeError("profile-deletion-delivery-guard-required")
                    # A transport/socket interruption can leave the local
                    # guard prepared even though the sidecar proves that this
                    # profile still exists and the same deletion request is
                    # pending.  A fresh explicit owner confirmation may
                    # safely replace that stale terminal key; without this
                    # cleanup it would remain permanently fail-closed.
                    read_delivery_status = getattr(
                        self.channel, "profile_deletion_status", None
                    )
                    if (
                        callable(read_delivery_status)
                        and read_delivery_status() == "prepared"
                    ):
                        cancel_delivery()
                    guard_prepared = prepare_delivery(
                        self._delivery_key(envelope, action)
                    )
                    try:
                        deleted = self.sidecar.confirm_profile_deletion(
                            self.subject,
                            envelope.sender_id,
                            request_message_id,
                            envelope.message_id,
                            envelope.message_utc,
                            token,
                        )
                    except Exception:
                        # The store deletes the encrypted profile before its
                        # final audit/confirmation cleanup.  If one of those
                        # post-destruction operations reports an error, the
                        # delivery gate must remain closed rather than
                        # accidentally restoring health delivery.
                        committed_status = status_reader(
                            self.subject,
                            envelope.sender_id,
                            envelope.message_id,
                            envelope.message_utc,
                            token,
                        )
                        if (
                            isinstance(committed_status, Mapping)
                            and committed_status.get("deleted") is True
                        ):
                            deleted = {"deleted": True}
                        else:
                            # Only a positively observed non-deleted state is
                            # safe to cancel.  An unavailable/malformed status
                            # leaves the gate prepared and therefore fail-closed.
                            if (
                                guard_prepared
                                and isinstance(committed_status, Mapping)
                                and committed_status.get("deleted") is False
                            ):
                                cancel_delivery()
                            raise
                    if not isinstance(deleted, Mapping) or deleted.get("deleted") is not True:
                        if guard_prepared:
                            cancel_delivery()
                        raise RuntimeError("profile-deletion-confirmation-invalid")
                    deletion_committed = True
                    complete_delivery()
                    deletion_terminal_notice = True
                    message = (
                        "健康档案已永久删除，后续访问和投递已阻断。\n\n"
                        "已发送的微信附件或普通聊天副本无法撤回。"
                    )
                    label = "健康档案已删除"
            elif action == VIEW_ACTION:
                view = self.sidecar.read_authorized_view(
                    self.subject,
                    envelope.sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                )
                if not isinstance(view, Mapping):
                    raise RuntimeError("authorized-view-invalid")
                message = self._render_view(view)
                label = "完整健康档案"
            elif action == ANALYZE_ACTION:
                if self.analyzer is None or not callable(
                    getattr(self.analyzer, "analyze", None)
                ):
                    raise RuntimeError("health-view-analyzer-unconfigured")
                context = self.sidecar.read_authorized_analysis_context(
                    self.subject,
                    envelope.sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                )
                if not isinstance(context, Mapping):
                    raise RuntimeError("analysis-context-invalid")
                message = str(
                    self.analyzer.analyze(context, envelope.message_text)
                ).strip()
                if not message:
                    raise RuntimeError("health-view-analysis-empty")
                label = "健康分析"
            elif action == GRANT_ACTION:
                changed = self._confirmed_change(self.sidecar.grant_viewer(
                    self.subject,
                    envelope.sender_id,
                    self.expected_viewer_sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                ))
                message = (
                    "已向预配置查看者开放只读健康档案。\n\n"
                    "〔健康管家：查看授权已生效〕"
                    if changed
                    else "预配置查看者原本已获只读权限，状态未变化。"
                )
            elif action == REVOKE_ACTION:
                changed = self._confirmed_change(self.sidecar.revoke_viewer(
                    self.subject,
                    envelope.sender_id,
                    self.expected_viewer_sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                ))
                message = (
                    "已撤回预配置查看者的健康档案权限。\n\n"
                    "〔健康管家：查看授权已撤回〕"
                    if changed
                    else "预配置查看者原本没有有效权限，状态未变化。"
                )
            elif action == PAUSE_PROACTIVE_ACTION:
                changed = self._confirmed_change(self.sidecar.pause_proactive_contact(
                    self.subject,
                    envelope.sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                    pause_until,
                ))
                scope = f"至 {pause_until}" if pause_until else "（无限期）"
                message = (
                    f"主动触达已暂停{scope}。\n\n〔健康管家：主动触达已暂停〕"
                    if changed
                    else "主动触达已处于相同暂停状态，状态未变化。"
                )
            elif action == RESUME_PROACTIVE_ACTION:
                changed = self._confirmed_change(self.sidecar.resume_proactive_contact(
                    self.subject,
                    envelope.sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                ))
                message = (
                    "主动触达已恢复。\n\n〔健康管家：主动触达已恢复〕"
                    if changed
                    else "主动触达原本已恢复，状态未变化。"
                )
            elif action == STOP_RECORDING_ACTION:
                changed = self._confirmed_change(self.sidecar.stop_health_recording(
                    self.subject,
                    envelope.sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                ))
                message = (
                    "健康记录已停止；已有加密档案仍可查看。\n\n"
                    "〔健康管家：健康记录已停止〕"
                    if changed
                    else "健康记录原本已停止，状态未变化。"
                )
            else:
                changed = self._confirmed_change(self.sidecar.resume_health_recording(
                    self.subject,
                    envelope.sender_id,
                    envelope.message_id,
                    envelope.message_utc,
                    token,
                ))
                message = (
                    "健康记录已恢复。\n\n〔健康管家：健康记录已恢复〕"
                    if changed
                    else "健康记录原本已恢复，状态未变化。"
                )
        except _ControlValidationError:
            if action in {GRANT_ACTION, REVOKE_ACTION}:
                message = "健康档案查看授权未更改，请只指定预配置查看者。"
            elif action in {PAUSE_PROACTIVE_ACTION, RESUME_PROACTIVE_ACTION}:
                message = "主动触达状态未更改，请明确写出时长或“无限期”。"
            elif action in {EXPORT_ACTION, DELETE_REQUEST_ACTION, DELETE_CONFIRM_ACTION}:
                message = "此操作仅限主人，并且需要一条明确、独立的控制指令；健康数据未更改。"
            elif action in {TRANSFER_OWNER_ACTION, RECOVER_OWNER_ACTION}:
                message = "身份迁移或恢复请求无效，健康数据和主人绑定未更改。"
            else:
                message = "控制请求无效，状态未更改。"
        except Exception:
            if action == DELETE_CONFIRM_ACTION and deletion_committed:
                # The sidecar committed the irreversible boundary, but the
                # local delivery tombstone did not finish.  Do not send an
                # inaccurate failure message through a guarded channel; a
                # later explicit confirmation retry reconciles it fail-closed.
                return _PreparedOwnerControl(
                    envelope=envelope,
                    action=action,
                    message=None,
                    label="",
                    terminal_delivery=False,
                )
            if action in {VIEW_ACTION, ANALYZE_ACTION, EXPORT_ACTION}:
                message = "健康档案查看失败或当前身份未获授权，请重新确认后再试。"
            elif action in {DELETE_REQUEST_ACTION, DELETE_CONFIRM_ACTION}:
                message = (
                    "删除结果无法确认；健康档案尚未按本条消息声明为已删除。"
                    "请勿重复发送本条消息，请用新的明确指令查询或重试。"
                )
            elif action in {TRANSFER_OWNER_ACTION, RECOVER_OWNER_ACTION}:
                message = (
                    "身份迁移或恢复失败关闭；健康数据未更改。"
                    "请使用新的明确指令，且不要重复发送本条消息。"
                )
            else:
                message = (
                    "健康控制结果无法确认；请勿重复发送本条消息，"
                    "请用新的明确指令查询当前状态。"
                )
        return _PreparedOwnerControl(
            envelope=envelope,
            action=action,
            message=message,
            label=label,
            attachment=attachment,
            recovery_recipient=(
                str(receipt_payload["target_sender_id"]).strip()
                if action == TRANSFER_OWNER_ACTION
                and "recovery_code" in locals()
                else None
            ),
            recovery_code=(
                recovery_code
                if action == TRANSFER_OWNER_ACTION
                and isinstance(recovery_code, str)
                else None
            ),
            deletion_terminal_notice=deletion_terminal_notice,
            deletion_notice_recovery=deletion_notice_recovery,
        )

    def prepare_recording_transition(
        self,
        envelope: TrustedWeixinEnvelope,
    ) -> _PreparedOwnerControl:
        """Commit only stop/resume state while the adapter owns the FIFO gate."""
        action = self._recognized_action(envelope)
        if action not in {STOP_RECORDING_ACTION, RESUME_RECORDING_ACTION}:
            raise ValueError("recording-transition-required")
        with self._recording_lock:
            return self._prepare_locked(envelope, action)

    def deliver_prepared(
        self,
        prepared: _PreparedOwnerControl,
    ) -> OwnerControlOutcome:
        """Deliver a frozen control result after any state-ordering gate is free."""
        if not isinstance(prepared, _PreparedOwnerControl):
            raise ValueError("prepared-owner-control-invalid")
        if prepared.terminal_delivery is not None:
            return OwnerControlOutcome(
                prepared.action,
                prepared.terminal_delivery,
            )
        if prepared.attachment is not None:
            if prepared.message is not None:
                raise RuntimeError("prepared-owner-control-attachment-message-conflict")
            delivered = self._deliver_json_attachment(
                prepared.envelope,
                prepared.action,
                prepared.attachment,
            )
            return OwnerControlOutcome(prepared.action, delivered)
        if (
            prepared.recovery_recipient is not None
            or prepared.recovery_code is not None
        ):
            if (
                not prepared.recovery_recipient
                or not isinstance(prepared.recovery_code, str)
            ):
                raise RuntimeError("prepared-recovery-code-invalid")
            recovery_envelope = replace(
                prepared.envelope, sender_id=prepared.recovery_recipient
            )
            if not self._deliver(
                recovery_envelope,
                f"{prepared.action}.recovery-code",
                self._recovery_code_message(prepared.recovery_code),
                label="身份恢复码",
            ):
                return OwnerControlOutcome(prepared.action, False)
        if prepared.message is None:
            raise RuntimeError("prepared-owner-control-message-missing")
        delivered = self._deliver(
            prepared.envelope,
            prepared.action,
            prepared.message,
            label=prepared.label,
            deletion_terminal_notice=prepared.deletion_terminal_notice,
            deletion_notice_recovery=prepared.deletion_notice_recovery,
        )
        return OwnerControlOutcome(prepared.action, delivered)

    def handle(self, envelope: TrustedWeixinEnvelope) -> OwnerControlOutcome:
        """Consume one authenticated control without entering ordinary chat."""
        action = self._recognized_action(envelope)
        lock = (
            self._recording_lock
            if action in {STOP_RECORDING_ACTION, RESUME_RECORDING_ACTION}
            else self._control_lock
        )
        with lock:
            prepared = self._prepare_locked(envelope, action)
            return self.deliver_prepared(prepared)


class PinnedHealthViewAnalyzer:
    """Analyze one explicit turn through the separately pinned health model."""

    def __init__(self, plugin_llm: Any, config: HealthModelConfig) -> None:
        self.config = config
        self._client = PinnedHealthModelClient(plugin_llm, config)

    def analyze(self, context: Mapping[str, Any], request_text: str) -> str:
        allowed_fields = {
            "analysis_context_schema_version",
            "subject",
            "role",
            "current_version_id",
            "profile_summary_zh",
            "evidence_ids",
        }
        if not isinstance(context, Mapping) or set(context) != allowed_fields:
            raise RuntimeError("analysis-context-invalid")
        evidence_ids = context.get("evidence_ids")
        profile_summary = context.get("profile_summary_zh")
        if (
            context.get("analysis_context_schema_version") != 1
            or context.get("role") not in {"owner", "viewer"}
            or not isinstance(context.get("subject"), str)
            or not str(context["subject"]).strip()
            or not isinstance(profile_summary, str)
            or len(profile_summary) > 300
            or not isinstance(evidence_ids, list)
            or len(evidence_ids) > MAX_HEALTH_TURN_EVIDENCE_IDS
            or any(
                not isinstance(evidence_id, str)
                or not evidence_id.strip()
                or len(evidence_id) > 256
                for evidence_id in evidence_ids
            )
            or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise RuntimeError("analysis-context-invalid")
        payload = {
            "current_turn": {"request_text": str(request_text)},
            "authorized_health_context": dict(context),
        }
        try:
            result = self._client.complete_structured(
                instructions=(
                    "Analyze only the explicitly authorized compact health context in "
                    "this request. No ordinary conversation history or tools are "
                    "available. Evidence identifiers are references, not evidence text. "
                    "Do not invent missing facts, write the profile, create tasks, or "
                    "emit health-steward status markers. Return only the required JSON."
                ),
                payload=payload,
                json_schema=HEALTH_VIEW_ANALYSIS_SCHEMA,
                schema_name="pinned_health_view_analysis_v1",
                task="pinned-health-view-analysis",
                max_tokens=1200,
                timeout_seconds=15.0,
            )
        except PinnedHealthModelError as exc:
            raise RuntimeError(str(exc)) from exc
        if (
            result.provider != self.config.provider
            or result.model_id != self.config.model_id
        ):
            raise RuntimeError("health-model-snapshot-mismatch")
        value = result.parsed.get("analysis_text")
        if not isinstance(value, str):
            raise RuntimeError("health-view-analysis-invalid")
        cleaned = _SERVICE_MARKER.sub("", value).strip()
        if not cleaned:
            raise RuntimeError("health-view-analysis-invalid")
        return cleaned


__all__ = [
    "OwnerControlOutcome",
    "PartnerOwnerControlHandler",
    "PinnedHealthViewAnalyzer",
]

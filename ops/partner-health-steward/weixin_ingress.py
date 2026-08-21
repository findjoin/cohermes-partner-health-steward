"""Partner-only trusted Weixin health ingress orchestration."""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from health_model import (
    HealthModelConfig,
    PinnedHealthModelClient,
    PinnedHealthModelError,
)
from sidecar.recording import RECORDING_FEEDBACK_ACTION_BY_STATUS
from sidecar.protocol import (
    ACTION_HEALTH_TURN_CONTEXT_READ,
    HEALTH_TURN_CONTEXT_EVIDENCE_KIND,
)


CONSENT_ACTION = "health.recording.enable"
ADMIT_ACTION = "health.profile.message.admit"
RECENT_ACTION = "health.profile.message.recent"
PROFILE_UPDATED_MARKER = "〔健康管家：画像已更新〕"
PROCESSING_MARKER = "〔健康管家：记录处理中〕"
EXPLICIT_ENABLE_PHRASES = {"启用健康记录", "我同意启用健康记录"}


class WeixinIngressError(RuntimeError):
    """Raised when a trusted envelope or model decision fails closed."""


def _required(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WeixinIngressError(code)
    return value.strip()


def _aware_utc(value: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise WeixinIngressError("message-utc-invalid") from exc
    if parsed.tzinfo is None:
        raise WeixinIngressError("message-utc-invalid")
    # Keep sub-second trusted arrival order for destructive controls.  The
    # sidecar still stores UTC, but two independent owner turns must not become
    # indistinguishable merely because they arrived in the same wall-clock
    # second.
    return parsed.astimezone(dt.timezone.utc).isoformat()


@dataclass(frozen=True)
class TrustedWeixinEnvelope:
    sender_id: str
    message_id: str
    message_utc: str
    message_text: str
    channel: str
    profile_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sender_id", _required(self.sender_id, "sender-required"))
        object.__setattr__(self, "message_id", _required(self.message_id, "message-id-required"))
        object.__setattr__(self, "message_utc", _aware_utc(self.message_utc))
        object.__setattr__(self, "message_text", _required(self.message_text, "message-text-required"))
        object.__setattr__(self, "channel", _required(self.channel, "channel-required"))
        object.__setattr__(self, "profile_name", _required(self.profile_name, "profile-name-required"))


@dataclass(frozen=True)
class IngressOutcome:
    status: str
    tail_marker: str | None = None
    version_id: str | None = None
    evidence_id: str | None = None
    health_related: bool = False
    source_verification_required: bool = False
    health_answer_ready: bool = True
    recovery_code: str | None = None


class HealthClassifier(Protocol):
    def classify(self, envelope: TrustedWeixinEnvelope) -> Mapping[str, Any]:
        ...


class ReceiptSigner(Protocol):
    def sign_access(self, **payload: Any) -> str:
        ...

    def sign_ingress(self, **payload: Any) -> str:
        ...


CLASSIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "decision",
        "health_related",
        "requires_source_verification",
    ],
    "properties": {
        "decision": {"type": "string", "enum": ["none", "candidate"]},
        "health_related": {"type": "boolean"},
        "requires_source_verification": {"type": "boolean"},
        "candidate": {"type": "object"},
    },
}


class HermesFreshHealthClassifier:
    """Make one fresh, fail-closed call to the snapshotted Hermes endpoint.

    Hermes' general auxiliary caller intentionally falls back to another
    provider on capacity errors.  That behavior is useful for ordinary agent
    tasks but is not acceptable for health data because an unapproved fallback
    would change the data recipient.  This adapter still applies PluginLlm's
    trust policy, then uses the pinned Hermes provider client directly once.
    """

    def __init__(self, plugin_llm: Any, config: HealthModelConfig) -> None:
        self.plugin_llm = plugin_llm
        self.config = config
        self._client = PinnedHealthModelClient(plugin_llm, config)

    def classify(self, envelope: TrustedWeixinEnvelope) -> Mapping[str, Any]:
        payload = {
            "sender_id": envelope.sender_id,
            "message_id": envelope.message_id,
            "message_utc": envelope.message_utc,
            "channel": envelope.channel,
            "profile_name": envelope.profile_name,
            "message_text": envelope.message_text,
        }
        instructions = (
                "Classify only this authenticated Weixin message. Set health_related=true "
                "for a health question or directly stated health fact, otherwise false. "
                "Set requires_source_verification=true only when the owner asks a medical "
                "or health question that needs an authoritative source; a health statement "
                "or measurement without a question must set it false. "
                "Return decision=none when no personal evidence should be written. For a "
                "directly stated personal health fact, return "
                "decision=candidate and a sidecar profile candidate whose evidence fields "
                "refer exactly to this message. Do not diagnose or use outside context."
            )
        try:
            result = self._client.complete_structured(
                instructions=instructions,
                payload=payload,
                json_schema=CLASSIFICATION_SCHEMA,
                schema_name="health_weixin_candidate_v1",
                task="health-weixin-classification",
                max_tokens=1200,
                timeout_seconds=15.0,
            )
        except PinnedHealthModelError as exc:
            raise WeixinIngressError(str(exc)) from exc
        if (
            result.provider != self.config.provider
            or result.model_id != self.config.model_id
        ):
            raise WeixinIngressError("health-model-snapshot-mismatch")
        parsed = result.parsed
        if not isinstance(parsed, Mapping):
            raise WeixinIngressError("health-classification-invalid")
        decision = parsed.get("decision")
        health_related = parsed.get("health_related")
        requires_source_verification = parsed.get(
            "requires_source_verification"
        )
        if (
            not isinstance(health_related, bool)
            or not isinstance(requires_source_verification, bool)
            or (requires_source_verification and not health_related)
        ):
            raise WeixinIngressError("health-classification-invalid")
        if decision == "none":
            return {
                "decision": "none",
                "health_related": health_related,
                "requires_source_verification": requires_source_verification,
            }
        if (
            decision != "candidate"
            or health_related is not True
            or not isinstance(parsed.get("candidate"), Mapping)
        ):
            raise WeixinIngressError("health-classification-invalid")
        return {
            "decision": "candidate",
            "health_related": True,
            "requires_source_verification": requires_source_verification,
            "candidate": dict(parsed["candidate"]),
        }


def _is_explicit_enable(text: str) -> bool:
    normalized = text.strip().rstrip("。！!").strip()
    return normalized in EXPLICIT_ENABLE_PHRASES


class PartnerWeixinIngressCoordinator:
    """Coordinate consent, fresh classification, signing and sidecar admission."""

    def __init__(
        self,
        adapter: Any,
        signer: ReceiptSigner,
        classifier: HealthClassifier,
        *,
        expected_owner_sender_id: str,
        subject: str = "profile",
    ) -> None:
        self.adapter = adapter
        self.signer = signer
        self.classifier = classifier
        self.expected_owner_sender_id = _required(
            expected_owner_sender_id, "expected-owner-required"
        )
        self.subject = _required(subject, "subject-required")

    def is_current_owner(self, sender_id: str) -> bool:
        """Ask the sidecar for the active owner without reading health content."""
        normalized = str(sender_id or "").strip()
        if not normalized:
            return False
        status_reader = getattr(self.adapter, "health_recording_status", None)
        if callable(status_reader):
            try:
                status = status_reader(self.subject, normalized)
                return status in {
                    "recording_enabled",
                    "recording_stopped",
                } or (
                    status == "recording_disabled"
                    and normalized == self.expected_owner_sender_id
                )
            except Exception:
                return False
        return normalized == self.expected_owner_sender_id

    @staticmethod
    def _check_deadline(
        cancellation_requested: Callable[[], bool] | None,
        deadline_monotonic: float | None,
    ) -> None:
        if (
            (cancellation_requested is not None and cancellation_requested())
            or (
                deadline_monotonic is not None
                and time.monotonic() >= deadline_monotonic
            )
        ):
            raise WeixinIngressError("health-ingress-deadline-exceeded")

    def prepare(
        self,
        envelope: TrustedWeixinEnvelope,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
        deadline_monotonic: float | None = None,
    ) -> IngressOutcome | None:
        """Apply ordered consent/status checks without invoking the model."""
        self._check_deadline(cancellation_requested, deadline_monotonic)
        if envelope.channel != "weixin" or envelope.profile_name != "partner":
            return IngressOutcome("not-authorized")

        if (
            _is_explicit_enable(envelope.message_text)
            and envelope.sender_id == self.expected_owner_sender_id
        ):
            self._check_deadline(cancellation_requested, deadline_monotonic)
            token = self.signer.sign_access(
                action=CONSENT_ACTION,
                subject=self.subject,
                actor_sender_id=envelope.sender_id,
                target_sender_id=envelope.sender_id,
                message_id=envelope.message_id,
                message_utc=envelope.message_utc,
            )
            self._check_deadline(cancellation_requested, deadline_monotonic)
            result = self.adapter.enable_health_recording(
                self.subject,
                envelope.sender_id,
                envelope.message_id,
                envelope.message_utc,
                token,
            )
            if result.get("enabled") is not True:
                raise WeixinIngressError("recording-enable-not-confirmed")
            recovery_code = result.get("recovery_code")
            if recovery_code is not None and (
                not isinstance(recovery_code, str) or not recovery_code.strip()
            ):
                raise WeixinIngressError("recovery-code-invalid-response")
            return IngressOutcome(
                "recording-enabled",
                recovery_code=(
                    recovery_code.strip()
                    if isinstance(recovery_code, str)
                    else None
                ),
            )

        if not self.is_current_owner(envelope.sender_id):
            return IngressOutcome("not-authorized")
        if not self.adapter.health_recording_enabled(
            self.subject, envelope.sender_id
        ):
            return IngressOutcome("recording-disabled")

        return None

    def classify_and_admit(
        self,
        envelope: TrustedWeixinEnvelope,
        *,
        attempt_utc: str | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        deadline_monotonic: float | None = None,
        health_decision_observed: Callable[[bool, bool], None] | None = None,
    ) -> IngressOutcome:
        """Classify under a sidecar lease serialized with stop-recording."""
        self._check_deadline(cancellation_requested, deadline_monotonic)
        lease_id = self.adapter.begin_recording_attempt(
            self.subject, envelope.sender_id
        )
        try:
            return self._classify_and_admit_leased(
                envelope,
                attempt_utc=attempt_utc,
                cancellation_requested=cancellation_requested,
                deadline_monotonic=deadline_monotonic,
                health_decision_observed=health_decision_observed,
            )
        finally:
            self.adapter.end_recording_attempt(lease_id)

    def _classify_and_admit_leased(
        self,
        envelope: TrustedWeixinEnvelope,
        *,
        attempt_utc: str | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        deadline_monotonic: float | None = None,
        health_decision_observed: Callable[[bool, bool], None] | None = None,
    ) -> IngressOutcome:
        """Run one fresh model call while its sidecar lease is active."""

        self._check_deadline(cancellation_requested, deadline_monotonic)
        decision = self.classifier.classify(envelope)
        self._check_deadline(cancellation_requested, deadline_monotonic)
        if not isinstance(decision, Mapping):
            raise WeixinIngressError("health-classification-invalid")
        health_related = (
            decision.get("health_related") is True
            or decision.get("decision") == "candidate"
        )
        source_verification_required = (
            decision.get("requires_source_verification") is True
        )
        if health_decision_observed is not None:
            if not callable(health_decision_observed):
                raise WeixinIngressError("health-decision-observer-invalid")
            health_decision_observed(
                health_related,
                source_verification_required,
            )
        if decision.get("decision") == "none":
            if health_related:
                return IngressOutcome(
                    "health-related",
                    health_related=True,
                    source_verification_required=source_verification_required,
                )
            normalized_attempt_utc = _aware_utc(attempt_utc or envelope.message_utc)
            self._check_deadline(cancellation_requested, deadline_monotonic)
            token = self.signer.sign_ingress(
                action=RECENT_ACTION,
                subject=self.subject,
                sender_id=envelope.sender_id,
                message_id=envelope.message_id,
                message_utc=envelope.message_utc,
                message_text=envelope.message_text,
                evidence_kind="ordinary_chat",
                channel=envelope.channel,
                profile_name=envelope.profile_name,
                attempt_utc=normalized_attempt_utc,
            )
            self._check_deadline(cancellation_requested, deadline_monotonic)
            self.adapter.remember_recent_owner_message(
                self.subject,
                envelope.sender_id,
                envelope.message_id,
                envelope.message_utc,
                envelope.message_text,
                "ordinary_chat",
                token,
                attempt_utc=normalized_attempt_utc,
                channel=envelope.channel,
                profile_name=envelope.profile_name,
            )
            return IngressOutcome("no-health-candidate")
        candidate = decision.get("candidate")
        if not isinstance(candidate, Mapping):
            raise WeixinIngressError("health-classification-invalid")
        evidence_kind = _required(
            candidate.get("evidence_kind"), "candidate-evidence-kind-required"
        )
        normalized_attempt_utc = _aware_utc(attempt_utc or envelope.message_utc)
        self._check_deadline(cancellation_requested, deadline_monotonic)
        token = self.signer.sign_ingress(
            action=ADMIT_ACTION,
            subject=self.subject,
            sender_id=envelope.sender_id,
            message_id=envelope.message_id,
            message_utc=envelope.message_utc,
            message_text=envelope.message_text,
            evidence_kind=evidence_kind,
            channel=envelope.channel,
            profile_name=envelope.profile_name,
            attempt_utc=normalized_attempt_utc,
        )
        self._check_deadline(cancellation_requested, deadline_monotonic)
        result = self.adapter.admit_consented_profile_candidate(
            subject=self.subject,
            sender_id=envelope.sender_id,
            message_id=envelope.message_id,
            message_utc=envelope.message_utc,
            attempt_utc=normalized_attempt_utc,
            message_text=envelope.message_text,
            evidence_kind=evidence_kind,
            channel=envelope.channel,
            profile_name=envelope.profile_name,
            verification_token=token,
            candidate=candidate,
        )
        changed = result.get("changed") is True
        return IngressOutcome(
            "profile-updated" if changed else "no-profile-change",
            tail_marker=PROFILE_UPDATED_MARKER if changed else None,
            version_id=(str(result.get("version_id")) if changed else None),
            evidence_id=(str(result.get("evidence_id")) if changed else None),
            health_related=True,
            source_verification_required=source_verification_required,
        )

    def profile_message_admitted(self, envelope: TrustedWeixinEnvelope) -> bool:
        """Confirm a prior commit without reusing an old receipt or LLM call."""
        if (
            envelope.channel != "weixin"
            or envelope.profile_name != "partner"
            or not self.is_current_owner(envelope.sender_id)
        ):
            return False
        return bool(
            self.adapter.profile_message_admitted(
                self.subject, envelope.sender_id, envelope.message_id
            )
        )

    def health_recording_enabled(self, envelope: TrustedWeixinEnvelope) -> bool:
        """Read only the sidecar lifecycle bit for a trusted owner envelope."""
        if (
            envelope.channel != "weixin"
            or envelope.profile_name != "partner"
            or not self.is_current_owner(envelope.sender_id)
        ):
            return False
        return bool(
            self.adapter.health_recording_enabled(
                self.subject, envelope.sender_id
            )
        )

    def load_health_turn_context(
        self, envelope: TrustedWeixinEnvelope
    ) -> Mapping[str, Any]:
        """Read the post-admission context for exactly this trusted turn."""
        if (
            envelope.channel != "weixin"
            or envelope.profile_name != "partner"
            or not self.is_current_owner(envelope.sender_id)
        ):
            raise WeixinIngressError("health-turn-context-not-authorized")
        attempt_utc = dt.datetime.now(dt.timezone.utc).replace(
            microsecond=0
        ).isoformat()
        token = self.signer.sign_ingress(
            action=ACTION_HEALTH_TURN_CONTEXT_READ,
            subject=self.subject,
            sender_id=envelope.sender_id,
            message_id=envelope.message_id,
            message_utc=envelope.message_utc,
            message_text=envelope.message_text,
            evidence_kind=HEALTH_TURN_CONTEXT_EVIDENCE_KIND,
            channel=envelope.channel,
            profile_name=envelope.profile_name,
            attempt_utc=attempt_utc,
        )
        result = self.adapter.read_health_turn_context(
            subject=self.subject,
            sender_id=envelope.sender_id,
            message_id=envelope.message_id,
            message_utc=envelope.message_utc,
            message_text=envelope.message_text,
            channel=envelope.channel,
            profile_name=envelope.profile_name,
            attempt_utc=attempt_utc,
            verification_token=token,
        )
        if not isinstance(result, Mapping):
            raise WeixinIngressError("health-turn-context-invalid-response")
        return dict(result)

    def send_feedback(
        self, envelope: TrustedWeixinEnvelope, feedback_status: str
    ) -> Mapping[str, Any]:
        try:
            action = RECORDING_FEEDBACK_ACTION_BY_STATUS[feedback_status]
        except KeyError as exc:
            raise WeixinIngressError("recording-feedback-invalid") from exc
        token = self.signer.sign_access(
            action=action,
            subject=self.subject,
            actor_sender_id=envelope.sender_id,
            target_sender_id=envelope.sender_id,
            message_id=envelope.message_id,
            message_utc=envelope.message_utc,
        )
        result = self.adapter.send_recording_feedback(
            self.subject,
            envelope.sender_id,
            envelope.message_id,
            envelope.message_utc,
            token,
            feedback_status,
        )
        if not isinstance(result, Mapping):
            raise WeixinIngressError("recording-feedback-invalid-response")
        return dict(result)

    def process(self, envelope: TrustedWeixinEnvelope) -> IngressOutcome:
        prepared = self.prepare(envelope)
        if prepared is not None:
            return prepared
        return self.classify_and_admit(envelope)

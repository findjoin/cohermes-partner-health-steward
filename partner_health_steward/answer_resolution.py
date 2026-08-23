"""Content-free authority values for strict model answer resolution.

The model transport result, the outer effect ledger, and the committed answer
resolution make different claims.  This module keeps those claims separate:

* :class:`ModelEffectReport` records body-free facts about the inner model
  attempt and derives, but does not store, the corresponding outer effect
  status;
* :class:`ModelEffectRef` binds a resolution to the exact persisted report;
* :class:`ModelAnswerResolution` records either a fixed failed-closed outcome
  or the digests of an already validated, deterministically rendered answer.

No type in this module can carry model output, candidate content, or reply
text.  The only reply text exposed here is the fixed failed-closed owner
prompt returned by :func:`render_failed_closed`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass


class AnswerResolutionViolation(ValueError):
    """A value cannot cross the model-answer authority seam."""


MODEL_EFFECT_STATUSES = frozenset(
    {"not-started", "completed", "incomplete", "failed", "unknown"}
)
OUTER_EFFECT_STATUSES = frozenset({"accepted", "rejected", "unknown"})
ANSWER_RESOLUTION_STATUSES = frozenset({"failed-closed", "rendered"})
_COMPLETED_REJECTION_REASONS = frozenset(
    {
        "transport-requested-model-drift",
        "fallback-observed",
        "actual-model-drift",
        "model-output-truncated",
        "strict-schema-error",
    }
)


def _mapping(
    value: object,
    fields: frozenset[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != fields:
        raise AnswerResolutionViolation(f"invalid {name}")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > 16384:
        raise AnswerResolutionViolation(f"invalid {name}")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _sha(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise AnswerResolutionViolation(f"invalid {name}")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise AnswerResolutionViolation(f"invalid {name}") from exc
    return text


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise AnswerResolutionViolation(f"invalid {name}")
    return value


def _stable_digest(value: object) -> str:
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError) as exc:
        raise AnswerResolutionViolation("invalid canonical answer value") from exc
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


FAILED_CLOSED_TEMPLATE_ID = "health-answer-failed-closed"
FAILED_CLOSED_TEMPLATE_VERSION = "1"
FAILED_CLOSED_REPLY_TEXT = "这次健康处理无法安全完成，且没有形成或记录健康回答。"
FAILED_CLOSED_TEMPLATE_DIGEST = _stable_digest(
    {
        "reply_text": FAILED_CLOSED_REPLY_TEXT,
        "template_id": FAILED_CLOSED_TEMPLATE_ID,
        "template_version": FAILED_CLOSED_TEMPLATE_VERSION,
    }
)


@dataclass(frozen=True)
class ModelEffectReport:
    """Body-free facts observed at the single controlled model boundary.

    ``model_status`` is the inner model/transport status.  It is deliberately
    not the outer effect-ledger status: a terminal, explicit model failure is
    still an ``accepted`` outer effect because the controlled effect happened
    and its result is known.  ``result_digest`` binds the omitted transport
    result without persisting its structured output here.
    """

    model_status: str
    transport_attempted: bool
    terminal_proven: bool
    requested_model: str
    actual_model: str | None
    fallback_observed: bool
    truncated: bool
    reason_code: str | None
    result_digest: str

    def __post_init__(self) -> None:
        if type(self.model_status) is not str or self.model_status not in MODEL_EFFECT_STATUSES:
            raise AnswerResolutionViolation("invalid inner model status")
        for value, name in (
            (self.transport_attempted, "transport attempted marker"),
            (self.terminal_proven, "terminal proven marker"),
            (self.fallback_observed, "fallback observed marker"),
            (self.truncated, "truncation marker"),
        ):
            _boolean(value, name)
        _text(self.requested_model, "requested model")
        _optional_text(self.actual_model, "actual model")
        _optional_text(self.reason_code, "model effect reason code")
        _sha(self.result_digest, "model result digest")

        if not self.transport_attempted:
            if (
                self.model_status != "not-started"
                or self.terminal_proven
                or self.actual_model is not None
                or self.fallback_observed
                or self.truncated
                or self.reason_code is None
            ):
                raise AnswerResolutionViolation("invalid not-started model effect")
            return

        if self.model_status == "not-started":
            raise AnswerResolutionViolation("attempted transport cannot be not-started")
        if self.model_status == "unknown":
            if self.terminal_proven or self.reason_code is None:
                raise AnswerResolutionViolation("invalid unknown model effect")
            return
        if not self.terminal_proven:
            raise AnswerResolutionViolation("known model result must prove terminality")
        if self.actual_model is None:
            raise AnswerResolutionViolation("known model result requires actual model")
        if self.model_status == "completed":
            if self.reason_code is not None and self.reason_code not in _COMPLETED_REJECTION_REASONS:
                raise AnswerResolutionViolation("invalid completed model rejection reason")
            if (self.fallback_observed or self.truncated) and self.reason_code is None:
                raise AnswerResolutionViolation(
                    "unsafe completed model result requires a rejection reason"
                )
        elif self.reason_code is None:
            raise AnswerResolutionViolation("non-completed model result requires a reason")

    @property
    def outer_effect_status(self) -> str:
        """Return the Ticket 110 outer status implied by these model facts."""

        if not self.transport_attempted:
            return "rejected"
        if self.model_status == "unknown":
            return "unknown"
        return "accepted"

    @property
    def digest(self) -> str:
        """Content address of this complete body-free report."""

        return _stable_digest(self.to_storage())

    def to_storage(self) -> dict[str, object]:
        return {
            "model_status": self.model_status,
            "transport_attempted": self.transport_attempted,
            "terminal_proven": self.terminal_proven,
            "requested_model": self.requested_model,
            "actual_model": self.actual_model,
            "fallback_observed": self.fallback_observed,
            "truncated": self.truncated,
            "reason_code": self.reason_code,
            "result_digest": self.result_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "ModelEffectReport":
        fields = _mapping(
            value,
            frozenset(
                {
                    "model_status",
                    "transport_attempted",
                    "terminal_proven",
                    "requested_model",
                    "actual_model",
                    "fallback_observed",
                    "truncated",
                    "reason_code",
                    "result_digest",
                }
            ),
            "model effect report",
        )
        return cls(
            model_status=_text(fields["model_status"], "inner model status"),
            transport_attempted=_boolean(
                fields["transport_attempted"], "transport attempted marker"
            ),
            terminal_proven=_boolean(
                fields["terminal_proven"], "terminal proven marker"
            ),
            requested_model=_text(fields["requested_model"], "requested model"),
            actual_model=_optional_text(fields["actual_model"], "actual model"),
            fallback_observed=_boolean(
                fields["fallback_observed"], "fallback observed marker"
            ),
            truncated=_boolean(fields["truncated"], "truncation marker"),
            reason_code=_optional_text(
                fields["reason_code"], "model effect reason code"
            ),
            result_digest=_sha(fields["result_digest"], "model result digest"),
        )


@dataclass(frozen=True)
class ModelEffectRef:
    """Reference to one effect and the exact body-free report for it."""

    effect_id: str
    report_digest: str

    def __post_init__(self) -> None:
        _text(self.effect_id, "model effect identifier")
        _sha(self.report_digest, "model effect report digest")

    @property
    def digest(self) -> str:
        return _stable_digest(self.to_storage())

    def to_storage(self) -> dict[str, object]:
        return {
            "effect_id": self.effect_id,
            "report_digest": self.report_digest,
        }

    @classmethod
    def from_storage(cls, value: object) -> "ModelEffectRef":
        fields = _mapping(
            value,
            frozenset({"effect_id", "report_digest"}),
            "model effect reference",
        )
        return cls(
            effect_id=_text(fields["effect_id"], "model effect identifier"),
            report_digest=_sha(
                fields["report_digest"], "model effect report digest"
            ),
        )


_RESOLUTION_COMMON_FIELDS = frozenset(
    {
        "status",
        "effect_ref",
        "strict_request_digest",
        "model_authority_digest",
        "template_id",
        "template_version",
        "template_digest",
    }
)
_FAILED_CLOSED_STORAGE_FIELDS = _RESOLUTION_COMMON_FIELDS | frozenset({"reason_code"})
_RENDERED_STORAGE_FIELDS = _RESOLUTION_COMMON_FIELDS | frozenset(
    {"candidate_digest", "rendered_reply_digest"}
)


@dataclass(frozen=True)
class ModelAnswerResolution:
    """Content-free committed outcome of one strict model-answer request.

    ``strict_request_digest`` binds the exact validated request payload.
    ``model_authority_digest`` binds the current route, consent, capability,
    and strict-schema authority used to judge that request.

    The two statuses have disjoint storage shapes.  ``failed-closed`` requires
    a reason and the fixed owner-prompt template, and cannot carry candidate or
    rendered-reply digests.  ``rendered`` requires both digests and an effect
    reference, and cannot carry a failure reason.
    """

    status: str
    strict_request_digest: str
    model_authority_digest: str
    template_id: str
    template_version: str
    template_digest: str
    effect_ref: ModelEffectRef | None = None
    reason_code: str | None = None
    candidate_digest: str | None = None
    rendered_reply_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in ANSWER_RESOLUTION_STATUSES:
            raise AnswerResolutionViolation("invalid model answer resolution status")
        _sha(self.strict_request_digest, "strict model request digest")
        _sha(self.model_authority_digest, "model authority digest")
        _text(self.template_id, "answer template identifier")
        _text(self.template_version, "answer template version")
        _sha(self.template_digest, "answer template digest")
        if self.effect_ref is not None and type(self.effect_ref) is not ModelEffectRef:
            raise AnswerResolutionViolation("invalid model effect reference")
        _optional_text(self.reason_code, "answer resolution reason code")

        if self.status == "failed-closed":
            if self.reason_code is None:
                raise AnswerResolutionViolation("failed-closed reason required")
            if self.candidate_digest is not None or self.rendered_reply_digest is not None:
                raise AnswerResolutionViolation(
                    "failed-closed resolution cannot carry answer digests"
                )
            if (
                self.template_id != FAILED_CLOSED_TEMPLATE_ID
                or self.template_version != FAILED_CLOSED_TEMPLATE_VERSION
                or self.template_digest != FAILED_CLOSED_TEMPLATE_DIGEST
            ):
                raise AnswerResolutionViolation(
                    "failed-closed resolution requires the fixed template"
                )
            return

        if self.reason_code is not None:
            raise AnswerResolutionViolation("rendered resolution cannot carry a reason")
        if type(self.effect_ref) is not ModelEffectRef:
            raise AnswerResolutionViolation("rendered resolution requires an effect reference")
        _sha(self.candidate_digest, "validated candidate digest")
        _sha(self.rendered_reply_digest, "rendered owner reply digest")

    @classmethod
    def failed_closed(
        cls,
        *,
        strict_request_digest: str,
        model_authority_digest: str,
        reason_code: str,
        effect_ref: ModelEffectRef | None = None,
    ) -> "ModelAnswerResolution":
        """Construct the only valid failed-closed resolution shape."""

        return cls(
            status="failed-closed",
            strict_request_digest=strict_request_digest,
            model_authority_digest=model_authority_digest,
            template_id=FAILED_CLOSED_TEMPLATE_ID,
            template_version=FAILED_CLOSED_TEMPLATE_VERSION,
            template_digest=FAILED_CLOSED_TEMPLATE_DIGEST,
            effect_ref=effect_ref,
            reason_code=reason_code,
        )

    @classmethod
    def rendered(
        cls,
        *,
        strict_request_digest: str,
        model_authority_digest: str,
        template_id: str,
        template_version: str,
        template_digest: str,
        effect_ref: ModelEffectRef,
        candidate_digest: str,
        rendered_reply_digest: str,
    ) -> "ModelAnswerResolution":
        """Construct the only valid successfully rendered resolution shape."""

        return cls(
            status="rendered",
            strict_request_digest=strict_request_digest,
            model_authority_digest=model_authority_digest,
            template_id=template_id,
            template_version=template_version,
            template_digest=template_digest,
            effect_ref=effect_ref,
            candidate_digest=candidate_digest,
            rendered_reply_digest=rendered_reply_digest,
        )

    @property
    def digest(self) -> str:
        """Content address of the complete body-free resolution."""

        return _stable_digest(self.to_storage())

    def to_storage(self) -> dict[str, object]:
        common: dict[str, object] = {
            "status": self.status,
            "effect_ref": (
                None if self.effect_ref is None else self.effect_ref.to_storage()
            ),
            "strict_request_digest": self.strict_request_digest,
            "model_authority_digest": self.model_authority_digest,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_digest": self.template_digest,
        }
        if self.status == "failed-closed":
            common["reason_code"] = self.reason_code
            return common
        common["candidate_digest"] = self.candidate_digest
        common["rendered_reply_digest"] = self.rendered_reply_digest
        return common

    @classmethod
    def from_storage(cls, value: object) -> "ModelAnswerResolution":
        if type(value) is not dict:
            raise AnswerResolutionViolation("invalid model answer resolution")
        status = value.get("status")
        if status == "failed-closed":
            fields = _mapping(
                value,
                _FAILED_CLOSED_STORAGE_FIELDS,
                "failed-closed model answer resolution",
            )
            reason_code: str | None = _text(
                fields["reason_code"], "answer resolution reason code"
            )
            candidate_digest: str | None = None
            rendered_reply_digest: str | None = None
        elif status == "rendered":
            fields = _mapping(
                value,
                _RENDERED_STORAGE_FIELDS,
                "rendered model answer resolution",
            )
            reason_code = None
            candidate_digest = _sha(
                fields["candidate_digest"], "validated candidate digest"
            )
            rendered_reply_digest = _sha(
                fields["rendered_reply_digest"], "rendered owner reply digest"
            )
        else:
            raise AnswerResolutionViolation("invalid model answer resolution status")

        raw_effect_ref = fields["effect_ref"]
        effect_ref = (
            None
            if raw_effect_ref is None
            else ModelEffectRef.from_storage(raw_effect_ref)
        )
        return cls(
            status=status,
            strict_request_digest=_sha(
                fields["strict_request_digest"], "strict model request digest"
            ),
            model_authority_digest=_sha(
                fields["model_authority_digest"], "model authority digest"
            ),
            template_id=_text(fields["template_id"], "answer template identifier"),
            template_version=_text(
                fields["template_version"], "answer template version"
            ),
            template_digest=_sha(
                fields["template_digest"], "answer template digest"
            ),
            effect_ref=effect_ref,
            reason_code=reason_code,
            candidate_digest=candidate_digest,
            rendered_reply_digest=rendered_reply_digest,
        )


def render_failed_closed(resolution: ModelAnswerResolution) -> str:
    """Render the one approved owner prompt for a failed-closed resolution."""

    if type(resolution) is not ModelAnswerResolution or resolution.status != "failed-closed":
        raise AnswerResolutionViolation("failed-closed resolution required")
    if (
        resolution.template_id != FAILED_CLOSED_TEMPLATE_ID
        or resolution.template_version != FAILED_CLOSED_TEMPLATE_VERSION
        or resolution.template_digest != FAILED_CLOSED_TEMPLATE_DIGEST
        or resolution.candidate_digest is not None
        or resolution.rendered_reply_digest is not None
    ):
        raise AnswerResolutionViolation("invalid fixed failed-closed template")
    return FAILED_CLOSED_REPLY_TEXT


__all__ = [
    "ANSWER_RESOLUTION_STATUSES",
    "FAILED_CLOSED_REPLY_TEXT",
    "FAILED_CLOSED_TEMPLATE_DIGEST",
    "FAILED_CLOSED_TEMPLATE_ID",
    "FAILED_CLOSED_TEMPLATE_VERSION",
    "MODEL_EFFECT_STATUSES",
    "OUTER_EFFECT_STATUSES",
    "AnswerResolutionViolation",
    "ModelAnswerResolution",
    "ModelEffectRef",
    "ModelEffectReport",
    "render_failed_closed",
]

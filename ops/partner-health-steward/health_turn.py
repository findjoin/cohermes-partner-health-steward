"""Controlled orchestration for one authenticated partner health turn.

The handler has no ordinary-chat fallback and no profile, task, or tool-write
interface.  External source text crosses this module only as an explicitly
untrusted, public card projection into the pinned no-tools responder.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from health_turn_answer import (
    FreshSourceCardSummary,
    HealthTurnAnswerInput,
)
from sidecar.health_turn_context import MAX_HEALTH_TURN_EVIDENCE_IDS
from weixin_ingress import (
    PROCESSING_MARKER,
    PROFILE_UPDATED_MARKER,
    IngressOutcome,
    TrustedWeixinEnvelope,
)


SOURCE_VERIFYING_MESSAGE = "正在核验资料"
SOURCE_UNAVAILABLE_NOTICE = "当前无法核验所需权威资料。"
ANSWER_UNAVAILABLE_NOTICE = "健康回答暂时不可用。"
MAX_SOURCE_FETCH_SECONDS = 20.0
MAX_CATALOG_BYTES = 64 * 1024

_LEGACY_PROFILE_UPDATED_MARKER = "〔健康管家：档案已更新〕"
_ALLOWED_TAIL_MARKERS = frozenset(
    {PROFILE_UPDATED_MARKER, PROCESSING_MARKER, _LEGACY_PROFILE_UPDATED_MARKER}
)
_PUBLIC_CARD_FIELDS = (
    "card_id",
    "url",
    "source_type",
    "title",
    "version_hash",
    "key_excerpt",
    "tags",
    "fetched_utc",
    "review_due_utc",
    "untrusted_data",
)


class HealthTurnError(RuntimeError):
    """Raised when a health turn cannot satisfy its controlled interface."""


class HealthTurnCancelled(HealthTurnError):
    """Raised when Gateway shutdown cancels a worker before channel handoff."""


class HealthSourceCatalogError(HealthTurnError):
    """Raised when the static source catalog is malformed or ambiguous."""


def _required_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HealthTurnError(code)
    return value.strip()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HealthSourceCatalogError("health-source-catalog-duplicate-key")
        result[key] = value
    return result


class HealthSourceCatalog:
    """Immutable deterministic keyword-to-exact-HTTPS-URL catalog.

    The JSON interface is deliberately small and strict::

        {
          "catalog_schema_version": 1,
          "keyword_urls": {"睡眠": "https://www.who.int/sleep"}
        }

    Longest matching keyword wins; equal-length matches use lexical order.
    URLs are never read from the model output or the inbound message.
    """

    def __init__(self, keyword_urls: Mapping[str, str]) -> None:
        if not isinstance(keyword_urls, Mapping) or not keyword_urls:
            raise HealthSourceCatalogError("health-source-catalog-empty")
        normalized: dict[str, tuple[str, str]] = {}
        for raw_keyword, raw_url in keyword_urls.items():
            if not isinstance(raw_keyword, str) or raw_keyword != raw_keyword.strip():
                raise HealthSourceCatalogError("health-source-keyword-invalid")
            keyword = raw_keyword.strip()
            if not keyword:
                raise HealthSourceCatalogError("health-source-keyword-invalid")
            folded = keyword.casefold()
            if folded in normalized:
                raise HealthSourceCatalogError("health-source-keyword-duplicate")
            if not isinstance(raw_url, str) or raw_url != raw_url.strip():
                raise HealthSourceCatalogError("health-source-url-invalid")
            parsed = urlparse(raw_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise HealthSourceCatalogError("health-source-url-invalid")
            normalized[folded] = (keyword, raw_url)
        self._entries = tuple(
            sorted(
                normalized.values(),
                key=lambda item: (-len(item[0].casefold()), item[0].casefold()),
            )
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "HealthSourceCatalog":
        catalog_path = Path(path)
        try:
            if catalog_path.stat().st_size > MAX_CATALOG_BYTES:
                raise HealthSourceCatalogError("health-source-catalog-too-large")
            payload = json.loads(
                catalog_path.read_text(encoding="utf-8"),
                object_pairs_hook=_strict_object,
            )
        except HealthSourceCatalogError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HealthSourceCatalogError(
                "health-source-catalog-unavailable"
            ) from exc
        if not isinstance(payload, Mapping) or set(payload) != {
            "catalog_schema_version",
            "keyword_urls",
        }:
            raise HealthSourceCatalogError("health-source-catalog-invalid")
        if payload.get("catalog_schema_version") != 1:
            raise HealthSourceCatalogError("health-source-catalog-invalid")
        keyword_urls = payload.get("keyword_urls")
        if not isinstance(keyword_urls, Mapping):
            raise HealthSourceCatalogError("health-source-catalog-invalid")
        return cls(keyword_urls)

    def url_for(self, text: str) -> str | None:
        if not isinstance(text, str) or not text.strip():
            return None
        folded = text.casefold()
        for keyword, url in self._entries:
            if keyword.casefold() in folded:
                return url
        return None


@dataclass(frozen=True)
class HealthTurnResult:
    """Observable result of the two idempotent channel handoffs."""

    final_text: str
    verification_status: str
    source_cards: tuple[Mapping[str, Any], ...]
    status_delivery_key: str | None
    final_delivery_key: str


class HealthTurnHandler:
    """Answer one classified health turn through controlled injected seams."""

    def __init__(
        self,
        *,
        context_loader: Any,
        source_reader: Any,
        responder: Any,
        channel: Any,
        source_catalog: HealthSourceCatalog,
    ) -> None:
        for dependency, method, code in (
            (context_loader, "load_health_turn_context", "context-loader-invalid"),
            (source_reader, "query_sources", "source-reader-invalid"),
            (responder, "answer", "pinned-responder-invalid"),
            (channel, "send_once", "send-once-channel-invalid"),
        ):
            if not callable(getattr(dependency, method, None)):
                raise HealthTurnError(code)
        if not isinstance(source_catalog, HealthSourceCatalog):
            raise HealthTurnError("health-source-catalog-invalid")
        self.context_loader = context_loader
        self.source_reader = source_reader
        self.responder = responder
        self.channel = channel
        self.source_catalog = source_catalog

    @staticmethod
    def _delivery_key(envelope: TrustedWeixinEnvelope, purpose: str) -> str:
        canonical = json.dumps(
            {
                "channel": envelope.channel,
                "message_id": envelope.message_id,
                "profile_name": envelope.profile_name,
                "sender_id": envelope.sender_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()[:32]
        return f"health-turn:{digest}:{purpose}"

    @staticmethod
    def _context_values(
        context: Any,
    ) -> tuple[
        str | None,
        str,
        tuple[str, ...],
        tuple[dict[str, Any], ...],
    ]:
        if not isinstance(context, Mapping) or context.get(
            "context_schema_version"
        ) != 1:
            raise HealthTurnError("health-turn-context-invalid")
        version_id = context.get("current_version_id")
        if version_id is not None:
            version_id = _required_text(
                version_id, "health-turn-context-invalid"
            )
        summary = context.get("profile_summary_zh")
        if not isinstance(summary, str) or len(summary.strip()) > 300:
            raise HealthTurnError("health-turn-context-invalid")
        evidence = context.get("evidence_ids")
        if (
            not isinstance(evidence, (list, tuple))
            or len(evidence) > MAX_HEALTH_TURN_EVIDENCE_IDS
        ):
            raise HealthTurnError("health-turn-context-invalid")
        evidence_ids = tuple(
            _required_text(value, "health-turn-context-invalid")
            for value in evidence
        )
        if len(evidence_ids) != len(set(evidence_ids)):
            raise HealthTurnError("health-turn-context-invalid")
        source_status = context.get("source_status")
        source_cards = context.get("source_cards")
        if (
            not isinstance(source_status, Mapping)
            or not isinstance(source_cards, list)
            or not isinstance(source_status.get("verified"), bool)
        ):
            raise HealthTurnError("health-turn-context-invalid")
        public_cards = HealthTurnHandler._public_cards(
            {
                "verified": source_status.get("verified"),
                "source": source_status.get("source"),
                "cards": source_cards,
            }
        )
        if source_status.get("verified") is True and not public_cards:
            raise HealthTurnError("health-turn-context-invalid")
        return version_id, summary.strip(), evidence_ids, public_cards

    @staticmethod
    def _public_cards(
        result: Any, *, selected_url: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        if not isinstance(result, Mapping) or result.get("verified") is not True:
            return ()
        if result.get("source") not in {"card", "whitelist-fetch"}:
            return ()
        cards = result.get("cards")
        if not isinstance(cards, list) or not cards:
            return ()
        projected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for raw in cards:
            if not isinstance(raw, Mapping) or raw.get("untrusted_data") is not True:
                return ()
            if not all(field in raw for field in _PUBLIC_CARD_FIELDS):
                return ()
            card = {field: raw[field] for field in _PUBLIC_CARD_FIELDS}
            for field in (
                "card_id",
                "url",
                "source_type",
                "version_hash",
                "key_excerpt",
                "fetched_utc",
                "review_due_utc",
            ):
                if not isinstance(card[field], str) or not card[field].strip():
                    return ()
                card[field] = card[field].strip()
            if not isinstance(card["title"], str):
                return ()
            card["title"] = card["title"].strip()
            parsed = urlparse(card["url"])
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                return ()
            if (
                selected_url is not None
                and result.get("source") == "whitelist-fetch"
                and card["url"] != selected_url
            ):
                return ()
            tags = card["tags"]
            if not isinstance(tags, Mapping) or not all(
                isinstance(key, str)
                and key.strip()
                and isinstance(value, (list, tuple))
                and all(isinstance(item, str) and item.strip() for item in value)
                for key, value in tags.items()
            ):
                return ()
            card["tags"] = {
                str(key): list(value) for key, value in tags.items()
            }
            card_id = str(card["card_id"])
            if card_id in seen_ids:
                return ()
            seen_ids.add(card_id)
            projected.append(card)
        return tuple(projected)

    @staticmethod
    def _answer_cards(
        cards: tuple[Mapping[str, Any], ...]
    ) -> tuple[FreshSourceCardSummary, ...]:
        return tuple(
            FreshSourceCardSummary(
                card_id=str(card["card_id"]),
                title=str(card["title"]).strip() or str(card["url"]),
                source_url=str(card["url"]),
                summary_zh=str(card["key_excerpt"]),
            )
            for card in cards
        )

    @staticmethod
    def _strip_reserved(value: Any) -> str:
        text = str(value or "")
        for marker in (
            *_ALLOWED_TAIL_MARKERS,
            SOURCE_VERIFYING_MESSAGE,
            SOURCE_UNAVAILABLE_NOTICE,
            ANSWER_UNAVAILABLE_NOTICE,
        ):
            text = text.replace(marker, "")
        lines = [line.rstrip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line.strip()).strip()

    @classmethod
    def _final_text(
        cls,
        answer_text: Any,
        *,
        verification_status: str,
        answer_failed: bool,
        tail_marker: Any,
    ) -> str:
        cleaned = cls._strip_reserved(answer_text)
        if answer_failed:
            cleaned = ANSWER_UNAVAILABLE_NOTICE
            if verification_status == "unavailable":
                cleaned = f"{cleaned}\n\n{SOURCE_UNAVAILABLE_NOTICE}"
        elif verification_status == "unavailable":
            cleaned = (
                f"{cleaned}\n\n{SOURCE_UNAVAILABLE_NOTICE}"
                if cleaned
                else SOURCE_UNAVAILABLE_NOTICE
            )
        elif not cleaned:
            cleaned = ANSWER_UNAVAILABLE_NOTICE
        marker = tail_marker if tail_marker in _ALLOWED_TAIL_MARKERS else None
        if marker:
            cleaned = f"{cleaned}\n\n{marker}"
        return cleaned

    def _send_once(
        self, envelope: TrustedWeixinEnvelope, message: str, purpose: str
    ) -> str:
        key = self._delivery_key(envelope, purpose)
        confirmed = self.channel.send_once(envelope.sender_id, message, key)
        if confirmed is not True:
            raise HealthTurnError(f"health-turn-{purpose}-delivery-unconfirmed")
        return key

    @staticmethod
    def _ensure_not_cancelled(
        cancellation_requested: Callable[[], bool] | None,
    ) -> None:
        if cancellation_requested is None:
            return
        if not callable(cancellation_requested):
            raise HealthTurnError("health-turn-cancellation-invalid")
        try:
            cancelled = cancellation_requested()
        except Exception as exc:
            raise HealthTurnCancelled("health-turn-cancelled") from exc
        if cancelled:
            raise HealthTurnCancelled("health-turn-cancelled")

    def handle(
        self,
        envelope: TrustedWeixinEnvelope,
        outcome: IngressOutcome,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> HealthTurnResult:
        """Resolve sources, call the pinned answerer, and send exactly once.

        Any context, source, or answer failure remains inside this controlled
        route.  This method has no reference to the native ordinary-chat path.
        """

        if (
            not isinstance(envelope, TrustedWeixinEnvelope)
            or not isinstance(outcome, IngressOutcome)
            or outcome.health_related is not True
        ):
            raise HealthTurnError("health-turn-required")
        self._ensure_not_cancelled(cancellation_requested)

        final_key = self._delivery_key(envelope, "final")
        if outcome.health_answer_ready is not True:
            final_text = self._final_text(
                "",
                verification_status="not_attempted",
                answer_failed=True,
                tail_marker=outcome.tail_marker,
            )
            self._ensure_not_cancelled(cancellation_requested)
            confirmed = self.channel.send_once(
                envelope.sender_id, final_text, final_key
            )
            if confirmed is not True:
                raise HealthTurnError("health-turn-final-delivery-unconfirmed")
            return HealthTurnResult(
                final_text=final_text,
                verification_status="not_attempted",
                source_cards=(),
                status_delivery_key=None,
                final_delivery_key=final_key,
            )

        status_key: str | None = None
        verification_status = (
            "unavailable"
            if outcome.source_verification_required
            else "not_required"
        )
        public_cards: tuple[dict[str, Any], ...] = ()
        answer_text = ""
        answer_failed = False

        try:
            context = self.context_loader.load_health_turn_context(envelope)
            version_id, summary, evidence_ids, public_cards = self._context_values(
                context
            )
            self._ensure_not_cancelled(cancellation_requested)
        except HealthTurnCancelled:
            raise
        except Exception:
            answer_failed = True
        else:
            if not public_cards and outcome.source_verification_required:
                self._ensure_not_cancelled(cancellation_requested)
                status_key = self._send_once(
                    envelope, SOURCE_VERIFYING_MESSAGE, "source-status"
                )
                self._ensure_not_cancelled(cancellation_requested)
                selected_url = self.source_catalog.url_for(
                    envelope.message_text
                )
                if selected_url is not None:
                    try:
                        fetched = self.source_reader.query_sources(
                            envelope.message_text,
                            source_url=selected_url,
                            timeout_seconds=MAX_SOURCE_FETCH_SECONDS,
                        )
                        self._ensure_not_cancelled(cancellation_requested)
                    except HealthTurnCancelled:
                        raise
                    except Exception:
                        fetched = None
                    public_cards = self._public_cards(
                        fetched, selected_url=selected_url
                    )
            if public_cards:
                verification_status = "verified"
            elif outcome.source_verification_required:
                verification_status = "unavailable"
            else:
                verification_status = "not_required"

            try:
                self._ensure_not_cancelled(cancellation_requested)
                answer_input = HealthTurnAnswerInput(
                    envelope=envelope,
                    current_version_id=version_id,
                    profile_summary_zh=summary,
                    relevant_evidence_ids=evidence_ids,
                    fresh_source_cards=self._answer_cards(public_cards),
                    verification_status=verification_status,
                )
                answer = self.responder.answer(answer_input)
                self._ensure_not_cancelled(cancellation_requested)
                answer_text = _required_text(
                    getattr(answer, "answer_text", None),
                    "health-turn-answer-invalid",
                )
                used_ids = getattr(answer, "used_source_card_ids", ())
                if not isinstance(used_ids, tuple) or not set(used_ids).issubset(
                    {str(card["card_id"]) for card in public_cards}
                ):
                    raise HealthTurnError("health-turn-answer-invalid")
            except HealthTurnCancelled:
                raise
            except Exception:
                answer_failed = True

        final_text = self._final_text(
            answer_text,
            verification_status=verification_status,
            answer_failed=answer_failed,
            tail_marker=outcome.tail_marker,
        )
        self._ensure_not_cancelled(cancellation_requested)
        confirmed = self.channel.send_once(
            envelope.sender_id, final_text, final_key
        )
        if confirmed is not True:
            raise HealthTurnError("health-turn-final-delivery-unconfirmed")
        return HealthTurnResult(
            final_text=final_text,
            verification_status=verification_status,
            source_cards=tuple(dict(card) for card in public_cards),
            status_delivery_key=status_key,
            final_delivery_key=final_key,
        )


__all__ = [
    "ANSWER_UNAVAILABLE_NOTICE",
    "MAX_SOURCE_FETCH_SECONDS",
    "SOURCE_UNAVAILABLE_NOTICE",
    "SOURCE_VERIFYING_MESSAGE",
    "HealthSourceCatalog",
    "HealthSourceCatalogError",
    "HealthTurnCancelled",
    "HealthTurnError",
    "HealthTurnHandler",
    "HealthTurnResult",
]

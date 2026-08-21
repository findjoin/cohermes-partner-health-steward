"""Controlled medical-source cards and bounded raw-document cache.

Source content is data only.  This module never interprets document text as
instructions and never writes profile conclusions or tasks.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import queue
import tempfile
import threading
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from .store import HealthSidecarStore, StoreError


SOURCE_SCHEMA_VERSION = 1
MAX_KEY_EXCERPT_BYTES = 8 * 1024
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_RAW_CACHE_BYTES = 200 * 1024 * 1024
MAX_METADATA_BYTES = 100 * 1024 * 1024
MAX_DAILY_DOWNLOADS = 20
MIN_DOMAIN_INTERVAL = dt.timedelta(minutes=1)
SOURCE_TYPES = {
    "public_health_alert",
    "clinical_guideline",
    "general_health_education",
}
TAG_CATEGORIES = (
    "topic",
    "symptom_behavior",
    "target_population",
    "evidence_type",
    "region_language",
    "freshness",
)
REVIEW_INTERVALS = {
    "public_health_alert": dt.timedelta(days=7),
    "clinical_guideline": dt.timedelta(days=180),
    "general_health_education": dt.timedelta(days=365),
}
DEFAULT_ALLOWED_HOSTS = {
    "nhc.gov.cn",
    "chinacdc.cn",
    "who.int",
    "cdc.gov",
    "nice.org.uk",
}
DEFAULT_TAG_SYNONYMS = {
    "topic": {
        "sleep hygiene": "sleep",
        "sleep quality": "sleep",
    },
    "symptom_behavior": {
        "sleep problem": "insomnia",
        "sleep problems": "insomnia",
    },
    "target_population": {
        "adults": "adult",
        "children": "child",
    },
    "evidence_type": {
        "guideline": "clinical_guideline",
        "clinical guideline": "clinical_guideline",
        "clinical_guideline": "clinical_guideline",
        "education": "health_education",
        "health education": "health_education",
        "public health alert": "public_health_alert",
    },
    "region_language": {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "中文": "zh-CN",
        "en": "en-US",
        "英文": "en-US",
    },
    "freshness": {
        "fresh": "current",
        "recent": "current",
        "outdated": "stale",
        "expired": "stale",
    },
}


class SourceLibraryError(StoreError):
    """A safe, content-free source-library validation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _RawWriteError(SourceLibraryError):
    def __init__(self, code: str, orphan_path: Path, storage_size: int) -> None:
        self.orphan_path = orphan_path
        self.storage_size = storage_size
        super().__init__(code)


def _now(store: HealthSidecarStore) -> dt.datetime:
    value = store.now_utc()
    if value.tzinfo is None:
        raise SourceLibraryError("clock-must-return-aware-utc")
    return value.astimezone(dt.timezone.utc).replace(microsecond=0)


def _iso(value: Any, code: str = "invalid-utc") -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceLibraryError(code)
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceLibraryError(code) from exc
    if parsed.tzinfo is None:
        raise SourceLibraryError("utc-must-be-aware")
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def _host(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise SourceLibraryError("source-url-must-be-https")
    return parsed.hostname.lower().rstrip(".")


def _allowed_host(host: str, allowed: set[str]) -> bool:
    return any(host == item or host.endswith("." + item) for item in allowed)


def _rate_domain(host: str, roots: set[str]) -> str:
    """Use the approved registrable/root domain for crawl pacing."""
    for root in sorted(roots, key=len, reverse=True):
        if host == root or host.endswith("." + root):
            return root
    pieces = host.split(".")
    return ".".join(pieces[-2:]) if len(pieces) >= 2 else host


def _default_state() -> dict[str, Any]:
    return {
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "cards": [],
        "tag_synonyms": copy.deepcopy(DEFAULT_TAG_SYNONYMS),
        "orphan_cleanup": [],
        "scan": {
            "day_utc": None,
            "download_count": 0,
            "last_fetch_by_domain": {},
            "pending_candidates": [],
        },
    }


def _source_locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.store.source_library_lock():
            return method(self, *args, **kwargs)

    return wrapper


class SourceLibrary:
    """Public source-card and bounded-cache domain seam."""

    def __init__(
        self,
        store: HealthSidecarStore,
        source_fetch: Any | None = None,
        cache_dir: str | os.PathLike[str] | None = None,
        allowed_hosts: set[str] | None = None,
        approved_guideline_hosts: set[str] | None = None,
        tag_synonyms: Mapping[str, Mapping[str, str]] | None = None,
        raw_cache_limit_bytes: int = MAX_RAW_CACHE_BYTES,
        metadata_limit_bytes: int = MAX_METADATA_BYTES,
        document_limit_bytes: int = MAX_DOCUMENT_BYTES,
    ) -> None:
        self.store = store
        self.source_fetch = source_fetch
        self.cache_dir = Path(cache_dir or store.store_path.parent / "source-cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_hosts = {
            str(host).lower().rstrip(".")
            for host in (allowed_hosts or DEFAULT_ALLOWED_HOSTS)
        }
        self.guideline_hosts = {
            str(host).lower().rstrip(".")
            for host in (approved_guideline_hosts or set())
        }
        self.raw_cache_limit_bytes = raw_cache_limit_bytes
        self.metadata_limit_bytes = metadata_limit_bytes
        self.document_limit_bytes = document_limit_bytes
        self.tag_synonyms = copy.deepcopy(DEFAULT_TAG_SYNONYMS)
        for category, values in (tag_synonyms or {}).items():
            self.tag_synonyms.setdefault(category, {}).update(
                {str(key).casefold(): str(value) for key, value in values.items()}
            )
        if min(
            raw_cache_limit_bytes, metadata_limit_bytes, document_limit_bytes
        ) < 1:
            raise SourceLibraryError("source-limits-must-be-positive")

    @_source_locked
    def ingest(self, document: Mapping[str, Any]) -> Mapping[str, Any]:
        self._drain_orphan_cleanup()
        state_for_tags = self._coerce_state(self._state())
        synonyms = copy.deepcopy(state_for_tags.get("tag_synonyms", {}))
        for category, values in self.tag_synonyms.items():
            synonyms.setdefault(category, {}).update(values)
        normalized = self._normalize_document(document, synonyms)
        card_id = normalized["card_id"]
        existing_state = self._state()
        existing = next(
            (card for card in existing_state["cards"] if card["card_id"] == card_id),
            None,
        )
        if existing is not None:
            refreshed = copy.deepcopy(existing)
            for field in (
                "title",
                "key_excerpt",
                "tags",
                "fetched_utc",
                "review_due_utc",
                "last_used_utc",
            ):
                refreshed[field] = normalized[field]

            def touch(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
                state = self._coerce_state(current)
                for card in state["cards"]:
                    if card["card_id"] == card_id:
                        card.update(refreshed)
                return state, copy.deepcopy(refreshed)

            return self.store.mutate_source_library_state(touch)

        state = self._coerce_state(existing_state)
        state_before = copy.deepcopy(state)
        state["tag_synonyms"] = synonyms
        raw_bytes = normalized.pop("_raw_bytes")
        raw_envelope = self.store.encrypt_blob(raw_bytes) if raw_bytes else b""
        storage_bytes = len(raw_envelope)
        removed_raw_paths = self._cleanup_state(state, storage_bytes)
        if self._raw_usage(state) + storage_bytes > self.raw_cache_limit_bytes:
            raise SourceLibraryError("source-cache-full")
        normalized["raw_size"] = len(raw_bytes)
        normalized["raw_storage_size"] = storage_bytes
        raw_path = self.cache_dir / f"{card_id}.blob"
        if raw_bytes:
            normalized["raw_path"] = str(raw_path)
        else:
            normalized["raw_path"] = None

        for card in state["cards"]:
            if card.get("url") == normalized["url"]:
                card["current"] = False
                card["superseded_by"] = card_id
        state["cards"].append(normalized)
        state_committed = False
        deleted_paths: list[str] = []
        cleanup_failed = False
        try:
            self._check_metadata_size(state)
            result = self.store.mutate_source_library_state(
                lambda _current: (state, copy.deepcopy(normalized))
            )
            state_committed = True
            if raw_bytes:
                self._write_encrypted_raw(raw_path, raw_envelope)
            for removed_path in removed_raw_paths:
                try:
                    Path(removed_path).unlink()
                    deleted_paths.append(removed_path)
                except OSError as exc:
                    cleanup_failed = True
                    partial = copy.deepcopy(state_before)
                    for card in partial["cards"]:
                        if card.get("raw_path") in deleted_paths:
                            card["raw_path"] = None
                            card["raw_size"] = 0
                            card["raw_storage_size"] = 0
                    if raw_path.exists():
                        try:
                            os.unlink(raw_path)
                        except OSError:
                            partial.setdefault("orphan_cleanup", []).append(
                                {"path": str(raw_path), "storage_size": storage_bytes}
                            )
                    self.store.mutate_source_library_state(
                        lambda _current: (partial, None)
                    )
                    raise SourceLibraryError("source-cache-cleanup-failed") from exc
        except Exception as exc:
            if state_committed and not deleted_paths and not cleanup_failed:
                # State was committed but raw-file creation failed.  Restore
                # the prior card set and account for an undeletable new blob.
                rollback = copy.deepcopy(state_before)
                if isinstance(exc, _RawWriteError):
                    rollback.setdefault("orphan_cleanup", []).append(
                        {
                            "path": str(exc.orphan_path),
                            "storage_size": exc.storage_size,
                        }
                    )
                if raw_path.exists():
                    try:
                        os.unlink(raw_path)
                    except OSError:
                        rollback.setdefault("orphan_cleanup", []).append(
                            {"path": str(raw_path), "storage_size": storage_bytes}
                        )
                self.store.mutate_source_library_state(
                    lambda _current: (rollback, None)
                )
            raise
        self.store.append_audit_event(
            "source_card_write",
            {"card_id": card_id, "host": normalized["host"], "version_hash": normalized["version_hash"]},
        )
        return result

    @_source_locked
    def lookup(
        self,
        query: str,
        source_url: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> Mapping[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise SourceLibraryError("source-query-required")
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= 20
        ):
            raise SourceLibraryError("source-timeout-out-of-range")
        if source_url is not None:
            requested_host = _host(source_url)
            if not self._is_allowed(requested_host):
                raise SourceLibraryError("source-origin-not-allowed")
        now = _now(self.store)
        state = self._state()
        terms = [term.casefold() for term in query.split() if term.strip()]
        current_cards = [
            card
            for card in state["cards"]
            if card.get("current", True)
            and self._card_matches(card, terms)
        ]
        fresh = [card for card in current_cards if not self._is_stale(card, now)]
        if fresh:
            fresh.sort(key=lambda card: str(card.get("fetched_utc", "")), reverse=True)
            self._touch_cards({card["card_id"] for card in fresh})
            return self._result(True, "card", fresh)
        if current_cards and source_url is None:
            return self._result(False, "card", [], reason="source-card-stale")
        if source_url is None:
            return self._result(False, "none", [], reason="verification-unavailable")
        host = _host(source_url)
        if not self._is_allowed(host):
            raise SourceLibraryError("source-origin-not-allowed")
        if self.source_fetch is None:
            return self._result(False, "none", [], reason="verification-unavailable")
        try:
            fetched = self._fetch_on_deadline(source_url, timeout_seconds)
        except TimeoutError:
            return self._result(False, "none", [], reason="verification-timeout")
        except Exception:
            return self._result(False, "none", [], reason="verification-unavailable")
        if not isinstance(fetched, Mapping) or not fetched:
            return self._result(False, "none", [], reason="verification-unavailable")
        if str(fetched.get("url", "")).strip() != source_url:
            return self._result(False, "none", [], reason="verification-unavailable")
        try:
            card = self.ingest(fetched)
        except SourceLibraryError:
            return self._result(False, "none", [], reason="verification-unavailable")
        return self._result(True, "whitelist-fetch", [card])

    def _fetch_on_deadline(
        self, source_url: str, timeout_seconds: float | None
    ) -> Any:
        if timeout_seconds is None:
            return self.source_fetch.fetch(source_url)

        completed: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def fetch() -> None:
            try:
                value = self.source_fetch.fetch(
                    source_url, timeout_seconds=float(timeout_seconds)
                )
            except BaseException as exc:
                completed.put((False, exc))
            else:
                completed.put((True, value))

        threading.Thread(
            target=fetch,
            name="health-source-on-demand-fetch",
            daemon=True,
        ).start()
        try:
            succeeded, value = completed.get(timeout=float(timeout_seconds))
        except queue.Empty as exc:
            raise TimeoutError("source-verification-timeout") from exc
        if not succeeded:
            raise value
        return value

    @_source_locked
    def scan(
        self,
        candidates: list[str] | tuple[str, ...],
        *,
        continue_check: Callable[[], bool] | None = None,
    ) -> Mapping[str, Any]:
        if not isinstance(candidates, (list, tuple)):
            raise SourceLibraryError("scan-candidates-must-be-list")

        def require_active() -> None:
            if continue_check is not None and not continue_check():
                raise SourceLibraryError("health-recording-stopped")

        with self.store._state_lock:
            require_active()
        state = self._coerce_state(self._state())
        now = _now(self.store)
        scan = state["scan"]
        day = now.date().isoformat()
        if scan.get("day_utc") != day:
            scan["day_utc"] = day
            scan["download_count"] = 0

        def persist_scan_progress(pending_values: list[str]) -> None:
            """Persist bounded-fetch counters and the exact remaining queue.

            A later owner stop may discard the fetched payload, but it must
            not erase attempts or completed downloads that already consumed
            the daily/domain allowance, requeue completed work, or lose the
            candidate whose fetch was interrupted.
            """

            scan["pending_candidates"] = list(dict.fromkeys(pending_values))

            def update_progress(
                current: Mapping[str, Any],
            ) -> tuple[Mapping[str, Any], None]:
                latest = self._coerce_state(current) if current else _default_state()
                latest["scan"] = copy.deepcopy(scan)
                self._check_metadata_size(latest)
                return latest, None

            with self.store._state_lock:
                require_active()
                self.store.mutate_source_library_state(update_progress)

        pending = list(dict.fromkeys([*scan.get("pending_candidates", []), *candidates]))
        downloaded: list[Mapping[str, Any]] = []
        deferred: list[str] = []
        rejected: list[Mapping[str, str]] = []
        for index, url in enumerate(pending):
            remaining = pending[index + 1 :]
            if scan["download_count"] >= MAX_DAILY_DOWNLOADS:
                deferred.append(url)
                continue
            try:
                host = _host(url)
                if not self._is_allowed(host):
                    raise SourceLibraryError("source-origin-not-allowed")
            except SourceLibraryError as exc:
                rejected.append({"url": str(url), "reason": exc.code})
                persist_scan_progress([*deferred, *remaining])
                continue
            rate_domain = _rate_domain(
                host, self.allowed_hosts | self.guideline_hosts
            )
            last = scan["last_fetch_by_domain"].get(rate_domain)
            if last:
                elapsed = now - dt.datetime.fromisoformat(last)
                if elapsed < MIN_DOMAIN_INTERVAL:
                    deferred.append(url)
                    persist_scan_progress([*deferred, *remaining])
                    continue
            scan["download_count"] += 1
            scan["last_fetch_by_domain"][rate_domain] = now.isoformat()
            persist_scan_progress([*deferred, url, *remaining])
            if self.source_fetch is None:
                rejected.append({"url": url, "reason": "verification-unavailable"})
                persist_scan_progress([*deferred, *remaining])
                continue
            try:
                with self.store._state_lock:
                    require_active()
                fetched = self.source_fetch.fetch(url)
                if not isinstance(fetched, Mapping) or not fetched:
                    raise SourceLibraryError("verification-unavailable")
                if str(fetched.get("url", "")).strip() != url:
                    raise SourceLibraryError("source-url-mismatch")
                # The external fetch is intentionally outside the state lock:
                # an owner stop must not wait for an unresponsive endpoint.
                # Ingest and its state commit are guarded by one state-lock
                # acquisition, so either they linearize before stop or they
                # observe stopped and perform no sidecar write.
                with self.store._state_lock:
                    require_active()
                    downloaded.append(self.ingest(fetched))
                    persist_scan_progress([*deferred, *remaining])
            except SourceLibraryError as exc:
                if exc.code == "health-recording-stopped":
                    raise
                rejected.append({"url": url, "reason": exc.code})
                persist_scan_progress([*deferred, *remaining])
            except Exception as exc:
                rejected.append({"url": url, "reason": getattr(exc, "code", "verification-unavailable")})
                persist_scan_progress([*deferred, *remaining])
        scan["pending_candidates"] = deferred
        result = {"downloaded": downloaded, "deferred": deferred, "rejected": rejected}

        def update_scan(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
            latest = self._coerce_state(current) if current else _default_state()
            latest["scan"] = copy.deepcopy(scan)
            self._check_metadata_size(latest)
            return latest, result

        with self.store._state_lock:
            require_active()
            self.store.mutate_source_library_state(update_scan)
        return {"downloaded": downloaded, "deferred": deferred, "rejected": rejected}

    @_source_locked
    def reference(
        self, card_id: str, conclusion_id: str | None = None, task_id: str | None = None
    ) -> bool:
        if not conclusion_id and not task_id:
            raise SourceLibraryError("source-reference-required")
        return self._update_references(card_id, conclusion_id, task_id, add=True)

    @_source_locked
    def unreference(
        self, card_id: str, conclusion_id: str | None = None, task_id: str | None = None
    ) -> bool:
        if not conclusion_id and not task_id:
            raise SourceLibraryError("source-reference-required")
        return self._update_references(card_id, conclusion_id, task_id, add=False)

    @_source_locked
    def cache_usage(self) -> Mapping[str, int]:
        state = self._coerce_state(self._state())
        return {
            "raw_bytes": self._raw_usage(state),
            "metadata_bytes": self._metadata_usage(state),
        }

    def _state(self) -> Mapping[str, Any]:
        return self.store.read_source_library_state() or _default_state()

    @staticmethod
    def _coerce_state(raw: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise SourceLibraryError("source-state-corrupt")
        state = copy.deepcopy(dict(raw))
        if state.get("source_schema_version") != SOURCE_SCHEMA_VERSION:
            raise SourceLibraryError("unsupported-source-schema")
        state.setdefault("cards", [])
        state.setdefault("tag_synonyms", copy.deepcopy(DEFAULT_TAG_SYNONYMS))
        state.setdefault("orphan_cleanup", [])
        state.setdefault("scan", _default_state()["scan"])
        return state

    def _normalize_document(
        self, document: Mapping[str, Any], tag_synonyms: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(document, Mapping):
            raise SourceLibraryError("source-document-must-be-object")
        url = document.get("url")
        if not isinstance(url, str) or not url.strip():
            raise SourceLibraryError("source-url-required")
        url = url.strip()
        host = _host(url)
        source_type = str(document.get("source_type", "")).strip()
        source_type = {
            "public_health": "public_health_alert",
            "public-health-alert": "public_health_alert",
            "health_education": "general_health_education",
            "general-health-education": "general_health_education",
            "guideline": "clinical_guideline",
            "clinical-guideline": "clinical_guideline",
        }.get(source_type, source_type)
        if source_type not in SOURCE_TYPES:
            raise SourceLibraryError("invalid-source-type")
        if not self._approved_for_type(host, source_type):
            raise SourceLibraryError("source-origin-not-allowed")
        excerpt = document.get("key_excerpt")
        if not isinstance(excerpt, str) or not excerpt.strip():
            raise SourceLibraryError("source-excerpt-required")
        if len(excerpt.encode("utf-8")) > MAX_KEY_EXCERPT_BYTES:
            raise SourceLibraryError("source-excerpt-too-large")
        raw = document.get("raw_document", b"")
        if isinstance(raw, str):
            raw_bytes = raw.encode("utf-8")
        elif isinstance(raw, bytes):
            raw_bytes = raw
        else:
            raise SourceLibraryError("raw-document-must-be-bytes")
        if len(raw_bytes) > self.document_limit_bytes:
            raise SourceLibraryError("source-document-too-large")
        version_hash = document.get("version_hash")
        if not isinstance(version_hash, str) or not version_hash.strip():
            version_hash = hashlib.sha256(raw_bytes or excerpt.encode("utf-8")).hexdigest()
        version_hash = version_hash.strip()
        tags = self._normalize_tags(document.get("tags"), tag_synonyms)
        fetched_utc = _now(self.store)
        default_due = fetched_utc + REVIEW_INTERVALS[source_type]
        declared = document.get("declared_valid_until_utc")
        declared_days = document.get("declared_validity_days")
        if declared is not None:
            declared_dt = dt.datetime.fromisoformat(_iso(declared))
            review_due = min(default_due, declared_dt)
        elif declared_days is not None:
            if isinstance(declared_days, bool) or not isinstance(declared_days, (int, float)) or declared_days <= 0:
                raise SourceLibraryError("invalid-declared-validity")
            review_due = min(default_due, fetched_utc + dt.timedelta(days=float(declared_days)))
        else:
            review_due = default_due
        card_id = hashlib.sha256(f"{url}\n{version_hash}".encode("utf-8")).hexdigest()[:24]
        return {
            "card_id": card_id,
            "url": url,
            "host": host,
            "source_type": source_type,
            "title": str(document.get("title", "")).strip()[:300],
            "version_hash": version_hash,
            "key_excerpt": excerpt.strip(),
            "tags": tags,
            "fetched_utc": fetched_utc.isoformat(),
            "review_due_utc": review_due.isoformat(),
            "current": True,
            "untrusted_data": True,
            "personal_facts": [],
            "task_actions": [],
            "conclusion_refs": [],
            "task_refs": [],
            "last_used_utc": fetched_utc.isoformat(),
            "superseded_by": None,
            "_raw_bytes": raw_bytes,
        }

    def _normalize_tags(
        self, raw: Any, tag_synonyms: Mapping[str, Any]
    ) -> dict[str, list[str]]:
        if not isinstance(raw, Mapping):
            raise SourceLibraryError("source-tags-must-be-object")
        if set(raw) != set(TAG_CATEGORIES):
            raise SourceLibraryError("source-tags-must-use-six-fixed-categories")
        normalized: dict[str, list[str]] = {}
        for category in TAG_CATEGORIES:
            values = raw[category]
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, (list, tuple)) or not values:
                raise SourceLibraryError("source-tag-values-required")
            result = []
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    raise SourceLibraryError("source-tag-value-invalid")
                value = value.strip()
                result.append(
                    tag_synonyms.get(category, {}).get(
                        value.casefold(), value.casefold()
                    )
                )
            normalized[category] = sorted(set(result))
        return normalized

    def _is_allowed(self, host: str) -> bool:
        return _allowed_host(host, self.allowed_hosts | self.guideline_hosts)

    def _approved_for_type(self, host: str, source_type: str) -> bool:
        if _allowed_host(host, self.allowed_hosts):
            return True
        return source_type == "clinical_guideline" and _allowed_host(
            host, self.guideline_hosts
        )

    @staticmethod
    def _card_matches(card: Mapping[str, Any], terms: list[str]) -> bool:
        haystack = " ".join(
            [
                str(card.get("title", "")),
                str(card.get("key_excerpt", "")),
                " ".join(
                    str(value)
                    for values in card.get("tags", {}).values()
                    for value in values
                ),
            ]
        ).casefold()
        return all(term in haystack for term in terms)

    @staticmethod
    def _is_stale(card: Mapping[str, Any], now: dt.datetime) -> bool:
        try:
            return dt.datetime.fromisoformat(str(card["review_due_utc"])) <= now
        except (KeyError, TypeError, ValueError):
            return True

    @staticmethod
    def _result(verified: bool, source: str, cards: list[Mapping[str, Any]], reason: str | None = None) -> dict[str, Any]:
        result = {
            "verified": verified,
            "source": source,
            "cards": [copy.deepcopy(dict(card)) for card in cards],
            "personal_facts": [],
            "task_actions": [],
            "untrusted_data": True,
        }
        if reason:
            result["reason"] = reason
        return result

    def _touch_cards(self, card_ids: set[str]) -> None:
        now = _now(self.store).isoformat()

        def touch(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], bool]:
            state = self._coerce_state(current)
            for card in state["cards"]:
                if card["card_id"] in card_ids:
                    card["last_used_utc"] = now
            return state, True

        self.store.mutate_source_library_state(touch)

    def _update_references(
        self, card_id: str, conclusion_id: str | None, task_id: str | None, add: bool
    ) -> bool:
        def update(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], bool]:
            state = self._coerce_state(current)
            for card in state["cards"]:
                if card["card_id"] != card_id:
                    continue
                for field, value in (("conclusion_refs", conclusion_id), ("task_refs", task_id)):
                    if value is None:
                        continue
                    refs = list(card.get(field, []))
                    if add and value not in refs:
                        refs.append(value)
                    if not add:
                        refs = [item for item in refs if item != value]
                    card[field] = refs
                return state, True
            raise SourceLibraryError("source-card-not-found")

        return self.store.mutate_source_library_state(update)

    def _cleanup_state(self, state: dict[str, Any], needed: int) -> list[str]:
        removed_paths: list[str] = []
        if self._raw_usage(state) + needed <= self.raw_cache_limit_bytes:
            return removed_paths
        candidates = [
            card
            for card in state["cards"]
            if card.get("raw_size", 0)
            and not card.get("conclusion_refs")
            and not card.get("task_refs")
        ]
        candidates.sort(key=lambda card: str(card.get("last_used_utc", "")))
        for card in candidates:
            if self._raw_usage(state) + needed <= self.raw_cache_limit_bytes:
                break
            raw_path = card.get("raw_path")
            if raw_path:
                removed_paths.append(str(raw_path))
            card["raw_path"] = None
            card["raw_size"] = 0
            card["raw_storage_size"] = 0
        return removed_paths

    def _drain_orphan_cleanup(self) -> None:
        state = self._coerce_state(self._state())
        pending = list(state.get("orphan_cleanup", []))
        if not pending:
            return
        remaining: list[dict[str, Any]] = []
        for entry in pending:
            path = Path(str(entry.get("path", "")))
            try:
                os.unlink(path)
            except FileNotFoundError:
                continue
            except OSError:
                remaining.append(entry)
        if len(remaining) != len(pending):
            state["orphan_cleanup"] = remaining
            self.store.mutate_source_library_state(lambda _current: (state, None))

    @staticmethod
    def _raw_usage(state: Mapping[str, Any]) -> int:
        card_bytes = sum(
            int(card.get("raw_storage_size", card.get("raw_size", 0)))
            for card in state.get("cards", [])
        )
        orphan_bytes = sum(
            int(entry.get("storage_size", entry.get("raw_size", 0)))
            for entry in state.get("orphan_cleanup", [])
        )
        return card_bytes + orphan_bytes

    @staticmethod
    def _metadata_usage(state: Mapping[str, Any]) -> int:
        return len(json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def _check_metadata_size(self, state: Mapping[str, Any]) -> None:
        if self._metadata_usage(state) > self.metadata_limit_bytes:
            raise SourceLibraryError("source-metadata-full")

    def _write_encrypted_raw(self, path: Path, envelope: bytes) -> None:
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(envelope)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, path)
        finally:
            if descriptor != -1:
                os.close(descriptor)
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise _RawWriteError(
                    "source-cache-temp-cleanup-failed",
                    Path(temp_name),
                    len(envelope),
                ) from exc

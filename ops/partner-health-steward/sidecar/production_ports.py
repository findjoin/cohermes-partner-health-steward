"""Fail-closed production adapters for scheduled health work.

The health sidecar deliberately owns this boundary.  It never receives a
Gateway plugin object, partner profile directory, or partner delivery ledger.
Instead it reads a dedicated sidecar configuration and its own restricted
credential files, then exposes the existing controlled ports to the stateful
sidecar service.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from health_model import HealthModelConfig, PinnedHealthModelClient

from .daily_runner import DAILY_REVIEW_INSTRUCTIONS, DAILY_REVIEW_PLAN_SCHEMA
from .ports import FileMemoryProjection, HealthStewardPorts
from .sources import MAX_DOCUMENT_BYTES, SOURCE_TYPES, TAG_CATEGORIES
from .store import FileKeyManager, SystemClock
from .weixin_delivery import HermesWeixinTransport, WeixinHealthChannel


MAX_SOURCE_FETCH_SECONDS = 20.0
MAX_SOURCE_METADATA_BYTES = 128 * 1024


class ProductionPortConfigurationError(RuntimeError):
    """Raised when a production-only adapter cannot be built safely."""


def _required(environment: Mapping[str, str], key: str, code: str) -> str:
    value = environment.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProductionPortConfigurationError(code)
    value = value.strip()
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ProductionPortConfigurationError(code)
    return value


def _file_path(value: str, code: str) -> Path:
    path = Path(value).expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ProductionPortConfigurationError(code)
    return path


def _directory_path(value: str, code: str) -> Path:
    path = Path(value).expanduser().resolve()
    if path.is_symlink() or not path.is_dir():
        raise ProductionPortConfigurationError(code)
    return path


def _sidecar_writable_path(value: str, code: str) -> Path:
    path = Path(value).expanduser().resolve()
    # This is an account-bound safety check, independent of the systemd
    # InaccessiblePaths defence.  A future unit-file regression must not make
    # a partner-owned ledger silently usable by the sidecar.
    if any(part.lower() == "hermes-partner" for part in path.parts):
        raise ProductionPortConfigurationError(code)
    return path


def _read_private_text(path: Path, code: str) -> str:
    try:
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ProductionPortConfigurationError(code)
        value = path.read_text(encoding="utf-8").strip()
    except ProductionPortConfigurationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ProductionPortConfigurationError(code) from exc
    if not value or "\x00" in value or "\r" in value or "\n" in value:
        raise ProductionPortConfigurationError(code)
    return value


def _canonical_https_url(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProductionPortConfigurationError(code)
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ProductionPortConfigurationError(code)
    host = parsed.hostname.lower().rstrip(".")
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    return urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))


def _https_base_url(value: str, code: str) -> str:
    normalized = _canonical_https_url(value, code)
    return normalized.rstrip("/") or normalized


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionPortConfigurationError("source-metadata-invalid")
        result[key] = value
    return result


def _validate_source_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"source_type", "title", "key_excerpt", "tags"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ProductionPortConfigurationError("source-metadata-invalid")
    source_type = value.get("source_type")
    title = value.get("title")
    excerpt = value.get("key_excerpt")
    tags = value.get("tags")
    if (
        not isinstance(source_type, str)
        or source_type not in SOURCE_TYPES
        or not isinstance(title, str)
        or not title.strip()
        or len(title) > 300
        or not isinstance(excerpt, str)
        or not excerpt.strip()
        or len(excerpt.encode("utf-8")) > 8 * 1024
        or not isinstance(tags, Mapping)
        or set(tags) != set(TAG_CATEGORIES)
    ):
        raise ProductionPortConfigurationError("source-metadata-invalid")
    normalized_tags: dict[str, list[str]] = {}
    for category in TAG_CATEGORIES:
        raw_values = tags[category]
        if isinstance(raw_values, str):
            raw_values = [raw_values]
        if not isinstance(raw_values, (list, tuple)) or not raw_values:
            raise ProductionPortConfigurationError("source-metadata-invalid")
        values = []
        for item in raw_values:
            if not isinstance(item, str) or not item.strip():
                raise ProductionPortConfigurationError("source-metadata-invalid")
            values.append(item.strip())
        normalized_tags[category] = list(dict.fromkeys(values))
    return {
        "source_type": source_type,
        "title": title.strip(),
        "key_excerpt": excerpt.strip(),
        "tags": normalized_tags,
    }


class _RejectRedirect(HTTPRedirectHandler):
    """Never follow a source redirect before its destination is checked."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        del request, fp, code, msg, headers, newurl
        return None


def _open_without_redirects(request: Request, timeout: float) -> Any:
    return build_opener(_RejectRedirect()).open(request, timeout=timeout)


class ApprovedSourceFetch:
    """Fetch only static, exact HTTPS source entries with bounded bytes."""

    def __init__(
        self,
        documents: Mapping[str, Mapping[str, Any]],
        *,
        opener: Callable[[Request, float], Any] | None = None,
    ) -> None:
        if not isinstance(documents, Mapping) or not documents:
            raise ProductionPortConfigurationError("source-metadata-invalid")
        normalized: dict[str, dict[str, Any]] = {}
        for raw_url, metadata in documents.items():
            url = _canonical_https_url(raw_url, "source-metadata-invalid")
            if url in normalized:
                raise ProductionPortConfigurationError("source-metadata-invalid")
            normalized[url] = _validate_source_metadata(metadata)
        self._documents = normalized
        self._opener = opener or _open_without_redirects

    @classmethod
    def from_file(
        cls,
        path: str | os.PathLike[str],
        *,
        opener: Callable[[Request, float], Any] | None = None,
    ) -> "ApprovedSourceFetch":
        metadata_path = _file_path(str(path), "source-metadata-unavailable")
        try:
            if metadata_path.stat().st_size > MAX_SOURCE_METADATA_BYTES:
                raise ProductionPortConfigurationError("source-metadata-invalid")
            payload = json.loads(
                metadata_path.read_text(encoding="utf-8"),
                object_pairs_hook=_strict_json_object,
            )
        except ProductionPortConfigurationError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductionPortConfigurationError("source-metadata-unavailable") from exc
        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"schema_version", "documents"}
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("documents"), Mapping)
        ):
            raise ProductionPortConfigurationError("source-metadata-invalid")
        return cls(payload["documents"], opener=opener)

    def fetch(
        self, url: str, timeout_seconds: float | None = None
    ) -> Mapping[str, Any]:
        requested = _canonical_https_url(url, "source-url-not-whitelisted")
        metadata = self._documents.get(requested)
        if metadata is None:
            raise ProductionPortConfigurationError("source-url-not-whitelisted")
        timeout = MAX_SOURCE_FETCH_SECONDS if timeout_seconds is None else timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < float(timeout) <= MAX_SOURCE_FETCH_SECONDS
        ):
            raise ProductionPortConfigurationError("source-fetch-timeout-invalid")
        response = None
        try:
            response = self._opener(
                Request(requested, headers={"User-Agent": "hermes-health-sidecar/1"}),
                float(timeout),
            )
            status = getattr(response, "status", getattr(response, "code", 200))
            if status is None:
                status = 200
            if not isinstance(status, int) or not 200 <= status < 300:
                raise ProductionPortConfigurationError("source-fetch-rejected")
            final_raw = getattr(response, "geturl", lambda: getattr(response, "url", ""))()
            final_url = _canonical_https_url(final_raw, "source-redirect-refused")
            if final_url != requested:
                raise ProductionPortConfigurationError("source-redirect-refused")
            raw_document = response.read(MAX_DOCUMENT_BYTES + 1)
            if not isinstance(raw_document, bytes) or len(raw_document) > MAX_DOCUMENT_BYTES:
                raise ProductionPortConfigurationError("source-document-too-large")
        except ProductionPortConfigurationError:
            raise
        except Exception as exc:
            raise ProductionPortConfigurationError("source-fetch-unavailable") from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        return {
            "url": requested,
            "version_hash": hashlib.sha256(raw_document).hexdigest(),
            "raw_document": raw_document,
            **metadata,
        }


@dataclass(frozen=True)
class _PinnedHealthPolicy:
    plugin_id: str
    allow_provider_override: bool = True
    allow_model_override: bool = True
    allow_any_provider: bool = False
    allowed_providers: frozenset[str] | None = None
    allow_any_model: bool = False
    allowed_models: frozenset[str] | None = None
    allow_agent_id_override: bool = False
    allow_profile_override: bool = True


class _SidecarPinnedModelFacade:
    """Minimal trusted facade required by Hermes' pinned structured client."""

    _plugin_id = "health-sidecar"

    def __init__(self, config: HealthModelConfig) -> None:
        self._policy = _PinnedHealthPolicy(
            plugin_id=self._plugin_id,
            allowed_providers=frozenset({config.provider.casefold()}),
            allowed_models=frozenset({config.model_id.casefold()}),
        )

    def _policy_loader(self, plugin_id: str) -> _PinnedHealthPolicy:
        if plugin_id != self._plugin_id:
            raise RuntimeError("sidecar-pinned-model-plugin-mismatch")
        return self._policy

    @staticmethod
    def _json_response_format(
        *, json_mode: bool, json_schema: Mapping[str, Any] | None
    ) -> Mapping[str, Any] | None:
        if json_schema is not None:
            return {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "health_sidecar_structured_output",
                        "schema": dict(json_schema),
                        "strict": False,
                    },
                }
            }
        if json_mode:
            return {"response_format": {"type": "json_object"}}
        return None


DISPATCH_DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "reason"],
    "properties": {
        "decision": {"type": "string", "enum": ["send", "skip"]},
        "message": {"type": "string", "maxLength": 2000},
        "reason": {"type": "string", "minLength": 1, "maxLength": 200},
    },
}


class PinnedHealthDispatchModel:
    """Fresh no-tools daily-review and dispatch calls through one pinned model."""

    def __init__(
        self,
        config: HealthModelConfig,
        *,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not isinstance(config, HealthModelConfig):
            raise ProductionPortConfigurationError("sidecar-health-model-config-invalid")
        self.config = config
        self._client = client or PinnedHealthModelClient(
            _SidecarPinnedModelFacade(config), config, api_key=api_key
        )

    def complete(self, prompt: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
        return self.complete_fresh(prompt, context, "health-dispatch:direct")

    def complete_fresh(
        self, prompt: str, context: Mapping[str, Any], session_id: str
    ) -> Mapping[str, Any]:
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or not isinstance(context, Mapping)
            or not isinstance(session_id, str)
            or not session_id.strip()
            or not session_id.startswith("health-dispatch:")
        ):
            raise ProductionPortConfigurationError("health-dispatch-request-invalid")
        try:
            result = self._client.complete_structured(
                instructions=prompt.strip(),
                payload=dict(context),
                json_schema=DISPATCH_DECISION_SCHEMA,
                schema_name="health_dispatch_decision",
                task="health-dispatch",
                max_tokens=800,
                timeout_seconds=15.0,
            )
            parsed = getattr(result, "parsed", None)
        except ProductionPortConfigurationError:
            raise
        except Exception as exc:
            raise ProductionPortConfigurationError("health-dispatch-model-unavailable") from exc
        if not isinstance(parsed, Mapping):
            raise ProductionPortConfigurationError("health-dispatch-model-invalid")
        return dict(parsed)

    def complete_daily_review(self, snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
        """Make one fresh daily plan without a Hermes chat/session object."""
        if not isinstance(snapshot, Mapping):
            raise ProductionPortConfigurationError("health-daily-review-request-invalid")
        try:
            result = self._client.complete_structured(
                instructions=DAILY_REVIEW_INSTRUCTIONS,
                payload=dict(snapshot),
                json_schema=DAILY_REVIEW_PLAN_SCHEMA,
                schema_name="health_daily_review_plan",
                task="health-daily-review",
                max_tokens=1200,
                timeout_seconds=20.0,
            )
            parsed = getattr(result, "parsed", None)
        except ProductionPortConfigurationError:
            raise
        except Exception as exc:
            raise ProductionPortConfigurationError(
                "health-daily-review-model-unavailable"
            ) from exc
        if not isinstance(parsed, Mapping):
            raise ProductionPortConfigurationError("health-daily-review-model-invalid")
        return dict(parsed)


def _ensure_pinned_hermes_source(source_root: Path) -> None:
    source_text = str(source_root)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    try:
        module = importlib.import_module("agent")
        module_path = Path(str(getattr(module, "__file__", ""))).resolve()
        module_path.relative_to(source_root)
    except (ImportError, ValueError, OSError) as exc:
        raise ProductionPortConfigurationError(
            "pinned-health-model-runtime-unavailable"
        ) from exc


@dataclass(frozen=True)
class _ProductionPortConfiguration:
    health_model_config_path: Path
    health_model_api_key_path: Path
    hermes_source_root: Path
    accepted_hermes_version: str
    weixin_token_path: Path
    weixin_base_url: str
    weixin_cdn_base_url: str
    delivery_ledger_path: Path
    source_metadata_path: Path
    memory_projection_path: Path
    subject: str


class ProductionPortsFactory:
    """Build one real port set after the sidecar store is available for audit."""

    def __init__(self, configuration: _ProductionPortConfiguration) -> None:
        self.configuration = configuration
        self.clock = SystemClock()
        self.key_manager = FileKeyManager()

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        memory_projection_path: str | os.PathLike[str] | None = None,
        subject: str | None = None,
    ) -> "ProductionPortsFactory":
        env = os.environ if environment is None else environment
        health_model_config_path = _file_path(
            _required(
                env,
                "HEALTH_SIDECAR_HEALTH_MODEL_CONFIG",
                "sidecar-health-model-config-required",
            ),
            "sidecar-health-model-config-unavailable",
        )
        health_model_api_key_path = _file_path(
            _required(
                env,
                "HEALTH_SIDECAR_HEALTH_MODEL_API_KEY_PATH",
                "sidecar-health-model-api-key-required",
            ),
            "sidecar-health-model-api-key-unavailable",
        )
        projection = str(
            memory_projection_path
            or _required(
                env,
                "HEALTH_SIDECAR_MEMORY_PROJECTION_PATH",
                "sidecar-memory-projection-path-required",
            )
        ).strip()
        profile_subject = str(
            subject
            or env.get("HEALTH_SIDECAR_SUBJECT", "profile")
        ).strip()
        if not profile_subject:
            raise ProductionPortConfigurationError("sidecar-subject-required")
        configuration = _ProductionPortConfiguration(
            health_model_config_path=health_model_config_path,
            health_model_api_key_path=health_model_api_key_path,
            hermes_source_root=_directory_path(
                _required(
                    env,
                    "HEALTH_SIDECAR_HERMES_SOURCE_ROOT",
                    "sidecar-hermes-source-root-required",
                ),
                "sidecar-hermes-source-root-unavailable",
            ),
            accepted_hermes_version=_required(
                env,
                "HEALTH_SIDECAR_ACCEPTED_HERMES_VERSION",
                "sidecar-accepted-hermes-version-required",
            ),
            weixin_token_path=_file_path(
                _required(
                    env,
                    "HEALTH_SIDECAR_WEIXIN_TOKEN_PATH",
                    "sidecar-weixin-token-required",
                ),
                "sidecar-weixin-token-unavailable",
            ),
            weixin_base_url=_https_base_url(
                _required(
                    env,
                    "HEALTH_SIDECAR_WEIXIN_BASE_URL",
                    "sidecar-weixin-base-url-required",
                ),
                "sidecar-weixin-base-url-invalid",
            ),
            weixin_cdn_base_url=_https_base_url(
                _required(
                    env,
                    "HEALTH_SIDECAR_WEIXIN_CDN_BASE_URL",
                    "sidecar-weixin-cdn-url-required",
                ),
                "sidecar-weixin-cdn-url-invalid",
            ),
            delivery_ledger_path=_sidecar_writable_path(
                _required(
                    env,
                    "HEALTH_SIDECAR_DELIVERY_LEDGER_PATH",
                    "sidecar-delivery-ledger-required",
                ),
                "sidecar-delivery-ledger-must-be-sidecar-owned",
            ),
            source_metadata_path=_file_path(
                _required(
                    env,
                    "HEALTH_SIDECAR_SOURCE_METADATA",
                    "sidecar-source-metadata-required",
                ),
                "source-metadata-unavailable",
            ),
            memory_projection_path=Path(projection).expanduser().resolve(),
            subject=profile_subject,
        )
        return cls(configuration)

    def build(self, audit_sink: Any) -> HealthStewardPorts:
        if not callable(getattr(audit_sink, "append_audit_event_once", None)):
            raise ProductionPortConfigurationError("sidecar-delivery-audit-unavailable")
        config = self.configuration
        _ensure_pinned_hermes_source(config.hermes_source_root)
        try:
            health_config = HealthModelConfig.from_file(config.health_model_config_path)
        except Exception as exc:
            raise ProductionPortConfigurationError(
                "sidecar-health-model-config-unavailable"
            ) from exc
        model = PinnedHealthDispatchModel(
            health_config,
            api_key=_read_private_text(
                config.health_model_api_key_path,
                "sidecar-health-model-api-key-unavailable",
            ),
        )
        source_fetch = ApprovedSourceFetch.from_file(config.source_metadata_path)
        try:
            transport = HermesWeixinTransport.from_hermes_source(
                config.hermes_source_root,
                token=_read_private_text(
                    config.weixin_token_path,
                    "sidecar-weixin-token-unavailable",
                ),
                base_url=config.weixin_base_url,
                cdn_base_url=config.weixin_cdn_base_url,
            )
            channel = WeixinHealthChannel(
                config.delivery_ledger_path,
                transport,
                accepted_hermes_version=config.accepted_hermes_version,
                clock=self.clock,
                audit_sink=audit_sink,
                profile_subject=config.subject,
            )
        except ProductionPortConfigurationError:
            raise
        except Exception as exc:
            raise ProductionPortConfigurationError(
                "sidecar-weixin-delivery-unavailable"
            ) from exc
        return HealthStewardPorts(
            clock=self.clock,
            key_manager=self.key_manager,
            llm=model,
            source_fetch=source_fetch,
            channel_send=channel,
            memory_projection=FileMemoryProjection(config.memory_projection_path),
        )


__all__ = [
    "ApprovedSourceFetch",
    "PinnedHealthDispatchModel",
    "ProductionPortConfigurationError",
    "ProductionPortsFactory",
]

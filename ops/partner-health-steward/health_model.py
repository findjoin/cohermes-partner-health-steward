"""One pinned, no-history, no-tools Hermes health-model call boundary."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


class PinnedHealthModelError(RuntimeError):
    """Raised before or during one fail-closed pinned health-model call."""


def _required(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PinnedHealthModelError(code)
    return value.strip()


def _normalized_endpoint(value: Any) -> str:
    parsed = urlparse(str(value or "").strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise PinnedHealthModelError("health-model-endpoint-unattested")
    host = parsed.hostname.lower()
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return f"https://{host}{parsed.path.rstrip('/')}"


@dataclass(frozen=True)
class HealthModelConfig:
    """Explicit recipient snapshot independent from ordinary chat settings."""

    provider: str
    endpoint: str
    model_id: str
    privacy_mode: str
    auth_profile: str

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "endpoint",
            "model_id",
            "privacy_mode",
            "auth_profile",
        ):
            object.__setattr__(
                self,
                name,
                _required(getattr(self, name), f"health-model-{name}-required"),
            )
        object.__setattr__(
            self, "endpoint", _normalized_endpoint(self.endpoint)
        )

    @classmethod
    def snapshot_from_file(
        cls, path: str | Path
    ) -> tuple["HealthModelConfig", str]:
        try:
            raw = Path(path).read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PinnedHealthModelError("health-model-config-unavailable") from exc
        allowed = {
            "provider",
            "endpoint",
            "model_id",
            "privacy_mode",
            "auth_profile",
        }
        if not isinstance(payload, Mapping) or set(payload) != allowed:
            raise PinnedHealthModelError("health-model-config-invalid")
        return cls(**dict(payload)), hashlib.sha256(raw).hexdigest()

    @classmethod
    def from_file(cls, path: str | Path) -> "HealthModelConfig":
        return cls.snapshot_from_file(path)[0]


@dataclass(frozen=True)
class PinnedHealthModelResult:
    parsed: Mapping[str, Any]
    provider: str
    endpoint: str
    model_id: str


class PinnedHealthModelClient:
    """Call the accepted endpoint exactly once without Hermes fallback."""

    def __init__(
        self,
        plugin_llm: Any,
        config: HealthModelConfig,
        *,
        api_key: str | None = None,
    ) -> None:
        if not isinstance(config, HealthModelConfig):
            raise PinnedHealthModelError("health-model-config-invalid")
        if api_key is not None and (
            not isinstance(api_key, str) or not api_key.strip()
        ):
            raise PinnedHealthModelError("health-model-api-key-invalid")
        self.plugin_llm = plugin_llm
        self.config = config
        # The sidecar supplies a dedicated credential from its own restricted
        # account.  The partner-plugin path intentionally leaves this unset so
        # Hermes continues to resolve only the configured partner profile.
        self.api_key = api_key.strip() if isinstance(api_key, str) else None

    def complete_structured(
        self,
        *,
        instructions: str,
        payload: Mapping[str, Any],
        json_schema: Mapping[str, Any],
        schema_name: str,
        task: str,
        max_tokens: int = 1200,
        timeout_seconds: float = 15.0,
    ) -> PinnedHealthModelResult:
        instructions = _required(instructions, "health-model-instructions-required")
        schema_name = _required(schema_name, "health-model-schema-name-required")
        task = _required(task, "health-model-task-required")
        if not isinstance(payload, Mapping) or not isinstance(json_schema, Mapping):
            raise PinnedHealthModelError("health-model-structured-input-invalid")
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or float(timeout_seconds) <= 0
        ):
            raise PinnedHealthModelError("health-model-call-budget-invalid")

        try:
            from agent.auxiliary_client import (
                _build_call_kwargs,
                _get_cached_client,
                _validate_llm_response,
            )
            from agent.plugin_llm import (
                _build_structured_messages,
                _check_overrides,
                _extract_text,
                _parse_structured_text,
            )
        except (ImportError, AttributeError) as exc:
            raise PinnedHealthModelError(
                "pinned-health-model-runtime-unavailable"
            ) from exc

        plugin_id = str(getattr(self.plugin_llm, "_plugin_id", "") or "").strip()
        policy_loader = getattr(self.plugin_llm, "_policy_loader", None)
        response_format = getattr(self.plugin_llm, "_json_response_format", None)
        if not plugin_id or not callable(policy_loader) or not callable(response_format):
            raise PinnedHealthModelError("pinned-health-model-runtime-unavailable")

        try:
            provider, model, _agent_id, profile = _check_overrides(
                policy_loader(plugin_id),
                requested_provider=self.config.provider,
                requested_model=self.config.model_id,
                requested_agent_id=None,
                requested_profile=self.config.auth_profile,
            )
            if (
                provider != self.config.provider
                or model != self.config.model_id
                or profile != self.config.auth_profile
            ):
                raise PinnedHealthModelError("health-model-snapshot-mismatch")
            client, resolved_model = _get_cached_client(
                provider,
                model,
                base_url=self.config.endpoint,
                api_key=self.api_key,
            )
        except PinnedHealthModelError:
            raise
        except Exception as exc:
            raise PinnedHealthModelError("pinned-health-model-unavailable") from exc
        if client is None or resolved_model != self.config.model_id:
            raise PinnedHealthModelError("health-model-snapshot-mismatch")
        if _normalized_endpoint(getattr(client, "base_url", None)) != (
            _normalized_endpoint(self.config.endpoint)
        ):
            raise PinnedHealthModelError("health-model-endpoint-mismatch")

        messages = _build_structured_messages(
            instructions=instructions,
            inputs=[
                {
                    "type": "text",
                    "text": json.dumps(
                        dict(payload),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            ],
            json_mode=False,
            json_schema=dict(json_schema),
            schema_name=schema_name,
            system_prompt=None,
        )
        if (
            len(messages) != 2
            or messages[0].get("role") != "system"
            or messages[1].get("role") != "user"
        ):
            raise PinnedHealthModelError("health-model-context-isolation-failed")
        response_options = response_format(
            json_mode=False, json_schema=dict(json_schema)
        )
        if response_options is None:
            extra_body: dict[str, Any] = {}
        elif isinstance(response_options, Mapping):
            extra_body = dict(response_options)
        else:
            raise PinnedHealthModelError("health-model-response-format-invalid")
        raw_metadata = extra_body.get("metadata")
        if raw_metadata is None:
            metadata: dict[str, Any] = {}
        elif isinstance(raw_metadata, Mapping):
            metadata = dict(raw_metadata)
        else:
            raise PinnedHealthModelError("health-model-response-format-invalid")
        existing_profile = metadata.get("auth_profile")
        if existing_profile not in (None, self.config.auth_profile):
            raise PinnedHealthModelError("health-model-snapshot-mismatch")
        metadata["auth_profile"] = self.config.auth_profile
        extra_body["metadata"] = metadata
        kwargs = _build_call_kwargs(
            provider,
            resolved_model,
            messages,
            temperature=0,
            max_tokens=max_tokens,
            timeout=float(timeout_seconds),
            extra_body=extra_body,
            base_url=self.config.endpoint,
        )
        tools = kwargs.pop("tools", None)
        if tools not in (None, [], ()):
            raise PinnedHealthModelError("health-model-tools-forbidden")
        try:
            response = _validate_llm_response(
                client.chat.completions.create(**kwargs), task=task
            )
            response_model = getattr(response, "model", None)
            if response_model is None and isinstance(response, Mapping):
                response_model = response.get("model")
            if (
                not isinstance(response_model, str)
                or response_model.strip() != self.config.model_id
            ):
                raise PinnedHealthModelError(
                    "health-model-response-model-mismatch"
                )
            parsed, content_type = _parse_structured_text(
                text=_extract_text(response),
                json_mode=False,
                json_schema=dict(json_schema),
            )
        except PinnedHealthModelError:
            raise
        except Exception as exc:
            raise PinnedHealthModelError("pinned-health-model-call-failed") from exc
        if content_type != "json" or not isinstance(parsed, Mapping):
            raise PinnedHealthModelError("pinned-health-model-response-invalid")
        return PinnedHealthModelResult(
            parsed=dict(parsed),
            provider=self.config.provider,
            endpoint=_normalized_endpoint(self.config.endpoint),
            model_id=response_model.strip(),
        )


__all__ = [
    "HealthModelConfig",
    "PinnedHealthModelClient",
    "PinnedHealthModelError",
    "PinnedHealthModelResult",
]

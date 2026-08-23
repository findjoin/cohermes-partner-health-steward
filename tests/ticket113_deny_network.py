"""Instrumented deny harness for Ticket 113 synthetic strict-port tests."""

from __future__ import annotations

import socket
from types import TracebackType
from unittest.mock import patch


class BypassDenied(RuntimeError):
    """A forbidden raw model, network, search, MCP, or tool path was attempted."""


class DenyBypassHarness:
    """Observe and deny every forbidden surface exercised by the synthetic adapter."""

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._patches = [
            patch("socket.create_connection", side_effect=self._deny_socket),
            patch("urllib.request.urlopen", side_effect=self._deny_http),
        ]

    def __enter__(self) -> "DenyBypassHarness":
        for active_patch in self._patches:
            active_patch.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        for active_patch in reversed(self._patches):
            active_patch.stop()

    def _deny(self, surface: str) -> None:
        self.attempts.append(surface)
        raise BypassDenied(surface)

    def _deny_socket(self, *args: object, **kwargs: object) -> None:
        self._deny("socket")

    def _deny_http(self, *args: object, **kwargs: object) -> None:
        self._deny("http")

    def raw_ctx_llm(self) -> None:
        self._deny("raw-ctx-llm")

    def socket_connect(self) -> None:
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)

    def web_search(self) -> None:
        self._deny("web")

    def mcp_call(self) -> None:
        self._deny("mcp")

    def tool_call(self) -> None:
        self._deny("tool")

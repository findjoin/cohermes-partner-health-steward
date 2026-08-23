"""Content-free health contract probe."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

class ProbeState(str, Enum):
    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProbeReport:
    state: ProbeState
    reason_code: str
    content: None = None
    checks: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "reason_code": self.reason_code,
            "content": None,
            "checks": list(self.checks),
        }

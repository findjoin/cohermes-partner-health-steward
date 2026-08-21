"""Shared, fail-closed entry point for the two Hermes pre-run scripts."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def main_for_role(role: str) -> int:
    """Print only the controlled snapshot for a scheduler-verified Job."""
    try:
        source_root = os.environ.get("HEALTH_STEWARD_SOURCE_ROOT", "").strip()
        if not source_root:
            return 0
        if source_root not in sys.path:
            sys.path.insert(0, source_root)
        from hermes_jobs import snapshot_for_role

        print(json.dumps(snapshot_for_role(role), ensure_ascii=False, sort_keys=True))
    except Exception:
        # A missing socket, stale Job identity, or malformed response must
        # suppress the model run without leaking health text into Cron output.
        return 0
    return 0


__all__ = ["main_for_role"]

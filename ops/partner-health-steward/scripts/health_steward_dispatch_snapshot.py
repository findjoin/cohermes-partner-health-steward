"""Hermes pre-run script for the fixed five-minute dispatcher Job."""

from __future__ import annotations

from health_steward_snapshot import main_for_role


def main() -> int:
    return main_for_role("due_task_dispatch")


if __name__ == "__main__":
    raise SystemExit(main())

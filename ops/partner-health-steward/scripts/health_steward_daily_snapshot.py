"""Hermes pre-run script for the fixed 04:00 health review Job."""

from __future__ import annotations

from health_steward_snapshot import main_for_role


def main() -> int:
    return main_for_role("daily_profile_review")


if __name__ == "__main__":
    raise SystemExit(main())

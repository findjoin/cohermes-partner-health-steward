"""Thin, deny-network JSON entry point for Ticket 119 contract fixtures.

Real target-local execution is deliberately not accepted here: it belongs to
an approved GateExecutor Adapter at the target boundary.  This entry point is
only for replaying a report or exercising the contract with synthetic evidence.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from partner_health_steward import AcceptanceRunContract, HostReleaseContract


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("input must contain a JSON object")
    return value


class _FixtureGateExecutor:
    """Return caller-supplied fixture observations without any external action."""

    def __init__(self, observations: object) -> None:
        if type(observations) is not dict:
            raise ValueError("fixture observations must be a JSON object")
        self._observations = copy.deepcopy(observations)

    def execute(self, request: dict[str, object]) -> object:
        gate_id = request.get("gate_id")
        if type(gate_id) is not str or gate_id not in self._observations:
            raise ValueError("fixture observation is unavailable")
        return copy.deepcopy(self._observations[gate_id])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run or replay a deny-network Ticket 119 contract fixture."
    )
    parser.add_argument("input", type=Path, help="path to the JSON input object")
    args = parser.parse_args(argv)
    value = _load_json(args.input)
    if set(value) != {"release_sources", "run_context", "observations"}:
        raise ValueError("ticket119 input fields are invalid")
    release_sources = value["release_sources"]
    run_context = value["run_context"]
    if type(release_sources) is not dict or type(run_context) is not dict:
        raise ValueError("ticket119 input fields are invalid")
    environment_class = run_context.get("environment_class")
    if type(environment_class) is not str or not any(
        marker in environment_class.lower()
        for marker in ("synthetic", "fixture", "deny-network", "test")
    ):
        raise ValueError("real target-local execution requires an approved adapter")
    manifest = HostReleaseContract().build(release_sources)
    report = AcceptanceRunContract().run(
        manifest,
        _FixtureGateExecutor(value["observations"]),
        run_context,
    )
    print(json.dumps(report.to_wire(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ticket119 acceptance input rejected: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

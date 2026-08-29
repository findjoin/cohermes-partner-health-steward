"""Thin JSON entry point for the Ticket 118 release/readiness seam."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from partner_health_steward import HostReleaseContract


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("input must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a Ticket 118 release or assess readiness."
    )
    parser.add_argument("mode", choices=("build", "assess"))
    parser.add_argument("input", type=Path, help="path to the JSON input object")
    args = parser.parse_args(argv)
    contract = HostReleaseContract()
    value = _load_json(args.input)
    if args.mode == "build":
        result = contract.build(value).to_wire()
    else:
        result = contract.assess(value).to_wire()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ticket118 release input rejected: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

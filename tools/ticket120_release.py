"""Narrow operator entry points for Ticket 120's staged release seam."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from partner_health_steward import DefaultOnlyGateExecutor, HermesReleasePublisher


def _build(args: argparse.Namespace) -> int:
    release = HermesReleasePublisher(Path.cwd()).build(args.output)
    print(json.dumps(release.to_wire(), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


def _execute(args: argparse.Namespace) -> int:
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    observation = DefaultOnlyGateExecutor().execute(request)
    print(json.dumps(observation.to_wire(), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0 if observation.to_wire()["verdict"] == "staged" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Ticket 120 staged release operator")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build one content-addressed staged release")
    build.add_argument("--output", required=True, type=Path)
    build.set_defaults(handler=_build)
    execute = commands.add_parser("execute", help="execute one default-only permit-bound request")
    execute.add_argument("--request", required=True, type=Path)
    execute.set_defaults(handler=_execute)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

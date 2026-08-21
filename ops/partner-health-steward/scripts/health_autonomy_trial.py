#!/usr/bin/env python3
"""Local, no-network trial harness for health-autonomy v0.2."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import importlib.util
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "plugin" / "health-autonomy" / "autonomy.py"
TRIAL_DIR = Path(tempfile.gettempdir()) / "hermes-health-autonomy-trial-v02"
TRIAL_DB = TRIAL_DIR / "health-autonomy-v02.sqlite3"
TRIAL_CLOCK = TRIAL_DIR / "clock.json"
TRIAL_JOB_ID = "trial-dispatcher-no-network"
SHANGHAI_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")
TRIAL_ROUTING = {
    "platform": "telegram",
    "user_id": "trial-user",
    "chat_id": "trial-private-chat",
    "thread_id": "",
    "chat_type": "dm",
}


def _load_core():
    spec = importlib.util.spec_from_file_location("health_autonomy_trial_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load health-autonomy core")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _initial_clock() -> dt.datetime:
    local_today = dt.datetime.now(SHANGHAI_TZ)
    return local_today.replace(hour=9, minute=0, second=0, microsecond=0).astimezone(
        dt.timezone.utc
    )


def _read_clock() -> dt.datetime:
    data = json.loads(TRIAL_CLOCK.read_text(encoding="utf-8"))
    value = dt.datetime.fromisoformat(str(data["now_utc"]))
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _write_clock(value: dt.datetime) -> None:
    TRIAL_DIR.mkdir(parents=True, exist_ok=True)
    TRIAL_CLOCK.write_text(
        json.dumps(
            {"now_utc": value.astimezone(dt.timezone.utc).isoformat()},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _clock_text(value: dt.datetime) -> str:
    return value.astimezone(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M")


class TrialCron:
    """A deterministic stub: it never creates a real cron or sends a message."""

    def ensure_dispatcher(self, routing):
        if routing != TRIAL_ROUTING:
            raise RuntimeError("trial route mismatch")
        return TRIAL_JOB_ID, True

    def verify_configured_dispatcher(self, job_id, subject_key, route_matches):
        del subject_key
        return job_id == TRIAL_JOB_ID and route_matches(TRIAL_ROUTING)

    def pause(self, job_id, reason):
        del job_id, reason

    def resume(self, job_id):
        del job_id

    def remove(self, job_id):
        del job_id


def _engine(core):
    now = _read_clock()
    store = core.HealthAutonomyStore(TRIAL_DB, now_fn=lambda: now)
    return core.HealthAutonomyEngine(store=store, cron=TrialCron()), now


def _start(core) -> None:
    if TRIAL_DB.exists():
        engine, now = _engine(core)
        print(
            json.dumps(
                {
                    "trial": "already_started",
                    "clock": _clock_text(now),
                    "status": engine.control("status", TRIAL_ROUTING),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    _write_clock(_initial_clock())
    engine, now = _engine(core)
    receipt = engine.activate(
        core.activation_example(),
        source_message_id="trial-visible-authorization",
        routing=TRIAL_ROUTING,
    )
    print(
        json.dumps(
            {
                "trial": "started",
                "clock": _clock_text(now),
                "receipt": receipt,
                "network": "disabled",
                "real_cron": "not_created",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _say(core, text: str) -> None:
    engine, now = _engine(core)
    result, context = engine.observe(
        text,
        source_message_id=f"trial-message-{uuid.uuid4().hex}",
        routing=TRIAL_ROUTING,
    )
    print(
        json.dumps(
            {
                "clock": _clock_text(now),
                "input": text,
                "decision": result,
                "minimal_model_context": context,
                "status": engine.control("status", TRIAL_ROUTING),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _advance(core, minutes: int) -> None:
    if minutes <= 0 or minutes > 7 * 24 * 60:
        raise ValueError("advance minutes must be between 1 and 10080")
    new_now = _read_clock() + dt.timedelta(minutes=minutes)
    _write_clock(new_now)
    engine, now = _engine(core)
    output = engine.store.dispatch_due()
    print(
        json.dumps(
            {
                "clock": _clock_text(now),
                "dispatch": output or "[SILENT]",
                "status": engine.control("status", TRIAL_ROUTING),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _status(core) -> None:
    engine, now = _engine(core)
    print(
        json.dumps(
            {
                "clock": _clock_text(now),
                "status": engine.control("status", TRIAL_ROUTING),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _destroy() -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    resolved = TRIAL_DIR.resolve()
    if resolved.parent != temp_root or resolved.name != "hermes-health-autonomy-trial-v02":
        raise RuntimeError("refusing to remove unexpected trial directory")
    if TRIAL_DIR.exists():
        shutil.rmtree(TRIAL_DIR)
    print(json.dumps({"trial": "destroyed"}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start")
    say = subparsers.add_parser("say")
    say_group = say.add_mutually_exclusive_group(required=True)
    say_group.add_argument("--text")
    say_group.add_argument("--text-b64")
    advance = subparsers.add_parser("advance")
    advance.add_argument("minutes", type=int)
    subparsers.add_parser("status")
    subparsers.add_parser("destroy")
    args = parser.parse_args()

    if args.command == "destroy":
        _destroy()
        return 0
    core = _load_core()
    if args.command == "start":
        _start(core)
        return 0
    if not TRIAL_DB.exists() or not TRIAL_CLOCK.exists():
        raise RuntimeError("trial is not started; run the start command first")
    if args.command == "say":
        text = args.text
        if args.text_b64:
            text = base64.b64decode(args.text_b64).decode("utf-8")
        _say(core, str(text))
        return 0
    if args.command == "advance":
        _advance(core, args.minutes)
        return 0
    if args.command == "status":
        _status(core)
        return 0
    raise RuntimeError("unknown trial command")


if __name__ == "__main__":
    raise SystemExit(main())

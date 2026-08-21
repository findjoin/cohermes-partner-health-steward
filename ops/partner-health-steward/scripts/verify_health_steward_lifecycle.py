"""Offline verification for encrypted backup, key destruction and day-30 purge."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar.store import HealthSidecarStore, StoreError  # noqa: E402


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class Projection:
    def remove_health_projection(self, _subject: str) -> bool:
        return True


def main() -> int:
    subject = "lifecycle-verification"
    owner = "verification-owner"
    clock = FixedClock(dt.datetime(2026, 1, 2, 0, 5, tzinfo=dt.timezone.utc))
    with tempfile.TemporaryDirectory(prefix="health-lifecycle-") as temp:
        root = Path(temp)
        store = HealthSidecarStore(root / "state.sqlite.enc", root / "sidecar.key", clock=clock)
        owner_token = store.message_verifier.sign_owner_binding(
            subject=subject, owner_sender_id=owner
        )
        store.bind_profile_owner(subject, owner, owner_token)
        store.stage_profile_message(
            subject,
            owner,
            "verification-message",
            "2026-01-02T00:04:00Z",
            "verification-state",
            "direct_statement",
            store.message_verifier.sign(
                subject=subject,
                sender_id=owner,
                message_id="verification-message",
                message_utc="2026-01-02T00:04:00Z",
                message_text="verification-state",
                evidence_kind="direct_statement",
            ),
        )
        store.record_profile_candidate(
            subject,
            owner,
            {
                "evidence_kind": "direct_statement",
                "source_message_id": "verification-message",
                "source_utc": "2026-01-02T00:04:00Z",
                "excerpt": "verification-state",
                "conclusions": [
                    {
                        "category": "state",
                        "dedupe_key": "verification",
                        "text": "verification-state",
                        "status": "fact",
                        "priority": 1,
                    }
                ],
            },
        )
        backup = sorted(store.backup_dir.glob("*.bak"))[-1]
        backup_copy = root / "restore-check.sqlite.enc"
        shutil.copy2(backup, backup_copy)
        request_message_id = "delete-verification-request"
        confirmation_message_id = "delete-verification-confirm"
        request_utc = "2026-01-02T00:04:30Z"
        confirmation_utc = "2026-01-02T00:04:31Z"
        request_receipt = store.message_verifier.sign_access_receipt(
            action="health.profile.delete.request",
            subject=subject,
            actor_sender_id=owner,
            target_sender_id=owner,
            message_id=request_message_id,
            message_utc=request_utc,
        )
        confirmation_receipt = store.message_verifier.sign_access_receipt(
            action="health.profile.delete.confirm",
            subject=subject,
            actor_sender_id=owner,
            target_sender_id=owner,
            message_id=confirmation_message_id,
            message_utc=confirmation_utc,
        )
        store.request_profile_deletion(
            subject,
            owner,
            request_message_id,
            request_utc,
            request_receipt,
        )
        deleted = store.confirm_profile_deletion(
            subject,
            owner,
            request_message_id,
            confirmation_message_id,
            confirmation_utc,
            confirmation_receipt,
            memory_projection=Projection(),
        )
        restored = HealthSidecarStore(backup_copy, root / "sidecar.key", clock=clock)
        undecryptable = False
        try:
            restored.read_subject_status(subject, _allow_profile_state=True)
        except StoreError as exc:
            undecryptable = "profile-key-destroyed" in str(exc)
        if not deleted.get("key_destroyed") or not undecryptable:
            raise RuntimeError("lifecycle-key-destruction-verification-failed")
        clock.now = dt.datetime(2026, 1, 31, 0, 5, tzinfo=dt.timezone.utc)
        before_day_30 = store.purge_expired_backups()
        clock.now = dt.datetime(2026, 2, 1, 0, 5, tzinfo=dt.timezone.utc)
        on_day_30 = store.purge_expired_backups()
        if before_day_30["deleted"] != 0 or on_day_30["deleted"] < 1:
            raise RuntimeError("lifecycle-day-30-purge-verification-failed")
    print(
        json.dumps(
            {
                "result": "passed",
                "encrypted_backup": True,
                "profile_key_destroyed": True,
                "backup_undecryptable": True,
                "day_30_purge": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

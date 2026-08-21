"""Ephemeral, private JSON attachments for owner health-record exports.

This module deliberately has no logging or delivery ledger.  It only writes a
short-lived plaintext file into a dedicated, verified tmpfs directory.  The
caller owns the attachment lifecycle and must remove it as soon as the channel
has confirmed the send.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


_ATTACHMENT_PREFIX = "health-export-"
_ATTACHMENT_SUFFIX = ".json"
# The enabled timer runs hourly.  Sweep two hours early so scheduling latency
# cannot carry a crash leftover beyond the 24-hour privacy boundary.
_MAX_ORPHAN_AGE = dt.timedelta(hours=22)
_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")


class ExportAttachmentError(RuntimeError):
    """Raised when private export plaintext cannot be handled safely."""


def _decode_mount_path(value: str) -> str:
    return _MOUNT_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _linux_mount_filesystem_type(path: Path) -> str | None:
    """Return the backing filesystem type for an absolute Linux path.

    ``/proc/self/mountinfo`` is the kernel-provided mount namespace view.  The
    longest matching mount point handles nested mounts such as a systemd
    ``RuntimeDirectory`` below ``/run``.
    """

    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ExportAttachmentError("export-tmpfs-mountinfo-unavailable") from exc

    target = str(path)
    matches: list[tuple[int, str]] = []
    for line in lines:
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        fields = left.split()
        optional_fields = right.split()
        if len(fields) < 5 or not optional_fields:
            continue
        mount_point = _decode_mount_path(fields[4])
        if mount_point == "/":
            covers_path = target.startswith("/")
        else:
            covers_path = target == mount_point or target.startswith(
                mount_point.rstrip("/") + "/"
            )
        if covers_path:
            matches.append((len(mount_point), optional_fields[0]))
    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


def verify_private_linux_tmpfs(directory: Path) -> None:
    """Fail closed unless ``directory`` is a private directory on Linux tmpfs."""

    if not sys.platform.startswith("linux"):
        raise ExportAttachmentError("export-tmpfs-linux-required")
    metadata = directory.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ExportAttachmentError("export-private-directory-required")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ExportAttachmentError("export-private-directory-required")
    if metadata.st_uid != os.geteuid():
        raise ExportAttachmentError("export-private-directory-owner-required")
    if _linux_mount_filesystem_type(directory) != "tmpfs":
        raise ExportAttachmentError("export-private-tmpfs-required")


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass(frozen=True)
class PreparedJsonExport:
    """A plaintext JSON attachment whose path is safe to hand to Weixin once."""

    path: Path

    def remove(self) -> bool:
        """Immediately remove the plaintext attachment; repeated removal is safe."""

        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        return True

    def __enter__(self) -> "PreparedJsonExport":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.remove()


class PrivateJsonExportStore:
    """Create and sweep short-lived JSON exports in a strict private tmpfs.

    Production uses :func:`verify_private_linux_tmpfs`.  Tests may inject a
    verifier because Windows has no Linux uid/mode/tmpfs equivalence; injected
    verifiers are intentionally explicit at construction rather than an
    environment switch that could weaken a deployed service.
    """

    def __init__(
        self,
        directory: str | os.PathLike[str],
        *,
        tmpfs_verifier: Callable[[Path], None] | None = None,
        clock: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        candidate = Path(directory)
        if not candidate.is_absolute():
            raise ExportAttachmentError("export-directory-absolute-required")
        self.directory = candidate
        self._tmpfs_verifier = tmpfs_verifier or verify_private_linux_tmpfs
        self._clock = clock
        self._validate_directory()
        # A process restart after a fatal handoff is the only normal route
        # that can bypass the caller's finally block. Sweep bounded leftovers
        # before this instance accepts any new export.
        self.cleanup_orphans()

    def _validate_directory(self) -> Path:
        try:
            metadata = self.directory.lstat()
        except FileNotFoundError as exc:
            raise ExportAttachmentError("export-directory-missing") from exc
        except OSError as exc:
            raise ExportAttachmentError("export-directory-unreadable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ExportAttachmentError("export-private-directory-required")
        self._tmpfs_verifier(self.directory)
        return self.directory

    def _now_utc(self) -> dt.datetime:
        value = self._clock()
        if not isinstance(value, dt.datetime) or value.tzinfo is None:
            raise ExportAttachmentError("export-clock-utc-required")
        offset = value.utcoffset()
        if offset is None:
            raise ExportAttachmentError("export-clock-utc-required")
        return value.astimezone(dt.timezone.utc)

    @staticmethod
    def _encode_json(payload: Mapping[str, Any]) -> bytes:
        if not isinstance(payload, Mapping):
            raise ExportAttachmentError("export-json-object-required")
        try:
            serialized = json.dumps(
                dict(payload),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise ExportAttachmentError("export-json-invalid") from exc
        return serialized.encode("utf-8")

    def _new_path(self) -> Path:
        return self.directory / (
            f"{_ATTACHMENT_PREFIX}{secrets.token_hex(16)}{_ATTACHMENT_SUFFIX}"
        )

    def write_json(self, payload: Mapping[str, Any]) -> PreparedJsonExport:
        """Write one UTF-8 JSON attachment with exact owner-only POSIX mode."""

        encoded = self._encode_json(payload)
        self.cleanup_orphans()
        directory = self._validate_directory()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        for _attempt in range(10):
            path = self._new_path()
            descriptor: int | None = None
            try:
                descriptor = os.open(path, flags, 0o600)
            except FileExistsError:
                continue
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(descriptor, 0o600)
                stream = os.fdopen(descriptor, "wb")
                descriptor = None
                with stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                if os.name == "posix":
                    metadata = path.lstat()
                    if (
                        stat.S_ISLNK(metadata.st_mode)
                        or not stat.S_ISREG(metadata.st_mode)
                        or stat.S_IMODE(metadata.st_mode) != 0o600
                    ):
                        raise ExportAttachmentError("export-private-file-required")
                return PreparedJsonExport(path)
            except BaseException:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                raise
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        raise ExportAttachmentError("export-attachment-name-collision")

    def cleanup_orphans(self) -> int:
        """Remove component plaintext early enough to meet the 24-hour limit."""

        directory = self._validate_directory()
        cutoff = self._now_utc() - _MAX_ORPHAN_AGE
        removed = 0
        try:
            candidates = tuple(directory.iterdir())
        except OSError as exc:
            raise ExportAttachmentError("export-directory-unreadable") from exc
        for candidate in candidates:
            if not (
                candidate.name.startswith(_ATTACHMENT_PREFIX)
                and candidate.name.endswith(_ATTACHMENT_SUFFIX)
            ):
                continue
            try:
                metadata = candidate.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(metadata.st_mode):
                continue
            modified = dt.datetime.fromtimestamp(
                metadata.st_mtime, tz=dt.timezone.utc
            )
            if modified > cutoff:
                continue
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue
            removed += 1
        return removed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="sweep expired private health-record JSON exports"
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="remove only component-owned exports before the 24-hour privacy limit",
    )
    parser.add_argument("--directory", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the timer-owned sweep without printing export metadata or content."""
    args = _parser().parse_args(argv)
    if not args.cleanup:
        raise ExportAttachmentError("export-cleanup-action-required")
    store = PrivateJsonExportStore(args.directory)
    store.cleanup_orphans()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by systemd.
    raise SystemExit(main())

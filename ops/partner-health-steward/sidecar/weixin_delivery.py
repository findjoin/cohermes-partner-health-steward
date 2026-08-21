"""Version-pinned, content-free idempotency for partner Weixin delivery."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import importlib
import os
import secrets
import sqlite3
import sys
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .store import Clock, SystemClock


_DELIVERY_ERROR_CODES = {
    "audit-write-failed",
    "interrupted-before-confirmation",
    "invalid-transport-error-code",
    "invalid-transport-result",
    "network-confirmation-missing",
    "post-handoff-state-failure",
    "provider-confirmation-missing",
    "provider-rejected",
    "recipient-unavailable",
    "transport-exception",
    "upload-url-unavailable",
}


def _safe_error_code(value: Any, default: str) -> str:
    candidate = str(value or default).strip()
    if candidate in _DELIVERY_ERROR_CODES:
        return candidate
    return "invalid-transport-error-code"


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome returned by the narrow Weixin network transport."""

    status: str
    provider_message_id: str | None = None
    error_code: str | None = None

    @classmethod
    def accepted(cls, provider_message_id: str) -> "DeliveryResult":
        return cls("accepted", provider_message_id=str(provider_message_id))

    @classmethod
    def uncertain(cls, error_code: str) -> "DeliveryResult":
        return cls("uncertain", error_code=str(error_code))

    @classmethod
    def rejected(cls, error_code: str) -> "DeliveryResult":
        return cls("rejected", error_code=str(error_code))


class ChannelSendUncertainError(RuntimeError):
    """Raised when another automatic handoff with this ID is unsafe."""


class ProfileDeliveryBlockedError(RuntimeError):
    """Raised when a profile deletion has made a new delivery unsafe."""


class WeixinVersionMismatchError(RuntimeError):
    """Raised before state or network access when Hermes was not accepted."""


class WeixinDeliveryTransport(Protocol):
    """Network boundary that receives the stable provider client ID."""

    runtime_version: str

    def send_text(
        self, recipient: str, message: str, client_id: str
    ) -> DeliveryResult:
        ...

    def send_json_attachment(
        self, recipient: str, attachment_path: Path, client_id: str
    ) -> DeliveryResult:
        ...


class DeliveryAuditSink(Protocol):
    """Content-free operational audit boundary."""

    def append_audit_event_once(
        self,
        event_id: str,
        event: str,
        details: Mapping[str, Any],
    ) -> bool | None:
        ...


class HermesWeixinTransport:
    """Call the pinned Hermes iLink surface with a caller-supplied client ID."""

    def __init__(
        self,
        weixin_module: Any,
        *,
        runtime_version: str,
        token: str,
        base_url: str,
        session_factory: Callable[[], Any],
        cdn_base_url: str | None = None,
    ) -> None:
        self.weixin = weixin_module
        self.runtime_version = str(runtime_version).strip()
        self.token = str(token).strip()
        self.base_url = str(base_url).strip().rstrip("/")
        self.cdn_base_url = str(
            cdn_base_url or getattr(weixin_module, "WEIXIN_CDN_BASE_URL", "")
        ).strip().rstrip("/")
        self.session_factory = session_factory
        if not self.runtime_version:
            raise ValueError("hermes-runtime-version-required")
        if not self.token:
            raise ValueError("weixin-token-required")
        if not self.base_url.startswith("https://"):
            raise ValueError("weixin-https-base-url-required")
        if not self.cdn_base_url.startswith("https://"):
            raise ValueError("weixin-https-cdn-url-required")

    @classmethod
    def from_hermes_source(
        cls,
        source_root: str | os.PathLike[str],
        *,
        token: str,
        module_loader: Callable[[Path], tuple[str, Any]] | None = None,
        session_factory: Callable[[], Any] | None = None,
        base_url: str | None = None,
        cdn_base_url: str | None = None,
    ) -> "HermesWeixinTransport":
        root = Path(source_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("hermes-source-root-unavailable")
        loader = module_loader or cls._load_hermes_module
        runtime_version, weixin_module = loader(root)
        if session_factory is None:
            session_factory = lambda: weixin_module.aiohttp.ClientSession(
                trust_env=True,
                connector=weixin_module._make_ssl_connector(),
            )
        return cls(
            weixin_module,
            runtime_version=runtime_version,
            token=token,
            base_url=base_url or weixin_module.ILINK_BASE_URL,
            cdn_base_url=cdn_base_url,
            session_factory=session_factory,
        )

    @staticmethod
    def _load_hermes_module(source_root: Path) -> tuple[str, Any]:
        source_text = str(source_root)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        hermes_cli = importlib.import_module("hermes_cli")
        weixin_module = importlib.import_module("gateway.platforms.weixin")
        for module in (hermes_cli, weixin_module):
            module_file = Path(str(getattr(module, "__file__", ""))).resolve()
            try:
                module_file.relative_to(source_root)
            except ValueError as exc:
                raise RuntimeError("hermes-module-outside-pinned-source") from exc
        return str(hermes_cli.__version__), weixin_module

    @staticmethod
    def _result(response: Any, client_id: str) -> DeliveryResult:
        if not isinstance(response, Mapping):
            return DeliveryResult.uncertain("provider-confirmation-missing")
        ret = response.get("ret")
        errcode = response.get("errcode")
        if (ret == 0 or errcode == 0) and ret in {None, 0} and errcode in {None, 0}:
            return DeliveryResult.accepted(client_id)
        if ret is not None or errcode is not None:
            return DeliveryResult.rejected("provider-rejected")
        return DeliveryResult.uncertain("provider-confirmation-missing")

    @staticmethod
    def _run(awaitable: Any) -> DeliveryResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        raise RuntimeError("weixin-sync-transport-inside-event-loop")

    async def _send_text(
        self, recipient: str, message: str, client_id: str
    ) -> DeliveryResult:
        async with self.session_factory() as session:
            response = await self.weixin._send_message(
                session,
                base_url=self.base_url,
                token=self.token,
                to=recipient,
                text=message,
                context_token=None,
                client_id=client_id,
            )
        return self._result(response, client_id)

    def send_text(
        self, recipient: str, message: str, client_id: str
    ) -> DeliveryResult:
        return self._run(self._send_text(recipient, message, client_id))

    def send_json_attachment(
        self, recipient: str, attachment_path: Path, client_id: str
    ) -> DeliveryResult:
        attachment = Path(attachment_path)
        if attachment.suffix.lower() != ".json" or not attachment.is_file():
            raise ValueError("json-attachment-required")
        return self._run(
            self._send_json_attachment(recipient, attachment, client_id)
        )

    async def _send_json_attachment(
        self, recipient: str, attachment: Path, client_id: str
    ) -> DeliveryResult:
        plaintext = attachment.read_bytes()
        file_key = secrets.token_hex(16)
        aes_key = secrets.token_bytes(16)
        raw_size = len(plaintext)
        raw_md5 = hashlib.md5(plaintext).hexdigest()
        async with self.session_factory() as session:
            upload_response = await self.weixin._get_upload_url(
                session,
                base_url=self.base_url,
                token=self.token,
                to_user_id=recipient,
                media_type=self.weixin.MEDIA_FILE,
                filekey=file_key,
                rawsize=raw_size,
                rawfilemd5=raw_md5,
                filesize=self.weixin._aes_padded_size(raw_size),
                aeskey_hex=aes_key.hex(),
            )
            if not isinstance(upload_response, Mapping):
                return DeliveryResult.rejected("upload-url-unavailable")
            upload_url = str(upload_response.get("upload_full_url") or "").strip()
            if not upload_url:
                upload_param = str(upload_response.get("upload_param") or "").strip()
                if upload_param:
                    upload_url = self.weixin._cdn_upload_url(
                        self.cdn_base_url, upload_param, file_key
                    )
            if not upload_url.startswith("https://"):
                return DeliveryResult.rejected("upload-url-unavailable")
            ciphertext = self.weixin._aes128_ecb_encrypt(plaintext, aes_key)
            encrypted_query = await self.weixin._upload_ciphertext(
                session,
                ciphertext=ciphertext,
                upload_url=upload_url,
            )
            aes_key_for_api = base64.b64encode(
                aes_key.hex().encode("ascii")
            ).decode("ascii")
            media_item = {
                "type": self.weixin.ITEM_FILE,
                "file_item": {
                    "media": {
                        "encrypt_query_param": encrypted_query,
                        "aes_key": aes_key_for_api,
                        "encrypt_type": 1,
                    },
                    "file_name": attachment.name,
                    "len": str(raw_size),
                },
            }
            response = await self.weixin._api_post(
                session,
                base_url=self.base_url,
                endpoint=self.weixin.EP_SEND_MESSAGE,
                payload={
                    "msg": {
                        "from_user_id": "",
                        "to_user_id": recipient,
                        "client_id": client_id,
                        "message_type": self.weixin.MSG_TYPE_BOT,
                        "message_state": self.weixin.MSG_STATE_FINISH,
                        "item_list": [media_item],
                    }
                },
                token=self.token,
                timeout_ms=self.weixin.API_TIMEOUT_MS,
            )
        return self._result(response, client_id)


def _now(clock: Clock) -> str:
    current = clock.now_utc()
    if not isinstance(current, dt.datetime) or current.tzinfo is None:
        raise ValueError("clock-must-return-aware-utc")
    return current.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def _client_id(delivery_key: str) -> str:
    digest = hashlib.sha256(delivery_key.encode("utf-8")).hexdigest()[:32]
    return f"hermes-health-{digest}"


def _profile_scope_id(profile_subject: str | None) -> str | None:
    """Return an opaque ledger scope without retaining the profile subject."""
    subject = str(profile_subject or "").strip()
    if not subject:
        return None
    return hashlib.sha256(
        f"health-profile-delivery-scope:v1:{subject}".encode("utf-8")
    ).hexdigest()


class WeixinHealthChannel:
    """Persist a handoff before calling Weixin and reuse its final outcome."""

    def __init__(
        self,
        ledger_path: str | os.PathLike[str],
        transport: WeixinDeliveryTransport,
        *,
        accepted_hermes_version: str,
        clock: Clock | None = None,
        audit_sink: DeliveryAuditSink,
        profile_subject: str | None = None,
    ) -> None:
        accepted = str(accepted_hermes_version).strip()
        runtime = str(getattr(transport, "runtime_version", "")).strip()
        if not accepted or not runtime or accepted != runtime:
            raise WeixinVersionMismatchError("hermes-weixin-version-mismatch")
        self.ledger_path = Path(ledger_path)
        self.transport = transport
        self.clock = clock or SystemClock()
        self.audit_sink = audit_sink
        self._profile_subject = str(profile_subject or "").strip() or None
        self._profile_scope_id = _profile_scope_id(self._profile_subject)
        self._lock = threading.RLock()
        self._initialize()
        self._recover_interrupted_handoffs()
        self._recover_pending_audits()
        self._recover_interrupted_batches()
        self._recover_interrupted_deletion_notices()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.ledger_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.ledger_path.parent.chmod(0o700)
        except OSError:
            pass
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    recipient_id TEXT NOT NULL,
                    scope_id TEXT NOT NULL DEFAULT '',
                    created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider_message_id TEXT,
                    error_code TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_batches (
                    batch_id TEXT PRIMARY KEY,
                    recipient_id TEXT NOT NULL,
                    scope_id TEXT NOT NULL DEFAULT '',
                    part_count INTEGER NOT NULL,
                    created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            self._ensure_scope_column(connection, "deliveries")
            self._ensure_scope_column(connection, "delivery_batches")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_deletion_guards (
                    scope_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    terminal_batch_id TEXT NOT NULL,
                    terminal_status TEXT NOT NULL DEFAULT 'pending',
                    prepared_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL,
                    CHECK (status IN ('prepared', 'deleted')),
                    CHECK (terminal_status IN (
                        'pending', 'sending', 'sent', 'rejected', 'uncertain'
                    ))
                )
                """
            )
            self._ensure_deletion_guard_terminal_status(connection)
        try:
            self.ledger_path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _ensure_scope_column(connection: sqlite3.Connection, table: str) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if "scope_id" not in columns:
            connection.execute(
                f"ALTER TABLE {table} "
                "ADD COLUMN scope_id TEXT NOT NULL DEFAULT ''"
            )

    @staticmethod
    def _ensure_deletion_guard_terminal_status(
        connection: sqlite3.Connection,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(profile_deletion_guards)")
        }
        if "terminal_status" not in columns:
            connection.execute(
                "ALTER TABLE profile_deletion_guards "
                "ADD COLUMN terminal_status TEXT NOT NULL DEFAULT 'pending'"
            )

    def _scope_id(self) -> str:
        if self._profile_scope_id is None:
            raise ValueError("profile-subject-required")
        return self._profile_scope_id

    def _delivery_id(self, delivery_key: str) -> str:
        scope = self._profile_scope_id
        if scope is None:
            return _client_id(delivery_key)
        return _client_id(f"scope:{scope}:delivery:{delivery_key}")

    def _batch_id(self, delivery_key: str) -> str:
        scope = self._profile_scope_id
        batch_key = f"batch:{delivery_key}"
        if scope is None:
            return _client_id(batch_key)
        return _client_id(f"scope:{scope}:{batch_key}")

    def _read_deletion_guard(
        self,
        connection: sqlite3.Connection,
        scope_id: str | None = None,
    ) -> sqlite3.Row | None:
        scope = scope_id if scope_id is not None else self._scope_id()
        return connection.execute(
            "SELECT * FROM profile_deletion_guards WHERE scope_id = ?",
            (scope,),
        ).fetchone()

    def _assert_delivery_permitted(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        if self._profile_scope_id is None:
            return
        guard = self._read_deletion_guard(connection, self._profile_scope_id)
        if guard is None:
            return
        raise ProfileDeliveryBlockedError("profile-delivery-blocked")

    def _assert_new_delivery_permitted(self) -> None:
        with closing(self._connect()) as connection:
            self._assert_delivery_permitted(connection)

    def profile_deletion_status(self) -> str:
        """Return the durable delivery guard state for the configured profile."""
        with closing(self._connect()) as connection:
            guard = self._read_deletion_guard(connection)
        return "active" if guard is None else str(guard["status"])

    def prepare_profile_deletion(self, terminal_delivery_key: str) -> bool:
        """Block new profile deliveries while a sidecar deletion is confirmed.

        Once :meth:`complete_profile_deletion` succeeds, the exact terminal
        key registered here is usable only by
        :meth:`send_profile_deletion_notice_once`.  Ordinary delivery APIs
        remain blocked, so they cannot recreate profile delivery state.
        """
        key = str(terminal_delivery_key).strip()
        if not key:
            raise ValueError("delivery-key-required")
        scope = self._scope_id()
        terminal_batch_id = self._batch_id(key)
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                guard = self._read_deletion_guard(connection, scope)
                if guard is None:
                    now = _now(self.clock)
                    connection.execute(
                        """
                        INSERT INTO profile_deletion_guards (
                            scope_id, status, terminal_batch_id,
                            prepared_utc, updated_utc
                        ) VALUES (?, 'prepared', ?, ?, ?)
                        """,
                        (scope, terminal_batch_id, now, now),
                    )
                    connection.commit()
                    return True
                if guard["terminal_batch_id"] != terminal_batch_id:
                    raise ValueError("profile-deletion-terminal-key-mismatch")
                connection.commit()
                return False
            except Exception:
                connection.rollback()
                raise

    def cancel_profile_deletion(self) -> bool:
        """Undo a prepared guard after sidecar deletion fails before commit."""
        scope = self._scope_id()
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                guard = self._read_deletion_guard(connection, scope)
                if guard is None:
                    connection.commit()
                    return False
                if guard["status"] == "deleted":
                    raise ProfileDeliveryBlockedError(
                        "profile-deletion-already-completed"
                    )
                deleted = connection.execute(
                    "DELETE FROM profile_deletion_guards "
                    "WHERE scope_id = ? AND status = 'prepared'",
                    (scope,),
                ).rowcount
                connection.commit()
                return deleted == 1
            except Exception:
                connection.rollback()
                raise

    def complete_profile_deletion(self) -> bool:
        """Purge this profile's prior delivery state and keep the guard closed."""
        scope = self._scope_id()
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                guard = self._read_deletion_guard(connection, scope)
                if guard is None:
                    raise ValueError("profile-deletion-not-prepared")
                if guard["status"] == "deleted":
                    connection.commit()
                    return False
                # Rows written before profile scopes existed have an empty
                # scope.  This channel is configured for the one profile
                # that owns that legacy ledger, so deleting it must not leave
                # old delivery state behind merely because of the migration.
                connection.execute(
                    "DELETE FROM deliveries WHERE scope_id IN (?, '')",
                    (scope,),
                )
                connection.execute(
                    "DELETE FROM delivery_batches WHERE scope_id IN (?, '')",
                    (scope,),
                )
                updated = connection.execute(
                    """
                    UPDATE profile_deletion_guards
                    SET status = 'deleted', updated_utc = ?
                    WHERE scope_id = ? AND status = 'prepared'
                    """,
                    (_now(self.clock), scope),
                ).rowcount
                if updated != 1:
                    raise ChannelSendUncertainError("profile-deletion-state-raced")
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise

    def _begin_deletion_notice(
        self,
        terminal_batch_id: str | None,
        *,
        recovery: bool = False,
    ) -> tuple[str, str]:
        """Reserve the sole content-free terminal notice without a delivery row."""
        scope = self._scope_id()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                guard = self._read_deletion_guard(connection, scope)
                if guard is None or guard["status"] != "deleted":
                    raise ProfileDeliveryBlockedError("profile-deletion-notice-blocked")
                stored_terminal_batch_id = str(guard["terminal_batch_id"])
                if not recovery and stored_terminal_batch_id != terminal_batch_id:
                    raise ProfileDeliveryBlockedError("profile-deletion-notice-blocked")
                terminal_status = str(guard["terminal_status"])
                if terminal_status in {"sent", "rejected"}:
                    connection.commit()
                    return stored_terminal_batch_id, terminal_status
                if terminal_status != "pending":
                    raise ChannelSendUncertainError("channel-send-uncertain")
                updated = connection.execute(
                    """
                    UPDATE profile_deletion_guards
                    SET terminal_status = 'sending', updated_utc = ?
                    WHERE scope_id = ?
                      AND status = 'deleted'
                      AND terminal_batch_id = ?
                      AND terminal_status = 'pending'
                    """,
                    (_now(self.clock), scope, stored_terminal_batch_id),
                ).rowcount
                if updated != 1:
                    raise ChannelSendUncertainError("channel-send-uncertain")
                connection.commit()
                return stored_terminal_batch_id, "sending"
            except Exception:
                connection.rollback()
                raise

    def _finish_deletion_notice(self, terminal_batch_id: str, status: str) -> None:
        if status not in {"sent", "rejected", "uncertain"}:
            raise ValueError("terminal-notice-status-invalid")
        scope = self._scope_id()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                updated = connection.execute(
                    """
                    UPDATE profile_deletion_guards
                    SET terminal_status = ?, updated_utc = ?
                    WHERE scope_id = ?
                      AND status = 'deleted'
                      AND terminal_batch_id = ?
                      AND terminal_status = 'sending'
                    """,
                    (status, _now(self.clock), scope, terminal_batch_id),
                ).rowcount
                if updated != 1:
                    raise ChannelSendUncertainError("channel-send-uncertain")
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def send_profile_deletion_notice_once(
        self,
        recipient: str,
        messages: tuple[str, ...],
        terminal_delivery_key: str,
    ) -> bool:
        """Send the one deletion notice without retaining health-delivery state.

        The durable deletion guard keeps only a hashed batch identifier and the
        terminal outcome.  Unlike ordinary health sends, no recipient, text,
        delivery row, or delivery audit remains after the confirmed deletion.
        A process interruption becomes ``uncertain`` rather than risking a
        duplicate notification.
        """
        recipient = str(recipient).strip()
        parts = tuple(str(message) for message in messages)
        key = str(terminal_delivery_key).strip()
        if not recipient:
            raise ValueError("delivery-recipient-required")
        if not key:
            raise ValueError("delivery-key-required")
        if not parts or any(not part.strip() for part in parts):
            raise ValueError("delivery-parts-required")
        terminal_batch_id = self._batch_id(key)
        return self._send_profile_deletion_notice(
            recipient,
            parts,
            terminal_batch_id,
            recovery=False,
        )

    def recover_profile_deletion_notice_once(
        self,
        recipient: str,
        messages: tuple[str, ...],
    ) -> bool:
        """Finish an interrupted deletion acknowledgement without reopening delivery.

        This is intentionally separate from the normal terminal API: it is
        used only after the control layer has authenticated a new explicit
        owner confirmation and the sidecar has already reported the profile
        deleted.  The guard retains only the original terminal hash, so this
        method never recreates a raw delivery key, recipient ledger row, or
        audit event.
        """
        recipient = str(recipient).strip()
        parts = tuple(str(message) for message in messages)
        if not recipient:
            raise ValueError("delivery-recipient-required")
        if not parts or any(not part.strip() for part in parts):
            raise ValueError("delivery-parts-required")
        return self._send_profile_deletion_notice(
            recipient,
            parts,
            None,
            recovery=True,
        )

    def _send_profile_deletion_notice(
        self,
        recipient: str,
        parts: tuple[str, ...],
        terminal_batch_id: str | None,
        *,
        recovery: bool,
    ) -> bool:
        with self._lock:
            terminal_batch_id, reservation = self._begin_deletion_notice(
                terminal_batch_id,
                recovery=recovery,
            )
            if reservation == "sent":
                return True
            if reservation == "rejected":
                return False
            try:
                for index, message in enumerate(parts, start=1):
                    client_id = self._delivery_id(
                        f"terminal:{terminal_batch_id}:{index:04d}-of-{len(parts):04d}"
                    )
                    try:
                        outcome = self.transport.send_text(recipient, message, client_id)
                    except Exception:
                        outcome = DeliveryResult.uncertain("transport-exception")
                    if not isinstance(outcome, DeliveryResult) or outcome.status not in {
                        "accepted",
                        "rejected",
                        "uncertain",
                    }:
                        outcome = DeliveryResult.uncertain("invalid-transport-result")
                    if outcome.status == "accepted":
                        continue
                    if outcome.status == "rejected":
                        self._finish_deletion_notice(terminal_batch_id, "rejected")
                        return False
                    self._finish_deletion_notice(terminal_batch_id, "uncertain")
                    raise ChannelSendUncertainError("channel-send-uncertain")
                self._finish_deletion_notice(terminal_batch_id, "sent")
                return True
            except ChannelSendUncertainError:
                raise
            except Exception:
                # If even the terminal status cannot be committed, leaving the
                # durable ``sending`` state is safer than a second handoff.
                raise ChannelSendUncertainError("channel-send-uncertain")

    def _read(self, delivery_id: str) -> sqlite3.Row | None:
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,)
            ).fetchone()

    def _read_batch(self, batch_id: str) -> sqlite3.Row | None:
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT * FROM delivery_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()

    def _set_batch_status(self, batch_id: str, status: str) -> None:
        with closing(self._connect()) as connection, connection:
            updated = connection.execute(
                """
                UPDATE delivery_batches
                SET status = ?, updated_utc = ?
                WHERE batch_id = ?
                """,
                (status, _now(self.clock), batch_id),
            ).rowcount
        if updated != 1:
            raise ChannelSendUncertainError("delivery-batch-state-missing")

    def _recover_interrupted_handoffs(self) -> None:
        recovered: list[dict[str, str]] = []
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT delivery_id, recipient_id FROM deliveries WHERE status = 'in_flight'"
            ).fetchall()
            if not rows:
                return
            now = _now(self.clock)
            for row in rows:
                connection.execute(
                    """
                    UPDATE deliveries
                    SET status = 'uncertain_audit_pending', updated_utc = ?,
                        provider_message_id = NULL,
                        error_code = 'interrupted-before-confirmation'
                    WHERE delivery_id = ? AND status = 'in_flight'
                    """,
                    (now, row["delivery_id"]),
                )
                recovered.append(
                    {
                        **dict(row),
                        "status": "uncertain_audit_pending",
                        "error_code": "interrupted-before-confirmation",
                    }
                )
        for row in recovered:
            self._complete_pending_uncertain_audit(
                row,
                action="weixin.delivery.recover",
            )

    def _recover_interrupted_batches(self) -> None:
        with closing(self._connect()) as connection, connection:
            interrupted = connection.execute(
                "SELECT 1 FROM delivery_batches WHERE status = 'sending' LIMIT 1"
            ).fetchone()
            if interrupted is None:
                return
            connection.execute(
                """
                UPDATE delivery_batches
                SET status = 'uncertain', updated_utc = ?
                WHERE status = 'sending'
                """,
                (_now(self.clock),),
            )

    def _recover_interrupted_deletion_notices(self) -> None:
        """Never resend a terminal deletion notice after a process interruption."""
        with closing(self._connect()) as connection, connection:
            interrupted = connection.execute(
                """
                SELECT 1 FROM profile_deletion_guards
                WHERE status = 'deleted' AND terminal_status = 'sending'
                LIMIT 1
                """
            ).fetchone()
            if interrupted is None:
                return
            connection.execute(
                """
                UPDATE profile_deletion_guards
                SET terminal_status = 'uncertain', updated_utc = ?
                WHERE status = 'deleted' AND terminal_status = 'sending'
                """,
                (_now(self.clock),),
            )

    def _sent_audit_details(
        self,
        delivery_id: str,
        recipient: str,
        *,
        action: str,
    ) -> dict[str, str]:
        details = {
            "actor_role": "weixin-delivery-adapter",
            "action": action,
            "object_id": delivery_id,
            "recipient_id": recipient,
            "result": "sent",
            "reason": "provider-accepted",
        }
        if self._profile_subject is not None:
            # The encrypted SQLite ledger keeps only a one-way scope.  The
            # content-free audit needs the normal profile binding solely so
            # confirmed deletion can remove this delivery trail as well.
            details["subject"] = self._profile_subject
        return details

    def _append_audit_once(
        self,
        event: str,
        delivery_id: str,
        details: Mapping[str, Any],
    ) -> None:
        self.audit_sink.append_audit_event_once(
            f"{event}:{delivery_id}",
            event,
            details,
        )

    def _uncertain_audit_details(
        self,
        delivery_id: str,
        recipient: str,
        reason: str,
        *,
        action: str,
    ) -> dict[str, str]:
        details = {
            "actor_role": "weixin-delivery-adapter",
            "action": action,
            "object_id": delivery_id,
            "recipient_id": recipient,
            "result": "uncertain",
            "reason": reason,
        }
        if self._profile_subject is not None:
            details["subject"] = self._profile_subject
        return details

    def _rejected_audit_details(
        self,
        delivery_id: str,
        recipient: str,
        reason: str,
        *,
        action: str,
    ) -> dict[str, str]:
        details = {
            "actor_role": "weixin-delivery-adapter",
            "action": action,
            "object_id": delivery_id,
            "recipient_id": recipient,
            "result": "rejected",
            "reason": reason,
        }
        if self._profile_subject is not None:
            details["subject"] = self._profile_subject
        return details

    def _complete_pending_audit(
        self,
        existing: Mapping[str, Any],
        *,
        action: str = "weixin.delivery.recover",
    ) -> bool:
        delivery_id = str(existing["delivery_id"])
        recipient = str(existing["recipient_id"])
        try:
            self._append_audit_once(
                "weixin_delivery_sent",
                delivery_id,
                self._sent_audit_details(
                    delivery_id,
                    recipient,
                    action=action,
                ),
            )
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    UPDATE deliveries SET status = 'sent', error_code = NULL
                    WHERE delivery_id = ? AND status = 'sent_audit_pending'
                    """,
                    (delivery_id,),
                )
        except Exception:
            return False
        return True

    def _complete_pending_uncertain_audit(
        self,
        existing: Mapping[str, Any],
        *,
        action: str = "weixin.delivery.recover",
    ) -> bool:
        delivery_id = str(existing["delivery_id"])
        recipient = str(existing["recipient_id"])
        reason = _safe_error_code(
            existing["error_code"],
            "network-confirmation-missing",
        )
        try:
            self._append_audit_once(
                "weixin_delivery_uncertain",
                delivery_id,
                self._uncertain_audit_details(
                    delivery_id,
                    recipient,
                    reason,
                    action=action,
                ),
            )
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    UPDATE deliveries SET status = 'uncertain'
                    WHERE delivery_id = ?
                      AND status = 'uncertain_audit_pending'
                    """,
                    (delivery_id,),
                )
        except Exception:
            return False
        return True

    def _complete_pending_rejected_audit(
        self,
        existing: Mapping[str, Any],
        *,
        action: str = "weixin.delivery.recover",
    ) -> bool:
        delivery_id = str(existing["delivery_id"])
        recipient = str(existing["recipient_id"])
        reason = _safe_error_code(existing["error_code"], "provider-rejected")
        try:
            self._append_audit_once(
                "weixin_delivery_rejected",
                delivery_id,
                self._rejected_audit_details(
                    delivery_id,
                    recipient,
                    reason,
                    action=action,
                ),
            )
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    UPDATE deliveries SET status = 'rejected'
                    WHERE delivery_id = ?
                      AND status = 'rejected_audit_pending'
                    """,
                    (delivery_id,),
                )
        except Exception:
            return False
        return True

    def _recover_pending_audits(self) -> None:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM deliveries
                WHERE status IN (
                    'sent_audit_pending',
                    'uncertain_audit_pending',
                    'rejected_audit_pending'
                )
                """
            ).fetchall()
        for row in rows:
            if row["status"] == "sent_audit_pending":
                self._complete_pending_audit(row)
            elif row["status"] == "uncertain_audit_pending":
                self._complete_pending_uncertain_audit(row)
            else:
                self._complete_pending_rejected_audit(row)

    def delivery_status(self, delivery_key: str) -> Mapping[str, Any]:
        key = str(delivery_key).strip()
        if not key:
            raise ValueError("delivery-key-required")
        row = self._read(self._delivery_id(key))
        if row is None:
            raise KeyError("delivery-not-found")
        return dict(row)

    def delivery_batch_status(self, delivery_key: str) -> Mapping[str, Any]:
        key = str(delivery_key).strip()
        if not key:
            raise ValueError("delivery-key-required")
        row = self._read_batch(self._batch_id(key))
        if row is None:
            raise KeyError("delivery-batch-not-found")
        return dict(row)

    def _reuse_existing(self, existing: Mapping[str, Any], recipient: str) -> bool:
        if existing["recipient_id"] != recipient:
            raise ValueError("delivery-recipient-mismatch")
        if existing["status"] == "sent":
            return True
        if existing["status"] == "sent_audit_pending":
            if not self._complete_pending_audit(existing):
                raise ChannelSendUncertainError("channel-send-uncertain")
            return True
        if existing["status"] == "uncertain_audit_pending":
            self._complete_pending_uncertain_audit(existing)
            raise ChannelSendUncertainError("channel-send-uncertain")
        if existing["status"] == "rejected_audit_pending":
            if not self._complete_pending_rejected_audit(existing):
                raise ChannelSendUncertainError("channel-send-uncertain")
            return False
        if existing["status"] in {"in_flight", "uncertain"}:
            raise ChannelSendUncertainError("channel-send-uncertain")
        return False

    def _reserve_delivery(
        self,
        delivery_id: str,
        recipient: str,
    ) -> tuple[sqlite3.Row | None, str | None]:
        """Atomically enforce the profile guard before creating a handoff."""
        with closing(self._connect()) as connection:
            self._assert_delivery_permitted(connection)
            existing = connection.execute(
                "SELECT * FROM deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        if existing is not None:
            return existing, None
        # Keep clock reads out of the SQLite writer transaction: tests and a
        # production clock implementation may block, and the delivery lock
        # must not prevent another process from observing the ledger.
        created_utc = _now(self.clock)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._assert_delivery_permitted(connection)
                existing = connection.execute(
                    "SELECT * FROM deliveries WHERE delivery_id = ?",
                    (delivery_id,),
                ).fetchone()
                if existing is not None:
                    connection.commit()
                    return existing, None
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO deliveries (
                        delivery_id, recipient_id, scope_id,
                        created_utc, updated_utc,
                        status, provider_message_id, error_code
                    ) VALUES (?, ?, ?, ?, ?, 'in_flight', NULL, NULL)
                    """,
                    (
                        delivery_id,
                        recipient,
                        self._profile_scope_id or "",
                        created_utc,
                        created_utc,
                    ),
                ).rowcount
                if inserted != 1:
                    existing = connection.execute(
                        "SELECT * FROM deliveries WHERE delivery_id = ?",
                        (delivery_id,),
                    ).fetchone()
                    if existing is None:
                        raise ChannelSendUncertainError("channel-send-uncertain")
                    connection.commit()
                    return existing, None
                connection.commit()
                return None, created_utc
            except Exception:
                connection.rollback()
                raise

    def _reserve_batch(
        self,
        batch_id: str,
        recipient: str,
        part_count: int,
    ) -> sqlite3.Row | None:
        """Atomically enforce the guard before creating an aggregate batch."""
        with closing(self._connect()) as connection:
            self._assert_delivery_permitted(connection)
            existing = connection.execute(
                "SELECT * FROM delivery_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        if existing is not None:
            return existing
        # See _reserve_delivery: do not call a potentially blocking clock
        # while holding SQLite's writer transaction.
        created_utc = _now(self.clock)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._assert_delivery_permitted(connection)
                existing = connection.execute(
                    "SELECT * FROM delivery_batches WHERE batch_id = ?",
                    (batch_id,),
                ).fetchone()
                if existing is not None:
                    connection.commit()
                    return existing
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO delivery_batches (
                        batch_id, recipient_id, scope_id, part_count,
                        created_utc, updated_utc, status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'sending')
                    """,
                    (
                        batch_id,
                        recipient,
                        self._profile_scope_id or "",
                        part_count,
                        created_utc,
                        created_utc,
                    ),
                ).rowcount
                if inserted != 1:
                    existing = connection.execute(
                        "SELECT * FROM delivery_batches WHERE batch_id = ?",
                        (batch_id,),
                    ).fetchone()
                    if existing is None:
                        raise ChannelSendUncertainError("delivery-batch-raced")
                    connection.commit()
                    return existing
                connection.commit()
                return None
            except Exception:
                connection.rollback()
                raise

    def send_once(self, recipient: str, message: str, delivery_key: str) -> bool:
        recipient = str(recipient).strip()
        message = str(message)
        if not recipient:
            raise ValueError("delivery-recipient-required")
        if not message.strip():
            raise ValueError("delivery-message-required")
        return self._deliver_once(
            recipient,
            delivery_key,
            action="weixin.send_once",
            handoff=lambda client_id: self.transport.send_text(
                recipient, message, client_id
            ),
        )

    def send_text_parts_once(
        self,
        recipient: str,
        messages: tuple[str, ...],
        delivery_key: str,
    ) -> bool:
        """Deliver one immutable text batch and persist its aggregate outcome."""
        recipient = str(recipient).strip()
        parts = tuple(str(message) for message in messages)
        key = str(delivery_key).strip()
        if not recipient:
            raise ValueError("delivery-recipient-required")
        if not key:
            raise ValueError("delivery-key-required")
        if not parts or any(not part.strip() for part in parts):
            raise ValueError("delivery-parts-required")
        batch_id = self._batch_id(key)
        with self._lock:
            existing = self._reserve_batch(batch_id, recipient, len(parts))
            if existing is not None:
                if existing["recipient_id"] != recipient:
                    raise ValueError("delivery-recipient-mismatch")
                if int(existing["part_count"]) != len(parts):
                    raise ValueError("delivery-batch-part-count-mismatch")
                if existing["status"] == "sent":
                    return True
                if existing["status"] == "rejected":
                    return False
                raise ChannelSendUncertainError("channel-send-uncertain")
            try:
                for index, part in enumerate(parts, start=1):
                    accepted = self._deliver_once(
                        recipient,
                        f"{key}:part:{index:04d}-of-{len(parts):04d}",
                        action="weixin.send_text_parts_once",
                        handoff=lambda client_id, text=part: self.transport.send_text(
                            recipient, text, client_id
                        ),
                    )
                    if not accepted:
                        self._set_batch_status(batch_id, "rejected")
                        return False
            except Exception:
                self._set_batch_status(batch_id, "uncertain")
                raise
            self._set_batch_status(batch_id, "sent")
            return True

    def send(self, recipient: str, message: str) -> None:
        """Fail closed because retryable health delivery requires a stable key."""
        raise RuntimeError("non-idempotent-weixin-send-disabled")

    def send_json_attachment_once(
        self,
        recipient: str,
        attachment_path: str | os.PathLike[str],
        delivery_key: str,
    ) -> bool:
        recipient = str(recipient).strip()
        attachment = Path(attachment_path)
        if not recipient:
            raise ValueError("delivery-recipient-required")
        delivery_key = str(delivery_key).strip()
        if not delivery_key:
            raise ValueError("delivery-key-required")
        self._assert_new_delivery_permitted()
        existing = self._read(self._delivery_id(delivery_key))
        if existing is not None:
            return self._reuse_existing(existing, recipient)
        if (
            attachment.suffix.lower() != ".json"
            or not attachment.is_file()
        ):
            raise ValueError("json-attachment-required")
        return self._deliver_once(
            recipient,
            delivery_key,
            action="weixin.send_attachment_once",
            handoff=lambda client_id: self.transport.send_json_attachment(
                recipient, attachment, client_id
            ),
        )

    def _deliver_once(
        self,
        recipient: str,
        delivery_key: str,
        *,
        action: str,
        handoff: Callable[[str], DeliveryResult],
    ) -> bool:
        delivery_key = str(delivery_key).strip()
        if not delivery_key:
            raise ValueError("delivery-key-required")
        delivery_id = self._delivery_id(delivery_key)
        with self._lock:
            existing, created_utc = self._reserve_delivery(
                delivery_id,
                recipient,
            )
            if existing is not None:
                return self._reuse_existing(existing, recipient)
            if created_utc is None:
                raise ChannelSendUncertainError("channel-send-uncertain")
            now = created_utc
            try:
                outcome = handoff(delivery_id)
            except Exception:
                outcome = DeliveryResult.uncertain("transport-exception")
            if not isinstance(outcome, DeliveryResult) or outcome.status not in {
                "accepted",
                "rejected",
                "uncertain",
            }:
                outcome = DeliveryResult.uncertain("invalid-transport-result")
            if outcome.status == "uncertain":
                reason = _safe_error_code(
                    outcome.error_code, "network-confirmation-missing"
                )
                finished = _now(self.clock)
                with closing(self._connect()) as connection, connection:
                    connection.execute(
                        """
                        UPDATE deliveries
                        SET status = 'uncertain_audit_pending', updated_utc = ?,
                            provider_message_id = NULL, error_code = ?
                        WHERE delivery_id = ?
                        """,
                        (finished, reason, delivery_id),
                    )
                existing = self._read(delivery_id)
                if existing is not None:
                    self._complete_pending_uncertain_audit(
                        existing,
                        action=action,
                    )
                raise ChannelSendUncertainError("channel-send-uncertain")
            if outcome.status == "rejected":
                reason = _safe_error_code(outcome.error_code, "provider-rejected")
                finished = _now(self.clock)
                with closing(self._connect()) as connection, connection:
                    connection.execute(
                        """
                        UPDATE deliveries
                        SET status = 'rejected_audit_pending', updated_utc = ?,
                            provider_message_id = NULL, error_code = ?
                        WHERE delivery_id = ?
                        """,
                        (finished, reason, delivery_id),
                    )
                existing = self._read(delivery_id)
                if existing is None or not self._complete_pending_rejected_audit(
                    existing,
                    action=action,
                ):
                    raise ChannelSendUncertainError("channel-send-uncertain")
                return False
            try:
                finished = _now(self.clock)
                with closing(self._connect()) as connection, connection:
                    connection.execute(
                        """
                        UPDATE deliveries
                        SET status = 'sent_audit_pending', updated_utc = ?,
                            provider_message_id = ?, error_code = 'audit-write-failed'
                        WHERE delivery_id = ?
                        """,
                        (finished, delivery_id, delivery_id),
                    )
            except Exception:
                reason = "post-handoff-state-failure"
                try:
                    with closing(self._connect()) as connection, connection:
                        connection.execute(
                            """
                            UPDATE deliveries
                            SET status = 'uncertain_audit_pending', updated_utc = ?,
                                provider_message_id = NULL, error_code = ?
                            WHERE delivery_id = ?
                            """,
                            (now, reason, delivery_id),
                        )
                except Exception:
                    pass
                try:
                    existing = self._read(delivery_id)
                    if existing is not None:
                        self._complete_pending_uncertain_audit(
                            existing,
                            action=action,
                        )
                except Exception:
                    pass
                raise ChannelSendUncertainError("channel-send-uncertain")
            existing = self._read(delivery_id)
            if existing is None or not self._complete_pending_audit(
                existing,
                action=action,
            ):
                raise ChannelSendUncertainError("channel-send-uncertain")
            return True


__all__ = [
    "ChannelSendUncertainError",
    "DeliveryResult",
    "HermesWeixinTransport",
    "ProfileDeliveryBlockedError",
    "WeixinHealthChannel",
    "WeixinVersionMismatchError",
]

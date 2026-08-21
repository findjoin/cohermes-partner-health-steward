"""Partner-only Weixin adapter that admits health events before text batching."""

from __future__ import annotations

import asyncio
import contextvars
import datetime as dt
import logging
import threading
import time
from dataclasses import replace
from typing import Any

from gateway.platforms.base import MessageEvent, MessageType
from gateway.platforms.weixin import WeixinAdapter, _extract_text, _guess_chat_type

from weixin_ingress import (
    PROCESSING_MARKER,
    PROFILE_UPDATED_MARKER,
    IngressOutcome,
    PartnerWeixinIngressCoordinator,
    TrustedWeixinEnvelope,
)
from sidecar.recording import FEEDBACK_BACKFILLED, FEEDBACK_NOT_RECORDED


logger = logging.getLogger(__name__)
_TAIL_METADATA_KEY = "health_steward_tail_marker"
_RETRY_STOP_POLL_SECONDS = 0.5
_OWNER_CONTROL_METHODS = (
    "recognizes",
    "handle",
    "is_recording_transition",
    "prepare_recording_transition",
    "deliver_prepared",
)


class PartnerHealthWeixinAdapter(WeixinAdapter):
    """Wrap the pinned native adapter without modifying Hermes core."""

    def __init__(
        self,
        config: Any,
        coordinator: PartnerWeixinIngressCoordinator,
        *,
        profile_name: str = "partner",
        health_ingress_budget_seconds: float = 15.0,
        health_retry_enabled: bool = False,
        health_retry_delay_seconds: float = 0.0,
        health_turn_handler: Any | None = None,
        owner_control_handler: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._health_coordinator = coordinator
        self._health_profile_name = profile_name
        self._health_ingress_budget_seconds = float(
            health_ingress_budget_seconds
        )
        if self._health_ingress_budget_seconds <= 0:
            raise ValueError("health-ingress-budget-must-be-positive")
        self._health_retry_enabled = bool(health_retry_enabled)
        self._health_turn_handler = health_turn_handler
        self._owner_control_handler = owner_control_handler
        if self._owner_control_handler is not None and any(
            not callable(getattr(self._owner_control_handler, method, None))
            for method in _OWNER_CONTROL_METHODS
        ):
            raise ValueError("owner-control-handler-invalid")
        self._health_retry_delay_seconds = float(health_retry_delay_seconds)
        if not 0 <= self._health_retry_delay_seconds < 600:
            raise ValueError("health-retry-delay-out-of-range")
        self._health_preflight_lock = asyncio.Lock()
        self._health_enqueue_lock = asyncio.Lock()
        self._health_next_sequence = 0
        self._health_next_flush_sequence = 0
        self._health_completed_events: dict[int, Any] = {}
        self._health_retry_tasks: dict[str, asyncio.Task[Any]] = {}
        self._health_tail_context: contextvars.ContextVar[str | None] = (
            contextvars.ContextVar(
                f"health_tail_{id(self)}", default=None
            )
        )

    def bind_health_turn_handler(self, handler: Any) -> None:
        """Complete the one-time production composition after native token load."""
        if self._health_turn_handler is not None:
            raise RuntimeError("health-turn-handler-already-bound")
        if not callable(getattr(handler, "handle", None)):
            raise ValueError("health-turn-handler-invalid")
        self._health_turn_handler = handler

    def bind_owner_control_handler(self, handler: Any) -> None:
        """Bind the pre-batch control route after the shared channel exists."""
        if self._owner_control_handler is not None:
            raise RuntimeError("owner-control-handler-already-bound")
        if any(
            not callable(getattr(handler, method, None))
            for method in _OWNER_CONTROL_METHODS
        ):
            raise ValueError("owner-control-handler-invalid")
        self._owner_control_handler = handler

    async def _process_message(self, message: dict[str, Any]) -> None:
        """Use trusted message IDs, not text fingerprints, for partner text."""
        sender_id = str(message.get("from_user_id") or "").strip()
        message_id = str(message.get("message_id") or "").strip()
        item_list = message.get("item_list") or []
        text = _extract_text(item_list)
        if (
            not sender_id
            or not message_id
            or not text
            or any(item.get("type") != 1 for item in item_list)
        ):
            await super()._process_message(message)
            return
        chat_type, effective_chat_id = _guess_chat_type(
            message,
            self._account_id,
        )
        # Destructive/profile-revealing controls are DM-only even when native
        # group intake is explicitly enabled.  The execution gate below
        # repeats the boundary against the trusted MessageEvent source.
        recognized_control = False
        candidate: TrustedWeixinEnvelope | None = None
        if self._owner_control_handler is not None:
            candidate = TrustedWeixinEnvelope(
                sender_id=sender_id,
                message_id=message_id,
                message_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                message_text=text,
                channel="weixin",
                profile_name=self._health_profile_name,
            )
            try:
                recognized_control = self._owner_control_handler.recognizes(candidate)
            except Exception as exc:
                logger.warning(
                    "[weixin] owner control match failed message_id=%s code=%s",
                    message_id,
                    type(exc).__name__,
                )
                return
            if recognized_control and chat_type != "dm":
                logger.warning(
                    "[weixin] owner control rejected outside DM message_id=%s",
                    message_id,
                )
                return
        if sender_id == self._account_id or self._dedup.is_duplicate(message_id):
            return
        if chat_type == "group":
            if self._group_policy == "disabled":
                return
            if (
                self._group_policy == "allowlist"
                and effective_chat_id not in self._group_allow_from
            ):
                return
            if self._group_policy == "pairing":
                return
        elif not self._is_dm_intake_allowed(sender_id):
            recovery_attempt = False
            is_identity_recovery = getattr(
                self._owner_control_handler, "is_identity_recovery", None
            )
            if recognized_control and callable(is_identity_recovery) and candidate:
                try:
                    recovery_attempt = bool(is_identity_recovery(candidate))
                except Exception:
                    recovery_attempt = False
            if not recovery_attempt:
                try:
                    dynamic_owner = await asyncio.to_thread(
                        self._health_coordinator.is_current_owner, sender_id
                    )
                except Exception:
                    dynamic_owner = False
                if not dynamic_owner:
                    return
        context_token = str(message.get("context_token") or "").strip()
        if context_token:
            self._token_store.set(self._account_id, sender_id, context_token)
        asyncio.create_task(
            self._maybe_fetch_typing_ticket(
                sender_id,
                context_token or None,
            )
        )
        source = self.build_source(
            chat_id=effective_chat_id,
            chat_type=chat_type,
            user_id=sender_id,
            user_name=sender_id,
        )
        self._enqueue_text_event(
            MessageEvent(
                text=text,
                message_type=MessageType.TEXT,
                source=source,
                raw_message=message,
                message_id=message_id,
                timestamp=dt.datetime.now(),
            )
        )

    def _enqueue_text_event(self, event: Any) -> None:
        """Capture each admitted event independently before native batching."""
        sequence = self._health_next_sequence
        self._health_next_sequence += 1
        arrival_monotonic = time.monotonic()
        # Keep trusted arrival ordering below one second so a genuine second
        # owner deletion receipt cannot be mistaken for the first request.
        message_utc = dt.datetime.now(dt.timezone.utc).isoformat()
        task = asyncio.create_task(
            self._admit_then_enqueue(
                event, sequence, message_utc, arrival_monotonic
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _admit_then_enqueue(
        self,
        event: Any,
        sequence: int,
        message_utc: str,
        arrival_monotonic: float,
    ) -> None:
        cancellation = threading.Event()
        deadline = arrival_monotonic + self._health_ingress_budget_seconds
        envelope: TrustedWeixinEnvelope | None = None
        health_outcome: Any | None = None
        retry_required = False
        health_decision_seen = threading.Event()
        source_verification_required = False

        def observe_health_decision(
            health_related: bool, requires_source_verification: bool
        ) -> None:
            nonlocal source_verification_required
            if health_related:
                source_verification_required = bool(
                    requires_source_verification
                )
                health_decision_seen.set()

        def failed_health_outcome() -> IngressOutcome:
            return IngressOutcome(
                "health-ingress-failed",
                health_related=True,
                source_verification_required=source_verification_required,
                health_answer_ready=False,
            )

        try:
            sender_id = str(getattr(event.source, "user_id", "") or "").strip()
            message_id = str(getattr(event, "message_id", "") or "").strip()
            if not sender_id or not message_id:
                raise ValueError("trusted-weixin-identity-missing")
            envelope = TrustedWeixinEnvelope(
                sender_id=sender_id,
                message_id=message_id,
                message_utc=message_utc,
                message_text=str(getattr(event, "text", "")),
                channel="weixin",
                profile_name=self._health_profile_name,
            )
            control_recognized = False
            is_direct_message = (
                str(getattr(event.source, "chat_type", "")).strip().lower()
                == "dm"
            )
            if self._owner_control_handler is not None and is_direct_message:
                try:
                    control_recognized = bool(
                        self._owner_control_handler.recognizes(envelope)
                    )
                except Exception as exc:
                    logger.warning(
                        "[weixin] owner control match failed message_id=%s code=%s",
                        envelope.message_id,
                        type(exc).__name__,
                    )
                    await self._complete_health_sequence(sequence, None)
                    return
            if control_recognized:
                ordered_control_delivery: tuple[Any, Any] | None = None
                try:
                    if self._owner_control_handler.is_recording_transition(
                        envelope
                    ):
                        # Only the stop/resume state transition shares the FIFO
                        # preflight gate. Its Weixin delivery runs afterwards so
                        # a slow transport cannot consume a later health turn's
                        # classification budget.
                        async with self._health_preflight_lock:
                            prepared = await asyncio.to_thread(
                                self._owner_control_handler.prepare_recording_transition,
                                envelope,
                            )
                        ordered_control_delivery = (
                            self._owner_control_handler,
                            prepared,
                        )
                    else:
                        # Private views and explicit analysis can stream or call
                        # the pinned model without blocking recording preflight.
                        await asyncio.to_thread(
                            self._owner_control_handler.handle,
                            envelope,
                        )
                except Exception as exc:
                    logger.warning(
                        "[weixin] owner control failed message_id=%s code=%s",
                        envelope.message_id,
                        type(exc).__name__,
                    )
                await self._complete_health_sequence(
                    sequence,
                    None,
                    control_delivery=ordered_control_delivery,
                )
                return
            # Consent and recording-state changes are ordered, but independent
            # health model calls run concurrently. Two rapid messages therefore
            # share one 15-second wall-clock budget instead of queuing to 30s.
            async with self._health_preflight_lock:
                outcome = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._health_coordinator.prepare,
                        envelope,
                        cancellation_requested=cancellation.is_set,
                        deadline_monotonic=deadline,
                    ),
                    timeout=max(0.001, deadline - time.monotonic()),
                )
            if outcome is None:
                outcome = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._health_coordinator.classify_and_admit,
                        envelope,
                        cancellation_requested=cancellation.is_set,
                        deadline_monotonic=deadline,
                        health_decision_observed=observe_health_decision,
                    ),
                    timeout=max(0.001, deadline - time.monotonic()),
                )
            if outcome.recovery_code is not None:
                deliver_recovery_code = getattr(
                    self._owner_control_handler,
                    "deliver_initial_recovery_code",
                    None,
                )
                if not callable(deliver_recovery_code):
                    raise RuntimeError("initial-recovery-code-delivery-unconfigured")
                delivered = await asyncio.to_thread(
                    deliver_recovery_code,
                    envelope,
                    outcome.recovery_code,
                )
                if delivered is not True:
                    raise RuntimeError("initial-recovery-code-delivery-unconfirmed")
                await self._complete_health_sequence(sequence, None)
                return
            if outcome.tail_marker:
                event.metadata[_TAIL_METADATA_KEY] = outcome.tail_marker
            if outcome.health_related:
                health_outcome = outcome
        except asyncio.TimeoutError:
            retry_required = True
            if health_decision_seen.is_set():
                health_outcome = failed_health_outcome()
            logger.warning(
                "[weixin] health ingress timed out message_id=%s",
                str(getattr(event, "message_id", "") or ""),
            )
        except Exception as exc:
            retry_required = True
            if health_decision_seen.is_set():
                health_outcome = failed_health_outcome()
            # A known-health admission failure remains on the fixed health
            # route. Only a classifier failure before any health decision may
            # continue through ordinary chat under the bounded policy.
            logger.warning(
                "[weixin] health ingress rejected message_id=%s code=%s",
                str(getattr(event, "message_id", "") or ""),
                type(exc).__name__,
            )
        finally:
            # asyncio.to_thread cannot terminate a running worker. Every exit,
            # including Gateway shutdown cancellation, therefore signals the
            # coordinator so late work cannot continue to sign or write.
            cancellation.set()

        if retry_required and envelope is not None and self._health_retry_enabled:
            event.metadata[_TAIL_METADATA_KEY] = PROCESSING_MARKER
            self._schedule_health_retry(envelope)
            if health_outcome is not None:
                health_outcome = replace(
                    health_outcome,
                    tail_marker=PROCESSING_MARKER,
                )

        if health_outcome is not None and envelope is not None:
            await self._complete_health_sequence(
                sequence,
                event,
                envelope=envelope,
                outcome=health_outcome,
            )
            return

        await self._complete_health_sequence(sequence, event)

    async def _complete_health_sequence(
        self,
        sequence: int,
        event: Any | None,
        *,
        envelope: TrustedWeixinEnvelope | None = None,
        outcome: Any | None = None,
        control_delivery: tuple[Any, Any] | None = None,
    ) -> None:
        async with self._health_enqueue_lock:
            self._health_completed_events[sequence] = (
                event,
                envelope,
                outcome,
                control_delivery,
            )
            while self._health_next_flush_sequence in self._health_completed_events:
                (
                    queued,
                    health_envelope,
                    health_outcome,
                    ordered_control,
                ) = self._health_completed_events.pop(self._health_next_flush_sequence)
                self._health_next_flush_sequence += 1
                if ordered_control is not None:
                    handler, prepared = ordered_control
                    delivery_task = asyncio.create_task(
                        asyncio.to_thread(handler.deliver_prepared, prepared)
                    )
                    try:
                        await asyncio.shield(delivery_task)
                    except asyncio.CancelledError:
                        # The transport thread cannot be stopped safely. Keep
                        # the single ordered consumer occupied until it settles
                        # so a later lifecycle result cannot overtake it.
                        await delivery_task
                        raise
                    except Exception as exc:
                        logger.warning(
                            "[weixin] ordered owner control delivery failed code=%s",
                            type(exc).__name__,
                        )
                    continue
                if health_outcome is not None and health_envelope is not None:
                    if self._health_turn_handler is None:
                        # Compatibility for an explicitly unconfigured local
                        # adapter. Production plugin construction always
                        # supplies the pinned health handler.
                        pass
                    else:
                        answer_cancellation = threading.Event()
                        try:
                            await asyncio.to_thread(
                                self._health_turn_handler.handle,
                                health_envelope,
                                health_outcome,
                                cancellation_requested=(
                                    answer_cancellation.is_set
                                ),
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            # Health-answer failures never fall back to the
                            # ordinary model or its session history.
                            logger.warning(
                                "[weixin] health answer failed message_id=%s code=%s",
                                health_envelope.message_id,
                                type(exc).__name__,
                            )
                        finally:
                            # A cancelled asyncio wait cannot terminate the
                            # worker thread. Signal the synchronous handler so
                            # it cannot perform a later channel handoff.
                            answer_cancellation.set()
                        continue
                if queued is None:
                    continue
                key = self._text_batch_key(queued)
                existing = self._pending_text_batches.get(key)
                marker = queued.metadata.get(_TAIL_METADATA_KEY)
                if existing is not None and isinstance(marker, str) and marker:
                    existing.metadata[_TAIL_METADATA_KEY] = marker
                super()._enqueue_text_event(queued)

    def _schedule_health_retry(self, envelope: TrustedWeixinEnvelope) -> None:
        if envelope.message_id in self._health_retry_tasks:
            return
        task = asyncio.create_task(self._retry_once(envelope))
        self._health_retry_tasks[envelope.message_id] = task
        self._background_tasks.add(task)

        def done(completed: asyncio.Task[Any]) -> None:
            self._health_retry_tasks.pop(envelope.message_id, None)
            self._background_tasks.discard(completed)

        task.add_done_callback(done)

    async def _retry_once(self, envelope: TrustedWeixinEnvelope) -> None:
        cancellation = threading.Event()
        feedback_status = FEEDBACK_NOT_RECORDED
        try:
            if not await self._wait_for_retry_delay_while_enabled(envelope):
                return
            deadline = time.monotonic() + self._health_ingress_budget_seconds
            async with self._health_preflight_lock:
                prepared = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._health_coordinator.prepare,
                        envelope,
                        cancellation_requested=cancellation.is_set,
                        deadline_monotonic=deadline,
                    ),
                    timeout=max(0.001, deadline - time.monotonic()),
                )
            if prepared is not None:
                # Recording was stopped or authorization disappeared while the
                # bounded retry was pending. Clear the in-memory envelope and
                # do not create another health-model call or status message.
                return
            admitted = await asyncio.wait_for(
                asyncio.to_thread(
                    self._health_coordinator.profile_message_admitted,
                    envelope,
                ),
                timeout=max(0.001, deadline - time.monotonic()),
            )
            if admitted:
                feedback_status = FEEDBACK_BACKFILLED
            else:
                attempt_utc = dt.datetime.now(dt.timezone.utc).replace(
                    microsecond=0
                ).isoformat()
                outcome = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._health_coordinator.classify_and_admit,
                        envelope,
                        attempt_utc=attempt_utc,
                        cancellation_requested=cancellation.is_set,
                        deadline_monotonic=deadline,
                    ),
                    timeout=max(0.001, deadline - time.monotonic()),
                )
                if outcome.status == "profile-updated":
                    feedback_status = FEEDBACK_BACKFILLED
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                recording_stopped = not await asyncio.to_thread(
                    self._health_coordinator.health_recording_enabled,
                    envelope,
                )
            except Exception:
                recording_stopped = False
            if recording_stopped:
                return
            logger.warning(
                "[weixin] health ingress retry failed message_id=%s code=%s",
                envelope.message_id,
                type(exc).__name__,
            )
        finally:
            cancellation.set()
        try:
            await asyncio.to_thread(
                self._health_coordinator.send_feedback,
                envelope,
                feedback_status,
            )
        except Exception as exc:
            logger.warning(
                "[weixin] health ingress feedback failed message_id=%s code=%s",
                envelope.message_id,
                type(exc).__name__,
            )

    async def _wait_for_retry_delay_while_enabled(
        self, envelope: TrustedWeixinEnvelope
    ) -> bool:
        """Drop a pending envelope promptly when sidecar recording stops."""
        deadline = time.monotonic() + self._health_retry_delay_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            await asyncio.sleep(min(_RETRY_STOP_POLL_SECONDS, remaining))
            if not await asyncio.to_thread(
                self._health_coordinator.health_recording_enabled,
                envelope,
            ):
                return False

    async def _process_message_background(self, event: Any, session_key: str) -> None:
        marker = event.metadata.get(_TAIL_METADATA_KEY)
        token = self._health_tail_context.set(
            marker if isinstance(marker, str) and marker else None
        )
        try:
            await super()._process_message_background(event, session_key)
        finally:
            self._health_tail_context.reset(token)

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        marker = self._health_tail_context.get()
        # The status phrase is reserved for adapter-owned sidecar evidence.
        # Strip any model-authored copy first, then append exactly one only
        # when this turn carries a confirmed sidecar marker.
        final_content = content
        for reserved in (PROFILE_UPDATED_MARKER, PROCESSING_MARKER):
            final_content = final_content.replace(reserved, "")
        final_content = final_content.rstrip()
        if marker in (PROFILE_UPDATED_MARKER, PROCESSING_MARKER):
            final_content = (
                f"{final_content}\n\n{marker}"
                if final_content
                else marker
            )
        return await super().send(
            chat_id=chat_id,
            content=final_content,
            reply_to=reply_to,
            metadata=metadata,
        )


__all__ = ["PartnerHealthWeixinAdapter"]

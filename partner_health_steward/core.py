"""Single-writer health-core state machine for Ticket 110."""

from __future__ import annotations

from typing import Any

from .contract import CommandEnvelope, ProtocolViolation, Response
from .current_head import HeadConflict, HeadTerminal, HeadTimeout, HeadUnknown
from .probe import ProbeReport, ProbeState
from .storage import EncryptedStateStore, KeyUnavailable


class HealthCore:
    def __init__(self, store: EncryptedStateStore, current_head: Any) -> None:
        self._store = store
        self._current_head = current_head
        self._closed_reason: str | None = None

    def handle(self, command: CommandEnvelope) -> Response:
        previous = self._store.receipt(command.causal_id)
        if previous is not None:
            return Response("replayed", command.causal_id, "duplicate-causal-id")

        try:
            response = self._handle_new(command)
        except ProtocolViolation as exc:
            response = Response("rejected", command.causal_id, str(exc))
        except KeyUnavailable:
            self._closed_reason = "health-key-unavailable"
            response = Response("unavailable", command.causal_id, self._closed_reason)
        self._store.save_receipt(command.causal_id, response.status, response.reason_code)
        return response

    def _handle_new(self, command: CommandEnvelope) -> Response:
        if command.action == "probe":
            report = self.probe()
            return Response("accepted", command.causal_id, report.reason_code, {"probe_state": report.state.value})
        try:
            head = self._read_head_or_close()
        except HeadUnknown:
            self._closed_reason = "current-head-unknown"
            return Response("unknown", command.causal_id, self._closed_reason)
        except (HeadConflict, HeadTimeout):
            self._closed_reason = "current-head-unavailable"
            return Response("unavailable", command.causal_id, self._closed_reason)
        if command.generation != head.generation:
            raise ProtocolViolation("generation mismatch")

        # Finalize is the only recovery write allowed while an otherwise healthy
        # path is stopped by an explicit prepared/committed crash state.
        transition_recovery = command.action in {"state.commit", "state.finalize"}
        if not transition_recovery and not self.health_writes_allowed():
            return Response("unavailable", command.causal_id, self._closed_reason or "health-path-closed")

        if command.action in {"state.candidate", "state.prepare", "state.commit", "state.finalize"}:
            return self._handle_state(command, head)
        if command.action == "effect.result":
            return self._handle_effect(command)
        raise ProtocolViolation("unknown action")

    def _handle_state(self, command: CommandEnvelope, head: Any) -> Response:
        payload = dict(command.payload)
        record_id = payload["record_id"]
        revision = payload["revision_digest"]
        transition = payload["transition_id"]
        current = self._store.record(record_id)
        if command.action == "state.candidate":
            self._store.write_record(record_id, "candidate", revision, transition, payload)
            return Response("accepted", command.causal_id, "candidate-recorded")
        if current is None or current[0] not in {"candidate", "prepared", "committed"}:
            raise ProtocolViolation("record is not prepared for this action")
        if command.action == "state.prepare":
            self._store.write_record(record_id, "prepared", revision, transition, payload)
            return Response("accepted", command.causal_id, "revision-prepared")
        if command.action == "state.commit":
            if current[0] != "prepared":
                raise ProtocolViolation("record is not prepared")
            try:
                updated = self._current_head.conditional_advance(
                    expected_generation=head.generation,
                    expected_revision_digest=head.revision_digest,
                    transition_id=transition,
                    revision_digest=revision,
                    writer_fence=payload.get("writer_fence"),
                )
            except HeadConflict:
                self._closed_reason = "current-head-conflict"
                return Response("unavailable", command.causal_id, self._closed_reason)
            except HeadTimeout:
                self._closed_reason = "current-head-timeout"
                return Response("unavailable", command.causal_id, self._closed_reason)
            except HeadUnknown:
                self._store.write_record(record_id, "unknown", revision, transition, payload)
                self._closed_reason = "current-head-unknown"
                return Response("unknown", command.causal_id, self._closed_reason)
            except HeadTerminal:
                self._closed_reason = "current-head-terminal"
                return Response("unavailable", command.causal_id, self._closed_reason)
            self._store.write_record(record_id, "committed", revision, transition, {**payload, "writer_fence": updated.writer_fence})
            return Response(
                "accepted",
                command.causal_id,
                "current-head-advanced",
                {"generation": updated.generation, "writer_fence": updated.writer_fence},
            )
        if command.action == "state.finalize":
            if current[0] not in {"prepared", "committed"}:
                raise ProtocolViolation("record is not ready to finalize")
            if (
                payload["writer_fence"] != head.writer_fence
                or revision != head.revision_digest
                or transition != head.transition_id
            ):
                self._closed_reason = "stale-writer-fence"
                return Response("unavailable", command.causal_id, self._closed_reason)
            self._store.write_record(record_id, "final", revision, transition, payload)
            self._closed_reason = None
            return Response("accepted", command.causal_id, "revision-finalized")
        raise ProtocolViolation("unknown state action")

    def _handle_effect(self, command: CommandEnvelope) -> Response:
        payload = dict(command.payload)
        state = payload["status"]
        if not payload["terminal"]:
            raise ProtocolViolation("effect result is incomplete")
        self._store.write_effect(payload["effect_id"], state, payload)
        if state == "unknown":
            self._closed_reason = "effect-result-unknown"
            return Response("unknown", command.causal_id, self._closed_reason)
        return Response("accepted" if state == "accepted" else "rejected", command.causal_id, "effect-terminal")

    def probe(self) -> ProbeReport:
        if self._closed_reason in {"current-head-unknown", "effect-result-unknown", "health-key-unavailable"}:
            return ProbeReport(ProbeState.UNKNOWN, self._closed_reason)
        try:
            self._store.verify_key()
            head = self._current_head.read().head
        except KeyUnavailable:
            self._closed_reason = "health-key-unavailable"
            return ProbeReport(ProbeState.UNAVAILABLE, self._closed_reason)
        except HeadUnknown:
            return ProbeReport(ProbeState.UNKNOWN, "current-head-unknown")
        except (HeadConflict, HeadTimeout):
            return ProbeReport(ProbeState.UNKNOWN, "current-head-unavailable")
        if head.terminal:
            return ProbeReport(ProbeState.UNAVAILABLE, "terminal-deletion")
        unresolved = self._store.unresolved_states()
        if "unknown" in unresolved:
            return ProbeReport(ProbeState.UNKNOWN, "local-transition-unknown")
        if any(state in {"prepared", "committed"} for state in unresolved):
            return ProbeReport(ProbeState.UNKNOWN, "local-transition-unresolved")
        if self._closed_reason is not None:
            return ProbeReport(ProbeState.UNAVAILABLE, self._closed_reason)
        return ProbeReport(ProbeState.HEALTHY, "contract-ok", checks=("key-boundary", "current-head", "single-writer"))

    def health_writes_allowed(self) -> bool:
        return self.probe().state is ProbeState.HEALTHY

    def model_effects_allowed(self) -> bool:
        return self.health_writes_allowed()

    def outbound_effects_allowed(self) -> bool:
        return self.health_writes_allowed()

    def _read_head_or_close(self) -> Any:
        try:
            return self._current_head.read().head
        except (HeadUnknown, HeadConflict, HeadTimeout):
            raise

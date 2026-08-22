"""Current Plugin facade; storage and authority remain inside health-core."""

from __future__ import annotations

from .contract import CommandEnvelope, ProtocolViolation, Response, decode_frame, encode_raw_response
from .core import HealthCore
from .probe import ProbeReport


class HealthPlugin:
    def __init__(self, core: HealthCore) -> None:
        self._core = core

    def invoke(self, command: CommandEnvelope, *, peer_id: str) -> Response:
        if peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if command.peer != "plugin":
            raise ProtocolViolation("untrusted command peer")
        return self._core.handle(command)

    def handle_frame(self, frame: bytes, *, peer_id: str) -> bytes:
        try:
            if peer_id != "plugin":
                raise ProtocolViolation("untrusted peer")
            command = decode_frame(frame)
            response = self.invoke(command, peer_id=peer_id)
        except ProtocolViolation as exc:
            response = Response("rejected", reason_code=str(exc))
        return encode_raw_response(response)

    def probe(self, *, ordinary_hermes_status: str | None = None) -> ProbeReport:
        # The ordinary Hermes status is intentionally ignored: it is not health proof.
        del ordinary_hermes_status
        return self._core.probe()

    def health_writes_allowed(self) -> bool:
        return self._core.health_writes_allowed()

    def model_effects_allowed(self) -> bool:
        return self._core.model_effects_allowed()

    def outbound_effects_allowed(self) -> bool:
        return self._core.outbound_effects_allowed()

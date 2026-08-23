"""Current Plugin facade; storage and authority remain inside health-core."""

from __future__ import annotations

from .authority import EffectExecutionGrant, EffectIntent
from .contract import CommandEnvelope, ProtocolViolation, Response, decode_frame, encode_raw_response
from .core import HealthCore
from .probe import ProbeReport


class HealthPlugin:
    def __init__(self, core: HealthCore) -> None:
        self._core = core

    def invoke(self, command: CommandEnvelope, *, peer_id: str) -> Response:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        # Do not read fields from a caller-provided Python object here.  Core
        # canonicalizes it through the strict wire parser before any command
        # field can reach state or authority handling.
        return self._core.handle(command)

    def handle_frame(self, frame: bytes, *, peer_id: str) -> bytes:
        try:
            if type(peer_id) is not str or peer_id != "plugin":
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

    def claim_effect_execution(self, intent: EffectIntent) -> EffectExecutionGrant | None:
        """Return the non-durable completion grant before an adapter may act."""

        return self._core.claim_effect_execution(intent)

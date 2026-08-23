"""Current Plugin facade; storage and authority remain inside health-core."""

from __future__ import annotations

from .admission import (
    AdmissionPolicy,
    NativeCursorDirective,
    RawWeixinMessage,
    SourceEnvelope,
    SourceReceipt,
    materialize_source,
)
from .authority import AuthorityValidationError, EffectExecutionGrant, EffectIntent
from .contract import (
    CommandEnvelope,
    InboundAdmitPayload,
    InitializationPreparePayload,
    NativeCursorResultPayload,
    ProtocolViolation,
    Response,
    StateCommitPayload,
    decode_frame,
    encode_raw_response,
)
from .core import HealthCore
from .initialization import (
    HealthInitRuntime,
    InitializationProjection,
    OwnerInitialization,
)
from .probe import ProbeReport


class HealthPlugin:
    def __init__(
        self,
        core: HealthCore,
        *,
        admission_policy: AdmissionPolicy | None = None,
        health_init_runtime: HealthInitRuntime | None = None,
    ) -> None:
        self._core = core
        self._admission_policy = admission_policy
        self._health_init_runtime = health_init_runtime

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

    def receive_weixin(self, message: RawWeixinMessage, *, peer_id: str) -> Response:
        """Apply technical admission before a native adapter materializes text."""

        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        policy = self._admission_policy
        if type(policy) is not AdmissionPolicy:
            return Response("unavailable", reason_code="admission-policy-unavailable")
        reason = policy.rejection_reason(message)
        causal_id = (
            message.causal_id
            if type(message) is RawWeixinMessage
            and type(message.causal_id) is str
            and message.causal_id
            else None
        )
        if reason is not None:
            return Response("rejected", causal_id, reason)
        try:
            envelope = materialize_source(message)
            command = CommandEnvelope(
                peer="plugin",
                action="inbound.admit",
                source="health_weixin",
                causal_id=envelope.causal_id,
                generation=message.generation,
                scope=("inbound:admit",),
                payload=InboundAdmitPayload(envelope),
            )
        except (AuthorityValidationError, ProtocolViolation, TypeError, ValueError):
            return Response("rejected", causal_id, "invalid-weixin-source")
        return self.invoke(command, peer_id=peer_id)

    def source_envelope(self, causal_id: str, *, peer_id: str) -> SourceEnvelope | None:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        return self._core.source_envelope(causal_id)

    def source_receipt(self, causal_id: str, *, peer_id: str) -> SourceReceipt | None:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        return self._core.source_receipt(causal_id)

    def prepare_initialization(
        self,
        initialization: OwnerInitialization,
        *,
        peer_id: str,
    ) -> Response:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        runtime = self._health_init_runtime
        if type(runtime) is not HealthInitRuntime:
            return Response("unavailable", reason_code="health-init-runtime-unavailable")
        if type(initialization) is not OwnerInitialization:
            return Response("rejected", reason_code="invalid-owner-initialization")
        reason = initialization.incomplete_reason
        if reason is not None:
            return Response("rejected", reason_code=reason)
        try:
            proof = runtime.run(initialization)
        except AuthorityValidationError as exc:
            reason_code = str(exc)
            if reason_code == "health-init-execution-failed":
                return Response("unavailable", reason_code=reason_code)
            if reason_code not in {
                "owner-consent-required",
                "first-hop-route-consent-required",
                "health-init workflow conflict",
            }:
                reason_code = "health-init-runtime-failed"
            return Response("rejected", reason_code=reason_code)
        source = self._core.source_envelope(initialization.admission_causal_id)
        if source is None:
            status = self._core.initialization_status()
            if (
                status.skill_use is None
                or status.skill_use.workflow_id != initialization.workflow_id
                or status.skill_use.admission_causal_id != initialization.admission_causal_id
                or status.prepared_authority is None
            ):
                return Response("rejected", reason_code="initialization-source-required")
            generation = status.prepared_authority.generation
        else:
            generation = source.generation
        command = CommandEnvelope(
            peer="plugin",
            action="initialization.prepare",
            source="health_weixin",
            causal_id="initialization-prepare:" + initialization.workflow_id,
            generation=generation,
            scope=("initialization:prepare",),
            payload=InitializationPreparePayload(initialization, proof),
        )
        return self.invoke(command, peer_id=peer_id)

    def initialization_status(self, *, peer_id: str) -> InitializationProjection:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        return self._core.initialization_status()

    def commit_initialization(self, *, peer_id: str) -> Response:
        status = self.initialization_status(peer_id=peer_id)
        if status.phase not in {"prepared", "unknown", "committed", "enabled"}:
            return Response("rejected", reason_code="initialization-not-prepared")
        return self.invoke(
            self._initialization_transition_command(status, "state.commit"),
            peer_id=peer_id,
        )

    def finalize_initialization(self, *, peer_id: str) -> Response:
        status = self.initialization_status(peer_id=peer_id)
        if status.phase not in {"committed", "enabled"}:
            return Response("rejected", reason_code="initialization-not-committed")
        return self.invoke(
            self._initialization_transition_command(status, "state.finalize"),
            peer_id=peer_id,
        )

    @staticmethod
    def _initialization_transition_command(
        status: InitializationProjection,
        action: str,
    ) -> CommandEnvelope:
        authority = status.prepared_authority
        skill_use = status.skill_use
        if (
            authority is None
            or skill_use is None
            or status.record_id is None
            or status.revision_digest is None
            or status.transition_id is None
        ):
            raise ProtocolViolation("initialization transition unavailable")
        generation = authority.generation if action == "state.commit" else authority.generation + 1
        suffix = "commit" if action == "state.commit" else "finalize"
        return CommandEnvelope(
            peer="plugin",
            action=action,
            source="health_weixin",
            causal_id=f"initialization-{suffix}:{skill_use.workflow_id}",
            generation=generation,
            scope=(f"state:{suffix}",),
            payload=StateCommitPayload(
                record_id=status.record_id,
                revision_digest=status.revision_digest,
                transition_id=status.transition_id,
                writer_fence=authority.writer_fence,
            ),
        )

    def native_cursor_directive(
        self,
        source_causal_id: str,
        *,
        peer_id: str,
    ) -> NativeCursorDirective | None:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        return self._core.native_cursor_directive(source_causal_id)

    def record_native_cursor_result(
        self,
        directive: NativeCursorDirective,
        *,
        status: str,
        peer_id: str,
    ) -> Response:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if type(directive) is not NativeCursorDirective:
            return Response("rejected", reason_code="invalid-native-cursor-directive")
        initialization = self.initialization_status(peer_id=peer_id)
        authority = initialization.prepared_authority
        if authority is None or initialization.transition_id != directive.initialization_transition_id:
            return Response("rejected", reason_code="native-cursor-directive-stale")
        try:
            payload = NativeCursorResultPayload(
                source_causal_id=directive.source_causal_id,
                native_cursor=directive.native_cursor,
                status=status,
            )
            command = CommandEnvelope(
                peer="plugin",
                action="cursor.result",
                source="health_weixin",
                causal_id=f"native-cursor:{directive.source_causal_id}:{status}",
                generation=authority.generation + 1,
                scope=("cursor:result",),
                payload=payload,
            )
        except ProtocolViolation as exc:
            return Response("rejected", reason_code=str(exc))
        return self.invoke(command, peer_id=peer_id)

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

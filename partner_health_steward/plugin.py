"""Current Plugin facade; storage and authority remain inside health-core."""

from __future__ import annotations

from collections.abc import Mapping

from .answer_resolution import ModelEffectReport
from .admission import (
    AdmissionPolicy,
    NativeCursorDirective,
    RawWeixinMessage,
    SourceEnvelope,
    SourceReceipt,
    materialize_source,
)
from .authority import (
    AuthoritySnapshot,
    AuthorityValidationError,
    EffectExecutionGrant,
    EffectIntent,
    validate_opaque_text,
)
from .contract import (
    CommandEnvelope,
    CommitMeta,
    DailySourceMeta,
    DailyTurnMeta,
    DailyTurnPreparePayload,
    InboundAdmitPayload,
    InitializationDisclosurePayload,
    InitializationPreparePayload,
    NativeCursorResultPayload,
    OwnerPreparePayload,
    ProtocolViolation,
    Response,
    StateCommitPayload,
    decode_frame,
    encode_raw_response,
)
from .coordination import (
    AtomicEvidenceClaim,
    CoarseMessageRouter,
    DAILY_HEALTH_SKILL_NAMES,
    DailyHealthState,
    DailySkillRuntime,
    DailyTurnDraft,
)
from .core import (
    DailyTurnStatus,
    HealthCore,
    OwnerMutationStatus,
)
from .delivery import (
    DeliveryContractViolation,
    DeliveryTransition,
    OwnerDeliveryCompletion,
    OwnerDeliverySendIntent,
    OwnerDeliveryTransportResult,
    OwnerDeliveryWireAdapter,
    validate_owner_delivery_observed_at,
)
from .initialization import (
    HealthInitAsset,
    HealthInitRuntime,
    InitializationDisclosure,
    InitializationProjection,
    OwnerConsentEvidence,
    OwnerInitialization,
    stable_digest,
)
from .health_commands import (
    HealthCommandContractViolation,
    TrustedHealthCommand,
)
from .model_contract import (
    StrictHealthLLM,
    StrictModelAdapter,
    StrictModelOutcome,
    StrictModelRequest,
)
from .nondiagnostic import NonDiagnosticCandidate
from .owner_authority import OwnerMutationContext, OwnerMutationRequest
from .probe import ProbeReport, ProbeState
from .rights import (
    ManagedExport,
    ManagedObject,
    ManagedObjectReference,
    PendingCorrectionDraft,
)
from .settings import OwnerSettingsState
from .status import BusinessStatusResult


def _wire_fields(
    value: object,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, object]:
    if type(value) is not dict:
        raise ProtocolViolation("invalid Ticket 115 wire payload")
    keys = frozenset(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise ProtocolViolation("invalid Ticket 115 wire fields")
    return value


def _delivery_transition_wire(transition: DeliveryTransition) -> dict[str, object]:
    return {
        "intent_id": transition.intent_id,
        "outcome": transition.outcome,
        "replayed": transition.replayed,
        "current_layer": transition.record.current_layer,
    }


def _unknown_owner_delivery_completion(
    send_intent: OwnerDeliverySendIntent,
    *,
    observed_at_utc: str,
) -> OwnerDeliveryCompletion:
    digest = stable_digest(
        {
            "contract": "owner-delivery-plugin-unknown-v1",
            "intent_id": send_intent.intent_id,
            "attempt_ref": send_intent.attempt_ref,
            "reason": "transport-exception-or-malformed-result",
        }
    ).removeprefix("sha256:")
    return OwnerDeliveryCompletion(
        intent_id=send_intent.intent_id,
        attempt_ref=send_intent.attempt_ref,
        status="unknown",
        result_ref="owner-delivery-result:" + digest,
        evidence_ref="owner-delivery-observation:" + digest,
        observed_at_utc=observed_at_utc,
    )


class HealthPlugin:
    def __init__(
        self,
        core: HealthCore,
        *,
        admission_policy: AdmissionPolicy | None = None,
        health_init_runtime: HealthInitRuntime | None = None,
        coarse_router: CoarseMessageRouter | None = None,
        daily_skill_runtime: DailySkillRuntime | None = None,
    ) -> None:
        self._core = core
        self._admission_policy = admission_policy
        self._health_init_runtime = health_init_runtime
        self._coarse_router = coarse_router
        self._daily_skill_runtime = daily_skill_runtime

    def invoke(self, command: CommandEnvelope, *, peer_id: str) -> Response:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            return Response("unavailable", reason_code="admission-policy-mismatch")
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
        initialization = self._core.initialization_status()
        allowed_capabilities = (
            ("health-init",)
            if initialization.phase == "uninitialized"
            else ("health-init", *DAILY_HEALTH_SKILL_NAMES)
        )
        reason = policy.rejection_reason(
            message,
            allowed_capabilities=allowed_capabilities,
        )
        causal_id = None
        if type(message) is RawWeixinMessage:
            try:
                causal_id = validate_opaque_text(message.causal_id, "causal_id")
            except AuthorityValidationError:
                pass
        if reason is not None:
            return Response("rejected", causal_id, reason)
        if not self._core.admission_policy_matches(policy):
            return Response(
                "unavailable",
                causal_id,
                "admission-policy-mismatch",
            )
        if initialization.phase == "cannot-confirm":
            return Response(
                "unavailable",
                causal_id,
                "initialization-state-unavailable",
            )
        if initialization.phase != "uninitialized" and (
            type(message) is not RawWeixinMessage
            or message.requested_capability == "health-init"
        ):
            return Response(
                "rejected",
                causal_id,
                "initialization already exists",
            )
        if initialization.phase not in {"uninitialized", "enabled"}:
            return Response(
                "unavailable",
                causal_id,
                "initialization-state-unavailable",
            )
        if (
            initialization.phase == "enabled"
            and self._core.ticket116_assets_configured()
        ):
            safety_entry = self._core.safety_entry_report()
            if safety_entry.state is not ProbeState.HEALTHY:
                return Response(
                    "unavailable",
                    causal_id,
                    safety_entry.reason_code,
                )
        if initialization.phase == "uninitialized":
            report = self._core.probe()
            if report.state is not ProbeState.HEALTHY:
                return Response("unavailable", causal_id, report.reason_code)
        try:
            envelope = materialize_source(message)
            if initialization.phase == "enabled":
                safety_facts = self._core.ticket116_rule_facts_for_body(
                    envelope.body
                )
                if safety_facts is not None:
                    admitted = self.invoke(
                        CommandEnvelope(
                            peer="plugin",
                            action="inbound.admit",
                            source="health_weixin",
                            causal_id=envelope.causal_id,
                            generation=message.generation,
                            scope=("inbound:admit",),
                            payload=InboundAdmitPayload(envelope, policy),
                        ),
                        peer_id=peer_id,
                    )
                    if admitted.status not in {"accepted", "replayed"}:
                        return admitted
                    try:
                        safety = self.health_operation(
                            "safety.evaluate",
                            {
                                "source_causal_id": envelope.causal_id,
                                "event_time": (
                                    envelope.protocol_timestamp
                                    or envelope.received_at
                                ),
                                "owner_recognizable_name": "主人",
                                "safety_rule_bundle_hash": (
                                    self._core.ticket116_safety_rule_bundle_hash()
                                ),
                                "facts": safety_facts,
                            },
                            context={
                                "source": "safety_runtime",
                                "causal_id": (
                                    "ticket116-inbound-safety:"
                                    + envelope.causal_id
                                ),
                                "generation": message.generation,
                                "scope": ["safety:evaluate"],
                            },
                            peer_id=peer_id,
                        )
                        return Response(
                            "accepted",
                            envelope.causal_id,
                            "ticket116-safety-result",
                            {
                                "branch": safety["branch"],
                                "owner_result": safety["owner_result"],
                                "contact_alert": safety["contact_alert"],
                            },
                        )
                    finally:
                        self._core.release_recording_plaintext_if_unowned(
                            envelope.causal_id
                        )
                router = self._coarse_router
                if type(router) is not CoarseMessageRouter:
                    return Response(
                        "unavailable",
                        envelope.causal_id,
                        "daily-routing-unavailable",
                    )
                classification = router.classify(
                    envelope.body,
                    envelope.requested_capability,
                )
                if (
                    classification == "ordinary"
                    and envelope.requested_capability == "health-steward"
                ):
                    return Response(
                        "accepted",
                        envelope.causal_id,
                        "ordinary-hermes-route",
                    )
                try:
                    return self._run_daily_turn(
                        envelope,
                        generation=message.generation,
                        peer_id=peer_id,
                    )
                finally:
                    # Admission may have placed a stopped-recording body only
                    # in core memory before a later status/read/commit failure.
                    # Every public receive exit must release it unless an
                    # unresolved durable turn is the sole recovery owner.
                    self._core.release_recording_plaintext_if_unowned(
                        envelope.causal_id
                    )
            command = CommandEnvelope(
                peer="plugin",
                action="inbound.admit",
                source="health_weixin",
                causal_id=envelope.causal_id,
                generation=message.generation,
                scope=("inbound:admit",),
                payload=InboundAdmitPayload(envelope, policy),
            )
        except (AuthorityValidationError, ProtocolViolation, TypeError, ValueError):
            return Response("rejected", causal_id, "invalid-weixin-source")
        return self.invoke(command, peer_id=peer_id)

    def _run_daily_turn(
        self,
        envelope: SourceEnvelope,
        *,
        generation: int,
        peer_id: str,
    ) -> Response:
        """Admit, prepare, commit, and finalize one resumable local health turn."""

        policy = self._admission_policy
        if type(policy) is not AdmissionPolicy:
            return Response("unavailable", envelope.causal_id, "admission-policy-unavailable")
        admitted = self.invoke(
            CommandEnvelope(
                peer="plugin",
                action="inbound.admit",
                source="health_weixin",
                causal_id=envelope.causal_id,
                generation=generation,
                scope=("inbound:admit",),
                payload=InboundAdmitPayload(envelope, policy),
            ),
            peer_id=peer_id,
        )
        if admitted.status not in {"accepted", "replayed"}:
            return admitted
        if (
            type(admitted.meta) is DailySourceMeta
            and admitted.meta.business_source_causal_id != envelope.causal_id
        ):
            root_causal_id = admitted.meta.business_source_causal_id
            root_status = self._core.daily_turn_status(root_causal_id)
            if root_status is None or root_status.phase != "finalized":
                return Response(
                    "unavailable",
                    envelope.causal_id,
                    "daily-source-native-replay-pending",
                )
            try:
                root_result = self._core.daily_turn_result(root_causal_id)
            except AuthorityValidationError as exc:
                return Response(
                    "unavailable",
                    envelope.causal_id,
                    str(exc) or "daily-turn-result-unavailable",
                )
            if root_result is None:
                return Response(
                    "replayed",
                    envelope.causal_id,
                    "daily-turn-result-redacted",
                )
            return Response(
                "replayed",
                envelope.causal_id,
                "daily-source-native-replay",
                DailyTurnMeta(root_result),
            )

        runtime = self._daily_skill_runtime
        status = self._core.daily_turn_status(envelope.causal_id)
        if status is None:
            try:
                with self._core.daily_turn_runtime_preparation(
                    envelope.causal_id
                ) as preparation:
                    if type(runtime) is not DailySkillRuntime:
                        return Response(
                            "unavailable",
                            envelope.causal_id,
                            "daily-turn-runtime-unavailable",
                        )
                    if preparation.reason_code == "daily-turn-busy":
                        return Response(
                            "unavailable",
                            envelope.causal_id,
                            preparation.reason_code,
                        )
                    if not preparation.ready:
                        status = self._core.daily_turn_status(envelope.causal_id)
                    else:
                        draft = runtime.execute_evidence_stage(
                            envelope,
                            self._core.daily_state(),
                        )
                        prepared = self.invoke(
                            CommandEnvelope(
                                peer="plugin",
                                action="turn.prepare",
                                source="daily_skill_runtime",
                                causal_id=self._daily_turn_causal_id(
                                    "evidence-prepare",
                                    envelope.causal_id,
                                ),
                                generation=preparation.generation,
                                scope=("turn:prepare",),
                                payload=DailyTurnPreparePayload(draft),
                            ),
                            peer_id=peer_id,
                        )
                        if prepared.status not in {"accepted", "replayed"}:
                            return prepared
                        status = self._core.daily_turn_status(envelope.causal_id)
            except (AuthorityValidationError, ProtocolViolation, TypeError, ValueError):
                return Response(
                    "unavailable",
                    envelope.causal_id,
                    "daily-turn-candidate-invalid",
                )

        while status is not None and status.phase != "finalized":
            if status.phase == "evidence-finalized":
                if (
                    status.draft is not None
                    and self._core.recording_excluded_owner_correction_handoff_required(
                        envelope.causal_id,
                        status.draft,
                    )
                ):
                    return Response(
                        "unavailable",
                        envelope.causal_id,
                        "owner-correction-handoff-required",
                    )
                try:
                    with self._core.daily_turn_runtime_preparation(
                        envelope.causal_id,
                        committed_evidence_stage=status.draft,
                    ) as preparation:
                        if type(runtime) is not DailySkillRuntime or status.draft is None:
                            return Response(
                                "unavailable",
                                envelope.causal_id,
                                "daily-turn-runtime-unavailable",
                            )
                        if preparation.reason_code == "daily-turn-busy":
                            return Response(
                                "unavailable",
                                envelope.causal_id,
                                preparation.reason_code,
                            )
                        if not preparation.ready:
                            status = self._core.daily_turn_status(
                                envelope.causal_id
                            )
                            continue
                        complete_draft = runtime.complete(
                            envelope,
                            self._core.daily_turn_post_stage_state(
                                envelope.causal_id
                            ),
                            status.draft,
                        )
                        prepared = self.invoke(
                            CommandEnvelope(
                                peer="plugin",
                                action="turn.prepare",
                                source="daily_skill_runtime",
                                causal_id=self._daily_turn_causal_id(
                                    "complete-prepare",
                                    envelope.causal_id,
                                ),
                                generation=preparation.generation,
                                scope=("turn:prepare",),
                                payload=DailyTurnPreparePayload(complete_draft),
                            ),
                            peer_id=peer_id,
                        )
                        if prepared.status not in {"accepted", "replayed"}:
                            return prepared
                        status = self._core.daily_turn_status(
                            envelope.causal_id
                        )
                except (
                    AuthorityValidationError,
                    ProtocolViolation,
                    TypeError,
                    ValueError,
                ):
                    return Response(
                        "unavailable",
                        envelope.causal_id,
                        "daily-turn-candidate-invalid",
                    )
                continue
            if status.phase in {"prepared", "unknown"}:
                transitioned = self.invoke(
                    self._daily_transition_command(status, "state.commit"),
                    peer_id=peer_id,
                )
            elif status.phase == "committed":
                transitioned = self.invoke(
                    self._daily_transition_command(status, "state.finalize"),
                    peer_id=peer_id,
                )
            else:
                return Response(
                    "unavailable",
                    envelope.causal_id,
                    "daily-turn-state-unavailable",
                )
            if transitioned.status not in {"accepted", "replayed"}:
                return transitioned
            status = self._core.daily_turn_status(envelope.causal_id)
        if status is None or status.phase != "finalized":
            return Response("unavailable", envelope.causal_id, "daily-turn-state-unavailable")
        try:
            result = self._core.daily_turn_result(envelope.causal_id)
        except AuthorityValidationError as exc:
            return Response(
                "unavailable",
                envelope.causal_id,
                str(exc) or "daily-turn-result-unavailable",
            )
        if result is None:
            # A later bounded historical summary may intentionally remove the
            # old reply/evidence projection.  Exact causal replay still proves
            # that the turn finalized, but must not reconstruct deleted health
            # detail from hashes or model output.
            return Response(
                "accepted",
                envelope.causal_id,
                "daily-turn-result-redacted",
            )
        return Response(
            "accepted",
            envelope.causal_id,
            "daily-turn-finalized",
            DailyTurnMeta(result),
        )

    @staticmethod
    def _daily_turn_causal_id(stage: str, source_causal_id: str) -> str:
        digest = stable_digest({"stage": stage, "source_causal_id": source_causal_id})
        return f"daily-turn-{stage}:" + digest.removeprefix("sha256:")

    @staticmethod
    def _daily_transition_command(status: DailyTurnStatus, action: str) -> CommandEnvelope:
        if action not in {"state.commit", "state.finalize"}:
            raise ProtocolViolation("invalid daily transition action")
        if status.draft is None or status.phase == "evidence-finalized":
            raise ProtocolViolation("daily transition draft unavailable")
        suffix = "commit" if action == "state.commit" else "finalize"
        turn_stage = (
            "evidence" if status.draft.turn_kind == "evidence-stage" else "complete"
        )
        authority = status.prepared_authority
        generation = authority.generation if action == "state.commit" else authority.generation + 1
        return CommandEnvelope(
            peer="plugin",
            action=action,
            source="daily_skill_runtime",
            causal_id=HealthPlugin._daily_turn_causal_id(
                f"{turn_stage}-{suffix}",
                status.draft.source_causal_id,
            ),
            generation=generation,
            scope=(f"state:{suffix}",),
            payload=StateCommitPayload(
                status.draft.record_id,
                status.draft.revision_digest,
                status.draft.transition_id,
                authority.writer_fence,
            ),
        )

    def daily_state(self, *, peer_id: str) -> DailyHealthState:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            raise AuthorityValidationError("daily-state-unavailable")
        return self._core.daily_state()

    def prepare_owner_mutation(
        self,
        request: OwnerMutationRequest,
        *,
        peer_id: str,
        candidate: NonDiagnosticCandidate | None = None,
    ) -> Response:
        """Submit one settings/correction draft to the sole owner writer."""

        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if type(request) is not OwnerMutationRequest:
            return Response("rejected", reason_code="invalid-owner-mutation")

        def finish(response: Response) -> Response:
            daily = request.daily_turn_draft
            if (
                type(daily) is DailyTurnDraft
                and response.status not in {"accepted", "replayed"}
            ):
                try:
                    status = self._core.owner_mutation_status(
                        request.context.command_id
                    )
                except AuthorityValidationError:
                    status = None
                if status is None or status.phase == "finalized":
                    self._core.discard_recording_plaintext(
                        daily.source_causal_id
                    )
            return response

        if not self._core.admission_policy_matches(self._admission_policy):
            return finish(
                Response(
                    "unavailable",
                    reason_code="admission-policy-mismatch",
                )
            )
        try:
            command = CommandEnvelope(
                peer="plugin",
                action="owner.prepare",
                source="owner_authority",
                causal_id=request.context.causal_id,
                generation=request.context.current_head_generation,
                scope=("owner:prepare",),
                payload=OwnerPreparePayload(request, candidate),
            )
        except ProtocolViolation as exc:
            return finish(Response("rejected", reason_code=str(exc)))
        return finish(self.invoke(command, peer_id=peer_id))

    def owner_mutation_status(
        self,
        command_id: str,
        *,
        peer_id: str,
    ) -> OwnerMutationStatus | None:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            raise AuthorityValidationError("owner-mutation-state-unavailable")
        parsed_command_id = validate_opaque_text(
            command_id,
            "owner mutation command identifier",
        )
        status = self._core.owner_mutation_status(parsed_command_id)
        if status is not None and type(status) is not OwnerMutationStatus:
            raise AuthorityValidationError("owner-mutation-state-unavailable")
        return status

    def commit_owner_mutation(
        self,
        command_id: str,
        *,
        peer_id: str,
    ) -> Response:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            return Response("unavailable", reason_code="admission-policy-mismatch")
        try:
            status = self.owner_mutation_status(command_id, peer_id=peer_id)
        except AuthorityValidationError:
            return Response(
                "unavailable",
                reason_code="owner-mutation-state-unavailable",
            )
        if status is None or status.phase not in {
            "prepared",
            "unknown",
            "committed",
            "finalized",
        }:
            return Response("rejected", reason_code="owner-mutation-not-prepared")
        if status.phase in {"committed", "finalized"}:
            authority = status.committed_authority
            if type(authority) is not AuthoritySnapshot:
                return Response(
                    "unavailable",
                    reason_code="owner-mutation-state-unavailable",
                )
            return Response(
                "accepted",
                self._owner_mutation_causal_id("commit", status.command_id),
                "current-head-advanced",
                CommitMeta(authority.generation, authority.writer_fence),
            )
        try:
            command = self._owner_mutation_transition_command(
                status,
                "state.commit",
            )
        except ProtocolViolation:
            return Response(
                "unavailable",
                reason_code="owner-mutation-state-unavailable",
            )
        return self.invoke(command, peer_id=peer_id)

    def finalize_owner_mutation(
        self,
        command_id: str,
        *,
        peer_id: str,
    ) -> Response:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            return Response("unavailable", reason_code="admission-policy-mismatch")
        try:
            status = self.owner_mutation_status(command_id, peer_id=peer_id)
        except AuthorityValidationError:
            return Response(
                "unavailable",
                reason_code="owner-mutation-state-unavailable",
            )
        if status is None or status.phase not in {"committed", "finalized"}:
            return Response("rejected", reason_code="owner-mutation-not-committed")
        if status.phase == "finalized":
            return Response(
                "accepted",
                self._owner_mutation_causal_id("finalize", status.command_id),
                "revision-finalized",
            )
        try:
            command = self._owner_mutation_transition_command(
                status,
                "state.finalize",
            )
        except ProtocolViolation:
            return Response(
                "unavailable",
                reason_code="owner-mutation-state-unavailable",
            )
        return self.invoke(command, peer_id=peer_id)

    @staticmethod
    def _owner_mutation_transition_command(
        status: OwnerMutationStatus,
        action: str,
    ) -> CommandEnvelope:
        if type(status) is not OwnerMutationStatus or action not in {
            "state.commit",
            "state.finalize",
        }:
            raise ProtocolViolation("owner mutation transition unavailable")
        authority = status.prepared_authority
        suffix = "commit" if action == "state.commit" else "finalize"
        generation = (
            authority.generation
            if action == "state.commit"
            else authority.generation + 1
        )
        return CommandEnvelope(
            peer="plugin",
            action=action,
            source="owner_authority",
            causal_id=HealthPlugin._owner_mutation_causal_id(
                suffix,
                status.command_id,
            ),
            generation=generation,
            scope=(f"state:{suffix}",),
            payload=StateCommitPayload(
                record_id=status.record_id,
                revision_digest=status.revision_digest,
                transition_id=status.transition_id,
                writer_fence=authority.writer_fence,
            ),
        )

    @staticmethod
    def _owner_mutation_causal_id(stage: str, command_id: str) -> str:
        if stage not in {"commit", "finalize"}:
            raise ProtocolViolation("invalid owner mutation stage")
        parsed_command_id = validate_opaque_text(
            command_id,
            "owner mutation command identifier",
        )
        digest = stable_digest(
            {"stage": stage, "command_id": parsed_command_id}
        )
        return f"owner-mutation-{stage}:" + digest.removeprefix("sha256:")

    def owner_settings_state(self, *, peer_id: str) -> OwnerSettingsState:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            raise AuthorityValidationError("owner-settings-state-unavailable")
        state = self._core.owner_settings_state()
        if type(state) is not OwnerSettingsState:
            raise AuthorityValidationError("owner-settings-state-unavailable")
        return state

    def managed_owner_settings_read(
        self,
        *,
        peer_id: str,
    ) -> dict[str, object]:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            raise AuthorityValidationError("owner-settings-read-unavailable")
        view = self._core.managed_owner_settings_read()
        if type(view) is not dict:
            raise AuthorityValidationError("owner-settings-read-unavailable")
        return view

    def _require_ticket115_peer(self, peer_id: str) -> None:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            raise AuthorityValidationError("ticket115-entry-unavailable")

    def managed_ticket115_read(self, *, peer_id: str) -> dict[str, object]:
        """Return the bounded Ticket 115 managed-read wire projection."""

        self._require_ticket115_peer(peer_id)
        view = self._core.managed_ticket115_read()
        if type(view) is not dict:
            raise AuthorityValidationError("ticket115-read-unavailable")
        return view

    def managed_safety_diagnosis_read(
        self,
        *,
        peer_id: str,
    ) -> dict[str, object]:
        """Return the bounded Ticket 116 safety/diagnosis projection."""

        self._require_ticket115_peer(peer_id)
        view = self._core.managed_safety_diagnosis_read()
        if type(view) is not dict:
            raise AuthorityValidationError("safety-diagnosis-read-unavailable")
        return view

    def health_operation(
        self,
        action: str,
        payload: Mapping[str, object],
        *,
        context: Mapping[str, object] | None = None,
        peer_id: str,
    ) -> dict[str, object]:
        """Forward one explicitly authorized semantic command to health-core."""

        self._require_ticket115_peer(peer_id)
        action = validate_opaque_text(action, "health operation")
        if type(payload) is not dict:
            raise ProtocolViolation("invalid health operation payload")
        fields = _wire_fields(
            context,
            frozenset({"source", "causal_id", "generation", "scope"}),
        )
        scope = fields["scope"]
        if type(scope) is not list:
            raise ProtocolViolation("invalid health command scope")
        try:
            command = TrustedHealthCommand(
                action=action,
                source=fields["source"],  # type: ignore[arg-type]
                causal_id=fields["causal_id"],  # type: ignore[arg-type]
                generation=fields["generation"],  # type: ignore[arg-type]
                scope=tuple(scope),
                payload=payload,
            )
        except HealthCommandContractViolation as exc:
            raise ProtocolViolation("invalid trusted health command") from exc
        return self._core.execute_trusted_health_command(command)

    def controlled_effect(
        self,
        action: str,
        payload: Mapping[str, object],
        *,
        grant: EffectExecutionGrant | None = None,
        transport: OwnerDeliveryWireAdapter | None = None,
        peer_id: str,
    ) -> dict[str, object]:
        """Run one controlled owner-delivery effect through stable wire seams."""

        self._require_ticket115_peer(peer_id)
        action = validate_opaque_text(action, "controlled effect action")
        if type(payload) is not dict:
            raise ProtocolViolation("invalid controlled effect payload")
        if action == "owner-delivery.issue":
            fields = _wire_fields(payload, frozenset({"intent_id"}))
            return {
                "response": self._core.issue_owner_delivery_effect(
                    fields["intent_id"]  # type: ignore[arg-type]
                ).to_wire()
            }
        if action == "owner-delivery.prepare":
            fields = _wire_fields(
                payload,
                frozenset({"intent_id", "attempted_at_utc"}),
                frozenset({"lease_seconds"}),
            )
            return {
                "send_intent": self._core.prepare_owner_delivery_attempt(
                    fields["intent_id"],  # type: ignore[arg-type]
                    attempted_at_utc=fields["attempted_at_utc"],  # type: ignore[arg-type]
                    lease_seconds=fields.get("lease_seconds", 300),  # type: ignore[arg-type]
                ).to_wire()
            }
        if action == "owner-delivery.execute":
            fields = _wire_fields(
                payload,
                frozenset({"intent_id", "attempted_at_utc"}),
                frozenset({"observed_at_utc"}),
            )
            if type(grant) is not EffectExecutionGrant or transport is None:
                raise ProtocolViolation("controlled effect grant and transport required")
            raw_observed_at_utc = fields.get(
                "observed_at_utc",
                fields["attempted_at_utc"],
            )
            try:
                observed_at_utc = validate_owner_delivery_observed_at(
                    raw_observed_at_utc
                )
            except DeliveryContractViolation as exc:
                raise ProtocolViolation(
                    "invalid owner delivery observation time"
                ) from exc
            send_intent = self._core.authorize_owner_delivery_attempt(
                fields["intent_id"],  # type: ignore[arg-type]
                grant,
                attempted_at_utc=fields["attempted_at_utc"],  # type: ignore[arg-type]
            )
            if type(send_intent) is not OwnerDeliverySendIntent:
                raise AuthorityValidationError("owner-delivery-authorization-required")
            try:
                send = getattr(transport, "send")
                if not callable(send):
                    raise TypeError("owner delivery transport send is not callable")
                supplied = send(send_intent.to_wire())
                transport_result = OwnerDeliveryTransportResult.from_wire(supplied)
                completion = OwnerDeliveryCompletion(
                    intent_id=send_intent.intent_id,
                    attempt_ref=send_intent.attempt_ref,
                    status=transport_result.status,
                    result_ref=transport_result.result_ref,
                    evidence_ref=transport_result.evidence_ref,
                    observed_at_utc=observed_at_utc,  # type: ignore[arg-type]
                )
            except Exception:
                completion = _unknown_owner_delivery_completion(
                    send_intent,
                    observed_at_utc=observed_at_utc,  # type: ignore[arg-type]
                )
            result = self._core.complete_owner_delivery_attempt(
                completion,
                grant,
            )
            return {
                "transport_result": result.transport_result.to_wire(),
                "effect_response": result.effect_response.to_wire(),
                "delivery_transition": _delivery_transition_wire(
                    result.delivery_transition
                ),
            }
        if action == "contact-alert.execute":
            try:
                fields = _wire_fields(
                    payload,
                    frozenset(
                        {"intent_id", "attempted_at_utc", "observed_at_utc"}
                    ),
                )
            except ProtocolViolation:
                if type(grant) is EffectExecutionGrant:
                    self._core.reject_malformed_ticket116_contact_claim(grant)
                raise
            if type(grant) is not EffectExecutionGrant or transport is None:
                raise ProtocolViolation(
                    "controlled effect grant and transport required"
                )
            return self._core.execute_ticket116_contact_alert(
                fields["intent_id"],  # type: ignore[arg-type]
                attempted_at_utc=fields["attempted_at_utc"],  # type: ignore[arg-type]
                observed_at_utc=fields["observed_at_utc"],  # type: ignore[arg-type]
                grant=grant,
                transport=transport,
            )
        raise ProtocolViolation("unsupported Ticket 115 controlled effect")

    def business_status(self, *, peer_id: str) -> BusinessStatusResult:
        """Expose only the projected tri-state, never raw capability facts."""

        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            raise AuthorityValidationError("business-status-unavailable")
        result = self._core.business_status()
        if type(result) is not BusinessStatusResult:
            raise AuthorityValidationError("business-status-unavailable")
        return result

    def managed_rights_read_current(
        self,
        *,
        peer_id: str,
    ) -> tuple[ManagedObject, ...]:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            raise AuthorityValidationError("managed-rights-read-unavailable")
        return self._core.managed_rights_read_current()

    def managed_correction_draft(
        self,
        *,
        target_ref: ManagedObjectReference,
        correction_id: str,
        reason: str,
        corrected_at_utc: str,
        replacement_claim: AtomicEvidenceClaim,
        correction_source_refs: tuple[str, ...],
        affected_object_refs: tuple[str, ...],
        disposition_requests: tuple[str, ...],
        peer_id: str,
    ) -> PendingCorrectionDraft:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            raise AuthorityValidationError("managed-correction-draft-unavailable")
        return self._core.managed_correction_draft(
            target_ref=target_ref,
            correction_id=correction_id,
            reason=reason,
            corrected_at_utc=corrected_at_utc,
            replacement_claim=replacement_claim,
            correction_source_refs=correction_source_refs,
            affected_object_refs=affected_object_refs,
            disposition_requests=disposition_requests,
        )

    def prepare_owner_correction(
        self,
        *,
        pending: PendingCorrectionDraft,
        source_message: RawWeixinMessage,
        context: OwnerMutationContext,
        expected_settings_version: int,
        requested_at_utc: str,
        peer_id: str,
        candidate: NonDiagnosticCandidate | None = None,
    ) -> Response:
        """Resume one managed correction and enter owner prepare atomically.

        The source body and complete draft remain transient until the existing
        owner prepare path accepts them.  The durable Ticket 112 daily row then
        becomes the sole prepared health-body aggregate, while the owner row
        retains only its body-free recovery reference.
        """

        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if (
            type(pending) is not PendingCorrectionDraft
            or type(source_message) is not RawWeixinMessage
            or type(context) is not OwnerMutationContext
            or pending.revision.source_refs
            != (f"source:{source_message.causal_id}",)
        ):
            return Response(
                "rejected",
                getattr(context, "causal_id", None),
                "invalid-owner-correction-handoff",
            )
        if not self._core.admission_policy_matches(self._admission_policy):
            return Response(
                "unavailable",
                context.causal_id,
                "admission-policy-mismatch",
            )
        try:
            envelope = materialize_source(source_message)
        except (AuthorityValidationError, TypeError, ValueError):
            return Response(
                "rejected",
                context.causal_id,
                "invalid-weixin-source",
            )
        router = self._coarse_router
        if type(router) is not CoarseMessageRouter:
            return Response(
                "unavailable",
                context.causal_id,
                "daily-routing-unavailable",
            )
        try:
            classification = router.classify(
                envelope.body,
                envelope.requested_capability,
            )
        except (AuthorityValidationError, TypeError, ValueError):
            return Response(
                "rejected",
                context.causal_id,
                "invalid-weixin-source",
            )
        if classification != "health":
            return Response(
                "rejected",
                context.causal_id,
                "owner-correction-health-source-required",
            )
        try:
            handoff = self._run_daily_turn(
                envelope,
                generation=source_message.generation,
                peer_id=peer_id,
            )
            if handoff.reason_code != "owner-correction-handoff-required":
                return handoff
            status = self._core.daily_turn_status(envelope.causal_id)
            runtime = self._daily_skill_runtime
            if (
                status is None
                or status.phase != "evidence-finalized"
                or type(status.draft) is not DailyTurnDraft
                or status.draft.steward_plan.evidence_maintenance_requests
                != (pending.maintenance_request,)
                or type(runtime) is not DailySkillRuntime
            ):
                return Response(
                    "rejected",
                    context.causal_id,
                    "owner-correction-handoff-mismatch",
                )
            with self._core.daily_turn_runtime_preparation(
                envelope.causal_id,
                committed_evidence_stage=status.draft,
            ) as preparation:
                if preparation.reason_code is not None:
                    return Response(
                        "unavailable",
                        context.causal_id,
                        preparation.reason_code,
                    )
                complete = runtime.complete(
                    envelope,
                    self._core.daily_turn_post_stage_state(
                        envelope.causal_id
                    ),
                    status.draft,
                )
            request = OwnerMutationRequest.form(
                context=context,
                expected_settings_version=expected_settings_version,
                requested_at_utc=requested_at_utc,
                pending_correction=pending,
                daily_turn_draft=complete,
            )
            return self.prepare_owner_mutation(
                request,
                peer_id=peer_id,
                candidate=candidate,
            )
        except (
            AuthorityValidationError,
            ProtocolViolation,
            TypeError,
            ValueError,
        ):
            return Response(
                "unavailable",
                context.causal_id,
                "daily-turn-candidate-invalid",
            )
        finally:
            self._core.release_recording_plaintext_if_unowned(
                envelope.causal_id
            )

    def managed_rights_export(
        self,
        *,
        requested_refs: tuple[ManagedObjectReference, ...],
        snapshot_id: str,
        created_at_utc: str,
        peer_id: str,
    ) -> ManagedExport:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            raise AuthorityValidationError("managed-rights-export-unavailable")
        return self._core.managed_rights_export(
            requested_refs=requested_refs,
            snapshot_id=snapshot_id,
            created_at_utc=created_at_utc,
        )

    def source_envelope(self, causal_id: str, *, peer_id: str) -> SourceEnvelope | None:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            return None
        return self._core.source_envelope(causal_id)

    def source_receipt(self, causal_id: str, *, peer_id: str) -> SourceReceipt | None:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            return None
        return self._core.source_receipt(causal_id)

    def form_initialization_disclosure(
        self,
        initialization: OwnerInitialization,
        *,
        peer_id: str,
    ) -> InitializationDisclosure:
        """Run the approved health-init disclosure before owner confirmation."""

        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if type(initialization) is not OwnerInitialization:
            raise AuthorityValidationError("invalid owner initialization")
        policy = self._admission_policy
        if (
            type(policy) is not AdmissionPolicy
            or not self._core.admission_policy_matches(policy)
        ):
            raise AuthorityValidationError("initialization-configuration-mismatch")
        replay, generation = self._core.initialization_disclosure_replay(
            initialization,
            policy,
        )
        if replay is not None:
            return replay
        runtime = self._health_init_runtime
        if type(runtime) is not HealthInitRuntime:
            raise AuthorityValidationError("health-init-runtime-unavailable")
        disclosure = runtime.form_disclosure(initialization)
        response = self.invoke(
            CommandEnvelope(
                peer="plugin",
                action="initialization.disclose",
                source="health_init_runtime",
                causal_id=self._initialization_causal_id(
                    "disclose",
                    initialization.workflow_id,
                ),
                generation=generation,
                scope=("initialization:disclose",),
                payload=InitializationDisclosurePayload(
                    initialization,
                    disclosure,
                    policy,
                ),
            ),
            peer_id=peer_id,
        )
        if response.status != "accepted":
            raise AuthorityValidationError(
                response.reason_code or "initialization-disclosure-unavailable"
            )
        return disclosure

    def prepare_initialization(
        self,
        initialization: OwnerInitialization,
        *,
        peer_id: str,
    ) -> Response:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if type(initialization) is not OwnerInitialization:
            return Response("rejected", reason_code="invalid-owner-initialization")
        if not self._core.admission_policy_matches(self._admission_policy):
            return Response(
                "unavailable",
                reason_code="admission-policy-mismatch",
            )
        reason = initialization.incomplete_reason
        if reason is not None:
            return Response("rejected", reason_code=reason)
        try:
            durable_replay = self._core.initialization_prepare_replay(initialization)
        except AuthorityValidationError as exc:
            reason_code = str(exc)
            if reason_code in {
                "health-init workflow conflict",
                "initialization already exists",
            }:
                return Response("rejected", reason_code=reason_code)
            return Response(
                "unavailable",
                reason_code="initialization-state-unavailable",
            )
        if durable_replay is not None:
            proof, generation = durable_replay
        else:
            source = self._core.source_envelope(initialization.admission_causal_id)
            if source is None:
                return Response(
                    "rejected",
                    reason_code="initialization-source-required",
                )
            try:
                consent = OwnerConsentEvidence.from_message_body(source.body)
            except AuthorityValidationError:
                consent = None
            try:
                evidence_asset = (
                    None
                    if consent is None
                    else HealthInitAsset(
                        canonical_name=consent.disclosure.skill_proof.skill_use.canonical_name,
                        version=consent.disclosure.skill_proof.skill_use.version,
                        asset_digest=consent.disclosure.skill_proof.skill_use.asset_digest,
                        disclosure_version=(
                            consent.disclosure.skill_proof.skill_use.disclosure_version
                        ),
                    )
                )
            except AuthorityValidationError:
                evidence_asset = None
            if (
                consent is None
                or evidence_asset is None
                or not consent.matches(initialization, evidence_asset)
            ):
                return Response(
                    "rejected",
                    reason_code="owner-consent-evidence-required",
                )
            proof = consent.disclosure.skill_proof
            generation = source.generation
        command = CommandEnvelope(
            peer="plugin",
            action="initialization.prepare",
            source="health_weixin",
            causal_id=self._initialization_causal_id(
                "prepare",
                initialization.workflow_id,
            ),
            generation=generation,
            scope=("initialization:prepare",),
            payload=InitializationPreparePayload(initialization, proof),
        )
        return self.invoke(command, peer_id=peer_id)

    def initialization_status(self, *, peer_id: str) -> InitializationProjection:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            return InitializationProjection.cannot_confirm()
        return self._core.initialization_status()

    def commit_initialization(self, *, peer_id: str) -> Response:
        if not self._core.admission_policy_matches(self._admission_policy):
            return Response("unavailable", reason_code="admission-policy-mismatch")
        status = self.initialization_status(peer_id=peer_id)
        if status.phase not in {"prepared", "unknown", "committed", "enabled"}:
            return Response("rejected", reason_code="initialization-not-prepared")
        return self.invoke(
            self._initialization_transition_command(status, "state.commit"),
            peer_id=peer_id,
        )

    def finalize_initialization(self, *, peer_id: str) -> Response:
        if not self._core.admission_policy_matches(self._admission_policy):
            return Response("unavailable", reason_code="admission-policy-mismatch")
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
            causal_id=HealthPlugin._initialization_causal_id(
                suffix,
                skill_use.workflow_id,
            ),
            generation=generation,
            scope=(f"state:{suffix}",),
            payload=StateCommitPayload(
                record_id=status.record_id,
                revision_digest=status.revision_digest,
                transition_id=status.transition_id,
                writer_fence=authority.writer_fence,
            ),
        )

    @staticmethod
    def _initialization_causal_id(stage: str, workflow_id: str) -> str:
        digest = stable_digest({"stage": stage, "workflow_id": workflow_id})
        return f"initialization-{stage}:" + digest.removeprefix("sha256:")

    def native_cursor_directive(
        self,
        source_causal_id: str,
        *,
        peer_id: str,
    ) -> NativeCursorDirective | None:
        if type(peer_id) is not str or peer_id != "plugin":
            raise ProtocolViolation("untrusted peer")
        if not self._core.admission_policy_matches(self._admission_policy):
            return None
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
        if not self._core.admission_policy_matches(self._admission_policy):
            return Response("unavailable", reason_code="admission-policy-mismatch")
        if type(directive) is not NativeCursorDirective:
            return Response("rejected", reason_code="invalid-native-cursor-directive")
        if not self._core.native_cursor_directive_matches(directive):
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
                causal_id=self._native_cursor_result_causal_id(
                    directive.source_causal_id,
                    status,
                ),
                generation=directive.authority_generation,
                scope=("cursor:result",),
                payload=payload,
            )
        except ProtocolViolation as exc:
            return Response("rejected", reason_code=str(exc))
        return self.invoke(command, peer_id=peer_id)

    @staticmethod
    def _native_cursor_result_causal_id(source_causal_id: str, status: str) -> str:
        digest = stable_digest(
            {
                "source_causal_id": source_causal_id,
                "status": status,
            }
        )
        return "native-cursor-result:" + digest.removeprefix("sha256:")

    def probe(self, *, ordinary_hermes_status: str | None = None) -> ProbeReport:
        # The ordinary Hermes status is intentionally ignored: it is not health proof.
        del ordinary_hermes_status
        report = self._core.probe()
        if (
            report.state is ProbeState.HEALTHY
            and not self._core.admission_policy_matches(self._admission_policy)
        ):
            return ProbeReport(ProbeState.UNAVAILABLE, "admission-policy-mismatch")
        return report

    def health_writes_allowed(self) -> bool:
        return (
            self._core.admission_policy_matches(self._admission_policy)
            and self._core.health_writes_allowed()
        )

    def model_effects_allowed(self) -> bool:
        return (
            self._core.admission_policy_matches(self._admission_policy)
            and self._core.model_effects_allowed()
        )

    def outbound_effects_allowed(self) -> bool:
        return (
            self._core.admission_policy_matches(self._admission_policy)
            and self._core.outbound_effects_allowed()
        )

    def claim_effect_execution(self, intent: EffectIntent) -> EffectExecutionGrant | None:
        """Return the non-durable completion grant before an adapter may act."""

        if not self._core.admission_policy_matches(self._admission_policy):
            return None
        return self._core.claim_effect_execution(intent)

    def execute_strict_health_model(
        self,
        llm: StrictHealthLLM,
        request: StrictModelRequest,
        source_causal_id: str,
        grant: EffectExecutionGrant | None,
        adapter: StrictModelAdapter,
    ) -> StrictModelOutcome:
        """Execute one exact request through the core-owned model boundary."""

        if not self._core.admission_policy_matches(self._admission_policy):
            return StrictModelOutcome(
                disposition="failed-closed",
                model_effect="not-started",
                reason_code="model-effect-authorization-required",
                candidate=None,
            )
        return self._core.execute_strict_health_model(
            llm,
            request,
            source_causal_id,
            grant,
            adapter,
        )

    def model_effect_report(self, effect_id: str) -> ModelEffectReport | None:
        """Expose only the core-verified, content-free terminal model report."""

        if not self._core.admission_policy_matches(self._admission_policy):
            return None
        return self._core.model_effect_report(effect_id)

    def model_answer_recovery_status(self, source_causal_id: str) -> str:
        """Return the core-owned retry/freeze projection for one daily source."""

        if not self._core.admission_policy_matches(self._admission_policy):
            return "unavailable"
        return self._core.model_answer_recovery_status(source_causal_id)

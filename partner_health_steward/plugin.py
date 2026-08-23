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
from .authority import (
    AuthorityValidationError,
    EffectExecutionGrant,
    EffectIntent,
    validate_opaque_text,
)
from .contract import (
    CommandEnvelope,
    DailySourceMeta,
    DailyTurnMeta,
    DailyTurnPreparePayload,
    InboundAdmitPayload,
    InitializationDisclosurePayload,
    InitializationPreparePayload,
    NativeCursorResultPayload,
    ProtocolViolation,
    Response,
    StateCommitPayload,
    decode_frame,
    encode_raw_response,
)
from .coordination import (
    CoarseMessageRouter,
    DAILY_HEALTH_SKILL_NAMES,
    DailyHealthState,
    DailySkillRuntime,
)
from .core import DailyTurnStatus, HealthCore
from .initialization import (
    HealthInitAsset,
    HealthInitRuntime,
    InitializationDisclosure,
    InitializationProjection,
    OwnerConsentEvidence,
    OwnerInitialization,
    stable_digest,
)
from .probe import ProbeReport, ProbeState


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
        if initialization.phase == "uninitialized":
            report = self._core.probe()
            if report.state is not ProbeState.HEALTHY:
                return Response("unavailable", causal_id, report.reason_code)
        try:
            envelope = materialize_source(message)
            if initialization.phase == "enabled":
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
                return self._run_daily_turn(
                    envelope,
                    generation=message.generation,
                    peer_id=peer_id,
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
            if type(runtime) is not DailySkillRuntime:
                return Response(
                    "unavailable",
                    envelope.causal_id,
                    "daily-turn-runtime-unavailable",
                )
            try:
                with self._core.daily_turn_runtime_preparation(
                    envelope.causal_id
                ) as preparation:
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
                if type(runtime) is not DailySkillRuntime or status.draft is None:
                    return Response(
                        "unavailable",
                        envelope.causal_id,
                        "daily-turn-runtime-unavailable",
                    )
                try:
                    with self._core.daily_turn_runtime_preparation(
                        envelope.causal_id,
                        committed_evidence_stage=status.draft,
                    ) as preparation:
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

"""Short Core RPCs around one observed production model attempt per stage."""
from __future__ import annotations

import asyncio
import uuid

from .bounded_transfer import (
    canonical_bytes, decode_canonical, decode_chunk,
    descriptor_for, encode_chunk, validate_bytes, validate_descriptor,
)
from .model_adapter import (
    BoundResponsesTransport, NonDiagnosticBudgetInputMeasurementStrategy,
    ProductionModelAdapter,
)
from .model_contract import (
    FirstHopRoute, ModelTransportResult, NonDiagnosticOperationalBudget,
    StrictModelRequest,
)


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError("invalid non-diagnostic Core response")
    return value


def _text(value):
    if type(value) is not str or not value or len(value.encode("utf-8")) > 16384:
        raise ValueError("invalid non-diagnostic metadata")
    return value


class LiveNonDiagnosticModelBridge:
    """The Plugin holds credentials; the Core remains the result authority."""

    def __init__(self, core_port, adapter):
        if (not callable(getattr(core_port, "request", None))
                or type(adapter) is not ProductionModelAdapter):
            raise ValueError("invalid non-diagnostic bridge dependencies")
        self._port, self._adapter = core_port, adapter
        self._lock = asyncio.Lock()

    async def _rpc(self, kind, operation, payload):
        identity = "nondiagnostic-rpc:" + uuid.uuid4().hex
        selector = "projection" if kind == "managed-read" else "operation"
        response = await asyncio.to_thread(self._port.request, kind, {
            "interface": "health-entry-v1", selector: operation, "payload": payload,
        }, request_id=identity)
        _exact(response, {"protocol_version", "kind", "request_id", "status", "payload"})
        if (response["protocol_version"] != 1 or response["kind"] != kind
                or response["request_id"] != identity or response["status"] != "accepted"
                or type(response["payload"]) is not dict):
            raise ValueError("non-diagnostic Core result unconfirmed")
        return response["payload"]

    async def _advance(self, source):
        value = await self._rpc("command", "governed-advance", {"source_causal_id": source})
        _exact(value, {"response", "next_stage", "model_use_disclosure", "delivery_refs"})
        if value["next_stage"] not in {None, "intake", "answer"} or type(value["delivery_refs"]) is not list:
            raise ValueError("invalid non-diagnostic stage projection")
        return value

    @staticmethod
    def _grant(prepared):
        intent, grant = prepared["intent"], prepared["grant"]
        _exact(intent, {"effect_id", "intent_digest", "effect_kind", "authority"})
        _exact(intent["authority"], {"source", "generation", "writer_fence"})
        _exact(grant, {"session_id", "lease_id", "effect_id", "intent_digest", "generation", "writer_fence"})
        if (intent["effect_kind"] != "model-work" or intent["authority"]["source"] != "core"
                or any(grant[field] != intent[field] for field in ("effect_id", "intent_digest"))
                or any(grant[field] != intent["authority"][field] for field in ("generation", "writer_fence"))):
            raise ValueError("non-diagnostic grant mismatch")
        return grant

    async def _abort(self, source, stage, grant, attempt, reason):
        try:
            await self._rpc("controlled-effect", "nondiagnostic-abort", {
                "source_causal_id": source, "stage": stage, "grant": grant,
                "attempt_ref": attempt, "reason_code": reason,
            })
        except Exception:
            # A failed callback is never permission to repeat an attempt.
            pass

    async def _stage(self, source, stage):
        prepared = await self._rpc("controlled-effect", "nondiagnostic-prepare", {
            "source_causal_id": source, "stage": stage,
        })
        _exact(prepared, {"stage", "state", "request_transfer", "intent", "grant"})
        if prepared["stage"] != stage:
            raise ValueError("non-diagnostic stage mismatch")
        if prepared["grant"] is None or prepared["intent"] is None or prepared["request_transfer"] is None:
            return
        grant = self._grant(prepared)
        attempt, observed = None, None
        buffer = bytearray()
        reason = "request-transfer-aborted"
        complete_called = False
        try:
            descriptor = validate_descriptor(prepared["request_transfer"])
            for index in range(descriptor["chunk_count"]):
                item = await self._rpc("controlled-effect", "nondiagnostic-request-chunk", {
                    "source_causal_id": source, "stage": stage, "grant": grant, "index": index,
                })
                _exact(item, {"request_transfer", "index", "bytes_b64", "next_index"})
                if (item["request_transfer"] != descriptor or item["index"] != index
                        or item["next_index"] != (index + 1 if index + 1 < descriptor["chunk_count"] else None)):
                    raise ValueError("non-diagnostic request transfer changed")
                buffer.extend(decode_chunk(item["bytes_b64"], index=index, descriptor=descriptor))
            wire = decode_canonical(validate_bytes(bytes(buffer), descriptor))
            request = StrictModelRequest.from_wire(wire)
            if StrictModelRequest.to_wire(request) != wire:
                raise ValueError("non-diagnostic request codec changed")
            from .model_adapter import (
                NONDIAGNOSTIC_INTAKE_SCHEMA_NAME, NONDIAGNOSTIC_INTAKE_SCHEMA_DIGEST,
                NONDIAGNOSTIC_OPERATION_SCHEMA_NAME, NONDIAGNOSTIC_OPERATION_SCHEMA_DIGEST,
            )
            expected = ((NONDIAGNOSTIC_INTAKE_SCHEMA_NAME, NONDIAGNOSTIC_INTAKE_SCHEMA_DIGEST)
                        if stage == "intake" else
                        (NONDIAGNOSTIC_OPERATION_SCHEMA_NAME, NONDIAGNOSTIC_OPERATION_SCHEMA_DIGEST))
            if (request.strict_schema_name, request.strict_schema_digest) != expected:
                raise ValueError("non-diagnostic request schema stage changed")
            started = await self._rpc("controlled-effect", "nondiagnostic-start", {
                "source_causal_id": source, "stage": stage, "grant": grant,
                "request_receipt": descriptor,
            })
            _exact(started, {"stage", "state", "request_digest", "attempt_ref"})
            if started["stage"] != stage:
                raise ValueError("non-diagnostic start stage changed")
            if started["state"] != "attempted" or started["attempt_ref"] is None:
                return
            attempt = _text(started["attempt_ref"])
            if started["request_digest"] != request.digest:
                raise ValueError("non-diagnostic started request changed")
            buffer.clear()
            reason = "adapter-precall-unconfirmed"
            observed = await asyncio.to_thread(ProductionModelAdapter.execute, self._adapter, wire)
            if type(observed) is not ModelTransportResult:
                raise ValueError("non-diagnostic typed result missing")
            observed = ModelTransportResult.canonical_copy(observed)
            reason = "result-transfer-aborted"
            result_bytes = canonical_bytes(ModelTransportResult.to_wire(observed))
            result_descriptor = descriptor_for(result_bytes)
            for index in range(result_descriptor["chunk_count"]):
                transferred = await self._rpc("controlled-effect", "nondiagnostic-result-chunk", {
                    "source_causal_id": source, "stage": stage, "grant": grant,
                    "attempt_ref": attempt, "result_transfer": result_descriptor,
                    "index": index, "bytes_b64": encode_chunk(result_bytes, index),
                })
                _exact(transferred, {"stage", "state", "next_index"})
                if (transferred["stage"] != stage
                        or transferred["next_index"] != (index + 1 if index + 1 < result_descriptor["chunk_count"] else None)):
                    raise ValueError("non-diagnostic result transfer unconfirmed")
            complete_called = True
            completed = await self._rpc("controlled-effect", "nondiagnostic-complete", {
                "source_causal_id": source, "stage": stage, "grant": grant,
                "attempt_ref": attempt, "result_receipt": result_descriptor,
            })
            _exact(completed, {"stage", "state", "reason_code"})
            if completed["stage"] != stage:
                raise ValueError("non-diagnostic completion stage changed")
        except Exception:
            if complete_called:
                # Read back the original terminal if its reply was lost. The
                # following advance consumes only the Core-observed candidate.
                await self._rpc("managed-read", "health-entry-nondiagnostic", {"source_causal_id": source})
            else:
                await self._abort(source, stage, grant, attempt, reason)
        finally:
            buffer.clear()
            observed = None

    async def advance_source(self, source_causal_id):
        source = _text(source_causal_id)
        async with self._lock:
            outcome = await self._advance(source)
            stages = set()
            while outcome["next_stage"] is not None:
                stage = outcome["next_stage"]
                if stage in stages or len(stages) >= 2:
                    return outcome
                stages.add(stage)
                await self._stage(source, stage)
                outcome = await self._advance(source)
            return outcome


def create_live_nondiagnostic_model_bridge(core_port, *, route, budget, credential_provider):
    """Build only the exact approved ND route, budget and production sender."""
    actual_route = FirstHopRoute.from_wire(route)
    actual_budget = NonDiagnosticOperationalBudget.from_wire(budget)
    if actual_budget.route != actual_route or not callable(credential_provider):
        raise ValueError("invalid non-diagnostic production binding")
    strategy = NonDiagnosticBudgetInputMeasurementStrategy(actual_budget)
    adapter = ProductionModelAdapter(actual_route, actual_budget,
        transport=BoundResponsesTransport(actual_route, credential_provider=credential_provider),
        measurement_strategy=strategy)
    return LiveNonDiagnosticModelBridge(core_port, adapter)

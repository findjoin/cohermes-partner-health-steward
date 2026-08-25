"""Synthetic delivery evidence capabilities for Ticket 115 tests only."""

from partner_health_steward.delivery import (
    DeliveryOutboxState,
    DeliveryTransition,
    OutboxIntent,
    OwnerDeliveryEngine,
    OwnerDeliveryTransportResult,
)
from partner_health_steward.ticket115_contracts import (
    DeliveryEvidenceAuthority,
    DeliveryEvidenceIssuer,
)


DELIVERY_KEYS = {
    "health-core.delivery.formed": b"ticket115-core-formed-key",
    "health-core.delivery.committed": b"ticket115-core-committed-key",
    "owner-delivery-adapter.attempted": b"ticket115-adapter-attempt-key",
    "owner-delivery-adapter.interface": b"ticket115-adapter-interface-key",
    "owner-delivery-adapter.unknown": b"ticket115-adapter-unknown-key",
    "weixin.channel.receipt": b"ticket115-weixin-receipt-key",
    "owner.admitted-event": b"ticket115-owner-event-key",
}

AUTHORITY = DeliveryEvidenceAuthority(DELIVERY_KEYS)
ISSUERS = {
    producer: DeliveryEvidenceIssuer(
        producer_contract=producer,
        allowed_layers=tuple(
            layer
            for layer, expected in DeliveryEvidenceAuthority.PRODUCER_BY_LAYER.items()
            if expected == producer
        ),
        signing_key=key,
    )
    for producer, key in DELIVERY_KEYS.items()
}


def core_and_adapter_issuers() -> tuple[DeliveryEvidenceIssuer, ...]:
    return tuple(
        ISSUERS[producer]
        for producer in (
            "health-core.delivery.formed",
            "health-core.delivery.committed",
            "owner-delivery-adapter.attempted",
            "owner-delivery-adapter.interface",
            "owner-delivery-adapter.unknown",
        )
    )


def submit(
    state: DeliveryOutboxState,
    intent: OutboxIntent,
    *,
    submitted_at_utc: str,
) -> DeliveryTransition:
    return OwnerDeliveryEngine.submit(
        state,
        intent,
        submitted_at_utc=submitted_at_utc,
        formed_issuer=ISSUERS["health-core.delivery.formed"],
        committed_issuer=ISSUERS["health-core.delivery.committed"],
    )


def mark_attempted(
    state: DeliveryOutboxState,
    intent_id: str,
    *,
    lease_id: str,
    attempt_ref: str,
    attempted_at_utc: str,
) -> DeliveryTransition:
    return OwnerDeliveryEngine.mark_attempted(
        state,
        intent_id,
        lease_id=lease_id,
        attempt_ref=attempt_ref,
        attempted_at_utc=attempted_at_utc,
        evidence=ISSUERS["owner-delivery-adapter.attempted"].issue(
            layer="attempted",
            generation=state.record(intent_id).intent.route_generation,
            replay_identity=attempt_ref,
            effect_id=state.record(intent_id).intent.effect_id,
            evidence_ref=attempt_ref,
        ),
        authority=AUTHORITY,
    )


def record_observation(
    state: DeliveryOutboxState,
    intent_id: str,
    *,
    kind: str,
    attempt_ref: str,
    result_ref: str,
    evidence_ref: str,
    observed_at_utc: str,
) -> DeliveryTransition:
    producer = (
        "owner-delivery-adapter.interface"
        if kind in {"accepted", "rejected"}
        else "owner-delivery-adapter.unknown"
        if kind == "unknown"
        else "owner.admitted-event"
        if kind == "actual-action"
        else "weixin.channel.receipt"
    )
    layer = {
        "accepted": "interface-accepted",
        "rejected": "interface-rejected",
    }.get(kind, kind)
    record = state.record(intent_id)
    evidence = ISSUERS[producer].issue(
        layer=layer,
        generation=record.intent.route_generation,
        replay_identity=result_ref,
        effect_id=record.intent.effect_id,
        evidence_ref=evidence_ref,
    )
    return OwnerDeliveryEngine.record_observation(
        state,
        intent_id,
        kind=kind,
        attempt_ref=attempt_ref,
        result_ref=result_ref,
        evidence_ref=evidence_ref,
        observed_at_utc=observed_at_utc,
        evidence=evidence,
        authority=AUTHORITY,
    )


def record_transport_result(
    state: DeliveryOutboxState,
    intent_id: str,
    *,
    attempt_ref: str,
    result: OwnerDeliveryTransportResult,
    observed_at_utc: str,
) -> DeliveryTransition:
    producer = (
        "owner-delivery-adapter.unknown"
        if result.status == "unknown"
        else "owner-delivery-adapter.interface"
    )
    record = state.record(intent_id)
    layer = {
        "accepted": "interface-accepted",
        "rejected": "interface-rejected",
        "unknown": "unknown",
    }[result.status]
    return OwnerDeliveryEngine.record_transport_result(
        state,
        intent_id,
        attempt_ref=attempt_ref,
        result=result,
        observed_at_utc=observed_at_utc,
        evidence=ISSUERS[producer].issue(
            layer=layer,
            generation=record.intent.route_generation,
            replay_identity=result.result_ref,
            effect_id=record.intent.effect_id,
            evidence_ref=result.evidence_ref,
        ),
        authority=AUTHORITY,
    )

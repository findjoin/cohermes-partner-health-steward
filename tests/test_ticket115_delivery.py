"""Ticket 115 transactional outbox and layered owner-delivery tests."""

from __future__ import annotations

import unittest

from partner_health_steward.delivery import (
    DeliveryContractViolation,
    DeliveryFact,
    DeliveryOutboxState,
    OwnerDeliveryCompletion,
    OwnerDeliveryEngine,
    OwnerDeliverySendIntent,
    OwnerDeliveryTransportResult,
    OwnerDeliveryWireAdapter,
    OwnerWeixinDestination,
)
from tests.ticket115_delivery_fixtures import (
    mark_attempted,
    record_observation,
    record_transport_result,
    submit,
)


OWNER = "owner-A"
INSTALLATION = "partner-installation"
FORMED_AT = "2026-08-24T02:00:00+00:00"
SUBMITTED_AT = "2026-08-24T02:00:01+00:00"
CLAIMED_AT = "2026-08-24T02:00:02+00:00"
ATTEMPTED_AT = "2026-08-24T02:00:03+00:00"


def _intent(
    *,
    formed_at_utc: str = FORMED_AT,
    effect_kind: str = "owner-delivery",
    effect_request_id: str = "effect:daily-review:2026-08-24",
    payload_digest: str = "sha256:" + "2" * 64,
):
    return OwnerDeliveryEngine.form_intent(
        effect_kind=effect_kind,
        owner_id=OWNER,
        installation_id=INSTALLATION,
        effect_request_id=effect_request_id,
        business_fact_ref="daily-review:2026-08-24",
        business_revision_digest="sha256:" + "1" * 64,
        source_ref="review:2026-08-24",
        recipient_ref="owner-route:weixin-private",
        route_id="health_weixin",
        route_generation=7,
        payload_ref="owner-message:daily-review:2026-08-24",
        payload_digest=payload_digest,
        formed_at_utc=formed_at_utc,
    )


def _submitted_state():
    transition = submit(
        DeliveryOutboxState.empty(OWNER, INSTALLATION),
        _intent(),
        submitted_at_utc=SUBMITTED_AT,
    )
    return transition.state, transition.intent_id


def _attempted_state():
    state, intent_id = _submitted_state()
    claimed = OwnerDeliveryEngine.claim(
        state,
        intent_id,
        holder_id="worker-A",
        lease_id="lease:delivery:1",
        acquired_at_utc=CLAIMED_AT,
        lease_seconds=30,
    )
    attempted = mark_attempted(
        claimed.state,
        intent_id,
        lease_id="lease:delivery:1",
        attempt_ref="weixin-attempt:1",
        attempted_at_utc=ATTEMPTED_AT,
    )
    return attempted.state, intent_id


class Ticket115DeliveryTests(unittest.TestCase):
    def test_legacy_scalar_delivery_evidence_round_trips_without_becoming_forgeable(
        self,
    ) -> None:
        state, _ = _attempted_state()
        legacy = state.to_wire()
        for fact in legacy["records"][0]["facts"]:
            fact["evidence_ref"] = fact.pop("evidence")["evidence_ref"]

        restored = DeliveryOutboxState.from_wire(legacy)
        restored_fact = restored.records[0].facts[0]

        self.assertTrue(restored_fact.is_legacy_storage_fact)
        self.assertEqual(restored.to_wire(), legacy)
        self.assertEqual(DeliveryOutboxState.from_wire(legacy), restored)
        with self.assertRaisesRegex(
            DeliveryContractViolation,
            "legacy delivery evidence is storage-only",
        ):
            DeliveryFact(
                kind=restored_fact.kind,
                occurred_at_utc=restored_fact.occurred_at_utc,
                proof=restored_fact.proof,
            )

    def test_plugin_transport_contract_exposes_only_owner_weixin_send_fields(self) -> None:
        destination = OwnerWeixinDestination(
            partner_id="partner-A",
            owner_sender_id=OWNER,
            conversation_id="conversation-owner-A",
            channel="weixin",
            entrypoint="health_weixin",
        )
        send_intent = OwnerDeliverySendIntent(
            intent_id="outbox:" + ("1" * 64),
            attempt_ref="owner-delivery-attempt:" + ("2" * 64),
            destination=destination,
            payload_ref="owner-message:daily-review:2026-08-24",
            payload_digest="sha256:" + ("3" * 64),
            idempotency_key="health-owner-delivery:v1:" + ("4" * 64),
        )
        completion = OwnerDeliveryCompletion(
            intent_id=send_intent.intent_id,
            attempt_ref=send_intent.attempt_ref,
            status="accepted",
            result_ref="weixin-result:accepted:1",
            evidence_ref="weixin-response:accepted:1",
            observed_at_utc="2026-08-24T02:00:04+00:00",
        )

        self.assertEqual(
            send_intent.to_wire(),
            {
                "intent_id": "outbox:" + ("1" * 64),
                "attempt_ref": "owner-delivery-attempt:" + ("2" * 64),
                "destination": {
                    "partner_id": "partner-A",
                    "owner_sender_id": OWNER,
                    "conversation_id": "conversation-owner-A",
                    "channel": "weixin",
                    "entrypoint": "health_weixin",
                },
                "payload_ref": "owner-message:daily-review:2026-08-24",
                "payload_digest": "sha256:" + ("3" * 64),
                "idempotency_key": "health-owner-delivery:v1:" + ("4" * 64),
            },
        )
        self.assertEqual(
            OwnerDeliverySendIntent.from_wire(send_intent.to_wire()),
            send_intent,
        )
        self.assertEqual(
            OwnerDeliveryCompletion.from_wire(completion.to_wire()),
            completion,
        )
        changed_conversation = OwnerWeixinDestination(
            partner_id="partner-A",
            owner_sender_id=OWNER,
            conversation_id="conversation-owner-A-v2",
        )
        self.assertTrue(destination.route_id.startswith("health-weixin-route:v1:"))
        self.assertNotEqual(destination.route_id, changed_conversation.route_id)
        self.assertNotIn("business_fact_ref", send_intent.to_wire())
        self.assertNotIn("source_ref", send_intent.to_wire())

    def test_stable_idempotency_key_is_bound_to_authoritative_intent(self) -> None:
        first = _intent()
        recovered = _intent(formed_at_utc="2026-08-24T02:05:00+00:00")
        changed_payload = _intent(payload_digest="sha256:" + "3" * 64)

        self.assertEqual(first.intent_id, recovered.intent_id)
        self.assertEqual(first.idempotency_key, recovered.idempotency_key)
        self.assertEqual(first.semantic_digest, recovered.semantic_digest)
        self.assertNotEqual(first.idempotency_key, changed_payload.idempotency_key)
        self.assertTrue(first.idempotency_key.startswith("health-owner-delivery:v1:"))
        self.assertNotIn(first.recipient_ref, first.idempotency_key)

    def test_contact_delivery_is_disabled_at_the_value_boundary(self) -> None:
        with self.assertRaisesRegex(
            DeliveryContractViolation,
            "contact delivery is not enabled",
        ):
            _intent(effect_kind="contact-delivery")

    def test_submission_atomically_binds_business_fact_and_outbox_intent(self) -> None:
        initial = DeliveryOutboxState.empty(OWNER, INSTALLATION)
        intent = _intent()

        submitted = submit(
            initial,
            intent,
            submitted_at_utc=SUBMITTED_AT,
        )
        record = submitted.state.record(submitted.intent_id)

        self.assertEqual(submitted.outcome, "submitted")
        self.assertEqual(submitted.state.version, 1)
        self.assertEqual(record.intent.business_fact_ref, "daily-review:2026-08-24")
        self.assertEqual(record.fact_kinds, ("formed", "submitted"))
        self.assertEqual(record.current_layer, "submitted")
        self.assertTrue(record.automatic_retry_allowed)

        replay = submit(
            submitted.state,
            _intent(formed_at_utc="2026-08-24T02:10:00+00:00"),
            submitted_at_utc="2026-08-24T02:10:01+00:00",
        )
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.state, submitted.state)

    def test_effect_request_identifier_cannot_be_reused_for_new_payload(self) -> None:
        submitted = submit(
            DeliveryOutboxState.empty(OWNER, INSTALLATION),
            _intent(),
            submitted_at_utc=SUBMITTED_AT,
        )

        with self.assertRaisesRegex(
            DeliveryContractViolation,
            "effect request identifier was already submitted",
        ):
            submit(
                submitted.state,
                _intent(payload_digest="sha256:" + "4" * 64),
                submitted_at_utc="2026-08-24T02:00:04+00:00",
            )

    def test_claim_is_exclusive_until_expiry_and_does_not_change_send_key(self) -> None:
        state, intent_id = _submitted_state()
        stable_key = state.record(intent_id).intent.idempotency_key
        first = OwnerDeliveryEngine.claim(
            state,
            intent_id,
            holder_id="worker-A",
            lease_id="lease:delivery:1",
            acquired_at_utc=CLAIMED_AT,
            lease_seconds=30,
        )

        with self.assertRaisesRegex(
            DeliveryContractViolation,
            "active delivery claim",
        ):
            OwnerDeliveryEngine.claim(
                first.state,
                intent_id,
                holder_id="worker-B",
                lease_id="lease:delivery:2",
                acquired_at_utc="2026-08-24T02:00:20+00:00",
            )

        recovered = OwnerDeliveryEngine.claim(
            first.state,
            intent_id,
            holder_id="worker-B",
            lease_id="lease:delivery:2",
            acquired_at_utc="2026-08-24T02:00:33+00:00",
        )
        record = recovered.state.record(intent_id)

        self.assertEqual(recovered.outcome, "claimed")
        self.assertEqual(
            record.active_lease("2026-08-24T02:00:33+00:00").holder_id,
            "worker-B",
        )
        self.assertEqual(record.intent.idempotency_key, stable_key)

    def test_accepted_delivered_and_read_are_distinct_facts(self) -> None:
        state, intent_id = _attempted_state()
        attempted = state.record(intent_id)
        self.assertEqual(
            attempted.fact_kinds,
            ("formed", "submitted", "attempted"),
        )

        accepted = record_observation(
            state,
            intent_id,
            kind="accepted",
            attempt_ref="weixin-attempt:1",
            result_ref="weixin-result:accepted:1",
            evidence_ref="weixin-response:accepted:1",
            observed_at_utc="2026-08-24T02:00:04+00:00",
        )
        accepted_record = accepted.state.record(intent_id)
        self.assertEqual(accepted_record.current_layer, "accepted")
        self.assertFalse(accepted_record.has_fact("delivered"))
        self.assertFalse(accepted_record.has_fact("read"))

        delivered = record_observation(
            accepted.state,
            intent_id,
            kind="delivered",
            attempt_ref="weixin-attempt:1",
            result_ref="weixin-result:delivered:1",
            evidence_ref="weixin-receipt:delivered:1",
            observed_at_utc="2026-08-24T02:00:05+00:00",
        )
        read = record_observation(
            delivered.state,
            intent_id,
            kind="read",
            attempt_ref="weixin-attempt:1",
            result_ref="weixin-result:read:1",
            evidence_ref="weixin-receipt:read:1",
            observed_at_utc="2026-08-24T02:00:06+00:00",
        )
        record = read.state.record(intent_id)

        self.assertEqual(
            record.fact_kinds,
            ("formed", "submitted", "attempted", "accepted", "delivered", "read"),
        )
        self.assertEqual(record.current_layer, "read")
        self.assertFalse(record.automatic_retry_allowed)

    def test_rejected_is_an_explicit_interface_fact_not_owner_delivery(self) -> None:
        state, intent_id = _attempted_state()
        rejected_result = OwnerDeliveryTransportResult(
            status="rejected",
            result_ref="weixin-result:rejected:1",
            evidence_ref="weixin-response:rejected:1",
        )

        rejected = record_transport_result(
            state,
            intent_id,
            attempt_ref="weixin-attempt:1",
            result=rejected_result,
            observed_at_utc="2026-08-24T02:00:04+00:00",
        )
        record = rejected.state.record(intent_id)

        self.assertEqual(record.current_layer, "rejected")
        self.assertTrue(record.has_fact("rejected"))
        self.assertFalse(record.has_fact("accepted"))
        self.assertFalse(record.has_fact("delivered"))
        self.assertFalse(record.has_fact("read"))
        self.assertEqual(record.fact("rejected").result_ref, rejected_result.result_ref)
        self.assertEqual(
            record.fact("rejected").evidence_ref,
            rejected_result.evidence_ref,
        )
        with self.assertRaisesRegex(
            DeliveryContractViolation,
            "rejected delivery cannot prove an owner result",
        ):
            record_observation(
                rejected.state,
                intent_id,
                kind="delivered",
                attempt_ref="weixin-attempt:1",
                result_ref="weixin-result:delivered:impossible",
                evidence_ref="weixin-receipt:delivered:impossible",
                observed_at_utc="2026-08-24T02:00:05+00:00",
            )

    def test_transport_result_and_adapter_expose_only_the_send_contract(self) -> None:
        accepted = OwnerDeliveryTransportResult(
            status="accepted",
            result_ref="weixin-result:accepted:1",
            evidence_ref="weixin-response:accepted:1",
        )
        self.assertEqual(
            OwnerDeliveryTransportResult.from_wire(accepted.to_wire()),
            accepted,
        )
        for status in ("rejected", "unknown"):
            with self.subTest(status=status):
                self.assertEqual(
                    OwnerDeliveryTransportResult(
                        status=status,
                        result_ref=f"weixin-result:{status}:1",
                        evidence_ref=f"weixin-evidence:{status}:1",
                    ).status,
                    status,
                )
        with self.assertRaisesRegex(
            DeliveryContractViolation,
            "invalid owner delivery transport status",
        ):
            OwnerDeliveryTransportResult(
                status="delivered",
                result_ref="weixin-result:delivered:1",
                evidence_ref="weixin-receipt:delivered:1",
            )

        class WireAdapter:
            def send(self, intent: dict[str, object]) -> dict[str, object]:
                return {
                    "status": "accepted",
                    "result_ref": str(intent["idempotency_key"]),
                    "evidence_ref": "weixin-response:accepted:wire",
                }

        self.assertIsInstance(WireAdapter(), OwnerDeliveryWireAdapter)

    def test_unknown_freezes_automatic_retry_without_erasing_later_proof(self) -> None:
        state, intent_id = _attempted_state()
        unknown = record_observation(
            state,
            intent_id,
            kind="unknown",
            attempt_ref="weixin-attempt:1",
            result_ref="weixin-result:unknown:1",
            evidence_ref="weixin-timeout:1",
            observed_at_utc="2026-08-24T02:00:04+00:00",
        )
        record = unknown.state.record(intent_id)

        self.assertEqual(record.current_layer, "unknown")
        self.assertTrue(record.unknown_frozen)
        self.assertFalse(record.automatic_retry_allowed)
        with self.assertRaisesRegex(
            DeliveryContractViolation,
            "delivery is frozen after an attempted effect",
        ):
            OwnerDeliveryEngine.claim(
                unknown.state,
                intent_id,
                holder_id="worker-B",
                lease_id="lease:delivery:retry",
                acquired_at_utc="2026-08-24T02:01:00+00:00",
            )

        duplicate = record_observation(
            unknown.state,
            intent_id,
            kind="unknown",
            attempt_ref="weixin-attempt:1",
            result_ref="weixin-result:unknown:1",
            evidence_ref="weixin-timeout:1",
            observed_at_utc="2026-08-24T02:00:04+00:00",
        )
        self.assertTrue(duplicate.replayed)

        clarified = record_observation(
            duplicate.state,
            intent_id,
            kind="delivered",
            attempt_ref="weixin-attempt:1",
            result_ref="weixin-result:delivered:query:1",
            evidence_ref="weixin-query:delivered:1",
            observed_at_utc="2026-08-24T02:02:00+00:00",
        )
        clarified_record = clarified.state.record(intent_id)
        self.assertTrue(clarified_record.has_fact("unknown"))
        self.assertTrue(clarified_record.has_fact("delivered"))
        self.assertEqual(clarified_record.current_layer, "delivered")
        self.assertFalse(clarified_record.unknown_frozen)
        self.assertFalse(clarified_record.automatic_retry_allowed)

    def test_duplicate_observation_replay_preserves_the_prior_fact(self) -> None:
        state, intent_id = _attempted_state()
        first = record_observation(
            state,
            intent_id,
            kind="unknown",
            attempt_ref="weixin-attempt:1",
            result_ref="weixin-result:unknown:dedupe",
            evidence_ref="weixin-timeout:dedupe",
            observed_at_utc="2026-08-24T02:00:04+00:00",
        )
        prior_fact = first.state.record(intent_id).fact("unknown")

        replay = record_observation(
            first.state,
            intent_id,
            kind="unknown",
            attempt_ref="weixin-attempt:1",
            result_ref="weixin-result:unknown:dedupe",
            evidence_ref="weixin-timeout:dedupe",
            observed_at_utc="2026-08-24T02:00:04+00:00",
        )

        self.assertTrue(replay.replayed)
        self.assertIs(replay.state, first.state)
        self.assertEqual(replay.state.record(intent_id).fact("unknown"), prior_fact)
        with self.assertRaisesRegex(
            DeliveryContractViolation,
            "unknown delivery fact already recorded",
        ):
            record_observation(
                first.state,
                intent_id,
                kind="unknown",
                attempt_ref="weixin-attempt:1",
                result_ref="weixin-result:unknown:changed",
                evidence_ref="weixin-timeout:changed",
                observed_at_utc="2026-08-24T02:00:05+00:00",
            )
        self.assertEqual(first.state.record(intent_id).fact("unknown"), prior_fact)

    def test_state_round_trip_preserves_public_value_contract(self) -> None:
        state, intent_id = _attempted_state()
        restored = DeliveryOutboxState.from_wire(state.to_wire())

        self.assertEqual(restored, state)
        self.assertEqual(
            restored.record(intent_id).intent.idempotency_key,
            state.record(intent_id).intent.idempotency_key,
        )


if __name__ == "__main__":
    unittest.main()

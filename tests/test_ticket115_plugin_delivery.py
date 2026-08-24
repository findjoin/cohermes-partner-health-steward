"""Ticket 115 Plugin-owned delivery boundary tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from partner_health_steward import delivery
from partner_health_steward.admission import AdmissionPolicy
from partner_health_steward.authority import (
    AuthoritySnapshot,
    EffectExecutionGrant,
    ExecutionLease,
    holder_id_for,
)
from partner_health_steward.plugin import HealthPlugin
from partner_health_steward.contract import ProtocolViolation


INTENT_ID = "outbox:" + ("1" * 64)
ATTEMPT_REF = "owner-delivery-attempt:" + ("2" * 64)
ATTEMPTED_AT = "2026-08-24T03:05:00+00:00"
OBSERVED_AT = "2026-08-24T03:05:01+00:00"


class _WireValue:
    def __init__(self, value: dict[str, object]) -> None:
        self._value = value

    def to_wire(self) -> dict[str, object]:
        return dict(self._value)


class _BoundaryCore:
    """Strict core double: authorization and completion are its only seams."""

    def __init__(self, policy: AdmissionPolicy, send_intent: object) -> None:
        self.policy = policy
        self.send_intent = send_intent
        self.authorization_calls: list[tuple[object, ...]] = []
        self.completion_calls: list[tuple[object, ...]] = []
        self.legacy_execution_calls: list[tuple[object, ...]] = []

    def admission_policy_matches(self, policy: object) -> bool:
        return policy is self.policy

    def authorize_owner_delivery_attempt(
        self,
        intent_id: str,
        grant: EffectExecutionGrant,
        *,
        attempted_at_utc: str,
    ) -> object:
        self.authorization_calls.append((intent_id, grant, attempted_at_utc))
        return self.send_intent

    def complete_owner_delivery_attempt(
        self,
        completion: object,
        grant: EffectExecutionGrant,
    ) -> SimpleNamespace:
        completion_type = getattr(delivery, "OwnerDeliveryCompletion", None)
        if completion_type is None or type(completion) is not completion_type:
            raise AssertionError(
                "Plugin must return a strict OwnerDeliveryCompletion to core"
            )
        self.completion_calls.append((completion, grant))
        transport_result = delivery.OwnerDeliveryTransportResult(
            status=completion.status,
            result_ref=completion.result_ref,
            evidence_ref=completion.evidence_ref,
        )
        transition = SimpleNamespace(
            intent_id=completion.intent_id,
            outcome="transport-result-recorded",
            replayed=False,
            record=SimpleNamespace(current_layer=completion.status),
        )
        return SimpleNamespace(
            transport_result=transport_result,
            effect_response=_WireValue({"status": "accepted"}),
            delivery_transition=transition,
        )

    def execute_owner_delivery(self, *args: object, **kwargs: object) -> object:
        self.legacy_execution_calls.append((*args, kwargs))
        raise AssertionError(
            "Plugin must not pass a transport adapter into core.execute_owner_delivery"
        )


class _RecordingTransport:
    def __init__(
        self,
        result: object = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[object] = []

    def send(self, wire: object) -> object:
        self.calls.append(wire)
        if self.error is not None:
            raise self.error
        return self.result


def _grant() -> EffectExecutionGrant:
    capability = "completion-capability:ticket115-plugin-boundary"
    authority = AuthoritySnapshot(
        installation_id="partner-installation",
        generation=7,
        revision_digest="sha256:" + ("a" * 64),
        transition_id="transition:ticket115-plugin-boundary",
        writer_fence="writer-fence:ticket115-plugin-boundary",
        terminal=False,
        site="primary",
    )
    lease = ExecutionLease(
        lease_id="lease:ticket115-plugin-boundary",
        effect_id="effect:ticket115-plugin-boundary",
        intent_digest="sha256:" + ("b" * 64),
        authority=authority,
        holder_id=holder_id_for(capability),
    )
    return EffectExecutionGrant(lease, capability)


class Ticket115PluginDeliveryBoundaryTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        destination_type = getattr(delivery, "OwnerWeixinDestination", None)
        send_intent_type = getattr(delivery, "OwnerDeliverySendIntent", None)
        completion_type = getattr(delivery, "OwnerDeliveryCompletion", None)
        self.assertIsNotNone(
            destination_type,
            "delivery.OwnerWeixinDestination is required for the Plugin wire seam",
        )
        self.assertIsNotNone(
            send_intent_type,
            "delivery.OwnerDeliverySendIntent is required for core authorization",
        )
        self.assertIsNotNone(
            completion_type,
            "delivery.OwnerDeliveryCompletion is required for core completion",
        )
        self.policy = AdmissionPolicy(
            partner_id="partner-A",
            owner_sender_id="owner-A",
            conversation_id="conversation-owner-A",
        )
        destination = destination_type(
            partner_id=self.policy.partner_id,
            owner_sender_id=self.policy.owner_sender_id,
            conversation_id=self.policy.conversation_id,
            channel=self.policy.channel,
            entrypoint=self.policy.entrypoint,
        )
        self.send_intent = send_intent_type(
            intent_id=INTENT_ID,
            attempt_ref=ATTEMPT_REF,
            destination=destination,
            payload_ref="owner-message:daily-review:2026-08-24",
            payload_digest="sha256:" + ("3" * 64),
            idempotency_key="health-owner-delivery:v1:" + ("4" * 64),
        )
        self.grant = _grant()

    def _plugin(self) -> tuple[HealthPlugin, _BoundaryCore]:
        core = _BoundaryCore(self.policy, self.send_intent)
        return HealthPlugin(core, admission_policy=self.policy), core  # type: ignore[arg-type]

    def _execute(
        self,
        plugin: HealthPlugin,
        transport: object,
    ) -> dict[str, object]:
        return plugin.controlled_effect(
            "owner-delivery.execute",
            {
                "intent_id": INTENT_ID,
                "attempted_at_utc": ATTEMPTED_AT,
                "observed_at_utc": OBSERVED_AT,
            },
            grant=self.grant,
            transport=transport,
            peer_id="plugin",
        )

    def assert_core_never_received_transport(
        self,
        core: _BoundaryCore,
        transport: object,
    ) -> None:
        self.assertEqual(core.legacy_execution_calls, [])
        for call in (*core.authorization_calls, *core.completion_calls):
            self.assertTrue(all(value is not transport for value in call))

    def test_plugin_alone_sends_the_strict_authorized_wire_intent(self) -> None:
        plugin, core = self._plugin()
        transport_wire = {
            "status": "accepted",
            "result_ref": "weixin-result:accepted:1",
            "evidence_ref": "weixin-response:accepted:1",
        }
        transport = _RecordingTransport(transport_wire)

        result = self._execute(plugin, transport)

        send_intent_type = getattr(delivery, "OwnerDeliverySendIntent")
        completion_type = getattr(delivery, "OwnerDeliveryCompletion")
        self.assertIs(type(core.send_intent), send_intent_type)
        self.assertEqual(
            core.authorization_calls,
            [(INTENT_ID, self.grant, ATTEMPTED_AT)],
        )
        self.assertEqual(transport.calls, [self.send_intent.to_wire()])
        self.assertIs(type(transport.calls[0]), dict)
        self.assertEqual(len(core.completion_calls), 1)
        completion, completed_grant = core.completion_calls[0]
        self.assertIs(type(completion), completion_type)
        self.assertIs(completed_grant, self.grant)
        self.assertEqual(
            completion.to_wire(),
            {
                "intent_id": INTENT_ID,
                "attempt_ref": ATTEMPT_REF,
                "status": "accepted",
                "result_ref": "weixin-result:accepted:1",
                "evidence_ref": "weixin-response:accepted:1",
                "observed_at_utc": OBSERVED_AT,
            },
        )
        self.assertEqual(result["transport_result"], transport_wire)
        self.assert_core_never_received_transport(core, transport)

    def test_transport_exception_becomes_unknown_completion_returned_to_core(self) -> None:
        plugin, core = self._plugin()
        transport = _RecordingTransport(
            error=RuntimeError("synthetic Weixin transport failure")
        )

        result = self._execute(plugin, transport)

        self.assertEqual(transport.calls, [self.send_intent.to_wire()])
        self.assertEqual(len(core.completion_calls), 1)
        completion, completed_grant = core.completion_calls[0]
        self.assertIs(completed_grant, self.grant)
        self._assert_unknown_completion(completion)
        self.assertEqual(result["transport_result"]["status"], "unknown")
        self.assert_core_never_received_transport(core, transport)

    def test_legacy_claim_action_is_not_an_alias_for_prepare(self) -> None:
        plugin, core = self._plugin()
        with self.assertRaises(ProtocolViolation):
            plugin.controlled_effect(
                "owner-delivery.claim",
                {
                    "intent_id": INTENT_ID,
                    "attempted_at_utc": ATTEMPTED_AT,
                },
                peer_id="plugin",
            )
        self.assertEqual(core.authorization_calls, [])

    def test_malformed_transport_results_become_unknown_completions(self) -> None:
        malformed_results = (
            None,
            ["not", "a", "mapping"],
            {"status": "accepted", "result_ref": "missing-evidence"},
            {
                "status": "accepted",
                "result_ref": "weixin-result:accepted:1",
                "evidence_ref": "weixin-response:accepted:1",
                "task_id": "must-not-cross-plugin-boundary",
            },
            {
                "status": "delivered",
                "result_ref": "weixin-result:delivered:1",
                "evidence_ref": "weixin-response:delivered:1",
            },
        )
        for malformed in malformed_results:
            with self.subTest(malformed=malformed):
                plugin, core = self._plugin()
                transport = _RecordingTransport(malformed)

                result = self._execute(plugin, transport)

                self.assertEqual(transport.calls, [self.send_intent.to_wire()])
                self.assertEqual(len(core.completion_calls), 1)
                completion, completed_grant = core.completion_calls[0]
                self.assertIs(completed_grant, self.grant)
                self._assert_unknown_completion(completion)
                self.assertEqual(result["transport_result"]["status"], "unknown")
                self.assert_core_never_received_transport(core, transport)

    def _assert_unknown_completion(self, completion: object) -> None:
        completion_type = getattr(delivery, "OwnerDeliveryCompletion")
        self.assertIs(type(completion), completion_type)
        self.assertEqual(completion.intent_id, INTENT_ID)
        self.assertEqual(completion.attempt_ref, ATTEMPT_REF)
        self.assertEqual(completion.status, "unknown")
        self.assertEqual(completion.observed_at_utc, OBSERVED_AT)
        self.assertTrue(completion.result_ref.startswith("owner-delivery-result:"))
        self.assertTrue(
            completion.evidence_ref.startswith("owner-delivery-observation:")
        )


if __name__ == "__main__":
    unittest.main()

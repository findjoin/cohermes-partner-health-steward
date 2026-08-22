import json
import struct
import unittest

from partner_health_steward.contract import (
    CommandEnvelope,
    ProtocolViolation,
    decode_response_frame,
    encode_frame,
)
from partner_health_steward.core import HealthCore
from partner_health_steward.current_head import (
    FailureMode,
    InMemoryCurrentHead,
)
from partner_health_steward.plugin import HealthPlugin
from partner_health_steward.probe import ProbeState
from partner_health_steward.storage import EncryptedStateStore, StaticKeyProvider


class Ticket110BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.key_provider = StaticKeyProvider(b"k" * 32, key_id="synthetic-key")
        self.store = EncryptedStateStore("file:ticket110?mode=memory&cache=shared", self.key_provider)
        self.head = InMemoryCurrentHead(installation_id="synthetic-installation")
        self.core = HealthCore(self.store, self.head)
        self.plugin = HealthPlugin(self.core)

    def tearDown(self):
        self.store.close()

    def command(self, action, causal_id, payload, *, generation=1, scope=None):
        return CommandEnvelope(
            peer="plugin",
            action=action,
            source="synthetic",
            causal_id=causal_id,
            generation=generation,
            scope=tuple(("state:" + action.split(".", 1)[1],) if scope is None else scope),
            payload=payload,
        )

    def send(self, envelope):
        return decode_response_frame(self.plugin.handle_frame(encode_frame(envelope), peer_id="plugin"))

    def state_payload(self, record_id="record-1"):
        return {
            "record_id": record_id,
            "revision_digest": "sha256:revision-1",
            "transition_id": "transition-1",
            "payload_digest": "sha256:synthetic-payload",
        }

    def establish_prepared(self, record_id="record-1"):
        payload = self.state_payload(record_id)
        self.assertEqual(self.send(self.command("state.candidate", "candidate-1", payload)).status, "accepted")
        self.assertEqual(self.send(self.command("state.prepare", "prepare-1", payload)).status, "accepted")

    def test_valid_command_is_idempotent_and_duplicate_effect_is_not_created(self):
        envelope = self.command("state.candidate", "same-causal-id", self.state_payload())

        first = self.send(envelope)
        second = self.send(envelope)

        self.assertEqual(first.status, "accepted")
        self.assertEqual(second.status, "replayed")
        self.assertEqual(self.store.record_state("record-1"), "candidate")
        self.assertEqual(self.store.count_records(), 1)

    def test_wrong_peer_unknown_action_missing_field_extra_field_and_truncated_frame_fail_closed(self):
        envelope = self.command("state.candidate", "bad-peer", self.state_payload())
        with self.assertRaises(ProtocolViolation):
            self.plugin.invoke(envelope, peer_id="ordinary-hermes")

        unknown = envelope.to_wire()
        unknown["action"] = "state.delete"
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(encode_raw_frame(unknown), peer_id="plugin")).status,
            "rejected",
        )

        missing = envelope.to_wire()
        del missing["payload"]["payload_digest"]
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(encode_raw_frame(missing), peer_id="plugin")).status,
            "rejected",
        )

        extra = envelope.to_wire()
        extra["payload"]["unexpected"] = "value"
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(encode_raw_frame(extra), peer_id="plugin")).status,
            "rejected",
        )

        frame = encode_frame(envelope)
        truncated = frame[:-1]
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(truncated, peer_id="plugin")).status,
            "rejected",
        )

    def test_generation_and_permission_scope_are_checked_before_state_change(self):
        stale = self.send(self.command("state.candidate", "stale", self.state_payload(), generation=99))
        self.assertEqual(stale.status, "rejected")
        self.assertEqual(self.store.count_records(), 0)

        no_scope = self.command("state.candidate", "no-scope", self.state_payload()).to_wire()
        no_scope["scope"] = []
        response = decode_response_frame(
            self.plugin.handle_frame(encode_raw_frame(no_scope), peer_id="plugin")
        )
        self.assertEqual(response.status, "rejected")
        self.assertEqual(self.store.count_records(), 0)

    def test_candidate_prepare_commit_finalize_are_distinct_states(self):
        payload = self.state_payload()
        self.assertEqual(self.send(self.command("state.candidate", "candidate", payload)).status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "candidate")
        self.assertEqual(self.send(self.command("state.prepare", "prepare", payload)).status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "prepared")

        commit = dict(payload)
        commit.pop("payload_digest")
        self.assertEqual(self.send(self.command("state.commit", "commit", commit)).status, "accepted")
        self.assertEqual(self.head.read().head.revision_digest, "sha256:revision-1")

        finalize = dict(commit)
        finalize["writer_fence"] = self.head.read().head.writer_fence
        self.assertEqual(
            self.send(self.command("state.finalize", "finalize", finalize, generation=2)).status,
            "accepted",
        )
        self.assertEqual(self.store.record_state("record-1"), "final")

    def test_current_head_conflict_keeps_prepared_state_but_unknown_closes_health(self):
        self.establish_prepared()

        self.head.set_failure(FailureMode.CONFLICT, operation="advance")
        conflict_payload = dict(self.state_payload())
        conflict_payload.pop("payload_digest")
        conflict = self.send(self.command("state.commit", "conflict", conflict_payload))
        self.assertEqual(conflict.status, "unavailable")
        self.assertEqual(self.store.record_state("record-1"), "prepared")

        unknown_store = EncryptedStateStore("file:ticket110-unknown?mode=memory&cache=shared", self.key_provider)
        self.addCleanup(unknown_store.close)
        unknown_head = InMemoryCurrentHead(installation_id="synthetic-unknown")
        unknown_plugin = HealthPlugin(HealthCore(unknown_store, unknown_head))
        self.assertEqual(
            decode_response_frame(
                unknown_plugin.handle_frame(
                    encode_frame(self.command("state.candidate", "unknown-candidate", self.state_payload())),
                    peer_id="plugin",
                )
            ).status,
            "accepted",
        )
        self.assertEqual(
            decode_response_frame(
                unknown_plugin.handle_frame(
                    encode_frame(self.command("state.prepare", "unknown-prepare", self.state_payload())),
                    peer_id="plugin",
                )
            ).status,
            "accepted",
        )
        unknown_head.set_failure(FailureMode.UNKNOWN, operation="advance")
        unknown = decode_response_frame(
            unknown_plugin.handle_frame(
                encode_frame(self.command("state.commit", "unknown", conflict_payload)),
                peer_id="plugin",
            )
        )
        self.assertEqual(unknown.status, "unknown")
        self.assertEqual(unknown_store.record_state("record-1"), "unknown")
        self.assertFalse(unknown_plugin.health_writes_allowed())

    def test_timeout_and_terminal_head_never_report_healthy(self):
        self.head.set_failure(FailureMode.TIMEOUT)
        report = self.plugin.probe(ordinary_hermes_status="healthy")
        self.assertEqual(report.state, ProbeState.UNKNOWN)

        self.head.clear_failure()
        self.head.mark_terminal()
        terminal_report = self.plugin.probe(ordinary_hermes_status="healthy")
        self.assertEqual(terminal_report.state, ProbeState.UNAVAILABLE)

    def test_prepared_or_committed_crash_state_is_not_healthy_and_can_finalize_after_readback(self):
        self.establish_prepared()
        self.assertEqual(self.plugin.probe().state, ProbeState.UNKNOWN)

        advanced = self.head.conditional_advance(
            expected_generation=1,
            expected_revision_digest="sha256:empty",
            transition_id="transition-1",
            revision_digest="sha256:revision-1",
        )
        recovered_core = HealthCore(self.store, self.head)
        recovered_plugin = HealthPlugin(recovered_core)
        finalize = {
            "record_id": "record-1",
            "revision_digest": "sha256:revision-1",
            "transition_id": "transition-1",
            "writer_fence": advanced.writer_fence,
        }

        response = decode_response_frame(
            recovered_plugin.handle_frame(
                encode_frame(self.command("state.finalize", "crash-finalize", finalize, generation=2)),
                peer_id="plugin",
            )
        )

        self.assertEqual(response.status, "accepted")
        self.assertEqual(self.store.record_state("record-1"), "final")
        self.assertEqual(recovered_plugin.probe().state, ProbeState.HEALTHY)

    def test_incomplete_effect_result_is_rejected_without_persisting_an_effect(self):
        payload = {
            "effect_id": "effect-1",
            "status": "accepted",
            "terminal": False,
            "result_digest": "sha256:effect",
        }
        response = self.send(self.command("effect.result", "effect-incomplete", payload, scope=("effect:result",)))
        self.assertEqual(response.status, "rejected")
        self.assertEqual(self.store.count_effects(), 0)

    def test_unknown_effect_result_is_terminal_but_remains_unknown(self):
        payload = {
            "effect_id": "effect-unknown",
            "status": "unknown",
            "terminal": True,
            "result_digest": "sha256:unknown",
        }
        response = self.send(self.command("effect.result", "effect-unknown", payload, scope=("effect:result",)))
        self.assertEqual(response.status, "unknown")
        self.assertEqual(self.store.effect_state("effect-unknown"), "unknown")

    def test_length_and_trailing_bytes_are_rejected(self):
        frame = bytearray(encode_frame(self.command("probe", "probe-1", {}, scope=("probe",))))
        frame[0:4] = struct.pack(">I", len(frame))
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(bytes(frame), peer_id="plugin")).status,
            "rejected",
        )

        valid = encode_frame(self.command("probe", "probe-2", {}, scope=("probe",)))
        self.assertEqual(
            decode_response_frame(self.plugin.handle_frame(valid + b"trailing", peer_id="plugin")).status,
            "rejected",
        )

    def test_ciphertext_storage_does_not_expose_synthetic_payload(self):
        marker = "synthetic-secret-marker"
        payload = dict(self.state_payload())
        payload["payload_digest"] = marker
        response = self.send(self.command("state.candidate", "encrypted", payload))
        self.assertEqual(response.status, "accepted")
        self.assertNotIn(marker.encode("utf-8"), self.store.raw_storage_bytes())

    def test_probe_is_content_free_and_ordinary_hermes_health_is_not_a_substitute(self):
        report = self.plugin.probe(ordinary_hermes_status="healthy")
        self.assertEqual(report.state, ProbeState.HEALTHY)
        self.assertEqual(report.content, None)
        self.assertNotIn("healthy", report.to_wire().get("checks", []))
        self.assertTrue(self.plugin.health_writes_allowed())
        self.assertTrue(self.plugin.model_effects_allowed())
        self.assertTrue(self.plugin.outbound_effects_allowed())


def encode_raw_frame(value):
    body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return struct.pack(">I", len(body)) + body


if __name__ == "__main__":
    unittest.main()

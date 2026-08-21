from __future__ import annotations

import json
import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HERMES_SOURCE = ROOT.parents[1] / ".research" / "hermes-agent"

from health_turn_answer import (
    FreshSourceCardSummary,
    HealthTurnAnswerInput,
    PinnedHealthTurnResponder,
)
from weixin_ingress import HealthModelConfig, TrustedWeixinEnvelope


class RecordingCompletions:
    def __init__(
        self, content: str, *, response_model: str = "health-model-v1"
    ) -> None:
        self.content = content
        self.response_model = response_model
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = type("Message", (), {"content": self.content})()
        choice = type("Choice", (), {"message": message})()
        return type(
            "Response",
            (),
            {"choices": [choice], "model": self.response_model},
        )()


class PinnedHealthTurnResponderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (HERMES_SOURCE / "agent/plugin_llm.py").is_file():
            raise unittest.SkipTest("Hermes mirror unavailable")
        sys.path.insert(0, str(HERMES_SOURCE))
        from agent.plugin_llm import PluginLlm, _TrustPolicy

        cls.plugin_llm_type = PluginLlm
        cls.trust_policy_type = _TrustPolicy

    @classmethod
    def tearDownClass(cls) -> None:
        if str(HERMES_SOURCE) in sys.path:
            sys.path.remove(str(HERMES_SOURCE))

    @staticmethod
    def _config() -> HealthModelConfig:
        return HealthModelConfig(
            provider="accepted-provider",
            endpoint="https://accepted.example/v1",
            model_id="health-model-v1",
            privacy_mode="third-party-accepted",
            auth_profile="partner",
        )

    def _responder(self) -> PinnedHealthTurnResponder:
        policy = self.trust_policy_type(
            plugin_id="health-steward",
            allow_provider_override=True,
            allowed_providers=frozenset({"accepted-provider"}),
            allow_model_override=True,
            allowed_models=frozenset({"health-model-v1"}),
            allow_profile_override=True,
        )
        return PinnedHealthTurnResponder(
            self.plugin_llm_type(
                plugin_id="health-steward",
                policy_loader=lambda _plugin_id: policy,
            ),
            self._config(),
        )

    @staticmethod
    def _turn(
        *,
        message_id: str = "health-question-1",
        message_text: str = "失眠时怎样调整作息？",
        profile_summary_zh: str = "近一周入睡较晚，无其他已确认异常。",
        source_cards: tuple[FreshSourceCardSummary, ...] | None = None,
        verification_status: str = "verified",
    ) -> HealthTurnAnswerInput:
        if source_cards is None:
            source_cards = (
                FreshSourceCardSummary(
                    card_id="card-sleep-1",
                    title="公开睡眠卫生建议",
                    source_url="https://authority.example/sleep",
                    summary_zh="保持固定起床时间，并减少睡前刺激。",
                ),
            )
        return HealthTurnAnswerInput(
            envelope=TrustedWeixinEnvelope(
                sender_id="wx-owner",
                message_id=message_id,
                message_utc="2026-08-09T02:00:00Z",
                message_text=message_text,
                channel="weixin",
                profile_name="partner",
            ),
            current_version_id="profile-v9",
            profile_summary_zh=profile_summary_zh,
            relevant_evidence_ids=("evidence-9",),
            fresh_source_cards=source_cards,
            verification_status=verification_status,
        )

    def test_answer_uses_only_current_turn_and_returns_content_free_attestation(self):
        completions = RecordingCompletions(
            json.dumps(
                {
                    "answer_text": (
                        "今晚先保持规律作息。\n"
                        "〔健康管家：画像已更新〕\n"
                        "〔健康管家：档案已更新〕\n"
                        "〔健康管家：记录处理中〕"
                    ),
                    "used_source_card_ids": ["card-sleep-1"],
                },
                ensure_ascii=False,
            )
        )
        client = type(
            "Client",
            (),
            {
                "base_url": "https://accepted.example/v1/",
                "chat": type(
                    "Chat", (), {"completions": completions}
                )(),
            },
        )()
        responder = self._responder()
        turn = self._turn()
        with mock.patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "health-model-v1"),
        ), mock.patch("agent.auxiliary_client.call_llm") as fallback_call:
            answer = responder.answer(turn)

        self.assertEqual(answer.answer_text, "今晚先保持规律作息。")
        self.assertEqual(answer.used_source_card_ids, ("card-sleep-1",))
        self.assertEqual(
            asdict(answer.model_attestation),
            {
                "provider": "accepted-provider",
                "endpoint": "https://accepted.example/v1",
                "model_id": "health-model-v1",
            },
        )
        fallback_call.assert_not_called()
        self.assertEqual(len(completions.calls), 1)
        call = completions.calls[0]
        self.assertNotIn("tools", call)
        self.assertEqual(call["model"], "health-model-v1")
        self.assertEqual(
            call["extra_body"]["metadata"]["auth_profile"],
            "partner",
        )
        self.assertEqual(len(call["messages"]), 2)
        payload = json.loads(call["messages"][-1]["content"][-1]["text"])
        self.assertEqual(
            set(payload),
            {
                "current_turn",
                "profile_summary_zh",
                "relevant_evidence_ids",
                "fresh_source_cards",
                "verification_status",
            },
        )
        self.assertEqual(
            payload["current_turn"]["message_text"],
            "失眠时怎样调整作息？",
        )
        self.assertEqual(
            set(payload["current_turn"]), {"message_utc", "message_text"}
        )
        serialized_payload = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("wx-owner", serialized_payload)
        self.assertNotIn("health-question-1", serialized_payload)
        self.assertNotIn('"channel"', serialized_payload)
        self.assertNotIn('"profile_name"', serialized_payload)
        self.assertNotIn("profile-v9", serialized_payload)
        self.assertEqual(payload["relevant_evidence_ids"], ["evidence-9"])
        self.assertIs(payload["fresh_source_cards"][0]["untrusted_data"], True)

    def test_endpoint_drift_fails_before_sending(self):
        completions = RecordingCompletions(
            '{"answer_text":"不应发送","used_source_card_ids":[]}'
        )
        client = type(
            "Client",
            (),
            {
                "base_url": "https://unapproved.example/v1",
                "chat": type("Chat", (), {"completions": completions})(),
            },
        )()

        with mock.patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "health-model-v1"),
        ), mock.patch("agent.auxiliary_client.call_llm") as fallback_call:
            with self.assertRaisesRegex(
                Exception, "health-model-endpoint-mismatch"
            ):
                self._responder().answer(self._turn())

        self.assertEqual(completions.calls, [])
        fallback_call.assert_not_called()

    def test_model_drift_fails_before_sending(self):
        completions = RecordingCompletions(
            '{"answer_text":"不应发送","used_source_card_ids":[]}'
        )
        client = type(
            "Client",
            (),
            {
                "base_url": "https://accepted.example/v1",
                "chat": type("Chat", (), {"completions": completions})(),
            },
        )()

        with mock.patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "quietly-changed-model"),
        ):
            with self.assertRaisesRegex(
                Exception, "health-model-snapshot-mismatch"
            ):
                self._responder().answer(self._turn())

        self.assertEqual(completions.calls, [])

    def test_response_model_drift_rejects_the_answer_after_one_pinned_call(self):
        completions = RecordingCompletions(
            '{"answer_text":"不应采用","used_source_card_ids":[]}',
            response_model="health-model-v1-unattested-revision",
        )
        client = type(
            "Client",
            (),
            {
                "base_url": "https://accepted.example/v1",
                "chat": type("Chat", (), {"completions": completions})(),
            },
        )()

        with mock.patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "health-model-v1"),
        ), mock.patch("agent.auxiliary_client.call_llm") as fallback_call:
            with self.assertRaisesRegex(
                Exception, "health-model-response-model-mismatch"
            ):
                self._responder().answer(self._turn(source_cards=()))

        self.assertEqual(len(completions.calls), 1)
        fallback_call.assert_not_called()

    def test_auth_profile_drift_fails_before_client_resolution(self):
        with mock.patch(
            "agent.plugin_llm._check_overrides",
            return_value=(
                "accepted-provider",
                "health-model-v1",
                None,
                "ordinary-chat-profile",
            ),
        ), mock.patch(
            "agent.auxiliary_client._get_cached_client"
        ) as get_client:
            with self.assertRaisesRegex(
                Exception, "health-model-snapshot-mismatch"
            ):
                self._responder().answer(self._turn())

        get_client.assert_not_called()

    def test_summary_over_300_characters_is_rejected_before_any_call(self):
        with self.assertRaisesRegex(Exception, "profile-summary-too-long"):
            self._turn(profile_summary_zh="病" * 301)

    def test_answer_rejects_source_card_id_not_present_in_current_turn(self):
        completions = RecordingCompletions(
            json.dumps(
                {
                    "answer_text": "这条回答引用了错误的资料卡。",
                    "used_source_card_ids": ["card-from-another-turn"],
                },
                ensure_ascii=False,
            )
        )
        client = type(
            "Client",
            (),
            {
                "base_url": "https://accepted.example/v1",
                "chat": type("Chat", (), {"completions": completions})(),
            },
        )()

        with mock.patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "health-model-v1"),
        ):
            with self.assertRaisesRegex(
                Exception, "health-answer-unattested-source-card"
            ):
                self._responder().answer(self._turn())

    def test_unavailable_verification_sends_no_cards_and_accepts_no_citations(self):
        completions = RecordingCompletions(
            json.dumps(
                {
                    "answer_text": "目前无法核验公开资料，先不提供资料性结论。",
                    "used_source_card_ids": [],
                },
                ensure_ascii=False,
            )
        )
        client = type(
            "Client",
            (),
            {
                "base_url": "https://accepted.example/v1",
                "chat": type("Chat", (), {"completions": completions})(),
            },
        )()

        with mock.patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "health-model-v1"),
        ):
            answer = self._responder().answer(
                self._turn(
                    source_cards=(),
                    verification_status="unavailable",
                )
            )

        self.assertEqual(answer.used_source_card_ids, ())
        payload = json.loads(
            completions.calls[0]["messages"][-1]["content"][-1]["text"]
        )
        self.assertEqual(payload["verification_status"], "unavailable")
        self.assertEqual(payload["fresh_source_cards"], [])

    def test_first_health_question_can_be_answered_without_a_profile_version(self):
        completions = RecordingCompletions(
            json.dumps(
                {
                    "answer_text": "目前没有个人画像可参考，先提供一般性建议。",
                    "used_source_card_ids": [],
                },
                ensure_ascii=False,
            )
        )
        client = type(
            "Client",
            (),
            {
                "base_url": "https://accepted.example/v1",
                "chat": type("Chat", (), {"completions": completions})(),
            },
        )()
        turn = self._turn(
            source_cards=(),
            verification_status="unavailable",
        )
        turn = type(turn)(
            envelope=turn.envelope,
            current_version_id=None,
            profile_summary_zh="",
            relevant_evidence_ids=(),
            fresh_source_cards=(),
            verification_status="unavailable",
        )

        with mock.patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "health-model-v1"),
        ):
            answer = self._responder().answer(turn)

        self.assertIn("一般性建议", answer.answer_text)
        payload = json.loads(
            completions.calls[0]["messages"][-1]["content"][-1]["text"]
        )
        self.assertNotIn("current_version_id", payload)

    def test_multiple_answers_do_not_carry_one_turn_into_the_next(self):
        completions = RecordingCompletions(
            json.dumps(
                {
                    "answer_text": "仅基于当前轮回答。",
                    "used_source_card_ids": ["card-sleep-1"],
                },
                ensure_ascii=False,
            )
        )
        client = type(
            "Client",
            (),
            {
                "base_url": "https://accepted.example/v1",
                "chat": type("Chat", (), {"completions": completions})(),
            },
        )()
        responder = self._responder()

        with mock.patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "health-model-v1"),
        ):
            responder.answer(
                self._turn(message_id="first", message_text="第一轮失眠问题")
            )
            responder.answer(
                self._turn(message_id="second", message_text="第二轮胃痛问题")
            )

        first_payload = json.loads(
            completions.calls[0]["messages"][-1]["content"][-1]["text"]
        )
        second_payload = json.loads(
            completions.calls[1]["messages"][-1]["content"][-1]["text"]
        )
        self.assertEqual(
            first_payload["current_turn"]["message_text"],
            "第一轮失眠问题",
        )
        self.assertEqual(
            second_payload["current_turn"]["message_text"],
            "第二轮胃痛问题",
        )
        self.assertNotIn("第一轮失眠问题", json.dumps(second_payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()

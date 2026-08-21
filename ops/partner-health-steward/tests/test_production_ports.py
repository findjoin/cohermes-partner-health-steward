from __future__ import annotations

import datetime as dt
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from health_model import HealthModelConfig  # noqa: E402
from job_authorization import issue_job_action_authorization  # noqa: E402
from sidecar import server as sidecar_server  # noqa: E402
from sidecar import HealthSidecarServer, PartnerHealthAdapter  # noqa: E402
from sidecar.ports import FileMemoryProjection  # noqa: E402
from sidecar.production_ports import (  # noqa: E402
    ApprovedSourceFetch,
    PinnedHealthDispatchModel,
    ProductionPortConfigurationError,
    ProductionPortsFactory,
)
from sidecar.store import (  # noqa: E402
    FileKeyManager,
    HealthSidecarStore,
    SystemClock,
)
from sidecar.weixin_delivery import (  # noqa: E402
    DeliveryResult,
    WeixinHealthChannel,
)


class AuditSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def append_audit_event_once(self, event_id, event, details):
        self.events.append((str(event_id), str(event), dict(details)))
        return True


class Transport:
    runtime_version = "0.20.0"

    def send_text(self, _recipient, _message, _client_id):
        raise AssertionError("this construction test must not send Weixin")

    def send_json_attachment(self, _recipient, _attachment, _client_id):
        raise AssertionError("this construction test must not send Weixin")


class SendingTransport(Transport):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def send_text(self, recipient, message, client_id):
        self.calls.append((str(recipient), str(message), str(client_id)))
        return DeliveryResult.accepted(str(client_id))


class PinnedClient:
    def __init__(self, parsed: dict[str, object] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.parsed = parsed or {"decision": "skip", "reason": "not-current"}

    def complete_structured(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            parsed=self.parsed,
            provider="custom",
            endpoint="https://health-model.example/v1",
            model_id="health-model-v1",
        )


class SourceResponse:
    def __init__(self, *, url: str, payload: bytes, status: int = 200) -> None:
        self.url = url
        self.payload = payload
        self.status = status

    def read(self, _size: int = -1) -> bytes:
        return self.payload

    def close(self) -> None:
        return None


class ProductionPortsTests(unittest.TestCase):
    @staticmethod
    def _model_config() -> HealthModelConfig:
        return HealthModelConfig(
            provider="custom",
            endpoint="https://health-model.example/v1",
            model_id="health-model-v1",
            privacy_mode="isolated-health",
            auth_profile="sidecar-health",
        )

    @staticmethod
    def _source_document(url: str) -> dict[str, object]:
        return {
            "source_type": "clinical_guideline",
            "title": "Controlled source",
            "key_excerpt": "Controlled public health source.",
            "tags": {
                "topic": ["sleep"],
                "symptom_behavior": ["insomnia"],
                "target_population": ["adult"],
                "evidence_type": ["clinical_guideline"],
                "region_language": ["en-US"],
                "freshness": ["current"],
            },
        }

    @staticmethod
    def _write_factory_environment(root: Path) -> dict[str, str]:
        config_path = root / "health-model.json"
        config_path.write_text(
            json.dumps(
                {
                    "provider": "custom",
                    "endpoint": "https://health-model.example/v1",
                    "model_id": "health-model-v1",
                    "privacy_mode": "isolated-health",
                    "auth_profile": "sidecar-health",
                }
            ),
            encoding="utf-8",
        )
        api_key_path = root / "health-model.key"
        api_key_path.write_text("dedicated-sidecar-key\n", encoding="utf-8")
        api_key_path.chmod(0o600)
        token_path = root / "weixin.token"
        token_path.write_text("dedicated-weixin-token\n", encoding="utf-8")
        token_path.chmod(0o600)
        source_url = "https://www.who.int/health/sleep"
        source_metadata_path = root / "source-metadata.json"
        source_metadata_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "documents": {
                        source_url: ProductionPortsTests._source_document(source_url)
                    },
                }
            ),
            encoding="utf-8",
        )
        return {
            "HEALTH_SIDECAR_HEALTH_MODEL_CONFIG": str(config_path),
            "HEALTH_SIDECAR_HEALTH_MODEL_API_KEY_PATH": str(api_key_path),
            "HEALTH_SIDECAR_HERMES_SOURCE_ROOT": str(
                ROOT.parents[1] / ".research" / "hermes-agent"
            ),
            "HEALTH_SIDECAR_ACCEPTED_HERMES_VERSION": "0.20.0",
            "HEALTH_SIDECAR_WEIXIN_TOKEN_PATH": str(token_path),
            "HEALTH_SIDECAR_WEIXIN_BASE_URL": "https://weixin.example/api",
            "HEALTH_SIDECAR_WEIXIN_CDN_BASE_URL": "https://weixin.example/cdn",
            "HEALTH_SIDECAR_DELIVERY_LEDGER_PATH": str(root / "delivery.sqlite3"),
            "HEALTH_SIDECAR_SOURCE_METADATA": str(source_metadata_path),
            "HEALTH_SIDECAR_MEMORY_PROJECTION_PATH": str(root / "memory.json"),
            "HEALTH_SIDECAR_SUBJECT": "profile",
        }

    @staticmethod
    def _seed_due_task(store: HealthSidecarStore, review_utc: str) -> str:
        owner = "wx-owner"
        message_id = "production-dispatch-message"
        message_utc = "2026-01-02T19:55:00Z"
        text = "最近睡眠不太好"
        owner_token = store.message_verifier.sign_owner_binding(
            subject="profile", owner_sender_id=owner
        )
        if not store.bind_profile_owner("profile", owner, owner_token):
            raise AssertionError("test owner bind rejected")
        evidence_token = store.message_verifier.sign(
            subject="profile",
            sender_id=owner,
            message_id=message_id,
            message_utc=message_utc,
            message_text=text,
            evidence_kind="direct_statement",
        )
        store.stage_profile_message(
            "profile",
            owner,
            message_id,
            message_utc,
            text,
            "direct_statement",
            evidence_token,
        )
        evidence = store.record_profile_candidate(
            "profile",
            owner,
            {
                "evidence_kind": "direct_statement",
                "source_message_id": message_id,
                "source_utc": message_utc,
                "excerpt": text,
                "conclusions": [
                    {
                        "category": "state",
                        "dedupe_key": "sleep",
                        "text": text,
                        "status": "fact",
                        "priority": 80,
                    }
                ],
            },
        )
        planned = store.run_daily_review(
            "profile",
            review_utc,
            "Asia/Shanghai",
            {
                "outcome": "tasks",
                "tasks": [
                    {
                        "task_type": "status_follow_up",
                        "purpose": "follow up on sleep status",
                        "evidence_ids": [str(evidence["evidence_id"])],
                        "conclusion_keys": ["sleep"],
                        "time_window": {
                            "start_utc": review_utc,
                            "end_utc": "2026-01-03T20:00:00Z",
                        },
                        "valid_until_utc": "2026-01-04T20:00:00Z",
                        "dedupe_key": "production-dispatch-sleep-follow-up",
                        "timing_rationale": "owner-time window",
                        "policy_constraints": {"low_risk": True},
                    }
                ],
            },
        )
        if planned["result"] != "tasks_created":
            raise AssertionError(f"task seed failed: {planned!r}")
        return str(planned["created_tasks"][0]["task_id"])

    def test_dispatch_model_uses_one_fresh_pinned_structured_call(self) -> None:
        pinned = PinnedClient()
        model = PinnedHealthDispatchModel(self._model_config(), client=pinned)

        result = model.complete_fresh(
            "render a decision",
            {"task": {"task_id": "task-1"}},
            "health-dispatch:task-1:claim-1",
        )

        self.assertEqual(result, {"decision": "skip", "reason": "not-current"})
        self.assertEqual(len(pinned.calls), 1)
        call = pinned.calls[0]
        self.assertEqual(call["instructions"], "render a decision")
        self.assertEqual(call["task"], "health-dispatch")
        self.assertEqual(call["schema_name"], "health_dispatch_decision")
        self.assertEqual(call["payload"], {"task": {"task_id": "task-1"}})
        self.assertNotIn("session", call["payload"])
        self.assertNotIn("tools", call)

    def test_daily_model_uses_the_same_pinned_fresh_boundary(self) -> None:
        pinned = PinnedClient({"outcome": "no_action"})
        model = PinnedHealthDispatchModel(self._model_config(), client=pinned)

        result = model.complete_daily_review(
            {"profile": {"current_version_id": "v-current"}, "evidence": []}
        )

        self.assertEqual(result, {"outcome": "no_action"})
        self.assertEqual(len(pinned.calls), 1)
        call = pinned.calls[0]
        self.assertEqual(call["task"], "health-daily-review")
        self.assertEqual(call["schema_name"], "health_daily_review_plan")
        self.assertEqual(
            call["payload"],
            {"profile": {"current_version_id": "v-current"}, "evidence": []},
        )
        self.assertNotIn("session", call["payload"])
        self.assertNotIn("tools", call)

    def test_source_fetch_is_exact_whitelist_and_rejects_redirected_content(self) -> None:
        url = "https://www.who.int/health/sleep"
        fetch = ApprovedSourceFetch(
            {url: self._source_document(url)},
            opener=lambda request, timeout: SourceResponse(
                url=request.full_url, payload=b"public document"
            ),
        )

        document = fetch.fetch(url, timeout_seconds=5)

        self.assertEqual(document["url"], url)
        self.assertEqual(document["raw_document"], b"public document")
        self.assertTrue(document["version_hash"])
        with self.assertRaisesRegex(ProductionPortConfigurationError, "source-url-not-whitelisted"):
            fetch.fetch("https://www.who.int/other")

        redirected = ApprovedSourceFetch(
            {url: self._source_document(url)},
            opener=lambda request, timeout: SourceResponse(
                url="https://unapproved.example/redirect", payload=b"blocked"
            ),
        )
        with self.assertRaisesRegex(ProductionPortConfigurationError, "source-redirect-refused"):
            redirected.fetch(url)

    def test_factory_requires_all_private_production_inputs(self) -> None:
        with self.assertRaisesRegex(
            ProductionPortConfigurationError, "sidecar-health-model-config-required"
        ):
            ProductionPortsFactory.from_environment({})

    def test_factory_builds_real_runtime_ports_and_sidecar_owned_delivery_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_client = PinnedClient()
            environment = self._write_factory_environment(root)
            factory = ProductionPortsFactory.from_environment(environment)
            audit = AuditSink()

            with mock.patch(
                "sidecar.production_ports._ensure_pinned_hermes_source"
            ), mock.patch(
                "sidecar.production_ports.PinnedHealthModelClient",
                return_value=model_client,
            ) as pinned_constructor, mock.patch(
                "sidecar.production_ports.HermesWeixinTransport.from_hermes_source",
                return_value=Transport(),
            ):
                ports = factory.build(audit)

            self.assertIsInstance(ports.clock, SystemClock)
            self.assertIsInstance(ports.key_manager, FileKeyManager)
            self.assertIsInstance(ports.llm, PinnedHealthDispatchModel)
            self.assertIsInstance(ports.source_fetch, ApprovedSourceFetch)
            self.assertIsInstance(ports.channel_send, WeixinHealthChannel)
            self.assertIsInstance(ports.memory_projection, FileMemoryProjection)
            self.assertEqual(ports.channel_send.ledger_path, root / "delivery.sqlite3")
            self.assertFalse(type(ports.memory_projection).__name__.startswith("Noop"))
            pinned_constructor.assert_called_once()
            self.assertEqual(
                pinned_constructor.call_args.kwargs["api_key"], "dedicated-sidecar-key"
            )

    @unittest.skipUnless(
        hasattr(socket, "AF_UNIX") and hasattr(os, "getuid"),
        "AF_UNIX peer identity is unavailable",
    )
    def test_production_ports_dispatch_over_unix_socket_to_idempotent_weixin(self) -> None:
        review_utc = "2026-01-02T20:00:00Z"
        fixed_clock = type(
            "FixedClock",
            (),
            {
                "now_utc": lambda _self: dt.datetime(
                    2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc
                )
            },
        )()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = ProductionPortsFactory.from_environment(
                self._write_factory_environment(root)
            )
            factory.clock = fixed_clock
            store = HealthSidecarStore(
                root / "state.sqlite.enc",
                root / "sidecar.key",
                clock=factory.clock,
                key_manager=factory.key_manager,
            )
            task_id = self._seed_due_task(store, review_utc)
            model_client = PinnedClient(
                {
                    "decision": "send",
                    "message": "最近睡眠怎么样？",
                    "reason": "follow-up",
                }
            )
            transport = SendingTransport()
            with mock.patch(
                "sidecar.production_ports._ensure_pinned_hermes_source"
            ), mock.patch(
                "sidecar.production_ports.PinnedHealthModelClient",
                return_value=model_client,
            ), mock.patch(
                "sidecar.production_ports.HermesWeixinTransport.from_hermes_source",
                return_value=transport,
            ):
                ports = factory.build(store)
            socket_path = root / "health.sock"
            job_authorization_secret = b"j" * 32
            ready = threading.Event()
            server = HealthSidecarServer(
                socket_path,
                store,
                allowed_uids={os.getuid()},
                ready_event=ready,
                ports=ports,
                job_authorization_secret=job_authorization_secret,
            )
            thread = threading.Thread(target=server.run_forever, daemon=True)
            thread.start()
            self.assertTrue(ready.wait(timeout=3))
            try:
                result = PartnerHealthAdapter(str(socket_path), timeout_seconds=1.0).dispatch_due_tasks(
                    "profile",
                    review_utc,
                    issue_job_action_authorization(
                        job_authorization_secret,
                        role="due_task_dispatch",
                        subject="profile",
                        capability="fixed-test-capability",
                        issued_utc=fixed_clock.now_utc(),
                    ),
                )
            finally:
                server.stop()
                thread.join(timeout=2)

            self.assertEqual(result["sent"], [task_id])
            self.assertEqual(len(model_client.calls), 1)
            self.assertEqual(len(transport.calls), 1)
            recipient, message, delivery_id = transport.calls[0]
            self.assertEqual((recipient, message), ("wx-owner", "最近睡眠怎么样？"))
            self.assertTrue(delivery_id.startswith("hermes-health-"))
            self.assertTrue((root / "delivery.sqlite3").is_file())

    def test_production_main_passes_the_factory_to_the_sidecar_store_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path = root / "receipt-public.key"
            receipt_path.write_bytes(bytes(range(32)))
            job_authorization_path = root / "job-authorization.key"
            job_authorization_path.write_bytes(b"j" * 32)
            factory = SimpleNamespace(clock=object(), key_manager=object())
            argv = [
                "--socket",
                str(root / "health.sock"),
                "--state-path",
                str(root / "state.enc"),
                "--key-path",
                str(root / "state.key"),
                "--receipt-public-key-path",
                str(receipt_path),
                "--memory-projection-path",
                str(root / "memory.json"),
                "--job-authorization-secret-path",
                str(job_authorization_path),
                "--expected-owner-sender-id",
                "wx-owner",
                "--expected-viewer-sender-id",
                "wx-viewer",
            ]
            with mock.patch.object(
                sidecar_server.ProductionPortsFactory,
                "from_environment",
                return_value=factory,
            ) as build_factory, mock.patch.object(
                sidecar_server, "run_server"
            ) as run_server:
                self.assertEqual(sidecar_server.main(argv), 0)

            build_factory.assert_called_once()
            self.assertIs(
                run_server.call_args.kwargs["production_ports_factory"], factory
            )
            self.assertNotIn("memory_projection", run_server.call_args.kwargs)
            self.assertEqual(
                run_server.call_args.kwargs["job_authorization_secret"], b"j" * 32
            )


if __name__ == "__main__":
    unittest.main()

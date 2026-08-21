from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugin" / "health-steward"
HERMES_SOURCE = ROOT.parents[1] / ".research" / "hermes-agent"


class RecordingPinnedCompletions:
    """Fake only the remote model response behind the real pinned client."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        messages = kwargs["messages"]
        payload = json.loads(messages[-1]["content"][-1]["text"])
        if "message_text" in payload:
            kind = "classification"
            if payload["message_text"] == "ordinary weather chat":
                result = {
                    "decision": "none",
                    "health_related": False,
                    "requires_source_verification": False,
                }
            else:
                result = {
                    "decision": "candidate",
                    "health_related": True,
                    "requires_source_verification": True,
                    "candidate": {
                        "evidence_kind": "direct_statement",
                        "source_message_id": payload["message_id"],
                        "source_utc": payload["message_utc"],
                        "excerpt": payload["message_text"],
                        "measurement": None,
                        "conclusions": [
                            {
                                "category": "state",
                                "dedupe_key": "abdominal-discomfort",
                                "text": "abdominal discomfort",
                                "status": "fact",
                                "priority": 3,
                            }
                        ],
                    },
                }
        elif "authorized_health_context" in payload:
            kind = "analysis"
            result = {
                "analysis_text": "当前紧凑画像可继续观察，并按需咨询医生。"
            }
        elif "current_turn" in payload:
            kind = "answer"
            result = {
                "answer_text": (
                    "Use the verified guidance and seek care if symptoms worsen."
                ),
                "used_source_card_ids": [
                    card["card_id"] for card in payload["fresh_source_cards"]
                ],
            }
        else:  # pragma: no cover - protects the production call contract
            raise AssertionError("unexpected pinned health-model payload")
        self.calls.append({"kind": kind, "payload": payload, "kwargs": kwargs})
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(result, ensure_ascii=False)
                    )
                )
            ],
            model="health-model-v1",
        )


class HealthPluginWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (HERMES_SOURCE / "gateway/platforms/weixin.py").is_file():
            raise unittest.SkipTest("Hermes mirror unavailable")
        sys.path.insert(0, str(HERMES_SOURCE))
        sys.path.insert(0, str(ROOT))
        spec = importlib.util.spec_from_file_location(
            "health_steward_plugin_under_test",
            PLUGIN_ROOT / "__init__.py",
            submodule_search_locations=[str(PLUGIN_ROOT)],
        )
        assert spec is not None and spec.loader is not None
        cls.plugin = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.plugin
        spec.loader.exec_module(cls.plugin)

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop("health_steward_plugin_under_test", None)
        sys.modules.pop("health_steward_plugin_under_test.weixin_adapter", None)
        for path in (str(ROOT), str(HERMES_SOURCE)):
            if path in sys.path:
                sys.path.remove(path)

    def test_builder_composes_pinned_answer_catalog_and_idempotent_channel(self):
        from gateway.config import PlatformConfig
        import hermes_cli
        from health_turn import HealthTurnHandler
        from owner_controls import PartnerOwnerControlHandler, PinnedHealthViewAnalyzer
        from sidecar.weixin_delivery import WeixinHealthChannel

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_config = root / "health-model.json"
            model_config.write_text(
                json.dumps(
                    {
                        "provider": "accepted-provider",
                        "endpoint": "https://accepted.example/v1",
                        "model_id": "health-model-v1",
                        "privacy_mode": "third-party-accepted",
                        "auth_profile": "partner",
                    }
                ),
                encoding="utf-8",
            )
            source_catalog = root / "health-sources.json"
            source_catalog.write_text(
                json.dumps(
                    {
                        "catalog_schema_version": 1,
                        "keyword_urls": {
                            "睡眠": "https://www.who.int/health-topics/sleep"
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            attestation_path = root / "health-model-attestation.json"
            export_tmpdir = root / "private-exports"
            if sys.platform.startswith("linux") and Path("/dev/shm").is_dir():
                export_tmpdir = Path("/dev/shm") / f"health-steward-test-{os.getpid()}-{id(self)}"
                self.addCleanup(
                    lambda: export_tmpdir.exists()
                    and shutil.rmtree(export_tmpdir)
                )
            export_tmpdir.mkdir(mode=0o700)
            env = {
                "HERMES_HOME": str(root / "hermes-home"),
                "HEALTH_STEWARD_SOURCE_ROOT": str(ROOT),
                "HEALTH_STEWARD_HERMES_SOURCE_ROOT": str(HERMES_SOURCE),
                "HEALTH_STEWARD_SOCKET": str(root / "health.sock"),
                "HEALTH_STEWARD_RECEIPT_SIGNER_SOCKET": str(root / "signer.sock"),
                "HEALTH_STEWARD_HEALTH_MODEL_CONFIG": str(model_config),
                "HEALTH_STEWARD_HEALTH_SOURCE_CATALOG": str(source_catalog),
                "HEALTH_STEWARD_EXPECTED_OWNER_SENDER_ID": "wx-owner",
                "HEALTH_STEWARD_EXPECTED_VIEWER_SENDER_ID": "wx-viewer",
                "HEALTH_STEWARD_ACCEPTED_HERMES_VERSION": str(
                    hermes_cli.__version__
                ),
                "HEALTH_STEWARD_DELIVERY_LEDGER_PATH": str(
                    root / "delivery.sqlite3"
                ),
                "HEALTH_STEWARD_HEALTH_MODEL_ATTESTATION_PATH": str(
                    attestation_path
                ),
                "HEALTH_STEWARD_EXPORT_TMPDIR": str(export_tmpdir),
            }
            if not sys.platform.startswith("linux"):
                env["HEALTH_STEWARD_TEST_MODE"] = "1"
            ctx = type(
                "Context",
                (),
                {"profile_name": "partner", "llm": object()},
            )()

            with mock.patch.dict(os.environ, env, clear=False), mock.patch(
                "sidecar.adapter.HealthSidecarClient"
            ):
                adapter = self.plugin._build_partner_weixin_adapter(
                    ctx,
                    PlatformConfig(
                        enabled=True,
                        token="test-token",
                        typing_indicator=False,
                        extra={
                            "account_id": "partner-bot",
                            "dm_policy": "allowlist",
                            "allow_from": ["wx-owner"],
                        },
                    ),
                )

            handler = adapter._health_turn_handler
            self.assertIsInstance(handler, HealthTurnHandler)
            self.assertIs(handler.context_loader, adapter._health_coordinator)
            self.assertIs(
                handler.source_reader,
                adapter._health_coordinator.adapter,
            )
            self.assertIsInstance(handler.channel, WeixinHealthChannel)
            controls = adapter._owner_control_handler
            self.assertIsInstance(controls, PartnerOwnerControlHandler)
            self.assertEqual(controls.expected_viewer_sender_id, "wx-viewer")
            self.assertEqual(adapter._dm_policy, "allowlist")
            self.assertEqual(adapter._allow_from, ["wx-owner", "wx-viewer"])
            self.assertIsInstance(controls.analyzer, PinnedHealthViewAnalyzer)
            self.assertIsNotNone(controls.export_store)
            self.assertIs(controls.channel, handler.channel)
            self.assertIs(controls.sidecar, handler.source_reader)
            self.assertEqual(
                handler.channel.ledger_path,
                root / "delivery.sqlite3",
            )
            self.assertEqual(
                handler.channel._profile_scope_id,
                hashlib.sha256(
                    b"health-profile-delivery-scope:v1:profile"
                ).hexdigest(),
            )
            attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
            self.assertEqual(
                attestation,
                {
                    "attestation_schema_version": 1,
                    "provider": "accepted-provider",
                    "endpoint": "https://accepted.example/v1",
                    "model_id": "health-model-v1",
                    "privacy_mode": "third-party-accepted",
                    "auth_profile": "partner",
                    "config_sha256": hashlib.sha256(
                        model_config.read_bytes()
                    ).hexdigest(),
                },
            )

    def test_daily_job_tool_delegates_the_capability_gated_attempt_to_sidecar(self):
        class Runtime:
            def __init__(self) -> None:
                self.execute_calls = 0

            def execute_daily_review(self, job_authorization):
                if job_authorization != "sidecar-job-authorization":
                    raise AssertionError("missing delegated Job authorization")
                self.execute_calls += 1
                return {"result": "no_action", "created_tasks": []}

        runtime = Runtime()
        with mock.patch.object(
            self.plugin,
            "_runtime_for_capability",
            return_value=(runtime, "sidecar-job-authorization"),
        ):
            result = self.plugin._handle_daily_review(
                {"capability": "one-time-capability"}
            )

        self.assertIn("no_action", result)
        self.assertEqual(runtime.execute_calls, 1)

    @unittest.skipUnless(
        hasattr(socket, "AF_UNIX") and hasattr(os, "getuid"),
        "Linux AF_UNIX peer identity required",
    )
    def test_scheduler_injected_fixed_job_ticks_close_production_plugin_model_socket_and_weixin(self):
        """Local Linux acceptance seam for both fixed Job roles, without core edits."""
        from health_model import HealthModelConfig
        from hermes_jobs import (
            DAILY_ROLE,
            DISPATCH_ROLE,
            fixed_job_specs,
            snapshot_for_role,
        )
        from sidecar import HealthSidecarServer
        from sidecar.production_ports import ProductionPortsFactory
        from sidecar.store import HealthSidecarStore
        from sidecar.weixin_delivery import DeliveryResult

        class FixedClock:
            def __init__(self) -> None:
                self.now = dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.timezone.utc)

            def now_utc(self):
                return self.now

        class Transport:
            runtime_version = "0.20.0"

            def __init__(self) -> None:
                self.calls: list[tuple[str, str, str]] = []

            def send_text(self, recipient, message, client_id):
                self.calls.append((str(recipient), str(message), str(client_id)))
                return DeliveryResult.accepted(str(client_id))

            def send_json_attachment(self, *_args):
                raise AssertionError("the fixed Job seam sends text only")

        class PinnedClient:
            def __init__(self, evidence_id: str) -> None:
                self.evidence_id = evidence_id
                self.calls: list[dict[str, object]] = []
                self.daily_attempts = 0
                self.retry_called = threading.Event()

            def complete_structured(self, **kwargs):
                self.calls.append(dict(kwargs))
                if kwargs["task"] == "health-daily-review":
                    self.daily_attempts += 1
                    if self.daily_attempts == 1:
                        raise RuntimeError("controlled-first-daily-failure")
                    self.retry_called.set()
                    parsed = {
                        "outcome": "tasks",
                        "tasks": [
                            {
                                "task_type": "status_follow_up",
                                "purpose": "follow up on sleep status",
                                "evidence_ids": [self.evidence_id],
                                "conclusion_keys": ["sleep"],
                                "time_window": {
                                    "start_utc": "2026-01-02T20:00:00Z",
                                    "end_utc": "2026-01-03T20:00:00Z",
                                },
                                "valid_until_utc": "2026-01-04T20:00:00Z",
                                "dedupe_key": "fixed-job-sleep-follow-up",
                                "timing_rationale": "owner time window",
                                "policy_constraints": {"low_risk": True},
                            }
                        ],
                    }
                elif kwargs["task"] == "health-dispatch":
                    parsed = {
                        "decision": "send",
                        "message": "最近睡眠怎么样？",
                        "reason": "follow-up",
                    }
                else:  # pragma: no cover - defends this primary seam contract
                    raise AssertionError(f"unexpected pinned task: {kwargs['task']!r}")
                return SimpleNamespace(parsed=parsed)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "health-model.json"
            config_path.write_text(
                json.dumps(
                    {
                        "provider": "custom",
                        "endpoint": "https://health-model.example/v1",
                        "model_id": "health-model-v1",
                        "privacy_mode": "isolated-health",
                        "auth_profile": "partner",
                    }
                ),
                encoding="utf-8",
            )
            key_path = root / "health-model.key"
            key_path.write_text("dedicated-sidecar-key\n", encoding="utf-8")
            key_path.chmod(0o600)
            token_path = root / "weixin.token"
            token_path.write_text("dedicated-weixin-token\n", encoding="utf-8")
            token_path.chmod(0o600)
            capability_path = root / "capability.key"
            capability_path.write_bytes(b"c" * 32)
            capability_path.chmod(0o600)
            job_authorization_path = root / "job-authorization.key"
            job_authorization_path.write_bytes(b"j" * 32)
            job_authorization_path.chmod(0o600)
            source_metadata = root / "source-metadata.json"
            source_metadata.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "documents": {
                            "https://www.who.int/health/sleep": {
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
                        },
                    }
                ),
                encoding="utf-8",
            )
            environment = {
                "HEALTH_STEWARD_SOURCE_ROOT": str(ROOT),
                "HEALTH_STEWARD_HEALTH_MODEL_CONFIG": str(config_path),
                "HEALTH_STEWARD_CAPABILITY_SECRET": str(capability_path),
                "HEALTH_STEWARD_JOB_AUTHORIZATION_SECRET": str(job_authorization_path),
                "HEALTH_STEWARD_SOCKET": str(root / "health.sock"),
                "HEALTH_STEWARD_SUBJECT": "profile",
                "HEALTH_STEWARD_TIMEZONE": "Asia/Shanghai",
                "HEALTH_SIDECAR_HEALTH_MODEL_CONFIG": str(config_path),
                "HEALTH_SIDECAR_HEALTH_MODEL_API_KEY_PATH": str(key_path),
                "HEALTH_SIDECAR_HERMES_SOURCE_ROOT": str(HERMES_SOURCE),
                "HEALTH_SIDECAR_ACCEPTED_HERMES_VERSION": "0.20.0",
                "HEALTH_SIDECAR_WEIXIN_TOKEN_PATH": str(token_path),
                "HEALTH_SIDECAR_WEIXIN_BASE_URL": "https://weixin.example/api",
                "HEALTH_SIDECAR_WEIXIN_CDN_BASE_URL": "https://weixin.example/cdn",
                "HEALTH_SIDECAR_DELIVERY_LEDGER_PATH": str(root / "delivery.sqlite3"),
                "HEALTH_SIDECAR_SOURCE_METADATA": str(source_metadata),
                "HEALTH_SIDECAR_MEMORY_PROJECTION_PATH": str(root / "memory.json"),
                "HEALTH_SIDECAR_SUBJECT": "profile",
            }
            clock = FixedClock()
            factory = ProductionPortsFactory.from_environment(environment)
            factory.clock = clock
            store = HealthSidecarStore(
                root / "state.sqlite.enc",
                root / "sidecar.key",
                clock=clock,
                key_manager=factory.key_manager,
            )
            owner = "wx-owner"
            owner_token = store.message_verifier.sign_owner_binding(
                subject="profile", owner_sender_id=owner
            )
            self.assertTrue(store.bind_profile_owner("profile", owner, owner_token))
            evidence_token = store.message_verifier.sign(
                subject="profile",
                sender_id=owner,
                message_id="fixed-job-evidence",
                message_utc="2026-01-02T19:55:00Z",
                message_text="最近睡眠不太好",
                evidence_kind="direct_statement",
            )
            store.stage_profile_message(
                "profile",
                owner,
                "fixed-job-evidence",
                "2026-01-02T19:55:00Z",
                "最近睡眠不太好",
                "direct_statement",
                evidence_token,
            )
            evidence = store.record_profile_candidate(
                "profile",
                owner,
                {
                    "evidence_kind": "direct_statement",
                    "source_message_id": "fixed-job-evidence",
                    "source_utc": "2026-01-02T19:55:00Z",
                    "excerpt": "最近睡眠不太好",
                    "conclusions": [
                        {
                            "category": "state",
                            "dedupe_key": "sleep",
                            "text": "睡眠不佳",
                            "status": "fact",
                            "priority": 80,
                        }
                    ],
                },
            )
            pinned = PinnedClient(str(evidence["evidence_id"]))
            transport = Transport()
            with mock.patch(
                "sidecar.production_ports._ensure_pinned_hermes_source"
            ), mock.patch(
                "sidecar.production_ports.PinnedHealthModelClient",
                return_value=pinned,
            ), mock.patch(
                "sidecar.production_ports.HermesWeixinTransport.from_hermes_source",
                return_value=transport,
            ):
                ports = factory.build(store)
            ready = threading.Event()
            server = HealthSidecarServer(
                root / "health.sock",
                store,
                allowed_uids={os.getuid()},
                ready_event=ready,
                ports=ports,
                projection_subject="profile",
                job_authorization_secret=job_authorization_path.read_bytes(),
            )
            thread = threading.Thread(target=server.run_forever, daemon=True)
            thread.start()
            self.assertTrue(ready.wait(timeout=3))
            model_config = HealthModelConfig.from_file(config_path)
            records = [
                spec.to_job_record(f"{spec.role}-id")
                for spec in fixed_job_specs(model_config)
            ]
            cron_module = types.ModuleType("cron")
            cron_jobs = types.ModuleType("cron.jobs")
            cron_scheduler = types.ModuleType("cron.scheduler")
            cron_jobs.list_jobs = lambda include_disabled=True: records
            cron_scheduler._runtime_job_fingerprint = (
                lambda record: f"fingerprint:{record['id']}"
            )
            cron_module.jobs = cron_jobs
            cron_module.scheduler = cron_scheduler
            try:
                with mock.patch.dict(os.environ, environment, clear=False), mock.patch.dict(
                    sys.modules,
                    {"cron": cron_module, "cron.jobs": cron_jobs, "cron.scheduler": cron_scheduler},
                ), mock.patch("sidecar.store.SystemClock", return_value=clock):
                    daily = next(record for record in records if record["name"] == "health-daily-profile-review")
                    os.environ["HERMES_CRON_JOB_ID"] = daily["id"]
                    os.environ["HERMES_CRON_JOB_FINGERPRINT"] = f"fingerprint:{daily['id']}"
                    daily_tick = snapshot_for_role(DAILY_ROLE)
                    self.assertEqual(daily_tick["snapshot"], {"action": "health_daily_review", "authority": "sidecar-current-snapshot"})
                    self.assertIn("failed", self.plugin._handle_daily_review({"capability": daily_tick["capability"]}))
                    clock.now = dt.datetime(2026, 1, 2, 20, 10, tzinfo=dt.timezone.utc)
                    self.assertIsNotNone(server.daily_executor)

                    dispatch = next(record for record in records if record["name"] == "health-due-task-dispatch")
                    os.environ["HERMES_CRON_JOB_ID"] = dispatch["id"]
                    os.environ["HERMES_CRON_JOB_FINGERPRINT"] = f"fingerprint:{dispatch['id']}"
                    dispatch_tick = snapshot_for_role(DISPATCH_ROLE)
                    self.assertEqual(dispatch_tick["snapshot"]["action"], "health_dispatch_due_tasks")
                    # The five-minute fixed dispatcher supplies the fresh
                    # authenticated Gateway lease that allows the sidecar's
                    # persisted +10 minute retry to run.  No third Cron is
                    # created for the retry.
                    self.assertIn("sent", self.plugin._handle_dispatch({"capability": dispatch_tick["capability"]}))
                    self.assertTrue(pinned.retry_called.wait(timeout=3))

                    clock.now = dt.datetime(2026, 1, 2, 20, 15, tzinfo=dt.timezone.utc)
                    dispatch_tick = snapshot_for_role(DISPATCH_ROLE)
                    self.assertEqual(dispatch_tick["snapshot"]["action"], "health_dispatch_due_tasks")
                    self.assertIn("sent", self.plugin._handle_dispatch({"capability": dispatch_tick["capability"]}))
            finally:
                server.stop()
                thread.join(timeout=3)

            self.assertEqual(
                [call["task"] for call in pinned.calls],
                ["health-daily-review", "health-daily-review", "health-dispatch"],
            )
            self.assertEqual(len(transport.calls), 1)
            recipient, message, delivery_id = transport.calls[0]
            self.assertEqual((recipient, message), (owner, "最近睡眠怎么样？"))
            self.assertTrue(delivery_id.startswith("hermes-health-"))

    @unittest.skipUnless(hasattr(socket, "AF_UNIX"), "AF_UNIX required")
    def test_builder_closes_one_reactive_turn_through_production_seams(self):
        from agent.plugin_llm import PluginLlm, _TrustPolicy
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        from gateway.config import PlatformConfig
        import hermes_cli
        from health_turn import (
            SOURCE_VERIFYING_MESSAGE,
            HealthSourceCatalog,
            HealthTurnHandler,
        )
        from health_turn_answer import PinnedHealthTurnResponder
        from sidecar.adapter import PartnerHealthAdapter
        from sidecar.receipt_signer import (
            Ed25519ReceiptSigner,
            ReceiptSignerClient,
            ReceiptSignerServer,
        )
        from sidecar.server import HealthSidecarServer
        from sidecar.store import (
            Ed25519InboundMessageVerifier,
            HealthSidecarStore,
        )
        from sidecar.weixin_delivery import (
            HermesWeixinTransport,
            WeixinHealthChannel,
        )
        from weixin_ingress import (
            EXPLICIT_ENABLE_PHRASES,
            PROFILE_UPDATED_MARKER,
            HermesFreshHealthClassifier,
        )

        owner = "wx-owner"
        subject = "profile"
        source_url = "https://www.who.int/health-topics/abdominal-pain"
        private = Ed25519PrivateKey.generate()
        private_bytes = private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        public_bytes = private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        peer_uid = os.getuid() if hasattr(os, "getuid") else 1001
        peer_gid = os.getgid() if hasattr(os, "getgid") else 1001
        peer_patchers: list[mock._patch] = []
        if not hasattr(socket, "SO_PEERCRED"):
            peer_patchers.extend(
                [
                    mock.patch("sidecar.server._peer_uid", return_value=peer_uid),
                    mock.patch("sidecar.server._peer_gid", return_value=peer_gid),
                    mock.patch(
                        "sidecar.receipt_signer._peer_pid_uid",
                        return_value=(os.getpid(), peer_uid),
                    ),
                ]
            )
        for patcher in peer_patchers:
            patcher.start()

        def stop_and_join(server, thread, method_name: str) -> None:
            getattr(server, method_name)()
            thread.join(2)
            self.assertFalse(
                thread.is_alive(), f"{method_name} server thread did not stop"
            )

        try:
            with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as cleanup:
                root = Path(temp)
                sidecar_socket = root / "health.sock"
                signer_socket = root / "signer.sock"
                ready = threading.Event()

                class SourceFetch:
                    def __init__(self) -> None:
                        self.calls: list[tuple[str, float | None]] = []

                    def fetch(self, url, timeout_seconds=None):
                        self.calls.append((url, timeout_seconds))
                        return {
                            "url": url,
                            "version_hash": "who-abdominal-v1",
                            "source_type": "general_health_education",
                            "title": "Abdominal discomfort guidance",
                            "tags": {
                                "topic": ["digestive health"],
                                "symptom_behavior": ["abdominal discomfort"],
                                "target_population": ["adult"],
                                "evidence_type": ["health education"],
                                "region_language": ["global-zh"],
                                "freshness": ["current"],
                            },
                            "key_excerpt": (
                                "Seek care for severe or worsening symptoms."
                            ),
                            "raw_document": b"controlled public health source",
                        }

                class RecordingMemoryProjection:
                    def __init__(self) -> None:
                        self.replacements: list[tuple[str, dict[str, object]]] = []
                        self.removals: list[str] = []

                    def replace_health_projection(self, subject_id, projection):
                        self.replacements.append(
                            (str(subject_id), dict(projection))
                        )
                        return True

                    def remove_health_projection(self, subject_id):
                        self.removals.append(str(subject_id))
                        return True

                source_fetch = SourceFetch()
                memory_projection = RecordingMemoryProjection()
                store = HealthSidecarStore(
                    root / "state.enc",
                    root / "state.key",
                    message_verifier=Ed25519InboundMessageVerifier(public_bytes),
                    expected_owner_sender_id=owner,
                    expected_viewer_sender_id="wx-viewer",
                )
                sidecar_server = HealthSidecarServer(
                    str(sidecar_socket),
                    store,
                    allowed_uids={peer_uid},
                    allowed_gids={peer_gid},
                    ready_event=ready,
                    ports=SimpleNamespace(
                        source_fetch=source_fetch,
                        memory_projection=None,
                    ),
                    memory_projection=memory_projection,
                    projection_subject=subject,
                )
                sidecar_thread = threading.Thread(
                    target=sidecar_server.run_forever,
                    daemon=True,
                )
                sidecar_thread.start()
                cleanup.callback(
                    stop_and_join, sidecar_server, sidecar_thread, "stop"
                )
                self.assertTrue(ready.wait(5), "sidecar did not become ready")

                signer_server = ReceiptSignerServer(
                    str(signer_socket),
                    Ed25519ReceiptSigner(private_bytes),
                    allowed_gateway_pid=os.getpid(),
                    allowed_gateway_uid=peer_uid,
                )
                signer_thread = threading.Thread(
                    target=signer_server.serve_forever,
                    daemon=True,
                )
                signer_thread.start()
                cleanup.callback(
                    stop_and_join, signer_server, signer_thread, "close"
                )
                for _ in range(100):
                    if signer_socket.exists():
                        break
                    threading.Event().wait(0.01)
                self.assertTrue(signer_socket.exists(), "signer did not become ready")

                model_config = root / "health-model.json"
                model_config.write_text(
                    json.dumps(
                        {
                            "provider": "accepted-provider",
                            "endpoint": "https://accepted.example/v1",
                            "model_id": "health-model-v1",
                            "privacy_mode": "third-party-accepted",
                            "auth_profile": "partner",
                        }
                    ),
                    encoding="utf-8",
                )
                source_catalog = root / "health-sources.json"
                source_catalog.write_text(
                    json.dumps(
                        {
                            "catalog_schema_version": 1,
                            "keyword_urls": {"abdominal": source_url},
                        }
                    ),
                    encoding="utf-8",
                )
                export_tmpdir = root / "private-exports"
                if sys.platform.startswith("linux") and Path("/dev/shm").is_dir():
                    export_tmpdir = Path("/dev/shm") / (
                        f"health-steward-test-{os.getpid()}-{id(self)}-production"
                    )
                    self.addCleanup(
                        lambda: export_tmpdir.exists()
                        and shutil.rmtree(export_tmpdir)
                    )
                export_tmpdir.mkdir(mode=0o700)
                env = {
                    "HERMES_HOME": str(root / "hermes-home"),
                    "HEALTH_STEWARD_SOURCE_ROOT": str(ROOT),
                    "HEALTH_STEWARD_HERMES_SOURCE_ROOT": str(HERMES_SOURCE),
                    "HEALTH_STEWARD_SOCKET": str(sidecar_socket),
                    "HEALTH_STEWARD_RECEIPT_SIGNER_SOCKET": str(signer_socket),
                    "HEALTH_STEWARD_HEALTH_MODEL_CONFIG": str(model_config),
                    "HEALTH_STEWARD_HEALTH_SOURCE_CATALOG": str(source_catalog),
                    "HEALTH_STEWARD_EXPECTED_OWNER_SENDER_ID": owner,
                    "HEALTH_STEWARD_EXPECTED_VIEWER_SENDER_ID": "wx-viewer",
                    "HEALTH_STEWARD_ACCEPTED_HERMES_VERSION": str(
                        hermes_cli.__version__
                    ),
                    "HEALTH_STEWARD_DELIVERY_LEDGER_PATH": str(
                        root / "delivery.sqlite3"
                    ),
                    "HEALTH_STEWARD_HEALTH_MODEL_ATTESTATION_PATH": str(
                        root / "health-model-attestation.json"
                    ),
                    "HEALTH_STEWARD_EXPORT_TMPDIR": str(export_tmpdir),
                }
                if not sys.platform.startswith("linux"):
                    env["HEALTH_STEWARD_TEST_MODE"] = "1"
                policy = _TrustPolicy(
                    plugin_id="health-steward",
                    allow_provider_override=True,
                    allowed_providers=frozenset({"accepted-provider"}),
                    allow_model_override=True,
                    allowed_models=frozenset({"health-model-v1"}),
                    allow_profile_override=True,
                )
                plugin_llm = PluginLlm(
                    plugin_id="health-steward",
                    policy_loader=lambda _plugin_id: policy,
                )
                ctx = SimpleNamespace(profile_name="partner", llm=plugin_llm)
                completions = RecordingPinnedCompletions()
                remote_client = SimpleNamespace(
                    base_url="https://accepted.example/v1",
                    chat=SimpleNamespace(completions=completions),
                )
                client_resolutions: list[tuple[str, str, str | None]] = []

                def resolve_pinned_client(provider, model, *, base_url=None):
                    client_resolutions.append((provider, model, base_url))
                    return remote_client, "health-model-v1"

                weixin_calls: list[dict[str, object]] = []

                async def fake_send_message(_session, **kwargs):
                    weixin_calls.append(dict(kwargs))
                    return {"ret": 0}

                async def fake_get_config(_session, **_kwargs):
                    return {"ret": 0}

                config = PlatformConfig(
                    enabled=True,
                    token="test-token",
                    typing_indicator=False,
                    extra={
                        "account_id": "partner-bot",
                        "dm_policy": "allowlist",
                        "allow_from": [owner, "wx-viewer", "wx-admin"],
                        "text_batch_delay_seconds": 30,
                    },
                )
                with mock.patch.dict(os.environ, env, clear=False), mock.patch(
                    "agent.auxiliary_client._get_cached_client",
                    side_effect=resolve_pinned_client,
                ), mock.patch(
                    "agent.auxiliary_client.call_llm"
                ) as fallback_call, mock.patch(
                    "gateway.platforms.weixin._send_message",
                    new=fake_send_message,
                ), mock.patch(
                    "gateway.platforms.weixin._get_config",
                    new=fake_get_config,
                ):
                    adapter = self.plugin._build_partner_weixin_adapter(ctx, config)
                    coordinator = adapter._health_coordinator
                    handler = adapter._health_turn_handler
                    self.assertIsInstance(coordinator.adapter, PartnerHealthAdapter)
                    self.assertIsInstance(coordinator.signer, ReceiptSignerClient)
                    self.assertIsInstance(
                        coordinator.classifier, HermesFreshHealthClassifier
                    )
                    self.assertIsInstance(handler, HealthTurnHandler)
                    self.assertIsInstance(
                        handler.responder, PinnedHealthTurnResponder
                    )
                    self.assertIsInstance(handler.source_catalog, HealthSourceCatalog)
                    self.assertIsInstance(handler.channel, WeixinHealthChannel)
                    self.assertIsInstance(
                        handler.channel.transport, HermesWeixinTransport
                    )
                    self.assertIs(handler.context_loader, coordinator)
                    self.assertIs(handler.source_reader, coordinator.adapter)
                    self.assertIs(
                        coordinator.classifier.config,
                        handler.responder.config,
                    )
                    self.assertIs(
                        coordinator.classifier.plugin_llm,
                        handler.responder.plugin_llm,
                    )
                    adapter._poll_session = object()

                    async def exercise_body() -> None:
                        async def wait_for(predicate, label: str) -> None:
                            for _ in range(300):
                                if predicate():
                                    return
                                await asyncio.sleep(0.01)
                            self.fail(f"timed out waiting for {label}")

                        current_contexts: list[dict[str, object]] = []
                        load_current_context = (
                            coordinator.load_health_turn_context
                        )

                        def record_current_context(envelope):
                            current = dict(load_current_context(envelope))
                            current_contexts.append(current)
                            return current

                        with mock.patch.object(
                            coordinator,
                            "load_health_turn_context",
                            side_effect=record_current_context,
                        ) as context_read:
                            consent_event = {
                                "from_user_id": owner,
                                "to_user_id": "partner-bot",
                                "message_id": "consent-production-1",
                                "item_list": [
                                    {
                                        "type": 1,
                                        "text_item": {
                                            "text": next(
                                                iter(EXPLICIT_ENABLE_PHRASES)
                                            )
                                        },
                                    }
                                ],
                            }
                            await adapter._process_message(consent_event)
                            await wait_for(
                                lambda: coordinator.adapter.health_recording_enabled(
                                    subject, owner
                                ),
                                "health recording consent",
                            )
                            self.assertEqual(completions.calls, [])

                            # Consent is an ordinary control message and is
                            # therefore natively batched. Drain it so this seam
                            # can distinguish the following health/ordinary turns.
                            batch_tasks = list(
                                adapter._pending_text_batch_tasks.values()
                            )
                            for task in batch_tasks:
                                task.cancel()
                            if batch_tasks:
                                await asyncio.gather(
                                    *batch_tasks, return_exceptions=True
                                )
                            adapter._pending_text_batches.clear()
                            adapter._pending_text_batch_tasks.clear()

                            health_event = {
                                "from_user_id": owner,
                                "to_user_id": "partner-bot",
                                "message_id": "health-production-1",
                                "item_list": [
                                    {
                                        "type": 1,
                                        "text_item": {
                                            "text": (
                                                "I have abdominal discomfort; "
                                                "what should I do?"
                                            )
                                        },
                                    }
                                ],
                            }
                            await adapter._process_message(health_event)
                            await wait_for(
                                lambda: len(weixin_calls) == 2
                                and [
                                    call["kind"] for call in completions.calls
                                ]
                                == ["classification", "answer"],
                                "health answer delivery",
                            )
                            self.assertEqual(context_read.call_count, 1)
                            self.assertEqual(len(current_contexts), 1)
                            self.assertEqual(adapter._pending_text_batches, {})
                            self.assertEqual(
                                source_fetch.calls, [(source_url, 20.0)]
                            )
                            self.assertEqual(
                                weixin_calls[0]["text"], SOURCE_VERIFYING_MESSAGE
                            )
                            self.assertIn(
                                "Use the verified guidance",
                                str(weixin_calls[1]["text"]),
                            )
                            self.assertIn(
                                PROFILE_UPDATED_MARKER,
                                str(weixin_calls[1]["text"]),
                            )

                            read_utc = dt.datetime.now(
                                dt.timezone.utc
                            ).replace(microsecond=0).isoformat()
                            read_token = coordinator.signer.sign_access(
                                action="health.profile.read",
                                subject=subject,
                                actor_sender_id=owner,
                                target_sender_id=owner,
                                message_id="read-production-1",
                                message_utc=read_utc,
                            )
                            profile = coordinator.adapter.read_profile(
                                subject,
                                owner,
                                "read-production-1",
                                read_utc,
                                read_token,
                            )
                            answer_payload = completions.calls[1]["payload"]
                            current_context = current_contexts[0]
                            self.assertEqual(
                                current_context["current_version_id"],
                                profile["current_version_id"],
                            )
                            self.assertEqual(
                                current_context["evidence_ids"],
                                [profile["evidence"][0]["evidence_id"]],
                            )
                            self.assertEqual(
                                answer_payload["relevant_evidence_ids"],
                                current_context["evidence_ids"],
                            )
                            self.assertEqual(
                                current_context["profile_summary_zh"],
                                profile["profile_summary_zh"],
                            )
                            self.assertEqual(
                                answer_payload["profile_summary_zh"],
                                current_context["profile_summary_zh"],
                            )
                            self.assertLessEqual(
                                len(current_context["profile_summary_zh"]), 300
                            )
                            self.assertNotIn(
                                "current_version_id", answer_payload
                            )
                            self.assertEqual(
                                profile["evidence"][0]["source_message_id"],
                                "health-production-1",
                            )
                            self.assertEqual(
                                len(answer_payload["fresh_source_cards"]), 1
                            )
                            answer_card = answer_payload[
                                "fresh_source_cards"
                            ][0]
                            self.assertEqual(
                                {
                                    "title": answer_card["title"],
                                    "source_url": answer_card["source_url"],
                                    "summary_zh": answer_card["summary_zh"],
                                    "untrusted_data": answer_card[
                                        "untrusted_data"
                                    ],
                                },
                                {
                                    "title": "Abdominal discomfort guidance",
                                    "source_url": source_url,
                                    "summary_zh": (
                                        "Seek care for severe or worsening "
                                        "symptoms."
                                    ),
                                    "untrusted_data": True,
                                },
                            )
                            source_view = coordinator.adapter.query_sources(
                                "abdominal discomfort"
                            )
                            self.assertTrue(source_view["verified"])
                            self.assertEqual(source_view["source"], "card")
                            self.assertEqual(len(source_view["cards"]), 1)
                            stored_card = source_view["cards"][0]
                            self.assertEqual(
                                answer_card["card_id"], stored_card["card_id"]
                            )
                            self.assertEqual(stored_card["url"], source_url)
                            self.assertEqual(
                                stored_card["key_excerpt"],
                                answer_card["summary_zh"],
                            )
                            self.assertIs(
                                stored_card["untrusted_data"], True
                            )
                            self.assertEqual(
                                source_fetch.calls, [(source_url, 20.0)]
                            )

                            # The owner-only natural-language control stays on
                            # the authenticated partner plugin path.  Its full
                            # view is read through the production socket and
                            # delivered directly to Weixin without another
                            # model turn or an ordinary text batch.
                            prior_model_calls = len(completions.calls)
                            prior_context_reads = len(current_contexts)
                            prior_source_calls = len(source_fetch.calls)
                            prior_weixin_calls = len(weixin_calls)
                            prior_projection_writes = len(
                                memory_projection.replacements
                            )
                            owner_view_event = {
                                "from_user_id": owner,
                                "to_user_id": "partner-bot",
                                "message_id": "owner-view-production-1",
                                "item_list": [
                                    {
                                        "type": 1,
                                        "text_item": {
                                            "text": "查看我的完整健康档案"
                                        },
                                    }
                                ],
                            }
                            await adapter._process_message(owner_view_event)
                            await wait_for(
                                lambda: len(weixin_calls) > prior_weixin_calls,
                                "owner private view delivery",
                            )
                            await wait_for(
                                lambda: not adapter._background_tasks,
                                "owner private view completion",
                            )
                            view_texts = [
                                str(call["text"])
                                for call in weixin_calls[prior_weixin_calls:]
                            ]
                            if len(view_texts) == 1:
                                serialized_view = view_texts[0]
                            else:
                                serialized_view = "".join(
                                    part.split("\n", 1)[1]
                                    for part in view_texts
                                )
                            private_view = json.loads(serialized_view)
                            self.assertEqual(
                                private_view["view_schema_version"], 1
                            )
                            self.assertEqual(
                                private_view["health_view"]["subject"], subject
                            )
                            self.assertEqual(
                                private_view["health_view"]["role"], "owner"
                            )
                            self.assertEqual(
                                private_view["health_view"]["profile"][
                                    "evidence"
                                ][0]["source_message_id"],
                                "health-production-1",
                            )
                            self.assertEqual(
                                len(completions.calls), prior_model_calls
                            )
                            self.assertEqual(
                                len(current_contexts), prior_context_reads
                            )
                            self.assertEqual(
                                len(source_fetch.calls), prior_source_calls
                            )
                            self.assertEqual(
                                len(memory_projection.replacements),
                                prior_projection_writes,
                            )
                            self.assertEqual(adapter._pending_text_batches, {})

                            receipt_utc = dt.datetime.now(
                                dt.timezone.utc
                            ).replace(microsecond=0).isoformat()
                            receipt_token = coordinator.signer.sign_access(
                                action="health.access.read",
                                subject=subject,
                                actor_sender_id=owner,
                                target_sender_id=owner,
                                message_id="receipt-production-1",
                                message_utc=receipt_utc,
                            )
                            with self.assertRaisesRegex(
                                RuntimeError, "unverified-access-receipt"
                            ):
                                coordinator.adapter.read_authorized_view(
                                    subject,
                                    owner,
                                    "receipt-production-tampered",
                                    receipt_utc,
                                    receipt_token,
                                )
                            receipt_view = (
                                coordinator.adapter.read_authorized_view(
                                    subject,
                                    owner,
                                    "receipt-production-1",
                                    receipt_utc,
                                    receipt_token,
                                )
                            )
                            self.assertEqual(receipt_view["role"], "owner")
                            with self.assertRaisesRegex(
                                RuntimeError, "access-receipt-replayed"
                            ):
                                coordinator.adapter.read_authorized_view(
                                    subject,
                                    owner,
                                    "receipt-production-1",
                                    receipt_utc,
                                    receipt_token,
                                )
                            self.assertEqual(
                                len(completions.calls), prior_model_calls
                            )
                            self.assertEqual(
                                len(memory_projection.replacements),
                                prior_projection_writes,
                            )

                            async def send_private_control(
                                sender_id: str,
                                message_id: str,
                                text: str,
                                label: str,
                            ) -> list[str]:
                                before = len(weixin_calls)
                                await adapter._process_message(
                                    {
                                        "from_user_id": sender_id,
                                        "to_user_id": "partner-bot",
                                        "message_id": message_id,
                                        "item_list": [
                                            {
                                                "type": 1,
                                                "text_item": {"text": text},
                                            }
                                        ],
                                    }
                                )
                                await wait_for(
                                    lambda: len(weixin_calls) > before,
                                    label,
                                )
                                await wait_for(
                                    lambda: not adapter._background_tasks,
                                    f"{label} completion",
                                )
                                return [
                                    str(call["text"])
                                    for call in weixin_calls[before:]
                                ]

                            def joined_control(parts: list[str]) -> str:
                                if len(parts) == 1 and not parts[0].startswith(
                                    "【"
                                ):
                                    return parts[0]
                                return "".join(
                                    part.split("\n", 1)[1] for part in parts
                                )

                            grant_reply = joined_control(
                                await send_private_control(
                                    owner,
                                    "owner-grant-production-1",
                                    "授权预配置查看者查看健康档案",
                                    "viewer grant",
                                )
                            )
                            self.assertIn("查看授权已生效", grant_reply)

                            viewer_view = joined_control(
                                await send_private_control(
                                    "wx-viewer",
                                    "viewer-view-production-1",
                                    "查看完整健康档案",
                                    "viewer private view",
                                )
                            )
                            viewer_payload = json.loads(viewer_view)
                            self.assertEqual(
                                viewer_payload["health_view"]["role"], "viewer"
                            )
                            self.assertEqual(
                                viewer_payload["health_view"]["profile"][
                                    "evidence"
                                ][0]["source_message_id"],
                                "health-production-1",
                            )

                            tampered_target = joined_control(
                                await send_private_control(
                                    owner,
                                    "owner-grant-admin-production-1",
                                    "授权 wx-admin 查看我的健康档案",
                                    "unconfigured target rejection",
                                )
                            )
                            self.assertIn("授权未更改", tampered_target)
                            admin_weixin_before = len(weixin_calls)
                            admin_model_before = len(completions.calls)
                            await adapter._process_message(
                                {
                                    "from_user_id": "wx-admin",
                                    "to_user_id": "partner-bot",
                                    "message_id": "admin-view-production-1",
                                    "item_list": [
                                        {
                                            "type": 1,
                                            "text_item": {
                                                "text": "查看完整健康档案"
                                            },
                                        }
                                    ],
                                }
                            )
                            await asyncio.sleep(0)
                            self.assertEqual(
                                len(weixin_calls), admin_weixin_before
                            )
                            self.assertEqual(
                                len(completions.calls), admin_model_before
                            )
                            self.assertEqual(adapter._pending_text_batches, {})

                            analysis_calls_before = len(completions.calls)
                            viewer_analysis = joined_control(
                                await send_private_control(
                                    "wx-viewer",
                                    "viewer-analysis-production-1",
                                    "请用健康模型分析我的当前健康画像",
                                    "viewer explicit analysis",
                                )
                            )
                            self.assertIn("继续观察", viewer_analysis)
                            self.assertEqual(
                                len(completions.calls), analysis_calls_before + 1
                            )
                            self.assertEqual(
                                completions.calls[-1]["kind"], "analysis"
                            )
                            self.assertEqual(
                                completions.calls[-1]["payload"][
                                    "authorized_health_context"
                                ]["role"],
                                "viewer",
                            )

                            revoke_reply = joined_control(
                                await send_private_control(
                                    owner,
                                    "owner-revoke-production-1",
                                    "撤回预配置查看者的健康档案查看权限",
                                    "viewer revoke",
                                )
                            )
                            self.assertIn("查看授权已撤回", revoke_reply)
                            denied_after_revoke = joined_control(
                                await send_private_control(
                                    "wx-viewer",
                                    "viewer-view-production-2",
                                    "查看完整健康档案",
                                    "revoked viewer rejection",
                                )
                            )
                            self.assertIn("未获授权", denied_after_revoke)
                            model_calls_after_revoke = len(completions.calls)
                            denied_analysis = joined_control(
                                await send_private_control(
                                    "wx-viewer",
                                    "viewer-analysis-production-2",
                                    "请用健康模型分析我的当前健康画像",
                                    "revoked viewer analysis rejection",
                                )
                            )
                            self.assertIn("未获授权", denied_analysis)
                            self.assertEqual(
                                len(completions.calls), model_calls_after_revoke
                            )
                            self.assertEqual(adapter._pending_text_batches, {})
                            self.assertEqual(
                                len(memory_projection.replacements),
                                prior_projection_writes,
                            )
                            audit_events = coordinator.adapter.read_audit()
                            serialized_audit = json.dumps(
                                audit_events,
                                ensure_ascii=False,
                                sort_keys=True,
                            )
                            for private_text in (
                                "abdominal discomfort",
                                "Use the verified guidance",
                                "继续观察",
                            ):
                                self.assertNotIn(
                                    private_text, serialized_audit
                                )
                            self.assertTrue(
                                any(
                                    event.get("event") == "access_grant"
                                    for event in audit_events
                                )
                            )
                            self.assertTrue(
                                any(
                                    event.get("event") == "access_revoke"
                                    for event in audit_events
                                )
                            )

                            prior_context_reads = len(current_contexts)
                            prior_source_calls = len(source_fetch.calls)
                            prior_weixin_calls = len(weixin_calls)
                            prior_model_calls = len(completions.calls)
                            ordinary_event = {
                                "from_user_id": owner,
                                "to_user_id": "partner-bot",
                                "message_id": "ordinary-production-1",
                                "item_list": [
                                    {
                                        "type": 1,
                                        "text_item": {
                                            "text": "ordinary weather chat"
                                        },
                                    }
                                ],
                            }
                            await adapter._process_message(ordinary_event)
                            await wait_for(
                                lambda: len(completions.calls)
                                == prior_model_calls + 1
                                and bool(adapter._pending_text_batches),
                                "ordinary native batch",
                            )
                            self.assertEqual(
                                [call["kind"] for call in completions.calls],
                                [
                                    "classification",
                                    "answer",
                                    "analysis",
                                    "classification",
                                ],
                            )
                            self.assertEqual(
                                len(current_contexts), prior_context_reads
                            )
                            self.assertEqual(
                                len(source_fetch.calls), prior_source_calls
                            )
                            self.assertEqual(len(weixin_calls), prior_weixin_calls)
                            pending = next(
                                iter(adapter._pending_text_batches.values())
                            )
                            self.assertEqual(pending.text, "ordinary weather chat")
                            metadata_text = json.dumps(
                                pending.metadata,
                                ensure_ascii=False,
                                sort_keys=True,
                            )
                            for forbidden in (
                                "profile_summary_zh",
                                "evidence_ids",
                                "source_cards",
                                "abdominal discomfort",
                            ):
                                self.assertNotIn(forbidden, metadata_text)

                            for call in completions.calls:
                                kwargs = call["kwargs"]
                                self.assertEqual(kwargs["model"], "health-model-v1")
                                self.assertEqual(len(kwargs["messages"]), 2)
                                self.assertNotIn("tools", kwargs)
                                self.assertEqual(
                                    kwargs["extra_body"]["metadata"][
                                        "auth_profile"
                                    ],
                                    "partner",
                                )
                            self.assertEqual(
                                client_resolutions,
                                [
                                    (
                                        "accepted-provider",
                                        "health-model-v1",
                                        "https://accepted.example/v1",
                                    )
                                ]
                                * 4,
                            )
                            fallback_call.assert_not_called()

                            pending_tasks = list(
                                adapter._pending_text_batch_tasks.values()
                            )
                            for task in pending_tasks:
                                task.cancel()
                            if pending_tasks:
                                await asyncio.gather(
                                    *pending_tasks, return_exceptions=True
                                )

                    async def exercise() -> None:
                        try:
                            await exercise_body()
                        finally:
                            pending_tasks = set(
                                adapter._pending_text_batch_tasks.values()
                            )
                            pending_tasks.update(adapter._background_tasks)
                            pending_tasks.update(
                                adapter._health_retry_tasks.values()
                            )
                            pending_tasks.discard(asyncio.current_task())
                            for task in pending_tasks:
                                task.cancel()
                            if pending_tasks:
                                await asyncio.gather(
                                    *pending_tasks, return_exceptions=True
                                )
                            adapter._pending_text_batches.clear()
                            adapter._pending_text_batch_tasks.clear()

                    asyncio.run(exercise())
        finally:
            for patcher in reversed(peer_patchers):
                patcher.stop()

if __name__ == "__main__":
    unittest.main()

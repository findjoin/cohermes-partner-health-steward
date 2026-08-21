from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermes_jobs import (  # noqa: E402
    DISPATCH_JOB_NAME,
    DAILY_ROLE,
    DAILY_JOB_NAME,
    FixedJobConfigurationError,
    JobRuntime,
    fixed_job_specs,
    ensure_capability_secret,
    install_fixed_jobs,
    issue_job_capability,
    job_matches_spec,
    snapshot_for_role,
    verify_job_capability,
    verify_runtime_job,
)
from health_model import HealthModelConfig  # noqa: E402


class FakeClock:
    def __init__(self, now: dt.datetime):
        self.now = now

    def now_utc(self) -> dt.datetime:
        return self.now


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def daily_review_snapshot(self, subject, review_utc, timezone):
        self.calls.append(("daily_snapshot", subject, review_utc, timezone))
        return {"profile": {"version_id": "v1"}, "evidence": []}

    def run_daily_review(self, subject, review_utc, timezone, plan):
        self.calls.append(("daily_apply", subject, review_utc, timezone, plan))
        return {"result": "no_action", "created_tasks": []}

    def execute_daily_review(self, subject, review_utc, timezone, job_authorization):
        self.calls.append(("daily_execute", subject, review_utc, timezone, job_authorization))
        return {"result": "no_action", "created_tasks": []}

    def dispatch_due_tasks(self, subject, now_utc, job_authorization):
        self.calls.append(("dispatch", subject, now_utc, job_authorization))
        return {"processed": [], "sent": [], "skipped": []}


class FakeCronBackend:
    def __init__(self, jobs=None):
        self.jobs = [dict(job) for job in (jobs or [])]
        self.created = []

    def list_jobs(self, include_disabled=True):
        del include_disabled
        return [dict(job) for job in self.jobs]

    def create_job(self, **kwargs):
        job = {"id": f"job-{len(self.jobs) + 1}", **kwargs}
        self.jobs.append(job)
        self.created.append(dict(job))
        return dict(job)


class HermesJobsContractTests(unittest.TestCase):
    @staticmethod
    def health_model_config() -> HealthModelConfig:
        return HealthModelConfig(
            provider="custom",
            endpoint="https://health-model.example/v1",
            model_id="health-model-v1",
            privacy_mode="isolated-health",
            auth_profile="partner-health",
        )

    def test_contract_contains_exactly_two_fixed_jobs(self):
        specs = fixed_job_specs()
        self.assertEqual(len(specs), 2)
        self.assertEqual({spec.name for spec in specs}, {DAILY_JOB_NAME, DISPATCH_JOB_NAME})
        by_name = {spec.name: spec for spec in specs}
        self.assertEqual(by_name[DAILY_JOB_NAME].schedule, "0 4 * * *")
        self.assertEqual(by_name[DISPATCH_JOB_NAME].schedule, "every 5m")
        self.assertTrue(all(spec.fresh_session for spec in specs))
        self.assertTrue(all(not spec.no_agent for spec in specs))
        self.assertEqual(specs[0].enabled_toolsets, ("health_steward_daily", "no_mcp"))
        self.assertEqual(specs[1].enabled_toolsets, ("health_steward_dispatch", "no_mcp"))

    def test_installer_creates_only_two_jobs_and_preserves_unrelated_jobs(self):
        unrelated = {"id": "unrelated", "name": "backup", "schedule": {"kind": "interval"}}
        backend = FakeCronBackend([unrelated])
        created = install_fixed_jobs(
            backend, health_model_config=self.health_model_config()
        )
        self.assertEqual({job["name"] for job in created}, {DAILY_JOB_NAME, DISPATCH_JOB_NAME})
        self.assertEqual(len(backend.created), 2)
        self.assertEqual(backend.jobs[0], unrelated)
        self.assertEqual(
            len(
                install_fixed_jobs(
                    backend, health_model_config=self.health_model_config()
                )
            ),
            2,
        )
        self.assertEqual(len(backend.created), 2)

    def test_installer_binds_both_jobs_to_the_fixed_health_model(self):
        config = self.health_model_config()
        backend = FakeCronBackend()

        created = install_fixed_jobs(backend, health_model_config=config)

        self.assertEqual(len(created), 2)
        for spec, job in zip(fixed_job_specs(config), created):
            self.assertEqual(job["provider"], config.provider)
            self.assertEqual(job["model"], config.model_id)
            self.assertEqual(job["base_url"], config.endpoint)
            self.assertTrue(job_matches_spec(job, spec))

        tampered = dict(created[0], model="ordinary-chat-model")
        self.assertFalse(job_matches_spec(tampered, fixed_job_specs(config)[0]))
        with self.assertRaisesRegex(FixedJobConfigurationError, "health-job-drift"):
            install_fixed_jobs(
                FakeCronBackend([tampered]), health_model_config=config
            )

    def test_installer_rejects_a_mismatched_existing_health_job(self):
        backend = FakeCronBackend(
            [{
                "id": "bad",
                "name": DAILY_JOB_NAME,
                "schedule": {"kind": "interval", "minutes": 5},
                "prompt": "wrong",
            }]
        )
        with self.assertRaises(FixedJobConfigurationError):
            install_fixed_jobs(
                backend, health_model_config=self.health_model_config()
            )

    def test_installer_uses_real_hermes_cron_store_without_touching_core(self):
        hermes_source = ROOT.parents[1] / ".research" / "hermes-agent"
        if not (hermes_source / "cron" / "jobs.py").exists():
            self.skipTest("local Hermes mirror unavailable")
        old_home = os.environ.get("HERMES_HOME")
        previous_path = list(sys.path)
        try:
            with tempfile.TemporaryDirectory() as temp:
                os.environ["HERMES_HOME"] = temp
                sys.path.insert(0, str(hermes_source))
                from cron import jobs as cron_jobs

                if not getattr(cron_jobs, "HAS_CRONITER", False):
                    self.skipTest("Hermes mirror lacks croniter in this environment")
                with cron_jobs.use_cron_store(temp):
                    records = install_fixed_jobs(
                        health_model_config=self.health_model_config()
                    )
                    self.assertEqual(len(records), 2)
                    persisted = cron_jobs.list_jobs(include_disabled=True)
                    self.assertEqual(len(persisted), 2)
                    for spec, record in zip(
                        fixed_job_specs(self.health_model_config()), persisted
                    ):
                        self.assertTrue(job_matches_spec(record, spec))
        finally:
            sys.path[:] = previous_path
            if old_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old_home

    def test_runtime_identity_requires_scheduler_injected_id_and_fingerprint(self):
        spec = fixed_job_specs()[0]
        job = spec.to_job_record("daily-id")
        fingerprint = lambda record: hashlib.sha256(repr(sorted(record.items())).encode()).hexdigest()
        good_env = {
            "HERMES_CRON_JOB_ID": "daily-id",
            "HERMES_CRON_JOB_FINGERPRINT": fingerprint(job),
        }
        self.assertTrue(verify_runtime_job("daily_profile_review", good_env, [job], fingerprint))
        spoofed = dict(good_env, HERMES_CRON_JOB_ID="attacker")
        self.assertFalse(verify_runtime_job("daily_profile_review", spoofed, [job], fingerprint))
        self.assertFalse(verify_runtime_job("daily_profile_review", {}, [job], fingerprint))

    def test_daily_cron_snapshot_keeps_health_content_out_of_outer_agent_context(self):
        config = self.health_model_config()
        job = fixed_job_specs(config)[0].to_job_record("daily-id")
        fingerprint = lambda _record: "fixed-fingerprint"
        cron_module = types.ModuleType("cron")
        jobs_module = types.ModuleType("cron.jobs")
        scheduler_module = types.ModuleType("cron.scheduler")
        jobs_module.list_jobs = lambda include_disabled=True: [job]
        scheduler_module._runtime_job_fingerprint = fingerprint
        cron_module.jobs = jobs_module
        cron_module.scheduler = scheduler_module
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_path = root / "health-model.json"
            model_path.write_text(
                json.dumps(
                    {
                        "provider": config.provider,
                        "endpoint": config.endpoint,
                        "model_id": config.model_id,
                        "privacy_mode": config.privacy_mode,
                        "auth_profile": config.auth_profile,
                    }
                ),
                encoding="utf-8",
            )
            secret_path = root / "capability.key"
            ensure_capability_secret(secret_path)
            environment = {
                "HEALTH_STEWARD_HEALTH_MODEL_CONFIG": str(model_path),
                "HEALTH_STEWARD_CAPABILITY_SECRET": str(secret_path),
                "HERMES_CRON_JOB_ID": "daily-id",
                "HERMES_CRON_JOB_FINGERPRINT": fingerprint(job),
            }
            with mock.patch.dict(os.environ, environment, clear=False), mock.patch.dict(
                sys.modules,
                {
                    "cron": cron_module,
                    "cron.jobs": jobs_module,
                    "cron.scheduler": scheduler_module,
                },
            ):
                result = snapshot_for_role(DAILY_ROLE)

        self.assertEqual(result["role"], DAILY_ROLE)
        self.assertEqual(
            result["snapshot"],
            {
                "action": "health_daily_review",
                "authority": "sidecar-current-snapshot",
            },
        )
        self.assertTrue(result["capability"])

    def test_job_capability_binds_role_job_fingerprint_and_short_expiry(self):
        spec = fixed_job_specs()[0]
        job = spec.to_job_record("daily-id")
        fingerprint = lambda record: hashlib.sha256(repr(sorted(record.items())).encode()).hexdigest()
        issued = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
        now = issued + dt.timedelta(minutes=5)
        with tempfile.TemporaryDirectory() as temp:
            secret = Path(temp) / "capability.key"
            ensure_capability_secret(secret)

            def issue() -> str:
                return issue_job_capability(
                    "daily_profile_review", "daily-id", fingerprint(job), issued, secret
                )

            token = issue()
            self.assertTrue(
                verify_job_capability(
                    token,
                    "daily_profile_review",
                    jobs=[job],
                    fingerprint=fingerprint,
                    now_utc=now,
                    secret_path=secret,
                )
            )
            # Replay has its own fresh token only for the successful first
            # verification above; every remaining negative verifies the
            # intended boundary before nonce consumption can influence it.
            self.assertFalse(
                verify_job_capability(
                    token,
                    "daily_profile_review",
                    jobs=[job],
                    fingerprint=fingerprint,
                    now_utc=now,
                    secret_path=secret,
                )
            )
            wrong_role = issue()
            self.assertFalse(
                verify_job_capability(
                    wrong_role,
                    "due_task_dispatch",
                    jobs=[job],
                    fingerprint=fingerprint,
                    now_utc=now,
                    secret_path=secret,
                )
            )
            tampered_token = issue()
            self.assertFalse(
                verify_job_capability(
                    tampered_token + "x",
                    "daily_profile_review",
                    jobs=[job],
                    fingerprint=fingerprint,
                    now_utc=now,
                    secret_path=secret,
                )
            )
            fingerprint_drift_token = issue()
            drifted_job = {**job, "prompt": "tampered fixed Job"}
            self.assertFalse(
                verify_job_capability(
                    fingerprint_drift_token,
                    "daily_profile_review",
                    jobs=[drifted_job],
                    fingerprint=fingerprint,
                    now_utc=now,
                    secret_path=secret,
                )
            )
            expired_token = issue()
            self.assertFalse(
                verify_job_capability(
                    expired_token,
                    "daily_profile_review",
                    jobs=[job],
                    fingerprint=fingerprint,
                    now_utc=issued + dt.timedelta(minutes=11),
                    secret_path=secret,
                )
            )

    def test_runtime_delegates_daily_and_dispatch_to_sidecar_with_owner_time(self):
        clock = FakeClock(dt.datetime(2026, 1, 2, 20, 5, tzinfo=dt.timezone.utc))
        adapter = FakeAdapter()
        runtime = JobRuntime(adapter, subject="profile", timezone="Asia/Shanghai", clock=clock)

        snapshot = runtime.daily_snapshot()
        self.assertIn("profile", snapshot)
        result = runtime.execute_daily_review("signed-daily-job-proof")
        self.assertEqual(result["result"], "no_action")
        dispatch = runtime.dispatch("signed-dispatch-job-proof")
        self.assertEqual(dispatch["processed"], [])
        self.assertEqual(adapter.calls[0], (
            "daily_snapshot", "profile", "2026-01-02T20:00:00+00:00", "Asia/Shanghai"
        ))
        self.assertEqual(adapter.calls[1][0], "daily_execute")
        self.assertEqual(adapter.calls[1][1:4], (
            "profile", "2026-01-02T20:00:00+00:00", "Asia/Shanghai"
        ))
        self.assertEqual(adapter.calls[1][4], "signed-daily-job-proof")
        self.assertEqual(
            adapter.calls[2],
            ("dispatch", "profile", "2026-01-02T20:05:00+00:00", "signed-dispatch-job-proof"),
        )

    def test_job_record_match_rejects_agent_or_toolset_drift(self):
        spec = fixed_job_specs()[0]
        job = spec.to_job_record("daily-id")
        self.assertTrue(job_matches_spec(job, spec))
        self.assertFalse(job_matches_spec({**job, "no_agent": True}, spec))
        self.assertFalse(job_matches_spec({**job, "enabled_toolsets": ["terminal"]}, spec))
        self.assertFalse(job_matches_spec({**job, "deliver": "telegram"}, spec))
        self.assertFalse(job_matches_spec({**job, "enabled": False}, spec))

    def test_asset_installer_copies_plugin_and_all_prerun_dependencies(self):
        installer_path = ROOT / "scripts" / "install_health_steward_jobs.py"
        old_path = list(sys.path)
        try:
            import importlib.util

            module_spec = importlib.util.spec_from_file_location("health_installer_test", installer_path)
            installer = importlib.util.module_from_spec(module_spec)
            assert module_spec.loader is not None
            module_spec.loader.exec_module(installer)
            with tempfile.TemporaryDirectory() as temp:
                home = Path(temp) / "hermes"
                installed = installer.install_assets(ROOT, home)
                self.assertTrue((home / "plugins" / "health-steward" / "plugin.yaml").is_file())
                for name in (
                    "health_steward_snapshot.py",
                    "health_steward_daily_snapshot.py",
                    "health_steward_dispatch_snapshot.py",
                ):
                    self.assertTrue((home / "scripts" / name).is_file())
                self.assertTrue(installed)
                (home / "plugins" / "health-steward" / "plugin.yaml").chmod(0o400)
                for script in (home / "scripts").glob("health_steward*.py"):
                    script.chmod(0o400)
                installed_again = installer.install_assets(ROOT, home)
                self.assertTrue(installed_again)
                self.assertTrue(
                    os.access(
                        home / "plugins" / "health-steward" / "plugin.yaml",
                        os.W_OK,
                    )
                )
                with self.assertRaisesRegex(RuntimeError, "partner-profile"):
                    installer._require_partner_home(home)
        finally:
            sys.path[:] = old_path

    def test_unmodified_hermes_mirror_loads_partner_plugin_tools(self):
        hermes_source = ROOT.parents[1] / ".research" / "hermes-agent"
        if not (hermes_source / "hermes_cli" / "plugins.py").exists():
            self.skipTest("local Hermes mirror unavailable")
        plugin_source = ROOT / "plugin" / "health-steward"
        old_home = os.environ.get("HERMES_HOME")
        old_test_mode = os.environ.get("HEALTH_STEWARD_TEST_MODE")
        old_source = os.environ.get("HEALTH_STEWARD_SOURCE_ROOT")
        old_projection = os.environ.get("HEALTH_STEWARD_MEMORY_PROJECTION_PATH")
        previous_path = list(sys.path)
        try:
            with tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                (home / "plugins").mkdir()
                shutil.copytree(plugin_source, home / "plugins" / "health-steward")
                (home / "config.yaml").write_text(
                    "plugins:\n  enabled:\n    - health-steward\n",
                    encoding="utf-8",
                )
                os.environ["HERMES_HOME"] = str(home)
                os.environ["HEALTH_STEWARD_TEST_MODE"] = "1"
                os.environ["HEALTH_STEWARD_SOURCE_ROOT"] = str(ROOT)
                projection_path = home / "health-memory.json"
                projection_path.write_text(
                    json.dumps(
                        {
                            "profile": {
                                "schema_version": 1,
                                "archive_pointer": "health-sidecar://profile/profile",
                                "interaction_preferences": ["prefer concise replies"],
                                "proactive_contact": {
                                    "paused": False,
                                    "pause_until_utc": None,
                                },
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                os.environ["HEALTH_STEWARD_MEMORY_PROJECTION_PATH"] = str(
                    projection_path
                )
                sys.path.insert(0, str(hermes_source))
                from hermes_cli import plugins

                previous_manager = plugins._plugin_manager
                plugins._plugin_manager = None
                try:
                    manager = plugins.get_plugin_manager()
                    manager.discover_and_load(force=True)
                    loaded = manager._plugins.get("health-steward")
                    self.assertIsNotNone(loaded)
                    self.assertTrue(loaded.enabled)
                    self.assertIn("health_daily_review", loaded.tools_registered)
                    self.assertIn("health_dispatch_due_tasks", loaded.tools_registered)
                    self.assertIn("pre_llm_call", loaded.hooks_registered)
                    from gateway.platform_registry import platform_registry

                    partner_weixin = platform_registry.get("weixin")
                    self.assertIsNotNone(partner_weixin)
                    self.assertEqual(partner_weixin.plugin_name, "health-steward")
                    self.assertEqual(partner_weixin.source, "plugin")
                    hook_results = manager.invoke_hook(
                        "pre_llm_call", session_id="gateway-session"
                    )
                    self.assertEqual(len(hook_results), 1)
                    self.assertIn("prefer concise replies", hook_results[0]["context"])
                    self.assertEqual(
                        manager.invoke_hook("pre_llm_call", session_id="cron_job_1"),
                        [],
                    )
                finally:
                    plugins._plugin_manager = previous_manager
        finally:
            sys.path[:] = previous_path
            if old_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old_home
            if old_test_mode is None:
                os.environ.pop("HEALTH_STEWARD_TEST_MODE", None)
            else:
                os.environ["HEALTH_STEWARD_TEST_MODE"] = old_test_mode
            if old_source is None:
                os.environ.pop("HEALTH_STEWARD_SOURCE_ROOT", None)
            else:
                os.environ["HEALTH_STEWARD_SOURCE_ROOT"] = old_source
            if old_projection is None:
                os.environ.pop("HEALTH_STEWARD_MEMORY_PROJECTION_PATH", None)
            else:
                os.environ["HEALTH_STEWARD_MEMORY_PROJECTION_PATH"] = old_projection


if __name__ == "__main__":
    unittest.main()

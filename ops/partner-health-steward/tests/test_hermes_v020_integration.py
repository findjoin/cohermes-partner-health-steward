from __future__ import annotations

import copy
import contextlib
import datetime as dt
import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
HERMES_SOURCE = REPO_ROOT / ".research" / "hermes-agent"


class HermesV020PluginIntegrationTests(unittest.TestCase):
    @staticmethod
    def _load_autonomy_core(path: Path):
        spec = importlib.util.spec_from_file_location(
            "health_autonomy_run_one_job_integration", path
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _run_no_agent_job(home: Path, script: str, job_id: str):
        previous_home = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(home)
        sys.path.insert(0, str(HERMES_SOURCE))
        try:
            from cron import scheduler

            previous_override = scheduler._hermes_home
            scheduler._hermes_home = home
            try:
                return scheduler.run_job(
                    {
                        "id": job_id,
                        "name": "health-autonomy-dispatch-v02",
                        "prompt": "health-autonomy deterministic dispatcher",
                        "script": script,
                        "no_agent": True,
                    }
                ), scheduler.SILENT_MARKER
            finally:
                scheduler._hermes_home = previous_override
        finally:
            if sys.path and sys.path[0] == str(HERMES_SOURCE):
                sys.path.pop(0)
            if previous_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous_home

    def test_scheduler_injects_actual_no_agent_job_id(self):
        with tempfile.TemporaryDirectory() as temp_home:
            home = Path(temp_home)
            scripts = home / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "job_id_probe.py").write_text(
                "import os\nprint(os.environ.get('HERMES_CRON_JOB_ID', ''))\n",
                encoding="utf-8",
            )
            previous_claim = os.environ.get("HERMES_CRON_JOB_ID")
            os.environ["HERMES_CRON_JOB_ID"] = "spoofed-parent-value"
            try:
                result, _ = self._run_no_agent_job(
                    home, "job_id_probe.py", "actual-caller-job"
                )
            finally:
                if previous_claim is None:
                    os.environ.pop("HERMES_CRON_JOB_ID", None)
                else:
                    os.environ["HERMES_CRON_JOB_ID"] = previous_claim

        ok, _doc, final_answer, error = result
        self.assertTrue(ok)
        self.assertEqual(final_answer, "actual-caller-job")
        self.assertIsNone(error)

    def test_corrupt_health_db_is_silent_through_real_no_agent_run_job(self):
        with tempfile.TemporaryDirectory() as temp_home:
            home = Path(temp_home)
            shutil.copytree(
                ROOT / "plugin" / "health-autonomy",
                home / "plugins" / "health-autonomy",
            )
            scripts = home / "scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(
                ROOT / "scripts" / "health_autonomy_dispatch.py",
                scripts / "health_autonomy_dispatch.py",
            )
            private = home / "private"
            private.mkdir()
            (private / "health-autonomy-v02.sqlite3").write_bytes(
                b"not-a-sqlite-database"
            )

            result, silent_marker = self._run_no_agent_job(
                home, "health_autonomy_dispatch.py", "untrusted-caller-job"
            )

        ok, _doc, final_answer, error = result
        self.assertTrue(ok)
        self.assertEqual(final_answer, silent_marker)
        self.assertIsNone(error)

    def _run_health_snapshot_scenario(self, *, stale_snapshot: bool):
        with tempfile.TemporaryDirectory() as temp_home:
            home = Path(temp_home)
            shutil.copytree(
                ROOT / "plugin" / "health-autonomy",
                home / "plugins" / "health-autonomy",
            )
            scripts = home / "scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(
                ROOT / "scripts" / "health_autonomy_dispatch.py",
                scripts / "health_autonomy_dispatch.py",
            )

            previous_home = os.environ.get("HERMES_HOME")
            previous_pythonpath = os.environ.get("PYTHONPATH")
            os.environ["HERMES_HOME"] = str(home)
            os.environ["PYTHONPATH"] = str(HERMES_SOURCE) + (
                os.pathsep + previous_pythonpath if previous_pythonpath else ""
            )
            sys.path.insert(0, str(HERMES_SOURCE))
            try:
                from cron import jobs as cron_jobs
                from cron import scheduler

                previous_override = scheduler._hermes_home
                scheduler._hermes_home = home
                try:
                    with cron_jobs.use_cron_store(home):
                        routing = {
                            "platform": "telegram",
                            "user_id": "partner-user",
                            "chat_id": "partner-chat",
                            "thread_id": "",
                            "chat_type": "dm",
                        }
                        persisted_job = cron_jobs.create_job(
                            prompt="[health-autonomy-v02] deterministic private dispatcher",
                            schedule="every 5m",
                            name="health-autonomy-dispatch-v02",
                            repeat=None,
                            deliver="origin",
                            origin=routing,
                            script="health_autonomy_dispatch.py",
                            no_agent=True,
                            attach_to_session=False,
                        )
                        autonomy = self._load_autonomy_core(
                            home / "plugins" / "health-autonomy" / "autonomy.py"
                        )
                        store = autonomy.HealthAutonomyStore(
                            home / "private" / "health-autonomy-v02.sqlite3"
                        )
                        activation_text = autonomy.activation_example().replace(
                            "静默时段=23:00-08:00", "静默时段=00:00-00:01"
                        )
                        config = autonomy.parse_activation(activation_text)
                        subject_key = autonomy.routing_subject_key(routing)
                        store.activate(
                            config,
                            source_message_id="integration-activation",
                            dispatcher_job_id=persisted_job["id"],
                            subject_key=subject_key,
                            dispatcher_routing=routing,
                        )
                        store.observe(
                            "我总忘记喝水",
                            "integration-hydration",
                            subject_key,
                        )
                        due_at = (
                            dt.datetime.now(dt.timezone.utc)
                            - dt.timedelta(minutes=1)
                        ).replace(microsecond=0).isoformat()
                        with contextlib.closing(
                            sqlite3.connect(store.path)
                        ) as connection:
                            connection.execute(
                                "UPDATE automation_task SET next_run_at=?, "
                                "suppressed_until=NULL, status='active'",
                                (due_at,),
                            )
                            connection.commit()

                        run_snapshot = copy.deepcopy(persisted_job)
                        if stale_snapshot:
                            run_snapshot["deliver"] = "telegram:attacker-chat"
                        delivery = mock.Mock(return_value=None)
                        with (
                            mock.patch.object(
                                scheduler, "claim_dispatch", return_value=True
                            ),
                            mock.patch.object(
                                scheduler,
                                "save_job_output",
                                return_value=home / "cron-output.md",
                            ),
                            mock.patch.object(scheduler, "mark_job_run"),
                            mock.patch.object(
                                scheduler, "_is_interrupted", return_value=False
                            ),
                            mock.patch.object(
                                scheduler,
                                "_consume_interrupted_flag",
                                return_value=False,
                            ),
                            mock.patch.object(
                                scheduler, "_deliver_result", delivery
                            ),
                        ):
                            processed = scheduler.run_one_job(run_snapshot)

                        with contextlib.closing(
                            sqlite3.connect(store.path)
                        ) as connection:
                            dispatch_count = connection.execute(
                                "SELECT COUNT(*) FROM dispatch_event"
                            ).fetchone()[0]
                        calls = list(delivery.call_args_list)
                finally:
                    scheduler._hermes_home = previous_override
            finally:
                if sys.path and sys.path[0] == str(HERMES_SOURCE):
                    sys.path.pop(0)
                if previous_home is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = previous_home
                if previous_pythonpath is None:
                    os.environ.pop("PYTHONPATH", None)
                else:
                    os.environ["PYTHONPATH"] = previous_pythonpath

        return processed, calls, dispatch_count

    def test_run_one_job_binds_execution_snapshot_to_final_delivery(self):
        processed, calls, dispatch_count = self._run_health_snapshot_scenario(
            stale_snapshot=False
        )
        self.assertTrue(processed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0]["origin"]["chat_id"], "partner-chat")
        self.assertEqual(dispatch_count, 1)

        processed, calls, dispatch_count = self._run_health_snapshot_scenario(
            stale_snapshot=True
        )
        self.assertTrue(processed)
        self.assertEqual(calls, [])
        self.assertEqual(dispatch_count, 0)

    def test_real_plugin_manager_loads_command_and_gateway_hook(self):
        if not (HERMES_SOURCE / "hermes_cli" / "plugins.py").exists():
            self.skipTest("local Hermes v0.20-compatible source mirror is unavailable")

        with tempfile.TemporaryDirectory() as temp_home:
            home = Path(temp_home)
            shutil.copytree(
                ROOT / "plugin" / "health-guard",
                home / "plugins" / "health-guard",
            )
            shutil.copytree(
                ROOT / "plugin" / "health-autonomy",
                home / "plugins" / "health-autonomy",
            )
            (home / "config.yaml").write_text(
                "plugins:\n  enabled:\n    - health-guard\n    - health-autonomy\n",
                encoding="utf-8",
            )

            previous_home = os.environ.get("HERMES_HOME")
            previous_test_mode = os.environ.get("HEALTH_GUARD_TEST_MODE")
            previous_autonomy_test_mode = os.environ.get("HEALTH_AUTONOMY_TEST_MODE")
            previous_path = list(sys.path)
            previous_gateway = sys.modules.get("gateway")
            previous_gateway_run = sys.modules.get("gateway.run")
            os.environ["HERMES_HOME"] = str(home)
            os.environ["HEALTH_GUARD_TEST_MODE"] = "1"
            os.environ["HEALTH_AUTONOMY_TEST_MODE"] = "1"
            sys.path.insert(0, str(HERMES_SOURCE))
            try:
                from hermes_cli import plugins

                class FakeGatewayRunner:
                    async def _handle_message(self, event):
                        return "original-idle"

                    async def _handle_active_session_busy_message(self, event, session_key):
                        return False

                gateway_module = types.ModuleType("gateway")
                gateway_run_module = types.ModuleType("gateway.run")
                gateway_run_module.GatewayRunner = FakeGatewayRunner
                gateway_module.run = gateway_run_module
                sys.modules["gateway"] = gateway_module
                sys.modules["gateway.run"] = gateway_run_module

                plugins._plugin_manager = None
                plugins.discover_plugins(force=True)

                handler = plugins.get_plugin_command_handler("health-guard-safe")
                self.assertIsNotNone(handler)
                self.assertIn("120", handler("emergency"))
                self.assertIsNotNone(
                    plugins.get_plugin_command_handler("health-autonomy-safe")
                )

                source = types.SimpleNamespace(
                    chat_type="dm",
                    authorized=True,
                    platform=types.SimpleNamespace(value="telegram"),
                    user_id="partner-user",
                    chat_id="partner-chat",
                    thread_id="",
                )
                gateway = types.SimpleNamespace(
                    _is_user_authorized=lambda candidate: candidate.authorized
                )
                event = types.SimpleNamespace(
                    text="我喘不过气",
                    source=source,
                )
                results = plugins.invoke_hook(
                    "pre_gateway_dispatch",
                    event=event,
                    gateway=gateway,
                    session_store=None,
                )
                self.assertEqual(
                    results,
                    [{"action": "rewrite", "text": "/health-guard-safe emergency"}],
                )
                self.assertTrue(
                    getattr(FakeGatewayRunner, "_partner_health_guard_v01_installed", False)
                )
            finally:
                try:
                    from hermes_cli import plugins

                    plugins._plugin_manager = None
                except Exception:
                    pass
                if previous_home is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = previous_home
                if previous_test_mode is None:
                    os.environ.pop("HEALTH_GUARD_TEST_MODE", None)
                else:
                    os.environ["HEALTH_GUARD_TEST_MODE"] = previous_test_mode
                if previous_autonomy_test_mode is None:
                    os.environ.pop("HEALTH_AUTONOMY_TEST_MODE", None)
                else:
                    os.environ["HEALTH_AUTONOMY_TEST_MODE"] = previous_autonomy_test_mode
                if previous_gateway is None:
                    sys.modules.pop("gateway", None)
                else:
                    sys.modules["gateway"] = previous_gateway
                if previous_gateway_run is None:
                    sys.modules.pop("gateway.run", None)
                else:
                    sys.modules["gateway.run"] = previous_gateway_run
                sys.path[:] = previous_path


if __name__ == "__main__":
    unittest.main()

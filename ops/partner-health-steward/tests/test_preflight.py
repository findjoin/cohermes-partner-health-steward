from __future__ import annotations

import importlib.util
import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
HERMES_SOURCE = REPO_ROOT / ".research" / "hermes-agent"
PREFLIGHT_PATH = ROOT / "scripts" / "verify_health_guard_preflight.py"
SPEC = importlib.util.spec_from_file_location("health_guard_preflight_under_test", PREFLIGHT_PATH)
preflight = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


class PreflightParserTests(unittest.TestCase):
    def test_reads_block_plugin_lists(self):
        config = """
plugins:
  enabled:
    - medical
    - health-guard
  disabled:
    - demo
"""
        self.assertEqual(
            preflight._yaml_list(config, ("plugins", "enabled")),
            ["medical", "health-guard"],
        )
        self.assertEqual(
            preflight._yaml_list(config, ("plugins", "disabled")),
            ["demo"],
        )

    def test_reads_inline_plugin_list(self):
        config = "plugins:\n  enabled: [medical, 'health-guard']\n"
        self.assertEqual(
            preflight._yaml_list(config, ("plugins", "enabled")),
            ["medical", "health-guard"],
        )

    def test_empty_plugin_list_is_empty(self):
        config = "plugins:\n  enabled: []\nauxiliary:\n  enabled: true\n"
        self.assertEqual(preflight._yaml_list(config, ("plugins", "enabled")), [])

    def test_embedded_release_hashes_match_local_artifacts(self):
        local_paths = {
            "plugins/health-guard/plugin.yaml": ROOT / "plugin" / "health-guard" / "plugin.yaml",
            "plugins/health-guard/__init__.py": ROOT / "plugin" / "health-guard" / "__init__.py",
            "plugins/health-guard/guard.py": ROOT / "plugin" / "health-guard" / "guard.py",
            "plugins/health-autonomy/plugin.yaml": (
                ROOT / "plugin" / "health-autonomy" / "plugin.yaml"
            ),
            "plugins/health-autonomy/__init__.py": (
                ROOT / "plugin" / "health-autonomy" / "__init__.py"
            ),
            "plugins/health-autonomy/autonomy.py": (
                ROOT / "plugin" / "health-autonomy" / "autonomy.py"
            ),
            "skills/health-steward/SKILL.md": ROOT / "skill" / "health-steward" / "SKILL.md",
            "skills/health-steward/references/medical-safety-sources.md": (
                ROOT
                / "skill"
                / "health-steward"
                / "references"
                / "medical-safety-sources.md"
            ),
            "scripts/health_reminder_generic.py": ROOT / "scripts" / "health_reminder_generic.py",
            "scripts/health_autonomy_dispatch.py": (
                ROOT / "scripts" / "health_autonomy_dispatch.py"
            ),
        }
        for relative_path, expected in preflight.EXPECTED_ARTIFACT_HASHES.items():
            with self.subTest(relative_path=relative_path):
                actual = hashlib.sha256(local_paths[relative_path].read_bytes()).hexdigest()
                self.assertEqual(actual, expected)

        drop_in = ROOT / "systemd" / "hermes-gateway-partner-health-guard.conf"
        actual_drop_in = hashlib.sha256(drop_in.read_bytes()).hexdigest()
        self.assertEqual(
            actual_drop_in,
            next(iter(preflight.EXPECTED_EXTERNAL_HASHES.values())),
        )

    def test_embedded_cron_function_hashes_match_patched_local_core(self):
        actual = preflight._top_level_function_hashes(
            HERMES_SOURCE / "cron" / "scheduler.py",
            set(preflight.EXPECTED_CRON_FUNCTION_HASHES),
        )
        self.assertEqual(actual, preflight.EXPECTED_CRON_FUNCTION_HASHES)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path
import subprocess
import sys
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "pm" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pm_config import default_config
from pm_runtime import (
    build_openclaw_session_id,
    describe_openclaw_agent_failure,
    openclaw_wrapper_timeout,
    run_codex_cli,
    run_openclaw_agent,
)


class PmRuntimeTest(unittest.TestCase):
    def test_unknown_agent_failure_includes_front_agent_hint(self) -> None:
        message = describe_openclaw_agent_failure("codex", stderr='Unknown agent id "codex"')
        self.assertIn("Unknown agent id", message)
        self.assertIn("front agent", message)
        self.assertIn("openclaw agents list --bindings", message)

    def test_codex_cli_uses_minimum_effective_timeout(self) -> None:
        with mock.patch("pm_runtime.subprocess.run") as mocked_run:
            mocked_run.return_value = subprocess.CompletedProcess(
                args=["codex"],
                returncode=0,
                stdout="ok",
                stderr="",
            )
            result = run_codex_cli(
                agent_id="codex",
                message="Reply with OK",
                cwd="/tmp",
                timeout_seconds=120,
            )
        self.assertEqual(result["backend"], "codex-cli")
        self.assertEqual(mocked_run.call_args.kwargs["timeout"], 300)

    def test_build_openclaw_session_id_rewrites_reserved_main(self) -> None:
        value = build_openclaw_session_id("main", agent_id="main")
        self.assertNotEqual(value, "main")
        self.assertTrue(value.startswith("pm-openclaw-main-"))

    def test_openclaw_wrapper_timeout_adds_grace_window(self) -> None:
        self.assertEqual(openclaw_wrapper_timeout(120), 150)
        self.assertEqual(openclaw_wrapper_timeout(1), 31)
        self.assertIsNone(openclaw_wrapper_timeout(0))

    def test_run_openclaw_agent_always_passes_dedicated_session_id(self) -> None:
        with mock.patch("pm_runtime.subprocess.run") as mocked_run:
            mocked_run.return_value = subprocess.CompletedProcess(
                args=["openclaw"],
                returncode=0,
                stdout='{"status":"ok"}',
                stderr="",
            )
            result = run_openclaw_agent(
                agent_id="main",
                message="Reply with OK",
                cwd="/tmp",
                timeout_seconds=120,
                session_id="main",
                bin_path_fn=lambda: Path("/usr/bin/openclaw"),
                env_fn=lambda **_: {"PATH": "/usr/bin"},
            )
        self.assertEqual(result["status"], "ok")
        cmd = mocked_run.call_args.args[0]
        self.assertIn("--session-id", cmd)
        idx = cmd.index("--session-id") + 1
        self.assertTrue(cmd[idx].startswith("pm-openclaw-main-"))
        self.assertNotEqual(cmd[idx], "main")
        self.assertEqual(mocked_run.call_args.kwargs["timeout"], 150)

    def test_run_openclaw_agent_reports_subprocess_timeout(self) -> None:
        with mock.patch("pm_runtime.subprocess.run") as mocked_run:
            mocked_run.side_effect = subprocess.TimeoutExpired(cmd=["openclaw"], timeout=150)
            with self.assertRaises(SystemExit) as ctx:
                run_openclaw_agent(
                    agent_id="main",
                    message="Reply with OK",
                    cwd="/tmp",
                    timeout_seconds=120,
                    session_id="main",
                    bin_path_fn=lambda: Path("/usr/bin/openclaw"),
                    env_fn=lambda **_: {"PATH": "/usr/bin"},
                )
        self.assertIn("subprocess timed out after 120s", str(ctx.exception))
        self.assertIn("wrapper timeout: 150s", str(ctx.exception))

    def test_default_config_includes_review_defaults(self) -> None:
        review = default_config()["review"]
        self.assertEqual(review["required"], True)
        self.assertEqual(review["enforce_on_complete"], True)
        self.assertEqual(review["sync_comment"], True)
        self.assertEqual(review["sync_state"], True)


if __name__ == "__main__":
    unittest.main()

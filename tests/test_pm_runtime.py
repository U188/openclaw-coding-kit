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
from pm_runtime import describe_openclaw_agent_failure, run_codex_cli


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

    def test_default_config_includes_review_defaults(self) -> None:
        review = default_config()["review"]
        self.assertEqual(review["required"], True)
        self.assertEqual(review["enforce_on_complete"], True)
        self.assertEqual(review["sync_comment"], True)
        self.assertEqual(review["sync_state"], True)


if __name__ == "__main__":
    unittest.main()

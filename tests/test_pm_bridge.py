from __future__ import annotations

import unittest
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PM_SCRIPT_DIR = REPO_ROOT / "skills" / "pm" / "scripts"
if str(PM_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(PM_SCRIPT_DIR))

from pm_bridge import bridge_script_path
from pm_dispatch import build_run_label, spawn_acp_session


class PmBridgeTest(unittest.TestCase):
    def test_repo_local_lark_bridge_script_exists_and_is_preferred(self) -> None:
        repo_script = REPO_ROOT / "skills" / "openclaw-lark-bridge" / "scripts" / "invoke_openclaw_tool.py"
        fallback_script = Path.home() / ".codex" / "skills" / "openclaw-lark-bridge" / "scripts" / "invoke_openclaw_tool.py"

        self.assertTrue(repo_script.exists())
        resolved = bridge_script_path((repo_script, fallback_script))
        self.assertEqual(resolved, repo_script)

    def test_build_run_label_is_unique_per_call(self) -> None:
        root = Path("/tmp/openclaw-coding-kit")
        label_a = build_run_label(root, "codex", "T2")
        label_b = build_run_label(root, "codex", "T2")
        self.assertNotEqual(label_a, label_b)
        self.assertTrue(label_a.startswith("pm-openclaw-coding-kit-codex-t2-"))
        self.assertTrue(label_b.startswith("pm-openclaw-coding-kit-codex-t2-"))

    def test_spawn_acp_session_requests_inherited_sandbox(self) -> None:
        captured: dict[str, object] = {}

        def fake_bridge(tool: str, action: str, args: dict[str, object] | None = None, *, session_key: str = "") -> dict[str, object]:
            captured["tool"] = tool
            captured["action"] = action
            captured["args"] = dict(args or {})
            captured["session_key"] = session_key
            return {"status": "accepted"}

        result = spawn_acp_session(
            fake_bridge,
            agent_id="codex",
            message="do work",
            cwd="/tmp/project",
            timeout_seconds=123,
            thinking="high",
            label="pm-demo-codex-t1-1234",
            session_key="main",
        )

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(captured["tool"], "sessions_spawn")
        self.assertEqual(captured["action"], "")
        self.assertEqual(captured["session_key"], "main")
        spawn_args = captured["args"]
        self.assertIsInstance(spawn_args, dict)
        self.assertEqual(spawn_args["sandbox"], "inherit")
        self.assertEqual(spawn_args["cwd"], "/tmp/project")
        self.assertEqual(spawn_args["mode"], "run")
        self.assertEqual(spawn_args["cleanup"], "keep")


if __name__ == "__main__":
    unittest.main()

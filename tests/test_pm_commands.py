from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from contextlib import contextmanager


REPO_ROOT = Path(__file__).resolve().parents[1]
PM_SCRIPT_DIR = REPO_ROOT / "skills" / "pm" / "scripts"
if str(PM_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(PM_SCRIPT_DIR))

from pm_commands import build_command_handlers


class _FakeApi:
    def __init__(self) -> None:
        self.spawn_calls = 0
        self.openclaw_calls = 0
        self.codex_calls = 0
        self.persist_dispatch_calls = 0
        self.persist_run_calls = 0
        self.last_bundle = {"current_task": {"task_id": "T1"}}
        self.ACTIVE_CONFIG = {}

    def build_coder_context(self, task_id: str = "", task_guid: str = ""):
        return self.last_bundle, Path("/tmp/coder-context.json")

    def coder_config(self) -> dict:
        return {
            "backend": "codex-cli",
            "agent_id": "codex",
            "timeout": 60,
            "thinking": "high",
            "session_key": "main",
        }

    def build_run_message(self, bundle: dict) -> str:
        return "run message"

    def resolve_effective_task(self, bundle: dict) -> dict:
        current = bundle.get("current_task") if isinstance(bundle.get("current_task"), dict) else {}
        if current:
            return current
        return {"task_id": "T1"}

    def build_run_label(self, root: Path, agent_id: str, task_id: str) -> str:
        return f"{agent_id}:{task_id}"

    def project_root_path(self, repo_root: str | None = None) -> Path:
        return Path("/tmp/repo")

    def spawn_acp_session(self, **kwargs):
        self.spawn_calls += 1
        raise SystemExit("Tool not available: sessions_spawn")

    def run_openclaw_agent(self, **kwargs):
        self.openclaw_calls += 1
        return {"status": "ok", "summary": "completed", "result": {"payloads": []}}

    def run_codex_cli(self, **kwargs):
        self.codex_calls += 1
        return {"backend": "codex-cli", "status": "ok", "summary": "completed", "result": {"payloads": []}}

    def persist_dispatch_side_effects(self, bundle: dict, result: dict, *, agent_id: str, runtime: str) -> dict:
        self.persist_dispatch_calls += 1
        return {"runtime": runtime, "kind": "dispatch"}

    def persist_run_side_effects(self, bundle: dict, result: dict) -> dict:
        self.persist_run_calls += 1
        return {"kind": "run"}

    @contextmanager
    def task_run_lock(self, task_id: str):
        self.last_locked_task_id = task_id
        yield Path(f"/tmp/{task_id}.lock")

    def write_pm_bundle(self, name: str, payload: dict) -> None:
        self.last_written_name = name
        self.last_written_payload = payload

    def write_pm_run_record(self, payload: dict, *, run_id: str = "") -> None:
        self.last_written_name = "last-run.json"
        self.last_written_payload = payload
        self.last_written_run_id = run_id


class PmCommandsFallbackTest(unittest.TestCase):
    def test_cmd_run_falls_back_from_acp_to_codex_cli_when_sessions_spawn_unavailable(self) -> None:
        api = _FakeApi()
        handlers = build_command_handlers(api)
        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            backend="acp",
            agent="main",
            timeout=120,
            thinking="high",
            session_key="main",
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = handlers["run"](args)

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["backend"], "codex-cli")
        self.assertEqual(api.spawn_calls, 1)
        self.assertEqual(api.codex_calls, 1)
        self.assertEqual(api.openclaw_calls, 0)
        self.assertEqual(api.persist_dispatch_calls, 0)
        self.assertEqual(api.persist_run_calls, 1)
        self.assertIn("fell back to backend=codex-cli", payload["warnings"][0])
        self.assertEqual(api.last_locked_task_id, "T1")
        self.assertEqual(api.last_written_name, "last-run.json")
        self.assertEqual(api.last_written_payload["backend"], "codex-cli")
        self.assertEqual(api.last_written_run_id, "")

    def test_cmd_run_auto_switches_default_codex_cli_to_acp_for_brownfield_bundle(self) -> None:
        api = _FakeApi()
        api.last_bundle = {
            "bootstrap": {"project_mode": "brownfield"},
            "current_task": {
                "task_id": "T2",
                "description": "这是一个较长的任务说明。" * 20,
            },
            "handoff_contract": {
                "required_reads": ["pm.json", ".pm/current-context.json", ".pm/bootstrap.json"],
            },
        }
        handlers = build_command_handlers(api)
        args = argparse.Namespace(
            task_id="T2",
            task_guid="",
            backend="",
            agent="codex",
            timeout=120,
            thinking="high",
            session_key="main",
        )

        def _spawn_ok(**kwargs):
            api.spawn_calls += 1
            return {"status": "accepted", "result": {"payloads": []}}

        api.spawn_acp_session = _spawn_ok

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = handlers["run"](args)

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["backend"], "acp")
        self.assertEqual(api.spawn_calls, 1)
        self.assertEqual(api.codex_calls, 0)
        self.assertEqual(api.last_locked_task_id, "T2")
        self.assertIn("Auto-switched backend from codex-cli to acp", payload["warnings"][0])

    def test_cmd_run_writes_run_id_from_dispatch_side_effects(self) -> None:
        api = _FakeApi()
        api.last_bundle = {
            "bootstrap": {"project_mode": "brownfield"},
            "current_task": {"task_id": "T3", "description": "desc" * 80},
            "handoff_contract": {"required_reads": ["pm.json", ".pm/current-context.json", ".pm/bootstrap.json"]},
        }
        handlers = build_command_handlers(api)
        args = argparse.Namespace(
            task_id="T3",
            task_guid="",
            backend="",
            agent="codex",
            timeout=120,
            thinking="high",
            session_key="main",
        )

        def _spawn_ok(**kwargs):
            api.spawn_calls += 1
            return {"status": "accepted", "result": {"payloads": []}}

        def _dispatch_effects(bundle: dict, result: dict, *, agent_id: str, runtime: str) -> dict:
            api.persist_dispatch_calls += 1
            return {"runtime": runtime, "kind": "dispatch", "run_id": "run-123", "session_key": "agent:codex:acp:abc"}

        api.spawn_acp_session = _spawn_ok
        api.persist_dispatch_side_effects = _dispatch_effects

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = handlers["run"](args)

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["run_id"], "run-123")
        self.assertEqual(api.last_written_run_id, "run-123")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
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
        self.last_bundle = {"current_task": {"task_id": "T1", "guid": "guid-T1", "summary": "Task 1"}}
        self.ACTIVE_CONFIG = {}
        self._coder_config = {
            "backend": "codex-cli",
            "agent_id": "codex",
            "timeout": 60,
            "thinking": "high",
            "session_key": "main",
            "auto_switch_to_acp": False,
            "acp_cleanup": "delete",
        }
        self.last_run_record = None
        self.run_records: dict[str, dict] = {}
        self._now_counter = 0
        self.comments: list[tuple[str, str]] = []
        self.state_updates: list[str] = []
        self._tmpdir = tempfile.TemporaryDirectory()
        self._repo_root = Path(self._tmpdir.name) / "repo"
        self._repo_root.mkdir(parents=True, exist_ok=True)
        self._pm_dir = Path(self._tmpdir.name) / ".pm"
        self._pm_dir.mkdir(parents=True, exist_ok=True)

    def build_coder_context(self, task_id: str = "", task_guid: str = ""):
        return self.last_bundle, Path("/tmp/coder-context.json")

    def coder_config(self) -> dict:
        return dict(self._coder_config)

    def default_config(self) -> dict:
        return {
            "task": {"backend": "local"},
            "doc": {"backend": "repo"},
            "coder": dict(self._coder_config),
            "review": {
                "required": True,
                "enforce_on_complete": True,
                "sync_comment": True,
                "sync_state": True,
            },
            "monitor": {
                "enabled": True,
                "mode": "cron",
                "interval_minutes": 5,
                "stalled_after_minutes": 20,
                "notify_on_start": True,
                "notify_on_review_pending": True,
                "notify_on_review_failed": True,
                "auto_stop_on_complete": True,
            },
        }

    def build_run_message(self, bundle: dict) -> str:
        review_context = bundle.get("review_context") if isinstance(bundle.get("review_context"), dict) else {}
        feedback = str(review_context.get("review_feedback") or "").strip()
        if feedback:
            return f"run message\n{feedback}"
        return "run message"

    def resolve_effective_task(self, bundle: dict) -> dict:
        current = bundle.get("current_task") if isinstance(bundle.get("current_task"), dict) else {}
        if current:
            return current
        return {"task_id": "T1"}

    def build_run_label(self, root: Path, agent_id: str, task_id: str) -> str:
        return f"{agent_id}:{task_id}"

    def project_root_path(self, repo_root: str | None = None) -> Path:
        return self._repo_root

    def resolve_runtime_path(self, *, env_vars=(), path_lookup_names=(), fallback_paths=()):
        if tuple(path_lookup_names or ()) == ("codex",):
            return Path("/tmp/fake-codex")
        return None

    def openclaw_config(self) -> dict:
        return {}

    def pm_dir_path(self, repo_root: str | None = None) -> Path:
        return self._pm_dir

    def pm_file(self, name: str) -> Path:
        return self._pm_dir / name

    def monitor_config(self) -> dict:
        return dict(self.default_config()["monitor"])

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

    def acp_cleanup_mode_from_coder(self, coder: dict) -> str:
        return str((coder or {}).get("acp_cleanup") or "delete")

    def build_run_cleanup_plan(self, *, backend: str, session_key: str = "", acp_cleanup: str = "") -> dict:
        return {
            "status": "planned" if backend == "acp" else "not-applicable",
            "backend": backend,
            "session_key": session_key,
            "acp_cleanup": acp_cleanup if backend == "acp" else "",
        }

    def now_iso(self) -> str:
        self._now_counter += 1
        return f"2026-04-09T07:00:0{self._now_counter}+08:00"

    def load_json_file(self, path: Path):
        if path.name == "last-run.json":
            return dict(self.last_run_record) if isinstance(self.last_run_record, dict) else None
        if path.parent.name == "runs":
            record = self.run_records.get(path.stem)
            return dict(record) if isinstance(record, dict) else None
        if path.parent.name == "monitors":
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
        return None

    def create_task_comment(self, task_guid: str, content: str) -> dict:
        self.comments.append((task_guid, content))
        return {"task_guid": task_guid, "content": content}

    def append_state_doc(self, markdown: str) -> dict:
        self.state_updates.append(markdown)
        return {"status": "ok"}

    def refresh_context_cache(self, **kwargs) -> dict:
        return {}

    def get_task_record(self, task_id: str, include_completed: bool = False) -> dict:
        return {"task_id": task_id, "guid": f"guid-{task_id}", "summary": f"{task_id} summary"}

    def get_task_record_by_guid(self, task_guid: str) -> dict:
        return {"task_id": "T1", "guid": task_guid, "summary": "T1 summary"}

    def ensure_task_started(self, task: dict) -> None:
        return None

    def resolve_optional_text_input(self, content: str, content_file: str) -> str:
        return content

    def upload_task_attachments(self, task: dict, task_id: str, files: list[str]) -> dict:
        return {"status": "skipped", "uploaded_count": 0}

    def current_head_commit_url(self, repo_root: str) -> str:
        return ""

    def build_completion_comment(self, content: str, commit_url: str, uploaded_count: int) -> str:
        return content

    def patch_task(self, guid: str, payload: dict) -> dict:
        return {"guid": guid, **payload}

    def task_id_for_output(self, task_id: str) -> str:
        return task_id

    def finalize_last_run_for_completion(self, last_run: dict | None, *, task_id: str = "", task_guid: str = "", completed_at: str, finalized_at: str):
        if not isinstance(last_run, dict):
            return None, {"status": "no-last-run-record"}
        updated = dict(last_run)
        updated["task_id"] = task_id or updated.get("task_id") or ""
        updated["task_guid"] = task_guid or updated.get("task_guid") or ""
        updated["completed_at"] = completed_at
        updated["finalized_at"] = finalized_at
        updated["cleanup_result"] = {"status": "finalized", "completed_at": completed_at, "finalized_at": finalized_at}
        return updated, updated["cleanup_result"]

    def write_pm_bundle(self, name: str, payload: dict) -> None:
        self.last_written_name = name
        self.last_written_payload = payload

    def write_pm_run_record(self, payload: dict, *, run_id: str = "") -> None:
        self.last_written_name = "last-run.json"
        self.last_written_payload = payload
        self.last_written_run_id = run_id
        self.last_run_record = dict(payload)
        normalized_run_id = str(run_id or payload.get("run_id") or "").strip()
        if normalized_run_id:
            self.run_records[normalized_run_id] = dict(payload)
            runs_dir = self._pm_dir / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            (runs_dir / f"{normalized_run_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def start_run_monitor(self, *, repo_root: str, task_id: str, task_guid: str, run_id: str, backend: str, side_effects: dict, session_key: str) -> dict:
        return {
            "status": "active",
            "status_reason": "cron-verified",
            "task_id": task_id,
            "task_guid": task_guid,
            "run_id": run_id,
            "backend": backend,
            "repo_root": repo_root,
            "child_session_key": str(side_effects.get("session_key") or ""),
            "cron_job_id": f"job-{run_id}",
            "kickoff_enabled": True,
            "kickoff_status": "pending",
        }

    def refresh_run_monitor(self, run_id: str, *, write: bool = True) -> dict:
        record = self.run_records.get(run_id)
        monitor = {}
        if isinstance(record, dict) and isinstance(record.get("monitor"), dict):
            monitor = dict(record["monitor"])
        return {"status": str(monitor.get("status") or "not-found"), "monitor": monitor}

    def kickoff_run_monitor(self, run_id: str, *, reason: str = "pm monitor start") -> dict:
        monitor = {}
        record = self.run_records.get(run_id)
        if isinstance(record, dict) and isinstance(record.get("monitor"), dict):
            monitor = dict(record["monitor"])
        monitor["kickoff_status"] = "sent"
        monitor["kickoff_reason"] = reason
        monitor["kickoff_result"] = {"status": "ok", "jobId": monitor.get("cron_job_id")}
        return {"status": "sent", "monitor": monitor, "kickoff_result": monitor["kickoff_result"]}

    def stop_run_monitor(self, run_id: str, *, reason: str = "pm monitor-stop") -> dict:
        monitor = {}
        record = self.run_records.get(run_id)
        if isinstance(record, dict) and isinstance(record.get("monitor"), dict):
            monitor = dict(record["monitor"])
        monitor["status"] = "stopped"
        monitor["stop_reason"] = reason
        return {"status": "stopped", "monitor": monitor, "remove_result": {"status": "ok"}}


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
        self.assertTrue(any("fell back to backend=codex-cli" in item for item in payload["warnings"]))
        self.assertIn("PM 执行器已确认", payload["runtime_banner"])
        self.assertIn("backend=codex-cli", payload["runtime_banner"])
        self.assertIn("任务 T1", payload["runtime_banner"])
        self.assertIn(f"cwd={api.project_root_path()}", payload["runtime_banner"])
        self.assertEqual(api.last_locked_task_id, "T1")
        self.assertEqual(api.last_written_name, "last-run.json")
        self.assertEqual(api.last_written_payload["backend"], "codex-cli")

    def test_review_targets_latest_run_for_requested_task_not_global_last_run(self) -> None:
        api = _FakeApi()
        handlers = build_command_handlers(api)
        api.write_pm_run_record(
            {
                "run_id": "run-t1",
                "task_id": "T1",
                "task_guid": "guid-T1",
                "review_required": True,
                "review_status": "pending",
                "attempt": 1,
                "review_round": 1,
            },
            run_id="run-t1",
        )
        api.write_pm_run_record(
            {
                "run_id": "run-t2",
                "task_id": "T2",
                "task_guid": "guid-T2",
                "review_required": True,
                "review_status": "pending",
                "attempt": 1,
                "review_round": 1,
            },
            run_id="run-t2",
        )

        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            run_id="",
            verdict="fail",
            feedback="redo",
            feedback_file="",
            reviewer="qa",
        )

        with io.StringIO() as buf, contextlib.redirect_stdout(buf):
            code = handlers["review"](args)
            payload = json.loads(buf.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload["run_id"], "run-t1")
        self.assertEqual(payload["review_status"], "failed")

    def test_complete_targets_requested_tasks_latest_run_not_global_last_run(self) -> None:
        api = _FakeApi()
        handlers = build_command_handlers(api)
        api.write_pm_run_record(
            {
                "run_id": "run-t1",
                "task_id": "T1",
                "task_guid": "guid-T1",
                "backend": "codex-cli",
                "session_key": "main",
                "review_required": True,
                "review_status": "passed",
                "attempt": 1,
                "review_round": 1,
                "monitor": {"status": "active", "run_id": "run-t1"},
            },
            run_id="run-t1",
        )
        api.write_pm_run_record(
            {
                "run_id": "run-t2",
                "task_id": "T2",
                "task_guid": "guid-T2",
                "backend": "codex-cli",
                "session_key": "main",
                "review_required": True,
                "review_status": "pending",
                "attempt": 1,
                "review_round": 1,
                "monitor": {"status": "active", "run_id": "run-t2"},
            },
            run_id="run-t2",
        )
        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            include_completed=False,
            content="done",
            content_file="",
            file=[],
            commit_url="",
            skip_head_commit_url=True,
            force_review_bypass=False,
        )

        with io.StringIO() as buf, contextlib.redirect_stdout(buf):
            code = handlers["complete"](args)
            payload = json.loads(buf.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload["task_id"], "T1")
        self.assertEqual(payload["monitor_stop"]["monitor"]["run_id"], "run-t1")
        self.assertEqual(api.last_written_run_id, "run-t1")

    def test_cmd_run_auto_switches_default_codex_cli_to_acp_for_brownfield_bundle(self) -> None:
        api = _FakeApi()
        api._coder_config["auto_switch_to_acp"] = True
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
        self.assertIn("PM 执行器已确认", payload["runtime_banner"])
        self.assertIn("backend=acp", payload["runtime_banner"])

    def test_cmd_run_blocks_explicit_acp_when_permission_mode_is_not_writable(self) -> None:
        api = _FakeApi()
        api.openclaw_config = lambda: {"plugins": {"entries": {"acpx": {"config": {"permissionMode": "approve-reads"}}}}}
        handlers = build_command_handlers(api)
        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            backend="acp",
            agent="codex",
            timeout=120,
            thinking="high",
            session_key="main",
        )

        with self.assertRaises(SystemExit) as ctx:
            handlers["run"](args)

        self.assertIn("blocked before ACP dispatch", str(ctx.exception))
        self.assertEqual(api.spawn_calls, 0)
        self.assertEqual(api.codex_calls, 0)

    def test_cmd_run_auto_downgrades_acp_when_permission_mode_is_not_writable(self) -> None:
        api = _FakeApi()
        api._coder_config["backend"] = "acp"
        api.openclaw_config = lambda: {"plugins": {"entries": {"acpx": {"config": {"permissionMode": "approve-reads"}}}}}
        handlers = build_command_handlers(api)
        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            backend="",
            agent="codex",
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
        self.assertEqual(api.spawn_calls, 0)
        self.assertEqual(api.codex_calls, 1)
        self.assertIn("fell back to backend=codex-cli", payload["warnings"][0])

    def test_cmd_run_blocks_when_bundle_repo_hint_disagrees_with_cwd(self) -> None:
        api = _FakeApi()
        api.last_bundle = {
            "project": {"repo_root": "/tmp/other-repo"},
            "current_task": {"task_id": "T1", "guid": "guid-T1", "summary": "Task 1"},
        }
        handlers = build_command_handlers(api)
        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            backend="codex-cli",
            agent="codex",
            timeout=120,
            thinking="high",
            session_key="main",
        )

        with self.assertRaises(SystemExit) as ctx:
            handlers["run"](args)

        self.assertIn("repo_root / cwd mismatch", str(ctx.exception))
        self.assertEqual(api.codex_calls, 0)

    def test_cmd_run_reviewed_starts_monitor_for_acp(self) -> None:
        api = _FakeApi()

        def _spawn_ok(**kwargs):
            api.spawn_calls += 1
            return {"status": "accepted", "result": {"details": {"childSessionKey": "child-1", "runId": "run-1"}}}

        api.spawn_acp_session = _spawn_ok
        api.persist_dispatch_side_effects = lambda bundle, result, *, agent_id, runtime: {"session_key": "child-1", "run_id": "run-1"}
        handlers = build_command_handlers(api)
        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            backend="acp",
            agent="codex",
            timeout=120,
            thinking="high",
            session_key="main",
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = handlers["run_reviewed"](args)

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["monitor"]["status"], "active")
        self.assertEqual(payload["monitor_status"], "active")
        self.assertEqual(payload["monitor"]["cron_job_id"], "job-run-1")
        self.assertEqual(payload["monitor"]["kickoff_status"], "sent")
        self.assertIn("pm run-reviewed", payload["monitor"]["kickoff_reason"])

    def test_cmd_run_reviewed_starts_monitor_for_codex_cli(self) -> None:
        api = _FakeApi()
        handlers = build_command_handlers(api)
        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            backend="codex-cli",
            agent="codex",
            timeout=120,
            thinking="high",
            session_key="main",
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = handlers["run_reviewed"](args)

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["backend"], "codex-cli")
        self.assertEqual(payload["monitor"]["status"], "active")
        self.assertEqual(payload["monitor_status"], "active")
        self.assertEqual(payload["monitor"]["backend"], "codex-cli")
        self.assertEqual(payload["monitor"]["kickoff_status"], "sent")

    def test_cmd_complete_stops_active_monitor(self) -> None:
        api = _FakeApi()
        handlers = build_command_handlers(api)
        api.last_run_record = {
            "task_id": "T1",
            "task_guid": "guid-T1",
            "run_id": "run-1",
            "review_required": True,
            "review_status": "passed",
            "monitor": {"status": "active", "run_id": "run-1", "cron_job_id": "job-run-1"},
        }
        api.run_records["run-1"] = dict(api.last_run_record)
        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            include_completed=False,
            content="done",
            content_file="",
            file=[],
            commit_url="",
            skip_head_commit_url=True,
            force_review_bypass=False,
            repo_root="",
        )
        api.resolve_optional_text_input = lambda content, content_file: content
        api.upload_task_attachments = lambda task, task_id, files: {"status": "skipped", "uploaded_count": 0}
        api.current_head_commit_url = lambda repo_root: ""
        api.build_completion_comment = lambda content, commit_url, uploaded: content
        api.patch_task = lambda guid, payload: {"guid": guid, **payload}

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = handlers["complete"](args)

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["monitor_stop"]["status"], "stopped")

    def test_cmd_run_writes_run_id_from_dispatch_side_effects(self) -> None:
        api = _FakeApi()
        api._coder_config["auto_switch_to_acp"] = True
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

    def test_cmd_run_reviewed_writes_pending_review_metadata(self) -> None:
        api = _FakeApi()
        handlers = build_command_handlers(api)
        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            backend="codex-cli",
            agent="codex",
            timeout=120,
            thinking="high",
            session_key="main",
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = handlers["run_reviewed"](args)

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["review_required"], True)
        self.assertEqual(payload["review_status"], "pending")
        self.assertEqual(payload["attempt"], 1)
        self.assertEqual(payload["review_round"], 1)
        self.assertEqual(payload["review_history"], [])
        self.assertTrue(str(payload["run_id"]).startswith("run-"))
        self.assertEqual(api.last_written_run_id, payload["run_id"])

    def test_cmd_rerun_carries_failed_review_feedback_and_increments_round(self) -> None:
        api = _FakeApi()
        handlers = build_command_handlers(api)
        source_run = {
            "run_id": "run-source",
            "task_id": "T1",
            "task_guid": "guid-T1",
            "review_required": True,
            "review_status": "failed",
            "review_feedback": "Address the missing test coverage.",
            "reviewer": "qa",
            "reviewed_at": "2026-04-09T07:10:00+08:00",
            "review_history": [
                {
                    "verdict": "fail",
                    "review_status": "failed",
                    "feedback": "Address the missing test coverage.",
                    "reviewer": "qa",
                    "reviewed_at": "2026-04-09T07:10:00+08:00",
                }
            ],
            "attempt": 1,
            "review_round": 1,
        }
        api.last_run_record = dict(source_run)
        api.run_records["run-source"] = dict(source_run)
        args = argparse.Namespace(
            task_id="T1",
            task_guid="",
            run_id="",
            backend="codex-cli",
            agent="codex",
            timeout=120,
            thinking="high",
            session_key="main",
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = handlers["rerun"](args)

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["review_required"], True)
        self.assertEqual(payload["review_status"], "pending")
        self.assertEqual(payload["attempt"], 2)
        self.assertEqual(payload["review_round"], 2)
        self.assertEqual(payload["rerun_of_run_id"], "run-source")
        self.assertIn("Address the missing test coverage.", payload["message_preview"])
        self.assertNotEqual(payload["run_id"], "run-source")


if __name__ == "__main__":
    unittest.main()

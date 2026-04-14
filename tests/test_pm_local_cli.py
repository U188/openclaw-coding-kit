from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PM_SCRIPT = REPO_ROOT / "skills" / "pm" / "scripts" / "pm.py"
REPO_FAKE_BRIDGE = REPO_ROOT / "examples" / "fake-openclaw-lark-bridge.py"


class PmLocalCliTest(unittest.TestCase):
    @staticmethod
    def _write_planning_scaffold(root: Path) -> None:
        planning = root / ".planning"
        planning.mkdir(parents=True)
        for name in ("PROJECT.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md"):
            (planning / name).write_text(f"# {name}\n", encoding="utf-8")

    @staticmethod
    def _write_fake_acpx(root: Path) -> Path:
        script = root / "acpx"
        script.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    "exit 0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return script

    def _build_monitor_cli_harness(self, root: Path) -> tuple[Path, dict[str, str]]:
        self._write_planning_scaffold(root)
        (root / "openclaw.json").write_text(
            json.dumps(
                {
                    "plugins": {
                        "entries": {
                            "acpx": {
                                "config": {
                                    "permissionMode": "approve-all",
                                }
                            }
                        }
                    }
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        config = {
            "repo_root": str(root),
            "project": {"name": "demo"},
            "task": {"backend": "local", "tasklist_name": "demo", "prefix": "T", "kind": "task"},
            "doc": {"backend": "repo", "folder_name": "demo"},
            "coder": {"backend": "acp", "agent_id": "codex", "timeout": 60, "thinking": "high", "session_key": "main"},
            "review": {"required": True, "enforce_on_complete": True, "sync_comment": True, "sync_state": True},
        }
        config_path = root / "pm.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_fake_acpx(root)
        fake_openclaw = self._write_fake_openclaw(root)
        fake_codex = root / "fake-codex"
        fake_codex.write_text(
            "#!/bin/sh\n"
            "out=\"\"\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  if [ \"$1\" = \"-o\" ]; then\n"
            "    shift\n"
            "    out=\"$1\"\n"
            "  fi\n"
            "  shift\n"
            "done\n"
            "if [ -n \"$out\" ]; then\n"
            "  printf '%s\\n' 'worker ok' > \"$out\"\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_codex.chmod(0o755)
        env = os.environ.copy()
        env["OPENCLAW_LARK_BRIDGE_SCRIPT"] = str(REPO_FAKE_BRIDGE)
        env["OPENCLAW_BIN"] = str(fake_openclaw)
        env["FAKE_BRIDGE_STATE_PATH"] = str(root / ".pm" / "fake-bridge-log.json")
        env["CODEX_BIN"] = str(fake_codex)
        env["PATH"] = str(root) + os.pathsep + env.get("PATH", "")
        return config_path, env

    @staticmethod
    def _write_fake_openclaw(root: Path) -> Path:
        script = root / "openclaw"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "state_path = Path(os.environ.get('FAKE_BRIDGE_STATE_PATH', '.pm/fake-bridge-log.json'))\n"
            "state = {}\n"
            "if state_path.exists():\n"
            "    try:\n"
            "        state = json.loads(state_path.read_text(encoding='utf-8'))\n"
            "    except Exception:\n"
            "        state = {}\n"
            "responses = state.setdefault('agent_turn_responses', [])\n"
            "if len(sys.argv) > 1 and sys.argv[1] == 'agent' and responses:\n"
            "    response = responses.pop(0)\n"
            "    state_path.parent.mkdir(parents=True, exist_ok=True)\n"
            "    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')\n"
            "    print(json.dumps(response, ensure_ascii=False))\n"
            "    raise SystemExit(0)\n"
            "print(json.dumps({'status':'ok','summary':'completed','result':{'payloads':[{'text':'openclaw worker ok','mediaUrl':None}]}}))\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return script

    def _run_pm(self, root: Path, config_path: Path, env: dict[str, str], *args: str, check: bool = True):
        return subprocess.run(
            ["python3", str(PM_SCRIPT), "--config", str(config_path), *args],
            cwd=str(root),
            text=True,
            capture_output=True,
            check=check,
            env=env,
        )

    def _bridge_log(self, root: Path) -> dict:
        return json.loads((root / ".pm" / "fake-bridge-log.json").read_text(encoding="utf-8"))

    def test_run_requires_explicit_task_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            proc = self._run_pm(root, config_path, env, "run", "--backend", "codex-cli", "--agent", "codex", check=False)

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("requires explicit --task-id or --task-guid", proc.stderr)
            self.assertIn("pm start-work", proc.stderr)

    def test_run_blocks_guarded_managed_work_and_points_to_run_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            self._run_pm(root, config_path, env, "create", "--summary", "UI build verification code task")
            proc = self._run_pm(
                root,
                config_path,
                env,
                "run",
                "--task-id",
                "T1",
                "--backend",
                "codex-cli",
                "--agent",
                "codex",
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("pm run blocked: reviewed gate required", proc.stderr)
            self.assertIn("pm run-reviewed", proc.stderr)

    def test_start_work_blocks_guarded_managed_work_without_reviewed_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            proc = self._run_pm(
                root,
                config_path,
                env,
                "start-work",
                "--summary",
                "Land PM-first gate",
                "--request",
                "Need tracked code changes across multiple files and test coverage",
                "--backend",
                "codex-cli",
                "--agent",
                "codex",
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("pm start-work blocked: reviewed gate required", proc.stderr)
            self.assertIn("pm start-work --reviewed", proc.stderr)

    def test_start_work_creates_bound_task_kickoff_comment_and_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            proc = self._run_pm(
                root,
                config_path,
                env,
                "start-work",
                "--summary",
                "Land PM-first gate",
                "--request",
                "Need a tracked intake + dispatch command",
                "--reviewed",
                "--backend",
                "codex-cli",
                "--agent",
                "codex",
            )
            payload = json.loads(proc.stdout)

            self.assertEqual(payload["task_id"], "T1")
            self.assertTrue(payload["created"])
            self.assertEqual(payload["dispatch"]["task_id"], "T1")
            self.assertEqual(payload["dispatch"]["review_status"], "pending")
            self.assertTrue(payload["dispatch"]["run_id"])
            self.assertEqual(payload["dispatch"]["execution_phase"], "monitor")
            self.assertIn(f"run_id: {payload['dispatch']['run_id']}", payload["kickoff_comment"]["content"])
            self.assertIn("monitor_status:", payload["kickoff_comment"]["content"])
            self.assertIn("显式 task 绑定已建立", payload["kickoff_comment"]["content"])
            self.assertEqual(payload["current_task"]["task_id"], "T1")

            task_detail = json.loads(
                self._run_pm(root, config_path, env, "get", "--task-id", "T1").stdout
            )
            comments = task_detail.get("comments") or []
            self.assertTrue(any(f"run_id: {payload['dispatch']['run_id']}" in str(item.get("content") or "") for item in comments))

    def test_install_assets_copies_repo_runtime_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)
            codex_home = root / "codex-home"
            workspace_root = root / "workspace"

            proc = self._run_pm(
                root,
                config_path,
                env,
                "install-assets",
                "--codex-home",
                str(codex_home),
                "--workspace-root",
                str(workspace_root),
            )
            payload = json.loads(proc.stdout)

            self.assertEqual(payload["status"], "installed")
            self.assertTrue((codex_home / "skills" / "pm" / "SKILL.md").exists())
            self.assertTrue((workspace_root / "skills" / "pm" / "SKILL.md").exists())
            self.assertTrue((workspace_root / "plugins" / "acp-progress-bridge").exists())

    def test_local_backend_supports_attachment_and_complete_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            planning = root / ".planning"
            planning.mkdir(parents=True)
            for name in ("PROJECT.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md"):
                (planning / name).write_text(f"# {name}\n", encoding="utf-8")
            config = {
                "repo_root": str(root),
                "project": {"name": "demo"},
                "task": {"backend": "local", "tasklist_name": "demo", "prefix": "T", "kind": "task"},
                "doc": {"backend": "repo", "folder_name": "demo"},
                "coder": {"backend": "codex-cli", "agent_id": "codex", "timeout": 60, "thinking": "high", "session_key": "main"},
            }
            config_path = root / "pm.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            evidence_file = root / "evidence.txt"
            evidence_file.write_text("evidence", encoding="utf-8")

            def run(*args: str) -> dict:
                proc = subprocess.run(
                    ["python3", str(PM_SCRIPT), "--config", str(config_path), *args],
                    cwd=str(root),
                    text=True,
                    capture_output=True,
                    check=True,
                )
                return json.loads(proc.stdout)

            created = run("create", "--summary", "Lifecycle task")
            self.assertEqual(created["task_id"], "T1")

            upload = run("upload-attachments", "--task-id", "T1", "--file", str(evidence_file))
            self.assertEqual(upload["status"], "ok")
            self.assertEqual(upload["backend"], "local")
            self.assertEqual(upload["uploaded_count"], 1)

            listed = run("attachments", "--task-id", "T1")
            self.assertEqual(listed["backend"], "local")
            self.assertEqual(listed["attachment_count"], 1)
            self.assertEqual(listed["attachments"][0]["name"], "evidence.txt")

            completed = run("complete", "--task-id", "T1", "--content", "done locally")
            self.assertEqual(completed["task_id"], "T1")
            task = run("get", "--task-id", "T1", "--include-completed")
            self.assertTrue(bool(task["completed_at"]))
            self.assertEqual(len(task["attachments"]), 1)
            self.assertTrue(any("done locally" in str(item.get("content") or "") for item in task["comments"]))

    def test_complete_finalizes_last_run_cleanup_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            planning = root / ".planning"
            planning.mkdir(parents=True)
            for name in ("PROJECT.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md"):
                (planning / name).write_text(f"# {name}\n", encoding="utf-8")
            config = {
                "repo_root": str(root),
                "project": {"name": "demo"},
                "task": {"backend": "local", "tasklist_name": "demo", "prefix": "T", "kind": "task"},
                "doc": {"backend": "repo", "folder_name": "demo"},
                "coder": {"backend": "codex-cli", "agent_id": "codex", "timeout": 60, "thinking": "high", "session_key": "main", "acp_cleanup": "delete"},
            }
            config_path = root / "pm.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

            def run(*args: str) -> dict:
                proc = subprocess.run(
                    ["python3", str(PM_SCRIPT), "--config", str(config_path), *args],
                    cwd=str(root),
                    text=True,
                    capture_output=True,
                    check=True,
                )
                return json.loads(proc.stdout)

            created = run("create", "--summary", "Cleanup lifecycle task")
            task_guid = str(created["task"].get("guid") or "")
            pm_dir = root / ".pm"
            pm_dir.mkdir(parents=True, exist_ok=True)
            last_run_path = pm_dir / "last-run.json"
            last_run_path.write_text(
                json.dumps(
                    {
                        "task_id": "T1",
                        "task_guid": task_guid,
                        "backend": "acp",
                        "session_key": "agent:codex:acp:demo",
                        "acp_cleanup": "delete",
                        "run_id": "run-cleanup-demo",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            completed = run("complete", "--task-id", "T1", "--content", "done with cleanup")
            self.assertEqual(completed["cleanup_result"]["status"], "finalized")
            self.assertEqual(completed["cleanup_result"]["acp_cleanup"], "delete")
            self.assertEqual(completed["cleanup_result"]["session_cleanup_state"], "auto-delete-on-run-exit")

            last_run = json.loads(last_run_path.read_text(encoding="utf-8"))
            self.assertEqual(last_run["finalized_by"], "pm complete")
            self.assertEqual(last_run["cleanup_result"]["status"], "finalized")
            self.assertEqual(last_run["cleanup_result"]["owned_artifacts"]["run_record"], "kept")
            self.assertEqual(last_run["cleanup_result"]["owned_artifacts"]["acp_session"], "auto-delete-on-run-exit")

    def test_reviewed_flow_requires_pass_or_explicit_bypass_before_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            planning = root / ".planning"
            planning.mkdir(parents=True)
            for name in ("PROJECT.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md"):
                (planning / name).write_text(f"# {name}\n", encoding="utf-8")
            config = {
                "repo_root": str(root),
                "project": {"name": "demo"},
                "task": {"backend": "local", "tasklist_name": "demo", "prefix": "T", "kind": "task"},
                "doc": {"backend": "repo", "folder_name": "demo"},
                "coder": {"backend": "codex-cli", "agent_id": "codex", "timeout": 60, "thinking": "high", "session_key": "main"},
                "review": {"required": True, "enforce_on_complete": True, "sync_comment": True, "sync_state": True},
            }
            config_path = root / "pm.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            fake_codex = root / "fake-codex"
            fake_codex.write_text(
                "#!/bin/sh\n"
                "out=\"\"\n"
                "while [ \"$#\" -gt 0 ]; do\n"
                "  if [ \"$1\" = \"-o\" ]; then\n"
                "    shift\n"
                "    out=\"$1\"\n"
                "  fi\n"
                "  shift\n"
                "done\n"
                "if [ -n \"$out\" ]; then\n"
                "  printf '%s\\n' 'worker ok' > \"$out\"\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            env = os.environ.copy()
            env["CODEX_BIN"] = str(fake_codex)

            def run_ok(*args: str) -> dict:
                proc = subprocess.run(
                    ["python3", str(PM_SCRIPT), "--config", str(config_path), *args],
                    cwd=str(root),
                    text=True,
                    capture_output=True,
                    check=True,
                    env=env,
                )
                return json.loads(proc.stdout)

            def run_fail(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["python3", str(PM_SCRIPT), "--config", str(config_path), *args],
                    cwd=str(root),
                    text=True,
                    capture_output=True,
                    check=False,
                    env=env,
                )

            created = run_ok("create", "--summary", "Reviewed task")
            self.assertEqual(created["task_id"], "T1")

            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "codex-cli", "--agent", "codex")
            self.assertEqual(first_run["review_status"], "pending")
            self.assertEqual(first_run["review_required"], True)

            blocked_pending = run_fail("complete", "--task-id", "T1", "--content", "should block")
            self.assertNotEqual(blocked_pending.returncode, 0)
            self.assertIn("manual review gate", blocked_pending.stderr)

            failed_review = run_ok(
                "review",
                "--task-id",
                "T1",
                "--verdict",
                "fail",
                "--feedback",
                "Add regression coverage",
                "--reviewer",
                "qa",
            )
            self.assertEqual(failed_review["review_status"], "failed")
            self.assertEqual(failed_review["review_feedback"], "Add regression coverage")

            blocked_failed = run_fail("complete", "--task-id", "T1", "--content", "still blocked")
            self.assertNotEqual(blocked_failed.returncode, 0)
            self.assertIn("manual review gate", blocked_failed.stderr)
            self.assertIn("Add regression coverage", blocked_failed.stderr)

            rerun = run_ok("rerun", "--task-id", "T1", "--backend", "codex-cli", "--agent", "codex")
            self.assertEqual(rerun["review_status"], "pending")
            self.assertEqual(rerun["attempt"], 2)
            self.assertEqual(rerun["review_round"], 2)
            self.assertEqual(rerun["rerun_of_run_id"], first_run["run_id"])

            passed_review = run_ok(
                "review",
                "--task-id",
                "T1",
                "--verdict",
                "pass",
                "--evidence",
                "pytest -q -> 3 passed",
                "--reviewer",
                "qa",
            )
            self.assertEqual(passed_review["review_status"], "passed")
            self.assertEqual(passed_review["verification_status"], "verified")
            self.assertIn("pytest -q -> 3 passed", passed_review["verification_evidence"])
            self.assertEqual(len(passed_review["review_history"]), 2)

            completed = run_ok("complete", "--task-id", "T1", "--content", "done after pass")
            self.assertEqual(completed["task_id"], "T1")

            bypass_task = run_ok("create", "--summary", "Bypass task")
            bypass_run = run_ok("run-reviewed", "--task-id", bypass_task["task_id"], "--backend", "codex-cli", "--agent", "codex")
            self.assertEqual(bypass_run["review_status"], "pending")

            bypass_complete = run_ok(
                "complete",
                "--task-id",
                bypass_task["task_id"],
                "--content",
                "forced completion",
                "--force-review-bypass",
            )
            self.assertEqual(bypass_complete["review_bypass"]["status"], "bypassed")
            last_run = json.loads((root / ".pm" / "last-run.json").read_text(encoding="utf-8"))
            self.assertEqual(last_run["review_status"], "bypassed")
            self.assertTrue(last_run["review_bypassed"])

    def test_run_reviewed_creates_monitor_for_acp_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            created = run_ok("create", "--summary", "Monitor task")
            self.assertEqual(created["task_id"], "T1")

            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "acp", "--agent", "codex")
            self.assertEqual(first_run["monitor_status"], "active")
            self.assertEqual(first_run["monitor"]["status"], "active")
            self.assertEqual(first_run["monitor"]["watch_mode"], "child-session")
            self.assertTrue(first_run["monitor"]["cron_job_id"])
            self.assertEqual(first_run["monitor"]["kickoff_status"], "disabled")
            monitor_status = run_ok("monitor-status", "--task-id", "T1")
            self.assertEqual(monitor_status["monitor_status"], "active")
            self.assertEqual(monitor_status["monitor"]["status"], "active")
            self.assertEqual(monitor_status["monitor"]["run_id"], first_run["run_id"])
            monitor_file = root / ".pm" / "monitors" / f"{first_run['run_id']}.json"
            self.assertTrue(monitor_file.exists())
            bridge_calls = self._bridge_log(root)["calls"]
            cron_add = next(item for item in bridge_calls if item["tool"] == "cron" and item["action"] == "add")
            job = cron_add["args"]["job"]
            self.assertEqual(job["payload"]["kind"], "agentTurn")
            self.assertEqual(job["sessionTarget"], "isolated")
            self.assertEqual(job["schedule"]["kind"], "every")
            self.assertTrue(any(item["tool"] == "cron" and item["action"] == "list" for item in bridge_calls))
            self.assertFalse(any(item["tool"] == "cron" and item["action"] == "run" for item in bridge_calls))

    def test_run_reviewed_creates_monitor_for_codex_cli_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "Sync monitor task")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "codex-cli", "--agent", "codex")
            self.assertEqual(first_run["monitor_status"], "active")
            self.assertEqual(first_run["monitor"]["status"], "active")
            self.assertEqual(first_run["monitor"]["watch_mode"], "run-record")
            self.assertTrue(first_run["monitor"]["cron_job_id"])
            self.assertEqual(first_run["monitor"]["kickoff_status"], "disabled")
            monitor_file = root / ".pm" / "monitors" / f"{first_run['run_id']}.json"
            self.assertTrue(monitor_file.exists())
            monitor_status = run_ok("monitor-status", "--run-id", first_run["run_id"])
            self.assertEqual(monitor_status["monitor_status"], "active")
            self.assertEqual(monitor_status["monitor"]["status"], "active")
            self.assertEqual(monitor_status["monitor"]["backend"], "codex-cli")

    def test_run_reviewed_creates_monitor_for_openclaw_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)
            self._write_fake_openclaw(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "OpenClaw monitor task")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "openclaw", "--agent", "front")
            self.assertEqual(first_run["backend"], "openclaw")
            self.assertEqual(first_run["monitor"]["status"], "active")
            self.assertEqual(first_run["monitor"]["backend"], "openclaw")
            self.assertEqual(first_run["monitor"]["kickoff_status"], "disabled")
            monitor_status = run_ok("monitor-status", "--task-id", "T1")
            self.assertEqual(monitor_status["monitor"]["run_id"], first_run["run_id"])
            self.assertEqual(monitor_status["monitor"]["backend"], "openclaw")

    def test_run_reviewed_marks_monitor_cron_error_when_add_list_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)
            env["FAKE_CRON_ADD_LIST_MISMATCH"] = "1"

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "Monitor mismatch task")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "codex-cli", "--agent", "codex")
            self.assertEqual(first_run["monitor_status"], "cron-error")
            self.assertEqual(first_run["monitor"]["status"], "cron-error")
            self.assertEqual(first_run["monitor"]["status_reason"], "cron-job-missing")
            self.assertEqual(first_run["monitor"]["kickoff_status"], "disabled")
            monitor_status = run_ok("monitor-status", "--run-id", first_run["run_id"])
            self.assertEqual(monitor_status["monitor_status"], "cron-error")
            self.assertEqual(monitor_status["monitor"]["status"], "cron-error")

    def test_monitor_status_persists_cron_error_when_job_is_lost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "Monitor lost job task")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "acp", "--agent", "codex")
            bridge_state = self._bridge_log(root)
            bridge_state["jobs"] = []
            (root / ".pm" / "fake-bridge-log.json").write_text(json.dumps(bridge_state, ensure_ascii=False, indent=2), encoding="utf-8")

            monitor_status = run_ok("monitor-status", "--run-id", first_run["run_id"])
            self.assertEqual(monitor_status["monitor_status"], "cron-error")
            self.assertEqual(monitor_status["monitor"]["status"], "cron-error")
            self.assertEqual(monitor_status["monitor"]["status_reason"], "cron-job-missing")

            run_record = json.loads((root / ".pm" / "runs" / f"{first_run['run_id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(run_record["monitor_status"], "cron-error")
            self.assertEqual(run_record["monitor"]["status"], "cron-error")

    def test_monitor_status_bridges_failed_child_session_into_run_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "ACP bridge failed child")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "acp", "--agent", "codex")
            child_key = first_run["monitor"]["child_session_key"]
            bridge_state = self._bridge_log(root)
            bridge_state.setdefault("session_statuses", {})[child_key] = {
                "ok": True,
                "result": {
                    "details": {
                        "sessionKey": child_key,
                        "status": "failed",
                        "endedAt": "2026-04-12T01:00:00Z",
                        "lastError": "acpx exited with code 1",
                        "acp": {"state": "error"},
                    }
                },
            }
            (root / ".pm" / "fake-bridge-log.json").write_text(json.dumps(bridge_state, ensure_ascii=False, indent=2), encoding="utf-8")

            monitor_status = run_ok("monitor-status", "--run-id", first_run["run_id"])
            self.assertEqual(monitor_status["monitor"]["child_session_bridge_status"], "bridged")
            self.assertEqual(monitor_status["monitor"]["child_session_terminal_status"], "failed")

            run_record = json.loads((root / ".pm" / "runs" / f"{first_run['run_id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(run_record["execution_step"], "worker-terminal-state-bridged")
            self.assertEqual(run_record["child_session_terminal_status"], "failed")
            self.assertEqual(run_record["error"], "acpx exited with code 1")
            self.assertTrue(run_record["worker_done_at"])
            self.assertTrue(run_record["bridge_done_at"])

    def test_monitor_status_falls_back_to_local_agent_session_registry_when_bridge_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)
            openclaw_home = root / ".openclaw"
            sessions_dir = openclaw_home / "agents" / "codex" / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            env["OPENCLAW_HOME"] = str(openclaw_home)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "ACP local registry fallback")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "acp", "--agent", "codex")
            child_key = first_run["monitor"]["child_session_key"]

            bridge_state = self._bridge_log(root)
            bridge_state.setdefault("session_statuses", {})[child_key] = {
                "ok": False,
                "error": "Agent-to-agent session status denied by tools.agentToAgent.allow.",
            }
            (root / ".pm" / "fake-bridge-log.json").write_text(json.dumps(bridge_state, ensure_ascii=False, indent=2), encoding="utf-8")

            (sessions_dir / "sessions.json").write_text(
                json.dumps(
                    {
                        child_key: {
                            "status": "failed",
                            "endedAt": "2026-04-12T01:02:00Z",
                            "sessionFile": str(sessions_dir / "child.jsonl"),
                            "acp": {"state": "error", "lastError": "acpx exited with code 1"},
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            monitor_status = run_ok("monitor-status", "--run-id", first_run["run_id"])
            self.assertEqual(monitor_status["monitor"]["child_session_bridge_status"], "bridged")
            self.assertEqual(monitor_status["monitor"]["child_session_terminal_status"], "failed")

            run_record = json.loads((root / ".pm" / "runs" / f"{first_run['run_id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(run_record["execution_step"], "worker-terminal-state-bridged")
            self.assertEqual(run_record["child_session_terminal_status"], "failed")
            self.assertEqual(run_record["error"], "acpx exited with code 1")
            self.assertTrue(run_record["worker_done_at"])
            self.assertTrue(run_record["bridge_done_at"])

    def test_monitor_status_falls_back_to_local_agent_session_registry_when_bridge_call_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)
            openclaw_home = root / ".openclaw"
            sessions_dir = openclaw_home / "agents" / "codex" / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            env["OPENCLAW_HOME"] = str(openclaw_home)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "ACP local registry fallback after bridge failure")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "acp", "--agent", "codex")
            child_key = first_run["monitor"]["child_session_key"]

            bridge_state = self._bridge_log(root)
            bridge_state.setdefault("session_statuses", {})[child_key] = {
                "_exit_code": 1,
                "_stderr": "session_status bridge returned 500",
            }
            (root / ".pm" / "fake-bridge-log.json").write_text(json.dumps(bridge_state, ensure_ascii=False, indent=2), encoding="utf-8")

            (sessions_dir / "sessions.json").write_text(
                json.dumps(
                    {
                        child_key: {
                            "status": "done",
                            "endedAt": "2026-04-12T01:03:00Z",
                            "sessionFile": str(sessions_dir / "child.jsonl"),
                            "acp": {"state": "idle", "lastError": ""},
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            monitor_status = run_ok("monitor-status", "--run-id", first_run["run_id"])
            self.assertEqual(monitor_status["monitor"]["child_session_bridge_status"], "bridged")
            self.assertEqual(monitor_status["monitor"]["child_session_terminal_status"], "completed")

            run_record = json.loads((root / ".pm" / "runs" / f"{first_run['run_id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(run_record["execution_step"], "worker-terminal-state-bridged")
            self.assertEqual(run_record["child_session_terminal_status"], "completed")
            self.assertEqual(run_record["status"], "completed")
            self.assertEqual(run_record["summary"], "completed")
            self.assertEqual(run_record["result"]["status"], "completed")
            self.assertTrue(run_record["worker_done_at"])
            self.assertTrue(run_record["bridge_done_at"])

    def test_monitor_advance_does_not_wait_forever_after_child_session_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            review_cfg = config.setdefault("review", {})
            review_cfg["backend"] = "openclaw"
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "ACP advance after failed child")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "acp", "--agent", "codex")
            child_key = first_run["monitor"]["child_session_key"]
            bridge_state = self._bridge_log(root)
            bridge_state.setdefault("session_statuses", {})[child_key] = {
                "ok": True,
                "result": {
                    "details": {
                        "sessionKey": child_key,
                        "status": "failed",
                        "endedAt": "2026-04-12T01:00:00Z",
                        "lastError": "acpx exited with code 1",
                        "acp": {"state": "error"},
                    }
                },
            }
            bridge_state.setdefault("agent_turn_responses", []).append(
                {
                    "status": "ok",
                    "result": {
                        "payloads": [
                            {
                                "text": '{"verdict":"fail","feedback":"worker failed after child session bridge","summary":"terminal child session failure propagated","confidence":"high","evidence":["child session status=failed"]}'
                            }
                        ]
                    },
                }
            )
            (root / ".pm" / "fake-bridge-log.json").write_text(json.dumps(bridge_state, ensure_ascii=False, indent=2), encoding="utf-8")

            # Force the run into the exact monitor-advance precondition window:
            # terminal child session already bridged, review still pending.
            run_record_path = root / ".pm" / "runs" / f"{first_run['run_id']}.json"
            run_record = json.loads(run_record_path.read_text(encoding="utf-8"))
            run_record["child_session_terminal_status"] = "failed"
            run_record["execution_step"] = "worker-terminal-state-bridged"
            run_record["worker_done_at"] = run_record.get("worker_done_at") or "2026-04-12T01:00:00Z"
            run_record["bridge_done_at"] = run_record.get("bridge_done_at") or "2026-04-12T01:00:01Z"
            run_record["monitor_status"] = "running"
            run_record["review_status"] = "pending"
            run_record["status"] = "running"
            run_record["result"] = {
                "status": "failed",
                "summary": "worker failed after child session bridge",
                "error": "acpx exited with code 1",
            }
            monitor = run_record.setdefault("monitor", {})
            monitor["status"] = "running"
            monitor["watch_mode"] = "child-session"
            monitor["child_session_key"] = child_key
            monitor["child_session_bridge_status"] = "bridged"
            monitor["child_session_terminal_status"] = "failed"
            run_record_path.write_text(json.dumps(run_record, ensure_ascii=False, indent=2), encoding="utf-8")

            advanced = run_ok("monitor-advance", "--run-id", first_run["run_id"])
            self.assertEqual(advanced["status"], "rerun-started")
            self.assertIn(advanced["review"]["review_status"], {"failed", "fail"})
            self.assertEqual(advanced["rerun"]["review_status"], "pending")

    def test_rerun_stops_previous_monitor_before_starting_new_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "Monitor rerun task")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "acp", "--agent", "codex")
            failed = run_ok("review", "--task-id", "T1", "--verdict", "fail", "--feedback", "redo", "--reviewer", "qa")
            self.assertEqual(failed["review_status"], "failed")

            rerun = run_ok("rerun", "--task-id", "T1", "--backend", "acp", "--agent", "codex")
            self.assertEqual(rerun["monitor"]["status"], "active")
            self.assertEqual(rerun["monitor"]["replaces_run_id"], first_run["run_id"])

    def test_complete_stops_active_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "Monitor complete task")
            run_ok("run-reviewed", "--task-id", "T1", "--backend", "acp", "--agent", "codex")
            run_ok("review", "--task-id", "T1", "--verdict", "pass", "--evidence", "pytest -q -> 3 passed", "--reviewer", "qa")
            completed = run_ok("complete", "--task-id", "T1", "--content", "done after pass")
            self.assertEqual(completed["monitor_stop"]["status"], "stopped")
            last_run = json.loads((root / ".pm" / "last-run.json").read_text(encoding="utf-8"))
            self.assertEqual(last_run["monitor"]["status"], "stopped")
            bridge_calls = self._bridge_log(root)["calls"]
            cron_remove = next(item for item in bridge_calls if item["tool"] == "cron" and item["action"] == "remove")
            self.assertEqual(cron_remove["session_key"], "main")

    def test_complete_stops_active_monitor_for_codex_cli_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "Codex monitor complete task")
            run_ok("run-reviewed", "--task-id", "T1", "--backend", "codex-cli", "--agent", "codex")
            run_ok("review", "--task-id", "T1", "--verdict", "pass", "--evidence", "pytest -q -> 3 passed", "--reviewer", "qa")
            completed = run_ok("complete", "--task-id", "T1", "--content", "done after pass")
            self.assertEqual(completed["monitor_stop"]["status"], "stopped")
            last_run = json.loads((root / ".pm" / "last-run.json").read_text(encoding="utf-8"))
            self.assertEqual(last_run["monitor"]["status"], "stopped")

    def test_monitor_stop_command_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "Monitor stop task")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "acp", "--agent", "codex")
            first = run_ok("monitor-stop", "--run-id", first_run["run_id"], "--reason", "manual close")
            second = run_ok("monitor-stop", "--run-id", first_run["run_id"], "--reason", "manual close")
            self.assertEqual(first["status"], "stopped")
            self.assertEqual(second["status"], "already-stopped")

    def test_review_and_rerun_resolve_latest_run_for_requested_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "Task one")
            run_ok("create", "--summary", "Task two")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "codex-cli", "--agent", "codex")
            second_run = run_ok("run-reviewed", "--task-id", "T2", "--backend", "codex-cli", "--agent", "codex")

            monitor_status = run_ok("monitor-status", "--task-id", "T1")
            self.assertEqual(monitor_status["run_id"], first_run["run_id"])
            self.assertEqual(monitor_status["monitor"]["task_id"], "T1")

            failed_review = run_ok(
                "review",
                "--task-id",
                "T1",
                "--verdict",
                "fail",
                "--feedback",
                "redo T1",
                "--reviewer",
                "qa",
            )
            self.assertEqual(failed_review["run_id"], first_run["run_id"])
            self.assertEqual(failed_review["review_status"], "failed")

            rerun = run_ok("rerun", "--task-id", "T1", "--backend", "codex-cli", "--agent", "codex")
            self.assertEqual(rerun["task_id"], "T1")
            self.assertEqual(rerun["rerun_of_run_id"], first_run["run_id"])
            self.assertNotEqual(rerun["run_id"], second_run["run_id"])

    def test_complete_uses_requested_tasks_latest_run_not_global_last_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, env = self._build_monitor_cli_harness(root)

            def run_ok(*args: str) -> dict:
                proc = self._run_pm(root, config_path, env, *args)
                return json.loads(proc.stdout)

            run_ok("create", "--summary", "Complete task one")
            run_ok("create", "--summary", "Complete task two")
            first_run = run_ok("run-reviewed", "--task-id", "T1", "--backend", "codex-cli", "--agent", "codex")
            run_ok("review", "--task-id", "T1", "--verdict", "pass", "--evidence", "pytest -q -> 3 passed", "--reviewer", "qa")
            second_run = run_ok("run-reviewed", "--task-id", "T2", "--backend", "codex-cli", "--agent", "codex")

            completed = run_ok("complete", "--task-id", "T1", "--content", "done after pass")
            self.assertEqual(completed["task_id"], "T1")
            self.assertEqual(completed["monitor_stop"]["status"], "stopped")
            self.assertEqual(completed["monitor_stop"]["monitor"]["run_id"], first_run["run_id"])

            last_run = json.loads((root / ".pm" / "last-run.json").read_text(encoding="utf-8"))
            self.assertEqual(last_run["run_id"], first_run["run_id"])
            latest_t2 = json.loads((root / ".pm" / "runs" / f"{second_run['run_id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(latest_t2["review_status"], "pending")

    def test_repo_root_prefers_target_repo_pm_json_without_explicit_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other_tmp:
            root = Path(tmp)
            outside = Path(other_tmp)
            planning = root / ".planning"
            planning.mkdir(parents=True)
            for name in ("PROJECT.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md"):
                (planning / name).write_text(f"# {name}\n", encoding="utf-8")
            config = {
                "repo_root": str(root),
                "project": {"name": "demo"},
                "task": {"backend": "local", "tasklist_name": "demo", "prefix": "T", "kind": "task"},
                "doc": {"backend": "repo", "folder_name": "demo"},
                "coder": {"backend": "codex-cli", "agent_id": "codex", "timeout": 60, "thinking": "high", "session_key": "main"},
            }
            (root / "pm.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

            proc = subprocess.run(
                [
                    "python3",
                    str(PM_SCRIPT),
                    "create",
                    "--repo-root",
                    str(root),
                    "--summary",
                    "Repo root config task",
                ],
                cwd=str(outside),
                text=True,
                capture_output=True,
                check=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["task_id"], "T1")
            self.assertEqual(payload["task"]["tasklists"][0]["tasklist_guid"], "local:demo")
            self.assertTrue(str(payload["context_path"]).startswith(str(root / ".pm")))

    def test_init_with_repo_root_writes_config_and_context_into_target_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other_tmp:
            root = Path(tmp)
            outside = Path(other_tmp)
            planning = root / ".planning"
            planning.mkdir(parents=True)
            for name in ("PROJECT.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md"):
                (planning / name).write_text(f"# {name}\n", encoding="utf-8")

            proc = subprocess.run(
                [
                    "python3",
                    str(PM_SCRIPT),
                    "init",
                    "--repo-root",
                    str(root),
                    "--project-name",
                    "demo",
                    "--task-backend",
                    "local",
                    "--doc-backend",
                    "repo",
                    "--write-config",
                    "--skip-auto-run",
                    "--skip-bootstrap-task",
                    "--no-auth-bundle",
                ],
                cwd=str(outside),
                text=True,
                capture_output=True,
                check=True,
            )
            payload = json.loads(proc.stdout)

            self.assertEqual(payload["repo_root"], str(root))
            self.assertEqual(payload["config_path"], str(root / "pm.json"))
            self.assertTrue((root / "pm.json").exists())
            self.assertFalse((outside / "pm.json").exists())

    def test_init_in_copied_repo_rewrites_stale_repo_root_to_current_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            planning = root / ".planning"
            planning.mkdir(parents=True)
            for name in ("PROJECT.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md"):
                (planning / name).write_text(f"# {name}\n", encoding="utf-8")
            (root / "pm.json").write_text(
                json.dumps(
                    {
                        "project": {"name": "demo"},
                        "repo_root": "/tmp/original-repo",
                        "task": {"backend": "local", "tasklist_name": "demo", "prefix": "T", "kind": "task"},
                        "doc": {"backend": "repo", "folder_name": "demo"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    "python3",
                    str(PM_SCRIPT),
                    "init",
                    "--project-name",
                    "demo",
                    "--task-backend",
                    "local",
                    "--doc-backend",
                    "repo",
                    "--write-config",
                    "--skip-auto-run",
                    "--skip-bootstrap-task",
                    "--no-auth-bundle",
                ],
                cwd=str(root),
                text=True,
                capture_output=True,
                check=True,
            )
            payload = json.loads(proc.stdout)
            written = json.loads((root / "pm.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["repo_root"], str(root))
            self.assertEqual(payload["config_path"], str(root / "pm.json"))
            self.assertEqual(written["repo_root"], str(root))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PM_SCRIPT = REPO_ROOT / "skills" / "pm" / "scripts" / "pm.py"


class PmLocalCliTest(unittest.TestCase):
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
            self.assertIn("review gate", blocked_pending.stderr)

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
            self.assertIn("review gate", blocked_failed.stderr)
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
                "--reviewer",
                "qa",
            )
            self.assertEqual(passed_review["review_status"], "passed")
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


if __name__ == "__main__":
    unittest.main()

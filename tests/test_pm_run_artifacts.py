from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "pm" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pm
from pm_commands import build_command_handlers


class PmRunArtifactsTest(unittest.TestCase):
    def test_write_pm_run_record_writes_last_run_and_run_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pm_dir = root / ".pm"
            with mock.patch("pm.project_root_path", return_value=root), mock.patch("pm.pm_dir_path", return_value=pm_dir), mock.patch("pm.pm_file", side_effect=lambda name: pm_dir / name):
                payload = {"backend": "acp", "run_id": "run-xyz", "ok": True}
                written = pm.write_pm_run_record(payload, run_id="run-xyz")
            last_run = root / ".pm" / "last-run.json"
            run_file = root / ".pm" / "runs" / "run-xyz.json"
            self.assertEqual(written, [last_run, run_file])
            self.assertEqual(json.loads(last_run.read_text(encoding="utf-8"))["run_id"], "run-xyz")
            self.assertEqual(json.loads(run_file.read_text(encoding="utf-8"))["run_id"], "run-xyz")

    def test_task_run_lock_blocks_duplicate_task(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pm_dir = root / ".pm"
            with mock.patch("pm.pm_dir_path", return_value=pm_dir):
                with pm.task_run_lock("T9"):
                    with self.assertRaises(SystemExit) as ctx:
                        with pm.task_run_lock("T9"):
                            pass
            self.assertIn("task already running", str(ctx.exception))

    def test_task_run_lock_reclaims_stale_pid_lock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pm_dir = root / ".pm"
            lock_dir = pm_dir / "locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            lock_path = lock_dir / "t9.lock"
            lock_path.write_text(json.dumps({"task_id": "T9", "pid": "999999"}, ensure_ascii=False), encoding="utf-8")
            with mock.patch("pm.pm_dir_path", return_value=pm_dir):
                with pm.task_run_lock("T9") as acquired:
                    self.assertEqual(acquired, lock_path)
                    self.assertTrue(lock_path.exists())
            self.assertFalse(lock_path.exists())

    def test_task_scoped_run_lookup_prefers_runs_directory_over_global_last_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pm_dir = root / ".pm"
            runs_dir = pm_dir / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            (pm_dir / "last-run.json").write_text(
                json.dumps({"run_id": "run-t2", "task_id": "T2", "task_guid": "guid-T2"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (runs_dir / "run-t1.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-t1",
                        "task_id": "T1",
                        "task_guid": "guid-T1",
                        "review_required": True,
                        "review_status": "pending",
                        "monitor": {"status": "active", "run_id": "run-t1"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (runs_dir / "run-t2.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-t2",
                        "task_id": "T2",
                        "task_guid": "guid-T2",
                        "review_required": True,
                        "review_status": "pending",
                        "monitor": {"status": "active", "run_id": "run-t2"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            class _Api:
                def pm_file(self, name: str) -> Path:
                    return pm_dir / name

                def pm_dir_path(self) -> Path:
                    return pm_dir

                def load_json_file(self, path: Path):
                    try:
                        return json.loads(path.read_text(encoding="utf-8"))
                    except FileNotFoundError:
                        return None

                def default_config(self) -> dict:
                    return {"review": {}, "monitor": {}}

            handlers = build_command_handlers(_Api())
            args = type("Args", (), {"task_id": "T1", "task_guid": "", "run_id": ""})()

            with mock.patch("builtins.print") as mocked_print:
                code = handlers["monitor_status"](args)

            self.assertEqual(code, 0)
            payload = json.loads(mocked_print.call_args.args[0])
            self.assertEqual(payload["run_id"], "run-t1")
            self.assertEqual(payload["monitor"]["run_id"], "run-t1")

    def test_task_scoped_run_lookup_prefers_latest_task_run_over_matching_last_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pm_dir = root / ".pm"
            runs_dir = pm_dir / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            (pm_dir / "last-run.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-t1-old",
                        "task_id": "T1",
                        "task_guid": "guid-T1",
                        "attempt": 1,
                        "review_round": 1,
                        "monitor": {"status": "active", "run_id": "run-t1-old"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (runs_dir / "run-t1-old.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-t1-old",
                        "task_id": "T1",
                        "task_guid": "guid-T1",
                        "attempt": 1,
                        "review_round": 1,
                        "reviewed_at": "2026-04-09T07:00:01+08:00",
                        "monitor": {"status": "active", "run_id": "run-t1-old"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (runs_dir / "run-t1-new.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-t1-new",
                        "task_id": "T1",
                        "task_guid": "guid-T1",
                        "attempt": 2,
                        "review_round": 2,
                        "reviewed_at": "2026-04-09T07:00:02+08:00",
                        "monitor": {"status": "active", "run_id": "run-t1-new"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.utime(runs_dir / "run-t1-old.json", (1, 1))
            os.utime(runs_dir / "run-t1-new.json", (2, 2))

            class _Api:
                def pm_file(self, name: str) -> Path:
                    return pm_dir / name

                def pm_dir_path(self) -> Path:
                    return pm_dir

                def load_json_file(self, path: Path):
                    try:
                        return json.loads(path.read_text(encoding="utf-8"))
                    except FileNotFoundError:
                        return None

                def default_config(self) -> dict:
                    return {"review": {}, "monitor": {}}

            handlers = build_command_handlers(_Api())
            args = type("Args", (), {"task_id": "T1", "task_guid": "", "run_id": ""})()

            with mock.patch("builtins.print") as mocked_print:
                code = handlers["monitor_status"](args)

            self.assertEqual(code, 0)
            payload = json.loads(mocked_print.call_args.args[0])
            self.assertEqual(payload["run_id"], "run-t1-new")
            self.assertEqual(payload["monitor"]["run_id"], "run-t1-new")

    def test_kickoff_run_monitor_force_runs_created_cron_job(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pm_dir = root / ".pm"
            monitor_dir = pm_dir / "monitors"
            prompts_dir = pm_dir / "prompts"
            monitor_dir.mkdir(parents=True, exist_ok=True)
            prompts_dir.mkdir(parents=True, exist_ok=True)
            state = {
                "run_id": "run-1",
                "status": "active",
                "cron_job_id": "job-1",
                "cron_session_key": "main",
                "kickoff_enabled": True,
                "kickoff_status": "pending",
                "monitor_path": str(monitor_dir / "run-1.json"),
                "prompt_path": str(prompts_dir / "run-1-monitor.txt"),
                "pm_config_path": str(root / "pm.json"),
                "repo_root": str(root),
                "run_record_path": str(pm_dir / "runs" / "run-1.json"),
                "watch_mode": "run-record",
                "backend": "codex-cli",
                "child_session_key": "",
            }
            (monitor_dir / "run-1.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

            with mock.patch("pm.pm_dir_path", return_value=pm_dir), mock.patch(
                "pm.cron_list", return_value={"jobs": [{"jobId": "job-1"}]}
            ), mock.patch(
                "pm.cron_run", return_value={"status": "ok", "jobId": "job-1", "runMode": "force"}
            ) as mocked_cron_run, mock.patch("pm.now_iso", return_value="2026-04-09T08:00:00+08:00"):
                result = pm.kickoff_run_monitor("run-1", reason="pm run-reviewed T1")

            self.assertEqual(result["status"], "sent")
            mocked_cron_run.assert_called_once_with("job-1", session_key="main", run_mode="force")
            saved = json.loads((monitor_dir / "run-1.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["kickoff_status"], "sent")
            self.assertEqual(saved["kickoff_reason"], "pm run-reviewed T1")
            self.assertEqual(saved["kickoff_result"]["jobId"], "job-1")

    def test_start_run_monitor_accepts_cron_id_from_result_details(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pm_dir = root / ".pm"
            runs_dir = pm_dir / "runs"
            monitor_dir = pm_dir / "monitors"
            runs_dir.mkdir(parents=True, exist_ok=True)
            monitor_dir.mkdir(parents=True, exist_ok=True)

            run_id = "run-1"
            run_record = {
                "run_id": run_id,
                "task_id": "T1",
                "task_guid": "guid-T1",
                "backend": "codex-cli",
            }
            (runs_dir / f"{run_id}.json").write_text(json.dumps(run_record, ensure_ascii=False, indent=2), encoding="utf-8")

            with mock.patch("pm.project_root_path", return_value=root), mock.patch("pm.pm_dir_path", return_value=pm_dir), mock.patch(
                "pm.pm_file", side_effect=lambda name: pm_dir / name
            ), mock.patch(
                "pm.monitor_config",
                return_value={"enabled": True, "interval_minutes": 5, "notify_on_start": True, "auto_stop_on_complete": True},
            ), mock.patch(
                "pm.default_config", return_value={"monitor": {}}
            ), mock.patch(
                "pm.cron_add",
                return_value={
                    "result": {
                        "details": {
                            "id": "job-from-id"
                        }
                    }
                },
            ), mock.patch(
                "pm.cron_list",
                return_value={
                    "result": {
                        "details": {
                            "jobs": [{"id": "job-from-id", "name": "pm-monitor-run-1"}]
                        }
                    }
                },
            ), mock.patch("pm.now_iso", return_value="2026-04-09T08:00:00+08:00"):
                monitor = pm.start_run_monitor(
                    repo_root=str(root),
                    task_id="T1",
                    task_guid="guid-T1",
                    run_id=run_id,
                    backend="codex-cli",
                    side_effects={},
                    session_key="main",
                )

            self.assertEqual(monitor["cron_job_id"], "job-from-id")
            self.assertEqual(monitor["status"], "active")
            self.assertEqual(monitor["status_reason"], "cron-verified")

            saved = json.loads((monitor_dir / f"{run_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["cron_job_id"], "job-from-id")
            self.assertEqual(saved["status"], "active")
            self.assertEqual(saved["status_reason"], "cron-verified")


if __name__ == "__main__":
    unittest.main()

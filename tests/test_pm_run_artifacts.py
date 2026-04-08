from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "pm" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pm


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


if __name__ == "__main__":
    unittest.main()

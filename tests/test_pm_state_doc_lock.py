from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "pm" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pm


class PmStateDocLockTest(unittest.TestCase):
    def test_append_state_doc_uses_repo_write_lock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_path = root / ".planning" / "STATE.md"
            entered: list[str] = []

            class _Lock:
                def __enter__(self):
                    entered.append("enter")
                    return None
                def __exit__(self, exc_type, exc, tb):
                    entered.append("exit")
                    return False

            with mock.patch("pm.doc_backend_name", return_value="repo"), \
                 mock.patch("pm.project_root_path", return_value=root), \
                 mock.patch("pm._repo_doc_paths", return_value={"state": state_path}), \
                 mock.patch("pm.repo_write_lock", side_effect=lambda name: _Lock()):
                result = pm.append_state_doc("hello")

            self.assertEqual(entered, ["enter", "exit"])
            self.assertEqual(result["status"], "repo_local_appended")
            self.assertIn("hello", state_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PM_SCRIPT_DIR = REPO_ROOT / "skills" / "pm" / "scripts"
if str(PM_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(PM_SCRIPT_DIR))


class PmOpenClawGuardTest(unittest.TestCase):
    def test_pm_scripts_do_not_shell_out_to_openclaw_agent_outside_runtime(self) -> None:
        scripts_dir = REPO_ROOT / "skills" / "pm" / "scripts"
        offenders: list[str] = []
        for path in scripts_dir.glob("*.py"):
            if path.name == "pm_runtime.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "openclaw" in text and '"agent"' in text and "subprocess.run" in text:
                offenders.append(path.name)
        self.assertEqual(
            offenders,
            [],
            f"Direct openclaw agent subprocess usage must stay centralized in pm_runtime.py: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()

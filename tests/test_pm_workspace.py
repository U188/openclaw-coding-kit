from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "pm" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pm_workspace import (
    REPO_WORKSPACE_TEMPLATES,
    build_workspace_profile,
    install_runtime_assets,
    scaffold_workspace,
    workspace_template_root,
)


class PmWorkspaceTest(unittest.TestCase):
    def test_repo_workspace_templates_are_self_contained(self) -> None:
        self.assertTrue(REPO_WORKSPACE_TEMPLATES.exists())
        self.assertEqual(workspace_template_root(), REPO_WORKSPACE_TEMPLATES)
        self.assertTrue((REPO_WORKSPACE_TEMPLATES / "AGENTS.md.tpl").exists())

    def test_scaffold_workspace_templates_encode_pm_first_gate(self) -> None:
        with TemporaryDirectory() as tmp:
            repo_root = Path(__file__).resolve().parents[1]
            workspace_root = Path(tmp) / "workspace"
            profile = build_workspace_profile(
                project_name="Demo Project",
                english_name="demo-project",
                agent_id="demo-project",
                channel="feishu",
                group_id="oc_demo",
                repo_root=repo_root,
                workspace_root=workspace_root,
                tasklist_name="Demo Project",
                doc_folder_name="Demo Project",
                task_prefix="T",
                default_worker="codex",
                reviewer_worker="reviewer",
                task_backend_type="local-task",
            )
            scaffold_workspace(output=workspace_root, profile=profile)
            agents_text = (workspace_root / "AGENTS.md").read_text(encoding="utf-8")
            workflow_text = (workspace_root / "WORKFLOW_AUTO.md").read_text(encoding="utf-8")
            self.assertIn("pm start-work", agents_text)
            self.assertIn("No explicit task binding, no coder dispatch.", agents_text)
            self.assertIn("Heavy-task Gate", workflow_text)
            self.assertIn("pm start-work", workflow_text)

    def test_install_runtime_assets_copy_mode_is_self_contained(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_home = root / "codex-home"
            workspace_root = root / "openclaw-workspace"
            payload = install_runtime_assets(
                codex_home=str(codex_home),
                workspace_root=str(workspace_root),
                mode="copy",
                force=False,
                dry_run=False,
            )
            self.assertEqual(payload.get("status"), "installed")
            self.assertTrue((codex_home / "skills" / "pm" / "SKILL.md").exists())
            self.assertTrue((codex_home / "skills" / "coder" / "SKILL.md").exists())
            self.assertTrue((codex_home / "skills" / "openclaw-lark-bridge" / "SKILL.md").exists())
            self.assertTrue((workspace_root / "skills" / "pm" / "SKILL.md").exists())
            self.assertTrue((workspace_root / "skills" / "coder" / "SKILL.md").exists())
            self.assertTrue((workspace_root / "plugins" / "acp-progress-bridge").exists())


if __name__ == "__main__":
    unittest.main()

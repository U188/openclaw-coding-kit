from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "pm" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pm_config
from pm_monitor import (
    build_monitor_job,
    build_monitor_prompt,
    build_monitor_state,
    build_user_visible_followup_job,
    should_start_monitor,
    validate_user_visible_followup_job,
)


class PmMonitorTest(unittest.TestCase):
    def tearDown(self) -> None:
        pm_config.ACTIVE_CONFIG.clear()

    def test_default_config_contains_monitor_block(self) -> None:
        cfg = pm_config.default_config()
        self.assertEqual(cfg["monitor"]["enabled"], True)
        self.assertEqual(cfg["monitor"]["interval_minutes"], 5)
        self.assertEqual(cfg["monitor"]["notify_on_start"], False)

    def test_monitor_config_merges_defaults_with_active_config(self) -> None:
        pm_config.ACTIVE_CONFIG.clear()
        pm_config.ACTIVE_CONFIG.update({"monitor": {"enabled": False, "interval_minutes": 9}})
        merged = pm_config.monitor_config()
        self.assertEqual(merged["enabled"], False)
        self.assertEqual(merged["interval_minutes"], 9)
        self.assertEqual(merged["notify_on_start"], False)
        self.assertEqual(merged["auto_stop_on_complete"], True)

    def test_should_start_monitor_for_supported_reviewed_backends(self) -> None:
        self.assertEqual(
            should_start_monitor(
                backend="acp",
                side_effects={"session_key": "child"},
                monitor_cfg={"enabled": True},
            ),
            True,
        )
        self.assertEqual(
            should_start_monitor(
                backend="codex-cli",
                side_effects={},
                monitor_cfg={"enabled": True},
            ),
            True,
        )
        self.assertEqual(
            should_start_monitor(
                backend="openclaw",
                side_effects={},
                monitor_cfg={"enabled": True},
            ),
            True,
        )
        self.assertEqual(
            should_start_monitor(
                backend="unknown-backend",
                side_effects={},
                monitor_cfg={"enabled": True},
            ),
            False,
        )

    def test_build_monitor_state_captures_run_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = build_monitor_state(
                repo_root=root,
                task_id="T1",
                task_guid="guid-1",
                run_id="run-1",
                backend="acp",
                side_effects={"session_key": "child-1"},
                monitor_cfg={"interval_minutes": 5},
                now_iso="2026-04-09T03:00:00Z",
            )
        self.assertEqual(state["run_id"], "run-1")
        self.assertEqual(state["child_session_key"], "child-1")
        self.assertEqual(state["watch_mode"], "child-session")
        self.assertEqual(state["status"], "pending-cron")
        self.assertEqual(state["continuation_contract"]["progress_updates_are_terminal"], False)
        self.assertEqual(state["reporting_contract"]["delivery_mode"], "none")
        self.assertEqual(state["reporting_contract"]["payload_kind"], "agentTurn")
        self.assertEqual(state["kickoff_enabled"], False)
        self.assertEqual(state["kickoff_status"], "disabled")
        self.assertTrue(str(state["monitor_path"]).endswith(".pm/monitors/run-1.json"))

    def test_build_monitor_prompt_points_to_run_and_monitor_records(self) -> None:
        state = {
            "run_id": "run-1",
            "repo_root": "/repo",
            "pm_config_path": "/repo/pm.json",
            "run_record_path": "/repo/.pm/runs/run-1.json",
            "monitor_path": "/repo/.pm/monitors/run-1.json",
            "cron_job_id": "job-1",
            "backend": "codex-cli",
            "watch_mode": "run-record",
            "child_session_key": "",
        }
        prompt = build_monitor_prompt(state)
        self.assertIn("Config: /repo/pm.json", prompt)
        self.assertIn("Run record: /repo/.pm/runs/run-1.json", prompt)
        self.assertIn("Monitor record: /repo/.pm/monitors/run-1.json", prompt)
        self.assertIn("Cron job id: job-1", prompt)
        self.assertIn("Backend: codex-cli", prompt)
        self.assertIn("Treat progress updates as non-terminal", prompt)
        self.assertIn("monitor-advance --run-id run-1", prompt)
        self.assertIn("first tick is force-run immediately", prompt)

    def test_build_user_visible_followup_job_defaults_to_silent_contract_without_explicit_target(self) -> None:
        job = build_user_visible_followup_job(
            name="pm-monitor-run-1",
            schedule={"kind": "every", "everyMs": 300000},
            message="hello",
            timeout_seconds=1200,
            session_target="isolated",
        )
        self.assertEqual(job["payload"]["kind"], "agentTurn")
        self.assertEqual(job["delivery"]["mode"], "none")
        self.assertEqual(job["sessionTarget"], "isolated")

    def test_build_user_visible_followup_job_uses_announce_when_explicit_channel_is_bound(self) -> None:
        job = build_user_visible_followup_job(
            name="pm-monitor-run-1",
            schedule={"kind": "every", "everyMs": 300000},
            message="hello",
            timeout_seconds=1200,
            session_target="isolated",
            channel="telegram",
            to="7387265533",
        )
        self.assertEqual(job["delivery"]["mode"], "announce")
        self.assertEqual(job["delivery"]["channel"], "telegram")
        self.assertEqual(job["delivery"]["to"], "7387265533")

    def test_validate_user_visible_followup_job_rejects_invalid_payload_kind(self) -> None:
        with self.assertRaises(ValueError):
            validate_user_visible_followup_job(
                {
                    "name": "bad-job",
                    "schedule": {"kind": "every", "everyMs": 300000},
                    "payload": {"kind": "systemEvent", "text": "noop"},
                    "sessionTarget": "main",
                    "delivery": {"mode": "none"},
                }
            )

    def test_validate_user_visible_followup_job_rejects_invalid_delivery_mode(self) -> None:
        with self.assertRaises(ValueError):
            validate_user_visible_followup_job(
                {
                    "name": "bad-job",
                    "schedule": {"kind": "every", "everyMs": 300000},
                    "payload": {"kind": "agentTurn", "message": "noop"},
                    "sessionTarget": "isolated",
                    "delivery": {"mode": "webhook"},
                }
            )

    def test_build_monitor_job_uses_silent_agent_turn_payload_by_default(self) -> None:
        state = {
            "run_id": "run-1",
            "cron_schedule": {"kind": "every", "everyMs": 300000},
            "repo_root": "/repo",
            "pm_config_path": "/repo/pm.json",
            "run_record_path": "/repo/.pm/runs/run-1.json",
            "monitor_path": "/repo/.pm/monitors/run-1.json",
            "cron_job_id": "job-1",
            "backend": "codex-cli",
            "watch_mode": "run-record",
            "child_session_key": "",
            "reporting_contract": {"session_target": "isolated"},
        }
        job = build_monitor_job(state, monitor_cfg={"stalled_after_minutes": 20})
        self.assertEqual(job["name"], "pm-monitor-run-1")
        self.assertEqual(job["schedule"]["kind"], "every")
        self.assertEqual(job["payload"]["kind"], "agentTurn")
        self.assertEqual(job["delivery"]["mode"], "none")
        self.assertEqual(job["sessionTarget"], "isolated")
        self.assertEqual(job["payload"]["timeoutSeconds"], 1200)
        self.assertIn("Run record: /repo/.pm/runs/run-1.json", job["payload"]["message"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
from typing import Any


MONITORED_BACKENDS = {"acp", "codex-cli", "openclaw"}


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _monitor_schedule(interval_minutes: int) -> dict[str, Any]:
    minutes = max(int(interval_minutes or 0), 1)
    return {"kind": "every", "everyMs": minutes * 60 * 1000}


def _watch_mode(backend: str, side_effects: dict[str, Any]) -> str:
    session_key = str((side_effects or {}).get("session_key") or "").strip()
    normalized_backend = str(backend or "").strip()
    if normalized_backend == "acp" and session_key:
        return "child-session"
    return "run-record"


def validate_user_visible_followup_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    delivery = job.get("delivery") if isinstance(job.get("delivery"), dict) else {}
    session_target = str(job.get("sessionTarget") or "").strip()
    if payload.get("kind") != "agentTurn":
        raise ValueError("user-visible follow-up jobs must use payload.kind=agentTurn")
    if delivery.get("mode") != "announce":
        raise ValueError("user-visible follow-up jobs must use delivery.mode=announce")
    if not session_target or session_target == "main":
        raise ValueError("user-visible follow-up jobs must bind to isolated/current/session:* targets")
    return job


def build_user_visible_followup_job(
    *,
    name: str,
    schedule: dict[str, Any],
    message: str,
    timeout_seconds: int,
    session_target: str = "isolated",
    channel: str = "",
    to: str = "",
    best_effort: bool = True,
) -> dict[str, Any]:
    normalized_name = str(name or "").strip()
    normalized_message = str(message or "").strip()
    normalized_session_target = str(session_target or "").strip() or "isolated"
    if not normalized_name:
        raise ValueError("follow-up job name is required")
    if not normalized_message:
        raise ValueError("follow-up job message is required")
    delivery: dict[str, Any] = {"mode": "announce", "bestEffort": bool(best_effort)}
    normalized_channel = str(channel or "").strip()
    normalized_to = str(to or "").strip()
    if normalized_channel:
        delivery["channel"] = normalized_channel
    if normalized_to:
        delivery["to"] = normalized_to
    job = {
        "name": normalized_name,
        "schedule": dict(schedule),
        "payload": {
            "kind": "agentTurn",
            "message": normalized_message,
            "timeoutSeconds": int(timeout_seconds),
        },
        "sessionTarget": normalized_session_target,
        "delivery": delivery,
    }
    return validate_user_visible_followup_job(job)


def should_start_monitor(*, backend: str, side_effects: dict[str, Any], monitor_cfg: dict[str, Any]) -> bool:
    if not bool(monitor_cfg.get("enabled")):
        return False
    normalized_backend = str(backend or "").strip()
    return normalized_backend in MONITORED_BACKENDS


def build_monitor_state(
    *,
    repo_root: str | Path,
    task_id: str,
    task_guid: str,
    run_id: str,
    backend: str,
    side_effects: dict[str, Any],
    monitor_cfg: dict[str, Any],
    now_iso: str,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    normalized_run_id = str(run_id or "").strip()
    monitors_dir = root / ".pm" / "monitors"
    run_record_path = root / ".pm" / "runs" / f"{normalized_run_id}.json"
    monitor_path = monitors_dir / f"{normalized_run_id}.json"
    prompt_path = monitors_dir / f"{normalized_run_id}.prompt.txt"
    watch_mode = _watch_mode(backend, side_effects)
    return {
        "status": "pending-cron",
        "task_id": str(task_id or "").strip(),
        "task_guid": str(task_guid or "").strip(),
        "run_id": normalized_run_id,
        "backend": str(backend or "").strip(),
        "repo_root": str(root),
        "pm_config_path": str(root / "pm.json"),
        "child_session_key": str((side_effects or {}).get("session_key") or "").strip(),
        "watch_mode": watch_mode,
        "continuation_contract": {
            "progress_updates_are_terminal": False,
            "terminal_states": ["completed", "blocked", "needs-decision"],
            "source_of_truth": [str(run_record_path), str(monitor_path)],
        },
        "reporting_contract": {
            "delivery_mode": "announce",
            "payload_kind": "agentTurn",
            "session_target": "isolated",
        },
        "cron_session_key": "main",
        "cron_job_id": "",
        "cron_schedule": _monitor_schedule(int(monitor_cfg.get("interval_minutes") or 5)),
        "prompt_path": str(prompt_path),
        "run_record_path": str(run_record_path),
        "monitor_path": str(monitor_path),
        "started_at": str(now_iso or "").strip(),
        "last_checked_at": "",
        "last_notified_state": "",
        "stopped_at": "",
        "stop_reason": "",
        "stop_result": None,
    }


def build_monitor_prompt(state: dict[str, Any]) -> str:
    prompt_lines = [
        "You are the PM monitor tick for one PM run.",
        f"Repo root: {state['repo_root']}",
        f"Config: {state['pm_config_path']}",
        f"Run record: {state['run_record_path']}",
        f"Monitor record: {state['monitor_path']}",
        f"Cron job id: {state['cron_job_id']}",
        f"Backend: {state.get('backend', '')}",
        f"Watch mode: {state.get('watch_mode', 'run-record')}",
    ]
    child_session_key = str(state.get("child_session_key") or "").strip()
    if child_session_key:
        prompt_lines.append(f"Child session key: {child_session_key}")
    prompt_lines.extend(
        [
            "Read the config, run record, and monitor record before deciding.",
            "This monitor exists to enforce continued task progression in code, not to preserve a one-off memory.",
            "Treat progress updates as non-terminal. Keep pushing until the run reaches a real terminal state.",
            "Terminal states are: completed, blocked, or needs-decision.",
            "If the run is finalized/completed, remove the cron job and mark the monitor closed.",
            "If review is failed, emit one rerun reminder.",
            "If review is passed but task is not completed, emit one complete reminder.",
            "If the run is active but stalled, emit one continue reminder.",
            "This is a user-visible follow-up contract: do not silently downgrade it to a non-announcing reminder.",
            "If nothing changed, reply with NO_REPLY.",
        ]
    )
    return "\n".join(prompt_lines)


def build_monitor_job(state: dict[str, Any], *, monitor_cfg: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = max(_int_or_default(monitor_cfg.get("stalled_after_minutes"), 20), 5) * 60
    return build_user_visible_followup_job(
        name=f"pm-monitor-{state['run_id']}",
        schedule=dict(state["cron_schedule"]),
        message=build_monitor_prompt(state),
        timeout_seconds=timeout_seconds,
        session_target=str((state.get("reporting_contract") or {}).get("session_target") or "isolated"),
        channel=str((state.get("reporting_contract") or {}).get("channel") or ""),
        to=str((state.get("reporting_contract") or {}).get("to") or ""),
        best_effort=True,
    )

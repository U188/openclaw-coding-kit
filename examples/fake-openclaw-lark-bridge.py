#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True)
    parser.add_argument("--action", default="")
    parser.add_argument("--args", default="{}")
    parser.add_argument("--session-key", default="")
    parser.add_argument("--message-channel", default="")
    parser.add_argument("--account-id", default="")
    parser.add_argument("--message-to", default="")
    parser.add_argument("--thread-id", default="")
    ns = parser.parse_args()

    payload = json.loads(ns.args or "{}")
    state_path = Path.cwd() / ".pm" / "fake-bridge-log.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {"calls": [], "next_job_id": 1, "jobs": []}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))

    calls = state.setdefault("calls", [])
    calls.append(
        {
            "tool": ns.tool,
            "action": ns.action,
            "args": payload,
            "session_key": ns.session_key,
            "message_channel": ns.message_channel,
            "account_id": ns.account_id,
            "message_to": ns.message_to,
            "thread_id": ns.thread_id,
        }
    )

    if ns.tool == "sessions_spawn":
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "ok", "result": {"details": {"childSessionKey": "child-1", "runId": "run-acp-1"}}}, ensure_ascii=False))
        return 0

    if ns.tool == "cron" and ns.action == "add":
        job_id = f"job-{state.get('next_job_id', 1)}"
        state["next_job_id"] = int(state.get("next_job_id", 1)) + 1
        if os.environ.get("FAKE_CRON_ADD_LIST_MISMATCH") != "1":
            jobs = state.setdefault("jobs", [])
            jobs.append({"jobId": job_id, "name": ((payload.get("job") or {}).get("name") or ""), "status": "active"})
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "ok", "job": {"jobId": job_id}}, ensure_ascii=False))
        return 0

    if ns.tool == "cron" and ns.action == "list":
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "ok", "jobs": state.get("jobs", [])}, ensure_ascii=False))
        return 0

    if ns.tool == "cron" and ns.action == "remove":
        jobs = state.setdefault("jobs", [])
        state["jobs"] = [job for job in jobs if str(job.get("jobId") or "") != str(payload.get("jobId") or "")]
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "ok", "removed": payload.get("jobId") or ""}, ensure_ascii=False))
        return 0

    if ns.tool == "cron" and ns.action == "run":
        job_id = str(payload.get("jobId") or "")
        jobs = state.setdefault("jobs", [])
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        if any(str(job.get("jobId") or "") == job_id for job in jobs):
            print(json.dumps({"status": "ok", "jobId": job_id, "runMode": payload.get("runMode") or "force"}, ensure_ascii=False))
            return 0
        print(json.dumps({"status": "error", "jobId": job_id, "message": "job not found"}, ensure_ascii=False))
        return 0

    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

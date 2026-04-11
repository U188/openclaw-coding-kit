from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable

CommandHandler = Callable[[argparse.Namespace], int]


def task_summary_text(item: dict[str, Any]) -> str:
    return str(item.get("normalized_summary") or item.get("summary") or "").strip()


def build_command_handlers(api: Any) -> dict[str, CommandHandler]:
    def emit(payload: dict[str, Any]) -> int:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    def review_cfg() -> dict[str, Any]:
        getter = getattr(api, "review_config", None)
        if callable(getter):
            value = getter()
            if isinstance(value, dict):
                return value
        defaults = api.default_config()
        review = defaults.get("review") if isinstance(defaults, dict) else None
        return review if isinstance(review, dict) else {}

    def review_required_default() -> bool:
        return bool(review_cfg().get("required"))

    def review_gate_enforced() -> bool:
        return bool(review_cfg().get("enforce_on_complete"))

    def review_comment_sync_enabled() -> bool:
        getter = getattr(api, "review_comment_sync_enabled", None)
        if callable(getter):
            return bool(getter())
        return bool(review_cfg().get("sync_comment"))

    def review_state_sync_enabled() -> bool:
        getter = getattr(api, "review_state_sync_enabled", None)
        if callable(getter):
            return bool(getter())
        return bool(review_cfg().get("sync_state"))

    def require_explicit_task_binding(*, command_name: str, task_id: str = "", task_guid: str = "") -> tuple[str, str]:
        normalized_task_id = str(task_id or "").strip()
        normalized_task_guid = str(task_guid or "").strip()
        if normalized_task_id or normalized_task_guid:
            return normalized_task_id, normalized_task_guid
        raise SystemExit(
            f"{command_name} requires explicit --task-id or --task-guid. "
            "Use `pm start-work --summary ...` (or `pm create` first) to bind tracked work before dispatch."
        )

    def monitor_cfg() -> dict[str, Any]:
        getter = getattr(api, "monitor_config", None)
        if callable(getter):
            value = getter()
            if isinstance(value, dict):
                return value
        defaults = api.default_config()
        monitor = defaults.get("monitor") if isinstance(defaults, dict) else None
        return monitor if isinstance(monitor, dict) else {}

    def clone_monitor_state(record: dict[str, Any] | None) -> dict[str, Any] | None:
        monitor = record.get("monitor") if isinstance(record, dict) else None
        return dict(monitor) if isinstance(monitor, dict) else None

    def persist_monitor_on_run_record(run_record: dict[str, Any], monitor: dict[str, Any]) -> None:
        normalized_run_id = str(run_record.get("run_id") or "").strip()
        if not normalized_run_id:
            return
        updated = dict(run_record)
        updated["monitor"] = dict(monitor)
        updated["monitor_status"] = str(monitor.get("status") or "").strip()
        api.write_pm_run_record(updated, run_id=normalized_run_id)

    def refresh_monitor_for_run_record(run_record: dict[str, Any] | None, *, persist: bool = True) -> dict[str, Any] | None:
        if not isinstance(run_record, dict):
            return None
        monitor = clone_monitor_state(run_record)
        if not isinstance(monitor, dict):
            return None
        refresh = getattr(api, "refresh_run_monitor", None)
        if not callable(refresh):
            return monitor
        refreshed = refresh(str(run_record.get("run_id") or "").strip(), write=persist)
        refreshed_monitor = refreshed.get("monitor") if isinstance(refreshed, dict) else None
        if isinstance(refreshed_monitor, dict) and persist:
            persist_monitor_on_run_record(run_record, refreshed_monitor)
        return dict(refreshed_monitor) if isinstance(refreshed_monitor, dict) else monitor

    def clone_run_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
        return dict(record) if isinstance(record, dict) else None

    def load_last_run_record(*, task_id: str = "", task_guid: str = "") -> dict[str, Any] | None:
        record = clone_run_record(api.load_json_file(api.pm_file("last-run.json")))
        if not isinstance(record, dict):
            return None
        normalized_task_id = str(task_id or "").strip()
        normalized_task_guid = str(task_guid or "").strip()
        if normalized_task_id:
            run_task_id = str(record.get("task_id") or "").strip()
            if run_task_id and run_task_id != normalized_task_id:
                return None
        if normalized_task_guid:
            run_task_guid = str(record.get("task_guid") or "").strip()
            if run_task_guid and run_task_guid != normalized_task_guid:
                return None
        return record

    def load_run_record(run_id: str) -> dict[str, Any] | None:
        loader = getattr(api, "load_run_record", None)
        if callable(loader):
            record = loader(run_id)
            return clone_run_record(record)
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            return None
        path = api.pm_dir_path() / "runs" / f"{normalized_run_id}.json"
        return clone_run_record(api.load_json_file(path))

    def find_latest_task_run_record(*, task_id: str = "", task_guid: str = "") -> tuple[dict[str, Any] | None, str]:
        normalized_task_id = str(task_id or "").strip()
        normalized_task_guid = str(task_guid or "").strip()
        runs_dir = api.pm_dir_path() / "runs"
        if not runs_dir.exists():
            return None, ""
        matches: list[tuple[tuple[float, str, str], dict[str, Any], str]] = []
        for path in runs_dir.glob("*.json"):
            record = clone_run_record(api.load_json_file(path))
            if not isinstance(record, dict):
                continue
            run_task_id = str(record.get("task_id") or "").strip()
            run_task_guid = str(record.get("task_guid") or "").strip()
            if normalized_task_id and run_task_id != normalized_task_id:
                continue
            if normalized_task_guid and run_task_guid != normalized_task_guid:
                continue
            try:
                mtime = float(path.stat().st_mtime)
            except OSError:
                mtime = 0.0
            time_hint = str(
                record.get("finalized_at")
                or record.get("reviewed_at")
                or record.get("completed_at")
                or record.get("review_bypassed_at")
                or ""
            ).strip()
            resolved_run_id = str(record.get("run_id") or path.stem).strip()
            matches.append(((mtime, time_hint, resolved_run_id), record, resolved_run_id))
        if not matches:
            return None, ""
        matches.sort(key=lambda item: item[0], reverse=True)
        _, record, resolved_run_id = matches[0]
        return record, resolved_run_id

    def resolve_run_record(*, task_id: str = "", task_guid: str = "", run_id: str = "") -> tuple[dict[str, Any], str]:
        normalized_run_id = str(run_id or "").strip()
        if normalized_run_id:
            record = load_run_record(normalized_run_id)
            if not isinstance(record, dict):
                raise SystemExit(f"run record not found: {normalized_run_id}")
            return record, normalized_run_id
        normalized_task_id = str(task_id or "").strip()
        normalized_task_guid = str(task_guid or "").strip()
        if normalized_task_id or normalized_task_guid:
            matched_record, resolved_run_id = find_latest_task_run_record(task_id=normalized_task_id, task_guid=normalized_task_guid)
            if isinstance(matched_record, dict):
                return matched_record, resolved_run_id
            last_run = load_last_run_record(task_id=normalized_task_id, task_guid=normalized_task_guid)
            if isinstance(last_run, dict):
                resolved_run_id = str(last_run.get("run_id") or "").strip()
                return last_run, resolved_run_id
            target = normalized_task_id or normalized_task_guid
            raise SystemExit(f"run record not found for task: {target}")
        last_run = load_last_run_record()
        if not isinstance(last_run, dict):
            raise SystemExit("last-run record not found")
        resolved_run_id = str(last_run.get("run_id") or "").strip()
        return last_run, resolved_run_id

    def next_generated_run_id(task_id: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", str(task_id or "").lower()).strip("-") or "run"
        return f"run-{slug}-{re.sub(r'[^0-9]', '', api.now_iso())}"

    def review_history(record: dict[str, Any]) -> list[dict[str, Any]]:
        history = record.get("review_history")
        if not isinstance(history, list):
            return []
        return [dict(item) for item in history if isinstance(item, dict)]

    def build_review_event(*, verdict: str, feedback: str, reviewer: str, reviewed_at: str) -> dict[str, Any]:
        normalized_verdict = str(verdict or "").strip().lower()
        return {
            "verdict": normalized_verdict,
            "review_status": "passed" if normalized_verdict == "pass" else "failed",
            "feedback": feedback,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
        }

    def sync_review_feedback(task_guid: str, task_id: str, event: dict[str, Any]) -> dict[str, Any]:
        task_id_text = str(task_id or "").strip()
        verdict = str(event.get("verdict") or "").strip()
        feedback = str(event.get("feedback") or "").strip()
        reviewer = str(event.get("reviewer") or "").strip()
        reviewed_at = str(event.get("reviewed_at") or "").strip()
        comment_result = None
        state_result = None
        if review_comment_sync_enabled():
            lines = [f"PM manual review verdict: {verdict}", "Boundary: this is a manual review gate, not an automatic review chain."]
            if task_id_text:
                lines.append(f"任务：{task_id_text}")
            if reviewer:
                lines.append(f"Reviewer: {reviewer}")
            if reviewed_at:
                lines.append(f"Reviewed at: {reviewed_at}")
            if feedback:
                lines.extend(["Feedback:", feedback])
            comment_result = api.create_task_comment(task_guid, "\n".join(lines))
        if review_state_sync_enabled():
            state_lines = ["", "", "## PM Review Update", "- boundary: manual review gate, not an automatic review chain", f"- verdict: {verdict}"]
            if task_id_text:
                state_lines.append(f"- 任务：{task_id_text}")
            if reviewer:
                state_lines.append(f"- reviewer：{reviewer}")
            if reviewed_at:
                state_lines.append(f"- reviewed_at：{reviewed_at}")
            if feedback:
                state_lines.extend(["- feedback：", feedback])
            state_result = api.append_state_doc("\n".join(state_lines))
        return {"comment_result": comment_result, "state_result": state_result}

    def decorate_run_payload(
        *,
        payload: dict[str, Any],
        review_required: bool,
        review_status: str,
        attempt: int,
        review_round: int,
        rerun_of_run_id: str = "",
        review_feedback: str = "",
        reviewer: str = "",
        reviewed_at: str = "",
        review_history_items: list[dict[str, Any]] | None = None,
        review_bypassed: bool = False,
        review_bypass_reason: str = "",
        review_bypassed_at: str = "",
    ) -> dict[str, Any]:
        normalized = dict(payload)
        normalized["review_required"] = bool(review_required)
        default_status = "pending" if review_required else ""
        normalized["review_status"] = str(review_status or default_status).strip()
        normalized["attempt"] = int(attempt or 1)
        normalized["review_round"] = int(review_round or 1)
        normalized["review_feedback"] = review_feedback
        normalized["reviewer"] = reviewer
        normalized["reviewed_at"] = reviewed_at
        normalized["review_history"] = [dict(item) for item in (review_history_items or []) if isinstance(item, dict)]
        normalized["rerun_of_run_id"] = rerun_of_run_id
        normalized["review_bypassed"] = bool(review_bypassed)
        normalized["review_bypass_reason"] = review_bypass_reason
        normalized["review_bypassed_at"] = review_bypassed_at
        return normalized

    def execute_run(
        args: argparse.Namespace,
        *,
        command_name: str = "pm run",
        review_required: bool = False,
        review_status: str = "",
        attempt: int | None = None,
        review_round: int | None = None,
        rerun_of_run_id: str = "",
        review_feedback: str = "",
        reviewer: str = "",
        reviewed_at: str = "",
        review_history_items: list[dict[str, Any]] | None = None,
        bundle_mutator: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        normalized_task_id, normalized_task_guid = require_explicit_task_binding(
            command_name=command_name,
            task_id=getattr(args, "task_id", ""),
            task_guid=getattr(args, "task_guid", ""),
        )
        args.task_id = normalized_task_id
        args.task_guid = normalized_task_guid
        bundle, path = api.build_coder_context(task_id=normalized_task_id, task_guid=normalized_task_guid)
        bundle = dict(bundle)
        if callable(bundle_mutator):
            bundle_mutator(bundle)
        coder = api.coder_config()
        backend = str(args.backend or coder.get("backend") or "acp").strip() or "acp"
        agent_id = str(args.agent or coder.get("agent_id") or "codex").strip() or "codex"
        timeout_seconds = int(args.timeout or coder.get("timeout") or 900)
        thinking = str(args.thinking or coder.get("thinking") or "high").strip()
        session_key = str(args.session_key or coder.get("session_key") or "main").strip() or "main"
        acp_cleanup = api.acp_cleanup_mode_from_coder(coder)
        message = api.build_run_message(bundle)
        task = api.resolve_effective_task(bundle)
        task_id = str(task.get("task_id") or "").strip()
        label = api.build_run_label(api.project_root_path(), agent_id, task_id)
        backend_warnings: list[str] = []
        explicit_backend = bool(str(args.backend or "").strip())
        auto_switched = False
        auto_switch_to_acp = bool(coder.get("auto_switch_to_acp"))
        if not explicit_backend and backend == "codex-cli" and auto_switch_to_acp:
            prefer_acp, prefer_reasons = should_prefer_acp_for_bundle(bundle, message, timeout_seconds)
            if prefer_acp:
                backend = "acp"
                auto_switched = True
                backend_warnings.append(
                    "Auto-switched backend from codex-cli to acp for this run: " + "；".join(prefer_reasons)
                )
        cwd_path = resolve_run_cwd(bundle)
        with api.task_run_lock(task_id):
            backend, result, side_effects, backend_runtime_warnings = run_coder_backend(
                backend=backend,
                agent_id=agent_id,
                message=message,
                cwd=str(cwd_path),
                timeout_seconds=timeout_seconds,
                thinking=thinking,
                session_key=session_key,
                label=label,
                bundle=bundle,
                acp_cleanup=acp_cleanup,
                explicit_backend=explicit_backend,
            )
        backend_warnings.extend(backend_runtime_warnings)
        run_id = ""
        if isinstance(side_effects, dict):
            run_id = str(side_effects.get("run_id") or "").strip()
        if not run_id:
            run_id = next_generated_run_id(task_id)
        cleanup_plan = api.build_run_cleanup_plan(
            backend=backend,
            session_key=session_key,
            acp_cleanup=acp_cleanup if backend == "acp" else "",
        )
        payload = {
            "coder_context_path": str(path),
            "backend": backend,
            "agent_id": agent_id,
            "task_id": task_id,
            "task_guid": str(task.get("guid") or "").strip(),
            "session_key": session_key,
            "acp_cleanup": acp_cleanup if backend == "acp" else "",
            "timeout": timeout_seconds,
            "thinking": thinking,
            "cwd": str(cwd_path),
            "message_preview": message[:1200],
            "result": result,
            "side_effects": side_effects,
            "run_id": run_id,
            "cleanup_plan": cleanup_plan,
            "warnings": backend_warnings,
            "runtime_banner": build_runtime_banner(
                backend=backend,
                agent_id=agent_id,
                task_id=task_id,
                auto_switched=auto_switched,
                side_effects=side_effects,
                cwd=str(cwd_path),
            ),
        }
        payload = decorate_run_payload(
            payload=payload,
            review_required=review_required,
            review_status=review_status,
            attempt=attempt or 1,
            review_round=review_round or 1,
            rerun_of_run_id=rerun_of_run_id,
            review_feedback=review_feedback,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            review_history_items=review_history_items or [],
        )
        monitor = {"status": "not-applicable"}
        if rerun_of_run_id:
            prior_record = load_run_record(rerun_of_run_id)
            prior_monitor = clone_monitor_state(prior_record)
            if isinstance(prior_monitor, dict) and str(prior_monitor.get("status") or "").strip() == "active":
                stop_result = api.stop_run_monitor(rerun_of_run_id, reason=f"pm rerun -> {run_id}")
                stopped_monitor = stop_result.get("monitor") if isinstance(stop_result, dict) else None
                if isinstance(stopped_monitor, dict):
                    persist_monitor_on_run_record(prior_record or {}, stopped_monitor)
        started_monitor = api.start_run_monitor(
            repo_root=str(api.project_root_path()),
            task_id=task_id,
            task_guid=str(task.get("guid") or "").strip(),
            run_id=run_id,
            backend=backend,
            side_effects=side_effects,
            session_key=session_key,
        )
        if isinstance(started_monitor, dict):
            monitor = started_monitor
            if rerun_of_run_id and str(monitor.get("status") or "").strip() != "not-applicable":
                monitor = dict(monitor)
                monitor["replaces_run_id"] = rerun_of_run_id
        payload["monitor"] = monitor
        payload["monitor_status"] = str(monitor.get("status") or "").strip() if isinstance(monitor, dict) else ""
        api.write_pm_run_record(payload, run_id=run_id)
        if isinstance(monitor, dict) and str(monitor.get("status") or "").strip() != "not-applicable":
            persist_monitor_on_run_record(payload, monitor)
            kickoff_monitor = getattr(api, "kickoff_run_monitor", None)
            if callable(kickoff_monitor):
                kickoff_result = kickoff_monitor(
                    run_id,
                    reason=f"pm {'rerun' if rerun_of_run_id else 'run-reviewed'} {task_id or run_id}",
                )
                refreshed_monitor = kickoff_result.get("monitor") if isinstance(kickoff_result, dict) else None
                if isinstance(refreshed_monitor, dict):
                    monitor = refreshed_monitor
                    if rerun_of_run_id and str(monitor.get("status") or "").strip() != "not-applicable":
                        monitor = dict(monitor)
                        monitor["replaces_run_id"] = rerun_of_run_id
                    payload["monitor"] = monitor
                    payload["monitor_status"] = str(monitor.get("status") or "").strip()
                    api.write_pm_run_record(payload, run_id=run_id)
                    persist_monitor_on_run_record(payload, monitor)
        return payload

    def should_prefer_acp_for_bundle(bundle: dict[str, Any], message: str, timeout_seconds: int) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        bootstrap = bundle.get("bootstrap") if isinstance(bundle.get("bootstrap"), dict) else {}
        current_task = bundle.get("current_task") if isinstance(bundle.get("current_task"), dict) else {}
        handoff = bundle.get("handoff_contract") if isinstance(bundle.get("handoff_contract"), dict) else {}
        required_reads = handoff.get("required_reads") if isinstance(handoff.get("required_reads"), list) else []
        task_description = str(current_task.get("description") or "").strip()
        project_mode = str(bootstrap.get("project_mode") or "").strip().lower()

        if project_mode == "brownfield":
            reasons.append("brownfield 项目默认优先 ACP")
        if len(required_reads) >= 3:
            reasons.append("required reads 较多")
        if len(task_description) >= 160:
            reasons.append("任务描述较长")
        if len(message) >= 1800:
            reasons.append("coder handoff 较长")
        if timeout_seconds >= 180:
            reasons.append("任务超时预算较长")
        return (len(reasons) > 0), reasons

    def extract_repo_hint_from_bundle(bundle: dict[str, Any]) -> str:
        project = bundle.get("project") if isinstance(bundle.get("project"), dict) else {}
        project_root = str(project.get("repo_root") or "").strip()
        if project_root:
            return project_root
        task = api.resolve_effective_task(bundle)
        description = str(task.get("description") or "").strip()
        match = re.search(r"^Repo[：:]\s*(.+?)\s*$", description, flags=re.MULTILINE)
        return str(match.group(1) if match else "").strip()

    def resolve_run_cwd(bundle: dict[str, Any]) -> Path:
        cwd_path = Path(api.project_root_path()).expanduser().resolve()
        if not cwd_path.exists():
            raise SystemExit(f"pm run blocked: configured repo_root does not exist: {cwd_path}")
        if not cwd_path.is_dir():
            raise SystemExit(f"pm run blocked: configured repo_root is not a directory: {cwd_path}")
        hinted_repo = extract_repo_hint_from_bundle(bundle)
        if hinted_repo:
            hinted_path = Path(hinted_repo).expanduser().resolve()
            if hinted_path != cwd_path:
                raise SystemExit(
                    "pm run blocked: repo_root / cwd mismatch. "
                    f"task context expects {hinted_path}, but PM resolved {cwd_path}. "
                    "Refresh PM context or fix pm.json repo_root before dispatch."
                )
        return cwd_path

    def resolve_runtime_binary(base_name: str, env_vars: tuple[str, ...]) -> str:
        resolver = getattr(api, "resolve_runtime_path", None)
        if not callable(resolver):
            return ""
        resolved = resolver(env_vars=env_vars, path_lookup_names=(base_name,))
        return str(resolved or "").strip()

    def openclaw_config_payload() -> tuple[dict[str, Any], str]:
        getter = getattr(api, "openclaw_config", None)
        if not callable(getter):
            return {}, ""
        try:
            payload = getter()
        except SystemExit:
            return {}, ""
        if not isinstance(payload, dict):
            return {}, ""
        path_getter = getattr(api, "find_openclaw_config_path", None)
        if callable(path_getter):
            try:
                path = path_getter()
            except SystemExit:
                path = None
            return payload, str(path or "").strip()
        return payload, ""

    def acpx_permission_mode(payload: dict[str, Any]) -> str:
        plugins = payload.get("plugins") if isinstance(payload.get("plugins"), dict) else {}
        entries = plugins.get("entries") if isinstance(plugins.get("entries"), dict) else {}
        acpx_entry = entries.get("acpx") if isinstance(entries.get("acpx"), dict) else {}
        config = acpx_entry.get("config") if isinstance(acpx_entry.get("config"), dict) else {}
        for key in ("permissionMode", "permission_mode"):
            value = str(config.get(key) or "").strip()
            if value:
                return value
        acp_cfg = payload.get("acp") if isinstance(payload.get("acp"), dict) else {}
        for key in ("permissionMode", "permission_mode"):
            value = str(acp_cfg.get(key) or "").strip()
            if value:
                return value
        return ""

    def acpx_write_allowed(permission_mode: str) -> bool:
        normalized = str(permission_mode or "").strip().lower()
        return normalized in {"approve-all", "bypass"}

    def build_acp_permission_error(*, config_path: str, permission_mode: str) -> str:
        where = config_path or "openclaw.json"
        current = permission_mode or "missing"
        return (
            "pm run blocked before ACP dispatch: managed coder runs need ACPX write/exec approval, "
            f"but {where} resolves to permissionMode={current}. "
            "Set plugins.entries.acpx.config.permissionMode to approve-all, "
            "or rerun with --backend codex-cli for local execution."
        )

    def build_runtime_banner(
        *,
        backend: str,
        agent_id: str,
        task_id: str,
        auto_switched: bool,
        side_effects: dict[str, Any] | None = None,
        cwd: str = "",
    ) -> str:
        task_suffix = f" · 任务 {task_id}" if task_id else ""
        switch_suffix = " · 本次为自动路由" if auto_switched else ""
        effective_side_effects = side_effects if isinstance(side_effects, dict) else {}
        run_suffix = ""
        child_session_key = str(effective_side_effects.get("session_key") or "").strip()
        run_id = str(effective_side_effects.get("run_id") or "").strip()
        if child_session_key:
            run_suffix += f" · child_session={child_session_key}"
        if run_id:
            run_suffix += f" · run_id={run_id}"
        cwd_suffix = f" · cwd={cwd}" if cwd else ""
        return (
            f"🔔 PM 执行器已确认 · backend={backend} · agent={agent_id}"
            f"{task_suffix}{switch_suffix}{run_suffix}{cwd_suffix}"
        )

    def run_coder_backend(
        *,
        backend: str,
        agent_id: str,
        message: str,
        cwd: str,
        timeout_seconds: int,
        thinking: str,
        session_key: str,
        label: str,
        bundle: dict[str, Any],
        acp_cleanup: str,
        explicit_backend: bool,
    ) -> tuple[str, dict[str, Any], dict[str, Any], list[str]]:
        warnings: list[str] = []
        normalized = str(backend or "acp").strip() or "acp"
        if normalized == "acp":
            openclaw_payload, openclaw_config_path = openclaw_config_payload()
            permission_mode = acpx_permission_mode(openclaw_payload)
            if openclaw_payload and not acpx_write_allowed(permission_mode):
                codex_cli_path = resolve_runtime_binary("codex", ("CODEX_BIN", "CODEX_PATH", "CODEX_CLI"))
                if explicit_backend or not codex_cli_path:
                    raise SystemExit(
                        build_acp_permission_error(
                            config_path=openclaw_config_path,
                            permission_mode=permission_mode,
                        )
                    )
                warnings.append(
                    "ACPX preflight rejected this managed write run "
                    f"(permissionMode={permission_mode or 'missing'}); fell back to backend=codex-cli."
                )
                normalized = "codex-cli"
            elif not openclaw_payload:
                warnings.append(
                    "ACP preflight could not inspect openclaw.json; runtime fallback will rely on actual dispatch result."
                )
        if normalized == "acp":
            try:
                result = api.spawn_acp_session(
                    agent_id=agent_id,
                    message=message,
                    cwd=cwd,
                    timeout_seconds=timeout_seconds,
                    thinking=thinking,
                    label=label,
                    session_key=session_key,
                    cleanup=acp_cleanup,
                    permission_mode="approve-all",
                )
                side_effects = api.persist_dispatch_side_effects(bundle, result, agent_id=agent_id, runtime="acp")
                return normalized, result, side_effects, warnings
            except SystemExit as exc:
                error_text = str(exc).strip()
                if "Tool not available: sessions_spawn" in error_text:
                    warnings.append(
                        "ACP dispatch unavailable on this OpenClaw build (`sessions_spawn` is not exposed via /tools/invoke); fell back to backend=codex-cli."
                    )
                    normalized = "codex-cli"
                elif "acpx exited with code 1" in error_text or "Internal error" in error_text:
                    warnings.append(
                        "ACP runtime failed while creating the Codex session; fell back to backend=codex-cli."
                    )
                    normalized = "codex-cli"
                elif "Permission denied by ACP runtime" in error_text or "permissionmode" in error_text.lower():
                    codex_cli_path = resolve_runtime_binary("codex", ("CODEX_BIN", "CODEX_PATH", "CODEX_CLI"))
                    if explicit_backend or not codex_cli_path:
                        raise SystemExit(
                            error_text
                            + "\nHint: ACPX blocked write/exec. Set plugins.entries.acpx.config.permissionMode=approve-all "
                            "or rerun with --backend codex-cli."
                        )
                    warnings.append(
                        "ACP runtime denied write/exec during session creation; fell back to backend=codex-cli."
                    )
                    normalized = "codex-cli"
                else:
                    raise
        if normalized == "codex-cli":
            result = api.run_codex_cli(
                agent_id=agent_id,
                message=message,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                thinking=thinking,
            )
            side_effects = api.persist_run_side_effects(bundle, result)
            return normalized, result, side_effects, warnings
        result = api.run_openclaw_agent(
            agent_id=agent_id,
            message=message,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            thinking=thinking,
        )
        side_effects = api.persist_run_side_effects(bundle, result)
        return normalized, result, side_effects, warnings

    def cmd_auth_link(args: argparse.Namespace) -> int:
        raw = [item.strip() for item in re.split(r"[\s,]+", args.scopes or "") if item.strip()]
        if not raw:
            raise SystemExit("provide --scopes, e.g. --scopes drive:drive offline_access")
        if args.mode == "user-oauth":
            payload = api.request_user_oauth_link(scopes=raw)
        else:
            payload = api.build_auth_link(scopes=raw, token_type=args.token_type)
        return emit(payload)

    def cmd_permission_bundle(args: argparse.Namespace) -> int:
        if args.list_presets:
            return emit({"presets": api.list_app_scope_presets()})
        payload = api.build_permission_bundle(
            preset_names=list(args.preset or []),
            scopes=list(args.scope or []),
            token_type=args.token_type,
        )
        return emit(payload)

    def cmd_auth(args: argparse.Namespace) -> int:
        payload = api.build_auth_bundle(
            include_group_open_reply=not bool(args.no_group_open_reply),
            include_attachment_oauth=not bool(args.no_attachment_oauth),
        )
        return emit(payload)

    def current_task_cfg() -> dict[str, Any]:
        value = api.ACTIVE_CONFIG.get("task")
        return value if isinstance(value, dict) else {}

    def current_doc_cfg() -> dict[str, Any]:
        value = api.ACTIVE_CONFIG.get("doc")
        return value if isinstance(value, dict) else {}

    def current_project_cfg() -> dict[str, Any]:
        value = api.ACTIVE_CONFIG.get("project")
        return value if isinstance(value, dict) else {}

    def current_task_backend() -> str:
        return str(current_task_cfg().get("backend") or api.default_config()["task"]["backend"]).strip() or "feishu"

    def current_doc_backend() -> str:
        return str(current_doc_cfg().get("backend") or api.default_config()["doc"]["backend"]).strip() or "feishu"

    def safe_project_label(project_name: str, english_name: str = "", agent_id: str = "") -> str:
        try:
            return str(api.project_display_name(project_name, english_name, agent_id)).strip()
        except Exception:
            return str(project_name or "").strip()

    def resolve_tasklist_name(root: Any, project_name: str, *, explicit_name: str = "", english_name: str = "", agent_id: str = "") -> str:
        explicit = str(explicit_name or "").strip()
        if explicit:
            return explicit
        task_cfg = current_task_cfg()
        current_name = str(task_cfg.get("tasklist_name") or api.ACTIVE_CONFIG.get("tasklist_name") or "").strip()
        current_guid = str(task_cfg.get("tasklist_guid") or "").strip()
        config_exists = bool(Path(str(api.ACTIVE_CONFIG.get("_config_path") or "")).exists())
        legacy_names = {
            str(api.default_config()["task"].get("tasklist_name") or "").strip(),
            str(api.default_config().get("tasklist_name") or "").strip(),
        }
        if current_guid and current_name:
            return current_name
        if current_name and config_exists:
            inspection = api.inspect_tasklist(current_name, configured_guid=current_guid)
            if str(inspection.get("status") or "") in {"configured_match", "unique_match"}:
                return current_name
        if current_name and current_name not in legacy_names:
            return current_name
        try:
            return str(api.default_tasklist_name(project_name, english_name, agent_id)).strip()
        except Exception:
            return safe_project_label(project_name, english_name, agent_id) or str(root.name)

    def resolve_doc_folder_name(root: Any, project_name: str, *, explicit_name: str = "", english_name: str = "", agent_id: str = "") -> str:
        explicit = str(explicit_name or "").strip()
        if explicit:
            return explicit
        doc_cfg = current_doc_cfg()
        current_name = str(doc_cfg.get("folder_name") or "").strip()
        current_token = str(doc_cfg.get("folder_token") or "").strip()
        config_exists = bool(Path(str(api.ACTIVE_CONFIG.get("_config_path") or "")).exists())
        legacy_names = {
            str(api.default_config()["doc"].get("folder_name") or "").strip(),
            str(root.name or "").strip(),
            f"{root.name} Docs",
        }
        if current_token and current_name:
            return current_name
        if current_name and config_exists:
            return current_name
        if current_name and current_name not in legacy_names:
            return current_name
        try:
            return str(api.default_doc_folder_name(project_name, english_name, agent_id)).strip()
        except Exception:
            return safe_project_label(project_name, english_name, agent_id) or str(root.name)

    def cmd_init(args: argparse.Namespace) -> int:
        root = api.project_root_path(args.repo_root)
        repo_config_path = root / "pm.json"
        args.config = str(repo_config_path)
        deprecated_command = str(getattr(args, "_deprecated_command", "") or "").strip()
        explicit_tasklist_name = str(args.tasklist_name or "").strip()
        explicit_doc_folder_name = str(args.doc_folder_name or "").strip()

        configured_project_name = str(current_project_cfg().get("name") or "").strip()
        if configured_project_name in {"", "未命名项目"}:
            configured_project_name = ""
        project_name = str(args.project_name or configured_project_name or root.name).strip() or root.name
        group_id = str(args.group_id or "").strip()
        english_name = ""
        agent_id = ""
        if group_id or str(args.english_name or "").strip() or str(args.agent_id or "").strip():
            english_name = api.english_project_name(project_name, args.english_name, args.agent_id)
            agent_id = api.project_slug(project_name, english_name, args.agent_id)

        resolved_tasklist_name = resolve_tasklist_name(
            root,
            project_name,
            explicit_name=str(args.tasklist_name or "").strip(),
            english_name=english_name,
            agent_id=agent_id,
        )
        resolved_doc_folder_name = resolve_doc_folder_name(
            root,
            project_name,
            explicit_name=str(args.doc_folder_name or "").strip(),
            english_name=english_name,
            agent_id=agent_id,
        )
        configured_tasklist_guid = str(args.tasklist_guid or current_task_cfg().get("tasklist_guid") or "").strip()
        configured_doc_folder_token = str(args.doc_folder_token or current_doc_cfg().get("folder_token") or "").strip()

        api.ACTIVE_CONFIG["repo_root"] = str(root)
        api.ACTIVE_CONFIG.setdefault("task", {})
        if isinstance(api.ACTIVE_CONFIG.get("task"), dict):
            api.ACTIVE_CONFIG["task"]["tasklist_name"] = resolved_tasklist_name
            if configured_tasklist_guid:
                api.ACTIVE_CONFIG["task"]["tasklist_guid"] = configured_tasklist_guid
        api.ACTIVE_CONFIG["tasklist_name"] = resolved_tasklist_name
        api.ACTIVE_CONFIG.setdefault("doc", {})
        if isinstance(api.ACTIVE_CONFIG.get("doc"), dict):
            api.ACTIVE_CONFIG["doc"]["folder_name"] = resolved_doc_folder_name
            if configured_doc_folder_token:
                api.ACTIVE_CONFIG["doc"]["folder_token"] = configured_doc_folder_token

        resolved_task_backend = str(args.task_backend or current_task_backend()).strip() or "feishu"
        resolved_doc_backend = str(args.doc_backend or current_doc_backend()).strip() or "feishu"
        auth_bundle = None if args.no_auth_bundle else api.build_auth_bundle(
            include_group_open_reply=True,
            include_attachment_oauth=True,
            explicit_openclaw_config=str(args.openclaw_config or "").strip(),
        )

        workspace_bootstrap = None
        if group_id:
            openclaw_config_path = api.resolve_openclaw_config_path(args.openclaw_config)
            workspace_root = api.resolve_workspace_root(
                openclaw_config_path=openclaw_config_path,
                agent_id=agent_id,
                explicit=args.workspace_root,
            )
            profile = api.build_workspace_profile(
                project_name=project_name,
                english_name=english_name,
                agent_id=agent_id,
                channel=str(args.channel or "feishu").strip() or "feishu",
                group_id=group_id,
                repo_root=root,
                workspace_root=workspace_root,
                tasklist_name=resolved_tasklist_name,
                doc_folder_name=resolved_doc_folder_name,
                task_prefix=str(args.task_prefix or "T").strip() or "T",
                default_worker=str(args.default_worker or "codex").strip() or "codex",
                reviewer_worker=str(args.reviewer_worker or "reviewer").strip() or "reviewer",
                task_backend_type="local-task" if resolved_task_backend == "local" else "feishu-task",
            )
            scaffold_result = api.scaffold_workspace(
                output=workspace_root,
                profile=profile,
                force=bool(args.force),
                dry_run=bool(args.dry_run),
            )
            register_result = api.register_workspace(
                config_path=openclaw_config_path,
                agent_id=agent_id,
                workspace_root=workspace_root,
                group_id=group_id,
                channel=str(args.channel or "feishu").strip() or "feishu",
                skills=list(args.skill or []),
                allow_agents=list(args.allow_agent or []),
                model_primary=str(args.model_primary or "").strip(),
                replace_binding=bool(args.replace_binding),
                dry_run=bool(args.dry_run),
            )
            workspace_bootstrap = {
                "project_name": project_name,
                "english_name": english_name,
                "agent_id": agent_id,
                "workspace_root": str(workspace_root),
                "group_id": group_id,
                "profile": profile,
                "scaffold": scaffold_result,
                "registration": register_result,
            }
        api.ACTIVE_CONFIG.setdefault("task", {})
        if isinstance(api.ACTIVE_CONFIG.get("task"), dict):
            api.ACTIVE_CONFIG["task"]["backend"] = resolved_task_backend
        api.ACTIVE_CONFIG.setdefault("doc", {})
        if isinstance(api.ACTIVE_CONFIG.get("doc"), dict):
            api.ACTIVE_CONFIG["doc"]["backend"] = resolved_doc_backend
        task_inspection = api.inspect_tasklist(resolved_tasklist_name, configured_guid=configured_tasklist_guid)
        config_path = api.resolve_config_path(args.config)
        config_payload = {key: value for key, value in api.ACTIVE_CONFIG.items() if not str(key).startswith("_")}
        config_payload["repo_root"] = str(root)
        config_payload.setdefault("repo", {})
        if isinstance(config_payload["repo"], dict):
            config_payload["repo"]["root"] = str(root)
        config_payload.setdefault("task", {})
        if isinstance(config_payload["task"], dict):
            config_payload["task"]["backend"] = resolved_task_backend
            config_payload["task"]["tasklist_name"] = resolved_tasklist_name
            config_payload["task"].setdefault("prefix", api.task_prefix())
            config_payload["task"].setdefault("kind", api.task_kind())
            if configured_tasklist_guid:
                config_payload["task"]["tasklist_guid"] = configured_tasklist_guid
            config_payload.setdefault("tasklist_name", config_payload["task"]["tasklist_name"])
            config_payload.setdefault("task_prefix", config_payload["task"]["prefix"])
            config_payload.setdefault("kind", config_payload["task"]["kind"])
        config_payload.setdefault("doc", api.default_config()["doc"])
        if isinstance(config_payload["doc"], dict):
            config_payload["doc"]["backend"] = resolved_doc_backend
            config_payload["doc"]["folder_name"] = resolved_doc_folder_name
            if configured_doc_folder_token:
                config_payload["doc"]["folder_token"] = configured_doc_folder_token
            config_payload["doc"].setdefault("project_title", "PROJECT")
            config_payload["doc"].setdefault("requirements_title", "REQUIREMENTS")
            config_payload["doc"].setdefault("roadmap_title", "ROADMAP")
            config_payload["doc"].setdefault("state_title", "STATE")
        config_payload.setdefault("coder", api.default_config()["coder"])
        if isinstance(config_payload["coder"], dict):
            config_payload["coder"].setdefault("backend", "codex-cli")
            config_payload["coder"].setdefault("agent_id", args.agent or "codex")
            config_payload["coder"].setdefault("timeout", int(args.timeout or 900))
            config_payload["coder"].setdefault("thinking", args.thinking or "high")
            config_payload["coder"].setdefault("session_key", args.session_key or "main")
        config_payload.setdefault("project", {})
        if isinstance(config_payload["project"], dict):
            current_name = str(config_payload["project"].get("name") or "").strip()
            if not current_name or current_name == "未命名项目":
                config_payload["project"]["name"] = project_name
            if group_id:
                config_payload["project"]["group_id"] = group_id
            if isinstance(workspace_bootstrap, dict) and str(workspace_bootstrap.get("agent_id") or "").strip():
                config_payload["project"]["agent"] = str(workspace_bootstrap.get("agent_id") or "").strip()

        if args.dry_run:
            api.ACTIVE_CONFIG.update(config_payload)
            docs_preview = api.ensure_project_docs(root, dry_run=True)
            warnings = []
            if deprecated_command:
                warnings.append(f"`{deprecated_command}` 已弃用，请改用 `init`。")
            if explicit_tasklist_name:
                warnings.append("`--tasklist-name` 仅保留为兼容覆盖参数；默认应只传 `--project-name`。")
            if explicit_doc_folder_name:
                warnings.append("`--doc-folder-name` 仅保留为兼容覆盖参数；默认应只传 `--project-name`。")
            return emit(
                {
                    "status": "dry_run",
                    "warnings": warnings,
                    "config_path": str(config_path),
                    "repo_root": str(root),
                    "project_name": project_name,
                    "naming_mode": "project_name_default" if not (explicit_tasklist_name or explicit_doc_folder_name) else "explicit_override",
                    "resolved_tasklist_name": resolved_tasklist_name,
                    "resolved_doc_folder_name": resolved_doc_folder_name,
                    "tasklist_inspection": task_inspection,
                    "docs_preview": docs_preview,
                    "workspace_bootstrap": workspace_bootstrap,
                    "auth_bundle": auth_bundle,
                    "config_preview": config_payload,
                }
            )

        tasklist = api.ensure_tasklist(resolved_tasklist_name)
        tasklist_guid = str(tasklist.get("guid") or "").strip()
        tasklist_url = str(tasklist.get("url") or "").strip()
        tasklist_owner = tasklist.get("owner") if isinstance(tasklist.get("owner"), dict) else {}
        tasklist_owner_id = str(tasklist_owner.get("id") or "").strip()
        if isinstance(config_payload.get("task"), dict):
            if tasklist_guid:
                config_payload["task"]["tasklist_guid"] = tasklist_guid
            if tasklist_url:
                config_payload["task"]["tasklist_url"] = tasklist_url
            if tasklist_owner_id:
                config_payload["task"].setdefault("default_assignee", tasklist_owner_id)
        api.ACTIVE_CONFIG.update(config_payload)
        docs = api.ensure_project_docs(root)
        if isinstance(config_payload.get("doc"), dict):
            config_payload["doc"].update(docs)
        api.ACTIVE_CONFIG.update(config_payload)
        api.ensure_pm_dir(str(root))
        if args.write_config or not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        bootstrap_task = None if args.skip_bootstrap_task else api.ensure_bootstrap_task(root)
        selected_task_id = str(((bootstrap_task or {}).get("task") or {}).get("task_id") or "").strip()
        selected_task_guid = str(((bootstrap_task or {}).get("task") or {}).get("guid") or "").strip()
        payload = api.refresh_context_cache(task_id=selected_task_id, task_guid=selected_task_guid)
        run_payload = None
        auto_run_reason = "disabled_by_flag" if args.skip_auto_run else "not_requested"
        if not args.skip_auto_run:
            if isinstance(bootstrap_task, dict) and bootstrap_task.get("created"):
                run_args = argparse.Namespace(
                    task_id=selected_task_id,
                    task_guid=selected_task_guid,
                    backend=str((config_payload.get("coder") or {}).get("backend") or "acp"),
                    agent=args.agent or str((config_payload.get("coder") or {}).get("agent_id") or "codex"),
                    timeout=int(args.timeout or (config_payload.get("coder") or {}).get("timeout") or 900),
                    thinking=args.thinking or str((config_payload.get("coder") or {}).get("thinking") or "high"),
                    session_key=args.session_key or str((config_payload.get("coder") or {}).get("session_key") or "main"),
                )
                auto_run_reason = "bootstrap_task_created"
                bundle, coder_context_path = api.build_coder_context(task_id=selected_task_id, task_guid=selected_task_guid)
                message = api.build_run_message(bundle)
                acp_cleanup = api.acp_cleanup_mode_from_coder(config_payload.get("coder") if isinstance(config_payload.get("coder"), dict) else {})
                resolved_backend, run_result, run_side_effects, run_warnings = run_coder_backend(
                    backend="acp",
                    agent_id=str(run_args.agent or "codex"),
                    message=message,
                    cwd=str(root),
                    timeout_seconds=int(run_args.timeout or 900),
                    thinking=str(run_args.thinking or "high"),
                    session_key=str(run_args.session_key or "main"),
                    label=api.build_run_label(root, str(run_args.agent or "codex"), selected_task_id),
                    bundle=bundle,
                    acp_cleanup=acp_cleanup,
                )
                run_payload = {
                    "coder_context_path": str(coder_context_path),
                    "backend": resolved_backend,
                    "agent_id": str(run_args.agent or "codex"),
                    "task_id": selected_task_id,
                    "task_guid": selected_task_guid,
                    "session_key": str(run_args.session_key or "main"),
                    "acp_cleanup": acp_cleanup if resolved_backend == "acp" else "",
                    "timeout": int(run_args.timeout or 900),
                    "thinking": str(run_args.thinking or "high"),
                    "message_preview": message[:1200],
                    "result": run_result,
                    "side_effects": run_side_effects,
                    "cleanup_plan": api.build_run_cleanup_plan(
                        backend=resolved_backend,
                        session_key=str(run_args.session_key or "main"),
                        acp_cleanup=acp_cleanup if resolved_backend == "acp" else "",
                    ),
                    "warnings": run_warnings,
                }
                api.write_pm_bundle("last-run.json", run_payload)
            else:
                auto_run_reason = "bootstrap_task_not_created"
        warnings = []
        if deprecated_command:
            warnings.append(f"`{deprecated_command}` 已弃用，请改用 `init`。")
        if explicit_tasklist_name:
            warnings.append("`--tasklist-name` 仅保留为兼容覆盖参数；默认应只传 `--project-name`。")
        if explicit_doc_folder_name:
            warnings.append("`--doc-folder-name` 仅保留为兼容覆盖参数；默认应只传 `--project-name`。")
        return emit(
            {
                "status": "initialized",
                "warnings": warnings,
                "config_path": str(config_path),
                "repo_root": str(root),
                "pm_dir": str(api.pm_dir_path(str(root))),
                "project_name": project_name,
                "naming_mode": "project_name_default" if not (explicit_tasklist_name or explicit_doc_folder_name) else "explicit_override",
                "tasklist": tasklist,
                "tasklist_inspection": task_inspection,
                "bootstrap_task": bootstrap_task,
                "auto_run_reason": auto_run_reason,
                "run": run_payload,
                "context_path": str(api.pm_file("current-context.json", str(root))),
                "project_scan_path": str(api.pm_file("project-scan.json", str(root))),
                "repo_scan": payload.get("repo_scan") or {},
                "doc_index": payload.get("doc_index") or {},
                "gsd": payload.get("gsd") or {},
                "workspace_bootstrap": workspace_bootstrap,
                "auth_bundle": auth_bundle,
            }
        )

    def cmd_sync_gsd_docs(args: argparse.Namespace) -> int:
        root = api.project_root_path(args.repo_root)
        api.ACTIVE_CONFIG["repo_root"] = str(root)
        payload = api.sync_gsd_docs(root=root, include=list(args.include or []))
        refreshed = api.refresh_context_cache()
        payload["context_path"] = str(api.pm_file("current-context.json", str(root)))
        payload["doc_index"] = refreshed.get("doc_index") or {}
        payload["gsd"] = refreshed.get("gsd") or {}
        return emit(payload)

    def cmd_sync_gsd_progress(args: argparse.Namespace) -> int:
        root = api.project_root_path(args.repo_root)
        api.ACTIVE_CONFIG["repo_root"] = str(root)
        task_guid = str(args.task_guid or "").strip()
        if not task_guid and str(args.task_id or "").strip():
            task = api.get_task_record(args.task_id, include_completed=args.include_completed)
            task_guid = str(task.get("guid") or "").strip()
        payload = api.sync_gsd_progress(
            root=root,
            phase=str(args.phase or "").strip(),
            task_guid=task_guid,
            append_to_state=not args.no_state_append,
        )
        payload["context_path"] = str(api.pm_file("current-context.json", str(root)))
        return emit(payload)

    def cmd_materialize_gsd_tasks(args: argparse.Namespace) -> int:
        root = api.project_root_path(args.repo_root)
        api.ACTIVE_CONFIG["repo_root"] = str(root)
        payload = api.materialize_gsd_tasks(root=root, phase=str(args.phase or "").strip())
        refreshed = api.refresh_context_cache()
        payload["context_path"] = str(api.pm_file("current-context.json", str(root)))
        payload["doc_index"] = refreshed.get("doc_index") or {}
        payload["gsd"] = refreshed.get("gsd") or {}
        return emit(payload)

    def cmd_route_gsd(args: argparse.Namespace) -> int:
        root = api.project_root_path(args.repo_root)
        api.ACTIVE_CONFIG["repo_root"] = str(root)
        payload = api.route_gsd_work(root, phase=str(args.phase or "").strip(), prefer_pm_tasks=True)
        refreshed = api.refresh_context_cache()
        return emit(
            {
                "repo_root": str(root),
                "route": payload,
                "context_path": str(api.pm_file("current-context.json", str(root))),
                "doc_index": refreshed.get("doc_index") or {},
                "gsd": refreshed.get("gsd") or {},
            }
        )

    def cmd_plan_phase(args: argparse.Namespace) -> int:
        root = api.project_root_path(args.repo_root)
        api.ACTIVE_CONFIG["repo_root"] = str(root)
        payload = api.plan_gsd_phase_workflow(
            root=root,
            phase=str(args.phase or "").strip(),
            task_id=str(args.task_id or "").strip(),
            task_guid=str(args.task_guid or "").strip(),
            include_completed=bool(args.include_completed),
            agent_id=str(args.agent or "").strip(),
            timeout_seconds=int(args.timeout or 0),
            thinking=str(args.thinking or "").strip(),
            research=bool(args.research),
            skip_research=bool(args.skip_research),
            gaps=bool(args.gaps),
            skip_verify=bool(args.skip_verify),
            prd=str(args.prd or "").strip(),
            reviews=bool(args.reviews),
            sync_docs=not args.no_doc_sync,
            sync_progress=not args.no_progress_sync,
            append_state=not args.no_state_append,
        )
        return emit(payload)

    def cmd_context(args: argparse.Namespace) -> int:
        use_cache = not args.refresh and not args.task_id and not args.task_guid
        if not use_cache:
            payload = api.refresh_context_cache(task_id=args.task_id, task_guid=args.task_guid)
        else:
            context_path = api.pm_file("current-context.json")
            cached = api.load_json_file(context_path)
            payload = cached if isinstance(cached, dict) else api.refresh_context_cache()
        return emit(payload)

    def cmd_next(args: argparse.Namespace) -> int:
        payload = api.refresh_context_cache() if args.refresh else api.build_context_payload()
        return emit({"next_task": payload.get("next_task"), "current_task": payload.get("current_task")})

    def cmd_plan(args: argparse.Namespace) -> int:
        payload, path = api.build_planning_bundle("plan", task_id=args.task_id, task_guid=args.task_guid, focus=args.focus)
        return emit({"bundle_path": str(path), "bundle": payload})

    def cmd_refine(args: argparse.Namespace) -> int:
        payload, path = api.build_planning_bundle("refine", task_id=args.task_id, task_guid=args.task_guid, focus=args.focus)
        return emit({"bundle_path": str(path), "bundle": payload})

    def cmd_coder_context(args: argparse.Namespace) -> int:
        payload, path = api.build_coder_context(task_id=args.task_id, task_guid=args.task_guid)
        return emit({"bundle_path": str(path), "bundle": payload})

    def cmd_run(args: argparse.Namespace) -> int:
        payload = execute_run(args, command_name="pm run")
        return emit(payload)

    def cmd_run_reviewed(args: argparse.Namespace) -> int:
        payload = execute_run(
            args,
            command_name="pm run-reviewed",
            review_required=review_required_default(),
            review_status="pending",
            attempt=1,
            review_round=1,
        )
        return emit(payload)

    def cmd_create(args: argparse.Namespace) -> int:
        if args.tasklist_name:
            api.ACTIVE_CONFIG.setdefault("task", {})
            if isinstance(api.ACTIVE_CONFIG.get("task"), dict):
                api.ACTIVE_CONFIG["task"]["tasklist_name"] = str(args.tasklist_name).strip()
            api.ACTIVE_CONFIG["tasklist_name"] = str(args.tasklist_name).strip()
        tasklist = api.ensure_tasklist(args.tasklist_name)
        summary = args.summary.strip()
        if not args.force_new:
            existing = api.find_existing_task_by_summary(summary, include_completed=True)
            if isinstance(existing, dict) and str(existing.get("guid") or "").strip():
                context = api.refresh_context_cache(task_guid=str(existing.get("guid") or ""))
                parsed = api.parse_task_summary(task_summary_text(existing)) or {}
                return emit(
                    {
                        "task_id": str((parsed or {}).get("task_id") or existing.get("normalized_task_id") or ""),
                        "task": existing,
                        "tasklist": tasklist,
                        "deduplicated": True,
                        "context_path": str(api.pm_file("current-context.json")),
                        "next_task": context.get("next_task"),
                    }
                )
        task_id = api.next_task_id()
        title = f"[{task_id}] {summary}"
        description = api.build_description(task_id, summary, args.request or "", args.repo_root, args.kind)
        create_args: dict[str, Any] = {
            "summary": title,
            "description": description,
            "tasklists": [{"tasklist_guid": str(tasklist.get("guid") or "").strip()}],
        }
        owner = tasklist.get("owner") if isinstance(tasklist.get("owner"), dict) else {}
        current_user_id = str(owner.get("id") or "").strip()
        if current_user_id:
            create_args["current_user_id"] = current_user_id
        task = api.create_task(
            summary=title,
            description=description,
            tasklists=[{"tasklist_guid": str(tasklist.get("guid") or "").strip()}],
            current_user_id=current_user_id,
        )
        context = api.refresh_context_cache(task_guid=str(task.get("guid") or ""))
        return emit(
            {
                "task_id": task_id,
                "task": task,
                "tasklist": tasklist,
                "deduplicated": False,
                "context_path": str(api.pm_file("current-context.json")),
                "next_task": context.get("next_task"),
            }
        )

    def cmd_start_work(args: argparse.Namespace) -> int:
        tasklist = None
        created = False
        deduplicated = False
        if args.task_guid:
            task = api.get_task_record_by_guid(args.task_guid)
        elif args.task_id:
            task = api.get_task_record(args.task_id, include_completed=getattr(args, "include_completed", False))
        else:
            summary = str(args.summary or "").strip()
            if not summary:
                raise SystemExit("pm start-work requires --summary when --task-id/--task-guid is not provided")
            tasklist_name = str(args.tasklist_name or "").strip()
            if tasklist_name:
                api.ACTIVE_CONFIG.setdefault("task", {})
                if isinstance(api.ACTIVE_CONFIG.get("task"), dict):
                    api.ACTIVE_CONFIG["task"]["tasklist_name"] = tasklist_name
                api.ACTIVE_CONFIG["tasklist_name"] = tasklist_name
            tasklist = api.ensure_tasklist(tasklist_name)
            task = None
            if not args.force_new:
                existing = api.find_existing_task_by_summary(summary, include_completed=True)
                if isinstance(existing, dict) and str(existing.get("guid") or "").strip():
                    task = existing
                    deduplicated = True
            if not isinstance(task, dict):
                task_id = api.next_task_id()
                title = f"[{task_id}] {summary}"
                description = api.build_description(task_id, summary, args.request or "", args.repo_root, args.kind)
                owner = tasklist.get("owner") if isinstance(tasklist, dict) and isinstance(tasklist.get("owner"), dict) else {}
                current_user_id = str(owner.get("id") or "").strip()
                task = api.create_task(
                    summary=title,
                    description=description,
                    tasklists=[{"tasklist_guid": str((tasklist or {}).get("guid") or "").strip()}],
                    current_user_id=current_user_id,
                )
                created = True
        if not isinstance(task, dict):
            raise SystemExit("pm start-work failed to resolve task binding")
        parsed = api.parse_task_summary(task_summary_text(task)) or {}
        task_id = str(task.get("task_id") or parsed.get("task_id") or args.task_id or "").strip()
        task_guid = str(task.get("guid") or args.task_guid or "").strip()
        if not task_guid:
            raise SystemExit("pm start-work resolved a task without guid")
        context = api.refresh_context_cache(task_guid=task_guid)
        kickoff_comment = None
        if not getattr(args, "no_comment", False):
            auto_started = api.ensure_task_started(task)
            mode = "run-reviewed" if bool(getattr(args, "reviewed", False)) else "run"
            backend_name = str(args.backend or api.coder_config().get("backend") or "").strip() or "default"
            agent_name = str(args.agent or api.coder_config().get("agent_id") or "").strip() or "default"
            kickoff_body = str(getattr(args, "comment", "") or "").strip() or "\n".join(
                [
                    "开工。",
                    "阶段：intake",
                    f"任务：{task_id or task_guid}",
                    f"执行方式：pm {mode}",
                    f"执行体：backend={backend_name} agent={agent_name}",
                    f"状态：{'ready' if bool(getattr(args, 'no_run', False)) else 'preflight'}",
                    "说明：真实 backend/session/run_id/monitor_status 以成功派发后的 run 记录与评论为准。",
                    "机制：显式 task 绑定已建立。",
                ]
            )
            kickoff_comment = api.create_task_comment(task_guid, kickoff_body)
            if isinstance(auto_started, dict):
                kickoff_comment = dict(kickoff_comment)
                kickoff_comment["start_result"] = auto_started
            task = api.get_task_record_by_guid(task_guid)
            context = api.refresh_context_cache(task_guid=task_guid)
        dispatch = None
        if not getattr(args, "no_run", False):
            run_args = argparse.Namespace(
                task_id=task_id,
                task_guid=task_guid,
                backend=str(args.backend or ""),
                agent=str(args.agent or ""),
                timeout=int(args.timeout or 0),
                thinking=str(args.thinking or ""),
                session_key=str(args.session_key or ""),
            )
            if bool(getattr(args, "reviewed", False)):
                dispatch = execute_run(
                    run_args,
                    command_name="pm start-work",
                    review_required=review_required_default(),
                    review_status="pending",
                    attempt=1,
                    review_round=1,
                )
            else:
                dispatch = execute_run(run_args, command_name="pm start-work")
            context = api.refresh_context_cache(task_guid=task_guid)
        return emit(
            {
                "task_id": task_id,
                "task_guid": task_guid,
                "task": task,
                "tasklist": tasklist,
                "created": created,
                "deduplicated": deduplicated,
                "kickoff_comment": kickoff_comment,
                "dispatch": dispatch,
                "context_path": str(api.pm_file("current-context.json")),
                "current_task": context.get("current_task"),
                "next_task": context.get("next_task"),
            }
        )

    def cmd_install_assets(args: argparse.Namespace) -> int:
        workspace_root = str(args.workspace_root or "").strip()
        if not workspace_root and str(args.agent_id or "").strip():
            openclaw_config_path = api.resolve_openclaw_config_path(str(args.openclaw_config or "").strip())
            resolved_workspace_root = api.resolve_workspace_root(
                openclaw_config_path=openclaw_config_path,
                agent_id=str(args.agent_id or "").strip(),
                explicit="",
            )
            workspace_root = str(resolved_workspace_root)
        payload = api.install_runtime_assets(
            codex_home=str(args.codex_home or "").strip(),
            workspace_root=workspace_root,
            mode=str(args.mode or "copy").strip() or "copy",
            force=bool(args.force),
            dry_run=bool(args.dry_run),
        )
        return emit(payload)

    def cmd_get(args: argparse.Namespace) -> int:
        task = api.get_task_record_by_guid(args.task_guid) if args.task_guid else api.get_task_record(args.task_id, include_completed=args.include_completed)
        guid = str(task.get("guid") or "").strip()
        comments = api.list_task_comments(guid, 20)
        parsed = api.parse_task_summary(task_summary_text(task))
        result = {
            "task_id": api.normalize_task_key(args.task_id) if args.task_id else str((parsed or {}).get("task_id") or ""),
            "summary": task.get("summary") or "",
            "normalized_summary": str((parsed or {}).get("normalized_summary") or task_summary_text(task)),
            "status": task.get("status") or "",
            "description": task.get("description") or "",
            "url": task.get("url") or "",
            "guid": task.get("guid") or "",
            "created_at": task.get("created_at") or "",
            "updated_at": task.get("updated_at") or "",
            "completed_at": task.get("completed_at") or "",
            "start": task.get("start") or {},
            "due": task.get("due") or {},
            "members": task.get("members") or [],
            "tasklists": task.get("tasklists") or [],
            "attachments": task.get("attachments") or [],
            "comments": comments,
        }
        return emit(result)

    def cmd_comment(args: argparse.Namespace) -> int:
        task = api.get_task_record_by_guid(args.task_guid) if args.task_guid else api.get_task_record(args.task_id, include_completed=args.include_completed)
        guid = str(task.get("guid") or "").strip()
        if not guid:
            raise SystemExit(f"task missing guid: {args.task_id or args.task_guid}")
        auto_started = api.ensure_task_started(task)
        content = args.content.strip()
        payload = api.create_task_comment(guid, content)
        context = api.refresh_context_cache(task_guid=guid)
        return emit(
            {
                "task_id": api.task_id_for_output(args.task_id),
                "task_guid": guid,
                "auto_started": bool(auto_started),
                "start_result": auto_started,
                "result": payload,
                "context_path": str(api.pm_file("current-context.json")),
                "next_task": context.get("next_task"),
            }
        )

    def cmd_review(args: argparse.Namespace) -> int:
        task = None
        if args.task_guid:
            task = api.get_task_record_by_guid(args.task_guid)
        elif args.task_id:
            task = api.get_task_record(args.task_id, include_completed=True)
        run_record, resolved_run_id = resolve_run_record(
            task_id=str((task or {}).get("task_id") or args.task_id or "").strip(),
            task_guid=str((task or {}).get("guid") or args.task_guid or "").strip(),
            run_id=args.run_id,
        )
        task_id = str((task or {}).get("task_id") or run_record.get("task_id") or args.task_id or "").strip()
        task_guid = str((task or {}).get("guid") or run_record.get("task_guid") or args.task_guid or "").strip()
        feedback = api.resolve_optional_text_input(args.feedback, args.feedback_file)
        verdict = str(args.verdict or "").strip().lower()
        if verdict == "fail" and not feedback:
            raise SystemExit("review fail requires --feedback or --feedback-file")
        reviewed_at = api.now_iso()
        reviewer = str(args.reviewer or "").strip()
        event = build_review_event(verdict=verdict, feedback=feedback, reviewer=reviewer, reviewed_at=reviewed_at)
        history = review_history(run_record)
        history.append(event)
        updated = decorate_run_payload(
            payload=run_record,
            review_required=bool(run_record.get("review_required")),
            review_status=str(event.get("review_status") or ""),
            attempt=int(run_record.get("attempt") or 1),
            review_round=int(run_record.get("review_round") or 1),
            rerun_of_run_id=str(run_record.get("rerun_of_run_id") or "").strip(),
            review_feedback=feedback,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            review_history_items=history,
            review_bypassed=bool(run_record.get("review_bypassed")),
            review_bypass_reason=str(run_record.get("review_bypass_reason") or "").strip(),
            review_bypassed_at=str(run_record.get("review_bypassed_at") or "").strip(),
        )
        updated["task_id"] = task_id or str(updated.get("task_id") or "").strip()
        updated["task_guid"] = task_guid or str(updated.get("task_guid") or "").strip()
        sync_result = sync_review_feedback(task_guid, task_id, event) if task_guid else {"comment_result": None, "state_result": None}
        api.write_pm_run_record(updated, run_id=resolved_run_id or str(updated.get("run_id") or "").strip())
        payload = dict(updated)
        payload["run_id"] = resolved_run_id or str(updated.get("run_id") or "").strip()
        payload["sync_result"] = sync_result
        return emit(payload)

    def cmd_rerun(args: argparse.Namespace) -> int:
        task = None
        if args.task_guid:
            task = api.get_task_record_by_guid(args.task_guid)
        elif args.task_id:
            task = api.get_task_record(args.task_id, include_completed=True)
        prior_run, resolved_run_id = resolve_run_record(
            task_id=str((task or {}).get("task_id") or args.task_id or "").strip(),
            task_guid=str((task or {}).get("guid") or args.task_guid or "").strip(),
            run_id=args.run_id,
        )
        prior_status = str(prior_run.get("review_status") or "").strip().lower()
        if prior_status != "failed":
            raise SystemExit(f"rerun requires the source run to be failed, got: {prior_status or 'unknown'}")
        feedback = str(prior_run.get("review_feedback") or "").strip()
        task_id = str((task or {}).get("task_id") or prior_run.get("task_id") or args.task_id or "").strip()
        task_guid = str((task or {}).get("guid") or prior_run.get("task_guid") or args.task_guid or "").strip()
        rerun_args = argparse.Namespace(
            task_id=task_id,
            task_guid=task_guid,
            backend=args.backend,
            agent=args.agent,
            timeout=args.timeout,
            thinking=args.thinking,
            session_key=args.session_key,
        )

        def apply_review_feedback(bundle: dict[str, Any]) -> None:
            bundle["review_context"] = {
                "prior_run_id": resolved_run_id or str(prior_run.get("run_id") or "").strip(),
                "review_feedback": feedback,
                "reviewer": str(prior_run.get("reviewer") or "").strip(),
                "reviewed_at": str(prior_run.get("reviewed_at") or "").strip(),
            }

        payload = execute_run(
            rerun_args,
            command_name="pm rerun",
            review_required=bool(prior_run.get("review_required", True)),
            review_status="pending",
            attempt=int(prior_run.get("attempt") or 1) + 1,
            review_round=int(prior_run.get("review_round") or 1) + 1,
            rerun_of_run_id=resolved_run_id or str(prior_run.get("run_id") or "").strip(),
            review_feedback=feedback,
            reviewer="",
            reviewed_at="",
            review_history_items=review_history(prior_run),
            bundle_mutator=apply_review_feedback,
        )
        return emit(payload)

    def cmd_complete(args: argparse.Namespace) -> int:
        task = api.get_task_record_by_guid(args.task_guid) if args.task_guid else api.get_task_record(args.task_id, include_completed=args.include_completed)
        guid = str(task.get("guid") or "").strip()
        if not guid:
            raise SystemExit(f"task missing guid: {args.task_id or args.task_guid}")
        task_id_text = str(task.get("task_id") or args.task_id or "").strip()
        last_run = None
        if task_id_text or guid:
            matched_run, _ = find_latest_task_run_record(task_id=task_id_text, task_guid=guid)
            if isinstance(matched_run, dict):
                last_run = matched_run
        if not isinstance(last_run, dict):
            last_run = load_last_run_record(task_id=task_id_text, task_guid=guid)
        latest_run_id = str((last_run or {}).get("run_id") or "").strip()
        latest_review_status = str((last_run or {}).get("review_status") or "").strip().lower()
        latest_review_feedback = str((last_run or {}).get("review_feedback") or "").strip()
        review_required = bool((last_run or {}).get("review_required"))
        if review_gate_enforced() and review_required and latest_review_status not in {"passed", "bypassed"}:
            if not args.force_review_bypass:
                suggestion = "pm review --verdict pass|fail" if latest_review_status == "pending" else "pm rerun"
                raise SystemExit(
                    "manual review gate blocked completion: "
                    + json.dumps(
                        {
                            "task_id": str(task.get("task_id") or args.task_id or "").strip(),
                            "run_id": latest_run_id,
                            "review_status": latest_review_status or "missing",
                            "review_feedback": latest_review_feedback,
                            "next_step": suggestion,
                        },
                        ensure_ascii=False,
                    )
                )
        refreshed_monitor = refresh_monitor_for_run_record(last_run, persist=True)
        if isinstance(refreshed_monitor, dict) and isinstance(last_run, dict):
            last_run = dict(last_run)
            last_run["monitor"] = dict(refreshed_monitor)
            last_run["monitor_status"] = str(refreshed_monitor.get("status") or "").strip()
        content = api.resolve_optional_text_input(args.content, args.content_file)
        upload_result = api.upload_task_attachments(task, args.task_id, args.file)
        if upload_result.get("status") == "authorization_required":
            upload_result["pending_action"] = "complete"
            upload_result["content"] = content
            upload_result["commit_url"] = args.commit_url.strip() or ("" if args.skip_head_commit_url else api.current_head_commit_url(args.repo_root))
            return emit(upload_result)
        auto_started = upload_result.get("start_result")
        if upload_result.get("status") == "skipped":
            auto_started = api.ensure_task_started(task)
        commit_url = args.commit_url.strip() or ("" if args.skip_head_commit_url else api.current_head_commit_url(args.repo_root))
        completion_comment = api.build_completion_comment(content, commit_url, int(upload_result.get("uploaded_count") or 0))
        comment_payload: dict[str, Any] | None = None
        if completion_comment:
            comment_payload = api.create_task_comment(guid, completion_comment)
        completed_at = api.now_iso()
        payload = api.patch_task(guid, {"completed_at": completed_at})
        review_bypass = None
        if args.force_review_bypass and isinstance(last_run, dict):
            bypassed_at = api.now_iso()
            last_run = decorate_run_payload(
                payload=last_run,
                review_required=bool(last_run.get("review_required")),
                review_status="bypassed",
                attempt=int(last_run.get("attempt") or 1),
                review_round=int(last_run.get("review_round") or 1),
                rerun_of_run_id=str(last_run.get("rerun_of_run_id") or "").strip(),
                review_feedback=str(last_run.get("review_feedback") or "").strip(),
                reviewer=str(last_run.get("reviewer") or "").strip(),
                reviewed_at=str(last_run.get("reviewed_at") or "").strip(),
                review_history_items=review_history(last_run),
                review_bypassed=True,
                review_bypass_reason="pm complete --force-review-bypass",
                review_bypassed_at=bypassed_at,
            )
            review_bypass = {
                "status": "bypassed",
                "bypassed_at": bypassed_at,
                "reason": "pm complete --force-review-bypass",
            }
        finalized_run, cleanup_result = api.finalize_last_run_for_completion(
            last_run,
            task_id=str(task.get("task_id") or args.task_id or "").strip(),
            task_guid=guid,
            completed_at=completed_at,
            finalized_at=api.now_iso(),
        )
        monitor_stop = None
        if (
            isinstance(finalized_run, dict)
            and bool(monitor_cfg().get("auto_stop_on_complete"))
            and isinstance(finalized_run.get("monitor"), dict)
            and str(finalized_run["monitor"].get("status") or "").strip() == "active"
        ):
            run_id = str(finalized_run.get("run_id") or "").strip()
            monitor_stop = api.stop_run_monitor(run_id, reason="pm complete")
            stopped_monitor = monitor_stop.get("monitor") if isinstance(monitor_stop, dict) else None
            if isinstance(stopped_monitor, dict):
                finalized_run = dict(finalized_run)
                finalized_run["monitor"] = dict(stopped_monitor)
                finalized_run["monitor_status"] = str(stopped_monitor.get("status") or "").strip()
        if isinstance(finalized_run, dict):
            api.write_pm_run_record(finalized_run, run_id=str(finalized_run.get("run_id") or "").strip())
        context = api.refresh_context_cache()
        return emit(
            {
                "task_id": api.task_id_for_output(args.task_id),
                "task_guid": guid,
                "auto_started": bool(auto_started),
                "start_result": auto_started,
                "completion_comment": completion_comment,
                "comment_result": comment_payload,
                "commit_url": commit_url,
                "upload_result": upload_result,
                "result": payload,
                "review_bypass": review_bypass,
                "cleanup_result": cleanup_result,
                "monitor_stop": monitor_stop,
                "monitor_status": str((finalized_run or {}).get("monitor_status") or "").strip(),
                "context_path": str(api.pm_file("current-context.json")),
                "next_task": context.get("next_task"),
            }
        )

    def cmd_monitor_status(args: argparse.Namespace) -> int:
        run_record, resolved_run_id = resolve_run_record(task_id=args.task_id, task_guid=args.task_guid, run_id=args.run_id)
        monitor = refresh_monitor_for_run_record(run_record, persist=True)
        if not isinstance(monitor, dict):
            return emit({"status": "not-found", "run_id": resolved_run_id, "monitor": None})
        return emit({"status": "ok", "run_id": resolved_run_id, "monitor": monitor, "monitor_status": str(monitor.get("status") or "").strip()})

    def cmd_monitor_stop(args: argparse.Namespace) -> int:
        run_record, resolved_run_id = resolve_run_record(task_id=args.task_id, task_guid=args.task_guid, run_id=args.run_id)
        result = api.stop_run_monitor(resolved_run_id, reason=str(args.reason or "").strip() or "pm monitor-stop")
        monitor = result.get("monitor") if isinstance(result, dict) else None
        if isinstance(monitor, dict):
            persist_monitor_on_run_record(run_record, monitor)
        payload = dict(result) if isinstance(result, dict) else {"status": "unknown"}
        payload["run_id"] = resolved_run_id
        return emit(payload)

    def cmd_update_description(args: argparse.Namespace) -> int:
        task = api.get_task_record_by_guid(args.task_guid) if args.task_guid else api.get_task_record(args.task_id, include_completed=args.include_completed)
        guid = str(task.get("guid") or "").strip()
        if not guid:
            raise SystemExit(f"task missing guid: {args.task_id or args.task_guid}")
        content = api.resolve_text_input(args.content, args.content_file)
        current = str(task.get("description") or "").strip()
        if args.mode == "replace":
            description = content
        else:
            separator = args.separator
            description = f"{current}{separator}{content}".strip() if current else content
        payload = api.patch_task(guid, {"description": description})
        context = api.refresh_context_cache(task_guid=guid)
        return emit(
            {
                "task_id": api.normalize_task_key(args.task_id) if args.task_id else "",
                "task_guid": guid,
                "mode": args.mode,
                "description": description,
                "result": payload,
                "context_path": str(api.pm_file("current-context.json")),
                "next_task": context.get("next_task"),
            }
        )

    def cmd_list(args: argparse.Namespace) -> int:
        rows = [item for item in api.task_pool(include_completed=args.include_completed) if api.extract_task_number(task_summary_text(item)) > 0]
        rows.sort(key=lambda item: api.extract_task_number(task_summary_text(item)), reverse=not args.asc)
        if args.limit:
            rows = rows[: args.limit]
        result = [
            {
                "task_id": str((api.parse_task_summary(task_summary_text(item)) or {}).get("task_id") or ""),
                "summary": item.get("summary") or "",
                "normalized_summary": str(item.get("normalized_summary") or item.get("summary") or ""),
                "status": item.get("status") or "",
                "guid": item.get("guid") or "",
                "url": item.get("url") or "",
                "created_at": item.get("created_at") or "",
                "updated_at": item.get("updated_at") or "",
            }
            for item in rows
        ]
        return emit({"tasks": result})

    def cmd_normalize_titles(args: argparse.Namespace) -> int:
        result = api.normalize_task_titles(include_completed=args.include_completed)
        api.refresh_context_cache()
        return emit(result)

    def cmd_search(args: argparse.Namespace) -> int:
        query = args.query.strip().lower()
        if not query:
            raise SystemExit("search query is required")
        matches: list[dict[str, Any]] = []
        for item in api.task_pool(include_completed=args.include_completed):
            summary = task_summary_text(item)
            parsed = api.parse_task_summary(summary)
            if not summary:
                continue
            if query in summary.lower():
                matches.append(
                    {
                        "task_id": str((parsed or {}).get("task_id") or ""),
                        "summary": item.get("summary") or "",
                        "normalized_summary": str((parsed or {}).get("normalized_summary") or summary),
                        "guid": item.get("guid") or "",
                        "completed_at": item.get("completed_at") or "0",
                    }
                )
                continue
            guid = str(item.get("guid") or "").strip()
            if not guid:
                continue
            task = api.get_task_record_by_guid(guid)
            description = str(task.get("description") or "")
            if query in description.lower():
                matches.append(
                    {
                        "task_id": str((parsed or {}).get("task_id") or ""),
                        "summary": item.get("summary") or "",
                        "normalized_summary": str((parsed or {}).get("normalized_summary") or summary),
                        "guid": guid,
                        "completed_at": item.get("completed_at") or "0",
                        "description_excerpt": description[:240],
                    }
                )
        matches.sort(key=lambda item: api.extract_task_number(str(item.get("normalized_summary") or item.get("summary") or "")), reverse=True)
        if args.limit:
            matches = matches[: args.limit]
        return emit({"tasks": matches})

    def cmd_attachments(args: argparse.Namespace) -> int:
        task = api.get_task_record_by_guid(args.task_guid) if args.task_guid else api.get_task_record(args.task_id, include_completed=args.include_completed)
        result = api.list_task_attachments(
            task,
            args.task_id,
            args.download_dir,
            task_id_for_output_fn=api.task_id_for_output,
            attachment_auth_result_fn=api.attachment_auth_result,
            feishu_credentials=api.feishu_credentials,
            request_json=api.request_json,
        )
        return emit(result)

    def cmd_upload_attachments(args: argparse.Namespace) -> int:
        task = api.get_task_record_by_guid(args.task_guid) if args.task_guid else api.get_task_record(args.task_id, include_completed=args.include_completed)
        result = api.upload_task_attachments(task, args.task_id, args.file)
        if str(result.get("status") or "") != "authorization_required":
            api.refresh_context_cache(task_guid=str(task.get("guid") or ""))
        return emit(result)

    return {
        "auth": cmd_auth,
        "auth_link": cmd_auth_link,
        "permission_bundle": cmd_permission_bundle,
        "init": cmd_init,
        "sync_gsd_docs": cmd_sync_gsd_docs,
        "sync_gsd_progress": cmd_sync_gsd_progress,
        "materialize_gsd_tasks": cmd_materialize_gsd_tasks,
        "route_gsd": cmd_route_gsd,
        "plan_phase": cmd_plan_phase,
        "context": cmd_context,
        "next": cmd_next,
        "plan": cmd_plan,
        "refine": cmd_refine,
        "coder_context": cmd_coder_context,
        "run": cmd_run,
        "run_reviewed": cmd_run_reviewed,
        "review": cmd_review,
        "rerun": cmd_rerun,
        "monitor_status": cmd_monitor_status,
        "monitor_stop": cmd_monitor_stop,
        "create": cmd_create,
        "start_work": cmd_start_work,
        "install_assets": cmd_install_assets,
        "get": cmd_get,
        "comment": cmd_comment,
        "complete": cmd_complete,
        "update_description": cmd_update_description,
        "list": cmd_list,
        "normalize_titles": cmd_normalize_titles,
        "search": cmd_search,
        "attachments": cmd_attachments,
        "upload_attachments": cmd_upload_attachments,
    }

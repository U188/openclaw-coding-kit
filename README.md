# OpenClaw Coding Kit

[![Repository](https://img.shields.io/badge/GitHub-openclaw--coding--kit-181717?logo=github)](https://github.com/GalaxyXieyu/openclaw-coding-kit)
![Python](https://img.shields.io/badge/python-%3E%3D3.9-3776AB?logo=python&logoColor=white)
![Node.js](https://img.shields.io/badge/node-%3E%3D22-5FA04E?logo=node.js&logoColor=white)
![OpenClaw](https://img.shields.io/badge/openclaw-2026.3.22-0F172A)
![Mode](https://img.shields.io/badge/mode-local--first%20%E2%86%92%20integrated-7C3AED)

> A production-minded collaboration kit for running `PM + coder + OpenClaw + ACPX + progress bridge` as one stable delivery loop.

`OpenClaw Coding Kit` is not a one-off demo scaffold.  
It packages a repeatable working model for complex delivery: requirement intake, task routing, coding execution, progress relay, and optional Feishu synchronization.

![OpenClaw Coding Kit Architecture](./diagrams/openclaw-coding-kit-architecture.svg)

## Why This Exists

Most AI coding setups break down for the same reasons:

- business discussion and implementation details collapse into one polluted session
- PM-side context and coder-side execution do not share the same truth
- progress from sub-sessions is hard to route back into the parent workflow
- installation instructions, runtime config, and actual operator flow drift apart over time

This repository addresses that by separating roles and making the execution path explicit:

- `PM` owns task intake, context refresh, document sync, and routing
- `coder` owns implementation and validation inside ACP sessions
- `acp-progress-bridge` owns progress/completion relay only
- `Feishu task/doc` is optional collaboration truth in integrated mode
- `local task + repo docs` provides a low-friction local-first mode

## What You Get

| Area | Included | Purpose |
|---|---|---|
| Task orchestration | `skills/pm` | task intake, context refresh, doc sync, GSD routing |
| Execution worker | `skills/coder` | canonical ACP coding worker |
| Feishu bridge reuse | `skills/openclaw-lark-bridge` | calls Feishu tools from a running OpenClaw gateway |
| Progress relay | `plugins/acp-progress-bridge` | sends child-session progress and completion back to the parent |
| Config references | `examples/*` | minimal and extended config snippets |
| Verification | `tests/*` | repo-local validation baseline |

## Best For

Use this repository when you want:

- a local-first validation path before touching real collaboration systems
- a clearer boundary between PM reasoning and coder execution
- a repeatable OpenClaw + Codex + ACP workflow instead of one long improvised session
- optional Feishu integration without making Feishu a hard prerequisite for smoke checks

This repository is not trying to replace OpenClaw itself.  
It is an operator kit layered on top of OpenClaw.

## Architecture At A Glance

```mermaid
flowchart LR
    U[User / PM Conversation] --> F[OpenClaw Front Agent]
    F --> PM[PM Skill]
    PM --> T[Shared Truth\nTask / Doc / Context]
    PM --> G[GSD Routing\nOptional Planning]
    PM --> C[Coder Dispatch]
    C --> A[ACP / Codex Worker]
    A --> B[acp-progress-bridge]
    B --> F
    T --> PM
    T --> A
    F -. optional .-> L[Feishu Channel]
    T -. backend .-> X[Local Task + Repo Docs\nor Feishu Task + Docs]
```

Editable diagram sources:

- [`diagrams/openclaw-coding-kit-architecture.svg`](./diagrams/openclaw-coding-kit-architecture.svg)
- [`diagrams/openclaw-coding-kit-architecture.drawio`](./diagrams/openclaw-coding-kit-architecture.drawio)

## Operating Modes

### Local-First

Start here if your goal is to verify the repository, not the whole collaboration stack.

Recommended config:

```json
{
  "task": { "backend": "local" },
  "doc": { "backend": "repo" },
  "coder": { "backend": "codex-cli", "agent_id": "codex" },
  "review": {
    "required": true,
    "enforce_on_complete": true,
    "sync_comment": true,
    "sync_state": true
  },
  "monitor": {
    "enabled": true,
    "mode": "cron",
    "interval_minutes": 5,
    "stalled_after_minutes": 20,
    "notify_on_review_pending": true,
    "notify_on_review_failed": true,
    "auto_stop_on_complete": true
  }
}
```

Good for:

- smoke checks
- PM/coder/GSD routing validation
- bootstrap verification
- installation debugging without Feishu
- Telegram/local-first delivery with Codex CLI as the default worker path

### Integrated

Use this when you want the real collaboration loop:

- Codex + OpenClaw runtime
- agent binding and ACP execution
- Feishu bot / group / task / doc integration
- progress bridge and authorization flows

Current operator recommendation on OpenClaw `2026.3.24`:

- keep `coder.backend = "codex-cli"` as the default config for local-first operation
- keep `backend=acp` available as an explicit path when you want native ACP child sessions
- only enable automatic ACP routing when you explicitly set `coder.auto_switch_to_acp = true`
- when `backend=acp`, default `coder.acp_cleanup = "delete"` so run-mode child sessions are auto-reclaimed after completion; set it to `"keep"` only when you deliberately want to preserve the child session for debugging
- task completion is finalized by `pm complete`; it now writes machine-readable cleanup metadata back into `.pm/last-run.json` instead of relying on operator memory
- the default operator loop is now `pm run-reviewed` -> `pm review --verdict pass|fail` -> `pm rerun` when failed -> `pm complete` only after pass
- reviewed PM runs now create a monitor record under `.pm/monitors/<run_id>.json` and attach the same `monitor` block to `.pm/last-run.json` and `.pm/runs/<run_id>.json`; this continuation guard exists so progress does not rely on operator memory
- if `sessions_spawn` is used through Gateway HTTP, expose it with `gateway.tools.allow = ["sessions_spawn", "sessions_send"]`
- monitor mode also needs bridge access to `cron.add` and `cron.remove`; PM schedules the continuation guard as an isolated `agentTurn` cron job that reads absolute `.pm` paths from the prompt and treats progress updates as non-terminal
- user-visible follow-up jobs are now an explicit code contract inside `pm_monitor.py`: they must use `payload.kind=agentTurn`, `delivery.mode=announce`, and a non-`main` session target, so this behavior does not rely on operator memory

## Review Loop

Recommended PM operator flow:

```bash
python3 skills/pm/scripts/pm.py run-reviewed --task-id T1 --backend acp --agent codex
python3 skills/pm/scripts/pm.py monitor-status --task-id T1
python3 skills/pm/scripts/pm.py review --task-id T1 --verdict fail --feedback "List the problems to fix" --reviewer qa
python3 skills/pm/scripts/pm.py rerun --task-id T1 --backend acp --agent codex
python3 skills/pm/scripts/pm.py review --task-id T1 --verdict pass --reviewer qa
python3 skills/pm/scripts/pm.py monitor-stop --run-id run-acp-1 --reason "manual intervention"
python3 skills/pm/scripts/pm.py complete --task-id T1 --content "done"
```

Behavior summary:

- `run-reviewed` behaves like `run` but marks the run record as review-required with `review_status=pending`
- `run-reviewed` now starts one continuation monitor for supported PM backends (`acp`, `codex-cli`, `openclaw`) and persists deterministic monitor state in `.pm/monitors/<run_id>.json`
- `review --verdict fail` records structured reviewer metadata plus feedback history and keeps completion blocked
- `rerun` creates a new run record, carries the latest failed feedback into the coder handoff, increments `attempt` and `review_round`, links `rerun_of_run_id`, and stops the previous active monitor before starting the new one
- `monitor-status` reads the explicit `--run-id` or resolves the requested task's latest run from `.pm/runs/*.json`, so operators can inspect cron metadata without opening JSON files manually
- `monitor-stop` is idempotent and persists the final stop result back into monitor and run records
- if the bridge cannot create the cron job, the run still succeeds and the monitor is persisted as `cron-error` instead of aborting the whole execution
- `complete` now rejects `pending` and `failed` latest runs for the requested task unless you explicitly pass `--force-review-bypass`, which is also recorded in the run record; when that task's latest run has an active monitor and monitor auto-stop is enabled, `complete` also closes the cron automatically

## Quick Start

If you want the fastest meaningful validation path, do not start with Feishu. These commands are intended to work from any clone or copied directory, not just the author's machine. The `init --write-config` step writes a repo-local `pm.json` so the following steps keep using `local/repo` backend. Run:

```bash
python3 -m py_compile skills/pm/scripts/*.py skills/coder/scripts/*.py
python3 skills/pm/scripts/pm.py init --project-name demo --task-backend local --doc-backend repo --write-config --skip-auto-run --skip-bootstrap-task --no-auth-bundle
python3 skills/pm/scripts/pm.py context --refresh
python3 skills/pm/scripts/pm.py route-gsd --repo-root .
```

Once that passes, move to:

1. runtime and dependency checks
2. OpenClaw / Codex asset deployment
3. config wiring
4. optional Feishu setup
5. real backend initialization

Full operator flow:

- [`INSTALL.md`](./INSTALL.md)

## Installation Strategy

Recommended order:

1. install runtime prerequisites first
2. verify repo-local smoke path
3. deploy `pm`, `coder`, `openclaw-lark-bridge`, and `acp-progress-bridge`
4. wire `openclaw.json` and `pm.json`
5. only then add Feishu bot, group, permissions, and OAuth when required
6. finish with real backend initialization and E2E verification

That order is intentional.  
It keeps runtime problems, config problems, and collaboration-system problems from collapsing into one debugging session.

## Repository Layout

```text
openclaw-coding-kit/
  README.md
  INSTALL.md
  examples/
    openclaw.json5.snippets.md
    pm.json.example
  plugins/
    acp-progress-bridge/
  skills/
    coder/
    openclaw-lark-bridge/
    pm/
  tests/
  diagrams/
    openclaw-coding-kit-architecture.drawio
    openclaw-coding-kit-architecture.svg
```

## Design Principles

- `PM` is the tracked-work front door
- `coder` executes; it does not own task/doc truth
- `GSD` owns roadmap/phase planning, not task/doc truth
- `bridge` is a relay, not a source of truth
- default to `local/repo` first, real Feishu second
- keep the OpenClaw baseline on `2026.3.22`, not `2026.4.5+`

## Feishu Integration Notes

If you enable `@larksuite/openclaw-lark`:

- bot creation, sensitive permission approval, version publishing, and `/auth` / `/feishu auth` still include manual user steps
- PM now supports common `env` / `file` / `exec` SecretRef resolution for `appSecret`
- do not keep both built-in `plugins.entries.feishu` and `openclaw-lark` enabled at the same time

That last point matters. Duplicate Feishu tool registration can cause tool conflicts and, in heavier environments, even destabilize CLI introspection.

Detailed install and permission guidance:

- [`INSTALL.md`](./INSTALL.md)

## Compatibility

| Item | Baseline |
|---|---|
| Python | `>= 3.9` |
| Node.js | `>= 22` |
| OpenClaw | `2026.3.22` |
| PM state dir | prefers `openclaw-coding-kit`, still falls back to legacy `openclaw-pm-coder-kit` |

## Included References

- [`INSTALL.md`](./INSTALL.md)
- [`examples/pm.json.example`](./examples/pm.json.example)
- [`examples/openclaw.json5.snippets.md`](./examples/openclaw.json5.snippets.md)

## Security

Do not commit:

- real `appId` / `appSecret`
- OAuth token or device auth state
- real group IDs, allowlists, user identifiers
- real tasklist GUIDs or document tokens
- local session stores or runtime caches

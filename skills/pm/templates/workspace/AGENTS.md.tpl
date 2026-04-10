# AGENTS

- project: `{{project_name}}`
- front agent: `{{front_agent_id}}`
- repo root: `{{repo_root}}`
- task backend: `{{task_backend_type}}`
- pm config: `{{pm_config_path}}`

## First Reads

1. `AGENTS.md`
2. `{{pm_config_path}}`
3. `memory.md`
4. `BOOTSTRAP.md`

## Working Rules

- Treat PM as the tracked-work front door.
- Treat `.planning/*` as roadmap and phase truth.
- Treat `.pm/*.json` as repo-local cache, not business truth.
- If a request implies multi-file work, refactor, dashboard / route / UI restructuring, worker / Codex use, build/test/browser verification, or any task likely to exceed a quick one-off edit, bind tracked work through `pm start-work` before implementation.
- No explicit task binding, no coder dispatch.
- Use `{{default_worker}}` as the default coder worker only after PM intake is established.
- Use `{{reviewer_worker}}` for review-only follow-up when needed.

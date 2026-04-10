# WORKFLOW_AUTO

## Default Loop

1. Read `{{pm_config_path}}` and repo-local PM context first.
2. If the incoming request hits the heavy-task gate, run `pm start-work` (or bind an existing task) before any coding or worker dispatch.
3. Confirm the active task and source of truth before coding.
4. Route roadmap and phase questions back through PM/GSD.
5. Let `{{default_worker}}` handle implementation work only after PM intake is established.
6. Let `{{reviewer_worker}}` handle review-only follow-up when needed.

## Heavy-task Gate

Treat the request as PM-first when it includes any of these:
- multi-file changes
- refactor / redesign / migration
- dashboard, route, sidebar, task-flow, or other cross-surface UI work
- worker / Codex / ACP execution
- build, test, browser verification, or staged acceptance
- work that is unlikely to finish as a quick one-off edit

## Collaboration Surface

- tasklist: `{{tasklist_name}}`
- doc folder: `{{doc_folder_name}}`
- channel: `{{channel}}`
- group id: `{{group_id}}`

# demo

## 项目定位
- 仓库：`/root/openclaw-coding-kit`
- 项目模式：brownfield
- 目标：把 `PM + coder + OpenClaw + ACPX + progress bridge` 收敛成一套可重复的交付回路，先走 local-first，再按需接 Feishu。

## 当前代码结构
### 1. PM 编排层
- 位置：`skills/pm/`
- 作用：任务入口、上下文刷新、文档同步、GSD 路由、执行派发。
- 关键脚本：
  - `skills/pm/scripts/pm.py`：CLI 入口，装配各模块能力
  - `skills/pm/scripts/pm_commands.py`：命令处理与 run/bootstrap 主流程
  - `skills/pm/scripts/pm_dispatch.py`：ACP 派发标签与 session 结果解析
  - `skills/pm/scripts/pm_runtime.py`：`acp` / `codex-cli` / `openclaw` 三种 coder backend 运行时
  - `skills/pm/scripts/pm_context.py`：上下文扫描与 `.pm/*.json` 生成

### 2. coder 执行层
- 位置：`skills/coder/`
- 作用：规范 coder worker 的执行约束与输出格式。
- 当前仓库里主要作为被 PM 调起的标准执行角色。

### 3. OpenClaw/Feishu bridge
- 位置：`skills/openclaw-lark-bridge/`
- 作用：通过运行中的 OpenClaw Gateway 调工具。
- 关键脚本：
  - `skills/openclaw-lark-bridge/scripts/invoke_openclaw_tool.py`
- 当前发现：仓库默认把 `sessions_spawn` 也当作 `/tools/invoke` 可调用工具，但在本机 OpenClaw `2026.3.24` 上并不成立。

### 4. progress relay 插件
- 位置：`plugins/acp-progress-bridge/`
- 作用：把子会话进度/完成事件回传给父会话。
- 当前状态：仓库已部署到 `workspace-main/plugins/acp-progress-bridge`，但本轮 local-first 验证不依赖它完成基本跑通。

### 5. 样例与测试
- `examples/pm.json.example`：PM 配置样例
- `examples/openclaw.json5.snippets.md`：OpenClaw 配置片段
- `tests/`：桥接、runtime、context、本地 CLI 等测试基线

## 当前环境结论
### 已打通
- `pm init`
- `pm context --refresh`
- `pm route-gsd`
- `gsd-tools`
- `acpx`
- `codex` 已配置到 `glen/gpt-5.4-xhigh` 并可最小实测通过

### 已定位问题
- 仓库默认 `backend=acp` 时，会在 `pm_commands.py -> spawn_acp_session() -> invoke_openclaw_tool.py` 这条链上通过 `/tools/invoke` 调 `sessions_spawn`
- 本机 OpenClaw `2026.3.24` 实测：
  - `tavily_search` 经 `/tools/invoke` 返回 `200`
  - `sessions_list` 经 `/tools/invoke` 返回 `200`
  - `sessions_spawn` 经 `/tools/invoke` 返回 `404 Tool not available`
- 结论：不是 OpenClaw 网关整体失效，而是仓库桥接默认假设与当前构建的工具暴露面不一致。

## 本轮修复
- 已在 `skills/pm/scripts/pm_commands.py` 增加统一的 `run_coder_backend()`
- 当用户仍配置 `backend=acp` 时：
  - 若 `sessions_spawn` 可用，继续走 ACP
  - 若抛出 `Tool not available: sessions_spawn`，自动回退到 `backend=openclaw`
- 这样做的目标不是掩盖问题，而是保证仓库在当前 OpenClaw `2026.3.24` 上仍能继续完成任务，不会卡死在坏桥上。

## 后续建议
1. 把 `invoke_openclaw_tool.py` 与 `pm_dispatch.py` 再收口，做成显式“ACP 可用性探测 + 回退”而不是只在命令层兜底。
2. 单独补一份兼容说明：说明 `2026.3.22+` 是基线，但 `sessions_spawn` 是否可经 `/tools/invoke` 调用，仍取决于实际构建/暴露策略。
3. 在 `tests/` 里增加一条回退测试，覆盖 `sessions_spawn unavailable -> fallback openclaw backend`。

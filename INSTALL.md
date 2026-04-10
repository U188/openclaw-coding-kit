# 安装说明

这份文档只保留一条可执行的安装主线。

如果你只是想先验证仓库可用，先做 Step 0 和 Step 1，不要一开始就接 Feishu。

相关资料：

- 仓库介绍与角色边界：`README.md`
- 最小 PM 配置示例：`examples/pm.json.example`
- OpenClaw 配置片段：`examples/openclaw.json5.snippets.md`

## 0. 完整安装 Checklist

如果你的目标不是“只验证 repo 能跑”，而是把整套链路真实装起来，先按这 6 步走：

1. 先装基础运行时：`python3 >= 3.9`、`node >= 22`、`openclaw = 2026.3.22`、`codex`、`gsd-tools`；如果要 ACP / bridge，再装 `acpx`
2. 如果目标包含 Feishu，这一步就并行准备：安装 `@larksuite/openclaw-lark`、写 `channels.feishu`、准备飞书 app / bot / 群 / 权限、让用户完成 `/auth`；如果要附件上传，再补 attachment OAuth
3. 部署仓库资产：`skills/pm`、`skills/coder`、`skills/openclaw-lark-bridge` 放到 Codex；`plugins/acp-progress-bridge` 放到 OpenClaw；只有 front agent 直接依赖 repo skills 时，才把 `pm/coder` 额外复制到 OpenClaw
4. 写配置：先把 `openclaw.json` 和 `pm.json` 配好
5. 再跑 smoke / runtime 验证：这时再跑 `py_compile`、`context --refresh`、`route-gsd`、`openclaw agents list --bindings`、`openclaw plugins list`
6. 最后才做真实 backend 的 `init` 和 E2E；如果是 Feishu backend，必须等 bot / 群 / 权限都 ready 之后再跑真实 `pm init`

### 0.1 这些步骤必须用户手动完成

下面这些动作，AI 最多只能帮你生成链接、命令和导入 JSON，不能替你点完：

1. 运行 `@larksuite/openclaw-lark` 的交互式安装流程，并在需要时扫码或确认 App 信息
2. 在飞书开放平台确认新增应用权限，并发布应用版本
3. 在飞书里私聊机器人或目标群里执行 `/auth` 或 `/feishu auth`
4. 在真实群里发消息验证“不用 @ 也回复”是否已经生效

也就是说，AI 可以把授权入口一次性整理好，但最后的人机确认动作还是要你自己点。

## 1. 安装策略

这份仓库实际上有两条入口：

1. 只验证仓库是否可跑
2. 真的要把整套链路装到 Codex / OpenClaw / Feishu

如果你只是做 repo 验证，推荐按下面顺序推进：

1. 先检查运行时和版本。
2. 先跑 repo-local smoke。
3. 再按需接入 Codex / OpenClaw。
4. 最后按需接 Feishu、OAuth 和 progress bridge。

如果你要做完整安装，推荐顺序改成：

1. 先检查并补齐运行时。
2. 如果目标包含 Feishu，让用户并行准备 app / bot / 群 / 权限，同时安装 `openclaw-lark`。
3. 先把仓库资产部署到 Codex / OpenClaw，并写好 `openclaw.json` / `pm.json`。
4. 再跑 smoke 和 runtime 验证。
5. 最后才做真实 Feishu backend 的 `init`、任务流和 E2E。

关键原则：

- 默认先走 `local/repo` backend，再接真实 Feishu。
- 先补依赖，再改配置。
- `front agent` 和 ACP worker 不是一回事，不要把 `codex` 直接当成 front agent。
- `cc` 不是必需前置，但要记录是否已安装。
- `openclaw` 默认基线固定为 `2026.3.22`，不要默认升级到 `2026.4.5+`。
- 如果目标包含 Feishu，用户侧创建 app / bot / 群 / 权限申请要和机器侧安装并行进行。

### 1.1 仓库可复制约束

这套仓库按“复制出去还能直接用”来维护，安装文档和配置示例也按这个标准写：

- 版本库里的文档链接必须是仓库内相对路径，不能写作者机器上的绝对路径
- 如果你在仓库根目录放 `pm.json`，`repo_root` 建议写成 `"."`，这样复制到新目录后不用先改路径
- 允许外置的只有敏感信息和真实环境参数，例如 token、secret、真实群组 id、真实 workspace 路径
- 真正的验收不是“原目录能跑”，而是“复制到新目录后，按 Step 1 还能跑通”

推荐把安装任务拆成三档：

| 档位 | 目标 | 是否需要 Feishu |
|------|------|----------------|
| 本地验证 | 证明 `pm` / `coder` / GSD 路由可启动 | 否 |
| OpenClaw 接入 | 证明 skill / plugin / agent 配置生效 | 否 |
| 完整集成 | 证明 task/doc/OAuth/bridge 能跑通 | 是 |

## 2. Step 0：环境检查

### 2.1 必查命令

最少检查：

- `python3`
- `node`
- `openclaw`
- `codex`
- `cc`
- `gsd-tools`

macOS / Linux:

```bash
which python3
which node
which openclaw
which codex
which cc
which gsd-tools
python3 --version
node -v
openclaw -v
```

Windows PowerShell:

```powershell
Get-Command python3
Get-Command node
Get-Command openclaw
Get-Command codex
Get-Command cc
Get-Command gsd-tools
python3 --version
node -v
openclaw -v
```

版本基线：

- Python `>= 3.9`
- Node.js `>= 22`
- OpenClaw `= 2026.3.22`

注意：

- 不能只看“机器上有更高版本 Python”；真正执行 `pm.py` 的 `python3` 必须满足 `>= 3.9`
- 如果机器上同时有 3.8 和 3.12，建议把登录环境里的默认 `python3` 前置到 3.12
- 可用 Python 解释器示例：`~/.local/bin/python3 -> /usr/local/bin/python3.12`
- 如果 `cc` 不存在，不阻塞本仓库安装，但交付里要明确写出“仅验证了 Codex 路径”

### 2.2 缺失时优先补什么

#### GSD

如果要让 `route-gsd`、`plan-phase`、`materialize-gsd-tasks` 正常工作，先安装 GSD：

```bash
npx get-shit-done-cc@latest --codex --global
node ~/.codex/get-shit-done/bin/gsd-tools.cjs --help
```

如果不是默认安装路径，显式设置：

```bash
export GSD_TOOLS_PATH=/abs/path/to/gsd-tools.cjs
```

#### ACPX

如果你准备启用：

- `acp.backend = "acpx"`
- ACP 子会话派发
- `acp-progress-bridge`

就先安装 `acpx` CLI：

```bash
npm install -g acpx@latest
acpx --help
```

如果 coder 要走 Codex，还要补齐 ACPX 依赖：

```bash
npm install -g @zed-industries/codex-acp@0.11.1
npm install -g @zed-industries/codex-acp-linux-x64@0.9.2
```

Gateway 如果要经 HTTP `/tools/invoke` 调 `sessions_spawn`，还要放开默认 deny：

```json5
{
  "gateway": {
    "tools": {
      "allow": ["sessions_spawn", "sessions_send"]
    }
  }
}
```

最小验收命令：

```bash
codex login status
acpx codex sessions new
python3 skills/pm/scripts/pm.py run-reviewed --task-id T1 --backend codex-cli --agent codex --timeout 120
python3 skills/pm/scripts/pm.py review --task-id T1 --verdict pass --reviewer qa
python3 skills/pm/scripts/pm.py complete --task-id T1 --content "validated"
python3 skills/pm/scripts/pm.py run --backend acp --agent codex --timeout 120
```

补充说明：

- `codex-cli` 路径在仓库里设置了 **300 秒最小有效超时**，避免短任务参数把真实 Codex 执行窗口截断。
- 所以即使传 `--timeout 120`，`codex-cli` 这条路径也会至少给 300 秒执行时间。

注意：

- `acpx` CLI 装好了，不代表旧的 `openclaw.json` 插件配置一定合法
- 如果 `openclaw config validate` 仍报 `plugin not found`，优先修配置，而不是重复安装 CLI
- 在 OpenClaw `2026.3.24` 上，推荐保留 `coder.backend = "codex-cli"` 作为默认配置；如需自动把 brownfield、required reads 多、task/doc 协作重的执行切到 `acp`，请显式设置 `coder.auto_switch_to_acp = true`
- 如果显式使用 `backend=acp`，默认 `coder.acp_cleanup = "delete"`，run-mode 子会话在任务完成后按机制自动回收；只有需要保留现场排障时才改成 `"keep"`
- 默认收口链路改为 `pm run-reviewed` -> `pm review --verdict pass|fail` -> 失败时 `pm rerun` -> `pm complete`
- `pm complete` 会拒绝该任务最近一次 run 仍为 `pending` / `failed` 的情况；特殊情况必须显式传 `--force-review-bypass`，并且 bypass 会写入对应 run record 与 `.pm/last-run.json`
- monitor loop 现在作为**继续推进机制**挂在 reviewed PM run 上；它依赖 bridge 侧暴露 `cron.add`、`cron.run` 和 `cron.remove`，并通过 isolated `agentTurn` cron job 读取绝对 `.pm` 路径做巡检
- 这条 continuation guard 不再只盯 ACP；当前支持 `acp`、`codex-cli`、`openclaw` 三类 PM backend
- user-visible 的 follow-up / reporter job 现在有显式代码约束：必须走 `agentTurn + announce`，且不能绑到 `sessionTarget=main`；这样不会退化成只提醒 AI、不通知操作者的静默 cron
- `monitor.notify_on_start = true` 时，reviewed run 在写完 run record 后会立刻 `cron.run --force` 一次 monitor job，避免操作者傻等下一个轮询窗口
- monitor 状态固定写入 `.pm/monitors/<run_id>.json`，并镜像到 `.pm/last-run.json` / `.pm/runs/<run_id>.json`

Monitor operator flow:

```bash
python3 skills/pm/scripts/pm.py run-reviewed --task-id T1 --backend acp --agent codex
python3 skills/pm/scripts/pm.py monitor-status --task-id T1
python3 skills/pm/scripts/pm.py review --task-id T1 --verdict fail --feedback "Add evidence" --reviewer qa
python3 skills/pm/scripts/pm.py rerun --task-id T1 --backend acp --agent codex
python3 skills/pm/scripts/pm.py review --task-id T1 --verdict pass --reviewer qa
python3 skills/pm/scripts/pm.py complete --task-id T1 --content "done"
```

预期行为：

- `run-reviewed` 成功后生成 monitor JSON，并向 bridge 请求一条 cron；它的目的就是把“继续推进直到完成/阻塞/需拍板”固化成代码机制
- `rerun` 会先关闭上一轮 monitor，再给新 run 建立新 monitor
- `review`、`rerun`、`monitor-status`、`complete` 在没显式传 `--run-id` 时，会按你指定的 `--task-id` / `--task-guid` 去 `.pm/runs/*.json` 里解析该任务自己的最近一轮 run，而不是盲目吃全局 `last-run`
- `complete` 会返回 `monitor_stop.status == "stopped"`，同时把最终 monitor 状态写回 `.pm/last-run.json`
- 如果 bridge 暂时不可用，run 不会因为 monitor 建立失败而整体中断；对应 monitor 会落成 `cron-error`，方便后续补桥接后继续查

如果当前没有 Feishu/真实 bridge，可以先用本地 fake bridge 做 smoke：

```bash
OPENCLAW_LARK_BRIDGE_SCRIPT=./examples/fake-openclaw-lark-bridge.py python3 skills/pm/scripts/pm.py run-reviewed --task-id T1 --backend codex-cli --agent codex
OPENCLAW_LARK_BRIDGE_SCRIPT=./examples/fake-openclaw-lark-bridge.py python3 skills/pm/scripts/pm.py monitor-status --task-id T1
OPENCLAW_LARK_BRIDGE_SCRIPT=./examples/fake-openclaw-lark-bridge.py python3 skills/pm/scripts/pm.py complete --task-id T1 --content "local monitor smoke"
```

#### Feishu 插件

Feishu 集成依赖运行时插件 `@larksuite/openclaw-lark`，不是本仓库自带代码。

最小检查与安装顺序：

```bash
openclaw plugins list
openclaw plugins info openclaw-lark
openclaw plugins install @larksuite/openclaw-lark
openclaw gateway restart
```

验收标准不是“记住某个包名”，而是：

- `openclaw plugins info openclaw-lark` 显示 `Status: loaded`
- 插件工具面可用

补充一个运行态约束：

- 如果你已经启用了 `openclaw-lark`，通常不要再把内置 `plugins.entries.feishu.enabled` 打开
- 两套 Feishu 工具同时注册时，可能出现 `plugin tool name conflict (openclaw-lark): feishu_chat`
- 在远端真实环境里，这种双注册还可能把 `openclaw plugins list` 顶到 Node OOM

### 2.3 如果目标包含 Feishu，立刻并行准备

不要等本地 smoke 全跑完才让用户去准备 Feishu。

用户侧应并行完成：

1. 创建飞书应用
2. 开启 Bot 能力
3. 准备 `appId` / `appSecret`
4. 创建目标群
5. 申请 task / attachment / doc 相关权限

这里的预期是 OAuth 授权链接或卡片，不是 OpenClaw pairing 二维码。

### 2.4 路径约定

这套仓库按下面顺序查找运行时入口：

1. 显式环境变量覆盖
2. `PATH`
3. 平台候选目录

常见覆盖项：

- `OPENCLAW_BIN`
- `CODEX_BIN`
- `GSD_TOOLS_PATH`
- `OPENCLAW_CONFIG`
- `OPENCLAW_HOME`
- `PM_STATE_DIR`
- `PM_WORKSPACE_ROOT`
- `PM_WORKSPACE_TEMPLATE_ROOT`

如果一台机器上同时有多个 OpenClaw profile，建议显式设置：

```bash
export OPENCLAW_CONFIG=/abs/path/to/real/openclaw.json
```

不要依赖 repo 根目录里的占位 `openclaw.json` 自动猜。

例如：

```bash
export OPENCLAW_CONFIG=/abs/path/to/openclaw.json
```

路径建议：

- macOS / Linux：`/abs/path/to/workspace`
- Windows JSON：`C:/path/to/workspace` 或 `C:\\path\\to\\workspace`

## 3. Step 1：本地无鉴权验证

这一段只验证仓库本身，不要求你已经接入 OpenClaw 或 Feishu。

### 3.1 CLI 与语法检查

```bash
python3 -m py_compile skills/pm/scripts/*.py skills/coder/scripts/*.py skills/openclaw-lark-bridge/scripts/*.py
python3 skills/pm/scripts/pm.py --help
python3 skills/pm/scripts/pm.py context --help
python3 skills/coder/scripts/observe_acp_session.py --help
python3 skills/openclaw-lark-bridge/scripts/invoke_openclaw_tool.py --help
```

至少记录：

- `python3` 路径
- `node` 路径
- `openclaw` 路径
- `codex` 路径

### 3.2 先跑 `pm init --dry-run`

```bash
python3 skills/pm/scripts/pm.py init --project-name demo --dry-run
```

如果项目名包含中文或其他非 ASCII 字符：

```bash
python3 skills/pm/scripts/pm.py init --project-name "测试项目" --english-name demo --dry-run
```

重点看：

- `status: "dry_run"`
- `config_preview`
- `workspace_bootstrap`

说明：

- 这一段只是在验证 repo-local CLI 形状，不等于你已经完成了真实安装
- 不传 `--group-id` 时，`workspace_bootstrap: null` 是预期行为
- 非 ASCII 项目名未传 `--english-name` 会直接报错

### 3.3 刷新上下文并验证 GSD 路由

```bash
python3 skills/pm/scripts/pm.py context --refresh
python3 skills/pm/scripts/pm.py route-gsd --repo-root .
```

至少保留这些 evidence：

- `.pm/current-context.json`
- `.pm/bootstrap.json`
- `.pm/doc-index.json`
- `route-gsd` 输出里的 `runtime.ready`

如果 `route-gsd` 已经报：

- `gsd-tools not found`
- `node not found`

就先修运行时，不要继续谈 `plan-phase`。

### 3.4 repo-local smoke 建议口径

如果你只是要证明仓库本地可用，这一组命令已经够用：

```bash
python3 skills/pm/scripts/pm.py init --project-name demo --task-backend local --doc-backend repo --write-config --skip-auto-run --skip-bootstrap-task --no-auth-bundle
python3 skills/pm/scripts/pm.py context --refresh
python3 skills/pm/scripts/pm.py route-gsd --repo-root .
```

这里用 `--write-config`，不是为了偷懒，而是为了把 `local/repo` 这组最小配置真正落到当前副本里；否则前一条只做 `--dry-run`，后面的 `context --refresh` 仍会回到默认 backend。

如果你要再证明本地 task/doc 写入链路也可用，可以补：

```bash
python3 skills/pm/scripts/pm.py create --summary "Install smoke task"
python3 skills/pm/scripts/pm.py upload-attachments --task-id T1 --file ./README.md
python3 skills/pm/scripts/pm.py complete --task-id T1 --content "local smoke done"
python3 skills/pm/scripts/pm.py get --task-id T1 --include-completed
```

预期：

- `.pm/local-tasks.json` 出现任务
- `attachments` 非空
- `comments` 中出现完成说明

## 4. Step 2：接入 OpenClaw

本地无鉴权验证通过以后，再做这一步。

### 4.1 复制仓库资产

这一段要分清楚两侧：

```text
Codex / CODEX_HOME
skills/pm                    -> ~/.codex/skills/pm
skills/coder                 -> ~/.codex/skills/coder
skills/openclaw-lark-bridge  -> ~/.codex/skills/openclaw-lark-bridge

OpenClaw workspace
plugins/acp-progress-bridge  -> $OPENCLAW_WORKSPACE/plugins/acp-progress-bridge
```

默认推荐：

- `pm`、`coder`、`openclaw-lark-bridge` 先放到 Codex skills 目录
- `acp-progress-bridge` 只放到 OpenClaw plugins 目录
- `skills/openclaw-lark-bridge` 不作为默认 OpenClaw workspace 资产

推荐直接用 repo 内命令同步运行时资产：

```bash
python3 skills/pm/scripts/pm.py install-assets --workspace-root "$OPENCLAW_WORKSPACE"
```

这条命令会默认完成：

- `skills/pm` → `~/.codex/skills/pm`
- `skills/coder` → `~/.codex/skills/coder`
- `skills/openclaw-lark-bridge` → `~/.codex/skills/openclaw-lark-bridge`
- `plugins/acp-progress-bridge` → `$OPENCLAW_WORKSPACE/plugins/acp-progress-bridge`
- `skills/pm` → `$OPENCLAW_WORKSPACE/skills/pm`
- `skills/coder` → `$OPENCLAW_WORKSPACE/skills/coder`

如果你只想预览、不想落盘，先跑：

```bash
python3 skills/pm/scripts/pm.py install-assets --workspace-root "$OPENCLAW_WORKSPACE" --dry-run
```

如果目标目录已经存在并且你确认要替换，再加：

```bash
python3 skills/pm/scripts/pm.py install-assets --workspace-root "$OPENCLAW_WORKSPACE" --force
```

复制/安装后立刻检查：

- `~/.codex/skills/pm/SKILL.md` 是否存在
- `~/.codex/skills/coder/SKILL.md` 是否存在
- `~/.codex/skills/openclaw-lark-bridge/SKILL.md` 是否存在
- `$OPENCLAW_WORKSPACE/skills/pm/SKILL.md` 是否存在
- `$OPENCLAW_WORKSPACE/skills/coder/SKILL.md` 是否存在
- `$OPENCLAW_WORKSPACE/plugins/acp-progress-bridge` 是否存在

这里仍然不建议默认复制：

```text
skills/openclaw-lark-bridge -> $OPENCLAW_WORKSPACE/skills/openclaw-lark-bridge
```

手工 `cp -R` 仍然可行，但它现在只是 fallback，不再是推荐主路径。

### 4.2 最小 OpenClaw 配置

最低要求：

1. 有真实可见的 front agent
2. `acp` 已启用
3. 如果该 front agent 直接依赖 repo skills，再给它挂 `pm` 和 `coder`

最小形状：

```json
{
  "agents": {
    "list": [
      {
        "id": "your-agent-id",
        "name": "your-agent-id",
        "workspace": "REPLACE_WITH_ABSOLUTE_WORKSPACE_PATH",
        "skills": ["pm", "coder"]
      }
    ]
  },
  "acp": {
    "enabled": true,
    "backend": "acpx",
    "defaultAgent": "codex"
  }
}
```

注意：

- `front agent` 配的是你要直接对话的 agent
- ACP worker 由 `acp.defaultAgent` 或运行时派发逻辑决定
- 两者可以相同，也可以不同
- `openclaw-lark-bridge` 默认是 Codex 侧 skill，不是 OpenClaw agent 必挂 skill

验证：

```bash
acpx --help
openclaw agents list --bindings
openclaw plugins list
```

### 4.3 最小 PM 配置

`pm.json` 至少要明确：

1. `repo_root`
2. `project.name`
3. `project.agent`
4. `task.backend`
5. `doc.backend`
6. `coder.backend`
7. `coder.agent_id`

本地优先最小配置：

```json
{
  "repo_root": ".",
  "task": { "backend": "local" },
  "doc": { "backend": "repo" }
}
```

这里把 `repo_root` 写成 `"."`，就是为了让同一份配置跟着仓库一起移动；只要 `pm.json` 在仓库根目录，复制到新目录后仍能直接使用。

如果要接 Feishu，再补：

- `task.tasklist_guid` 或可解析的 `tasklist_name`
- `doc.folder_token`
- `project.group_id`

修改后验证：

```bash
python3 skills/pm/scripts/pm.py context --refresh
python3 skills/pm/scripts/pm.py next --refresh
```

不要直接把旧机器上的 `pm.json` 原样复制到新机器继续跑。至少要重写：

- `repo_root`
- backend 类型
- 旧 `group_id`
- 旧 token / 文档地址

## 5. Step 3：可选接 Feishu / OAuth / Bridge

如果当前目标只是本地或 OpenClaw 接入验证，可以跳过本节。

### 5.1 Feishu 接入最小要求

先完成飞书应用准备，再回头写 repo 配置。

最少需要：

1. 飞书应用和 Bot
2. `appId` / `appSecret`
3. 事件订阅
4. task / doc / attachment 所需权限
5. 目标群

建议优先参考：

- OpenClaw Feishu 文档
- `larksuite/openclaw-lark` README

安装后先做诊断，不要手抄一大段权限清单。

### 5.2 OpenClaw Feishu 配置

最小形状：

```json5
{
  channels: {
    feishu: {
      enabled: true,
      domain: "feishu",
      accounts: {
        main: {
          appId: "cli_xxx",
          appSecret: "xxx",
          name: "My AI assistant"
        }
      }
    }
  }
}
```

如果是国际版 Lark，把 `domain` 改成 `"lark"`。

如果目标是群会话，还要补：

- `bindings`
- `channels.feishu.groups`
- 必要时 `groupAllowFrom`

这里有一个高频坑：

- `allowFrom` 通常是用户
- `groupAllowFrom` 通常是群 id，例如 `oc_xxx`

如果 `groupPolicy = "allowlist"`，但 `groupAllowFrom` 里写成用户 open_id，机器人会收到群消息但不回复。

### 5.3 统一授权入口

现在 `pm init` 默认会附带 `auth_bundle`。

如果你想单独重新生成整套授权引导，直接运行：

```bash
python3 skills/pm/scripts/pm.py auth
```

默认会一次性输出：

- tenant 应用权限 bundle
- 群里不用 `@` 也回复所需的敏感权限
- 附件上传所需的 user OAuth 链接
- 机器人侧建议执行的 `/auth` / `/feishu auth`
- 当前仍需人工确认的步骤

输出里可以直接优先看这几个顶层字段：

- `permission_url`
- `app_scope_auth_url`
- `user_oauth_verification_url`
- `manual_steps`

如果你只想做最小初始化、不想默认生成这组引导，可以显式关闭：

```bash
python3 skills/pm/scripts/pm.py init --project-name demo --no-auth-bundle --dry-run
```

### 5.4 `/auth` 与附件 OAuth

Bot 能收消息后，要明确引导用户主动触发授权：

- 优先尝试 `/auth`
- 如果机器人帮助文案显示 `/feishu auth`，以机器人提示为准

附件上传不是 bridge 行为，而是 PM 直接调用 Feishu attachment API。

第一次执行下面命令时，如果还没有有效 OAuth：

```bash
python3 skills/pm/scripts/pm.py attachments --task-id T1
python3 skills/pm/scripts/pm.py upload-attachments --task-id T1 --file ./evidence.txt
```

预期会返回：

- `status = "authorization_required"`
- `verification_uri_complete`
- `user_code`

也可以主动取授权链接：

```bash
python3 skills/pm/scripts/pm.py auth-link \
  --mode user-oauth \
  --scopes task:task:read task:attachment:read task:attachment:write offline_access
```

如果附件授权失败，按这个顺序排查：

1. `openclaw.json` 里是否已有 `channels.feishu.appId` / `appSecret`
2. app 权限是否完整
3. 返回的授权链接是否由正确账号完成
4. state 目录里是否残留过期 token / pending 文件

补充一个这次远端真实踩到的坑：

- 如果 `appSecret` 不是明文，而是 OpenClaw SecretRef，例如 `{"source":"file","provider":"lark-secrets","id":"/lark/appSecret"}`，旧版 PM 可能会把它当普通字符串直接发给飞书，表现为 `device authorization failed: invalid_client`
- 现在仓库内 PM 已支持解析常见的 `env` / `file` / `exec` SecretRef；如果你在旧环境里遇到这个报错，先不要急着怀疑飞书凭证本身错了，先检查是不是 SecretRef 没有被正确解引用

### 5.5 把飞书权限开通抽出来

不要把“权限开通”混在长链路安装末尾再做。

尤其下面这类能力，应该单独准备并尽早验：

- 群里不用 `@` 也回复
- PM 附件上传
- Feishu task / doc 真同步

先看内置 preset：

```bash
python3 skills/pm/scripts/pm.py permission-bundle --list-presets
```

给 OpenClaw Lark 插件生成 tenant 权限导入 JSON：

```bash
python3 skills/pm/scripts/pm.py permission-bundle \
  --preset openclaw-lark-tenant-baseline
```

给“群里不 @ 也回复”额外生成敏感权限导入 JSON：

```bash
python3 skills/pm/scripts/pm.py permission-bundle \
  --preset openclaw-lark-tenant-baseline \
  --preset group-open-reply
```

输出里重点看：

- `permission_url`
- `auth_url`
- `import_payload`
- `notes`
- `manual_steps`

这一步的定位要说清楚：

- PM 现在能帮你生成权限页链接和批量导入 JSON
- 但 `im:message.group_msg` 这类敏感权限，仍然要在飞书开放平台确认新增权限并重新发布应用
- 也就是说，这不是“后台全自动开通”，而是“把要开的权限一次性整理好，减少人工抄写和漏项”
- 飞书官方插件能自动化的是“扫码建 bot / 写配置 / 生成用户授权入口”，不能替你在开放平台代点“确认新增权限”“创建版本”“确认发布”

如果你已经把 `requireMention=false` 配好了，但群里还是必须 `@` 才回复，优先检查这里，而不是反复重装 OpenClaw。

### 5.6 用户手动步骤要单独看

完整安装里，下面这些动作一定要明确告诉用户是“手动步骤”：

1. 手动运行 `npx -y @larksuite/openclaw-lark install`
2. 如果安装过程要求扫码或确认 App 信息，用户自己完成
3. 手动在飞书开放平台导入权限、确认新增权限并发布
4. 手动在飞书里执行 `/auth` 或 `/feishu auth`
5. 手动在目标群里发普通消息验证机器人是否已经能免 `@` 回复

不要把这些步骤写成“AI 会自动做好”，否则后面最容易绕晕。

### 5.7 可选启用 progress bridge

只有在你需要下面能力时，才启用 `acp-progress-bridge`：

- 子会话进度自动回推
- 子会话完成结果自动回推
- Feishu 群内持续看到执行状态

它不是最小安装前置。

如果 bridge 没有自动汇报，按这个顺序排查：

1. `parentSessionPrefixes` 是否命中父会话
2. `childSessionPrefixes` 是否命中子会话
3. OpenClaw session store / transcript / ACP stream 是否存在
4. `bridge-status` 是否已显示 `progress delivered` 或 `completion delivered`

如果 plugin 内部已经 delivered，但外部仍看不到结果，再去查父会话策略、bindings 或消息投递链路。

## 6. 验收建议

### 6.1 最小可交付

如果只做本地验证，至少交付：

1. `py_compile`
2. `pm.py --help`
3. `init --write-config --skip-auto-run --skip-bootstrap-task --no-auth-bundle`
4. `context --refresh`
5. `route-gsd --repo-root .`

如果还想额外证明 CLI 形状没问题，再补一条 `init --dry-run` 即可；但真正的 repo-local 主线验收，要以前面这组“已落配置”的命令为准。

### 6.2 OpenClaw 接入验收

至少补：

1. `openclaw agents list --bindings`
2. `openclaw plugins list`
3. `python3 skills/pm/scripts/pm.py next --refresh`

### 6.3 完整集成验收

如果用户明确要求 Feishu E2E，再继续做。

这里的前置条件必须已经满足：

1. OpenClaw runtime 已可用
2. `openclaw-lark` 已安装并加载
3. `channels.feishu` 已配置
4. 飞书 app / bot / 群 / 权限已准备好
5. 用户已能通过 `/auth` 或环境里的等价命令完成授权

真正的完整链路才是：

1. 创建真实任务
2. 派给 Codex
3. 观察 bridge 回推
4. 完成任务
5. 读取最终状态

可直接按下面顺序执行：

```bash
python3 skills/pm/scripts/pm.py init --project-name demo --group-id oc_xxx --task-backend feishu --doc-backend feishu --write-config
python3 skills/pm/scripts/pm.py create --summary "Install E2E smoke task" --request "Verify PM -> coder -> bridge -> completion flow"
python3 skills/pm/scripts/pm.py run --task-id T1
python3 skills/pm/scripts/pm.py complete --task-id T1 --content "E2E smoke done"
python3 skills/pm/scripts/pm.py get --task-id T1 --include-completed
```

建议最终交付统一按这几个状态汇报：

```text
Installation Summary
- repo_smoke: pass/fail
- gsd_runtime: pass/fail
- openclaw_runtime: pass/fail
- openclaw_lark: pass/fail
- progress_bridge: not_run/pass/fail
- feishu_binding: not_run/pass/fail
- attachment_oauth: not_run/pass/fail
```

## 7. 常见问题

- `workspace` 不是绝对路径：改成目标机器真实绝对路径
- Windows JSON 路径未转义：优先写 `C:/...`
- 中文项目名没传 `--english-name`：补参数
- `route-gsd` 的 `runtime.ready = false`：先检查 `node` 和 `gsd-tools`
- `plan-phase` 报 `Unknown agent id`：说明 front agent 不存在，不要把 ACP worker 当成 front agent
- `upload-attachments` 一直返回 `authorization_required`：附件 OAuth 还没完成，不等于 PM 安装失败
- `openclaw plugins info openclaw-lark` 不是 `Status: loaded`：插件未安装、未启用或版本不兼容
- 群消息到了但机器人不回：优先检查 `groupAllowFrom` 是否写成了错误的用户 id
- `invoke_openclaw_tool.py --dry-run` 失败：通常是 `openclaw.json`、gateway token 或 gateway URL 解析有问题

## 8. 运行态目录

| 类别 | 典型位置 | 说明 |
|------|----------|------|
| repo-local | `.planning/`, `.pm/`, `./openclaw.json`, `./.openclaw/openclaw.json` | 跟当前仓库强相关，适合版本化 |
| user-global | `~/.openclaw/`, `~/.config/openclaw/`, `%APPDATA%\\OpenClaw\\`, `%LOCALAPPDATA%\\OpenClawPMCoder\\` | 跟当前用户环境强相关，不应直接提交 |

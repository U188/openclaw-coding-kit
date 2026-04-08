# demo ROADMAP

## 当前阶段
### Phase 0 · local-first 验证
目标：先验证仓库、运行时与 OpenClaw 基础接线，不引入 Feishu 变量。

已完成：
- [x] 拉取仓库到 `/root/openclaw-coding-kit`
- [x] 安装 `gsd-tools`
- [x] 安装 `acpx`
- [x] 配置并验证 `codex`
- [x] 跑通 `pm init`
- [x] 跑通 `pm context --refresh`
- [x] 跑通 `pm route-gsd`
- [x] 定位 `sessions_spawn` 桥接失配根因
- [x] 为 `backend=acp` 增加自动回退到 `openclaw` backend 的修复

待完成：
- [ ] 用修复后的流程完成 T1 brownfield 初始化任务并回填任务状态
- [ ] 为回退逻辑补自动化测试

## Phase 1 · OpenClaw 协作链稳定化
目标：让 PM + coder 在当前 OpenClaw 上稳定运行。

任务：
- [ ] 收口 `pm_dispatch.py` / `invoke_openclaw_tool.py` 的兼容逻辑
- [ ] 明确 `sessions_spawn` 在当前 OpenClaw 构建中的真实可用调用面
- [ ] 给 `README` / `INSTALL` 增加兼容说明，避免“版本够但桥不通”的误判
- [ ] 验证 `openclaw` backend 与 `codex-cli` backend 的行为差异

## Phase 2 · progress bridge 与 ACP 完整链
目标：在不接飞书的前提下，补齐父子会话进度回传体验。

任务：
- [ ] 验证 `acp-progress-bridge` 在当前环境的事件回传
- [ ] 明确主会话、子会话、bridge 三者的数据契约
- [ ] 形成 repo-local E2E smoke 命令

## Phase 3 · 可选 Feishu 集成
目标：在 local-first 验证稳定后，再按需接 Feishu。

任务：
- [ ] 校验 Feishu plugin 只保留单一路径，避免重复注册
- [ ] 验证 task/doc OAuth 与权限 bundle
- [ ] 补 integrated mode 文档与验收命令

## 当前阻塞
- OpenClaw `2026.3.24` 当前构建下，`/tools/invoke` 不暴露 `sessions_spawn`
- 仓库默认 `acp` 桥接与当前构建的工具暴露策略不一致

## 当前可执行主线
1. 继续用修复后的 PM 流程完成 T1
2. 让仓库在 `backend=acp` 配置下也能自动回退为 `openclaw` backend
3. 再决定是否进一步修正 ACP 原生桥接契约

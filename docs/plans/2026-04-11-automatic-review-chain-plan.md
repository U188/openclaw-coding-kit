# 2026-04-11 自动 review chain 执行计划

- 关联需求：`docs/requirements/2026-04-11-automatic-review-chain.md`
- 关联任务：T8
- 执行等级：L
- Repo：`/root/openclaw-coding-kit`

## 主状态源
1. `.pm/runs/<run_id>.json`
2. `.pm/monitors/<run_id>.json`
3. `review verdict` 结构化落盘（优先并入 run record，必要时补独立文件）
4. 自动推进相关 comments / cleanup metadata（辅助）

## 完成条件
- `run-reviewed` 后无需人工 `pm review`
- 系统可自动产出 verdict 并据此推进 `rerun / complete`
- monitor 能自动收口，且状态真实可复核
- 文档和测试齐全，验证命令通过

## 监控方式
- 继续使用 cron monitor，但角色从“提醒器”升级为“推进守卫”
- monitor 只在状态变化时发声，完成后自动删 cron
- reviewer executor 的执行结果必须被 monitor / PM 消费到，而不是停留在一次性输出

## 阶段划分

### Phase 1：状态机与 contract 设计
目标：定义自动链的状态、字段、因果边界
步骤：
1. 梳理现有 `review_status / attempt / review_round / rerun_of_run_id / monitor_status`
2. 定义 reviewer verdict contract
3. 定义自动推进状态（如 `awaiting-reviewer` / `auto-rerun-requested` / `auto-complete-requested` 等）
验收点：run/monitor 结构设计明确，避免状态歧义

### Phase 2：reviewer executor 落地
目标：实现能读取 run 产物并输出结构化 verdict 的执行器
步骤：
1. 选定挂载点（PM 命令层 / monitor 调度层 / 独立模块）
2. 接入必要输入：summary、tests、diff、证据
3. 输出标准 verdict + evidence + feedback
验收点：能在本地测试中稳定产出 pass/fail

### Phase 3：自动分叉推进
目标：把 reviewer verdict 接回 PM 主链
步骤：
1. pass -> 自动 `complete` 等价逻辑
2. fail -> 自动 `rerun` 等价逻辑
3. 写回因果字段，确保可审计
验收点：happy path 与 fail path 均无需人工 `pm review`

### Phase 4：monitor 升级与收口
目标：让 monitor 从提醒器升级为推进守卫
步骤：
1. 消费 reviewer verdict
2. 控制提醒节奏，避免刷屏
3. 完成后自动 stop + remove cron
验收点：monitor 状态与 run record 一致，stop 有证据

### Phase 5：文档与验证
目标：让机制、文档、测试一致
步骤：
1. 更新 README / SKILL / spec
2. 补单测 / 集成测试
3. 跑完整验证命令
验收点：测试通过，文档与行为一致

## 风险点
- 自动 reviewer 若证据输入不足，可能误判 pass
- rerun/complete 自动推进若因果字段设计差，会造成循环触发或重复收口
- cron monitor 与 reviewer executor 若职责重叠，容易出现双写状态
- 自动链若只看命令成功，不看最终落盘，会再次回到“假自动化”

## 回滚方案
- 保留当前 manual review gate 作为可切换 fallback
- 新增自动链逻辑时以显式配置开关守护，未通过验证前不默认替换旧链
- 出现状态机混乱时，可回退到 `pm review / pm rerun / pm complete` 的现有人工链

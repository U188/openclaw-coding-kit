# 2026-04-09 PM Auto Review Loop

## 背景
主人要求把 `openclaw-coding-kit` 的执行链改成稳定机制：
- 实施工作默认派给 worker 去做
- 主会话/前台只负责审核
- 审核不通过时，自动把问题打回给 worker 重做
- 重要任务不依赖主人反复催办
- 结果必须有机器可读的留痕，不能只靠口头说明

当前现实问题：
1. `pm run` 只能派发 worker，一次执行结束后没有正式的 review gate。
2. `pm complete` 没有强制“先审核通过再完成”的门禁。
3. worker 在 clean worktree 产出后，前台仍需要手工判断、手工打回、手工记忆当前第几轮。
4. `reviewer_worker` 只存在于 workspace profile，尚未形成真正的执行闭环。

## 目标
把流程升级为默认可重复使用的机制：
1. `pm run-reviewed`：一次命令里完成 worker 执行 + 进入审核态。
2. `pm review`：写入结构化审核结果（pass / fail）。
3. 审核失败后，`pm rerun` 能基于上次失败意见自动生成返工 handoff，再次派发 worker。
4. `pm complete` 默认拒绝未通过审核的任务，除非显式 `--force-review-bypass`。
5. `.pm/last-run.json` 和每次 run record 都要保留 review 状态、失败意见、轮次、最近 verdict。
6. README / INSTALL / example config 一起同步，形成机制，而不是只改代码。

## 非目标
- 这次不做真正的多 agent 自治评审闭环（例如 reviewer 也完全自动调用另一个 ACP worker 并自己判定）。
- 这次先不接浏览器自动化审计编排；review 结果先由前台或外部审核器写入 `pm review`。
- 这次不改 Feishu/Docs 的权限流。

## 机制设计

### 一、运行记录新增 review 元数据
在 `.pm/last-run.json` / `.pm/runs/<run_id>.json` 中新增：
- `attempt`
- `review_status`：`pending | passed | failed | bypassed`
- `review_required`：bool
- `review_round`
- `review_feedback`
- `reviewer`
- `reviewed_at`
- `review_history[]`
- `rerun_of_run_id`

默认：
- 新 run 产生后，若 review gate 开启，则 `review_status = "pending"`
- 只有 `pm review --verdict pass` 才能进入 `passed`
- `pm complete` 看到 `pending/failed` 时拒绝完成

### 二、命令层新增三条主命令

#### 1) `pm run-reviewed`
等价于：
- 跑一次 `pm run`
- 自动标记 `review_required = true`
- 写入 `review_status = pending`
- 输出 review gate 提示与 run_id

用途：
- 主流程默认从这里进，不再裸用 `pm run`

#### 2) `pm review`
输入：
- `--task-id` / `--run-id`
- `--verdict pass|fail`
- `--feedback` / `--feedback-file`
- `--reviewer`

行为：
- 更新 `last-run` 和对应 run record
- `pass`：标记审核通过
- `fail`：标记审核失败，并记录返工意见
- 可选把审核结论同步写回 task comment / STATE

#### 3) `pm rerun`
输入：
- `--task-id` / `--run-id`
- `--backend` / `--agent` 可覆盖

行为：
- 读取上次失败 run 的 `review_feedback`
- 把失败意见追加进新的 coder handoff
- 递增 `attempt` / `review_round`
- 写 `rerun_of_run_id`
- 新 run 默认继续 `review_status = pending`

### 三、完成门禁
`pm complete` 新增：
- 默认要求最近一次 run `review_status in {passed, bypassed}`
- 如果不是，则直接拒绝，并返回结构化错误：
  - 当前 run_id
  - 当前 review_status
  - 最近 review_feedback
  - 建议下一步：`pm review` 或 `pm rerun`
- 特殊情况下允许 `--force-review-bypass`，并把 `review_status = bypassed` 写入记录

### 四、配置默认项
`pm_config.default_config()` / `examples/pm.json.example` 新增：
```json
"review": {
  "required": true,
  "enforce_on_complete": true,
  "sync_comment": true,
  "sync_state": true
}
```

### 五、文档与验收
README / INSTALL / 示例配置更新：
- 推荐主流程从 `pm run-reviewed` 开始
- 审核不通过用 `pm review --verdict fail ...` + `pm rerun`
- 通过后再 `pm complete`

## 实施步骤
1. 扩展默认配置与 helper，加入 review config/record helper。
2. 在 `pm_commands.py` 内抽取“创建 run record”的公共逻辑。
3. 新增 `run-reviewed` / `review` / `rerun` / `complete --force-review-bypass`。
4. 为 `pm complete` 增加 review gate 检查。
5. 补测试：
   - review-required run 初始为 pending
   - review pass 后可 complete
   - review fail 时 complete 被拒绝
   - rerun 会继承失败意见并增加轮次
6. 同步 README / INSTALL / examples。

## 验收标准
满足以下全部条件才算通过：
1. `python3 -m unittest tests.test_pm_commands tests.test_pm_local_cli tests.test_pm_runtime` 通过。
2. 本地临时 repo 中可完成：
   - `create`
   - `run-reviewed`
   - `review fail`
   - `rerun`
   - `review pass`
   - `complete`
3. `pm complete` 对未审核通过任务会明确拒绝，不允许再口头假完成。
4. `.pm/last-run.json` 与 run record 能看到 review 历史与当前 verdict。

## 推荐结论
这次不再把“我来盯 review loop”当流程，而是把它写进 PM 命令层，变成默认门禁。这样以后真正能做到：
- worker 干活
- 前台只审核
- 不通过自动打回
- 主人不用反复催

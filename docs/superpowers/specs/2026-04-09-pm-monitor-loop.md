# PM Worker Monitor Loop Spec

## 背景
当前 `openclaw-coding-kit` 已经有 `run-reviewed -> review -> rerun -> complete` 的审核闭环，但还没有稳定的“监工闭环”。

缺口在于：
- worker 异步执行期间，没有机器可读的巡检状态
- 没有统一的循环 cron 来持续提醒/巡检
- 任务完成后，没有自动撤销巡检 cron 的机制
- 返工重跑时，旧监工与新监工的交接没有结构化留痕

## 目标
为 PM 增加一套默认可复用的监工机制：
1. 异步 worker run 启动时，自动创建一条 monitor cron
2. monitor cron 绑定到明确的 PM run / task / repo_root，不靠操作者记忆
3. monitor 状态写入 `.pm/monitors/<run_id>.json`，并同步进 `.pm/last-run.json` / `.pm/runs/<run_id>.json`
4. `pm rerun` 会关闭上一轮 monitor，再为新 run 创建新 monitor
5. `pm complete` 或 `pm monitor-stop` 会自动撤销 monitor cron，并把 stop 结果写回 run record
6. monitor tick 以“状态变化提醒”为主，不做高频刷屏

## 非目标
- v1 不做复杂的 ACP 流事件解析
- v1 不新增数据库或外部队列
- v1 不改 Feishu 权限流
- v1 不要求 monitor 自己完成 review 判定；当前 review 机制仍是由 `pm review` / `pm complete` 驱动的手动 review gate，不是自动 review chain

## 约束
- 保持 KISS，不引入新依赖
- 默认只对异步 run（优先 ACP）启用 monitor；同步本地 run 返回 `not-applicable`
- monitor 必须是幂等的：同一 run 不能重复挂多条活跃 cron
- 监工的“命令成功”不算完成；必须把最终 monitor 状态写回文件
- `monitor.status=active` 只能在 cron add 后再次校验 job 确实存在时写回；否则必须显式落成 `cron-error` / `skipped-no-cron`
- 文档、示例配置、测试一起更新

## v1 机制结论
- 新增 `monitor` 配置段，控制是否启用、巡检间隔、超时阈值、提示策略
- 新增 `pm_monitor.py` 作为唯一监工状态模块
- `pm run-reviewed` / `pm rerun`：创建 monitor state + cron job
- `pm complete`：自动 stop monitor
- 新增 `pm monitor-status` / `pm monitor-stop`
- monitor cron prompt 读取 `.pm/monitors/<run_id>.json` 与 `.pm/runs/<run_id>.json`，只在状态变化时提醒；检测到 run 已完成时自删 cron 并关闭 monitor

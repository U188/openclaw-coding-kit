# 2026-04-11 自动 review chain 需求冻结

- 日期：2026-04-11
- 模式：autonomous
- 关联任务：T8
- Repo：`/root/openclaw-coding-kit`

## 目标
把当前 `pm run-reviewed -> pm review --verdict pass|fail -> pm rerun / pm complete` 的**人工 review gate**升级成**机制化全自动闭环**，使受管执行链在 worker 完成后可自动完成审查、落盘 verdict、触发 rerun 或 complete，并自动收口 monitor，不再依赖操作者手工执行 `pm review`。

## 交付物
1. review verdict 的结构化 contract（机器可读）
2. reviewer executor（能消费 run 产物并输出 `pass|fail + evidence + feedback`）
3. PM 命令与 run record 升级，支持自动 verdict 写回
4. fail -> 自动 rerun 机制
5. pass -> 自动 complete 机制
6. monitor 升级为状态推进器，而不是只提醒不推进
7. README / SKILL / spec / tests 同步更新

## 约束
- 保持 T4（dashboard 首页改造）暂停，不混入任何 dashboard 代码或任务收口
- 不修改与本需求无关的 `.planning/STATE.md`、`.codex` 等噪声文件
- 保持现有 PM tracked flow 为入口，不退回主聊天会话手工代做业务编码
- 自动化必须诚实：不能把“命令返回成功”写成“流程真实完成”
- 自动 complete 前必须具备明确证据，不允许跳过验证
- monitor / reviewer / PM 状态必须有统一、可复核的文件落盘

## 验收标准
1. `pm run-reviewed` 启动后，不需要人工执行 `pm review`
2. worker 达到可审查状态后，系统会自动生成 verdict
3. 若 verdict=fail：
   - feedback 被写入 run record
   - 自动触发 `pm rerun` 等价逻辑
   - 新 run 继承上一轮反馈
4. 若 verdict=pass：
   - 自动触发 `pm complete` 等价逻辑
   - completion / cleanup / monitor stop 均被结构化写回
5. `complete` 前若缺少验证证据，自动链不得伪造 pass
6. `.pm/runs/*.json`、`.pm/last-run.json`、`.pm/monitors/*.json` 中能看出：
   - verdict 来源
   - 自动推进阶段
   - rerun / complete 的因果关系
7. 至少有覆盖自动 pass、自动 fail->rerun、monitor auto-stop 的测试

## 非目标
- 本轮不做通用 LLM 评审平台
- 本轮不接入外部数据库或消息队列
- 本轮不改 Feishu 权限流
- 本轮不顺手处理 T4 或其他 dashboard/UI 事项

## 推断说明（autonomous）
- 自动 review 的主状态源应继续落在 `.pm/runs/*.json` 与 `.pm/monitors/*.json`，必要时增加 reviewer verdict 文件或 run 字段，而不是靠聊天记忆
- monitor 不应直接代替 reviewer 做语义判断；更稳的方式是 monitor 负责推进，reviewer 负责产出 verdict
- 全自动链仍需保留人工旁路/强制终止能力，但默认 happy path 不依赖人工

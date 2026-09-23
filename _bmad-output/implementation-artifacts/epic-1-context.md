# Epic 1 Context: 执行中可问可答（引擎与 API 级闭环）

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

平台的无头技能与 AI 命令执行到中途，可就「只有用户能定的事」发起提问：任务转入 waiting 并暴露问题明细，用户经 `POST /api/tasks/{id}/answer` 应答或取消，任务带着答案恢复运行（可多轮问）；超时、取消、异常与服务重启各有明确归宿。本 Epic 交付引擎与 API 级闭环，curl 即可完成全链操作，独立可用；Epic 2 的面板问答在其之上构建。

## Stories

- Story 1.1: AskUser 工具与问题桥（askuser.py 核心）
- Story 1.2: run() 接线与挂载矩阵
- Story 1.3: 应答端点与状态机收尾
- Story 1.4: 全链验证与边界测试

## Requirements & Constraints

**AskUser 工具**
- 工具名 `AskUserQuestion`（与 Claude Code/vendor 同名同义，技能正文双环境通用），平台自写；挂载于技能 invoke 与 AI 命令栏两类运行，scaffold_build 等无人值守任务不挂
- 输入 schema 对齐 vendor 惯例：1-4 问 × 每问 question + 2-4 选项（label/description）+ multiSelect（默认单选）；用户端恒可自由输入
- 同批单问：任一时刻一个任务至多一个待答问题；工具描述与系统提示词写明「何时该问」——仅限依赖用户偏好/授权的分叉，可查资料自答的不许问

**waiting 态与超时**
- 任务状态机扩为 `running|waiting|success|failed`；发起提问即 waiting，问题明细挂 `task_runs.payload.pending_question`
- 等待期吃 `skill_run_timeout`（默认 3600s）同一额度，不另设等待超时
- 服务重启孤儿清扫覆盖 waiting：与 running 一同置 failed「服务重启，任务中断」并清 pending_question

**应答 API**
- `POST /api/tasks/{id}/answer`：`{"id", "answers": [{"question", "answer": str}]}` 多问题一并提交，或 `{"id", "cancel": true}`；顶层 id = pending_question.id
- 200 成功投递并留痕；404 无任务；409 非 waiting / 无桥 / id 不匹配 / 重复提交；应答后任务回 running

**横切**
- 线程安全：提问/应答横跨 worker 线程与事件循环，JSON 列整体重赋值沿用
- 留痕：问 `❓` / 答 `✅ 应答：…` / 取消 `⛔ 用户取消了应答` 进任务时间线（封顶 200 沿用）
- 权限不变：不经 PermissionChecker 放行逻辑，引擎 auto_approve 照旧
- 非目标：任意时刻暂停/恢复、CLI 子进程交互、多人抢答、历史任务补答均不做

## Technical Decisions

**范式：可见性走 DB，唤醒走 Event。** DB（pending_question + waiting）只服务 UI 可见性与留痕；答案向工具的传递只走进程内桥（Event + 答案槽），绝不经 DB 回读。单进程双层线程模型不变（任务层事件循环 asyncio.Task，引擎层 worker 线程同步生成器）。

**状态机与条件清场**
- waiting↔running 翻转只由工具侧发起，一律条件更新（`WHERE status='waiting'`，晚到者自然空操作）
- 终态与孤儿清扫沿任务层/启动层现状写入，不受单写者限制，但须顺手清 pending_question 并注销桥（工具 try/finally 之外的第二道网）

**跨线程桥**
- 模块级注册表 `{task_id→Bridge}` + Lock；Bridge = Event + 答案槽（latch 首写生效，再写 409）+ deadline + abort 标志
- 工具侧次序：注册 → 写 DB → wait（0.5s 分片轮询 abort）→ 取结果 → 注销；端点侧：查表（无桥 409）→ 校验 id → 锁内写槽 → Event.set() + 留痕；cancel/answer 并发时锁内先到者生效

**工具设计**
- `is_read_only()` 返回 False——与 vendor 版相反，正是为借引擎「非只读工具独立成批串行单跑」机制；vendor 版内嵌终端 UI 会挂死 worker 线程，禁止 import 顶替，仅借鉴其 schema 与返回文案
- execute 全程 try/finally 清场（引擎吞工具异常，清场不能依赖异常路径）；退出四路：answered（`User answered:\n{q} => {a}`）/ cancelled（`User cancelled the question.` + is_error）/ 超时（is_error）/ 异常（转 is_error ToolResult 不上抛）
- pending_question.id 每问唯一（uuid），多轮问 = 多次工具调用各新 id

**挂载与接线**
- `agent_sdk.run()` 签名增 `task_id` 与 `interactive`（默认 False）；interactive=True 时工具列表追加该工具，默认 `_system_prompt()` 的工具手册段按 interactive 动态生成（挂了才写用法与「何时该问」）
- interactive=True 的汇点是 `skill_runner.run_prompt`（技能 invoke 与 AI 命令栏共同入口）；scaffold_builder 保持 False
- run() 的超时/异常路径在 `engine.abort()` 后必须调 `askuser.abort_bridge(task_id)`：置 abort 标志 + Event.set()，有界等待后放弃（abort 只关 HTTP 流，叫不醒 Event.wait）
- 工具构造参数 `(task_id, log_cb, deadline_at)`；deadline = skill_run_timeout 剩余额度（run() 构造时注入）

**数据契约与落点**
- `pending_question = {id, questions: [{question, options: [{label, description}], multiSelect}], asked_at: iso-UTC}`；answer 恒字符串（multiSelect 由前端拼接）
- 新文件 `app/services/askuser.py`、`tests/test_askuser_flow.py`（直跑断言脚本风格，不跑真 LLM）；改动 agent_sdk.py / skill_runner.py / api.py / tasks.py / main.py / models.py（状态注释）；无新增依赖

## Cross-Story Dependencies

- 1.1 是地基：1.2 消费其工具与 abort_bridge，1.3 消费其注册表与 latch，1.4 端到端验证 1.1-1.3 全部退出路径
- 1.2 须回归现有 `tests/test_agent_sdk_boundaries.py`
- Epic 2（面板表单、冒烟技能）消费本 Epic 的 API 与状态机；本 Epic 不动前端

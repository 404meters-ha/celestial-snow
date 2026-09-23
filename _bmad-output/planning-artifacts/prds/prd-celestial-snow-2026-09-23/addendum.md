# Addendum · 技能交互 L2（下游架构输入）

> PRD 不承载的实现机理与方案取舍，全部在这里。架构文档（`bmad-architecture`）应从这里取材。

## 1. 方案取舍记录

### 等待态表达：waiting 状态 vs payload 标记（已选前者）

- **已选：新增 `waiting` 状态**（用户 2026-09-23 拍板，兑现 2026-09-14 共识「孤儿清扫兼顾 paused」口径）
- 否决方案：status 保持 running + `payload.pending_question` 标记。改动面更小（轮询/孤儿清扫不动），但列表状态不直观、语义失真（任务明明在等人）
- **waiting 状态的全部变更点**（架构与故事须逐点覆盖）：
  1. `app/models.py` TaskRun.status 注释与写入点
  2. 前端 `focusTask` 1s 定向轮询的 `status !== 'running'` 停轮条件 → waiting 须继续轮询
  3. 前端 `pollOnce` 3s 通用扫描的接管过滤 → 含 waiting
  4. `main.py::_fail_orphan_tasks` 扫描条件 → `status in (running, waiting)`
  5. 前端状态 tag 映射（running/success/failed 三色之外补 waiting）
  6. elapsed 计时显示冻结逻辑

### 不复用 vendor `AskUserQuestionTool`

`vendor/cc-mini/src/tools/ask_user.py` 的 execute 内嵌 prompt_toolkit 终端 Application 同步阻塞等键盘——无头 worker 线程会永久挂起。仅借鉴其 **input_schema 与返回格式**（`"User answered:\nq => a"`、取消 `is_error=True`），交互层平台自写。

### 不做独立等待超时

等待与执行共享 `skill_run_timeout`（3600s）单一额度：语义简单（任务总预算不变）、配置面不增。代价是长任务+多轮问可能吃满——单人自用可接受，面板显示剩余预算缓解。

## 2. 机制草图（架构细化起点）

```
worker 线程                                事件循环
──────────                                ────────
Engine.submit() 生成器
  └ tool_call: AskUserQuestion
      execute():
        1. 问题写入任务 payload.pending_question
           （经线程安全回调：loop.call_soon_threadsafe
            或直接 DB 写 + 状态置 waiting）
        2. threading.Event.wait(带剩余额度上限)   ←─ POST /api/tasks/{id}/answer
        3a. set → 取出 answers → ToolResult            │ 读 payload 问题的校验和
            （任务回 running，Event 置位）              │ Event.set()
        3b. 超时 → ToolResult(is_error=                │
            "等待用户应答超时")                          └ cancel:true → answers=None set
        3c. abort 标志 → 同上收尾
```

关键点：

- **桥**：`threading.Event` + 共享答案槽（工具实例属性或任务级 dict）；答案由 answer 端点写入后 `set()`。Event.wait 必须带 deadline（取 skill_run_timeout 剩余），外层 `asyncio.wait_for` 超时 `engine.abort()` 时工具也要能退（abort 关 HTTP 流但叫不醒 Event.wait——需工具自己轮询 abort 标志或依赖 deadline）
- **单问串行**：工具 `is_read_only()` 返回 False → 引擎不与其它工具并批、单独执行 → 任一时刻至多一个 pending_question，答案端点无并发歧义
- **状态回写**：waiting/running 翻转发生在工具 execute 内（worker 线程）——DB 写走现有同步 helper 可直接用（SQLAlchemy session 在线程内的用法沿用 `_append_log` 模式）；答案写入在事件循环侧
- **多轮问**：一问一答循环天然支持（工具可多次调用）；pending_question 在恢复时清除，答案进 logs 留痕
- **409 语义**：非 waiting 态收到 answer → 409；waiting 态但问题校验和不匹配（已被下一问覆盖等）→ 409

## 3. answer 端点契约草案

```
POST /api/tasks/{id}/answer
  {"answers": [{"question": str, "answer": str}]}   # 多问题一并提交；自由输入即 answer 文本
  {"cancel": true}                                    # 取消：Event set 且 answers=None
→ 200 {"ok": true} | 409 任务不在等待态 | 404 无此任务
```

返回给模型的 ToolResult 文案对齐 vendor：`User answered:\n{question} => {answer}`；取消为 `User cancelled the question.` + `is_error=True`。

## 4. 前端落点（勘察坐标）

- 面板模板 `App.vue:29-56`；`panelTask.status` 驱动 tag 与 foot；waiting 分支在 `.task-logs` 上方插问题表单卡片
- `focusTask`（:1172-1196）`status !== 'running'` → `!['running','waiting'].includes(status)`
- `pollOnce`（:1981-2009）接管过滤加 waiting；skillTasks 表 tag 映射同步
- elapsed（:1093-1099）以 tick 驱动——waiting 冻结=记一个 waiting_since，恢复时把区间从起点扣掉
- api.js 增 `answerTask(id, body)`

## 5. 测试落点

- 沿用 `tests/test_agent_sdk_boundaries.py` 的「项目根直跑断言脚本」风格，新增 `tests/test_askuser_flow.py`：Mock LLM 不必真跑——直接实例化工具与 Event 桥单测（提问→payload 写入→answer→ToolResult；取消；超时 deadline；409 分支）
- 全链 E2E 用冒烟技能真跑（`ask` 技能：先问一个偏好再按答案产出不同结果，验证答案真的回了模型）

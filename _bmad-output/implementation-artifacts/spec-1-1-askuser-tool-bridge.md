---
title: 'Story 1.1: AskUser 工具与问题桥（askuser.py 核心）'
type: 'feature'
created: 2026-09-23
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'a8e67168afb069b206cacfe13de7cc733976d88f'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 无头技能/AI 命令执行中遇到只有用户能定的分叉时只能硬编码或停摆；引擎侧没有「问出去、等答案、带答案回来」的机制。
**Approach:** 新建 `app/services/askuser.py`：`AskUserQuestionTool`（继承 cc-mini Tool）+ `Bridge`（Event + 答案槽 latch + deadline + abort 标志）+ 模块级注册表 + 条件清场 helper + `abort_bridge`。本故事只做引擎侧核心与单测；run() 接线归 1.2、应答端点归 1.3、前端归 Epic 2。

## Boundaries & Constraints

**Always:**
- 桥语义（脊柱 AD-2）：注册 → 写 DB（pending_question + status=waiting + `❓` 留痕）→ `Event.wait` 0.5s 分片轮询 abort → 取结果 → 注销；答案槽 **latch 首写生效**（已有结果再投递被拒，供端点转 409）；cancel/answer 锁内先到者生效
- 退出四路文案逐字（AD-5）：answered=`User answered:\n{q} => {a}`；cancelled=`User cancelled the question.`（is_error）；timed-out=超时说明（is_error）；异常转 is_error ToolResult **不上抛**（引擎 `_execute_tool` 吞异常会跳过清场，故清场必须 try/finally）
- 清场一律**条件更新**（`WHERE id=? AND status='waiting'`）且回 running、清 pending_question、注销桥（AD-1：终态不可被工具覆盖，条件更新天然空操作）
- schema 对齐 vendor：1-4 问 × 每问 2-4 选项（label/description）+ multiSelect（默认 false）；`is_read_only()` 返回 **False**（借引擎非只读单跑保证同任务串行单问）
- DB 写走 `tasks.py` 同款模式：每调用独立 `SessionLocal()`、JSON 列整体重赋值、留痕封顶 200
- 工具构造参数 `(task_id, log_cb, deadline_at)`（deadline 由 1.2 的 run() 注入）

**Never:**
- 不 import vendor 的 `AskUserQuestionTool`（prompt_toolkit TTY 阻塞，无头线程永久挂起）——只参照其 schema 与文案
- 不改 `agent_sdk.py` / `api.py` / `tasks.py` / `main.py`（后续故事范围）
- 不做 HTTP 端点、不做前端
- 参数不合法（问数/选项数越界、空 questions）不得进入等待：直接返回参数错误 is_error，不写 DB、不注册

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| answered | execute 等待中，另线程投递 answers 并 set | ToolResult `User answered:\n{q} => {a}`；DB 行 waiting→running（条件清场）、pending_question 写入后清除；桥注销 | N/A |
| cancelled | 投递 cancel | `User cancelled the question.` is_error=True；清场同上 | N/A |
| timed-out | deadline_at 到期 | 超时说明 is_error；清场 | N/A |
| 内部异常 | execute 中 raise | finally 清场完成；异常转 is_error ToolResult 返回 | 不上抛 |
| latch 二写 | 桥已有结果再投递 | 投递被拒（返回「已被消费」标志） | 调用方（1.3 端点）据此转 409 |
| abort | `abort_bridge(task_id)` 置位+set | 阻塞中的 wait 在一个分片周期（≤0.5s）内退出，走 timed-out 文案并清场 | N/A |
| 参数不合法 | questions 空/超 4/选项数越界 | 不等待不写 DB，直接参数错误 is_error | N/A |

</frozen-after-approval>

## Code Map

- `app/services/askuser.py` -- 新建，本故事主体
- `app/tasks.py:16-40` -- `_sync_update`/`_append_log` 模式（每调用独立 SessionLocal；JSON 列整体重赋值；封顶 200）——清场与留痕 helper 仿此
- `app/models.py:167-184` -- TaskRun（status String/progress Text/logs JSON/payload JSON）
- `vendor/cc-mini/src/core/tool.py:7-41` -- Tool ABC 与 ToolResult（`from core.tool import Tool, ToolResult`，与 agent_sdk 同 import 根）
- `vendor/cc-mini/src/tools/ask_user.py:354-421` -- schema 与返回文案参照（禁 import 顶替，其 is_read_only=True 与本工具相反）
- `vendor/cc-mini/src/core/engine.py:404-426` -- 非只读工具独立成批单跑机制（is_read_only=False 的依据）
- `app/config.py:37` -- `skill_run_timeout=3600`（deadline 最终来源，1.2 注入）
- `app/db.py` -- `SessionLocal`
- `tests/test_agent_sdk_boundaries.py` -- 「项目根直跑断言脚本」风格模板（check() 收集 PASS/FAIL、exit 1 on fail、utf-8 重配）

## Tasks & Acceptance

**Execution:**
- [x] `app/services/askuser.py` -- 实现 Bridge/注册表/Lock、AskUserQuestionTool、条件清场 helper、abort_bridge -- 故事主体
- [x] `tests/test_askuser_flow.py` -- 桥六情形直跑断言（answered/cancelled/timed-out/异常清场/latch 拒二写/abort 分片退出）+ 参数不合法 -- I/O 矩阵全覆盖

**Acceptance Criteria:**
- Given 工具以 (task_id, log_cb, deadline_at) 构造、DB 有该任务行，When execute 被调且另线程投递答案并 Event.set()，Then ToolResult 文案逐字符合四路之一，任务行经历 running→waiting→running，pending_question 按 `{"id","questions":[{"question","options":[{"label","description"}],"multiSelect"}],"asked_at"}` 形状写入并在退出时清除，时间线含 `❓` 留痕
- Given 桥已 latch，When 再次投递，Then 投递被拒且首次结果不被覆盖
- Given abort_bridge(task_id) 被调，When 工具阻塞在 wait，Then ≤1s 内退出且清场完成（无 waiting 残留、桥已注销）
- Given execute 内部抛异常，Then 返回 is_error ToolResult、清场完成、异常不上抛

## Implementation Notes

- `Bridge.wait()` 单出口：Event 置位或 deadline 到期都归结为「返回 `self._result`」——deliver 置位得结果、abort 置位得 None（走 timed-out 文案），到期与投递竞态时已 latch 的结果优先（先到者生效）
- `_mark_waiting` 也做成条件更新（`WHERE status='running'`，落空即抛错走异常路）：堵住「run() 超时先写 failed、工具稍后才把 waiting 盖上去」的窄竞态——终态两端都不可被工具覆盖
- 清场 `_restore_running`：条件 UPDATE（waiting→running）赢得翻转后，同事务内读行、pop pending_question、整体重赋值 payload——原子且 JSON 列不留脏键
- `❓` 留痕走构造注入的 log_cb（生产接线即 TaskManager 的 `_append_log`，封顶 200 随之继承）；answer/cancel 的 `✅/⛔` 留痕留给 1.3 端点侧，避免双写
- 注册表暴露 `get_bridge(task_id)` 只读访问器：abort_bridge / 测试 / 1.3 端点（无桥→409）共用；注册时同 task_id 已有桥直接返回 is_error（引擎非只读单跑之外的双保险）
- 超时文案定为 `User did not answer in time; the question timed out.`（spec 只约束「超时说明」，其余三路逐字对齐 vendor）
- 测试的 log_cb 接真实 `tasks._append_log`，「时间线含 ❓」是对 DB 行 logs 的断言而非仅回调捕获

## Spec Change Log

（评审回路时由 step-04 填）

## Review Triage Log

- high — 桥退出后未关闭：abort()/超时后 deliver() 仍 True（盲审1+2、边界3 同源）——`_abort` 只写不读属死状态，评审实测 abort 后 deliver 返回 True；1.3 端点将 200 但答案无人消费 → patch（关闭语义）
- high — 注册表双保险整段删除测试仍全绿，删后二问会静默毁掉首问 DB 状态（验证缺口3，追链证实：B 桥 finally 命中 waiting 条件清场销毁 pending，A 桥失联）→ patch（补测）
- medium — `_mark_waiting` 终态闸（WHERE running + rowcount=0 抛错）零测试驱动（验证缺口1，删除演示 50 项全绿）→ patch（补测）
- medium — `_restore_running` 的 AD-1 条件清场空操作分支零覆盖（验证缺口2，同上演示）→ patch（补测）
- medium — finally 内 `_restore_running` 抛错会跳过 `_unregister` 且异常逃出 execute，违反「不上抛」Always（边界1，结构性证实）→ patch（嵌套 try/finally）
- medium — deadline_at=None 默认无限等待，退出全押 1.2 每路径调 abort_bridge（盲审10、边界2）→ patch（必传参数）
- medium — deadline 已过仍写 DB：幻影问题+重试连打 ❓ 闪跳 waiting/running（盲审4，读码证实无预检）→ patch（_mark_waiting 前预检）
- medium — 校验器与 schema 不一致：description 未校验、重复 question 文本使 by_question 折叠同答案（盲审5、边界6/7，读码证实）→ patch（校验补齐）
- medium — 终态行残留 pending_question：条件清场落空时键不清理，UI 僵尸问题（边界5、验证缺口 Other1）→ patch（落空时仍 pop 键、不动 status）
- low — 超时/中止收场零留痕，复盘无法区分答/取消/超时（盲审3；✅/⛔ 已归 1.3 端点，超时无人记）→ patch（超时分支补一行 ⏳）
- low — 缺 get_activity_description，1.2 接线后时间线退化为 JSON 摘要（盲审9，同 app 其余工具惯例）→ patch
- low — `_utcnow` 为项目内第三份同义 helper（盲审11）→ patch（复用既有）
- low — models.py:178 status 注释未含 waiting（盲审6、验证缺口 Other2）→ patch（一行）
- low — 乱序 answers 文案未测、双保险/终态两闸未测（盲审7，与验证缺口1-3 重叠）→ patch（随补测）
- low — 时序敏感断言 flake：timed-out deadline 0.3s、abort elapsed ≤1.0 含 DB commit（盲审12、边界8）→ patch（放宽阈值）
- low-reject(部分) — 测试直写生产库（盲审8）：临时库方案超出直接修正（config 缓存/engine 导入序）且日常影响低 → 仅采纳直接部分（启动时预清 asktest-%），临时库方案拒绝
- low-reject — deliver kind 非法值格式化为 answered（边界4）：仅内部字面量调用方可触发，一行守卫随关闭语义顺手加，不单列

## Design Notes

- 测试建临时 TaskRun 行（id 前缀 `asktest-`，finally 清理），避免污染真实任务列表；断言直接读行状态与 payload
- 条件更新用 `sqlalchemy.update(TaskRun).where(TaskRun.id==tid, TaskRun.status=="waiting").values(...)`
- Bridge 槽存元组 `(kind, answers)`：kind ∈ {answered, cancelled}；投递函数返回 bool（False=已 latch）
- 分片 0.5s；deadline_at 为绝对时刻（time.monotonic 基）
- 注册表 `_REGISTRY: dict[str, Bridge]` + `threading.Lock`；abort_bridge 对无桥 task_id 静默返回（幂等）

## Verification

**Commands:**
- `.venv/Scripts/python.exe tests/test_askuser_flow.py` -- expected: 全 PASS、exit 0
- `.venv/Scripts/python.exe tests/test_agent_sdk_boundaries.py` -- expected: 回归全 PASS（无既有行为破坏）

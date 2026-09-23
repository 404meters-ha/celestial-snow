---
title: 'Story 1.3: 应答端点与状态机收尾'
type: 'feature'
created: 2026-09-23
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'cf4f3a553903ba590a8b0c564c6157c192ab58dd'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 任务已能进入 waiting 暴露问题（1.1/1.2），但用户没有通道作答；任务层终态与重启孤儿清扫也不认识 waiting 态，僵尸问题无兜底。
**Approach:** api.py 增 `POST /api/tasks/{id}/answer`（只投递+留痕，不碰 status——翻转是工具侧单写者职责）；tasks.py 终态写入与 main.py 孤儿清扫顺手清 pending_question 并幂等注销桥，清扫范围扩 waiting。

## Boundaries & Constraints

**Always:**
- 端点契约（脊柱 AD-2/AD-6）：请求 `{id: str, answers: [{question, answer:str}]}` 或 `{id: str, cancel: true}`；200 `{"ok": true}`；404 无任务；409 四分支（非 waiting / 无桥 / id 不匹配 / 已 latch 重复投递）；400 形状不合法（缺 id、answers 与 cancel 两无或两有、answers 空或元素非 {question, answer:str} 形状）
- 检查次序：404 → 409 非 waiting → 409 无桥（get_bridge）→ 409 id 不匹配（payload.pending_question.id 对比）→ deliver → False 则 409
- 端点**不写 status、不清 pending_question**（AD-1 单写者是工具 execute 的条件清场）；只经 `_append_log` 留痕：answer → `✅ 应答：{q => a 摘要（截断）}`，cancel → `⛔ 用户取消了应答`
- tasks.py 终态写入（成功/失败/取消三路 `_append_log(status=...)` 处）顺手清 pending_question（status 无关的键清理）并惰性导入 askuser 调 `abort_bridge`（幂等注销，**不得模块级 import**——askuser 已 `from ..tasks import _now`，顶置会成环）
- main.py `_fail_orphan_tasks` 扫描扩 `status in (running, waiting)`，置 failed 同时清 payload.pending_question（逐行读改写，启动时一次性、量小）
- models.py 状态注释已含 waiting（1.1 已做，本故事零改动）

**Never:**
- 不改 `askuser.py` / `agent_sdk.py` / `skill_runner.py` / 前端（前端是 Epic 2）
- 不做答案经 DB 回传给工具的任何路径（只走桥）
- 不给端点加鉴权/多用户语义（单人平台现状）
- 不为 waiting 单独设超时（吃 skill_run_timeout）

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| answer 投递 | 行 waiting、桥在、id 匹配 | 200 ok:true；时间线 `✅ 应答：…`；工具线程收到 answered ToolResult（文案含所选答案） | N/A |
| cancel 投递 | 同上但 cancel:true | 200；`⛔ 用户取消了应答`；工具线程收到取消 is_error | N/A |
| 404 | task_id 无此行 | 404 | N/A |
| 409 非 waiting | 行 running/success/failed | 409「任务不在等待应答状态」 | N/A |
| 409 无桥 | 行 waiting 但 get_bridge 为 None（重启僵尸/竞态窗口） | 409 | N/A |
| 409 id 不匹配 | req.id ≠ pending_question.id | 409 | N/A |
| 409 重复投递 | 桥已 latch（首次 deliver 成功后）再投 | 409 | N/A |
| 400 形状 | 缺 id / answers 与 cancel 两无或两有 / answers 空 / 元素缺 answer 字符串 | 400 | N/A |
| 终态清场 | 任务层写 success/failed 时行上有残留 pq | pq 被清、status 照终态、桥幂等注销 | N/A |
| 孤儿清扫 | 重启时行 running 或 waiting（带 pq） | 置 failed「服务重启，任务中断」且 pq 清 | N/A |

</frozen-after-approval>

## Code Map

- `app/api.py:294-305` -- tasks 三端点区（GET /tasks、GET /tasks/{id}）——answer 端点紧随其后落位；Pydantic 请求模型惯例见 `ContributeRequest`（:257）与 HTTPException 中文文案（:284-289）
- `app/tasks.py:26-40, 70-89` -- `_append_log`（留痕+extra 落 status）与 `_runner` 三路终态写入——终态清场挂点
- `app/main.py:69-84` -- `_fail_orphan_tasks` 启动清扫（现只扫 running 的 bulk update）——扩 waiting + 清 pq
- `app/services/askuser.py` -- `get_bridge`（无桥判定）/`Bridge.deliver`（False=已 latch）/`abort_bridge`（幂等）——端点与终态清场消费；注意其 `from ..tasks import _now` 的 import 方向
- `app/models.py:167-184` -- TaskRun（status/payload）——注释已含 waiting，零改动
- `tests/test_askuser_flow.py` -- 直跑断言风格与 `_new_task`/`_row` 手法（asktest- 前缀 + finally 清理）——新测试沿用
- `app/db.py` -- SessionLocal

## Tasks & Acceptance

**Execution:**
- [x] `app/api.py` -- `AnswerRequest` 模型 + `POST /tasks/{task_id}/answer` 端点（检查次序与留痕按 Always） -- 应答通道
- [x] `app/tasks.py` -- 终态三路顺手清 pq + 惰性导入 abort_bridge -- 第二道兜底网
- [x] `app/main.py` -- 孤儿清扫扩 waiting 并清 pq -- 重启归宿
- [x] `tests/test_answer_endpoint.py` -- 直跑断言：端点十情形（answer/cancel 全链含工具线程收结果、404/409×4/400、终态清场、孤儿清扫），asyncio.run 直调端点函数捕获 HTTPException -- I/O 矩阵全覆盖

**Acceptance Criteria:**
- Given 行 waiting、桥在、id 匹配，When POST answer（answers 完整），Then 200、时间线含 `✅ 应答：`、并行工具线程的 ToolResult 文案含所选答案且行被条件清场回 running
- Given 同状态但 cancel:true，Then 200、`⛔` 留痕、工具线程收到 `User cancelled the question.` is_error
- Given 非 waiting / 无桥 / id 不匹配 / 重复投递四种状态，When POST answer，Then 各自 409（文案可区分）
- Given 行不存在，Then 404；Given 缺 id / answers 与 cancel 两无或两有 / answers 空，Then 400
- Given 任务层终态写入时行残留 pq，Then pq 被清且桥注销（幂等，无异常外抛）
- Given 重启清扫遇 running 与 waiting 各一行（均带 pq），Then 两行均 failed「服务重启，任务中断」且 pq 清

## Implementation Notes

- `AnswerRequest` 三字段全 `typing.Any`：类型与形状校验（缺 id / id 非 str / cancel 非 bool / answers 非 list / 两无两有（`cancel:false` 视同缺省，两种组合均 400）/ 空 / 超 4 条 / 元素非 `{question:str 非空, answer:str 非空}`）全部在端点内手工抛 400——严格 Pydantic 模型会把 id 传 int 等变成 FastAPI 的 422，不符契约
- 400 形状检查先于 404（请求解析先于资源查找）；测试里 400 用例均布置在真实 waiting 行上，与 404 分支不重叠，两种次序解释下行为一致
- 评审回路加固（13 项）：get_bridge 后新鲜复读行复核 status+pq.id（TOCTOU：读行与取桥间问题轮替时旧 id 不得 latch 进新桥）；deliver 后留痕 try/except（投递是事实源，留痕失败不 500）；端点改 sync def（同步 SQLite I/O 走线程池）；409 文案细分（无等待问题 / 轮替 / 已应答已关闭已过期）；tasks.py 惰性 import 进 try；main.py 孤儿清扫逐行容错（损坏 payload 行 print+跳过不拖垮启动）；测试补路由级 TestClient（不带 context manager 免 lifespan）、TOCTOU 轮替、已过期桥、cancel:false 两用例与孤儿清扫真实任务守卫（SKIP 注记）
- `tasks.py` 新增 `_clear_pending_question(task_id)`：status 无关 pop pq（JSON 列整体重赋值），自身 DB 异常吞掉（兜底网不拖垮终态写入），`finally` 里惰性 `from .services import askuser` 调 `abort_bridge`（幂等）；挂在 `_runner` 三路 `_append_log(status=...)` 之后
- `main.py` 孤儿清扫从 bulk update 改 `query(status.in_(running, waiting))` + 逐行读改写（要读 payload 才能清 JSON 键）；不注销桥——新进程注册表天然为空；终态行（success/failed）不在清扫范围
- 端点测试 44 断言全过：`anstest-` 前缀行 + `manager.submit` 产出的 probe 行（uuid id，`PROBE_TIDS` 收集）首尾各清一次；409 重复投递用「手工注册无主桥」确定性命中 latch 分支（真工具线程会被首投唤醒清场，抢走二投的 409 归因）
- 验证：test_answer_endpoint 44/0、test_askuser_flow 85/0、test_run_wiring 45/0、test_agent_sdk_boundaries 17/0，全部 exit 0；另 TestClient HTTP 层冒烟（路由注册、404/400 真回包、lifespan 含新清扫正常启动）

## Spec Change Log

（评审回路时由 step-04 填）

## Review Triage Log

- high — `cancel:false` 被当取消执行：`has_cancel = req.cancel is not None`，JS 端展开状态对象常发 false（盲审1、边界1）——用户明确答了「不取消」问题却被取消 → patch（is True 判定 + 补 400 用例）
- high — TOCTOU：行读与 get_bridge 之间问题轮替（超时→重问），旧行校验 q1 的 id 却把答案 latch 进 q2 的桥（盲审2、边界3）→ patch（取桥后新鲜重读行复核 status+pq.id 再 deliver）
- high — 路由级契约零执行：44 断言全部绕过 FastAPI 路由/解析层，删掉 @router.post 装饰器测试照 44/0（验证缺口主发现，删除演示证实）→ patch（TestClient 场景：200/400 非 422/404 过真路由；不带 context manager 免 lifespan）
- high — 孤儿清扫测试跑真 `_fail_orphan_tasks` 打全库：服务器在跑真实任务时执行测试即误杀（盲审6、边界7、验证缺口 Other1）→ patch（场景前置守卫：存在非 anstest 的 running/waiting 行则 SKIP 注记）
- medium — 类型不匹配走 FastAPI 422 而非契约 400（边界2）→ patch（模型字段 typing.Any + 端点内 isinstance 全量手工校验）
- medium — deliver 成功后留痕失败变 500，重试又撞 409「不能重复投递」（盲审3）→ patch（留痕 try/except 吸收，投递是事实源）
- medium — async def 端点在事件循环上做同步 SQLite I/O，15s busy 锁可拖垮全部并发请求（边界4）→ patch（改 sync def 走线程池，deliver/_append_log 线程安全）
- medium — answers 无 ≤4 上限、空串过 isinstance 产出空行（盲审4）→ patch（上限 4 + 非空串）
- medium — `_clear_pending_question` 的惰性 import 在 try 外，import 失败会让 _runner 在终态写入后再抛（边界5）→ patch（挪进 try）
- medium — 孤儿清扫遇 payload 损坏行会整体回滚、lifespan 启动即死（边界6）→ patch（逐行 try/except continue）
- low — 409 文案混淆：waiting 无 pq 报「id 不匹配」；deliver False 混 latch/关闭/过期（盲审5）→ patch（分列文案）
- low — 已过期桥的 409 分支未在端点层测过（盲审7）→ patch（staged 过期 deadline 桥）
- low — 清扫无条件重赋 payload + 重复实现 _now（盲审8）→ patch（pop 守卫 + 复用 _now）
- low — PROBE_TIDS 预清理死代码（盲审9）→ patch（删除）
- defer — CLAUDE.md 关键 API 速览补 answer 端点（盲审11、验证缺口 Other2）：改 agent-context 文件按规则 defer，Epic 1 收尾（1.4）或 CLAUDE.md 例行更新时并入
- false — 「400/404 检查次序与冻结 spec 不符」（盲审10）：冻结区只钉了 404→409 链，400 位置未钉；Implementation Notes 已记录决策且验证缺口层独立复核后主动撤下此项

## Design Notes

- 端点直读 DB 行做 404/waiting/id 检查（`SessionLocal` + `s.get(TaskRun, task_id)`），桥经 `askuser.get_bridge`；不经理由：manager.get 返回视图 dict 也行，但直读可在一个 session 内取 status+payload，少一次转换
- `✅ 应答：` 摘要格式：`{question} => {answer}` 逐条 join 后截 120 字符（与 ❓ preview 口径一致）
- tasks.py 的 pq 清理 helper 可复用 askuser `_restore_running` 之外的独立小函数（DB-only，status 无关 pop），避免与 askuser 循环 import；abort_bridge 在 helper 内 `from .services import askuser` 惰性导入
- 孤儿清扫从 bulk update 改 select+逐行 update：启动一次性、量小，需读 payload 才能清 pq
- 端点测试直调 `api.answer_task(...)`（async）+ `asyncio.run`，HTTPException 用 `except HTTPException as e: e.status_code` 断言——不起服务，符合直跑约定

## Verification

**Commands:**
- `.venv/Scripts/python.exe tests/test_answer_endpoint.py` -- expected: 全 PASS、exit 0
- `.venv/Scripts/python.exe tests/test_askuser_flow.py` -- expected: 85 全 PASS（askuser 未动）
- `.venv/Scripts/python.exe tests/test_run_wiring.py` -- expected: 45 全 PASS（agent_sdk/skill_runner 未动）
- `.venv/Scripts/python.exe tests/test_agent_sdk_boundaries.py` -- expected: 17 全 PASS

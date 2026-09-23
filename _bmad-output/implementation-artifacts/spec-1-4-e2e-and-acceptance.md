---
title: 'Story 1.4: 全链验证与边界测试（V1 收口）'
type: 'feature'
created: 2026-09-23
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '4564caa959fac32136787d7309f21a3a97357000'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Epic 1 的引擎侧、接线、端点已分故事交付并有单元级断言，但「一句话 → 提问 → 应答 → 答案真回到模型 → 完成」从未在真实 LLM 上走过一遍；curl 消费者文档也缺 answer 端点。
**Approach:** 新增 `scripts/askuser_e2e.py`：起 8101 测试实例驱动真 LLM 全链（含前置守卫防误杀在跑任务），产物归档 `_bmad-output/implementation-artifacts/e2e-askuser/`；CLAUDE.md 关键 API 速览补 answer 端点（折入 1.3 的 defer 项）。

## Boundaries & Constraints

**Always:**
- NFR4 四情形（非 waiting 应答 409 / 取消路径 / 超时回收 / 重启孤儿）已有单元断言——本故事**不重复造**，spec 只登记映射：409 与取消→tests/test_answer_endpoint.py（60 断言）、超时与异常清场→tests/test_askuser_flow.py（85 断言）、重启孤儿→test_answer_endpoint.py 孤儿清扫场景
- E2E 全链断言：任务时间线出现 `❓ 等待用户应答` → 端点留痕 `✅ 应答：` → 终态 success；`payload.result.result` 文本包含用户所选答案内容；全程 curl 可复现（脚本内用 httpx 对 8101 实例，等价 curl）
- **前置守卫**：起测试实例前查 celestial.db，存在 running/waiting 行（说明 8100 生产实例可能在跑任务，8101 启动会孤儿清扫误杀）即中止并打印原因——不静默
- 测试实例用 8101（沿用脚手架周期惯例），结束杀进程；E2E 产生的任务行留在库中作留痕（带可识别 type）
- prompt 工程：让模型「先调 AskUserQuestion 问一个二选一偏好（选项猫/狗），拿到答案后在总结中明确写出我的选择」——问题与答案都是脚本里预定义的，断言确定性
- CLAUDE.md 补录（折入 defer）：速览任务段增 `POST /api/tasks/{id}/answer` 一行（{id, answers}|{id, cancel:true}；404/409×5/400；waiting 态有效）——只增不删既有行

**Never:**
- 不改 app/ 生产代码（本故事只加脚本与文档；若 E2E 暴露产品缺陷即停下报告，不顺手修——那是新故事）
- 不做前端（Epic 2）
- E2E 不硬编码端口占用（8101 被占时清晰报错退出）

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 全链应答 | 实例起、agent 提问、脚本 answer 猫 | success；result 含「猫」；时间线 ❓→✅→完成 | N/A |
| 全链取消 | 同上但 cancel:true | 任务正常收尾（success/failed 均可，模型自行总结）；时间线 ❓→⛔ | N/A |
| 守卫触发 | 库中有 running/waiting 行 | 脚本中止并打印原因，不起实例 | exit 非 0 带说明 |
| 端口被占 | 8101 已有监听 | 清晰报错退出 | exit 非 0 |
| LLM 不可用 | llm_configured 为假或端点失联 | 任务 failed；脚本报告失败原因 | exit 非 0 |

</frozen-after-approval>

## Code Map

- `scripts/scaffold_dryrun.py` -- 项目既有「脚本驱动 + 日志留痕」E2E 惯例模板
- `.research-s8/e2e.py` -- 上周期 8101 测试实例驱动的先例（起服/轮询/断言/清理的手法）
- `app/api.py` -- POST /api/agent/run（:892 一带，interactive 链路汇点）、POST /api/tasks/{id}/answer（1.3 交付）、GET /api/tasks/{id}
- `app/config.py:37-39` -- skill_run_timeout / platform_api_base（E2E 超时预算与实例地址）
- `tests/test_answer_endpoint.py` / `tests/test_askuser_flow.py` -- NFR4 映射登记对象
- `CLAUDE.md` -- 关键 API 速览段（任务相关行在 GET /api/tasks 附近）
- `main.py` -- uvicorn main:app；lifespan 含孤儿清扫（守卫存在的原因）

## Tasks & Acceptance

**Execution:**
- [x] `scripts/askuser_e2e.py` -- 守卫 → 起 8101 实例 → agent/run 触发提问 → answer（猫）→ 断言 success+result 含答案 → cancel 复链 → 归档日志与任务 JSON 到 `_bmad-output/implementation-artifacts/e2e-askuser/` -- 真实全链验收
- [x] `CLAUDE.md` -- 速览任务段补 answer 端点一行（折入 1.3 defer） -- curl 消费者文档
- [x] 运行 E2E 并归档产物；spec 登记 NFR4→既有测试映射 -- V1 收口证据

**Acceptance Criteria:**
- Given 本机 LLM 已配置且库无在跑任务，When 执行 askuser_e2e.py，Then exit 0：应答链 success 且 result 文本含预定义答案、时间线三段齐全；取消链任务正常收尾且时间线含 ⛔；日志与任务 JSON 已归档
- Given 库中存在 running/waiting 行，When 执行脚本，Then 起服前中止并打印原因（exit 非 0）
- Given 三套既有测试，Then 全部维持绿（本故事不动 app/ 代码）
- Given CLAUDE.md，Then 速览含 answer 端点行且无既有行被删改

## Implementation Notes

（实现期追加）

- 交付物：`scripts/askuser_e2e.py`（驱动脚本）+ CLAUDE.md 速览在 `GET /api/tasks` 行后补 `POST /api/tasks/{id}/answer` 一行（1.3 defer 折入，git diff 确认只增不删）；**未动 app/ 生产代码**。
- NFR4 → 既有测试映射（登记，未重复造）：
  - 非 waiting 应答 409 + 取消路径 → `tests/test_answer_endpoint.py`（60 断言，本故事复验全绿）
  - 超时回收 + 异常清场 + latch 拒二写/abort 分片退出 → `tests/test_askuser_flow.py`（85 断言，本故事复验全绿）
  - 重启孤儿清扫（running+waiting 残留行标失败、清 pending_question）→ `tests/test_answer_endpoint.py` 孤儿清扫场景
  - run() 接线挂载矩阵（interactive/task_id）→ `tests/test_run_wiring.py`（45 断言，本故事复验全绿）
- E2E 实跑证据（2026-09-23 16:34，真 LLM，8101 测试实例）：
  - 应答链 task `9c2052dbd1ba`：running→waiting(6s)→POST answer（「猫 (Recommended)」）→success(11s)；`payload.result.result` = 「总结：你选择了猫——你更喜欢猫。」（含预定义答案，证明答案真回到了模型）；时间线 ❓→✅→完成 三段顺序齐全
  - 取消链 task `be30494a8846`：waiting(5s)→POST cancel→success(12s)（模型自行总结收尾）；时间线含 ❓ 与 ⛔
  - 11/11 断言通过，exit 0；产物归档 `e2e-askuser/`：`e2e.log`（含每步 curl 回放行，全程可复制回放）、`server-8101.log`、`task-answer.json`、`task-cancel.json`
  - 任务行留库作留痕（type=agent，payload.prompt 带【AskUser-E2E】前缀可识别）
- 守卫路径实测（均未起实例）：插探针 running 行 → 起服前中止并打印行明细，exit 2（探针即删）；8101 被占 → 清晰报错，exit 2。
- 驱动细节（Design Notes 之上的补强）：模型重复提问时按同策略续投（上限 5 次防问询风暴）；轮询 GET 静默、仅状态迁移落日志；实例子进程注入 `PLATFORM_API_BASE=http://127.0.0.1:8101` 自闭环；uvicorn 输出归档 `server-8101.log`；guard 异常路径修复为干净 exit 2（不带 traceback）。

### 评审回路修订（review round 1，2026-09-23）

- 13 项评审意见全部落地：guard_db 改只读 URI 打开 + `sqlite3.Error` 分流（仅 no-such-table 放行，locked/corrupt/缺文件 Abort）；投递仅 2xx 计数 + 已成功 pq id 不重发 + 预算触顶留痕；链中 httpx 传输异常转 Abort 进归档日志；杀实例前 sqlite 直写清残留 running/waiting 行；注入 SCHED_HOUR 避开每日刷新 cron；每链收尾补 wire 级负路径三发（终态再答 409 / answers+cancel 同传 400 / 乱 task_id 404）；新增超时链（短命实例 SKILL_RUN_TIMEOUT=45，不投递等过期，断言 ⏳ + 终态）；首个 pq 到手即验形状；取消链补「⛔ 后无 ❓」顺序断言；归档改 `run-{时间戳}/` 子目录 + `latest/` 副本；kill 后 wait 兜底不裸崩、归档 open 防 PermissionError；断言名改「投递成功（2xx）」口径；CLAUDE.md 409×5 更正为 409×6（补「问题已轮替」）。
- **E2E 暴露产品缺陷（按 Never 不顺手修，登记待新故事）**：任务时间线 `_append_log` 是整列读-改-写，多线程并发追加会丢行——端点留痕线程 vs 被唤醒的工具线程（⛔/✅ 可能丢）、工具超时留痕 vs run() 超时/任务层收尾追加（⏳ 可能丢）。三次实跑：run-20260923-165305 丢 ⛔（25/27）、run-20260923-165640 丢 ⏳（26/27，settled DB 行证实从未写入）、run-20260923-165946 全过（27/27，latest/）。断言保持严格以持续暴露该缺陷；修复前 E2E 偶发 exit 1 属预期。

## Spec Change Log

（评审回路时由 step-04 填）

## Review Triage Log

- high — guard_db 过捕 OperationalError：locked/corrupt 库被误报「未初始化」静默放行（8101 清扫误杀生产任务——守卫的存在目的失效）；corrupt 的 DatabaseError 是 OperationalError 父类根本没接住，违背「干净 exit 2」承诺（盲审2、边界1、验证缺口 Other1）→ patch（sqlite3.Error 分流：no such table 才放行，其余 Abort）
- medium — guard 的 sqlite3.connect 无中生有创建空 celestial.db 且 Abort 后残留（盲审3）→ patch（只读 URI `mode=ro` 打开，缺文件成为可探测条件；与上一条同函数一并修）
- medium — 409 重投吃 MAX_DELIVERIES 预算 + 0.5s 清场窗内同 pq 重发（盲审4、边界3）→ patch（记已投 pq id 跳过重发；仅 2xx 计数；触顶时落一行日志）
- medium — 链中 httpx 传输异常在 harness 外裸崩、进不了归档日志（盲审5、边界5）→ patch（轮询请求包 try/except httpx.HTTPError → Abort）
- medium — 300s 链超时杀实例留孤儿 running 行，下次 E2E 守卫自锁 exit 2（边界4）→ patch（stop_server 前把库中残留 running/waiting 行标 failed——守卫保证起点无外人行，残留皆本脚本所致）
- low — 实例存活窗口撞上 APScheduler 每日刷新 cron（盲审9）→ patch（子进程注入无害 SCHED_HOUR，同 PLATFORM_API_BASE 手法）
- low — 零 wire 级负路径断言：文档宣告的 400/404/409 契约从未在活实例上打过（盲审6；TestClient 已覆盖 ASGI 层，此为 socket 层增量）→ patch（每链后补 3 发：终态任务→409、双字段→400、乱 id→404）
- low — 超时第三退出路缺席 E2E（NFR4 四情形唯一没有真链验证的）（盲审7）→ patch（注入小 SKILL_RUN_TIMEOUT 起服，问题过期→断言 ⏳ 留痕+任务达终态）
- low — 畸形 pq 静默空转到 300s、pq 形状（UI 依赖）从未断言（盲审8）→ patch（首个 pq 到手即 check 形状四键）
- low — 归档 mode="w" 重跑即毁前次验收证据（盲审10）→ patch（按时间戳子目录归档）
- low — 取消链未验证「取消终结了问询循环」：⛔ 后不得再出现 ❓（盲审11）→ patch（顺序断言）
- low — CLAUDE.md 新行写 409×5 漏了轮替分支（实际 ×6）（盲审1）——修的是本故事自己新增的行 → patch（改 409×6 补轮替）
- low — proc.wait(10) 的 TimeoutExpired 会在 finally 里裸崩（边界6）→ patch（try/except pass）
- low — 归档日志被并发 E2E 持有时 PermissionError 裸崩（边界8）→ patch（open 包 try/except → 干净 exit 2）
- low — 断言名「完成应答投递」言过其实（只证尝试不证成功）（验证缺口 Other2）→ patch（随仅-2xx-计数一并正名）
- low-reject — 守卫与 8101 启动清扫之间的 ms 级竞态（边界2）：脚本层无法预防（清扫在 /api/config 可响应前已完成），事后检测不能挽回；单人平台+毫秒窗，接受
- false — 「spec 与证据目录未入 change set」（盲审12）：step-05 收尾提交 _bmad-output 是既定流程（1.1-1.3 同款）

## Design Notes

- 起服：`subprocess.Popen([venv_python, "-m", "uvicorn", "main:app", "--port", "8101"])`，轮询 `/api/config` 200 即就绪；结束 terminate+wait
- 提问触发 prompt（确定性）：「请先调用 AskUserQuestion 问我一个问题：'你更喜欢猫还是狗？'，选项：猫（推荐）/狗。拿到我的回答后，用一句话总结并明确写出我选择了什么。」——答案预定义「猫」，断言 result 含「猫」
- 轮询节奏：GET /api/tasks/{id} 每 1s、上限 300s（真 LLM 一问一答 + 总结，2-4 轮内完成）
- 取消链可以第二个 agent 任务复用同一 prompt，waiting 后 POST {id, cancel:true}
- 归档产物：`e2e.log`（脚本全输出）、`task-answer.json` / `task-cancel.json`（最终任务视图含 logs）

## Verification

**Commands:**
- `.venv/Scripts/python.exe scripts/askuser_e2e.py` -- expected: exit 0、归档目录出现日志与任务 JSON
- `.venv/Scripts/python.exe tests/test_askuser_flow.py` -- expected: 85 全 PASS
- `.venv/Scripts/python.exe tests/test_answer_endpoint.py` -- expected: 60 全 PASS
- `.venv/Scripts/python.exe tests/test_run_wiring.py` -- expected: 45 全 PASS

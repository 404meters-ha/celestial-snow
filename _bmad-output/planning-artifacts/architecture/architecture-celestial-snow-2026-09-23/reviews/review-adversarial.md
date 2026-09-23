# 对抗性架构评审 · ARCHITECTURE-SPINE（技能交互 L2）

- 评审对象：`../ARCHITECTURE-SPINE.md`（2026-09-23 draft）；PRD 与 addendum 同期版
- 方法：构造「下一层单元」对——后端故事（工具+桥+端点）与前端故事（面板+轮询）、工具故事与任务故事——各自**字面遵守每一条 AD**，检验结合处是否仍崩。所有场景对照现有代码验证（`app/tasks.py`、`app/services/agent_sdk.py`、`app/services/skill_runner.py`、`app/services/scaffold_builder.py`、`app/api.py`、`main.py`、`vendor/cc-mini/src/core/engine.py`、`frontend/src/App.vue`、`frontend/src/api.js`）。
- 裁决：**脊柱的范式与分工成立，但按现稿切故事会在四个高危点产出不兼容/自毁系统：应答契约缺 id 字段（V1）、超时路径终态回卷成僵尸（V2）、abort 与 task_id 无接线方案（V3）、异常路径无清场（V4）。V1/V3 属「照着写不出来」，V2/V4 属「写出来会自毁」，均须修稿后再切故事。**

严重度：🔴 高（阻塞或自毁）· 🟡 中（功能性缺陷）· ⚪ 低（措辞/边界）。

---

## 🔴 V1 应答契约自相矛盾：请求体没有问题 id，AD-2/AD-3 的 id 校验无法实现

**两故事冲突。** 后端故事按 AD-2 实现「查注册表（无桥→409）→ 校验问题 id → 不匹配 409」；前端故事按 AD-6 实现提交：请求形状只有 `{"answers": [{"question","answer"}]}` 或 `{"cancel": true}`——**id 字段在请求契约里不存在**（AD-3 明说「answer 请求须携带并匹配」，AD-6 的形状却没定义它放哪；addendum §3 草案同样没有）。

**崩法。**
- a：后端强制要求 id → 前端所有提交 422/400，全链不通；
- b：后端退化为按 `answers[].question` 文本匹配 → 多轮问里模型复用同一句问文（「还有其他偏好吗？」类追问很常见）时，**q1 的迟到/重复提交被接线到 q2 的桥上**，模型拿到上一轮的旧答案；`{"cancel": true}` 更是无从区分取消的是哪一问——这正是 AD-3 声称「Prevents 答案归属歧义」要防的事故。

**涉及 AD：** AD-6 × AD-2/AD-3。

**修法（收紧 AD-6）：** 请求顶层增加 `"id"`（uuid，取自 `pending_question.id`），answers 与 cancel 两种body都携带；顺带写死 multiSelect 前端拼接符（建议 `", "`，对齐 vendor `ask_user.py` 的 join 口径），消除另一处自由度。

---

## 🔴 V2 超时路径写序颠倒：任务层先写 failed、工具清场后写 running → 永久 running 僵尸

**场景（对照代码逐步验证）。** 等待用户占满 `skill_run_timeout`：

1. 事件循环：`asyncio.wait_for` 到点 → `engine.abort()` → `raise RuntimeError`（`app/services/agent_sdk.py:466-470`）；
2. `tasks.py::_runner` 捕获 → `_append_log(status="failed", finished_at=…)`（`app/tasks.py:84-86`）——**终态此刻已落库**；
3. 数百毫秒后，worker 线程里的工具按 AD-5「三路全部先清场（回 running、清 pending_question、注销桥）」走 timed-out 收尾，用 tasks.py 同步 helper 模式**无条件**回写 `status="running"`；
4. 终态行：`status=running` + `finished_at` 已设 + 无任何人在跟踪 → 面板 1s 轮询永不停止、任务列表永久「运行中」，直到下次服务重启被孤儿清扫收尸。

**两故事冲突。** 工具故事忠实执行 AD-5 的清场三步；任务故事按 AD-1「任务终态收尾沿任务层现状」保持 `_runner` 原样。AD-1 的担保「若终态时仍 waiting 由工具退出路径**先行**清场」在 `wait_for` 语义下**不可能成立**：终态写在事件循环即时发生，清场在 worker 线程延后发生，次序天然颠倒，而两侧都没有等待对方的机制。

**涉及 AD：** AD-1 / AD-5 × 任务层现状（`tasks.py::_runner` + `agent_sdk.run` 超时路径）。

**修法（新 AD 或收紧 AD-1，建议双保险）：**
1. 清场写条件化：回 running / 清 pq 一律走 `UPDATE … WHERE status='waiting'` 守卫式更新（`_sync_update` 现为无条件 setattr，需加条件变体）；
2. 任务层终态写兜底：`_runner` 落 success/failed 时同时清 `pending_question` 并注销/取消桥（终态即清场），使「工具清晚了」不再是事故。

---

## 🔴 V3 abort 传导与 task_id 注入没有接线方案，Structural Seed 的「其余不动」恰好禁掉了必需改动

**场景 a（abort 叫不醒工具）。** `engine.abort()` 只置 `engine._aborted` 并关闭 HTTP 流（`vendor/cc-mini/src/core/engine.py:170-181`）；生成器此刻阻塞在 `_execute_tool → 工具.execute → Event.wait` 里，「下一个事件点」要等工具返回才出现（`agent_sdk.py:469` 的注释「worker 线程下一个事件点自行退出」对 WebFetch 成立，对可等 3600s 的 AskUser 不成立）。AD-5 说工具「0.5s 分片轮询 abort 标志」——**这个标志是谁的没写**：桥的 cancelled 标志只有 answer 端点会置；`engine._aborted` 是引擎私有属性，而工具实例在 `Engine(...)` 构造参数里先于引擎创建（`agent_sdk.py:400-410`），拿不到引擎引用。两故事各自合规（工具故事轮询桥标志；run() 故事超时调 `engine.abort()`），合起来工具**退不出来**——worker 线程挂到 deadline 为止，`to_thread` 线程被占最长一小时，且与 V2 复合成僵尸。

**场景 b（task_id 无处取）。** AD-2 注册表键是 task_id、工具写 DB（pq/waiting/❓留痕）也要 task_id；但 `run()` 签名没有 task_id——`skill_runner.run_prompt` 收了 task_id 却没往下传（`app/services/skill_runner.py:121`）。Structural Seed 明文「`agent_sdk.py` run() 增 interactive 参数（工具组装处，**其余不动**）」。两个开发者被迫各自发明：一个改 `run()` 签名（字面违反「其余不动」），一个上 contextvar/模块级全局（工具执行点跨线程——引擎顺序路径在 worker 线程内联执行，contextvar 靠 `to_thread` 的上下文快照才碰巧可用，脆弱且无人能从稿子里推出这个结论）。**桥的注册键都无法可靠构造，这是「照着写不出来」级别的洞。**

**涉及 AD：** AD-5 × AD-2 × Structural Seed（agent_sdk.py 条目）。

**修法（新 AD「接线契约」）：** `run()` 签名增加 `task_id`（三个调用点 `skill_runner.run_prompt`/scaffold_builder/warmup 同步）；交互运行构造工具时注入 `(task_id, 剩余额度闭包, abort 信号)`；`run()` 的超时与轮次中止路径在 `engine.abort()` 之外**同时置桥的 cancel 标志**（持引用或按 task_id 查注册表）。Structural Seed 的「其余不动」改为「工具组装、task_id 线程化、abort 接线三处改动，余不动」。

---

## 🔴 V4 工具异常路径不在「三路退出」枚举里 → waiting+桥 残留成无人消费的永久僵尸

**场景。** 工具 `execute()` 在「注册 → 写 DB(waiting)」之后、「wait」之前抛异常（SQLite busy 锁冲突在多线程写场景下真实存在：事件循环 `_append_log` 与 worker 线程 DB 写并发；或任意实现 bug）。`engine._execute_tool` 捕获**一切**异常转成 ToolResult(is_error) 继续跑（`engine.py:474-475`）；引擎照常完成、任务层写 success——但 DB 行停在 waiting+pending_question、桥还挂在注册表里。AD-5 只枚举 answered/cancelled/timed-out 三路清场，异常是第四路，没人管。

**后果放大。** 此后 answer 端点查桥命中、id 匹配 → 写槽 `set()`、返回 200、留 ✅ 痕——**没有消费者**，任务永远 waiting（直到重启）。注意 AD-1 的不变量「waiting ⇔ pq 非空 ⇔ 桥已注册」字面全部成立，恰是盲区所在：桥在、等的人不在。

**两故事冲突。** 工具故事按 AD-5 三路实现清场（正常路径全覆盖）；任务故事按 AD-1 相信「waiting 进出只有工具管」而不做终态兜底。

**涉及 AD：** AD-5（三路枚举不全）× AD-1（唯一写者无兜底）。

**修法（收紧 AD-5 + V2 修法第 2 条）：** 清场必须 `try/finally`（异常路径同样回 running/清 pq/注销桥）；叠加任务层终态兜底清场，双保险。

---

## 🟡 V5 「后写覆盖槽」× 乐观清表单 × 1s 轮询重渲染 → 重复/空提交覆盖首答

**场景。** 用户提交答案（200，乐观清表单）。下一次 1s 定向轮询落在工具翻转 status **之前**（wait 0.5s 切片 + DB 往返，窗口客观存在）：`syncLogs` 整体替换 `panelTask`（`App.vue:1158-1168`），waiting+pending_question 仍在 → 问题表单**重新渲染出来**。用户再提交一次（或双击的第二击落在重渲染的空/默认表单上）：第二份答案按 AD-2「后写覆盖槽」写进槽——此刻工具可能尚未读走首答 → 模型拿到空/错答案。AD-2 说「无副作用」不实：在「首答未被消费」时，覆盖本身就是副作用。

**两故事冲突。** 前端故事按 AD-7「乐观清 + 继续轮询」；桥故事按 AD-2「后写覆盖」。

**涉及 AD：** AD-2（幂等语义写反了）× AD-7（乐观更新+轮询重渲染）。

**修法：** 收紧 AD-2：槽**首写生效**（桥置 answered 后，同 id 再提交直接 200 幂等返回、不覆盖不重置 Event）；AD-7 补「已答抑制：waiting 但本地已提交时表单置灰，而非从 pending_question 重渲染」。

---

## 🟡 V6 并发交互任务的 waiting 问题被单面板单焦点藏死

**场景。** 技能任务 A waiting（面板 1s 定向轮询中）。用户在 AI 命令栏再发一条命令 B → `focusTask(B)`：`stopPolling()` 杀掉 A 的 1s 轮询、面板整体切给 B（`App.vue:1172-1196`，无抢占保护）。B 运行期间 A 的问题**没有任何 UI 入口**；若 B 也发起提问，`pollOnce` 的 `find()` 只接管列表里第一条 running/waiting（`App.vue:1984`）。AD-3 只串行化「**同一任务内**」的问题，跨任务并发 waiting 平台本来就允许（连续提交两个技能即可触发）。被藏的 A 最终 3600s 超时失败，用户一脸懵。

**涉及 AD：** AD-3（单问串行的范围只写单任务）× AD-7（接管规则只管单焦点面板）。

**修法：** 二选一必须写下来：新 AD（waiting 任务计数徽标 + 面板可切换，`focusTask` 抢占时保底提示「还有 N 个任务在等你回答」）；或进 Deferred 明示「并发交互任务的问题可能互相遮挡，单人平台接受」。现状是空白，两个前端故事会做出相反取舍。

---

## 🟡 V7 六触点清单漏了三个状态判断点

**场景。** 前端故事严格按 AD-7 的触点①-⑥改完后：

- 任务从 waiting 直接结束时（答完即 success），`pollOnce` 收尾逻辑 `if (panelTask.value?.status === 'running') await syncLogs(…)`（`App.vue:1992`）**不命中 waiting** → 面板永远停在 waiting 旧态、无终态 foot、无最后一行日志——触点②只改了接管过滤，没收尾补拉；
- 面板 foot 渲染条件 `v-if="panelTask.status !== 'running'"`（`App.vue:48`）在 waiting 期就显示终态 foot（关闭/查看结果按钮）；
- `api.js` 的 `apiPost` 错误不透出 status 码（`frontend/src/api.js:13-24`，有 detail 时 status 丢失）——AD-7「409 时重拉任务态」无法程序化分支，须改 `apiPost` 或约定错误结构，同样不在清单。

**涉及 AD：** AD-7 触点清单不完备。

**修法：** 清单补 ⑦ `pollOnce` 终态补拉条件改 `['running','waiting'].includes(…)`；⑧ 面板 foot/`已运行|耗时` 标签的 waiting 分支；⑨ `apiPost` 错误携带 status（或 `answerTask` 专用错误通道）。

---

## ⚪ V8 AD-1「唯一写者」字面与孤儿清扫/任务层终态写构成三写方

AD-1 说进出 waiting 唯一写方是工具；AD-7③ 要求孤儿清扫把 waiting 置 failed（`main.py::_fail_orphan_tasks` 现只扫 running，待扩）；任务层 `_runner` 的终态写也可能落在 waiting 行上（V2 场景）。重启期无竞态（旧进程已死、清扫在 lifespan 启动段早于任何请求，`main.py:53-55`），但**字面矛盾会诱导后端故事给 status 写路径加「仅工具可改」守卫，反过来挡掉清扫的 UPDATE**。

**修法（收紧 AD-1 措辞）：**「**运行期**的 waiting↔running 翻转唯一写方是工具；重启孤儿清扫与任务层终态收尾是显式例外，且终态写须条件化（见 V2）」。

---

## ⚪ V9 AD-2 正文与时序图的注册/写库顺序相反，409 权威源未定

正文：「注册 → 写 DB → wait」；时序图：先写 DB 再注册。两个顺序各留一个窗口：前者「桥在、DB 非 waiting」——PRD FR-3 的 status-first 409 与 AD-2 的 bridge-first 409 在此窗口**给出不同答案**（同一请求一个实现 409 一个实现 200）；后者「DB waiting、桥不在 → 409」而前端表单已渲染——用户答题吃 409，AD-7 只说「重拉任务态」，重拉后表单恢复已填还是清空未定义。不变量三段（waiting ⇔ pq ⇔ 桥）是两次独立写，不可能原子。

**修法（收紧 AD-2）：** 固定顺序（建议：注册 → 写 DB → wait）；写明端点权威判定「桥存在**且**桥内 id == DB `pending_question.id`，任何不一致 409」；写明注册与写库间的毫秒级窗口由「前端 409 → 重拉 → 有限次重试」兜住。

---

## ⚪ V10 deadline 与 Event.set 同时到达、cancel 与 answer 并发的优先级未定义

工具从 wait 醒来必须裁决「答案是真是超时/取消」。桥故事「先置槽后 set」+ 端点故事「先留 ✅ 痕再返回 200」的合规组合下，可能出现：端点已留 ✅ 应答、用户看到 200，而工具走 timed-out 路径丢弃答案——**留痕说谎**，复盘时时间线与模型实际收到的不一致。

**修法（收紧 AD-5）：** 醒来后先查槽：非空 → answered 优先于超时/取消；槽空且 deadline 到 → timed-out。cancel 与 answer 并发时先到者生效，桥 latched 后另一操作返回 409（与 V5 的 latch 修法同一条）。

---

## ⚪ V11 PlatformAPI 可代答任意 waiting 任务

交互运行的模型自身挂着 PlatformAPI（可 POST 任意 `/api/` 路径，`agent_sdk.py:301-318`），无人值守的 scaffold_build 也挂着它：可以对并发 waiting 的任务 POST answer，注入用户从未给出的答案。单用户平台属自伤型风险，但 AD-4 挂载矩阵只管 AskUser 工具自身的挂载，未对「谁能调 answer 端点」设防。

**修法：** 进 Deferred 写明「接受」，或 answer 端点校验来源（PlatformAPI 注入 `X-Task-Id` 头，端点拒绝应答自己/须同人）。二选一落纸即可。

---

## 已验证不成立的攻击（记录备查）

- **「引擎并批导致同任务并发双问」**：不成立。`is_read_only()=False` 使非只读工具独立成批串行（`engine.py:337-345`），`[WebFetch, AskUser]` 混排也逐批顺序执行；AD-3 借力成立。
- **「重启孤儿清扫与运行中清场竞态」**：不成立。清扫在 lifespan 启动段同步完成、早于任何请求，旧进程已死（dev 模式 `--reload` 双进程重叠属开发环境，不计入）。
- **「answer 端点 ✅ 留痕会覆盖 status」**：不成立。`_append_log` 不带 status 字段时不动 status（`tasks.py:26-40`）。
- **「waiting 行污染 `_task_view` 消费者」**：不成立。`_task_view` 原样透传 status/payload（`tasks.py:43-52`），列表/详情后端无需改；风险全在前端映射（已入触点④与 V7）。
- **「技能正文调 AskUserQuestion 但该运行未挂工具会崩」**：不成立。未挂载即不进 `to_api_schema()`，模型无从调用；scaffold 运行遇到指示提问的技能正文只会降级为文本自答/默认值（`engine.py:442` Unknown tool 路径根本到不了）。挂载矩阵 AD-4 本身无洞。

## 修法汇总

| 洞 | 严重度 | 处置 | 落点 |
|---|---|---|---|
| V1 请求缺 id | 🔴 | 收紧 AD-6 | 请求顶层加 `id`；写死 multiSelect 拼接符 |
| V2 终态回卷僵尸 | 🔴 | 新增守卫式清场 + 终态兜底（改 AD-1/AD-5） | `UPDATE…WHERE status='waiting'`；`_runner` 终态清 pq/注销桥 |
| V3 abort/task_id 接线缺失 | 🔴 | 新 AD「接线契约」 | `run()` 增 task_id；超时/中止同时 cancel 桥；修 Structural Seed「其余不动」 |
| V4 异常路径无清场 | 🔴 | 收紧 AD-5 | 清场 try/finally + 终态兜底 |
| V5 覆盖槽毁首答 | 🟡 | 收紧 AD-2 + AD-7 | 槽首写生效（latch）；已答抑制重渲染 |
| V6 并发 waiting 藏死 | 🟡 | 新 AD 或 Deferred（必须落纸） | waiting 徽标/面板切换，或明示接受 |
| V7 触点清单缺项 | 🟡 | 收紧 AD-7 | 补⑦pollOnce 收尾⑧foot/耗时标签⑨apiPost 错误带 status |
| V8 唯一写者措辞 | ⚪ | 收紧 AD-1 | 限定「运行期」，清扫/终态列显式例外 |
| V9 顺序与 409 权威 | ⚪ | 收紧 AD-2 | 固定注册→写库→wait；桥+DB 双确认 |
| V10 醒来裁决优先级 | ⚪ | 收紧 AD-5 | 槽非空优先；cancel/answer 先到生效 |
| V11 PlatformAPI 代答 | ⚪ | Deferred 或端点校验 | 写明取舍即可 |

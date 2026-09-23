---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
inputDocuments:
  - prds/prd-celestial-snow-2026-09-23/prd.md
  - architecture/architecture-celestial-snow-2026-09-23/ARCHITECTURE-SPINE.md
  - prds/prd-celestial-snow-2026-09-23/addendum.md
---

# celestial-snow（技能交互 L2）- Epic Breakdown

## Overview

本文档将「技能交互 L2：AskUser 工具 + 任务暂停/恢复」的 PRD 需求与架构脊柱决策分解为可实施的故事。无 UX 设计契约（前端改动限于既有任务面板内分支，沿用现有视觉体系）。

## Requirements Inventory

### Functional Requirements

FR1: AskUserQuestion 工具（引擎侧）——平台在 agent_sdk 自写，挂载于技能 invoke 与 AI 命令栏两类运行（scaffold_build 不挂）；输入 schema 对齐 vendor 惯例（1-4 问 × 2-4 选项 + 自由输入 + multiSelect）；同批单问（非只读→引擎单跑）；工具描述与系统提示词写明「何时该问」
FR2: 任务暂停（waiting 态）——状态机扩为 running|waiting|success|failed；问题明细挂 payload.pending_question；时间线留痕；等待期吃 skill_run_timeout 同一额度；服务重启孤儿清扫覆盖 waiting；elapsed 展示冻结
FR3: 应答 API——POST /api/tasks/{id}/answer（{id, answers} 多问题一并提交 / {id, cancel:true}）；任务非 waiting 报 409；应答后回 running 并留痕
FR4: 前端应答 UI——任务面板 waiting 态内嵌问题表单（单选/多选/自由输入）；1s 定向轮询与 3s 通用扫描视 waiting 为仍在跟踪；页面刷新后可重新接管；表单与日志区共存
FR5: L3 审批门模式——两选项问题（允许继续/取消）的文档化用法，不建独立机制；前端轻量强调；写入技能作者指南（不可逆动作前必须问）
FR6: 冒烟技能——新增演示技能（如 ask）跑通「执行中问→面板答→带答案续跑」全链，兼做 L3 模式示例；ping 保持零交互不动

### NonFunctional Requirements

NFR1: 线程安全——提问/应答横跨 worker 线程与事件循环，遵循现有 JSON 列整体重赋值惯例
NFR2: 留痕——问题与答案均进任务时间线（封顶 200 沿用）
NFR3: 权限不变——AskUser 不经 PermissionChecker 放行逻辑（引擎 auto_approve 照旧）
NFR4: 边界测试沿用「项目根直跑断言脚本」风格，覆盖非 waiting 应答 409、取消路径、超时回收、重启孤儿

### Additional Requirements

（来自架构脊柱 ARCHITECTURE-SPINE.md，AD 编号即脊柱稳定 ID）

- ARCH-AD1: 状态机 4 值；waiting↔running 翻转只由工具侧发起且一律条件更新（WHERE status='waiting'）；终态/孤儿清扫沿任务层现状但顺手清 pending_question 并注销桥（双保险）
- ARCH-AD2: 模块级桥注册表 {task_id→Bridge}+Lock；Bridge=Event+答案槽（latch 首写生效，再写 409）+deadline+abort 标志；注册先于写 DB；端点查表投递（无桥→409）；cancel/answer 锁内先到者生效
- ARCH-AD3: 工具 is_read_only()=False（与 vendor 相反，禁止 import vendor 工具顶替）；pending_question.id 每问唯一，answer 顶层带 id
- ARCH-AD4: run() 增 task_id/interactive 参数；interactive=True 汇点=skill_runner.run_prompt（两入口共用）；scaffold_builder 保持 False；默认 _system_prompt 工具手册段按 interactive 动态生成
- ARCH-AD5: execute 全程 try/finally 清场；退出四路（answered/cancelled/timed-out/异常），异常转 is_error ToolResult 不上抛；deadline=skill_run_timeout 剩余额度注入
- ARCH-AD6: 数据契约——pending_question={id,questions:[{question,options:[{label,description}],multiSelect}],asked_at}；请求 {id,answers:[{question,answer:str}]}|{id,cancel:true}；logs 前缀 ❓/✅/⛔
- ARCH-AD7: 前端触点清单 8 点为验收项——focusTask 停轮条件、pollOnce 接管过滤、pollOnce 终态补拉条件、task-foot v-if、_fail_orphan_tasks 扫 running+waiting、状态 tag 映射与 elapsed 标签、models.py 状态注释、apiPost 错误透出 status
- ARCH-AD8: run() 接线契约——超时/异常路径在 engine.abort() 后调 askuser.abort_bridge(task_id)（置 abort 标志+Event.set，有界等待后放弃）；工具构造 (task_id, log_cb, deadline_at)
- ARCH-范式: 可见性走 DB、唤醒走 Event——答案传递只走桥，绝不经 DB 回读
- ARCH-种子: 新文件 app/services/askuser.py、tests/test_askuser_flow.py、.claude/skills/ask/SKILL.md；改动 agent_sdk/skill_runner/api/tasks/main/App.vue/api.js；无新增依赖

### UX Design Requirements

（无 UX 设计契约——前端改动限于既有任务面板内分支）

### FR Coverage Map

FR1: Epic 1 - AskUserQuestion 工具（挂载/schema/单问串行/何时该问）
FR2: Epic 1 - waiting 态与条件清场、超时额度、孤儿清扫
FR3: Epic 1 - 应答端点（answers/cancel/409/latch）
FR4: Epic 2 - 面板问题表单 + 轮询接管（触点 8 点）
FR5: Epic 2 - 审批门两选项模式与技能作者指南
FR6: Epic 2 - 冒烟技能 ask 全链验证

## Epic List

### Epic 1: 执行中可问可答（引擎与 API 级闭环）
用户提交的技能 / AI 命令在执行中途可以向用户发起提问：任务转入 waiting 并暴露问题，用户经 API 应答或取消，任务带着答案恢复运行；超时与服务重启有明确归宿。curl 即可完成全链操作。
**FRs covered:** FR1, FR2, FR3（含 NFR1-4 与 ARCH-AD1/2/3/4/5/6/8）

### Epic 2: 面板问答与审批门（web 端体验）
用户在 web 任务面板直接看到问题表单并作答（无需 curl）：waiting 视觉区分、刷新接管、乐观更新；审批门作为两选项模式落地（含技能作者指南）；冒烟技能跑通全链并作为 L3 示例。
**FRs covered:** FR4, FR5, FR6（含 ARCH-AD7 触点 8 点）

依赖：Epic 2 建立在 Epic 1 之上（消费其 API 与状态机）；Epic 1 独立可用。

## Epic 1: 执行中可问可答（引擎与 API 级闭环）

用户提交的技能 / AI 命令在执行中途可以向用户发起提问：任务转入 waiting 并暴露问题，用户经 API 应答或取消，任务带着答案恢复运行；超时与服务重启有明确归宿。

**FRs covered:** FR1, FR2, FR3（NFR1-4、ARCH-AD1/2/3/4/5/6/8）

### Story 1.1: AskUser 工具与问题桥（askuser.py 核心）

As a 技能作者,
I want 我的技能在无头执行中能调用 AskUserQuestion 工具发起提问,
So that 依赖用户偏好的分叉不再只能硬编码默认值或直接停摆。

范围：`app/services/askuser.py` 新建——`AskUserQuestionTool`（schema 对齐 vendor：1-4 问 × 2-4 选项 + multiSelect；`is_read_only()=False`）、`Bridge`（Event + 答案槽 latch + deadline + abort 标志）、模块级注册表 `{task_id→Bridge}+Lock`、条件清场 helper（`WHERE status='waiting'`）、`abort_bridge(task_id)`；退出四路文案（AD-5）；`execute` 全程 try/finally。

**Acceptance Criteria:**

**Given** 桥单测环境（直跑断言脚本，不跑真 LLM，工具构造带 task_id/log_cb/deadline_at）
**When** 实例化工具并调用 execute，另一线程对桥投递 answers 后 Event.set()
**Then** ToolResult 返回 `User answered:\n{q} => {a}` 格式文案，任务行已按 AD-6 形状写入 pending_question 且 status=waiting、时间线含 `❓` 留痕，退出后条件清场回 running 并注销桥
**And** cancel 投递返回 `User cancelled the question.` 且 is_error=True；deadline 到期返回超时 is_error；execute 内部抛异常时 finally 仍完成清场且异常转为 is_error ToolResult；同一桥二次投递（latch 后）被拒；abort_bridge 置位后阻塞中的 wait 在一个分片周期内退出

### Story 1.2: run() 接线与挂载矩阵

As a 平台开发者,
I want agent_sdk.run() 支持 task_id 与 interactive 参数并在超时路径唤醒阻塞的工具,
So that 技能与 AI 命令的运行能挂上 AskUser 工具，而 scaffold 等无人值守任务不受影响、超时不留悬挂线程。

范围：`agent_sdk.run()` 签名增 `task_id`/`interactive`；interactive 时工具列表追加 `AskUserQuestionTool(task_id, log_cb, deadline_at)`；默认 `_system_prompt()` 工具手册段按 interactive 动态生成（含「何时该问」约束）；`skill_runner.run_prompt` 补传 task_id 并传 interactive=True（技能 invoke 与 AI 命令栏两汇点共用）；`run()` 超时/异常路径在 `engine.abort()` 后调 `askuser.abort_bridge`（有界等待后放弃）；scaffold_builder 不改（默认 False）。

**Acceptance Criteria:**

**Given** agent_sdk.run 以 interactive=True 且 task_id 非空运行
**When** 检查 Engine 工具列表与系统提示词
**Then** 工具列表含 AskUserQuestion 且提示词含其用法与「何时该问」段；interactive=False（含 scaffold_build 现有调用）时工具不在列表、提示词无该段
**And** run_prompt 发起的技能/AI 命令任务两者都挂工具；模拟超时（极小 timeout）时 abort_bridge 被调用且 worker 线程在有界时间内退出（无永久悬挂）；现有 `tests/test_agent_sdk_boundaries.py` 回归全过

### Story 1.3: 应答端点与状态机收尾

As a 用户,
I want 通过 POST /api/tasks/{id}/answer 应答或取消一个等待中的任务,
So that 任务带着我的答案恢复运行，而非法应答、超时与重启都有明确归宿。

范围：`api.py` 增 `POST /api/tasks/{id}/answer`（`{id, answers}` / `{id, cancel:true}`；404 无任务；409 非 waiting/无桥/id 不匹配/已 latch）；端点只投递+留痕不碰 status（AD-1）；`tasks.py` 终态写入与 `main.py::_fail_orphan_tasks` 顺手清 pending_question、清扫扩 waiting；`models.py` 状态注释更新。

**Acceptance Criteria:**

**Given** 一个 waiting 中的任务（桥已注册，pending_question.id 已知）
**When** POST answer 携带匹配 id 与 answers
**Then** 200 返回，任务回 running（工具侧条件清场），时间线含 `✅ 应答：…`，模型侧收到答案文本继续生成
**And** cancel 返回 200 且模型收到 is_error 取消文案、时间线 `⛔`；非 waiting/无桥/id 不匹配/重复提交均 409；服务重启后原 waiting 任务被清扫为 failed（错误「服务重启，任务中断」）且 pending_question 已清

### Story 1.4: 全链验证与边界测试

As a 平台开发者,
I want 直跑断言脚本与一次真实 LLM 的 curl 全链演示,
So that Epic 1 的四条退出路径与状态机变更点有可复验的证据。

范围：`tests/test_askuser_flow.py`（直跑断言脚本风格）覆盖：投递/取消/超时/异常清场、latch、abort_bridge、409 分支、重启清扫（内存态模拟）；真实 LLM 一次的 curl E2E（临时系统提示词约定「先问一个问题再总结」验证答案真回到模型）。

**Acceptance Criteria:**

**Given** Epic 1.1-1.3 已实现
**When** 执行 `.venv/Scripts/python.exe tests/test_askuser_flow.py`
**Then** 全部断言 PASS（脚本 exit 0），覆盖 NFR4 四情形
**And** curl E2E 留痕：任务日志时间线呈现 ❓→✅→完成，最终 result 文本包含用户答案内容；演示记录归档实现工件目录

## Epic 2: 面板问答与审批门（web 端体验）

用户在 web 任务面板直接看到问题表单并作答（无需 curl）；审批门作为两选项模式落地；冒烟技能跑通全链并作为 L3 示例。

**FRs covered:** FR4, FR5, FR6（ARCH-AD7 触点 8 点）

### Story 2.1: 面板 waiting 表单与轮询接管

As a 用户,
I want 任务等待我应答时在面板里直接看到问题表单并作答,
So that 我不用 curl 就能回答执行中的提问，且刷新页面也不丢跟踪。

范围：`App.vue` 面板 waiting 分支（日志区上方问题表单：单选 radio / multiSelect checkbox / 恒可选的自由输入；提交/取消按钮 + 乐观更新 + 已答抑制重渲染；409 时重拉）；AD-7 触点 8 点：focusTask 停轮条件、pollOnce 接管过滤、pollOnce 终态补拉条件、`.task-foot` v-if、状态 tag 映射（含 skillTasks 表）与 elapsed 标签（waiting 冻结）、`api.js` 增 `answerTask` 且 apiPost 错误透出 status。构建走 `npm run build`。

**Acceptance Criteria:**

**Given** 一个交互任务进入 waiting（面板正被 focusTask 跟踪）
**When** 面板轮询拉到 pending_question
**Then** 日志区上方渲染问题表单（选项+自由输入），状态 tag 显示等待应答、耗时冻结、`.task-foot` 终态区不显示
**And** 提交后表单即清且本地状态置 running（轮询确认前不重渲染复活）；取消同理；页面刷新后 3s 通用扫描接管 waiting 任务并重新显示表单；对已非 waiting 的任务提交答案，前端依 409 重拉任务态不报错弹窗

### Story 2.2: 冒烟技能 ask 与审批门模式

As a 技能作者,
I want 一个演示技能示范「执行中问→作答→按答案续跑」与审批门两选项模式,
So that L2 能力有可复验的样板，后续技能照抄模式即可。

范围：`.claude/skills/ask/SKILL.md` 新建——先问一个偏好（2-3 选项）再按答案产出不同总结；正文含审批门示例段（允许/取消两选项，演示 cancel 路径）与「不可逆动作前必须问」的作者指南；`ping` 不动。

**Acceptance Criteria:**

**Given** web 端技能对话框运行 /ask（无表单参数）
**When** 任务执行到提问点
**Then** 面板出现偏好问题；作答 A/B 两次运行的最终 result 文本可区分（答案真回到模型）
**And** 审批门示例选择「取消」时任务收到取消文案且正常收尾（非 failed）；技能正文含作者指南段落；/ping 行为零改动

### Story 2.3: 全链 E2E 验收

As a 平台开发者,
I want Playwright 页面级 E2E 验证面板问答全链,
So that Epic 2 的交互路径（作答/取消/刷新接管）有自动化证据。

范围：E2E 脚本（对齐项目既有 Playwright 用法）三路径：作答续跑、取消收尾、刷新接管；产物（截图/日志）归档 `_bmad-output/implementation-artifacts`。

**Acceptance Criteria:**

**Given** 服务运行（8100）且 /ask 技能可调用
**When** Playwright 驱动：提交 /ask → 等待表单 → 作答 → 等待完成
**Then** 断言结果文本包含所选答案对应的产出；取消路径任务正常收尾；刷新路径表单重新出现且作答仍成功
**And** E2E 脚本可重复执行；截图与运行日志归档留痕

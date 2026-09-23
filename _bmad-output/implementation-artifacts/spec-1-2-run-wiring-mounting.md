---
title: 'Story 1.2: run() 接线与挂载矩阵'
type: 'feature'
created: 2026-09-23
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '6c01d5c8ecfd876afd7cb93e8add87626bde50ed'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 1.1 交付的 AskUserQuestionTool 与 abort_bridge 没有任何调用方——run() 不接收 task_id、工具列表硬编码五件、系统提示词静态，超时路径叫不醒阻塞中的问询。
**Approach:** `agent_sdk.run()` 增 `task_id`/`interactive` 参数并按 interactive 组装工具与提示词段；`skill_runner.run_prompt` 作为技能 invoke 与 AI 命令栏的共同汇点补传 task_id 并置 interactive=True；超时/中止路径在 `engine.abort()` 后调 `askuser.abort_bridge`。scaffold_builder 零改动（默认 False）。

## Boundaries & Constraints

**Always:**
- 挂载矩阵（脊柱 AD-4）：`run(..., task_id: str | None = None, interactive: bool = False)`；interactive=True 且 task_id 非空时工具列表追加 `AskUserQuestionTool(task_id, log_cb, deadline_at)`，deadline = `time.monotonic() + timeout`（run 起点算，等待与执行共享同一额度）
- 提示词落点（AD-4）：`_system_prompt(interactive: bool = False)`——True 时「环境与能力」的工具清单如实反映新增工具，并增加「向用户提问」段（AskUserQuestion 用法 + 仅限依赖用户偏好/授权分叉、可查资料不问）；False 时与现状逐字不变（scaffold 走覆盖式 system_prompt 本就不受影响）
- 接线契约（AD-8）：run() 的超时路径在 `engine.abort()` 后调 `askuser.abort_bridge(task_id)`（task_id 为空跳过）；轮次上限触发的 `engine.abort()` 处同样补调（防御性，事件流中工具不可能阻塞，但两处中止语义一致）
- `run_prompt` 补传 `task_id=task_id, interactive=True`——技能 invoke 与 AI 命令栏两入口自动获得，api.py 零改动
- interactive=True 但 task_id=None：不挂工具（无任务行可写），不报错

**Never:**
- 不改 `scaffold_builder.py`（默认 False 即不挂，其调用 `run(..., system_prompt=SCAFFOLD_SYSTEM, max_tokens=...)` 语义不变）
- 不改 `api.py` / `tasks.py` / `main.py` / `askuser.py`（1.3 与后续范围；askuser.py 仅作为被调用方）
- 不做端点、不做前端
- 不给 waiting 另设超时（吃 skill_run_timeout 同一额度）

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 交互运行挂载 | run(interactive=True, task_id="t") | 工具列表含 AskUserQuestionTool（task_id/deadline 正确注入），提示词含提问段 | N/A |
| 非交互不挂 | run(interactive=False)（含 scaffold_build 现有调用） | 工具列表与现状一致（五件），默认提示词无提问段 | N/A |
| interactive 无 task_id | run(interactive=True, task_id=None) | 不挂工具、不报错，其余行为不变 | N/A |
| 汇点接线 | run_prompt(prompt, task_id, …) | agent_sdk.run 收到 task_id 与 interactive=True（技能 invoke 与 AI 命令栏共用） | N/A |
| 超时唤醒 | run(..., timeout=极小) | TimeoutError 路径 engine.abort() 后调 abort_bridge(task_id)，RuntimeError 照旧抛出 | 阻塞中的问询一个分片周期内退出 |
| scaffold 回归 | scaffold_builder 调用路径 | 行为零改动 | N/A |

</frozen-after-approval>

## Code Map

- `app/services/agent_sdk.py:382-410` -- run() 签名与 Engine 构造（tools 硬编码五件 L401、`system_prompt or _system_prompt()` L402）——本故事主改点
- `app/services/agent_sdk.py:321-360` -- `_system_prompt()` 静态实现，「环境与能力」段 L328-330 列工具清单——改签名加 interactive 段
- `app/services/agent_sdk.py:465-470` -- 超时路径（`engine.abort()` + raise RuntimeError）——补 abort_bridge
- `app/services/agent_sdk.py:453-455` -- 轮次上限 abort（_drive 内 usage 分支）——防御性补调
- `app/services/skill_runner.py:105-121` -- `run_prompt(prompt, task_id, progress, …)`：L121 调 `agent_sdk.run` 丢弃 task_id——补传并置 interactive=True
- `app/services/scaffold_builder.py:279-286` -- 直调 run()（自带 system_prompt/max_tokens）——不改，验证不受影响
- `app/services/askuser.py` -- 1.1 交付的 AskUserQuestionTool(task_id, log_cb, deadline_at) 与 abort_bridge(task_id)（幂等）——仅消费
- `app/config.py:37` -- skill_run_timeout=3600 → run(timeout) → deadline
- `tests/test_agent_sdk_boundaries.py` -- 回归基准（17 断言）
- `tests/test_askuser_flow.py` -- 直跑断言脚本风格模板（85 断言）

## Tasks & Acceptance

**Execution:**
- [x] `app/services/agent_sdk.py` -- run() 增 task_id/interactive；抽出工具组装（如 `_build_tools(...)` 便于测试直查）；`_system_prompt(interactive)` 动态段；超时与轮次上限路径补 abort_bridge -- 挂载矩阵与接线契约
- [x] `app/services/skill_runner.py` -- run_prompt 补传 task_id + interactive=True -- 两入口共用汇点
- [x] `tests/test_run_wiring.py` -- 直跑断言：挂载正反例与 task_id 缺省、提示词两态、run_prompt 传参（spy agent_sdk.run）、超时路径 abort_bridge 被调（spy + 极小 timeout，LLM 未配置时跳过并注明）、boundaries 回归 -- I/O 矩阵全覆盖

**Acceptance Criteria:**
- Given interactive=True 且 task_id 非空，When 检查工具组装与提示词，Then 工具列表含 AskUserQuestionTool（task_id 与 deadline 注入正确），提示词含「向用户提问」段与「何时该问」约束
- Given interactive=False（含 scaffold_build 调用形状），Then 工具列表为原五件、默认提示词与现状逐字一致
- Given run_prompt 以任意 prompt 调用，Then agent_sdk.run 收到 task_id 与 interactive=True
- Given run(timeout=极小, task_id 非空)，When 超时触发，Then abort_bridge(task_id) 在 engine.abort() 之后被调，RuntimeError 照旧抛出
- Given 现有 boundaries 测试，Then 回归全过

## Implementation Notes

- `agent_sdk` 顶部模块级 `from . import askuser`（askuser → app.tasks → app.db 无回路，import 冒烟过）；中止路径均以 `askuser.abort_bridge(task_id)` 属性访问调用，测试 spy 可替换
- 三处中止统一语义：超时（RuntimeError 照旧抛出）、轮次上限（防御性）、**asyncio.CancelledError（任务层取消/服务关停，re-raise）**——均在 `engine.abort()` 后按 task_id 非空调 `abort_bridge`，阻塞中的问询一个分片周期内退出，不再泊到 deadline
- `t0` 上移至 run() 起点，`deadline_at = t0 + timeout` 同点算出（等待与执行共享额度的落点）；duration_ms 因此把 Engine 构造也计入，语义更完整
- `_build_tools(task_id, log_cb, deadline_at, interactive=False)` 返回完整列表（基础五件 + 条件追加），run/warmup/测试共用（warmup 不再硬编码五件）；log_cb 传 `emit`（log or progress）
- `_system_prompt(interactive=False)`：工具清单行与提问段抽为局部变量条件拼装，False 渲染与 1.1 基线逐字一致（测试内嵌基线原文逐字符比对钉死）；True 分支工具行如实写「工具六件」逐件列出（与 _build_tools 口径一致），「## 向用户提问」置于「环境与能力」之后、「平台工具手册」之前
- 提示词旗标与工具挂载同条件：`_system_prompt(bool(interactive and task_id))`——interactive 无 task_id 时工具不挂、提示词也不宣告（防模型调不存在的工具）；传自定义 system_prompt 时提问段不追加但工具仍按条件挂载（docstring 已注明）
- 超时/取消测试两层：确定性 stub Engine captor 为主覆盖（无网络：组装 kwargs 六件/五件、deadline≈起点+timeout、超时与取消路径的 abort 顺序），真 LLM 组为可选附加（LLM 未配置或端点先完成打 SKIP 注记计数，不进 FAIL）
- 验证结果（评审修正后）：test_run_wiring.py 45 通过 / 0 失败 / 0 SKIP 注记；test_agent_sdk_boundaries.py 17 PASS；test_askuser_flow.py 85 PASS；`warmup()` 直调 OK、`import main` 冒烟 OK

## Spec Change Log

（评审回路时由 step-04 填）

## Review Triage Log

- high — run()→Engine 组装零断言：删掉 _build_tools 的 interactive 实参或换错 emit/deadline 位置参，三套测试全绿照过（验证缺口1，删除演示证实）——本故事的核心交付物（挂载+提示词+共享 deadline 的组装）可被任意 run() 内部重构静默破坏 → patch（stub Engine captor 场景）
- high — 唯一执行真 run() 的测试组在无 LLM 配置的机器上静默 SKIP 且 exit 0，超时唤醒回归（「run 已超时、问题还挂界面」窗口）在该环境全盲（验证缺口2）→ patch（确定性 stub-Engine 超时场景，去网络依赖）
- medium — CancelledError 取消路径不 abort：任务层取消/服务关停时阻塞中的问询线程泊到 deadline（最长 3600s），桥与 waiting 残留（盲审1、边界2）→ patch（镜像超时 handler 的 except CancelledError）
- medium — interactive=True 且 task_id 空：提示词宣告 AskUserQuestion 但工具未挂，模型调不存在的工具空耗轮次（边界1、验证缺口 Other1；现无调用方触达，潜伏）→ patch（提示词旗标 bool(interactive and task_id)）
- medium — 提示词「工具五个」实挂六件（ReadFile/ListDir 合并计数与 _build_tools「基础五件」口径打架），测试还钉死了错误文案（盲审2）→ patch（如实计数并更新 pin）
- low — scaffold 源码 regex 非贪婪截到首个 ) ，无害重构即空转/误报（盲审7、验证缺口 Other2）→ patch（换成稳健断言）
- low — warmup 硬编码五件工具列表，基础集变更时的漂移隐患（验证缺口 Other3）→ patch（_build_tools(None, None, 0.0)）
- low — 超时测试对快端点 flaky：2s 内完成则假失败（盲审3、边界3）→ patch（随确定性场景取代 + 完成即 SKIP 注记）
- low — interactive+自定义 system_prompt 的耦合未文档化（盲审5）→ patch（run() docstring 两行说明）
- low-reject — deadline_at 与 wait_for 预算差一个 Engine 构造时长（盲审6）：漂移方向安全（桥先过期即设计意图），spec 冻结区钉死了 t0+timeout 公式
- low-reject — pytest 收集 test_*.py 零用例的绿 CI 错觉（盲审8）：仓库无 pytest/CI 配置，直跑断言脚本即项目约定（docstring 已给命令），不为假设的 CI 加层
- false — 「跟踪工件不在评审 diff 内」（盲审9）：工作流按代码路径出 diff、BMAD 工件另行随故事提交，流程设计而非缺陷

## Design Notes

- 工具组装抽成模块级 `_build_tools(task_id, log_cb, deadline_at, interactive)`：run() 与测试共用，避免为断言而跑真 LLM
- 提示词动态段做法：`_system_prompt(interactive=False)` 默认参保证所有既有调用零改动；True 时在「环境与能力」追加工具行 + 新增「## 向用户提问」段（何时该问/用法）
- 超时测试的 spy：monkeypatch `askuser.abort_bridge` 收集调用；run 内 `from . import askuser`（或模块级 import）后以属性访问，spy 才能生效——实现时注意 import 方式
- 超时测试约发起一次被中止的真实 LLM 请求（成本≈0）；`llm_configured` 为假时打印 SKIP 并跳过该断言组

## Verification

**Commands:**
- `.venv/Scripts/python.exe tests/test_run_wiring.py` -- expected: 全 PASS（或含显式 SKIP 注记）、exit 0
- `.venv/Scripts/python.exe tests/test_agent_sdk_boundaries.py` -- expected: 17 全 PASS
- `.venv/Scripts/python.exe tests/test_askuser_flow.py` -- expected: 85 全 PASS（askuser 未动，回归）

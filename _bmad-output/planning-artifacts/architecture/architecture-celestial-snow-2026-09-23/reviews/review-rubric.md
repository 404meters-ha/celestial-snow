# Rubric 评审 · ARCHITECTURE-SPINE（技能交互 L2：AskUser + 任务暂停/恢复）

- 评审对象：`..\ARCHITECTURE-SPINE.md`（2026-09-23 draft）
- 评审方式：good-spine 8 项清单逐项判定；全部棕地事实对照真实代码核实（抽查坐标见 §证据）
- 结论：**有条件通过（pass with revisions）**——范式与主干决策质量高且经代码证实；1 项 High（终态竞态）须修订后方可进 stories，3 项 Medium 建议随手补钉

## 逐项判定

| # | 清单项 | 判定 | 一句依据 |
| --- | --- | --- | --- |
| 1 | 固定 stories 真正的分叉点，无遗漏 | **pass（带补充）** | 状态机单写者/桥机制/单问串行/挂载矩阵/三路退出/数据契约/六触点等主干分叉全部钉死；但漏了 3 钉：run() 缺 task_id 通道（M-1）、前端状态分支枚举不全（M-2）、「何时该问」提示词落点（M-3） |
| 2 | 每个 AD 的 Rule 可执行且真的阻止其声明的分叉 | **fail（一处）** | AD-2/3/4/6/7 逐条可执行且经代码证实（引擎确有「非只读单跑」）；AD-1 声明防「僵尸态」，但 wait_for 超时抛弃线程后清场写回 running 可晚于终态 failed 写入——恰在该角落防不住（H-1） |
| 3 | Deferred 无跨单元不兼容项 | **pass（条件）** | 6 项 Deferred 中 5 项纯故事级；唯「waiting 区间扣除前端 vs 后端」是跨层位置决策被下放，两故事可各猜一边（L-4，建议上提一句「前端算」） |
| 4 | 点名技经核实当前有效 | **pass** | SEED 全部现存：Python 3.14.2（.venv/pyvenv.cfg 实测）、threading 标准库、requirements.txt、vendor ask_user.py 文案原文（"User answered:\n" + join / "User cancelled the question."）、测试风格样板 tests/test_agent_sdk_boundaries.py——「无新增依赖」声明可信 |
| 5 | 棕地批准式（ratify） | **pass** | 全部点名事实相符：status 3 值（models.py:178）、tool 接口（tool.py:27-34）、agent_sdk.run 签名（agent_sdk.py:382）、引擎单跑机制（engine.py:335-344）；仅 2 处文档小错（L-3：main.py 路径、agent 端点改法） |
| 6 | 覆盖驱动 spec 的能力（PRD 六 FR） | **pass** | Capability→Map 六 FR 全落位且各绑 AD；小缺口：FR-1 末条「系统提示词明确何时该问」无落点（M-3） |
| 7 | 该 altitude 的结构维度均已决定/推迟/开放 | **pass** | 数据（复用 payload JSON 列，合规免 _migrate）、可观测（❓✅⛔ 封顶 200）、故障重启（孤儿清扫）、权限（auto_approve 不变）、并发（注册表锁+幂等）、测试、部署（范式句钉死单进程，多 worker 不可行）——运维/环境无沉默遗漏；唯 H-1/M-1 两点是被沉默而非列开放 |
| 8 | mermaid 图有效且传达结构 | **pass（小疵）** | 语法有效可渲染（未声明的 API 参与者会被自动创建），跨线程桥「DB 可见性 / Event 唤醒」二分传达准确；疵：图与 AD-2 文本的注册/写库次序互相矛盾（L-1），U→DB 标注 "GET /api/tasks/{id}" 混用 API/DB 参与者 |

## 发现清单

### High

- **H-1 终态竞态：超时路径的「先行清场」次序不可强制**（AD-1 / AD-5）
  `agent_sdk.run` 的 `asyncio.wait_for(asyncio.to_thread(_drive), timeout)` 超时后（agent_sdk.py:466-470）只调 `engine.abort()` 即抛错，worker 线程被抛弃但仍在跑：工具 wait 循环 ≤0.5s 后才看到 abort 标志、执行清场（回 running + 清 pending_question + 注销）。任务层此时已写终态 failed（tasks.py:86）——清场的 `status=running` 若晚落，DB 终态变成「running + finished_at 已写 + 无桥」的永久僵尸（孤儿清扫只在下次重启收）。AD-1 说「若终态时仍 waiting 由工具退出路径先行清场」，但被抛弃的线程无法保证「先行」。
  **修复建议（钉进 AD-1 或 AD-5 一句话）**：清场回 running 用条件更新（`UPDATE ... WHERE status='waiting'`；终态已写则只清 payload + 注销桥），或 `run()` 在 abort 后对线程做有界 join（≤2s）再抛超时。

### Medium

- **M-1 `run()` 构造工具所需的 task_id 通道未钉死**（AD-4 + Structural Seed）
  `AskUserQuestionTool` 要注册桥、写 `task_runs.payload.pending_question`，必须知道 task_id；AD-5 的 deadline 也由 run() 注入。但现签名 `run(prompt, progress, log, timeout, ...)` 无 task_id，`interactive: bool` 信息量不足。两个故事（桥模块 vs 挂载）会在此撞车。建议钉死：`run(..., interactive=False, task_id=None)`，或 interactive 直接收工具工厂。
- **M-2 前端状态分支枚举不全：六触点漏了第 ⑦ 点**（AD-7）
  面板模板还有两处字面状态分支不在清单里：`App.vue:48` 的 `v-if="panelTask.status !== 'running'"`（task-foot：waiting 会误显「查看结果/关闭」终态 footer）与 `App.vue:40` 的 elapsed 标签三元（waiting 误显「耗时」措辞）。触点清单是故事验收项，漏项=漏验收。
- **M-3 「何时该问」的系统提示词落点未定**（AD-4 / FR-1）
  PRD FR-1 要求「工具描述与系统提示词明确何时该问」。默认 `_system_prompt()`（agent_sdk.py:321）被 scaffold 运行共用——引导文案进默认提示词会泄漏到无 AskUser 工具的运行；interactive 专属附加段才是对的位置。挂载矩阵管了工具列表，漏了提示词维度。

### Low

- **L-1 图文次序矛盾**：时序图先「写 DB（waiting）」后「Bridge 注册」，AD-2 文本是「注册 → 写 DB → wait」。文本次序才避免「DB 已 waiting 但桥未注册」的 409 窗口，统一为注册在前。
- **L-2 不变量未限定非终态**：AD-1「waiting ⇔ pending_question 非空 ⇔ 桥已注册」在孤儿清扫后字面即破（waiting→failed 但 payload 残留 pending_question——留痕反而合理）。补「非终态任务上恒成立」即可。
- **L-3 Structural Seed 两处与代码不符**：`main.py` 实际在项目根（main.py:69），不在 `app/` 下；「api.py agent 端点传 interactive=True」不必要——AI 命令栏（/agent/run）与技能 invoke 都汇入 `skill_runner.run_prompt`（api.py:903 / skill_runner.py:121），单点改 run_prompt 即覆盖两端点。
- **L-4 Deferred 跨层项建议上提**：「waiting 区间扣除（前端 vs 后端）」是位置决策非实现细节；addendum §4 已倾向前端（记 waiting_since），脊柱补一句即消歧（关联清单项 3）。

## 证据（抽查坐标）

| 脊柱声明 | 代码事实 | 判定 |
| --- | --- | --- |
| 状态机现 3 值 running\|success\|failed | `app/models.py:178` | 相符 |
| 工具接口 is_read_only / ToolResult(content, is_error) | `vendor/cc-mini/src/core/tool.py:7-34` | 相符 |
| 引擎「非只读工具单跑」 | `vendor/cc-mini/src/core/engine.py:335-344`（批划分区注释明言 "a non-read-only tool runs alone"） | 相符 |
| abort() 关流但叫不醒阻塞中的工具（分片轮询必要性） | `engine.py:170-181`（只置标志 + 关 `_active_stream`；工具执行期无活动流） | 相符 |
| agent_sdk.run 现签名 | `app/services/agent_sdk.py:382` | 相符 |
| scaffold_builder 直调 run、默认不挂 | `app/services/scaffold_builder.py:279-287` | 相符 |
| 技能 invoke 与 AI 命令栏都走 run_prompt | `app/services/skill_runner.py:121`、`app/api.py:903` | 相符（催生 L-3） |
| 孤儿清扫现只扫 running | `main.py:69-84`（`status == "running"`） | 相符，增量合法 |
| tasks.py 同步 helper / 封顶 200 / \_task_view 含 payload | `app/tasks.py:9,16-40,43-52` | 相符 |
| auto_approve 放行非只读工具 | `vendor/cc-mini/src/core/permissions.py:92-95` | 相符 |
| focusTask 停轮 / pollOnce 接管 / elapsed 现状 | `frontend/src/App.vue:1185`（`!== 'running'`）、`:1984`（find running）、`:1093-1099` | 相符，坐标与 addendum 一致 |
| vendor 文案 "User answered:\n{q} => {a}" / "User cancelled the question." | `vendor/cc-mini/src/tools/ask_user.py:410-420` | 相符 |
| Python 3.14（现有 .venv） | `.venv/pyvenv.cfg` → 3.14.2 | 相符 |

## 门裁决

**有条件通过。** 修订 H-1（必须）+ M-1/M-2/M-3（应当）后即可产 stories；L 级可随故事顺手消化。范式句（可见性走 DB、唤醒走 Event）正确抓住了棕地线程模型的真实约束，挂载矩阵/单问串行/文案契约均经代码核实成立。

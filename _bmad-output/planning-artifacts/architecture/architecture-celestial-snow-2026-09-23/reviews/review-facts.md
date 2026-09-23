# 事实核实评审 — ARCHITECTURE-SPINE.md（技能交互 L2）

- 评审员角色：version/reality checker（逐条对照源码，不信训练数据）
- 日期：2026-09-23
- 对象：`../ARCHITECTURE-SPINE.md`（status: draft）
- 裁决：**通过（需修 2 处）**——脊柱引用的现实现状经逐条源码核实基本全部属实、committed 决策有现实依据；但 Structural Seed 对 `agent_sdk.run()` 签名改动的描述不足（task_id 缺口，F1），Stack 表「锁定版」用词不准（F2）。修完可提交。

## 一、核查点与证据

### 1. 「无新增依赖」— 属实（附措辞备注）

| 依赖 | 声称 | 核实结果 |
| --- | --- | --- |
| threading（Event/Lock） | 标准库 | 属实。标准库无需安装；当前 `app/`、`main.py` 无 threading 使用（vendor/cc-mini 的 tui/buddy/agents 模块在用），不影响「无新增依赖」结论 |
| FastAPI + Uvicorn | requirements.txt | 属实：`fastapi>=0.115`、`uvicorn[standard]>=0.32`（`requirements.txt` L1-2）；main.py 全文在用 |
| Vue 3 + Element Plus | frontend 现有 | 属实：`vue ^3.5.13`、`element-plus ^2.9.0`（`frontend/package.json`）；App.vue 中 `el-` 组件 391 处在用 |
| Python 3.14 | 现有 .venv | 属实：实测 `.venv/Scripts/python.exe --version` → Python 3.14.2 |

### 2. tasks.py 每调用独立 SessionLocal — 属实（AD-1 / 约定依赖成立）

`app/tasks.py`：
- `_sync_update`（L16-23）：`with SessionLocal() as s:` 每调用独立开 session 后 commit；
- `_append_log`（L26-40）：同样独立 `with SessionLocal()`，且 JSON 列整体重赋值（`row.logs = [*(row.logs or []), entry][-MAX_LOGS:]`）、`MAX_LOGS = 200` 封顶。

脊柱「复用 tasks.py 每调用独立 SessionLocal 的同步 helper 模式」「留痕走 _append_log（封顶 200）」均与源码一致。worker 线程直接调这两个同步 helper 的模式在现有代码里就是跨线程安全的用法，AD-1 前提成立。

### 3. vendor 引擎「非只读工具单跑」— 属实（AD-3 依赖成立）

`vendor/cc-mini/src/core/engine.py` submit()（L335-344）：

```python
is_concurrent = t is not None and t.is_read_only()
if batches and batches[-1][0] == is_concurrent and is_concurrent:
    batches[-1][1].append(tu)
else:
    batches.append((is_concurrent, [tu]))
```

非只读工具（`is_concurrent=False`）总是自成新批，走 L403-426 的串行支路（逐个 `yield tool_call → _execute_tool → tool_result`）；只有「连续的只读工具」才进 ThreadPoolExecutor 并行批。**「非只读工具单跑」与源码一致**——`is_read_only() → False` 的 AskUserQuestionTool 必然独占串行批，AD-3 的单问串行机制有现实依据。

`vendor/cc-mini/src/core/tool.py`（L33-34）：`is_read_only()` 默认返回 **False**。脊柱新工具显式声明 False 与基类默认一致（显式写更稳，不构成问题）。

### 4. agent_sdk.run() 签名现状 — timeout 在、**task_id 不在**（→ F1）

`app/services/agent_sdk.py` L382-384 现有签名：

```python
async def run(prompt: str, progress, log=None, timeout: int = 3600,
              max_turns: int = MAX_TURNS, system_prompt: str | None = None,
              max_tokens: int | None = None) -> dict:
```

- `timeout` 参数存在（默认 3600，与 `config.py` L37 `skill_run_timeout: int = 3600` 一致，AD-5「deadline = skill_run_timeout 剩余额度、由 run() 构造工具时注入」在现有参数下可推导，可行）。
- **`task_id` 参数不存在**：`skill_runner.run_prompt`（L105）收了 task_id，但调 `agent_sdk.run(prompt, progress, log=log, timeout=timeout)`（L121）时丢掉了。见发现 F1。

### 5. main.py _fail_orphan_tasks 只扫 running — 属实（脊柱要求扩 waiting 的前提成立）

`main.py` L69-84（注意：**main.py 在仓库根目录，不在 app/ 下**，Structural Seed 的树里写的 `main.py` 与此一致）：

```python
update(TaskRun)
.where(TaskRun.status == "running")
.values(status="failed", error="服务重启，任务中断", ...)
```

当前确实只扫 `running`；在 lifespan 启动时调用（L55）。waiting 态加入后若不扩扫，重启会留下 waiting 僵尸——脊柱 AD-7 触点③的必要性属实。

### 6. ask_user.py 返回文案 — 与 AD-5 引用逐字一致（附一个对照发现 F3）

`vendor/cc-mini/src/tools/ask_user.py`：
- answered（L418-421）：`result_text = "User answered:\n" + "\n".join(answers)`，每条 answer 为 `f"{question_text} => {answer}"` —— 与 AD-5 的 `User answered:\n{q} => {a}` 一致（多问时逐行拼接）。
- cancelled（L410、L415）：`ToolResult(content="User cancelled the question.", is_error=True)` —— 逐字一致，且 is_error=True 与 AD-5 相符。
- **vendor 版 `is_read_only()` 返回 True**（L388-389）——与脊柱新工具取 False 相反，见 F3。

### 7. Stack 表「现有锁定版」— 说法站不住一半（→ F2）

requirements.txt 全部是 `>=` 下限约束（fastapi>=0.115、uvicorn>=0.32、sqlalchemy>=2.0、pydantic>=2.9、pydantic-settings>=2.6、httpx>=0.28、apscheduler>=3.10,<4、beautifulsoup4>=4.12、./vendor/cc-mini），**没有锁定版本号**。.venv 实装：fastapi 0.141.1、uvicorn 0.52.4。前端同为 `^` 区间（vue ^3.5.13、element-plus ^2.9.0）。「现有锁定版」作为「沿用既有、不新增」的意图成立，但「锁定」一词与事实不符—— rebuild 环境装到的可能是更高版本。

### 8. （额外语境核实）AD-4 挂载点与 AD-7 六触点对应的现状 — 全部属实

- 挂载点存在：技能 invoke `POST /skills/{name}/invoke`（api.py L762-780 → run_skill，带 task_id）；AI 命令栏 `POST /agent/run`（api.py L892-917 → run_prompt，timeout 取 skill_run_timeout）；scaffold_builder.py L279 直调 `agent_sdk.run(...)`（无 interactive，新参数默认 False 向后兼容，AD-4「scaffold_builder 保持默认 False」成立）。
- `focusTask` 1s 定向轮询（App.vue L1195 `setInterval(onTick, 1000)`）；停轮条件 L1185 `status !== 'running'`——waiting 会被当完结停轮，脊柱要改的点真实存在。
- `pollOnce` 3s 通用扫描（L2000-2002 `setInterval(..., 3000)`），L1984 只认 `status === 'running'`——waiting 任务刷新后无人接管，属实。
- 状态 tag 三态映射（L539-540 表格、L1114 文案、L1144 type：success/running/其余 danger）——waiting 会显示成「失败」红色，触点④必要。
- elapsed 计算 L1097（created_at → finished_at/now），waiting 冻结需新增逻辑，触点⑤必要。
- `models.py` L178：`status ... default="running"  # running|success|failed`——触点⑥（补 waiting 注释与写入点）对应现状属实。
- 约定「读侧补 Z 由前端 parseUTC 处理」：App.vue L1080-1083 parseUTC 对无时区后缀的串补 `Z`，属实。

## 二、发现（需处理）

### F1（中）— Structural Seed 漏了 run() 必须增 task_id，「其余不动」不成立

- **位置**：ARCHITECTURE-SPINE.md Structural Seed `app/services/agent_sdk.py # run() 增 interactive 参数（工具组装处，其余不动）`；关联 AD-2（注册表按 task_id 键控）、AD-1（waiting/pending_question 按 task_id 写 task_runs）、AD-5（run() 构造工具时注入 deadline）。
- **问题**：现有 `run()` 没有 task_id（agent_sdk.py L382-384；skill_runner.py L121 调用时丢弃）。AskUserQuestionTool 在 run() 内构造，要写 DB、注册桥、被 answer 端点按 `/api/tasks/{id}/answer` 定位，都必须知道 task_id。只加 `interactive: bool` 一个参数不够——这不是故事级细节，是脊柱级签名事实，影响 AD-4/AD-5 的可行性表述与 skill_runner 的改动范围。
- **建议**：Structural Seed 与 AD-4 改为「run() 增 `interactive: bool = False` 与 `task_id: str | None = None`（工具构造与桥注册所需）；非交互路径不传，其余不动」，skill_runner L121 相应补 `task_id=task_id`。

### F2（低）— Stack 表「现有锁定版」措辞与 requirements.txt 事实不符

- **位置**：Stack 表 `FastAPI + Uvicorn | 现有 requirements.txt 锁定版`、`Vue 3 + Element Plus | frontend 现有锁定版`。
- **问题**：requirements.txt 全为 `>=` 下限（fastapi>=0.115、uvicorn>=0.32），前端为 `^` 区间——不是锁定。「锁定版」是凭印象的断言，恰是本次评审要防的类别。
- **建议**：改为实际约束/实装版本，如「fastapi>=0.115（.venv 实装 0.141.1）/ uvicorn>=0.32（实装 0.52.4）」「vue ^3.5.13 / element-plus ^2.9.0（package.json 既有区间）」。

### F3（低，备注级）— vendor 版 AskUserQuestion 的 is_read_only=True 与脊柱取 False 相反，值得在 AD-3 写明

- **位置**：AD-3「工具 is_read_only() → False」；vendor/cc-mini/src/tools/ask_user.py L388-389 为 True。
- **问题**：脊柱规则本身正确且必要（若照抄 vendor 的 True，同轮两个 AskUserQuestion 会被引擎的只读并行批同时拉起，单问串行失效——engine.py L350-386）。但脊柱未注明这一差异，实现故事有可能图省事直接 import vendor 工具类。
- **建议**：AD-3 补一句「注意 vendor 版 is_read_only 为 True（CLI 交互语义），web 版必须覆写为 False 才能借单跑机制；vendor 保持上游只读，实现在 app/services/askuser.py」——脊柱已有后半句，补前半句差异原因即可。

## 三、结论

脊柱的 8 组现实现状引用（tasks.py 独立 session、engine 非只读单跑、tool 默认值、run() 签名现状、孤儿清扫范围、vendor 文案、挂载点、前端六触点）经源码逐条核实**全部属实**，committed 决策不是凭训练数据断言。两处需修：F1（run() 增 task_id 是脊柱级遗漏，影响 AD-4/AD-5 表述）、F2（「锁定版」措辞）。F3 为防走偏的备注。修完 F1/F2 即可进入故事拆分。

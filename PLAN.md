# celestial-snow 学习闭环 · 实施计划

> 定稿 2026-09-07（/grill-me 四轮共识）｜ 状态：✅ 已完成上线（2026-09-08 实施，全链路联调通过）
> 本文件是唯一权威计划：开工时按此执行，改设计先改这里。

## 附录 A · 通用技能宿主（2026-09-08 追加，已完成）

用户追加需求：不拆解 /tech，要一种**通用**方法在平台调用各类 Claude Code 技能，且**实时生效**。

- 设计：平台作为技能宿主。`GET /api/skills` 每次请求现扫 `项目/.claude/skills/` + `~/.claude/skills/` 的 SKILL.md frontmatter（不缓存 ⇒ 新增/修改技能即时生效，无需重启）；`POST /api/skills/{name}/invoke` 用 TaskManager 后台跑 `claude -p "/<name> <args>" --output-format stream-json`（cwd=项目根），工具事件实时写任务进度，最终结果（含 cost/turns）挂到任务 payload。前端新增「🛠 技能」tab（卡片 + 参数对话框 + 最近执行表 + 结果查看）。
- 权限边界（用户拍板）：**允许清单 + 可选全放行**。`skill_run_bypass_permissions` 默认 False，走项目 `.claude/settings.json` 允许清单（Read/Write/Edit(./**) + Glob/Grep/WebFetch + Bash 的 curl/ls/cat/head/tail/wc/grep/rg/pwd）；`.env` 设 `SKILL_RUN_BYPASS_PERMISSIONS=1` 才全放行。
- 实时生效已验证：服务运行中新增技能文件 → 下一次 GET /api/skills 即出现（57→58，无重启）。
- 已知限制：Claude Code 会话内部（本沙箱）禁止再启动 claude.exe（防嵌套 agent，WDAC 报 WinError 786「管理员用策略规则限制」）——因此**无头调用的最终验证必须由用户从自己的终端启动服务后进行**；平台自身代码链路（发现/提交/轮询/前端）均已验证。
- 测试技能：`/ping`（冒烟测试，含一次 Bash 工具调用验证权限链路）、`/hello`（最小技能模板，可复制改造为新技能）。

## 定位与闭环

一人公司 OPS（自用，多用户预留）：调研 GitHub → 优选 issue → `/tech` 生成课程 → 平台托管学习 + quiz 反馈 → 结束。

- PR 不归平台管；课程纯知识（无 PR 指导课）；考试后无任何流程
- 品牌路线不直接变现；暂不开源；git 仅本地 init、无远端
- 多用户预留：新表带 `user_id` 列（固定值 1），无登录

## 已定设计决策

1. **课程形态**：teach 风格 HTML（Tufte），平台托管于顶层 `courses/` 目录，静态挂载到 `/courses` 路由
2. **课程骨架**：三章「项目导览 → 核心代码路径 → issue 实战」，每章 1–3 节，总节数按仓库规模自适应（3–9 节）；课程语言中文
3. **quiz**：每节 HTML 尾嵌客观题（单选/多选/判断）3–5 题；即时反馈 + 回传平台；无及格线、无平台判分
4. **issue 状态机**：`null → learning`（生成课程时自动）→ `done`（该课程全部 quiz 均提交后自动判定）
5. **/tech skill**：复制 `~/.claude/skills/teach` → 项目级 `.claude/skills/tech`，改造成一次性批量生成器；保留 MISSION/learning-records/reference/assets；原 teach 不动
6. **调用**：`/tech <issue_id>`（无参时兜底列出可选 issue）；skill 直接写盘 `courses/{course_id}/`，元数据走 API
7. **「学习」tab**：打开课程 = 新标签页 `/courses/{id}/index.html`（不用 iframe）
8. **默认已定**：`courses/` 生成物不入 git；`user_id=1` 占位

## 实施清单

### 1. 基础设施
- [x] `git init`（本地，无远端）
- [x] 核对 `.gitignore`：覆盖 `.env`、`celestial.db`、`courses/`、`node_modules`、`dist`

### 2. 后端（app/，沿用 JSON 列 + String 状态 + UTC 惯例）
- [x] `models.py` 新表：
  - `courses`：id, user_id(默认1), repo_id FK, issue_id FK, title, lessons JSON, status('learning'|'done'), created_at
  - `quiz_results`：id, user_id, course_id FK, lesson_id(str), score, total, detail JSON(每题对错), created_at
- [x] `issues` 加列 `learning_status`——注意 SQLite：`create_all` 不会改旧表，需 `ALTER TABLE issues ADD COLUMN learning_status VARCHAR(16)`
- [x] `api.py` 新端点：
  - `GET /api/learning-context/{issue_id}`：打包 issue + repo 元数据 + README + 分析报告（供 /tech 一次取全）
  - `POST /api/courses`：注册元数据 → 返回 course_id；副作用：issue → learning
  - `GET /api/courses` / `GET /api/courses/{id}`：含各章 quiz 进度
  - `POST /api/quiz-results`：回传；全部 lesson 均有提交 → course 与 issue 置 done
- [x] `main.py`：`courses/` 静态目录挂载到 `/courses`（`html=True`）

### 3. 前端（App.vue + api.js，不引 vue-router，沿用 el-tabs）
- [x] 新 el-tab「📚 学习」：课程卡片（repo、issue、状态、各章 quiz 进度），「打开」→ 新标签 `/courses/{id}/index.html`
- [x] Issue 榜加「学习」列：未生成 → 复制命令提示（`/tech <issue_id>`）；已生成 → 状态 tag（学习中/已完成）
- [x] api.js 新增 5 个方法（getLearningContext / postCourse / getCourses / getCourse / postQuizResult）

### 4. /tech skill（.claude/skills/tech/）
- [x] 复制 teach 目录，改 SKILL.md：
  - name: tech；argument-hint: issue_id
  - 流程：`GET /api/learning-context/{id}` → 生成三章课程 → `POST /api/courses` 拿 course_id → 写 `courses/{course_id}/`（index.html + 各节 HTML）→ 生成 MISSION.md（使命 = 彻底理解 {repo}、吃透 issue #{n}）+ learning-records 骨架
  - 保留：MISSION/RESOURCES/reference/learning-records/assets（共享样式 + quiz 组件）；课程理念（短课、单一收获、引用规范）
  - 移除：有状态多会话教学 / ZPD 逐节推进（改一次性批量生成）
  - quiz 组件内嵌回传 JS：`fetch POST /api/quiz-results`（course_id 写死进生成的 HTML）
  - 该 issue 已有课程时：询问覆盖还是新开
- [x] 原 teach 保持不动

### 5. 联调
- [x] 取一个真实 issue 走全流程：生成 → 学 → quiz → issue 自动变 done
- [x] 前端改动后 `cd frontend && npm run build`

## 现状参考（代码事实，2026-09-07 勘察）

- 后端：单 `app/api.py` 全端点；`app/models.py`（SQLAlchemy 2.0 Mapped/mapped_column）；`app/tasks.py` 进程内 asyncio TaskManager（无 Celery/Redis）；`main.py` APScheduler 每日刷新 + SPA 静态托管
- 前端：`frontend/src/` 仅 3 文件（App.vue 473 行 el-tabs 单文件、api.js、main.js）；Element Plus；Vite dev 代理 /api → 8100
- 启动：`.venv/Scripts/python.exe -m uvicorn main:app --port 8100`
- 已有表：repos / issues / analyses / snapshots / contribution_reports / task_runs
- 平台已有 `GET /api/config` 返回用户技能配置；`.claude/settings.local.json` 已允许读用户 skills 目录

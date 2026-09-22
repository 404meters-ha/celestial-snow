# celestial-snow 平台速览（给无头运行的 AI）

GitHub Trending 情报站：抓取热门项目 → 规则 + LLM 双重评分 → issue 匹配推荐 → 贡献报告与学习闭环。
后端 FastAPI 跑在 `localhost:8100`，SQLite（`celestial.db`），前端 Vue 构建产物由本服务托管。

用户画像（`.env` 可覆盖，默认见 `app/config.py`）：`USER_PROFILE`（背景方向）、`USER_SKILLS`（技能清单，逗号分隔）。
给项目/issue 做推荐或打分时，围绕这份画像评估「与用户的匹配度」。

## 关键 API（curl 可直接访问）

- `GET /api/repos?sort=total|rule|stars&q=<关键词>&analyzed=all|done|todo&period=weekly|monthly&tag=<标签>&tag=<标签2>&limit=N&offset=N` — 项目榜
  （分页返回 `{repos, total}`；字段：`full_name` `stars` `language` `total_score` `rule_score` `tags` `analyzed` `latest_report`。
  `analyzed=done` ⇔ LLM 精析完成；`tag` 可重复多选，多值 AND 交集；`tag`/`period` 是 JSON 列 LIKE 过滤，模式须走 `api._json_like`——中文存成 `\uXXXX`，裸拼 LIKE 匹配不到）
- `GET /api/repos/{full_name}` — 项目详情，含 README 全文缓存 `readme_cached`、LLM 精析 `llm_scores`、`latest_report`（贡献报告 id）
- `GET /api/issues?sort=match|rule|latest&difficulty=低|中|高&deep_only=true&analyzed=all|done|todo&limit=N&offset=N` — issue 排行榜
  （分页返回 `{issues, total}`；`analyzed=done` ⇔ `match_score` 非空（LLM 精筛过）；「疑似已修复」按物化列 `issues.fixed_hint` 在 SQL 沉底）
- `POST /api/repos/analyze` `{"repo_ids": [...]}` — 批量精析选中项目（≤10 个，任务类型 `analyze`，复用刷新流水线的单仓精析）
- `POST /api/repos/translate` — 为 `repos.zh_desc`（中文一句话简介）缺失的项目批量生成（已是中文的直接回填，其余 LLM 翻译；任务类型 `translate`；精析完成时也会用 core_idea 兜底回填）
- `GET /api/tags` — 标签 → 项目数汇总（`repos.tags` JSON 列，行业分析与全量打标都写这里）
- `POST /api/tags/auto` — 全量自动分类：LLM 先提 8-15 个分类体系（强制优先复用 `tags` 表已有标签），再分批给所有项目打 1-3 个标签（任务类型 `tagging`）
- `POST /api/industries/parse` `{"text": "agent运行时 pi deer-flow"}` — 行业分析输入解析（同步 2-5 秒）：LLM 拆「方向 vs 项目名」，
  方向经标签库归一给 canonical，项目名 GitHub 定位出候选清单——前端确认面板的数据源
- `POST /api/industries` `{"directions": [{"raw": "agent运行时", "tag": "Agent运行时"}], "repos": ["bytedance/deer-flow"]}` — 确认后的多方向分析
  （任务类型 `industry`，方向串行跑；种子项目并入各方向候选与报告，项目名本身不打成标签）；报告看 `GET /api/industries`（列表）/ `GET /api/industries/{id}`（含 `overview_md` 与项目分类清单）；
  `DELETE /api/industries/{id}` 删一份报告（只删报告记录，`repos.tags` 是累积知识不动）
- `GET /api/learning-context/{issue_id}` — 一次取全：issue + 仓库元数据 + README + 贡献报告深读段（深度分析/生成课程用这个）
- `POST /api/courses/{course_id}/publish` — 把 `courses/{id}/` 发布到服务器本地磁盘（`LOCAL_PUBLISH_DIR`，默认 `./published`，平台静态托管在 `/published`），返回 `entry_url` 等清单
  （平台负责分文件夹、用中文课标题重命名课件、改写页面内相对链接；`{"prune": true}` 清掉上一版残留文件；nginx 接管时改 `LOCAL_PUBLISH_BASE_URL`）
- `GET /api/tasks?limit=N` — 后台任务状态；`GET /api/config` — 配置状态
- `POST /api/scaffold/requests {"text":"一句话需求"}` — 脚手架匹配任务（status=matching→matched，产出 `need_brief` 与 `framework_candidates` 5-8 个，
  双轨适配度 fit=规则0-40+LLM0-60）；`GET /api/scaffold/requests` 分页列表 / `GET /{id}` 详情；`POST /{id}/match` 改话重跑
- `POST /api/scaffold/requests/{id}/adopt {"full_name"}` — 采用分支（同步评估报告，终态 done_adopt）
- `POST /api/scaffold/requests/{id}/split` — 拆技术条目（同步 2-10 秒，matched→split；同需求命中拆解缓存秒回）；
  `PUT /{id}/items {"items":[…],"tech_stack":"…"}` — 条目增删改确认 → selecting 任务 → selected（每条目 candidates 3-5 双轨评分，条目关键词入 tags）
- `POST /api/scaffold/requests/{id}/select {"selections":[{no, full_name|null}]}` — 逐条选型提交（null=自研）→ scaffold_build 任务：
  base 预判 → Agent 生成六件套（README/前端页/docs 三件/LICENSES）→ 校验打包 → status=built，`build` JSON 含 zip_url/base 主干/license 告警；
  产物 `GET /scaffolds/{id}/scaffold.zip` 直链下载（main.py 静态挂载，工作区 scaffolds/workspace/ 用完即清）
- 三层缓存（`scaffold_caches` 表，内容寻址指纹）：拆解（需求→条目）/ fit（条目+项目→分）/ build（组合指纹→产物，同组合重生成秒回不重跑 Agent；
  生成规范升级靠指纹版本号 v2 自动失效）

## 约定

- 结论要能支撑决策：值不值得投入这个项目 / 这个 issue 适不适合用户上手，给出理由与下一步动作。
- 输出用精炼的结构化 Markdown。
- 生成课程走 `/tech` 技能（参数 issue_id，可带 `replace` 表示覆盖已有课程不再询问），不要手工绕过它的流程。
- 课程有本地与发布目录两份：本地 `localhost:8100/courses/{id}/` 会回传 quiz 进度，发布目录（`/published`）那份是静态副本（可分享、不计进度）。
- 子路径部署走 `.env` 的 `BASE_PATH`（如 `/celestial-snow`）：后端 `_BasePathStrip` 中间件剥前缀（带/不带前缀都能访问），前端 `vite.config.js` 读同一份 `.env` 定构建 base，`api.js` 的 `BASE` 与课程 quiz.js 的相对回传路径（`../../api/…`）自动跟随；改动后须 `cd frontend && npm run build`。
- 技能参数表单：SKILL.md frontmatter 可写 `arguments: {单行 JSON}`（type: text/issue/select，`visible_if: "existing_course"` 为目前唯一条件），web 端据此渲染结构化表单，取值按声明顺序空格拼进 args。词表两端同步：`app/services/skill_runner.py::_parse_arguments` 与 `App.vue` 的 paramVisible。
- 列表分页一律服务端 `limit/offset` + 返回 `total`，排序末尾补 `id` tiebreaker（OFFSET 分页要求全序稳定）；`issues.fixed_hint` 是写入时算好的物化列（摄入/LLM 回写各节点经 `scoring.refresh_fixed_hint` 重算），不要回到「取一批再 Python 排序」的老路。
- 行业/分类标签统一存 `repos.tags`（JSON 数组，只增不减取并集）；新表/新列走 `db._migrate` 的 inspect+ALTER 模式。
- 标签库（`tags` 表）是 canonical 唯一登记处：所有写 `repos.tags` 的路径先过 `tags.ensure_tags` 归一——别名精确命中直接映射，
  未命中的 LLM 只做翻译级/缩写级同义合并（拿不准保持独立，宁可多标签不可错并）。canonical 一律中文（专有名词除外），
  英文原词进 aliases。历史脏标签（含紧贴式 `/` 的整串）由启动检测的一次性清洗任务拆串（`tag_cleanup`，成功一次即哨兵永不重跑）。

<template>
  <el-container class="layout">
    <el-header class="header">
      <div class="brand">
        <span class="logo">❄️ celestial-snow</span>
        <span class="sub">GitHub Trending 情报站</span>
      </div>
      <div class="ops">
        <el-tag v-if="config" :type="config.llm ? 'success' : 'info'" size="small" class="cfg-tag">
          LLM {{ config.llm ? '已配置' : '未配置' }}
        </el-tag>
        <el-tag v-if="config" :type="config.github_token ? 'success' : 'warning'" size="small" class="cfg-tag">
          GitHub Token {{ config.github_token ? '已配置' : '未配置（限流）' }}
        </el-tag>
        <el-button type="primary" :loading="refreshing" @click="refresh">立即刷新榜单</el-button>
      </div>
    </el-header>

    <el-main>
      <!-- AI 命令栏：自由指令，/开头即技能；行内「AI」按钮会把该行上下文预填到这里 -->
      <div class="ai-bar">
        <span class="ai-bar-logo">🤖</span>
        <el-input ref="agentInput" v-model="agentPrompt" class="ai-input" clearable
          placeholder="告诉 AI 要做什么，如：分析 volcengine/OpenViking、给 issue #462 打分；也支持 /技能名 参数"
          @keyup.enter="runAgentCmd" />
        <el-button type="primary" :loading="agentRunning" @click="runAgentCmd">运行</el-button>
      </div>

      <!-- 后台任务进度：运行时是时间线面板（真实长任务 74~338s，单行覆盖看不出还在动），
           结束后留在原位显示终态摘要，点「关闭」收起 -->
      <div v-if="panelTask" class="task-panel">
        <div class="task-head" @click="togglePanel">
          <el-tag :type="statusTag(panelTask.status)" size="small">{{ statusLabel(panelTask.status) }}</el-tag>
          <span class="task-what" :title="panelLabel(panelTask)">{{ panelLabel(panelTask) }}</span>
          <span class="task-msg" :class="{ 'task-err': panelTask.status === 'failed' }">
            {{ panelTask.status === 'failed'
              ? (panelTask.error || panelTask.progress)
              : (panelTask.progress || '处理中…') }}
          </span>
          <span class="task-elapsed">{{ panelTask.status === 'running' ? '已运行' : '耗时' }} {{ elapsedText }}</span>
          <span v-if="panelLogs.length" class="task-toggle">{{ panelOpen ? '▲' : '▼' }}</span>
        </div>
        <div v-show="panelOpen" ref="logsBox" class="task-logs">
          <div v-for="(l, i) in logLines" :key="i" class="log-line">
            <span class="log-time">{{ l.t }}</span>{{ l.msg }}
          </div>
        </div>
        <div v-if="panelTask.status !== 'running'" class="task-foot">
          <span v-if="panelResult && panelResult.cost_usd != null" class="muted">
            成本 ${{ panelResult.cost_usd.toFixed(4) }} · {{ panelResult.num_turns }} 轮
          </span>
          <el-button v-if="panelResult?.result" link type="primary" size="small"
            @click="showResult(panelTask)">查看结果</el-button>
          <el-button link size="small" @click="closePanel">关闭</el-button>
        </div>
      </div>

      <el-tabs v-model="activeTab" class="main-tabs">
        <!-- ================= 项目榜 ================= -->
        <el-tab-pane name="repos">
          <template #label>
            <span class="tab-label">📦 项目榜</span>
          </template>

          <div class="toolbar">
            <el-radio-group v-model="analyzedFilter" @change="resetRepoPage">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="done">已精析</el-radio-button>
              <el-radio-button value="todo">未精析</el-radio-button>
            </el-radio-group>
            <el-radio-group v-model="periodFilter" @change="resetRepoPage">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="weekly">周榜</el-radio-button>
              <el-radio-button value="monthly">月榜</el-radio-button>
            </el-radio-group>
            <el-radio-group v-model="sort" @change="resetRepoPage">
              <el-radio-button value="total">综合分</el-radio-button>
              <el-radio-button value="rule">规则分</el-radio-button>
              <el-radio-button value="stars">Star 数</el-radio-button>
            </el-radio-group>
            <el-select v-model="tagFilter" clearable filterable placeholder="标签" class="tag-select" @change="resetRepoPage">
              <el-option v-for="t in tagOptions" :key="t.tag" :value="t.tag" :label="`${t.tag}（${t.count}）`" />
            </el-select>
            <el-input v-model="q" placeholder="搜索项目名 / 描述" clearable class="search" @input="debouncedLoad" />
            <el-button :loading="translating" @click="runTranslate">译中文简介</el-button>
            <span class="picked-hint">已选 {{ picked.length }}/5</span>
            <el-button type="warning" :disabled="picked.length === 0" :loading="analyzing" @click="analyzeSelected">
              ✨ 精析选中
            </el-button>
            <el-button type="success" :disabled="picked.length === 0" :loading="contributing" @click="analyzeContribution">
              分析贡献机会
            </el-button>
          </div>

          <el-table :data="repos" v-loading="loading" @selection-change="onSelect" row-key="id" stripe>
            <el-table-column type="selection" width="42" />
            <el-table-column label="项目" min-width="300">
              <template #default="{ row }">
                <div class="repo-title">
                  <a :href="`https://github.com/${row.full_name}`" target="_blank" class="repo-name">{{ row.full_name }}</a>
                  <el-tag v-if="row.ai_analyzed" type="warning" size="small" effect="plain">AI 析</el-tag>
                  <el-tag v-if="periodLabel(row.periods)" :type="row.periods.length > 1 ? 'danger' : 'primary'"
                    size="small" effect="plain">{{ periodLabel(row.periods) }}</el-tag>
                </div>
                <div class="repo-desc">{{ row.description }}</div>
                <div v-if="(row.tags || []).length" class="repo-tags">
                  <el-tag v-for="t in row.tags" :key="t" size="small" effect="plain" class="tag-chip"
                    @click="filterTag(t)">{{ t }}</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="中文简介" min-width="240">
              <template #default="{ row }">
                <el-tooltip v-if="row.zh_desc || row.core_idea" :content="row.zh_desc || row.core_idea"
                  placement="top" :show-after="400">
                  <span class="zh-desc">{{ row.zh_desc || row.core_idea }}</span>
                </el-tooltip>
                <span v-else class="muted">—（点「译中文简介」生成）</span>
              </template>
            </el-table-column>
            <el-table-column prop="language" label="语言" width="110" />
            <el-table-column label="Star" width="100" sortable :sort-by="'stars'">
              <template #default="{ row }">⭐ {{ row.stars.toLocaleString() }}</template>
            </el-table-column>
            <el-table-column label="综合分" width="100" sortable :sort-by="'total_score'">
              <template #default="{ row }">
                <el-tag :type="scoreType(row.total_score)">{{ row.total_score }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="规则分" width="90" sortable :sort-by="'rule_score'">
              <template #default="{ row }">{{ row.rule_score }}</template>
            </el-table-column>
            <el-table-column label="LLM" width="90">
              <template #default="{ row }">
                <el-tag v-if="row.analyzed" type="success" size="small">已精析</el-tag>
                <el-tag v-else type="info" size="small">未分析</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">详情</el-button>
                <el-button v-if="row.latest_report" link type="success" @click="openReport(row.latest_report.id)">
                  贡献报告
                </el-button>
                <el-tooltip content="把该项目上下文预填进顶部 AI 命令栏" placement="top">
                  <el-button link type="warning" @click="aiRepoCmd(row)">✨ AI</el-button>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>

          <div class="pager">
            <el-pagination v-model:current-page="repoPage" v-model:page-size="repoPageSize"
              :total="repoTotal" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
              @current-change="loadRepos" @size-change="resetRepoPage" />
          </div>
        </el-tab-pane>

        <!-- ================= Issue 榜 ================= -->
        <el-tab-pane name="issues">
          <template #label>
            <span class="tab-label">🐛 Issue 榜</span>
          </template>

          <el-alert type="success" :closable="false" show-icon class="task-alert"
            title="按「与我的技能匹配度」排序的 issue 排行榜——分数越高，越适合你上手成为贡献者" />

          <div class="toolbar">
            <el-radio-group v-model="issueAnalyzed" @change="resetIssuePage">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="done">已分析</el-radio-button>
              <el-radio-button value="todo">未分析</el-radio-button>
            </el-radio-group>
            <el-radio-group v-model="issueSort" @change="resetIssuePage">
              <el-radio-button value="match">匹配度</el-radio-button>
              <el-radio-button value="rule">规则预分</el-radio-button>
              <el-radio-button value="latest">最新更新</el-radio-button>
            </el-radio-group>
            <el-select v-model="issueDifficulty" clearable placeholder="难度" class="diff-select" @change="resetIssuePage">
              <el-option value="低" label="难度：低" />
              <el-option value="中" label="难度：中" />
              <el-option value="高" label="难度：高" />
            </el-select>
            <el-select v-model="issueRepo" clearable filterable placeholder="按项目筛选 issue"
              class="repo-select" @change="resetIssuePage">
              <el-option v-for="r in issueRepoOptions" :key="r.full_name" :value="r.full_name"
                :label="`${r.full_name}（${r.issue_count}）`" />
            </el-select>
            <el-checkbox v-model="issueDeepOnly" @change="resetIssuePage">只看已深读</el-checkbox>
            <span class="picked-hint">技能：{{ (config?.user_skills || []).slice(0, 5).join(' / ') || '（.env 配置 USER_SKILLS）' }}</span>
          </div>

          <el-table :data="issues" v-loading="issueLoading" row-key="id" stripe>
            <el-table-column label="匹配度" width="150" sortable :sort-by="'effective_score'">
              <template #default="{ row }">
                <div class="match-cell">
                  <el-progress :percentage="Math.min(row.effective_score, 100)" :stroke-width="10"
                    :color="matchColor(row.effective_score)" class="match-bar" />
                  <span class="match-num">{{ row.effective_score }}</span>
                </div>
                <el-tag v-if="row.match_score != null" type="success" size="small">LLM 评分</el-tag>
                <el-tag v-else type="info" size="small">规则预估</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="Issue" min-width="320">
              <template #default="{ row }">
                <a :href="row.url" target="_blank" class="repo-name">{{ row.title }}</a>
                <div class="repo-desc">
                  <span class="repo-attr">{{ row.repo }} #{{ row.number }}</span>
                  <el-tag v-for="lb in row.labels.slice(0, 3)" :key="lb" size="small" effect="plain"
                    class="label-tag">{{ lb }}</el-tag>
                  <el-tag v-if="row.fixed_hint" type="warning" size="small" effect="plain" class="label-tag">⚠ 疑似已修复</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="难度" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.difficulty" size="small"
                  :type="row.difficulty === '低' ? 'success' : row.difficulty === '高' ? 'danger' : 'warning'">
                  {{ row.difficulty }}</el-tag>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="说了什么事 · 你要做什么" min-width="300">
              <template #default="{ row }">
                <div v-if="row.summary || row.action">
                  <div class="issue-summary">{{ row.summary }}</div>
                  <div v-if="row.action" class="issue-action">👉 {{ row.action }}</div>
                </div>
                <div v-else-if="row.body_excerpt" class="muted body-cut">{{ row.body_excerpt.slice(0, 90) }}…</div>
                <div v-else class="muted">刷新时会为高分 issue 自动生成摘要</div>
              </template>
            </el-table-column>
            <el-table-column label="为什么适合你" min-width="220">
              <template #default="{ row }">
                <span v-if="row.fit_reason">{{ row.fit_reason }}</span>
                <span v-else-if="row.screen_reason" class="muted">{{ row.screen_reason }}</span>
                <span v-else class="muted">运行「分析贡献机会」后由 LLM 精析</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag v-if="row.deep_read" type="success" size="small">已深读</el-tag>
                <el-tag v-else type="info" size="small">已预筛</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="AI" width="56">
              <template #default="{ row }">
                <el-tooltip content="把该 issue 上下文预填进顶部 AI 命令栏" placement="top">
                  <el-button link type="warning" size="small" @click="aiIssueCmd(row)">✨</el-button>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="学习" width="130">
              <template #default="{ row }">
                <el-tag v-if="row.learning_status === 'done'" type="success" size="small">✅ 已完成</el-tag>
                <el-tag v-else-if="row.learning_status === 'learning'" type="primary" size="small">📖 学习中</el-tag>
                <el-tooltip v-else content="复制后在 Claude Code 中运行 /tech <issue_id> 生成课程" placement="top">
                  <el-button link type="primary" size="small" @click="copyTech(row)">生成课程</el-button>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>

          <div class="pager">
            <el-pagination v-model:current-page="issuePage" v-model:page-size="issuePageSize"
              :total="issueTotal" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
              @current-change="loadIssues" @size-change="resetIssuePage" />
          </div>
        </el-tab-pane>

        <!-- ================= 行业洞察 ================= -->
        <el-tab-pane name="industries">
          <template #label>
            <span class="tab-label">🧭 行业洞察</span>
          </template>

          <el-alert type="info" :closable="false" show-icon class="task-alert"
            title="输入行业/方向词，LLM 规划关键词 → GitHub 检索 + 代表项目解析 → 生成行业开源格局报告；项目入库并打上行业标签，已有项目也会自动匹配" />

          <div class="toolbar">
            <el-input v-model="industryInput" placeholder="行业 / 方向词，如：生成视频、向量数据库、AI 编程助手"
              clearable class="industry-input" @keyup.enter="runIndustry" />
            <el-button type="primary" :loading="industryRunning" @click="runIndustry">开始定向分析</el-button>
            <el-button :loading="tagging" @click="runAutoTag">一键给全部项目打标签</el-button>
            <span class="picked-hint">分析 2-5 分钟，进度见顶部面板</span>
          </div>

          <el-empty v-if="!industriesLoading && industries.length === 0"
            description="还没有行业分析——输入一个方向词（如「生成视频」），让 LLM 帮你摸清这个领域的开源格局" />

          <el-table v-else :data="industries" v-loading="industriesLoading" row-key="id" stripe>
            <el-table-column label="行业 / 方向" min-width="200">
              <template #default="{ row }">
                <a href="javascript:;" class="repo-name" @click="openIndustry(row.id)">{{ row.name }}</a>
                <div class="repo-desc">{{ (row.keywords || []).slice(0, 5).join(' · ') }}</div>
              </template>
            </el-table-column>
            <el-table-column label="项目数" width="90">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ row.project_count }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="过程统计" min-width="260">
              <template #default="{ row }">
                <span class="muted">
                  搜索 {{ row.stats?.searched || 0 }} · 代表项目 {{ row.stats?.flagship_resolved || 0 }}
                  · 已有项目命中 {{ row.stats?.tagged_existing || 0 }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="生成时间" width="170">
              <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openIndustry(row.id)">查看报告</el-button>
                <el-button link type="warning" @click="filterTag(row.name)">看项目</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ================= 学习 ================= -->
        <el-tab-pane name="learning">
          <template #label>
            <span class="tab-label">📚 学习</span>
          </template>

          <el-alert type="info" :closable="false" show-icon class="task-alert"
            title="在 Issue 榜点「生成课程」拿到 /tech 命令 → 在 Claude Code 中运行 → 课程出现在这里；每节 quiz 即时反馈并回传，全部提交后 issue 自动标记已完成" />

          <div class="toolbar">
            <el-button :loading="coursesLoading" @click="loadCourses">刷新课程</el-button>
            <span class="picked-hint">课程由 /tech 一次性生成，静态托管于 /courses</span>
          </div>

          <el-empty v-if="!coursesLoading && courses.length === 0"
            description="还没有课程——去 Issue 榜挑一个高分 issue，点「生成课程」开始" />

          <el-row :gutter="14">
            <el-col v-for="c in courses" :key="c.id" :span="8" class="course-col">
              <el-card shadow="hover" class="course-card">
                <div class="course-head">
                  <span class="course-title">{{ c.title }}</span>
                  <el-tag :type="c.status === 'done' ? 'success' : 'primary'" size="small">
                    {{ c.status === 'done' ? '✅ 已完成' : '📖 学习中' }}
                  </el-tag>
                </div>
                <div class="repo-desc course-meta">
                  <span class="repo-attr">{{ c.repo }} #{{ c.issue_number }}</span>{{ c.issue_title }}
                </div>
                <div class="course-lessons">
                  <div v-for="l in c.lessons" :key="l.lesson_id" class="lesson-row">
                    <span class="lesson-check">{{ l.submitted ? '✅' : '⬜' }}</span>
                    <span class="lesson-name">{{ l.title }}</span>
                    <span v-if="l.submitted" class="lesson-score">{{ l.score }}/{{ l.total }}</span>
                  </div>
                </div>
                <div class="course-actions">
                  <el-button type="primary" size="small"
                    @click="openCourse(c.id, `${c.done_lessons}/${c.total_lessons} 节 quiz 已完成`)">
                    打开课程（{{ c.done_lessons }}/{{ c.total_lessons }}）
                  </el-button>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </el-tab-pane>

        <!-- ================= 技能 ================= -->
        <el-tab-pane name="skills">
          <template #label>
            <span class="tab-label">🛠 技能</span>
          </template>

          <el-alert type="info" :closable="false" show-icon class="task-alert"
            title="无头调用 Claude Code 技能（claude -p）：技能来自项目 .claude/skills/ 与 ~/.claude/skills/，每次调用现读文件——新增或修改 SKILL.md 即时生效，无需重启本平台" />

          <div class="toolbar">
            <el-button :loading="skillsLoading" @click="loadSkills">刷新技能</el-button>
            <span class="picked-hint">执行走后台任务，进度见顶部提示，结果在下方「最近执行」查看</span>
          </div>

          <el-empty v-if="!skillsLoading && skills.length === 0"
            description="没有发现技能——在项目 .claude/skills/ 下建一个含 SKILL.md 的目录，保存后点「刷新技能」立刻可见" />

          <el-row :gutter="14">
            <el-col v-for="s in skills" :key="s.scope + '-' + s.name" :span="8" class="course-col">
              <el-card shadow="hover" class="course-card">
                <div class="course-head">
                  <span class="course-title">/{{ s.name }}</span>
                  <span>
                    <el-tag v-if="s.requires === 'local'" type="warning" size="small">🖥 需本地</el-tag>
                    <el-tag size="small" :type="s.scope === 'project' ? 'primary' : 'info'">
                      {{ s.scope === 'project' ? '项目级' : '全局' }}
                    </el-tag>
                  </span>
                </div>
                <div class="repo-desc skill-desc">{{ s.description }}</div>
                <div v-if="s.argument_hint" class="skill-hint">参数：{{ s.argument_hint }}</div>
                <div class="course-actions">
                  <el-tooltip :disabled="s.requires !== 'local'"
                    content="该技能要写本地文件：表单帮你组装命令，复制后到 Claude Code 里运行" placement="top">
                    <el-button type="primary" size="small" @click="openSkill(s)">运行</el-button>
                  </el-tooltip>
                </div>
              </el-card>
            </el-col>
          </el-row>

          <h3 class="skill-hist-title">最近执行</h3>
          <el-table :data="skillTasks" size="small" row-key="id" stripe>
            <el-table-column label="技能 / 命令" width="180">
              <template #default="{ row }">
                <span v-if="row.type === 'skill'">/{{ row.payload?.skill }}</span>
                <span v-else class="agent-prompt">🤖 {{ (row.payload?.prompt || '').slice(0, 30) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="参数" min-width="160">
              <template #default="{ row }"><span class="muted">{{ row.payload?.args || '—' }}</span></template>
            </el-table-column>
            <el-table-column label="状态" width="96">
              <template #default="{ row }">
                <el-tag size="small"
                  :type="row.status === 'success' ? 'success' : row.status === 'running' ? 'primary' : 'danger'">
                  {{ row.status === 'success' ? '成功' : row.status === 'running' ? '运行中' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度 / 错误" min-width="240">
              <template #default="{ row }">
                <span :class="row.status === 'failed' ? '' : 'muted'">{{ row.error || row.progress }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button v-if="row.payload?.result" link type="primary" size="small"
                  @click="showResult(row)">查看结果</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-main>

    <!-- 项目详情抽屉 -->
    <el-drawer v-model="detailVisible" :title="detail?.full_name" size="46%">
      <template v-if="detail">
        <div class="detail-stats">
          <el-tag>⭐ {{ detail.stars.toLocaleString() }}</el-tag>
          <el-tag v-if="periodLabel(detail.periods)" type="danger">{{ periodLabel(detail.periods) }}</el-tag>
          <el-tag v-if="detail.language" type="warning">{{ detail.language }}</el-tag>
          <el-tag v-if="detail.license" type="info">{{ detail.license }}</el-tag>
          <el-tag type="success">规则分 {{ detail.rule_score }}</el-tag>
          <el-tag type="danger">综合分 {{ detail.total_score }}</el-tag>
          <el-tag v-for="t in detail.tags || []" :key="t" effect="plain">{{ t }}</el-tag>
        </div>

        <h4>核心思想</h4>
        <p>{{ detail.core_idea || '（尚未 LLM 精析，配置 LLM 后刷新自动分析）' }}</p>

        <h4>企业落地场景</h4>
        <template v-if="detail.enterprise_cases && detail.enterprise_cases.length">
          <div v-for="(c, i) in detail.enterprise_cases" :key="i" class="case-item">
            <b>{{ c.company }}</b> — {{ c.scenario }}
            <div class="evidence">「{{ c.evidence }}」</div>
          </div>
        </template>
        <p v-else class="muted">无公开案例（只收录 README/官网明确声明的生产案例）</p>

        <h4>LLM 评分</h4>
        <div v-for="v in llmScoreList" :key="v.key" class="score-row">
          <span class="score-name">{{ v.label }}</span>
          <el-progress :percentage="v.score" :stroke-width="14" class="score-bar" />
          <span class="score-reason">{{ v.reason }}</span>
        </div>
        <p v-if="!llmScoreList.length" class="muted">未分析</p>

        <h4>规则评分明细</h4>
        <div v-for="v in ruleScoreList" :key="v.key" class="score-row">
          <span class="score-name">{{ v.label }}</span>
          <el-progress :percentage="v.score" :stroke-width="14" class="score-bar" />
          <span class="score-reason">{{ v.reason }}</span>
        </div>

        <template v-if="detail.report_md">
          <h4>AI 分析报告</h4>
          <pre class="result-pre">{{ detail.report_md }}</pre>
        </template>

        <div class="detail-actions">
          <el-button v-if="detail.latest_report" type="success" @click="openReport(detail.latest_report.id)">
            查看贡献报告
          </el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 贡献报告弹窗 -->
    <el-dialog v-model="reportVisible" :title="`贡献机会报告 · ${report?.repo || ''}`" width="72%" top="4vh">
      <template v-if="report">
        <div v-if="report.status === 'running'" class="muted">报告生成中…稍后重新打开</div>
        <template v-else>
          <el-card shadow="never" class="verdict">
            <h4>综合判断 {{ report.repo_verdict.worth_investing ? '✅ 值得投入' : '⛔ 建议观望' }}</h4>
            <p>{{ report.repo_verdict.verdict }}</p>
            <p><b>仓库健康度：</b>{{ report.repo_verdict.health }}</p>
            <p v-if="(report.repo_verdict.directions || []).length">
              <b>长期方向：</b>
              <el-tag v-for="d in report.repo_verdict.directions" :key="d" size="small" class="dir-tag">{{ d }}</el-tag>
            </p>
          </el-card>

          <el-card v-for="issue in report.issues" :key="issue.number" shadow="never" class="issue-card">
            <h4>
              <a :href="issue.url" target="_blank">#{{ issue.number }} {{ issue.title }}</a>
              <el-tag size="small"
                :type="issue.difficulty === '低' ? 'success' : issue.difficulty === '高' ? 'danger' : 'warning'"
                class="diff-tag">难度：{{ issue.difficulty }}</el-tag>
            </h4>
            <p><b>背景：</b>{{ issue.background }}</p>
            <p><b>为什么值得：</b>{{ issue.why_it_matters }}</p>
            <p><b>涉及模块：</b>{{ issue.modules }}</p>
            <p><b>切入方式：</b>{{ issue.approach }}</p>
            <p><b>为什么适合你：</b>{{ issue.fit_reason }}</p>
            <p v-if="issue.screen_reason" class="muted">筛选理由：{{ issue.screen_reason }}</p>
          </el-card>
        </template>
      </template>
    </el-dialog>

    <!-- 行业洞察报告弹窗：markdown 综述 + 按子方向分组的项目清单 -->
    <el-dialog v-model="industryVisible" :title="`行业洞察 · ${industryReport?.name || ''}`" width="72%" top="4vh">
      <template v-if="industryReport">
        <div class="detail-stats">
          <el-tag type="primary" size="small">项目 {{ industryReport.projects.length }}</el-tag>
          <el-tag v-for="k in (industryReport.keywords || []).slice(0, 4)" :key="k" size="small" effect="plain">
            {{ k }}
          </el-tag>
          <el-tag type="info" size="small">{{ industryReport.model }}</el-tag>
        </div>

        <div class="md-body" v-html="industryMdHtml"></div>

        <h4>项目清单（{{ industryReport.projects.length }}）</h4>
        <div v-for="(group, cat) in industryGroups" :key="cat" class="industry-group">
          <div class="industry-cat">{{ cat || '未分类' }}<span class="muted">（{{ group.length }}）</span></div>
          <div v-for="p in group" :key="p.full_name" class="industry-project">
            <a :href="`https://github.com/${p.full_name}`" target="_blank" class="repo-name">{{ p.full_name }}</a>
            <span class="muted industry-stars">⭐ {{ (p.stars || 0).toLocaleString() }}</span>
            <span class="industry-pos">{{ p.position }}</span>
            <el-button link type="primary" size="small" @click="openDetail({ full_name: p.full_name })">
              库内详情
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 技能运行参数对话框：声明了 arguments 的技能渲染结构化表单（把「执行中问用户」提前到提交前） -->
    <el-dialog v-model="skillDialog" :title="`运行 /${currentSkill?.name}`" width="560px">
      <p v-if="currentSkill" class="muted">{{ currentSkill.description }}</p>

      <template v-if="hasSkillForm">
        <div v-for="(def, key) in currentSkill.arguments" v-show="paramVisible(def)" :key="key" class="skill-field">
          <div class="skill-field-label">{{ def.label || key }}<span v-if="def.required" class="req">*</span></div>
          <el-select v-if="def.type === 'issue'" v-model="skillForm[key]" filterable :loading="skillIssueLoading"
            placeholder="搜索选择 issue（按匹配度取前 50）" @change="onIssueParamChange">
            <el-option v-for="i in skillIssueOptions" :key="i.id" :value="i.id"
              :label="`#${i.id} · ${i.repo}#${i.number} · ${i.title.slice(0, 30)}`" />
          </el-select>
          <el-radio-group v-else-if="def.type === 'select'" v-model="skillForm[key]" class="skill-radios">
            <el-radio v-for="o in def.options" :key="o.value" :value="o.value">{{ o.label }}</el-radio>
          </el-radio-group>
          <el-input v-else v-model="skillForm[key]" :placeholder="def.placeholder || ''" @keyup.enter="runSkill" />
        </div>
        <el-alert v-if="existingCourses.length" type="warning" :closable="false" class="skill-course-warn">
          <template #title>
            该 issue 已有 {{ existingCourses.length }} 门课程：《{{ existingCourses.map((c) => c.title).join('》《') }}》
          </template>
        </el-alert>
      </template>
      <el-input v-else v-model="skillArgs" :placeholder="currentSkill?.argument_hint || '参数（可空）'"
        @keyup.enter="runSkill" />

      <el-alert v-if="currentSkill?.requires === 'local'" type="info" :closable="false" class="skill-local-tip"
        title="该技能需要本地文件环境：下方组装好命令复制，到本项目的 Claude Code 里运行" />
      <el-alert v-if="copiedCmd" type="success" :closable="false" class="skill-local-tip"
        :title="`剪贴板不可用，请手动复制：${copiedCmd}`" />

      <template #footer>
        <el-button @click="skillDialog = false">取消</el-button>
        <el-button v-if="currentSkill?.requires === 'local'" type="primary" :disabled="!skillFormReady"
          @click="copySkillCommand">复制命令</el-button>
        <el-button v-else type="primary" :loading="invoking" :disabled="!skillFormReady"
          @click="runSkill">执行</el-button>
      </template>
    </el-dialog>

    <!-- 技能 / AI 命令结果对话框 -->
    <el-dialog v-model="resultDialog"
      :title="resultTask?.type === 'agent' ? 'AI 命令执行结果' : `/${resultTask?.payload?.skill} 执行结果`"
      width="72%" top="4vh">
      <template v-if="resultTask">
        <div class="detail-stats">
          <el-tag v-if="resultTask.payload?.result?.cost_usd != null" type="warning" size="small">
            成本 ${{ (resultTask.payload.result.cost_usd || 0).toFixed(4) }}
          </el-tag>
          <el-tag v-if="resultTask.payload?.result?.duration_ms != null" type="info" size="small">
            耗时 {{ Math.round((resultTask.payload.result.duration_ms || 0) / 1000) }}s
          </el-tag>
          <el-tag v-if="resultTask.payload?.result?.num_turns != null" size="small">
            {{ resultTask.payload.result.num_turns }} 轮
          </el-tag>
        </div>
        <pre class="result-pre">{{ resultTask.payload?.result?.result }}</pre>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getConfig, getCourses, getIndustry, getIndustries, getIssueRepos, getIssues, getRepo, getRepos,
  getReport, getSkills, getTags, getTask, getTasks, invokeSkill, postAnalyze, postAutoTag,
  postContribute, postIndustry, postRefresh, postTranslate, runAgent,
} from './api'

const activeTab = ref('repos')
const repos = ref([])
const issues = ref([])
const loading = ref(false)
const issueLoading = ref(false)
const sort = ref('total')
const q = ref('')
const periodFilter = ref('all')
// 分页 + 精析状态子tab + 标签筛选（全部走服务端，每页条数由后端保证）
const analyzedFilter = ref('all')
const repoPage = ref(1)
const repoPageSize = ref(20)
const repoTotal = ref(0)
const tagFilter = ref('')
const tagOptions = ref([])
const issueAnalyzed = ref('all')
const issuePage = ref(1)
const issuePageSize = ref(20)
const issueTotal = ref(0)
// 行业洞察
const industryInput = ref('')
const industryRunning = ref(false)
const industries = ref([])
const industriesLoading = ref(false)
const industryVisible = ref(false)
const industryReport = ref(null)
const tagging = ref(false)
const analyzing = ref(false)
const translating = ref(false)
const picked = ref([])
const config = ref(null)
const detailVisible = ref(false)
const detail = ref(null)
const reportVisible = ref(false)
const report = ref(null)
const refreshing = ref(false)
const contributing = ref(false)
// 进度面板当前展示的任务：自己提交的（定向轮询）或扫描到的运行中任务；结束后留在面板上显示摘要
const panelTask = ref(null)
const panelLogs = ref([])      // 面板任务的时间线（列表接口不带 logs，按需拉 /api/tasks/{id}）
const panelOpen = ref(false)
const logsBox = ref(null)      // 日志滚动容器（新增行自动滚底）
const tick = ref(0)            // 每秒自增，驱动「耗时」重算（Date.now 本身不是响应式的）
const issueSort = ref('match')
const issueDifficulty = ref('')
const issueDeepOnly = ref(false)
const issueRepo = ref('')
const issueRepoOptions = ref([])
const courses = ref([])
const coursesLoading = ref(false)
const skills = ref([])
const skillsLoading = ref(false)
const skillDialog = ref(false)
const currentSkill = ref(null)
const skillArgs = ref('')
// 结构化参数表单（frontmatter arguments 声明的技能用）：参数名 -> 值
const skillForm = ref({})
const skillIssueOptions = ref([])    // issue 下拉数据
const skillIssueLoading = ref(false)
const existingCourses = ref([])      // 所选 issue 的已有课程（决定 replace 选项是否出现）
const copiedCmd = ref('')            // 剪贴板被拒时兜底亮出命令
const invoking = ref(false)
const agentPrompt = ref('')
const agentRunning = ref(false)
const agentInput = ref(null)
const skillTasks = ref([])
const resultDialog = ref(false)
const resultTask = ref(null)
let pollTimer = null
let tickTimer = null
let debounceTimer = null

const SCORE_LABELS = {
  enterprise_potential: '企业落地潜力',
  match: '与我的匹配度',
  learning_value: '核心思想/学习价值',
  star_momentum: 'Star 增速',
  activity: '活跃度',
  maintenance: '维护健康度',
}

const llmScoreList = computed(() =>
  Object.entries(detail.value?.llm_scores || {}).map(([k, v]) => ({
    key: k, label: SCORE_LABELS[k] || k, score: Number(v?.score || 0), reason: v?.reason || '',
  })))
const ruleScoreList = computed(() =>
  Object.entries(detail.value?.rule_detail || {}).map(([k, v]) => ({
    key: k, label: SCORE_LABELS[k] || k, score: Number(v?.score || 0), reason: v?.reason || '',
  })))

function periodLabel(periods) {
  if (!periods || periods.length === 0) return ''
  if (periods.length > 1) return '双榜'
  return periods[0] === 'weekly' ? '周榜' : '月榜'
}

// ---------- 进度面板 ----------
const panelResult = computed(() => panelTask.value?.payload?.result || null)

/** SQLite 的 DateTime 列存的是 UTC，但序列化出来不带时区（"2026-09-14T02:50:07.357854"），
 *  Date.parse 会当成本地时间、耗时平白多出 8 小时——补个 Z 才是真实时刻。
 *  日志时间戳走 JSON 列（自带 +00:00），原样解析即可。*/
function parseUTC(s) {
  if (!s) return NaN
  return Date.parse(/[Zz]$|[+-]\d{2}:?\d{2}$/.test(s) ? s : `${s.replace(' ', 'T')}Z`)
}

function fmtDuration(sec) {
  if (!Number.isFinite(sec)) return ''
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  if (sec < 3600) return `${m}m${String(sec % 60).padStart(2, '0')}s`
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}m`
}

const elapsedText = computed(() => {
  void tick.value // 建立依赖：每秒重算一次未结束任务的耗时
  const t = panelTask.value
  if (!t?.created_at) return ''
  const end = t.finished_at ? parseUTC(t.finished_at) : Date.now()
  return fmtDuration(Math.max(0, Math.round((end - parseUTC(t.created_at)) / 1000)))
})

const logLines = computed(() => (panelLogs.value || []).map((l) => {
  const ms = parseUTC(l.t)
  return { t: Number.isNaN(ms) ? '' : new Date(ms).toLocaleTimeString('zh-CN', { hour12: false }), msg: l.msg }
}))

async function scrollLogsBottom() {
  await nextTick()
  const el = logsBox.value
  if (el) el.scrollTop = el.scrollHeight
}
watch([() => panelOpen.value, () => panelLogs.value.length], scrollLogsBottom)

function statusLabel(s) {
  return s === 'success' ? '已完成' : s === 'running' ? '运行中' : '失败'
}

const TASK_TYPE_LABELS = {
  refresh: '刷新榜单',
  contribution: '贡献分析',
  industry: '定向行业分析',
  tagging: '项目自动打标',
  analyze: '批量精析',
  translate: '中文简介翻译',
}

/** 面板头部标识任务本身：连发多条时面板会在任务间切换（前一个结束就接手下一个运行中的），
 *  只显示进度行会让人以为同一件事在反复横跳。*/
function panelLabel(t) {
  if (!t) return ''
  if (t.type === 'agent') return `🤖 ${(t.payload?.prompt || 'AI 命令').slice(0, 30)}`
  if (t.type === 'skill') return `/${t.payload?.skill || '技能'} ${t.payload?.args || ''}`.trim()
  if (t.type === 'industry') return `🧭 行业分析 · ${t.payload?.args?.[0] || ''}`
  if (t.type === 'analyze') return `🔬 批量精析 ${((t.payload?.args?.[0] || '').match(/\d+/g) || []).length} 个项目`
  return TASK_TYPE_LABELS[t.type] || t.type
}

function statusTag(s) {
  return s === 'success' ? 'success' : s === 'running' ? 'primary' : 'danger'
}

function togglePanel() {
  if (panelLogs.value.length) panelOpen.value = !panelOpen.value // 无时间线可展开（如刷新任务）
}

function closePanel() {
  panelTask.value = null
  panelLogs.value = []
  panelOpen.value = false
}

/** 拉某个任务的最新状态与时间线；返回是否拉取成功（失败多为服务重启后记录丢失）。 */
async function syncLogs(taskId) {
  try {
    const task = (await getTask(taskId)).task
    if (panelTask.value?.id !== taskId) return true // 焦点已被别的入口接管，别覆盖
    panelTask.value = task
    panelLogs.value = task.logs || []
    return true
  } catch {
    return false
  }
}

/** 提交后立即占位 + 定向轮询该任务（1s）：长任务的时间线要秒级可见。
 *  结束后交给 onDone 回退到通用扫描（并发任务/别的入口提交的任务仍由扫描兜住）。*/
function focusTask(taskId, onDone) {
  stopPolling() // 暂停通用扫描，避免两个轮询抢同一个面板
  panelTask.value = {
    id: taskId, status: 'running', progress: '已提交，等待启动…', payload: {},
    created_at: new Date().toISOString(),
  }
  panelLogs.value = []
  panelOpen.value = true
  let fails = 0
  const onTick = async () => {
    if (panelTask.value?.id !== taskId) return stopPolling()
    if (await syncLogs(taskId)) {
      fails = 0
      if (panelTask.value?.status !== 'running') {
        stopPolling()
        onDone?.()
      }
    } else if (++fails >= 5) {
      stopPolling() // 连续查不到（服务重启后记录没了），别无限轮询
      onDone?.()
    }
  }
  onTick()
  pollTimer = setInterval(onTick, 1000)
}

function scoreType(v) {
  if (v >= 70) return 'success'
  if (v >= 40) return 'warning'
  return 'info'
}

function matchColor(v) {
  if (v >= 70) return '#67c23a'
  if (v >= 40) return '#e6a23c'
  return '#909399'
}

async function loadRepos() {
  loading.value = true
  try {
    const data = await getRepos({
      sort: sort.value,
      q: q.value,
      analyzed: analyzedFilter.value,
      period: periodFilter.value !== 'all' ? periodFilter.value : '',
      tag: tagFilter.value,
      limit: repoPageSize.value,
      offset: (repoPage.value - 1) * repoPageSize.value,
    })
    repos.value = data.repos
    repoTotal.value = data.total
  } catch (e) {
    ElMessage.error(`加载榜单失败：${e.message}`)
  } finally {
    loading.value = false
  }
}

/** 筛选条件变化：回第 1 页再拉（不然停在第 5 页可能直接翻空） */
function resetRepoPage() {
  repoPage.value = 1
  loadRepos()
}

async function loadIssues() {
  issueLoading.value = true
  try {
    const data = await getIssues({
      sort: issueSort.value,
      difficulty: issueDifficulty.value,
      repo: issueRepo.value,
      deep_only: issueDeepOnly.value,
      analyzed: issueAnalyzed.value,
      limit: issuePageSize.value,
      offset: (issuePage.value - 1) * issuePageSize.value,
    })
    issues.value = data.issues
    issueTotal.value = data.total
  } catch (e) {
    ElMessage.error(`加载 Issue 榜失败：${e.message}`)
  } finally {
    issueLoading.value = false
  }
}

function resetIssuePage() {
  issuePage.value = 1
  loadIssues()
}

async function loadIssueRepos() {
  try {
    issueRepoOptions.value = (await getIssueRepos()).repos
  } catch { /* 忽略：筛选器加载失败不阻塞榜单 */ }
}

function debouncedLoad() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(resetRepoPage, 300)
}

// ---------- 标签 / 行业洞察 ----------

async function loadTags() {
  try {
    tagOptions.value = (await getTags()).tags
  } catch { /* 忽略：标签加载失败不阻塞榜单 */ }
}

/** 行内标签点击 → 项目榜按该标签筛选并跳过去 */
function filterTag(tag) {
  activeTab.value = 'repos'
  tagFilter.value = tag
  resetRepoPage()
}

async function loadIndustries() {
  industriesLoading.value = true
  try {
    industries.value = (await getIndustries()).industries
  } catch (e) {
    ElMessage.error(`加载行业报告失败：${e.message}`)
  } finally {
    industriesLoading.value = false
  }
}

async function runIndustry() {
  const name = industryInput.value.trim()
  if (!name) return
  industryRunning.value = true
  try {
    const { task_id: taskId } = await postIndustry(name)
    ElMessage.success(`「${name}」定向分析已提交，进度见顶部面板`)
    industryInput.value = ''
    focusTask(taskId, () => {
      loadIndustries()
      loadTags()
      if (activeTab.value === 'repos') loadRepos()
      startPolling()
    })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    industryRunning.value = false
  }
}

async function runAutoTag() {
  tagging.value = true
  try {
    const { task_id: taskId } = await postAutoTag()
    ElMessage.success('自动分类已提交，LLM 会先提分类体系再逐批打标签')
    focusTask(taskId, () => {
      loadTags()
      if (activeTab.value === 'repos') loadRepos()
      startPolling()
    })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    tagging.value = false
  }
}

async function openIndustry(id) {
  try {
    industryReport.value = await getIndustry(id)
    industryVisible.value = true
  } catch (e) {
    ElMessage.error(`加载报告失败：${e.message}`)
  }
}

/** 报告项目按子方向分组（保持出现顺序） */
const industryGroups = computed(() => {
  const groups = {}
  for (const p of industryReport.value?.projects || []) {
    const cat = p.category || '未分类'
    ;(groups[cat] = groups[cat] || []).push(p)
  }
  return groups
})

// 极简 markdown 渲染（标题/列表/粗体/链接），内容来自自家 LLM 报告，先转义再替换防注入
function mdToHtml(md = '') {
  const inline = (s) => s
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank">$1</a>')
  const out = []
  let inList = false
  for (const raw of String(md).split(/\r?\n/)) {
    const line = raw
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    const h = line.match(/^(#{1,4})\s+(.*)$/)
    const li = line.match(/^\s*[-*]\s+(.*)$/)
    if (li) {
      if (!inList) { out.push('<ul>'); inList = true }
      out.push(`<li>${inline(li[1])}</li>`)
      continue
    }
    if (inList) { out.push('</ul>'); inList = false }
    if (h) {
      const lvl = Math.min(h[1].length + 2, 5)
      out.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`)
    } else if (line.trim()) {
      out.push(`<p>${inline(line)}</p>`)
    }
  }
  if (inList) out.push('</ul>')
  return out.join('\n')
}

const industryMdHtml = computed(() => mdToHtml(industryReport.value?.overview_md || ''))

function fmtTime(iso) {
  if (!iso) return ''
  const ms = Date.parse(/[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso.replace(' ', 'T')}Z`)
  return Number.isNaN(ms) ? '' : new Date(ms).toLocaleString('zh-CN', { hour12: false })
}

async function analyzeSelected() {
  analyzing.value = true
  try {
    const { task_id: taskId } = await postAnalyze(picked.value)
    ElMessage.success(`已提交 ${picked.value.length} 个项目的 LLM 精析，完成后切「已精析」查看`)
    focusTask(taskId, () => { loadRepos(); startPolling(loadRepos) })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    analyzing.value = false
  }
}

async function runTranslate() {
  translating.value = true
  try {
    const { task_id: taskId } = await postTranslate()
    ElMessage.success('中文简介翻译已提交：已是中文的直接回填，其余由 LLM 翻译提炼')
    focusTask(taskId, () => { loadRepos(); startPolling(loadRepos) })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    translating.value = false
  }
}

async function loadCourses() {
  coursesLoading.value = true
  try {
    courses.value = (await getCourses()).courses
  } catch (e) {
    ElMessage.error(`加载课程失败：${e.message}`)
  } finally {
    coursesLoading.value = false
  }
}

async function copyTech(row) {
  const cmd = `/tech ${row.id}`
  try {
    await navigator.clipboard.writeText(cmd)
    ElMessage.success(`已复制「${cmd}」，到 Claude Code 中运行即可生成课程`)
  } catch {
    ElMessage.info(`请手动运行：${cmd}`)
  }
}

function openCourse(id, hint) {
  window.open(`/courses/${id}/index.html`, '_blank')
  if (hint) ElMessage.info(hint)
}

// ---------- AI 命令栏 ----------
function prefillAgent(text) {
  agentPrompt.value = text
  agentInput.value?.focus()
}

// 行内预填：把该行的关键数据内联进指令，AI 无需再查即有上下文
function aiRepoCmd(row) {
  prefillAgent(`分析 ${row.full_name}（语言 ${row.language || '未知'}，⭐${row.stars.toLocaleString()}，综合分 ${row.total_score}）：`)
}

function aiIssueCmd(row) {
  prefillAgent(`分析 issue #${row.id}（${row.title.slice(0, 60)}，难度 ${row.difficulty || '未知'}，匹配度 ${row.effective_score}）：`)
}

async function runAgentCmd() {
  const prompt = agentPrompt.value.trim()
  if (!prompt) return
  agentRunning.value = true
  try {
    const { task_id: taskId } = await runAgent(prompt)
    ElMessage.success('AI 命令已提交，进度见顶部面板，结果完成后在「🛠 技能 · 最近执行」查看')
    agentPrompt.value = ''
    loadSkillTasks()
    focusTask(taskId, () => { loadSkillTasks(); startPolling(loadSkillTasks) })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    agentRunning.value = false
  }
}

// ---------- 技能调用 ----------
async function loadSkills() {
  skillsLoading.value = true
  try {
    skills.value = (await getSkills()).skills // 每次现拉：新增技能保存后点刷新立即可见
  } catch (e) {
    ElMessage.error(`加载技能失败：${e.message}`)
  } finally {
    skillsLoading.value = false
  }
}

async function loadSkillTasks() {
  try {
    skillTasks.value = (await getTasks(30)).tasks.filter((t) => t.type === 'skill' || t.type === 'agent')
  } catch { /* 忽略 */ }
}

function openSkill(s) {
  currentSkill.value = s
  skillArgs.value = ''
  copiedCmd.value = ''
  existingCourses.value = []
  skillForm.value = {}
  // 单选参数默认取第一项（/tech 的「另起新课」是更安全的默认）
  for (const [key, def] of Object.entries(s.arguments || {})) {
    if (def.type === 'select') skillForm.value[key] = def.options?.[0]?.value ?? ''
  }
  if ([...Object.values(s.arguments || {})].some((d) => d.type === 'issue')) loadIssueOptions()
  skillDialog.value = true
}

// ---------- 结构化参数表单 ----------
const hasSkillForm = computed(() => Object.keys(currentSkill.value?.arguments || {}).length > 0)

function paramVisible(def) {
  // 目前唯一的条件：所选 issue 已有课程（/tech 的覆盖选择）。新增条件在这里扩展
  if (def.visible_if === 'existing_course') return existingCourses.value.length > 0
  return true
}

const skillArgsBuilt = computed(() => {
  const args = currentSkill.value?.arguments
  if (!hasSkillForm.value) return skillArgs.value
  return Object.entries(args)
    .filter(([, def]) => paramVisible(def))
    .map(([key]) => String(skillForm.value[key] ?? '').trim())
    .filter(Boolean)
    .join(' ')
})

const skillFormReady = computed(() => {
  if (!hasSkillForm.value) return true
  const args = currentSkill.value.arguments
  return Object.entries(args).every(([key, def]) =>
    !paramVisible(def) || !def.required || String(skillForm.value[key] ?? '').trim() !== '')
})

async function loadIssueOptions() {
  skillIssueLoading.value = true
  try {
    skillIssueOptions.value = (await getIssues({ sort: 'match', deep_only: true, limit: 50 })).issues
  } catch (e) {
    ElMessage.error(`加载 issue 列表失败：${e.message}`)
  } finally {
    skillIssueLoading.value = false
  }
}

async function onIssueParamChange() {
  existingCourses.value = []
  const id = Number(skillForm.value.issue_id)
  if (id) {
    try {
      existingCourses.value = (await getCourses()).courses.filter((c) => c.issue_id === id)
    } catch { /* 查不到就当作没有旧课：条件字段不显示 */ }
  }
  if (!existingCourses.value.length) {
    // 条件字段隐藏时清掉值，避免看不见的选择泄漏进 args（先选有旧课的 issue 再换没旧的）
    for (const [key, def] of Object.entries(currentSkill.value?.arguments || {})) {
      if (def.visible_if) skillForm.value[key] = def.type === 'select' ? (def.options?.[0]?.value ?? '') : ''
    }
  }
}

/** local 技能 SDK 跑不了，表单的价值是组装命令；复制到剪贴板去 Claude Code 里跑。 */
async function copySkillCommand() {
  const cmd = `/${currentSkill.value.name} ${skillArgsBuilt.value}`.trim()
  try {
    await navigator.clipboard.writeText(cmd)
    ElMessage.success(`已复制：${cmd}（到 Claude Code 里运行）`)
    skillDialog.value = false
  } catch {
    copiedCmd.value = cmd
  }
}

async function runSkill() {
  invoking.value = true
  try {
    const { task_id: taskId } = await invokeSkill(currentSkill.value.name, skillArgsBuilt.value)
    ElMessage.success(`技能 /${currentSkill.value.name} 已提交，进度见顶部面板`)
    skillDialog.value = false
    loadSkillTasks()
    focusTask(taskId, () => { loadSkillTasks(); startPolling(loadSkillTasks) })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    invoking.value = false
  }
}

function showResult(t) {
  resultTask.value = t
  resultDialog.value = true
}

function onSelect(rows) {
  picked.value = rows.map((r) => r.id)
}

async function refresh() {
  refreshing.value = true
  try {
    await postRefresh()
    ElMessage.success('刷新任务已提交')
    startPolling(() => { loadRepos(); if (activeTab.value === 'issues') loadIssues() })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    refreshing.value = false
  }
}

async function analyzeContribution() {
  contributing.value = true
  try {
    await postContribute(picked.value)
    ElMessage.success('贡献分析任务已提交，完成后可在 Issue 榜和贡献报告查看')
    startPolling(() => { loadRepos(); if (activeTab.value === 'issues') loadIssues() })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    contributing.value = false
  }
}

async function openDetail(row) {
  detail.value = await getRepo(row.full_name)
  detailVisible.value = true
}

async function openReport(id) {
  report.value = await getReport(id)
  reportVisible.value = true
}

async function pollOnce() {
  try {
    const tasks = (await getTasks(5)).tasks
    const running = tasks.find((t) => t.status === 'running') || null
    if (running) {
      panelTask.value = running
      await syncLogs(running.id) // 列表不带 logs：刷新页面后靠这一下补回时间线并持续滚动
      return false
    }
    stopPolling()
    // 刚结束：再拉一次拿终态与最后一行日志（进度行本身可能是「处理中…」）；已结束的旧任务不覆盖
    if (panelTask.value?.status === 'running') await syncLogs(panelTask.value.id)
    return true
  } catch { /* 忽略轮询错误 */ }
  return false
}

function startPolling(onDone) {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (await pollOnce()) onDone?.()
  }, 3000)
  pollOnce()
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

watch(activeTab, (tab) => {
  if (tab === 'issues' && issues.value.length === 0) loadIssues()
  if (tab === 'issues') loadIssueRepos() // 每次进入都刷新：贡献分析可能新增了有 issue 的项目
  if (tab === 'industries') { loadIndustries(); loadTags() } // 报告与标签都可能被新任务更新
  if (tab === 'learning') loadCourses() // 每次进入都刷新，/tech 生成后能看到新课程
  if (tab === 'skills') { loadSkills(); loadSkillTasks() }
})

onMounted(async () => {
  await loadRepos()
  config.value = await getConfig().catch(() => null)
  loadTags()
  startPolling() // 扫描到运行中任务就持续跟（刷新页面后进度继续动）；没有任务时 pollOnce 自己停表
  tickTimer = setInterval(() => tick.value++, 1000)
})
onBeforeUnmount(() => {
  stopPolling()
  if (tickTimer) clearInterval(tickTimer)
})
</script>

<style>
body { margin: 0; background: #f6f8fa; font-family: system-ui, 'Microsoft YaHei', sans-serif; }
.layout { min-height: 100vh; }
.header { display: flex; align-items: center; justify-content: space-between; background: #fff; border-bottom: 1px solid #e5e9ef; }
.brand .logo { font-size: 20px; font-weight: 700; }
.brand .sub { margin-left: 12px; color: #8a919f; font-size: 13px; }
.ops { display: flex; align-items: center; }
.cfg-tag { margin-right: 8px; }
.main-tabs .el-tabs__header { background: #fff; padding: 0 8px; margin-bottom: 14px; border-radius: 6px; }
.tab-label { font-size: 15px; font-weight: 600; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.search { width: 240px; }
.diff-select { width: 130px; }
.repo-select { width: 250px; }
.picked-hint { color: #8a919f; font-size: 13px; margin-left: auto; }
.task-alert { margin-bottom: 14px; }
.task-panel { background: #fff; border: 1px solid #e5e9ef; border-radius: 6px; margin-bottom: 14px; overflow: hidden; }
.task-head { display: flex; align-items: center; gap: 10px; padding: 9px 14px; cursor: pointer; }
.task-what { flex-shrink: 0; max-width: 280px; padding-right: 10px; border-right: 1px solid #eef1f5; color: #8a919f; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-msg { flex: 1; font-size: 13px; color: #24292f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-err { color: #f56c6c; }
.task-elapsed { flex-shrink: 0; color: #8a919f; font-size: 12px; font-variant-numeric: tabular-nums; }
.task-toggle { flex-shrink: 0; color: #a8b0bd; font-size: 11px; }
.task-logs { max-height: 260px; overflow-y: auto; background: #fbfcfd; border-top: 1px solid #eef1f5; padding: 8px 14px; }
.log-line { font-family: Consolas, 'SFMono-Regular', Menlo, monospace; font-size: 12px; line-height: 1.7; color: #24292f; word-break: break-word; }
.log-time { margin-right: 8px; color: #a8b0bd; }
.task-foot { display: flex; align-items: center; gap: 12px; padding: 5px 14px; border-top: 1px solid #eef1f5; font-size: 12px; }
.repo-title { display: flex; align-items: center; gap: 8px; }
.repo-name { font-weight: 600; color: #24292f; text-decoration: none; }
.repo-name:hover { color: #409eff; }
.repo-desc { color: #8a919f; font-size: 12px; margin-top: 2px; }
.repo-attr { color: #409eff; margin-right: 8px; }
.label-tag { margin-right: 4px; }
.issue-summary { font-size: 13px; color: #24292f; }
.issue-action { font-size: 12px; color: #b88230; margin-top: 4px; }
.body-cut { font-size: 12px; }
.match-cell { display: flex; align-items: center; gap: 8px; }
.match-bar { width: 90px; }
.match-num { font-weight: 700; }
.detail-stats { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
h4 { margin: 18px 0 8px; }
.case-item { padding: 8px 12px; background: #f6f8fa; border-radius: 6px; margin-bottom: 8px; }
.evidence { color: #8a919f; font-size: 12px; margin-top: 4px; }
.muted { color: #8a919f; }
.score-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.score-name { width: 130px; font-size: 13px; flex-shrink: 0; }
.score-bar { flex: 0 0 160px; }
.score-reason { font-size: 12px; color: #8a919f; }
.verdict { margin-bottom: 12px; }
.issue-card { margin-bottom: 12px; }
.diff-tag { margin-left: 10px; }
.dir-tag { margin-right: 6px; }
.detail-actions { margin-top: 20px; }
.course-col { margin-bottom: 14px; }
.course-card { height: 100%; }
.course-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.course-title { font-weight: 700; font-size: 15px; line-height: 1.4; }
.course-meta { margin: 6px 0 10px; }
.course-lessons { border-top: 1px dashed #e5e9ef; padding-top: 8px; margin-bottom: 12px; }
.lesson-row { display: flex; align-items: center; gap: 6px; padding: 3px 0; font-size: 13px; }
.lesson-check { flex-shrink: 0; }
.lesson-name { flex: 1; color: #24292f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lesson-score { color: #67c23a; font-weight: 600; font-size: 12px; flex-shrink: 0; }
.course-actions { text-align: right; }
.skill-desc { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; min-height: 3.2em; }
.skill-hint { font-size: 12px; color: #b88230; margin-bottom: 10px; }
.skill-field { margin-bottom: 14px; }
.skill-field-label { font-size: 13px; color: #24292f; margin-bottom: 6px; }
.skill-field-label .req { color: #f56c6c; margin-left: 2px; }
.skill-radios { display: flex; flex-direction: column; gap: 4px; align-items: normal; }
.skill-radios .el-radio { margin-right: 0; height: auto; white-space: normal; }
.skill-course-warn { margin-top: 2px; }
.skill-local-tip { margin-top: 12px; }
.skill-hist-title { margin: 22px 0 10px; }
.result-pre {
  white-space: pre-wrap;
  word-break: break-word;
  background: #f6f8fa;
  border-radius: 6px;
  padding: 14px 16px;
  font-size: 13px;
  font-family: Consolas, 'SFMono-Regular', Menlo, monospace;
  max-height: 60vh;
  overflow-y: auto;
}
.ai-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fff;
  border: 1px solid #e5e9ef;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 14px;
}
.ai-bar-logo { font-size: 18px; }
.ai-input { flex: 1; }
.agent-prompt { color: #b88230; font-size: 13px; }

/* 分页 */
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
.tag-select { width: 160px; }

/* 行内标签 / 行业洞察 */
.zh-desc { font-size: 12px; color: #4a5160; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.5; }
.repo-tags { margin-top: 4px; }
.tag-chip { margin-right: 4px; cursor: pointer; }
.industry-input { width: 320px; }
.industry-group { margin-bottom: 14px; }
.industry-cat { font-weight: 600; font-size: 14px; margin-bottom: 6px; padding: 4px 10px; background: #f6f8fa; border-left: 3px solid #409eff; border-radius: 3px; }
.industry-project { display: flex; align-items: center; gap: 10px; padding: 5px 12px; font-size: 13px; }
.industry-project:hover { background: #fbfcfd; }
.industry-stars { flex-shrink: 0; font-size: 12px; }
.industry-pos { flex: 1; color: #8a919f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 行业报告 markdown 正文（自家 LLM 产出，前端已转义防注入） */
.md-body { font-size: 14px; line-height: 1.8; color: #24292f; margin-bottom: 8px; }
.md-body h3, .md-body h4, .md-body h5 { margin: 16px 0 8px; }
.md-body p { margin: 8px 0; }
.md-body ul { margin: 8px 0; padding-left: 22px; }
.md-body a { color: #409eff; }
</style>

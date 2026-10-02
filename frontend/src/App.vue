<template>
  <el-container class="layout">
    <el-header class="header">
      <div class="brand">
        <svg class="brand-mark" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <g stroke="currentColor" stroke-width="1.35" stroke-linecap="round">
            <path d="M12 1.6v20.8M2.9 6.9l18.2 10.2M21.1 6.9L2.9 17.1" />
            <path d="M9.9 3.9L12 6l2.1-2.1M14.1 20.1L12 18l-2.1 2.1M2.5 10.2l2.9.6.6-2.9M21.5 13.8l-2.9-.6-.6 2.9M2.5 13.8l2.9-.6M21.5 10.2l-2.9.6" />
          </g>
        </svg>
        <div class="brand-text">
          <span class="brand-name">CELESTIAL&nbsp;SNOW</span>
          <span class="brand-sub">GITHUB TRENDING · 情报终端</span>
        </div>
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
        <span class="ai-glyph" aria-hidden="true">❯</span>
        <el-input ref="agentInput" v-model="agentPrompt" class="ai-input" clearable
          placeholder="告诉 AI 要做什么，如：分析 volcengine/OpenViking、给 issue #462 打分；也支持 /技能名 参数"
          @keyup.enter="runAgentCmd" />
        <el-button type="primary" :loading="agentRunning" @click="runAgentCmd">运行</el-button>
      </div>

      <el-tabs v-model="activeTab" class="main-tabs">
        <!-- ================= 项目榜 ================= -->
        <el-tab-pane name="repos">
          <template #label>
            <span class="tab-label"><i>01</i>项目榜</span>
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
            <el-select v-model="tagFilter" multiple clearable filterable collapse-tags collapse-tags-tooltip
              placeholder="标签（多选交集）" class="tag-select" @change="resetRepoPage">
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
            <el-table-column label="建立 / 活跃" width="125">
              <template #default="{ row }">
                <el-tooltip v-if="row.github_created_at || row.pushed_at" placement="top" :show-after="400">
                  <template #content>
                    <div>建立：{{ fmtTime(row.github_created_at) || '未知' }}</div>
                    <div>最近 push：{{ fmtTime(row.pushed_at) || '未知' }}</div>
                  </template>
                  <div>
                    <div class="repo-age">建于 {{ fmtAgo(row.github_created_at) }}</div>
                    <div class="repo-push" :class="{ stale: pushDays(row) > 90 }">push {{ fmtAgo(row.pushed_at) }}</div>
                  </div>
                </el-tooltip>
                <span v-else class="muted">—</span>
              </template>
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
            <span class="tab-label"><i>02</i>Issue 榜</span>
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
            <span class="tab-label"><i>03</i>行业洞察</span>
          </template>

          <el-alert type="info" :closable="false" show-icon class="task-alert"
            title="自由输入方向词和项目名（可混合），先解析确认再分析：方向 → LLM 调研开源格局并打行业标签；项目名 → 直接入库并入报告，项目名本身不会成为标签" />

          <div class="toolbar">
            <el-input v-model="industryInput" placeholder="方向词 + 项目名随意混输，如：agent运行时 pi agentScope-java deer-flow"
              clearable class="industry-input" @keyup.enter="runIndustry" />
            <el-button type="primary" :loading="industryParsing" @click="runIndustry">解析输入</el-button>
            <el-button :loading="tagging" @click="runAutoTag">一键给全部项目打标签</el-button>
            <span class="picked-hint">解析 2-5 秒，分析 2-5 分钟</span>
          </div>

          <el-dialog v-model="parseDialog" title="确认解析结果" width="680px">
            <div v-if="parseResult">
              <div class="parse-section">方向（勾选保留，标签经标签库归一）</div>
              <div v-for="d in parseResult.directions" :key="d.raw" class="parse-row">
                <el-checkbox v-model="d.keep" />
                <span class="parse-raw">{{ d.raw }}</span>
                <span class="muted">→</span>
                <el-tag size="small">{{ d.tag }}</el-tag>
              </div>
              <div v-if="!parseResult.directions.length" class="muted parse-row">（没有识别出方向）</div>
              <div class="parse-section">项目（点名入库并入报告；下拉可换定位到的仓库）</div>
              <div v-for="r in parseResult.repos" :key="r.raw" class="parse-row">
                <el-checkbox v-model="r.keep" :disabled="!r.candidates.length" />
                <span class="parse-raw">{{ r.raw }}</span>
                <el-select v-if="r.candidates.length" v-model="r.selected" filterable size="small"
                  class="parse-select" placeholder="选择仓库">
                  <el-option v-for="c in r.candidates" :key="c.full_name" :value="c.full_name"
                    :label="`${c.full_name}（⭐${(c.stars || 0).toLocaleString()}）`">
                    <span>{{ c.full_name }} ⭐{{ (c.stars || 0).toLocaleString() }}</span>
                    <span class="parse-cand-desc">{{ c.description }}</span>
                  </el-option>
                </el-select>
                <span v-else class="muted">未找到候选（将跳过）</span>
              </div>
              <div v-if="!parseResult.repos.length" class="muted parse-row">（没有识别出项目名）</div>
            </div>
            <template #footer>
              <el-button @click="parseDialog = false">取消</el-button>
              <el-button type="primary" :loading="industryRunning" @click="confirmIndustry">开始分析</el-button>
            </template>
          </el-dialog>

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
            <el-table-column label="操作" width="190" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openIndustry(row.id)">查看报告</el-button>
                <el-button link type="warning" @click="filterTag(row.name)">看项目</el-button>
                <el-button link type="danger" @click="removeIndustry(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ================= 脚手架 ================= -->
        <el-tab-pane name="scaffold">
          <template #label>
            <span class="tab-label"><i>04</i>脚手架</span>
          </template>

          <el-alert type="info" :closable="false" show-icon class="task-alert"
            title="一句话描述想做的系统 → 检索匹配开源框架（适配度%）→ 直接采用或拆成技术条目逐条选型 → 最终整合生成可启动的脚手架 zip（分期上线：当前为整体匹配）" />

          <div class="toolbar">
            <el-input v-model="scaffoldInput" placeholder="一句话需求，如：想做个流放之路洗装备的工具"
              clearable class="industry-input" @keyup.enter="runScaffold" />
            <el-button type="primary" :loading="scaffoldRunning" @click="runScaffold">开始匹配</el-button>
            <el-button :loading="scaffoldsLoading" @click="resetScaffoldPage">刷新</el-button>
            <span class="picked-hint">匹配约 30-60 秒，双轨评分（规则 + LLM 语义）</span>
          </div>

          <el-empty v-if="!scaffoldsLoading && scaffolds.length === 0"
            description="还没有需求——输入一句话，让平台帮你找现成的开源框架" />

          <el-table v-else :data="scaffolds" v-loading="scaffoldsLoading" row-key="id" stripe>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="scaffoldStatus(row.status).type" size="small">
                  {{ scaffoldStatus(row.status).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="需求（一句话）" min-width="300">
              <template #default="{ row }">
                <a href="javascript:;" class="repo-name" @click="openScaffold(row.id)">{{ row.raw_text }}</a>
                <div class="repo-desc">{{ row.domain || '（归纳中…）' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="最佳候选 / 进度" min-width="240">
              <template #default="{ row }">
                <template v-if="row.top_candidate">
                  <span class="repo-name">{{ row.top_candidate }}</span>
                  <el-tag size="small" :type="scoreType(row.top_fit)" class="scaffold-fit-tag">
                    适配 {{ row.top_fit }}
                  </el-tag>
                </template>
                <span v-else class="muted">{{ row.status === 'matching' ? '匹配中…' : '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="160">
              <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openScaffold(row.id)">
                  {{ row.status === 'matched' ? '查看候选' : row.status === 'done_adopt' ? '查看报告' : '继续' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pager">
            <el-pagination v-model:current-page="scaffoldPage" :page-size="scaffoldPageSize"
              :total="scaffoldTotal" layout="total, prev, pager, next"
              @current-change="loadScaffolds" />
          </div>
        </el-tab-pane>

        <!-- ================= 学习 ================= -->
        <el-tab-pane name="learning">
          <template #label>
            <span class="tab-label"><i>05</i>学习</span>
          </template>

          <el-alert type="info" :closable="false" show-icon class="task-alert"
            title="课程四种来源：Issue 榜「生成课程」（/tech）· 项目课（/tech-repo）· 教材课（上传 PDF → /tech-book）· 导入教程包；每节 quiz 即时反馈并回传，全部提交后自动标记已完成" />

          <div class="toolbar">
            <el-button :loading="coursesLoading" @click="loadCourses">刷新课程</el-button>
            <el-button type="primary" @click="openRepoCourseDialog">生成项目课程</el-button>
            <el-button type="primary" @click="openBooksDialog">教材书架</el-button>
            <el-button @click="openImportDialog">导入教程包</el-button>
            <span class="picked-hint">课程由技能一次性生成，静态托管于 /courses</span>
          </div>

          <el-empty v-if="!coursesLoading && courses.length === 0"
            description="还没有课程——从 Issue / 项目 / PDF 教材生成，或直接导入教程包" />

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
                  <template v-if="c.source_type === 'repo'">
                    <span class="repo-attr">📁 项目课</span>{{ c.repo }}
                  </template>
                  <template v-else-if="c.source_type === 'book'">
                    <span class="repo-attr">📖 教材课</span>{{ c.book_title || '（教材已删）' }}
                  </template>
                  <template v-else-if="c.source_type === 'import'">
                    <span class="repo-attr">📦 导入</span>{{ (c.created_at || '').slice(0, 10) }} 上传
                  </template>
                  <template v-else>
                    <span class="repo-attr">{{ c.repo }} #{{ c.issue_number }}</span>{{ c.issue_title }}
                  </template>
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
            <span class="tab-label"><i>06</i>技能</span>
          </template>

          <el-alert type="info" :closable="false" show-icon class="task-alert"
            title="技能来自项目 .claude/skills/ 与 ~/.claude/skills/，每次调用现读文件——新增或修改 SKILL.md 即时生效，无需重启本平台" />

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
                <el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
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

    <!-- 脚手架需求详情抽屉：按状态分态渲染（当前：matched 候选榜；拆条/选型/生成随 V2/V3 上线） -->
    <el-drawer v-model="scaffoldVisible" :title="`脚手架需求 #${scaffoldDetail?.id || ''}`" size="58%">
      <template v-if="scaffoldDetail">
        <div class="detail-stats">
          <el-tag :type="scaffoldStatus(scaffoldDetail.status).type">
            {{ scaffoldStatus(scaffoldDetail.status).label }}
          </el-tag>
          <el-tag v-if="scaffoldDetail.domain" effect="plain">{{ scaffoldDetail.domain }}</el-tag>
          <el-tag v-if="scaffoldDetail.candidate_count" type="info" size="small">
            候选 {{ scaffoldDetail.candidate_count }}
          </el-tag>
        </div>

        <p class="scaffold-raw">「{{ scaffoldDetail.raw_text }}」</p>

        <!-- 采用分支（终态）：clone 地址 + 评估报告 -->
        <template v-if="scaffoldDetail.status === 'done_adopt'">
          <h4>已采用</h4>
          <div class="adopt-box">
            <a :href="`https://github.com/${scaffoldDetail.adopt_repo}`" target="_blank" class="repo-name">
              {{ scaffoldDetail.adopt_repo }}
            </a>
            <el-input :model-value="adoptCloneUrl" readonly size="small" class="adopt-clone">
              <template #append>
                <el-button @click="copyText(adoptCloneUrl, 'clone 地址')">复制 clone</el-button>
              </template>
            </el-input>
          </div>
          <h4>评估报告</h4>
          <div class="md-body" v-html="adoptMdHtml"></div>
        </template>

        <template v-else-if="scaffoldDetail.need_brief?.summary">
          <h4>需求理解</h4>
          <p>{{ scaffoldDetail.need_brief.summary }}</p>
          <p v-if="(scaffoldDetail.need_brief.features || []).length">
            <b>核心功能：</b>
            <el-tag v-for="f in scaffoldDetail.need_brief.features" :key="f" size="small" effect="plain"
              class="label-tag">{{ f }}</el-tag>
          </p>
          <p v-if="scaffoldDetail.need_brief.scale"><b>规模：</b>{{ scaffoldDetail.need_brief.scale }}</p>
          <p v-if="(scaffoldDetail.need_brief.constraints || []).length" class="muted">
            约束：{{ scaffoldDetail.need_brief.constraints.join('；') }}
          </p>
        </template>

        <template v-if="(scaffoldDetail.framework_candidates || []).length
          && scaffoldDetail.status === 'matched'">
          <h4>候选框架（{{ scaffoldDetail.framework_candidates.length }}，按适配度降序）</h4>
          <el-table :data="scaffoldDetail.framework_candidates" size="small" row-key="full_name" stripe>
            <el-table-column label="适配度" width="150" sortable :sort-by="'fit_score'">
              <template #default="{ row }">
                <el-tooltip placement="top" :show-after="300">
                  <template #content>
                    <div>规则分（语言/关键词/活跃）：{{ row.rule_score }} / 40</div>
                    <div>LLM 语义分（需求 vs 定位）：{{ row.llm_score }} / 60</div>
                    <div v-if="row.rule_reason">{{ row.rule_reason }}</div>
                  </template>
                  <div class="match-cell">
                    <el-progress :percentage="Math.min(row.fit_score, 100)" :stroke-width="10"
                      :color="matchColor(row.fit_score)" class="match-bar" />
                    <span class="match-num">{{ row.fit_score }}</span>
                  </div>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="项目" min-width="280">
              <template #default="{ row }">
                <div class="repo-title">
                  <a :href="`https://github.com/${row.full_name}`" target="_blank" class="repo-name">
                    {{ row.full_name }}
                  </a>
                  <el-tag size="small" effect="plain">{{ row.language || '?' }}</el-tag>
                  <span class="muted">⭐ {{ (row.stars || 0).toLocaleString() }}</span>
                </div>
                <div class="repo-desc">{{ row.zh_desc || row.description }}</div>
              </template>
            </el-table-column>
            <el-table-column label="适配理由" min-width="220">
              <template #default="{ row }">
                <span v-if="row.reason">{{ row.reason }}</span>
                <span v-else class="muted">（LLM 评分未产出，仅规则分）</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button link type="success" :loading="adoptingRepo === row.full_name"
                  @click="adoptCandidate(row)">采用</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="detail-actions">
            <el-button :loading="scaffoldRematching" @click="rematchScaffoldRow">🔄 重新匹配（可改话）</el-button>
            <el-button type="warning" :loading="splittingScaffold" @click="runSplit">🔧 拆条继续</el-button>
          </div>
        </template>

        <!-- 拆条编辑面板：split 态 + selected 态的「改条目重选」都走这里 -->
        <template v-else-if="scaffoldDetail.status === 'split' || editingItems">
          <h4>技术条目（可增删改，确认后逐条选型开源组件）</h4>
          <div class="split-bar">
            <span class="muted">主技术栈：</span>
            <el-select v-model="splitStack" filterable allow-create size="small" class="stack-select"
              placeholder="选择或输入">
              <el-option v-for="s in STACK_OPTIONS" :key="s" :value="s" :label="s" />
            </el-select>
            <el-button size="small" @click="addSplitItem">＋ 添加条目</el-button>
            <el-tooltip content="重新让 LLM 拆解（会覆盖当前编辑；同一句话命中缓存秒出）" placement="top">
              <el-button size="small" :loading="splittingScaffold" @click="runSplit">🔄 重新拆条</el-button>
            </el-tooltip>
          </div>
          <div v-for="(it, i) in splitItems" :key="i" class="split-row">
            <span class="split-no">{{ i + 1 }}</span>
            <div class="split-fields">
              <div class="split-line1">
                <el-input v-model="it.name" size="small" placeholder="条目名（如：视觉识别）" class="split-name" />
                <el-input v-model="it.kw" size="small" placeholder="检索关键词（英文，逗号分隔）" class="split-kw" />
                <el-button link type="danger" size="small" @click="splitItems.splice(i, 1)">删除</el-button>
              </div>
              <el-input v-model="it.desc" size="small" placeholder="职责描述（做什么、怎么与其他条目配合）" />
            </div>
          </div>
          <div class="detail-actions">
            <el-button type="primary" :loading="scaffoldSelecting" @click="confirmItems">
              ✅ 确认并选型（{{ splitItems.length }} 条）
            </el-button>
          </div>
        </template>

        <!-- 条目选型面板：逐条勾一个候选或标自研（built 态点「改选型」也回到这里） -->
        <template v-else-if="scaffoldDetail.status === 'selected' || reselecting">
          <h4>逐条选型（每个条目选一个候选开源项目，或标自研）</h4>
          <div v-for="it in scaffoldDetail.items" :key="it.no" class="sel-item">
            <div class="sel-head">
              <b>{{ it.no }}. {{ it.name }}</b>
              <span class="muted sel-desc">{{ it.desc }}</span>
            </div>
            <el-radio-group v-model="selChoices[it.no]" class="sel-radios">
              <el-radio v-for="c in it.candidates || []" :key="c.full_name"
                :value="c.full_name" class="sel-radio">
                <a :href="`https://github.com/${c.full_name}`" target="_blank" class="repo-name"
                  @click.stop>{{ c.full_name }}</a>
                <el-tag size="small" :type="scoreType(c.fit_score)" class="scaffold-fit-tag">
                  {{ c.fit_score }}
                </el-tag>
                <span class="muted sel-reason">{{ c.reason }}</span>
              </el-radio>
              <el-radio :value="SELF_DEV" class="sel-radio">
                <span class="muted">🔧 自研（无合适开源，生成时从零写骨架）</span>
              </el-radio>
            </el-radio-group>
          </div>
          <div class="detail-actions">
            <el-button @click="startEditItems">✏️ 改条目重选</el-button>
            <el-button type="success" :disabled="!allChosen" :loading="scaffoldBuilding"
              @click="generateScaffold">🏗 生成脚手架</el-button>
          </div>
          <div v-if="!allChosen" class="muted">还有条目未选完（自研也算一种选择）。</div>
        </template>

        <!-- 生成完成：zip 下载 + 构建信息 + 重生成 -->
        <template v-else-if="scaffoldDetail.status === 'built' && scaffoldDetail.build?.zip_url">
          <h4>脚手架已生成</h4>
          <div class="detail-stats">
            <el-tag type="success">📦 {{ scaffoldDetail.build.file_count }} 个文件</el-tag>
            <el-tag type="info">{{ Math.round((scaffoldDetail.build.total_bytes || 0) / 1024) }} KB</el-tag>
            <el-tag v-if="scaffoldDetail.build.turns" type="warning">
              {{ scaffoldDetail.build.turns }} 轮 / ${{ (scaffoldDetail.build.cost_usd || 0).toFixed(2) }}
            </el-tag>
            <el-tag v-if="scaffoldDetail.build.cache_hit" type="primary">⚡ 产物缓存命中</el-tag>
          </div>
          <p v-if="scaffoldDetail.build.base">
            <b>base 主干：</b>
            <a :href="`https://github.com/${scaffoldDetail.build.base}`" target="_blank" class="repo-name">
              {{ scaffoldDetail.build.base }}
            </a>
            <span class="muted">（{{ scaffoldDetail.build.base_rationale }}）</span>
          </p>
          <p v-if="scaffoldDetail.build.mounting" class="muted">{{ scaffoldDetail.build.mounting }}</p>

          <h4>六件套清单</h4>
          <div class="six-list">
            <div v-for="f in sixFiles" :key="f" class="six-item">✅ {{ f }}</div>
          </div>
          <el-alert v-if="(scaffoldDetail.build.warnings || []).length" type="warning" :closable="false"
            class="task-alert">
            <template #title>
              License 提示：{{ scaffoldDetail.build.warnings.join('；') }}（自用不受影响，对外分发需注意）
            </template>
          </el-alert>

          <div class="detail-actions">
            <el-button type="primary" @click="downloadZip">⬇️ 下载 zip（{{ Math.round((scaffoldDetail.build.total_bytes || 0) / 1024) }} KB）</el-button>
            <el-button :loading="scaffoldBuilding" @click="generateScaffold">🔄 重新生成</el-button>
            <el-tooltip content="回到选型改组件后再生成；同组合会命中产物缓存不重跑" placement="top">
              <el-button @click="reselectScaffold">改选型</el-button>
            </el-tooltip>
          </div>
        </template>

        <div v-else-if="scaffoldDetail.status === 'building'">
          <!-- 任务失败不改 status（平台约定），需求停在 building——看任务行区分失败与进行中 -->
          <template v-if="scaffoldDetail.build_task?.status === 'failed'">
            <el-alert type="error" :closable="false" class="task-alert">
              <template #title>生成失败（可重试；重试会重新生成）</template>
              {{ scaffoldDetail.build_task.error || '未知原因，看任务时间线末尾' }}
            </el-alert>
            <div class="detail-actions">
              <el-button type="primary" :loading="scaffoldBuilding" @click="retryScaffoldBuild">
                🔄 重试生成
              </el-button>
              <el-button @click="reselectScaffold">改选型后再生成</el-button>
            </div>
          </template>
          <div v-else class="muted">
            Agent 生成进行中（写项目骨架 + 六件套，预计数分钟），进度见顶部任务面板，完成后
            <el-button link type="primary" @click="openScaffold(scaffoldDetail.id)">刷新</el-button>
          </div>
        </div>

        <div v-else-if="scaffoldDetail.status === 'selecting'" class="muted">
          条目选型进行中（每条目检索候选 + 双轨评分），任务完成后
          <el-button link type="primary" @click="openScaffold(scaffoldDetail.id)">刷新</el-button>
        </div>

        <div v-else-if="scaffoldDetail.status === 'matching'" class="muted">
          匹配进行中（LLM 归纳 + 双通道检索 + 双轨评分），任务完成后
          <el-button link type="primary" @click="openScaffold(scaffoldDetail.id)">刷新</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 技能运行参数对话框：声明了 arguments 的技能渲染结构化表单（把「执行中问用户」提前到提交前） -->    <el-dialog v-model="skillDialog" :title="`运行 /${currentSkill?.name}`" width="560px">
      <p v-if="currentSkill" class="muted">{{ currentSkill.description }}</p>

      <template v-if="hasSkillForm">
        <div v-for="(def, key) in currentSkill.arguments" v-show="paramVisible(def)" :key="key" class="skill-field">
          <div class="skill-field-label">{{ def.label || key }}<span v-if="def.required" class="req">*</span></div>
          <el-select v-if="def.type === 'issue'" v-model="skillForm[key]" filterable :loading="skillIssueLoading"
            placeholder="搜索选择 issue（按匹配度取前 50）" @change="onIssueParamChange">
            <el-option v-for="i in skillIssueOptions" :key="i.id" :value="i.id"
              :label="`#${i.id} · ${i.repo}#${i.number} · ${i.title.slice(0, 30)}`" />
          </el-select>
          <el-select v-else-if="def.type === 'repo'" v-model="skillForm[key]" filterable :loading="skillRepoLoading"
            placeholder="搜索选择项目（按总分取前 50）" @change="onRepoParamChange">
            <el-option v-for="r in skillRepoOptions" :key="r.id" :value="r.id"
              :label="`#${r.id} · ${r.full_name} · ${(r.zh_desc || r.description || '').slice(0, 24)}`" />
          </el-select>
          <el-select v-else-if="def.type === 'book'" v-model="skillForm[key]" filterable :loading="skillBookLoading"
            placeholder="选择教材（解析完成的）" @change="onBookParamChange">
            <el-option v-for="b in skillBookOptions" :key="b.id" :value="b.id"
              :label="`《${b.title || b.filename}》· ${b.pages} 页 · ${b.chapters} 章`" />
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
        <el-alert v-else-if="existingRepoCourses.length" type="warning" :closable="false" class="skill-course-warn">
          <template #title>
            该项目已有 {{ existingRepoCourses.length }} 门项目课：《{{ existingRepoCourses.map((c) => c.title).join('》《') }}》，将另起新课
          </template>
        </el-alert>
        <el-alert v-else-if="existingBookCourses.length" type="warning" :closable="false" class="skill-course-warn">
          <template #title>
            该教材已有 {{ existingBookCourses.length }} 门教程：《{{ existingBookCourses.map((c) => c.title).join('》《') }}》，将另起新课
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

    <!-- 生成项目课程：选一个已精析项目 → /tech-repo（项目导览/架构走读/上手路径三章） -->
    <el-dialog v-model="repoCourseVisible" title="生成项目课程" width="560px">
      <p class="muted">挑一个项目生成整仓课程：项目导览 → 架构与核心模块走读 → 上手路径。
        建议选已精析的项目（README 与评分已就绪，生成质量更好）。</p>
      <el-select v-model="repoCoursePick" filterable :loading="repoCourseLoading"
        placeholder="搜索选择项目（按总分取前 50，未精析也可选）" style="width: 100%">
        <el-option v-for="r in repoOptions" :key="r.id" :value="r.id"
          :label="`#${r.id} · ${r.full_name}${r.analyzed ? '' : ' · 未精析'}`">
          <span class="repo-name">{{ r.full_name }}</span>
          <span class="repo-desc" style="margin-left: 8px">{{ (r.zh_desc || r.description || '').slice(0, 30) }}</span>
        </el-option>
      </el-select>
      <template #footer>
        <el-button @click="repoCourseVisible = false">取消</el-button>
        <el-button type="primary" :loading="repoCourseRunning" :disabled="!repoCoursePick"
          @click="runRepoCourse">生成课程</el-button>
      </template>
    </el-dialog>

    <!-- 教材书架：上传 PDF 解析（文本层直抽 + 扫描页视觉转录 + 大纲）→ 整本精讲 / 章节系列 -->
    <el-dialog v-model="booksVisible" title="教材书架" width="720px" top="6vh">
      <div class="book-upload">
        <input type="file" accept=".pdf" class="file-input" @change="onBookFileChange" />
        <el-input v-model="bookUploadTitle" placeholder="书名（可空，解析时自动从封面推断）"
          style="flex: 1" @keyup.enter="submitBook" />
        <el-button type="primary" :loading="bookUploading" :disabled="!bookUploadFile"
          @click="submitBook">上传并解析</el-button>
      </div>
      <p class="muted">解析走后台任务（大书扫描页多时要一阵子，看右下角任务卡）；完成后可生成
        「整本精讲」（挑重点章一门课）或「章节系列」（选中章逐章各生成一门课）。</p>
      <el-empty v-if="!booksLoading && books.length === 0" description="还没有上传教材" />
      <div v-for="b in books" :key="b.id" class="book-row">
        <div class="book-info">
          <span class="book-title">《{{ b.title || b.filename }}》</span>
          <span class="muted">{{ b.pages }} 页 · {{ b.chapters }} 章
            <template v-if="b.stats?.chars">· {{ Math.round(b.stats.chars / 1000) }}k 字</template>
            <template v-if="b.stats?.vision_pages">· 视觉转录 {{ b.stats.vision_pages }} 页</template>
          </span>
        </div>
        <el-tag :type="b.status === 'ready' ? 'success' : b.status === 'failed' ? 'danger' : 'primary'"
          size="small" class="book-status">
          {{ b.status === 'ready' ? '✓ 可生成' : b.status === 'failed' ? '✕ 解析失败' : '⟳ 解析中' }}
        </el-tag>
        <div class="book-actions">
          <template v-if="b.status === 'ready'">
            <el-button link type="primary" size="small"
              @click="runBookCourse(b)">整本精讲</el-button>
            <el-button link type="primary" size="small"
              @click="openSeriesDialog(b)">章节系列</el-button>
          </template>
          <el-button v-if="b.status !== 'ready'" link size="small"
            @click="openBookNote(b)">{{ b.status === 'failed' ? '看原因' : '详情' }}</el-button>
          <el-button link type="danger" size="small" @click="removeBook(b)">删除</el-button>
        </div>
        <div v-if="b.status === 'failed' && b.note" class="book-note">{{ b.note }}</div>
      </div>
    </el-dialog>

    <!-- 章节系列课：勾选要生成的章（一章一门课，后台串行跑） -->
    <el-dialog v-model="seriesVisible" :title="`章节系列课 ·《${seriesBook?.title || ''}》`" width="560px">
      <p class="muted">一章一门课，串行生成（章多耗时长，进度看任务卡；可只勾重点章）。</p>
      <div v-loading="seriesLoading" class="series-list">
        <el-checkbox-group v-model="seriesChecked">
          <el-checkbox v-for="ch in seriesChapters" :key="ch.no" :value="ch.no" class="series-check">
            第{{ ch.no }}章 {{ ch.title }}
            <span class="muted">（p.{{ ch.start }}-{{ ch.end }}）</span>
          </el-checkbox>
        </el-checkbox-group>
      </div>
      <template #footer>
        <el-button @click="seriesVisible = false">取消</el-button>
        <el-button type="primary" :loading="seriesStarting" :disabled="!seriesChecked.length"
          @click="startSeries">生成 {{ seriesChecked.length }} 门章节课</el-button>
      </template>
    </el-dialog>

    <!-- 导入教程包：已生成好的课程 zip 解压注册（旧 course_id 由平台改写，quiz 进度正常对上） -->
    <el-dialog v-model="importVisible" title="导入教程包" width="520px">
      <p class="muted">上传一份已生成好的教程压缩包（/tech 系技能产物或其发布副本 zip），
        解压注册后显示在课程列表。</p>
      <div class="book-upload">
        <input type="file" accept=".zip" class="file-input" @change="onImportFileChange" />
        <el-input v-model="importTitle" placeholder="课程标题（可空，取压缩包首页标题）"
          style="flex: 1" @keyup.enter="submitImport" />
      </div>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" :disabled="!importFile"
          @click="submitImport">导入</el-button>
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
    <!-- 右下角任务中心：所有运行中/等待中任务一卡一条（长任务如脚手架生成 74~338s 需要常驻可见），
         终态卡停留待确认，收起成胶囊；waiting 卡内嵌应答表单（交互式技能中途抛问题） -->
    <div v-if="taskCards.length" class="task-center">
      <template v-if="centerOpen">
        <div class="tc-head">
          <span class="tc-title">任务中心</span>
          <span class="tc-count">{{ activeCards.length ? `${activeCards.length} 个进行中` : '近期任务' }}</span>
          <span v-if="taskCards.some((c) => c.status !== 'running' && c.status !== 'waiting')"
            class="tc-clear" title="清除已结束的任务" @click="clearDoneCards">清除已结束</span>
          <span class="tc-min" title="收起" @click="centerOpen = false">—</span>
        </div>
        <div class="tc-list">
          <div v-for="c in taskCards" :key="c.id" class="tc-card" :class="`tc-${c.status}`">
            <div v-if="c.status === 'running' || c.status === 'waiting'" class="tc-bar"></div>
            <div class="tc-row" @click="toggleCardLogs(c)">
              <span class="tc-icon">{{ statusIcon(c.status) }}</span>
              <span class="tc-what" :title="panelLabel(c)">{{ panelLabel(c) }}</span>
              <span class="tc-elapsed">
                {{ c.status === 'running' || c.status === 'waiting' ? '已运行' : '耗时' }} {{ elapsedOf(c) }}
              </span>
              <span v-if="c.logs.length" class="tc-toggle">{{ c.expanded ? '▲' : '▼' }}</span>
            </div>
            <div class="tc-msg" :class="{ 'tc-err': c.status === 'failed' }">
              {{ c.status === 'failed'
                ? (c.error || c.progress)
                : (c.progress || (c.status === 'waiting' ? '等待你的回答…' : '处理中…')) }}
            </div>

            <!-- waiting：问题应答表单（options 单选/多选 + 「其他」自由输入——工具语义承诺用户永远可自由作答；
                 无 options 直接自由作答；问题可轮替，id 变了表单自动刷新） -->
            <div v-if="c.status === 'waiting' && c.payload?.pending_question && !c.answered" class="tc-ask">
              <div v-for="(q, qi) in c.payload.pending_question.questions" :key="qi" class="tc-q">
                <div class="tc-q-text">{{ qi + 1 }}. {{ q.question }}</div>
                <el-radio-group v-if="q.options?.length && !q.multiSelect" v-model="c.answers[qi]" class="tc-choices">
                  <el-radio v-for="o in q.options" :key="o.label" :value="o.label" class="tc-option">
                    {{ o.label }}<span v-if="o.description" class="tc-q-desc"> — {{ o.description }}</span>
                  </el-radio>
                  <el-radio value="__other__" class="tc-option">✍ 其他</el-radio>
                </el-radio-group>
                <el-checkbox-group v-else-if="q.options?.length" v-model="c.answers[qi]" class="tc-choices">
                  <el-checkbox v-for="o in q.options" :key="o.label" :value="o.label" class="tc-option">
                    {{ o.label }}<span v-if="o.description" class="tc-q-desc"> — {{ o.description }}</span>
                  </el-checkbox>
                  <el-checkbox value="__other__" class="tc-option">✍ 其他</el-checkbox>
                </el-checkbox-group>
                <el-input
                  v-if="q.options?.length && (c.answers[qi] === '__other__'
                    || (Array.isArray(c.answers[qi]) && c.answers[qi].includes('__other__')))"
                  v-model="c.others[qi]" class="tc-other-input" placeholder="输入自定义回答…" />
                <el-input v-else-if="!q.options?.length" v-model="c.answers[qi]" placeholder="输入你的回答…" />
              </div>
              <div class="tc-ask-actions">
                <el-button size="small" :loading="c.submitting" @click="cancelAnswer(c)">取消应答</el-button>
                <el-button size="small" type="primary" :loading="c.submitting" @click="submitAnswer(c)">提交回答</el-button>
              </div>
            </div>
            <div v-else-if="c.status === 'waiting' && c.answered" class="tc-answered">✅ 已提交，任务继续执行…</div>

            <div v-show="c.expanded && c.logs.length" :data-task="c.id" class="task-logs">
              <div v-for="(l, i) in logLinesOf(c)" :key="i" class="log-line">
                <span class="log-time">{{ l.t }}</span>{{ l.msg }}
              </div>
            </div>
            <div v-if="c.status !== 'running' && c.status !== 'waiting'" class="tc-foot">
              <span v-if="c.payload?.result?.cost_usd != null" class="muted">
                成本 ${{ c.payload.result.cost_usd.toFixed(4) }} · {{ c.payload.result.num_turns }} 轮
              </span>
              <span class="tc-foot-gap"></span>
              <el-button v-if="c.payload?.result?.result" link type="primary" size="small"
                @click="showResult(c)">查看结果</el-button>
              <el-button link size="small" @click="closeCard(c)">关闭</el-button>
            </div>
          </div>
        </div>
      </template>
      <div v-else class="tc-pill" @click="centerOpen = true">
        <span v-if="activeCards.length" class="tc-pill-spin"></span>
        <span v-else class="tc-pill-dot"></span>
        {{ activeCards.length ? `${activeCards.length} 个任务运行中` : '任务动态' }}
      </div>
    </div>
  </el-container>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  BASE, adoptScaffold, answerTask, confirmScaffoldItems, createBookSeries, createScaffoldRequest,
  deleteBook, deleteIndustry, getConfig, getCourses, getBook, getBooks, getIndustry, getIndustries,
  getIssueRepos, getIssues, getRepo, getRepos, getReport, getScaffold, getScaffolds, getSkills,
  getTags, getTask, getTasks, importCourse, invokeSkill, postAnalyze, postAutoTag, postContribute,
  postIndustryParse, postIndustryRuns, postRefresh, postTranslate, rematchScaffold, runAgent,
  splitScaffold, submitScaffoldSelection, uploadBook,
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
const tagFilter = ref([])
const tagOptions = ref([])
const issueAnalyzed = ref('all')
const issuePage = ref(1)
const issuePageSize = ref(20)
const issueTotal = ref(0)
// 行业洞察
const industryInput = ref('')
const industryRunning = ref(false)
const industryParsing = ref(false)
const parseDialog = ref(false)
const parseResult = ref(null)
const industries = ref([])
const industriesLoading = ref(false)
const industryVisible = ref(false)
const industryReport = ref(null)
const tagging = ref(false)
const analyzing = ref(false)
const translating = ref(false)
// 脚手架（一句话需求 → 框架匹配 → 拆条选型 → 生成 zip）
const scaffoldInput = ref('')
const scaffoldRunning = ref(false)
const scaffoldRematching = ref(false)
const scaffolds = ref([])
const scaffoldsLoading = ref(false)
const scaffoldPage = ref(1)
const scaffoldPageSize = 20
const scaffoldTotal = ref(0)
const scaffoldVisible = ref(false)
const scaffoldDetail = ref(null)
const picked = ref([])
const config = ref(null)
const detailVisible = ref(false)
const detail = ref(null)
const reportVisible = ref(false)
const report = ref(null)
const refreshing = ref(false)
const contributing = ref(false)
// 进度面板当前展示的任务：自己提交的（定向轮询）或扫描到的运行中任务；结束后留在面板上显示摘要
// ---------- 任务中心（右下角浮动卡） ----------
const taskCards = ref([])      // 在册卡：running/waiting + 刚终态未关闭的
const centerOpen = ref(true)   // 展开卡堆栈；false 收起成右下角胶囊
let centerTimer = null         // 统一轮询：有进行中任务 2s，空闲降 10s 心跳（外部入口提交的任务也能被发现）
let centerBusy = false         // 单飞标志：上一轮没跑完不叠下一轮
const onDoneMap = new Map()    // taskId -> 终态回调（各提交处的数据刷新钩子）
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
const skillRepoOptions = ref([])     // repo 下拉数据（/tech-repo 一类）
const skillRepoLoading = ref(false)
const existingRepoCourses = ref([])  // 所选项目的已有项目课
const skillBookOptions = ref([])     // book 下拉数据（/tech-book 一类）
const skillBookLoading = ref(false)
const existingBookCourses = ref([])  // 所选教材的已有教程
const copiedCmd = ref('')            // 剪贴板被拒时兜底亮出命令
const invoking = ref(false)
// 学习模块化：项目课 / 教材书架 / 导入教程包
const repoCourseVisible = ref(false)
const repoCourseLoading = ref(false)
const repoOptions = ref([])
const repoCoursePick = ref(null)
const repoCourseRunning = ref(false)
const booksVisible = ref(false)
const books = ref([])
const booksLoading = ref(false)
const bookUploadFile = ref(null)
const bookUploadTitle = ref('')
const bookUploading = ref(false)
const seriesVisible = ref(false)
const seriesLoading = ref(false)
const seriesBook = ref(null)
const seriesChapters = ref([])
const seriesChecked = ref([])
const seriesStarting = ref(false)
const importVisible = ref(false)
const importFile = ref(null)
const importTitle = ref('')
const importing = ref(false)
const agentPrompt = ref('')
const agentRunning = ref(false)
const agentInput = ref(null)
const skillTasks = ref([])
const resultDialog = ref(false)
const resultTask = ref(null)
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

// ---------- 任务耗时与日志格式化 ----------

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

/** 卡片耗时：方法内读 tick 建立依赖，每秒重算所有未结束卡的「已运行」 */
function elapsedOf(c) {
  void tick.value
  if (!c.created_at) return ''
  const end = c.finished_at ? parseUTC(c.finished_at) : Date.now()
  return fmtDuration(Math.max(0, Math.round((end - parseUTC(c.created_at)) / 1000)))
}

function logLinesOf(c) {
  return (c.logs || []).map((l) => {
    const ms = parseUTC(l.t)
    return { t: Number.isNaN(ms) ? '' : new Date(ms).toLocaleTimeString('zh-CN', { hour12: false }), msg: l.msg }
  })
}

/** 展开中/新日志到达的卡自动滚底（多卡并存，按 data-task 定位各自的日志容器；
 *  用户上翻看历史时距底 >40px 就不拽回去） */
watch(
  () => taskCards.value.map((c) => `${c.id}:${c.expanded}:${c.logs.length}`).join('|'),
  async () => {
    await nextTick()
    for (const c of taskCards.value) {
      if (!c.expanded) continue
      const el = document.querySelector(`.task-logs[data-task="${c.id}"]`)
      if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 40) el.scrollTop = el.scrollHeight
    }
  },
)

function statusLabel(s) {
  return s === 'success' ? '已完成' : s === 'running' ? '运行中' : s === 'waiting' ? '等待输入' : '失败'
}

function statusIcon(s) {
  return s === 'running' ? '⟳' : s === 'waiting' ? '✋' : s === 'success' ? '✓' : '✕'
}

const TASK_TYPE_LABELS = {
  task: '新任务', // focusTask 占位卡：首轮轮询（<1s）就会换成真实类型
  refresh: '刷新榜单',
  contribution: '贡献分析',
  industry: '定向行业分析',
  tagging: '项目自动打标',
  analyze: '批量精析',
  translate: '中文简介翻译',
  book_extract: '教材解析',
  book_series: '教材系列课',
  scaffold_match: '脚手架框架匹配',
  scaffold_select: '脚手架条目选型',
  scaffold_build: '脚手架生成',
}

/** 面板头部标识任务本身：连发多条时面板会在任务间切换（前一个结束就接手下一个运行中的），
 *  只显示进度行会让人以为同一件事在反复横跳。*/
function panelLabel(t) {
  if (!t) return ''
  if (t.type === 'agent') return `🤖 ${(t.payload?.prompt || 'AI 命令').slice(0, 30)}`
  if (t.type === 'skill') return `/${t.payload?.skill || '技能'} ${t.payload?.args || ''}`.trim()
  if (t.type === 'industry') return `🧭 行业分析 · ${t.payload?.args?.[0] || ''}`
  if (t.type === 'analyze') return `🔬 批量精析 ${((t.payload?.args?.[0] || '').match(/\d+/g) || []).length} 个项目`
  if (t.type === 'book_extract') return `📖 教材解析 #${t.payload?.book_id ?? '?'}`
  if (t.type === 'book_series') return `📚 教材系列课 · ${t.payload?.chapter_nos?.length || '?'} 章`
  if (t.type === 'scaffold_match') return `🏗 需求 #${t.payload?.request_id ?? '?'} 框架匹配`
  if (t.type === 'scaffold_select') return `🏗 需求 #${t.payload?.request_id ?? '?'} 条目选型`
  if (t.type === 'scaffold_build') return `🏗 需求 #${t.payload?.request_id ?? '?'} 生成脚手架`
  return TASK_TYPE_LABELS[t.type] || t.type
}

function statusTag(s) {
  return s === 'success' ? 'success' : s === 'running' ? 'primary' : s === 'waiting' ? 'warning' : 'danger'
}

// ---------- 任务中心引擎 ----------

const activeCards = computed(() =>
  taskCards.value.filter((c) => c.status === 'running' || c.status === 'waiting'))

/** 列表项 → 卡片：answers/others 是应答表单的本地态（waiting 用），logs 按需拉。
 *  reactive 包一层：发现新卡后立即 pullLogs(rawC) 的场景，绕过代理的赋值不会触发渲染。*/
function makeCard(t) {
  return reactive({
    ...t, logs: [], logsLoaded: false, expanded: false,
    answers: [], others: [], answered: false, submitting: false, miss: 0,
  })
}

/** 新一轮提问（或问题轮替）时重置表单本地态；唯一选项预选，少一次点击 */
function resetAnswers(c) {
  const qs = c.payload?.pending_question?.questions || []
  c.answers = qs.map((q) => (q.multiSelect ? []
    : q.options?.length === 1 ? q.options[0].label : ''))
  c.others = qs.map(() => '')
  c.answered = false
}

/** 单卡拉最新状态与时间线（终态补最后一拉 / 展开中的卡滚动日志 / 滑出列表窗口的兜底）。
 *  返回是否拉取成功（失败多为记录丢失：服务重启后孤儿任务由后端标 failed，查不到才算丢）。*/
async function pullLogs(c) {
  try {
    const { task } = await getTask(c.id)
    Object.assign(c, task)
    c.logs = task.logs || []
    c.logsLoaded = true
    return true
  } catch {
    return false
  }
}

async function toggleCardLogs(c) {
  if (!c.logsLoaded && !c.logs.length) await pullLogs(c)
  if (!c.logs.length) return // 无时间线可展开（如刷新任务）
  c.expanded = !c.expanded
}

function closeCard(c) {
  taskCards.value = taskCards.value.filter((x) => x.id !== c.id)
  onDoneMap.delete(c.id)
  scheduleCenter() // 卡全空了要降到心跳频率
}

function clearDoneCards() {
  taskCards.value = taskCards.value.filter((c) => c.status === 'running' || c.status === 'waiting')
}

/** 刚到终态：补全量时间线 + 触发提交处注册的刷新回调 */
async function finalizeCard(c) {
  await pullLogs(c)
  const cb = onDoneMap.get(c.id)
  onDoneMap.delete(c.id)
  cb?.()
}

/** 统一轮询：列表扫新卡、更新在册卡、发现终态。有进行中任务 2s，空闲降到 10s 心跳
 *  （Claude Code 侧跑 /tech 等技能提交的任务也能被 web 端发现）。*/
async function pollCenter() {
  if (centerBusy) return
  centerBusy = true
  try {
    const { tasks: list } = await getTasks(15)
    const byId = new Map(list.map((t) => [t.id, t]))
    for (const t of list) { // 新出现的进行中任务上卡（外部入口提交的也在此被发现）
      if ((t.status === 'running' || t.status === 'waiting') && !taskCards.value.some((c) => c.id === t.id)) {
        const c = makeCard(t)
        resetAnswers(c)
        taskCards.value.unshift(c)
        pullLogs(c) // 预拉一次：卡上能立刻显示 ▼ 展开提示（后续仅展开中的卡才续拉）
        centerOpen.value = true
      }
    }
    for (const c of taskCards.value) {
      const fresh = byId.get(c.id)
      const wasActive = c.status === 'running' || c.status === 'waiting'
      if (fresh) {
        const pendBefore = c.payload?.pending_question?.id
        Object.assign(c, fresh)
        c.miss = 0
        if (c.status === 'waiting' && c.payload?.pending_question?.id !== pendBefore) resetAnswers(c)
        const active = c.status === 'running' || c.status === 'waiting'
        if (wasActive && !active) await finalizeCard(c) // 刚结束：最后一拉拿终态与末行日志
        else if (active && c.expanded) await pullLogs(c)
      } else if (wasActive) {
        // 滑出最近列表窗口（>15 条新任务挤掉）但还在跑：定向兜底；连续查不到才判丢失
        if (await pullLogs(c)) {
          c.miss = 0
          if (c.status !== 'running' && c.status !== 'waiting') await finalizeCard(c)
        } else if (++c.miss >= 3) {
          c.status = 'failed'
          c.error = '任务记录已丢失（服务可能已重启）'
          await finalizeCard(c)
        }
      }
    }
  } catch { /* 后端暂不可达：保留现状下一轮再试 */ } finally {
    centerBusy = false
  }
  scheduleCenter() // 按最新活跃数调整轮询频率
}

function scheduleCenter() {
  if (centerTimer) clearInterval(centerTimer)
  centerTimer = setInterval(pollCenter, activeCards.value.length ? 2000 : 10000)
}

function startCenter() {
  if (!centerTimer) scheduleCenter()
  pollCenter()
}

function stopCenter() {
  if (centerTimer) clearInterval(centerTimer)
  centerTimer = null
}

/** 提交后立即上卡占位（时间线秒级可见）+ 注册终态回调；轮询交给任务中心统一驱动。
 *  签名与旧版一致：focusTask(taskId, onDone)。*/
function focusTask(taskId, onDone) {
  if (onDone) onDoneMap.set(taskId, onDone)
  if (!taskCards.value.some((c) => c.id === taskId)) {
    const c = makeCard({
      id: taskId, type: 'task', status: 'running', progress: '已提交，等待启动…', payload: {},
      created_at: new Date().toISOString(),
    })
    c.expanded = true // 自己提交的任务默认展开时间线
    taskCards.value.unshift(c)
  }
  centerOpen.value = true
  startCenter()
}

// ---------- waiting 应答 ----------

async function submitAnswer(c) {
  const pending = c.payload?.pending_question
  if (!pending) return
  const answers = pending.questions.map((q, i) => {
    const raw = c.answers[i]
    let answer
    if (Array.isArray(raw)) { // 多选：「其他」的补充文本并入
      const labels = raw.filter((v) => v !== '__other__')
      if (raw.includes('__other__') && (c.others[i] || '').trim()) labels.push(c.others[i].trim())
      answer = labels.join('、')
    } else if (raw === '__other__') {
      answer = (c.others[i] || '').trim()
    } else {
      answer = (raw || '').trim()
    }
    return { question: q.question, answer }
  })
  const missing = answers.findIndex((a) => !a.answer)
  if (missing >= 0) {
    ElMessage.warning(`第 ${missing + 1} 题还没作答`)
    return
  }
  c.submitting = true
  try {
    await answerTask(c.id, { id: pending.id, answers })
    c.answered = true // 表单收起；工具侧消费后 waiting→running，卡片回到运行态
    ElMessage.success('已提交，任务继续执行')
  } catch (e) {
    ElMessage.error(`应答失败：${e.message}`) // 409 多为问题已轮替：重拉拿新表单
    await pullLogs(c)
    if (c.status === 'waiting') resetAnswers(c)
  } finally {
    c.submitting = false
  }
}

async function cancelAnswer(c) {
  const pending = c.payload?.pending_question
  if (!pending) return
  try {
    await ElMessageBox.confirm('取消应答后任务将以「已取消」结束，确定？', '取消应答', { type: 'warning' })
  } catch { return }
  c.submitting = true
  try {
    await answerTask(c.id, { id: pending.id, cancel: true })
    c.answered = true
  } catch (e) {
    ElMessage.error(`取消失败：${e.message}`)
    await pullLogs(c)
    if (c.status === 'waiting') resetAnswers(c)
  } finally {
    c.submitting = false
  }
}

function scoreType(v) {
  if (v >= 70) return 'success'
  if (v >= 40) return 'warning'
  return 'info'
}

function matchColor(v) {
  if (v >= 70) return '#34d399'
  if (v >= 40) return '#fbbf24'
  return '#64748b'
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

/** 行内标签点击 → 项目榜按该标签筛选并跳过去（多选模式：点谁换谁） */
function filterTag(tag) {
  activeTab.value = 'repos'
  tagFilter.value = [tag]
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

/** 删除一份行业报告（只删报告记录；项目上的标签是累积知识，保留） */
async function removeIndustry(row) {
  try {
    await ElMessageBox.confirm(`删除行业报告「${row.name}」？项目上的标签会保留。`, '删除确认', { type: 'warning' })
  } catch { /* 取消 */ return }
  try {
    await deleteIndustry(row.id)
    ElMessage.success('已删除')
    loadIndustries()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

/** 行业分析两段式：先解析（方向 + 项目候选），确认面板里删/换之后再跑 */
async function runIndustry() {
  const text = industryInput.value.trim()
  if (!text) return
  industryParsing.value = true
  try {
    const data = await postIndustryParse(text)
    parseResult.value = {
      directions: (data.directions || []).map((d) => ({ ...d, keep: true })),
      repos: (data.repos || []).map((r) => ({ ...r, keep: true })),
    }
    parseDialog.value = true
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    industryParsing.value = false
  }
}

async function confirmIndustry() {
  const directions = (parseResult.value?.directions || []).filter((d) => d.keep)
  const repos = (parseResult.value?.repos || []).filter((r) => r.keep && r.selected).map((r) => r.selected)
  if (!directions.length) {
    ElMessage.warning('至少保留一个方向')
    return
  }
  industryRunning.value = true
  try {
    const { task_id: taskId } = await postIndustryRuns({
      directions: directions.map(({ raw, tag }) => ({ raw, tag })),
      repos,
    })
    ElMessage.success(`${directions.length} 个方向的分析已提交，进度见右下角任务中心`)
    parseDialog.value = false
    industryInput.value = ''
    focusTask(taskId, () => {
      loadIndustries()
      loadTags()
      if (activeTab.value === 'repos') loadRepos()
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

// ---------- 脚手架 ----------

const SCAFFOLD_STATUS = {
  matching: ['匹配中', 'primary'], matched: ['已匹配', 'success'],
  done_adopt: ['已采用', 'info'], splitting: ['拆条中', 'primary'],
  split: ['待确认条目', 'warning'], selecting: ['选型中', 'primary'],
  selected: ['已选型', 'success'], building: ['生成中', 'primary'],
  built: ['已生成', 'success'],
}

function scaffoldStatus(s) {
  const [label, type] = SCAFFOLD_STATUS[s] || [s, 'info']
  return { label, type }
}

async function loadScaffolds() {
  scaffoldsLoading.value = true
  try {
    const data = await getScaffolds({
      limit: scaffoldPageSize,
      offset: (scaffoldPage.value - 1) * scaffoldPageSize,
    })
    scaffolds.value = data.requests
    scaffoldTotal.value = data.total
  } catch (e) {
    ElMessage.error(`加载脚手架需求失败：${e.message}`)
  } finally {
    scaffoldsLoading.value = false
  }
}

function resetScaffoldPage() {
  scaffoldPage.value = 1
  loadScaffolds()
}

async function runScaffold() {
  const text = scaffoldInput.value.trim()
  if (!text) return
  scaffoldRunning.value = true
  try {
    const { task_id: taskId, request_id: requestId } = await createScaffoldRequest(text)
    ElMessage.success('需求匹配已提交：LLM 归纳 → 双通道检索 → 双轨评分，进度见右下角任务中心')
    scaffoldInput.value = ''
    resetScaffoldPage()
    focusTask(taskId, () => {
      loadScaffolds()
      if (scaffoldVisible.value) openScaffold(requestId) // 抽屉开着就原地刷新结果
    })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    scaffoldRunning.value = false
  }
}

async function openScaffold(id) {
  try {
    const detail = await getScaffold(id)
    scaffoldDetail.value = detail
    initScaffoldEdit(detail)
    scaffoldVisible.value = true
  } catch (e) {
    ElMessage.error(`加载需求详情失败：${e.message}`)
  }
}

/** 改话重跑（回退）：弹输入框预填原话，清掉匹配产出重新提交 */
async function rematchScaffoldRow() {
  const row = scaffoldDetail.value
  if (!row) return
  let text
  try {
    ({ value: text } = await ElMessageBox.prompt('修改需求描述（清空则用原话重跑）', '重新匹配', {
      inputValue: row.raw_text, inputType: 'textarea', confirmButtonText: '重新匹配',
    }))
  } catch { /* 取消 */ return }
  scaffoldRematching.value = true
  try {
    const { task_id: taskId } = await rematchScaffold(row.id, (text || '').trim())
    ElMessage.success('已重新提交匹配，进度见右下角任务中心')
    scaffoldVisible.value = false
    loadScaffolds()
    focusTask(taskId, () => {
      loadScaffolds()
      openScaffold(row.id)
    })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    scaffoldRematching.value = false
  }
}

// ---------- 采用分支（终态：clone 地址 + 评估报告） ----------

const adoptingRepo = ref('')

const adoptCloneUrl = computed(() =>
  scaffoldDetail.value?.adopt_repo ? `https://github.com/${scaffoldDetail.value.adopt_repo}.git` : '')
const adoptMdHtml = computed(() => mdToHtml(scaffoldDetail.value?.adopt_report_md || ''))

/** 复制文本到剪贴板（拒访时兜底亮出内容），课程命令与 clone 地址共用 */
async function copyText(text, what) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`已复制${what}`)
  } catch {
    ElMessage.info(`剪贴板不可用，请手动复制：${text}`)
  }
}

/** 采用候选：确认后同步生成评估报告（拉 README + 单次 LLM，约 5-15 秒） */
async function adoptCandidate(cand) {
  const row = scaffoldDetail.value
  if (!row) return
  try {
    await ElMessageBox.confirm(
      `采用 ${cand.full_name} 作为项目起点？将生成采用评估报告（约 5-15 秒），该需求就此完结。`,
      '采用确认', { type: 'info', confirmButtonText: '采用' })
  } catch { /* 取消 */ return }
  adoptingRepo.value = cand.full_name
  try {
    const res = await adoptScaffold(row.id, cand.full_name)
    ElMessage.success(res.cached ? '该仓库已有评估报告' : '已采用，评估报告已生成')
    await openScaffold(row.id) // 原地刷新成 done_adopt 态
    loadScaffolds()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    adoptingRepo.value = ''
  }
}

// ---------- 拆条与条目选型（V2） ----------

const STACK_OPTIONS = ['Python', 'Java', 'JavaScript', 'TypeScript', 'Go', 'Rust', 'C++', 'C#']
const SELF_DEV = '__self__' // 选型 radio 的「自研」哨兵值
const splittingScaffold = ref(false)
const scaffoldSelecting = ref(false)
const splitItems = ref([])     // 条目编辑副本（kw = keywords 逗号串）
const splitStack = ref('')
const editingItems = ref(false) // selected 态点「改条目重选」切回编辑面板
const selChoices = ref({})      // {条目 no: full_name | SELF_DEV}

/** 打开抽屉时初始化对应态的本地编辑副本 */
function initScaffoldEdit(detail) {
  editingItems.value = false
  reselecting.value = false
  selChoices.value = {}
  splitItems.value = (detail.items || []).map((it) => ({
    ...it, kw: (it.keywords || []).join(', '),
  }))
  splitStack.value = detail.tech_stack || ''
  for (const it of detail.items || []) {
    if (it.selected) selChoices.value[it.no] = it.selected
    else if (it.self_dev) selChoices.value[it.no] = SELF_DEV
  }
}

function addSplitItem() {
  splitItems.value.push({ no: splitItems.value.length + 1, name: '', desc: '', kw: '',
    candidates: [], selected: null, self_dev: false })
}

/** 拆条（同步 2-10s；matched 态入口与「重新拆条」共用，后者覆盖编辑） */
async function runSplit() {
  const row = scaffoldDetail.value
  if (!row) return
  if (editingItems.value || row.status === 'split') {
    try {
      await ElMessageBox.confirm('重新拆条会覆盖当前编辑的条目，继续？', '重新拆条', { type: 'warning' })
    } catch { /* 取消 */ return }
  }
  splittingScaffold.value = true
  try {
    const res = await splitScaffold(row.id)
    ElMessage.success(res.cached ? '命中拆解缓存，条目秒出' : `拆出 ${res.items.length} 条技术条目`)
    await openScaffold(row.id) // 原地刷新成 split 态
    loadScaffolds()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    splittingScaffold.value = false
  }
}

/** 条目确认 → 提交条目级选型任务（focusTask 跟踪，完成后原地刷 selected 态） */
async function confirmItems() {
  const row = scaffoldDetail.value
  if (!row) return
  const items = splitItems.value.filter((it) => it.name.trim())
  if (!items.length) {
    ElMessage.warning('至少保留一个条目（名称不能为空）')
    return
  }
  scaffoldSelecting.value = true
  try {
    const { task_id: taskId } = await confirmScaffoldItems(
      row.id,
      items.map(({ name, desc, kw }) => ({
        name: name.trim(), desc: desc.trim(),
        keywords: kw.split(/[,，]/).map((k) => k.trim()).filter(Boolean),
      })),
      splitStack.value,
    )
    ElMessage.success('选型任务已提交：每条目检索候选并双轨评分，进度见右下角任务中心')
    editingItems.value = false
    await openScaffold(row.id) // 刷成 selecting 态
    loadScaffolds()
    focusTask(taskId, () => {
      loadScaffolds()
      if (scaffoldVisible.value) openScaffold(row.id)
    })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    scaffoldSelecting.value = false
  }
}

/** selected 态点「改条目重选」：切回编辑面板（重确认会重跑选型，fit 缓存兜成本） */
function startEditItems() {
  editingItems.value = true
}

/** 全部条目都有归属（候选或自研）才能生成 */
const allChosen = computed(() => {
  const items = scaffoldDetail.value?.items || []
  return items.length > 0 && items.every((it) => selChoices.value[it.no])
})

// ---------- 生成（V3） ----------

const scaffoldBuilding = ref(false)
const reselecting = ref(false) // built 态点「改选型」：切回选型面板
const sixFiles = computed(() => {
  const b = scaffoldDetail.value?.build
  if (!b) return []
  return ['README.md（启动说明）', '前端页面', 'docs/research.md（行业调研）',
    'docs/requirement.md（原始需求）', 'docs/architecture.md（架构）', 'LICENSES.md']
    .filter((f) => f !== '前端页面' || b.file_count > 0)
})

/** 生成脚手架（selected 态首发 / built 态重新生成共用）：提交选型 → focusTask → built */
async function generateScaffold() {
  const row = scaffoldDetail.value
  if (!row || !allChosen.value) {
    ElMessage.warning('还有条目未选完（自研也算一种选择）')
    return
  }
  await submitScaffoldBuild((row.items || []).map((it) => ({
    no: it.no,
    full_name: selChoices.value[it.no] === SELF_DEV ? null : selChoices.value[it.no],
  })))
}

/** 失败重试：按已落库的选型原样重发（不动选型面板；同组合命中产物缓存则秒回） */
async function retryScaffoldBuild() {
  const row = scaffoldDetail.value
  if (!row) return
  await submitScaffoldBuild((row.items || []).map((it) => ({
    no: it.no, full_name: it.selected || null, // selected 为空 = 自研（后端同判）
  })))
}

/** 提交集型 → scaffold_build 任务 → 刷成 building 态并跟踪收尾 */
async function submitScaffoldBuild(selections) {
  const row = scaffoldDetail.value
  scaffoldBuilding.value = true
  try {
    const { task_id: taskId } = await submitScaffoldSelection(row.id, selections)
    ElMessage.success('生成任务已提交：Agent 整合选型产出可启动骨架（数分钟），进度见右下角任务中心')
    reselecting.value = false
    await openScaffold(row.id) // 刷成 building 态
    loadScaffolds()
    focusTask(taskId, () => {
      loadScaffolds()
      if (scaffoldVisible.value) openScaffold(row.id)
    })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    scaffoldBuilding.value = false
  }
}

function downloadZip() {
  const url = scaffoldDetail.value?.build?.zip_url
  if (url) window.open(BASE + url, '_blank')
}

function reselectScaffold() {
  reselecting.value = true
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

/** 相对时间（月按 30 天近似）：今天 / 3 天前 / 2 个月前 / 1 年前 */
function fmtAgo(iso) {
  if (!iso) return '—'
  const ms = parseUTC(iso)
  if (Number.isNaN(ms)) return '—'
  const days = Math.max(0, Math.floor((Date.now() - ms) / 86400000))
  if (days === 0) return '今天'
  if (days < 30) return `${days} 天前`
  if (days < 365) return `${Math.floor(days / 30)} 个月前`
  return `${Math.floor(days / 365)} 年前`
}

/** 距最近 push 的天数；无数据返回 -1（不算停更） */
function pushDays(row) {
  if (!row.pushed_at) return -1
  const ms = parseUTC(row.pushed_at)
  return Number.isNaN(ms) ? -1 : Math.floor((Date.now() - ms) / 86400000)
}

async function analyzeSelected() {
  analyzing.value = true
  try {
    const { task_id: taskId } = await postAnalyze(picked.value)
    ElMessage.success(`已提交 ${picked.value.length} 个项目的 LLM 精析，完成后切「已精析」查看`)
    focusTask(taskId, loadRepos)
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
    focusTask(taskId, loadRepos)
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
  window.open(`${BASE}/courses/${id}/index.html`, '_blank')
  if (hint) ElMessage.info(hint)
}

// ---------- 学习模块化：项目课 / 教材书架 / 导入教程包 ----------

async function loadRepoOptions() {
  repoCourseLoading.value = true
  try {
    repoOptions.value = (await getRepos({ sort: 'total', limit: 50 })).repos
  } catch (e) {
    ElMessage.error(`加载项目列表失败：${e.message}`)
  } finally {
    repoCourseLoading.value = false
  }
}

function openRepoCourseDialog() {
  repoCourseVisible.value = true
  if (!repoOptions.value.length) loadRepoOptions()
}

async function runRepoCourse() {
  repoCourseRunning.value = true
  try {
    const { task_id: taskId } = await invokeSkill('tech-repo', String(repoCoursePick.value))
    ElMessage.success('项目课生成已提交，进度见右下角任务中心')
    repoCourseVisible.value = false
    focusTask(taskId, loadCourses)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    repoCourseRunning.value = false
  }
}

async function loadBooks() {
  booksLoading.value = true
  try {
    books.value = (await getBooks()).books
  } catch (e) {
    ElMessage.error(`加载教材失败：${e.message}`)
  } finally {
    booksLoading.value = false
  }
}

function openBooksDialog() {
  booksVisible.value = true
  loadBooks()
}

function onBookFileChange(e) {
  bookUploadFile.value = e.target.files?.[0] || null
}

async function submitBook() {
  if (!bookUploadFile.value) return
  bookUploading.value = true
  try {
    const { task_id: taskId } = await uploadBook(bookUploadFile.value, bookUploadTitle.value)
    ElMessage.success('教材已上传，解析任务已提交（见右下角任务卡）')
    bookUploadFile.value = null
    bookUploadTitle.value = ''
    focusTask(taskId, loadBooks)
    loadBooks()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    bookUploading.value = false
  }
}

/** 整本精讲：直接调 /tech-book（技能自己按大纲挑重点章）。 */
function runBookCourse(book) {
  invokeSkill('tech-book', String(book.id)).then(({ task_id: taskId }) => {
    ElMessage.success(`《${book.title || book.filename}》精讲课已提交，进度见右下角任务中心`)
    booksVisible.value = false
    focusTask(taskId, loadCourses)
  }).catch((e) => ElMessage.error(e.message))
}

/** 章节系列：拉完整大纲勾选章，一章一门课的串行批量任务。 */
async function openSeriesDialog(book) {
  seriesBook.value = book
  seriesChapters.value = []
  seriesChecked.value = []
  seriesVisible.value = true
  seriesLoading.value = true
  try {
    seriesChapters.value = (await getBook(book.id)).outline?.chapters || []
  } catch (e) {
    ElMessage.error(`加载大纲失败：${e.message}`)
  } finally {
    seriesLoading.value = false
  }
}

async function startSeries() {
  seriesStarting.value = true
  try {
    const { task_id: taskId } = await createBookSeries(seriesBook.value.id, [...seriesChecked.value].sort((a, b) => a - b))
    ElMessage.success(`章节系列课已提交（${seriesChecked.value.length} 门），串行生成中，看任务卡`)
    seriesVisible.value = false
    booksVisible.value = false
    focusTask(taskId, () => { loadCourses(); loadBooks() })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    seriesStarting.value = false
  }
}

function openBookNote(book) {
  ElMessageBox.alert(book.note || '解析中，等任务完成后再试。', `《${book.title || book.filename}》`)
}

async function removeBook(book) {
  try {
    await ElMessageBox.confirm(
      `删除《${book.title || book.filename}》（PDF 与解析文本一并删除，已生成的课程保留）`, '删除教材',
      { type: 'warning' })
  } catch { return }
  try {
    await deleteBook(book.id)
    loadBooks()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function openImportDialog() {
  importVisible.value = true
}

function onImportFileChange(e) {
  importFile.value = e.target.files?.[0] || null
}

async function submitImport() {
  if (!importFile.value) return
  importing.value = true
  try {
    const course = await importCourse(importFile.value, importTitle.value)
    ElMessage.success(`已导入《${course.title}》（${course.total_lessons} 课），出现在课程列表`)
    importVisible.value = false
    importFile.value = null
    importTitle.value = ''
    if (activeTab.value === 'learning') loadCourses()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    importing.value = false
  }
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
    ElMessage.success('AI 命令已提交，进度见右下角任务中心，结果完成后在「🛠 技能 · 最近执行」查看')
    agentPrompt.value = ''
    loadSkillTasks()
    focusTask(taskId, loadSkillTasks)
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
  existingRepoCourses.value = []
  existingBookCourses.value = []
  skillForm.value = {}
  // 单选参数默认取第一项（/tech 的「另起新课」是更安全的默认）
  for (const [key, def] of Object.entries(s.arguments || {})) {
    if (def.type === 'select') skillForm.value[key] = def.options?.[0]?.value ?? ''
  }
  const defs = Object.values(s.arguments || {})
  if (defs.some((d) => d.type === 'issue')) loadIssueOptions()
  if (defs.some((d) => d.type === 'repo')) loadSkillRepoOptions()
  if (defs.some((d) => d.type === 'book')) loadSkillBookOptions()
  skillDialog.value = true
}

// ---------- 结构化参数表单 ----------
const hasSkillForm = computed(() => Object.keys(currentSkill.value?.arguments || {}).length > 0)

function paramVisible(def) {
  // 条件词表（与 skill_runner._parse_arguments 注释同步）：
  // 所选 issue/项目/教材已有课程时才显示对应字段（/tech 的覆盖选择等）
  if (def.visible_if === 'existing_course') return existingCourses.value.length > 0
  if (def.visible_if === 'existing_repo_course') return existingRepoCourses.value.length > 0
  if (def.visible_if === 'existing_book_course') return existingBookCourses.value.length > 0
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
  _resetConditionalFields(existingCourses.value.length)
}

async function loadSkillRepoOptions() {
  skillRepoLoading.value = true
  try {
    skillRepoOptions.value = (await getRepos({ sort: 'total', limit: 50 })).repos
  } catch (e) {
    ElMessage.error(`加载项目列表失败：${e.message}`)
  } finally {
    skillRepoLoading.value = false
  }
}

async function onRepoParamChange() {
  existingRepoCourses.value = []
  const id = Number(skillForm.value.repo)
  if (id) {
    try {
      existingRepoCourses.value = (await getCourses()).courses
        .filter((c) => c.source_type === 'repo' && c.repo_id === id)
    } catch { /* 同上：查不到当作没有 */ }
  }
  _resetConditionalFields(existingRepoCourses.value.length)
}

async function loadSkillBookOptions() {
  skillBookLoading.value = true
  try {
    skillBookOptions.value = (await getBooks()).books.filter((b) => b.status === 'ready')
  } catch (e) {
    ElMessage.error(`加载教材失败：${e.message}`)
  } finally {
    skillBookLoading.value = false
  }
}

async function onBookParamChange() {
  existingBookCourses.value = []
  const id = Number(skillForm.value.book)
  if (id) {
    try {
      existingBookCourses.value = (await getCourses()).courses
        .filter((c) => c.source_type === 'book' && c.book_id === id)
    } catch { /* 同上 */ }
  }
  _resetConditionalFields(existingBookCourses.value.length)
}

/** 条件字段隐藏时清掉值，避免看不见的选择泄漏进 args（先选有旧课的再换没旧的）。
 *  hasExisting=false 表示当前来源没有旧课，所有 visible_if 字段都该收起来。 */
function _resetConditionalFields(hasExisting) {
  if (hasExisting) return
  for (const [key, def] of Object.entries(currentSkill.value?.arguments || {})) {
    if (def.visible_if) skillForm.value[key] = def.type === 'select' ? (def.options?.[0]?.value ?? '') : ''
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
    ElMessage.success(`技能 /${currentSkill.value.name} 已提交，进度见右下角任务中心`)
    skillDialog.value = false
    loadSkillTasks()
    focusTask(taskId, loadSkillTasks)
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
    const { task_id: taskId } = await postRefresh()
    ElMessage.success('刷新任务已提交，进度见右下角任务中心')
    focusTask(taskId, () => { loadRepos(); if (activeTab.value === 'issues') loadIssues() })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    refreshing.value = false
  }
}

async function analyzeContribution() {
  contributing.value = true
  try {
    const { task_id: taskId } = await postContribute(picked.value)
    ElMessage.success('贡献分析任务已提交，进度见右下角任务中心，完成后可在 Issue 榜查看')
    focusTask(taskId, () => { loadRepos(); if (activeTab.value === 'issues') loadIssues() })
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

watch(activeTab, (tab) => {
  if (tab === 'issues' && issues.value.length === 0) loadIssues()
  if (tab === 'issues') loadIssueRepos() // 每次进入都刷新：贡献分析可能新增了有 issue 的项目
  if (tab === 'industries') { loadIndustries(); loadTags() } // 报告与标签都可能被新任务更新
  if (tab === 'scaffold') loadScaffolds() // 每次进入都刷新：匹配任务可能刚改状态
  if (tab === 'learning') loadCourses() // 每次进入都刷新，/tech 生成后能看到新课程
  if (tab === 'skills') { loadSkills(); loadSkillTasks() }
})

onMounted(async () => {
  await loadRepos()
  config.value = await getConfig().catch(() => null)
  loadTags()
  startCenter() // 首轮扫描：刷新页面后运行中/等待中任务自动上卡继续跟
  tickTimer = setInterval(() => tick.value++, 1000)
})
onBeforeUnmount(() => {
  stopCenter()
  if (tickTimer) clearInterval(tickTimer)
})
</script>

<style>
/* =====================================================================
   celestial-snow · Observatory Terminal 主题
   深墨蓝夜空 + 冰青主色 + 星点极光氛围；Chakra Petch 展示字 / Plex Mono 数据字
   Element Plus 走官方 dark 变量打底，再用本块重设坡道
   ===================================================================== */

html.dark {
  /* 字体 */
  --font-display: 'Chakra Petch', 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif;
  --font-mono: 'IBM Plex Mono', Consolas, 'SFMono-Regular', Menlo, monospace;

  /* 主题色 */
  --ice: #6fd3f2;
  --ice-soft: #9fe0f7;
  --mint: #34d399;
  --amber: #fbbf24;
  --rose: #fb7185;
  --text-hi: #e8eef8;
  --text-mid: #b7c5d9;
  --text-low: #7286a3;
  --line: rgba(140, 175, 230, .14);
  --line-strong: rgba(140, 175, 230, .26);
  --panel: #0f1830;
  --panel-deep: #0b1220;

  /* ---- Element Plus 变量坡道 ---- */
  --el-font-family: var(--font-display);
  --el-color-primary: #6fd3f2;
  --el-color-primary-light-3: #4e97b1;
  --el-color-primary-light-5: #3d728a;
  --el-color-primary-light-7: #2c4e64;
  --el-color-primary-light-8: #203d50;
  --el-color-primary-light-9: #152b3a;
  --el-color-primary-dark-2: #8adcf5;
  --el-color-success: #34d399;
  --el-color-success-light-3: #258f6d;
  --el-color-success-light-5: #1b6b52;
  --el-color-success-light-7: #124a3a;
  --el-color-success-light-8: #0e3b2f;
  --el-color-success-light-9: #0a2c23;
  --el-color-success-dark-2: #5cdcab;
  --el-color-warning: #fbbf24;
  --el-color-warning-light-3: #c7972f;
  --el-color-warning-light-5: #94712d;
  --el-color-warning-light-7: #634b27;
  --el-color-warning-light-8: #4a3924;
  --el-color-warning-light-9: #31291e;
  --el-color-warning-dark-2: #fcc953;
  --el-color-danger: #fb7185;
  --el-color-danger-light-3: #c75f72;
  --el-color-danger-light-5: #94465a;
  --el-color-danger-light-7: #622f40;
  --el-color-danger-light-8: #492431;
  --el-color-danger-light-9: #301922;
  --el-color-danger-dark-2: #fc8a9b;
  --el-color-error: #fb7185;
  --el-color-error-light-3: #c75f72;
  --el-color-error-light-5: #94465a;
  --el-color-error-light-7: #622f40;
  --el-color-error-light-8: #492431;
  --el-color-error-light-9: #301922;
  --el-color-error-dark-2: #fc8a9b;
  --el-color-info: #8496b0;
  --el-color-info-light-3: #6a7a91;
  --el-color-info-light-5: #4e5c71;
  --el-color-info-light-7: #353f51;
  --el-color-info-light-8: #293143;
  --el-color-info-light-9: #1c2333;
  --el-color-info-dark-2: #97a7bd;

  --el-bg-color: #0c1322;
  --el-bg-color-overlay: #111b30;
  --el-bg-color-page: #080d1a;
  --el-text-color-primary: #e8eef8;
  --el-text-color-regular: #c2cfdf;
  --el-text-color-secondary: #8ba0ba;
  --el-text-color-placeholder: #57677f;
  --el-text-color-disabled: #3e4c62;
  --el-border-color: #26334f;
  --el-border-color-light: #1f2c49;
  --el-border-color-lighter: #1a2440;
  --el-border-color-extra-light: #161f38;
  --el-border-color-dark: #324265;
  --el-border-color-darker: #3d4f75;
  --el-fill-color: #18223a;
  --el-fill-color-light: #141d32;
  --el-fill-color-lighter: #111927;
  --el-fill-color-extra-light: #0e1522;
  --el-fill-color-dark: #1d2a45;
  --el-fill-color-darker: #223154;
  --el-fill-color-blank: #0e1526;
  --el-mask-color: rgba(3, 7, 16, .72);
  --el-disabled-bg-color: #141d32;
  --el-box-shadow: 0 12px 32px 4px rgba(0, 0, 0, .38), 0 8px 20px rgba(0, 0, 0, .32);
  --el-box-shadow-light: 0 0 12px rgba(0, 0, 0, .32);
}

/* ---------- 基底：夜空 + 极光 + 星点 + 噪点 ---------- */

html { background: #080d1a; }

body {
  margin: 0;
  min-height: 100vh;
  font-family: var(--font-display);
  color: var(--text-mid);
  -webkit-font-smoothing: antialiased;
}

body::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background:
    radial-gradient(1000px 520px at 6% -12%, rgba(56, 189, 248, .13), transparent 62%),
    radial-gradient(1200px 560px at 94% -4%, rgba(139, 92, 246, .10), transparent 62%),
    radial-gradient(900px 640px at 52% 118%, rgba(45, 212, 191, .07), transparent 62%),
    radial-gradient(1.4px 1.4px at 12% 22%, rgba(226, 240, 255, .60), transparent 55%),
    radial-gradient(1px 1px at 28% 68%, rgba(226, 240, 255, .40), transparent 55%),
    radial-gradient(1.2px 1.2px at 41% 12%, rgba(226, 240, 255, .48), transparent 55%),
    radial-gradient(.8px .8px at 55% 44%, rgba(226, 240, 255, .34), transparent 55%),
    radial-gradient(1.4px 1.4px at 67% 76%, rgba(226, 240, 255, .44), transparent 55%),
    radial-gradient(1px 1px at 76% 9%, rgba(226, 240, 255, .52), transparent 55%),
    radial-gradient(.9px .9px at 85% 57%, rgba(226, 240, 255, .36), transparent 55%),
    radial-gradient(1.1px 1.1px at 93% 84%, rgba(226, 240, 255, .42), transparent 55%),
    radial-gradient(.8px .8px at 5% 82%, rgba(226, 240, 255, .30), transparent 55%),
    radial-gradient(1.2px 1.2px at 34% 92%, rgba(226, 240, 255, .38), transparent 55%),
    radial-gradient(1px 1px at 61% 27%, rgba(196, 216, 255, .30), transparent 55%),
    linear-gradient(180deg, #0b1122 0%, #070c17 100%);
}

body::after {
  content: '';
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  opacity: .035;
  background: url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E");
}

::selection { background: rgba(111, 211, 242, .30); color: #f2f9ff; }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: #22304e; border-radius: 8px; border: 2px solid #080d1a; }
::-webkit-scrollbar-thumb:hover { background: #324265; }
::-webkit-scrollbar-track, ::-webkit-scrollbar-corner { background: transparent; }

/* ---------- 骨架 ---------- */

.layout { min-height: 100vh; }
.layout > .el-main {
  padding: 22px 28px 48px;
  max-width: 1680px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

@keyframes rise {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: none; }
}
@keyframes spin-slow { to { transform: rotate(360deg); } }

/* ---------- 顶栏 ---------- */

.header {
  --el-header-height: 72px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  background: rgba(9, 14, 28, .72);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  z-index: 100;
  animation: rise .45s ease both;
}

.brand { display: flex; align-items: center; gap: 14px; }
.brand-mark {
  width: 27px;
  height: 27px;
  color: var(--ice);
  animation: spin-slow 90s linear infinite;
  filter: drop-shadow(0 0 7px rgba(111, 211, 242, .55));
}
.brand-text { display: flex; flex-direction: column; line-height: 1.25; }
.brand-name {
  font-weight: 700;
  font-size: 19px;
  letter-spacing: .17em;
  background: linear-gradient(92deg, #eaf5ff 10%, #6fd3f2 55%, #a5b4fc 95%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.brand-sub {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .34em;
  color: var(--text-low);
}
.ops { display: flex; align-items: center; }
.cfg-tag {
  margin-right: 8px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: .04em;
}

/* ---------- AI 命令控制台 ---------- */

.ai-bar {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  margin-bottom: 16px;
  background: rgba(13, 21, 40, .66);
  backdrop-filter: blur(10px);
  border: 1px solid var(--line);
  border-radius: 12px;
  transition: border-color .25s, box-shadow .25s;
  animation: rise .5s .06s cubic-bezier(.2, .7, .25, 1) both;
}
.ai-bar::before {
  content: '';
  position: absolute;
  top: 0;
  left: 18px;
  right: 18px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(160, 200, 255, .22), transparent);
}
.ai-bar:focus-within {
  border-color: rgba(111, 211, 242, .55);
  box-shadow: 0 0 0 1px rgba(111, 211, 242, .22), 0 0 30px rgba(111, 211, 242, .13);
}
.ai-glyph {
  font-family: var(--font-mono);
  font-size: 16px;
  font-weight: 600;
  color: var(--ice);
  text-shadow: 0 0 12px rgba(111, 211, 242, .65);
}
.ai-bar .el-input__wrapper { background: transparent; box-shadow: none; }
.ai-bar .el-input__inner {
  font-family: var(--font-mono);
  font-size: 13.5px;
  color: var(--text-hi);
}
.ai-bar .el-input__inner::placeholder { color: var(--text-low); }
.ai-input { flex: 1; }
.agent-prompt { color: var(--amber); font-size: 13px; font-family: var(--font-mono); }

/* ---------- Tabs：HUD 目标框导航 ----------
   页签是「被锁定的观测目标」：常态灰暗，hover 预亮角标，激活时文字辉光 +
   左上/右下目标框角标点亮 + 底部能量条流光扫描。 */

.main-tabs > .el-tabs__header {
  margin: 0 0 18px;
  padding: 0 6px;
  animation: rise .5s .12s cubic-bezier(.2, .7, .25, 1) both;
}
.main-tabs .el-tabs__nav-wrap::after {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--line-strong) 18%, var(--line-strong) 82%, transparent);
}
.main-tabs .el-tabs__item {
  height: 46px;
  font-size: 14.5px;
  font-weight: 500;
  letter-spacing: .03em;
  color: var(--text-mid);
}
.main-tabs .el-tabs__item:hover { color: var(--text-hi); }
.main-tabs .el-tabs__item.is-active {
  color: var(--text-hi);
  text-shadow: 0 0 16px rgba(111, 211, 242, .45);
}
.tab-label {
  position: relative;
  display: inline-flex;
  align-items: center;
  padding: 3px 2px;
}
.tab-label i {
  font-family: var(--font-mono);
  font-style: normal;
  font-size: 11px;
  letter-spacing: .08em;
  color: var(--ice);
  opacity: .45;
  margin-right: 9px;
  transition: opacity .2s;
}
.el-tabs__item.is-active .tab-label i {
  opacity: 1;
  text-shadow: 0 0 10px rgba(111, 211, 242, .75);
}
/* 目标框角标：左上 ⌜ 与右下 ⌟（冰青描边 + 辉光），激活点亮、hover 预亮 */
.tab-label::before,
.tab-label::after {
  content: '';
  position: absolute;
  width: 8px;
  height: 8px;
  opacity: 0;
  transition: opacity .25s;
  pointer-events: none;
}
.tab-label::before {
  left: -4px;
  top: -3px;
  border-left: 1.5px solid var(--ice);
  border-top: 1.5px solid var(--ice);
  filter: drop-shadow(0 0 4px rgba(111, 211, 242, .8));
}
.tab-label::after {
  right: -4px;
  bottom: -3px;
  border-right: 1.5px solid var(--ice);
  border-bottom: 1.5px solid var(--ice);
  filter: drop-shadow(0 0 4px rgba(111, 211, 242, .8));
}
.main-tabs .el-tabs__item:hover .tab-label::before,
.main-tabs .el-tabs__item:hover .tab-label::after { opacity: .35; }
.el-tabs__item.is-active .tab-label::before,
.el-tabs__item.is-active .tab-label::after { opacity: 1; }
/* 激活指示条：能量条 + 周期流光扫描 */
.main-tabs .el-tabs__active-bar {
  height: 2px;
  border-radius: 2px;
  background: linear-gradient(90deg, transparent, #6fd3f2 22%, #a5b4fc 50%, #6fd3f2 78%, transparent);
  box-shadow: 0 0 12px rgba(111, 211, 242, .55);
  overflow: hidden;
}
.main-tabs .el-tabs__active-bar::after {
  content: '';
  position: absolute;
  inset: 0;
  width: 34%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, .8), transparent);
  animation: tab-sweep 2.8s linear infinite;
}
@keyframes tab-sweep {
  0% { transform: translateX(-130%); }
  55%, 100% { transform: translateX(330%); }
}

/* ---------- 面板（tab 内容容器） ---------- */

.main-tabs .el-tab-pane {
  position: relative;
  padding: 18px 20px;
  margin-bottom: 26px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: 0 26px 52px -34px rgba(0, 0, 0, .6);
  animation: rise .3s ease both;
}
.main-tabs .el-tab-pane::before {
  content: '';
  position: absolute;
  top: 0;
  left: 26px;
  right: 26px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(160, 200, 255, .24), transparent);
}

/* ---------- 工具栏 ---------- */

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.search { width: 240px; }
.diff-select { width: 130px; }
.repo-select { width: 250px; }
.tag-select { width: 170px; }
.picked-hint {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-low);
}

/* 分段控件（el-radio-button） */
.toolbar .el-radio-button__inner {
  padding: 7px 15px;
  font-size: 12.5px;
  background: transparent;
  color: var(--text-mid);
  border-color: var(--line-strong);
  box-shadow: none;
  transition: color .2s, background .2s, border-color .2s;
}
.toolbar .el-radio-button__inner:hover { color: var(--text-hi); }
.toolbar .el-radio-button.is-active .el-radio-button__inner {
  background: rgba(111, 211, 242, .13);
  border-color: rgba(111, 211, 242, .45);
  color: var(--ice-soft);
  box-shadow: inset 0 0 0 1px rgba(111, 211, 242, .18), 0 0 14px rgba(111, 211, 242, .10);
}
.toolbar .el-checkbox__label { font-size: 13px; color: var(--text-mid); }

/* 复选/单选：与按钮同一套描边辉光语言（替代 EP 默认的实心蓝底白勾） */
html.dark .el-checkbox__inner {
  background: rgba(111, 211, 242, .06);
  border-color: rgba(111, 211, 242, .45);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .04);
  transition: background-color .18s, border-color .18s, box-shadow .18s;
}
html.dark .el-checkbox__inner:hover { border-color: var(--ice); }
html.dark .el-checkbox__input.is-checked .el-checkbox__inner,
html.dark .el-checkbox__input.is-indeterminate .el-checkbox__inner {
  background: rgba(111, 211, 242, .18);
  border-color: var(--ice);
  box-shadow: 0 0 10px rgba(111, 211, 242, .28);
}
html.dark .el-checkbox__input.is-checked .el-checkbox__inner::after { border-color: #cbf1fd; }
html.dark .el-checkbox__input.is-indeterminate .el-checkbox__inner::before { background: #cbf1fd; }
html.dark .el-radio__inner {
  background: rgba(111, 211, 242, .06);
  border-color: rgba(111, 211, 242, .45);
  transition: background-color .18s, border-color .18s, box-shadow .18s;
}
html.dark .el-radio__inner:hover { border-color: var(--ice); }
html.dark .el-radio__input.is-checked .el-radio__inner {
  background: rgba(111, 211, 242, .2);
  border-color: var(--ice);
  box-shadow: 0 0 10px rgba(111, 211, 242, .3);
}
html.dark .el-radio__input.is-checked .el-radio__inner::after { background: #d9f6fe; }
html.dark .el-radio__input.is-checked + .el-radio__label { color: var(--text-hi); }

/* ---------- 提示条（el-alert 改造为注释行） ---------- */

.task-alert { margin-bottom: 14px; border-radius: 8px; }
.task-alert.el-alert { padding: 8px 14px; }
.task-alert .el-alert__title { font-size: 12.5px; color: var(--text-mid); letter-spacing: .02em; }
.task-alert.el-alert--info {
  background: rgba(111, 211, 242, .05);
  border: 1px solid rgba(111, 211, 242, .14);
  border-left: 2px solid rgba(111, 211, 242, .55);
}
.task-alert.el-alert--success {
  background: rgba(52, 211, 153, .05);
  border: 1px solid rgba(52, 211, 153, .14);
  border-left: 2px solid rgba(52, 211, 153, .55);
}
.task-alert.el-alert--warning {
  background: rgba(251, 191, 36, .05);
  border: 1px solid rgba(251, 191, 36, .16);
  border-left: 2px solid rgba(251, 191, 36, .55);
}
.task-alert.el-alert--error {
  background: rgba(251, 113, 133, .06);
  border: 1px solid rgba(251, 113, 133, .18);
  border-left: 2px solid rgba(251, 113, 133, .6);
}

/* ---------- 表格 ---------- */

.el-table {
  --el-table-border-color: var(--line);
  --el-table-header-bg-color: var(--panel-deep);
  --el-table-header-text-color: var(--text-low);
  --el-table-bg-color: var(--panel);
  --el-table-tr-bg-color: var(--panel);
  --el-table-row-hover-bg-color: rgba(111, 211, 242, .07);
  --el-table-fixed-column-bg: var(--panel);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.el-table th.el-table__cell {
  font-weight: 600;
  font-size: 11.5px;
  letter-spacing: .06em;
}
.el-table .cell { line-height: 1.55; }
.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell {
  background: #111b2f;
}
.el-table--enable-row-hover .el-table__body tr:hover > td.el-table__cell {
  background: var(--el-table-row-hover-bg-color);
}

.repo-title { display: flex; align-items: center; gap: 8px; }
.repo-name {
  font-weight: 600;
  color: #dce8f6;
  text-decoration: none;
  transition: color .15s;
}
.repo-name:hover { color: var(--ice-soft); text-shadow: 0 0 10px rgba(111, 211, 242, .35); }
.repo-desc { color: #93a5bd; font-size: 12px; margin-top: 2px; }
.repo-age { color: var(--text-low); font-size: 12px; }
.repo-push { color: var(--text-mid); font-size: 12px; margin-top: 2px; }
.repo-push.stale { color: var(--amber); }
.repo-attr { color: var(--ice); margin-right: 8px; font-family: var(--font-mono); font-size: 11.5px; }
.label-tag { margin-right: 4px; }
.issue-summary { font-size: 13px; color: var(--text-mid); }
.issue-action { font-size: 12px; color: var(--amber); margin-top: 4px; }
.body-cut { font-size: 12px; }
.zh-desc {
  font-size: 12px;
  color: #a4b4c9;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.55;
}
.repo-tags { margin-top: 4px; }
.tag-chip { margin-right: 4px; cursor: pointer; }

.match-cell { display: flex; align-items: center; gap: 8px; }
.match-bar { width: 90px; }
.match-num { font-weight: 700; color: var(--text-hi); }
.el-progress-bar__outer { background: rgba(255, 255, 255, .08); }

/* ---------- 标签 ---------- */

.el-tag { border-radius: 5px; font-size: 11.5px; }
.el-tag--primary {
  --el-tag-bg-color: rgba(111, 211, 242, .10);
  --el-tag-border-color: rgba(111, 211, 242, .32);
  --el-tag-text-color: var(--ice-soft);
}
.el-tag--success {
  --el-tag-bg-color: rgba(52, 211, 153, .10);
  --el-tag-border-color: rgba(52, 211, 153, .32);
  --el-tag-text-color: #6ee7b7;
}
.el-tag--warning {
  --el-tag-bg-color: rgba(251, 191, 36, .10);
  --el-tag-border-color: rgba(251, 191, 36, .32);
  --el-tag-text-color: #fcd34d;
}
.el-tag--danger {
  --el-tag-bg-color: rgba(251, 113, 133, .10);
  --el-tag-border-color: rgba(251, 113, 133, .32);
  --el-tag-text-color: #fda4af;
}
.el-tag--info {
  --el-tag-bg-color: rgba(132, 150, 176, .10);
  --el-tag-border-color: rgba(132, 150, 176, .30);
  --el-tag-text-color: #a8b7cc;
}

/* ---------- 按钮：HUD 描边辉光（无实心填充） ----------
   形制统一为「透明暗底 + 类型色描边 + 同色文字」：常态克制，hover 点亮边框并外扩辉光，
   按压内收。类型色经 --btn-accent（R,G,B）供 box-shadow 复用；link 变体不吃底色。 */

.el-button {
  border-radius: 7px;
  font-family: var(--font-display);
  letter-spacing: .02em;
  transition: color .18s, background-color .18s, border-color .18s, box-shadow .18s;
}
/* 无类型的默认按钮：中性细描边 */
html.dark .el-button {
  --btn-accent: 148, 180, 220;
  --el-button-text-color: var(--text-mid);
  --el-button-bg-color: rgba(148, 180, 220, .04);
  --el-button-border-color: rgba(148, 180, 220, .26);
  --el-button-hover-text-color: var(--text-hi);
  --el-button-hover-bg-color: rgba(148, 180, 220, .10);
  --el-button-hover-border-color: rgba(148, 180, 220, .52);
  --el-button-active-text-color: var(--text-hi);
  --el-button-active-bg-color: rgba(148, 180, 220, .14);
  --el-button-active-border-color: rgba(148, 180, 220, .62);
  --el-button-disabled-text-color: var(--text-low);
  --el-button-disabled-bg-color: transparent;
  --el-button-disabled-border-color: rgba(148, 180, 220, .14);
}
html.dark .el-button--primary {
  --btn-accent: 111, 211, 242;
  --el-button-text-color: var(--ice);
  --el-button-bg-color: rgba(111, 211, 242, .07);
  --el-button-border-color: rgba(111, 211, 242, .48);
  --el-button-hover-text-color: #b5ecfb;
  --el-button-hover-bg-color: rgba(111, 211, 242, .16);
  --el-button-hover-border-color: var(--ice);
  --el-button-active-text-color: #e2f7fe;
  --el-button-active-bg-color: rgba(111, 211, 242, .24);
  --el-button-active-border-color: #a4e2f8;
  --el-button-disabled-text-color: rgba(111, 211, 242, .38);
  --el-button-disabled-bg-color: rgba(111, 211, 242, .03);
  --el-button-disabled-border-color: rgba(111, 211, 242, .18);
}
html.dark .el-button--success {
  --btn-accent: 52, 211, 153;
  --el-button-text-color: #6ee7b7;
  --el-button-bg-color: rgba(52, 211, 153, .07);
  --el-button-border-color: rgba(52, 211, 153, .46);
  --el-button-hover-text-color: #9ff3cf;
  --el-button-hover-bg-color: rgba(52, 211, 153, .15);
  --el-button-hover-border-color: var(--mint);
  --el-button-active-text-color: #d3fae8;
  --el-button-active-bg-color: rgba(52, 211, 153, .22);
  --el-button-active-border-color: #7fe7bb;
  --el-button-disabled-text-color: rgba(52, 211, 153, .38);
  --el-button-disabled-bg-color: rgba(52, 211, 153, .03);
  --el-button-disabled-border-color: rgba(52, 211, 153, .18);
}
html.dark .el-button--warning {
  --btn-accent: 251, 191, 36;
  --el-button-text-color: #fcd34d;
  --el-button-bg-color: rgba(251, 191, 36, .06);
  --el-button-border-color: rgba(251, 191, 36, .48);
  --el-button-hover-text-color: #fde08a;
  --el-button-hover-bg-color: rgba(251, 191, 36, .14);
  --el-button-hover-border-color: var(--amber);
  --el-button-active-text-color: #fef0c6;
  --el-button-active-bg-color: rgba(251, 191, 36, .2);
  --el-button-active-border-color: #fcd765;
  --el-button-disabled-text-color: rgba(251, 191, 36, .38);
  --el-button-disabled-bg-color: rgba(251, 191, 36, .03);
  --el-button-disabled-border-color: rgba(251, 191, 36, .18);
}
html.dark .el-button--danger {
  --btn-accent: 251, 113, 133;
  --el-button-text-color: #fda4af;
  --el-button-bg-color: rgba(251, 113, 133, .06);
  --el-button-border-color: rgba(251, 113, 133, .48);
  --el-button-hover-text-color: #fec4cc;
  --el-button-hover-bg-color: rgba(251, 113, 133, .14);
  --el-button-hover-border-color: var(--rose);
  --el-button-active-text-color: #fee3e8;
  --el-button-active-bg-color: rgba(251, 113, 133, .2);
  --el-button-active-border-color: #fd8ba0;
  --el-button-disabled-text-color: rgba(251, 113, 133, .38);
  --el-button-disabled-bg-color: rgba(251, 113, 133, .03);
  --el-button-disabled-border-color: rgba(251, 113, 133, .18);
}

/* 共同形制：顶缘高光（机加工感）；hover 外扩辉光；按压内收；键盘焦点圈 */
html.dark .el-button:not(.is-link):not(.is-text) {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .045);
}
html.dark .el-button:not(.is-link):not(.is-text):not(.is-disabled):hover {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .07),
              0 0 16px rgba(var(--btn-accent), .24),
              inset 0 0 14px rgba(var(--btn-accent), .08);
}
html.dark .el-button:not(.is-link):not(.is-text):not(.is-disabled):active {
  box-shadow: inset 0 2px 8px rgba(0, 0, 0, .35), inset 0 0 10px rgba(var(--btn-accent), .12);
}
html.dark .el-button:not(.is-link):focus-visible {
  outline: none;
  box-shadow: 0 0 0 1px rgba(var(--btn-accent), .8), 0 0 18px rgba(var(--btn-accent), .3);
}
html.dark .el-button.is-link { background: transparent; }

/* ---------- 输入 ---------- */

html.dark .el-input__wrapper {
  background: rgba(8, 13, 26, .55);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--line) inset;
}
html.dark .el-input__wrapper:hover { box-shadow: 0 0 0 1px var(--line-strong) inset; }
html.dark .el-input__wrapper.is-focus {
  box-shadow: 0 0 0 1px rgba(111, 211, 242, .65) inset, 0 0 14px rgba(111, 211, 242, .15);
}
html.dark .el-textarea__inner {
  background: rgba(8, 13, 26, .55);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--line) inset;
}

/* ---------- 弹层：抽屉 / 对话框 ---------- */

.el-drawer { --el-drawer-bg-color: #0d1526; }
.el-drawer__header {
  margin-bottom: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
  color: var(--text-hi);
  font-family: var(--font-display);
  font-weight: 600;
  letter-spacing: .03em;
}
.el-dialog {
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  background: #0e1728;
  box-shadow: 0 30px 80px -20px rgba(0, 0, 0, .65);
}
.el-dialog__header { padding-bottom: 12px; border-bottom: 1px solid var(--line); }
.el-dialog__title { color: var(--text-hi); font-weight: 600; letter-spacing: .04em; }
.el-message-box {
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  background: var(--el-bg-color-overlay);
}
.el-message-box__title { color: var(--text-hi); }

/* 详情抽屉 / 报告弹窗内容 */
h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 22px 0 10px;
  font-family: var(--font-display);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: .12em;
  color: var(--ice);
}
h4::before {
  content: '';
  width: 5px;
  height: 5px;
  background: var(--ice);
  transform: rotate(45deg);
  box-shadow: 0 0 8px rgba(111, 211, 242, .6);
}
.detail-stats { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.detail-actions { margin-top: 20px; }
.case-item {
  padding: 9px 12px;
  background: rgba(255, 255, 255, .028);
  border: 1px solid var(--line);
  border-radius: 8px;
  margin-bottom: 8px;
}
.evidence { color: var(--text-low); font-size: 12px; margin-top: 4px; }
.muted { color: var(--text-low); }
.score-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.score-name { width: 130px; font-size: 13px; flex-shrink: 0; color: var(--text-mid); }
.score-bar { flex: 0 0 160px; }
.score-reason { font-size: 12px; color: var(--text-low); }
.verdict.el-card {
  background: rgba(52, 211, 153, .05);
  border: 1px solid rgba(52, 211, 153, .22);
  border-radius: 10px;
  margin-bottom: 12px;
}
.issue-card.el-card {
  background: rgba(255, 255, 255, .02);
  border: 1px solid var(--line);
  border-radius: 10px;
  margin-bottom: 12px;
}
.diff-tag { margin-left: 10px; }
.dir-tag { margin-right: 6px; }
.result-pre {
  white-space: pre-wrap;
  word-break: break-word;
  background: #0a101f;
  border: 1px solid var(--line);
  border-left: 2px solid rgba(111, 211, 242, .55);
  border-radius: 8px;
  padding: 14px 16px;
  font-size: 12.5px;
  font-family: var(--font-mono);
  color: #c6d8ec;
  max-height: 60vh;
  overflow-y: auto;
}

/* 行业报告 markdown 正文 */
.md-body { font-size: 14px; line-height: 1.85; color: var(--text-mid); margin-bottom: 8px; }
.md-body h3, .md-body h4, .md-body h5 { margin: 16px 0 8px; color: var(--text-hi); }
.md-body p { margin: 8px 0; }
.md-body ul { margin: 8px 0; padding-left: 22px; }
.md-body a { color: var(--ice-soft); }
.md-body b { color: var(--text-hi); }

/* ---------- 卡片（课程 / 技能） ---------- */

.course-col { margin-bottom: 14px; }
.course-card.el-card {
  position: relative;
  overflow: hidden;
  background: linear-gradient(180deg, #121c33, #0e1626);
  border: 1px solid var(--line);
  border-radius: 12px;
  height: 100%;
  transition: transform .25s, border-color .25s, box-shadow .25s;
}
.course-card.el-card::before {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 52px;
  height: 52px;
  background: radial-gradient(circle at 100% 0%, rgba(111, 211, 242, .16), transparent 70%);
}
.course-card.el-card:hover {
  transform: translateY(-3px);
  border-color: rgba(111, 211, 242, .42);
  box-shadow: 0 16px 32px -14px rgba(0, 0, 0, .5), 0 0 22px rgba(111, 211, 242, .08);
}
.course-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.course-title { font-weight: 700; font-size: 15px; line-height: 1.4; color: var(--text-hi); }
.course-meta { margin: 6px 0 10px; }
.course-lessons { border-top: 1px dashed var(--line-strong); padding-top: 8px; margin-bottom: 12px; }
.lesson-row { display: flex; align-items: center; gap: 6px; padding: 3px 0; font-size: 13px; }
.lesson-check { flex-shrink: 0; }
.lesson-name { flex: 1; color: var(--text-mid); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lesson-score { color: #6ee7b7; font-weight: 600; font-size: 12px; flex-shrink: 0; font-family: var(--font-mono); }
.course-actions { text-align: right; }
.skill-desc {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 3.4em;
}
.skill-hint { font-size: 12px; color: var(--amber); margin-bottom: 10px; font-family: var(--font-mono); }
.skill-hist-title {
  margin: 24px 0 10px;
  font-family: var(--font-display);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: .12em;
  color: var(--ice);
}

/* 技能表单 */
.skill-field { margin-bottom: 14px; }
.skill-field-label { font-size: 13px; color: var(--text-mid); margin-bottom: 6px; }
.skill-field-label .req { color: var(--rose); margin-left: 2px; }
.skill-radios { display: flex; flex-direction: column; gap: 4px; align-items: normal; }
.skill-radios .el-radio { margin-right: 0; height: auto; white-space: normal; }
.skill-course-warn { margin-top: 2px; }
.skill-local-tip { margin-top: 12px; }

/* ---------- 学习模块化：教材书架 / 导入教程包 ---------- */

.book-upload { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; }
.file-input {
  color: var(--text-mid);
  font-size: 13px;
  max-width: 240px;
}
.file-input::file-selector-button {
  background: rgba(111, 211, 242, .12);
  color: var(--ice);
  border: 1px solid rgba(111, 211, 242, .45);
  border-radius: 4px;
  padding: 5px 12px;
  margin-right: 10px;
  cursor: pointer;
}
.book-row {
  border-top: 1px solid var(--line);
  padding: 10px 2px 8px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.book-row:first-of-type { border-top: none; }
.book-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.book-title {
  font-family: 'Chakra Petch', var(--el-font-family);
  font-size: 14px;
  color: var(--text-hi);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.book-status { flex: none; }
.book-actions { flex: none; display: flex; gap: 2px; }
.book-note { flex-basis: 100%; font-size: 12px; color: var(--rose); opacity: .85; }
.series-list { max-height: 46vh; overflow: auto; margin-top: 6px; }
.series-check { display: flex; width: 100%; }
.series-check .muted { font-weight: 400; }

/* ---------- 脚手架详情 ---------- */

.scaffold-raw {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-hi);
  background: rgba(111, 211, 242, .05);
  border-left: 2px solid rgba(111, 211, 242, .6);
  border-radius: 4px;
  padding: 9px 13px;
}
.scaffold-fit-tag { margin-left: 8px; }
.adopt-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: rgba(52, 211, 153, .05);
  border: 1px solid rgba(52, 211, 153, .22);
  border-radius: 8px;
}
.adopt-clone { max-width: 560px; }
.split-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.stack-select { width: 140px; }
.split-row { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px dashed var(--line); }
.split-no {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--ice);
  color: #04222e;
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-mono);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 4px;
}
.split-fields { flex: 1; display: flex; flex-direction: column; gap: 6px; }
.split-line1 { display: flex; gap: 8px; align-items: center; }
.split-name { width: 180px; flex-shrink: 0; }
.split-kw { flex: 1; }
.sel-item { padding: 10px 0; border-bottom: 1px dashed var(--line); }
.sel-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; flex-wrap: wrap; }
.sel-desc { font-size: 12px; }
.sel-radios { display: flex; flex-direction: column; gap: 2px; align-items: normal; }
.sel-radios .el-radio { margin-right: 0; height: auto; white-space: normal; line-height: 1.7; }
.sel-reason { font-size: 12px; }
.six-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px 16px; margin-bottom: 12px; }
.six-item { font-size: 13px; color: var(--text-mid); }

/* ---------- 行业洞察 ---------- */

.industry-input { width: 320px; }
.parse-section {
  font-size: 13px;
  font-weight: 600;
  color: var(--ice);
  letter-spacing: .04em;
  margin: 10px 0 6px;
}
.parse-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.parse-raw { min-width: 90px; font-size: 13px; color: var(--text-hi); }
.parse-select { flex: 1; }
.parse-cand-desc {
  color: var(--text-low);
  font-size: 12px;
  margin-left: 8px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.industry-group { margin-bottom: 14px; }
.industry-cat {
  font-weight: 600;
  font-size: 13.5px;
  color: var(--text-hi);
  margin-bottom: 6px;
  padding: 5px 10px;
  background: rgba(111, 211, 242, .05);
  border-left: 2px solid rgba(111, 211, 242, .6);
  border-radius: 3px;
}
.industry-project { display: flex; align-items: center; gap: 10px; padding: 5px 12px; font-size: 13px; }
.industry-project:hover { background: rgba(111, 211, 242, .04); }
.industry-stars { flex-shrink: 0; font-size: 12px; font-family: var(--font-mono); }
.industry-pos { flex: 1; color: var(--text-low); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ---------- 分页 / 空态 ---------- */

.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
.el-pagination { --el-pagination-bg-color: transparent; --el-pagination-button-disabled-bg-color: transparent; }
.el-pagination .el-pager li { color: var(--text-mid); background: transparent; border-radius: 6px; }
.el-pagination .el-pager li:hover { color: var(--text-hi); }
.el-pagination .el-pager li.is-active {
  color: var(--ice);
  background: rgba(111, 211, 242, .1);
  text-shadow: 0 0 8px rgba(111, 211, 242, .5);
}
.el-pagination button { background-color: transparent; color: var(--text-mid); }
.el-pagination .el-pagination__total { color: var(--text-low); font-size: 12px; font-family: var(--font-mono); }
.el-empty__description p { color: var(--text-low); }

/* ---------- 右下角任务中心 ----------
   z-index 2400 压过 el-drawer/el-dialog（popup 基准 2000+）：
   脚手架流程就是抽屉开着跑 338s 生成任务，进度卡必须始终可见 */
.task-center { position: fixed; right: 20px; bottom: 20px; width: 380px; max-width: calc(100vw - 40px); z-index: 2400; }
.tc-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  background: linear-gradient(92deg, #16213a, #0e1728);
  border: 1px solid var(--line-strong);
  border-bottom: none;
  border-radius: 12px 12px 0 0;
  color: var(--text-hi);
  font-size: 13px;
}
.tc-title { font-weight: 600; letter-spacing: .04em; }
.tc-count { flex: 1; color: var(--text-low); font-size: 12px; font-family: var(--font-mono); }
.tc-clear, .tc-min { cursor: pointer; color: var(--text-low); font-size: 12px; padding: 0 4px; }
.tc-clear:hover, .tc-min:hover { color: var(--ice-soft); }
.tc-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: min(60vh, 520px);
  overflow-y: auto;
  padding: 10px;
  background: rgba(12, 19, 35, .92);
  backdrop-filter: blur(14px);
  border: 1px solid var(--line-strong);
  border-top: none;
  border-radius: 0 0 12px 12px;
  box-shadow: 0 18px 44px -18px rgba(0, 0, 0, .65);
}
.tc-card { position: relative; background: #0e1728; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.tc-card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--tc-accent, var(--ice)); }
.tc-running { --tc-accent: #6fd3f2; }
.tc-waiting { --tc-accent: #fbbf24; animation: tc-pulse 2s ease-in-out infinite; }
.tc-success { --tc-accent: #34d399; }
.tc-failed { --tc-accent: #fb7185; }
@keyframes tc-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(251, 191, 36, .35); }
  50% { box-shadow: 0 0 0 5px rgba(251, 191, 36, 0); }
}
/* 运行/等待态顶部细进度条：无真实百分比，走 indeterminate 扫动 */
.tc-bar { position: relative; height: 3px; overflow: hidden; background: rgba(255, 255, 255, .06); }
.tc-bar::after { content: ''; position: absolute; top: 0; left: -40%; width: 40%; height: 100%; background: var(--tc-accent); animation: tc-slide 1.6s ease-in-out infinite; }
@keyframes tc-slide { 0% { left: -40%; } 100% { left: 100%; } }
.tc-row { display: flex; align-items: center; gap: 8px; padding: 8px 12px 0 14px; cursor: pointer; }
.tc-icon { flex-shrink: 0; font-size: 13px; font-weight: 700; color: var(--tc-accent, var(--ice)); }
.tc-running .tc-icon { display: inline-block; animation: tc-spin 1.1s linear infinite; }
@keyframes tc-spin { to { transform: rotate(360deg); } }
.tc-what { flex: 1; font-size: 13px; font-weight: 600; color: var(--text-hi); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tc-elapsed { flex-shrink: 0; color: var(--text-low); font-size: 12px; font-variant-numeric: tabular-nums; font-family: var(--font-mono); }
.tc-toggle { flex-shrink: 0; color: var(--text-low); font-size: 11px; }
.tc-msg { padding: 3px 12px 8px 14px; font-size: 12px; color: var(--text-mid); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tc-err { color: var(--rose); }
.tc-card .task-logs { max-height: 180px; border-top: 1px dashed var(--line); }
.tc-foot { display: flex; align-items: center; gap: 10px; padding: 6px 12px 8px 14px; border-top: 1px dashed var(--line); font-size: 12px; }
.tc-foot-gap { flex: 1; }
/* waiting 应答表单 */
.tc-ask {
  margin: 0 12px 10px 14px;
  padding: 10px 12px;
  background: rgba(251, 191, 36, .06);
  border: 1px solid rgba(251, 191, 36, .24);
  border-radius: 8px;
}
.tc-q { margin-bottom: 10px; }
.tc-q-text { font-size: 13px; font-weight: 600; color: var(--text-hi); margin-bottom: 6px; }
.tc-q-desc { color: var(--text-low); font-weight: 400; font-size: 12px; }
.tc-choices { display: flex; flex-direction: column; gap: 4px; align-items: normal; }
.tc-option { height: auto; white-space: normal; line-height: 1.6; margin-right: 0; }
.tc-other-input { margin-top: 6px; }
.tc-ask-actions { display: flex; justify-content: flex-end; gap: 8px; }
.tc-answered { padding: 0 12px 8px 14px; font-size: 12px; color: #6ee7b7; }
/* 收起态胶囊 */
.tc-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #0e1728;
  border: 1px solid var(--line-strong);
  color: var(--text-hi);
  padding: 8px 16px;
  border-radius: 999px;
  font-size: 13px;
  cursor: pointer;
  box-shadow: 0 10px 28px -10px rgba(0, 0, 0, .6);
  user-select: none;
  transition: border-color .2s;
}
.tc-pill:hover { border-color: rgba(111, 211, 242, .5); }
.tc-pill-spin { width: 12px; height: 12px; border: 2px solid var(--text-low); border-top-color: var(--ice); border-radius: 50%; animation: tc-spin 1s linear infinite; }
.tc-pill-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--mint); box-shadow: 0 0 8px rgba(52, 211, 153, .7); }

/* 任务日志 */
.task-logs { max-height: 260px; overflow-y: auto; background: #0a0f1e; padding: 8px 14px; }
.log-line { font-family: var(--font-mono); font-size: 12px; line-height: 1.7; color: var(--text-mid); word-break: break-word; }
.log-time { margin-right: 8px; color: var(--text-low); }

/* ---------- 动效偏好 ---------- */

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
  .brand-mark { animation: none !important; }
}
</style>

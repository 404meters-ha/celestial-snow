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
      <el-tabs v-model="activeTab" class="main-tabs">
        <!-- ================= 项目榜 ================= -->
        <el-tab-pane name="repos">
          <template #label>
            <span class="tab-label">📦 项目榜</span>
          </template>

          <el-alert v-if="runningTask" :title="`后台任务运行中：${runningTask.progress || '处理中…'}`" type="info"
            :closable="false" show-icon class="task-alert" />

          <div class="toolbar">
            <el-radio-group v-model="periodFilter">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="weekly">周榜</el-radio-button>
              <el-radio-button value="monthly">月榜</el-radio-button>
            </el-radio-group>
            <el-radio-group v-model="sort" @change="loadRepos">
              <el-radio-button value="total">综合分</el-radio-button>
              <el-radio-button value="rule">规则分</el-radio-button>
              <el-radio-button value="stars">Star 数</el-radio-button>
            </el-radio-group>
            <el-input v-model="q" placeholder="搜索项目名 / 描述" clearable class="search" @input="debouncedLoad" />
            <span class="picked-hint">已选 {{ picked.length }}/5</span>
            <el-button type="success" :disabled="picked.length === 0" :loading="contributing" @click="analyzeContribution">
              分析贡献机会
            </el-button>
          </div>

          <el-table :data="filteredRepos" v-loading="loading" @selection-change="onSelect" row-key="id" stripe>
            <el-table-column type="selection" width="42" />
            <el-table-column label="项目" min-width="300">
              <template #default="{ row }">
                <div class="repo-title">
                  <a :href="`https://github.com/${row.full_name}`" target="_blank" class="repo-name">{{ row.full_name }}</a>
                  <el-tag v-if="periodLabel(row.periods)" :type="row.periods.length > 1 ? 'danger' : 'primary'"
                    size="small" effect="plain">{{ periodLabel(row.periods) }}</el-tag>
                </div>
                <div class="repo-desc">{{ row.description }}</div>
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
            <el-table-column label="操作" width="170" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">详情</el-button>
                <el-button v-if="row.latest_report" link type="success" @click="openReport(row.latest_report.id)">
                  贡献报告
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ================= Issue 榜 ================= -->
        <el-tab-pane name="issues">
          <template #label>
            <span class="tab-label">🐛 Issue 榜</span>
          </template>

          <el-alert type="success" :closable="false" show-icon class="task-alert"
            title="按「与我的技能匹配度」排序的 issue 排行榜——分数越高，越适合你上手成为贡献者" />

          <div class="toolbar">
            <el-radio-group v-model="issueSort" @change="loadIssues">
              <el-radio-button value="match">匹配度</el-radio-button>
              <el-radio-button value="rule">规则预分</el-radio-button>
              <el-radio-button value="latest">最新更新</el-radio-button>
            </el-radio-group>
            <el-select v-model="issueDifficulty" clearable placeholder="难度" class="diff-select" @change="loadIssues">
              <el-option value="低" label="难度：低" />
              <el-option value="中" label="难度：中" />
              <el-option value="高" label="难度：高" />
            </el-select>
            <el-checkbox v-model="issueDeepOnly" @change="loadIssues">只看已深读</el-checkbox>
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
                  <el-tag size="small" :type="s.scope === 'project' ? 'primary' : 'info'">
                    {{ s.scope === 'project' ? '项目级' : '全局' }}
                  </el-tag>
                </div>
                <div class="repo-desc skill-desc">{{ s.description }}</div>
                <div v-if="s.argument_hint" class="skill-hint">参数：{{ s.argument_hint }}</div>
                <div class="course-actions">
                  <el-button type="primary" size="small" @click="openSkill(s)">运行</el-button>
                </div>
              </el-card>
            </el-col>
          </el-row>

          <h3 class="skill-hist-title">最近执行</h3>
          <el-table :data="skillTasks" size="small" row-key="id" stripe>
            <el-table-column label="技能" width="150">
              <template #default="{ row }">/{{ row.payload?.skill }}</template>
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

    <!-- 技能运行参数对话框 -->
    <el-dialog v-model="skillDialog" :title="`运行 /${currentSkill?.name}`" width="560px">
      <p v-if="currentSkill" class="muted">{{ currentSkill.description }}</p>
      <el-input v-model="skillArgs" :placeholder="currentSkill?.argument_hint || '参数（可空）'"
        @keyup.enter="runSkill" />
      <template #footer>
        <el-button @click="skillDialog = false">取消</el-button>
        <el-button type="primary" :loading="invoking" @click="runSkill">执行</el-button>
      </template>
    </el-dialog>

    <!-- 技能结果对话框 -->
    <el-dialog v-model="resultDialog" :title="`/${resultTask?.payload?.skill} 执行结果`" width="72%" top="4vh">
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getConfig, getCourses, getIssues, getRepo, getRepos, getReport, getSkills, getTasks, invokeSkill, postContribute, postRefresh } from './api'

const activeTab = ref('repos')
const repos = ref([])
const issues = ref([])
const loading = ref(false)
const issueLoading = ref(false)
const sort = ref('total')
const q = ref('')
const periodFilter = ref('all')
const picked = ref([])
const config = ref(null)
const detailVisible = ref(false)
const detail = ref(null)
const reportVisible = ref(false)
const report = ref(null)
const refreshing = ref(false)
const contributing = ref(false)
const runningTask = ref(null)
const issueSort = ref('match')
const issueDifficulty = ref('')
const issueDeepOnly = ref(false)
const courses = ref([])
const coursesLoading = ref(false)
const skills = ref([])
const skillsLoading = ref(false)
const skillDialog = ref(false)
const currentSkill = ref(null)
const skillArgs = ref('')
const invoking = ref(false)
const skillTasks = ref([])
const resultDialog = ref(false)
const resultTask = ref(null)
let pollTimer = null
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

// 周榜/月榜筛选（客户端过滤 periods）
const filteredRepos = computed(() => {
  if (periodFilter.value === 'all') return repos.value
  return repos.value.filter((r) => (r.periods || []).includes(periodFilter.value))
})

function periodLabel(periods) {
  if (!periods || periods.length === 0) return ''
  if (periods.length > 1) return '双榜'
  return periods[0] === 'weekly' ? '周榜' : '月榜'
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
    repos.value = (await getRepos(sort.value, q.value)).repos
  } catch (e) {
    ElMessage.error(`加载榜单失败：${e.message}`)
  } finally {
    loading.value = false
  }
}

async function loadIssues() {
  issueLoading.value = true
  try {
    issues.value = (await getIssues({
      sort: issueSort.value,
      difficulty: issueDifficulty.value,
      deep_only: issueDeepOnly.value,
      limit: 200,
    })).issues
  } catch (e) {
    ElMessage.error(`加载 Issue 榜失败：${e.message}`)
  } finally {
    issueLoading.value = false
  }
}

function debouncedLoad() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(loadRepos, 300)
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
    skillTasks.value = (await getTasks(30)).tasks.filter((t) => t.type === 'skill')
  } catch { /* 忽略 */ }
}

function openSkill(s) {
  currentSkill.value = s
  skillArgs.value = ''
  skillDialog.value = true
}

async function runSkill() {
  invoking.value = true
  try {
    await invokeSkill(currentSkill.value.name, skillArgs.value)
    ElMessage.success(`技能 /${currentSkill.value.name} 已提交，进度见顶部提示`)
    skillDialog.value = false
    loadSkillTasks()
    startPolling(loadSkillTasks)
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
    runningTask.value = tasks.find((t) => t.status === 'running') || null
    if (!runningTask.value) {
      stopPolling()
      return true // 刚结束
    }
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
  if (tab === 'learning') loadCourses() // 每次进入都刷新，/tech 生成后能看到新课程
  if (tab === 'skills') { loadSkills(); loadSkillTasks() }
})

onMounted(async () => {
  await loadRepos()
  config.value = await getConfig().catch(() => null)
  pollOnce()
})
onBeforeUnmount(stopPolling)
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
.picked-hint { color: #8a919f; font-size: 13px; margin-left: auto; }
.task-alert { margin-bottom: 14px; }
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
</style>

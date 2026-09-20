const BASE = ''

async function apiGet(path) {
  const res = await fetch(BASE + path)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text.slice(0, 200)}`)
  }
  return res.json()
}

async function apiPost(path, body) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || `${res.status} 请求失败`)
  }
  return data
}

// 项目榜：分页（limit/offset）+ 精析状态（analyzed=all|done|todo）+ 榜单期次（period）+ 标签（tag）
export const getRepos = (params = {}) => {
  const qs = new URLSearchParams()
  if (params.sort) qs.set('sort', params.sort)
  if (params.q) qs.set('q', params.q)
  if (params.limit) qs.set('limit', params.limit)
  if (params.offset) qs.set('offset', params.offset)
  if (params.analyzed && params.analyzed !== 'all') qs.set('analyzed', params.analyzed)
  if (params.period) qs.set('period', params.period)
  if (params.tag) qs.set('tag', params.tag)
  return apiGet(`/api/repos?${qs}`)
}
export const getRepo = (fullName) => apiGet(`/api/repos/${fullName}`)
export const getReport = (id) => apiGet(`/api/reports/${id}`)
export const getTasks = (limit = 10) => apiGet(`/api/tasks?limit=${limit}`)
// 单个任务（含 logs 时间线）：列表接口不带 logs，进度面板与刷新恢复用这个
export const getTask = (id) => apiGet(`/api/tasks/${id}`)
export const getConfig = () => apiGet('/api/config')
export const getIssues = (params = {}) => {
  const qs = new URLSearchParams()
  if (params.sort) qs.set('sort', params.sort)
  if (params.difficulty) qs.set('difficulty', params.difficulty)
  if (params.repo) qs.set('repo', params.repo)
  if (params.deep_only) qs.set('deep_only', 'true')
  if (params.limit) qs.set('limit', params.limit)
  if (params.offset) qs.set('offset', params.offset)
  if (params.analyzed && params.analyzed !== 'all') qs.set('analyzed', params.analyzed)
  return apiGet(`/api/issues?${qs}`)
}
// Issue 榜筛选器：有 issue 的项目清单（含条数）
export const getIssueRepos = () => apiGet('/api/issue-repos')
export const postRefresh = () => apiPost('/api/refresh')
export const postContribute = (repoIds) => apiPost('/api/contributions', { repo_ids: repoIds })
// 批量精析选中的项目（「未精析」队列入口）
export const postAnalyze = (repoIds) => apiPost('/api/repos/analyze', { repo_ids: repoIds })
// 标签 / 定向行业分析
export const getTags = () => apiGet('/api/tags')
export const postAutoTag = () => apiPost('/api/tags/auto')
export const getIndustries = () => apiGet('/api/industries')
export const getIndustry = (id) => apiGet(`/api/industries/${id}`)
export const postIndustry = (name) => apiPost('/api/industries', { name })
// 学习闭环：/tech 取上下文、注册课程；课程 HTML 静态托管在 /courses/{id}/
export const getLearningContext = (issueId) => apiGet(`/api/learning-context/${issueId}`)
export const postCourse = (payload) => apiPost('/api/courses', payload)
export const getCourses = () => apiGet('/api/courses')
export const getCourse = (id) => apiGet(`/api/courses/${id}`)
export const postQuizResult = (payload) => apiPost('/api/quiz-results', payload)
// 通用技能调用：内置 Agent SDK 执行（SKILL.md 正文注入 prompt），技能文件现读即时生效
export const getSkills = () => apiGet('/api/skills')
export const invokeSkill = (name, args = '') => apiPost(`/api/skills/${name}/invoke`, { args })
// 页面 AI 命令栏：自由指令（/开头即技能）
export const runAgent = (prompt) => apiPost('/api/agent/run', { prompt })

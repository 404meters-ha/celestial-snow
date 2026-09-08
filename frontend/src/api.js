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

export const getRepos = (sort = 'total', q = '', limit = 100) =>
  apiGet(`/api/repos?sort=${sort}&q=${encodeURIComponent(q)}&limit=${limit}`)
export const getRepo = (fullName) => apiGet(`/api/repos/${fullName}`)
export const getReport = (id) => apiGet(`/api/reports/${id}`)
export const getTasks = (limit = 10) => apiGet(`/api/tasks?limit=${limit}`)
export const getConfig = () => apiGet('/api/config')
export const getIssues = (params = {}) => {
  const qs = new URLSearchParams()
  if (params.sort) qs.set('sort', params.sort)
  if (params.difficulty) qs.set('difficulty', params.difficulty)
  if (params.repo) qs.set('repo', params.repo)
  if (params.deep_only) qs.set('deep_only', 'true')
  if (params.limit) qs.set('limit', params.limit)
  return apiGet(`/api/issues?${qs}`)
}
export const postRefresh = () => apiPost('/api/refresh')
export const postContribute = (repoIds) => apiPost('/api/contributions', { repo_ids: repoIds })
// 学习闭环：/tech 取上下文、注册课程；课程 HTML 静态托管在 /courses/{id}/
export const getLearningContext = (issueId) => apiGet(`/api/learning-context/${issueId}`)
export const postCourse = (payload) => apiPost('/api/courses', payload)
export const getCourses = () => apiGet('/api/courses')
export const getCourse = (id) => apiGet(`/api/courses/${id}`)
export const postQuizResult = (payload) => apiPost('/api/quiz-results', payload)

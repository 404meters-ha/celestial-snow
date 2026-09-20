"""REST API：榜单、详情、刷新、贡献分析、issue 排行、任务进度、学习闭环。"""
import json
import re
import shutil

from sqlalchemy import and_, delete, func, or_, select

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .config import get_settings
from .db import SessionLocal
from .models import (
    Analysis,
    ContributionReport,
    Course,
    IndustryReport,
    Issue,
    QuizResult,
    Repo,
    TaskRun,
    utcnow,
)
from .services import course_publish, oss, scoring
from .services.github_client import GitHubClient
from .services.industry import (
    multi_industry_pipeline,
    parse_input,
    tagging_pipeline,
    translate_pipeline,
)
from .services.llm import LLMNotConfigured
from .services.pipeline import (
    MAX_ANALYZE_REPOS,
    MAX_CONTRIB_REPOS,
    _upsert_repo,
    analyze_pipeline,
    contribution_pipeline,
    refresh_pipeline,
)
from .tasks import manager

router = APIRouter(prefix="/api")


# ---------- 榜单 ----------

def _repo_view(repo: Repo, analysis: Analysis | None) -> dict:
    return {
        "id": repo.id,
        "full_name": repo.full_name,
        "description": repo.description,
        "zh_desc": repo.zh_desc or "",
        "language": repo.language,
        "topics": repo.topics or [],
        "homepage": repo.homepage,
        "license": repo.license,
        "stars": repo.stars,
        "open_issues": repo.open_issues,
        "contributors_count": repo.contributors_count,
        "periods": repo.periods or [],
        "tags": repo.tags or [],
        "rule_score": repo.rule_score,
        "rule_detail": repo.rule_detail or {},
        "total_score": repo.total_score,
        "first_seen_at": repo.first_seen_at.isoformat() if repo.first_seen_at else None,
        "github_created_at": repo.github_created_at.isoformat() if repo.github_created_at else None,
        "pushed_at": repo.pushed_at.isoformat() if repo.pushed_at else None,
        "analyzed": bool(analysis and analysis.status == "done"),
        "ai_analyzed": bool(analysis and analysis.note.startswith("AI")),
        "core_idea": analysis.core_idea if analysis else "",
        "enterprise_cases": analysis.enterprise_cases if analysis else [],
        "llm_scores": analysis.llm_scores if analysis else {},
    }


def _json_like(value: str) -> str:
    """JSON 列的 LIKE 模式：SQLAlchemy 落库走 json.dumps（默认 ensure_ascii），
    中文 tag 存成 "\\uXXXX"——模式必须同样转义，裸写 '%"中文"%' 永远匹配不到。"""
    return f"%{json.dumps(value)}%"


@router.get("/repos")
def list_repos(
    sort: str = "total",  # total | rule | stars
    q: str = "",  # full_name/description 模糊
    limit: int = 20,
    offset: int = 0,
    analyzed: str = "all",  # all | done（已精析）| todo（未精析，含 failed/skipped/无记录）
    period: str = "",  # weekly | monthly | 空=不限榜单期次
    tag: list[str] = Query(default=[]),  # 标签多选（AND 交集：同时具备全部所选标签）
):
    """项目榜：分页（limit/offset）+ 精析状态/榜单期次/标签过滤；total 供前端分页控件。"""
    with SessionLocal() as session:
        stmt = select(Repo, Analysis).outerjoin(Analysis, Analysis.repo_id == Repo.id)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(Repo.full_name.like(like) | Repo.description.like(like))
        if analyzed == "done":
            stmt = stmt.where(Analysis.status == "done")
        elif analyzed == "todo":
            # 无 Analysis 记录的行 status 为 NULL（NULL != 'done' 判不出真），必须显式 or
            stmt = stmt.where(or_(Analysis.id.is_(None), Analysis.status != "done"))
        if period in ("weekly", "monthly"):
            stmt = stmt.where(Repo.periods.like(_json_like(period)))
        if tag:
            conditions = [Repo.tags.like(_json_like(t)) for t in tag if t.strip()]
            if conditions:
                stmt = stmt.where(and_(*conditions))
        # id 兜底 tiebreaker：OFFSET 分页要求排序全序稳定
        if sort == "stars":
            stmt = stmt.order_by(Repo.stars.desc(), Repo.id.desc())
        elif sort == "rule":
            stmt = stmt.order_by(Repo.rule_score.desc(), Repo.id.desc())
        else:
            stmt = stmt.order_by(Repo.total_score.desc(), Repo.rule_score.desc(), Repo.id.desc())
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = session.execute(stmt.limit(min(limit, 200)).offset(max(offset, 0))).unique().all()
        # 最近一份贡献报告 id（行内「贡献报告」按钮）；只对查出的一页做，避免全表扫
        repo_ids = [repo.id for repo, _ in rows]
        report_ids: dict[int, int] = {}
        if repo_ids:
            report_rows = session.execute(
                select(ContributionReport.repo_id, func.max(ContributionReport.id))
                .where(ContributionReport.repo_id.in_(repo_ids))
                .group_by(ContributionReport.repo_id)
            ).all()
            report_ids = dict(report_rows)
        views = []
        for repo, analysis in rows:
            view = _repo_view(repo, analysis)
            view["latest_report"] = (
                {"id": report_ids[repo.id], "status": "done", "created_at": None}
                if repo.id in report_ids
                else None
            )
            views.append(view)
        return {"repos": views, "total": total}


@router.get("/repos/{full_name:path}")
def repo_detail(full_name: str):
    with SessionLocal() as session:
        repo = session.scalar(select(Repo).where(Repo.full_name == full_name))
        if repo is None:
            raise HTTPException(404, "仓库不在库中，请先刷新榜单")
        analysis = session.scalar(select(Analysis).where(Analysis.repo_id == repo.id))
        report = session.scalar(
            select(ContributionReport)
            .where(ContributionReport.repo_id == repo.id)
            .order_by(ContributionReport.created_at.desc())
        )
        view = _repo_view(repo, analysis)
        view["readme_cached"] = bool(analysis and analysis.readme)
        view["report_md"] = analysis.report_md if analysis else ""
        view["latest_report"] = (
            {"id": report.id, "status": report.status, "created_at": report.created_at.isoformat()}
            if report
            else None
        )
        return view


# ---------- Issue 排行榜 ----------

# 「疑似已修复」的判定正则已挪到 services/scoring.py（fixed_hint 物化列共用）


@router.get("/issue-repos")
def issue_repos():
    """Issue 榜筛选器数据源：有 issue 的项目清单（含条数），按条数降序。"""
    with SessionLocal() as session:
        rows = session.execute(
            select(Repo.full_name, func.count(Issue.id))
            .join(Issue, Issue.repo_id == Repo.id)
            .group_by(Repo.id)
            .order_by(func.count(Issue.id).desc())
        ).all()
        return {"repos": [{"full_name": name, "issue_count": count} for name, count in rows]}


@router.get("/issues")
def list_issues(
    sort: str = "match",  # match=匹配度（LLM 分优先，缺则规则分） | rule | latest
    difficulty: str = "",  # 低|中|高|空=全部
    repo: str = "",  # 过滤仓库 full_name（支持子串模糊匹配）
    min_score: float = 0,
    deep_only: bool = False,  # 只看深读过的
    limit: int = 20,
    offset: int = 0,
    analyzed: str = "all",  # all | done（LLM 精筛过，match_score 非空）| todo
):
    """跨仓库 issue 排行榜：分页 + 精筛状态过滤；「疑似已修复」按物化列 SQL 沉底。"""
    with SessionLocal() as session:
        stmt = select(Issue, Repo).join(Repo, Issue.repo_id == Repo.id)
        if difficulty:
            stmt = stmt.where(Issue.difficulty == difficulty)
        if repo:
            stmt = stmt.where(Repo.full_name.like(f"%{repo}%"))
        if deep_only:
            stmt = stmt.where(Issue.deep_read.is_(True))
        if analyzed == "done":
            stmt = stmt.where(Issue.match_score.is_not(None))
        elif analyzed == "todo":
            stmt = stmt.where(Issue.match_score.is_(None))
        # 排序键：LLM 匹配分缺失时退回规则预分；match 排序下 LLM 已评分的恒优先（两套口径不混排）；
        # 「疑似已修复」经物化列 fixed_hint 沉底（latest 是显式时间视图，保持纯时间序）
        eff_score = func.coalesce(Issue.match_score, Issue.rule_match_score)
        stmt = stmt.where(eff_score >= min_score)
        if sort == "rule":
            stmt = stmt.order_by(Issue.fixed_hint.asc(), Issue.rule_match_score.desc(), Issue.id.desc())
        elif sort == "latest":
            stmt = stmt.order_by(Issue.updated_at.desc(), Issue.id.desc())
        else:
            stmt = stmt.order_by(
                Issue.fixed_hint.asc(), Issue.match_score.is_(None).asc(), eff_score.desc(), Issue.id.desc()
            )
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = session.execute(stmt.limit(min(limit, 300)).offset(max(offset, 0))).all()
        return {
            "issues": [
                {
                    "id": issue.id,
                    "repo": r.full_name,
                    "number": issue.number,
                    "title": issue.title,
                    "url": issue.url,
                    "labels": issue.labels or [],
                    "difficulty": issue.difficulty,
                    "match_score": issue.match_score,
                    "rule_match_score": issue.rule_match_score,
                    "effective_score": round(float(issue.match_score if issue.match_score is not None
                                                     else issue.rule_match_score), 1),
                    "summary": issue.summary,
                    "action": issue.action,
                    "fixed_hint": issue.fixed_hint,
                    "body_excerpt": issue.body_excerpt,
                    "fit_reason": issue.fit_reason,
                    "screen_reason": issue.screen_reason,
                    "deep_read": issue.deep_read,
                    "learning_status": issue.learning_status,
                    "comments_count": issue.comments_count,
                    "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
                }
                for issue, r in rows
            ],
            "total": total,
        }


# ---------- 任务触发 ----------

class ContributeRequest(BaseModel):
    repo_ids: list[int]


def _submit(task_type: str, coro_fn, *args):
    """把流水线包成 TaskManager 需要的 coro_factory，并管理 GitHubClient 生命周期。"""
    payload = {"args": [str(a) for a in args]}

    async def _run(task_id: str, progress, log=None) -> dict:
        github = GitHubClient()
        try:
            return await coro_fn(github, *args, task_id, progress)
        finally:
            await github.close()

    return manager.submit(task_type, _run, payload)


@router.post("/refresh")
async def refresh():
    task_id = _submit("refresh", refresh_pipeline)
    return {"task_id": task_id}


@router.post("/contributions")
async def contribute(req: ContributeRequest):
    if not req.repo_ids:
        raise HTTPException(400, "请先勾选项目")
    if len(req.repo_ids) > MAX_CONTRIB_REPOS:
        raise HTTPException(400, f"每次最多分析 {MAX_CONTRIB_REPOS} 个项目")
    settings = get_settings()
    if not settings.llm_configured:
        raise HTTPException(400, "LLM 未配置（.env 里填 LLM_BASE_URL / LLM_API_KEY）")
    task_id = _submit("contribution", contribution_pipeline, req.repo_ids)
    return {"task_id": task_id}


@router.get("/tasks")
def tasks(limit: int = 20):
    return {"tasks": manager.list(limit)}


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    """单个任务（含 logs 时间线）。列表接口不带 logs 省流量，前端定向轮询与刷新恢复走这里。"""
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return {"task": task}


# ---------- 报告 ----------

@router.get("/reports/{report_id}")
def get_report(report_id: int):
    with SessionLocal() as session:
        report = session.get(ContributionReport, report_id)
        if report is None:
            raise HTTPException(404, "报告不存在")
        repo = session.get(Repo, report.repo_id)
        return {
            "id": report.id,
            "repo": repo.full_name if repo else "?",
            "status": report.status,
            "repo_verdict": report.repo_verdict or {},
            "issues": report.issues or [],
            "stats": report.stats or {},
            "error": report.error,
            "created_at": report.created_at.isoformat() if report.created_at else None,
            "finished_at": report.finished_at.isoformat() if report.finished_at else None,
        }


# ---------- 标签 / 定向行业分析 ----------

@router.get("/tags")
def list_tags():
    """项目标签汇总（tag → 项目数），按热度降序；行业分析与全量打标的结果都在这。"""
    with SessionLocal() as session:
        rows = session.execute(select(Repo.tags)).scalars().all()
    counter: dict[str, int] = {}
    for tags in rows:
        for t in tags or []:
            counter[t] = counter.get(t, 0) + 1
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"tags": [{"tag": t, "count": c} for t, c in ranked]}


@router.get("/industries")
def list_industries():
    """历史行业分析报告清单（不含正文全文，详情走 /industries/{id}）。"""
    with SessionLocal() as session:
        rows = session.execute(
            select(IndustryReport).order_by(IndustryReport.created_at.desc())
        ).scalars().all()
        return {
            "industries": [
                {
                    "id": r.id,
                    "name": r.name,
                    "keywords": r.keywords or [],
                    "stats": r.stats or {},
                    "model": r.model,
                    "project_count": len(r.projects or []),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        }


@router.delete("/industries/{industry_id}")
def delete_industry(industry_id: int):
    """删除一份行业报告（只删报告记录；repos.tags 是累积的知识，不动）。"""
    with SessionLocal() as session:
        row = session.get(IndustryReport, industry_id)
        if row is None:
            raise HTTPException(404, "行业报告不存在")
        session.delete(row)
        session.commit()
    return {"ok": True}


class IndustryParseRequest(BaseModel):
    text: str


@router.post("/industries/parse")
async def parse_industry_input(req: IndustryParseRequest):
    """行业分析输入解析（同步快接口，2-5 秒）：拆方向/项目 + 方向归一标签 + 项目定位候选。
    注册顺序须在 /industries/{industry_id} 之前，否则 "parse" 会被 int 路径参数吃掉。"""
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "请输入内容（方向词 + 项目名，如：agent运行时 pi agentScope-java）")
    if not get_settings().llm_configured:
        raise HTTPException(400, "LLM 未配置（.env 里填 LLM_BASE_URL / LLM_API_KEY）")
    github = GitHubClient()
    try:
        return await parse_input(github, text)
    finally:
        await github.close()


@router.get("/industries/{industry_id}")
def industry_detail(industry_id: int):
    with SessionLocal() as session:
        r = session.get(IndustryReport, industry_id)
        if r is None:
            raise HTTPException(404, "行业报告不存在")
        return {
            "id": r.id,
            "name": r.name,
            "keywords": r.keywords or [],
            "overview_md": r.overview_md,
            "projects": r.projects or [],
            "stats": r.stats or {},
            "model": r.model,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }


class IndustryRunRequest(BaseModel):
    directions: list[dict]  # [{raw: 用户原词, tag: 归一后 canonical}]
    repos: list[str] = []  # 种子项目 full_name（确认面板选定的）


@router.post("/industries")
async def create_industry(req: IndustryRunRequest):
    """定向行业分析（确认面板提交）：多方向串行跑完整流水线，种子项目无条件并入各方向候选。"""
    directions = [
        {"raw": str(d.get("raw", "")).strip(),
         "tag": str(d.get("tag", "")).strip() or str(d.get("raw", "")).strip()}
        for d in req.directions if str(d.get("raw", "")).strip()
    ]
    if not directions:
        raise HTTPException(400, "至少保留一个方向")
    if not get_settings().llm_configured:
        raise HTTPException(400, "LLM 未配置（.env 里填 LLM_BASE_URL / LLM_API_KEY）")
    seeds = [r.strip() for r in req.repos if "/" in r.strip()]
    task_id = _submit("industry", multi_industry_pipeline, directions, seeds)
    return {"task_id": task_id}


@router.post("/tags/auto")
async def auto_tag():
    """全量自动分类：LLM 先提出分类体系，再给库内全部项目打标签。"""
    if not get_settings().llm_configured:
        raise HTTPException(400, "LLM 未配置（.env 里填 LLM_BASE_URL / LLM_API_KEY）")
    task_id = _submit("tagging", tagging_pipeline)
    return {"task_id": task_id}


class AnalyzeRequest(BaseModel):
    repo_ids: list[int]


@router.post("/repos/analyze")
async def analyze_repos(req: AnalyzeRequest):
    """批量精析选中的项目（「未精析」队列的入口，跑完即入「已精析」tab）。"""
    if not req.repo_ids:
        raise HTTPException(400, "请先勾选项目")
    if len(req.repo_ids) > MAX_ANALYZE_REPOS:
        raise HTTPException(400, f"每次最多精析 {MAX_ANALYZE_REPOS} 个项目")
    if not get_settings().llm_configured:
        raise HTTPException(400, "LLM 未配置（.env 里填 LLM_BASE_URL / LLM_API_KEY）")
    task_id = _submit("analyze", analyze_pipeline, req.repo_ids)
    return {"task_id": task_id}


@router.post("/repos/translate")
async def translate_repos():
    """为 zh_desc 缺失的项目批量生成中文一句话简介（已是中文的直接回填，其余 LLM 翻译）。"""
    if not get_settings().llm_configured:
        raise HTTPException(400, "LLM 未配置（.env 里填 LLM_BASE_URL / LLM_API_KEY）")
    task_id = _submit("translate", translate_pipeline)
    return {"task_id": task_id}


# ---------- 配置状态（前端提示用） ----------

@router.get("/config")
def config_status():
    s = get_settings()
    return {
        "github_token": bool(s.github_token),
        "llm": s.llm_configured,
        "search": s.search_configured,
        "top_n_llm": s.top_n_llm,
        "sched_hour": s.sched_hour,
        "user_profile": s.user_profile,
        "user_skills": [x.strip() for x in s.user_skills.split(",") if x.strip()],
    }


# ---------- 通用技能调用 ----------

@router.get("/skills")
def skills():
    """现扫磁盘列出可用技能（项目级 + 用户级）——新增/修改 SKILL.md 即时生效。"""
    from .services.skill_runner import list_skills

    return {"skills": list_skills()}


class SkillInvokeRequest(BaseModel):
    args: str = ""


@router.post("/skills/{name}/invoke")
async def invoke_skill(name: str, req: SkillInvokeRequest):
    """以内置 Agent SDK 执行一个技能（正文注入 prompt），进度走任务轮询。

    注意必须是 async def：manager.submit 里用 asyncio.create_task，
    同步 def 会被丢进线程池导致「no running event loop」。
    """
    from .config import get_settings
    from .services.skill_runner import list_skills, run_skill

    skill = next((s for s in list_skills() if s["name"] == name), None)
    if skill is None:
        raise HTTPException(404, f"技能 {name} 不存在（检查 .claude/skills/ 或 ~/.claude/skills/）")
    if skill.get("requires") == "local":
        raise HTTPException(400, f"技能 /{name} 需要本地文件环境（requires: local），请在 Claude Code 中运行")
    timeout = get_settings().skill_run_timeout

    async def _run(task_id: str, progress, log=None) -> dict:
        result = await run_skill(name, req.args, task_id, progress, log=log, timeout=timeout)
        # TaskManager 不存返回值：结果自己挂到任务 payload 上，前端从 /api/tasks 取
        with SessionLocal() as s:
            row = s.get(TaskRun, task_id)
            row.payload = {**(row.payload or {}), "result": result}
            s.commit()
        return result

    task_id = manager.submit("skill", _run, payload={"skill": name, "args": req.args})
    return {"task_id": task_id}


class AgentRunRequest(BaseModel):
    """页面 AI 命令栏：自由指令，/开头解析为技能。"""
    prompt: str


# ---------- AI 分析沉淀入榜单 ----------

_GITHUB_URL_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?(?=$|[/\s.,)'\"）」])")
_OWNER_REPO_RE = re.compile(r"(?<![\w./-])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]{2,})(?![\w./-])")
_KNOWN_DIMS = ("enterprise_potential", "match", "learning_value",
               "star_momentum", "activity", "maintenance")


def _repo_candidates(prompt: str) -> list[str]:
    """从指令里提取候选 owner/repo：GitHub URL 优先，其次裸 owner/repo 词（交给 GitHub 校验）。"""
    seen: list[str] = []
    for m in _GITHUB_URL_RE.finditer(prompt):
        seen.append(m.group(1))
    for m in _OWNER_REPO_RE.finditer(prompt):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen[:3]


def _parse_llm_scores(result_text: str) -> dict:
    """按系统提示词约定，取报告末尾的 ```json 六维评分块。"""
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", result_text or "", re.S)
    for raw in reversed(blocks):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and any(k in data for k in _KNOWN_DIMS):
            return {k: v for k, v in data.items() if k in _KNOWN_DIMS and isinstance(v, dict)}
    return {}


async def _persist_ai_analysis(prompt: str, result_text: str, progress, log=None) -> str | None:
    """指令若指向某个 GitHub 项目，把分析沉淀进榜单（Repo + Analysis），返回 full_name。

    候选逐个到 GitHub 校验，全部落空则静默放弃——沉淀失败不能拖垮命令任务本身。
    """
    from datetime import datetime, timezone

    candidates = _repo_candidates(prompt)
    if not candidates:
        return None
    scores = _parse_llm_scores(result_text)
    gh = GitHubClient()
    try:
        meta = None
        for cand in candidates:
            try:
                raw = await gh.get_repo(cand)
            except Exception:  # noqa: BLE001  404/限流都换下一个候选
                continue
            meta = {
                "full_name": raw["full_name"],
                "description": raw.get("description") or "",
                "language": raw.get("language") or "",
                "stars": raw.get("stargazers_count") or 0,
                "topics": raw.get("topics") or [],
                "homepage": raw.get("homepage") or "",
                "license": (raw.get("license") or {}).get("spdx_id") or "",
                "open_issues": raw.get("open_issues_count") or 0,
                "pushed_at": raw.get("pushed_at"),
                "github_created_at": raw.get("created_at"),
            }
            break
        if meta is None:
            return None

        rule, rule_detail = scoring.score_repo(meta)
        total = scoring.total_score(rule_detail, scores)
        with SessionLocal() as s:
            repo = _upsert_repo(s, meta)
            s.flush()  # 新仓库要拿到自增 id 才能挂 Analysis
            repo.rule_score = rule
            repo.rule_detail = rule_detail
            repo.total_score = total
            analysis = s.scalar(select(Analysis).where(Analysis.repo_id == repo.id))
            if analysis is None:
                analysis = Analysis(repo_id=repo.id)
                s.add(analysis)
            analysis.status = "done"
            analysis.core_idea = result_text.strip()[:300]
            if scores:
                analysis.llm_scores = scores
            analysis.model = get_settings().llm_model
            analysis.note = "AI 命令分析"
            analysis.report_md = result_text.strip()
            analysis.analyzed_at = datetime.now(timezone.utc)
            s.commit()
        (log or progress)(f"已沉淀入榜单：{meta['full_name']}（综合分 {total}）")
        return meta["full_name"]
    finally:
        await gh.close()


@router.post("/agent/run")
async def agent_run(req: AgentRunRequest):
    """以内置 Agent SDK 执行一段自由指令，进度与结果走任务轮询，机制同 /skills/{name}/invoke。"""
    from .services.skill_runner import run_prompt

    if not req.prompt.strip():
        raise HTTPException(400, "prompt 不能为空")
    timeout = get_settings().skill_run_timeout

    async def _run(task_id: str, progress, log=None) -> dict:
        emit = log or progress
        result = await run_prompt(req.prompt.strip(), task_id, progress, log=log, timeout=timeout)
        # 指令若指向某个 GitHub 项目，把分析沉淀进榜单（失败不影响命令结果）
        try:
            result["repo"] = await _persist_ai_analysis(req.prompt, result.get("result") or "",
                                                        progress, log=log)
        except Exception as e:  # noqa: BLE001
            emit(f"分析结果入库失败（不影响命令结果）：{e}")
        with SessionLocal() as s:
            row = s.get(TaskRun, task_id)
            row.payload = {**(row.payload or {}), "result": result}
            s.commit()
        return result

    task_id = manager.submit("agent", _run, payload={"prompt": req.prompt.strip()})
    return {"task_id": task_id}


# ---------- 学习闭环 ----------

@router.get("/learning-context/{issue_id}")
def learning_context(issue_id: int):
    """/tech 一次取全：issue + 仓库元数据 + README + 贡献报告 + 已有课程提示。"""
    with SessionLocal() as session:
        issue = session.get(Issue, issue_id)
        if issue is None:
            raise HTTPException(404, "issue 不存在")
        repo = session.get(Repo, issue.repo_id)
        analysis = session.scalar(select(Analysis).where(Analysis.repo_id == repo.id))
        report = session.scalar(
            select(ContributionReport)
            .where(ContributionReport.repo_id == repo.id)
            .order_by(ContributionReport.created_at.desc())
        )
        report_issue = next(
            (i for i in (report.issues or []) if i.get("number") == issue.number), None
        ) if report else None
        existing = session.scalar(
            select(Course).where(Course.issue_id == issue.id)
            .order_by(Course.created_at.desc())
        )
        return {
            "issue": {
                "id": issue.id,
                "number": issue.number,
                "title": issue.title,
                "url": issue.url,
                "labels": issue.labels or [],
                "difficulty": issue.difficulty,
                "summary": issue.summary,
                "action": issue.action,
                "fit_reason": issue.fit_reason,
                "body_excerpt": issue.body_excerpt,
                "comments_count": issue.comments_count,
                "learning_status": issue.learning_status,
            },
            "repo": {
                "id": repo.id,
                "full_name": repo.full_name,
                "description": repo.description,
                "language": repo.language,
                "topics": repo.topics or [],
                "homepage": repo.homepage,
                "license": repo.license,
                "stars": repo.stars,
                "forks": repo.forks,
                "open_issues": repo.open_issues,
                "contributors_count": repo.contributors_count,
            },
            "analysis": None if analysis is None else {
                "core_idea": analysis.core_idea,
                "enterprise_cases": analysis.enterprise_cases or [],
                "llm_scores": analysis.llm_scores or {},
                "readme": analysis.readme,  # 生成「项目导览」章的底料，可能很长
            },
            "report": None if report is None else {
                "repo_verdict": report.repo_verdict or {},
                "this_issue": report_issue,  # 深读报告里对该 issue 的背景/切入方式（若有）
            },
            "existing_course": None if existing is None else {
                "id": existing.id,
                "title": existing.title,
                "status": existing.status,
                "created_at": existing.created_at.isoformat() if existing.created_at else None,
            },
        }


def _course_view(session, course: Course, full: bool = False) -> dict:
    """课程视图：lessons 摊平并附每节 quiz 提交进度。

    full=True 时附带 OSS 发布的逐文件明细（详情页用；列表里不带，避免每门课都驮一份清单）。
    """
    results = session.scalars(
        select(QuizResult).where(QuizResult.course_id == course.id)
    ).all()
    by_lesson = {r.lesson_id: r for r in results}
    lessons = []
    for l in course.lessons or []:
        r = by_lesson.get(l.get("lesson_id"))
        lessons.append({
            **l,
            "submitted": r is not None,
            "score": r.score if r else None,
            "total": r.total if r else None,
            "submitted_at": r.created_at.isoformat() if r else None,
        })
    pub = course.publish or {}
    publish = {
        k: pub[k]
        for k in ("published_at", "folder", "entry_url", "file_count", "total_bytes", "renamed")
        if k in pub
    }
    if full and "files" in pub:
        publish["files"] = pub["files"]
    return {
        "id": course.id,
        "user_id": course.user_id,
        "repo": course.repo.full_name if course.repo else "?",
        "issue_id": course.issue_id,
        "issue_number": course.issue.number if course.issue else None,
        "issue_title": course.issue.title if course.issue else "",
        "title": course.title,
        "status": course.status,
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "lessons": lessons,
        "done_lessons": sum(1 for l in lessons if l["submitted"]),
        "total_lessons": len(lessons),
        # OSS 发布状态（逐文件明细只在详情里带）
        "published": bool(pub.get("entry_url")),
        "publish": publish or None,
    }


@router.get("/courses")
def list_courses():
    with SessionLocal() as session:
        courses = session.scalars(
            select(Course).order_by(Course.created_at.desc())
        ).all()
        return {"courses": [_course_view(session, c) for c in courses]}


@router.get("/courses/{course_id}")
def get_course(course_id: int):
    with SessionLocal() as session:
        course = session.get(Course, course_id)
        if course is None:
            raise HTTPException(404, "课程不存在")
        return _course_view(session, course, full=True)


class CourseCreate(BaseModel):
    issue_id: int
    title: str
    # [{"lesson_id", "title", "file", "quiz_count"}]
    lessons: list[dict]
    replace: bool = False  # 覆盖该 issue 已有课程（连 quiz 记录一起清）


@router.post("/courses")
def create_course(req: CourseCreate):
    """注册课程元数据返回 course_id；副作用：issue → learning。课程 HTML 由 /tech 写盘。

    replace=True（覆盖重生成）：清掉该 issue 的旧课程记录（连 quiz）**和旧课程目录 courses/{旧id}/
    ——SDK 模式下 agent 没有删除权限，清理由平台做，本地与 web 两条路行为一致。
    """
    with SessionLocal() as session:
        issue = session.get(Issue, req.issue_id)
        if issue is None:
            raise HTTPException(404, "issue 不存在")
        old_ids: list[int] = []
        if req.replace:
            old_ids = session.scalars(
                select(Course.id).where(Course.issue_id == req.issue_id)
            ).all()
            if old_ids:
                session.execute(delete(QuizResult).where(QuizResult.course_id.in_(old_ids)))
                session.execute(delete(Course).where(Course.id.in_(old_ids)))
        if not req.lessons:
            raise HTTPException(400, "lessons 不能为空")
        course = Course(
            user_id=1,
            repo_id=issue.repo_id,
            issue_id=issue.id,
            title=req.title,
            lessons=req.lessons,
            status="learning",
        )
        session.add(course)
        issue.learning_status = "learning"
        session.commit()
    for old_id in old_ids:  # DB 已提交，目录清理失败只留孤儿文件、不影响新课
        shutil.rmtree(course_publish.course_dir_for(old_id), ignore_errors=True)
    return {"course_id": course.id, "status": course.status}


class CoursePublish(BaseModel):
    prune: bool = False  # 顺带删掉该课程文件夹下本次没上传的旧文件（重生成课程后用）


@router.post("/courses/{course_id}/publish")
def publish_course(course_id: int, req: CoursePublish | None = None):
    """把 courses/{id}/ 发布到卡奥斯 OSS。

    按课程分文件夹（{id}-{repo}-issue{n}-{课程标题}/），课件文件用中文课标题重命名，
    页面之间的相对链接同步改写，静态副本额外注入 CELESTIAL_PUBLISHED 标记。
    同 key 覆盖，可重复执行；失败如实报错，不写入半成品发布记录。
    """
    if not oss.is_enabled():
        raise HTTPException(
            503,
            "卡奥斯 OSS 未配置：请在 .env 填 HYIDA_OBS_ACCESS_KEY / HYIDA_OBS_SECRET_KEY 等并置 HYIDA_OBS_ENABLED=1",
        )
    prune = bool(req.prune) if req else False
    with SessionLocal() as session:
        course = session.get(Course, course_id)
        if course is None:
            raise HTTPException(404, "课程不存在")
        try:
            manifest = course_publish.publish_course(course, prune=prune)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except oss.OSSNotConfigured as exc:
            raise HTTPException(503, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 OSS 侧异常原样转达，便于排查网络/权限
            raise HTTPException(502, f"OSS 上传失败：{exc}") from exc
        manifest["published_at"] = utcnow().isoformat()
        course.publish = manifest
        session.commit()
        return manifest


class QuizResultCreate(BaseModel):
    course_id: int
    lesson_id: str
    score: int
    total: int
    detail: list[dict] = []  # 每题对错明细


@router.post("/quiz-results")
def create_quiz_result(req: QuizResultCreate):
    """回传一节 quiz（页面即时反馈，平台只存档）。全部 lesson 均有提交 → 课程与 issue 置 done。"""
    with SessionLocal() as session:
        course = session.get(Course, req.course_id)
        if course is None:
            raise HTTPException(404, "课程不存在")
        lesson_ids = {l.get("lesson_id") for l in (course.lessons or [])}
        if req.lesson_id not in lesson_ids:
            raise HTTPException(400, f"lesson_id {req.lesson_id} 不属于课程 {course.id}")
        session.add(QuizResult(
            user_id=course.user_id,
            course_id=course.id,
            lesson_id=req.lesson_id,
            score=req.score,
            total=req.total,
            detail=req.detail,
        ))
        # SessionLocal 关了 autoflush，上面的 add 还没落库，这里手动并入再对账
        submitted = set(session.scalars(
            select(QuizResult.lesson_id).where(QuizResult.course_id == course.id)
        ).all()) | {req.lesson_id}
        finished = lesson_ids and lesson_ids <= submitted and course.status != "done"
        if finished:
            course.status = "done"
            issue = session.get(Issue, course.issue_id)
            if issue:
                issue.learning_status = "done"
        session.commit()
        return {"ok": True, "course_status": course.status}

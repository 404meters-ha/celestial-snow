"""REST API：榜单、详情、刷新、贡献分析、issue 排行、任务进度、学习闭环。"""
from sqlalchemy import delete, func

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .models import Analysis, ContributionReport, Course, Issue, QuizResult, Repo, TaskRun
from .services.github_client import GitHubClient
from .services.llm import LLMNotConfigured
from .services.pipeline import MAX_CONTRIB_REPOS, contribution_pipeline, refresh_pipeline
from .tasks import manager

router = APIRouter(prefix="/api")


# ---------- 榜单 ----------

def _repo_view(repo: Repo, analysis: Analysis | None) -> dict:
    return {
        "id": repo.id,
        "full_name": repo.full_name,
        "description": repo.description,
        "language": repo.language,
        "topics": repo.topics or [],
        "homepage": repo.homepage,
        "license": repo.license,
        "stars": repo.stars,
        "open_issues": repo.open_issues,
        "contributors_count": repo.contributors_count,
        "periods": repo.periods or [],
        "rule_score": repo.rule_score,
        "rule_detail": repo.rule_detail or {},
        "total_score": repo.total_score,
        "first_seen_at": repo.first_seen_at.isoformat() if repo.first_seen_at else None,
        "analyzed": bool(analysis and analysis.status == "done"),
        "core_idea": analysis.core_idea if analysis else "",
        "enterprise_cases": analysis.enterprise_cases if analysis else [],
        "llm_scores": analysis.llm_scores if analysis else {},
    }


@router.get("/repos")
def list_repos(sort: str = "total", q: str = "", limit: int = 100):
    """榜单：total_score 降序（默认）。q 过滤 full_name/description。"""
    with SessionLocal() as session:
        stmt = select(Repo, Analysis).outerjoin(Analysis, Analysis.repo_id == Repo.id)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(Repo.full_name.like(like) | Repo.description.like(like))
        if sort == "stars":
            stmt = stmt.order_by(Repo.stars.desc())
        elif sort == "rule":
            stmt = stmt.order_by(Repo.rule_score.desc())
        else:
            stmt = stmt.order_by(Repo.total_score.desc(), Repo.rule_score.desc())
        rows = session.execute(stmt.limit(min(limit, 200))).unique().all()
        return {"repos": [_repo_view(repo, analysis) for repo, analysis in rows]}


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
        view["latest_report"] = (
            {"id": report.id, "status": report.status, "created_at": report.created_at.isoformat()}
            if report
            else None
        )
        return view


# ---------- Issue 排行榜 ----------

@router.get("/issues")
def list_issues(
    sort: str = "match",  # match=匹配度（LLM 分优先，缺则规则分） | rule | latest
    difficulty: str = "",  # 低|中|高|空=全部
    repo: str = "",  # 过滤仓库 full_name
    min_score: float = 0,
    deep_only: bool = False,  # 只看深读过的
    limit: int = 100,
):
    """跨仓库 issue 排行榜：与用户技能匹配度降序。"""
    with SessionLocal() as session:
        stmt = select(Issue, Repo).join(Repo, Issue.repo_id == Repo.id)
        if difficulty:
            stmt = stmt.where(Issue.difficulty == difficulty)
        if repo:
            stmt = stmt.where(Repo.full_name == repo)
        if deep_only:
            stmt = stmt.where(Issue.deep_read.is_(True))
        # 排序键：LLM 匹配分缺失时退回规则预分；match 排序下 LLM 已评分的恒优先（两套口径不混排）
        eff_score = func.coalesce(Issue.match_score, Issue.rule_match_score)
        if sort == "rule":
            order = Issue.rule_match_score.desc()
        elif sort == "latest":
            order = Issue.updated_at.desc()
        else:
            order = [Issue.match_score.is_(None).asc(), eff_score.desc()]
        stmt = stmt.where(eff_score >= min_score).order_by(*order).limit(min(limit, 300))
        rows = session.execute(stmt).all()
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
                    "body_excerpt": issue.body_excerpt,
                    "fit_reason": issue.fit_reason,
                    "screen_reason": issue.screen_reason,
                    "deep_read": issue.deep_read,
                    "learning_status": issue.learning_status,
                    "comments_count": issue.comments_count,
                    "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
                }
                for issue, r in rows
            ]
        }


# ---------- 任务触发 ----------

class ContributeRequest(BaseModel):
    repo_ids: list[int]


def _submit(task_type: str, coro_fn, *args):
    """把流水线包成 TaskManager 需要的 coro_factory，并管理 GitHubClient 生命周期。"""
    payload = {"args": [str(a) for a in args]}

    async def _run(task_id: str, progress) -> dict:
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
    """无头执行一个 Claude Code 技能：claude -p "/<name> <args>"，进度走任务轮询。

    注意必须是 async def：manager.submit 里用 asyncio.create_task，
    同步 def 会被丢进线程池导致「no running event loop」。
    """
    """无头执行一个 Claude Code 技能：claude -p "/<name> <args>"，进度走任务轮询。"""
    from .config import get_settings
    from .services.skill_runner import list_skills, run_skill

    if not any(s["name"] == name for s in list_skills()):
        raise HTTPException(404, f"技能 {name} 不存在（检查 .claude/skills/ 或 ~/.claude/skills/）")
    timeout = get_settings().skill_run_timeout

    async def _run(task_id: str, progress) -> dict:
        result = await run_skill(name, req.args, task_id, progress, timeout=timeout)
        # TaskManager 不存返回值：结果自己挂到任务 payload 上，前端从 /api/tasks 取
        with SessionLocal() as s:
            row = s.get(TaskRun, task_id)
            row.payload = {**(row.payload or {}), "result": result}
            s.commit()
        return result

    task_id = manager.submit("skill", _run, payload={"skill": name, "args": req.args})
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


def _course_view(session, course: Course) -> dict:
    """课程视图：lessons 摊平并附每节 quiz 提交进度。"""
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
        return _course_view(session, course)


class CourseCreate(BaseModel):
    issue_id: int
    title: str
    # [{"lesson_id", "title", "file", "quiz_count"}]
    lessons: list[dict]
    replace: bool = False  # 覆盖该 issue 已有课程（连 quiz 记录一起清）


@router.post("/courses")
def create_course(req: CourseCreate):
    """注册课程元数据返回 course_id；副作用：issue → learning。课程 HTML 由 /tech 写盘。"""
    with SessionLocal() as session:
        issue = session.get(Issue, req.issue_id)
        if issue is None:
            raise HTTPException(404, "issue 不存在")
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
        return {"course_id": course.id, "status": course.status}


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

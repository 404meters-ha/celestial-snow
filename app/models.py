"""数据模型：项目去重主表 + 每日快照 + LLM 分析 + 贡献报告 + 任务运行记录 + 学习闭环。"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Repo(Base):
    """GitHub 项目主表，按 full_name 去重，一份记录长期维护。"""

    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(64), default="")
    topics: Mapped[list] = mapped_column(JSON, default=list)
    homepage: Mapped[str] = mapped_column(String(512), default="")
    license: Mapped[str] = mapped_column(String(128), default="")

    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    open_issues: Mapped[int] = mapped_column(Integer, default=0)
    contributors_count: Mapped[int] = mapped_column(Integer, default=0)
    github_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 出现在哪些榜：["weekly"] / ["monthly"] / ["weekly", "monthly"]（双榜）
    periods: Mapped[list] = mapped_column(JSON, default=list)

    # 最近一次规则分（每次刷新重算）
    rule_score: Mapped[float] = mapped_column(Float, default=0.0)
    rule_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    total_score: Mapped[float] = mapped_column(Float, default=0.0)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    analysis: Mapped["Analysis | None"] = relationship(back_populates="repo", uselist=False)
    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="repo")
    reports: Mapped[list["ContributionReport"]] = relationship(back_populates="repo")
    issues: Mapped[list["Issue"]] = relationship(back_populates="repo")


class Snapshot(Base):
    """每日 star 快照，用于计算真实 7 天 / 30 天增量（自建周榜/月榜的核心）。"""

    __tablename__ = "snapshots"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    stars: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    repo: Mapped[Repo] = relationship(back_populates="snapshots")


class Analysis(Base):
    """LLM 精析结果，持久化；分析过不重复分析。"""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|done|failed|skipped
    core_idea: Mapped[str] = mapped_column(Text, default="")
    # [{"company": str, "scenario": str, "source": "readme"|"search", "evidence": str, "verified": bool}]
    enterprise_cases: Mapped[list] = mapped_column(JSON, default=list)
    # {"enterprise_potential": {"score": int, "reason": str}, "match": {...}, "learning_value": {...}}
    llm_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    model: Mapped[str] = mapped_column(String(128), default="")
    note: Mapped[str] = mapped_column(Text, default="")  # 降级原因等
    readme: Mapped[str] = mapped_column(Text, default="")  # 缓存，避免重复拉取
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    repo: Mapped[Repo] = relationship(back_populates="analysis")


class ContributionReport(Base):
    """贡献机会分析报告：一次分析 = 一个仓库一份报告。"""

    __tablename__ = "contribution_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")  # running|done|failed
    # 综合判断：{"verdict": str, "worth_investing": bool, "directions": [str], "health": {...}}
    repo_verdict: Mapped[dict] = mapped_column(JSON, default=dict)
    # [{"number", "title", "url", "labels", "background", "why_it_matters", "modules",
    #   "difficulty", "approach", "fit_reason"}]
    issues: Mapped[list] = mapped_column(JSON, default=list)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)  # 拉取/筛选过程统计
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    repo: Mapped[Repo] = relationship(back_populates="reports")


class Issue(Base):
    """issue 排行榜条目：跨仓库汇聚，按与用户技能的匹配度排序。

    rule_match_score 是本地规则预分（标签+技能关键词，无 LLM 也有排序）；
    match_score 是 LLM 精筛分（跑过贡献分析才有），排序时优先取后者。
    """

    __tablename__ = "issues"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512), default="")
    url: Mapped[str] = mapped_column(String(512), default="")
    labels: Mapped[list] = mapped_column(JSON, default=list)
    comments_count: Mapped[int] = mapped_column(Integer, default=0)

    rule_match_score: Mapped[float] = mapped_column(Float, default=0.0)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # LLM 打分
    difficulty: Mapped[str] = mapped_column(String(16), default="")  # 低|中|高（LLM 估）
    summary: Mapped[str] = mapped_column(Text, default="")  # 这个 issue 说了个什么事（一句话）
    action: Mapped[str] = mapped_column(Text, default="")  # 需要贡献者做什么（一句话）
    fit_reason: Mapped[str] = mapped_column(Text, default="")  # LLM：为什么适合用户
    screen_reason: Mapped[str] = mapped_column(Text, default="")  # 预筛理由
    deep_read: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否做过逐 issue 深读
    body_excerpt: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    # 学习状态机：None（未生成课程）→ learning（注册课程时）→ done（该课程全部 quiz 提交后）
    learning_status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    repo: Mapped[Repo] = relationship(back_populates="issues")


class TaskRun(Base):
    """后台任务记录（刷新 / 贡献分析），供前端轮询进度。"""

    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid
    type: Mapped[str] = mapped_column(String(32))  # refresh | contribution
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|failed
    progress: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Course(Base):
    """一门课程：/tech 针对某个 issue 一次性生成，HTML 托管于顶层 courses/{id}/。

    lessons JSON：[{"lesson_id": "01-overview", "title": "...", "file": "01-overview.html",
    "quiz_count": 4}]——quiz 进度按 lesson_id 与 quiz_results 对账。
    """

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, default=1, index=True)  # 多用户预留，当前恒为 1
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    lessons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="learning")  # learning|done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    repo: Mapped[Repo] = relationship()
    issue: Mapped[Issue] = relationship()


class QuizResult(Base):
    """一节 quiz 的回传记录：判分在页面上即时完成，平台只存档、不设及格线。"""

    __tablename__ = "quiz_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    lesson_id: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    # 每题对错明细：[{"question": str, "chosen": ..., "answer": ..., "correct": bool}]
    detail: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

"""celestial-snow 入口：FastAPI + APScheduler（每日抓取分析）+ 前端静态托管。

启动：.venv/Scripts/python.exe -m uvicorn main:app --port 8100
前端开发模式另行 vite dev（代理到本服务），生产直接读 frontend/dist。
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import get_settings
from app.db import init_db
from app.services.github_client import GitHubClient
from app.services.pipeline import refresh_pipeline

logger = logging.getLogger("celestial")


async def _scheduled_refresh() -> None:
    """每日定时抓取分析（与手动刷新同一条流水线）。"""
    logger.info("定时刷新开始")
    github = GitHubClient()
    try:
        stats = await refresh_pipeline(github, "scheduled", lambda msg: None)
        logger.info("定时刷新完成: %s", stats)
    except Exception:  # noqa: BLE001 定时任务绝不能拖垮进程
        logger.exception("定时刷新失败")
    finally:
        await github.close()


async def _warm_agent_sdk() -> None:
    """预热内置 Agent SDK：首次运行时构造 Engine 会同步导入一大串依赖（实测阻塞事件循环 2s+，
    让「点了运行没反应」——POST 的响应被压在后面出不去）。这里在后台线程先付掉这笔开销。"""
    from app.services import agent_sdk  # noqa: F401 触发核心模块导入

    def _warm() -> None:
        try:
            agent_sdk.warmup()
        except Exception:  # noqa: BLE001 预热只是提速，失败不能影响启动
            logger.warning("Agent SDK 预热失败（不影响功能，只是首次运行会慢一点）", exc_info=True)

    await asyncio.to_thread(_warm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _fail_orphan_tasks()
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler()
    scheduler.add_job(_scheduled_refresh, CronTrigger(hour=get_settings().sched_hour, minute=0))
    scheduler.start()
    logger.info("调度器已启动：每天 %02d:00 抓取分析", get_settings().sched_hour)
    await _warm_agent_sdk()
    yield
    scheduler.shutdown()


def _fail_orphan_tasks() -> None:
    """服务重启会把进程内 asyncio 任务带走；库里还挂着 running 的都是孤儿，标记失败。"""
    from datetime import datetime, timezone

    from sqlalchemy import update

    from app.db import SessionLocal
    from app.models import TaskRun

    with SessionLocal() as session:
        session.execute(
            update(TaskRun)
            .where(TaskRun.status == "running")
            .values(status="failed", error="服务重启，任务中断", finished_at=datetime.now(timezone.utc))
        )
        session.commit()


app = FastAPI(title="celestial-snow", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

# /tech 生成的课程 HTML 静态托管（目录先行创建，保证 mount 不因目录缺失报错）
COURSES_DIR = Path(__file__).parent / "courses"
COURSES_DIR.mkdir(exist_ok=True)
app.mount("/courses", StaticFiles(directory=COURSES_DIR, html=True), name="courses")

# 课程发布目录（LOCAL_PUBLISH_DIR）：/publish 落盘的静态副本由本服务直接托管在 /published，
# 服务器上 nginx 接管该目录时把 LOCAL_PUBLISH_BASE_URL 指向 nginx 的对外地址即可。
# .md 注册成 text/plain：按 text/markdown 响应时浏览器会下载而不是在标签页显示（实测）
import mimetypes

from app.services import store

mimetypes.add_type("text/plain", ".md")
app.mount("/published", StaticFiles(directory=store.root()), name="published")

DIST = Path(__file__).parent / "frontend" / "dist"


@app.get("/api/health")
async def health():
    return {"ok": True}


if DIST.exists():

    @app.get("/{path:path}")
    async def spa(path: str):
        """前端 SPA 路由兜底：有文件给文件，没有给 index.html（history 模式）。"""
        target = DIST / path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html")

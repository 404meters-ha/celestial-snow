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
    _maybe_cleanup_tags()
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


def _maybe_cleanup_tags() -> None:
    """脏标签一次性清洗：有脏特征（含 '/' 的整串标签）且从未成功清洗过（哨兵）才提交。

    成功一次永不重跑；失败不落哨兵，下次启动重试（脏特征还在才会试，不空转）。
    """
    from app.services.tags import cleanup_done, cleanup_pipeline, has_dirty_tags
    from app.tasks import manager

    try:
        if not has_dirty_tags() or cleanup_done():
            return
        logger.info("检测到历史脏标签，提交一次性清洗任务")
        manager.submit("tag_cleanup", cleanup_pipeline)
    except Exception:  # noqa: BLE001 清洗是锦上添花，绝不能影响启动
        logger.warning("脏标签清洗检测失败", exc_info=True)


class _BasePathStrip:
    """子路径部署（BASE_PATH=/celestial-snow）时剥掉请求路径里的前缀。

    纯 ASGI 层改 scope，路由/静态挂载/SPA 兜底都按剥掉后的路径工作，因此
    nginx 直接透传（proxy_pass 不带尾斜杠）即可；nginx 侧先剥掉前缀同样兼容。
    不带前缀的请求（本地 localhost:8100、Agent SDK 回环调用）原样放行。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        prefix = get_settings().base_path.rstrip("/")
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if prefix and (path == prefix or path.startswith(prefix + "/")):
            scope = dict(scope)
            scope["path"] = path[len(prefix):] or "/"
            if scope.get("raw_path"):
                scope["raw_path"] = scope["path"].encode()
        await self.app(scope, receive, send)


app = FastAPI(title="celestial-snow", lifespan=lifespan)
app.add_middleware(_BasePathStrip)
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

# 脚手架产物（scaffolds/{id}/scaffold.zip）静态托管：zip 直链下载；workspace/ 是生成过程区
SCAFFOLDS_DIR = Path(__file__).parent / "scaffolds"
(SCAFFOLDS_DIR / "workspace").mkdir(parents=True, exist_ok=True)
app.mount("/scaffolds", StaticFiles(directory=SCAFFOLDS_DIR), name="scaffolds")

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

"""进程内 asyncio 后台任务管理器：提交、进度更新、状态查询。不引入 Celery/Redis。"""
import asyncio
import uuid
from datetime import datetime, timezone

from .db import SessionLocal
from .models import TaskRun


def _sync_update(task_id: str, **fields) -> None:
    with SessionLocal() as s:
        row = s.get(TaskRun, task_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        s.commit()


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def submit(self, type_: str, coro_factory, payload: dict | None = None) -> str:
        """coro_factory: 接收 (task_id, progress_cb) 返回协程的工厂。"""
        task_id = uuid.uuid4().hex[:12]
        with SessionLocal() as s:
            s.add(TaskRun(id=task_id, type=type_, payload=payload or {}))
            s.commit()

        async def _runner() -> None:
            def progress(msg: str) -> None:
                _sync_update(task_id, progress=msg)

            try:
                await coro_factory(task_id, progress)
                _sync_update(task_id, status="success", progress="完成",
                             finished_at=datetime.now(timezone.utc))
            except asyncio.CancelledError:
                _sync_update(task_id, status="failed", error="已取消",
                             finished_at=datetime.now(timezone.utc))
                raise
            except Exception as e:  # noqa: BLE001 任务层兜底，错误落库展示
                _sync_update(task_id, status="failed", error=f"{type(e).__name__}: {e}",
                             finished_at=datetime.now(timezone.utc))

        self._tasks[task_id] = asyncio.create_task(_runner(), name=task_id)
        return task_id

    def list(self, limit: int = 20) -> list[dict]:
        with SessionLocal() as s:
            rows = s.query(TaskRun).order_by(TaskRun.created_at.desc()).limit(limit).all()
            return [
                {
                    "id": r.id, "type": r.type, "status": r.status, "progress": r.progress,
                    "error": r.error, "payload": r.payload,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                }
                for r in rows
            ]


manager = TaskManager()

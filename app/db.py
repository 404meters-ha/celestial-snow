"""SQLAlchemy 引擎与会话。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

engine = create_engine(
    get_settings().db_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """SQLite 的 create_all 不会改旧表：缺的列在这里手工 ALTER 补齐。"""
    from sqlalchemy import inspect, text

    with engine.connect() as conn:
        columns = {c["name"] for c in inspect(engine).get_columns("issues")}
        if "learning_status" not in columns:
            conn.execute(text("ALTER TABLE issues ADD COLUMN learning_status VARCHAR(16)"))
        conn.commit()

# -*- coding: utf-8 -*-
"""
数据库连接配置模块
使用SQLAlchemy进行数据库管理
"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from .config import settings

# 确保数据目录存在
os.makedirs("data", exist_ok=True)

# 同步数据库引擎
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite专用
    echo=settings.debug,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, connection_record):
    """每个连接开启 WAL + busy_timeout，减少并发写锁争用"""
    try:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
    except Exception:
        pass


# 异步数据库引擎
# 使用 NullPool：aiosqlite 连接与创建它的事件循环绑定，
# 避免 asyncio.run()/多循环场景下复用上一循环的池连接导致挂起或报错
async_database_url = settings.database_url.replace("sqlite://", "sqlite+aiosqlite://")
async_engine = create_async_engine(
    async_database_url,
    echo=settings.debug,
    poolclass=NullPool,
    connect_args={"timeout": 30},  # busy_timeout=30s，缓解并发写锁抛错
)

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 模型基类
Base = declarative_base()


async def get_async_session():
    """获取异步数据库会话"""
    async with AsyncSession(async_engine) as session:
        try:
            yield session
        finally:
            await session.close()


def get_db():
    """获取同步数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def init_db():
    """初始化数据库，创建所有表"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _migrate_columns()


def init_db_sync():
    """同步方式初始化数据库"""
    Base.metadata.create_all(bind=engine)
    _migrate_columns()


def _migrate_columns():
    """轻量级列迁移：为已存在的表补充新列（SQLite 的 create_all 不会为已存在表加列）"""
    try:
        from sqlalchemy import text
        # 补全所有历史新增列（不限于最近一次），保证老库升级后各模块可正常运行
        _ensure_column("conversation_messages", "message_type", "VARCHAR(20) DEFAULT 'text'")
        _ensure_column("conversation_messages", "tool_calls", "TEXT")
        _ensure_column("conversation_messages", "trace_id", "VARCHAR(64)")
        _ensure_column("conversation_messages", "prompt_tokens", "INTEGER DEFAULT 0")
        _ensure_column("conversation_messages", "completion_tokens", "INTEGER DEFAULT 0")
        _ensure_column("audit_logs", "session_id", "VARCHAR(64)")
        _ensure_column("audit_logs", "created_at", "DATETIME")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"数据库列迁移失败: {e}")


def _ensure_column(table: str, column: str, ddl: str):
    """若表中缺少指定列，则执行 ALTER TABLE ADD COLUMN（幂等）"""
    from sqlalchemy import text, inspect

    try:
        cols = {col["name"] for col in inspect(engine).get_columns(table)}
    except Exception:
        # 表不存在则跳过
        return
    if column not in cols:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))

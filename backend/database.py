# -*- coding: utf-8 -*-
"""
数据库连接配置模块
使用SQLAlchemy进行数据库管理
"""

import os
from sqlalchemy import create_engine
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

# 异步数据库引擎
async_database_url = settings.database_url.replace("sqlite://", "sqlite+aiosqlite://")
async_engine = create_async_engine(
    async_database_url,
    echo=settings.debug,
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


def init_db_sync():
    """同步方式初始化数据库"""
    Base.metadata.create_all(bind=engine)

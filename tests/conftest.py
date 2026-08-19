# -*- coding: utf-8 -*-
"""测试配置：使用临时文件数据库"""
import os
import sys
import tempfile
from pathlib import Path

# 在导入任何项目模块前设置测试环境变量
# 使用临时文件，避免 :memory: 的每个连接独立数据库问题
# 强制覆盖（不用 setdefault）：防止开发者本机已有的 DATABASE_URL/LLM_API_KEY
# 让测试打到真实库/真实密钥
TEST_DB_FD, TEST_DB_PATH = tempfile.mkstemp(suffix=".test.db")
os.close(TEST_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["LLM_API_KEY"] = "test-key"
os.environ["ENABLE_SECURITY_GUARDRAIL"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key"

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """初始化测试数据库表"""
    from backend.database import init_db_sync
    init_db_sync()
    yield
    # 清理临时测试数据库：先释放引擎句柄（Windows 下 SQLite 文件被占用无法删除）
    try:
        from backend.database import engine, async_engine
        engine.dispose()
        try:
            import asyncio
            asyncio.run(async_engine.dispose())
        except Exception:
            pass
    except Exception:
        pass
    try:
        os.remove(TEST_DB_PATH)
        for suffix in ("-journal", "-wal", "-shm"):
            try:
                os.remove(TEST_DB_PATH + suffix)
            except OSError:
                pass
    except OSError:
        pass


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)

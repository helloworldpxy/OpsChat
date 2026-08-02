# -*- coding: utf-8 -*-
"""测试配置：使用临时文件数据库"""
import os
import sys
import tempfile
from pathlib import Path

# 在导入任何项目模块前设置测试环境变量
# 使用临时文件，避免 :memory: 的每个连接独立数据库问题
TEST_DB_FD, TEST_DB_PATH = tempfile.mkstemp(suffix=".test.db")
os.close(TEST_DB_FD)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("ENABLE_SECURITY_GUARDRAIL", "false")

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """应用生命周期会自动初始化数据库表"""
    yield
    # 清理临时测试数据库
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)

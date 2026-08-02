# -*- coding: utf-8 -*-
"""
API接口测试
测试FastAPI路由
"""

import pytest
from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


class TestHealthAPI:
    """健康检查API测试"""
    
    def test_health_check(self, client):
        """测试健康检查接口"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestToolsAPI:
    """工具API测试"""
    
    def test_get_tools(self, client):
        """测试获取工具列表"""
        response = client.get("/api/tools/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "data" in data
        assert len(data["data"]) > 0
    
    def test_get_llm_tools(self, client):
        """测试获取LLM工具列表"""
        response = client.get("/api/tools/llm")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "data" in data
    
    def test_get_tool_detail(self, client):
        """测试获取工具详情"""
        response = client.get("/api/tools/get_system_info")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["data"]["name"] == "get_system_info"
    
    def test_get_nonexistent_tool(self, client):
        """测试获取不存在的工具"""
        response = client.get("/api/tools/nonexistent")
        assert response.status_code == 404


class TestSettingsAPI:
    """设置API测试"""
    
    def test_get_settings(self, client):
        """测试获取设置"""
        response = client.get("/api/settings/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "api" in data["data"]
        assert "security" in data["data"]
    
    def test_get_models(self, client):
        """测试获取模型列表"""
        response = client.get("/api/models/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "data" in data


class TestAuditAPI:
    """审计API测试"""
    
    def test_get_audit_logs(self, client):
        """测试获取审计日志"""
        response = client.get("/api/audit/logs")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "data" in data
    
    def test_get_traces(self, client):
        """测试获取追踪列表"""
        response = client.get("/api/audit/traces")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True


class TestStatusAPI:
    """状态API测试"""
    
    def test_get_status(self, client):
        """测试获取系统状态"""
        response = client.get("/api/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "cpu_percent" in data["data"]
        assert "memory_percent" in data["data"]
        assert "disk_percent" in data["data"]

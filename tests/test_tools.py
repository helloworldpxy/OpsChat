# -*- coding: utf-8 -*-
"""
工具模块测试
测试MCP工具的注册和执行
"""

import pytest
from backend.mcp.protocol import MCPProtocol, MCPRequest, RiskLevel
from backend.mcp.registry import ToolRegistry


class TestMCPProtocol:
    """MCP协议测试"""
    
    def setup_method(self):
        """测试前准备"""
        self.protocol = MCPProtocol()
    
    def test_tool_registration(self):
        """测试工具注册"""
        from backend.mcp.protocol import ToolDefinition, ToolExecutor
        
        # 创建测试工具
        class TestExecutor(ToolExecutor):
            async def execute(self, **kwargs):
                return {"success": True, "data": "test"}
        
        definition = ToolDefinition(
            name="test_tool",
            description="测试工具",
            category="test",
            parameters={"type": "object", "properties": {}},
            risk_level=RiskLevel.LOW,
        )
        
        self.protocol.register_tool(definition, TestExecutor(definition))
        
        # 验证注册
        assert "test_tool" in self.protocol.tools
        assert len(self.protocol.get_all_tools()) == 1
    
    def test_get_llm_tools(self):
        """测试获取LLM工具列表"""
        from backend.mcp.protocol import ToolDefinition, ToolExecutor
        
        class TestExecutor(ToolExecutor):
            async def execute(self, **kwargs):
                return {"success": True}
        
        # 注册低风险工具
        low_risk = ToolDefinition(
            name="low_risk_tool",
            description="低风险工具",
            category="test",
            risk_level=RiskLevel.LOW,
        )
        self.protocol.register_tool(low_risk, TestExecutor(low_risk))
        
        # 注册高风险工具
        high_risk = ToolDefinition(
            name="high_risk_tool",
            description="高风险工具",
            category="test",
            risk_level=RiskLevel.HIGH,
        )
        self.protocol.register_tool(high_risk, TestExecutor(high_risk))
        
        # 验证LLM工具列表不包含高风险工具
        llm_tools = self.protocol.get_llm_tools()
        assert len(llm_tools) == 1
        assert llm_tools[0]["function"]["name"] == "low_risk_tool"


class TestToolRegistry:
    """工具注册中心测试"""
    
    def setup_method(self):
        """测试前准备"""
        self.registry = ToolRegistry()
    
    def test_initialization(self):
        """测试初始化"""
        self.registry.initialize()
        
        tools = self.registry.get_all_tools()
        assert len(tools) > 0
        
        # 验证包含预期的工具
        tool_names = [t.name for t in tools]
        assert "get_system_info" in tool_names
        assert "get_disk_usage" in tool_names
        assert "get_memory_usage" in tool_names
        assert "get_cpu_usage" in tool_names
        assert "get_process_list" in tool_names
        assert "kill_process" in tool_names
        assert "list_services" in tool_names
        assert "restart_service" in tool_names
    
    def test_risk_levels(self):
        """测试风险等级"""
        self.registry.initialize()
        
        protocol = self.registry.get_protocol()
        
        # 验证低风险工具
        low_risk_tools = protocol.get_tools_by_risk_level(RiskLevel.LOW)
        assert len(low_risk_tools) > 0
        
        # 验证高风险工具
        high_risk_tools = protocol.get_tools_by_risk_level(RiskLevel.HIGH)
        assert len(high_risk_tools) > 0
        
        # 验证kill_process是高风险
        kill_tool = protocol.get_tool("kill_process")
        assert kill_tool.risk_level == RiskLevel.HIGH
        assert kill_tool.requires_approval is True
    
    def test_llm_tools_excludes_high_risk(self):
        """测试LLM工具列表排除高风险工具"""
        self.registry.initialize()
        
        llm_tools = self.registry.get_llm_tools()
        tool_names = [t["function"]["name"] for t in llm_tools]
        
        # 高风险工具不应在LLM工具列表中
        assert "kill_process" not in tool_names

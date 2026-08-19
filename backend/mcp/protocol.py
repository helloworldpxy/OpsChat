# -*- coding: utf-8 -*-
"""
MCP协议核心实现
Model Context Protocol - 工具调用协议
"""

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional, Callable, Awaitable
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class RiskLevel(str, Enum):
    """风险等级枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolParameter(BaseModel):
    """工具参数定义"""
    name: str
    type: str
    description: str
    required: bool = False
    default: Optional[Any] = None
    enum: Optional[List[str]] = None


class ToolDefinition(BaseModel):
    """工具定义"""
    name: str
    description: str
    category: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    enabled: bool = True


class MCPRequest(BaseModel):
    """MCP请求"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)
    session_id: Optional[str] = None
    trace_id: Optional[str] = None


class MCPResponse(BaseModel):
    """MCP响应"""
    id: str
    request_id: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }


class ToolExecutor:
    """工具执行器基类"""
    
    def __init__(self, definition: ToolDefinition):
        self.definition = definition
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """执行工具，子类需要重写此方法"""
        raise NotImplementedError("子类必须实现execute方法")


class MCPProtocol:
    """MCP协议管理器"""
    
    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self.executors: Dict[str, ToolExecutor] = {}
    
    def register_tool(self, definition: ToolDefinition, executor: ToolExecutor):
        """注册工具"""
        self.tools[definition.name] = definition
        self.executors[definition.name] = executor
    
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        return self.tools.get(name)
    
    def get_all_tools(self) -> List[ToolDefinition]:
        """获取所有工具"""
        return list(self.tools.values())
    
    def get_tools_by_risk_level(self, level: RiskLevel) -> List[ToolDefinition]:
        """按风险等级获取工具"""
        return [t for t in self.tools.values() if t.risk_level == level]
    
    def get_llm_tools(self) -> List[Dict[str, Any]]:
        """获取LLM可调用的工具列表
        高危工具不再过滤，交由权限审批引擎（PermissionService）在调用时拦截
        """
        tools = []
        for tool in self.tools.values():
            if tool.enabled:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    }
                })
        return tools
    
    async def execute_tool(self, request: MCPRequest) -> MCPResponse:
        """执行工具"""
        start_time = datetime.now()
        
        # 检查工具是否存在
        if request.tool_name not in self.tools:
            return MCPResponse(
                id=str(uuid.uuid4()),
                request_id=request.id,
                success=False,
                error=f"工具不存在: {request.tool_name}"
            )
        
        tool = self.tools[request.tool_name]
        
        # 检查工具是否启用
        if not tool.enabled:
            return MCPResponse(
                id=str(uuid.uuid4()),
                request_id=request.id,
                success=False,
                error=f"工具已禁用: {request.tool_name}"
            )
        
        # 执行工具（放到线程池，避免同步 subprocess 阻塞事件循环）
        try:
            executor = self.executors[request.tool_name]
            result = await asyncio.to_thread(self._run_executor_sync, executor, request.parameters)

            duration = int((datetime.now() - start_time).total_seconds() * 1000)

            return MCPResponse(
                id=str(uuid.uuid4()),
                request_id=request.id,
                success=True,
                result=result,
                duration_ms=duration
            )
        except Exception as e:
            duration = int((datetime.now() - start_time).total_seconds() * 1000)

            return MCPResponse(
                id=str(uuid.uuid4()),
                request_id=request.id,
                success=False,
                error=str(e),
                duration_ms=duration
            )

    @staticmethod
    def _run_executor_sync(executor: ToolExecutor, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """在独立事件循环中运行 async executor 的同步实现（线程池内执行，避免阻塞主事件循环）
        executor 的 async execute 内部为同步 subprocess/IO 代码，无真实 await，可在工作线程的
        独立事件循环中安全运行。
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(executor.execute(**parameters))
        finally:
            loop.close()


# 全局MCP协议实例
mcp_protocol = MCPProtocol()

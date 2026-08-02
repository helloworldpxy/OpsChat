# -*- coding: utf-8 -*-
"""
工具定义数据模型
MCP工具的数据库定义和执行日志
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, JSON
from sqlalchemy.sql import func

from ..database import Base


class ToolDefinition(Base):
    """工具定义模型"""
    __tablename__ = "tool_definitions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False, comment="工具名称")
    description = Column(Text, nullable=False, comment="工具描述")
    category = Column(String(50), nullable=False, comment="工具类别: system/network/process/service")
    risk_level = Column(String(20), default="low", comment="风险等级: low/medium/high")
    requires_approval = Column(Boolean, default=False, comment="是否需要审批")
    parameters = Column(JSON, nullable=True, comment="参数定义JSON Schema")
    is_enabled = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<ToolDefinition(name={self.name}, risk_level={self.risk_level})>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "parameters": self.parameters,
            "is_enabled": self.is_enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_llm_tool_format(self):
        """转换为LLM可调用的工具格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            }
        }


class ToolExecutionLog(Base):
    """工具执行日志模型"""
    __tablename__ = "tool_execution_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tool_name = Column(String(100), nullable=False, index=True, comment="工具名称")
    trace_id = Column(String(36), nullable=True, index=True, comment="追踪ID")
    session_id = Column(String(36), nullable=True, comment="会话ID")

    # 执行信息
    parameters = Column(JSON, nullable=True, comment="执行参数")
    result = Column(Text, nullable=True, comment="执行结果")
    success = Column(Boolean, default=True, comment="是否成功")
    error_message = Column(Text, nullable=True, comment="错误信息")
    duration_ms = Column(Integer, nullable=True, comment="执行耗时(毫秒)")

    # 安全信息
    risk_level = Column(String(20), nullable=True, comment="风险等级")
    approved = Column(Boolean, nullable=True, comment="是否已批准")
    approved_by = Column(String(100), nullable=True, comment="批准人")

    # 时间信息
    executed_at = Column(DateTime, default=func.now(), comment="执行时间")

    def __repr__(self):
        return f"<ToolExecutionLog(tool={self.tool_name}, success={self.success})>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "parameters": self.parameters,
            "result": self.result,
            "success": self.success,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "risk_level": self.risk_level,
            "approved": self.approved,
            "approved_by": self.approved_by,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }

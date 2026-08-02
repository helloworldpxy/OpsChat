# -*- coding: utf-8 -*-
"""
自定义工具数据模型
用户可通过UI创建自定义MCP工具
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, JSON
from sqlalchemy.sql import func

from ..database import Base


class CustomTool(Base):
    """用户自定义工具模型"""
    __tablename__ = "custom_tools"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False, comment="工具名称（英文，唯一）")
    description = Column(Text, nullable=False, comment="工具描述")
    category = Column(String(50), default="custom", comment="工具类别")
    risk_level = Column(String(20), default="low", comment="风险等级: low/medium/high")
    requires_approval = Column(Boolean, default=False, comment="是否需要审批")

    # 工具定义
    parameters = Column(JSON, nullable=True, comment="参数定义JSON Schema")
    command_template = Column(Text, nullable=False, comment="命令模板，支持 {param} 占位符")
    command_type = Column(String(20), default="shell", comment="命令类型: shell/python")

    # 元数据
    is_builtin = Column(Boolean, default=False, comment="是否为内置工具（不可删除）")
    is_enabled = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<CustomTool(name={self.name}, category={self.category})>"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "parameters": self.parameters,
            "command_template": self.command_template,
            "command_type": self.command_type,
            "is_builtin": self.is_builtin,
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

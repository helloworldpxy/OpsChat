# -*- coding: utf-8 -*-
"""
审计日志数据模型
记录完整的思维链和操作日志
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, JSON
from sqlalchemy.sql import func

from ..database import Base


class AuditLog(Base):
    """审计日志模型"""
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trace_id = Column(String(36), nullable=False, index=True, comment="追踪ID")
    timestamp = Column(DateTime, default=func.now(), nullable=False, comment="时间戳")

    # 阶段信息
    stage = Column(String(50), nullable=False, comment="阶段名称")
    stage_order = Column(Integer, default=0, comment="阶段顺序")

    # 内容
    content = Column(Text, nullable=True, comment="内容")
    details = Column(JSON, nullable=True, comment="详细信息JSON")

    # 安全相关信息
    risk_level = Column(String(20), nullable=True, comment="风险等级")
    security_decision = Column(String(50), nullable=True, comment="安全决策")
    rules_triggered = Column(JSON, nullable=True, comment="触发的规则")

    # 工具调用信息
    tool_name = Column(String(100), nullable=True, comment="工具名称")
    tool_params = Column(JSON, nullable=True, comment="工具参数")
    tool_result = Column(Text, nullable=True, comment="工具执行结果")

    # 用户信息
    user_confirmed = Column(Boolean, nullable=True, comment="用户是否确认")

    # 元数据
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    session_id = Column(String(36), nullable=True, index=True, comment="会话ID")

    def __repr__(self):
        return f"<AuditLog(id={self.id}, stage={self.stage}, trace_id={self.trace_id})>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "stage": self.stage,
            "stage_order": self.stage_order,
            "content": self.content,
            "details": self.details,
            "risk_level": self.risk_level,
            "security_decision": self.security_decision,
            "rules_triggered": self.rules_triggered,
            "tool_name": self.tool_name,
            "tool_params": self.tool_params,
            "tool_result": self.tool_result,
            "user_confirmed": self.user_confirmed,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Conversation(Base):
    """对话会话模型"""
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(200), default="新对话", comment="对话标题")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    is_active = Column(Boolean, default=True, comment="是否活跃")

    def __repr__(self):
        return f"<Conversation(id={self.id}, title={self.title})>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": self.is_active,
        }


class ConversationMessage(Base):
    """对话消息模型"""
    __tablename__ = "conversation_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), nullable=False, index=True, comment="对话ID")
    role = Column(String(20), nullable=False, comment="角色: user/assistant/system")
    content = Column(Text, nullable=False, comment="消息内容")
    message_type = Column(String(20), default="text", comment="消息类型: text/tool_call/tool_result")
    tool_calls = Column(JSON, nullable=True, comment="工具调用信息")
    trace_id = Column(String(36), nullable=True, comment="关联的追踪ID")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    def __repr__(self):
        return f"<ConversationMessage(id={self.id}, role={self.role})>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "message_type": self.message_type,
            "tool_calls": self.tool_calls,
            "trace_id": self.trace_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

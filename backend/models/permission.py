# -*- coding: utf-8 -*-
"""
权限数据模型
定义权限规则与审批请求的数据库表
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, JSON
from sqlalchemy.sql import func

from ..database import Base


class PermissionRule(Base):
    """权限规则模型
    存储用户"始终允许/拒绝"等持久化规则，重启后依然生效
    """
    __tablename__ = "permission_rules"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    permission = Column(String(100), nullable=False, index=True, comment="权限名称，如 tool:kill_process")
    pattern = Column(String(255), nullable=False, comment="匹配模式，支持 * 通配符")
    action = Column(String(20), nullable=False, comment="动作: allow/deny/ask")
    session_id = Column(String(36), nullable=True, index=True, comment="关联会话ID，为空表示全局规则")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    def __repr__(self):
        return f"<PermissionRule(permission={self.permission}, pattern={self.pattern}, action={self.action})>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "permission": self.permission,
            "pattern": self.pattern,
            "action": self.action,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PermissionRequest(Base):
    """权限审批请求模型
    记录一次待用户确认的高危操作请求
    """
    __tablename__ = "permission_requests"

    id = Column(String(36), primary_key=True, comment="请求ID")
    session_id = Column(String(36), nullable=True, index=True, comment="会话ID")
    permission = Column(String(100), nullable=True, comment="权限名称")
    patterns = Column(JSON, nullable=True, comment="待审批的模式列表")
    metadata_json = Column("metadata", JSON, nullable=True, comment="审批卡展示用元数据")
    always = Column(JSON, nullable=True, comment="选择 always 时写入的规则模式列表")
    tool_name = Column(String(100), nullable=True, comment="关联工具名称")
    tool_params = Column(JSON, nullable=True, comment="工具参数")
    tool_call_id = Column(String(100), nullable=True, comment="工具调用ID")
    trace_id = Column(String(36), nullable=True, comment="关联追踪ID")
    status = Column(String(20), default="pending", comment="状态: pending/approved/rejected/expired")
    password_required = Column(Boolean, default=True, comment="是否需要 sudo 密码验证")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    expires_at = Column(DateTime, nullable=True, comment="过期时间")

    def __repr__(self):
        return f"<PermissionRequest(id={self.id}, tool={self.tool_name}, status={self.status})>"
# -*- coding: utf-8 -*-
"""
大模型配置档案数据模型
支持在设置界面添加多个大模型（提供商+模型），持久化到数据库
"""

import re
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, JSON
from sqlalchemy.sql import func

from ..database import Base

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_valid_profile_id(profile_id: str) -> bool:
    """校验提供商/路由 ID：仅允许字母、数字、下划线、连字符"""
    return bool(_ID_RE.match(profile_id or ""))


class ModelProfile(Base):
    """大模型配置档案（一个档案 = 一个提供商 + 其下多个模型）"""
    __tablename__ = "model_profiles"

    id = Column(String(64), primary_key=True, comment="提供商/路由 ID（唯一，如 deepseek 或自定义网关）")
    name = Column(String(100), nullable=False, comment="显示名称")
    base_url = Column(String(500), nullable=False, comment="API Base URL")
    api_key = Column(Text, default="", comment="API 密钥（加密存储；读接口永不返回明文）")
    models = Column(JSON, default=list, comment="模型 ID 列表")
    active_model = Column(String(100), default="", comment="当前使用的模型 ID")
    is_active = Column(Boolean, default=False, comment="是否当前启用的档案（同一时间仅一个）")

    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    def _encrypt_key(self, value: str) -> str:
        """写入前加密（空值不变）"""
        if not value:
            return ""
        from ..security.secrets import encrypt_secret
        return encrypt_secret(value)

    def _decrypt_key(self, value: str) -> str:
        """读取后解密（兼容历史明文）"""
        if not value:
            return ""
        from ..security.secrets import decrypt_secret
        return decrypt_secret(value)

    def get_api_key(self) -> str:
        """解密后的真实密钥（仅内部/运行时使用，勿下发前端）"""
        return self._decrypt_key(self.api_key)

    def __repr__(self):
        return f"<ModelProfile(id={self.id}, name={self.name}, is_active={self.is_active})>"

    def to_dict(self, include_key: bool = False) -> dict:
        """转为字典（默认不暴露 API 密钥明文）"""
        data = {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "api_key_set": bool(self.api_key),
            "models": self.models or [],
            "active_model": self.active_model or (self.models[0] if self.models else ""),
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_key:
            # 需要明文时返回解密值（仅内部可信路径使用）
            data["api_key"] = self.get_api_key()
        return data
# -*- coding: utf-8 -*-
"""
大模型配置档案服务
- 启动时从环境变量种子化默认档案（兼容既有部署）
- 将激活的档案应用到运行时 LLM 配置
"""

import logging
from typing import Optional

from ..config import settings
from ..models.model_profile import ModelProfile

logger = logging.getLogger(__name__)


def _infer_provider(base_url: str) -> str:
    """从 base_url 推断提供商 key（与 api/settings._get_current_provider 同口径）"""
    url = (base_url or "").lower()
    if "deepseek" in url:
        return "deepseek"
    if "xiaomimimo" in url:
        return "mimo"
    if "dashscope" in url or "aliyuncs" in url:
        return "qwen"
    if "bigmodel" in url:
        return "chatglm"
    if "moonshot" in url:
        return "kimi"
    if "baidubce" in url:
        return "wenxin"
    return "custom"


def _provider_name(provider: str) -> str:
    info = settings.model_providers.get(provider)
    return info.get("name") if info else (provider if provider != "custom" else "自定义API")


def _db() -> "Session":
    from ..database import SessionLocal
    return SessionLocal()


def seed_default_profile_if_empty() -> None:
    """数据库无任何档案时，用当前环境变量配置种子化一个默认档案"""
    db = _db()
    try:
        count = db.query(ModelProfile).count()
        if count > 0:
            return

        provider = _infer_provider(settings.llm_base_url)
        catalog = settings.model_providers.get(provider, {})
        models = list(catalog.get("models") or [])
        if settings.llm_model and settings.llm_model not in models:
            models.append(settings.llm_model)
        if not models:
            models = ["deepseek-chat"]

        from ..security.secrets import encrypt_secret
        profile = ModelProfile(
            id=provider,
            name=_provider_name(provider),
            base_url=settings.llm_base_url or catalog.get("base_url", ""),
            api_key=encrypt_secret(settings.llm_api_key),
            models=models,
            active_model=settings.llm_model or (models[0] if models else ""),
            is_active=True,
        )
        db.add(profile)
        db.commit()
        logger.info(f"已种子化默认模型档案: {profile.id}")
    finally:
        db.close()


def get_active_profile(db=None) -> Optional[ModelProfile]:
    """获取当前激活的模型档案"""
    owns_db = db is None
    if owns_db:
        db = _db()
    try:
        return db.query(ModelProfile).filter(ModelProfile.is_active.is_(True)).first()
    finally:
        if owns_db:
            db.close()


def apply_active_model_profile(db=None) -> Optional[ModelProfile]:
    """
    将激活档案应用到运行时 LLM 配置（settings + agent.llm_client）
    无激活档案时返回 None，保持 .env 默认配置
    """
    profile = get_active_profile(db)
    if profile is None or not profile.base_url or not profile.active_model:
        return None

    settings.llm_base_url = profile.base_url
    settings.llm_model = profile.active_model
    api_key = profile.get_api_key()
    if api_key:
        settings.llm_api_key = api_key

    from ..core.agent import agent
    agent.update_llm_config(
        api_key=api_key or settings.llm_api_key,
        base_url=profile.base_url,
        model=profile.active_model,
    )
    logger.info(f"已应用激活模型档案: {profile.id} - {profile.active_model}")
    return profile
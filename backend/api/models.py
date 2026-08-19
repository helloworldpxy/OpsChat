# -*- coding: utf-8 -*-
"""
模型列表API接口
获取可用的模型列表
"""

import logging
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException

from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def get_models():
    """
    获取所有可用模型列表
    
    Returns:
        模型列表
    """
    try:
        models = {}
        
        for provider_key, provider_info in settings.model_providers.items():
            models[provider_key] = {
                "name": provider_info["name"],
                "base_url": provider_info["base_url"],
                "models": provider_info["models"],
            }
        
        return {
            "success": True,
            "data": models,
        }
        
    except Exception as e:
        logger.error(f"获取模型列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{provider}")
async def get_provider_models(provider: str):
    """
    获取指定提供商的模型列表
    
    Args:
        provider: 提供商名称
        
    Returns:
        模型列表
    """
    try:
        provider_info = settings.model_providers.get(provider)
        
        if not provider_info:
            raise HTTPException(status_code=404, detail=f"提供商不存在: {provider}")
        
        return {
            "success": True,
            "data": {
                "name": provider_info["name"],
                "base_url": provider_info["base_url"],
                "models": provider_info["models"],
            },
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取提供商模型列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

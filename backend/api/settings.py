# -*- coding: utf-8 -*-
"""
设置API接口
管理系统配置和API设置
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..core.agent import agent
from ..core.llm_client import LLMClient

logger = logging.getLogger(__name__)

router = APIRouter()


class APIConfigRequest(BaseModel):
    """API配置请求"""
    provider: str
    api_key: Optional[str] = None
    base_url: str
    model: str


class SystemConfigRequest(BaseModel):
    """系统配置请求"""
    enable_security_guardrail: Optional[bool] = None
    enable_input_sanitizer: Optional[bool] = None
    enable_output_validator: Optional[bool] = None
    enable_sandbox: Optional[bool] = None
    log_level: Optional[str] = None


@router.get("/")
async def get_settings():
    """
    获取当前设置
    
    Returns:
        当前设置
    """
    try:
        return {
            "success": True,
            "data": {
                "api": {
                    "provider": _get_current_provider(),
                    "base_url": settings.llm_base_url,
                    "model": settings.llm_model,
                    "api_key_set": bool(settings.llm_api_key),
                },
                "security": {
                    "enable_security_guardrail": settings.enable_security_guardrail,
                    "enable_input_sanitizer": settings.enable_input_sanitizer,
                    "enable_output_validator": settings.enable_output_validator,
                    "enable_sandbox": settings.enable_sandbox,
                },
                "system": {
                    "log_level": settings.log_level,
                    "max_conversation_history": settings.max_conversation_history,
                    "session_timeout": settings.session_timeout,
                },
                "providers": settings.model_providers,
            },
        }
        
    except Exception as e:
        logger.error(f"获取设置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def _get_current_provider() -> str:
    """获取当前使用的模型提供商"""
    base_url = settings.llm_base_url.lower()
    
    if "deepseek" in base_url:
        return "deepseek"
    elif "xiaomimimo" in base_url:
        return "mimo"
    elif "dashscope" in base_url or "aliyuncs" in base_url:
        return "qwen"
    elif "bigmodel" in base_url:
        return "chatglm"
    elif "baidubce" in base_url:
        return "wenxin"
    else:
        return "custom"


@router.post("/api")
async def save_api_config(request: APIConfigRequest):
    """
    保存API配置
    
    Args:
        request: API配置请求
        
    Returns:
        操作结果
    """
    try:
        # 更新LLM配置
        agent.update_llm_config(
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
        )
        
        # 更新环境变量（注意：这只是运行时更新，不会持久化到.env文件）
        if request.api_key:
            settings.llm_api_key = request.api_key
        settings.llm_base_url = request.base_url
        settings.llm_model = request.model
        
        logger.info(f"API配置已更新: {request.provider} - {request.model}")
        
        return {
            "success": True,
            "message": "API配置已保存",
        }
        
    except Exception as e:
        logger.error(f"保存API配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save-to-env")
async def save_to_env(request: APIConfigRequest):
    """
    将API配置持久化到.env文件
    """
    try:
        import os
        env_path = ".env"
        
        # 读取现有.env内容
        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        # 更新或添加配置项
        config_map = {
            "LLM_API_KEY": request.api_key,
            "LLM_BASE_URL": request.base_url,
            "LLM_MODEL": request.model,
        }
        
        updated_keys = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key in config_map and config_map[key]:
                    new_lines.append(f"{key}={config_map[key]}\n")
                    updated_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        # 添加未更新的配置项
        for key, value in config_map.items():
            if key not in updated_keys and value:
                new_lines.append(f"{key}={value}\n")
        
        # 写入.env文件
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        
        # 同时更新运行时配置
        await save_api_config(request)
        
        return {
            "success": True,
            "message": "配置已保存到.env文件",
        }
        
    except Exception as e:
        logger.error(f"保存到.env失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/system")
async def save_system_config(request: SystemConfigRequest):
    """
    保存系统配置
    
    Args:
        request: 系统配置请求
        
    Returns:
        操作结果
    """
    try:
        # 更新安全配置
        if request.enable_security_guardrail is not None:
            settings.enable_security_guardrail = request.enable_security_guardrail
        if request.enable_input_sanitizer is not None:
            settings.enable_input_sanitizer = request.enable_input_sanitizer
        if request.enable_output_validator is not None:
            settings.enable_output_validator = request.enable_output_validator
        if request.enable_sandbox is not None:
            settings.enable_sandbox = request.enable_sandbox
        if request.log_level is not None:
            settings.log_level = request.log_level
        
        logger.info("系统配置已更新")
        
        return {
            "success": True,
            "message": "系统配置已保存",
        }
        
    except Exception as e:
        logger.error(f"保存系统配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-connection")
async def test_connection(request: Optional[APIConfigRequest] = None):
    """
    测试API连接
    支持传入临时配置测试，不传则使用当前配置
    """
    try:
        # 如果传入了配置（即使api_key为空也用传入的base_url和model）
        if request and request.base_url and request.model:
            api_key = request.api_key or settings.llm_api_key
            if not api_key or api_key == "your_api_key_here":
                return {
                    "success": False,
                    "message": "请先输入API Key",
                }
            temp_client = LLMClient(
                api_key=api_key,
                base_url=request.base_url,
                model=request.model,
            )
            result = await temp_client.test_connection()
        else:
            result = await agent.test_llm_connection()
        return result
        
    except Exception as e:
        logger.error(f"测试连接失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# -*- coding: utf-8 -*-
"""
设置API接口
管理系统配置和API设置
"""

import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..core.agent import agent
from ..core.llm_client import LLMClient
from ..core.model_profiles import apply_active_model_profile, seed_default_profile_if_empty
from ..models.model_profile import ModelProfile, is_valid_profile_id

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


class ModelProfileCreate(BaseModel):
    """新增模型档案请求"""
    id: Optional[str] = None  # 自定义提供商时必填
    name: str
    base_url: str
    api_key: Optional[str] = None
    models: List[str] = []
    active_model: Optional[str] = None
    is_active: bool = False


class ModelProfileUpdate(BaseModel):
    """更新模型档案请求"""
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None  # 留空/不传 = 保持原密钥
    models: Optional[List[str]] = None
    active_model: Optional[str] = None
    is_active: Optional[bool] = None


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
        import tempfile

        env_path = ".env"
        
        def _env_quote(value: str) -> str:
            """.env 值转义：含特殊字符时用双引号包裹"""
            value = value.strip()
            if any(c in value for c in (" ", "#", "=", '"', "'", "\\")):
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                return f'"{escaped}"'
            return value
        
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
                    new_lines.append(f"{key}={_env_quote(config_map[key])}\n")
                    updated_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        # 添加未更新的配置项
        for key, value in config_map.items():
            if key not in updated_keys and value:
                new_lines.append(f"{key}={_env_quote(value)}\n")
        
        # 原子写入 .env（临时文件 + os.replace，避免写入中断毁掉整个文件）
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(env_path) or ".", prefix=".env.tmp.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            os.replace(tmp_path, env_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        
        # 同时更新运行时配置
        await save_api_config(request)
        
        return {
            "success": True,
            "message": "配置已保存到.env文件",
        }
        
    except HTTPException:
        raise
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


# ==================== 模型管理（多模型配置档案） ====================

def _db():
    from ..database import SessionLocal
    return SessionLocal()


def _profile_to_response(p: ModelProfile) -> Dict[str, Any]:
    """档案响应：永不返回 API 密钥明文"""
    return p.to_dict(include_key=False)


def _clear_other_active(db, profile_id: str) -> None:
    db.query(ModelProfile).filter(
        ModelProfile.is_active.is_(True),
        ModelProfile.id != profile_id,
    ).update({"is_active": False})
    db.commit()


def _apply_activation(db, profile: ModelProfile) -> None:
    """激活档案：写库 + 应用到运行时配置"""
    _clear_other_active(db, profile.id)
    profile.is_active = True
    db.commit()
    apply_active_model_profile(db)


@router.get("/models")
async def list_model_profiles():
    """获取所有模型档案 + 内置提供商目录（供添加表单）"""
    try:
        seed_default_profile_if_empty()
        db = _db()
        try:
            profiles = db.query(ModelProfile).order_by(ModelProfile.is_active.desc(), ModelProfile.created_at).all()
            return {
                "success": True,
                "data": {
                    "profiles": [_profile_to_response(p) for p in profiles],
                    "catalog": settings.model_providers,
                },
            }
        finally:
            db.close()
    except Exception as e:
        logger.error(f"获取模型档案失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models")
async def create_model_profile(request: ModelProfileCreate):
    """新增模型档案"""
    try:
        profile_id = (request.id or "").strip()
        if not is_valid_profile_id(profile_id):
            raise HTTPException(status_code=400, detail="档案 ID 仅允许字母、数字、下划线、连字符（1-64位）")
        if not request.base_url.strip():
            raise HTTPException(status_code=400, detail="请输入 API Base URL")
        if not request.models:
            raise HTTPException(status_code=400, detail="请至少添加一个模型")

        db = _db()
        try:
            if db.query(ModelProfile).filter(ModelProfile.id == profile_id).first():
                raise HTTPException(status_code=409, detail=f"档案已存在: {profile_id}")

            from ..security.secrets import encrypt_secret
            profile = ModelProfile(
                id=profile_id,
                name=request.name.strip() or profile_id,
                base_url=request.base_url.strip(),
                api_key=encrypt_secret((request.api_key or "").strip()),
                models=request.models,
                active_model=request.active_model or request.models[0],
                is_active=False,
            )
            db.add(profile)
            db.commit()

            if request.is_active:
                _apply_activation(db, profile)

            db.refresh(profile)
            logger.info(f"模型档案已创建: {profile.id}")
            return {"success": True, "data": _profile_to_response(profile), "message": f"已添加 {profile.name}。"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"新增模型档案失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/models/{profile_id}")
async def update_model_profile(profile_id: str, request: ModelProfileUpdate):
    """更新模型档案（api_key 留空 = 保持原密钥）"""
    try:
        db = _db()
        try:
            profile = db.query(ModelProfile).filter(ModelProfile.id == profile_id).first()
            if not profile:
                raise HTTPException(status_code=404, detail=f"档案不存在: {profile_id}")

            if request.name is not None:
                profile.name = request.name.strip() or profile_id
            if request.base_url is not None:
                if not request.base_url.strip():
                    raise HTTPException(status_code=400, detail="请输入 API Base URL")
                profile.base_url = request.base_url.strip()
            if request.api_key:
                # M4: 掩码占位值（前端"未修改"回传）视为未变更；否则作为新密钥加密写入
                if not request.api_key.lstrip().startswith("*"):
                    from ..security.secrets import encrypt_secret
                    profile.api_key = encrypt_secret(request.api_key.strip())
            if request.models is not None:
                if not request.models:
                    raise HTTPException(status_code=400, detail="请至少添加一个模型")
                profile.models = request.models
            if request.active_model is not None:
                profile.active_model = request.active_model
            elif request.models is not None and profile.active_model not in (request.models or []):
                profile.active_model = request.models[0]

            if request.is_active is True:
                _apply_activation(db, profile)
            elif request.is_active is False and profile.is_active:
                profile.is_active = False
                db.commit()

            db.commit()
            db.refresh(profile)
            logger.info(f"模型档案已更新: {profile.id}")
            return {"success": True, "data": _profile_to_response(profile), "message": f"已保存 {profile.name}。"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新模型档案失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/models/{profile_id}")
async def delete_model_profile(profile_id: str):
    """删除模型档案（若为激活档案，运行时回退到 .env 默认配置）"""
    try:
        db = _db()
        try:
            profile = db.query(ModelProfile).filter(ModelProfile.id == profile_id).first()
            if not profile:
                raise HTTPException(status_code=404, detail=f"档案不存在: {profile_id}")
            was_active = profile.is_active
            db.delete(profile)
            db.commit()

            if was_active:
                # 回退：恢复环境变量默认配置（读取 .env 原始值，而非已删档案的运行时密钥）
                import os as _os
                from ..core.agent import agent
                agent.update_llm_config(
                    api_key=_os.environ.get("LLM_API_KEY", ""),
                    base_url=settings.llm_base_url,
                    model=settings.llm_model,
                )
                logger.info(f"删除激活档案 {profile_id}，运行时已回退到 .env 默认配置")

            logger.info(f"模型档案已删除: {profile_id}")
            return {"success": True, "message": f"已删除 {profile.name}。"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除模型档案失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/{profile_id}/activate")
async def activate_model_profile(profile_id: str):
    """激活指定模型档案并应用到运行时"""
    try:
        db = _db()
        try:
            profile = db.query(ModelProfile).filter(ModelProfile.id == profile_id).first()
            if not profile:
                raise HTTPException(status_code=404, detail=f"档案不存在: {profile_id}")
            if not profile.models:
                raise HTTPException(status_code=400, detail="该档案没有可用模型")
            _apply_activation(db, profile)
            db.refresh(profile)
            logger.info(f"模型档案已激活: {profile.id} - {profile.active_model}")
            return {"success": True, "data": _profile_to_response(profile), "message": f"已切换到 {profile.name}（{profile.active_model}）。"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"激活模型档案失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/{profile_id}/test")
async def test_model_profile(profile_id: str):
    """使用档案保存的密钥/地址/模型测试连接"""
    try:
        db = _db()
        try:
            profile = db.query(ModelProfile).filter(ModelProfile.id == profile_id).first()
            if not profile:
                raise HTTPException(status_code=404, detail=f"档案不存在: {profile_id}")
            if not profile.api_key:
                return {"success": False, "message": "该档案未配置 API Key", "model": profile.active_model}
            temp_client = LLMClient(
                api_key=profile.api_key,
                base_url=profile.base_url,
                model=profile.active_model,
            )
            return await temp_client.test_connection()
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"测试模型档案失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

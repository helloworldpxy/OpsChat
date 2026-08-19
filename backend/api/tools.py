# -*- coding: utf-8 -*-
"""
工具管理API接口
管理MCP工具的查询和执行
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..mcp.registry import tool_registry

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def get_tools():
    """
    获取所有工具列表（内置+自定义）
    """
    try:
        from ..database import SessionLocal
        from ..models.custom_tool import CustomTool
        
        tools = tool_registry.get_all_tools()
        result = []
        
        # 获取自定义工具名称列表与创建时间
        db = SessionLocal()
        try:
            custom_rows = db.query(CustomTool).all()
        finally:
            db.close()
        custom_names = {t.name for t in custom_rows}
        custom_dates = {t.name: (t.created_at.isoformat() if t.created_at else None) for t in custom_rows}
        
        for tool in tools:
            tool_data = tool.model_dump()
            tool_data["is_custom"] = tool.name in custom_names
            tool_data["created_at"] = custom_dates.get(tool.name)
            result.append(tool_data)
        
        return {
            "success": True,
            "data": result,
            "total": len(result),
        }
        
    except Exception as e:
        logger.error(f"获取工具列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm")
async def get_llm_tools():
    """
    获取LLM可用的工具列表
    
    Returns:
        LLM工具列表
    """
    try:
        tools = tool_registry.get_llm_tools()
        return {
            "success": True,
            "data": tools,
            "total": len(tools),
        }
        
    except Exception as e:
        logger.error(f"获取LLM工具列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{tool_name}")
async def get_tool(tool_name: str):
    """
    获取工具详情
    
    Args:
        tool_name: 工具名称
        
    Returns:
        工具详情
    """
    try:
        protocol = tool_registry.get_protocol()
        tool = protocol.get_tool(tool_name)
        
        if not tool:
            raise HTTPException(status_code=404, detail=f"工具不存在: {tool_name}")
        
        return {
            "success": True,
            "data": tool.model_dump(),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取工具详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

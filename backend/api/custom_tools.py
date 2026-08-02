# -*- coding: utf-8 -*-
"""
自定义工具管理API
用户可创建、编辑、删除自定义MCP工具
"""

import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import SessionLocal
from ..models.custom_tool import CustomTool
from ..mcp.registry import tool_registry
from ..mcp.protocol import ToolDefinition, RiskLevel
from ..mcp.tools.custom import CustomToolExecutor

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateToolRequest(BaseModel):
    """创建工具请求"""
    name: str
    description: str
    category: str = "custom"
    risk_level: str = "low"
    requires_approval: bool = False
    parameters: Optional[Dict[str, Any]] = None
    command_template: str
    command_type: str = "shell"


class UpdateToolRequest(BaseModel):
    """更新工具请求"""
    description: Optional[str] = None
    category: Optional[str] = None
    risk_level: Optional[str] = None
    requires_approval: Optional[bool] = None
    parameters: Optional[Dict[str, Any]] = None
    command_template: Optional[str] = None
    command_type: Optional[str] = None
    is_enabled: Optional[bool] = None


# 预置工具模板
TOOL_TEMPLATES = [
    {
        "name": "check_port",
        "description": "检查指定端口是否被占用",
        "category": "network",
        "risk_level": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "端口号"}
            },
            "required": ["port"]
        },
        "command_template": "ss -tlnp | grep :{port}",
        "command_type": "shell",
    },
    {
        "name": "check_service_status",
        "description": "检查指定服务的运行状态",
        "category": "service",
        "risk_level": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "description": "服务名称"}
            },
            "required": ["service_name"]
        },
        "command_template": "systemctl status {service_name}",
        "command_type": "shell",
    },
    {
        "name": "get_file_info",
        "description": "获取文件的详细信息（大小、修改时间等）",
        "category": "file",
        "risk_level": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"}
            },
            "required": ["path"]
        },
        "command_template": "ls -lh \"{path}\"",
        "command_type": "shell",
    },
    {
        "name": "check_dns",
        "description": "检查DNS解析是否正常",
        "category": "network",
        "risk_level": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "域名"},
                "dns_server": {"type": "string", "description": "DNS服务器（可选）", "default": ""}
            },
            "required": ["domain"]
        },
        "command_template": "nslookup {domain} {dns_server}",
        "command_type": "shell",
    },
    {
        "name": "tail_log",
        "description": "查看日志文件的最后N行",
        "category": "system",
        "risk_level": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "日志文件路径"},
                "lines": {"type": "integer", "description": "行数", "default": 50}
            },
            "required": ["path"]
        },
        "command_template": "tail -n {lines} \"{path}\"",
        "command_type": "shell",
    },
]


@router.get("/")
async def list_custom_tools():
    """获取所有自定义工具"""
    try:
        db = SessionLocal()
        try:
            tools = db.query(CustomTool).filter(CustomTool.is_enabled == True).all()
            return {
                "success": True,
                "data": [t.to_dict() for t in tools],
                "total": len(tools),
            }
        finally:
            db.close()
    except Exception as e:
        logger.error(f"获取自定义工具列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/templates")
async def get_tool_templates():
    """获取工具模板列表"""
    return {
        "success": True,
        "data": TOOL_TEMPLATES,
    }


@router.post("/")
async def create_custom_tool(request: CreateToolRequest):
    """创建自定义工具"""
    try:
        db = SessionLocal()
        try:
            # 检查名称是否与内置工具冲突
            existing_builtin = tool_registry.get_protocol().get_tool(request.name)
            if existing_builtin:
                raise HTTPException(
                    status_code=400,
                    detail=f"工具名称 '{request.name}' 与内置工具冲突，请使用其他名称"
                )

            # 检查是否已存在
            existing = db.query(CustomTool).filter(CustomTool.name == request.name).first()
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"工具 '{request.name}' 已存在"
                )

            # 创建工具
            tool = CustomTool(
                name=request.name,
                description=request.description,
                category=request.category,
                risk_level=request.risk_level,
                requires_approval=request.requires_approval,
                parameters=request.parameters,
                command_template=request.command_template,
                command_type=request.command_type,
                is_builtin=False,
                is_enabled=True,
            )
            db.add(tool)
            db.commit()
            db.refresh(tool)

            # 注册到MCP协议
            _register_custom_tool(tool)

            logger.info(f"自定义工具创建成功: {request.name}")
            return {"success": True, "data": tool.to_dict()}

        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建自定义工具失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tool_id}")
async def update_custom_tool(tool_id: str, request: UpdateToolRequest):
    """更新自定义工具"""
    try:
        db = SessionLocal()
        try:
            tool = db.query(CustomTool).filter(CustomTool.id == tool_id).first()
            if not tool:
                raise HTTPException(status_code=404, detail="工具不存在")
            if tool.is_builtin:
                raise HTTPException(status_code=403, detail="不能修改内置工具")

            # 更新字段
            if request.description is not None:
                tool.description = request.description
            if request.category is not None:
                tool.category = request.category
            if request.risk_level is not None:
                tool.risk_level = request.risk_level
            if request.requires_approval is not None:
                tool.requires_approval = request.requires_approval
            if request.parameters is not None:
                tool.parameters = request.parameters
            if request.command_template is not None:
                tool.command_template = request.command_template
            if request.command_type is not None:
                tool.command_type = request.command_type
            if request.is_enabled is not None:
                tool.is_enabled = request.is_enabled

            db.commit()
            db.refresh(tool)

            # 重新注册
            _unregister_custom_tool(tool.name)
            if tool.is_enabled:
                _register_custom_tool(tool)

            return {"success": True, "data": tool.to_dict()}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新自定义工具失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tool_id}")
async def delete_custom_tool(tool_id: str):
    """删除自定义工具（只能删除用户创建的）"""
    try:
        db = SessionLocal()
        try:
            tool = db.query(CustomTool).filter(CustomTool.id == tool_id).first()
            if not tool:
                raise HTTPException(status_code=404, detail="工具不存在")
            if tool.is_builtin:
                raise HTTPException(status_code=403, detail="不能删除内置工具")

            # 从MCP协议中注销
            _unregister_custom_tool(tool.name)

            # 从数据库删除
            db.delete(tool)
            db.commit()

            logger.info(f"自定义工具已删除: {tool.name}")
            return {"success": True, "message": f"工具 {tool.name} 已删除"}

        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除自定义工具失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _register_custom_tool(tool: CustomTool):
    """将自定义工具注册到MCP协议"""
    protocol = tool_registry.get_protocol()

    definition = ToolDefinition(
        name=tool.name,
        description=tool.description,
        category=tool.category,
        parameters=tool.parameters or {"type": "object", "properties": {}},
        risk_level=RiskLevel(tool.risk_level),
        requires_approval=tool.requires_approval,
    )

    executor = CustomToolExecutor(
        definition=definition,
        command_template=tool.command_template,
        command_type=tool.command_type,
    )

    protocol.register_tool(definition, executor)
    logger.info(f"自定义工具已注册: {tool.name}")


def _unregister_custom_tool(tool_name: str):
    """从MCP协议中注销自定义工具"""
    protocol = tool_registry.get_protocol()
    if tool_name in protocol.tools:
        del protocol.tools[tool_name]
    if tool_name in protocol.executors:
        del protocol.executors[tool_name]
    logger.info(f"自定义工具已注销: {tool_name}")


def load_custom_tools_from_db():
    """从数据库加载所有自定义工具"""
    try:
        db = SessionLocal()
        try:
            tools = db.query(CustomTool).filter(
                CustomTool.is_enabled == True
            ).all()

            for tool in tools:
                _register_custom_tool(tool)

            logger.info(f"从数据库加载了 {len(tools)} 个自定义工具")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"加载自定义工具失败: {e}")

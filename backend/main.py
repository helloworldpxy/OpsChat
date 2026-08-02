# -*- coding: utf-8 -*-
"""
FastAPI应用入口
智能运维Agent后端服务
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .config import settings
from .database import init_db_sync
from .utils.logger import setup_logging
from .mcp.registry import tool_registry
from .api import chat, tools, audit, settings as settings_api, models, custom_tools

# 在模块级别导入所有模型并初始化数据库（确保 TestClient 不触发 lifespan 时也能用）
from .models import audit as _audit, custom_tool as _custom_tool, tool as _tool  # noqa: F401
init_db_sync()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("正在启动智能运维Agent服务...")
    
    # 数据库已在模块加载时初始化，这里不再重复
    
    # 初始化工具注册中心
    tool_registry.initialize()
    logger.info("MCP工具注册完成")
    
    # 加载用户自定义工具
    from .api.custom_tools import load_custom_tools_from_db
    load_custom_tools_from_db()
    
    # 创建数据目录
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    logger.info("智能运维Agent服务启动完成")
    
    yield
    
    # 关闭时执行
    logger.info("智能运维Agent服务正在关闭...")


# 创建FastAPI应用
app = FastAPI(
    title="智能运维Agent",
    description="智能运维Agent（OpsChat）",
    version=settings.app_version,
    lifespan=lifespan,
)

# 配置CORS（从配置读取，支持逗号分隔的源列表）
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
_allow_credentials = "*" not in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 编码中间件 - 确保所有响应使用UTF-8
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class UTF8Middleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if "content-type" in response.headers and "charset" not in response.headers["content-type"]:
            if response.headers["content-type"].startswith("text/"):
                response.headers["content-type"] += "; charset=utf-8"
        return response

app.add_middleware(UTF8Middleware)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 配置模板
templates = Jinja2Templates(directory="backend/templates")
templates.env.charset = "utf-8"
templates.env.loader.encoding = "utf-8"

# 注册API路由
app.include_router(chat.router, prefix="/api/chat", tags=["对话"])
app.include_router(tools.router, prefix="/api/tools", tags=["工具"])
app.include_router(audit.router, prefix="/api/audit", tags=["审计"])
app.include_router(settings_api.router, prefix="/api/settings", tags=["设置"])
app.include_router(models.router, prefix="/api/models", tags=["模型"])
app.include_router(custom_tools.router, prefix="/api/custom-tools", tags=["自定义工具"])


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """首页"""
    return templates.TemplateResponse(request, "index.html")


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "service": settings.app_name,
    }


@app.get("/api/status")
async def get_status():
    """获取系统状态"""
    import psutil
    
    return {
        "success": True,
        "data": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "tools_count": len(tool_registry.get_all_tools()),
            "llm_configured": bool(settings.llm_api_key),
        },
    }

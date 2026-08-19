# -*- coding: utf-8 -*-
"""
API路由模块
"""

from .chat import router as chat_router
from .tools import router as tools_router
from .audit import router as audit_router
from .settings import router as settings_router
from .models import router as models_router

__all__ = [
    "chat_router",
    "tools_router",
    "audit_router",
    "settings_router",
    "models_router",
]

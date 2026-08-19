# -*- coding: utf-8 -*-
"""
基础登录认证（HTTP Basic）
可选安全层：默认关闭。开启后所有页面与 API 需 Basic Auth，
静态资源（/static）放行以便样式/脚本加载。
"""

import base64
import hmac
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings

logger = logging.getLogger(__name__)

# 放行的路径前缀（静态资源无需认证）
_PUBLIC_PREFIXES = ("/static",)


def _parse_basic_auth(header: str) -> tuple:
    """解析 Authorization: Basic base64(user:pass)"""
    if not header or not header.lower().startswith("basic "):
        return ("", "")
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8", errors="ignore")
    except Exception:
        return ("", "")
    user, _, pwd = decoded.partition(":")
    return (user, pwd)


def _credentials_configured() -> bool:
    """密码未配置时视为认证未启用（防止误锁死）"""
    return bool(settings.auth_enabled and settings.auth_password)


def check_credentials(user: str, password: str) -> bool:
    """校验用户名密码（常量时间比较，避免用户名枚举/时序侧信道）"""
    return (
        hmac.compare_digest(user or "", settings.auth_username or "")
        and hmac.compare_digest(password or "", settings.auth_password or "")
    )


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic 认证中间件（enable_auth 关闭时直通）"""

    async def dispatch(self, request: Request, call_next):
        if not _credentials_configured():
            return await call_next(request)

        # 静态资源放行
        if request.url.path.startswith(_PUBLIC_PREFIXES):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        user, pwd = _parse_basic_auth(auth)
        if not check_credentials(user, pwd):
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="OpsChat"'},
            )

        return await call_next(request)


def auth_middleware() -> BaseHTTPMiddleware:
    """中间件工厂"""
    return BasicAuthMiddleware()
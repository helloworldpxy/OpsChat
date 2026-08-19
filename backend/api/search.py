# -*- coding: utf-8 -*-
"""
全文检索API接口
对对话历史与审计日志执行 FTS5 全文检索
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query

from ..search import search_messages, search_audit

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def search(
    q: Optional[str] = Query(None, max_length=200, description="检索关键词"),
    scope: str = Query("messages", pattern="^(messages|audit)$", description="检索范围"),
    limit: int = Query(50, ge=1, le=100, description="返回条数"),
):
    """
    全文检索

    Args:
        q: 检索关键词
        scope: messages（对话消息）或 audit（审计日志）
        limit: 返回条数

    Returns:
        检索结果列表
    """
    if not q or not q.strip():
        return {"success": True, "data": [], "total": 0}

    if scope == "audit":
        data = search_audit(q, limit)
    else:
        data = search_messages(q, limit)

    return {
        "success": True,
        "data": data,
        "total": len(data),
        "scope": scope,
        "query": q,
    }
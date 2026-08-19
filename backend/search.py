# -*- coding: utf-8 -*-
"""
全文检索模块（SQLite FTS5 + trigram）
- 为对话消息（conversation_messages）与审计日志（audit_logs）建立 FTS5 索引
- 短中文查询（<3 字符，trigram 无法覆盖）自动降级 LIKE 子串匹配
"""

import logging
from typing import List, Dict, Any, Optional

from sqlalchemy import text

from .database import engine

logger = logging.getLogger(__name__)

# FTS5 表 + 触发器 + 回填（幂等）
_DDL = [
    # 对话消息全文索引
    """CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts
       USING fts5(content, role, conversation_id UNINDEXED, tokenize='trigram')""",
    # 审计日志全文索引
    """CREATE VIRTUAL TABLE IF NOT EXISTS audit_fts
       USING fts5(content, trace_id UNINDEXED, stage UNINDEXED, tokenize='trigram')""",
    # 新消息自动入索引
    """CREATE TRIGGER IF NOT EXISTS conversation_fts_insert
       AFTER INSERT ON conversation_messages
       BEGIN
         INSERT INTO conversation_fts(rowid, content, role, conversation_id)
         VALUES (new.rowid, new.content, new.role, new.conversation_id);
       END""",
    """CREATE TRIGGER IF NOT EXISTS conversation_fts_delete
       AFTER DELETE ON conversation_messages
       BEGIN
         DELETE FROM conversation_fts WHERE rowid = old.rowid;
       END""",
    """CREATE TRIGGER IF NOT EXISTS conversation_fts_update
       AFTER UPDATE ON conversation_messages
       BEGIN
         DELETE FROM conversation_fts WHERE rowid = old.rowid;
         INSERT INTO conversation_fts(rowid, content, role, conversation_id)
         VALUES (new.rowid, new.content, new.role, new.conversation_id);
       END""",
    """CREATE TRIGGER IF NOT EXISTS audit_fts_insert
       AFTER INSERT ON audit_logs
       BEGIN
         INSERT INTO audit_fts(rowid, content, trace_id, stage)
         VALUES (new.rowid, new.content, new.trace_id, new.stage);
       END""",
    """CREATE TRIGGER IF NOT EXISTS audit_fts_delete
       AFTER DELETE ON audit_logs
       BEGIN
         DELETE FROM audit_fts WHERE rowid = old.rowid;
       END""",
    """CREATE TRIGGER IF NOT EXISTS audit_fts_update
       AFTER UPDATE ON audit_logs
       BEGIN
         DELETE FROM audit_fts WHERE rowid = old.rowid;
         INSERT INTO audit_fts(rowid, content, trace_id, stage)
         VALUES (new.rowid, new.content, new.trace_id, new.stage);
       END""",
    # 回填已有数据
    """INSERT INTO conversation_fts(rowid, content, role, conversation_id)
       SELECT rowid, content, role, conversation_id FROM conversation_messages
       WHERE rowid NOT IN (SELECT rowid FROM conversation_fts)""",
    """INSERT INTO audit_fts(rowid, content, trace_id, stage)
       SELECT rowid, content, trace_id, stage FROM audit_logs
       WHERE rowid NOT IN (SELECT rowid FROM audit_fts)""",
    # 清理残留（源表已删除但 FTS 未清理的历史孤儿行）
    """DELETE FROM conversation_fts
       WHERE rowid NOT IN (SELECT rowid FROM conversation_messages)""",
    """DELETE FROM audit_fts
       WHERE rowid NOT IN (SELECT rowid FROM audit_logs)""",
]


def ensure_fts() -> None:
    """幂等创建 FTS5 虚拟表 + 触发器，并回填已有数据"""
    try:
        with engine.begin() as conn:
            for stmt in _DDL:
                conn.execute(text(stmt))
    except Exception as e:
        logger.warning(f"初始化全文索引失败: {e}")


def _has_cjk(text: str) -> bool:
    """是否包含中日韩统一表意文字"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _escape_like(term: str) -> str:
    """转义 LIKE 通配符"""
    return (term.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_"))


def _escape_fts(term: str) -> str:
    """转义 FTS5 短语查询特殊字符，避免被解释为操作符导致误匹配"""
    return term.replace('"', '""').replace("*", " ").replace("^", " ")


def _iso(ts) -> Optional[str]:
    """datetime 或 SQLite 文本时间 转 ISO 字符串，兼容 None"""
    if not ts:
        return None
    if isinstance(ts, str):
        return ts.replace(" ", "T")
    return ts.isoformat()


def search_messages(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    全文检索对话消息
    命中规则：优先 FTS5 MATCH；FTS 失败或命中为空（索引过期/语法）时回退 LIKE
    """
    term = query.strip()
    if not term:
        return []

    results: List[Dict[str, Any]] = []
    try:
        with engine.connect() as conn:
            # 长度≥3 或纯 ASCII 时尝试 FTS5（trigram 对 1-2 字符中文无效）
            if len(term) >= 3 or not _has_cjk(term):
                try:
                    rows = conn.execute(text(
                        "SELECT m.rowid AS mid, m.conversation_id, m.role, m.content, "
                        "       m.created_at, c.title AS conversation_title "
                        "FROM conversation_fts f "
                        "JOIN conversation_messages m ON m.rowid = f.rowid "
                        "JOIN conversations c ON c.id = m.conversation_id AND c.is_active = 1 "
                        "WHERE conversation_fts MATCH :q "
                        "ORDER BY m.created_at DESC LIMIT :limit"
                    ), {"q": f'"{_escape_fts(term)}"', "limit": limit}).fetchall()
                    results = [dict(r._mapping) for r in rows]
                except Exception as e:
                    logger.debug(f"FTS5 对话检索失败，回退 LIKE: {e}")
                    results = []

            if not results:
                pat = f"%{_escape_like(term)}%"
                rows = conn.execute(text(
                    "SELECT m.rowid AS mid, m.conversation_id, m.role, m.content, "
                    "       m.created_at, c.title AS conversation_title "
                    "FROM conversation_messages m "
                    "JOIN conversations c ON c.id = m.conversation_id AND c.is_active = 1 "
                    "WHERE m.content LIKE :pat ESCAPE '\\' "
                    "ORDER BY m.created_at DESC LIMIT :limit"
                ), {"pat": pat, "limit": limit}).fetchall()
                results = [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.warning(f"对话全文检索失败: {e}")

    for r in results:
        r["created_at"] = _iso(r.get("created_at"))
    return results


def search_audit(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    全文检索审计日志
    命中规则：优先 FTS5 MATCH；FTS 失败或命中为空（索引过期/语法）时回退 LIKE
    """
    term = query.strip()
    if not term:
        return []

    results: List[Dict[str, Any]] = []
    try:
        with engine.connect() as conn:
            if len(term) >= 3 or not _has_cjk(term):
                try:
                    rows = conn.execute(text(
                        "SELECT a.rowid AS aid, a.trace_id, a.stage, a.content, a.timestamp, "
                        "       a.tool_name "
                        "FROM audit_fts f JOIN audit_logs a ON a.rowid = f.rowid "
                        "WHERE audit_fts MATCH :q "
                        "ORDER BY a.timestamp DESC LIMIT :limit"
                    ), {"q": f'"{_escape_fts(term)}"', "limit": limit}).fetchall()
                    results = [dict(r._mapping) for r in rows]
                except Exception as e:
                    logger.debug(f"FTS5 审计检索失败，回退 LIKE: {e}")
                    results = []

            if not results:
                pat = f"%{_escape_like(term)}%"
                rows = conn.execute(text(
                    "SELECT a.rowid AS aid, a.trace_id, a.stage, a.content, a.timestamp, "
                    "       a.tool_name "
                    "FROM audit_logs a "
                    "WHERE a.content LIKE :pat ESCAPE '\\' "
                    "ORDER BY a.timestamp DESC LIMIT :limit"
                ), {"pat": pat, "limit": limit}).fetchall()
                results = [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.warning(f"审计全文检索失败: {e}")

    for r in results:
        r["timestamp"] = _iso(r.get("timestamp"))
    return results
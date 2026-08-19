# -*- coding: utf-8 -*-
"""
阶段四测试：FTS5 全文检索 + 会话标题自动生成
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.database import SessionLocal, init_db_sync
from backend.models.audit import Conversation, ConversationMessage, AuditLog
from backend.search import ensure_fts, search_messages, search_audit


@pytest.fixture(autouse=True)
def ensure_test_fts():
    """确保 FTS 表在测试库中存在"""
    init_db_sync()
    ensure_fts()
    yield


def _make_conversation(title="新对话"):
    db = SessionLocal()
    try:
        conv = Conversation(id=str(uuid.uuid4()), title=title)
        db.add(conv)
        db.commit()
        return conv.id
    finally:
        db.close()


def _add_message(conv_id, role, content):
    db = SessionLocal()
    try:
        msg = ConversationMessage(
            id=str(uuid.uuid4()), conversation_id=conv_id, role=role, content=content
        )
        db.add(msg)
        db.commit()
    finally:
        db.close()


class TestSearch:
    def test_fts_tables_created(self):
        """FTS5 虚拟表与触发器创建成功"""
        from sqlalchemy import text
        db = SessionLocal()
        try:
            tables = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_fts'")).fetchall()
            names = [t[0] for t in tables]
            assert "conversation_fts" in names
            assert "audit_fts" in names
            triggers = db.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger'")
            ).fetchall()
            trigger_names = [t[0] for t in triggers]
            assert "conversation_fts_insert" in trigger_names
            assert "audit_fts_insert" in trigger_names
            # T1: DELETE/UPDATE 触发器必须存在，否则删除消息后 FTS 残留导致行号复用冲突
            assert "conversation_fts_delete" in trigger_names
            assert "conversation_fts_update" in trigger_names
            assert "audit_fts_delete" in trigger_names
        finally:
            db.close()

    def test_fts_delete_syncs(self):
        """T1: 删除消息后 FTS 同步清理（DELETE 触发器）"""
        from sqlalchemy import text
        conv_id = _make_conversation()
        _add_message(conv_id, "user", "会被删除的检索词DELETEKEY123")
        # 命中
        assert any(r["conversation_id"] == conv_id for r in search_messages("DELETEKEY123"))

        # 删除消息行 → FTS 应同步清理
        db = SessionLocal()
        try:
            db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == conv_id).delete()
            db.commit()
        finally:
            db.close()
        assert search_messages("DELETEKEY123") == []

    def test_fts_update_syncs(self):
        """T1: 更新消息内容后 FTS 同步（UPDATE 触发器）"""
        conv_id = _make_conversation()
        _add_message(conv_id, "user", "旧内容OLDKEY999")

        db = SessionLocal()
        try:
            msg = db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == conv_id).first()
            msg.content = "新内容NEWKEY888"
            db.commit()
        finally:
            db.close()

        assert search_messages("OLDKEY999") == []
        assert any(r["conversation_id"] == conv_id for r in search_messages("NEWKEY888"))

    def test_search_messages_like_cjk(self):
        """短中文（<3字符）走 LIKE 降级命中"""
        conv_id = _make_conversation()
        _add_message(conv_id, "user", "帮我查看网络连接状态")
        result = search_messages("网络")
        assert len(result) >= 1
        hit = next(r for r in result if r["conversation_id"] == conv_id)
        assert hit["conversation_title"] == "新对话"

    def test_search_messages_fts_trigram(self):
        """≥3 字符中文走 FTS5 trigram 命中"""
        conv_id = _make_conversation("标题测试")
        _add_message(conv_id, "user", "检查磁盘空间使用情况")
        result = search_messages("磁盘空间")
        assert any(r["conversation_id"] == conv_id for r in result)

    def test_search_messages_no_match(self):
        """无命中返回空列表"""
        _make_conversation()
        _add_message(_make_conversation(), "user", "正常日志内容")
        assert search_messages("完全不存在的关键词XYZ") == []

    def test_search_audit(self):
        """审计日志检索"""
        db = SessionLocal()
        try:
            log = AuditLog(trace_id="tr_test_1", stage="llm_reasoning", content="正在分析磁盘问题")
            db.add(log)
            db.commit()
        finally:
            db.close()

        result = search_audit("磁盘")
        assert any(r["trace_id"] == "tr_test_1" for r in result)

    def test_search_endpoint(self, client):
        """/api/search 接口可用"""
        resp = client.get("/api/search", params={"q": "系统", "scope": "messages"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

        resp2 = client.get("/api/search", params={"q": "", "scope": "audit"})
        assert resp2.json()["data"] == []


class TestTitleGeneration:
    def test_generate_title_updates_db(self, monkeypatch):
        """默认标题 + 恰好 1 条用户消息 → 生成并落库"""
        from backend.core import title as title_mod
        async def fake_generate(llm_client, user_message):
            return "查看系统状态"
        monkeypatch.setattr(title_mod, "generate_title", fake_generate)

        conv_id = _make_conversation()
        _add_message(conv_id, "user", "帮我看看系统状态")

        result = asyncio.run(title_mod.maybe_generate_title(conv_id))
        assert result == "查看系统状态"

        db = SessionLocal()
        try:
            conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
            assert conv.title == "查看系统状态"
        finally:
            db.close()

    def test_generate_title_skips_renamed(self, monkeypatch):
        """已重命名的会话不生成"""
        from backend.core import title as title_mod
        async def fake_generate(llm_client, user_message):
            return "不应使用"
        monkeypatch.setattr(title_mod, "generate_title", fake_generate)

        conv_id = _make_conversation(title="手动标题")
        _add_message(conv_id, "user", "你好")

        assert asyncio.run(title_mod.maybe_generate_title(conv_id)) is None

    def test_generate_title_skips_multiple_messages(self, monkeypatch):
        """超过 1 条用户消息不生成"""
        from backend.core import title as title_mod
        async def fake_generate(llm_client, user_message):
            return "不应使用"
        monkeypatch.setattr(title_mod, "generate_title", fake_generate)

        conv_id = _make_conversation()
        _add_message(conv_id, "user", "你好")
        _add_message(conv_id, "user", "再见")

        assert asyncio.run(title_mod.maybe_generate_title(conv_id)) is None
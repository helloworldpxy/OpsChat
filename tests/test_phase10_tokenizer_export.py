# -*- coding: utf-8 -*-
"""
阶段十测试：DeepSeek V3 tokenizer 精确计数 + 审计日志导出 + 会话 token 聚合
"""

import io
import json

import pytest

from backend.core.token_counter import count_tokens, count_json_tokens, estimate_tokens
from backend.core.agent import agent
from backend.security.permission import permission_service


@pytest.fixture(autouse=True)
def reset_state():
    permission_service.reset()
    yield
    permission_service.reset()


class TestTokenCounter:
    def test_tokenizer_loaded(self):
        # 真实 DeepSeek V3 tokenizer（128k 词表）应成功加载
        from backend.core.token_counter import _load_tokenizer
        assert _load_tokenizer() is not None

    def test_empty_text(self):
        assert count_tokens("") == 0

    def test_ascii_counting(self):
        # "Hello!" = 2 tokens（真实 BPE）
        assert count_tokens("Hello!") == 2

    def test_cjk_counting(self):
        # 中文按真实 tokenizer 计数（系统信息 = 2 tokens）
        assert count_tokens("系统信息") == 2

    def test_long_text_matches_vocab(self):
        # 200 个 a = 25 tokens（真实 BPE 8字符/词元）
        assert count_tokens("a" * 200) == 25

    def test_json_counting(self):
        assert count_json_tokens([]) > 0
        assert count_json_tokens({"role": "user", "content": "你好"}) > 0

    def test_estimate_fallback_exists(self):
        # 回退函数仍然可用
        assert estimate_tokens("") == 0
        assert estimate_tokens("系统信息") >= 4


class TestAuditExport:
    def test_export_csv(self, client):
        resp = client.get("/api/audit/export?format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        assert resp.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
        # 表头存在
        assert b"timestamp,trace_id,stage" in resp.content

    def test_export_json(self, client):
        resp = client.get("/api/audit/export?format=json")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]
        payload = json.loads(resp.content)
        assert payload["success"] is True
        assert "data" in payload

    def test_export_invalid_format(self, client):
        resp = client.get("/api/audit/export?format=xml")
        assert resp.status_code == 400

    def test_export_empty_db_csv(self, client):
        # 用不存在的 trace_id 过滤，模拟"空库/无匹配"导出：
        # CSV 应只含表头（BOM + 列名），不报 500
        resp = client.get("/api/audit/export", params={
            "format": "csv", "trace_id": "no_such_trace_xyz",
        })
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert resp.content.startswith(b"\xef\xbb\xbf")
        lines = resp.content.decode("utf-8-sig").splitlines()
        assert len(lines) == 1  # 仅表头
        assert "timestamp,trace_id,stage" in lines[0]

    def test_export_empty_db_json(self, client):
        resp = client.get("/api/audit/export", params={
            "format": "json", "trace_id": "no_such_trace_xyz",
        })
        assert resp.status_code == 200
        payload = json.loads(resp.content)
        assert payload["success"] is True
        assert payload["count"] == 0
        assert payload["data"] == []


class TestConversationTokenAggregation:
    def test_message_persists_tokens(self, monkeypatch):
        # 通过 agent 流程验证消息落库时携带精确 token 数
        import asyncio
        from backend.database import async_engine
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy import select
        from backend.models.audit import ConversationMessage

        class FakeLLM:
            async def chat(self, messages, tools=None, stream=False):
                async def gen():
                    yield {"type": "content", "content": "一切正常"}
                    yield {"type": "finish", "finish_reason": "stop"}
                return gen()

        monkeypatch.setattr(agent, "llm_client", FakeLLM())
        session_id = "tok_s1"

        async def run():
            async for _evt in await agent.process_message("检查系统", session_id, stream=True):
                pass

        asyncio.run(run())

        # 查询落库消息的 token 字段
        async def fetch():
            async with AsyncSession(async_engine) as db:
                return (await db.execute(
                    select(ConversationMessage).where(
                        ConversationMessage.conversation_id == session_id
                    ).order_by(ConversationMessage.created_at.asc())
                )).scalars().all()

        rows = asyncio.run(fetch())

        # 用户消息带 prompt_tokens，助手消息带 completion_tokens
        user_msg = rows[0]
        assert user_msg.role == "user"
        assert user_msg.prompt_tokens > 0
        assert user_msg.completion_tokens == 0

        asst_msg = rows[1]
        assert asst_msg.role == "assistant"
        assert asst_msg.completion_tokens > 0

        # 清理
        agent.clear_conversation(session_id)
        async def cleanup():
            from sqlalchemy import delete
            async with AsyncSession(async_engine) as db:
                await db.execute(delete(ConversationMessage).where(
                    ConversationMessage.conversation_id == session_id))
                await db.commit()
        asyncio.run(cleanup())

    def test_conversation_list_aggregates_tokens(self, client):
        # 直接落库两条消息，验证列表接口聚合 total_tokens
        import uuid
        from backend.database import SessionLocal
        from backend.models.audit import Conversation, ConversationMessage

        conv_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(Conversation(id=conv_id, title="token 聚合测试"))
            db.add(ConversationMessage(
                conversation_id=conv_id, role="user", content="你好",
                message_type="text", prompt_tokens=10, completion_tokens=0,
            ))
            db.add(ConversationMessage(
                conversation_id=conv_id, role="assistant", content="回复",
                message_type="text", prompt_tokens=0, completion_tokens=5,
            ))
            db.commit()
        finally:
            db.close()

        try:
            resp = client.get("/api/chat/conversations")
            assert resp.status_code == 200
            convs = resp.json()["data"]
            target = next(c for c in convs if c["id"] == conv_id)
            assert target["prompt_tokens"] == 10
            assert target["completion_tokens"] == 5
            assert target["total_tokens"] == 15
        finally:
            db = SessionLocal()
            try:
                db.query(ConversationMessage).filter(
                    ConversationMessage.conversation_id == conv_id).delete()
                db.query(Conversation).filter(Conversation.id == conv_id).delete()
                db.commit()
            finally:
                db.close()
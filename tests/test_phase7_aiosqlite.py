# -*- coding: utf-8 -*-
"""
阶段七测试：aiosqlite 异步落库
验证 agent 历史与思维链通过异步引擎持久化，且同步引擎可读回
"""

import asyncio

from backend.core.agent import agent
from backend.core.chain_of_thought import cot_manager
from backend.database import SessionLocal
from backend.models.audit import Conversation, ConversationMessage, AuditLog


class FakeLLM:
    """普通文本响应（不触发工具）"""

    async def chat(self, messages, tools=None, stream=False):
        if stream:
            async def gen():
                yield {"type": "content", "content": "异步落库正常"}
                yield {"type": "finish", "finish_reason": "stop"}
            return gen()
        return {"content": "异步落库正常", "role": "assistant", "finish_reason": "stop",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def test_conversation_persisted_via_async_engine(monkeypatch):
    """process_message 后，用户消息与助手消息已通过 aiosqlite 写入，同步引擎可读回"""
    monkeypatch.setattr(agent, "llm_client", FakeLLM())

    async def run():
        await agent.process_message("异步落库验证", "p7_conv", stream=False)

    asyncio.run(run())

    db = SessionLocal()
    try:
        msgs = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == "p7_conv"
        ).order_by(ConversationMessage.created_at).all()
        roles = [m.role for m in msgs]
        assert "user" in roles
        assert "assistant" in roles
        assert any("异步落库正常" in (m.content or "") for m in msgs)
        conv = db.query(Conversation).filter(Conversation.id == "p7_conv").first()
        assert conv is not None
    finally:
        db.close()
    # 清理内存会话
    agent.conversations.pop("p7_conv", None)


def test_cot_persisted_via_async_engine():
    """思维链各阶段已通过 aiosqlite 写入 audit_logs，同步引擎可读回"""
    trace_id = cot_manager.create_trace()

    async def run():
        await cot_manager.log_user_input(trace_id, "诊断磁盘")
        await cot_manager.log_llm_reasoning(trace_id, "test-model", "计划调用工具")
        await cot_manager.log_response(trace_id, "完成")

    asyncio.run(run())

    db = SessionLocal()
    try:
        rows = db.query(AuditLog).filter(AuditLog.trace_id == trace_id).order_by(AuditLog.stage_order).all()
        stages = [r.stage for r in rows]
        assert "user_input" in stages
        assert "llm_reasoning" in stages
        assert "response" in stages
    finally:
        db.close()
    cot_manager.clear_trace(trace_id)


def test_tool_stage_persisted_with_truncated_result():
    """工具执行阶段落库时 result 已截断（不撑爆审计库）"""
    trace_id = cot_manager.create_trace()
    big_result = {"stdout": "x" * 50000, "success": True}

    async def run():
        await cot_manager.log_execution(trace_id, "disk_usage", big_result, True)

    asyncio.run(run())

    db = SessionLocal()
    try:
        row = db.query(AuditLog).filter(AuditLog.trace_id == trace_id, AuditLog.stage == "execution").first()
        assert row is not None
        assert row.tool_name == "disk_usage"
        assert row.tool_result is None or len(row.tool_result) < 5000
    finally:
        db.close()
    cot_manager.clear_trace(trace_id)
# -*- coding: utf-8 -*-
"""
对话API接口
处理用户与Agent的对话
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, AsyncGenerator
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func

from ..config import settings
from ..core.agent import agent
from ..core.chain_of_thought import cot_manager
from ..core.title import maybe_generate_title
from ..database import SessionLocal
from ..models.audit import Conversation, ConversationMessage

logger = logging.getLogger(__name__)

router = APIRouter()

# 心跳包装内部使用的流结束哨兵
_STREAM_END = object()


class ChatRequest(BaseModel):
    """对话请求"""
    message: str = Field(min_length=1, max_length=20000, description="用户消息")
    session_id: Optional[str] = Field(None, max_length=64, description="会话ID")
    stream: bool = False

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("消息不能为空")
        return v


class ConfirmRequest(BaseModel):
    """权限审批确认请求"""
    session_id: str = Field(max_length=64)
    request_id: str = Field(max_length=64)
    reply: str = "once"  # once（仅本次）/ always（始终允许）/ reject（拒绝）
    password: Optional[str] = None
    stream: bool = False


@router.post("/")
async def chat(request: ChatRequest):
    """
    对话接口
    
    Args:
        request: 对话请求
        
    Returns:
        对话响应
    """
    try:
        session_id = request.session_id or "default"
        
        if request.stream:
            # 流式响应
            return StreamingResponse(
                _stream_response(request.message, session_id),
                media_type="text/event-stream",
            )
        else:
            # 普通响应
            result = await agent.process_message(
                user_message=request.message,
                session_id=session_id,
                stream=False,
            )
            # 自动生成会话标题（仅默认标题 + 恰好 1 条用户消息）
            new_title = await maybe_generate_title(session_id)
            if new_title:
                result["title"] = new_title
            return result
            
    except Exception as e:
        logger.error(f"对话处理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _with_heartbeat(
    stream: AsyncGenerator[Dict[str, Any], None],
    interval: Optional[int] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    为异步生成器注入 SSE 心跳
    长工具执行/LLM 生成间隙，若超过 interval 秒无事件产出，则产出 heartbeat 事件，
    避免前端 fetch 或中间代理/网关（如 Nginx 60s）判定连接空闲而断开。
    """
    import time as _time
    interval = interval if interval is not None else settings.sse_heartbeat_interval

    queue: "asyncio.Queue" = asyncio.Queue()
    done = asyncio.Event()

    async def producer():
        try:
            async for item in stream:
                await queue.put(item)
        except Exception as exc:  # 透传上游异常
            await queue.put(exc)
        finally:
            queue.put_nowait(_STREAM_END)
            done.set()

    async def consumer():
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat", "ts": int(_time.time())}
                continue
            if item is _STREAM_END:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    producer_task = asyncio.create_task(producer())
    try:
        async for evt in consumer():
            yield evt
    finally:
        producer_task.cancel()
        await stream.aclose()


async def _stream_response(message: str, session_id: str):
    """生成流式响应"""
    try:
        # 包装心跳：长间隙自动产出 heartbeat 事件
        inner = await agent.process_message(
            user_message=message,
            session_id=session_id,
            stream=True,
        )
        async for chunk in _with_heartbeat(inner):
            # 转换为SSE格式
            data = json.dumps(chunk, ensure_ascii=False)
            yield f"data: {data}\n\n"

        # 自动生成会话标题（仅默认标题 + 恰好 1 条用户消息），推送给前端
        new_title = await maybe_generate_title(session_id)
        if new_title:
            title_data = json.dumps({"type": "title", "title": new_title}, ensure_ascii=False)
            yield f"data: {title_data}\n\n"

        yield "data: [DONE]\n\n"
        
    except Exception as e:
        logger.error(f"流式响应生成失败: {str(e)}")
        error_data = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
        yield f"data: {error_data}\n\n"


@router.post("/confirm")
async def confirm_tool_execution(request: ConfirmRequest):
    """
    权限审批确认接口

    前端在内嵌审批卡上选择 once/always/reject 并（如需要）输入 sudo 密码后调用。
    reply 通过后可流式返回执行结果与模型总结。

    Args:
        request: 审批确认请求

    Returns:
        执行结果（stream=True 时返回 SSE 流）
    """
    try:
        if request.reply not in ("once", "always", "reject"):
            raise HTTPException(status_code=400, detail="reply 必须是 once/always/reject")

        result = await agent.confirm_permission(
            session_id=request.session_id,
            request_id=request.request_id,
            reply=request.reply,
            password=request.password,
            stream=request.stream,
        )

        if request.stream:
            # 流式响应（async generator）
            return StreamingResponse(
                _confirm_stream_response(result),
                media_type="text/event-stream",
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"确认处理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _confirm_stream_response(generator):
    """将权限确认的流式总结转换为SSE格式"""
    try:
        async for chunk in generator:
            data = json.dumps(chunk, ensure_ascii=False)
            yield f"data: {data}\n\n"

        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.error(f"确认流式响应生成失败: {str(e)}")
        error_data = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
        yield f"data: {error_data}\n\n"


@router.delete("/conversation/{session_id}")
async def clear_conversation(session_id: str):
    """
    清除对话历史
    
    Args:
        session_id: 会话ID
        
    Returns:
        操作结果
    """
    try:
        agent.clear_conversation(session_id)
        # 同步清理 DB 中的消息行（FTS 由 DELETE 触发器自动清理），避免刷新后旧消息复现
        from ..database import SessionLocal
        from ..models.audit import Conversation, ConversationMessage
        db = SessionLocal()
        try:
            db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == session_id
            ).delete()
            conv = db.query(Conversation).filter(Conversation.id == session_id).first()
            if conv:
                conv.updated_at = datetime.now()
            db.commit()
        finally:
            db.close()
        return {"success": True, "message": "对话历史已清除"}

    except Exception as e:
        logger.error(f"清除对话失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


class CreateConversationRequest(BaseModel):
    """创建对话请求"""
    title: Optional[str] = "新对话"


class RenameConversationRequest(BaseModel):
    """重命名对话请求"""
    title: str


@router.get("/conversations")
async def list_conversations():
    """获取对话列表"""
    try:
        db = SessionLocal()
        try:
            conversations = db.query(Conversation).filter(
                Conversation.is_active == True
            ).order_by(Conversation.updated_at.desc()).all()

            # 一次性聚合 token 用量、消息数与最后一条消息（避免 N+1）
            agg_rows = db.query(
                ConversationMessage.conversation_id,
                func.count(ConversationMessage.id).label("message_count"),
                func.coalesce(func.sum(ConversationMessage.prompt_tokens), 0).label("prompt_total"),
                func.coalesce(func.sum(ConversationMessage.completion_tokens), 0).label("completion_total"),
                func.max(ConversationMessage.created_at).label("last_created_at"),
            ).filter(
                ConversationMessage.conversation_id.in_([c.id for c in conversations])
            ).group_by(ConversationMessage.conversation_id).all()

            agg = {r.conversation_id: r for r in agg_rows}

            # 取每个会话最后一条消息的 content（按 created_at 倒序窗口函数取第 1 行；id 是随机 UUID 不可用）
            if conversations:
                ranked = db.query(
                    ConversationMessage.conversation_id,
                    ConversationMessage.content,
                    func.row_number().over(
                        partition_by=ConversationMessage.conversation_id,
                        order_by=ConversationMessage.created_at.desc(),
                    ).label("rn"),
                ).filter(
                    ConversationMessage.conversation_id.in_([c.id for c in conversations])
                ).subquery()
                last_content_rows = db.query(
                    ranked.c.conversation_id, ranked.c.content
                ).filter(ranked.c.rn == 1).all()
                last_content = {r[0]: r[1] for r in last_content_rows}
            else:
                last_content = {}

            result = []
            for conv in conversations:
                a = agg.get(conv.id)
                result.append({
                    **conv.to_dict(),
                    "last_message": (last_content.get(conv.id) or "")[:50] or None,
                    "message_count": a.message_count if a else 0,
                    "prompt_tokens": int(a.prompt_total or 0) if a else 0,
                    "completion_tokens": int(a.completion_total or 0) if a else 0,
                    "total_tokens": int((a.prompt_total or 0) + (a.completion_total or 0)) if a else 0,
                })

            return {"success": True, "data": result}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"获取对话列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations")
async def create_conversation(request: CreateConversationRequest):
    """创建新对话"""
    try:
        db = SessionLocal()
        try:
            conv = Conversation(title=request.title or "新对话")
            db.add(conv)
            db.commit()
            db.refresh(conv)
            
            return {"success": True, "data": conv.to_dict()}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"创建对话失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, request: RenameConversationRequest):
    """重命名对话"""
    try:
        db = SessionLocal()
        try:
            conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                raise HTTPException(status_code=404, detail="对话不存在")
            
            conv.title = request.title
            db.commit()
            
            return {"success": True, "data": conv.to_dict()}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重命名对话失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """删除对话"""
    try:
        db = SessionLocal()
        try:
            conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                raise HTTPException(status_code=404, detail="对话不存在")
            
            conv.is_active = False
            db.commit()
            
            # 清理消息记录（FTS 由 conversation_fts_delete 触发器自动清理）
            db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == conversation_id
            ).delete(synchronize_session=False)
            db.commit()
            
            # 同时清除Agent内存中的对话历史
            agent.clear_conversation(conversation_id)
            
            return {"success": True, "message": "对话已删除"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除对话失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str):
    """获取对话消息列表"""
    try:
        db = SessionLocal()
        try:
            messages = db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == conversation_id
            ).order_by(ConversationMessage.created_at.asc()).all()
            
            return {"success": True, "data": [m.to_dict() for m in messages]}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"获取对话消息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trace/{trace_id}")
async def get_trace(trace_id: str):
    """
    获取思维链追踪
    
    Args:
        trace_id: 追踪ID
        
    Returns:
        追踪信息
    """
    try:
        trace = agent.get_trace(trace_id)
        return trace
        
    except Exception as e:
        logger.error(f"获取追踪失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

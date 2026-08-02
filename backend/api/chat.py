# -*- coding: utf-8 -*-
"""
对话API接口
处理用户与Agent的对话
"""

import json
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.agent import agent
from ..core.chain_of_thought import cot_manager
from ..database import SessionLocal
from ..models.audit import Conversation, ConversationMessage

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    """对话请求"""
    message: str
    session_id: Optional[str] = None
    stream: bool = False


class ConfirmRequest(BaseModel):
    """确认请求"""
    session_id: str
    trace_id: str
    tool_name: str
    tool_params: Dict[str, Any]
    tool_call_id: str
    confirmed: bool


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
            return result
            
    except Exception as e:
        logger.error(f"对话处理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _stream_response(message: str, session_id: str):
    """生成流式响应"""
    try:
        async for chunk in await agent.process_message(
            user_message=message,
            session_id=session_id,
            stream=True,
        ):
            # 转换为SSE格式
            data = json.dumps(chunk, ensure_ascii=False)
            yield f"data: {data}\n\n"
        
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        logger.error(f"流式响应生成失败: {str(e)}")
        error_data = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
        yield f"data: {error_data}\n\n"


@router.post("/confirm")
async def confirm_tool_execution(request: ConfirmRequest):
    """
    确认工具执行接口
    
    Args:
        request: 确认请求
        
    Returns:
        执行结果
    """
    try:
        result = await agent.confirm_tool_execution(
            session_id=request.session_id,
            trace_id=request.trace_id,
            tool_name=request.tool_name,
            tool_params=request.tool_params,
            tool_call_id=request.tool_call_id,
            confirmed=request.confirmed,
        )
        return result
        
    except Exception as e:
        logger.error(f"确认处理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


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
            
            result = []
            for conv in conversations:
                # 获取最后一条消息
                last_msg = db.query(ConversationMessage).filter(
                    ConversationMessage.conversation_id == conv.id
                ).order_by(ConversationMessage.created_at.desc()).first()
                
                result.append({
                    **conv.to_dict(),
                    "last_message": last_msg.content[:50] if last_msg else None,
                    "message_count": db.query(ConversationMessage).filter(
                        ConversationMessage.conversation_id == conv.id
                    ).count(),
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

# -*- coding: utf-8 -*-
"""
会话标题自动生成
仅当标题仍为默认「新对话」且该会话恰好有 1 条用户消息时，
用 LLM 生成 ≤50 字符、与用户消息同语言的新标题，并落库。
"""

import logging
from typing import Optional

from ..database import SessionLocal
from ..models.audit import Conversation, ConversationMessage

logger = logging.getLogger(__name__)

TITLE_SYSTEM_PROMPT = (
    "你是一个会话标题生成器。为下面的用户提问生成一个简洁的对话标题。"
    "要求：不超过50个字符；与用户提问使用同一种语言；只用一句话；"
    "不要使用引号、冒号或句号结尾；不要描述任务本身。"
)


async def generate_title(llm_client, user_message: str) -> str:
    """
    调用 LLM 生成会话标题

    Args:
        llm_client: LLM 客户端
        user_message: 用户消息内容

    Returns:
        str: 生成的标题（失败返回空字符串）
    """
    try:
        resp = await llm_client.client.chat.completions.create(
            model=llm_client.model,
            messages=[
                {"role": "system", "content": TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=40,
        )
        title = (resp.choices[0].message.content or "").strip()
        # 去除可能包裹的引号
        title = title.strip('"').strip("'").strip()
        return title[:50]
    except Exception as e:
        logger.warning(f"标题生成失败: {e}")
        return ""


async def maybe_generate_title(session_id: str) -> Optional[str]:
    """
    满足条件时自动生成会话标题并落库

    Args:
        session_id: 会话ID

    Returns:
        Optional[str]: 新标题；条件不满足或失败返回 None
    """
    try:
        db = SessionLocal()
        try:
            conv = db.query(Conversation).filter(Conversation.id == session_id).first()
            if not conv:
                return None
            # 仅当仍为默认标题
            if (conv.title or "") != "新对话":
                return None

            user_msgs = db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == session_id,
                ConversationMessage.role == "user",
            ).all()
            # 仅当恰好 1 条用户消息
            if len(user_msgs) != 1:
                return None

            user_message = (user_msgs[0].content or "").strip()
            if not user_message:
                return None

            from ..core.agent import agent
            title = await generate_title(agent.llm_client, user_message)
            if not title:
                return None

            conv.title = title
            db.commit()
            logger.info(f"会话 {session_id} 自动生成标题: {title}")
            return title
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"自动生成标题失败: {e}")
        return None
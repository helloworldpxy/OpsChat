# -*- coding: utf-8 -*-
"""
大模型调用客户端
支持OpenAI兼容API，适配多种国产大模型
"""

import asyncio
import json
import logging
from typing import Dict, Any, List, Optional, AsyncGenerator
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from ..config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """
    大模型调用客户端
    支持OpenAI兼容API
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        """
        初始化LLM客户端
        
        Args:
            api_key: API密钥
            base_url: API基础URL
            model: 模型名称
        """
        self.api_key = api_key or settings.llm_api_key
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens
        
        # 创建异步客户端
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        
        logger.info(f"LLM客户端初始化完成: {self.base_url} - {self.model}")
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> Any:
        """
        发送对话请求
        
        Args:
            messages: 对话消息列表
            tools: 可用工具列表
            stream: 是否流式返回
            
        Returns:
            对话响应
        """
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            
            if stream:
                return self._stream_chat(**kwargs)
            else:
                return await self._normal_chat(**kwargs)
                
        except Exception as e:
            logger.error(f"LLM调用失败: {str(e)}")
            raise
    
    @staticmethod
    def _is_retryable_error(e: Exception) -> bool:
        """判断是否值得重试：网络错误 / 超时 / 5xx / 429（限流）。4xx 参数类错误不重试"""
        msg = str(e).lower()
        # 明确不可重试的客户端错误（密钥/参数/内容安全/上下文超长）
        non_retryable = (
            "authentication" in msg or "invalid api key" in msg or "401" in msg
            or "invalid_request_error" in msg or "400" in msg or "401 " in msg
            or "permission denied" in msg or "403" in msg
            or "not found" in msg or "404" in msg
            or "context_length" in msg or "maximum context" in msg or "token limit" in msg
            or "content_filter" in msg or "content policy" in msg
        )
        if non_retryable:
            return False
        # 429 / 5xx / 连接类错误 → 可重试
        retryable = (
            "429" in msg or "rate limit" in msg or "too many requests" in msg
            or "500" in msg or "502" in msg or "503" in msg or "504" in msg
            or "timeout" in msg or "timed out" in msg
            or "connection" in msg or "connect" in msg
            or "remote protocol" in msg or "reset" in msg
            or "temporarily" in msg or "unavailable" in msg
            or "overloaded" in msg or "server error" in msg or "internal server" in msg
            or "capacity" in msg
        )
        return retryable

    async def _normal_chat(self, **kwargs) -> Dict[str, Any]:
        """普通对话请求（带指数退避重试，仅对可重试错误）"""
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response: ChatCompletion = await self.client.chat.completions.create(**kwargs)
                
                message = response.choices[0].message
                
                usage = None
                if response.usage is not None:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }
                
                result = {
                    "content": message.content,
                    "role": message.role,
                    "finish_reason": response.choices[0].finish_reason,
                    "usage": usage,
                }
                
                # 处理工具调用
                if message.tool_calls:
                    result["tool_calls"] = []
                    for tool_call in message.tool_calls:
                        result["tool_calls"].append({
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            }
                        })
                
                return result
                
            except Exception as e:
                last_error = e
                # 4xx 参数/认证类错误直接抛出，不浪费重试
                if not self._is_retryable_error(e):
                    raise
                if attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(f"LLM调用失败（第{attempt+1}次），{wait}秒后重试: {e}")
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"LLM调用重试{max_retries}次后全部失败: {e}")
                    raise last_error
    
    async def _stream_chat(self, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        """流式对话请求
        请求 stream_options.include_usage 以获取 provider 权威 token 用量；
        若 provider 不支持该参数，自动回退重试（不带该参数）
        """
        kwargs["stream"] = True
        usage = None

        async def _create():
            try:
                kw = {**kwargs, "stream_options": {"include_usage": True}}
                return await self.client.chat.completions.create(**kw)
            except Exception as e:
                msg = str(e)
                if "stream_options" in msg or "include_usage" in msg or "unknown parameter" in msg.lower():
                    logger.warning(f"stream_options 不被支持，回退重试: {e}")
                    return await self.client.chat.completions.create(**kwargs)
                raise

        stream = await _create()
        tool_calls_buffer = {}
        finish_pending = None
        
        async for chunk in stream:
            # 末块（choices 为空）携带 usage（include_usage 开启时）
            if not chunk.choices:
                if chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }
                continue
            
            choice = chunk.choices[0]
            delta = choice.delta
            
            # 处理内容
            if delta.content:
                yield {
                    "type": "content",
                    "content": delta.content,
                    "finish_reason": choice.finish_reason,
                }
            
            # 处理工具调用
            if delta.tool_calls:
                for tool_call in delta.tool_calls:
                    index = tool_call.index
                    
                    if index not in tool_calls_buffer:
                        tool_calls_buffer[index] = {
                            "id": tool_call.id or "",
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name if tool_call.function and tool_call.function.name else "",
                                "arguments": tool_call.function.arguments if tool_call.function and tool_call.function.arguments else "",
                            }
                        }
                    else:
                        # 累积工具调用信息
                        if tool_call.id:
                            tool_calls_buffer[index]["id"] = tool_call.id
                        if tool_call.function:
                            if tool_call.function.name:
                                tool_calls_buffer[index]["function"]["name"] += tool_call.function.name
                            if tool_call.function.arguments:
                                tool_calls_buffer[index]["function"]["arguments"] += tool_call.function.arguments
            
            # 处理结束：缓冲 finish 事件，等流结束后（usage 已到达）再发出
            if choice.finish_reason:
                finish_pending = choice.finish_reason
        
        # 流结束：此时 usage 已捕获（include_usage 开启时），发出 finish 事件
        if finish_pending:
            # 发送累积的工具调用
            if tool_calls_buffer:
                yield {
                    "type": "tool_calls",
                    "tool_calls": list(tool_calls_buffer.values()),
                    "finish_reason": finish_pending,
                }
            yield {
                "type": "finish",
                "finish_reason": finish_pending,
                "usage": usage,
            }
    
    def update_config(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        """
        更新配置
        
        Args:
            api_key: API密钥
            base_url: API基础URL
            model: 模型名称
        """
        if api_key:
            self.api_key = api_key
        if base_url:
            self.base_url = base_url
        if model:
            self.model = model
        
        # 重新创建客户端
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        
        logger.info(f"LLM客户端配置已更新: {self.base_url} - {self.model}")
    
    async def test_connection(self) -> Dict[str, Any]:
        """
        测试API连接
        
        Returns:
            测试结果
        """
        try:
            response = await self._normal_chat(
                model=self.model,
                messages=[{"role": "user", "content": "你好，请回复OK"}],
                max_tokens=10,
            )
            
            return {
                "success": True,
                "message": "API连接成功",
                "model": self.model,
                "response": response.get("content", ""),
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"API连接失败: {str(e)}",
                "model": self.model,
            }

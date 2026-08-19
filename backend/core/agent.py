# -*- coding: utf-8 -*-
"""
Agent调度器
核心调度逻辑，协调各模块工作
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime

from ..config import settings
from ..mcp.registry import tool_registry
from ..security.guardrail import SecurityGuardrail, SecurityDecision
from ..security.permission import permission_service, PermissionDeniedError
from .llm_client import LLMClient
from .chain_of_thought import cot_manager
from .root_cause import root_cause_analyzer
from ..utils.text import truncate_json
from .token_counter import count_tokens, count_json_tokens, count_message_tokens, estimate_tokens

logger = logging.getLogger(__name__)


# System Prompt
SYSTEM_PROMPT = """你是一个专业的智能运维助手，部署于通用 Linux 操作系统上（原生支持 LoongArch 等国产架构）。你的职责是帮助运维人员管理和维护操作系统。

## 你的能力
1. **系统状态监控**：查看CPU、内存、磁盘、网络使用情况
2. **进程管理**：查看进程列表、进程详情、终止进程
3. **服务管理**：查看服务状态、启动/停止/重启服务
4. **日志分析**：查看系统日志，按优先级和服务过滤
5. **网络诊断**：Ping测试、查看网络连接状态、端口占用查询
6. **配置安全**：检测关键配置文件是否被意外修改（配置漂移检测）
7. **智能诊断**：一键系统健康诊断，自动检测异常并分析根因，给出修复建议

## 工作原则
1. **安全第一**：绝不执行可能损害系统的操作，如删除系统文件、修改关键配置
2. **确认优先**：对于任何修改性操作（如终止进程、重启服务、删除文件、修改权限），必须先向用户确认
3. **最小权限**：只执行必要的操作，不越权
4. **透明沟通**：清晰告知用户你将要执行的操作及其影响
5. **异常上报**：发现异常情况及时告知用户，并主动分析原因

## 智能诊断能力
当用户要求"系统诊断"、"健康检查"、"检查系统异常"等时，你应该：
1. 调用 diagnose_system 工具执行全面诊断
2. 根据诊断报告，用通俗易懂的语言向用户解释每个异常
3. 按严重程度排序，优先说明最紧急的问题
4. 给出具体的修复命令或操作建议

## 根因分析方法论
分析系统问题时，你应该遵循以下逻辑链：
- CPU高 → 哪个进程导致 → 该进程是否正常 → 是否需要重启/优化
- 内存高 → 是否有内存泄漏 → 哪个进程占用最多 → 是否需要重启释放
- 磁盘满 → 哪个目录占用大 → 是否有日志/临时文件堆积 → 清理建议
- 服务异常 → 查看服务日志 → 分析错误原因 → 重启或配置修复

## 响应格式
- 使用中文回复
- 使用Markdown格式化输出（表格、列表、代码块）
- 对于复杂操作，分步骤说明
- 对于风险操作，明确标注并请求确认
- 诊断报告使用表格展示异常项

## 工具使用规则
1. 优先使用只读工具获取信息
2. 修改类操作需要用户明确确认
3. 不要尝试执行危险命令
4. 如果工具调用失败，分析原因并给出建议
5. 配置漂移检测工具可以用于建立基线和对比检查

请始终遵守以上原则，为用户提供安全、可靠的运维支持。"""


class Agent:
    """
    Agent调度器
    协调LLM、MCP工具、安全护栏的工作
    """
    
    MAX_TOOL_ITERATIONS = 5  # 最大工具调用迭代次数
    
    def __init__(self):
        """初始化Agent"""
        self.llm_client = LLMClient()
        self.security_guardrail = SecurityGuardrail({
            "enable_input_filter": settings.enable_input_sanitizer,
            "enable_output_validation": settings.enable_output_validator,
            "enable_sandbox": settings.enable_sandbox,
        })
        
        # 初始化工具注册中心
        tool_registry.initialize()
        
        # 对话历史
        self.conversations: Dict[str, List[Dict[str, str]]] = {}
        # 会话最后活动时间
        self._session_activity: Dict[str, datetime] = {}
        
        logger.info("Agent调度器初始化完成")
    
    def _get_system_message(self) -> Dict[str, str]:
        """获取系统消息"""
        return {"role": "system", "content": SYSTEM_PROMPT}
    
    def _get_conversation_history(self, session_id: str) -> List[Dict[str, str]]:
        """获取对话历史"""
        if session_id not in self.conversations:
            self.conversations[session_id] = []
        return self.conversations[session_id]
    
    def _add_to_history(self, session_id: str, message: Dict[str, str]):
        """添加消息到对话历史"""
        if session_id not in self.conversations:
            self.conversations[session_id] = []
        
        self.conversations[session_id].append(message)
        
        # 限制历史长度
        max_history = settings.max_conversation_history
        if len(self.conversations[session_id]) > max_history:
            self.conversations[session_id] = self.conversations[session_id][-max_history:]
    
    def clear_conversation(self, session_id: str):
        """清除对话历史"""
        if session_id in self.conversations:
            del self.conversations[session_id]
        self._session_activity.pop(session_id, None)
    
    def cleanup_expired_sessions(self):
        """清理过期会话，防止内存泄漏"""
        timeout = settings.session_timeout  # 秒
        now = datetime.now()
        expired = [
            sid for sid, last in self._session_activity.items()
            if (now - last).total_seconds() > timeout
        ]
        for sid in expired:
            self.conversations.pop(sid, None)
            self._session_activity.pop(sid, None)
        if expired:
            logger.info(f"清理了 {len(expired)} 个过期会话")
    
    async def process_message(
        self,
        user_message: str,
        session_id: str,
        stream: bool = False,
    ) -> Any:
        """
        处理用户消息
        
        Args:
            user_message: 用户消息
            session_id: 会话ID
            stream: 是否流式返回
            
        Returns:
            处理结果
        """
        # 创建思维链追踪
        trace_id = cot_manager.create_trace()
        await cot_manager.log_user_input(trace_id, user_message)
        
        # 更新会话活动时间
        self._session_activity[session_id] = datetime.now()
        # 清理过期会话
        self.cleanup_expired_sessions()
        
        # 第一层安全检查：输入过滤
        if settings.enable_security_guardrail:
            check_result = self.security_guardrail.check_input(user_message)
            if not check_result.is_allowed:
                await cot_manager.log_safety_check(
                    trace_id=trace_id,
                    risk_level=check_result.risk_level,
                    rules_triggered=["input_injection_detected"],
                    decision="REJECT",
                )
                return {
                    "success": False,
                    "message": check_result.message,
                    "trace_id": trace_id,
                }
        
        # 添加用户消息到历史
        await self._add_user_message(session_id, user_message)
        
        # 构建消息列表
        messages = self._build_messages(session_id)
        
        # 获取可用工具
        tools = tool_registry.get_llm_tools()
        
        if stream:
            return self._process_stream(messages, tools, session_id, trace_id)
        else:
            return await self._process_normal(messages, tools, session_id, trace_id)
    
    async def _add_user_message(self, session_id: str, content: str):
        """添加用户消息"""
        await self._add_message(session_id, "user", content, prompt_tokens=count_tokens(content))

    async def _add_assistant_message(
        self,
        session_id: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ):
        """添加助手消息"""
        await self._add_message(
            session_id,
            "assistant",
            content,
            tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def _add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ):
        """添加消息到历史"""
        message = {"role": role, "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        await self._add_message_to_history(
            session_id,
            message,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def _add_message_to_history(
        self,
        session_id: str,
        message: Dict[str, Any],
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ):
        """添加消息到历史（内存 + aiosqlite 异步持久化）"""
        if session_id not in self.conversations:
            self.conversations[session_id] = []
        self.conversations[session_id].append(message)
        
        # 异步持久化到数据库（不阻塞事件循环）
        try:
            from sqlalchemy.ext.asyncio import AsyncSession
            from sqlalchemy import select
            from ..database import async_engine
            from ..models.audit import Conversation, ConversationMessage
            
            async with AsyncSession(async_engine) as db:
                # 确保对话记录存在
                result = await db.execute(select(Conversation).where(Conversation.id == session_id))
                conv = result.scalar_one_or_none()
                if not conv:
                    conv = Conversation(id=session_id, title="新对话")
                    db.add(conv)
                    await db.flush()
                
                # 保存消息
                role = message.get("role", "unknown")
                content = message.get("content", "")
                tool_calls = message.get("tool_calls")
                
                msg = ConversationMessage(
                    conversation_id=session_id,
                    role=role,
                    content=content,
                    message_type="tool_call" if tool_calls else "text",
                    tool_calls=tool_calls,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                db.add(msg)
                await db.commit()
        except Exception as e:
            logger.warning(f"持久化消息失败: {e}")
    
    def _message_tokens(self, message: Dict[str, Any]) -> int:
        """精确计数单条消息的 token 占用（content + tool_calls）"""
        return count_message_tokens(message)

    def _trim_history_by_budget(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        按 token 预算裁剪历史（保留最新消息）
        - 从最旧开始累积 token，超出预算处切断
        - 防止切断后残留孤立 tool 消息（其前置 assistant(tool_calls) 已被裁掉）
        """
        if not history:
            return history

        budget = int(settings.context_window * settings.history_token_budget_ratio)
        if budget <= 0:
            # 预算无效时退回条数裁剪
            return history[-settings.max_conversation_history:]

        # 记录每个 assistant(tool_calls) 消息的索引（tool 消息的锚点）
        anchors = {i for i, m in enumerate(history)
                   if m.get("role") == "assistant" and m.get("tool_calls")}

        def _nearest_anchor(j: int) -> Optional[int]:
            for k in range(j - 1, -1, -1):
                if k in anchors:
                    return k
            return None

        # 从最新往前累积，超出预算即切断
        exceeded = False
        keep_idx = len(history)
        tokens = 0
        for i in range(len(history) - 1, -1, -1):
            t = self._message_tokens(history[i])
            if tokens + t > budget:
                keep_idx = i + 1
                exceeded = True
                break
            tokens += t

        # 预算内全部保留
        if not exceeded:
            return history

        # 丢弃被切断成孤儿的 tool 消息
        while keep_idx < len(history):
            m = history[keep_idx]
            if m.get("role") != "tool":
                break
            anchor = _nearest_anchor(keep_idx)
            if anchor is not None and anchor < keep_idx:
                keep_idx += 1
            else:
                break

        return history[keep_idx:]

    def _build_messages(self, session_id: str) -> List[Dict[str, str]]:
        """构建消息列表（含 token 预算裁剪）"""
        messages = [self._get_system_message()]
        
        # 添加对话历史（token 预算裁剪）
        history = self.conversations.get(session_id, [])
        messages.extend(self._trim_history_by_budget(history))
        
        return messages

    def _estimate_context(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """估算上下文占用（ContextMeter：system / tools / messages 细分）
        使用真实 DeepSeek V3 tokenizer 精确计数
        返回值与 limit 一起供前端渲染占用环
        """
        system_tokens = sum(
            count_tokens(m.get("content", "")) for m in messages if m.get("role") == "system"
        )
        tools_tokens = count_json_tokens(tools or [])
        messages_tokens = sum(
            count_message_tokens(m) for m in messages if m.get("role") != "system"
        )
        total = system_tokens + tools_tokens + messages_tokens
        return {
            "system": system_tokens,
            "tools": tools_tokens,
            "messages": messages_tokens,
            "total": total,
            "limit": settings.context_window,
            "percent": round(min(total / settings.context_window, 1.0) * 100, 1) if settings.context_window else 0,
        }

    def _build_finish_event(
        self,
        trace_id: str,
        start_time: float,
        metrics: Dict[str, Any],
        messages: List[Dict[str, str]],
        api_usage: Optional[Dict[str, int]] = None,
        completion_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """构造带指标的 finish 事件（TTFT / tokens每秒 / 耗时 / token 数）
        token 数优先使用 provider 返回的真实 usage；无则用 DeepSeek V3 tokenizer 精确计数
        """
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        prompt_tokens, completion_tokens = self._resolve_token_usage(
            api_usage, messages, completion_text if completion_text is not None else metrics.get("completion_text", "")
        )

        event = {
            "type": "finish",
            "trace_id": trace_id,
            "model": settings.llm_model,
            "elapsed_ms": elapsed_ms,
            "ttft_ms": metrics.get("ttft_ms"),
            "tokens_per_sec": round(completion_tokens / max(elapsed_ms / 1000, 0.001), 1) if completion_tokens else 0,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        return event

    def _resolve_token_usage(
        self,
        api_usage: Optional[Dict[str, int]],
        messages: List[Dict[str, str]],
        completion_text: str,
    ) -> tuple:
        """解析 token 用量：provider usage 两项齐备则优先使用，否则整体回退本地精确计数"""
        if (api_usage
                and api_usage.get("prompt_tokens") is not None
                and api_usage.get("completion_tokens") is not None):
            try:
                return int(api_usage["prompt_tokens"]), int(api_usage["completion_tokens"])
            except (TypeError, ValueError):
                pass
        return count_json_tokens(messages), count_tokens(completion_text)
    
    async def _process_normal(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        session_id: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        """普通模式处理"""
        try:
            exceeded = True
            for iteration in range(self.MAX_TOOL_ITERATIONS):
                # 调用LLM
                await cot_manager.log_llm_reasoning(
                    trace_id=trace_id,
                    model=settings.llm_model,
                    thought="正在分析用户请求...",
                )
                
                response = await self.llm_client.chat(messages=messages, tools=tools)
                api_usage = response.get("usage")
                
                # 处理工具调用
                if response.get("tool_calls"):
                    result = await self._handle_tool_calls(
                        response=response,
                        session_id=session_id,
                        trace_id=trace_id,
                        messages=messages,
                        tools=tools,
                    )
                    # 如果需要用户确认，直接返回
                    if result.get("type") in ("confirmation_required", "permission_required"):
                        exceeded = False
                        return result
                    # 工具执行完成后重建消息继续
                    messages = self._build_messages(session_id)
                    continue
                
                # 普通响应
                content = response.get("content", "")
                
                # LLM输出内容安全校验
                if settings.enable_output_validator and content:
                    llm_check = self.security_guardrail.output_validator.validate_llm_output(content)
                    if not llm_check.is_valid:
                        await cot_manager.log_safety_check(
                            trace_id=trace_id,
                            risk_level=llm_check.risk_level,
                            rules_triggered=["llm_output_dangerous_command"],
                            decision="REJECT",
                        )
                        content = f"[安全拦截] {llm_check.message}\n\n原始回复中包含高危命令，已被安全护栏拦截。请重新描述您的需求。"
                
                prompt_tokens, completion_tokens = self._resolve_token_usage(
                    api_usage, messages, content)
                await self._add_assistant_message(
                    session_id,
                    content,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                await cot_manager.log_response(trace_id, content)
                exceeded = False
                
                return {
                    "success": True,
                    "message": content,
                    "trace_id": trace_id,
                    "type": "text",
                }
            
            if exceeded:
                # 超过最大迭代次数
                error_msg = f"工具调用次数超过限制（{self.MAX_TOOL_ITERATIONS}次），已自动终止"
                logger.warning(error_msg)
                await self._add_assistant_message(session_id, error_msg)
                await cot_manager.log_response(trace_id, error_msg)
                return {
                    "success": False,
                    "message": error_msg,
                    "trace_id": trace_id,
                }
                
        except Exception as e:
            logger.error(f"处理消息失败: {str(e)}")
            return {
                "success": False,
                "message": f"处理消息时发生错误: {str(e)}",
                "trace_id": trace_id,
            }
    
    async def _process_stream(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        session_id: str,
        trace_id: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式模式处理
        单 LLM 调用循环：每轮只调用一次模型，工具执行结果由外层循环重新构建
        消息后继续下一轮，不再在工具处理函数内部二次调用模型
        """
        start_time = time.monotonic()
        # Turn 级指标：首 token 时间、累计生成文本（估算 token 用）
        metrics = {"ttft_ms": None, "completion_text": ""}
        try:
            exceeded = True
            for iteration in range(self.MAX_TOOL_ITERATIONS):
                await cot_manager.log_llm_reasoning(
                    trace_id=trace_id,
                    model=settings.llm_model,
                    thought="正在分析用户请求...",
                )

                # ContextMeter：每轮 LLM 调用前推送上下文占用估算
                yield {
                    "type": "context_usage",
                    "trace_id": trace_id,
                    **self._estimate_context(messages, tools),
                }

                full_content = ""
                tool_calls = None
                api_usage = None

                async for chunk in await self.llm_client.chat(messages=messages, tools=tools, stream=True):
                    if metrics["ttft_ms"] is None:
                        metrics["ttft_ms"] = int((time.monotonic() - start_time) * 1000)
                    if chunk["type"] == "content":
                        full_content += chunk["content"]
                        metrics["completion_text"] += chunk["content"]
                        yield {
                            "type": "content",
                            "content": chunk["content"],
                            "trace_id": trace_id,
                        }
                    elif chunk["type"] == "tool_calls":
                        tool_calls = chunk["tool_calls"]
                        for tc in tool_calls:
                            metrics["completion_text"] += tc.get("function", {}).get("arguments", "")
                        yield {
                            "type": "tool_calls",
                            "tool_calls": tool_calls,
                            "trace_id": trace_id,
                        }
                    elif chunk["type"] == "finish":
                        api_usage = chunk.get("usage")
                        if tool_calls:
                            # 执行工具并挂载结果（不再在内部二次调用模型）
                            has_permission = False
                            async for result in self._handle_tool_calls_stream(
                                tool_calls=tool_calls,
                                full_content=full_content,
                                session_id=session_id,
                                trace_id=trace_id,
                                messages=messages,
                            ):
                                if result.get("type") == "permission_asked":
                                    has_permission = True
                                yield result

                            # 出现待用户审批的高危操作，停止当前流，等待 confirm 接口续跑
                            if has_permission:
                                return

                            # 重建消息列表，进入下一轮模型推理（支持多步工具链）
                            messages = self._build_messages(session_id)
                        else:
                            prompt_tokens, completion_tokens = self._resolve_token_usage(
                                api_usage, messages, full_content)
                            # 流式主路径输出安全校验（与普通路径一致，拦截高危命令）
                            validated = await self._validate_llm_content(full_content, trace_id)
                            if validated != full_content:
                                yield {
                                    "type": "content",
                                    "content": validated,
                                    "trace_id": trace_id,
                                }
                                full_content = validated
                            await self._add_assistant_message(
                                session_id,
                                full_content,
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                            )
                            await cot_manager.log_response(trace_id, full_content)
                            yield self._build_finish_event(
                                trace_id, start_time, metrics, messages, api_usage,
                                completion_text=full_content)
                            exceeded = False
                            return

                # 模型未产生工具调用则结束
                if not tool_calls:
                    exceeded = False
                    break

            if exceeded:
                error_msg = f"工具调用次数超过限制（{self.MAX_TOOL_ITERATIONS}次），已自动终止"
                logger.warning(error_msg)
                await self._add_assistant_message(session_id, error_msg)
                await cot_manager.log_response(trace_id, error_msg)
                yield {"type": "content", "content": error_msg, "trace_id": trace_id}
                yield {"type": "finish", "trace_id": trace_id, "elapsed_ms": int((time.monotonic() - start_time) * 1000)}

        except Exception as e:
            logger.error(f"流式处理失败: {str(e)}")
            yield {
                "type": "error",
                "message": f"处理消息时发生错误: {str(e)}",
                "trace_id": trace_id,
            }
    
    async def _handle_tool_calls(
        self,
        response: Dict[str, Any],
        session_id: str,
        trace_id: str,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """处理工具调用（非流式）"""
        tool_calls = response.get("tool_calls", [])
        tool_results = []

        # 保存助手消息（包含工具调用）
        await self._add_assistant_message(
            session_id,
            response.get("content", ""),
            tool_calls,
            prompt_tokens=count_json_tokens(messages),
        )

        # 执行每个工具调用
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            try:
                tool_args = json.loads(tool_call["function"]["arguments"] or "{}")
            except (json.JSONDecodeError, TypeError):
                # LLM 输出非法 JSON 参数：将该调用标记为失败结果，不中断整轮
                logger.warning(f"工具参数 JSON 解析失败: {tool_name}")
                await cot_manager.log_execution(
                    trace_id, tool_name,
                    {"success": False, "error": "工具参数不是合法 JSON"}, False,
                )
                tool_results.append({
                    "tool_call_id": tool_call["id"],
                    "role": "tool",
                    "content": truncate_json(
                        {"success": False, "error": "工具参数解析失败（非法 JSON）"},
                        settings.tool_result_max_chars,
                    ),
                })
                continue

            # 安全检查 + 权限审批
            approve = await self._check_and_approve_tool(
                tool_call=tool_call,
                tool_name=tool_name,
                tool_args=tool_args,
                session_id=session_id,
                trace_id=trace_id,
            )
            if approve["action"] != "execute":
                # 提交此前已执行的工具结果
                for tr in tool_results:
                    await self._add_message_to_history(session_id, tr)

                for evt in approve["events"]:
                    if evt["type"] == "tool_result":
                        # 规则拒绝：记录失败结果，继续处理下一个工具
                        tool_results.append({
                            "tool_call_id": tool_call["id"],
                            "role": "tool",
                            "content": truncate_json(evt["result"], settings.tool_result_max_chars),
                        })
                    elif evt["type"] == "permission_asked":
                        return {
                            "success": True,
                            "type": "permission_required",
                            "message": evt["message"],
                            "tool_name": tool_name,
                            "tool_params": tool_args,
                            "trace_id": trace_id,
                            "tool_call_id": tool_call["id"],
                            "request": evt["request"],
                        }
                    elif evt["type"] == "confirmation_required":
                        return {
                            "success": True,
                            "type": "confirmation_required",
                            "message": evt["message"],
                            "tool_name": tool_name,
                            "tool_params": tool_args,
                            "trace_id": trace_id,
                            "tool_call_id": tool_call["id"],
                        }
                continue

            # 执行工具
            await cot_manager.log_environment_perception(trace_id, tool_name, tool_args)

            result = await self._execute_tool(tool_name, tool_args)

            await cot_manager.log_execution(trace_id, tool_name, result, result.get("success", False))

            tool_results.append({
                "tool_call_id": tool_call["id"],
                "role": "tool",
                "content": truncate_json(result, settings.tool_result_max_chars),
            })

        # 添加工具结果到消息历史
        for tool_result in tool_results:
            await self._add_message_to_history(session_id, tool_result)

        # 返回工具调用结果，由外层循环继续处理
        return {
            "success": True,
            "type": "tool_result",
            "trace_id": trace_id,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
        }
    
    async def _handle_tool_calls_stream(
        self,
        tool_calls: List[Dict[str, Any]],
        full_content: str,
        session_id: str,
        trace_id: str,
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式处理工具调用
        仅负责执行工具并产出结果事件，不再内部调用模型生成总结
        （总结由外层 _process_stream 的下一轮循环完成）
        """
        tool_results = []

        # 保存助手消息（包含工具调用与模型思考内容）
        await self._add_assistant_message(
            session_id,
            full_content,
            tool_calls,
            prompt_tokens=count_json_tokens(messages) if messages else 0,
            completion_tokens=count_tokens(full_content) + count_json_tokens(tool_calls),
        )

        # 执行每个工具调用
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            try:
                tool_args = json.loads(tool_call["function"]["arguments"] or "{}")
            except (json.JSONDecodeError, TypeError):
                # LLM 输出非法 JSON 参数：产出失败结果事件，继续后续调用
                logger.warning(f"工具参数 JSON 解析失败: {tool_name}")
                tool_results.append({
                    "tool_call_id": tool_call["id"],
                    "role": "tool",
                    "content": truncate_json(
                        {"success": False, "error": "工具参数解析失败（非法 JSON）"},
                        settings.tool_result_max_chars,
                    ),
                })
                yield {
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "tool_call_id": tool_call["id"],
                    "result": {"success": False, "error": "工具参数解析失败（非法 JSON）"},
                    "trace_id": trace_id,
                }
                continue

            # 安全检查 + 权限审批
            approve = await self._check_and_approve_tool(
                tool_call=tool_call,
                tool_name=tool_name,
                tool_args=tool_args,
                session_id=session_id,
                trace_id=trace_id,
            )
            if approve["action"] != "execute":
                # 拒绝/挂起审批/退回旧确认，产出事件后终止本轮
                for evt in approve["events"]:
                    yield evt
                return

            # 执行工具
            result = await self._execute_tool(tool_name, tool_args)

            yield {
                "type": "tool_result",
                "tool_name": tool_name,
                "tool_call_id": tool_call["id"],
                "result": result,
                "trace_id": trace_id,
            }

            tool_results.append({
                "tool_call_id": tool_call["id"],
                "role": "tool",
                "content": truncate_json(result, settings.tool_result_max_chars),
            })

        # 添加工具结果到消息历史
        for tool_result in tool_results:
            await self._add_message_to_history(session_id, tool_result)

    def _ask_permission(
        self,
        session_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: str,
        trace_id: str,
        message: str,
    ) -> Dict[str, Any]:
        """
        通过权限引擎发起一次高危操作审批
        返回 {"type": "denied"/"asked"/"allowed"/"legacy", ...}
        - denied: 规则明确禁止
        - asked: 已挂起审批请求
        - allowed: 规则放行，可继续执行
        - legacy: 权限服务未启用，退回旧确认机制
        """
        if not settings.enable_permission_service:
            return {"type": "legacy"}

        tool_def = tool_registry.get_protocol().get_tool(tool_name)
        risk_level = tool_def.risk_level.value if tool_def else "medium"

        try:
            request = permission_service.ask(
                session_id=session_id,
                permission=f"tool:{tool_name}",
                patterns=[tool_name],
                metadata={
                    "message": message,
                    "tool_name": tool_name,
                    "tool_params": tool_args,
                    "risk_level": risk_level,
                },
                always=[tool_name],
                tool_name=tool_name,
                tool_params=tool_args,
                tool_call_id=tool_call_id,
                trace_id=trace_id,
                password_required=True,
            )
        except PermissionDeniedError as e:
            return {"type": "denied", "message": e.message}

        if request is None:
            return {"type": "allowed"}

        return {"type": "asked", "request": permission_service.to_dict(request)}

    async def _check_and_approve_tool(
        self,
        tool_call: Dict[str, Any],
        tool_name: str,
        tool_args: Dict[str, Any],
        session_id: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        """
        执行工具前的安全检查与权限审批
        返回 {"action": "execute"} 表示放行；
        否则返回 {"action": "stop", "events": [...]}，由调用方产出事件后终止本轮
        """
        need_confirm = False
        check_message = ""

        # 安全护栏检查
        if settings.enable_security_guardrail:
            check_result = self.security_guardrail.check_tool_call(tool_name, tool_args)

            await cot_manager.log_safety_check(
                trace_id=trace_id,
                risk_level=check_result.risk_level,
                rules_triggered=check_result.details.get("rules_triggered", []),
                decision=check_result.decision.value,
            )

            if check_result.decision == SecurityDecision.REJECT:
                return {
                    "action": "stop",
                    "events": [{
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": {"success": False, "error": check_result.message},
                        "trace_id": trace_id,
                    }],
                }

            if check_result.decision == SecurityDecision.REQUIRE_CONFIRMATION:
                need_confirm = True
                check_message = check_result.message

        # 第三层：执行沙箱检查（路径/环境限制，独立于安全护栏开关）
        if settings.enable_sandbox:
            exec_check = self.security_guardrail.check_execution(tool_name, tool_args)
            await cot_manager.log_safety_check(
                trace_id=trace_id,
                risk_level=exec_check.risk_level,
                rules_triggered=["sandbox_path_restriction"],
                decision=exec_check.decision.value,
            )
            if exec_check.decision == SecurityDecision.REJECT:
                return {
                    "action": "stop",
                    "events": [{
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": {"success": False, "error": exec_check.message},
                        "trace_id": trace_id,
                    }],
                }

        # 工具自身声明需审批或风险等级为高（即使安全护栏未拦截）
        if not need_confirm:
            tool_def = tool_registry.get_protocol().get_tool(tool_name)
            if tool_def and tool_def.requires_approval:
                need_confirm = True
                check_message = f"该操作需要用户确认：{tool_name}"
            elif tool_def and tool_def.risk_level.value in ("high", "critical"):
                need_confirm = True
                check_message = f"高风险操作需要用户确认：{tool_name}（风险等级 {tool_def.risk_level.value}）"

        if not need_confirm:
            return {"action": "execute"}

        # 发起权限审批
        perm = self._ask_permission(
            session_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call["id"],
            trace_id=trace_id,
            message=check_message,
        )

        if perm["type"] == "denied":
            return {
                "action": "stop",
                "events": [{
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "result": {"success": False, "error": perm["message"]},
                    "trace_id": trace_id,
                }],
            }

        if perm["type"] == "asked":
            return {
                "action": "stop",
                "events": [{
                    "type": "permission_asked",
                    "request": perm["request"],
                    "message": check_message,
                    "tool_name": tool_name,
                    "tool_params": tool_args,
                    "tool_call_id": tool_call["id"],
                    "trace_id": trace_id,
                }],
            }

        if perm["type"] == "legacy":
            # 权限服务禁用时退回旧确认机制
            return {
                "action": "stop",
                "events": [{
                    "type": "confirmation_required",
                    "message": check_message,
                    "tool_name": tool_name,
                    "tool_params": tool_args,
                    "trace_id": trace_id,
                    "tool_call_id": tool_call["id"],
                }],
            }

        # allowed：规则放行，继续执行
        return {"action": "execute"}
    
    async def _execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具"""
        try:
            protocol = tool_registry.get_protocol()
            from ..mcp.protocol import MCPRequest
            
            request = MCPRequest(
                tool_name=tool_name,
                parameters=parameters,
            )
            
            response = await protocol.execute_tool(request)
            
            return response.to_dict()
        except Exception as e:
            logger.error(f"工具执行失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
            }
    
    async def _validate_llm_content(self, content: str, trace_id: str) -> str:
        """LLM 输出安全校验，命中高危规则时替换为拦截提示"""
        if settings.enable_output_validator and content:
            llm_check = self.security_guardrail.output_validator.validate_llm_output(content)
            if not llm_check.is_valid:
                await cot_manager.log_safety_check(
                    trace_id=trace_id,
                    risk_level=llm_check.risk_level,
                    rules_triggered=["llm_output_dangerous_command"],
                    decision="REJECT",
                )
                return f"[安全拦截] {llm_check.message}\n\n原始回复中包含高危命令，已被安全护栏拦截。请重新描述您的需求。"
        return content

    async def _stream_summary(
        self,
        session_id: str,
        trace_id: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式生成最终总结
        不携带工具列表，避免模型在总结阶段再次发起工具调用
        """
        start_time = time.monotonic()
        messages = self._build_messages(session_id)
        metrics = {"ttft_ms": None, "completion_text": ""}

        yield {
            "type": "context_usage",
            "trace_id": trace_id,
            **self._estimate_context(messages, []),
        }

        full_content = ""
        api_usage = None
        async for chunk in await self.llm_client.chat(messages=messages, stream=True):
            if metrics["ttft_ms"] is None:
                metrics["ttft_ms"] = int((time.monotonic() - start_time) * 1000)
            if chunk["type"] == "content":
                full_content += chunk["content"]
                metrics["completion_text"] += chunk["content"]
                yield {
                    "type": "content",
                    "content": chunk["content"],
                    "trace_id": trace_id,
                }
            elif chunk["type"] == "finish":
                api_usage = chunk.get("usage")
                # 无工具可调用时模型可能仍输出 tool_calls，忽略仅保留文本
                if chunk.get("tool_calls"):
                    continue
                full_content = await self._validate_llm_content(full_content, trace_id)
                await self._add_assistant_message(
                    session_id,
                    full_content,
                    prompt_tokens=count_json_tokens(messages),
                    completion_tokens=count_tokens(full_content),
                )
                await cot_manager.log_response(trace_id, full_content)
                yield self._build_finish_event(trace_id, start_time, metrics, messages, api_usage)
                return

    async def confirm_permission(
        self,
        session_id: str,
        request_id: str,
        reply: str,
        password: Optional[str] = None,
        stream: bool = False,
    ) -> Any:
        """
        处理用户对权限审批请求的回复并继续执行
        - reply: once（仅本次允许）/ always（始终允许）/ reject（拒绝）
        - 批准后执行工具，并由模型生成总结（支持流式）
        """
        result = await asyncio.to_thread(
            permission_service.reply, request_id, reply, password, session_id
        )
        if result.get("error"):
            return {"success": False, "message": result["error"]}

        req = result["request"]
        trace_id = req.trace_id or ""

        await cot_manager.log_user_confirmation(trace_id, result["status"] == "approved")

        if result["status"] == "rejected":
            # 用户拒绝：记录并返回拒绝消息
            await self._add_message_to_history(session_id, {
                "role": "user",
                "content": f"用户拒绝执行: {req.tool_name}({json.dumps(req.tool_params or {}, ensure_ascii=False)})",
            })
            message = f"已取消执行 {req.tool_name}"
            await self._add_assistant_message(session_id, message)
            return {
                "success": True,
                "message": message,
                "trace_id": trace_id,
                "type": "text",
            }

        # 用户批准：记录用户操作
        await self._add_message_to_history(session_id, {
            "role": "user",
            "content": f"用户批准执行: {req.tool_name}({json.dumps(req.tool_params or {}, ensure_ascii=False)})",
        })

        # 执行工具（sudo timestamp 已由权限引擎刷新，工具内 sudo 命令可免密）
        result = await self._execute_tool(req.tool_name, req.tool_params or {})

        await cot_manager.log_execution(trace_id, req.tool_name, result, result.get("success", False))

        # 添加工具结果到消息历史
        await self._add_message_to_history(session_id, {
            "tool_call_id": req.tool_call_id,
            "role": "tool",
            "content": json.dumps(result, ensure_ascii=False),
        })

        if stream:
            # 流式：先产出工具执行结果事件，再生成总结
            async def _confirm_gen():
                yield {
                    "type": "tool_result",
                    "tool_name": req.tool_name,
                    "tool_call_id": req.tool_call_id or "",
                    "result": result,
                    "trace_id": trace_id,
                }
                async for evt in self._stream_summary(session_id, trace_id):
                    yield evt
            return _confirm_gen()

        # 非流式总结
        messages = self._build_messages(session_id)
        response = await self.llm_client.chat(messages=messages)

        content = await self._validate_llm_content(response.get("content", ""), trace_id)
        await self._add_assistant_message(
            session_id,
            content,
            prompt_tokens=count_json_tokens(messages),
            completion_tokens=count_tokens(content),
        )
        await cot_manager.log_response(trace_id, content)

        return {
            "success": True,
            "message": content,
            "trace_id": trace_id,
            "tool_result": result,
            "type": "text",
        }
    
    def get_trace(self, trace_id: str) -> Dict[str, Any]:
        """获取思维链追踪"""
        return {
            "trace_id": trace_id,
            "stages": cot_manager.get_trace(trace_id),
            "summary": cot_manager.get_trace_summary(trace_id),
        }
    
    async def test_llm_connection(self) -> Dict[str, Any]:
        """测试LLM连接"""
        return await self.llm_client.test_connection()
    
    def update_llm_config(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        """更新LLM配置"""
        self.llm_client.update_config(api_key, base_url, model)


# 全局Agent实例
agent = Agent()

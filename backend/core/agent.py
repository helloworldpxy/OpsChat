# -*- coding: utf-8 -*-
"""
Agent调度器
核心调度逻辑，协调各模块工作
"""

import json
import logging
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime

from ..config import settings
from ..mcp.registry import tool_registry
from ..security.guardrail import SecurityGuardrail, SecurityDecision
from .llm_client import LLMClient
from .chain_of_thought import cot_manager
from .root_cause import root_cause_analyzer

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
        cot_manager.log_user_input(trace_id, user_message)
        
        # 更新会话活动时间
        self._session_activity[session_id] = datetime.now()
        # 清理过期会话
        self.cleanup_expired_sessions()
        
        # 第一层安全检查：输入过滤
        if settings.enable_security_guardrail:
            check_result = self.security_guardrail.check_input(user_message)
            if not check_result.is_allowed:
                cot_manager.log_safety_check(
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
        self._add_user_message(session_id, user_message)
        
        # 构建消息列表
        messages = self._build_messages(session_id)
        
        # 获取可用工具
        tools = tool_registry.get_llm_tools()
        
        if stream:
            return self._process_stream(messages, tools, session_id, trace_id)
        else:
            return await self._process_normal(messages, tools, session_id, trace_id)
    
    def _add_user_message(self, session_id: str, content: str):
        """添加用户消息"""
        self._add_message(session_id, "user", content)
    
    def _add_assistant_message(self, session_id: str, content: str, tool_calls: Optional[List[Dict]] = None):
        """添加助手消息"""
        self._add_message(session_id, "assistant", content, tool_calls)
    
    def _add_message(self, session_id: str, role: str, content: str, tool_calls: Optional[List[Dict]] = None):
        """添加消息到历史"""
        message = {"role": role, "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        self._add_message_to_history(session_id, message)
    
    def _add_message_to_history(self, session_id: str, message: Dict[str, Any]):
        """添加消息到历史（内存+数据库）"""
        if session_id not in self.conversations:
            self.conversations[session_id] = []
        self.conversations[session_id].append(message)
        
        # 持久化到数据库
        try:
            from ..database import SessionLocal
            from ..models.audit import Conversation, ConversationMessage
            
            db = SessionLocal()
            try:
                # 确保对话记录存在
                conv = db.query(Conversation).filter(Conversation.id == session_id).first()
                if not conv:
                    conv = Conversation(id=session_id, title="新对话")
                    db.add(conv)
                    db.commit()
                
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
                )
                db.add(msg)
                
                # 更新对话标题（取第一条用户消息的前20个字）
                if role == "user" and conv.title == "新对话":
                    conv.title = content[:20] + ("..." if len(content) > 20 else "")
                
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"持久化消息失败: {e}")
    
    def _build_messages(self, session_id: str) -> List[Dict[str, str]]:
        """构建消息列表"""
        messages = [self._get_system_message()]
        
        # 添加对话历史
        history = self.conversations.get(session_id, [])
        messages.extend(history)
        
        return messages
    
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
                cot_manager.log_llm_reasoning(
                    trace_id=trace_id,
                    model=settings.llm_model,
                    thought="正在分析用户请求...",
                )
                
                response = await self.llm_client.chat(messages=messages, tools=tools)
                
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
                    if result.get("type") == "confirmation_required":
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
                        cot_manager.log_safety_check(
                            trace_id=trace_id,
                            risk_level=llm_check.risk_level,
                            rules_triggered=["llm_output_dangerous_command"],
                            decision="REJECT",
                        )
                        content = f"[安全拦截] {llm_check.message}\n\n原始回复中包含高危命令，已被安全护栏拦截。请重新描述您的需求。"
                
                self._add_assistant_message(session_id, content)
                cot_manager.log_response(trace_id, content)
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
                self._add_assistant_message(session_id, error_msg)
                cot_manager.log_response(trace_id, error_msg)
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
        """流式模式处理"""
        try:
            exceeded = True
            for iteration in range(self.MAX_TOOL_ITERATIONS):
                cot_manager.log_llm_reasoning(
                    trace_id=trace_id,
                    model=settings.llm_model,
                    thought="正在分析用户请求...",
                )
                
                full_content = ""
                tool_calls = None
                
                async for chunk in await self.llm_client.chat(messages=messages, tools=tools, stream=True):
                    if chunk["type"] == "content":
                        full_content += chunk["content"]
                        yield {
                            "type": "content",
                            "content": chunk["content"],
                            "trace_id": trace_id,
                        }
                    elif chunk["type"] == "tool_calls":
                        tool_calls = chunk["tool_calls"]
                        yield {
                            "type": "tool_calls",
                            "tool_calls": tool_calls,
                            "trace_id": trace_id,
                        }
                    elif chunk["type"] == "finish":
                        if tool_calls:
                            has_confirmation = False
                            async for result in self._handle_tool_calls_stream(
                                tool_calls=tool_calls,
                                session_id=session_id,
                                trace_id=trace_id,
                                messages=messages,
                                tools=tools,
                            ):
                                if result.get("type") == "confirmation_required":
                                    has_confirmation = True
                                yield result
                            
                            # 如果要求确认，停止循环
                            if has_confirmation:
                                return
                            
                            # 重建消息继续循环
                            messages = self._build_messages(session_id)
                        else:
                            self._add_assistant_message(session_id, full_content)
                            cot_manager.log_response(trace_id, full_content)
                            yield {"type": "finish", "trace_id": trace_id}
                            exceeded = False
                            return
                
                # 如果没有工具调用，退出循环
                if not tool_calls:
                    exceeded = False
                    break
            
            if exceeded:
                error_msg = f"工具调用次数超过限制（{self.MAX_TOOL_ITERATIONS}次），已自动终止"
                logger.warning(error_msg)
                self._add_assistant_message(session_id, error_msg)
                cot_manager.log_response(trace_id, error_msg)
                yield {"type": "content", "content": error_msg, "trace_id": trace_id}
                yield {"type": "finish", "trace_id": trace_id}
                    
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
        """处理工具调用"""
        tool_calls = response.get("tool_calls", [])
        tool_results = []
        
        # 保存助手消息（包含工具调用）
        self._add_assistant_message(session_id, response.get("content", ""), tool_calls)
        
        # 执行每个工具调用
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_args = json.loads(tool_call["function"]["arguments"])
            
            # 安全检查
            if settings.enable_security_guardrail:
                check_result = self.security_guardrail.check_tool_call(tool_name, tool_args)
                
                cot_manager.log_safety_check(
                    trace_id=trace_id,
                    risk_level=check_result.risk_level,
                    rules_triggered=check_result.details.get("rules_triggered", []),
                    decision=check_result.decision.value,
                )
                
                if check_result.decision == SecurityDecision.REJECT:
                    tool_results.append({
                        "tool_call_id": tool_call["id"],
                        "role": "tool",
                        "content": json.dumps({
                            "success": False,
                            "error": check_result.message,
                        }),
                    })
                    continue
                
                if check_result.decision == SecurityDecision.REQUIRE_CONFIRMATION:
                    # 需要用户确认
                    return {
                        "success": True,
                        "type": "confirmation_required",
                        "message": check_result.message,
                        "tool_name": tool_name,
                        "tool_params": tool_args,
                        "trace_id": trace_id,
                        "tool_call_id": tool_call["id"],
                    }
            
            # 执行工具
            cot_manager.log_environment_perception(trace_id, tool_name, tool_args)
            
            result = await self._execute_tool(tool_name, tool_args)
            
            cot_manager.log_execution(trace_id, tool_name, result, result.get("success", False))
            
            tool_results.append({
                "tool_call_id": tool_call["id"],
                "role": "tool",
                "content": json.dumps(result, ensure_ascii=False),
            })
        
        # 添加工具结果到消息历史
        for tool_result in tool_results:
            self._add_message_to_history(session_id, tool_result)
        
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
        session_id: str,
        trace_id: str,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式处理工具调用"""
        tool_results = []
        
        # 保存助手消息（包含工具调用）
        self._add_assistant_message(session_id, "", tool_calls)
        
        # 执行每个工具调用
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_args = json.loads(tool_call["function"]["arguments"])
            
            # 安全检查
            if settings.enable_security_guardrail:
                check_result = self.security_guardrail.check_tool_call(tool_name, tool_args)
                
                cot_manager.log_safety_check(
                    trace_id=trace_id,
                    risk_level=check_result.risk_level,
                    rules_triggered=check_result.details.get("rules_triggered", []),
                    decision=check_result.decision.value,
                )
                
                if check_result.decision == SecurityDecision.REJECT:
                    yield {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": {"success": False, "error": check_result.message},
                        "trace_id": trace_id,
                    }
                    continue
                
                if check_result.decision == SecurityDecision.REQUIRE_CONFIRMATION:
                    yield {
                        "type": "confirmation_required",
                        "message": check_result.message,
                        "tool_name": tool_name,
                        "tool_params": tool_args,
                        "trace_id": trace_id,
                        "tool_call_id": tool_call["id"],
                    }
                    return
            
            # 执行工具
            result = await self._execute_tool(tool_name, tool_args)
            
            yield {
                "type": "tool_result",
                "tool_name": tool_name,
                "result": result,
                "trace_id": trace_id,
            }
            
            tool_results.append({
                "tool_call_id": tool_call["id"],
                "role": "tool",
                "content": json.dumps(result, ensure_ascii=False),
            })
        
        # 添加工具结果到消息历史
        for tool_result in tool_results:
            self._add_message_to_history(session_id, tool_result)
        
        # 再次调用LLM生成最终响应
        messages = self._build_messages(session_id)
        
        full_content = ""
        async for chunk in await self.llm_client.chat(messages=messages, tools=tools, stream=True):
            if chunk["type"] == "content":
                full_content += chunk["content"]
                yield {
                    "type": "content",
                    "content": chunk["content"],
                    "trace_id": trace_id,
                }
            elif chunk["type"] == "finish":
                self._add_assistant_message(session_id, full_content)
                cot_manager.log_response(trace_id, full_content)
                
                yield {
                    "type": "finish",
                    "trace_id": trace_id,
                }
    
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
    
    async def confirm_tool_execution(
        self,
        session_id: str,
        trace_id: str,
        tool_name: str,
        tool_params: Dict[str, Any],
        tool_call_id: str,
        confirmed: bool,
    ) -> Dict[str, Any]:
        """
        确认工具执行
        
        Args:
            session_id: 会话ID
            trace_id: 追踪ID
            tool_name: 工具名称
            tool_params: 工具参数
            tool_call_id: 工具调用ID
            confirmed: 是否确认
            
        Returns:
            执行结果
        """
        cot_manager.log_user_confirmation(trace_id, confirmed)
        
        # 将用户的确认/拒绝操作加入对话历史
        confirm_msg = "确认执行" if confirmed else "拒绝执行"
        self._add_message_to_history(session_id, {
            "role": "user",
            "content": f"用户{confirm_msg}: {tool_name}({json.dumps(tool_params, ensure_ascii=False)})",
        })
        
        if not confirmed:
            # 用户拒绝执行
            message = f"用户拒绝执行 {tool_name}"
            self._add_assistant_message(session_id, message)
            
            return {
                "success": True,
                "message": message,
                "trace_id": trace_id,
            }
        
        # 用户确认执行
        result = await self._execute_tool(tool_name, tool_params)
        
        cot_manager.log_execution(trace_id, tool_name, result, result.get("success", False))
        
        # 添加工具结果到历史
        self._add_message_to_history(session_id, {
            "tool_call_id": tool_call_id,
            "role": "tool",
            "content": json.dumps(result, ensure_ascii=False),
        })
        
        # 调用LLM生成最终响应
        messages = self._build_messages(session_id)
        tools = tool_registry.get_llm_tools()
        
        response = await self.llm_client.chat(messages=messages, tools=tools)
        
        content = response.get("content", "")
        self._add_assistant_message(session_id, content)
        
        cot_manager.log_response(trace_id, content)
        
        return {
            "success": True,
            "message": content,
            "trace_id": trace_id,
            "tool_result": result,
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

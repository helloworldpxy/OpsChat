# -*- coding: utf-8 -*-
"""
思维链管理模块
记录和管理Agent的推理过程
"""

import uuid
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field

from ..utils.text import truncate_json

logger = logging.getLogger(__name__)


@dataclass
class ThoughtStage:
    """思维阶段"""
    stage: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "stage": self.stage,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


class ChainOfThoughtManager:
    """
    思维链管理器
    记录完整的推理过程
    """

    # 内存追踪数量上限（防止无界增长撑爆内存）
    MAX_TRACES = 200
    # 内存侧单阶段 details 截断上限（与 DB 侧一致）
    MAX_DETAILS_CHARS = 8000
    # 内存侧单阶段 content 截断上限
    MAX_CONTENT_CHARS = 4000

    def __init__(self):
        """初始化思维链管理器"""
        self.traces: Dict[str, List[ThoughtStage]] = {}
    
    def _truncate_details(self, details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """截断 details 中的大字段（工具结果），防止内存无界增长"""
        if not details:
            return {}
        from ..utils.text import truncate_json
        return truncate_json(details, max_chars=self.MAX_DETAILS_CHARS) or {}
    
    def _cleanup_old_traces(self):
        """超出上限时按最旧创建时间丢弃，保持内存有界"""
        if len(self.traces) <= self.MAX_TRACES:
            return
        # 按首个阶段的 timestamp 排序，淘汰最旧的
        overflow = len(self.traces) - self.MAX_TRACES
        ordered = sorted(
            self.traces.items(),
            key=lambda kv: kv[1][0].timestamp if kv[1] else datetime.min,
        )
        for trace_id, _ in ordered[:overflow]:
            del self.traces[trace_id]
        logger.warning(f"思维链追踪达到上限({self.MAX_TRACES})，已丢弃最旧的 {overflow} 条")
    
    def create_trace(self, trace_id: Optional[str] = None) -> str:
        """
        创建新的追踪
        
        Args:
            trace_id: 追踪ID，不提供则自动生成
            
        Returns:
            str: 追踪ID
        """
        if trace_id is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
            uuid_short = uuid.uuid4().hex[:8]
            trace_id = f"{date_str}-{uuid_short}"
        
        self.traces[trace_id] = []
        self._cleanup_old_traces()
        logger.info(f"创建思维链追踪: {trace_id}")
        
        return trace_id
    
    async def log_stage(
        self,
        trace_id: str,
        stage: str,
        content: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        记录思维阶段（内存 + aiosqlite 异步持久化）

        Args:
            trace_id: 追踪ID
            stage: 阶段名称
            content: 阶段内容
            details: 详细信息
        """
        if trace_id not in self.traces:
            self.traces[trace_id] = []
        
        thought_stage = ThoughtStage(
            stage=stage,
            content=content[: self.MAX_CONTENT_CHARS],
            details=self._truncate_details(details),
        )
        
        self.traces[trace_id].append(thought_stage)
        self._cleanup_old_traces()
        
        # 异步持久化到数据库（不阻塞事件循环）
        try:
            from sqlalchemy.ext.asyncio import AsyncSession
            from ..database import async_engine
            from ..models.audit import AuditLog
            
            async with AsyncSession(async_engine) as db:
                # 构建审计日志记录
                log_data = {
                    "trace_id": trace_id,
                    "stage": stage,
                    "stage_order": len(self.traces[trace_id]),
                    "content": content,
                    "details": details,
                }
                
                # 安全检查阶段：提取风险等级和决策信息
                if stage == "safety_check":
                    log_data["risk_level"] = details.get("risk_level") if details else None
                    log_data["security_decision"] = details.get("decision") if details else None
                    log_data["rules_triggered"] = details.get("rules_triggered") if details else []
                
                # 感知/执行阶段：提取工具信息（工具结果做截断，避免大输出撑爆审计库）
                if stage in ("environment_perception", "execution"):
                    log_data["tool_name"] = details.get("tool_name") if details else None
                    result = details.get("result") if details else None
                    log_data["tool_result"] = truncate_json(result) if result else None
                
                # 用户确认阶段
                if stage == "user_confirmation":
                    log_data["user_confirmed"] = details.get("confirmed") if details else None
                
                record = AuditLog(**log_data)
                db.add(record)
                await db.commit()
        except Exception as e:
            logger.warning(f"持久化审计日志失败 [{stage}]: {e}")
        
        logger.debug(f"记录思维阶段: [{trace_id}] {stage}")
    
    async def log_user_input(self, trace_id: str, user_input: str):
        """记录用户输入"""
        await self.log_stage(
            trace_id=trace_id,
            stage="user_input",
            content=user_input,
        )
    
    async def log_environment_perception(
        self,
        trace_id: str,
        tool_name: str,
        tool_result: Dict[str, Any],
    ):
        """记录环境感知"""
        await self.log_stage(
            trace_id=trace_id,
            stage="environment_perception",
            content=f"调用工具: {tool_name}",
            details={
                "tool_name": tool_name,
                "result": tool_result,
            },
        )
    
    async def log_llm_reasoning(
        self,
        trace_id: str,
        model: str,
        thought: str,
        planned_action: Optional[str] = None,
    ):
        """记录LLM推理"""
        details = {"model": model}
        if planned_action:
            details["planned_action"] = planned_action
        
        await self.log_stage(
            trace_id=trace_id,
            stage="llm_reasoning",
            content=thought,
            details=details,
        )
    
    async def log_safety_check(
        self,
        trace_id: str,
        risk_level: str,
        rules_triggered: List[str],
        decision: str,
    ):
        """记录安全检查"""
        await self.log_stage(
            trace_id=trace_id,
            stage="safety_check",
            content=f"安全决策: {decision}",
            details={
                "risk_level": risk_level,
                "rules_triggered": rules_triggered,
                "decision": decision,
            },
        )
    
    async def log_user_confirmation(
        self,
        trace_id: str,
        confirmed: bool,
        message: str = "",
    ):
        """记录用户确认"""
        await self.log_stage(
            trace_id=trace_id,
            stage="user_confirmation",
            content=f"用户{'确认' if confirmed else '拒绝'}: {message}",
            details={"confirmed": confirmed},
        )
    
    async def log_execution(
        self,
        trace_id: str,
        tool_name: str,
        result: Dict[str, Any],
        success: bool,
    ):
        """记录执行结果"""
        await self.log_stage(
            trace_id=trace_id,
            stage="execution",
            content=f"执行结果: {'成功' if success else '失败'}",
            details={
                "tool_name": tool_name,
                "result": result,
                "success": success,
            },
        )
    
    async def log_response(self, trace_id: str, response: str):
        """记录最终响应"""
        await self.log_stage(
            trace_id=trace_id,
            stage="response",
            content=response,
        )
    
    def get_trace(self, trace_id: str) -> List[Dict[str, Any]]:
        """
        获取完整追踪
        
        Args:
            trace_id: 追踪ID
            
        Returns:
            List[Dict]: 追踪阶段列表
        """
        stages = self.traces.get(trace_id, [])
        return [stage.to_dict() for stage in stages]
    
    def get_trace_summary(self, trace_id: str) -> Dict[str, Any]:
        """
        获取追踪摘要
        
        Args:
            trace_id: 追踪ID
            
        Returns:
            Dict: 追踪摘要
        """
        stages = self.traces.get(trace_id, [])
        
        if not stages:
            return {"trace_id": trace_id, "exists": False}
        
        return {
            "trace_id": trace_id,
            "exists": True,
            "start_time": stages[0].timestamp.isoformat(),
            "end_time": stages[-1].timestamp.isoformat(),
            "stage_count": len(stages),
            "stages": [stage.stage for stage in stages],
        }
    
    def clear_trace(self, trace_id: str):
        """清除追踪"""
        if trace_id in self.traces:
            del self.traces[trace_id]
    
    def clear_all(self):
        """清除所有追踪"""
        self.traces.clear()


# 全局思维链管理器实例
cot_manager = ChainOfThoughtManager()

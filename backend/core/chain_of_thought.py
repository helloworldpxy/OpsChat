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
    
    def __init__(self):
        """初始化思维链管理器"""
        self.traces: Dict[str, List[ThoughtStage]] = {}
    
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
        logger.info(f"创建思维链追踪: {trace_id}")
        
        return trace_id
    
    def log_stage(
        self,
        trace_id: str,
        stage: str,
        content: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        记录思维阶段
        
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
            content=content,
            details=details or {},
        )
        
        self.traces[trace_id].append(thought_stage)
        
        # 持久化到数据库
        try:
            from ..database import SessionLocal
            from ..models.audit import AuditLog
            
            db = SessionLocal()
            try:
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
                
                # 感知/执行阶段：提取工具信息
                if stage in ("environment_perception", "execution"):
                    log_data["tool_name"] = details.get("tool_name") if details else None
                    log_data["tool_result"] = str(details.get("result")) if details and details.get("result") else None
                
                # 用户确认阶段
                if stage == "user_confirmation":
                    log_data["user_confirmed"] = details.get("confirmed") if details else None
                
                record = AuditLog(**log_data)
                db.add(record)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.warning(f"持久化审计日志失败 [{stage}]: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"保存审计日志异常: {e}")
        
        logger.debug(f"记录思维阶段: [{trace_id}] {stage}")
    
    def log_user_input(self, trace_id: str, user_input: str):
        """记录用户输入"""
        self.log_stage(
            trace_id=trace_id,
            stage="user_input",
            content=user_input,
        )
    
    def log_environment_perception(
        self,
        trace_id: str,
        tool_name: str,
        tool_result: Dict[str, Any],
    ):
        """记录环境感知"""
        self.log_stage(
            trace_id=trace_id,
            stage="environment_perception",
            content=f"调用工具: {tool_name}",
            details={
                "tool_name": tool_name,
                "result": tool_result,
            },
        )
    
    def log_llm_reasoning(
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
        
        self.log_stage(
            trace_id=trace_id,
            stage="llm_reasoning",
            content=thought,
            details=details,
        )
    
    def log_safety_check(
        self,
        trace_id: str,
        risk_level: str,
        rules_triggered: List[str],
        decision: str,
    ):
        """记录安全检查"""
        self.log_stage(
            trace_id=trace_id,
            stage="safety_check",
            content=f"安全决策: {decision}",
            details={
                "risk_level": risk_level,
                "rules_triggered": rules_triggered,
                "decision": decision,
            },
        )
    
    def log_user_confirmation(
        self,
        trace_id: str,
        confirmed: bool,
        message: str = "",
    ):
        """记录用户确认"""
        self.log_stage(
            trace_id=trace_id,
            stage="user_confirmation",
            content=f"用户{'确认' if confirmed else '拒绝'}: {message}",
            details={"confirmed": confirmed},
        )
    
    def log_execution(
        self,
        trace_id: str,
        tool_name: str,
        result: Dict[str, Any],
        success: bool,
    ):
        """记录执行结果"""
        self.log_stage(
            trace_id=trace_id,
            stage="execution",
            content=f"执行结果: {'成功' if success else '失败'}",
            details={
                "tool_name": tool_name,
                "result": result,
                "success": success,
            },
        )
    
    def log_response(self, trace_id: str, response: str):
        """记录最终响应"""
        self.log_stage(
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

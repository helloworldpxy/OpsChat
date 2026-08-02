# -*- coding: utf-8 -*-
"""
安全护栏主模块
整合三层安全防护机制
"""

import logging
from typing import Dict, Any, Optional, Tuple
from enum import Enum

from .input_sanitizer import InputSanitizer, SecurityException
from .output_validator import OutputValidator, ValidationResult
from .sandbox import Sandbox

logger = logging.getLogger(__name__)


class SecurityDecision(str, Enum):
    """安全决策枚举"""
    ALLOW = "allow"                    # 允许执行
    REJECT = "reject"                  # 拒绝执行
    REQUIRE_CONFIRMATION = "require_confirmation"  # 需要用户确认
    WARN = "warn"                      # 警告但允许


class SecurityCheckResult:
    """安全检查结果"""
    
    def __init__(
        self,
        decision: SecurityDecision,
        message: str,
        risk_level: str = "low",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.decision = decision
        self.message = message
        self.risk_level = risk_level
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "decision": self.decision.value,
            "message": self.message,
            "risk_level": self.risk_level,
            "details": self.details,
        }
    
    @property
    def is_allowed(self) -> bool:
        """是否允许执行"""
        return self.decision in [SecurityDecision.ALLOW, SecurityDecision.WARN]
    
    @property
    def requires_confirmation(self) -> bool:
        """是否需要确认"""
        return self.decision == SecurityDecision.REQUIRE_CONFIRMATION


class SecurityGuardrail:
    """
    安全护栏主类
    实现三层安全防护：
    1. 输入过滤 - 防止提示词注入
    2. 输出校验 - 校验LLM输出的工具调用
    3. 沙箱执行 - 限制执行权限
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化安全护栏
        
        Args:
            config: 安全配置字典
        """
        self.config = config or {}
        
        # 初始化各层安全组件
        self.input_sanitizer = InputSanitizer()
        self.output_validator = OutputValidator()
        self.sandbox = Sandbox()
        
        # 安全开关
        self.enable_input_filter = self.config.get("enable_input_filter", True)
        self.enable_output_validation = self.config.get("enable_output_validation", True)
        self.enable_sandbox = self.config.get("enable_sandbox", True)
        
        logger.info("安全护栏初始化完成")
    
    def check_input(self, user_input: str) -> SecurityCheckResult:
        """
        第一层：检查用户输入
        
        Args:
            user_input: 用户输入文本
            
        Returns:
            SecurityCheckResult: 安全检查结果
        """
        if not self.enable_input_filter:
            return SecurityCheckResult(
                decision=SecurityDecision.ALLOW,
                message="输入过滤已禁用"
            )
        
        try:
            # 执行输入过滤
            sanitized_input = self.input_sanitizer.sanitize(user_input)
            
            return SecurityCheckResult(
                decision=SecurityDecision.ALLOW,
                message="输入检查通过",
                risk_level="low"
            )
        except SecurityException as e:
            logger.warning(f"输入安全检查失败: {str(e)}")
            return SecurityCheckResult(
                decision=SecurityDecision.REJECT,
                message=f"输入安全检查失败: {str(e)}",
                risk_level="high",
                details={"exception": str(e)}
            )
    
    def check_tool_call(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str] = None,
    ) -> SecurityCheckResult:
        """
        第二层：检查工具调用
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            current_user: 当前用户
            
        Returns:
            SecurityCheckResult: 安全检查结果
        """
        if not self.enable_output_validation:
            return SecurityCheckResult(
                decision=SecurityDecision.ALLOW,
                message="输出校验已禁用"
            )
        
        # 执行输出校验
        result = self.output_validator.validate_tool_call(tool_name, parameters, current_user)
        
        if result.is_valid:
            # 检查是否需要用户确认
            if result.requires_confirmation:
                return SecurityCheckResult(
                    decision=SecurityDecision.REQUIRE_CONFIRMATION,
                    message=result.message,
                    risk_level=result.risk_level,
                    details=result.details
                )
            else:
                return SecurityCheckResult(
                    decision=SecurityDecision.ALLOW,
                    message="工具调用检查通过",
                    risk_level=result.risk_level
                )
        else:
            return SecurityCheckResult(
                decision=SecurityDecision.REJECT,
                message=result.message,
                risk_level=result.risk_level,
                details=result.details
            )
    
    def check_execution(self, tool_name: str, parameters: Dict[str, Any]) -> SecurityCheckResult:
        """
        第三层：检查执行环境
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            
        Returns:
            SecurityCheckResult: 安全检查结果
        """
        if not self.enable_sandbox:
            return SecurityCheckResult(
                decision=SecurityDecision.ALLOW,
                message="沙箱执行已禁用"
            )
        
        # 检查是否可以在沙箱中执行
        can_execute = self.sandbox.can_execute(tool_name, parameters)
        
        if can_execute:
            return SecurityCheckResult(
                decision=SecurityDecision.ALLOW,
                message="执行环境检查通过"
            )
        else:
            return SecurityCheckResult(
                decision=SecurityDecision.REJECT,
                message="不允许在当前环境下执行此操作",
                risk_level="high"
            )
    
    def full_check(
        self,
        user_input: str,
        tool_name: Optional[str] = None,
        tool_parameters: Optional[Dict[str, Any]] = None,
        current_user: Optional[str] = None,
    ) -> Tuple[bool, SecurityCheckResult]:
        """
        执行完整的安全检查
        
        Args:
            user_input: 用户输入
            tool_name: 工具名称（可选）
            tool_parameters: 工具参数（可选）
            current_user: 当前用户
            
        Returns:
            Tuple[bool, SecurityCheckResult]: (是否通过, 检查结果)
        """
        # 第一层：输入检查
        input_result = self.check_input(user_input)
        if not input_result.is_allowed:
            return False, input_result
        
        # 如果有工具调用，执行第二层检查
        if tool_name and tool_parameters:
            tool_result = self.check_tool_call(tool_name, tool_parameters, current_user)
            if not tool_result.is_allowed and not tool_result.requires_confirmation:
                return False, tool_result
            
            # 第三层：执行环境检查
            exec_result = self.check_execution(tool_name, tool_parameters)
            if not exec_result.is_allowed:
                return False, exec_result
            
            # 如果需要确认，返回确认请求
            if tool_result.requires_confirmation:
                return True, tool_result
        
        return True, SecurityCheckResult(
            decision=SecurityDecision.ALLOW,
            message="安全检查全部通过"
        )

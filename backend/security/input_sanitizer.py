# -*- coding: utf-8 -*-
"""
输入过滤模块
第一层安全防护：防止提示词注入攻击
"""

import re
import logging
from typing import List, Pattern

logger = logging.getLogger(__name__)


class SecurityException(Exception):
    """安全异常"""
    pass


class InputSanitizer:
    """
    输入过滤器
    检测并阻止提示词注入攻击
    """
    
    def __init__(self):
        """初始化输入过滤器"""
        # 提示词注入模式
        self.injection_patterns: List[Pattern] = [
            # 中文注入模式
            re.compile(r"忽略(之前|上面|以上|前面)的(指令|规则|提示|要求|对话)", re.IGNORECASE),
            re.compile(r"无视(之前|上面|以上|前面)的(指令|规则|提示|要求)", re.IGNORECASE),
            re.compile(r"不要(遵循|遵守|执行)(之前|上面|以上|前面)的(指令|规则|提示)", re.IGNORECASE),
            re.compile(r"(忘记|丢弃|抛弃)(之前|上面|以上|前面)的(指令|规则|提示|要求)", re.IGNORECASE),
            re.compile(r"你现在是", re.IGNORECASE),
            re.compile(r"假装(你是|自己是|你是)", re.IGNORECASE),
            re.compile(r"扮演(一个|一位)?", re.IGNORECASE),
            re.compile(r"从现在开始", re.IGNORECASE),
            re.compile(r"(新的|另一个)(身份|角色|模式)", re.IGNORECASE),
            
            # 英文注入模式
            re.compile(r"ignore (previous|above|earlier) (instructions|rules|prompts|context)", re.IGNORECASE),
            re.compile(r"disregard (previous|above|earlier) (instructions|rules|prompts)", re.IGNORECASE),
            re.compile(r"forget (previous|above|earlier) (instructions|rules|prompts)", re.IGNORECASE),
            re.compile(r"you are now", re.IGNORECASE),
            re.compile(r"pretend (you are|to be|you're)", re.IGNORECASE),
            re.compile(r"act as (a|an)", re.IGNORECASE),
            re.compile(r"from now on", re.IGNORECASE),
            re.compile(r"new (identity|persona|role|mode)", re.IGNORECASE),
            re.compile(r"system prompt", re.IGNORECASE),
            re.compile(r"jailbreak", re.IGNORECASE),
            
            # 命令注入模式
            re.compile(r";\s*(rm|shutdown|reboot|mkfs|dd|chmod|chown)\s", re.IGNORECASE),
            re.compile(r"\|\s*(rm|shutdown|reboot|mkfs|dd|chmod|chown)\s", re.IGNORECASE),
            re.compile(r"`[^`]*(rm|shutdown|reboot|mkfs|dd)\s", re.IGNORECASE),
            re.compile(r"\$\([^)]*(rm|shutdown|reboot|mkfs|dd)\s", re.IGNORECASE),
            
            # SQL注入模式
            re.compile(r"(union\s+select|drop\s+table|delete\s+from|insert\s+into)", re.IGNORECASE),
            
            # 越狱尝试
            re.compile(r"DAN\s*(mode|prompt|version)", re.IGNORECASE),
            re.compile(r"developer\s*mode", re.IGNORECASE),
            re.compile(r"(bypass|override)\s*(safety|security|filter|restriction)", re.IGNORECASE),
        ]
        
        # 危险命令模式
        self.dangerous_command_patterns: List[Pattern] = [
            re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
            re.compile(r"\bmkfs\b", re.IGNORECASE),
            re.compile(r"\bdd\s+if=.*of=/dev/", re.IGNORECASE),
            re.compile(r"\bshutdown\b", re.IGNORECASE),
            re.compile(r"\breboot\b", re.IGNORECASE),
            re.compile(r"\binit\s+0\b", re.IGNORECASE),
            re.compile(r"\bhalt\b", re.IGNORECASE),
        ]
        
        # 敏感信息模式
        self.sensitive_patterns: List[Pattern] = [
            re.compile(r"(password|passwd|pwd)\s*[:=]\s*\S+", re.IGNORECASE),
            re.compile(r"(api[_-]?key|apikey)\s*[:=]\s*\S+", re.IGNORECASE),
            re.compile(r"(secret|token)\s*[:=]\s*\S+", re.IGNORECASE),
            re.compile(r"(aws|azure|gcp)[_-]?(access|secret)[_-]?(key|token)", re.IGNORECASE),
        ]
        
        logger.info("输入过滤器初始化完成")
    
    def sanitize(self, user_input: str) -> str:
        """
        过滤用户输入
        
        Args:
            user_input: 用户输入文本
            
        Returns:
            过滤后的输入文本
            
        Raises:
            SecurityException: 检测到安全威胁时抛出
        """
        if not user_input or not user_input.strip():
            return user_input
        
        # 检查提示词注入
        self._check_injection(user_input)
        
        # 检查危险命令
        self._check_dangerous_commands(user_input)
        
        # 检查敏感信息泄露
        self._check_sensitive_info(user_input)
        
        return user_input
    
    def _check_injection(self, text: str) -> None:
        """检查提示词注入"""
        for pattern in self.injection_patterns:
            match = pattern.search(text)
            if match:
                matched_text = match.group()
                logger.warning(f"检测到潜在的提示词注入: {matched_text}")
                raise SecurityException(
                    f"检测到潜在的提示词注入攻击，输入包含: '{matched_text}'"
                )
    
    def _check_dangerous_commands(self, text: str) -> None:
        """检查危险命令"""
        for pattern in self.dangerous_command_patterns:
            match = pattern.search(text)
            if match:
                matched_text = match.group()
                logger.warning(f"检测到危险命令: {matched_text}")
                raise SecurityException(
                    f"检测到危险命令，拒绝执行: '{matched_text}'"
                )
    
    def _check_sensitive_info(self, text: str) -> None:
        """检查敏感信息泄露（警告但不阻止）"""
        for pattern in self.sensitive_patterns:
            match = pattern.search(text)
            if match:
                logger.warning(f"检测到敏感信息: {match.group()[:20]}...")
                # 只警告，不阻止
                break
    
    def get_risk_score(self, text: str) -> float:
        """
        计算输入的风险分数
        
        Args:
            text: 输入文本
            
        Returns:
            风险分数 (0.0-1.0)
        """
        score = 0.0
        
        # 检查注入模式
        for pattern in self.injection_patterns:
            if pattern.search(text):
                score += 0.4
        
        # 检查危险命令
        for pattern in self.dangerous_command_patterns:
            if pattern.search(text):
                score += 0.3
        
        # 检查敏感信息
        for pattern in self.sensitive_patterns:
            if pattern.search(text):
                score += 0.1
        
        # 限制分数范围
        return min(score, 1.0)

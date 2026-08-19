# -*- coding: utf-8 -*-
"""
输出校验模块
第二层安全防护：校验LLM输出的工具调用
"""

import os
import re
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ValidationResult:
    """校验结果"""
    is_valid: bool
    message: str
    risk_level: str = "low"
    requires_confirmation: bool = False
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "is_valid": self.is_valid,
            "message": self.message,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "details": self.details,
        }


class OutputValidator:
    """
    输出校验器
    校验LLM输出的工具调用是否安全
    """
    
    def __init__(self):
        """初始化输出校验器"""
        # 系统关键路径
        self.critical_paths = [
            "/etc",
            "/boot",
            "/var/lib",
            "/usr",
            "/bin",
            "/sbin",
            "/lib",
            "/lib64",
            "/root",
            "/proc",
            "/sys",
            "/dev",
        ]
        
        # 危险文件扩展名
        self.dangerous_extensions = [
            ".conf",
            ".cfg",
            ".ini",
            ".yaml",
            ".yml",
            ".json",
            ".sh",
            ".bash",
            ".service",
            ".socket",
            ".timer",
        ]
        
        # 高危工具列表
        self.high_risk_tools = [
            "delete_file",
            "chmod",
            "chown",
            "kill_process",
            "restart_service",
            "stop_service",
        ]
        
        # 需要确认的工具
        self.require_confirmation_tools = [
            "restart_service",
            "stop_service",
        ]
        
        # 安全规则列表
        self.safety_rules: List[Callable] = [
            self._rule_no_critical_path_delete,
            self._rule_no_root_kill,
            self._rule_no_777_permission,
            self._rule_no_systemd_stop,
            self._rule_no_dev_manipulation,
            self._rule_path_traversal_check,
            self._rule_no_recursive_delete_critical,
            self._rule_no_unsafe_permissions,
            self._rule_no_mass_kill,
            self._rule_no_baseline_tampering,
            self._rule_no_monitoring_sabotage,
        ]
        
        # LLM输出内容危险模式
        self._llm_dangerous_patterns = [
            re.compile(r"rm\s+-[a-z]*r[a-z]*f", re.IGNORECASE),
            re.compile(r"rm\s+-[a-z]*f[a-z]*r", re.IGNORECASE),
            re.compile(r"mkfs\s", re.IGNORECASE),
            re.compile(r"dd\s+if=.*of=/dev/", re.IGNORECASE),
            re.compile(r"chmod\s+(777|0777|666|0666)\s", re.IGNORECASE),
            re.compile(r"echo\s+.*>\s*/etc/(passwd|shadow|sudoers)", re.IGNORECASE),
            re.compile(r"shutdown|reboot|halt|init\s+0", re.IGNORECASE),
            re.compile(r"systemctl\s+(stop|disable)\s+(sshd|firewalld|auditd)", re.IGNORECASE),
            re.compile(r"kill\s+-9\s+1\b", re.IGNORECASE),
            re.compile(r"iptables\s+-F", re.IGNORECASE),
        ]
        
        logger.info("输出校验器初始化完成")
    
    def validate_tool_call(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str] = None,
    ) -> ValidationResult:
        """
        校验工具调用
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            current_user: 当前用户
            
        Returns:
            ValidationResult: 校验结果
        """
        # 检查工具是否为高危工具
        risk_level = self._get_risk_level(tool_name)
        
        # 执行安全规则检查
        for rule in self.safety_rules:
            result = rule(tool_name, parameters, current_user)
            if not result.is_valid:
                return result
        
        # 检查是否需要确认
        requires_confirmation = tool_name in self.require_confirmation_tools or risk_level in ["high", "critical"]
        
        return ValidationResult(
            is_valid=True,
            message="工具调用校验通过",
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
        )
    
    def _get_risk_level(self, tool_name: str) -> str:
        """获取工具风险等级"""
        if tool_name in ["delete_file", "chmod", "chown"]:
            return RiskLevel.HIGH.value
        elif tool_name in ["kill_process", "restart_service", "stop_service"]:
            return RiskLevel.HIGH.value
        else:
            return RiskLevel.LOW.value
    
    def _rule_no_critical_path_delete(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则1: 禁止删除系统关键路径"""
        if tool_name != "delete_file":
            return ValidationResult(is_valid=True, message="通过")
        
        path = parameters.get("path", "")
        for critical_path in self.critical_paths:
            if path == critical_path or path.startswith(critical_path + "/"):
                return ValidationResult(
                    is_valid=False,
                    message=f"禁止删除系统关键目录: {critical_path}",
                    risk_level=RiskLevel.CRITICAL.value,
                    details={"path": path, "critical_path": critical_path}
                )
        
        return ValidationResult(is_valid=True, message="通过")
    
    def _rule_no_root_kill(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则2: 禁止kill PID 1"""
        if tool_name != "kill_process":
            return ValidationResult(is_valid=True, message="通过")
        
        pid = parameters.get("pid")
        if pid == 1:
            return ValidationResult(
                is_valid=False,
                message="禁止终止PID 1 (init进程)",
                risk_level=RiskLevel.CRITICAL.value,
                details={"pid": pid}
            )
        
        return ValidationResult(is_valid=True, message="通过")
    
    def _rule_no_777_permission(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则3: 禁止设置777权限"""
        if tool_name != "chmod":
            return ValidationResult(is_valid=True, message="通过")
        
        mode = parameters.get("mode", "")
        if mode in ["777", "0777", "a+rwx"]:
            return ValidationResult(
                is_valid=False,
                message="不允许设置777权限，存在安全风险",
                risk_level=RiskLevel.HIGH.value,
                details={"mode": mode}
            )
        
        return ValidationResult(is_valid=True, message="通过")
    
    def _rule_no_systemd_stop(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则4: 限制关键系统服务停止"""
        if tool_name not in ["stop_service", "restart_service"]:
            return ValidationResult(is_valid=True, message="通过")
        
        service_name = parameters.get("service_name", "")
        critical_services = [
            "sshd",
            "systemd",
            "systemd-logind",
            "dbus",
            "networkd",
            "NetworkManager",
            "firewalld",
        ]
        
        if service_name in critical_services:
            return ValidationResult(
                is_valid=False,
                message=f"不允许停止关键系统服务: {service_name}",
                risk_level=RiskLevel.CRITICAL.value,
                details={"service_name": service_name}
            )
        
        return ValidationResult(is_valid=True, message="通过")
    
    def _rule_no_dev_manipulation(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则5: 禁止操作/dev设备文件"""
        path = parameters.get("path", "")
        if path.startswith("/dev"):
            return ValidationResult(
                is_valid=False,
                message="禁止操作设备文件",
                risk_level=RiskLevel.CRITICAL.value,
                details={"path": path}
            )
        
        return ValidationResult(is_valid=True, message="通过")
    
    def _rule_path_traversal_check(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则6: 路径遍历检查"""
        path = parameters.get("path", "")
        if ".." in path:
            return ValidationResult(
                is_valid=False,
                message="检测到路径遍历攻击",
                risk_level=RiskLevel.HIGH.value,
                details={"path": path}
            )
        
        return ValidationResult(is_valid=True, message="通过")
    
    def _rule_no_recursive_delete_critical(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则7: 禁止递归删除关键目录（rm -rf等效）"""
        if tool_name != "delete_file":
            return ValidationResult(is_valid=True, message="通过")
        
        path = parameters.get("path", "")
        recursive = parameters.get("recursive", False)
        
        if recursive:
            normalized = path.replace("\\", "/").rstrip("/")
            dangerous_dirs = ["/", "/etc", "/var", "/usr", "/home", "/boot", "/tmp", "/opt"]
            for d in dangerous_dirs:
                if normalized == d or normalized == d.rstrip("/"):
                    return ValidationResult(
                        is_valid=False,
                        message=f"安全拦截: 禁止递归删除关键目录 {d}（等效 rm -rf {d}）",
                        risk_level=RiskLevel.CRITICAL.value,
                        details={"path": path, "recursive": True}
                    )
        
        return ValidationResult(is_valid=True, message="通过")
    
    def _rule_no_unsafe_permissions(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则8: 拦截不安全的权限设置"""
        if tool_name != "chmod":
            return ValidationResult(is_valid=True, message="通过")
        
        mode = parameters.get("mode", "")
        unsafe_modes = ["777", "0777", "666", "0666", "776", "0776"]
        if mode in unsafe_modes:
            return ValidationResult(
                is_valid=False,
                message=f"不允许设置不安全权限 {mode}，其他用户可写入存在安全风险",
                risk_level=RiskLevel.HIGH.value,
                details={"mode": mode}
            )
        
        path = parameters.get("path", "")
        sensitive_files = ["/etc/passwd", "/etc/shadow", "/etc/sudoers", "/etc/ssh/sshd_config"]
        if path in sensitive_files:
            try:
                mode_int = int(mode, 8)
                if mode_int & 0o022:
                    return ValidationResult(
                        is_valid=False,
                        message=f"不允许对敏感配置文件 {path} 设置可写权限",
                        risk_level=RiskLevel.CRITICAL.value,
                        details={"path": path, "mode": mode}
                    )
            except ValueError:
                pass
        
        return ValidationResult(is_valid=True, message="通过")
    
    def _rule_no_mass_kill(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则9: 防止批量终止进程（killall等效）"""
        if tool_name != "kill_process":
            return ValidationResult(is_valid=True, message="通过")
        
        signal = parameters.get("signal", "SIGTERM")
        pid = parameters.get("pid")
        
        if pid == 0:
            return ValidationResult(
                is_valid=False,
                message="安全拦截: 禁止 kill PID 0（会终止当前进程组所有进程）",
                risk_level=RiskLevel.CRITICAL.value,
                details={"pid": pid, "signal": signal}
            )
        
        return ValidationResult(is_valid=True, message="通过")
    
    def _rule_no_baseline_tampering(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则10: 禁止篡改配置基线文件（防止隐藏配置漂移）"""
        path = parameters.get("path", "")
        
        protected_paths = [
            "data/config_baseline.json",
            "config_baseline.json",
        ]
        normalized = path.replace("\\", "/")
        for pp in protected_paths:
            if normalized.endswith(pp) or normalized.endswith(pp.split("/")[-1]):
                if tool_name in ["delete_file", "chmod"]:
                    return ValidationResult(
                        is_valid=False,
                        message="安全拦截: 禁止修改或删除配置基线文件，这会破坏配置漂移检测能力",
                        risk_level=RiskLevel.HIGH.value,
                        details={"path": path, "tool": tool_name}
                    )
        
        return ValidationResult(is_valid=True, message="通过")
    
    def _rule_no_monitoring_sabotage(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        current_user: Optional[str],
    ) -> ValidationResult:
        """规则11: 禁止停止安全监控/日志服务（防止绕过安全审计）"""
        if tool_name not in ["stop_service", "restart_service"]:
            return ValidationResult(is_valid=True, message="通过")
        
        service_name = parameters.get("service_name", "")
        security_services = [
            "auditd", "rsyslog", "syslog", "systemd-journald",
            "firewalld", "iptables", "selinux",
            "fail2ban", "aide", "tripwire",
        ]
        if service_name in security_services:
            return ValidationResult(
                is_valid=False,
                message=f"安全拦截: 禁止停止安全监控服务 {service_name}，这会削弱系统安全审计能力",
                risk_level=RiskLevel.CRITICAL.value,
                details={"service_name": service_name, "tool": tool_name}
            )
        
        return ValidationResult(is_valid=True, message="通过")
    
    def validate_llm_output(self, text: str) -> ValidationResult:
        """
        校验LLM文本输出中的危险指令
        防止LLM在回复中直接给出危险的shell命令
        """
        if not text:
            return ValidationResult(is_valid=True, message="通过")
        
        code_blocks = re.findall(r'```(?:bash|sh|shell)?\n(.*?)```', text, re.DOTALL)
        all_code = "\n".join(code_blocks)
        check_text = all_code + "\n" + text
        
        for pattern in self._llm_dangerous_patterns:
            match = pattern.search(check_text)
            if match:
                matched = match.group()
                logger.warning(f"LLM输出中检测到危险指令: {matched}")
                return ValidationResult(
                    is_valid=False,
                    message=f"LLM输出中包含高危命令: {matched}，已拦截",
                    risk_level=RiskLevel.HIGH.value,
                    details={"matched": matched, "pattern": pattern.pattern}
                )
        
        return ValidationResult(is_valid=True, message="通过")

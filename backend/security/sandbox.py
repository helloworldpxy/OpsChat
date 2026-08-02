# -*- coding: utf-8 -*-
"""
执行沙箱模块
第三层安全防护：限制执行权限和环境
"""

import os
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class Sandbox:
    """
    执行沙箱
    限制工具执行的权限和环境
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化执行沙箱
        
        Args:
            config: 沙箱配置
        """
        self.config = config or {}
        
        # 允许执行的用户
        self.allowed_users = self.config.get("allowed_users", ["opsagent", "root"])
        
        # 禁止执行的路径前缀
        self.forbidden_path_prefixes = [
            "/dev",
            "/proc",
            "/sys",
        ]
        
        # 只读路径
        self.readonly_paths = [
            "/etc",
            "/boot",
            "/usr",
            "/lib",
            "/lib64",
        ]
        
        # 允许执行的命令
        self.allowed_commands = [
            "ps",
            "top",
            "df",
            "du",
            "free",
            "uptime",
            "hostname",
            "uname",
            "whoami",
            "id",
            "ip",
            "ifconfig",
            "ping",
            "netstat",
            "ss",
            "lsof",
            "journalctl",
            "systemctl",
            "cat",
            "head",
            "tail",
            "grep",
            "find",
            "ls",
            "wc",
        ]
        
        # 需要sudo的命令
        self.sudo_commands = [
            "systemctl",
            "journalctl",
        ]
        
        logger.info("执行沙箱初始化完成")
    
    def can_execute(self, tool_name: str, parameters: Dict[str, Any]) -> bool:
        """
        检查工具是否可以在沙箱中执行
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            
        Returns:
            bool: 是否允许执行
        """
        # 检查路径参数
        path = parameters.get("path", "")
        if path:
            # 检查禁止路径
            for prefix in self.forbidden_path_prefixes:
                if path.startswith(prefix):
                    logger.warning(f"禁止操作路径: {path}")
                    return False
            
            # 检查只读路径（只允许读取，不允许修改）
            if tool_name in ["delete_file", "modify_config", "chmod", "chown"]:
                for readonly_path in self.readonly_paths:
                    if path.startswith(readonly_path):
                        logger.warning(f"禁止修改只读路径: {path}")
                        return False
        
        return True
    
    def get_sandbox_command(self, command: str, args: List[str]) -> List[str]:
        """
        获取沙箱包装后的命令
        
        Args:
            command: 原始命令
            args: 命令参数
            
        Returns:
            List[str]: 包装后的命令列表
        """
        # 检查是否需要sudo
        if command in self.sudo_commands:
            return ["sudo", command] + args
        
        return [command] + args
    
    def validate_path(self, path: str) -> bool:
        """
        验证路径是否安全
        
        Args:
            path: 文件路径
            
        Returns:
            bool: 路径是否安全
        """
        # 规范化路径
        normalized_path = os.path.normpath(path)
        
        # 检查路径遍历
        if ".." in normalized_path:
            return False
        
        # 检查禁止路径
        for prefix in self.forbidden_path_prefixes:
            if normalized_path.startswith(prefix):
                return False
        
        return True
    
    def get_resource_limits(self) -> Dict[str, Any]:
        """
        获取资源限制配置
        
        Returns:
            Dict: 资源限制配置
        """
        return {
            "max_cpu_percent": self.config.get("max_cpu_percent", 80),
            "max_memory_mb": self.config.get("max_memory_mb", 512),
            "timeout_seconds": self.config.get("timeout_seconds", 60),
            "max_output_size": self.config.get("max_output_size", 1024 * 1024),  # 1MB
        }

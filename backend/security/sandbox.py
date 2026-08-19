# -*- coding: utf-8 -*-
"""
执行沙箱模块
第三层安全防护：限制执行权限和环境
"""

import os
import subprocess
import logging
from typing import Dict, Any, List, Optional

from ..utils.text import truncate_text

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
    
    def run_shell(
        self,
        command,
        args: Optional[List[str]] = None,
        timeout: Optional[int] = None,
        shell: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        统一 shell 执行入口（沙箱接线点）
        - list 形式：经 get_sandbox_command 包装（sudo 提权），禁用 shell 解释
        - shell 字符串：保留 shell 语义，但同样做超时限制与输出截断
        - 输出统一 ANSI 清理 + 按资源限制截断

        Args:
            command: 命令名（str），或完整 argv 列表（list）
            args: list 形式的参数
            timeout: 超时秒数（默认取资源限制配置）
            shell: 是否按 shell 字符串执行
            **kwargs: 透传 subprocess.run 参数

        Returns:
            Dict: 执行结果（success/stdout/stderr/returncode）
        """
        # 兼容“整条 argv 作为列表传入”的调用方式
        if isinstance(command, (list, tuple)):
            cmd_parts = list(command)
            command = cmd_parts[0]
            args = list(cmd_parts[1:]) + list(args or [])

        limits = self.get_resource_limits()
        timeout = timeout if timeout is not None else limits.get("timeout_seconds", 60)
        max_output = limits.get("max_output_size", 1024 * 1024)

        try:
            if shell or (isinstance(command, str) and not args):
                # shell 字符串执行
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    **kwargs,
                )
            else:
                # list 形式：经沙箱包装（sudo 提权）
                cmd = self.get_sandbox_command(command, args or [])
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    **kwargs,
                )

            return {
                "success": result.returncode == 0,
                "stdout": truncate_text(result.stdout, max_chars=max_output),
                "stderr": truncate_text(result.stderr, max_chars=max_output),
                "returncode": result.returncode,
            }
        except FileNotFoundError:
            return {"success": False, "error": f"命令不存在: {command}"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"命令执行超时: {command}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
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

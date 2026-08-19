# -*- coding: utf-8 -*-
"""
自定义工具执行器
执行用户自定义的命令模板
"""

import re
import shlex
import logging
from typing import Dict, Any

from ..protocol import ToolExecutor
from ...security.sandbox import Sandbox

logger = logging.getLogger(__name__)

# 危险的 shell 命令片段黑名单（自定义工具模板不允许包含）
_DANGEROUS_SHELL_PATTERNS = [
    re.compile(r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+\s*/?\s*$", re.IGNORECASE),
    re.compile(r"\brm\s+-[a-zA-Z]*[rf]", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+.*of=/dev/", re.IGNORECASE),
    re.compile(r"\bshred\b", re.IGNORECASE),
    re.compile(r"\b>+\s*/dev/sd[a-z]", re.IGNORECASE),
    re.compile(r"\bchmod\s+-R\s+777\b", re.IGNORECASE),
    re.compile(r"\bchown\b.*root", re.IGNORECASE),
    re.compile(r"\bpasswd\b", re.IGNORECASE),
    re.compile(r"\buseradd\b", re.IGNORECASE),
    re.compile(r"\bwget\b.*\|", re.IGNORECASE),
    re.compile(r"\bcurl\b.*\|", re.IGNORECASE),
    re.compile(r"\b(base64|xxd)\b.*(-d|--decode)", re.IGNORECASE),
    re.compile(r"\bmv\b.*\s+\/etc\/", re.IGNORECASE),
    re.compile(r"\b\|\s*(sh|bash|python|perl|ruby)\b", re.IGNORECASE),
]


class CustomToolExecutor(ToolExecutor):
    """自定义工具执行器"""

    def __init__(self, definition, command_template: str, command_type: str = "shell"):
        super().__init__(definition)
        self.command_template = command_template
        self.command_type = command_type
        self.sandbox = Sandbox()

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """执行自定义工具"""
        try:
            # 替换命令模板中的参数
            command = self._render_command(kwargs)

            if self.command_type == "python":
                return await self._execute_python(command, kwargs)
            else:
                return await self._execute_shell(command)

        except Exception as e:
            logger.error(f"自定义工具 {self.definition.name} 执行失败: {e}")
            return {"success": False, "error": str(e)}

    def _render_command(self, params: Dict[str, Any]) -> str:
        """渲染命令模板，参数值经 shlex.quote 转义防止注入"""
        command = self.command_template
        for key, value in params.items():
            command = command.replace(f"{{{key}}}", shlex.quote(str(value)))
        # 清理未替换的占位符
        command = re.sub(r'\{[a-zA-Z_]+\}', '', command)
        return command.strip()

    async def _execute_shell(self, command: str) -> Dict[str, Any]:
        """执行shell命令（经沙箱统一出口：超时限制 + ANSI清理 + 输出截断）"""
        try:
            result = self.sandbox.run_shell(command, shell=True)

            return {
                "success": result["success"],
                "data": {
                    "command": command,
                    "stdout": result.get("stdout", ""),
                    "stderr": result.get("stderr", ""),
                    "returncode": result.get("returncode"),
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_python(self, code: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行Python代码
        注意：Python exec 无法被真正沙箱化（对象属性访问可逃逸到完整 builtins）。
        为消除任意代码执行面，python 类型自定义工具默认禁用，返回明确错误。
        """
        return {
            "success": False,
            "error": "python 类型自定义工具已被安全策略禁用（exec 无法安全沙箱化，可能被用于任意代码执行）。"
                     "请改用 shell 类型并限制在安全命令内，或在服务端将本工具定义为内置工具。",
        }

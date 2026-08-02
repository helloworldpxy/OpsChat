# -*- coding: utf-8 -*-
"""
自定义工具执行器
执行用户自定义的命令模板
"""

import re
import shlex
import subprocess
import logging
from typing import Dict, Any

from ..protocol import ToolExecutor

logger = logging.getLogger(__name__)


class CustomToolExecutor(ToolExecutor):
    """自定义工具执行器"""

    def __init__(self, definition, command_template: str, command_type: str = "shell"):
        super().__init__(definition)
        self.command_template = command_template
        self.command_type = command_type

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
        """执行shell命令"""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )

            return {
                "success": result.returncode == 0,
                "data": {
                    "command": command,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                    "returncode": result.returncode,
                }
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"命令执行超时: {command}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_python(self, code: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行Python代码"""
        try:
            # 安全的执行环境
            safe_globals = {
                "__builtins__": {
                    "print": print,
                    "len": len,
                    "str": str,
                    "int": int,
                    "float": float,
                    "list": list,
                    "dict": dict,
                    "tuple": tuple,
                    "range": range,
                    "enumerate": enumerate,
                    "zip": zip,
                    "map": map,
                    "filter": filter,
                    "sorted": sorted,
                    "reversed": reversed,
                    "min": min,
                    "max": max,
                    "sum": sum,
                    "abs": abs,
                    "round": round,
                    "type": type,
                    "isinstance": isinstance,
                    "hasattr": hasattr,
                    "getattr": getattr,
                    "True": True,
                    "False": False,
                    "None": None,
                }
            }
            safe_locals = {"params": params, "result": None}

            exec(code, safe_globals, safe_locals)

            return {
                "success": True,
                "data": {
                    "result": safe_locals.get("result", "代码执行完成"),
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Python执行错误: {str(e)}"}

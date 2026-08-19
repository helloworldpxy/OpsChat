# -*- coding: utf-8 -*-
"""
原生Linux命令工具
调用 lsof, netstat, dmesg, iostat 等底层命令获取系统信息
"""

import subprocess
import platform
from typing import Dict, Any, Optional

from ..protocol import ToolExecutor
from ...security.sandbox import Sandbox

_sandbox = Sandbox()


def _run_cmd(cmd: list, timeout: int = 10) -> Dict[str, Any]:
    """执行系统命令并返回结果（经沙箱统一出口：sudo 包装 + ANSI清理 + 输出截断）"""
    if not cmd:
        return {"success": False, "error": "空命令"}
    result = _sandbox.run_shell(cmd[0], cmd[1:], timeout=timeout)
    if "error" in result:
        return result
    return {
        "success": result["success"],
        "stdout": result.get("stdout", "").strip(),
        "stderr": result.get("stderr", "").strip(),
        "returncode": result.get("returncode"),
    }


class LsofTool(ToolExecutor):
    """lsof - 查看文件/端口占用"""

    name = "lsof_ports"
    description = "使用lsof查看端口占用或文件打开情况。可查看指定端口被哪个进程占用"
    category = "system"
    risk_level = "low"
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "port": {
                "type": "integer",
                "description": "要查询的端口号（不填则列出所有监听端口）"
            },
            "pid": {
                "type": "integer",
                "description": "查看指定进程打开的文件"
            }
        },
        "required": []
    }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        port = kwargs.get("port")
        pid = kwargs.get("pid")

        if platform.system() != "Linux":
            return {"success": False, "error": "lsof仅支持Linux系统"}

        if port:
            cmd = ["lsof", "-i", f":{port}", "-P", "-n"]
        elif pid:
            cmd = ["lsof", "-p", str(pid)]
        else:
            # 列出所有监听端口
            cmd = ["lsof", "-i", "-sTCP:LISTEN", "-P", "-n"]

        result = _run_cmd(cmd)
        if not result["success"]:
            # lsof可能不存在，回退到ss
            if port:
                cmd = ["ss", "-tlnp", f"sport = :{port}"]
            else:
                cmd = ["ss", "-tlnp"]
            result = _run_cmd(cmd)

        if result["success"]:
            lines = result["stdout"].split("\n")
            return {
                "success": True,
                "data": {
                    "command": " ".join(cmd),
                    "output_lines": len(lines),
                    "output": result["stdout"],
                }
            }
        return result


class NetstatTool(ToolExecutor):
    """netstat - 查看网络连接状态"""

    name = "netstat_connections"
    description = "使用netstat查看网络连接、监听端口、路由表等网络状态信息"
    category = "network"
    risk_level = "low"
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": "查看模式: listening(监听端口), connections(所有连接), routing(路由表), stats(统计)",
                "default": "listening"
            }
        },
        "required": []
    }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        mode = kwargs.get("mode", "listening")

        if platform.system() != "Linux":
            return {"success": False, "error": "netstat仅支持Linux系统"}

        mode_map = {
            "listening": ["netstat", "-tlnp"],
            "connections": ["netstat", "-tanp"],
            "routing": ["netstat", "-rn"],
            "stats": ["netstat", "-s"],
        }
        cmd = mode_map.get(mode, mode_map["listening"])
        result = _run_cmd(cmd)

        # netstat不存在时回退到ss
        if not result["success"] and mode == "listening":
            cmd = ["ss", "-tlnp"]
            result = _run_cmd(cmd)
        elif not result["success"] and mode == "connections":
            cmd = ["ss", "-tanp"]
            result = _run_cmd(cmd)

        if result["success"]:
            lines = result["stdout"].split("\n")
            return {
                "success": True,
                "data": {
                    "mode": mode,
                    "command": " ".join(cmd),
                    "output_lines": len(lines),
                    "output": result["stdout"],
                }
            }
        return result


class DmesgTool(ToolExecutor):
    """dmesg - 查看内核日志"""

    name = "dmesg_kernel_log"
    description = "使用dmesg查看内核日志，可按优先级过滤。用于排查硬件错误、OOM、驱动问题等"
    category = "system"
    risk_level = "low"
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "description": "日志级别过滤: emerg/alert/crit/err/warning/notice/info/debug。不填则显示全部",
                "default": ""
            },
            "lines": {
                "type": "integer",
                "description": "显示最后N行",
                "default": 50
            }
        },
        "required": []
    }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        level = kwargs.get("level", "")
        lines = kwargs.get("lines", 50)

        if platform.system() != "Linux":
            return {"success": False, "error": "dmesg仅支持Linux系统"}

        # 构建无shell的命令列表
        cmd = ["dmesg", "--time-format=iso"]
        if level:
            cmd.extend(["-l", level])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}

            output = result.stdout.strip()
            log_lines = output.split("\n") if output else []
            # 取最后N行
            tailed = log_lines[-lines:] if lines > 0 else log_lines

            return {
                "success": True,
                "data": {
                    "command": " ".join(cmd),
                    "level_filter": level or "all",
                    "output_lines": len(tailed),
                    "output": "\n".join(tailed),
                }
            }
        except FileNotFoundError:
            return {"success": False, "error": "dmesg命令不存在"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "dmesg执行超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class IostatTool(ToolExecutor):
    """iostat - 磁盘I/O监控"""

    name = "iostat_disk_io"
    description = "使用iostat查看磁盘I/O性能指标，包括读写速率、IOPS、等待时间等。用于排查磁盘I/O瓶颈"
    category = "system"
    risk_level = "low"
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "采样次数",
                "default": 1
            },
            "interval": {
                "type": "integer",
                "description": "采样间隔(秒)",
                "default": 1
            }
        },
        "required": []
    }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        count = kwargs.get("count", 1)
        interval = kwargs.get("interval", 1)

        if platform.system() != "Linux":
            return {"success": False, "error": "iostat仅支持Linux系统"}

        cmd = ["iostat", "-xd", str(interval), str(count)]
        result = _run_cmd(cmd, timeout=30)

        if not result["success"]:
            # iostat不存在时尝试从/proc/diskstats获取
            try:
                with open("/proc/diskstats", "r") as f:
                    diskstats = f.read()
                return {
                    "success": True,
                    "data": {
                        "command": "cat /proc/diskstats (iostat不可用)",
                        "output": diskstats,
                        "note": "iostat未安装，使用/proc/diskstats替代"
                    }
                }
            except Exception:
                return result

        return {
            "success": True,
            "data": {
                "command": " ".join(cmd),
                "output": result["stdout"],
            }
        }


def get_lsof_executor():
    return LsofTool(None)

def get_netstat_executor():
    return NetstatTool(None)

def get_dmesg_executor():
    return DmesgTool(None)

def get_iostat_executor():
    return IostatTool(None)

# -*- coding: utf-8 -*-
"""
服务管理工具
管理系统服务的启停、状态查询等
"""

import subprocess
import platform
from typing import Dict, Any, List, Optional

from ..protocol import ToolExecutor, ToolDefinition, RiskLevel


class ServiceTool(ToolExecutor):
    """服务管理工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """根据参数执行不同的服务操作"""
        return await self._list_services(**kwargs)
    
    async def _list_services(self, **kwargs) -> Dict[str, Any]:
        """列出系统服务"""
        status_filter = kwargs.get("status", "all")
        
        try:
            if platform.system() == "Linux":
                return await self._list_services_linux(status_filter)
            else:
                return {"success": False, "error": "当前操作系统不支持服务管理"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _list_services_linux(self, status_filter: str) -> Dict[str, Any]:
        """在Linux上列出服务"""
        try:
            cmd = ["systemctl", "list-units", "--type=service", "--no-pager", "--plain"]
            
            if status_filter == "active":
                cmd.append("--state=active")
            elif status_filter == "inactive":
                cmd.append("--state=inactive")
            elif status_filter == "failed":
                cmd.append("--state=failed")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            services = []
            for line in result.stdout.strip().split('\n')[1:]:  # 跳过标题行
                parts = line.split()
                if len(parts) >= 4:
                    services.append({
                        "name": parts[0],
                        "load": parts[1],
                        "active": parts[2],
                        "sub": parts[3],
                        "description": " ".join(parts[4:]) if len(parts) > 4 else "",
                    })
            
            return {
                "success": True,
                "data": services
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "命令执行超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class ServiceStatusTool(ToolExecutor):
    """服务状态工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """获取服务状态"""
        service_name = kwargs.get("service_name")
        return await self._get_service_status(service_name)
    
    async def _get_service_status(self, service_name: str) -> Dict[str, Any]:
        """获取指定服务的详细状态"""
        try:
            if platform.system() == "Linux":
                return await self._get_service_status_linux(service_name)
            else:
                return {"success": False, "error": "当前操作系统不支持服务管理"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _get_service_status_linux(self, service_name: str) -> Dict[str, Any]:
        """在Linux上获取服务状态"""
        try:
            cmd = ["systemctl", "status", service_name, "--no-pager"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            # 解析状态信息
            status_info = {
                "name": service_name,
                "output": result.stdout,
                "returncode": result.returncode,
                "is_active": "active (running)" in result.stdout.lower(),
            }
            
            # 提取关键信息
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith("Loaded:"):
                    status_info["loaded"] = line.split(":", 1)[1].strip()
                elif line.startswith("Active:"):
                    status_info["active"] = line.split(":", 1)[1].strip()
                elif line.startswith("Main PID:"):
                    status_info["main_pid"] = line.split(":", 1)[1].strip()
                elif "Memory:" in line:
                    status_info["memory"] = line.split(":", 1)[1].strip()
                elif "CGroup:" in line:
                    status_info["cgroup"] = line.split(":", 1)[1].strip()
            
            return {
                "success": True,
                "data": status_info
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "命令执行超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class RestartServiceTool(ToolExecutor):
    """重启服务工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """重启服务"""
        service_name = kwargs.get("service_name")
        return await self._restart_service(service_name)
    
    async def _restart_service(self, service_name: str) -> Dict[str, Any]:
        """重启指定服务"""
        try:
            if platform.system() == "Linux":
                return await self._restart_service_linux(service_name)
            else:
                return {"success": False, "error": "当前操作系统不支持服务管理"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _restart_service_linux(self, service_name: str) -> Dict[str, Any]:
        """在Linux上重启服务"""
        try:
            cmd = ["sudo", "systemctl", "restart", service_name]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "data": {
                        "service_name": service_name,
                        "action": "restart",
                        "message": f"服务 {service_name} 已成功重启"
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"重启服务失败: {result.stderr}"
                }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "命令执行超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class StopServiceTool(ToolExecutor):
    """停止服务工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """停止服务"""
        service_name = kwargs.get("service_name")
        return await self._stop_service(service_name)
    
    async def _stop_service(self, service_name: str) -> Dict[str, Any]:
        """停止指定服务"""
        try:
            if platform.system() == "Linux":
                return await self._stop_service_linux(service_name)
            else:
                return {"success": False, "error": "当前操作系统不支持服务管理"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _stop_service_linux(self, service_name: str) -> Dict[str, Any]:
        """在Linux上停止服务"""
        try:
            cmd = ["sudo", "systemctl", "stop", service_name]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "data": {
                        "service_name": service_name,
                        "action": "stop",
                        "message": f"服务 {service_name} 已成功停止"
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"停止服务失败: {result.stderr}"
                }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "命令执行超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class SystemLogsTool(ToolExecutor):
    """系统日志工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """获取系统日志"""
        lines = kwargs.get("lines", 50)
        priority = kwargs.get("priority", "err")
        service = kwargs.get("service")
        return await self._get_system_logs(lines, priority, service)
    
    async def _get_system_logs(self, lines: int, priority: str, service: Optional[str]) -> Dict[str, Any]:
        """获取系统日志"""
        try:
            if platform.system() == "Linux":
                return await self._get_journal_logs(lines, priority, service)
            else:
                return {"success": False, "error": "当前操作系统不支持日志查询"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _get_journal_logs(self, lines: int, priority: str, service: Optional[str]) -> Dict[str, Any]:
        """使用journalctl获取日志"""
        try:
            cmd = ["journalctl", "--no-pager", "-n", str(lines), "-p", priority]
            
            if service:
                cmd.extend(["-u", service])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            logs = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    logs.append(line)
            
            return {
                "success": True,
                "data": {
                    "logs": logs,
                    "total": len(logs),
                    "priority": priority,
                    "service": service,
                }
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "命令执行超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}


def get_service_executor() -> ToolExecutor:
    """获取服务工具执行器"""
    return ServiceTool(None)

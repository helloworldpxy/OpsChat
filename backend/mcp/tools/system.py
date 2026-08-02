# -*- coding: utf-8 -*-
"""
系统信息工具
获取系统基本信息、磁盘、内存、CPU使用情况
"""

import os
import platform
import subprocess
import psutil
from typing import Dict, Any, Optional
from datetime import datetime

from ..protocol import ToolExecutor, ToolDefinition, RiskLevel


class SystemInfoTool(ToolExecutor):
    """系统信息工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """执行系统信息获取"""
        return await self._get_system_info()
    
    async def _get_system_info(self) -> Dict[str, Any]:
        """获取系统基本信息"""
        try:
            uname = platform.uname()
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            
            return {
                "success": True,
                "data": {
                    "hostname": uname.node,
                    "os": f"{uname.system} {uname.release}",
                    "version": uname.version,
                    "architecture": uname.machine,
                    "processor": uname.processor or "Unknown",
                    "python_version": platform.python_version(),
                    "boot_time": boot_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "uptime_seconds": int((datetime.now() - boot_time).total_seconds()),
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class DiskUsageTool(ToolExecutor):
    """磁盘使用情况工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """获取磁盘使用情况"""
        path = kwargs.get("path", "/")
        return await self._get_disk_usage(path)
    
    async def _get_disk_usage(self, path: str) -> Dict[str, Any]:
        """获取磁盘使用情况"""
        try:
            partitions = psutil.disk_partitions()
            result = []
            
            for partition in partitions:
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    result.append({
                        "device": partition.device,
                        "mountpoint": partition.mountpoint,
                        "fstype": partition.fstype,
                        "total_gb": round(usage.total / (1024**3), 2),
                        "used_gb": round(usage.used / (1024**3), 2),
                        "free_gb": round(usage.free / (1024**3), 2),
                        "percent": usage.percent,
                    })
                except PermissionError:
                    continue
            
            return {
                "success": True,
                "data": result
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class MemoryUsageTool(ToolExecutor):
    """内存使用情况工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """获取内存使用情况"""
        return await self._get_memory_usage()
    
    async def _get_memory_usage(self) -> Dict[str, Any]:
        """获取内存使用情况"""
        try:
            virtual_memory = psutil.virtual_memory()
            swap_memory = psutil.swap_memory()
            
            return {
                "success": True,
                "data": {
                    "virtual_memory": {
                        "total_gb": round(virtual_memory.total / (1024**3), 2),
                        "available_gb": round(virtual_memory.available / (1024**3), 2),
                        "used_gb": round(virtual_memory.used / (1024**3), 2),
                        "percent": virtual_memory.percent,
                    },
                    "swap_memory": {
                        "total_gb": round(swap_memory.total / (1024**3), 2),
                        "used_gb": round(swap_memory.used / (1024**3), 2),
                        "free_gb": round(swap_memory.free / (1024**3), 2),
                        "percent": swap_memory.percent,
                    }
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class CPUUsageTool(ToolExecutor):
    """CPU使用情况工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """获取CPU使用情况"""
        return await self._get_cpu_usage()
    
    async def _get_cpu_usage(self) -> Dict[str, Any]:
        """获取CPU使用情况"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
            cpu_count = psutil.cpu_count()
            cpu_count_logical = psutil.cpu_count(logical=True)
            cpu_freq = psutil.cpu_freq()
            load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else None
            
            return {
                "success": True,
                "data": {
                    "physical_cores": cpu_count,
                    "logical_cores": cpu_count_logical,
                    "usage_per_core": cpu_percent,
                    "average_usage": sum(cpu_percent) / len(cpu_percent) if cpu_percent else 0,
                    "frequency": {
                        "current_mhz": cpu_freq.current if cpu_freq else None,
                        "min_mhz": cpu_freq.min if cpu_freq else None,
                        "max_mhz": cpu_freq.max if cpu_freq else None,
                    },
                    "load_average": {
                        "1min": load_avg[0] if load_avg else None,
                        "5min": load_avg[1] if load_avg else None,
                        "15min": load_avg[2] if load_avg else None,
                    } if load_avg else None,
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


def get_system_info_executor() -> ToolExecutor:
    """获取系统信息工具执行器"""
    return SystemInfoTool(None)


def get_disk_usage_executor() -> ToolExecutor:
    """获取磁盘使用情况工具执行器"""
    return DiskUsageTool(None)


def get_memory_usage_executor() -> ToolExecutor:
    """获取内存使用情况工具执行器"""
    return MemoryUsageTool(None)


def get_cpu_usage_executor() -> ToolExecutor:
    """获取CPU使用情况工具执行器"""
    return CPUUsageTool(None)

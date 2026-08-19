# -*- coding: utf-8 -*-
"""
进程工具
获取进程列表、进程详情、终止进程等
"""

import os
import signal
import psutil
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..protocol import ToolExecutor, ToolDefinition, RiskLevel


class ProcessTool(ToolExecutor):
    """进程工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """根据参数执行不同的进程操作"""
        return await self._get_process_list(**kwargs)
    
    async def _get_process_list(self, **kwargs) -> Dict[str, Any]:
        """获取进程列表"""
        limit = kwargs.get("limit", 20)
        sort_by = kwargs.get("sort_by", "cpu")
        
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'status', 'create_time']):
                try:
                    pinfo = proc.info
                    processes.append({
                        "pid": pinfo['pid'],
                        "name": pinfo['name'],
                        "username": pinfo['username'],
                        "cpu_percent": pinfo['cpu_percent'],
                        "memory_percent": round(pinfo['memory_percent'], 2),
                        "status": pinfo['status'],
                        "create_time": datetime.fromtimestamp(pinfo['create_time']).strftime("%Y-%m-%d %H:%M:%S") if pinfo['create_time'] else None,
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            # 排序
            sort_key_map = {
                "cpu": lambda x: x.get('cpu_percent', 0) or 0,
                "memory": lambda x: x.get('memory_percent', 0) or 0,
                "pid": lambda x: x.get('pid', 0),
                "name": lambda x: x.get('name', ''),
            }
            sort_func = sort_key_map.get(sort_by, sort_key_map['cpu'])
            processes.sort(key=sort_func, reverse=(sort_by != 'pid' and sort_by != 'name'))
            
            return {
                "success": True,
                "data": processes[:limit],
                "total": len(processes)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class ProcessDetailTool(ToolExecutor):
    """进程详情工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """获取进程详情"""
        pid = kwargs.get("pid")
        return await self._get_process_detail(pid)
    
    async def _get_process_detail(self, pid: int) -> Dict[str, Any]:
        """获取指定进程的详细信息"""
        try:
            proc = psutil.Process(pid)
            
            with proc.oneshot():
                info = {
                    "pid": proc.pid,
                    "name": proc.name(),
                    "exe": proc.exe() if proc.exe() else None,
                    "cwd": proc.cwd() if proc.cwd() else None,
                    "cmdline": proc.cmdline(),
                    "status": proc.status(),
                    "username": proc.username(),
                    "create_time": datetime.fromtimestamp(proc.create_time()).strftime("%Y-%m-%d %H:%M:%S"),
                    "cpu_percent": proc.cpu_percent(),
                    "memory_percent": round(proc.memory_percent(), 2),
                    "memory_info": {
                        "rss": proc.memory_info().rss,
                        "vms": proc.memory_info().vms,
                    },
                    "num_threads": proc.num_threads(),
                    "nice": proc.nice(),
                }
                
                # 获取父进程信息
                try:
                    parent = proc.parent()
                    if parent:
                        info["parent_pid"] = parent.pid
                        info["parent_name"] = parent.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    info["parent_pid"] = None
                
                # 获取子进程
                try:
                    children = proc.children()
                    info["children"] = [{"pid": c.pid, "name": c.name()} for c in children]
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    info["children"] = []
            
            return {
                "success": True,
                "data": info
            }
        except psutil.NoSuchProcess:
            return {"success": False, "error": f"进程不存在: PID {pid}"}
        except psutil.AccessDenied:
            return {"success": False, "error": f"权限不足，无法访问进程: PID {pid}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class KillProcessTool(ToolExecutor):
    """终止进程工具 (高危操作)"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """终止进程"""
        pid = kwargs.get("pid")
        sig = kwargs.get("signal", "SIGTERM")
        return await self._kill_process(pid, sig)
    
    async def _kill_process(self, pid: int, signal_name: str) -> Dict[str, Any]:
        """终止指定进程"""
        try:
            proc = psutil.Process(pid)
            proc_name = proc.name()
            
            # 信号映射
            signal_map = {
                "SIGTERM": signal.SIGTERM,
                "SIGKILL": signal.SIGKILL,
                "SIGINT": signal.SIGINT,
            }
            
            sig = signal_map.get(signal_name, signal.SIGTERM)
            
            # 发送信号
            proc.send_signal(sig)
            
            return {
                "success": True,
                "data": {
                    "pid": pid,
                    "process_name": proc_name,
                    "signal": signal_name,
                    "message": f"已向进程 {proc_name} (PID: {pid}) 发送 {signal_name} 信号"
                }
            }
        except psutil.NoSuchProcess:
            return {"success": False, "error": f"进程不存在: PID {pid}"}
        except psutil.AccessDenied:
            return {"success": False, "error": f"权限不足，无法终止进程: PID {pid}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class ZombieDetectorTool(ToolExecutor):
    """僵尸进程检测工具"""

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """检测并报告僵尸进程"""
        try:
            zombies = []
            for proc in psutil.process_iter(['pid', 'name', 'ppid', 'status', 'create_time']):
                try:
                    if proc.info['status'] == psutil.STATUS_ZOMBIE:
                        parent_name = None
                        try:
                            parent = psutil.Process(proc.info['ppid'])
                            parent_name = parent.name()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                        zombies.append({
                            "pid": proc.info['pid'],
                            "name": proc.info['name'],
                            "ppid": proc.info['ppid'],
                            "parent_name": parent_name,
                            "create_time": datetime.fromtimestamp(
                                proc.info['create_time']
                            ).strftime("%Y-%m-%d %H:%M:%S") if proc.info['create_time'] else None,
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # 分析建议
            suggestions = []
            if zombies:
                parent_pids = set(z['ppid'] for z in zombies if z['ppid'])
                suggestions.append(f"发现 {len(zombies)} 个僵尸进程，涉及 {len(parent_pids)} 个父进程")
                for ppid in list(parent_pids)[:5]:
                    parent_zombies = [z for z in zombies if z['ppid'] == ppid]
                    pname = parent_zombies[0].get('parent_name', 'unknown')
                    suggestions.append(f"父进程 {pname}(PID:{ppid}) 有 {len(parent_zombies)} 个僵尸子进程，建议重启该父进程")
            else:
                suggestions.append("系统中没有僵尸进程，状态良好")

            return {
                "success": True,
                "data": {
                    "zombie_count": len(zombies),
                    "zombies": zombies,
                    "suggestions": suggestions,
                    "has_zombies": len(zombies) > 0,
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


def get_process_executor() -> ToolExecutor:
    """获取进程工具执行器"""
    return ProcessTool(None)


def get_zombie_detector_executor() -> ToolExecutor:
    """获取僵尸进程检测器执行器"""
    return ZombieDetectorTool(None)

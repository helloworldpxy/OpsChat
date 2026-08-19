# -*- coding: utf-8 -*-
"""
网络工具
获取网络状态、连接信息、ping测试等
"""

import socket
import subprocess
import psutil
import platform
from typing import Dict, Any, List, Optional

from ..protocol import ToolExecutor, ToolDefinition, RiskLevel


class NetworkTool(ToolExecutor):
    """网络工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """根据参数执行不同的网络操作"""
        return await self._get_network_status()
    
    async def _get_network_status(self) -> Dict[str, Any]:
        """获取网络接口状态"""
        try:
            interfaces = []
            for name, addrs in psutil.net_if_addrs().items():
                stats = psutil.net_if_stats().get(name)
                interface_info = {
                    "name": name,
                    "addresses": [],
                    "is_up": stats.isup if stats else False,
                    "speed_mbps": stats.speed if stats else 0,
                }
                
                for addr in addrs:
                    addr_info = {
                        "family": str(addr.family),
                        "address": addr.address,
                        "netmask": addr.netmask,
                        "broadcast": addr.broadcast,
                    }
                    interface_info["addresses"].append(addr_info)
                
                interfaces.append(interface_info)
            
            # 获取IO计数器
            io_counters = psutil.net_io_counters()
            
            return {
                "success": True,
                "data": {
                    "interfaces": interfaces,
                    "io_counters": {
                        "bytes_sent": io_counters.bytes_sent,
                        "bytes_recv": io_counters.bytes_recv,
                        "packets_sent": io_counters.packets_sent,
                        "packets_recv": io_counters.packets_recv,
                        "errin": io_counters.errin,
                        "errout": io_counters.errout,
                        "dropin": io_counters.dropin,
                        "dropout": io_counters.dropout,
                    }
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class NetworkConnectionTool(ToolExecutor):
    """网络连接工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """获取网络连接"""
        protocol_filter = kwargs.get("protocol", "all")
        return await self._get_network_connections(protocol_filter)
    
    async def _get_network_connections(self, protocol_filter: str) -> Dict[str, Any]:
        """获取网络连接列表"""
        try:
            connections = psutil.net_connections()
            result = []
            
            for conn in connections:
                # 协议过滤
                if protocol_filter != "all":
                    if protocol_filter == "tcp" and conn.type != socket.SOCK_STREAM:
                        continue
                    if protocol_filter == "udp" and conn.type != socket.SOCK_DGRAM:
                        continue
                
                conn_info = {
                    "fd": conn.fd,
                    "family": str(conn.family),
                    "type": str(conn.type),
                    "laddr": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else None,
                    "raddr": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else None,
                    "status": conn.status,
                    "pid": conn.pid,
                }
                result.append(conn_info)
            
            return {
                "success": True,
                "data": result
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class PingTool(ToolExecutor):
    """Ping工具"""
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """Ping指定主机"""
        host = kwargs.get("host")
        count = kwargs.get("count", 4)
        return await self._ping_host(host, count)
    
    async def _ping_host(self, host: str, count: int) -> Dict[str, Any]:
        """Ping指定主机"""
        try:
            # 根据操作系统选择ping命令
            param = "-n" if platform.system().lower() == "windows" else "-c"
            command = ["ping", param, str(count), host]
            
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return {
                "success": True,
                "data": {
                    "host": host,
                    "reachable": result.returncode == 0,
                    "output": result.stdout,
                    "error": result.stderr if result.returncode != 0 else None,
                }
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Ping超时: {host}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


def get_network_executor() -> ToolExecutor:
    """获取网络工具执行器（兼容，实际使用各独立工具类）"""
    return NetworkTool(None)

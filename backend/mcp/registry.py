# -*- coding: utf-8 -*-
"""
工具注册中心
管理所有MCP工具的注册和初始化
"""

import json
import logging
from typing import Dict, List, Optional, Any

from .protocol import (
    MCPProtocol, 
    ToolDefinition, 
    ToolExecutor, 
    RiskLevel,
    mcp_protocol
)
from .tools.system import (
    SystemInfoTool, get_system_info_executor,
    get_disk_usage_executor, get_memory_usage_executor, get_cpu_usage_executor,
)
from .tools.network import NetworkTool, NetworkConnectionTool, PingTool
from .tools.process import ProcessTool, ProcessDetailTool, KillProcessTool, get_zombie_detector_executor
from .tools.service import ServiceTool, ServiceStatusTool, RestartServiceTool, StopServiceTool, SystemLogsTool
from .tools.file import DeleteFileTool, ChmodTool, ConfigDriftTool
from .tools.native import get_lsof_executor, get_netstat_executor, get_dmesg_executor, get_iostat_executor

logger = logging.getLogger(__name__)


class DiagnoseSystemTool(ToolExecutor):
    """系统全面诊断工具（集成根因分析）"""

    def __init__(self, definition, protocol: MCPProtocol = None):
        super().__init__(definition)
        self.protocol = protocol

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """执行全面系统诊断"""
        from ..core.root_cause import root_cause_analyzer
        from .protocol import MCPRequest

        protocol = self.protocol or mcp_protocol

        async def call_tool(name, **params):
            try:
                req = MCPRequest(tool_name=name, parameters=params)
                resp = await protocol.execute_tool(req)
                if resp.success and resp.result:
                    return resp.result
                return None
            except Exception as e:
                logger.warning(f"诊断工具 {name} 调用失败: {e}")
                return None

        tools = {
            "get_cpu_usage": lambda **kw: call_tool("get_cpu_usage", **kw),
            "get_memory_usage": lambda **kw: call_tool("get_memory_usage", **kw),
            "get_disk_usage": lambda **kw: call_tool("get_disk_usage", **kw),
            "get_process_list": lambda **kw: call_tool("get_process_list", **kw),
            "get_system_logs": lambda **kw: call_tool("get_system_logs", **kw),
            "get_network_connections": lambda **kw: call_tool("get_network_connections", **kw),
        }

        try:
            return await root_cause_analyzer.run_full_diagnosis(tools)
        except Exception as e:
            logger.error(f"系统诊断执行失败: {e}")
            return {
                "success": True,
                "data": {
                    "health_score": 0,
                    "health_level": "未知",
                    "summary": {"total_anomalies": 0, "critical": 0, "warning": 0},
                    "anomalies": [],
                    "root_causes": [],
                    "recommendations": [f"诊断过程中出现错误: {str(e)}，请尝试单独使用各项检查工具"],
                }
            }


class ToolRegistry:
    """工具注册中心"""
    
    def __init__(self):
        self.protocol = mcp_protocol
        self._initialized = False
    
    def initialize(self):
        """初始化并注册所有工具"""
        if self._initialized:
            return
        
        logger.info("开始注册MCP工具...")
        
        # 注册系统信息工具
        self._register_system_tools()
        
        # 注册网络工具
        self._register_network_tools()
        
        # 注册进程工具
        self._register_process_tools()
        
        # 注册服务管理工具
        self._register_service_tools()
        
        # 注册文件操作工具
        self._register_file_tools()
        
        # 注册智能诊断工具
        self._register_diagnosis_tools()
        
        # 注册原生命令工具
        self._register_native_tools()
        
        self._initialized = True
        logger.info(f"MCP工具注册完成，共注册 {len(self.protocol.tools)} 个工具")
    
    def _register_system_tools(self):
        """注册系统信息工具"""
        # get_system_info - 获取系统信息
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="get_system_info",
                description="获取系统基本信息，包括操作系统版本、内核版本、主机名等",
                category="system",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=get_system_info_executor()
        )
        
        # get_disk_usage - 获取磁盘使用情况
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="get_disk_usage",
                description="获取磁盘使用情况，包括各分区的总容量、已用空间、可用空间和使用率",
                category="system",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "指定路径，默认为根目录",
                            "default": "/"
                        }
                    },
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=get_disk_usage_executor()
        )
        
        # get_memory_usage - 获取内存使用情况
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="get_memory_usage",
                description="获取内存使用情况，包括总内存、已用内存、可用内存和使用率",
                category="system",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=get_memory_usage_executor()
        )
        
        # get_cpu_usage - 获取CPU使用情况
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="get_cpu_usage",
                description="获取CPU使用情况，包括CPU核心数、使用率、负载等信息",
                category="system",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=get_cpu_usage_executor()
        )
    
    def _register_network_tools(self):
        """注册网络工具"""
        # get_network_status - 获取网络状态
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="get_network_status",
                description="获取网络接口状态和连接信息",
                category="network",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=NetworkTool(None)
        )
        
        # get_network_connections - 获取网络连接
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="get_network_connections",
                description="获取当前网络连接列表，包括TCP/UDP连接信息",
                category="network",
                parameters={
                    "type": "object",
                    "properties": {
                        "protocol": {
                            "type": "string",
                            "description": "协议类型过滤: tcp/udp/all",
                            "default": "all"
                        }
                    },
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=NetworkConnectionTool(None)
        )
        
        # ping_host - ping指定主机
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="ping_host",
                description="Ping指定主机，检测网络连通性",
                category="network",
                parameters={
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "description": "目标主机地址"
                        },
                        "count": {
                            "type": "integer",
                            "description": "ping次数",
                            "default": 4
                        }
                    },
                    "required": ["host"]
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=PingTool(None)
        )
    
    def _register_process_tools(self):
        """注册进程工具"""
        # get_process_list - 获取进程列表
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="get_process_list",
                description="获取当前运行的进程列表，包括PID、名称、CPU和内存使用率",
                category="process",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "返回的进程数量限制",
                            "default": 20
                        },
                        "sort_by": {
                            "type": "string",
                            "description": "排序字段: cpu/memory/pid/name",
                            "default": "cpu"
                        }
                    },
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=ProcessTool(None)
        )
        
        # get_process_detail - 获取进程详情
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="get_process_detail",
                description="获取指定进程的详细信息",
                category="process",
                parameters={
                    "type": "object",
                    "properties": {
                        "pid": {
                            "type": "integer",
                            "description": "进程PID"
                        }
                    },
                    "required": ["pid"]
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=ProcessDetailTool(None)
        )
        
        # kill_process - 终止进程 (高危操作)
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="kill_process",
                description="终止指定进程。这是一个高危操作，需要用户确认",
                category="process",
                parameters={
                    "type": "object",
                    "properties": {
                        "pid": {
                            "type": "integer",
                            "description": "进程PID"
                        },
                        "signal": {
                            "type": "string",
                            "description": "信号类型: SIGTERM(优雅终止)/SIGKILL(强制终止)",
                            "default": "SIGTERM"
                        }
                    },
                    "required": ["pid"]
                },
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
            ),
            executor=KillProcessTool(None)
        )
    
    def _register_service_tools(self):
        """注册服务管理工具"""
        # list_services - 列出服务
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="list_services",
                description="列出系统服务及其状态",
                category="service",
                parameters={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "按状态过滤: active/inactive/failed/all",
                            "default": "all"
                        }
                    },
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=ServiceTool(None)
        )
        
        # get_service_status - 获取服务状态
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="get_service_status",
                description="获取指定服务的详细状态信息",
                category="service",
                parameters={
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "服务名称"
                        }
                    },
                    "required": ["service_name"]
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=ServiceStatusTool(None)
        )
        
        # restart_service - 重启服务 (中等风险)
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="restart_service",
                description="重启指定服务。需要用户确认",
                category="service",
                parameters={
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "服务名称"
                        }
                    },
                    "required": ["service_name"]
                },
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
            ),
            executor=RestartServiceTool(None)
        )
        
        # stop_service - 停止服务 (中等风险)
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="stop_service",
                description="停止指定服务。需要用户确认",
                category="service",
                parameters={
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "服务名称"
                        }
                    },
                    "required": ["service_name"]
                },
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
            ),
            executor=StopServiceTool(None)
        )
        
        # get_system_logs - 获取系统日志
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="get_system_logs",
                description="获取系统日志，支持按优先级和服务过滤",
                category="service",
                parameters={
                    "type": "object",
                    "properties": {
                        "lines": {
                            "type": "integer",
                            "description": "返回的日志行数",
                            "default": 50
                        },
                        "priority": {
                            "type": "string",
                            "description": "日志优先级: emerg/alert/crit/err/warning/notice/info/debug",
                            "default": "err"
                        },
                        "service": {
                            "type": "string",
                            "description": "按服务名过滤"
                        }
                    },
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=SystemLogsTool(None)
        )
    
    def _register_file_tools(self):
        """注册文件操作工具"""
        # delete_file - 删除文件 (高危操作)
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="delete_file",
                description="删除指定文件或目录。这是一个高危操作，需要用户确认",
                category="file",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "要删除的文件或目录路径"
                        },
                        "recursive": {
                            "type": "boolean",
                            "description": "是否递归删除目录",
                            "default": False
                        }
                    },
                    "required": ["path"]
                },
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
            ),
            executor=DeleteFileTool(None)
        )
        
        # chmod - 修改权限 (高危操作)
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="chmod",
                description="修改文件或目录的权限。这是一个高危操作，需要用户确认",
                category="file",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "文件或目录路径"
                        },
                        "mode": {
                            "type": "string",
                            "description": "权限模式(八进制)，如 644, 755, 777"
                        }
                    },
                    "required": ["path", "mode"]
                },
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
            ),
            executor=ChmodTool(None)
        )
        
        # config_drift_check - 配置文件漂移检测
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="config_drift_check",
                description="检测关键配置文件是否被意外修改。可生成快照基线或与已有基线对比",
                category="file",
                parameters={
                    "type": "object",
                    "properties": {
                        "baseline": {
                            "type": "string",
                            "description": "基线文件路径（不提供则生成新快照）",
                            "default": ""
                        },
                        "config_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要检测的配置文件列表（不提供则使用默认列表）"
                        }
                    },
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=ConfigDriftTool(None)
        )
    
    def _register_diagnosis_tools(self):
        """注册智能诊断工具"""
        # diagnose_system - 系统全面诊断（集成根因分析）
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="diagnose_system",
                description="执行全面系统健康诊断：自动检测CPU、内存、磁盘、进程、日志、网络等异常，进行关联分析和根因推断，给出修复建议。当用户要求系统诊断、健康检查时使用",
                category="diagnosis",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=DiagnoseSystemTool(None, self.protocol)
        )
    
    def _register_native_tools(self):
        """注册原生Linux命令工具"""
        # lsof - 端口/文件占用查询
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="lsof_ports",
                description="使用lsof查看端口占用或文件打开情况。可查看指定端口被哪个进程占用",
                category="system",
                parameters={
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
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=get_lsof_executor()
        )
        
        # netstat - 网络连接状态
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="netstat_connections",
                description="使用netstat查看网络连接、监听端口、路由表等网络状态信息",
                category="network",
                parameters={
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "description": "查看模式: listening(监听端口), connections(所有连接), routing(路由表), stats(统计)",
                            "default": "listening"
                        }
                    },
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=get_netstat_executor()
        )
        
        # dmesg - 内核日志
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="dmesg_kernel_log",
                description="使用dmesg查看内核日志，可按优先级过滤。用于排查硬件错误、OOM、驱动问题等",
                category="system",
                parameters={
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "string",
                            "description": "日志级别过滤: emerg/alert/crit/err/warning/notice/info/debug",
                            "default": ""
                        },
                        "lines": {
                            "type": "integer",
                            "description": "显示最后N行",
                            "default": 50
                        }
                    },
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=get_dmesg_executor()
        )
        
        # iostat - 磁盘I/O监控
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="iostat_disk_io",
                description="使用iostat查看磁盘I/O性能指标，包括读写速率、IOPS、等待时间等。用于排查磁盘I/O瓶颈",
                category="system",
                parameters={
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
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=get_iostat_executor()
        )
        
        # detect_zombies - 僵尸进程检测
        self.protocol.register_tool(
            definition=ToolDefinition(
                name="detect_zombies",
                description="检测系统中的僵尸进程，报告其PID、父进程信息，并给出清理建议",
                category="process",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            executor=get_zombie_detector_executor()
        )
    
    def get_protocol(self) -> MCPProtocol:
        """获取MCP协议实例"""
        return self.protocol
    
    def get_all_tools(self) -> List[ToolDefinition]:
        """获取所有注册的工具"""
        return self.protocol.get_all_tools()
    
    def get_llm_tools(self) -> List[dict]:
        """获取LLM可调用的工具列表"""
        return self.protocol.get_llm_tools()


# 全局工具注册中心实例
tool_registry = ToolRegistry()

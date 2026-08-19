# -*- coding: utf-8 -*-
"""
智能根因分析模块
实现异常检测 -> 关联分析 -> 根因推断 -> 修复建议
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Anomaly:
    """异常事件"""
    category: str       # cpu / memory / disk / process / network / log
    severity: str       # critical / warning / info
    title: str
    detail: str
    value: Any = None
    threshold: Any = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class RootCause:
    """根因分析结果"""
    anomaly: Anomaly
    probable_causes: List[str]
    related_evidence: List[Dict[str, Any]]
    fix_suggestions: List[str]
    confidence: str  # high / medium / low


class RootCauseAnalyzer:
    """
    智能根因分析器
    通过规则引擎和关联分析，定位系统异常的根本原因
    """

    # 阈值配置
    THRESHOLDS = {
        "cpu_high": 85.0,
        "cpu_critical": 95.0,
        "memory_high": 80.0,
        "memory_critical": 95.0,
        "disk_high": 85.0,
        "disk_critical": 95.0,
        "load_per_cpu_high": 2.0,
        "zombie_process_warn": 5,
        "log_error_rate_high": 10,   # 每分钟错误日志条数
    }

    async def run_full_diagnosis(self, tools: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行全面系统诊断
        tools: 工具执行器字典 {tool_name: execute_func}
        """
        anomalies: List[Anomaly] = []
        evidence: List[Dict[str, Any]] = []

        # 1. 收集数据
        cpu_data = await self._safe_call(tools, "get_cpu_usage")
        mem_data = await self._safe_call(tools, "get_memory_usage")
        disk_data = await self._safe_call(tools, "get_disk_usage")
        proc_data = await self._safe_call(tools, "get_process_list", limit=50, sort_by="cpu")
        log_data = await self._safe_call(tools, "get_system_logs", lines=100, priority="err")
        net_data = await self._safe_call(tools, "get_network_connections")

        # 2. 检测异常
        anomalies.extend(self._check_cpu(cpu_data, proc_data))
        anomalies.extend(self._check_memory(mem_data, proc_data))
        anomalies.extend(self._check_disk(disk_data))
        anomalies.extend(self._check_processes(proc_data))
        anomalies.extend(self._check_logs(log_data))
        anomalies.extend(self._check_network(net_data))

        # 3. 根因分析
        root_causes = self._analyze_root_causes(anomalies, {
            "cpu": cpu_data,
            "memory": mem_data,
            "disk": disk_data,
            "process": proc_data,
            "log": log_data,
            "network": net_data,
        })

        # 4. 生成报告
        report = self._generate_report(anomalies, root_causes)

        return {
            "success": True,
            "data": report
        }

    async def _safe_call(self, tools: Dict, name: str, **kwargs) -> Optional[Dict]:
        """安全调用工具，失败返回None"""
        try:
            if name in tools:
                return await tools[name](**kwargs)
        except Exception as e:
            logger.warning(f"诊断数据采集失败 [{name}]: {e}")
        return None

    def _check_cpu(self, cpu_data: Optional[Dict], proc_data: Optional[Dict]) -> List[Anomaly]:
        """检查CPU异常"""
        anomalies = []
        if not cpu_data or not cpu_data.get("success"):
            return anomalies

        data = cpu_data.get("data", {})
        avg_usage = data.get("average_usage", 0)

        if avg_usage >= self.THRESHOLDS["cpu_critical"]:
            anomalies.append(Anomaly(
                category="cpu",
                severity="critical",
                title="CPU使用率严重过高",
                detail=f"平均CPU使用率 {avg_usage:.1f}%",
                value=avg_usage,
                threshold=self.THRESHOLDS["cpu_critical"]
            ))
        elif avg_usage >= self.THRESHOLDS["cpu_high"]:
            anomalies.append(Anomaly(
                category="cpu",
                severity="warning",
                title="CPU使用率偏高",
                detail=f"平均CPU使用率 {avg_usage:.1f}%",
                value=avg_usage,
                threshold=self.THRESHOLDS["cpu_high"]
            ))

        # 检查负载
        load_avg = data.get("load_average", {})
        if load_avg:
            cpu_count = data.get("logical_cores", 1) or 1
            load_1min = load_avg.get("1min", 0) or 0
            per_cpu = load_1min / cpu_count
            if per_cpu > self.THRESHOLDS["load_per_cpu_high"]:
                anomalies.append(Anomaly(
                    category="cpu",
                    severity="warning",
                    title="系统负载过高",
                    detail=f"1分钟负载 {load_1min:.2f}，每CPU负载 {per_cpu:.2f}",
                    value=per_cpu,
                    threshold=self.THRESHOLDS["load_per_cpu_high"]
                ))

        return anomalies

    def _check_memory(self, mem_data: Optional[Dict], proc_data: Optional[Dict]) -> List[Anomaly]:
        """检查内存异常"""
        anomalies = []
        if not mem_data or not mem_data.get("success"):
            return anomalies

        data = mem_data.get("data", {})
        vm = data.get("virtual_memory", {})
        percent = vm.get("percent", 0)

        if percent >= self.THRESHOLDS["memory_critical"]:
            anomalies.append(Anomaly(
                category="memory",
                severity="critical",
                title="内存使用率严重过高",
                detail=f"内存使用率 {percent}%，可用 {vm.get('available_gb', 0)}GB",
                value=percent,
                threshold=self.THRESHOLDS["memory_critical"]
            ))
        elif percent >= self.THRESHOLDS["memory_high"]:
            anomalies.append(Anomaly(
                category="memory",
                severity="warning",
                title="内存使用率偏高",
                detail=f"内存使用率 {percent}%",
                value=percent,
                threshold=self.THRESHOLDS["memory_high"]
            ))

        # 检查swap
        swap = data.get("swap_memory", {})
        if swap and swap.get("percent", 0) > 50:
            anomalies.append(Anomaly(
                category="memory",
                severity="warning",
                title="Swap使用率偏高",
                detail=f"Swap使用率 {swap['percent']}%",
                value=swap["percent"],
                threshold=50
            ))

        return anomalies

    def _check_disk(self, disk_data: Optional[Dict]) -> List[Anomaly]:
        """检查磁盘异常"""
        anomalies = []
        if not disk_data or not disk_data.get("success"):
            return anomalies

        for partition in disk_data.get("data", []):
            percent = partition.get("percent", 0)
            mount = partition.get("mountpoint", "")

            if percent >= self.THRESHOLDS["disk_critical"]:
                anomalies.append(Anomaly(
                    category="disk",
                    severity="critical",
                    title=f"磁盘空间严重不足: {mount}",
                    detail=f"{mount} 使用率 {percent}%，剩余 {partition.get('free_gb', 0)}GB",
                    value=percent,
                    threshold=self.THRESHOLDS["disk_critical"]
                ))
            elif percent >= self.THRESHOLDS["disk_high"]:
                anomalies.append(Anomaly(
                    category="disk",
                    severity="warning",
                    title=f"磁盘空间偏高: {mount}",
                    detail=f"{mount} 使用率 {percent}%",
                    value=percent,
                    threshold=self.THRESHOLDS["disk_high"]
                ))

        return anomalies

    def _check_processes(self, proc_data: Optional[Dict]) -> List[Anomaly]:
        """检查进程异常"""
        anomalies = []
        if not proc_data or not proc_data.get("success"):
            return anomalies

        procs = proc_data.get("data", [])

        # 检查僵尸进程
        zombies = [p for p in procs if p.get("status") == "zombie"]
        if len(zombies) >= self.THRESHOLDS["zombie_process_warn"]:
            anomalies.append(Anomaly(
                category="process",
                severity="warning",
                title=f"存在 {len(zombies)} 个僵尸进程",
                detail=", ".join([f"{p['name']}(PID:{p['pid']})" for p in zombies[:5]]),
                value=len(zombies),
                threshold=self.THRESHOLDS["zombie_process_warn"]
            ))

        # 检查单进程CPU占用过高
        for p in procs[:5]:
            cpu_pct = p.get("cpu_percent", 0) or 0
            if cpu_pct > 50:
                anomalies.append(Anomaly(
                    category="process",
                    severity="warning",
                    title=f"进程CPU占用过高: {p.get('name', '?')}",
                    detail=f"PID {p['pid']} CPU {cpu_pct}%, 用户 {p.get('username', '?')}",
                    value=cpu_pct,
                    threshold=50
                ))

        # 检查单进程内存占用过高
        for p in procs[:10]:
            mem_pct = p.get("memory_percent", 0) or 0
            if mem_pct > 30:
                anomalies.append(Anomaly(
                    category="process",
                    severity="warning",
                    title=f"进程内存占用过高: {p.get('name', '?')}",
                    detail=f"PID {p['pid']} 内存 {mem_pct}%",
                    value=mem_pct,
                    threshold=30
                ))

        return anomalies

    def _check_logs(self, log_data: Optional[Dict]) -> List[Anomaly]:
        """检查日志异常"""
        anomalies = []
        if not log_data or not log_data.get("success"):
            return anomalies

        data = log_data.get("data", {})
        logs = data.get("logs", [])
        total = data.get("total", 0)

        if total > self.THRESHOLDS["log_error_rate_high"]:
            anomalies.append(Anomaly(
                category="log",
                severity="warning",
                title=f"错误日志数量较多",
                detail=f"最近获取到 {total} 条错误级别日志",
                value=total,
                threshold=self.THRESHOLDS["log_error_rate_high"]
            ))

        # 分析日志关键词
        oom_count = sum(1 for l in logs if "oom" in l.lower() or "out of memory" in l.lower())
        if oom_count > 0:
            anomalies.append(Anomaly(
                category="log",
                severity="critical",
                title="检测到OOM(内存溢出)事件",
                detail=f"发现 {oom_count} 条OOM相关日志",
                value=oom_count,
                threshold=1
            ))

        disk_error_count = sum(1 for l in logs if "i/o error" in l.lower() or "disk" in l.lower())
        if disk_error_count > 0:
            anomalies.append(Anomaly(
                category="log",
                severity="critical",
                title="检测到磁盘I/O错误",
                detail=f"发现 {disk_error_count} 条磁盘错误日志",
                value=disk_error_count,
                threshold=1
            ))

        return anomalies

    def _check_network(self, net_data: Optional[Dict]) -> List[Anomaly]:
        """检查网络异常"""
        anomalies = []
        if not net_data or not net_data.get("success"):
            return anomalies

        data = net_data.get("data", {})
        counters = data.get("io_counters", {})

        errin = counters.get("errin", 0)
        errout = counters.get("errout", 0)
        dropin = counters.get("dropin", 0)
        dropout = counters.get("dropout", 0)

        if errin + errout > 100:
            anomalies.append(Anomaly(
                category="network",
                severity="warning",
                title="网络错误包数量偏高",
                detail=f"入站错误 {errin}，出站错误 {errout}",
                value=errin + errout,
                threshold=100
            ))

        if dropin + dropout > 100:
            anomalies.append(Anomaly(
                category="network",
                severity="warning",
                title="网络丢包数量偏高",
                detail=f"入站丢包 {dropin}，出站丢包 {dropout}",
                value=dropin + dropout,
                threshold=100
            ))

        return anomalies

    def _analyze_root_causes(self, anomalies: List[Anomaly], all_data: Dict) -> List[RootCause]:
        """关联分析 + 根因推断"""
        root_causes = []

        for anomaly in anomalies:
            causes = []
            evidence_list = []
            suggestions = []
            confidence = "medium"

            if anomaly.category == "cpu":
                # CPU高 -> 找哪个进程导致
                procs = (all_data.get("process") or {}).get("data", [])
                top_cpu_procs = [p for p in procs if (p.get("cpu_percent") or 0) > 20]
                if top_cpu_procs:
                    proc_desc = ", ".join([p["name"] + "(" + str(p["cpu_percent"]) + "%)" for p in top_cpu_procs[:3]])
                    causes.append("高CPU进程: " + proc_desc)
                    evidence_list.append({"type": "process", "data": top_cpu_procs[:3]})
                else:
                    causes.append("可能是大量短时进程导致的CPU瞬时飙升")
                suggestions.append("使用 top/htop 查看具体进程CPU占用")
                suggestions.append("检查是否有异常进程需要终止")

            elif anomaly.category == "memory":
                procs = (all_data.get("process") or {}).get("data", [])
                top_mem_procs = [p for p in procs if (p.get("memory_percent") or 0) > 10]
                if top_mem_procs:
                    mem_desc = ", ".join([p["name"] + "(" + str(p["memory_percent"]) + "%)" for p in top_mem_procs[:3]])
                    causes.append("高内存进程: " + mem_desc)
                    evidence_list.append({"type": "process", "data": top_mem_procs[:3]})

                # 检查OOM日志
                logs = (all_data.get("log") or {}).get("data", {}).get("logs", [])
                oom_logs = [l for l in logs if "oom" in l.lower()]
                if oom_logs:
                    causes.append("系统日志中存在OOM事件，可能发生过内存溢出")
                    evidence_list.append({"type": "log", "data": oom_logs[:3]})
                    confidence = "high"

                suggestions.append("检查内存泄漏进程，考虑重启高内存服务")
                suggestions.append("检查是否需要增加swap或物理内存")

            elif anomaly.category == "disk":
                causes.append("磁盘空间被大量日志文件、临时文件或应用数据占用")
                suggestions.append("使用 du -sh /* 查找大目录")
                suggestions.append("清理 /var/log、/tmp 中的过期文件")
                suggestions.append("检查是否有日志轮转配置")

            elif anomaly.category == "process":
                if "僵尸" in anomaly.title:
                    causes.append("父进程未正确回收子进程资源")
                    suggestions.append("查找并重启僵尸进程的父进程")
                    suggestions.append("使用 kill -9 <pid> 清理僵尸进程")
                elif "CPU" in anomaly.title:
                    causes.append(f"单个进程 {anomaly.detail.split(' ')[0]} 占用大量CPU")
                    suggestions.append("检查该进程是否正常，考虑重启或限制资源")
                elif "内存" in anomaly.title:
                    causes.append(f"单个进程存在内存泄漏或正常高内存使用")
                    suggestions.append("检查应用是否正常，考虑重启释放内存")

            elif anomaly.category == "log":
                if "OOM" in anomaly.title:
                    causes.append("系统因内存不足而终止进程")
                    confidence = "high"
                    suggestions.append("增加物理内存或调整OOM killer策略")
                    suggestions.append("找出内存泄漏的应用并修复")
                elif "磁盘I/O" in anomaly.title:
                    causes.append("磁盘硬件故障或文件系统损坏")
                    confidence = "high"
                    suggestions.append("立即备份重要数据")
                    suggestions.append("运行 fsck 检查文件系统")
                    suggestions.append("检查磁盘健康状态: smartctl -a /dev/sdX")

            elif anomaly.category == "network":
                causes.append("网络硬件故障、驱动问题或网络拥塞")
                suggestions.append("检查网线连接和交换机状态")
                suggestions.append("检查网卡驱动是否正常")

            root_causes.append(RootCause(
                anomaly=anomaly,
                probable_causes=causes,
                related_evidence=evidence_list,
                fix_suggestions=suggestions,
                confidence=confidence,
            ))

        return root_causes

    def _generate_report(self, anomalies: List[Anomaly], root_causes: List[RootCause]) -> Dict[str, Any]:
        """生成诊断报告"""
        critical = [a for a in anomalies if a.severity == "critical"]
        warnings = [a for a in anomalies if a.severity == "warning"]

        # 给出整体健康评分
        health_score = 100
        health_score -= len(critical) * 25
        health_score -= len(warnings) * 5
        health_score = max(0, min(100, health_score))

        if health_score >= 90:
            health_level = "健康"
        elif health_score >= 70:
            health_level = "良好"
        elif health_score >= 50:
            health_level = "一般"
        elif health_score >= 30:
            health_level = "较差"
        else:
            health_level = "危险"

        report = {
            "timestamp": datetime.now().isoformat(),
            "health_score": health_score,
            "health_level": health_level,
            "summary": {
                "total_anomalies": len(anomalies),
                "critical": len(critical),
                "warning": len(warnings),
            },
            "anomalies": [
                {
                    "category": a.category,
                    "severity": a.severity,
                    "title": a.title,
                    "detail": a.detail,
                    "value": a.value,
                    "threshold": a.threshold,
                }
                for a in anomalies
            ],
            "root_causes": [
                {
                    "anomaly_title": rc.anomaly.title,
                    "severity": rc.anomaly.severity,
                    "probable_causes": rc.probable_causes,
                    "related_evidence": rc.related_evidence,
                    "fix_suggestions": rc.fix_suggestions,
                    "confidence": rc.confidence,
                }
                for rc in root_causes
            ],
            "recommendations": self._generate_recommendations(anomalies, root_causes),
        }

        return report

    def _generate_recommendations(self, anomalies: List[Anomaly], root_causes: List[RootCause]) -> List[str]:
        """生成综合修复建议"""
        recs = []
        categories = set(a.category for a in anomalies)

        if "cpu" in categories:
            recs.append("【CPU优化】检查高CPU进程，优化代码或增加资源限制")
        if "memory" in categories:
            recs.append("【内存优化】排查内存泄漏，考虑增加物理内存或优化应用配置")
        if "disk" in categories:
            recs.append("【磁盘清理】清理过期日志和临时文件，配置日志轮转")
        if "process" in categories:
            recs.append("【进程管理】清理僵尸进程，重启异常进程")
        if "log" in categories:
            recs.append("【日志分析】深入分析错误日志，修复根因问题")
        if "network" in categories:
            recs.append("【网络排查】检查网络硬件和驱动，排查丢包原因")

        critical = [a for a in anomalies if a.severity == "critical"]
        if critical:
            recs.insert(0, "⚠️ 存在严重异常，建议立即处理！")

        if not anomalies:
            recs.append("系统运行状态良好，无需特别处理。建议定期运行诊断。")

        return recs


# 全局根因分析器实例
root_cause_analyzer = RootCauseAnalyzer()

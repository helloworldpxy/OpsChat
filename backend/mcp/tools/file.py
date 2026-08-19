# -*- coding: utf-8 -*-
"""
文件操作工具
包含高危操作工具（用于安全护栏演示）
以及配置文件漂移检测
"""

import os
import stat
import hashlib
import json
import subprocess
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..protocol import ToolExecutor, RiskLevel


class DeleteFileTool(ToolExecutor):
    """删除文件工具（高危操作）"""

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """删除指定文件"""
        path = kwargs.get("path", "")
        recursive = kwargs.get("recursive", False)
        force = kwargs.get("force", False)

        if not path:
            return {"success": False, "error": "必须指定文件路径"}

        # 安全检查: 关键路径
        critical_paths = ["/etc", "/boot", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/root", "/proc", "/sys", "/dev"]
        normalized = os.path.normpath(path)
        for cp in critical_paths:
            if normalized == cp or normalized.startswith(cp + "/"):
                return {"success": False, "error": f"安全拦截: 禁止删除系统关键目录 {cp} 下的文件"}

        if not os.path.exists(path):
            return {"success": False, "error": f"路径不存在: {path}"}

        try:
            if os.path.isfile(path):
                size = os.path.getsize(path)
                os.remove(path)
                return {
                    "success": True,
                    "data": {
                        "path": path,
                        "action": "delete_file",
                        "size_bytes": size,
                        "message": f"已删除文件: {path}"
                    }
                }
            elif os.path.isdir(path):
                if not recursive:
                    return {"success": False, "error": f"{path} 是目录，需要 recursive=true 才能删除"}
                import shutil
                shutil.rmtree(path)
                return {
                    "success": True,
                    "data": {
                        "path": path,
                        "action": "delete_directory",
                        "message": f"已删除目录: {path}"
                    }
                }
            else:
                return {"success": False, "error": f"未知文件类型: {path}"}
        except PermissionError:
            return {"success": False, "error": f"权限不足，无法删除: {path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class ChmodTool(ToolExecutor):
    """修改文件权限工具（高危操作）"""

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """修改文件权限"""
        path = kwargs.get("path", "")
        mode = kwargs.get("mode", "")

        if not path or not mode:
            return {"success": False, "error": "必须指定文件路径和权限模式"}

        if not os.path.exists(path):
            return {"success": False, "error": f"路径不存在: {path}"}

        try:
            mode_int = int(mode, 8)
            old_stat = os.stat(path)
            old_mode = oct(stat.S_IMODE(old_stat.st_mode))
            os.chmod(path, mode_int)
            new_mode = oct(stat.S_IMODE(mode_int))

            return {
                "success": True,
                "data": {
                    "path": path,
                    "action": "chmod",
                    "old_mode": old_mode,
                    "new_mode": new_mode,
                    "message": f"已修改 {path} 权限: {old_mode} -> {new_mode}"
                }
            }
        except ValueError:
            return {"success": False, "error": f"无效的权限模式: {mode}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class ConfigDriftTool(ToolExecutor):
    """配置文件漂移检测工具
    通过对比文件哈希值来检测配置文件是否被意外修改
    """

    # 关键配置文件列表
    CRITICAL_CONFIGS = [
        "/etc/passwd",
        "/etc/shadow",
        "/etc/sudoers",
        "/etc/ssh/sshd_config",
        "/etc/fstab",
        "/etc/hosts",
        "/etc/resolv.conf",
        "/etc/sysctl.conf",
        "/etc/security/limits.conf",
        "/etc/crontab",
    ]

    def _get_file_hash(self, path: str) -> Optional[str]:
        """获取文件SHA256哈希"""
        try:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except (PermissionError, FileNotFoundError, OSError):
            return None

    def _get_file_info(self, path: str) -> Optional[Dict[str, Any]]:
        """获取文件详细信息"""
        try:
            st = os.stat(path)
            return {
                "path": path,
                "exists": True,
                "size": st.st_size,
                "mode": oct(stat.S_IMODE(st.st_mode)),
                "owner_uid": st.st_uid,
                "group_gid": st.st_gid,
                "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
                "hash_sha256": self._get_file_hash(path),
            }
        except (FileNotFoundError, PermissionError, OSError):
            return {"path": path, "exists": False}

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """检测配置文件漂移"""
        config_files = kwargs.get("config_files", self.CRITICAL_CONFIGS)
        baseline_path = kwargs.get("baseline", "")

        # 如果提供了基线文件，对比当前状态与基线
        if baseline_path and os.path.exists(baseline_path):
            return await self._compare_with_baseline(config_files, baseline_path)

        # 否则生成当前快照
        return await self._generate_snapshot(config_files)

    async def _generate_snapshot(self, config_files: List[str]) -> Dict[str, Any]:
        """生成当前配置快照"""
        snapshot = {}
        for path in config_files:
            info = self._get_file_info(path)
            if info:
                snapshot[path] = info

        # 保存为基线
        baseline = {
            "timestamp": datetime.now().isoformat(),
            "files": snapshot
        }

        baseline_path = "data/config_baseline.json"
        os.makedirs("data", exist_ok=True)
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)

        return {
            "success": True,
            "data": {
                "action": "snapshot",
                "files_scanned": len(snapshot),
                "baseline_saved": baseline_path,
                "snapshot": snapshot,
                "message": f"已生成 {len(snapshot)} 个配置文件的快照，基线已保存"
            }
        }

    async def _compare_with_baseline(self, config_files: List[str], baseline_path: str) -> Dict[str, Any]:
        """与基线对比"""
        try:
            with open(baseline_path, "r", encoding="utf-8") as f:
                baseline = json.load(f)
        except Exception as e:
            return {"success": False, "error": f"读取基线文件失败: {e}"}

        changes = []
        baseline_files = baseline.get("files", {})

        for path in config_files:
            current = self._get_file_info(path)
            old = baseline_files.get(path)

            if current is None and old is None:
                continue
            if current is None and old is not None:
                changes.append({"path": path, "change": "deleted", "old": old})
            elif current is not None and old is None:
                changes.append({"path": path, "change": "new", "current": current})
            elif current.get("hash_sha256") != old.get("hash_sha256"):
                changes.append({
                    "path": path,
                    "change": "modified",
                    "old_hash": old.get("hash_sha256"),
                    "new_hash": current.get("hash_sha256"),
                    "old_mtime": old.get("mtime"),
                    "new_mtime": current.get("mtime"),
                    "old_mode": old.get("mode"),
                    "new_mode": current.get("mode"),
                })

        return {
            "success": True,
            "data": {
                "action": "drift_check",
                "baseline_time": baseline.get("timestamp"),
                "files_checked": len(config_files),
                "changes_detected": len(changes),
                "changes": changes,
                "has_drift": len(changes) > 0,
                "message": f"检测到 {len(changes)} 处配置漂移" if changes else "未检测到配置漂移"
            }
        }

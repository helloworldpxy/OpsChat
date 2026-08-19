# -*- coding: utf-8 -*-
"""
权限服务模块
实现基于规则的权限审批引擎（借鉴 opencode 的 permission 设计）：
- Rule: {permission, pattern, action: allow/deny/ask}，持久化到 SQLite
- Request: 一次待用户审批的高危操作请求，挂起等待，超时自动拒绝
- Reply: once/always/reject，always 会写入持久化规则，级联放行
- sudo 密码提权验证：sudo -S -v 刷新 sudo timestamp，密码即焚（不落库、不进日志、不进 LLM 上下文）
"""

import fnmatch
import logging
import platform
import subprocess
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..config import settings
from ..models.permission import PermissionRule, PermissionRequest

logger = logging.getLogger(__name__)


class PermissionDeniedError(Exception):
    """权限被规则拒绝异常"""
    def __init__(self, permission: str, message: str):
        self.permission = permission
        super().__init__(message)


class PermissionService:
    """权限审批服务"""

    def __init__(self):
        self._rules: List[PermissionRule] = []
        self._pending: Dict[str, PermissionRequest] = {}
        self._seq = 0
        self._lock = threading.Lock()
        self._load_rules()

    # ---------- 规则管理 ----------

    def _load_rules(self) -> None:
        """从数据库加载已有规则"""
        try:
            from ..database import SessionLocal
            db = SessionLocal()
            try:
                self._rules = db.query(PermissionRule).order_by(PermissionRule.created_at.asc()).all()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"加载权限规则失败: {e}")
            self._rules = []

    def add_rule(self, permission: str, pattern: str, action: str,
                 session_id: Optional[str] = None) -> PermissionRule:
        """添加一条权限规则并持久化"""
        rule = PermissionRule(
            permission=permission,
            pattern=pattern,
            action=action,
            session_id=session_id,
        )
        try:
            from ..database import SessionLocal
            db = SessionLocal()
            try:
                db.add(rule)
                db.commit()
                # 提交后刷新属性，避免 detached 状态下访问时触发懒加载报错
                db.refresh(rule)
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"持久化权限规则失败: {e}")
        with self._lock:
            self._rules.append(rule)
        logger.info(f"新增权限规则: {permission} {pattern} -> {action}")
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        """删除一条权限规则"""
        with self._lock:
            self._rules = [r for r in self._rules if r.id != rule_id]
        try:
            from ..database import SessionLocal
            db = SessionLocal()
            try:
                rule = db.query(PermissionRule).filter(PermissionRule.id == rule_id).first()
                if rule:
                    db.delete(rule)
                    db.commit()
                    return True
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"删除权限规则失败: {e}")
        return False

    def list_rules(self) -> List[Dict[str, Any]]:
        """列出所有规则"""
        return [r.to_dict() for r in self._rules]

    def clear_rules(self, session_id: Optional[str] = None) -> None:
        """清空权限规则（管理接口与测试用）"""
        try:
            from ..database import SessionLocal
            db = SessionLocal()
            try:
                q = db.query(PermissionRule)
                if session_id:
                    q = q.filter(PermissionRule.session_id == session_id)
                q.delete()
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"清空权限规则失败: {e}")
        with self._lock:
            if session_id:
                self._rules = [r for r in self._rules if r.session_id != session_id]
            else:
                self._rules = []

    def reset(self) -> None:
        """重置全部规则与挂起请求（管理与测试用）"""
        self.clear_rules()
        with self._lock:
            self._pending.clear()
            self._seq = 0

    def evaluate(self, permission: str, pattern: str, session_id: Optional[str] = None) -> str:
        """评估某个 (权限, 模式) 对应的动作：allow / deny / ask（未匹配默认 ask）
        权限名与资源模式均支持 * 通配符匹配，多条匹配时取最后一条。
        规则按会话隔离：优先匹配 session_id 完全一致的规则，其次全局规则（session_id 为空）。
        """
        session_matches = []
        global_matches = []
        for rule in self._rules:
            if (fnmatch.fnmatch(permission, rule.permission)
                    and fnmatch.fnmatch(pattern, rule.pattern)):
                if session_id is not None and rule.session_id == session_id:
                    session_matches.append(rule)
                elif not rule.session_id:
                    global_matches.append(rule)

        # 会话专属规则优先于全局规则；同层内取最后一条
        if session_matches:
            return session_matches[-1].action
        if global_matches:
            return global_matches[-1].action
        return "ask"

    # ---------- 审批请求 ----------

    def ask(
        self,
        session_id: str,
        permission: str,
        patterns: List[str],
        metadata: Optional[Dict[str, Any]] = None,
        always: Optional[List[str]] = None,
        tool_name: Optional[str] = None,
        tool_params: Optional[Dict[str, Any]] = None,
        tool_call_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        password_required: bool = True,
    ) -> Optional[PermissionRequest]:
        """
        发起一次权限审批请求
        - 所有模式均命中 allow 规则：返回 None（无需审批）
        - 任一模式命中 deny 规则：抛出 PermissionDeniedError
        - 否则挂起一个请求等待用户回复
        """
        need_approval = False
        for pattern in patterns:
            action = self.evaluate(permission, pattern, session_id=session_id)
            if action == "deny":
                raise PermissionDeniedError(
                    permission,
                    f"该操作已被安全规则禁止: {permission} ({pattern})",
                )
            if action == "ask":
                need_approval = True

        if not need_approval:
            return None

        with self._lock:
            now = datetime.now()
            req = PermissionRequest(
                id=str(uuid.uuid4()),
                session_id=session_id,
                permission=permission,
                patterns=patterns,
                metadata_json=metadata or {},
                always=always or patterns,
                tool_name=tool_name,
                tool_params=tool_params,
                tool_call_id=tool_call_id,
                trace_id=trace_id,
                status="pending",
                password_required=password_required,
                created_at=now,
                expires_at=now + timedelta(seconds=settings.permission_ask_timeout),
            )
            self._pending[req.id] = req
        self._persist_request(req)
        logger.info(f"发起权限审批请求 {req.id}: {permission} {patterns}")
        return req

    def get_request(self, request_id: str) -> Optional[PermissionRequest]:
        """获取挂起的审批请求"""
        self.expire_pending()
        return self._pending.get(request_id)

    def expire_pending(self) -> None:
        """将超时未处理的请求标记为过期"""
        now = datetime.now()
        with self._lock:
            expired = [
                rid for rid, r in self._pending.items()
                if r.expires_at and r.expires_at < now
            ]
            for rid in expired:
                req = self._pending.pop(rid, None)
                if req:
                    req.status = "expired"
                    self._update_request_status(rid, "expired")
        if expired:
            logger.info(f"审批请求超时自动拒绝: {expired}")

    def reply(self, request_id: str, reply: str, password: Optional[str] = None,
              session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        处理用户对审批请求的回复
        - reply: once（仅本次允许）/ always（始终允许）/ reject（拒绝）
        - session_id: 必须与发起请求的会话一致，防止跨会话代批
        - 返回 {"status": "approved"/"rejected", "request": req} 或 {"error": ...}
        """
        self.expire_pending()
        with self._lock:
            req = self._pending.get(request_id)
            if not req:
                return {"error": "审批请求不存在或已过期"}
            if req.status != "pending":
                return {"error": f"审批请求已被处理（{req.status}）"}
            # 会话归属校验：请求必须由同一会话发起才可处理
            if session_id is not None and req.session_id != session_id:
                return {"error": "审批请求不属于当前会话，已拒绝处理"}
            req = self._pending.pop(request_id)

        # sudo 密码验证（仅通过类型的回复需要）
        if reply in ("once", "always") and req.password_required:
            if not self.verify_sudo(password):
                # 验证失败恢复挂起状态，允许用户重试
                with self._lock:
                    req.status = "pending"
                    self._pending[request_id] = req
                return {"error": "sudo 密码验证失败，请检查密码后重试"}

        if reply == "reject":
            req.status = "rejected"
            self._update_request_status(request_id, "rejected")
            logger.info(f"用户拒绝了审批请求 {request_id}: {req.tool_name}")
            return {"status": "rejected", "request": req}

        # once / always 均放行本次操作
        if reply == "always":
            for item in (req.always or []):
                self.add_rule(req.permission, item, "allow", session_id=req.session_id)

        req.status = "approved"
        self._update_request_status(request_id, "approved")
        logger.info(f"用户批准了审批请求 {request_id}: {req.tool_name} (reply={reply})")
        return {"status": "approved", "request": req}

    def _persist_request(self, req: PermissionRequest) -> None:
        """持久化审批请求，便于审计"""
        try:
            from ..database import SessionLocal
            db = SessionLocal()
            try:
                db.add(req)
                db.commit()
                # 刷新属性，避免 detached 后访问字段触发懒加载
                db.refresh(req)
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"持久化权限请求失败: {e}")

    def _update_request_status(self, request_id: str, status: str) -> None:
        """更新审批请求状态"""
        try:
            from ..database import SessionLocal
            db = SessionLocal()
            try:
                req = db.query(PermissionRequest).filter(PermissionRequest.id == request_id).first()
                if req:
                    req.status = status
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"更新权限请求状态失败: {e}")

    # ---------- sudo 提权验证 ----------

    @staticmethod
    def sudo_available() -> bool:
        """判断当前环境是否支持 sudo（Windows 无 sudo）"""
        return platform.system() != "Windows"

    @staticmethod
    def verify_sudo(password: Optional[str] = None) -> bool:
        """
        验证 sudo 密码并刷新 sudo timestamp
        1. 先检测 sudo timestamp 是否仍有效（sudo -n true）
        2. 无效则用密码刷新凭证（sudo -S -v）
        密码即焚：验证完成后立即丢弃，不记录、不落库
        """
        if not PermissionService.sudo_available():
            # Windows 环境无 sudo，降级为免密码审批
            return True

        try:
            # 检测 sudo timestamp 是否有效
            check = subprocess.run(
                ["sudo", "-n", "true"],
                capture_output=True,
                timeout=10,
            )
            if check.returncode == 0:
                return True

            if not password:
                return False

            # 用密码刷新 sudo timestamp（输入密码，不回显）
            verify = subprocess.run(
                ["sudo", "-S", "-v"],
                input=password + "\n",
                capture_output=True,
                timeout=10,
                text=True,
            )
            return verify.returncode == 0
        except Exception as e:
            logger.warning(f"sudo 验证异常: {e}")
            return False

    def to_dict(self, req: PermissionRequest) -> Dict[str, Any]:
        """将审批请求序列化为字典（用于 SSE 下发前端）"""
        return {
            "request_id": req.id,
            "session_id": req.session_id,
            "permission": req.permission,
            "patterns": req.patterns,
            "metadata": req.metadata_json,
            "tool_name": req.tool_name,
            "tool_params": req.tool_params,
            "tool_call_id": req.tool_call_id,
            "trace_id": req.trace_id,
            "status": req.status,
            "password_required": req.password_required,
            "created_at": req.created_at.isoformat() if req.created_at else None,
            "expires_at": req.expires_at.isoformat() if req.expires_at else None,
        }


# 全局权限服务实例
permission_service = PermissionService()
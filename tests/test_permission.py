# -*- coding: utf-8 -*-
"""
权限引擎测试
测试 PermissionService 规则评估、审批流程与 sudo 提权验证
"""

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from backend.security.permission import PermissionService, PermissionDeniedError, permission_service
from backend.core.agent import agent


@pytest.fixture(autouse=True)
def reset_permission_state():
    """每个测试前后重置权限引擎，避免规则与挂起请求跨测试累积"""
    permission_service.reset()
    yield
    permission_service.reset()


class TestPermissionService:
    """权限服务单元测试"""

    def setup_method(self):
        """每个测试前创建独立实例"""
        self.service = PermissionService()

    def test_evaluate_default_ask(self):
        """未配置规则时默认 ask"""
        assert self.service.evaluate("tool:test", "foo") == "ask"

    def test_add_rule_and_evaluate(self):
        """添加规则后按规则评估"""
        self.service.add_rule("tool:kill_process", "kill_process", "allow")
        assert self.service.evaluate("tool:kill_process", "kill_process") == "allow"

    def test_wildcard_pattern(self):
        """通配符规则匹配"""
        self.service.add_rule("tool:*", "*", "deny")
        assert self.service.evaluate("tool:kill_process", "kill_process") == "deny"
        assert self.service.evaluate("tool:restart_service", "restart_service") == "deny"

    def test_rule_take_last_match(self):
        """多条规则匹配时取最后一条"""
        self.service.add_rule("tool:kill_process", "kill_process", "deny")
        self.service.add_rule("tool:kill_process", "kill_process", "allow")
        assert self.service.evaluate("tool:kill_process", "kill_process") == "allow"

    def test_ask_all_allowed_returns_none(self):
        """所有模式均被规则放行时无需审批"""
        self.service.add_rule("tool:get_system_info", "get_system_info", "allow")
        req = self.service.ask(
            "s1", "tool:get_system_info", ["get_system_info"], tool_name="get_system_info"
        )
        assert req is None

    def test_ask_deny_raises(self):
        """命中 deny 规则时抛出异常"""
        self.service.add_rule("tool:kill_process", "kill_process", "deny")
        with pytest.raises(PermissionDeniedError):
            self.service.ask(
                "s1", "tool:kill_process", ["kill_process"], tool_name="kill_process"
            )

    def test_ask_pending(self):
        """未匹配规则时挂起审批请求"""
        req = self.service.ask(
            "s1", "tool:kill_process", ["kill_process"], tool_name="kill_process"
        )
        assert req is not None
        assert req.status == "pending"
        assert self.service.get_request(req.id) is req

    def test_reply_once(self):
        """once 批准本次操作且不写规则"""
        req = self.service.ask(
            "s1", "tool:kill_process", ["kill_process"],
            tool_name="kill_process", tool_call_id="call_1",
        )
        req.password_required = False
        result = self.service.reply(req.id, "once")
        assert result["status"] == "approved"
        assert result["request"].tool_call_id == "call_1"
        # 本次放行但不写入规则
        assert self.service.evaluate("tool:kill_process", "kill_process") == "ask"

    def test_reply_always_writes_rule(self):
        """always 写入持久化规则，后续不再询问（规则绑定发起会话）"""
        req = self.service.ask(
            "s1", "tool:kill_process", ["kill_process"],
            always=["kill_process"], tool_name="kill_process",
        )
        req.password_required = False
        result = self.service.reply(req.id, "always")
        assert result["status"] == "approved"
        # 规则绑定 s1：带 session_id 评估命中 allow
        assert self.service.evaluate("tool:kill_process", "kill_process", session_id="s1") == "allow"
        # 无 session 上下文 / 其他会话不命中（H5 会话隔离）
        assert self.service.evaluate("tool:kill_process", "kill_process") == "ask"
        assert self.service.evaluate("tool:kill_process", "kill_process", session_id="s2") == "ask"
        # 再次发起审批（同会话）直接放行
        assert self.service.ask("s1", "tool:kill_process", ["kill_process"]) is None
        # 其他会话仍需审批
        assert self.service.ask("s2", "tool:kill_process", ["kill_process"]) is not None

    def test_reply_reject(self):
        """reject 拒绝操作"""
        req = self.service.ask(
            "s1", "tool:restart_service", ["restart_service"], tool_name="restart_service"
        )
        req.password_required = False
        result = self.service.reply(req.id, "reject")
        assert result["status"] == "rejected"
        assert self.service.evaluate("tool:restart_service", "restart_service") == "ask"

    def test_reply_unknown_request(self):
        """不存在的审批请求返回错误"""
        result = self.service.reply("per_999", "once")
        assert "error" in result

    def test_reply_twice_rejected(self):
        """同一请求不能重复处理"""
        req = self.service.ask("s1", "tool:x", ["x"], tool_name="x")
        req.password_required = False
        first = self.service.reply(req.id, "once")
        assert first["status"] == "approved"
        second = self.service.reply(req.id, "once")
        assert "error" in second

    def test_expired_request(self):
        """超时未处理的请求自动过期"""
        req = self.service.ask("s1", "tool:x", ["x"], tool_name="x")
        req.expires_at = datetime.now() - timedelta(seconds=1)
        assert self.service.get_request(req.id) is None

    def test_reply_after_expired(self):
        """过期后回复返回错误"""
        req = self.service.ask("s1", "tool:x", ["x"], tool_name="x")
        req.expires_at = datetime.now() - timedelta(seconds=1)
        result = self.service.reply(req.id, "once")
        assert "error" in result

    def test_to_dict(self):
        """审批请求序列化"""
        req = self.service.ask(
            "s1", "tool:kill_process", ["kill_process"],
            tool_name="kill_process", tool_params={"pid": 123},
        )
        d = self.service.to_dict(req)
        assert d["request_id"] == req.id
        assert d["tool_name"] == "kill_process"
        assert d["password_required"] is True
        assert "expires_at" in d

    def test_verify_sudo_windows(self, monkeypatch):
        """Windows 环境降级为免密码审批"""
        monkeypatch.setattr("backend.security.permission.platform.system", lambda: "Windows")
        assert PermissionService.verify_sudo() is True

    def test_verify_sudo_valid_timestamp(self, monkeypatch):
        """sudo timestamp 有效时无需密码"""
        monkeypatch.setattr("backend.security.permission.platform.system", lambda: "Linux")

        class FakeResult:
            returncode = 0

        monkeypatch.setattr(
            "backend.security.permission.subprocess.run",
            lambda cmd, **kwargs: FakeResult(),
        )
        assert PermissionService.verify_sudo() is True

    def test_verify_sudo_with_password(self, monkeypatch):
        """timestamp 失效时用密码刷新"""
        monkeypatch.setattr("backend.security.permission.platform.system", lambda: "Linux")

        class OkResult:
            returncode = 0

        class FailResult:
            returncode = 1

        def fake_run(cmd, **kwargs):
            if cmd == ["sudo", "-n", "true"]:
                return FailResult()
            if cmd == ["sudo", "-S", "-v"]:
                # 密码通过 stdin 传入，不回显
                assert kwargs.get("input") == "secret\n"
                return OkResult()
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr("backend.security.permission.subprocess.run", fake_run)
        assert PermissionService.verify_sudo("secret") is True

    def test_verify_sudo_wrong_password(self, monkeypatch):
        """密码错误返回 False"""
        monkeypatch.setattr("backend.security.permission.platform.system", lambda: "Linux")

        class FailResult:
            returncode = 1

        def fake_run(cmd, **kwargs):
            return FailResult()

        monkeypatch.setattr("backend.security.permission.subprocess.run", fake_run)
        assert PermissionService.verify_sudo("wrong") is False

    def test_verify_sudo_no_password_no_timestamp(self, monkeypatch):
        """无密码且 timestamp 失效时返回 False"""
        monkeypatch.setattr("backend.security.permission.platform.system", lambda: "Linux")

        class FailResult:
            returncode = 1

        monkeypatch.setattr(
            "backend.security.permission.subprocess.run",
            lambda cmd, **kwargs: FailResult(),
        )
        assert PermissionService.verify_sudo() is False


class FakeLLM:
    """模拟 LLM 客户端：按脚本顺序返回响应"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def chat(self, messages, tools=None, stream=False):
        idx = self.calls
        self.calls += 1
        if idx >= len(self.script):
            raise RuntimeError(f"LLM 被调用次数超出脚本: {idx}")

        item = self.script[idx]
        if stream:
            async def gen():
                chunks = item if isinstance(item, list) else [item]
                for c in chunks:
                    yield c
            return gen()

        # 非流式返回 dict
        return item if isinstance(item, dict) else {"content": "", "tool_calls": None}


def tool_call_chunk(name, args, call_id="call_1"):
    """构造流式工具调用 chunk"""
    return [
        {"type": "tool_calls", "tool_calls": [
            {"id": call_id, "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}},
        ]},
        {"type": "finish", "finish_reason": "tool_calls"},
    ]


def text_chunk(text):
    """构造流式文本 chunk"""
    return [
        {"type": "content", "content": text},
        {"type": "finish", "finish_reason": "stop"},
    ]


async def collect_stream(agen):
    """收集异步生成器的全部事件"""
    events = []
    async for evt in agen:
        events.append(evt)
    return events


class TestAgentPermissionIntegration:
    """Agent 权限集成测试（mock LLM 与工具执行）"""

    async def _fake_execute(self, tool_name, params):
        return {"success": True, "message": f"executed:{tool_name}"}

    def test_stream_high_risk_tool_asks_permission(self, monkeypatch):
        """流式模式下高危工具触发权限审批卡"""
        fake_llm = FakeLLM([
            tool_call_chunk("kill_process", {"pid": 123}),
        ])
        monkeypatch.setattr(agent, "llm_client", fake_llm)

        async def run():
            events = await collect_stream(await agent.process_message(
                "杀掉进程 123", "s1", stream=True,
            ))
            return events

        events = asyncio.run(run())

        asked = [e for e in events if e["type"] == "permission_asked"]
        assert len(asked) == 1
        assert asked[0]["tool_name"] == "kill_process"
        assert asked[0]["request"]["tool_name"] == "kill_process"
        assert asked[0]["request"]["password_required"] is True
        # 未执行工具
        assert not [e for e in events if e["type"] == "tool_result"]
        # 只调用了一次 LLM（挂起审批，不继续推理）
        assert fake_llm.calls == 1

    def test_confirm_once_executes_and_summarizes(self, monkeypatch):
        """once 批准后执行工具并生成总结"""
        fake_llm = FakeLLM([
            tool_call_chunk("kill_process", {"pid": 123}),
            {"content": "已终止进程 123", "tool_calls": None},
        ])
        monkeypatch.setattr(agent, "llm_client", fake_llm)
        monkeypatch.setattr(agent, "_execute_tool", self._fake_execute)

        async def run():
            events = await collect_stream(await agent.process_message(
                "杀掉进程 123", "s2", stream=True,
            ))
            request_id = [e for e in events if e["type"] == "permission_asked"][0]["request"]["request_id"]
            result = await agent.confirm_permission("s2", request_id, "once", stream=False)
            return result

        result = asyncio.run(run())

        assert result["success"] is True
        assert result["message"] == "已终止进程 123"
        assert result["tool_result"]["success"] is True
        # LLM 共调用 2 次：一次工具调用，一次总结（修复双调后不再多余调用）
        assert fake_llm.calls == 2

    def test_confirm_reject_cancels(self, monkeypatch):
        """reject 拒绝操作，不执行工具不调 LLM 总结"""
        fake_llm = FakeLLM([
            tool_call_chunk("kill_process", {"pid": 123}),
        ])
        monkeypatch.setattr(agent, "llm_client", fake_llm)
        monkeypatch.setattr(agent, "_execute_tool", self._fake_execute)

        async def run():
            events = await collect_stream(await agent.process_message(
                "杀掉进程 123", "s3", stream=True,
            ))
            request_id = [e for e in events if e["type"] == "permission_asked"][0]["request"]["request_id"]
            result = await agent.confirm_permission("s3", request_id, "reject", stream=False)
            return result

        result = asyncio.run(run())

        assert result["success"] is True
        assert "取消" in result["message"]
        # 拒绝不执行工具、不再调用 LLM
        assert fake_llm.calls == 1

    def test_confirm_always_skips_next_ask(self, monkeypatch):
        """always 批准后写入规则，后续同工具不再询问"""
        fake_llm = FakeLLM([
            tool_call_chunk("kill_process", {"pid": 123}),
            {"content": "已终止进程 123", "tool_calls": None},
            # 第二次对话：规则放行，直接执行工具
            tool_call_chunk("kill_process", {"pid": 456}, call_id="call_2"),
            {"content": "已终止进程 456", "tool_calls": None},
        ])
        monkeypatch.setattr(agent, "llm_client", fake_llm)
        monkeypatch.setattr(agent, "_execute_tool", self._fake_execute)

        async def run():
            events = await collect_stream(await agent.process_message(
                "杀掉进程 123", "s4", stream=True,
            ))
            request_id = [e for e in events if e["type"] == "permission_asked"][0]["request"]["request_id"]
            await agent.confirm_permission("s4", request_id, "always", stream=False)

            # 第二次对话
            events2 = await collect_stream(await agent.process_message(
                "杀掉进程 456", "s4", stream=True,
            ))
            return events2

        events2 = asyncio.run(run())

        # 规则放行后不再出现审批卡，直接执行工具
        assert not [e for e in events2 if e["type"] == "permission_asked"]
        tool_results = [e for e in events2 if e["type"] == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0]["tool_name"] == "kill_process"
        assert tool_results[0]["result"]["success"] is True
        assert fake_llm.calls == 4

    def test_stream_no_double_llm_call(self, monkeypatch):
        """修复流式双调：低风险工具处理后只再调用一次 LLM 总结"""
        fake_llm = FakeLLM([
            tool_call_chunk("get_system_info", {}),
            text_chunk("系统信息如下"),
        ])
        monkeypatch.setattr(agent, "llm_client", fake_llm)
        monkeypatch.setattr(agent, "_execute_tool", self._fake_execute)

        async def run():
            return await collect_stream(await agent.process_message(
                "查看系统信息", "s5", stream=True,
            ))

        events = asyncio.run(run())

        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 1
        assert [e for e in events if e["type"] == "finish"]
        # 关键断言：总共只调用 2 次 LLM（旧实现会双调导致 3 次）
        assert fake_llm.calls == 2

    def test_stream_multi_step_tool_chain(self, monkeypatch):
        """多步工具链：连续两次工具调用后生成总结"""
        fake_llm = FakeLLM([
            tool_call_chunk("get_system_info", {}, call_id="call_1"),
            tool_call_chunk("get_cpu_usage", {}, call_id="call_2"),
            text_chunk("已完成诊断"),
        ])
        monkeypatch.setattr(agent, "llm_client", fake_llm)
        monkeypatch.setattr(agent, "_execute_tool", self._fake_execute)

        async def run():
            return await collect_stream(await agent.process_message(
                "诊断系统", "s6", stream=True,
            ))

        events = asyncio.run(run())

        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 2
        assert [e for e in events if e["type"] == "finish"]
        # 三次 LLM 调用：两次工具推理 + 一次总结
        assert fake_llm.calls == 3

    def test_confirm_stream_summary(self, monkeypatch):
        """confirm 接口流式返回总结"""
        fake_llm = FakeLLM([
            tool_call_chunk("kill_process", {"pid": 123}),
            # 流式总结，逐个 chunk 产出
            [{"type": "content", "content": "已"}, {"type": "content", "content": "终止"},
             {"type": "finish", "finish_reason": "stop"}],
        ])
        monkeypatch.setattr(agent, "llm_client", fake_llm)
        monkeypatch.setattr(agent, "_execute_tool", self._fake_execute)

        async def run():
            events = await collect_stream(await agent.process_message(
                "杀掉进程 123", "s7", stream=True,
            ))
            request_id = [e for e in events if e["type"] == "permission_asked"][0]["request"]["request_id"]
            stream = await agent.confirm_permission("s7", request_id, "once", stream=True)
            chunks = await collect_stream(stream)
            return chunks

        chunks = asyncio.run(run())

        contents = "".join(e["content"] for e in chunks if e["type"] == "content")
        assert contents == "已终止"
        assert [e for e in chunks if e["type"] == "finish"]
        # 总结阶段仅 1 次 LLM 调用（不含工具）
        assert fake_llm.calls == 2

    def test_guardrail_reject_blocked(self, monkeypatch):
        """护栏 REJECT 的操作直接返回失败结果，不产生审批卡"""
        from backend.security.guardrail import SecurityCheckResult, SecurityDecision

        # conftest 全局关闭了护栏，这里单独开启
        monkeypatch.setattr("backend.core.agent.settings.enable_security_guardrail", True)

        class FakeGuardrail:
            def check_input(self, user_message):
                return SecurityCheckResult(
                    decision=SecurityDecision.ALLOW,
                    message="ok",
                )

            def check_tool_call(self, tool_name, args):
                return SecurityCheckResult(
                    decision=SecurityDecision.REJECT,
                    message="危险操作被拦截",
                    risk_level="critical",
                    details={"rules_triggered": ["test"]},
                )

        monkeypatch.setattr(agent, "llm_client", FakeLLM([
            tool_call_chunk("delete_file", {"path": "/etc/passwd"}),
        ]))
        monkeypatch.setattr(agent, "security_guardrail", FakeGuardrail())

        async def run():
            return await collect_stream(await agent.process_message(
                "删除系统文件", "s8", stream=True,
            ))

        events = asyncio.run(run())

        assert not [e for e in events if e["type"] == "permission_asked"]
        results = [e for e in events if e["type"] == "tool_result"]
        assert len(results) == 1
        assert results[0]["result"]["success"] is False
        assert "拦截" in results[0]["result"]["error"]
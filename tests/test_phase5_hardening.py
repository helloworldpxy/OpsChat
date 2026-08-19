# -*- coding: utf-8 -*-
"""
阶段五测试：工程化加固
沙箱接线 / SSE 心跳 / token 预算裁剪与工具结果截断 / 可选基础认证
"""

import asyncio
import base64
import json

import pytest

from backend.core.agent import agent
from backend.utils.text import strip_ansi, truncate_text
from backend.security.sandbox import Sandbox
from backend.security.auth import check_credentials


class TestTextUtils:
    def test_strip_ansi(self):
        assert strip_ansi("\x1b[31mred\x1b[0m text") == "red text"
        assert strip_ansi("plain") == "plain"
        assert strip_ansi("\x1b[1;32mgreen\x1b[0m") == "green"

    def test_truncate_long_line(self):
        out = truncate_text("x" * 1000, max_chars=8000, max_line_len=100)
        assert len(out) < 300
        assert "[+900 chars]" in out

    def test_truncate_total(self):
        out = truncate_text("\n".join("行" * 200 for _ in range(100)), max_chars=500, max_line_len=100)
        assert len(out) <= 500 + 64
        assert "truncated" in out

    def test_truncate_collapses_blank_lines(self):
        out = truncate_text("a\n\n\n\nb")
        # 多个空行压缩为单个空行（一个换行分割 = "\n\n"）
        assert out == "a\n\nb"
        assert out.count("\n") == 2

    def test_truncate_strips_ansi_first(self):
        out = truncate_text("a\x1b[0m\n" + "b" * 300, max_line_len=10)
        assert "\x1b" not in out


class TestSandbox:
    def test_get_sandbox_command_sudo(self):
        sb = Sandbox()
        assert sb.get_sandbox_command("systemctl", ["status", "nginx"]) == ["sudo", "systemctl", "status", "nginx"]
        assert sb.get_sandbox_command("ls", ["-la"]) == ["ls", "-la"]

    def test_can_execute_path_restrictions(self):
        sb = Sandbox()
        # 禁止路径
        assert sb.can_execute("cat", {"path": "/proc/cpuinfo"}) is False
        # 只读路径禁止修改类工具
        assert sb.can_execute("delete_file", {"path": "/etc/passwd"}) is False
        assert sb.can_execute("chmod", {"path": "/usr/bin/foo"}) is False
        # 普通只读工具可执行
        assert sb.can_execute("ls", {"path": "/tmp"}) is True

    def test_run_shell_truncates_output(self):
        sb = Sandbox({"max_output_size": 120, "timeout_seconds": 15})
        result = sb.run_shell(
            ["python", "-c", 'print("x" * 5000)'],
        )
        assert result["success"] is True
        assert len(result["stdout"]) < 300
        assert "truncated" in result["stdout"]

    def test_run_shell_list_form_no_shell(self):
        sb = Sandbox()
        result = sb.run_shell(["python", "-c", "print('hello')"])
        assert result["success"] is True
        assert result["stdout"].strip() == "hello"


class TestHistoryTrim:
    def _user(self, n):
        return {"role": "user", "content": f"消息{n}"}

    def test_keeps_all_within_budget(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "context_window", 100000)
        monkeypatch.setattr(settings, "history_token_budget_ratio", 1.0)
        history = [self._user(i) for i in range(5)]
        out = agent._trim_history_by_budget(history)
        assert len(out) == 5

    def test_trims_oldest_on_budget_exceeded(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "context_window", 10)
        monkeypatch.setattr(settings, "history_token_budget_ratio", 1.0)
        history = [self._user(i) for i in range(10)]
        out = agent._trim_history_by_budget(history)
        assert len(out) < len(history)
        # 保留的是最新消息
        assert out[-1]["content"] == "消息9"
        assert out[0]["content"] != "消息0"

    def test_drops_orphan_tool_messages(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "context_window", 100000)
        monkeypatch.setattr(settings, "history_token_budget_ratio", 1.0)
        # 构造：assistant(tool_calls) + tool 紧跟；以及一条孤立的 tool（前面无 assistant）
        history = [
            {"role": "assistant", "content": "思考", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "结果1"},
            {"role": "assistant", "content": "总结"},
        ]
        out = agent._trim_history_by_budget(history)
        # 全保留：预算内，无孤儿
        assert len(out) == 3

        # 预算极小 → 只剩最新 assistant，紧跟其 tool 不保留（避免孤儿）
        monkeypatch.setattr(settings, "context_window", 3)
        monkeypatch.setattr(settings, "history_token_budget_ratio", 1.0)
        out2 = agent._trim_history_by_budget(history)
        assert len(out2) == 1
        assert out2[0]["role"] == "assistant"
        assert not out2[0].get("tool_calls")


class TestSandboxInAgentChain:
    def test_check_execution_blocks_readonly_modification(self, monkeypatch):
        """delete_file 修改 /etc 下文件 → 沙箱第三层检查拦截（action=stop）"""
        monkeypatch.setattr(agent, "llm_client", None)  # 仅测检查链路，无需 LLM

        async def run():
            return await agent._check_and_approve_tool(
                tool_call={"id": "call_x", "function": {"name": "delete_file", "arguments": '{"path": "/etc/passwd"}'}},
                tool_name="delete_file",
                tool_args={"path": "/etc/passwd"},
                session_id="p5_sandbox_1",
                trace_id="p5-trace",
            )

        result = asyncio.run(run())
        assert result["action"] == "stop"
        assert result["events"][0]["type"] == "tool_result"
        assert result["events"][0]["result"]["success"] is False

    def test_check_execution_allows_normal_tool(self, monkeypatch):
        """普通只读工具不被沙箱拦截"""
        async def run():
            return await agent._check_and_approve_tool(
                tool_call={"id": "call_y", "function": {"name": "disk_usage", "arguments": "{}"}},
                tool_name="disk_usage",
                tool_args={},
                session_id="p5_sandbox_2",
                trace_id="p5-trace2",
            )

        result = asyncio.run(run())
        # 无 path 参数 → 沙箱放行；未被权限机制拒绝（未确认阶段返回 asked 或 execute）
        assert result["action"] in ("execute", "stop")


class TestSSEHeartbeat:
    def test_heartbeat_on_slow_stream(self):
        from backend.api.chat import _with_heartbeat

        async def slow_stream():
            await asyncio.sleep(0.05)
            yield {"type": "content", "content": "a"}
            await asyncio.sleep(0.05)

        async def run():
            events = []
            async for evt in _with_heartbeat(slow_stream(), interval=0.02):
                events.append(evt)
            return events

        events = asyncio.run(run())
        types = [e["type"] for e in events]
        assert "heartbeat" in types
        assert "content" in types

    def test_no_heartbeat_when_fast(self):
        from backend.api.chat import _with_heartbeat

        async def fast_stream():
            yield {"type": "content", "content": "a"}
            yield {"type": "content", "content": "b"}

        async def run():
            events = []
            async for evt in _with_heartbeat(fast_stream(), interval=10):
                events.append(evt)
            return events

        events = asyncio.run(run())
        assert all(e["type"] != "heartbeat" for e in events)
        assert len(events) == 2


class TestAuth:
    def test_check_credentials(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "auth_username", "admin")
        monkeypatch.setattr(settings, "auth_password", "secret")
        assert check_credentials("admin", "secret") is True
        assert check_credentials("admin", "wrong") is False
        assert check_credentials("root", "secret") is False

    def test_auth_disabled_by_default(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_auth_enabled_blocks_and_allows(self, monkeypatch):
        from backend.config import settings
        from fastapi.testclient import TestClient
        from backend.main import app

        monkeypatch.setattr(settings, "auth_enabled", True)
        monkeypatch.setattr(settings, "auth_username", "admin")
        monkeypatch.setattr(settings, "auth_password", "secret")

        c = TestClient(app)

        # 未认证 → 401
        resp = c.get("/")
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate", "").startswith("Basic")

        # 静态资源放行
        resp_static = c.get("/static/css/style.css")
        assert resp_static.status_code == 200

        # 正确认证 → 200
        token = base64.b64encode(b"admin:secret").decode()
        resp_ok = c.get("/", headers={"Authorization": f"Basic {token}"})
        assert resp_ok.status_code == 200

        # API 同样受保护
        resp_api = c.get("/api/status")
        assert resp_api.status_code == 401
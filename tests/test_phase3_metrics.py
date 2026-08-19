# -*- coding: utf-8 -*-
"""
阶段三测试：ContextMeter（context_usage 事件）与 Turn 指标（TTFT / tokens每秒 / 耗时）
覆盖 _process_stream 与 _stream_summary 的事件输出
"""

import asyncio
import json

import pytest

from backend.core.agent import agent, estimate_tokens
from backend.security.permission import permission_service


@pytest.fixture(autouse=True)
def reset_state():
    permission_service.reset()
    yield
    permission_service.reset()


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
        return item if isinstance(item, dict) else {"content": "", "tool_calls": None}


def tool_call_chunk(name, args, call_id="call_1"):
    return [
        {"type": "tool_calls", "tool_calls": [
            {"id": call_id, "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}},
        ]},
        {"type": "finish", "finish_reason": "tool_calls"},
    ]


def text_chunk(text):
    return [
        {"type": "content", "content": text},
        {"type": "finish", "finish_reason": "stop"},
    ]


async def collect_stream(agen):
    events = []
    async for evt in agen:
        events.append(evt)
    return events


class TestEstimateTokens:
    def test_estimate_empty(self):
        assert estimate_tokens("") == 0

    def test_estimate_cjk(self):
        # 中文按 1 字符≈1 token
        assert estimate_tokens("系统信息") >= 4

    def test_estimate_mixed(self):
        assert estimate_tokens("hello 世界") > 0


class TestContextUsageEvent:
    def test_stream_emits_context_usage(self, monkeypatch):
        fake_llm = FakeLLM([
            text_chunk("系统正常"),
        ])
        monkeypatch.setattr(agent, "llm_client", fake_llm)

        async def run():
            return await collect_stream(await agent.process_message(
                "检查系统", "p3_s1", stream=True,
            ))

        events = asyncio.run(run())

        usage_events = [e for e in events if e["type"] == "context_usage"]
        assert len(usage_events) >= 1
        evt = usage_events[0]
        # 细分字段齐备
        for key in ("system", "tools", "messages", "total", "limit", "percent"):
            assert key in evt, f"context_usage 缺少字段 {key}"
        assert evt["system"] > 0          # System Prompt 恒有内容
        assert evt["tools"] >= 0
        assert evt["messages"] > 0        # 至少包含用户消息
        assert evt["total"] == evt["system"] + evt["tools"] + evt["messages"]
        assert evt["limit"] > 0
        assert 0 <= evt["percent"] <= 100


class TestTurnMetrics:
    def test_finish_contains_metrics(self, monkeypatch):
        fake_llm = FakeLLM([
            text_chunk("一切正常"),
        ])
        monkeypatch.setattr(agent, "llm_client", fake_llm)

        async def run():
            return await collect_stream(await agent.process_message(
                "检查系统", "p3_s2", stream=True,
            ))

        events = asyncio.run(run())

        finish = [e for e in events if e["type"] == "finish"]
        assert len(finish) == 1
        f = finish[0]
        assert "model" in f
        assert f["elapsed_ms"] >= 0
        assert f["ttft_ms"] >= 0
        assert f["tokens_per_sec"] > 0
        assert f["usage"]["completion_tokens"] > 0
        assert f["usage"]["prompt_tokens"] > 0
        assert f["usage"]["total_tokens"] == f["usage"]["prompt_tokens"] + f["usage"]["completion_tokens"]

    def test_summary_finish_contains_metrics(self, monkeypatch):
        """confirm 总结路径（_stream_summary）同样产出指标与 context_usage"""
        fake_llm = FakeLLM([
            tool_call_chunk("kill_process", {"pid": 1}),
            [{"type": "content", "content": "已"},
             {"type": "content", "content": "终止"},
             {"type": "finish", "finish_reason": "stop"}],
        ])
        monkeypatch.setattr(agent, "llm_client", fake_llm)
        async def fake_execute(name, params):
            return {"success": True, "message": "ok"}
        monkeypatch.setattr(agent, "_execute_tool", fake_execute)

        async def run():
            events = await collect_stream(await agent.process_message(
                "杀掉进程 1", "p3_s3", stream=True,
            ))
            request_id = [e for e in events if e["type"] == "permission_asked"][0]["request"]["request_id"]
            stream = await agent.confirm_permission("p3_s3", request_id, "once", stream=True)
            return await collect_stream(stream)

        chunks = asyncio.run(run())

        # 总结阶段前有 context_usage
        assert [e for e in chunks if e["type"] == "context_usage"]
        # tool_result 先行，finish 带指标
        assert chunks[0]["type"] == "tool_result"
        finish = [e for e in chunks if e["type"] == "finish"]
        assert len(finish) == 1
        assert finish[0]["ttft_ms"] >= 0
        assert finish[0]["usage"]["completion_tokens"] > 0
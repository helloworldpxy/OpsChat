# -*- coding: utf-8 -*-
"""
功能测试（端到端）
在真实 FastAPI 应用上通过 HTTP 驱动完整用户流程：
对话/会话管理、流式 SSE、工具目录、自定义工具 CRUD、
安全审批（once/always/reject）、沙箱拦截、输出校验、
全文检索、审计追踪、模型档案、系统状态。
LLM 客户端替换为可编排脚本的 FakeLLM，其余全部走真实链路。
"""

import json
import uuid

import pytest

from backend.config import settings
from backend.core.agent import agent
from backend.database import SessionLocal
from backend.models.audit import Conversation, ConversationMessage


# --------------------------------------------------------------------------
# FakeLLM：按脚本返回 文本 / 工具调用，支持流式
# --------------------------------------------------------------------------

def _text(content):
    return {
        "content": content, "role": "assistant", "finish_reason": "stop",
        "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
    }


def _tool(name, args):
    return {
        "content": "", "role": "assistant",
        "tool_calls": [{
            "id": "ftc_" + uuid.uuid4().hex[:6],
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
        }],
        "finish_reason": "tool_calls",
        "usage": {"prompt_tokens": 20, "completion_tokens": 0, "total_tokens": 20},
    }


class FakeLLM:
    """脚本式假 LLM：依次消费 script 中的响应，耗尽后返回默认文本"""

    def __init__(self, script=None):
        self.script = list(script or [])

    def _pop(self):
        return self.script.pop(0) if self.script else _text("功能测试通过")

    async def chat(self, messages=None, tools=None, stream=False):
        resp = self._pop()
        if stream:
            async def gen():
                if resp.get("tool_calls"):
                    yield {"type": "tool_calls", "tool_calls": resp["tool_calls"]}
                else:
                    for ch in resp.get("content", ""):
                        yield {"type": "content", "content": ch}
                yield {"type": "finish", "finish_reason": "stop",
                       "usage": resp.get("usage", {})}
            return gen()
        return resp


# --------------------------------------------------------------------------
# 工具函数 / fixtures
# --------------------------------------------------------------------------

def install_llm(monkeypatch, script=None):
    fake = FakeLLM(script)
    monkeypatch.setattr(agent, "llm_client", fake)
    return fake


@pytest.fixture
def full_security(monkeypatch):
    """开启完整安全链路（护栏 + 权限服务 + 沙箱 + 输出校验）"""
    monkeypatch.setattr(settings, "enable_security_guardrail", True)
    monkeypatch.setattr(settings, "enable_permission_service", True)
    monkeypatch.setattr(settings, "enable_sandbox", True)
    monkeypatch.setattr(settings, "enable_output_validator", True)
    monkeypatch.setattr(settings, "enable_input_sanitizer", True)


def sse_events(text):
    """解析 SSE 文本，返回事件 dict 列表（排除 [DONE]）"""
    events = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            payload = line[len("data: "):]
            if payload == "[DONE]":
                continue
            events.append(json.loads(payload))
    return events


def create_custom_tool(client, name, template, requires_approval=False, parameters=None):
    body = {
        "name": name,
        "description": "功能测试工具",
        "category": "custom",
        "risk_level": "low",
        "requires_approval": requires_approval,
        "parameters": parameters or {"type": "object", "properties": {}, "required": []},
        "command_template": template,
        "command_type": "shell",
    }
    r = client.post("/api/custom-tools/", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def delete_custom_tool(client, name):
    r = client.get("/api/custom-tools/")
    for item in r.json().get("data", []):
        if item["name"] == name:
            client.delete(f"/api/custom-tools/{item['id']}")


def delete_conversation(client, sid):
    try:
        client.delete(f"/api/chat/conversations/{sid}")
    except Exception:
        pass


# --------------------------------------------------------------------------
# 1. 系统状态与工具目录
# --------------------------------------------------------------------------

def test_health_and_status(client):
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["status"] == "healthy"

    s = client.get("/api/status").json()
    assert s["success"] is True
    assert s["data"]["tools_count"] > 0
    assert s["data"]["llm_configured"] is True


def test_tools_catalog(client):
    r = client.get("/api/tools/").json()
    assert r["success"] is True and r["total"] > 0
    names = []
    for t in r["data"]:
        assert all(k in t for k in ("name", "description", "risk_level",
                                    "requires_approval", "enabled", "is_custom"))
        names.append(t["name"])

    # 详情端点（动态取第一个内置工具）
    detail = client.get(f"/api/tools/{names[0]}").json()
    assert detail["success"] is True and detail["data"]["name"] == names[0]
    assert client.get("/api/tools/nonexistent_tool").status_code == 404

    # LLM 工具格式
    llm = client.get("/api/tools/llm").json()
    assert llm["success"] is True and llm["total"] > 0
    assert all("function" in t for t in llm["data"])


# --------------------------------------------------------------------------
# 2. 对话流程 + 会话生命周期
# --------------------------------------------------------------------------

def test_chat_flow_and_conversation_lifecycle(client, monkeypatch):
    sid = "ft_sess_" + uuid.uuid4().hex[:8]
    install_llm(monkeypatch)
    try:
        # 显式创建会话
        r = client.post("/api/chat/conversations", json={"title": "功能测试会话"})
        assert r.status_code == 200 and r.json()["success"]

        # 发送消息
        r = client.post("/api/chat/", json={"message": "你好", "session_id": sid, "stream": False})
        body = r.json()
        assert body["success"] is True and body["type"] == "text"
        assert "功能测试通过" in body["message"]
        trace_id = body["trace_id"]

        # 会话列表包含新会话，消息计数=2
        convs = client.get("/api/chat/conversations").json()["data"]
        conv = next((c for c in convs if c["id"] == sid), None)
        assert conv is not None
        assert conv["message_count"] == 2
        assert conv["last_message"]

        # 会话消息持久化
        msgs = client.get(f"/api/chat/conversations/{sid}/messages").json()["data"]
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant"]
        assert msgs[1]["content"] == "功能测试通过"

        # 重命名
        r = client.put(f"/api/chat/conversations/{sid}", json={"title": "已改名会话"})
        assert r.status_code == 200 and r.json()["data"]["title"] == "已改名会话"

        # 思维追踪（同步接口）
        tr = client.get(f"/api/chat/trace/{trace_id}")
        assert tr.status_code == 200
        assert tr.json()["trace_id"] == trace_id
        stage_names = [s["stage"] for s in tr.json()["stages"]]
        assert "user_input" in stage_names and "llm_reasoning" in stage_names and "response" in stage_names

        # 删除会话
        r = client.delete(f"/api/chat/conversations/{sid}")
        assert r.status_code == 200 and r.json()["success"]
        after = client.get("/api/chat/conversations").json()["data"]
        assert sid not in {c["id"] for c in after}

        # T2: 会话删除后 DB 消息行应同步清空（FTS 由 DELETE 触发器清理）
        from backend.database import SessionLocal as _SL
        from backend.models.audit import ConversationMessage as _CM
        _db = _SL()
        try:
            orphan = _db.query(_CM).filter(_CM.conversation_id == sid).count()
            assert orphan == 0
        finally:
            _db.close()
    finally:
        delete_conversation(client, sid)


def test_legacy_clear_conversation(client, monkeypatch):
    sid = "ft_clear_" + uuid.uuid4().hex[:8]
    install_llm(monkeypatch)
    try:
        client.post("/api/chat/", json={"message": "测试", "session_id": sid, "stream": False})
        r = client.delete(f"/api/chat/conversation/{sid}")
        assert r.status_code == 200 and r.json()["success"]

        # H2: 清空后 DB 消息行同步删除（FTS 由 DELETE 触发器清理），刷新不应复现
        msgs = client.get(f"/api/chat/conversations/{sid}/messages").json()["data"]
        assert msgs == []
    finally:
        delete_conversation(client, sid)


def test_conversation_list_last_message_latest(client, monkeypatch):
    """H1: 会话列表 last_message 取最新消息（按 created_at），而非随机 UUID"""
    import uuid as _uuid
    from backend.database import SessionLocal
    from backend.models.audit import Conversation, ConversationMessage
    from datetime import datetime, timedelta

    conv_id = "ft_last_" + _uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        db.add(Conversation(id=conv_id, title="last_message 测试"))
        # 故意乱序 id（id 是随机 UUID），created_at 第一条约早
        db.add(ConversationMessage(
            id=str(_uuid.uuid4()), conversation_id=conv_id, role="assistant",
            content="最新回复", message_type="text",
            created_at=datetime.now() - timedelta(seconds=1),
        ))
        db.add(ConversationMessage(
            id=str(_uuid.uuid4()), conversation_id=conv_id, role="user",
            content="较老消息", message_type="text",
            created_at=datetime.now() - timedelta(seconds=30),
        ))
        db.commit()
    finally:
        db.close()

    try:
        convs = client.get("/api/chat/conversations").json()["data"]
        target = next(c for c in convs if c["id"] == conv_id)
        assert target["last_message"] == "最新回复"
    finally:
        db = SessionLocal()
        try:
            db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == conv_id).delete()
            db.query(Conversation).filter(Conversation.id == conv_id).delete()
            db.commit()
        finally:
            db.close()


def test_tool_invalid_json_params_degrades(client, monkeypatch, full_security):
    """H7: 工具参数为非法 JSON 时不中断整轮，降级为失败结果"""
    sid = "ft_badjson_" + uuid.uuid4().hex[:8]
    tname = "ft_echo_badjson_" + uuid.uuid4().hex[:6]

    class BadArgsLLM:
        def __init__(self, name):
            self.name = name
            self.calls = 0
        def _pop(self):
            self.calls += 1
            if self.calls == 1:
                return {
                    "content": "", "role": "assistant",
                    "tool_calls": [{
                        "id": "tc_bad",
                        "type": "function",
                        "function": {"name": self.name, "arguments": "{not json"},
                    }],
                    "finish_reason": "tool_calls",
                    "usage": {"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5},
                }
            return _text("已降级处理")
        async def chat(self, messages=None, tools=None, stream=False):
            resp = self._pop()
            if stream:
                async def gen():
                    if resp.get("tool_calls"):
                        yield {"type": "tool_calls", "tool_calls": resp["tool_calls"]}
                        yield {"type": "finish", "finish_reason": "tool_calls", "usage": {}}
                    else:
                        for ch in resp.get("content", ""):
                            yield {"type": "content", "content": ch}
                        yield {"type": "finish", "finish_reason": "stop",
                               "usage": resp.get("usage", {})}
                return gen()
            return resp

    fake = BadArgsLLM(tname)
    monkeypatch.setattr(agent, "llm_client", fake)
    create_custom_tool(client, tname, "echo {text}")
    try:
        r = client.post("/api/chat/", json={
            "message": "执行", "session_id": sid, "stream": False,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        # 不崩溃，继续返回文本总结
        assert body["type"] == "text"
        assert "已降级处理" in body["message"]

        msgs = client.get(f"/api/chat/conversations/{sid}/messages").json()["data"]
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        assert tool_msgs, "应有失败的工具结果消息"
        assert "非法 JSON" in (tool_msgs[0]["content"] or "")
    finally:
        delete_custom_tool(client, tname)
        delete_conversation(client, sid)


# --------------------------------------------------------------------------
# 3. 流式 SSE
# --------------------------------------------------------------------------

def test_streaming_sse(client, monkeypatch):
    sid = "ft_stream_" + uuid.uuid4().hex[:8]
    install_llm(monkeypatch)
    try:
        r = client.post("/api/chat/", json={
            "message": "流式输出", "session_id": sid, "stream": True,
        })
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/event-stream")
        events = sse_events(r.text)

        types = [e["type"] for e in events]
        assert "context_usage" in types
        assert "content" in types
        assert "finish" in types
        assert types[-1] == "finish"
        text = "".join(e["content"] for e in events if e["type"] == "content")
        assert "功能测试通过" in text

        # 上下文占用计算事件包含关键字段
        cu = next(e for e in events if e["type"] == "context_usage")
        for key in ("system", "tools", "messages", "total", "limit", "percent"):
            assert key in cu
    finally:
        delete_conversation(client, sid)


# --------------------------------------------------------------------------
# 4. 安全审批流程（once / always / reject / 非法 reply）
# --------------------------------------------------------------------------

def _ask_tool_call(client, monkeypatch, sid, tool_name, script):
    """发起一次需要审批的工具调用，返回 permission_required 响应"""
    body = client.post("/api/chat/", json={
        "message": "帮我执行工具", "session_id": sid, "stream": False,
    }).json()
    assert body["success"] is True
    assert body["type"] == "permission_required", body
    assert body["tool_name"] == tool_name
    assert "request" in body and body["request"]["request_id"]
    return body


def test_approval_once_flow(client, monkeypatch, full_security):
    sid = "ft_aprv_once_" + uuid.uuid4().hex[:8]
    tname = "ft_echo_once_" + uuid.uuid4().hex[:6]
    install_llm(monkeypatch, script=[_tool(tname, {"text": "hi"}), _text("已执行")])
    create_custom_tool(client, tname, "echo {text}", requires_approval=True)
    try:
        # 第一次：应要求权限
        resp = _ask_tool_call(client, monkeypatch, sid, tname, [_tool(tname, {"text": "hi"})])
        request_id = resp["request"]["request_id"]

        # 审批 once → 执行工具 → 模型总结
        r = client.post("/api/chat/confirm", json={
            "session_id": sid, "request_id": request_id, "reply": "once", "stream": False,
        })
        body = r.json()
        assert body["success"] is True and body["type"] == "text"
        assert "已执行" in body["message"]
        assert body["tool_result"]["success"] is True

        # 历史包含 用户批准记录 + tool 结果 + assistant 总结
        msgs = client.get(f"/api/chat/conversations/{sid}/messages").json()["data"]
        roles = [m["role"] for m in msgs]
        assert "user" in roles and "assistant" in roles and "tool" in roles

        # 审计：确认节点 + 执行节点
        trace_id = resp["trace_id"]
        trace = client.get(f"/api/audit/trace/{trace_id}").json()["data"]
        stages = [s["stage"] for s in trace["stages"]]
        assert "user_confirmation" in stages
        assert "execution" in stages
        assert "safety_check" in stages
    finally:
        delete_custom_tool(client, tname)
        delete_conversation(client, sid)


def test_approval_always_persists(client, monkeypatch, full_security):
    sid = "ft_aprv_always_" + uuid.uuid4().hex[:8]
    tname = "ft_echo_always_" + uuid.uuid4().hex[:6]
    install_llm(monkeypatch, script=[
        _tool(tname, {"text": "a"}), _text("第一次已执行"),
        _tool(tname, {"text": "b"}), _text("第二次已执行"),
    ])
    create_custom_tool(client, tname, "echo {text}", requires_approval=True)
    try:
        resp = _ask_tool_call(client, monkeypatch, sid, tname, [_tool(tname, {"text": "a"})])
        request_id = resp["request"]["request_id"]
        r = client.post("/api/chat/confirm", json={
            "session_id": sid, "request_id": request_id, "reply": "always", "stream": False,
        })
        assert r.json()["success"] is True

        # 第二次调用：always 规则命中 → 自动执行，不再询问
        r = client.post("/api/chat/", json={
            "message": "再次执行", "session_id": sid, "stream": False,
        })
        body = r.json()
        assert body["success"] is True
        assert body.get("type") != "permission_required"
        assert "第二次已执行" in body["message"]

        # 工具结果已在历史中
        msgs = client.get(f"/api/chat/conversations/{sid}/messages").json()["data"]
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        assert all('"success": true' in (m["content"] or "") for m in tool_msgs)
    finally:
        delete_custom_tool(client, tname)
        delete_conversation(client, sid)


def test_approval_reject(client, monkeypatch, full_security):
    sid = "ft_aprv_reject_" + uuid.uuid4().hex[:8]
    tname = "ft_echo_reject_" + uuid.uuid4().hex[:6]
    install_llm(monkeypatch, script=[_tool(tname, {"text": "x"})])
    create_custom_tool(client, tname, "echo {text}", requires_approval=True)
    try:
        resp = _ask_tool_call(client, monkeypatch, sid, tname, [_tool(tname, {"text": "x"})])
        request_id = resp["request"]["request_id"]

        r = client.post("/api/chat/confirm", json={
            "session_id": sid, "request_id": request_id, "reply": "reject", "stream": False,
        })
        body = r.json()
        assert body["success"] is True
        assert "已取消执行" in body["message"]

        # 历史记录用户拒绝
        msgs = client.get(f"/api/chat/conversations/{sid}/messages").json()["data"]
        assert any("拒绝" in (m["content"] or "") and m["role"] == "user" for m in msgs)
    finally:
        delete_custom_tool(client, tname)
        delete_conversation(client, sid)


def test_approval_invalid_reply(client, monkeypatch, full_security):
    sid = "ft_aprv_bad_" + uuid.uuid4().hex[:8]
    tname = "ft_echo_bad_" + uuid.uuid4().hex[:6]
    install_llm(monkeypatch, script=[_tool(tname, {"text": "x"})])
    create_custom_tool(client, tname, "echo {text}", requires_approval=True)
    try:
        resp = _ask_tool_call(client, monkeypatch, sid, tname, [_tool(tname, {"text": "x"})])
        r = client.post("/api/chat/confirm", json={
            "session_id": sid, "request_id": resp["request"]["request_id"], "reply": "maybe",
        })
        assert r.status_code == 400
        assert "once" in r.json()["detail"]
    finally:
        delete_custom_tool(client, tname)
        delete_conversation(client, sid)


# --------------------------------------------------------------------------
# 5. 沙箱拦截 + 输出校验
# --------------------------------------------------------------------------

def test_sandbox_blocks_forbidden_path(client, monkeypatch, full_security):
    sid = "ft_sbx_" + uuid.uuid4().hex[:8]
    tname = "ft_ls_" + uuid.uuid4().hex[:6]
    # 自定义工具带 path 参数，指向 /proc 被沙箱拦截
    install_llm(monkeypatch, script=[
        _tool(tname, {"path": "/proc/ft_test"}), _text("已完成"),
    ])
    create_custom_tool(
        client, tname, "ls {path}",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "路径"}},
            "required": ["path"],
        },
    )
    try:
        r = client.post("/api/chat/", json={
            "message": "帮我查看文件", "session_id": sid, "stream": False,
        })
        body = r.json()
        assert body["success"] is True

        # 审计：安全拦截决策 REJECT
        trace_id = body["trace_id"]
        trace = client.get(f"/api/audit/trace/{trace_id}").json()["data"]
        safety = [s for s in trace["stages"] if s["stage"] == "safety_check"]
        assert safety, "应存在 safety_check 阶段"
        assert any(s.get("security_decision", "").upper() == "REJECT" for s in safety)

        # 工具调用被记录为失败结果
        msgs = client.get(f"/api/chat/conversations/{sid}/messages").json()["data"]
        assert any(m["role"] == "tool" and "error" in (m["content"] or "") for m in msgs)
    finally:
        delete_custom_tool(client, tname)
        delete_conversation(client, sid)


def test_output_validator_blocks_dangerous_llm_content(client, monkeypatch):
    sid = "ft_ov_" + uuid.uuid4().hex[:8]
    install_llm(monkeypatch, script=[_text("请执行：\n```bash\nrm -rf /tmp/x\n```")])
    try:
        r = client.post("/api/chat/", json={
            "message": "给我一个命令", "session_id": sid, "stream": False,
        })
        body = r.json()
        assert body["success"] is True
        assert body["message"].startswith("[安全拦截]")
        assert "rm -rf" in body["message"]  # 拦截信息会回显触发的命令
        assert "请重新描述您的需求" in body["message"]
    finally:
        delete_conversation(client, sid)


# --------------------------------------------------------------------------
# 6. 全文检索 + 审计查询
# --------------------------------------------------------------------------

def test_search_messages_and_audit(client, monkeypatch):
    sid = "ft_srch_" + uuid.uuid4().hex[:8]
    marker = "OPSCHAT_FT_MARKER_" + uuid.uuid4().hex[:6]
    install_llm(monkeypatch, script=[_text("结果 " + marker + " 完成")])
    try:
        r = client.post("/api/chat/", json={
            "message": "查询 " + marker + " 信息", "session_id": sid, "stream": False,
        })
        trace_id = r.json()["trace_id"]

        # 消息检索
        res = client.get(f"/api/search?q={marker}&scope=messages").json()
        assert res["success"] is True and res["total"] >= 1
        assert any(item["conversation_id"] == sid for item in res["data"])

        # 审计检索（response 阶段内容含 marker）
        res = client.get(f"/api/search?q={marker}&scope=audit").json()
        assert res["success"] is True and res["total"] >= 1

        # 审计日志按 trace 过滤
        logs = client.get(f"/api/audit/logs?trace_id={trace_id}").json()
        assert logs["success"] is True and logs["total"] >= 1
        assert all(l["trace_id"] == trace_id for l in logs["data"])

        # 空查询
        assert client.get("/api/search").json()["data"] == []
    finally:
        delete_conversation(client, sid)


# --------------------------------------------------------------------------
# 7. 自定义工具 CRUD
# --------------------------------------------------------------------------

def test_custom_tools_crud(client):
    tname = "ft_crud_" + uuid.uuid4().hex[:6]
    try:
        created = create_custom_tool(client, tname, "echo hello")
        assert created["name"] == tname and created["is_enabled"] is True

        # 重复名称 → 400
        dup = client.post("/api/custom-tools/", json={
            "name": tname, "description": "dup", "command_template": "echo",
        })
        assert dup.status_code == 400

        # 模板
        tmpl = client.get("/api/custom-tools/templates").json()
        assert tmpl["success"] is True and len(tmpl["data"]) >= 5

        # 更新
        up = client.put(f"/api/custom-tools/{created['id']}", json={
            "description": "已更新", "requires_approval": True,
        })
        assert up.status_code == 200
        assert up.json()["data"]["description"] == "已更新"
        assert up.json()["data"]["requires_approval"] is True

        # 删除
        d = client.delete(f"/api/custom-tools/{created['id']}")
        assert d.status_code == 200 and d.json()["success"]
        assert client.delete(f"/api/custom-tools/{created['id']}").status_code == 404
    finally:
        delete_custom_tool(client, tname)


def test_custom_tools_validation(client):
    """创建/更新时非法工具名与 risk_level 一律 400（与 pydantic 校验一致）"""
    try:
        # 非法工具名（含空格/连字符）→ 400
        r = client.post("/api/custom-tools/", json={
            "name": "bad name!", "description": "t", "command_template": "echo",
        })
        assert r.status_code == 400
        assert "工具名称" in r.json()["detail"]

        # 非法 risk_level → 400
        r = client.post("/api/custom-tools/", json={
            "name": "ft_val_" + uuid.uuid4().hex[:6], "description": "t",
            "command_template": "echo", "risk_level": "critical",
        })
        assert r.status_code == 400
        assert "risk_level" in r.json()["detail"]

        # 数字开头 → 400
        r = client.post("/api/custom-tools/", json={
            "name": "1bad_tool", "description": "t", "command_template": "echo",
        })
        assert r.status_code == 400

        # 更新路径同样校验 risk_level
        created = create_custom_tool(client, "ft_val_upd_" + uuid.uuid4().hex[:6], "echo")
        try:
            r = client.put(f"/api/custom-tools/{created['id']}", json={"risk_level": "critical"})
            assert r.status_code == 400
            assert "risk_level" in r.json()["detail"]
        finally:
            delete_custom_tool(client, created["name"])
    finally:
        pass


def test_approval_flow_stream_confirm(client, monkeypatch, full_security):
    """审批卡前端真实路径：once 走 SSE 流式 confirm（前端 confirmPermissionStream）"""
    sid = "ft_aprv_strm_" + uuid.uuid4().hex[:8]
    tname = "ft_echo_strm_" + uuid.uuid4().hex[:6]
    install_llm(monkeypatch, script=[_tool(tname, {"text": "hi"}), _text("已执行")])
    create_custom_tool(client, tname, "echo {text}", requires_approval=True)
    try:
        resp = _ask_tool_call(client, monkeypatch, sid, tname, [_tool(tname, {"text": "hi"})])
        request_id = resp["request"]["request_id"]

        r = client.post("/api/chat/confirm", json={
            "session_id": sid, "request_id": request_id, "reply": "once", "stream": True,
        })
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/event-stream")
        events = sse_events(r.text)

        types = [e["type"] for e in events]
        # 事件顺序：tool_result → content → finish
        assert "tool_result" in types
        assert "content" in types
        assert "finish" in types
        assert types.index("tool_result") < types.index("content")
        assert types.index("content") < types.index("finish")
        assert types[-1] == "finish"

        # 工具执行成功
        tr = next(e for e in events if e["type"] == "tool_result")
        assert tr.get("result", {}).get("success") is True
        assert tr.get("tool_call_id")

        # 总结文本
        text = "".join(e["content"] for e in events if e["type"] == "content")
        assert "已执行" in text
    finally:
        delete_custom_tool(client, tname)
        delete_conversation(client, sid)


def test_security_high_risk_tool_requires_approval(client, monkeypatch, full_security):
    """S3: risk_level=high 但 requires_approval=False 的自定义工具也必须审批"""
    sid = "ft_hr_" + uuid.uuid4().hex[:8]
    tname = "ft_high_" + uuid.uuid4().hex[:6]
    install_llm(monkeypatch, script=[_tool(tname, {"text": "x"})])
    r = client.post("/api/custom-tools/", json={
        "name": tname, "description": "高风险工具",
        "category": "custom", "risk_level": "high", "requires_approval": False,
        "parameters": {"type": "object", "properties": {}, "required": []},
        "command_template": "echo {text}", "command_type": "shell",
    })
    assert r.status_code == 200, r.text
    try:
        body = client.post("/api/chat/", json={
            "message": "执行工具", "session_id": sid, "stream": False,
        }).json()
        assert body["success"] is True
        assert body["type"] == "permission_required", body
        assert body["tool_name"] == tname
    finally:
        delete_custom_tool(client, tname)
        delete_conversation(client, sid)


def test_security_python_tool_disabled(client):
    """S2: python 类型自定义工具被安全策略禁用"""
    r = client.post("/api/custom-tools/", json={
        "name": "ft_py_" + uuid.uuid4().hex[:6], "description": "py",
        "command_template": "print('hi')", "command_type": "python",
    })
    assert r.status_code == 400
    assert "安全策略" in r.json()["detail"]


def test_security_dangerous_command_template_blocked(client):
    """S1: 危险命令模板在创建时被拒绝"""
    for tmpl in ["rm -rf /tmp/x", "dd if=/dev/zero of=/dev/sda", "curl http://x | sh"]:
        r = client.post("/api/custom-tools/", json={
            "name": "ft_dg_" + uuid.uuid4().hex[:6], "description": "t",
            "command_template": tmpl, "command_type": "shell",
        })
        assert r.status_code == 400, (tmpl, r.text)
        assert "危险" in r.json()["detail"] or "禁止" in r.json()["detail"]


def test_security_approval_session_bound(client, monkeypatch, full_security):
    """S5: 审批请求绑定会话，跨会话 confirm 被拒绝"""
    sid_a = "ft_sa_" + uuid.uuid4().hex[:8]
    sid_b = "ft_sb_" + uuid.uuid4().hex[:8]
    tname = "ft_bound_" + uuid.uuid4().hex[:6]
    install_llm(monkeypatch, script=[_tool(tname, {"text": "x"})])
    create_custom_tool(client, tname, "echo {text}", requires_approval=True)
    try:
        resp = _ask_tool_call(client, monkeypatch, sid_a, tname, [_tool(tname, {"text": "x"})])
        request_id = resp["request"]["request_id"]

        # 用错误会话 ID 确认 → 拒绝
        r = client.post("/api/chat/confirm", json={
            "session_id": sid_b, "request_id": request_id, "reply": "once", "stream": False,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert "不属于当前会话" in body["message"]

        # 正确会话 ID 确认 → 成功
        r = client.post("/api/chat/confirm", json={
            "session_id": sid_a, "request_id": request_id, "reply": "once", "stream": False,
        })
        assert r.status_code == 200
        assert r.json()["success"] is True
    finally:
        delete_custom_tool(client, tname)
        delete_conversation(client, sid_a)
        delete_conversation(client, sid_b)


# --------------------------------------------------------------------------
# 8. 模型档案管理（功能链路）
# --------------------------------------------------------------------------

def test_model_profiles_functional(client):
    pid = "ft_prof_" + uuid.uuid4().hex[:6]
    try:
        # 创建
        r = client.post("/api/settings/models", json={
            "id": pid, "name": "功能档案", "base_url": "https://api.example.com/v1",
            "api_key": "sk-ft", "models": ["ft-model-a", "ft-model-b"],
            "active_model": "ft-model-a", "is_active": True,
        })
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["id"] == pid and body["api_key_set"] is True
        assert "sk-ft" not in r.text  # 密钥不回显

        # 列表激活状态
        lst = client.get("/api/settings/models").json()["data"]["profiles"]
        active = next(p for p in lst if p["id"] == pid)
        assert active["is_active"] is True

        # 测试连接：未配置密钥时给出明确错误
        t = client.post(f"/api/settings/models/{pid}/test").json()
        assert t.get("success") is False or "API" in t.get("message", "")

        # 删除
        d = client.delete(f"/api/settings/models/{pid}")
        assert d.status_code == 200 and d.json()["success"]
    finally:
        try:
            client.delete(f"/api/settings/models/{pid}")
        except Exception:
            pass


# --------------------------------------------------------------------------
# 9. 设置与模型目录
# --------------------------------------------------------------------------

def test_settings_and_model_catalog(client):
    s = client.get("/api/settings/").json()
    assert s["success"] is True
    for key in ("api", "security", "system", "providers"):
        assert key in s["data"]

    cat = client.get("/api/models/").json()
    assert cat["success"] is True and len(cat["data"]) >= 1
    provider = next(iter(cat["data"]))
    detail = client.get(f"/api/models/{provider}").json()
    assert detail["success"] is True
    assert detail["data"]["name"] == cat["data"][provider]["name"]

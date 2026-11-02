"""Phase 8 隔离验收：模拟模型验证运维助手 SSE、持久化与错误路径，不触碰用户数据。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config
from app.agent.tools import execute_tool
from app.assistant import service as assistant_service_module
from app.assistant.routes import ASSISTANT_SYSTEM_PROMPT
from app.llm.provider import LLMClient
from app.server import create_app

SETTINGS = {"provider": "zhipu", "base_url": "https://example.invalid/v4", "model": "mock", "api_key": "fake-only"}


def result(value: dict | str) -> dict:
    return {"content": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), "model": "mock"}


def stream_of(*chunks: str):
    async def generator(*args, **kwargs):
        for chunk in chunks:
            yield chunk
    return generator


def parse_sse(response) -> list[dict]:
    events = []
    for line in response.text.splitlines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    assert "【命令：" in ASSISTANT_SYSTEM_PROMPT and "【配置：" in ASSISTANT_SYSTEM_PROMPT
    with tempfile.TemporaryDirectory() as folder, \
            patch.object(config, "DB_PATH", Path(folder) / "test.db"), \
            patch.object(config, "ASSISTANT_FILES_DIR", Path(folder) / "asst_files"), \
            patch.object(config, "AGENT_FILES_DIR", Path(folder) / "agent_files"), \
            patch.object(assistant_service_module, "WORKSPACE_JSON", Path(folder) / "agent_workspace.json"):
        client = TestClient(create_app())

        # A：工具轨迹 + 流式终答 + 原子落库
        chat_replies = [result({"action": "tool", "tool": "search_kb", "args": {"q": "nginx", "limit": 3}}),
                        result({"action": "final"})]
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=chat_replies), \
             patch.object(LLMClient, "chat_stream", new=stream_of("nginx -s reload", "【配置：nginx/nginx -s reload】")):
            response = client.post("/api/assistant/chat", json={"message": "nginx 怎么平滑重载"})
        assert response.status_code == 200 and "text/event-stream" in response.headers["content-type"]
        events = parse_sse(response)
        assert events[0]["tool"] == "search_kb" and events[0]["args"] == {"q": "nginx", "limit": 3}
        deltas = [e["delta"] for e in events if "delta" in e]
        done = [e for e in events if e.get("done")][0]
        assert "".join(deltas).startswith("nginx -s reload") and done["session_id"] == 1

        messages = client.get("/api/assistant/sessions/1").json()["messages"]
        assert [m["role"] for m in messages] == ["user", "tool", "assistant"]
        assert json.loads(messages[1]["content"])["tool"] == "search_kb"
        sessions = client.get("/api/assistant/sessions").json()["items"]
        assert sessions[0]["title"] == "nginx 怎么平滑重载" and sessions[0]["id"] == 1

        # B：同会话第二轮，历史上下文进入模型请求；直接作答路径
        captured: list[list[dict]] = []
        async def capture_chat(self, messages, **kwargs):
            captured.append(messages)
            return result({"action": "final", "answer": "结合上下文的直接回答"})
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", new=capture_chat):
            response = client.post("/api/assistant/chat", json={"message": "那它和 du 的区别呢", "session_id": 1})
        events = parse_sse(response)
        assert [e.get("delta") for e in events if "delta" in e] == ["结合上下文的直接回答"]
        assert events[-1]["done"] and events[-1]["session_id"] == 1
        history_text = json.dumps(captured[0], ensure_ascii=False)
        assert "nginx 怎么平滑重载" in history_text and "nginx -s reload" in history_text  # 历史用户+助手都进入上下文
        messages = client.get("/api/assistant/sessions/1").json()["messages"]
        assert len(messages) == 5  # 轮1：user+tool+assistant；轮2：user+assistant

        # C：无密钥 → 明确错误且不建会话
        with patch("app.assistant.routes.effective_settings", return_value={"model": "x"}):
            events = parse_sse(client.post("/api/assistant/chat", json={"message": "hi"}))
        assert events[0].get("error") and "设置" in events[0]["error"]
        assert len(client.get("/api/assistant/sessions").json()["items"]) == 1

        # D：不存在的会话 / 模型中途失败 → error 且不落库
        assert parse_sse(client.post("/api/assistant/chat", json={"message": "x", "session_id": 99}))[0].get("error")
        async def broken_stream(*args, **kwargs):
            from app.llm.provider import LLMError
            yield "半句"
            raise LLMError("连接模型服务失败")
        async def crashed_stream(*args, **kwargs):
            yield "半"
            raise RuntimeError("boom")
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[result({"action": "final"})]), \
             patch.object(LLMClient, "chat_stream", new=broken_stream):
            events = parse_sse(client.post("/api/assistant/chat", json={"message": "你好"}))
        assert any(e.get("delta") == "半句" for e in events) and events[-1].get("error") == "连接模型服务失败"
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[result({"action": "final"})]), \
             patch.object(LLMClient, "chat_stream", new=crashed_stream):
            events = parse_sse(client.post("/api/assistant/chat", json={"message": "意外"}))
        assert events[-1].get("error", "").startswith("回答生成失败")
        assert len(client.get("/api/assistant/sessions").json()["items"]) == 1  # 失败轮未建会话

        # E：三次协议解析失败 → 退回无工具直答
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[result("bad")] * 3), \
             patch.object(LLMClient, "chat_stream", new=stream_of("降级回答")):
            events = parse_sse(client.post("/api/assistant/chat", json={"message": "再问一个"}))
        assert [e.get("delta") for e in events if "delta" in e] == ["降级回答"] and events[-1]["done"]

        # F：会话删除连带消息
        assert client.delete("/api/assistant/sessions/1").json() == {"ok": True}
        assert client.get("/api/assistant/sessions/1").status_code == 404
        assert client.delete("/api/assistant/sessions/1").status_code == 404

        # G：附件上传、多模态装配与回显
        from pathlib import Path as _P
        agent_dir = _P(folder) / "agent_files"
        upload = client.post("/api/assistant/files",
                             files={"file": ("nginx.conf", "server {\n listen 80;\n}\n".encode(), "text/plain")})
        assert upload.status_code == 200, upload.text
        text_id = upload.json()["id"]
        assert upload.json()["kind"] == "text"
        image_id = client.post("/api/assistant/files",
                               files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")}).json()["id"]
        assert client.post("/api/assistant/files", files={"file": ("evil.exe", b"MZ", "application/octet-stream")}).status_code == 415
        assert client.post("/api/assistant/files", files={"file": ("big.log", b"x" * (5 * 1024 * 1024 + 1), "text/plain")}).status_code == 413
        captured_stream: list[list[dict]] = []
        async def capture_stream(self, messages, **kwargs):
            captured_stream.append(messages)
            yield "收到"
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[result({"action": "final"})]), \
             patch.object(LLMClient, "chat_stream", new=capture_stream):
            events = parse_sse(client.post("/api/assistant/chat",
                                           json={"message": "看看这两个文件", "attachments": [text_id, image_id]}))
        done = [e for e in events if e.get("done")][0]
        attach_session = done["session_id"]
        multimodal = [m for m in captured_stream[0] if isinstance(m.get("content"), list)]
        assert multimodal, "图片未并入终答消息"
        parts = multimodal[0]["content"]
        assert any(p.get("type") == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,") for p in parts)
        assert any(p.get("type") == "text" and "nginx.conf" in p["text"] and "listen 80" in p["text"] for p in parts)
        rows = client.get(f"/api/assistant/sessions/{attach_session}").json()["messages"]
        user_rows = [m for m in rows if m["role"] == "user"]
        assert any(a["name"] == "shot.png" for a in user_rows[-1]["attachments"])
        assert client.get(f"/api/assistant/files/{image_id}/content").status_code == 200
        # 已归属附件不可复用
        assert parse_sse(client.post("/api/assistant/chat",
                                     json={"message": "again", "attachments": [text_id]}))[0].get("error")

        # H：write_file 提案 → 用户确认落盘 / 取消 / 穿越与直接调用防线
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[
                 result({"action": "tool", "tool": "write_file",
                         "args": {"filename": "deploy.conf", "content": "key=value\n", "note": "部署配置"}}),
                 result({"action": "final"})]), \
             patch.object(LLMClient, "chat_stream", new=stream_of("已提交提案，", "说明用途")):
            events = parse_sse(client.post("/api/assistant/chat",
                                           json={"message": "帮我生成部署配置文件", "session_id": attach_session}))
        proposals = [e for e in events if "proposal" in e]
        assert proposals and proposals[0]["proposal"]["filename"] == "deploy.conf"
        assert not agent_dir.joinpath("deploy.conf").exists()  # 未确认绝不写盘
        applied = client.post("/api/assistant/files/apply",
                              json={"session_id": attach_session, "filename": "deploy.conf"})
        assert applied.status_code == 200 and "已写入 agent_files/deploy.conf" in applied.json()["outcome"], applied.text
        assert agent_dir.joinpath("deploy.conf").read_text(encoding="utf-8") == "key=value\n"
        assert client.post("/api/assistant/files/apply",
                           json={"session_id": attach_session, "filename": "deploy.conf"}).status_code == 404
        assert client.post("/api/assistant/files/apply",
                           json={"session_id": attach_session, "filename": "../evil"}).status_code == 400
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[
                 result({"action": "tool", "tool": "write_file",
                         "args": {"filename": "../evil.txt", "content": "x"}}),
                 result({"action": "final"})]), \
             patch.object(LLMClient, "chat_stream", new=stream_of("ok")):
            events = parse_sse(client.post("/api/assistant/chat",
                                           json={"message": "穿越测试", "session_id": attach_session}))
        assert not [e for e in events if "proposal" in e] and not agent_dir.parent.joinpath("evil.txt").exists()
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[
                 result({"action": "tool", "tool": "write_file",
                         "args": {"filename": "tmp.yaml", "content": "a: 1"}}),
                 result({"action": "final"})]), \
             patch.object(LLMClient, "chat_stream", new=stream_of("ok")):
            parse_sse(client.post("/api/assistant/chat",
                                  json={"message": "再来一个", "session_id": attach_session}))
        cancelled = client.post("/api/assistant/files/cancel",
                                json={"session_id": attach_session, "filename": "tmp.yaml"})
        assert cancelled.status_code == 200 and "已取消" in cancelled.json()["outcome"]
        assert not agent_dir.joinpath("tmp.yaml").exists()
        assert execute_tool("write_file", {"filename": "x.conf", "content": "y"})["ok"] is False  # 直接调用防线

        # K：工作目录下的会话归属与目录移除迁移
        ws_a = Path(folder) / "ws_a"; ws_a.mkdir()
        ws_b = Path(folder) / "ws_b"; ws_b.mkdir()
        client.put("/api/assistant/workspace", json={"directories": [str(ws_a), str(ws_b)]})
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[result({"action": "final"})]), \
             patch.object(LLMClient, "chat_stream", new=stream_of("A 目录的回答")):
            events = parse_sse(client.post("/api/assistant/chat",
                                           json={"message": "A 目录的问题", "workspace": str(ws_a)}))
        sid_a = [e for e in events if e.get("done")][0]["session_id"]
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[result({"action": "final"})]), \
             patch.object(LLMClient, "chat_stream", new=stream_of("B 目录的回答")):
            events = parse_sse(client.post("/api/assistant/chat",
                                           json={"message": "B 目录的问题", "workspace": str(ws_b)}))
        sid_b = [e for e in events if e.get("done")][0]["session_id"]
        in_a = [s["id"] for s in client.get("/api/assistant/sessions", params={"workspace": str(ws_a)}).json()["items"]]
        assert in_a == [sid_a]
        in_b = [s["id"] for s in client.get("/api/assistant/sessions", params={"workspace": str(ws_b)}).json()["items"]]
        assert in_b == [sid_b]
        assert len(client.get("/api/assistant/sessions").json()["items"]) >= 2  # 不带过滤=全部
        # 移除目录 A → 其会话迁入未分组，不再凭空消失
        client.put("/api/assistant/workspace", json={"directories": [str(ws_b)]})
        ungrouped = client.get("/api/assistant/sessions", params={"workspace": "__none__"}).json()["items"]
        assert sid_a in [s["id"] for s in ungrouped]
        assert client.get("/api/assistant/sessions", params={"workspace": str(ws_a)}).json()["items"] == []

        # I：工作目录授权（读写/生成/执行）与联网工具
        ws_dir = Path(folder) / "ws"; ws_dir.mkdir()
        (ws_dir / "sub").mkdir()
        assert client.put("/api/assistant/workspace", json={"directories": [str(ws_dir), "Z:\\不存在"]}).status_code == 400
        put = client.put("/api/assistant/workspace", json={"directories": [str(ws_dir)]})
        assert put.status_code == 200 and put.json()["directories"] == [str(ws_dir)]
        assert client.get("/api/assistant/workspace").json()["directories"] == [str(ws_dir)]
        import app.agent.tools as agent_tools
        from unittest.mock import patch as _patch
        listing = execute_tool("list_dir", {"path": ""})
        assert listing["ok"] and any(e["name"] == "sub" for e in listing["result"]["entries"])
        assert not execute_tool("read_workspace_file", {"path": "../evil.txt"})["ok"]  # 越界拒绝
        written = execute_tool("write_workspace_file", {"path": "sub/a.conf", "content": "k=v\n"})
        assert written["ok"] and (ws_dir / "sub" / "a.conf").read_text(encoding="utf-8") == "k=v\n"
        assert execute_tool("read_workspace_file", {"path": "sub/a.conf"})["result"]["content"] == "k=v\n"
        assert not execute_tool("write_workspace_file", {"path": str(Path(folder) / "escape.txt"), "content": "x"})["ok"]
        run = execute_tool("run_command", {"command": "echo opsmate-ws-ok"})
        assert run["ok"] and "opsmate-ws-ok" in run["result"]["stdout"], run
        # 资源管理器打开端点：仅限已授权目录（越界 400；mock startfile，不真弹窗）
        import os as verify_os
        with _patch.object(verify_os, "startfile") as fake_start:
            opened = client.post("/api/assistant/workspace/open", json={"path": str(ws_dir)})
            assert opened.status_code == 200 and opened.json()["ok"]
            fake_start.assert_called_once_with(str(ws_dir))
            assert client.post("/api/assistant/workspace/open",
                               json={"path": str(ws_dir / "sub")}).status_code == 400
            assert client.post("/api/assistant/workspace/open",
                               json={"path": "Z:\\不存在"}).status_code == 400
        # 联网：搜索解析（mock HTML）与内网防护
        fake_bing = ('<li class="b_algo"><h2><a href="https://example.com/a">结果 A</a></h2>'
                     "<p>摘要 内容</p></li><li class=\"b_algo\"><h2><a href=\"https://example.com/b\">结果 B</a></h2></li>")
        class _FakeResp:
            status_code = 200
            headers = {"content-type": "text/html"}
            text = "<html><body>" + fake_bing + "</body></html>"
        with _patch.object(agent_tools.httpx, "get", return_value=_FakeResp()):
            search = execute_tool("web_search", {"q": "nginx"})
            assert search["ok"] and search["result"][0]["title"] == "结果 A" and "摘要" in search["result"][0]["snippet"]
            fetched = execute_tool("web_fetch", {"url": "https://example.com/page"})
            assert fetched["ok"] and "结果 A" in fetched["result"]["content"]
        assert not execute_tool("web_fetch", {"url": "http://127.0.0.1:5731/api/health"})["ok"]  # SSRF 防护
        assert not execute_tool("web_fetch", {"url": "file:///etc/passwd"})["ok"]
        client.put("/api/assistant/workspace", json={"directories": []})  # 清空授权
        assert not execute_tool("list_dir", {"path": ""})["ok"]

        # J：终答协议泄露守卫——流式开头的工具 JSON/围栏不进入 delta 与最终回答
        def saved_answer(events) -> str:
            sid = [e for e in events if e.get("done")][0]["session_id"]
            rows = client.get(f"/api/assistant/sessions/{sid}").json()["messages"]
            return [m["content"] for m in rows if m["role"] == "assistant"][-1]
        leak = '{"action":"tool","tool":"search_kb","args":{"q":"nginx","limit":3}}\n\n'
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[result({"action": "final"})]), \
             patch.object(LLMClient, "chat_stream", new=stream_of(leak, "真正的回答内容")):
            events = parse_sse(client.post("/api/assistant/chat", json={"message": "测试泄露"}))
        deltas = "".join(e["delta"] for e in events if "delta" in e)
        assert '"action"' not in deltas and "真正的回答内容" in deltas, deltas[:100]
        assert saved_answer(events).strip() == "真正的回答内容"
        # 纯协议输出 → 纠正重试一次成功
        calls = {"n": 0}
        async def leak_then_ok(self, messages, **kwargs):
            calls["n"] += 1
            yield '{"ok": true, "result": []}' if calls["n"] == 1 else "重试后的回答"
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[result({"action": "final"})]), \
             patch.object(LLMClient, "chat_stream", new=leak_then_ok):
            events = parse_sse(client.post("/api/assistant/chat", json={"message": "纯协议测试"}))
        assert saved_answer(events).strip() == "重试后的回答" and calls["n"] == 2
        # 直接回答本身是协议 JSON → 转最终流式生成
        with patch("app.assistant.routes.effective_settings", return_value=SETTINGS), \
             patch.object(LLMClient, "chat", side_effect=[
                 result({"action": "final", "answer": '{"tool": "search_kb", "args": {}}'})]), \
             patch.object(LLMClient, "chat_stream", new=stream_of("最终生成的回答")):
            events = parse_sse(client.post("/api/assistant/chat", json={"message": "直答协议测试"}))
        assert saved_answer(events).strip() == "最终生成的回答"

    print("assistant ok")


if __name__ == "__main__":
    main()

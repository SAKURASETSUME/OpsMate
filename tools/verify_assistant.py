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
            patch.object(config, "AGENT_FILES_DIR", Path(folder) / "agent_files"):
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

    print("assistant ok")


if __name__ == "__main__":
    main()

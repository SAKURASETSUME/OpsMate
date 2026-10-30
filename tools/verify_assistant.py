"""Phase 8 隔离验收：模拟模型验证运维助手 SSE、持久化与错误路径，不触碰用户数据。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config
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
    with tempfile.TemporaryDirectory() as folder, patch.object(config, "DB_PATH", Path(folder) / "test.db"):
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
    print("assistant ok")


if __name__ == "__main__":
    main()

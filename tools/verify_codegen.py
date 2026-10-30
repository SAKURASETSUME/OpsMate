"""Phase 4 隔离验收：仅模拟模型，不执行生成脚本、不修改用户数据库。"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import config
from app.agent.engine import parse_object, run_agent
from app.agent.tools import execute_tool
from app.codegen.prompts import CODEGEN_SYSTEM_PROMPT
from app.codegen.routes import validate_payload
from app.agent.engine import AgentFormatError
from app.llm.provider import LLMClient
from app.server import create_app


def payload() -> dict:
    """最小可验收模型结果。"""
    return {"need_clarification": False, "script": "#!/usr/bin/env bash\n# 用途：隔离验证\n# 用法：bash script.sh\n# 参数：无\n# 依赖：bash、printf\n# AI生成，使用前请审阅\n# 适用：测试环境\n# 严格模式\nset -euo pipefail\n# 测试输出\nprintf '%s\\n' '测试'\n",
            "explanation": [{"lines": "1-3", "title": "脚本防护", "detail": "严格模式遇错停止"}] * 3,
            "warnings": ["执行前检查 cron 和 root 权限", "确认路径"], "usage": "bash script.sh"}


def result(value: dict | str) -> dict:
    return {"content": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), "model": "mock"}


def main() -> None:
    """运行隔离验证，任一失败直接退出。"""
    assert parse_object('```json\n{"ok":true}\n```')["ok"]
    assert parse_object('prefix {"ok":true} suffix')["ok"]
    assert len(validate_payload({"need_clarification": True, "questions": ["path?", "policy?", "scope?", "distro?"]})["questions"]) == 3
    async def verify_model_adapter() -> None:
        def respond(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["thinking"] == {"type": "enabled"}
            assert body["reasoning_effort"] == "low" and body["max_tokens"] >= 4096
            return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})
        adapted = LLMClient({"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "GLM-5.3", "api_key": "fake-only"}, httpx.MockTransport(respond))
        assert (await adapted.chat([], max_tokens=8))["ok"] is False
        generic = LLMClient({"base_url": "https://example.invalid/v1", "model": "GLM-5.3", "api_key": "fake-only"})
        assert generic._adapt_request({"max_tokens": 8}) == {"max_tokens": 8}
    asyncio.run(verify_model_adapter())
    with tempfile.TemporaryDirectory() as folder, patch.object(config, "DB_PATH", Path(folder) / "test.db"):
        client = TestClient(create_app())
        settings = {"provider": "custom", "base_url": "https://example.invalid", "model": "mock", "api_key": "fake-only"}
        replies = [result({"action": "tool", "tool": "search_commands", "args": {"q": "tar"}}),
                   result({"action": "final", "payload": payload()}), result(payload())]
        with patch("app.codegen.routes.effective_settings", return_value=settings), patch.object(LLMClient, "chat", new=AsyncMock(side_effect=replies)):
            response = client.post("/api/codegen/generate", json={"requirement": "nginx tar backup"})
            assert response.status_code == 200, response.text
            assert len(response.json()["steps"]) == 2
        history = client.get("/api/codegen/history").json()["items"]
        assert len(history) == 1
        detail = client.get(f"/api/codegen/history/{history[0]['id']}").json()
        assert detail["script"] == payload()["script"] and detail["steps"]
        assert execute_tool("search_history", {"q": "nginx"})["result"][0]["id"] == history[0]["id"]
        assert not execute_tool("shell", {"q": "whoami"})["ok"]
        assert not execute_tool("search_commands", {"q": "tar", "limit": "bad"})["ok"]
        clarification = {"need_clarification": True, "questions": ["请指定目标路径（建议 /var/log）"]}
        replies = [result({"action": "final", "payload": clarification}), result(clarification)]
        with patch("app.codegen.routes.effective_settings", return_value=settings), patch.object(LLMClient, "chat", new=AsyncMock(side_effect=replies)):
            response = client.post("/api/codegen/generate", json={"requirement": "cleanup"})
            assert response.json()["need_clarification"]
        assert len(client.get("/api/codegen/history").json()["items"]) == 1
        replies = [result("bad")] * 3 + [result(payload())]
        with patch.object(LLMClient, "chat", new=AsyncMock(side_effect=replies)):
            output, steps = asyncio.run(run_agent(LLMClient(settings), CODEGEN_SYSTEM_PROMPT, "test"))
            assert output["script"] and steps == []
        replies = [result({"action": "tool", "tool": "search_commands", "args": {"q": "tar"}})] * 5
        replies += [result({"action": "final", "payload": {}}), result(payload())]
        with patch.object(LLMClient, "chat", new=AsyncMock(side_effect=replies)):
            _, steps = asyncio.run(run_agent(LLMClient(settings), CODEGEN_SYSTEM_PROMPT, "test"))
            assert len(steps) == 6
        unsafe = payload()
        unsafe["script"] += 'mkdir -p $BACKUP_DIR\n'
        try:
            validate_payload(unsafe)
            raise AssertionError("Unquoted expansion accepted")
        except AgentFormatError:
            pass
        with patch("app.codegen.routes.effective_settings", return_value=settings), patch.object(LLMClient, "chat", new=AsyncMock(return_value=result("bad"))):
            assert client.post("/api/codegen/generate", json={"requirement": "test"}).status_code == 502
        with patch("app.codegen.routes.effective_settings", return_value={**settings, "api_key": ""}):
            assert client.post("/api/codegen/generate", json={"requirement": "test"}).status_code == 502
        assert client.get("/api/codegen/history/99999").status_code == 404
    print("PASS: JSON recovery, tool loop, atomic history/FTS, recall, clarification, fallback, invalid output, no key")


if __name__ == "__main__":
    main()

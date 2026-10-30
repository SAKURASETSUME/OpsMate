"""Phase 6 隔离验收：只使用临时库和模拟模型，不发送用户日志。"""
from __future__ import annotations
import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import config
from app.server import create_app
from app.agent.tools import execute_tool
from app.logs import store
from app.logs.analyze import LOG_ANALYZE_SYSTEM_PROMPT, analysis_events, build_materials
from app.logs.rules import classify_level, cluster_rows, normalize_message
from app.llm.provider import LLMError

REPORT = "## 结论速览\n发现连接错误。\n## 问题清单\n### 问题 1：连接失败\n- 证据：聚类 1，行号 1\n- 根因推断：不确定\n- 建议动作：检查连接。\n## 下一步排查建议\n检查服务。"


class FakeClient:
    """强制先下钻一次，再输出分段报告。"""
    mode = "ok"

    def __init__(self, settings: dict) -> None:
        self.calls = 0

    async def chat(self, messages: list, **kwargs: object) -> dict:
        self.calls += 1
        assert "OTHER_PRIVATE" not in json.dumps(messages)
        if self.mode == "malformed":
            return {"content": "invalid"}
        if self.mode == "budget" or self.calls == 1:
            return {"content": json.dumps({"action":"tool", "tool":"get_context", "args":{"log_id":1,"line_no":1,"around":1}})}
        return {"content": '{"action":"final","answer":"ready"}'}

    async def chat_stream(self, messages: list, **kwargs: object) -> AsyncIterator[str]:
        assert "OTHER_PRIVATE" not in json.dumps(messages)
        yield REPORT[:30]
        if self.mode == "network":
            raise LLMError("network failure test-secret")
        yield "broken" if self.mode == "invalid" else REPORT[30:]


def main() -> None:
    """覆盖聚类、材料预算、工具隔离、事件顺序、错误和历史。"""
    document = (Path(__file__).resolve().parents[1]/"OpsMate-施工提示词.md").read_text(encoding="utf-8")
    original = document.split("### 9.2 日志分析 LOG_ANALYZE_SYSTEM_PROMPT",1)[1].split("```text\n",1)[1].split("\n```",1)[0]
    assert LOG_ANALYZE_SYSTEM_PROMPT == original
    normalized = normalize_message('10.1.2.3 123.45 abcdef 123e4567-e89b-12d3-a456-426614174000 "abc" /var/log/a')
    assert normalized == "<ip> <num> <hex> <id> <str> <path>", normalized
    rows = ["2026-10-30 10:00:01 ERROR failed id=1", "    at example.run(Main.java:42)",
            "2026-10-30 10:00:02 ERROR failed id=2", "    at example.run(Main.java:43)",
            "WARN retry id=3", "WARN retry id=4", "WARN unique", "INFO end"]
    clusters, times = cluster_rows([{"line_no":i+1,"level":classify_level(text),"text":text} for i,text in enumerate(rows)])
    assert len(clusters) == 2 and clusters[0]["count"] == 2
    assert clusters[0]["first_no"] == 1 and clusters[0]["last_no"] == 4
    assert times == ["2026-10-30 10:00:01", "2026-10-30 10:00:02"]
    with tempfile.TemporaryDirectory() as folder, patch.object(config,"DB_PATH",Path(folder)/"test.db"), patch.object(config,"LOGS_DIR",Path(folder)/"raw"):
        client = TestClient(create_app())
        log = store.import_log("analysis fixture", "\n".join(rows).encode("utf-8"))
        other = store.import_log("other", b"ERROR OTHER_PRIVATE")
        large = store.import_log("budget fixture", "\n".join("ERROR category"+chr(103+i)+" "+"z"*400 for i in range(24)).encode("utf-8"))
        bounded, large_stats = build_materials(large["id"], "x"*1000)
        assert len(bounded) <= 6000 and len(large_stats["top_clusters"]) == 20
        assert len(json.loads(bounded)["top_clusters"]) == 20
        assert all(cluster["count"] == 1 for cluster in json.loads(bounded)["top_clusters"])
        log_id = log["id"]; assert log_id == 1
        assert not execute_tool("get_stats", {"log_id":other["id"]}, scope_log_id=log_id)["ok"]
        assert not execute_tool("get_stats", {"log_id":log_id})["ok"]
        context = execute_tool("get_context", {"log_id":log_id,"line_no":2,"around":999}, scope_log_id=log_id)
        assert context["ok"] and len(context["result"]["lines"]) <= 21
        material, stats = build_materials(log_id, "x"*1000)
        assert len(material) <= 6000 and len(json.loads(material)["top_clusters"]) == 2
        assert stats["top_clusters"] == clusters
        url = f"/api/logs/{log_id}"
        assert client.get(url+"/stats").json()["top_clusters"] == clusters
        settings = {"model":"fixture","api_key":"test-secret"}
        with patch("app.logs.analyze.LLMClient", FakeClient), patch("app.logs.routes.effective_settings", return_value=settings):
            def request() -> list[dict]:
                response = client.post(url+"/llm-analyze",json={})
                assert response.status_code == 200 and "text/event-stream" in response.headers["content-type"]
                return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
            events = request()
            assert [e["tool"] for e in events if "tool" in e] == ["get_stats","get_context"]
            assert "delta" in events[2] and events[-1]["done"]
            rid = events[-1]["report_id"]
            assert client.get(url+f"/reports/{rid}").json()["content"] == REPORT
            assert client.get(f'/api/logs/{other["id"]}/reports/{rid}').status_code == 404
            for mode in ("network", "invalid"):
                FakeClient.mode = mode
                events = request()
                assert "error" in events[-1] and "test-secret" not in json.dumps(events)
                assert len(store.list_reports(log_id)) == 1
            for mode, count in (("malformed",1),("budget",6)):
                FakeClient.mode = mode; events = request()
                assert events[-1]["done"] and len([e for e in events if "tool" in e]) == count
            FakeClient.mode = "ok"
            async def cancelled() -> bool:
                return True
            async def collect() -> list[dict]:
                return [event async for event in analysis_events(log_id,"",settings,cancelled)]
            assert asyncio.run(collect()) == []
            assert len(store.list_reports(log_id)) == 3
        with patch("app.logs.routes.effective_settings",return_value={}):
            response = client.post(url+"/llm-analyze",json={})
            assert "error" in response.text and "API key" in response.text
            assert len(store.list_reports(log_id)) == 3
    print("PASS: normalization, stack clustering, materials budget, log scope, ordered SSE, history, network/invalid/no-key/cancel, fallback and six-step budget")


if __name__ == "__main__":
    main()

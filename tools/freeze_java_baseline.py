"""导出 Java J0 契约快照，仅在临时数据库建表，不读取真实配置。"""
from __future__ import annotations
import json
import tempfile
import socket
import threading
import time
import httpx
import uvicorn
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from app import config
from app.server import create_app
from app.logs.store import connection
from app.codegen.routes import ensure_history
from app.assistant import service as assistant_service
from app.agent import mcp


def main() -> None:
    """生成 OpenAPI、SQLite DDL 和模块阶段矩阵。"""
    output = Path(__file__).resolve().parents[1]/"migration"/"j0"
    output.mkdir(parents=True, exist_ok=True)
    stages = {"commands":"J2", "kb":"J2", "versions":"J2", "notes":"J2",
              "logs":"J3/J4", "settings":"J4", "llm":"J4", "codegen":"J4", "assistant":"J5", "mcp":"J5", "health":"J1"}
    with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
        root = Path(folder)
        for name, path in {"DATA_DIR":root,"DB_PATH":root/"test.db", "LOGS_DIR":root/"logs",
                           "ASSISTANT_FILES_DIR":root/"attachments", "AGENT_FILES_DIR":root/"files",
                           "CONFIG_JSON":root/"config.json", "PROFILES_JSON":root/"profiles.json"}.items():
            stack.enter_context(patch.object(config, name, path))
        app = create_app()
        ensure_history()
        stack.enter_context(patch.object(assistant_service, "WORKSPACE_JSON", root/"workspace.json"))
        stack.enter_context(patch.object(mcp, "MCP_JSON", root/"mcp.json"))
        spec = app.openapi()
        (output/"openapi.json").write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding="utf-8")
        with connection() as conn:
            ddl = [row[0] for row in conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name")]
        (output/"schema.sql").write_text(";\n\n".join(ddl)+";\n",encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            server = uvicorn.Server(uvicorn.Config(app,log_level="error"))
            worker = threading.Thread(target=server.run,kwargs={"sockets":[sock]},daemon=True)
            worker.start()
            deadline = time.monotonic()+15
            while not server.started and time.monotonic()<deadline:
                time.sleep(0.02)
            assert server.started, "isolated HTTP server failed to start"
            captured = []
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{sock.getsockname()[1]}",trust_env=False,timeout=15) as client:
                    for path in ("/api/health","/api/commands?limit=1","/api/kb","/api/settings",
                                 "/api/codegen/history","/api/logs","/api/assistant/sessions",
                                 "/api/versions","/api/notes","/api/mcp"):
                        response = client.get(path)
                        assert response.status_code == 200, (path,response.status_code)
                        captured.append({"method":"GET","path":path,"status":200,"body":response.json()})
                    result = client.post("/api/logs",json={"title":"J0 synthetic","content":"ERROR failed id=1\nWARN retry id=2"})
                    assert result.status_code == 200
                    log_id = result.json()["id"]
                    stream = client.post(f"/api/logs/{log_id}/llm-analyze",json={})
                    assert stream.status_code == 200 and '"error"' in stream.text
                    captured.append({"method":"POST","path":"/api/logs/{id}/llm-analyze","status":200,"body":stream.text})
                (output/"http-baseline.json").write_text(json.dumps(captured,ensure_ascii=False,indent=2),encoding="utf-8")
            finally:
                server.should_exit = True
                worker.join(timeout=10)
                assert not worker.is_alive(), "HTTP server did not exit"
    rows = ["# J0 API 阶段矩阵", "", "来源为当前基线的 OpenAPI。字段与约束详见 openapi.json。文件和流事件需由 HTTP 回放补充。", "", "| 方法 | 路径 | 阶段 |", "|---|---|---|"]
    count = 0
    for path, methods in spec["paths"].items():
        group = path.split("/")[2]
        for method in methods:
            if method not in {"get","post","put","delete","patch"}:
                continue
            assert group in stages, path
            rows.append(f"| {method.upper()} | {path} | {stages[group]} |")
            count += 1
    (output/"API_MATRIX.md").write_text("\n".join(rows)+"\n",encoding="utf-8")
    print(f"Exported {count} endpoints; DDL and OpenAPI use temporary database")


if __name__ == "__main__":
    main()

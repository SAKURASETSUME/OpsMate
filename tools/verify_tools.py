"""版本管理与便签模块隔离验收（2026-10-30 用户需求）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config
from app.server import create_app


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory() as folder, patch.object(config, "DB_PATH", Path(folder) / "t.db"):
        client = TestClient(create_app())

        # 版本管理：建/查/搜/改/删与校验
        created = client.post("/api/versions", json={"package": "nginx", "version": "1.26.3",
                                                     "description": "生产稳定版", "release_date": "2026-10-01"})
        assert created.status_code == 200 and created.json()["package"] == "nginx", created.text
        vid = created.json()["id"]
        assert client.post("/api/versions", json={"package": "", "version": "1"}).status_code == 422
        client.post("/api/versions", json={"package": "redis", "version": "7.2.5", "description": "缓存升级"})
        items = client.get("/api/versions").json()["items"]
        assert len(items) == 2 and items[0]["package"] == "redis"  # 倒序
        assert [i["package"] for i in client.get("/api/versions?q=稳定").json()["items"]] == ["nginx"]
        assert client.put(f"/api/versions/{vid}", json={"package": "nginx", "version": "1.27.0",
                                                        "description": "主线", "release_date": ""}).json() == {"ok": True}
        assert client.get("/api/versions?q=nginx").json()["items"][0]["version"] == "1.27.0"
        assert client.put("/api/versions/999", json={"package": "x", "version": "1"}).status_code == 404
        assert client.delete(f"/api/versions/{vid}").json() == {"ok": True}
        assert client.delete(f"/api/versions/{vid}").status_code == 404
        assert len(client.get("/api/versions").json()["items"]) == 1

        # 便签：增/勾选/过滤排序/删
        nid = client.post("/api/notes", json={"content": "升级 nginx"}).json()["id"]
        nid2 = client.post("/api/notes", json={"content": "写周报"}).json()["id"]
        assert client.post("/api/notes", json={"content": "  "}).status_code == 422
        marked = client.put(f"/api/notes/{nid}/done", json={"done": True})
        assert marked.json() == {"ok": True, "done": 1}
        items = client.get("/api/notes").json()["items"]
        assert [i["content"] for i in items] == ["写周报", "升级 nginx"]  # 未完成在前
        assert items[1]["done"] == 1
        assert client.put("/api/notes/999/done", json={"done": True}).status_code == 404
        assert client.delete(f"/api/notes/{nid2}").json() == {"ok": True}
        assert len(client.get("/api/notes").json()["items"]) == 1
        assert client.delete(f"/api/notes/{nid2}").status_code == 404
    print("tools ok")


if __name__ == "__main__":
    main()

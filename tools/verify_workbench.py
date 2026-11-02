"""Phase 7 隔离验收：临时数据库验证知识库扩充与配置工坊，不触碰用户数据。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config
from app.agent.tools import TOOL_DESCRIPTIONS, execute_tool
from app.kb.service import get_kb
from app.server import create_app

KB_QUOTA = {"keepalived": (8, 30), "kafka": (10, 30), "redis": (10, 30), "docker": (15, 25),
            "mysql": (15, 20), "postgresql": (12, 18), "rabbitmq": (10, 10),
            "elasticsearch": (10, 12), "prometheus": (7, 10), "haproxy": (6, 10),
            "tomcat": (8, 10), "zookeeper": (7, 10), "firewalld": (10, 6)}
SOFTWARES = {"nginx", "zabbix", "keepalived", "kafka", "redis", "docker",
             "mysql", "postgresql", "rabbitmq", "elasticsearch", "prometheus",
             "haproxy", "tomcat", "zookeeper", "firewalld"}


def check_kb_contract() -> None:
    """/api/kb 十五软件达标 + 新 YAML 契约 + cli/conf 严格隔离。"""
    kb = get_kb()
    items = {row["software"]: row for row in kb.summary()}
    assert set(items) == SOFTWARES, items.keys()
    for software, (need_cli, need_conf) in KB_QUOTA.items():
        assert items[software]["cli_count"] >= need_cli, software
        assert items[software]["conf_count"] >= need_conf, software
    for software in KB_QUOTA:
        data = kb.get(software)
        assert data is not None
        names: set[str] = set()
        cli_names: set[str] = set()
        conf_names: set[str] = set()
        for category in data["categories"]:
            for entry in category["entries"]:
                assert entry["name"] not in names, f"{software} 重名 {entry['name']}"
                names.add(entry["name"])
                level = "false" if entry.get("danger") is False else str(entry.get("danger"))
                assert level in ("false", "low", "medium", "high"), entry
                if category["id"] == "cli":
                    assert entry.get("example"), entry["name"]
                    cli_names.add(entry["name"])
                else:
                    assert entry.get("section") and "default" in entry, entry["name"]
                    conf_names.add(entry["name"])
        assert not (cli_names & conf_names), f"{software} cli/conf 混排"
    print("kb contract ok")


def check_validation(client: TestClient) -> None:
    """/api/kb/workbench/validate 各格式的行号级错误与警告。"""
    def validate(fmt: str, content: str) -> dict:
        response = client.post("/api/kb/workbench/validate",
                               json={"format": fmt, "content": content})
        assert response.status_code == 200, response.text
        return response.json()

    bad_yaml = "a:\n  b: 1\n c: 2\n"
    result = validate("yaml", bad_yaml)
    assert not result["ok"] and result["errors"], result
    assert result["errors"][0]["line"] == 3, result
    # 同一份坏文件：缩进错误（行号级）+ 重复键警告（解析失败时的降级扫描）
    combined = "name: a\nlisten: 80\nname: b\na:\n  b: 1\n c: 2\n"
    result = validate("yaml", combined)
    assert not result["ok"] and result["errors"][0]["line"] == 6, result
    assert any("重复键" in w["message"] and w["line"] == 3 for w in result["warnings"]), result
    # 嵌套同名键不是重复键（启发式不应误报）
    nested = "a:\n  name: x\nb:\n  name: y\n"
    result = validate("yaml", nested)
    assert result["ok"] and not [w for w in result["warnings"] if "重复键" in w["message"]], result
    dup_yaml = "name: a\nlisten: 80\nname: b\n"
    result = validate("yaml", dup_yaml)
    assert result["ok"], result
    dup_warnings = [w for w in result["warnings"] if "重复键" in w["message"]]
    assert dup_warnings and dup_warnings[0]["line"] == 3, result
    assert validate("yaml", "a: 1\n")["ok"]

    keepalived = "vrrp_instance VI_1 {\n    state MASTER\n    interface eth0\n    priority 100\n"
    result = validate("keepalived", keepalived)
    assert not result["ok"] and len(result["errors"]) == 1, result
    assert result["errors"][0]["line"] == 1 and "未闭合" in result["errors"][0]["message"], result

    nginx = "server {\n    listen 80\n    location / {\n        root /var/www\n    }\n}\n"
    result = validate("nginx", nginx)
    assert not result["ok"], result
    assert {error["line"] for error in result["errors"] if "分号" in error["message"]} == {2, 4}, result
    nginx_ok = ("http {\n    log_format main '$remote_addr \"$request\" {ignored}';\n"
                "    # comment { }\n    server_tokens off;\n}\n")
    assert validate("nginx", nginx_ok)["ok"], validate("nginx", nginx_ok)

    properties = "# comment\nbroker.id=1\nlisteners PLAINTEXT://:9092\nbroker.id=2\n"
    result = validate("properties", properties)
    assert not result["ok"], result
    assert any(e["line"] == 3 and "非法行" in e["message"] for e in result["errors"]), result
    assert any("重复键" in w["message"] and w["line"] == 4 for w in result["warnings"]), result

    result = validate("json", '{\n  "a": 1,\n  "b": ?\n}')
    assert not result["ok"] and result["errors"][0]["line"] == 3, result
    assert validate("json", '{"a": 1}')["ok"]

    result = validate("yaml", "\ufeffa: 1 \nb: 2\n" + "c: " + "x" * 1001 + "\n")
    messages = [w["message"] for w in result["warnings"]]
    assert any("BOM" in m for m in messages), messages
    assert any("行尾存在多余空白字符" in m for m in messages), messages
    assert any("1000" in m for m in messages), messages
    mixed = validate("text", "a: 1\r\nb: 2\nc: 3\r\n")
    assert any("混合行尾" in w["message"] for w in mixed["warnings"]), mixed
    assert mixed["ok"] and mixed["stats"] == {"lines": 3, "bytes": 17}, mixed
    print("validation ok")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    check_kb_contract()
    assert "read_user_config" in TOOL_DESCRIPTIONS
    with tempfile.TemporaryDirectory() as folder, patch.object(config, "DB_PATH", Path(folder) / "test.db"):
        client = TestClient(create_app())
        check_validation(client)

        created = client.post("/api/kb/workbench/configs",
                              json={"name": "生产 nginx", "format": "nginx", "content": "server {\n}\n"})
        assert created.status_code == 200, created.text
        config_id = created.json()["id"]
        assert created.json() == {"id": config_id, "name": "生产 nginx", "format": "nginx"}

        assert client.post("/api/kb/workbench/configs",
                           json={"name": "x", "format": "ini", "content": "x"}).status_code == 422
        too_large = client.post("/api/kb/workbench/configs",
                                json={"name": "big", "format": "text", "content": "x" * (2 * 1024 * 1024 + 1)})
        assert too_large.status_code == 413, too_large.status_code

        listing = client.get("/api/kb/workbench/configs").json()["items"]
        assert len(listing) == 1 and "content" not in listing[0] and listing[0]["shared"] == 0, listing
        detail = client.get(f"/api/kb/workbench/configs/{config_id}").json()
        assert detail["content"] == "server {\n}\n" and detail["name"] == "生产 nginx", detail

        updated = client.put(f"/api/kb/workbench/configs/{config_id}",
                             json={"name": "生产 nginx v2", "format": "nginx", "content": "events {\n}\n"})
        assert updated.status_code == 200 and updated.json() == {"ok": True}
        assert client.get("/api/kb/workbench/configs/999").status_code == 404
        assert client.put("/api/kb/workbench/configs/999",
                          json={"name": "x", "format": "yaml", "content": "a: 1"}).status_code == 404

        # 默认不共享：智能体读不到；显式共享后可读、截断正确；关闭立即失效。
        assert execute_tool("read_user_config", {"name": "生产 nginx v2"}) == {
            "ok": False, "error": "配置不存在或未共享"}
        shared = client.put(f"/api/kb/workbench/configs/{config_id}/share", json={"shared": True})
        assert shared.json() == {"ok": True, "shared": 1}
        assert execute_tool("read_user_config", {"name": "生产 nginx v2"})["result"]["content"] == "events {\n}\n"
        assert not execute_tool("read_user_config", {"name": "不存在的配置"})["ok"]
        long_config = client.post("/api/kb/workbench/configs",
                                  json={"name": "long", "format": "text", "content": "y" * 5000})
        long_id = long_config.json()["id"]
        client.put(f"/api/kb/workbench/configs/{long_id}/share", json={"shared": True})
        result = execute_tool("read_user_config", {"name": "long"})["result"]
        assert len(result["content"]) == 4000 and result["truncated"] is True, result
        assert client.put(f"/api/kb/workbench/configs/{config_id}/share", json={"shared": False}).json()["shared"] == 0
        assert execute_tool("read_user_config", {"name": "生产 nginx v2"})["ok"] is False

        assert client.delete(f"/api/kb/workbench/configs/{config_id}").json() == {"ok": True}
        assert client.get(f"/api/kb/workbench/configs/{config_id}").status_code == 404
        remaining = client.get("/api/kb/workbench/configs").json()["items"]
        assert [item["name"] for item in remaining] == ["long"], remaining
        assert json.dumps(listing, ensure_ascii=False)  # 列表可序列化
    print("workbench ok")


if __name__ == "__main__":
    main()

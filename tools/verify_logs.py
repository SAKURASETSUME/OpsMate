"""Phase 5 临时数据库验收，不修改用户日志或密钥。"""
from __future__ import annotations
import tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import config
from app.server import create_app
from app.logs import store
from app.logs.rules import classify_level


def sample_lines() -> list[str]:
    """200 行，含 ERROR/WARN/INFO/DEBUG 与 Java 延续堆栈。"""
    return [
        f"2026-10-30 10:00:{i % 60:02d} ERROR Network Exception id={i}" if i % 10 == 0 else
        f"2026-10-30 WARN Network retry id={i}" if i % 10 == 1 else
        f"2026-10-30 DEBUG detail id={i}" if i % 10 == 3 else
        "    at java.example.Main.run(Main.java:42)" if i % 10 == 4 else
        f"2026-10-30 INFO healthy id={i}" for i in range(200)]


def main() -> None:
    """运行 API/数据库/文件副本/50MB 真实边界验证。"""
    with tempfile.TemporaryDirectory() as folder, patch.object(config, "DB_PATH", Path(folder)/"logs.db"), patch.object(config, "LOGS_DIR", Path(folder)/"raw"):
        client = TestClient(create_app())
        raw = ("\n".join(sample_lines()) + "\n").encode("utf-8")
        response = client.post("/api/logs", files={"file": ("sample.log", raw, "text/plain")})
        assert response.status_code == 200, response.text
        log = response.json(); log_id = log["id"]
        assert log["line_count"] == 200 and log["size_bytes"] == len(raw)
        assert log["format_guess"] == "java_app"
        assert log["level_stats"] == {"ERROR":20,"WARN":20,"INFO":120,"DEBUG":20,"":20}
        assert (config.LOGS_DIR/f"{log_id}.txt").read_bytes() == raw
        url = f"/api/logs/{log_id}"
        assert client.get(url+"/lines",params={"level":"ERROR"}).json()["total"] == 20
        assert client.get(url+"/lines",params={"regex":"Exception"}).json()["total"] == 20
        assert client.get(url+"/lines",params={"q":"NETWORK","level":"ERROR"}).json()["total"] == 20
        assert client.get(url+"/lines",params={"q":"healthy","level":"ERROR"}).json()["total"] == 0
        assert client.get(url+"/lines",params={"q":"Network","level":"ERROR,WARN","regex":"Exception"}).json()["total"] == 20
        assert client.get(url+"/lines",params={"level":"UNKNOWN"}).json()["total"] == 20
        page = client.get(url+"/lines",params={"offset":10,"limit":7,"order":"desc"}).json()
        assert len(page["lines"]) == 7 and page["lines"][0]["line_no"] == 190
        assert client.get(url+"/lines",params={"regex":"["}).status_code == 400
        assert client.get(url+"/export",params={"regex":"["}).status_code == 400
        exported = client.get(url+"/export",params={"level":"ERROR"}).text.splitlines()
        assert len(exported) == 20 and exported[0].startswith("1\t") and exported[-1].startswith("191\t")
        assert client.get(url+"/stats").json()["level_counts"]["ERROR"] == 20
        assert client.post("/api/logs",json={"title":"", "content":"INFO test"}).status_code == 400
        assert client.post("/api/logs",files={"file":("bad.log",b'\xff')}).status_code == 400
        with store.connection() as conn:
            conn.execute("INSERT INTO reports(log_id,content) VALUES (?,?)",(log_id,"test report")); conn.commit()
        assert client.delete(url).json()["ok"]
        assert not (config.LOGS_DIR/f"{log_id}.txt").exists()
        assert client.get(url).status_code == 404
        with store.connection() as conn:
            assert conn.execute("SELECT count(*) FROM log_lines").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM reports").fetchone()[0] == 0
        assert not client.get('/api/logs').json()['items']
        response = client.post('/api/logs', files={"file":("oversize.log",b'x'*(store.MAX_BYTES+1))})
        assert response.status_code == 413 and 'split/grep' in response.text
        pasted = client.post('/api/logs',json={"title":"paste","content":"INFO one\nERROR two"})
        assert pasted.status_code == 200 and pasted.json()['line_count']==2
        assert classify_level('critical failure')=='ERROR' and classify_level('[warning] retry')=='WARN'
    print('PASS: 200 lines, format/count/size, intersections, pagination, regex 400, numbered export, cascading delete, UTF-8, real 50MB+1 limit')


if __name__ == '__main__':
    main()

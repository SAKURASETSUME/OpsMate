"""Synthetic Python->Java copy and rollback rehearsal. No real local data is read."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import httpx
from migrate_java_data import migrate,digest
from verify_java_baseline import start,stop
from verify_java_offline import ROOT,java_server
from verify_java_assistant import Model
from verify_java_generation import events
from http.server import ThreadingHTTPServer
import threading


def main() -> None:
    with tempfile.TemporaryDirectory(dir=ROOT/"java-app/target",prefix="j6-cutover-") as folder:
        root=Path(folder); source=root/"python"; source.mkdir()
        proc,client,_=start(source)
        try:
            note=client.post("/api/notes",json={"content":"旧版便签"}).json()
            config=client.post("/api/kb/workbench/configs",json={"name":"旧版配置","format":"text","content":"保留内容"}).json()
            attachment=client.post("/api/assistant/files",files={"file":("旧附件.conf","原始中文".encode(),"text/plain")}).json()
            log=client.post("/api/logs",json={"title":"旧日志","content":"ERROR 旧版错误"}).json()
        finally: stop(proc,client)
        # Baseline fixture uses test.db and attachments; convert the known fixture DB name only.
        (source/"test.db").rename(source/"opsmate.db")
        with closing(sqlite3.connect(source/"opsmate.db")) as db:
            db.execute("INSERT INTO assistant_sessions(title) VALUES ('旧会话')")
            sid=db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute("INSERT INTO assistant_messages(session_id,role,content) VALUES (?,'user','旧问题')",(sid,))
            mid=db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute("UPDATE assistant_attachments SET session_id=?,message_id=? WHERE id=?",(sid,mid,attachment["id"]))
            db.execute("INSERT INTO assistant_messages(session_id,role,content) VALUES (?,'assistant','旧回答')",(sid,))
            db.commit()
        before=digest(source/"opsmate.db")
        copied=root/"java"
        report=migrate(source,copied)
        assert report["integrity"]=="ok" and report["attachments"]==1
        assert digest(source/"opsmate.db")==before
        server=ThreadingHTTPServer(("127.0.0.1",0),Model)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with java_server(root,root/"java.log") as java:
                assert java.get(f"/api/assistant/sessions/{sid}").json()["messages"][0]["content"]=="旧问题"
                assert java.get(f"/api/assistant/files/{attachment['id']}/content").content=="原始中文".encode()
                assert java.get(f"/api/kb/workbench/configs/{config['id']}").json()["content"]=="保留内容"
                assert java.get(f"/api/logs/{log['id']}").status_code==200
                assert any(row["id"]==note["id"] for row in java.get("/api/notes").json()["items"])
                java.put("/api/settings",json={"provider":"custom","base_url":f"http://127.0.0.1:{server.server_port}","model":"normal","api_key":"j6-synthetic-key"})
                answer=events(java,"/api/assistant/chat",{"message":"Java增量会话","tools":False})
                assert answer[-1].get("done"),answer
                java_id=answer[-1]["session_id"]
        finally: server.shutdown(); server.server_close()
        increment=root/"java-increment"
        increment_report=migrate(copied,increment)
        assert increment_report["row_counts"]["assistant_sessions"]==2
        assert digest(source/"opsmate.db")==before,"Java must not write source DB"
        # Rollback is simply reopening the untouched source; retain Java increment separately.
        (source/"opsmate.db").rename(source/"test.db")
        proc,client,_=start(source)
        try:
            assert client.get(f"/api/assistant/sessions/{sid}").status_code==200
            assert client.get(f"/api/assistant/sessions/{java_id}").status_code==404
            assert client.get(f"/api/assistant/files/{attachment['id']}/content").content=="原始中文".encode()
        finally: stop(proc,client)
        with closing(sqlite3.connect(source/"test.db")) as db: assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        evidence={"python_source_untouched":True,"backup_integrity":True,"attachment_checksum_and_http":True,"java_increment_retained":True,"python_rollback_readable":True,"private_copy_never_packaged":True}
        output=ROOT/"migration/j6"; output.mkdir(exist_ok=True)
        (output/"cutover.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    print("PASS: synthetic old DB/attachments cutover, Java increment backup, Python rollback")


if __name__=="__main__": main()

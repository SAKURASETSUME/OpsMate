"""J3 日志真 HTTP 差分、50MiB 边界与 Python 旧库读取验收。"""
from __future__ import annotations
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from contextlib import closing
from verify_java_baseline import start, stop
from verify_java_offline import ROOT, java_server, normalize


def replay(client):
    captures = []
    def request(name,method,path,**kwargs):
        response = client.request(method,path,**kwargs)
        body = response.json() if "application/json" in response.headers.get("content-type","") else response.text
        captures.append({"name":name,"status":response.status_code,"body":normalize(body)})
        return body
    lines = [f"2026-11-05 10:00:{i%60:02d} ERROR Network Exception id={i}" if i%10==0 else
             f"2026-11-05 WARN Network retry id={i}" if i%10==1 else
             "    at java.example.Main.run(Main.java:42)" if i%10==4 else
             f"2026-11-05 INFO healthy id={i}" for i in range(200)]
    log = request("import","POST","/api/logs",files={"file":("sample.log",("\n".join(lines)+"\n").encode("utf-8"))})
    url = f'/api/logs/{log["id"]}'
    request("metadata","GET",url)
    request("list","GET","/api/logs")
    request("clusters","GET",url+"/stats")
    for params in ({"level":"ERROR"},{"q":"NETWORK","level":"ERROR,WARN","regex":"Exception"},
                   {"level":"UNKNOWN"},{"order":"desc","offset":10,"limit":7},{"regex":"["},
                   {"level":"INVALID"}):
        request("filter "+str(params),"GET",url+"/lines",params=params)
    request("export","GET",url+"/export",params={"level":"ERROR"})
    request("invalid export","GET",url+"/export",params={"regex":"["})
    request("delete","DELETE",url)
    request("deleted","GET",url)
    request("bad encoding","POST","/api/logs",files={"file":("invalid.log",b"\xff")})
    request("empty title","POST","/api/logs",json={"title":"","content":"INFO x"})
    legacy = request("paste","POST","/api/logs",json={"title":"legacy synthetic","content":"INFO 一\r\nERROR 二\r\n"})
    request("paste stats","GET",f'/api/logs/{legacy["id"]}/stats')
    line = b"INFO synthetic " + b"x"*110+b"\n"
    raw = (line*(50*1024*1024//len(line)+1))[:50*1024*1024]
    before = time.perf_counter()
    big = request("50MiB","POST","/api/logs",files={"file":("large.log",raw)})
    duration = time.perf_counter()-before
    request("50MiB+1","POST","/api/logs",files={"file":("large.log",raw+b"x")})
    request("big first page","GET",f'/api/logs/{big["id"]}/lines',params={"limit":1})
    return captures,legacy["id"],duration


def main() -> None:
    with tempfile.TemporaryDirectory(dir=ROOT/"java-app"/"target",prefix="j3-diff-") as folder:
        root = Path(folder)
        pyroot = root/"python"
        pyroot.mkdir()
        proc,client,_ = start(pyroot)
        try:
            expected,old_id,pytime = replay(client)
            with java_server(root,root/"java.log") as java:
                actual,_,jtime = replay(java)
            for python,java in zip(expected,actual,strict=True):
                assert python == java,(python["name"],str(python)[:900],str(java)[:900])
            legacy_root = root/"legacy"
            (legacy_root/"java").mkdir(parents=True)
            with closing(sqlite3.connect(pyroot/"test.db")) as source, closing(sqlite3.connect(legacy_root/"java"/"opsmate.db")) as target:
                source.backup(target)
            with java_server(legacy_root,legacy_root/"java.log") as java:
                assert java.get(f"/api/logs/{old_id}").json()["line_count"] == 2
                assert java.get(f"/api/logs/{old_id}/lines").json()["lines"][1]["text"] == "ERROR 二"
            output = ROOT/"migration"/"j3"
            output.mkdir(parents=True,exist_ok=True)
            (output/"http-differential.json").write_text(json.dumps({"cases":[{"name":case["name"],"status":case["status"]} for case in actual],
                "legacy_sqlite_read":True,"import_seconds":{"python":pytime,"java":jtime}},ensure_ascii=False,indent=2),encoding="utf-8")
            print(f"PASS: {len(actual)} log differential cases; 50MiB; old Python SQLite; Java import {jtime:.2f}s")
        finally:
            stop(proc,client)


if __name__ == "__main__":
    main()

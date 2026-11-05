"""J2 同一 HTTP 操作序列对比 Python 与 Java，数据各自隔离。"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
import httpx
from verify_java_baseline import start, stop

ROOT = Path(__file__).resolve().parents[1]


def normalize(value):
    if isinstance(value,dict):
        return {key:normalize(item) for key,item in value.items()
                if key not in {"created_at","updated_at","message"}}
    if isinstance(value,list):
        return [normalize(item) for item in value]
    return value


def replay(client: httpx.Client) -> list[dict]:
    captures = []
    def request(name: str,method: str,path: str,**kwargs):
        response = client.request(method,path,**kwargs)
        body = response.json()
        captures.append({"name":name,"status":response.status_code,"body":normalize(body)})
        return body
    for query in ("","磁盘","disk","df","nginx"):
        request("commands "+query,"GET","/api/commands",params={"q":query,"limit":20})
    request("command detail","GET","/api/commands/df")
    request("missing command","GET","/api/commands/does-not-exist")
    request("knowledge list","GET","/api/kb")
    for software in ("nginx","keepalived","kafka","mysql","redis","docker"):
        request("knowledge "+software,"GET","/api/kb/"+software)
    request("knowledge search","GET","/api/kb/search",params={"q":"worker"})
    for fmt,content in (("yaml","a: 1\na: 2\n  broken: ["),("yaml","x:\n  a: 1\n  a: 2"),
                        ("keepalived","vrrp_instance VI_1 {\n priority 100\n"),
                        ("nginx","server {\n listen 80\n}\n"),("json",'{"a":'),
                        ("properties","a=1\na=2\nbroken"),("text","a  \r\nb\n")):
        request("validate "+fmt+str(len(content)),"POST","/api/kb/workbench/validate",json={"format":fmt,"content":content})
    config = request("config create","POST","/api/kb/workbench/configs",json={"name":"synthetic","format":"yaml","content":"a: 1"})
    cid = config["id"]
    request("config list","GET","/api/kb/workbench/configs")
    request("config detail","GET",f"/api/kb/workbench/configs/{cid}")
    request("config share on","PUT",f"/api/kb/workbench/configs/{cid}/share",json={"shared":True})
    request("config share off","PUT",f"/api/kb/workbench/configs/{cid}/share",json={"shared":False})
    request("config update","PUT",f"/api/kb/workbench/configs/{cid}",json={"name":"updated","format":"text","content":"中文"})
    request("config utf8 exact","POST","/api/kb/workbench/configs",json={"name":"limit","format":"text","content":"x"*(2*1024*1024)})
    request("config too large","POST","/api/kb/workbench/configs",json={"name":"limit","format":"text","content":"x"*(2*1024*1024+1)})
    request("config delete","DELETE",f"/api/kb/workbench/configs/{cid}")
    request("config missing","GET",f"/api/kb/workbench/configs/{cid}")
    note = request("note create","POST","/api/notes",json={"content":"J2 synthetic"})
    request("note done","PUT",f'/api/notes/{note["id"]}/done',json={"done":True})
    request("notes","GET","/api/notes")
    request("note delete","DELETE",f'/api/notes/{note["id"]}')
    request("persistent note","POST","/api/notes",json={"content":"persist after restart"})
    for version in ("1.2.3","1.10.0"):
        request("version create "+version,"POST","/api/versions",json={"package":"synthetic","version":version})
    request("versions list","GET","/api/versions")
    request("versions filter","GET","/api/versions",params={"package":"SYNTHETIC","version":"1.10"})
    return captures


@contextmanager
def java_server(root: Path,logfile: Path):
    """启动可重复重启的 Java 服务，日志和数据均在本次夹具目录。"""
    target = ROOT/"java-app"/"target"
    with logfile.open("w",encoding="utf-8") as log:
        proc = subprocess.Popen(["java","-Djava.io.tmpdir="+str(root),"-jar",str(target/"opsmate-1.0.0-migration.jar"),
                                 "--headless","--opsmate.data="+str(root/"java"),
                                 "--opsmate.knowledge="+str(ROOT/"data")],stdout=log,stderr=subprocess.STDOUT,
                                cwd=ROOT/"java-app")
        try:
            deadline = time.monotonic()+25
            port = None
            while time.monotonic()<deadline:
                match = re.search(r"Tomcat started on port (\d+)",logfile.read_text(encoding="utf-8"))
                if match:
                    port = int(match[1])
                    break
                if proc.poll() is not None:
                    raise AssertionError(logfile.read_text(encoding="utf-8"))
                time.sleep(0.05)
            assert port is not None, "Java startup timeout"
            with httpx.Client(base_url=f"http://127.0.0.1:{port}",trust_env=False,timeout=30) as client:
                yield client
        finally:
            proc.terminate()
            proc.wait(timeout=15)


def main() -> None:
    target = ROOT/"java-app"/"target"
    with tempfile.TemporaryDirectory(dir=target,prefix="j2-diff-") as folder:
        root = Path(folder)
        pyroot = root/"python"
        pyroot.mkdir()
        pyproc,pyclient,_ = start(pyroot)
        try:
            python = replay(pyclient)
            with java_server(root,root/"java.log") as client:
                actual = replay(client)
            for expected,observed in zip(python,actual,strict=True):
                assert expected == observed, (expected["name"],str(expected)[:1200],str(observed)[:1200])
            with java_server(root,root/"java-restart.log") as client:
                assert client.get("/api/notes").json()["items"][0]["content"] == "persist after restart"
                assert len(client.get("/api/versions").json()["items"]) == 2
                configs = client.get("/api/kb/workbench/configs").json()["items"]
                assert len(configs) == 1 and configs[0]["size_bytes"] == 2097152
            report = [{"name":case["name"],"status":case["status"],
                       "body_sha256":hashlib.sha256(json.dumps(case["body"],ensure_ascii=False,sort_keys=True).encode("utf-8")).hexdigest()} for case in actual]
            output = ROOT/"migration"/"j2"
            output.mkdir(parents=True,exist_ok=True)
            (output/"http-differential.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            print(f"PASS: {len(report)} Python/Java HTTP differential cases; restart persistence passed")
        finally:
            stop(pyproc,pyclient)


if __name__ == "__main__":
    main()

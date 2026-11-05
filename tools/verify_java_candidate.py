"""Run only extracted candidate copies, headless and without system Java."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import zipfile
import httpx
from http.server import ThreadingHTTPServer
from verify_java_assistant import Model
from verify_java_baseline import working_set
from package_java import ROOT,sha256


@contextmanager
def running(image: Path,folder: Path) -> Iterator[tuple[httpx.Client,int,float]]:
    folder.mkdir(parents=True,exist_ok=True)
    logfile=folder/"startup.log"
    env=dict(os.environ)
    env["JAVA_HOME"]=str(folder/"no-system-java")
    env["PATH"]=str(Path(env.get("SystemRoot","C:/Windows"))/"System32")
    env["JAVA_TOOL_OPTIONS"]='-XX:-UsePerfData -Djava.io.tmpdir="'+str(folder)+'"'
    env["TEMP"]=str(folder); env["TMP"]=str(folder)
    started=time.perf_counter()
    launcher_log=folder/"launcher.log"
    output=launcher_log.open("wb")
    process=subprocess.Popen([str(image/"OpsMate.exe"),"--headless","--logging.file.name="+str(logfile)],cwd=folder,env=env,stdout=output,stderr=subprocess.STDOUT)
    try:
        port=None
        while time.perf_counter()-started<25:
            if process.poll() is not None:
                detail=launcher_log.read_text(encoding="utf-8",errors="replace")
                if logfile.exists(): detail+="\n"+logfile.read_text(encoding="utf-8",errors="replace")
                raise AssertionError("candidate exited before startup; exit="+str(process.returncode)+" "+detail[-3000:])
            if logfile.exists():
                match=re.search(r"Tomcat started on port (\d+)",logfile.read_text(encoding="utf-8"))
                if match: port=int(match[1]); break
            time.sleep(0.03)
        assert port,"candidate startup timeout"
        with httpx.Client(base_url=f"http://127.0.0.1:{port}",trust_env=False,timeout=40) as client:
            assert client.get("/api/health").json()=={"ok":True,"version":"1.0.0"}
            actual=re.search(r"Starting OpsMateApplication[^\r\n]* with PID (\d+)",logfile.read_text(encoding="utf-8"))
            assert actual,"JVM PID not present in startup evidence"
            jvm_pid=int(actual[1])
            yield client,jvm_pid,time.perf_counter()-started
    finally:
        process.terminate(); process.wait(timeout=15); output.close()
    if port:
        try:
            httpx.get(f"http://127.0.0.1:{port}/api/health",timeout=1,trust_env=False)
        except httpx.HTTPError: pass
        else: raise AssertionError("candidate port still alive after process exit")


def main() -> None:
    candidate=json.loads((ROOT/"migration/j6/candidate.json").read_text(encoding="utf-8"))
    archive=Path(candidate["archive"])
    assert sha256(archive)==candidate["sha256"]
    model=ThreadingHTTPServer(("127.0.0.1",0),Model)
    threading.Thread(target=model.serve_forever,daemon=True).start()
    samples=[]
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/"java-app/target",prefix="candidate-test-") as folder:
            root=Path(folder)
            for attempt in range(1,4):
                trial=root/f"中文 空格 {attempt}"
                with zipfile.ZipFile(archive) as bundle: bundle.extractall(trial)
                image=trial/"OpsMate"
                # Reproduce pre-created empty knowledge directories before first launch.
                for category in ("commands","kb","skills"): (image/"data"/category).mkdir(parents=True)
                with running(image,trial/"tmp") as (client,pid,elapsed):
                    time.sleep(1)
                    memory=working_set(pid)
                    assert client.get("/api/commands",params={"limit":2000}).json()["total"]==621
                    assert len(client.get("/api/kb").json()["items"])==15
                    assert len(client.get("/api/assistant/skills").json()["items"])==6
                    for route in ("/index.html","/app.js","/style.css","/vendor/vue.global.prod.js","/vendor/marked.min.js"):
                        assert client.get(route).status_code==200,route
                    assert client.get("/__verify").status_code==404
                    assert (image/"data/opsmate.db").is_file(),"default data must be beside exe"
                    assert not client.get("/api/settings").json()["api_key_set"]
                    note=client.post("/api/notes",json={"content":"候选重启保留"}).json()
                    content=b"x"*(50*1024*1024)
                    start=time.perf_counter()
                    imported=client.post("/api/logs",files={"file":("50MiB.log",content,"text/plain")})
                    import_seconds=time.perf_counter()-start
                    assert imported.status_code==200,imported.text[:200]
                    client.put("/api/settings",json={"provider":"custom","base_url":f"http://127.0.0.1:{model.server_port}","model":"normal","api_key":"candidate-test-key"})
                    start=time.perf_counter(); first_delta=None; done=False
                    with client.stream("POST","/api/assistant/chat",json={"message":"候选模拟流","tools":False}) as response:
                        for line in response.iter_lines():
                            if not line.startswith("data:"): continue
                            event=json.loads(line[5:])
                            assert "error" not in event,event
                            if "delta" in event and first_delta is None: first_delta=time.perf_counter()-start
                            if event.get("done"): done=True
                    assert done and first_delta is not None
                    samples.append({"attempt":attempt,"cold_to_health_seconds":elapsed,"idle_working_set_bytes":memory,"import_50mib_seconds":import_seconds,"synthetic_first_delta_seconds":first_delta})
                    assert elapsed<=20,samples[-1]
                    assert memory<=512*1024*1024,samples[-1]
                    assert import_seconds<=12,samples[-1]
                    assert first_delta<=2,samples[-1]
                    client.delete(f"/api/logs/{imported.json()['id']}")
                if attempt==1:
                    # User KB additions and edits must survive a second startup.
                    custom=image/"data/kb/j6-added.yaml"
                    custom.write_text("software: candidate-added\nlabel: 用户新增\ncategories: []\n",encoding="utf-8")
                    with running(image,trial/"restart-tmp") as (client,_,_):
                        assert any(item["id"]==note["id"] for item in client.get("/api/notes").json()["items"])
                        assert client.get("/api/settings").json()["api_key_set"]
                        assert client.get("/api/kb/candidate-added").status_code==200
            evidence={"archive_sha256":candidate["sha256"],"jar_sha256":candidate["jar_sha256"],"samples":samples,"memory_scope":"actual JVM PID parsed from Boot startup log, excludes native parent launcher","no_system_java":True,"chinese_space_paths":True,"first_launch_assets":True,"restart_preserves_user_data":True,"port_released":True,"private_pristine_archive_unchanged":sha256(archive)==candidate["sha256"],"desktop_not_tested":True,"real_model_tested_in_this_run":False,"separate_real_model_evidence_bound":candidate.get("real_model_verified",False)}
            (ROOT/"migration/j6/candidate-headless.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    finally: model.shutdown(); model.server_close()
    print("PASS: candidate exe headless, bundled Java, assets, persistence, 3 performance samples")


if __name__=="__main__": main()

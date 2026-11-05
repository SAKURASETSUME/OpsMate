"""无界面验收 jpackage 启动器，自带运行时，禁止依赖系统 Java。"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import zipfile
import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package",type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    assert (package/"runtime"/"bin"/"server"/"jvm.dll").is_file()
    payload = package/"app"/"opsmate.jar"
    with zipfile.ZipFile(payload) as jar:
        names = jar.namelist()
        assert "BOOT-INF/classes/static/index.html" in names
        assert not any(name.endswith(("config.json","model_profiles.json","opsmate.db")) for name in names)
    workspace_target = Path(__file__).resolve().parents[1]/"java-app"/"target"
    with tempfile.TemporaryDirectory(prefix="package-check-",dir=workspace_target,ignore_cleanup_errors=True) as folder:
        logfile = Path(folder)/"startup.log"
        env = dict(os.environ)
        env["JAVA_HOME"] = str(Path(folder)/"no-java")
        env["JAVA_TOOL_OPTIONS"] = '-XX:-UsePerfData -Djava.io.tmpdir="'+folder+'"'
        env["TEMP"] = folder
        env["TMP"] = folder
        env["PATH"] = str(Path(env.get("SystemRoot","C:/Windows"))/"System32")
        started = time.perf_counter()
        proc = subprocess.Popen([str(package/"OpsMate-J1.exe"),"--headless",
                                 "--logging.file.name="+str(logfile)],cwd=package,env=env)
        try:
            deadline = time.monotonic()+25
            port = None
            while time.monotonic()<deadline:
                if proc.poll() is not None:
                    raise AssertionError("packaged JVM exited before health")
                if logfile.exists():
                    match = re.search(r"Tomcat started on port (\d+)",logfile.read_text(encoding="utf-8"))
                    if match:
                        port = int(match[1])
                        break
                time.sleep(0.05)
            assert port is not None, "packaged JVM did not start"
            with httpx.Client(base_url=f"http://127.0.0.1:{port}",trust_env=False,timeout=5) as client:
                assert client.get("/api/health").json() == {"ok":True,"version":"1.0.0"}
                assert client.get("/index.html").status_code == 200
                assert client.get("/__verify").status_code == 404
            evidence = {"bundled_runtime":True,"system_java_removed":True,
                        "health":True,"static":True,"verification_profile_disabled":True,
                        "start_to_health_seconds":time.perf_counter()-started}
        finally:
            proc.terminate()
            proc.wait(timeout=15)
        target = Path(__file__).resolve().parents[1]/"migration"/"j1"
        target.mkdir(parents=True,exist_ok=True)
        (target/"package-smoke.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    print("PASS: packaged exe HTTP health, static assets, private files excluded, no system Java")


if __name__ == "__main__":
    main()

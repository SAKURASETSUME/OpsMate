"""J0 跨进程 HTTP 验收和 Python 后端性能记录，仅合成数据。"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx
from fastapi import Request


def serve(root: Path) -> None:
    """应用导入前隔离所有运行目录，知识资产仅只读复用。"""
    from app import config
    config.DATA_DIR = root
    config.DB_PATH = root/"test.db"
    config.CONFIG_JSON = root/"config.json"
    config.PROFILES_JSON = root/"model_profiles.json"
    config.LOGS_DIR = root/"logs"
    config.ASSISTANT_FILES_DIR = root/"attachments"
    config.AGENT_FILES_DIR = root/"files"
    from app.server import create_app
    import socket
    import uvicorn
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        app = create_app()
        from fastapi.responses import StreamingResponse
        @app.post("/__baseline/chat/completions")
        async def mock_model(request: Request):
            body = await request.json()
            if not body.get("stream"):
                return {"choices":[{"message":{"content":"J0 synthetic response"}}]}
            async def chunks():
                import asyncio
                for delta in ("J0 ","synthetic ","response"):
                    yield "data: " + json.dumps({"choices":[{"delta":{"content":delta}}]}) + "\n\n"
                    await asyncio.sleep(0.03)
                yield "data: [DONE]\n\n"
            return StreamingResponse(chunks(),media_type="text/event-stream")
        app.router.routes.insert(0,app.router.routes.pop())
        server = uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",log_level="error",access_log=False))
        @app.post("/__baseline/stop")
        def shutdown() -> dict[str, bool]:
            server.should_exit = True
            return {"ok":True}
        app.router.routes.insert(0,app.router.routes.pop())
        (root/"ready.json").write_text(json.dumps({"port":sock.getsockname()[1],"pid":os.getpid()}),encoding="utf-8")
        server.run(sockets=[sock])


def start(root: Path) -> tuple[subprocess.Popen, httpx.Client, float]:
    """以健康响应作为冷进程启动计时终点。"""
    ready = root/"ready.json"
    ready.unlink(missing_ok=True)
    started = time.perf_counter()
    proc = subprocess.Popen([sys.executable,__file__,"--serve",str(root)],
                            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                            text=True,encoding="utf-8",errors="replace")
    try:
        deadline = time.monotonic()+20
        while time.monotonic()<deadline:
            if proc.poll() is not None:
                raise RuntimeError(proc.stderr.read())
            if ready.exists():
                port = json.loads(ready.read_text(encoding="utf-8"))["port"]
                client = httpx.Client(base_url=f"http://127.0.0.1:{port}",trust_env=False,timeout=120)
                try:
                    if client.get("/api/health").status_code == 200:
                        return proc,client,time.perf_counter()-started
                except httpx.HTTPError:
                    pass
                client.close()
            time.sleep(0.02)
        raise RuntimeError("isolated server startup timed out")
    except BaseException:
        proc.kill()
        proc.wait()
        raise


def stop(proc: subprocess.Popen, client: httpx.Client) -> None:
    try:
        client.post("/__baseline/stop").raise_for_status()
    finally:
        client.close()
    proc.wait(timeout=15)
    if proc.stderr:
        proc.stderr.close()


def working_set(pid: int) -> int:
    """Windows PSAPI读取本次测试子进程工作集。"""
    class Counters(ctypes.Structure):
        _fields_ = [("cb",wintypes.DWORD),("faults",wintypes.DWORD)] + [
            (name,ctypes.c_size_t) for name in ("peak","working","peak_paged","paged","peak_nonpaged","nonpaged","pagefile","peak_pagefile")]
    value = Counters()
    value.cb = ctypes.sizeof(value)
    call = ctypes.WinDLL("psapi",use_last_error=True).GetProcessMemoryInfo
    call.argtypes = [wintypes.HANDLE,ctypes.c_void_p, wintypes.DWORD]
    call.restype = wintypes.BOOL
    kernel = ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x410,False,pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not call(handle,ctypes.byref(value),value.cb):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)
    return value.working


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve",type=Path)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve)
        return
    samples = []
    for attempt in range(3):
        with tempfile.TemporaryDirectory(prefix="opsmate-j0-") as folder:
            root = Path(folder)
            proc,client,startup = start(root)
            try:
                time.sleep(1)
                server_pid = json.loads((root/"ready.json").read_text(encoding="utf-8"))["pid"]
                idle_memory = working_set(server_pid)
                assert len(client.get("/api/kb").json()["items"]) == 15
                note = client.post("/api/notes",json={"content":"J0 synthetic"}).json()
                assert "id" in note
                version = client.post("/api/versions",json={"package":"j0","version":"1.2.3"})
                assert version.status_code == 200
                cfg = client.post("/api/kb/workbench/configs",json={"name":"j0","format":"yaml","content":"a: 1"}).json()
                assert "id" in cfg
                assert client.post("/api/kb/workbench/validate",json={"format":"yaml","content":"a: ["}).json()["ok"] is False
                assert client.post("/api/kb/workbench/configs",json={"name":"big","format":"text","content":"x"*(2*1024*1024+1)}).status_code == 413
                row = b"2026-11-05 INFO synthetic baseline " + b"x"*90 + b"\n"
                raw = (row*(50*1024*1024//len(row)+1))[:50*1024*1024]
                before = time.perf_counter()
                response = client.post("/api/logs",files={"file":("synthetic.log",raw)})
                duration = time.perf_counter()-before
                assert response.status_code == 200, response.status_code
                log_id = response.json()["id"]
                assert response.json()["size_bytes"] == len(raw)
                assert client.get(f"/api/logs/{log_id}/lines",params={"level":"ERROR"}).json()["total"] == 0
                before = time.perf_counter()
                with client.stream("POST",f"/api/logs/{log_id}/llm-analyze",json={}) as stream:
                    first = next(line for line in stream.iter_lines() if line.startswith("data:"))
                    first_event = time.perf_counter()-before
                    assert "error" in json.loads(first[5:])
                settings = {"provider":"custom","base_url":str(client.base_url).rstrip("/")+"/__baseline",
                            "model":"synthetic","api_key":"j0-fake-local-only"}
                # Fixture model and application share a loopback server; production settings never read.
                assert client.put("/api/settings",json=settings).status_code == 200
                started_stream = time.perf_counter()
                events = []
                first_delta = None
                with client.stream("POST","/api/assistant/chat",json={"message":"J0 synthetic", "tools":False}) as stream:
                    for line in stream.iter_lines():
                        if line.startswith("data:"):
                            event = json.loads(line[5:])
                            assert "error" not in event, event
                            events.append(event)
                            if event.get("delta") and first_delta is None:
                                first_delta = time.perf_counter()-started_stream
                assert first_delta is not None and "J0 synthetic response" in "".join(e.get("delta","") for e in events)
                assert client.post("/api/logs",files={"file":("too-large.log",raw+b"x")}).status_code == 413
                del raw
                # Working set measured by the OS, after import. This is not idle memory.
                samples.append({"attempt":attempt+1,"process_start_to_health_seconds":startup,
                                "import_50_mib_seconds":duration,"missing_key_first_error_seconds":first_event,
                                "successful_first_delta_seconds":first_delta,
                                "idle_working_set_bytes":idle_memory,
                                "post_import_working_set_bytes":working_set(server_pid)})
            finally:
                stop(proc,client)
            proc,client,_ = start(root)
            try:
                assert client.get("/api/notes").json()["items"][0]["content"] == "J0 synthetic"
                assert client.get("/api/versions").json()["items"][0]["version"] == "1.2.3"
                assert client.get(f'/api/kb/workbench/configs/{cfg["id"]}').json()["content"] == "a: 1"
                assert client.get(f"/api/logs/{log_id}").status_code == 200
            finally:
                stop(proc,client)
    report = {"python":sys.version,"platform":platform.platform(),"cpu":platform.processor(),
              "samples":samples,"passed":"CRUD, validation, byte limits, persisted restart, 50MiB, no-key SSE",
              "pending":"desktop cold start; backend only, no UI performance claim"}
    target = Path(__file__).resolve().parents[1]/"migration"/"j0"/"process-baseline.json"
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("PASS: three isolated processes/restarts, HTTP business fixtures and backend measurements")


if __name__ == "__main__":
    main()

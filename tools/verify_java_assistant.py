"""J5 isolated real HTTP assistant and MCP verification; never opens desktop apps."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from verify_java_offline import ROOT, java_server
from verify_java_generation import events


def fixture() -> None:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mode, pidfile = sys.argv[2:4]
    Path(pidfile).write_text(str(os.getpid()), encoding="utf-8")
    for line in sys.stdin:
        body = json.loads(line)
        if "id" not in body:
            continue
        if mode == "hang":
            time.sleep(20)
        if body["method"] == "initialize":
            result = {"protocolVersion":"2024-11-05", "capabilities":{"tools":{}}}
        elif body["method"] == "tools/list":
            result = {"tools":[{"name":"echo", "description":"synthetic echo"}]}
        else:
            result = {"content":[{"type":"text", "text":"MCP中文:"+body.get("params",{}).get("arguments",{}).get("text","")}]}
        if mode == "fail":
            reply = {"jsonrpc":"2.0", "id":body["id"], "error":{"code":-1,"message":"synthetic"}}
        else:
            # Interleave notifications; client must match request IDs.
            print(json.dumps({"jsonrpc":"2.0","method":"notifications/message","params":{}}),flush=True)
            reply = {"jsonrpc":"2.0", "id":body["id"], "result":result}
        print(json.dumps(reply,ensure_ascii=False),flush=True)


def alive(pid: int) -> bool:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p,ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000,False,pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle,0)==258
    finally:
        kernel.CloseHandle(handle)


class Model(BaseHTTPRequestHandler):
    captures: list[dict] = []
    action: dict | None = None
    http_session_seen = False

    def log_message(self,*args) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "method" in body:
            if self.path=="/mcp-hang":
                self.send_response(200); self.send_header("Content-Type","text/event-stream"); self.end_headers()
                try:
                    self.wfile.write(b"e"); self.wfile.flush(); time.sleep(5); self.wfile.write(b"nd")
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
                return
            method = body["method"]
            if method == "initialize":
                result = {"protocolVersion":"2024-11-05", "capabilities":{"tools":{}}}
            else:
                assert self.headers.get("Mcp-Session-Id")=="j5-session"
                Model.http_session_seen = True
                result = {"tools":[{"name":"echo","description":"HTTP synthetic"}]} if method=="tools/list" else {"content":[{"type":"text","text":"HTTP-MCP中文"}]}
            reply = {"jsonrpc":"2.0","id":body["id"],"result":result}
            data = ("event: message\ndata: "+json.dumps(reply,ensure_ascii=False)+"\n\n").encode("utf-8")
            self.send_response(200)
            self.send_header("Mcp-Session-Id","j5-session")
            self.send_header("Content-Type","text/event-stream")
            self.send_header("Content-Length",str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        Model.captures.append(body)
        model = body["model"]
        if model == "unauthorized":
            self.send_response(401); self.end_headers()
            self.wfile.write(b'{"error":{"message":"j5-test-synthetic-key"}}'); return
        if not body.get("stream"):
            data = json.dumps({"choices":[{"message":{"content":"摘要：第一轮主题，当前追问未决。"}}]},ensure_ascii=False).encode("utf-8")
            self.send_response(200); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        planning = "本轮只输出一个 JSON" in str(body["messages"][0]["content"])
        if planning:
            used = any(row["role"]=="assistant" and '"action"' in str(row["content"]) for row in body["messages"])
            output = json.dumps(Model.action if Model.action and not used else {"action":"final"},ensure_ascii=False)
        elif model == "protocol":
            output = '{"action":"final","answer":"协议剥离后的回答"}'
        elif model == "echo-key":
            output = "secret="+self.headers["Authorization"].removeprefix("Bearer ")+" 已隐藏"
        else:
            output = "当前问题的回答【命令：df】，中文附件已读取。"
        self.send_response(200); self.send_header("Content-Type","text/event-stream; charset=utf-8"); self.end_headers()
        try:
            for i in range(0,len(output),3):
                data = ("data: "+json.dumps({"choices":[{"delta":{"content":output[i:i+3]}}]},ensure_ascii=False)+"\n\n").encode("utf-8")
                for offset in range(0,len(data),5):
                    self.wfile.write(data[offset:offset+5]); self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
            pass


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1",0),Model)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    results: list[dict] = []
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/"java-app"/"target",prefix="j5-wire-") as folder:
            root = Path(folder)
            workspace = root/"授权工作区"; workspace.mkdir()
            outside = root/"外部"; outside.mkdir()
            sid = 0
            with java_server(root,root/"java.log",("--opsmate.mcp-timeout-seconds=2",)) as client:
                base = f"http://127.0.0.1:{server.server_port}"

                def configure(model: str = "normal") -> None:
                    assert client.put("/api/settings",json={"provider":"custom","base_url":base,"model":model,"api_key":"j5-test-synthetic-key"}).status_code==200

                def chat(message: str = "当前问题",**kwargs) -> list[dict]:
                    reply = events(client,"/api/assistant/chat",{"message":message,**kwargs})
                    assert "error" not in reply[-1],reply
                    assert reply[-1].get("done"),reply
                    assert "j5-test-synthetic-key" not in json.dumps(reply)
                    return reply

                def tool(name: str,args: dict) -> list[dict]:
                    Model.action={"action":"tool","tool":name,"args":args}
                    reply=chat()
                    Model.action=None
                    return reply

                configure()
                first=chat("第一轮主题",tools=False)
                sid=first[-1]["session_id"]
                assert len(Model.captures)==1,"direct mode must not plan tools"
                second=chat("第二轮追问",session_id=sid,tools=False)
                assert second[-1]["session_id"]==sid
                captured=Model.captures[-1]["messages"]
                assert captured[-1]["content"]=="第二轮追问" and any(row["content"]=="第一轮主题" for row in captured)
                results.append({"scenario":"direct zero tools/multi-turn current question","passed":True})

                file=client.post("/api/assistant/files",files={"file":("中文.conf","中文附件=是".encode(),"text/plain")}).json()
                raw=client.get(f"/api/assistant/files/{file['id']}/content")
                assert raw.content=="中文附件=是".encode()
                attachment_turn=chat("读取附件",attachments=[file["id"]],tools=False)
                attachment_sid=attachment_turn[-1]["session_id"]
                assert "中文附件=是" in str(Model.captures[-1])
                assert "error" in events(client,"/api/assistant/chat",{"message":"复用","attachments":[file["id"]]})[-1]
                assert client.post("/api/assistant/files",files={"file":("bad.txt",b"\xff","text/plain")}).status_code==415
                assert client.post("/api/assistant/files",files={"file":("big.txt",b"x"*(5*1024*1024+1),"text/plain")}).status_code==413
                results.append({"scenario":"attachment bytes/context/ownership/size/encoding","passed":True})

                configure("protocol"); assert "协议剥离后的回答" in str(chat(tools=False)); configure("echo-key")
                assert "[密钥已隐藏]" in str(chat(tools=False)); configure()
                results.append({"scenario":"protocol prefix/cross-chunk secret redaction","passed":True})

                reply=tool("write_file",{"filename":"输出.txt","content":"待确认内容"})
                proposal_sid=reply[-1]["session_id"]
                target=root/"java"/"agent_files"/"输出.txt"
                assert any("proposal" in event for event in reply) and not target.exists()
                assert client.post("/api/assistant/files/apply",json={"session_id":proposal_sid,"filename":"../越界.txt"}).status_code==400
                assert client.post("/api/assistant/files/apply",json={"session_id":proposal_sid,"filename":"输出.txt"}).json()["ok"]
                assert target.read_text(encoding="utf-8")=="待确认内容"
                assert client.post("/api/assistant/files/apply",json={"session_id":proposal_sid,"filename":"输出.txt"}).status_code==404
                cancelled=tool("write_file",{"filename":"取消.txt","content":"取消内容"})[-1]["session_id"]
                assert client.post("/api/assistant/files/cancel",json={"session_id":cancelled,"filename":"取消.txt"}).json()["ok"]
                assert not (target.parent/"取消.txt").exists()
                results.append({"scenario":"proposal confirmation/cancel/replay/traversal","passed":True})

                assert client.put("/api/assistant/workspace",json={"directories":[str(workspace)]}).json()["ok"]
                reply=tool("write_workspace_file",{"path":"子目录/你好.txt","content":"工作内容"})
                assert (workspace/"子目录"/"你好.txt").read_text(encoding="utf-8")=="工作内容"
                for name,args in (("read_workspace_file",{"path":"子目录/你好.txt"}),("list_dir",{"path":"子目录"}),("run_command",{"command":"echo synthetic","cwd":str(workspace)})):
                    reply=tool(name,args); assert '"ok":true' in next(e["result"] for e in reply if e.get("tool")==name),reply
                denied=tool("write_workspace_file",{"path":str(outside/"不应出现.txt"),"content":"outside"})
                assert '"ok":false' in next(e["result"] for e in denied if e.get("tool")=="write_workspace_file") and not (outside/"不应出现.txt").exists()
                results.append({"scenario":"workspace real read/write/list/command/outside denial","passed":True})

                junction=workspace/"越界联接"
                created=subprocess.run(["cmd.exe","/d","/c","mklink","/J",str(junction),str(outside)],capture_output=True,encoding="utf-8",errors="replace")
                assert created.returncode==0,"test junction creation failed"
                try:
                    denied=tool("write_workspace_file",{"path":str(junction/"new"/"拒绝.txt"),"content":"outside"})
                    assert '"ok":false' in str(denied) and not (outside/"new").exists()
                finally:
                    os.rmdir(junction)
                zip_source=workspace/"恶意.zip"
                with zipfile.ZipFile(zip_source,"w") as bundle: bundle.writestr("../escape.txt","outside")
                denied=tool("archive_files",{"action":"unzip","source":str(zip_source),"target":str(workspace/"解压")})
                assert '"ok":false' in str(denied) and not (workspace/"escape.txt").exists()
                for args in ({"action":"zip","source":"子目录","target":"合成.zip"},{"action":"unzip","source":"合成.zip","target":"展开"}):
                    reply=tool("archive_files",args); assert '"ok":true' in str(reply)
                assert (workspace/"展开"/"你好.txt").read_text(encoding="utf-8")=="工作内容"
                results.append({"scenario":"actual Windows junction denial/zip-slip/zip roundtrip","passed":True})

                config=client.post("/api/kb/workbench/configs",json={"name":"引用配置","format":"text","content":"PRIVATE_CONFIG_CONTENT"}).json()
                cid=config["id"]
                client.put(f"/api/kb/workbench/configs/{cid}/share",json={"shared":True})
                assert "PRIVATE_CONFIG_CONTENT" in str(tool("read_user_config",{"name":"引用配置"}))
                client.put(f"/api/kb/workbench/configs/{cid}/share",json={"shared":False})
                Model.captures.clear(); tool("read_user_config",{"name":"引用配置"})
                assert "PRIVATE_CONFIG_CONTENT" not in str(Model.captures)
                chat("显式引用",tools=False,config_refs=["引用配置"])
                assert "PRIVATE_CONFIG_CONTENT" in str(Model.captures[-1])
                results.append({"scenario":"sharing revoked next request/explicit reference authorized","passed":True})

                skills=client.get("/api/assistant/skills").json()["items"]; assert len(skills)>=6
                content="name: j5-test\nlabel: 合成技能\ntriggers: [独有触发]\nmethodology: 方法论合成内容\n"
                assert client.post("/api/assistant/skills",json={"name":"j5-test","content":content}).json()["ok"]
                assert client.post("/api/assistant/skills",json={"name":"j5-duplicate","content":content}).status_code==400
                chat("独有触发"); assert "方法论合成内容" in str(Model.captures[-1])
                assert client.delete("/api/assistant/skills/j5-test").json()["ok"]
                denied=tool("install_skill",{"url":base+"/private"}); assert '"ok":false' in str(denied)
                results.append({"scenario":"skill install/match/duplicate/delete/private URL rejection","passed":True})

                for name,args in (("system_info",{}),("list_processes",{"name":"java","limit":3}),
                                  ("manage_workspace",{"action":"add","path":str(workspace)})):
                    assert '"ok":true' in str(tool(name,args))
                for name,args in (("stop_process",{"pid":"invalid"}),("schedule_task",{"action":"create","name":"test","schedule":"daily 99:99","command":"echo no"}),
                                  ("open_path",{"path":str(outside/"missing")}),
                                  ("web_fetch",{"url":base+"/private"}),("download_file",{"url":base+"/private","filename":"private.txt"})):
                    assert '"ok":false' in str(tool(name,args))
                kb="software: j5-synthetic\nlabel: 合成软件\ncategories:\n  - id: cli\n    entries:\n      - name: check\n        example: check\n        danger: false\n  - id: conf\n    entries:\n      - name: port\n        section: server\n        danger: low\n"
                assert '"ok":true' in str(tool("install_kb",{"filename":"j5-synthetic","content":kb}))
                assert client.get("/api/kb/j5-synthetic").status_code==200
                configured=tool("configure_api",{"base_url":base,"api_key":"j5-new-test-key","model":"unauthorized","provider":"custom"})
                assert "401" in str(configured) and "j5-new-test-key" not in str(configured)
                configure()
                results.append({"scenario":"system tools read/denied boundaries/KB installation/API failure diagnosis","passed":True})

                pids=[]
                for mode in ("ok","fail","hang"):
                    pidfile=root/f"mcp-{mode}.pid"
                    command=[sys.executable,str(Path(__file__).resolve()),"--mcp-fixture",mode,str(pidfile)]
                    body={"name":"stdio-"+mode,"transport":"stdio","command":command,"enabled":True}
                    server_id=client.post("/api/mcp",json=body).json()["id"]
                    tested=client.post(f"/api/mcp/{server_id}/test").json()
                    pid=int(pidfile.read_text(encoding="utf-8")); pids.append(pid)
                    if mode=="ok":
                        assert tested["ok"] and tested["tools"][0]["name"]=="echo"
                        reply=tool("mcp__stdio-ok__echo",{"text":"测试"}); assert "MCP中文:测试" in str(reply),reply
                        disabled={**body,"enabled":False}; assert client.put(f"/api/mcp/{server_id}",json=disabled).json()["ok"]
                    else:
                        assert not tested["ok"]
                    assert client.delete(f"/api/mcp/{server_id}").json()["ok"]
                    for _ in range(30):
                        if not alive(pid): break
                        time.sleep(0.05)
                    assert not alive(pid),f"MCP child still alive: {pid}"
                http_id=client.post("/api/mcp",json={"name":"http-test","transport":"http","url":base+"/mcp"}).json()["id"]
                assert client.post(f"/api/mcp/{http_id}/test").json()["ok"]
                assert "HTTP-MCP中文" in str(tool("mcp__http-test__echo",{})) and Model.http_session_seen
                client.delete(f"/api/mcp/{http_id}")
                hanging=client.post("/api/mcp",json={"name":"http-hang","transport":"http","url":base+"/mcp-hang"}).json()["id"]
                started=time.monotonic()
                assert not client.post(f"/api/mcp/{hanging}/test").json()["ok"]
                assert time.monotonic()-started<4,"MCP body deadline must release stream"
                client.delete(f"/api/mcp/{hanging}")
                failed_pid=root/"install-failed.pid"
                reply=tool("install_mcp",{"name":"rollback","transport":"stdio","command":[sys.executable,str(Path(__file__).resolve()),"--mcp-fixture","fail",str(failed_pid)]})
                assert "已自动回滚" in str(reply)
                assert not client.get("/api/mcp").json()["items"]
                assert not alive(int(failed_pid.read_text(encoding="utf-8")))
                results.append({"scenario":"MCP stdio/HTTP/SSE/notifications/session/call/timeout/disable/rollback/no children","passed":True})

                for _ in range(6): chat("后续轮",session_id=sid,tools=False)
                assert "历史对话摘要" in str(Model.captures[-1])
                results.append({"scenario":"long session summary preserves recent turns","passed":True})
                assert client.delete(f"/api/assistant/sessions/{attachment_sid}").json()["ok"]
                assert client.get(f"/api/assistant/files/{file['id']}/content").status_code==404
            with java_server(root,root/"restart.log") as client:
                assert client.get(f"/api/assistant/sessions/{sid}").status_code==200
                assert client.get("/api/assistant/workspace").json()["directories"]==[str(workspace.resolve())]
                assert all(s["name"]!="j5-test" for s in client.get("/api/assistant/skills").json()["items"])
                assert client.get("/api/mcp").json()["items"]==[]
                assert client.get("/api/kb/j5-synthetic").status_code==200
                results.append({"scenario":"restart sessions/workspace/deleted skills/MCP","passed":True})
    finally:
        server.shutdown(); server.server_close()
    directory=ROOT/"migration"/"j5"; directory.mkdir(exist_ok=True)
    (directory/"assistant-wire.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print("J5 assistant/MCP HTTP verification passed:",len(results))


if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--mcp-fixture": fixture()
    else: main()

"""J4 本机模拟模型的端到端 SSE、历史、诊断与配置验收。"""
from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
from verify_java_offline import ROOT, java_server

SCRIPT = {
    "need_clarification":False,
    "script":"#!/usr/bin/env bash\n# 用途 用法 参数 依赖 适用 AI生成请审阅\nset -euo pipefail\necho \"synthetic\"",
    "explanation":[{"lines":str(i),"title":"synthetic","detail":"synthetic"} for i in range(1,4)],
    "warnings":[],"usage":"synthetic"
}
REPORT = "## 结论速览\n发现连接错误。\n## 问题清单\n### 问题1\n证据：聚类 1，行号 1。根因不确定。\n## 下一步排查建议\n检查服务。"


class Model(BaseHTTPRequestHandler):
    def log_message(self,*args) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = body["model"]
        if model=="slow":
            time.sleep(5)
        if model=="network":
            self.send_response(503); self.end_headers(); return
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type","text/event-stream; charset=utf-8")
            self.end_headers()
            if model.startswith("log"):
                report = "broken" if model=="log-invalid" else REPORT
            elif model=="multi":
                report=json.dumps({"scripts":[{"name":name,**SCRIPT} for name in ("甲脚本","乙脚本","丙脚本")]},ensure_ascii=False)
            else:
                report=json.dumps({**SCRIPT,"script":"broken"} if model=="invalid" else SCRIPT,ensure_ascii=False)
            try:
                if model=="slow-final": time.sleep(5)
                for fragment in (report[:12],report[12:]):
                    data = ("data: "+json.dumps({"choices":[{"delta":{"content":fragment}}]},ensure_ascii=False)+"\n\n").encode("utf-8")
                    # Deliberately split UTF-8 code units across writes.
                    for i in range(0,len(data),7):
                        self.wfile.write(data[i:i+7]); self.wfile.flush()
                    time.sleep(0.03)
                self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
                pass
            return
        system = str(body["messages"][0]["content"])
        if "下钻规划" in system:
            content = json.dumps({"action":"final","answer":"ready"})
        elif "当前只做资料" in system:
            if model=="malformed":
                content = "not-json"
            elif model=="budget":
                content = json.dumps({"action":"tool","tool":"search_kb","args":{"q":"nginx","limit":1}})
            else:
                content = json.dumps({"action":"final","payload":{"need_clarification":True,"questions":["目标路径是什么？"]} if model=="clarify" else {}})
        elif model=="multi":
            content = json.dumps({"scripts":[{"name":name,**SCRIPT} for name in ("甲脚本","乙脚本","丙脚本")]},ensure_ascii=False)
        elif model=="invalid":
            content = json.dumps({**SCRIPT,"script":"broken"})
        elif "回复 pong" in str(body["messages"]):
            content = "pong"
        else:
            content = "```json\n"+json.dumps(SCRIPT,ensure_ascii=False)+"\n```"
        data = json.dumps({"choices":[{"message":{"content":content}}]},ensure_ascii=False).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data))); self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass


def events(client,path,payload):
    response = client.post(path,json=payload)
    assert response.status_code==200,response.text
    assert "text/event-stream" in response.headers["content-type"]
    return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]


def main() -> None:
    model = ThreadingHTTPServer(("127.0.0.1",0),Model)
    worker = threading.Thread(target=model.serve_forever,daemon=True)
    worker.start()
    results = []
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/"java-app"/"target",prefix="j4-wire-") as folder:
            root = Path(folder)
            with java_server(root,root/"java.log",("--opsmate.generation-budget-seconds=3",)) as client:
                missing = events(client,"/api/codegen/generate",{"requirement":"synthetic"})
                assert "error" in missing[-1]
                assert not client.get("/api/codegen/history").json()["items"]
                base = f"http://127.0.0.1:{model.server_port}"
                def configure(name):
                    response = client.put("/api/settings",json={"provider":"custom","base_url":base,
                        "model":name,"api_key":"j4-local-synthetic-key"})
                    assert response.json()=={"ok":True}
                    public = client.get("/api/settings").json()
                    assert public["api_key_set"] and "api_key" not in public
                for name in ("single","multi","clarify","invalid","network","malformed","budget"):
                    configure(name)
                    before = len(client.get("/api/codegen/history").json()["items"])
                    data = events(client,"/api/codegen/generate",{"requirement":"两个脚本 synthetic" if name=="multi" else "synthetic"})
                    assert "j4-local-synthetic-key" not in json.dumps(data)
                    after = len(client.get("/api/codegen/history").json()["items"])
                    if name in ("invalid","network"):
                        assert "error" in data[-1] and before==after,(name,data)
                    else:
                        assert data[-1]["done"]
                        result = next(item["result"] for item in data if "result" in item and "tool" not in item)
                        if name=="clarify":
                            assert result["need_clarification"] and before==after
                        else:
                            assert after==before+1
                            assert any("tool" in item for item in data)
                            latest = client.get("/api/codegen/history").json()["items"][0]["id"]
                            stored = client.get(f"/api/codegen/history/{latest}").json()
                            if name=="multi":
                                assert len(result["scripts"])==3 and stored["scripts"]==result["scripts"]
                            if name=="budget": assert len([item for item in data if "tool" in item])<=6
                            if name=="malformed": assert result["steps"]==[]
                    results.append({"scenario":name,"passed":True})
                assert client.post("/api/codegen/generate",json={"requirement":"x"*60001}).status_code==422
                configure("clarify")
                assert events(client,"/api/codegen/generate",{"requirement":"x"*60000})[-1]["done"]
                log = client.post("/api/logs",json={"title":"synthetic","content":"ERROR connection failed\nWARN retry\nWARN retry"}).json()["id"]
                other = client.post("/api/logs",json={"title":"unrelated","content":"ERROR unrelated"}).json()["id"]
                configure("log")
                report = events(client,f"/api/logs/{log}/llm-analyze",{})
                assert "tool" in report[0] and any("delta" in event for event in report)
                rid = report[-1]["report_id"]
                assert client.get(f"/api/logs/{log}/reports/{rid}").json()["content"]==REPORT
                assert client.get(f"/api/logs/{other}/reports/{rid}").status_code==404
                configure("log-invalid")
                failure = events(client,f"/api/logs/{log}/llm-analyze",{})
                assert "error" in failure[-1]
                assert len(client.get(f"/api/logs/{log}/reports").json()["items"])==1
                assert client.post("/api/llm/test").json()["ok"]
                results.append({"scenario":"log report/history/scope/invalid","passed":True})
                configure("slow")
                before = len(client.get("/api/codegen/history").json()["items"])
                started = time.perf_counter()
                timed_out = events(client,"/api/codegen/generate",{"requirement":"synthetic slow"})
                assert "error" in timed_out[-1] and time.perf_counter()-started<10
                assert len(client.get("/api/codegen/history").json()["items"])==before
                assert client.get("/api/health").status_code==200
                results.append({"scenario":"total deadline cancellation/no history","passed":True})
                configure("slow-final")
                before=len(client.get("/api/codegen/history").json()["items"])
                started=time.perf_counter()
                timed_out=events(client,"/api/codegen/generate",{"requirement":"synthetic final stream stall"})
                assert "error" in timed_out[-1] and time.perf_counter()-started<10
                assert len(client.get("/api/codegen/history").json()["items"])==before
                assert client.get("/api/health").status_code==200
                results.append({"scenario":"final stream body stall cancelled/no partial history","passed":True})
            with java_server(root,root/"restart.log") as client:
                assert client.get("/api/settings").json()["api_key_set"]
                assert len(client.get("/api/codegen/history").json()["items"])==4
                assert len(client.get(f"/api/logs/{log}/reports").json()["items"])==1
            output = ROOT/"migration"/"j4"
            output.mkdir(parents=True,exist_ok=True)
            (output/"generation-wire.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
            print("PASS: simulated model SSE, three scripts, clarification, quality/network failures, fallback, budget, long input, reports, restart")
    finally:
        model.shutdown(); model.server_close(); worker.join(timeout=5)


if __name__=="__main__":
    main()

"""J4 已启用模型验收，只发送合成需求，不打印或发布本机 key。"""
from __future__ import annotations
import json
import argparse
from pathlib import Path
import tempfile
import time
from verify_java_offline import ROOT, java_server
from verify_java_generation import events


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--connect-only",action="store_true")
    args=parser.parse_args()
    settings=json.loads((ROOT/"data"/"config.json").read_text(encoding="utf-8"))
    assert settings.get("api_key"),"No locally enabled model key"
    results=[]
    with tempfile.TemporaryDirectory(dir=ROOT/"java-app"/"target",prefix="j4-live-") as folder:
        root=Path(folder)
        with java_server(root,root/"java.log") as client:
            client.timeout=60
            assert client.put("/api/settings",json={key:settings.get(key,"") for key in ("provider","base_url","model","api_key")}).json()=={"ok":True}
            if args.connect_only:
                response=client.post("/api/llm/test").json()
                output=ROOT/"migration"/"j4"
                output.mkdir(parents=True,exist_ok=True)
                (output/"live-connection.json").write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding="utf-8")
                print(json.dumps(response,ensure_ascii=True))
                return
            started=time.perf_counter()
            generation=events(client,"/api/codegen/generate",{"requirement":"生成一个 Bash 脚本，使用 df -h 查看磁盘占用并输出中文提示，不做修改，不需要定时。"})
            complete=next((event["result"] for event in generation if "result" in event and "tool" not in event),None)
            if complete is None or complete.get("need_clarification"):
                diagnostic=next((event.get("error") for event in generation if event.get("error")),"unexpected clarification")
                diagnostic=str(diagnostic).replace(settings["api_key"],"[密钥已隐藏]")
                raise AssertionError("Live codegen failed: "+diagnostic[:500])
            assert generation[-1].get("done"),"Live codegen did not finish"
            results.append({"scenario":"synthetic disk inspection script","seconds":round(time.perf_counter()-started,3),
                            "tool_events":sum("tool" in item for item in generation),"passed":True})
            log=client.post("/api/logs",json={"title":"J4 synthetic connection errors","content":"\n".join(
                f"2026-11-05 10:00:{i:02d} ERROR connection timeout request={i}" if i%5==0 else
                f"2026-11-05 10:00:{i:02d} INFO synthetic healthy request={i}" for i in range(40))}).json()["id"]
            started=time.perf_counter()
            analysis=events(client,f"/api/logs/{log}/llm-analyze",{})
            assert analysis[-1].get("done") and analysis[-1].get("report_id"),"Live report did not validate and save"
            assert client.get(f"/api/logs/{log}/reports").json()["items"],"Live report missing from history"
            results.append({"scenario":"synthetic log diagnosis","seconds":round(time.perf_counter()-started,3),
                            "tool_events":sum("tool" in item for item in analysis),"passed":True})
    # Report metadata only, excluding model output and all model configuration.
    output=ROOT/"migration"/"j4"
    output.mkdir(parents=True,exist_ok=True)
    (output/"live-synthetic.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print("PASS: locally enabled model generated synthetic script and persisted synthetic log report; no scripts executed")


if __name__=="__main__":
    main()

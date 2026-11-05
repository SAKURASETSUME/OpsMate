"""J4 已启用模型验收，只发送合成需求，不打印或发布本机 key。"""
from __future__ import annotations
import json
import argparse
import os
from pathlib import Path
import tempfile
import time
from verify_java_offline import ROOT, java_server
from verify_java_generation import events


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--connect-only",action="store_true")
    parser.add_argument("--dsh-volcengine",action="store_true")
    parser.add_argument("--dsh-model",default="")
    args=parser.parse_args()
    if args.dsh_volcengine:
        import yaml
        path=Path(os.environ['APPDATA'])/'dsh-desktop/harness/profiles/web/cordis.patch.yml'
        document=yaml.safe_load(path.read_text(encoding='utf-8'))
        provider=next(row['config']['providers']['volcengine-ark'] for row in document if isinstance(row,dict) and 'volcengine-ark' in row.get('config',{}).get('providers',{}))
        key=os.environ.get(provider.get('apiKeyEnv',''),'')
        assert key,'DSH Volcengine key environment variable is not available'
        models=[item['id'] for item in provider.get('models',[]) if isinstance(item,dict) and item.get('id')]
        model=args.dsh_model or ('ark-code-latest' if 'ark-code-latest' in models else models[0])
        assert model in models,'model must already exist in the DSH Volcengine configuration'
        settings={'provider':'custom','base_url':provider['baseURL'],'model':model,'api_key':key}
    else:
        settings=json.loads((ROOT/"data"/"config.json").read_text(encoding="utf-8"))
    assert settings.get("api_key"),"No locally enabled model key"
    output=ROOT/'migration'/('j6' if args.dsh_volcengine else 'j4')
    output.mkdir(parents=True,exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(dir=ROOT/"java-app"/"target",prefix="j4-live-") as folder:
        root=Path(folder)
        with java_server(root,root/"java.log") as client:
            client.timeout=60
            assert client.put("/api/settings",json={key:settings.get(key,"") for key in ("provider","base_url","model","api_key")}).json()=={"ok":True}
            if args.connect_only:
                response=client.post("/api/llm/test").json()
                (output/("volcengine-connection.json" if args.dsh_volcengine else "live-connection.json")).write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding="utf-8")
                print(json.dumps(response,ensure_ascii=True))
                return
            started=time.perf_counter()
            generation=events(client,"/api/codegen/generate",{"requirement":"生成一个 Bash 脚本，使用 df -h 查看磁盘占用并输出中文提示，不做修改，不需要定时。"})
            complete=next((event["result"] for event in generation if "result" in event and "tool" not in event),None)
            if complete is None or complete.get("need_clarification"):
                diagnostic=next((event.get("error") for event in generation if event.get("error")),"unexpected clarification")
                diagnostic=str(diagnostic).replace(settings["api_key"],"[密钥已隐藏]")
                (output/'live-failure.json').write_text(json.dumps({'stage':'codegen','model':settings['model'],'error':diagnostic[:500],
                    'phases':[event['phase'] for event in generation if 'phase' in event],
                    'tools':[event['tool'] for event in generation if 'tool' in event]},ensure_ascii=False,indent=2),encoding='utf-8')
                raise AssertionError("Live codegen failed: "+diagnostic[:500])
            assert generation[-1].get("done"),"Live codegen did not finish"
            results.append({"scenario":"synthetic disk inspection script","model":settings['model'],"seconds":round(time.perf_counter()-started,3),
                            "tool_events":sum("tool" in item for item in generation),"passed":True})
            print("PASS: live synthetic script validated and saved; scripts were not executed",flush=True)
            log=client.post("/api/logs",json={"title":"J4 synthetic connection errors","content":"\n".join(
                f"2026-11-05 10:00:{i:02d} ERROR connection timeout request={i}" if i%5==0 else
                f"2026-11-05 10:00:{i:02d} INFO synthetic healthy request={i}" for i in range(40))}).json()["id"]
            started=time.perf_counter()
            analysis=events(client,f"/api/logs/{log}/llm-analyze",{})
            if not (analysis[-1].get("done") and analysis[-1].get("report_id")):
                diagnostic=next((event.get("error") for event in analysis if event.get("error")),"missing completion")
                raise AssertionError("Live report failed: "+str(diagnostic).replace(settings["api_key"],"[密钥已隐藏]")[:500])
            assert client.get(f"/api/logs/{log}/reports").json()["items"],"Live report missing from history"
            results.append({"scenario":"synthetic log diagnosis","model":settings['model'],"seconds":round(time.perf_counter()-started,3),
                            "tool_events":sum("tool" in item for item in analysis),"passed":True})
    # Report metadata only, excluding model output and all model configuration.
    (output/("volcengine-synthetic.json" if args.dsh_volcengine else "live-synthetic.json")).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print("PASS: locally enabled model generated synthetic script and persisted synthetic log report; no scripts executed")


if __name__=="__main__":
    main()

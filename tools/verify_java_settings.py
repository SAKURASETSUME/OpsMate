"""J4 模型档案 HTTP 差分，合成密钥只进本机临时目录。"""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
from verify_java_baseline import start, stop
from verify_java_offline import ROOT, java_server


def replay(client):
    snapshots = []
    aliases = {}
    def canonical(value):
        if isinstance(value,dict): return {key:canonical(item) for key,item in value.items()}
        if isinstance(value,list): return [canonical(item) for item in value]
        if isinstance(value,str): return aliases.get(value,value)
        return value
    def request(name,method,path,payload=None):
        response = client.request(method,path,json=payload) if payload is not None else client.request(method,path)
        value = response.json()
        assert "j4-config-secret" not in response.text
        if name=="profile create": aliases[value["id"]]="profile-generated"
        snapshots.append({"name":name,"status":response.status_code,"body":canonical(value)})
        return value
    request("initial settings","GET","/api/settings")
    request("initial profiles","GET","/api/settings/profiles")
    body = {"provider":"custom","base_url":"https://example.invalid/v1///","model":"first","api_key":"j4-config-secret-first"}
    request("save","PUT","/api/settings",body)
    request("public","GET","/api/settings")
    request("preserve key","PUT","/api/settings",{**body,"api_key":""})
    profile = request("profile create","POST","/api/settings/profiles",{**body,"name":"独立档案","model":"second","api_key":""})["id"]
    request("new not active","GET","/api/settings")
    request("empty cannot activate","POST",f"/api/settings/profiles/{profile}/activate")
    request("profile update","PUT",f"/api/settings/profiles/{profile}",{**body,"name":"独立档案","model":"second","api_key":"j4-config-secret-second"})
    request("profile activate","POST",f"/api/settings/profiles/{profile}/activate")
    request("activated snapshot","GET","/api/settings")
    request("profiles","GET","/api/settings/profiles")
    request("bad provider","PUT","/api/settings",{**body,"provider":"invalid"})
    request("missing profile","POST","/api/settings/profiles/does-not-exist/activate")
    return snapshots


def main() -> None:
    with tempfile.TemporaryDirectory(dir=ROOT/"java-app"/"target",prefix="j4-settings-") as folder:
        root = Path(folder)
        pyroot = root/"python"
        pyroot.mkdir()
        proc,python,_ = start(pyroot)
        try:
            expected = replay(python)
            with java_server(root,root/"java.log") as java:
                actual = replay(java)
                for body in ({},{"base_url":"https://example.invalid","model":"x","api_key":"x"*8193}):
                    response=java.put("/api/settings",json=body)
                    assert response.status_code==422 and "input" not in response.text
            assert expected==actual,[(a,b) for a,b in zip(expected,actual) if a!=b]
            with java_server(root,root/"restart.log") as java:
                assert java.get("/api/settings").json()["model"]=="second"
                assert java.get("/api/settings").json()["api_key_set"]
            output = ROOT/"migration"/"j4"
            output.mkdir(parents=True,exist_ok=True)
            (output/"settings-differential.json").write_text(json.dumps(actual,ensure_ascii=False,indent=2),encoding="utf-8")
            print(f"PASS: {len(actual)} settings/profile differential cases; validation privacy; restart")
        finally:
            stop(proc,python)


if __name__=="__main__":
    main()

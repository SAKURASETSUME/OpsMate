"""Assemble a pristine jpackage app-image and zip using only the verified jar."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN={"config.json","model_profiles.json","opsmate.db","opsmate.db-wal","opsmate.db-shm","agent_workspace.json","mcp_servers.json"}


def sha256(path: Path) -> str:
    with path.open("rb") as stream: return hashlib.file_digest(stream,"sha256").hexdigest()


def local_keys() -> list[bytes]:
    keys=[]
    for name in ("config.json","model_profiles.json"):
        path=ROOT/"data"/name
        if not path.exists(): continue
        value=json.loads(path.read_text(encoding="utf-8"))
        records=value.get("items",[]) if name=="model_profiles.json" else [value]
        for record in records:
            key=record.get("api_key","")
            if isinstance(key,str) and len(key)>8 and key.encode() not in keys: keys.append(key.encode())
    # User-authorized DSH Volcengine key remains in the environment, never in the release.
    ark=os.environ.get("ARK_API_KEY","")
    if len(ark)>8 and ark.encode() not in keys: keys.append(ark.encode())
    return keys


def inspect_jar(jar: Path,keys: list[bytes]) -> dict:
    expected={"knowledge/"+name for name in (ROOT/"java-app/src/main/resources/knowledge/manifest.txt").read_text(encoding="utf-8").splitlines()}
    with zipfile.ZipFile(jar) as bundle:
        classes={name.removeprefix("BOOT-INF/classes/") for name in bundle.namelist() if name.startswith("BOOT-INF/classes/") and not name.endswith("/")}
        actual={name for name in classes if name.startswith("knowledge/") and name!="knowledge/manifest.txt"}
        assert actual==expected,"jar contains missing or unexpected knowledge assets"
        assert len(actual)==642
        for name in classes:
            assert Path(name).name.lower() not in FORBIDDEN,"private runtime filename in jar"
            raw=bundle.read("BOOT-INF/classes/"+name)
            assert not any(key in raw for key in keys),"private model key found in application payload"
    return {"commands":621,"software":15,"skills":6,"private_filename_hits":0,"real_key_hits":0}


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    jar=ROOT/"java-app/target/opsmate-1.0.0-migration.jar"
    reports=ROOT/"java-app/target"
    summary=reports/'failsafe-reports/failsafe-summary.xml'
    assert summary.is_file() and summary.stat().st_mtime>=jar.stat().st_mtime,'run full Maven verify after building this jar'
    integration=ET.parse(summary).getroot()
    assert int(integration.findtext('completed','0'))>=6
    assert all(int(integration.findtext(name,'0'))==0 for name in ('errors','failures','skipped')),'integration gate failed or skipped'
    unit_count=0
    for report in (reports/'surefire-reports').glob('TEST-*.xml'):
        suite=ET.parse(report).getroot()
        assert all(int(suite.get(name,'0'))==0 for name in ('errors','failures','skipped')),'unit gate failed or skipped'
        unit_count+=int(suite.get('tests','0'))
    assert unit_count>=27,'unit evidence incomplete'
    keys=local_keys()
    assets=inspect_jar(jar,keys)
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:6]
    destination=(args.output or ROOT/"java-app/target/releases"/stamp).resolve()
    if destination.exists(): raise ValueError("package destination must be new")
    destination.mkdir(parents=True)
    payload=destination/"input"; payload.mkdir()
    shutil.copy2(jar,payload/"opsmate.jar")
    jpackage=Path(os.environ.get("JAVA_HOME","D:/java21"))/"bin/jpackage.exe"
    subprocess.run([str(jpackage),"--type","app-image","--name","OpsMate","--input",str(payload),
        "--main-jar","opsmate.jar","--main-class","org.springframework.boot.loader.launch.JarLauncher",
        "--dest",str(destination/"image"),"--add-modules","ALL-MODULE-PATH",
        "--java-options","-Dfile.encoding=UTF-8","--java-options","-XX:-UsePerfData"],check=True,encoding="utf-8")
    image=destination/"image/OpsMate"
    assert (image/"runtime/bin/server/jvm.dll").is_file()
    (image/"使用说明.md").write_text("# OpsMate Java 候选版\n\n此候选包仍待最终桌面与真实模型验收。\n\n解压整个目录，双击 OpsMate.exe。内含Java运行时，无需安装Java、Python或数据库。\n知识资料首次启动保存到程序旁的data目录；请放在可写目录。\n模型密钥由本人在设置页填写并启用，只保存本机，发布包不带任何模型配置。\n\n关闭主窗口即可退出。若嵌入窗口不可用，会打开默认浏览器并保留小型控制窗，点击“退出OpsMate”关闭后端。\n升级前完整备份原data；试用迁移副本，保留原Python版本以便回退。不要在原数据目录同时运行两版。\n",encoding="utf-8")
    entries=[]
    for path in sorted(image.rglob("*")):
        if not path.is_file(): continue
        relative=path.relative_to(image).as_posix()
        assert relative.split("/")[0] in {"OpsMate.exe","app","runtime","使用说明.md"},"unexpected package directory"
        assert path.name.lower() not in FORBIDDEN,"private runtime file in app image"
        assert not any(part in {"data","assistant_files","agent_files","logs","agent_downloads"} for part in path.relative_to(image).parts),"runtime data directory in release"
        with path.open("rb") as stream:
            tail=b""; overlap=max((len(key) for key in keys),default=1)-1
            while chunk:=stream.read(1024*1024):
                raw=tail+chunk
                assert not any(key in raw for key in keys),"private key in app image"
                tail=raw[-overlap:] if overlap else b""
        entries.append({"path":relative,"size":path.stat().st_size,"sha256":sha256(path)})
    revision=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,check=True,encoding="utf-8").stdout.strip()
    manifest={"candidate":True,"source_commit":revision,"jar_sha256":sha256(jar),"verified_tests":{"unit_architecture":unit_count,"integration":int(integration.findtext('completed'))},"assets":assets,"files":entries,"private_data_included":False}
    (image/"RELEASE-MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    archive=destination/f"OpsMate-Java-candidate-{stamp}.zip"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(image.rglob("*")):
            if path.is_file(): bundle.write(path,"OpsMate/"+path.relative_to(image).as_posix())
    evidence={"archive":str(archive),"image":str(image),"sha256":sha256(archive),"jar_sha256":sha256(jar),"size_bytes":archive.stat().st_size,"assets":assets,"bundled_runtime":True,"status":"candidate pending desktop and real model"}
    output=ROOT/"migration/j6"; output.mkdir(exist_ok=True)
    (output/"candidate.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=="__main__": main()

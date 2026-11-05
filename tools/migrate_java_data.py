"""Copy local data for Java trial; source stays intact, destination must be new.

This tool copies private local files. Its destination must never be used as a release payload.
Stop the old application first: SQLite backup is consistent, external files need a quiet source.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle,"sha256").hexdigest()


def migrate(source: Path,destination: Path) -> dict:
    source=source.resolve(strict=True)
    destination=destination.resolve()
    if destination==source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("source and destination must be separate non-nested directories")
    repository=Path(__file__).resolve().parents[1]
    private_roots=(repository/"local-java-data",repository/"local-java-backups",repository/"java-app/target")
    if destination.is_relative_to(repository) and not any(destination.is_relative_to(root) for root in private_roots):
        raise ValueError("inside this repository use ignored local-java-data/local-java-backups only")
    if destination.exists():
        raise ValueError("destination already exists; no files were overwritten")
    if not (source/"opsmate.db").is_file():
        raise ValueError("source database missing")
    destination.mkdir(parents=True)
    files=0
    try:
        for directory in ("logs","agent_files","kb","skills","commands"):
            original=source/directory
            if not original.exists(): continue
            for path in original.rglob("*"):
                if not path.is_file(): continue
                if not path.resolve().is_relative_to(source): raise ValueError("source contains an external link")
                relative=path.relative_to(source)
                target=destination/relative
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,target)
                if digest(path)!=digest(target): raise ValueError("copy checksum mismatch")
                files+=1
        # Private profiles/authorizations stay exclusively in this local migration copy.
        for name in ("config.json","model_profiles.json","agent_workspace.json","mcp_servers.json"):
            path=source/name
            if path.is_file():
                if not path.resolve().is_relative_to(source): raise ValueError("private config points outside source")
                shutil.copy2(path,destination/name)
                files+=1
        with closing(sqlite3.connect((source/"opsmate.db").as_uri()+"?mode=ro",uri=True)) as old, closing(sqlite3.connect(destination/"opsmate.db")) as new:
            old.backup(new)
            if new.execute("PRAGMA integrity_check").fetchone()[0]!="ok": raise ValueError("backup integrity check failed")
            tables={row[0] for row in new.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            attachments=0
            if "assistant_attachments" in tables:
                for file_id,filename,size in new.execute("SELECT id,path,size_bytes FROM assistant_attachments").fetchall():
                    path=Path(filename)
                    if not path.is_absolute(): path=source/path
                    path=path.resolve(strict=True)
                    if not path.is_relative_to(source): raise ValueError("attachment points outside source")
                    target=destination/"assistant_files"/str(file_id)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(path,target)
                    if target.stat().st_size!=size or digest(path)!=digest(target): raise ValueError("attachment checksum mismatch")
                    new.execute("UPDATE assistant_attachments SET path=? WHERE id=?",(str(target),file_id))
                    attachments+=1
            new.commit()
            count={table:new.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0] for table in ("assistant_sessions","assistant_messages","assistant_attachments","codegen_history","logs","log_lines","reports","user_configs","notes","versions") if table in tables}
        report={"integrity":"ok","copied_files":files,"attachments":attachments,"row_counts":count,"source_untouched":True,"private_local_copy":True}
        (destination/".migration.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        return report
    except BaseException:
        # Keep evidence for inspection; do not recursively remove a computed destination.
        (destination/".migration-failed").write_text("Migration incomplete. Do not launch this copy.",encoding="utf-8")
        raise


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",required=True,type=Path)
    parser.add_argument("--destination",required=True,type=Path)
    args=parser.parse_args()
    report=migrate(args.source,args.destination)
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":
    main()

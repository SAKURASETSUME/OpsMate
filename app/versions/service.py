"""版本记录持久化：包名/版本必填，描述与上传日期选填。"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from app import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_versions() -> None:
    config.ensure_dirs()
    with closing(_connect()) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""
        CREATE TABLE IF NOT EXISTS version_records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          package TEXT NOT NULL,
          version TEXT NOT NULL,
          description TEXT,
          release_date TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))""")
        connection.commit()


def check_fields(package: str, version: str, description: str, release_date: str) -> None:
    if not package.strip() or len(package) > 100:
        raise ValueError("包名必填且不超过 100 字")
    if not version.strip() or len(version) > 50:
        raise ValueError("版本必填且不超过 50 字")
    if len(description) > 500:
        raise ValueError("描述不能超过 500 字")
    if len(release_date) > 20:
        raise ValueError("上传日期格式无效")


def list_versions(query: str = "") -> list[dict[str, Any]]:
    """倒序列表；q 对包名/版本/描述大小写不敏感子串过滤。"""
    keyword = query.strip().casefold()
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT id,package,version,description,release_date,created_at "
            "FROM version_records ORDER BY id DESC")
        items = [dict(row) for row in rows]
    if not keyword:
        return items
    return [item for item in items if keyword in " ".join(
        str(item.get(field) or "") for field in ("package", "version", "description")).casefold()]


def get_version(version_id: int) -> dict[str, Any] | None:
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT id,package,version,description,release_date,created_at "
            "FROM version_records WHERE id=?", (version_id,)).fetchone()
        return dict(row) if row else None


def create_version(package: str, version: str, description: str, release_date: str) -> dict[str, Any]:
    check_fields(package, version, description, release_date)
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                "INSERT INTO version_records(package,version,description,release_date) VALUES (?,?,?,?)",
                (package.strip(), version.strip(), description.strip(), release_date.strip()))
            return {"id": int(cursor.lastrowid), "package": package.strip(), "version": version.strip()}


def update_version(version_id: int, package: str, version: str,
                   description: str, release_date: str) -> bool:
    check_fields(package, version, description, release_date)
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                "UPDATE version_records SET package=?,version=?,description=?,release_date=? WHERE id=?",
                (package.strip(), version.strip(), description.strip(), release_date.strip(), version_id))
            return cursor.rowcount > 0


def delete_version(version_id: int) -> bool:
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute("DELETE FROM version_records WHERE id=?", (version_id,))
            return cursor.rowcount > 0

"""便签待办持久化。"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from app import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_notes() -> None:
    config.ensure_dirs()
    with closing(_connect()) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""
        CREATE TABLE IF NOT EXISTS notes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          content TEXT NOT NULL,
          done INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))""")
        connection.commit()


def list_notes() -> list[dict[str, Any]]:
    """倒序列表（未完成在前，完成的沉底）。"""
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT id,content,done,created_at FROM notes ORDER BY done ASC, id DESC")
        return [dict(row) for row in rows]


def create_note(content: str) -> dict[str, Any]:
    text = content.strip()
    if not text or len(text) > 500:
        raise ValueError("待办内容必填且不超过 500 字")
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute("INSERT INTO notes(content) VALUES (?)", (text,))
            return {"id": int(cursor.lastrowid)}


def set_done(note_id: int, done: bool) -> int | None:
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute("UPDATE notes SET done=? WHERE id=?",
                                        (1 if done else 0, note_id))
            return (1 if done else 0) if cursor.rowcount else None


def delete_note(note_id: int) -> bool:
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute("DELETE FROM notes WHERE id=?", (note_id,))
            return cursor.rowcount > 0

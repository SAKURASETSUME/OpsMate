"""运维助手会话与消息持久化（SQLite，DDL 按施工文档 §4.4）。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Any

from app import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_assistant() -> None:
    """建 assistant_sessions / assistant_messages 表与索引。"""
    config.ensure_dirs()
    with closing(_connect()) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS assistant_sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS assistant_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id INTEGER NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        CREATE INDEX IF NOT EXISTS idx_asst_msg_session ON assistant_messages(session_id, id);
        """)
        connection.commit()


class SessionNotFound(ValueError):
    """传入的 session_id 不存在。"""


def list_sessions() -> list[dict[str, Any]]:
    """倒序会话列表。"""
    with closing(_connect()) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT id,title,updated_at FROM assistant_sessions ORDER BY updated_at DESC,id DESC")]


def get_messages(session_id: int) -> list[dict[str, Any]]:
    """按 id 升序返回会话全部消息；tool 行 content 为 JSON 轨迹字符串。"""
    with closing(_connect()) as connection:
        if connection.execute("SELECT 1 FROM assistant_sessions WHERE id=?", (session_id,)).fetchone() is None:
            raise SessionNotFound("会话不存在")
        return [dict(row) for row in connection.execute(
            "SELECT id,role,content FROM assistant_messages WHERE session_id=? ORDER BY id", (session_id,))]


def conversation_history(session_id: int) -> list[dict[str, str]]:
    """供模型使用的上下文：只取 user/assistant 正文，不含 tool 轨迹。"""
    return [{"role": row["role"], "content": row["content"]}
            for row in get_messages(session_id) if row["role"] in ("user", "assistant")]


def delete_session(session_id: int) -> bool:
    """删除会话与全部消息。"""
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute("DELETE FROM assistant_sessions WHERE id=?", (session_id,))
            connection.execute("DELETE FROM assistant_messages WHERE session_id=?", (session_id,))
            return cursor.rowcount > 0


def save_turn(session_id: int | None, message: str, steps: list[dict[str, Any]],
              answer: str, model: str) -> int:
    """成功一轮后原子写入：用户消息 + tool 轨迹行 + 助手回答，并刷新会话时间。

    session_id 为空时创建新会话（标题=首条用户消息截断 50 字）。
    """
    with closing(_connect()) as connection:
        with connection:
            if session_id is None:
                cursor = connection.execute(
                    "INSERT INTO assistant_sessions(title) VALUES (?)", (message.strip()[:50],))
                session_id = int(cursor.lastrowid)
            elif connection.execute("SELECT 1 FROM assistant_sessions WHERE id=?",
                                    (session_id,)).fetchone() is None:
                raise SessionNotFound("会话不存在")
            connection.execute(
                "INSERT INTO assistant_messages(session_id,role,content) VALUES (?,'user',?)",
                (session_id, message))
            for step in steps:
                connection.execute(
                    "INSERT INTO assistant_messages(session_id,role,content) VALUES (?,'tool',?)",
                    (session_id, json.dumps({
                        "tool": step.get("tool", ""),
                        "args": step.get("args", {}),
                        "result": str(step.get("result", ""))[:600],
                    }, ensure_ascii=False)))
            connection.execute(
                "INSERT INTO assistant_messages(session_id,role,content) VALUES (?,'assistant',?)",
                (session_id, answer))
            connection.execute(
                "UPDATE assistant_sessions SET updated_at=datetime('now','localtime') WHERE id=?",
                (session_id,))
    return session_id

"""运维助手会话、消息、附件、文件提案与工作目录持久化。"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from app import config

# 附件与文件提案（2026-10-30 用户授权的智能体能力扩展）
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES_PER_TURN = 5
TEXT_SUFFIXES = {
    ".txt", ".md", ".log", ".conf", ".cfg", ".ini", ".yaml", ".yml", ".json",
    ".properties", ".toml", ".csv", ".sh", ".bash", ".py", ".pl", ".rb", ".go",
    ".js", ".ts", ".java", ".sql", ".xml", ".html", ".css", ".env", ".service",
}
IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}
UNSAFE_NAME = re.compile(r"[^\w.\-\u4e00-\u9fff ]")


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
          workspace TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS assistant_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id INTEGER NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          summary TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        CREATE INDEX IF NOT EXISTS idx_asst_msg_session ON assistant_messages(session_id, id);
        CREATE TABLE IF NOT EXISTS assistant_attachments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id INTEGER,
          message_id INTEGER,
          name TEXT NOT NULL,
          mime TEXT NOT NULL,
          kind TEXT NOT NULL,
          size_bytes INTEGER NOT NULL,
          path TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS assistant_summaries (
          session_id INTEGER PRIMARY KEY,
          compressed_until INTEGER NOT NULL,
          summary TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        """)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(assistant_messages)")}
        if "summary" not in columns:
            connection.execute("ALTER TABLE assistant_messages ADD COLUMN summary TEXT")
        session_columns = {row[1] for row in connection.execute("PRAGMA table_info(assistant_sessions)")}
        if "workspace" not in session_columns:
            connection.execute("ALTER TABLE assistant_sessions ADD COLUMN workspace TEXT")
        connection.commit()


def classify_upload(name: str, mime: str) -> tuple[str, str]:
    """按扩展名/MIME 判定附件类型；返回 (kind, 错误说明)。kind ∈ text/image。"""
    lowered = name.lower()
    if mime in IMAGE_MIMES or lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
        return "image", ""
    if mime.startswith("text/") or lowered.endswith(tuple(TEXT_SUFFIXES)):
        return "text", ""
    return "", "仅支持文本/配置/代码文件与 PNG/JPG/GIF/WebP/BMP 图片"


def save_attachment(name: str, mime: str, kind: str, raw: bytes) -> dict[str, Any]:
    """附件落盘并登记元数据；文件名按 id 存储，原始名仅作元数据。"""
    config.ensure_dirs()
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                "INSERT INTO assistant_attachments(name,mime,kind,size_bytes,path) VALUES (?,?,?,?,?)",
                (name, mime, kind, len(raw), ""))
            file_id = int(cursor.lastrowid)
    path = config.ASSISTANT_FILES_DIR / str(file_id)
    path.write_bytes(raw)
    with closing(_connect()) as connection:
        with connection:
            connection.execute("UPDATE assistant_attachments SET path=? WHERE id=?",
                               (str(path), file_id))
    return {"id": file_id, "name": name, "mime": mime, "kind": kind, "size_bytes": len(raw)}


def get_attachment(file_id: int) -> dict[str, Any] | None:
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT id,name,mime,kind,size_bytes,path,session_id,message_id FROM assistant_attachments WHERE id=?",
            (file_id,)).fetchone()
        return dict(row) if row else None


def link_attachments(message_id: int, session_id: int, attachment_ids: list[int]) -> None:
    """保存成功轮后把附件归属到用户消息。"""
    if not attachment_ids:
        return
    with closing(_connect()) as connection:
        with connection:
            connection.executemany(
                "UPDATE assistant_attachments SET session_id=?,message_id=? WHERE id=? AND message_id IS NULL",
                [(session_id, message_id, file_id) for file_id in attachment_ids])


class SessionNotFound(ValueError):
    """传入的 session_id 不存在。"""


def list_sessions(workspace: str | None = None) -> list[dict[str, Any]]:
    """倒序会话列表；workspace 过滤：None=全部，__none__=未分组，其余=精确匹配。"""
    with closing(_connect()) as connection:
        if workspace is None:
            rows = connection.execute(
                "SELECT id,title,workspace,updated_at FROM assistant_sessions ORDER BY updated_at DESC,id DESC")
        elif workspace == "__none__":
            rows = connection.execute(
                "SELECT id,title,workspace,updated_at FROM assistant_sessions "
                "WHERE workspace IS NULL OR workspace='' ORDER BY updated_at DESC,id DESC")
        else:
            rows = connection.execute(
                "SELECT id,title,workspace,updated_at FROM assistant_sessions "
                "WHERE workspace=? ORDER BY updated_at DESC,id DESC", (workspace,))
        return [dict(row) for row in rows]


def get_messages(session_id: int) -> list[dict[str, Any]]:
    """按 id 升序返回会话全部消息；tool 行 content 为 JSON 轨迹字符串，
    user 行附带 attachments 元数据（不含正文，内容由文件接口按需读取）。"""
    with closing(_connect()) as connection:
        if connection.execute("SELECT 1 FROM assistant_sessions WHERE id=?", (session_id,)).fetchone() is None:
            raise SessionNotFound("会话不存在")
        messages = [dict(row) for row in connection.execute(
            "SELECT id,role,content,summary FROM assistant_messages WHERE session_id=? ORDER BY id", (session_id,))]
        by_message: dict[int, list[dict[str, Any]]] = {}
        for row in connection.execute(
                "SELECT id,message_id,name,mime,kind,size_bytes FROM assistant_attachments "
                "WHERE session_id=? AND message_id IS NOT NULL ORDER BY id", (session_id,)):
            by_message.setdefault(int(row["message_id"]), []).append(dict(row))
    for message in messages:
        message["attachments"] = by_message.get(int(message["id"]), [])
    return messages


def conversation_history(session_id: int) -> list[dict[str, str]]:
    """供模型使用的上下文：user/assistant 正文 + 附件文本块 + write_file 结果注记。"""
    history: list[dict[str, str]] = []
    for row in get_messages(session_id):
        role, content = row["role"], row["content"]
        if role == "user":
            blocks = []
            for attachment in row["attachments"]:
                if attachment["kind"] != "text":
                    blocks.append(f"\n\n[附件 {attachment['name']}（{attachment['mime']}，图片，本轮未重发）]")
                    continue
                record = get_attachment(int(attachment["id"])) or {}
                raw = ""
                path = record.get("path")
                if path:
                    try:
                        raw = open(path, encoding="utf-8", errors="replace").read()
                    except OSError:
                        raw = ""
                blocks.append(f"\n\n[附件 {attachment['name']}（{attachment['mime']}，"
                              f"{attachment['size_bytes']} 字节）]\n{raw[:2000]}")
            history.append({"role": "user", "content": content + "".join(blocks)})
        elif role == "assistant":
            history.append({"role": "assistant", "content": content})
        elif role == "tool":
            try:
                trace = json.loads(row["content"])
            except ValueError:
                continue
            if trace.get("tool") == "write_file" and "已写入" in str(trace.get("result", "")):
                history.append({"role": "user", "content": f"（系统注记：用户已确认，文件已写入 {trace['result'].split('已写入', 1)[1].strip()}）"})
    return history


# ---------------- 长会话滚动摘要（优化方案二） ----------------

def get_summary(session_id: int) -> dict[str, Any] | None:
    """读取已压缩摘要：{compressed_until, summary}，无则 None。"""
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT compressed_until, summary FROM assistant_summaries WHERE session_id=?",
            (session_id,)).fetchone()
    return {"compressed_until": row[0], "summary": row[1]} if row else None


def save_summary(session_id: int, compressed_until: int, summary: str) -> None:
    """保存/更新会话摘要（compressed_until = 已压缩进摘要的历史消息条数）。"""
    with closing(_connect()) as connection:
        with connection:
            connection.execute(
                "INSERT INTO assistant_summaries(session_id, compressed_until, summary, updated_at) "
                "VALUES (?,?,?,datetime('now','localtime')) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "compressed_until=excluded.compressed_until, summary=excluded.summary, "
                "updated_at=excluded.updated_at",
                (session_id, compressed_until, summary))


def delete_session(session_id: int) -> bool:
    """删除会话与全部消息。"""
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute("DELETE FROM assistant_sessions WHERE id=?", (session_id,))
            connection.execute("DELETE FROM assistant_messages WHERE session_id=?", (session_id,))
            connection.execute("DELETE FROM assistant_summaries WHERE session_id=?", (session_id,))
            return cursor.rowcount > 0


def save_turn(session_id: int | None, message: str, steps: list[dict[str, Any]],
              answer: str, model: str, attachment_ids: list[int] | None = None,
              workspace: str = "") -> int:
    """成功一轮后原子写入：用户消息 + tool 轨迹行 + 助手回答，并刷新会话时间。

    session_id 为空时创建新会话（标题=首条用户消息截断 50 字，归属 workspace）；
    附件随后归属该用户消息。
    """
    with closing(_connect()) as connection:
        with connection:
            if session_id is None:
                cursor = connection.execute(
                    "INSERT INTO assistant_sessions(title,workspace) VALUES (?,?)",
                    (message.strip()[:50], workspace or None))
                session_id = int(cursor.lastrowid)
            elif connection.execute("SELECT 1 FROM assistant_sessions WHERE id=?",
                                    (session_id,)).fetchone() is None:
                raise SessionNotFound("会话不存在")
            cursor = connection.execute(
                "INSERT INTO assistant_messages(session_id,role,content,summary) VALUES (?,'user',?,?)",
                (session_id, message,
                 message.strip()[:24] + ("…" if len(message.strip()) > 24 else "")))
            message_id = int(cursor.lastrowid)
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
    link_attachments(message_id, session_id, attachment_ids or [])
    return session_id


# ---------------- 文件提案（write_file，用户确认后写入） ----------------

def _proposal_row(connection: sqlite3.Connection, session_id: int, filename: str) -> sqlite3.Row | None:
    rows = connection.execute(
        "SELECT id, content FROM assistant_messages WHERE session_id=? AND role='tool' "
        "AND content LIKE '%write_file%' AND content LIKE '%等待用户确认%' ORDER BY id DESC",
        (session_id,)).fetchall()
    for row in rows:
        try:
            trace = json.loads(row["content"])
        except ValueError:
            continue
        if trace.get("tool") == "write_file" and trace.get("args", {}).get("filename") == filename:
            return row
    return None


def resolve_proposal(session_id: int, filename: str, accept: bool) -> str:
    """确认/取消最近的待确认 write_file 提案，返回结果说明（未找到待确认提案时报错）。"""
    with closing(_connect()) as connection:
        with connection:
            row = _proposal_row(connection, session_id, filename)
            if row is None:
                raise SessionNotFound("没有待确认的文件提案")
            original = connection.execute(
                "SELECT content FROM assistant_messages WHERE id=?", (row["id"],)).fetchone()["content"]
            trace = json.loads(original)
            outcome = "用户已取消，未写入" if not accept else "用户已确认，已写入"
            if accept:
                target = config.AGENT_FILES_DIR / filename
                temporary = target.with_name(target.name + ".tmp")
                temporary.write_text(trace["args"].get("content", ""), encoding="utf-8")
                temporary.replace(target)
                outcome += f" agent_files/{filename}"
            connection.execute("UPDATE assistant_messages SET content=? WHERE id=?",
                (json.dumps({**trace, "result": outcome[:600]}, ensure_ascii=False), row["id"]))
    return outcome


def sanitize_agent_filename(filename: str) -> str:
    """提案文件名只允许安全字符且不含路径分隔，防目录穿越。"""
    name = filename.strip()
    if not name or len(name) > 120 or "/" in name or "\\" in name or UNSAFE_NAME.search(name):
        raise ValueError("文件名仅支持中文/字母/数字/空格/点/下划线/连字符，且不能包含路径")
    return name


# ---------------- 工作目录授权（2026-10-30 用户授权：读写/生成/执行） ----------------

WORKSPACE_JSON = config.DATA_DIR / "agent_workspace.json"


def load_workspace_dirs() -> list[str]:
    """读取用户配置的工作目录列表（原样返回，不做存在性过滤）。"""
    try:
        data = json.loads(WORKSPACE_JSON.read_text(encoding="utf-8"))
        dirs = data.get("directories")
        return [str(item) for item in dirs if isinstance(item, str)] if isinstance(dirs, list) else []
    except (OSError, ValueError):
        return []


def save_workspace_dirs(directories: list[str]) -> None:
    """保存工作目录；被移除目录下的会话归入"未分组"，避免会话凭空消失。"""
    previous = load_workspace_dirs()
    config.ensure_dirs()
    temporary = WORKSPACE_JSON.with_name(WORKSPACE_JSON.name + ".tmp")
    temporary.write_text(json.dumps({"directories": directories}, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    temporary.replace(WORKSPACE_JSON)
    removed = [item for item in previous if item not in directories]
    if removed:
        with closing(_connect()) as connection:
            with connection:
                connection.executemany(
                    "UPDATE assistant_sessions SET workspace=NULL WHERE workspace=?",
                    [(item,) for item in removed])


def workspace_roots() -> list[str]:
    """已配置且实际存在的工作目录（规范化绝对路径）。"""
    roots = []
    for item in load_workspace_dirs():
        path = Path(item).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_dir():
            roots.append(str(resolved))
    return roots

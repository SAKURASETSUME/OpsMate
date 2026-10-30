"""SQLite 日志存储：批量导入、组合过滤与原行号导出。"""
from __future__ import annotations
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from app import config
from app.logs.rules import classify_level, guess_format, cluster_rows

MAX_BYTES = 50 * 1024 * 1024
LEVELS = ("ERROR", "WARN", "INFO", "DEBUG", "")


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """每次操作独立连接，用完关闭。"""
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_store() -> None:
    """按当前 Phase 的原始 DDL 建表。"""
    config.ensure_dirs()
    with connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, filename TEXT,
          size_bytes INTEGER NOT NULL, line_count INTEGER NOT NULL, format_guess TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS log_lines (
          log_id INTEGER NOT NULL, line_no INTEGER NOT NULL, level TEXT NOT NULL DEFAULT '',
          text TEXT NOT NULL, PRIMARY KEY(log_id,line_no));
        CREATE INDEX IF NOT EXISTS idx_lines_level ON log_lines(log_id,level);
        CREATE TABLE IF NOT EXISTS reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT, log_id INTEGER NOT NULL,
          kind TEXT NOT NULL DEFAULT 'llm', model TEXT, content TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        """)
        conn.commit()


def _counts(conn: sqlite3.Connection, log_id: int) -> dict[str, int]:
    counts = {level: 0 for level in LEVELS}
    for row in conn.execute("SELECT level,count(*) n FROM log_lines WHERE log_id=? GROUP BY level", (log_id,)):
        counts[row["level"]] = row["n"]
    return counts


def get_log(log_id: int) -> dict[str, Any] | None:
    """元信息与级别统计。"""
    with connection() as conn:
        row = conn.execute("SELECT * FROM logs WHERE id=?", (log_id,)).fetchone()
        return {**dict(row), "level_stats": _counts(conn, log_id)} if row else None


def list_logs() -> list[dict[str, Any]]:
    """倒序日志列表。"""
    with connection() as conn:
        return [{**dict(row), "level_stats": _counts(conn, row["id"])}
                for row in conn.execute("SELECT * FROM logs ORDER BY id DESC")]


def import_log(title: str, raw: bytes, filename: str | None = None) -> dict[str, Any]:
    """UTF-8 日志单事务导入，文件副本失败时回滚。"""
    if len(raw) > MAX_BYTES:
        raise OverflowError("单份日志不能超过 50MB，请先 split/grep 裁剪")
    text = raw.decode("utf-8-sig")
    if "\x00" in text:
        raise ValueError("不支持二进制日志，请上传 UTF-8 文本")
    lines = text.splitlines()
    if not lines:
        raise ValueError("日志内容不能为空")
    backup = None
    with connection() as conn:
        try:
            with conn:
                cursor = conn.execute("INSERT INTO logs(title,filename,size_bytes,line_count,format_guess) VALUES (?,?,?,?,?)",
                                      (title, filename, len(raw), len(lines), guess_format(lines)))
                log_id = int(cursor.lastrowid)
                for start in range(0, len(lines), 5000):
                    conn.executemany("INSERT INTO log_lines(log_id,line_no,level,text) VALUES (?,?,?,?)",
                        [(log_id, i + 1, classify_level(lines[i]), lines[i])
                         for i in range(start, min(start + 5000, len(lines)))])
                if filename is not None:
                    backup = config.LOGS_DIR / f"{log_id}.txt"
                    backup.write_bytes(raw)
        except Exception:
            if backup is not None:
                backup.unlink(missing_ok=True)
            raise
    result = get_log(log_id)
    assert result is not None
    return result


def _filters(log_id: int, level: str, q: str, regex: str) -> tuple[str, list[Any], re.Pattern | None]:
    clauses, params = ["log_id=?"], [log_id]
    if level:
        levels = ["" if item.strip().upper() == "UNKNOWN" else item.strip().upper() for item in level.split(",")]
        if any(item not in LEVELS for item in levels):
            raise ValueError("日志级别无效")
        clauses.append("level IN (" + ",".join("?" for _ in levels) + ")")
        params.extend(levels)
    if q:
        clauses.append("CONTAINS_TEXT(text,?)")
        params.append(q)
    return " AND ".join(clauses), params, re.compile(regex, re.I) if regex else None


def query_lines(log_id: int, level: str = "", q: str = "", regex: str = "",
                offset: int = 0, limit: int = 500, order: str = "asc") -> dict[str, Any]:
    """SQL 多级别与 Unicode 关键词过滤，正则取交集后分页。"""
    where, params, compiled = _filters(log_id, level, q, regex)
    direction = "DESC" if order == "desc" else "ASC"
    with connection() as conn:
        conn.create_function("CONTAINS_TEXT", 2, lambda text, term: term.casefold() in text.casefold())
        if compiled is None:
            total = conn.execute(f"SELECT count(*) FROM log_lines WHERE {where}", params).fetchone()[0]
            rows = conn.execute(f"SELECT line_no,level,text FROM log_lines WHERE {where} ORDER BY line_no {direction} LIMIT ? OFFSET ?", [*params, limit, offset])
            return {"total": total, "lines": [dict(row) for row in rows]}
        result, total = [], 0
        for row in conn.execute(f"SELECT line_no,level,text FROM log_lines WHERE {where} ORDER BY line_no {direction}", params):
            if compiled.search(row["text"]):
                if offset <= total < offset + limit:
                    result.append(dict(row))
                total += 1
        return {"total": total, "lines": result}


def export_lines(log_id: int, level: str = "", q: str = "", regex: str = "") -> Iterator[str]:
    """流式导出全部匹配行，带原行号。"""
    where, params, compiled = _filters(log_id, level, q, regex)
    with connection() as conn:
        conn.create_function("CONTAINS_TEXT", 2, lambda text, term: term.casefold() in text.casefold())
        for row in conn.execute(f"SELECT line_no,text FROM log_lines WHERE {where} ORDER BY line_no", params):
            if compiled is None or compiled.search(row["text"]):
                yield f"{row['line_no']}\t{row['text']}\n"


def delete_log(log_id: int) -> bool:
    """删除元数据/行/报告及原始副本。"""
    with connection() as conn:
        with conn:
            if conn.execute("SELECT 1 FROM logs WHERE id=?", (log_id,)).fetchone() is None:
                return False
            conn.execute("DELETE FROM log_lines WHERE log_id=?", (log_id,))
            conn.execute("DELETE FROM reports WHERE log_id=?", (log_id,))
            conn.execute("DELETE FROM logs WHERE id=?", (log_id,))
            (config.LOGS_DIR / f"{log_id}.txt").unlink(missing_ok=True)
    return True


def get_stats(log_id: int) -> dict[str, Any]:
    """扫描当前日志构建 L1 聚类，不改动原始行。"""
    metadata = get_log(log_id)
    if metadata is None:
        raise ValueError("日志不存在")
    with connection() as conn:
        clusters, time_range = cluster_rows(conn.execute("SELECT line_no,level,text FROM log_lines WHERE log_id=? ORDER BY line_no", (log_id,)))
    result = {"level_counts": metadata["level_stats"], "format_guess": metadata["format_guess"], "top_clusters": clusters}
    if time_range:
        result["time_range"] = time_range
    return result


def get_context(log_id: int, line_no: int, around: int = 10) -> dict[str, Any]:
    """返回当前行附近有界上下文。"""
    return query_lines(log_id, offset=max(0, line_no - around - 1), limit=around * 2 + 1)


def save_report(log_id: int, model: str, content: str) -> int:
    """仅保存完整报告，日志被删则拒绝孤立记录。"""
    with connection() as conn:
        with conn:
            if conn.execute("SELECT 1 FROM logs WHERE id=?", (log_id,)).fetchone() is None:
                raise ValueError("日志已删除，报告未保存")
            cursor = conn.execute("INSERT INTO reports(log_id,kind,model,content) VALUES (?,'llm',?,?)", (log_id, model, content))
            return int(cursor.lastrowid)


def list_reports(log_id: int) -> list[dict[str, Any]]:
    """倒序报告元信息。"""
    with connection() as conn:
        return [dict(row) for row in conn.execute("SELECT id,model,created_at FROM reports WHERE log_id=? ORDER BY id DESC", (log_id,))]


def get_report(log_id: int, report_id: int) -> dict[str, str] | None:
    """报告必须属于当前日志。"""
    with connection() as conn:
        row = conn.execute("SELECT content FROM reports WHERE log_id=? AND id=?", (log_id, report_id)).fetchone()
        return dict(row) if row else None

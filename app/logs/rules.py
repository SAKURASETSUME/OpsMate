"""本地日志级别与格式识别。"""
from __future__ import annotations
import re
import hashlib
from collections.abc import Iterable, Mapping
from typing import Any
from collections.abc import Sequence

LEVEL_PATTERN = re.compile(r"\b(ERROR|FATAL|CRITICAL|WARN(?:ING)?|INFO|DEBUG|TRACE)\b", re.I)


def classify_level(text: str) -> str:
    """识别显式级别，堆栈延续行保持未知。"""
    match = LEVEL_PATTERN.search(text)
    if not match:
        return ""
    level = match.group(1).upper()
    return {"FATAL": "ERROR", "CRITICAL": "ERROR", "WARNING": "WARN", "TRACE": "DEBUG"}.get(level, level)


def guess_format(lines: Sequence[str]) -> str:
    """按契约优先级采样前 200 行。"""
    sample = "\n".join(lines[:200])
    patterns = ((r'^\S+ \S+ \S+ \[.*\] "\w+ .*" \d{3} ', "nginx_access"),
                (r" \[(?:error|warn)\] ", "nginx_error"),
                (r"^\w{3} +\d+ \d{2}:\d{2}:\d{2} \S+ ", "syslog"),
                (r" \[main\]|java\.|Exception|ERROR", "java_app"),
                (r"zabbix_server|zabbix_agent", "known_service"))
    return next((name for pattern, name in patterns if re.search(pattern, sample, re.M)), "unknown")


def normalize_message(text: str) -> str:
    """归一化变量，预保护复合标识避免数字替换破坏识别。"""
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", text)
    text = re.sub(r"/[\w./-]+", "\ue002", text)
    text = re.sub(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b", "\ue000", text)
    text = re.sub(r"\b(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{6,}\b", "\ue001", text)
    text = re.sub(r"\d+(?:\.\d+)?", "<num>", text)
    text = text.replace("\ue001", "<hex>").replace("\ue000", "<id>")
    text = re.sub(r"'[^']*'|\"[^\"]*\"", "<str>", text)
    return re.sub(r"\s+", " ", text.replace("\ue002", "<path>")).strip()


def cluster_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict], list[str] | None]:
    """流式合并堆栈，按归一化 sha1 聚类，保留 ERROR 与重复 WARN。"""
    groups: dict[str, dict] = {}
    current: dict | None = None
    first_ts = last_ts = None

    def flush() -> None:
        if current is None or current["level"] not in {"ERROR", "WARN"}:
            return
        normalized = normalize_message(current["text"])
        key = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
        group = groups.get(key)
        if group is None:
            group = {"pattern": normalized[:80], "count": 0, "first_no": current["first_no"], "last_no": current["last_no"], "sample": current["text"][:300], "level": current["level"]}
            groups[key] = group
        group["count"] += 1
        group["last_no"] = current["last_no"]
        if current["level"] == "ERROR":
            group["level"] = "ERROR"

    for row in rows:
        text = row["text"]
        timestamp = re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?", text)
        if timestamp:
            first_ts = first_ts or timestamp.group()
            last_ts = timestamp.group()
        continuation = bool(re.match(r"^(?:\s+|at |Caused by:|\.\.\.\s*\d+ more)", text))
        if continuation and current is not None:
            current["text"] += "\n" + text
            current["last_no"] = row["line_no"]
        else:
            flush()
            current = {"level": row["level"], "text": text, "first_no": row["line_no"], "last_no": row["line_no"]}
    flush()
    kept = [g for g in groups.values() if g["level"] == "ERROR" or g["count"] >= 2]
    kept.sort(key=lambda group: (-group["count"], group["first_no"]))
    return [{k: v for k, v in g.items() if k != "level"} for g in kept[:20]], [first_ts, last_ts] if first_ts else None

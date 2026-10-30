"""本地日志级别与格式识别。"""
from __future__ import annotations
import re
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

"""只读工具白名单；工具执行不联网、不写库、不执行脚本。"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from app import config
from app.commands.service import get_command_index
from app.kb.service import get_kb

TOOL_DESCRIPTIONS = {
    "search_commands": "检索本地命令文档，args={q:字符串,limit:1到5}，返回简介及正文摘录",
    "search_kb": "检索本地配置知识，args={q:字符串,software:可选软件名,limit:1到5}",
    "search_history": "FTS5 检索既往脚本，args={q:简短关键词,limit:1到5}；相似任务先查历史",
}


def search_history(q: str, limit: int = 5) -> list[dict[str, Any]]:
    """只读 FTS 查询，关键词作为字面量转义以免注入 FTS 运算符。"""
    if not config.DB_PATH.exists() or not q.strip():
        return []
    expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in q.split()[:8])
    with closing(sqlite3.connect(config.DB_PATH.resolve().as_uri() + "?mode=ro", uri=True,
                                 check_same_thread=False)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT h.id,h.requirement,substr(h.script,1,3000) AS script,h.model "
            "FROM codegen_history_fts f JOIN codegen_history h ON h.id=f.rowid "
            "WHERE codegen_history_fts MATCH ? ORDER BY rank LIMIT ?", (expression, limit))
        return [dict(row) for row in rows]


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """仅分派白名单工具，未知工具/参数错误转为结构化结果。"""
    if name not in TOOL_DESCRIPTIONS:
        return {"ok": False, "error": "工具不存在或未开放"}
    try:
        q = args.get("q", "")
        if not isinstance(q, str) or not q.strip() or len(q) > 500:
            return {"ok": False, "error": "q 必须是 1–500 字文本"}
        limit = max(1, min(int(args.get("limit", 5)), 5))
        if name == "search_commands":
            index = get_command_index()
            items, _ = index.search(q, limit)
            result = [{**item, "markdown": (index.get(item["name"]) or {}).get("markdown", "")[:2500]}
                      for item in items]
        elif name == "search_kb":
            result = get_kb().search(q, args.get("software"))[:limit]
        else:
            result = search_history(q, limit)
        return {"ok": True, "result": result}
    except (ValueError, TypeError, sqlite3.Error):
        return {"ok": False, "error": "工具参数无效或知识数据暂不可用"}

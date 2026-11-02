"""只读工具白名单 + 工作目录/联网工具（用户授权范围）；工具执行仅联网查询，其余本地受控。"""
from __future__ import annotations

import html as html_module
import os
import re
import subprocess
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app import config
from app.assistant import service as assistant_service
from app.commands.service import get_command_index
from app.kb import workbench
from app.kb.service import get_kb
from app.logs import store as log_store

TOOL_DESCRIPTIONS = {
    "search_commands": "检索本地命令文档，args={q:字符串,limit:1到5}，返回简介及正文摘录",
    "search_kb": "检索本地配置知识，args={q:字符串,software:可选软件名,limit:1到5}",
    "search_history": "FTS5 检索既往脚本，args={q:简短关键词,limit:1到5}；相似任务先查历史",
    "filter_log": "只读筛选当前日志，args={log_id,q可选,level可选,regex可选,limit:1到50}，返回行号和有界片段",
    "get_stats": "只读当前日志的级别与聚类统计，args={log_id}",
    "get_context": "只读当前日志行附近上下文，args={log_id,line_no,around:0到10}",
    "read_user_config": "读取用户显式开启共享的配置原文，args={name:配置名称}；未共享或不存在时返回失败",
    "write_file": "提交本地文件生成/修改提案，args={filename:不含路径的文件名, content:完整文件内容, note:一句话用途}；提案需用户在界面确认后才写入 agent_files/ 目录；用户已设置工作目录时应优先用 write_workspace_file",
    "list_dir": "列出工作目录内容，args={path:工作目录内相对路径，留空列根}；返回名称/类型/大小",
    "read_workspace_file": "读取工作目录内文件文本，args={path}",
    "write_workspace_file": "写入/生成工作目录内文件（用户已授权，无需确认），args={path,content}",
    "run_command": "在工作目录执行系统命令，args={command,timeout:秒,可选默认30}；返回返回码与截断输出；执行前评估影响并在回答中说明",
    "web_search": "联网搜索（Bing），args={q}；返回标题/链接/摘要",
    "web_fetch": "抓取网页正文文本，args={url}（http/https，禁止内网地址）",
}

WORKSPACE_TOOLS = ("list_dir", "read_workspace_file", "write_workspace_file", "run_command")
WEB_TOOLS = ("web_search", "web_fetch")
MAX_WS_READ = 200_000
MAX_WS_WRITE = 1_000_000
MAX_CMD_OUTPUT = 4_000
PRIVATE_HOST_PREFIXES = ("127.", "10.", "192.168.", "169.254.", "0.0.0.0")
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _resolve_in_workspace(path_text: str, *, must_exist: bool = True) -> Path | None:
    """把路径解析到某个已授权工作目录内；越界或不存在返回 None。"""
    roots = assistant_service.workspace_roots()
    if not roots:
        return None
    raw = Path(str(path_text or "").strip())
    for root in roots:
        candidate = raw if raw.is_absolute() else (Path(root) / raw)
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        root_norm = os.path.normcase(str(root))
        resolved_norm = os.path.normcase(str(resolved))
        if resolved_norm != root_norm and not resolved_norm.startswith(root_norm + os.sep):
            continue
        if must_exist and not resolved.exists():
            continue
        return resolved
    return None


def _workspace_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    roots = assistant_service.workspace_roots()
    if not roots:
        return {"ok": False, "error": "用户未设置工作目录，请在运维助手中添加后再使用文件/命令工具"}
    if name == "list_dir":
        target = _resolve_in_workspace(str(args.get("path", "")), must_exist=False)
        if target is None or not target.is_dir():
            return {"ok": False, "error": "目录不存在或不在工作目录范围内"}
        entries = []
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[:300]:
            entries.append({"name": child.name, "type": "dir" if child.is_dir() else "file",
                            "size": child.stat().st_size if child.is_file() else None})
        return {"ok": True, "result": {"path": str(target), "entries": entries}}
    if name == "read_workspace_file":
        target = _resolve_in_workspace(str(args.get("path", "")))
        if target is None or not target.is_file():
            return {"ok": False, "error": "文件不存在或不在工作目录范围内"}
        if target.stat().st_size > MAX_WS_READ:
            return {"ok": False, "error": f"文件超过 {MAX_WS_READ // 1000}KB 读取上限"}
        text = target.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "result": {"path": str(target), "content": text}}
    if name == "write_workspace_file":
        content = args.get("content")
        if not isinstance(content, str) or not content or len(content) > MAX_WS_WRITE:
            return {"ok": False, "error": "content 必须是非空文本且不超过 1MB"}
        target = _resolve_in_workspace(str(args.get("path", "")), must_exist=False)
        if target is None:
            return {"ok": False, "error": "目标路径不在工作目录范围内（含子目录自动创建）"}
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)
        return {"ok": True, "result": {"path": str(target), "bytes": len(content.encode("utf-8"))}}
    if name == "run_command":
        command = str(args.get("command", "")).strip()
        if not command or len(command) > 2000:
            return {"ok": False, "error": "command 必须是 1-2000 字"}
        try:
            timeout = max(5, min(int(args.get("timeout", 30)), 120))
        except (TypeError, ValueError):
            timeout = 30
        cwd = _resolve_in_workspace(str(args.get("cwd", "")), must_exist=False) if args.get("cwd") else Path(roots[0])
        if cwd is None or not cwd.is_dir():
            return {"ok": False, "error": "cwd 无效或不在工作目录范围内"}
        try:
            proc = subprocess.run(command, shell=True, cwd=str(cwd), capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"命令超过 {timeout} 秒未完成，已终止"}
        except OSError as exc:
            return {"ok": False, "error": f"命令启动失败：{exc}"}
        def _decode(raw: bytes) -> str:
            for encoding in ("utf-8", "gbk"):
                try:
                    return raw.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")
        return {"ok": True, "result": {
            "command": command, "cwd": str(cwd), "returncode": proc.returncode,
            "stdout": _decode(proc.stdout)[:MAX_CMD_OUTPUT],
            "stderr": _decode(proc.stderr)[:2000]}}
    return {"ok": False, "error": "未知工作目录工具"}


def _strip_html(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _assert_public_http_url(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "URL 无效"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "仅支持 http/https URL"
    host = parts.hostname.lower()
    if host == "localhost" or host.startswith(PRIVATE_HOST_PREFIXES) or host.startswith("172."):
        return "禁止访问内网/本机地址"
    return None


def _web_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "web_search":
        query = str(args.get("q", "")).strip()
        if not query or len(query) > 300:
            return {"ok": False, "error": "q 必须是 1-300 字"}
        response = httpx.get("https://www.bing.com/search", params={"q": query},
                             headers={"User-Agent": BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                             timeout=15, follow_redirects=True)
        results = []
        for block in re.findall(r'<li class="b_algo".*?</li>', response.text, re.S)[:8]:
            hit = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
            if not hit:
                continue
            snippet = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
            results.append({"title": _strip_html(hit.group(2))[:120], "url": hit.group(1),
                            "snippet": _strip_html(snippet.group(1))[:200] if snippet else ""})
            if len(results) >= 5:
                break
        if not results:
            return {"ok": True, "result": [], "note": "搜索结果为空，可改用 web_fetch 访问 "
                    "https://www.bing.com/search?q=<关键词> 自行提取"}
        return {"ok": True, "result": results}
    url = str(args.get("url", "")).strip()
    blocked = _assert_public_http_url(url)
    if blocked:
        return {"ok": False, "error": blocked}
    response = httpx.get(url, headers={"User-Agent": BROWSER_UA}, timeout=15, follow_redirects=True)
    content_type = response.headers.get("content-type", "")
    if response.status_code >= 400:
        return {"ok": False, "error": f"HTTP {response.status_code}"}
    if not any(kind in content_type for kind in ("text/", "json", "xml")):
        return {"ok": False, "error": f"不支持的 content-type：{content_type}"}
    text = _strip_html(response.text)
    return {"ok": True, "result": {"url": url, "content": text[:8000], "truncated": len(text) > 8000}}


def guard_unconfirmable(name: str) -> dict[str, Any] | None:
    """需要用户确认/禁止直接执行的工具在此拦截（引擎提案路径之外的第二道防线）。"""
    if name == "write_file":
        return {"ok": False, "error": "write_file 需要用户确认，不能直接执行"}
    return None


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


def execute_tool(name: str, args: dict[str, Any], *, scope_log_id: int | None = None) -> dict[str, Any]:
    """仅分派白名单工具，未知工具/参数错误转为结构化结果。"""
    if name not in TOOL_DESCRIPTIONS:
        return {"ok": False, "error": "工具不存在或未开放"}
    blocked = guard_unconfirmable(name)
    if blocked is not None:
        return blocked
    try:
        if name in WORKSPACE_TOOLS:
            return _workspace_tool(name, args)
        if name in WEB_TOOLS:
            return _web_tool(name, args)
        if name in {"filter_log", "get_stats", "get_context"}:
            if scope_log_id is None or int(args.get("log_id", -1)) != scope_log_id:
                return {"ok": False, "error": "未授权读取该日志，仅允许当前日志"}
            if log_store.get_log(scope_log_id) is None:
                return {"ok": False, "error": "日志不存在"}
            if name == "get_stats":
                result = log_store.get_stats(scope_log_id)
            elif name == "get_context":
                line_no = max(1, int(args.get("line_no", 1)))
                around = max(0, min(int(args.get("around", 10)), 10))
                result = log_store.get_context(scope_log_id, line_no, around)
            else:
                result = log_store.query_lines(scope_log_id, str(args.get("level", "")), str(args.get("q", "")),
                    str(args.get("regex", "")), limit=max(1, min(int(args.get("limit", 50)), 50)))
            if "lines" in result:
                result["lines"] = [{**row, "text": row["text"][:600]} for row in result["lines"]]
            return {"ok": True, "result": result}
        if name == "read_user_config":
            config_name = str(args.get("name", "")).strip()
            if not config_name or len(config_name) > 80:
                return {"ok": False, "error": "配置不存在或未共享"}
            return workbench.read_shared_config(config_name)
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
    except (ValueError, TypeError, sqlite3.Error, re.error):
        return {"ok": False, "error": "工具参数无效或知识数据暂不可用"}
    except httpx.HTTPError:
        return {"ok": False, "error": "网络请求失败；请检查网络或换一个来源"}

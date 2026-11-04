"""MCP（Model Context Protocol）客户端：用户自添加服务器，智能体动态调用其工具。

零新依赖：stdio 传输 = subprocess + 换行分隔 JSON-RPC；HTTP 传输 = httpx。
服务器配置存 data/mcp_servers.json；工具以 mcp__<服务器名>__<工具名> 注入智能体。
"""
from __future__ import annotations

import json
import subprocess
import threading
from queue import Empty, Queue
from typing import Any

import httpx

from app import config

MCP_JSON = config.DATA_DIR / "mcp_servers.json"
PROTOCOL_VERSION = "2024-11-05"
CALL_TIMEOUT = 120

_servers_lock = threading.Lock()
_stdio_procs: dict[str, "_StdioSession"] = {}


def load_servers() -> list[dict[str, Any]]:
    try:
        data = json.loads(MCP_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_servers(servers: list[dict[str, Any]]) -> None:
    MCP_JSON.parent.mkdir(parents=True, exist_ok=True)
    MCP_JSON.write_text(json.dumps(servers, ensure_ascii=False, indent=2), encoding="utf-8")
    with _servers_lock:
        for sid, session in list(_stdio_procs.items()):
            if sid not in {str(item.get("id")) for item in servers}:
                session.close()
                _stdio_procs.pop(sid, None)


class _StdioSession:
    """与一个 stdio MCP 服务器进程的会话（换行 JSON-RPC，读线程 + 队列做超时）。"""

    def __init__(self, command: list[str]) -> None:
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", shell=False)
        self._queue: Queue[str] = Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        self._id = 0

    def _pump(self) -> None:
        try:
            for line in self.proc.stdout:  # 进程退出后迭代结束
                if line.strip():
                    self._queue.put(line)
        except OSError:
            pass

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        try:
            line = self._queue.get(timeout=30)
        except Empty:
            raise RuntimeError(f"MCP 请求超时：{method}") from None
        reply = json.loads(line)
        if reply.get("id") != self._id:  # 乱序/通知行：再等一条
            line = self._queue.get(timeout=30)
            reply = json.loads(line)
        if "error" in reply:
            raise RuntimeError(f"MCP 错误：{reply['error']}")
        return reply.get("result", {})

    def notify(self, method: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        try:
            self.proc.kill()
        except OSError:
            pass


def _session_for(server: dict[str, Any]) -> _StdioSession:
    sid = str(server["id"])
    with _servers_lock:
        session = _stdio_procs.get(sid)
        if session is not None and session.alive():
            return session
        command = [str(item) for item in server.get("command", [])]
        session = _StdioSession(command)
        session.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "OpsMate", "version": "1.0.0"}})
        session.notify("notifications/initialized")
        _stdio_procs[sid] = session
        return session


def _http_rpc(server: dict[str, Any], method: str, params: dict[str, Any] | None = None,
              session_id: str | None = None) -> tuple[dict[str, Any], str | None]:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    response = httpx.post(str(server["url"]), json=payload, headers=headers, timeout=CALL_TIMEOUT)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}")
    new_session = response.headers.get("Mcp-Session-Id", session_id)
    body = response.text
    if body.lstrip().startswith("event:") or "data:" in body[:200]:
        for line in body.splitlines():
            if line.startswith("data:"):
                body = line[5:].strip()
                break
    reply = json.loads(body)
    if "error" in reply:
        raise RuntimeError(f"MCP 错误：{reply['error']}")
    return reply.get("result", {}), new_session


def list_tools(server: dict[str, Any]) -> list[dict[str, Any]]:
    """返回该服务器暴露的工具清单 [{name, description}]；连接失败抛 RuntimeError。"""
    if server.get("transport") == "http":
        result, session_id = _http_rpc(server, "initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "OpsMate", "version": "1.0.0"}})
        del result
        result, _ = _http_rpc(server, "tools/list", {}, session_id=session_id)
        return result.get("tools", [])
    session = _session_for(server)
    return session.request("tools/list", {}).get("tools", [])


def registry_tools() -> dict[str, str]:
    """全部启用服务器的工具 → 智能体工具注册表（mcp__<name>__<tool> → 描述）。"""
    registry: dict[str, str] = {}
    for server in load_servers():
        if not server.get("enabled", True):
            continue
        prefix = f"mcp__{re_slug(str(server.get('name', 'srv')))}__"
        try:
            tools = list_tools(server)
        except (RuntimeError, OSError, ValueError):
            continue  # 单个服务器不可用不影响其余
        for tool in tools:
            tool_name = str(tool.get("name", "")).strip()
            if tool_name:
                registry[prefix + tool_name] = (
                    f"[MCP:{server.get('name')}] {str(tool.get('description') or tool_name)[:160]}")
    return registry


def re_slug(text: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9_]", "-", text)[:24] or "srv"


def call_mcp_tool(qualified: str, args: dict[str, Any]) -> dict[str, Any]:
    """执行 mcp__<服务器>__<工具> 调用，返回统一 {ok, result/error} 结构。"""
    parts = qualified.split("__", 2)
    if len(parts) != 3:
        return {"ok": False, "error": f"非法 MCP 工具名：{qualified}"}
    _, server_slug, tool_name = parts
    server = next((item for item in load_servers()
                   if item.get("enabled", True) and re_slug(str(item.get("name", ""))) == server_slug), None)
    if server is None:
        return {"ok": False, "error": f"MCP 服务器 {server_slug} 不存在或已停用"}
    try:
        if server.get("transport") == "http":
            _, session_id = _http_rpc(server, "initialize", {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "OpsMate", "version": "1.0.0"}})
            result, _ = _http_rpc(server, "tools/call",
                                  {"name": tool_name, "arguments": args}, session_id=session_id)
        else:
            session = _session_for(server)
            result = session.request("tools/call", {"name": tool_name, "arguments": args})
    except (RuntimeError, OSError, ValueError, httpx.HTTPError) as exc:
        return {"ok": False, "error": f"MCP 调用失败：{exc}"}
    if result.get("isError"):
        texts = [item.get("text", "") for item in result.get("content", []) if isinstance(item, dict)]
        return {"ok": False, "error": "；".join(t for t in texts if t)[:300] or "MCP 工具返回错误"}
    texts = [item.get("text", "") for item in result.get("content", []) if isinstance(item, dict)]
    joined = "\n".join(t for t in texts if t)
    return {"ok": True, "result": joined[:8000] if joined else "(空结果)"}

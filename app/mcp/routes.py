"""MCP 服务器管理路由：CRUD + 连接测试（工具清单预览）。"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent import mcp

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class ServerBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    transport: str = Field(pattern="^(stdio|http)$")
    command: list[str] = Field(default_factory=list, max_length=20)
    url: str = Field(default="", max_length=500)
    enabled: bool = True


def _validate(server: ServerBody) -> None:
    if server.transport == "stdio" and (not server.command
                                        or any(not str(item).strip() for item in server.command)):
        raise HTTPException(status_code=400, detail="stdio 服务器需提供 command 命令行数组")
    if server.transport == "http" and not server.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="http 服务器需提供 http(s) url")


@router.get("")
def list_servers() -> dict[str, Any]:
    """MCP 服务器列表（不含敏感 env，仅回传配置概要）。"""
    items = []
    for server in mcp.load_servers():
        items.append({"id": server.get("id"), "name": server.get("name"),
                      "transport": server.get("transport"),
                      "command": server.get("command", []),
                      "url": server.get("url", ""), "enabled": server.get("enabled", True)})
    return {"items": items}


@router.post("")
def add_server(body: ServerBody) -> dict[str, Any]:
    _validate(body)
    servers = mcp.load_servers()
    if any(item.get("name") == body.name for item in servers):
        raise HTTPException(status_code=400, detail=f"服务器 {body.name} 已存在")
    record = {"id": uuid.uuid4().hex[:12], "name": body.name, "transport": body.transport,
              "command": [str(item) for item in body.command], "url": body.url,
              "enabled": body.enabled}
    servers.append(record)
    mcp.save_servers(servers)
    return {"ok": True, "id": record["id"]}


@router.put("/{server_id}")
def update_server(server_id: str, body: ServerBody) -> dict[str, Any]:
    _validate(body)
    servers = mcp.load_servers()
    for server in servers:
        if server.get("id") == server_id:
            server.update({"name": body.name, "transport": body.transport,
                           "command": [str(item) for item in body.command],
                           "url": body.url, "enabled": body.enabled})
            mcp.save_servers(servers)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="服务器不存在")


@router.delete("/{server_id}")
def delete_server(server_id: str) -> dict[str, Any]:
    servers = mcp.load_servers()
    remaining = [item for item in servers if item.get("id") != server_id]
    if len(remaining) == len(servers):
        raise HTTPException(status_code=404, detail="服务器不存在")
    mcp.save_servers(remaining)
    return {"ok": True}


@router.post("/{server_id}/test")
def test_server(server_id: str) -> dict[str, Any]:
    """连接测试：返回该服务器暴露的工具清单。"""
    server = next((item for item in mcp.load_servers() if item.get("id") == server_id), None)
    if server is None:
        raise HTTPException(status_code=404, detail="服务器不存在")
    try:
        tools = mcp.list_tools(server)
    except (RuntimeError, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)[:300]}
    return {"ok": True, "tools": [{"name": tool.get("name"),
                                    "description": str(tool.get("description") or "")[:160]}
                                   for tool in tools]}

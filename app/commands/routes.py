"""指令速查 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.commands.service import get_command_index

router = APIRouter(prefix="/api/commands", tags=["commands"])


@router.get("")
def list_commands(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=2000),
) -> dict[str, object]:
    """搜索命令；空关键词返回字母序列表。"""
    items, total = get_command_index().search(q, limit)
    return {"items": items, "total": total}


@router.get("/{name}")
def get_command(name: str) -> dict[str, str]:
    """返回单个命令的标题与 markdown 正文。"""
    command = get_command_index().get(name)
    if command is None:
        raise HTTPException(status_code=404, detail="命令不存在")
    return command

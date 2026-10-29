"""配置速查 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.kb.service import get_kb

router = APIRouter(prefix="/api/kb", tags=["kb"])


@router.get("")
def list_software() -> dict[str, object]:
    """软件列表与 cli/conf 条目计数。"""
    return {"items": get_kb().summary()}


@router.get("/search")
def search_kb(
    q: str = Query(default=""),
    software: str | None = Query(default=None),
) -> dict[str, object]:
    """跨软件搜索条目；q 大小写不敏感子串，空 q 返回空列表。

    注意：本路由必须先于 /api/kb/{software} 注册（FastAPI 按注册顺序匹配）。
    """
    return {"items": get_kb().search(q, software)}


@router.get("/{software}")
def get_software(software: str) -> dict:
    """返回单个软件的完整知识库解析结果。"""
    data = get_kb().get(software)
    if data is None:
        raise HTTPException(status_code=404, detail="软件不存在")
    return data

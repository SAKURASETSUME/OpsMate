"""配置速查 API 路由（含 /api/kb/workbench/* 我的配置工坊）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.kb import workbench
from app.kb.service import get_kb

router = APIRouter(prefix="/api/kb", tags=["kb"])


def _check_format(value: str) -> str:
    if value not in workbench.FORMATS:
        raise ValueError("格式仅支持 " + "/".join(workbench.FORMATS))
    return value


class ConfigBody(BaseModel):
    """配置创建/更新入参；精确的 2MB 字节校验在服务层完成。"""

    name: str = Field(min_length=1, max_length=80)
    format: str
    content: str = Field(max_length=3_000_000)

    @field_validator("format")
    @classmethod
    def check_format(cls, value: str) -> str:
        return _check_format(value)


class ShareBody(BaseModel):
    shared: bool


class ValidateBody(BaseModel):
    """静态校验入参，不落库。"""

    format: str
    content: str = Field(max_length=3_000_000)

    @field_validator("format")
    @classmethod
    def check_format(cls, value: str) -> str:
        return _check_format(value)


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


@router.get("/workbench/configs")
def list_configs() -> dict[str, object]:
    """我的配置列表（摘要，不含正文）。"""
    return {"items": workbench.list_configs()}


@router.post("/workbench/configs")
def create_config(body: ConfigBody) -> dict[str, object]:
    """保存新配置；内容超过 2MB 返回 413。"""
    try:
        return workbench.create_config(body.name, body.format, body.content)
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/workbench/configs/{config_id}")
def get_config(config_id: int) -> dict[str, object]:
    """单条完整记录，供本地编辑回看。"""
    item = workbench.get_config(config_id)
    if item is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    return item


@router.put("/workbench/configs/{config_id}")
def update_config(config_id: int, body: ConfigBody) -> dict[str, object]:
    try:
        updated = workbench.update_config(config_id, body.name, body.format, body.content)
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if not updated:
        raise HTTPException(status_code=404, detail="配置不存在")
    return {"ok": True}


@router.delete("/workbench/configs/{config_id}")
def delete_config(config_id: int) -> dict[str, object]:
    if not workbench.delete_config(config_id):
        raise HTTPException(status_code=404, detail="配置不存在")
    return {"ok": True}


@router.put("/workbench/configs/{config_id}/share")
def share_config(config_id: int, body: ShareBody) -> dict[str, object]:
    """显式共享开关；关闭立即生效。"""
    shared = workbench.set_shared(config_id, body.shared)
    if shared is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    return {"ok": True, "shared": shared}


@router.post("/workbench/validate")
def validate_config(body: ValidateBody) -> dict[str, object]:
    """静态校验，不落库。"""
    return workbench.validate_config(body.format, body.content)


@router.get("/{software}")
def get_software(software: str) -> dict:
    """返回单个软件的完整知识库解析结果。"""
    data = get_kb().get(software)
    if data is None:
        raise HTTPException(status_code=404, detail="软件不存在")
    return data

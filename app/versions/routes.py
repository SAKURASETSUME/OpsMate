"""版本管理 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.versions import service

router = APIRouter(prefix="/api/versions", tags=["versions"])


class VersionBody(BaseModel):
    package: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=500)
    release_date: str = Field(default="", max_length=20)


@router.get("")
def list_items(q: str = Query(default="")) -> dict[str, Any]:
    service.init_versions()
    return {"items": service.list_versions(q)}


@router.post("")
def create_item(body: VersionBody) -> dict[str, Any]:
    service.init_versions()
    try:
        return service.create_version(body.package, body.version, body.description, body.release_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.put("/{version_id}")
def update_item(version_id: int, body: VersionBody) -> dict[str, Any]:
    service.init_versions()
    try:
        if not service.update_version(version_id, body.package, body.version,
                                      body.description, body.release_date):
            raise HTTPException(status_code=404, detail="版本记录不存在")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"ok": True}


@router.delete("/{version_id}")
def delete_item(version_id: int) -> dict[str, Any]:
    service.init_versions()
    if not service.delete_version(version_id):
        raise HTTPException(status_code=404, detail="版本记录不存在")
    return {"ok": True}

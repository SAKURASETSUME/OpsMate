"""日志中心基础 API：所有日志处理仅本机完成。"""
from __future__ import annotations
import re
from typing import Any, Literal
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile
from app.logs import store
from app.logs.analyze import analysis_events
from app.llm.routes import effective_settings
from pydantic import BaseModel, Field
import json

router = APIRouter(prefix="/api/logs", tags=["logs"])


def require_log(log_id: int) -> dict[str, Any]:
    """不存在的日志统一返回 404。"""
    result = store.get_log(log_id)
    if result is None:
        raise HTTPException(404, "日志不存在")
    return result


def check_filters(level: str, regex: str) -> None:
    """在导出流响应发出前验证过滤参数。"""
    try:
        store._filters(0, level, "", regex)
    except re.error:
        raise HTTPException(400, "正则表达式无效") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("")
async def create_log(request: Request) -> dict[str, Any]:
    """multipart file 或 JSON title/content，统一限制 50MiB。"""
    media_type = request.headers.get("content-type", "").lower()
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > store.MAX_BYTES + 1024 * 1024:
        raise HTTPException(413, "单份日志不能超过 50MB，请先 split/grep 裁剪")
    filename = None
    if media_type.startswith("multipart/form-data"):
        async with request.form(max_part_size=store.MAX_BYTES) as form:
            upload = form.get("file")
            if not isinstance(upload, UploadFile):
                raise HTTPException(400, "请选择日志文件")
            filename = (upload.filename or "log.txt").replace("\\", "/").split("/")[-1][:255]
            raw = await upload.read(store.MAX_BYTES + 1)
            title = str(form.get("title") or filename).strip()
    elif media_type.startswith("application/json"):
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(400, "JSON 格式无效") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), str) or not isinstance(payload.get("title"), str):
            raise HTTPException(400, "粘贴日志需提供 title 和 content 文本")
        title, raw = payload["title"].strip(), payload["content"].encode("utf-8")
    else:
        raise HTTPException(415, "请使用文件上传或 JSON 粘贴日志")
    if not title or len(title) > 200:
        raise HTTPException(400, "日志标题必填且不能超过 200 字")
    try:
        return await run_in_threadpool(store.import_log, title, raw, filename)
    except OverflowError as exc:
        raise HTTPException(413, str(exc)) from None
    except UnicodeDecodeError:
        raise HTTPException(400, "日志必须是 UTF-8 文本，请转换编码后上传") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("")
def list_logs() -> dict[str, Any]:
    """倒序日志列表。"""
    return {"items": store.list_logs()}


@router.get("/{log_id}")
def get_log(log_id: int) -> dict[str, Any]:
    return require_log(log_id)


@router.get("/{log_id}/lines")
def lines(log_id: int, level: str = "", q: str = "", regex: str = "",
          offset: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000),
          order: Literal["asc", "desc"] = "asc") -> dict[str, Any]:
    require_log(log_id)
    check_filters(level, regex)
    return store.query_lines(log_id, level, q, regex, offset, limit, order)


@router.get("/{log_id}/stats")
def stats(log_id: int) -> dict[str, Any]:
    require_log(log_id)
    return store.get_stats(log_id)


@router.get("/{log_id}/export")
def export(log_id: int, level: str = "", q: str = "", regex: str = "") -> StreamingResponse:
    require_log(log_id)
    check_filters(level, regex)
    return StreamingResponse(store.export_lines(log_id, level, q, regex), media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="opsmate-log-{log_id}.txt"'})


@router.delete("/{log_id}")
def delete_log(log_id: int) -> dict[str, bool]:
    if not store.delete_log(log_id):
        raise HTTPException(404, "日志不存在")
    return {"ok": True}


class AnalyzeInput(BaseModel):
    focus: str = Field(default="", max_length=1000)


@router.post("/{log_id}/llm-analyze")
async def analyze(log_id: int, body: AnalyzeInput, request: Request) -> StreamingResponse:
    require_log(log_id)
    async def events():
        async for event in analysis_events(log_id, body.focus, effective_settings(), request.is_disconnected):
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{log_id}/reports")
def reports(log_id: int) -> dict[str, Any]:
    require_log(log_id)
    return {"items": store.list_reports(log_id)}


@router.get("/{log_id}/reports/{report_id}")
def report(log_id: int, report_id: int) -> dict[str, str]:
    require_log(log_id)
    result = store.get_report(log_id, report_id)
    if result is None:
        raise HTTPException(404, "报告不存在或不属于该日志")
    return result

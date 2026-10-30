"""模型设置与连通测试；任何响应均不返回密钥。"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.llm.provider import LLMClient, PRESETS

router = APIRouter(prefix="/api", tags=["llm"])


class SettingsInput(BaseModel):
    provider: str = "zhipu"
    base_url: str = Field(max_length=2048)
    model: str = Field(max_length=256)
    api_key: str = Field(default="", max_length=8192)


def effective_settings() -> dict[str, Any]:
    """合并默认预设与本机设置（仅内部使用）。"""
    return {"provider": "zhipu", **PRESETS["zhipu"], **config.load_settings()}


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    """返回设置与密钥存在标志。"""
    settings = effective_settings()
    return {field: settings.get(field, "") for field in ("provider", "base_url", "model")} | {
        "api_key_set": bool(settings.get("api_key"))}


@router.put("/settings")
def put_settings(body: SettingsInput) -> dict[str, bool]:
    """保存设置；空密钥保留已有值。"""
    base_url = body.base_url.strip().rstrip("/")
    if body.provider not in PRESETS or not base_url.startswith(("http://", "https://")) or not body.model.strip():
        raise HTTPException(400, "请检查预设、base_url 与模型名")
    settings = effective_settings()
    settings.update(provider=body.provider, base_url=base_url, model=body.model.strip())
    if body.api_key.strip():
        settings["api_key"] = body.api_key.strip()
    config.ensure_dirs()
    config.save_settings(settings)
    return {"ok": True}


@router.post("/llm/test")
async def test_connection() -> dict[str, Any]:
    """总预算 55 秒内完成测试，包含 429 重试。"""
    settings = effective_settings()
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            LLMClient(settings).chat([{"role": "user", "content": "回复 pong"}],
                                     temperature=0, timeout=20, max_tokens=8), timeout=55)
    except asyncio.TimeoutError:
        result = {"ok": False, "error": "测试超时；请检查网络/密钥/模型名"}
    response = {"ok": result.get("ok", True), "latency_ms": round((time.perf_counter() - start) * 1000),
                "model": settings.get("model", "")}
    if not response["ok"]:
        response["error"] = result["error"]
    return response

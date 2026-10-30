"""模型设置与连通测试；任何响应均不返回密钥。"""
from __future__ import annotations

import asyncio
import time
import threading
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.llm.provider import LLMClient, PRESETS

router = APIRouter(prefix="/api", tags=["llm"])
_SETTINGS_LOCK = threading.RLock()


class SettingsInput(BaseModel):
    provider: str = "zhipu"
    base_url: str = Field(max_length=2048)
    model: str = Field(max_length=256)
    api_key: str = Field(default="", max_length=8192)


class ProfileInput(SettingsInput):
    name: str = Field(min_length=1, max_length=80)


def read_profiles() -> dict[str, Any]:
    """旧配置惰性迁移到本机列表；读取不写盘。"""
    try:
        profiles = config.load_model_profiles()
    except (OSError, ValueError):
        raise HTTPException(500, "本机命名配置读取失败，请检查本地文件") from None
    if not profiles["items"]:
        profiles = {"active_id": "current", "items": [
            {"id": "current", "name": "原有配置", **effective_settings()}]}
    return profiles


def public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """显式字段白名单，避免本机密钥进入响应。"""
    return {field: profile.get(field, "") for field in ("id", "name", "provider", "base_url", "model")} | {
        "api_key_set": bool(profile.get("api_key"))}


def validated_settings(body: SettingsInput, old: dict[str, Any]) -> dict[str, Any]:
    """验证模型配置，空 key 只保留所属配置的原值。"""
    base_url = body.base_url.strip().rstrip("/")
    if body.provider not in PRESETS or not base_url.startswith(("http://", "https://")) or not body.model.strip():
        raise HTTPException(400, "请检查预设、base_url 与模型名")
    return {"provider": body.provider, "base_url": base_url, "model": body.model.strip(),
            "api_key": body.api_key.strip() or old.get("api_key", "")}


@router.get("/settings/profiles")
def list_profiles() -> dict[str, Any]:
    """仅列出脱敏的本机配置。"""
    with _SETTINGS_LOCK:
        profiles = read_profiles()
        return {"active_id": profiles["active_id"], "items": [public_profile(p) for p in profiles["items"]]}


@router.post("/settings/profiles")
def create_profile(body: ProfileInput) -> dict[str, Any]:
    """保存独立配置，绝不复制原有配置的 key。"""
    settings = validated_settings(body, {})
    if not body.name.strip():
        raise HTTPException(400, "请填写配置名称")
    with _SETTINGS_LOCK:
        profiles = read_profiles()
        profile = {"id": uuid.uuid4().hex, "name": body.name.strip(), **settings}
        profiles["items"].append(profile)
        config.save_model_profiles(profiles)
    return {"ok": True, "id": profile["id"]}


@router.put("/settings/profiles/{profile_id}")
def update_profile(profile_id: str, body: ProfileInput) -> dict[str, bool]:
    """更新指定配置，只有当前启用项同步到活动快照。"""
    if not body.name.strip():
        raise HTTPException(400, "请填写配置名称")
    with _SETTINGS_LOCK:
        profiles = read_profiles()
        profile = next((p for p in profiles["items"] if p["id"] == profile_id), None)
        if profile is None:
            raise HTTPException(404, "本机配置不存在")
        settings = validated_settings(body, profile)
        profile.update(name=body.name.strip(), **settings)
        config.save_model_profiles(profiles)
        if profiles["active_id"] == profile_id:
            config.save_settings(settings)
    return {"ok": True}


@router.post("/settings/profiles/{profile_id}/activate")
def activate_profile(profile_id: str) -> dict[str, bool]:
    """显式启用；此动作不自动发起付费请求。"""
    with _SETTINGS_LOCK:
        profiles = read_profiles()
        profile = next((p for p in profiles["items"] if p["id"] == profile_id), None)
        if profile is None:
            raise HTTPException(404, "本机配置不存在")
        settings = {field: profile.get(field, "") for field in ("provider", "base_url", "model", "api_key")}
        if not settings["api_key"]:
            raise HTTPException(400, "请先保存该配置的 API key")
        config.ensure_dirs()
        config.save_settings(settings)
        profiles["active_id"] = profile_id
        config.save_model_profiles(profiles)
    return {"ok": True}


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
    with _SETTINGS_LOCK:
        settings = validated_settings(body, effective_settings())
        profiles = read_profiles()
        for profile in profiles["items"]:
            if profile["id"] == profiles["active_id"]:
                profile.update(settings)
        # 未使用多配置时维持原来的单文件布局。
        if config.PROFILES_JSON.exists():
            config.save_model_profiles(profiles)
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

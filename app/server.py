"""create_app()：FastAPI 实例、/api 路由挂载、静态托管 app/web。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config

VERSION = "1.0.0"


def create_app() -> FastAPI:
    """构建 FastAPI 应用实例（Phase 0：health + 静态托管）。"""
    config.ensure_dirs()
    app = FastAPI(title="OpsMate", version=VERSION)

    @app.get("/api/health")
    def health() -> JSONResponse:
        return JSONResponse({"ok": True, "version": VERSION})

    # 静态托管前端（零构建，Vue3/marked 为 vendored 全局构建）
    app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
    return app

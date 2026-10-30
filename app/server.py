"""create_app()：FastAPI 实例、/api 路由挂载、静态托管 app/web。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.commands.routes import router as commands_router
from app.kb.routes import router as kb_router
from app.llm.routes import router as llm_router
from app.codegen.routes import router as codegen_router
from app.logs.routes import router as logs_router
from app.logs.store import init_store
from app.kb.workbench import init_workbench
from app.assistant.routes import router as assistant_router
from app.assistant.service import init_assistant

VERSION = "1.0.0"


def create_app() -> FastAPI:
    """构建 FastAPI 应用实例（Phase 0：health + 静态托管）。"""
    config.ensure_dirs()
    init_store()
    init_workbench()
    init_assistant()
    app = FastAPI(title="OpsMate", version=VERSION)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI 默认会回显 input；设置参数可能包含密钥，统一仅返回定位与错误类型。
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]})

    @app.get("/api/health")
    def health() -> JSONResponse:
        return JSONResponse({"ok": True, "version": VERSION})

    app.include_router(commands_router)
    app.include_router(kb_router)
    app.include_router(llm_router)
    app.include_router(codegen_router)
    app.include_router(logs_router)
    app.include_router(assistant_router)

    # 静态托管前端（零构建，Vue3/marked 为 vendored 全局构建）
    app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
    return app

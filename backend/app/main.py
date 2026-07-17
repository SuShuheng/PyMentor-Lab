"""FastAPI application factory for the PyMentor Lab API service.

挂载系统路由（health + ping）、认证路由、管理端路由，安装错误信封处理器与
trace_id 中间件。启动时执行幂等引导（初始 admin、角色种子、demo 租户）。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.health import router as system_router
from app.config import get_settings
from app.errors import install_error_handlers
from app.middleware import TraceIdMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动时执行幂等引导（可由 PYMENTOR_BOOTSTRAP_ON_STARTUP=false 关闭）。

    测试环境默认关闭（通过环境变量），避免污染测试隔离。
    """
    if os.environ.get("PYMENTOR_BOOTSTRAP_ON_STARTUP", "true").lower() == "true":
        from app.bootstrap import run_bootstrap
        from app.db import SessionLocal

        with SessionLocal() as db:
            run_bootstrap(db)
    yield


def create_app() -> FastAPI:
    """Build the configured FastAPI application."""

    settings = get_settings()
    app = FastAPI(
        title="PyMentor Lab API",
        description="Higher-education Python learning system (competition release V1.0).",
        version=settings.version,
        lifespan=lifespan,
    )

    app.add_middleware(TraceIdMiddleware)
    install_error_handlers(app)

    app.include_router(system_router)
    app.include_router(auth_router)
    app.include_router(admin_router)

    return app


app = create_app()

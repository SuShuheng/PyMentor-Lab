"""FastAPI application factory for the PyMentor Lab API service.

挂载系统路由（health + ping）、认证路由、管理端路由，安装错误信封处理器与
trace_id 中间件。启动时执行幂等引导（初始 admin、角色种子、demo 租户）。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.admin_queries import router as admin_queries_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.cms import router as cms_router
from app.api.code import router as code_router
from app.api.evidence import router as evidence_router
from app.api.health import router as system_router
from app.api.hints import router as hints_router
from app.api.knowledge import router as knowledge_router
from app.api.learning import router as learning_router
from app.api.mastery import router as mastery_router
from app.api.paths import router as paths_router
from app.api.practice import router as practice_router
from app.api.profiles import router as profiles_router
from app.api.providers import router as providers_router
from app.api.resources import router as resources_router
from app.api.reviews import router as reviews_router
from app.api.system_maintenance import router as system_maintenance_router
from app.api.system_observability import router as system_observability_router
from app.api.tasks import router as tasks_router
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
    settings = get_settings()
    consumer_task: asyncio.Task[None] | None = None
    if settings.agent_event_consumer_enabled:
        from app.agent_event_consumer import (
            AgentEventConsumerHealth,
            create_agent_event_redis,
            run_agent_event_consumer,
        )
        from app.db import SessionLocal

        consumer_health = AgentEventConsumerHealth()
        app.state.agent_event_consumer_health = consumer_health
        consumer_task = asyncio.create_task(
            run_agent_event_consumer(
                create_agent_event_redis(settings), SessionLocal, settings, consumer_health
            ),
            name="agent-event-consumer",
        )
        app.state.agent_event_consumer_task = consumer_task
    try:
        yield
    finally:
        if consumer_task is not None:
            consumer_task.cancel()
            with suppress(asyncio.CancelledError):
                await consumer_task


def create_app() -> FastAPI:
    """Build the configured FastAPI application."""

    settings = get_settings()
    if "*" in settings.cors_allowed_origins:
        raise ValueError(
            "PYMENTOR_CORS_ALLOWED_ORIGINS must list explicit origins when credentials are enabled"
        )
    app = FastAPI(
        title="PyMentor Lab API",
        description="Higher-education Python learning system (competition release V1.0).",
        version=settings.version,
        lifespan=lifespan,
    )

    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "x-trace-id",
        ],
        expose_headers=["x-trace-id"],
    )
    install_error_handlers(app)

    app.include_router(system_router)
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(admin_router)
    app.include_router(admin_queries_router)
    app.include_router(cms_router)
    app.include_router(providers_router)
    app.include_router(system_observability_router)
    app.include_router(system_maintenance_router)
    app.include_router(evidence_router)
    app.include_router(profiles_router)
    app.include_router(knowledge_router)
    app.include_router(learning_router)
    app.include_router(paths_router)
    app.include_router(tasks_router)
    app.include_router(mastery_router)
    app.include_router(practice_router)
    app.include_router(reviews_router)
    app.include_router(resources_router)
    app.include_router(code_router)
    app.include_router(hints_router)

    return app


app = create_app()

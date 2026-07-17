"""FastAPI application factory for the PyMentor Lab API service.

The bootstrap app mounts the system router (health + ping) and installs the
stable error-envelope handlers plus the trace_id middleware. Domain routers
land in their own tasks (BE-002 onward).
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.health import router as system_router
from app.config import get_settings
from app.errors import install_error_handlers
from app.middleware import TraceIdMiddleware


def create_app() -> FastAPI:
    """Build the configured FastAPI application."""

    settings = get_settings()
    app = FastAPI(
        title="PyMentor Lab API",
        description="Higher-education Python learning system (competition release V1.0).",
        version=settings.version,
    )

    app.add_middleware(TraceIdMiddleware)
    install_error_handlers(app)

    app.include_router(system_router)

    return app


app = create_app()

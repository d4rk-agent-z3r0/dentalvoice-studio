"""FastAPI application factory.

Run with: ``uvicorn app.main:create_app --factory``. Nothing is built at import time, so importing
this module never requires configuration.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.database.session import create_engine, create_session_factory
from app.middleware.request_id import RequestIdMiddleware

log = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        log.info(
            "startup",
            environment=settings.environment.value,
            provider_mode=settings.voice_provider_mode.value,
        )
        try:
            yield
        finally:
            await engine.dispose()
            log.info("shutdown")

    app = FastAPI(
        title="DentalVoice Studio API",
        version="0.1.0",
        description="Synthetic AI voice patient onboarding simulator. Demo data only.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    return app

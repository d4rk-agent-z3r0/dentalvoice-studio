# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""FastAPI application factory.

Run with: ``uvicorn app.main:create_app --factory``. Nothing is built at import time, so importing
this module never requires configuration.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api import v1 as api_v1
from app.api.errors import install_error_handlers
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.database.session import create_engine, create_session_factory
from app.integrations.llm.factory import build_conversation_provider
from app.integrations.speech.factory import build_speech_providers
from app.middleware.request_id import RequestIdMiddleware
from app.orchestrators.conversation import ConversationOrchestrator
from app.voice.clips import default_library

log = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # Fails fast on a half-configured live mode instead of degrading at the first call.
    provider = build_conversation_provider(settings)
    clip_library = default_library()
    speech = build_speech_providers(settings, clip_library)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.clip_library = clip_library
        app.state.speech = speech
        app.state.orchestrator = ConversationOrchestrator(
            app.state.session_factory,
            provider,
            booking_horizon_days=settings.booking_horizon_days,
        )
        log.info(
            "startup",
            environment=settings.environment.value,
            provider_mode=settings.voice_provider_mode.value,
            conversation_provider=provider.name,
            stt_provider=speech.stt.name,
            tts_provider=speech.tts.name,
            auth_configured=settings.jwt_secret is not None,
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
        expose_headers=["X-Request-ID", "Idempotent-Replayed", "X-Clip-Source"],
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(api_v1.router)
    return app

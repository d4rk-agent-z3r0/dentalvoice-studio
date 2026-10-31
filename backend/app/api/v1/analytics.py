# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Clinic analytics, read only. The clinic is always ``principal.clinic_id``, from the token."""

from fastapi import APIRouter

from app.api.deps import CurrentPrincipal, SessionFactory
from app.core.config import ProviderMode
from app.schemas.analytics import AnalyticsSummary, LatencyReport
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
async def get_summary(
    principal: CurrentPrincipal, session_factory: SessionFactory
) -> AnalyticsSummary:
    return await AnalyticsService(session_factory).summary(principal.clinic_id)


@router.get("/latency", response_model=LatencyReport)
async def get_latency(
    principal: CurrentPrincipal,
    session_factory: SessionFactory,
    provider_mode: ProviderMode | None = None,
) -> LatencyReport:
    """p50/p95 per stage; ``provider_mode`` limits it to mock or live calls."""
    return await AnalyticsService(session_factory).latency(
        principal.clinic_id, provider_mode=provider_mode
    )

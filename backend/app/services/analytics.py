# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Clinic performance figures, computed from persisted rows only."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderMode
from app.domain.enums import TERMINAL_STATES, ConversationState
from app.repositories.analytics import AnalyticsRepository
from app.schemas.analytics import (
    AnalyticsSummary,
    EscalationReasonCount,
    LatencyReport,
    StageLatency,
)
from app.services.booking.availability import Clock, utc_now


class AnalyticsService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], clock: Clock = utc_now
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def summary(self, clinic_id: uuid.UUID) -> AnalyticsSummary:
        # One snapshot: every figure is read in the same REPEATABLE READ transaction.
        async with self._session_factory() as session, session.begin():
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            repository = AnalyticsRepository(session)
            counts = await repository.conversations_by_state(clinic_id)
            duration = await repository.duration(clinic_id)
            reasons = await repository.escalation_reasons(clinic_id)
        by_state = {state: counts.get(state, 0) for state in ConversationState}
        ended = sum(by_state[state] for state in TERMINAL_STATES)
        completed = by_state[ConversationState.COMPLETED]
        return AnalyticsSummary(
            generated_at=self._clock(),
            conversations_total=sum(by_state.values()),
            by_state=by_state,
            in_progress=sum(by_state.values()) - ended,
            ended=ended,
            completed=completed,
            escalated=by_state[ConversationState.ESCALATED],
            abandoned=by_state[ConversationState.ABANDONED],
            completion_rate=completed / ended if ended else None,
            average_duration_seconds=duration.average_seconds,
            duration_samples=duration.samples,
            escalation_reasons=[EscalationReasonCount(reason=r, count=c) for r, c in reasons],
        )

    async def latency(
        self, clinic_id: uuid.UUID, *, provider_mode: ProviderMode | None = None
    ) -> LatencyReport:
        async with self._session_factory() as session:
            stages = await AnalyticsRepository(session).stage_latency(
                clinic_id, provider_mode=provider_mode
            )
        return LatencyReport(
            generated_at=self._clock(),
            provider_mode=provider_mode,
            stages=[
                StageLatency.model_validate(
                    {
                        "stage": s.stage,
                        "samples": s.samples,
                        "p50_ms": s.p50_ms,
                        "p95_ms": s.p95_ms,
                    }
                )
                for s in stages
            ],
        )

# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Clinic-scoped aggregates over persisted rows. Every number is computed by PostgreSQL from what
was stored; nothing is estimated, and a measurement that was never taken stays NULL."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import String, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.config import ProviderMode
from app.domain.enums import ConversationState
from app.models import Conversation, ConversationEvent, ConversationTurn

# Stage name -> measured column on conversation_turns.
STAGE_COLUMNS: dict[str, InstrumentedAttribute[int | None]] = {
    "stt": ConversationTurn.stt_ms,
    "llm": ConversationTurn.llm_ms,
    "tts": ConversationTurn.tts_ms,
    "total": ConversationTurn.total_ms,
}


@dataclass(frozen=True)
class DurationStats:
    average_seconds: float | None
    samples: int


@dataclass(frozen=True)
class StageStats:
    stage: str
    samples: int
    p50_ms: float | None
    p95_ms: float | None


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def conversations_by_state(self, clinic_id: uuid.UUID) -> dict[ConversationState, int]:
        stmt = (
            select(Conversation.state, func.count())
            .where(Conversation.clinic_id == clinic_id)
            .group_by(Conversation.state)
        )
        rows = (await self._session.execute(stmt)).all()
        return {ConversationState(state): int(count) for state, count in rows}

    async def duration(self, clinic_id: uuid.UUID) -> DurationStats:
        """Mean ``ended_at - started_at`` over calls that both started and ended."""
        seconds = func.extract("epoch", Conversation.ended_at - Conversation.started_at)
        stmt = select(func.avg(seconds), func.count()).where(
            Conversation.clinic_id == clinic_id,
            Conversation.started_at.is_not(None),
            Conversation.ended_at.is_not(None),
        )
        average, samples = (await self._session.execute(stmt)).one()
        return DurationStats(
            average_seconds=None if average is None else float(average), samples=int(samples)
        )

    async def escalation_reasons(self, clinic_id: uuid.UUID) -> Sequence[tuple[str, int]]:
        """``escalated`` timeline events grouped by their recorded reason, most frequent first."""
        reason = func.coalesce(ConversationEvent.payload["reason"].astext, "unspecified").cast(
            String
        )
        stmt = (
            select(reason, func.count())
            .where(ConversationEvent.clinic_id == clinic_id, ConversationEvent.type == "escalated")
            .group_by(reason)
            .order_by(func.count().desc(), reason)
        )
        return [(str(r), int(c)) for r, c in (await self._session.execute(stmt)).all()]

    async def stage_latency(
        self, clinic_id: uuid.UUID, *, provider_mode: ProviderMode | None = None
    ) -> list[StageStats]:
        """p50/p95 (``percentile_cont``, interpolated) of each stage's measured milliseconds.

        Aggregates ignore NULLs, so a stage with no measurement has 0 samples and NULL
        percentiles, never 0 ms.
        """
        columns = []
        for column in STAGE_COLUMNS.values():
            columns += [
                func.count(column),
                func.percentile_cont(0.5).within_group(column),
                func.percentile_cont(0.95).within_group(column),
            ]
        stmt = select(*columns).where(ConversationTurn.clinic_id == clinic_id)
        if provider_mode is not None:
            stmt = stmt.join(
                Conversation,
                and_(
                    Conversation.clinic_id == ConversationTurn.clinic_id,
                    Conversation.id == ConversationTurn.conversation_id,
                ),
            ).where(Conversation.provider_mode == provider_mode)
        row = (await self._session.execute(stmt)).one()
        stats = []
        for index, stage in enumerate(STAGE_COLUMNS):
            samples, p50, p95 = row[index * 3 : index * 3 + 3]
            stats.append(
                StageStats(
                    stage=stage,
                    samples=int(samples),
                    p50_ms=None if p50 is None else float(p50),
                    p95_ms=None if p95 is None else float(p95),
                )
            )
        return stats

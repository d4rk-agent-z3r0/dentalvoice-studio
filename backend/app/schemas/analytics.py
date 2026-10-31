# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Clinic analytics. ``null`` always means "nothing measured yet", never zero."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.config import ProviderMode
from app.domain.enums import ConversationState

Stage = Literal["stt", "llm", "tts", "total"]


class EscalationReasonCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str
    count: int


class AnalyticsSummary(BaseModel):
    """Counts from ``conversations`` and ``conversation_events`` of the token's clinic.

    ``completion_rate`` is ``completed / ended`` (ended = completed + escalated + abandoned), or
    ``null`` before any call has ended. ``average_duration_seconds`` is the mean of
    ``ended_at - started_at`` over the ``duration_samples`` calls that have both, or ``null``.
    """

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    conversations_total: int
    by_state: dict[ConversationState, int]
    in_progress: int
    ended: int
    completed: int
    escalated: int
    abandoned: int
    completion_rate: float | None
    average_duration_seconds: float | None
    duration_samples: int
    escalation_reasons: list[EscalationReasonCount]


class StageLatency(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: Stage
    samples: int
    p50_ms: float | None
    p95_ms: float | None


class LatencyReport(BaseModel):
    """Percentiles of the stage timings measured on ``conversation_turns``."""

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    provider_mode: ProviderMode | None
    stages: list[StageLatency]

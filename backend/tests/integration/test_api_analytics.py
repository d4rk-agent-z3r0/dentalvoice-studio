# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Clinic analytics computed by PostgreSQL from known rows: counts, rates, durations, p50/p95."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderMode, Settings
from app.domain.enums import ClinicRole, ConversationState
from tests.conftest import ClientFactory
from tests.support.booking import build_booking_clinic, headers_for
from tests.support.records import TurnTimings, add_conversation, add_scenario

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]
S = ConversationState
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
async def client(
    client_factory: ClientFactory, database_settings: Settings, session_factory: SessionFactory
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory(database_settings) as http:
        yield http


async def _call(
    session_factory: SessionFactory,
    clinic_id: uuid.UUID,
    scenario_id: uuid.UUID,
    state: ConversationState,
    *,
    seconds: int | None = None,
    started: bool = True,
    provider_mode: ProviderMode = ProviderMode.MOCK,
    turns: list[TurnTimings] | None = None,
    escalation_reason: str | None = None,
) -> uuid.UUID:
    """A call that started at T0 (unless ``started`` is False) and, if terminal, ended
    ``seconds`` later."""
    ended = state in {S.COMPLETED, S.ESCALATED, S.ABANDONED}
    return await add_conversation(
        session_factory,
        clinic_id,
        scenario_id,
        state=state,
        created_at=T0,
        started_at=T0 if started else None,
        ended_at=T0 + timedelta(seconds=seconds or 0) if ended else None,
        provider_mode=provider_mode,
        turns=turns,
        escalation_reason=escalation_reason,
    )


@pytest.fixture
async def busy_clinic(session_factory: SessionFactory) -> uuid.UUID:
    """Eight calls with known states, durations, escalation reasons and stage timings."""
    clinic = await build_booking_clinic(session_factory)
    cid = clinic.clinic_id
    scenario = await add_scenario(session_factory, cid)
    await _call(
        session_factory,
        cid,
        scenario,
        S.COMPLETED,
        seconds=120,
        turns=[
            TurnTimings(llm_ms=100, total_ms=150),
            TurnTimings(llm_ms=200, total_ms=250),
            TurnTimings(llm_ms=300),
            TurnTimings(llm_ms=400),
            TurnTimings(),  # a greeting: nothing measured
        ],
    )
    await _call(
        session_factory,
        cid,
        scenario,
        S.COMPLETED,
        seconds=240,
        provider_mode=ProviderMode.LIVE,
        turns=[TurnTimings(llm_ms=1000), TurnTimings(llm_ms=2000)],
    )
    await _call(
        session_factory, cid, scenario, S.ESCALATED, seconds=60, escalation_reason="urgent_symptoms"
    )
    await _call(
        session_factory, cid, scenario, S.ESCALATED, seconds=60, escalation_reason="urgent_symptoms"
    )
    await _call(
        session_factory,
        cid,
        scenario,
        S.ESCALATED,
        started=False,
        escalation_reason="caller_request",
    )
    # Hung up before the call started: ended, but has no duration.
    await _call(session_factory, cid, scenario, S.ABANDONED, started=False)
    await _call(session_factory, cid, scenario, S.GREETING)
    await _call(session_factory, cid, scenario, S.CREATED, started=False)
    return cid


async def test_summary_counts_rates_and_durations_from_persisted_rows(
    client: httpx.AsyncClient,
    busy_clinic: uuid.UUID,
    database_settings: Settings,
    session_factory: SessionFactory,
) -> None:
    response = await client.get(
        "/api/v1/analytics/summary",
        headers=await headers_for(
            session_factory, database_settings, busy_clinic, ClinicRole.VIEWER
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["conversations_total"] == 8
    assert body["by_state"] == {
        **{state.value: 0 for state in ConversationState},
        "COMPLETED": 2,
        "ESCALATED": 3,
        "ABANDONED": 1,
        "GREETING": 1,
        "CREATED": 1,
    }
    assert (body["ended"], body["in_progress"]) == (6, 2)
    assert (body["completed"], body["escalated"], body["abandoned"]) == (2, 3, 1)
    assert body["completion_rate"] == pytest.approx(2 / 6)
    # (120 + 240 + 60 + 60) / 4: calls that never started are not averaged in.
    assert body["average_duration_seconds"] == pytest.approx(120.0)
    assert body["duration_samples"] == 4
    assert body["escalation_reasons"] == [
        {"reason": "urgent_symptoms", "count": 2},
        {"reason": "caller_request", "count": 1},
    ]
    assert datetime.fromisoformat(body["generated_at"])


async def test_latency_percentiles_on_known_timings(
    client: httpx.AsyncClient,
    busy_clinic: uuid.UUID,
    database_settings: Settings,
    session_factory: SessionFactory,
) -> None:
    headers = await headers_for(session_factory, database_settings, busy_clinic, ClinicRole.STAFF)

    async def stages(query: str = "") -> dict[str, dict[str, object]]:
        response = await client.get(f"/api/v1/analytics/latency{query}", headers=headers)
        assert response.status_code == 200, response.text
        return {s.pop("stage"): s for s in response.json()["stages"]}

    # llm: 100, 200, 300, 400, 1000, 2000. percentile_cont interpolates:
    # p50 at rank 2.5 -> 350; p95 at rank 4.75 -> 1000 + 0.75 * 1000 = 1750.
    everything = await stages()
    assert everything["llm"] == {"samples": 6, "p50_ms": 350.0, "p95_ms": 1750.0}
    assert everything["total"] == {"samples": 2, "p50_ms": 200.0, "p95_ms": 245.0}
    # Never measured (speech stages arrive with Milestone 5): null, not 0.
    assert everything["stt"] == {"samples": 0, "p50_ms": None, "p95_ms": None}
    assert everything["tts"] == {"samples": 0, "p50_ms": None, "p95_ms": None}

    mock = await stages("?provider_mode=mock")
    assert mock["llm"] == {"samples": 4, "p50_ms": 250.0, "p95_ms": 385.0}
    live = await stages("?provider_mode=live")
    assert live["llm"] == {"samples": 2, "p50_ms": 1500.0, "p95_ms": 1950.0}
    assert live["total"] == {"samples": 0, "p50_ms": None, "p95_ms": None}

    bad = await client.get("/api/v1/analytics/latency?provider_mode=fake", headers=headers)
    assert (bad.status_code, bad.json()["error"]["code"]) == (400, "VALIDATION_ERROR")


async def test_an_empty_clinic_reports_nothing_measured_rather_than_zero(
    client: httpx.AsyncClient,
    busy_clinic: uuid.UUID,
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    empty = (await build_booking_clinic(session_factory)).clinic_id
    headers = await headers_for(session_factory, database_settings, empty, ClinicRole.VIEWER)

    summary = (await client.get("/api/v1/analytics/summary", headers=headers)).json()
    assert summary["conversations_total"] == 0
    assert set(summary["by_state"].values()) == {0}
    assert summary["completion_rate"] is None
    assert summary["average_duration_seconds"] is None
    assert summary["duration_samples"] == 0
    assert summary["escalation_reasons"] == []

    latency = (await client.get("/api/v1/analytics/latency", headers=headers)).json()
    assert latency["provider_mode"] is None
    assert latency["stages"] == [
        {"stage": stage, "samples": 0, "p50_ms": None, "p95_ms": None}
        for stage in ("stt", "llm", "tts", "total")
    ]


async def test_turns_without_any_timing_give_null_percentiles(
    client: httpx.AsyncClient, session_factory: SessionFactory, database_settings: Settings
) -> None:
    clinic = (await build_booking_clinic(session_factory)).clinic_id
    scenario = await add_scenario(session_factory, clinic)
    await _call(session_factory, clinic, scenario, S.GREETING, turns=[TurnTimings()] * 3)

    response = await client.get(
        "/api/v1/analytics/latency",
        headers=await headers_for(session_factory, database_settings, clinic, ClinicRole.ADMIN),
    )
    assert all(
        stage["samples"] == 0 and stage["p50_ms"] is None and stage["p95_ms"] is None
        for stage in response.json()["stages"]
    )
    summary = await client.get(
        "/api/v1/analytics/summary",
        headers=await headers_for(session_factory, database_settings, clinic, ClinicRole.ADMIN),
    )
    # One call in progress, none ended yet: no completion rate.
    assert (summary.json()["in_progress"], summary.json()["completion_rate"]) == (1, None)


async def test_figures_are_scoped_to_the_tokens_clinic(
    client: httpx.AsyncClient,
    busy_clinic: uuid.UUID,
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    other = (await build_booking_clinic(session_factory)).clinic_id
    scenario = await add_scenario(session_factory, other)
    await _call(
        session_factory,
        other,
        scenario,
        S.COMPLETED,
        seconds=30,
        turns=[TurnTimings(llm_ms=5)],
    )
    headers = await headers_for(session_factory, database_settings, other, ClinicRole.VIEWER)

    summary = (await client.get("/api/v1/analytics/summary", headers=headers)).json()
    assert (summary["conversations_total"], summary["completion_rate"]) == (1, 1.0)
    assert summary["average_duration_seconds"] == pytest.approx(30.0)
    latency = (await client.get("/api/v1/analytics/latency", headers=headers)).json()
    llm = next(s for s in latency["stages"] if s["stage"] == "llm")
    assert llm == {"stage": "llm", "samples": 1, "p50_ms": 5.0, "p95_ms": 5.0}
    # A clinic id in the query string is ignored.
    smuggled = await client.get(
        f"/api/v1/analytics/summary?clinic_id={busy_clinic}", headers=headers
    )
    assert smuggled.json()["conversations_total"] == 1

    for path in ("/api/v1/analytics/summary", "/api/v1/analytics/latency"):
        anonymous = await client.get(path)
        assert (anonymous.status_code, anonymous.json()["error"]["code"]) == (401, "AUTH_REQUIRED")

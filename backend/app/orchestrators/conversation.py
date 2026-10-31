# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""One conversation turn, end to end.

A caller turn runs in three phases so no database lock is held while a model is thinking:

1. **Record** (transaction, row lock): check the conversation is open, persist the caller turn,
   read the context, and note ``state_version``.
2. **Propose** (no transaction): ask the conversation model for a ``TurnProposal``, timed.
3. **Decide and commit** (transaction, row lock): re-check ``state_version`` (a concurrent turn
   loses with ``ConcurrentUpdateError``), validate and apply intake values, derive the path through
   the state machine, run side effects (review, confirmation, snapshot, patient record), persist
   the receptionist turn and every event.

The orchestrator is stateless: everything lives in PostgreSQL, so a restarted process continues
any conversation exactly where it was.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import uuid7
from app.core.logging import get_logger
from app.domain.enums import (
    TERMINAL_STATES,
    ConversationState,
    IntakeField,
    PatientStatus,
    Speaker,
)
from app.domain.errors import (
    ConcurrentUpdateError,
    ConversationClosedError,
    ConversationNotStartedError,
    InvalidStateTransitionError,
    NotFoundError,
)
from app.integrations.llm.base import (
    ConversationModelProvider,
    HistoryLine,
    ProposalResult,
    ProviderError,
    TokenUsage,
    TurnContext,
)
from app.models import Conversation, ConversationTurn, Patient
from app.orchestrators.decision import Decision, decide
from app.orchestrators.responses import ReplyContext, compose_reply
from app.repositories.clinics import ClinicRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.intake import EventRepository
from app.repositories.patients import PatientRepository
from app.repositories.scenarios import ScenarioRepository
from app.repositories.turns import TurnRepository
from app.schemas.intake import IntakeSnapshotData
from app.schemas.proposal import TurnProposal
from app.services.intake.fields import ValidationContext
from app.services.intake.service import IntakeChanges, IntakeService
from app.services.intake.stages import LiveValues, missing_fields
from app.state_machine.machine import validate_path

log = get_logger(__name__)

S = ConversationState
HISTORY_TURNS = 8
# States whose wording must never come from a model.
_FIXED_REPLY_STATES = frozenset({S.ESCALATED, S.COMPLETED, S.ABANDONED, S.CONFIRMATION_PENDING})


@dataclass(frozen=True)
class TurnResult:
    conversation_id: uuid.UUID
    previous_state: ConversationState
    state: ConversationState
    path: list[ConversationState]
    state_version: int
    reply: str
    receptionist_turn_seq: int
    caller_turn_seq: int | None = None
    missing_fields: list[IntakeField] = field(default_factory=list)
    rejected_fields: dict[IntakeField, str] = field(default_factory=dict)
    corrected_fields: list[IntakeField] = field(default_factory=list)
    llm_ms: int | None = None


@dataclass(frozen=True)
class _Recorded:
    caller_turn_id: uuid.UUID
    caller_seq: int
    state: ConversationState
    version: int
    context: TurnContext
    clinic_today: datetime


class ConversationOrchestrator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: ConversationModelProvider,
        *,
        booking_horizon_days: int = 60,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sf = session_factory
        self._provider = provider
        self._horizon = booking_horizon_days
        self._clock = clock

    # --- lifecycle ------------------------------------------------------------------------------

    async def start(self, clinic_id: uuid.UUID, conversation_id: uuid.UUID) -> TurnResult:
        async with self._sf.begin() as session:
            conversation = await self._locked(session, clinic_id, conversation_id)
            if conversation.state is not S.CREATED:
                raise InvalidStateTransitionError("This conversation has already started.")
            clinic = await ClinicRepository(session).get(clinic_id)
            assert clinic is not None  # guaranteed by the foreign key
            now = self._clock()
            self._transition(session, conversation, [S.GREETING], now)
            conversation.started_at = now
            reply = compose_reply(
                ReplyContext(clinic.name, S.GREETING, {}, [], {}, {}, [], clarification=False)
            )
            seq, _ = self._add_turn(session, conversation, Speaker.RECEPTIONIST, reply)
            await session.flush()
            return TurnResult(
                conversation_id=conversation.id,
                previous_state=S.CREATED,
                state=conversation.state,
                path=[S.GREETING],
                state_version=conversation.state_version,
                reply=reply,
                receptionist_turn_seq=seq,
            )

    async def end(self, clinic_id: uuid.UUID, conversation_id: uuid.UUID) -> ConversationState:
        """The caller hung up. Abandons the call unless it already ended."""
        async with self._sf.begin() as session:
            conversation = await self._locked(session, clinic_id, conversation_id)
            if conversation.state in TERMINAL_STATES:
                raise ConversationClosedError
            self._transition(session, conversation, [S.ABANDONED], self._clock())
            return conversation.state

    async def record_reply_audio(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        turn_seq: int,
        *,
        tts_ms: int | None,
        total_ms: int | None,
    ) -> None:
        """Store speech timings measured by the voice session for a receptionist turn."""
        async with self._sf.begin() as session:
            await TurnRepository(session).set_audio_timings(
                clinic_id, conversation_id, turn_seq, tts_ms=tts_ms, total_ms=total_ms
            )

    # --- caller turn ---------------------------------------------------------------------------

    async def handle_caller_turn(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        text: str,
        *,
        clip_id: str | None = None,
        stt_ms: int | None = None,
    ) -> TurnResult:
        recorded = await self._record(clinic_id, conversation_id, text, clip_id, stt_ms)

        started = time.perf_counter()
        try:
            result = await self._provider.propose(recorded.context)
        except ProviderError as error:
            await self._record_provider_error(clinic_id, conversation_id, error)
            raise
        llm_ms = round((time.perf_counter() - started) * 1000)

        return await self._decide_and_commit(clinic_id, conversation_id, recorded, result, llm_ms)

    async def _record(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        text: str,
        clip_id: str | None,
        stt_ms: int | None,
    ) -> _Recorded:
        async with self._sf.begin() as session:
            conversation = await self._locked(session, clinic_id, conversation_id)
            if conversation.state in TERMINAL_STATES:
                raise ConversationClosedError
            if conversation.state is S.CREATED:
                raise ConversationNotStartedError
            seq, turn_id = self._add_turn(
                session, conversation, Speaker.CALLER, text, clip_id=clip_id, stt_ms=stt_ms
            )
            clinic = await ClinicRepository(session).get(clinic_id)
            assert clinic is not None
            now_local = self._clock().astimezone(ZoneInfo(clinic.timezone))
            services = {
                t.code: t.name
                for t in await ClinicRepository(session).active_appointment_types(clinic_id)
            }
            values = await IntakeService(session).live_values(clinic_id, conversation_id)
            history = await TurnRepository(session).list(
                clinic_id, conversation_id, last=HISTORY_TURNS
            )
            context = TurnContext(
                clinic_name=clinic.name,
                clinic_today=now_local.date(),
                state=conversation.state,
                utterance=text,
                known_values={name: value for name, (value, _) in values.items()},
                missing_fields=missing_fields(values),
                services=services,
                history=[HistoryLine(t.speaker, t.text) for t in history],
            )
            return _Recorded(
                caller_turn_id=turn_id,
                caller_seq=seq,
                state=conversation.state,
                version=conversation.state_version,
                context=context,
                clinic_today=now_local,
            )

    async def _decide_and_commit(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        recorded: _Recorded,
        result: ProposalResult,
        llm_ms: int,
    ) -> TurnResult:
        proposal = result.proposal
        async with self._sf.begin() as session:
            conversation = await self._locked(session, clinic_id, conversation_id)
            if conversation.state_version != recorded.version:
                raise ConcurrentUpdateError(
                    "The conversation changed while this turn was processed. Please retry."
                )
            intake = IntakeService(session)
            changes = await intake.apply(
                clinic_id,
                conversation_id,
                updates=proposal.field_updates.items(),
                declined=list(proposal.declined_fields),
                corrected=list(proposal.corrected_fields),
                confidence=proposal.confidence,
                source_turn_id=recorded.caller_turn_id,
                ctx=ValidationContext(
                    today=recorded.context.clinic_today,
                    service_codes=frozenset(recorded.context.services),
                    booking_horizon_days=self._horizon,
                ),
            )
            values = await intake.live_values(clinic_id, conversation_id)
            decision = decide(recorded.state, proposal, changes, values)
            validate_path(recorded.state, decision.path)  # defence in depth
            events = EventRepository(session)
            if decision.ignored_action is not None:
                events.record(
                    clinic_id,
                    conversation_id,
                    "proposal_action_ignored",
                    {"action": decision.ignored_action.value},
                )
            now = self._clock()
            self._transition(session, conversation, decision.path, now)
            await self._side_effects(session, conversation, decision, proposal, now)

            values = await intake.live_values(clinic_id, conversation_id)
            reply = self._reply(recorded, conversation.state, decision, proposal, changes, values)
            seq, _ = self._add_turn(
                session,
                conversation,
                Speaker.RECEPTIONIST,
                reply,
                llm_ms=llm_ms,
                usage=result.usage,
                attempts=result.attempts,
            )
            await session.flush()
            log.info(
                "conversation_turn",
                conversation_id=str(conversation_id),
                previous_state=recorded.state.value,
                state=conversation.state.value,
                path=[s.value for s in decision.path],
                accepted=len(changes.accepted),
                corrected=len(changes.corrected),
                rejected=len(changes.rejected),
                llm_ms=llm_ms,
                llm_attempts=result.attempts,
                prompt_tokens=result.usage.prompt_tokens if result.usage else None,
                output_tokens=result.usage.output_tokens if result.usage else None,
                provider=self._provider.name,
            )
            return TurnResult(
                conversation_id=conversation_id,
                previous_state=recorded.state,
                state=conversation.state,
                path=decision.path,
                state_version=conversation.state_version,
                reply=reply,
                receptionist_turn_seq=seq,
                caller_turn_seq=recorded.caller_seq,
                missing_fields=missing_fields(values),
                rejected_fields=changes.rejected,
                corrected_fields=changes.corrected,
                llm_ms=llm_ms,
            )

    # --- helpers -------------------------------------------------------------------------------

    async def _locked(
        self, session: AsyncSession, clinic_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = await ConversationRepository(session).get_for_update(
            clinic_id, conversation_id
        )
        if conversation is None:
            raise NotFoundError("Conversation")
        return conversation

    def _transition(
        self,
        session: AsyncSession,
        conversation: Conversation,
        path: list[ConversationState],
        now: datetime,
    ) -> None:
        if not path:
            return
        validate_path(conversation.state, path)
        events = EventRepository(session)
        previous = conversation.state
        for target in path:
            events.record(
                conversation.clinic_id,
                conversation.id,
                "state_changed",
                {"from": previous.value, "to": target.value},
            )
            previous = target
        conversation.state = path[-1]
        conversation.state_version += 1
        if conversation.state in TERMINAL_STATES:
            conversation.ended_at = now

    async def _side_effects(
        self,
        session: AsyncSession,
        conversation: Conversation,
        decision: Decision,
        proposal: TurnProposal,
        now: datetime,
    ) -> None:
        clinic_id, conversation_id = conversation.clinic_id, conversation.id
        intake = IntakeService(session)
        entered = set(decision.path)
        if S.INFORMATION_REVIEW in entered:
            await intake.mark_for_review(clinic_id, conversation_id)
        if S.CONFIRMATION_PENDING in entered:
            await intake.confirm_all(clinic_id, conversation_id)  # the caller confirmed the review
        if S.ESCALATED in entered:
            EventRepository(session).record(
                clinic_id,
                conversation_id,
                "escalated",
                {"reason": proposal.escalation_reason or "requested"},
            )
        if S.COMPLETED in entered:
            snapshot = await intake.create_snapshot(clinic_id, conversation_id, now)
            conversation.patient_id = await self._link_patient(session, conversation, snapshot)

    async def _link_patient(
        self, session: AsyncSession, conversation: Conversation, snapshot: IntakeSnapshotData
    ) -> uuid.UUID:
        """Duplicate detection: an existing record with the same contact value is reused."""
        clinic_id = conversation.clinic_id
        events = EventRepository(session)
        existing = await PatientRepository(session).find_by_contact(
            clinic_id, email=snapshot.email, phone=snapshot.phone
        )
        if existing is not None:
            events.record(
                clinic_id,
                conversation.id,
                "patient_matched",
                {"patient_id": str(existing.id), "claimed_type": snapshot.patient_type.value},
            )
            if existing.status is not PatientStatus.REGISTERED:
                existing.status = PatientStatus.REGISTERED
            return existing.id
        scenario = await ScenarioRepository(session).get(clinic_id, conversation.scenario_id)
        patient = Patient(
            id=uuid7(),
            clinic_id=clinic_id,
            persona_id=scenario.persona_id if scenario else None,
            first_name=snapshot.first_name,
            last_name=snapshot.last_name,
            email=snapshot.email,
            phone=snapshot.phone,
            preferred_contact_channel=snapshot.preferred_contact_channel,
            patient_type=snapshot.patient_type,
            status=PatientStatus.REGISTERED,
        )
        PatientRepository(session).add(patient)
        await session.flush()  # the conversation's composite FK must see the new row
        events.record(
            clinic_id, conversation.id, "patient_created", {"patient_id": str(patient.id)}
        )
        return patient.id

    def _reply(
        self,
        recorded: _Recorded,
        state: ConversationState,
        decision: Decision,
        proposal: TurnProposal,
        changes: IntakeChanges,
        values: LiveValues,
    ) -> str:
        use_model_text = (
            self._provider.writes_responses
            and state not in _FIXED_REPLY_STATES
            and decision.ignored_action is None
            and not changes.rejected
        )
        if use_model_text:
            return proposal.assistant_response
        return compose_reply(
            ReplyContext(
                clinic_name=recorded.context.clinic_name,
                state=state,
                values={name: value for name, (value, _) in values.items()},
                missing=missing_fields(values),
                services=recorded.context.services,
                rejected=changes.rejected,
                corrected=changes.corrected,
                clarification=decision.clarification,
            )
        )

    def _add_turn(
        self,
        session: AsyncSession,
        conversation: Conversation,
        speaker: Speaker,
        text: str,
        *,
        clip_id: str | None = None,
        stt_ms: int | None = None,
        llm_ms: int | None = None,
        usage: TokenUsage | None = None,
        attempts: int | None = None,
    ) -> tuple[int, uuid.UUID]:
        seq = conversation.turn_count + 1
        turn_id = uuid7()
        TurnRepository(session).add(
            ConversationTurn(
                id=turn_id,
                clinic_id=conversation.clinic_id,
                conversation_id=conversation.id,
                seq=seq,
                speaker=speaker,
                text=text,
                clip_id=clip_id,
                stt_ms=stt_ms,
                llm_ms=llm_ms,
                prompt_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                llm_attempts=attempts,
            )
        )
        conversation.turn_count = seq
        return seq, turn_id

    async def _record_provider_error(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID, error: ProviderError
    ) -> None:
        log.warning("provider_error", provider=error.provider, conversation_id=str(conversation_id))
        async with self._sf.begin() as session:
            EventRepository(session).record(
                clinic_id,
                conversation_id,
                "provider_error",
                {"provider": error.provider, "code": error.code},
            )

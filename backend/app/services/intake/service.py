# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Apply proposed intake values with validation, provenance and correction history.

Runs inside the caller's transaction (the orchestrator owns it). Every decision is recorded as a
``conversation_events`` row. Event payloads hold field names and draft ids only, never the values
themselves, so the timeline can be shown without exposing contact details.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.domain.enums import ContactChannel, IntakeField, IntakeFieldStatus, PatientType
from app.models import IntakeDraft, IntakeSnapshot
from app.repositories.intake import EventRepository, IntakeRepository
from app.schemas.intake import IntakeSnapshotData
from app.services.intake.fields import (
    DECLINABLE_FIELDS,
    FieldRejectedError,
    ValidationContext,
    validate_field,
)
from app.services.intake.stages import ALL_FIELDS, LiveValues

# Below this model confidence a value is kept but flagged for explicit confirmation.
CONFIRMATION_THRESHOLD = 0.6

_ACTIVE = (IntakeFieldStatus.PROVIDED, IntakeFieldStatus.NEEDS_CONFIRMATION)


@dataclass
class IntakeChanges:
    accepted: list[IntakeField] = field(default_factory=list)
    corrected: list[IntakeField] = field(default_factory=list)
    rejected: dict[IntakeField, str] = field(default_factory=dict)
    declined: list[IntakeField] = field(default_factory=list)
    unchanged: list[IntakeField] = field(default_factory=list)

    @property
    def changed_fields(self) -> list[IntakeField]:
        return [*self.accepted, *self.corrected, *self.declined]


class IntakeService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._drafts = IntakeRepository(session)
        self._events = EventRepository(session)

    async def live(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> dict[IntakeField, IntakeDraft]:
        return {d.field: d for d in await self._drafts.live_drafts(clinic_id, conversation_id)}

    async def live_values(self, clinic_id: uuid.UUID, conversation_id: uuid.UUID) -> LiveValues:
        live = await self.live(clinic_id, conversation_id)
        return {name: (draft.value, draft.status) for name, draft in live.items()}

    async def apply(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        updates: list[tuple[IntakeField, str]],
        declined: list[IntakeField],
        corrected: list[IntakeField],
        confidence: float,
        source_turn_id: uuid.UUID | None,
        ctx: ValidationContext,
    ) -> IntakeChanges:
        live = await self.live(clinic_id, conversation_id)
        changes = IntakeChanges()
        status = (
            IntakeFieldStatus.NEEDS_CONFIRMATION
            if confidence < CONFIRMATION_THRESHOLD
            else IntakeFieldStatus.PROVIDED
        )
        conf = Decimal(str(round(confidence, 3)))

        for name, raw in updates:
            try:
                value = validate_field(name, raw, ctx)
            except FieldRejectedError as error:
                draft = self._new_draft(
                    clinic_id,
                    conversation_id,
                    name,
                    raw[:500],
                    IntakeFieldStatus.REJECTED,
                    conf,
                    source_turn_id,
                    reason=error.reason[:200],
                )
                changes.rejected[name] = error.reason
                self._event(clinic_id, conversation_id, "field_rejected", name, draft.id)
                continue

            previous = live.get(name)
            if previous is not None and previous.value == value:
                changes.unchanged.append(name)
                continue
            if previous is not None:
                previous.status = IntakeFieldStatus.SUPERSEDED
                await self._flush()
            draft = self._new_draft(
                clinic_id, conversation_id, name, value, status, conf, source_turn_id
            )
            if previous is None:
                changes.accepted.append(name)
                self._event(clinic_id, conversation_id, "field_proposed", name, draft.id)
            else:
                changes.corrected.append(name)
                self._event(
                    clinic_id,
                    conversation_id,
                    "field_corrected",
                    name,
                    draft.id,
                    replaces=str(previous.id),
                    announced=name in corrected,
                )
            live[name] = draft

        for name in declined:
            if name not in DECLINABLE_FIELDS:
                self._event(clinic_id, conversation_id, "decline_ignored", name, None)
                continue
            previous = live.get(name)
            if previous is not None and previous.value is None:
                continue  # already declined
            if previous is not None:
                previous.status = IntakeFieldStatus.SUPERSEDED
                await self._flush()
            draft = self._new_draft(
                clinic_id,
                conversation_id,
                name,
                None,
                IntakeFieldStatus.NOT_PROVIDED,
                conf,
                source_turn_id,
            )
            changes.declined.append(name)
            self._event(clinic_id, conversation_id, "field_declined", name, draft.id)
            live[name] = draft
        await self._flush()
        return changes

    async def mark_for_review(self, clinic_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        await self._drafts.set_status(
            clinic_id,
            conversation_id,
            from_statuses=[IntakeFieldStatus.PROVIDED],
            to_status=IntakeFieldStatus.NEEDS_CONFIRMATION,
        )

    async def confirm_all(self, clinic_id: uuid.UUID, conversation_id: uuid.UUID) -> int:
        return await self._drafts.set_status(
            clinic_id, conversation_id, from_statuses=_ACTIVE, to_status=IntakeFieldStatus.CONFIRMED
        )

    async def create_snapshot(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID, confirmed_at: datetime
    ) -> IntakeSnapshotData:
        live = await self.live(clinic_id, conversation_id)
        missing = [name for name in ALL_FIELDS if name not in live]
        if missing:
            raise ValueError(f"Cannot snapshot an incomplete intake: missing {missing}")

        def value(name: IntakeField) -> str:
            raw = live[name].value
            if raw is None:
                raise ValueError(f"{name} has no value")
            return raw

        data = IntakeSnapshotData(
            first_name=value(IntakeField.FIRST_NAME),
            last_name=value(IntakeField.LAST_NAME),
            patient_type=PatientType(value(IntakeField.PATIENT_TYPE)),
            preferred_contact_channel=ContactChannel(value(IntakeField.PREFERRED_CONTACT_CHANNEL)),
            email=live[IntakeField.EMAIL].value,
            phone=live[IntakeField.PHONE].value,
            visit_reason=value(IntakeField.VISIT_REASON),
            requested_service=value(IntakeField.REQUESTED_SERVICE),
            preferred_date=date.fromisoformat(value(IntakeField.PREFERRED_DATE)),
            preferred_time=time.fromisoformat(value(IntakeField.PREFERRED_TIME)),
            provenance={name: draft.id for name, draft in live.items()},
        )
        self._drafts.add_snapshot(
            IntakeSnapshot(
                clinic_id=clinic_id,
                conversation_id=conversation_id,
                data=data.model_dump(mode="json"),
                confirmed_at=confirmed_at,
            )
        )
        self._events.record(clinic_id, conversation_id, "intake_snapshot_created", {})
        return data

    # --- helpers -------------------------------------------------------------------------------

    def _new_draft(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        name: IntakeField,
        value: str | None,
        status: IntakeFieldStatus,
        confidence: Decimal,
        source_turn_id: uuid.UUID | None,
        *,
        reason: str | None = None,
    ) -> IntakeDraft:
        draft = IntakeDraft(
            id=uuid7(),  # known before flush, so events can reference it
            clinic_id=clinic_id,
            conversation_id=conversation_id,
            field=name,
            value=value,
            status=status,
            confidence=confidence,
            source_turn_id=source_turn_id,
            rejection_reason=reason,
        )
        self._drafts.add(draft)
        return draft

    def _event(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        type_: str,
        name: IntakeField,
        draft_id: uuid.UUID | None,
        **extra: object,
    ) -> None:
        payload: dict[str, object] = {"field": name.value, **extra}
        if draft_id is not None:
            payload["draft_id"] = str(draft_id)
        self._events.record(clinic_id, conversation_id, type_, payload)

    async def _flush(self) -> None:
        await self._session.flush()

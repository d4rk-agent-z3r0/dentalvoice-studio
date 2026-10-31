# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from datetime import datetime

from app.core.config import ProviderMode
from app.domain.enums import ConversationState
from app.schemas.common import ReadModel


class ConversationRead(ReadModel):
    id: uuid.UUID
    scenario_id: uuid.UUID
    patient_id: uuid.UUID | None
    state: ConversationState
    state_version: int
    provider_mode: ProviderMode
    turn_count: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime

# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
from fastapi import APIRouter

from app.api.v1 import (
    appointments,
    audio,
    availability,
    conversations,
    patients,
    scenarios,
    voice,
)

router = APIRouter(prefix="/api/v1")
router.include_router(scenarios.router)
router.include_router(conversations.router)
router.include_router(availability.router)
router.include_router(appointments.router)
router.include_router(audio.router)
router.include_router(voice.router)
router.include_router(patients.router)

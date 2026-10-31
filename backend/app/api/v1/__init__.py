# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
from fastapi import APIRouter

from app.api.v1 import availability, conversations, scenarios

router = APIRouter(prefix="/api/v1")
router.include_router(scenarios.router)
router.include_router(conversations.router)
router.include_router(availability.router)

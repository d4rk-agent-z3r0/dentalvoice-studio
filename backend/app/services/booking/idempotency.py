# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Idempotency keys and canonical request hashes for booking writes."""

import hashlib
import json
import re
from collections.abc import Mapping

# Client keys: URL-safe characters only. Keys the server generates itself (reschedules) contain a
# ':' and therefore can never collide with, or be pre-empted by, a client-chosen key.
CLIENT_KEY_PATTERN = r"^[A-Za-z0-9_-]{8,128}$"
_CLIENT_KEY = re.compile(CLIENT_KEY_PATTERN)


def is_client_key(key: str) -> bool:
    return _CLIENT_KEY.fullmatch(key) is not None


def canonical_json(payload: Mapping[str, object]) -> str:
    """Sorted keys, no insignificant whitespace, UTF-8: equal payloads give equal text."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_hash(payload: Mapping[str, object]) -> str:
    """SHA-256 hex digest of the canonical JSON of a validated, normalised request body."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def reschedule_key(appointment_id: object) -> str:
    """The idempotency key of the appointment that replaces ``appointment_id``.

    Deterministic, so ``UNIQUE (clinic_id, idempotency_key)`` also guarantees that one appointment
    is replaced at most once.
    """
    return f"reschedule:{appointment_id}"

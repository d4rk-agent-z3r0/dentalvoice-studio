# ADR-0004: Database-enforced booking integrity

**Status:** Accepted · 2026-10-30

## Context
Double booking must be impossible under concurrent requests. Application-level "check then insert"
races; `SERIALIZABLE` everywhere adds retry complexity to every booking path.

## Decision
- `EXCLUDE USING gist (dentist_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)` for active
  statuses (requires `btree_gist`).
- `UNIQUE (clinic_id, idempotency_key)`; a replay with an identical request hash returns the original
  appointment, a different hash returns `409 IDEMPOTENCY_CONFLICT`.
- Availability is computed from `dentist_schedules` minus active appointments; there is no
  materialised `appointment_slots` table.
- The API reports `confirmed` only after the transaction commits.

## Consequences
The database is the single arbiter. A losing concurrent request receives `409 BOOKING_SLOT_TAKEN`.
Tests must run against PostgreSQL.

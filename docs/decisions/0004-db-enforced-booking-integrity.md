# ADR-0004: Database-enforced booking integrity

**Status:** Accepted · 2026-10-30 · **Revised** 2026-10-31 (published slots, see below)

## Context
Double booking must be impossible under concurrent requests. Application-level "check then insert"
races; `SERIALIZABLE` everywhere adds retry complexity to every booking path.

## Decision
- `EXCLUDE USING gist (dentist_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)` on
  `appointments` for active statuses (`requested`, `confirmed`); requires `btree_gist`.
- `UNIQUE (clinic_id, idempotency_key)`; a replay with an identical request hash returns the original
  appointment, a different hash returns `409 IDEMPOTENCY_CONFLICT`.
- The API reports `confirmed` only after the transaction commits.
- Every booking foreign key is composite `(clinic_id, id)`, so an appointment cannot reference
  another clinic's patient, dentist or appointment type even if application code is wrong.

## Revision 2026-10-31: published `appointment_slots`
The revised build specification lists `appointment_slots` as a table to implement. The original
decision computed availability directly from `dentist_schedules`. It now reads from published slots:

| Concern | Decision |
|---|---|
| What a slot is | A bookable block of one dentist's time in UTC, generated from `dentist_schedules` for a rolling horizon in the clinic's timezone |
| Overlap | `appointment_slots` has its own exclusion constraint, so a dentist's published blocks cannot overlap |
| Blocking time | `status = 'blocked'` withdraws a block (holiday, training) without touching schedules |
| Availability | Open slots whose time does not overlap an active appointment |
| Double booking | Still decided only by the `appointments` exclusion constraint. Slots are the calendar, not the lock: two requests for the same slot race on that constraint and exactly one wins |

## Consequences
The database is the single arbiter. A losing concurrent request receives `409 BOOKING_SLOT_TAKEN`.
Two inserts racing on the exclusion constraint can deadlock: each finds the other's uncommitted row
and waits for it, and PostgreSQL aborts one (SQLSTATE `40P01`). As PostgreSQL recommends, the
aborted transaction is run again in full (bounded: four attempts, with jitter). The retry sees the
committed winner, so the loser still receives `409 BOOKING_SLOT_TAKEN`; if every attempt is
aborted, `409 CONCURRENT_UPDATE`, never a 500. (Added 2026-10-31 after the deadlock appeared in
concurrency tests under load.)
Slots must be regenerated when schedules change (a service operation, Milestone 6). Tests must run
against PostgreSQL.

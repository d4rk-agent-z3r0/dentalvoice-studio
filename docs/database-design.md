# Database Design

> Status: **Implemented.** Alembic revisions `293745f95565` (core schema, Milestone 2) and
> `7c1e2a9d4b10` (intake `not_provided`, Milestone 3). `ws_tickets` arrives with Milestone 8.

## Conventions

| Rule | Detail |
|---|---|
| Primary keys | `uuid` generated in the application (UUIDv7, `app/core/ids.py`, for index locality) |
| Timestamps | `timestamptz`, stored in UTC. Every table has `created_at`; mutable tables also have `updated_at`. Append-only tables (`conversation_turns`, `conversation_events`, `intake_snapshots`, `audit_events`) have no `updated_at`. |
| Tenancy | Every clinic-owned table has `clinic_id NOT NULL`. Child rows reference parents through **composite foreign keys `(clinic_id, parent_id)`**, so the database rejects a row linking two clinics' data. |
| Naming | snake_case plural tables; constraints named by the SQLAlchemy naming convention (`pk_`, `fk_`, `uq_`, `ck_`, `ix_`) plus explicit `ex_` exclusion constraints |
| Enums | `varchar` + named `CHECK` constraints generated from the Python `StrEnum` (cheaper to migrate than native enums) |
| Migrations | Alembic only. `tests/integration/test_migrations.py` proves upgrade → models match (no autogenerate diff) → downgrade leaves nothing → upgrade again |

## Entities

| Table | Purpose | Key columns / constraints |
|---|---|---|
| `clinics` | Fictional clinic tenant | `name`, `slug` (uq, kebab-case CHECK), `timezone` (IANA, validated by the service layer) |
| `users` | Dashboard identity | `email` (uq, reserved-domain CHECK), `password_hash` (argon2id, Milestone 8), `is_active` |
| `clinic_users` | Membership + role | (`clinic_id`,`user_id`) uq, `role` ∈ {`admin`,`staff`,`viewer`} |
| `dentists` | Fictional providers | `clinic_id`, `display_name`, `is_active` |
| `dentist_schedules` | Weekly working hours | `(clinic_id, dentist_id)` FK, `weekday` 0–6 (Monday = 0), `start_local` < `end_local` (clinic-local `time`) |
| `appointment_types` | Service catalogue | `code` (uq per clinic), `duration_minutes` > 0 and a multiple of 15 |
| `appointment_slots` | Published bookable calendar (ADR-0004 revision) | `(clinic_id, dentist_id)` FK, `starts_at` < `ends_at` (UTC), `status` ∈ {`open`,`blocked`}, exclusion constraint: one dentist's slots never overlap |
| `synthetic_personas` | Generated caller identities | names, reserved contact CHECKs, `preferred_contact_channel`, `patient_type`, `background` |
| `synthetic_scenarios` | Scenario definition | `code` A–Z (uq per clinic), `(clinic_id, persona_id)` FK, `objective`, `clips` (jsonb array of fixture IDs), `expected` (jsonb object, `ScenarioExpectation` schema) |
| `patients` | Synthetic patient record | names, contact fields (reserved CHECKs, at least one present), `patient_type`, `status` ∈ {`prospective`,`registered`,`archived`}; **duplicate detection**: unique per clinic on `lower(email)` and on `phone` |
| `conversations` | One simulated call | `(clinic_id, scenario_id)` and `(clinic_id, patient_id)` FKs, `state` (12 states), `state_version` ≥ 1 (optimistic lock), `provider_mode`, `turn_count`, `started_at`, `ended_at`; CHECK: `ended_at` is set **iff** the state is terminal |
| `conversation_turns` | Committed utterances | `seq` (uq per conversation), `speaker` ∈ {`caller`,`receptionist`}, `text`, `clip_id`, non-negative `stt_ms`/`llm_ms`/`tts_ms`/`total_ms` |
| `conversation_events` | Append-only timeline | `type` (`state_changed`, `field_proposed`, `field_rejected`, `provider_error`, `escalated`, …), `payload` jsonb object |
| `intake_drafts` | Per-field proposals with provenance | `field`, `value`, `status` ∈ {`provided`,`not_provided`,`needs_confirmation`,`confirmed`,`rejected`,`superseded`}, `(clinic_id, source_turn_id)` FK, `confidence` 0–1; CHECKs: rejected **iff** `rejection_reason`, `not_provided` **iff** no value; partial unique: at most one live value per field. A field never mentioned has no row; a declined one has a `not_provided` row |
| `intake_snapshots` | Immutable confirmed intake, separate from drafts | `conversation_id` (uq), `data` jsonb object, `confirmed_at` |
| `appointments` | Booking | composite FKs to patient, dentist, appointment type, conversation and `rescheduled_from`; `status` ∈ {`requested`,`confirmed`,`cancelled`,`rescheduled`}; `idempotency_key` (8–128 chars), `request_hash` |
| `ws_tickets` | Single-use WS auth (Milestone 8) | `jti` (pk), `user_id`, `clinic_id`, `conversation_id`, `expires_at`, `used_at` |
| `audit_events` | Security-relevant actions | `clinic_id` (nullable: pre-auth events), `actor_user_id`, `action`, `resource_type`, `resource_id`, `request_id`; identifiers only, no free text |

## Integrity guarantees

```sql
-- No overlapping active appointments for one dentist (ADR-0004)
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE appointments ADD CONSTRAINT ex_appointments_dentist_no_overlap
  EXCLUDE USING gist (dentist_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)
  WHERE (status IN ('confirmed', 'requested'));

-- Published slots for one dentist never overlap
ALTER TABLE appointment_slots ADD CONSTRAINT ex_appointment_slots_dentist_no_overlap
  EXCLUDE USING gist (dentist_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&);

-- Idempotent booking per clinic
ALTER TABLE appointments ADD CONSTRAINT uq_appointments_clinic_id_idempotency_key
  UNIQUE (clinic_id, idempotency_key);

-- Cross-tenant references are impossible: e.g.
ALTER TABLE appointments ADD FOREIGN KEY (clinic_id, patient_id) REFERENCES patients (clinic_id, id);
```

Contact columns on `users`, `synthetic_personas` and `patients` carry `CHECK` constraints that only
accept `example.com|example.org|example.net` emails and `+1-555-0100`–`+1-555-0199` phone numbers
(patterns in `app/domain/contact.py`, shared with Pydantic validation). A real contact value cannot
be stored even by a buggy code path.

## Availability

Published `appointment_slots` are the calendar; availability is open slots minus active
appointments. Double booking is still decided only by the `appointments` exclusion constraint.
See the ADR-0004 revision for why the table was added.

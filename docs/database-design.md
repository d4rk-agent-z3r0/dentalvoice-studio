# Database Design

> Status: **Proposed (Milestone 1)** — implemented in Milestone 2 (core) and Milestone 6 (booking).

## Conventions

| Rule | Detail |
|---|---|
| Primary keys | `uuid` generated in the application (`uuid7` for index locality) |
| Timestamps | `timestamptz`, stored in UTC; every table has `created_at`, mutable tables have `updated_at` |
| Tenancy | Every clinic-owned table has `clinic_id NOT NULL` FK + an index leading with `clinic_id` |
| Naming | snake_case plural tables; constraint names via SQLAlchemy naming convention (`pk_`, `fk_`, `uq_`, `ck_`, `ix_`, `ex_`) |
| Enums | PostgreSQL `text` + `CHECK` constraints (cheaper to migrate than native enums) |
| Migrations | Alembic only; no `create_all` outside throwaway tests |

## Entities

| Table | Purpose | Key columns / constraints |
|---|---|---|
| `clinics` | Fictional clinic tenant | `name`, `slug` (uq), `timezone` (IANA, validated) |
| `users` | Dashboard identity | `email` (uq, `example.*` domains in seed), `password_hash` (argon2id), `is_active` |
| `clinic_users` | Membership + role | (`clinic_id`,`user_id`) uq, `role` ∈ {`admin`,`staff`,`viewer`} |
| `dentists` | Fictional providers | `clinic_id`, `display_name` |
| `dentist_schedules` | Weekly working hours | `dentist_id`, `weekday` 0–6, `start_local`, `end_local` (clinic-local `time`), ck start < end |
| `appointment_types` | Service catalogue | `clinic_id`, `code` (uq per clinic), `duration_minutes` ck > 0 |
| `synthetic_personas` | Generated caller identities | `clinic_id`, names, reserved contact values (`@example.com`, `+1-555-01xx`) |
| `synthetic_scenarios` | Scenario definition | `clinic_id`, `code` (A–E), `persona_id`, `objective`, `expected` (jsonb), `clips` (jsonb ordered list of fixture IDs) |
| `patients` | Synthetic patient record created/updated from a confirmed snapshot | `clinic_id`, `persona_id` nullable, normalised names, contact fields, `status` |
| `conversations` | One simulated call | `clinic_id`, `scenario_id`, `patient_id` nullable, `state`, `state_version` (optimistic lock), `provider_mode`, `started_at`, `ended_at`, `turn_count` |
| `conversation_turns` | Committed utterances | `conversation_id`, `seq` (uq per conv), `speaker` ∈ {`caller`,`receptionist`}, `text`, `stt_ms`, `llm_ms`, `tts_ms`, `total_ms` |
| `conversation_events` | Append-only timeline | `conversation_id`, `type` (state_changed, field_proposed, field_rejected, provider_error, escalated, …), `payload` jsonb |
| `intake_drafts` | Per-field proposals with provenance | `conversation_id`, `field`, `value`, `status` ∈ {`provided`,`needs_confirmation`,`confirmed`,`rejected`,`superseded`}, `source_turn_id`, `confidence`, `rejection_reason` |
| `intake_snapshots` | Immutable confirmed intake | `conversation_id` (uq), `data` jsonb validated by `IntakeSnapshot` schema, `confirmed_at` |
| `appointments` | Booking | `clinic_id`, `patient_id`, `dentist_id`, `appointment_type_id`, `starts_at`, `ends_at`, `status` ∈ {`requested`,`confirmed`,`cancelled`,`rescheduled`}, `idempotency_key`, `conversation_id` nullable |
| `ws_tickets` | Single-use WS auth | `jti` (pk), `user_id`, `clinic_id`, `conversation_id`, `expires_at`, `used_at` |
| `audit_events` | Security-relevant actions | `clinic_id`, `actor_user_id`, `action`, `resource_type`, `resource_id`, `request_id` — no free-text PII |

## Integrity guarantees

```sql
-- No overlapping active appointments for one dentist (ADR-0004)
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE appointments ADD CONSTRAINT ex_appointments_dentist_no_overlap
  EXCLUDE USING gist (dentist_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)
  WHERE (status IN ('requested', 'confirmed'));

-- Idempotent booking per clinic
ALTER TABLE appointments ADD CONSTRAINT uq_appointments_clinic_idempotency
  UNIQUE (clinic_id, idempotency_key);
```

`synthetic_*` / `patients` contact columns carry `CHECK` constraints restricting email domains to
`example.com|example.org|example.net` and phone numbers to the `555-01xx` fictional range, so a real
contact value cannot be stored even by a buggy code path.

## Why computed availability instead of `appointment_slots`

Materialised slot rows duplicate schedule data and must be regenerated whenever durations or hours
change. Availability = schedule windows − active appointments, computed per request; the exclusion
constraint is the final arbiter under concurrency. Documented in ADR-0004.

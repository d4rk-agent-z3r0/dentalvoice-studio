# API Reference

> Status: **Contract (Milestone 1)**. Each endpoint is marked with the milestone that implements it.
> Shipped endpoints are also described by the live OpenAPI schema at `/docs`.

All JSON. All `/api/v1` routes except `auth/login` require `Authorization: Bearer <access token>`.
The active clinic comes **only** from the token's `clinic_id` claim, never from a path, query or body.

## Errors

```json
{ "error": { "code": "BOOKING_SLOT_TAKEN", "message": "That time is no longer available.", "request_id": "…" } }
```

| HTTP | Codes |
|---|---|
| 400 | `VALIDATION_ERROR`, `INVALID_STATE_TRANSITION` |
| 401 | `AUTH_REQUIRED`, `AUTH_INVALID` (with `WWW-Authenticate: Bearer`) |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND` (also returned for other clinics' resources — no existence leak) |
| 409 | `BOOKING_SLOT_TAKEN`, `IDEMPOTENCY_CONFLICT`, `CONVERSATION_CLOSED`, `CONCURRENT_UPDATE`, `DUPLICATE_PATIENT` |
| 429 | `RATE_LIMITED` |
| 502/503 | `PROVIDER_ERROR`, `PROVIDER_UNAVAILABLE`, `AUTH_NOT_CONFIGURED` (503) |

## Health — M1

| Method | Path | Response |
|---|---|---|
| GET | `/health/live` | `200 {"status":"ok"}` — process is up |
| GET | `/health/ready` | `200 {"status":"ok","database":"ok"}` or `503` when the DB is unreachable |

## Auth

Access tokens are HS256 JWTs signed with `JWT_SECRET` (32+ characters; the app refuses shorter
keys). Claims: `sub` (user), `clinic_id`, `role`, `iss`, `aud`, `iat`, `exp`, `jti`. Only `HS256`
is accepted, so unsigned (`alg: none`) and algorithm-confusion tokens are rejected.

| Status | How a token is obtained |
|---|---|
| **Shipped (M3)** | `make dev-token EMAIL=demo.staff@example.com CLINIC=brightsmile`: development only, refuses to run in production; reads the user's real membership and role |
| M8 | `POST /api/v1/auth/login` `{email,password}` → `{access_token, clinics[]}`; `POST /api/v1/auth/switch-clinic`; `GET /api/v1/auth/me` |

Roles: `admin` and `staff` may create and drive conversations; `viewer` is read-only (`403
FORBIDDEN`).

## Scenarios & conversations — shipped in M3

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/api/v1/scenarios` | any | Scenarios of the token's clinic |
| POST | `/api/v1/conversations` | admin, staff | `{scenario_id}` → `201` conversation in `CREATED`. Unknown fields (e.g. `clinic_id`) are a `400` |
| GET | `/api/v1/conversations?state=&limit=` | any | Newest first, `limit` 1–100 |
| GET | `/api/v1/conversations/{id}` | any | Conversation, turns, timeline events, every intake draft (with history), missing fields, snapshot |
| POST | `/api/v1/conversations/{id}/start` | admin, staff | `CREATED → GREETING`; returns the greeting turn |
| POST | `/api/v1/conversations/{id}/turns` | admin, staff | `{text}` (1–500 chars). Typed caller turn for development and tests; **`403` when `ENVIRONMENT=production`**, where caller speech only comes from audio fixtures (M5) |
| POST | `/api/v1/conversations/{id}/end` | admin, staff | Caller hung up: `ABANDONED`; `409 CONVERSATION_CLOSED` if already ended |
| POST | `/api/v1/conversations/{id}/ws-ticket` | admin, staff | M8: `{ticket, expires_in}` (60 s, single use) |
| GET | `/api/v1/audio/clips/{clip_id}` | any | M5: allow-listed fixture audio (`audio/wav`) |

A turn response (`TurnResultRead`) carries `previous_state`, `state`, the full `path` of states
entered in that turn, `state_version`, the receptionist `reply`, `missing_fields`,
`rejected_fields` (field → reason), `corrected_fields` and the measured `llm_ms`.

## WebSocket — M5

`GET /api/v1/ws/conversations/{id}?ticket=…`

| Direction | `type` | Payload |
|---|---|---|
| C→S | `start` | — (server sends greeting) |
| C→S | `next_clip` | — server picks the next scripted clip; the client cannot name arbitrary audio |
| C→S | `end` | — marks `ABANDONED` if not terminal |
| S→C | `state` | `{state, previous}` |
| S→C | `clip` | `{clip_id, url}` — client starts playback |
| S→C | `transcript.interim` | `{turn_seq, text}` — display only, never persisted |
| S→C | `utterance.final` | `{turn_seq, text}` — committed caller turn |
| S→C | `assistant.text` | `{turn_seq, text}` |
| S→C | binary frame | 4-byte big-endian `turn_seq` header + audio chunk |
| S→C | `assistant.audio_end` | `{turn_seq}` |
| S→C | `intake` | field drafts with status/provenance |
| S→C | `latency` | `{turn_seq, stt_ms, llm_ms, tts_first_byte_ms, total_ms}` measured server-side |
| S→C | `error` | `{code, message, provider?}` — surfaced in UI, never swallowed |

## Availability — shipped in M6

`GET /api/v1/availability?appointment_type_id=&date=&days=` · any role

| Parameter | Rules |
|---|---|
| `appointment_type_id` | Required. An active type of the token's clinic; anything else (unknown, inactive, another clinic's) is `404 NOT_FOUND` |
| `date` | Required. First clinic-local day, `YYYY-MM-DD` |
| `days` | Optional, 1–14, default 1 |

A start time is offered when consecutive **open** published slots of one active dentist tile
exactly `[start, start + duration)`, no active (`requested`/`confirmed`) appointment of that dentist
overlaps it, it lies inside the requested local days and it is in the future. Local days are
resolved per date, so a daylight-saving day is 23 or 25 hours long and opening hours stay at the
same wall-clock time. Availability is advisory: a listed time can still be taken by the time it is
booked (`409 BOOKING_SLOT_TAKEN`).

```json
{
  "appointment_type_id": "…", "duration_minutes": 45, "timezone": "Europe/London",
  "first_day": "2030-01-07", "days": 1,
  "slots": [
    { "dentist_id": "…", "dentist_name": "Dr. Ada Example",
      "starts_at": "2030-01-07T09:00:00Z", "ends_at": "2030-01-07T09:45:00Z",
      "starts_at_local": "2030-01-07T09:00:00+00:00", "ends_at_local": "2030-01-07T09:45:00+00:00" }
  ]
}
```

Slots are ordered by start time, then dentist. `starts_at`/`ends_at` are UTC; the `*_local` strings
are the same instants in the clinic's timezone, with their offset.

## Patients, appointments, analytics — M6/M7

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/patients?q=&status=` | Search + filter |
| GET | `/api/v1/patients/{id}` | Profile, snapshots, conversations, appointments |
| GET | `/api/v1/appointments?from=&to=&status=` | |
| POST | `/api/v1/appointments` | Header `Idempotency-Key` required; same key + same body → same result; different body → `409 IDEMPOTENCY_CONFLICT` |
| POST | `/api/v1/appointments/{id}/cancel` | |
| POST | `/api/v1/appointments/{id}/reschedule` | `{starts_at}` atomic cancel-and-create |
| GET | `/api/v1/analytics/summary` | Counts, completion rate, avg duration from persisted data |
| GET | `/api/v1/analytics/latency` | p50/p95 of measured stage timings |

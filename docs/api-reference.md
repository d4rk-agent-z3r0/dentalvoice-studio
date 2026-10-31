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
| 409 | `BOOKING_SLOT_TAKEN`, `SLOT_UNAVAILABLE`, `IDEMPOTENCY_CONFLICT`, `APPOINTMENT_NOT_ACTIVE`, `CONVERSATION_CLOSED`, `CONCURRENT_UPDATE`, `DUPLICATE_PATIENT` |
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

A turn response (`TurnResultRead`) carries `previous_state`, `state`, the full `path` of states
entered in that turn, `state_version`, the receptionist `reply`, `missing_fields`,
`rejected_fields` (field → reason), `corrected_fields` and the measured `llm_ms`.

## Voice — shipped in M5

### Admission

1. `POST /api/v1/conversations/{id}/ws-ticket` (admin, staff) → `{ticket, expires_in: 60}`. The
   conversation must belong to the token's clinic (`404` otherwise) and not have ended (`409`).
2. `GET /api/v1/ws/conversations/{id}?ticket=…` (WebSocket). The ticket is checked **before** the
   handshake is accepted: it must be unused, unexpired and issued for this conversation, and it is
   consumed atomically (a second connection with the same ticket is refused). Rejection is an HTTP
   `403` handshake response. Only a SHA-256 of the ticket is stored, and `ticket=` values are
   redacted from every log line, including the server's own connection log.

`GET /api/v1/audio/clips/{clip_id}` (any role) serves a caller clip as `audio/wav` when the clip
belongs to one of the clinic's scenarios; anything else is `404`. `X-Clip-Source` says whether it
is the committed eSpeak NG fixture or a locally generated Deepgram clip.

### Messages

Client → server: JSON text frames of at most 1 KiB. Binary frames (audio) are refused with
`AUDIO_NOT_ACCEPTED`: caller audio comes only from the scenario's synthetic clips.

| `type` | Meaning |
|---|---|
| `start` | `CREATED → GREETING`; the receptionist greets |
| `next_clip` | The server picks the scenario's next unanswered clip, announces it, and streams it to speech-to-text. While the receptionist is speaking this cancels the speech (barge-in); while a turn is being processed it queues (one command), then `BUSY` |
| `end` | Caller hung up: `ABANDONED` unless already finished; the server closes the socket |

Server → client:

| `type` | Payload |
|---|---|
| `ready` | `{state, audio: {sample_rate, encoding: "linear16", channels}}` — the format of reply audio |
| `clip` | `{clip_id, url, duration_ms}` — play `url` (fetch with the bearer token) |
| `transcript.interim` | `{text}` — provisional, display only, never stored |
| `utterance.final` | `{turn_seq, text}` — the committed caller turn |
| `state` | `{state, previous, path}` — every state entered this turn |
| `assistant.text` | `{turn_seq, text}` |
| binary frame | 4-byte big-endian `turn_seq` + raw PCM in the `ready` format; drop frames for a turn you have moved past |
| `assistant.audio_end` / `assistant.audio_cancelled` | `{turn_seq}` |
| `intake` | `{missing_fields, rejected_fields: {field: reason}, corrected_fields}` |
| `latency` | `{turn_seq, stt_ms, llm_ms, tts_first_byte_ms, total_ms}` measured on the server; `null` when a stage did not happen (the greeting has no STT or LLM stage). Also stored on the turns |
| `closed` | `{state}` — the call ended; the server then closes the socket normally |
| `error` | `{code, message, provider?}` — `NO_SPEECH`, `NO_MORE_CLIPS`, `CONVERSATION_CLOSED`, `INVALID_STATE_TRANSITION`, `INVALID_MESSAGE`, `BUSY`, `AUDIO_NOT_ACCEPTED`, `PROVIDER_ERROR`, `PROVIDER_UNAVAILABLE`. Never swallowed, never replaced by mock output |

Latency definitions: `stt_ms` = end of caller audio → utterance complete; `llm_ms` = the
conversation-model call (all attempts); `tts_first_byte_ms` = synthesis request → first audio
byte; `total_ms` = end of caller audio → first reply audio byte. With `VOICE_REALTIME_FACTOR=1`
(default) caller audio is streamed at its real duration, so these are what a caller would
experience; tests run at `0`.

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

## Appointments — shipped in M6

| Method | Path | Role | Success |
|---|---|---|---|
| GET | `/api/v1/appointments?from=&to=&status=&limit=` | any | `200` list |
| POST | `/api/v1/appointments` | admin, staff | `201` appointment |
| POST | `/api/v1/appointments/{id}/cancel` | admin, staff | `200` appointment (`cancelled`) |
| POST | `/api/v1/appointments/{id}/reschedule` | admin, staff | `201` the **new** appointment |

Every write is one PostgreSQL transaction, and the response is built only after it has committed:
a `2xx` means the database holds the result, and any failure is an error response.

**Appointment** (all responses):

```json
{ "id": "…", "patient_id": "…", "dentist_id": "…", "appointment_type_id": "…",
  "conversation_id": null, "rescheduled_from_id": null, "status": "confirmed",
  "starts_at": "2030-01-07T09:00:00Z", "ends_at": "2030-01-07T09:30:00Z",
  "starts_at_local": "2030-01-07T09:00:00+00:00", "ends_at_local": "2030-01-07T09:30:00+00:00",
  "timezone": "Europe/London", "created_at": "…", "updated_at": "…" }
```

### `POST /api/v1/appointments`

Header `Idempotency-Key`: required, 8–128 characters from `A-Z a-z 0-9 _ -`. Body:

```json
{ "patient_id": "…", "appointment_type_id": "…", "dentist_id": "…",
  "starts_at": "2030-01-07T09:00:00Z", "conversation_id": null }
```

`starts_at` needs an explicit offset (a naive time is a `400`) and is stored in UTC; `ends_at` is
`starts_at` plus the type's duration. Unknown fields such as `clinic_id` are a `400`. The appointment
is created as `confirmed`.

| Outcome | Response |
|---|---|
| Booked | `201` |
| Same key, same body (also when the requests race) | The original appointment, as it is now, `201` with `Idempotent-Replayed: true`. No new row |
| Same key, different body | `409 IDEMPOTENCY_CONFLICT` |
| Another active appointment of that dentist overlaps | `409 BOOKING_SLOT_TAKEN` (the database exclusion constraint decided) |
| The database aborted the transaction to break a deadlock with a concurrent booking, four times in a row | `409 CONCURRENT_UPDATE`; retry with the same key. (One deadlock is retried internally, so it normally ends as one of the rows above) |
| Past, not exactly covered by open published slots, blocked, or dentist inactive | `409 SLOT_UNAVAILABLE` |
| Patient, appointment type (or inactive type), dentist or conversation unknown or another clinic's | `404 NOT_FOUND` naming the resource |
| Viewer | `403 FORBIDDEN` |

The body hash is SHA-256 of the canonical JSON of the validated body (sorted keys, UTC instant,
`conversation_id` always present), so the same instant written with another offset is the same
request. Keys are scoped to the clinic. A request that failed stored nothing, so retrying its key
runs it again.

### Cancel and reschedule

`POST …/{id}/cancel`, no body: `confirmed`/`requested` → `cancelled`; the time becomes bookable
again. `POST …/{id}/reschedule` `{"starts_at": "…"}`: same patient, dentist and type. In one
transaction the original becomes `rescheduled` and a new `confirmed` appointment with
`rescheduled_from_id` is created, so the new time may overlap the old one. If the new time is
taken (`409 BOOKING_SLOT_TAKEN`) or not bookable (`409 SLOT_UNAVAILABLE`), nothing changes. Either
call on an appointment that is no longer active is `409 APPOINTMENT_NOT_ACTIVE`; another clinic's
appointment is `404`.

### List

`from` and `to` are clinic-local days (`YYYY-MM-DD`, both inclusive, `to` ≥ `from`), filtering on
`starts_at`; `status` is one of `requested`, `confirmed`, `cancelled`, `rescheduled`; `limit` 1–200
(default 100). Ordered by `starts_at`.

## Patients, analytics — M7

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/patients?q=&status=` | Search + filter |
| GET | `/api/v1/patients/{id}` | Profile, snapshots, conversations, appointments |
| GET | `/api/v1/analytics/summary` | Counts, completion rate, avg duration from persisted data |
| GET | `/api/v1/analytics/latency` | p50/p95 of measured stage timings |

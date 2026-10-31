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
| 405 | `METHOD_NOT_ALLOWED` |
| 413 | `PAYLOAD_TOO_LARGE` (request bodies are capped at 64 KiB) |
| 401 | `AUTH_REQUIRED`, `AUTH_INVALID`, `AUTH_FAILED` (sign-in) (with `WWW-Authenticate: Bearer`) |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND` (also returned for other clinics' resources — no existence leak) |
| 409 | `BOOKING_SLOT_TAKEN`, `SLOT_UNAVAILABLE`, `IDEMPOTENCY_CONFLICT`, `APPOINTMENT_NOT_ACTIVE`, `CONVERSATION_CLOSED`, `CONCURRENT_UPDATE`, `DUPLICATE_PATIENT` |
| 429 | `RATE_LIMITED` |
| 502/503 | `PROVIDER_ERROR`, `PROVIDER_UNAVAILABLE`, `AUTH_NOT_CONFIGURED` (503) |

Every failure uses this shape, including framework errors (unknown route `404 NOT_FOUND`, wrong
method, oversized body).

## HTTP hardening — M8

| Measure | Detail |
|---|---|
| CORS | Exact origins from `CORS_ORIGINS` only (scheme, host, optional port; no `*`, no path; checked at startup). No credentials mode: auth is a bearer header, never a cookie, so cross-site request forgery has nothing to ride on |
| WebSocket origin | A socket whose `Origin` is not in `CORS_ORIGINS` is refused before the handshake (`403`) and before the ticket is redeemed. Browsers always send `Origin` |
| Response headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`, and `Cache-Control: no-store` unless a route sets its own (clips: `private, max-age=3600`) |
| Request size | Bodies over 64 KiB are refused with `413`, before reading when `Content-Length` says so, otherwise as soon as the count passes the limit |
| API docs | `/docs`, `/redoc` and `/openapi.json` exist outside production only. They are the only paths without the CSP, because Swagger UI needs its scripts |

HSTS belongs to the TLS terminator in front of the API; the app itself serves plain HTTP.

## Health — M1

| Method | Path | Response |
|---|---|---|
| GET | `/health/live` | `200 {"status":"ok"}` — process is up |
| GET | `/health/ready` | `200 {"status":"ok","database":"ok"}` or `503` when the DB is unreachable |

## Auth

Access tokens are HS256 JWTs signed with `JWT_SECRET` (32+ characters; the app refuses shorter
keys). Claims: `sub` (user), `clinic_id`, `role`, `iss`, `aud`, `iat`, `exp`, `jti`. Only `HS256`
is accepted, so unsigned (`alg: none`) and algorithm-confusion tokens are rejected.

Every request re-checks the token's user and membership in the database. A user who was
deactivated, removed from the clinic or given another role since the token was issued gets `401
AUTH_INVALID` at once, not when the token expires.

### Shipped in M8

| Method | Path | Token | Response |
|---|---|---|---|
| POST | `/api/v1/auth/login` | none | `{email, password}` → session (below) |
| POST | `/api/v1/auth/switch-clinic` | yes | `{clinic_id}` → session for that clinic; `403 FORBIDDEN` if not a member |
| GET | `/api/v1/auth/me` | yes | `{user, clinic, role, clinics}`, read from the database |

```json
{ "access_token": "<JWT>", "token_type": "bearer", "expires_in": 3600,
  "user": { "id": "…", "email": "demo.staff@example.com", "display_name": "Demo Staff" },
  "clinic": { "id": "…", "name": "BrightSmile Dental Studio", "timezone": "Europe/London" },
  "role": "staff",
  "clinics": [ { "id": "…", "name": "BrightSmile Dental Studio", "role": "staff" } ] }
```

- `clinics` lists every clinic the user belongs to, sorted by name. Login issues the token for the
  first one; `switch-clinic` issues a new token for another one.
- Sign-in failures are all `401 AUTH_FAILED` "Email or password is incorrect.": unknown email,
  wrong password, inactive user, no password set, no clinic. Each costs the same password check,
  so neither the message nor the timing reveals which accounts exist.
- The email is matched case-insensitively. A malformed body is `400 VALIDATION_ERROR`, which never
  echoes the submitted values. Passwords longer than 128 characters are refused.
- Token responses carry `Cache-Control: no-store`. There is no logout endpoint: tokens are
  short-lived (`JWT_TTL_MINUTES`, default 60), and signing out discards the token in the browser.
- Passwords are stored as argon2id hashes (RFC 9106 low-memory profile). A hash made with older
  parameters is upgraded at the next successful sign-in. Neither passwords nor emails are logged.
- Demo users get a password only from `DEMO_PASSWORD` in your local `.env`, applied by `make seed`.
  No password is committed anywhere.

`make dev-token EMAIL=demo.staff@example.com CLINIC=brightsmile` still issues a token without a
password, for development only. It refuses to run in production.

Roles: `admin` and `staff` may create and drive conversations; `viewer` is read-only (`403
FORBIDDEN`).

### Rate limits — M8

Token buckets in the API process; a refused request is `429 RATE_LIMITED` with a `Retry-After`
header (seconds) and the same value in `error.retry_after_seconds`. A refused request consumes
nothing, so retrying early does not extend the wait.

| What | Key | Default | Setting |
|---|---|---|---|
| Sign-in attempts | client IP (TCP peer; `X-Forwarded-For` is not trusted) | 20 per minute | `RATE_LOGIN_PER_IP_PER_MINUTE` |
| Failed sign-ins | account (email, held only as a hash) | 5 per 15 minutes, then locked even for the right password until a token refills; a successful sign-in clears the count | `RATE_LOGIN_FAILURES_PER_ACCOUNT` |
| Authenticated requests | user | 600 per minute | `RATE_REQUESTS_PER_USER_PER_MINUTE` |
| Writes (every admin/staff route, including WebSocket tickets) | user | 120 per minute | `RATE_WRITES_PER_USER_PER_MINUTE` |

Only a validly signed token reaches the per-user buckets. `RATE_LIMITS_ENABLED=false` turns them
all off (for load tests only). The state is per process: running several API replicas would need a
shared store (docs/security/threat-model.md).

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
| `error` | `{code, message, provider?}` — `NO_SPEECH`, `NO_MORE_CLIPS`, `CONVERSATION_CLOSED`, `INVALID_STATE_TRANSITION`, `INVALID_MESSAGE`, `BUSY`, `AUDIO_NOT_ACCEPTED`, `IDLE_TIMEOUT`, `PROVIDER_ERROR`, `PROVIDER_UNAVAILABLE`. Never swallowed, never replaced by mock output. `IDLE_TIMEOUT`: no command and nothing in progress for `VOICE_IDLE_TIMEOUT_SECONDS` (default 300); the socket closes normally and the call resumes on a new socket |

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

## Clinic — shipped in M7

`GET /api/v1/clinic` · any role · the token's clinic (there is no clinic id in the path)

```json
{ "id": "…", "name": "BrightSmile Dental Studio", "timezone": "Europe/London", "today": "2026-10-31",
  "appointment_types": [
    { "id": "…", "code": "checkup", "name": "Check-up", "duration_minutes": 30, "is_active": true } ],
  "dentists": [ { "id": "…", "display_name": "Dr. Ada Example", "is_active": true } ] }
```

`today` is the current calendar day in the clinic's timezone. Types are ordered by name and dentists
by display name. Inactive ones are included, flagged, so existing appointments can still be
described; only active ones are bookable. This is the reference data the appointment screens need
to pick a type and to name the dentist and type of an appointment, which `Appointment` carries as
ids only.

## Patients — shipped in M7

Read only. Patients are created or matched by the conversation engine when a call completes with a
confirmed intake; there is no create or update endpoint.

| Method | Path | Role | Success |
|---|---|---|---|
| GET | `/api/v1/patients?q=&status=&limit=&offset=` | any | `200` list of `PatientRead` |
| GET | `/api/v1/patients/{id}` | any | `200` `PatientDetail`; another clinic's or unknown id `404 NOT_FOUND` (`Patient not found.`) |

List parameters: `q` (≤ 254 characters, trimmed; blank means no search) matches first name, last
name, the full name ("Ava Lindqvist") or email, case-insensitively, with `%`, `_` and `\` taken
literally (phone numbers are not a search key); `status` is one of `prospective`, `registered`,
`archived`; `limit` 1–100 (default 50); `offset` 0–10000. Ordered by last name, first name, then
id, so pages are stable.

**PatientRead:**

```json
{ "id": "…", "first_name": "Ava", "last_name": "Lindqvist", "email": "ava.lindqvist@example.com",
  "phone": "+1-555-0101", "preferred_contact_channel": "email", "patient_type": "new",
  "status": "registered", "created_at": "…", "updated_at": "…" }
```

**PatientDetail:**

```json
{
  "patient": { "…": "PatientRead" },
  "conversations": [
    { "id": "…", "scenario_id": "…", "state": "COMPLETED", "provider_mode": "mock", "turn_count": 17,
      "started_at": "…", "ended_at": "…", "created_at": "…",
      "snapshot_confirmed_at": "2026-10-31T12:03:10Z" }
  ],
  "appointments": [ { "…": "Appointment, as in the booking API" } ],
  "latest_snapshot": {
    "conversation_id": "…", "confirmed_at": "…", "patient_type": "new",
    "preferred_contact_channel": "email", "visit_reason": "Routine cleaning",
    "requested_service": "hygiene_cleaning", "preferred_date": "2026-11-03", "preferred_time": "10:00:00"
  }
}
```

`conversations` are the calls linked to the patient (`conversations.patient_id`), newest first;
`snapshot_confirmed_at` is set when that call produced a confirmed intake snapshot. `appointments`
are in every status, latest start first. Each list holds at most 100 rows. `latest_snapshot` is the
most recently confirmed snapshot among the linked calls, without its contact values (those are on
`patient`), or `null`.

## Analytics — shipped in M7

Read only, any role, the token's clinic. Every figure is computed by PostgreSQL from stored rows at
request time; nothing is estimated or defaulted, and `null` means "nothing to measure yet", never 0.

### `GET /api/v1/analytics/summary`

```json
{ "generated_at": "2026-10-31T13:26:45Z", "conversations_total": 6,
  "by_state": { "CREATED": 0, "GREETING": 1, "…": 0, "COMPLETED": 3, "ESCALATED": 1, "ABANDONED": 1 },
  "in_progress": 1, "ended": 5, "completed": 3, "escalated": 1, "abandoned": 1,
  "completion_rate": 0.6, "average_duration_seconds": 0.234, "duration_samples": 5,
  "escalation_reasons": [ { "reason": "urgent_symptoms", "count": 1 } ] }
```

| Field | Definition |
|---|---|
| `by_state` | Conversations per state; every state is present (a real zero count is `0`) |
| `ended` / `in_progress` | Terminal (`COMPLETED`, `ESCALATED`, `ABANDONED`) / all other states |
| `completion_rate` | `completed / ended`; `null` while no call has ended |
| `average_duration_seconds` | Mean of `ended_at - started_at` over the `duration_samples` calls that have both (a call hung up before it started has no duration); `null` when there are none |
| `escalation_reasons` | `escalated` timeline events grouped by `payload.reason`, most frequent first |

The figures are read in one `REPEATABLE READ` transaction, so they are consistent with each other.

### `GET /api/v1/analytics/latency?provider_mode=`

```json
{ "generated_at": "…", "provider_mode": null,
  "stages": [
    { "stage": "stt", "samples": 0, "p50_ms": null, "p95_ms": null },
    { "stage": "llm", "samples": 34, "p50_ms": 0.0, "p95_ms": 0.35 },
    { "stage": "tts", "samples": 0, "p50_ms": null, "p95_ms": null },
    { "stage": "total", "samples": 0, "p50_ms": null, "p95_ms": null } ] }
```

`p50_ms`/`p95_ms` are `percentile_cont(0.5|0.95)` (linear interpolation) over the non-null
`stt_ms`, `llm_ms`, `tts_ms` and `total_ms` of the clinic's `conversation_turns`; `samples` is the
number of measurements. A stage with no measurement has `samples: 0` and `null` percentiles. Typed
text turns record only `llm_ms`; `stt`, `tts` and `total` appear once Milestone 5 streams audio. Optional
`provider_mode` (`mock` or `live`) limits the turns to calls run with that provider; anything else
is `400`.

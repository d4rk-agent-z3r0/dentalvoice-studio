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
| 401 | `AUTH_REQUIRED`, `AUTH_INVALID` |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND` (also returned for other clinics' resources — no existence leak) |
| 409 | `BOOKING_SLOT_TAKEN`, `IDEMPOTENCY_CONFLICT`, `CONVERSATION_CLOSED` |
| 429 | `RATE_LIMITED` |
| 502/503 | `PROVIDER_ERROR`, `PROVIDER_UNAVAILABLE` |

## Health — M1

| Method | Path | Response |
|---|---|---|
| GET | `/health/live` | `200 {"status":"ok"}` — process is up |
| GET | `/health/ready` | `200 {"status":"ok","database":"ok"}` or `503` when the DB is unreachable |

## Auth — M8 (dev token stub in M2 tests)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/auth/login` | `{email,password}` → `{access_token, clinics[]}` (first membership active) |
| POST | `/api/v1/auth/switch-clinic` | `{clinic_id}` → new token, only if the user is a member |
| GET | `/api/v1/auth/me` | user, active clinic, role |

## Scenarios & conversations — M2/M3/M5

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/scenarios` | Scenarios for the active clinic |
| POST | `/api/v1/conversations` | `{scenario_id}` → conversation in `CREATED` |
| GET | `/api/v1/conversations?state=&limit=&cursor=` | Paginated list |
| GET | `/api/v1/conversations/{id}` | Turns, events, intake drafts, snapshot |
| POST | `/api/v1/conversations/{id}/turns` | Text turn for mock/dev (M3); `{text}` only allowed when `ENVIRONMENT=development` |
| POST | `/api/v1/conversations/{id}/ws-ticket` | → `{ticket, expires_in}` (60 s, single use) |
| GET | `/api/v1/audio/clips/{clip_id}` | Allow-listed fixture audio (`audio/wav`) |

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

## Patients, appointments, analytics — M6/M7

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/patients?q=&status=` | Search + filter |
| GET | `/api/v1/patients/{id}` | Profile, snapshots, conversations, appointments |
| GET | `/api/v1/availability?appointment_type_id=&date=` | Slots in clinic-local time + UTC |
| GET | `/api/v1/appointments?from=&to=&status=` | |
| POST | `/api/v1/appointments` | Header `Idempotency-Key` required; same key + same body → same result; different body → `409 IDEMPOTENCY_CONFLICT` |
| POST | `/api/v1/appointments/{id}/cancel` | |
| POST | `/api/v1/appointments/{id}/reschedule` | `{starts_at}` atomic cancel-and-create |
| GET | `/api/v1/analytics/summary` | Counts, completion rate, avg duration from persisted data |
| GET | `/api/v1/analytics/latency` | p50/p95 of measured stage timings |

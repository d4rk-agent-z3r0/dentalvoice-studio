# DentalVoice Studio — Architecture

> Status: **Proposed (Milestone 1)**. Sections marked *planned* describe intended design, not shipped code.
> Every claim of working behaviour lives in `docs/verification-report.md` with command evidence.

## 1. Repository assessment (2026-10-30)

| Item | Finding | Consequence |
|---|---|---|
| Existing code | None. Fresh directory, no git history. | Greenfield; nothing to preserve or migrate. |
| Existing secrets | None present. | `.gitignore` + `.env.example` placeholders from the first commit. |
| Python / uv | 3.13.18 / uv 0.11.32 | Target `requires-python >=3.12`; dev and CI on 3.13. |
| Node / pnpm | 22.23.4 / pnpm 10.28.0 | pnpm for the frontend (strict, fast lockfile). |
| PostgreSQL | 16.15 server binaries; Docker can pull `postgres:16` | Integration tests run against real PostgreSQL, never SQLite. |
| Docker | Engine 29.9.2, Compose v5.6.1 | `docker compose up` is verifiable in this environment. |
| Ownership / licensing | Independently authored by Siddharth Majhi. No employer, client, university or NDA material. | Recorded in `PROJECT_ELIGIBILITY.md`. |

Current stable versions checked against PyPI and npm on 2026-10-30:
FastAPI 0.162, Pydantic 2.14, SQLAlchemy 2.1, Alembic 1.20, asyncpg 0.32, pytest 9.2,
Ruff 0.17, mypy 2.4, google-genai 2.34, deepgram-sdk 7.16, Next.js 16.4, React 19.3,
Tailwind 4.3, Recharts 3.10, Vitest 5.0, Playwright 1.64.

## 2. Assumptions

| # | Assumption | Why it is safe / how to revisit |
|---|---|---|
| A1 | The demo is operated by an authenticated clinic user; there is no anonymous public simulator. | Spec requires dashboard auth and WebSocket auth. A public "guest" mode can be added later as a read-only role. |
| A2 | The "caller" is scripted: each scenario is an ordered list of pre-recorded clips. | No microphone by design. The receptionist (LLM) adapts; the caller does not. See R3. |
| A3 | Patient audio is played by the browser from a static URL while the **server** streams the same fixture file to STT. | Enforces "all STT audio originates from fixtures" structurally (ADR-0002). |
| A4 | One modular monolith process serves REST + WebSocket. | Demo concurrency is tiny. No Redis/Celery until a requirement appears. |
| A5 | Clinic timezones are fictional but real IANA zones (e.g. `Asia/Kolkata`, `Europe/London`). | Exercises DST and offset handling in booking tests. |
| A6 | Live-provider credentials are supplied by the developer through environment variables, never through the repo or chat. | Mock mode is the default and needs no credentials. |

## 3. Logical architecture

```
Browser (Next.js)                         FastAPI modular monolith                      External
─────────────────                         ────────────────────────                      ────────
Scenario picker ──REST──▶ api/v1 ──▶ services (conversations, booking, intake) ──▶ PostgreSQL
Audio <audio> ◀─static── /audio/clips/{clip_id}   (allow-listed fixture files)
Simulator UI ◀══WS══▶ ws/conversations/{id}
                          │
                          ▼
                  VoiceSession (per WS connection)
                    ├─ FixtureAudioSource ── reads clip from demo_data/audio
                    ├─ SpeechToTextProvider ───────────────────────────────────▶ Deepgram STT (or mock)
                    ├─ UtteranceAssembler (interim vs final, endpointing)
                    ├─ ConversationOrchestrator
                    │    ├─ ConversationModelProvider ─────────────────────────▶ Gemini (or mock)
                    │    ├─ ProposalValidator  (schema + business semantics)
                    │    ├─ IntakeService      (drafts, provenance, corrections)
                    │    └─ StateMachine       (deterministic transitions)
                    └─ TextToSpeechProvider ───────────────────────────────────▶ Deepgram Aura (or mock)
```

**Core rule:** the LLM *proposes*, the application *disposes*. A model turn returns a
`TurnProposal` (response text, field updates, a bounded `next_action`, escalation flag).
It never names a target state, never writes to the database and has no tools. The
orchestrator validates the proposal, applies accepted field updates through `IntakeService`,
computes the next state from intake completeness + the validated action, and persists
everything in one transaction per turn.

## 4. Component responsibility map

| Component | Package | Owns | Must not |
|---|---|---|---|
| API routers | `app/api/v1` | HTTP/WS transport, auth dependency, DTO mapping | Contain business rules |
| Auth | `app/core/security`, `app/services/auth` | Password hashing (argon2), JWT issue/verify, clinic membership | Trust a clinic ID from the client |
| Domain | `app/domain` | Enums, value objects, state transition table, domain exceptions | Import FastAPI or SQLAlchemy |
| Models | `app/models` | SQLAlchemy tables, constraints | Hold behaviour beyond simple properties |
| Repositories | `app/repositories` | Clinic-scoped queries (every query takes `clinic_id`) | Commit transactions |
| Services | `app/services` | Use cases + transaction boundaries (`async with uow:`) | Call providers directly except via injected interfaces |
| Orchestrator | `app/orchestrators` | One conversation turn end-to-end | Know about WebSocket framing |
| State machine | `app/state_machine` | Allowed transitions, guard conditions | Be influenced by free-text model output |
| Intake | `app/services/intake` | Field validation, normalisation, provenance, corrections, snapshot | Guess missing values |
| Booking | `app/services/booking` | Availability, reservation, idempotency, cancel/reschedule | Report "confirmed" before commit |
| Integrations | `app/integrations/{speech_to_text,text_to_speech,llm}` | Provider adapters + mocks behind Protocols | Leak provider types past the interface |
| Voice session | `app/orchestrators/voice_session` | Per-connection pipeline, ordering, cancellation, latency timing | Persist anything except via services |
| Observability | `app/core/logging`, `app/middleware` | JSON logs, request/conversation IDs, redaction | Log transcripts or contact values at INFO |

## 5. Key decisions (full ADRs in `docs/decisions/`)

| ADR | Decision | Trade-off accepted |
|---|---|---|
| 0001 | Modular monolith, single FastAPI process | Horizontal scale of WS sessions deferred; documented as roadmap |
| 0002 | Server-side fixture streaming: client sends `{"type":"next_clip"}`, never audio bytes | Diverges from spec diagram's "frontend → WS → STT" audio path; gains a hard guarantee no arbitrary audio reaches STT |
| 0003 | LLM proposes, deterministic services decide; no model tools | Less "agentic" flexibility; far stronger safety and testability |
| 0004 | Double booking prevented by a PostgreSQL `EXCLUDE USING gist` constraint on `(dentist_id, tstzrange)` + idempotency keys, availability computed from schedules rather than materialised slot rows | Requires `btree_gist`; the DB is the source of truth instead of app-level locking |
| 0005 | Mock providers are first-class (rule-based receptionist, scripted STT events incl. interim/final splits, generated-tone TTS) and selected explicitly by `VOICE_PROVIDER_MODE`; a live failure surfaces as an error, never a silent mock fallback | Mock receptionist is less fluent than Gemini |
| 0006 | Short-lived, single-use WebSocket tickets bound to `(user, clinic, conversation)` | Extra REST round-trip before connecting |

## 6. Risk assessment

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Deepgram / Gemini API or model IDs change after knowledge cutoff | Med | High | Model IDs in config; verify against official docs at M4/M5; contract tests on recorded payload shapes |
| R2 | Gemini returns malformed or policy-violating JSON | High | Med | `response_schema` + Pydantic validation, bounded retry, then explicit `ESCALATED`/error turn — never silent acceptance |
| R3 | Scripted caller drifts from a live LLM's question order | High | Med | Clips answer the *topic* of a scenario step, intake accepts out-of-order fields; deterministic acceptance tests run in mock mode; live runs assert final outcomes, not exact wording |
| R4 | Double booking under concurrency | Med | High | DB exclusion constraint + concurrent integration tests with real PostgreSQL |
| R5 | Prompt injection inside caller speech | Med | Med | Utterances passed as quoted data; proposals validated independently; no tools; injection fixture in tests |
| R6 | Tenant data leakage | Low | High | Clinic ID only from token; repository signatures require `clinic_id`; cross-clinic tests on every resource |
| R7 | Stale TTS audio after turn change | Med | Low | Turn-sequence IDs on every audio frame; client drops frames for old turns; server cancels in-flight TTS task |
| R8 | Scope: ~45 verified commits is multi-session work | High | Med | Vertical milestones, each leaving `main`-mergeable state; progress tracked in `docs/verification-report.md` |
| R9 | Live provider keys unavailable for verification | Med | Med | Mock mode fully functional; live-mode checks recorded as *blocked* rather than claimed |

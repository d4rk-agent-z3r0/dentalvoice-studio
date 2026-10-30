# Implementation Plan & Git Strategy

## Branching

| Rule | Practice |
|---|---|
| Working branch | `feat/dentalvoice-studio` (created before the first commit) |
| Remote | None until explicitly approved; no pushes otherwise |
| Commits | Conventional Commits `<type>(<scope>): <description>`; one logically complete, verified feature per commit |
| Pre-commit | Never bypassed (`--no-verify` is forbidden); no amends or history rewrites without instruction |
| Gate before each commit | relevant tests → lint → typecheck → `git diff --staged` review → secret scan → stage named paths only → `git log -1` |
| Milestone close | `git status --short` clean, `git log --oneline -5`, evidence appended to `docs/verification-report.md` |

The baseline commit list in the build spec is followed where the work matches it; commits are split
or merged only when the real change set justifies it, and any deviation is noted in the milestone report.

## Milestones

| # | Milestone | Acceptance evidence |
|---|---|---|
| 1 | Foundation: monorepo, backend + frontend scaffolding, health checks, Compose, CI | `docker compose up` → `/health/ready` 200 with DB; frontend page served; lint/type/test green |
| 2 | Domain & persistence: models, migrations, seed of 2 clinics + 5 scenarios, clinic-scoped repositories | Migration up/down test; CRUD via services; cross-clinic test fails closed |
| 3 | Conversation engine: state machine, orchestrator, intake extraction, mock receptionist | Full onboarding completes in mock mode via the text-turn API, all 5 scenarios |
| 4 | Gemini: adapter, versioned prompt, structured output, retry/timeout, token + latency capture | Contract tests green; live run recorded **only if** a key is provided |
| 5 | Voice: fixtures, Deepgram STT/TTS adapters, WS session, transcript assembly, cancellation | Mock-mode WS scenario passes end-to-end; live run recorded only with keys |
| 6 | Booking: availability, reservation, exclusion constraint, idempotency, cancel/reschedule | Concurrency test: N parallel bookings → exactly 1 succeeds |
| 7 | Frontend: landing, simulator, patients, appointments, analytics | RTL tests + browser-verified flows against real API |
| 8 | Security: auth, RBAC, WS tickets, LLM output restrictions, redaction, rate limits | Security suite green; threat model doc |
| 9 | Polish: walkthrough, docs, loading/error/empty states, screenshots | Fresh-clone README run succeeds |
| 10 | Final verification: E2E for all scenarios, `make verify` in CI, release report | `make verify` exit 0 or failures documented as blockers |

## What is deliberately *not* built

Redis, Celery, Kafka, Kubernetes, microservices, n8n, real SMS/email, external calendars, microphone
input, file uploads, model benchmarking. Each would need a documented requirement first.

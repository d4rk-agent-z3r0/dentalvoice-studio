# Testing Strategy

## Layers

| Layer | Tooling | Scope | Runs against |
|---|---|---|---|
| Unit | pytest, pytest-asyncio | State machine, intake validation/normalisation, proposal validator, utterance assembler, slot computation, timezone maths, mock providers | Pure Python, no I/O |
| Contract | pytest + recorded payloads | Provider adapters translate real Deepgram/Gemini message shapes into our domain types; failure shapes (timeouts, 4xx/5xx, malformed JSON) | Fixtures under `tests/contract/payloads/` |
| Integration | pytest + HTTPX + real PostgreSQL | Migrations up/down, database constraints, repositories, services, REST, WebSocket, tenant isolation, concurrent booking | `TEST_DATABASE_URL`, rebuilt with Alembic (downgrade to base, upgrade to head) at session start. Tests isolate themselves by creating their own clinics, so services commit for real. Migration tests use throwaway scratch databases. |
| Frontend unit | Vitest + React Testing Library | Scenario selection, transcript rendering, interim vs final display, error/loading/empty states | jsdom |
| E2E | Playwright | All five scenarios in mock mode; assert UI **and** persisted DB state via the API | `docker compose` stack |

SQLite is never used as a stand-in for PostgreSQL: exclusion constraints, `timestamptz`, jsonb and
isolation behaviour are the things under test.

## Must-have cases

| Area | Cases |
|---|---|
| State machine | every allowed transition; every disallowed transition raises; terminal states are sticky; recovery reloads persisted state |
| Intake | explicit vs missing vs needs-confirmation vs rejected; correction supersedes prior value with provenance; no guessed values; non-reserved email/phone rejected |
| LLM output | invalid JSON, schema-valid but semantically invalid (unknown field, past date, state-skipping action), injection attempt in caller text, retry then explicit failure |
| Voice | interim never committed; multiple finals concatenated in order; endpointing; provider error mid-stream; client disconnect cancels TTS; stale-turn audio dropped |
| Booking | overlap rejected by DB; 20 concurrent requests for one slot → exactly one succeeds; idempotent replay; DST boundary in `Europe/London` |
| Security | cross-clinic access returns 404 for every resource type; WS ticket replay rejected; expired ticket rejected; role checks |

## Gates

| Command | Does |
|---|---|
| `make lint` | ruff check + ruff format --check + eslint |
| `make typecheck` | mypy --strict + tsc --noEmit |
| `make test` | backend unit + contract, frontend unit |
| `make test-integration` | backend integration against PostgreSQL |
| `make test-e2e` | Playwright against the compose stack |
| `make verify` | all of the above; non-zero exit on any failure |

Tests are never edited to match incorrect behaviour, and assertions are never weakened to get green.
Coverage is recorded per milestone in `docs/verification-report.md` together with notable uncovered areas.

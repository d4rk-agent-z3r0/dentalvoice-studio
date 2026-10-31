# CLAUDE.md — working agreement for AI-assisted development

## Project
DentalVoice Studio: synthetic AI voice patient-onboarding simulator. FastAPI modular monolith
(`backend/`), Next.js 16 app (`frontend/`), PostgreSQL. Read `docs/architecture.md` and
`docs/decisions/` before changing structure.

## Non-negotiables
- Synthetic data only. Contact values must be `example.com|org|net` emails or `555-01xx` phones.
- Never add secrets, real personal data or API keys to files, commits or prompts.
- The LLM proposes; deterministic services decide (ADR-0003). No model tools, no model-driven DB writes.
- The clinic/tenant ID comes only from the authenticated token, never from request input.
- Live provider failures surface as errors. Never fall back to mocks silently (ADR-0005).
- Never claim something works without command output proving it.

## Commands
| Task | Command |
|---|---|
| All lint | `make lint` |
| All type checks | `make typecheck` |
| Unit tests (backend + frontend) | `make test` |
| Integration tests (real PostgreSQL) | `make test-integration` (needs `TEST_DATABASE_URL`) |
| Everything | `make verify` |
| Backend dev server | `cd backend && uv run uvicorn app.main:create_app --factory --reload` |
| Frontend dev server | `cd frontend && pnpm dev` |

Next.js 16 differs from older versions: consult `frontend/node_modules/next/dist/docs/` before using
an unfamiliar API (see `frontend/AGENTS.md`).

## Git workflow
- One branch per milestone (`feat/m<N>-<name>`), merged into protected `main` by pull request
  (owner merges, Rebase and merge). Push only with the owner's approval.
- Conventional Commits `<type>(<scope>): <description>`; one verified feature per commit.
- Before committing: relevant tests → lint → typecheck → review `git diff --staged` → stage named paths only.
- Never `--no-verify`, never amend or rewrite history unless asked, never weaken tests to pass.

## Code conventions
- Python: mypy `--strict`, Ruff, Pydantic v2 models at boundaries, `async` DB access, repositories
  take `clinic_id` explicitly, services own transactions.
- TypeScript: `strict`, no `any`, server data via typed API client; no hardcoded business metrics.
- Logs: structured JSON via `app.core.logging`; never log transcripts, contact values or tokens.

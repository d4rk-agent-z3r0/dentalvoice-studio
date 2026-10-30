# Verification Report

Evidence for every claim of working behaviour. Each milestone section lists the commands run and
their actual results. Anything not listed here has not been verified.

## Environment

| Tool | Version |
|---|---|
| Python | 3.13.18 (uv 0.11.32) |
| Node / pnpm | 22.23.4 / 10.28.0 |
| PostgreSQL (tests) | `postgres:16-alpine` container |
| Docker / Compose | 29.9.2 / v5.6.1 |

## Milestone 1 — Foundation

### `chore(project): initialize DentalVoice monorepo`

| Check | Command | Result |
|---|---|---|
| Backend unit tests | `uv run pytest -m "not integration"` | 15 passed |
| Backend integration | `uv run pytest -m integration` (real PostgreSQL 16) | 1 passed — `/health/ready` → 200 |
| Backend coverage | `pytest --cov` | 97 % (147 stmts) |
| Ruff | `ruff check . && ruff format --check .` | clean |
| mypy | `mypy` (strict) | no issues, 20 files |
| Frontend unit | `pnpm test` | 2 passed (demo banner) |
| ESLint | `pnpm lint` (`--max-warnings=0`) | clean |
| tsc | `pnpm typecheck` | clean |
| Next build | `pnpm build` | success, `/` prerendered |

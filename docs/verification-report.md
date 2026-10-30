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

### `build(docker): configure local development services`

| Check | Command | Result |
|---|---|---|
| Images build | `docker build ./backend`, `docker build ./frontend` | both succeed (non-root runtime users, uid 10001) |
| Stack health | `docker compose up -d --wait` | db, backend, frontend all `healthy` |
| Readiness | `curl /health/ready` | `200 {"status":"ok","database":"ok"}` with `x-request-id` header |
| Readiness failure | `docker compose stop db` → `curl /health/ready` | `503 {"status":"unavailable","database":"unavailable"}` |
| Recovery | `docker compose start db` → `curl /health/ready` | back to `200` without restarting backend |
| Frontend | `curl :3000/` | page served with the synthetic-data banner |
| Test DB init | `psql -l` in db container | `dentalvoice_test` created by `scripts/db/init` |
| Integration vs compose DB | `pytest -m integration` with `.env` loaded | 1 passed |
| Structured logs | `docker compose logs backend` | JSON `startup` event with `provider_mode: mock` |

Note: this sandbox's network requires host-network builds plus its proxy CA via the `extra_ca`
build secret; on a normal machine `make up` needs neither.

### `ci(github): add lint and test workflows`

| Check | Command | Result |
|---|---|---|
| Workflow syntax & action inputs | `actionlint .github/workflows/ci.yml` (v1.7.12) | clean (shellcheck not installed, so `run:` scripts not shell-linted) |
| CI database config | backend integration tests against `postgres:16-alpine` with `POSTGRES_HOST_AUTH_METHOD=trust`, URL without password | 1 passed |
| Compose validation step | `docker compose config --quiet` with placeholder password | valid |
| Compose password guard | same, with no password | exits 1 with "set POSTGRES_PASSWORD in .env" |
| Job commands | identical to `make lint`, `make typecheck`, `make test`, `make test-integration`, image builds | all pass locally (sections above) |

**Not yet verified:** an actual GitHub Actions run. That requires pushing to a remote, which waits
for explicit approval. Action versions are pinned to tags confirmed to exist (`checkout@v5`,
`setup-node@v5`, `setup-uv@v8.2.0`, `pnpm/action-setup@v4`); Dependabot keeps them current.

# DentalVoice Studio

> **DEMO ENVIRONMENT — ALL PATIENTS AND CONVERSATIONS ARE SYNTHETIC.**

An AI voice receptionist simulator for fictional dental clinics. Synthetic callers speak through
pre-generated audio; the receptionist transcribes them (Deepgram), reasons over a deterministic
onboarding workflow (Gemini proposes, the application decides), replies with synthesised speech
(Deepgram Aura) and books simulated appointments with database-enforced integrity.

This is an engineering portfolio project — not a healthcare product. See
[PROJECT_ELIGIBILITY.md](PROJECT_ELIGIBILITY.md).

## Status

Under active, milestone-based development. What is verified so far is recorded with command evidence
in [docs/verification-report.md](docs/verification-report.md).

## Quick start with Docker

Requirements: Docker with Compose v2.

```bash
cp .env.example .env          # replace "replace-with-a-local-password" (both occurrences)
make up                       # db + backend + frontend, waits for health checks
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API health | http://localhost:8000/health/ready |
| API docs | http://localhost:8000/docs |

Behind a TLS-inspecting proxy, pass its CA as a BuildKit secret (never stored in an image layer):
`docker build --secret id=extra_ca,src=/path/to/ca.pem ./backend` (same for `./frontend`).

## Development without Docker

Requirements: Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm 10, PostgreSQL 16
(or just `docker compose up -d db`, which also creates the `_test` database).

```bash
make install
make verify                   # lint, types, unit + integration tests
```

## Documentation

| Doc | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Assessment, assumptions, architecture, component map, risks |
| [docs/database-design.md](docs/database-design.md) | Tables, constraints, integrity guarantees |
| [docs/api-reference.md](docs/api-reference.md) | REST + WebSocket contract |
| [docs/testing-strategy.md](docs/testing-strategy.md) | Test layers and quality gates |
| [docs/implementation-plan.md](docs/implementation-plan.md) | Milestones and Git strategy |
| [docs/decisions/](docs/decisions/) | Architecture decision records |

# ADR-0001: Modular monolith

**Status:** Accepted · 2026-10-30

## Context
The product is a single-tenant-per-request demo with tiny concurrency. The interesting engineering is
the voice turn pipeline, state handling and transactional booking — not service decomposition.

## Decision
One FastAPI application serving REST and WebSocket, organised by package boundaries
(`api → services/orchestrators → repositories/integrations → models/domain`). Import direction is
one-way; `domain` imports nothing from the framework.

## Consequences
- One deployable, one database, simple local dev and CI.
- WebSocket sessions are process-local; horizontal scaling would need sticky sessions or a shared
  session store. Recorded on the roadmap, not built.

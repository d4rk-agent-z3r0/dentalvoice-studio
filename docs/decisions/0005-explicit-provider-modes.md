# ADR-0005: Explicit provider modes, no silent fallback

**Status:** Accepted · 2026-10-30

## Context
The demo must run without credentials, and provider-backed mode must use genuine integrations.

## Decision
`VOICE_PROVIDER_MODE=mock|live` is read once at startup and wires concrete providers through FastAPI
dependency injection. Each conversation records its `provider_mode`. In `live` mode a provider failure
produces a `PROVIDER_ERROR` event and a visible UI error; the system never substitutes the mock.
Startup in `live` mode fails fast if required keys are missing.

Mocks are deterministic and realistic enough to exercise the same code paths: the mock STT emits
interim and split final events with endpointing; the mock receptionist is a rule-based extractor that
returns the same `TurnProposal` contract; the mock TTS returns a short generated WAV.

## Consequences
Every test runs offline. Live behaviour is verified separately and recorded as blocked when keys are
absent rather than claimed.

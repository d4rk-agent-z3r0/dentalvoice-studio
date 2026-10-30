# ADR-0003: The LLM proposes, the application decides

**Status:** Accepted · 2026-10-30

## Context
LLM output is untrusted and caller speech may contain injection attempts. The spec forbids the model
from controlling state or performing database writes.

## Decision
The model returns a `TurnProposal`: `assistant_response`, `intent`, `field_updates`, `missing_fields`,
`next_action` (closed enum: `ASK_CLARIFICATION`, `ASK_NEXT_FIELD`, `REQUEST_CONFIRMATION`,
`CONFIRM`, `ESCALATE`, `END`), `confidence`, `requires_escalation`. It has no tools and never names a
state. The orchestrator:

1. validates the proposal schema (Pydantic, strict);
2. validates each field update (type, normalisation, reserved contact values, date in the future and
   within the clinic's booking window) — rejected values are recorded, not applied;
3. derives the next state from the state machine using intake completeness + the validated action;
4. persists turn, drafts, events and state in one transaction.

`missing_fields` from the model is advisory; the authoritative list is computed from intake.

## Consequences
Behaviour is reproducible in tests without a model. The model cannot skip review/confirmation, cannot
confirm a booking, and cannot leak data it was never given.

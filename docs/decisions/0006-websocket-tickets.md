# ADR-0006: Single-use WebSocket tickets

**Status:** Accepted · 2026-10-30 · Implemented 2026-10-31 (Milestone 5: `ws_tickets`, migration `f61a7e4e6e78`)

## Context
Browsers cannot set an `Authorization` header on a WebSocket handshake. Putting the long-lived access
token in the URL leaks it into logs and history.

## Decision
`POST /conversations/{id}/ws-ticket` (authenticated) issues a random 256-bit ticket stored in
`ws_tickets`, bound to user, clinic and conversation, valid 60 s and consumed atomically on connect
(`UPDATE … SET used_at = now() WHERE jti = :t AND used_at IS NULL AND expires_at > now() RETURNING …`).

## Consequences
Replay and cross-conversation use are rejected by the database; the URL token is useless after one
connection. Costs one REST round-trip per connection.

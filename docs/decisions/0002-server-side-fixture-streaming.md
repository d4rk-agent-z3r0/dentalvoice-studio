# ADR-0002: Server-side fixture streaming to STT

**Status:** Accepted · 2026-10-30

## Context
The spec's diagram routes audio Frontend Player → WebSocket → STT. It also requires that *all* audio
reaching speech recognition originates from predefined synthetic fixtures, and forbids microphone
access and arbitrary uploads. If the browser sends audio bytes, the server cannot prove their origin.

## Decision
The browser never sends audio. It sends a control message (`next_clip`). The server resolves the next
clip from the scenario's ordered allow-list, streams that file from `demo_data/audio/` to the STT
provider at real-time pace, and tells the browser which static clip URL to play in parallel.

## Consequences
- The synthetic-audio boundary is enforced by construction, not by validation.
- The user still hears the caller and sees interim/final transcripts arrive while it plays.
- Diverges from the literal diagram; behaviour visible to the user is the same.

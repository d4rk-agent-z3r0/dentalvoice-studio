# Threat Model

> Status: Milestone 8, 2026-10-31. DentalVoice Studio is a **simulator for fictional clinics with
> synthetic data only**. It is not a medical system, holds no real patient data and makes no
> HIPAA or other compliance claim. This model exists so the demo is built the way a real system
> would have to be, and so its limits are stated plainly.

## 1. What is being protected

| Asset | Why it matters even in a demo |
|---|---|
| Tenant isolation (one clinic's data invisible to another) | The core property a multi-clinic product must never lose |
| Sign-in credentials and access tokens | Whoever holds them acts as a clinic user |
| Booking integrity (no double booking, idempotent retries) | A booking system that double-books is broken |
| What the receptionist says to callers | A spoken false promise ("you're booked") is the most visible failure an AI receptionist can make |
| Provider credentials (Gemini, Deepgram keys) | Cost and abuse; they live only in the operator's local `.env` |
| Service availability (CPU, memory, connections) | Password hashing, model calls and sockets are expensive |

Out of scope by design: real patient data (none exists; contact values are restricted to
`example.com|org|net` and `555-01xx` by database CHECK constraints), microphone input (none; caller
audio is server-side synthetic fixtures, ADR-0002), arbitrary uploads (none).

## 2. Actors and trust boundaries

```
 Browser (Next.js app) ──HTTPS/WSS──▶ FastAPI API ──▶ PostgreSQL
   untrusted input          │  trust boundary: every request authenticated and re-checked
                            ├──▶ Gemini (model output is untrusted input)
                            └──▶ Deepgram (transcripts are untrusted input)
```

| Actor | Can | Must not be able to |
|---|---|---|
| Anonymous internet user | Reach the sign-in endpoint | Enumerate accounts, brute-force passwords, call any other API route |
| Signed-in viewer | Read their clinic | Write anything; read another clinic |
| Signed-in staff/admin | Run calls and bookings in their clinic | Touch another clinic; keep access after removal |
| Malicious web page in the user's browser | Send requests to the API | Ride the user's session (no cookies), open the voice socket (Origin check), frame the app |
| Caller speech / model output | Shape the conversation | Change state outside the state machine, write to the database, make the receptionist claim things that did not happen |

## 3. Threats and controls (STRIDE)

| # | Threat | Control | Evidence |
|---|---|---|---|
| S1 | Spoofing: guessing passwords | argon2id hashing (RFC 9106 low-memory); 5 failures per account per 15 min then lockout; 20 attempts per IP per minute | `test_api_auth.py`, `test_api_rate_limits.py`, `test_passwords.py` |
| S2 | Spoofing: discovering which emails have accounts | One `AUTH_FAILED` for every failure, each costing the same hash check (a dummy hash for unknown users) | `test_every_sign_in_failure_looks_the_same`, `test_a_missing_hash_fails_after_doing_the_same_work` |
| S3 | Spoofing: forged or tampered tokens | HS256 only (no `alg: none`, no algorithm confusion), issuer and audience checked, 32+ character key enforced at startup | `test_security.py` |
| S4 | Spoofing: cross-site WebSocket hijacking | Single-use 60 s tickets bound to a conversation (ADR-0006); foreign `Origin` refused before the ticket is redeemed | `test_voice_socket.py` |
| T1 | Tampering: client-chosen clinic id | The clinic comes only from the signed token; repositories take `clinic_id` explicitly; composite `(clinic_id, id)` foreign keys | `test_tenant_isolation.py`, mutation: removing a tenant filter fails them |
| T2 | Tampering: model or caller drives state | The model proposes, deterministic services decide (ADR-0003): closed action enum, validated fields, no model tools, no model-written SQL | `test_decision.py`, `test_state_machine.py`, orchestrator tests |
| T3 | Tampering: concurrent double booking | PostgreSQL exclusion constraint decides; per-dentist transaction lock; bounded retry of aborted transactions; idempotency keys | `test_booking_concurrency.py` |
| R1 | Repudiation | Conversation events and turns are append-only records with request IDs in every log line | `test_logging.py` |
| I1 | Information disclosure: other clinics' data | 404 (not 403) for other clinics' resources, so existence does not leak | tenant isolation tests |
| I2 | Information disclosure: secrets in logs | Structured JSON logs; keys named like secrets and `?ticket=`/`?token=` query values are redacted; passwords, emails, transcripts and contact values are never logged | `test_logging.py`, `test_sign_in_never_logs_the_password_or_the_email` |
| I3 | Information disclosure: the model reveals its prompt, the provider or schema, or invents contact details | Reply guard replaces such replies with the deterministic one and records only reason codes | `test_reply_guard*.py`, docs/security/reply-guard.md |
| I4 | Information disclosure: browser-side | Strict CSP with per-request nonces; `no-referrer`; `nosniff`; tokens in memory and `sessionStorage` (per tab), never in URLs or cookies; API responses `no-store` | `headers.test.ts`, `test_http_hardening.py` |
| D1 | Denial of service: hashing load | At most 4 concurrent password hashes, in worker threads; IP limit on sign-in | `test_passwords.py` |
| D2 | Denial of service: request floods | Per-user request and write limits (`429` with `Retry-After`); bodies over 64 KiB refused; WebSocket commands capped at 1 KiB | `test_api_rate_limits.py`, `test_http_hardening.py` |
| D3 | Denial of service: abandoned sockets | Idle voice sockets closed after 5 minutes; barge-in and hang-up cancel speech in flight | `test_voice_failures.py` |
| E1 | Elevation: viewer performs writes | Role checked server-side on every write route; the frontend hides buttons only as a courtesy | role tests in the API suites |
| E2 | Elevation: keeping access after removal or demotion | Every request re-checks the user and membership in the database; a changed role invalidates the token | `test_a_token_stops_working_as_soon_as_access_changes` |
| E3 | Elevation: prompt injection ("ignore your instructions…") | The model has no tools and no write path; its words pass the reply guard; state changes go through the state machine only | reply guard integration tests |

## 4. Residual risks and limits

| Risk | Why it remains | What a production deployment would add |
|---|---|---|
| Rate-limit state is per process | Single-process demo | A shared store (e.g. Redis) or limits at the gateway |
| `X-Forwarded-For` is not trusted | No proxy is configured, so the TCP peer is the client | Trust exactly one configured proxy hop |
| Access tokens cannot be revoked individually | Stateless JWTs; mitigated by the per-request membership check and a 60-minute lifetime | Short tokens plus refresh tokens, or a revocation list |
| Tokens in `sessionStorage` are readable by script on the page | Mitigated by the strict CSP (no inline or third-party script) | An httpOnly cookie with CSRF protection |
| The reply guard is pattern-based | Paraphrased claims ("consider it done") can pass | A second classifier, or never speaking model text directly |
| No TLS in the app | TLS terminates in front of it | HSTS and TLS at the load balancer |
| Demo passwords are operator-chosen | `DEMO_PASSWORD` is in the operator's local `.env` | Per-user passwords, MFA, account recovery |
| Live provider behaviour is unverified here | No keys in the build environment | Contract tests against the live APIs before release |

## 5. Reporting

See `SECURITY.md` for how to report a vulnerability.

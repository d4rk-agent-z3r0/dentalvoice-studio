# External Providers

How the live integrations are configured, what they receive, and what has been verified.
`VOICE_PROVIDER_MODE=mock` (the default) needs none of this and makes no external calls. In
`live` mode a provider failure is shown as an error. The mock is never used as a fallback
(ADR-0005).

## Conversation model: Gemini (Milestone 4)

| Item | Value |
|---|---|
| SDK | `google-genai` 2.34.0, `client.aio.models.generate_content` |
| Configuration | `GEMINI_API_KEY`, `GEMINI_MODEL` in your local `.env` only. There is **no default model**: model ids change, so the operator names one explicitly. Google's structured-output guide used `gemini-3.8-flash` in its examples when checked on 2026-10-31; confirm the current id before use. |
| Startup | `live` mode refuses to start if either value is missing |
| Prompt | `backend/app/integrations/llm/prompts/receptionist_v1.md`, version `receptionist-v1`, sent as the system instruction |
| Output | `responseMimeType: application/json` with `responseJsonSchema` = the `TurnProposal` schema (inlined, closed objects). Gemini ignores some schema keywords (string lengths, for example), so output is validated again with Pydantic |
| Tools | None declared; automatic function calling disabled; the model cannot act, only propose (ADR-0003) |
| Transport | API key in the `x-goog-api-key` header, never in a URL or log. SDK-internal retries disabled; the adapter decides retries |
| Data sent | Clinic name, today's date, current stage, intake values collected so far, missing fields, service codes, the last 8 turns, and the caller's utterance (fenced as untrusted). All of it is synthetic: the database only accepts reserved example contact values |
| Measured per turn | `llm_ms` (wall time around the provider call, all attempts), `prompt_tokens` and `output_tokens` as reported by Gemini, `llm_attempts` |

### Verification status

| Check | Status |
|---|---|
| Request shape, parsing, failure handling via the real SDK against documented-shape payloads (`backend/tests/contract/`) | Verified (see `docs/verification-report.md`) |
| A live call against Gemini | **Blocked**: no API key available in the build environment. To run it: put `GEMINI_API_KEY` and `GEMINI_MODEL` in your local `.env`, set `VOICE_PROVIDER_MODE=live`, and run a scenario. Record the result here |

## Speech: Deepgram (Milestone 5)

Not yet integrated. Before any synthetic audio is committed, Deepgram's terms for redistributing
generated speech must be checked and recorded (`docs/license-audit.md`, synthetic audio item).

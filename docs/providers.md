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

Two adapters behind the speech interfaces in `backend/app/integrations/speech/base.py`. Neither
uses the Deepgram SDK: speech-to-text speaks the documented WebSocket protocol through
`websockets` (17.3), and text-to-speech the documented REST call through `httpx` (0.28.1).
Library types stay inside the adapter modules.

| Item | Value |
|---|---|
| Configuration | `DEEPGRAM_API_KEY`, `STT_MODEL`, `TTS_MODEL` in your local `.env` only; `SPEECH_TIMEOUT_SECONDS` (default 10). There are **no default model ids**: the operator names them. When checked on 2026-10-31 Deepgram's docs used `nova-3` (and `nova-2`) in streaming speech-to-text examples, `aura-2-thalia-en` in text-to-speech examples, and the REST reference listed `aura-asteria-en` as the server-side default. Confirm current ids before use |
| Startup | `live` mode refuses to start if any of the three values is missing; the factory builds both adapters without opening a connection |
| Transport | API key only in `Authorization: Token <key>`, never in a URL or log. The `websockets` library logs through a private logger pinned above DEBUG, because its debug output prints request headers and frames |
| Data sent | Speech-to-text: the caller audio the voice session streams (in the demo, synthetic scenario clips). Text-to-speech: the receptionist's reply text. Nothing else; transcripts, reply text and audio are never logged |
| Fallback | None. Every failure is a `ProviderError` (502) or `ProviderUnavailableError` (503); the mock is never substituted (ADR-0005) |

### Speech-to-text: `DeepgramSpeechToTextProvider` (`deepgram_stt.py`)

One WebSocket per stream to `wss://api.deepgram.com/v1/listen` with the query
`model=<STT_MODEL>&encoding=linear16&sample_rate=<rate>&channels=1&interim_results=true&endpointing=300&utterance_end_ms=1000&vad_events=true&smart_format=true&punctuate=true`.
Audio is sent as binary frames of raw linear16 PCM, exactly as the caller passes it (the clip
library streams 20 ms chunks at 16 kHz); empty chunks are not sent.

| Deepgram message | Becomes |
|---|---|
| `Results`, `is_final: false` | `INTERIM` (text and confidence from `channel.alternatives[0]`) |
| `Results`, `is_final: true` | `FINAL`, with `speech_final` copied. Empty finals are passed through: a `speech_final` with no words still ends the utterance in `UtteranceAssembler` |
| `UtteranceEnd` | `UTTERANCE_END`; ignored when `last_word_end` is `-1` (documented as "already finalized") |
| `Metadata`, `SpeechStarted`, others | ignored |
| `Error` | `ProviderError` raised from `events()`; the socket is closed |
| binary, non-JSON or malformed message | `ProviderError` |

| Situation | Behaviour |
|---|---|
| `finish()` | Sends `{"type": "CloseStream"}` (text frame). Deepgram then sends the remaining results and `Metadata` and closes the socket; `events()` ends at that close. The adapter does not invent an utterance end: the caller flushes `UtteranceAssembler` when the stream ends |
| No close within `SPEECH_TIMEOUT_SECONDS` of `finish()` | `ProviderUnavailableError` from `events()`; socket closed |
| No audio sent for 3 s | `{"type": "KeepAlive"}` text frame (docs: every 3–5 s; Deepgram closes after about 10 s without audio or KeepAlive) |
| Handshake 400, 401, 403 or other 4xx | `ProviderError`, message `HTTP <status> (<dg-error header>)` |
| Handshake 429 or 5xx, connection refused, handshake timeout (`SPEECH_TIMEOUT_SECONDS`) | `ProviderUnavailableError` |
| Close 1011 (`NET-0000/0001/0002`), a connection lost without a close frame, or a normal close before `finish()` | `ProviderUnavailableError` from `events()`, and from `send_audio`/`finish` once the socket is gone |
| Close 1008 (`DATA-0000`, undecodable audio) | `ProviderError` |
| Context exit, error or cancellation (hang-up) | Background reader and KeepAlive tasks stopped, socket closed (our close handshake is bounded at 2 s); `CloseStream` is not sent |

### Text-to-speech: `DeepgramTextToSpeechProvider` (`deepgram_tts.py`)

`POST https://api.deepgram.com/v1/speak?model=<TTS_MODEL>&encoding=linear16&sample_rate=24000&container=none`
with the JSON body `{"text": "<reply>"}`. `output_format` is 24 kHz mono linear16 with no WAV
header. Chunks are yielded as they arrive, trimmed to whole 2-byte samples (a split sample is carried
into the next chunk). An injectable `httpx.AsyncClient` is used by the tests.

| Situation | Behaviour |
|---|---|
| 4xx other than 429 (400, 401, 402, 403, 413 …) | `ProviderError`, message `HTTP <status> <err_code>`; never retried |
| 429, 5xx, connection error or timeout **before any audio was yielded** | One retry after 0.25 s; if that fails, `ProviderUnavailableError` |
| Any failure **after** audio was yielded | `ProviderUnavailableError` at once; no retry (it would repeat audio already played) and no silence or mock audio |
| Timeout | `SPEECH_TIMEOUT_SECONDS` for the response headers and again for each body chunk |
| 200 with an empty body | `ProviderError` |
| Consumer stops early (barge-in, hang-up) | The response is released immediately |

### Deepgram API facts relied on (checked 2026-10-31)

| Fact | Source |
|---|---|
| Live endpoint `wss://api.deepgram.com/v1/listen`; `Authorization: Token <key>` (or `Bearer <JWT>`); success is HTTP 101; query parameters `model`, `encoding`, `sample_rate`, `channels` (default 1), `interim_results`, `endpointing` (default 10), `utterance_end_ms`, `vad_events`, `smart_format`, `punctuate`; message types `Results`, `Metadata`, `UtteranceEnd`, `SpeechStarted`, `Error` and their fields; client messages `KeepAlive`, `Finalize`, `CloseStream` | [Listen streaming reference](https://developers.deepgram.com/reference/speech-to-text/listen-streaming) |
| `linear16` is 16-bit little-endian signed PCM; `sample_rate` is required when `encoding` is set | [Encoding](https://developers.deepgram.com/docs/encoding) |
| `endpointing` is milliseconds of silence before `speech_final`; append every `is_final` result until `speech_final`; "do not use `speech_final: true` alone to capture full transcripts" | [Endpointing and interim results](https://developers.deepgram.com/docs/understand-endpointing-interim-results) |
| `utterance_end_ms` in ms, 1000–5000, requires `interim_results=true`; `UtteranceEnd` has `channel` and `last_word_end`; `-1` means already finalized, ignore | [Utterance End](https://developers.deepgram.com/docs/utterance-end) |
| `CloseStream`: remaining audio processed, final results and `Metadata` sent, then the connection is terminated | [Close Stream](https://developers.deepgram.com/docs/close-stream) |
| `KeepAlive` must be a text frame, every 3–5 s; closed after 10 s without audio or KeepAlive (`NET-0001`) | [Audio Keep Alive](https://developers.deepgram.com/docs/audio-keep-alive) |
| `Finalize` flushes without ending the stream (`from_finalize: true`); not used here | [Finalize](https://developers.deepgram.com/docs/finalize) |
| Failed handshakes return 4xx/5xx with a `dg-error` header and `dg-request-id`; mid-stream errors arrive in the close frame: 1008 `DATA-0000`, 1011 `NET-0000`/`NET-0001`/`NET-0002`; empty binary frames can close the stream | [WebSocket, DATA and NET errors](https://developers.deepgram.com/docs/stt-troubleshooting-websocket-data-and-net-errors) |
| `POST https://api.deepgram.com/v1/speak`, `Authorization: Token <key>`, JSON body `{"text": ...}`, query `model`, `encoding`, `sample_rate`, `container` | [Speak REST reference](https://developers.deepgram.com/reference/text-to-speech/speak-request) |
| REST `linear16` sample rates 8000, 16000, 24000 (default), 32000, 48000; container `wav` (default) or `none`; `none` returns raw audio with `Content-Type: audio/l16;rate=24000` | [Media output settings](https://developers.deepgram.com/docs/tts-media-output-settings) |
| REST audio can be played from the first byte; no need to wait for the whole file | [Audio Output Streaming](https://developers.deepgram.com/docs/streaming-the-audio-output) |
| Error body `err_code`, `err_msg`, `request_id` (the 503 example uses `error_code`); 401 invalid key, 402 no credits, 413 text over the limit, 429 rate limit (retry with backoff), 503 retryable | [Errors](https://developers.deepgram.com/docs/errors) |
| Aura text limit 2000 characters, 413 when exceeded | [Streaming TTS](https://developers.deepgram.com/docs/streaming-text-to-speech) |

### Ambiguous or undocumented, and what the adapters assume

| Point | Assumption |
|---|---|
| The close code Deepgram uses after `CloseStream` is not documented | A normal close (1000/1001) after `finish()` ends the stream; any other code is an error. If a live run shows a different code, it will surface as an error, not be hidden. Check on the first live run |
| `vad_events` appears only in the Utterance End code examples ("To get UtteranceEnd, the following must be set: interim_results, utterance_end_ms, vad_events"); the prose names only `interim_results` | Sent as `true`; the resulting `SpeechStarted` messages are ignored |
| `Error` messages are described as non-fatal (sent, for example, for an unparseable text message) | Treated as fatal: the adapter only sends documented messages, so an `Error` means the integration itself is wrong |
| Handshake failure statuses are not enumerated beyond "4xx or 5xx" | 429 is treated like 5xx (transient), per the general errors page; other 4xx are not retried |
| The streaming reference does not list the `encoding` enum on the page itself | `linear16` taken from the Encoding page's list |
| The REST reference does not describe chunked delivery or the success content type | Taken from the Audio Output Streaming and Media output settings guides; the adapter does not check the content type |
| The models overview lists Flux models (`flux-general-en`, `flux-general-multi`) alongside Nova for streaming | Not checked whether Flux works with `/v1/listen` and these parameters; use a Nova model |
| Character limit stated on the streaming TTS page, 413 on the errors page | No client-side length check; the receptionist's replies are short, and a 413 is a `ProviderError` |

### Verification status

| Check | Status |
|---|---|
| Speech-to-text against a real local WebSocket server through the real `websockets` client: handshake headers and query, binary audio, CloseStream and KeepAlive frames, message mapping and assembly, every failure path above, cancellation (`backend/tests/contract/test_deepgram_stt.py`) | Verified (see `docs/verification-report.md`) |
| Text-to-speech through the real `httpx` client with `httpx.MockTransport`: request shape, streaming order, sample alignment, retry rules, timeouts (`backend/tests/contract/test_deepgram_tts.py`) | Verified |
| A live call to Deepgram (either adapter) | **Blocked**: no API key available in the build environment. To run it: put `DEEPGRAM_API_KEY`, `STT_MODEL` and `TTS_MODEL` in your local `.env`, set `VOICE_PROVIDER_MODE=live`, and run a scenario. Record the result here, including the close code seen after `CloseStream` |

The message payloads used by the tests are hand-written in the documented format, not recordings
(`backend/tests/contract/payloads/deepgram/README.md`). Deepgram-generated audio is never committed;
before that changes, review Deepgram's terms for generated speech (`docs/license-audit.md`).

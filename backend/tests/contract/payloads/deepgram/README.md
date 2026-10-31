<!-- SPDX-FileCopyrightText: 2026 Siddharth Majhi -->
<!-- SPDX-License-Identifier: MIT -->
# Deepgram payloads

Written by hand from the message shapes in Deepgram's documentation, checked on 2026-10-31:

- `stt_*.json`: live streaming speech-to-text (`/v1/listen`) server messages: `Results` (with
  `channel.alternatives[0].transcript` / `confidence`, `is_final`, `speech_final`,
  `from_finalize`), `UtteranceEnd` (`channel`, `last_word_end`, including the documented
  `last_word_end: -1` case), `SpeechStarted`, `Metadata` and `Error`.
- `tts_error_*.json`: text-to-speech REST error bodies (`err_code`, `err_msg`, `request_id`; the
  documented 503 example uses `error_code` instead of `err_code`, and `tts_error_503.json` keeps
  that difference).

They are **not** recordings of live traffic: no API key was available while writing them. The
request ids, model name, hash and error messages are placeholders. The fake server in
`tests/contract/deepgram_fake.py` plays the `stt_*` messages back through the real `websockets`
client; `tests/contract/test_deepgram_tts.py` serves the `tts_*` bodies through the real `httpx`
client. Replace them with real recordings, with any identifiers removed, once a live run is
possible (`docs/providers.md`).

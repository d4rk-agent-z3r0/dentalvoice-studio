<!-- SPDX-FileCopyrightText: 2026 Siddharth Majhi -->
<!-- SPDX-License-Identifier: MIT -->
# Deepgram payloads

Written by hand from the message shapes in Deepgram's documentation, checked on 2026-10-31:

- `stt_*.json`: live streaming speech-to-text (`/v1/listen`) server messages: `Results` (with
  `channel.alternatives[0].transcript` / `confidence`, `is_final`, `speech_final`,
  `from_finalize`), `UtteranceEnd` (`channel`, `last_word_end`, including the documented
  `last_word_end: -1` case), `SpeechStarted`, `Metadata` and `Error`.

They are **not** recordings of live traffic: no API key was available while writing them. The
request ids, model name and hash are placeholders. The fake server in
`tests/contract/deepgram_fake.py` plays them back through the real `websockets` client. Replace
them with real recordings, with any identifiers removed, once a live run is possible
(`docs/providers.md`).

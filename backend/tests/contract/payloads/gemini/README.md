<!-- SPDX-FileCopyrightText: 2026 Siddharth Majhi -->
<!-- SPDX-License-Identifier: MIT -->
# Gemini response payloads

Written by hand from the documented `generateContent` REST response shape (candidates →
content → parts → text, `finishReason`, `usageMetadata`, `promptFeedback`) and checked by
parsing them with `google-genai` 2.34.0's own response types. They are **not** recordings of live
traffic: no API key was available while writing them. Replace them with real recordings, with
any identifiers removed, once a live run is possible (`docs/providers.md`).

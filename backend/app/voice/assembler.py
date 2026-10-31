# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Reconstruct complete caller utterances from streaming transcript events.

Rules (build spec §8):

- Interim results are displayed, never committed.
- Every final segment is kept, in order, until the utterance completes. A long sentence often
  arrives as several finals, and none may be lost.
- An utterance completes on an utterance-end event, on a final marked ``speech_final``, or when
  the stream ends. Whatever finals were collected become one committed utterance.
"""

from dataclasses import dataclass, field

from app.integrations.speech.base import TranscriptEvent, TranscriptKind


@dataclass
class UtteranceAssembler:
    _finals: list[str] = field(default_factory=list)
    interim: str = ""  # latest provisional text, for display only

    def add(self, event: TranscriptEvent) -> str | None:
        """Feed one event. Returns the completed utterance when this event completes one."""
        match event.kind:
            case TranscriptKind.INTERIM:
                self.interim = event.text.strip()
                return None
            case TranscriptKind.FINAL:
                text = event.text.strip()
                if text:
                    self._finals.append(text)
                self.interim = ""
                return self._complete() if event.speech_final else None
            case TranscriptKind.UTTERANCE_END:
                return self._complete()

    def flush(self) -> str | None:
        """The stream ended: commit whatever finals were received."""
        return self._complete()

    @property
    def pending(self) -> str:
        """Finals so far plus the current interim, for live display."""
        return " ".join([*self._finals, self.interim]).strip()

    def _complete(self) -> str | None:
        if not self._finals:
            return None  # an utterance-end with no speech is not an utterance
        text = " ".join(self._finals)
        self._finals.clear()
        self.interim = ""
        return text

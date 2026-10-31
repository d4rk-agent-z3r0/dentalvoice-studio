# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The conversation-model interface. Implementations: the rule-based mock (this milestone) and
Gemini (Milestone 4). Both return the same ``TurnProposal`` contract."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.domain.enums import ConversationState, IntakeField, Speaker
from app.schemas.proposal import TurnProposal


@dataclass(frozen=True)
class HistoryLine:
    speaker: Speaker
    text: str


@dataclass(frozen=True)
class TurnContext:
    """Everything a model may see for one turn. Synthetic data only."""

    clinic_name: str
    clinic_today: date  # in the clinic's timezone; relative dates resolve against this
    state: ConversationState
    utterance: str  # untrusted caller speech: data, never instructions
    known_values: dict[IntakeField, str | None]  # None = explicitly declined
    missing_fields: list[IntakeField]
    services: dict[str, str]  # code -> display name
    history: list[HistoryLine]


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class ProposalResult:
    proposal: TurnProposal
    usage: TokenUsage | None = None  # reported by the provider; never estimated
    attempts: int = 1


class ProviderError(Exception):
    """A provider call failed. Surfaced to the user; never replaced by a mock (ADR-0005)."""

    code = "PROVIDER_ERROR"

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message


class ProviderUnavailableError(ProviderError):
    """Transient: timeouts, rate limits and server errors that persisted through retries."""

    code = "PROVIDER_UNAVAILABLE"


class ConversationModelProvider(Protocol):
    name: str
    # True when the provider writes natural replies that may be spoken as-is (subject to checks);
    # False when the orchestrator should always speak its own deterministic reply.
    writes_responses: bool

    async def propose(self, context: TurnContext) -> ProposalResult: ...

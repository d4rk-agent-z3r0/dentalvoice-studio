# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The reply guard: deterministic checks on the words a model wants the receptionist to say.

ADR-0003 already treats the model's *action* as a request. This module does the same for its
*words*: before a model-written ``assistant_response`` is stored and spoken, ``check_reply``
looks for things the application never did or must never say. A rejected reply is replaced by
the deterministic one (``responses.compose_reply``). The guard is pure and has no I/O; its
verdict carries reason codes only, never the text.

What the conversation engine actually commits to (see ``docs/security/reply-guard.md``):

* It never books, schedules, reserves or confirms an appointment. Appointments are created only
  by clinic staff through the appointments API. A call records an appointment *request*, which
  the clinic confirms later. So a booking claim is false in every state.
* The intake is confirmed on entering ``CONFIRMATION_PENDING``, and the snapshot and patient
  record are created on entering ``COMPLETED``. Only then are the caller's details registered or
  saved. Model text is never spoken in those states (their wording is fixed), but the guard is
  state-aware so the rule is right on its own: a registration claim passes only in ``COMPLETED``.

The rules favour clear patterns over breadth. A false positive costs a less natural sentence,
because the deterministic reply is always safe; a false negative is spoken aloud.
"""

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache

from app.domain.enums import ConversationState, IntakeField
from app.integrations.llm.prompting import (
    CALLER_CLOSE,
    CALLER_OPEN,
    PROMPT_VERSION,
    system_prompt,
)
from app.schemas.proposal import FieldUpdates, Intent, NextAction, TurnProposal

# Two short spoken sentences are 100-250 characters. The longest legitimate reply is the
# read-back in INFORMATION_REVIEW (at most 220 characters for the demo scenarios). 400 characters is
# roughly 65 words, or 25 seconds of speech: anything longer is a monologue on a phone line, and
# long output is the usual shape of a prompt dump. The schema allows 600.
MAX_SPOKEN_CHARS = 400

# How many consecutive words shared with the receptionist prompt count as quoting it.
PROMPT_ECHO_WORDS = 8


class GuardReason(StrEnum):
    """Why a reply was refused. The values are stored in ``reply_filtered`` events."""

    FALSE_BOOKING_CLAIM = "false_booking_claim"
    FALSE_REGISTRATION_CLAIM = "false_registration_claim"
    SYSTEM_DISCLOSURE = "system_disclosure"
    PROVIDER_DISCLOSURE = "provider_disclosure"
    SCHEMA_LEAK = "schema_leak"
    PROMPT_ECHO = "prompt_echo"
    UNLISTED_EMAIL = "unlisted_email"
    UNLISTED_PHONE = "unlisted_phone"
    LINK = "link"
    DIAGNOSIS = "diagnosis"
    TREATMENT_ADVICE = "treatment_advice"
    MEDICATION_ADVICE = "medication_advice"
    PRICE_QUOTE = "price_quote"
    MARKUP = "markup"
    CONTROL_CHARACTERS = "control_characters"
    TOO_LONG = "too_long"


@dataclass(frozen=True)
class GuardContext:
    """What the application knows to be true for this turn."""

    state: ConversationState  # the state the conversation is in after this turn
    emails: frozenset[str]  # the caller's own live email (lower case), if given
    phones: frozenset[str]  # the caller's own live phone, as comparable digits
    names: frozenset[str]  # the caller's own name parts (lower case)


@dataclass(frozen=True)
class GuardVerdict:
    reasons: tuple[GuardReason, ...]  # in rule order, no duplicates; never the text

    @property
    def allowed(self) -> bool:
        return not self.reasons


def _phone_digits(value: str) -> str:
    """Digits a listener would compare: ``+1-555-0101`` and ``555 0101`` are the same number."""
    digits = re.sub(r"\D", "", value)
    if len(digits) in (8, 11) and digits.startswith("1"):
        digits = digits[1:]
    return digits


def guard_context(
    state: ConversationState, values: Mapping[IntakeField, str | None]
) -> GuardContext:
    """Build the context from live intake values (``None`` = declined)."""
    email = values.get(IntakeField.EMAIL)
    phone = values.get(IntakeField.PHONE)
    names = {
        part.lower()
        for name in (values.get(IntakeField.FIRST_NAME), values.get(IntakeField.LAST_NAME))
        if name
        for part in re.findall(r"[^\W\d_]+", name)
    }
    return GuardContext(
        state=state,
        emails=frozenset({email.lower()} if email else set()),
        phones=frozenset({_phone_digits(phone)} if phone else set()),
        names=frozenset(names),
    )


# --- text preparation ---------------------------------------------------------------------------

_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'"})
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Zl", "Zp"})


def _prepare_char(ch: str) -> str:
    category = unicodedata.category(ch)
    if ch == "\n" or category not in _INVISIBLE_CATEGORIES:
        return ch
    return "" if category == "Cf" else " "  # zero-width characters join, controls separate


def _prepare(text: str) -> str:
    """Normalise look-alikes (full-width letters, curly apostrophes) and remove invisible
    characters, so they cannot hide a pattern. Line breaks stay, so line-anchored markup is
    still seen. The control rule sees the original text."""
    folded = unicodedata.normalize("NFKC", text).translate(_APOSTROPHES)
    return "".join(_prepare_char(ch) for ch in folded)


def _compile(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns)


def _any(patterns: Iterable[re.Pattern[str]], text: str) -> bool:
    return any(p.search(text) for p in patterns)


# --- false commitments --------------------------------------------------------------------------

_AUX = r"(?:is|are|was|were|has been|have been|'s|'re)"
_ADVERBS = r"(?:(?:now|all|already|officially|successfully|just|been|fully)\s+)*"
_WE = r"(?:I|we|the clinic|the team|the practice|they)(?:'ve|'s|\s+have|\s+has)?"
_SUBORDINATE = re.compile(
    r"\b(?:once|when|whenever|after|until|till|unless|if|before|as soon as|whether)\b",
    re.IGNORECASE,
)

_BOOKING = _compile(
    # "your appointment (on Tuesday) is booked", "your booking has been confirmed"
    r"\b(?:appointments?|appts?|bookings?|visits?|slots?|cleanings?|check-?ups?|consultations?"
    r"|exams?|sessions?|reservations?)\b[^.!?,;:]{0,30}?\s"
    + _AUX
    + r"\s+"
    + _ADVERBS
    + r"(?:booked|scheduled|reserved|confirmed|set|set up|locked in|arranged|secured|made)\b",
    # "I've booked you in", "we have reserved the 10 o'clock slot", "the clinic has confirmed"
    r"\b" + _WE + r"\s+" + _ADVERBS + r"(?:gone ahead and\s+)?"
    r"(?:booked|scheduled|reserved|confirmed|secured|arranged)\s+(?:you|your|an?|the|it|that)\b",
    # "you're all booked in", "you are confirmed for Tuesday"
    r"\byou(?:'re|\s+are|'ve been|\s+have been)\s+"
    + _ADVERBS
    + r"(?:booked|scheduled|reserved|confirmed(?=\s+for)|(?:set|pencil+ed)\s+(?:in|for))\b",
    r"\b(?:confirmation|booking|reservation)\s+(?:number|code|reference|id)\b",
    # "Booked! See you Tuesday.", "All booked for Tuesday."
    r"(?:^|[.!?]\s+)(?:all\s+)?(?:booked|scheduled|reserved)\b(?=\s*(?:[!.,]|$|(?:in|for)\b))",
)

_REGISTRATION = _compile(
    # "your details are saved", "everything is confirmed", "your request has been submitted"
    r"\b(?:details|information|info|registration|record|profile|account|request|application"
    r"|everything|it all|all of (?:it|that))\b[^.!?,;:]{0,30}?\s"
    + _AUX
    + r"\s+"
    + _ADVERBS
    + r"(?:saved|stored|submitted|registered|confirmed|finali[sz]ed|complete|completed|processed"
    r"|recorded|logged|filed|on file|in (?:the|our) system)\b",
    # "I've saved your details", "we have registered you"
    r"\b"
    + _WE
    + r"\s+"
    + _ADVERBS
    + r"(?:saved|stored|submitted|registered|confirmed|finali[sz]ed|processed|filed|signed)\s+"
    r"(?:you|your|it|that|everything|all)\b",
    # "you're now registered"
    r"\byou(?:'re|\s+are|'ve been|\s+have been)\s+"
    + _ADVERBS
    + r"(?:registered|signed up|enrolled|on file|in (?:the|our) system)\b",
)


def _claims(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    """A match counts unless its sentence makes it conditional ("once your appointment is
    confirmed, ..."). Negations ("isn't booked", "can't book") never match the patterns."""
    for pattern in patterns:
        for match in pattern.finditer(text):
            sentence_start = max(text.rfind(mark, 0, match.start()) for mark in ".!?;\n")
            if not _SUBORDINATE.search(text, sentence_start + 1, match.start() + 1):
                return True
    return False


def _false_booking(text: str, _: GuardContext) -> bool:
    return _claims(_BOOKING, text)  # the engine never books: false in every state


def _false_registration(text: str, ctx: GuardContext) -> bool:
    return ctx.state is not ConversationState.COMPLETED and _claims(_REGISTRATION, text)


# --- prompt or system leakage -------------------------------------------------------------------

_SYSTEM = _compile(
    r"\bsystem\s+(?:prompt|message|instructions?)\b",
    r"\b(?:my|these|those|internal|hidden|original|previous|prior|initial)\s+"
    r"(?:instructions|prompt|programming|configuration|guidelines|directives)\b",
    r"\bignor(?:e|ing)\s+(?:(?:all|any|my|your|the|previous|prior|earlier|these)\s+)*"
    r"(?:instructions|rules|prompt)\b",
    r"\bI(?:'m|\s+am|'ve been|\s+have been|\s+was)\s+(?:programmed|instructed|configured|prompted)"
    r"\b",
    r"\b(?:developer|debug|admin|god|jailbreak|unrestricted)\s+mode\b",
    r"\bjailbr(?:eak|oken)\b",
    r"\bmy\s+(?:developers|creators|programmers|operators|makers)\b",
    re.escape(CALLER_OPEN),
    re.escape(CALLER_CLOSE),
    r"<<<|>>>",
    re.escape(PROMPT_VERSION),
)

_PROVIDER_NAMES = re.compile(
    r"\b(gemini|google|deepmind|vertex|openai|chatgpt|gpt(?:-?\d[\w.]*)?|claude|anthropic|llama"
    r"|mistral|bard|copilot)\b",
    re.IGNORECASE,
)
_MODEL_WORDS = _compile(
    r"\b(?:large\s+)?language\s+models?\b",
    r"\bLLMs?\b",
    r"\bAI\s+models?\b",
    r"\bneural\s+network\b",
    r"\btraining\s+data\b",
    r"\bopen\s+ai\b",
)


def _system_disclosure(text: str, _: GuardContext) -> bool:
    return _any(_SYSTEM, text)


def _provider_disclosure(text: str, ctx: GuardContext) -> bool:
    if _any(_MODEL_WORDS, text):
        return True
    # A provider word that is the caller's own name ("Thanks, Claude") is just their name.
    return any(m.group(1).lower() not in ctx.names for m in _PROVIDER_NAMES.finditer(text))


@cache
def _schema_identifiers() -> re.Pattern[str]:
    """Every snake_case or SCREAMING_CASE identifier of the model contract and the turn context:
    field names, actions, intents and states. Derived from the code so it never drifts."""
    names = {
        *TurnProposal.model_fields,
        *FieldUpdates.model_fields,
        *(member.value for member in NextAction),
        *(member.value for member in Intent),
        *(member.value for member in ConversationState),
        *(member.value for member in IntakeField),
        "known_values",
        "clinic_today",
    }
    words = sorted((n for n in names if "_" in n), key=len, reverse=True)
    return re.compile(
        r"(?<![A-Za-z0-9_])(?:" + "|".join(map(re.escape, words)) + r")(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )


_JSON = _compile(r"\bjson\b", r"\bschema\b", r"\{\s*\"\w+\"\s*:")


def _schema_leak(text: str, _: GuardContext) -> bool:
    return bool(_schema_identifiers().search(text)) or _any(_JSON, text)


_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


@cache
def _prompt_ngrams() -> frozenset[tuple[str, ...]]:
    words = _words(system_prompt())
    n = PROMPT_ECHO_WORDS
    return frozenset(tuple(words[i : i + n]) for i in range(len(words) - n + 1))


def _prompt_echo(text: str, _: GuardContext) -> bool:
    words = _words(text)
    n = PROMPT_ECHO_WORDS
    grams = _prompt_ngrams()
    return any(tuple(words[i : i + n]) in grams for i in range(len(words) - n + 1))


# --- contact data and links ---------------------------------------------------------------------

_TLDS = r"com|org|net|edu|gov|io|co|uk|ai|info|biz|app|dev|ly|xyz|online|site|health|dental|clinic"
_EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.IGNORECASE)
_SPOKEN_EMAIL = re.compile(
    r"\b([a-z0-9]+(?:\s+(?:dot|underscore|dash|hyphen)\s+[a-z0-9]+)*)\s+at\s+"
    r"([a-z0-9-]+(?:\s+dot\s+[a-z0-9-]+)*\s+dot\s+(?:" + _TLDS + r"))\b",
    re.IGNORECASE,
)
_SPOKEN_SEPARATORS = {" dot ": ".", " underscore ": "_", " dash ": "-", " hyphen ": "-"}


def _spoken_to_address(local: str, domain: str) -> str:
    address = f"{' '.join(local.split())}@{' '.join(domain.split())}".lower()
    for spoken, symbol in _SPOKEN_SEPARATORS.items():
        address = address.replace(spoken, symbol)
    return address


def _unlisted_email(text: str, ctx: GuardContext) -> bool:
    found = {m.group(0).lower().rstrip(".") for m in _EMAIL.finditer(text)}
    found |= {_spoken_to_address(m.group(1), m.group(2)) for m in _SPOKEN_EMAIL.finditer(text)}
    return not found <= ctx.emails  # the clinic publishes no contact details of its own


_DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
_PHONE = re.compile(r"(?<![\w+])\+?\(?\d(?:[\s().-]{0,2}\d){6,14}(?!\w)")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SPOKEN_PHONE = re.compile(
    r"\b(?:(?:" + "|".join(_DIGIT_WORDS) + r")\b[\s,.-]*){7,}",
    re.IGNORECASE,
)


def _unlisted_phone(text: str, ctx: GuardContext) -> bool:
    numbers = [m.group(0) for m in _PHONE.finditer(text) if not _ISO_DATE.fullmatch(m.group(0))]
    numbers += [
        "".join(_DIGIT_WORDS[w.lower()] for w in re.findall(r"[a-z]+", m.group(0), re.I))
        for m in _SPOKEN_PHONE.finditer(text)
    ]
    return any(_phone_digits(number) not in ctx.phones for number in numbers)


_LINKS = _compile(
    r"\b(?:https?|ftp)://",
    r"\bwww\.",
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:" + _TLDS + r")(?![a-z0-9-])",
    r"\b[a-z0-9-]+\s+dot\s+(?:" + _TLDS + r")\b",
)


def _link(text: str, _: GuardContext) -> bool:
    # Email addresses are judged by the email rule; their domains are not links.
    rest = _SPOKEN_EMAIL.sub(" ", _EMAIL.sub(" ", text))
    return _any(_LINKS, rest)


# --- clinical and price advice ------------------------------------------------------------------

_CONDITIONS = (
    r"(?:abscess(?:ed)?|infection|infected|cavit(?:y|ies)|decay|gum disease|gingivitis"
    r"|periodontitis|pulpitis|cracked tooth|fractured tooth|impacted|tmj|tmd|dry socket"
    r"|nerve damage|bruxism|enamel erosion|an? (?:fracture|cyst))"
)
_DIAGNOSIS = _compile(
    r"\b(?:sounds|looks|seems)\s+(?:like|to be)\s+(?:you(?:'ve|\s+have|\s+might have|\s+may have"
    r"|'ve got)?\s+)?(?:got\s+)?(?:an?\s+|some\s+)?(?:\w+\s+){0,2}?" + _CONDITIONS + r"\b",
    r"\byou(?:'ve|\s+have)?\s+(?:probably|likely|most likely|possibly|might|may|could|must)\s+"
    r"(?:have\s+|have got\s+|be developing\s+)?(?:an?\s+|some\s+)?(?:\w+\s+){0,2}?"
    + _CONDITIONS
    + r"\b",
    r"\byou(?:'ve|\s+have)\s+got\s+(?:an?\s+|some\s+)?(?:\w+\s+){0,1}?" + _CONDITIONS + r"\b",
    r"\b(?:it|that|this)(?:'s|\s+is)\s+(?:probably|likely|most likely|definitely|almost certainly"
    r"|clearly|surely)\s+(?:just\s+)?(?:an?\s+|some\s+)?(?:\w+\s+){0,1}?" + _CONDITIONS + r"\b",
    r"\b(?:it|that|this)\s+(?:could|might|may|must)\s+be\s+(?:just\s+)?(?:an?\s+|some\s+)?"
    r"(?:\w+\s+){0,1}?" + _CONDITIONS + r"\b",
)

_TREATMENTS = (
    r"(?:root canal|filling|extraction|crown|implant|bridge|veneers?|braces|aligners|invisalign"
    r"|scaling|deep cleaning|whitening|antibiotics|wisdom tooth removal|x-?rays?|gum surgery"
    r"|denture)"
)
_TREATMENT = _compile(
    # "you'll need a root canal", "you will probably need a filling"
    r"(?<!\bdo )(?<!\bdoes )(?<!\bwould )(?<!\bwill )(?<!\bif )\byou(?:'ll|\s+will|'d|\s+would)?"
    r"\s+(?:probably\s+|likely\s+|definitely\s+|certainly\s+)?(?:need|require)\s+"
    r"(?:to\s+(?:get|have)\s+)?(?:an?\s+|some\s+|the\s+)?(?:\w+\s+){0,1}?" + _TREATMENTS,
    # "I'd recommend getting a crown", "I suggest a deep cleaning"
    r"\b(?:I|we)(?:'d|\s+would)?\s+(?:strongly\s+)?(?:recommend|suggest|advise)\s+"
    r"(?:that\s+you\s+|you\s+)?(?:get(?:ting)?\s+|hav(?:e|ing)\s+|tak(?:e|ing)\s+|book(?:ing)?\s+)?"
    r"(?:an?\s+|some\s+|the\s+)?(?:\w+\s+){0,1}?" + _TREATMENTS,
    # "you should get an extraction"
    r"\byou\s+(?:should|must|ought to|have to|need to)\s+(?:get|have|take|consider|start)\s+"
    r"(?:an?\s+|some\s+|the\s+)?(?:\w+\s+){0,1}?" + _TREATMENTS,
    # "that tooth should be pulled"
    r"\b(?:should|must|needs? to|will have to|has to|ought to)\s+be\s+"
    r"(?:pulled|extracted|removed|filled|crowned|drilled)\b",
)

_DRUGS = (
    r"(?:ibuprofen|paracetamol|acetaminophen|tylenol|advil|motrin|aspirin|naproxen|aleve|codeine"
    r"|tramadol|oxycodone|hydrocodone|amoxicillin|penicillin|clindamycin|metronidazole"
    r"|azithromycin|antibiotics?|painkillers?|pain ?relievers?|pain medication|anti-?inflammator"
    r"(?:y|ies)|benzocaine|lidocaine|orajel|chlorhexidine|numbing gel|salt ?water|clove oil"
    r"|(?:cold|warm|ice) (?:compress|pack))"
)
_MEDICATION = _compile(
    r"\b\d+(?:\.\d+)?\s?(?:mg|milligrams?|mcg|micrograms?|ml|millilit(?:er|re)s?)\b",
    r"\b(?:take|taking|try|trying|use|using|apply|applying|rinse with|rinsing with|gargle with"
    r"|swallow|get some|pick up|ask for|hold)\s+(?:\w+\s+){0,3}?" + _DRUGS + r"\b",
    r"\b" + _DRUGS + r"\b[^.!?]{0,20}?\b(?:should|will|can|might|may|would)\s+"
    r"(?:help|ease|relieve|reduce|work|calm|numb)\b",
)

_NUMBER_WORDS = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty"
    r"|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)"
)
_PRICE = _compile(
    r"[$£€₹¥]\s?\d",
    r"\b" + _NUMBER_WORDS + r"\s+(?:dollars|bucks|pounds|quid|euros?|rupees)\b",
    r"\b\d+\s?(?:%|percent)\s+(?:off|discount)\b",
    r"\b(?:promo|discount|coupon|voucher)\s+codes?\b",
    r"\b\d+(?:[.,]\d+)*\s?(?:dollars|bucks|pounds|quid|euros?|rupees|usd|gbp|eur|inr)\b",
    r"\b(?:costs?|priced at|price is|fee is|charge is|fee of|price of|charges?)\s+"
    r"(?:(?:about|around|roughly|only|just|approximately|from|of)\s+)*\d",
)


def _diagnosis(text: str, _: GuardContext) -> bool:
    return _any(_DIAGNOSIS, text)


def _treatment(text: str, _: GuardContext) -> bool:
    return _any(_TREATMENT, text)


def _medication(text: str, _: GuardContext) -> bool:
    return _any(_MEDICATION, text)


def _price(text: str, _: GuardContext) -> bool:
    return _any(_PRICE, text)


# --- unsafe formatting for speech ---------------------------------------------------------------

_MARKUP = _compile(
    r"`",  # inline code and code fences
    r"\*\*|__|~~",  # bold, strike-through
    r"(?<![\w*])\*[^*\s][^*\n]*\*(?![\w*])",  # *emphasis* or *stage directions*
    r"^\s{0,3}#{1,6}\s",  # headings
    r"^\s*(?:[-*+\u2022]|\d+[.)])\s+\S",  # list items
    r"\[[^\]\n]+\]\([^)\n]*\)",  # [links](target)
    r"</?[a-z][\w:.-]*(?:\s[^<>]*)?/?>",  # HTML or SSML tags
    r"&(?:[a-z]+|#\d+|#x[0-9a-f]+);",  # HTML entities
)


def _markup(text: str, _: GuardContext) -> bool:
    return _any(_MARKUP, text)


# The only rules that judge the original text: control characters are removed by ``_prepare``.
def _control_characters(text: str, _: GuardContext) -> bool:
    return any(unicodedata.category(ch) in _INVISIBLE_CATEGORIES for ch in text)


def _too_long(text: str, _: GuardContext) -> bool:
    return len(text) > MAX_SPOKEN_CHARS


Rule = Callable[[str, GuardContext], bool]

# One rule per line, in reason order.
_RULES: tuple[tuple[GuardReason, Rule], ...] = (
    (GuardReason.FALSE_BOOKING_CLAIM, _false_booking),
    (GuardReason.FALSE_REGISTRATION_CLAIM, _false_registration),
    (GuardReason.SYSTEM_DISCLOSURE, _system_disclosure),
    (GuardReason.PROVIDER_DISCLOSURE, _provider_disclosure),
    (GuardReason.SCHEMA_LEAK, _schema_leak),
    (GuardReason.PROMPT_ECHO, _prompt_echo),
    (GuardReason.UNLISTED_EMAIL, _unlisted_email),
    (GuardReason.UNLISTED_PHONE, _unlisted_phone),
    (GuardReason.LINK, _link),
    (GuardReason.DIAGNOSIS, _diagnosis),
    (GuardReason.TREATMENT_ADVICE, _treatment),
    (GuardReason.MEDICATION_ADVICE, _medication),
    (GuardReason.PRICE_QUOTE, _price),
    (GuardReason.MARKUP, _markup),
)
_RAW_RULES: tuple[tuple[GuardReason, Rule], ...] = (
    (GuardReason.CONTROL_CHARACTERS, _control_characters),
    (GuardReason.TOO_LONG, _too_long),
)


def check_reply(text: str, context: GuardContext) -> GuardVerdict:
    """Return every reason ``text`` must not be spoken in ``context``; none means allowed."""
    prepared = _prepare(text)
    found = {reason for reason, rule in _RULES if rule(prepared, context)}
    found |= {reason for reason, rule in _RAW_RULES if rule(text, context)}
    return GuardVerdict(tuple(reason for reason in GuardReason if reason in found))

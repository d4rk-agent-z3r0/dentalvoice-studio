# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Turn spoken phrasing into candidate structured values.

Speech-to-text gives "ava dot lindqvist at example dot com" and "around ten in the morning", not
``ava.lindqvist@example.com`` and ``10:00``. These helpers find such phrases and return a
*candidate*. Every candidate still goes through intake validation. Each helper returns ``None``
when the text is ambiguous, rather than guessing.
"""

import re
from datetime import date, timedelta

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "noon": 12,
}  # fmt: skip
_MINUTE_WORDS = {"fifteen": 15, "thirty": 30, "forty five": 45, "forty-five": 45, "half": 30}

_SPOKEN_EMAIL = re.compile(
    r"\b([a-z0-9]+(?:\s+(?:dot|underscore|dash|hyphen)\s+[a-z0-9]+)*)"
    r"\s+at\s+example\s+dot\s+(com|org|net)\b"
)
_WRITTEN_EMAIL = re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?\(?555\)?[\s.-]?01\d\s?\d")
_DIGIT_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b")
_WORD_TIME = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|noon)"
    r"(?:\s+(o'clock|fifteen|thirty|forty[\s-]five))?\b"
)


def find_email(text: str) -> str | None:
    lowered = text.lower()
    written = _WRITTEN_EMAIL.search(lowered)
    if written:
        return written.group(0)
    spoken = _SPOKEN_EMAIL.search(lowered)
    if not spoken:
        return None
    local = spoken.group(1)
    for word, symbol in (("dot", "."), ("underscore", "_"), ("dash", "-"), ("hyphen", "-")):
        local = re.sub(rf"\s+{word}\s+", symbol, local)
    return f"{local}@example.{spoken.group(2)}"


def find_phone(text: str) -> str | None:
    match = _PHONE.search(text)
    return match.group(0) if match else None


def find_weekday_date(text: str, today: date) -> date | None:
    """ "next Tuesday", "Thursday next week", "on Friday" → the first such day after ``today``.

    Exactly one weekday must be named; otherwise the phrase is ambiguous and ``None`` is returned.
    """
    lowered = text.lower()
    named = [i for i, day in enumerate(WEEKDAYS) if re.search(rf"\b{day}\b", lowered)]
    if len(named) != 1:
        return None
    days_ahead = (named[0] - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


def _meridiem(text: str, hour: int, marker: str | None) -> int:
    marker = (marker or "").replace(".", "")
    if marker == "pm" or re.search(r"\b(afternoon|evening)\b", text):
        return hour + 12 if hour < 12 else hour
    if marker == "am" or re.search(r"\bmorning\b", text):
        return 0 if hour == 12 else hour
    # No marker: clinic hours make 7-11 the morning and 1-6 the afternoon.
    return hour + 12 if 1 <= hour <= 6 else hour


def find_time(text: str) -> str | None:
    """ "ten in the morning" → 10:00, "two o'clock" in the afternoon → 14:00, "2:30 pm" → 14:30."""
    lowered = text.lower()
    word = _WORD_TIME.search(lowered)
    if word:
        hour = _NUMBER_WORDS[word.group(1)]
        minute = _MINUTE_WORDS.get((word.group(2) or "").replace("-", " "), 0)
        return f"{_meridiem(lowered, hour, None):02d}:{minute:02d}"
    for match in _DIGIT_TIME.finditer(lowered):
        hour, minute, marker = int(match.group(1)), int(match.group(2) or 0), match.group(3)
        if match.group(2) is None and marker is None:
            continue  # a bare number ("555", "3 years") is not a time
        if 1 <= hour <= 23 and minute < 60:
            hour = _meridiem(lowered, hour, marker) if hour <= 12 else hour
            return f"{hour:02d}:{minute:02d}"
    return None

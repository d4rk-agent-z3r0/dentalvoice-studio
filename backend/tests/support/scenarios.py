# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Turn a catalogue scenario's expectations into concrete values for a given call date."""

from datetime import date

from app.demo import catalog
from app.domain.enums import IntakeField
from app.domain.spoken import WEEKDAYS


def resolve_expected(value: str, today: date) -> str:
    """``next:<weekday>`` → ISO date of the first such weekday after ``today``."""
    if value.startswith("next:"):
        target = WEEKDAYS.index(value.removeprefix("next:"))
        days = (target - today.weekday()) % 7 or 7
        return date.fromordinal(today.toordinal() + days).isoformat()
    return value


def expected_fields(scenario: catalog.Scenario, today: date) -> dict[IntakeField, str]:
    return {name: resolve_expected(value, today) for name, value in scenario.fields.items()}

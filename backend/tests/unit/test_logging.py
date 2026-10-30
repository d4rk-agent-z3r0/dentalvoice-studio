# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import json
import logging

import pytest

from app.core.logging import REDACTED, configure_logging, get_logger, redact_sensitive


def _last_json_line(text: str) -> dict[str, object]:
    lines = [line for line in text.splitlines() if line.startswith("{")]
    assert lines, f"no JSON log lines in output: {text!r}"
    parsed: dict[str, object] = json.loads(lines[-1])
    return parsed


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "Authorization",
        "ticket",
        "api_key",
        "email",
        "phone",
        "db_password",
        "refresh_token",
        "x-api-key",
        "client_secret",
        "Cookie",
    ],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    event = redact_sensitive(None, "info", {"event": "x", key: "secret-value"})
    assert event[key] == REDACTED


@pytest.mark.parametrize("key", ["conversation_id", "prompt_tokens", "path", "status"])
def test_non_sensitive_keys_are_preserved(key: str) -> None:
    event = redact_sensitive(None, "info", {"event": "x", key: "keep-me"})
    assert event[key] == "keep-me"


def test_nested_mappings_and_sequences_are_redacted() -> None:
    event = redact_sensitive(
        None,
        "info",
        {
            "event": "x",
            "headers": {"authorization": "Bearer abc", "accept": "json"},
            "attempts": [{"api_key": "k1"}, {"status": 401}],
        },
    )
    assert event["headers"] == {"authorization": REDACTED, "accept": "json"}
    assert event["attempts"] == [{"api_key": REDACTED}, {"status": 401}]


def test_structlog_events_are_json_and_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    get_logger("tests").info("login_attempt", email="a@example.com", outcome="ok")

    line = _last_json_line(capsys.readouterr().out)
    assert line["event"] == "login_attempt"
    assert line["email"] == REDACTED
    assert line["outcome"] == "ok"
    assert line["logger"] == "tests"


def test_stdlib_records_are_rendered_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    logging.getLogger("uvicorn.error").warning("worker %s restarted", 3)

    line = _last_json_line(capsys.readouterr().out)
    assert line["event"] == "worker 3 restarted"
    assert line["level"] == "warning"
    assert line["logger"] == "uvicorn.error"


def test_uvicorn_access_log_is_suppressed(capsys: pytest.CaptureFixture[str]) -> None:
    # The access log prints full URLs incl. query strings (where WS tickets travel); the request
    # middleware logs the path only.
    configure_logging("INFO")
    logging.getLogger("uvicorn.access").info("GET /ws?ticket=SECRET 101")

    assert "SECRET" not in capsys.readouterr().out


def test_level_filtering_applies(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING")
    get_logger("tests").info("too_quiet")
    logging.getLogger("sqlalchemy.engine").info("SELECT 1")

    assert capsys.readouterr().out == ""

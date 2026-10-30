import pytest

from app.core.logging import REDACTED, redact_sensitive


@pytest.mark.parametrize(
    "key", ["password", "Authorization", "ticket", "api_key", "email", "phone"]
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    event = redact_sensitive(None, "info", {"event": "x", key: "secret-value"})
    assert event[key] == REDACTED


def test_non_sensitive_keys_are_preserved() -> None:
    event = redact_sensitive(None, "info", {"event": "x", "conversation_id": "c-1"})
    assert event["conversation_id"] == "c-1"

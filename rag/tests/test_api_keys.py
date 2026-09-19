from app.db import parse_api_key


def test_parse_api_key() -> None:
    assert parse_api_key("ga_live_abc_0123456789abcdef") == (
        "abc",
        "0123456789abcdef",
    )


def test_rejects_malformed_api_key() -> None:
    assert parse_api_key("secret") is None
    assert parse_api_key("ga_live_abc_short") is None

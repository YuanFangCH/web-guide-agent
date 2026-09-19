from app.priorities import (
    priority_label,
    priority_name,
    resolve_priority,
)


def test_resolve_priority_prefers_explicit_value() -> None:
    assert resolve_priority("primary", "website") == 1
    assert resolve_priority("secondary", "website") == 2
    assert resolve_priority("1", "upload") == 1
    assert resolve_priority(2, "upload") == 2


def test_resolve_priority_uses_source_defaults() -> None:
    assert resolve_priority(None, "website") == 3
    assert resolve_priority(None, "book:example") == 2
    assert resolve_priority(None, "team-note") == 2


def test_priority_labels() -> None:
    assert priority_name(1) == "primary"
    assert priority_name(99) == "tertiary"
    assert priority_label("primary") == "一级资料"
    assert priority_label(3) == "三级资料"

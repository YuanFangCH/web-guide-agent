from app.actions import parse_action_markers, safe_action


def test_action_whitelist() -> None:
    assert safe_action({"type": "highlight", "anchor": "section-1"}) == {
        "type": "highlight",
        "anchor": "section-1",
    }
    assert safe_action({"type": "open_link", "url": "javascript:alert(1)"}) is None
    assert safe_action({"type": "run_script"}) is None


def test_parse_legacy_markers() -> None:
    actions = parse_action_markers(
        "请查看 [CLIENT_ACTION:scroll] 和 [CLIENT_ACTION:highlight]"
    )

    assert actions == [
        {"type": "scroll"},
        {"type": "highlight"},
    ]

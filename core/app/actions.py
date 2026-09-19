from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import Any

ACTION_TYPES = {"scroll", "highlight", "open_link", "sequential_explain"}
MARKER_RE = re.compile(r"\[CLIENT_ACTION:([a-z_]+)\]", re.IGNORECASE)


def safe_action(action: dict[str, Any]) -> dict[str, Any] | None:
    action_type = str(action.get("type") or "").strip().lower()
    if action_type not in ACTION_TYPES:
        return None
    result = {"type": action_type}
    if action_type in {"scroll", "highlight"}:
        anchor = str(action.get("anchor") or "").strip()
        if not anchor or len(anchor) > 300:
            return None
        result["anchor"] = anchor
    elif action_type == "open_link":
        url = str(action.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        result["url"] = url
    elif action_type == "sequential_explain":
        sections = action.get("sections") or []
        result["sections"] = [
            {
                "anchor": str(section.get("anchor") or "")[:300],
                "heading": str(section.get("heading") or "")[:300],
            }
            for section in sections[:50]
            if section.get("anchor")
        ]
    if action.get("label"):
        result["label"] = str(action["label"])[:300]
    return result


def parse_action_markers(value: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for match in MARKER_RE.finditer(value or ""):
        action_type = match.group(1).lower()
        action = {"type": action_type}
        if action_type in ACTION_TYPES and action not in actions:
            actions.append(action)
    return actions


def merge_actions(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for action in group:
            safe = safe_action(action)
            if not safe:
                continue
            key = repr(sorted(safe.items(), key=lambda item: item[0]))
            if key not in seen:
                seen.add(key)
                merged.append(safe)
    return merged

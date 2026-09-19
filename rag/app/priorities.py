from __future__ import annotations

from typing import Literal

PriorityTier = Literal["primary", "secondary", "tertiary"]

PRIORITY_TO_INT: dict[str, int] = {
    "primary": 1,
    "secondary": 2,
    "tertiary": 3,
}

PRIORITY_NAMES: dict[int, PriorityTier] = {
    1: "primary",
    2: "secondary",
    3: "tertiary",
}

PRIORITY_LABELS: dict[PriorityTier, str] = {
    "primary": "一级资料",
    "secondary": "二级资料",
    "tertiary": "三级资料",
}


def resolve_priority(value: str | int | None, source: str) -> int:
    if isinstance(value, int) and value in PRIORITY_NAMES:
        return value
    if isinstance(value, str) and value in PRIORITY_TO_INT:
        return PRIORITY_TO_INT[value]
    if isinstance(value, str) and value.isdigit() and int(value) in PRIORITY_NAMES:
        return int(value)
    return 3 if source == "website" else 2


def priority_name(value: int | None) -> PriorityTier:
    return PRIORITY_NAMES.get(int(value or 3), "tertiary")


def priority_label(value: int | str | None) -> str:
    if isinstance(value, str):
        return PRIORITY_LABELS.get(value, PRIORITY_LABELS["tertiary"])
    return PRIORITY_LABELS[priority_name(value)]

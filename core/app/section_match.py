from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


ORDINALS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
    "十三": 13,
    "十四": 14,
    "十五": 15,
    "十六": 16,
    "十七": 17,
    "十八": 18,
    "十九": 19,
    "二十": 20,
}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _ordinal_number(question: str) -> int | None:
    match = re.search(
        r"第\s*([0-9]+|[一二两三四五六七八九十]+)\s*(?:章|节|部分|段|篇)",
        question,
    )
    if not match:
        return None
    value = match.group(1)
    if value.isdigit():
        return int(value)
    return ORDINALS.get(value)


def _english_tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9._-]{1,}", value)
    }


def match_section(
    question: str,
    sections: list[dict[str, Any]],
    current_anchor: str | None = None,
) -> dict[str, Any] | None:
    if not sections:
        return None

    ordinal = _ordinal_number(question)
    if ordinal and 1 <= ordinal <= len(sections):
        section = sections[ordinal - 1]
        return {
            "section": section,
            "strategy": "ordinal",
            "score": 1.0,
        }

    normalized_question = _normalize(question)
    title_candidates: list[tuple[float, dict[str, Any]]] = []
    for section in sections:
        heading = _normalize(str(section.get("heading") or ""))
        if heading and heading in normalized_question:
            title_candidates.append((1.0, section))
            continue
        heading_tokens = [
            token
            for token in re.split(r"[\s，。！？、：；·（）()\[\]【】]+", str(section.get("heading") or ""))
            if len(token) >= 2
        ]
        if heading_tokens:
            hits = sum(1 for token in heading_tokens if _normalize(token) in normalized_question)
            if hits:
                title_candidates.append((hits / len(heading_tokens), section))
        if heading:
            similarity = SequenceMatcher(None, heading, normalized_question).ratio()
            if similarity >= 0.35:
                title_candidates.append((similarity, section))
    if title_candidates:
        score, section = max(title_candidates, key=lambda item: item[0])
        return {"section": section, "strategy": "title", "score": score}

    question_tokens = _english_tokens(question)
    if question_tokens:
        english_candidates: list[tuple[float, dict[str, Any]]] = []
        for section in sections:
            heading_tokens = _english_tokens(str(section.get("heading") or ""))
            if not heading_tokens:
                continue
            overlap = len(question_tokens & heading_tokens) / len(
                question_tokens | heading_tokens
            )
            if overlap:
                english_candidates.append((overlap, section))
        if english_candidates:
            score, section = max(english_candidates, key=lambda item: item[0])
            return {"section": section, "strategy": "english", "score": score}

    fuzzy_candidates: list[tuple[float, dict[str, Any]]] = []
    for section in sections:
        haystack = _normalize(
            f"{section.get('heading') or ''}{section.get('text') or ''}"[:800]
        )
        score = SequenceMatcher(None, normalized_question, haystack).ratio()
        if score:
            fuzzy_candidates.append((score, section))
    if fuzzy_candidates:
        score, section = max(fuzzy_candidates, key=lambda item: item[0])
        if score >= 0.12:
            return {"section": section, "strategy": "fuzzy", "score": score}

    if current_anchor:
        current = next(
            (
                section
                for section in sections
                if str(section.get("anchor") or "") == current_anchor
            ),
            None,
        )
        if current:
            return {"section": current, "strategy": "current", "score": 0.0}
    return None

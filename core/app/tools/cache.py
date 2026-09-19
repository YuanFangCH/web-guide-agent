from __future__ import annotations

from typing import Any

from .. import db
from .base import ToolContext, ToolResult, ToolSpec


async def get_cached_page(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    page_key = str(
        arguments.get("pageKey")
        or context.page_context.get("pageKey")
        or ""
    ).strip()
    if not page_key:
        return ToolResult(ok=False, error="page_key_required", content="缺少页面键。")
    page = db.get_page_cache(page_key)
    if not page:
        return ToolResult(
            ok=False,
            error="cache_miss",
            content="页面缓存未命中。",
            data={"cacheHit": False},
        )
    return ToolResult(
        content=(
            f"缓存标题：{page.get('title') or ''}\n"
            f"章节数：{len(page.get('sections') or [])}\n"
            f"正文：\n{str(page.get('page_text') or '')[:18000]}"
        ),
        data={**page, "cacheHit": True},
        meta={"cacheHit": True},
    )


async def get_cached_section(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    page_key = str(
        arguments.get("pageKey")
        or context.page_context.get("pageKey")
        or ""
    ).strip()
    anchor = str(arguments.get("anchor") or "").strip()
    if not page_key or not anchor:
        return ToolResult(
            ok=False,
            error="page_key_and_anchor_required",
            content="缺少页面键或章节锚点。",
        )
    section = db.get_cached_section(page_key, anchor)
    if not section:
        return ToolResult(
            ok=False,
            error="section_cache_miss",
            content="章节缓存未命中。",
            data={"cacheHit": False},
        )

    section_digest = db.section_hash(
        str(section.get("heading") or ""), str(section.get("text") or "")
    )
    cached_answer = db.get_section_answer(
        section_digest, context.prompt_version, context.model
    )
    if cached_answer:
        return ToolResult(
            content=cached_answer["answer"],
            data={
                "cacheHit": True,
                "answerCacheHit": True,
                "section": section,
            },
            sources=cached_answer.get("sources") or [],
            meta={
                "cacheHit": True,
                "answerCacheHit": True,
                "sectionHash": section_digest,
            },
        )
    return ToolResult(
        content=(
            f"章节：{section.get('heading') or ''}\n"
            f"原文：{section.get('text') or ''}"
        ),
        data={
            "cacheHit": True,
            "answerCacheHit": False,
            "section": section,
        },
        meta={
            "cacheHit": True,
            "answerCacheHit": False,
            "sectionHash": section_digest,
        },
    )


TOOLS = {
    "get_cached_page": ToolSpec(
        name="get_cached_page",
        description="按页面键读取已缓存的整页正文和章节。",
        parameters={
            "type": "object",
            "properties": {
                "pageKey": {"type": "string"},
            },
            "additionalProperties": False,
        },
        handler=get_cached_page,
    ),
    "get_cached_section": ToolSpec(
        name="get_cached_section",
        description="按页面键和章节锚点读取缓存章节，可同时命中已有讲解答案。",
        parameters={
            "type": "object",
            "properties": {
                "pageKey": {"type": "string"},
                "anchor": {"type": "string"},
            },
            "required": ["anchor"],
            "additionalProperties": False,
        },
        handler=get_cached_section,
    ),
}

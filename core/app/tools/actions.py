from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .base import ToolContext, ToolResult, ToolSpec


def _anchor(arguments: dict[str, Any]) -> str:
    return str(arguments.get("anchor") or "").strip()[:300]


async def scroll_to_section(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    anchor = _anchor(arguments)
    if not anchor:
        return ToolResult(ok=False, error="anchor_required", content="缺少章节锚点。")
    return ToolResult(
        content=f"已请求滚动到章节 {anchor}。",
        client_actions=[{"type": "scroll", "anchor": anchor}],
    )


async def highlight_section(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    anchor = _anchor(arguments)
    if not anchor:
        return ToolResult(ok=False, error="anchor_required", content="缺少章节锚点。")
    return ToolResult(
        content=f"已请求高亮章节 {anchor}。",
        client_actions=[{"type": "highlight", "anchor": anchor}],
    )


async def open_link(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    url = str(arguments.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ToolResult(ok=False, error="invalid_url", content="链接格式不正确。")
    return ToolResult(
        content=f"已准备打开链接：{url}",
        client_actions=[
            {
                "type": "open_link",
                "url": url,
                "label": str(arguments.get("label") or "")[:300],
            }
        ],
    )


async def explain_sequentially(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    sections = [
        {
            "anchor": str(section.get("anchor") or "")[:300],
            "heading": str(section.get("heading") or "")[:300],
        }
        for section in (context.page_context.get("sections") or [])
        if section.get("anchor")
    ][:30]
    if not sections:
        return ToolResult(ok=False, error="sections_required", content="当前页面没有可讲解章节。")
    return ToolResult(
        content=f"已准备逐段讲解 {len(sections)} 个章节。",
        client_actions=[
            {
                "type": "sequential_explain",
                "sections": sections,
            }
        ],
    )


TOOLS = {
    "scroll_to_section": ToolSpec(
        name="scroll_to_section",
        description="让网页滚动到指定章节。",
        parameters={
            "type": "object",
            "properties": {"anchor": {"type": "string"}},
            "required": ["anchor"],
            "additionalProperties": False,
        },
        handler=scroll_to_section,
    ),
    "highlight_section": ToolSpec(
        name="highlight_section",
        description="让网页高亮指定章节。",
        parameters={
            "type": "object",
            "properties": {"anchor": {"type": "string"}},
            "required": ["anchor"],
            "additionalProperties": False,
        },
        handler=highlight_section,
    ),
    "open_link": ToolSpec(
        name="open_link",
        description="打开公开网页链接。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "label": {"type": "string"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=open_link,
    ),
    "explain_sequentially": ToolSpec(
        name="explain_sequentially",
        description="启动整页逐段讲解流程。",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=explain_sequentially,
    ),
}

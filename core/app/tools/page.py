from __future__ import annotations

import re
from typing import Any

from .base import ToolContext, ToolResult, ToolSpec


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _sections(context: ToolContext) -> list[dict[str, Any]]:
    return [
        {
            "anchor": _clean(section.get("anchor"), 300),
            "heading": _clean(section.get("heading"), 300),
            "text": _clean(section.get("text"), 1500),
        }
        for section in (context.page_context.get("sections") or [])
        if section.get("anchor") or section.get("heading") or section.get("text")
    ]


async def get_page_context(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    page = context.page_context
    sections = _sections(context)
    text = _clean(page.get("text"), 18000)
    return ToolResult(
        content=(
            f"标题：{_clean(page.get('title'), 500)}\n"
            f"地址：{_clean(page.get('url'), 2000)}\n"
            f"章节数：{len(sections)}\n"
            f"正文：\n{text}"
        ),
        data={
            "pageKey": page.get("pageKey"),
            "title": page.get("title"),
            "url": page.get("url"),
            "text": text,
            "sections": sections,
        },
    )


async def list_sections(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    sections = _sections(context)
    lines = [
        f"{index + 1}. {section['heading'] or '未命名章节'} [{section['anchor']}]"
        for index, section in enumerate(sections)
    ]
    return ToolResult(
        content="\n".join(lines) or "当前页面没有可识别章节。",
        data={"sections": sections},
    )


async def summarize_page(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    sections = _sections(context)
    anchor = _clean(arguments.get("anchor"), 300)
    if anchor:
        selected = [
            section for section in sections if section["anchor"] == anchor
        ]
    else:
        selected = sections[:5]

    if selected:
        lines = []
        for section in selected:
            text = re.sub(r"\s+", " ", section["text"]).strip()
            sentences = re.split(r"(?<=[。！？!?])\s*", text)
            summary = "".join(sentences[:2])[:420]
            lines.append(
                f"{section['heading'] or '章节'}：{summary}"
            )
        content = "\n".join(lines)
    else:
        text = re.sub(r"\s+", " ", _clean(context.page_context.get("text"), 5000))
        content = text[:900]
    return ToolResult(content=content or "当前页面没有足够内容可摘要。")


TOOLS = {
    "get_page_context": ToolSpec(
        name="get_page_context",
        description="读取当前网页的标题、地址、正文和章节结构。",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=get_page_context,
    ),
    "list_sections": ToolSpec(
        name="list_sections",
        description="列出当前网页识别到的章节及稳定锚点。",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=list_sections,
    ),
    "summarize_page": ToolSpec(
        name="summarize_page",
        description="对整页或指定章节生成简短导览摘要。",
        parameters={
            "type": "object",
            "properties": {
                "anchor": {
                    "type": "string",
                    "description": "可选章节锚点；不传则摘要整页。",
                }
            },
            "additionalProperties": False,
        },
        handler=summarize_page,
    ),
}

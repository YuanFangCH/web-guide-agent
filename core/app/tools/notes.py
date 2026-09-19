from __future__ import annotations

from typing import Any

from .. import db
from .base import ToolContext, ToolResult, ToolSpec


async def save_research_note(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    if not context.user:
        return ToolResult(ok=False, error="team_login_required", content="需要团队账号。")
    title = str(arguments.get("title") or "").strip()
    content = str(arguments.get("content") or "").strip()
    if not title or not content:
        return ToolResult(
            ok=False,
            error="title_and_content_required",
            content="保存笔记需要标题和内容。",
        )
    note = db.create_note(context.user["id"], title[:300], content[:20000])
    return ToolResult(
        content=f"已保存研究笔记：{note['title']}",
        data={"note": note},
    )


TOOLS = {
    "save_research_note": ToolSpec(
        name="save_research_note",
        description="把研究结论保存为团队研究笔记，不会发布到网站。",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        },
        handler=save_research_note,
        side_effect=True,
    ),
}

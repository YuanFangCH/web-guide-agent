from __future__ import annotations

from typing import Any

from ..document_parser import parse_base64
from .base import ToolContext, ToolResult, ToolSpec


async def parse_document(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    filename = str(arguments.get("filename") or "").strip()
    content_base64 = str(arguments.get("contentBase64") or "").strip()
    content_type = str(arguments.get("contentType") or "").strip()
    if not filename or not content_base64:
        return ToolResult(
            ok=False,
            error="filename_and_content_required",
            content="解析文档需要 filename 和 contentBase64。",
        )
    try:
        parsed = parse_base64(filename, content_base64, content_type)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=str(exc), content=f"文档解析失败：{exc}")
    return ToolResult(
        content=(
            f"文件：{parsed['filename']}\n"
            f"章节数：{len(parsed['sections'])}\n"
            f"正文：\n{parsed['contentText'][:16000]}"
        ),
        data=parsed,
    )


TOOLS = {
    "parse_document": ToolSpec(
        name="parse_document",
        description="解析团队提供的 PDF、DOCX、HTML、Markdown 或文本文件。",
        parameters={
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "contentBase64": {"type": "string"},
                "contentType": {"type": "string"},
            },
            "required": ["filename", "contentBase64"],
            "additionalProperties": False,
        },
        handler=parse_document,
    ),
}

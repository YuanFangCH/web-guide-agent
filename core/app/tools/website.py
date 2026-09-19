from __future__ import annotations

import json
from typing import Any

from .base import ToolContext, ToolResult, ToolSpec


MEMBER_CONTENT_TYPES = {"post", "image"}


def _json_text(value: Any, limit: int = 7000) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)[:limit]


def _created_by(context: ToolContext) -> str | None:
    user = context.user or {}
    return str(user.get("username") or "") or None


async def website_content_search(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    content_type = str(arguments.get("contentType") or "")
    if context.profile == "member" and content_type not in MEMBER_CONTENT_TYPES:
        return ToolResult(
            ok=False,
            error="member_content_type_not_allowed",
            content="团队成员只能查询网站推文和图片，不能查询视频或媒体文件。",
        )
    if context.website_db is None:
        return ToolResult(
            ok=False,
            error="website_database_not_configured",
            content="网站只读数据库未配置。",
        )
    try:
        items = context.website_db.search(
            content_type=content_type,
            query=str(arguments.get("query") or ""),
            status=str(arguments.get("status") or "") or None,
            album=str(arguments.get("album") or "") or None,
            category=str(arguments.get("category") or "") or None,
            tag=str(arguments.get("tag") or "") or None,
            limit=int(arguments.get("limit") or 20),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=str(exc),
            content=f"网站内容查询失败：{exc}",
        )
    return ToolResult(
        content=_json_text(items) if items else "没有找到符合条件的网站内容。",
        data={"items": items},
        sources=[
            {
                "source": "website-db",
                "type": item.get("status") or arguments.get("contentType"),
                "title": item.get("title") or item.get("name") or "",
                "sourceId": item.get("id"),
            }
            for item in items[:8]
        ],
        meta={"count": len(items)},
    )


async def website_content_get(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    content_type = str(arguments.get("contentType") or "")
    if context.profile == "member" and content_type not in MEMBER_CONTENT_TYPES:
        return ToolResult(
            ok=False,
            error="member_content_type_not_allowed",
            content="团队成员只能读取网站推文和图片，不能读取视频或媒体文件。",
        )
    if context.website_db is None:
        return ToolResult(
            ok=False,
            error="website_database_not_configured",
            content="网站只读数据库未配置。",
        )
    try:
        item = context.website_db.get(
            content_type=content_type,
            identifier=str(arguments.get("identifier") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=str(exc),
            content=f"网站内容读取失败：{exc}",
        )
    if not item:
        return ToolResult(ok=False, error="not_found", content="没有找到该网站内容。")
    return ToolResult(content=_json_text(item), data={"item": item})


async def website_content_stats(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    del arguments
    if context.website_db is None:
        return ToolResult(
            ok=False,
            error="website_database_not_configured",
            content="网站只读数据库未配置。",
        )
    try:
        stats = context.website_db.stats()
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=str(exc),
            content=f"网站内容统计失败：{exc}",
        )
    if context.profile == "member":
        stats = {
            key: value
            for key, value in stats.items()
            if key in MEMBER_CONTENT_TYPES
        }
    return ToolResult(content=_json_text(stats), data={"stats": stats})


async def website_draft_create(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    if context.website_write is None or not context.write_session:
        return ToolResult(
            ok=False,
            error="write_session_required",
            content="当前没有有效的网站写入授权会话。",
        )
    payload = arguments.get("payload")
    if not isinstance(payload, dict):
        return ToolResult(ok=False, error="payload_required", content="缺少草稿内容。")
    try:
        result = await context.website_write.create_draft(
            str(arguments.get("contentType") or ""),
            payload,
            created_by=_created_by(context),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=str(exc),
            content=f"创建网站草稿失败：{exc}",
        )
    return ToolResult(
        content=_json_text(result),
        data=result,
        meta={"sideEffect": True},
    )


async def website_draft_update(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    if context.website_write is None or not context.write_session:
        return ToolResult(
            ok=False,
            error="write_session_required",
            content="当前没有有效的网站写入授权会话。",
        )
    payload = arguments.get("payload")
    if not isinstance(payload, dict):
        return ToolResult(ok=False, error="payload_required", content="缺少草稿内容。")
    try:
        result = await context.website_write.update_draft(
            str(arguments.get("contentType") or ""),
            str(arguments.get("id") or ""),
            payload,
            created_by=_created_by(context),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=str(exc),
            content=f"更新网站草稿失败：{exc}",
        )
    return ToolResult(
        content=_json_text(result),
        data=result,
        meta={"sideEffect": True},
    )


async def website_published_update(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    if context.website_write is None or not context.write_session:
        return ToolResult(
            ok=False,
            error="write_session_required",
            content="当前没有有效的网站发布授权会话。",
        )
    payload = arguments.get("payload")
    if not isinstance(payload, dict):
        return ToolResult(ok=False, error="payload_required", content="缺少更新内容。")
    try:
        result = await context.website_write.update_draft(
            str(arguments.get("contentType") or ""),
            str(arguments.get("id") or ""),
            {**payload, "status": "PUBLISHED"},
            created_by=_created_by(context),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=str(exc),
            content=f"更新已发布网站内容失败：{exc}",
        )
    return ToolResult(
        content=_json_text(result),
        data=result,
        meta={"sideEffect": True},
    )


async def website_publish_draft(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    if context.website_write is None or not context.write_session:
        return ToolResult(
            ok=False,
            error="write_session_required",
            content="当前没有有效的网站发布授权会话。",
        )
    try:
        result = await context.website_write.publish_draft(
            str(arguments.get("contentType") or ""),
            str(arguments.get("id") or ""),
            created_by=_created_by(context),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=str(exc),
            content=f"发布网站草稿失败：{exc}",
        )
    return ToolResult(
        content=_json_text(result),
        data=result,
        meta={"sideEffect": True},
    )


CONTENT_TYPE_SCHEMA = {
    "type": "string",
    "enum": ["post", "image", "video", "media", "category", "tag"],
}

TOOLS = {
    "website_content_search": ToolSpec(
        name="website_content_search",
        description="直接查询网站 PostgreSQL 中的内容表，支持文章、图片、视频、媒体、分类和标签。",
        parameters={
            "type": "object",
            "properties": {
                "contentType": CONTENT_TYPE_SCHEMA,
                "query": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["DRAFT", "PUBLISHED", "ARCHIVED"],
                },
                "album": {"type": "string"},
                "category": {"type": "string"},
                "tag": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["contentType"],
            "additionalProperties": False,
        },
        handler=website_content_search,
    ),
    "website_content_get": ToolSpec(
        name="website_content_get",
        description="按 ID 或 slug 读取一条网站内容记录。",
        parameters={
            "type": "object",
            "properties": {
                "contentType": CONTENT_TYPE_SCHEMA,
                "identifier": {"type": "string"},
            },
            "required": ["contentType", "identifier"],
            "additionalProperties": False,
        },
        handler=website_content_get,
    ),
    "website_content_stats": ToolSpec(
        name="website_content_stats",
        description="统计网站内容及不同发布状态的数量。",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=website_content_stats,
    ),
    "website_draft_create": ToolSpec(
        name="website_draft_create",
        description="在有效写授权会话中创建网站文章、图片或视频草稿。",
        parameters={
            "type": "object",
            "properties": {
                "contentType": {
                    "type": "string",
                    "enum": ["post", "image", "video"],
                },
                "payload": {"type": "object"},
            },
            "required": ["contentType", "payload"],
            "additionalProperties": False,
        },
        handler=website_draft_create,
        side_effect=True,
        requires_write=True,
        required_write_mode="draft",
    ),
    "website_draft_update": ToolSpec(
        name="website_draft_update",
        description="更新仍处于草稿状态的网站文章、图片或视频。",
        parameters={
            "type": "object",
            "properties": {
                "contentType": {
                    "type": "string",
                    "enum": ["post", "image", "video"],
                },
                "id": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["contentType", "id", "payload"],
            "additionalProperties": False,
        },
        handler=website_draft_update,
        side_effect=True,
        requires_write=True,
        required_write_mode="draft",
    ),
    "website_published_update": ToolSpec(
        name="website_published_update",
        description=(
            "在发布授权会话中更新仍保持已发布状态的网站文章、图片或视频，"
            "不得修改发布状态。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "contentType": {
                    "type": "string",
                    "enum": ["post", "image", "video"],
                },
                "id": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["contentType", "id", "payload"],
            "additionalProperties": False,
        },
        handler=website_published_update,
        side_effect=True,
        requires_write=True,
        required_write_mode="publish",
    ),
    "website_publish_draft": ToolSpec(
        name="website_publish_draft",
        description=(
            "在发布授权会话中将现有网站文章、图片或视频草稿发布上线；"
            "不能归档、删除或把已发布内容退回草稿。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "contentType": {
                    "type": "string",
                    "enum": ["post", "image", "video"],
                },
                "id": {"type": "string"},
            },
            "required": ["contentType", "id"],
            "additionalProperties": False,
        },
        handler=website_publish_draft,
        side_effect=True,
        requires_write=True,
        required_write_mode="publish",
    ),
}

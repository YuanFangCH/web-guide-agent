#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app import db
from app.website_write import WebsiteWriteClient


def _json_arg(value: str) -> dict[str, Any]:
    path = Path(value)
    raw = path.read_text(encoding="utf-8") if path.exists() else value
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("payload_must_be_object")
    return parsed


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="网页讲解助手网站写入会话与草稿 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    open_parser = subparsers.add_parser("open-session")
    open_parser.add_argument("--minutes", type=int, default=30)
    open_parser.add_argument(
        "--mode",
        choices=["draft-only", "draft-and-publish"],
        default="draft-only",
    )
    open_parser.add_argument("--purpose", default="Codex 网站内容整理")
    open_parser.add_argument("--created-by", default="codex")

    subparsers.add_parser("status")

    revoke_parser = subparsers.add_parser("revoke-session")
    revoke_parser.add_argument("session_id")

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--limit", type=int, default=50)

    create_parser = subparsers.add_parser("create-draft")
    create_parser.add_argument(
        "content_type", choices=["post", "image", "video"]
    )
    create_parser.add_argument("payload", help="JSON 字符串或 JSON 文件路径")

    update_parser = subparsers.add_parser("update-draft")
    update_parser.add_argument(
        "content_type", choices=["post", "image", "video"]
    )
    update_parser.add_argument("content_id")
    update_parser.add_argument("payload", help="JSON 字符串或 JSON 文件路径")

    publish_parser = subparsers.add_parser("publish-draft")
    publish_parser.add_argument(
        "content_type", choices=["post", "image", "video"]
    )
    publish_parser.add_argument("content_id")

    upload_parser = subparsers.add_parser("upload-media")
    upload_parser.add_argument("path")
    upload_parser.add_argument("--content-type", default="")

    args = parser.parse_args()
    db.init_db()
    client = WebsiteWriteClient()

    if args.command == "open-session":
        result = await client.open_session(
            minutes=args.minutes,
            mode=args.mode,
            purpose=args.purpose,
            created_by=args.created_by,
        )
    elif args.command == "status":
        result = client.local_status()
    elif args.command == "revoke-session":
        result = await client.revoke_session(args.session_id)
    elif args.command == "audit":
        result = {"items": await client.list_audit(args.limit)}
    elif args.command == "create-draft":
        result = await client.create_draft(
            args.content_type, _json_arg(args.payload)
        )
    elif args.command == "update-draft":
        result = await client.update_draft(
            args.content_type,
            args.content_id,
            _json_arg(args.payload),
        )
    elif args.command == "publish-draft":
        result = await client.publish_draft(
            args.content_type, args.content_id
        )
    else:
        path = Path(args.path)
        content_type = args.content_type
        if not content_type:
            suffix = path.suffix.lower()
            content_type = (
                "video/mp4"
                if suffix in {".mp4", ".webm"}
                else "image/jpeg"
                if suffix in {".jpg", ".jpeg"}
                else "image/png"
                if suffix == ".png"
                else "application/octet-stream"
            )
        result = await client.upload_media(
            filename=path.name,
            content=path.read_bytes(),
            content_type=content_type,
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(async_main()))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc

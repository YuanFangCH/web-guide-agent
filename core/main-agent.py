#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from app import db
from app.config import settings
from app.kernel import AgentKernel, KernelRequest
from app.llm_client import LLMClient
from app.rag_client import RagClient
from app.tools.registry import ToolRegistry
from app.website_db import website_content_db
from app.website_write import WebsiteWriteClient


def _load_page_context(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def _parse_sse_block(block: str) -> tuple[str, dict[str, Any]]:
    event = "message"
    data_lines: list[str] = []
    for line in block.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    try:
        data = json.loads("\n".join(data_lines)) if data_lines else {}
    except json.JSONDecodeError:
        data = {"text": "\n".join(data_lines)}
    return event, data


async def _ask(
    kernel: AgentKernel,
    *,
    question: str,
    page_context: dict[str, Any],
    conversation_id: str,
    profile: str,
    as_json: bool,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer = ""
    sources: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    buffer = ""

    async for chunk in kernel.stream(
        KernelRequest(
            question=question,
            page_context=page_context,
            conversation_id=conversation_id,
        ),
        profile=profile,
        user=user,
    ):
        buffer += chunk
        boundary = buffer.find("\n\n")
        while boundary >= 0:
            event, data = _parse_sse_block(buffer[:boundary])
            buffer = buffer[boundary + 2 :]
            if event == "token":
                answer += data.get("text", "")
                if not as_json:
                    print(data.get("text", ""), end="", flush=True)
            elif event == "sources":
                sources = data.get("items", [])
            elif event == "actions":
                actions = data.get("items", [])
            elif event == "tool_status":
                tools.append(data)
            elif event == "error" and not as_json:
                print(f"\n错误：{data.get('message')}", file=sys.stderr)
            boundary = buffer.find("\n\n")
    if not as_json:
        print()
    return {
        "answer": answer,
        "sources": sources,
        "actions": actions,
        "tools": tools,
    }


async def _interactive(
    kernel: AgentKernel,
    *,
    page_context: dict[str, Any],
    profile: str,
    user: dict[str, Any] | None,
) -> None:
    conversation_id = db.create_conversation(
        "cli",
        str(page_context.get("url") or ""),
        str(page_context.get("title") or ""),
    )
    print("网页讲解助手 CLI。输入 /tools、/sections、/cache、/exit。")
    while True:
        try:
            question = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not question:
            continue
        if question == "/exit":
            return
        if question == "/tools":
            print(json.dumps(kernel.registry.describe(profile), ensure_ascii=False, indent=2))
            continue
        if question == "/sections":
            print(
                json.dumps(
                    page_context.get("sections") or [],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            continue
        if question == "/cache":
            print(json.dumps(db.page_cache_stats(), ensure_ascii=False, indent=2))
            continue
        await _ask(
            kernel,
            question=question,
            page_context=page_context,
            conversation_id=conversation_id,
            profile=profile,
            as_json=False,
            user=user,
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="网页讲解助手 Agent CLI")
    parser.add_argument("--question", "-q", help="单次提问")
    parser.add_argument("--page-context", help="页面上下文 JSON 或 JSON 文件路径")
    parser.add_argument("--profile", default="cli", choices=["cli", "team", "visitor"])
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()

    db.init_db()
    db.ensure_admin()
    cli_user = db.get_user_by_username(settings.admin_username)
    registry = ToolRegistry.from_file(settings.tool_config_path)
    rag = RagClient()
    try:
        website_content_db.start()
    except Exception:
        pass
    kernel = AgentKernel(
        registry,
        rag,
        LLMClient(),
        website_db=website_content_db,
        website_write=WebsiteWriteClient(),
    )
    page_context = _load_page_context(args.page_context)

    if not args.question:
        await _interactive(
            kernel,
            page_context=page_context,
            profile=args.profile,
            user=cli_user if args.profile == "cli" else None,
        )
        return

    conversation_id = args.conversation_id or db.create_conversation(
        "cli",
        str(page_context.get("url") or ""),
        str(page_context.get("title") or ""),
    )
    result = await _ask(
        kernel,
        question=args.question,
        page_context=page_context,
        conversation_id=conversation_id,
        profile=args.profile,
        as_json=args.json,
        user=cli_user if args.profile == "cli" else None,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

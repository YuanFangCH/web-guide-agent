from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from . import db
from .config import settings
from .rag_client import RagClient
from .web_search import search_web


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _chat_url() -> str:
    base = settings.chat_base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _trim(value: str, limit: int) -> str:
    return value[:limit] if len(value) > limit else value


def _source_payload(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": source.get("id"),
        "sourceType": source.get("source"),
        "title": source.get("title") or "未命名来源",
        "url": source.get("url") or "",
        "anchor": source.get("anchor") or "",
        "sectionTitle": source.get("sectionTitle") or "",
        "score": source.get("score"),
        "priority": source.get("priority"),
        "priorityLabel": source.get("priorityLabel"),
        "bookTitle": source.get("bookTitle"),
        "chapterTitle": source.get("chapterTitle"),
        "pageStart": source.get("pageStart"),
        "pageEnd": source.get("pageEnd"),
        "pageNumber": source.get("pageNumber"),
        "excerpt": _trim(source.get("content") or "", 360),
    }


def _actions_for(
    sources: list[dict[str, Any]], page_context: dict[str, Any]
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    current_url = page_context.get("url") or ""
    for source in sources:
        source_url = source.get("url") or ""
        anchor = source.get("anchor") or ""
        if current_url and source_url == current_url and anchor:
            actions.append(
                {
                    "type": "highlight",
                    "anchor": anchor,
                    "label": source.get("sectionTitle") or source.get("title"),
                }
            )
        elif source_url:
            actions.append(
                {
                    "type": "open_link",
                    "url": source_url,
                    "label": source.get("title"),
                }
            )
    return actions


def _build_messages(
    question: str,
    page_context: dict[str, Any],
    sources: list[dict[str, Any]],
) -> list[dict[str, str]]:
    source_text = "\n\n".join(
        (
            f"[{index + 1}] {source.get('title') or '未命名来源'}\n"
            f"类型：{source.get('source') or 'unknown'}\n"
            f"资料级别：{source.get('priorityLabel') or '未分级'}\n"
            f"书名：{source.get('bookTitle') or ''}\n"
            f"章节：{source.get('sectionTitle') or ''}\n"
            f"链接：{source.get('url') or ''}\n"
            f"内容：{_trim(source.get('content') or '', 1800)}"
        )
        for index, source in enumerate(sources)
    )
    section_text = "\n".join(
        f"- {section.get('heading') or '未命名章节'}: "
        f"{_trim(section.get('text') or '', 700)}"
        for section in (page_context.get("sections") or [])[:12]
    )
    page_text = _trim(page_context.get("text") or "", 12000)
    system = (
        "你是“网页讲解助手”，负责讲解当前网页并检索站内或团队资料。"
        "回答要准确、简洁、使用中文。优先依据给定来源，不得编造不存在的链接、"
        "图片、人物或事实。使用来源时在句末标注 [1]、[2]。如果资料不足，"
        "明确说明缺少哪类资料。站内内容优先于外部资料，外部资料必须标注来源。"
        "资料优先级由高到低为一级资料、二级资料、三级资料；"
        "同等相关时优先使用更高级资料，引用书籍时标明书名、章节和页码。"
        "OCR 文本中的精确引文、数字和人名如无其他依据，不得声称已经人工校对。"
    )
    user = (
        f"当前页面：{page_context.get('title') or ''}\n"
        f"当前地址：{page_context.get('url') or ''}\n"
        f"页面章节：\n{section_text or '无'}\n\n"
        f"页面正文：\n{page_text or '无'}\n\n"
        f"检索来源：\n{source_text or '无'}\n\n"
        f"用户问题：{question}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def _stream_model(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    if not settings.chat_base_url or not settings.chat_model:
        raise RuntimeError("chat_model_not_configured")
    payload = {
        "model": settings.chat_model,
        "messages": messages,
        "stream": True,
        "temperature": 0.2,
    }
    headers = {"Content-Type": "application/json"}
    if settings.chat_api_key:
        headers["Authorization"] = f"Bearer {settings.chat_api_key}"

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST", _chat_url(), headers=headers, json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {}).get("content")
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    continue
                if isinstance(delta, list):
                    delta = "".join(
                        item.get("text", "")
                        for item in delta
                        if isinstance(item, dict)
                    )
                if delta:
                    yield str(delta)


def _fallback_answer(
    question: str, page_context: dict[str, Any], sources: list[dict[str, Any]]
) -> str:
    if sources:
        lines = ["根据当前知识库检索到的资料："]
        for index, source in enumerate(sources[:3], start=1):
            excerpt = _trim((source.get("content") or "").replace("\n", " "), 220)
            lines.append(f"{index}. {excerpt} [{index}]")
        lines.append("以上内容来自当前检索结果；如需更完整答案，请配置网页讲解助手模型接口。")
        return "\n\n".join(lines)
    page_text = _trim((page_context.get("text") or "").replace("\n", " "), 500)
    if page_text:
        return (
            f"当前知识库没有找到足够依据。你正在查看“"
            f"{page_context.get('title') or '当前页面'}”，页面可读内容摘要为："
            f"{page_text}。"
        )
    return "当前知识库没有找到足够依据，且网页讲解助手模型接口尚未配置。"


async def stream_chat(
    *,
    question: str,
    page_context: dict[str, Any],
    conversation_id: str,
    visitor_id: str,
    rag: RagClient,
) -> AsyncIterator[str]:
    sources = await rag.retrieve(question, top_k=8)
    if not sources and settings.web_search_provider:
        sources = await search_web(question, max_results=5)
    source_payloads = [_source_payload(source) for source in sources]
    yield sse_event(
        "meta",
        {
            "conversationId": conversation_id,
            "sourceCount": len(source_payloads),
            "webSearchProvider": settings.web_search_provider or None,
        },
    )
    yield sse_event("sources", {"items": source_payloads})

    answer_parts: list[str] = []
    try:
        async for token in _stream_model(
            _build_messages(question, page_context, sources)
        ):
            answer_parts.append(token)
            yield sse_event("token", {"text": token})
    except Exception as exc:  # noqa: BLE001
        answer_parts.append(_fallback_answer(question, page_context, sources))
        yield sse_event(
            "token",
            {"text": answer_parts[-1], "fallback": True, "reason": str(exc)},
        )

    actions = _actions_for(sources, page_context)
    yield sse_event("actions", {"items": actions})
    answer = "".join(answer_parts).strip()
    yield sse_event("done", {"answer": answer})

    await asyncio.to_thread(
        db.append_message, conversation_id, "user", question, []
    )
    await asyncio.to_thread(
        db.append_message, conversation_id, "assistant", answer, source_payloads
    )

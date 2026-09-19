from __future__ import annotations

from typing import Any

from ..config import settings
from ..url_safety import UnsafeUrlError, fetch_public_url
from ..web_search import search_web
from .base import ToolContext, ToolResult, ToolSpec


async def rag_search(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    query = str(arguments.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, error="query_required", content="缺少检索词。")
    top_k = min(max(int(arguments.get("topK") or 8), 1), 20)
    items = await context.rag_client.retrieve(query, top_k=top_k)
    lines = [
        f"[{index + 1}] {item.get('title') or ''} · "
        f"{item.get('sectionTitle') or ''}\n{str(item.get('content') or '')[:1800]}"
        for index, item in enumerate(items)
    ]
    return ToolResult(
        content="\n\n".join(lines) or "站内知识库没有找到相关结果。",
        data={"items": items},
        sources=items,
        meta={"count": len(items)},
    )


async def web_search(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    if not settings.web_search_provider:
        return ToolResult(
            ok=False,
            error="web_search_not_configured",
            content="外网搜索未配置。",
        )
    query = str(arguments.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, error="query_required", content="缺少检索词。")
    items = await search_web(query, max_results=5)
    return ToolResult(
        content="\n\n".join(
            f"{index + 1}. {item.get('title')}\n{item.get('content')}\n{item.get('url')}"
            for index, item in enumerate(items)
        )
        or "外网搜索没有返回结果。",
        data={"items": items},
        sources=items,
    )


async def fetch_url(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    url = str(arguments.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, error="url_required", content="缺少 URL。")
    try:
        final_url, content_type, content = await fetch_public_url(url)
    except UnsafeUrlError as exc:
        return ToolResult(ok=False, error=str(exc), content=f"URL 不可访问：{exc}")

    if content_type.startswith("text/html"):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
        for element in soup(["script", "style", "noscript", "svg"]):
            element.decompose()
        title = soup.title.get_text(strip=True) if soup.title else final_url
        text = soup.get_text("\n", strip=True)
    else:
        title = final_url
        text = content.decode("utf-8", errors="replace")
    text = text[:12000]
    return ToolResult(
        content=f"标题：{title}\n地址：{final_url}\n正文：\n{text}",
        data={"title": title, "url": final_url, "text": text},
        sources=[{"title": title, "url": final_url, "source": "web"}],
    )


TOOLS = {
    "rag_search": ToolSpec(
        name="rag_search",
        description="检索网站与团队知识库，返回带来源的内容片段。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "topK": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=rag_search,
    ),
    "web_search": ToolSpec(
        name="web_search",
        description="在站内资料不足时搜索公开网页。",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=web_search,
    ),
    "fetch_url": ToolSpec(
        name="fetch_url",
        description="读取公开 HTTP/HTTPS 网页正文。",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=fetch_url,
    ),
}

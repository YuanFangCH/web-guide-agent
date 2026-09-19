from __future__ import annotations

from typing import Any

import httpx

from .config import settings


async def search_web(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    provider = settings.web_search_provider.lower()
    if not provider:
        return []

    async with httpx.AsyncClient(timeout=20) as client:
        if provider == "tavily":
            response = await client.post(
                settings.web_search_base_url or "https://api.tavily.com/search",
                json={
                    "api_key": settings.web_search_api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            response.raise_for_status()
            rows = response.json().get("results", [])
        elif provider == "serper":
            response = await client.post(
                settings.web_search_base_url or "https://google.serper.dev/search",
                headers={"X-API-KEY": settings.web_search_api_key},
                json={"q": query, "num": max_results},
            )
            response.raise_for_status()
            rows = response.json().get("organic", [])
        elif provider == "searxng":
            if not settings.web_search_base_url:
                raise RuntimeError("WEB_SEARCH_BASE_URL is required for SearXNG")
            response = await client.get(
                f"{settings.web_search_base_url}/search",
                params={"q": query, "format": "json"},
            )
            response.raise_for_status()
            rows = response.json().get("results", [])
        else:
            raise RuntimeError(f"unsupported_web_search_provider:{provider}")

    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:max_results]):
        results.append(
            {
                "id": f"web:{index}",
                "source": "web",
                "title": row.get("title") or row.get("name") or "外部网页",
                "url": row.get("url") or row.get("link") or "",
                "content": row.get("content")
                or row.get("snippet")
                or row.get("description")
                or "",
                "score": None,
                "anchor": "",
                "sectionTitle": "",
            }
        )
    return results

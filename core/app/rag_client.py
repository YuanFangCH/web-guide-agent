from __future__ import annotations

from typing import Any

import httpx

from .config import settings


class RagClient:
    def __init__(self) -> None:
        self.base_url = settings.rag_base_url
        self.headers = {"Authorization": f"Bearer {settings.rag_service_token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=self.headers,
                json=json,
                files=files,
                data=data,
            )
            response.raise_for_status()
            return response.json()

    async def retrieve(
        self, query: str, top_k: int = 8, source_filter: str | None = None
    ) -> list[dict[str, Any]]:
        payload = await self._request(
            "POST",
            "/internal/retrieve",
            json={
                "query": query,
                "topK": top_k,
                "sourceFilter": source_filter,
            },
        )
        return payload.get("items", [])

    async def upsert_batch(
        self, items: list[dict[str, Any]], *, replace_source: bool = False
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/guide-agent/v1/documents/batch",
            json={"items": items, "replaceSource": replace_source},
        )

    async def ingest_urls(
        self, urls: list[str], metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/guide-agent/v1/ingestions/url",
            json={"urls": urls, "source": "url", "metadata": metadata or {}},
        )

    async def ingest_file(
        self, filename: str, content: bytes, content_type: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/guide-agent/v1/ingestions/file",
            files={"file": (filename, content, content_type)},
        )

    async def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET", f"/internal/documents?limit={limit}"
        )
        return payload.get("items", [])

    async def list_api_keys(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/internal/api-keys")
        return payload.get("items", [])

    async def create_api_key(
        self, name: str, scopes: list[str]
    ) -> dict[str, Any]:
        return await self._request(
            "POST", "/internal/api-keys", json={"name": name, "scopes": scopes}
        )

    async def revoke_api_key(self, key_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/internal/api-keys/{key_id}")

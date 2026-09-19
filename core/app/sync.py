from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from . import db
from .config import settings
from .rag_client import RagClient


class WebsiteSynchronizer:
    def __init__(self, rag: RagClient) -> None:
        self.rag = rag
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self.last_error: str | None = None

    def start(self) -> None:
        if settings.website_sync_enabled and self._task is None:
            self._task = asyncio.create_task(
                self._run_loop(), name="guide-agent-website-sync"
            )

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            await self._task

    async def _run_loop(self) -> None:
        await asyncio.sleep(2)
        while not self._stopping.is_set():
            attempt_started_at = datetime.now(timezone.utc).isoformat()
            try:
                await self.sync(manifest=False)
            except Exception as exc:  # noqa: BLE001
                last_success = db.get_sync_state("website_last_sync_at")
                if not last_success or last_success < attempt_started_at:
                    self.last_error = str(exc)
                    await asyncio.to_thread(
                        db.set_sync_state, "website_last_error", self.last_error
                    )
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=settings.website_sync_interval_seconds,
                )
            except TimeoutError:
                pass

    async def sync(self, *, manifest: bool = False) -> dict[str, Any]:
        if not settings.website_export_base_url or not settings.website_export_token:
            raise RuntimeError("website_export_not_configured")
        if self._lock.locked():
            raise RuntimeError("sync_already_running")

        async with self._lock:
            started_at = datetime.now(timezone.utc)
            cursor = None if manifest else db.get_sync_state("website_cursor")
            mode = "manifest" if manifest else "incremental"
            items: list[dict[str, Any]] = []
            next_cursor: str | None = None

            async with httpx.AsyncClient(timeout=120) as client:
                while True:
                    params = {"mode": mode, "limit": "500"}
                    if cursor:
                        params["cursor"] = cursor
                    response = await client.get(
                        f"{settings.website_export_base_url}/api/agent-export/v1/content",
                        params=params,
                        headers={
                            "Authorization": f"Bearer {settings.website_export_token}"
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    items.extend(payload.get("items", []))
                    next_cursor = payload.get("nextCursor")
                    if not payload.get("hasMore"):
                        break
                    cursor = next_cursor

            if items:
                await self.rag.upsert_batch(
                    items, replace_source=manifest
                )
            if next_cursor and not manifest:
                await asyncio.to_thread(
                    db.set_sync_state, "website_cursor", next_cursor
                )
            elif manifest and items:
                last_item = items[-1]
                manifest_cursor = base64.urlsafe_b64encode(
                    json.dumps(
                        {
                            "updatedAt": last_item["updatedAt"],
                            "sourceId": last_item["sourceId"],
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).decode("ascii").rstrip("=")
                await asyncio.to_thread(
                    db.set_sync_state, "website_cursor", manifest_cursor
                )
            finished_at = datetime.now(timezone.utc)
            await asyncio.to_thread(
                db.set_sync_state, "website_last_sync_at", finished_at.isoformat()
            )
            await asyncio.to_thread(
                db.set_sync_state, "website_last_sync_count", str(len(items))
            )
            await asyncio.to_thread(db.set_sync_state, "website_last_error", "")
            self.last_error = None
            return {
                "mode": mode,
                "items": len(items),
                "startedAt": started_at.isoformat(),
                "finishedAt": finished_at.isoformat(),
            }

    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.website_sync_enabled,
            "running": self._lock.locked(),
            "lastSyncAt": db.get_sync_state("website_last_sync_at"),
            "lastSyncCount": db.get_sync_state("website_last_sync_count"),
            "lastError": db.get_sync_state("website_last_error"),
            "cursor": db.get_sync_state("website_cursor"),
            "intervalSeconds": settings.website_sync_interval_seconds,
            "manifestIntervalSeconds": settings.website_manifest_interval_seconds,
        }

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from . import db
from .chunking import build_chunks
from .config import settings
from .parsers import html_to_text, parse_file_bytes
from .url_safety import fetch_public_url
from .vector_store import RagIndex


class JobWorker:
    def __init__(self, rag_index: RagIndex) -> None:
        self.rag_index = rag_index
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="guide-agent-rag-worker")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            await self._task

    async def _run(self) -> None:
        while not self._stopping.is_set():
            job = await asyncio.to_thread(db.claim_job)
            if not job:
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=1.0)
                except TimeoutError:
                    pass
                continue

            try:
                result = await self._process(job)
                await asyncio.to_thread(db.complete_job, job["id"], result)
            except Exception as exc:  # noqa: BLE001
                if job.get("document_id"):
                    await asyncio.to_thread(
                        db.set_document_status,
                        job["document_id"],
                        "failed",
                        str(exc),
                    )
                await asyncio.to_thread(db.fail_job, job["id"], str(exc))

    async def _process(self, job: dict[str, Any]) -> dict[str, Any]:
        kind = job["kind"]
        payload = job.get("payload") or {}
        document_id_value = job.get("document_id")

        if kind == "document":
            if not document_id_value:
                raise ValueError("document_id_required")
            return await self._index_document(document_id_value)

        if kind == "url":
            if not document_id_value:
                raise ValueError("document_id_required")
            url = str(payload["url"])
            final_url, content_type, content = await fetch_public_url(
                url, max_bytes=settings.max_upload_bytes
            )
            if (content_type or "").startswith("text/html"):
                html = content.decode("utf-8", errors="replace")
                title = _html_title(html) or final_url
                parsed = {
                    "contentHtml": html,
                    "contentText": html_to_text(html),
                    "sections": None,
                }
                from .parsers import extract_sections_from_html

                parsed["sections"] = extract_sections_from_html(html)
            else:
                parsed = parse_file_bytes(final_url, content, content_type)
                title = final_url
            await asyncio.to_thread(
                db.update_document_content,
                document_id_value,
                title=title,
                content_html=parsed.get("contentHtml", ""),
                content_text=parsed.get("contentText", ""),
                sections=parsed.get("sections", []),
                metadata={**(payload.get("metadata") or {}), "finalUrl": final_url},
            )
            return await self._index_document(document_id_value)

        if kind == "file":
            if not document_id_value:
                raise ValueError("document_id_required")
            path = Path(str(payload["path"]))
            content = await asyncio.to_thread(path.read_bytes)
            parsed = parse_file_bytes(
                str(payload.get("filename") or path.name),
                content,
                str(payload.get("contentType") or ""),
            )
            await asyncio.to_thread(
                db.update_document_content,
                document_id_value,
                title=payload.get("title") or payload.get("filename") or path.name,
                content_html=parsed.get("contentHtml", ""),
                content_text=parsed.get("contentText", ""),
                sections=parsed.get("sections", []),
                metadata=payload.get("metadata") or {},
            )
            return await self._index_document(document_id_value)

        if kind == "delete_document":
            if not document_id_value:
                raise ValueError("document_id_required")
            document = await asyncio.to_thread(db.get_document, document_id_value)
            if document:
                await asyncio.to_thread(
                    self.rag_index.delete_chunks, document.get("chunk_ids") or []
                )
                await asyncio.to_thread(db.finish_document_delete, document_id_value)
            return {"deleted": document_id_value}

        raise ValueError(f"unknown_job_kind:{kind}")

    async def _index_document(self, document_id_value: str) -> dict[str, Any]:
        document = await asyncio.to_thread(db.get_document, document_id_value)
        if not document:
            raise ValueError("document_not_found")
        if document.get("deleted_at"):
            await asyncio.to_thread(
                self.rag_index.delete_chunks, document.get("chunk_ids") or []
            )
            await asyncio.to_thread(db.finish_document_delete, document_id_value)
            return {"documentId": document_id_value, "deleted": True, "chunks": 0}

        chunks = build_chunks(document)
        if not chunks:
            raise ValueError("document_has_no_indexable_text")
        old_chunk_ids = document.get("chunk_ids") or []
        new_chunk_ids = await asyncio.to_thread(
            self.rag_index.index_document, old_chunk_ids, chunks
        )
        await asyncio.to_thread(db.set_document_ready, document_id_value, new_chunk_ids)
        return {
            "documentId": document_id_value,
            "chunks": len(new_chunk_ids),
            "checksum": document.get("checksum"),
        }


def _html_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


def source_id_for_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()

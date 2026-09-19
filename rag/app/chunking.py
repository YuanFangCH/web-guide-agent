from __future__ import annotations

import hashlib
import re
from typing import Any


def _split_text(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            candidates = [
                text.rfind(mark, start, end)
                for mark in ("。", "！", "？", ".", "!", "?", "\n")
            ]
            boundary = max(candidates)
            if boundary > start + max_chars // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_chunks(document: dict[str, Any]) -> list[dict[str, Any]]:
    sections = document.get("sections") or []
    if not sections:
        sections = [
            {
                "anchor": "section-1",
                "heading": document.get("title", ""),
                "text": document.get("content_text") or document.get("contentText") or "",
            }
        ]

    chunks: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections):
        text = (section.get("text") or "").strip()
        heading = (section.get("heading") or "").strip()
        if heading:
            text = f"{heading}\n{text}".strip()
        for chunk_index, chunk in enumerate(_split_text(text)):
            chunk_id = hashlib.sha256(
                (
                    f"{document['id']}:{section.get('anchor', section_index)}:"
                    f"{chunk_index}"
                ).encode("utf-8")
            ).hexdigest()
            metadata = document.get("metadata") or {}
            page_match = re.fullmatch(r"第\s*(\d+)\s*页", heading)
            knowledge_priority = str(document.get("knowledge_priority") or 3)
            chunks.append(
                {
                    "id": chunk_id,
                    "content": chunk,
                    "meta": {
                        "document_id": document["id"],
                        "source": document["source"],
                        "source_id": document["source_id"],
                        "type": document["type"],
                        "title": document.get("title", ""),
                        "url": document.get("url", ""),
                        "anchor": section.get("anchor", f"section-{section_index + 1}"),
                        "section_title": heading,
                        "published_at": str(metadata.get("publishedAt") or ""),
                        "album": str(metadata.get("album") or ""),
                        "category": str(metadata.get("category") or ""),
                        "tags": ", ".join(metadata.get("tags") or []),
                        "chunk_index": chunk_index,
                        "knowledge_priority": knowledge_priority,
                        "priority_label": {
                            "1": "一级资料",
                            "2": "二级资料",
                            "3": "三级资料",
                        }.get(knowledge_priority, "三级资料"),
                        "book_key": str(metadata.get("bookKey") or ""),
                        "book_title": str(metadata.get("bookTitle") or ""),
                        "book_author": str(metadata.get("bookAuthor") or ""),
                        "book_isbn": str(metadata.get("bookIsbn") or ""),
                        "chapter_id": str(metadata.get("chapterId") or ""),
                        "chapter_title": str(metadata.get("chapterTitle") or ""),
                        "page_start": str(metadata.get("pageStart") or ""),
                        "page_end": str(metadata.get("pageEnd") or ""),
                        "page_number": page_match.group(1) if page_match else "",
                        "priority_reason": str(metadata.get("priorityReason") or ""),
                    },
                }
            )
    return chunks

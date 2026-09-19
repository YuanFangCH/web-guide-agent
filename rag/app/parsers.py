from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from pypdf import PdfReader


def normalize_text(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\s*\n\s*", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _heading_for(element: Any) -> str:
    explicit = element.get("data-agent-title")
    if explicit:
        return normalize_text(str(explicit))
    heading = element.find(["h1", "h2", "h3"])
    if heading:
        return normalize_text(heading.get_text(" ", strip=True))
    return ""


def _fallback_sections(text: str, max_chars: int = 900) -> list[dict[str, str]]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    paragraphs = [
        part.strip()
        for part in re.split(r"\n+|(?<=[。！？!?])\s+", normalized)
        if part.strip()
    ]
    sections: list[dict[str, str]] = []
    buffer = ""
    for paragraph in paragraphs or [normalized]:
        if buffer and len(buffer) + len(paragraph) + 1 > max_chars:
            sections.append(
                {
                    "anchor": f"section-{len(sections) + 1}",
                    "heading": "",
                    "text": buffer,
                }
            )
            buffer = paragraph
        else:
            buffer = f"{buffer}\n{paragraph}".strip()
    if buffer:
        sections.append(
            {
                "anchor": f"section-{len(sections) + 1}",
                "heading": "",
                "text": buffer,
            }
        )
    return sections


def extract_sections_from_html(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()

    explicit = soup.select("[data-agent-section]")
    if explicit:
        return [
            {
                "anchor": str(
                    element.get("data-agent-section") or f"section-{index + 1}"
                ),
                "heading": _heading_for(element),
                "text": normalize_text(element.get_text("\n", strip=True)),
            }
            for index, element in enumerate(explicit)
            if normalize_text(element.get_text("\n", strip=True))
        ]

    headings = soup.find_all(["h1", "h2", "h3"])
    if headings:
        sections: list[dict[str, str]] = []
        for index, heading in enumerate(headings):
            texts: list[str] = []
            for sibling in heading.next_siblings:
                if getattr(sibling, "name", None) in {"h1", "h2", "h3"}:
                    break
                if hasattr(sibling, "get_text"):
                    text = normalize_text(sibling.get_text("\n", strip=True))
                    if text:
                        texts.append(text)
            sections.append(
                {
                    "anchor": str(heading.get("id") or f"section-{index + 1}"),
                    "heading": normalize_text(heading.get_text(" ", strip=True)),
                    "text": normalize_text("\n".join(texts)),
                }
            )
        return sections

    containers = soup.find_all(["section", "article"])
    if len(containers) > 1:
        return [
            {
                "anchor": str(
                    element.get("id") or f"section-{index + 1}"
                ),
                "heading": _heading_for(element),
                "text": normalize_text(element.get_text("\n", strip=True)),
            }
            for index, element in enumerate(containers)
            if normalize_text(element.get_text("\n", strip=True))
        ]

    return _fallback_sections(soup.get_text("\n", strip=True))


def html_to_text(html: str) -> str:
    sections = extract_sections_from_html(html)
    if sections:
        return normalize_text(
            "\n\n".join(
                "\n".join(
                    value
                    for value in (section.get("heading", ""), section.get("text", ""))
                    if value
                )
                for section in sections
            )
        )
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()
    return normalize_text(soup.get_text("\n", strip=True))


def parse_file_bytes(
    filename: str, content: bytes, content_type: str | None = None
) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" or content_type == "application/pdf":
        reader = PdfReader(io.BytesIO(content))
        text = normalize_text("\n\n".join(page.extract_text() or "" for page in reader.pages))
        return {"contentHtml": "", "contentText": text, "sections": _fallback_sections(text)}

    if suffix == ".docx" or content_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    }:
        document = DocxDocument(io.BytesIO(content))
        text = normalize_text("\n\n".join(p.text for p in document.paragraphs if p.text))
        return {"contentHtml": "", "contentText": text, "sections": _fallback_sections(text)}

    if suffix in {".html", ".htm"} or (content_type or "").startswith("text/html"):
        html = content.decode("utf-8", errors="replace")
        sections = extract_sections_from_html(html)
        return {
            "contentHtml": html,
            "contentText": html_to_text(html),
            "sections": sections,
        }

    if suffix in {".md", ".markdown", ".txt", ".csv", ".json"} or (
        content_type or ""
    ).startswith("text/"):
        text = normalize_text(content.decode("utf-8", errors="replace"))
        return {"contentHtml": "", "contentText": text, "sections": _fallback_sections(text)}

    raise ValueError(f"unsupported_file_type:{suffix or content_type or 'unknown'}")

from __future__ import annotations

import base64
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


def sections_from_text(text: str, max_chars: int = 1500) -> list[dict[str, str]]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    paragraphs = [
        item.strip()
        for item in re.split(r"\n+|(?<=[。！？!?])\s+", normalized)
        if item.strip()
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


def parse_bytes(
    filename: str, content: bytes, content_type: str = ""
) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" or content_type == "application/pdf":
        reader = PdfReader(io.BytesIO(content))
        text = normalize_text(
            "\n\n".join(page.extract_text() or "" for page in reader.pages)
        )
    elif suffix == ".docx" or content_type.endswith(
        "wordprocessingml.document"
    ):
        document = DocxDocument(io.BytesIO(content))
        text = normalize_text(
            "\n\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text)
        )
    elif suffix in {".html", ".htm"} or content_type.startswith("text/html"):
        soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
        for element in soup(["script", "style", "noscript", "svg"]):
            element.decompose()
        text = normalize_text(soup.get_text("\n", strip=True))
    else:
        text = normalize_text(content.decode("utf-8", errors="replace"))
    return {
        "filename": filename,
        "contentText": text,
        "sections": sections_from_text(text),
    }


def parse_base64(
    filename: str, content_base64: str, content_type: str = ""
) -> dict[str, Any]:
    return parse_bytes(filename, base64.b64decode(content_base64), content_type)

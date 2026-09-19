from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup


def _clean_download_html(content: str) -> str:
    soup = BeautifulSoup(content or "", "html.parser")
    for tag in soup(["script", "iframe", "object", "embed", "form", "input"]):
        tag.decompose()
    for tag in soup.find_all(True):
        for attribute in list(tag.attrs):
            lowered = attribute.lower()
            if lowered.startswith("on") or lowered == "srcdoc":
                del tag.attrs[attribute]
                continue
            if lowered in {"href", "src"}:
                value = str(tag.attrs.get(attribute) or "").strip().lower()
                if value.startswith("javascript:"):
                    del tag.attrs[attribute]
    return str(soup)


def build_post_download_html(
    post: dict[str, Any], *, site_url: str = ""
) -> bytes:
    title = str(post.get("title") or post.get("slug") or "网站推文")
    summary = str(post.get("summary") or "")
    published_at = str(post.get("publishedAt") or "")
    category = str(post.get("categoryName") or "")
    body = _clean_download_html(str(post.get("content") or ""))
    base_url = f"{site_url.rstrip('/')}/" if site_url else ""
    metadata = " · ".join(
        item for item in (category, published_at) if item
    )
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {f'<base href="{html.escape(base_url, quote=True)}">' if base_url else ''}
  <title>{html.escape(title)}</title>
  <style>
    body {{ max-width: 900px; margin: 0 auto; padding: 32px 18px 64px; color: #172033; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; line-height: 1.8; }}
    header {{ margin-bottom: 28px; padding-bottom: 18px; border-bottom: 1px solid #d8e0ea; }}
    h1 {{ margin: 0 0 10px; font-size: 30px; line-height: 1.35; }}
    .meta, .summary {{ color: #607086; }}
    .summary {{ margin: 10px 0 0; }}
    img, video {{ max-width: 100%; height: auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #d8e0ea; padding: 7px; }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    {f'<div class="meta">{html.escape(metadata)}</div>' if metadata else ''}
    {f'<p class="summary">{html.escape(summary)}</p>' if summary else ''}
  </header>
  <main>{body}</main>
</body>
</html>
"""
    return document.encode("utf-8")


def content_disposition(filename: str, fallback: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "-", fallback).strip("-._")
    if not ascii_name:
        ascii_name = "download"
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )

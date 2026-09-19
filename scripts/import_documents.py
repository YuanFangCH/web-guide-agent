from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DocumentConfig:
    key: str
    source: str
    path: Path
    priority: str


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_checksum(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def document_id(source: str, source_id: str) -> str:
    return hashlib.sha256(f"{source}\0{source_id}".encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_pages(book_dir: Path, start_page: int, end_page: int) -> list[dict[str, str]]:
    pages: list[dict[str, str]] = []
    pages_dir = book_dir / "text_raw" / "pages_text"
    for page_number in range(start_page, end_page + 1):
        path = pages_dir / f"page_{page_number:03d}.txt"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            pages.append(
                {
                    "anchor": f"page-{page_number:03d}",
                    "heading": f"Page {page_number}",
                    "text": text,
                }
            )
    return pages


def build_documents(config: DocumentConfig) -> list[dict[str, Any]]:
    knowledge_base = load_json(
        config.path / "knowledge_base" / "knowledge_base.json"
    )
    metadata = knowledge_base["metadata"]
    book_title = str(metadata["title"])
    created_at = str(metadata.get("created_at") or "1970-01-01")
    source_updated_at = f"{created_at}T00:00:00+00:00"
    documents: list[dict[str, Any]] = []

    for chunk in knowledge_base["chunks"]:
        chapter_id = str(chunk["chapter_id"])
        chapter_title = str(chunk["chapter_title"])
        start_page = int(chunk["start_page"])
        end_page = int(chunk["end_page"])
        source_id = f"{config.key}:{chunk['id']}"
        sections = load_pages(config.path, start_page, end_page)
        if not sections:
            sections = [
                {
                    "anchor": str(chunk["id"]),
                    "heading": chapter_title,
                    "text": str(chunk["content"]),
                }
            ]
        title = f"{book_title} | {chapter_title} | pages {start_page}-{end_page}"
        document_metadata = {
            "bookKey": config.key,
            "bookTitle": book_title,
            "bookAuthor": str(metadata.get("author") or ""),
            "bookPublisher": str(metadata.get("publisher") or ""),
            "bookPublishDate": str(metadata.get("publish_date") or ""),
            "bookIsbn": str(metadata.get("isbn") or ""),
            "chapterId": chapter_id,
            "chapterTitle": chapter_title,
            "pageStart": start_page,
            "pageEnd": end_page,
            "sourcePath": str(config.path),
            "ocrQualityNotice": "OCR-derived text should be checked against the source.",
        }
        documents.append(
            {
                "source": config.source,
                "sourceId": source_id,
                "type": "document",
                "title": title,
                "url": "",
                "contentHtml": "",
                "contentText": str(chunk["content"]),
                "sections": sections,
                "metadata": document_metadata,
                "priority": config.priority,
                "checksum": stable_checksum(
                    {
                        "title": title,
                        "contentText": chunk["content"],
                        "sections": sections,
                        "metadata": document_metadata,
                        "priority": config.priority,
                    }
                ),
                "updatedAt": source_updated_at,
            }
        )
    return documents


def build_manifest(
    documents_by_source: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    summary: dict[str, dict[str, int]] = {}
    for key, documents in documents_by_source.items():
        counts = {"primary": 0, "secondary": 0, "tertiary": 0}
        for document in documents:
            priority = str(document["priority"])
            counts[priority] += 1
            metadata = document["metadata"]
            items.append(
                {
                    "key": key,
                    "source": document["source"],
                    "sourceId": document["sourceId"],
                    "title": document["title"],
                    "chapterId": metadata["chapterId"],
                    "chapterTitle": metadata["chapterTitle"],
                    "pageStart": metadata["pageStart"],
                    "pageEnd": metadata["pageEnd"],
                    "priority": priority,
                }
            )
        summary[key] = {
            "total": len(documents),
            "primary": counts["primary"],
            "secondary": counts["secondary"],
            "tertiary": counts["tertiary"],
        }
    return {"summary": summary, "items": items}


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


class AgentApi:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {"Authorization": f"Bearer {self.token}"}
        if payload is not None:
            body = stable_json(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc

    def import_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        return self.request(
            "POST",
            "/api/guide-agent/v1/documents/batch",
            {"items": documents, "replaceSource": True},
        )

    def wait_for_jobs(
        self, job_ids: list[str], timeout_seconds: int = 900
    ) -> list[dict[str, Any]]:
        pending = set(job_ids)
        results: dict[str, dict[str, Any]] = {}
        deadline = time.monotonic() + timeout_seconds
        while pending and time.monotonic() < deadline:
            for job_id in list(pending):
                job = self.request(
                    "GET", f"/api/guide-agent/v1/ingestions/{job_id}"
                )
                if job["status"] in {"succeeded", "failed"}:
                    results[job_id] = job
                    pending.remove(job_id)
            if pending:
                time.sleep(0.5)
        if pending:
            raise TimeoutError(f"timed out waiting for {len(pending)} jobs")
        return list(results.values())

    def remove_documents(self, documents: list[dict[str, Any]]) -> int:
        removed = 0
        for document in documents:
            doc_id = document_id(document["source"], document["sourceId"])
            try:
                self.request("DELETE", f"/api/guide-agent/v1/documents/{doc_id}")
                removed += 1
            except RuntimeError as exc:
                if "404" not in str(exc):
                    raise
        return removed


def parse_document_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected KEY=PATH")
    key, path = value.split("=", 1)
    if not key.strip():
        raise argparse.ArgumentTypeError("document key cannot be empty")
    return key.strip(), Path(path)


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import structured documents into the guide-agent RAG database."
    )
    parser.add_argument(
        "--document",
        action="append",
        default=[],
        type=parse_document_arg,
        metavar="KEY=PATH",
        required=True,
    )
    parser.add_argument(
        "--priority",
        choices=("primary", "secondary", "tertiary"),
        default="secondary",
    )
    parser.add_argument("--api-base", default="http://127.0.0.1:8001")
    parser.add_argument("--token", default="")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    selected = dict(args.document)
    documents_by_source: dict[str, list[dict[str, Any]]] = {}
    for key, path in selected.items():
        documents_by_source[key] = build_documents(
            DocumentConfig(
                key=key,
                source=f"document:{key}",
                path=path,
                priority=args.priority,
            )
        )

    manifest = build_manifest(documents_by_source)
    total = sum(len(value) for value in documents_by_source.values())
    print(f"prepared total={total}")
    for key, summary in manifest["summary"].items():
        print(f"  {key}: {summary}")

    if args.manifest:
        write_manifest(Path(args.manifest), manifest)
        print(f"manifest written: {args.manifest}")

    if args.dry_run:
        return 0

    env_values = read_env_file(Path(args.env_file))
    token = (
        args.token
        or os.getenv("RAG_BOOTSTRAP_API_KEY", "")
        or env_values.get("RAG_BOOTSTRAP_API_KEY", "")
    )
    if not token:
        raise RuntimeError(
            "RAG_BOOTSTRAP_API_KEY is missing; pass --token or --env-file"
        )
    api = AgentApi(args.api_base, token)

    if args.remove:
        removed = sum(
            api.remove_documents(documents)
            for documents in documents_by_source.values()
        )
        print(f"remove requested: {removed}")
        return 0

    job_ids: list[str] = []
    for key, documents in documents_by_source.items():
        result = api.import_documents(documents)
        imported_ids = [
            item["job"]["id"]
            for item in result.get("items", [])
            if item.get("job", {}).get("id")
        ]
        job_ids.extend(imported_ids)
        print(
            f"imported {key}: documents={len(imported_ids)} "
            f"deleted={len(result.get('deleted') or [])}"
        )

    if args.wait:
        jobs = api.wait_for_jobs(job_ids, timeout_seconds=args.timeout)
        failed = [job for job in jobs if job["status"] == "failed"]
        succeeded = len(jobs) - len(failed)
        print(f"jobs succeeded={succeeded} failed={len(failed)}")
        for job in failed:
            print(f"  failed {job['id']}: {job.get('error') or ''}")
        if failed:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

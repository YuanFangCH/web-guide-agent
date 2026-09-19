from __future__ import annotations

import asyncio
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from . import db
from .config import settings
from .embeddings import build_embedding_backend
from .priorities import priority_label, priority_name
from .schemas import (
    AgentDocumentInput,
    ApiKeyCreateRequest,
    DocumentBatchRequest,
    RetrievalRequest,
    UrlIngestionRequest,
)
from .security import require_scope
from .url_safety import UnsafeUrlError, validate_public_url
from .vector_store import RagIndex
from .worker import JobWorker, source_id_for_url


def _document_response(row: dict[str, Any]) -> dict[str, Any]:
    priority = priority_name(row.get("knowledge_priority"))
    return {
        "id": row["id"],
        "source": row["source"],
        "sourceId": row["source_id"],
        "type": row["type"],
        "title": row["title"],
        "url": row["url"],
        "checksum": row["checksum"],
        "updatedAt": row["source_updated_at"],
        "priority": priority,
        "priorityLabel": priority_label(priority),
        "status": row["status"],
        "error": row.get("error"),
        "chunkCount": len(row.get("chunk_ids") or []),
    }


def _job_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "kind": row["kind"],
        "status": row["status"],
        "documentId": row.get("document_id"),
        "attempts": row["attempts"],
        "maxAttempts": row["max_attempts"],
        "error": row.get("error"),
        "result": row.get("result"),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    db.init_db()
    db.ensure_bootstrap_key()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

    worker: JobWorker | None = None
    rag_index: RagIndex | None = None
    rag_error: str | None = None
    try:
        embeddings = build_embedding_backend(settings)
        rag_index = RagIndex(settings, embeddings)
        worker = JobWorker(rag_index)
        worker.start()
    except Exception as exc:  # noqa: BLE001
        rag_error = str(exc)

    app.state.rag_index = rag_index
    app.state.rag_error = rag_error
    try:
        yield
    finally:
        if worker:
            await worker.stop()
        db.close_pool()


app = FastAPI(title="GuideAgent RAG", version="1.0.0", lifespan=lifespan)


def _index_or_503() -> RagIndex:
    rag_index: RagIndex | None = app.state.rag_index
    if rag_index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=app.state.rag_error or "rag_not_ready",
        )
    return rag_index


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok" if app.state.rag_index is not None else "degraded",
        "embeddingProvider": settings.embedding_provider,
        "embeddingDimension": settings.embedding_dimension,
        "error": app.state.rag_error,
    }


@app.put(
    "/api/guide-agent/v1/documents",
    status_code=status.HTTP_202_ACCEPTED,
)
async def put_document(
    payload: AgentDocumentInput,
    _: dict = Depends(require_scope("documents:write")),
) -> dict[str, Any]:
    _index_or_503()
    document = await asyncio.to_thread(
        db.upsert_document_record, payload.model_dump(by_alias=True)
    )
    job = await asyncio.to_thread(
        db.create_job, "document", {"documentId": document["id"]}, document["id"]
    )
    return {"document": _document_response(document), "job": _job_response(job)}


@app.post(
    "/api/guide-agent/v1/documents/batch",
    status_code=status.HTTP_202_ACCEPTED,
)
async def put_document_batch(
    payload: DocumentBatchRequest,
    _: dict = Depends(require_scope("documents:write")),
) -> dict[str, Any]:
    _index_or_503()
    if not payload.items:
        return {"items": [], "deleted": []}

    source = payload.source or payload.items[0].source
    if any(item.source != source for item in payload.items):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="batch_items_must_share_source",
        )

    deleted_ids: list[str] = []
    if payload.replace_source:
        deleted_ids = await asyncio.to_thread(
            db.reconcile_source,
            source,
            [item.source_id for item in payload.items],
        )
        for deleted_id in deleted_ids:
            await asyncio.to_thread(
                db.create_job,
                "delete_document",
                {"reason": "source_snapshot"},
                deleted_id,
            )

    results: list[dict[str, Any]] = []
    for item in payload.items:
        document = await asyncio.to_thread(
            db.upsert_document_record, item.model_dump(by_alias=True)
        )
        job = await asyncio.to_thread(
            db.create_job, "document", {"documentId": document["id"]}, document["id"]
        )
        results.append(
            {"document": _document_response(document), "job": _job_response(job)}
        )
    return {"items": results, "deleted": deleted_ids}


@app.get("/api/guide-agent/v1/documents/{document_id}")
async def get_document(
    document_id: str,
    _: dict = Depends(require_scope("documents:read")),
) -> dict[str, Any]:
    document = await asyncio.to_thread(db.get_document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document_not_found")
    return _document_response(document)


@app.get("/internal/documents")
async def list_documents(
    limit: int = 100,
    _: dict = Depends(require_scope("documents:read")),
) -> dict[str, Any]:
    rows = await asyncio.to_thread(db.list_documents, min(max(limit, 1), 500))
    return {"items": [_document_response(row) for row in rows]}


@app.delete(
    "/api/guide-agent/v1/documents/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_document(
    document_id: str,
    _: dict = Depends(require_scope("documents:write")),
) -> dict[str, Any]:
    _index_or_503()
    document = await asyncio.to_thread(db.mark_document_deleted, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document_not_found")
    job = await asyncio.to_thread(
        db.create_job, "delete_document", {"reason": "api_request"}, document_id
    )
    return {"document": _document_response(document), "job": _job_response(job)}


@app.post(
    "/api/guide-agent/v1/ingestions/url",
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_urls(
    payload: UrlIngestionRequest,
    _: dict = Depends(require_scope("ingestions:write")),
) -> dict[str, Any]:
    _index_or_503()
    results: list[dict[str, Any]] = []
    for url in payload.urls:
        try:
            normalized = await validate_public_url(url)
        except UnsafeUrlError as exc:
            results.append({"url": url, "error": str(exc)})
            continue
        document_payload = {
            "source": payload.source,
            "sourceId": source_id_for_url(normalized),
            "type": "document",
            "title": normalized,
            "url": normalized,
            "contentHtml": "",
            "contentText": "",
            "sections": [],
            "metadata": payload.metadata,
            "checksum": "",
            "updatedAt": db.now_utc().isoformat(),
        }
        document = await asyncio.to_thread(
            db.upsert_document_record, document_payload
        )
        job = await asyncio.to_thread(
            db.create_job,
            "url",
            {"url": normalized, "metadata": payload.metadata},
            document["id"],
        )
        results.append(
            {"document": _document_response(document), "job": _job_response(job)}
        )
    return {"items": results}


@app.post(
    "/api/guide-agent/v1/ingestions/file",
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_file(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    source: str = Form(default="upload"),
    source_id: str | None = Form(default=None, alias="sourceId"),
    _: dict = Depends(require_scope("ingestions:write")),
) -> dict[str, Any]:
    _index_or_503()
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="file_too_large",
        )
    filename = Path(file.filename or "upload.bin").name
    safe_suffix = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).suffix)[:16]
    stored_name = f"{uuid.uuid4().hex}{safe_suffix}"
    path = Path(settings.upload_dir) / stored_name
    await asyncio.to_thread(path.write_bytes, content)

    stable_source_id = source_id or db.document_id(source, filename + str(len(content)))
    document_payload = {
        "source": source,
        "sourceId": stable_source_id,
        "type": "document",
        "title": title or filename,
        "url": "",
        "contentHtml": "",
        "contentText": "",
        "sections": [],
        "metadata": {"filename": filename, "contentType": file.content_type or ""},
        "checksum": "",
        "updatedAt": db.now_utc().isoformat(),
    }
    document = await asyncio.to_thread(db.upsert_document_record, document_payload)
    job = await asyncio.to_thread(
        db.create_job,
        "file",
        {
            "path": str(path),
            "filename": filename,
            "contentType": file.content_type or "",
            "title": title or filename,
            "metadata": document_payload["metadata"],
        },
        document["id"],
    )
    return {"document": _document_response(document), "job": _job_response(job)}


@app.get("/api/guide-agent/v1/ingestions/{job_id}")
async def get_ingestion(
    job_id: str,
    _: dict = Depends(require_scope("ingestions:write")),
) -> dict[str, Any]:
    job = await asyncio.to_thread(db.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    return _job_response(job)


@app.post("/internal/retrieve")
async def internal_retrieve(
    payload: RetrievalRequest,
    _: dict = Depends(require_scope("retrieval:read")),
) -> dict[str, Any]:
    rag_index = _index_or_503()
    results = await asyncio.to_thread(
        rag_index.retrieve,
        payload.query,
        top_k=payload.top_k,
        source_filter=payload.source_filter,
    )
    return {"items": results}


@app.get("/internal/api-keys")
async def list_api_keys(
    _: dict = Depends(require_scope("admin")),
) -> dict[str, Any]:
    return {"items": await asyncio.to_thread(db.list_api_keys)}


@app.post("/internal/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    _: dict = Depends(require_scope("admin")),
) -> dict[str, Any]:
    token, row = await asyncio.to_thread(
        db.create_api_key, payload.name, payload.scopes
    )
    return {"token": token, "key": row}


@app.delete("/internal/api-keys/{key_id}")
async def delete_api_key(
    key_id: str,
    _: dict = Depends(require_scope("admin")),
) -> dict[str, Any]:
    revoked = await asyncio.to_thread(db.revoke_api_key, key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="api_key_not_found")
    return {"revoked": True}

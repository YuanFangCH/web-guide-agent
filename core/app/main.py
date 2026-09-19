from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .auth import (
    VISITOR_COOKIE,
    clear_session_cookie,
    current_user,
    owner_required,
    set_session_cookie,
)
from .config import settings
from .kernel import AgentKernel, KernelRequest
from .llm_client import LLMClient
from .rag_client import RagClient
from .rate_limit import BandwidthRateLimiter, SlidingWindowRateLimiter
from .section_match import match_section
from .sync import WebsiteSynchronizer
from .tools.registry import ToolRegistry
from .website_db import WebsiteDatabaseUnavailable, website_content_db
from .website_library import build_post_download_html, content_disposition
from .website_write import WebsiteWriteClient, WebsiteWriteError

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str
    conversation_id: str | None = Field(default=None, alias="conversationId")
    page_context: dict[str, Any] = Field(default_factory=dict, alias="pageContext")
    tour_context: dict[str, Any] | None = Field(default=None, alias="tourContext")
    mode: str = "chat"
    profile: str = "visitor"
    reasoning_effort: Literal["off", "low", "high", "max"] | None = Field(
        default=None, alias="reasoningEffort"
    )


class LoginRequest(BaseModel):
    username: str
    password: str


class NoteRequest(BaseModel):
    title: str
    content: str


class UrlRequest(BaseModel):
    urls: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApiKeyRequest(BaseModel):
    name: str
    scopes: list[str] = Field(
        default_factory=lambda: [
            "documents:write",
            "documents:read",
            "ingestions:write",
            "retrieval:read",
        ]
    )


class AccountSyncRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str
    display_name: str = Field(alias="displayName")
    role: Literal["owner", "member"]
    password: str = ""
    previous_username: str = Field(default="", alias="previousUsername")


class PageCacheRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page_key: str = Field(alias="pageKey")
    url: str = ""
    title: str = ""
    content_hash: str = Field(default="", alias="contentHash")
    text: str = ""
    sections: list[dict[str, Any]] = Field(default_factory=list)
    current_anchor: str = Field(default="", alias="currentAnchor")


class SectionMatchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    current_anchor: str = Field(default="", alias="currentAnchor")


class WebsiteWriteSessionRequest(BaseModel):
    password: str
    mode: Literal["draft-only", "draft-and-publish"] = "draft-only"
    minutes: int = Field(
        default=settings.website_write_session_default_minutes,
        ge=5,
        le=settings.website_write_session_max_minutes,
    )
    purpose: str = "网页讲解助手网站草稿写入"


async def _cleanup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(
                db.cleanup_conversations, settings.conversation_retention_days
            )
            await asyncio.to_thread(
                db.cleanup_page_cache, settings.page_cache_retention_days
            )
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(24 * 60 * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.ensure_admin()
    rag = RagClient()
    website_db = website_content_db
    try:
        website_db.start()
    except Exception:
        pass
    website_write = WebsiteWriteClient()
    registry = ToolRegistry.from_file(settings.tool_config_path)
    kernel = AgentKernel(
        registry,
        rag,
        LLMClient(),
        website_db=website_db,
        website_write=website_write,
    )
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, read=300.0),
        follow_redirects=False,
        headers={"Accept-Encoding": "identity"},
    )
    download_limiter = BandwidthRateLimiter(
        settings.website_download_limit_mbps * 1_000_000 / 8,
        burst_seconds=settings.website_download_burst_seconds,
    )
    synchronizer = WebsiteSynchronizer(rag)
    synchronizer.start()
    cleanup_task = asyncio.create_task(_cleanup_loop(), name="guide-agent-retention")
    app.state.rag = rag
    app.state.website_db = website_db
    app.state.website_write = website_write
    app.state.kernel = kernel
    app.state.registry = registry
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.download_limiter = download_limiter
    app.state.http_client = http_client
    app.state.synchronizer = synchronizer
    try:
        yield
    finally:
        cleanup_task.cancel()
        await synchronizer.stop()
        await http_client.aclose()
        website_db.close()


app = FastAPI(title="GuideAgent Core", version="1.0.0", lifespan=lifespan)


def _rag(request: Request) -> RagClient:
    return request.app.state.rag


def _synchronizer(request: Request) -> WebsiteSynchronizer:
    return request.app.state.synchronizer


def _require_account_sync(request: Request) -> None:
    supplied = request.headers.get("X-Account-Sync-Token", "")
    expected = settings.account_sync_token
    if not expected or not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid_account_sync_token")


def _client_key(request: Request) -> str:
    return (
        request.cookies.get(VISITOR_COOKIE)
        or request.client.host
        or "unknown"
    )


def _enforce_rate_limit(request: Request, scope: str, limit: int) -> None:
    limiter: SlidingWindowRateLimiter = request.app.state.rate_limiter
    if not limiter.allow(f"{scope}:{_client_key(request)}", limit):
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "guide-agent-core",
        "sync": _synchronizer(request).status(),
        "cache": db.page_cache_stats(),
        "tools": len(request.app.state.registry.specs),
        "chatModel": request.app.state.kernel.llm_client.primary_model,
        "chatThinking": settings.chat_thinking,
        "chatReasoningEffort": settings.chat_reasoning_effort,
        "chatRateLimitPerMinute": settings.chat_rate_limit_per_minute,
        "websiteDownloadLimitMbps": settings.website_download_limit_mbps,
        "websiteRead": request.app.state.website_db.health(),
        "websiteWrite": request.app.state.website_write.local_status(),
    }


@app.get("/guide-agent/widget.js", include_in_schema=False)
async def widget_script() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "widget.js",
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/guide-agent/admin", include_in_schema=False)
@app.get("/guide-agent/admin/", include_in_schema=False)
async def admin_page() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "admin.html",
        media_type="text/html",
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


@app.post("/api/guide-agent/auth/login")
async def login(payload: LoginRequest):
    user = await asyncio.to_thread(
        db.authenticate, payload.username, payload.password
    )
    if not user:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    token, expires_at = await asyncio.to_thread(db.create_session, user["id"])
    response = JSONResponse({"user": user, "expiresAt": expires_at})
    set_session_cookie(response, token, expires_at)
    return response


@app.post("/api/guide-agent/auth/logout")
async def logout(request: Request):
    token = request.cookies.get("guide_agent_session", "")
    if token:
        await asyncio.to_thread(db.delete_session, token)
    response = JSONResponse({"ok": True})
    clear_session_cookie(response)
    return response


@app.get("/api/guide-agent/auth/me")
async def me(user: dict = Depends(current_user)) -> dict[str, Any]:
    return {"user": user}


@app.get("/api/guide-agent/internal/accounts")
async def internal_accounts(request: Request) -> dict[str, Any]:
    _require_account_sync(request)
    return {"items": await asyncio.to_thread(db.list_user_accounts)}


@app.put("/api/guide-agent/internal/accounts")
async def sync_internal_account(
    payload: AccountSyncRequest,
    request: Request,
) -> dict[str, Any]:
    _require_account_sync(request)
    try:
        user = await asyncio.to_thread(
            db.sync_user_account,
            username=payload.username,
            display_name=payload.display_name,
            role=payload.role,
            password=payload.password,
            previous_username=payload.previous_username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"user": user}


@app.delete("/api/guide-agent/internal/accounts/{username}")
async def delete_internal_account(
    username: str,
    request: Request,
) -> dict[str, Any]:
    _require_account_sync(request)
    try:
        await asyncio.to_thread(db.delete_user_account, username)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/guide-agent/chat/stream")
@app.post("/api/guide-agent/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
) -> StreamingResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question_required")
    _enforce_rate_limit(
        request, "chat", settings.chat_rate_limit_per_minute
    )

    visitor_id = request.cookies.get(VISITOR_COOKIE) or secrets.token_urlsafe(24)
    user = await asyncio.to_thread(
        db.get_session_user, request.cookies.get("guide_agent_session", "")
    )
    profile = (
        "team"
        if user and user.get("role") == "owner"
        else "member"
        if user
        else "visitor"
    )
    default_effort = (
        "off"
        if settings.chat_thinking == "disabled"
        else settings.chat_reasoning_effort
        if settings.chat_reasoning_effort in {"low", "high", "max"}
        else "low"
    )
    conversation_id = payload.conversation_id or ""
    conversation_exists = bool(conversation_id) and await asyncio.to_thread(
        db.conversation_exists, conversation_id
    )
    stored_effort = (
        await asyncio.to_thread(
            db.get_conversation_reasoning_effort, conversation_id
        )
        if conversation_exists
        else None
    )
    if profile in {"team", "member"}:
        reasoning_effort = (
            payload.reasoning_effort or stored_effort or default_effort
        )
    else:
        reasoning_effort = stored_effort or default_effort
    if reasoning_effort not in {"off", "low", "high", "max"}:
        reasoning_effort = "low"
    if not conversation_exists:
        conversation_id = await asyncio.to_thread(
            db.create_conversation,
            visitor_id,
            str(payload.page_context.get("url") or ""),
            str(payload.page_context.get("title") or ""),
            reasoning_effort,
        )
    elif profile in {"team", "member"} and payload.reasoning_effort:
        await asyncio.to_thread(
            db.set_conversation_reasoning_effort,
            conversation_id,
            reasoning_effort,
        )

    response = StreamingResponse(
        request.app.state.kernel.stream(
            KernelRequest(
                question=question,
                page_context=payload.page_context,
                conversation_id=conversation_id,
                mode=payload.mode,
                reasoning_effort=reasoning_effort,
                tour_context=payload.tour_context or {},
            ),
            profile=profile,
            user=user,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    response.set_cookie(
        VISITOR_COOKIE,
        visitor_id,
        max_age=90 * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@app.get("/api/guide-agent/tools")
async def tools(
    request: Request,
    profile: str = "visitor",
) -> dict[str, Any]:
    if profile not in {"visitor", "team", "member"}:
        raise HTTPException(status_code=400, detail="invalid_profile")
    user: dict[str, Any] | None = None
    if profile in {"team", "member"}:
        user = await asyncio.to_thread(
            db.get_session_user, request.cookies.get("guide_agent_session", "")
        )
        if not user:
            raise HTTPException(status_code=403, detail="team_login_required")
        profile = "team" if user.get("role") == "owner" else "member"
    write_session = (
        request.app.state.website_write.local_status(user["username"])
        if user
        else {"active": False, "session": None}
    )
    write_mode = (
        str(write_session.get("session", {}).get("mode") or "draft-only")
        if write_session.get("active")
        else None
    )
    return {
        "profile": profile,
        "items": request.app.state.registry.describe(
            profile, write_mode=write_mode
        ),
    }


@app.post("/api/guide-agent/page/cache")
async def cache_page(
    payload: PageCacheRequest,
    request: Request,
) -> dict[str, Any]:
    _enforce_rate_limit(
        request, "page-cache", settings.page_cache_rate_limit_per_minute
    )
    result = await asyncio.to_thread(
        db.upsert_page_cache,
        page_key=payload.page_key,
        site_id=settings.site_id,
        url=payload.url,
        title=payload.title,
        content_hash=payload.content_hash
        or hashlib.sha256(
            json.dumps(
                {
                    "title": payload.title,
                    "text": payload.text,
                    "sections": payload.sections,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        page_text=payload.text,
        sections=payload.sections,
    )
    return result


@app.get("/api/guide-agent/page/{page_key}")
async def get_page(
    page_key: str,
    request: Request,
) -> dict[str, Any]:
    page = await asyncio.to_thread(db.get_page_cache, page_key)
    if not page:
        raise HTTPException(status_code=404, detail="page_not_found")
    return page


@app.post("/api/guide-agent/page/section-match")
async def section_match(
    payload: SectionMatchRequest,
    request: Request,
) -> dict[str, Any]:
    result = match_section(
        payload.question, payload.sections, payload.current_anchor
    )
    return {"match": result}


@app.get("/api/guide-agent/admin/conversations")
async def conversations(
    _: dict = Depends(current_user),
) -> dict[str, Any]:
    return {"items": await asyncio.to_thread(db.list_conversations)}


@app.get("/api/guide-agent/admin/conversations/{conversation_id}")
async def conversation_detail(
    conversation_id: str,
    _: dict = Depends(current_user),
) -> dict[str, Any]:
    return {
        "items": await asyncio.to_thread(db.list_messages, conversation_id),
        "reasoningEffort": await asyncio.to_thread(
            db.get_conversation_reasoning_effort, conversation_id
        ),
    }


@app.get("/api/guide-agent/admin/notes")
async def notes(user: dict = Depends(current_user)) -> dict[str, Any]:
    return {"items": await asyncio.to_thread(db.list_notes, user["id"])}


@app.post("/api/guide-agent/admin/notes", status_code=201)
async def create_note(
    payload: NoteRequest,
    user: dict = Depends(owner_required),
) -> dict[str, Any]:
    if not payload.title.strip() or not payload.content.strip():
        raise HTTPException(status_code=400, detail="title_and_content_required")
    note = await asyncio.to_thread(
        db.create_note, user["id"], payload.title.strip(), payload.content.strip()
    )
    return {"note": note}


@app.post("/api/guide-agent/admin/notes/{note_id}/ingest")
async def ingest_note(
    note_id: str,
    request: Request,
    user: dict = Depends(owner_required),
) -> dict[str, Any]:
    note = await asyncio.to_thread(db.get_note, note_id)
    if not note or note["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="note_not_found")
    item = {
        "source": "team-note",
        "sourceId": note["id"],
        "type": "team-note",
        "title": note["title"],
        "url": "",
        "contentHtml": "",
        "contentText": note["content"],
        "sections": [
            {"anchor": "note", "heading": note["title"], "text": note["content"]}
        ],
        "metadata": {
            "createdBy": user["username"],
            "updatedAt": note["updated_at"],
        },
        "checksum": "",
        "updatedAt": note["updated_at"],
    }
    return await _rag(request).upsert_batch([item])


@app.get("/api/guide-agent/admin/documents")
async def documents(
    request: Request,
    _: dict = Depends(current_user),
) -> dict[str, Any]:
    return {"items": await _rag(request).list_documents()}


@app.get("/api/guide-agent/admin/website-content")
async def website_content_library(
    request: Request,
    response: Response,
    content_type: Literal["post", "image"] = Query(
        default="post", alias="type"
    ),
    query: str = Query(default="", alias="q"),
    album: str = "",
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(current_user),
) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(
            request.app.state.website_db.library_search,
            content_type=content_type,
            query=query,
            album=album or None,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WebsiteDatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="website_database_unavailable"
        ) from exc
    response.headers["Cache-Control"] = "private, no-store"
    result["downloadLimitMbps"] = settings.website_download_limit_mbps
    return result


@app.get(
    "/api/guide-agent/admin/website-content/{content_type}/{identifier}/download"
)
async def download_website_content(
    content_type: Literal["post", "image"],
    identifier: str,
    request: Request,
    user: dict = Depends(current_user),
) -> Response:
    try:
        item = await asyncio.to_thread(
            request.app.state.website_db.get_download_item,
            content_type=content_type,
            identifier=identifier,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WebsiteDatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="website_database_unavailable"
        ) from exc

    if not item:
        raise HTTPException(status_code=404, detail="website_content_not_found")

    limiter: BandwidthRateLimiter = request.app.state.download_limiter
    bucket_key = f"website-download:{user.get('id') or user['username']}"

    if content_type == "post":
        try:
            site_url = await asyncio.to_thread(
                request.app.state.website_db.site_url
            )
        except Exception:  # noqa: BLE001
            site_url = ""
        payload = build_post_download_html(item, site_url=site_url)
        slug = str(item.get("slug") or item.get("id") or "post")
        filename = f"{slug}.html"

        async def stream_post():
            for index in range(0, len(payload), 64 * 1024):
                chunk = payload[index : index + 64 * 1024]
                await limiter.consume(bucket_key, len(chunk))
                yield chunk

        return StreamingResponse(
            stream_post(),
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": content_disposition(
                    filename, f"{slug}.html"
                ),
                "Cache-Control": "private, no-store",
                "Content-Length": str(len(payload)),
                "X-Download-Limit-Mbps": str(
                    settings.website_download_limit_mbps
                ),
            },
        )

    mime_type = str(item.get("mimeType") or "application/octet-stream")
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="not_an_image")

    storage_key = str(item.get("storageKey") or "").lstrip("/")
    if not storage_key:
        raise HTTPException(status_code=404, detail="media_not_found")
    if not settings.website_export_base_url:
        raise HTTPException(
            status_code=503, detail="website_media_source_not_configured"
        )
    media_url = (
        f"{settings.website_export_base_url}/media/"
        f"{quote(storage_key, safe='/')}"
    )
    client: httpx.AsyncClient = request.app.state.http_client
    upstream_request = client.build_request("GET", media_url)
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="website_media_unavailable"
        ) from exc
    if upstream.status_code != 200:
        await upstream.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"website_media_http_{upstream.status_code}",
        )

    original_name = str(
        item.get("originalName") or item.get("slug") or "image"
    )
    suffix = Path(original_name).suffix.lower() or ".img"
    fallback_name = f"website-image-{item.get('id')}{suffix}"
    content_length = upstream.headers.get("content-length") or item.get("size")

    async def stream_image():
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=64 * 1024):
                if not chunk:
                    continue
                await limiter.consume(bucket_key, len(chunk))
                yield chunk
        finally:
            await upstream.aclose()

    headers = {
        "Content-Disposition": content_disposition(
            original_name, fallback_name
        ),
        "Cache-Control": "private, no-store",
        "X-Download-Limit-Mbps": str(settings.website_download_limit_mbps),
    }
    if content_length:
        headers["Content-Length"] = str(content_length)
    return StreamingResponse(
        stream_image(),
        media_type=mime_type,
        headers=headers,
    )


@app.get("/api/guide-agent/admin/tool-audit")
async def tool_audit(
    request: Request,
    _: dict = Depends(current_user),
) -> dict[str, Any]:
    return {"items": await asyncio.to_thread(db.list_tool_audit, 100)}


@app.get("/api/guide-agent/admin/cache")
async def cache_stats(
    request: Request,
    _: dict = Depends(current_user),
) -> dict[str, Any]:
    return await asyncio.to_thread(db.page_cache_stats)


@app.get("/api/guide-agent/admin/website-write")
async def website_write_status(
    request: Request,
    user: dict = Depends(owner_required),
) -> dict[str, Any]:
    status = request.app.state.website_write.local_status(user["username"])
    try:
        status["audit"] = await request.app.state.website_write.list_audit(50)
    except Exception as exc:  # noqa: BLE001
        status["auditError"] = str(exc)
        status["audit"] = []
    return status


@app.post("/api/guide-agent/admin/website-write/sessions", status_code=201)
async def open_website_write_session(
    payload: WebsiteWriteSessionRequest,
    request: Request,
    user: dict = Depends(owner_required),
) -> dict[str, Any]:
    authenticated = await asyncio.to_thread(
        db.authenticate, user["username"], payload.password
    )
    if not authenticated:
        raise HTTPException(status_code=403, detail="password_required")
    try:
        return await request.app.state.website_write.open_session(
            minutes=payload.minutes,
            mode=payload.mode,
            purpose=payload.purpose.strip() or "网页讲解助手网站草稿写入",
            created_by=user["username"],
        )
    except WebsiteWriteError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/api/guide-agent/admin/website-write/sessions/{session_id}")
async def close_website_write_session(
    session_id: str,
    request: Request,
    _: dict = Depends(owner_required),
) -> dict[str, Any]:
    try:
        return {
            "session": await request.app.state.website_write.revoke_session(
                session_id
            )
        }
    except WebsiteWriteError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/guide-agent/admin/website-media", status_code=201)
async def upload_website_media(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(owner_required),
) -> dict[str, Any]:
    content = await file.read()
    if len(content) > 500 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file_too_large")
    try:
        return await request.app.state.website_write.upload_media(
            filename=file.filename or "upload.bin",
            content=content,
            content_type=file.content_type or "application/octet-stream",
            created_by=user["username"],
        )
    except WebsiteWriteError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/api/guide-agent/admin/ingestions/url", status_code=202)
async def ingest_urls(
    payload: UrlRequest,
    request: Request,
    _: dict = Depends(owner_required),
) -> dict[str, Any]:
    if not payload.urls:
        raise HTTPException(status_code=400, detail="urls_required")
    return await _rag(request).ingest_urls(payload.urls, payload.metadata)


@app.post("/api/guide-agent/admin/ingestions/file", status_code=202)
async def ingest_file(
    request: Request,
    file: UploadFile = File(...),
    _: dict = Depends(owner_required),
) -> dict[str, Any]:
    content = await file.read()
    return await _rag(request).ingest_file(
        file.filename or "upload.bin",
        content,
        file.content_type or "application/octet-stream",
    )


@app.get("/api/guide-agent/admin/api-keys")
async def api_keys(
    request: Request,
    _: dict = Depends(owner_required),
) -> dict[str, Any]:
    return {"items": await _rag(request).list_api_keys()}


@app.post("/api/guide-agent/admin/api-keys", status_code=201)
async def create_api_key(
    payload: ApiKeyRequest,
    request: Request,
    _: dict = Depends(owner_required),
) -> dict[str, Any]:
    return await _rag(request).create_api_key(payload.name, payload.scopes)


@app.delete("/api/guide-agent/admin/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    request: Request,
    _: dict = Depends(owner_required),
) -> dict[str, Any]:
    return await _rag(request).revoke_api_key(key_id)


@app.get("/api/guide-agent/admin/sync")
async def sync_status(
    request: Request,
    _: dict = Depends(current_user),
) -> dict[str, Any]:
    return _synchronizer(request).status()


@app.post("/api/guide-agent/admin/sync", status_code=202)
async def trigger_sync(
    request: Request,
    manifest: bool = False,
    _: dict = Depends(owner_required),
) -> dict[str, Any]:
    try:
        return await _synchronizer(request).sync(manifest=manifest)
    except RuntimeError as exc:
        if str(exc) == "sync_already_running":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise

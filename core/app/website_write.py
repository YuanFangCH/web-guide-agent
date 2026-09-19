from __future__ import annotations

from typing import Any

import httpx

from . import db
from .config import settings


class WebsiteWriteError(RuntimeError):
    pass


class WebsiteWriteNotAuthorized(WebsiteWriteError):
    pass


class WebsiteWriteClient:
    def __init__(self) -> None:
        self.base_url = settings.website_write_base_url.rstrip("/")
        self.admin_token = settings.website_write_admin_token

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.admin_token)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise WebsiteWriteNotAuthorized("website_write_not_configured")
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=json,
                data=data,
                files=files,
            )
            if response.status_code in {401, 403}:
                raise WebsiteWriteNotAuthorized("write_session_expired")
            response.raise_for_status()
            return response.json()

    async def open_session(
        self,
        *,
        minutes: int,
        mode: str,
        purpose: str,
        created_by: str,
    ) -> dict[str, Any]:
        existing_sessions = await self.list_remote_sessions()
        for existing in existing_sessions:
            if (
                existing.get("createdBy") == created_by
                and existing.get("active")
                and existing.get("id")
            ):
                await self.revoke_session(str(existing["id"]))
        effective_minutes = 30 if mode == "draft-and-publish" else minutes
        payload = await self._request(
            "POST",
            "/sessions",
            token=self.admin_token,
            json={
                "minutes": min(
                    max(effective_minutes, 5),
                    settings.website_write_session_max_minutes,
                ),
                "mode": mode,
                "purpose": purpose,
                "createdBy": created_by,
            },
        )
        session = payload["session"]
        token = payload["token"]
        return db.save_website_write_session(
            session_id=session["id"],
            token=token,
            scopes=list(session.get("scopes") or []),
            mode=session.get("mode") or mode,
            purpose=session.get("purpose") or purpose,
            created_by=session.get("createdBy") or created_by,
            created_at=session["createdAt"],
            expires_at=session["expiresAt"],
        )

    async def list_remote_sessions(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET", "/sessions", token=self.admin_token
        )
        return list(payload.get("items") or [])

    async def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET", "/audit", token=self.admin_token
        )
        return list(payload.get("items") or [])[:limit]

    async def revoke_session(self, session_id: str) -> dict[str, Any]:
        payload = await self._request(
            "DELETE", f"/sessions/{session_id}", token=self.admin_token
        )
        db.mark_website_write_session_revoked(session_id)
        return dict(payload.get("session") or {})

    def local_status(self, created_by: str | None = None) -> dict[str, Any]:
        active = db.get_active_website_write_session(created_by)
        recent = [
            {
                key: item.get(key)
                for key in (
                    "id",
                    "scopes",
                    "mode",
                    "purpose",
                    "createdBy",
                    "createdAt",
                    "expiresAt",
                    "revokedAt",
                    "active",
                )
            }
            for item in db.list_website_write_sessions(created_by)
        ]
        return {
            "configured": self.configured,
            "active": bool(active),
            "session": {
                key: active.get(key)
                for key in (
                    "id",
                    "scopes",
                    "mode",
                    "purpose",
                    "createdBy",
                    "createdAt",
                    "expiresAt",
                )
            }
            if active
            else None,
            "recent": recent,
        }

    def _active_token(self, created_by: str | None = None) -> str:
        session = db.get_active_website_write_session(created_by)
        if not session:
            raise WebsiteWriteNotAuthorized("write_session_required")
        return str(session["token"])

    async def create_draft(
        self,
        content_type: str,
        payload: dict[str, Any],
        *,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        if content_type not in {"post", "image", "video"}:
            raise WebsiteWriteError("unsupported_content_type")
        return await self._request(
            "POST",
            f"/{content_type}s",
            token=self._active_token(created_by),
            json=payload,
        )

    async def update_draft(
        self,
        content_type: str,
        content_id: str,
        payload: dict[str, Any],
        *,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        if content_type not in {"post", "image", "video"}:
            raise WebsiteWriteError("unsupported_content_type")
        return await self._request(
            "PUT",
            f"/{content_type}s/{content_id}",
            token=self._active_token(created_by),
            json=payload,
        )

    async def publish_draft(
        self,
        content_type: str,
        content_id: str,
        *,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        if content_type not in {"post", "image", "video"}:
            raise WebsiteWriteError("unsupported_content_type")
        return await self._request(
            "POST",
            f"/{content_type}s/{content_id}/publish",
            token=self._active_token(created_by),
        )

    async def upload_media(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/media/upload",
            token=self._active_token(created_by),
            files={"file": (filename, content, content_type)},
        )


website_write_client = WebsiteWriteClient()

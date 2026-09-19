from __future__ import annotations

from fastapi import HTTPException, Request, status

from . import db
from .config import settings

SESSION_COOKIE = "guide_agent_session"
VISITOR_COOKIE = "guide_agent_visitor"


def current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE, "")
    user = db.get_session_user(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required"
        )
    return user


def owner_required(request: Request) -> dict:
    user = current_user(request)
    if user.get("role") != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="owner_required",
        )
    return user


def set_session_cookie(response, token: str, expires_at: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        expires=expires_at,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")

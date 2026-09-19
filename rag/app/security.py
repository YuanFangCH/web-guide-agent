from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, status

from . import db


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_bearer_token",
        )
    return authorization[7:].strip()


def require_scope(scope: str) -> Callable:
    async def dependency(request: Request) -> dict:
        token = _bearer_token(request)
        key = db.verify_api_key(token)
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_api_key",
            )
        if scope not in key.get("scopes", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing_scope:{scope}",
            )
        return key

    return dependency

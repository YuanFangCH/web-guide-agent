from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx


class UnsafeUrlError(ValueError):
    pass


def _is_blocked_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("only_http_and_https_are_allowed")
    if not parsed.hostname:
        raise UnsafeUrlError("missing_hostname")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("credentials_in_url_are_not_allowed")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise UnsafeUrlError("private_host_is_not_allowed")

    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UnsafeUrlError("hostname_resolution_failed") from exc

    if not addresses:
        raise UnsafeUrlError("hostname_resolution_failed")
    for address in addresses:
        if _is_blocked_ip(address[4][0]):
            raise UnsafeUrlError("private_network_target_is_not_allowed")
    return parsed.geturl()


async def fetch_public_url(
    url: str, *, max_bytes: int, timeout_seconds: float = 20
) -> tuple[str, str, bytes]:
    current = url
    headers = {
        "User-Agent": "WebGuideAgentRAG/1.0 (+https://example.invalid/guide-agent)"
    }
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout_seconds,
        headers=headers,
    ) as client:
        for _ in range(6):
            current = await validate_public_url(current)
            response = await client.get(current)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise UnsafeUrlError("redirect_without_location")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise ValueError("response_too_large")
            if len(response.content) > max_bytes:
                raise ValueError("response_too_large")
            return current, response.headers.get("content-type", ""), response.content
    raise UnsafeUrlError("too_many_redirects")

import pytest

from app.url_safety import UnsafeUrlError, validate_public_url


@pytest.mark.asyncio
async def test_rejects_non_http_schemes() -> None:
    with pytest.raises(UnsafeUrlError):
        await validate_public_url("file:///etc/passwd")


@pytest.mark.asyncio
async def test_rejects_localhost() -> None:
    with pytest.raises(UnsafeUrlError):
        await validate_public_url("http://localhost/admin")


@pytest.mark.asyncio
async def test_rejects_private_ip_literals() -> None:
    with pytest.raises(UnsafeUrlError):
        await validate_public_url("http://127.0.0.1/")
    with pytest.raises(UnsafeUrlError):
        await validate_public_url("http://[::1]/")

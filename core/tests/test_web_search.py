import pytest

from app import web_search


@pytest.mark.asyncio
async def test_web_search_disabled_returns_empty(monkeypatch) -> None:
    class DisabledSettings:
        web_search_provider = ""

    monkeypatch.setattr(web_search, "settings", DisabledSettings())

    assert await web_search.search_web("测试") == []

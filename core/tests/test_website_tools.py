import pytest

from app.tools.base import ToolContext
from app.tools.website import (
    website_content_search,
    website_content_stats,
    website_draft_create,
)


class FakeWebsiteDb:
    def search(self, **kwargs):
        return [{"id": "post-1", "title": "文章", "status": "DRAFT"}]

    def get(self, **kwargs):
        return {"id": kwargs["identifier"], "title": "文章"}

    def stats(self):
        return {
            "post": {"DRAFT": 1},
            "image": {"PUBLISHED": 2},
            "video": {"PUBLISHED": 1},
            "media": 3,
        }


class FakeWebsiteWrite:
    async def create_draft(self, content_type, payload, *, created_by=None):
        return {content_type: {"id": "draft-1", **payload}}

    async def publish_draft(self, content_type, content_id, *, created_by=None):
        return {content_type: {"id": content_id, "status": "PUBLISHED"}}


def context(*, write_session=None, profile="team"):
    return ToolContext(
        profile=profile,
        page_context={},
        conversation_id="",
        prompt_version="v1",
        model="test",
        rag_client=None,
        website_db=FakeWebsiteDb(),
        website_write=FakeWebsiteWrite(),
        write_session=write_session,
    )


@pytest.mark.asyncio
async def test_structured_website_read_tools() -> None:
    search = await website_content_search(
        {"contentType": "post", "query": "文章"}, context()
    )
    stats = await website_content_stats({}, context())

    assert search.ok is True
    assert search.meta["count"] == 1
    assert stats.ok is True
    assert stats.data["stats"]["post"]["DRAFT"] == 1


@pytest.mark.asyncio
async def test_write_tool_requires_active_session() -> None:
    denied = await website_draft_create(
        {"contentType": "post", "payload": {"title": "草稿"}},
        context(),
    )
    allowed = await website_draft_create(
        {"contentType": "post", "payload": {"title": "草稿"}},
        context(write_session={"id": "session-1"}),
    )

    assert denied.ok is False
    assert denied.error == "write_session_required"
    assert allowed.ok is True
    assert allowed.data["post"]["id"] == "draft-1"


@pytest.mark.asyncio
async def test_member_website_tools_exclude_videos_and_media() -> None:
    video = await website_content_search(
        {"contentType": "video"},
        context(profile="member"),
    )
    media = await website_content_search(
        {"contentType": "media"},
        context(profile="member"),
    )
    stats = await website_content_stats({}, context(profile="member"))

    assert video.ok is False
    assert video.error == "member_content_type_not_allowed"
    assert media.ok is False
    assert media.error == "member_content_type_not_allowed"
    assert set(stats.data["stats"]) == {"post", "image"}

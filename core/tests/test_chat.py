from fastapi.testclient import TestClient

from app import db
from app.chat import _actions_for, sse_event
from app.main import app
from app.rate_limit import SlidingWindowRateLimiter


def test_sse_event_uses_named_event() -> None:
    assert sse_event("token", {"text": "你好"}) == (
        'event: token\ndata: {"text": "你好"}\n\n'
    )


def test_actions_prefer_current_page_highlight() -> None:
    actions = _actions_for(
        [
            {
                "title": "文章",
                "url": "https://example.test/posts/1",
                "anchor": "section-2",
                "sectionTitle": "章节",
            }
        ],
        {"url": "https://example.test/posts/1"},
    )

    assert actions == [
        {"type": "highlight", "anchor": "section-2", "label": "章节"}
    ]


def test_actions_open_external_source() -> None:
    actions = _actions_for(
        [{"title": "外部资料", "url": "https://example.test/source"}],
        {"url": "https://example.test/current"},
    )

    assert actions == [
        {
            "type": "open_link",
            "url": "https://example.test/source",
            "label": "外部资料",
        }
    ]


def test_chat_accepts_null_tour_context_for_public_widget(monkeypatch) -> None:
    calls = []

    class FakeKernel:
        primary_model = "mock-model"

        async def stream(self, request, *, profile, user):
            calls.append((request, profile, user))
            yield 'event: done\ndata: {"answer": "ok"}\n\n'

    app.state.kernel = FakeKernel()
    app.state.rate_limiter = SlidingWindowRateLimiter()
    monkeypatch.setattr(db, "get_session_user", lambda _: None)
    monkeypatch.setattr(db, "conversation_exists", lambda _: False)
    monkeypatch.setattr(db, "create_conversation", lambda *_: "conversation-1")

    response = TestClient(app).post(
        "/api/guide-agent/chat/stream",
        json={
            "question": "你好",
            "mode": "chat",
            "conversationId": None,
            "pageContext": {"url": "https://example.test/", "title": "测试页"},
            "tourContext": None,
        },
    )

    assert response.status_code == 200
    assert calls[0][0].tour_context == {}

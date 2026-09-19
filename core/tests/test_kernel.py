import json

import pytest

from app import db
from app.kernel import AgentKernel, KernelRequest
from app.tools.base import ToolResult, ToolSpec
from app.tools.registry import ToolRegistry


class DummySettings:
    def __init__(self, path):
        self.db_path = str(path)


class FakeRag:
    async def retrieve(self, query, top_k=8, source_filter=None):
        return [
            {
                "id": "source-1",
                "source": "website",
                "title": "测试来源",
                "url": "https://example.test/source",
                "anchor": "intro",
                "sectionTitle": "导语",
                "content": "来源内容",
            }
        ]


class FakeLLM:
    primary_model = "mock-model"

    def __init__(self):
        self.calls = 0

    async def stream(
        self,
        messages,
        tools=None,
        *,
        thinking=None,
        reasoning_effort=None,
    ):
        self.calls += 1
        if self.calls == 1:
            yield type("Event", (), {"type": "tool_calls", "text": "", "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "get_page_context", "arguments": "{}"},
                }
            ]})()
        else:
            yield type("Event", (), {"type": "token", "text": "最终回答", "tool_calls": []})()
            yield type("Event", (), {"type": "done", "text": "", "tool_calls": []})()


@pytest.mark.asyncio
async def test_kernel_uses_tool_loop_and_audits(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "settings", DummySettings(tmp_path / "kernel.db"))
    db.init_db()
    conversation_id = db.create_conversation("visitor", "/test", "测试页")

    async def handler(arguments, context):
        return ToolResult(content="页面内容")

    spec = ToolSpec(
        name="get_page_context",
        description="读取页面",
        parameters={"type": "object", "properties": {}},
        handler=handler,
    )
    registry = ToolRegistry({"get_page_context": spec}, {"visitor": ["get_page_context"]})
    llm = FakeLLM()
    kernel = AgentKernel(registry, FakeRag(), llm)

    chunks = []
    async for chunk in kernel.stream(
        KernelRequest(
            question="导语是什么",
            conversation_id=conversation_id,
            page_context={
                "pageKey": "page-1",
                "url": "https://example.test/",
                "title": "测试页",
                "text": "页面内容",
                "sections": [{"anchor": "intro", "heading": "导语", "text": "内容"}],
            },
        ),
        profile="visitor",
        user=None,
    ):
        chunks.append(chunk)

    output = "".join(chunks)
    assert "event: token" in output
    assert "最终回答" in output
    assert llm.calls == 2
    assert len(db.list_tool_audit()) == 1

    cached_output = []
    async for chunk in kernel.stream(
        KernelRequest(
            question="导语是什么",
            conversation_id=conversation_id,
            page_context={
                "pageKey": "page-1",
                "url": "https://example.test/",
                "title": "测试页",
                "text": "页面内容",
                "sections": [{"anchor": "intro", "heading": "导语", "text": "内容"}],
            },
        ),
        profile="visitor",
        user=None,
    ):
        cached_output.append(chunk)

    assert llm.calls == 2
    assert "answerCacheHit" in "".join(cached_output)


@pytest.mark.asyncio
async def test_kernel_circuit_breaker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "settings", DummySettings(tmp_path / "breaker.db"))
    db.init_db()
    conversation_id = db.create_conversation("visitor", "/test", "测试页")

    async def failing(arguments, context):
        return ToolResult(ok=False, error="boom", content="失败")

    spec = ToolSpec(
        name="get_page_context",
        description="读取页面",
        parameters={"type": "object", "properties": {}},
        handler=failing,
    )
    registry = ToolRegistry({"get_page_context": spec}, {"visitor": ["get_page_context"]})

    class FailingLLM:
        primary_model = "mock-model"

        def __init__(self):
            self.calls = 0

        async def stream(
            self,
            messages,
            tools=None,
            *,
            thinking=None,
            reasoning_effort=None,
        ):
            self.calls += 1
            yield type(
                "Event",
                (),
                {
                    "type": "tool_calls",
                    "text": "",
                    "tool_calls": [
                        {
                            "id": f"call-{self.calls}",
                            "type": "function",
                            "function": {
                                "name": "get_page_context",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
            )()

    llm = FailingLLM()
    kernel = AgentKernel(registry, FakeRag(), llm)
    output = []
    async for chunk in kernel.stream(
        KernelRequest(
            question="介绍一下",
            conversation_id=conversation_id,
            page_context={"title": "测试页", "text": "内容", "sections": []},
        ),
        profile="visitor",
        user=None,
    ):
        output.append(chunk)

    assert llm.calls == 3
    assert "熔断" in "".join(output) or "fallback" in "".join(output)


@pytest.mark.asyncio
async def test_kernel_streams_reasoning_only_to_team_and_isolates_cache(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(db, "settings", DummySettings(tmp_path / "reasoning.db"))
    db.init_db()

    class ReasoningLLM:
        primary_model = "mock-model"

        def __init__(self):
            self.calls = 0
            self.options = []

        async def stream(
            self,
            messages,
            tools=None,
            *,
            thinking=None,
            reasoning_effort=None,
        ):
            self.calls += 1
            self.options.append((thinking, reasoning_effort))
            yield type(
                "Event",
                (),
                {"type": "reasoning", "text": "思考内容", "tool_calls": []},
            )()
            yield type(
                "Event",
                (),
                {"type": "token", "text": "回答", "tool_calls": []},
            )()
            yield type("Event", (), {"type": "done", "text": "", "tool_calls": []})()

    llm = ReasoningLLM()
    kernel = AgentKernel(
        ToolRegistry({}, {"team": [], "visitor": []}),
        FakeRag(),
        llm,
    )
    page_context = {
        "pageKey": "page-reasoning",
        "title": "测试页",
        "text": "页面内容",
        "sections": [{"anchor": "intro", "heading": "导语", "text": "内容"}],
    }

    team_output = []
    async for chunk in kernel.stream(
        KernelRequest(
            question="导语是什么",
            page_context=page_context,
            reasoning_effort="high",
        ),
        profile="team",
        user={"username": "admin"},
    ):
        team_output.append(chunk)

    assert "event: reasoning" in "".join(team_output)
    assert llm.options[-1] == ("enabled", "high")

    visitor_output = []
    async for chunk in kernel.stream(
        KernelRequest(
            question="另一个问题",
            page_context=page_context,
            reasoning_effort="max",
        ),
        profile="visitor",
        user=None,
    ):
        visitor_output.append(chunk)

    assert "event: reasoning" not in "".join(visitor_output)
    assert llm.options[-1] == ("enabled", "max")

    cached_high = []
    async for chunk in kernel.stream(
        KernelRequest(
            question="导语是什么",
            page_context=page_context,
            reasoning_effort="high",
        ),
        profile="team",
        user={"username": "admin"},
    ):
        cached_high.append(chunk)
    assert "answerCacheHit" in "".join(cached_high)

    cached_low = []
    async for chunk in kernel.stream(
        KernelRequest(
            question="导语是什么",
            page_context=page_context,
            reasoning_effort="low",
        ),
        profile="team",
        user={"username": "admin"},
    ):
        cached_low.append(chunk)
    assert '"answerCacheHit": false' in "".join(cached_low)


@pytest.mark.asyncio
async def test_tour_mode_rejects_out_of_scope_without_calling_model(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(db, "settings", DummySettings(tmp_path / "tour-scope.db"))
    db.init_db()

    class FailingLLM:
        primary_model = "mock-model"

        async def stream(self, *args, **kwargs):
            raise AssertionError("model should not be called")
            yield

    kernel = AgentKernel(
        ToolRegistry({}, {"visitor": []}),
        FakeRag(),
        FailingLLM(),
    )
    output = []
    async for chunk in kernel.stream(
        KernelRequest(
            question="明天天气怎么样",
            mode="tour",
            tour_context={
                "title": "Configured tour",
                "stepIndex": 0,
                "stepCount": 12,
                "currentStep": {"title": "从这里启程"},
            },
        ),
        profile="visitor",
        user=None,
    ):
        output.append(chunk)

    text = "".join(output)
    assert '"tourScope": "out_of_scope"' in text
    assert "不在当前主题参观范围" in text
    assert "从这里启程" in text

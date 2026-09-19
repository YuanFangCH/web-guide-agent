import httpx
import pytest

from app.llm_client import LLMClient


class DummyConfig:
    chat_base_url = "http://mock.test/v1"
    chat_api_key = ""
    chat_model = "mock-model"
    chat_fallback_base_url = ""
    chat_fallback_api_key = ""
    chat_fallback_model = ""
    chat_thinking = "enabled"
    chat_reasoning_effort = "low"


@pytest.mark.asyncio
async def test_llm_client_parses_streamed_tokens_and_tools() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = __import__("json").loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                'data: {"choices":[{"delta":{"reasoning_content":"先判断"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
                '"id":"call-1","function":{"name":"rag_search",'
                '"arguments":"{\\"query\\":\\"测试\\"}"}}]}}]}\n\n'
                "data: [DONE]\n\n"
            ).encode("utf-8"),
        )

    client = LLMClient(DummyConfig(), transport=httpx.MockTransport(handler))
    events = [event async for event in client.stream([{"role": "user", "content": "你好"}])]

    assert events[0].type == "reasoning"
    assert events[0].text == "先判断"
    assert events[1].type == "token"
    assert events[1].text == "你好"
    assert events[2].type == "tool_calls"
    assert events[2].tool_calls[0]["function"]["name"] == "rag_search"
    assert events[-1].type == "done"
    assert seen["payload"]["thinking"] == {"type": "enabled"}
    assert seen["payload"]["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_llm_client_accepts_per_request_reasoning() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = __import__("json").loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n\n",
        )

    client = LLMClient(DummyConfig(), transport=httpx.MockTransport(handler))
    _ = [
        event
        async for event in client.stream(
            [{"role": "user", "content": "你好"}],
            thinking="disabled",
            reasoning_effort="",
        )
    ]

    assert seen["payload"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in seen["payload"]

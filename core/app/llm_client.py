from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings, settings


class ModelNotConfigured(RuntimeError):
    pass


@dataclass
class ModelEndpoint:
    base_url: str
    api_key: str
    model: str


@dataclass
class LLMStreamEvent:
    type: str
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class LLMClient:
    def __init__(
        self,
        config: Settings = settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport

    def _endpoints(self) -> list[ModelEndpoint]:
        endpoints: list[ModelEndpoint] = []
        if self.config.chat_base_url and self.config.chat_model:
            endpoints.append(
                ModelEndpoint(
                    self.config.chat_base_url,
                    self.config.chat_api_key,
                    self.config.chat_model,
                )
            )
        if (
            self.config.chat_fallback_base_url
            and self.config.chat_fallback_model
        ):
            endpoints.append(
                ModelEndpoint(
                    self.config.chat_fallback_base_url,
                    self.config.chat_fallback_api_key,
                    self.config.chat_fallback_model,
                )
            )
        return endpoints

    @property
    def configured(self) -> bool:
        return bool(self._endpoints())

    @property
    def primary_model(self) -> str:
        endpoints = self._endpoints()
        return endpoints[0].model if endpoints else "unconfigured"

    @staticmethod
    def _chat_url(base_url: str) -> str:
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        endpoints = self._endpoints()
        if not endpoints:
            raise ModelNotConfigured("chat_model_not_configured")
        last_error: Exception | None = None
        for endpoint in endpoints:
            emitted = False
            try:
                async for event in self._stream_endpoint(
                    endpoint,
                    messages,
                    tools=tools,
                    thinking=thinking,
                    reasoning_effort=reasoning_effort,
                ):
                    emitted = True
                    yield event
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if emitted:
                    raise
        raise last_error or ModelNotConfigured("chat_model_not_configured")

    async def _stream_endpoint(
        self,
        endpoint: ModelEndpoint,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        thinking: str | None,
        reasoning_effort: str | None,
    ) -> AsyncIterator[LLMStreamEvent]:
        payload: dict[str, Any] = {
            "model": endpoint.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        effective_thinking = (
            self.config.chat_thinking if thinking is None else thinking
        )
        effective_effort = (
            self.config.chat_reasoning_effort
            if reasoning_effort is None
            else reasoning_effort
        )
        if effective_thinking in {"enabled", "disabled"}:
            payload["thinking"] = {"type": effective_thinking}
        if effective_effort:
            payload["reasoning_effort"] = effective_effort
        headers = {"Content-Type": "application/json"}
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"

        tool_calls: dict[int, dict[str, Any]] = {}
        async with httpx.AsyncClient(
            timeout=None, transport=self.transport
        ) as client:
            async with client.stream(
                "POST",
                self._chat_url(endpoint.base_url),
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        choice = chunk["choices"][0]
                        delta = choice.get("delta", {})
                    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                        continue

                    content = delta.get("content")
                    if isinstance(content, list):
                        content = "".join(
                            item.get("text", "")
                            for item in content
                            if isinstance(item, dict)
                        )
                    if content:
                        yield LLMStreamEvent(type="token", text=str(content))

                    reasoning = delta.get("reasoning_content")
                    if isinstance(reasoning, list):
                        reasoning = "".join(
                            item.get("text", "")
                            for item in reasoning
                            if isinstance(item, dict)
                        )
                    if reasoning:
                        yield LLMStreamEvent(
                            type="reasoning", text=str(reasoning)
                        )

                    for call_delta in delta.get("tool_calls") or []:
                        index = int(call_delta.get("index") or 0)
                        current = tool_calls.setdefault(
                            index,
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if call_delta.get("id"):
                            current["id"] = call_delta["id"]
                        function = call_delta.get("function") or {}
                        if function.get("name"):
                            current["function"]["name"] += function["name"]
                        if function.get("arguments"):
                            current["function"]["arguments"] += function["arguments"]

        if tool_calls:
            yield LLMStreamEvent(
                type="tool_calls",
                tool_calls=[tool_calls[index] for index in sorted(tool_calls)],
            )
        yield LLMStreamEvent(type="done")

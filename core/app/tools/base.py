from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolResult:
    ok: bool = True
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    client_actions: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["clientActions"] = value.pop("client_actions")
        return value

    def model_content(self, limit: int = 8000) -> str:
        marker_lines = [
            f"[CLIENT_ACTION:{action['type']}]"
            for action in self.client_actions
            if action.get("type")
        ]
        body = self.content.strip()
        if marker_lines:
            body = "\n".join([body, *marker_lines]).strip()
        return body[:limit]


@dataclass
class ToolContext:
    profile: str
    page_context: dict[str, Any]
    conversation_id: str
    prompt_version: str
    model: str
    rag_client: Any
    website_db: Any = None
    website_write: Any = None
    write_session: dict[str, Any] | None = None
    user: dict[str, Any] | None = None


ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    side_effect: bool = False
    requires_write: bool = False
    required_write_mode: str | None = None
    timeout_seconds: float = 20.0

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

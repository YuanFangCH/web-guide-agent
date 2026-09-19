from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .priorities import PriorityTier


class AgentSection(BaseModel):
    anchor: str = "section-1"
    heading: str = ""
    text: str


class AgentDocumentInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: str
    source_id: str = Field(alias="sourceId")
    type: Literal["post", "image", "video", "page", "document", "team-note"]
    title: str = ""
    url: str = ""
    content_html: str = Field(default="", alias="contentHtml")
    content_text: str = Field(default="", alias="contentText")
    sections: list[AgentSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    priority: PriorityTier | None = None
    checksum: str = ""
    updated_at: str = Field(alias="updatedAt")

    @field_validator("source", "source_id")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must_not_be_empty")
        return value.strip()


class DocumentBatchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[AgentDocumentInput]
    replace_source: bool = Field(default=False, alias="replaceSource")
    source: str | None = None


class UrlIngestionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    urls: list[str]
    source: str = "url"
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    query: str
    top_k: int = Field(default=8, alias="topK", ge=1, le=50)
    source_filter: str | None = Field(default=None, alias="sourceFilter")


class ApiKeyCreateRequest(BaseModel):
    name: str
    scopes: list[str] = Field(
        default_factory=lambda: [
            "documents:write",
            "documents:read",
            "ingestions:write",
            "retrieval:read",
        ]
    )

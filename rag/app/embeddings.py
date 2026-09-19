from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from typing import Protocol

from haystack import Document
from haystack.components.embedders import OpenAIDocumentEmbedder, OpenAITextEmbedder
from haystack.utils import Secret

from .config import Settings


class EmbeddingBackend(Protocol):
    name: str

    def embed_documents(self, documents: list[Document]) -> list[Document]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class OpenAIEmbeddingBackend:
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.embedding_model:
            raise RuntimeError("EMBEDDING_MODEL is required")
        secret = Secret.from_token(settings.embedding_api_key or "not-set")
        kwargs = {
            "api_key": secret,
            "model": settings.embedding_model,
        }
        if settings.embedding_base_url:
            kwargs["api_base_url"] = settings.embedding_base_url
        self.document_embedder = OpenAIDocumentEmbedder(**kwargs)
        self.text_embedder = OpenAITextEmbedder(**kwargs)

    def embed_documents(self, documents: list[Document]) -> list[Document]:
        return self.document_embedder.run(documents=documents)["documents"]

    def embed_query(self, text: str) -> list[float]:
        return self.text_embedder.run(text=text)["embedding"]


class HashEmbeddingBackend:
    """Deterministic offline backend for tests and local smoke checks."""

    name = "hash"

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimension:
            digest = hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
            values.extend((byte / 127.5) - 1 for byte in digest)
            counter += 1
        values = values[: self.dimension]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    def embed_documents(self, documents: list[Document]) -> list[Document]:
        return [
            replace(document, embedding=self._vector(document.content or ""))
            for document in documents
        ]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def build_embedding_backend(settings: Settings) -> EmbeddingBackend:
    if settings.embedding_provider == "hash":
        return HashEmbeddingBackend(settings.embedding_dimension)
    return OpenAIEmbeddingBackend(settings)

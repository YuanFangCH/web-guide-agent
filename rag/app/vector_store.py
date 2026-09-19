from __future__ import annotations

import re
from typing import Any

import psycopg
from haystack import Document
from haystack.document_stores.types import DuplicatePolicy
from haystack.utils import Secret
from haystack_integrations.components.retrievers.pgvector import (
    PgvectorEmbeddingRetriever,
    PgvectorKeywordRetriever,
)
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from psycopg import sql
from psycopg.rows import dict_row

from .config import Settings
from .embeddings import EmbeddingBackend
from .priorities import priority_label, priority_name, resolve_priority

SOURCE_WEIGHTS = {
    "website": 1.25,
    "team-note": 1.1,
    "document": 1.0,
    "url": 0.9,
    "upload": 0.95,
}

TYPE_WEIGHTS = {
    "page": 1.15,
    "post": 1.1,
    "team-note": 1.08,
    "document": 1.0,
    "image": 0.92,
    "video": 0.92,
}

PRIORITY_WEIGHTS = {
    1: 2.5,
    2: 1.5,
    3: 1.0,
}

STOP_TERMS = {
    "什么",
    "哪些",
    "怎么",
    "如何",
    "为什么",
    "请",
    "讲解",
    "介绍",
    "一下",
    "关于",
    "当前",
    "页面",
    "资料",
}

QUERY_ALIASES: tuple[tuple[tuple[str, ...], str], ...] = ()

SOURCE_INTENT_TERMS = ("网站", "站内", "本站", "页面", "首页")
TYPE_INTENT_TERMS = {
    "post": ("文章", "推文", "帖子"),
    "image": ("图片", "图库", "照片", "相册"),
    "video": ("视频", "影片"),
}


def _query_terms(query: str) -> list[str]:
    cleaned = query
    for stop_term in sorted(STOP_TERMS, key=len, reverse=True):
        cleaned = cleaned.replace(stop_term, " ")
    tokens = re.findall(
        r"[\u4e00-\u9fff]+|[A-Za-z0-9][A-Za-z0-9._-]*", cleaned
    )
    terms: set[str] = set()
    for token in tokens:
        normalized = token.lower().strip()
        if not normalized or normalized in STOP_TERMS:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", normalized):
            if len(normalized) <= 6:
                terms.add(normalized)
            for size in (2, 3, 4):
                if len(normalized) >= size:
                    terms.update(
                        normalized[index : index + size]
                        for index in range(len(normalized) - size + 1)
                    )
        else:
            terms.add(normalized)
    for required_terms, alias in QUERY_ALIASES:
        if all(term in query for term in required_terms):
            terms.add(alias)
    return sorted(
        (term for term in terms if term not in STOP_TERMS),
        key=lambda value: (-len(value), value),
    )[:40]


def _priority_weight(document: Document) -> float:
    return PRIORITY_WEIGHTS[
        resolve_priority(
            document.meta.get("knowledge_priority"),
            str(document.meta.get("source", "")),
        )
    ]


def _intent_weight(query: str, document: Document) -> float:
    weight = 1.0
    source = str(document.meta.get("source") or "")
    document_type = str(document.meta.get("type") or "")
    if source == "website" and any(term in query for term in SOURCE_INTENT_TERMS):
        weight *= 2.5
    intent_terms = TYPE_INTENT_TERMS.get(document_type, ())
    if any(term in query for term in intent_terms):
        weight *= 3.0
    return weight


def _ranking_score(
    document: Document,
    *,
    result_weight: float,
    rank: int,
    query: str = "",
    matched_terms: int = 3,
    lexical_hits: int = 0,
) -> float:
    source_weight = SOURCE_WEIGHTS.get(
        str(document.meta.get("source", "")), 1.0
    )
    type_weight = TYPE_WEIGHTS.get(
        str(document.meta.get("type", "")), 1.0
    )
    relevance_factor = min(1.0, max(0, matched_terms - 1) / 2.0)
    priority_weight = 1.0 + (_priority_weight(document) - 1.0) * relevance_factor
    score = (
        result_weight
        * source_weight
        * type_weight
        * priority_weight
        * _intent_weight(query, document)
        / (60 + rank + 1)
    )
    if lexical_hits:
        score += min(lexical_hits, 6) * 0.01
    return score


class RagIndex:
    def __init__(self, settings: Settings, embeddings: EmbeddingBackend) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self.database_url = settings.database_url
        self.table_name = settings.vector_table_name
        self.store = PgvectorDocumentStore(
            connection_string=Secret.from_token(settings.database_url),
            table_name=settings.vector_table_name,
            embedding_dimension=settings.embedding_dimension,
            vector_function="cosine_similarity",
            recreate_table=False,
            search_strategy="hnsw",
            language="simple",
        )
        self.embedding_retriever = PgvectorEmbeddingRetriever(
            document_store=self.store
        )
        self.keyword_retriever = PgvectorKeywordRetriever(document_store=self.store)

    def _lexical_documents(
        self, query: str, terms: list[str]
    ) -> list[tuple[Document, int]]:
        if not terms:
            return []
        statement = sql.SQL(
            """
            SELECT id, content, meta
            FROM {}
            WHERE content ILIKE ANY(%s)
            LIMIT 1000
            """
        ).format(sql.Identifier(self.table_name))
        patterns = [f"%{term}%" for term in terms]
        with psycopg.connect(
            self.database_url, row_factory=dict_row
        ) as connection:
            rows = connection.execute(statement, (patterns,)).fetchall()

        ranked: list[tuple[Document, int, int, int]] = []
        for row in rows:
            content = str(row.get("content") or "").lower()
            matched_terms = [term for term in terms if term in content]
            if matched_terms:
                coverage = len(matched_terms)
                specificity = sum(len(term) for term in matched_terms)
                hits = sum(min(content.count(term), 3) for term in matched_terms)
                ranked.append(
                    (
                        Document(
                            id=row["id"],
                            content=row.get("content") or "",
                            meta=row.get("meta") or {},
                        ),
                        coverage,
                        specificity,
                        hits,
                    )
                )
        ranked.sort(
            key=lambda item: (
                -item[1],
                -item[2],
                -item[3],
                item[0].meta.get("type") not in {"page", "post"},
            )
        )
        return [(document, coverage) for document, coverage, _, _ in ranked[:48]]

    def index_document(
        self, old_chunk_ids: list[str], chunks: list[dict[str, Any]]
    ) -> list[str]:
        if old_chunk_ids:
            self.store.delete_documents(document_ids=old_chunk_ids)
        if not chunks:
            return []
        documents = [
            Document(id=chunk["id"], content=chunk["content"], meta=chunk["meta"])
            for chunk in chunks
        ]
        documents = self.embeddings.embed_documents(documents)
        self.store.write_documents(documents, policy=DuplicatePolicy.OVERWRITE)
        return [document.id for document in documents]

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if chunk_ids:
            self.store.delete_documents(document_ids=chunk_ids)

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 8,
        source_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        candidate_k = max(top_k * 3, 12)
        terms = _query_terms(query)
        vector_documents: list[Document] = []
        keyword_documents: list[Document] = []
        lexical_documents: list[tuple[Document, int]] = []
        errors: list[str] = []

        try:
            query_embedding = self.embeddings.embed_query(query)
            vector_documents = self.embedding_retriever.run(
                query_embedding=query_embedding, top_k=candidate_k
            )["documents"]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"vector:{exc}")

        try:
            keyword_documents = self.keyword_retriever.run(
                query=query, top_k=candidate_k
            )["documents"]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"keyword:{exc}")

        try:
            lexical_documents = self._lexical_documents(query, terms)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"lexical:{exc}")

        if (
            not vector_documents
            and not keyword_documents
            and not lexical_documents
            and errors
        ):
            raise RuntimeError("; ".join(errors))

        scores: dict[str, float] = {}
        documents: dict[str, Document] = {}
        for result_set, result_weight in (
            (vector_documents, 0.7),
            (keyword_documents, 1.2),
        ):
            for rank, document in enumerate(result_set):
                if source_filter and document.meta.get("source") != source_filter:
                    continue
                documents[document.id] = document
                matched_terms = sum(
                    term in (document.content or "").lower() for term in terms
                )
                intent_weight = _intent_weight(query, document)
                if (
                    self.settings.embedding_provider == "hash"
                    and terms
                    and matched_terms == 0
                    and intent_weight == 1.0
                ):
                    continue
                scores[document.id] = scores.get(document.id, 0.0) + (
                    _ranking_score(
                        document,
                        result_weight=result_weight,
                        rank=rank,
                        query=query,
                        matched_terms=matched_terms,
                    )
                )

        for rank, (document, hits) in enumerate(lexical_documents):
            if source_filter and document.meta.get("source") != source_filter:
                continue
            documents[document.id] = document
            matched_terms = sum(
                term in (document.content or "").lower() for term in terms
            )
            intent_weight = _intent_weight(query, document)
            if (
                self.settings.embedding_provider == "hash"
                and terms
                and matched_terms == 0
                and intent_weight == 1.0
            ):
                continue
            scores[document.id] = scores.get(document.id, 0.0) + (
                _ranking_score(
                    document,
                    result_weight=2.2,
                    rank=rank,
                    query=query,
                    matched_terms=matched_terms,
                    lexical_hits=hits,
                )
            )

        ordered = sorted(scores, key=scores.get, reverse=True)[:top_k]
        results: list[dict[str, Any]] = []
        for document_id in ordered:
            document = documents[document_id]
            priority = priority_name(
                resolve_priority(
                    document.meta.get("knowledge_priority"),
                    str(document.meta.get("source", "")),
                )
            )
            results.append(
                {
                    "id": document_id,
                    "content": document.content or "",
                    "score": scores[document_id],
                    "source": document.meta.get("source"),
                    "sourceId": document.meta.get("source_id"),
                    "type": document.meta.get("type"),
                    "title": document.meta.get("title"),
                    "url": document.meta.get("url"),
                    "anchor": document.meta.get("anchor"),
                    "sectionTitle": document.meta.get("section_title"),
                    "priority": priority,
                    "priorityLabel": priority_label(priority),
                    "bookTitle": document.meta.get("book_title"),
                    "chapterTitle": document.meta.get("chapter_title"),
                    "pageStart": document.meta.get("page_start"),
                    "pageEnd": document.meta.get("page_end"),
                    "pageNumber": document.meta.get("page_number"),
                }
            )
        return results

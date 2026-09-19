from haystack import Document

from app.vector_store import _intent_weight, _query_terms, _ranking_score


def _document(priority: str, source: str = "book:test") -> Document:
    return Document(
        id=f"{source}-{priority}",
        content="测试",
        meta={
            "source": source,
            "type": "document",
            "knowledge_priority": priority,
        },
    )


def test_priority_changes_equal_relevance_ranking() -> None:
    primary = _ranking_score(
        _document("primary"), result_weight=1.2, rank=0
    )
    secondary = _ranking_score(
        _document("secondary"), result_weight=1.2, rank=0
    )
    tertiary = _ranking_score(
        _document("tertiary"), result_weight=1.2, rank=0
    )

    assert primary > secondary > tertiary


def test_high_relevance_lower_tier_can_beat_weak_primary() -> None:
    weak_primary = _ranking_score(
        _document("primary"), result_weight=0.7, rank=35
    )
    strong_tertiary = _ranking_score(
        _document("tertiary", source="url"),
        result_weight=2.2,
        rank=0,
        lexical_hits=6,
    )

    assert strong_tertiary > weak_primary


def test_single_broad_match_does_not_get_full_priority_boost() -> None:
    primary = _ranking_score(
        _document("primary"),
        result_weight=1.2,
        rank=0,
        matched_terms=1,
    )
    tertiary = _ranking_score(
        _document("tertiary"),
        result_weight=1.2,
        rank=0,
        matched_terms=1,
    )

    assert primary == tertiary


def test_query_terms_and_intent_weights() -> None:
    terms = _query_terms("railway maintenance plan")
    assert "railway" in terms
    assert "maintenance" in terms

    website_post = Document(
        id="website-post",
        content="网站文章",
        meta={"source": "website", "type": "post"},
    )
    book_document = Document(
        id="book",
        content="书籍资料",
        meta={"source": "book:test", "type": "document"},
    )

    assert _intent_weight("网站有哪些文章", website_post) > 1
    assert _intent_weight("网站有哪些文章", book_document) == 1

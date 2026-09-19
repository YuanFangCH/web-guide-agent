from app.vector_store import _query_terms


def test_query_terms_extract_chinese_ngrams() -> None:
    terms = _query_terms("铁路维护计划")

    assert "铁路" in terms
    assert "维护" in terms
    assert "计划" in terms


def test_query_terms_remove_common_instruction_words() -> None:
    terms = _query_terms("请讲解一下当前页面")

    assert terms == []

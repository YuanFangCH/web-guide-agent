from app.section_match import match_section


SECTIONS = [
    {"anchor": "a", "heading": "项目背景", "text": "背景内容"},
    {"anchor": "b", "heading": "工具调用与熔断", "text": "工具最多十轮"},
    {"anchor": "c", "heading": "RAG 缓存层", "text": "缓存页面章节"},
]


def test_ordinal_match() -> None:
    assert match_section("请讲第二章", SECTIONS)["section"]["anchor"] == "b"


def test_title_match() -> None:
    assert match_section("工具调用怎么熔断", SECTIONS)["strategy"] == "title"


def test_english_match() -> None:
    assert match_section("RAG 缓存是什么", SECTIONS)["strategy"] == "title"


def test_fuzzy_fallback() -> None:
    result = match_section("缓存页面章节内容", SECTIONS)
    assert result["section"]["anchor"] == "c"

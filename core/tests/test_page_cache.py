from app import db


class DummySettings:
    def __init__(self, path):
        self.db_path = str(path)


def test_page_cache_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "settings", DummySettings(tmp_path / "cache.db"))
    db.init_db()
    db.upsert_page_cache(
        page_key="page-1",
        site_id="test",
        url="https://example.test/",
        title="测试页",
        content_hash="hash-1",
        page_text="页面正文",
        sections=[
            {
                "anchor": "intro",
                "heading": "导语",
                "text": "第一段",
            }
        ],
    )

    page = db.get_page_cache("page-1")
    section = db.get_cached_section("page-1", "intro")

    assert page["title"] == "测试页"
    assert page["sections"][0]["heading"] == "导语"
    assert section["text"] == "第一段"


def test_section_answer_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "settings", DummySettings(tmp_path / "answer.db"))
    db.init_db()
    db.save_section_answer(
        section_hash="section-hash",
        prompt_version="v1",
        model="mock",
        answer="缓存答案",
        sources=[{"title": "来源"}],
    )

    cached = db.get_section_answer("section-hash", "v1", "mock")

    assert cached["answer"] == "缓存答案"
    assert cached["sources"][0]["title"] == "来源"
    assert cached["hit_count"] == 0

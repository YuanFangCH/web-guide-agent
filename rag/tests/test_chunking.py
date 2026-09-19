from app.chunking import build_chunks


def test_build_chunks_preserves_source_metadata() -> None:
    document = {
        "id": "doc-1",
        "source": "website",
        "source_id": "post-1",
        "type": "post",
        "title": "测试文章",
        "url": "https://example.test/posts/1",
        "content_text": "",
        "metadata": {"tags": ["railway", "maintenance"]},
        "knowledge_priority": 1,
        "sections": [
            {
                "anchor": "intro",
                "heading": "导语",
                "text": "第一段。" * 300,
            }
        ],
    }

    chunks = build_chunks(document)

    assert len(chunks) >= 2
    assert chunks[0]["meta"]["source"] == "website"
    assert chunks[0]["meta"]["anchor"] == "intro"
    assert chunks[0]["meta"]["tags"] == "railway, maintenance"
    assert chunks[0]["meta"]["knowledge_priority"] == "1"
    assert chunks[0]["meta"]["priority_label"] == "一级资料"
    assert chunks[0]["id"] != chunks[1]["id"]


def test_build_chunks_preserves_book_metadata() -> None:
    document = {
        "id": "doc-book",
        "source": "book:example",
        "source_id": "example:chunk_004",
        "type": "document",
        "title": "Example Book · Chapter 1 · Pages 8-12",
        "url": "",
        "content_text": "",
        "knowledge_priority": 1,
        "metadata": {
            "bookKey": "example",
            "bookTitle": "Example Book",
            "bookAuthor": "Example Author",
            "bookIsbn": "978-0-00-000000-0",
            "chapterId": "ch01",
            "chapterTitle": "Chapter 1",
            "pageStart": 8,
            "pageEnd": 12,
            "priorityReason": "source_priority",
        },
        "sections": [
            {
                "anchor": "page-008",
                "heading": "第8页",
                "text": "Example book content.",
            }
        ],
    }

    chunk = build_chunks(document)[0]

    assert chunk["meta"]["book_title"] == "Example Book"
    assert chunk["meta"]["book_author"] == "Example Author"
    assert chunk["meta"]["chapter_title"] == "Chapter 1"
    assert chunk["meta"]["page_start"] == "8"
    assert chunk["meta"]["page_end"] == "12"
    assert chunk["meta"]["page_number"] == "8"
    assert chunk["meta"]["priority_reason"] == "source_priority"


def test_build_chunks_falls_back_to_content_text() -> None:
    document = {
        "id": "doc-2",
        "source": "upload",
        "source_id": "file-1",
        "type": "document",
        "title": "文件",
        "url": "",
        "content_text": "没有章节结构的正文。",
        "metadata": {},
        "sections": [],
    }

    chunks = build_chunks(document)

    assert len(chunks) == 1
    assert chunks[0]["content"] == "文件 没有章节结构的正文。"

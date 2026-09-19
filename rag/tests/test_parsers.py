from app.parsers import extract_sections_from_html, html_to_text


def test_extract_explicit_sections() -> None:
    sections = extract_sections_from_html(
        """
        <h2>普通标题</h2>
        <section data-agent-section="intro" data-agent-title="导语">
          <h2>内部标题</h2><p>第一段</p>
        </section>
        """
    )

    assert sections == [
        {
            "anchor": "intro",
            "heading": "导语",
            "text": "内部标题\n第一段",
        }
    ]


def test_extract_fallback_blocks_without_headings() -> None:
    sections = extract_sections_from_html(
        f"<p>{'甲' * 700}</p><p>{'乙' * 500}</p>"
    )

    assert len(sections) == 2
    assert sections[0]["anchor"] == "section-1"
    assert sections[1]["anchor"] == "section-2"


def test_html_to_text_removes_scripts() -> None:
    assert html_to_text("<script>alert(1)</script><h2>标题</h2><p>正文</p>") == (
        "标题\n正文"
    )

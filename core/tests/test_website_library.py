from app.website_library import build_post_download_html, content_disposition


def test_post_download_contains_only_safe_html() -> None:
    payload = build_post_download_html(
        {
            "title": "测试推文",
            "slug": "test-post",
            "summary": "摘要",
            "categoryName": "技术",
            "publishedAt": "2026-09-12T00:00:00+00:00",
            "content": (
                '<p onclick="alert(1)">正文</p>'
                '<script>alert(2)</script>'
                '<a href="javascript:alert(3)">链接</a>'
                '<img src="/media/images/test.jpg">'
            ),
        },
        site_url="https://www.example.test",
    )
    text = payload.decode("utf-8")

    assert "测试推文" in text
    assert "onclick" not in text
    assert "<script" not in text
    assert "javascript:" not in text
    assert '<base href="https://www.example.test/">' in text


def test_content_disposition_supports_chinese_filename() -> None:
    header = content_disposition("铁路图片.jpg", "website-image-1.jpg")

    assert header.startswith('attachment; filename="website-image-1.jpg"')
    assert "filename*=UTF-8''" in header

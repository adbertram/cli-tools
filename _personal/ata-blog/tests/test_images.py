"""Regression tests for Notion image URL extraction during publishing."""

from __future__ import annotations

from ata_blog_cli.utils.images import extract_notion_image_urls


_S3 = "https://prod-files-secure.s3.us-west-2.amazonaws.com"
_SIGNED = (
    "/7e6ab015/c9b18c0a/image.png"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=ABC%2F20260611"
    "&X-Amz-Signature=deadbeef&x-id=GetObject"
)


def test_extracts_plain_image_url() -> None:
    url = f"{_S3}{_SIGNED}"
    md = f"![]({url})"
    assert extract_notion_image_urls(md) == [url]


def test_extracts_url_when_alt_text_contains_nested_markdown_link() -> None:
    """The reported bug: alt text with a nested link hid the real image URL.

    `![see [site](http://example.com/)](notion_url)` made the markdown-image
    regex capture the inner link instead of the Notion URL, so migration
    skipped it and shipped an expiring S3 URL.
    """
    url = f"{_S3}{_SIGNED}"
    md = f"![Screenshot of [adamtheautomator.com](http://adamtheautomator.com/) graph]({url})"
    assert extract_notion_image_urls(md) == [url]


def test_extracts_url_from_html_img_tag() -> None:
    url = f"{_S3}{_SIGNED}"
    md = f'<img src="{url}" alt="x" />'
    assert extract_notion_image_urls(md) == [url]


def test_dedupes_repeated_urls_preserving_order() -> None:
    first = f"{_S3}/a/image.png?X-Amz-Signature=aaa"
    second = f"{_S3}/b/image.png?X-Amz-Signature=bbb"
    md = f"![]({first})\n![]({second})\n![]({first})"
    assert extract_notion_image_urls(md) == [first, second]


def test_ignores_non_notion_urls() -> None:
    md = "![](https://adamtheautomator.com/wp-content/uploads/2026/06/x.png)"
    assert extract_notion_image_urls(md) == []

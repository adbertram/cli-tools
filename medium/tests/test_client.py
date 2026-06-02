from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace

import pytest

from cli_tools_shared.exceptions import ClientError

from medium_cli.client import (
    MediumClient,
    _render_medium_html,
    _visible_text_from_content,
)
from medium_cli.commands.common import read_content
from medium_cli.main import _test_handler


class FakePage:
    def __init__(self, url="https://medium.com/new-story"):
        self.url = url
        self.waited_for = []
        self.eval_calls = []
        self.network_idle_calls = []
        self.type_calls = []
        self.save_after_typing = True

    def wait_for_selector(self, selector, timeout=0):
        self.waited_for.append((selector, timeout))
        return None

    def evaluate(self, js, arg=None):
        self.eval_calls.append((js, arg))
        if arg in (
            '[data-testid="editorTitleParagraph"]',
            '[data-testid="editorParagraphText"]',
        ):
            return {"success": True}
        if arg == {"title": "Draft title", "bodyText": "Hello world"}:
            return {
                "url": self.url,
                "titleText": "Draft title",
                "bodyText": "Hello world",
                "containsTitle": True,
                "containsBody": True,
            }
        return {"success": True}

    def type_text(self, text):
        self.type_calls.append(text)
        if self.save_after_typing and len(self.type_calls) == 2:
            self.url = "https://medium.com/p/abc123/edit"
        return None

    def wait_for_network_idle(self, timeout=0, idle_ms=0):
        self.network_idle_calls.append((timeout, idle_ms))
        return True

    def wait_for_timeout(self, ms):
        return None


class FakeBrowser:
    AUTH_CHECK_URL = "https://medium.com/new-story"
    AUTH_URL_PATTERN = r"/m/signin|/m/signup|/m/register|/m/sign-in"

    def __init__(self, page):
        self.page = page
        self.closed = False
        self.urls = []

    def get_page(self, url):
        self.urls.append(url)
        return self.page

    def close(self):
        self.closed = True


def fake_config(page=None):
    page = page or FakePage()
    browser = FakeBrowser(page)
    return SimpleNamespace(
        storage_dir=Path(mkdtemp(prefix="medium-client-test-")),
        get_browser=lambda: browser,
        browser=browser,
    )


def test_render_medium_html_wraps_plain_text():
    assert _render_medium_html("Hello\nworld") == "<p>Hello<br>world</p>"


def test_render_medium_html_keeps_html():
    assert _render_medium_html("<p>Hello</p>") == "<p>Hello</p>"


def test_visible_text_from_html_strips_tags():
    assert _visible_text_from_content("<h1>Hello</h1><p>world</p>") == "Hello world"


def test_create_post_fills_editor_and_returns_draft_url():
    config = fake_config()
    client = MediumClient(config=config)

    post = client.create_post(title="Draft title", content="Hello world")

    assert post == {
        "title": "Draft title",
        "draft_url": "https://medium.com/p/abc123/edit",
        "edit_url": "https://medium.com/p/abc123/edit",
    }
    assert config.browser.urls == ["https://medium.com/new-story"]
    assert config.browser.page.waited_for == [
        ('[contenteditable="true"]', 60000),
        ('[data-testid="editorTitleParagraph"]', 60000),
        ('[data-testid="editorParagraphText"]', 60000),
    ]
    assert [call[1] for call in config.browser.page.eval_calls[:2]] == [
        '[data-testid="editorTitleParagraph"]',
        '[data-testid="editorParagraphText"]',
    ]
    assert config.browser.page.type_calls == ["Draft title", "Hello world"]
    assert config.browser.page.network_idle_calls == [(10.0, 1000)]


def test_create_post_requires_authenticated_browser_session():
    config = fake_config(page=FakePage(url="https://medium.com/m/signin"))
    client = MediumClient(config=config)

    with pytest.raises(ClientError, match="Run 'medium auth login' first"):
        client.create_post(title="Draft title", content="Hello world")


def test_create_post_requires_draft_edit_url():
    config = fake_config()
    client = MediumClient(config=config)
    config.browser.page.save_after_typing = False

    with pytest.raises(ClientError, match="draft edit URL"):
        client.create_post(title="Draft title", content="Hello world")


def test_test_handler_reports_signin_redirect():
    browser = FakeBrowser(FakePage(url="https://medium.com/m/signin"))
    config = SimpleNamespace(get_browser=lambda: browser)

    result = _test_handler(config)

    assert result["api_test"].startswith("failed: redirected to https://medium.com/m/signin")
    assert browser.closed is True


def test_read_content_requires_exactly_one_source(tmp_path):
    content_file = tmp_path / "post.md"
    content_file.write_text("# Title", encoding="utf-8")

    assert read_content(None, content_file) == "# Title"

    with pytest.raises(ClientError, match="exactly one"):
        read_content("inline", content_file)

    with pytest.raises(ClientError, match="exactly one"):
        read_content(None, None)

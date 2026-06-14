import pytest
from typer.testing import CliRunner

from youtube_cli import client as youtube_client
from youtube_cli.commands import channel
from youtube_cli.main import app


runner = CliRunner()


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def click(self):
        self.page.clicks.append(self.selector)
        if self.selector == youtube_client.POST_PLACEHOLDER_SELECTOR:
            self.page.state["editor_visible"] = True
            self.page.state["submit_visible"] = True
        if self.selector == youtube_client.POST_SUBMIT_SELECTOR:
            if not self.page.state["submit_enabled"]:
                raise AssertionError("submit clicked while disabled")
            self.page.posted = True
            self.page.state["editor_text"] = ""
            self.page.state["submit_enabled"] = False


class FakePage:
    def __init__(self, *, composer_visible=True):
        self.state = {
            "composer_visible": composer_visible,
            "placeholder_visible": composer_visible,
            "editor_visible": False,
            "submit_visible": False,
            "submit_enabled": False,
            "editor_text": "",
            "visibility": "Public",
        }
        self.clicks = []
        self.typed = []
        self.posted = False

    def evaluate(self, script):
        if script == youtube_client.COMPOSER_STATE_JS:
            return dict(self.state)
        if script == youtube_client.CLEAR_EDITOR_JS:
            self.state["editor_text"] = ""
            self.state["submit_enabled"] = False
            return None
        raise AssertionError(f"Unexpected script: {script[:80]}")

    def wait_for_timeout(self, _ms):
        return None

    def locator(self, selector):
        return FakeLocator(self, selector)

    def type_text(self, text):
        self.typed.append(text)
        self.state["editor_text"] = text
        self.state["submit_enabled"] = bool(text)
        self.state["submit_visible"] = True


class FakeBrowser:
    def __init__(self, page, *, authenticated=True):
        self.page = page
        self.authenticated = authenticated
        self.opened_url = None
        self.closed = False

    def is_authenticated(self):
        return self.authenticated

    def get_page(self, url):
        self.opened_url = url
        return self.page

    def close(self):
        self.closed = True


def test_channel_posts_create_help_lists_message_option():
    result = runner.invoke(app, ["channel", "posts", "create", "--help"])

    assert result.exit_code == 0
    assert "--message" in result.stdout
    assert "--dry-run" in result.stdout


def test_validate_channel_url_accepts_full_youtube_channel_url():
    assert channel._validate_channel_url("https://www.youtube.com/@BrickBuddyIO/?utm_source=test#posts") == (
        "https://www.youtube.com/@BrickBuddyIO"
    )


def test_validate_channel_url_rejects_non_youtube_url():
    with pytest.raises(ValueError, match="full https://www.youtube.com"):
        channel._validate_channel_url("https://example.com/@BrickBuddyIO")


def test_owned_channel_target_prefers_custom_url(monkeypatch):
    class FakeRequest:
        def execute(self):
            return {
                "items": [
                    {
                        "id": "channel-123",
                        "snippet": {"title": "Brick Buddy", "customUrl": "@BrickBuddyIO"},
                    }
                ]
            }

    class FakeChannels:
        def list(self, **_kwargs):
            return FakeRequest()

    class FakeService:
        def channels(self):
            return FakeChannels()

    class FakeClient:
        def get_youtube_service(self):
            return FakeService()

    monkeypatch.setattr(channel, "get_api_client", lambda profile=None: FakeClient())

    result = channel._owned_channel_target("brickbuddy")

    assert result == {
        "channel_id": "channel-123",
        "channel_title": "Brick Buddy",
        "channel_url": "https://www.youtube.com/@BrickBuddyIO",
    }


def test_browser_client_expands_composer_types_message_and_clicks_post():
    page = FakePage()
    browser = FakeBrowser(page)

    result = youtube_client.YouTubeBrowserClient(browser=browser).create_community_post(
        "https://www.youtube.com/@BrickBuddyIO",
        "New Brick Buddy update",
    )

    assert browser.opened_url == "https://www.youtube.com/@BrickBuddyIO"
    assert page.clicks == [
        youtube_client.POST_PLACEHOLDER_SELECTOR,
        youtube_client.POST_EDITOR_SELECTOR,
        youtube_client.POST_SUBMIT_SELECTOR,
    ]
    assert page.typed == ["New Brick Buddy update"]
    assert page.posted is True
    assert browser.closed is True
    assert result == {
        "posted": True,
        "dry_run": False,
        "channel_url": "https://www.youtube.com/@BrickBuddyIO",
        "visibility": "Public",
        "message": "New Brick Buddy update",
    }


def test_browser_client_dry_run_fills_composer_without_posting():
    page = FakePage()
    browser = FakeBrowser(page)

    result = youtube_client.YouTubeBrowserClient(browser=browser).create_community_post(
        "https://www.youtube.com/@BrickBuddyIO",
        "Dry run update",
        dry_run=True,
    )

    assert page.clicks == [
        youtube_client.POST_PLACEHOLDER_SELECTOR,
        youtube_client.POST_EDITOR_SELECTOR,
    ]
    assert page.posted is False
    assert browser.closed is True
    assert result == {
        "posted": False,
        "dry_run": True,
        "channel_url": "https://www.youtube.com/@BrickBuddyIO",
        "visibility": "Public",
        "message": "Dry run update",
    }


def test_browser_client_fails_when_composer_is_missing():
    browser = FakeBrowser(FakePage(composer_visible=False))

    with pytest.raises(youtube_client.ClientError, match="community post composer not found"):
        youtube_client.YouTubeBrowserClient(browser=browser).create_community_post(
            "https://www.youtube.com/@BrickBuddyIO",
            "Message",
        )

    assert browser.closed is True


def test_browser_client_fails_when_browser_session_is_not_authenticated():
    browser = FakeBrowser(FakePage(), authenticated=False)

    with pytest.raises(youtube_client.ClientError, match="browser session is not authenticated"):
        youtube_client.YouTubeBrowserClient(browser=browser).create_community_post(
            "https://www.youtube.com/@BrickBuddyIO",
            "Message",
        )

    assert browser.opened_url is None
    assert browser.closed is False

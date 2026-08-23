"""Browser transport, challenge, and error-message tests."""

import json
import tempfile
from pathlib import Path

import pytest
from cli_tools_shared.exceptions import ClientError

from vinted_cli.client import CHALLENGE_ATTEMPTS, VintedClient

# `_listing_shipping` is @cached, and the decorator needs a storage directory.
_STORAGE_DIR = Path(tempfile.mkdtemp(prefix="vinted-client-tests-"))


class _FakePage:
    """Stands in for the browser page the client fetches through."""

    def __init__(self, responses=None, cleared=True, title="Vinted"):
        self.responses = list(responses or [])
        self.cleared = cleared
        self.title = title
        self.evaluated = []
        self.gotos = []
        self.waits = []

    def evaluate(self, js, args=None):
        self.evaluated.append((js, args))
        if "document.cookie.includes('anon_id=')" in js:
            return {"cleared": self.cleared, "title": self.title}
        if not self.responses:
            raise AssertionError("no fake response left")
        return self.responses.pop(0)

    def goto(self, url):
        self.gotos.append(url)

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


class _FakeBrowser:
    def __init__(self, page, authenticated=True):
        self._page = page
        self._authenticated = authenticated
        self.closed = False

    def is_authenticated(self):
        return self._authenticated

    def get_page(self, url=None):
        return self._page

    def close(self):
        self.closed = True


class _FakeConfig:
    CREDENTIAL_TYPES = []
    storage_dir = _STORAGE_DIR

    def __init__(self, browser, base_url="https://www.vinted.com"):
        self._browser = browser
        self.base_url = base_url

    def get_browser(self):
        return self._browser


class _RecordingLimiter:
    """Records the limiter calls a request made, and never sleeps."""

    def __init__(self, max_retries=4):
        self.max_retries = max_retries
        self.interval = 0.9
        self.acquired = 0
        self.answered = 0
        self.throttled = []

    def acquire(self):
        self.acquired += 1
        return 0.0

    def on_answered(self):
        self.answered += 1

    def on_throttled(self, attempt, retry_after=None):
        self.throttled.append((attempt, retry_after))
        return 0.0


def _client(page=None, authenticated=True, base_url="https://www.vinted.com", limiter=None):
    browser = _FakeBrowser(page or _FakePage(), authenticated=authenticated)
    return (
        VintedClient(
            config=_FakeConfig(browser, base_url),
            limiter=limiter or _RecordingLimiter(),
        ),
        browser,
    )


def _ok(payload, content_type="application/json; charset=utf-8"):
    return {
        "status": 200,
        "contentType": content_type,
        "retryAfter": None,
        "url": "https://www.vinted.com/api/v2/catalog/items",
        "text": json.dumps(payload) if isinstance(payload, (dict, list)) else payload,
    }


# --- session requirement ---------------------------------------------------

def test_a_missing_session_names_the_login_command():
    client, _ = _client(authenticated=False)

    with pytest.raises(ClientError) as exc:
        client._cleared_page()

    message = str(exc.value)
    assert "vinted auth login" in message
    assert "Cloudflare" in message


def test_the_page_is_opened_once_and_reused():
    page = _FakePage(responses=[_ok({"a": 1}), _ok({"b": 2})])
    client, browser = _client(page)

    client._json("https://www.vinted.com/api/v2/catalog/items")
    client._json("https://www.vinted.com/api/v2/catalog/items")

    assert client._page is page
    assert browser.closed is False


def test_close_releases_the_browser():
    page = _FakePage(responses=[_ok({"a": 1})])
    client, browser = _client(page)
    client._json("https://www.vinted.com/api/v2/catalog/items")

    client.close()

    assert browser.closed is True
    assert client._page is None


# --- challenge handling ----------------------------------------------------

def test_a_cleared_page_needs_no_reload():
    page = _FakePage(responses=[_ok({"a": 1})], cleared=True)
    client, _ = _client(page)

    client._json("https://www.vinted.com/api/v2/catalog/items")

    assert page.gotos == []


def test_a_challenged_page_is_retried_then_reported():
    """Verified live: the first page open after a login can still be challenged."""
    page = _FakePage(cleared=False, title="Vinted")
    client, _ = _client(page)

    with pytest.raises(ClientError) as exc:
        client._cleared_page()

    message = str(exc.value)
    assert f"{CHALLENGE_ATTEMPTS} attempts" in message
    assert "vinted auth login --force" in message
    assert len(page.gotos) == CHALLENGE_ATTEMPTS - 1


def test_a_page_that_clears_on_the_second_look_succeeds():
    class _ClearsAfterOneReload(_FakePage):
        def evaluate(self, js, args=None):
            if "document.cookie.includes('anon_id=')" in js:
                return {"cleared": bool(self.gotos), "title": "Vinted"}
            return super().evaluate(js, args)

    page = _ClearsAfterOneReload(responses=[_ok({"a": 1})])
    client, _ = _client(page)

    assert client._json("https://www.vinted.com/api/v2/catalog/items") == {"a": 1}
    assert len(page.gotos) == 1


# --- request construction --------------------------------------------------

def test_query_parameters_are_encoded_into_the_url():
    page = _FakePage(responses=[_ok({"items": []})])
    client, _ = _client(page)

    client._json(
        "https://www.vinted.com/api/v2/catalog/items",
        params={"search_text": "lego bulk", "per_page": 2},
    )

    _, args = page.evaluated[-1]
    assert args["url"] == (
        "https://www.vinted.com/api/v2/catalog/items?search_text=lego+bulk&per_page=2"
    )
    assert args["accept"] == "application/json"


def test_the_fetch_script_sends_the_session_cookies():
    page = _FakePage(responses=[_ok({"items": []})])
    client, _ = _client(page)

    client._json("https://www.vinted.com/api/v2/catalog/items")

    js, _ = page.evaluated[-1]
    assert "credentials: 'include'" in js
    assert "X-Anon-Id" in js


# --- error reporting -------------------------------------------------------

def test_a_non_ok_status_names_the_url_and_content_type():
    page = _FakePage(responses=[{
        "status": 403,
        "contentType": "text/html; charset=UTF-8",
        "url": "https://www.vinted.com/api/v2/catalog/items",
        "text": "<html>blocked</html>",
    }])
    client, _ = _client(page)

    with pytest.raises(ClientError) as exc:
        client._json("https://www.vinted.com/api/v2/catalog/items")

    message = str(exc.value)
    assert "HTTP 403" in message
    assert "text/html" in message
    assert "<html>" not in message


def test_html_under_http_200_names_the_cloudflare_check():
    """Cloudflare answers a bot check with an HTML page under HTTP 200."""
    page = _FakePage(responses=[_ok("<html>Just a moment</html>", "text/html")])
    client, _ = _client(page)

    with pytest.raises(ClientError) as exc:
        client._json("https://www.vinted.com/api/v2/catalog/items")

    message = str(exc.value)
    assert "text/html" in message
    assert "Cloudflare" in message
    assert "Expecting value" not in message


def test_an_undecodable_json_body_is_reported():
    page = _FakePage(responses=[_ok("not json at all")])
    client, _ = _client(page)

    with pytest.raises(ClientError, match="not valid JSON"):
        client._json("https://www.vinted.com/api/v2/catalog/items")


def test_a_malformed_browser_result_is_reported():
    page = _FakePage(responses=["oops"])
    client, _ = _client(page)

    with pytest.raises(ClientError, match="no usable response"):
        client._json("https://www.vinted.com/api/v2/catalog/items")


# --- get_listing -----------------------------------------------------------

def test_get_listing_builds_the_slug_url_and_keeps_the_redirect_target():
    page = _FakePage(responses=[{
        "status": 200,
        "contentType": "text/html; charset=utf-8",
        "retryAfter": None,
        "url": "https://www.vinted.com/items/9571854910-lego-instructions-manuals",
        "text": "<script>self.__next_f.push([1,"
                + json.dumps('{"item":{"id":9571854910,"title":"Lego"}}')
                + "])</script>",
    }])
    client, _ = _client(page)

    record = VintedClient._get_listing.__wrapped__(
        client, "https://www.vinted.com", "9571854910"
    )

    _, args = page.evaluated[-1]
    assert args["url"] == "https://www.vinted.com/items/9571854910-item"
    assert args["accept"] == "text/html"
    assert record["id"] == "9571854910"
    assert record["title"] == "Lego"
    assert record["url"] == "https://www.vinted.com/items/9571854910-lego-instructions-manuals"


# --- shipping lookup -------------------------------------------------------

_SHIPPING = (
    '{"isPickupOnly":false,"areMultipleShippingOptionsAvailable":false,'
    '"isFreeShipping":true,"price":{"amount":"0","currencyCode":"USD"},'
    '"discount":null}'
)
_SHIPPING_PAGE = (
    "<script>self.__next_f.push([1,"
    + json.dumps('{"shippingDetails":' + _SHIPPING + "}")
    + "])</script>"
)


def _page_html(text):
    return {
        "status": 200,
        "contentType": "text/html; charset=utf-8",
        "retryAfter": None,
        "url": "https://www.vinted.com/items/1-item",
        "text": text,
    }


def test_add_shipping_reads_one_page_per_listing():
    page = _FakePage(responses=[_page_html(_SHIPPING_PAGE)] * 3)
    client, _ = _client(page)
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]

    client.add_shipping(rows)

    assert [row["shipping"]["price"] for row in rows] == ["0"] * 3
    assert [row["shipping"]["free"] for row in rows] == [True] * 3
    urls = [args["url"] for _, args in page.evaluated if args]
    assert urls == [f"https://www.vinted.com/items/{n}-item" for n in (1, 2, 3)]


def test_add_shipping_makes_no_request_for_an_empty_result():
    page = _FakePage()
    client, _ = _client(page)

    assert client.add_shipping([]) == []
    assert page.evaluated == []


def test_add_shipping_rejects_a_listing_id_that_could_rewrite_the_path():
    page = _FakePage(responses=[_page_html(_SHIPPING_PAGE)])
    client, _ = _client(page)

    with pytest.raises(ValueError, match="Invalid listing ID"):
        client.add_shipping([{"id": "../../etc/passwd"}])


# --- rate limiting ---------------------------------------------------------

def _throttled(status=429, retry_after=None):
    return {
        "status": status,
        "contentType": "text/html; charset=UTF-8",
        "retryAfter": retry_after,
        "url": "https://www.vinted.com/items/1-item",
        "text": "<html>slow down</html>",
    }


def test_every_request_asks_the_limiter_first():
    """Verified live: unpaced item page reads make Vinted answer HTTP 429."""
    page = _FakePage(responses=[_ok({"a": 1}), _ok({"b": 2})])
    limiter = _RecordingLimiter()
    client, _ = _client(page, limiter=limiter)

    client._json("https://www.vinted.com/api/v2/catalog/items")
    client._json("https://www.vinted.com/api/v2/catalog/items")

    assert limiter.acquired == 2
    assert limiter.answered == 2
    assert limiter.throttled == []


def test_a_throttled_request_backs_off_and_is_retried():
    page = _FakePage(responses=[_throttled(), _throttled(), _ok({"a": 1})])
    limiter = _RecordingLimiter()
    client, _ = _client(page, limiter=limiter)

    assert client._json("https://www.vinted.com/api/v2/catalog/items") == {"a": 1}
    assert limiter.acquired == 3
    assert limiter.throttled == [(0, None), (1, None)]
    assert limiter.answered == 1


def test_a_server_retry_after_value_reaches_the_limiter():
    page = _FakePage(responses=[_throttled(retry_after="7"), _ok({"a": 1})])
    limiter = _RecordingLimiter()
    client, _ = _client(page, limiter=limiter)

    client._json("https://www.vinted.com/api/v2/catalog/items")

    assert limiter.throttled == [(0, 7.0)]


def test_http_503_is_treated_as_pushback_not_as_a_failure():
    page = _FakePage(responses=[_throttled(status=503), _ok({"a": 1})])
    limiter = _RecordingLimiter()
    client, _ = _client(page, limiter=limiter)

    assert client._json("https://www.vinted.com/api/v2/catalog/items") == {"a": 1}
    assert limiter.throttled == [(0, None)]


def test_persistent_throttling_reports_the_retries_it_already_spent():
    limiter = _RecordingLimiter(max_retries=2)
    page = _FakePage(responses=[_throttled()] * 3)
    client, _ = _client(page, limiter=limiter)

    with pytest.raises(ClientError) as exc:
        client._fetch("https://www.vinted.com/items/1-item", accept="text/html")

    message = str(exc.value)
    assert "HTTP 429" in message
    assert "2 backoff retries" in message
    assert "smaller --limit" in message
    # Three attempts, two backoffs, and no success recorded.
    assert limiter.acquired == 3
    assert limiter.throttled == [(0, None), (1, None)]
    assert limiter.answered == 0


def test_a_plain_error_status_is_not_retried():
    page = _FakePage(responses=[{
        "status": 404,
        "contentType": "application/json",
        "retryAfter": None,
        "url": "https://www.vinted.com/api/v2/catalog/items",
        "text": "{}",
    }])
    limiter = _RecordingLimiter()
    client, _ = _client(page, limiter=limiter)

    with pytest.raises(ClientError, match="HTTP 404"):
        client._json("https://www.vinted.com/api/v2/catalog/items")

    assert limiter.acquired == 1
    assert limiter.throttled == []

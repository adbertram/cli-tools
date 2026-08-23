"""Regression tests for the eBay browser-session authentication check.

Root cause covered here: eBay's ``BrowserAutomation`` subclass previously used
``AUTH_COOKIE_PATTERNS = [r"nonsession", r"ebay", r"dp1", r"s"]``. eBay sets
dozens of anonymous/guest cookies on every visitor (dp1, nonsession, ebay, s,
svid, ...), so those broad patterns matched a fully logged-out session and
``_check_auth`` returned True. That made ``ebay auth status`` falsely report the
browser session as authenticated, while ``ebay listings search`` — which relies
on the same live ``is_authenticated()`` check — failed with "No browser session
found" whenever the same navigation happened to hit eBay's captcha wall. The two
commands disagreed on ground truth.

The fix removes the cookie-presence heuristic and uses eBay's real behavior:
the My eBay summary page (``AUTH_CHECK_URL``) requires login, so the request URL
staying on ``AUTH_SUCCESS_URL`` proves a live authenticated session, and a
redirect to signin/captcha proves it is not.
"""

from unittest.mock import MagicMock

from ebay_cli.browser import EbayBrowser


class FakePage:
    """Minimal stand-in for the BrowserHarnessService page used by _check_auth.

    Has no ``evaluate`` method, so the eBay content-signal check falls back to
    the summary-URL match (the historical behavior).
    """

    def __init__(self, url, cookies=None):
        self.url = url
        self._cookies = cookies or []

    def cookie_list(self):
        return self._cookies


class EvalFakePage(FakePage):
    """FakePage that can be inspected: ``evaluate`` returns a canned
    AUTH_FAILURE_PAGE_JS verdict so the eBay content check runs."""

    def __init__(self, url, failure_banner, cookies=None):
        super().__init__(url, cookies=cookies)
        self._failure_banner = failure_banner

    def evaluate(self, _script):
        return self._failure_banner


def _browser():
    return EbayBrowser(MagicMock())


# Real anonymous cookies observed on https://www.ebay.com/ while logged OUT.
ANONYMOUS_EBAY_COOKIES = [
    {"name": name, "expires": -1}
    for name in [
        "dp1", "nonsession", "ebay", "s", "svid", "ds2", "ns1", "cid",
        "__cf_bm", "bm_s", "khaos", "rts",
    ]
]


def test_ebay_does_not_use_broad_cookie_patterns():
    """The broken guest-cookie heuristic must stay removed.

    A truthy AUTH_COOKIE_PATTERNS re-introduces the false positive because
    _check_auth short-circuits on cookie presence before any URL check.
    """
    assert not EbayBrowser.AUTH_COOKIE_PATTERNS


def test_positive_auth_signal_is_the_summary_page():
    assert EbayBrowser.AUTH_SUCCESS_URL
    assert EbayBrowser.AUTH_CHECK_URL.endswith(EbayBrowser.AUTH_SUCCESS_URL.lstrip("^"))


def test_logged_out_home_page_is_not_authenticated():
    """Anonymous cookies must NOT be treated as an authenticated session."""
    page = FakePage("https://www.ebay.com/", cookies=ANONYMOUS_EBAY_COOKIES)
    assert _browser()._check_auth(page) is False


def test_signin_redirect_is_not_authenticated():
    page = FakePage(
        "https://signin.ebay.com/ws/eBayISAPI.dll?SignIn&ru=https://www.ebay.com/mye/myebay/summary",
        cookies=ANONYMOUS_EBAY_COOKIES,
    )
    assert _browser()._check_auth(page) is False


def test_captcha_wall_is_not_authenticated():
    page = FakePage(
        "https://www.ebay.com/splashui/captcha?ap=1&appName=orch&ru=https://signin.ebay.com/",
        cookies=ANONYMOUS_EBAY_COOKIES,
    )
    assert _browser()._check_auth(page) is False


def test_summary_page_is_authenticated():
    """A live session that lands on the My eBay summary page is authenticated."""
    page = FakePage(
        "https://www.ebay.com/mye/myebay/summary",
        cookies=ANONYMOUS_EBAY_COOKIES,
    )
    assert _browser()._check_auth(page) is True


def test_summary_url_with_rendered_page_is_authenticated():
    """When the summary page can be inspected and shows no failure banner,
    the session is authenticated."""
    page = EvalFakePage(
        "https://www.ebay.com/mye/myebay/summary",
        failure_banner=False,
        cookies=ANONYMOUS_EBAY_COOKIES,
    )
    assert _browser()._check_auth(page) is True


def test_summary_url_error_interstitial_is_not_authenticated():
    """Truthfulness fix: a URL-preserving error/interstitial served at the
    summary URL must NOT report healthy -- the browser could not actually
    fetch a usable page."""
    page = EvalFakePage(
        "https://www.ebay.com/mye/myebay/summary",
        failure_banner=True,
        cookies=ANONYMOUS_EBAY_COOKIES,
    )
    assert _browser()._check_auth(page) is False

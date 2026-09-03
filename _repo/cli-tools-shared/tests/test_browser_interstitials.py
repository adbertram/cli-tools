"""Declarative interstitial-wall handling on BrowserAutomation.

Sites front real content with walls that all look like "the element never
appeared" to a downstream selector wait, but need opposite handling. The
motivating live case (eBay, 2026-08-28) had three at one URL: a self-clearing
``/splashui/challenge``, a sticky "Error Page" rate wall, and a real captcha.
A per-tool title blocklist handled exactly one of them and returned the other
two to callers as healthy pages.

These tests pin the generic engine: rule ordering, per-strategy behavior,
bounded attempts, real jittered backoff, and the opt-out for tools that
declare no rules.
"""

import pytest

from cli_tools_shared.auth import (
    INTERSTITIAL_ABORT,
    INTERSTITIAL_RELOAD,
    INTERSTITIAL_SETTLE,
    BrowserAutomation,
    BrowserAutomationError,
    Interstitial,
    classify_interstitial,
)


PAGE_URL = "https://example.com/results?q=widget"

ABORT_RULE = Interstitial(
    kind="captcha",
    label="CAPTCHA/human-verification",
    strategy=INTERSTITIAL_ABORT,
    url_markers=("/captcha",),
    body_markers=("verify you are human",),
)
SETTLE_RULE = Interstitial(
    kind="challenge",
    label="browser-check",
    strategy=INTERSTITIAL_SETTLE,
    url_markers=("/challenge",),
    title_markers=("just a moment",),
)
RELOAD_RULE = Interstitial(
    kind="error",
    label="error",
    strategy=INTERSTITIAL_RELOAD,
    title_markers=("error page",),
)
RULES = (ABORT_RULE, SETTLE_RULE, RELOAD_RULE)


OK = (PAGE_URL, "Widgets for sale")
ERR = (PAGE_URL, "Error Page")
CHAL = ("https://example.com/challenge?ru=x", "Just a moment...")
CAP = ("https://example.com/captcha?ap=1", "Security Measure")


class FakePage:
    """Advances to the next scripted ``(url, title)`` on goto/wait."""

    def __init__(self, states, goto_state=None):
        self._states = list(states)
        self._index = 0
        self._goto_state = goto_state
        self.goto_calls = []
        self.waits = []

    @property
    def _current(self):
        return self._states[self._index]

    def _advance(self):
        if self._index < len(self._states) - 1:
            self._index += 1

    @property
    def url(self):
        return self._current[0]

    def evaluate(self, script):
        if script == "document.title":
            return self._current[1]
        return ""

    def goto(self, url, wait_until=None):
        self.goto_calls.append(url)
        if self._goto_state is not None:
            self._states = [self._goto_state]
            self._index = 0
            return
        self._advance()

    def wait_for_timeout(self, ms):
        self.waits.append(ms)
        self._advance()


class WalledBrowser(BrowserAutomation):
    SESSION_NAME = "test-walled"
    INTERSTITIALS = RULES
    INTERSTITIAL_SETTLE_TIMEOUT_MS = 3000
    INTERSTITIAL_POLL_INTERVAL_MS = 1000


class OpenBrowser(BrowserAutomation):
    """A tool that declares no walls -- navigation must be untouched."""

    SESSION_NAME = "test-open"


def _browser(cls=WalledBrowser):
    from unittest.mock import MagicMock

    return cls(MagicMock())


def _page(*states, goto_state=None):
    return FakePage(list(states), goto_state=goto_state)


@pytest.fixture
def stub_navigate(monkeypatch):
    def install(page):
        monkeypatch.setattr(
            BrowserAutomation, "_navigate_page", lambda self, url=None: page
        )
        return page

    return install


@pytest.fixture
def no_jitter(monkeypatch):
    monkeypatch.setattr("cli_tools_shared.auth.random.random", lambda: 0.0)


# ---- classification ----

def test_first_matching_rule_wins_in_declaration_order():
    """Declared most-severe first, so a captcha is never downgraded."""
    rule = classify_interstitial(
        RULES, url="https://example.com/challenge", title="Verify you are human"
    )
    assert rule is ABORT_RULE


def test_real_content_classifies_as_none():
    assert classify_interstitial(RULES, url=PAGE_URL, title="Widgets") is None


def test_markers_match_url_title_and_body_independently():
    assert classify_interstitial(RULES, url="https://x/captcha") is ABORT_RULE
    assert classify_interstitial(RULES, title="Error Page") is RELOAD_RULE
    assert classify_interstitial(RULES, body="verify you are human") is ABORT_RULE


def test_title_markers_do_not_match_body_text():
    """A title-only rule must not fire on prose inside real page content."""
    assert (
        classify_interstitial(RULES, url=PAGE_URL, title="Widgets", body="error page")
        is None
    )


# ---- opt-out ----

def test_tool_without_rules_returns_page_untouched(stub_navigate):
    page = stub_navigate(_page(ERR))
    assert _browser(OpenBrowser).get_page(PAGE_URL) is page
    assert page.goto_calls == []
    assert page.waits == []


# ---- reload strategy ----

def test_reload_wall_is_retried_until_it_clears(stub_navigate, no_jitter):
    page = stub_navigate(_page(ERR, ERR, ERR, ERR, OK))
    assert _browser().get_page(PAGE_URL) is page
    assert page.goto_calls == [PAGE_URL, PAGE_URL]


def test_reload_wall_exhausts_all_attempts_then_raises(stub_navigate, no_jitter):
    page = stub_navigate(_page(ERR))
    with pytest.raises(BrowserAutomationError) as excinfo:
        _browser().get_page(PAGE_URL)

    message = str(excinfo.value)
    assert "did not clear after 4 navigation attempts" in message
    assert PAGE_URL in message
    # 4 navigation attempts == the initial load plus 3 reloads.
    assert page.goto_calls == [PAGE_URL] * 3


def test_backoff_grows_between_attempts(stub_navigate, no_jitter):
    page = stub_navigate(_page(ERR))
    with pytest.raises(BrowserAutomationError):
        _browser().get_page(PAGE_URL)
    assert page.waits == [4000, 8000, 16000]


def test_backoff_is_jittered_within_bounds():
    browser = _browser()
    delays = {browser._interstitial_delay_ms(1) for _ in range(200)}
    assert len(delays) > 1, "delay must be jittered, not constant"
    low = WalledBrowser.INTERSTITIAL_BASE_DELAY_MS
    high = int(low * (1 + WalledBrowser.INTERSTITIAL_JITTER_RATIO))
    assert all(low <= d <= high for d in delays)


def test_backoff_is_capped():
    browser = _browser()
    capped = browser._interstitial_delay_ms(20)
    ceiling = int(
        WalledBrowser.INTERSTITIAL_MAX_DELAY_MS
        * (1 + WalledBrowser.INTERSTITIAL_JITTER_RATIO)
    )
    assert WalledBrowser.INTERSTITIAL_MAX_DELAY_MS <= capped <= ceiling


# ---- settle strategy ----

def test_settle_wall_is_waited_out_without_re_navigating(stub_navigate):
    """A self-redirecting wall must not be interrupted by a fresh goto."""
    page = stub_navigate(_page(CHAL, OK))
    assert _browser().get_page(PAGE_URL) is page
    assert page.goto_calls == []
    assert page.waits == [1000]


def test_settle_wall_that_never_clears_is_then_reloaded_and_raises(
    stub_navigate, no_jitter
):
    page = stub_navigate(_page(CHAL))
    with pytest.raises(BrowserAutomationError) as excinfo:
        _browser().get_page(PAGE_URL)
    assert "browser-check" in str(excinfo.value)
    assert page.goto_calls == [PAGE_URL] * 3


# ---- abort strategy ----

def test_abort_wall_raises_immediately_and_is_never_retried(stub_navigate):
    page = stub_navigate(_page(CAP))
    with pytest.raises(BrowserAutomationError) as excinfo:
        _browser().get_page(PAGE_URL)
    message = str(excinfo.value)
    assert "CAPTCHA/human-verification" in message
    assert "cannot be resolved automatically" in message
    assert page.goto_calls == [], "an abort wall must never be reloaded around"


def test_abort_wall_reached_mid_retry_stops_the_loop(stub_navigate, no_jitter):
    """Landing on a captcha while retrying an error wall must stop, not loop."""
    page = stub_navigate(_page(ERR, goto_state=CAP))
    with pytest.raises(BrowserAutomationError):
        _browser().get_page(PAGE_URL)
    assert len(page.goto_calls) == 1


def test_abort_message_redacts_url_query():
    """The wall URL is logged through the shared redaction helper."""
    page = _page(("https://example.com/captcha?token=secret123", "Security"))
    with pytest.raises(BrowserAutomationError) as excinfo:
        _browser()._settle_interstitial(page)
    assert "secret123" not in str(excinfo.value)


# ---- probe robustness ----

def test_failed_title_probe_is_not_treated_as_a_wall(stub_navigate):
    class BrokenPage(FakePage):
        def evaluate(self, script):
            raise RuntimeError("evaluate failed mid-navigation")

    page = stub_navigate(BrokenPage([OK]))
    assert _browser().get_page(PAGE_URL) is page


def test_body_is_only_probed_when_a_rule_declares_body_markers():
    """Reading innerText on every navigation is not free -- skip it if unused."""

    class TitleOnlyBrowser(BrowserAutomation):
        SESSION_NAME = "test-title-only"
        INTERSTITIALS = (RELOAD_RULE,)

    scripts = []

    class RecordingPage(FakePage):
        def evaluate(self, script):
            scripts.append(script)
            return super().evaluate(script)

    _browser(TitleOnlyBrowser)._classify_page_interstitial(RecordingPage([OK]))
    assert scripts == ["document.title"]

    scripts.clear()
    _browser()._classify_page_interstitial(RecordingPage([OK]))
    assert any("innerText" in s for s in scripts)

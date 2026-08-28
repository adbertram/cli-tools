"""Regression tests for eBay's interstitial handling.

Root cause covered here (diagnosed live 2026-08-28 against
``/sch/i.html?_nkw=LEGO+7097&LH_Complete=1&LH_Sold=1`` with an *authenticated*
session, so this was never a stale-session problem):

``EbayBrowser.get_page``'s retry loop was gated on a one-string title
blocklist -- ``ERROR_PAGE_TITLE_MARKERS = ("Error Page",)``. eBay fronts the
same URL with a *second*, differently-titled wall: ``/splashui/challenge``,
titled "Pardon Our Interruption...". Because that title is not "Error Page",
``_detect_error_page`` returned False and ``get_page`` handed the caller the
interstitial as a healthy page. An instrumented run of the real loop caught
exactly that: one ``detect`` probe, ``detected: false``, and ``get_page``
returning a page still parked on ``/splashui/challenge``.

That is why the reported failure printed "attempt 1/4" and then died
immediately: the first load was an "Error Page", the single reload landed on
the differently-titled challenge page, the loop exited believing it had
recovered, and the caller's ``wait_for_selector`` timed out and reported the
misleading "results container was not found" (by which point the page had
settled back to the Error Page, which is why that message quoted the Error
Page title).

Two further behaviors were measured live and are locked in here:

* The "Error Page" is eBay's request-rate wall. It stayed put for 8s+ of
  polling and survived re-navigation at ~9.5s spacing, so the old jitter-free
  2/4/6/8s ramp could not clear it. Backoff is now exponential from 4s with
  jitter.
* ``/splashui/challenge`` is SELF-CLEARING ("Your browser will redirect to
  your requested content shortly") -- observed resolving to real results on
  the next sample. It is waited out in place, not re-navigated.
"""

import pytest

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError

from ebay_cli.browser import (
    INTERSTITIAL_CAPTCHA,
    INTERSTITIAL_CHALLENGE,
    INTERSTITIAL_ERROR,
    EbayBrowser,
    classify_interstitial,
)


def _kind(url="", title="", body=""):
    """Classify a page and return the rule's kind (None when real content)."""
    rule = classify_interstitial(url=url, title=title, body=body)
    return rule.kind if rule is not None else None


SEARCH_URL = (
    "https://www.ebay.com/sch/i.html?_nkw=LEGO+7094&LH_Complete=1&LH_Sold=1"
)
# Titles/URLs below are verbatim from the live captures described above.
ERROR_TITLE = "\U0001f434 Error Page | eBay"
CHALLENGE_TITLE = "\U0001f434 Pardon Our Interruption..."
RESULTS_TITLE = "\U0001f434 Lego 7094 for sale | eBay"
CHALLENGE_URL = (
    "https://www.ebay.com/splashui/challenge?ap=1&appName=orch"
    "&ru=https%3A%2F%2Fwww.ebay.com%2Fsch%2Fi.html"
)
CAPTCHA_URL = "https://www.ebay.com/splashui/captcha?ap=1&appName=orch"
ERROR_BODY = (
    "SORRY Something went wrong on our end 0.a15bca17.1787933601.6321e4b8 "
    "Please go back and try again or go to eBay Homepage."
)
CHALLENGE_BODY = (
    "Skip to main content Checking your browser before you access eBay. Your "
    "browser will redirect to your requested content shortly."
)


class FakePage:
    """Stand-in for BrowserHarnessService driven by a scripted state sequence.

    Each entry is an ``(url, title)`` pair. The page advances to the next
    entry (holding the last) on a state-CHANGING event -- ``goto`` or
    ``wait_for_timeout`` -- which mirrors reality: a page only changes when
    you navigate or when time passes and its own redirect fires. Reads
    (``url``, ``evaluate``) are pure, so a single classification always sees
    one internally consistent state no matter what order the engine probes in.
    """

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
        # The body probe the engine runs when a rule declares body markers.
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


class BrokenTitlePage(FakePage):
    def evaluate(self, script):
        raise RuntimeError("evaluate failed mid-navigation")


def _browser():
    from unittest.mock import MagicMock

    return EbayBrowser(MagicMock())


def _page(*states, goto_state=None):
    return FakePage(list(states), goto_state=goto_state)


OK = (SEARCH_URL, RESULTS_TITLE)
ERR = (SEARCH_URL, ERROR_TITLE)
CHAL = (CHALLENGE_URL, CHALLENGE_TITLE)
CAP = (CAPTCHA_URL, "\U0001f434 Security Measure")


@pytest.fixture
def stub_base_get_page(monkeypatch):
    """Replace the shared base get_page with one returning a scripted page."""

    def install(page):
        monkeypatch.setattr(
            BrowserAutomation, "_navigate_page", lambda self, url=None: page
        )
        return page

    return install


@pytest.fixture
def no_jitter(monkeypatch):
    """Make the backoff deterministic so it can be asserted exactly."""
    monkeypatch.setattr("cli_tools_shared.auth.random.random", lambda: 0.0)


@pytest.fixture
def instant_waits(monkeypatch):
    """Collapse the challenge settle poll so tests do not sleep."""
    monkeypatch.setattr(EbayBrowser, "INTERSTITIAL_SETTLE_TIMEOUT_MS", 3000)
    monkeypatch.setattr(EbayBrowser, "INTERSTITIAL_POLL_INTERVAL_MS", 1000)


# ---- classification taxonomy ----

def test_error_page_is_classified_as_error():
    assert _kind(url=SEARCH_URL, title=ERROR_TITLE, body=ERROR_BODY) == (
        INTERSTITIAL_ERROR
    )


def test_pardon_our_interruption_is_classified_as_challenge_not_captcha():
    """The regression: this wall is self-clearing, not a human challenge."""
    kind = _kind(
        url=CHALLENGE_URL, title=CHALLENGE_TITLE, body=CHALLENGE_BODY
    )
    assert kind == INTERSTITIAL_CHALLENGE
    assert kind != INTERSTITIAL_CAPTCHA


def test_challenge_is_recognized_by_title_alone():
    """The challenge is retryable even if only the title survives the probe."""
    assert _kind(title=CHALLENGE_TITLE) == INTERSTITIAL_CHALLENGE


def test_captcha_url_is_classified_as_captcha():
    assert _kind(url=CAPTCHA_URL) == INTERSTITIAL_CAPTCHA


def test_verify_you_are_human_outranks_challenge_markers():
    """A real human wall must never be downgraded to a retryable one."""
    assert (
        _kind(
            url=CHALLENGE_URL, title="Verify you are human", body=CHALLENGE_BODY
        )
        == INTERSTITIAL_CAPTCHA
    )


def test_real_results_page_is_not_an_interstitial():
    assert _kind(url=SEARCH_URL, title=RESULTS_TITLE) is None


def test_listing_body_text_does_not_trip_detection():
    """Body prose on a real listing must not be read as an interstitial."""
    assert (
        _kind(
            url=SEARCH_URL,
            title=RESULTS_TITLE,
            body="Something went wrong with my last order, seller made it right",
        )
        is None
    )


# ---- detection on a live page ----

def _live_kind(page):
    rule = _browser()._classify_page_interstitial(page)
    return rule.kind if rule is not None else None


def test_live_page_classification_covers_both_retryable_walls():
    """The original bug: only 'Error Page' was ever detected on a live page."""
    assert _live_kind(_page(ERR)) == INTERSTITIAL_ERROR
    assert _live_kind(_page(CHAL)) == INTERSTITIAL_CHALLENGE
    assert _live_kind(_page(OK)) is None


def test_title_probe_failure_is_not_interstitial_proof():
    """A transient mid-navigation evaluate failure is not interstitial proof."""
    assert _live_kind(BrokenTitlePage([OK])) is None


# ---- retry loop ----

def test_get_page_passes_clean_page_through_without_reload(stub_base_get_page):
    page = stub_base_get_page(_page(OK))
    assert _browser().get_page(SEARCH_URL) is page
    assert page.goto_calls == []
    assert page.waits == []


def test_get_page_reloads_until_error_page_clears(stub_base_get_page, no_jitter):
    # Each attempt consumes two entries: the backoff wait, then the reload.
    page = stub_base_get_page(_page(ERR, ERR, ERR, ERR, OK))
    result = _browser().get_page(SEARCH_URL)
    assert result is page
    assert page.goto_calls == [SEARCH_URL, SEARCH_URL]


def test_get_page_exhausts_all_four_attempts_on_repeated_interstitials(
    stub_base_get_page, no_jitter
):
    """The reported bug: the loop must not bail out after one attempt."""
    page = stub_base_get_page(_page(ERR))
    with pytest.raises(BrowserAutomationError) as excinfo:
        _browser().get_page(SEARCH_URL)

    message = str(excinfo.value)
    assert "did not clear" in message
    assert f"{EbayBrowser.INTERSTITIAL_MAX_ATTEMPTS} navigation attempts" in message
    assert SEARCH_URL in message
    # 4 navigation attempts == the initial load + 3 reloads.
    assert len(page.goto_calls) == EbayBrowser.INTERSTITIAL_MAX_ATTEMPTS - 1
    assert page.goto_calls == [SEARCH_URL] * (EbayBrowser.INTERSTITIAL_MAX_ATTEMPTS - 1)


def test_backoff_is_applied_and_grows_between_attempts(
    stub_base_get_page, no_jitter
):
    """Every reload must be preceded by a real, growing wait."""
    page = stub_base_get_page(_page(ERR))
    with pytest.raises(BrowserAutomationError):
        _browser().get_page(SEARCH_URL)

    # With jitter zeroed: 4s, 8s, 16s -- one wait per reload, strictly growing.
    assert page.waits == [4000, 8000, 16000]
    assert all(b > a for a, b in zip(page.waits, page.waits[1:]))
    assert min(page.waits) >= EbayBrowser.INTERSTITIAL_BASE_DELAY_MS


def test_retry_delay_includes_jitter_within_bounds():
    """Jitter must vary the delay without dropping below the base backoff."""
    browser = _browser()
    delays = {browser._interstitial_delay_ms(1) for _ in range(200)}
    assert len(delays) > 1, "delay must be jittered, not constant"
    low = EbayBrowser.INTERSTITIAL_BASE_DELAY_MS
    high = int(low * (1 + EbayBrowser.INTERSTITIAL_JITTER_RATIO))
    assert all(low <= d <= high for d in delays)


def test_retry_delay_is_capped():
    browser = _browser()
    capped = browser._interstitial_delay_ms(20)
    ceiling = int(
        EbayBrowser.INTERSTITIAL_MAX_DELAY_MS * (1 + EbayBrowser.INTERSTITIAL_JITTER_RATIO)
    )
    assert EbayBrowser.INTERSTITIAL_MAX_DELAY_MS <= capped <= ceiling


def test_get_page_reloads_current_url_when_no_url_requested(
    stub_base_get_page, no_jitter
):
    """get_page(None) (auth-check path) still retries, using the page's URL."""
    page = stub_base_get_page(_page(ERR, ERR, OK))
    assert _browser().get_page() is page
    assert page.goto_calls == [SEARCH_URL]


# ---- self-clearing browser check ----

def test_challenge_is_waited_out_in_place_not_re_navigated(
    stub_base_get_page, instant_waits
):
    """The challenge redirects itself; re-navigating would abandon it."""
    page = stub_base_get_page(_page(CHAL, OK))
    assert _browser().get_page(SEARCH_URL) is page
    assert page.goto_calls == [], "challenge must clear without re-navigation"
    assert page.waits, "challenge must be polled while it clears"


def test_challenge_that_never_clears_is_retried_then_raises(
    stub_base_get_page, instant_waits, no_jitter
):
    page = stub_base_get_page(_page(CHAL))
    with pytest.raises(BrowserAutomationError) as excinfo:
        _browser().get_page(SEARCH_URL)
    assert "Pardon Our Interruption" in str(excinfo.value)
    assert "did not clear" in str(excinfo.value)


# ---- captcha hard stop ----

def test_captcha_raises_immediately_and_is_never_retried(stub_base_get_page):
    """A human-verification wall is a hard stop -- never solved or reloaded."""
    page = stub_base_get_page(_page(CAP))
    with pytest.raises(BrowserAutomationError) as excinfo:
        _browser().get_page(SEARCH_URL)
    message = str(excinfo.value)
    assert "CAPTCHA/human-verification" in message
    assert "cannot be resolved automatically" in message
    assert page.goto_calls == [], "captcha must never be reloaded around"


def test_reload_landing_on_captcha_raises_auth_challenge(
    stub_base_get_page, no_jitter
):
    """A reload that lands on the captcha wall stops, rather than looping."""
    page = stub_base_get_page(_page(ERR, goto_state=CAP))
    with pytest.raises(BrowserAutomationError) as excinfo:
        _browser().get_page(SEARCH_URL)
    assert "challenge" in str(excinfo.value).lower()
    assert page.goto_calls == [SEARCH_URL]

"""Every search wall must name itself, never fall through to "container missing".

The reported bug surfaced as ``eBay search results container was not found on
the page`` with ``title='🐴 Error Page | eBay'`` -- a generic message for a
specific, diagnosable condition. ``_raise_for_search_blocker`` is the last
gate before that generic message, so these tests pin each blocker to its own
actionable error and keep the generic one for genuinely unrecognized pages.

The stale/unauthenticated-session case is covered here too: it was ruled out
as the cause of the reported failure (``ebay auth status`` reported the
browser_session authenticated, and the live results page rendered "Hi Adam!"),
but an expired session must still produce a re-login instruction rather than a
container-missing report, so the ordering is locked in.
"""

import pytest

from ebay_cli.browser import BrowserError
from ebay_cli.browser_client import EbayBrowserClient


SEARCH_URL = (
    "https://www.ebay.com/sch/i.html?_nkw=LEGO+7097&LH_Complete=1&LH_Sold=1"
)


def _state(url=SEARCH_URL, title="", body="", container=True, zero=False):
    return {
        "url": url,
        "title": title,
        "body_text_snippet": body,
        "container_exists": container,
        "heading_text": None,
        "zero_results": zero,
    }


def _raise(state):
    return EbayBrowserClient._raise_for_search_blocker(state)


def test_error_page_reports_rate_wall_not_missing_container():
    """The exact reported symptom must no longer be misdiagnosed."""
    with pytest.raises(BrowserError) as excinfo:
        _raise(
            _state(
                title="\U0001f434 Error Page | eBay",
                body="SORRY Something went wrong on our end 0.a15bca17",
                container=False,
            )
        )
    message = str(excinfo.value)
    assert "Error Page" in message
    assert "rate wall" in message
    assert "results container was not found" not in message


def test_browser_check_reports_transient_wall_not_captcha():
    """'Pardon Our Interruption' is self-clearing -- do not call it a CAPTCHA."""
    with pytest.raises(BrowserError) as excinfo:
        _raise(
            _state(
                url="https://www.ebay.com/splashui/challenge?ap=1&appName=orch",
                title="\U0001f434 Pardon Our Interruption...",
                body="Checking your browser before you access eBay.",
                container=False,
            )
        )
    message = str(excinfo.value)
    assert "not a" in message and "CAPTCHA" in message
    assert "transient" in message


def test_real_captcha_still_reports_as_captcha():
    with pytest.raises(BrowserError) as excinfo:
        _raise(
            _state(
                url="https://www.ebay.com/splashui/captcha?ap=1",
                title="Security Measure",
                container=False,
            )
        )
    message = str(excinfo.value)
    assert "CAPTCHA/human-verification" in message
    assert "cannot be solved automatically" in message


def test_stale_session_signin_redirect_reports_relogin_not_missing_container():
    """An expired browser session must produce the re-login instruction."""
    with pytest.raises(BrowserError) as excinfo:
        _raise(
            _state(
                url="https://signin.ebay.com/ws/eBayISAPI.dll?SignIn",
                title="Sign in or Register | eBay",
                container=False,
            )
        )
    message = str(excinfo.value)
    assert "expired or unauthenticated" in message
    assert "ebay auth login --credential-type browser_session --force" in message
    assert "results container was not found" not in message


def test_signin_wins_over_missing_container_even_when_both_apply():
    """Ordering guard: the sign-in diagnosis must outrank the generic one."""
    with pytest.raises(BrowserError) as excinfo:
        _raise(_state(url="https://www.ebay.com/signin/", container=False))
    assert "expired or unauthenticated" in str(excinfo.value)


def test_unrecognized_page_without_container_still_reports_generic_error():
    """The generic message survives for genuinely unknown failures."""
    with pytest.raises(BrowserError) as excinfo:
        _raise(_state(title="Something Unfamiliar", container=False))
    assert "results container was not found" in str(excinfo.value)


def test_healthy_results_page_raises_nothing():
    assert _raise(_state(title="Lego 7097 for sale | eBay", container=True)) is None

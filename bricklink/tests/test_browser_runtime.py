"""Phase B3 — Bricklink _check_session_expired auto-clears + raises actionable.

Confirms the new contract from the persistent-profile refactor plan:
- When the page URL matches the expired-session pattern, ``clear_session()``
  is invoked unconditionally (try/finally) and the resulting error tells
  the user exactly which command to run to recover.
- Non-matching URLs are no-ops.
- ``clear_session()`` failures are surfaced via ``finally`` — the actionable
  error message always reaches the user, never a silent corruption.
"""

from unittest.mock import MagicMock

import pytest


class _Page:
    def __init__(self, url: str):
        self.url = url


def _make_runtime(monkeypatch):
    """Build a BricklinkRuntimeBrowser without invoking its __init__.

    The full __init__ requires a working config + persistent profile dir.
    We bypass it because these tests only exercise ``_check_session_expired``.
    """
    from bricklink_cli.browser_runtime import BricklinkRuntimeBrowser

    runtime = BricklinkRuntimeBrowser.__new__(BricklinkRuntimeBrowser)
    runtime._confirmation_handler = None
    runtime.confirmation = MagicMock()
    runtime.clear_session = MagicMock()
    return runtime


def test_check_session_expired_clears_session_and_raises_actionable_error(monkeypatch):
    runtime = _make_runtime(monkeypatch)
    page = _Page("https://identity.lego.com/en-US/login?ReturnUrl=...")

    with pytest.raises(RuntimeError) as ei:
        runtime._check_session_expired(page)

    runtime.clear_session.assert_called_once_with()
    msg = str(ei.value)
    assert "Bricklink session expired" in msg
    assert "bricklink auth login --force" in msg


def test_check_session_expired_matches_v2_login_page(monkeypatch):
    runtime = _make_runtime(monkeypatch)
    page = _Page("https://www.bricklink.com/v2/login.page")

    with pytest.raises(RuntimeError, match="bricklink auth login --force"):
        runtime._check_session_expired(page)

    runtime.clear_session.assert_called_once_with()


def test_check_session_expired_no_match_does_not_clear(monkeypatch):
    runtime = _make_runtime(monkeypatch)
    page = _Page("https://www.bricklink.com/orderList.asp")

    # No raise, no clear.
    result = runtime._check_session_expired(page)
    assert result is None
    runtime.clear_session.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bricklink.com/v3/user/confirmation_code_required.page?returnTo=/orderReceived.asp",
        "https://www.bricklink.com/v3/confirmation_code_required.page?returnTo=/orderReceived.asp",
    ],
)
def test_check_auth_rejects_confirmation_code_page(monkeypatch, url):
    runtime = _make_runtime(monkeypatch)
    page = _Page(url)

    assert runtime._check_auth(page) is False


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.bricklink.com/v3/user/confirmation_code_required.page?returnTo=/x", True),
        ("https://www.bricklink.com/v3/confirmation_code_required.page?returnTo=/x", True),
        ("https://www.bricklink.com/myMsg.asp", False),
        ("", False),
    ],
)
def test_is_confirmation_code_page_returns_boolean(monkeypatch, url, expected):
    runtime = _make_runtime(monkeypatch)

    assert runtime._is_confirmation_code_page(url) is expected
    assert runtime._is_confirmation_code_page(_Page(url)) is expected


def test_check_session_expired_confirmation_page_raises_without_clearing(monkeypatch):
    runtime = _make_runtime(monkeypatch)
    page = _Page("https://www.bricklink.com/v3/user/confirmation_code_required.page")

    with pytest.raises(Exception) as ei:
        runtime._check_session_expired(page)

    runtime.clear_session.assert_not_called()
    assert "confirmation code page has come up" in str(ei.value)


def test_check_auth_accepts_message_page(monkeypatch):
    runtime = _make_runtime(monkeypatch)
    page = _Page("https://www.bricklink.com/myMsg.asp")

    assert runtime._check_auth(page) is True


def test_check_session_expired_raises_actionable_even_if_clear_session_fails(monkeypatch):
    runtime = _make_runtime(monkeypatch)
    runtime.clear_session.side_effect = RuntimeError("disk full")
    page = _Page("https://identity.lego.com/en-US/login")

    # The actionable Bricklink message must still surface. We accept
    # either: (a) the original Bricklink message wraps the clear failure
    # (RuntimeError "Bricklink session expired..."), or (b) the clear
    # failure surfaces with the Bricklink message attached. The contract
    # is "the user sees `bricklink auth login --force` in the final
    # message".
    with pytest.raises(RuntimeError) as ei:
        runtime._check_session_expired(page)

    runtime.clear_session.assert_called_once_with()
    # The original session-expired RuntimeError must be the one that
    # reaches the user (finally raises it regardless of clear_session
    # failure). The clear failure may be chained via __context__.
    final_msg = str(ei.value)
    assert "Bricklink session expired" in final_msg
    assert "bricklink auth login --force" in final_msg


# ============================================================================
# Bug class: silent empty results when a target page is a server error.
#
# When Bricklink redirects to ``/oops.asp?err=404`` (or err=500, or any
# 4xx/5xx variant), the response is HTTP 200 with a generic error UI.
# Parsers that just count business-data elements see "0 matches" and
# return ``[]`` — masking dead endpoints as empty results.
# ``_check_server_error`` and the ``search_orders_by_item`` sentinel
# both raise loudly to kill that bug class.
# ============================================================================


def test_check_server_error_raises_on_oops_asp(monkeypatch):
    """oops.asp redirect must raise with BOTH URLs in the message."""
    runtime = _make_runtime(monkeypatch)
    page = _Page("https://www.bricklink.com/oops.asp?err=404")

    with pytest.raises(RuntimeError) as ei:
        runtime._check_server_error(
            page, "https://www.bricklink.com/orderSearch.asp?a=p&itemNo=2420"
        )

    msg = str(ei.value)
    assert "oops.asp" in msg
    assert "err=404" in msg
    # Original target URL must be named so the caller can tell what failed.
    assert "orderSearch.asp" in msg
    assert "itemNo=2420" in msg


def test_check_server_error_matches_err_4xx_and_5xx_query_strings(monkeypatch):
    """err=4xx / err=5xx in query strings must trip the check."""
    runtime = _make_runtime(monkeypatch)
    for bad in (
        "https://www.bricklink.com/somepage.asp?err=404",
        "https://www.bricklink.com/somepage.asp?err=500",
        "https://www.bricklink.com/somepage.asp?x=1&err=503",
    ):
        page = _Page(bad)
        with pytest.raises(RuntimeError, match="Bricklink server error"):
            runtime._check_server_error(page, "https://www.bricklink.com/orig")


def test_check_server_error_matches_v2_and_v3_error_page_urls(monkeypatch):
    """Bricklink also rewrites dead URLs to /v2/error_<code>.page and
    /v3/error/<code>_<name>.page. Both forms must trip the check, otherwise
    parsers see a healthy-looking HTTP 200 with no business data and silently
    return empty results (recurrence of the original /oops.asp bug)."""
    runtime = _make_runtime(monkeypatch)
    for bad in (
        "http://www.bricklink.com/v3/error/404_not_found.page",
        "https://www.bricklink.com/v3/error/404_not_found.page",
        "https://www.bricklink.com/v3/error/500_internal_server_error.page",
        "https://www.bricklink.com/v2/error_404.page",
        "https://www.bricklink.com/v2/error_500.page",
    ):
        page = _Page(bad)
        with pytest.raises(RuntimeError, match="Bricklink server error"):
            runtime._check_server_error(page, "https://www.bricklink.com/orig")


def test_check_server_error_does_not_raise_on_healthy_url(monkeypatch):
    """Normal bricklink URLs must NOT raise."""
    runtime = _make_runtime(monkeypatch)
    for healthy in (
        "https://www.bricklink.com/orderSearch.asp?a=p&itemNo=2420",
        "https://www.bricklink.com/myMsg.asp?pg=1&a=i",
        "https://www.bricklink.com/v2/clone/orders.page?o=ABC",
        # 'err=' inside a non-numeric value must not match.
        "https://www.bricklink.com/some.asp?err=ok",
    ):
        page = _Page(healthy)
        # Must return None, not raise.
        result = runtime._check_server_error(page, "https://www.bricklink.com/orig")
        assert result is None


def _make_search_runtime(monkeypatch, page):
    """Build a runtime whose ``_get_page_for`` returns ``page``."""
    runtime = _make_runtime(monkeypatch)
    runtime._get_page_for = MagicMock(return_value=page)
    return runtime


class _SearchPage:
    """Mock playwright Page for search_orders_by_item tests."""

    def __init__(self, url: str, *, has_form: bool, eval_result=None):
        self.url = url
        self._has_form = has_form
        self._eval_result = eval_result or []
        self.submissions = []

    def query_selector(self, selector):
        # Sentinel target — present only when has_form=True.
        if selector == 'input[name="itemNo"]' and self._has_form:
            return object()
        return None

    def evaluate(self, _script, arg=None):
        if arg is not None:
            self.submissions.append(arg)
            return None
        return self._eval_result

    def wait_for_timeout(self, _ms):
        return None

    def wait_for_selector(self, *_args, **_kwargs):
        return None

    def wait_for_network_idle(self, *_args, **_kwargs):
        return None


def test_search_orders_by_item_raises_when_results_ui_missing(monkeypatch):
    """When the search form is absent, raise — DO NOT return []."""
    # Simulate a page where _get_page_for somehow returned a page that
    # passed the URL-pattern server-error check but is not actually
    # orderSearch.asp (no itemNo input). Could happen if Bricklink
    # silently changes the endpoint to one that returns a soft-404.
    bad_page = _SearchPage(
        "https://www.bricklink.com/orderSearch.asp?a=p&itemNo=2420",
        has_form=False,
    )
    runtime = _make_search_runtime(monkeypatch, bad_page)

    with pytest.raises(RuntimeError) as ei:
        runtime.search_orders_by_item("2420", item_type="PART")

    msg = str(ei.value)
    assert "orderSearch.asp" in msg
    assert "input[name='itemNo']" in msg or "itemNo" in msg


def test_search_orders_by_item_returns_empty_only_when_form_present_with_zero_matches(monkeypatch):
    """Healthy page + zero order links = legitimate empty result."""
    healthy_page = _SearchPage(
        "https://www.bricklink.com/orderSearch.asp?a=p&itemNo=2420",
        has_form=True,
        eval_result=[],
    )
    runtime = _make_search_runtime(monkeypatch, healthy_page)

    result = runtime.search_orders_by_item("2420", item_type="PART")
    assert result == []
    runtime._get_page_for.assert_called_once_with(
        "https://www.bricklink.com/orderSearch.asp?a=p"
    )
    assert healthy_page.submissions[0]["itemNo"] == "2420"
    assert healthy_page.submissions[0]["itemType"] == "P"


def test_search_orders_by_item_uses_received_order_scope(monkeypatch):
    healthy_page = _SearchPage(
        "https://www.bricklink.com/orderSearch.asp?a=r",
        has_form=True,
        eval_result=[],
    )
    runtime = _make_search_runtime(monkeypatch, healthy_page)

    assert runtime.search_orders_by_item("2420", direction="in") == []
    runtime._get_page_for.assert_called_once_with(
        "https://www.bricklink.com/orderSearch.asp?a=r"
    )


def test_search_orders_by_item_rejects_unknown_order_scope(monkeypatch):
    healthy_page = _SearchPage(
        "https://www.bricklink.com/orderSearch.asp?a=p",
        has_form=True,
        eval_result=[],
    )
    runtime = _make_search_runtime(monkeypatch, healthy_page)

    with pytest.raises(ValueError, match="direction must be 'in' or 'out'"):
        runtime.search_orders_by_item("2420", direction="sideways")


def test_search_orders_by_item_returns_results_when_form_and_links_present(monkeypatch):
    """Healthy page + order links = parsed orders."""
    healthy_page = _SearchPage(
        "https://www.bricklink.com/orderSearch.asp?a=p&itemNo=2420",
        has_form=True,
        eval_result=[
            {"order_id": "12345", "date": "May 1 2026", "buyer": "alice", "url": "..."},
        ],
    )
    runtime = _make_search_runtime(monkeypatch, healthy_page)

    result = runtime.search_orders_by_item("2420", item_type="PART")
    assert result == [
        {"order_id": "12345", "date": "May 1 2026", "buyer": "alice", "url": "..."},
    ]


def test_search_orders_by_item_splits_set_sequence(monkeypatch):
    """Bricklink order search form stores set suffixes in itemSeq."""
    healthy_page = _SearchPage(
        "https://www.bricklink.com/orderSearch.asp?a=p",
        has_form=True,
        eval_result=[],
    )
    runtime = _make_search_runtime(monkeypatch, healthy_page)

    assert runtime.search_orders_by_item("30103-1", item_type="SET") == []
    assert healthy_page.submissions[0]["itemNo"] == "30103"
    assert healthy_page.submissions[0]["itemSeq"] == "1"
    assert healthy_page.submissions[0]["itemType"] == "S"

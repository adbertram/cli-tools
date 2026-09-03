"""Browser-automation contract tests for the mercor CLI.

These assert the declarative hooks in browser.py and the Gmail link regex in
magic_link.py against the REAL login flow captured live 2026-09-03 (see the
browser.py module docstring): email-only login card, Firebase action-link email
from auth@mercor.com, and the `token` session cookie.
"""

from __future__ import annotations

import re

from mercor_cli import magic_link
from mercor_cli.browser import MercorBrowser, _mercor_login_handler


def test_login_page_selectors_are_the_real_ones():
    """Email card: the handler targets Mercor's email input + Login button."""
    from mercor_cli.browser import EMAIL_INPUT_SELECTOR, LOGIN_BUTTON_TEXT

    assert EMAIL_INPUT_SELECTOR == 'input[type="email"]'
    assert LOGIN_BUTTON_TEXT == "Login"
    assert callable(_mercor_login_handler)


def test_session_hooks_match_worker_app():
    assert MercorBrowser.LOGIN_URL == "https://work.mercor.com/login"
    assert MercorBrowser.AUTH_CHECK_URL == "https://work.mercor.com/"
    assert re.search(MercorBrowser.AUTH_URL_PATTERN, "https://work.mercor.com/login")
    assert not re.search(
        MercorBrowser.AUTH_URL_PATTERN, "https://work.mercor.com/explore"
    )
    # The session JWT cookie Mercor's own backend reads.
    assert any(re.search(p, "token") for p in MercorBrowser.AUTH_COOKIE_PATTERNS)
    # Mercor has no password: the non-interactive login is the email handler.
    assert MercorBrowser.AUTH_LOGIN_HANDLER is not None


def test_sign_in_link_regex_matches_real_firebase_link():
    """The regex must match the exact Firebase action URL shape captured from
    the live 'Sign in to Mercor' email."""
    live = (
        "https://mercor-prod-firebase.firebaseapp.com/__/auth/action?"
        "mode=signIn&oobCode=AbCdEf123456&apiKey=AIzaSyEXAMPLE"
        "&continueUrl=https%3A%2F%2Fwork.mercor.com%2Fverify-email%3FpostAuthUrl%3D%252F"
        "&lang=en&utm_campaign=oob_link_template"
    )
    assert magic_link.VERIFY_LINK_RE.search(live)


def test_sign_in_link_regex_rejects_non_mercor_links():
    assert not magic_link.VERIFY_LINK_RE.search("https://example.com/login?token=x")
    assert not magic_link.VERIFY_LINK_RE.search(
        "https://app.outlier.ai/login/verify?token=x"
    )


def test_sender_is_mercor_auth():
    # Validated live: FROM "Mercor <auth@mercor.com>", not no-reply.
    assert magic_link.SENDER == "auth@mercor.com"
    assert "no-reply" not in magic_link.SEARCH_QUERY

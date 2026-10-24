"""Browser-automation contract tests for the mercor CLI.

These assert the declarative hooks in browser.py and the Gmail link regex in
magic_link.py against the REAL login flow captured live 2026-09-03 (see the
browser.py module docstring): email-only login card, Firebase action-link email
from auth@mercor.com, and the `token` session cookie.
"""

from __future__ import annotations

import re

from mercor_cli import magic_link
from mercor_cli.browser import (
    LOGIN_CARD_MARKERS,
    MercorBrowser,
    _bot_wall_error,
    _generic_timeout_error,
    _is_headless,
    _mercor_login_handler,
    _still_on_login_card,
)


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


# ---------------------------------------------------------------------------
# Bot-wall classification: when a headless submit times out with the login card
# still on screen, the CLI must raise the actionable CDP-bootstrap error rather
# than the old generic "did not confirm it sent a sign-in link" message.
# ---------------------------------------------------------------------------

REAL_LOGIN_CARD_BODY = (
    "Continue to Mercor\nEmail address\nLogin\nSign up\nOr continue with\n"
    "Google\nOkta\n\nBy signing in, you agree to our Worker Terms of Service."
)


def test_login_card_markers_match_the_real_card():
    assert all(marker in REAL_LOGIN_CARD_BODY for marker in LOGIN_CARD_MARKERS)
    assert "Check your inbox" not in REAL_LOGIN_CARD_BODY


def test_still_on_login_card_classifies_captured_bodies():
    # The real untouched card (headless bot-wall failure) is classified as the
    # card; a changed page (e.g. an inline error screen) is not.
    assert _still_on_login_card(REAL_LOGIN_CARD_BODY)
    assert not _still_on_login_card(
        "Check your inbox\n\nWe've sent you an activation link."
    )
    assert not _still_on_login_card(
        "Something went wrong on our end. Please try again."
    )
    assert not _still_on_login_card("")


def test_is_headless_defaults_true_and_reads_config():
    class HeadedStub:
        @staticmethod
        def _headless_enabled():
            return False

    class MissingStub:
        pass

    assert _is_headless(HeadedStub()) is False
    assert _is_headless(MissingStub()) is True


def test_bot_wall_error_names_wall_remedy_and_evidence():
    err = _bot_wall_error(
        "adbertram@gmail.com",
        "https://work.mercor.com/login",
        REAL_LOGIN_CARD_BODY,
        "/tmp/profile-dir/chromium-profile",
    )
    message = str(err)
    assert isinstance(err, Exception)
    # Symptom and wall identification.
    assert "adbertram@gmail.com" in message
    assert "reCAPTCHA Enterprise" in message
    assert "exchangeRecaptchaEnterpriseToken" in message
    # The wall markers live in the console, so the card stays silent.
    assert "browser console" in message
    assert "single-use" not in message
    # Actionable remedy: the exact profile directory for the CDP bootstrap.
    assert "/tmp/profile-dir/chromium-profile" in message
    assert "Bot-protection bootstrap" in message
    # Evidence preserved for diagnosis.
    assert "https://work.mercor.com/login" in message
    assert "Continue to Mercor" in message


def test_generic_timeout_error_used_when_card_changed_or_headed():
    changed = str(
        _generic_timeout_error(
            "adbertram@gmail.com",
            "https://work.mercor.com/login",
            "Something went wrong on our end. Please try again.",
            headless=True,
        )
    )
    # Not the wall claim: the card changed, so the wall signature is absent.
    assert "login card never changed" not in changed
    assert "Something went wrong" in changed
    assert "ACCOUNT_EMAIL" in changed

    headed = str(
        _generic_timeout_error(
            "adbertram@gmail.com",
            "https://work.mercor.com/login",
            REAL_LOGIN_CARD_BODY,
            headless=False,
        )
    )
    assert "(headless=False)" in headed
    assert "bot wall is the likely cause" in headed
    assert "Bot-protection bootstrap" in headed

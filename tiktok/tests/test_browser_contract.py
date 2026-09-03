"""Browser-automation contract tests for the tiktok CLI.

These assert the declarative hooks and login selectors in browser.py against
the REAL TikTok login flow captured live via the harness headless Chromium (see
the browser.py module docstring): the email/password form at
/login/phone-or-email/email and the "Log in" button e2e token.
"""

from __future__ import annotations

import re

from tiktok_cli.browser import (
    EMAIL_LOGIN_URL,
    PASSWORD_SELECTOR,
    SUBMIT_SELECTOR,
    USERNAME_SELECTOR,
    VERIFY_CODE_SELECTOR,
    TiktokBrowser,
    _tiktok_login_handler,
)


def test_email_login_form_selectors_are_the_real_ones():
    """Email form: username/password inputs + the Log in button e2e token."""
    assert EMAIL_LOGIN_URL == "https://www.tiktok.com/login/phone-or-email/email"
    assert USERNAME_SELECTOR == 'input[name="username"]'
    assert PASSWORD_SELECTOR == 'input[type="password"]'
    assert SUBMIT_SELECTOR == 'button[data-e2e="login-button"]'


def test_verification_code_selector_matches_captured_placeholder():
    """The 2FA/verification step is detected via its 6-digit code input."""
    assert VERIFY_CODE_SELECTOR == 'input[placeholder="Enter 6-digit code"]'


def test_session_hooks_match_tiktok():
    assert TiktokBrowser.LOGIN_URL == "https://www.tiktok.com/login"
    assert TiktokBrowser.AUTH_CHECK_URL == "https://www.tiktok.com/"
    assert re.search(TiktokBrowser.AUTH_URL_PATTERN, "https://www.tiktok.com/login")
    assert not re.search(
        TiktokBrowser.AUTH_URL_PATTERN, "https://www.tiktok.com/foryou"
    )
    # Headless login is fully driven by AUTH_LOGIN_HANDLER.
    assert TiktokBrowser.AUTH_LOGIN_HANDLER is not None
    assert callable(_tiktok_login_handler)

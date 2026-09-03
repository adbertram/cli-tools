"""Selector regression tests against real, captured CrowdGen DOM fixtures.

`login_page.html` and `signup_page.html` were captured live from headed real
Chrome (2026-09-03) at https://app.crowdgen.com/login and /apply/signup. They
are the ground truth the declarative hooks in browser.py must keep matching.
"""

from __future__ import annotations

from pathlib import Path

from crowdgen_cli.browser import CrowdgenBrowser

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> str:
    path = FIXTURES / name
    assert path.is_file(), f"missing fixture {path}"
    return path.read_text(encoding="utf-8")


def test_login_fixture_contains_credential_form():
    html = _load("login_page.html")
    assert 'id="register_email"' in html
    assert 'id="register_password"' in html
    assert 'type="submit"' in html
    assert 'id="register"' in html


def test_signup_fixture_contains_email_field():
    html = _load("signup_page.html")
    assert 'id="email"' in html


def test_login_selectors_match_fixture():
    assert 'id="register_email"' in _load("login_page.html")
    assert 'id="register_password"' in _load("login_page.html")
    assert CrowdgenBrowser.AUTH_LOGIN_USERNAME_SELECTOR == "input#register_email"
    assert CrowdgenBrowser.AUTH_LOGIN_PASSWORD_SELECTOR == "input#register_password"
    assert CrowdgenBrowser.AUTH_LOGIN_SUBMIT_SELECTOR == 'button[type="submit"]'


def test_login_form_selector_matches_fixture():
    assert CrowdgenBrowser.AUTH_LOGIN_FORM_SELECTOR == "input#register_password"
    assert 'id="register_password"' in _load("login_page.html")


def test_logged_out_pattern_urls():
    assert CrowdgenBrowser.LOGIN_URL.startswith("https://app.crowdgen.com/")
    assert CrowdgenBrowser.AUTH_CHECK_URL.startswith("https://app.crowdgen.com/")
    assert "/login" in CrowdgenBrowser.AUTH_URL_PATTERN
    assert "/apply/signup" in CrowdgenBrowser.AUTH_URL_PATTERN


def test_secret_names_match_cli_tools_secret_schema():
    # The cli-tools secret manager schema is <tool>-<type>.
    assert CrowdgenBrowser.AUTH_LOGIN_USERNAME_SECRET == "crowdgen-username"
    assert CrowdgenBrowser.AUTH_LOGIN_PASSWORD_SECRET == "crowdgen-password"

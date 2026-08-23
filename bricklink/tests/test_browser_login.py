import json
import traceback
from types import SimpleNamespace

import pytest


class _Control:
    def __init__(self, *, visible=True, enabled=True, on_click=None):
        self.first = self
        self._visible = visible
        self._enabled = enabled
        self.clicks = 0
        self.on_click = on_click

    def count(self):
        return 1

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return self._enabled

    def click(self):
        self.clicks += 1
        if self.on_click:
            self.on_click()


class _LoginPage:
    def __init__(self):
        self.url = "https://identity.lego.com/en-US/login"
        password = _Control(visible=False)
        self.controls = {
            "#username": _Control(),
            "#password": password,
            'button[type="submit"]': _Control(
                on_click=lambda: setattr(password, "_visible", True)
            ),
            '[role="alert"]': _Control(visible=False),
        }
        self.filled = []

    def locator(self, selector):
        return self.controls[selector]

    def fill(self, selector, value):
        self.filled.append((selector, value))

    def wait_for_timeout(self, _milliseconds):
        if self.controls['button[type="submit"]'].clicks >= 2:
            self.url = "https://www.bricklink.com/myMsg.asp"


class _ConfirmationLoginPage(_LoginPage):
    def __init__(self, confirmation_code):
        super().__init__()
        self.confirmation_code = confirmation_code

    def wait_for_timeout(self, _milliseconds):
        if self.controls['button[type="submit"]'].clicks >= 2:
            self.url = (
                "https://www.bricklink.com/v3/user/"
                "confirmation_code_required.page"
            )

    def query_selector(self, selector):
        if selector == "#confirmation-code":
            return _LeakingCodeInput(self.confirmation_code)
        return None

    def fill(self, selector, value):
        if selector == "#confirmation-code":
            raise RuntimeError(f"Playwright fill failed for value {value}")
        super().fill(selector, value)


class _LegoTwoFactorLoginPage(_LoginPage):
    def __init__(self):
        super().__init__()
        self.controls['input[name="token"][autocomplete="one-time-code"]'] = _Control()

    def wait_for_timeout(self, _milliseconds):
        clicks = self.controls['button[type="submit"]'].clicks
        if clicks >= 3:
            self.url = "https://www.bricklink.com/myMsg.asp"
        elif clicks >= 2:
            self.url = "https://identity.lego.com/auth/two-factor-authentication"


class _LeakingCodeInput:
    def __init__(self, confirmation_code):
        self.confirmation_code = confirmation_code

    def fill(self, value):
        raise RuntimeError(f"Playwright fill failed for value {value}")


class _PersistenceService:
    """Model BrickLink finalizing its session on the protected-page request."""

    def __init__(self):
        self.url = ""
        self.open_count = 0
        self.persisted = False

    def browser_open(self, url, **_kwargs):
        self.open_count += 1
        if self.open_count == 1:
            self.url = "https://identity.lego.com/en-US/login"
        else:
            self.url = (
                url
                if self.persisted
                else "https://identity.lego.com/en-US/login"
            )

    def goto(self, url):
        self.url = url

    def wait_for_timeout(self, _milliseconds):
        return None

    def browser_close(self):
        if (
            self.open_count == 1
            and self.url == "https://www.bricklink.com/myMsg.asp"
        ):
            self.persisted = True


class _PersistenceConfig:
    headless = True

    def has_saved_session(self):
        return False

    def get_persistent_profile_dir(self):
        return "/tmp/bricklink-test-profile"

    def get_active_profile_name(self):
        return "default"


def test_noninteractive_login_reads_managed_lastpass_without_exposing_secrets(
    monkeypatch, capsys
):
    from bricklink_cli.browser import BricklinkBrowser

    calls = []
    secrets = {"username": "sentinel-user", "password": "sentinel-password"}

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=secrets[command[2]] + "\n")

    monkeypatch.setattr("bricklink_cli.managed_auth.subprocess.run", fake_run)
    browser = BricklinkBrowser.__new__(BricklinkBrowser)
    page = _LoginPage()

    browser._complete_noninteractive_login(page)

    assert [call[0] for call in calls] == [
        ["lastpass", "items", "username", "lego.com"],
        ["lastpass", "items", "password", "lego.com"],
    ]
    assert all(call[1] == {"check": True, "capture_output": True, "text": True} for call in calls)
    assert page.filled == [
        ("#username", "sentinel-user"),
        ("#password", "sentinel-password"),
    ]
    assert page.controls['button[type="submit"]'].clicks == 2
    captured = capsys.readouterr()
    assert "sentinel-user" not in captured.out + captured.err
    assert "sentinel-password" not in captured.out + captured.err


def test_two_factor_page_should_not_be_authenticated_when_return_url_contains_bricklink():
    from bricklink_cli.browser import BricklinkBrowser

    browser = BricklinkBrowser.__new__(BricklinkBrowser)
    page = SimpleNamespace(
        url=(
            "https://identity.lego.com/auth/two-factor-authentication"
            "?returnurl=https%3A%2F%2Fauth.preview.v2.bricklink.com%2Fauth-callback"
        )
    )

    assert browser._check_auth(page) is False


def test_noninteractive_login_should_submit_fresh_lego_two_factor_code(monkeypatch):
    from bricklink_cli.browser import BricklinkBrowser

    page = _LegoTwoFactorLoginPage()
    browser = BricklinkBrowser.__new__(BricklinkBrowser)
    calls = []
    monkeypatch.setattr(
        "bricklink_cli.browser.get_lastpass_credential",
        lambda field: f"sentinel-{field}",
    )
    monkeypatch.setattr(
        "bricklink_cli.browser.get_lego_two_factor_code",
        lambda **kwargs: calls.append(kwargs) or "sentinel-code",
        raising=False,
    )

    browser._complete_noninteractive_login(page)

    assert calls and list(calls[0]) == ["requested_after"]
    assert page.filled[-1] == (
        'input[name="token"][autocomplete="one-time-code"]',
        "sentinel-code",
    )
    assert page.url == "https://www.bricklink.com/myMsg.asp"


def test_login_should_finalize_session_on_protected_page_before_reopening(monkeypatch):
    from bricklink_cli.browser import BricklinkBrowser

    service = _PersistenceService()
    browser = BricklinkBrowser(_PersistenceConfig())
    monkeypatch.setattr(browser, "_get_service", lambda: service)
    monkeypatch.setattr(browser, "_prompt_enter_eof_safe", lambda **_kwargs: False)
    monkeypatch.setattr(
        browser,
        "_complete_noninteractive_login",
        lambda page: setattr(page, "url", "https://www.bricklink.com/v3/user/redirect.page"),
    )

    result = browser.login()

    assert result == {"success": True, "message": "Session saved. Browser closed."}
    assert service.persisted is True
    assert service.open_count == 2


def test_password_fill_failure_suppresses_secret_from_all_outputs(
    monkeypatch, capsys, caplog
):
    from bricklink_cli.browser import BricklinkBrowser

    page = _LoginPage()
    sentinel = "sentinel-password-must-never-appear"

    def fake_credential(field):
        return "sentinel-user" if field == "username" else sentinel

    original_fill = page.fill

    def unsafe_fill(selector, value):
        if selector == "#password":
            raise RuntimeError(f"Playwright fill failed for value {value}")
        original_fill(selector, value)

    page.fill = unsafe_fill
    monkeypatch.setattr("bricklink_cli.browser.get_lastpass_credential", fake_credential)
    browser = BricklinkBrowser.__new__(BricklinkBrowser)

    with pytest.raises(Exception) as caught:
        browser._complete_noninteractive_login(page)

    rendered = "".join(
        traceback.format_exception(type(caught.value), caught.value, caught.value.__traceback__)
    )
    captured = capsys.readouterr()
    assert sentinel not in rendered
    assert sentinel not in captured.out + captured.err
    assert sentinel not in caplog.text


def test_confirmation_fill_failure_suppresses_code_from_exception_traceback(
    monkeypatch, capsys, caplog
):
    from bricklink_cli.browser import BricklinkBrowser

    sentinel = "987654"
    page = _ConfirmationLoginPage(sentinel)
    browser = BricklinkBrowser.__new__(BricklinkBrowser)
    monkeypatch.setattr(
        "bricklink_cli.browser.get_lastpass_credential",
        lambda field: f"sentinel-{field}",
    )
    monkeypatch.setattr(
        "bricklink_cli.browser.get_bricklink_confirmation_code",
        lambda **_kwargs: sentinel,
    )
    monkeypatch.setattr(browser, "_check_auth", lambda _page: False)

    with pytest.raises(Exception) as caught:
        browser._complete_noninteractive_login(page)

    rendered = "".join(
        traceback.format_exception(
            type(caught.value), caught.value, caught.value.__traceback__
        )
    )
    captured = capsys.readouterr()
    assert sentinel not in rendered
    assert sentinel not in captured.out + captured.err
    assert sentinel not in caplog.text


def test_confirmation_provider_uses_newest_post_attempt_email_without_exposing_code(
    monkeypatch, capsys
):
    from bricklink_cli.managed_auth import GmailConfirmationCodeProvider

    calls = []
    responses = iter(
        [
            json.dumps(
                [
                    {
                        "id": "new-message",
                        "from": "BrickLink <blservice@bricklink.com>",
                        "subject": "Your BrickLink confirmation code",
                        "date": "Sun, 19 Jul 2026 18:37:42 -0400 (EDT)",
                    }
                ]
            ),
            json.dumps(
                {
                    "id": "new-message",
                    "body": "Your BrickLink confirmation code is 654321. It expires soon.",
                }
            ),
        ]
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=next(responses))

    monkeypatch.setattr("bricklink_cli.managed_auth.subprocess.run", fake_run)
    provider = GmailConfirmationCodeProvider(profile="adbertram", timeout_seconds=1)

    assert provider.get_code(requested_after=1_774_000_000) == "654321"
    assert calls[0][0] == [
        "google",
        "gmail",
        "search",
        'from:blservice@bricklink.com subject:"Your BrickLink confirmation code" after:1774000000',
        "--limit",
        "1",
        "--properties",
        "id,from,subject,date",
        "--profile",
        "adbertram",
    ]
    assert calls[1][0] == [
        "google",
        "gmail",
        "get",
        "new-message",
        "--include-body",
        "--profile",
        "adbertram",
    ]
    captured = capsys.readouterr()
    assert "654321" not in captured.out + captured.err


def test_lego_two_factor_provider_uses_fresh_subject_code_without_exposing_it(
    monkeypatch, capsys
):
    from bricklink_cli.managed_auth import get_lego_two_factor_code

    calls = []
    sentinel = "654321"

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            stdout=json.dumps(
                [
                    {
                        "id": "new-message",
                        "from": "LEGO Account <account@mail.identity.lego.com>",
                        "subject": f"Your LEGO code: {sentinel}",
                        "date": "Mon, 20 Jul 2026 15:30:25 +0000",
                    }
                ]
            )
        )

    monkeypatch.setattr("bricklink_cli.managed_auth.subprocess.run", fake_run)

    assert get_lego_two_factor_code(requested_after=1_774_000_000) == sentinel
    assert calls[0][0] == [
        "google",
        "gmail",
        "search",
        'from:account@mail.identity.lego.com subject:"Your LEGO" after:1774000000',
        "--limit",
        "1",
        "--properties",
        "id,from,subject,date",
        "--profile",
        "adbertram",
    ]
    captured = capsys.readouterr()
    assert sentinel not in captured.out + captured.err


class _SelectAccountPage:
    """Mock the LEGO identity select-account interstitial.

    Starts on ``identity.lego.com/select-account`` (no username/password form)
    and, once a continue control is clicked, redirects to the authenticated
    BrickLink page on the next ``wait_for_timeout``.
    """

    def __init__(self, *, click_returns=True):
        self.url = (
            "https://identity.lego.com/select-account"
            "?clientname=BrickLink&returnUrl=%2Fconnect%2Fauthorize%2Fcallback"
        )
        self.click_returns = click_returns
        self.evaluate_scripts = []

    def evaluate(self, script):
        self.evaluate_scripts.append(script)
        return self.click_returns

    def wait_for_timeout(self, _milliseconds):
        if self.evaluate_scripts:
            self.url = "https://www.bricklink.com/myMsg.asp"


def test_select_account_page_is_not_authenticated():
    from bricklink_cli.browser import BricklinkBrowser

    browser = BricklinkBrowser.__new__(BricklinkBrowser)
    page = SimpleNamespace(
        url=(
            "https://identity.lego.com/select-account"
            "?clientname=BrickLink&returnUrl=%2Fconnect%2Fauthorize%2Fcallback"
            "%3Fclient_id%3Dbricklink%26prompt%3Dselect_account"
        )
    )

    assert browser._check_auth(page) is False


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://identity.lego.com/select-account?clientname=BrickLink", True),
        ("https://identity.lego.com/en-US/select-account?clientname=BrickLink", True),
        ("https://identity.lego.com/en-US/login", False),
        ("https://identity.lego.com/auth/two-factor-authentication", False),
        ("https://www.bricklink.com/myMsg.asp", False),
        ("", False),
    ],
)
def test_is_select_account_page_classification(url, expected):
    from bricklink_cli.browser import BricklinkBrowser

    assert BricklinkBrowser._is_select_account_page(url) is expected


def test_noninteractive_login_clicks_select_account_control(monkeypatch):
    from bricklink_cli.browser import SELECT_ACCOUNT_CLICK_JS, BricklinkBrowser

    page = _SelectAccountPage()
    browser = BricklinkBrowser.__new__(BricklinkBrowser)

    def fail_credential(_field):
        raise AssertionError("no credential may be fetched on select-account")

    monkeypatch.setattr("bricklink_cli.browser.get_lastpass_credential", fail_credential)

    browser._complete_noninteractive_login(page)

    assert page.url == "https://www.bricklink.com/myMsg.asp"
    assert page.evaluate_scripts == [SELECT_ACCOUNT_CLICK_JS]


def test_noninteractive_login_raises_when_select_account_control_missing(monkeypatch):
    from bricklink_cli.browser import BricklinkBrowser

    page = _SelectAccountPage(click_returns=False)
    browser = BricklinkBrowser.__new__(BricklinkBrowser)
    monkeypatch.setattr("bricklink_cli.browser.get_lastpass_credential", lambda _f: None)

    with pytest.raises(Exception, match="select-account"):
        browser._complete_noninteractive_login(page)

from pathlib import Path

import pytest

from cli_tools_shared.auth import AuthResult, BrowserAutomationError

from facebook_cli.browser import FacebookBrowser


class _Config:
    def __init__(
        self,
        tmp_path: Path,
        *,
        username: str | None,
        password: str | None,
        has_saved_session: bool = False,
    ):
        self._browser_data_dir = tmp_path / "browser-data"
        self._persistent_profile_dir = self._browser_data_dir / "chromium-profile"
        self._persistent_profile_dir.mkdir(parents=True, exist_ok=True)
        self._tool_name = "facebook"
        self._username = username
        self._password = password
        self._has_saved_session = has_saved_session

    def get_browser_data_dir(self) -> Path:
        return self._browser_data_dir

    def get_persistent_profile_dir(self) -> Path:
        return self._persistent_profile_dir

    def has_saved_session(self) -> bool:
        return self._has_saved_session

    @property
    def username(self) -> str | None:
        return self._username

    @property
    def password(self) -> str | None:
        return self._password


class _FakeService:
    def __init__(self):
        self.browser_open_calls = []
        self.wait_for_selector_calls = []
        self.wait_for_timeout_calls = []
        self.evaluate_calls = []
        self.browser_close_calls = 0
        self.data_delete_calls = 0
        self.url = "https://www.facebook.com/login"
        self._cookie_sequences = []
        self._blocker_response = {"captcha": False, "checkpoint": False, "twoStep": False}

    def browser_open(self, *args, **kwargs):
        self.browser_open_calls.append((args, kwargs))

    def wait_for_selector(self, selector, timeout=None):
        self.wait_for_selector_calls.append((selector, timeout))

    def evaluate(self, script, arg=None):
        self.evaluate_calls.append((script, arg))
        if "Facebook login form is missing the form, email field, or password field." in script:
            return {"success": True}
        if "captcha:" in script and "twoStep:" in script:
            return dict(self._blocker_response)
        raise AssertionError(f"Unexpected evaluate call: {script[:120]}")

    def cookie_list(self):
        if self._cookie_sequences:
            return self._cookie_sequences.pop(0)
        return []

    def wait_for_timeout(self, timeout):
        self.wait_for_timeout_calls.append(timeout)

    def browser_close(self):
        self.browser_close_calls += 1

    def data_delete(self):
        self.data_delete_calls += 1
        return {"success": True}


def test_authenticate_requires_profile_username_and_password(tmp_path, monkeypatch):
    browser = FacebookBrowser(_Config(tmp_path, username=None, password="secret"))
    service = _FakeService()
    monkeypatch.setattr(browser, "_get_service", lambda: service)

    with pytest.raises(
        BrowserAutomationError,
        match="USERNAME and PASSWORD",
    ):
        browser.authenticate(force=True)


def test_authenticate_submits_profile_credentials_and_verifies_persistence(tmp_path, monkeypatch):
    browser = FacebookBrowser(_Config(tmp_path, username="user@example.com", password="secret"))
    service = _FakeService()
    service._cookie_sequences = [
        [],
        [{"name": "c_user", "value": "1", "expires": -1}],
    ]
    service.url = "https://www.facebook.com/"

    monkeypatch.setattr(browser, "_get_service", lambda: service)
    monkeypatch.setattr(browser, "is_authenticated", lambda: AuthResult(True, live_check=True))

    browser.authenticate(force=True)

    assert service.data_delete_calls == 1
    assert service.browser_open_calls == [
        (
            ("https://www.facebook.com/login",),
            {
                "headed": True,
                "persistent_profile_dir": browser._get_persistent_profile_dir(),
            },
        )
    ]
    assert service.wait_for_selector_calls == [
        ('form#login_form', 15000),
        ('input[name="email"]', 15000),
        ('input[name="pass"]', 15000),
    ]
    submit_call = service.evaluate_calls[0]
    assert "form#login_form" in submit_call[0]
    assert "requestSubmit()" in submit_call[0]
    assert 'button[name="login"]' not in submit_call[0]
    assert submit_call[1] == {
        "username": "user@example.com",
        "password": "secret",
    }
    assert service.browser_close_calls == 2


def test_authenticate_fails_on_checkpoint_url(tmp_path, monkeypatch):
    browser = FacebookBrowser(_Config(tmp_path, username="user@example.com", password="secret"))
    service = _FakeService()
    service.url = "https://www.facebook.com/checkpoint/123"

    monkeypatch.setattr(browser, "_get_service", lambda: service)

    with pytest.raises(
        BrowserAutomationError,
        match=r"blocked by checkpoint at https://www.facebook.com/checkpoint/123",
    ):
        browser.authenticate(force=True)


def test_authenticate_fails_on_captcha_probe(tmp_path, monkeypatch):
    browser = FacebookBrowser(_Config(tmp_path, username="user@example.com", password="secret"))
    service = _FakeService()
    service._blocker_response = {"captcha": True, "checkpoint": False, "twoStep": False}
    service.url = "https://www.facebook.com/login/device-based/regular/login/"

    monkeypatch.setattr(browser, "_get_service", lambda: service)

    with pytest.raises(
        BrowserAutomationError,
        match=r"blocked by captcha at https://www.facebook.com/login/device-based/regular/login/",
    ):
        browser.authenticate(force=True)

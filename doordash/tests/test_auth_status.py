"""DoorDash auth-status regressions."""

from cli_tools_shared.auth_verifier import AuthVerifier
from cli_tools_shared.credentials import CredentialType

from doordash_cli.browser import DoorDashBrowser


class _FakePage:
    def __init__(self, *, url: str, consumer_id: str):
        self.url = url
        self._consumer_id = consumer_id
        self.wait_for_timeout_calls: list[int] = []

    def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)

    def localstorage_list(self) -> list[dict]:
        if not self._consumer_id:
            return []
        return [{"key": "consumerId", "value": self._consumer_id}]


class _FakeConfig:
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]

    def __init__(self, tmp_path, page: _FakePage, *, has_saved_session: bool = True):
        self._page = page
        self._has_saved_session = has_saved_session
        self.browser_data_dir = tmp_path
        self._tool_name = "doordash"

    def get_browser(self):
        browser = DoorDashBrowser(self)
        browser.get_page = lambda _url=None: self._page
        browser.close = lambda: None
        return browser

    def has_saved_session(self) -> bool:
        return self._has_saved_session

    def get_browser_data_dir(self):
        return self.browser_data_dir

    def get_persistent_profile_dir(self):
        return self.browser_data_dir / "chromium-profile"


def test_auth_status_marks_guest_orders_page_unauthenticated(tmp_path):
    page = _FakePage(
        url="https://www.doordash.com/consumer/orders",
        consumer_id="",
    )
    result = AuthVerifier(_FakeConfig(tmp_path, page)).verify()

    block = result["credential_types"]["browser_session"]
    assert page.wait_for_timeout_calls == [2000]
    assert block["credentials_saved"] is True
    assert block["browser_session"] is False
    assert block["browser_available"] is True
    assert block["authenticated"] is False
    assert result["authenticated"] is False


def test_auth_status_marks_consumer_orders_page_authenticated(tmp_path):
    page = _FakePage(
        url="https://www.doordash.com/consumer/orders",
        consumer_id="consumer_123",
    )
    result = AuthVerifier(_FakeConfig(tmp_path, page)).verify()

    block = result["credential_types"]["browser_session"]
    assert page.wait_for_timeout_calls == [2000]
    assert block["credentials_saved"] is True
    assert block["browser_session"] is True
    assert block["browser_available"] is True
    assert block["authenticated"] is True
    assert result["authenticated"] is True

from unittest.mock import MagicMock

from cli_tools_shared.testing.auth_matrix import seed_auth_profile
from typer.testing import CliRunner


class _ConfirmationPage:
    def __init__(self):
        self.url = None
        self.confirmation_submitted = False
        self.entered_code = None
        self.goto_calls = []

    def goto(self, url, wait_until=None):
        self.goto_calls.append(url)
        if not self.confirmation_submitted:
            self.url = "https://www.bricklink.com/v3/user/confirmation_code_required.page"
            return
        self.url = url

    def wait_for_selector(self, selector, state=None, timeout=None):
        if selector == 'a[href*="myMsg.asp?msgID="]':
            raise RuntimeError("no messages")
        return object()

    def wait_for_timeout(self, timeout):
        return None

    def evaluate(self, script, *args):
        if "document.title" in script:
            return "Confirmation code required [BrickLink]" if "confirmation_code_required" in self.url else "BrickLink"
        if "button.click()" in script:
            self.confirmation_submitted = True
            return True
        return []

    def query_selector(self, selector):
        if selector == "#confirmation-code":
            return _CodeInput(self)
        return None


class _CodeInput:
    def __init__(self, page):
        self.page = page

    def fill(self, value):
        self.page.entered_code = value


def _fake_runtime_init(self, config=None):
    self.config = MagicMock()
    self.confirmation = MagicMock()
    self.confirmation.is_pending.return_value = False
    self.clear_session = MagicMock()
    self._confirmation_handler = None


def test_messages_list_uses_managed_confirmation_code_and_retries(tmp_path, monkeypatch):
    data_home = tmp_path / "data-home"
    profiles_dir = data_home / "cli-tools" / "bricklink" / "authentication_profiles"
    seed_auth_profile(
        profiles_dir,
        "default",
        active=True,
        browser_session=True,
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    from bricklink_cli.main import app
    from bricklink_cli.browser_runtime import BricklinkRuntimeBrowser

    page = _ConfirmationPage()
    requested_after_values = []

    def fake_confirmation_code(*, requested_after):
        requested_after_values.append(requested_after)
        return "123456"

    monkeypatch.setattr(BricklinkRuntimeBrowser, "__init__", _fake_runtime_init)
    monkeypatch.setattr(BricklinkRuntimeBrowser, "get_page", lambda self: page)
    monkeypatch.setattr(BricklinkRuntimeBrowser, "close", lambda self: None)
    monkeypatch.setattr("bricklink_cli.browser_runtime.time.time", lambda: 1_774_000_120)
    monkeypatch.setattr(
        "bricklink_cli.browser_runtime.get_bricklink_confirmation_code",
        fake_confirmation_code,
    )

    runner = CliRunner()
    result = runner.invoke(app, ["messages", "list"])

    assert result.exit_code == 0
    assert page.entered_code == "123456"
    assert requested_after_values == [1_774_000_000]
    assert page.goto_calls == [
        "https://www.bricklink.com/myMsg.asp?pg=1&a=i",
        "https://www.bricklink.com/myMsg.asp?pg=1&a=i",
    ]

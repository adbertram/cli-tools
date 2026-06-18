from unittest.mock import MagicMock

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


def test_messages_list_prompts_for_confirmation_code_and_retries(monkeypatch):
    from bricklink_cli.main import app
    from bricklink_cli.browser_runtime import BricklinkRuntimeBrowser

    page = _ConfirmationPage()

    monkeypatch.setattr(BricklinkRuntimeBrowser, "__init__", _fake_runtime_init)
    monkeypatch.setattr(BricklinkRuntimeBrowser, "get_page", lambda self: page)
    monkeypatch.setattr(BricklinkRuntimeBrowser, "close", lambda self: None)

    runner = CliRunner()
    result = runner.invoke(app, ["messages", "list"], input="123456\n")

    assert result.exit_code == 0
    assert page.entered_code == "123456"
    assert page.goto_calls == [
        "https://www.bricklink.com/myMsg.asp?pg=1&a=i",
        "https://www.bricklink.com/myMsg.asp?pg=1&a=i",
    ]

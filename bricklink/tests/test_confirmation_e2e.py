from unittest.mock import MagicMock

from typer.testing import CliRunner


class _ConfirmationPage:
    def __init__(self):
        self.url = "https://www.bricklink.com/v3/confirmation_code_required.page"

    def goto(self, url, wait_until=None):
        self.url = "https://www.bricklink.com/v3/confirmation_code_required.page"

    def wait_for_selector(self, selector, state=None, timeout=None):
        return object()

    def wait_for_timeout(self, timeout):
        return None

    def evaluate(self, script, *args):
        raise AssertionError("request path must not evaluate the confirmation page")

    def query_selector(self, selector):
        raise AssertionError("request path must not inspect confirmation-page controls")


def _fake_runtime_init(self, config=None):
    self.config = MagicMock()
    self.confirmation = MagicMock()
    self.confirmation.is_pending.return_value = False
    self.clear_session = MagicMock()
    self._confirmation_handler = None


def test_messages_list_fails_immediately_on_confirmation_code_page(monkeypatch):
    from bricklink_cli.main import app
    from bricklink_cli.browser_runtime import BricklinkRuntimeBrowser

    page = _ConfirmationPage()

    monkeypatch.setattr(BricklinkRuntimeBrowser, "__init__", _fake_runtime_init)
    monkeypatch.setattr(BricklinkRuntimeBrowser, "get_page", lambda self, url: page)
    monkeypatch.setattr(BricklinkRuntimeBrowser, "close", lambda self: None)

    runner = CliRunner()
    result = runner.invoke(app, ["messages", "list"])

    assert result.exit_code == 1
    assert "BrickLink requires an email confirmation code." in result.output
    assert "Check your email and retry." in result.output

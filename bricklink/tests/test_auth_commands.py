from bricklink_cli.commands.auth import _test_handler
from bricklink_cli.commands import messages, notification, refund


def test_test_handler_uses_uncached_connection_probe(monkeypatch):
    calls = []

    class DummyClient:
        def test_connection(self):
            calls.append("test_connection")

        def list_orders(self, direction="in"):
            raise AssertionError("auth test handler must not call cached list_orders()")

    monkeypatch.setattr("bricklink_cli.client.BricklinkClient", DummyClient)

    result = _test_handler(config=None)

    assert calls == ["test_connection"]
    assert result == {"api_test": "passed", "method": "oauth1_api"}


def test_browser_only_command_groups_require_only_browser_session():
    assert messages.COMMAND_CREDENTIALS == {
        "get": ["browser_session"],
        "list": ["browser_session"],
        "mark-read": ["browser_session"],
        "mark-unread": ["browser_session"],
        "reply": ["browser_session"],
        "send": ["browser_session"],
    }
    assert refund.COMMAND_CREDENTIALS == {
        "full": ["browser_session"],
        "info": ["browser_session"],
        "issue": ["browser_session"],
    }
    assert notification.COMMAND_CREDENTIALS == {
        "get": ["browser_session"],
        "list": ["browser_session"],
        "send-wanted-list": ["browser_session"],
    }

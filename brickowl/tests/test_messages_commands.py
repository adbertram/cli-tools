import json

from brickowl_cli.commands import messages


class _MessagesBrowser:
    def __init__(self):
        self.closed = False

    @staticmethod
    def normalize_subject(subject):
        return subject.lower()

    def list_messages(self, folder="received"):
        return [
            {
                "message_id": "123",
                "date": "Jul 20, 2026, 14:22",
                "from": "geeklife",
                "to": "buyer",
                "subject": "Order #456",
                "is_unread": False,
            }
        ]

    def get_message(self, message_id):
        return {
            "message_id": message_id,
            "sent_date": "Jul 20, 2026, 14:22",
            "from": "geeklife",
            "to": "buyer",
            "subject": "Order #456",
            "body": "Your order is ready.",
        }

    def close(self):
        self.closed = True


def test_outbox_list_with_history_emits_only_json_on_stdout(monkeypatch, capsys):
    browser = _MessagesBrowser()

    import brickowl_cli.browser as browser_module

    monkeypatch.setattr(browser_module, "get_browser", lambda: browser)
    monkeypatch.setattr(browser_module, "BrickOwlBrowser", _MessagesBrowser)

    messages.messages_list(
        folder="outbox",
        page=1,
        include_history=True,
        table=False,
        filter=None,
        limit=100,
        properties=None,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert captured.err == ""
    assert isinstance(payload, list)
    assert payload[0]["username"] == "buyer"
    assert payload[0]["message_history"][0]["message_id"] == "123"
    assert browser.closed is True

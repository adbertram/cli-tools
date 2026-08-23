from bricklink_cli.commands.messages import _build_conversation


class _ConversationBrowser:
    def __init__(self):
        self.list_calls = []

    def list_messages(self, page_num=1, folder="i"):
        self.list_calls.append((folder, page_num))
        pages = {
            ("i", 1): [
                {
                    "message_id": "1",
                    "subject": "Re: Missing Part Notification",
                    "date": "Jun 14, 2026 1:00 PM",
                }
            ],
            ("i", 2): [
                {
                    "message_id": "2",
                    "subject": "Re: Missing Part Notification",
                    "date": "Jun 12, 2026 1:00 PM",
                }
            ],
            ("i", 3): [
                {
                    "message_id": "3",
                    "subject": "Re: Missing Part Notification",
                    "date": "Jun 11, 2026 1:00 PM",
                }
            ],
            ("i", 4): [
                {
                    "message_id": "4",
                    "subject": "Re: Missing Part Notification",
                    "date": "Jun 10, 2026 1:00 PM",
                }
            ],
            ("o", 1): [],
        }
        return pages.get((folder, page_num), [])

    def get_message(self, message_id, folder="i"):
        return {
            "message_id": message_id,
            "subject": "Re: Missing Part Notification",
            "sent_date": f"Jun {15 - int(message_id)}, 2026 1:00 PM",
            "body": "fixture",
        }


def test_build_conversation_bounds_generic_reply_subjects_by_source_date(monkeypatch):
    browser = _ConversationBrowser()
    source_detail = {
        "message_id": "1",
        "subject": "Re: Missing Part Notification",
        "sent_date": "Jun 14, 2026 1:00 PM",
        "body": "fixture",
    }

    conversation = _build_conversation(
        browser,
        "Re: Missing Part Notification",
        "1",
        source_detail,
        max_search_messages=3,
    )

    assert conversation
    assert ("i", 3) not in browser.list_calls

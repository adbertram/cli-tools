from types import SimpleNamespace

from buttondown_cli.client import ButtondownClient
from buttondown_cli.models import Subscriber, Tag


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def config():
    return SimpleNamespace(
        api_key="test-key",
        base_url="https://api.buttondown.com/v1",
        has_credentials=lambda: True,
    )


def test_auth_header_uses_buttondown_token_scheme():
    session = FakeSession([FakeResponse({"ok": True})])
    client = ButtondownClient(config=config(), session=session)

    client.ping()

    assert session.calls[0]["headers"]["Authorization"] == "Token test-key"


def test_list_subscribers_translates_filters_and_follows_next_until_limit():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "count": 2,
                    "next": "https://api.buttondown.com/v1/subscribers?page=2",
                    "results": [
                        {
                            "id": "sub_1",
                            "creation_date": "2026-04-20T00:00:00Z",
                            "email_address": "one@example.com",
                            "referral_code": "ABC",
                            "secondary_id": 1,
                            "source": "api",
                            "tags": [],
                            "type": "regular",
                            "utm_campaign": "",
                            "utm_medium": "",
                            "utm_source": "",
                        }
                    ],
                }
            ),
            FakeResponse(
                {
                    "count": 2,
                    "next": None,
                    "results": [
                        {
                            "id": "sub_2",
                            "creation_date": "2026-04-20T00:00:00Z",
                            "email_address": "two@example.com",
                            "referral_code": "DEF",
                            "secondary_id": 2,
                            "source": "api",
                            "tags": ["vip"],
                            "type": "regular",
                            "utm_campaign": "",
                            "utm_medium": "",
                            "utm_source": "",
                        }
                    ],
                }
            ),
        ]
    )
    client = ButtondownClient(config=config(), session=session)

    subscribers = client.list_subscribers(
        limit=2,
        filters=["email_address:ilike:example.com", "type:eq:regular"],
    )

    assert [subscriber.email_address for subscriber in subscribers] == [
        "one@example.com",
        "two@example.com",
    ]
    assert isinstance(subscribers[0], Subscriber)
    assert session.calls[0]["params"] == {
        "email_address": "example.com",
        "type": "regular",
    }
    assert session.calls[1]["url"] == "https://api.buttondown.com/v1/subscribers?page=2"


def test_create_tag_returns_typed_model():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "id": "tag_1",
                    "creation_date": "2026-04-20T00:00:00Z",
                    "secondary_id": 1,
                    "name": "VIP",
                    "color": "#FFD700",
                    "subscriber_editable": False,
                }
            )
        ]
    )
    client = ButtondownClient(config=config(), session=session)

    tag = client.create_tag(name="VIP", color="#FFD700")

    assert isinstance(tag, Tag)
    assert tag.name == "VIP"
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["json"] == {"name": "VIP", "color": "#FFD700"}

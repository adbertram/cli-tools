import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError

from airbnb_cli.chrome_session import AirbnbChromeSession
from airbnb_cli.client import (
    DEFERRED_STATE_SCRIPT_ID,
    INJECTOR_SCRIPT_ID,
    AirbnbClient,
    _coerce_message_thread_id,
    _encode_global_id,
)


class FakeResponse:
    def __init__(self, *, status_code=200, text="", data=None):
        self.status_code = status_code
        self.text = text
        self._data = data
        self.headers = {}
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class FakeCookieJar:
    def __init__(self):
        self.cookies = []

    def set(self, name, value, **kwargs):
        self.cookies.append({"name": name, "value": value, **kwargs})


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.headers = {}
        self.cookies = FakeCookieJar()
        self.requests = []

    def request(self, method, url, params=None, headers=None, timeout=None):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "params": params,
                "headers": headers or {},
                "timeout": timeout,
            }
        )
        for marker, response in self.responses.items():
            if marker in url:
                return response
        raise AssertionError(f"unexpected request url: {url}")


class FakeBrowserSession:
    def close(self):
        return None


def _global_id(typename: str, internal_id: str) -> str:
    return base64.b64encode(f"{typename}:{internal_id}".encode()).decode()


def _script_state_html(script_id: str, state: dict) -> str:
    return f'<script id="{script_id}" type="application/json">{json.dumps(state)}</script>'


def _injector_html(entries):
    state = {"root": [["NiobeClientToken", entries, 0]]}
    return _script_state_html(INJECTOR_SCRIPT_ID, state)


def _deferred_html(results):
    state = {
        "niobeClientData": [
            [
                "StaysSearch:{}",
                {
                    "data": {
                        "presentation": {
                            "staysSearch": {
                                "results": {
                                    "searchResults": results,
                                }
                            }
                        }
                    }
                },
            ]
        ]
    }
    return _script_state_html(DEFERRED_STATE_SCRIPT_ID, state)


def _config(tmp_path: Path):
    return SimpleNamespace(
        CREDENTIAL_TYPES=[CredentialType.CUSTOM],
        base_url="https://www.airbnb.com",
        browser_user_agent="test-agent",
        airbnb_api_key="api-key",
        auth_cookies=[
            {
                "name": "_airbed_session_id",
                "value": "session",
                "domain": ".airbnb.com",
                "path": "/",
                "secure": True,
            }
        ],
        storage_dir=tmp_path,
        has_credentials=lambda: True,
        has_saved_session=lambda: True,
        get_browser=lambda: FakeBrowserSession(),
        get_missing_credentials=lambda: [],
    )


class LoginConfig:
    browser_user_agent = "test-agent"

    def __init__(self):
        self.saved = False
        self.cleared = False

    def clear_session(self):
        self.cleared = True

    def save_chrome_session(self, cookies, api_key):
        self.saved = True


@pytest.fixture(autouse=True)
def disable_cache(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "false")


def test_listings_parse_airbnb_page_state(tmp_path):
    listing = {"id": "listing-1", "name": "Cabin", "status": "listed"}
    html = _injector_html(
        [
            [
                'BeehiveGetListingsQuery:{"request":{"limit":30}}',
                {"data": {"presentation": {"beehiveListings": {"listings": [listing]}}}},
            ]
        ]
    )
    session = FakeSession({"hosting/listings": FakeResponse(text=html)})
    client = AirbnbClient(config=_config(tmp_path), session=session)

    assert client.list_listings(limit=10) == [listing]


def test_search_stays_parse_public_deferred_state(tmp_path):
    result = {
        "title": "Cabin in Pigeon Forge",
        "subtitle": "Mountain cabin with hot tub",
        "avgRatingLocalized": "4.95 (312)",
        "avgRatingA11yLabel": "4.95 out of 5 average rating, 312 reviews",
        "structuredDisplayPrice": {
            "primaryLine": {
                "discountedPrice": "$426",
                "originalPrice": "$469",
                "qualifier": "for 2 nights",
                "accessibilityLabel": "$426 for 2 nights, originally $469",
            },
            "explanationData": {
                "priceDetails": [
                    {
                        "items": [
                            {
                                "description": "2 nights x $212.83",
                                "priceString": "$425.66",
                            }
                        ]
                    }
                ]
            },
        },
        "structuredContent": {
            "primaryLine": [
                {"body": "1 bedroom"},
                {"body": "1 king bed"},
                {"body": "1 bath"},
            ]
        },
        "badges": [{"text": "Guest favorite"}],
        "paymentMessages": [{"text": "Free cancellation"}],
        "contextualPictures": [{"picture": "https://example.test/image.jpg"}],
        "demandStayListing": {
            "id": _global_id("DemandStayListing", "43045473"),
            "location": {"coordinate": {"latitude": 35.79795, "longitude": -83.63991}},
            "description": {
                "name": {
                    "localizedStringWithTranslationPreference": "Mountain cabin with hot tub",
                }
            },
        },
    }
    session = FakeSession({"s/homes": FakeResponse(text=_deferred_html([result]))})
    client = AirbnbClient(config=_config(tmp_path), session=session, require_credentials=False)

    records = client.search_stays(
        destination="Pigeon Forge, TN",
        checkin="2026-08-01",
        checkout="2026-08-03",
        adults=2,
        children=1,
        pets=1,
        min_price=100,
        max_price=500,
        bedrooms=1,
        beds=1,
        bathrooms=1,
        room_types=["Entire home/apt"],
        property_type_ids=["4"],
        limit=1,
    )

    assert records == [
        {
            "id": "43045473",
            "name": "Mountain cabin with hot tub",
            "title": "Cabin in Pigeon Forge",
            "subtitle": "Mountain cabin with hot tub",
            "url": "https://www.airbnb.com/rooms/43045473?check_in=2026-08-01&check_out=2026-08-03&adults=2",
            "rating": "4.95 (312)",
            "rating_label": "4.95 out of 5 average rating, 312 reviews",
            "price_display": "$426",
            "price_total": 425.66,
            "price_original": 469.0,
            "price_qualifier": "for 2 nights",
            "nightly_price_display": "2 nights x $212.83",
            "details": ["1 bedroom", "1 king bed", "1 bath"],
            "badges": ["Guest favorite"],
            "payment_messages": ["Free cancellation"],
            "latitude": 35.79795,
            "longitude": -83.63991,
            "image_url": "https://example.test/image.jpg",
        }
    ]
    request = session.requests[0]
    assert request["url"] == "https://www.airbnb.com/s/homes"
    assert ("query", "Pigeon Forge, TN") in request["params"]
    assert ("checkin", "2026-08-01") in request["params"]
    assert ("checkout", "2026-08-03") in request["params"]
    assert ("adults", "2") in request["params"]
    assert ("price_min", "100") in request["params"]
    assert ("price_max", "500") in request["params"]
    assert ("room_types[]", "Entire home/apt") in request["params"]
    assert ("property_type_id[]", "4") in request["params"]


def test_verify_host_session_only_requires_niobe_state(tmp_path):
    html = _injector_html([["UnifiedListOfListingsQuery:{}", {"data": {"viewer": {"user": {"id": "1"}}}}]])
    session = FakeSession({"hosting/listings": FakeResponse(text=html)})
    client = AirbnbClient(config=_config(tmp_path), session=session)

    assert client.verify_host_session() is None


def test_login_clears_imported_session_when_live_verification_fails(monkeypatch):
    config = LoginConfig()
    browser = AirbnbChromeSession(config)
    monkeypatch.setattr("airbnb_cli.chrome_session.read_airbnb_cookies", lambda: [{"name": "_airbed_session_id"}])
    monkeypatch.setattr(browser, "_extract_api_key", lambda cookies: "api-key")
    monkeypatch.setattr(browser, "test_session", lambda: {"authenticated": False, "error": "missing Niobe"})

    with pytest.raises(ClientError, match="missing Niobe"):
        browser.login()

    assert config.saved is True
    assert config.cleared is True


def test_reservations_call_read_endpoint_with_limit(tmp_path):
    session = FakeSession(
        {
            "api/v2/reservations": FakeResponse(
                data={"reservations": [{"id": 123}], "metadata": {"total_count": 1}}
            )
        }
    )
    client = AirbnbClient(config=_config(tmp_path), session=session)

    assert client.list_reservations(limit=7, date_min="2026-06-17") == [{"id": 123}]
    request = session.requests[0]
    assert request["params"]["_limit"] == 7
    assert request["params"]["date_min"] == "2026-06-17"
    assert request["params"]["_format"] == "for_remy"


def test_messages_use_viewer_global_id_and_return_inbox_nodes(tmp_path):
    html = _injector_html(
        [
            [
                'UnifiedListOfListingsQuery:{"first":24}',
                {"data": {"viewer": {"user": {"id": _global_id("User", "67386970")}}}},
            ]
        ]
    )
    inbox_data = {
        "data": {
            "node": {
                "messagingInbox": {
                    "priorityItems": None,
                    "inboxItems": {"edges": [{"node": {"id": "thread-1"}}]},
                }
            }
        },
        "extensions": {"traceId": "trace"},
    }
    session = FakeSession(
        {
            "hosting/listings": FakeResponse(text=html),
            "ViaductInboxData": FakeResponse(data=inbox_data),
        }
    )
    client = AirbnbClient(config=_config(tmp_path), session=session)

    assert client.list_messages(limit=5) == [{"id": "thread-1"}]
    request = session.requests[-1]
    variables = json.loads(request["params"]["variables"])
    assert variables["userId"] == _global_id("Viewer", "67386970")
    assert variables["numRequestedThreads"] == 5


def test_thread_id_is_encoded_when_internal_id_is_passed():
    assert _coerce_message_thread_id("123") == _encode_global_id("MessageThread", "123")


def test_missing_reservations_list_fails_clearly(tmp_path):
    session = FakeSession({"api/v2/reservations": FakeResponse(data={"metadata": {}})})
    client = AirbnbClient(config=_config(tmp_path), session=session)

    with pytest.raises(ClientError, match="reservations list"):
        client.list_reservations(limit=1)

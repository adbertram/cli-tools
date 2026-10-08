"""Client tests with mocked HTTP: request shapes, envelope errors, cost, filters."""

import pytest
import requests

from cli_tools_shared.exceptions import ClientError, CredentialError
from dataforseo_cli.client import DataforseoClient, to_api_filters


class _Config:
    CREDENTIAL_TYPES = []
    base_url = "https://api.dataforseo.test"
    username = "login@example.com"
    password = "api-password"

    def has_credentials(self):
        return True


class _Response:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.ok = status_code < 400
        self.headers = {}
        self.text = str(body)

    def json(self):
        return self._body


def _envelope(result, cost=0.0123, status_code=20000, task_status=20000, task_message="Ok."):
    return {
        "status_code": status_code,
        "status_message": "Ok.",
        "cost": cost,
        "tasks": [{"status_code": task_status, "status_message": task_message, "result": result}],
    }


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "false")


@pytest.fixture
def sent(monkeypatch):
    """Capture the one request the client sends and answer with `sent.response`."""

    class Sent:
        calls = []
        response = None

    def fake_request(method, url, **kwargs):
        Sent.calls.append({"method": method, "url": url, **kwargs})
        return Sent.response

    Sent.calls = []
    monkeypatch.setattr(requests, "request", fake_request)
    return Sent


def _client():
    return DataforseoClient(config=_Config())


def test_search_volume_request_and_result(sent):
    rows = [{"keyword": "powershell", "search_volume": 1000, "cpc": 1.2}]
    sent.response = _Response(_envelope(rows, cost=0.09))
    client = _client()

    assert client.search_volume(["powershell"]) == rows

    call = sent.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.dataforseo.test/v3/keywords_data/google_ads/search_volume/live"
    assert call["json"] == [{"keywords": ["powershell"], "location_code": 2840, "language_code": "en"}]
    assert call["auth"] == ("login@example.com", "api-password")
    assert client.last_cost == 0.09


def test_keyword_difficulty_returns_items(sent):
    items = [{"keyword": "powershell", "keyword_difficulty": 55}]
    sent.response = _Response(_envelope([{"items_count": 1, "items": items}]))

    assert _client().keyword_difficulty(["powershell"], 2826, "en") == items

    call = sent.calls[0]
    assert call["url"].endswith("/v3/dataforseo_labs/google/bulk_keyword_difficulty/live")
    assert call["json"] == [{"keywords": ["powershell"], "location_code": 2826, "language_code": "en"}]


def test_keyword_ideas_sends_limit_filters_and_order(sent):
    items = [{"keyword": "powershell tips", "keyword_info": {"search_volume": 90}}]
    sent.response = _Response(_envelope([{"items": items}]))

    result = _client().keyword_ideas(
        ["powershell"],
        limit=5,
        filters=["keyword_info.search_volume:gte:50,keyword_properties.keyword_difficulty:lt:40"],
        order_by="keyword_info.search_volume,desc",
    )

    assert result == items
    task = sent.calls[0]["json"][0]
    assert task["limit"] == 5
    assert task["order_by"] == ["keyword_info.search_volume,desc"]
    assert task["filters"] == [
        ["keyword_info.search_volume", ">=", 50],
        "and",
        ["keyword_properties.keyword_difficulty", "<", 40],
    ]


def test_keyword_ideas_without_items_returns_empty(sent):
    sent.response = _Response(_envelope([{"total_count": 0, "items": None}]))
    assert _client().keyword_ideas(["nothing"]) == []


def test_get_user_data_uses_get_and_returns_first_result(sent):
    data = {"login": "me", "money": {"balance": 0.9, "total": 1}}
    sent.response = _Response(_envelope([data], cost=0))

    assert _client().get_user_data() == data
    assert sent.calls[0]["method"] == "GET"
    assert sent.calls[0]["url"].endswith("/v3/appendix/user_data")


def test_top_level_non_20000_fails_with_status_message(sent):
    sent.response = _Response(_envelope([], status_code=40200, task_status=40200) | {"status_message": "Payment Required."})
    with pytest.raises(ClientError, match="40200: Payment Required."):
        _client().search_volume(["x"])


def test_task_level_error_fails_with_task_message(sent):
    sent.response = _Response(_envelope(None, task_status=40501, task_message="Invalid Field: 'keywords'."))
    with pytest.raises(ClientError, match="task error 40501: Invalid Field: 'keywords'."):
        _client().search_volume(["x"])


def test_http_401_is_credential_error(sent):
    sent.response = _Response({"status_code": 40100, "status_message": "Authentication failed."}, status_code=401)
    with pytest.raises(CredentialError, match="40100 Authentication failed."):
        _client().get_user_data()


def test_http_403_reports_api_message_without_auth_hint(sent):
    body = {"status_code": 40104, "status_message": "Please verify your account before using the API."}
    sent.response = _Response(body, status_code=403)
    with pytest.raises(ClientError, match="40104 Please verify your account") as excinfo:
        _client().keyword_difficulty(["x"])
    assert "auth login" not in str(excinfo.value)


def test_multiple_filter_flags_are_rejected():
    with pytest.raises(ClientError, match="Multiple --filter flags"):
        to_api_filters(["a:eq:1", "b:eq:2"])


def test_unsupported_operator_is_rejected():
    with pytest.raises(ClientError, match="'notnull' is not supported"):
        to_api_filters(["keyword_info.cpc:notnull"])


def test_filter_translation_covers_operators():
    assert to_api_filters(["keyword_info.search_volume:in:10|20"]) == [["keyword_info.search_volume", "in", [10, 20]]]
    assert to_api_filters(["keyword:contains:power"]) == [["keyword", "ilike", "%power%"]]
    assert to_api_filters(["keyword:startswith:how"]) == [["keyword", "ilike", "how%"]]
    assert to_api_filters(["keyword_info.cpc:gt:1.5"]) == [["keyword_info.cpc", ">", 1.5]]
    assert to_api_filters(["keyword:ne:foo"]) == [["keyword", "<>", "foo"]]
    assert to_api_filters(None) is None


def test_more_than_eight_conditions_rejected():
    many = ",".join(f"keyword_info.cpc:gt:{i}" for i in range(9))
    with pytest.raises(ClientError, match="at most 8"):
        to_api_filters([many])


def test_unknown_filter_operator_fails_before_any_request(sent):
    with pytest.raises(Exception, match="bogus"):
        _client().keyword_ideas(["x"], filters=["keyword_info.search_volume:bogus:5"])
    assert sent.calls == []


@pytest.mark.parametrize("limit", [0, 1001, -5])
def test_ideas_limit_bounds_enforced_without_request(sent, limit):
    with pytest.raises(ClientError, match="--limit must be between 1 and 1000"):
        _client().keyword_ideas(["x"], limit=limit)
    assert sent.calls == []


def test_blank_keywords_rejected_without_request(sent):
    with pytest.raises(ClientError, match="non-empty"):
        _client().search_volume(["ok", "  "])
    with pytest.raises(ClientError, match="non-empty"):
        _client().keyword_difficulty([""])
    assert sent.calls == []

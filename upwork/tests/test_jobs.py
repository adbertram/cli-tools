"""Offline tests for the Upwork jobs GraphQL group (no live credentials)."""

from __future__ import annotations

import pytest
from cli_tools_shared.filters import FilterValidationError

from upwork_cli.filters import (
    ALLOWED_FILTER_FIELDS,
    build_jobs_filter_input,
    split_server_and_client_filters,
    validate_jobs_filters,
)
from upwork_cli.graphql import UpworkGraphQLClient, UpworkGraphQLError
from upwork_cli.jobs_client import UpworkJobsClient, normalize_job


# ---------------------------------------------------------------------------
# Filter map (data-driven)
# ---------------------------------------------------------------------------
def test_server_side_filters_translate_to_suffixed_api_fields():
    server, client = split_server_and_client_filters(
        ["skills:eq:python|automation", "client_location:eq:United States"]
    )
    assert client == []
    api_input = build_jobs_filter_input(server)
    assert api_input["skillExpression_eq"] == "python,automation"
    assert api_input["locations_any"] == ["United States"]


def test_client_side_filters_are_partitioned_out():
    server, client = split_server_and_client_filters(
        ["job_type:eq:hourly", "hourly_min:gte:50"]
    )
    assert server == []
    assert set(client) == {"job_type:eq:hourly", "hourly_min:gte:50"}
    # No server-side fields => empty API filter input.
    assert build_jobs_filter_input(server) == {}


def test_query_field_maps_to_title_expression():
    server, _client = split_server_and_client_filters(["query:eq:react developer"])
    assert build_jobs_filter_input(server) == {"titleExpression_eq": "react developer"}


def test_unknown_filter_field_raises():
    with pytest.raises(FilterValidationError):
        validate_jobs_filters(["nonsense:eq:1"])


def test_allowed_fields_cover_website_filters():
    for field in (
        "query",
        "skills",
        "category",
        "client_location",
        "job_type",
        "experience_level",
        "fixed_min",
        "fixed_max",
        "hourly_min",
        "hourly_max",
        "posted_after",
    ):
        assert field in ALLOWED_FILTER_FIELDS


# ---------------------------------------------------------------------------
# GraphQL error handling (HTTP 200 with errors array must raise)
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class _FakeConfig:
    """Minimal config double: credentials present, token never expires."""

    graphql_url = "https://api.upwork.com/graphql"
    access_token = "test-token"
    refresh_token = "test-refresh"
    token_expires_at = None
    OAUTH_TOKEN_URL = "https://www.upwork.com/api/v3/oauth2/token"
    OAUTH_TOKEN_AUTH = "body"
    OAUTH_REDIRECT_URI = "http://localhost:8765/callback"
    client_id = "cid"
    client_secret = "secret"

    def has_api_credentials(self):
        return True

    @property
    def redirect_uri(self):
        return self.OAUTH_REDIRECT_URI


def _client_with_response(monkeypatch, payload, status_code=200):
    client = UpworkGraphQLClient(_FakeConfig())
    # Never actually refresh or sleep in tests.
    monkeypatch.setattr(client._tokens, "ensure_valid", lambda: None)
    monkeypatch.setattr(client._tokens, "force_refresh", lambda: None)
    monkeypatch.setattr(
        client._session, "post", lambda *a, **k: _FakeResponse(payload, status_code)
    )
    return client


def test_graphql_errors_array_raises_even_on_http_200(monkeypatch):
    client = _client_with_response(
        monkeypatch,
        {"errors": [{"message": "Validation error of type MissingFieldArgument"}]},
    )
    with pytest.raises(UpworkGraphQLError, match="MissingFieldArgument"):
        client.execute("query { user { id } }")


def test_graphql_missing_credentials_raises(monkeypatch):
    class _NoCreds(_FakeConfig):
        def has_api_credentials(self):
            return False

    client = UpworkGraphQLClient(_NoCreds())
    with pytest.raises(Exception, match="Missing Upwork API credentials"):
        client.execute("query { user { id } }")


def test_graphql_success_returns_data(monkeypatch):
    client = _client_with_response(monkeypatch, {"data": {"user": {"id": "42"}}})
    data = client.execute("query { user { id } }", operation_name="user")
    assert data == {"user": {"id": "42"}}


# ---------------------------------------------------------------------------
# Pagination + normalization
# ---------------------------------------------------------------------------
def _search_page(nodes, end_cursor, has_next):
    return {
        "marketplaceJobPostingsSearch": {
            "totalCount": 99,
            "edges": [{"node": node} for node in nodes],
            "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next},
        }
    }


def test_search_paginates_via_page_info_cursor(monkeypatch):
    jobs_client = UpworkJobsClient(_FakeConfig())
    pages = [
        _search_page([{"id": "1", "title": "A"}], "cur1", True),
        _search_page([{"id": "2", "title": "B"}], "cur2", False),
    ]
    calls = {"n": 0, "after": []}

    def fake_execute(query, variables=None, operation_name=None):
        calls["after"].append((variables or {}).get("after"))
        page = pages[calls["n"]]
        calls["n"] += 1
        return page

    monkeypatch.setattr(jobs_client._graphql, "execute", fake_execute)
    rows = jobs_client.search_jobs(limit=10)
    assert [r["id"] for r in rows] == ["1", "2"]
    # First call has no cursor; second call passes the first page's endCursor.
    assert calls["after"] == [None, "cur1"]


def test_search_stops_at_limit(monkeypatch):
    jobs_client = UpworkJobsClient(_FakeConfig())

    def fake_execute(query, variables=None, operation_name=None):
        return _search_page(
            [{"id": "1"}, {"id": "2"}, {"id": "3"}], "curX", True
        )

    monkeypatch.setattr(jobs_client._graphql, "execute", fake_execute)
    rows = jobs_client.search_jobs(limit=2)
    assert len(rows) == 2


def test_client_side_filter_applied_after_fetch(monkeypatch):
    jobs_client = UpworkJobsClient(_FakeConfig())

    def fake_execute(query, variables=None, operation_name=None):
        return _search_page(
            [
                {"id": "hourly", "hourlyBudgetType": "MANUAL"},
                {"id": "fixed", "amount": {"currency": "USD", "rawValue": "500"}},
            ],
            "curX",
            False,
        )

    monkeypatch.setattr(jobs_client._graphql, "execute", fake_execute)
    rows = jobs_client.search_jobs(filters=["job_type:eq:fixed"], limit=10)
    assert [r["id"] for r in rows] == ["fixed"]


def test_normalize_job_derives_filter_fields():
    record = normalize_job(
        {
            "id": "1",
            "title": "Build automation",
            "hourlyBudgetType": "MANUAL",
            "hourlyBudgetMin": {"currency": "USD", "rawValue": "40"},
            "hourlyBudgetMax": {"currency": "USD", "rawValue": "80"},
            "experienceLevel": "EXPERT",
            "publishedDateTime": "2026-06-01T00:00:00Z",
        }
    )
    assert record["job_type"] == "hourly"
    assert record["hourly_min"] == 40.0
    assert record["hourly_max"] == 80.0
    assert record["experience_level"] == "expert"
    assert record["published_datetime"] == "2026-06-01T00:00:00Z"
    # Original node fields are preserved.
    assert record["title"] == "Build automation"


def test_invalid_sort_raises(monkeypatch):
    jobs_client = UpworkJobsClient(_FakeConfig())
    with pytest.raises(Exception, match="Unsupported sort"):
        jobs_client.search_jobs(sort="cheapest", limit=1)

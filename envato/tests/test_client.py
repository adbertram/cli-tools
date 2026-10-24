"""Output-contract tests for the Envato client normalizers and option resolvers.

Fixture records mirror the live response shapes of the search endpoint
(rating is an object) and the catalog item endpoint (rating is a number with a
separate rating_count). No network access is needed.
"""
import pytest
from typer.testing import CliRunner

from cli_tools_shared.exceptions import ClientError, CredentialError

import envato_cli.client as client_module
from envato_cli.client import (
    normalize_item,
    normalize_search_match,
    resolve_site,
    resolve_sort,
)
from envato_cli.main import app

CONTRACT_FIELDS = [
    "id", "title", "url", "price", "number_of_sales", "rating",
    "rating_count", "published_at", "updated_at", "site",
]
COMMON = {
    "id": 5529125,
    "name": "Out-of-the-Box | Dropbox plugin for WordPress",
    "url": "https://codecanyon.net/item/outofthebox-dropbox-plugin-for-wordpress-/5529125",
    "price_cents": 6900,
    "number_of_sales": 8184,
    "published_at": "2013-09-10T22:10:47+10:00",
    "updated_at": "2026-10-14T20:43:58+11:00",
    "site": "codecanyon.net",
    "author_username": "ignored",
}
EXPECTED = {
    "id": 5529125,
    "title": "Out-of-the-Box | Dropbox plugin for WordPress",
    "url": "https://codecanyon.net/item/outofthebox-dropbox-plugin-for-wordpress-/5529125",
    "price": 69.0,
    "number_of_sales": 8184,
    "rating": 4.83,
    "rating_count": 236,
    "published_at": "2013-09-10T22:10:47+10:00",
    "updated_at": "2026-10-14T20:43:58+11:00",
    "site": "codecanyon.net",
}


def test_search_match_and_catalog_item_share_one_shape():
    search = normalize_search_match({**COMMON, "rating": {"rating": 4.83, "count": 236}})
    item = normalize_item({**COMMON, "rating": 4.83, "rating_count": 236})
    assert search == item == EXPECTED
    assert list(search) == CONTRACT_FIELDS


def test_missing_contract_field_fails_loudly():
    raw = {key: value for key, value in COMMON.items() if key != "price_cents"}
    with pytest.raises(KeyError):
        normalize_item({**raw, "rating": 4.83, "rating_count": 236})


@pytest.mark.parametrize(
    ("sort", "desc", "expected"),
    [
        ("newest", False, {"sort_by": "date", "sort_direction": "desc"}),
        ("newest", True, {"sort_by": "date", "sort_direction": "asc"}),
        ("price", False, {"sort_by": "price", "sort_direction": "asc"}),
        ("SALES", True, {"sort_by": "sales", "sort_direction": "desc"}),
        ("relevance", False, {"sort_by": "relevance"}),
    ],
)
def test_resolve_sort(sort, desc, expected):
    assert resolve_sort(sort, desc) == expected


def test_resolve_sort_rejects_unknown_value_and_relevance_desc():
    with pytest.raises(ClientError, match="Valid values: newest"):
        resolve_sort("popular", False)
    with pytest.raises(ClientError, match="--desc cannot be used"):
        resolve_sort("relevance", True)


@pytest.mark.parametrize(
    ("site", "expected"),
    [("codecanyon", "codecanyon.net"), ("codecanyon.net", "codecanyon.net"), (" ThemeForest ", "themeforest.net")],
)
def test_resolve_site(site, expected):
    assert resolve_site(site) == expected


def test_search_rejects_invalid_sort_before_any_request():
    result = CliRunner().invoke(app, ["search", "dropbox", "--sort", "popular"])
    assert result.exit_code == 1
    assert "Invalid --sort 'popular'" in result.output


@pytest.mark.parametrize("limit", ["0", "101"])
def test_search_limit_is_bounded_to_envato_page_size(limit):
    result = CliRunner().invoke(app, ["search", "dropbox", "--limit", limit])
    assert result.exit_code == 2


class _FakeConfig:
    base_url = "https://api.envato.com"
    personal_access_token = "fake-token"

    def has_credentials(self):
        return True


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.ok = status_code < 400
        self.headers = {}
        self._body = body

    def json(self):
        return self._body


@pytest.mark.parametrize(
    ("status", "body", "error", "message"),
    [
        (401, {"error": "Missing or malformed API token: x", "reason": "missing-token"},
         CredentialError, "HTTP 401: Missing or malformed API token"),
        (404, {"error": 404, "description": "Item not found with that ID"},
         ClientError, "HTTP 404: Item not found with that ID"),
    ],
)
def test_api_errors_map_to_plain_messages(monkeypatch, status, body, error, message):
    monkeypatch.setattr(client_module.requests, "get", lambda *a, **k: _FakeResponse(status, body))
    with pytest.raises(error, match=message):
        client_module.EnvatoClient(config=_FakeConfig())._get(client_module.ITEM_PATH, {"id": "1"})

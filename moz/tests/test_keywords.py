"""Tests for `moz keywords` partial-result handling and Moz error classification."""
import json

import pytest
from typer.testing import CliRunner

from moz_cli import client as client_module
from moz_cli.client import ClientError, MozClient, NoDataError
from moz_cli.commands import keywords as keywords_commands
from moz_cli.main import app
from moz_cli.models import create_keyword_metrics


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code, payload, content_type="application/json", text=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.headers = {"Content-Type": content_type}
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


def _client(monkeypatch, response):
    """Build a MozClient whose single HTTP call returns `response`."""
    monkeypatch.setattr(
        client_module.requests, "post", lambda *args, **kwargs: response
    )

    class FakeConfig:
        api_key = "test-key"
        base_url = "https://api.moz.test/jsonrpc"

        def has_credentials(self):
            return True

    return MozClient(config=FakeConfig())


class FakeKeywordClient:
    """Keyword client whose metrics are looked up from a fixed table."""

    def __init__(self, metrics_by_keyword, errors_by_keyword=None):
        self.metrics_by_keyword = metrics_by_keyword
        self.errors_by_keyword = errors_by_keyword or {}
        self.requested = []

    def get_keyword_metrics(self, keyword):
        self.requested.append(keyword)
        if keyword in self.errors_by_keyword:
            raise self.errors_by_keyword[keyword]
        return create_keyword_metrics(self.metrics_by_keyword[keyword])


# ==================== Client error classification ====================


def test_jsonrpc_404_envelope_raises_no_data_error(monkeypatch):
    response = FakeResponse(
        404,
        {
            "jsonrpc": "2.0",
            "error": {
                "code": -32660,
                "status": 404,
                "message": "No keyword metrics found for the provided query.",
            },
        },
    )
    client = _client(monkeypatch, response)

    with pytest.raises(NoDataError) as exc_info:
        client.get_keyword_metrics("query performance insight")

    assert "No keyword metrics found" in str(exc_info.value)


def test_quota_403_stays_a_hard_client_error(monkeypatch):
    response = FakeResponse(
        403,
        {
            "jsonrpc": "2.0",
            "error": {
                "code": -32670,
                "status": 403,
                "message": "The account does not have enough quota remaining for current period.",
            },
        },
    )
    client = _client(monkeypatch, response)

    with pytest.raises(ClientError) as exc_info:
        client.get_keyword_metrics("azure sql database")

    assert not isinstance(exc_info.value, NoDataError)
    assert "403" in str(exc_info.value)


def test_non_json_404_is_not_treated_as_missing_data(monkeypatch):
    """A proxy/gateway 404 is infrastructure failure, not a Moz answer."""
    response = FakeResponse(
        404, None, content_type="text/html", text="<html>404 Not Found</html>"
    )
    client = _client(monkeypatch, response)

    with pytest.raises(ClientError) as exc_info:
        client.get_keyword_metrics("azure sql database")

    assert not isinstance(exc_info.value, NoDataError)


# ==================== keywords list partial results ====================


def test_keywords_list_returns_metrics_for_resolvable_keywords(monkeypatch):
    fake = FakeKeywordClient(
        metrics_by_keyword={
            "azure sql database": {
                "keyword": "azure sql database",
                "volume": 1450,
                "difficulty": 70.0,
            }
        },
        errors_by_keyword={
            "query performance insight": NoDataError(
                "No keyword metrics found for the provided query."
            )
        },
    )
    monkeypatch.setattr(keywords_commands, "get_client", lambda: fake)

    result = CliRunner().invoke(
        app, ["keywords", "list", "-k", "azure sql database,query performance insight"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [row["keyword"] for row in payload] == ["azure sql database"]
    assert payload[0]["volume"] == 1450
    assert fake.requested == ["azure sql database", "query performance insight"]
    assert "query performance insight" in result.stderr
    assert "no metrics" in result.stderr


def test_keywords_list_reports_every_unresolved_keyword(monkeypatch):
    fake = FakeKeywordClient(
        metrics_by_keyword={},
        errors_by_keyword={
            "query performance insight": NoDataError("No keyword metrics found."),
            "azure sql performance tuning": NoDataError("No keyword metrics found."),
        },
    )
    monkeypatch.setattr(keywords_commands, "get_client", lambda: fake)

    result = CliRunner().invoke(
        app,
        [
            "keywords",
            "list",
            "-k",
            "query performance insight,azure sql performance tuning",
        ],
    )

    # No metrics is data, not failure: empty result set, exit 0.
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
    assert "query performance insight" in result.stderr
    assert "azure sql performance tuning" in result.stderr


def test_keywords_list_aborts_on_quota_error(monkeypatch):
    fake = FakeKeywordClient(
        metrics_by_keyword={
            "azure sql database": {"keyword": "azure sql database", "volume": 1450}
        },
        errors_by_keyword={
            "sql server": ClientError(
                "API request failed (403): The account does not have enough quota "
                "remaining for current period."
            )
        },
    )
    monkeypatch.setattr(keywords_commands, "get_client", lambda: fake)

    result = CliRunner().invoke(
        app, ["keywords", "list", "-k", "azure sql database,sql server"]
    )

    assert result.exit_code == 1
    assert "quota" in result.stderr


def test_keywords_list_filter_narrows_results(monkeypatch):
    fake = FakeKeywordClient(
        metrics_by_keyword={
            "azure sql database": {
                "keyword": "azure sql database",
                "volume": 1450,
                "difficulty": 70.0,
            },
            "sql server": {
                "keyword": "sql server",
                "volume": 7400,
                "difficulty": 61.0,
            },
        }
    )
    monkeypatch.setattr(keywords_commands, "get_client", lambda: fake)

    result = CliRunner().invoke(
        app,
        ["keywords", "list", "-k", "azure sql database,sql server", "--filter", "volume:gt:2000"],
    )

    assert result.exit_code == 0
    assert [row["keyword"] for row in json.loads(result.stdout)] == ["sql server"]


def test_keywords_list_rejects_unknown_filter_field(monkeypatch):
    fake = FakeKeywordClient(
        metrics_by_keyword={
            "sql server": {"keyword": "sql server", "volume": 7400}
        }
    )
    monkeypatch.setattr(keywords_commands, "get_client", lambda: fake)

    result = CliRunner().invoke(
        app, ["keywords", "list", "-k", "sql server", "--filter", "searchVolume:gt:10"]
    )

    assert result.exit_code == 1
    assert "not filterable" in result.stderr


def test_keywords_list_properties_narrows_output(monkeypatch):
    fake = FakeKeywordClient(
        metrics_by_keyword={
            "sql server": {"keyword": "sql server", "volume": 7400, "difficulty": 61.0}
        }
    )
    monkeypatch.setattr(keywords_commands, "get_client", lambda: fake)

    result = CliRunner().invoke(
        app, ["keywords", "list", "-k", "sql server", "--properties", "keyword,volume"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"keyword": "sql server", "volume": 7400}]


def test_keywords_get_missing_keyword_exits_non_zero(monkeypatch):
    fake = FakeKeywordClient(
        metrics_by_keyword={},
        errors_by_keyword={
            "query performance insight": NoDataError("No keyword metrics found.")
        },
    )
    monkeypatch.setattr(keywords_commands, "get_client", lambda: fake)

    result = CliRunner().invoke(
        app, ["keywords", "get", "query performance insight"]
    )

    assert result.exit_code == 1
    assert "query performance insight" in result.stderr

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner
from google_cli.commands import searchconsole
from google_cli.main import app


@pytest.fixture
def resource(monkeypatch):
    resource = Mock()
    client = Mock()
    client.get_webmasters_v3_service.return_value.sitemaps.return_value = resource
    monkeypatch.setattr(searchconsole, "get_client", lambda profile=None: client)
    return resource


def test_list_filters_before_limit_and_projects(resource):
    resource.list.return_value.execute.return_value = {"sitemap": [
        {"path": "https://example.com/old.xml", "errors": "1"},
        {"path": "https://example.com/new.xml", "errors": "0"},
    ]}
    result = CliRunner().invoke(app, ["searchconsole", "sitemaps", "list", "sc-domain:example.com", "-f", "errors:eq:0", "-l", "1", "-p", "path,errors"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"path": "https://example.com/new.xml", "errors": "0"}]
    resource.list.assert_called_once_with(siteUrl="sc-domain:example.com")


def test_list_empty(resource):
    resource.list.return_value.execute.return_value = {}
    result = CliRunner().invoke(app, ["searchconsole", "sitemaps", "list", "https://example.com/"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []


@pytest.mark.parametrize("action", ["get", "submit"])
def test_sitemap_exact_api_arguments(resource, action):
    getattr(resource, action).return_value.execute.return_value = {"path": "https://example.com/sitemap.xml"} if action == "get" else {}
    result = CliRunner().invoke(app, ["searchconsole", "sitemaps", action, "https://example.com/", "https://example.com/sitemap.xml"])
    assert result.exit_code == 0, result.output
    getattr(resource, action).assert_called_once_with(siteUrl="https://example.com/", feedpath="https://example.com/sitemap.xml")
    payload = json.loads(result.stdout)
    assert payload["path"] == "https://example.com/sitemap.xml"
    if action == "submit":
        assert payload["submitted"] is True


def test_submit_failure_never_reports_success(resource):
    resource.submit.return_value.execute.side_effect = ValueError("API rejected sitemap")
    result = CliRunner().invoke(app, ["searchconsole", "sitemaps", "submit", "https://example.com/", "https://example.com/sitemap.xml"])
    assert result.exit_code != 0
    assert '"submitted": true' not in result.output

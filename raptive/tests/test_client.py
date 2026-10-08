"""RaptiveClient publisher-API calls made from inside the dashboard page."""
import json

import pytest

from cli_tools_shared.exceptions import ClientError
from raptive_cli.client import RaptiveClient


class FakePage:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def evaluate(self, js, arg):
        self.urls.append(arg[0])
        return self.responses.pop(0)


class FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def get_page(self, url):
        assert url == "https://dashboard.raptive.com"
        return self.page

    def close(self):
        self.closed = True


class FakeConfig:
    base_url = "https://dashboard.raptive.com"
    api_base_url = "https://publisher-api.raptive.com"
    site_id = "site1"

    def __init__(self, browser):
        self.browser = browser

    def get_browser(self):
        return self.browser


def make_client(responses):
    browser = FakeBrowser(FakePage(responses))
    return RaptiveClient(FakeConfig(browser)), browser


def ok(body):
    return {"status": 200, "body": json.dumps(body)}


def page_body(records, next_page):
    return ok({"data": records, "meta": {"page": {"next": next_page}}})


def test_date_bounds_reads_analytics_range():
    client, browser = make_client([ok({"data": {"analyticsDateBounds": {
        "range": {"startDate": "2020-07-23", "endDate": "2026-10-06"}}}})])
    bounds = RaptiveClient.get_date_bounds.__wrapped__(client)
    assert (bounds.earliest_date, bounds.latest_date) == ("2020-07-23", "2026-10-06")
    assert browser.closed


def test_date_bounds_unexpected_shape_fails_loudly():
    client, _ = make_client([ok({"earliestDate": "2020-07-23"})])
    with pytest.raises(ClientError, match="Unexpected dateBounds response shape"):
        RaptiveClient.get_date_bounds.__wrapped__(client)


def test_api_pages_caps_page_size_and_truncates_to_limit():
    client, browser = make_client([
        page_body([{"n": i} for i in range(500)], 2),
        page_body([{"n": i} for i in range(500, 1000)], 3),
    ])
    records = client._api_pages("/x?sort=-pageviews", 700)
    assert len(records) == 700
    assert browser.page.urls == [
        "https://publisher-api.raptive.com/x?sort=-pageviews&page[size]=500&page[number]=1",
        "https://publisher-api.raptive.com/x?sort=-pageviews&page[size]=500&page[number]=2",
    ]
    assert browser.closed


def test_api_pages_stops_on_last_page():
    client, browser = make_client([page_body([{"n": 1}], None)])
    assert client._api_pages("/x?sort=-pageviews", 50) == [{"n": 1}]
    assert browser.page.urls == ["https://publisher-api.raptive.com/x?sort=-pageviews&page[size]=50&page[number]=1"]


def test_non_200_reports_status_and_body_and_closes_browser():
    client, browser = make_client([{"status": 400, "body": '{"detail":["page[size] must not be greater than 500"]}'}])
    with pytest.raises(ClientError, match=r"HTTP 400 .*must not be greater than 500"):
        client._api_call("/x")
    assert browser.closed


def test_waf_challenge_status_is_an_error():
    client, _ = make_client([{"status": 202, "body": ""}])
    with pytest.raises(ClientError, match="HTTP 202"):
        client._api_call("/x")


def test_401_means_session_expired():
    client, _ = make_client([{"status": 401, "body": ""}])
    with pytest.raises(ClientError, match="Session expired"):
        client._api_call("/x")


def test_page_errors_surface():
    client, _ = make_client([{"error": "TypeError: Failed to fetch"}])
    with pytest.raises(ClientError, match="Failed to fetch"):
        client._api_call("/x")
    client, _ = make_client([{"error": "no_token"}])
    with pytest.raises(ClientError, match="No JWT token"):
        client._api_call("/x")


def test_config_presents_real_chrome_user_agent(monkeypatch):
    from raptive_cli import config as config_mod

    monkeypatch.setattr(config_mod, "derive_real_chrome_user_agent", lambda: "Mozilla/5.0 Chrome/154.0.1.2 Safari/537.36")
    monkeypatch.delenv("BROWSER_USER_AGENT", raising=False)
    cfg = config_mod.get_config()
    assert "HeadlessChrome" not in cfg.browser_user_agent
    assert config_mod.Config.BROWSER_SESSION_REQUIRES_API_TEST is True

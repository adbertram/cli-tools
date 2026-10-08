"""Analytics HTTP and CLI contracts, independent of live credentials or paid API access."""
import gzip
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from typer.testing import CliRunner

from x_cli.analytics import AnalyticsClient, POST_ANALYTICS_FIELDS, MEDIA_ANALYTICS_FIELDS
from x_cli.client import ClientError, XClient
from x_cli.commands import analytics

START = "2026-10-01T00:00:00Z"
END = "2026-10-02T00:00:00Z"


def config(oauth=True, bearer="test-bearer"):
    return SimpleNamespace(has_api_credentials=lambda: oauth, get_missing_api_credentials=lambda: ["X_CONSUMER_KEY"], consumer_key="key", consumer_secret="secret", access_token="token", access_token_secret="token-secret", bearer_token=bearer, base_url="https://api.x.com")


def response(payload, status=200, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def transport(monkeypatch):
    request = Mock(return_value=response({"data": []}))
    monkeypatch.setattr("x_cli.client.requests.request", request)
    return request


@pytest.fixture
def api():
    return AnalyticsClient(config=config(), max_retries=0)


def test_post_metrics_preserve_private_and_unknown_fields(api, transport):
    report = {"data": [{"id": "123", "non_public_metrics": {"url_link_clicks": 2, "new_field": 7}}], "includes": {"media": [{"media_key": "13_456", "non_public_metrics": {"playback_25_count": 8}}]}, "errors": [{"resource_id": "124", "detail": "not found"}]}
    transport.return_value = response(report)
    assert api.posts("123,124", "public_metrics,non_public_metrics,organic_metrics,promoted_metrics") == report
    params = transport.call_args.kwargs["params"]
    assert params["ids"] == "123,124"
    assert params["post.fields"] == "created_at,attachments,public_metrics,non_public_metrics,organic_metrics,promoted_metrics"
    assert params["expansions"] == "attachments.media_keys,author_id"
    assert "promoted_metrics" in params["media.fields"]


def test_bearer_only_public_read_needs_no_oauth(transport):
    api = AnalyticsClient(config=config(oauth=False), auth_mode="bearer")
    api.posts("123")
    args = transport.call_args.kwargs
    assert isinstance(args["auth"], requests.auth.AuthBase)
    assert args["headers"]["Authorization"] == "Bearer test-bearer"
    assert args["timeout"] == 60
    assert args["allow_redirects"] is False
    with pytest.raises(ClientError, match="require OAuth"):
        api.posts("123", "organic_metrics")


def test_existing_default_client_still_requires_oauth():
    with pytest.raises(ClientError, match="Missing credentials"):
        XClient(config=config(oauth=False))
    with pytest.raises(ClientError, match="Missing X_BEARER_TOKEN"):
        AnalyticsClient(config=config(bearer=None), auth_mode="bearer")


@pytest.mark.parametrize("ids", ["", "12,", "a", "12,12", ",".join(str(i) for i in range(101)), "123/../usage"])
def test_invalid_ids_do_not_call_api(api, transport, ids):
    with pytest.raises(ClientError):
        api.posts(ids)
    transport.assert_not_called()


def test_media_lookup(api, transport):
    api.media("13_123,16_456", "public_metrics,organic_metrics")
    assert transport.call_args.kwargs["url"] == "https://api.x.com/2/media"
    assert transport.call_args.kwargs["params"]["media_keys"] == "13_123,16_456"


@pytest.mark.parametrize("kind,ids,granularity,field_name,expected", [("posts", "123", "weekly", "analytics.fields", POST_ANALYTICS_FIELDS), ("media", "13_123", "daily", "media_analytics.fields", MEDIA_ANALYTICS_FIELDS)])
def test_series_requests_all_documented_fields(api, transport, kind, ids, granularity, field_name, expected):
    api.series(kind, ids, START, END, granularity, None)
    assert transport.call_args.kwargs["params"][field_name] == expected
    assert transport.call_args.kwargs["params"]["start_time"] == START
    assert transport.call_args.kwargs["params"]["end_time"] == END


def test_series_rejects_weekly_media_and_app_auth(api, transport):
    with pytest.raises(ClientError, match="granularity"):
        api.series("media", "13_123", START, END, "weekly", None)
    with pytest.raises(ClientError, match="user authentication"):
        AnalyticsClient(config=config(), auth_mode="bearer").series("posts", "123", START, END, "daily", None)
    transport.assert_not_called()


@pytest.mark.parametrize("start,end", [(END, START), (START, START), ("2026-10-01", END), ("bad", END)])
def test_series_invalid_time_range(api, transport, start, end):
    with pytest.raises(ClientError):
        api.series("posts", "123", start, end, "daily", None)
    transport.assert_not_called()


def test_timeline_preserves_page_and_forwards_token(api, transport):
    report = {"data": [{"id": "123"}], "meta": {"next_token": "next"}}
    transport.return_value = response(report)
    assert api.timeline("12", "public_metrics", 5, START, END, "previous", "replies") == report
    args = transport.call_args.kwargs
    assert args["params"]["pagination_token"] == "previous"
    assert args["params"]["max_results"] == 5
    assert transport.call_count == 1


def test_user_lookup_selectors(api, transport):
    api.user(username="@example")
    assert transport.call_args.kwargs["url"].endswith("/2/users/by/username/example")
    assert "public_metrics" in transport.call_args.kwargs["params"]["user.fields"]
    with pytest.raises(ClientError, match="either"):
        api.user("123", "example")


def test_counts_archive_and_usage_bearer(transport):
    api = AnalyticsClient(config=config(oauth=False), auth_mode="bearer")
    api.counts("from:example", True, START, END, "day", "cursor", "123", "456")
    assert transport.call_args.kwargs["url"].endswith("/2/tweets/counts/all")
    assert transport.call_args.kwargs["params"]["next_token"] == "cursor"
    api.usage(90)
    assert transport.call_args.kwargs["params"]["days"] == 90
    assert "daily_client_app_usage" in transport.call_args.kwargs["params"]["usage.fields"]
    api.usage(credits=True)
    assert transport.call_args.kwargs["url"].endswith("/2/usage/credits")


def test_ads_sync_and_async_request_contract(api, transport):
    api.ads_report("abc", "CAMPAIGN", "def,ghi", START, END, "TOTAL", "ENGAGEMENT,VIDEO", "TREND")
    args = transport.call_args.kwargs
    assert args["url"] == "https://ads-api.x.com/12/stats/accounts/abc"
    assert args["method"] == "GET"
    assert args["auth"] is api.oauth
    api.ads_report("abc", "CAMPAIGN", "def", START, END, "HOUR", "ENGAGEMENT", "ALL_ON_TWITTER", asynchronous=True, segmentation="REGIONS", country="country-id")
    args = transport.call_args.kwargs
    assert args["url"] == "https://ads-api.x.com/12/stats/jobs/accounts/abc"
    assert args["method"] == "POST"
    assert args["params"]["segmentation_type"] == "REGIONS"
    assert args["params"]["country"] == "country-id"


@pytest.mark.parametrize("changes,match", [({"end": "2026-10-09T00:00:00Z"}, "7 days"), ({"start": "2026-10-01T00:01:00Z"}, "whole hours"), ({"asynchronous": True, "segmentation": "REGIONS"}, "requires --country"), ({"asynchronous": True, "segmentation": "CONVERSION_TAGS"}, "WEB_CONVERSION"), ({"metrics": "MOBILE_CONVERSION,ENGAGEMENT"}, "separately"), ({"asynchronous": True, "segmentation": "AGE", "end": "2026-12-01T00:00:00Z"}, "45 days")])
def test_ads_invalid_ranges_and_groups(api, transport, changes, match):
    kwargs = dict(account="abc", entity="CAMPAIGN", ids="def", start=START, end=END, granularity="TOTAL", metrics="ENGAGEMENT", placement="ALL_ON_TWITTER")
    kwargs.update(changes)
    with pytest.raises(ClientError, match=match):
        api.ads_report(**kwargs)
    transport.assert_not_called()


def test_ads_report_creation_never_retries(transport):
    transport.return_value = response({"error": "busy"}, 503)
    with pytest.raises(ClientError, match="503"):
        AnalyticsClient(config=config()).ads_report("abc", "CAMPAIGN", "def", START, END, "TOTAL", "ENGAGEMENT", "ALL_ON_TWITTER", asynchronous=True)
    assert transport.call_count == 1


def test_ads_active_reach_jobs(api, transport):
    api.ads_active("abc", "LINE_ITEM", START, END, campaigns="def")
    assert transport.call_args.kwargs["params"]["campaign_ids"] == "def"
    with pytest.raises(ClientError, match="one entity scope"):
        api.ads_active("abc", "LINE_ITEM", START, END, campaigns="def", funding="ghi")
    api.ads_reach("abc", "def", START, END, funding=True)
    assert transport.call_args.kwargs["url"].endswith("/reach/funding_instruments")
    api.ads_jobs("abc", "123,456")
    assert transport.call_args.kwargs["params"] == {"job_ids": "123,456"}


def test_rate_limit_reset_not_capped_or_retried_early(transport, monkeypatch):
    monkeypatch.setattr("x_cli.client.time.time", lambda: 1000)
    sleep = Mock()
    monkeypatch.setattr("x_cli.client.time.sleep", sleep)
    transport.return_value = response({}, 429, {"x-rate-limit-reset": "1120", "Retry-After": "30"})
    with pytest.raises(ClientError, match="120 seconds"):
        AnalyticsClient(config=config()).posts("123")
    assert transport.call_count == 1
    sleep.assert_not_called()


def test_short_server_retry_wait_honored(transport, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("x_cli.client.time.sleep", sleep)
    transport.side_effect = [response({}, 503, {"Retry-After": "2"}), response({"data": []})]
    AnalyticsClient(config=config()).posts("123")
    sleep.assert_called_once_with(2)


def test_transport_rejects_redirect_instead_of_leaking_credentials(transport):
    transport.return_value = response({}, 302)
    with pytest.raises(ClientError, match="302"):
        AnalyticsClient(config=config()).posts("123")


def test_download_checks_job_and_never_sends_api_auth(api, monkeypatch):
    api.ads_jobs = Mock(return_value={"data": [{"id_str": "123", "status": "SUCCESS", "url": "https://ton.twimg.com/advertiser-api-async-analytics/report.json.gz"}]})
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.get.return_value = SimpleNamespace(status_code=200, content=gzip.compress(b'{"data": [{"id": "def"}]}'))
    monkeypatch.setattr("x_cli.analytics.requests.Session", lambda: session)
    assert api.ads_download("abc", "123") == {"data": [{"id": "def"}]}
    assert session.trust_env is False
    assert session.get.call_args.kwargs == {"timeout": 60, "allow_redirects": False}


@pytest.mark.parametrize("url", ["http://ton.twimg.com/advertiser-api-async-analytics/a", "https://evil.example/a", "https://ton.twimg.com.evil.example/advertiser-api-async-analytics/a", "https://user:pass@ton.twimg.com/advertiser-api-async-analytics/a", "https://ton.twimg.com/other/a", "https://ton.twimg.com:444/advertiser-api-async-analytics/a", "https://ton.twimg.com:bad/advertiser-api-async-analytics/a", "https://[bad"])
def test_download_rejects_untrusted_url(api, url):
    api.ads_jobs = Mock(return_value={"data": [{"id": 123, "status": "SUCCESS", "url": url}]})
    with pytest.raises(ClientError, match="unsupported download URL"):
        api.ads_download("abc", "123")


def test_download_not_ready(api):
    api.ads_jobs = Mock(return_value={"data": [{"id_str": "123", "status": "PROCESSING"}]})
    with pytest.raises(ClientError, match="PROCESSING"):
        api.ads_download("abc", "123")


def test_cli_partial_errors_keep_data_and_exit_nonzero(monkeypatch):
    report = {"data": [{"id": "123"}], "errors": [{"detail": "private metrics unavailable"}]}
    fake = SimpleNamespace(posts=lambda *args: report)
    monkeypatch.setattr(analytics, "client", lambda *args: fake)
    result = CliRunner().invoke(analytics.app, ["posts", "123"])
    assert result.exit_code == 1
    assert json.loads(result.stdout) == report
    assert "partial" in result.stderr


def test_cli_profile_auth_and_table(monkeypatch):
    monkeypatch.setattr("cli_tools_shared.command_registry._resolve_runtime_profile_context", lambda *args, **kwargs: ("work", "custom"))
    factory = Mock(return_value=SimpleNamespace(posts=lambda *args: {"data": [{"id": "123"}]}))
    monkeypatch.setattr(analytics, "client", factory)
    result = CliRunner().invoke(analytics.app, ["posts", "123", "--profile", "work", "--auth-mode", "bearer", "--table"])
    assert result.exit_code == 0
    factory.assert_called_once_with("work", "bearer")
    assert "123" in result.stdout


@pytest.mark.parametrize("name", ["posts", "media", "user", "timeline", "post-series", "media-series", "counts", "usage", "credits", "ads-stats", "ads-job-create", "ads-jobs", "ads-download", "ads-active", "ads-reach", "ads-accounts"])
def test_every_analytics_command_help(name):
    result = CliRunner().invoke(analytics.app, [name, "--help"])
    assert result.exit_code == 0
    assert "--profile" in result.stdout
    assert "--table" in result.stdout


def test_cli_resolves_api_profile_when_browser_is_active(monkeypatch):
    configured = config()
    resolve = Mock(return_value=configured)
    constructor = Mock()
    monkeypatch.setattr(analytics, "get_config", resolve)
    monkeypatch.setattr(analytics, "AnalyticsClient", constructor)
    analytics.client(None)
    resolve.assert_called_once_with(profile=None, profile_auth_type="custom")
    constructor.assert_called_once_with(config=configured, auth_mode="oauth1")


def test_ads_account_discovery_preserves_cursor(api, transport):
    report = {"data": [{"id": "abc", "timezone": "America/Chicago"}], "next_cursor": "next"}
    transport.return_value = response(report)
    assert api.ads_accounts(10, "previous", "Example", "abc", True) == report
    assert transport.call_args.kwargs["url"] == "https://ads-api.x.com/12/accounts"
    assert transport.call_args.kwargs["params"] == {"count": 10, "cursor": "previous", "q": "Example", "account_ids": "abc", "with_deleted": "true"}


def test_bearer_auth_cannot_be_replaced_by_netrc(transport, monkeypatch):
    monkeypatch.setattr("requests.sessions.get_netrc_auth", lambda url: ("netrc-user", "netrc-password"))
    AnalyticsClient(config=config(oauth=False), auth_mode="bearer").posts("123")
    args = transport.call_args.kwargs
    prepared = requests.Session().prepare_request(requests.Request(method="GET", url=args["url"], headers=args["headers"], auth=args["auth"]))
    assert prepared.headers["Authorization"] == "Bearer test-bearer"


def test_truncated_gzip_becomes_client_error(api, monkeypatch):
    api.ads_jobs = Mock(return_value={"data": [{"id_str": "123", "status": "SUCCESS", "url": "https://ton.twimg.com/advertiser-api-async-analytics/a.gz"}]})
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.get.return_value = SimpleNamespace(status_code=200, content=gzip.compress(b'{"data": []}')[:-3])
    monkeypatch.setattr("x_cli.analytics.requests.Session", lambda: session)
    with pytest.raises(ClientError, match="EOFError"):
        api.ads_download("abc", "123")


def test_bearer_mode_cannot_mutate(transport):
    with pytest.raises(ClientError, match="read-only"):
        XClient(config=config(), auth_mode="bearer").post_tweet("hello")
    transport.assert_not_called()


def test_analytics_credential_metadata_covers_every_command():
    names = {info.name or info.callback.__name__.replace("_", "-") for info in analytics.app.registered_commands}
    assert set(analytics.COMMAND_CREDENTIALS) == names
    assert all(types == ["custom"] for types in analytics.COMMAND_CREDENTIALS.values())


def test_bearer_cli_usage_accepts_no_oauth_credentials(monkeypatch, transport):
    monkeypatch.setattr(analytics, "get_config", lambda **kwargs: config(oauth=False))
    result = CliRunner().invoke(analytics.app, ["usage", "--days", "1"])
    assert result.exit_code == 0, result.stderr
    assert transport.call_args.kwargs["headers"]["Authorization"] == "Bearer test-bearer"

import json

import pytest
from cli_tools_shared.exceptions import ClientError
from typer.testing import CliRunner

from clipster_cli.client import USER_AGENT, ClipsterClient
from clipster_cli.main import app

WEB_URL = "https://www.clipster.gg/discover?openedCampaignId=%s"


class FakeConfig:
    base_url = "https://api.clipster.gg"

    def __init__(self, storage_dir):
        self.storage_dir = storage_dir


class FakeResponse:
    ok = True
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def campaign(index):
    return {"id": f"c{index}", "name": f"Campaign {index}", "status": "CAMPAIGN_STATUS_ACTIVE",
            "statistics": {"total_approved": 0}}


def document(rows, page, total_pages):
    return {"success": True, "data": {"campaigns": rows},
            "metadata": {"pagination": {"page": page, "total_pages": total_pages}}}


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "false")


@pytest.fixture
def catalog(monkeypatch):
    """Serve 250 campaigns, paged by the requested limit, and record every request."""
    rows = [campaign(i) for i in range(250)]
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append({"url": url, "headers": headers, "params": params})
        size, page = params["limit"], params["page"]
        total_pages = -(-len(rows) // size)
        return FakeResponse(document(rows[(page - 1) * size:page * size], page, total_pages))

    monkeypatch.setattr("clipster_cli.client.requests.get", fake_get)
    return calls


def client(tmp_path):
    return ClipsterClient(config=FakeConfig(tmp_path))


def test_list_reads_every_page_and_stops_at_total_pages(monkeypatch, tmp_path):
    pages = {1: [campaign(0)], 2: [campaign(1)]}
    seen = []

    def fake_get(url, headers, params, timeout):
        seen.append(params)
        return FakeResponse(document(pages[params["page"]], params["page"], 2))

    monkeypatch.setattr("clipster_cli.client.requests.get", fake_get)
    rows = client(tmp_path).list_campaigns(limit=100)

    assert [row["id"] for row in rows] == ["c0", "c1"]
    assert seen == [{"page": 1, "limit": 100}, {"page": 2, "limit": 100}]


def test_list_adds_web_url_and_keeps_every_api_field(catalog, tmp_path):
    row = client(tmp_path).list_campaigns(limit=1)[0]

    assert row == {**campaign(0), "web_url": WEB_URL % "c0"}


def test_list_limit_spans_pages_and_is_not_exceeded(monkeypatch, tmp_path):
    rows = [campaign(i) for i in range(250)]
    seen = []

    def fake_get(url, headers, params, timeout):
        seen.append(params)
        start = (params["page"] - 1) * params["limit"]
        return FakeResponse(document(rows[start:start + params["limit"]], params["page"], 3))

    monkeypatch.setattr("clipster_cli.client.requests.get", fake_get)
    result = client(tmp_path).list_campaigns(limit=150)

    assert len(result) == 150
    assert [params["page"] for params in seen] == [1, 2]


def test_list_small_limit_is_sent_as_the_page_size(catalog, tmp_path):
    rows = client(tmp_path).list_campaigns(limit=3)

    assert len(rows) == 3
    assert [call["params"] for call in catalog] == [{"page": 1, "limit": 3}]


def test_requests_send_explicit_user_agent_and_accept(catalog, tmp_path):
    client(tmp_path).list_campaigns(limit=1)

    headers = catalog[0]["headers"]
    assert headers["User-Agent"] == USER_AGENT
    assert headers["Accept"] == "application/json"
    assert catalog[0]["url"] == "https://api.clipster.gg/campaigns/public"


@pytest.mark.parametrize("payload", [
    {"success": False, "data": None},
    {"data": {"campaigns": {"id": "c0"}}},
    {"data": {}},
    ["not", "an", "object"],
])
def test_non_list_campaigns_is_a_client_error(monkeypatch, tmp_path, payload):
    monkeypatch.setattr("clipster_cli.client.requests.get", lambda *a, **k: FakeResponse(payload))

    with pytest.raises(ClientError, match="did not return a list"):
        client(tmp_path).list_campaigns(limit=10)


def test_row_without_id_is_a_client_error(monkeypatch, tmp_path):
    monkeypatch.setattr("clipster_cli.client.requests.get",
                        lambda *a, **k: FakeResponse(document([{"name": "no id"}], 1, 1)))

    with pytest.raises(ClientError, match="no id"):
        client(tmp_path).list_campaigns(limit=10)


@pytest.mark.parametrize("limit", [0, -1])
def test_limit_below_one_is_a_client_error(catalog, tmp_path, limit):
    with pytest.raises(ClientError, match="at least 1"):
        client(tmp_path).list_campaigns(limit=limit)
    assert catalog == []


def test_http_error_is_a_client_error(monkeypatch, tmp_path):
    class Forbidden(FakeResponse):
        ok = False
        status_code = 403

    monkeypatch.setattr("clipster_cli.client.requests.get", lambda *a, **k: Forbidden({"error": "blocked"}))

    with pytest.raises(ClientError, match="HTTP 403"):
        client(tmp_path).list_campaigns(limit=10)


def test_retryable_status_is_retried_with_backoff(monkeypatch, tmp_path):
    class Unavailable(FakeResponse):
        ok = False
        status_code = 503

    answers = [Unavailable({}), FakeResponse(document([campaign(0)], 1, 1))]
    sleeps = []
    monkeypatch.setattr("clipster_cli.client.requests.get", lambda *a, **k: answers.pop(0))
    monkeypatch.setattr("clipster_cli.client.time.sleep", sleeps.append)

    assert len(client(tmp_path).list_campaigns(limit=10)) == 1
    assert len(sleeps) == 1


def test_get_finds_a_row_on_a_later_page(catalog, tmp_path):
    row = client(tmp_path).get_campaign("c249")

    assert row == {**campaign(249), "web_url": WEB_URL % "c249"}
    assert [call["params"]["page"] for call in catalog] == [1, 2, 3]


def test_get_missing_id_is_a_client_error(catalog, tmp_path):
    with pytest.raises(ClientError, match="Campaign not found: nope"):
        client(tmp_path).get_campaign("nope")


class FakeClient:
    def __init__(self):
        self.rows = [{**campaign(i), "web_url": WEB_URL % f"c{i}"} for i in range(3)]

    def list_campaigns(self, limit):
        self.limit = limit
        return self.rows[:limit]

    def get_campaign(self, campaign_id):
        return next(row for row in self.rows if row["id"] == campaign_id)


def test_campaigns_list_outputs_json(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr("clipster_cli.main.get_client", lambda: fake)

    result = CliRunner().invoke(app, ["campaigns", "list", "--limit", "2"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == fake.rows[:2]
    assert fake.limit == 2


def test_campaigns_list_defaults_to_limit_100_and_filters(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr("clipster_cli.main.get_client", lambda: fake)

    result = CliRunner().invoke(app, ["campaigns", "list", "--filter", "id:eq:c1", "--properties", "id,web_url"])

    assert result.exit_code == 0, result.output
    assert fake.limit == 100
    assert json.loads(result.stdout) == [{"id": "c1", "web_url": WEB_URL % "c1"}]


def test_campaigns_get_outputs_json(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr("clipster_cli.main.get_client", lambda: fake)

    result = CliRunner().invoke(app, ["campaigns", "get", "c2"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == fake.rows[2]


def test_campaigns_get_missing_id_exits_nonzero(monkeypatch, catalog, tmp_path):
    monkeypatch.setattr("clipster_cli.main.get_client", lambda: client(tmp_path))

    result = CliRunner().invoke(app, ["campaigns", "get", "nope"])

    assert result.exit_code != 0
    assert result.stdout == ""

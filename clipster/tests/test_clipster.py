import json

import pytest
from cli_tools_shared.exceptions import ClientError, CredentialError
from dotenv import dotenv_values, set_key
from typer.testing import CliRunner

from clipster_cli import client as client_module
from clipster_cli.client import USER_AGENT, ClipsterClient
from clipster_cli.main import app

WEB_URL = "https://www.clipster.gg/discover?openedCampaignId=%s"
BASE = "https://api.clipster.gg"
TIKTOK = "SOCIAL_MEDIA_PLATFORM_TIKTOK"
POST = "https://www.tiktok.com/@ata_clipper/video/7696592655307787533"
FUTURE = "2099-01-01T00:00:00.123456789Z"
PAST = "2020-01-01T00:00:00Z"


class FakeConfig:
    base_url = BASE

    def __init__(self, tmp_path, email="clipping@example.com"):
        self.storage_dir = tmp_path
        self.env_file_path = tmp_path / ".env"
        self.env_file_path.touch()
        self.email = email

    def get_profile_data_dir(self):
        return self.storage_dir

    def _get(self, name):
        return self.email if name == "EMAIL" else None

    def _set(self, name, value):
        set_key(str(self.env_file_path), name, value)


class FakeResponse:
    headers = {}

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def ok(data, pagination=None):
    return FakeResponse({"success": True, "data": data, "metadata": {"pagination": pagination or {}}})


def fail(status, code="UNAUTHORIZED", message="Invalid or expired token"):
    return FakeResponse({"success": False, "error": {"code": code, "message": message}}, status)


def campaign(index):
    return {"id": f"c{index}", "name": f"Campaign {index}", "status": "CAMPAIGN_STATUS_ACTIVE",
            "statistics": {"total_approved": 0}}


def document(rows, page, total_pages):
    return {"success": True, "data": {"campaigns": rows},
            "metadata": {"pagination": {"page": page, "total_pages": total_pages}}}


class Server:
    """Route fake HTTP calls by (method, path) and record each one."""

    def __init__(self, monkeypatch, routes):
        self.routes = routes
        self.calls = []
        monkeypatch.setattr("clipster_cli.client.requests.request", self)

    def __call__(self, method, url, headers, params, json, timeout):
        path = url[len(BASE):]
        self.calls.append({"method": method, "path": path, "headers": headers, "params": params, "body": json})
        answer = self.routes[(method, path)]
        return answer(self.calls[-1]) if callable(answer) else (answer.pop(0) if isinstance(answer, list) else answer)

    def paths(self, method=None):
        return [call["path"] for call in self.calls if method is None or call["method"] == method]


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "false")


def make_client(tmp_path, tokens=None):
    config = FakeConfig(tmp_path)
    for name, value in (tokens or {}).items():
        set_key(str(config.env_file_path), name, value)
    return ClipsterClient(config=config)


def signed_in(tmp_path, expires=FUTURE):
    return make_client(tmp_path, {"ACCESS_TOKEN": "access-1", "REFRESH_TOKEN": "refresh-1",
                                  "TOKEN_EXPIRES_AT": expires, "REFRESH_EXPIRES_AT": FUTURE})


SESSION = {"access_token": "access-2", "refresh_token": "refresh-2", "expires_at": FUTURE,
           "refresh_expires_at": FUTURE, "action": "LOGIN", "account_type": "creator"}
USER = {"user": {"id": "u1", "email": "clipping@example.com", "username": "ataclipper"}, "bio_linking_enabled": False}


# ==================== public catalog ====================

def catalog_server(monkeypatch, rows, total_pages=None):
    def page(call):
        size, number = call["params"]["limit"], call["params"]["page"]
        pages = total_pages or -(-len(rows) // size)
        return FakeResponse(document(rows[(number - 1) * size:number * size], number, pages))
    return Server(monkeypatch, {("GET", "/campaigns/public"): page})


def test_list_reads_every_page_until_the_limit(monkeypatch, tmp_path):
    server = catalog_server(monkeypatch, [campaign(i) for i in range(250)])
    rows = make_client(tmp_path).list_campaigns(limit=150)

    assert len(rows) == 150
    assert [call["params"] for call in server.calls] == [{"page": 1, "limit": 100}, {"page": 2, "limit": 100}]


def test_list_adds_web_url_and_sends_explicit_headers(monkeypatch, tmp_path):
    server = catalog_server(monkeypatch, [campaign(0)])
    row = make_client(tmp_path).list_campaigns(limit=1)[0]

    assert row == {**campaign(0), "web_url": WEB_URL % "c0"}
    headers = server.calls[0]["headers"]
    assert headers["User-Agent"] == USER_AGENT and headers["X-Fee-Model"] == "v2"
    assert "Authorization" not in headers


@pytest.mark.parametrize("payload", [{"success": False, "data": None}, {"data": {"campaigns": {"id": "c0"}}}])
def test_non_list_campaigns_is_a_client_error(monkeypatch, tmp_path, payload):
    Server(monkeypatch, {("GET", "/campaigns/public"): FakeResponse(payload)})
    with pytest.raises(ClientError, match="did not return a list"):
        make_client(tmp_path).list_campaigns(limit=10)


@pytest.mark.parametrize("limit", [0, -1])
def test_limit_below_one_is_a_client_error(monkeypatch, tmp_path, limit):
    server = catalog_server(monkeypatch, [campaign(0)])
    with pytest.raises(ClientError, match="at least 1"):
        make_client(tmp_path).list_campaigns(limit=limit)
    assert server.calls == []


def test_get_is_retried_but_a_write_is_never_repeated(monkeypatch, tmp_path):
    sleeps = []
    monkeypatch.setattr("clipster_cli.client.time.sleep", sleeps.append)
    server = Server(monkeypatch, {
        ("GET", "/campaigns/public"): [fail(503, "X", "down"), FakeResponse(document([campaign(0)], 1, 1))],
        ("POST", "/auth/initialize"): fail(503, "X", "down"),
    })
    client = make_client(tmp_path)
    assert len(client.list_campaigns(limit=1)) == 1
    with pytest.raises(ClientError, match="HTTP 503 X: down"):
        client._document(client._send("POST", "/auth/initialize", body={}))
    assert server.paths("POST") == ["/auth/initialize"]
    assert len(sleeps) == 1


# ==================== login and session ====================

def gmail(monkeypatch, searches, body="Your authentication code (OTP) is 123456 This code expires"):
    calls = []

    def fake_google(*args):
        calls.append(args)
        if args[1] == "search":
            return json.dumps([{"id": i} for i in searches.pop(0)])
        return json.dumps({"body": body})

    monkeypatch.setattr(client_module, "_google", fake_google)
    monkeypatch.setattr("clipster_cli.client.time.sleep", lambda s: None)
    return calls


def test_login_requests_code_reads_only_the_new_email_and_saves_session(monkeypatch, tmp_path):
    google_calls = gmail(monkeypatch, [["old"], ["old"], ["new", "old"]])
    server = Server(monkeypatch, {
        ("POST", "/auth/initialize"): ok({"auth_id": "A1"}),
        ("POST", "/auth/finalize"): ok(SESSION),
    })
    client = make_client(tmp_path)

    assert client.login() == "access-2"
    assert server.calls[0]["body"] == {"email": "clipping@example.com", "user_kind": "Creator"}
    assert server.calls[1]["body"] == {"auth_id": "A1", "code": "123456"}
    assert [args for args in google_calls if args[1] == "read"] == [("gmail", "read", "new")]
    saved = dotenv_values(client.config.env_file_path)
    assert saved["ACCESS_TOKEN"] == "access-2" and saved["REFRESH_TOKEN"] == "refresh-2"
    assert oct(client.config.env_file_path.stat().st_mode & 0o777) == "0o600"


def test_login_rejects_a_non_creator_account(monkeypatch, tmp_path):
    gmail(monkeypatch, [[], ["new"]])
    Server(monkeypatch, {("POST", "/auth/initialize"): ok({"auth_id": "A1"}),
                         ("POST", "/auth/finalize"): ok({**SESSION, "account_type": "advertiser"})})
    with pytest.raises(CredentialError, match="not a Clipster creator account"):
        make_client(tmp_path).login()


def test_login_without_email_fails_before_any_request(monkeypatch, tmp_path):
    server = Server(monkeypatch, {})
    client = make_client(tmp_path)
    client.config.email = None
    with pytest.raises(CredentialError, match="auth login"):
        client.login()
    assert server.calls == []


def test_expired_access_token_is_refreshed_before_the_call(monkeypatch, tmp_path):
    server = Server(monkeypatch, {("POST", "/auth/refresh"): ok(SESSION), ("GET", "/auth/identify"): ok(USER)})
    client = signed_in(tmp_path, expires=PAST)

    assert client.account()["email"] == "clipping@example.com"
    assert server.calls[0]["body"] == {"refresh_token": "refresh-1"}
    assert server.calls[1]["headers"]["Authorization"] == "Bearer access-2"


def test_401_refreshes_once_and_retries(monkeypatch, tmp_path):
    server = Server(monkeypatch, {("GET", "/auth/identify"): [fail(401), ok(USER)],
                                  ("POST", "/auth/refresh"): ok(SESSION)})
    signed_in(tmp_path).account()

    assert server.paths() == ["/auth/identify", "/auth/refresh", "/auth/identify"]


def test_rejected_refresh_falls_back_to_passcode_login(monkeypatch, tmp_path):
    gmail(monkeypatch, [[], ["new"]])
    server = Server(monkeypatch, {
        ("GET", "/auth/identify"): [fail(401), ok(USER)],
        ("POST", "/auth/refresh"): fail(401, "AUTH_BAD_REFRESH_TOKEN"),
        ("POST", "/auth/initialize"): ok({"auth_id": "A1"}),
        ("POST", "/auth/finalize"): ok(SESSION),
    })
    signed_in(tmp_path).account()

    assert server.paths("POST") == ["/auth/refresh", "/auth/initialize", "/auth/finalize"]


def test_status_check_never_sends_a_passcode(monkeypatch, tmp_path):
    server = Server(monkeypatch, {("GET", "/auth/identify"): fail(401),
                                  ("POST", "/auth/refresh"): fail(401, "AUTH_BAD_REFRESH_TOKEN")})
    with pytest.raises(CredentialError, match="auth login"):
        signed_in(tmp_path).account(allow_login=False)
    assert "/auth/initialize" not in server.paths()


def test_transient_refresh_failure_keeps_the_session(monkeypatch, tmp_path):
    server = Server(monkeypatch, {("POST", "/auth/refresh"): fail(503, "X", "down")})
    with pytest.raises(ClientError, match="HTTP 503"):
        signed_in(tmp_path, expires=PAST).account()
    assert server.paths() == ["/auth/refresh"]


def test_token_rotated_by_another_process_is_used_without_refreshing(monkeypatch, tmp_path):
    server = Server(monkeypatch, {("GET", "/auth/identify"): ok(USER)})
    client = signed_in(tmp_path)
    set_key(str(client.config.env_file_path), "ACCESS_TOKEN", "access-from-peer")

    assert client._renew("access-1", allow_login=False) == "access-from-peer"
    assert server.calls == []


# ==================== creator reads ====================

def test_account_flattens_user_and_flags(monkeypatch, tmp_path):
    Server(monkeypatch, {("GET", "/auth/identify"): ok(USER)})
    assert signed_in(tmp_path).account() == {**USER["user"], "bio_linking_enabled": False}


def test_submissions_page_through_and_filter_by_campaign(monkeypatch, tmp_path):
    pages = {1: [{"id": "s1"}], 2: [{"id": "s2"}]}
    server = Server(monkeypatch, {("GET", "/submissions/submission-requests"): lambda call: ok(
        {"submissions_with_requests": pages[call["params"]["page"]]}, {"total_pages": 2})})

    rows = signed_in(tmp_path).submissions("c1", limit=None)

    assert [row["id"] for row in rows] == ["s1", "s2"]
    assert server.calls[0]["params"] == {"campaign_id": "c1", "page": 1, "limit": 20}


def test_earnings_merges_balance_and_statistics(monkeypatch, tmp_path):
    Server(monkeypatch, {("GET", "/balance"): ok({"campaign_balance": "1.00"}),
                         ("GET", "/users/statistics"): ok({"total_views": 5})})
    assert signed_in(tmp_path).earnings() == {"campaign_balance": "1.00", "total_views": 5}


# ==================== campaigns and submissions ====================

ACCOUNT = {"account_id": "a1", "platform": TIKTOK, "username": "ata_clipper", "oauth_connected": True}


def campaign_detail(**overrides):
    return {"id": "c1", "status": "CAMPAIGN_STATUS_ACTIVE", "allowed_platforms": [TIKTOK],
            "disable_dashboard_submissions": False, "is_application_only": False, **overrides}


def eligibility(eligible=True, application=None):
    return {"application": application, "accounts": [{"account_id": "a1", "eligible": eligible}]}


def submission_server(monkeypatch, rows=None, detail=None, elig=None, post=None):
    rows = rows if rows is not None else []
    return Server(monkeypatch, {
        ("GET", "/submissions/submission-requests"): lambda call: ok(
            {"submissions_with_requests": list(rows)}, {"total_pages": 1}),
        ("GET", "/campaigns/c1"): ok(detail or campaign_detail()),
        ("GET", "/campaigns/c1/account-eligibility"): ok(elig or eligibility()),
        ("GET", "/accounts"): ok([ACCOUNT], {"total_pages": 1}),
        ("POST", "/campaigns/c1/submissions-async"): post or (lambda call: rows.append(
            {"id": "s9", "campaign_id": "c1", "post_url": POST + "?utm_source=x"}) or ok({"accepted": True})),
    })


def test_campaign_get_adds_web_url_and_account_eligibility(monkeypatch, tmp_path):
    submission_server(monkeypatch)
    row = signed_in(tmp_path).get_campaign("c1")
    assert row["web_url"] == WEB_URL % "c1" and row["account_eligibility"] == eligibility()


def test_existing_url_is_returned_without_posting(monkeypatch, tmp_path):
    existing = {"id": "s1", "campaign_id": "c1", "post_url": POST + "?utm_campaign=tt4d", "status": "processing"}
    server = submission_server(monkeypatch, rows=[existing])

    result = signed_in(tmp_path).create_submission("c1", "https://tiktok.com/@ATA_clipper/video/7696592655307787533", False)

    assert result == {"status": "existing", "submission": existing, "url": POST}
    assert server.paths("POST") == []


def test_dry_run_returns_the_exact_request_without_posting(monkeypatch, tmp_path):
    server = submission_server(monkeypatch)
    result = signed_in(tmp_path).create_submission("c1", POST, True)

    assert result["status"] == "dry_run"
    assert result["request"] == {"method": "POST", "url": f"{BASE}/campaigns/c1/submissions-async",
                                 "body": {"campaign_id": "c1", "content_list": [{"content_url": POST}]}}
    assert server.paths("POST") == []


def test_create_posts_once_and_returns_the_native_record(monkeypatch, tmp_path):
    server = submission_server(monkeypatch)
    result = signed_in(tmp_path).create_submission("c1", POST, False)

    assert result["status"] == "created" and result["submission"]["id"] == "s9"
    assert result["response"] == {"accepted": True}
    assert server.paths("POST") == ["/campaigns/c1/submissions-async"]


def test_failed_write_that_committed_is_reported_as_created(monkeypatch, tmp_path):
    rows = []

    def commit_then_fail(call):
        rows.append({"id": "s9", "campaign_id": "c1", "post_url": POST})
        return fail(500, "INTERNAL", "boom")

    submission_server(monkeypatch, rows=rows, post=commit_then_fail)
    assert signed_in(tmp_path).create_submission("c1", POST, False)["submission"]["id"] == "s9"


@pytest.mark.parametrize("detail,elig,url,reason", [
    (None, None, "https://www.tiktok.com/@someone/video/1", "tiktok_account_not_linked"),
    (campaign_detail(status="CAMPAIGN_STATUS_COMPLETED"), None, POST, "campaign_not_active"),
    (campaign_detail(disable_dashboard_submissions=True), None, POST, "campaign_submissions_closed"),
    (campaign_detail(allowed_platforms=["SOCIAL_MEDIA_PLATFORM_YOUTUBE"]), None, POST, "does_not_accept_tiktok"),
    (campaign_detail(is_application_only=True), None, POST, "application_not_approved"),
    (None, eligibility(eligible=False), POST, "account_not_eligible"),
])
def test_submission_blockers_stop_before_sending(monkeypatch, tmp_path, detail, elig, url, reason):
    server = submission_server(monkeypatch, detail=detail, elig=elig)
    with pytest.raises(ClientError, match=reason):
        signed_in(tmp_path).create_submission("c1", url, True)
    assert server.paths("POST") == []


@pytest.mark.parametrize("url", ["https://vm.tiktok.com/ZMabc/", "http://www.tiktok.com/@a/video/1",
                                 "https://www.tiktok.com/@a"])
def test_only_full_tiktok_post_urls_are_accepted(url):
    with pytest.raises(ClientError, match="full https://www.tiktok.com"):
        client_module.tiktok_post(url)


@pytest.mark.parametrize("detail,elig,status", [
    (campaign_detail(), eligibility(), "not_required"),
    (campaign_detail(is_application_only=True), eligibility(application={"status": "PENDING"}), "existing"),
    (campaign_detail(is_application_only=True), eligibility(), "applied"),
])
def test_join(monkeypatch, tmp_path, detail, elig, status):
    server = submission_server(monkeypatch, detail=detail, elig=elig)
    server.routes[("POST", "/campaigns/c1/applications")] = ok({"status": "PENDING"})

    assert signed_in(tmp_path).join_campaign("c1", dry_run=False)["status"] == status
    assert server.paths("POST") == (["/campaigns/c1/applications"] if status == "applied" else [])


# ==================== CLI ====================

class FakeClient:
    base_url = BASE

    def __init__(self):
        self.rows = [{**campaign(i), "web_url": WEB_URL % f"c{i}"} for i in range(3)]

    def list_campaigns(self, limit):
        self.limit = limit
        return self.rows[:limit]

    def get_campaign(self, campaign_id):
        return next(row for row in self.rows if row["id"] == campaign_id)

    def create_submission(self, campaign_id, url, dry_run):
        return {"status": "dry_run" if dry_run else "created", "submission": None, "url": url}


@pytest.fixture
def fake(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr("clipster_cli.main.get_client", lambda: fake)
    return fake


def test_campaigns_list_filters_and_selects_properties(fake):
    result = CliRunner().invoke(app, ["campaigns", "list", "--filter", "id:eq:c1", "--properties", "id,web_url"])

    assert result.exit_code == 0, result.output
    assert fake.limit == 100
    assert json.loads(result.stdout) == [{"id": "c1", "web_url": WEB_URL % "c1"}]


def test_campaigns_get_outputs_json(fake):
    result = CliRunner().invoke(app, ["campaigns", "get", "c2"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == fake.rows[2]


@pytest.mark.parametrize("args,message", [
    (["submissions", "create", "c1", "--url", POST], "Refusing to submit without --yes or --dry-run"),
    (["submissions", "create", "c1", "--url", POST, "--yes", "--dry-run"], "not both"),
    (["campaigns", "join", "c1"], "Refusing to join a campaign"),
    (["social-accounts", "link", "--platform", "tiktok", "--username", "x"], "Refusing to link an account"),
])
def test_mutations_require_yes_or_dry_run(fake, args, message):
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1
    assert message in result.output and result.stdout == ""


def test_submissions_create_dry_run_outputs_json(fake):
    result = CliRunner().invoke(app, ["submissions", "create", "c1", "--url", POST, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "dry_run"


def test_social_account_get_finds_the_linked_row(monkeypatch, tmp_path):
    Server(monkeypatch, {("GET", "/accounts"): ok([ACCOUNT], {"total_pages": 1})})
    client = signed_in(tmp_path)

    assert client.social_account("a1") == ACCOUNT
    with pytest.raises(ClientError, match="Linked account not found: nope"):
        client.social_account("nope")

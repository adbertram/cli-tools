import json
from types import SimpleNamespace

from typer.testing import CliRunner

from linkedin_cli.main import app


runner = CliRunner()


class FakeClient:
    def __init__(
        self,
        *,
        current_member_urn="urn:li:person:member123",
        linkedin_person_urn=None,
        linkedin_page_urn=None,
    ):
        self.calls = []
        self.current_member_urn = current_member_urn
        self.config = SimpleNamespace(
            linkedin_person_urn=linkedin_person_urn,
            linkedin_page_urn=linkedin_page_urn,
        )

    def get_current_member_urn(self):
        self.calls.append(("get_current_member_urn", {}))
        return self.current_member_urn

    def list_posts(self, **kwargs):
        self.calls.append(("list_posts", kwargs))
        return [{"id": "urn:li:share:1", "author": kwargs["author"], "commentary": "Hello"}]

    def get_post(self, **kwargs):
        self.calls.append(("get_post", kwargs))
        return {
            "id": kwargs["post_urn"],
            "author": kwargs["permission_author"],
            "commentary": "Hello",
        }

    def create_post(self, **kwargs):
        self.calls.append(("create_post", kwargs))
        return {"id": "urn:li:share:1", "author": kwargs["author"], "commentary": kwargs["commentary"]}

    def update_post(self, **kwargs):
        self.calls.append(("update_post", kwargs))
        return {"id": kwargs["post_urn"], "commentary": kwargs["commentary"], "updated": True}

    def delete_post(self, **kwargs):
        self.calls.append(("delete_post", kwargs))
        return {"id": kwargs["post_urn"], "deleted": True}

    def search_posts(self, **kwargs):
        self.calls.append(("search_posts", kwargs))
        return [{"id": "urn:li:share:2", "author": kwargs["author"], "commentary": "Search hit"}]


class FakeConfig:
    def __init__(
        self,
        *,
        name="default",
        scopes=None,
        authenticated=True,
        missing_credentials=None,
        linkedin_person_urn="urn:li:person:configured123",
        linkedin_page_urn="urn:li:organization:555",
    ):
        self.name = name
        self._scopes = scopes or []
        self._authenticated = authenticated
        self._missing_credentials = missing_credentials or []
        self.linkedin_person_urn = linkedin_person_urn
        self.linkedin_page_urn = linkedin_page_urn

    def get_active_profile_name(self):
        return self.name

    def has_api_credentials(self):
        return not self._missing_credentials

    def get_missing_api_credentials(self):
        return self._missing_credentials

    def test_connection(self):
        if not self._authenticated:
            return {"api_test": "failed: token is not active"}
        return {
            "api_test": "passed",
            "token_status": "active",
            "scopes": self._scopes,
        }


def test_root_help_shows_user_and_page_groups():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "user" in result.stdout
    assert "page" in result.stdout
    assert "posts  Manage LinkedIn posts" not in result.stdout


def test_user_posts_list_defaults_to_current_member(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr("linkedin_cli.main.get_client", lambda profile=None: client)

    result = runner.invoke(app, ["user", "posts", "list", "--limit", "1"])

    assert result.exit_code == 0
    assert client.calls == [
        ("get_current_member_urn", {}),
        (
            "list_posts",
            {
                "author": "urn:li:person:member123",
                "limit": 1,
                "start": 0,
                "sort_by": "LAST_MODIFIED",
            },
        ),
    ]
    assert "urn:li:person:member123" in result.stdout


def test_user_posts_list_uses_configured_default_person(monkeypatch):
    client = FakeClient(linkedin_person_urn="urn:li:person:configured123")
    monkeypatch.setattr("linkedin_cli.main.get_client", lambda profile=None: client)

    result = runner.invoke(app, ["user", "posts", "list", "--limit", "1"])

    assert result.exit_code == 0
    assert client.calls == [
        (
            "list_posts",
            {
                "author": "urn:li:person:configured123",
                "limit": 1,
                "start": 0,
                "sort_by": "LAST_MODIFIED",
            },
        ),
    ]
    assert "urn:li:person:configured123" in result.stdout


def test_user_posts_create_uses_explicit_person(monkeypatch):
    client = FakeClient(linkedin_person_urn="urn:li:person:configured123")
    monkeypatch.setattr("linkedin_cli.main.get_client", lambda profile=None: client)

    result = runner.invoke(
        app,
        [
            "user",
            "posts",
            "create",
            "Hello LinkedIn",
            "--person",
            "urn:li:person:abc123",
        ],
    )

    assert result.exit_code == 0
    assert client.calls == [
        (
            "create_post",
            {
                "commentary": "Hello LinkedIn",
                "author": "urn:li:person:abc123",
                "visibility": "PUBLIC",
                "feed_distribution": "MAIN_FEED",
                "disable_reshare": False,
            },
        )
    ]
    assert json.loads(result.stdout)["author"] == "urn:li:person:abc123"


def test_user_posts_get_passes_author_context(monkeypatch):
    client = FakeClient(linkedin_person_urn="urn:li:person:configured123")
    monkeypatch.setattr("linkedin_cli.main.get_client", lambda profile=None: client)

    result = runner.invoke(app, ["user", "posts", "get", "urn:li:share:1"])

    assert result.exit_code == 0
    assert client.calls == [
        (
            "get_post",
            {
                "post_urn": "urn:li:share:1",
                "view_context": "AUTHOR",
                "permission_author": "urn:li:person:configured123",
            },
        )
    ]


def test_user_posts_search_uses_configured_default_person(monkeypatch):
    client = FakeClient(linkedin_person_urn="urn:li:person:configured123")
    monkeypatch.setattr("linkedin_cli.main.get_client", lambda profile=None: client)

    result = runner.invoke(app, ["user", "posts", "search", "launch*", "--limit", "2"])

    assert result.exit_code == 0
    assert client.calls == [
        (
            "search_posts",
            {
                "query": "launch*",
                "author": "urn:li:person:configured123",
                "limit": 2,
            },
        ),
    ]
    assert "urn:li:person:configured123" in result.stdout


def test_page_posts_create_uses_configured_default_page(monkeypatch):
    client = FakeClient(linkedin_page_urn="urn:li:organization:555")
    monkeypatch.setattr("linkedin_cli.main.get_client", lambda profile=None: client)

    result = runner.invoke(app, ["page", "posts", "create", "Page update"])

    assert result.exit_code == 0
    assert client.calls == [
        (
            "create_post",
            {
                "commentary": "Page update",
                "author": "urn:li:organization:555",
                "visibility": "PUBLIC",
                "feed_distribution": "MAIN_FEED",
                "disable_reshare": False,
            },
        )
    ]
    assert json.loads(result.stdout)["author"] == "urn:li:organization:555"


def test_page_posts_get_passes_author_context(monkeypatch):
    client = FakeClient(linkedin_page_urn="urn:li:organization:555")
    monkeypatch.setattr("linkedin_cli.main.get_client", lambda profile=None: client)

    result = runner.invoke(app, ["page", "posts", "get", "urn:li:share:1"])

    assert result.exit_code == 0
    assert client.calls == [
        (
            "get_post",
            {
                "post_urn": "urn:li:share:1",
                "view_context": "AUTHOR",
                "permission_author": "urn:li:organization:555",
            },
        )
    ]


def test_page_posts_list_requires_page_when_no_default(monkeypatch):
    client = FakeClient(linkedin_page_urn=None)
    monkeypatch.setattr("linkedin_cli.main.get_client", lambda profile=None: client)

    result = runner.invoke(app, ["page", "posts", "list"], catch_exceptions=False)

    assert result.exit_code == 1
    assert "Page URN is required" in result.output


def test_user_posts_list_passes_profile_to_client(monkeypatch):
    client = FakeClient()
    requested_profiles = []

    def fake_get_client(profile=None):
        requested_profiles.append(profile)
        return client

    monkeypatch.setattr("linkedin_cli.main.get_client", fake_get_client)

    result = runner.invoke(
        app,
        ["user", "posts", "list", "--profile", "member-app", "--limit", "1"],
    )

    assert result.exit_code == 0
    assert requested_profiles == ["member-app"]
    assert client.calls[1][0] == "list_posts"


def test_page_posts_create_passes_profile_to_client(monkeypatch):
    client = FakeClient(linkedin_page_urn="urn:li:organization:555")
    requested_profiles = []

    def fake_get_client(profile=None):
        requested_profiles.append(profile)
        return client

    monkeypatch.setattr("linkedin_cli.main.get_client", fake_get_client)

    result = runner.invoke(
        app,
        ["page", "posts", "create", "Page update", "--profile", "affiliate-magic-page"],
    )

    assert result.exit_code == 0
    assert requested_profiles == ["affiliate-magic-page"]
    assert client.calls[0][0] == "create_post"
    assert client.calls[0][1]["author"] == "urn:li:organization:555"


def test_user_posts_update_passes_permission_author(monkeypatch):
    client = FakeClient(linkedin_person_urn="urn:li:person:configured123")
    monkeypatch.setattr("linkedin_cli.main.get_client", lambda profile=None: client)

    result = runner.invoke(app, ["user", "posts", "update", "urn:li:share:1", "Updated"])

    assert result.exit_code == 0
    assert client.calls == [
        (
            "update_post",
            {
                "post_urn": "urn:li:share:1",
                "commentary": "Updated",
                "permission_author": "urn:li:person:configured123",
            },
        )
    ]


def test_page_posts_delete_passes_permission_author(monkeypatch):
    client = FakeClient(linkedin_page_urn="urn:li:organization:555")
    monkeypatch.setattr("linkedin_cli.main.get_client", lambda profile=None: client)

    result = runner.invoke(app, ["page", "posts", "delete", "urn:li:share:1"])

    assert result.exit_code == 0
    assert client.calls == [
        (
            "delete_post",
            {
                "post_urn": "urn:li:share:1",
                "permission_author": "urn:li:organization:555",
            },
        )
    ]


def test_auth_readiness_reports_oauth_scope_matrix(monkeypatch):
    configs = {
        "default": FakeConfig(
            name="default",
            scopes=["openid", "profile", "w_member_social"],
        ),
        "affiliate-magic-page": FakeConfig(
            name="affiliate-magic-page",
            scopes=[],
            authenticated=False,
            missing_credentials=["ACCESS_TOKEN"],
            linkedin_page_urn="urn:li:organization:116016518",
        ),
    }

    monkeypatch.setattr(
        "linkedin_cli.main.list_profiles",
        lambda config: [
            {"name": "default", "file": ".env", "auth_type": "default", "active": True},
            {"name": "affiliate-magic-page", "file": ".env", "auth_type": "default", "active": False},
        ],
    )
    monkeypatch.setattr(
        "linkedin_cli.main.get_config",
        lambda profile=None: configs[profile or "default"],
    )

    result = runner.invoke(app, ["auth", "readiness"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    default_checks = {check["command"]: check for check in payload["profiles"][0]["checks"]}
    page_checks = {check["command"]: check for check in payload["profiles"][1]["checks"]}
    assert default_checks["user posts create/update/delete"]["ready"] is True
    assert default_checks["user posts create/update/delete"]["credential"] == "oauth"
    assert default_checks["user posts create/update/delete"]["commands"] == [
        "user posts create",
        "user posts update",
        "user posts delete",
    ]
    assert default_checks["user posts list/get/search"]["blocked_by"] == [
        "missing scopes: r_member_social"
    ]
    assert default_checks["user posts list/get/search"]["commands"] == [
        "user posts list",
        "user posts get",
        "user posts search",
    ]
    assert default_checks["page posts create/update/delete"]["blocked_by"] == [
        "missing scopes: w_organization_social"
    ]
    assert page_checks["page posts list/get/search"]["blocked_by"] == [
        "missing credentials: ACCESS_TOKEN",
        "missing scopes: r_organization_social",
    ]

from dotenv import dotenv_values
from typer.testing import CliRunner

import jira_cli.config as jira_config
from jira_cli.main import app


runner = CliRunner()


def test_auth_login_requires_profile_when_auth_modes_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    jira_config._configs.clear()

    result = runner.invoke(app, ["auth", "login"])

    assert result.exit_code == 1, result.output
    assert "auth login requires --profile" in result.output


def test_auth_login_prompts_for_base_url_and_site_basic_token_setup_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("PASSWORD", raising=False)
    jira_config._configs.clear()

    create_result = runner.invoke(
        app,
        ["auth", "profiles", "create", "personal", "--auth-type", jira_config.SITE_BASIC_AUTH_TYPE],
    )
    assert create_result.exit_code == 0, create_result.output

    result = runner.invoke(
        app,
        ["auth", "login", "--profile", "personal"],
        input="https://acme.atlassian.net\nadam@example.com\njira-api-token\n",
    )

    assert result.exit_code == 0, result.output
    assert "https://id.atlassian.com/manage-profile/security/api-tokens" in result.output
    assert "Enter Jira Cloud site URL (for example https://example.atlassian.net):" in result.output
    assert "Enter Atlassian account email:" in result.output
    assert "Enter Atlassian API token:" in result.output

    root_env = tmp_path / "cli-tools" / "jira" / ".env"
    profile_env = tmp_path / "cli-tools" / "jira" / "authentication_profiles" / "personal" / ".env"

    assert root_env.exists()
    assert profile_env.exists()
    assert dotenv_values(root_env)["BASE_URL"] == "https://acme.atlassian.net"
    assert dotenv_values(profile_env)["AUTH_TYPE"] == jira_config.SITE_BASIC_AUTH_TYPE


def test_auth_profiles_create_scoped_token_profile_captures_cloud_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    jira_config._configs.clear()

    result = runner.invoke(
        app,
        [
            "auth",
            "profiles",
            "create",
            "scoped",
            "--auth-type",
            jira_config.SCOPED_API_TOKEN_AUTH_TYPE,
            "--auth-param",
            "CLOUD_ID=1324a887-45db-1bf4-1e99-ef0ff456d421",
        ],
    )

    assert result.exit_code == 0, result.output
    profile_env = (
        tmp_path / "cli-tools" / "jira" / "authentication_profiles" / "scoped" / ".env"
    )
    values = dotenv_values(profile_env)
    assert values["AUTH_TYPE"] == jira_config.SCOPED_API_TOKEN_AUTH_TYPE
    assert values["CLOUD_ID"] == "1324a887-45db-1bf4-1e99-ef0ff456d421"


def test_oauth_profile_base_url_selects_matching_resource(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    for name in ("BASE_URL", "CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN", "TOKEN_EXPIRES_AT", "REDIRECT_URI", "CLOUD_ID"):
        monkeypatch.delenv(name, raising=False)
    jira_config._configs.clear()

    create_result = runner.invoke(
        app,
        [
            "auth",
            "profiles",
            "create",
            "devolutions",
            "--auth-type",
            jira_config.OAUTH_3LO_AUTH_TYPE,
            "--auth-param",
            "BASE_URL=https://devolutions.atlassian.net",
        ],
    )
    assert create_result.exit_code == 0, create_result.output

    def fake_oauth_login(config, force):
        config._set("ACCESS_TOKEN", "oauth-access-token")
        config._set("REFRESH_TOKEN", "oauth-refresh-token")
        config._set("TOKEN_EXPIRES_AT", "9999999999")

    class FakeResponse:
        status_code = 200

        def json(self):
            return [
                {
                    "id": "wrong-cloud-id",
                    "name": "Other Jira",
                    "url": "https://other.atlassian.net",
                    "scopes": ["read:jira-work", "write:jira-work"],
                },
                {
                    "id": "devolutions-cloud-id",
                    "name": "Devolutions Jira",
                    "url": "https://devolutions.atlassian.net",
                    "scopes": ["read:jira-work", "write:jira-work"],
                },
            ]

    monkeypatch.setattr("jira_cli.main.oauth_login", fake_oauth_login)
    monkeypatch.setattr("jira_cli.main.requests.get", lambda *args, **kwargs: FakeResponse())

    result = runner.invoke(
        app,
        ["auth", "login", "--profile", "devolutions"],
        input="client-id-123\nclient-secret-456\nhttp://localhost\n",
    )

    assert result.exit_code == 0, result.output
    profile_env = tmp_path / "cli-tools" / "jira" / "authentication_profiles" / "devolutions" / ".env"
    root_env = tmp_path / "cli-tools" / "jira" / ".env"
    assert dotenv_values(profile_env)["AUTH_TYPE"] == jira_config.OAUTH_3LO_AUTH_TYPE
    assert dotenv_values(profile_env)["CLOUD_ID"] == "devolutions-cloud-id"
    assert dotenv_values(root_env)["BASE_URL"] == "https://devolutions.atlassian.net"


def test_legacy_profile_without_auth_type_is_migrated_to_site_basic(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    for name in ("AUTH_TYPE", "USERNAME", "PASSWORD", "BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    jira_config._configs.clear()

    tool_dir = tmp_path / "cli-tools" / "jira"
    profile_env = tool_dir / "authentication_profiles" / "default" / ".env"
    profile_env.parent.mkdir(parents=True)
    (tool_dir / ".env").write_text("BASE_URL=https://acme.atlassian.net\n")
    profile_env.write_text(
        "ACTIVE=true\n"
        "USERNAME=adam@example.com\n"
        "PASSWORD=jira-api-token\n"
    )

    config = jira_config.get_config(profile="default")

    assert config.auth_type == jira_config.SITE_BASIC_AUTH_TYPE
    assert dotenv_values(profile_env)["AUTH_TYPE"] == jira_config.SITE_BASIC_AUTH_TYPE


def test_oauth_login_stores_cloud_id_from_accessible_resources(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    for name in ("BASE_URL", "CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN", "TOKEN_EXPIRES_AT", "REDIRECT_URI", "CLOUD_ID"):
        monkeypatch.delenv(name, raising=False)
    jira_config._configs.clear()

    create_result = runner.invoke(
        app,
        [
            "auth",
            "profiles",
            "create",
            "oauth",
            "--auth-type",
            jira_config.OAUTH_3LO_AUTH_TYPE,
            "--auth-param",
            "BASE_URL=https://acme.atlassian.net",
        ],
    )
    assert create_result.exit_code == 0, create_result.output

    oauth_calls = {}

    def fake_oauth_login(config, force):
        oauth_calls["force"] = force
        oauth_calls["client_id"] = config.client_id
        oauth_calls["redirect_uri"] = config.redirect_uri
        config._set("ACCESS_TOKEN", "oauth-access-token")
        config._set("REFRESH_TOKEN", "oauth-refresh-token")
        config._set("TOKEN_EXPIRES_AT", "9999999999")

    class FakeResponse:
        status_code = 200

        def json(self):
            return [
                {
                    "id": "1324a887-45db-1bf4-1e99-ef0ff456d421",
                    "name": "Acme Jira",
                    "url": "https://acme.atlassian.net",
                    "scopes": ["read:jira-work", "write:jira-work"],
                }
            ]

    monkeypatch.setattr("jira_cli.main.oauth_login", fake_oauth_login)
    monkeypatch.setattr("jira_cli.main.requests.get", lambda *args, **kwargs: FakeResponse())

    result = runner.invoke(
        app,
        ["auth", "login", "--profile", "oauth"],
        input="client-id-123\nclient-secret-456\nhttp://localhost\n",
    )

    assert result.exit_code == 0, result.output
    assert oauth_calls == {
        "force": False,
        "client_id": "client-id-123",
        "redirect_uri": "http://localhost",
    }

    profile_env = tmp_path / "cli-tools" / "jira" / "authentication_profiles" / "oauth" / ".env"
    root_env = tmp_path / "cli-tools" / "jira" / ".env"
    assert dotenv_values(profile_env)["AUTH_TYPE"] == jira_config.OAUTH_3LO_AUTH_TYPE
    assert dotenv_values(profile_env)["CLOUD_ID"] == "1324a887-45db-1bf4-1e99-ef0ff456d421"
    assert dotenv_values(root_env)["BASE_URL"] == "https://acme.atlassian.net"

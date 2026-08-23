"""Auth profile creation tests for the YouTube CLI."""

import pytest
from typer.testing import CliRunner

from youtube_cli.commands.auth import app
from youtube_cli.config import YOUTUBE_PROFILE_AUTH_TYPE, reset_config


RUNNER = CliRunner()


@pytest.fixture(autouse=True)
def _reset_config_cache():
    reset_config()
    yield
    reset_config()


def _configure_temp_profile_store(monkeypatch, tmp_path):
    tool_dir = tmp_path / "youtube"
    tool_dir.mkdir()
    (tool_dir / ".env.example").write_text(
        "AUTH_TYPE=\nCLIENT_ID=\nCLIENT_SECRET=\nACTIVE=true\n"
    )

    profiles_dir = tmp_path / "data" / "youtube" / "authentication_profiles"

    monkeypatch.setattr(
        "youtube_cli.config.resolve_tool_dir",
        lambda _dist_name: tool_dir,
    )
    monkeypatch.setattr(
        "cli_tools_shared.config.get_profiles_base_dir",
        lambda _tool_name: profiles_dir,
    )
    monkeypatch.setattr(
        "cli_tools_shared.profiles.get_profiles_base_dir",
        lambda _tool_name: profiles_dir,
    )
    return profiles_dir


def test_profiles_create_requires_auth_type(monkeypatch, tmp_path):
    _configure_temp_profile_store(monkeypatch, tmp_path)

    result = RUNNER.invoke(app, ["profiles", "create", "demo-profile"])

    assert result.exit_code == 2, result.output
    assert "Missing option '--auth-type'" in result.output


def test_profiles_create_prompts_for_client_credentials(monkeypatch, tmp_path):
    profiles_dir = _configure_temp_profile_store(monkeypatch, tmp_path)

    result = RUNNER.invoke(
        app,
        [
            "profiles",
            "create",
            "demo-profile",
            "--auth-type",
            YOUTUBE_PROFILE_AUTH_TYPE,
        ],
        input="client-id-123\nclient-secret-456\n",
    )

    assert result.exit_code == 0, result.output
    assert "Enter OAuth Client ID" in result.output

    content = (profiles_dir / "demo-profile" / ".env").read_text()
    assert "AUTH_TYPE='google_oauth_desktop'" in content
    assert "CLIENT_ID='client-id-123'" in content
    assert "CLIENT_SECRET='secret://youtube-demo-profile-client-secret'" in content


def test_profiles_create_accepts_auth_params(monkeypatch, tmp_path):
    profiles_dir = _configure_temp_profile_store(monkeypatch, tmp_path)

    result = RUNNER.invoke(
        app,
        [
            "profiles",
            "create",
            "demo-profile",
            "--auth-type",
            YOUTUBE_PROFILE_AUTH_TYPE,
            "--auth-param",
            "CLIENT_ID=client-id-123",
            "--auth-param",
            "CLIENT_SECRET=client-secret-456",
        ],
        input="",
    )

    assert result.exit_code == 0, result.output
    assert "Enter OAuth Client ID" not in result.output

    content = (profiles_dir / "demo-profile" / ".env").read_text()
    assert "AUTH_TYPE='google_oauth_desktop'" in content
    assert "CLIENT_ID='client-id-123'" in content
    assert "CLIENT_SECRET='secret://youtube-demo-profile-client-secret'" in content

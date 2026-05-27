"""Regression tests for Grammarly's dual auth model."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from grammarly_cli.commands import auth, docs, plagiarism
from grammarly_cli.config import Config, _reset_config


@pytest.fixture(autouse=True)
def reset_config_cache():
    _reset_config()
    yield
    _reset_config()


@pytest.fixture
def fake_secret_manager(monkeypatch):
    store: dict[str, str] = {}

    def _run(command: str, secret_name: str, *, secret_value=None):
        if command == "get":
            if secret_name not in store:
                return subprocess.CompletedProcess([], 1, stdout="", stderr="not found")
            return subprocess.CompletedProcess([], 0, stdout=store[secret_name], stderr="")
        if command == "set":
            store[secret_name] = secret_value
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if command == "has":
            code = 0 if secret_name in store else 1
            return subprocess.CompletedProcess([], code, stdout="", stderr="")
        if command == "delete":
            if secret_name not in store:
                return subprocess.CompletedProcess([], 1, stdout="", stderr="not found")
            del store[secret_name]
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected secret-manager command: {command}")

    import cli_tools_shared.config as config_module

    monkeypatch.setattr(config_module, "_run_secret_manager", _run)
    return store


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    data_home = tmp_path / "data"
    home = tmp_path / "home"
    data_home.mkdir(parents=True)
    home.mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("GRAMMARLY_COOKIES", raising=False)
    monkeypatch.delenv("GRAMMARLY_CLIENT_ID", raising=False)
    monkeypatch.delenv("GRAMMARLY_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GRAMMARLY_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GRAMMARLY_TOKEN_EXPIRES_AT", raising=False)
    return tmp_path


def test_command_credentials_split_by_auth_type():
    assert docs.COMMAND_CREDENTIALS == {
        "get": ["browser_session"],
        "list": ["browser_session"],
        "new": ["browser_session"],
        "read": ["browser_session"],
    }
    assert plagiarism.COMMAND_CREDENTIALS == {
        "check": ["custom"],
        "status": ["custom"],
    }


def test_cookie_session_is_separate_from_plagiarism_credentials(
    isolated_env,
    fake_secret_manager,
):
    config = Config()
    config.save_cookies("grauth=abc; csrf-token=def")

    assert config.has_saved_session() is True
    assert config.has_cookies() is True
    assert config.has_credentials() is False
    assert config.has_api_credentials() is False


def test_legacy_cookie_file_still_counts_as_saved_session(
    isolated_env,
    fake_secret_manager,
):
    legacy_path = Path.home() / ".grammarly_cookies"
    legacy_path.write_text("grauth=legacy; csrf-token=token")

    config = Config()

    assert config.cookies == "grauth=legacy; csrf-token=token"
    assert config.has_saved_session() is True


def test_clear_session_removes_profile_cookie_state(
    isolated_env,
    fake_secret_manager,
):
    config = Config()
    config.save_cookies("grauth=abc; csrf-token=def")

    config.clear_session()

    assert config.has_saved_session() is False
    assert config.cookies is None


def test_auth_status_reports_browser_session_separately(
    isolated_env,
    fake_secret_manager,
    monkeypatch,
):
    config = Config()
    config.save_cookies("grauth=abc; csrf-token=def")

    monkeypatch.setattr(
        "grammarly_cli.browser.GrammarlyCookieBrowserSession._probe_or_login_page",
        lambda self, url=None: type("Page", (), {"url": "https://app.grammarly.com/", "wait_for_timeout": lambda *_args, **_kwargs: None})(),
    )

    result = CliRunner().invoke(auth.app, ["status"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    profile = payload["profiles"][0]
    assert profile["authenticated"] is True
    assert profile["credential_types"]["browser_session"]["credentials_saved"] is True
    assert profile["credential_types"]["browser_session"]["authenticated"] is True
    assert profile["credential_types"]["custom"]["credentials_saved"] is False
    assert profile["credential_types"]["custom"]["authenticated"] is False


def test_auth_status_rejects_anonymous_browser_session(
    isolated_env,
    fake_secret_manager,
    monkeypatch,
):
    config = Config()
    config.save_cookies("grauth=anon; csrf-token=token")

    monkeypatch.setattr(
        "grammarly_cli.client.DocsClient.get_user",
        lambda self: {
            "id": "anon-user",
            "email": "anon-user@anonymous",
            "anonymous": True,
        },
    )

    result = CliRunner().invoke(auth.app, ["status"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    profile = payload["profiles"][0]
    assert profile["authenticated"] is False
    assert profile["credential_types"]["browser_session"]["credentials_saved"] is True
    assert profile["credential_types"]["browser_session"]["authenticated"] is False


def test_browser_session_login_imports_existing_cookie_source(
    isolated_env,
    fake_secret_manager,
    monkeypatch,
):
    legacy_path = Path.home() / ".grammarly_cookies"
    legacy_path.write_text("grauth=legacy; csrf-token=token")
    monkeypatch.setattr(
        "grammarly_cli.client.DocsClient.get_user",
        lambda self: {"id": "user-1"},
    )

    config = Config()
    result = config.get_browser().login(force=False)

    assert result == {"success": True, "message": "Grammarly docs cookies saved"}
    assert config.cookies == "grauth=legacy; csrf-token=token"


def test_browser_session_login_fails_cleanly_without_cookie_source(
    isolated_env,
    fake_secret_manager,
):
    config = Config()

    result = config.get_browser().login(force=False)

    assert result["success"] is False
    assert "No Grammarly docs cookies found" in result["message"]

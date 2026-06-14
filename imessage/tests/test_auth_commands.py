import json

from typer.testing import CliRunner

from imessage_cli.main import app
from imessage_cli.models import create_auth_status


class FakeClient:
    def __init__(self, authenticated=True):
        self.authenticated = authenticated

    def auth_status(self):
        return create_auth_status(
            {
                "authenticated": self.authenticated,
                "messages_app_available": True,
                "messages_db_accessible": self.authenticated,
                "contacts_accessible": True,
                "macos_version": "14.0",
            }
        )

    def auth_login(self, **kwargs):
        return {
            "success": True,
            "message": "System Settings opened.",
            "force": kwargs.get("force", False),
        }

    def auth_logout(self):
        return {
            "success": True,
            "message": "No session to clear.",
        }


def test_auth_status_outputs_json_when_permissions_are_available(monkeypatch):
    monkeypatch.setattr(
        "imessage_cli.commands.auth.get_client",
        lambda: FakeClient(authenticated=True),
    )

    result = CliRunner().invoke(app, ["auth", "status"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["authenticated"] is True
    assert payload["messages_db_accessible"] is True
    assert payload["contacts_accessible"] is True
    profile = payload["profiles"][0]
    assert profile["name"] == "default"
    assert profile["auth_type"] == "system_permissions"
    assert profile["active"] is True
    assert profile["authenticated"] is True
    assert profile["credential_types"]["custom"]["credentials_saved"] is True
    assert profile["credential_types"]["custom"]["authenticated"] is True
    assert profile["credential_types"]["custom"]["api_test"] == "passed"


def test_auth_status_exits_2_when_messages_database_is_not_accessible(monkeypatch):
    monkeypatch.setattr(
        "imessage_cli.commands.auth.get_client",
        lambda: FakeClient(authenticated=False),
    )

    result = CliRunner().invoke(app, ["auth", "status"])

    assert result.exit_code == 2, result.output
    payload = json.loads(result.stdout)
    assert payload["authenticated"] is False
    assert payload["messages_db_accessible"] is False
    profile = payload["profiles"][0]
    assert profile["authenticated"] is False
    assert profile["credential_types"]["custom"]["authenticated"] is False
    assert profile["credential_types"]["custom"]["api_test"].startswith("failed:")


def test_auth_login_accepts_force_and_outputs_result(monkeypatch):
    monkeypatch.setattr(
        "imessage_cli.commands.auth.get_client",
        lambda: FakeClient(authenticated=True),
    )

    result = CliRunner().invoke(app, ["auth", "login", "--force"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["force"] is True


def test_auth_logout_outputs_result(monkeypatch):
    monkeypatch.setattr(
        "imessage_cli.commands.auth.get_client",
        lambda: FakeClient(authenticated=True),
    )

    result = CliRunner().invoke(app, ["auth", "logout"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True

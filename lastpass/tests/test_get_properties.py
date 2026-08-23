"""Command-level tests for `lastpass items get --properties`.

The properties path must NEVER emit secret values:

1. `--properties` selects non-secret fields (dot-notation aware, explicit
   null for absent fields) from the entry.
2. Requesting a secret field (password, secret, token, ... — including as a
   dot-notation segment) is a clear error with a non-zero exit, and the
   secret value never reaches stdout/stderr.
3. `--properties` cannot be combined with `--show-password`.
4. Defense in depth: selection always runs against the masked entry, so a
   string field carrying nested JSON secrets (e.g. Notes) stays masked.
"""
import json

import pytest
from typer.testing import CliRunner

from lastpass_cli.client import LastpassClient, MASKED_SECRET_VALUE as MASKED
from lastpass_cli.commands import items as items_module


SYNTHETIC_PASSWORD = "synthetic-password-value"
SYNTHETIC_PASSWD = "synthetic-passwd-value"
SYNTHETIC_TOKEN = "synthetic-token-value"
SYNTHETIC_OTP = "synthetic-otp-value"
SYNTHETIC_TOTP = "synthetic-totp-seed"

SHOW_OUTPUT = "\n".join(
    [
        "Work/GitHub [id: 1234567890]",
        "URL: https://github.com",
        "Username: synthetic-user",
        f"Password: {SYNTHETIC_PASSWORD}",
        f"passwd: {SYNTHETIC_PASSWD}",
        f"OTP: {SYNTHETIC_OTP}",
        f"TOTP Seed: {SYNTHETIC_TOTP}",
        "Environment: synthetic-staging",
        f'Notes: {{"api_token": "{SYNTHETIC_TOKEN}", "hint": "blue"}}',
    ]
)


def _real_client_with_show_output(output: str) -> LastpassClient:
    """Real LastpassClient (parse + mask intact) with a faked lpass call."""
    client = LastpassClient.__new__(LastpassClient)

    def fake_run_command(args, **kwargs):
        import subprocess
        assert args[0] == "show"
        return subprocess.CompletedProcess(args, 0, output, "")

    client._run_command = fake_run_command
    return client


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def patch_client(monkeypatch):
    monkeypatch.setattr(
        items_module, "get_client",
        lambda: _real_client_with_show_output(SHOW_OUTPUT),
    )


def test_properties_selects_only_requested_nonsecret_fields(runner):
    result = runner.invoke(
        items_module.app, ["get", "1234567890", "--properties", "id,name,URL"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {"id": "1234567890", "name": "GitHub", "URL": "https://github.com"}


def test_properties_projects_explicit_null_for_absent_fields(runner):
    result = runner.invoke(
        items_module.app, ["get", "1234567890", "--properties", "id,nonexistent"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {"id": "1234567890", "nonexistent": None}


@pytest.mark.parametrize(
    "props",
    [
        "password",
        "Password",
        "id,Password",
        "Note.password",  # dot-notation segments are checked too
        "api_token",
        "client_secret",
        "passwd",
        "OTP",
        "otp",
        "TOTP",
        "totp",
        "TOTP Seed",
        "Notes.OTP",
        "custom.totp_secret",
    ],
)
def test_properties_refuses_secret_fields(runner, props):
    result = runner.invoke(items_module.app, ["get", "1234567890", "--properties", props])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "cannot select secret fields" in result.stderr
    assert SYNTHETIC_PASSWORD not in result.stderr
    assert SYNTHETIC_TOKEN not in result.stderr
    assert SYNTHETIC_OTP not in result.stderr
    assert SYNTHETIC_TOTP not in result.stderr


def test_properties_refuses_show_password_combination(runner):
    result = runner.invoke(
        items_module.app,
        ["get", "1234567890", "--properties", "id,name", "--show-password"],
    )

    assert result.exit_code != 0
    assert "cannot be combined with --show-password" in result.output
    assert SYNTHETIC_PASSWORD not in result.output
    assert result.stdout.strip() == ""


def test_properties_selection_runs_against_masked_entry(runner):
    # Notes itself is not a secret key, but its embedded JSON secrets must
    # already be masked when the properties path selects it.
    result = runner.invoke(
        items_module.app, ["get", "1234567890", "--properties", "Notes"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert SYNTHETIC_TOKEN not in result.output
    assert MASKED in payload["Notes"]


def test_properties_works_with_table_output(runner):
    result = runner.invoke(
        items_module.app, ["get", "1234567890", "--properties", "id,name", "--table"]
    )

    assert result.exit_code == 0, result.output
    assert "1234567890" in result.stdout
    assert SYNTHETIC_PASSWORD not in result.output


def test_get_without_properties_still_masks_by_default(runner):
    result = runner.invoke(items_module.app, ["get", "1234567890"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["Password"] == MASKED
    assert payload["passwd"] == MASKED
    assert payload["OTP"] == MASKED
    assert payload["TOTP Seed"] == MASKED
    assert payload["Environment"] == "synthetic-staging"
    assert SYNTHETIC_PASSWORD not in result.output
    assert SYNTHETIC_PASSWD not in result.output
    assert SYNTHETIC_OTP not in result.output
    assert SYNTHETIC_TOTP not in result.output


def test_show_password_without_properties_still_reveals(runner):
    result = runner.invoke(items_module.app, ["get", "1234567890", "--show-password"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["Password"] == SYNTHETIC_PASSWORD

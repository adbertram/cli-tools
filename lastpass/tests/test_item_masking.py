"""Synthetic tests for LastPass item detail masking."""
import json
import subprocess

from lastpass_cli.client import LastpassClient, MASKED_SECRET_VALUE as MASKED


SYNTHETIC_PASSWORD = "synthetic-password-value"
SYNTHETIC_PASSWD = "synthetic-passwd-value"
SYNTHETIC_SECRET = "synthetic-api-secret-value"
SYNTHETIC_EMAIL = "synthetic-user@example.invalid"
SYNTHETIC_NOTES_JSON = json.dumps(
    {
        "email": SYNTHETIC_EMAIL,
        "password": SYNTHETIC_PASSWORD,
        "passwd": SYNTHETIC_PASSWD,
        "pwd": "nested-pwd-value",
        "metadata": {
            "api_secret": SYNTHETIC_SECRET,
        },
    }
)
SYNTHETIC_SHOW_OUTPUT = "\n".join(
    [
        "Name: Synthetic Entry",
        "Password: top-level-password",
        "password: lower-case-password",
        f"passwd: {SYNTHETIC_PASSWD}",
        "pwd: short-password-alias",
        "Environment: synthetic-staging",
        f"Notes: {SYNTHETIC_NOTES_JSON}",
    ]
)


def _client_with_show_output(output: str) -> LastpassClient:
    client = LastpassClient.__new__(LastpassClient)

    def fake_run_command(args, **kwargs):
        assert args == ["show", "synthetic-item"]
        return subprocess.CompletedProcess(args, 0, output, "")

    client._run_command = fake_run_command
    return client


def test_get_item_masks_nested_password_secret_and_email_fields_by_default():
    client = _client_with_show_output(SYNTHETIC_SHOW_OUTPUT)

    item = client.get_item("synthetic-item")
    serialized = json.dumps(item, sort_keys=True)

    assert item["Password"] == MASKED
    assert item["password"] == MASKED
    assert item["passwd"] == MASKED
    assert item["pwd"] == MASKED
    assert item["Environment"] == "synthetic-staging"
    assert "top-level-password" not in serialized
    assert "lower-case-password" not in serialized
    assert "short-password-alias" not in serialized
    assert SYNTHETIC_PASSWD not in serialized
    assert "nested-pwd-value" not in serialized
    assert SYNTHETIC_PASSWORD not in serialized
    assert SYNTHETIC_SECRET not in serialized
    assert SYNTHETIC_EMAIL not in serialized


def test_get_item_reveals_password_secret_and_email_fields_when_requested():
    client = _client_with_show_output(SYNTHETIC_SHOW_OUTPUT)

    item = client.get_item("synthetic-item", show_password=True)

    assert item["Password"] == "top-level-password"
    assert item["password"] == "lower-case-password"
    assert item["passwd"] == SYNTHETIC_PASSWD
    assert item["pwd"] == "short-password-alias"
    assert item["Environment"] == "synthetic-staging"
    assert item["Notes"] == SYNTHETIC_NOTES_JSON

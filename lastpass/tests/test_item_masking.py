"""Synthetic tests for LastPass item detail masking."""
import json
import subprocess

import pytest

from lastpass_cli.client import (
    LastpassClient,
    MASKED_SECRET_VALUE as MASKED,
    is_sensitive_item_detail_key,
)


SYNTHETIC_PASSWORD = "synthetic-password-value"
SYNTHETIC_PASSWD = "synthetic-passwd-value"
SYNTHETIC_SECRET = "synthetic-api-secret-value"
SYNTHETIC_EMAIL = "synthetic-user@example.invalid"
SYNTHETIC_OTP = "synthetic-otp-value"
SYNTHETIC_TOTP = "synthetic-totp-seed"
SYNTHETIC_NOTES_JSON = json.dumps(
    {
        "email": SYNTHETIC_EMAIL,
        "password": SYNTHETIC_PASSWORD,
        "passwd": SYNTHETIC_PASSWD,
        "pwd": "nested-pwd-value",
        "otp": SYNTHETIC_OTP,
        "totp_secret": SYNTHETIC_TOTP,
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
        f"OTP: {SYNTHETIC_OTP}",
        f"TOTP Seed: {SYNTHETIC_TOTP}",
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
    assert item["OTP"] == MASKED
    assert item["TOTP Seed"] == MASKED
    assert item["Environment"] == "synthetic-staging"
    assert "top-level-password" not in serialized
    assert "lower-case-password" not in serialized
    assert "short-password-alias" not in serialized
    assert SYNTHETIC_PASSWD not in serialized
    assert "nested-pwd-value" not in serialized
    assert SYNTHETIC_PASSWORD not in serialized
    assert SYNTHETIC_SECRET not in serialized
    assert SYNTHETIC_EMAIL not in serialized
    assert SYNTHETIC_OTP not in serialized
    assert SYNTHETIC_TOTP not in serialized


def test_get_item_reveals_password_secret_and_email_fields_when_requested():
    client = _client_with_show_output(SYNTHETIC_SHOW_OUTPUT)

    item = client.get_item("synthetic-item", show_password=True)

    assert item["Password"] == "top-level-password"
    assert item["password"] == "lower-case-password"
    assert item["passwd"] == SYNTHETIC_PASSWD
    assert item["pwd"] == "short-password-alias"
    assert item["OTP"] == SYNTHETIC_OTP
    assert item["TOTP Seed"] == SYNTHETIC_TOTP
    assert item["Environment"] == "synthetic-staging"
    assert item["Notes"] == SYNTHETIC_NOTES_JSON


@pytest.mark.parametrize(
    "field_name",
    [
        "OTP",
        "otp",
        "TOTP",
        "totp",
        "TOTP-Secret",
        "totp_secret",
        "Totp Seed",
    ],
)
def test_otp_and_totp_variants_are_sensitive_at_every_depth(field_name):
    canary = f"synthetic-value-for-{field_name}"
    notes = json.dumps({field_name: canary})
    client = _client_with_show_output(
        "\n".join(
            [
                f"{field_name}: {canary}",
                f"Notes: {notes}",
            ]
        )
    )

    masked = client.get_item("synthetic-item")
    revealed = client.get_item("synthetic-item", show_password=True)

    assert is_sensitive_item_detail_key(field_name) is True
    assert masked[field_name] == MASKED
    assert json.loads(masked["Notes"])[field_name] == MASKED
    assert canary not in json.dumps(masked)
    assert revealed[field_name] == canary
    assert json.loads(revealed["Notes"])[field_name] == canary

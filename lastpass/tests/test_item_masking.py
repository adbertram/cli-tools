"""Synthetic tests for LastPass item detail masking."""
import json
import subprocess

from lastpass_cli.client import LastpassClient


SYNTHETIC_PASSWORD = "synthetic-password-value"
SYNTHETIC_SECRET = "synthetic-api-secret-value"
SYNTHETIC_EMAIL = "synthetic-user@example.invalid"
MASKED = "********"


def _client_with_show_output(output: str) -> LastpassClient:
    client = LastpassClient.__new__(LastpassClient)

    def fake_run_command(args, **kwargs):
        assert args == ["show", "synthetic-item"]
        return subprocess.CompletedProcess(args, 0, output, "")

    client._run_command = fake_run_command
    return client


def test_get_item_masks_nested_password_secret_and_email_fields_by_default():
    notes_payload = {
        "email": SYNTHETIC_EMAIL,
        "password": SYNTHETIC_PASSWORD,
        "metadata": {
            "api_secret": SYNTHETIC_SECRET,
        },
    }
    client = _client_with_show_output(
        "\n".join(
            [
                "Name: Synthetic Entry",
                "Password: top-level-password",
                "password: lower-case-password",
                f"Notes: {json.dumps(notes_payload)}",
            ]
        )
    )

    item = client.get_item("synthetic-item")
    serialized = json.dumps(item, sort_keys=True)

    assert item["Password"] == MASKED
    assert item["password"] == MASKED
    assert "top-level-password" not in serialized
    assert "lower-case-password" not in serialized
    assert SYNTHETIC_PASSWORD not in serialized
    assert SYNTHETIC_SECRET not in serialized
    assert SYNTHETIC_EMAIL not in serialized


def test_get_item_reveals_password_secret_and_email_fields_when_requested():
    notes_payload = {
        "email": SYNTHETIC_EMAIL,
        "password": SYNTHETIC_PASSWORD,
        "metadata": {
            "api_secret": SYNTHETIC_SECRET,
        },
    }
    notes_json = json.dumps(notes_payload)
    client = _client_with_show_output(
        "\n".join(
            [
                "Name: Synthetic Entry",
                "Password: top-level-password",
                "password: lower-case-password",
                f"Notes: {notes_json}",
            ]
        )
    )

    item = client.get_item("synthetic-item", show_password=True)

    assert item["Password"] == "top-level-password"
    assert item["password"] == "lower-case-password"
    assert item["Notes"] == notes_json

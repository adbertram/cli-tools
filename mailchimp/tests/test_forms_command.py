import json
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from mailchimp_cli.main import app


class FakeFormsClient:
    def __init__(self):
        self.create_call = None

    def list_all_signup_forms(self, count):
        return self.list_signup_forms("abc123")[:count]

    def list_signup_forms(self, list_id):
        return [
            {
                "list_id": list_id,
                "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
            },
            {
                "list_id": list_id,
                "signup_form_url": "https://second.example.list-manage.com/subscribe?u=abc&id=ghi",
            }
        ]

    def get_signup_form(self, list_id):
        return {
            "list_id": list_id,
            "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
        }

    def customize_signup_form(
        self,
        list_id,
        header_text,
        signup_message,
        signup_thank_you_title,
    ):
        self.create_call = {
            "list_id": list_id,
            "header_text": header_text,
            "signup_message": signup_message,
            "signup_thank_you_title": signup_thank_you_title,
        }
        return {
            "list_id": list_id,
            "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
            "header": {"text": header_text},
            "contents": [
                {"section": "signup_message", "value": signup_message},
                {"section": "signup_thank_you_title", "value": signup_thank_you_title},
            ],
        }


class FormsCommandTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_list_outputs_signup_forms_for_list(self):
        fake_client = FakeFormsClient()

        with patch("mailchimp_cli.commands.forms.get_client", return_value=fake_client):
            result = self.runner.invoke(app, ["forms", "list", "abc123"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            json.loads(result.stdout),
            [
                {
                    "list_id": "abc123",
                    "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
                },
                {
                    "list_id": "abc123",
                    "signup_form_url": "https://second.example.list-manage.com/subscribe?u=abc&id=ghi",
                }
            ],
        )

    def test_list_outputs_signup_forms_for_all_lists_without_list_id(self):
        fake_client = FakeFormsClient()

        with patch("mailchimp_cli.commands.forms.get_client", return_value=fake_client):
            result = self.runner.invoke(app, ["forms", "list", "--limit", "1"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            json.loads(result.stdout),
            [
                {
                    "list_id": "abc123",
                    "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
                }
            ],
        )

    def test_list_supports_limit_and_properties_flags(self):
        fake_client = FakeFormsClient()

        with patch("mailchimp_cli.commands.forms.get_client", return_value=fake_client):
            result = self.runner.invoke(
                app,
                [
                    "forms",
                    "list",
                    "abc123",
                    "--limit",
                    "1",
                    "--properties",
                    "list_id",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout), [{"list_id": "abc123"}])

    def test_get_outputs_default_signup_form_for_list(self):
        fake_client = FakeFormsClient()

        with patch("mailchimp_cli.commands.forms.get_client", return_value=fake_client):
            result = self.runner.invoke(app, ["forms", "get", "abc123"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "list_id": "abc123",
                "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
            },
        )

    def test_create_customizes_default_signup_form(self):
        fake_client = FakeFormsClient()

        with patch("mailchimp_cli.commands.forms.get_client", return_value=fake_client):
            result = self.runner.invoke(
                app,
                [
                    "forms",
                    "create",
                    "abc123",
                    "--header-text",
                    "Example beta",
                    "--signup-message",
                    "Join the beta tester list.",
                    "--thank-you-title",
                    "You are on the list",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            fake_client.create_call,
            {
                "list_id": "abc123",
                "header_text": "Example beta",
                "signup_message": "Join the beta tester list.",
                "signup_thank_you_title": "You are on the list",
            },
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "list_id": "abc123",
                "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
                "header": {"text": "Example beta"},
                "contents": [
                    {
                        "section": "signup_message",
                        "value": "Join the beta tester list.",
                    },
                    {
                        "section": "signup_thank_you_title",
                        "value": "You are on the list",
                    },
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()

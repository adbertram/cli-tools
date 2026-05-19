import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from cli_tools_shared.credentials import CredentialType
from partnerstack_cli.client import AUTH_BASIC, AUTH_BEARER, PartnerstackClient
from partnerstack_cli.commands import applications, form_templates, marketplace, partnerships, rewards
from partnerstack_cli.config import Config
from partnerstack_cli.main import app


class FakeConfig:
    base_url = "https://api.partnerstack.com/api/v2"
    api_key = "bearer-key"
    username = "basic-public"
    password = "basic-secret"

    def _get(self, name: str):
        values = {
            "API_KEY": self.api_key,
            "USERNAME": self.username,
            "PASSWORD": self.password,
            "BASE_URL": self.base_url,
        }
        return values.get(name)


class FakeResponse:
    ok = True
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class PartnerStackAuthConstraintTests(unittest.TestCase):
    def test_top_level_help_keeps_basic_auth_groups_enabled(self) -> None:
        result = CliRunner().invoke(app, ["--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("form-templates", result.output)
        self.assertIn("applications", result.output)
        self.assertNotIn("disabled until Basic credential support is implemented", result.output)
        self.assertNotIn("Basic-auth only", result.output)

    def test_form_templates_commands_use_basic_auth_type(self) -> None:
        self.assertEqual(form_templates.COMMAND_AUTH_TYPES["list"], AUTH_BASIC)
        self.assertEqual(form_templates.COMMAND_AUTH_TYPES["get"], AUTH_BASIC)

    def test_applications_create_uses_basic_auth_type(self) -> None:
        self.assertEqual(applications.COMMAND_AUTH_TYPES["create"], AUTH_BASIC)

    def test_profile_keeps_bearer_auth_as_default_auth_status_type(self) -> None:
        self.assertEqual(Config.CREDENTIAL_TYPES, [CredentialType.API_KEY])

    def test_bearer_command_groups_stay_on_api_key_credentials(self) -> None:
        self.assertEqual(rewards.COMMAND_CREDENTIALS["list"], ["api_key"])
        self.assertEqual(marketplace.COMMAND_CREDENTIALS["list"], ["api_key"])
        self.assertEqual(partnerships.COMMAND_CREDENTIALS["list"], ["api_key"])

    @patch("partnerstack_cli.client.requests.request")
    @patch("partnerstack_cli.client.get_config", return_value=FakeConfig())
    def test_bearer_client_sends_bearer_authorization(self, _config, request) -> None:
        request.return_value = FakeResponse({"data": {"items": []}})

        client = PartnerstackClient(auth_type=AUTH_BEARER, max_retries=0)
        client.list_rewards()

        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer bearer-key")
        self.assertIsNone(kwargs["auth"])

    @patch("partnerstack_cli.client.requests.request")
    @patch("partnerstack_cli.client.get_config", return_value=FakeConfig())
    def test_basic_client_sends_basic_auth(self, _config, request) -> None:
        request.return_value = FakeResponse({"data": {"items": []}})

        client = PartnerstackClient(auth_type=AUTH_BASIC, max_retries=0)
        client.list_form_templates()

        kwargs = request.call_args.kwargs
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertEqual(kwargs["auth"], ("basic-public", "basic-secret"))


if __name__ == "__main__":
    unittest.main()

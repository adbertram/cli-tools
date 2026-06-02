from typer.testing import CliRunner

from cli_tools_shared.auth_commands import create_auth_app

from udemy_cli.config import Config


class AuthConfig:
    CREDENTIAL_TYPES = Config.CREDENTIAL_TYPES
    LOGIN_INSTRUCTIONS = Config.LOGIN_INSTRUCTIONS
    AUTH_EXTRA_PROMPTS = []
    OAUTH_AUTH_URL = None
    OAUTH_TOKEN_URL = None

    def __init__(self):
        self.values = {}

    def _get(self, field_name):
        return self.values.get(field_name)

    def _set(self, field_name, value):
        self.values[field_name] = value

    def get_browser(self):
        return None


def test_auth_login_instructions_show_api_clients_url_and_token_guidance():
    assert "https://www.udemy.com/user/edit-api-clients/" in Config.LOGIN_INSTRUCTIONS
    assert "Create a Udemy Instructor API client" in Config.LOGIN_INSTRUCTIONS
    assert "copy its bearer token" in Config.LOGIN_INSTRUCTIONS
    assert "Paste the bearer token" in Config.LOGIN_INSTRUCTIONS


def test_auth_login_prints_instructions_and_personal_access_token_prompt():
    config = AuthConfig()
    app = create_auth_app(lambda profile=None: config, tool_name="udemy", include_profiles=False)

    result = CliRunner().invoke(app, ["login"], input="token-123\n")

    assert result.exit_code == 0
    assert "Create a Udemy Instructor API client before logging in:" in result.output
    assert "https://www.udemy.com/user/edit-api-clients/" in result.output
    assert "Enter Personal access token:" in result.output
    assert config.values == {"PERSONAL_ACCESS_TOKEN": "token-123"}

"""Webull authentication profiles; reusable credentials stay in the secret manager."""
from cli_tools_shared.config import BaseConfig, config_getter, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "webull-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ["APP_KEY", "APP_SECRET"]
    CUSTOM_ALL_FIELDS = ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"]
    CUSTOM_SENSITIVE_FIELDS = CUSTOM_ALL_FIELDS
    CUSTOM_LOGIN_PROMPTS = [("APP_KEY", "Webull app key", True), ("APP_SECRET", "Webull app secret", True)]
    CUSTOM_EPHEMERAL_FIELDS = []
    OPTIONAL_SECRET_FIELDS = ("ACCESS_TOKEN",)
    AUTH_SETUP_INSTRUCTIONS = (
        "Create a Webull OpenAPI application at https://www.webull.com/center . "
        "App key and app secret are saved in the CLI-tools secret manager. "
        "Production account access also needs a Webull-authorized access token; "
        "save it with 'webull auth token' after authorizing it through Webull."
    )

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    def test_connection(self):
        from .client import WebullClient, WebullError
        try:
            WebullClient(config=self).account_list()
            return {"api_test": "passed"}
        except WebullError as exc:
            return {"api_test": "failed: " + exc.message}


get_config = config_getter(Config)

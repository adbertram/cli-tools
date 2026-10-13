"""Vyro browser profiles, scoped to the observed app and API hosts."""
from cli_tools_shared.config import BaseConfig, config_getter, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    DIST_NAME = "vyro-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    PORTABLE_BROWSER_SESSION = True
    LOGIN_INSTRUCTIONS = (
        "Sign in to your existing Vyro account with its emailed code, then confirm login. "
        "CLI-managed browser state stays in the private runtime profile."
    )

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    def get_browser(self):
        from .browser import VyroBrowser
        return VyroBrowser(self)

    def browser_session_origins(self):
        return ("https://app.vyro.com",)

    def browser_session_cookie_domains(self):
        return ("vyro.com", "api.vyro.com")

    def browser_session_identity(self, browser):
        from .client import VyroClient
        row = VyroClient(config=self, browser=browser).account()
        return {"account_id": row["id"], "username": row["username"]}

    def test_connection(self):
        from .client import VyroClient
        client = VyroClient(self)
        try:
            client.account()
            return {"api_test": "passed"}
        finally:
            client.close()


get_config = config_getter(Config)

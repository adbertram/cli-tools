"""Vues configuration: browser-session login, HTTP session afterwards.

Login happens once in a real browser (Google/Apple via Supabase). The resulting
Supabase session is read out of the browser and saved as runtime auth state, so
every later command runs over plain HTTP against the Vues API and refreshes the
session itself. The Supabase project ref and its public ``anon`` key are the
same values the Vues web app ships in its JavaScript bundle; neither is secret.
"""

from cli_tools_shared.config import BaseConfig, config_for, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError

# Verified from the Vues web app bundle and live calls, 2026-10-14.
SUPABASE_REF = "ycfkjzqusvyzbrisjziy"
SUPABASE_URL = f"https://{SUPABASE_REF}.supabase.co"
# Public anonymous client key (shipped in the site's JS; required by GoTrue for
# the token-refresh call). Not a secret and safe to embed.
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InljZmtqenF1c3Z5emJyaXNqeml5Iiwicm9sZSI6ImFub24i"
    "LCJpYXQiOjE3NzM3NjI3NTIsImV4cCI6MjA4OTMzODc1Mn0.kPnNcfX8u5cVSiGTb7ngaw9u1XzaRUGnOndIO_wKye8"
)
# Session fields written by login and automatic refresh; runtime state only.
TOKEN_FIELDS = ["SUPABASE_ACCESS_TOKEN", "SUPABASE_REFRESH_TOKEN", "SUPABASE_EXPIRES_AT"]


class Config(BaseConfig):
    DIST_NAME = "vues-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    PORTABLE_BROWSER_SESSION = True
    DEFAULT_BASE_URL = "https://api.evrgreen.ai"
    AUTH_SETUP_INSTRUCTIONS = (
        "Vues has no email/password or API key: you sign in once with Google or Apple.\n"
        "  1. Open https://vues.app/login and sign up (free) with Google or Apple.\n"
        "  2. Link your TikTok account (@ata_clipper) in the Vues app.\n"
        "  3. Run `vues auth login` and complete the provider sign-in in the browser."
    )

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    def get_browser(self):
        from .browser import VuesBrowser

        return VuesBrowser(self)

    def browser_session_origins(self):
        return ("https://vues.app",)

    def browser_session_identity(self, browser):
        """Runs right after a successful browser login: capture the Supabase
        session for HTTP use and confirm the signed-in creator."""
        from .client import VuesClient

        VuesClient(config=self).capture_session(browser)
        user = VuesClient(config=self).account()
        return {"account_id": user.get("id"), "email": user.get("email")}

    def test_connection(self) -> dict:
        """Live identity check over HTTP; refreshes an expired session but never
        opens a browser."""
        from .client import VuesClient

        try:
            user = VuesClient(config=self).account()
            return {"api_test": "passed", "id": user.get("id"), "email": user.get("email")}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    return config_for(Config, profile, _configs)

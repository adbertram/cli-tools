"""Browser automation class for Nextdoor CLI."""

from cli_tools_shared.auth import BrowserAutomation


class NextdoorBrowser(BrowserAutomation):
    """Browser automation for Nextdoor.

    Authentication is detected by URL redirect, not cookie presence. Nextdoor
    sets ``ndp_session_id`` even for logged-out visitors, so keying auth on that
    cookie reports a false positive (``auth status`` says authenticated while
    the server treats the session as logged out). Instead, the auth check loads
    an auth-required page (``/news_feed/``); an unauthenticated session is
    bounced to ``/login/``, which ``AUTH_URL_PATTERN`` matches to mean "not
    authenticated".
    """

    LOGIN_URL = "https://nextdoor.com/login/"
    AUTH_CHECK_URL = "https://nextdoor.com/news_feed/"
    AUTH_URL_PATTERN = r"/login"
    SESSION_NAME = "nextdoor"

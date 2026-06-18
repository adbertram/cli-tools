"""Browser automation hooks for Airbnb."""

from cli_tools_shared.auth import BrowserAutomation


class AirbnbBrowser(BrowserAutomation):
    """Declarative browser automation hooks for Airbnb."""

    SESSION_NAME = "airbnb"
    LOGIN_URL = "https://www.airbnb.com/login"
    AUTH_CHECK_URL = "https://www.airbnb.com/hosting/listings"
    AUTH_URL_PATTERN = r"/login|/authenticate"
    AUTH_COOKIE_PATTERNS = [r"_airbed_session_id"]

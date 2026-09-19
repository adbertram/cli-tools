"""Browser session automation for Garrul.

Garrul's only admin auth is a session cookie minted by an OAuth sign-in, so the
login has to happen in a real browser. Every command after that is a plain
HTTP request carrying the cookie.
"""

from cli_tools_shared.auth import BrowserAutomation

LOGIN_PATH = "/api/v1/auth/github/start"
AUTH_CHECK_PATH = "/admin"


class GarrulBrowser(BrowserAutomation):
    """BrowserAutomation hooks for the Garrul GitHub OAuth sign-in (default instance)."""

    SESSION_NAME = "garrul"
    LOGIN_URL = "https://comments.adamtheautomator.com/api/v1/auth/github/start"
    AUTH_CHECK_URL = "https://comments.adamtheautomator.com/admin"
    # Logged-out signal: /admin answers 401 with this heading and no app shell.
    AUTH_LOGIN_FORM_SELECTOR = 'h1:has-text("Sign in required")'


def browser_for(config) -> GarrulBrowser:
    """Return the browser bound to the instance named by BASE_URL.

    The class constants describe the default instance. BASE_URL may point at any
    other Garrul instance (a local `wrangler dev` one, for example), so the two
    URL hooks are always taken from the active configuration.
    """
    browser = GarrulBrowser(config)
    browser.LOGIN_URL = config.instance_origin + LOGIN_PATH
    browser.AUTH_CHECK_URL = config.instance_origin + AUTH_CHECK_PATH
    return browser

"""Browser automation for Poshmark."""

from cli_tools_shared.auth import BrowserAutomation


class PoshmarkBrowser(BrowserAutomation):
    """Browser automation for Poshmark via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks only — no methods. The base class handles auth lifecycle
    using these class-level constants. See cli-tool-browser-expert skill for
    selector validation guidance.
    """

    SESSION_NAME = "poshmark"
    LOGIN_URL = "https://poshmark.com/login"
    AUTH_CHECK_URL = "https://poshmark.com"
    AUTH_URL_PATTERN = r"/login|/register"
    # Poshmark blocks headless Chrome; run headed by default so the harnessed
    # browser presents a normal user fingerprint.
    AUTOMATION_HEADED = True
    # AUTH_SUCCESS_SELECTOR must target a VISIBLE element on the authenticated page.
    # Validate against a real page snapshot before shipping.
    AUTH_SUCCESS_SELECTOR = ""
    # AUTH_LOGIN_FORM_SELECTOR is the preferred "logged out" signal — its absence
    # on a non-login URL means the user is authenticated. More durable than positive
    # markers. Recommended: 'input[type="password"], form[action*="login"]'.
    AUTH_LOGIN_FORM_SELECTOR = 'input[type="password"], form[action*="login"]'

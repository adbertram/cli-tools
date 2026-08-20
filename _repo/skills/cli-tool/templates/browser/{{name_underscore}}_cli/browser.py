"""Browser automation for {{Name}}."""

from cli_tools_shared.auth import BrowserAutomation


class {{Name}}Browser(BrowserAutomation):
    """Browser automation for {{Name}} via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks only — no methods. The base class handles auth lifecycle
    using these class-level constants. See cli-tool-browser-expert skill for
    selector validation guidance.
    """

    SESSION_NAME = "{{name}}"
    LOGIN_URL = "{{base_url}}/login"
    AUTH_CHECK_URL = "{{base_url}}"
    AUTH_URL_PATTERN = r"/login|/register"
    # AUTH_SUCCESS_SELECTOR must target a VISIBLE element on the authenticated page.
    # Validate against a real page snapshot before shipping.
    AUTH_SUCCESS_SELECTOR = ""
    # AUTH_LOGIN_FORM_SELECTOR is the preferred "logged out" signal — its absence
    # on a non-login URL means the user is authenticated. More durable than positive
    # markers. Recommended: 'input[type="password"], form[action*="login"]'.
    AUTH_LOGIN_FORM_SELECTOR = 'input[type="password"], form[action*="login"]'

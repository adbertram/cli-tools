"""Browser automation for Mercari (declarative hooks only).

The base class (cli_tools_shared.auth.BrowserAutomation) handles the entire
auth lifecycle from these class-level constants. Every value below was
validated against the live authenticated session (see the CLI README's
"Data source" section): mercari.com sits behind Cloudflare and its login
requires an emailed one-time code, so `auth login` completes the code step
via the interactive login flow.
"""

from cli_tools_shared.auth import BrowserAutomation


class MercariBrowser(BrowserAutomation):
    """Browser automation for Mercari via cli_tools_shared.auth.BrowserAutomation."""

    SESSION_NAME = "mercari"
    LOGIN_URL = "https://www.mercari.com/login/"
    # /mypage/ redirects to /login/ when logged out and renders the account
    # shell (no login form) when logged in.
    AUTH_CHECK_URL = "https://www.mercari.com/mypage/"
    # URL match => on a login/signup page => NOT authenticated.
    AUTH_URL_PATTERN = r"/login|/signup"
    # Absence of the login form on a non-login URL => authenticated. Validated:
    # the Mercari login form uses data-testid="EmailInput"/"PasswordInput".
    AUTH_LOGIN_FORM_SELECTOR = 'input[data-testid="PasswordInput"], input[data-testid="EmailInput"]'

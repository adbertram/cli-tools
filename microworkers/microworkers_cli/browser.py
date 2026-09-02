"""Browser automation for Microworkers."""

from cli_tools_shared.auth import BrowserAutomation


class MicroworkersBrowser(BrowserAutomation):
    """Browser automation for Microworkers via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks only — no methods. The base class handles auth lifecycle
    using these class-level constants. See cli-tool-browser-expert skill for
    selector validation guidance.
    """

    SESSION_NAME = "microworkers"
    LOGIN_URL = "https://www.microworkers.com/login.php"
    AUTH_CHECK_URL = "https://www.microworkers.com/account.php"
    # Validated against the live login page 2026-09-02: unauthenticated
    # navigation to account.php redirects to
    # https://www.microworkers.com/login.php.
    AUTH_URL_PATTERN = r"login\.php"
    # AUTH_LOGIN_FORM_SELECTOR is the preferred "logged out" signal — its
    # absence on a non-login URL means the user is authenticated. The live
    # login form (validated 2026-09-02) is a plain POST form to login.php
    # with an <input name="Password" type="password"> field.
    AUTH_LOGIN_FORM_SELECTOR = 'input[name="Password"]'

    # Non-interactive credential-fill login. The live login form (validated
    # 2026-09-02) is: <input type="email" name="Email" id="Email">,
    # <input type="password" name="Password" id="Password">,
    # <input type="submit" name="Button" value="Login">.
    AUTH_LOGIN_USERNAME_SELECTOR = 'input[name="Email"]'
    AUTH_LOGIN_PASSWORD_SELECTOR = 'input[name="Password"]'
    AUTH_LOGIN_SUBMIT_SELECTOR = 'input[type="submit"][name="Button"]'
    AUTH_LOGIN_USERNAME_SECRET = "microworkers-username"
    AUTH_LOGIN_PASSWORD_SECRET = "microworkers-password"

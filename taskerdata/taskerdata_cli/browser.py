"""Browser automation for Taskerdata."""

from cli_tools_shared.auth import BrowserAutomation


class TaskerdataBrowser(BrowserAutomation):
    """Browser automation for Taskerdata via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks only — no methods. The base class handles auth lifecycle
    using these class-level constants. See cli-tool-browser-expert skill for
    selector validation guidance.
    """

    SESSION_NAME = "taskerdata"
    # The real sign-in form lives on the `blog.taskerdata.com` host (validated
    # live against the DOM — worker.taskerdata.com itself just bounces
    # unauthenticated traffic to the marketing homepage at taskerdata.com).
    LOGIN_URL = "https://blog.taskerdata.com/signin"
    AUTH_CHECK_URL = "https://worker.taskerdata.com/"
    # Live-validated: an unauthenticated hit to worker.taskerdata.com bounces
    # to the bare marketing apex domain (https://taskerdata.com/, no
    # subdomain) rather than to a /login-style path, so that bounce target
    # MUST also count as "not authenticated" — otherwise the negative
    # AUTH_LOGIN_FORM_SELECTOR check below false-positives (the marketing
    # homepage has no password field either). The `^` anchor + apex-only
    # pattern deliberately excludes worker./blog.taskerdata.com, which both
    # contain "taskerdata.com" as a substring.
    AUTH_URL_PATTERN = r"/signin|/auth/worker|^https://taskerdata\.com(/|$)"
    # AUTH_SUCCESS_SELECTOR must target a VISIBLE element on the authenticated page.
    # Validate against a real page snapshot before shipping.
    AUTH_SUCCESS_SELECTOR = ""
    # AUTH_LOGIN_FORM_SELECTOR is the preferred "logged out" signal — its absence
    # on a non-login URL means the user is authenticated. More durable than positive
    # markers. Recommended: 'input[type="password"], form[action*="login"]'.
    AUTH_LOGIN_FORM_SELECTOR = 'input[type="password"], form[action*="login"]'

    # Declarative non-interactive login: this Vue/Vuesax sign-in form has
    # exactly one visible text input (email) and one password input, validated
    # live against blog.taskerdata.com/signin's DOM. The submit button carries
    # a stable semantic id="signin" (not the Vuesax-generated field ids, which
    # are unstable across page loads).
    AUTH_LOGIN_USERNAME_SELECTOR = 'input[type="text"]'
    AUTH_LOGIN_PASSWORD_SELECTOR = 'input[type="password"]'
    AUTH_LOGIN_SUBMIT_SELECTOR = "button#signin"
    AUTH_LOGIN_USERNAME_SECRET = "taskerdata-username"
    AUTH_LOGIN_PASSWORD_SECRET = "taskerdata-password"

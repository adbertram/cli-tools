"""Browser automation service for Globiflow CLI."""

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError


class AuthenticationRequired(Exception):
    """Raised when authentication is required but session is invalid."""


class BrowserError(BrowserAutomationError):
    """Browser automation error with context."""


class GlobiflowBrowser(BrowserAutomation):
    """Globiflow browser automation backed by cli_tools_shared BrowserAutomation."""

    SESSION_NAME = "globiflow"
    LOGIN_URL = "https://workflow-automation.podio.com"
    AUTH_CHECK_URL = "https://workflow-automation.podio.com/flows.php"
    AUTH_URL_PATTERN = r"/login|podio\.com/login|accounts\.podio\.com"
    AUTH_FAILURE_URL_PATTERN = r"^https://workflow-automation\.podio\.com/?(?:[?#].*)?$"

    # Non-interactive login: LOGIN_URL redirects through podio.com/oauth/authorize
    # to podio.com/login, a plain Email/Password/Sign-In form (verified via a
    # read-only DOM probe on 2026-08-14 -- stable ids, no framework churn).
    AUTH_LOGIN_USERNAME_SELECTOR = "#email"
    AUTH_LOGIN_PASSWORD_SELECTOR = "#password"
    AUTH_LOGIN_SUBMIT_SELECTOR = "#loginFormSignInButton"
    AUTH_LOGIN_USERNAME_SECRET = "globiflow-username"
    AUTH_LOGIN_PASSWORD_SECRET = "globiflow-password"

    def _complete_noninteractive_login(self, page) -> None:
        """Navigate to the Podio login form before submitting credentials.

        ``LOGIN_URL`` opens the Workflow Automation marketing page, which only
        exposes a "LOGIN" link to a stateful ``/oauth/authorize`` URL. Following
        that link redirects to ``podio.com/login?return_to=...`` where the
        ``#email`` / ``#password`` form actually renders. The base
        implementation submits credentials against whatever page
        ``authenticate`` opened (the marketing page, which has no form), so
        navigate to the form first.
        """
        if not self._is_login_page(page):
            login_link = page.locator("a[href*='oauth/authorize']")
            if login_link.count() == 0:
                raise BrowserAutomationError(
                    "Could not find the Podio OAuth login link on the Workflow "
                    "Automation page."
                )
            href = login_link.first.get_attribute("href")
            if not href:
                raise BrowserAutomationError("Podio OAuth login link has no href.")
            page.goto(href)
            page.wait_for_selector(
                self.AUTH_LOGIN_USERNAME_SELECTOR, state="visible", timeout=15000
            )
        super()._complete_noninteractive_login(page)


BrowserError = BrowserAutomationError
BrowserService = GlobiflowBrowser

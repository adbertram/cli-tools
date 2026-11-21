from cli_tools_shared.auth import BrowserAutomation, Interstitial, INTERSTITIAL_ABORT
from cli_tools_shared.exceptions import ClientError


def require_authenticated_session(browser):
    result = browser.ensure_fresh_session()
    if not result.authenticated:
        raise ClientError(
            f"Saved browser session is not authenticated: {result.reason or 'login required'}. "
            "Run `pluralsight-author auth login --profile PROFILE` with the affected profile name."
        )


class PluralsightAuthorBrowser(BrowserAutomation):
    SESSION_NAME = "pluralsight-author"
    LOGIN_URL = "https://app.pluralsight.com/author-home/opportunities/all"
    AUTH_CHECK_URL = "https://app.pluralsight.com/author-home/opportunities/all"
    AUTH_URL_PATTERN = r"/id(?:[/?]|$)"
    AUTH_LOGIN_ORIGIN = "https://app.pluralsight.com"
    AUTH_LOGIN_USERNAME_SELECTOR = "input#email-address"
    AUTH_LOGIN_USERNAME_SUBMIT_SELECTOR = 'button[type=submit]:has-text("Continue")'
    AUTH_LOGIN_PASSWORD_SELECTOR = "input#password[type=password]"
    AUTH_LOGIN_SUBMIT_SELECTOR = 'button[type=submit]:has-text("Sign In")'
    AUTH_LOGIN_USERNAME_SECRET = "pluralsight-author-dashboard-username"
    AUTH_LOGIN_PASSWORD_SECRET = "pluralsight-author-dashboard-password"
    AUTH_SUCCESS_URL = r"^https://app\.pluralsight\.com/author-home/opportunities/all/?(?:[?#]|$)"
    INTERSTITIALS = (
        Interstitial(
            kind="challenge", label="Pluralsight cloud verification",
            strategy=INTERSTITIAL_ABORT, title_markers=("just a moment",),
            body_markers=("please complete the security check to access the site",),
        ),
    )
    LOGIN_REDIRECT_FRAGMENT = "/id?redirectTo=%2Fauthor-home%2Fopportunities%2Fall"
    LOGIN_PAGE_TITLE = "Sign In | Pluralsight"


class PluralsightAuthorKitBrowser(BrowserAutomation):
    SESSION_NAME = "pluralsight-author-author-kit"
    LOGIN_URL = "https://authors.pluralsight.com/icon-library/"
    AUTH_CHECK_URL = "https://authors.pluralsight.com/icon-library/"
    AUTH_URL_PATTERN = r"/wp-login\.php|/login"
    AUTH_SUCCESS_URL = r"/icon-library/?(?:[?#]|$)"
    AUTH_LOGIN_USERNAME_SELECTOR = "#user_login"
    AUTH_LOGIN_PASSWORD_SELECTOR = "#user_pass"
    AUTH_LOGIN_SUBMIT_SELECTOR = "#wp-submit"
    AUTH_LOGIN_ERROR_SELECTOR = "#login_error"
    AUTH_LOGIN_USERNAME_SECRET = "pluralsight-author-username"
    AUTH_LOGIN_PASSWORD_SECRET = "pluralsight-author-password"
    AUTH_LOGIN_TOTP_SELECTOR = "#authcode"
    AUTH_LOGIN_TOTP_SUBMIT_SELECTOR = "#wp-submit"
    AUTH_LOGIN_TOTP_SECRET = "pluralsight-author-totp-secret"
    LOGIN_PAGE_TITLE = "Log In"

from cli_tools_shared.auth import BrowserAutomation


class PluralsightAuthorBrowser(BrowserAutomation):
    SESSION_NAME = "pluralsight-author"
    LOGIN_URL = "https://app.pluralsight.com/author-home/opportunities/all"
    AUTH_CHECK_URL = "https://app.pluralsight.com/author-home/opportunities/all"
    AUTH_URL_PATTERN = r"/id(?:[/?]|$)"
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

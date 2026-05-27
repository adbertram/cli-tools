"""Browser automation for CVS CLI."""
from cli_tools_shared.auth import BrowserAutomation


class CvsBrowser(BrowserAutomation):
    SESSION_NAME = "cvs"
    LOGIN_URL = "https://www.cvs.com/account-login/look-up"
    AUTH_CHECK_URL = "https://www.cvs.com/pharmacy/rx/prescriptions"
    AUTH_URL_PATTERN = r"/account-login"
    AUTH_LOGIN_FORM_SELECTOR = 'input[autocomplete="username"]'
    AUTH_SUCCESS_SELECTOR = 'h1:has-text("Your prescriptions")'

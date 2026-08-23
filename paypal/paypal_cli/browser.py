"""Declarative PayPal browser-session hooks."""

from cli_tools_shared.auth import PlaywrightBrowserAutomation


class PayPalBrowser(PlaywrightBrowserAutomation):
    """Browser automation for PayPal business account sessions."""

    SESSION_NAME = "paypal"
    MANUAL_LOGIN = True
    LOGIN_URL = "https://www.paypal.com/signin?returnUri=%2Fmep%2Funifiedtransactions%3Ffilter%3D0%26query%3D"
    AUTH_CHECK_URL = "https://www.paypal.com/mep/unifiedtransactions?filter=0&query="
    AUTH_URL_PATTERN = r"/signin|/authflow|/auth/validatecaptcha|/webapps/auth"
    AUTH_FAILURE_URL_PATTERN = r"/signin|/authflow|/auth/validatecaptcha|/webapps/auth"
    AUTH_LOGIN_FORM_SELECTOR = "input[type='password'], input[name='login_password'], input#password"
    AUTH_SUCCESS_URL = r"paypal\.com/(mep/unifiedtransactions|activity|myaccount|business)"
    PLAYWRIGHT_EXECUTABLE_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

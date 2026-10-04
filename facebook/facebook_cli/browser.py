"""Browser automation for Facebook CLI."""
from cli_tools_shared.auth import BrowserAutomation


class FacebookBrowser(BrowserAutomation):
    SESSION_NAME = "facebook"
    LOGIN_URL = "https://www.facebook.com/login"
    AUTH_CHECK_URL = "https://m.facebook.com/"
    AUTH_URL_PATTERN = r"/login"
    AUTH_COOKIE_PATTERNS = ["c_user"]  # c_user cookie exists when logged into Facebook
    AUTH_LOGIN_FORM_SELECTOR = 'input[name="email"], input[name="pass"]'
    AUTH_LOGIN_USERNAME_SELECTOR = 'input[name="email"]'
    AUTH_LOGIN_PASSWORD_SELECTOR = 'input[name="pass"]'
    AUTH_LOGIN_SUBMIT_SELECTOR = 'button[name="login"]'
    AUTH_LOGIN_USERNAME_SECRET = "facebook-username"
    AUTH_LOGIN_PASSWORD_SECRET = "facebook-password"
    AUTH_LOGIN_SECRETS_PROFILE_SCOPED = True
    # A Facebook checkpoint, MFA prompt, or CAPTCHA still needs a person. The
    # shared auth flow attempts the declarative secret-manager login first,
    # then preserves this plain-browser fallback for those human gates.
    MANUAL_LOGIN = True

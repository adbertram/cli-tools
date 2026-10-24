"""Browser automation for Brickfreedom dashboard."""

from cli_tools_shared.auth import PlaywrightBrowserAutomation


class BrickfreedomBrowser(PlaywrightBrowserAutomation):
    """Browser automation for Brickfreedom dashboard."""

    SESSION_NAME = "brickfreedom"
    LOGIN_URL = "https://brickfreedom.com/login"
    AUTH_CHECK_URL = "https://brickfreedom.com/dashboard"
    AUTH_URL_PATTERN = r"/login|/register"
    AUTH_SUCCESS_SELECTOR = 'h2.text-xl'
    PLAYWRIGHT_EXECUTABLE_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    # Non-interactive credential-fill login so an expired saved session
    # self-heals without a human at a terminal.
    AUTH_LOGIN_USERNAME_SELECTOR = 'input[name="email"]'
    AUTH_LOGIN_PASSWORD_SELECTOR = 'input[name="password"]'
    AUTH_LOGIN_SUBMIT_SELECTOR = 'button[type="submit"]'
    AUTH_LOGIN_USERNAME_SECRET = "brickfreedom-legacy-username"
    AUTH_LOGIN_PASSWORD_SECRET = "brickfreedom-legacy-password"

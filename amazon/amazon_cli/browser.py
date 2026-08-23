"""Browser automation for Amazon."""

from cli_tools_shared.auth import BrowserAutomation


class AmazonBrowser(BrowserAutomation):
    """Browser automation for Amazon via cli_tools_shared.BrowserAutomation.

    Declarative hooks only — no methods. The base class handles auth lifecycle
    using these class-level constants. See cli-tool-browser-expert skill for
    selector validation guidance.
    """

    SESSION_NAME = "amazon"
    AUTH_CHECK_URL = "https://www.amazon.com/gp/css/order-history"
    LOGIN_URL = AUTH_CHECK_URL
    AUTH_URL_PATTERN = r"/ap/signin|/login|/register"
    AUTH_SUCCESS_SELECTOR = "#ordersContainer, .js-order-card, [data-order-id]"
    MANUAL_LOGIN = True

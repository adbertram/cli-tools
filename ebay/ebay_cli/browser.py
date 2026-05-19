"""eBay browser automation using cli_tools_shared."""

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError


class EbayBrowser(BrowserAutomation):
    """eBay browser session managed by the shared BrowserAutomation base."""

    SESSION_NAME = "ebay"
    LOGIN_URL = "https://www.ebay.com/signin/"
    AUTH_CHECK_URL = "https://www.ebay.com/mye/myebay/summary"
    AUTH_URL_PATTERN = r"/signin|SignIn|signin\.ebay|login"
    AUTH_COOKIE_PATTERNS = [
        r"nonsession",
        r"ebay",
        r"dp1",
        r"s",
    ]


BrowserService = EbayBrowser
BrowserError = BrowserAutomationError

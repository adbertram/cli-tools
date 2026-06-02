"""Declarative Bricklink browser-session hooks."""

import re

from cli_tools_shared.auth import PlaywrightBrowserAutomation

from .confirmation import CONFIRMATION_CODE_URL_PATTERN


class BricklinkBrowser(PlaywrightBrowserAutomation):
    SESSION_NAME = "bricklink"
    LOGIN_URL = "https://www.bricklink.com/v2/login.page"
    AUTH_CHECK_URL = "https://www.bricklink.com/myMsg.asp"
    # ``identity.lego.com/<locale>/login`` is the real expired-session
    # landing page (e.g. ``identity.lego.com/en-US/login?ReturnUrl=...``).
    # The previous pattern ``identity\.lego\.com/login`` did not match
    # because the locale segment sits between the host and ``/login``.
    # We anchor on the host and a ``login`` segment anywhere in the path
    # so live-auth detection works for every locale.
    AUTH_URL_PATTERN = (
        r"identity\.lego\.com/[^?]*login"
        r"|/v2/login\.page"
    )
    # Shared auth probing checks this before the broad ``AUTH_SUCCESS_URL``.
    AUTH_FAILURE_URL_PATTERN = CONFIRMATION_CODE_URL_PATTERN.pattern
    AUTH_SUCCESS_URL = r"bricklink\.com"
    AUTH_COOKIE_PATTERNS = ()
    PLAYWRIGHT_EXECUTABLE_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    MESSAGES_URL = "https://www.bricklink.com/myMsg.asp"
    CONTACT_URL = "https://www.bricklink.com/contact.asp"
    REFUND_URL = "https://www.bricklink.com/v3/order/refund.page"
    # INVOICE_URL removed 2026-05-16; Bricklink retired `/v3/billing/invoice.page`
    # and the `invoice` command group along with it. See browser_runtime.py for
    # the Invoices comment block.
    ORDER_SEARCH_URL = "https://www.bricklink.com/orderSearch.asp?a=p"
    WANTED_NOTIFY_URL = "https://www.bricklink.com/wantedNotify.asp"

def normalize_subject(subject: str) -> str:
    value = subject.strip()
    while value.lower().startswith("re: "):
        value = value[4:]
    value = re.sub(r"\s*\(view order\)\s*$", "", value, flags=re.IGNORECASE)
    value = value.replace("#", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value.lower()

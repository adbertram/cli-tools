"""Browser automation for Amazon."""

from cli_tools_shared.auth import (
    BrowserAutomation, Interstitial, INTERSTITIAL_ABORT, INTERSTITIAL_CONTINUE,
)


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
    INTERSTITIALS = (
        Interstitial(
            kind="captcha", label="Amazon CAPTCHA", strategy=INTERSTITIAL_ABORT,
            body_markers=("enter the characters you see below", "type the characters you see"),
        ),
        Interstitial(
            kind="continue", label="Amazon Continue shopping",
            strategy=INTERSTITIAL_CONTINUE,
            body_markers=("click the button below to continue shopping",),
            # The observed gate has only hidden inputs. Refuse a form with
            # an image, frame, or visible input instead of solving a challenge.
            continue_selector=(
                "form[action$='/errors_page/validateCaptcha']"
                ":not(:has(input:not([type='hidden']), img, iframe)) "
                "button:has-text('Continue shopping')"
            ),
        ),
    )

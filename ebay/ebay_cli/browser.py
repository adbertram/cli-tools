"""eBay browser automation using cli_tools_shared."""

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError


# JavaScript run on the My-eBay summary page to distinguish a real, rendered
# signed-in page from a URL-preserving error/interstitial. eBay redirects a
# logged-out summary request to sign-in (URL changes, caught by
# AUTH_URL_PATTERN) and a challenged one to /splashui/captcha (caught by
# AUTH_FAILURE_URL_PATTERN), so the only remaining false-healthy path is an
# error page that keeps the summary URL. This flags those. The shared
# AUTH_FAILURE_PAGE_JS hook treats a truthy result as "not authenticated".
EBAY_AUTH_FAILURE_PAGE_JS = """() => {
    const body = document.body ? document.body.innerText : '';
    return /something went wrong|we'?re having trouble|try again later|temporarily unavailable|this page is (currently )?unavailable|access denied|page not found|error reference/i.test(body);
}"""


class EbayBrowser(BrowserAutomation):
    """eBay browser session managed by the shared BrowserAutomation base."""

    SESSION_NAME = "ebay"
    LOGIN_URL = "https://www.ebay.com/signin/"
    AUTH_CHECK_URL = "https://www.ebay.com/mye/myebay/summary"
    AUTH_URL_PATTERN = r"/signin|SignIn|signin\.ebay|login"
    AUTH_FAILURE_URL_PATTERN = r"/splashui/captcha|hcaptcha|recaptcha"
    # Positive authenticated signal: the My eBay summary page requires login.
    # A logged-out (or challenged) session is redirected to signin/captcha and
    # never lands here, so the request URL staying on the summary path is proof
    # of a live authenticated session.
    #
    # NOTE: Do NOT use AUTH_COOKIE_PATTERNS for eBay. eBay sets dozens of
    # anonymous/guest cookies (dp1, nonsession, ebay, s, svid, ...) on every
    # visitor, including logged-out ones, so cookie presence is not an auth
    # signal. Broad patterns there (e.g. r"s", r"ebay") match those guest
    # cookies and make auth status falsely report the browser session as
    # authenticated while listings search — which relies on the same live
    # check — fails. See tests/test_browser_auth_check.py.
    AUTH_SUCCESS_URL = r"/mye/myebay/summary"
    # Truthfulness guard: an error page served at the summary URL matches
    # AUTH_SUCCESS_URL but was never really fetched. See the JS above.
    AUTH_FAILURE_PAGE_JS = EBAY_AUTH_FAILURE_PAGE_JS


BrowserService = EbayBrowser
BrowserError = BrowserAutomationError

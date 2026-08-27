"""eBay browser automation using cli_tools_shared."""

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
from cli_tools_shared.output import print_warning


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

    # eBay error/bot-challenge interstitial. On bot-like access (especially a
    # cold headless-Chromium profile) eBay serves a generic error page titled
    # "🐴 Error Page | eBay" AT THE REQUESTED URL instead of the real content
    # (observed live 2026-08-27 on a /sch/i.html completed-comps search). The
    # interstitial usually clears on a follow-up navigation once the first
    # response has set its challenge cookies — the same behavior as BrickLink's
    # AWS WAF wall (see bricklink_cli/browser_runtime.py::_detect_waf_challenge).
    # Detection is title-based on purpose: the title is the one stable marker,
    # while body-text markers ("something went wrong", ...) can legitimately
    # appear inside listing content on real pages.
    ERROR_PAGE_MAX_RETRIES = 4
    ERROR_PAGE_TITLE_MARKERS = ("Error Page",)

    def _detect_error_page(self, page) -> bool:
        """Return True when the current page is eBay's error interstitial."""
        try:
            title = page.evaluate("document.title") or ""
        except Exception:
            # A title probe can fail transiently mid-navigation; treat that as
            # "no interstitial evidence" — the caller's own content waits will
            # surface a real page failure. Mirrors the bricklink WAF detector.
            return False
        return any(marker in title for marker in self.ERROR_PAGE_TITLE_MARKERS)

    def get_page(self, url: str = None):
        """Get a page like the shared base, retrying past eBay's error page.

        Every browser-backed ebay command funnels through here, so the retry
        is inherited by search, item detail, auth checks, and any future flow.
        Each reload (with a growing backoff) gives eBay's challenge cookies a
        chance to be accepted; if the interstitial survives
        ``ERROR_PAGE_MAX_RETRIES`` reloads, raise a descriptive error instead
        of letting a downstream selector wait misdiagnose the failure as
        "results container not found".
        """
        page = super().get_page(url)
        attempts = 0
        while self._detect_error_page(page):
            attempts += 1
            target = url or page.url
            if attempts > self.ERROR_PAGE_MAX_RETRIES:
                raise BrowserAutomationError(
                    f"eBay is serving its error/bot-challenge page "
                    f"('Error Page') for {target!r} and it did not clear "
                    f"after {self.ERROR_PAGE_MAX_RETRIES} reloads. Try again "
                    "in a minute, or run 'ebay auth login --credential-type "
                    "browser_session' to refresh the session."
                )
            print_warning(
                f"eBay error interstitial detected "
                f"(attempt {attempts}/{self.ERROR_PAGE_MAX_RETRIES}) -- "
                f"reloading {target}"
            )
            page.wait_for_timeout(2000 * attempts)
            page.goto(target)
            self._raise_if_auth_failure_page(page)
        return page


BrowserService = EbayBrowser
BrowserError = BrowserAutomationError

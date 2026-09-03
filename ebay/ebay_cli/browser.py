"""eBay browser automation using cli_tools_shared."""

from typing import Optional

from cli_tools_shared.auth import (
    INTERSTITIAL_ABORT,
    INTERSTITIAL_RELOAD,
    INTERSTITIAL_SETTLE,
    BrowserAutomation,
    BrowserAutomationError,
    Interstitial,
)
from cli_tools_shared.auth import classify_interstitial as _classify_interstitial


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


# --------------------------------------------------------------------------
# eBay interstitial taxonomy
# --------------------------------------------------------------------------
# eBay fronts its pages with three distinct walls. They look alike to a naive
# title check but need opposite handling. All three were captured live on
# 2026-08-28 against
# /sch/i.html?_nkw=LEGO+7097&LH_Complete=1&LH_Sold=1 using an AUTHENTICATED
# session, so none of them is a stale-session symptom.
#
# Declared most-severe first: the shared classifier takes the first match, so
# the captcha rule can never be masked by a broader retryable one.
INTERSTITIAL_CAPTCHA = "captcha"
INTERSTITIAL_CHALLENGE = "challenge"
INTERSTITIAL_ERROR = "error"

EBAY_INTERSTITIALS = (
    # A real human-verification challenge. HARD STOP -- never solved, clicked
    # through, or reloaded around.
    Interstitial(
        kind=INTERSTITIAL_CAPTCHA,
        label="CAPTCHA/human-verification",
        strategy=INTERSTITIAL_ABORT,
        url_markers=("/splashui/captcha", "hcaptcha", "recaptcha"),
        body_markers=("verify you are human",),
    ),
    # /splashui/challenge, titled "Pardon Our Interruption...", body "Checking
    # your browser before you access eBay. Your browser will redirect to your
    # requested content shortly." SELF-CLEARING, not a human challenge:
    # observed resolving to real results on the very next sample. Waited out
    # in place -- re-navigating abandons the redirect eBay just issued.
    Interstitial(
        kind=INTERSTITIAL_CHALLENGE,
        label="browser-check ('Pardon Our Interruption')",
        strategy=INTERSTITIAL_SETTLE,
        url_markers=("/splashui/challenge",),
        title_markers=("pardon our interruption",),
    ),
    # Titled "Error Page", served AT the requested URL with body "SORRY
    # Something went wrong on our end <reference id>". eBay's request-rate
    # wall. Observed sticky: it held for 8s+ of polling without re-navigation
    # and survived re-navigation at ~9.5s spacing, so clearing it needs a real
    # jittered backoff, not a tight reload. Matched on TITLE only on purpose:
    # "something went wrong" legitimately appears inside real listing content.
    Interstitial(
        kind=INTERSTITIAL_ERROR,
        label="error ('Error Page')",
        strategy=INTERSTITIAL_RELOAD,
        title_markers=("error page",),
    ),
)


def classify_interstitial(
    url: str = "", title: str = "", body: str = ""
) -> Optional[Interstitial]:
    """Classify an eBay page against :data:`EBAY_INTERSTITIALS`.

    ``None`` means the page is real content. Lets a scraper classify a
    page-state dict it already captured against the same rules the navigation
    path uses, so there is one source of truth for what an eBay wall is.
    """
    return _classify_interstitial(
        EBAY_INTERSTITIALS, url=url, title=title, body=body
    )


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

    # Walls eBay serves instead of real content. The shared base resolves
    # these on every navigation, so search, item detail, and auth checks all
    # inherit the handling. See EBAY_INTERSTITIALS above for the live evidence
    # behind each rule and the backoff values.
    INTERSTITIALS = EBAY_INTERSTITIALS


BrowserService = EbayBrowser
BrowserError = BrowserAutomationError

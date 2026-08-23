"""Browser automation for AuctionZip (declarative hooks only).

AuctionZip's auction search and lot pages are public (no AuctionZip account is
required to read them), but auctionzip.com sits behind Cloudflare Bot
Management. Unlike Depop's Managed *Challenge* (which auto-clears headless with
a real-Chrome UA), AuctionZip returns Cloudflare's hard WAF block page
("Sorry, you have been blocked" / "Attention Required! | Cloudflare", HTTP 403)
to *every* headless browser — validated live during CLI creation, including the
real `chrome` channel headless. Only a real, headed browser clears it.

`auth login` therefore opens a one-time headed real-Chrome pass at
auctionzip.com; clearing Cloudflare mints a `cf_clearance` cookie in the
persistent profile. That cookie is the auth signal this CLI checks for — there
is no account login form to detect. See `references/authentication/cloudflare.md`
in the browser-automation skill.

`Config.headless` / `Config.browser_user_agent` (config.py) pin the real-Chrome
UA so the reused `cf_clearance` is not invalidated by the default
`HeadlessChrome` UA token.

Auth signal — DOM element, not the `cf_clearance` cookie
-------------------------------------------------------
Reading AuctionZip needs no account login; the auth check only needs to answer
"is Cloudflare cleared?" We use ``AUTH_SUCCESS_SELECTOR`` (the header logo, which
renders only on the real site, never on Cloudflare's block page) rather than an
``AUTH_COOKIE_PATTERNS`` cf_clearance check. Cloudflare re-issues cf_clearance on
every homepage hit, and the shared ``is_authenticated()`` reads cookies with NO
settle wait when a cookie pattern is set — that race made a cookie-based check
~50% flaky against AuctionZip live. With a selector, the shared check waits 2s
for the page to settle before probing the DOM, which is reliable.
"""

from cli_tools_shared.auth import BrowserAutomation


class AuctionzipBrowser(BrowserAutomation):
    """Browser automation for AuctionZip via cli_tools_shared.auth.BrowserAutomation."""

    SESSION_NAME = "auctionzip"
    LOGIN_URL = "https://www.auctionzip.com/"
    AUTH_CHECK_URL = "https://www.auctionzip.com/"
    # The header logo link is present on every real AuctionZip page and absent
    # on Cloudflare's "Sorry, you have been blocked" page — a stable, reliably
    # visible "Cloudflare is cleared" signal (validated live). Leaving
    # AUTH_COOKIE_PATTERNS unset makes the shared is_authenticated() settle the
    # page (2s) before this DOM probe, avoiding the cf_clearance read race.
    AUTH_SUCCESS_SELECTOR = "#logo-link"

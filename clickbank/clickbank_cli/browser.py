"""Browser session automation for the ClickBank affiliate marketplace.

ClickBank's marketplace UI at https://accounts.clickbank.com/marketplace.htm is
publicly browsable -- no login required.  Behind the scenes the SPA calls a
private GraphQL endpoint at ``POST https://accounts.clickbank.com/graphql``
that is not documented in the public REST API and is the only source for the
marketplace search results affiliates need.

Direct HTTP requests to that endpoint from a vanilla httpx client are blocked
by ClickBank's WAF (Cloudflare).  Driving the requests from inside a real
Chromium session that has already rendered the marketplace page sails through
because the WAF has seen the browser fingerprint, cookies, and TLS handshake.

This module exposes the minimum declarative hooks the shared
``BrowserAutomation`` base needs to manage that persistent session.  Auth
checks are intentionally loose -- the marketplace is public, so any rendered
marketplace page counts as "authenticated" for browser-session-presence
purposes.  Lifecycle (storage state, daemon reuse, EOF-safe prompts) is
handled entirely by ``cli_tools_shared``; nothing per-CLI lives here beyond
the constants.
"""

from cli_tools_shared.auth import BrowserAutomation


CLICKBANK_BROWSER_SESSION = "clickbank"


class ClickBankBrowser(BrowserAutomation):
    """BrowserAutomation hooks for the public ClickBank affiliate marketplace.

    Notes on selector choices:

    * The marketplace home page does not present a login form to anonymous
      visitors -- it just renders the catalog.  ``AUTH_LOGIN_FORM_SELECTOR``
      below points at the master account login form (used only when a user
      explicitly navigates to ``accounts.clickbank.com/login``); when the
      marketplace page is loaded, that selector is absent and the session is
      considered authenticated.
    * ``AUTH_URL_PATTERN`` matches any path that looks like a sign-in flow.
      The marketplace itself lives at ``/marketplace.htm`` and does NOT match
      this pattern, so the URL check alone confirms a healthy session.
    """

    SESSION_NAME = CLICKBANK_BROWSER_SESSION

    # The marketplace home page is the canonical "is the session alive" check.
    # It is publicly accessible, requires JS hydration to render results, and
    # is the only origin from which the private /graphql endpoint will accept
    # POSTs without being challenged by Cloudflare.
    AUTH_CHECK_URL = "https://accounts.clickbank.com/marketplace.htm"

    # ClickBank gates the master account dashboard (separate from the
    # marketplace) at https://accounts.clickbank.com/login.htm.  The
    # marketplace itself does NOT require a login.  This URL is only used by
    # 'clickbank auth login' for users who want to sign in to their primary
    # ClickBank account inside the same persistent profile (so the affiliate
    # nickname auto-populates in hoplink generators on the offer page).
    LOGIN_URL = "https://accounts.clickbank.com/login.htm"

    # Any path that looks like a master-account login/signup flow counts as
    # "not authenticated" for the master-account credential.  The marketplace
    # is unaffected -- /marketplace.htm doesn't match.
    AUTH_URL_PATTERN = r"/login\.htm|/signup|/register"

    # Absence-of-login-form check.  When we are on a non-login URL and there
    # is no visible password input or master-account login form, the
    # persistent session is healthy.
    AUTH_LOGIN_FORM_SELECTOR = (
        'input[type="password"], '
        'input[name="password"], '
        'form[action*="login"], '
        'form#loginForm'
    )

    # ClickBank's master-account login presents a Cloudflare turnstile that
    # blocks headless automation.  The browser MUST come up headed so the
    # human can solve the challenge once; subsequent reads of /graphql reuse
    # the cookies inside the same persistent profile and run headless.
    AUTOMATION_HEADED = True

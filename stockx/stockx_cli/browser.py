"""Browser automation for StockX (declarative hooks only).

stockx.com is fronted by Cloudflare and serves a "Please login to continue"
bot wall to the default ``HeadlessChrome/<v>`` User-Agent (verified live: page
title "Error", body "Please log in to verify you are not a bot"). With the real
Chrome UA pinned by ``Config.browser_user_agent``, the same headless profile
loads the full public catalog with no StockX account, so ``products search``,
``products list``, ``products get``, and ``products market`` all work on a cold
profile.

``auth login`` therefore exists for account-scoped work, not for read access.

Validated live against stockx.com: the signed-out home page serves exactly one
visible "Log In" nav control, and no password field or ``form[action*=login]``
— StockX signs in on a separate Auth0 host, so the usual login-form selector is
absent even when signed out and would report every cold profile as
authenticated. The logged-out signal is therefore that nav control itself; its
absence on a non-login URL means the profile is signed in.
"""

from cli_tools_shared.auth import BrowserAutomation

# Truthy result means NOT authenticated. Polls for the signed-out "Log In" nav
# control, and treats an unhydrated page as signed out as well.
_LOGGED_OUT_JS = """async () => {
    const isLoginControl = () => Array.from(
        document.querySelectorAll('header a, header button, nav a, nav button')
    ).some(el => /^(log ?in|sign ?in)$/i.test((el.textContent || '').trim()));
    const isHydrated = () =>
        document.querySelectorAll('header a, nav a').length > 5;
    for (let attempt = 0; attempt < 10; attempt++) {
        if (isLoginControl()) { return true; }
        if (isHydrated()) { return false; }
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
    return true;
}"""


class StockxBrowser(BrowserAutomation):
    """Browser automation for StockX via cli_tools_shared.auth.BrowserAutomation."""

    SESSION_NAME = "stockx"
    LOGIN_URL = "https://stockx.com/login"
    AUTH_CHECK_URL = "https://stockx.com/"
    AUTH_URL_PATTERN = r"/login|/signup"
    # Cloudflare's managed challenge can take most of a minute to settle, so
    # poll rather than report a false block on the first check.
    AUTH_CHALLENGE_ATTEMPTS = 4
    # stockx.com renders its header nav about four seconds after navigation
    # returns (measured live), so a plain selector check races hydration and
    # reports a cold profile as signed in. This hook polls for the control and
    # reports "not authenticated" for an unhydrated page too, so a bot wall or
    # a blank document can never read as a healthy session.
    AUTH_FAILURE_PAGE_JS = _LOGGED_OUT_JS

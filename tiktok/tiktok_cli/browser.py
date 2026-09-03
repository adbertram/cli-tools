"""Browser automation for TikTok (declarative hooks only).

`favorites list` has no public or internal API path that works without a
logged-in session: TikTok's own web app posts every "Favorites" tab query to
`GET /api/user/collect/item_list/` on tiktok.com's own domain, signed in-page
by TikTok's ``webmssdk`` (msToken / X-Bogus headers minted client-side). An
unauthenticated probe of that exact endpoint returns HTTP 200 with an empty
body — the route exists, but requires the caller's own session cookies. The
client therefore runs the request INSIDE the live tiktok.com page through
`page.evaluate()` (see client.py), the same in-page-fetch pattern this repo
already uses for OfferUp — not click-driven UI scraping.

Login detection: TikTok's header renders a "Log in" nav control when signed
out (React-hydrated, so the SSR HTML alone does not show it) and no such
control once signed in. This mirrors the proven detection in
`offerup_cli/browser.py`.
"""

from cli_tools_shared.auth import BrowserAutomation

# Truthy result means NOT authenticated. Polls for the signed-out "Log in" nav
# control, and treats an unhydrated page as signed out as well.
_LOGGED_OUT_JS = """async () => {
    const isLoginControl = () => Array.from(
        document.querySelectorAll('header a, header button, nav a, nav button')
    ).some(el => /^(log ?in|sign ?in)$/i.test((el.textContent || '').trim()));
    const isHydrated = () =>
        document.querySelectorAll('header a, header button').length > 2;
    for (let attempt = 0; attempt < 10; attempt++) {
        if (isLoginControl()) { return true; }
        if (isHydrated()) { return false; }
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
    return true;
}"""


class TiktokBrowser(BrowserAutomation):
    """Browser automation for TikTok via cli_tools_shared.auth.BrowserAutomation."""

    SESSION_NAME = "tiktok"
    LOGIN_URL = "https://www.tiktok.com/login"
    AUTH_CHECK_URL = "https://www.tiktok.com/"
    AUTH_URL_PATTERN = r"/login"
    # Polls for the control rather than reading the DOM once, so a slow nav
    # render cannot report a cold profile as signed in, and an unhydrated page
    # reports "not authenticated" instead of a false healthy session.
    AUTH_FAILURE_PAGE_JS = _LOGGED_OUT_JS

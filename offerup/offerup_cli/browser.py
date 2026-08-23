"""Browser automation for OfferUp (declarative hooks only).

OfferUp's marketplace feed is public: `listings search`, `listings list`, and
`listings get` all work on a cold profile with no OfferUp account, because the
client runs OfferUp's own `/api/graphql` calls inside a live offerup.com page
(see client.py). `auth login` is therefore optional, and exists so a signed-in
session can be saved for account-scoped work.

Validated live against offerup.com: the signed-out home page serves exactly one
visible "Log in" nav control, and no password field or `form[action*=login]` —
OfferUp's sign-in runs in a modal, so the usual login-form selector is absent
even when signed out and would report every cold profile as authenticated. The
logged-out signal is therefore that nav control itself; its absence on a
non-login URL means the profile is signed in.
"""

from cli_tools_shared.auth import BrowserAutomation

# Truthy result means NOT authenticated. Polls for the signed-out "Log in" nav
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


class OfferupBrowser(BrowserAutomation):
    """Browser automation for OfferUp via cli_tools_shared.auth.BrowserAutomation."""

    SESSION_NAME = "offerup"
    LOGIN_URL = "https://offerup.com/login"
    AUTH_CHECK_URL = "https://offerup.com/"
    AUTH_URL_PATTERN = r"/login|/signup"
    # This hook polls for the control rather than reading the DOM once, so a
    # slow nav render cannot report a cold profile as signed in, and it reports
    # "not authenticated" for an unhydrated page too, so a blank document can
    # never read as a healthy session.
    AUTH_FAILURE_PAGE_JS = _LOGGED_OUT_JS

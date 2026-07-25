"""Browser automation for Depop (declarative hooks only).

Depop's marketplace search is public (no Depop account required), but
depop.com sits behind Cloudflare Bot Management (`__cf_bm` / `cf_clearance`
cookies, `server: cloudflare` header — validated live). `auth login` opens a
headed real-Chrome session at depop.com; Cloudflare's Managed Challenge
cleared silently within a few seconds in every live test (no interactive
"verify you are human" checkbox was ever observed), minting a `cf_clearance`
cookie in the persistent profile. That cookie is the auth signal this CLI
checks for — see `references/authentication/cloudflare.md` in the
browser-automation skill.

Subsequent `search` calls reuse that profile headlessly. `Config.headless` /
`Config.browser_user_agent` (config.py) pin the real-Chrome UA so the reused
`cf_clearance` is not invalidated by the default `HeadlessChrome` UA token.
"""

from cli_tools_shared.auth import BrowserAutomation


class DepopBrowser(BrowserAutomation):
    """Browser automation for Depop via cli_tools_shared.auth.BrowserAutomation."""

    SESSION_NAME = "depop"
    LOGIN_URL = "https://www.depop.com/"
    AUTH_CHECK_URL = "https://www.depop.com/"
    # cf_clearance is Cloudflare's proof-of-passed-challenge cookie (validated
    # live). There is no login form to check for on depop.com; the presence
    # of a live cf_clearance cookie is the ground-truth "ready to search" signal.
    AUTH_COOKIE_PATTERNS = [r"^cf_clearance$"]

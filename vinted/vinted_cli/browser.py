"""Browser session automation for Vinted.

Vinted needs no account. Cloudflare fronts it and raises a managed JavaScript
challenge against clients it does not trust, which a plain HTTP client cannot
pass. A real Chrome window passes it, and Cloudflare writes a `cf_clearance`
cookie into the persistent profile. Every later command reuses that profile
headless with the same user agent, so no window opens again.

`Config.get_browser()` rewrites LOGIN_URL and AUTH_CHECK_URL for the
marketplace named by BASE_URL, because each Vinted country site is a separate
host with its own clearance.
"""

from cli_tools_shared.auth import BrowserAutomation


class VintedBrowser(BrowserAutomation):
    """BrowserAutomation hooks for the Vinted marketplace session."""

    SESSION_NAME = "vinted"
    LOGIN_URL = "https://www.vinted.com/"
    AUTH_CHECK_URL = "https://www.vinted.com/"

    # `anon_id` is the cookie the catalog API needs, and Vinted sets it only
    # when the page really rendered. A Cloudflare challenge page never sets it,
    # so its presence proves the challenge cleared.
    AUTH_COOKIE_PATTERNS = [r"^anon_id$"]
    AUTH_COOKIE_DOMAINS = ("vinted.com", "www.vinted.com")

    # The first pass must be headed. Cloudflare mints a clearance only for a
    # real browser window. Later commands run headless from the saved profile.
    AUTOMATION_HEADED = True

    # Cloudflare's managed challenge clears without interaction, but it can take
    # most of a minute. A single immediate check reports a false block, so the
    # shared engine polls for about 75 seconds.
    AUTH_CHALLENGE_ATTEMPTS = 25
    AUTH_CHALLENGE_POLL_MS = 3000

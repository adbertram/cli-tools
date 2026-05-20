"""Browser automation for {{ServiceName}} dashboard.

This file should be ~15 lines. It declares auth detection hooks as class
constants and delegates ALL logic to cli_tools_common.BrowserAutomation.

DO NOT add custom methods here. If you need custom behavior, use the
overridable hooks listed in references/hooks-reference.md.
"""

from cli_tools_common.browser_automation import BrowserAutomation

from .config import get_config


class {{ServiceName}}Browser(BrowserAutomation):
    """Browser automation for {{ServiceName}}."""

    # === Required class constants (auth detection hooks) ===

    SESSION_NAME = "{{cli_name}}"
    # Unique playwright-cli session name. Must be unique across all CLIs.

    LOGIN_URL = "https://{{domain}}/login"
    # URL to open for interactive headed login.

    AUTH_CHECK_URL = "https://{{domain}}/dashboard"
    # URL to load in headless mode to verify authentication.
    # Must be a page that requires login (redirects to login if not auth'd).

    AUTH_URL_PATTERN = r"/login|/register"
    # Regex: if current URL matches this pattern, user is on login page (NOT authenticated).
    # Include third-party auth providers if applicable: r"/login|identity\.provider\.com"

    AUTH_SUCCESS_SELECTOR = "h2.page-title"
    # CSS selector that is VISIBLE only when authenticated.
    # MUST target a visible element — avoid collapsed menus, hidden sidebars, lazy-loaded images.
    # Validate with: playwright-cli page goto "<AUTH_CHECK_URL>" && playwright-cli page snapshot

    # === Optional class constants (uncomment if needed) ===

    # AUTH_COOKIE_PATTERNS = ["session_token", r"auth\.jwt"]
    # Cookie name regexes indicating valid session. Checked before selector.

    # AUTH_SUCCESS_URL = "/dashboard"
    # URL pattern indicating successful authentication.

    # AUTH_STORAGE_KEY = "auth_token"
    # localStorage key that must exist when authenticated.

    # LOGIN_TIMEOUT = 300
    # Seconds to wait for manual login (default: 300).

    # AUTH_CHECK_TTL = 300
    # Cache successful auth check N seconds (default: 300).

    def __init__(self, config=None):
        config = config or get_config()
        super().__init__(config)

"""Slack browser automation — extracts session tokens via persistent profiles."""
import re
import sys

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
from cli_tools_shared.http_session import BrowserAuthState, BrowserAuthenticatedHttpClient


class SlackBrowser(BrowserAutomation):
    """Browser automation for Slack session token capture.

    Extends BrowserAutomation to:
    - Navigate to Slack signin
    - Wait for user to complete login
    - Extract xoxc token from localStorage (via _on_authenticated hook)
    - Save token and 'd' cookie to profile .env

    Per-profile session isolation is handled by the SESSION_NAME +
    profile name combination in the playwright CLI.
    """

    SESSION_NAME = "slack"
    LOGIN_URL = "https://slack.com/signin"
    AUTH_CHECK_URL = "https://app.slack.com/client"
    AUTH_URL_PATTERN = r"/signin|/sign-in|workspace-signin"
    AUTH_SUCCESS_URL = ""  # Disabled — using custom _check_auth
    AUTH_COOKIE_PATTERNS = ["^d$"]  # Slack 'd' session cookie
    AUTH_COOKIE_DOMAINS = ("slack.com", "app.slack.com")

    def __init__(self, config):
        super().__init__(config)

    def _session_name(self) -> str:
        """Include profile name for per-workspace isolation."""
        profile_name = self._get_profile_name()
        return f"slack-{profile_name}"

    def _get_profile_name(self) -> str:
        if hasattr(self.config, "get_active_profile_name"):
            return self.config.get_active_profile_name()
        if hasattr(self.config, "profile") and self.config.profile:
            return self.config.profile
        return "default"

    def auth_state(self) -> BrowserAuthState:
        """Return the saved Slack browser auth state."""
        return BrowserAuthState.from_config(self.config)

    def http_client(self) -> BrowserAuthenticatedHttpClient:
        """Return an HTTP client backed by the saved Slack browser state."""
        return BrowserAuthenticatedHttpClient(
            self.auth_state(),
            allowed_domains=self.AUTH_COOKIE_DOMAINS,
            required_cookies=("d",),
            headers={"Accept": "application/json"},
        )

    def _check_auth(self, page) -> bool:
        """Check if the page shows an authenticated Slack workspace.

        With persistent profiles, there's a single page. We check the URL
        and fall back to a cookie check.
        """
        if self._check_url_authenticated(page.url):
            return True

        # Cookie fallback: 'd' cookie set after auth
        try:
            cookies = page.context.cookies(
                ["https://slack.com", "https://app.slack.com"]
            )
            if any(c["name"] == "d" and c.get("value") for c in cookies):
                return True
        except Exception:
            pass

        return False

    @staticmethod
    def _check_url_authenticated(url: str) -> bool:
        """Check if a URL indicates successful Slack authentication."""
        if "/client/" in url or url.endswith("/client"):
            return True
        if "app.slack.com" in url:
            if not re.search(r'signin|sign-in|workspace-signin', url):
                return True
        return False

    def _on_authenticated(self, page):
        """After login: extract xoxc token from localStorage and save to profile .env."""
        # Navigate to /client to ensure Slack JS populates localStorage
        if "/client" not in page.url:
            print(f"Navigating to Slack client (from {page.url})...", file=sys.stderr)
            page.goto("https://app.slack.com/client", wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

        # Extract tokens from localStorage
        js_code = """() => {
            try {
                const config = JSON.parse(localStorage.localConfig_v2 || '{}');
                const teams = config.teams || {};
                const results = [];
                for (const [teamId, teamData] of Object.entries(teams)) {
                    if (teamData.token) {
                        results.push({
                            team_id: teamId,
                            team_name: teamData.name || '',
                            team_domain: teamData.domain || '',
                            token: teamData.token
                        });
                    }
                }
                return results;
            } catch(e) {
                return [];
            }
        }"""

        token_data = page.evaluate(js_code)

        if not token_data:
            # Retry: Slack JS may need more time to populate localStorage
            print("Waiting for Slack to populate session data...", file=sys.stderr)
            page.wait_for_timeout(5000)
            token_data = page.evaluate(js_code)

        if token_data:
            if len(token_data) == 1:
                selected = token_data[0]
            else:
                team_id = self.config._get("SLACK_TEAM_ID")
                if not team_id:
                    teams = ", ".join(
                        ws.get("team_name") or ws.get("team_domain") or ws["team_id"]
                        for ws in token_data
                    )
                    raise BrowserAutomationError(
                        "Multiple Slack workspaces found. Set SLACK_TEAM_ID before login. "
                        f"Available workspaces: {teams}"
                    )
                matches = [ws for ws in token_data if ws["team_id"] == team_id]
                if not matches:
                    raise BrowserAutomationError(f"SLACK_TEAM_ID {team_id} was not found in the browser session.")
                selected = matches[0]

            self.config._set("ACCESS_TOKEN", selected["token"])
            print(f"Token captured for workspace: {selected.get('team_name', selected['team_id'])}", file=sys.stderr)
        else:
            print("Warning: Could not extract token from localStorage", file=sys.stderr)

        # Get 'd' cookie and store as REFRESH_TOKEN
        cookies = page.context.cookies(["https://slack.com", "https://app.slack.com"])
        d_cookie = next((c["value"] for c in cookies if c["name"] == "d"), None)
        if d_cookie:
            self.config._set("REFRESH_TOKEN", d_cookie)

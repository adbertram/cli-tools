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


def _slack_get_profile_name(self) -> str:
    if hasattr(self.config, "get_active_profile_name"):
        return self.config.get_active_profile_name()
    if hasattr(self.config, "profile") and self.config.profile:
        return self.config.profile
    return "default"


def _slack_session_name(self) -> str:
    return f"slack-{self._get_profile_name()}"


def _slack_auth_state(self) -> BrowserAuthState:
    return BrowserAuthState.from_config(self.config)


def _slack_http_client(self) -> BrowserAuthenticatedHttpClient:
    return BrowserAuthenticatedHttpClient(
        self.auth_state(),
        allowed_domains=self.AUTH_COOKIE_DOMAINS,
        required_cookies=("d",),
        headers={"Accept": "application/json"},
    )


def _slack_check_url_authenticated(url: str) -> bool:
    if "/client/" in url or url.endswith("/client"):
        return True
    if "app.slack.com" in url and not re.search(r"signin|sign-in|workspace-signin", url):
        return True
    return False


def _slack_check_auth(self, page) -> bool:
    if self._check_url_authenticated(page.url):
        return True
    try:
        cookies = page.context.cookies(["https://slack.com", "https://app.slack.com"])
        return any(cookie["name"] == "d" and cookie.get("value") for cookie in cookies)
    except Exception:
        return False


def _slack_on_authenticated(self, page) -> None:
    if "/client" not in page.url:
        print(f"Navigating to Slack client (from {page.url})...", file=sys.stderr)
        page.goto("https://app.slack.com/client", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

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
                    workspace.get("team_name") or workspace.get("team_domain") or workspace["team_id"]
                    for workspace in token_data
                )
                raise BrowserAutomationError(
                    "Multiple Slack workspaces found. Set SLACK_TEAM_ID before login. "
                    f"Available workspaces: {teams}"
                )
            matches = [workspace for workspace in token_data if workspace["team_id"] == team_id]
            if not matches:
                raise BrowserAutomationError(
                    f"SLACK_TEAM_ID {team_id} was not found in the browser session."
                )
            selected = matches[0]

        self.config._set("ACCESS_TOKEN", selected["token"])
        print(
            f"Token captured for workspace: {selected.get('team_name', selected['team_id'])}",
            file=sys.stderr,
        )
    else:
        print("Warning: Could not extract token from localStorage", file=sys.stderr)

    cookies = page.context.cookies(["https://slack.com", "https://app.slack.com"])
    d_cookie = next((cookie["value"] for cookie in cookies if cookie["name"] == "d"), None)
    if d_cookie:
        self.config._set("REFRESH_TOKEN", d_cookie)


SlackBrowser._get_profile_name = _slack_get_profile_name
SlackBrowser._session_name = _slack_session_name
SlackBrowser.auth_state = _slack_auth_state
SlackBrowser.http_client = _slack_http_client
SlackBrowser._check_url_authenticated = staticmethod(_slack_check_url_authenticated)
SlackBrowser._check_auth = _slack_check_auth
SlackBrowser._on_authenticated = _slack_on_authenticated

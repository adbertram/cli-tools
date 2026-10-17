"""Browser session automation for Garrul.

Garrul's only admin auth is a session cookie minted by an OAuth sign-in, so the
login has to happen in a real browser. Every command after that is a plain
HTTP request carrying the cookie, and `session_store` keeps a copy of that
cookie so the requests never have to go back through Chromium.
"""

from urllib.parse import urlparse

import requests
from cli_tools_shared.auth import AuthResult, BrowserAutomation, BrowserAutomationError
from cli_tools_shared.output import print_warning

from . import session_store

LOGIN_PATH = "/api/v1/auth/github/start"
AUTH_CHECK_PATH = "/admin"
AUTH_TIMEOUT_SECONDS = 15


def _cookie_matches_host(entry: dict, host: str) -> bool:
    """A cookie belongs to the instance when its domain covers the instance host."""
    domain = str(entry.get("domain") or "").lstrip(".").lower()
    if not domain:
        return False
    normalized = host.lower()
    return normalized == domain or normalized.endswith("." + domain)


class GarrulBrowser(BrowserAutomation):
    """BrowserAutomation hooks for the Garrul GitHub OAuth sign-in (default instance)."""

    SESSION_NAME = "garrul"
    LOGIN_URL = "https://comments.adamtheautomator.com/api/v1/auth/github/start"
    AUTH_CHECK_URL = "https://comments.adamtheautomator.com/admin"
    # Logged-out signal: /admin answers 401 with this heading and no app shell.
    AUTH_LOGIN_FORM_SELECTOR = 'h1:has-text("Sign in required")'

    def _on_authenticated(self, page) -> None:
        """Keep the cookie the Worker issued, outside the shared Chromium jar.

        The login itself already succeeded, so a failure to cache must not fail
        the login: warn and leave the browser profile as the only source, which
        is where this tool used to lose the session.
        """
        host = urlparse(self.AUTH_CHECK_URL).hostname or ""
        try:
            live = self.live_cookies()
        except Exception as exc:  # noqa: BLE001 - any browser failure degrades to the old path
            print_warning(f"Could not read the session cookie after login: {exc}")
            return
        wanted = [
            cookie
            for cookie in live
            if cookie.get("name") in session_store.SESSION_COOKIE_NAMES and _cookie_matches_host(cookie, host)
        ]
        if not wanted:
            print_warning(f"The login left no Garrul session cookie for {host}.")
            return
        try:
            session_store.save(self.config, wanted)
        except Exception as exc:  # noqa: BLE001 - see docstring
            print_warning(f"Could not store the session cookie for reuse: {exc}")

    def is_authenticated(self) -> AuthResult:
        """Report whether the session actually works, without launching Chrome.

        The inherited check drives a live page, which on this host queues behind
        the shared desktop lease and can wait ten minutes for a demo to finish.
        When the CLI holds the cookie the Worker issued, one admin GET is the
        same ground truth: 200 means the session is live, 401 means it is not.
        """
        stored = session_store.load(self.config)
        if not stored:
            return super().is_authenticated()
        cookie_header = "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in stored)
        url = self.config.instance_origin + AUTH_CHECK_PATH
        try:
            response = requests.get(
                url,
                headers={"Cookie": cookie_header},
                timeout=AUTH_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise BrowserAutomationError(f"Could not reach {url} to verify the stored session: {exc}") from exc
        return AuthResult(
            authenticated=response.status_code == 200,
            live_check=True,
            available=True,
            reason="" if response.status_code == 200 else f"{url} answered HTTP {response.status_code}",
        )

    def close(self) -> None:
        """Close an open browser; never start one just to close it.

        `auth status` closes the browser it just used. When the stored cookie
        answered the check, nothing was opened, and the inherited close would
        launch Chromium to shut it down again.
        """
        if self._service is None:
            return
        super().close()


def browser_for(config) -> GarrulBrowser:
    """Return the browser bound to the instance named by BASE_URL.

    The class constants describe the default instance. BASE_URL may point at any
    other Garrul instance (a local `wrangler dev` one, for example), so the two
    URL hooks are always taken from the active configuration.
    """
    browser = GarrulBrowser(config)
    browser.LOGIN_URL = config.instance_origin + LOGIN_PATH
    browser.AUTH_CHECK_URL = config.instance_origin + AUTH_CHECK_PATH
    return browser

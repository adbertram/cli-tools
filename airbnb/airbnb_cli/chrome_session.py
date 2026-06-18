"""Import and verify Airbnb authentication from Chrome cookies."""

from __future__ import annotations

import re
from typing import Any

import requests
from cli_tools_shared import get_activity_logger
from cli_tools_shared.exceptions import ClientError

from .chrome_cookies import read_airbnb_cookies

LOGGER = get_activity_logger("airbnb")


class AirbnbChromeSession:
    """Chrome-session auth adapter used by the shared auth commands."""

    def __init__(self, config):
        self.config = config

    def close(self) -> None:
        return None

    def clear_session(self) -> None:
        self.config.clear_session()

    def is_authenticated(self) -> bool:
        return self.test_session().get("authenticated") is True

    def login(self, force: bool = False) -> dict[str, Any]:
        LOGGER.info("auth_login force=%s", force)
        if force:
            self.config.clear_session()
        elif getattr(self.config, "has_saved_session", lambda: False)():
            status = self.test_session()
            if status.get("authenticated") is True:
                LOGGER.info("auth_login already_authenticated=true")
                return {"success": True, "message": "Airbnb Chrome session already works."}

        cookies = read_airbnb_cookies()
        api_key = self._extract_api_key(cookies)
        self.config.save_chrome_session(cookies, api_key)

        status = self.test_session()
        if status.get("authenticated") is True:
            LOGGER.info("auth_login imported_session_authenticated=true")
            return {"success": True, "message": "Imported Airbnb Chrome session."}

        self.config.clear_session()
        LOGGER.info("auth_login imported_session_authenticated=false")
        raise ClientError(status.get("error") or "Imported Airbnb Chrome session failed live verification.")

    def test_session(self) -> dict[str, Any]:
        if not getattr(self.config, "has_saved_session", lambda: False)():
            LOGGER.info("auth_test authenticated=false saved_session=false")
            return {
                "authenticated": False,
                "api_test": "failed: no saved Airbnb Chrome session",
                "error": "No saved Airbnb Chrome session. Run 'airbnb auth login'.",
            }

        from .client import AirbnbClient

        try:
            AirbnbClient(config=self.config, max_retries=0).verify_host_session()
        except ClientError as exc:
            LOGGER.info("auth_test authenticated=false api_test=failed")
            return {"authenticated": False, "api_test": f"failed: {exc}", "error": str(exc)}
        LOGGER.info("auth_test authenticated=true api_test=passed")
        return {"authenticated": True, "api_test": "passed"}

    def _extract_api_key(self, cookies: list[dict]) -> str:
        LOGGER.info("extract_api_key")
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.config.browser_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        for cookie in cookies:
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie["domain"],
                path=cookie.get("path") or "/",
                secure=bool(cookie.get("secure")),
            )

        base_url = getattr(self.config, "base_url", "https://www.airbnb.com").rstrip("/")
        response = session.get(f"{base_url}/hosting", timeout=30)
        if response.status_code >= 400:
            raise ClientError(f"Airbnb hosting page returned HTTP {response.status_code} while extracting API key.")

        patterns = (
            r'"apiKey"\s*:\s*"([^"]+)"',
            r'"airbnbApiKey"\s*:\s*"([^"]+)"',
            r'"X-Airbnb-API-Key"\s*:\s*"([^"]+)"',
            r"x-airbnb-api-key['\"]?\s*[:=]\s*['\"]([^'\"]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, response.text, re.IGNORECASE)
            if match:
                return match.group(1)

        raise ClientError("Could not find Airbnb API key in the Chrome-authenticated hosting page.")


def airbnb_chrome_login(config, force: bool = False) -> dict[str, Any]:
    return AirbnbChromeSession(config).login(force=force)


def airbnb_auth_test(config) -> dict[str, Any]:
    return AirbnbChromeSession(config).test_session()

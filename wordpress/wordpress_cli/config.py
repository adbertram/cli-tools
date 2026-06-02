"""Configuration management for Wordpress CLI."""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):

    DIST_NAME = "wordpress-cli"
    CREDENTIAL_TYPES = [CredentialType.USERNAME_PASSWORD]
    DEFAULT_BASE_URL = "https://example.com/wp-json/wp/v2"
    ROOT_CONFIG_FIELDS = ("URL",)
    ADDITIONAL_AUTH_FIELDS = (
        "APP_PASSWORD",
        "WPCOM_CLIENT_ID",
        "WPCOM_CLIENT_SECRET",
        "WPCOM_SITE",
        "WPCOM_REDIRECT_URI",
        "WPCOM_ACCESS_TOKEN",
        "WPCOM_TOKEN_TYPE",
        "WPCOM_SCOPE",
    )
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = (
        "APP_PASSWORD",
        "WPCOM_CLIENT_SECRET",
    )
    OPTIONAL_SECRET_FIELDS = (
        "WPCOM_CLIENT_SECRET",
    )
    SECRET_NAME_OVERRIDES = {
        "USERNAME": "wordpress-username",
        "PASSWORD": "wordpress-app-password",
        "APP_PASSWORD": "wordpress-app-password",
        "WPCOM_CLIENT_SECRET": "wordpress-wpcom-client-secret",
    }
    WPCOM_REQUIRED_FIELDS = (
        "WPCOM_CLIENT_ID",
        "WPCOM_CLIENT_SECRET",
        "WPCOM_SITE",
        "WPCOM_REDIRECT_URI",
    )

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    def _get(self, key):
        """Override to support WordPress-specific env var names.

        Maps PASSWORD -> APP_PASSWORD and BASE_URL -> URL-derived value
        for backwards compatibility with existing .env files.
        """
        val = super()._get(key)
        if val is not None:
            return val

        # Fall back: PASSWORD -> APP_PASSWORD
        if key == "PASSWORD":
            return super()._get("APP_PASSWORD")

        # Fall back: BASE_URL -> constructed from URL
        if key == "BASE_URL":
            url = super()._get("URL")
            if url:
                url = url.rstrip("/")
                if not url.endswith("/wp-json/wp/v2"):
                    url = f"{url}/wp-json/wp/v2"
                return url

        return None

    @property
    def app_password(self) -> Optional[str]:
        """Get WordPress Application Password."""
        return self._get("APP_PASSWORD") or self._get("PASSWORD")

    @property
    def url(self) -> Optional[str]:
        """Get WordPress site URL."""
        return super()._get("URL")

    @property
    def wpcom_access_token(self) -> Optional[str]:
        """Get WordPress.com OAuth access token for Jetpack management APIs."""
        return self._get("WPCOM_ACCESS_TOKEN")

    @property
    def wpcom_client_id(self) -> Optional[str]:
        """Get WordPress.com OAuth client id."""
        return self._get("WPCOM_CLIENT_ID")

    @property
    def wpcom_client_secret(self) -> Optional[str]:
        """Get WordPress.com OAuth client secret."""
        return self._get("WPCOM_CLIENT_SECRET")

    @property
    def wpcom_site(self) -> Optional[str]:
        """Get the WordPress.com site identifier for Jetpack management APIs."""
        return self._get("WPCOM_SITE")

    @property
    def wpcom_redirect_uri(self) -> Optional[str]:
        """Get the registered WordPress.com OAuth redirect URI."""
        return self._get("WPCOM_REDIRECT_URI")

    @property
    def wpcom_token_type(self) -> Optional[str]:
        """Get saved WordPress.com OAuth token type."""
        return self._get("WPCOM_TOKEN_TYPE")

    @property
    def wpcom_scope(self) -> Optional[str]:
        """Get saved WordPress.com OAuth scope."""
        return self._get("WPCOM_SCOPE")

    def has_wpcom_credentials(self) -> bool:
        """Check whether the secondary WordPress.com credential bundle is complete."""
        return all(self._get(field) for field in self.WPCOM_REQUIRED_FIELDS)

    def get_missing_wpcom_credentials(self) -> list[str]:
        """Return missing WordPress.com credential field names."""
        return [field for field in self.WPCOM_REQUIRED_FIELDS if not self._get(field)]

    def save_wpcom_credentials(
        self,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        site: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> None:
        """Save provided WordPress.com credential fields and clear any stale token."""
        updates = {
            "WPCOM_CLIENT_ID": client_id,
            "WPCOM_CLIENT_SECRET": client_secret,
            "WPCOM_SITE": site,
            "WPCOM_REDIRECT_URI": redirect_uri,
        }
        changed = False
        for field, value in updates.items():
            if value is None:
                continue
            self._set(field, value)
            changed = True

        if changed:
            self.clear_wpcom_access_token()

    def save_wpcom_access_token(
        self,
        access_token: str,
        *,
        token_type: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> None:
        """Save WordPress.com OAuth token metadata."""
        self._set("WPCOM_ACCESS_TOKEN", access_token)
        if token_type:
            self._set("WPCOM_TOKEN_TYPE", token_type)
        else:
            self._clear("WPCOM_TOKEN_TYPE")
        if scope:
            self._set("WPCOM_SCOPE", scope)
        else:
            self._clear("WPCOM_SCOPE")

    def clear_wpcom_access_token(self) -> None:
        """Clear the saved WordPress.com OAuth token metadata."""
        self._clear("WPCOM_ACCESS_TOKEN")
        self._clear("WPCOM_TOKEN_TYPE")
        self._clear("WPCOM_SCOPE")

    def clear_credentials(self) -> None:
        """Clear primary WordPress auth plus saved WordPress.com auth state."""
        super().clear_credentials()
        for field in (
            "APP_PASSWORD",
            "WPCOM_CLIENT_ID",
            "WPCOM_CLIENT_SECRET",
            "WPCOM_SITE",
            "WPCOM_REDIRECT_URI",
            "WPCOM_ACCESS_TOKEN",
            "WPCOM_TOKEN_TYPE",
            "WPCOM_SCOPE",
        ):
            self._clear(field)

    def test_connection(self) -> dict:
        """Test WordPress API connectivity with a lightweight call."""
        import requests
        from requests.auth import HTTPBasicAuth

        try:
            resp = requests.get(
                f"{self.base_url}/posts",
                auth=HTTPBasicAuth(self.username, self.password),
                headers={"Accept": "application/json", "User-Agent": "WordPressClient/1.0"},
                params={"context": "edit", "per_page": 1},
                timeout=10,
            )
            if resp.ok:
                return {"api_test": "passed"}
            return {"api_test": f"failed: API request failed ({resp.status_code}): {resp.text}"}
        except Exception as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]

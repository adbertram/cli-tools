"""Configuration management for Garrul CLI."""

from urllib.parse import urlparse

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError, ConfigError


class Config(BaseConfig):
    DIST_NAME = "garrul-cli"
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://comments.adamtheautomator.com"
    # EMBED_ORIGIN is the site that embeds the widget. Garrul's public /api/*
    # routes reject any request whose Origin is not in ALLOWED_ORIGINS.
    ROOT_CONFIG_FIELDS = ("EMBED_ORIGIN",)
    # A session cookie on disk proves nothing: Garrul can revoke it server side.
    # `auth status` must also pass the authenticated JSON probe below.
    BROWSER_SESSION_REQUIRES_API_TEST = True

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def instance_origin(self) -> str:
        """Scheme and host of the Garrul instance. Admin mutations must send it as Origin."""
        where = f"BASE_URL {self.base_url!r} in {self.config_env_file_path}"
        try:
            parsed = urlparse(self.base_url)
            host, _port = parsed.hostname, parsed.port  # reading .port is what validates it
        except ValueError as exc:
            raise ConfigError(f"{where} is not a valid URL: {exc}.") from exc
        if parsed.scheme not in ("http", "https") or not host:
            raise ConfigError(f"{where} is not an http(s) URL.")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ConfigError(f"{where} must be the instance origin only, with no path, query or fragment.")
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def embed_origin(self) -> str:
        value = self._get("EMBED_ORIGIN")
        if value is None:
            raise ConfigError(
                f"EMBED_ORIGIN is not set in {self.config_env_file_path}. Set it to a site origin listed in the "
                "Garrul instance's ALLOWED_ORIGINS, for example https://adamtheautomator.com."
            )
        return value

    def get_browser(self):
        """Return the BrowserAutomation subclass that owns the GitHub OAuth sign-in."""
        from .browser import browser_for

        return browser_for(self)

    def test_connection(self) -> dict:
        """Prove the saved session still works with a real authenticated request."""
        from .client import GarrulClient

        try:
            GarrulClient(config=self).list_saved_replies()
            return {"api_test": "passed"}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs = {}


def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]

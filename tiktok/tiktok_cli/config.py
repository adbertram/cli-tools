"""Configuration management for TikTok CLI."""
import subprocess
from typing import Optional

from dotenv import dotenv_values

from cli_tools_shared.config import BaseConfig, get_profiles_base_dir, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType

API_AUTH_TYPE = CredentialType.CUSTOM.value
BROWSER_AUTH_TYPE = CredentialType.BROWSER_SESSION.value

TIKTOK_API_REQUIRED_FIELDS = [
    "AUTH_TYPE",
    "CLIENT_KEY",
    "CLIENT_SECRET",
    "REDIRECT_URI",
    "ACCESS_TOKEN",
]
TIKTOK_API_ALL_FIELDS = [
    *TIKTOK_API_REQUIRED_FIELDS,
    "REFRESH_TOKEN",
    "TOKEN_EXPIRES_AT",
    "OPEN_ID",
    "TIKTOK_SCOPES",
    "TIKTOK_GRANTED_SCOPES",
]
TIKTOK_API_LOGIN_PROMPTS = [
    ("CLIENT_KEY", "TikTok Client key", False),
    ("CLIENT_SECRET", "TikTok Client secret", True),
    ("REDIRECT_URI", "Desktop redirect URI", False),
]
TIKTOK_API_SENSITIVE_FIELDS = [
    "CLIENT_SECRET",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
]
TIKTOK_API_EPHEMERAL_FIELDS = [
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "TOKEN_EXPIRES_AT",
    "OPEN_ID",
    "TIKTOK_GRANTED_SCOPES",
]
DEFAULT_TIKTOK_SCOPES = ["user.info.basic", "video.publish"]


def _migrate_legacy_profiles(tool_name: str) -> None:
    """Mark existing pre-API TikTok profiles as browser-session profiles."""
    profiles_dir = get_profiles_base_dir(tool_name)
    if not profiles_dir.exists():
        return
    for env_path in profiles_dir.glob("*/.env"):
        values = dotenv_values(env_path)
        if values.get("AUTH_TYPE"):
            continue
        env_path.write_text(f"AUTH_TYPE={BROWSER_AUTH_TYPE}\n{env_path.read_text()}")


class Config(BaseConfig):
    """Configuration manager for TikTok browser and Content Posting API access."""

    DIST_NAME = "tiktok-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM, CredentialType.BROWSER_SESSION]
    PROFILE_AUTH_TYPE_FIELD = "AUTH_TYPE"
    PROFILE_AUTH_TYPES = {
        API_AUTH_TYPE: [],
        BROWSER_AUTH_TYPE: [],
    }

    LOGIN_INSTRUCTIONS = (
        "TikTok has separate auth profiles.\n"
        "  - browser_session is used only for favorites list.\n"
        "  - custom is the Content Posting API profile. Create a TikTok developer app,\n"
        "    enable Login Kit + Direct Post, register a desktop localhost redirect URI,\n"
        "    and grant user.info.basic plus video.publish.\n"
        "Transcript downloads and favorites get use yt-dlp and require no CLI auth."
    )

    def __init__(
        self,
        profile: Optional[str] = None,
        profile_auth_type: Optional[str] = None,
    ):
        tool_dir = resolve_tool_dir(self.DIST_NAME)
        _migrate_legacy_profiles(tool_dir.name)
        super().__init__(
            tool_dir=tool_dir,
            profile=profile,
            profile_auth_type=profile_auth_type,
        )

    @property
    def auth_type(self) -> Optional[str]:
        return self._get(self.PROFILE_AUTH_TYPE_FIELD)

    @property
    def CUSTOM_REQUIRED_FIELDS(self) -> list[str]:
        if self.auth_type == BROWSER_AUTH_TYPE:
            return ["AUTH_TYPE"]
        return list(TIKTOK_API_REQUIRED_FIELDS)

    @property
    def CUSTOM_ALL_FIELDS(self) -> list[str]:
        if self.auth_type == BROWSER_AUTH_TYPE:
            return ["AUTH_TYPE"]
        return list(TIKTOK_API_ALL_FIELDS)

    @property
    def CUSTOM_LOGIN_PROMPTS(self) -> list[tuple[str, str, bool]]:
        if self.auth_type == BROWSER_AUTH_TYPE:
            return []
        return list(TIKTOK_API_LOGIN_PROMPTS)

    @property
    def CUSTOM_SENSITIVE_FIELDS(self) -> list[str]:
        if self.auth_type == BROWSER_AUTH_TYPE:
            return []
        return list(TIKTOK_API_SENSITIVE_FIELDS)

    @property
    def CUSTOM_EPHEMERAL_FIELDS(self) -> list[str]:
        if self.auth_type == BROWSER_AUTH_TYPE:
            return []
        return list(TIKTOK_API_EPHEMERAL_FIELDS)

    @property
    def client_key(self) -> Optional[str]:
        return self._get("CLIENT_KEY")

    @property
    def client_secret(self) -> Optional[str]:
        return self._get("CLIENT_SECRET")

    @property
    def redirect_uri(self) -> Optional[str]:
        return self._get("REDIRECT_URI")

    @property
    def requested_scopes(self) -> list[str]:
        raw = self._get("TIKTOK_SCOPES")
        if raw:
            return [scope.strip() for scope in raw.split(",") if scope.strip()]
        return list(DEFAULT_TIKTOK_SCOPES)

    @property
    def api_base_url(self) -> str:
        return "https://open.tiktokapis.com"

    @property
    def token_url(self) -> str:
        return f"{self.api_base_url}/v2/oauth/token/"

    @property
    def authorization_url(self) -> str:
        return "https://www.tiktok.com/v2/auth/authorize/"

    @property
    def base_url(self) -> str:
        return "https://www.tiktok.com"

    @property
    def headless(self) -> bool:
        val = self._get("HEADLESS")
        return val is None or val.lower() == "true"

    def get_browser(self):
        from .browser import TiktokBrowser
        return TiktokBrowser(self)

    def has_credentials(self) -> bool:
        if self.auth_type == BROWSER_AUTH_TYPE:
            return self.has_saved_session()
        return bool(self.client_key and self.client_secret and self.access_token)

    def get_missing_credentials(self) -> list[str]:
        if self.auth_type == BROWSER_AUTH_TYPE:
            return [] if self.has_saved_session() else ["browser_session"]
        return [field for field in TIKTOK_API_REQUIRED_FIELDS if not self._get(field)]

    def test_connection(self) -> Optional[dict]:
        if self.auth_type == API_AUTH_TYPE:
            try:
                from .posting import TikTokPostingClient
                creator = TikTokPostingClient(config=self).creator_info()
                return {
                    "api_test": "passed",
                    "creator_username": creator.get("creator_username"),
                    "creator_nickname": creator.get("creator_nickname"),
                    "privacy_level_options": creator.get("privacy_level_options") or [],
                }
            except Exception as exc:
                return {"api_test": f"failed: {exc}"}

        if self.auth_type == BROWSER_AUTH_TYPE:
            try:
                result = self.get_browser().test_session()
                if result.get("authenticated"):
                    return {"api_test": "passed (browser session active)"}
                return {"api_test": f"failed: {result.get('error', 'not authenticated')}"}
            except Exception as exc:
                return {"api_test": f"failed: {exc}"}

        try:
            result = subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
        except FileNotFoundError:
            return {"api_test": "failed: yt-dlp not installed", "upstream": "yt-dlp"}
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or str(exc)).strip()
            return {"api_test": f"failed: {message}", "upstream": "yt-dlp"}
        except subprocess.TimeoutExpired:
            return {"api_test": "failed: yt-dlp --version timed out", "upstream": "yt-dlp"}

        return {
            "api_test": "passed",
            "upstream": "yt-dlp",
            "version": result.stdout.strip(),
        }


_configs: dict = {}


def get_config(
    profile: Optional[str] = None,
    profile_auth_type: Optional[str] = None,
) -> Config:
    key = (profile or "_default", profile_auth_type or "_any")
    if key not in _configs:
        _configs[key] = Config(
            profile=profile,
            profile_auth_type=profile_auth_type,
        )
    return _configs[key]


def reset_config() -> None:
    _configs.clear()

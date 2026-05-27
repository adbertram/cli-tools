"""Configuration management for Copilot CLI.

Filesystem layout:

    ~/.local/share/cli-tools/copilot/
        .env                          # non-authentication config
        authentication_profiles/
            default/.env              # auth profile runtime state
            <name>/.env               # additional auth profiles
            <name>/cache/             # auth-tied token/cache state

Secrets (e.g., AZURE_CLIENT_SECRET) are referenced from the profile .env as
``secret://<name>`` placeholders and stored by the CLI-tools secret manager.

Override env vars (highest precedence):
    XDG_DATA_HOME       — platform user-data root override used by cli-tools-shared
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from cli_tools_shared.config import (
    BaseConfig,
    get_profiles_base_dir,
    get_tool_data_dir,
    resolve_tool_dir,
)
from cli_tools_shared import CredentialType
from cli_tools_shared.exceptions import ConfigError


# ============================================================================
# App-wide constants
# ============================================================================

APP_NAME = "copilot"

def get_config_root() -> Path:
    """Resolve the cli-tools user-data root for copilot."""
    return get_tool_data_dir(APP_NAME)


def get_cache_root() -> Path:
    """Resolve the active profile cache directory."""
    active_profile = find_active_profile_file()
    profile_name = profile_name_from_xdg_path(active_profile) if active_profile else "default"
    return get_profiles_base_dir(APP_NAME) / profile_name / "cache"


def get_profiles_dir() -> Path:
    """Directory holding authentication profile directories."""
    return get_profiles_base_dir(APP_NAME)


def profile_env_path(profile_name: str) -> Path:
    """Return the canonical .env path for a profile."""
    if not profile_name:
        raise ValueError("profile_name is required")
    safe = profile_name.replace("/", "_").replace("\\", "_")
    return get_profiles_dir() / safe / ".env"


def list_profile_files() -> list[Path]:
    """Return all canonical profile .env files sorted."""
    pdir = get_profiles_dir()
    if not pdir.is_dir():
        return []
    return sorted(p for p in pdir.glob("*/.env") if p.is_file())


def profile_name_from_xdg_path(path: Path) -> str:
    """Extract profile name from a canonical profile file path."""
    if path.name == ".env":
        return path.parent.name
    return path.stem


def _read_active(path: Path) -> Optional[bool]:
    """Return True/False/None for ACTIVE in a profile file."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ACTIVE="):
                    value = line.split("=", 1)[1].strip().strip("\"'")
                    return value == "true"
    except (OSError, UnicodeDecodeError):
        pass
    return None


def find_active_profile_file() -> Optional[Path]:
    """Find the canonical profile file marked ACTIVE=true."""
    matches = []
    for f in list_profile_files():
        if _read_active(f) is True:
            matches.append(f)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(profile_name_from_xdg_path(p) for p in matches)
        from cli_tools_shared.exceptions import ConfigError
        raise ConfigError(
            f"Multiple active profiles found: {names}. "
            "Only one profile should have ACTIVE=true for the copilot auth type."
        )
    return None


# ============================================================================
# Config class
# ============================================================================

class Config(BaseConfig):
    """Configuration for Copilot CLI authentication and settings.

    Storage layout:

    - Profile (.env) files live under ``authentication_profiles/<name>/.env``
      inside :func:`get_config_root`. Each holds non-secret values like
      ``DATAVERSE_URL``, ``AZURE_TENANT_ID``, ``AZURE_CLIENT_ID``,
      ``AZURE_CLI_EXPECTED_USER``.
    - Sensitive fields use ``secret://...`` placeholders in the profile .env
      and raw values in the CLI-tools secret manager.
    """

    # Distribution name from pyproject.toml [project].name
    DIST_NAME = "copilot-cli"

    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    DEFAULT_BASE_URL = ""

    CUSTOM_REQUIRED_FIELDS = ["DATAVERSE_URL"]
    CUSTOM_ALL_FIELDS = [
        "DATAVERSE_URL",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_CLI_EXPECTED_USER",
        "DIRECTLINE_SECRET",
        "M365_SDK_CLIENT_SECRET",
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("DATAVERSE_URL", "Dataverse environment URL (e.g., https://yourorg.crm.dynamics.com)", False),
    ]
    CUSTOM_EPHEMERAL_FIELDS = []
    CUSTOM_SENSITIVE_FIELDS = [
        "AZURE_CLIENT_SECRET",
        "M365_SDK_CLIENT_SECRET",
        "DIRECTLINE_SECRET",
    ]

    def __init__(self, profile=None, profile_auth_type: Optional[str] = None):
        """Initialize configuration.

        Profile resolution order:
            1. Explicit ``profile`` argument
            2. ``ACTIVE=true`` marker inside a canonical profile file
            3. ``authentication_profiles/default/.env`` for future writes when no profiles exist
        """
        # Make sure the config root exists before BaseConfig touches it.
        config_root = resolve_tool_dir(self.DIST_NAME)
        get_profiles_dir().mkdir(parents=True, exist_ok=True)

        super().__init__(
            tool_dir=config_root,
            profile=profile,
            profile_auth_type=profile_auth_type,
        )

    # ------------------------------------------------------------------
    # Path resolution overrides — canonical cli-tools profile layout
    # ------------------------------------------------------------------

    def _resolve_env_file(
        self,
        profile: str = None,
        profile_auth_type: str = None,
    ):
        """Resolve which .env file to load.

        Order: explicit profile arg → active profile → canonical default path when no profiles exist.
        """
        if profile_auth_type not in (None, CredentialType.CUSTOM.value):
            raise ConfigError(
                f"Copilot config only supports profile auth type '{CredentialType.CUSTOM.value}', "
                f"got '{profile_auth_type}'."
            )
        if profile:
            return self._env_file_for_profile(profile)

        active = find_active_profile_file()
        if active is not None:
            return active

        if list_profile_files():
            raise ConfigError(
                "No active profile found. Select one with "
                "'copilot auth profiles select <name>'."
            )

        # Initial profile path for first writes.
        implicit = profile_env_path("default")
        return implicit

    def _env_file_for_profile(self, name: str):
        """Get .env file path for a named profile."""
        path = profile_env_path(name)
        if path.exists():
            return path

        from cli_tools_shared.exceptions import ConfigError
        raise ConfigError(
            f"Profile '{name}' not found.\n"
            f"Expected file: {path}\n"
            f"Create it with: copilot auth login --profile {name}"
        )

    def _active_profile_name(self) -> str:
        """Return the active profile name."""
        path = self.env_file_path
        if path.name == ".env":
            return path.parent.name
        if path.name.startswith(".env."):
            return path.name[len(".env."):]
        return path.stem

    # ------------------------------------------------------------------
    # Standard accessors
    # ------------------------------------------------------------------

    @property
    def dataverse_url(self) -> Optional[str]:
        return self._get("DATAVERSE_URL")

    @property
    def environment_id(self) -> Optional[str]:
        return self._get("DATAVERSE_ENVIRONMENT_ID") or self._get("POWERPLATFORM_ENVIRONMENT_ID")

    @property
    def tenant_id(self) -> Optional[str]:
        return self._get("AZURE_TENANT_ID")

    @property
    def azure_client_id(self) -> Optional[str]:
        return self._get("AZURE_CLIENT_ID")

    @property
    def azure_client_secret(self) -> Optional[str]:
        """AZURE_CLIENT_SECRET resolved from the profile secret placeholder."""
        return self._get("AZURE_CLIENT_SECRET")

    @property
    def expected_user(self) -> Optional[str]:
        return self._get("AZURE_CLI_EXPECTED_USER")

    def has_credentials(self) -> bool:
        """Return whether the profile has enough saved config to run auth."""
        return super().has_credentials()

    def has_service_principal_auth(self) -> bool:
        return bool(
            self.dataverse_url
            and self.tenant_id
            and self.azure_client_id
            and self.azure_client_secret
        )

    def has_cli_auth(self) -> bool:
        return bool(self.dataverse_url)

    def get_auth_method(self) -> str:
        if self.has_cli_auth():
            return "azure_cli"
        elif self.has_service_principal_auth():
            return "service_principal"
        else:
            return "none"

    def clear_session(self):
        """No-op: Copilot CLI uses Azure CLI auth, not browser sessions."""
        pass

    def get_active_profile_name(self) -> str:
        """Profile name for the active env file.

        Override kept so profile-scoped secret names use the active profile
        directory name.
        """
        return self._active_profile_name()

    # ------------------------------------------------------------------
    # Profile-discovery hooks (authentication_profiles/<name>/.env)
    # ------------------------------------------------------------------

    def list_profile_paths(self) -> list[Path]:
        """Return all canonical profile env files."""
        return list_profile_files()

    def profile_path_for(self, name: str) -> Path:
        return profile_env_path(name)

    def profile_name_for_path(self, path: Path) -> str:
        if path.name == ".env":
            return path.parent.name
        if path.name.startswith(".env."):
            return path.name[len(".env."):]
        return path.stem

    def profile_data_dir_name(self) -> str:
        """Per-profile runtime data scopes under ``cli-tools/copilot/`` so the
        scope name stays stable regardless of where the config dir is.
        """
        return APP_NAME

    # NOTE: test_connection() is intentionally NOT overridden. The shared auth
    # app receives `_copilot_test_handler` directly, so `auth status` and
    # `auth test` both run the same live Dataverse probe.


# Global config cache
_config: Optional[Config] = None


def get_config(profile=None, profile_auth_type: Optional[str] = None) -> Config:
    """Get or create the config instance."""
    global _config
    if _config is None or profile is not None or profile_auth_type is not None:
        _config = Config(profile=profile, profile_auth_type=profile_auth_type)
    return _config


def _reset_config() -> None:
    """Reset the global config instance."""
    global _config
    _config = None

"""Configuration management for Copilot CLI.

Filesystem layout (post-migration):

    ~/.config/copilot/                 (Linux/macOS) or %APPDATA%/copilot/
        profiles/
            default.env              # non-secret per-profile fields
            <name>.env               # additional profiles
    ~/.cache/copilot/                  (Linux/macOS) or %LOCALAPPDATA%/copilot/Cache/
        token-cache.json
        m365-token-cache.json

Secrets (e.g., AZURE_CLIENT_SECRET) live in the OS keychain via the
``cli_tools_shared.secrets`` helpers — never in the plain-text .env files.

Override env vars (highest precedence):
    COPILOT_CONFIG_DIR  — entire config root (overrides XDG and platform default)
    COPILOT_CACHE_DIR   — entire cache root
    XDG_CONFIG_HOME     — Linux/macOS XDG override (config goes under <xdg>/copilot/)
    XDG_CACHE_HOME      — Linux/macOS XDG override
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared import CredentialType
from cli_tools_shared.paths import resolve_config_dir, resolve_cache_dir
from cli_tools_shared.secrets import (
    SecretError,
    get_secret as _get_secret,
    set_secret as _set_secret,
    delete_secret as _delete_secret,
)


# ============================================================================
# App-wide constants
# ============================================================================

APP_NAME = "copilot"

#: Service name registered in the OS keychain. Visible in macOS Keychain
#: Access, Windows Credential Manager, and ``secret-tool`` on Linux.
KEYCHAIN_SERVICE = "copilot-cli"

#: Override env var for the config dir (highest precedence).
CONFIG_DIR_OVERRIDE_ENV = "COPILOT_CONFIG_DIR"

#: Override env var for the cache dir.
CACHE_DIR_OVERRIDE_ENV = "COPILOT_CACHE_DIR"


def get_config_root() -> Path:
    """Resolve the user-config root for copilot.

    Precedence: ``COPILOT_CONFIG_DIR`` > ``XDG_CONFIG_HOME/copilot`` >
    ``~/.config/copilot`` (Linux/macOS) > ``%APPDATA%/copilot`` (Windows).
    """
    override = os.environ.get(CONFIG_DIR_OVERRIDE_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return resolve_config_dir(APP_NAME)


def get_cache_root() -> Path:
    """Resolve the user-cache root for copilot.

    Precedence: ``COPILOT_CACHE_DIR`` > ``XDG_CACHE_HOME/copilot`` >
    ``~/.cache/copilot`` (Linux/macOS) > ``%LOCALAPPDATA%/copilot/Cache``
    (Windows).
    """
    override = os.environ.get(CACHE_DIR_OVERRIDE_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return resolve_cache_dir(APP_NAME)


def get_profiles_dir() -> Path:
    """Directory holding per-profile .env files (XDG layout)."""
    return get_config_root() / "profiles"


def profile_env_path(profile_name: str) -> Path:
    """Return the .env path for a profile under the new XDG layout.

    ``default`` → ``<config>/profiles/default.env``,
    ``staging`` → ``<config>/profiles/staging.env``.
    """
    if not profile_name:
        raise ValueError("profile_name is required")
    safe = profile_name.replace("/", "_").replace("\\", "_")
    return get_profiles_dir() / f"{safe}.env"


def list_profile_files() -> list[Path]:
    """Return all profile .env files under the new XDG layout, sorted."""
    pdir = get_profiles_dir()
    if not pdir.is_dir():
        return []
    return sorted(p for p in pdir.glob("*.env") if p.is_file())


def profile_name_from_xdg_path(path: Path) -> str:
    """Extract profile name from an XDG-style profile file path."""
    return path.stem


def _read_is_default(path: Path) -> Optional[bool]:
    """Return True/False/None for IS_DEFAULT_PROFILE in a profile file."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("IS_DEFAULT_PROFILE="):
                    value = line.split("=", 1)[1].strip().strip("\"'")
                    return value == "1"
    except (OSError, UnicodeDecodeError):
        pass
    return None


def find_default_profile_file() -> Optional[Path]:
    """Find the profile file marked IS_DEFAULT_PROFILE=1 in the XDG layout."""
    matches = []
    for f in list_profile_files():
        if _read_is_default(f) is True:
            matches.append(f)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(profile_name_from_xdg_path(p) for p in matches)
        from cli_tools_shared.exceptions import ConfigError
        raise ConfigError(
            f"Multiple default profiles found: {names}. "
            "Only one profile should have IS_DEFAULT_PROFILE=1."
        )
    return None


# ============================================================================
# Legacy .env discovery (for migration + deprecation warnings)
# ============================================================================

def find_legacy_env_files() -> list[Path]:
    """Return any legacy ``.env``/``.env.<name>`` files in the package source dir.

    Pre-migration installs put profile data alongside the source code via
    ``resolve_tool_dir(DIST_NAME)``. We surface those so users can migrate.
    Returns an empty list when the tool_dir cannot be resolved (e.g.,
    package metadata missing in odd installs).

    Files we do not consider profiles:
    - ``.env.example`` — the public template
    - any path ending in ``.migrated`` — markers written by a prior
      ``copilot config migrate`` run
    """
    try:
        legacy_dir = resolve_tool_dir("copilot-cli")
    except Exception:
        return []
    files: list[Path] = []
    bare = legacy_dir / ".env"
    if bare.exists():
        files.append(bare)
    for f in sorted(legacy_dir.glob(".env.*")):
        if f.name == ".env.example":
            continue
        if f.name.endswith(".migrated"):
            continue
        files.append(f)
    return files


def has_legacy_env() -> bool:
    """Return True if a legacy in-repo .env file exists."""
    return bool(find_legacy_env_files())


# ============================================================================
# Config class
# ============================================================================

class Config(BaseConfig):
    """Configuration for Copilot CLI authentication and settings.

    Storage layout:

    - Profile (.env) files live under the user's config dir: see
      :func:`get_config_root`. Each holds non-secret values like
      ``DATAVERSE_URL``, ``AZURE_TENANT_ID``, ``AZURE_CLIENT_ID``,
      ``AZURE_CLI_EXPECTED_USER``.
    - Sensitive fields (``AZURE_CLIENT_SECRET``) live in the OS keychain.
      Reads transparently look up the keychain first, then fall back to
      the .env file (and then to the process env var) for backward compat.
      Writes always target the keychain — never the .env file.

    Subclasses inheriting this Config should preserve the keychain routing
    by adding any new sensitive field name to ``CUSTOM_SENSITIVE_FIELDS``
    and to ``KEYCHAIN_FIELDS``.
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
    ]
    CUSTOM_LOGIN_PROMPTS = [
        ("DATAVERSE_URL", "Dataverse environment URL (e.g., https://yourorg.crm.dynamics.com)", False),
    ]
    CUSTOM_EPHEMERAL_FIELDS = []
    CUSTOM_SENSITIVE_FIELDS = ["AZURE_CLIENT_SECRET"]

    #: Field names that must be stored in the OS keychain instead of the
    #: plain-text .env file. ``_get``/``_set``/``_clear`` route these
    #: through ``cli_tools_shared.secrets``.
    KEYCHAIN_FIELDS = frozenset({
        "AZURE_CLIENT_SECRET",
        "M365_SDK_CLIENT_SECRET",
        "DIRECTLINE_SECRET",
    })

    def __init__(self, profile=None):
        """Initialize configuration.

        Profile resolution order:
            1. Explicit ``profile`` argument
            2. ``IS_DEFAULT_PROFILE=1`` marker inside an XDG profile file
            3. ``profiles/default.env`` if it exists (implicit default)
            4. Legacy ``.env`` in the package source dir (with deprecation
               warning) — read-only fallback so existing installs keep working
               until the user runs ``copilot config migrate``.

        ``tool_dir`` is set to the user-config root (e.g.
        ``~/.config/copilot/``) so that ``BaseConfig._set`` writes go to the
        XDG location, not the install directory.
        """
        # Make sure the config root exists before BaseConfig touches it.
        config_root = get_config_root()
        config_root.mkdir(parents=True, exist_ok=True)
        get_profiles_dir().mkdir(parents=True, exist_ok=True)

        super().__init__(
            tool_dir=config_root,
            profile=profile,
        )

    # ------------------------------------------------------------------
    # Path resolution overrides — XDG-first with legacy fallback
    # ------------------------------------------------------------------

    def _resolve_env_file(self, profile: str = None):
        """Resolve which .env file to load.

        Order: explicit profile arg → XDG default → legacy .env (deprecated).
        """
        if profile:
            return self._env_file_for_profile(profile)

        default = find_default_profile_file()
        if default is not None:
            return default

        # Implicit default: profiles/default.env if it exists.
        implicit = profile_env_path("default")
        if implicit.exists():
            return implicit

        # Legacy fallback: keep a working CLI when the user hasn't migrated.
        legacy = self._first_legacy_env_file()
        if legacy is not None:
            self._warn_legacy(legacy)
            return legacy

        # Nothing found yet — return the implicit default path so subsequent
        # writes (login flows) create it in the right place.
        return implicit

    def _env_file_for_profile(self, name: str):
        """Get .env file path for a named profile (XDG layout)."""
        path = profile_env_path(name)
        if path.exists():
            return path

        # Legacy: support `.env.<name>` in the package source dir during
        # the migration window. Tell the user to migrate.
        try:
            legacy_dir = resolve_tool_dir("copilot-cli")
        except Exception:
            legacy_dir = None
        if legacy_dir is not None:
            legacy = legacy_dir / f".env.{name}"
            if legacy.exists():
                self._warn_legacy(legacy)
                return legacy

        from cli_tools_shared.exceptions import ConfigError
        raise ConfigError(
            f"Profile '{name}' not found.\n"
            f"Expected file: {path}\n"
            f"Create it with: copilot auth login --profile {name}"
        )

    def _first_legacy_env_file(self) -> Optional[Path]:
        """Pick the legacy .env file we should read for an implicit default.

        Honors ``IS_DEFAULT_PROFILE=1`` if any legacy file declares it,
        falls back to the bare ``.env`` if present, and finally to the
        first ``.env.<name>`` alphabetically.
        """
        legacy = find_legacy_env_files()
        if not legacy:
            return None
        # 1. Respect explicit IS_DEFAULT_PROFILE marker.
        for path in legacy:
            if _read_is_default(path) is True:
                return path
        # 2. Fall back to bare .env if it exists.
        for path in legacy:
            if path.name == ".env":
                return path
        # 3. Otherwise return the first .env.<name> alphabetically.
        return legacy[0]

    def _warn_legacy(self, path: Path) -> None:
        """Emit a deprecation warning for a legacy .env file (once per process)."""
        if getattr(self.__class__, "_legacy_warned", False):
            return
        self.__class__._legacy_warned = True
        # Use stderr directly so the warning appears even when stdout is
        # piped to JSON consumers.
        print(
            f"⚠️  copilot: using legacy profile file at {path}\n"
            f"   Run `copilot config migrate` to move profiles to {get_config_root()}\n"
            f"   and store secrets in the OS keychain.",
            file=sys.stderr,
        )

    # ------------------------------------------------------------------
    # Sensitive-field routing — keychain instead of .env
    # ------------------------------------------------------------------

    def _is_sensitive(self, name: str) -> bool:
        return name in self.KEYCHAIN_FIELDS

    def _active_profile_name(self) -> str:
        """Return the active profile name (works for XDG and legacy paths)."""
        path = self.env_file_path
        # XDG layout: .../profiles/<name>.env
        if path.parent.name == "profiles":
            return path.stem
        # Legacy: .env or .env.<name>
        if path.name == ".env":
            return "default"
        if path.name.startswith(".env."):
            return path.name[len(".env."):]
        return "default"

    def _get(self, name: str) -> Optional[str]:
        """Read a value: keychain for sensitive fields, env vars otherwise."""
        if self._is_sensitive(name):
            try:
                value = _get_secret(KEYCHAIN_SERVICE, self._active_profile_name(), name)
            except SecretError:
                value = None
            if value:
                return value
            # Backward compat: process env or legacy .env file may still
            # carry the secret. Returning these lets pre-migration installs
            # work; the migrate command moves them to the keychain.
            legacy_value = os.getenv(name)
            return legacy_value if legacy_value else None
        return super()._get(name)

    def _set(self, name: str, value: str):
        """Write a value: keychain for sensitive fields, .env otherwise.

        For sensitive fields we also clear any plain-text copy from the
        process env and from the .env file, so a half-migrated state can't
        leave the secret on disk.
        """
        if self._is_sensitive(name):
            _set_secret(KEYCHAIN_SERVICE, self._active_profile_name(), name, value)
            os.environ[name] = value  # in-memory only; do NOT persist to .env
            # Best-effort scrub of any plain-text copy in the .env file.
            try:
                from cli_tools_shared.config import _set_key_with_retry
                if self.env_file_path.exists():
                    _set_key_with_retry(str(self.env_file_path), name, "")
            except Exception:
                pass
            return
        super()._set(name, value)

    def _clear(self, name: str):
        """Clear a value: keychain for sensitive fields, .env otherwise."""
        if self._is_sensitive(name):
            try:
                _delete_secret(KEYCHAIN_SERVICE, self._active_profile_name(), name)
            except SecretError:
                pass
            os.environ.pop(name, None)
            try:
                super()._clear(name)
            except Exception:
                pass
            return
        super()._clear(name)

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
        """AZURE_CLIENT_SECRET — pulled from OS keychain (with legacy fallback)."""
        return self._get("AZURE_CLIENT_SECRET")

    @property
    def expected_user(self) -> Optional[str]:
        return self._get("AZURE_CLI_EXPECTED_USER")

    def has_credentials(self) -> bool:
        """Check if credentials are configured and valid."""
        if not super().has_credentials():
            return False

        if self.get_auth_method() == "azure_cli" and self.expected_user:
            import subprocess
            import json as _json
            try:
                from .client import _resolve_az_command
                az = _resolve_az_command()
                result = subprocess.run(
                    [az, "account", "show", "-o", "json"],
                    capture_output=True, text=True, check=True,
                )
                account = _json.loads(result.stdout)
                actual_user = account.get("user", {}).get("name", "")
                if actual_user.lower() != self.expected_user.lower():
                    return False
            except (subprocess.CalledProcessError, FileNotFoundError):
                return False

        return True

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
        if self.has_service_principal_auth():
            return "service_principal"
        elif self.has_cli_auth():
            return "azure_cli"
        else:
            return "none"

    def clear_session(self):
        """No-op: Copilot CLI uses Azure CLI auth, not browser sessions."""
        pass

    def get_active_profile_name(self) -> str:
        """Profile name for the active env file.

        Override needed because BaseConfig assumes the legacy ``.env.<name>``
        naming and would chop the first 5 chars of the filename for
        XDG-style ``<name>.env`` files.
        """
        return self._active_profile_name()

    # ------------------------------------------------------------------
    # Profile-discovery hooks (XDG layout: <config>/profiles/<name>.env)
    # ------------------------------------------------------------------

    def list_profile_paths(self) -> list[Path]:
        """Return all XDG profile files under ``<config>/profiles/``."""
        return list_profile_files()

    def profile_path_for(self, name: str) -> Path:
        return profile_env_path(name)

    def profile_name_for_path(self, path: Path) -> str:
        # XDG: <config>/profiles/<name>.env → '<name>'
        if path.parent.name == "profiles":
            return path.stem
        # Legacy ``.env.<name>`` fallback support.
        if path.name == ".env":
            return "default"
        if path.name.startswith(".env."):
            return path.name[len(".env."):]
        return path.stem

    def profile_data_dir_name(self) -> str:
        """Per-profile runtime data scopes under ``cli-tools/copilot/`` so the
        scope name stays stable regardless of where the config dir is.
        """
        return APP_NAME

    # NOTE: test_connection() is intentionally NOT overridden. `copilot auth status`
    # therefore does NOT run a live Dataverse probe and does NOT include an
    # `api_test` field in its output. The active live probe lives in
    # `_copilot_test_handler` (main.py) and is wired into `copilot auth test` only.
    # Status reports `credentials_saved` to indicate config completeness; callers
    # that need a live probe must run `copilot auth test`.


# Global config cache
_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create the config instance."""
    global _config
    if _config is None or profile is not None:
        _config = Config(profile=profile)
    return _config


def _reset_config() -> None:
    """Reset the global config instance."""
    global _config
    _config = None

"""Base configuration with profile-aware env loading."""

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values, load_dotenv, set_key

from .credentials import (
    CredentialType,
    combined_all_fields,
    combined_login_prompts,
    combined_required_fields,
)
from .exceptions import ConfigError


# ==================== File Write Utilities ====================

def _set_key_with_retry(env_path: str, name: str, value: str, max_retries: int = 3):
    """Wrap set_key with retry for Windows PermissionError (Dropbox file locks)."""
    path = Path(env_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    for attempt in range(max_retries):
        try:
            set_key(env_path, name, value)
            return
        except PermissionError:
            if sys.platform != "win32" or attempt == max_retries - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


# ==================== Cache Utilities ====================

_CACHE_TRUTHY = ("true", "1", "yes")
DEFAULT_CACHE_TTL = 3600


def is_cache_enabled() -> bool:
    """Check CACHE_ENABLED env var (default: true)."""
    return os.environ.get("CACHE_ENABLED", "true").lower() in _CACHE_TRUTHY


def get_cache_ttl() -> int:
    """Read CACHE_TTL env var (default: 3600)."""
    return int(os.environ.get("CACHE_TTL", str(DEFAULT_CACHE_TTL)))


def read_is_default_profile(env_path: Path) -> Optional[bool]:
    """Read IS_DEFAULT_PROFILE from an env file without loading into os.environ.

    Returns True if IS_DEFAULT_PROFILE=1, False if =0, None if not found.
    """
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("IS_DEFAULT_PROFILE="):
                    value = line.split("=", 1)[1].strip().strip("\"'")
                    return value == "1"
    except (OSError, UnicodeDecodeError):
        pass
    return None


def profile_name_from_path(env_path: Path) -> str:
    """Extract profile name from env file path.

    The env file is always named ``.env``; the profile name is the
    parent-directory name. Example::

        ~/.local/share/cli-tools/impact/authentication_profiles/default/.env  →  "default"
        ~/.local/share/cli-tools/impact/authentication_profiles/staging/.env  →  "staging"
    """
    return env_path.parent.name


def get_tool_data_dir(tool_name: str) -> Path:
    """Get the platform-appropriate root user-data directory for a tool."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "cli-tools" / tool_name


def config_env_path_for_tool(tool_name: str) -> Path:
    """Get the root env file for non-authentication configuration."""
    return get_tool_data_dir(tool_name) / ".env"


def env_path_for_profile(tool_name: str, profile_name: str) -> Path:
    """Get env file path for a profile name.

    Authentication configuration lives outside the cli-tools source repo,
    under the platform user-data directory::

        ~/.local/share/cli-tools/<tool>/authentication_profiles/<profile>/.env

    Non-authentication configuration lives in the tool-level env file:
    ``~/.local/share/cli-tools/<tool>/.env``.
    """
    return get_profiles_base_dir(tool_name) / profile_name / ".env"


def list_env_files(tool_name: str) -> list:
    """List all profile env files for a tool.

    Scans ``~/.local/share/cli-tools/<tool>/authentication_profiles/*/.env``
    and returns the paths sorted by profile name.
    """
    base = get_profiles_base_dir(tool_name)
    if not base.exists():
        return []
    files = []
    for profile_dir in sorted(base.iterdir()):
        if not profile_dir.is_dir():
            continue
        env_file = profile_dir / ".env"
        if env_file.exists():
            files.append(env_file)
    return files


def _set_is_default_in_file(env_path: Path, is_default: bool) -> None:
    value = "1" if is_default else "0"
    content = env_path.read_text()
    lines = content.splitlines()
    updated = []
    found = False
    for line in lines:
        if line.strip().startswith("IS_DEFAULT_PROFILE="):
            updated.append(f"IS_DEFAULT_PROFILE={value}")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.insert(0, f"IS_DEFAULT_PROFILE={value}")
    env_path.write_text("\n".join(updated) + "\n")


_AUTH_METADATA_FIELDS = {"IS_DEFAULT_PROFILE"}
_AUTH_FIELD_PREFIXES = ("AUTH_", "OAUTH_")
_AUTH_FIELD_NAMES = {"AUTHORIZATION_CODE", "REDIRECT_URI"}
_DEFAULT_ROOT_CONFIG_FIELDS = {
    "BASE_URL",
    "CACHE_ENABLED",
    "CACHE_TTL",
    "HEADLESS",
    "BROWSER_USER_AGENT",
    "BROWSER_WINDOW_SIZE",
    "CLI_COMMAND",
    "CLI_PATH",
}


def _is_auth_env_field(name: str, auth_fields: set[str]) -> bool:
    return (
        name in _AUTH_METADATA_FIELDS
        or name in _AUTH_FIELD_NAMES
        or name in auth_fields
        or name.startswith(_AUTH_FIELD_PREFIXES)
    )


def _read_env_values(env_path: Path) -> dict[str, str]:
    return {
        key: "" if value is None else str(value)
        for key, value in dotenv_values(env_path).items()
    }


def _write_env_values(env_path: Path, values: dict[str, str]) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))


def _split_env_values(
    values: dict[str, str],
    auth_fields: set[str],
    root_config_fields: set[str],
) -> tuple[dict[str, str], dict[str, str]]:
    auth_values: dict[str, str] = {}
    config_values: dict[str, str] = {}
    for key, value in values.items():
        if key in root_config_fields and not _is_auth_env_field(key, auth_fields):
            config_values[key] = value
        else:
            auth_values[key] = value
    return auth_values, config_values


def _merge_config_values(config_path: Path, values: dict[str, str]) -> None:
    if not values:
        return
    existing = _read_env_values(config_path) if config_path.exists() else {}
    merged = dict(existing)
    for key, value in values.items():
        if key in existing and existing[key] != value:
            raise ConfigError(
                f"Conflicting non-auth configuration value for {key} in {config_path}. "
                "Non-auth configuration is tool-wide; remove the conflicting profile value."
            )
        merged[key] = value
    _write_env_values(config_path, merged)


def _initialize_default_profile(
    tool_dir: Path,
    tool_name: str,
    auth_fields: set[str],
    root_config_fields: set[str],
) -> None:
    """Create root config and default auth profile env files when missing."""
    example = tool_dir / ".env.example"
    auth_values: dict[str, str] = {}
    config_values: dict[str, str] = {}
    if example.exists():
        auth_values, config_values = _split_env_values(
            _read_env_values(example),
            auth_fields,
            root_config_fields,
        )

    config_path = config_env_path_for_tool(tool_name)
    if config_values and not config_path.exists():
        _write_env_values(config_path, config_values)

    if list_env_files(tool_name):
        return

    target = env_path_for_profile(tool_name, "default")
    auth_values["IS_DEFAULT_PROFILE"] = "1"
    _write_env_values(target, auth_values)


def _read_toml_project_name(pyproject_path: Path) -> Optional[str]:
    """Read the [project] name field from a pyproject.toml without requiring tomllib.

    Returns None if the file doesn't exist or doesn't contain a project name.
    Fails loudly on malformed files (does NOT silently fall back).
    """
    if not pyproject_path.exists():
        return None
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        tomllib = None
    if tomllib is not None:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        project = data.get("project") or {}
        name = project.get("name")
        return name if name else None
    # Python < 3.11 fallback: naive parser for the name field under [project]
    in_project = False
    with open(pyproject_path, "r") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("["):
                in_project = stripped == "[project]"
                continue
            if in_project and stripped.startswith("name") and "=" in stripped:
                _, _, value = stripped.partition("=")
                return value.strip().strip("\"'")
    return None


def resolve_tool_dir(dist_name: str) -> Path:
    """Resolve the canonical source folder for an installed CLI tool distribution.

    This is the ONLY supported way to compute a CLI tool's `tool_dir`. It must
    NEVER be computed from `Path(__file__).resolve().parent.parent` — that path
    follows whichever copy of the package Python happened to load, which can
    point at an unrelated repository when a stray editable copy exists.

    Resolution strategy (fail-fast, no fallbacks):

    1. Env override: ``CLI_TOOL_DIR_<DIST_NAME_UPPER_UNDERSCORES>`` — used by
       tests and deliberate local overrides. Must point at an existing directory.
    2. Installed distribution metadata:
       - Look up the distribution via ``importlib.metadata.distribution``.
       - For editable (PEP 660) installs, read ``direct_url.json`` and use the
         ``url`` (file://) as the canonical source folder.
       - For wheel installs, use the directory containing the top-level package.
    3. Validate the resolved directory contains a ``pyproject.toml`` whose
       ``[project].name`` matches ``dist_name``. If it does not, raise.

    Args:
        dist_name: The distribution name (from pyproject.toml ``[project].name``),
            e.g. ``"copilot-cli"``, ``"podio-cli"``.

    Returns:
        Absolute path to the canonical CLI tool source folder.

    Raises:
        ConfigError: If the dist cannot be resolved or the resolved directory
            does not match ``dist_name``.
    """
    # 1. Explicit env override (for tests and deliberate overrides)
    env_key = "CLI_TOOL_DIR_" + dist_name.upper().replace("-", "_").replace(".", "_")
    override = os.environ.get(env_key)
    if override:
        path = Path(override).resolve()
        if not path.is_dir():
            raise ConfigError(
                f"{env_key}={override!r} does not point at an existing directory."
            )
        return path

    # 2. Resolve via installed distribution metadata
    try:
        from importlib.metadata import PackageNotFoundError, distribution
    except ImportError as exc:  # pragma: no cover
        raise ConfigError(
            f"importlib.metadata is required to resolve tool_dir for {dist_name!r}"
        ) from exc

    try:
        dist = distribution(dist_name)
    except PackageNotFoundError as exc:
        raise ConfigError(
            f"Distribution {dist_name!r} is not installed. "
            f"Install with `uv tool install -e <path-to-{dist_name}>` or "
            f"set {env_key} to override."
        ) from exc

    tool_dir: Optional[Path] = None

    # 2a. Editable install — direct_url.json records the source folder
    try:
        direct_url_text = dist.read_text("direct_url.json")
    except (FileNotFoundError, OSError):
        direct_url_text = None
    if direct_url_text:
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"Malformed direct_url.json for distribution {dist_name!r}"
            ) from exc
        url = direct_url.get("url", "")
        if url.startswith("file://"):
            tool_dir = Path(url[len("file://") :]).resolve()

    # 2b. Wheel install — locate the top-level package directory's parent
    if tool_dir is None:
        top_level: Optional[str] = None
        try:
            top_level_text = dist.read_text("top_level.txt")
        except (FileNotFoundError, OSError):
            top_level_text = None
        if top_level_text:
            lines = [line.strip() for line in top_level_text.splitlines() if line.strip()]
            if lines:
                top_level = lines[0]
        if top_level is None:
            # Fall back to deriving package name from dist name (hyphen → underscore)
            top_level = dist_name.replace("-", "_")
        located = dist.locate_file(f"{top_level}/__init__.py")
        if located is None:
            raise ConfigError(
                f"Could not locate package directory for distribution {dist_name!r}."
            )
        tool_dir = Path(located).resolve().parent.parent

    if not tool_dir.is_dir():
        raise ConfigError(
            f"Resolved tool_dir for {dist_name!r} does not exist: {tool_dir}"
        )

    # 3. Validate pyproject.toml name matches dist_name
    pyproject = tool_dir / "pyproject.toml"
    project_name = _read_toml_project_name(pyproject)
    if project_name is None:
        raise ConfigError(
            f"Resolved tool_dir for {dist_name!r} at {tool_dir} has no "
            f"pyproject.toml with a [project].name. "
            f"The canonical CLI tool folder must contain its own pyproject.toml. "
            f"Set {env_key} to override."
        )
    # Normalize hyphens/underscores when comparing (PEP 503)
    if project_name.replace("_", "-").lower() != dist_name.replace("_", "-").lower():
        raise ConfigError(
            f"Distribution {dist_name!r} resolved to {tool_dir}, but that folder's "
            f"pyproject.toml declares name={project_name!r}. The distribution and "
            f"folder disagree — the tool is likely installed from the wrong source. "
            f"Reinstall with `uv tool install -e <canonical-tool-folder> --force`, "
            f"or set {env_key} to override."
        )

    return tool_dir


def get_profiles_base_dir(tool_name: str) -> Path:
    """Get the platform-appropriate authentication_profiles directory."""
    return get_tool_data_dir(tool_name) / "authentication_profiles"


def _migrate_legacy_profiles_dir(tool_dir: Path, tool_name: str) -> None:
    """Move source-tree authentication profile data into user data.

    Per-profile runtime data (browser cookies, cache) belongs under
    ``~/.local/share/cli-tools/<tool>/authentication_profiles/`` so the
    source tree stays generic and the on-disk layout is consistent.
    """
    old_dir = tool_dir / "authentication_profiles"
    if not old_dir.exists():
        return
    new_dir = get_profiles_base_dir(tool_name)
    if new_dir.exists() and any(new_dir.iterdir()):
        shutil.rmtree(old_dir)
        return
    new_dir.parent.mkdir(parents=True, exist_ok=True)
    if new_dir.exists():
        shutil.rmtree(new_dir)
    shutil.move(str(old_dir), str(new_dir))
    print(
        f"[cli-tools-shared] migrated profile data: {old_dir} -> {new_dir}",
        file=sys.stderr,
    )


def _migrate_env_files(
    tool_dir: Path,
    tool_name: str,
    auth_fields: set[str],
    root_config_fields: set[str],
) -> None:
    """Move legacy source-tree env files into user data.

    The legacy layout stored credentials inside the cli-tools source repo
    (``tool_dir/.env`` for the default profile, ``tool_dir/.env.<name>``
    for named profiles). Split each file so auth-related fields stay in
    ``authentication_profiles/<profile>/.env`` and non-auth configuration
    moves into the tool-level config file::

        ~/.local/share/cli-tools/<tool>/.env

    Idempotent. Once a tool has been migrated, subsequent calls do nothing.
    """
    tool_data_dir = get_tool_data_dir(tool_name)
    tool_data_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_env_path_for_tool(tool_name)

    bare = tool_dir / ".env"
    if bare.exists():
        auth_values, config_values = _split_env_values(
            _read_env_values(bare),
            auth_fields,
            root_config_fields,
        )
        auth_values.setdefault("IS_DEFAULT_PROFILE", "1")
        _merge_config_values(config_path, config_values)
        target = env_path_for_profile(tool_name, "default")
        if auth_values and not target.exists():
            _write_env_values(target, auth_values)
            print(
                f"[cli-tools-shared] migrated {bare} -> {target}",
                file=sys.stderr,
            )
        bare.unlink()

    for src in sorted(tool_dir.glob(".env.*")):
        if src.name == ".env.example":
            continue
        profile_name = src.name[len(".env."):]
        auth_values, config_values = _split_env_values(
            _read_env_values(src),
            auth_fields,
            root_config_fields,
        )
        auth_values.setdefault("IS_DEFAULT_PROFILE", "0")
        _merge_config_values(config_path, config_values)
        target = env_path_for_profile(tool_name, profile_name)
        if auth_values and not target.exists():
            _write_env_values(target, auth_values)
            print(
                f"[cli-tools-shared] migrated {src} -> {target}",
                file=sys.stderr,
            )
        src.unlink()


def _normalize_profile_env_files(tool_name: str, auth_fields: set[str], root_config_fields: set[str]) -> None:
    """Move non-auth fields out of profile env files into root config."""
    config_path = config_env_path_for_tool(tool_name)
    for env_file in list_env_files(tool_name):
        values = _read_env_values(env_file)
        auth_values, config_values = _split_env_values(
            values,
            auth_fields,
            root_config_fields,
        )
        if not config_values:
            continue
        auth_values.setdefault("IS_DEFAULT_PROFILE", "0")
        _merge_config_values(config_path, config_values)
        _write_env_values(env_file, auth_values)


class BaseConfig:
    """Base configuration with profile-aware env loading.

    Subclasses set class variables:
        CREDENTIAL_TYPES: list of CredentialType values (AND — all must be satisfied)
        DEFAULT_BASE_URL: str fallback URL

    Example subclass (simple API key tool):

        from cli_tools_shared.config import BaseConfig, resolve_tool_dir

        class Config(BaseConfig):
            CREDENTIAL_TYPES = [CredentialType.API_KEY]
            DEFAULT_BASE_URL = "https://api.example.com/v1"
            DIST_NAME = "example-cli"  # matches [project].name in pyproject.toml

            def __init__(self, profile=None):
                super().__init__(
                    tool_dir=resolve_tool_dir(self.DIST_NAME),
                    profile=profile,
                )

    NEVER compute ``tool_dir`` from ``Path(__file__).resolve().parent.parent``
    — that resolves relative to whichever copy of the package Python happens
    to import, which breaks when a stray editable copy of the package exists
    in an unrelated repository. Always use ``resolve_tool_dir(DIST_NAME)``.
    """

    CREDENTIAL_TYPES: list = None           # List of CredentialType values (AND)
    DEFAULT_BASE_URL: str = ""

    # OAuth 2.0 configuration (set by subclasses that use OAuth)
    OAUTH_AUTH_URL: str = ""              # Authorization endpoint
    OAUTH_TOKEN_URL: str = ""            # Token endpoint
    OAUTH_SCOPES: list = []              # Scope strings
    OAUTH_REDIRECT_URI: str = ""         # Default redirect URI (overridable in .env via REDIRECT_URI)
    OAUTH_PKCE: bool = False             # Enable PKCE (S256)
    OAUTH_TOKEN_AUTH: str = "body"       # "basic" | "body" | "none"
    OAUTH_EXTRA_AUTH_PARAMS: dict = {}   # Extra params for auth URL (e.g. audience)
    OAUTH_TOKEN_EXPIRES: bool = True   # False for OAuth 1.0a/static token credentials
    OAUTH_STATIC_REQUIRED_FIELDS: tuple = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN")

    # Extra credential prompts (set by subclasses that need additional fields prompted during login)
    # List of (field_name, prompt_label, hide_input) tuples
    # Prompted AFTER standard credential prompts but BEFORE login_handler or browser login
    AUTH_EXTRA_PROMPTS: list = []

    # Custom credential type field definitions (only used when CREDENTIAL_TYPES includes CUSTOM)
    CUSTOM_REQUIRED_FIELDS: list = []
    CUSTOM_ALL_FIELDS: list = []
    CUSTOM_LOGIN_PROMPTS: list = []
    CUSTOM_EPHEMERAL_FIELDS: list = []
    CUSTOM_SENSITIVE_FIELDS: list = []
    ROOT_CONFIG_FIELDS: tuple = ()

    def _auth_field_names(self) -> set[str]:
        fields = set(combined_all_fields(self.CREDENTIAL_TYPES, config=self))
        fields.update(combined_required_fields(self.CREDENTIAL_TYPES, config=self))
        fields.update(
            field_name
            for field_name, _prompt_text, _hide in combined_login_prompts(
                self.CREDENTIAL_TYPES,
                config=self,
            )
        )
        fields.update(_AUTH_METADATA_FIELDS)
        return fields

    def _root_config_field_names(self) -> set[str]:
        fields = set(_DEFAULT_ROOT_CONFIG_FIELDS)
        fields.update(getattr(self, "ROOT_CONFIG_FIELDS", ()) or ())
        return fields

    def __init__(self, tool_dir: Path, profile: str = None):
        """Initialize config by resolving the profile and loading the env file.

        Profile resolution priority:
            1. Explicit profile argument (from profile-management code)
            2. Whichever .env* file has IS_DEFAULT_PROFILE=1

        Args:
            tool_dir: Root directory of the CLI tool (contains .env.example).
            profile: Optional explicit profile name.
        """
        if self.CREDENTIAL_TYPES is None:
            raise ConfigError(
                "Subclass must set CREDENTIAL_TYPES (list of CredentialType values)."
            )
        self.tool_dir = tool_dir
        self._tool_name = tool_dir.name
        self.profile = profile
        self.config_env_file_path = config_env_path_for_tool(self._tool_name)
        auth_fields = self._auth_field_names()
        root_config_fields = self._root_config_field_names()

        # One-shot migrations from legacy in-repo layout to user-data layout.
        # Order matters: move profile state first so the env migration can
        # strip ``.env`` out of any migrated per-profile directories.
        # Idempotent — both helpers no-op once migration has completed.
        _migrate_legacy_profiles_dir(self.tool_dir, self._tool_name)
        _migrate_env_files(self.tool_dir, self._tool_name, auth_fields, root_config_fields)
        _initialize_default_profile(
            self.tool_dir,
            self._tool_name,
            auth_fields,
            root_config_fields,
        )
        _normalize_profile_env_files(self._tool_name, auth_fields, root_config_fields)

        self.env_file_path = self._resolve_env_file(profile)

        if self.config_env_file_path.exists():
            load_dotenv(self.config_env_file_path, override=True)

        if self.env_file_path.exists():
            # Clear standard credential env vars before loading to prevent
            # stale values from a previously loaded profile
            for field in auth_fields:
                os.environ.pop(field, None)
            os.environ.pop("IS_DEFAULT_PROFILE", None)
            load_dotenv(self.env_file_path, override=True)
        # If no .env file exists, keep current env vars intact — supports
        # running with credentials injected via environment (e.g., n8n nodes)

    def _resolve_env_file(self, profile: str = None) -> Path:
        """Resolve which .env file to load."""
        # 1. Explicit profile argument
        if profile:
            return self._env_file_for_profile(profile)

        # 2. Find default (IS_DEFAULT_PROFILE=1)
        return self._find_default_env_file()

    def _env_file_for_profile(self, name: str) -> Path:
        """Get .env file path for a named profile."""
        path = env_path_for_profile(self._tool_name, name)
        if not path.exists():
            raise ConfigError(
                f"Profile '{name}' not found. "
                f"Expected file: {path}\n"
                f"Run 'auth profiles create {name}' to create it."
            )
        return path

    def _find_default_env_file(self) -> Path:
        """Find the .env file with IS_DEFAULT_PROFILE=1."""
        env_files = list_env_files(self._tool_name)

        if not env_files:
            # No env files exist yet — return the path the default profile
            # WOULD live at, so subsequent _set() writes can create it.
            return env_path_for_profile(self._tool_name, "default")

        defaults = []
        for f in env_files:
            if read_is_default_profile(f) is True:
                defaults.append(f)

        if len(defaults) == 1:
            return defaults[0]

        if len(defaults) > 1:
            names = [profile_name_from_path(f) for f in defaults]
            raise ConfigError(
                f"Multiple default profiles found: {', '.join(names)}. "
                "Only one .env file should have IS_DEFAULT_PROFILE=1."
            )

        # No IS_DEFAULT_PROFILE=1 marker on any profile — fall back to the
        # default profile env file if it exists.
        default_path = env_path_for_profile(self._tool_name, "default")
        if default_path.exists():
            return default_path

        raise ConfigError(
            "No default profile found. Set IS_DEFAULT_PROFILE=1 in one .env file."
        )

    # ==================== Generic Get/Set/Clear ====================

    def _get(self, name: str) -> Optional[str]:
        """Get an env var value. Returns None for empty strings."""
        val = os.getenv(name)
        return val if val else None

    def _env_file_for_field(self, name: str) -> Path:
        if _is_auth_env_field(name, self._auth_field_names()):
            return self.env_file_path
        return self.config_env_file_path

    def _set(self, name: str, value: str):
        """Set an env var in the owning env file and os.environ."""
        _set_key_with_retry(str(self._env_file_for_field(name)), name, value)
        os.environ[name] = value

    def _clear(self, name: str):
        """Clear an env var from the owning env file and os.environ."""
        _set_key_with_retry(str(self._env_file_for_field(name)), name, "")
        os.environ.pop(name, None)

    # ==================== Standard Properties ====================

    @property
    def api_key(self) -> Optional[str]:
        return self._get("API_KEY")

    @property
    def client_id(self) -> Optional[str]:
        return self._get("CLIENT_ID")

    @property
    def client_secret(self) -> Optional[str]:
        return self._get("CLIENT_SECRET")

    @property
    def personal_access_token(self) -> Optional[str]:
        return self._get("PERSONAL_ACCESS_TOKEN")

    @property
    def access_token(self) -> Optional[str]:
        return self._get("ACCESS_TOKEN")

    @property
    def refresh_token(self) -> Optional[str]:
        return self._get("REFRESH_TOKEN")

    @property
    def token_expires_at(self) -> Optional[str]:
        return self._get("TOKEN_EXPIRES_AT")

    @property
    def username(self) -> Optional[str]:
        return self._get("USERNAME")

    @property
    def password(self) -> Optional[str]:
        return self._get("PASSWORD")

    @property
    def redirect_uri(self) -> Optional[str]:
        return self._get("REDIRECT_URI")

    @property
    def base_url(self) -> str:
        return self._get("BASE_URL") or self.DEFAULT_BASE_URL

    @property
    def cache_enabled(self) -> bool:
        return is_cache_enabled()

    @property
    def cache_ttl(self) -> int:
        return get_cache_ttl()

    # ==================== Credential Management ====================

    def _required_fields_for(self, cred_types: list[CredentialType]) -> list[str]:
        """Return deduplicated required fields for the given credential types."""
        seen = set()
        fields = []
        oauth_types = {
            CredentialType.OAUTH,
            CredentialType.OAUTH_AUTHORIZATION_CODE,
        }

        for cred_type in cred_types:
            if cred_type in oauth_types and not getattr(self, "OAUTH_TOKEN_EXPIRES", True):
                required = getattr(
                    self,
                    "OAUTH_STATIC_REQUIRED_FIELDS",
                    ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN"),
                )
            elif cred_type == CredentialType.CUSTOM:
                required = self.CUSTOM_REQUIRED_FIELDS
            else:
                required = cred_type.required_fields

            for field in required:
                if field in seen:
                    continue
                seen.add(field)
                fields.append(field)

        return fields

    def has_credentials(self) -> bool:
        """Check if required credentials are set.

        For dual-auth tools (e.g. OAUTH + BROWSER_SESSION), uses OR logic:
        the tool has credentials if non-browser creds are complete OR a saved
        browser session exists.  Single-type tools use simple all-fields check.
        """
        cred_types = self.CREDENTIAL_TYPES
        if CredentialType.BROWSER_SESSION in cred_types:
            non_browser_types = [ct for ct in cred_types if ct != CredentialType.BROWSER_SESSION]
            non_browser_ok = all(self._get(f) for f in self._required_fields_for(non_browser_types))
            browser_ok = self.has_saved_session()
            if non_browser_types:
                # Dual-auth: either pathway is sufficient
                return non_browser_ok or browser_ok
            # Browser-only: just check session
            return browser_ok
        return all(self._get(f) for f in self._required_fields_for(cred_types))

    def get_missing_credentials(self) -> list:
        """Get list of missing required credential field names."""
        return [f for f in self._required_fields_for(self.CREDENTIAL_TYPES) if not self._get(f)]

    def save_api_key(self, api_key: str):
        """Save API key credential."""
        self._set("API_KEY", api_key)

    def save_credentials(self, **kwargs):
        """Save arbitrary credentials. Keys are uppercased to env var names."""
        for key, value in kwargs.items():
            self._set(key.upper(), value)

    def save_tokens(self, access_token: str, refresh_token: str | None, expires_at: str):
        """Save OAuth tokens."""
        self._set("ACCESS_TOKEN", access_token)
        if refresh_token is None:
            self._clear("REFRESH_TOKEN")
        else:
            self._set("REFRESH_TOKEN", refresh_token)
        self._set("TOKEN_EXPIRES_AT", expires_at)

    def clear_credentials(self):
        """Clear all credential fields for this credential type."""
        for field in combined_all_fields(self.CREDENTIAL_TYPES, config=self):
            self._clear(field)

    def clear_ephemeral(self):
        """Clear ephemeral fields (tokens) and browser session. Preserves static credentials."""
        from .credentials import combined_ephemeral_fields  # avoid circular at module level
        for field in combined_ephemeral_fields(self.CREDENTIAL_TYPES, config=self):
            self._clear(field)
        self.clear_session()

    def clear_ephemeral_for_type(self, cred_type: 'CredentialType'):
        """Clear ephemeral fields for a single credential type."""
        if cred_type == CredentialType.CUSTOM:
            fields = self.CUSTOM_EPHEMERAL_FIELDS
        else:
            fields = cred_type.ephemeral_fields
        for field in fields:
            self._clear(field)
        if cred_type == CredentialType.BROWSER_SESSION:
            self.clear_session()

    # ==================== Profile Data Directories ====================

    def get_profiles_dir(self) -> Path:
        """Get the authentication_profiles directory for runtime data."""
        return get_profiles_base_dir(self._tool_name)

    def get_profile_data_dir(self) -> Path:
        """Get data directory for the active profile."""
        name = profile_name_from_path(self.env_file_path)
        profile_dir = self.get_profiles_dir() / name
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir

    def get_browser_data_dir(self) -> Path:
        """Get browser data directory for the active profile."""
        browser_dir = self.get_profile_data_dir() / "browser-data"
        browser_dir.mkdir(parents=True, exist_ok=True)
        return browser_dir

    def get_persistent_profile_dir(self) -> Path:
        """Get the persistent Chromium user-data-dir for the active profile.

        Chrome auto-creates ``Default/`` inside this directory and stores
        cookies (``Default/Cookies`` SQLite), localStorage, IndexedDB,
        service workers, and cache there. Single source of truth for
        browser session state.
        """
        return self.get_browser_data_dir() / "chromium-profile"

    def has_saved_session(self) -> bool:
        """Return True when the persistent Chromium profile has a session.

        Single ownership: this is the ONLY definition of "does this profile
        have a usable saved session?" — callers used to consult
        ``BrowserAutomation.has_session()`` as a parallel check; that method
        has been removed. The presence of Chrome's cookie database under
        ``chromium-profile/Default/Cookies`` is the sole on-disk indicator
        that an interactive login has been completed for this profile.
        """
        return (self.get_persistent_profile_dir() / "Default" / "Cookies").exists()

    def clear_session(self):
        """Clear saved session data for the active profile."""
        browser_dir = self.get_profile_data_dir() / "browser-data"
        if browser_dir.exists():
            shutil.rmtree(browser_dir)

    def clear_all(self):
        """Clear credentials and session data."""
        self.clear_credentials()
        self.clear_session()

    # ==================== Active Profile Info ====================

    def get_active_profile_name(self) -> str:
        """Get the name of the currently active profile."""
        return self.profile_name_for_path(self.env_file_path)

    # ==================== Profile Discovery Hooks ====================
    #
    # Subclasses that store profiles outside the shared cli-tools layout
    # (e.g., XDG ``~/.config/<app>/profiles/<name>.env``) override these to
    # teach the shared profiles/auth machinery where to look.

    def list_profile_paths(self) -> list:
        """Return all profile env-file paths managed by this Config."""
        return list_env_files(self._tool_name)

    def profile_path_for(self, name: str):
        """Return the env-file path for a profile name."""
        return env_path_for_profile(self._tool_name, name)

    def profile_name_for_path(self, path):
        """Return the profile name for an env-file path."""
        return profile_name_from_path(path)

    def profile_data_dir_name(self) -> str:
        """Return the directory name used under ``get_profiles_base_dir`` for
        per-profile runtime data. Defaults to ``tool_dir.name``; subclasses
        with a non-standard ``tool_dir`` (e.g. Copilot's ``~/.config/copilot``)
        override to produce a stable scope key.
        """
        return self._tool_name

    def test_connection(self) -> Optional[dict]:
        """Test API connectivity. Override in subclass to make a lightweight API call.

        Returns:
            dict with at minimum {"api_test": "passed"} or {"api_test": "failed: reason"},
            or None if no test is implemented.
        """
        return None

    def get_browser(self):
        """Return browser service instance for browser-based authentication.

        Override in CLI Config subclasses that require browser session authentication
        (in addition to or instead of API credentials).

        The returned object must implement:
        - is_authenticated() -> bool
        - login(force: bool) -> dict with 'success' key
        - close() -> None

        Returns None if browser auth is not needed.
        """
        return None

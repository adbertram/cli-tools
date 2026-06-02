"""Base configuration with profile-aware env loading."""

import json
import os
import subprocess
import shutil
import sys
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values, set_key

from .credentials import (
    CredentialType,
    combined_all_fields,
    combined_login_prompts,
    combined_required_fields,
    combined_sensitive_fields,
)
from .exceptions import ConfigError
from .repo_paths import secret_manager_script


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


_RUNTIME_PROFILE_NAME: ContextVar[Optional[str]] = ContextVar(
    "cli_tools_runtime_profile_name",
    default=None,
)
_RUNTIME_PROFILE_AUTH_TYPE: ContextVar[Optional[str]] = ContextVar(
    "cli_tools_runtime_profile_auth_type",
    default=None,
)


def set_runtime_profile_resolution(
    *,
    profile_name: Optional[str],
    profile_auth_type: Optional[str],
) -> tuple:
    """Set runtime-only profile resolution overrides for the current command."""
    name_token = _RUNTIME_PROFILE_NAME.set(profile_name)
    auth_type_token = _RUNTIME_PROFILE_AUTH_TYPE.set(profile_auth_type)
    return name_token, auth_type_token


def reset_runtime_profile_resolution(tokens: tuple) -> None:
    """Reset runtime-only profile resolution overrides for the current command."""
    name_token, auth_type_token = tokens
    _RUNTIME_PROFILE_NAME.reset(name_token)
    _RUNTIME_PROFILE_AUTH_TYPE.reset(auth_type_token)


def get_runtime_profile_resolution() -> tuple[Optional[str], Optional[str]]:
    """Return runtime-only profile resolution overrides for the current command."""
    return _RUNTIME_PROFILE_NAME.get(), _RUNTIME_PROFILE_AUTH_TYPE.get()


def read_profile_active(env_path: Path) -> Optional[bool]:
    """Read ACTIVE from an env file without loading into os.environ."""
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ACTIVE="):
                    value = line.split("=", 1)[1].strip().strip("\"'")
                    if value == "true":
                        return True
                    if value == "false":
                        return False
                    raise ConfigError(
                        f"{env_path} has invalid ACTIVE value {value!r}. "
                        "Expected ACTIVE=true or ACTIVE=false."
                    )
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


_AUTH_METADATA_FIELDS = {"ACTIVE"}
_AUTH_FIELD_PREFIXES = ("AUTH_", "OAUTH_")
_AUTH_FIELD_NAMES = {"AUTHORIZATION_CODE", "REDIRECT_URI"}
_SECRET_PLACEHOLDER_PREFIX = "secret://"
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


def get_profile_auth_settings(config_or_cls) -> Optional[tuple[str, dict]]:
    """Return profile auth-type metadata declared by the config, if any."""
    sentinel = object()
    auth_type_field = getattr(config_or_cls, "PROFILE_AUTH_TYPE_FIELD", sentinel)
    if auth_type_field is sentinel:
        auth_type_field = getattr(
            getattr(config_or_cls, "__dict__", {}),
            "get",
            lambda *_args, **_kwargs: sentinel,
        )("PROFILE_AUTH_TYPE_FIELD", sentinel)
    auth_types = getattr(config_or_cls, "PROFILE_AUTH_TYPES", sentinel)
    if auth_types is sentinel:
        auth_types = getattr(
            getattr(config_or_cls, "__dict__", {}),
            "get",
            lambda *_args, **_kwargs: sentinel,
        )("PROFILE_AUTH_TYPES", sentinel)
    if auth_type_field is sentinel and auth_types is sentinel:
        return None
    if auth_type_field is sentinel or auth_types is sentinel:
        raise ConfigError(
            "Config profile auth types must define PROFILE_AUTH_TYPE_FIELD and non-empty PROFILE_AUTH_TYPES."
        )
    if not auth_type_field or not isinstance(auth_types, dict) or not auth_types:
        raise ConfigError(
            "Config profile auth types must define PROFILE_AUTH_TYPE_FIELD and non-empty PROFILE_AUTH_TYPES."
        )
    return auth_type_field, auth_types


def implicit_profile_auth_type() -> str:
    """Return the implicit single auth type for CLIs without profile auth metadata."""
    return "default"


def _secret_name_from_placeholder(value: str) -> Optional[str]:
    if not value.startswith(_SECRET_PLACEHOLDER_PREFIX):
        return None
    secret_name = value[len(_SECRET_PLACEHOLDER_PREFIX) :]
    if not secret_name:
        raise ConfigError(
            f"Invalid secret placeholder {value!r}. "
            f"Expected {_SECRET_PLACEHOLDER_PREFIX}<secret-name>."
        )
    return secret_name


def _run_secret_manager(
    command: str,
    secret_name: str,
    *,
    secret_value: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    script_path = secret_manager_script()
    try:
        return subprocess.run(
            [str(script_path), command, secret_name],
            input=secret_value,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ConfigError(
            f"Failed to run CLI-tools secret manager at {script_path}."
        ) from exc


def _strip_secret_output(value: str) -> str:
    if value.endswith("\n"):
        value = value[:-1]
    if value.endswith("\r"):
        value = value[:-1]
    return value


def read_cli_tool_secret(secret_name: str) -> Optional[str]:
    """Read a raw reusable CLI-tool secret from the central secret manager."""
    result = _run_secret_manager("get", secret_name)
    if result.returncode != 0:
        return None
    return _strip_secret_output(result.stdout)


def _get_secret_value(secret_name: str, profile_path: Path) -> str:
    value = read_cli_tool_secret(secret_name)
    if value is None:
        raise ConfigError(
            f"Missing secret '{secret_name}' referenced by {profile_path}."
        )
    return value


def _set_secret_value(secret_name: str, value: str, profile_path: Path) -> None:
    result = _run_secret_manager("set", secret_name, secret_value=value)
    if result.returncode != 0:
        raise ConfigError(
            f"Failed to store secret '{secret_name}' for {profile_path}."
        )


def _delete_secret_value(secret_name: str, profile_path: Path) -> None:
    result = _run_secret_manager("delete", secret_name)
    if result.returncode != 0:
        raise ConfigError(
            f"Failed to delete secret '{secret_name}' for {profile_path}."
        )


def _secret_exists(secret_name: str) -> bool:
    result = _run_secret_manager("has", secret_name)
    if result.returncode not in (0, 1):
        raise ConfigError(
            f"Failed to check whether secret '{secret_name}' exists."
        )
    return result.returncode == 0


def _secret_placeholder(secret_name: str) -> str:
    return f"{_SECRET_PLACEHOLDER_PREFIX}{secret_name}"


def _normalize_secret_name_part(value: str) -> str:
    return value.lower().replace("_", "-")


def auth_profile_secret_placeholders(tool_name: str) -> list[tuple[Path, str, str]]:
    """Return ``(env_path, field_name, secret_name)`` for profile placeholders."""
    references: list[tuple[Path, str, str]] = []
    for env_path in list_env_files(tool_name):
        for field_name, value in _read_env_values(env_path).items():
            if not value:
                continue
            try:
                secret_name = _secret_name_from_placeholder(value)
            except ConfigError as exc:
                raise ConfigError(
                    f"{env_path} field '{field_name}' has invalid secret placeholder: {exc}"
                ) from exc
            if secret_name is None:
                continue
            references.append((env_path, field_name, secret_name))
    return references


def _optional_secret_fields_for_tool(tool_name: str) -> set[str]:
    """Return optional secret-managed auth fields declared by the tool config."""
    try:
        from importlib import import_module
        from importlib.metadata import PackageNotFoundError, distribution
    except ImportError:  # pragma: no cover
        return set()

    dist_candidates = [f"{tool_name}-cli", tool_name]
    dist = None
    for dist_name in dist_candidates:
        try:
            dist = distribution(dist_name)
            break
        except PackageNotFoundError:
            continue
    if dist is None:
        package_candidates = [
            f"{tool_name.replace('-', '_')}_cli",
            f"{tool_name.replace('-', '')}_cli",
        ]
        for package_name in package_candidates:
            try:
                module = import_module(f"{package_name}.config")
            except ImportError:
                continue
            config_cls = getattr(module, "Config", None)
            if config_cls is None:
                continue
            return set(getattr(config_cls, "OPTIONAL_SECRET_FIELDS", ()) or ())
        return set()

    top_level_text = dist.read_text("top_level.txt") or ""
    top_levels = [line.strip() for line in top_level_text.splitlines() if line.strip()]
    if not top_levels:
        top_levels = [tool_name.replace("-", "_")]

    for top_level in top_levels:
        try:
            module = import_module(f"{top_level}.config")
        except ImportError:
            continue
        config_cls = getattr(module, "Config", None)
        if config_cls is None:
            continue
        return set(getattr(config_cls, "OPTIONAL_SECRET_FIELDS", ()) or ())

    return set()


def validate_auth_profile_secret_placeholders(tool_name: str) -> None:
    """Fail when any auth-profile secret placeholder has no matching secret."""
    optional_fields = _optional_secret_fields_for_tool(tool_name)
    missing: list[tuple[Path, str, str]] = []
    for env_path, field_name, secret_name in auth_profile_secret_placeholders(tool_name):
        if field_name in optional_fields and not _secret_exists(secret_name):
            continue
        if _secret_exists(secret_name):
            continue
        missing.append((env_path, field_name, secret_name))

    if not missing:
        return

    detail_lines = [
        f"- {env_path} field '{field_name}' references missing secret '{secret_name}'"
        for env_path, field_name, secret_name in missing
    ]
    raise ConfigError(
        "Missing CLI-tools secrets referenced by authentication profiles:\n"
        + "\n".join(detail_lines)
    )


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


def _merge_config_values(config_path: Path, config_values: dict[str, str]) -> None:
    """Fill missing root config values when creating canonical profiles."""
    if not config_values:
        return
    existing_values = _read_env_values(config_path) if config_path.exists() else {}
    merged_values = dict(existing_values)
    changed = False
    for key, value in config_values.items():
        if key in merged_values and merged_values[key] != "":
            continue
        if merged_values.get(key) == value:
            continue
        merged_values[key] = value
        changed = True
    if changed:
        _write_env_values(config_path, merged_values)


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


def _validate_no_legacy_profile_layout(tool_dir: Path, tool_name: str) -> None:
    legacy_paths = [
        tool_dir / ".env",
        tool_dir / "authentication_profiles",
        get_tool_data_dir(tool_name) / ".profiles",
    ]
    legacy_paths.extend(
        path for path in sorted(tool_dir.glob(".env.*")) if path.name != ".env.example"
    )
    existing_paths = [path for path in legacy_paths if path.exists()]
    if not existing_paths:
        return

    details = "\n".join(f"- {path}" for path in existing_paths)
    raise ConfigError(
        "Unsupported legacy profile layout detected. Perform the profile cutover "
        "outside runtime before starting the CLI. Canonical auth profiles must "
        f"live under {get_profiles_base_dir(tool_name)}/<profile>/.\n{details}"
    )


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
    auth_values["ACTIVE"] = "true"
    _write_env_values(target, auth_values)


def _profile_auth_type_for_env_path(
    env_path: Path,
    profile_auth_settings: Optional[tuple[str, dict]],
) -> str:
    """Return the auth type declared by ``env_path`` for grouping/validation."""
    if profile_auth_settings is None:
        return implicit_profile_auth_type()

    auth_type_field, auth_types = profile_auth_settings
    auth_type = _read_env_values(env_path).get(auth_type_field, "").strip()
    if not auth_type:
        raise ConfigError(
            f"Profile '{profile_name_from_path(env_path)}' is missing {auth_type_field}. "
            "Recreate the profile with 'auth profiles create'."
        )
    if auth_type not in auth_types:
        raise ConfigError(
            f"Profile '{profile_name_from_path(env_path)}' has invalid auth type "
            f"{auth_type!r}. Valid types: {', '.join(sorted(auth_types))}."
        )
    return auth_type


def _validate_profile_env_files(
    tool_name: str,
    auth_fields: set[str],
    root_config_fields: set[str],
) -> None:
    """Fail when profile env files still contain tool-wide config fields."""
    config_path = config_env_path_for_tool(tool_name)
    violations: list[tuple[Path, list[str]]] = []
    for env_file in list_env_files(tool_name):
        _auth_values, config_values = _split_env_values(
            _read_env_values(env_file),
            auth_fields,
            root_config_fields,
        )
        if config_values:
            violations.append((env_file, sorted(config_values)))

    if not violations:
        return

    details = [
        f"- {env_file}: {', '.join(fields)}"
        for env_file, fields in violations
    ]
    raise ConfigError(
        "Authentication profile .env files contain non-authentication "
        f"configuration fields. Move these fields to {config_path}:\n"
        + "\n".join(details)
    )


def _validate_root_config_env_file(
    tool_name: str,
    auth_fields: set[str],
) -> None:
    """Fail when the canonical root config file stores auth fields."""
    config_path = config_env_path_for_tool(tool_name)
    if not config_path.exists():
        return

    auth_values = _read_env_values(config_path)
    violations = sorted(
        key for key in auth_values if _is_auth_env_field(key, auth_fields)
    )
    if not violations:
        return

    raise ConfigError(
        "Root config .env contains authentication fields. Move these fields to "
        f"{get_profiles_base_dir(tool_name)}/<profile>/.env:\n"
        + "\n".join(f"- {config_path}: {field_name}" for field_name in violations)
    )


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
    OAUTH_REDIRECT_URI_REQUIRED: bool = True
    OAUTH_PKCE: bool = False             # Enable PKCE (S256)
    OAUTH_TOKEN_AUTH: str = "body"       # "basic" | "body" | "none"
    OAUTH_EXTRA_AUTH_PARAMS: dict = {}   # Extra params for auth URL (e.g. audience)
    OAUTH_TOKEN_EXPIRES: bool = True   # False for OAuth 1.0a/static token credentials
    OAUTH_STATIC_REQUIRED_FIELDS: tuple = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN")
    BROWSER_SESSION_REQUIRES_API_TEST: bool = False

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
    ADDITIONAL_AUTH_FIELDS: tuple = ()
    ADDITIONAL_SENSITIVE_AUTH_FIELDS: tuple = ()
    OPTIONAL_SECRET_FIELDS: tuple = ()
    SECRET_NAME_OVERRIDES: dict = {}

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
        fields.update(getattr(self, "ADDITIONAL_AUTH_FIELDS", ()) or ())
        return fields

    def _root_config_field_names(self) -> set[str]:
        fields = set(_DEFAULT_ROOT_CONFIG_FIELDS)
        fields.update(getattr(self, "ROOT_CONFIG_FIELDS", ()) or ())
        return fields

    def _sensitive_auth_field_names(self) -> set[str]:
        fields = set(combined_sensitive_fields(self.CREDENTIAL_TYPES, config=self))
        fields.update(getattr(self, "ADDITIONAL_SENSITIVE_AUTH_FIELDS", ()) or ())
        return fields

    def _secret_managed_auth_field_names(self) -> set[str]:
        return self._sensitive_auth_field_names()

    def _optional_secret_field_names(self) -> set[str]:
        return set(getattr(self, "OPTIONAL_SECRET_FIELDS", ()) or ())

    def _resolve_env_values(
        self,
        values: dict[str, str],
        env_path: Path,
        placeholder_fields: Optional[set[str]] = None,
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        optional_secret_fields = self._optional_secret_field_names()
        for key, value in values.items():
            secret_name = (
                _secret_name_from_placeholder(value)
                if value and (placeholder_fields is None or key in placeholder_fields)
                else None
            )
            if secret_name is None:
                resolved[key] = value
                continue
            if key in optional_secret_fields and not _secret_exists(secret_name):
                resolved[key] = ""
                continue
            resolved[key] = _get_secret_value(secret_name, env_path)
        return resolved

    def _secret_name_for_field_in_profile(self, name: str, env_path: Path) -> str:
        overrides = getattr(self, "SECRET_NAME_OVERRIDES", {}) or {}
        override = overrides.get(name)
        if override:
            return override
        tool_name = _normalize_secret_name_part(self._tool_name)
        field_name = _normalize_secret_name_part(name)
        prefix = f"{tool_name}-"
        if field_name.startswith(prefix):
            field_name = field_name[len(prefix) :]
        profile_name = _normalize_secret_name_part(profile_name_from_path(env_path))
        if profile_name == "default":
            return f"{tool_name}-{field_name}"
        return f"{tool_name}-{profile_name}-{field_name}"

    def _secret_name_for_field(self, name: str) -> str:
        return self._secret_name_for_field_in_profile(name, self.env_file_path)

    def _validate_sensitive_placeholders(self) -> None:
        secret_managed_auth_fields = self._secret_managed_auth_field_names()
        for field_name in secret_managed_auth_fields:
            target_env = self._env_file_for_field(field_name)
            if not target_env.exists():
                continue
            current_value = _read_env_values(target_env).get(field_name, "")
            if not current_value:
                continue
            if _secret_name_from_placeholder(current_value) is not None:
                continue
            raise ConfigError(
                f"{target_env} field '{field_name}' contains a plain-text "
                "sensitive value. Store the value with the CLI-tools secret "
                "manager and set the field to secret://<secret-name>."
            )

    def __init__(
        self,
        tool_dir: Path,
        profile: str = None,
        profile_auth_type: str = None,
    ):
        """Initialize config by resolving the profile and loading the env file.

        Profile resolution priority:
            1. Explicit profile argument (from profile-management code)
            2. Runtime command-profile override
            3. Active profile for the requested auth type
            4. Single active profile when the CLI has one implicit auth type

        Args:
            tool_dir: Root directory of the CLI tool (contains .env.example).
            profile: Optional explicit profile name.
            profile_auth_type: Optional auth type whose active profile should load.
        """
        if self.CREDENTIAL_TYPES is None:
            raise ConfigError(
                "Subclass must set CREDENTIAL_TYPES (list of CredentialType values)."
            )
        self.tool_dir = tool_dir
        self._tool_name = tool_dir.name
        self.profile = profile
        self.profile_auth_type = profile_auth_type
        self.config_env_file_path = config_env_path_for_tool(self._tool_name)
        auth_fields = self._auth_field_names()
        root_config_fields = self._root_config_field_names()

        _validate_no_legacy_profile_layout(self.tool_dir, self._tool_name)
        _initialize_default_profile(
            self.tool_dir,
            self._tool_name,
            auth_fields,
            root_config_fields,
        )
        _validate_root_config_env_file(self._tool_name, auth_fields)
        _validate_profile_env_files(self._tool_name, auth_fields, root_config_fields)
        self.env_file_path = self._resolve_env_file(
            profile=profile,
            profile_auth_type=profile_auth_type,
        )
        self._validate_sensitive_placeholders()

        if self.config_env_file_path.exists():
            for key, value in self._resolve_env_values(
                _read_env_values(self.config_env_file_path),
                self.config_env_file_path,
            ).items():
                if key not in os.environ:
                    os.environ[key] = value

        if self.env_file_path.exists():
            # Clear standard credential env vars before loading to prevent
            # stale values from a previously loaded profile
            for field in auth_fields:
                os.environ.pop(field, None)
            os.environ.pop("ACTIVE", None)
            for key, value in self._resolve_env_values(
                _read_env_values(self.env_file_path),
                self.env_file_path,
                auth_fields,
            ).items():
                os.environ[key] = value
        # If no .env file exists, keep current env vars intact — supports
        # running with credentials injected via environment (e.g., n8n nodes)

    def _resolve_env_file(
        self,
        profile: str = None,
        profile_auth_type: str = None,
    ) -> Path:
        """Resolve which .env file to load."""
        # 1. Explicit profile argument
        if profile:
            env_path = self._env_file_for_profile(profile)
            if profile_auth_type is not None:
                self._validate_profile_auth_type(env_path, profile_auth_type)
            return env_path

        runtime_profile, runtime_profile_auth_type = get_runtime_profile_resolution()
        if runtime_profile:
            env_path = self._env_file_for_profile(runtime_profile)
            resolved_auth_type = profile_auth_type or runtime_profile_auth_type
            if resolved_auth_type is not None:
                self._validate_profile_auth_type(env_path, resolved_auth_type)
            return env_path

        resolved_auth_type = profile_auth_type or runtime_profile_auth_type
        return self._find_active_env_file(resolved_auth_type)

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

    def _find_active_env_file(self, profile_auth_type: str | None = None) -> Path:
        """Find the active .env file for the CLI or the requested auth type."""
        env_files = list_env_files(self._tool_name)

        if not env_files:
            # No env files exist yet — return the bootstrap profile path
            # WOULD live at, so subsequent _set() writes can create it.
            return env_path_for_profile(self._tool_name, "default")

        active_profiles = []
        for env_file in env_files:
            if read_profile_active(env_file) is not True:
                continue
            if profile_auth_type is not None:
                if self._profile_auth_type_for_env(env_file) != profile_auth_type:
                    continue
            active_profiles.append(env_file)

        if len(active_profiles) == 1:
            return active_profiles[0]

        if len(active_profiles) > 1:
            names = [profile_name_from_path(env_file) for env_file in active_profiles]
            if profile_auth_type is not None:
                raise ConfigError(
                    f"Multiple active profiles found for auth type '{profile_auth_type}': "
                    f"{', '.join(names)}. Only one profile of a given auth type may be ACTIVE=true."
                )
            raise ConfigError(
                "Multiple active profiles found. Resolve the command to a specific auth type "
                f"or profile. Active profiles: {', '.join(names)}."
            )

        if profile_auth_type is not None:
            raise ConfigError(
                f"No active profile found for auth type '{profile_auth_type}'. "
                f"Select one with '{self._tool_name} auth profiles select <name>'."
            )

        raise ConfigError(
            "No active profile found. Select a profile with "
            f"'{self._tool_name} auth profiles select <name>'."
        )

    def _profile_auth_type_for_env(self, env_path: Path) -> str:
        return _profile_auth_type_for_env_path(
            env_path,
            get_profile_auth_settings(type(self)),
        )

    def _validate_profile_auth_type(self, env_path: Path, expected_auth_type: str) -> None:
        actual_auth_type = self._profile_auth_type_for_env(env_path)
        if actual_auth_type != expected_auth_type:
            raise ConfigError(
                f"Profile '{profile_name_from_path(env_path)}' has auth type "
                f"'{actual_auth_type}', not '{expected_auth_type}'."
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
        auth_fields = self._auth_field_names()
        secret_managed_auth_fields = self._secret_managed_auth_field_names()
        if name in secret_managed_auth_fields and _is_auth_env_field(name, auth_fields):
            existing_value = _read_env_values(self.env_file_path).get(name, "")
            existing_secret_name = (
                _secret_name_from_placeholder(existing_value)
                if existing_value
                else None
            )
            secret_name = existing_secret_name or self._secret_name_for_field(name)
            _set_secret_value(secret_name, value, self.env_file_path)
            _set_key_with_retry(
                str(self.env_file_path),
                name,
                _secret_placeholder(secret_name),
            )
            os.environ[name] = value
            return

        _set_key_with_retry(str(self._env_file_for_field(name)), name, value)
        os.environ[name] = value

    def _clear(self, name: str):
        """Clear an env var from the owning env file and os.environ."""
        env_path = self._env_file_for_field(name)
        auth_fields = self._auth_field_names()
        secret_managed_auth_fields = self._secret_managed_auth_field_names()
        if name in secret_managed_auth_fields and _is_auth_env_field(name, auth_fields):
            existing_value = _read_env_values(env_path).get(name, "")
            existing_secret_name = (
                _secret_name_from_placeholder(existing_value)
                if existing_value
                else None
            )
            if existing_secret_name is not None and _secret_exists(existing_secret_name):
                _delete_secret_value(existing_secret_name, env_path)
            _set_key_with_retry(str(env_path), name, "")
            os.environ.pop(name, None)
            return
        _set_key_with_retry(str(env_path), name, "")
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
    # override these to teach the shared profiles/auth machinery where to look.

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
        with a non-standard ``tool_dir`` override to produce a stable scope key.
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

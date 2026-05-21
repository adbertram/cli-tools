"""Cross-platform user-directory resolution following XDG Base Directory spec.

These helpers compute the canonical config / cache / state directories for a
CLI tool on Linux, macOS, and Windows. The intent is that public-facing CLIs
store their data under predictable, scriptable locations rather than inside
the install tree.

Resolution order (first match wins):

1. App-specific override: ``<APP_NAME_UPPER>_CONFIG_DIR`` /
   ``<APP_NAME_UPPER>_CACHE_DIR`` / ``<APP_NAME_UPPER>_STATE_DIR``.
   Hyphens become underscores; ``copilot-cli`` → ``COPILOT_CLI_CONFIG_DIR``.
2. XDG environment variables on Linux/macOS: ``XDG_CONFIG_HOME``,
   ``XDG_CACHE_HOME``, ``XDG_STATE_HOME``.
3. Platform default:
   - Linux:   ``~/.config/<app>``, ``~/.cache/<app>``, ``~/.local/state/<app>``
   - macOS:   same as Linux (XDG style — easier to script than
     ``~/Library/Application Support/...``)
   - Windows: ``%APPDATA%/<app>`` (config),
     ``%LOCALAPPDATA%/<app>/Cache`` (cache),
     ``%LOCALAPPDATA%/<app>/State`` (state)

The directories are NOT created — callers create them on demand.
"""

import os
import sys
from pathlib import Path


__all__ = [
    "resolve_config_dir",
    "resolve_cache_dir",
    "resolve_state_dir",
    "config_dir_env_var",
    "cache_dir_env_var",
    "state_dir_env_var",
]


def _normalize_env_var(app_name: str, suffix: str) -> str:
    """Build the override env var name for an app: ``COPILOT_CLI_CONFIG_DIR`` etc."""
    cleaned = app_name.upper().replace("-", "_").replace(".", "_")
    return f"{cleaned}_{suffix}"


def config_dir_env_var(app_name: str) -> str:
    """Return the override env var name for the app's config dir."""
    return _normalize_env_var(app_name, "CONFIG_DIR")


def cache_dir_env_var(app_name: str) -> str:
    """Return the override env var name for the app's cache dir."""
    return _normalize_env_var(app_name, "CACHE_DIR")


def state_dir_env_var(app_name: str) -> str:
    """Return the override env var name for the app's state dir."""
    return _normalize_env_var(app_name, "STATE_DIR")


def _resolve(app_name: str, override_var: str, xdg_var: str, default: Path) -> Path:
    """Apply override → XDG → platform default precedence."""
    # 1. App-specific override
    override = os.environ.get(override_var)
    if override:
        return Path(override).expanduser().resolve()

    # 2. XDG env var (Linux/macOS) — does NOT apply on Windows by convention
    if sys.platform != "win32":
        xdg = os.environ.get(xdg_var)
        if xdg:
            return Path(xdg).expanduser().resolve() / app_name

    # 3. Platform default
    return default


def resolve_config_dir(app_name: str) -> Path:
    """Return the user-config directory for ``app_name``.

    Linux/macOS:  ``~/.config/<app>``
    Windows:      ``%APPDATA%/<app>``
    Override env: ``<APP>_CONFIG_DIR`` or ``XDG_CONFIG_HOME/<app>``.
    """
    home = Path.home()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        default = Path(appdata) / app_name
    else:
        default = home / ".config" / app_name
    return _resolve(app_name, config_dir_env_var(app_name), "XDG_CONFIG_HOME", default)


def resolve_cache_dir(app_name: str) -> Path:
    """Return the user-cache directory for ``app_name``.

    Linux/macOS:  ``~/.cache/<app>``
    Windows:      ``%LOCALAPPDATA%/<app>/Cache``
    Override env: ``<APP>_CACHE_DIR`` or ``XDG_CACHE_HOME/<app>``.
    """
    home = Path.home()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        default = Path(local) / app_name / "Cache"
    else:
        default = home / ".cache" / app_name
    return _resolve(app_name, cache_dir_env_var(app_name), "XDG_CACHE_HOME", default)


def resolve_state_dir(app_name: str) -> Path:
    """Return the user-state directory for ``app_name``.

    State data: logs, history, anything that should survive cache clears
    but isn't user-edited config.

    Linux/macOS:  ``~/.local/state/<app>``
    Windows:      ``%LOCALAPPDATA%/<app>/State``
    Override env: ``<APP>_STATE_DIR`` or ``XDG_STATE_HOME/<app>``.
    """
    home = Path.home()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        default = Path(local) / app_name / "State"
    else:
        default = home / ".local" / "state" / app_name
    return _resolve(app_name, state_dir_env_var(app_name), "XDG_STATE_HOME", default)

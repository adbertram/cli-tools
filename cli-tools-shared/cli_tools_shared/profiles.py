"""Profile CRUD operations for CLI tools.

Profile discovery is delegated to the active ``Config`` instance via the
hooks defined on :class:`cli_tools_shared.config.BaseConfig`. This lets
subclasses with non-default layouts (e.g., XDG ``~/.config/<app>/profiles/``)
participate without forking the public CLI surface.

For backward compatibility every function accepts EITHER a ``Config``
instance OR a legacy ``tool_dir`` path. Internally the path is wrapped in
a thin shim that delegates to the standard layout helpers so no caller
has to migrate at once.
"""

import shutil
from pathlib import Path
from typing import Union

from .config import (
    env_path_for_profile,
    get_profiles_base_dir,
    profile_name_from_path,
    read_is_default_profile,
    list_env_files,
)
from .exceptions import ConfigError


class _ToolDirShim:
    """Adapter exposing the BaseConfig profile-discovery hooks for a bare path.

    Lets ``list_profiles(tool_dir)`` / ``create_profile(tool_dir, ...)`` etc.
    keep working on tools that pass a path instead of a Config. The shim
    derives ``tool_name`` from the directory name; per-account state lives
    under ``~/.local/share/cli-tools/<tool_name>/.profiles/``.
    """

    def __init__(self, tool_dir: Path):
        self.tool_dir = tool_dir
        self._tool_name = tool_dir.name

    def list_profile_paths(self):
        return list_env_files(self._tool_name)

    def profile_path_for(self, name: str):
        return env_path_for_profile(self._tool_name, name)

    def profile_name_for_path(self, path):
        return profile_name_from_path(path)

    def profile_data_dir_name(self) -> str:
        return self._tool_name


def _adapt(config_or_dir) -> "_ToolDirShim":
    """Return something that exposes the profile-discovery hooks.

    Accepts a Config instance (uses its hooks directly) or a Path/PathLike
    (wraps it with the legacy shim). Anything else is a programming error.
    """
    if hasattr(config_or_dir, "list_profile_paths"):
        return config_or_dir
    return _ToolDirShim(Path(config_or_dir))


def list_profiles(config_or_dir: Union["BaseConfig", Path]) -> list:
    """List all profiles known to the active config (or tool dir).

    Returns a list of ``{name, file, is_default}`` dicts.
    """
    adapter = _adapt(config_or_dir)
    profiles = []
    for path in adapter.list_profile_paths():
        is_default = read_is_default_profile(path)
        profiles.append({
            "name": adapter.profile_name_for_path(path),
            "file": path.name,
            "is_default": bool(is_default),
        })
    return profiles


def create_profile(config_or_dir, name: str) -> Path:
    """Create a new profile by copying ``.env.example``.

    Raises ``ConfigError`` if the profile already exists. Falls back to a
    minimal ``IS_DEFAULT_PROFILE=0`` stub when no ``.env.example`` template
    is available next to the tool dir.
    """
    adapter = _adapt(config_or_dir)
    target = adapter.profile_path_for(name)
    if target.exists():
        raise ConfigError(f"Profile '{name}' already exists at {target}")

    target.parent.mkdir(parents=True, exist_ok=True)

    # Look for ``.env.example`` next to the tool dir if available.
    tool_dir = getattr(adapter, "tool_dir", None)
    example = (tool_dir / ".env.example") if tool_dir else None
    if example is not None and example.exists():
        shutil.copy2(example, target)
        _set_is_default_in_file(target, False)
    else:
        target.write_text("IS_DEFAULT_PROFILE=0\n")

    return target


def set_default_profile(config_or_dir, name: str):
    """Mark ``name`` as the default profile (sets every other to 0)."""
    adapter = _adapt(config_or_dir)
    target = adapter.profile_path_for(name)
    if not target.exists():
        raise ConfigError(f"Profile '{name}' not found at {target}")

    for path in adapter.list_profile_paths():
        _set_is_default_in_file(path, path == target)


def delete_profile(config_or_dir, name: str):
    """Delete a profile and any per-profile runtime data.

    Refuses to delete the active default — set another profile as default
    first via ``set_default_profile`` to avoid leaving the CLI without a
    default profile.
    """
    adapter = _adapt(config_or_dir)
    target = adapter.profile_path_for(name)
    if not target.exists():
        raise ConfigError(f"Profile '{name}' not found at {target}")

    if read_is_default_profile(target) is True:
        raise ConfigError(
            f"Cannot delete default profile '{name}'. "
            "Set another profile as default first with 'auth profiles set-default <name>'."
        )

    # Under the per-profile-dir layout, ``.env`` lives inside the profile
    # data directory. Removing the data dir removes the .env in one shot.
    scope_name = adapter.profile_data_dir_name()
    profile_data_dir = get_profiles_base_dir(scope_name) / name
    if profile_data_dir.exists():
        shutil.rmtree(profile_data_dir)
    elif target.exists():
        # Custom layouts (e.g., Copilot) where the env file is not inside
        # the data dir — fall back to removing just the env file.
        target.unlink()

    # Legacy in-tool-dir data location for older installs that pre-date
    # the user-data migration.
    tool_dir = getattr(adapter, "tool_dir", None)
    if tool_dir:
        legacy_data_dir = tool_dir / ".profiles" / name
        if legacy_data_dir.exists():
            shutil.rmtree(legacy_data_dir)


def _set_is_default_in_file(env_path: Path, is_default: bool):
    """Set ``IS_DEFAULT_PROFILE`` value in ``env_path`` (in-place if present)."""
    value = "1" if is_default else "0"
    try:
        content = env_path.read_text()
    except OSError:
        return

    lines = content.splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.strip().startswith("IS_DEFAULT_PROFILE="):
            new_lines.append(f"IS_DEFAULT_PROFILE={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.insert(0, f"IS_DEFAULT_PROFILE={value}")

    env_path.write_text("\n".join(new_lines) + "\n")

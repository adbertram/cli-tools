"""Profile CRUD operations for canonical CLI-tool auth profiles."""

import shutil
from pathlib import Path
from typing import Union

from .config import (
    _DEFAULT_ROOT_CONFIG_FIELDS,
    _merge_config_values,
    _read_env_values,
    _split_env_values,
    _write_env_values,
    config_env_path_for_tool,
    env_path_for_profile,
    get_profiles_base_dir,
    profile_name_from_path,
    read_is_default_profile,
    list_env_files,
)
from .exceptions import ConfigError


class _ToolDirShim:
    """Adapter exposing canonical profile paths for callers that pass a tool dir."""

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
    """Return something that exposes the canonical profile-discovery hooks."""
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

    Raises ``ConfigError`` if the profile already exists. Non-authentication
    config fields from ``.env.example`` are written to the canonical root
    config file, while auth fields are written to the canonical profile env.
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
        auth_fields = (
            adapter._auth_field_names()
            if hasattr(adapter, "_auth_field_names")
            else set()
        )
        root_config_fields = (
            adapter._root_config_field_names()
            if hasattr(adapter, "_root_config_field_names")
            else set(_DEFAULT_ROOT_CONFIG_FIELDS)
        )
        auth_values, config_values = _split_env_values(
            _read_env_values(example),
            auth_fields,
            root_config_fields,
        )
        auth_values["IS_DEFAULT_PROFILE"] = "0"
        config_path = getattr(
            adapter,
            "config_env_file_path",
            config_env_path_for_tool(adapter.profile_data_dir_name()),
        )
        _merge_config_values(config_path, config_values)
        _write_env_values(target, auth_values)
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

    scope_name = adapter.profile_data_dir_name()
    profile_data_dir = get_profiles_base_dir(scope_name) / name
    if profile_data_dir.exists():
        shutil.rmtree(profile_data_dir)
    elif target.exists():
        target.unlink()


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

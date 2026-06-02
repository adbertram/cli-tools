"""Profile CRUD operations for canonical CLI-tool auth profiles."""

import shutil
from pathlib import Path
from typing import Optional, Union

from .config import (
    _DEFAULT_ROOT_CONFIG_FIELDS,
    _merge_config_values,
    _read_env_values,
    _split_env_values,
    _write_env_values,
    config_env_path_for_tool,
    env_path_for_profile,
    get_profile_auth_settings,
    get_profiles_base_dir,
    implicit_profile_auth_type,
    list_env_files,
    profile_name_from_path,
    read_profile_active,
)
from .exceptions import ConfigError


class ProfileStore:
    """Adapter exposing canonical profile paths for a tool name."""

    def __init__(
        self,
        tool_name: str,
        *,
        tool_dir: Optional[Path] = None,
        profile_auth_settings: Optional[tuple[str, dict]] = None,
    ):
        self.tool_dir = tool_dir
        self._tool_name = tool_name
        self._profile_auth_settings = profile_auth_settings

    def list_profile_paths(self):
        return list_env_files(self._tool_name)

    def profile_path_for(self, name: str):
        return env_path_for_profile(self._tool_name, name)

    def profile_name_for_path(self, path):
        return profile_name_from_path(path)

    def profile_data_dir_name(self) -> str:
        return self._tool_name

    def get_profile_auth_settings(self):
        return self._profile_auth_settings


class _ToolDirShim(ProfileStore):
    """Adapter exposing canonical profile paths for callers that pass a tool dir."""

    def __init__(self, tool_dir: Path):
        super().__init__(tool_dir.name, tool_dir=tool_dir)


def _adapt(config_or_dir) -> Union["BaseConfig", ProfileStore]:
    """Return something that exposes the canonical profile-discovery hooks."""
    if hasattr(config_or_dir, "list_profile_paths"):
        return config_or_dir
    if isinstance(config_or_dir, str):
        return ProfileStore(config_or_dir)
    return _ToolDirShim(Path(config_or_dir))


def _profile_auth_settings(subject) -> Optional[tuple[str, dict]]:
    if hasattr(subject, "get_profile_auth_settings"):
        settings = subject.get_profile_auth_settings()
        if settings is not None:
            return settings
    return get_profile_auth_settings(subject)


def _profile_auth_type(subject, env_path: Path) -> str:
    settings = _profile_auth_settings(subject)
    if settings is None:
        return implicit_profile_auth_type()
    auth_type_field, auth_types = settings
    auth_type = _read_env_values(env_path).get(auth_type_field, "").strip()
    if not auth_type:
        raise ConfigError(
            f"Profile '{profile_name_from_path(env_path)}' is missing {auth_type_field}. "
            "Recreate the profile with 'auth profiles create'."
        )
    if auth_type not in auth_types:
        raise ConfigError(
            f"Profile '{profile_name_from_path(env_path)}' has invalid auth type {auth_type!r}. "
            f"Valid types: {', '.join(sorted(auth_types))}."
        )
    return auth_type


def _resolve_created_profile_auth_type(subject, provided_auth_type: Optional[str]) -> str:
    settings = _profile_auth_settings(subject)
    if settings is None:
        return implicit_profile_auth_type()

    auth_type_field, auth_types = settings
    if provided_auth_type:
        if provided_auth_type not in auth_types:
            raise ConfigError(
                f"Unknown auth type '{provided_auth_type}'. Valid types: {', '.join(sorted(auth_types))}."
            )
        return provided_auth_type

    if len(auth_types) == 1:
        return next(iter(auth_types))

    example = (getattr(subject, "tool_dir", None) or Path(".")) / ".env.example"
    if example.exists():
        example_auth_type = _read_env_values(example).get(auth_type_field, "").strip()
        if example_auth_type:
            if example_auth_type not in auth_types:
                raise ConfigError(
                    f"{example} declares invalid {auth_type_field}={example_auth_type!r}. "
                    f"Valid types: {', '.join(sorted(auth_types))}."
                )
            return example_auth_type

    raise ConfigError(
        "Profile auth type is required. Create the profile with "
        "'auth profiles create <name> --auth-type <type>'."
    )


def _count_active_profiles_for_auth_type(subject, auth_type: str) -> int:
    count = 0
    for env_path in subject.list_profile_paths():
        if read_profile_active(env_path) is not True:
            continue
        if _profile_auth_type(subject, env_path) == auth_type:
            count += 1
    return count


def _set_profile_active_in_file(env_path: Path, active: bool):
    value = "true" if active else "false"
    content = env_path.read_text() if env_path.exists() else ""
    lines = content.splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.strip().startswith("ACTIVE="):
            new_lines.append(f"ACTIVE={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.insert(0, f"ACTIVE={value}")
    env_path.write_text("\n".join(new_lines) + "\n")


def list_profiles(config_or_dir: Union["BaseConfig", Path, str]) -> list:
    """List all profiles known to the active config (or tool dir)."""
    subject = _adapt(config_or_dir)
    profiles = []
    for path in subject.list_profile_paths():
        profiles.append(
            {
                "name": subject.profile_name_for_path(path),
                "file": path.name,
                "auth_type": _profile_auth_type(subject, path),
                "active": bool(read_profile_active(path)),
            }
        )
    return profiles


def create_profile(config_or_dir, name: str, auth_type: Optional[str] = None) -> Path:
    """Create a new profile by copying ``.env.example``."""
    subject = _adapt(config_or_dir)
    target = subject.profile_path_for(name)
    if target.exists():
        raise ConfigError(f"Profile '{name}' already exists at {target}")

    target.parent.mkdir(parents=True, exist_ok=True)

    resolved_auth_type = _resolve_created_profile_auth_type(subject, auth_type)
    active = _count_active_profiles_for_auth_type(subject, resolved_auth_type) == 0

    tool_dir = getattr(subject, "tool_dir", None)
    example = (tool_dir / ".env.example") if tool_dir else None
    if example is not None and example.exists():
        auth_fields = (
            subject._auth_field_names()
            if hasattr(subject, "_auth_field_names")
            else set()
        )
        root_config_fields = (
            subject._root_config_field_names()
            if hasattr(subject, "_root_config_field_names")
            else set(_DEFAULT_ROOT_CONFIG_FIELDS)
        )
        auth_values, config_values = _split_env_values(
            _read_env_values(example),
            auth_fields,
            root_config_fields,
        )
        settings = _profile_auth_settings(subject)
        if settings is not None:
            auth_type_field, _auth_types = settings
            auth_values[auth_type_field] = resolved_auth_type
        auth_values["ACTIVE"] = "true" if active else "false"
        config_path = getattr(
            subject,
            "config_env_file_path",
            config_env_path_for_tool(subject.profile_data_dir_name()),
        )
        _merge_config_values(config_path, config_values)
        _write_env_values(target, auth_values)
    else:
        _write_env_values(
            target,
            {
                "ACTIVE": "true" if active else "false",
            },
        )

    return target


def select_profile(config_or_dir, name: str):
    """Activate ``name`` within its auth type only."""
    subject = _adapt(config_or_dir)
    target = subject.profile_path_for(name)
    if not target.exists():
        raise ConfigError(f"Profile '{name}' not found at {target}")

    target_auth_type = _profile_auth_type(subject, target)
    for env_path in subject.list_profile_paths():
        if _profile_auth_type(subject, env_path) != target_auth_type:
            continue
        _set_profile_active_in_file(env_path, env_path == target)


def delete_profile(config_or_dir, name: str):
    """Delete a profile and any per-profile runtime data."""
    subject = _adapt(config_or_dir)
    target = subject.profile_path_for(name)
    if not target.exists():
        raise ConfigError(f"Profile '{name}' not found at {target}")

    target_auth_type = _profile_auth_type(subject, target)
    if read_profile_active(target) is True:
        active_count = _count_active_profiles_for_auth_type(subject, target_auth_type)
        if active_count <= 1:
            raise ConfigError(
                f"Cannot delete active profile '{name}'. "
                f"Select another {target_auth_type} profile first."
            )

    scope_name = subject.profile_data_dir_name()
    profile_data_dir = get_profiles_base_dir(scope_name) / name
    if profile_data_dir.exists():
        shutil.rmtree(profile_data_dir)
    elif target.exists():
        target.unlink()

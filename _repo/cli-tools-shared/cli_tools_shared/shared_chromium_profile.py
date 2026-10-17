"""Safe one-time seeding for the shared Chromium user-data directory."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .browser.processes import (
    CHROMIUM_PROFILE_RUNTIME_ARTIFACTS,
    ProcessTableUnavailableError,
    profile_process_pids,
)
from .exceptions import ConfigError


_COOKIES_PATH = Path("Default") / "Cookies"


def chromium_profile_has_cookies(profile_dir: Path) -> bool:
    """Return whether a Chromium user-data directory has a Cookies database."""
    return (Path(profile_dir) / _COOKIES_PATH).is_file()


def get_shared_chromium_profile_seed_guidance(
    config: object,
    cli_name: str | None = None,
) -> str | None:
    """Return validated seed guidance while supporting legacy config objects."""
    guidance_fn = getattr(config, "shared_chromium_profile_seed_guidance", None)
    guidance = guidance_fn(cli_name) if callable(guidance_fn) else None
    return guidance if isinstance(guidance, str) and guidance else None


def _assert_profile_is_not_in_use(profile_dir: Path) -> None:
    """Refuse a copy while Chrome owns the source or destination profile."""
    try:
        pids = profile_process_pids(profile_dir)
    except ProcessTableUnavailableError as exc:
        raise ConfigError(
            "Cannot seed the shared Chromium profile because this host cannot "
            "inspect Chrome processes. Close Chrome and run the command from a "
            "shell that can inspect local processes."
        ) from exc
    if pids:
        raise ConfigError(
            "Cannot seed the shared Chromium profile while Chrome is using "
            f"{profile_dir} (PID(s): {', '.join(str(pid) for pid in pids)}). "
            "Close Chrome and retry."
        )


def seed_shared_chromium_profile(source: Path, target: Path) -> Path:
    """Copy one verified legacy profile into an empty shared target safely.

    The operation never merges or overwrites a populated shared directory.
    It also rejects live Chrome owners and omits stale singleton artifacts that
    cannot safely move between Chromium profile directories.
    """
    source = Path(source)
    target = Path(target)
    if not chromium_profile_has_cookies(source):
        raise ConfigError(
            f"Cannot seed the shared Chromium profile: source has no Cookies "
            f"database at {source / _COOKIES_PATH}."
        )

    try:
        same_profile = source.resolve() == target.resolve()
    except OSError as exc:
        raise ConfigError(
            "Cannot resolve the source and shared Chromium profile paths before seeding."
        ) from exc
    if same_profile:
        raise ConfigError(
            "Cannot seed the shared Chromium profile from itself. Choose a CLI "
            "with a separate, known-good legacy browser-data profile."
        )

    if target.exists() or target.is_symlink():
        if not target.is_dir() or target.is_symlink():
            raise ConfigError(
                f"Cannot seed the shared Chromium profile because the destination "
                f"is not an empty directory: {target}."
            )
        if any(target.iterdir()):
            raise ConfigError(
                f"Cannot seed the shared Chromium profile because the destination "
                f"is not empty: {target}. Refusing to overwrite or merge profiles."
            )

    _assert_profile_is_not_in_use(source)
    _assert_profile_is_not_in_use(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{target.name}.seed-", dir=target.parent))
    staged_profile = staging_root / target.name
    try:
        shutil.copytree(
            source,
            staged_profile,
            symlinks=True,
            ignore=shutil.ignore_patterns(*CHROMIUM_PROFILE_RUNTIME_ARTIFACTS),
        )
        if not chromium_profile_has_cookies(staged_profile):
            raise ConfigError(
                "Cannot seed the shared Chromium profile because the copied "
                "profile has no Cookies database."
            )
        if target.exists() or target.is_symlink():
            if not target.is_dir() or target.is_symlink() or any(target.iterdir()):
                raise ConfigError(
                    f"Cannot seed the shared Chromium profile because the destination "
                    f"became populated: {target}. Refusing to overwrite or merge profiles."
                )
            target.rmdir()
        try:
            staged_profile.replace(target)
        except OSError as exc:
            raise ConfigError(
                f"Failed to activate the seeded shared Chromium profile at {target}: {exc}"
            ) from exc
        return target
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

"""Deterministic auth-profile fixtures for CLI tool tests."""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AuthProfileSeed:
    name: str
    active: bool
    env_body: str = ""
    browser_session: bool = False


@dataclass(frozen=True)
class AuthProfilePaths:
    profile_dir: Path
    env_file: Path
    browser_data_dir: Path
    persistent_profile_dir: Path
    cookies_file: Path


def seed_auth_profile(
    base_profiles_dir: Path,
    name: str,
    *,
    active: bool,
    env_body: str = "",
    browser_session: bool = False,
) -> AuthProfilePaths:
    """Create one profile state for auth status tests."""
    profile_dir = base_profiles_dir / name
    env_file = profile_dir / ".env"
    browser_data_dir = profile_dir / "browser-data"
    persistent_profile_dir = browser_data_dir / "chromium-profile"
    cookies_file = persistent_profile_dir / "Default" / "Cookies"

    profile_dir.mkdir(parents=True, exist_ok=True)
    env_file.write_text(_profile_env(active=active, env_body=env_body))
    if browser_session:
        cookies_file.parent.mkdir(parents=True, exist_ok=True)
        cookies_file.write_text("sqlite-stub")

    return AuthProfilePaths(
        profile_dir=profile_dir,
        env_file=env_file,
        browser_data_dir=browser_data_dir,
        persistent_profile_dir=persistent_profile_dir,
        cookies_file=cookies_file,
    )


def seed_auth_profiles(
    base_profiles_dir: Path,
    profiles: Iterable[AuthProfileSeed],
) -> list[AuthProfilePaths]:
    """Create a deterministic authentication matrix."""
    return [
        seed_auth_profile(
            base_profiles_dir,
            profile.name,
            active=profile.active,
            env_body=profile.env_body,
            browser_session=profile.browser_session,
        )
        for profile in profiles
    ]


def _profile_env(*, active: bool, env_body: str) -> str:
    active_value = "true" if active else "false"
    body = env_body
    if body and not body.endswith("\n"):
        body = f"{body}\n"
    return f"ACTIVE={active_value}\n{body}"
